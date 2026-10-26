from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from panoptes_backend.catalog import repository, router
from panoptes_storage import client


@pytest.mark.parametrize("kind", ["html", "image"])
async def test_html_capture_download_is_attachment_and_signature_expires(
    monkeypatch, kind
):
    asset_id = uuid4()
    monkeypatch.setattr(
        repository,
        "read_asset",
        AsyncMock(
            return_value={"bucket": "panoptes", "object_key": "html/test", "kind": kind}
        ),
    )
    storage = AsyncMock()
    storage.generate_presigned_url.return_value = "https://storage.example/capture"

    @asynccontextmanager
    async def fake_storage(*args, **kwargs):
        yield storage

    monkeypatch.setattr(client, "create_storage", fake_storage)
    monkeypatch.setattr(client, "load_storage_settings", lambda: object())
    result = await router.asset_url(asset_id, object())
    args = storage.generate_presigned_url.await_args.kwargs
    assert args["ExpiresIn"] == 300
    assert result["expires_in_seconds"] == 300
    if kind == "html":
        assert (
            args["Params"]["ResponseContentDisposition"]
            == f'attachment; filename="panoptes-{asset_id}.html"'
        )
    else:
        assert "ResponseContentDisposition" not in args["Params"]
