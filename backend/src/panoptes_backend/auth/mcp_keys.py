"""User-issued MCP JWTs. The database is authoritative for revocation and grants."""

import calendar
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from panoptes_database.session import unit_of_work
from sqlalchemy import text

from .mcp_models import MCPKeyCreate
from .router import current_user, unauthorized
from .security import token_hash

router = APIRouter(prefix="/auth/mcp-keys", tags=["MCP credentials"])
FIELDS = "public_id,name,admin,permissions,expires_at,revoked_at,created_at"


def expiration(value, now=None):
    now = now or datetime.now(UTC)
    if value.expiration == "never":
        return None
    if value.expiration == "custom":
        return value.expires_at
    if value.expiration in ("1w", "2w"):
        return now + timedelta(weeks=1 if value.expiration == "1w" else 2)
    months = {"1m": 1, "6m": 6, "1y": 12}[value.expiration]
    year, month = divmod(now.year * 12 + now.month - 1 + months, 12)
    month += 1
    return now.replace(
        year=year, month=month, day=min(now.day, calendar.monthrange(year, month)[1])
    )


async def browser_user(user=Depends(current_user)):
    if user.get("mcp_key"):
        raise HTTPException(403, "Use uma sessão de usuário para gerenciar chaves MCP.")
    return user


@router.get("")
async def list_keys(request: Request, user=Depends(browser_user)):
    async with unit_of_work(request.app.state.sessions) as session:
        rows = (
            (
                await session.execute(
                    text(f"""SELECT {FIELDS},
          ARRAY(SELECT r.public_id FROM auth.mcp_key_routine kr
            JOIN scraping.scheduled_routine r ON r.id=kr.routine_id
            WHERE kr.key_id=k.id) AS routine_ids
          FROM auth.mcp_key k WHERE user_id=(SELECT id FROM auth."user" WHERE public_id=:uid)
          ORDER BY created_at DESC"""),
                    {"uid": user["public_id"]},
                )
            )
            .mappings()
            .all()
        )
        return rows


@router.post("", status_code=201)
async def create_key(value: MCPKeyCreate, request: Request, user=Depends(browser_user)):
    if value.admin and user["role"] != "admin":
        raise HTTPException(
            403, "Apenas administradores podem emitir uma chave MCP admin."
        )
    kid, now, expires = uuid4(), datetime.now(UTC), expiration(value)
    claims = {
        "sub": str(user["public_id"]),
        "kid": str(kid),
        "type": "mcp",
        "jti": str(uuid4()),
        "iat": now,
        "nbf": now,
        "iss": "panoptes",
        "aud": "panoptes-mcp",
    }
    if expires:
        claims["exp"] = expires
    token = "pmcp_" + jwt.encode(
        claims, request.app.state.jwt_secret, algorithm="HS256"
    )
    async with unit_of_work(request.app.state.sessions) as session:
        ids = [] if value.admin else list(set(value.routine_ids))
        found = (
            (
                await session.execute(
                    text("""SELECT id FROM scraping.scheduled_routine
          WHERE public_id=ANY(CAST(:ids AS uuid[]))"""),
                    {"ids": ids},
                )
            )
            .scalars()
            .all()
        )
        if len(found) != len(ids):
            raise HTTPException(422, "Rotina não encontrada.")
        key = (
            (
                await session.execute(
                    text(f"""INSERT INTO auth.mcp_key
          (public_id,user_id,name,token_hash,admin,permissions,expires_at)
          VALUES (:kid,(SELECT id FROM auth."user" WHERE public_id=:uid),:name,:hash,
          :admin,CAST(:permissions AS jsonb),:expires) RETURNING id,{FIELDS}"""),
                    {
                        "kid": kid,
                        "uid": user["public_id"],
                        "name": value.name,
                        "hash": token_hash(token),
                        "admin": value.admin,
                        "permissions": json.dumps(
                            {} if value.admin else value.permissions.model_dump()
                        ),
                        "expires": expires,
                    },
                )
            )
            .mappings()
            .one()
        )
        for rid in found:
            await session.execute(
                text("""INSERT INTO auth.mcp_key_routine(key_id,routine_id)
              VALUES (:kid,:rid)"""),
                {"kid": key["id"], "rid": rid},
            )
        return {
            **{k: v for k, v in key.items() if k != "id"},
            "routine_ids": ids,
            "key": token,
        }


@router.delete("/{key_id}", status_code=204)
async def revoke_key(key_id: UUID, request: Request, user=Depends(browser_user)):
    async with unit_of_work(request.app.state.sessions) as session:
        found = (
            await session.execute(
                text("""UPDATE auth.mcp_key SET revoked_at=coalesce(revoked_at,now())
          WHERE public_id=:kid AND user_id=(SELECT id FROM auth."user" WHERE public_id=:uid)
          RETURNING id"""),
                {"kid": key_id, "uid": user["public_id"]},
            )
        ).scalar_one_or_none()
        if found is None:
            raise HTTPException(404, "Chave não encontrada.")


async def authenticate(request, token):
    from .mcp_policy import authorize

    try:
        claims = jwt.decode(
            token[5:],
            request.app.state.jwt_secret,
            algorithms=["HS256"],
            issuer="panoptes",
            audience="panoptes-mcp",
            options={"require": ["sub", "kid", "type", "jti", "iat", "nbf"]},
        )
        from uuid import UUID

        kid, uid = UUID(claims["kid"]), UUID(claims["sub"])
        if claims["type"] != "mcp":
            raise ValueError("Invalid token type")
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise unauthorized() from None
    async with unit_of_work(request.app.state.sessions) as session:
        row = (
            (
                await session.execute(
                    text("""SELECT k.*,u.public_id AS user_public_id,
          u.name AS user_name,u.email,u.role,u.active FROM auth.mcp_key k
          JOIN auth."user" u ON u.id=k.user_id WHERE k.public_id=:kid
          AND u.public_id=:uid AND k.token_hash=:hash"""),
                    {"kid": kid, "uid": uid, "hash": token_hash(token)},
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            row is None
            or not row["active"]
            or row["revoked_at"] is not None
            or (
                row["expires_at"] is not None and row["expires_at"] <= datetime.now(UTC)
            )
        ):
            raise unauthorized()
        # A key never gains permissions when its issuer loses administrator status.
        if row["admin"] and row["role"] != "admin":
            raise unauthorized()
        user = {
            "public_id": row["user_public_id"],
            "name": row["user_name"],
            "email": row["email"],
            "role": "admin" if row["admin"] else "user",
            "mcp_key": dict(row),
        }
        await authorize(request, session, user)
        return user
