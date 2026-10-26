from unittest.mock import AsyncMock

import pytest
from panoptes_workers.backfill_commerce import capture_html


class ChunkedBody:
    def __init__(self, body):
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def read(self, size=-1):
        return self.body if size == -1 else self.body[:12]


async def test_reads_complete_chunked_capture_including_late_product_dom():
    html = (
        b"<html><head>"
        + b" " * 10000
        + b'</head><div id="pixPrice">R$ 90,00 no Pix</div></html>'
    )
    storage = AsyncMock()
    storage.get_object.return_value = {
        "ContentLength": len(html),
        "Body": ChunkedBody(html),
    }
    assert await capture_html(storage, "s3://test/html/product") == html


async def test_rejects_truncated_or_oversized_captures():
    storage = AsyncMock()
    storage.get_object.return_value = {
        "ContentLength": 100,
        "Body": ChunkedBody(b"partial"),
    }
    with pytest.raises(ValueError, match="incomplete_capture"):
        await capture_html(storage, "s3://test/html/product")
    storage.get_object.return_value = {
        "ContentLength": 6_000_001,
        "Body": ChunkedBody(b"partial"),
    }
    with pytest.raises(ValueError, match="capture_too_large"):
        await capture_html(storage, "s3://test/html/product")
