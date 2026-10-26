from datetime import date, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth.router import current_user
from panoptes_backend.catalog.router import session_dependency
from panoptes_backend.main import create_app
from panoptes_backend.management import price_analytics
from panoptes_backend.management.router import price_filters


def test_inclusive_period_and_brasilia_boundary():
    filters = price_filters(date(2026, 10, 1), date(2026, 10, 6), site=None)
    assert filters["start_at"].isoformat() == "2026-10-01T00:00:00-03:00"
    assert filters["end_at"].isoformat() == "2026-10-07T00:00:00-03:00"


@pytest.mark.parametrize("days", [-1, 366])
def test_invalid_period_is_rejected(days):
    start = date(2026, 1, 1)
    with pytest.raises(HTTPException) as error:
        price_filters(start, start + timedelta(days=days), site=None)
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "path",
    ["/analytics/prices/dashboard", "/analytics/prices/products", "/analytics/detail"],
)
async def test_price_analytics_requires_authentication(path):
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        assert (await client.get(path)).status_code == 401


async def test_all_filters_reach_dashboard_and_detail(monkeypatch):
    term_id, product_id = uuid4(), uuid4()
    dashboard = AsyncMock(return_value={"totals": {"products": 2}})
    detail = AsyncMock(
        return_value={"items": [], "total": 26, "limit": 25, "offset": 25}
    )
    monkeypatch.setattr(price_analytics, "dashboard", dashboard)
    monkeypatch.setattr(price_analytics, "detail", detail)
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"name": "test"}
    marker = object()

    async def session():
        yield marker

    app.dependency_overrides[session_dependency] = session
    params = {
        "start": "2026-10-01",
        "end": "2026-10-06",
        "term_id": str(term_id),
        "product_id": str(product_id),
        "site": "amazon_br",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.get("/analytics/prices/dashboard", params=params)
        ).status_code == 200
        response = await client.get(
            "/analytics/detail", params={**params, "offset": 25}
        )
        assert response.status_code == 200 and response.json()["total"] == 26
        for invalid in (
            {"product_id": "bad"},
            {"start": "2026-10-07", "end": "2026-10-06"},
            {"limit": 101},
            {"offset": -1},
        ):
            assert (
                await client.get("/analytics/detail", params=invalid)
            ).status_code == 422
    filters = dashboard.await_args.args[1]
    assert filters["term_id"] == term_id and filters["product_id"] == product_id
    assert filters["site"] == "amazon_br"
    detail.assert_awaited_once_with(marker, filters, 25, 25)


async def test_canonical_filter_intersects_search_without_pagination(monkeypatch):
    from types import SimpleNamespace

    from panoptes_backend.catalog import products_repository
    from panoptes_backend.management.router import resolve_price_search

    canonical_id, included, other = uuid4(), uuid4(), uuid4()
    ids = AsyncMock(return_value=[included])
    monkeypatch.setattr(products_repository, "canonical_entity_ids", ids)
    search = AsyncMock(return_value=[{"public_id": included}, {"public_id": other}])
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(product_search=SimpleNamespace(search=search))
        )
    )
    filters = {
        "canonical_product_id": canonical_id,
        "q": "Kindle",
        "term_id": None,
        "site": None,
        "product_ids": None,
    }
    await resolve_price_search(request, None, filters)
    assert filters["product_ids"] == [included]
    ids.assert_awaited_once_with(None, canonical_id)
    search.assert_awaited_once_with(None, "Kindle", None, None, limit=None)


@pytest.mark.parametrize("count", [0, 125])
async def test_product_search_filters_dashboard_and_detail_without_result_limit(
    monkeypatch, count
):
    matches = [{"public_id": uuid4()} for _ in range(count)]
    service = AsyncMock()
    service.search.return_value = matches
    dashboard = AsyncMock(return_value={"totals": {"products": count}})
    detail = AsyncMock(return_value={"items": [], "total": count})
    monkeypatch.setattr(price_analytics, "dashboard", dashboard)
    monkeypatch.setattr(price_analytics, "detail", detail)
    app = create_app()
    app.state.product_search = service
    app.dependency_overrides[current_user] = lambda: {"name": "test"}
    marker = object()

    async def session():
        yield marker

    app.dependency_overrides[session_dependency] = session
    term_id = uuid4()
    params = {"q": "  refrigerador  ", "term_id": str(term_id), "site": "amazon_br"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for path in ("/analytics/prices/dashboard", "/analytics/detail"):
            assert (await client.get(path, params=params)).status_code == 200
        assert (
            await client.get("/analytics/prices/dashboard", params={"q": "x" * 301})
        ).status_code == 422
    assert service.search.await_count == 2
    service.search.assert_awaited_with(
        marker, "refrigerador", term_id, "amazon_br", limit=None
    )
    for handler in (dashboard, detail):
        filters = handler.await_args.args[1]
        assert filters["product_ids"] == [row["public_id"] for row in matches]
        assert filters["q"] == "refrigerador"


async def test_product_details_requests_latest_capture_before_pagination(monkeypatch):
    detail = AsyncMock(return_value={"items": [], "total": 0, "limit": 25, "offset": 0})
    monkeypatch.setattr(price_analytics, "detail", detail)
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"name": "test"}
    marker = object()

    async def session():
        yield marker

    app.dependency_overrides[session_dependency] = session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/analytics/detail", params={"latest": "true"})
        assert response.status_code == 200
        assert response.json()["total"] == 0
    assert detail.await_args.args[0] is marker
    assert detail.await_args.kwargs == {"latest": True}


@pytest.mark.parametrize("latest", [False, True])
async def test_detail_uses_same_selection_for_count_and_page(latest):
    from unittest.mock import MagicMock

    count = MagicMock()
    count.scalar_one.return_value = 2
    rows = MagicMock()
    rows.mappings.return_value.all.return_value = [
        {"seller": "Loja A"},
        {"seller": "Loja B"},
    ]
    session = AsyncMock()
    session.execute.side_effect = [count, rows]
    result = await price_analytics.detail(session, {}, 25, 0, latest=latest)
    assert result["total"] == 2
    assert len(result["items"]) == 2
    count_sql, items_sql = [
        str(call.args[0]) for call in session.execute.await_args_list
    ]
    for sql in (count_sql, items_sql):
        assert ("capture_rank=1" in sql) is latest
        if latest:
            assert (
                "PARTITION BY product_id ORDER BY captured_at DESC,capture_id DESC"
                in sql
            )
    if latest:
        assert items_sql.index("capture_rank=1") < items_sql.index(
            "LIMIT :limit OFFSET :offset"
        )
