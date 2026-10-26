from decimal import Decimal, localcontext
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .base import Contract
from .extraction import Money, Version


class AgentDefinition(Contract):
    slug: Version
    version: Version
    role: Literal["navigator", "extractor", "parser_repair"]
    prompt_path: str
    output_schema_path: str | None = None
    model: str = Field(pattern=r"^[^/]+/.+$")
    allowed_models: tuple[str, ...] = ()
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    max_steps: int = Field(default=1, gt=0)


class NavigationAction(Contract):
    action: Literal["follow_link", "inspect", "stop"]
    target: str | None = None
    reason: str


class ParserRepairProposal(Contract):
    parser_slug: Version
    base_version: Version
    proposed_version: Version
    explanation: str
    unified_diff: str
    fixtures_to_verify: tuple[str, ...] = Field(min_length=1)


class LlmInteraction(Contract):
    public_id: UUID
    job_id: UUID
    snapshot_id: UUID
    correlation_id: UUID
    agent_slug: Version
    agent_version: Version
    model: Version
    provider: str | None = None
    provider_request_id: str | None = None
    attempt_qt: int = Field(ge=1)
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["pending", "completed", "failed", "cancelled"]
    prompt_tokens_qt: int | None = Field(default=None, ge=0)
    completion_tokens_qt: int | None = Field(default=None, ge=0)
    cost_usd: Money | None = None
    cost_status: Literal["unknown", "estimated", "reported", "reconciled"] = "unknown"
    price_snapshot: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_cost(self):
        if (self.cost_usd is None) != (self.cost_status == "unknown"):
            raise ValueError("unknown cost must be null; known cost needs a status")
        return self


class HtmlCostSummary(Contract):
    snapshot_id: UUID
    known_cost_usd: Money
    unknown_interactions_qt: int = Field(ge=0)
    estimated_interactions_qt: int = Field(ge=0)
    interactions_qt: int = Field(ge=0)
    complete: bool


def summarize_html_cost(
    snapshot_id: UUID, interactions: tuple[LlmInteraction, ...]
) -> HtmlCostSummary:
    rows = [row for row in interactions if row.snapshot_id == snapshot_id]
    if len({row.public_id for row in rows}) != len(rows):
        raise ValueError("duplicate interaction identifiers")
    unknown = sum(row.cost_status == "unknown" for row in rows)
    estimated = sum(row.cost_status == "estimated" for row in rows)
    with localcontext() as context:
        context.prec = 60
        total = sum(
            (row.cost_usd for row in rows if row.cost_usd is not None), Decimal(0)
        )
    return HtmlCostSummary(
        snapshot_id=snapshot_id,
        known_cost_usd=total,
        unknown_interactions_qt=unknown,
        estimated_interactions_qt=estimated,
        interactions_qt=len(rows),
        complete=not (unknown or estimated),
    )
