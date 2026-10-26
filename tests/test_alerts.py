import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from panoptes_backend.alerts import delivery, router
from panoptes_backend.auth.router import current_user
from panoptes_backend.catalog.router import session_dependency
from panoptes_backend.main import create_app
from panoptes_contracts.alerts import AlertRule, WebhookConfig
from panoptes_database.alerts import enqueue, rule_matches
from panoptes_mcp.server import create_server
from panoptes_workers.workflow import runner
from panoptes_workers.workflow.service import WorkflowResources
from pydantic import ValidationError


def rule(event="price_threshold", **kwargs):
    return {"event": event, "routine_ids": [], "currency": "BRL", **kwargs}


@pytest.mark.parametrize(
    "event,previous,price,options,expected",
    [
        ("price_threshold", None, "100", {"threshold": "100"}, True),
        ("price_threshold", "110", "100", {"threshold": "100"}, True),
        ("price_threshold", "100", "90", {"threshold": "100"}, False),
        (
            "price_threshold",
            "90",
            "100",
            {"threshold": "100", "direction": "above"},
            True,
        ),
        (
            "price_threshold",
            "100",
            "110",
            {"threshold": "100", "direction": "above"},
            False,
        ),
        ("price_drop", "100", "90", {"percent": "10"}, True),
        ("price_drop", "100", "90.01", {"percent": "10"}, False),
        ("price_increase", "100", "110", {"percent": "10"}, True),
        ("price_increase", "100", "90", {"percent": "10"}, False),
        ("price_drop", None, "90", {"percent": "10"}, False),
        ("price_increase", "0", "90", {"percent": "10"}, False),
    ],
)
def test_price_rules(event, previous, price, options, expected):
    assert (
        rule_matches(
            rule(event, **options),
            event,
            None,
            {"price": price, "previous_price": previous, "currency": "BRL"},
        )
        is expected
    )


def test_rule_scope_never_matches_other_routines_entities_or_currencies():
    routine, entity = str(uuid4()), str(uuid4())
    config = rule(threshold="100", routine_ids=[routine], entity_id=entity)
    data = {"entity_id": entity, "price": "50", "currency": "BRL"}
    assert rule_matches(config, "price_threshold", routine, data)
    assert not rule_matches(config, "price_threshold", None, data)
    assert not rule_matches(config, "price_threshold", uuid4(), data)
    assert not rule_matches(config, "price_drop", routine, data)
    assert not rule_matches(
        config, "price_threshold", routine, {**data, "currency": "USD"}
    )
    assert not rule_matches(
        config, "price_threshold", routine, {**data, "entity_id": str(uuid4())}
    )
    assert rule_matches(rule("extraction_started"), "extraction_started", None, {})


@pytest.mark.parametrize(
    "value",
    [
        {"event": "price_threshold"},
        {"event": "price_drop", "percent": 0},
        {"event": "extraction_started", "threshold": 5},
        {"event": "extraction_started", "entity_id": str(uuid4())},
        {"event": "price_drop", "percent": "NaN"},
        {"event": "unknown"},
        {"event": "price_threshold", "threshold": -1},
    ],
)
def test_rule_validation(value):
    with pytest.raises(ValidationError):
        AlertRule.model_validate(value)


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/test",
        "https://user:pass@example.com",
        "https://example.com/#secret",
    ],
)
def test_webhook_url_validation(url):
    with pytest.raises(ValidationError):
        WebhookConfig(
            name="Receiver", url=url, rules=[AlertRule(event="extraction_started")]
        )


def result(rows):
    value = MagicMock()
    value.mappings.return_value.all.return_value = rows
    value.mappings.return_value.one_or_none.return_value = rows[0] if rows else None
    value.mappings.return_value.one.return_value = rows[0] if rows else None
    return value


async def test_outbox_one_delivery_per_destination_even_for_multiple_matching_rules():
    session = AsyncMock()
    session.execute.side_effect = [
        result(
            [
                {
                    "id": 1,
                    "url": "https://example.com/a",
                    "rules": [rule("extraction_started"), rule("extraction_started")],
                },
                {
                    "id": 2,
                    "url": "https://example.com/b",
                    "rules": [rule("extraction_error")],
                },
            ]
        ),
        MagicMock(),
    ]
    await enqueue(
        session, "extraction_started", "request-1", None, {"status": "running"}
    )
    assert session.execute.await_count == 2
    args = session.execute.await_args.args
    assert "ON CONFLICT" in str(args[0])
    payload = json.loads(args[1]["payload"])
    assert payload["id"] == str(args[1]["pid"])
    assert payload["routine_id"] is None
    assert len(payload["matched_rules"]) == 2


