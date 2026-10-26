import re

from panoptes_contracts.offers import ProductDetail, ProductOffer
from selectolax.lexbor import LexborHTMLParser

from .categories import normalize_catalog
from .commercial import enrich_promotions, parse_payments, parse_shipping
from .detail import parse_product, structured_products, text_of
from .identity import normalize


def parse_catalog_product(html, url, expected_asin, category_hint=None):
    detail = parse_product(html, url, expected_asin)
    tree = LexborHTMLParser(html)
    structured = next(
        (
            item
            for item in structured_products(tree)
            if (not item.get("url") or f"/dp/{expected_asin}" in str(item["url"]))
            and normalize(str(item.get("name", ""))) == normalize(detail.entity.title)
        ),
        {},
    )
    for node in tree.css("script,style,noscript"):
        node.decompose()
    catalog = normalize_catalog(
        detail.entity.title,
        detail.specifications,
        structured,
        category_hint=category_hint,
        isbn=detail.isbn,
    )
    payments = parse_payments(tree)
    shipping = parse_shipping(tree)
    promotions = enrich_promotions(detail.offer.promotions)
    # Preserve text even when the source omitted currency; unapproved amounts stay unknown.
    currency = detail.offer.currency
    if currency is None and any(
        re.search(r"R\$\s*\d", node.text())
        for node in tree.css(
            "#pixPrice,#couponFeature,#deliveryBlockMessage,#installmentCalculator_feature_div,[data-payment-method]"
        )
    ):
        currency = "BRL"
    if currency != "BRL":
        payments = tuple(
            p.model_copy(update={"total_price": None, "installment_price": None})
            for p in payments
        )
        if shipping:
            shipping = shipping.model_copy(update={"price": None})
        promotions = tuple(
            p.model_copy(update={"discount_amount": None, "minimum_spend": None})
            for p in promotions
        )
    offer_data = detail.offer.model_dump()
    offer_data.update(
        payment_options=payments,
        shipping=shipping,
        promotions=promotions,
        currency=currency,
    )
    raw_offer = structured.get("offers", {})
    raw_offer = raw_offer if isinstance(raw_offer, dict) else {}
    if raw_offer.get("@type") == "AggregateOffer":
        raw_offer = {}
    seller = raw_offer.get("seller")
    seller = seller.get("name") if isinstance(seller, dict) else seller
    offer_data["seller"] = (
        detail.offer.seller or text_of(tree, "#merchant-info") or seller
    )
    offer_data["condition"] = (
        str(raw_offer["itemCondition"]).rsplit("/", 1)[-1]
        if raw_offer.get("itemCondition")
        else None
    )
    return ProductDetail.model_validate(
        {
            **detail.model_dump(),
            "catalog": catalog,
            "offer": ProductOffer.model_validate(offer_data),
        }
    )
