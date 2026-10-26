"""Identity-bound product data. Never search the whole page for a price."""

import json
import re
from urllib.parse import urljoin, urlsplit

from panoptes_contracts import ExtractedEntity
from panoptes_contracts.offers import (
    CommercialEvidence,
    CommercialExtraction,
    PaymentOption,
    ProductDetail,
    ProductOffer,
)
from panoptes_contracts.sources import SOURCES, captcha_page
from selectolax.lexbor import LexborHTMLParser

from ..common.catalog import normalize_catalog
from ..common.commerce import payment_facts
from ..common.matching import normalize
from ..mercado_livre.product import money, structured_products, text_of
from .identity import canonical_url, key_from_url

CONFIG = {
    "kabum_br": {
        "price": '.finalPrice,#price,[data-testid="price-value"],.priceCard',
        "stock": '[data-testid="product-unavailable"],.available',
        "card": '.regularPrice,[data-testid="price-installments"]',
        "list": ".oldPrice",
        "seller": '#sellerName,[data-testid="seller-name"]',
    },
    "pichau_br": {
        "price": '[class*="-price_vista-"],[class$="-price_vista"]',
        "card": '[class*="-price_total"],[class*="-price_parcelado_text"],[class*="-priceTotal"],[class*="-installmentsPrice"] > p:not([class*="-priceTotal"])',
        "list": '[class*="-price_from"],[class*="-dePor"] s',
        "stock": '[class*="-availability"],[class*="-stock"],[class*="-product_info_stock"],[class*="-priceWrapper"] [class*="-addToCartWrapper"]',
        "seller": '[data-cy="seller-name"]',
    },
    "terabyte_br": {
        "price": ".AreaInfvlrpdt .valVista:not(.prodEsgPreco)",
        "card": ".AreaInfvlrpdt .valParc,.AreaInfvlrpdt .val-parc",
        "list": ".AreaInfvlrpdt .precoDe",
        "stock": ".AreaInfvlrpdt .disp-ok,#indisponivel",
        "seller": ".AreaInfvlrpdt .vendPor span",
    },
}


def next_data(tree):
    node = tree.css_first("script#__NEXT_DATA__")
    try:
        props = (
            json.loads(node.text()).get("props", {}).get("pageProps", {})
            if node
            else {}
        )
        if isinstance(props.get("data"), str):
            props["data"] = json.loads(props["data"])
        return props
    except (ValueError, TypeError, AttributeError):
        return {}


def selected_product(tree, site, key, title):
    for item in structured_products(tree):
        raw_offer = item.get("offers")
        offer_url = raw_offer.get("url") if isinstance(raw_offer, dict) else None
        identity_url = item.get("url") or item.get("@id") or offer_url
        if identity_url:
            try:
                if key_from_url(site, identity_url) == key:
                    return item
            except ValueError:
                continue
        elif title and normalize(str(item.get("name", ""))) == normalize(title):
            return item
    return {}


def price_value(value):
    # Both 2.199,99 and 2,199.99 occur in Pichau SSR/hydrated DOM.
    if not isinstance(value, str):
        return money(value)
    raw = value.replace("\xa0", " ")
    if not re.fullmatch(r"\s*(?:R\$\s*)?\d[\d.,]*\s*", raw):
        return None
    if "." in raw and "," in raw and raw.rfind(".") > raw.rfind(","):
        raw = raw.replace(",", "")
    return money(raw)


