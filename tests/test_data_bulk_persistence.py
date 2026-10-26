"""Bulk selection and decimal filtering against an isolated migrated PostgreSQL."""

import json
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from panoptes_backend.management import data_repository as data
from panoptes_backend.management.data_models import BulkDataAction, DataFilters
from panoptes_database.config import DatabaseSettings
from panoptes_database.session import create_database
from sqlalchemy import text


@pytest.mark.integration
async def test_price_filters_and_bulk_selection_across_pages():
    url = os.getenv("TEST_WORKFLOW_DATABASE_URL")
    if not url:
        pytest.skip("Requires migrated disposable TEST_WORKFLOW_DATABASE_URL")
    engine, sessions = create_database(DatabaseSettings(url, 1, 2))
    try:
        async with sessions() as session:
            async with session.begin():
                site = "data-test-" + uuid4().hex

                async def scalar(sql, **params):
                    return (await session.execute(text(sql), params)).scalar_one()

                term = await scalar(
                    "INSERT INTO scraping.search_term(site,term,normalized_term,criteria) VALUES (:site,'test',:site,'{}') RETURNING id",
                    site=site,
                )
                request = await scalar(
                    "INSERT INTO scraping.scrape_request(mode,search_term_id,status) VALUES ('discover',:term,'completed') RETURNING id",
                    term=term,
                )
                request_public = await scalar(
                    "SELECT public_id FROM scraping.scrape_request WHERE id=:id",
                    id=request,
                )
                routine = await scalar(
                    "INSERT INTO scraping.routine(slug,version,definition) VALUES (:slug,'1','{}') RETURNING id",
                    slug=site,
                )
                parser = await scalar(
                    "INSERT INTO scraping.parser(slug,version,manifest) VALUES (:slug,'1','{}') RETURNING id",
                    slug=site,
                )
                pages = []
                for index, (price, currency) in enumerate(
                    [
                        ("0", "BRL"),
                        ("10.10", "BRL"),
                        ("20.20", "BRL"),
                        ("30.30", "BRL"),
                        (None, "BRL"),
                        ("10.10", "USD"),
                    ]
                ):
                    entity = await scalar(
                        "INSERT INTO scraping.entity(site,source_key,kind) VALUES (:site,:key,'product') RETURNING id",
                        site=site,
                        key=f"item-{index}",
                    )
                    pages.append(
                        await scalar(
                            "SELECT public_id FROM scraping.entity WHERE id=:id",
                            id=entity,
                        )
                    )
                    snapshot = await scalar(
                        "INSERT INTO scraping.html_snapshot(source_url,final_url,sha256,artifact_uri,capture_metadata,captured_at,scrape_request_id) VALUES ('https://example.com','https://example.com',:sha,:uri,'{}',now(),:request) RETURNING id",
                        sha="a" * 64,
                        uri=f"s3://test/{index}",
                        request=request,
                    )
                    job = await scalar(
                        "INSERT INTO scraping.job(routine_id,parser_id,html_snapshot_id,correlation_id,idempotency_key,policy,status,scrape_request_id) VALUES (:routine,:parser,:snapshot,:correlation,:key,'{}','completed',:request) RETURNING id",
                        routine=routine,
                        parser=parser,
                        snapshot=snapshot,
                        correlation=uuid4(),
                        key=f"{site}-{index}",
                        request=request,
                    )
                    await session.execute(
                        text(
                            "INSERT INTO scraping.observation(entity_id,job_id,payload,evidence) VALUES (:entity,:job,CAST(:payload AS jsonb),'[]')"
                        ),
                        dict(
                            entity=entity,
                            job=job,
                            payload=json.dumps(
                                {
                                    "offer": {
                                        "price": price,
                                        "currency": currency,
                                        "image_urls": ["https://example.com/image.png"],
                                    }
                                }
                            ),
                        ),
                    )
                    await session.execute(
                        text(
                            "INSERT INTO scraping.tracking_target(entity_id,product_url,criteria,refresh_interval_seconds) VALUES (:entity,'https://example.com','{}',86400)"
                        ),
                        dict(entity=entity),
                    )

                async def filtered(operator=None, price=None, price_to=None):
                    filters = DataFilters(
                        site=site,
                        request_id=request_public,
                        price_operator=operator,
                        price=price,
                        price_to=price_to,
                    )
                    return await data.rows(
                        session, None, site, request_public, 1, 0, filters=filters
                    )

                assert (await filtered())["total"] == 6
                assert (await filtered("gt", "10.10"))["total"] == 2
                assert (await filtered("eq", "10.1000"))["total"] == 1
                assert (await filtered("lt", "10.10"))["total"] == 1
                assert (await filtered("between", "10.10", "20.20"))["total"] == 2
                assert (await filtered("eq", "0"))["total"] == 1
                assert (await filtered())["items"][0][
                    "image_url"
                ] == "https://example.com/image.png"

                selected = BulkDataAction(
                    action="exclude",
                    all_matching=True,
                    filters=DataFilters(
                        site=site,
                        price_operator="between",
                        price="10.10",
                        price_to="30.30",
                    ),
                    excluded_ids=[pages[2]],
                    expected_count=2,
                )
                assert (await data.bulk_remove(session, selected))["affected"] == 2
                assert (
                    await scalar(
                        "SELECT count(*) FROM scraping.excluded_page WHERE site=:site",
                        site=site,
                    )
                    == 2
                )
                assert await scalar(
                    "SELECT enabled FROM scraping.tracking_target t JOIN scraping.entity e ON e.id=t.entity_id WHERE e.public_id=:id",
                    id=pages[2],
                )
                assert (await filtered())["total"] == 6
                # A changed result count prevents any partial mutation.
                with pytest.raises(HTTPException) as error:
                    await data.bulk_remove(
                        session,
                        BulkDataAction(
                            action="purge", ids=[pages[0], uuid4()], expected_count=2
                        ),
                    )
                assert error.value.status_code == 409
                assert (await filtered())["total"] == 6
                # If a later page is running, the whole batch rolls back.
                async with session.begin_nested() as savepoint:
                    await session.execute(
                        text(
                            "INSERT INTO scraping.scrape_request(mode,tracking_target_id,status) SELECT 'refresh',t.id,'running' FROM scraping.tracking_target t JOIN scraping.entity e ON e.id=t.entity_id WHERE e.public_id=:id"
                        ),
                        dict(id=pages[2]),
                    )
                    with pytest.raises(HTTPException):
                        await data.bulk_remove(
                            session,
                            BulkDataAction(
                                action="purge",
                                ids=[pages[0], pages[2]],
                                expected_count=2,
                            ),
                        )
                    await savepoint.rollback()
                assert (await filtered())["total"] == 6
                result = await data.bulk_remove(
                    session,
                    BulkDataAction(
                        action="purge",
                        all_matching=True,
                        filters=DataFilters(
                            site=site,
                            price_operator="between",
                            price="10.10",
                            price_to="30.30",
                        ),
                        expected_count=3,
                    ),
                )
                assert result["affected"] == 3
                assert (await filtered())["total"] == 3
                assert (await filtered("eq", "10.10"))["total"] == 0
                await session.rollback()
    finally:
        await engine.dispose()