async def test_alert_api_requires_authentication():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        assert (await client.get("/alerts/webhooks")).status_code == 401


async def test_alert_api_create_read_update_pause_deliveries_delete(monkeypatch):
    pid = uuid4()
    now = datetime.now(UTC)
    value = {
        "name": "Receiver",
        "url": "https://example.com/",
        "enabled": True,
        "rules": [AlertRule(event="extraction_started").model_dump(mode="json")],
    }
    stored = {**value, "public_id": pid, "created_at": now, "updated_at": now}
    session = AsyncMock()
    session.execute.return_value = result([stored])
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"name": "test"}
    app.dependency_overrides[session_dependency] = lambda: session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alerts/webhooks", json=value)
        assert response.status_code == 201 and response.json()["public_id"] == str(pid)
        assert "id" not in response.json()
        assert (await client.get(f"/alerts/webhooks/{pid}")).status_code == 200
        assert (await client.get("/alerts/webhooks?limit=101")).status_code == 422
        assert (
            await client.put(
                f"/alerts/webhooks/{pid}", json={**value, "enabled": False}
            )
        ).status_code == 200
        assert any(
            "status='cancelled'" in str(call.args[0])
            for call in session.execute.await_args_list
        )
        session.execute.return_value = result([])
        assert (await client.get(f"/alerts/webhooks/{pid}")).status_code == 404
        session.execute.return_value = result([stored])
        assert (await client.delete(f"/alerts/webhooks/{pid}")).status_code == 204


async def test_unknown_routine_rejected():
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = []
    value = WebhookConfig(
        name="Receiver",
        url="https://example.com",
        rules=[AlertRule(event="extraction_started", routine_ids=[uuid4()])],
    )
    with pytest.raises(Exception) as error:
        await router.validate_references(session, value)
    assert error.value.status_code == 422


async def test_mcp_webhooks_publish_schemas_and_forward_configuration():
    api = AsyncMock()
    pid, routine = uuid4(), uuid4()
    value = {
        "name": "Receiver",
        "url": "https://example.com/",
        "enabled": True,
        "rules": [
            AlertRule(
                event="price_drop", percent="10", routine_ids=[routine]
            ).model_dump(mode="json")
        ],
    }
    api.request.return_value = {
        **value,
        "public_id": str(pid),
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    async with create_connected_server_and_client_session(
        create_server(lambda: api)
    ) as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert tools["delete_webhook"].annotations.destructiveHint
        assert tools["list_webhooks"].annotations.readOnlyHint
        response = await session.call_tool("create_webhook", {"value": value})
        assert not response.isError
        api.request.assert_awaited_with("POST", "/alerts/webhooks", body=value)
        response = await session.call_tool(
            "update_webhook",
            {"webhook_id": str(pid), "value": {**value, "enabled": False}},
        )
        assert not response.isError
        api.request.assert_awaited_with(
            "PUT", f"/alerts/webhooks/{pid}", body={**value, "enabled": False}
        )
        guide = await session.call_tool(
            "get_usage_guide", {"tool_name": "create_webhook"}
        )
        assert "price_threshold" in guide.structuredContent["result"]


async def test_send_pins_destination_and_preserves_delivery_id(monkeypatch):
    monkeypatch.setattr(
        delivery,
        "resolve_destination",
        AsyncMock(
            return_value=(
                httpx.URL("https://93.184.216.34/hook"),
                "example.com",
                "example.com",
            )
        ),
    )
    pid = uuid4()
    requests = []

    def receive(request):
        requests.append(request)
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
        row = {
            "destination_url": "https://example.com/hook",
            "payload": {"id": str(pid)},
            "public_id": pid,
            "event": "extraction_started",
        }
        assert await delivery.send(client, row) == 204
        assert await delivery.send(client, row) == 204
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "example.com"
    assert requests[0].extensions["sni_hostname"] == "example.com"
    assert (
        requests[0].headers["X-Panoptes-Delivery"]
        == requests[1].headers["X-Panoptes-Delivery"]
    )


async def test_private_destinations_blocked_and_opt_in_allowed(monkeypatch):
    monkeypatch.delenv("WEBHOOK_ALLOW_PRIVATE_NETWORKS", raising=False)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop, "getaddrinfo", AsyncMock(return_value=[(2, 1, 6, "", ("127.0.0.1", 80))])
    )
    with pytest.raises(ValueError):
        await delivery.resolve_destination("http://localhost/events")
    monkeypatch.setenv("WEBHOOK_ALLOW_PRIVATE_NETWORKS", "true")
    pinned, host, _ = await delivery.resolve_destination("http://localhost/events")
    assert pinned.host == "127.0.0.1" and host == "localhost"


