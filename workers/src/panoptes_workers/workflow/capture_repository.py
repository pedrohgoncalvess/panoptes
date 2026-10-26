from sqlalchemy import text


async def save_asset(session, asset):
    return (
        (
            await session.execute(
                text("""INSERT INTO "scraping"."asset"
        (public_id, kind, bucket, object_key, sha256, byte_qt, media_type, source_url)
        VALUES (:public_id, :kind, :bucket, :object_key, :sha256, :byte_qt, :media_type, :source_url)
        ON CONFLICT (bucket, object_key) DO UPDATE SET object_key = EXCLUDED.object_key
        RETURNING id, public_id"""),
                asset.model_dump(mode="json"),
            )
        )
        .mappings()
        .one()
    )


async def save_snapshot(session, snapshot, asset_id, request_id):
    values = snapshot.model_dump(mode="json")
    values["public_id"] = snapshot.public_id
    values["captured_at"] = snapshot.captured_at
    values["asset_id"] = asset_id
    values["request_id"] = request_id
    values["metadata"] = snapshot.model_dump_json()
    return (
        await session.execute(
            text("""INSERT INTO "scraping"."html_snapshot"
        (public_id, source_url, final_url, sha256, artifact_uri, capture_metadata, captured_at, asset_id, scrape_request_id)
        VALUES (:public_id, :source_url, :final_url, :sha256, :artifact_uri,
                CAST(:metadata AS jsonb), :captured_at, :asset_id, :request_id) RETURNING id"""),
            values,
        )
    ).scalar_one()


async def save_candidate(session, request_id, snapshot_id, validation):
    await session.execute(
        text("""INSERT INTO "scraping"."search_candidate"
        (scrape_request_id, html_snapshot_id, source_key, validation)
        VALUES (:request, :snapshot, :key, CAST(:validation AS jsonb))
        ON CONFLICT (scrape_request_id, source_key) DO NOTHING"""),
        {
            "request": request_id,
            "snapshot": snapshot_id,
            "key": validation.candidate.source_key,
            "validation": validation.model_dump_json(),
        },
    )


async def save_detail_validation(
    session, request_id, source_key, validation, snapshot_id
):
    await session.execute(
        text("""INSERT INTO "scraping"."product_validation"
        (scrape_request_id, html_snapshot_id, source_key, validation)
        VALUES (:request, :snapshot, :key, CAST(:validation AS jsonb))
        ON CONFLICT (scrape_request_id, html_snapshot_id) DO NOTHING"""),
        {
            "request": request_id,
            "snapshot": snapshot_id,
            "key": source_key,
            "validation": validation.model_dump_json(),
        },
    )
    await session.execute(
        text("""UPDATE "scraping"."search_candidate"
        SET detail_validation = CAST(:validation AS jsonb)
        WHERE scrape_request_id = :request AND source_key = :key"""),
        {
            "request": request_id,
            "key": source_key,
            "validation": validation.model_dump_json(),
        },
    )


async def observed_keys(session, request_id):
    result = await session.execute(
        text("""SELECT e.source_key FROM "scraping"."observation" o
        JOIN "scraping"."entity" e ON e.id = o.entity_id
        JOIN "scraping"."job" j ON j.id = o.job_id WHERE j.scrape_request_id = :id"""),
        {"id": request_id},
    )
    return set(result.scalars())
