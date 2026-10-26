"""Transactional webhook outbox shared by the API and extraction workers."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text


def rule_matches(rule, event, routine_id, data):
    if rule["event"] != event:
        return False
    if rule.get("routine_ids") and str(routine_id) not in rule["routine_ids"]:
        return False
    if rule.get("entity_id") and str(data.get("entity_id")) != rule["entity_id"]:
        return False
    if not event.startswith("price_"):
        return True
    if rule.get("currency", "BRL") != data.get("currency") or data.get("price") is None:
        return False
    price = Decimal(str(data["price"]))
    previous = data.get("previous_price")
    previous = Decimal(str(previous)) if previous is not None else None
    if event == "price_threshold":
        threshold = Decimal(str(rule["threshold"]))
        # Notify on entering the range, including the first known price.
        if rule.get("direction", "below") == "below":
            return price <= threshold and (previous is None or previous > threshold)
        return price >= threshold and (previous is None or previous < threshold)
    if previous is None or previous <= 0:
        return False
    change = (price - previous) / previous * 100
    target = Decimal(str(rule["percent"]))
    return change <= -target if event == "price_drop" else change >= target


async def enqueue(session, event, key, routine_id, data):
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,url,rules FROM alerting.webhook WHERE enabled FOR SHARE"
                )
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        matched = [
            rule for rule in row["rules"] if rule_matches(rule, event, routine_id, data)
        ]
        if not matched:
            continue
        event_id = uuid4()
        payload = {
            "id": str(event_id),
            "version": 1,
            "event": event,
            "occurred_at": datetime.now(UTC).isoformat(),
            "routine_id": str(routine_id) if routine_id else None,
            "data": data,
            "matched_rules": matched,
        }
        await session.execute(
            text("""INSERT INTO alerting.delivery
            (public_id,webhook_id,event,event_key,destination_url,payload)
            VALUES (:pid,:hook,:event,:key,:url,CAST(:payload AS jsonb))
            ON CONFLICT(webhook_id,event_key) DO NOTHING"""),
            {
                "pid": event_id,
                "hook": row["id"],
                "event": event,
                "key": f"{event}:{key}",
                "url": row["url"],
                "payload": json.dumps(payload, default=str),
            },
        )


async def extraction_event(session, request, event, **data):
    await enqueue(
        session,
        event,
        str(request["public_id"]),
        request.get("routine_public_id"),
        {
            "request_id": str(request["public_id"]),
            "mode": request["mode"],
            **data,
        },
    )


async def price_event(session, observation_id):
    row = (
        (
            await session.execute(
                text("""SELECT o.public_id,o.price_vl AS price,o.currency,
        o.observed_at,off.public_id AS offer_id,e.public_id AS entity_id,e.site,
        r.public_id AS request_id,r.routine_public_id,
        (SELECT prev.price_vl FROM pricing.observation prev
         WHERE prev.offer_id=o.offer_id AND prev.currency=o.currency
           AND prev.price_vl IS NOT NULL AND (prev.observed_at,prev.id)<(o.observed_at,o.id)
         ORDER BY prev.observed_at DESC,prev.id DESC LIMIT 1) AS previous_price
        FROM pricing.observation o JOIN pricing.offer off ON off.id=o.offer_id
        JOIN catalog.listing l ON l.id=off.listing_id JOIN scraping.entity e ON e.id=l.entity_id
        JOIN scraping.observation so ON so.id=o.source_observation_id
        JOIN scraping.job j ON j.id=so.job_id JOIN scraping.scrape_request r ON r.id=j.scrape_request_id
        WHERE o.id=:id AND NOT EXISTS (
          SELECT 1 FROM pricing.observation newer WHERE newer.offer_id=o.offer_id
          AND newer.currency=o.currency AND newer.price_vl IS NOT NULL
          AND (newer.observed_at,newer.id)>(o.observed_at,o.id))"""),
                {"id": observation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if not row or row["price"] is None:
        return
    data = {
        key: str(value) if value is not None else None
        for key, value in row.items()
        if key != "routine_public_id"
    }
    previous = row["previous_price"]
    data["change_percent"] = (
        str((row["price"] - previous) / previous * 100)
        if previous and previous > 0
        else None
    )
    for event in ("price_threshold", "price_drop", "price_increase"):
        await enqueue(
            session, event, str(row["public_id"]), row["routine_public_id"], data
        )
