from sqlalchemy import text


async def canonical_entity_ids(session, public_id):
    return (
        (
            await session.execute(
                text("""
      SELECT e.public_id FROM catalog.product_normalization n
      JOIN catalog.canonical_product c ON c.id=n.canonical_product_id
      JOIN catalog.listing l ON l.id=n.listing_id
      JOIN scraping.entity e ON e.id=l.entity_id
      WHERE c.public_id=:id AND n.status='completed'
    """),
                {"id": public_id},
            )
        )
        .scalars()
        .all()
    )


async def canonical_products(session, limit, offset):
    return (
        (
            await session.execute(
                text("""
      SELECT c.public_id,c.name,c.identity,count(n.listing_id) AS listing_count,
        array_agg(DISTINCT e.site ORDER BY e.site) AS sites
      FROM catalog.canonical_product c
      JOIN catalog.product_normalization n ON n.canonical_product_id=c.id
        AND n.status='completed'
      JOIN catalog.listing l ON l.id=n.listing_id
      JOIN scraping.entity e ON e.id=l.entity_id
      GROUP BY c.id ORDER BY c.id DESC LIMIT :limit OFFSET :offset
    """),
                {"limit": limit, "offset": offset},
            )
        )
        .mappings()
        .all()
    )


async def canonical_listings(session, public_id, limit, offset):
    return (
        (
            await session.execute(
                text("""
      SELECT l.public_id,l.title,l.url,e.public_id AS listing_entity_id,
        e.site,e.source_key,c.public_id AS canonical_product_id,c.name AS canonical_name,
        n.result AS normalization
      FROM catalog.canonical_product c
      JOIN catalog.product_normalization n ON n.canonical_product_id=c.id
        AND n.status='completed'
      JOIN catalog.listing l ON l.id=n.listing_id
      JOIN scraping.entity e ON e.id=l.entity_id
      WHERE c.public_id=:id ORDER BY l.id LIMIT :limit OFFSET :offset
    """),
                {"id": public_id, "limit": limit, "offset": offset},
            )
        )
        .mappings()
        .all()
    )


async def list_products(session, category, brand, limit, offset):
    return (
        (
            await session.execute(
                text("""SELECT p.public_id,p.category,p.title,p.brand,p.model,p.identifiers,
        coalesce((SELECT jsonb_agg(jsonb_build_object('public_id',v.public_id,'attributes',v.attributes,
            'identifiers',v.identifiers) ORDER BY v.id) FROM "catalog"."variant" v WHERE v.product_id=p.id),'[]'::jsonb) AS variants
        FROM "catalog"."product" p
        WHERE (CAST(:category AS text) IS NULL OR p.category=:category)
          AND (CAST(:brand AS text) IS NULL OR lower(p.brand)=lower(:brand))
        ORDER BY p.id DESC LIMIT :limit OFFSET :offset"""),
                {
                    "category": category,
                    "brand": brand,
                    "limit": limit,
                    "offset": offset,
                },
            )
        )
        .mappings()
        .all()
    )


async def exists(session, public_id):
    return (
        await session.execute(
            text('SELECT id FROM "catalog"."product" WHERE public_id=:id'),
            {"id": public_id},
        )
    ).scalar_one_or_none() is not None


async def listings(session, product_public_id, limit, offset):
    return (
        (
            await session.execute(
                text("""SELECT l.public_id,l.title,l.url,e.public_id AS listing_entity_id,
        e.site,e.source_key,v.public_id AS variant_id,v.attributes,t.public_id AS tracking_target_id,t.enabled
        FROM "catalog"."listing" l JOIN "catalog"."variant" v ON v.id=l.variant_id
        JOIN "catalog"."product" p ON p.id=v.product_id JOIN "scraping"."entity" e ON e.id=l.entity_id
        LEFT JOIN "scraping"."tracking_target" t ON t.entity_id=e.id
        WHERE p.public_id=:id ORDER BY l.id LIMIT :limit OFFSET :offset"""),
                {"id": product_public_id, "limit": limit, "offset": offset},
            )
        )
        .mappings()
        .all()
    )
