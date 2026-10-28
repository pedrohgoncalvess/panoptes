"""Async Amazon discovery and recurring product refresh executor."""

import argparse
import asyncio
import json
import os
import signal

import httpx
from panoptes_ai.audit import audit_loop
from panoptes_ai.client import OpenRouter
from panoptes_database.config import load_database_settings
from panoptes_database.session import create_database, unit_of_work
from panoptes_storage.client import create_storage, ensure_bucket, load_storage_settings
from sqlalchemy import text

from .infrastructure.browser import BrowserClient
from .infrastructure.commerce_llm import CommerceLLM
from .infrastructure.events import DatabaseEvents
from .infrastructure.selection_llm import ProductClassifier
from .normalization import normalization_loop
from .taxonomy import taxonomy_loop
from .workflow.runner import run, schedule_loop
from .workflow.service import WorkflowResources


async def main(once=False):
    engine, sessions = create_database(load_database_settings())
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    browser = None
    if os.getenv("BROWSER_SERVICE_URL"):
        token = os.getenv("BROWSER_SERVICE_TOKEN", "")
        if not token:
            raise ValueError(
                "BROWSER_SERVICE_TOKEN is required with BROWSER_SERVICE_URL"
            )
        browser = BrowserClient(os.environ["BROWSER_SERVICE_URL"], token)
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    try:
        async with unit_of_work(sessions) as session:
            await session.execute(text("SELECT 1"))
        settings = load_storage_settings()
        interval = float(os.getenv("AMAZON_REQUEST_INTERVAL_SECONDS", "1.5"))
        if interval < 0.1:
            raise ValueError("AMAZON_REQUEST_INTERVAL_SECONDS must be >= 0.1")
        async with (
            create_storage(settings) as storage,
            httpx.AsyncClient(
                timeout=30,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/134.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "pt-BR,pt;q=0.9",
                },
            ) as http,
            httpx.AsyncClient(timeout=25) as commerce_http,
        ):
            await ensure_bucket(storage, settings.bucket)
            resources = WorkflowResources(
                sessions,
                storage,
                settings.bucket,
                http,
                asyncio.Lock(),
                interval,
                browser,
                DatabaseEvents(sessions),
                CommerceLLM(OpenRouter(sessions, commerce_http)),
                ProductClassifier(OpenRouter(sessions, commerce_http)),
            )
            print(
                json.dumps({"event": "worker_ready", "mode": "multi_source"}),
                flush=True,
            )
            task = asyncio.create_task(run(resources, stop, once=once))
            stopping = asyncio.create_task(stop.wait())
            tasks = [
                task,
                stopping,
                asyncio.create_task(audit_loop(sessions, storage, settings.bucket)),
            ]
            if not once:
                tasks.append(
                    asyncio.create_task(
                        taxonomy_loop(
                            sessions, OpenRouter(sessions, commerce_http), stop
                        )
                    )
                )
                tasks.append(asyncio.create_task(schedule_loop(sessions, stop, browser)))
                tasks.append(
                    asyncio.create_task(
                        normalization_loop(
                            sessions, OpenRouter(sessions, commerce_http), stop
                        )
                    )
                )
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for running in tasks:
                    if running.done():
                        await running
            finally:
                for running in tasks:
                    running.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        if browser:
            await browser.close()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    asyncio.run(main(parser.parse_args().once))
