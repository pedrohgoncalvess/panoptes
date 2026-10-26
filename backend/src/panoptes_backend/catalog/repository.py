from sqlalchemy import text


async def insert_term(session, value, normalized):
    await session.execute(
        text("""
        INSERT INTO "scraping"."search_term"
            (site, term, normalized_term, criteria, max_pages_qt, max_candidates_qt, refresh_interval_seconds)
        VALUES (:site, :term, :normalized, CAST(:criteria AS jsonb), :pages, :candidates, :interval)
        ON CONFLICT (site, normalized_term, configuration_key) DO NOTHING
    """),
        {
            "site": value.site,
            "term": value.term.strip(),
            "normalized": normalized,
            "criteria": value.criteria.model_dump_json(),
            "pages": value.max_pages,
            "candidates": value.max_candidates,
            "interval": value.refresh_interval_seconds,
        },
    )
    return (
        (
            await session.execute(
                text("""SELECT * FROM "scraping"."search_term"
        WHERE site = :site AND normalized_term = :normalized AND configuration_key=md5(CAST(:criteria AS jsonb)::text)"""),
                {
                    "site": value.site,
                    "normalized": normalized,
                    "criteria": value.criteria.model_dump_json(),
                },
            )
        )
        .mappings()
        .one()
    )


async def find_term(session, public_id):
    return (
        (
            await session.execute(
                text('SELECT * FROM "scraping"."search_term" WHERE public_id = :id'),
                {"id": public_id},
            )
        )
        .mappings()
        .one_or_none()
    )


async def list_terms(session, limit, offset, *, q=None, site=None):
    from ..auth.mcp_policy import bindings, key_for, term_scope

    key = key_for(session)
    scope = " AND " + term_scope("search_term") if key else ""
    params = {"limit": limit, "offset": offset, "q": q, "site": site}
    if key:
        params.update(bindings(key))
    return (
        (
            await session.execute(
                text(f"""SELECT public_id, site, term, criteria,
        max_pages_qt, max_candidates_qt, refresh_interval_seconds, created_at FROM "scraping"."search_term"
        WHERE (CAST(:site AS text) IS NULL OR site=:site)
          AND (CAST(:q AS text) IS NULL OR position(lower(:q) in lower(term))>0)
        {scope} ORDER BY id DESC LIMIT :limit OFFSET :offset"""),
                params,
            )
        )
        .mappings()
        .all()
    )


async def routine_sources(session, public_id):
    """Only sources requested together in this configuration's first extraction."""
    return (
        (
            await session.execute(
                text("""
        WITH original AS (
          SELECT normalized_term, configuration_key FROM scraping.search_term
          WHERE public_id=:pid
        ), first_extraction AS (
          SELECT r.correlation_id FROM scraping.scrape_request r
          JOIN scraping.search_term t ON t.id=r.search_term_id
          JOIN original o USING (normalized_term, configuration_key)
          WHERE r.mode='discover' ORDER BY r.created_at,r.id LIMIT 1
        )
        SELECT DISTINCT t.id,t.public_id,t.site,t.term FROM scraping.search_term t
        JOIN original o USING (normalized_term, configuration_key)
        JOIN scraping.scrape_request r ON r.search_term_id=t.id
        JOIN first_extraction f ON f.correlation_id=r.correlation_id
        WHERE r.mode='discover' ORDER BY t.id
        """),
                {"pid": public_id},
            )
        )
        .mappings()
        .all()
    )


async def find_target(session, entity_public_id):
    return (
        (
            await session.execute(
                text("""SELECT t.* FROM "scraping"."tracking_target" t
        JOIN "scraping"."entity" e ON e.id = t.entity_id WHERE e.public_id = :id"""),
                {"id": entity_public_id},
            )
        )
        .mappings()
        .one_or_none()
    )


async def enqueue(session, mode, internal_id, correlation_id=None):
    column = "search_term_id" if mode == "discover" else "tracking_target_id"
    result = await session.execute(
        text(f"""INSERT INTO "scraping"."scrape_request" (mode, {column}, correlation_id)
        VALUES (:mode, :id, coalesce(CAST(:correlation AS uuid), gen_random_uuid())) ON CONFLICT ({column})
        WHERE status IN ('pending', 'running') AND mode = '{mode}'
        DO UPDATE SET mode = EXCLUDED.mode RETURNING public_id, status"""),
        {"mode": mode, "id": internal_id, "correlation": correlation_id},
    )
    return result.mappings().one()


