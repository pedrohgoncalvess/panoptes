from unittest.mock import AsyncMock, MagicMock

import pytest
from panoptes_database.config import load_database_settings
from panoptes_database.session import unit_of_work


@pytest.mark.parametrize("low,high", [("0", "10"), ("2", "1")])
def test_invalid_pool_fails_at_startup(monkeypatch, low, high):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/postgres"
    )
    monkeypatch.setenv("DB_POOL_MIN", low)
    monkeypatch.setenv("DB_POOL_MAX", high)
    with pytest.raises(ValueError):
        load_database_settings()


async def test_unit_of_work_gives_transaction_context_exception():
    session = MagicMock()
    transaction = session.begin.return_value
    transaction.__aenter__ = AsyncMock()
    transaction.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    with pytest.raises(RuntimeError):
        async with unit_of_work(factory):
            raise RuntimeError("rollback")
    assert transaction.__aexit__.await_args.args[0] is RuntimeError
