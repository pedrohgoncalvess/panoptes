"""Conservative price composition over a single captured offer.

Scenarios never assert customer eligibility or coupon stacking. Unknown coupon
inclusion is kept unknown; the displayed price is only an explicit assumption.
"""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel


class CouponScenario(BaseModel):
    promotion_index: int
    code: str | None = None
    status: Literal["simulated", "expired", "minimum_not_met", "unknown"]
    base_price: str | None = None
    savings: str | None = None
    price_with_coupon: str | None = None
    total_with_shipping: str | None = None
    assumptions: list[str]


class PriceComposition(BaseModel):
    advertised_price: str | None = None
    price_includes_coupon: bool | None = None
    price_without_coupon: str | None = None
    shipping_price: str | None = None
    total_without_coupon: str | None = None
    coupon_scenarios: list[CouponScenario]
    notes: list[str]


def money(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def render(value):
    return None if value is None else format(value, "f")


def compose_price(offer: dict[str, Any], *, now=None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    price = money(offer.get("price")) if offer.get("currency") else None
    includes = offer.get("price_includes_coupon")
    includes = includes if isinstance(includes, bool) else None
    base = money(offer.get("price_without_coupon")) if offer.get("currency") else None
    if base is None and includes is False:
        base = price
    shipping = offer.get("shipping") or {}
    # Multiple delivery choices require a selection, never choose the cheapest.
    options = offer.get("shipping_options") or []
    if len(options) == 1:
        shipping = options[0]
    fee = (
        money(shipping.get("price"))
        if len(options) <= 1 and offer.get("currency")
        else None
    )
    if (
        fee is None
        and shipping.get("is_free") is True
        and not shipping.get("conditions")
        and len(options) <= 1
        and offer.get("currency")
    ):
        fee = Decimal(0)
    notes = [
        "List price is a reference price, not proof of the price without a coupon.",
        "Shipping applies only to the captured destination and conditions; unknown is not zero.",
        "Payment prices and cashback are not combined with coupons automatically.",
        "Scenarios use one advertised purchase unit; quantity and basket changes are not simulated.",
    ]
    scenarios = []
    for index, promo in enumerate(offer.get("promotions") or []):
        if promo.get("kind") != "coupon":
            continue
        assumed_base = base if base is not None else price if includes is None else None
        assumptions = [
            "Customer eligibility, payment compatibility and activation must be checked.",
            "Coupons are evaluated individually, without stacking.",
        ]
        if base is None and includes is None:
            assumptions.append(
                "Assumes the advertised price does not already include this coupon; this is unverified."
            )
        status = "simulated"
        expiry = promo.get("expires_at")
        if expiry:
            try:
                expires = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
                if expires.tzinfo is None:
                    status = "unknown"
                elif expires <= now:
                    status = "expired"
            except ValueError:
                status = "unknown"
        amount, percent = (
            money(promo.get("discount_amount")),
            money(promo.get("discount_percent")),
        )
        minimum, maximum = (
            money(promo.get("minimum_spend")),
            money(promo.get("maximum_discount")),
        )
        if status == "simulated":
            if (
                assumed_base is None
                or (amount is None and percent is None)
                or (amount is not None and percent is not None)
                or (percent is not None and percent > 100)
            ):
                status = "unknown"
            elif minimum is not None and assumed_base < minimum:
                status = "minimum_not_met"
        savings = final = total = None
        if status == "simulated":
            savings = amount if amount is not None else assumed_base * percent / 100
            savings = min(
                savings, assumed_base, maximum if maximum is not None else assumed_base
            )
            savings = savings.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            savings = min(savings, assumed_base)
            final = assumed_base - savings
            total = final + fee if fee is not None else None
        scenarios.append(
            CouponScenario(
                promotion_index=index,
                code=promo.get("code"),
                status=status,
                base_price=render(assumed_base),
                savings=render(savings),
                price_with_coupon=render(final),
                total_with_shipping=render(total),
                assumptions=assumptions,
            )
        )
    return PriceComposition(
        advertised_price=render(price),
        price_includes_coupon=includes,
        price_without_coupon=render(base),
        shipping_price=render(fee),
        total_without_coupon=render(base + fee)
        if base is not None and fee is not None
        else None,
        coupon_scenarios=scenarios,
        notes=notes,
    ).model_dump()


def with_composition(row):
    value = dict(row)
    value["price_composition"] = compose_price(value)
    return value
