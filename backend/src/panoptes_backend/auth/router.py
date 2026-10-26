import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from panoptes_database.session import unit_of_work

from . import repository, services
from .models import Login, Refresh
from .security import decode_token

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


def unauthorized():
    return HTTPException(
        401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"}
    )


def decode(request, token, kind):
    try:
        return decode_token(request.app.state.jwt_secret, token, kind)
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise unauthorized() from None


async def current_user(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
):
    if credentials is None:
        raise unauthorized()
    if credentials.credentials.startswith("pmcp_"):
        from .mcp_keys import authenticate

        user = await authenticate(request, credentials.credentials)
        request.state.principal = user
        return user
    claims = decode(request, credentials.credentials, "access")
    async with unit_of_work(request.app.state.sessions) as session:
        row = await repository.find_session(session, claims["sid"])
    if not services.valid_session(row, claims):
        raise unauthorized()
    user = {
        "public_id": row["user_public_id"],
        "name": row["name"],
        "email": row["email"],
        "role": row.get("role", "user"),
        "session_id": row["public_id"],
    }
    request.state.principal = user
    return user


@router.post("/login")
async def login(value: Login, request: Request):
    async with unit_of_work(request.app.state.sessions) as session:
        pair = await services.login(
            session,
            request.app.state.jwt_secret,
            value.email,
            value.password.get_secret_value(),
        )
    if pair is None:
        raise unauthorized()
    return pair


@router.post("/refresh")
async def refresh(value: Refresh, request: Request):
    token = value.refresh_token.get_secret_value()
    claims = decode(request, token, "refresh")
    async with unit_of_work(request.app.state.sessions) as session:
        pair = await services.refresh(
            session, request.app.state.jwt_secret, claims, token
        )
    # Replay revocation must commit before returning an authentication error.
    if pair is None:
        raise unauthorized()
    return pair


@router.get("/me")
async def me(user=Depends(current_user)):
    return {k: v for k, v in user.items() if k not in {"session_id", "mcp_key"}}


@router.post("/logout", status_code=204)
async def logout(request: Request, user=Depends(current_user)):
    if user.get("mcp_key"):
        raise HTTPException(403, "Use uma sessão de usuário.")
    async with unit_of_work(request.app.state.sessions) as session:
        await repository.revoke(session, user["session_id"])
