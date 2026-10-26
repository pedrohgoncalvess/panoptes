import hashlib
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from aiobotocore.session import get_session
from botocore.config import Config
from botocore.exceptions import ClientError
from panoptes_contracts.assets import StoredAsset


@dataclass(frozen=True)
class StorageSettings:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    public_endpoint: str


def load_storage_settings() -> StorageSettings:
    endpoint = os.environ["S3_ENDPOINT_URL"]
    return StorageSettings(
        endpoint,
        os.environ["S3_ACCESS_KEY"],
        os.environ["S3_SECRET_KEY"],
        os.getenv("S3_BUCKET", "panoptes"),
        os.getenv("S3_PUBLIC_ENDPOINT_URL", endpoint),
    )


@asynccontextmanager
async def create_storage(settings: StorageSettings, *, public: bool = False):
    async with get_session().create_client(
        "s3",
        endpoint_url=settings.public_endpoint if public else settings.endpoint,
        aws_access_key_id=settings.access_key,
        aws_secret_access_key=settings.secret_key,
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=10,
            read_timeout=30,
            retries={"max_attempts": 3},
        ),
    ) as client:
        yield client


async def ensure_bucket(client, bucket: str):
    try:
        await client.head_bucket(Bucket=bucket)
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("404", "NoSuchBucket", "NotFound"):
            raise
        try:
            await client.create_bucket(Bucket=bucket)
        except ClientError as create_error:
            if create_error.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                raise


async def store_bytes(
    client,
    bucket: str,
    data: bytes,
    *,
    kind: str,
    media_type: str,
    source_url: str | None = None,
) -> StoredAsset:
    sha = hashlib.sha256(data).hexdigest()
    key = f"{kind}/{sha[:2]}/{sha}"
    await client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType=media_type,
        Metadata={"sha256": sha},
    )
    return StoredAsset(
        public_id=uuid4(),
        kind=kind,
        bucket=bucket,
        object_key=key,
        sha256=sha,
        byte_qt=len(data),
        media_type=media_type,
        source_url=source_url,
    )
