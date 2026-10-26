import json
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from panoptes_backend.catalog import repository, services
from panoptes_backend.catalog.models import SearchTermCreate
from panoptes_contracts.discovery import ProductMatchCriteria, TrackedCandidate
from panoptes_workers.amazon.product import parse_catalog_product
from panoptes_workers.common.intent import qualify_intent
from panoptes_workers.infrastructure.selection_llm import (
    ProductClassifier,
    product_fields,
)
from panoptes_workers.workflow import queue_repository, schedules
from pydantic import ValidationError


def product(title="AMD Ryzen 7 5700X3D", description="8 núcleos, 16 threads"):
    detail = parse_catalog_product(
        f'<h1 id="productTitle">{title}</h1><div id="productDescription">{description}</div>'
        '<div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">R$ 1.199,98</span></span></div>',
        "https://www.amazon.com.br/dp/B09VCHQHZ6",
        "B09VCHQHZ6",
    )
    candidate = TrackedCandidate(
        title=title,
        url=detail.entity.url,
        source_key=detail.entity.source_key,
    )
    return candidate, detail


def criteria(description=""):
    return ProductMatchCriteria(
        match_mode="intent", query="Ryzen 7", description=description
    )


def response(checks):
    return {"choices": [{"message": {"content": json.dumps({"checks": checks})}}]}


def check(requirement="query", status="matched", excerpt="Ryzen 7 5700X3D"):
    return dict(
        requirement=requirement,
        status=status,
        field="title",
        excerpt=excerpt,
        explanation="Família e modelo identificados no produto.",
    )


def classifier(monkeypatch, payload):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("PRODUCT_CLASSIFIER_ENABLED", "true")
    client = Mock(invoke=AsyncMock(return_value=payload))
    return ProductClassifier(client), client


def test_new_request_only_requires_search_and_freezes_optional_description():
    value = SearchTermCreate(
        term=" Ryzen 7 ",
        description=" processador avulso da linha 3d ",
        reference_price="1500",
    )
    assert value.criteria.query == "Ryzen 7"
    assert value.criteria.description == "processador avulso da linha 3d"
    assert value.criteria.category is None
    assert value.criteria.reference_price == Decimal("1500")
    assert SearchTermCreate(term="Ryzen 7").criteria.description == ""
    assert SearchTermCreate.model_json_schema()["required"] == ["term"]


@pytest.mark.parametrize(
    "data",
    [
        {"term": " "},
        {"term": 7},
        {"term": "Ryzen 7", "description": None},
        {"term": "Ryzen 7", "description": "a" * 1001},
    ],
)
def test_bad_mapping_requests_are_validation_errors(data):
    with pytest.raises(ValidationError):
        SearchTermCreate.model_validate(data)


def test_search_cards_never_reject_before_detail_and_fallback_keeps_uncertainty():
    candidate, detail = product("Processador AMD Ryzen 5 5500")
    assert qualify_intent(candidate, criteria()).decision == "accepted"
    assert qualify_intent(candidate, criteria(), detail=detail).decision == "uncertain"
    candidate, detail = product()
    assert qualify_intent(candidate, criteria(), detail=detail).decision == "uncertain"
    assert (
        qualify_intent(candidate, criteria("avulso 3d"), detail=detail).decision
        == "uncertain"
    )
    candidate, detail = product("Kit upgrade Ryzen 7 5700X3D B550")
    assert qualify_intent(candidate, criteria(), detail=detail).decision == "rejected"


@pytest.mark.parametrize(
    "title",
    [
        "Pichau Kit upgrade, AMD Ryzen 7 8700F, B650M DDR5",
        "Computador Ryzen 7 5700G 16GB SSD",
        "Notebook Lenovo AMD Ryzen 7 5700U",
        "Placa-mãe AM4 para Ryzen 7",
    ],
)
async def test_component_search_cannot_approve_a_bundle_even_if_provider_does(
    monkeypatch, title
):
    candidate, detail = product(title)
    engine, client = classifier(monkeypatch, response([check(excerpt=title)]))
    result = await engine.classify(candidate, criteria(), detail)
    assert result.decision == "rejected"
    assert result.reason == "product_type_mismatch"
    client.invoke.assert_not_awaited()


