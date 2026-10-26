from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth.router import current_user
from panoptes_backend.catalog import repository
from panoptes_backend.catalog.router import session_dependency
from panoptes_backend.main import create_app
from panoptes_contracts.sources import SOURCES


async def test_create_term_and_trigger_discovery_with_public_identifiers(monkeypatch):
    public_id, request_id = uuid4(), uuid4()
    criteria = {
        "title": "Database Internals",
        "authors": ["Alex Petrov"],
        "isbn": [],
        "excluded_title_terms": [
            "summary",
            "workbook",
            "study guide",
            "resumo",
            "analysis",
            "review",
        ],
    }
    row = {
        "id": 42,
        "public_id": public_id,
        "site": "amazon_br",
        "term": "Database Internals",
        "criteria": criteria,
        "max_pages_qt": 1,
        "refresh_interval_seconds": 86400,
    }
    monkeypatch.setattr(repository, "insert_term", AsyncMock(return_value=row))
    monkeypatch.setattr(repository, "find_term", AsyncMock(return_value=row))
    monkeypatch.setattr(
        repository,
        "enqueue",
        AsyncMock(return_value={"public_id": request_id, "status": "pending"}),
    )
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"name": "admin"}

    async def session():
        yield object()

    app.dependency_overrides[session_dependency] = session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/search-terms",
            json={
                "term": "Database Internals",
                "criteria": {"title": "Database Internals", "authors": ["Alex Petrov"]},
            },
        )
        assert response.status_code == 201
        assert response.json()["public_id"] == str(public_id)
        assert "id" not in response.json()
        response = await client.post(f"/search-terms/{public_id}/discover")
        assert response.status_code == 202
        assert response.json()["public_id"] == str(request_id)
        assert (
            repository.enqueue.await_args.args[-1]
            == response.headers["X-Correlation-ID"]
        )


async def test_unknown_term_returns_domain_error(monkeypatch):
    monkeypatch.setattr(repository, "find_term", AsyncMock(return_value=None))
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"name": "admin"}

    async def session():
        yield object()

    app.dependency_overrides[session_dependency] = session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/search-terms/{uuid4()}/discover")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "sites,expected",
    [
        ("all", list(SOURCES)),
        (["mercado_livre_br"], ["mercado_livre_br"]),
    ],
)
async def test_source_selection_clones_same_criteria_and_shares_correlation(
    monkeypatch, sites, expected
):
    from panoptes_contracts.discovery import ProductMatchCriteria

    original_id, ml_id = uuid4(), uuid4()
    original = {
        "id": 1,
        "public_id": original_id,
        "site": "amazon_br",
        "term": "CTO livro",
        "criteria": ProductMatchCriteria(title="CTO").model_dump(mode="json"),
        "max_pages_qt": 5,
        "max_candidates_qt": 200,
        "refresh_interval_seconds": 86400,
    }
    ml = {**original, "id": 2, "public_id": ml_id, "site": "mercado_livre_br"}
    rows = {original_id: original, ml_id: ml}
    inserted = []

    async def insert(_, value, normalized):
        inserted.append(value)
        assert normalized == "cto livro"
        if value.site == "amazon_br":
            return original
        if value.site == "mercado_livre_br":
            return ml
        row = {
            **original,
            "id": len(rows) + 1,
            "public_id": uuid4(),
            "site": value.site,
        }
        rows[row["public_id"]] = row
        return row

    monkeypatch.setattr(
        repository, "find_term", AsyncMock(side_effect=lambda _, key: rows.get(key))
    )
    monkeypatch.setattr(repository, "insert_term", AsyncMock(side_effect=insert))
    monkeypatch.setattr(
        repository,
        "enqueue",
        AsyncMock(
            side_effect=lambda *args: {"public_id": uuid4(), "status": "pending"}
        ),
    )
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"name": "admin"}

    async def session():
        yield object()

    app.dependency_overrides[session_dependency] = session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/search-terms/{original_id}/discover-sources", json={"sites": sites}
        )
        assert response.status_code == 202
        assert [r["site"] for r in response.json()["requests"]] == expected
        assert all(
            value.criteria.title == "CTO"
            and value.max_pages == 5
            and value.max_candidates == 200
            for value in inserted
        )
        assert all(
            call.args[-1] == response.headers["X-Correlation-ID"]
            for call in repository.enqueue.await_args_list
        )
        sources = await client.get("/sources")
        assert [s["id"] for s in sources.json()] == list(SOURCES)
        for invalid in ([], ["unknown"], ["amazon_br", "amazon_br"]):
            response = await client.post(
                f"/search-terms/{original_id}/discover-sources", json={"sites": invalid}
            )
            assert response.status_code == 422
