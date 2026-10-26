import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from panoptes_storage.client import create_storage, ensure_bucket, load_storage_settings

from .audit import audit_loop, flush_audits
from .client import OpenRouter
from .registry import model_sync_loop, sync_agents


@asynccontextmanager
async def ai_runtime(sessions):
    """Application startup synchronizes disk agents before accepting requests."""
    await sync_agents(sessions)
    settings = load_storage_settings()
    async with (
        httpx.AsyncClient(timeout=30) as http,
        create_storage(settings) as storage,
    ):
        await ensure_bucket(storage, settings.bucket)
        tasks = [
            asyncio.create_task(model_sync_loop(sessions, http)),
            asyncio.create_task(audit_loop(sessions, storage, settings.bucket)),
        ]
        try:
            yield OpenRouter(sessions, http)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await flush_audits(sessions, storage, settings.bucket)
            except Exception:
                logging.getLogger(__name__).exception(
                    "AI audits remain queued for next startup"
                )
