"""Durable semantic identities for comparison, independent of retailer variants."""

import asyncio
import json
import logging
import os
import re
import unicodedata
from uuid import uuid4

from panoptes_contracts.base import Contract
from panoptes_database.session import unit_of_work
from pydantic import Field, model_validator
from sqlalchemy import text

from .workflow.catalog_repository import fingerprint

logger = logging.getLogger(__name__)


class MaterialAttribute(Contract):
    name: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=1000)


class Normalization(Contract):
    name: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=80)
    brand: str = Field(min_length=1, max_length=150)
    model: str = Field(min_length=1, max_length=200)
    attributes: list[MaterialAttribute] = Field(max_length=30)
    missing: list[str] = Field(max_length=30)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_attributes(self):
        keys = [normalize(a.name) for a in self.attributes]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate_material_attribute")
        if any(k in {"color", "colour", "cor", "seller", "marketplace"} for k in keys):
            raise ValueError("cosmetic_attribute_in_identity")
        return self


def normalize(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value).strip()


def identity(result):
    return {
        "category": normalize(result.category),
        "brand": normalize(result.brand),
        "model": normalize(result.model),
        "attributes": {
            normalize(a.name): normalize(a.value) for a in result.attributes
        },
    }


def evidence_input(payload):
    entity = payload.get("entity") or {}
    return {
        "entity": {
            "title": entity.get("title"),
            "description": entity.get("description"),
        },
        "catalog": payload.get("catalog"),
        "specifications": payload.get("specifications") or {},
        "offer": {"condition": (payload.get("offer") or {}).get("condition")},
    }


async def enqueue(session, listing_id, payload):
    evidence = json.dumps(evidence_input(payload), ensure_ascii=False)
    # Hash in PostgreSQL so backfill and live captures share the same JSONB encoding.
    await session.execute(
        text("""
        INSERT INTO catalog.product_normalization(listing_id,input_hash,input)
        VALUES (:listing,md5(CAST(:input AS jsonb)::text),CAST(:input AS jsonb))
        ON CONFLICT(listing_id) DO UPDATE SET input=excluded.input,
          input_hash=excluded.input_hash,status='pending',canonical_product_id=NULL,
          result=NULL,attempts=0,available_at=now(),lease_token=NULL,updated_at=now()
        WHERE product_normalization.input_hash<>excluded.input_hash
    """),
        {"listing": listing_id, "input": evidence},
    )


def bounded_evidence(source):
    # Bound paid context while retaining structured attributes and specifications.
    entity = source.get("entity") or {}
    return {
        "entity": {
            "title": (entity.get("title") or "")[:1500],
            "description": (entity.get("description") or "")[:6000],
        },
        "catalog": source.get("catalog"),
        "offer": {"condition": (source.get("offer") or {}).get("condition")},
        "specifications": {
            str(k)[:150]: str(v)[:1000]
            for k, v in list((source.get("specifications") or {}).items())[:60]
        },
    }


async def infer(client, source, *, context):
    source = bounded_evidence(source)
    payload = await client.invoke(
        "product_normalizer", json.dumps(source, ensure_ascii=False), context=context
    )
    content = payload["choices"][0]["message"]["content"]
    if len(content) > 20000:
        raise ValueError("normalization_output_too_large")
    result = Normalization.model_validate_json(content)
    fragments = []
    for section in source.values():
        if isinstance(section, dict):
            fragments.extend(str(v) for v in section.values() if v is not None)
    for attribute in result.attributes:
        if not any(attribute.evidence in fragment for fragment in fragments):
            raise ValueError("normalization_evidence_invalid")
    missing = set(result.missing)
    for key in ("brand", "model", "category"):
        if normalize(getattr(result, key)) in {"unknown", "desconhecido", "other", ""}:
            missing.add(key)
    if "kindle" in normalize(result.model) and not any(
        normalize(a.name) == "storage_gb" for a in result.attributes
    ):
        missing.add("storage_gb")
    if missing:
        result = result.model_copy(update={"missing": sorted(missing)})
    return result


async def process_one(sessions, client):
    token = uuid4()
    async with unit_of_work(sessions) as session:
        row = (
            (
                await session.execute(
                    text("""
          WITH candidate AS (
            SELECT listing_id FROM catalog.product_normalization
            WHERE status IN ('pending','failed','processing') AND available_at<=now()
              AND attempts<5 ORDER BY available_at,listing_id
            FOR UPDATE SKIP LOCKED LIMIT 1
          ) UPDATE catalog.product_normalization n SET status='processing',
            attempts=attempts+1,lease_token=:token,available_at=now()+interval '5 minutes',
            updated_at=now() FROM candidate c WHERE n.listing_id=c.listing_id
          RETURNING n.*
        """),
                    {"token": token},
                )
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return False
    try:
        result = await infer(
            client,
            row["input"],
            context={
                "listing_id": row["listing_id"],
                "input_hash": row["input_hash"],
                "attempt_qt": row["attempts"],
            },
        )
        status = (
            "uncertain" if result.missing or result.confidence < 0.9 else "completed"
        )
        async with unit_of_work(sessions) as session:
            current = (
                await session.execute(
                    text("""
              SELECT listing_id FROM catalog.product_normalization
              WHERE listing_id=:id AND lease_token=:token FOR UPDATE
            """),
                    {"id": row["listing_id"], "token": token},
                )
            ).scalar_one_or_none()
            if current is None:
                return True  # A newer capture invalidated this inference.
            canonical_id = None
            if status == "completed":
                normalized = identity(result)
                canonical_id = (
                    await session.execute(
                        text("""
                  INSERT INTO catalog.canonical_product(identity_key,name,identity)
                  VALUES (:key,:name,CAST(:identity AS jsonb))
                  ON CONFLICT(identity_key) DO UPDATE SET identity_key=excluded.identity_key
                  RETURNING id
                """),
                        {
                            "key": fingerprint(normalized),
                            "name": result.name,
                            "identity": json.dumps(normalized),
                        },
                    )
                ).scalar_one()
                from panoptes_database.taxonomy import enqueue as enqueue_taxonomy

                await enqueue_taxonomy(session, canonical_id, row["input"])
            await session.execute(
                text("""
              UPDATE catalog.product_normalization SET status=:status,
                canonical_product_id=:canonical,result=CAST(:result AS jsonb),
                lease_token=NULL,updated_at=now()
              WHERE listing_id=:id AND lease_token=:token
            """),
                {
                    "id": current,
                    "token": token,
                    "status": status,
                    "canonical": canonical_id,
                    "result": result.model_dump_json(),
                },
            )
    except Exception as exc:
        logger.warning(
            "Product normalization failed for listing %s: %s",
            row["listing_id"],
            type(exc).__name__,
        )
        async with unit_of_work(sessions) as session:
            await session.execute(
                text("""
              UPDATE catalog.product_normalization SET status='failed',lease_token=NULL,
                result=CAST(:error AS jsonb),updated_at=now(),
                available_at=now()+interval '1 minute'*power(2,attempts)
              WHERE listing_id=:id AND lease_token=:token
            """),
                {
                    "id": row["listing_id"],
                    "token": token,
                    "error": json.dumps({"error": type(exc).__name__}),
                },
            )
    return True


async def normalization_loop(sessions, client, stop):
    while not stop.is_set():
        enabled = (
            bool(os.getenv("OPENROUTER_API_KEY"))
            and os.getenv("PRODUCT_NORMALIZER_ENABLED", "true").lower() == "true"
        )
        try:
            if enabled and await process_one(sessions, client):
                continue
        except Exception:
            logger.exception("Product normalization queue unavailable")
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass
