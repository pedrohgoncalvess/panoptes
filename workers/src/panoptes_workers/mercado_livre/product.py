import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

from panoptes_contracts import ExtractedEntity
from panoptes_contracts.offers import (
    PaymentOption,
    ProductDetail,
    ProductOffer,
    Promotion,
    ShippingQuote,
)
from panoptes_contracts.sources import SOURCES, captcha_page
from selectolax.lexbor import LexborHTMLParser

from ..common.catalog import normalize_catalog
from ..common.matching import normalize
from .identity import canonical_url, key_from_url


def text_of(tree, selector):
    node = tree.css_first(selector)
    return (
        " ".join(node.text(separator=" ", strip=True).split()) or None if node else None
    )


def structured_products(tree):
    products = []

    def collect(value):
        if isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            kinds = value.get("@type", [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if set(kinds) & {"Product", "Book"}:
                products.append(value)
            collect(value.get("@graph", []))

    for node in tree.css('script[type="application/ld+json"]'):
        try:
            collect(json.loads(node.text()))
        except (ValueError, TypeError):
            continue
    return products


def money(value, *, localized=False):
    if value is None:
        return None
    if "-" in str(value):
        return None
    raw = re.sub(r"[^\d.,]", "", str(value))
    if localized or "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        result = Decimal(raw)
        return result if result.is_finite() and result >= 0 else None
    except InvalidOperation:
        return None


def dom_price(node):
    if node is None:
        return None
    fraction = text_of(node, ".andes-money-amount__fraction")
    cents = text_of(node, ".andes-money-amount__cents")
    if fraction:
        return money(fraction + "," + (cents or "00").zfill(2), localized=True)
    return money(node.text(strip=True), localized=True)


def parse_catalog_product(html, url, expected_key, category_hint=None):
    if captcha_page(url, html):
        raise ValueError("captcha")
    if key_from_url(url) != expected_key:
        raise ValueError("redirected_to_different_product")
    tree = LexborHTMLParser(html)
    canonical = tree.css_first('link[rel="canonical"]')
    if canonical and canonical.attributes.get("href"):
        canonical_href = urljoin(url, canonical.attributes["href"])
        if key_from_url(canonical_href) != expected_key:
            raise ValueError("canonical_source_key_mismatch")
        url = canonical_href
    structured = {}
    title = text_of(tree, "h1.ui-pdp-title, h1[itemprop=name]")
    for item in structured_products(tree):
        if item.get("url"):
            try:
                if key_from_url(item["url"]) != expected_key:
                    continue
            except ValueError:
                continue
        elif item.get("sku") and str(item["sku"]).replace("-", "") != expected_key:
            continue
        if title and normalize(str(item.get("name", ""))) != normalize(title):
            continue
        structured = item
        break
    title = title or structured.get("name")
    if not title:
        raise ValueError("product_layout_not_recognized")
    specs = {}
    for row in tree.css(".ui-pdp-specs__table tr, .andes-table__row"):
        label = text_of(row, "th, .andes-table__header__container")
        value = text_of(row, "td, .andes-table__column--value")
        if label and value:
            specs[label.strip(" :")] = value
    normalized_specs = {normalize(k): v for k, v in specs.items()}
    isbn_value = (
        normalized_specs.get("isbn")
        or normalized_specs.get("isbn 13")
        or structured.get("isbn")
    )
    isbn = (re.sub(r"[^0-9Xx]", "", str(isbn_value)),) if isbn_value else ()
    author = (
        normalized_specs.get("autor")
        or normalized_specs.get("autores")
        or structured.get("author")
    )
    raw_authors = author if isinstance(author, list) else [author] if author else []
    authors = tuple(
        str(a.get("name")) if isinstance(a, dict) else str(a)
        for a in raw_authors
        if not isinstance(a, dict) or a.get("name")
    )
    raw_offers = structured.get("offers", {})
    # Do not invent a seller/price for aggregate or multiple-seller offers.
    offers = (
        raw_offers
        if isinstance(raw_offers, dict) and raw_offers.get("@type") != "AggregateOffer"
        else {}
    )
    price_node = tree.css_first(
        ".ui-pdp-price__second-line .andes-money-amount, .ui-pdp-price .andes-money-amount:not(.andes-money-amount--previous)"
    )
    price = money(offers.get("price"))
    currency = offers.get("priceCurrency")
    if price is None:
        price = dom_price(price_node)
        symbol = (
            text_of(price_node, ".andes-money-amount__currency-symbol")
            if price_node
            else None
        )
        currency = "BRL" if symbol == "R$" else None
    if not currency or not re.fullmatch(r"[A-Z]{3}", str(currency)):
        price, currency = None, None
    list_price = (
        dom_price(tree.css_first("s.andes-money-amount, .andes-money-amount--previous"))
        if currency == "BRL"
        else None
    )
    availability_text = text_of(
        tree,
        ".ui-pdp-stock-information, .ui-pdp-buybox__quantity__available, .ui-pdp-unavailable__title",
    )
    available = str(offers.get("availability", "")).rsplit("/", 1)[-1]
    availability = {
        "InStock": "in_stock",
        "OutOfStock": "out_of_stock",
        "SoldOut": "out_of_stock",
    }.get(available, "unknown")
    if availability_text:
        normalized = normalize(availability_text)
        if any(
            s in normalized for s in ("sem estoque", "indisponivel", "anuncio pausado")
        ):
            availability = "out_of_stock"
        elif "estoque disponivel" in normalized:
            availability = "in_stock"
    stock = None
    if availability_text and "mais de" not in normalize(availability_text):
        match = re.search(
            r"\b(\d+)\s+(?:unidades?\s+)?dispon[ií]ve(?:is|l)", availability_text, re.I
        )
        stock = int(match.group(1)) if match else None
    seller = offers.get("seller")
    seller = seller.get("name") if isinstance(seller, dict) else seller
    seller = (
        text_of(tree, ".ui-pdp-seller__header__title, .ui-pdp-seller__link-trigger")
        or seller
    )
    condition = normalized_specs.get("condicao do item") or text_of(
        tree, ".ui-pdp-subtitle"
    )
    if condition:
        condition = next(
            (
                v
                for v in ("Novo", "Usado", "Recondicionado")
                if normalize(v) in normalize(condition)
            ),
            None,
        )
    images = []
    raw_images = structured.get("image", [])
    if isinstance(raw_images, (str, dict)):
        raw_images = [raw_images]
    images.extend(i.get("url", "") if isinstance(i, dict) else i for i in raw_images)
    for node in tree.css(".ui-pdp-gallery__figure img, .ui-pdp-image"):
        images.append(
            node.attributes.get("data-zoom")
            or node.attributes.get("data-src")
            or node.attributes.get("src", "")
        )
    image_urls = tuple(
        dict.fromkeys(
            str(i)
            for i in images
            if isinstance(i, str)
            and urlsplit(i).scheme == "https"
            and urlsplit(i).hostname in SOURCES["mercado_livre_br"].image_hosts
        )
    )[:10]
    payments = []
    payment_text = text_of(
        tree, ".ui-pdp-price__subtitles, .ui-pdp-price__subtitles-item"
    )
    if payment_text:
        match = re.search(r"(\d+)\s*x\s*(?:de\s*)?R\$\s*([\d.,]+)", payment_text, re.I)
        payments.append(
            PaymentOption(
                method="installment" if match else "card",
                text=payment_text,
                installment_count=int(match.group(1)) if match else None,
                installment_price=money(match.group(2), localized=True)
                if match and currency == "BRL"
                else None,
                interest_free=True if "sem juros" in normalize(payment_text) else None,
            )
        )
    shipping_text = text_of(tree, ".ui-pdp-shipping__message, .ui-pdp-media__title")
    shipping = (
        ShippingQuote(
            text=shipping_text,
            is_free=True if "frete gratis" in normalize(shipping_text) else None,
        )
        if shipping_text
        else None
    )
    promotions = tuple(
        Promotion(
            kind="coupon" if "cupom" in normalize(n.text()) else "promotion",
            text=n.text(separator=" ", strip=True),
        )
        for n in tree.css(".ui-pdp-promotions-pill, .ui-pdp-coupons")
        if n.text(strip=True)
    )
    description = text_of(tree, ".ui-pdp-description__content") or structured.get(
        "description"
    )
    offer = ProductOffer(
        price=price,
        list_price=list_price,
        currency=currency,
        availability=availability,
        availability_text=availability_text,
        stock_qt=stock,
        seller=seller,
        condition=condition,
        image_urls=image_urls,
        payment_options=tuple(payments),
        shipping=shipping,
        promotions=promotions,
    )
    entity = ExtractedEntity(
        kind="product",
        source_key=expected_key,
        url=canonical_url(url),
        title=title,
        description=description,
        price=price,
        currency=currency if price is not None else None,
        availability=availability,
    )
    return ProductDetail(
        entity=entity,
        offer=offer,
        authors=authors,
        isbn=isbn,
        specifications=specs,
        rating_text=text_of(tree, ".ui-pdp-review__rating"),
        review_count_text=text_of(tree, ".ui-pdp-review__amount"),
        catalog=normalize_catalog(
            title, specs, structured, category_hint=category_hint, isbn=isbn
        ),
    )
