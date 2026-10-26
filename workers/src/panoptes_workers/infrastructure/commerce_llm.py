"""Optional, bounded structured-output enrichment of already scoped commerce blocks."""

import json
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Literal

import httpx
from jsonschema.exceptions import ValidationError as SchemaValidationError
from panoptes_contracts.base import Contract
from panoptes_contracts.offers import (
    CommercialEvidence,
    PaymentOption,
    ProductOffer,
    Promotion,
    ShippingQuote,
)
from pydantic import Field, ValidationError

from ..common.commerce import MONEY, amount, deduplicate


class Fact(Contract):
    fragment_id: str
    kind: Literal["payment", "promotion", "shipping"]
    excerpt: str = Field(min_length=1, max_length=2000)
    method: Literal["pix", "cash", "card", "installment"] | None
    amount: str | None
    percent: str | None
    installment_count: int | None
    installment_price: str | None
    code: str | None


class Result(Contract):
    facts: tuple[Fact, ...] = Field(max_length=30)


class CommerceLLM:
    def __init__(self, client):
        self.client = client
        self.key = os.getenv("OPENROUTER_API_KEY", "")
        self.enabled = (
            bool(self.key)
            and os.getenv("COMMERCE_LLM_ENABLED", "true").lower() == "true"
        )

    async def enrich(self, detail, blocks, *, context=None):
        report = detail.offer.commercial_extraction
        if not blocks or report is None:
            return detail
        if not self.enabled:
            return detail.model_copy(
                update={
                    "offer": detail.offer.model_copy(
                        update={
                            "commercial_extraction": report.model_copy(
                                update={"fallback_status": "disabled"}
                            )
                        }
                    )
                }
            )
        # Address-bearing shipping fragments stay local. They are already preserved in the capture.
        blocks = [
            b
            for b in blocks
            if not re.search(
                r"\b\d{5}-?\d{3}\b|entregar em|enviar para", b["text"], re.I
            )
        ]
        bounded = []
        size = 0
        for block in blocks:
            if size + len(block["text"]) > 12000:
                break
            bounded.append(block)
            size += len(block["text"])
        blocks = bounded
        if not blocks:
            return detail
        try:
            agent = await self.client.agent("commerce")
            report = report.model_copy(update={"model": agent["model"]})
            payload = await self.client.invoke(
                "commerce",
                json.dumps(blocks, ensure_ascii=False),
                context=context,
                agent=agent,
            )
            content = payload["choices"][0]["message"]["content"]
            if len(content) > 18000:
                raise ValueError("commerce_output_too_large")
            result = Result.model_validate_json(content)
            values = detail.offer.model_dump()
            payments, promos, shipping = (
                list(detail.offer.payment_options),
                list(detail.offer.promotions),
                list(detail.offer.shipping_options),
            )
            evidence = list(report.evidence)
            resolved = set()
            lookup = {b["id"]: b for b in blocks}
            for fact in result.facts:
                block = lookup.get(fact.fragment_id)
                if (
                    not block
                    or fact.kind != block["kind"]
                    or fact.excerpt not in block["text"]
                ):
                    continue
                quoted_amounts = {
                    amount(m[1]) for m in re.finditer(MONEY, fact.excerpt)
                }
                money = Decimal(fact.amount) if fact.amount else None
                installment = (
                    Decimal(fact.installment_price) if fact.installment_price else None
                )
                if any(
                    v is not None and (not v.is_finite() or v not in quoted_amounts)
                    for v in (money, installment)
                ):
                    continue
                percent = Decimal(fact.percent) if fact.percent else None
                if percent is not None and (
                    not percent.is_finite()
                    or not 0 <= percent <= 100
                    or percent
                    not in {
                        Decimal(m[1].replace(",", "."))
                        for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*%", fact.excerpt)
                    }
                ):
                    continue
                # Only explicit wording can grant a coupon amount or a shipping fee.
                if (
                    fact.kind == "promotion"
                    and money is not None
                    and not re.search(
                        MONEY + r"\s*(?:de\s*)?(?:desconto|off)", fact.excerpt, re.I
                    )
                ):
                    continue
                if (
                    fact.kind == "shipping"
                    and money is not None
                    and not re.search(
                        r"(?:frete|entrega)\s*(?:[:\-]|de)?\s*" + MONEY,
                        fact.excerpt,
                        re.I,
                    )
                ):
                    continue
                if fact.code and not re.search(
                    r"\b" + re.escape(fact.code) + r"\b", fact.excerpt
                ):
                    continue
                if fact.installment_count is not None and (
                    fact.installment_count < 1
                    or not re.search(
                        r"\b" + str(fact.installment_count) + r"\s*(?:x|parcelas?)",
                        fact.excerpt,
                        re.I,
                    )
                ):
                    continue
                common = {
                    "text": block["text"],
                    "conditions": (block["text"],),
                    "extraction_method": "openrouter",
                }
                if (
                    fact.kind == "payment"
                    and fact.method
                    and (money is not None or installment is not None)
                ):
                    method_words = {
                        "pix": r"\bpix\b",
                        "cash": r"boleto|[aà]\s+vista",
                        "card": r"cart[aã]o",
                        "installment": r"\d+\s*(?:x|parcelas?)",
                    }
                    if not re.search(method_words[fact.method], fact.excerpt, re.I):
                        continue
                    if fact.method == "installment" and (
                        fact.installment_count is None or installment is None
                    ):
                        continue
                    if money is not None and re.search(
                        r"m[ií]nim|acima de|limitado|cashback", fact.excerpt, re.I
                    ):
                        continue
                    candidate = PaymentOption(
                        method=fact.method,
                        total_price=money,
                        installment_count=fact.installment_count,
                        installment_price=installment,
                        **common,
                    )
                    if any(
                        p.method == candidate.method and p.total_price is not None
                        for p in payments
                    ):
                        continue
                    payments.append(candidate)
                elif fact.kind == "promotion" and (
                    money is not None or percent is not None or fact.code
                ):
                    if percent is not None and not re.search(
                        r"\d+(?:[.,]\d+)?\s*%\s*(?:de\s*)?(?:desconto|off)",
                        fact.excerpt,
                        re.I,
                    ):
                        continue
                    if any(
                        p.text == block["text"]
                        and (
                            p.discount_amount is not None
                            or p.discount_percent is not None
                            or p.code
                        )
                        for p in promos
                    ):
                        continue
                    promos.append(
                        Promotion(
                            kind="coupon"
                            if fact.code or "cupom" in block["text"].lower()
                            else "promotion",
                            discount_amount=money,
                            discount_percent=percent,
                            code=fact.code,
                            **common,
                        )
                    )
                elif fact.kind == "shipping" and money is not None:
                    if any(
                        s.text == block["text"] and s.price is not None
                        for s in shipping
                    ):
                        continue
                    shipping.append(ShippingQuote(price=money, **common))
                else:
                    continue
                resolved.add(fact.fragment_id)
                evidence.append(
                    CommercialEvidence(
                        field=fact.kind,
                        locator=block["locator"],
                        excerpt=fact.excerpt,
                        method="openrouter",
                    )
                )
            values.update(
                payment_options=deduplicate(payments, lambda p: (p.method, p.text)),
                promotions=deduplicate(promos, lambda p: p.text),
                shipping_options=deduplicate(shipping, lambda s: s.text),
            )
            if values["shipping_options"]:
                values["shipping"] = values["shipping_options"][0]
            usage = payload.get("usage", {})
            report = report.model_copy(
                update={
                    "fallback_status": "completed",
                    "evidence": tuple(evidence),
                    "unresolved": tuple(
                        i for i in report.unresolved if i not in resolved
                    ),
                    "input_tokens": usage.get("prompt_tokens"),
                    "output_tokens": usage.get("completion_tokens"),
                }
            )
            values["commercial_extraction"] = report
            return detail.model_copy(
                update={"offer": ProductOffer.model_validate(values)}
            )
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            ValidationError,
            InvalidOperation,
            SchemaValidationError,
        ):
            return detail.model_copy(
                update={
                    "offer": detail.offer.model_copy(
                        update={
                            "commercial_extraction": report.model_copy(
                                update={"fallback_status": "failed"}
                            )
                        }
                    )
                }
            )
