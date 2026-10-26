"""Period-aware analytics over persisted captures, never over a UI page."""

from panoptes_contracts.pricing import with_composition
from sqlalchemy import text

from ..auth.mcp_policy import (
    entity_scope,
    observation_scope,
    request_scope,
    scoped_clause,
    term_scope,
)
from ..catalog.pricing_repository import CHILDREN, OBSERVATION_FIELDS

ZONE = "America/Sao_Paulo"
ENTITY_FILTER = """
 (CAST(:term_id AS uuid) IS NULL OR EXISTS (
   SELECT 1 FROM scraping.search_term_entity link
   JOIN scraping.search_term t ON t.id=link.search_term_id
   WHERE link.entity_id=e.id AND lower(btrim(t.term))=(SELECT lower(btrim(term)) FROM scraping.search_term WHERE public_id=CAST(:term_id AS uuid))))
 AND (CAST(:product_id AS uuid) IS NULL OR e.public_id=CAST(:product_id AS uuid))
 AND (CAST(:site AS text) IS NULL OR e.site=:site)
 AND (CAST(:product_ids AS uuid[]) IS NULL OR e.public_id=ANY(CAST(:product_ids AS uuid[])))
"""
BASE = f"""
 SELECT o.*, e.public_id AS product_id,e.site,e.source_key,
   coalesce(l.title,source.payload->'offer'->>'title',e.source_key) AS title,
   l.url,f.seller,f.public_id AS offer_public_id,j.public_id AS job_id,
   r.public_id AS request_id,r.status AS execution_status,
   source.public_id AS capture_id,source.created_at AS captured_at,
   (SELECT string_agg(DISTINCT t.term, ', ' ORDER BY t.term)
    FROM scraping.search_term_entity link
    JOIN scraping.search_term t ON t.id=link.search_term_id
    WHERE link.entity_id=e.id) AS terms
 FROM scraping.observation source
 JOIN scraping.entity e ON e.id=source.entity_id
 JOIN scraping.job j ON j.id=source.job_id
 LEFT JOIN scraping.scrape_request r ON r.id=j.scrape_request_id
 LEFT JOIN catalog.listing l ON l.entity_id=e.id
 LEFT JOIN pricing.observation o ON o.source_observation_id=source.id
 LEFT JOIN pricing.offer f ON f.id=o.offer_id
 WHERE coalesce(o.observed_at,source.created_at)>=:start_at
   AND coalesce(o.observed_at,source.created_at)<:end_at
   AND {ENTITY_FILTER}
"""


async def options(session, term_id=None, site=None):
    return (
        (
            await session.execute(
                text("""
      SELECT e.public_id,coalesce(l.title,e.source_key) AS title,e.site
      FROM scraping.entity e LEFT JOIN catalog.listing l ON l.entity_id=e.id
      WHERE (CAST(:site AS text) IS NULL OR e.site=:site)
        AND (CAST(:term_id AS uuid) IS NULL OR EXISTS (
          SELECT 1 FROM scraping.search_term_entity link
          JOIN scraping.search_term t ON t.id=link.search_term_id
          WHERE link.entity_id=e.id AND lower(btrim(t.term))=(SELECT lower(btrim(term)) FROM scraping.search_term WHERE public_id=CAST(:term_id AS uuid))))
      ORDER BY title,e.public_id
    """),
                {"term_id": term_id, "site": site},
            )
        )
        .mappings()
        .all()
    )


def scoped_base(session, filters):
    scope, params = scoped_clause(
        session, f"{observation_scope('source')} AND {entity_scope()}"
    )
    base = BASE + scope
    if scope:
        base = base.replace(
            "WHERE link.entity_id=e.id) AS terms",
            f"WHERE link.entity_id=e.id AND {term_scope()}) AS terms",
        )
    if filters.get("time_basis") == "collected_at":
        base = base.replace(
            "coalesce(o.observed_at,source.created_at)", "source.created_at"
        )
    if filters.get("currency"):
        base += " AND o.currency=:currency"
    return base, params


