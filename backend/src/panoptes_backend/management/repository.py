from panoptes_contracts.pricing import with_composition
from sqlalchemy import text

from ..catalog.pricing_repository import CHILDREN, COUPON_FIELDS, OBSERVATION_FIELDS


async def prices(session, term_id, limit, offset):
    from ..auth.mcp_policy import observation_scope, pricing_scope, scoped_clause

    capture_scope, scope_params = scoped_clause(session, observation_scope("capture"))
    history_scope, _ = scoped_clause(session, pricing_scope("h"))
    latest_scope, _ = scoped_clause(session, pricing_scope("latest"))
    params = {"term_id": term_id, "limit": limit, "offset": offset, **scope_params}
    total = (
        await session.execute(
            text("""
        SELECT count(*) FROM scraping.search_term_entity WHERE search_term_id=:term_id
    """),
            params,
        )
    ).scalar_one()
    items = (
        (
            await session.execute(
                text(f"""
        SELECT e.public_id,e.site, coalesce(l.title, p.title, e.source_key) AS title,
          l.url, p.brand, v.attributes,
          source.created_at AS observed_at,
          coalesce(source.payload->'offer'->'image_urls', '[]'::jsonb) AS image_urls,
          coalesce(prices.offers, '[]'::jsonb) AS offers
        FROM scraping.search_term_entity link
        JOIN scraping.entity e ON e.id=link.entity_id
        LEFT JOIN catalog.listing l ON l.entity_id=e.id
        LEFT JOIN catalog.variant v ON v.id=l.variant_id
        LEFT JOIN catalog.product p ON p.id=v.product_id
        LEFT JOIN LATERAL (SELECT id, payload, created_at FROM scraping.observation capture
          WHERE entity_id=e.id {capture_scope} ORDER BY created_at DESC,id DESC LIMIT 1) source ON true
        LEFT JOIN LATERAL (
          SELECT jsonb_agg(to_jsonb(offer) ORDER BY offer.price::numeric NULLS LAST) AS offers
          FROM (
            SELECT f.public_id, f.seller, f.condition, {OBSERVATION_FIELDS.replace("o.public_id,", "o.public_id AS observation_id,")},
              {CHILDREN},
              (SELECT min(h.price_vl)::text FROM pricing.observation h
                WHERE h.offer_id=f.id {history_scope} AND h.currency=o.currency) AS lowest_price,
              (SELECT h.price_vl::text FROM pricing.observation h
                WHERE h.offer_id=f.id {history_scope} AND h.currency=o.currency AND h.price_vl IS NOT NULL
                  AND (h.observed_at,h.id)<(o.observed_at,o.id)
                ORDER BY h.observed_at DESC,h.id DESC LIMIT 1) AS previous_price,
              coalesce((SELECT jsonb_agg(to_jsonb(point) ORDER BY point.observed_at)
                FROM (SELECT h.observed_at,h.price_vl::text AS price,h.currency,
                    h.stock_qt,h.stock_lower_bound_qt,h.units_per_pack,h.commercial_extraction,
                    h.shipping_options,{COUPON_FIELDS.replace("o.source_observation_id", "h.source_observation_id")},{CHILDREN.replace("o.id", "h.id")}
                    FROM pricing.observation h
                  WHERE h.offer_id=f.id {history_scope} AND h.currency IS NOT DISTINCT FROM o.currency
                  ORDER BY h.observed_at DESC,h.id DESC LIMIT 30) point),'[]'::jsonb) AS history
            FROM pricing.offer f
            JOIN LATERAL (SELECT latest.* FROM pricing.observation latest WHERE offer_id=f.id {latest_scope}
              ORDER BY observed_at DESC,id DESC LIMIT 1) o ON true
            WHERE f.listing_id=l.id AND o.source_observation_id=source.id
          ) offer
        ) prices ON true
        WHERE link.search_term_id=:term_id
        ORDER BY e.id LIMIT :limit OFFSET :offset
    """),
                params,
            )
        )
        .mappings()
        .all()
    )
    enriched = []
    for row in items:
        item = dict(row)
        item["offers"] = [
            with_composition(
                {
                    **offer,
                    "history": [
                        with_composition(point) for point in offer.get("history", [])
                    ],
                }
            )
            for offer in item.get("offers", [])
        ]
        enriched.append(item)
    return {"items": enriched, "total": total, "limit": limit, "offset": offset}


