from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth import repository, services
from panoptes_backend.auth.security import (
    PASSWORDS,
    decode_token,
    encode_token,
    token_hash,
    token_pair,
)
from panoptes_backend.main import create_app

SECRET = "test-secret-with-at-least-32-bytes-long"


@pytest.mark.parametrize(
    "path,method",
    [
        ("/contracts", "get"),
        ("/openapi.json", "get"),
        ("/search-terms", "get"),
        ("/search-terms", "post"),
        ("/routines", "get"),
        ("/routines", "post"),
        ("/auth/me", "get"),
        ("/auth/logout", "post"),
        (f"/assets/{uuid4()}/url", "get"),
        (f"/products/{uuid4()}/refresh", "post"),
    ],
)
async def test_api_requires_authentication(path, method):
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        result = await getattr(client, method)(path)
    assert result.status_code == 401
    assert result.headers["WWW-Authenticate"] == "Bearer"


def test_jwt_types_expiry_and_signature():
    pair = token_pair(SECRET, uuid4(), uuid4(), datetime.now(UTC) + timedelta(days=1))
    assert decode_token(SECRET, pair["access_token"], "access")["type"] == "access"
    for token, secret in [
        (pair["refresh_token"], SECRET),
        (pair["access_token"], "wrong-secret-with-at-least-32bytes"),
    ]:
        with pytest.raises(jwt.InvalidTokenError):
            decode_token(secret, token, "access")
    expired = encode_token(
        SECRET, uuid4(), uuid4(), "access", datetime.now(UTC) - timedelta(seconds=2)
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(SECRET, expired, "access")


async def test_refresh_rotation_and_replay_revoke(monkeypatch):
    uid, sid = uuid4(), uuid4()
    pair = token_pair(SECRET, uid, sid, datetime.now(UTC) + timedelta(days=1))
    row = {
        "public_id": sid,
        "user_public_id": uid,
        "active": True,
        "revoked_at": None,
        "expires_at": datetime.now(UTC) + timedelta(days=1),
        "refresh_hash": token_hash(pair["refresh_token"]),
    }
    monkeypatch.setattr(repository, "find_session", AsyncMock(return_value=row))
    monkeypatch.setattr(repository, "rotate", AsyncMock())
    monkeypatch.setattr(repository, "revoke", AsyncMock())
    claims = decode_token(SECRET, pair["refresh_token"], "refresh")
    rotated = await services.refresh(object(), SECRET, claims, pair["refresh_token"])
    assert rotated["refresh_token"] != pair["refresh_token"]
    row["refresh_hash"] = token_hash(rotated["refresh_token"])
    assert (
        await services.refresh(object(), SECRET, claims, pair["refresh_token"]) is None
    )
    repository.revoke.assert_awaited_once()


async def test_seed_admin_reuses_hash_and_resets_changed_password(monkeypatch):
    monkeypatch.setenv("SUPERUSER_NAME", "Custom Admin")
    monkeypatch.setenv("SUPERUSER_EMAIL", " CUSTOM@example.com ")
    monkeypatch.setenv("SUPERUSER_PASSWORD", "custom-password")
    row = {"id": 1, "password_hash": PASSWORDS.hash("custom-password")}
    monkeypatch.setattr(repository, "find_user", AsyncMock(return_value=row))
    monkeypatch.setattr(repository, "upsert_admin", AsyncMock(return_value=row))
    monkeypatch.setattr(repository, "revoke_user", AsyncMock())
    session = object()
    await services.seed_admin(session)
    repository.find_user.assert_awaited_once_with(session, "custom@example.com")
    assert repository.upsert_admin.await_args.kwargs == {
        "email": "custom@example.com",
        "name": "Custom Admin",
    }
    assert repository.upsert_admin.await_args.args[1] == row["password_hash"]
    repository.revoke_user.assert_not_awaited()
    row["password_hash"] = PASSWORDS.hash("other-password")
    await services.seed_admin(object())
    assert PASSWORDS.verify(
        "custom-password", repository.upsert_admin.await_args.args[1]
    )
    repository.revoke_user.assert_awaited_once()


@pytest.mark.parametrize(
    "missing", ["SUPERUSER_NAME", "SUPERUSER_EMAIL", "SUPERUSER_PASSWORD", "all"]
)
@pytest.mark.parametrize("value", [None, "", "   "])
async def test_seed_admin_skips_missing_or_blank_credentials(
    monkeypatch, missing, value
):
    for key, configured in {
        "SUPERUSER_NAME": "admin",
        "SUPERUSER_EMAIL": "admin@panoptes.com",
        "SUPERUSER_PASSWORD": "admin",
    }.items():
        if missing in {key, "all"}:
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        else:
            monkeypatch.setenv(key, configured)
    monkeypatch.setattr(repository, "find_user", AsyncMock())
    monkeypatch.setattr(repository, "upsert_admin", AsyncMock())
    await services.seed_admin(object())
    repository.find_user.assert_not_awaited()
    repository.upsert_admin.assert_not_awaited()


async def test_seed_admin_creates_configured_superuser(monkeypatch):
    monkeypatch.setenv("SUPERUSER_NAME", "admin")
    monkeypatch.setenv("SUPERUSER_EMAIL", "admin@panoptes.com")
    monkeypatch.setenv("SUPERUSER_PASSWORD", "admin")
    monkeypatch.setattr(repository, "find_user", AsyncMock(return_value=None))
    monkeypatch.setattr(repository, "upsert_admin", AsyncMock(return_value={"id": 1}))
    monkeypatch.setattr(repository, "revoke_user", AsyncMock())
    await services.seed_admin(object())
    assert PASSWORDS.verify("admin", repository.upsert_admin.await_args.args[1])
    repository.revoke_user.assert_not_awaited()