async def detail(
    session,
    filters,
    limit,
    offset,
    *,
    latest=False,
    sort_by="observed_at",
    sort_order="desc",
):
    columns = {
        "observed_at": "coalesce(o.observed_at,o.captured_at)",
        "collected_at": "o.captured_at",
        "price": "o.price_vl",
    }
    if sort_by not in columns or sort_order not in {"asc", "desc"}:
        raise ValueError("Invalid price ordering")
    # Never compare nominal amounts from different currencies as one ranking.
    if sort_by == "price" and not filters.get("currency"):
        raise ValueError("currency is required when sorting by price")
    selected, scope_params = scoped_base(session, filters)
    params = {**filters, **scope_params, "limit": limit, "offset": offset}
    # Keep every seller from the newest capture, including captures without an offer.
    # Rank before pagination so a product cannot repeat across pages as history.
    if latest:
        selected = f"""
          SELECT * FROM (
            SELECT b.*,dense_rank() OVER (
              PARTITION BY product_id ORDER BY captured_at DESC,capture_id DESC
            ) AS capture_rank FROM ({selected}) b
          ) ranked WHERE capture_rank=1
        """
    total = (
        await session.execute(text(f"SELECT count(*) FROM ({selected}) b"), params)
    ).scalar_one()
    items = (
        (
            await session.execute(
                text(f"""
      WITH filtered AS ({selected})
      SELECT {OBSERVATION_FIELDS.replace("o.observed_at", "coalesce(o.observed_at,o.captured_at) AS observed_at")},o.product_id,o.title,o.site,o.source_key,
        o.url,o.seller,o.offer_public_id,o.job_id,o.request_id,o.execution_status,
        o.capture_id,o.captured_at AS collected_at,o.terms,p.brand,p.model,p.category,v.attributes,
        coalesce(p.identifiers,'{{}}'::jsonb) || coalesce(v.identifiers,'{{}}'::jsonb) AS identifiers,
        f.ships_from,f.condition,{CHILDREN}
      FROM filtered o
      LEFT JOIN catalog.listing l ON l.entity_id=(SELECT id FROM scraping.entity WHERE public_id=o.product_id)
      LEFT JOIN catalog.variant v ON v.id=l.variant_id
      LEFT JOIN catalog.product p ON p.id=v.product_id
      LEFT JOIN pricing.offer f ON f.id=o.offer_id
      ORDER BY {columns[sort_by]} {sort_order.upper()} NULLS LAST,o.capture_id DESC,o.id DESC
      LIMIT :limit OFFSET :offset
    """),
                params,
            )
        )
        .mappings()
        .all()
    )
    return {
        "items": [with_composition(row) for row in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def dashboard(session, filters):
    base, params = scoped_base(session, filters)
    executions_scope, execution_params = scoped_clause(session, request_scope())
    # Each series is grouped in PostgreSQL. Currency groups are kept separate.
    query = f"""
    WITH filtered AS ({base}), priced AS (
      SELECT * FROM filtered WHERE id IS NOT NULL
    ), latest AS (
      SELECT DISTINCT ON (offer_id) * FROM priced
      ORDER BY offer_id,observed_at DESC,id DESC
    ), comparison AS (
      SELECT l.*,(SELECT p.price_vl FROM priced p
        WHERE p.offer_id=l.offer_id AND p.currency=l.currency
          AND p.price_vl IS NOT NULL AND (p.observed_at,p.id)<(l.observed_at,l.id)
        ORDER BY p.observed_at DESC,p.id DESC LIMIT 1) AS previous_price
      FROM latest l
    ), requests AS (
      SELECT r.* FROM scraping.scrape_request r
      LEFT JOIN scraping.search_term t ON t.id=r.search_term_id
      LEFT JOIN scraping.tracking_target target ON target.id=r.tracking_target_id
      LEFT JOIN scraping.entity e ON e.id=target.entity_id
      WHERE r.created_at>=:start_at AND r.created_at<:end_at
        {executions_scope}
        AND (CAST(:site AS text) IS NULL OR coalesce(t.site,e.site)=:site)
        AND (CAST(:term_id AS uuid) IS NULL OR lower(btrim(t.term))=(SELECT lower(btrim(term)) FROM scraping.search_term WHERE public_id=CAST(:term_id AS uuid))
          OR EXISTS (SELECT 1 FROM scraping.search_term_entity link
            JOIN scraping.search_term st ON st.id=link.search_term_id
            WHERE link.entity_id=e.id AND lower(btrim(st.term))=(SELECT lower(btrim(term)) FROM scraping.search_term WHERE public_id=CAST(:term_id AS uuid))))
        AND (CAST(:product_id AS uuid) IS NULL OR e.public_id=CAST(:product_id AS uuid)
          OR EXISTS (SELECT 1 FROM scraping.job j
            JOIN scraping.observation s ON s.job_id=j.id
            JOIN scraping.entity se ON se.id=s.entity_id
            WHERE j.scrape_request_id=r.id AND se.public_id=CAST(:product_id AS uuid)))
        AND (CAST(:product_ids AS uuid[]) IS NULL OR e.public_id=ANY(CAST(:product_ids AS uuid[]))
          OR EXISTS (SELECT 1 FROM scraping.job j
            JOIN scraping.observation s ON s.job_id=j.id
            JOIN scraping.entity se ON se.id=s.entity_id
            WHERE j.scrape_request_id=r.id AND se.public_id=ANY(CAST(:product_ids AS uuid[]))))
    )
    SELECT jsonb_build_object(
      'totals', (SELECT jsonb_build_object(
        'products',count(DISTINCT product_id),'observations',count(DISTINCT capture_id),
        'offers',count(DISTINCT offer_id)) FROM filtered),
      'execution_totals', (SELECT jsonb_build_object('total',count(*),
        'completed',count(*) FILTER (WHERE status='completed'),
        'failed',count(*) FILTER (WHERE status IN ('failed','blocked')),
        'partial',count(*) FILTER (WHERE status='partial'),
        'in_progress',count(*) FILTER (WHERE status IN ('pending','running'))) FROM requests),
      'currencies',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM (
        SELECT currency,count(*) FILTER (WHERE price_vl IS NOT NULL) AS priced_offers,
          min(price_vl) AS minimum,avg(price_vl) AS average,max(price_vl) AS maximum,
          count(*) FILTER (WHERE price_vl<previous_price) AS drops,
          count(*) FILTER (WHERE price_vl>previous_price) AS rises,
          count(*) FILTER (WHERE availability='in_stock') AS available,
          count(*) FILTER (WHERE EXISTS (SELECT 1 FROM pricing.payment_option p
            WHERE p.observation_id=comparison.id AND p.interest_free=true
              AND p.installment_qt>1)) AS interest_free,
          count(*) FILTER (WHERE EXISTS (SELECT 1 FROM pricing.promotion p
            WHERE p.observation_id=comparison.id)) AS promotions
        FROM comparison WHERE currency IS NOT NULL GROUP BY currency ORDER BY currency
      ) x),'[]'::jsonb),
      'daily',coalesce((SELECT jsonb_agg(to_jsonb(x) ORDER BY x.date,x.site,x.currency) FROM (
        SELECT (observed_at AT TIME ZONE '{ZONE}')::date AS date,site,currency,
          min(price_vl) AS minimum,avg(price_vl) AS average,max(price_vl) AS maximum,
          count(*) AS observations
        FROM priced WHERE currency IS NOT NULL AND price_vl IS NOT NULL
        GROUP BY 1,site,currency
      ) x),'[]'::jsonb),
      'executions',coalesce((SELECT jsonb_agg(to_jsonb(x) ORDER BY x.date) FROM (
        SELECT (created_at AT TIME ZONE '{ZONE}')::date AS date,count(*) AS total,
          count(*) FILTER (WHERE status='completed') AS completed,
          count(*) FILTER (WHERE status IN ('failed','blocked')) AS failed,
          count(*) FILTER (WHERE status='partial') AS partial,
          count(*) FILTER (WHERE status IN ('pending','running')) AS in_progress
        FROM requests GROUP BY 1
      ) x),'[]'::jsonb),
      'sites',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM (
        SELECT site,currency,min(price_vl) AS minimum,avg(price_vl) AS average,
          max(price_vl) AS maximum,count(*) AS offers
        FROM latest WHERE currency IS NOT NULL AND price_vl IS NOT NULL
        GROUP BY site,currency ORDER BY site,currency
      ) x),'[]'::jsonb),
      'commerce',coalesce((SELECT jsonb_agg(to_jsonb(x) ORDER BY x.site,x.currency) FROM (
        SELECT l.site,l.currency,count(*) AS offers,
          count(*) FILTER (WHERE c.coupons>0) AS with_coupons,
          coalesce(sum(c.coupons),0) AS coupons,
          coalesce(sum(c.quantified),0) AS quantified_coupons,
          coalesce(sum(c.expired),0) AS expired_coupons,
          avg(l.price_vl) FILTER (WHERE c.coupons>0) AS average_advertised_with_coupons,
          avg(l.price_vl) FILTER (WHERE c.coupons=0) AS average_advertised_without_coupons,
          count(*) FILTER (WHERE s.observation_id IS NOT NULL) AS with_shipping,
          count(*) FILTER (WHERE s.is_free=true AND s.price_vl=0) AS free_shipping,
          count(*) FILTER (WHERE s.price_vl>0) AS paid_shipping,
          count(*) FILTER (WHERE s.price_vl IS NULL) AS unknown_shipping,
          avg(s.price_vl) AS average_shipping,
          count(*) FILTER (WHERE s.destination_postal_code IS NOT NULL) AS destination_specific,
          count(*) FILTER (WHERE jsonb_array_length(coalesce(l.shipping_options,'[]'::jsonb))>1) AS multiple_shipping_options
        FROM latest l
        LEFT JOIN pricing.shipping_quote s ON s.observation_id=l.id
        LEFT JOIN LATERAL (
          SELECT count(*) AS coupons,
            count(*) FILTER (WHERE p.discount_vl IS NOT NULL OR p.discount_percent IS NOT NULL) AS quantified,
            count(*) FILTER (WHERE p.expires_at<=CURRENT_TIMESTAMP) AS expired
          FROM pricing.promotion p WHERE p.observation_id=l.id AND p.kind='coupon'
        ) c ON true
        WHERE l.currency IS NOT NULL GROUP BY l.site,l.currency
      ) x),'[]'::jsonb),
      'coupon_terms',coalesce((SELECT jsonb_agg(to_jsonb(x) ORDER BY x.site,x.code,x.text) FROM (
        SELECT l.site,l.currency,p.code,p.text,p.discount_vl::text AS discount_amount,
          p.discount_percent::text AS discount_percent,p.minimum_spend_vl::text AS minimum_spend,
          p.maximum_discount_vl::text AS maximum_discount,p.requires_activation,p.expires_at,
          count(DISTINCT l.offer_id) AS offers
        FROM latest l JOIN pricing.promotion p ON p.observation_id=l.id
        WHERE p.kind='coupon' AND l.currency IS NOT NULL
        GROUP BY l.site,l.currency,p.code,p.text,p.discount_vl,p.discount_percent,
          p.minimum_spend_vl,p.maximum_discount_vl,p.requires_activation,p.expires_at
      ) x),'[]'::jsonb),
      'payments',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM (
        SELECT l.site,l.currency,p.method,p.installment_qt AS installments,
          p.interest_free,count(DISTINCT l.offer_id) AS offers,
          avg(p.total_price_vl) AS average_total,
          avg(p.installment_price_vl) AS average_installment
        FROM latest l JOIN pricing.payment_option p ON p.observation_id=l.id
        GROUP BY l.site,l.currency,p.method,p.installment_qt,p.interest_free
        ORDER BY l.site,p.method,p.installment_qt
      ) x),'[]'::jsonb),
      'opportunities',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM (
        SELECT product_id,title,site,currency,price_vl AS price,previous_price,
          (price_vl/NULLIF(previous_price,0)-1)*100 AS change,observed_at
        FROM comparison WHERE price_vl<previous_price AND previous_price>0
        ORDER BY (price_vl/previous_price-1) LIMIT 8
      ) x),'[]'::jsonb)
    )
    """
    return (
        await session.execute(text(query), {**filters, **params, **execution_params})
    ).scalar_one()
