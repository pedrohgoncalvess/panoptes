from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth.router import current_user
from panoptes_backend.main import create_app


async def test_contract_api_works_without_extraction_or_database():
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"name": "admin"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/contracts")
        assert response.status_code == 200
        assert "ExtractionJob" in response.json()["contracts"]
        schema = await client.get("/contracts/ExtractionJob")
        assert schema.json()["type"] == "object"
        missing = await client.get("/contracts/missing")
        assert missing.status_code == 404
        assert set(missing.json()) == {"detail", "code", "correlation_id"}
        assert missing.headers["X-Correlation-ID"] == missing.json()["correlation_id"]
