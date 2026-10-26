from sqlalchemy import text


async def find_user(session, email):
    return (
        (
            await session.execute(
                text('SELECT * FROM "auth"."user" WHERE email=:email'), {"email": email}
            )
        )
        .mappings()
        .one_or_none()
    )


async def upsert_admin(session, password_hash, *, email, name):
    return (
        (
            await session.execute(
                text("""INSERT INTO "auth"."user" (email,name,password_hash,role)
        VALUES (:email,:name,:hash,'admin') ON CONFLICT(email) DO UPDATE
        SET name=EXCLUDED.name,password_hash=EXCLUDED.password_hash,active=true,role='admin' RETURNING *"""),
                {"hash": password_hash, "email": email, "name": name},
            )
        )
        .mappings()
        .one()
    )


async def create_session(session, user_id, public_id, refresh_hash, expires):
    await session.execute(
        text("""INSERT INTO "auth"."session" (user_id,public_id,refresh_hash,expires_at)
        VALUES (:user,:sid,:hash,:expires)"""),
        {"user": user_id, "sid": public_id, "hash": refresh_hash, "expires": expires},
    )


async def find_session(session, sid, lock=False):
    return (
        (
            await session.execute(
                text(
                    """SELECT s.*,u.public_id AS user_public_id,u.email,u.name,u.active,u.role
        FROM "auth"."session" s JOIN "auth"."user" u ON u.id=s.user_id
        WHERE s.public_id=:sid"""
                    + (" FOR UPDATE OF s" if lock else "")
                ),
                {"sid": sid},
            )
        )
        .mappings()
        .one_or_none()
    )


async def rotate(session, sid, refresh_hash):
    await session.execute(
        text('UPDATE "auth"."session" SET refresh_hash=:hash WHERE public_id=:sid'),
        {"sid": sid, "hash": refresh_hash},
    )


async def revoke(session, sid):
    await session.execute(
        text('UPDATE "auth"."session" SET revoked_at=now() WHERE public_id=:sid'),
        {"sid": sid},
    )


async def revoke_user(session, user_id):
    await session.execute(
        text('UPDATE "auth"."session" SET revoked_at=now() WHERE user_id=:uid'),
        {"uid": user_id},
    )
