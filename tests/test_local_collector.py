import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth.router import current_user
from panoptes_backend.browser.local import LocalCollector, Result, page_allowed
from panoptes_backend.browser.service import BrowserConnections
from panoptes_backend.main import create_app

SITE = "mercado_livre_br"
URL = "https://lista.mercadolivre.com.br/sofa"


async def claim(collector, agent):
    for _ in range(20):
        await asyncio.sleep(0)
        job = collector.next(SITE, agent)
        if job["job_id"]:
            return job
    pytest.fail("Job was not queued")


async def test_local_job_uses_same_pipeline_without_transferring_cookies():
    collector = LocalCollector()
    agent = uuid4()
    collector.start(SITE, agent)
    task = asyncio.create_task(collector.fetch(SITE, URL))
    job = await claim(collector, agent)
    assert job["url"] == URL
    assert collector.next(SITE, agent)["job_id"] is None
    with pytest.raises(HTTPException):
        collector.complete(
            SITE,
            Result(agent_id=uuid4(), job_id=job["job_id"], final_url=URL, body="wrong"),
        )
    with pytest.raises(HTTPException):
        collector.complete(
            SITE,
            Result(
                agent_id=agent,
                job_id=job["job_id"],
                final_url="https://evil.test/",
                body="wrong",
            ),
        )
    collector.complete(
        SITE,
        Result(
            agent_id=agent,
            job_id=job["job_id"],
            final_url=URL,
            body="<html>results</html>",
        ),
    )
    result = await task
    assert result["capture_mode"] == "browser_local"
    assert result["body"] == "<html>results</html>"
    assert not collector.jobs
    with pytest.raises(HTTPException):
        collector.complete(
            SITE,
            Result(agent_id=agent, job_id=job["job_id"], final_url=URL, body="late"),
        )


async def test_captcha_and_login_content_are_never_returned_to_worker():
    collector = LocalCollector()
    agent = uuid4()
    collector.start(SITE, agent)
    for url, html, reason in [
        (
            "https://www.mercadolivre.com.br/captcha/wall/logged",
            "secret form",
            "verification_required",
        ),
        (
            "https://www.mercadolivre.com.br/login/identification",
            "secret login",
            "reconnect_required",
        ),
    ]:
        task = asyncio.create_task(collector.fetch(SITE, URL))
        job = await claim(collector, agent)
        collector.complete(
            SITE, Result(agent_id=agent, job_id=job["job_id"], final_url=url, body=html)
        )
        result = await task
        assert result["blocked"] == reason
        assert "secret" not in str(result)


async def test_disconnect_timeout_and_offline_never_fall_back_to_http():
    collector = LocalCollector()
    assert await collector.fetch(SITE, URL) == {"blocked": "local_browser_unavailable"}
    agent = uuid4()
    collector.start(SITE, agent)
    task = asyncio.create_task(collector.fetch(SITE, URL))
    await claim(collector, agent)
    collector.stop(SITE)
    assert await task == {"blocked": "local_browser_unavailable"}
    collector.start(SITE, agent)
    assert await collector.fetch(SITE, URL, timeout=0.001) == {
        "blocked": "local_browser_timeout"
    }
    assert not collector.jobs


async def test_backend_local_routes_require_admin_and_dispatch_without_chromium(
    tmp_path,
):
    app = create_app()
    instance = BrowserConnections(tmp_path, Fernet.generate_key().decode())
    app.state.browser_connections = instance
    agent = str(uuid4())
    prefix = f"/browser-connections/{SITE}/local"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post(prefix + "/start", json={"agent_id": agent})
        ).status_code == 401
        app.dependency_overrides[current_user] = lambda: {"email": "user@example.com"}
        assert (
            await client.post(prefix + "/start", json={"agent_id": agent})
        ).status_code == 403
        app.dependency_overrides[current_user] = lambda: {"email": "admin@panoptes.com"}
        response = await client.post(prefix + "/start", json={"agent_id": agent})
        assert response.json()["connection_method"] == "local_extension"
        assert not instance.browsers
        task = asyncio.create_task(instance.fetch(SITE, URL))
        await asyncio.sleep(0)
        job = (await client.post(prefix + "/next", json={"agent_id": agent})).json()
        assert job["url"] == URL
        response = await client.post(
            prefix + "/result",
            json={
                "agent_id": agent,
                "job_id": job["job_id"],
                "final_url": URL,
                "body": "<p>Results</p>",
            },
        )
        assert response.status_code == 200
        assert (await task)["capture_mode"] == "browser_local"
        await client.delete(f"/browser-connections/{SITE}")
        assert (await instance.status(SITE))["status"] == "disconnected"
        assert (
            await client.post(prefix + "/next", json={"agent_id": agent})
        ).status_code == 409


@pytest.mark.parametrize(
    "url",
    [
        "http://lista.mercadolivre.com.br/",
        "https://lista.mercadolivre.com.br.evil.test/",
        "https://user:pass@lista.mercadolivre.com.br/",
        "https://lista.mercadolivre.com.br:444/",
        "https://www.amazon.com.br/",
    ],
)
def test_local_capture_origin_boundaries(url):
    assert not page_allowed(SITE, url)


async def test_switching_to_docker_stops_local_jobs_and_blocks_workers_during_login(
    tmp_path,
):
    instance = BrowserConnections(tmp_path, Fernet.generate_key().decode())
    await instance.start_local(SITE, uuid4())
    entry = {"interactive": False}
    instance.context = AsyncMock(return_value=entry)
    instance.navigate = AsyncMock()
    instance.live[SITE] = entry
    assert (await instance.connect(SITE))["status"] == "connecting"
    assert not instance.local.online(SITE)
    assert instance.read(SITE)["connection_method"] == "browser"
    assert await instance.fetch(SITE, URL) == {"blocked": "connection_in_progress"}


def test_html_is_secret_in_validation_and_model_representation():
    value = Result(agent_id=uuid4(), job_id=uuid4(), final_url=URL, body="private-page")
    assert "private-page" not in repr(value)
