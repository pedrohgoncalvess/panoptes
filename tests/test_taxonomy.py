import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from jsonschema import validate
from panoptes_backend.auth.router import current_user
from panoptes_backend.catalog.router import session_dependency
from panoptes_backend.main import create_app
from panoptes_contracts.taxonomy import Classification, TaxonEdit
from panoptes_database import taxonomy as repository
from panoptes_workers import taxonomy as worker


def node(name, parent=None, **changes):
    return {"id": uuid4(), "name": name, "parent_id": parent, "active": True, **changes}


def choice(name, node_id=None, **changes):
    return {
        "id": str(node_id) if node_id else None,
        "name": name,
        "evidence": "SSD",
        "creation_reason": "Tipo durável sem equivalente nas classificações disponíveis.",
        "exceptional": False,
        **changes,
    }


def category(name, node_id=None, children=(), **changes):
    return {**choice(name, node_id, **changes), "subcategories": list(children)}


def classification(*categories, confidence=0.98):
    return Classification.model_validate(
        {
            "categories": list(categories),
            "confidence": confidence,
            "reason": "Componente de armazenamento identificado.",
        }
    )


def policy(**changes):
    return {
        "category_target": 20,
        "subcategory_target": 200,
        "allow_creation": True,
        **changes,
    }


def test_multilabel_includes_parents_and_creates_unseeded_subcategories():
    hardware, electronics = node("Hardware"), node("Eletrônicos")
    result = classification(
        category(
            "Hardware", hardware["id"], [choice("Armazenamento"), choice("Componentes")]
        ),
        category("Eletrônicos", electronics["id"]),
    )
    selected, created = repository.resolve_choices(
        result, [hardware, electronics], policy()
    )
    assert len(selected) == 4 and len(created) == 2
    assert {hardware["id"], electronics["id"]} <= selected
    assert all(n["parent_id"] == hardware["id"] for n in created)


def test_equivalent_spelling_and_concurrent_creation_reuse_existing_nodes():
    root = node("Eletrônicos")
    child = node("Leitores digitais", root["id"])
    result = classification(
        category(" ELETRONICOS ", children=[choice("Leitores-digitais")])
    )
    selected, created = repository.resolve_choices(result, [root, child], policy())
    assert selected == {root["id"], child["id"]} and created == []


def test_duplicate_proposals_create_only_one_node():
    result = classification(
        category("Livros", children=[choice("Programação"), choice("programacao")])
    )
    selected, created = repository.resolve_choices(result, [], policy())
    assert len(created) == len(selected) == 2


async def test_batch_crossing_target_never_creates_partial_taxonomy():
    root = node("Hardware")
    result = classification(category("Livros"), category("Esportes"))
    session = Mock(execute=AsyncMock())
    with pytest.raises(ValueError, match="Meta atingida"):
        await repository.apply_classification(
            session, 7, result, [root], policy(category_target=2)
        )
    session.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "target,category_count,subcategory_count",
    [("category_target", 1, 100), ("subcategory_target", 100, 1)],
)
def test_target_requires_exception_for_each_new_node(
    target, category_count, subcategory_count
):
    root = node("Hardware")
    child = node("Armazenamento", root["id"])
    new = (
        category("Outro domínio")
        if target == "category_target"
        else category("Hardware", root["id"], [choice("Outra função")])
    )
    with pytest.raises(ValueError, match="Meta atingida"):
        repository.resolve_choices(
            classification(new),
            [root, child],
            policy(
                category_target=category_count, subcategory_target=subcategory_count
            ),
        )


