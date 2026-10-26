from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from panoptes_contracts import ParserManifest
from panoptes_contracts.catalog import CatalogProduct
from panoptes_contracts.discovery import ProductMatchCriteria, TrackedCandidate
from panoptes_contracts.offers import PaymentOption, ProductDetail, ProductOffer
from panoptes_workers.amazon.identity import validate_candidate
from panoptes_workers.amazon.product import parse_catalog_product
from panoptes_workers.amazon.search import parse_search, search_url
from panoptes_workers.workflow.catalog_repository import (
    identity_keys,
    validate_existing,
)
from pydantic import ValidationError

FIXTURES = Path(__file__).resolve().parents[1] / "workers/parsers/amazon-product"


def tv():
    return parse_catalog_product(
        (FIXTURES / "television.html").read_bytes(),
        "https://www.amazon.com.br/dp/B0TV500001",
        "B0TV500001",
    )


def test_category_search_preserves_brands_and_models_and_excludes_other_sizes():
    candidates, _ = parse_search((FIXTURES / "search.html").read_bytes(), uuid4(), 1)
    criteria = ProductMatchCriteria(
        match_mode="category",
        category="television",
        required_attributes={"screen_size_inches": 50},
    )
    accepted = [
        c.source_key
        for c in candidates
        if validate_candidate(c, criteria).decision == "accepted"
    ]
    assert accepted == ["B0TV500001", "B0TV500002", "B0TV500003", "B0TV500004"]
    assert "stripbooks" not in search_url("tv 50 polegadas", book_only=False)
    assert "stripbooks" in search_url("Database Internals")


def test_detail_accepts_confirmed_attributes_and_rejects_wrong_or_missing_specs():
    detail = tv()
    candidate = TrackedCandidate(
        source_key=detail.entity.source_key,
        url=detail.entity.url,
        title=detail.entity.title,
    )
    criteria = ProductMatchCriteria(
        match_mode="category",
        category="television",
        required_attributes={"screen_size_inches": 50},
    )
    assert (
        validate_candidate(
            candidate, criteria, detail=True, catalog=detail.catalog
        ).decision
        == "accepted"
    )
    wrong = detail.catalog.model_copy(update={"attributes": {"screen_size_inches": 55}})
    assert (
        validate_candidate(candidate, criteria, detail=True, catalog=wrong).reason
        == "attribute_mismatch:screen_size_inches"
    )
    missing = detail.catalog.model_copy(update={"attributes": {}})
    assert (
        validate_candidate(candidate, criteria, detail=True, catalog=missing).decision
        == "uncertain"
    )
    lg = criteria.model_copy(update={"brands": ("LG",)})
    assert (
        validate_candidate(candidate, lg, detail=True, catalog=detail.catalog).reason
        == "brand_mismatch"
    )


def test_commercial_amounts_remain_separate_and_conditions_are_preserved():
    offer = tv().offer
    assert offer.price == Decimal("2999.90") and offer.list_price == Decimal("3499.90")
    coupon = next(p for p in offer.promotions if p.kind == "coupon")
    assert coupon.code == "TV10" and coupon.discount_percent == 10
    assert (
        coupon.minimum_spend == Decimal("2000.00")
        and coupon.requires_activation is True
    )
    assert coupon.discount_amount is None and "elegíveis" in coupon.conditions[0]
    pix = next(p for p in offer.payment_options if p.method == "pix")
    installments = next(p for p in offer.payment_options if p.method == "installment")
    assert pix.total_price == Decimal("2799.90")
    assert (
        installments.installment_count == 10
        and installments.installment_price == Decimal("299.99")
    )
    assert installments.total_price is None and installments.interest_free is True
    assert offer.shipping.price == Decimal("15.90")
    assert offer.shipping.destination_postal_code == "01001-000"


def test_generic_manifest_has_reproducible_category_fixtures():
    manifest = ParserManifest.model_validate_json(
        (FIXTURES / "manifest.json").read_text()
    )
    categories = set()
    for fixture in manifest.fixtures:
        expected = ProductDetail.model_validate_json(
            (FIXTURES / fixture.expected_path).read_text(encoding="utf-8")
        )
        actual = parse_catalog_product(
            (FIXTURES / fixture.html_path).read_bytes(),
            str(expected.entity.url),
            expected.entity.source_key,
        )
        assert actual == expected
        categories.add(actual.catalog.category)
    assert categories == {"television", "refrigerator", "school_supplies"}


@pytest.mark.parametrize(
    "criteria",
    [
        {"match_mode": "category"},
        {
            "match_mode": "category",
            "category": "television",
            "required_attributes": {"capacity_liters": 400},
        },
        {
            "match_mode": "category",
            "category": "television",
            "required_attributes": {"screen_size_inches": None},
        },
        {
            "match_mode": "category",
            "category": "television",
            "required_attributes": {"screen_size_inches": -1},
        },
        {"match_mode": "category", "category": "television", "authors": ["Someone"]},
    ],
)
def test_category_contract_rejects_invalid_or_unknown_attributes(criteria):
    with pytest.raises(ValidationError):
        ProductMatchCriteria(**criteria)


def test_prices_require_currency_and_reject_excess_precision():
    with pytest.raises(ValidationError):
        ProductOffer(price="0.00001", currency="BRL")
    with pytest.raises(ValidationError):
        ProductOffer(
            payment_options=(
                PaymentOption(method="pix", text="Price", total_price="123.45"),
            )
        )


def test_shipping_minimum_purchase_is_not_a_shipping_fee():
    html = '<h1 id="productTitle">Smart TV 50 polegadas</h1><div id="deliveryBlockMessage">Frete grátis para compras acima de R$ 99,00. Apenas Prime.</div>'
    result = parse_catalog_product(
        html, "https://www.amazon.com.br/dp/B0TV500001", "B0TV500001"
    )
    assert result.offer.shipping.is_free is True
    assert result.offer.shipping.price is None
    assert "Prime" in result.offer.shipping.conditions[0]


def test_book_category_uses_isbn_evidence_without_title_prefix():
    html = '<h1 id="productTitle">Database Internals</h1><table id="productDetails_techSpec_section_1"><tr><th>ISBN-13</th><td>9781492040347</td></tr></table>'
    result = parse_catalog_product(
        html, "https://www.amazon.com.br/dp/1492040347", "1492040347"
    )
    assert result.catalog.category == "book"


def test_identity_keeps_models_variants_and_unknown_sources_separate():
    first = tv()
    second = first.model_copy(
        update={"entity": first.entity.model_copy(update={"source_key": "B0TV500002"})}
    )
    assert identity_keys(first)[0] == identity_keys(second)[0]
    assert identity_keys(first)[1] != identity_keys(second)[1]
    second = second.model_copy(
        update={"catalog": second.catalog.model_copy(update={"model": "S50Q200"})}
    )
    assert identity_keys(first)[0] != identity_keys(second)[0]
    existing = {
        "category": "television",
        "brand": "Samsung",
        "model": "S50C100",
        "attributes": {"screen_size_inches": "50.00"},
    }
    validate_existing(existing, first.catalog)
    with pytest.raises(ValueError, match="listing_identity_changed"):
        validate_existing(existing, second.catalog)
    assert CatalogProduct(
        category="television",
        attributes={"resolution": "3840 × 2160", "voltage": "220 V"},
    ).attributes == {"resolution": "3840x2160", "voltage": "220v"}
