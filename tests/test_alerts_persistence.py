"""Run against an empty disposable PostgreSQL via TEST_ALERTS_DATABASE_URL.

The upstream tables below are fixtures for the joins; alert tables use the real
migration. No pgvector or external receivers are needed. Everything rolls back.
"""

import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from panoptes_backend.alerts import delivery, router
from panoptes_contracts.alerts import AlertRule, WebhookConfig
from panoptes_database.alerts import extraction_event, price_event
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
async def test_alerts_postgres_transactions_prices_delivery_and_migration(monkeypatch):
    url = os.getenv("TEST_ALERTS_DATABASE_URL")
    if not url:
        pytest.skip("Requires empty disposable TEST_ALERTS_DATABASE_URL")
    engine = create_async_engine(url)
    routine_id, other_id, entity_id = uuid4(), uuid4(), uuid4()
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                # The fixture requires an EMPTY database; never use an app database.
                assert not (
                    await conn.execute(
                        text(
                            "SELECT 1 FROM information_schema.schemata WHERE schema_name IN ('scraping','alerting','pricing','catalog')"
                        )
                    )
                ).first()
                ddl = """
                    CREATE SCHEMA scraping; CREATE SCHEMA pricing; CREATE SCHEMA catalog;
                    CREATE TABLE scraping.scheduled_routine(id bigint,public_id uuid);
                    CREATE TABLE scraping.entity(id bigint,public_id uuid,site text);
                    CREATE TABLE scraping.scrape_request(id bigint,public_id uuid,mode text);
                    CREATE TABLE scraping.job(id bigint,scrape_request_id bigint);
                    CREATE TABLE scraping.observation(id bigint,job_id bigint);
                    CREATE TABLE catalog.listing(id bigint,entity_id bigint);
                    CREATE TABLE pricing.offer(id bigint,public_id uuid,listing_id bigint);
                    CREATE TABLE pricing.observation(id bigint,public_id uuid,offer_id bigint,source_observation_id bigint,
                      price_vl numeric(18,4),currency char(3),observed_at timestamptz)
                """
                for stmt in ddl.split(";"):
                    if stmt.strip():
                        await conn.execute(text(stmt))
                # Apply, roll back, reapply the exact production alert migration.
                for filename in [
                    "20261024_16_alerts.sql",
                    "20261024_16_alerts.rollback.sql",
                    "20261024_16_alerts.sql",
                ]:
                    for stmt in (
                        (ROOT / "migrations/sql" / filename).read_text().split(";")
                    ):
                        if stmt.strip():
                            await conn.execute(text(stmt))
                await conn.execute(
                    text(
                        "INSERT INTO scraping.scheduled_routine VALUES(1,:pid),(2,:other)"
                    ),
                    {"pid": routine_id, "other": other_id},
                )
                await conn.execute(
                    text("INSERT INTO scraping.entity VALUES(1,:pid,'amazon_br')"),
                    {"pid": entity_id},
                )
                await conn.execute(text("INSERT INTO catalog.listing VALUES(1,1)"))
                await conn.execute(
                    text("INSERT INTO pricing.offer VALUES(1,gen_random_uuid(),1)")
                )

                def sessions():
                    return AsyncSession(
                        bind=conn, join_transaction_mode="create_savepoint"
                    )

                async with sessions() as session:
                    async with session.begin():
                        webhook = await router.create_webhook(
                            WebhookConfig(
                                name="Scoped receiver",
                                url="https://example.com/events",
                                rules=[
                                    AlertRule(
                                        event="extraction_started",
                                        routine_ids=[routine_id],
                                    ),
                                    AlertRule(
                                        event="price_drop",
                                        routine_ids=[routine_id],
                                        percent="10",
                                    ),
                                    AlertRule(
                                        event="price_threshold",
                                        routine_ids=[routine_id],
                                        threshold="95",
                                    ),
                                ],
                            ),
                            session,
                        )
                        config = WebhookConfig.model_validate(
                            {k: webhook[k] for k in ("name", "url", "enabled", "rules")}
                        )
                        request = {
                            "public_id": uuid4(),
                            "mode": "discover",
                            "routine_public_id": routine_id,
                        }
                        await extraction_event(
                            session, request, "extraction_started", status="running"
                        )
                        await extraction_event(
                            session, request, "extraction_started", status="running"
                        )
                        await extraction_event(
                            session,
                            {
                                **request,
                                "public_id": uuid4(),
                                "routine_public_id": other_id,
                            },
                            "extraction_started",
                        )
                        assert (
                            len(
                                await router.list_deliveries(
                                    webhook["public_id"], 100, 0, session
                                )
                            )
                            == 1
                        )

                        # Rolling back an extraction also rolls back its outbox event.
                        savepoint = await session.begin_nested()
                        await extraction_event(
                            session,
                            {**request, "public_id": uuid4()},
                            "extraction_started",
                        )
                        await savepoint.rollback()
                        assert (
                            len(
                                await router.list_deliveries(
                                    webhook["public_id"], 100, 0, session
                                )
                            )
                            == 1
                        )

                        for i, (price, currency) in enumerate(
                            [(100, "BRL"), (1, "USD"), (90, "BRL"), (85, "BRL")], 1
                        ):
                            await session.execute(
                                text(
                                    "INSERT INTO scraping.scrape_request VALUES(:i,gen_random_uuid(),'discover',:pid)"
                                ),
                                {"i": i, "pid": routine_id},
                            )
                            await session.execute(
                                text("INSERT INTO scraping.job VALUES(:i,:i)"), {"i": i}
                            )
                            await session.execute(
                                text("INSERT INTO scraping.observation VALUES(:i,:i)"),
                                {"i": i},
                            )
                            await session.execute(
                                text("""INSERT INTO pricing.observation VALUES(:i,gen_random_uuid(),1,:i,:price,:currency,
                                now()+CAST(:i AS bigint)*interval '1 second')"""),
                                {"i": i, "price": price, "currency": currency},
                            )
                            await price_event(session, i)
                            await price_event(session, i)
                        rows = await router.list_deliveries(
                            webhook["public_id"], 100, 0, session
                        )
                        assert {r["event"] for r in rows} == {
                            "extraction_started",
                            "price_threshold",
                            "price_drop",
                        }
                        assert len(rows) == 3
                        payload = (
                            await session.execute(
                                text(
                                    "SELECT payload FROM alerting.delivery WHERE event='price_drop'"
                                )
                            )
                        ).scalar_one()
                        assert payload["data"]["previous_price"] == "100.0000"
                        assert payload["data"]["price"] == "90.0000"
                        assert payload["routine_id"] == str(routine_id)

                attempts = []

                def receive(request):
                    attempts.append(json.loads(request.content))
                    return httpx.Response(503 if len(attempts) == 1 else 204)

                monkeypatch.setattr(
                    delivery, "resolve_destination", lambda _: resolve()
                )

                async def resolve():
                    return (
                        httpx.URL("https://93.184.216.34/events"),
                        "example.com",
                        "example.com",
                    )

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(receive)
                ) as client:
                    assert await delivery.deliver_one(sessions, client)
                    # Make the failed delivery immediately due, preserving its ID.
                    await conn.execute(
                        text(
                            "UPDATE alerting.delivery SET next_attempt_at=now()-interval '1 second' WHERE attempts=1"
                        )
                    )
                    assert await delivery.deliver_one(sessions, client)
                    assert attempts[0]["id"] == attempts[1]["id"]
                    async with sessions() as session:
                        async with session.begin():
                            await router.update_webhook(
                                webhook["public_id"],
                                config.model_copy(update={"enabled": False}),
                                session,
                            )
                            rows = await router.list_deliveries(
                                webhook["public_id"], 100, 0, session
                            )
                            assert sorted(r["status"] for r in rows) == [
                                "cancelled",
                                "cancelled",
                                "delivered",
                            ]
                            await extraction_event(
                                session,
                                {**request, "public_id": uuid4()},
                                "extraction_started",
                            )
                            assert (
                                len(
                                    await router.list_deliveries(
                                        webhook["public_id"], 100, 0, session
                                    )
                                )
                                == 3
                            )
                            await router.delete_webhook(webhook["public_id"], session)
                            assert (
                                await session.execute(
                                    text("SELECT count(*) FROM alerting.delivery")
                                )
                            ).scalar_one() == 0
                    assert not await delivery.deliver_one(sessions, client)
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
