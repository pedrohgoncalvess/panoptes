from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth.router import current_user
from panoptes_backend.catalog import repository, services
from panoptes_backend.catalog.models import SearchTermsCreate
from panoptes_backend.catalog.router import session_dependency
from panoptes_backend.catalog.search import ProductQuery, search_products
from panoptes_backend.main import create_app
from pydantic import ValidationError


def app_with_session():
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"name": "test"}
    marker = object()

    async def session():
        yield marker

    app.dependency_overrides[session_dependency] = session
    app.state.product_search = AsyncMock()
    return app, marker


async def test_batch_and_term_routes(monkeypatch):
    app, marker = app_with_session()
    result = {"terms": [], "requests": []}
    create = AsyncMock(return_value=result)
    monkeypatch.setattr(services, "create_terms", create)
    terms = AsyncMock(return_value=[])
    monkeypatch.setattr(repository, "list_terms", terms)
    pid = uuid4()
    monkeypatch.setattr(
        repository,
        "find_term",
        AsyncMock(
            return_value={"id": 42, "public_id": pid, "term": "GPU", "criteria": {}}
        ),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/search-terms/batch",
            json={
                "term": "GPU",
                "description": "Excluir acessórios",
                "sites": ["kabum_br", "pichau_br"],
                "discover": True,
            },
        )
        assert response.status_code == 201
        value = create.await_args.args[1]
        assert value.criteria.description == "Excluir acessórios"
        assert value.sites == ("kabum_br", "pichau_br")
        assert create.await_args.args[2] == response.headers["X-Correlation-ID"]
        response = await client.get(
            "/search-terms?q=GPU&site=kabum_br&limit=10&offset=20"
        )
        assert response.status_code == 200
        terms.assert_awaited_once_with(marker, 10, 20, q="GPU", site="kabum_br")
        response = await client.get(f"/search-terms/{pid}")
        assert response.status_code == 200 and "id" not in response.json()
        for body in (
            {"term": "GPU", "sites": []},
            {"term": "GPU", "sites": ["kabum_br", "kabum_br"]},
            {"term": "GPU", "sites": ["bad"]},
            {"term": "GPU", "site": "amazon_br", "sites": ["kabum_br"]},
        ):
            assert (
                await client.post("/search-terms/batch", json=body)
            ).status_code == 422


async def test_batch_preserves_configuration_and_correlation(monkeypatch):
    calls = []
    ids = [uuid4(), uuid4()]

    async def insert(session, value):
        calls.append(value)
        return {"public_id": ids[len(calls) - 1], "site": value.site}

    create = AsyncMock(side_effect=insert)
    discover = AsyncMock(return_value={"public_id": uuid4(), "status": "pending"})
    monkeypatch.setattr(services, "create_term", create)
    monkeypatch.setattr(services, "discover", discover)
    value = SearchTermsCreate(
        term="GPU",
        description="Excluir PCs",
        reference_price=100,
        sites=["kabum_br", "pichau_br"],
        discover=True,
    )
    marker, correlation = object(), str(uuid4())
    result = await services.create_terms(marker, value, correlation)
    assert len(result["terms"]) == len(result["requests"]) == 2
    assert [v.site for v in calls] == ["kabum_br", "pichau_br"]
    assert all(v.criteria == value.criteria for v in calls)
    assert [c.args for c in discover.await_args_list] == [
        (marker, ids[0], correlation),
        (marker, ids[1], correlation),
    ]
    discover.reset_mock()
    create.reset_mock()
    calls.clear()
    await services.create_terms(
        marker, value.model_copy(update={"discover": False}), correlation
    )
    discover.assert_not_awaited()


async def test_search_api_validation_scope_and_auth(monkeypatch):
    from panoptes_backend.catalog import search

    app, marker = app_with_session()
    query = AsyncMock(return_value={"items": [], "total": 0})
    monkeypatch.setattr(search, "search_products", query)
    monkeypatch.setattr(repository, "find_term", AsyncMock(return_value={"id": 1}))
    term = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/products/search",
            params={
                "q": "placa de vídeo",
                "term_id": str(term),
                "site": "kabum_br",
                "start_at": "2026-10-01T00:00:00-03:00",
                "offset": 50,
            },
        )
        assert response.status_code == 200
        assert query.await_args.args[0] is marker
        filters = query.await_args.args[2]
        assert filters.term_id == term and filters.offset == 50
        for params in (
            {},
            {"q": "  "},
            {"mode": "recent", "q": "GPU"},
            {"q": "gpu", "limit": 101},
            {"q": "gpu", "site": "bad"},
            {"mode": "recent", "start_at": "2026-10-01T00:00:00"},
            {
                "mode": "recent",
                "start_at": "2026-10-02T00:00:00Z",
                "end_at": "2026-10-01T00:00:00Z",
            },
        ):
            assert (
                await client.get("/products/search", params=params)
            ).status_code == 422
        repository.find_term.return_value = None
        assert (
            await client.get(
                "/products/search", params={"q": "gpu", "term_id": str(term)}
            )
        ).status_code == 404
        app.dependency_overrides.pop(current_user)
        assert (await client.get("/products/search?q=gpu")).status_code == 401
        assert (
            await client.post(
                "/search-terms/batch", json={"term": "gpu", "sites": ["kabum_br"]}
            )
        ).status_code == 401


