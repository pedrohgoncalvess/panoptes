"""Timezone-aware schedules shared by API and executors."""

import hashlib
import random
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator

from .base import Contract


class RoutineSchedule(Contract):
    kind: Literal["fixed", "random_daily", "interval"]
    timezone: str = "America/Sao_Paulo"
    times: list[str] = Field(default_factory=list, max_length=1440)
    times_per_day: int | None = Field(default=None, ge=1, le=1440)
    interval_minutes: int | None = Field(default=None, ge=1, le=525600)

    @model_validator(mode="after")
    def validate_schedule(self):
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        if self.kind == "fixed":
            if not self.times or len(set(self.times)) != len(self.times):
                raise ValueError("Supply distinct HH:MM times")
            for value in self.times:
                if (
                    len(value) != 5
                    or value[2] != ":"
                    or not (value[:2] + value[3:]).isdigit()
                ):
                    raise ValueError("Expected HH:MM")
                if int(value[:2]) > 23 or int(value[3:]) > 59:
                    raise ValueError("Invalid time")
        elif self.times:
            raise ValueError("Times require fixed schedule")
        if (self.kind == "random_daily") != (self.times_per_day is not None):
            raise ValueError("times_per_day requires random_daily")
        if (self.kind == "interval") != (self.interval_minutes is not None):
            raise ValueError("interval_minutes requires interval")
        return self


def next_run(schedule: RoutineSchedule, after: datetime, seed: str) -> datetime:
    if after.tzinfo is None:
        raise ValueError("Aware datetime required")
    if schedule.kind == "interval":
        return after.astimezone(UTC) + timedelta(minutes=schedule.interval_minutes)
    zone = ZoneInfo(schedule.timezone)
    day = after.astimezone(zone).date()
    for offset in range(370):
        date = day + timedelta(days=offset)
        if schedule.kind == "fixed":
            minutes = [int(t[:2]) * 60 + int(t[3:]) for t in schedule.times]
        else:
            digest = hashlib.sha256(
                f"{seed}:{date}:{schedule.model_dump_json()}".encode()
            ).digest()
            minutes = random.Random(digest).sample(range(1440), schedule.times_per_day)
        candidates = []
        for minute in minutes:
            local = datetime(
                date.year, date.month, date.day, minute // 60, minute % 60, tzinfo=zone
            )
            utc = local.astimezone(UTC)
            if utc.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
                continue
            if utc > after:
                candidates.append(utc)
        if candidates:
            return min(candidates)
    raise ValueError("No valid schedule occurrence")
