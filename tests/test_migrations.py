import os
from pathlib import Path

import pytest
from yoyo import get_backend, read_migrations

ROOT = Path(__file__).resolve().parents[1]


def test_yoyo_loads_dependency_chain_and_rollback_files():
    folder = ROOT / "migrations/sql"
    migrations = read_migrations(str(folder))
    assert len(migrations) == len(
        [
            path
            for path in folder.glob("*.sql")
            if not path.name.endswith(".rollback.sql")
        ]
    )
    for migration in migrations:
        migration.load()
        assert migration.steps
        assert (folder / (migration.id + ".rollback.sql")).is_file()
        assert "DROP TABLE" not in Path(migration.path).read_text()


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "true",
    reason="Requires opt-in and empty disposable PostgreSQL",
)
def test_postgres_apply_vector_rollback_reapply():
    import psycopg

    url = os.environ["TEST_DATABASE_URL"]
    connection_url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(connection_url) as conn:
        existing = conn.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name IN ('ai', 'scraping')"
        ).fetchall()
        assert not existing, "Use an empty disposable test database"
        conn.execute('CREATE SCHEMA IF NOT EXISTS "migration"')
    backend = get_backend(url + ("&" if "?" in url else "?") + "schema=migration")
    migrations = read_migrations(str(ROOT / "migrations/sql"))
    try:
        with backend.lock():
            backend.apply_migrations(backend.to_apply(migrations))
        with psycopg.connect(connection_url) as conn:
            assert conn.execute("SELECT '[1,2,3]'::extensions.vector").fetchone()[0]
            assert conn.execute(
                'SELECT count(*) FROM "scraping"."html_cost"'
            ).fetchone() == (0,)
            for schema, table in [
                ("catalog", "product"),
                ("catalog", "variant"),
                ("catalog", "listing"),
                ("pricing", "offer"),
                ("pricing", "observation"),
                ("pricing", "promotion"),
                ("pricing", "payment_option"),
                ("pricing", "shipping_quote"),
            ]:
                assert conn.execute(
                    "SELECT to_regclass(%s)", (f'"{schema}"."{table}"',)
                ).fetchone()[0]
            assert (
                conn.execute("""SELECT numeric_precision,numeric_scale FROM information_schema.columns
                WHERE table_schema='pricing' AND table_name='observation' AND column_name='price_vl' """).fetchone()
                == (18, 4)
            )
        with backend.lock():
            backend.rollback_migrations(backend.to_rollback(migrations))
            backend.apply_migrations(backend.to_apply(migrations))
    finally:
        with backend.lock():
            backend.rollback_migrations(backend.to_rollback(migrations))
        backend.connection.close()
