from pathlib import Path

import yaml


def test_compose_services_wait_for_successful_migrations():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "compose.yaml").read_text())
    assert set(compose["services"]) == {
        "postgres",
        "backend",
        "workers",
        "migrations",
        "frontend",
    }
    for name in ("backend", "workers"):
        service = compose["services"][name]
        assert (
            service["depends_on"]["migrations"]["condition"]
            == "service_completed_successfully"
        )
        assert service["environment"]["DATABASE_URL"].startswith(
            "postgresql+asyncpg://"
        )
    assert ":latest" not in compose["services"]["postgres"]["image"]
    for name in ("backend", "workers"):
        service = compose["services"][name]
        assert "minio" not in service["depends_on"]
        assert (
            service["environment"]["S3_ENDPOINT_URL"]
            == "${S3_ENDPOINT_URL:-http://s3:9000}"
        )
        assert (
            service["environment"]["S3_ACCESS_KEY"]
            == "${S3_ACCESS_KEY:?Set S3_ACCESS_KEY}"
        )
        assert (
            service["environment"]["S3_SECRET_KEY"]
            == "${S3_SECRET_KEY:?Set S3_SECRET_KEY}"
        )
    assert "minio_data" not in compose["volumes"]


def test_published_ports_have_environment_defaults_and_public_s3_is_external():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "compose.yaml").read_text())
    assert compose["services"]["backend"]["ports"] == [
        "127.0.0.1:${BACKEND_PORT:-8000}:8000"
    ]
    assert compose["services"]["postgres"]["ports"] == [
        "127.0.0.1:${POSTGRES_PORT:-5432}:5432"
    ]
    assert (
        compose["services"]["backend"]["environment"]["S3_PUBLIC_ENDPOINT_URL"]
        == "${S3_PUBLIC_ENDPOINT_URL:-http://localhost:9000}"
    )
    frontend = compose["services"]["frontend"]
    assert frontend["ports"] == ["127.0.0.1:${FRONTEND_PORT:-3000}:3000"]
    assert frontend["environment"]["PANOPTES_API_URL"] == "http://backend:8000"
    assert frontend["depends_on"]["backend"]["condition"] == "service_healthy"
    assert frontend["build"]["dockerfile"] == "frontend/Dockerfile"
