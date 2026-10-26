from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from .base import Contract

Money = Annotated[Decimal, Field(ge=0, max_digits=30, decimal_places=16)]
Version = Annotated[str, Field(min_length=1)]


class Layer(StrEnum):
    STRUCTURED_DATA = "structured_data"
    SITE_PARSER = "site_parser"
    RENDERED_DOM = "rendered_dom"
    LLM = "llm"


class HtmlSnapshot(Contract):
    public_id: UUID
    source_url: HttpUrl
    final_url: HttpUrl
    captured_at: AwareDatetime
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    artifact_uri: str = Field(min_length=1)
    media_type: Literal["text/html"] = "text/html"
    encoding: str = "utf-8"
    byte_qt: int = Field(ge=0)
    http_status: int = Field(ge=100, le=599)
    capture_mode: Literal["http", "browser", "browser_local"]
    parent_snapshot_id: UUID | None = None


class Evidence(Contract):
    entity_source_key: str = Field(min_length=1)
    field: str = Field(min_length=1)
    snapshot_id: UUID
    locator: str = Field(min_length=1)
    method: Literal["css", "xpath", "json_pointer", "text"]
    excerpt: str = Field(min_length=1, max_length=2000)


class ExtractedEntity(Contract):
    kind: Literal["product", "service"]
    source_key: str = Field(min_length=1)
    url: HttpUrl
    title: str = Field(min_length=1)
    description: str | None = None
    price: Money | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    availability: Literal["in_stock", "out_of_stock", "unknown"] = "unknown"
    attributes: dict[str, str | int | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_money(self):
        if (self.price is None) != (self.currency is None):
            raise ValueError("price and currency must be provided together")
        return self


class ExtractionPolicy(Contract):
    layers: tuple[Layer, ...] = (
        Layer.STRUCTURED_DATA,
        Layer.SITE_PARSER,
        Layer.RENDERED_DOM,
        Layer.LLM,
    )
    required_fields: tuple[str, ...] = ("source_key", "url", "title")
    min_confidence: Decimal = Field(default=Decimal("0.95"), ge=0, le=1)
    layer_timeout_seconds: float = Field(default=30, gt=0)
    max_llm_calls: int = Field(default=0, ge=0)
    max_cost_usd: Money = Decimal("0")

    @model_validator(mode="after")
    def validate_layers(self):
        if not self.layers or len(set(self.layers)) != len(self.layers):
            raise ValueError("layers must be nonempty and unique")
        if Layer.LLM in self.layers and self.layers[-1] != Layer.LLM:
            raise ValueError("LLM must be the last layer")
        allowed = set(ExtractedEntity.model_fields)
        if not self.required_fields or not set(self.required_fields) <= allowed:
            raise ValueError("required_fields must reference entity fields")
        return self


class ExtractionJob(Contract):
    contract_version: Literal["1.0"] = "1.0"
    public_id: UUID
    correlation_id: UUID
    routine_id: UUID
    routine_version: Version
    snapshot: HtmlSnapshot
    parser_slug: Version
    parser_version: Version
    policy: ExtractionPolicy = Field(default_factory=ExtractionPolicy)
    idempotency_key: str = Field(min_length=1)


class LayerOutcome(Contract):
    status: Literal["success", "miss", "blocked", "failed"]
    entities: tuple[ExtractedEntity, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    confidence: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    reason: str | None = None


class LayerAttempt(Contract):
    layer: Layer
    outcome: LayerOutcome
    duration_ms: int = Field(ge=0)


class ExtractionResult(Contract):
    contract_version: Literal["1.0"] = "1.0"
    job_id: UUID
    snapshot_id: UUID
    correlation_id: UUID
    status: Literal["completed", "exhausted", "blocked"]
    entities: tuple[ExtractedEntity, ...] = ()
    attempts: tuple[LayerAttempt, ...]
    completed_at: AwareDatetime