@pytest.mark.parametrize(
    "exceptional,confidence,reason,allowed",
    [
        (
            True,
            0.98,
            "Domínio ausente: as opções existentes descrevem componentes ou eletrodomésticos, não vestuário.",
            True,
        ),
        (
            False,
            0.98,
            "Domínio ausente, sem categoria compatível entre as opções existentes.",
            False,
        ),
        (
            True,
            0.94,
            "Domínio ausente, sem categoria compatível entre as opções existentes.",
            False,
        ),
        (True, 0.98, "Novo tipo", False),
    ],
)
def test_soft_target_allows_only_justified_confident_exceptions(
    exceptional, confidence, reason, allowed
):
    result = classification(
        category("Vestuário", exceptional=exceptional, creation_reason=reason),
        confidence=confidence,
    )
    if allowed:
        _, created = repository.resolve_choices(
            result, [node("Hardware")], policy(category_target=1)
        )
        assert created[0]["name"] == "Vestuário"
    else:
        with pytest.raises(ValueError, match="Meta atingida"):
            repository.resolve_choices(
                result, [node("Hardware")], policy(category_target=1)
            )


def test_creation_disabled_still_reuses_existing_nodes():
    root = node("Hardware")
    selected, created = repository.resolve_choices(
        classification(category("Hardware", root["id"])),
        [root],
        policy(allow_creation=False),
    )
    assert selected == {root["id"]} and not created
    with pytest.raises(ValueError, match="desativada"):
        repository.resolve_choices(
            classification(category("Livros")), [root], policy(allow_creation=False)
        )


def test_inactive_nodes_invalid_ids_and_wrong_parent_cannot_be_selected():
    root, another = node("Hardware"), node("Eletrônicos")
    child = node("SSD", root["id"])
    for result, nodes in [
        (classification(category("Hardware", uuid4())), [root]),
        (classification(category("Hardware", root["id"])), [{**root, "active": False}]),
        (
            classification(
                category("Eletrônicos", another["id"], [choice("SSD", child["id"])])
            ),
            [root, another, child],
        ),
    ]:
        with pytest.raises(ValueError):
            repository.resolve_choices(result, nodes, policy())


async def test_inference_quotes_product_evidence_not_taxonomy_labels():
    root = node("Hardware")
    result = classification(category("Hardware", root["id"]))
    client = Mock(
        invoke=AsyncMock(
            return_value={
                "choices": [{"message": {"content": result.model_dump_json()}}]
            }
        )
    )
    evidence = {"name": "SSD NVMe", "identity": {}, "source": {}}
    assert await worker.infer(client, evidence, [root], policy(), context={}) == result
    content = json.loads(client.invoke.await_args.args[1])
    assert content["taxonomy"][0]["id"] == str(root["id"])
    assert content["counts"] == {"categories": 1, "subcategories": 0}
    invalid = classification(category("Hardware", root["id"], evidence="Hardware"))
    client.invoke.return_value = {
        "choices": [{"message": {"content": invalid.model_dump_json()}}]
    }
    with pytest.raises(ValueError, match="Evidência"):
        await worker.infer(client, evidence, [root], policy(), context={})


def test_checked_in_schema_matches_contract():
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "agents/taxonomy_normalizer/output.schema.json"
        ).read_text()
    )
    validate(classification(category("Hardware")).model_dump(mode="json"), schema)
    assert schema == Classification.model_json_schema()


async def test_stale_worker_cannot_overwrite_manual_classification(monkeypatch):
    root = node("Hardware")
    row = {"product_id": 7, "evidence": {"name": "SSD"}, "attempts": 1}
    claimed = Mock(mappings=Mock(return_value=Mock(one_or_none=Mock(return_value=row))))
    session = Mock(
        execute=AsyncMock(
            side_effect=[claimed, Mock(scalar_one_or_none=Mock(return_value=None))]
        )
    )

    @asynccontextmanager
    async def work(_):
        yield session

    monkeypatch.setattr(worker, "unit_of_work", work)
    monkeypatch.setattr(repository, "nodes", AsyncMock(return_value=[root]))
    monkeypatch.setattr(repository, "policy", AsyncMock(return_value=policy()))
    monkeypatch.setattr(repository, "lock", AsyncMock())
    apply = AsyncMock()
    monkeypatch.setattr(repository, "apply_classification", apply)
    monkeypatch.setattr(
        worker,
        "infer",
        AsyncMock(return_value=classification(category("Hardware", root["id"]))),
    )
    assert await worker.process_one(None, None)
    apply.assert_not_awaited()


