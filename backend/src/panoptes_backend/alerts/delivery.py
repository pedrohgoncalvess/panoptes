"""Durable, bounded webhook delivery with DNS pinning and no redirects."""

import asyncio
import ipaddress
import json
import logging
import os
import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from panoptes_database.session import unit_of_work
from sqlalchemy import text

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


async def credential_allows_delivery(session, key_id, rules):
    from ..auth.mcp_policy import check_rules

    key = (
        (
            await session.execute(
                text("""SELECT k.*,u.active,u.role FROM auth.mcp_key k
      JOIN auth."user" u ON u.id=k.user_id WHERE k.id=:kid"""),
                {"kid": key_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        key is None
        or not key["active"]
        or key["revoked_at"] is not None
        or (key["expires_at"] is not None and key["expires_at"] <= datetime.now(UTC))
    ):
        return False
    if key["admin"]:
        return key["role"] == "admin"
    if not key["permissions"].get("create_alerts"):
        return False
    try:
        await check_rules(session, key, rules)
    except HTTPException:
        return False
    return True


async def resolve_destination(url):
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    records = await asyncio.wait_for(
        asyncio.get_running_loop().getaddrinfo(
            parsed.hostname,
            port,
            type=socket.SOCK_STREAM,
        ),
        timeout=5,
    )
    addresses = {record[4][0] for record in records}
    if not addresses:
        raise ValueError("destination_unresolved")
    if os.getenv("WEBHOOK_ALLOW_PRIVATE_NETWORKS") != "true" and any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise ValueError("destination_private_network")
    address = sorted(addresses)[0]
    # Pin the resolved address for this attempt to prevent DNS rebinding.
    pinned = httpx.URL(url).copy_with(host=address)
    return pinned, parsed.netloc, parsed.hostname


async def send(client, row):
    pinned, host, hostname = await resolve_destination(row["destination_url"])
    body = json.dumps(
        row["payload"], ensure_ascii=False, separators=(",", ":")
    ).encode()
    # Stream and close the response without buffering an unbounded receiver body.
    async with client.stream(
        "POST",
        pinned,
        content=body,
        headers={
            "Host": host,
            "Content-Type": "application/json",
            "User-Agent": "Panoptes-Webhooks/1",
            "X-Panoptes-Event": row["event"],
            "X-Panoptes-Delivery": str(row["public_id"]),
        },
        extensions={"sni_hostname": hostname},
    ) as response:
        return response.status_code


async def deliver_one(sessions, client):
    # Lock through the bounded HTTP request: concurrent API instances skip this
    # row, and pause/edit/delete serialize with deliveries already in progress.
    async with unit_of_work(sessions) as session:
        row = (
            (
                await session.execute(
                    text("""SELECT d.*,w.mcp_key_id,w.rules FROM alerting.delivery d
            JOIN alerting.webhook w ON w.id=d.webhook_id
            WHERE d.status='pending' AND w.enabled AND d.next_attempt_at<=now()
            ORDER BY d.next_attempt_at,d.id LIMIT 1 FOR UPDATE OF d,w SKIP LOCKED""")
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return False
        if row.get("mcp_key_id") and not await credential_allows_delivery(
            session, row["mcp_key_id"], row["rules"]
        ):
            await session.execute(
                text("""UPDATE alerting.delivery SET status='cancelled'
              WHERE webhook_id=:wid AND status='pending' """),
                {"wid": row["webhook_id"]},
            )
            await session.execute(
                text("UPDATE alerting.webhook SET enabled=false WHERE id=:wid"),
                {"wid": row["webhook_id"]},
            )
            return True
        status_code, error = None, None
        try:
            status_code = await asyncio.wait_for(send(client, row), timeout=15)
            if not 200 <= status_code < 300:
                error = f"http_{status_code}"
        except (httpx.HTTPError, OSError, ValueError, TimeoutError):
            error = "destination_unavailable_or_disallowed"
        attempts = row["attempts"] + 1
        status = (
            "delivered"
            if error is None
            else "failed"
            if attempts >= MAX_ATTEMPTS
            else "pending"
        )
        await session.execute(
            text("""UPDATE alerting.delivery SET status=:status,
            attempts=:attempts,http_status=:http,last_error=:error,
            next_attempt_at=:next,delivered_at=:delivered WHERE id=:id"""),
            {
                "id": row["id"],
                "status": status,
                "attempts": attempts,
                "http": status_code,
                "error": error,
                "next": datetime.now(UTC) + timedelta(seconds=30 * 2 ** (attempts - 1)),
                "delivered": datetime.now(UTC) if status == "delivered" else None,
            },
        )
        return True


async def run(sessions):
    async with httpx.AsyncClient(
        timeout=10,
        follow_redirects=False,
        trust_env=False,
        limits=httpx.Limits(max_keepalive_connections=0),
    ) as client:
        while True:
            try:
                worked = await deliver_one(sessions, client)
            except Exception:
                logger.exception("Webhook dispatcher failed")
                worked = False
            if not worked:
                await asyncio.sleep(2)
