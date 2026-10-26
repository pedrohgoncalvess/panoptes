from sqlalchemy import text

CHILDREN = """
  coalesce((SELECT jsonb_agg(jsonb_build_object(
    'public_id',p.public_id,'kind',p.kind,'text',p.text,'code',p.code,
    'discount_amount',p.discount_vl::text,'discount_percent',p.discount_percent::text,
    'minimum_spend',p.minimum_spend_vl::text,'expires_at',p.expires_at,
    'requires_activation',p.requires_activation,'conditions',p.conditions,
    'maximum_discount',p.maximum_discount_vl::text,'extraction_method',p.extraction_method) ORDER BY p.position_qt)
    FROM "pricing"."promotion" p WHERE p.observation_id=o.id),'[]'::jsonb) AS promotions,
  coalesce((SELECT jsonb_agg(jsonb_build_object(
    'public_id',p.public_id,'method',p.method,'text',p.text,'total_price',p.total_price_vl::text,
    'installment_count',p.installment_qt,'installment_price',p.installment_price_vl::text,
    'interest_free',p.interest_free,'conditions',p.conditions,
    'total_is_derived',p.total_is_derived,'extraction_method',p.extraction_method) ORDER BY p.position_qt)
    FROM "pricing"."payment_option" p WHERE p.observation_id=o.id),'[]'::jsonb) AS payment_options,
  (SELECT jsonb_build_object('public_id',s.public_id,'text',s.text,'price',s.price_vl::text,
    'is_free',s.is_free,'destination_postal_code',s.destination_postal_code,'conditions',s.conditions,
    'delivery_text',s.delivery_text,'extraction_method',s.extraction_method)
    FROM "pricing"."shipping_quote" s WHERE s.observation_id=o.id) AS shipping
"""
COUPON_FIELDS = """
    (SELECT source.payload->'offer'->>'price_without_coupon'
     FROM scraping.observation source WHERE source.id=o.source_observation_id) AS price_without_coupon,
    (SELECT CASE source.payload->'offer'->>'price_includes_coupon' WHEN 'true' THEN true WHEN 'false' THEN false END
     FROM scraping.observation source WHERE source.id=o.source_observation_id) AS price_includes_coupon"""

OBSERVATION_FIELDS = f"""o.public_id,o.observed_at,o.price_vl::text AS price,
    o.list_price_vl::text AS list_price,o.currency,o.availability,o.availability_text,o.stock_qt,
    o.stock_lower_bound_qt,o.units_per_pack,o.minimum_purchase_qt,o.maximum_purchase_qt,
    o.commercial_extraction,o.shipping_options,
    {COUPON_FIELDS}"""


async def list_offers(session, entity_public_id, limit, offset):
    from ..auth.mcp_policy import pricing_scope, scoped_clause

    latest_scope, params = scoped_clause(session, pricing_scope("latest"))
    current_scope, _ = scoped_clause(session, pricing_scope("po"))
    return (
        (
            await session.execute(
                text(f"""SELECT f.public_id,f.seller,f.ships_from,f.condition,
        e.public_id AS listing_entity_id,l.public_id AS listing_id,
        o.public_id AS observation_id,o.observed_at,o.price_vl::text AS price,
        o.list_price_vl::text AS list_price,o.currency,o.availability,o.availability_text,o.stock_qt,
        o.stock_lower_bound_qt,o.units_per_pack,o.minimum_purchase_qt,o.maximum_purchase_qt,
        o.commercial_extraction,o.shipping_options,
        {COUPON_FIELDS},
        (o.source_observation_id=(SELECT po.source_observation_id FROM "pricing"."observation" po
            JOIN "pricing"."offer" pf ON pf.id=po.offer_id WHERE pf.listing_id=l.id {current_scope}
            ORDER BY po.observed_at DESC,po.id DESC LIMIT 1)) AS is_current,
        {CHILDREN}
        FROM "pricing"."offer" f JOIN "catalog"."listing" l ON l.id=f.listing_id
        JOIN "scraping"."entity" e ON e.id=l.entity_id
        JOIN LATERAL (SELECT latest.* FROM "pricing"."observation" latest WHERE offer_id=f.id {latest_scope}
            ORDER BY observed_at DESC,id DESC LIMIT 1) o ON true
        WHERE e.public_id=:id ORDER BY o.observed_at DESC,f.id LIMIT :limit OFFSET :offset"""),
                {"id": entity_public_id, "limit": limit, "offset": offset, **params},
            )
        )
        .mappings()
        .all()
    )


async def offer_exists(session, public_id):
    return (
        await session.execute(
            text('SELECT id FROM "pricing"."offer" WHERE public_id=:id'),
            {"id": public_id},
        )
    ).scalar_one_or_none() is not None


async def history(session, offer_public_id, limit, offset):
    from ..auth.mcp_policy import pricing_scope, scoped_clause

    scope, params = scoped_clause(session, pricing_scope())
    return (
        (
            await session.execute(
                text(f"""SELECT {OBSERVATION_FIELDS},{CHILDREN}
        FROM "pricing"."observation" o JOIN "pricing"."offer" f ON f.id=o.offer_id
        WHERE f.public_id=:id {scope} ORDER BY o.observed_at DESC,o.id DESC LIMIT :limit OFFSET :offset"""),
                {"id": offer_public_id, "limit": limit, "offset": offset, **params},
            )
        )
        .mappings()
        .all()
    )
