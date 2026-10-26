import importlib
import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from panoptes_contracts import ParserManifest
from panoptes_contracts.discovery import ProductMatchCriteria, SearchCandidate
from panoptes_contracts.sources import SOURCES, SourceSelection
from panoptes_workers.infrastructure.http import Download, block_reason, validate_url
from panoptes_workers.retailers.identity import canonical_url, key_from_url
from panoptes_workers.retailers.product import parse_product, price_value
from panoptes_workers.sources import get_source

ROOT = Path(__file__).resolve().parents[1] / "workers" / "parsers"
URLS = {
    "kabum_br": "https://www.kabum.com.br/produto/123/placa-de-video-rtx-3070",
    "pichau_br": "https://www.pichau.com.br/placa-de-video-rtx-3070",
    "terabyte_br": "https://www.terabyteshop.com.br/produto/123/placa-de-video-rtx-3070",
}


def document(site, *, offers=None, extra="", title="Placa de Video RTX 3070"):
    product = {
        "@type": "Product",
        "name": title,
        "url": URLS[site],
        "offers": offers
        if offers is not None
        else {
            "@type": "Offer",
            "price": "2199.99",
            "priceCurrency": "BRL",
            "availability": "https://schema.org/InStock",
        },
    }
    return f'<h1>{title}</h1><script type="application/ld+json">{json.dumps(product)}</script>{extra}'


@pytest.mark.parametrize("site", URLS)
def test_adapters_and_manifests_are_runnable(site):
    assert site in SourceSelection(sites=tuple(SOURCES)).sites
    source = get_source(site)
    manifest = ParserManifest.model_validate_json(
        (ROOT / source.definition.parser_slug / "manifest.json").read_text()
    )
    module, name = manifest.entrypoint.split(":")
    parser = getattr(importlib.import_module(module), name)
    for fixture in manifest.fixtures:
        from panoptes_contracts.offers import ProductDetail

        folder = ROOT / source.definition.parser_slug
        expected = ProductDetail.model_validate_json(
            (folder / fixture.expected_path).read_text(encoding="utf-8")
        )
        result = parser(
            (folder / fixture.html_path).read_text(encoding="utf-8"),
            str(expected.entity.url),
            expected.entity.source_key,
        )
        assert result == expected


@pytest.mark.parametrize("site", URLS)
def test_identity_rejects_redirects_and_wrong_canonical(site):
    key = key_from_url(site, URLS[site])
    different = (
        URLS[site].replace("123", "456") if site != "pichau_br" else URLS[site] + "-ti"
    )
    with pytest.raises(ValueError, match="redirected_to_different_product"):
        parse_product(site, document(site), different, key)
    with pytest.raises(ValueError, match="canonical_source_key_mismatch"):
        parse_product(
            site,
            document(site, extra=f'<link rel="canonical" href="{different}">'),
            URLS[site],
            key,
        )
    with pytest.raises(ValueError):
        key_from_url(site, "https://evil.example/produto/123")
    with pytest.raises(ValueError):
        key_from_url(site, URLS[site].replace("https://", "https://user:secret@"))
    assert "?" not in canonical_url(site, URLS[site] + "?utm_source=test")


@pytest.mark.parametrize("site", URLS)
def test_out_of_stock_keeps_observed_prices_and_availability(site):
    offers = {
        "@type": "Offer",
        "price": "15999.90",
        "priceCurrency": "BRL",
        "availability": "https://schema.org/OutOfStock",
    }
    d = parse_product(
        site,
        document(
            site, offers=offers, extra="<aside>R$ 1,00 em produto recomendado</aside>"
        ),
        URLS[site],
        key_from_url(site, URLS[site]),
    )
    assert d.offer.availability == "out_of_stock"
    assert d.offer.price == Decimal("15999.90")
    assert d.entity.price == Decimal("15999.90")
    assert d.entity.availability == "out_of_stock"
    assert d.offer.payment_options == ()
    assert (
        "unavailable_offer_prices_suppressed"
        not in d.offer.commercial_extraction.unresolved
    )


