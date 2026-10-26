from fastapi import HTTPException
from sqlalchemy import text

from ..core.errors import NotFoundError
from .data_models import DataFilters

BASE = """
      FROM scraping.entity e
      LEFT JOIN catalog.listing l ON l.entity_id=e.id
      LEFT JOIN catalog.variant v ON v.id=l.variant_id
      LEFT JOIN catalog.product p ON p.id=v.product_id
      LEFT JOIN catalog.product_normalization n ON n.listing_id=l.id
      LEFT JOIN catalog.canonical_product c ON c.id=n.canonical_product_id AND n.status='completed'
      LEFT JOIN scraping.tracking_target t ON t.entity_id=e.id
      LEFT JOIN scraping.excluded_page x ON x.site=e.site AND x.source_key=e.source_key
      LEFT JOIN LATERAL (SELECT o.* FROM scraping.observation o
        WHERE o.entity_id=e.id AND (CAST(:request_id AS uuid) IS NULL OR EXISTS (
          SELECT 1 FROM scraping.job j JOIN scraping.scrape_request r ON r.id=j.scrape_request_id
          WHERE j.id=o.job_id AND r.public_id=:request_id))
        ORDER BY o.created_at DESC,o.id DESC LIMIT 1) latest ON true
      LEFT JOIN LATERAL (SELECT
        CASE WHEN latest.payload->'offer'->>'price' ~ '^[0-9]+([.][0-9]+)?$'
          THEN (latest.payload->'offer'->>'price')::numeric END AS amount,
        latest.payload->'offer'->>'currency' AS currency) money ON true
      WHERE (CAST(:site AS text) IS NULL OR e.site=:site)
        AND (CAST(:q AS text) IS NULL OR
          concat_ws(' ',l.title,p.title,c.name,e.source_key,t.product_url) ILIKE '%' || :q || '%')
        AND (CAST(:request_id AS uuid) IS NULL OR EXISTS (
          SELECT 1 FROM scraping.observation o JOIN scraping.job j ON j.id=o.job_id
          JOIN scraping.scrape_request r ON r.id=j.scrape_request_id
          WHERE o.entity_id=e.id AND r.public_id=:request_id))
        AND (CAST(:price_operator AS text) IS NULL OR (money.currency=:currency AND (
          (:price_operator='gt' AND money.amount>CAST(:price AS numeric)) OR
          (:price_operator='eq' AND money.amount=CAST(:price AS numeric)) OR
          (:price_operator='lt' AND money.amount<CAST(:price AS numeric)) OR
          (:price_operator='between' AND money.amount BETWEEN CAST(:price AS numeric) AND CAST(:price_to AS numeric)))))
    """


def filter_params(filters):
    params = filters.model_dump(include=set(DataFilters.model_fields))
    params["q"] = params["q"].strip() or None if params["q"] else None
    params["site"] = params["site"] or None
    return params


