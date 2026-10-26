import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from panoptes_contracts import ExtractionPolicy, Layer, LayerOutcome
from panoptes_contracts.pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[1]


def success():
    return LayerOutcome.model_validate_json(
        (ROOT / "workers/parsers/amazon/expected.json").read_text(encoding="utf-8")
    )


async def test_stops_after_validated_parser(job):
    parser = AsyncMock(return_value=success())
    rendered = AsyncMock()
    result = await run_pipeline(
        job,
        {
            Layer.STRUCTURED_DATA: AsyncMock(return_value=LayerOutcome(status="miss")),
            Layer.SITE_PARSER: parser,
            Layer.RENDERED_DOM: rendered,
        },
    )
    assert result.status == "completed"
    assert len(result.entities) == 1
    assert len(result.attempts) == 2
    rendered.assert_not_awaited()


async def test_missing_evidence_falls_through(job):
    invalid = success().model_copy(update={"evidence": ()})
    result = await run_pipeline(
        job,
        {
            Layer.STRUCTURED_DATA: AsyncMock(return_value=invalid),
            Layer.SITE_PARSER: AsyncMock(return_value=success()),
        },
    )
    assert result.status == "completed"
    assert len(result.attempts) == 2


async def test_evidence_cannot_be_reused_for_another_entity(job):
    good = success()
    second = good.entities[0].model_copy(update={"source_key": "different-product"})
    invalid = good.model_copy(update={"entities": (*good.entities, second)})
    result = await run_pipeline(
        job, {Layer.SITE_PARSER: AsyncMock(return_value=invalid)}
    )
    assert result.status == "exhausted"


async def test_blocked_capture_does_not_escalate(job):
    parser = AsyncMock()
    result = await run_pipeline(
        job,
        {
            Layer.STRUCTURED_DATA: AsyncMock(
                return_value=LayerOutcome(status="blocked")
            ),
            Layer.SITE_PARSER: parser,
        },
    )
    assert result.status == "blocked"
    parser.assert_not_awaited()


async def test_llm_cannot_make_paid_calls_in_contract_mode(job):
    llm = AsyncMock()
    result = await run_pipeline(job, {Layer.LLM: llm})
    assert result.status == "exhausted"
    assert result.attempts[-1].outcome.reason == "llm_execution_not_implemented"
    llm.assert_not_awaited()


async def test_timeout_falls_through(job):
    async def slow(_):
        await asyncio.sleep(1)

    job = job.model_copy(
        update={"policy": ExtractionPolicy(layer_timeout_seconds=0.01)}
    )
    result = await run_pipeline(
        job,
        {
            Layer.STRUCTURED_DATA: slow,
            Layer.SITE_PARSER: AsyncMock(return_value=success()),
        },
    )
    assert result.status == "completed"
    assert result.attempts[0].outcome.reason == "layer_timeout"


async def test_cancellation_propagates(job):
    async def cancelled(_):
        raise asyncio.CancelledError()

    import pytest

    with pytest.raises(asyncio.CancelledError):
        await run_pipeline(job, {Layer.STRUCTURED_DATA: cancelled})
