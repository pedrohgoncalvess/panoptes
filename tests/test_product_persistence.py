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
from panoptes_workers.amazon.product import parse_catalog_product
from panoptes_workers.workflow import capture_repository, product_repository
from sqlalchemy import text


@pytest.mark.integration
@pytest.mark.parametrize("unclassified", [False, True])
async def test_product_persistence_creates_tracking_and_offer_with_integer_interval(
    unclassified,
):
    url = os.getenv("TEST_WORKFLOW_DATABASE_URL")
    if not url:
        pytest.skip(
            "Requires TEST_WORKFLOW_DATABASE_URL pointing to migrated PostgreSQL"
        )
    engine, sessions = create_database(DatabaseSettings(url, 1, 2))
    html = (
        Path(__file__).resolve().parents[1] / "workers/parsers/amazon-book/product.html"
    ).read_bytes()
    detail = parse_catalog_product(
        html, "https://www.amazon.com.br/dp/1492040347", "1492040347", "book"
    )
    from panoptes_workers.common.commerce import extract_commerce

    detail, _ = extract_commerce(
        detail,
        '<div id="pixPrice">R$ 40,00 no Pix</div><div id="installment_feature_div">2x de R$ 25,00 sem juros</div>'
        '<div id="couponFeature">Ative cupom: BOOK10 de 10% de desconto, acima de R$ 30,00</div>',
        "amazon_br",
    )
    if unclassified:
        detail = detail.model_copy(update={"catalog": None})
    try:
        async with sessions() as session:
            async with session.begin():
                term = str(uuid4())
                term_id = (
                    await session.execute(
                        text("""
                    INSERT INTO scraping.search_term
                    (site,term,normalized_term,criteria)
                    VALUES ('amazon_br',:term,:term,'{}') RETURNING id
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
                routine, _ = await product_repository.register_runtime(session)
                job = ExtractionJob(
                    public_id=uuid4(),
                    correlation_id=request["correlation_id"],
                    routine_id=routine["public_id"],
                    routine_version="1.0.0",
                    snapshot=snapshot,
                    parser_slug="amazon-product",
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
                    {"id": term_id, "criteria": {}, "refresh_interval_seconds": 86400},
                    detail.model_copy(
                        update={
                            "offer": detail.offer.model_copy(
                                update={
                                    "commercial_extraction": None,
                                    "payment_options": (),
                                    "promotions": (),
                                }
                            )
                        }
                    ),
                    job_id,
                    result,
                    [],
                )
                from panoptes_workers.workflow.pricing_repository import save_offer

                legacy = (
                    (
                        await session.execute(
                            text("""
                    SELECT p.source_observation_id,f.listing_id,o.payload
                    FROM pricing.observation p JOIN pricing.offer f ON f.id=p.offer_id
                    JOIN scraping.observation o ON o.id=p.source_observation_id WHERE o.job_id=:job
                """),
                            {"job": job_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                for _ in range(2):
                    await save_offer(
                        session,
                        legacy["listing_id"],
                        detail.offer,
                        legacy["source_observation_id"],
                        job_id,
                        enrich_existing=True,
                    )
                original = (
                    await session.execute(
                        text("SELECT payload FROM scraping.observation WHERE id=:id"),
                        {"id": legacy["source_observation_id"]},
                    )
                ).scalar_one()
                assert original == legacy["payload"]
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
                assert (
                    next(p for p in offer["payment_options"] if p["method"] == "pix")[
                        "total_price"
                    ]
                    == "40.0000"
                )
                historical = offer["history"][0]
                assert next(
                    p
                    for p in historical["payment_options"]
                    if p["method"] == "installment"
                )["total_is_derived"]
                assert any(p["code"] == "BOOK10" for p in historical["promotions"])
                assert historical["commercial_extraction"]["evidence"]
                view_count = (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM pricing.payment_history WHERE source_key=:key"
                        ),
                        {"key": detail.entity.source_key},
                    )
                ).scalar_one()
                assert view_count >= 2
                from panoptes_backend.management import data_repository

                entity_public_id = product["public_id"]
                data = await data_repository.rows(
                    session, None, "amazon_br", request["public_id"], 25, 0
                )
                assert data["total"] == 1
                assert data["items"][0]["observations"] == 1
                shared = (
                    await session.execute(
                        text("""INSERT INTO scraping.entity(site,source_key,kind)
                    VALUES ('amazon_br',:key,'product') RETURNING id"""),
                        {"key": "shared-" + str(uuid4())},
                    )
                ).scalar_one()
                await session.execute(
                    text("""INSERT INTO catalog.listing(entity_id,variant_id,url,title)
                    SELECT :shared,variant_id,'https://example.com/shared','Shared page'
                    FROM catalog.listing WHERE id=:listing"""),
                    {"shared": shared, "listing": legacy["listing_id"]},
                )
                await data_repository.remove(session, entity_public_id, False)
                assert (
                    await data_repository.rows(
                        session, None, None, request["public_id"], 25, 0
                    )
                )["items"][0]["excluded"]
                await data_repository.remove(session, entity_public_id, True)
                assert (
                    await data_repository.rows(
                        session, None, None, request["public_id"], 25, 0
                    )
                )["total"] == 0
                assert (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM scraping.observation WHERE job_id=:job"
                        ),
                        {"job": job_id},
                    )
                ).scalar_one() == 0
                assert (
                    await session.execute(
                        text("""SELECT count(*) FROM catalog.listing l
                    JOIN catalog.variant v ON v.id=l.variant_id JOIN catalog.product p ON p.id=v.product_id
                    WHERE l.entity_id=:shared"""),
                        {"shared": shared},
                    )
                ).scalar_one() == 1
                # The independent exclusion survives deletion and prevents re-creation.
                await product_repository.save_product(
                    session,
                    request,
                    {"id": term_id, "criteria": {}, "refresh_interval_seconds": 86400},
                    detail,
                    job_id,
                    result,
                    [],
                )
                assert (
                    await data_repository.rows(
                        session, None, None, request["public_id"], 25, 0
                    )
                )["total"] == 0
                await session.rollback()
    finally:
        await engine.dispose()
