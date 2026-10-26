from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth import repository as auth_repository
from panoptes_backend.auth import router as auth_router
from panoptes_backend.auth.security import encode_token
from panoptes_backend.catalog.router import session_dependency
from panoptes_backend.main import create_app
from panoptes_backend.management import repository

SECRET = "management-test-secret-at-least-32-bytes"
PID = "00000000-0000-4000-8000-000000000001"
EMPTY_ANALYTICS = {
    "period_days": 7,
    "totals": {
        "products": 0,
        "active_routines": 0,
        "requests": 0,
        "completed": 0,
        "failed": 0,
        "in_progress": 0,
    },
    "daily": [],
}
PROTECTED = [
    ("GET", "/data"),
    ("POST", "/data/bulk"),
    ("DELETE", f"/data/{PID}"),
    ("GET", f"/assets/{PID}/url"),
    ("GET", "/extraction-logs"),
    ("GET", "/extraction-logs/stream"),
    ("GET", "/analytics"),
    ("GET", f"/analytics/prices?term_id={PID}"),
    ("GET", "/scrape-requests"),
    ("GET", "/extraction-groups"),
    ("GET", f"/scrape-requests/{PID}"),
    ("GET", "/routines"),
    ("POST", "/routines"),
    ("POST", f"/routines/{PID}/advance"),
    ("GET", f"/routines/{PID}"),
    ("PUT", f"/routines/{PID}"),
    ("DELETE", f"/routines/{PID}"),
    ("GET", "/search-terms"),
    ("POST", "/search-terms"),
    ("POST", f"/search-terms/{PID}/discover"),
    ("GET", f"/search-terms/{PID}/products"),
    ("POST", f"/products/{PID}/refresh"),
    ("PATCH", f"/products/{PID}/tracking"),
    ("GET", f"/products/{PID}/observations"),
    ("GET", "/auth/me"),
    ("POST", "/auth/logout"),
    ("GET", "/openapi.json"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
@pytest.mark.parametrize(
    "credential", ["missing", "malformed", "expired", "refresh", "wrong_signature"]
)
async def test_protected_http_endpoints_reject_unauthenticated(
    monkeypatch, method, path, credential
):
    app = create_app()
    app.state.jwt_secret = SECRET
    session = AsyncMock()

    async def forbidden_session():
        await session()
        yield object()

    app.dependency_overrides[session_dependency] = forbidden_session
    auth_read = AsyncMock()
    monkeypatch.setattr(auth_repository, "find_session", auth_read)
    headers = {}
    if credential != "missing":
        kind = "refresh" if credential == "refresh" else "access"
        expires = datetime.now(UTC) + timedelta(minutes=5)
        if credential == "expired":
            expires = datetime.now(UTC) - timedelta(minutes=1)
        secret = (
            "wrong-signature-secret-at-least-32-bytes"
            if credential == "wrong_signature"
            else SECRET
        )
        token = (
            "not-a-jwt"
            if credential == "malformed"
            else encode_token(secret, uuid4(), uuid4(), kind, expires)
        )
        headers["Authorization"] = f"Bearer {token}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["correlation_id"] == response.headers["X-Correlation-ID"]
    session.assert_not_awaited()
    auth_read.assert_not_awaited()


@pytest.mark.parametrize(
    "state", ["missing", "revoked", "expired", "inactive", "different_user"]
)
@pytest.mark.parametrize(
    "path",
    [
        "/analytics",
        f"/analytics/prices?term_id={PID}",
        "/scrape-requests",
        "/routines",
        "/auth/me",
    ],
)
async def test_valid_jwt_with_invalid_session_is_denied(monkeypatch, state, path):
    uid, sid = uuid4(), uuid4()
    row = {
        "active": state != "inactive",
        "revoked_at": datetime.now(UTC) if state == "revoked" else None,
        "expires_at": datetime.now(UTC)
        + timedelta(days=-1 if state == "expired" else 1),
        "user_public_id": uuid4() if state == "different_user" else uid,
    }

    @asynccontextmanager
    async def transaction(factory):
        yield object()

    monkeypatch.setattr(auth_router, "unit_of_work", transaction)
    monkeypatch.setattr(
        auth_repository,
        "find_session",
        AsyncMock(return_value=None if state == "missing" else row),
    )
    app = create_app()
    app.state.jwt_secret, app.state.sessions = SECRET, object()
    token = encode_token(
        SECRET, uid, sid, "access", datetime.now(UTC) + timedelta(minutes=5)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.parametrize("kind,expired", [("refresh", True), ("access", False)])
async def test_refresh_rejects_expiration_and_access_token(monkeypatch, kind, expired):
    read = AsyncMock()
    monkeypatch.setattr(auth_repository, "find_session", read)
    app = create_app()
    app.state.jwt_secret = SECRET
    token = encode_token(
        SECRET,
        uuid4(),
        uuid4(),
        kind,
        datetime.now(UTC) + timedelta(minutes=-1 if expired else 5),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/auth/refresh", json={"refresh_token": token})
    assert response.status_code == 401
    read.assert_not_awaited()


async def test_authenticated_management_filters_and_validation(monkeypatch):
    summary = EMPTY_ANALYTICS
    analytics = AsyncMock(return_value=summary)
    extractions = AsyncMock(
        return_value={"items": [], "total": 0, "limit": 10, "offset": 20}
    )
    monkeypatch.setattr(repository, "analytics", analytics)
    monkeypatch.setattr(repository, "extractions", extractions)
    app = create_app()
    app.dependency_overrides[auth_router.current_user] = lambda: {"name": "admin"}
    marker = object()

    async def session():
        yield marker

    app.dependency_overrides[session_dependency] = session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/analytics")
        assert response.status_code == 200 and response.json() == summary
        analytics.assert_awaited_once_with(marker, 7)
        response = await client.get("/scrape-requests?status=failed&limit=10&offset=20")
        assert response.status_code == 200 and response.json()["total"] == 0
        extractions.assert_awaited_once_with(marker, "failed", 10, 20, None)
        for path in [
            "/analytics?days=0",
            "/analytics?days=91",
            "/scrape-requests?status=unknown",
            "/scrape-requests?limit=101",
            "/scrape-requests?offset=-1",
        ]:
            assert (await client.get(path)).status_code == 422


async def test_valid_access_token_reaches_management_endpoint(monkeypatch):
    uid, sid = uuid4(), uuid4()

    @asynccontextmanager
    async def transaction(factory):
        yield object()

    row = {
        "public_id": sid,
        "user_public_id": uid,
        "name": "admin",
        "email": "admin@panoptes.com",
        "active": True,
        "revoked_at": None,
        "expires_at": datetime.now(UTC) + timedelta(days=1),
    }
    monkeypatch.setattr(auth_router, "unit_of_work", transaction)
    monkeypatch.setattr(auth_repository, "find_session", AsyncMock(return_value=row))
    monkeypatch.setattr(
        repository, "analytics", AsyncMock(return_value=EMPTY_ANALYTICS)
    )
    app = create_app()
    app.state.jwt_secret, app.state.sessions = SECRET, object()

    async def session():
        yield object()

    app.dependency_overrides[session_dependency] = session
    token = encode_token(
        SECRET, uid, sid, "access", datetime.now(UTC) + timedelta(minutes=5)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/analytics", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200


@pytest.mark.parametrize("site", ["amazon_br", "mercado_livre_br", None])
async def test_management_serializes_dates_and_only_public_identifiers(
    monkeypatch, site
):
    from datetime import date

    pid, term = uuid4(), uuid4()
    summary = {
        **EMPTY_ANALYTICS,
        "daily": [{"date": date(2026, 10, 4), "total": 0, "completed": 0, "failed": 0}],
    }
    row = {
        "public_id": pid,
        "site": site,
        "mode": "discover",
        "status": "pending",
        "summary": {},
        "created_at": datetime(2026, 10, 4, 12, tzinfo=UTC),
        "completed_at": None,
        "search_term_id": term,
        "term": "Book",
        "entity_id": None,
        "source_key": None,
    }
    monkeypatch.setattr(repository, "analytics", AsyncMock(return_value=summary))
    monkeypatch.setattr(
        repository,
        "extractions",
        AsyncMock(return_value={"items": [row], "total": 1, "limit": 25, "offset": 0}),
    )
    app = create_app()
    app.dependency_overrides[auth_router.current_user] = lambda: {"name": "admin"}

    async def session():
        yield object()

    app.dependency_overrides[session_dependency] = session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/analytics")
        assert response.status_code == 200
        assert response.json()["daily"][0]["date"] == "2026-10-04"
        response = await client.get("/scrape-requests")
        assert response.status_code == 200
        result = response.json()["items"][0]
        assert result["public_id"] == str(pid)
        assert result["site"] == site
        assert result["search_term_id"] == str(term)
        assert result["entity_id"] is None
        assert "id" not in result


async def test_prices_http_pagination_validation_and_unknown_term(monkeypatch):
    from panoptes_backend.catalog import repository as catalog

    app = create_app()
    app.dependency_overrides[auth_router.current_user] = lambda: {"name": "admin"}
    marker = object()

    async def session():
        yield marker

    app.dependency_overrides[session_dependency] = session
    term = AsyncMock(return_value={"id": 42})
    prices = AsyncMock(
        return_value={"items": [], "total": 0, "limit": 24, "offset": 24}
    )
    monkeypatch.setattr(catalog, "find_term", term)
    monkeypatch.setattr(repository, "prices", prices)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/analytics/prices?term_id={PID}&limit=24&offset=24"
        )
        assert response.status_code == 200
        assert response.json() == prices.return_value
        prices.assert_awaited_once_with(marker, 42, 24, 24)
        for query in [
            "",
            "?term_id=invalid",
            f"?term_id={PID}&limit=101",
            f"?term_id={PID}&offset=-1",
        ]:
            assert (await client.get("/analytics/prices" + query)).status_code == 422
        term.return_value = None
        assert (await client.get(f"/analytics/prices?term_id={PID}")).status_code == 404
    assert prices.await_count == 1


async def test_grouped_extractions_and_history_filter(monkeypatch):
    app = create_app()
    app.dependency_overrides[auth_router.current_user] = lambda: {"name": "admin"}
    marker = object()

    async def session():
        yield marker

    app.dependency_overrides[session_dependency] = session
    groups = AsyncMock(
        return_value={"items": [], "total": 0, "limit": 10, "offset": 20}
    )
    histories = AsyncMock(
        return_value={"items": [], "total": 0, "limit": 10, "offset": 0}
    )
    monkeypatch.setattr(repository, "extraction_groups", groups)
    monkeypatch.setattr(repository, "extractions", histories)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/extraction-groups?status=failed&limit=10&offset=20"
        )
        assert response.status_code == 200
        groups.assert_awaited_once_with(marker, "failed", 10, 20)
        response = await client.get(
            "/scrape-requests", params={"group_key": "term:Book", "limit": 10}
        )
        assert response.status_code == 200
        histories.assert_awaited_once_with(marker, None, 10, 0, "term:Book")
        assert (await client.get("/extraction-groups?limit=101")).status_code == 422
