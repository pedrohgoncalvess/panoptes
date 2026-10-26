from typing import Literal
from uuid import UUID

from panoptes_contracts.base import Contract
from panoptes_contracts.schedules import RoutineSchedule
from pydantic import AwareDatetime, Field


class RoutineCreate(Contract):
    name: str = Field(min_length=1, max_length=200)
    search_term_id: UUID
    mode: Literal["discover", "refresh"] = "refresh"
    schedule: RoutineSchedule
    enabled: bool = True
    sites: list[str] | None = Field(default=None, min_length=1)


class RoutineUpdate(Contract):
    name: str = Field(min_length=1, max_length=200)
    schedule: RoutineSchedule
    enabled: bool
    sites: list[str] | None = Field(default=None, min_length=1)


class RoutineAdvance(Contract):
    next_run_at: AwareDatetime