async def analytics(session, days):
    totals = (
        (
            await session.execute(
                text("""
        SELECT
          (SELECT count(*) FROM scraping.entity) AS products,
          (SELECT count(*) FROM scraping.scheduled_routine WHERE enabled) AS active_routines,
          count(*) AS requests,
          count(*) FILTER (WHERE status = 'completed') AS completed,
          count(*) FILTER (WHERE status IN ('failed', 'blocked')) AS failed,
          count(*) FILTER (WHERE status IN ('pending', 'running')) AS in_progress
        FROM scraping.scrape_request
        WHERE created_at >= ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date
          - (:days - 1) * INTERVAL '1 day') AT TIME ZONE 'UTC'
    """),
                {"days": days},
            )
        )
        .mappings()
        .one()
    )
    daily = (
        (
            await session.execute(
                text("""
        SELECT day::date AS date, count(r.id) AS total,
          count(r.id) FILTER (WHERE r.status = 'completed') AS completed,
          count(r.id) FILTER (WHERE r.status IN ('failed', 'blocked')) AS failed
        FROM generate_series((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date
          - (:days - 1) * INTERVAL '1 day',
          (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date, INTERVAL '1 day') AS day
        LEFT JOIN scraping.scrape_request r
          ON r.created_at >= day AT TIME ZONE 'UTC'
          AND r.created_at < (day + INTERVAL '1 day') AT TIME ZONE 'UTC'
        GROUP BY day ORDER BY day
    """),
                {"days": days},
            )
        )
        .mappings()
        .all()
    )
    return {"period_days": days, "totals": totals, "daily": daily}


async def extractions(session, status, limit, offset, group_key=None):
    from ..auth.mcp_policy import bindings, key_for, request_scope

    params = {
        "status": status,
        "limit": limit,
        "offset": offset,
        "group_key": group_key,
    }
    # Static predicate and bound parameters keep user filters out of SQL text.
    predicate = """(CAST(:status AS text) IS NULL OR r.status = :status)
        AND (CAST(:group_key AS text) IS NULL OR
          coalesce('term:' || t.normalized_term || ':' || t.configuration_key, 'entity:' || e.public_id::text,
            'request:' || r.public_id::text) = :group_key)"""
    if key_for(session):
        params.update(bindings(key_for(session)))
        predicate += " AND " + request_scope()
    total = (
        await session.execute(
            text(f"""
        SELECT count(*) FROM scraping.scrape_request r
        LEFT JOIN scraping.search_term t ON t.id = r.search_term_id
        LEFT JOIN scraping.tracking_target target ON target.id = r.tracking_target_id
        LEFT JOIN scraping.entity e ON e.id = target.entity_id
        WHERE {predicate}
    """),
            params,
        )
    ).scalar_one()
    items = (
        (
            await session.execute(
                text(f"""
        SELECT r.public_id, r.mode, r.status, r.summary, r.created_at,
          r.completed_at, t.public_id AS search_term_id, t.term,
          e.public_id AS entity_id, e.source_key, coalesce(t.site,e.site) AS site
        FROM scraping.scrape_request r
        LEFT JOIN scraping.search_term t ON t.id = r.search_term_id
        LEFT JOIN scraping.tracking_target target ON target.id = r.tracking_target_id
        LEFT JOIN scraping.entity e ON e.id = target.entity_id
        WHERE {predicate}
        ORDER BY r.created_at DESC, r.id DESC LIMIT :limit OFFSET :offset
    """),
                params,
            )
        )
        .mappings()
        .all()
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def extraction_groups(session, status, limit, offset):
    from ..auth.mcp_policy import bindings, key_for, request_scope

    params = {"status": status, "limit": limit, "offset": offset}
    base = """
        SELECT r.id, r.public_id, r.mode, r.status, r.summary, r.created_at,
          r.completed_at, t.public_id AS search_term_id, t.term,
          e.public_id AS entity_id, e.source_key, coalesce(t.site,e.site) AS site,
          coalesce('term:' || t.normalized_term || ':' || t.configuration_key, 'entity:' || e.public_id::text,
            'request:' || r.public_id::text) AS group_key
        FROM scraping.scrape_request r
        LEFT JOIN scraping.search_term t ON t.id = r.search_term_id
        LEFT JOIN scraping.tracking_target target ON target.id = r.tracking_target_id
        LEFT JOIN scraping.entity e ON e.id = target.entity_id
    """
    if key_for(session):
        params.update(bindings(key_for(session)))
        base += " WHERE " + request_scope()
    total = (
        await session.execute(
            text(f"""
        WITH executions AS ({base})
        SELECT count(DISTINCT group_key) FROM executions
        WHERE CAST(:status AS text) IS NULL OR status=:status
    """),
            params,
        )
    ).scalar_one()
    items = (
        (
            await session.execute(
                text(f"""
        WITH executions AS ({base}), ranked AS (
          SELECT *, count(*) OVER (PARTITION BY group_key) AS execution_count,
            bool_or(CAST(:status AS text) IS NULL OR status=:status)
              OVER (PARTITION BY group_key) AS matches,
            row_number() OVER (PARTITION BY group_key ORDER BY created_at DESC,id DESC) AS position
          FROM executions
        )
        SELECT public_id, mode, status, summary, created_at, completed_at,
          search_term_id, term, entity_id, source_key, site, group_key, execution_count
        FROM ranked WHERE position=1 AND matches
        ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset
    """),
                params,
            )
        )
        .mappings()
        .all()
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}
