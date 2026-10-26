"""Authenticated extension jobs. Cookies and browser profiles remain local."""

import asyncio
import re
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import HTTPException
from panoptes_contracts.sources import SOURCES, captcha_page, login_page
from pydantic import BaseModel, Field, SecretStr


def page_allowed(site, url):
    try:
        parts = urlsplit(url)
        return (
            parts.scheme == "https"
            and parts.hostname in SOURCES[site].page_hosts
            and parts.port in (None, 443)
            and not parts.username
            and not parts.password
        )
    except ValueError:
        return False


class Agent(BaseModel):
    model_config = {"extra": "forbid"}
    agent_id: UUID


class Result(Agent):
    job_id: UUID
    final_url: str = Field(max_length=2048)
    body: SecretStr = Field(default=SecretStr(""), max_length=6_000_000)
    blocked: bool = False


class LocalCollector:
    def __init__(self):
        self.agents = {}
        self.jobs = {}

    def online(self, site):
        agent = self.agents.get(site)
        return bool(agent and time.monotonic() - agent["seen"] < 90)

    def start(self, site, agent_id):
        self.stop(site)
        self.agents[site] = {"id": agent_id, "seen": time.monotonic()}

    def stop(self, site):
        self.agents.pop(site, None)
        for job in list(self.jobs.values()):
            if job["site"] == site and not job["future"].done():
                job["future"].set_result({"blocked": "local_browser_unavailable"})

    def next(self, site, agent_id):
        agent = self.agents.get(site)
        if not agent or agent["id"] != agent_id:
            raise HTTPException(409, "Ative novamente a coleta na extensão.")
        agent["seen"] = time.monotonic()
        if any(
            j["site"] == site and j["claimed"] and not j["future"].done()
            for j in self.jobs.values()
        ):
            return {"job_id": None}
        for key, job in self.jobs.items():
            if job["site"] == site and not job["claimed"] and not job["future"].done():
                job["claimed"] = agent_id
                return {"job_id": str(key), "url": job["url"]}
        return {"job_id": None}

    async def fetch(self, site, url, timeout=55):
        if not self.online(site):
            return {"blocked": "local_browser_unavailable"}
        key = uuid4()
        future = asyncio.get_running_loop().create_future()
        self.jobs[key] = {"site": site, "url": url, "future": future, "claimed": None}
        try:
            return await asyncio.wait_for(future, timeout)
        except TimeoutError:
            return {"blocked": "local_browser_timeout"}
        finally:
            self.jobs.pop(key, None)

    def complete(self, site, value):
        job = self.jobs.get(value.job_id)
        agent = self.agents.get(site)
        if (
            not job
            or job["site"] != site
            or job["future"].done()
            or job["claimed"] != value.agent_id
            or not agent
            or agent["id"] != value.agent_id
        ):
            raise HTTPException(409, "Coleta encerrada ou pertencente a outra conexão.")
        agent["seen"] = time.monotonic()
        body = value.body.get_secret_value()
        if not page_allowed(site, value.final_url):
            raise HTTPException(422, "URL fora da fonte permitida.")
        if len(body.encode()) > 6_000_000:
            raise HTTPException(413, "Página excede o limite de captura.")
        path = urlsplit(value.final_url).path.lower()
        if captcha_page(value.final_url, body):
            result = {"blocked": "verification_required", "cause": "captcha"}
        elif login_page(value.final_url, body) or any(
            p in path for p in ("/login", "/ap/", "/auth/", "/account-verification")
        ):
            result = {"blocked": "reconnect_required"}
        elif re.search(r"<input\b[^>]*\btype\s*=\s*[\"\x27]?password\b", body, re.I):
            result = {"blocked": "reconnect_required"}
        elif value.blocked:
            result = {"blocked": "local_browser_error"}
        elif not body:
            raise HTTPException(422, "A captura não contém HTML.")
        else:
            # 200 represents a successful DOM capture, not a measured HTTP status.
            result = {
                "body": body,
                "final_url": value.final_url,
                "status": 200,
                "media_type": "text/html",
                "capture_mode": "browser_local",
            }
        job["future"].set_result(result)
        return {"ok": True}
