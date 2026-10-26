"""All platform inference goes through this audited OpenRouter gateway."""

import asyncio
import hashlib
import json
import os
import time
from decimal import Decimal
from uuid import uuid4

import httpx
from jsonschema import validate
from panoptes_database.session import unit_of_work
from sqlalchemy import text

from .registry import API


def provider_schema(schema):
    """Keep Gemini's decoding grammar small; enforce full constraints locally."""
    local_constraints = {
        "title",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "pattern",
        "format",
    }
    result = {}
    for key, value in schema.items():
        if key in local_constraints:
            continue
        if key in ("properties", "$defs", "definitions", "patternProperties"):
            result[key] = {
                name: provider_schema(child) for name, child in value.items()
            }
        elif isinstance(value, dict):
            result[key] = provider_schema(value)
        elif isinstance(value, list):
            result[key] = [
                provider_schema(child) if isinstance(child, dict) else child
                for child in value
            ]
        else:
            result[key] = value
    return result


class OpenRouter:
    def __init__(self, sessions, http):
        self.sessions = sessions
        self.http = http

    async def agent(self, slug):
        async with unit_of_work(self.sessions) as session:
            row = (
                (
                    await session.execute(
                        text("""
                SELECT a.id,a.slug,a.prompt,a.metadata,a.structured_output_schema,
                    a.default_model_id AS model_id,m.provider_id AS model,
                    p.pricing AS price_snapshot
                FROM ai.agent a JOIN ai.model m ON m.id=a.default_model_id
                LEFT JOIN ai.model_price p ON p.model_id=m.id AND p.deleted_at IS NULL
                WHERE a.slug=:slug AND a.deleted_at IS NULL AND m.deleted_at IS NULL
            """),
                        {"slug": slug},
                    )
                )
                .mappings()
                .one()
            )
            return dict(row)

    async def _begin(self, agent, request, context):
        public_id = uuid4()
        async with unit_of_work(self.sessions) as session:
            row_id = (
                await session.execute(
                    text("""
                INSERT INTO ai.interaction(public_id,agent_id,model_id,request,status,
                    agent_version,prompt_sha256,price_snapshot,context,trace_id,
                    job_id,html_snapshot_id,scrape_request_id,requested_model_id,attempt_qt)
                VALUES (:public_id,:agent_id,:model_id,CAST(:request AS jsonb),'pending',
                    :version,:hash,CAST(:price AS jsonb),CAST(:context AS jsonb),:trace_id,
                    :job_id,:html_snapshot_id,:scrape_request_id,:model_id,:attempt)
                RETURNING id
            """),
                    dict(
                        public_id=public_id,
                        agent_id=agent["id"],
                        model_id=agent["model_id"],
                        request=json.dumps(request),
                        version=agent["metadata"].get("version", "1"),
                        hash=hashlib.sha256(agent["prompt"].encode()).hexdigest(),
                        price=json.dumps(agent.get("price_snapshot") or {}),
                        context=json.dumps(context, default=str),
                        trace_id=context.get("correlation_id"),
                        job_id=context.get("job_id"),
                        html_snapshot_id=context.get("html_snapshot_id"),
                        scrape_request_id=context.get("scrape_request_id"),
                        attempt=context.get("attempt_qt", 1),
                    ),
                )
            ).scalar_one()
        return row_id, public_id

    async def _finish(
        self, identity, agent, request, response, status, error, elapsed, context
    ):
        row_id, public_id = identity
        usage = (response or {}).get("usage") or {}
        cost = usage.get("cost")
        document = dict(
            interaction_id=str(public_id),
            agent=agent["slug"],
            agent_version=agent["metadata"].get("version", "1"),
            prompt=agent["prompt"],
            structured_output_schema=agent["structured_output_schema"],
            request=request,
            response=response,
            status=status,
            error=error,
            context=context,
        )
        async with unit_of_work(self.sessions) as session:
            actual_model_id = agent["model_id"]
            actual_model = (response or {}).get("model")
            if (
                isinstance(actual_model, str)
                and "/" in actual_model
                and actual_model != agent["model"]
            ):
                actual_model_id = (
                    await session.execute(
                        text("""
                    INSERT INTO ai.model(provider_id,name) VALUES (:model,:model)
                    ON CONFLICT(provider_id) DO UPDATE SET provider_id=excluded.provider_id
                    RETURNING id
                """),
                        {"model": actual_model},
                    )
                ).scalar_one()
            await session.execute(
                text("""
                UPDATE ai.interaction SET response=CAST(:response AS jsonb),
                    model_id=:model_id,
                    provider_request_id=:provider_request_id,provider=:provider,
                    prompt_tokens=:prompt_tokens,completion_tokens=:completion_tokens,
                    total_tokens=:total_tokens,cost=:cost,cost_status=:cost_status,
                    latency_ms=:latency,status=:status,error=CAST(:error AS jsonb),finished_at=now()
                WHERE id=:id
            """),
                dict(
                    id=row_id,
                    response=json.dumps(response),
                    provider_request_id=(response or {}).get("id"),
                    provider=(response or {}).get("provider"),
                    prompt_tokens=usage.get("prompt_tokens", usage.get("input_tokens")),
                    completion_tokens=usage.get(
                        "completion_tokens",
                        usage.get(
                            "output_tokens",
                            0
                            if agent["metadata"].get("endpoint") == "embeddings"
                            else None,
                        ),
                    ),
                    total_tokens=usage.get("total_tokens"),
                    cost=Decimal(str(cost)) if cost is not None else None,
                    model_id=actual_model_id,
                    cost_status="reported" if cost is not None else "unknown",
                    latency=int(elapsed * 1000),
                    status=status,
                    error=json.dumps(error),
                ),
            )
            await session.execute(
                text("""
                INSERT INTO ai.audit_outbox(interaction_id,payload)
                VALUES (:id,CAST(:payload AS jsonb))
                ON CONFLICT(interaction_id) DO UPDATE SET payload=excluded.payload,available_at=now()
            """),
                {"id": row_id, "payload": json.dumps(document, default=str)},
            )

    async def invoke(self, slug, content, *, context=None, agent=None):
        if not os.getenv("OPENROUTER_API_KEY"):
            raise ValueError("OPENROUTER_API_KEY is required")
        agent = agent or await self.agent(slug)
        context = dict(context or {})
        first_attempt = context.get("attempt_qt", 1)
        for attempt in range(3):
            try:
                return await self._invoke_once(
                    slug,
                    content,
                    context={**context, "attempt_qt": first_attempt + attempt},
                    agent=agent,
                )
            except httpx.HTTPStatusError as error:
                if (
                    error.response.status_code not in (429, 502, 503, 504)
                    or attempt == 2
                ):
                    raise
                delay = 2 ** (attempt + 1)
                # Respect a bounded Retry-After; do not hold a worker indefinitely.
                retry_after = error.response.headers.get("retry-after", "")
                if retry_after.isdigit():
                    delay = max(delay, min(int(retry_after), 30))
                await asyncio.sleep(delay)

    async def _invoke_once(self, slug, content, *, context=None, agent=None):
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise ValueError("OPENROUTER_API_KEY is required")
        agent = agent or await self.agent(slug)
        metadata = agent["metadata"]
        endpoint = metadata.get("endpoint", "chat/completions")
        settings = metadata.get("settings") or {}
        request = {**settings, "model": agent["model"]}
        if endpoint == "embeddings":
            content = [content] if isinstance(content, str) else content
            request.update(input=content, encoding_format="float")
        elif endpoint == "chat/completions":
            request["messages"] = [
                {"role": "system", "content": agent["prompt"]},
                {"role": "user", "content": content},
            ]
            schema = agent["structured_output_schema"]
            if schema:
                request["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": slug.replace("-", "_"),
                        "strict": metadata.get("structured_output_strict", True),
                        "schema": provider_schema(schema)
                        if agent["model"].startswith("google/gemini-")
                        else schema,
                    },
                }
                request["provider"] = {"require_parameters": True}
        else:
            raise ValueError(f"Unsupported agent endpoint: {endpoint}")
        context = dict(context or {})
        identity = await self._begin(agent, request, context)
        started = time.monotonic()
        payload, error, status = None, None, "failed"
        try:
            response = await self.http.post(
                f"{API}/{endpoint}",
                headers={"Authorization": f"Bearer {key}"},
                json=request,
                timeout=60,
            )
            try:
                payload = response.json()
            except ValueError:
                payload = {"body": response.text}
            if not isinstance(payload, dict):
                payload = {"body": payload}
            response.raise_for_status()
            if payload.get("error"):
                raise ValueError("OpenRouter returned an inference error")
            if endpoint == "chat/completions":
                output = payload["choices"][0]["message"]["content"]
                if agent["structured_output_schema"]:
                    validate(json.loads(output), agent["structured_output_schema"])
            else:
                data = sorted(payload["data"], key=lambda item: item["index"])
                if [item["index"] for item in data] != list(range(len(content))):
                    raise ValueError("Invalid embedding response indices/count")
                import math

                dimensions = settings.get("dimensions")
                for item in data:
                    vector = item["embedding"]
                    if (
                        not vector
                        or (dimensions and len(vector) != dimensions)
                        or not all(math.isfinite(v) for v in vector)
                    ):
                        raise ValueError("Invalid embedding response vector")
            status = "completed"
            return payload
        except asyncio.CancelledError:
            status, error = "cancelled", {"type": "CancelledError"}
            raise
        except Exception as exc:
            # Full provider response is in the audit; do not persist authorization headers.
            error = {"type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            await asyncio.shield(
                self._finish(
                    identity,
                    agent,
                    request,
                    payload,
                    status,
                    error,
                    time.monotonic() - started,
                    context,
                )
            )
