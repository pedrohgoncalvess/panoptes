import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from pwdlib import PasswordHash

PASSWORDS = PasswordHash.recommended()


def load_secret():
    secret = os.environ.get("JWT_SECRET", "")
    if len(secret.encode()) < 32:
        raise ValueError("JWT_SECRET must contain at least 32 bytes")
    return secret


def encode_token(secret, user_id, session_id, kind, expires):
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "sid": str(session_id),
            "type": kind,
            "jti": str(uuid4()),
            "iat": now,
            "nbf": now,
            "exp": expires,
            "iss": "panoptes",
            "aud": "panoptes-api",
        },
        secret,
        algorithm="HS256",
    )


def decode_token(secret, token, kind):
    claims = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        issuer="panoptes",
        audience="panoptes-api",
        options={"require": ["sub", "sid", "type", "jti", "iat", "nbf", "exp"]},
    )
    if claims["type"] != kind:
        raise jwt.InvalidTokenError("Invalid token type")
    from uuid import UUID

    UUID(claims["sub"])
    UUID(claims["sid"])
    return claims


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def token_pair(secret, user, session_id, expires):
    return {
        "access_token": encode_token(
            secret,
            user,
            session_id,
            "access",
            min(expires, datetime.now(UTC) + timedelta(hours=2)),
        ),
        "refresh_token": encode_token(secret, user, session_id, "refresh", expires),
        "token_type": "bearer",
        "expires_in": min(
            7200, max(0, int((expires - datetime.now(UTC)).total_seconds()))
        ),
        "refresh_expires_in": max(
            0, int((expires - datetime.now(UTC)).total_seconds())
        ),
    }
