from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from panoptes_contracts import ParserManifest, ProductDetail, SourceSelection
from panoptes_contracts.discovery import ProductMatchCriteria, SearchCandidate
from panoptes_workers.mercado_livre.identity import canonical_url, key_from_url
from panoptes_workers.mercado_livre.product import parse_catalog_product
from panoptes_workers.mercado_livre.search import (
    pagination_unavailable,
    parse_search,
    search_url,
)
from panoptes_workers.sources import get_source
from pydantic import ValidationError

FIXTURES = Path(__file__).resolve().parents[1] / "workers/parsers/mercado-livre-product"


@pytest.mark.parametrize(
    "href",
    [
        None,
        "",
        "#",
        "?page=2",
        "/",
        "https://lista.mercadolivre.com.br",
        "https://evil.test/sofa",
        "https://user:pass@lista.mercadolivre.com.br/sofa",
        "https://lista.mercadolivre.com.br:444/sofa",
    ],
)
def test_missing_or_unsafe_next_link_never_becomes_marketplace_home(href):
    attribute = f'href="{href}"' if href is not None else ""
    html = f'<div class="ui-search-layout"></div><li class="andes-pagination__button--next"><a {attribute}>Seguinte</a></li>'
    assert parse_search(html, uuid4(), 1)[1] is None
    assert pagination_unavailable(html)


def test_disabled_next_page_is_a_normal_end_of_results():
    html = '<div class="ui-search-layout"></div><li class="andes-pagination__button--next andes-pagination__button--disabled"><a>Seguinte</a></li>'
    assert parse_search(html, uuid4(), 1)[1] is None
    assert not pagination_unavailable(html)


def test_search_preserves_native_identity_and_deduplicates_without_tracking():
    candidates, next_url = parse_search(
        (FIXTURES / "search.html").read_bytes(), uuid4(), 1
    )
    assert [c.source_key for c in candidates] == [
        "MLB1234567890",
        "MLB9876543210",
        "MLB1111111111",
    ]
    assert all(c.site == "mercado_livre_br" for c in candidates)
    assert all("?" not in str(c.url) for c in candidates)
    assert "_Desde_51" in next_url
    source = get_source("mercado_livre_br")
    criteria = ProductMatchCriteria(title="CTO")
    assert [source.validate(c, criteria).decision for c in candidates] == [
        "accepted",
        "accepted",
        "rejected",
    ]
    assert search_url("CTO livro") == "https://lista.mercadolivre.com.br/CTO-livro"


def test_manifest_executes_against_all_commercial_fixtures():
    manifest = ParserManifest.model_validate_json(
        (FIXTURES / "manifest.json").read_text()
    )
    assert (
        manifest.entrypoint
        == "panoptes_workers.mercado_livre.product:parse_catalog_product"
    )
    for fixture in manifest.fixtures:
        expected = ProductDetail.model_validate_json(
            (FIXTURES / fixture.expected_path).read_text(encoding="utf-8")
        )
        actual = parse_catalog_product(
            (FIXTURES / fixture.html_path).read_bytes(),
            str(expected.entity.url),
            expected.entity.source_key,
            "book",
        )
        assert actual == expected
    assert actual.offer.stock_qt is None
    assert actual.offer.price is None


def test_commercial_normalization_keeps_conditions_and_decimal_prices():
    detail = parse_catalog_product(
        (FIXTURES / "book.html").read_bytes(),
        "https://produto.mercadolivre.com.br/MLB-1234567890-livro-cto-_JM",
        "MLB1234567890",
        "book",
    )
    assert detail.offer.price == Decimal("129.90")
    assert detail.offer.list_price == Decimal("159.90")
    assert detail.offer.stock_qt == 3
    assert detail.offer.seller == "Livraria Exemplo"
    assert detail.catalog.attributes["page_count"] == 240
    assert detail.isbn == ("9781234567897",)
    assert detail.offer.payment_options[0].installment_price == Decimal("43.30")
    assert detail.offer.payment_options[0].interest_free is True
    assert detail.offer.shipping.is_free is True
    assert detail.offer.promotions[0].requires_activation is None


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/MLB-1234567890",
        "https://produto.mercadolivre.com.br:444/MLB-1234567890",
        "https://user:password@produto.mercadolivre.com.br/MLB-1234567890",
    ],
)
def test_native_identity_rejects_external_hosts_and_credentials(url):
    with pytest.raises(ValueError):
        key_from_url(url)


def test_detail_rejects_changed_canonical_identity():
    with pytest.raises(ValueError, match="canonical_source_key_mismatch"):
        parse_catalog_product(
            (FIXTURES / "book.html").read_bytes(),
            "https://produto.mercadolivre.com.br/MLB-9999999999-test-_JM",
            "MLB9999999999",
        )
    assert (
        canonical_url(
            "https://produto.mercadolivre.com.br/MLB-1234567890-livro-_JM?ref=abc"
        )
        == "https://produto.mercadolivre.com.br/MLB-1234567890-livro-_JM"
    )


def test_source_contract_does_not_accept_amazon_keys_for_mercado_livre():
    with pytest.raises(ValidationError):
        SearchCandidate(
            site="mercado_livre_br",
            source_key="1492040347",
            url="https://www.mercadolivre.com.br/p/MLB1234567890",
            title="CTO",
            search_snapshot_id=uuid4(),
            page_qt=1,
            position_qt=1,
        )
    for sites in ([], ["mercado_livre_br", "mercado_livre_br"], ["unknown"]):
        with pytest.raises(ValidationError):
            SourceSelection(sites=sites)


def test_dom_price_uses_centavos_and_ignores_related_product_jsonld():
    html = """<h1 class="ui-pdp-title">CTO</h1>
      <div class="ui-pdp-price__second-line"><span class="andes-money-amount">
        <span class="andes-money-amount__currency-symbol">R$</span>
        <span class="andes-money-amount__fraction">1.299</span>
        <span class="andes-money-amount__cents">90</span></span></div>
      <script type="application/ld+json">{"@type":"Product","name":"Outro produto","sku":"MLB9999999999","offers":{"price":"1.00","priceCurrency":"BRL"}}</script>"""
    result = parse_catalog_product(
        html, "https://www.mercadolivre.com.br/p/MLB1234567890", "MLB1234567890", "book"
    )
    assert result.offer.price == Decimal("1299.90")
    assert result.offer.availability == "unknown"