@pytest.mark.parametrize(
    "title,query,exclude_accessories",
    [
        ("Processador Ryzen 7 5700 com cooler", "Ryzen 7", True),
        ("Processador Ryzen 7 9700X sem cooler", "Ryzen 7", True),
        ("Kit upgrade Ryzen 7 5700X B550", "kit Ryzen 7", True),
        ("Kit upgrade Ryzen 7 5700X B550", "Ryzen 7", False),
    ],
)
def test_type_guard_preserves_processors_and_explicit_bundle_searches(
    title, query, exclude_accessories
):
    candidate, detail = product(title)
    requested = criteria().model_copy(
        update={"query": query, "exclude_accessories": exclude_accessories}
    )
    assert qualify_intent(candidate, requested, detail=detail).decision != "rejected"


async def test_repeated_consistent_query_checks_are_normalized(monkeypatch):
    candidate, detail = product()
    duplicate = {**check(), "explanation": "O modelo pertence à família pedida."}
    engine, _ = classifier(monkeypatch, response([check(), duplicate]))
    result = await engine.classify(candidate, criteria(), detail)
    assert result.decision == "accepted"
    assert len(result.checks) == 1


def test_natural_language_description_defers_product_type_to_classifier():
    candidate, detail = product("Notebook Lenovo AMD Ryzen 7 5700U")
    assert (
        qualify_intent(
            candidate, criteria("notebook com Ryzen 7"), detail=detail
        ).decision
        == "uncertain"
    )


async def test_unrequested_description_check_does_not_invalidate_query(monkeypatch):
    candidate, detail = product()
    engine, _ = classifier(
        monkeypatch,
        response([check(), check("description", status="missing", excerpt="")]),
    )
    result = await engine.classify(candidate, criteria(), detail)
    assert result.decision == "accepted"
    assert len(result.checks) == 1


@pytest.mark.parametrize(
    "second",
    [
        check(status="mismatch"),
        check(status="missing", excerpt=""),
        check(excerpt="inventado"),
    ],
)
async def test_conflicting_or_unverified_duplicates_stay_uncertain(monkeypatch, second):
    candidate, detail = product()
    engine, _ = classifier(monkeypatch, response([check(), second]))
    result = await engine.classify(candidate, criteria(), detail)
    assert result.decision == "uncertain"
    assert result.reason == "classifier_failed"


async def test_classifier_interprets_description_and_cites_verified_fields(monkeypatch):
    candidate, detail = product()
    engine, client = classifier(
        monkeypatch,
        response(
            [
                check(),
                check("description", excerpt="AMD Ryzen 7 5700X3D"),
            ]
        ),
    )
    result = await engine.classify(
        candidate,
        criteria("processador avulso da linha 3d"),
        detail,
        context={"scrape_request_id": 123},
    )
    assert result.decision == "accepted"
    assert result.validator_version == "product_classifier/1.0.0"
    assert len(result.checks) == 2
    call = client.invoke.await_args
    sent = json.loads(call.args[1])
    assert sent["description"] == "processador avulso da linha 3d"
    assert sent["product"]["title"] == detail.entity.title
    assert "price" not in sent["product"]
    assert call.kwargs["context"] == {"scrape_request_id": 123}
    assert detail.offer.price == Decimal("1199.98")


@pytest.mark.parametrize(
    "checks",
    [
        [check()],  # The description was not evaluated.
        [check(), check("description", excerpt="fabricated model X3D")],
        [check(), check()],  # Duplicate requirements cannot approve a description.
        [check(), check("description", excerpt="")],
    ],
)
async def test_incomplete_or_fabricated_evidence_never_approves(monkeypatch, checks):
    candidate, detail = product()
    engine, _ = classifier(monkeypatch, response(checks))
    result = await engine.classify(candidate, criteria("avulso 3d"), detail)
    assert result.decision == "uncertain"
    assert result.reason == "classifier_failed"