async def rows(session, q, site, request_id, limit, offset, filters=None):
    params = filter_params(
        filters or DataFilters(q=q, site=site, request_id=request_id)
    )
    params.update(limit=limit, offset=offset)
    base = BASE
    total = (
        await session.execute(text("SELECT count(*) " + base), params)
    ).scalar_one()
    items = (
        (
            await session.execute(
                text(
                    """
      SELECT e.public_id,e.site,e.source_key,coalesce(l.title,p.title,e.source_key) AS title,
        c.public_id AS canonical_product_id,c.name AS canonical_name,n.status AS normalization_status,
        coalesce((SELECT jsonb_agg(jsonb_build_object('id',tx.id,'name',tx.name,
          'parent_id',tx.parent_id,'parent_name',parent.name) ORDER BY parent.name NULLS FIRST,tx.name)
          FROM catalog.product_taxonomy pt JOIN catalog.taxon tx ON tx.id=pt.taxon_id
          LEFT JOIN catalog.taxon parent ON parent.id=tx.parent_id
          WHERE pt.product_id=c.id AND tx.active AND (parent.id IS NULL OR parent.active)), '[]'::jsonb) AS taxonomy,
        coalesce(l.url,t.product_url) AS url,p.brand,p.category,v.attributes,
        coalesce(t.enabled,false) AND x.site IS NULL AS enabled,
        x.site IS NOT NULL AS excluded,latest.created_at AS observed_at,
        latest.payload AS data,
        latest.payload->'offer'->'image_urls'->>0 AS image_url,
        (SELECT count(*) FROM scraping.observation o WHERE o.entity_id=e.id) AS observations,
        (SELECT string_agg(st.term, ', ' ORDER BY st.term)
          FROM scraping.search_term_entity se JOIN scraping.search_term st ON st.id=se.search_term_id
          WHERE se.entity_id=e.id) AS terms
    """
                    + base
                    + " ORDER BY latest.created_at DESC NULLS LAST,e.id DESC LIMIT :limit OFFSET :offset"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    return dict(items=items, total=total, limit=limit, offset=offset)


async def bulk_remove(session, value):
    await session.execute(text("LOCK TABLE scraping.excluded_page IN EXCLUSIVE MODE"))
    if value.all_matching:
        params = filter_params(value.filters)
        params["excluded_ids"] = list(set(value.excluded_ids))
        query = (
            "SELECT e.public_id "
            + BASE
            + " AND NOT (e.public_id=ANY(CAST(:excluded_ids AS uuid[]))) ORDER BY e.id"
        )
    else:
        params = {"ids": list(set(value.ids))}
        query = "SELECT public_id FROM scraping.entity WHERE public_id=ANY(CAST(:ids AS uuid[])) ORDER BY id"
    ids = list((await session.execute(text(query), params)).scalars())
    if len(ids) != value.expected_count:
        raise HTTPException(
            409,
            "Os resultados mudaram. Atualize a tabela e selecione novamente antes de confirmar.",
        )
    if value.action == "exclude":
        params = {"ids": ids}
        for sql in (
            "INSERT INTO scraping.excluded_page(site,source_key) SELECT site,source_key FROM scraping.entity WHERE public_id=ANY(CAST(:ids AS uuid[])) ON CONFLICT DO NOTHING",
            "UPDATE scraping.tracking_target SET enabled=false WHERE entity_id IN (SELECT id FROM scraping.entity WHERE public_id=ANY(CAST(:ids AS uuid[])))",
            """UPDATE scraping.scrape_request SET status='blocked', summary='{"reason":"page_excluded"}'::jsonb,
              completed_at=now(),lease_owner=NULL,lease_expires_at=NULL WHERE status='pending' AND tracking_target_id IN (
                SELECT t.id FROM scraping.tracking_target t JOIN scraping.entity e ON e.id=t.entity_id WHERE e.public_id=ANY(CAST(:ids AS uuid[])))""",
        ):
            await session.execute(text(sql), params)
    else:
        for public_id in ids:
            await remove(session, public_id, True)
    return {"affected": len(ids), "action": value.action}


async def remove(session, public_id, purge):
    # Serialize against product persistence, including discovery in progress.
    await session.execute(text("LOCK TABLE scraping.excluded_page IN EXCLUSIVE MODE"))
    entity = (
        (
            await session.execute(
                text("SELECT * FROM scraping.entity WHERE public_id=:id FOR UPDATE"),
                dict(id=public_id),
            )
        )
        .mappings()
        .one_or_none()
    )
    if entity is None:
        raise NotFoundError("Produto não encontrado.")
    params = dict(entity=entity["id"], site=entity["site"], key=entity["source_key"])
    if purge:
        active = (
            await session.execute(
                text("""
          SELECT count(*) FROM scraping.scrape_request r
          LEFT JOIN scraping.search_term st ON st.id=r.search_term_id
          LEFT JOIN scraping.tracking_target t ON t.id=r.tracking_target_id
          WHERE r.status='running' AND (st.site=:site OR t.entity_id=:entity)
        """),
                params,
            )
        ).scalar_one()
        if active:
            raise HTTPException(
                409,
                "Aguarde as extrações em execução nesta fonte terminarem para excluir os dados.",
            )
    await session.execute(
        text("""INSERT INTO scraping.excluded_page(site,source_key)
      VALUES (:site,:key) ON CONFLICT DO NOTHING"""),
        params,
    )
    await session.execute(
        text(
            "UPDATE scraping.tracking_target SET enabled=false WHERE entity_id=:entity"
        ),
        params,
    )
    await session.execute(
        text("""UPDATE scraping.scrape_request SET status='blocked',
      summary='{"reason":"page_excluded"}'::jsonb,completed_at=now(),lease_owner=NULL,lease_expires_at=NULL
      WHERE status='pending' AND tracking_target_id IN
        (SELECT id FROM scraping.tracking_target WHERE entity_id=:entity)"""),
        params,
    )
    if not purge:
        return {"removed": False, "excluded": True}

    async def ids(sql):
        return list((await session.execute(text(sql), params)).scalars())

    params["requests"] = await ids(
        "SELECT r.id FROM scraping.scrape_request r JOIN scraping.tracking_target t ON t.id=r.tracking_target_id WHERE t.entity_id=:entity"
    )
    params["jobs"] = await ids(
        "SELECT job_id FROM scraping.observation WHERE entity_id=:entity UNION SELECT id FROM scraping.job WHERE scrape_request_id=ANY(CAST(:requests AS bigint[]))"
    )
    params["snapshots"] = await ids(
        "SELECT html_snapshot_id FROM scraping.job WHERE id=ANY(CAST(:jobs AS bigint[])) UNION SELECT id FROM scraping.html_snapshot WHERE scrape_request_id=ANY(CAST(:requests AS bigint[]))"
    )
    params["variants"] = await ids(
        "SELECT variant_id FROM catalog.listing WHERE entity_id=:entity"
    )
    params["products"] = await ids(
        "SELECT product_id FROM catalog.variant WHERE id=ANY(CAST(:variants AS bigint[]))"
    )
    params["assets"] = await ids(
        "SELECT asset_id FROM scraping.observation_asset WHERE observation_id IN (SELECT id FROM scraping.observation WHERE entity_id=:entity) UNION SELECT asset_id FROM scraping.html_snapshot WHERE id=ANY(CAST(:snapshots AS bigint[])) AND asset_id IS NOT NULL"
    )
    statements = [
        "DELETE FROM pricing.{child} WHERE observation_id IN (SELECT po.id FROM pricing.observation po JOIN scraping.observation o ON o.id=po.source_observation_id WHERE o.entity_id=:entity)",
    ]
    for child in ("promotion", "payment_option", "shipping_quote"):
        await session.execute(text(statements[0].format(child=child)), params)
    for sql in (
        "DELETE FROM pricing.observation WHERE source_observation_id IN (SELECT id FROM scraping.observation WHERE entity_id=:entity)",
        "DELETE FROM pricing.offer WHERE listing_id IN (SELECT id FROM catalog.listing WHERE entity_id=:entity)",
        "DELETE FROM catalog.listing WHERE entity_id=:entity",
        "DELETE FROM catalog.variant v WHERE id=ANY(CAST(:variants AS bigint[])) AND NOT EXISTS (SELECT 1 FROM catalog.listing l WHERE l.variant_id=v.id)",
        "DELETE FROM catalog.product p WHERE id=ANY(CAST(:products AS bigint[])) AND NOT EXISTS (SELECT 1 FROM catalog.variant v WHERE v.product_id=p.id)",
        "DELETE FROM scraping.observation_asset WHERE observation_id IN (SELECT id FROM scraping.observation WHERE entity_id=:entity)",
        "DELETE FROM scraping.observation WHERE entity_id=:entity",
        "DELETE FROM scraping.search_term_entity WHERE entity_id=:entity",
        "DELETE FROM ai.audit_outbox WHERE interaction_id IN (SELECT id FROM ai.interaction WHERE job_id=ANY(CAST(:jobs AS bigint[])) OR html_snapshot_id=ANY(CAST(:snapshots AS bigint[])) OR scrape_request_id=ANY(CAST(:requests AS bigint[])))",
        "INSERT INTO scraping.asset_deletion(bucket,object_key) SELECT audit_bucket,audit_object_key FROM ai.interaction WHERE audit_bucket IS NOT NULL AND audit_object_key IS NOT NULL AND (job_id=ANY(CAST(:jobs AS bigint[])) OR html_snapshot_id=ANY(CAST(:snapshots AS bigint[])) OR scrape_request_id=ANY(CAST(:requests AS bigint[]))) ON CONFLICT DO NOTHING",
        "DELETE FROM ai.interaction WHERE job_id=ANY(CAST(:jobs AS bigint[])) OR html_snapshot_id=ANY(CAST(:snapshots AS bigint[])) OR scrape_request_id=ANY(CAST(:requests AS bigint[]))",
        "DELETE FROM scraping.layer_attempt WHERE job_id=ANY(CAST(:jobs AS bigint[]))",
        "DELETE FROM scraping.job WHERE id=ANY(CAST(:jobs AS bigint[]))",
        "DELETE FROM scraping.search_candidate WHERE scrape_request_id=ANY(CAST(:requests AS bigint[])) OR (source_key=:key AND scrape_request_id IN (SELECT r.id FROM scraping.scrape_request r JOIN scraping.search_term st ON st.id=r.search_term_id WHERE st.site=:site))",
        "DELETE FROM scraping.product_validation WHERE html_snapshot_id=ANY(CAST(:snapshots AS bigint[])) OR scrape_request_id=ANY(CAST(:requests AS bigint[]))",
        "DELETE FROM scraping.embedding WHERE html_snapshot_id=ANY(CAST(:snapshots AS bigint[]))",
        "UPDATE scraping.html_snapshot SET parent_snapshot_id=NULL WHERE parent_snapshot_id=ANY(CAST(:snapshots AS bigint[]))",
        "DELETE FROM scraping.html_snapshot WHERE id=ANY(CAST(:snapshots AS bigint[]))",
        "WITH removed AS (DELETE FROM scraping.asset a WHERE id=ANY(CAST(:assets AS bigint[])) AND NOT EXISTS (SELECT 1 FROM scraping.observation_asset oa WHERE oa.asset_id=a.id) AND NOT EXISTS (SELECT 1 FROM scraping.html_snapshot s WHERE s.asset_id=a.id) RETURNING bucket,object_key) INSERT INTO scraping.asset_deletion(bucket,object_key) SELECT bucket,object_key FROM removed ON CONFLICT DO NOTHING",
        "DELETE FROM scraping.extraction_log WHERE request_id=ANY(CAST(:requests AS bigint[])) OR (site=:site AND details->>'source_key'=:key)",
        "UPDATE scraping.scrape_request r SET summary=jsonb_set(r.summary,'{products}',coalesce((SELECT jsonb_agg(item) FROM jsonb_array_elements(r.summary->'products') item WHERE item->>'source_key' IS DISTINCT FROM :key),'[]'::jsonb)) FROM scraping.search_term st WHERE st.id=r.search_term_id AND st.site=:site AND jsonb_typeof(r.summary->'products')='array'",
        "DELETE FROM scraping.scrape_request WHERE id=ANY(CAST(:requests AS bigint[]))",
        "DELETE FROM scraping.tracking_target WHERE entity_id=:entity",
        "DELETE FROM scraping.entity WHERE id=:entity",
    ):
        await session.execute(text(sql), params)
    return {"removed": True, "excluded": True}
