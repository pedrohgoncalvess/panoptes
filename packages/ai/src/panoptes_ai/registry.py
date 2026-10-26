"""Load platform agents from disk and synchronize the OpenRouter catalog."""

import asyncio
import json
import logging
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from panoptes_database.session import unit_of_work
from sqlalchemy import text

logger = logging.getLogger(__name__)
API = "https://openrouter.ai/api/v1"
PRICE_FIELDS = (
    "prompt",
    "completion",
    "request",
    "image",
    "web_search",
    "internal_reasoning",
    "input_cache_read",
    "input_cache_write",
)


def catalog_path():
    return Path(os.getenv("AGENTS_CATALOG", "agents/metadata.yaml"))


def load_agents(path=None):
    path = Path(path or catalog_path()).resolve()
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if document.get("version") != 1 or not isinstance(document.get("agents"), dict):
        raise ValueError("metadata.yaml requires version: 1 and an agents mapping")

    def resource(relative):
        target = (path.parent / relative).resolve()
        if path.parent not in target.parents:
            raise ValueError(f"Agent resource escapes agents/: {relative}")
        return target

    agents = []
    for slug, entry in document["agents"].items():
        model = entry["model"]
        if not isinstance(model, str) or "/" not in model:
            raise ValueError(f"Invalid OpenRouter model ID for {slug}")
        prompt = resource(entry["prompt"]).read_text(encoding="utf-8").strip()
        if not prompt:
            raise ValueError(f"Empty prompt for {slug}")
        schema = None
        if entry.get("structured_output"):
            schema = json.loads(resource(entry["structured_output"]).read_text("utf-8"))
            Draft202012Validator.check_schema(schema)

            # Schemas are self-contained; validation never fetches external resources.
            def check_refs(value):
                if isinstance(value, dict):
                    if "$ref" in value and not value["$ref"].startswith("#"):
                        raise ValueError("Agent schemas must use local JSON references")
                    for child in value.values():
                        check_refs(child)
                elif isinstance(value, list):
                    for child in value:
                        check_refs(child)

            check_refs(schema)
        settings = dict(entry.get("settings") or {})
        if {
            "model",
            "messages",
            "input",
            "stream",
            "response_format",
        } & settings.keys():
            raise ValueError(f"Reserved inference settings for {slug}")
        endpoint = entry.get("endpoint", "chat/completions")
        if endpoint not in ("chat/completions", "embeddings"):
            raise ValueError(f"Unsupported endpoint for {slug}")
        if endpoint == "embeddings" and schema is not None:
            raise ValueError("Embedding agents cannot specify structured output")
        agents.append(
            dict(
                slug=slug,
                name=entry["name"],
                description=entry["description"],
                model=model,
                prompt=prompt,
                schema=schema,
                metadata={
                    "version": str(entry.get("version", "1")),
                    "endpoint": endpoint,
                    "settings": settings,
                    "structured_output_strict": entry.get(
                        "structured_output_strict", True
                    ),
                },
            )
        )
    return agents


async def sync_agents(sessions, agents=None):
    agents = load_agents() if agents is None else agents
    async with unit_of_work(sessions) as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(73180911)"))
        for agent in agents:
            model_id = (
                await session.execute(
                    text("""
                INSERT INTO ai.model(provider_id,name) VALUES (:model,:model)
                ON CONFLICT(provider_id) DO UPDATE SET deleted_at=NULL RETURNING id
            """),
                    {"model": agent["model"]},
                )
            ).scalar_one()
            await session.execute(
                text("""
                INSERT INTO ai.agent(slug,name,description,default_model_id,prompt,
                    structured_output_schema,metadata)
                VALUES (:slug,:name,:description,:model_id,:prompt,
                    CAST(:schema AS jsonb),CAST(:metadata AS jsonb))
                ON CONFLICT(slug) DO UPDATE SET name=excluded.name,
                    description=excluded.description,default_model_id=excluded.default_model_id,
                    prompt=excluded.prompt,structured_output_schema=excluded.structured_output_schema,
                    metadata=excluded.metadata,updated_at=now(),deleted_at=NULL
            """),
                {
                    **{k: agent[k] for k in ("slug", "name", "description", "prompt")},
                    "model_id": model_id,
                    "schema": json.dumps(agent["schema"]) if agent["schema"] else None,
                    "metadata": json.dumps(agent["metadata"]),
                },
            )
    return len(agents)