async def test_rejection_and_missing_evidence_are_distinct(monkeypatch):
    candidate, detail = product("Processador Ryzen 5 5500")
    engine, client = classifier(
        monkeypatch,
        response(
            [
                check(status="mismatch", excerpt="Ryzen 5 5500"),
            ]
        ),
    )
    assert (await engine.classify(candidate, criteria(), detail)).decision == "rejected"
    client.invoke.return_value = response([check(status="missing", excerpt="")])
    assert (
        await engine.classify(candidate, criteria(), detail)
    ).decision == "uncertain"


async def test_no_key_or_provider_failure_does_not_approve_description(monkeypatch):
    candidate, detail = product()
    engine, client = classifier(monkeypatch, None)
    client.invoke.side_effect = TimeoutError()
    assert (
        await engine.classify(candidate, criteria("avulso 3d"), detail)
    ).reason == "classifier_failed"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    result = await ProductClassifier(client).classify(
        candidate, criteria("avulso 3d"), detail
    )
    assert result.decision == "uncertain"
    assert result.reason == "classifier_unavailable"


async def test_clear_match_without_description_does_not_call_provider(monkeypatch):
    candidate, detail = product()
    engine, client = classifier(monkeypatch, None)
    exact = ProductMatchCriteria(match_mode="intent", query=detail.entity.title)
    assert (await engine.classify(candidate, exact, detail)).decision == "accepted"
    client.invoke.assert_not_awaited()


@pytest.mark.parametrize(
    "status,reason",
    [(429, "classifier_rate_limited"), (503, "classifier_provider_unavailable")],
)
async def test_provider_failure_preserves_specific_reason(monkeypatch, status, reason):
    candidate, detail = product()
    engine, client = classifier(monkeypatch, None)
    provider_response = httpx.Response(
        status, request=httpx.Request("POST", "https://example.test")
    )
    client.invoke.side_effect = httpx.HTTPStatusError(
        "provider unavailable",
        request=provider_response.request,
        response=provider_response,
    )
    result = await engine.classify(candidate, criteria(), detail)
    assert result.decision == "uncertain"
    assert result.reason == reason


def test_classifier_input_is_bounded_and_does_not_include_entire_html():
    _, detail = product()
    detail = detail.model_copy(
        update={
            "specifications": {f"spec{i}": "x" * 5000 for i in range(100)},
            "entity": detail.entity.model_copy(update={"description": "z" * 100000}),
        }
    )
    fields = product_fields(detail)
    assert sum(len(v) for v in fields.values()) <= 12000
    assert len(fields) <= 54


def test_dynamic_profile_category_does_not_break_product_parsing():
    html = '<h1 id="productTitle">AMD Ryzen 7 5700X3D</h1><div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">R$ 1.199,98</span></span></div>'
    detail = parse_catalog_product(
        html, "https://www.amazon.com.br/dp/B09VCHQHZ6", "B09VCHQHZ6", "hardware"
    )
    assert detail.catalog.category == "other"
    assert detail.offer.price == Decimal("1199.98")


async def test_mapping_does_not_query_category_registry(monkeypatch):
    from uuid import uuid4

    value = SearchTermCreate(term="Ryzen 7", description="avulso 3d")
    row = dict(
        public_id=uuid4(),
        site=value.site,
        term=value.term,
        criteria=value.criteria.model_dump(mode="json"),
        max_pages_qt=1,
        max_candidates_qt=100,
        refresh_interval_seconds=86400,
    )
    monkeypatch.setattr(repository, "insert_term", AsyncMock(return_value=row))
    session = Mock(execute=AsyncMock())
    result = await services.create_term(session, value)
    assert result["criteria"]["description"] == "avulso 3d"
    session.execute.assert_not_awaited()


async def test_only_explicit_routines_are_enqueued(monkeypatch):
    enqueue = AsyncMock()
    monkeypatch.setattr(schedules, "enqueue_schedules", enqueue)
    session = Mock(execute=AsyncMock())
    await queue_repository.enqueue_due(session)
    enqueue.assert_awaited_once_with(session)
    session.execute.assert_not_awaited()
