import json

from sqlalchemy import text


class LeaseLostError(Exception):
    pass


async def enqueue_due(session):
    from .schedules import enqueue_schedules

    await enqueue_schedules(session)


async def claim(session, owner):
    return (
        (
            await session.execute(
                text("""
        WITH ready AS (
            SELECT id FROM "scraping"."scrape_request"
            WHERE status = 'pending' OR (status = 'running' AND lease_expires_at < now())
            ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
        )
        UPDATE "scraping"."scrape_request" r SET status = 'running',
            lease_owner = :owner, lease_expires_at = now() + interval '120 seconds'
        FROM ready WHERE r.id = ready.id RETURNING r.*
    """),
                {"owner": owner},
            )
        )
        .mappings()
        .one_or_none()
    )


async def renew(session, request_id, owner):
    result = await session.execute(
        text("""UPDATE "scraping"."scrape_request"
        SET lease_expires_at = now() + interval '120 seconds'
        WHERE id = :id AND lease_owner = :owner AND status = 'running'
          AND lease_expires_at > now() RETURNING id"""),
        {"id": request_id, "owner": owner},
    )
    if result.scalar_one_or_none() is None:
        raise LeaseLostError()


async def guard(session, request_id, owner):
    result = await session.execute(
        text("""SELECT id FROM "scraping"."scrape_request"
        WHERE id = :id AND lease_owner = :owner AND status = 'running'
          AND lease_expires_at > now() FOR UPDATE"""),
        {"id": request_id, "owner": owner},
    )
    if result.scalar_one_or_none() is None:
        raise LeaseLostError()


async def finish(session, request_id, owner, status, summary):
    await guard(session, request_id, owner)
    await session.execute(
        text("""UPDATE "scraping"."scrape_request" SET status = :status,
        summary = CAST(:summary AS jsonb), completed_at = now(),
        lease_owner = NULL, lease_expires_at = NULL WHERE id = :id"""),
        {"id": request_id, "status": status, "summary": json.dumps(summary)},
    )
    await session.execute(
        text("""UPDATE "scraping"."tracking_target" t
        SET next_poll_at = now() + t.refresh_interval_seconds * interval '1 second',
            enabled = CASE WHEN :pause_tracking THEN false ELSE t.enabled END
        FROM "scraping"."scrape_request" r WHERE r.id = :id
          AND r.mode = 'refresh' AND r.tracking_target_id = t.id"""),
        {
            "id": request_id,
            "pause_tracking": summary.get("tracking_paused", False),
        },
    )


async def read_context(session, request):
    if request["mode"] == "discover":
        row = (
            (
                await session.execute(
                    text('SELECT * FROM "scraping"."search_term" WHERE id = :id'),
                    {"id": request["search_term_id"]},
                )
            )
            .mappings()
            .one()
        )
        return dict(row)
    row = (
        (
            await session.execute(
                text("""SELECT t.*, e.source_key, e.site, e.public_id AS entity_public_id
        FROM "scraping"."tracking_target" t JOIN "scraping"."entity" e ON e.id = t.entity_id
        WHERE t.id = :id"""),
                {"id": request["tracking_target_id"]},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)