def parse_product(site, html, url, expected_key, category_hint=None):
    if captcha_page(url, html):
        raise ValueError("captcha")
    if key_from_url(site, url) != expected_key:
        raise ValueError("redirected_to_different_product")
    tree = LexborHTMLParser(html)
    canonical = tree.css_first('link[rel="canonical"]')
    if canonical and canonical.attributes.get("href"):
        href = urljoin(url, canonical.attributes["href"])
        if key_from_url(site, href) != expected_key:
            raise ValueError("canonical_source_key_mismatch")
        url = href
    title = text_of(tree, "h1")
    structured = selected_product(tree, site, expected_key, title)
    title = title or structured.get("name")
    if not title:
        raise ValueError("product_layout_not_recognized")
    data = next_data(tree).get("product", {}) if site == "kabum_br" else {}
    if data and str(data.get("id")) != expected_key:
        raise ValueError("product_source_key_mismatch")
    raw_offer = structured.get("offers", {})
    # Aggregate/multiple offers need explicit seller selection, never use lowPrice.
    offer = (
        raw_offer
        if isinstance(raw_offer, dict) and raw_offer.get("@type") in (None, "Offer")
        else {}
    )
    for node in tree.css("script,style,noscript,header,footer"):
        node.decompose()
    config = CONFIG[site]
    evidence, unresolved = [], []
    heading = tree.css_first("h1")
    scope = heading.parent if site == "pichau_br" and heading else tree
    if (
        site == "pichau_br"
        and "-mainContentColumn" in scope.attributes.get("class", "")
        and scope.parent is not None
        and len(scope.parent.css("h1")) == 1
        and scope.parent.css_first('[class*="-priceWrapper"]') is not None
    ):
        # Builder kits put their buy box in a sibling of the title column.
        scope = scope.parent

    def record(field, locator, value):
        if value:
            evidence.append(
                CommercialEvidence(
                    field=field, locator=locator, excerpt=str(value)[:2000]
                )
            )

    price_text = text_of(scope, config["price"])
    price = price_value(price_text)
    record("price", config["price"], price_text)
    currency = "BRL" if price_text and "R$" in price_text else None
    if currency is None:
        price = None
    availability_text = (
        " ".join(
            n.text(separator=" ", strip=True) for n in scope.css(config["stock"])
        ).strip()
        or None
    )
    # Scope generic labels to the product info, excluding related-product cards.
    info = scope if site == "pichau_br" else heading.parent if heading else None
    if site == "kabum_br":
        info = tree.css_first("#main-content")
    info_text = info.text(separator=" ", strip=True) if info else ""
    norm = normalize((availability_text or "") + " " + info_text)
    availability = {
        "InStock": "in_stock",
        "OutOfStock": "out_of_stock",
        "SoldOut": "out_of_stock",
    }.get(str(offer.get("availability", "")).rsplit("/", 1)[-1], "unknown")
    if data.get("available") is False:
        availability = "out_of_stock"
    elif data.get("available") is True:
        availability = "in_stock"
    if any(
        marker in norm
        for marker in (
            "produto esgotado",
            "produto indisponivel",
            "todos vendidos",
            "sem estoque",
        )
    ):
        availability = "out_of_stock"
    elif any(marker in norm for marker in ("produto disponivel", "pronta entrega")):
        availability = "in_stock"
    if "atualizando informacoes" in norm:
        availability = "unknown"
        unresolved.append("availability_refresh_pending")
    if availability_text:
        record("availability", config["stock"], availability_text)
    elif offer.get("availability"):
        record("availability", "Product.offers.availability", offer["availability"])
    if price is None and offer.get("priceCurrency") == "BRL":
        price = price_value(offer.get("price"))
        currency = "BRL"
        record("price", "Product.offers.price", offer.get("price"))
    payments = []
    if price_text and price is not None:
        payments.append(
            PaymentOption(
                method="pix",
                text=price_text + " à vista no Pix",
                total_price=price,
                conditions=("a partir de",)
                if site == "pichau_br" and scope.css_first('[class*="-aPartir"]')
                else (),
            )
        )
    for node in scope.css(config["card"]):
        value = node.text(separator=" ", strip=True)
        record("payment_options", config["card"], value)
        if (
            "price_total" in node.attributes.get("class", "")
            or "priceTotal" in node.attributes.get("class", "")
            or "valParc" in node.attributes.get("class", "").split()
        ):
            total = price_value(value)
            if total is not None and "R$" in value:
                payments.append(
                    PaymentOption(method="card", text=value, total_price=total)
                )
        else:
            payment_text = value
            if site == "pichau_br":
                # Builder SSR uses US separators even though its currency is BRL.
                def localize(match):
                    if "." not in match[0] or match[0].rfind(".") < match[0].rfind(","):
                        return match[0]
                    parsed = price_value(match[0])
                    return (
                        "R$ " + format(parsed, "f").replace(".", ",")
                        if parsed is not None
                        else match[0]
                    )

                payment_text = re.sub(r"R\$\s*[\d.,]+", localize, value)
            facts = payment_facts(payment_text)
            if payment_text != value:
                facts = [
                    fact.model_copy(
                        update={
                            "text": value,
                            "conditions": (value,) if fact.conditions else (),
                        }
                    )
                    for fact in facts
                ]
            payments.extend(facts)
    if site == "kabum_br" and data:
        # Bound to pageProps.product.id, not recursively searched recommendations.
        prices = data.get("prices", {})
        if availability == "in_stock" or data.get("available") is True:
            if price_text is None:
                price = price_value(prices.get("priceWithDiscount"))
                currency = "BRL" if price is not None else currency
                record(
                    "price",
                    "#__NEXT_DATA__:pageProps.product.prices.priceWithDiscount",
                    price,
                )
                if price is not None:
                    payments.append(
                        PaymentOption(
                            method="pix", text="Preço à vista no Pix", total_price=price
                        )
                    )
            card_price = price_value(prices.get("price"))
            if card_price is not None:
                payments.append(
                    PaymentOption(
                        method="card", text="Preço no cartão", total_price=card_price
                    )
                )
        seller = data.get("sellerName")
    else:
        seller = None
    raw_seller = offer.get("seller")
    seller = (
        text_of(scope, config["seller"])
        or seller
        or (raw_seller.get("name") if isinstance(raw_seller, dict) else raw_seller)
    )
    list_text = text_of(scope, config["list"])
    list_match = re.search(r"R\$\s*([\d.,]+)", list_text or "")
    list_price = price_value(list_match[1]) if list_match else None
    if site == "pichau_br" and scope.css_first('[class*="-priceWrapper"]'):
        record("list_price", config["list"], list_text)
    # Availability describes this collection; displayed prices remain observable facts.
    if price is None:
        unresolved.append("price")
    stock_text = (
        text_of(tree, ".AreaInfvlrpdt .discount-bar__left")
        if site == "terabyte_br"
        else None
    )
    stock_match = re.search(r"\b[Rr]estam\s+(\d+)\b", stock_text or "")
    stock = int(stock_match[1]) if stock_match and availability == "in_stock" else None
    if stock_text:
        record("stock_qt", ".AreaInfvlrpdt .discount-bar__left", stock_text)
    if availability == "unknown":
        unresolved.append("availability")
    if currency != "BRL":
        price, list_price, payments = None, None, []
    images = structured.get("image", [])
    images = [images] if isinstance(images, (str, dict)) else images
    image_urls = []
    for image in images if isinstance(images, list) else []:
        image = image.get("url", "") if isinstance(image, dict) else image
        if (
            isinstance(image, str)
            and urlsplit(image).scheme == "https"
            and urlsplit(image).hostname in SOURCES[site].image_hosts
        ):
            image_urls.append(image)
    specs = {}
    for row in tree.css(
        "#main-content table tr,#technicalInfoSection table tr,#especificacoes table tr"
    ):
        cells = row.css("th,td")
        if len(cells) == 2:
            specs[cells[0].text(strip=True).strip(" :")] = cells[1].text(
                separator=" ", strip=True
            )
    for prop in structured.get("additionalProperty", []):
        if (
            isinstance(prop, dict)
            and prop.get("name")
            and prop.get("value") is not None
        ):
            specs[str(prop["name"])] = str(prop["value"])
    result = ProductOffer(
        price=price,
        currency=currency,
        list_price=list_price,
        availability=availability,
        availability_text=availability_text,
        stock_qt=stock,
        seller=seller,
        condition=str(offer["itemCondition"]).rsplit("/", 1)[-1]
        if offer.get("itemCondition")
        else None,
        image_urls=tuple(dict.fromkeys(image_urls))[:10],
        payment_options=tuple(payments),
        commercial_extraction=CommercialExtraction(
            evidence=tuple(evidence), unresolved=tuple(unresolved)
        ),
    )
    return ProductDetail(
        entity=ExtractedEntity(
            kind="product",
            source_key=expected_key,
            url=canonical_url(site, url),
            title=title,
            description=structured.get("description"),
            price=price,
            currency=currency if price is not None else None,
            availability=availability,
        ),
        offer=result,
        specifications=specs,
        catalog=normalize_catalog(
            title, specs, structured, category_hint=category_hint
        ),
    )
