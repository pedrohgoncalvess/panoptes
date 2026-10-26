import hashlib
from unittest.mock import AsyncMock

import pytest
from botocore.exceptions import ClientError
from panoptes_storage.client import ensure_bucket, store_bytes


async def test_binary_images_are_stored_with_exact_hash_and_content_type():
    client = AsyncMock()
    content = b"\x89PNG\r\n\x1a\nexample"
    asset = await store_bytes(
        client, "panoptes", content, kind="image", media_type="image/png"
    )
    assert asset.sha256 == hashlib.sha256(content).hexdigest()
    assert asset.uri.startswith("s3://panoptes/image/")
    client.put_object.assert_awaited_once()
    assert client.put_object.await_args.kwargs["Body"] == content
    assert client.put_object.await_args.kwargs["ContentType"] == "image/png"
    assert "ACL" not in client.put_object.await_args.kwargs


async def test_only_missing_bucket_triggers_creation():
    client = AsyncMock()
    client.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "403"}}, "HeadBucket"
    )
    with pytest.raises(ClientError):
        await ensure_bucket(client, "panoptes")
    client.create_bucket.assert_not_awaited()
    client.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "404"}}, "HeadBucket"
    )
    await ensure_bucket(client, "panoptes")
    client.create_bucket.assert_awaited_once_with(Bucket="panoptes")
