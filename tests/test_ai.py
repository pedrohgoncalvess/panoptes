import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
import yaml
from jsonschema.exceptions import ValidationError
from panoptes_ai import audit, client, registry
from panoptes_backend.catalog.product_search import ProductSearch
from panoptes_database.config import DatabaseSettings
from panoptes_database.session import create_database
from sqlalchemy import text


def agent(*, embeddings=False, schema=None):
    return dict(
        id=1,
        slug="test",
        model_id=2,
        model="test/model",
        prompt="Only extract evidenced facts.",
        structured_output_schema=schema,
        metadata={
            "version": "1",
            "endpoint": "embeddings" if embeddings else "chat/completions",
            "settings": {"dimensions": 2} if embeddings else {},
        },
        price_snapshot={},
    )


def fake_work(session):
    @asynccontextmanager
    async def work(_sessions):
        yield session

    return work


@pytest.mark.parametrize(
    "variant", ["success", "http_error", "schema_error", "cancelled"]
)
async def test_gateway_records_each_attempt_and_failure(monkeypatch, variant):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-key")
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
    }
    config = agent(schema=schema)
    events = []

    def handle(request):
        events.append("http")
        assert events[0] == "pending"
        body = json.loads(request.content)
        assert "secret-key" not in str(body)
        assert body["model"] == "test/model"
        assert body["messages"][0]["content"] == config["prompt"]
        if variant == "cancelled":
            raise asyncio.CancelledError
        return httpx.Response(
            400 if variant == "http_error" else 200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"ok": variant != "schema_error"})
                            if variant != "schema_error"
                            else "{}"
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "cost": 0.0001},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        gateway = client.OpenRouter(None, http)
        gateway.agent = AsyncMock(return_value=config)

        async def begin(*args):
            events.append("pending")
            return (1, uuid4())

        gateway._begin = AsyncMock(side_effect=begin)
        gateway._finish = AsyncMock()
        if variant == "success":
            await gateway.invoke(
                "test", "untrusted HTML", context={"html_snapshot_id": 7}
            )
        else:
            with pytest.raises(
                {
                    "http_error": httpx.HTTPStatusError,
                    "schema_error": ValidationError,
                    "cancelled": asyncio.CancelledError,
                }[variant]
            ):
                await gateway.invoke("test", "untrusted HTML")
        finish = gateway._finish.await_args.args
        assert finish[4] == {"success": "completed", "cancelled": "cancelled"}.get(
            variant, "failed"
        )
        assert finish[3] is not None if variant != "cancelled" else finish[3] is None
        gateway._begin.assert_awaited_once()
        gateway._finish.assert_awaited_once()


