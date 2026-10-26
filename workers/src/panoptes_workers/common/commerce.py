"""Commercial facts from product blocks, never recommendations or account chrome."""

import re
from decimal import Decimal, InvalidOperation

from panoptes_contracts.offers import (
    CommercialEvidence,
    CommercialExtraction,
    PaymentOption,
    ProductOffer,
    Promotion,
    ShippingQuote,
)
from selectolax.lexbor import LexborHTMLParser

from .matching import normalize

MONEY = r"R\$\s*([\d.]+(?:,\d{1,4})?)"
SELECTORS = {
    "amazon_br": {
        "payment": "#pixPrice,[data-payment-method],#installmentCalculator_feature_div,#installment_feature_div,#apex_desktop .a-price + span",
        "promotion": "#couponFeature,#promoPriceBlockMessage_feature_div,#promotions_feature_div",
        "shipping": "#deliveryBlockMessage,#mir-layout-DELIVERY_BLOCK",
        "stock": "#availability",
        "package": "#productDetails_detailBullets_sections1 tr,#productDetails_techSpec_section_1 tr,#detailBullets_feature_div li",
    },
    "mercado_livre_br": {
        "payment": ".ui-pdp-price__subtitles-item,.ui-pdp-price__subtitles,.ui-pdp-price__payment-methods,.ui-pdp-payment-methods",
        "promotion": ".ui-pdp-promotions-pill,.ui-pdp-coupons,.ui-pdp-promotions",
        "shipping": ".ui-pdp-shipping,.ui-pdp-shipping__message,.xprod-lib-shipping-promises__promise,.xprod-lib-shipping-highlight-info-summaries__summary",
        "stock": ".ui-pdp-stock-information,.ui-pdp-buybox__quantity__available,.ui-pdp-buybox__quantity",
        "package": ".ui-pdp-specs__table tr",
    },
}


def amount(raw):
    try:
        value = Decimal(raw.replace(".", "").replace(",", "."))
        return value if value.is_finite() and 0 <= value < Decimal("1e14") else None
    except InvalidOperation:
        return None


def fragments(html, site):
    tree = LexborHTMLParser(html)
    for node in tree.css("script,style,noscript"):
        node.decompose()
    result = []
    seen = set()
    for kind, selector in SELECTORS.get(site, {}).items():
        for node in tree.css(selector):
            # Mercado Livre splits money into fraction/cents spans. Join them before text extraction.
            for price in node.css(".andes-money-amount"):
                fraction = price.css_first(".andes-money-amount__fraction")
                cents = price.css_first(".andes-money-amount__cents")
                symbol = price.css_first(".andes-money-amount__currency-symbol")
                if fraction and symbol and symbol.text(strip=True) == "R$":
                    price.replace_with(
                        "R$ "
                        + fraction.text(strip=True)
                        + ","
                        + (cents.text(strip=True) if cents else "00")
                    )
            value = " ".join(node.text(separator=" ", strip=True).split())
            if not value or len(value) > 2000 or (kind, value) in seen:
                continue
            seen.add((kind, value))
            result.append(
                {
                    "id": str(len(result)),
                    "kind": kind,
                    "locator": selector,
                    "text": value,
                }
            )
            if len(result) >= 30:
                return result
    return result


def payment_facts(value):
    norm = normalize(value)
    result = []
    installment = re.search(
        r"\b(\d{1,3})\s*(?:x|parcelas?(?:\s+de)?)\s*(?:de\s*)?" + MONEY, value, re.I
    )
    if installment and int(installment[1]) > 0:
        count, price = int(installment[1]), amount(installment[2])
        if price is not None:
            result.append(
                PaymentOption(
                    method="installment",
                    text=value,
                    installment_count=count,
                    installment_price=price,
                    total_price=price * count,
                    total_is_derived=True,
                    interest_free=True
                    if "sem juros" in norm
                    else False
                    if "com juros" in norm
                    else None,
                    conditions=(value,),
                )
            )
    for method, keyword in (
        ("pix", "pix"),
        ("cash", r"boleto|à\s+vista"),
        ("card", r"cart[aã]o"),
    ):
        # Amount must be adjacent to its method; do not apply a coupon or installment amount.
        match = re.search(
            MONEY + r"\s*(?:no|via|com|por|em|à)?\s*(?:" + keyword + r")\b", value, re.I
        )
        match = match or re.search(
            r"\b(?:" + keyword + r")\s*[:\-]?\s*" + MONEY, value, re.I
        )
        if match and amount(match[1]) is not None:
            result.append(
                PaymentOption(
                    method=method,
                    text=value,
                    total_price=amount(match[1]),
                    conditions=(value,),
                )
            )
    return result


