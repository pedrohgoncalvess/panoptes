from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from panoptes_contracts import ParserManifest
from panoptes_contracts.discovery import ProductMatchCriteria, SearchCandidate
from panoptes_contracts.offers import ProductDetail
from panoptes_workers.amazon.detail import parse_product
from panoptes_workers.amazon.identity import asin_from_url, validate_candidate
from panoptes_workers.amazon.search import parse_search

FIXTURES = Path(__file__).resolve().parents[1] / "workers/parsers/amazon-book"


def test_search_keeps_distinct_asins_and_rejects_unrelated_books():
    candidates, next_url = parse_search(
        (FIXTURES / "search.html").read_bytes(), uuid4(), 1
    )
    assert len(candidates) == 4
    criteria = ProductMatchCriteria(
        title="Database Internals", authors=("Alex Petrov",)
    )
    accepted = [
        candidate.source_key
        for candidate in candidates
        if validate_candidate(candidate, criteria).decision == "accepted"
    ]
    assert accepted == ["1492040347", "B07XW76VHZ"]
    assert "page=2" in next_url


def test_executable_parser_matches_synthetic_and_live_sanitized_fixtures():
    manifest = ParserManifest.model_validate_json(
        (FIXTURES / "manifest.json").read_text()
    )
    for fixture in manifest.fixtures:
        expected = ProductDetail.model_validate_json(
            (FIXTURES / fixture.expected_path).read_text(encoding="utf-8")
        )
        actual = parse_product(
            (FIXTURES / fixture.html_path).read_bytes(),
            str(expected.entity.url),
            expected.entity.source_key,
        )
        assert actual == expected
    assert any(f.provenance == "sanitized_capture" for f in manifest.fixtures)


def test_offer_prices_stock_and_coupon_conditions():
    detail = parse_product(
        (FIXTURES / "product.html").read_bytes(),
        "https://www.amazon.com.br/dp/1492040347",
        "1492040347",
    )
    assert detail.offer.price == Decimal("399.90")
    assert detail.offer.list_price == Decimal("499.90")
    assert detail.offer.stock_qt == 3
    assert detail.offer.promotions[0].kind == "coupon"
    assert detail.offer.promotions[0].requires_activation is None
    assert "elegíveis" in detail.offer.promotions[0].text
    assert len(detail.offer.image_urls) == 1
    assert "large" in str(detail.offer.image_urls[0])


def test_missing_price_is_unknown_and_out_of_stock_is_not_in_stock():
    html = """<h1 id="productTitle">Database Internals</h1>
              <div id="availability">Produto indisponível</div>"""
    detail = parse_product(
        html, "https://www.amazon.com.br/dp/1492040347", "1492040347"
    )
    assert detail.entity.price is None
    assert detail.entity.currency is None
    assert detail.offer.stock_qt is None
    assert detail.offer.availability == "out_of_stock"


def test_author_and_isbn_mismatch_prevents_tracking():
    candidate = SearchCandidate(
        source_key="1492040347",
        url="https://www.amazon.com.br/dp/1492040347",
        title="Database Internals",
        authors=("Wrong Author",),
        search_snapshot_id=uuid4(),
        page_qt=1,
        position_qt=1,
    )
    criteria = ProductMatchCriteria(
        title="Database Internals", authors=("Alex Petrov",)
    )
    assert validate_candidate(candidate, criteria, detail=True).decision == "rejected"
    candidate = candidate.model_copy(update={"authors": ()})
    assert validate_candidate(candidate, criteria, detail=True).decision == "uncertain"
    candidate = candidate.model_copy(update={"authors": ("Alex Petrov",)})
    criteria = criteria.model_copy(update={"isbn": ("9781492040347",)})
    assert (
        validate_candidate(
            candidate, criteria, detail=True, isbn=("9781234567890",)
        ).decision
        == "rejected"
    )


def test_sponsored_url_never_changes_canonical_product_identity():
    assert (
        asin_from_url("https://www.amazon.com.br/a-title/dp/1492040347?ref=abc")
        == "1492040347"
    )
    with pytest.raises(ValueError):
        asin_from_url("https://evil.example/dp/1492040347")
    with pytest.raises(ValueError):
        parse_product(
            '<input id="ASIN" value="193693017X"><h1 id="productTitle">Database Internals</h1>',
            "https://www.amazon.com.br/dp/1492040347",
            "1492040347",
        )


def test_jsonld_book_fallback_without_dom_title():
    html = """<script type="application/ld+json">{"@type":"Book","name":"Database Internals",
        "author":{"@type":"Person","name":"Alex Petrov"}, "isbn":"9781492040347",
        "offers":{"price":"200.00","priceCurrency":"BRL","availability":"https://schema.org/InStock"}}</script>"""
    result = parse_product(
        html, "https://www.amazon.com.br/dp/1492040347", "1492040347"
    )
    assert result.offer.price == Decimal("200.00")
    assert result.authors == ("Alex Petrov",)
