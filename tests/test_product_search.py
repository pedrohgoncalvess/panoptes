import os
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth.router import current_user
from panoptes_backend.catalog.product_search import (
    VERSION,
    ProductSearch,
    document,
    fingerprint,
)
from panoptes_backend.catalog.router import session_dependency
from panoptes_backend.main import create_app
from panoptes_database.config import DatabaseSettings
from panoptes_database.session import create_database
from sqlalchemy import text


def test_document_includes_names_categories_and_description_and_changes_hash():
    row = dict(
        title="Geladeira 50L",
        catalog_title="Refrigerador compacto",
        extracted_title="Frigobar",
        category="refrigerator",
        categories="Eletrodomésticos",
        description="Conserva alimentos com baixo consumo de energia.",
        brand="Marca",
        source_key="MLB123",
        cookies="SECRET",
        account="PRIVATE",
    )
    value = document(row)
    for field in (
        "title",
        "catalog_title",
        "extracted_title",
        "categories",
        "description",
        "brand",
    ):
        assert row[field] in value
    assert "SECRET" not in value and "PRIVATE" not in value
    assert fingerprint(value) != fingerprint(
        document({**row, "description": "Nova descrição"})
    )
    assert document({"source_key": "MLB123"}) == "MLB123"


async def test_search_route_passes_query_scope_and_selection():
    app = create_app()
    marker = object()
    app.dependency_overrides[current_user] = lambda: {"name": "test"}

    async def session():
        yield marker

    app.dependency_overrides[session_dependency] = session
    app.state.product_search = service = AsyncMock()
    service.search.return_value = []
    term, selected = uuid4(), uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/analytics/prices/products",
            params={
                "q": "refrigerador",
                "term_id": str(term),
                "site": "amazon_br",
                "selected": str(selected),
            },
        )
        assert response.status_code == 200
        assert (
            await client.get("/analytics/prices/products", params={"q": "x" * 301})
        ).status_code == 422
    service.search.assert_awaited_once_with(
        marker, "refrigerador", term, "amazon_br", selected
    )


@pytest.mark.integration
async def test_vector_ranking_scope_and_selected_product():
    url = os.getenv("TEST_WORKFLOW_DATABASE_URL")
    if not url:
        pytest.skip("Requires disposable migrated PostgreSQL")
    engine, sessions = create_database(DatabaseSettings(url, 1, 2))
    service = ProductSearch(sessions)
    service.encode = AsyncMock(return_value=[[1.0] + [0.0] * 383])
    try:
        async with sessions() as session:
            async with session.begin():
                rows = []
                for site, vector, name in [
                    ("amazon_br", [1.0] + [0.0] * 383, "Geladeira econômica"),
                    ("amazon_br", [0.0, 1.0] + [0.0] * 382, "Livro"),
                    ("mercado_livre_br", [1.0] + [0.0] * 383, "Geladeira grande"),
                ]:
                    row = (
                        (
                            await session.execute(
                                text("""
                      INSERT INTO scraping.entity(site,source_key,kind) VALUES (:site,:key,'product')
                      RETURNING id,public_id
                    """),
                                {"site": site, "key": uuid4().hex},
                            )
                        )
                        .mappings()
                        .one()
                    )
                    await session.execute(
                        text("""
                      INSERT INTO catalog.product_search(entity_id,model,document_hash,document,embedding)
                      VALUES (:id,:model,:hash,:document,CAST(:vector AS extensions.vector))
                    """),
                        {
                            "id": row["id"],
                            "model": VERSION,
                            "hash": fingerprint(name),
                            "document": name,
                            "vector": str(vector),
                        },
                    )
                    rows.append(row)
                result = await service.search(session, "refrigerador", site="amazon_br")
                assert [row["public_id"] for row in result] == [rows[0]["public_id"]]
                result = await service.search(
                    session,
                    "refrigerador",
                    site="amazon_br",
                    selected=rows[1]["public_id"],
                )
                assert [row["public_id"] for row in result] == [
                    rows[1]["public_id"],
                    rows[0]["public_id"],
                ]
                assert result[1]["similarity"] == pytest.approx(1)
                # The document query works for products without a catalog listing.
                from panoptes_backend.catalog.product_search import DOCUMENTS

                documents = (
                    (await session.execute(text(DOCUMENTS), {"after": 0}))
                    .mappings()
                    .all()
                )
                assert len(documents) == 3
                await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_backfill_is_incremental_and_reindexes_changed_documents():
    url = os.getenv("TEST_WORKFLOW_DATABASE_URL")
    if not url:
        pytest.skip("Requires disposable migrated PostgreSQL")
    engine, sessions = create_database(DatabaseSettings(url, 1, 2))
    service = ProductSearch(sessions)
    service.encode = AsyncMock(return_value=[[1.0] + [0.0] * 383])
    entity_id = None
    try:
        async with sessions.begin() as session:
            entity_id = (
                await session.execute(
                    text("""
              INSERT INTO scraping.entity(site,source_key,kind) VALUES ('amazon_br',:key,'product') RETURNING id
            """),
                    {"key": uuid4().hex},
                )
            ).scalar_one()
        assert await service.refresh() == 1
        assert await service.refresh() == 0
        service.encode.assert_awaited_once()
        async with sessions.begin() as session:
            await session.execute(
                text("UPDATE scraping.entity SET source_key=:key WHERE id=:id"),
                {"key": uuid4().hex, "id": entity_id},
            )
        assert await service.refresh() == 1
        assert service.encode.await_count == 2
        async with sessions.begin() as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT model,document_hash,document FROM catalog.product_search WHERE entity_id=:id"
                        ),
                        {"id": entity_id},
                    )
                )
                .mappings()
                .one()
            )
            assert row["model"] == VERSION and row["document_hash"] == fingerprint(
                row["document"]
            )
    finally:
        if entity_id:
            async with sessions.begin() as session:
                await session.execute(
                    text("DELETE FROM scraping.entity WHERE id=:id"), {"id": entity_id}
                )
        await engine.dispose()
