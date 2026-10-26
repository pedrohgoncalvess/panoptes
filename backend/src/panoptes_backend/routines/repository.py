import json

from sqlalchemy import text

FIELDS = """r.public_id,r.name,t.public_id AS search_term_id,t.term,t.site,r.mode,r.schedule,r.enabled,r.next_run_at,r.created_at,
 ARRAY(SELECT st.site FROM scraping.routine_search_term rt
 JOIN scraping.search_term st ON st.id=rt.search_term_id WHERE rt.routine_id=r.id ORDER BY st.site) AS sites"""


async def insert(session, value, term_id, public_id, next_run_at):
    await session.execute(
        text("""INSERT INTO "scraping"."scheduled_routine"
        (public_id,name,search_term_id,mode,schedule,enabled,next_run_at)
        VALUES (:pid,:name,:term,:mode,CAST(:schedule AS jsonb),:enabled,:next)"""),
        {
            "pid": public_id,
            "name": value.name,
            "term": term_id,
            "mode": value.mode,
            "schedule": value.schedule.model_dump_json(),
            "enabled": value.enabled,
            "next": next_run_at,
        },
    )
    await set_terms(session, public_id, [term_id])


async def set_terms(session, public_id, term_ids):
    await session.execute(
        text("""DELETE FROM scraping.routine_search_term
        WHERE routine_id=(SELECT id FROM scraping.scheduled_routine WHERE public_id=:pid)"""),
        {"pid": public_id},
    )
    await session.execute(
        text("""INSERT INTO scraping.routine_search_term (routine_id,search_term_id)
        SELECT r.id,term_id FROM scraping.scheduled_routine r,
        unnest(CAST(:terms AS bigint[])) AS term_id WHERE r.public_id=:pid"""),
        {"pid": public_id, "terms": term_ids},
    )


async def read(session, public_id):
    return (
        (
            await session.execute(
                text(f"""SELECT {FIELDS} FROM "scraping"."scheduled_routine" r
        JOIN "scraping"."search_term" t ON t.id=r.search_term_id WHERE r.public_id=:pid"""),
                {"pid": public_id},
            )
        )
        .mappings()
        .one_or_none()
    )


async def list_routines(session, limit, offset, scheduled=False):
    from ..auth.mcp_policy import bindings, key_for

    where = "WHERE r.enabled" if scheduled else ""
    params = {"limit": limit, "offset": offset}
    key = key_for(session)
    if key:
        where += (
            (" AND " if where else " WHERE ")
            + """EXISTS (
          SELECT 1 FROM auth.mcp_key_routine kr WHERE kr.routine_id=r.id AND kr.key_id=:mcp_key)
          AND NOT EXISTS (SELECT 1 FROM scraping.routine_search_term rt
            JOIN scraping.search_term st ON st.id=rt.search_term_id
            WHERE rt.routine_id=r.id AND NOT(st.site=ANY(CAST(:mcp_sites AS text[]))))"""
        )
        params.update(bindings(key))
    order = "r.next_run_at,r.id" if scheduled else "r.id"
    return (
        (
            await session.execute(
                text(f"""SELECT {FIELDS} FROM "scraping"."scheduled_routine" r
        JOIN "scraping"."search_term" t ON t.id=r.search_term_id {where}
        ORDER BY {order} LIMIT :limit OFFSET :offset"""),
                params,
            )
        )
        .mappings()
        .all()
    )


async def advance(session, public_id, next_run_at):
    return (
        await session.execute(
            text("""UPDATE "scraping"."scheduled_routine" SET next_run_at=now()
            WHERE public_id=:pid AND enabled AND next_run_at=:expected
            AND next_run_at > now() RETURNING public_id"""),
            {"pid": public_id, "expected": next_run_at},
        )
    ).scalar_one_or_none()


async def update(session, public_id, value, next_run_at):
    await session.execute(
        text("""UPDATE "scraping"."scheduled_routine" SET name=:name,
        schedule=CAST(:schedule AS jsonb),enabled=:enabled,next_run_at=:next WHERE public_id=:pid"""),
        {
            "pid": public_id,
            "name": value.name,
            "schedule": json.dumps(value.schedule.model_dump()),
            "enabled": value.enabled,
            "next": next_run_at,
        },
    )


async def delete(session, public_id):
    await session.execute(
        text('DELETE FROM "scraping"."scheduled_routine" WHERE public_id=:pid'),
        {"pid": public_id},
    )
