import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseSettings:
    url: str
    pool_min: int
    pool_max: int


def load_database_settings() -> DatabaseSettings:
    url = os.environ["DATABASE_URL"]
    low = int(os.getenv("DB_POOL_MIN", "2"))
    high = int(os.getenv("DB_POOL_MAX", "10"))
    if not url.startswith("postgresql+asyncpg://"):
        raise ValueError("DATABASE_URL must use postgresql+asyncpg")
    if low <= 0 or high < low:
        raise ValueError("Require DB_POOL_MAX >= DB_POOL_MIN > 0")
    return DatabaseSettings(url=url, pool_min=low, pool_max=high)
