from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from panoptes_contracts.base import Contract
from pydantic import Field

RequestStatus = Literal[
    "pending", "running", "completed", "partial", "failed", "blocked"
]


class AnalyticsTotals(Contract):
    products: int = Field(ge=0)
    active_routines: int = Field(ge=0)
    requests: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    in_progress: int = Field(ge=0)


class DailyActivity(Contract):
    date: date
    total: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)


class AnalyticsResponse(Contract):
    period_days: int
    totals: AnalyticsTotals
    daily: list[DailyActivity]


class ExtractionSummary(Contract):
    public_id: UUID
    site: str | None = None
    mode: Literal["discover", "refresh"]
    status: RequestStatus
    summary: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None
    search_term_id: UUID | None
    term: str | None
    entity_id: UUID | None
    source_key: str | None


class ExtractionPage(Contract):
    items: list[ExtractionSummary]
    total: int
    limit: int
    offset: int