@pytest.mark.parametrize("status", [429, 502, 503, 504])
async def test_gateway_retries_transient_http_errors_with_separate_audits(
    monkeypatch, status
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    sleep = AsyncMock()
    monkeypatch.setattr(client.asyncio, "sleep", sleep)
    responses = [status, status, 200]

    def handle(request):
        return httpx.Response(
            responses.pop(0),
            headers={"Retry-After": "5"},
            json={"choices": [{"message": {"content": "{}"}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        gateway = client.OpenRouter(None, http)
        gateway._begin = AsyncMock(return_value=(1, uuid4()))
        gateway._finish = AsyncMock()
        context = {"scrape_request_id": 7}
        await gateway.invoke("test", "evidence", agent=agent(), context=context)
    assert context == {"scrape_request_id": 7}
    assert [c.args[2]["attempt_qt"] for c in gateway._begin.await_args_list] == [
        1,
        2,
        3,
    ]
    assert [c.args[4] for c in gateway._finish.await_args_list] == [
        "failed",
        "failed",
        "completed",
    ]
    assert [c.args[0] for c in sleep.await_args_list] == (
        [10, 30] if status == 429 else [5, 5]
    )


async def test_gateway_stops_after_three_rate_limited_attempts(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    sleep = AsyncMock()
    monkeypatch.setattr(client.asyncio, "sleep", sleep)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, json={"error": {"code": 429}})
        )
    ) as http:
        gateway = client.OpenRouter(None, http)
        gateway._begin = AsyncMock(return_value=(1, uuid4()))
        gateway._finish = AsyncMock()
        with pytest.raises(httpx.HTTPStatusError):
            await gateway.invoke("test", "evidence", agent=agent())
    assert gateway._finish.await_count == 3
    assert [c.args[0] for c in sleep.await_args_list] == [10, 30]


async def test_gemini_grammar_is_simple_but_local_validation_remains_strict(
    monkeypatch,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"title": {"type": "string", "maxLength": 5}},
        "required": ["title"],
    }
    config = agent(schema=schema)
    config["model"] = "google/gemini-test"

    def handle(request):
        sent = json.loads(request.content)["response_format"]["json_schema"]["schema"]
        assert sent["properties"]["title"] == {"type": "string"}
        assert sent["additionalProperties"] is False
        assert sent["required"] == ["title"]
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"title":"too long"}'}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        gateway = client.OpenRouter(None, http)
        gateway._begin = AsyncMock(return_value=(1, uuid4()))
        gateway._finish = AsyncMock()
        with pytest.raises(ValidationError):
            await gateway.invoke("test", "evidence", agent=config)
    assert schema["properties"]["title"]["maxLength"] == 5
    assert gateway._finish.await_args.args[4] == "failed"


@pytest.mark.parametrize("slug", ["commerce", "taxonomy_normalizer"])
def test_complex_schemas_retain_shape_and_refs_without_decoding_bounds(slug):
    config = next(a for a in registry.load_agents() if a["slug"] == slug)
    simplified = client.provider_schema(config["schema"])
    assert simplified["required"] == config["schema"]["required"]
    assert simplified["additionalProperties"] is False
    assert "$defs" in simplified
    for keyword in ('"maxLength"', '"maxItems"', '"minimum"', '"format"'):
        assert keyword not in json.dumps(simplified)
    assert '"$ref"' in json.dumps(simplified)


async def test_finalize_persists_tokens_and_outbox_together(monkeypatch):
    session = Mock(execute=AsyncMock())
    monkeypatch.setattr(client, "unit_of_work", fake_work(session))
    gateway = client.OpenRouter(None, None)
    payload = {
        "id": "generation-1",
        "model": "test/model",
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 4,
            "total_tokens": 19,
            "cost": "0.00000012",
        },
    }
    await gateway._finish(
        (1, uuid4()),
        agent(),
        {"input": "HTML"},
        payload,
        "completed",
        None,
        0.1,
        {"html_snapshot_id": 7},
    )
    update, enqueue = session.execute.await_args_list
    assert update.args[1]["prompt_tokens"] == 15
    assert update.args[1]["completion_tokens"] == 4
    assert update.args[1]["cost"] == Decimal("0.00000012")
    document = json.loads(enqueue.args[1]["payload"])
    assert document["request"]["input"] == "HTML"
    assert document["response"] == payload
    assert "ai.audit_outbox" in str(enqueue.args[0])


@pytest.mark.parametrize("fails", [False, True])
async def test_durable_audit_upload_and_retry(monkeypatch, fails):
    public_id = uuid4()
    rows = [
        dict(
            interaction_id=1,
            public_id=public_id,
            payload={"request": "HTML", "response": "facts"},
            attempts=0,
        )
    ]
    result = Mock()
    result.mappings.return_value.all.return_value = rows
    session = Mock(execute=AsyncMock(return_value=result))
    monkeypatch.setattr(audit, "unit_of_work", fake_work(session))
    storage = Mock(put_object=AsyncMock(side_effect=OSError if fails else None))
    assert await audit.flush_audits(None, storage, "bucket") == 1
    upload = storage.put_object.await_args.kwargs
    assert upload["Key"] == f"ai/interactions/{public_id}.json"
    assert json.loads(upload["Body"])["request"] == "HTML"
    sql = [str(call.args[0]) for call in session.execute.await_args_list]
    if fails:
        assert any("attempts=attempts+1" in statement for statement in sql)
        assert not any("DELETE" in statement for statement in sql)
    else:
        assert any("audit_uploaded_at=now()" in statement for statement in sql)
        assert any("DELETE" in statement for statement in sql)


