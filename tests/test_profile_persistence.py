"""Profile configuration and taxonomy freezing against disposable PostgreSQL."""

import os
from uuid import uuid4

import pytest
from panoptes_backend.catalog.models import SearchTermCreate
from panoptes_backend.catalog.services import create_term
from panoptes_contracts.discovery import ProductMatchCriteria
from panoptes_database.config import DatabaseSettings
from panoptes_database.session import create_database
from sqlalchemy import text


@pytest.mark.integration
async def test_profiles_store_reference_attributes_and_allow_same_term_with_distinct_criteria():
    url = os.getenv("TEST_WORKFLOW_DATABASE_URL")
    if not url:
        pytest.skip("Requires disposable migrated PostgreSQL")
    engine, sessions = create_database(DatabaseSettings(url, 1, 2))
    try:
        async with sessions() as session:
            async with session.begin():
                term = "SSD " + uuid4().hex
                criteria = ProductMatchCriteria(
                    match_mode="profile",
                    category="hardware",
                    title="SSD",
                    brands=("Kingston",),
                    reference_price="550",
                    characteristics=(
                        {
                            "name": "Velocidade de gravação",
                            "value": "5",
                            "unit": "GB/s",
                            "operator": "gte",
                        },
                    ),
                )
                value = SearchTermCreate(term=term, criteria=criteria)
                first = await create_term(session, value)
                assert first["criteria"]["reference_price"] == "550"
                assert first["criteria"]["category_name"] == "Hardware"
                assert first["criteria"]["characteristics"][0]["unit"] == "GB/s"
                assert (
                    first["public_id"]
                    == (await create_term(session, value))["public_id"]
                )
                second = await create_term(
                    session,
                    value.model_copy(
                        update={
                            "criteria": criteria.model_copy(
                                update={"brands": ("Samsung",)}
                            )
                        }
                    ),
                )
                assert first["public_id"] != second["public_id"]
                from panoptes_backend.management.repository import (
                    extraction_groups,
                    extractions,
                )

                for item in (first, second):
                    await session.execute(
                        text(
                            "INSERT INTO scraping.scrape_request(mode,search_term_id) SELECT 'discover',id FROM scraping.search_term WHERE public_id=:id"
                        ),
                        {"id": item["public_id"]},
                    )
                groups = await extraction_groups(session, None, 100, 0)
                matching = [item for item in groups["items"] if item["term"] == term]
                assert len(matching) == 2
                for item in matching:
                    history = await extractions(
                        session, None, 100, 0, item["group_key"]
                    )
                    assert history["total"] == 1
                await session.execute(
                    text(
                        "UPDATE catalog.search_category SET name='Computação',keywords='[\"gpu\"]',active=false WHERE slug='hardware'"
                    )
                )
                frozen = SearchTermCreate(
                    site="mercado_livre_br", term=term, criteria=first["criteria"]
                )
                copied = await create_term(session, frozen, frozen=True)
                assert copied["criteria"]["category_name"] == "Hardware"
                assert "ssd" in copied["criteria"]["category_keywords"]
                await session.rollback()
    finally:
        await engine.dispose()
