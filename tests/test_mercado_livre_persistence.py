"""Opt-in persistence regression on a migrated PostgreSQL database; always rollback."""

import hashlib
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from panoptes_backend.management import repository as management_repository
from panoptes_contracts import ExtractionJob, ExtractionPolicy, HtmlSnapshot, Layer
from panoptes_database.config import DatabaseSettings
from panoptes_database.session import create_database
from panoptes_workers.mercado_livre.product import parse_catalog_product
from panoptes_workers.workflow import capture_repository, product_repository
from sqlalchemy import text


@pytest.mark.integration
async def test_mercado_livre_persists_catalog_offer_and_source_specific_tracking():
    url = os.getenv("TEST_WORKFLOW_DATABASE_URL")
    if not url:
        pytest.skip(
            "Requires TEST_WORKFLOW_DATABASE_URL pointing to migrated PostgreSQL"
        )
    engine, sessions = create_database(DatabaseSettings(url, 1, 2))
    html = (
        Path(__file__).resolve().parents[1]
        / "workers/parsers/mercado-livre-product/book.html"
    ).read_bytes()
    detail = parse_catalog_product(
        html,
        "https://produto.mercadolivre.com.br/MLB-1234567890-livro-cto-_JM",
        "MLB1234567890",
        "book",
    )
    try:
        async with sessions() as session:
            async with session.begin():
                term = str(uuid4())
                term_id = (
                    await session.execute(
                        text("""
                    INSERT INTO scraping.search_term
                    (site,term,normalized_term,criteria)
                    VALUES ('mercado_livre_br',:term,:term,'{}') RETURNING id
                """),
                        {"term": term},
                    )
                ).scalar_one()
                request = dict(
                    (
                        await session.execute(
                            text("""
                    INSERT INTO scraping.scrape_request (mode,search_term_id)
                    VALUES ('discover',:term) RETURNING *
                """),
                            {"term": term_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                snapshot = HtmlSnapshot(
                    public_id=uuid4(),
                    source_url=str(detail.entity.url),
                    final_url=str(detail.entity.url),
                    captured_at=datetime.now(timezone.utc),
                    sha256=hashlib.sha256(html).hexdigest(),
                    byte_qt=len(html),
                    artifact_uri="s3://regression/product.html",
                    http_status=200,
                    capture_mode="http",
                    encoding="utf-8",
                )
                snapshot_id = await capture_repository.save_snapshot(
                    session, snapshot, None, request["id"]
                )
                routine, _ = await product_repository.register_runtime(
                    session, "mercado_livre_br"
                )
                job = ExtractionJob(
                    public_id=uuid4(),
                    correlation_id=request["correlation_id"],
                    routine_id=routine["public_id"],
                    routine_version="1.0.0",
                    snapshot=snapshot,
                    parser_slug="mercado-livre-product",
                    parser_version="1.0.0",
                    policy=ExtractionPolicy(layers=(Layer.SITE_PARSER,)),
                    idempotency_key="regression:" + str(uuid4()),
                )
                result = SimpleNamespace(
                    status="completed",
                    completed_at=datetime.now(timezone.utc),
                    attempts=(),
                )
                job_id = await product_repository.save_job(
                    session, request, job, snapshot_id, result
                )
                await product_repository.save_product(
                    session,
                    request,
                    {
                        "site": "mercado_livre_br",
                        "id": term_id,
                        "criteria": {},
                        "refresh_interval_seconds": 86400,
                    },
                    detail,
                    job_id,
                    result,
                    [],
                )
                row = (
                    (
                        await session.execute(
                            text("""
                    SELECT t.refresh_interval_seconds,
                        extract(epoch FROM (t.next_poll_at - now())) AS delay,
                        p.price_vl
                    FROM scraping.observation o
                    JOIN scraping.tracking_target t ON t.entity_id=o.entity_id
                    JOIN pricing.observation p ON p.source_observation_id=o.id
                    WHERE o.job_id=:job
                """),
                            {"job": job_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                assert row["refresh_interval_seconds"] == 86400
                assert row["delay"] == 86400
                assert row["price_vl"] == detail.offer.price
                prices = await management_repository.prices(session, term_id, 24, 0)
                assert prices["total"] == 1
                product = prices["items"][0]
                assert product["image_urls"] == [
                    str(url) for url in detail.offer.image_urls
                ]
                offer = product["offers"][0]
                assert offer["price"] == str(
                    detail.offer.price.quantize(Decimal("0.0001"))
                )
                assert offer["lowest_price"] == offer["price"]
                assert offer["previous_price"] is None
                assert offer["history"][0]["price"] == offer["price"]
                await session.rollback()
    finally:
        await engine.dispose()
