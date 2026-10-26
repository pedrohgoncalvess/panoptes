"""Audited, incremental multi-label categorization of canonical products."""

import asyncio
import json
import logging
import os
from uuid import uuid4

from panoptes_contracts.taxonomy import Classification
from panoptes_database import taxonomy as repository
from panoptes_database.session import unit_of_work
from sqlalchemy import text

from .normalization import bounded_evidence

logger = logging.getLogger(__name__)


def inference_input(evidence, taxa, policy):
    # Complete taxonomy, without counts/descriptions, keeps the catalog compact.
    # Never silently hide existing choices: oversized catalogs go to manual review.
    catalog = [
        {
            "id": str(n["id"]),
            "parent_id": str(n["parent_id"]) if n["parent_id"] else None,
            "name": n["name"],
            "active": n["active"],
        }
        for n in taxa
    ]
    content = {
        "product": {
            "name": evidence.get("name"),
            "identity": evidence.get("identity"),
            "source": bounded_evidence(evidence.get("source") or {}),
        },
        "taxonomy": catalog,
        "policy": policy,
        "counts": {
            "categories": sum(n["parent_id"] is None for n in taxa),
            "subcategories": sum(n["parent_id"] is not None for n in taxa),
        },
    }
    encoded = json.dumps(content, ensure_ascii=False)
    if len(encoded) > 180000:
        raise ValueError("Taxonomia excede o contexto econômico; revise manualmente.")
    return encoded


async def infer(client, evidence, taxa, policy, *, context):
    content = inference_input(evidence, taxa, policy)
    payload = await client.invoke("taxonomy_normalizer", content, context=context)
    output = payload["choices"][0]["message"]["content"]
    if len(output) > 25000:
        raise ValueError("Resposta de classificação muito extensa.")
    result = Classification.model_validate_json(output)
    # Evidence must come from the product, never from an existing category label.
    product = json.loads(content)["product"]

    def fragments(value):
        if isinstance(value, dict):
            return [part for v in value.values() for part in fragments(v)]
        if isinstance(value, list):
            return [part for v in value for part in fragments(v)]
        return [str(value)] if value is not None else []

    source_fragments = fragments(product)
    for category in result.categories:
        for choice in (category, *category.subcategories):
            if not any(choice.evidence in fragment for fragment in source_fragments):
                raise ValueError(
                    "Evidência de classificação não encontrada no produto."
                )
    return result


async def process_one(sessions, client):
    token = uuid4()
    async with unit_of_work(sessions) as session:
        row = (
            (
                await session.execute(
                    text("""
          WITH candidate AS (
            SELECT product_id FROM catalog.taxonomy_task
            WHERE status IN ('pending','failed','processing') AND available_at<=now()
              AND attempts<5 ORDER BY available_at,product_id
            FOR UPDATE SKIP LOCKED LIMIT 1
          ) UPDATE catalog.taxonomy_task t SET status='processing',attempts=attempts+1,
            lease_token=:token,available_at=now()+interval '5 minutes',updated_at=now()
          FROM candidate c WHERE t.product_id=c.product_id RETURNING t.*
        """),
                    {"token": token},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return False
        taxa, policy = await repository.nodes(session), await repository.policy(session)
    try:
        result = await infer(
            client,
            row["evidence"],
            taxa,
            policy,
            context={
                "canonical_product_id": row["product_id"],
                "attempt_qt": row["attempts"],
            },
        )
        async with unit_of_work(sessions) as session:
            await repository.lock(session)
            current = (
                await session.execute(
                    text("""
              SELECT product_id FROM catalog.taxonomy_task
              WHERE product_id=:id AND lease_token=:token AND status='processing' FOR UPDATE
            """),
                    {"id": row["product_id"], "token": token},
                )
            ).scalar_one_or_none()
            if current is None:
                return True  # Manual correction or newer lease wins over inference.
            status, document = "completed", result.model_dump(mode="json")
            if result.confidence < 0.9:
                status = "needs_review"
            else:
                try:
                    # Refresh under the lock: concurrent workers can already have
                    # created a suggestion, renamed a node, or changed the policy.
                    await repository.apply_classification(
                        session,
                        current,
                        result,
                        await repository.nodes(session),
                        await repository.policy(session),
                    )
                except ValueError as exc:
                    status, document = (
                        "needs_review",
                        {**document, "review_reason": str(exc)},
                    )
            await session.execute(
                text("""
              UPDATE catalog.taxonomy_task SET status=:status,result=CAST(:result AS jsonb),
                lease_token=NULL,updated_at=now() WHERE product_id=:id AND lease_token=:token
            """),
                {
                    "id": current,
                    "token": token,
                    "status": status,
                    "result": json.dumps(document),
                },
            )
    except Exception as exc:
        logger.warning(
            "Taxonomy failed for product %s: %s", row["product_id"], type(exc).__name__
        )
        async with unit_of_work(sessions) as session:
            await session.execute(
                text("""
              UPDATE catalog.taxonomy_task SET status='failed',lease_token=NULL,
                result=CAST(:result AS jsonb),updated_at=now(),
                available_at=now()+interval '1 minute'*power(2,attempts)
              WHERE product_id=:id AND lease_token=:token
            """),
                {
                    "id": row["product_id"],
                    "token": token,
                    "result": json.dumps({"error": type(exc).__name__}),
                },
            )
    return True


async def taxonomy_loop(sessions, client, stop):
    while not stop.is_set():
        enabled = (
            bool(os.getenv("OPENROUTER_API_KEY"))
            and os.getenv("TAXONOMY_NORMALIZER_ENABLED", "true").lower() == "true"
        )
        try:
            if enabled and await process_one(sessions, client):
                continue
        except Exception:
            logger.exception("Taxonomy queue unavailable")
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass
