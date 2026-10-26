from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from panoptes_backend.catalog import repository as catalog_repository
from panoptes_backend.core.errors import ConflictError
from panoptes_backend.routines import repository, services
from panoptes_backend.routines.models import RoutineCreate, RoutineUpdate
from pydantic import ValidationError


@pytest.mark.parametrize("sites", [[], ["amazon"], ["terabyte", "amazon"]])
async def test_reject_sources_outside_first_extraction(monkeypatch, sites):
    monkeypatch.setattr(
        services,
        "routine_sources",
        AsyncMock(return_value=[{"site": "terabyte", "id": 1}]),
    )
    with pytest.raises(ConflictError):
        await services.selected_terms(object(), uuid4(), sites)


async def test_no_initial_extraction_cannot_create_selection(monkeypatch):
    monkeypatch.setattr(services, "routine_sources", AsyncMock(return_value=[]))
    with pytest.raises(ConflictError):
        await services.selected_terms(object(), uuid4(), ["terabyte"])


@pytest.mark.parametrize("model", [RoutineCreate, RoutineUpdate])
def test_empty_marketplaces_rejected_by_contract(model):
    extra = {"search_term_id": uuid4()} if model is RoutineCreate else {}
    with pytest.raises(ValidationError) as error:
        model(
            name="PC",
            sites=[],
            enabled=True,
            schedule={"kind": "interval", "interval_minutes": 60},
            **extra,
        )
    assert error.value.errors()[0]["loc"] == ("sites",)


async def test_create_one_routine_with_multiple_marketplaces(monkeypatch):
    term_id = uuid4()
    monkeypatch.setattr(
        services, "find_term", AsyncMock(return_value={"id": 7, "site": "terabyte"})
    )
    monkeypatch.setattr(
        services,
        "routine_sources",
        AsyncMock(
            return_value=[{"id": 7, "site": "terabyte"}, {"id": 8, "site": "kabum"}]
        ),
    )
    insert = AsyncMock()
    save = AsyncMock()
    monkeypatch.setattr(repository, "insert", insert)
    monkeypatch.setattr(repository, "set_terms", save)
    monkeypatch.setattr(
        repository,
        "read",
        AsyncMock(
            return_value={"search_term_id": term_id, "sites": ["terabyte", "kabum"]}
        ),
    )
    value = RoutineCreate(
        name="PC",
        search_term_id=term_id,
        sites=["terabyte", "kabum", "terabyte"],
        schedule={"kind": "interval", "interval_minutes": 60},
    )
    result = await services.create(object(), value)
    insert.assert_awaited_once()
    assert save.await_args.args[-1] == [7, 8]
    assert result["sites"] == ["terabyte", "kabum"]


async def test_update_marketplaces_and_preserve_when_only_pausing(monkeypatch):
    term_id = uuid4()
    monkeypatch.setattr(
        repository, "read", AsyncMock(return_value={"search_term_id": term_id})
    )
    monkeypatch.setattr(repository, "update", AsyncMock())
    save = AsyncMock()
    monkeypatch.setattr(repository, "set_terms", save)
    monkeypatch.setattr(
        services,
        "routine_sources",
        AsyncMock(
            return_value=[{"id": 7, "site": "terabyte"}, {"id": 8, "site": "kabum"}]
        ),
    )
    value = RoutineUpdate(
        name="PC",
        enabled=True,
        sites=["kabum"],
        schedule={"kind": "interval", "interval_minutes": 60},
    )
    await services.update(object(), uuid4(), value)
    assert save.await_args.args[-1] == [8]
    save.reset_mock()
    await services.update(
        object(), uuid4(), value.model_copy(update={"sites": None, "enabled": False})
    )
    save.assert_not_awaited()


async def test_availability_uses_first_discovery_batch_and_same_configuration():
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session.execute.return_value = result
    await catalog_repository.routine_sources(session, uuid4())
    sql = str(session.execute.await_args.args[0])
    assert "ORDER BY r.created_at,r.id LIMIT 1" in sql
    assert "f.correlation_id=r.correlation_id" in sql
    assert "normalized_term, configuration_key" in sql