@pytest.mark.parametrize("available", [True, False])
@pytest.mark.parametrize(
    "old,current", [("5.697,61", "2.879,98"), ("5,697.61", "2,879.98")]
)
def test_pichau_upgrade_kit_keeps_previous_and_starting_prices(available, old, current):
    url = "https://www.pichau.com.br/pichau-kit-upgrade-ryzen-7"
    html = f"""<div>
        <div class="mui-test-mainContentColumn"><h1>Pichau Kit upgrade Ryzen 7</h1></div>
        <div><div class="mui-test-priceWrapper">
        <div class="mui-test-dePor"><s>deR$\xa0{old} por</s></div>
        <span class="mui-test-aPartir">a partir de</span>
        <strong class="mui-test-price_vista">R$\xa0{current}</strong>
        <div class="mui-test-priceTotal">R$ 3.388,21</div>
        <span class="mui-test-availability">
            {"Produto Disponível" if available else "Produto Indisponível"}
        </span>
        </div></div></div><aside><strong class="mui-test-price_vista">R$ 1,00</strong></aside>
    """
    detail = parse_product("pichau_br", html, url, url.rsplit("/", 1)[-1])
    from panoptes_workers.common.commerce import extract_commerce

    detail, _ = extract_commerce(detail, html, "pichau_br")
    assert detail.offer.price == Decimal("2879.98")
    assert detail.offer.list_price == Decimal("5697.61")
    assert detail.entity.price == Decimal("2879.98")
    assert detail.offer.availability == ("in_stock" if available else "out_of_stock")
    assert next(
        p for p in detail.offer.payment_options if p.method == "pix"
    ).conditions == ("a partir de",)
    assert next(
        p for p in detail.offer.payment_options if p.method == "pix"
    ).total_price == Decimal("2879.98")
    assert next(
        p for p in detail.offer.payment_options if p.method == "card"
    ).total_price == Decimal("3388.21")


@pytest.mark.parametrize("site", URLS)
@pytest.mark.parametrize(
    "offer",
    [
        {"@type": "AggregateOffer", "lowPrice": "1", "priceCurrency": "BRL"},
        [{"price": "1", "priceCurrency": "BRL"}],
        {"price": "123"},
    ],
)
def test_ambiguous_seller_aggregate_and_currency_are_not_prices(site, offer):
    d = parse_product(
        site, document(site, offers=offer), URLS[site], key_from_url(site, URLS[site])
    )
    assert d.offer.price is None


@pytest.mark.parametrize("site", URLS)
def test_related_structured_product_cannot_supply_price(site):
    html = "<h1>Placa de Video RTX 3070</h1>" + document(
        site, title="Outra placa"
    ).replace(
        URLS[site],
        URLS[site] + "-outro"
        if site == "pichau_br"
        else URLS[site].replace("123", "456"),
    )
    d = parse_product(site, html, URLS[site], key_from_url(site, URLS[site]))
    assert d.offer.price is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("R$ 2.199,99", "2199.99"),
        ("R$ 2,199.99", "2199.99"),
        ("2199.99", "2199.99"),
        ("R$ XY.ZXY,ZX", None),
        ("12x de R$ 215,69", None),
        ("-1", None),
    ],
)
def test_money_formats_and_placeholders(raw, expected):
    assert price_value(raw) == (Decimal(expected) if expected else None)


@pytest.mark.parametrize("site", SOURCES)
def test_challenges_never_reach_product_or_search_parsers(site):
    source = get_source(site)
    html = "<title>Just a moment...</title><h1>Produto</h1>"
    assert (
        block_reason(
            Download(
                source.search_url("ssd"),
                source.search_url("ssd"),
                html.encode(),
                200,
                "text/html",
            )
        )
        == "captcha"
    )
    with pytest.raises(ValueError, match="captcha"):
        source.parse_search(html, uuid4(), 1)


def test_kabum_json_string_category_redirect_and_pagination():
    data = {
        "catalogServer": {
            "data": [
                {
                    "code": 123,
                    "name": "SSD Kingston NV3 1TB",
                    "friendlyName": "ssd-kingston-nv3",
                }
            ],
            "pagination": {"next": 2},
        }
    }
    html = (
        '<script id="__NEXT_DATA__">'
        + json.dumps({"props": {"pageProps": {"data": json.dumps(data)}}})
        + "</script>"
    )
    candidates, _ = get_source("kabum_br").parse_search(html, uuid4(), 1)
    assert candidates[0].source_key == "123"
    assert candidates[0].title == "SSD Kingston NV3 1TB"