@pytest.mark.parametrize("low_confidence", [True, False])
async def test_ambiguous_and_disallowed_creation_go_to_review(
    monkeypatch, low_confidence
):
    root = node("Hardware")
    row = {"product_id": 7, "evidence": {"name": "SSD"}, "attempts": 1}
    claimed = Mock(mappings=Mock(return_value=Mock(one_or_none=Mock(return_value=row))))
    current = Mock(scalar_one_or_none=Mock(return_value=7))
    session = Mock(execute=AsyncMock(side_effect=[claimed, current, Mock()]))

    @asynccontextmanager
    async def work(_):
        yield session

    monkeypatch.setattr(worker, "unit_of_work", work)
    monkeypatch.setattr(repository, "nodes", AsyncMock(return_value=[root]))
    monkeypatch.setattr(repository, "policy", AsyncMock(return_value=policy()))
    monkeypatch.setattr(repository, "lock", AsyncMock())
    apply = AsyncMock(side_effect=ValueError("Meta atingida"))
    monkeypatch.setattr(repository, "apply_classification", apply)
    result = classification(
        category("Hardware", root["id"]), confidence=0.7 if low_confidence else 0.98
    )
    monkeypatch.setattr(worker, "infer", AsyncMock(return_value=result))
    assert await worker.process_one(None, None)
    params = session.execute.await_args.args[1]
    assert params["status"] == "needs_review"
    if low_confidence:
        apply.assert_not_awaited()
    else:
        assert json.loads(params["result"])["review_reason"] == "Meta atingida"


async def test_manual_assignment_adds_parent_and_protects_against_agent(monkeypatch):
    root = node("Hardware")
    child = node("Armazenamento", root["id"])
    session = Mock(
        execute=AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=7)))
    )
    monkeypatch.setattr(repository, "lock", AsyncMock())
    monkeypatch.setattr(repository, "nodes", AsyncMock(return_value=[root, child]))
    replace = AsyncMock()
    monkeypatch.setattr(repository, "replace_memberships", replace)
    await repository.manual_assignment(session, uuid4(), [child["id"]])
    replace.assert_awaited_once_with(session, 7, {root["id"], child["id"]})
    sql = str(session.execute.await_args.args[0])
    assert "status='manual'" in sql and "lease_token=NULL" in sql


async def test_manual_rename_preserves_id_and_prevents_duplicates(monkeypatch):
    root = node("Hardware")
    session = Mock(execute=AsyncMock())
    monkeypatch.setattr(repository, "lock", AsyncMock())
    monkeypatch.setattr(repository, "nodes", AsyncMock(return_value=[root]))
    assert (
        await repository.save_node(session, root["id"], TaxonEdit(name="Componentes"))
        == root["id"]
    )
    assert "UPDATE catalog.taxon" in str(session.execute.await_args.args[0])
    with pytest.raises(ValueError, match="Já existe"):
        await repository.save_node(session, None, TaxonEdit(name="HARDWARE"))


@pytest.mark.parametrize(
    "path,method,body",
    [
        ("/admin/taxonomy", "POST", {"name": "Esportes"}),
        ("/admin/taxonomy/policy", "PUT", policy()),
        ("/admin/taxonomy/products", "GET", None),
    ],
)
async def test_taxonomy_management_requires_admin(path, method, body):
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {"role": "user"}
    session = Mock(execute=AsyncMock())

    async def dependency():
        yield session

    app.dependency_overrides[session_dependency] = dependency
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.request(method, path, json=body)).status_code == 403
    session.execute.assert_not_awaited()


async def test_public_taxonomy_requires_authentication():
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        assert (await client.get("/catalog/taxonomy")).status_code == 401
