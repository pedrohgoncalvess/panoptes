"""Yoyo is synchronous, isolated in a one-shot migration service."""

import os
from pathlib import Path

import psycopg
from yoyo import get_backend, read_migrations


def main():
    url = os.environ["MIGRATIONS_DATABASE_URL"]
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("MIGRATIONS_DATABASE_URL must use postgresql+psycopg")
    with psycopg.connect(
        url.replace("postgresql+psycopg://", "postgresql://", 1)
    ) as conn:
        conn.execute('CREATE SCHEMA IF NOT EXISTS "migration"')
    backend = get_backend(url + ("&" if "?" in url else "?") + "schema=migration")
    migrations = read_migrations(
        str(Path(os.getenv("MIGRATIONS_PATH", "/app/migrations/sql")))
    )
    try:
        with backend.lock():
            backend.apply_migrations(backend.to_apply(migrations))
    finally:
        backend.connection.close()


if __name__ == "__main__":
    main()
