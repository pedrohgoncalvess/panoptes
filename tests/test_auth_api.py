from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth import repository, router, services
from panoptes_backend.auth.security import PASSWORDS, token_hash
from panoptes_backend.main import create_app


async def test_login_refresh_replay_and_logout_http(monkeypatch):
    user = {
        "id": 1,
        "public_id": uuid4(),
        "email": "admin@panoptes.com",
        "name": "admin",
        "password_hash": PASSWORDS.hash("admin"),
        "active": True,
    }
    sessions = {}
    transactions = []

    @asynccontextmanager
    async def transaction(factory):
        yield object()
        transactions.append("committed")

    async def create(session, uid, sid, hashed, expires):
        sessions[str(sid)] = {
            "public_id": sid,
            "user_public_id": user["public_id"],
            "email": user["email"],
            "name": user["name"],
            "active": True,
            "expires_at": expires,
            "revoked_at": None,
            "refresh_hash": hashed,
        }

    async def find(session, sid, lock=False):
        return sessions.get(str(sid))

    async def rotate(session, sid, hashed):
        sessions[str(sid)]["refresh_hash"] = hashed

    async def revoke(session, sid):
        sessions[str(sid)]["revoked_at"] = datetime.now(UTC)

    monkeypatch.setattr(router, "unit_of_work", transaction)
    monkeypatch.setattr(repository, "find_user", AsyncMock(return_value=user))
    monkeypatch.setattr(repository, "create_session", create)
    monkeypatch.setattr(repository, "find_session", find)
    monkeypatch.setattr(repository, "rotate", rotate)
    monkeypatch.setattr(repository, "revoke", revoke)
    app = create_app()
    app.state.jwt_secret = "test-secret-at-least-32-bytes-long-value"
    app.state.sessions = object()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        rejected = await client.post(
            "/auth/login", json={"email": user["email"], "password": "wrong"}
        )
        assert rejected.status_code == 401
        result = await client.post(
            "/auth/login", json={"email": user["email"], "password": "admin"}
        )
        assert result.status_code == 200
        pair = result.json()
        assert len(sessions) == 1 and next(iter(sessions.values()))[
            "refresh_hash"
        ] == token_hash(pair["refresh_token"])
        headers = {"Authorization": "Bearer " + pair["access_token"]}
        me = await client.get("/auth/me", headers=headers)
        assert me.json() == {
            "public_id": str(user["public_id"]),
            "email": user["email"],
            "name": "admin",
            "role": "user",
        }
        assert (
            await client.get(
                "/contracts",
                headers={"Authorization": "Bearer " + pair["refresh_token"]},
            )
        ).status_code == 401
        renewed = await client.post(
            "/auth/refresh", json={"refresh_token": pair["refresh_token"]}
        )
        assert renewed.status_code == 200
        before = len(transactions)
        replay = await client.post(
            "/auth/refresh", json={"refresh_token": pair["refresh_token"]}
        )
        assert replay.status_code == 401 and len(transactions) == before + 1
        assert (await client.get("/contracts", headers=headers)).status_code == 401
        result = await client.post(
            "/auth/login", json={"email": user["email"], "password": "admin"}
        )
        pair = result.json()
        headers = {"Authorization": "Bearer " + pair["access_token"]}
        assert (await client.post("/auth/logout", headers=headers)).status_code == 204
        assert (await client.get("/auth/me", headers=headers)).status_code == 401
        assert (
            await client.post(
                "/auth/refresh", json={"refresh_token": pair["refresh_token"]}
            )
        ).status_code == 401


async def test_inactive_user_and_expired_session_are_rejected(monkeypatch):
    monkeypatch.setattr(
        repository,
        "find_user",
        AsyncMock(
            return_value={
                "id": 1,
                "public_id": uuid4(),
                "active": False,
                "password_hash": PASSWORDS.hash("admin"),
            }
        ),
    )
    assert (
        await services.login(object(), "x" * 32, "admin@panoptes.com", "admin") is None
    )
    uid = uuid4()
    assert not services.valid_session(
        {
            "active": True,
            "revoked_at": None,
            "expires_at": datetime.now(UTC) - timedelta(seconds=1),
            "user_public_id": uid,
        },
        {"sub": str(uid)},
    )