@pytest.mark.parametrize("site", URLS)
def test_unknown_layout_is_failure_and_explicit_empty_search_is_success(site):
    source = get_source(site)
    with pytest.raises(ValueError, match="search_layout_not_recognized"):
        source.parse_search("<h1>Maintenance</h1>", uuid4(), 1)
    assert source.parse_search("<h1>Nenhum produto encontrado</h1>", uuid4(), 1) == (
        (),
        None,
    )
    with pytest.raises(ValueError):
        validate_url(
            "https://127.0.0.1/produto/1", allowed_hosts=source.definition.page_hosts
        )


@pytest.mark.parametrize(
    "term,title,accepted",
    [
        ("rtx 3070", "Placa de Video Asus GeForce RTX 3070 Dual 8GB", True),
        ("rtx 3070", "Placa de Video RTX 3070 Ti 8GB", False),
        ("rtx 3070", "Computador Gamer RTX 3070 Ryzen 5", False),
        ("rtx 3070", "Waterblock para RTX 3070", False),
        ("ryzen 5 5600", "Processador AMD Ryzen 5 5600, AM4", True),
        ("ryzen 5 5600", "Processador AMD Ryzen 5 5600X", False),
        ("ryzen 5 5600", "Processador AMD Ryzen 5 5500", False),
        ("ssd kingston nv2 1tb", "SSD Kingston NV3, 1TB M.2", False),
        ("ssd kingston nv3 1tb", "SSD Kingston NV3, 1 TB M.2", True),
        ("ssd kingston nv3 1tb", "SSD Kingston NV3, 2 TB M.2", False),
    ],
)
@pytest.mark.parametrize("site", SOURCES)
def test_hardware_identity_survives_store_prefixes_without_mixing_models(
    site, term, title, accepted
):
    url = {
        "amazon_br": "https://www.amazon.com.br/dp/B012345678",
        "mercado_livre_br": "https://www.mercadolivre.com.br/p/MLB12345678",
        **URLS,
    }[site]
    key = (
        "B012345678"
        if site == "amazon_br"
        else "MLB12345678"
        if site == "mercado_livre_br"
        else key_from_url(site, url)
    )
    candidate = SearchCandidate(
        site=site,
        source_key=key,
        url=url,
        title=title,
        search_snapshot_id=uuid4(),
        page_qt=1,
        position_qt=1,
    )
    result = get_source(site).validate(candidate, ProductMatchCriteria(title=term))
    assert (result.decision == "accepted") is accepted


def test_pichau_search_does_not_include_browsing_history():
    html = (ROOT / "pichau-product" / "search.html").read_text(encoding="utf-8")
    candidates, next_url = get_source("pichau_br").parse_search(html, uuid4(), 1)
    assert len(candidates) == 36
    assert not any("rtx-3070" in c.source_key for c in candidates)
    assert "page=2" in next_url


def test_terabyte_captured_ssd_distinguishes_card_total_from_installment_rounding():
    source = get_source("terabyte_br")
    from panoptes_contracts.offers import ProductDetail

    d = ProductDetail.model_validate_json(
        (ROOT / "terabyte-product/ssd.expected.json").read_text(encoding="utf-8")
    )
    actual = source.parse_product(
        (ROOT / "terabyte-product/ssd.html").read_bytes(),
        str(d.entity.url),
        d.entity.source_key,
    )
    assert actual.offer.price == Decimal("729.90")
    assert next(
        p.total_price for p in actual.offer.payment_options if p.method == "card"
    ) == Decimal("858.71")
    assert next(
        p.installment_price
        for p in actual.offer.payment_options
        if p.method == "installment"
    ) == Decimal("71.56")


def test_amazon_multiple_seller_offers_do_not_select_arbitrary_first_price():
    html = (
        '<h1 id="productTitle">RTX 3070</h1><script type="application/ld+json">'
        + json.dumps(
            {
                "@type": "Product",
                "name": "RTX 3070",
                "offers": [
                    {"price": 1, "priceCurrency": "BRL"},
                    {"price": 999, "priceCurrency": "BRL"},
                ],
            }
        )
        + "</script>"
    )
    assert (
        get_source("amazon_br")
        .parse_product(html, "https://www.amazon.com.br/dp/B012345678", "B012345678")
        .offer.price
        is None
    )


def test_pichau_pending_refresh_does_not_confirm_cached_stock():
    site = "pichau_br"
    html = document(site, extra="<button disabled>ATUALIZANDO INFORMAÇÕES...</button>")
    result = parse_product(site, html, URLS[site], key_from_url(site, URLS[site]))
    assert result.offer.availability == "unknown"
    assert (
        "availability_refresh_pending" in result.offer.commercial_extraction.unresolved
    )