async def list_products(session, term_id, limit, offset):
    from ..auth.mcp_policy import observation_scope, scoped_clause

    scope, params = scoped_clause(session, observation_scope("capture"))
    return (
        (
            await session.execute(
                text(f"""
        SELECT e.public_id, e.source_key, e.site, t.public_id AS tracking_target_id,
               t.product_url, t.enabled, t.next_poll_at,
               p.public_id AS catalog_product_id,v.public_id AS variant_id,
               p.category,p.brand,p.model,v.attributes,
               o.public_id AS observation_id, o.created_at AS observed_at, o.payload
        FROM "scraping"."search_term_entity" link
        JOIN "scraping"."entity" e ON e.id = link.entity_id
        LEFT JOIN "catalog"."listing" l ON l.entity_id=e.id
        LEFT JOIN "catalog"."variant" v ON v.id=l.variant_id
        LEFT JOIN "catalog"."product" p ON p.id=v.product_id
        LEFT JOIN "scraping"."tracking_target" t ON t.entity_id = e.id
        LEFT JOIN LATERAL (SELECT public_id, payload, created_at FROM "scraping"."observation" capture
            WHERE entity_id = e.id {scope} ORDER BY created_at DESC, id DESC LIMIT 1) o ON true
        WHERE link.search_term_id = :id ORDER BY e.id LIMIT :limit OFFSET :offset
    """),
                {"id": term_id, "limit": limit, "offset": offset, **params},
            )
        )
        .mappings()
        .all()
    )


async def read_history(
    session, entity_id, limit, offset, *, start_at=None, end_at=None
):
    from ..auth.mcp_policy import observation_scope, scoped_clause

    scope, params = scoped_clause(session, observation_scope())
    return (
        (
            await session.execute(
                text(f"""SELECT o.public_id, o.created_at, o.payload
        FROM "scraping"."observation" o JOIN "scraping"."entity" e ON e.id = o.entity_id
        WHERE e.public_id = :id {scope}
          AND (CAST(:start_at AS timestamptz) IS NULL OR o.created_at>=:start_at)
          AND (CAST(:end_at AS timestamptz) IS NULL OR o.created_at<:end_at)
        ORDER BY o.created_at DESC, o.id DESC LIMIT :limit OFFSET :offset"""),
                {
                    "id": entity_id,
                    "limit": limit,
                    "offset": offset,
                    "start_at": start_at,
                    "end_at": end_at,
                    **params,
                },
            )
        )
        .mappings()
        .all()
    )


async def update_target(session, target_id, value):
    await session.execute(
        text("""UPDATE "scraping"."tracking_target"
        SET enabled = :enabled, refresh_interval_seconds = :interval WHERE id = :id"""),
        {
            "id": target_id,
            "enabled": value.enabled,
            "interval": value.refresh_interval_seconds,
        },
    )


async def read_request(session, public_id):
    return (
        (
            await session.execute(
                text("""SELECT r.public_id, r.correlation_id, r.mode, r.status,
        coalesce(t.criteria,target.criteria) AS criteria,
        t.term, t.public_id AS search_term_id, e.public_id AS entity_id, e.source_key,
        t.max_pages_qt, t.max_candidates_qt,
        coalesce(target.refresh_interval_seconds,t.refresh_interval_seconds) AS refresh_interval_seconds,
        r.summary, r.created_at, r.completed_at, coalesce(t.site,e.site) AS site
        FROM "scraping"."scrape_request" r
        LEFT JOIN scraping.search_term t ON t.id=r.search_term_id
        LEFT JOIN scraping.tracking_target target ON target.id=r.tracking_target_id
        LEFT JOIN scraping.entity e ON e.id=target.entity_id WHERE r.public_id = :id"""),
                {"id": public_id},
            )
        )
        .mappings()
        .one_or_none()
    )


async def read_asset(session, public_id):
    return (
        (
            await session.execute(
                text(
                    'SELECT bucket, object_key, kind FROM "scraping"."asset" WHERE public_id = :id'
                ),
                {"id": public_id},
            )
        )
        .mappings()
        .one_or_none()
    )