async def test_catalog_preserves_modalities_and_decimal_prices(monkeypatch):
    result = Mock()
    result.mappings.return_value.all.return_value = [
        {"id": 2, "provider_id": "test/model"}
    ]
    session = Mock(execute=AsyncMock(return_value=result))
    monkeypatch.setattr(registry, "unit_of_work", fake_work(session))
    pricing = {"prompt": "0.0000000000000001", "audio": "0.0003"}

    def handle(request):
        assert request.url.params["output_modalities"] == "all"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "test/model",
                        "expiration_date": "2027-01-01",
                        "pricing": pricing,
                        "architecture": {
                            "input_modalities": ["text", "image", "audio"],
                            "output_modalities": ["embeddings"],
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        await registry.sync_models(None, http)
    calls = session.execute.await_args_list
    model = next(c.args[1] for c in calls if "UPDATE ai.model SET" in str(c.args[0]))
    price = next(
        c.args[1] for c in calls if "INSERT INTO ai.model_price" in str(c.args[0])
    )
    assert model["inputs"] == ["text", "image", "audio"]
    assert model["outputs"] == ["embeddings"]
    assert model["expiration"] == date(2027, 1, 1)
    assert price["prompt"] == Decimal("0.0000000000000001")
    assert json.loads(price["pricing"]) == pricing


def test_registry_optional_schema_and_path_validation(tmp_path):
    (tmp_path / "prompt.md").write_text("Return a helpful answer.")
    entry = {
        "name": "Test",
        "description": "Test",
        "model": "test/model",
        "prompt": "prompt.md",
    }
    path = tmp_path / "metadata.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "agents": {"test": entry}}))
    assert registry.load_agents(path)[0]["schema"] is None
    entry["prompt"] = "../outside.md"
    path.write_text(yaml.safe_dump({"version": 1, "agents": {"test": entry}}))
    with pytest.raises(ValueError, match="escapes"):
        registry.load_agents(path)


async def test_embeddings_reorder_validate_and_aggregate(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-key")
    config = agent(embeddings=True)

    def handle(request):
        body = json.loads(request.content)
        assert request.url.path.endswith("/embeddings")
        assert "messages" not in body and body["dimensions"] == 2
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [3.0, 4.0]}
                    for index in reversed(range(len(body["input"])))
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        gateway = client.OpenRouter(None, http)
        gateway.agent = AsyncMock(return_value=config)
        gateway._begin = AsyncMock(return_value=(1, uuid4()))
        gateway._finish = AsyncMock()
        search = ProductSearch(None, gateway)
        await search.configure()
        vector = (await search.encode(["a" * 4000]))[0]
        assert vector == pytest.approx([0.6, 0.8])
        assert "test/model:2:1" in search.version
        gateway._finish.assert_awaited_once()


async def test_registry_upsert_keeps_model_prompt_and_optional_schema(monkeypatch):
    result = Mock()
    result.scalar_one.return_value = 7
    session = Mock(execute=AsyncMock(return_value=result))
    monkeypatch.setattr(registry, "unit_of_work", fake_work(session))
    entries = registry.load_agents(
        Path(__file__).resolve().parents[1] / "agents/metadata.yaml"
    )
    assert await registry.sync_agents(None, entries) == 8
    upserts = [
        call
        for call in session.execute.await_args_list
        if "INSERT INTO ai.agent" in str(call.args[0])
    ]
    assert len(upserts) == 8
    embeddings = next(
        call.args[1] for call in upserts if call.args[1]["slug"] == "product_embedding"
    )
    assert embeddings["schema"] is None and embeddings["prompt"]


@pytest.mark.integration
async def test_database_registry_price_history_and_interaction_outbox(monkeypatch):
    url = os.getenv("TEST_WORKFLOW_DATABASE_URL")
    if not url:
        pytest.skip("Requires disposable migrated PostgreSQL")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    engine, sessions = create_database(DatabaseSettings(url, 1, 2))
    slug = "test-" + uuid4().hex
    model = "test/" + uuid4().hex
    entry = dict(
        slug=slug,
        name="Test",
        description="Test agent",
        model=model,
        prompt="Extract facts.",
        schema=None,
        metadata={"version": "1", "endpoint": "chat/completions", "settings": {}},
    )
    current_price = "0.0000001"

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": model,
                            "architecture": {
                                "input_modalities": ["text"],
                                "output_modalities": ["text"],
                            },
                            "expiration_date": "2027-01-01",
                            "pricing": {"prompt": current_price},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "gen-" + uuid4().hex,
                "model": model,
                "choices": [{"message": {"content": "Facts"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "cost": 0.000001,
                },
            },
        )

    try:
        await registry.sync_agents(sessions, [entry])
        entry["prompt"] = "Updated prompt."
        await registry.sync_agents(sessions, [entry])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            await registry.sync_models(sessions, http)
            await registry.sync_models(sessions, http)
            current_price = "0.0000002"
            await registry.sync_models(sessions, http)
            gateway = client.OpenRouter(sessions, http)
            assert (await gateway.agent(slug))["prompt"] == "Updated prompt."
            await gateway.invoke(slug, "HTML")
        async with sessions() as session:
            prices = (
                (
                    await session.execute(
                        text("""
                SELECT p.* FROM ai.model_price p JOIN ai.model m ON m.id=p.model_id
                WHERE m.provider_id=:model ORDER BY p.id
            """),
                        {"model": model},
                    )
                )
                .mappings()
                .all()
            )
            assert len(prices) == 2
            assert prices[0]["deleted_at"] is not None
            assert prices[1]["deleted_at"] is None
            assert prices[1]["prompt"] == Decimal(current_price)
            row = (
                (
                    await session.execute(
                        text("""
                SELECT i.*,o.payload FROM ai.interaction i JOIN ai.agent a ON a.id=i.agent_id
                JOIN ai.audit_outbox o ON o.interaction_id=i.id WHERE a.slug=:slug
            """),
                        {"slug": slug},
                    )
                )
                .mappings()
                .one()
            )
            assert row["status"] == "completed" and row["prompt_tokens"] == 10
            assert row["completion_tokens"] == 2 and row["cost_status"] == "reported"
            assert row["payload"]["request"]["messages"][1]["content"] == "HTML"
            assert (
                row["payload"]["response"]["choices"][0]["message"]["content"]
                == "Facts"
            )
    finally:
        async with sessions.begin() as session:
            await session.execute(
                text("""DELETE FROM ai.audit_outbox WHERE interaction_id IN
                (SELECT i.id FROM ai.interaction i JOIN ai.agent a ON a.id=i.agent_id WHERE a.slug=:slug)"""),
                {"slug": slug},
            )
            await session.execute(
                text(
                    "DELETE FROM ai.interaction WHERE agent_id IN (SELECT id FROM ai.agent WHERE slug=:slug)"
                ),
                {"slug": slug},
            )
            await session.execute(
                text("DELETE FROM ai.agent WHERE slug=:slug"), {"slug": slug}
            )
            await session.execute(
                text(
                    "DELETE FROM ai.model_price WHERE model_id IN (SELECT id FROM ai.model WHERE provider_id=:model)"
                ),
                {"model": model},
            )
            await session.execute(
                text("DELETE FROM ai.model WHERE provider_id=:model"), {"model": model}
            )
        await engine.dispose()
