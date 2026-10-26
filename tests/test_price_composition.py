from datetime import datetime, timezone

import pytest
from panoptes_contracts.pricing import compose_price


def offer(**changes):
    return {
        "price": "100.00",
        "currency": "BRL",
        "list_price": "150.00",
        "promotions": [{"kind": "coupon", "code": "SAVE10", "discount_percent": "10"}],
        **changes,
    }


def test_unknown_inclusion_never_claims_a_verified_base_or_total():
    result = compose_price(offer())
    assert result["price_without_coupon"] is None
    assert result["total_without_coupon"] is None
    scenario = result["coupon_scenarios"][0]
    assert scenario["savings"] == "10.00"
    assert scenario["price_with_coupon"] == "90.00"
    assert scenario["total_with_shipping"] is None
    assert "unverified" in " ".join(scenario["assumptions"])


def test_explicit_base_cap_shipping_and_no_stacking():
    result = compose_price(
        offer(
            price_without_coupon="120.00",
            price_includes_coupon=True,
            shipping={"price": "15.90", "destination_postal_code": "01001-000"},
            promotions=[
                {"kind": "coupon", "discount_percent": "20", "maximum_discount": "15"},
                {"kind": "coupon", "discount_amount": "5"},
                {"kind": "promotion", "discount_amount": "90", "text": "Cashback"},
            ],
        )
    )
    assert result["total_without_coupon"] == "135.90"
    a, b = result["coupon_scenarios"]
    assert a["savings"] == "15.00" and a["total_with_shipping"] == "120.90"
    assert b["price_with_coupon"] == "115.00"


def test_already_included_coupon_is_not_deducted_twice():
    result = compose_price(offer(price_includes_coupon=True))
    assert result["coupon_scenarios"][0]["status"] == "unknown"
    assert result["coupon_scenarios"][0]["price_with_coupon"] is None


@pytest.mark.parametrize(
    "promo,status",
    [
        ({"discount_amount": "10", "minimum_spend": "101"}, "minimum_not_met"),
        ({"discount_amount": "10", "expires_at": "2026-10-24T00:00:00Z"}, "expired"),
        ({"discount_percent": "101"}, "unknown"),
        ({"discount_percent": "10", "discount_amount": "10"}, "unknown"),
        ({"discount_amount": "NaN"}, "unknown"),
        ({"discount_amount": "-1"}, "unknown"),
        ({}, "unknown"),
    ],
)
def test_unavailable_scenarios_never_produce_savings(promo, status):
    result = compose_price(
        offer(promotions=[{"kind": "coupon", **promo}]),
        now=datetime(2026, 10, 25, tzinfo=timezone.utc),
    )
    scenario = result["coupon_scenarios"][0]
    assert scenario["status"] == status
    assert scenario["savings"] is None
    assert scenario["total_with_shipping"] is None


def test_zero_free_shipping_and_discount_cannot_exceed_price():
    result = compose_price(
        offer(
            price_includes_coupon=False,
            shipping={"price": "0", "is_free": True},
            promotions=[{"kind": "coupon", "discount_amount": "200"}],
        )
    )
    assert result["total_without_coupon"] == "100.00"
    assert result["coupon_scenarios"][0]["total_with_shipping"] == "0.00"


def test_multiple_shipping_options_require_selection_and_missing_currency_is_unknown():
    result = compose_price(
        offer(
            shipping={"price": "0"},
            shipping_options=[{"price": "0"}, {"price": "20"}],
        )
    )
    assert result["shipping_price"] is None
    assert result["coupon_scenarios"][0]["total_with_shipping"] is None
    assert compose_price(offer(currency=None))["advertised_price"] is None


def test_percentage_rounding_uses_decimal():
    result = compose_price(
        offer(price="19.95", promotions=[{"kind": "coupon", "discount_percent": "10"}])
    )
    scenario = result["coupon_scenarios"][0]
    assert scenario["savings"] == "2.00"
    assert scenario["price_with_coupon"] == "17.95"
