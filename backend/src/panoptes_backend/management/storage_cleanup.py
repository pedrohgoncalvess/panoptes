"""Retry physical removal after the data deletion transaction commits."""

import asyncio
import logging

from panoptes_database.session import unit_of_work
from panoptes_storage.client import create_storage, load_storage_settings
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def flush(sessions, storage):
    async with unit_of_work(sessions) as session:
        rows = (
            (
                await session.execute(
                    text("""
          SELECT * FROM scraping.asset_deletion ORDER BY created_at
          LIMIT 25 FOR UPDATE SKIP LOCKED
        """)
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            params = {"bucket": row["bucket"], "key": row["object_key"]}
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": row["bucket"] + "/" + row["object_key"]},
            )
            referenced = (
                await session.execute(
                    text("""SELECT EXISTS (
              SELECT 1 FROM scraping.asset WHERE bucket=:bucket AND object_key=:key
              UNION ALL SELECT 1 FROM ai.interaction
                WHERE audit_bucket=:bucket AND audit_object_key=:key
            )"""),
                    params,
                )
            ).scalar_one()
            if not referenced:
                await storage.delete_object(Bucket=row["bucket"], Key=row["object_key"])
            await session.execute(
                text(
                    "DELETE FROM scraping.asset_deletion WHERE bucket=:bucket AND object_key=:key"
                ),
                params,
            )


async def run(sessions):
    while True:
        try:
            async with create_storage(load_storage_settings()) as storage:
                await flush(sessions, storage)
        except Exception:
            logger.exception("Asset deletion failed; queued objects will be retried")
        await asyncio.sleep(10)