def promotion_fact(value):
    norm = normalize(value)
    percent = re.search(
        r"(\d+(?:[.,]\d+)?)\s*%\s*(?:de\s*)?(?:desconto|off)", value, re.I
    )
    discount = re.search(MONEY + r"\s*(?:de\s*)?(?:desconto|off)", value, re.I)
    minimum = re.search(
        r"(?:acima de|m[ií]nim[oa](?:\s+de)?|a partir de|compras? de)\s*" + MONEY,
        value,
        re.I,
    )
    maximum = re.search(
        r"(?:limitado a|m[aá]ximo(?:\s+de)?|at[eé])\s*" + MONEY, value, re.I
    )
    code = re.search(r"(?:c[oó]digo|cupom)\s*:\s*([A-Z0-9_-]{3,40})\b", value)
    # Cashback is retained as a conditional promotion, never deducted from the price.
    return Promotion(
        kind="coupon"
        if "cupom" in norm or "coupon" in norm
        else "discount"
        if discount or percent
        else "promotion",
        text=value,
        code=code[1] if code else None,
        discount_amount=amount(discount[1]) if discount else None,
        discount_percent=Decimal(percent[1].replace(",", "."))
        if percent and Decimal(percent[1].replace(",", ".")) <= 100
        else None,
        minimum_spend=amount(minimum[1]) if minimum else None,
        maximum_discount=amount(maximum[1]) if maximum else None,
        requires_activation=True
        if re.search(r"\b(?:ative|ativar|aplique|aplicar|resgate|resgatar)\b", norm)
        else None,
        conditions=(value,),
    )


def shipping_fact(value):
    norm = normalize(value)
    fee = re.search(r"(?:frete|entrega)\s*(?:[:\-]|de)?\s*" + MONEY, value, re.I)
    free = bool(re.search(r"\b(?:frete|entrega)\s+grat(?:is|uita|uito)\b", norm))
    postal = re.search(r"\b\d{5}-?\d{3}\b", value)
    conditional = bool(
        re.search(
            r"\b(?:acima|a partir|prime|full|assinantes|primeira compra|compras de|cupom|meli|meliplus)\b",
            norm,
        )
    )
    return ShippingQuote(
        text=value,
        price=amount(fee[1])
        if fee
        else Decimal(0)
        if free and not conditional
        else None,
        is_free=True if free and not conditional else None,
        destination_postal_code=postal[0] if postal else None,
        delivery_text=value
        if any(
            word in norm for word in ("chega", "receba", "amanha", "dias", "entrega")
        )
        else None,
        conditions=(value,),
    )


def deduplicate(items, key):
    result = {}
    for item in items:
        result[key(item)] = item
    return tuple(result.values())


def commercial_text_key(value):
    return re.sub(r"[^a-z0-9]", "", normalize(value))


