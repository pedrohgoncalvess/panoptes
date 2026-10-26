"""Opt-in real SQL regressions in a newly initialized, disposable PostgreSQL.

Set RUN_PRICE_QUERY_POSTGRES_TESTS=1 and PANOPTES_TEST_POSTGRES_BIN to a local
PostgreSQL bin directory. No existing database or application key is used.
"""

import os
import re
import socket
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi import Request
from mcp.shared.memory import create_connected_server_and_client_session
from panoptes_backend.auth import mcp_policy
from panoptes_backend.auth.mcp_models import MCPPermissions
from panoptes_backend.auth.router import current_user
from panoptes_backend.main import create_app
from panoptes_backend.management import price_analytics
from panoptes_backend.management.router import price_filters
from panoptes_mcp.client import PanoptesClient
from panoptes_mcp.server import create_server
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]
TERM = UUID("00000000-0000-4000-8000-000000000001")
START = datetime(2026, 10, 26, 8, tzinfo=UTC)


@pytest.fixture
def isolated_price_postgres(tmp_path):
    if os.getenv("RUN_PRICE_QUERY_POSTGRES_TESTS") != "1":
        pytest.skip("Requires opt-in disposable PostgreSQL cluster")
    binaries = Path(os.environ["PANOPTES_TEST_POSTGRES_BIN"])
    if not (binaries / "initdb.exe").is_file():
        pytest.skip("PostgreSQL Windows binaries unavailable")
    data = tmp_path / "postgres"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    def run(name, *args):
        subprocess.run(
            [str(binaries / name), *map(str, args)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    run(
        "initdb.exe",
        "-D",
        data,
        "-U",
        "postgres",
        "-A",
        "trust",
        "--no-locale",
        "-E",
        "UTF8",
    )
    run(
        "pg_ctl.exe",
        "-D",
        data,
        "-l",
        tmp_path / "postgres.log",
        "-o",
        f"-p {port} -h 127.0.0.1",
        "-w",
        "start",
    )
    try:
        yield f"postgresql+asyncpg://postgres@127.0.0.1:{port}/postgres"
    finally:
        run("pg_ctl.exe", "-D", data, "-m", "fast", "-w", "stop")


async def seed(connection):
    # Real PostgreSQL types and current migration columns; unrelated FK tables
    # are omitted so the fixture only initializes the pricing query surface.
    tables = {
        "scraping.entity",
        "scraping.job",
        "scraping.observation",
        "scraping.search_term",
        "scraping.search_term_entity",
        "scraping.tracking_target",
        "scraping.scrape_request",
        "catalog.listing",
        "pricing.offer",
        "pricing.observation",
        "pricing.promotion",
        "pricing.payment_option",
        "pricing.shipping_quote",
    }
    for schema in ["scraping", "catalog", "pricing", "auth"]:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
    for name in [
        "20261004_03_extraction.sql",
        "20261004_04_discovery.sql",
        "20261004_06_catalog_pricing.sql",
    ]:
        source = (ROOT / "migrations/sql" / name).read_text(encoding="utf-8")
        for table, body in re.findall(
            r'CREATE TABLE\s+("[^"]+"\."[^"]+")\s*\((.*?)\);', source, re.S
        ):
            if table.replace('"', "") in tables:
                columns = body.split("CONSTRAINT")[0].strip().rstrip(",")
                await connection.execute(text(f"CREATE TABLE {table} ({columns})"))
    source = (ROOT / "migrations/sql/20261006_08_commercial_details.sql").read_text(
        encoding="utf-8"
    )
    for statement in source.split(";"):
        if "ALTER TABLE pricing." in statement:
            await connection.execute(text(statement[statement.index("ALTER TABLE") :]))
    for statement in [
        "ALTER TABLE scraping.job ADD COLUMN scrape_request_id bigint",
        "ALTER TABLE scraping.scrape_request ADD COLUMN routine_public_id uuid",
        "CREATE TABLE catalog.product(id bigint, brand text, model text, category text, identifiers jsonb)",
        "CREATE TABLE catalog.variant(id bigint, product_id bigint, attributes jsonb, identifiers jsonb)",
        "CREATE TABLE scraping.scheduled_routine(id bigint, public_id uuid)",
        "CREATE TABLE scraping.routine_search_term(routine_id bigint, search_term_id bigint)",
        "CREATE TABLE auth.mcp_key_term(key_id bigint, term_id bigint)",
        "CREATE TABLE auth.mcp_key_routine(key_id bigint, routine_id bigint)",
        "INSERT INTO auth.mcp_key_term VALUES (7,1)",
    ]:
        await connection.execute(text(statement))
    for i, site in [(1, "kabum_br"), (2, "kabum_br"), (3, "pichau_br")]:
        public = UUID(f"00000000-0000-4000-8000-{i:012}")
        await connection.execute(
            text("""INSERT INTO scraping.entity(id,site,source_key,kind)
            OVERRIDING SYSTEM VALUE VALUES(:id,:site,:key,'product')"""),
            {"id": i, "site": site, "key": str(i)},
        )
        await connection.execute(
            text("""INSERT INTO scraping.search_term(id,public_id,site,term,normalized_term,criteria)
            OVERRIDING SYSTEM VALUE VALUES(:id,:public,:site,:term,'gpu','{}')"""),
            {
                "id": i,
                "public": public,
                "site": site,
                "term": "GPU" if i == 1 else " gpu ",
            },
        )
        await connection.execute(
            text("INSERT INTO scraping.search_term_entity VALUES(:id,:id,now())"),
            {"id": i},
        )
        await connection.execute(
            text("""INSERT INTO catalog.listing(id,entity_id,variant_id,url,title)
            OVERRIDING SYSTEM VALUE VALUES(:id,:id,1,'https://example.test/product','GPU')"""),
            {"id": i},
        )
        await connection.execute(
            text("""INSERT INTO pricing.offer(id,listing_id,identity_key,seller)
            OVERRIDING SYSTEM VALUE VALUES(:id,:id,'seller','Test seller')"""),
            {"id": i},
        )
    await connection.execute(
        text("INSERT INTO scraping.search_term_entity VALUES(2,1,now())")
    )
    foreign_routine = UUID("00000000-0000-4000-8000-000000000020")
    # Three forbidden observations: a foreign routine for the shared entity, an
    # ungranted same-text configuration, and an ungranted marketplace.
    for i, (entity, amount, hour, routine, currency) in enumerate(
        [
            (1, "100", 0, None, "BRL"),
            (1, "9", 1, None, "BRL"),
            (1, "2", 2, None, "BRL"),
            (1, None, 3, None, "BRL"),
            (1, "0.5", 1.5, foreign_routine, "BRL"),
            (2, "1", 1.5, None, "BRL"),
            (3, "0.1", 1.5, None, "BRL"),
            (1, "0.2", 2, None, "USD"),
        ],
        1,
    ):
        values = {
            "id": i,
            "job_key": str(i),
            "entity": entity,
            "price": Decimal(amount) if amount else None,
            "at": START + timedelta(hours=hour),
            "observed": START - timedelta(days=2),
            "routine": routine,
            "currency": currency,
        }
        await connection.execute(
            text("""INSERT INTO scraping.scrape_request(id,correlation_id,mode,
            search_term_id,status,created_at,routine_public_id) OVERRIDING SYSTEM VALUE
            VALUES(:id,gen_random_uuid(),'discover',:entity,'completed',:at,:routine)"""),
            values,
        )
        await connection.execute(
            text("""INSERT INTO scraping.job(id,routine_id,parser_id,html_snapshot_id,
            correlation_id,idempotency_key,policy,scrape_request_id) OVERRIDING SYSTEM VALUE
            VALUES(:id,1,1,1,gen_random_uuid(),:job_key,'{}',:id)"""),
            values,
        )
        await connection.execute(
            text("""INSERT INTO scraping.observation(id,entity_id,job_id,payload,evidence,created_at)
            OVERRIDING SYSTEM VALUE VALUES(:id,:entity,:id,'{}','[]',:at)"""),
            values,
        )
        await connection.execute(
            text("""INSERT INTO pricing.observation(id,offer_id,source_observation_id,
            observed_at,price_vl,currency,availability) OVERRIDING SYSTEM VALUE
            VALUES(:id,:entity,:id,:observed,:price,:currency,'unknown')"""),
            values,
        )


async def test_real_price_windows_numeric_order_and_restricted_aggregates(
    isolated_price_postgres,
    monkeypatch,
):
    engine = create_async_engine(isolated_price_postgres)
    try:
        async with engine.begin() as connection:
            await seed(connection)
        async with AsyncSession(engine) as session:
            filters = price_filters(
                site=None,
                term_id=TERM,
                currency="BRL",
                collected_start_at=START,
                collected_end_at=START + timedelta(hours=3),
            )
            # End is exclusive: the null-price capture exactly at hour 3 is absent.
            unrestricted = await price_analytics.detail(
                session, filters, 100, 0, sort_by="price", sort_order="asc"
            )
            assert unrestricted["total"] == 6
            session.info["mcp_key"] = {"id": 7, "permissions": {"sites": ["kabum_br"]}}
            restricted = await price_analytics.detail(
                session, filters, 2, 0, sort_by="price", sort_order="asc"
            )
            assert restricted["total"] == 3
            assert [Decimal(row["price"]) for row in restricted["items"]] == [
                Decimal("2"),
                Decimal("9"),
            ]
            assert all(row["terms"] == "GPU" for row in restricted["items"])
            assert all(
                START <= row["collected_at"] < START + timedelta(hours=3)
                for row in restricted["items"]
            )
            tail = await price_analytics.detail(
                session, filters, 2, 2, sort_by="price", sort_order="asc"
            )
            assert tail["total"] == 3 and [
                Decimal(row["price"]) for row in tail["items"]
            ] == [Decimal("100")]
            # Observed timestamps are two days earlier: collection window must
            # not accidentally filter by observed_at.
            filters["end_at"] = START + timedelta(hours=4)
            for direction, expected in [
                ("asc", ["2", "9", "100", None]),
                ("desc", ["100", "9", "2", None]),
            ]:
                page = await price_analytics.detail(
                    session, filters, 100, 0, sort_by="price", sort_order=direction
                )
                assert [
                    Decimal(row["price"]) if row["price"] is not None else None
                    for row in page["items"]
                ] == [Decimal(x) if x else None for x in expected]
            chronological = await price_analytics.detail(
                session, filters, 1, 0, sort_by="collected_at", sort_order="desc"
            )
            assert chronological["items"][0]["collected_at"] == START + timedelta(
                hours=3
            )
            latest = await price_analytics.detail(session, filters, 100, 0, latest=True)
            assert latest["total"] == 1 and latest["items"][0]["price"] is None
            dashboard = await price_analytics.dashboard(session, filters)
            assert dashboard["totals"] == {
                "products": 1,
                "observations": 4,
                "offers": 1,
            }
            # USD's request is still an authorized execution, but its amount
            # never participates in BRL ranking/aggregates.
            assert dashboard["execution_totals"]["total"] == 5
            assert all(row["currency"] == "BRL" for row in dashboard["currencies"])
            session.info["mcp_key"]["permissions"]["sites"] = []
            assert (await price_analytics.detail(session, filters, 10, 0))["total"] == 0
            assert (await price_analytics.dashboard(session, filters))["totals"][
                "products"
            ] == 0

        # End-to-end real MCP protocol -> ASGI API -> PostgreSQL. Only JWT
        # verification is replaced; the real authorization policy and SQL run.
        key = {
            "id": 7,
            "admin": False,
            "permissions": MCPPermissions(
                view_extractions=True, sites=["kabum_br"]
            ).model_dump(),
        }
        app = create_app()
        app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def scoped_user(request: Request):
            user = {"name": "test", "mcp_key": key}
            async with AsyncSession(engine) as session:
                await mcp_policy.authorize(request, session, user)
            request.state.principal = user
            return user

        app.dependency_overrides[current_user] = scoped_user
        monkeypatch.setenv("PANOPTES_MCP_KEY", "pmcp_synthetic_test")
        monkeypatch.setenv("PANOPTES_API_URL", "http://localhost")

        def client():
            return PanoptesClient(transport=httpx.ASGITransport(app=app))

        async with create_connected_server_and_client_session(
            create_server(client)
        ) as mcp:
            arguments = {
                "term_id": str(TERM),
                "collected_start_at": START.isoformat(),
                "collected_end_at": (START + timedelta(hours=3)).isoformat(),
                "currency": "BRL",
                "sort_by": "price",
                "sort_order": "asc",
                "limit": 2,
            }
            response = await mcp.call_tool("price_details", arguments)
            assert not response.isError, response.content
            assert response.structuredContent["total"] == 3
            assert [
                Decimal(r["price"]) for r in response.structuredContent["items"]
            ] == [Decimal("2"), Decimal("9")]
            response = await mcp.call_tool(
                "price_dashboard",
                {
                    k: v
                    for k, v in arguments.items()
                    if k not in {"sort_by", "sort_order", "limit"}
                },
            )
            assert not response.isError, response.content
            assert response.structuredContent["totals"]["observations"] == 3
            assert (await mcp.call_tool("price_details", {})).isError
    finally:
        await engine.dispose()
