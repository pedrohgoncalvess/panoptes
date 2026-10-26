"""Parse only explicit commercial amounts; retain the full conditions text."""

import re

from panoptes_contracts.offers import PaymentOption, Promotion, ShippingQuote

from .detail import parse_money, text_of
from .identity import normalize

AMOUNT = r"R\$\s*([\d.]+(?:,\d{1,4})?)"


def explicit_amount(value):
    match = re.search(AMOUNT, value, re.I)
    return parse_money(match.group(1)) if match else None


def enrich_promotions(promotions):
    enriched = []
    for promo in promotions:
        value = promo.text
        percent = re.search(r"(\d+(?:[.,]\d+)?)\s*%", value)
        # Capture discount amounts only adjacent to explicit discount wording.
        amount = re.search(AMOUNT + r"\s*(?:de\s+)?(?:desconto|off)", value, re.I)
        minimum = re.search(
            r"(?:acima de|minim[oa] de|a partir de)\s*" + AMOUNT, value, re.I
        )
        code = re.search(r"(?:codigo|código|cupom)\s*:\s*([A-Z0-9_-]{3,40})\b", value)
        activation = (
            True
            if re.search(
                r"\b(?:ative|ativar|aplique|aplicar|resgate|resgatar)\b",
                normalize(value),
            )
            else None
        )
        updates = {"conditions": (value,)}
        if promo.kind in ("coupon", "discount", "promotion"):
            updates.update(
                discount_percent=parse_money(percent.group(1)) if percent else None,
                discount_amount=parse_money(amount.group(1)) if amount else None,
                minimum_spend=parse_money(minimum.group(1)) if minimum else None,
                code=code.group(1) if code else promo.code,
                requires_activation=activation,
            )
        enriched.append(Promotion.model_validate({**promo.model_dump(), **updates}))
    return tuple(enriched)


def parse_payments(tree):
    payments = []
    seen = set()
    for node in tree.css(
        "#installmentCalculator_feature_div, #installment_feature_div, #pixPrice, [data-payment-method]"
    ):
        value = " ".join(node.text(separator=" ", strip=True).split())
        if not value or value in seen:
            continue
        seen.add(value)
        norm = normalize(value)
        installments = re.search(r"(\d+)\s*x\s*(?:de\s*)?" + AMOUNT, value, re.I)
        if installments:
            payments.append(
                PaymentOption(
                    method="installment",
                    text=value,
                    installment_count=int(installments.group(1)),
                    installment_price=parse_money(installments.group(2)),
                    interest_free=True
                    if "sem juros" in norm
                    else False
                    if "com juros" in norm
                    else None,
                    conditions=(value,),
                )
            )
        if "pix" in norm.split():
            pix = re.search(AMOUNT + r"\s*(?:no|via|com|por)?\s*Pix\b", value, re.I)
            if not pix:
                pix = re.search(r"\bPix\s*[:\-]?\s*" + AMOUNT, value, re.I)
            payments.append(
                PaymentOption(
                    method="pix",
                    text=value,
                    total_price=parse_money(pix.group(1)) if pix else None,
                    conditions=(value,),
                )
            )
    return tuple(payments)


def parse_shipping(tree):
    value = text_of(tree, "#deliveryBlockMessage")
    if not value:
        return None
    norm = normalize(value)
    free = bool(re.search(r"\b(?:frete|entrega)\s+grat(?:is|uita|uito)\b", norm))
    postal = re.search(r"\b(\d{5}-?\d{3})\b", value)
    fee = re.search(r"\b(?:frete|entrega)\s*[:\-]?\s*(?:de\s*)?" + AMOUNT, value, re.I)
    return ShippingQuote(
        text=value,
        price=parse_money(fee.group(1)) if fee else None,
        is_free=True if free else None,
        destination_postal_code=postal.group(1) if postal else None,
        conditions=(value,),
    )
