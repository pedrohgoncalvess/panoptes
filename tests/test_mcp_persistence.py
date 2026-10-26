"""Database behavior that cannot be established with mocked repositories."""

import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from panoptes_backend.catalog import repository, services
from panoptes_backend.catalog.models import SearchTermCreate, SearchTermsCreate
from panoptes_backend.catalog.search import ProductQuery, search_products
from panoptes_backend.core.errors import ConflictError
from panoptes_database.config import DatabaseSettings
from panoptes_database.session import create_database
from sqlalchemy import text


def database():
    url = os.getenv("TEST_WORKFLOW_DATABASE_URL")
    if not url:
        pytest.skip("Requires disposable migrated PostgreSQL with pgvector")
    return create_database(DatabaseSettings(url, 1, 2))


@pytest.mark.integration
async def test_batch_conflict_rolls_back_terms_and_queued_work():
    engine, sessions = database()
    try:
        async with sessions() as session, session.begin():
            term = "mcp-" + uuid4().hex
            await services.create_term(
                session, SearchTermCreate(term=term, site="pichau_br", max_pages=2)
            )
            value = SearchTermsCreate(
                term=term, sites=["kabum_br", "pichau_br"], discover=True
            )
            with pytest.raises(ConflictError):
                async with session.begin_nested():
                    await services.create_terms(session, value, str(uuid4()))
            terms = await repository.list_terms(session, 100, 0, q=term)
            assert [row["site"] for row in terms] == ["pichau_br"]
            count = (
                await session.execute(
                    text("""
                SELECT count(*) FROM scraping.scrape_request r
                JOIN scraping.search_term t ON t.id=r.search_term_id WHERE t.term=:term
            """),
                    {"term": term},
                )
            ).scalar_one()
            assert count == 0
            # Successful retries reuse both term IDs and active queued requests.
            value = value.model_copy(update={"max_pages": 2})
            first = await services.create_terms(session, value, str(uuid4()))
            second = await services.create_terms(session, value, str(uuid4()))
            assert [t["public_id"] for t in first["terms"]] == [
                t["public_id"] for t in second["terms"]
            ]
            assert [r["public_id"] for r in first["requests"]] == [
                r["public_id"] for r in second["requests"]
            ]
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_search_period_ranking_exact_term_and_pagination():
    engine, sessions = database()
    try:
        async with sessions() as session, session.begin():
            slug = "mcp-" + uuid4().hex

            async def scalar(sql, **params):
                return (await session.execute(text(sql), params)).scalar_one()

            term = await services.create_term(
                session, SearchTermCreate(term=slug, site="kabum_br")
            )
            internal = (await repository.find_term(session, term["public_id"]))["id"]
            routine = await scalar(
                "INSERT INTO scraping.routine(slug,version,definition) VALUES (:slug,'1','{}') RETURNING id",
                slug=slug,
            )
            parser = await scalar(
                "INSERT INTO scraping.parser(slug,version,manifest) VALUES (:slug,'1','{}') RETURNING id",
                slug=slug,
            )
            entity = await scalar(
                "INSERT INTO scraping.entity(site,source_key,kind) VALUES ('kabum_br',:key,'product') RETURNING id",
                key=slug,
            )
            public = await scalar(
                "SELECT public_id FROM scraping.entity WHERE id=:id", id=entity
            )
            await session.execute(
                text(
                    "INSERT INTO scraping.search_term_entity(search_term_id,entity_id) VALUES (:term,:entity)"
                ),
                {"term": internal, "entity": entity},
            )
            for index, day in enumerate([1, 15, 20]):
                snapshot = await scalar(
                    "INSERT INTO scraping.html_snapshot(source_url,final_url,sha256,artifact_uri,capture_metadata,captured_at) VALUES ('https://example.com','https://example.com',:sha,:uri,'{}',now()) RETURNING id",
                    sha="a" * 64,
                    uri=f"s3://test/{slug}/{index}",
                )
                job = await scalar(
                    "INSERT INTO scraping.job(routine_id,parser_id,html_snapshot_id,correlation_id,idempotency_key,policy,status) VALUES (:routine,:parser,:snapshot,:correlation,:key,'{}','completed') RETURNING id",
                    routine=routine,
                    parser=parser,
                    snapshot=snapshot,
                    correlation=uuid4(),
                    key=f"{slug}-{index}",
                )
                await session.execute(
                    text(
                        "INSERT INTO scraping.observation(entity_id,job_id,payload,evidence,created_at) VALUES (:entity,:job,CAST(:payload AS jsonb),'[]',:at)"
                    ),
                    {
                        "entity": entity,
                        "job": job,
                        "payload": json.dumps(
                            {
                                "entity": {
                                    "title": "GPU",
                                    "description": "placa de vídeo",
                                },
                                "offer": {"price": str(day)},
                            }
                        ),
                        "at": datetime(2026, 10, day, tzinfo=UTC),
                    },
                )
            await session.execute(
                text(
                    "INSERT INTO catalog.product_search(entity_id,model,document_hash,document,embedding) VALUES (:id,'mcp-test',:hash,'GPU',CAST(:vector AS extensions.vector))"
                ),
                {"id": entity, "hash": "a" * 64, "vector": str([1.0] + [0.0] * 383)},
            )
            service = MagicMock(agent=None, version="mcp-test")
            service.configure = AsyncMock()
            service.encode = AsyncMock(return_value=[[1.0] + [0.0] * 383])
            filters = ProductQuery(
                q="GPU",
                term_id=term["public_id"],
                site="kabum_br",
                start_at=datetime(2026, 10, 1, tzinfo=UTC),
                end_at=datetime(2026, 10, 20, tzinfo=UTC),
            )
            result = await search_products(session, service, filters)
            assert result["total"] == 1
            assert result["items"][0]["public_id"] == public
            assert result["items"][0]["data"]["offer"]["price"] == "15"
            assert result["items"][0]["similarity"] == pytest.approx(1)
            page = await search_products(
                session, service, filters.model_copy(update={"offset": 100})
            )
            assert page["items"] == [] and page["total"] == 1
            # A different configuration of the same textual term must not leak in.
            other = await services.create_term(
                session, SearchTermCreate(term=slug, site="pichau_br")
            )
            assert (
                await search_products(
                    session,
                    service,
                    filters.model_copy(update={"term_id": other["public_id"]}),
                )
            )["total"] == 0
            for mode in ["text", "recent"]:
                result = await search_products(
                    session,
                    service,
                    filters.model_copy(
                        update={"mode": mode, "q": "GPU" if mode == "text" else None}
                    ),
                )
                assert result["total"] == 1
                assert result["items"][0]["data"]["offer"]["price"] == "15"
            await session.rollback()
    finally:
        await engine.dispose()
