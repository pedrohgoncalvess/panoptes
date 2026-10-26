from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth import mcp_keys, mcp_policy
from panoptes_backend.auth.mcp_models import MCPKeyCreate, MCPPermissions
from panoptes_backend.auth.router import current_user
from panoptes_backend.auth.security import decode_token, token_hash, token_pair
from panoptes_backend.main import create_app
from pydantic import ValidationError
from starlette.requests import Request

SECRET = "test-secret-at-least-32-bytes-long-value"


def result(row=None, scalar=None, found=True):
    value = MagicMock()
    value.mappings.return_value.one_or_none.return_value = row
    value.mappings.return_value.one.return_value = row
    value.scalars.return_value.all.return_value = []
    value.scalar_one.return_value = scalar
    value.first.return_value = (1,) if found else None
    return value


def key(**permissions):
    return {
        "id": 5,
        "admin": False,
        "permissions": MCPPermissions(**permissions).model_dump(),
    }


def req(path, method="GET", body=b"", query=b""):
    async def receive():
        return {"type": "http.request", "body": body}

    return Request(
        {
            "type": "http",
            "path": path,
            "method": method,
            "headers": [],
            "query_string": query,
        },
        receive,
    )


def test_session_lifetimes_and_absolute_refresh_deadline():
    now = datetime.now(UTC)
    expires = now + timedelta(hours=10)
    pair = token_pair(SECRET, uuid4(), uuid4(), expires)
    access = decode_token(SECRET, pair["access_token"], "access")
    refresh = decode_token(SECRET, pair["refresh_token"], "refresh")
    assert access["exp"] - access["iat"] == 7200
    assert refresh["exp"] - refresh["iat"] == 36000
    assert 35999 <= pair["refresh_expires_in"] <= 36000
    near_end = token_pair(SECRET, uuid4(), uuid4(), now + timedelta(minutes=1))
    assert (
        decode_token(SECRET, near_end["access_token"], "access")["exp"]
        <= now.timestamp() + 60
    )


@pytest.mark.parametrize(
    "preset,expected",
    [
        ("1w", (2026, 2, 7)),
        ("2w", (2026, 2, 14)),
        ("1m", (2026, 2, 28)),
        ("6m", (2026, 7, 31)),
        ("1y", (2027, 1, 31)),
    ],
)
def test_calendar_expiration_presets(preset, expected):
    now = datetime(2026, 1, 31, 12, tzinfo=UTC)
    expires = mcp_keys.expiration(MCPKeyCreate(name=" key ", expiration=preset), now)
    assert (expires.year, expires.month, expires.day) == expected
    assert expires.hour == 12


def test_expiration_and_permission_validation():
    assert mcp_keys.expiration(MCPKeyCreate(name="key", expiration="never")) is None
    future = datetime.now(UTC) + timedelta(days=3)
    value = MCPKeyCreate(name=" key ", expiration="custom", expires_at=future)
    assert mcp_keys.expiration(value) == future and value.name == "key"
    for fields in (
        {"expiration": "custom"},
        {"expiration": "custom", "expires_at": "2000-01-01T00:00:00Z"},
        {"expires_at": future},
        {"name": " "},
        {"permissions": {"sites": ["unknown"]}},
        {"permissions": {"max_routines": -1}},
    ):
        with pytest.raises(ValidationError):
            MCPKeyCreate.model_validate({"name": "key", **fields})


@pytest.mark.parametrize(
    "path,method,permissions,body",
    [
        ("/routines", "POST", {}, b"{}"),
        ("/search-terms/batch", "POST", {}, b'{"sites":["amazon_br"]}'),
        (
            "/search-terms/batch",
            "POST",
            {"create_extractions": True, "sites": ["amazon_br"]},
            b'{"sites":["mercado_livre_br"]}',
        ),
        ("/search-terms", "GET", {}, b""),
        ("/scrape-requests", "GET", {}, b""),
        ("/products/search", "GET", {"view_extractions": True}, b""),
        ("/alerts/webhooks", "POST", {}, b'{"rules":[]}'),
        (
            "/alerts/webhooks",
            "POST",
            {"create_alerts": True},
            b'{"rules":[{"routine_ids":[]}]}',
        ),
        ("/data", "GET", {"view_extractions": True}, b""),
        ("/admin/categories/test", "PUT", {}, b"{}"),
        ("/auth/mcp-keys", "POST", {}, b"{}"),
        ("/openapi.json", "GET", {}, b""),
        ("/analytics/prices/dashboard", "GET", {"view_extractions": True}, b""),
    ],
)
async def test_restricted_keys_fail_closed(path, method, permissions, body):
    session = SimpleNamespace(execute=AsyncMock(return_value=result(found=False)))
    with pytest.raises(HTTPException) as exc:
        await mcp_policy.authorize(
            req(path, method, body), session, {"mcp_key": key(**permissions)}
        )
    assert exc.value.status_code == 403


