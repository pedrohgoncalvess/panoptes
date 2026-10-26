from contextlib import asynccontextmanager

from .config import DatabaseSettings


def create_database(settings: DatabaseSettings):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(
        settings.url,
        pool_size=settings.pool_min,
        max_overflow=settings.pool_max - settings.pool_min,
        pool_pre_ping=True,
        pool_timeout=30,
        connect_args={"server_settings": {"timezone": "America/Sao_Paulo"}},
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def unit_of_work(session_factory):
    async with session_factory() as session:
        async with session.begin():
            yield session
