"""Durable, authenticated execution history and resumable SSE."""

import asyncio
import json
import time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from panoptes_contracts.sources import SourceId
from panoptes_database.session import unit_of_work
from sqlalchemy import text

router = APIRouter(prefix="/extraction-logs", tags=["extraction-logs"])
Level = Literal["INFO", "WARNING", "ERROR"]


async def read_logs(
    sessions,
    *,
    after=0,
    before=None,
    request_id=None,
    site=None,
    level=None,
    limit=200,
    latest=False,
):
    async with unit_of_work(sessions) as session:
        rows = (
            (
                await session.execute(
                    text("""
            SELECT l.id,r.public_id AS request_id,l.correlation_id,l.site,l.level,
              l.event,l.message,l.details,l.created_at
            FROM scraping.extraction_log l
            JOIN scraping.scrape_request r ON r.id=l.request_id
            WHERE l.id>:after AND (CAST(:before AS bigint) IS NULL OR l.id<:before)
              AND (CAST(:request_id AS uuid) IS NULL OR r.public_id=:request_id)
              AND (CAST(:site AS text) IS NULL OR l.site=:site)
              AND (CAST(:level AS text) IS NULL OR l.level=:level)
            ORDER BY CASE WHEN :latest THEN -l.id ELSE l.id END LIMIT :limit
        """),
                    {
                        "after": after,
                        "before": before,
                        "request_id": request_id,
                        "site": site,
                        "level": level,
                        "limit": limit,
                        "latest": latest,
                    },
                )
            )
            .mappings()
            .all()
        )
    items = [dict(row) for row in rows]
    return list(reversed(items)) if latest else items


@router.get("")
async def history(
    request: Request,
    request_id: UUID | None = None,
    site: SourceId | None = None,
    level: Level | None = None,
    before: int | None = Query(None, ge=1),
    limit: int = Query(200, ge=1, le=500),
):
    items = await read_logs(
        request.app.state.sessions,
        request_id=request_id,
        site=site,
        level=level,
        before=before,
        limit=limit + 1,
        latest=True,
    )
    has_more = len(items) > limit
    items = items[-limit:]
    return {
        "items": items,
        "cursor": max((row["id"] for row in items), default=0),
        "has_more": has_more,
    }


def event_frame(row):
    return f"id: {row['id']}\nevent: log\ndata: {json.dumps(row, default=str, ensure_ascii=False)}\n\n"


async def stream_logs(request, cursor, filters, *, duration=45, pause=asyncio.sleep):
    yield "retry: 3000\n\n"
    deadline = time.monotonic() + duration
    heartbeat_at = time.monotonic()
    while time.monotonic() < deadline:
        if await request.is_disconnected():
            return
        rows = await read_logs(
            request.app.state.sessions, after=cursor, limit=200, **filters
        )
        for row in rows:
            yield event_frame(row)
            cursor = row["id"]
        if time.monotonic() - heartbeat_at >= 10:
            yield ": heartbeat\n\n"
            heartbeat_at = time.monotonic()
        if len(rows) < 200:
            await pause(1)


@router.get("/stream")
async def stream(
    request: Request,
    after: int = Query(0, ge=0, le=9223372036854775807),
    request_id: UUID | None = None,
    site: SourceId | None = None,
    level: Level | None = None,
):
    supplied = request.headers.get("Last-Event-ID")
    if supplied:
        try:
            last = int(supplied)
            if not 0 <= last <= 9223372036854775807:
                raise ValueError()
            after = max(after, last)
        except ValueError:
            raise HTTPException(422, "Cursor de eventos inválido.") from None
    # Periodic reconnect rechecks authentication and rotates frontend cookies.
    return StreamingResponse(
        stream_logs(
            request, after, {"request_id": request_id, "site": site, "level": level}
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
