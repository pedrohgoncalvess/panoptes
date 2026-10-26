from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from panoptes_contracts import ExtractionJob, HtmlSnapshot


@pytest.fixture
def job():
    return ExtractionJob(
        public_id=uuid4(),
        correlation_id=uuid4(),
        routine_id=uuid4(),
        routine_version="1",
        parser_slug="amazon",
        parser_version="0.1.0",
        idempotency_key="routine-1:capture-1:parser-1",
        snapshot=HtmlSnapshot(
            public_id=UUID("00000000-0000-4000-8000-000000000001"),
            source_url="https://www.amazon.com.br/synthetic/product-001",
            final_url="https://www.amazon.com.br/synthetic/product-001",
            captured_at=datetime.now(timezone.utc),
            sha256="a" * 64,
            artifact_uri="file:///artifacts/demo.html",
            byte_qt=100,
            http_status=200,
            capture_mode="http",
        ),
    )
