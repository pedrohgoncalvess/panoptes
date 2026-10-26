import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from panoptes_contracts import HtmlSnapshot
from panoptes_database.session import unit_of_work
from panoptes_storage.client import store_bytes
from sqlalchemy import text

from . import capture_repository, queue_repository


async def store_asset(sessions, storage, bucket, request, owner, page, kind):
    digest = hashlib.sha256(page.body).hexdigest()
    key = f"{kind}/{digest[:2]}/{digest}"
    async with unit_of_work(sessions) as session:
        await queue_repository.guard(session, request["id"], owner)
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": bucket + "/" + key},
        )
        asset = await store_bytes(
            storage,
            bucket,
            page.body,
            kind=kind,
            media_type=page.media_type,
            source_url=page.source_url,
        )
        row = await capture_repository.save_asset(session, asset)
    return asset, row


async def capture_page(sessions, storage, bucket, request, owner, page):
    asset, asset_row = await store_asset(
        sessions, storage, bucket, request, owner, page, "html"
    )
    snapshot = HtmlSnapshot(
        public_id=uuid4(),
        source_url=page.source_url,
        final_url=page.final_url,
        captured_at=datetime.now(timezone.utc),
        sha256=asset.sha256,
        artifact_uri=asset.uri,
        byte_qt=asset.byte_qt,
        http_status=page.status,
        capture_mode=page.capture_mode,
        encoding=page.encoding,
    )
    async with unit_of_work(sessions) as session:
        await queue_repository.guard(session, request["id"], owner)
        snapshot_id = await capture_repository.save_snapshot(
            session, snapshot, asset_row["id"], request["id"]
        )
    return (
        snapshot,
        snapshot_id,
        {**asset_row, "kind": "html", "uri": asset.uri, "source_url": page.source_url},
    )


async def capture_image(sessions, storage, bucket, request, owner, image):
    asset, row = await store_asset(
        sessions, storage, bucket, request, owner, image, "image"
    )
    return {**row, "kind": "image", "uri": asset.uri, "source_url": image.source_url}