@pytest.mark.parametrize(
    "attempts,http,status",
    [
        (0, 204, "delivered"),
        (0, 500, "pending"),
        (4, 500, "failed"),
        (0, 302, "pending"),
    ],
)
async def test_dispatch_records_success_retries_and_exhaustion(
    monkeypatch, attempts, http, status
):
    session = AsyncMock()
    session.execute.return_value = result([{"id": 1, "attempts": attempts}])

    @asynccontextmanager
    async def transaction(_):
        yield session

    monkeypatch.setattr(delivery, "unit_of_work", transaction)
    monkeypatch.setattr(delivery, "send", AsyncMock(return_value=http))
    assert await delivery.deliver_one(object(), object())
    params = session.execute.await_args.args[1]
    assert params["status"] == status
    assert params["attempts"] == attempts + 1
    assert (params["delivered"] is not None) == (status == "delivered")


@pytest.mark.parametrize("lease_lost", [False, True])
async def test_worker_failure_enqueues_terminal_events_only_after_saving_result(
    monkeypatch, lease_lost
):
    marker = object()

    @asynccontextmanager
    async def transaction(_):
        yield marker

    monkeypatch.setattr(runner, "unit_of_work", transaction)
    monkeypatch.setattr(runner, "emit", AsyncMock())
    monkeypatch.setattr(
        runner.queue_repository,
        "read_context",
        AsyncMock(side_effect=ValueError("missing_context")),
    )
    finish = AsyncMock(
        side_effect=runner.queue_repository.LeaseLostError() if lease_lost else None
    )
    monkeypatch.setattr(runner.queue_repository, "finish", finish)
    events = AsyncMock()
    monkeypatch.setattr(runner, "extraction_event", events)
    request = {
        "id": 1,
        "public_id": uuid4(),
        "correlation_id": uuid4(),
        "mode": "discover",
        "routine_public_id": uuid4(),
    }
    resources = WorkflowResources(None, None, "test", None, asyncio.Lock(), 0)
    await runner.process(resources, request, uuid4())
    assert finish.await_args.args[3] == "failed"
    if lease_lost:
        events.assert_not_awaited()
    else:
        assert [c.args[2] for c in events.await_args_list] == [
            "extraction_finished",
            "extraction_error",
        ]
        assert all(c.args[:2] == (marker, request) for c in events.await_args_list)


async def test_worker_start_event_uses_claimed_request_and_transaction(monkeypatch):
    marker = object()

    @asynccontextmanager
    async def transaction(_):
        yield marker

    request = {
        "id": 1,
        "public_id": uuid4(),
        "mode": "discover",
        "routine_public_id": uuid4(),
    }
    monkeypatch.setattr(runner, "unit_of_work", transaction)
    monkeypatch.setattr(runner.queue_repository, "enqueue_due", AsyncMock())
    monkeypatch.setattr(
        runner.queue_repository, "claim", AsyncMock(return_value=request)
    )
    monkeypatch.setattr(runner, "process", AsyncMock())
    events = AsyncMock()
    monkeypatch.setattr(runner, "extraction_event", events)
    resources = WorkflowResources(None, None, "test", None, asyncio.Lock(), 0)
    await runner.run(resources, asyncio.Event(), once=True)
    events.assert_awaited_once_with(
        marker, request, "extraction_started", status="running"
    )
