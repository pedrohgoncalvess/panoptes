from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth.router import current_user
from panoptes_backend.catalog.router import session_dependency
from panoptes_backend.core.errors import NotFoundError
from panoptes_backend.main import create_app
from panoptes_backend.management import data_repository
from panoptes_backend.management.data_models import DataQuery


async def test_data_filters_validation_and_deletion_modes(monkeypatch):
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"name": "test"}
    marker = object()

    async def session():
        yield marker

    app.dependency_overrides[session_dependency] = session
    rows = AsyncMock(return_value=dict(items=[], total=0, limit=25, offset=0))
    remove = AsyncMock(return_value={"excluded": True})
    monkeypatch.setattr(data_repository, "rows", rows)
    monkeypatch.setattr(data_repository, "remove", remove)
    pid = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.get(
                "/data", params={"q": "SSD", "site": "kabum_br", "request_id": str(pid)}
            )
        ).status_code == 200
        rows.assert_awaited_once_with(
            marker,
            "SSD",
            "kabum_br",
            pid,
            25,
            0,
            filters=DataQuery(q="SSD", site="kabum_br", request_id=pid),
        )
        for query in (
            "limit=101",
            "offset=-1",
            "request_id=bad",
            "price_operator=gt",
            "price_operator=bad&price=10",
            "price_operator=between&price=20&price_to=10",
            "price_operator=gt&price=-1",
            "price_operator=eq&price=NaN",
        ):
            assert (await client.get("/data?" + query)).status_code == 422
        assert (await client.delete(f"/data/{pid}")).status_code == 200
        remove.assert_awaited_with(marker, pid, False)
        assert (await client.delete(f"/data/{pid}?purge=true")).status_code == 200
        remove.assert_awaited_with(marker, pid, True)


async def test_bulk_selection_validation_and_filter_contract(monkeypatch):
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"name": "test"}

    async def session():
        yield object()

    app.dependency_overrides[session_dependency] = session
    bulk = AsyncMock(return_value={"affected": 2, "action": "exclude"})
    monkeypatch.setattr(data_repository, "bulk_remove", bulk)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for body in (
            {"action": "purge", "expected_count": 1},
            {"action": "purge", "all_matching": True, "expected_count": 1},
            {"action": "purge", "ids": ["bad"], "expected_count": 1},
            {
                "action": "purge",
                "all_matching": True,
                "ids": [str(uuid4())],
                "filters": {},
                "expected_count": 1,
            },
        ):
            assert (await client.post("/data/bulk", json=body)).status_code == 422
        bulk.assert_not_awaited()
        response = await client.post(
            "/data/bulk",
            json={
                "action": "exclude",
                "all_matching": True,
                "filters": {
                    "price_operator": "between",
                    "price": "10.00",
                    "price_to": "20.00",
                },
                "excluded_ids": [str(uuid4())],
                "expected_count": 2,
            },
        )
        assert response.status_code == 200
        assert response.json()["affected"] == 2
        assert str(bulk.await_args.args[1].filters.price) == "10.00"


def session_results(*values):
    results = []
    for value in values:
        result = MagicMock()
        result.mappings.return_value.one_or_none.return_value = value
        result.scalar_one.return_value = value
        results.append(result)
    session = MagicMock()
    session.execute = AsyncMock(side_effect=results)
    return session


async def test_unknown_page_cannot_be_deleted():
    session = session_results(None, None)
    with pytest.raises(NotFoundError):
        await data_repository.remove(session, uuid4(), True)


async def test_purge_refuses_running_extractions_before_any_mutation():
    session = session_results(None, dict(id=1, site="amazon_br", source_key="book"), 1)
    with pytest.raises(HTTPException) as error:
        await data_repository.remove(session, uuid4(), True)
    assert error.value.status_code == 409
    assert not any(
        "DELETE" in str(call.args[0]) or "UPDATE" in str(call.args[0]).split("FOR")[0]
        for call in session.execute.await_args_list
    )


async def test_excluded_page_is_skipped_before_fetch(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from panoptes_workers.workflow import service

    session = session_results(1)

    @asynccontextmanager
    async def uow(_):
        yield session

    monkeypatch.setattr(service, "unit_of_work", uow)
    fetch = AsyncMock()
    monkeypatch.setattr(service, "fetch_page", fetch)
    candidate = SimpleNamespace(source_key="book")
    result = await service.extract_product(
        SimpleNamespace(sessions=None), {}, {"site": "amazon_br"}, None, candidate, None
    )
    assert result["status"] == "excluded"
    fetch.assert_not_awaited()


@pytest.mark.parametrize("referenced", [True, False])
async def test_physical_cleanup_preserves_shared_assets(monkeypatch, referenced):
    from contextlib import asynccontextmanager

    from panoptes_backend.management import storage_cleanup

    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {"bucket": "test", "object_key": "html/test"}
    ]
    reference = MagicMock()
    reference.scalar_one.return_value = referenced
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[result, MagicMock(), reference, MagicMock()]
    )

    @asynccontextmanager
    async def uow(_):
        yield session

    monkeypatch.setattr(storage_cleanup, "unit_of_work", uow)
    storage = AsyncMock()
    await storage_cleanup.flush(None, storage)
    if referenced:
        storage.delete_object.assert_not_awaited()
    else:
        storage.delete_object.assert_awaited_once_with(Bucket="test", Key="html/test")


async def test_physical_cleanup_failure_keeps_work_queued(monkeypatch):
    from contextlib import asynccontextmanager

    from panoptes_backend.management import storage_cleanup

    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {"bucket": "test", "object_key": "html/test"}
    ]
    reference = MagicMock()
    reference.scalar_one.return_value = False
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[result, MagicMock(), reference])

    @asynccontextmanager
    async def uow(_):
        yield session

    monkeypatch.setattr(storage_cleanup, "unit_of_work", uow)
    storage = AsyncMock()
    storage.delete_object.side_effect = OSError("storage unavailable")
    with pytest.raises(OSError):
        await storage_cleanup.flush(None, storage)
    assert not any(
        "DELETE FROM" in str(call.args[0]) for call in session.execute.await_args_list
    )