async def test_authorized_and_foreign_resource_checks():
    pid = uuid4()
    session = SimpleNamespace(execute=AsyncMock(return_value=result()))
    credential = key(view_extractions=True, sites=["amazon_br"])
    await mcp_policy.authorize(
        req(f"/products/{pid}/observations"), session, {"mcp_key": credential}
    )
    sql, params = session.execute.await_args.args
    assert "mcp_key_routine" in str(sql) and "mcp_key_term" in str(sql)
    assert params["mcp_key"] == 5 and params["mcp_sites"] == ["amazon_br"]
    session.execute.return_value = result(found=False)
    with pytest.raises(HTTPException) as exc:
        await mcp_policy.authorize(
            req(f"/products/{uuid4()}/observations"), session, {"mcp_key": credential}
        )
    assert exc.value.status_code == 403


async def test_mcp_admin_bypasses_grants_but_cannot_issue_keys():
    session = SimpleNamespace(execute=AsyncMock())
    user = {"mcp_key": {"admin": True}}
    await mcp_policy.authorize(req("/data/bulk", "POST", b"{}"), session, user)
    session.execute.assert_not_awaited()
    with pytest.raises(HTTPException):
        await mcp_policy.authorize(req("/auth/mcp-keys", "POST", b"{}"), session, user)


async def test_quota_lock_and_limit():
    credential = key(create_routines=True, max_routines=2)
    session = SimpleNamespace(
        info={"mcp_key": credential}, execute=AsyncMock(return_value=result(scalar=2))
    )
    with pytest.raises(HTTPException, match="Limite"):
        await mcp_policy.reserve_routine(session)
    assert "FOR UPDATE" in str(session.execute.await_args_list[0].args[0])
    credential["permissions"]["max_routines"] = None
    await mcp_policy.reserve_routine(session)


async def test_issuance_is_browser_only_and_returns_secret_once(monkeypatch):
    uid, kid = uuid4(), uuid4()
    browser = {
        "public_id": uid,
        "name": "admin",
        "email": "admin@panoptes.com",
        "role": "admin",
    }
    row = {
        "id": 5,
        "public_id": kid,
        "name": "key",
        "admin": False,
        "permissions": {},
        "expires_at": None,
        "revoked_at": None,
        "created_at": datetime.now(UTC),
    }
    session = SimpleNamespace(execute=AsyncMock(side_effect=[result(), result(row)]))

    @asynccontextmanager
    async def transaction(factory):
        yield session

    monkeypatch.setattr(mcp_keys, "unit_of_work", transaction)
    app = create_app()
    app.state.sessions = object()
    app.state.jwt_secret = SECRET
    app.dependency_overrides[current_user] = lambda: browser
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/auth/mcp-keys", json={"name": "key", "expiration": "never"}
        )
        assert response.status_code == 201, response.text
        token = response.json()["key"]
        claims = jwt.decode(
            token[5:],
            SECRET,
            algorithms=["HS256"],
            audience="panoptes-mcp",
            issuer="panoptes",
        )
        assert (
            claims["sub"] == str(uid)
            and claims["type"] == "mcp"
            and "exp" not in claims
        )
        params = session.execute.await_args.args[1]
        assert params["hash"] == token_hash(token) and token not in str(params)
        browser["role"] = "user"
        assert (
            await client.post("/auth/mcp-keys", json={"name": "key", "admin": True})
        ).status_code == 403
        browser["mcp_key"] = {"admin": True}
        assert (
            await client.post("/auth/mcp-keys", json={"name": "key"})
        ).status_code == 403


@pytest.mark.parametrize(
    "invalid", ["revoked", "expired", "inactive", "wrong_hash", "signature", "demoted"]
)
async def test_api_rejects_invalid_mcp_credentials(monkeypatch, invalid):
    now, uid, kid = datetime.now(UTC), uuid4(), uuid4()
    claims = {
        "sub": str(uid),
        "kid": str(kid),
        "jti": str(uuid4()),
        "iat": now,
        "nbf": now,
        "type": "mcp",
        "iss": "panoptes",
        "aud": "panoptes-mcp",
    }
    token = "pmcp_" + jwt.encode(
        claims, SECRET if invalid != "signature" else "x" * 32, algorithm="HS256"
    )
    row = {
        **key(),
        "user_public_id": uid,
        "user_name": "test",
        "email": "test@example.com",
        "role": "user",
        "active": invalid != "inactive",
        "expires_at": now - timedelta(seconds=1) if invalid == "expired" else None,
        "revoked_at": now if invalid == "revoked" else None,
    }
    if invalid == "demoted":
        row["admin"] = True
    session = SimpleNamespace(
        execute=AsyncMock(return_value=result(None if invalid == "wrong_hash" else row))
    )

    @asynccontextmanager
    async def transaction(factory):
        yield session

    monkeypatch.setattr(mcp_keys, "unit_of_work", transaction)
    app = create_app()
    app.state.sessions = object()
    app.state.jwt_secret = SECRET
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/sources", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401


