from datetime import UTC, datetime, timedelta

from panoptes_contracts.schedules import RoutineSchedule, next_run
from sqlalchemy import text


async def enqueue_schedules(session):
    rows = (
        (
            await session.execute(
                text("""SELECT * FROM "scraping"."scheduled_routine"
        WHERE enabled AND next_run_at <= now() ORDER BY next_run_at
        LIMIT 50 FOR UPDATE SKIP LOCKED""")
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        if row["mode"] == "discover":
            await session.execute(
                text("""INSERT INTO "scraping"."scrape_request" (mode,search_term_id,routine_public_id)
                SELECT 'discover',search_term_id,CAST(:routine_pid AS UUID) FROM scraping.routine_search_term
                WHERE routine_id=:routine ON CONFLICT DO NOTHING"""),
                {"routine": row["id"], "routine_pid": row["public_id"]},
            )
        else:
            await session.execute(
                text("""INSERT INTO "scraping"."scrape_request" (mode,tracking_target_id,routine_public_id)
                SELECT DISTINCT 'refresh',t.id,CAST(:routine_pid AS UUID) FROM "scraping"."tracking_target" t
                JOIN "scraping"."search_term_entity" e ON e.entity_id=t.entity_id
                JOIN scraping.routine_search_term rt ON rt.search_term_id=e.search_term_id
                WHERE rt.routine_id=:routine AND t.enabled ON CONFLICT DO NOTHING"""),
                {"routine": row["id"], "routine_pid": row["public_id"]},
            )
        schedule = RoutineSchedule.model_validate(row["schedule"])
        now = datetime.now(UTC)
        if schedule.kind == "interval":
            step = timedelta(minutes=schedule.interval_minutes)
            upcoming = (
                row["next_run_at"]
                + (int((now - row["next_run_at"]) // step) + 1) * step
            )
        else:
            upcoming = next_run(schedule, now, str(row["public_id"]))
        await session.execute(
            text(
                """UPDATE "scraping"."scheduled_routine" SET next_run_at=:next WHERE id=:id"""
            ),
            {"id": row["id"], "next": upcoming},
        )