def extract_commerce(detail, html, site):
    package_units = (
        detail.catalog.attributes.get("units_per_pack") if detail.catalog else None
    )
    if detail.offer.units_per_pack is None and package_units is not None:
        detail = detail.model_copy(
            update={
                "offer": detail.offer.model_copy(
                    update={"units_per_pack": package_units}
                )
            }
        )
    blocks = fragments(html, site)
    if not blocks:
        return detail, []
    offer = detail.offer
    values = offer.model_dump()
    payments, promos, shipping = list(offer.payment_options), list(offer.promotions), []
    evidence, unresolved = [], []
    for block in blocks:
        kind, value = block["kind"], block["text"]
        norm = normalize(value)
        if kind == "payment":
            facts = payment_facts(value)
            if facts:
                # Fraction/cents spans change whitespace when converted to a localized amount.
                # Replace the earlier same-block interpretation rather than retain a truncated price.
                previous = [
                    p
                    for p in payments
                    if commercial_text_key(p.text) == commercial_text_key(value)
                ]
                payments = [p for p in payments if p not in previous]
                corrected = []
                for fact in facts:
                    reported = next(
                        (
                            p
                            for p in previous
                            if p.method == fact.method
                            and p.total_price is not None
                            and not p.total_is_derived
                        ),
                        None,
                    )
                    if reported and fact.total_is_derived:
                        fact = fact.model_copy(
                            update={
                                "total_price": reported.total_price,
                                "total_is_derived": False,
                            }
                        )
                    corrected.append(fact)
                facts = corrected
            payments.extend(facts)
            if not facts:
                unresolved.append(block["id"])
        elif kind == "promotion":
            # Only explicit same-block wording can establish a coupon-free base.
            without = re.search(r"sem cupom\s*[:\-]?\s*" + MONEY, value, re.I)
            without = without or re.search(MONEY + r"\s*sem cupom", value, re.I)
            if without and amount(without[1]) is not None:
                values["price_without_coupon"] = amount(without[1])
            with_coupon = re.search(r"com cupom\s*[:\-]?\s*" + MONEY, value, re.I)
            with_coupon = with_coupon or re.search(MONEY + r"\s*com cupom", value, re.I)
            if (
                with_coupon
                and amount(with_coupon[1]) == offer.price
                and offer.price is not None
            ):
                values["price_includes_coupon"] = True
            elif (
                without
                and amount(without[1]) == offer.price
                and offer.price is not None
            ):
                values["price_includes_coupon"] = False
            fact = promotion_fact(value)
            promos.append(fact)
            if (
                fact.discount_amount is None
                and fact.discount_percent is None
                and fact.code is None
            ):
                unresolved.append(block["id"])
        elif kind == "shipping":
            fact = shipping_fact(value)
            shipping.append(fact)
            if fact.price is None and fact.is_free is None:
                unresolved.append(block["id"])
        elif kind == "stock":
            more = re.search(r"mais de\s+(\d+)\s+(?:unidades?|disponiveis)", norm)
            exact = re.search(
                r"(?:restam|apenas|somente)\s+(\d+)\s+(?:unidades?|em estoque)", norm
            )
            exact = exact or re.search(r"\b(\d+)\s+(?:unidades?\s+)?disponiveis", norm)
            limit = re.search(
                r"(?:limite|maximo)\s*(?:de|por compra|:)??\s*(\d+)\s*unidades?", norm
            )
            if more:
                values["stock_lower_bound_qt"] = int(more[1]) + 1
                values["stock_qt"] = None
            elif exact:
                values["stock_qt"] = int(exact[1])
            if limit and int(limit[1]) > 0:
                values["maximum_purchase_qt"] = int(limit[1])
            minimum = re.search(
                r"(?:compra minima|minimo de)\s*:?\s*(\d+)\s*unidades?", norm
            )
            if minimum and int(minimum[1]) > 0:
                values["minimum_purchase_qt"] = int(minimum[1])
        elif kind == "package":
            count = re.search(
                r"(?:unidades por (?:pacote|embalagem)|quantidade (?:de unidades|por pacote))\s*:?\s*(\d+)\b",
                norm,
            )
            if count and int(count[1]) > 0:
                values["units_per_pack"] = int(count[1])
            else:
                continue
        evidence.append(
            CommercialEvidence(field=kind, locator=block["locator"], excerpt=value)
        )
    # Existing unstructured records from the site parser are superseded by the richer same-text record.
    values["payment_options"] = deduplicate(
        payments, lambda p: (p.method, normalize(p.text))
    )
    values["promotions"] = deduplicate(promos, lambda p: normalize(p.text))
    values["shipping_options"] = deduplicate(shipping, lambda s: normalize(s.text))
    if shipping:
        values["shipping"] = shipping[0]
    if offer.currency not in (None, "BRL"):
        return detail, []
    if offer.currency is None and any(re.search(MONEY, b["text"]) for b in blocks):
        values["currency"] = "BRL"
    if values["currency"] is None:
        values["shipping_options"] = tuple(
            s.model_copy(update={"price": None}) for s in values["shipping_options"]
        )
        if values["shipping"]:
            values["shipping"] = values["shipping"].model_copy(update={"price": None})
    values["commercial_extraction"] = CommercialExtraction(
        evidence=tuple(evidence), unresolved=tuple(unresolved)
    )
    return detail.model_copy(update={"offer": ProductOffer.model_validate(values)}), [
        b for b in blocks if b["id"] in unresolved
    ]
