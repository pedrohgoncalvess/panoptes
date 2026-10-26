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
        "minio",
        "minio-volume-init",
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
    assert (
        compose["services"]["minio"]["image"]
        == "minio/minio:RELEASE.2025-04-22T22-12-26Z"
    )
    assert (
        compose["services"]["workers"]["depends_on"]["minio"]["condition"]
        == "service_healthy"
    )


def test_published_ports_have_environment_defaults_and_public_s3_matches():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "compose.yaml").read_text())
    assert compose["services"]["backend"]["ports"] == [
        "127.0.0.1:${BACKEND_PORT:-8000}:8000"
    ]
    assert compose["services"]["postgres"]["ports"] == [
        "127.0.0.1:${POSTGRES_PORT:-5432}:5432"
    ]
    assert compose["services"]["minio"]["ports"] == [
        "127.0.0.1:${S3_PORT:-9000}:9000",
        "127.0.0.1:${MINIO_CONSOLE_PORT:-9001}:9001",
    ]
    assert (
        compose["services"]["backend"]["environment"]["S3_PUBLIC_ENDPOINT_URL"]
        == "http://localhost:${S3_PORT:-9000}"
    )
    frontend = compose["services"]["frontend"]
    assert frontend["ports"] == ["127.0.0.1:${FRONTEND_PORT:-3000}:3000"]
    assert frontend["environment"]["PANOPTES_API_URL"] == "http://backend:8000"
    assert frontend["depends_on"]["backend"]["condition"] == "service_healthy"
    assert frontend["build"]["dockerfile"] == "frontend/Dockerfile"
