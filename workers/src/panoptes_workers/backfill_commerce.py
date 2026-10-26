"""Populate missing commercial histories from preserved captures, without website access."""

import argparse
import asyncio
from urllib.parse import urlsplit

from panoptes_contracts.catalog import CatalogProduct
from panoptes_contracts.offers import CommercialExtraction, ProductDetail
from panoptes_database.config import load_database_settings
from panoptes_database.session import create_database, unit_of_work
from panoptes_storage.client import create_storage, load_storage_settings
from sqlalchemy import text

from .common.commerce import extract_commerce
from .workflow.catalog_repository import save_listing
from .workflow.pricing_repository import save_offer


async def capture_html(storage, uri):
    capture = urlsplit(uri)
    if capture.scheme != "s3":
        raise ValueError("unsupported_capture_uri")
    response = await storage.get_object(
        Bucket=capture.netloc, Key=capture.path.lstrip("/")
    )
    size = response["ContentLength"]
    if not 0 < size <= 6_000_000:
        raise ValueError("capture_too_large_or_empty")
    async with response["Body"] as stream:
        # read(n) may return only the currently available HTTP chunk.
        html = await stream.read()
    if len(html) != size:
        raise ValueError("incomplete_capture")
    return html


async def main(limit=100):
    engine, sessions = create_database(load_database_settings())
    saved = failed = 0
    try:
        async with sessions() as session:
            rows = (
                (
                    await session.execute(
                        text("""
                SELECT o.id,o.entity_id,o.job_id,o.payload,e.site,h.artifact_uri,h.capture_metadata
                FROM scraping.observation o JOIN scraping.entity e ON e.id=o.entity_id
                JOIN scraping.job j ON j.id=o.job_id
                JOIN scraping.html_snapshot h ON h.id=j.html_snapshot_id
                WHERE e.site IN ('amazon_br','mercado_livre_br')
                  AND NOT EXISTS(SELECT 1 FROM pricing.observation p WHERE p.source_observation_id=o.id
                    AND p.commercial_extraction IS NOT NULL
                    AND (p.commercial_extraction->>'version'='1.0.1'
                      OR jsonb_array_length(coalesce(p.commercial_extraction->'evidence','[]'::jsonb))>0))
                ORDER BY o.id LIMIT :limit
            """),
                        {"limit": limit},
                    )
                )
                .mappings()
                .all()
            )
        async with create_storage(load_storage_settings()) as storage:
            for row in rows:
                try:
                    html = await capture_html(storage, row["artifact_uri"])
                    detail = ProductDetail.model_validate(
                        {
                            k: v
                            for k, v in row["payload"].items()
                            if k in ProductDetail.model_fields
                        }
                    )
                    encoding = row["capture_metadata"].get("encoding", "utf-8")
                    detail, _ = extract_commerce(
                        detail, html.decode(encoding, errors="replace"), row["site"]
                    )
                    if detail.offer.commercial_extraction is None:
                        detail = detail.model_copy(
                            update={
                                "offer": detail.offer.model_copy(
                                    update={
                                        "commercial_extraction": CommercialExtraction()
                                    }
                                )
                            }
                        )
                    if detail.catalog is None:
                        detail = detail.model_copy(
                            update={"catalog": CatalogProduct(category="other")}
                        )
                    async with unit_of_work(sessions) as session:
                        listing = await save_listing(
                            session, row["entity_id"], detail, row["site"]
                        )
                        await save_offer(
                            session,
                            listing,
                            detail.offer,
                            row["id"],
                            row["job_id"],
                            enrich_existing=True,
                        )
                    saved += 1
                except Exception as error:
                    failed += 1
                    # Captures and account content never appear in maintenance logs.
                    print(
                        f"Observation {row['id']}: {type(error).__name__}", flush=True
                    )
        print(f"Commercial histories added: {saved}; failed: {failed}", flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000:
        parser.error("limit must be between 1 and 10000")
    asyncio.run(main(args.limit))
