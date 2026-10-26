import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from panoptes_contracts.alerts import Webhook, WebhookConfig, WebhookDelivery
from sqlalchemy import text

from ..catalog.router import session_dependency
from ..core.errors import NotFoundError

router = APIRouter(prefix="/alerts/webhooks", tags=["alerts"])
FIELDS = "public_id,name,url,enabled,rules,created_at,updated_at"


async def read_webhook(session, webhook_id, *, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    row = (
        (
            await session.execute(
                text(
                    f"SELECT {FIELDS} FROM alerting.webhook WHERE public_id=:pid{suffix}"
                ),
                {"pid": webhook_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise NotFoundError("Webhook não encontrado")
    return row


async def validate_references(session, value):
    routines = {uid for rule in value.rules for uid in rule.routine_ids}
    entities = {rule.entity_id for rule in value.rules if rule.entity_id}
    for table, ids in (
        ("scraping.scheduled_routine", routines),
        ("scraping.entity", entities),
    ):
        if not ids:
            continue
        found = (
            (
                await session.execute(
                    text(
                        f"SELECT public_id FROM {table} WHERE public_id=ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": list(ids)},
                )
            )
            .scalars()
            .all()
        )
        if set(found) != ids:
            raise HTTPException(
                422, "Rotina ou produto não encontrado. Consulte os IDs existentes."
            )


def parameters(value):
    return {
        "name": value.name,
        "url": str(value.url),
        "enabled": value.enabled,
        "rules": json.dumps([rule.model_dump(mode="json") for rule in value.rules]),
    }


@router.get("", response_model=list[Webhook])
async def list_webhooks(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session=Depends(session_dependency),
):
    from ..auth.mcp_policy import check_rules, key_for

    key = key_for(session)
    if key:
        rows = (
            (
                await session.execute(
                    text(f"""SELECT {FIELDS} FROM alerting.webhook
          WHERE mcp_key_id=:kid ORDER BY id"""),
                    {"kid": key["id"]},
                )
            )
            .mappings()
            .all()
        )
        allowed = []
        for row in rows:
            try:
                await check_rules(session, key, row["rules"])
                allowed.append(row)
            except HTTPException as exc:
                if exc.status_code != 403:
                    raise
        return allowed[offset : offset + limit]
    return (
        (
            await session.execute(
                text(
                    f"SELECT {FIELDS} FROM alerting.webhook ORDER BY id LIMIT :limit OFFSET :offset"
                ),
                {"limit": limit, "offset": offset},
            )
        )
        .mappings()
        .all()
    )


@router.post("", response_model=Webhook, status_code=201)
async def create_webhook(value: WebhookConfig, session=Depends(session_dependency)):
    from ..auth.mcp_policy import key_for

    info = getattr(session, "info", {})
    issuer = info.get("mcp_issuer") if isinstance(info, dict) else None
    issuer = issuer or key_for(session)
    await validate_references(session, value)
    return (
        (
            await session.execute(
                text(f"""INSERT INTO alerting.webhook(name,url,enabled,rules,mcp_key_id)
        VALUES (:name,:url,:enabled,CAST(:rules AS jsonb),:kid) RETURNING {FIELDS}"""),
                {**parameters(value), "kid": issuer["id"] if issuer else None},
            )
        )
        .mappings()
        .one()
    )


@router.get("/{webhook_id}", response_model=Webhook)
async def get_webhook(webhook_id: UUID, session=Depends(session_dependency)):
    return await read_webhook(session, webhook_id)


@router.put("/{webhook_id}", response_model=Webhook)
async def update_webhook(
    webhook_id: UUID, value: WebhookConfig, session=Depends(session_dependency)
):
    await read_webhook(session, webhook_id, lock=True)
    await validate_references(session, value)
    # Cancel the queued snapshot if the receiver or rules change. Re-enabling
    # never sends events collected while the destination was paused.
    await session.execute(
        text("""UPDATE alerting.delivery SET status='cancelled'
        WHERE webhook_id=(SELECT id FROM alerting.webhook WHERE public_id=:pid)
        AND status='pending'"""),
        {"pid": webhook_id},
    )
    return (
        (
            await session.execute(
                text(f"""UPDATE alerting.webhook SET name=:name,url=:url,
        enabled=:enabled,rules=CAST(:rules AS jsonb),updated_at=now()
        WHERE public_id=:pid RETURNING {FIELDS}"""),
                {**parameters(value), "pid": webhook_id},
            )
        )
        .mappings()
        .one()
    )


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: UUID, session=Depends(session_dependency)):
    await read_webhook(session, webhook_id, lock=True)
    await session.execute(
        text("DELETE FROM alerting.webhook WHERE public_id=:pid"), {"pid": webhook_id}
    )


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDelivery])
async def list_deliveries(
    webhook_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session=Depends(session_dependency),
):
    await read_webhook(session, webhook_id)
    return (
        (
            await session.execute(
                text("""SELECT d.public_id,d.event,d.status,d.attempts,
        d.http_status,d.last_error,d.created_at,d.delivered_at,d.next_attempt_at
        FROM alerting.delivery d JOIN alerting.webhook w ON w.id=d.webhook_id
        WHERE w.public_id=:pid ORDER BY d.id DESC LIMIT :limit OFFSET :offset"""),
                {"pid": webhook_id, "limit": limit, "offset": offset},
            )
        )
        .mappings()
        .all()
    )
