"""Durable asynchronous S3 delivery; safe to run in multiple processes."""

import asyncio
import hashlib
import json
import logging

from panoptes_database.session import unit_of_work
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def flush_audits(sessions, storage, bucket):
    # SKIP LOCKED lets workers share the outbox. An interrupted transaction retries
    # the same deterministic key, including a crash after S3 accepted the upload.
    async with unit_of_work(sessions) as session:
        rows = (
            (
                await session.execute(
                    text("""
            SELECT o.*,i.public_id FROM ai.audit_outbox o
            JOIN ai.interaction i ON i.id=o.interaction_id
            WHERE o.available_at<=now() ORDER BY o.available_at
            LIMIT 10 FOR UPDATE OF o SKIP LOCKED
        """)
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            body = json.dumps(
                row["payload"], ensure_ascii=False, sort_keys=True
            ).encode()
            digest = hashlib.sha256(body).hexdigest()
            key = f"ai/interactions/{row['public_id']}.json"
            try:
                await storage.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=body,
                    ContentType="application/json",
                    Metadata={"sha256": digest},
                )
            except Exception as exc:
                logger.warning(
                    "AI audit upload failed for %s: %s",
                    row["public_id"],
                    type(exc).__name__,
                )
                await session.execute(
                    text("""
                    UPDATE ai.audit_outbox SET attempts=attempts+1,last_error=:error,
                        available_at=now()+make_interval(secs=>:delay) WHERE interaction_id=:id
                """),
                    {
                        "id": row["interaction_id"],
                        "error": type(exc).__name__,
                        "delay": min(3600, 5 * 2 ** min(row["attempts"], 10)),
                    },
                )
                continue
            await session.execute(
                text("""
                UPDATE ai.interaction SET audit_bucket=:bucket,audit_object_key=:key,
                    audit_sha256=:sha,audit_uploaded_at=now() WHERE id=:id
            """),
                {
                    "id": row["interaction_id"],
                    "bucket": bucket,
                    "key": key,
                    "sha": digest,
                },
            )
            await session.execute(
                text("DELETE FROM ai.audit_outbox WHERE interaction_id=:id"),
                {"id": row["interaction_id"]},
            )
    return len(rows)


async def audit_loop(sessions, storage, bucket):
    while True:
        try:
            count = await flush_audits(sessions, storage, bucket)
        except Exception:
            logger.exception("AI audit delivery failed; will retry")
            count = 0
        await asyncio.sleep(0 if count == 10 else 5)
