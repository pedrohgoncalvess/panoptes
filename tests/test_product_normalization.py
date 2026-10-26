import json
from unittest.mock import AsyncMock, Mock

import pytest
from panoptes_workers.normalization import (
    Normalization,
    evidence_input,
    identity,
    infer,
    process_one,
)
from panoptes_workers.workflow.catalog_repository import fingerprint


def normalized(storage="16 GB", **overrides):
    return Normalization.model_validate(
        {
            "name": f"Kindle {storage}",
            "category": "ereader",
            "brand": "Amazon",
            "model": "Kindle",
            "attributes": [
                {"name": "storage_gb", "value": storage, "evidence": storage},
                {"name": "generation", "value": "11", "evidence": "11ª geração"},
            ],
            "missing": [],
            "confidence": 0.98,
            "reason": "Capacidade e geração confirmadas.",
            **overrides,
        }
    )


def reply(result):
    return {"choices": [{"message": {"content": result.model_dump_json()}}]}


def source(color="preto", storage="16 GB"):
    return {
        "entity": {"title": f"Amazon Kindle {storage} {color} 11ª geração"},
        "catalog": None,
        "specifications": {"Armazenamento": storage},
    }


async def test_three_marketplaces_and_different_colors_share_identity():
    client = Mock(invoke=AsyncMock(return_value=reply(normalized())))
    results = [
        await infer(client, source(color), context={"site": site})
        for site, color in [
            ("amazon_br", "preto"),
            ("mercado_livre_br", "azul"),
            ("terabyte_br", "branco"),
        ]
    ]
    assert len({fingerprint(identity(r)) for r in results}) == 1
    assert client.invoke.await_count == 3
    assert all(
        call.args[0] == "product_normalizer" for call in client.invoke.await_args_list
    )


def test_storage_generation_and_product_line_remain_separate():
    base = fingerprint(identity(normalized()))
    other_generation = normalized().model_dump()
    other_generation["attributes"][1]["value"] = "12"
    for different in [
        normalized("32 GB"),
        normalized(model="Kindle Paperwhite"),
        Normalization.model_validate(other_generation),
    ]:
        assert fingerprint(identity(different)) != base
    # Display names and field ordering never determine the canonical identity.
    assert fingerprint(identity(normalized(name="Outro título"))) == base
    assert fingerprint(identity(normalized(brand=" AMAZON "))) == base


async def test_invented_attribute_evidence_is_rejected():
    client = Mock(invoke=AsyncMock(return_value=reply(normalized("32 GB"))))
    with pytest.raises(ValueError, match="evidence_invalid"):
        await infer(client, source(), context={})


async def test_kindle_without_capacity_cannot_be_grouped_even_if_model_is_confident():
    result = normalized(attributes=[])
    client = Mock(invoke=AsyncMock(return_value=reply(result)))
    output = await infer(client, source(), context={})
    assert "storage_gb" in output.missing


def test_condition_changes_invalidate_normalization():
    new = {**source(), "offer": {"condition": "new"}}
    used = {**source(), "offer": {"condition": "used"}}
    assert evidence_input(new) != evidence_input(used)


def test_duplicate_and_cosmetic_attributes_are_rejected():
    attribute = {"name": "color", "value": "black", "evidence": "black"}
    with pytest.raises(ValueError, match="cosmetic"):
        normalized(attributes=[attribute])
    attribute["name"] = "storage_gb"
    with pytest.raises(ValueError, match="duplicate"):
        normalized(attributes=[attribute, attribute])


def test_price_images_and_retailer_ids_do_not_invalidate_identity():
    payload = {**source(), "offer": {"price": "100"}, "assets": ["image1"]}
    first = evidence_input(payload)
    payload.update(offer={"price": "200"}, assets=["image2"])
    payload["entity"].update(source_key="another-key", url="https://example.com")
    assert evidence_input(payload) == first
    payload["specifications"]["Armazenamento"] = "32 GB"
    assert json.dumps(evidence_input(payload)) != json.dumps(evidence_input(source()))


def fake_sessions(monkeypatch, responses):
    from contextlib import asynccontextmanager

    session = Mock(execute=AsyncMock(side_effect=responses))

    @asynccontextmanager
    async def work(_):
        yield session

    monkeypatch.setattr("panoptes_workers.normalization.unit_of_work", work)
    return session


def scalar(value):
    return Mock(
        scalar_one=Mock(return_value=value), scalar_one_or_none=Mock(return_value=value)
    )


def claimed():
    row = {"listing_id": 1, "input": source(), "input_hash": "hash", "attempts": 1}
    return Mock(mappings=Mock(return_value=Mock(one_or_none=Mock(return_value=row))))


@pytest.mark.parametrize("uncertain", [False, True])
async def test_queue_links_only_complete_identities(monkeypatch, uncertain):
    result = normalized(missing=["generation"] if uncertain else [])
    client = Mock(invoke=AsyncMock(return_value=reply(result)))
    responses = [claimed(), scalar(1)]
    if not uncertain:
        responses.append(scalar(42))
        responses.append(
            Mock()
        )  # Enqueue taxonomy on the reused/new canonical product.
    responses.append(Mock())
    session = fake_sessions(monkeypatch, responses)
    assert await process_one(None, client)
    writes = session.execute.await_args_list
    params = writes[-1].args[1]
    assert params["status"] == ("uncertain" if uncertain else "completed")
    assert params["canonical"] == (None if uncertain else 42)
    if not uncertain:
        assert "ON CONFLICT(identity_key)" in str(writes[-3].args[0])
        assert "catalog.taxonomy_task" in str(writes[-2].args[0])


async def test_new_capture_prevents_stale_assignment(monkeypatch):
    session = fake_sessions(monkeypatch, [claimed(), scalar(None)])
    client = Mock(invoke=AsyncMock(return_value=reply(normalized())))
    assert await process_one(None, client)
    assert session.execute.await_count == 2


async def test_failed_inference_retries_without_assigning(monkeypatch):
    session = fake_sessions(monkeypatch, [claimed(), Mock()])
    client = Mock(invoke=AsyncMock(side_effect=RuntimeError("provider unavailable")))
    assert await process_one(None, client)
    query = str(session.execute.await_args.args[0])
    assert "status='failed'" in query and "available_at" in query
    assert "canonical_product_id" not in query
