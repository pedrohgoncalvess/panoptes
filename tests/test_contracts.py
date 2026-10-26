from decimal import Decimal
from uuid import uuid4

import pytest
from panoptes_contracts import (
    CONTRACTS,
    ExtractionJob,
    ExtractionPolicy,
    LlmInteraction,
)
from panoptes_contracts.llm import summarize_html_cost
from pydantic import ValidationError


def interaction(snapshot_id, cost=None, status="unknown"):
    return LlmInteraction(
        public_id=uuid4(),
        job_id=uuid4(),
        snapshot_id=snapshot_id,
        correlation_id=uuid4(),
        agent_slug="extractor",
        agent_version="1",
        model="test-model",
        attempt_qt=1,
        prompt_sha256="a" * 64,
        status="completed",
        cost_usd=cost,
        cost_status=status,
    )


def test_cost_preserves_tiny_values_and_unknowns():
    snapshot = uuid4()
    rows = (
        interaction(snapshot, Decimal("0.0000000000000012"), "reported"),
        interaction(snapshot, Decimal("0.0000000000000013"), "reconciled"),
        interaction(snapshot),
        interaction(uuid4(), Decimal("1"), "reported"),
    )
    result = summarize_html_cost(snapshot, rows)
    assert result.known_cost_usd == Decimal("0.0000000000000025")
    assert result.unknown_interactions_qt == 1
    assert result.interactions_qt == 3
    assert not result.complete


def test_estimated_cost_is_not_final():
    snapshot = uuid4()
    result = summarize_html_cost(
        snapshot, (interaction(snapshot, "0.0001", "estimated"),)
    )
    assert result.estimated_interactions_qt == 1
    assert not result.complete


def test_unknown_cost_is_not_zero():
    with pytest.raises(ValidationError):
        interaction(uuid4(), "0", "unknown")
    assert interaction(uuid4(), "0", "reported").cost_usd == 0


def test_contract_roundtrip_and_no_unknown_fields(job):
    assert ExtractionJob.model_validate_json(job.model_dump_json()) == job
    with pytest.raises(ValidationError):
        ExtractionJob.model_validate({**job.model_dump(), "unexpected": True})


def test_llm_last_and_duplicate_layers_rejected():
    with pytest.raises(ValidationError):
        ExtractionPolicy(layers=("llm", "site_parser"))
    with pytest.raises(ValidationError):
        ExtractionPolicy(layers=("site_parser", "site_parser"))


@pytest.mark.parametrize("model", CONTRACTS.values())
def test_all_contracts_export_json_schema(model):
    assert model.model_json_schema()["type"] == "object"
