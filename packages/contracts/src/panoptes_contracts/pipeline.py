"""Offline orchestration only. LLM adapters must enforce the ledger budget."""

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from time import perf_counter

from .extraction import (
    ExtractionJob,
    ExtractionResult,
    Layer,
    LayerAttempt,
    LayerOutcome,
)
from .ports import Extractor


def is_acceptable(job: ExtractionJob, outcome: LayerOutcome) -> bool:
    if (
        outcome.status != "success"
        or not outcome.entities
        or outcome.confidence < job.policy.min_confidence
    ):
        return False
    for entity in outcome.entities:
        for field in job.policy.required_fields:
            if getattr(entity, field) in (None, ""):
                return False
            if not any(
                e.field == field
                and e.entity_source_key == entity.source_key
                and e.snapshot_id == job.snapshot.public_id
                for e in outcome.evidence
            ):
                return False
    return True


async def run_pipeline(
    job: ExtractionJob, extractors: Mapping[Layer, Extractor]
) -> ExtractionResult:
    attempts = []
    status = "exhausted"
    entities = ()
    for layer in job.policy.layers:
        start = perf_counter()
        outcome = await _run_layer(job, layer, extractors.get(layer))
        attempts.append(
            LayerAttempt(
                layer=layer,
                outcome=outcome,
                duration_ms=int((perf_counter() - start) * 1000),
            )
        )
        if outcome.status == "blocked":
            status = "blocked"
            break
        if is_acceptable(job, outcome):
            status, entities = "completed", outcome.entities
            break
    return ExtractionResult(
        job_id=job.public_id,
        snapshot_id=job.snapshot.public_id,
        correlation_id=job.correlation_id,
        status=status,
        entities=entities,
        attempts=tuple(attempts),
        completed_at=datetime.now(timezone.utc),
    )


async def _run_layer(
    job: ExtractionJob, layer: Layer, extractor: Extractor | None
) -> LayerOutcome:
    if extractor is None:
        return LayerOutcome(status="miss", reason="adapter_not_registered")
    if layer == Layer.LLM:
        # No paid execution in v1: budget reservation/reconciliation is a port only.
        return LayerOutcome(status="miss", reason="llm_execution_not_implemented")
    try:
        async with asyncio.timeout(job.policy.layer_timeout_seconds):
            return await extractor(job)
    except TimeoutError:
        return LayerOutcome(status="failed", reason="layer_timeout")
    except Exception:
        return LayerOutcome(status="failed", reason="adapter_error")