@pytest.mark.parametrize("mode", ["semantic", "text", "recent"])
async def test_search_embedding_is_only_generated_for_semantic(mode):
    service = MagicMock(agent={"model": "test"}, version="test-v1")
    service.configure = AsyncMock()
    service.encode = AsyncMock(return_value=[[1.0, 0.0]])
    count = MagicMock()
    count.scalar_one.return_value = 7
    rows = MagicMock()
    rows.mappings.return_value.all.return_value = []
    session = MagicMock(execute=AsyncMock(side_effect=[count, rows]))
    filters = ProductQuery(mode=mode, q=None if mode == "recent" else "gpu", offset=100)
    result = await search_products(session, service, filters)
    assert result["total"] == 7 and result["offset"] == 100
    if mode == "semantic":
        service.encode.assert_awaited_once_with(
            ["gpu"], agent=service.agent, version="test-v1"
        )
    else:
        service.encode.assert_not_awaited()


def test_term_and_search_schema_reject_bad_limits():
    with pytest.raises(ValidationError):
        SearchTermsCreate(term="gpu", sites=["kabum_br"], max_pages=21)
    with pytest.raises(ValidationError):
        ProductQuery(q="gpu", min_similarity=1.1)


async def test_history_period_is_forwarded_and_validated(monkeypatch):
    app, marker = app_with_session()
    history = AsyncMock(return_value=[])
    monkeypatch.setattr(repository, "read_history", history)
    entity = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/products/{entity}/observations",
            params={
                "start_at": "2026-10-01T00:00:00-03:00",
                "end_at": "2026-10-02T00:00:00-03:00",
            },
        )
        assert response.status_code == 200
        assert history.await_args.args == (marker, entity, 50, 0)
        assert history.await_args.kwargs["end_at"].day == 2
        for params in (
            {"start_at": "2026-10-01T00:00:00"},
            {"start_at": "2026-10-03T00:00:00Z", "end_at": "2026-10-02T00:00:00Z"},
        ):
            assert (
                await client.get(f"/products/{entity}/observations", params=params)
            ).status_code == 422


async def test_mcp_to_asgi_api_search_and_batch(monkeypatch):
    from mcp.shared.memory import create_connected_server_and_client_session
    from panoptes_backend.catalog import search
    from panoptes_mcp.client import PanoptesClient
    from panoptes_mcp.server import create_server

    app, marker = app_with_session()
    monkeypatch.setenv("PANOPTES_MCP_KEY", "pmcp_test-token")
    monkeypatch.setenv("PANOPTES_API_URL", "http://localhost")
    product = uuid4()
    query = AsyncMock(
        return_value={
            "items": [
                {
                    "public_id": str(product),
                    "similarity": 0.8,
                    "site": "kabum_br",
                    "source_key": "123456",
                    "title": "GPU",
                    "url": None,
                    "observation_id": str(uuid4()),
                    "observed_at": "2026-10-24T12:00:00-03:00",
                    "data": {},
                }
            ],
            "total": 1,
            "limit": 25,
            "offset": 0,
            "mode": "semantic",
        }
    )
    monkeypatch.setattr(search, "search_products", query)
    created = AsyncMock(return_value={"terms": [], "requests": []})
    monkeypatch.setattr(services, "create_terms", created)
    api = PanoptesClient(transport=ASGITransport(app=app))
    async with create_connected_server_and_client_session(
        create_server(lambda: api)
    ) as session:
        response = await session.call_tool("search_products", {"q": "placa de vídeo"})
        assert not response.isError
        assert str(product) in response.content[0].text
        assert query.await_args.args[0] is marker
        assert query.await_args.args[2].q == "placa de vídeo"
        response = await session.call_tool(
            "create_search_terms",
            {"value": {"term": "RTX 5070", "sites": ["kabum_br"], "discover": True}},
        )
        assert not response.isError
        assert created.await_args.args[1].discover
