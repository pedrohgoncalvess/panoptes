import asyncio
import hmac
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from . import repository
from .security import PASSWORDS, token_hash, token_pair


async def seed_admin(session):
    name = os.getenv("SUPERUSER_NAME", "").strip()
    email = os.getenv("SUPERUSER_EMAIL", "").strip().lower()
    password = os.getenv("SUPERUSER_PASSWORD", "")
    if not name or not email or not password.strip():
        return
    existing = await repository.find_user(session, email)
    matches = existing and await asyncio.to_thread(
        PASSWORDS.verify, password, existing["password_hash"]
    )
    hashed = (
        existing["password_hash"]
        if matches
        else await asyncio.to_thread(PASSWORDS.hash, password)
    )
    user = await repository.upsert_admin(session, hashed, email=email, name=name)
    if existing and not matches:
        await repository.revoke_user(session, user["id"])


async def login(session, secret, email, password):
    user = await repository.find_user(session, email.strip().lower())
    # Unknown users also require Argon2 verification.
    hashed = (
        user["password_hash"]
        if user
        else await asyncio.to_thread(PASSWORDS.hash, "invalid-password")
    )
    valid = await asyncio.to_thread(PASSWORDS.verify, password, hashed)
    if not user or not user["active"] or not valid:
        return None
    sid, expires = uuid4(), datetime.now(UTC) + timedelta(hours=10)
    pair = token_pair(secret, user["public_id"], sid, expires)
    await repository.create_session(
        session, user["id"], sid, token_hash(pair["refresh_token"]), expires
    )
    return pair


def valid_session(row, claims):
    return (
        row is not None
        and row["active"]
        and row["revoked_at"] is None
        and row["expires_at"] > datetime.now(UTC)
        and str(row["user_public_id"]) == claims["sub"]
    )


async def refresh(session, secret, claims, token):
    row = await repository.find_session(session, claims["sid"], lock=True)
    if not valid_session(row, claims):
        return None
    if not hmac.compare_digest(row["refresh_hash"], token_hash(token)):
        await repository.revoke(session, claims["sid"])
        return None
    pair = token_pair(
        secret, row["user_public_id"], row["public_id"], row["expires_at"]
    )
    await repository.rotate(session, claims["sid"], token_hash(pair["refresh_token"]))
    return pair
