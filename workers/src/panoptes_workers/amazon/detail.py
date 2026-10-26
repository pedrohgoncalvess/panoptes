import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from panoptes_contracts import ExtractedEntity
from panoptes_contracts.offers import ProductDetail, ProductOffer, Promotion
from panoptes_contracts.sources import captcha_page
from selectolax.lexbor import LexborHTMLParser

from .identity import asin_from_url, normalize, product_url


def text_of(node, selector: str) -> str | None:
    match = node.css_first(selector)
    return (
        " ".join(match.text(separator=" ", strip=True).split()) or None
        if match
        else None
    )


def parse_money(text: str | None) -> Decimal | None:
    if not text or "-" in text:
        return None
    raw = re.sub(r"[^0-9.,]", "", text)
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        value = Decimal(raw) if raw else None
        return (
            value
            if value is not None and value.is_finite() and 0 <= value < Decimal("1e14")
            else None
        )
    except InvalidOperation:
        return None


def structured_products(tree) -> list[dict]:
    products = []

    def collect(value):
        if isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            kinds = value.get("@type", [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if any(kind in ("Book", "Product") for kind in kinds):
                products.append(value)
            collect(value.get("@graph", []))

    for node in tree.css('script[type="application/ld+json"]'):
        try:
            collect(json.loads(node.text()))
        except (ValueError, TypeError):
            continue
    return products


def parse_specifications(tree) -> dict[str, str]:
    details = {}
    for row in tree.css(
        "#productDetails_detailBullets_sections1 tr, #productDetails_techSpec_section_1 tr"
    ):
        key, value = text_of(row, "th"), text_of(row, "td")
        if key and value:
            details[key.strip(" :\u200e\u200f")] = value
    for row in tree.css("#detailBullets_feature_div li"):
        label = row.css_first("span.a-text-bold")
        if label:
            label_text = label.text(separator=" ", strip=True)
            key = " ".join(
                label_text.replace("\u200e", "").replace("\u200f", "").split()
            ).strip(" :")
            value = " ".join(
                row.text(separator=" ", strip=True)
                .replace(label_text, "", 1)
                .replace("\u200e", "")
                .replace("\u200f", "")
                .split()
            ).strip(" :")
            if key and value:
                details[key] = value
    return details


def parse_images(tree) -> tuple[str, ...]:
    urls = []
    for node in tree.css("#imgTagWrapperId img, #imageBlock img, #imgBlkFront"):
        source = node.attributes.get("data-old-hires")
        raw = node.attributes.get("data-a-dynamic-image")
        if raw:
            try:
                variants = json.loads(raw)
                source = source or max(
                    variants, key=lambda key: variants[key][0] * variants[key][1]
                )
            except (ValueError, TypeError, IndexError):
                pass
        source = source or node.attributes.get("src")
        if source:
            urls.append(source)
    return tuple(dict.fromkeys(url for url in urls if url.startswith("https://")))[:10]


def parse_product(html: bytes, url: str, expected_asin: str) -> ProductDetail:
    if captcha_page(url, html):
        raise ValueError("captcha")
    if asin_from_url(url) != expected_asin:
        raise ValueError("redirected_to_different_product")
    tree = LexborHTMLParser(html)
    products = structured_products(tree)
    for node in tree.css("script, style, noscript"):
        node.decompose()
    asin_node = tree.css_first('input#ASIN, input[name="ASIN"]')
    if asin_node and asin_node.attributes.get("value", expected_asin) != expected_asin:
        raise ValueError("product_asin_mismatch")
    canonical = tree.css_first('link[rel="canonical"]')
    if canonical and canonical.attributes.get("href"):
        canonical_url = urljoin(url, canonical.attributes["href"])
        if asin_from_url(canonical_url) != expected_asin:
            raise ValueError("canonical_asin_mismatch")
    title = text_of(tree, "#productTitle")
    structured = next(
        (
            item
            for item in products
            if not item.get("url") or f"/dp/{expected_asin}" in str(item["url"])
        ),
        {},
    )
    if title and structured.get("name"):
        dom_title, data_title = normalize(title), normalize(str(structured["name"]))
        if not (
            dom_title == data_title
            or dom_title.startswith(data_title + " ")
            or data_title.startswith(dom_title + " ")
        ):
            structured = {}
    title = title or structured.get("name")
    if not title:
        raise ValueError("product_layout_not_recognized")
    authors = tuple(
        dict.fromkeys(
            node.text(strip=True)
            for node in tree.css(
                "#bylineInfo .author a.a-link-normal, #bylineInfo .author .a-size-base, [data-book-author]"
            )
        )
    )
    if not authors and structured.get("author"):
        raw = structured["author"]
        raw = raw if isinstance(raw, list) else [raw]
        authors = tuple(
            item.get("name", "") if isinstance(item, dict) else str(item)
            for item in raw
        )
    specifications = parse_specifications(tree)
    isbn = tuple(
        value for key, value in specifications.items() if "isbn" in key.casefold()
    )
    if structured.get("isbn"):
        isbn = tuple(dict.fromkeys((*isbn, str(structured["isbn"]))))
    price_text = text_of(
        tree,
        "#corePrice_feature_div .a-price:not(.a-text-price) .a-offscreen, "
        "#corePriceDisplay_desktop_feature_div .a-price:not(.a-text-price) .a-offscreen, "
        "#apex_desktop .a-price:not(.a-text-price) .a-offscreen, #priceblock_ourprice, #priceblock_dealprice",
    )
    price = parse_money(price_text)
    if price is None:
        for area in tree.css(
            "#corePriceDisplay_desktop_feature_div .priceToPay, #buybox .priceToPay"
        ):
            symbol = text_of(area, ".a-price-symbol")
            whole = text_of(area, ".a-price-whole")
            fraction = text_of(area, ".a-price-fraction")
            if symbol and whole and fraction and re.fullmatch(r"\d{2}", fraction):
                price_text = f"{symbol} {whole.rstrip(',.')} ,{fraction}"
                price = parse_money(price_text)
                break
    if price is None:
        price_text = text_of(tree, '#tmmSwatches [aria-checked="true"] .slot-price')
        price = parse_money(price_text)
    list_price = parse_money(
        text_of(
            tree,
            "#corePrice_feature_div .a-text-price .a-offscreen, "
            "#corePriceDisplay_desktop_feature_div .a-text-price .a-offscreen",
        )
    )
    offers = structured.get("offers") or {}
    offers = offers if isinstance(offers, dict) else {}
    if offers.get("@type") == "AggregateOffer":
        offers = {}
    currency = (
        "BRL" if price_text and "R$" in price_text else offers.get("priceCurrency")
    )
    if price is None and offers.get("price") is not None:
        price = parse_money(str(offers["price"]))
    # A numeric amount without a recognizable currency is not an approved price.
    if not currency or not re.fullmatch(r"[A-Z]{3}", str(currency)):
        currency = None
        price, list_price = None, None
    availability_text = text_of(tree, "#availability")
    availability = "unknown"
    if availability_text:
        stock = availability_text.casefold()
        if any(
            term in stock
            for term in (
                "indispon",
                "não disponível",
                "fora de estoque",
                "sem estoque",
                "out of stock",
                "unavailable",
            )
        ):
            availability = "out_of_stock"
        elif any(
            term in stock for term in ("em estoque", "in stock", "disponível", "restam")
        ):
            availability = "in_stock"
    elif offers.get("availability"):
        state = str(offers["availability"]).rsplit("/", 1)[-1]
        availability = {"InStock": "in_stock", "OutOfStock": "out_of_stock"}.get(
            state, "unknown"
        )
    quantity = re.search(r"(?:restam|only)\s+(\d+)", availability_text or "", re.I)
    promotions = []
    for selector, kind in (
        ("#couponFeature, #couponText, [data-coupon]", "coupon"),
        ("#dealBadge_feature_div, #dealBadgeSupportingText, #dealBadge", "promotion"),
        ("#installmentCalculator_feature_div", "installment"),
        ("#deliveryBlockMessage", "shipping"),
    ):
        for node in tree.css(selector):
            value = " ".join(node.text(separator=" ", strip=True).split())
            if value and value not in [promo.text for promo in promotions]:
                promotions.append(Promotion(kind=kind, text=value))
    offer = ProductOffer(
        price=price,
        list_price=list_price,
        currency=currency,
        availability=availability,
        availability_text=availability_text,
        stock_qt=int(quantity.group(1)) if quantity else None,
        seller=text_of(tree, "#sellerProfileTriggerId"),
        ships_from=text_of(
            tree,
            '#tabular-buybox .tabular-buybox-text[tabular-attribute-name="Enviado por"]',
        ),
        promotions=tuple(promotions),
        image_urls=parse_images(tree),
    )
    return ProductDetail(
        entity=ExtractedEntity(
            kind="product",
            source_key=expected_asin,
            url=product_url(expected_asin),
            title=title,
            description=text_of(
                tree, "#bookDescription_feature_div, #productDescription"
            ),
            price=offer.price,
            currency=offer.currency if offer.price is not None else None,
            availability=offer.availability,
        ),
        offer=offer,
        authors=authors,
        isbn=isbn,
        specifications=specifications,
        rating_text=text_of(tree, "#acrPopover"),
        review_count_text=text_of(tree, "#acrCustomerReviewText"),
    )
