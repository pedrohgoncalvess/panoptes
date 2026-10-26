import asyncio
import json
from uuid import uuid4

from panoptes_contracts import (
    ExtractionPolicy,
    Layer,
    ParserManifest,
    RoutineDefinition,
)
from sqlalchemy import text

from ..sources import ADAPTERS, get_source


async def register_runtime(session, site="amazon_br"):
    source = get_source(site)
    slug = source.definition.parser_slug
    workflow_slug = (
        f"{slug}-workflow" if site != "amazon_br" else "amazon-product-workflow"
    )
    definition = RoutineDefinition(
        public_id=uuid4(),
        version="1.0.0",
        name=f"{source.definition.name} product workflow",
        site=site,
        entity_kind="product",
        seed_urls=(source.search_url("produtos"),),
        allowed_hosts=source.definition.page_hosts,
        parser_slug=slug,
        parser_version=source.parser_version,
        interval_seconds=86400,
        policy=ExtractionPolicy(layers=(Layer.SITE_PARSER,)),
    )
    from pathlib import Path

    manifest_path = (
        Path(__file__).resolve().parents[3] / "parsers" / slug / "manifest.json"
    )
    if not manifest_path.exists():
        manifest_path = Path(f"/app/workers/parsers/{slug}/manifest.json")
    manifest = ParserManifest.model_validate_json(
        await asyncio.to_thread(manifest_path.read_text, encoding="utf-8")
    )
    routine = (
        (
            await session.execute(
                text("""INSERT INTO "scraping"."routine" (public_id, slug, version, definition)
        VALUES (:public_id, :slug, '1.0.0', CAST(:definition AS jsonb))
        ON CONFLICT (slug, version) DO UPDATE SET slug = EXCLUDED.slug RETURNING id, public_id"""),
                {
                    "public_id": definition.public_id,
                    "slug": workflow_slug,
                    "definition": definition.model_dump_json(),
                },
            )
        )
        .mappings()
        .one()
    )
    parser = (
        await session.execute(
            text("""INSERT INTO "scraping"."parser" (slug, version, manifest)
        VALUES (:slug, :version, CAST(:manifest AS jsonb))
        ON CONFLICT (slug, version) DO UPDATE SET slug = EXCLUDED.slug RETURNING id"""),
            {
                "slug": slug,
                "version": source.parser_version,
                "manifest": manifest.model_dump_json(),
            },
        )
    ).scalar_one()
    return routine, parser


async def save_job(session, request, job, snapshot_internal_id, result):
    site = next(
        source.definition.id
        for source in ADAPTERS.values()
        if source.definition.parser_slug == job.parser_slug
    )
    routine, parser = await register_runtime(session, site)
    internal_id = (
        await session.execute(
            text("""INSERT INTO "scraping"."job"
        (public_id, routine_id, parser_id, html_snapshot_id, correlation_id,
         idempotency_key, policy, status, completed_at, scrape_request_id)
        VALUES (:public_id, :routine, :parser, :snapshot, :correlation,
                :key, CAST(:policy AS jsonb), :status, :completed, :request)
        ON CONFLICT (idempotency_key) DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
        RETURNING id"""),
            {
                "public_id": job.public_id,
                "routine": routine["id"],
                "parser": parser,
                "snapshot": snapshot_internal_id,
                "correlation": job.correlation_id,
                "key": job.idempotency_key,
                "policy": job.policy.model_dump_json(),
                "status": result.status,
                "completed": result.completed_at,
                "request": request["id"],
            },
        )
    ).scalar_one()
    for attempt in result.attempts:
        await session.execute(
            text("""INSERT INTO "scraping"."layer_attempt" (job_id, layer, result, duration_ms)
            VALUES (:job, :layer, CAST(:result AS jsonb), :duration)"""),
            {
                "job": internal_id,
                "layer": attempt.layer.value,
                "result": attempt.outcome.model_dump_json(),
                "duration": attempt.duration_ms,
            },
        )
    return internal_id


async def save_product(
    session, request, context, detail, job_internal_id, result, assets
):
    await session.execute(text("LOCK TABLE scraping.excluded_page IN SHARE MODE"))
    excluded = (
        await session.execute(
            text("""SELECT 1 FROM scraping.excluded_page
        WHERE site=:site AND source_key=:key"""),
            {"site": context.get("site", "amazon_br"), "key": detail.entity.source_key},
        )
    ).scalar_one_or_none()
    if excluded:
        return
    entity_id = (
        await session.execute(
            text("""INSERT INTO "scraping"."entity" (site, source_key, kind)
        VALUES (:site, :key, 'product') ON CONFLICT (site, source_key)
        DO UPDATE SET source_key = EXCLUDED.source_key RETURNING id"""),
            {"site": context.get("site", "amazon_br"), "key": detail.entity.source_key},
        )
    ).scalar_one()
    if request["mode"] == "discover":
        await session.execute(
            text("""INSERT INTO "scraping"."search_term_entity" (search_term_id, entity_id)
            VALUES (:term, :entity) ON CONFLICT DO NOTHING"""),
            {"term": context["id"], "entity": entity_id},
        )
        await session.execute(
            text("""INSERT INTO "scraping"."tracking_target"
            (entity_id, product_url, criteria, refresh_interval_seconds, next_poll_at)
            VALUES (:entity, :url, CAST(:criteria AS jsonb), :interval,
                    now() + CAST(:interval AS integer) * interval '1 second') ON CONFLICT (entity_id) DO NOTHING"""),
            {
                "entity": entity_id,
                "url": str(detail.entity.url),
                "criteria": json.dumps(context["criteria"]),
                "interval": context["refresh_interval_seconds"],
            },
        )
    payload = detail.model_dump(mode="json")
    payload["assets"] = [
        {
            "public_id": str(row["public_id"]),
            "uri": row["uri"],
            "source_url": row["source_url"],
            "kind": row["kind"],
        }
        for row in assets
    ]
    observation_id = (
        await session.execute(
            text("""INSERT INTO "scraping"."observation"
        (entity_id, job_id, payload, evidence) VALUES (:entity, :job, CAST(:payload AS jsonb), CAST(:evidence AS jsonb))
        ON CONFLICT (entity_id, job_id) DO UPDATE SET payload = EXCLUDED.payload RETURNING id"""),
            {
                "entity": entity_id,
                "job": job_internal_id,
                "payload": json.dumps(payload),
                "evidence": json.dumps(
                    [
                        e.model_dump(mode="json")
                        for a in result.attempts
                        for e in a.outcome.evidence
                    ]
                ),
            },
        )
    ).scalar_one()
    from panoptes_contracts.catalog import CatalogProduct

    from .catalog_repository import save_listing
    from .pricing_repository import save_offer

    catalog_detail = (
        detail
        if detail.catalog
        else detail.model_copy(update={"catalog": CatalogProduct(category="other")})
    )
    listing_id = await save_listing(
        session, entity_id, catalog_detail, context.get("site", "amazon_br")
    )
    await save_offer(session, listing_id, detail.offer, observation_id, job_internal_id)
    from ..normalization import enqueue

    await enqueue(session, listing_id, payload)
    for asset in assets:
        await session.execute(
            text("""INSERT INTO "scraping"."observation_asset" (observation_id, asset_id)
            VALUES (:observation, :asset) ON CONFLICT DO NOTHING"""),
            {"observation": observation_id, "asset": asset["id"]},
        )
