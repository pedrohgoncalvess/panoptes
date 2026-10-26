from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth.router import current_user
from panoptes_backend.catalog.router import session_dependency
from panoptes_backend.main import create_app
from panoptes_backend.routines import repository, services


async def test_routine_create_configure_pause_and_delete(monkeypatch):
    term_id, public_id = uuid4(), uuid4()
    row = {
        "public_id": public_id,
        "name": "Book",
        "search_term_id": term_id,
        "mode": "refresh",
        "schedule": {"kind": "fixed", "times": ["08:00"]},
        "enabled": True,
    }
    monkeypatch.setattr(
        services,
        "find_term",
        AsyncMock(return_value={"id": 1, "public_id": term_id, "site": "terabyte"}),
    )
    monkeypatch.setattr(
        services,
        "routine_sources",
        AsyncMock(return_value=[{"id": 1, "site": "terabyte"}]),
    )
    monkeypatch.setattr(repository, "set_terms", AsyncMock())
    monkeypatch.setattr(repository, "insert", AsyncMock())
    monkeypatch.setattr(repository, "read", AsyncMock(return_value=row))
    monkeypatch.setattr(repository, "update", AsyncMock())
    monkeypatch.setattr(repository, "delete", AsyncMock())
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"name": "admin"}

    async def session():
        yield object()

    app.dependency_overrides[session_dependency] = session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            "/routines",
            json={
                "name": "Book",
                "search_term_id": str(term_id),
                "schedule": {"kind": "fixed", "times": ["08:00"]},
            },
        )
        assert result.status_code == 201 and "id" not in result.json()
        inserted = repository.insert.await_args.args
        assert inserted[1].mode == "refresh" and inserted[-1].tzinfo is not None
        result = await client.put(
            f"/routines/{public_id}",
            json={
                "name": "Book paused",
                "enabled": False,
                "schedule": {"kind": "random_daily", "times_per_day": 4},
            },
        )
        assert result.status_code == 200
        assert not repository.update.await_args.args[2].enabled
        result = await client.delete(f"/routines/{public_id}")
        assert result.status_code == 204
        repository.delete.assert_awaited_once()
        result = await client.post(
            "/routines",
            json={
                "name": "bad",
                "search_term_id": str(term_id),
                "schedule": {"kind": "interval", "interval_minutes": 0},
            },
        )
        assert result.status_code == 422


@pytest.mark.parametrize("outcome", ["ok", "changed", "missing"])
async def test_advance_routine_api(monkeypatch, outcome):
    public_id = uuid4()
    upcoming = datetime.now(UTC) + timedelta(hours=1)
    row = {"public_id": public_id, "next_run_at": upcoming, "enabled": True}
    monkeypatch.setattr(
        repository,
        "read",
        AsyncMock(return_value=None if outcome == "missing" else row),
    )
    advance = AsyncMock(return_value=public_id if outcome == "ok" else None)
    monkeypatch.setattr(repository, "advance", advance)
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"name": "admin"}

    async def session():
        yield object()

    app.dependency_overrides[session_dependency] = session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            f"/routines/{public_id}/advance", json={"next_run_at": upcoming.isoformat()}
        )
    assert result.status_code == {"ok": 200, "changed": 409, "missing": 404}[outcome]
    if outcome == "missing":
        advance.assert_not_awaited()
    else:
        assert advance.await_args.args[1:] == (public_id, upcoming)


async def test_scheduled_list_filters_and_orders_before_pagination():
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session.execute.return_value = result
    await repository.list_routines(session, 20, 40, scheduled=True)
    query, params = session.execute.await_args.args
    sql = str(query)
    assert "WHERE r.enabled" in sql
    assert "ORDER BY r.next_run_at,r.id LIMIT :limit OFFSET :offset" in sql
    assert "t.term,t.site" in sql
    assert params == {"limit": 20, "offset": 40}


async def test_advance_requires_same_future_slot_and_enabled_routine():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    public_id = uuid4()
    upcoming = datetime.now(UTC) + timedelta(hours=1)
    assert await repository.advance(session, public_id, upcoming) is None
    query, params = session.execute.await_args.args
    sql = str(query)
    assert "SET next_run_at=now()" in sql
    assert "AND enabled AND next_run_at=:expected" in sql
    assert "AND next_run_at > now()" in sql
    assert params == {"pid": public_id, "expected": upcoming}
