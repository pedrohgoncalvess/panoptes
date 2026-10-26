"""Agent-facing regressions: scope, recovery and bounded price queries."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.memory import create_connected_server_and_client_session
from panoptes_backend.auth import mcp_policy
from panoptes_backend.auth.mcp_models import MCPPermissions
from panoptes_backend.auth.router import current_user
from panoptes_backend.catalog.router import session_dependency
from panoptes_backend.main import create_app
from panoptes_backend.management import price_analytics
from panoptes_backend.management.router import price_filters
from panoptes_backend.routines.models import RoutineUpdate as APIUpdate
from panoptes_mcp.client import PanoptesClient
from panoptes_mcp.instructions import GUIDE
from panoptes_mcp.models import RoutineUpdate
from panoptes_mcp.server import create_server
from pydantic import ValidationError
from starlette.requests import Request


async def test_protocol_rejects_unknown_filters_and_missing_enabled_before_api():
    api = AsyncMock()
    async with create_connected_server_and_client_session(
        create_server(lambda: api)
    ) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        assert all(
            t.inputSchema["additionalProperties"] is False for t in tools.values()
        )
        assert tools["update_webhook"].annotations.destructiveHint
        for args in [
            {"mode": "recent", "site_id": "kabum_br"},
            {"mode": "recent", "start_date": "2026-10-01"},
        ]:
            assert (await session.call_tool("search_products", args)).isError
        assert (
            await session.call_tool(
                "update_routine",
                {
                    "routine_id": str(uuid4()),
                    "value": {
                        "name": "Paused",
                        "schedule": {"kind": "interval", "interval_minutes": 60},
                    },
                },
            )
        ).isError
        api.request.assert_not_awaited()


@pytest.mark.parametrize("model", [RoutineUpdate, APIUpdate])
def test_routine_update_requires_explicit_activation_state(model):
    value = {"name": "Paused", "schedule": {"kind": "interval", "interval_minutes": 60}}
    with pytest.raises(ValidationError):
        model.model_validate(value)
    assert model.model_validate({**value, "enabled": False}).enabled is False


async def test_tool_guide_is_selective_and_full_guide_remains_available():
    async with create_connected_server_and_client_session(
        create_server(AsyncMock)
    ) as session:
        compact = await session.call_tool(
            "get_usage_guide", {"tool_name": "search_products"}
        )
        full = await session.call_tool(
            "get_usage_guide", {"tool_name": "search_products", "include_guide": True}
        )
        assert GUIDE not in compact.structuredContent["result"]
        assert GUIDE in full.structuredContent["result"]
        assert len(compact.structuredContent["result"]) < len(
            full.structuredContent["result"]
        )


@pytest.mark.parametrize(
    "status,method,retryable,unknown",
    [
        (429, "GET", True, False),
        (503, "GET", True, False),
        (503, "POST", False, True),
        (422, "POST", False, False),
    ],
)
async def test_safe_http_errors_include_recovery_metadata(
    monkeypatch, status, method, retryable, unknown
):
    monkeypatch.setenv("PANOPTES_MCP_KEY", "pmcp_test")
    correlation = str(uuid4())
    client = PanoptesClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                status,
                json={
                    "detail": "password=secret SQL injection",
                    "fields": ["sites", "<unsafe>"],
                },
                headers={"Retry-After": "30", "X-Correlation-ID": correlation},
            )
        )
    )
    try:
        with pytest.raises(ToolError) as caught:
            await client.request(method, "/test")
        error = json.loads(str(caught.value))
        assert error["retryable"] is retryable
        assert error["outcome_unknown"] is unknown
        assert error["retry_after_seconds"] == 30
        assert error["correlation_id"] == correlation
        assert "secret" not in str(caught.value) and "SQL" not in str(caught.value)
        if status == 422:
            assert error["invalid_fields"] == ["sites"]
    finally:
        await client.close()


def test_collection_window_uses_exact_instants_and_requires_exclusive_date_mode():
    since = datetime(2026, 10, 26, 8, tzinfo=UTC)
    until = since + timedelta(hours=4)
    filters = price_filters(site=None, collected_start_at=since, collected_end_at=until)
    assert filters["start_at"] == since and filters["end_at"] == until
    assert filters["time_basis"] == "collected_at"
    assert price_filters(site=None, collected_end_at=until)[
        "start_at"
    ] == until - timedelta(days=30)
    for args in [
        {"collected_start_at": until, "collected_end_at": since},
        {"collected_start_at": since, "collected_end_at": since},
        {"collected_start_at": since, "collected_end_at": since + timedelta(days=367)},
        {"start": since.date(), "collected_start_at": since},
    ]:
        with pytest.raises(HTTPException):
            price_filters(site=None, **args)


async def test_price_window_sort_and_page_are_forwarded_through_protocol():
    api = AsyncMock()
    api.request.return_value = {"items": [], "total": 50, "limit": 10, "offset": 20}
    async with create_connected_server_and_client_session(
        create_server(lambda: api)
    ) as session:
        result = await session.call_tool(
            "price_details",
            {
                "collected_start_at": "2026-10-26T08:00:00-03:00",
                "collected_end_at": "2026-10-26T12:00:00-03:00",
                "sort_by": "price",
                "sort_order": "asc",
                "currency": "BRL",
                "limit": 10,
                "offset": 20,
                "latest": True,
            },
        )
        assert not result.isError
        params = api.request.await_args.kwargs["params"]
        assert params["sort_by"] == "price" and params["sort_order"] == "asc"
        assert (
            params["currency"] == "BRL"
            and params["limit"] == 10
            and params["offset"] == 20
        )
        assert params["collected_start_at"].utcoffset().total_seconds() == -10800
        api.request.reset_mock()
        assert (await session.call_tool("price_details", {"sort_by": "price"})).isError
        api.request.assert_not_awaited()


@pytest.mark.parametrize("path", ["/analytics/prices/dashboard", "/analytics/detail"])
async def test_restricted_price_reports_require_authorized_term(path):
    key = {
        "id": 7,
        "admin": False,
        "permissions": MCPPermissions(
            view_extractions=True, sites=["kabum_br"]
        ).model_dump(),
    }
    found = MagicMock()
    found.first.return_value = (1,)
    session = SimpleNamespace(execute=AsyncMock(return_value=found))
    request = Request(
        {
            "type": "http",
            "path": path,
            "method": "GET",
            "headers": [],
            "query_string": f"term_id={uuid4()}".encode(),
        }
    )
    await mcp_policy.authorize(request, session, {"mcp_key": key})
    found.first.return_value = None
    with pytest.raises(HTTPException) as caught:
        await mcp_policy.authorize(request, session, {"mcp_key": key})
    assert caught.value.status_code == 403


async def test_scoped_price_sql_filters_captures_and_executions_before_aggregation():
    response = MagicMock()
    response.scalar_one.return_value = {}
    key = {"id": 7, "permissions": {"sites": ["kabum_br"]}}
    session = SimpleNamespace(
        info={"mcp_key": key}, execute=AsyncMock(return_value=response)
    )
    await price_analytics.dashboard(session, {})
    sql, bindings = session.execute.await_args.args
    sql = str(sql)
    assert "mj.id=source.job_id" in sql
    assert "kr.key_id=:mcp_key AND mr.public_id=r.routine_public_id" in sql
    assert sql.index("mj.id=source.job_id") < sql.index("SELECT jsonb_build_object")
    assert bindings["mcp_key"] == 7 and bindings["mcp_sites"] == ["kabum_br"]
    assert "WHERE link.entity_id=e.id AND" in sql  # term names are scoped too


@pytest.mark.parametrize(
    "sort_by,sort_order", [("price", "asc"), ("price", "desc"), ("collected_at", "asc")]
)
async def test_price_sql_orders_numeric_values_and_limits_after_selection(
    sort_by, sort_order
):
    response = MagicMock()
    response.scalar_one.return_value = 0
    response.mappings.return_value.all.return_value = []
    session = SimpleNamespace(info={}, execute=AsyncMock(return_value=response))
    await price_analytics.detail(
        session,
        {"time_basis": "collected_at", "currency": "BRL"},
        10,
        20,
        latest=True,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    count, page = [str(c.args[0]) for c in session.execute.await_args_list]
    assert "source.created_at>=:start_at" in count
    assert "o.currency=:currency" in count
    column = "o.price_vl" if sort_by == "price" else "o.captured_at"
    ordering = f"ORDER BY {column} {sort_order.upper()} NULLS LAST"
    assert (
        page.index("capture_rank=1")
        < page.index(ordering)
        < page.index("LIMIT :limit OFFSET :offset")
    )


async def test_api_rejects_ambiguous_windows_unsafe_sorts_and_unbounded_pages(
    monkeypatch,
):
    detail = AsyncMock(return_value={"items": [], "total": 0, "limit": 10, "offset": 0})
    monkeypatch.setattr(price_analytics, "detail", detail)
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"name": "test"}

    async def session():
        yield object()

    app.dependency_overrides[session_dependency] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        valid = {
            "collected_start_at": "2026-10-26T08:00:00-03:00",
            "collected_end_at": "2026-10-26T12:00:00-03:00",
            "limit": 10,
            "sort_by": "price",
            "sort_order": "asc",
            "currency": "BRL",
        }
        assert (await client.get("/analytics/detail", params=valid)).status_code == 200
        assert detail.await_args.kwargs == {"sort_by": "price", "sort_order": "asc"}
        assert detail.await_args.args[1]["time_basis"] == "collected_at"
        for invalid in [
            {"sort_by": "price"},
            {"sort_by": "price;DROP TABLE"},
            {"sort_order": "wrong"},
            {"limit": 0},
            {"limit": 101},
            {"collected_start_at": "2026-10-26T08:00:00"},
            {"start": "2026-10-26", "collected_start_at": valid["collected_start_at"]},
        ]:
            assert (
                await client.get("/analytics/detail", params=invalid)
            ).status_code == 422
