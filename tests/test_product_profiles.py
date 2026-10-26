from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth.router import current_user
from panoptes_backend.catalog.router import session_dependency
from panoptes_backend.main import create_app
from panoptes_contracts.discovery import (
    AttributeRequirement,
    ProductMatchCriteria,
    TrackedCandidate,
)
from panoptes_workers.amazon.product import parse_catalog_product
from panoptes_workers.common.matching import validate_candidate
from panoptes_workers.common.qualification import compare, qualify


def ssd(specs=True):
    html = '<h1 id="productTitle">SSD NVMe Kingston 1TB</h1><span class="a-price"><span class="a-offscreen">R$ 499,90</span></span>'
    if specs:
        html += '<table id="productDetails_techSpec_section_1"><tr><th>Marca</th><td>Kingston</td></tr><tr><th>Velocidade de gravação</th><td>5000 MB/s</td></tr><tr><th>Capacidade de armazenamento</th><td>1 TB</td></tr></table>'
    detail = parse_catalog_product(
        html, "https://www.amazon.com.br/dp/B0SSD00001", "B0SSD00001"
    )
    candidate = TrackedCandidate(
        source_key=detail.entity.source_key,
        url=detail.entity.url,
        title=detail.entity.title,
    )
    return candidate, detail


def profile(**overrides):
    return ProductMatchCriteria(
        match_mode="profile",
        title="SSD NVMe",
        category="hardware",
        category_name="Hardware",
        category_keywords=("ssd", "processador"),
        **overrides,
    )


def test_profile_can_match_brands_and_specs_without_book_title_prefix():
    candidate, detail = ssd()
    criteria = profile(
        brands=("Kingston",),
        reference_price=Decimal("550"),
        characteristics=(
            AttributeRequirement(
                name="Velocidade de gravação", value="5", unit="GB/s", operator="gte"
            ),
        ),
    )
    assert validate_candidate(candidate, criteria).decision == "accepted"
    result = qualify(candidate, criteria, detail=detail)
    assert result.decision == "accepted"
    assert any(
        check.evidence == "Velocidade de gravação: 5000 MB/s" for check in result.checks
    )
    assert any(check.status == "info" for check in result.checks)
    assert detail.catalog.brand == "Kingston"


def test_missing_or_incompatible_specs_never_start_tracking():
    candidate, detail = ssd(False)
    criteria = profile(
        characteristics=(
            AttributeRequirement(name="Velocidade de gravação", value="5", unit="GB/s"),
        )
    )
    assert qualify(candidate, criteria, detail=detail).decision == "uncertain"
    candidate, detail = ssd()
    assert (
        qualify(candidate, profile(brands=("Samsung",)), detail=detail).decision
        == "rejected"
    )
    detail = detail.model_copy(
        update={"specifications": {"Velocidade de gravação": "5 GB"}}
    )
    assert qualify(candidate, criteria, detail=detail).decision == "uncertain"


@pytest.mark.parametrize(
    "expected,unit,actual,operator,result",
    [
        ("50", "L", "50000 ml", "eq", True),
        ("50", "L", "45 litros", "gte", False),
        ("5", "GB/s", "5000 MB/s", "gte", True),
        ("5", "GB/s", "5 GB", "eq", None),
        ("50", "L", "50", "eq", None),
        ("50", "L", "50 a 60 L", "eq", None),
        ("NVMe", "", "NVMe PCIe 4.0", "contains", True),
    ],
)
def test_numeric_units_and_text(expected, unit, actual, operator, result):
    assert (
        compare(
            AttributeRequirement(
                name="Teste", value=expected, unit=unit, operator=operator
            ),
            actual,
        )
        is result
    )


async def test_category_management_is_protected_and_validated():
    app = create_app()
    session = Mock(execute=AsyncMock())

    async def dependency():
        yield session

    app.dependency_overrides[session_dependency] = dependency
    app.dependency_overrides[current_user] = lambda: {"role": "user"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        value = {"slug": "sports", "name": "Esportes", "keywords": ["bicicleta"]}
        assert (
            await client.put("/admin/categories/sports", json=value)
        ).status_code == 403
        session.execute.assert_not_awaited()
        app.dependency_overrides[current_user] = lambda: {"role": "admin"}
        assert (
            await client.put("/admin/categories/sports", json=value)
        ).status_code == 200
        assert session.execute.await_args.args[1]["slug"] == "sports"
        assert (
            await client.put("/admin/categories/other", json=value)
        ).status_code == 422
        assert (
            await client.put(
                "/admin/categories/sports", json={**value, "slug": "Bad Slug"}
            )
        ).status_code == 422


def test_legacy_exact_titles_remain_compatible():
    assert (
        ProductMatchCriteria(title="Database Internals").match_mode == "exact_product"
    )
    with pytest.raises(ValueError):
        ProductMatchCriteria(match_mode="profile")


def test_profile_accepts_category_only_without_optional_filters_or_price():
    criteria = ProductMatchCriteria(
        match_mode="profile", category="hardware", category_keywords=("ssd",)
    )
    assert criteria.title is None and criteria.reference_price is None
    assert not criteria.brands and not criteria.authors and not criteria.characteristics
    candidate, detail = ssd()
    assert validate_candidate(candidate, criteria).decision == "accepted"
    assert qualify(candidate, criteria, detail=detail).decision == "accepted"


def test_mercado_livre_hardware_specs_are_qualified_with_the_same_rules():
    from panoptes_workers.mercado_livre.product import parse_catalog_product as parse_ml

    html = '<h1 class="ui-pdp-title">SSD Kingston NVMe</h1><table class="ui-pdp-specs__table"><tr><th>Marca</th><td>Kingston</td></tr><tr><th>Velocidade de escrita</th><td>5000 MB/s</td></tr></table>'
    detail = parse_ml(
        html,
        "https://produto.mercadolivre.com.br/MLB-1234567890-ssd-_JM",
        "MLB1234567890",
    )
    candidate = TrackedCandidate(
        site="mercado_livre_br",
        source_key=detail.entity.source_key,
        url=detail.entity.url,
        title=detail.entity.title,
    )
    result = qualify(
        candidate,
        profile(
            brands=("Kingston",),
            characteristics=(
                {
                    "name": "Velocidade de gravação",
                    "value": "5",
                    "unit": "GB/s",
                    "operator": "gte",
                },
            ),
        ),
        detail=detail,
    )
    assert result.decision == "accepted"
    assert result.checks[-1].evidence == "Velocidade de escrita: 5000 MB/s"