async def test_sql_lists_scope_before_pagination():
    from panoptes_backend.catalog.repository import list_terms
    from panoptes_backend.management.repository import extraction_groups, extractions
    from panoptes_backend.routines.repository import list_routines

    session = SimpleNamespace(
        info={"mcp_key": key(sites=["amazon_br"])},
        execute=AsyncMock(return_value=result(scalar=0)),
    )
    for call in [
        lambda: list_terms(session, 10, 20),
        lambda: list_routines(session, 10, 20),
        lambda: extractions(session, None, 10, 20),
        lambda: extraction_groups(session, None, 10, 20),
    ]:
        session.execute.reset_mock()
        await call()
        for invocation in session.execute.await_args_list:
            sql, params = invocation.args
            assert "mcp_key" in str(sql) and params["mcp_key"] == 5
            assert params["mcp_sites"] == ["amazon_br"]
            if "LIMIT" in str(sql):
                assert str(sql).index("mcp_key") < str(sql).index("LIMIT")


async def test_valid_mcp_key_is_scoped_and_revocation_applies_next_call(monkeypatch):
    now, uid, kid = datetime.now(UTC), uuid4(), uuid4()
    token = "pmcp_" + jwt.encode(
        {
            "sub": str(uid),
            "kid": str(kid),
            "jti": str(uuid4()),
            "iat": now,
            "nbf": now,
            "type": "mcp",
            "iss": "panoptes",
            "aud": "panoptes-mcp",
        },
        SECRET,
        algorithm="HS256",
    )
    row = {
        **key(),
        "user_public_id": uid,
        "user_name": "test",
        "email": "test@example.com",
        "role": "admin",
        "active": True,
        "expires_at": None,
        "revoked_at": None,
    }
    session = SimpleNamespace(execute=AsyncMock(return_value=result(row)))

    @asynccontextmanager
    async def transaction(factory):
        yield session

    monkeypatch.setattr(mcp_keys, "unit_of_work", transaction)
    app = create_app()
    app.state.sessions = object()
    app.state.jwt_secret = SECRET
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/sources", headers=headers)).status_code == 200
        assert (await client.get("/data", headers=headers)).status_code == 403
        me = (await client.get("/auth/me", headers=headers)).json()
        assert me["role"] == "user" and "mcp_key" not in me and "token_hash" not in me
        row["revoked_at"] = now
        assert (await client.get("/sources", headers=headers)).status_code == 401


@pytest.mark.parametrize(
    "state", ["expired", "revoked", "inactive", "demoted", "no_alerts", "lost_routine"]
)
async def test_alert_delivery_rechecks_key_and_grants(state):
    from panoptes_backend.alerts.delivery import credential_allows_delivery

    now = datetime.now(UTC)
    row = {
        **key(create_alerts=state != "no_alerts"),
        "active": state != "inactive",
        "role": "user",
        "admin": state == "demoted",
        "expires_at": now - timedelta(seconds=1) if state == "expired" else None,
        "revoked_at": now if state == "revoked" else None,
    }
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[result(row), result(found=False)])
    )
    assert not await credential_allows_delivery(
        session, 5, [{"routine_ids": [str(uuid4())]}]
    )


async def test_shared_product_history_checks_the_originating_routine():
    from panoptes_backend.catalog import pricing_repository, repository, search
    from panoptes_backend.management.repository import prices

    session = SimpleNamespace(
        info={"mcp_key": key(sites=["amazon_br"])},
        execute=AsyncMock(return_value=result(scalar=0)),
    )
    pid = uuid4()
    calls = [
        lambda: repository.read_history(session, pid, 10, 0),
        lambda: repository.list_products(session, 1, 10, 0),
        lambda: pricing_repository.history(session, pid, 10, 0),
        lambda: pricing_repository.list_offers(session, pid, 10, 0),
        lambda: search.search_products(
            session, None, search.ProductQuery(mode="recent", term_id=pid)
        ),
        lambda: prices(session, 1, 10, 0),
    ]
    for call in calls:
        session.execute.reset_mock()
        await call()
        # The final result query must scope captures, even when another routine
        # extracts the same entity. Filtering only the entity is insufficient.
        sql, params = session.execute.await_args.args
        assert "scraping.job mj" in str(sql) and "mreq.routine_public_id" in str(sql)
        assert params["mcp_key"] == 5 and params["mcp_sites"] == ["amazon_br"]
