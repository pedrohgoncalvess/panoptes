from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from panoptes_contracts.schedules import RoutineSchedule, next_run
from panoptes_workers.workflow.schedules import enqueue_schedules
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql.asyncpg import dialect


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "fixed", "times": []},
        {"kind": "fixed", "times": ["24:00"]},
        {"kind": "fixed", "times": ["08:00", "08:00"]},
        {"kind": "interval"},
        {"kind": "random_daily", "times_per_day": 0},
        {"kind": "fixed", "times": ["08:00"], "interval_minutes": 10},
        {"kind": "interval", "interval_minutes": 5, "timezone": "invalid"},
    ],
)
def test_reject_invalid_schedules(payload):
    with pytest.raises(ValidationError):
        RoutineSchedule(**payload)


def test_fixed_times_use_local_timezone_and_roll_day():
    schedule = RoutineSchedule(kind="fixed", times=["08:00", "18:00"])
    now = datetime(2026, 10, 4, 11, tzinfo=UTC)
    assert next_run(schedule, now, "routine") == datetime(2026, 10, 4, 21, tzinfo=UTC)
    assert next_run(
        schedule, datetime(2026, 10, 4, 21, tzinfo=UTC), "routine"
    ) == datetime(2026, 10, 5, 11, tzinfo=UTC)


def test_random_daily_is_restart_stable_and_distinct():
    schedule = RoutineSchedule(kind="random_daily", times_per_day=10, timezone="UTC")
    start = datetime(2026, 10, 4, tzinfo=UTC) - timedelta(microseconds=1)
    first = next_run(schedule, start, "routine")
    assert first == next_run(schedule, start, "routine")
    times = []
    for _ in range(10):
        start = next_run(schedule, start, "routine")
        times.append(start)
    assert len(set(times)) == 10
    assert all(t.date() == first.date() for t in times)
    assert next_run(schedule, start, "routine").date() > first.date()


def test_interval_and_dst_nonexistent_hour():
    start = datetime(2026, 10, 4, tzinfo=UTC)
    assert next_run(
        RoutineSchedule(kind="interval", interval_minutes=15), start, "a"
    ) == start + timedelta(minutes=15)
    schedule = RoutineSchedule(
        kind="fixed", times=["02:30"], timezone="America/New_York"
    )
    assert next_run(schedule, datetime(2026, 3, 8, 5, tzinfo=UTC), "a") == datetime(
        2026, 3, 9, 6, 30, tzinfo=UTC
    )


@pytest.mark.parametrize("mode", ["discover", "refresh"])
@pytest.mark.parametrize("unavailable", [(), ("amazon_br", "pichau_br")])
async def test_scheduler_enqueues_and_advances_persisted_slot(mode, unavailable):
    row = {
        "id": 3,
        "public_id": uuid4(),
        "search_term_id": 7,
        "mode": mode,
        "schedule": {"kind": "interval", "interval_minutes": 15},
        "next_run_at": datetime.now(UTC) - timedelta(minutes=35),
    }
    result = MagicMock()
    result.mappings.return_value.all.return_value = [row]
    session = AsyncMock()
    session.execute.return_value = result
    await enqueue_schedules(session, unavailable)
    calls = session.execute.await_args_list
    assert "FOR UPDATE SKIP LOCKED" in str(calls[0].args[0])
    assert ("tracking_target_id" if mode == "refresh" else "search_term_id") in str(
        calls[1].args[0]
    )
    assert "ON CONFLICT DO NOTHING" in str(calls[1].args[0])
    assert "routine_search_term" in str(calls[1].args[0])
    # DISTINCT resolves untyped SELECT parameters as text before INSERT coercion.
    compiled = calls[1].args[0].compile(dialect=dialect())
    routine_pid_position = compiled.positiontup.index("routine_pid") + 1
    assert f"CAST(${routine_pid_position} AS UUID)" in str(compiled)
    assert calls[1].args[1] == {
        "routine": row["id"],
        "routine_pid": row["public_id"],
        "unavailable_sites": list(unavailable),
    }
    assert "ANY(CAST(:unavailable_sites AS text[]))" in str(calls[1].args[0])
    assert calls[2].args[1]["next"] == row["next_run_at"] + timedelta(minutes=45)