async def sync_models(sessions, http):
    # Explicit all: the default catalog excludes embedding/image/audio models.
    response = await http.get(f"{API}/models", params={"output_modalities": "all"})
    response.raise_for_status()
    models = {model["id"]: model for model in response.json()["data"]}
    async with unit_of_work(sessions) as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(73180912)"))
        registered = (
            (
                await session.execute(
                    text("SELECT id,provider_id FROM ai.model WHERE deleted_at IS NULL")
                )
            )
            .mappings()
            .all()
        )
        for row in registered:
            model = models.get(row["provider_id"])
            if model is None:
                logger.warning(
                    "Registered OpenRouter model absent from catalog: %s",
                    row["provider_id"],
                )
                continue
            architecture = model.get("architecture") or {}
            await session.execute(
                text("""
                UPDATE ai.model SET canonical_slug=:canonical_slug,name=:name,
                    description=:description,context_length=:context_length,
                    architecture=CAST(:architecture AS jsonb),top_provider=CAST(:top_provider AS jsonb),
                    per_request_limits=CAST(:limits AS jsonb),supported_parameters=:parameters,
                    input_modalities=:inputs,output_modalities=:outputs,
                    default_parameters=CAST(:defaults AS jsonb),expiration_date=CAST(:expiration AS date),
                    metadata=CAST(:metadata AS jsonb),updated_at=now(),catalog_synced_at=now()
                WHERE id=:id
            """),
                dict(
                    id=row["id"],
                    canonical_slug=model.get("canonical_slug"),
                    name=model.get("name", model["id"]),
                    description=model.get("description"),
                    context_length=model.get("context_length"),
                    architecture=json.dumps(architecture),
                    top_provider=json.dumps(model.get("top_provider") or {}),
                    limits=json.dumps(model.get("per_request_limits")),
                    parameters=model.get("supported_parameters") or [],
                    inputs=architecture.get("input_modalities") or [],
                    outputs=architecture.get("output_modalities") or [],
                    defaults=json.dumps(model.get("default_parameters")),
                    expiration=date.fromisoformat(model["expiration_date"])
                    if model.get("expiration_date")
                    else None,
                    metadata=json.dumps(model),
                ),
            )
            pricing = model.get("pricing") or {}
            # Compare the complete pricing object, including future/audio/tiered prices.
            await session.execute(
                text("""
                UPDATE ai.model_price SET deleted_at=now()
                WHERE model_id=:id AND deleted_at IS NULL AND pricing IS DISTINCT FROM CAST(:pricing AS jsonb)
            """),
                {"id": row["id"], "pricing": json.dumps(pricing)},
            )
            fields = ",".join(PRICE_FIELDS)
            values = ",".join(f":{field}" for field in PRICE_FIELDS)
            await session.execute(
                text(f"""
                INSERT INTO ai.model_price(model_id,{fields},pricing)
                SELECT :id,{values},CAST(:pricing AS jsonb)
                WHERE NOT EXISTS (SELECT 1 FROM ai.model_price WHERE model_id=:id AND deleted_at IS NULL)
            """),
                {
                    "id": row["id"],
                    "pricing": json.dumps(pricing),
                    **{
                        field: Decimal(str(pricing[field]))
                        if pricing.get(field) not in (None, "")
                        else None
                        for field in PRICE_FIELDS
                    },
                },
            )
            await session.execute(
                text("""
                UPDATE ai.model_price SET checked_at=now() WHERE model_id=:id AND deleted_at IS NULL
            """),
                {"id": row["id"]},
            )


async def model_sync_loop(sessions, http):
    interval = max(60, int(os.getenv("OPENROUTER_SYNC_INTERVAL_SECONDS", "3600")))
    while True:
        try:
            await sync_models(sessions, http)
        except Exception:
            logger.exception("OpenRouter catalog synchronization failed; will retry")
        await asyncio.sleep(interval)
