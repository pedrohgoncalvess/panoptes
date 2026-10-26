import json
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from panoptes_ai.client import OpenRouter
from panoptes_ai.registry import load_agents
from panoptes_contracts import ExtractedEntity
from panoptes_contracts.offers import PaymentOption, ProductDetail, ProductOffer
from panoptes_workers.common.commerce import extract_commerce
from panoptes_workers.infrastructure.commerce_llm import CommerceLLM


def detail(currency="BRL"):
    return ProductDetail(
        entity=ExtractedEntity(
            kind="product",
            source_key="MLB1234567890",
            url="https://www.mercadolivre.com.br/MLB1234567890",
            title="Produto de teste",
        ),
        offer=ProductOffer(
            price=Decimal("100") if currency else None, currency=currency
        ),
    )


@pytest.mark.parametrize("site", ["amazon_br", "mercado_livre_br", "pichau_br"])
def test_unavailable_collection_preserves_observed_prices(site):
    observed = detail().model_copy(
        update={
            "entity": detail().entity.model_copy(
                update={
                    "price": Decimal("100"),
                    "currency": "BRL",
                    "availability": "out_of_stock",
                }
            ),
            "offer": ProductOffer(
                price=Decimal("100"),
                list_price=Decimal("150"),
                currency="BRL",
                availability="out_of_stock",
                availability_text="Produto Indisponível",
                payment_options=(
                    PaymentOption(
                        method="pix", text="R$ 100 no Pix", total_price=Decimal("100")
                    ),
                ),
            ),
        }
    )
    enriched, _ = extract_commerce(observed, "<h1>Produto</h1>", site)
    assert enriched.entity.price == Decimal("100")
    assert enriched.entity.availability == "out_of_stock"
    assert enriched.offer == observed.offer


@pytest.mark.parametrize(
    "site,html",
    [
        (
            "amazon_br",
            '<div id="pixPrice">R$ 90,00 no Pix</div><div id="installment_feature_div">10x de R$ 10,00 sem juros</div><div id="couponFeature">Ative cupom: TESTE10 de 10% de desconto, acima de R$ 80,00, limitado a R$ 20,00</div><div id="deliveryBlockMessage">Frete R$ 15,90 para CEP 01001-000; entrega em 3 dias</div><div id="availability">Restam apenas 3 unidades em estoque</div>',
        ),
        (
            "mercado_livre_br",
            '<div class="ui-pdp-price__subtitles-item">R$ 90,00 no Pix</div><div class="ui-pdp-price__subtitles-item">10x de R$ 10,00 sem juros</div><div class="ui-pdp-coupons">Ative cupom: TESTE10 de 10% de desconto, acima de R$ 80,00, limitado a R$ 20,00</div><div class="ui-pdp-shipping">Frete R$ 15,90 para CEP 01001-000; entrega em 3 dias</div><div class="ui-pdp-stock-information">Restam apenas 3 unidades em estoque</div>',
        ),
    ],
)
def test_commerce_preserves_conditional_prices_and_evidence(site, html):
    result, _ = extract_commerce(detail(), html, site)
    offer = result.offer
    assert offer.price == Decimal("100")
    assert next(
        p for p in offer.payment_options if p.method == "pix"
    ).total_price == Decimal("90")
    installments = next(p for p in offer.payment_options if p.method == "installment")
    assert installments.total_price == Decimal("100") and installments.total_is_derived
    coupon = offer.promotions[0]
    assert coupon.code == "TESTE10" and coupon.discount_percent == 10
    assert coupon.minimum_spend == 80 and coupon.maximum_discount == 20
    assert offer.shipping.price == Decimal("15.90")
    assert offer.shipping.destination_postal_code == "01001-000"
    assert len(offer.commercial_extraction.evidence) >= 4


def test_stock_lower_bound_not_exact_and_package_not_title():
    html = '<h1>Sofá 3 lugares</h1><div class="ui-pdp-stock-information">Mais de 50 unidades disponíveis</div><table class="ui-pdp-specs__table"><tr><th>Unidades por pacote</th><td>2</td></tr></table>'
    offer = extract_commerce(detail(), html, "mercado_livre_br")[0].offer
    assert offer.stock_qt is None and offer.stock_lower_bound_qt == 51
    assert offer.units_per_pack == 2
    empty = extract_commerce(detail(), "<h1>Sofá 3 lugares</h1>", "mercado_livre_br")[0]
    assert empty.offer.units_per_pack is None


def test_split_money_spans_and_related_product_exclusion():
    html = '<div class="ui-pdp-price__subtitles-item">12x de <span class="andes-money-amount"><span class="andes-money-amount__currency-symbol">R$</span><span class="andes-money-amount__fraction">9</span><span class="andes-money-amount__cents">90</span></span></div><aside>R$ 1,00 no Pix</aside>'
    offer = extract_commerce(detail(), html, "mercado_livre_br")[0].offer
    assert len(offer.payment_options) == 1
    assert offer.payment_options[0].installment_price == Decimal("9.90")
    assert offer.payment_options[0].total_price == Decimal("118.80")


def test_corrects_previous_installment_reader_without_duplicate_or_truncated_cents():
    old = detail().model_copy(
        update={
            "offer": ProductOffer(
                currency="BRL",
                payment_options=(
                    PaymentOption(
                        method="installment",
                        text="6x de R$ 149 87 sem juros",
                        installment_count=6,
                        installment_price=Decimal("149"),
                    ),
                ),
            )
        }
    )
    html = '<div class="ui-pdp-price__subtitles-item">6x de <span class="andes-money-amount"><span class="andes-money-amount__currency-symbol">R$</span><span class="andes-money-amount__fraction">149</span><span class="andes-money-amount__cents">87</span></span> sem juros</div>'
    offer = extract_commerce(old, html, "mercado_livre_br")[0].offer
    assert len(offer.payment_options) == 1
    assert offer.payment_options[0].installment_price == Decimal("149.87")
    assert offer.payment_options[0].total_price == Decimal("899.22")


def test_conditional_shipping_and_unknown_currency():
    for value in (
        "Frete grátis para assinantes Prime acima de R$ 100,00",
        "Entrega grátis",
    ):
        offer = extract_commerce(
            detail(None), f'<div id="deliveryBlockMessage">{value}</div>', "amazon_br"
        )[0].offer
        assert offer.shipping.price is None
    assert (
        extract_commerce(
            detail(), '<div id="deliveryBlockMessage">Entrega grátis</div>', "amazon_br"
        )[0].offer.shipping.price
        == 0
    )


def test_current_ml_shipping_block_preserves_unknown_destination_and_coupon_condition():
    html = '<div class="xprod-lib-shipping-promises__promise">Receba em 3 dias</div><div class="xprod-lib-shipping-highlight-info-summaries__summary">Frete grátis com cupom</div>'
    offer = extract_commerce(detail(), html, "mercado_livre_br")[0].offer
    assert len(offer.shipping_options) == 2
    assert offer.shipping_options[0].delivery_text == "Receba em 3 dias"
    assert offer.shipping_options[1].price is None
    assert offer.shipping_options[1].is_free is None


@pytest.mark.parametrize(
    "variant", ["valid", "hallucinated", "error", "invalid_amount"]
)
async def test_llm_validates_evidence_and_never_discards_deterministic_data(
    monkeypatch, variant
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("COMMERCE_LLM_ENABLED", "true")
    raw = "Pague R$ 90,00 utilizando Pix"
    parsed, blocks = extract_commerce(
        detail(), f'<div id="pixPrice">{raw}</div>', "amazon_br"
    )
    assert blocks

    def handle(request):
        body = json.loads(request.content)
        assert body["response_format"]["type"] == "json_schema"
        assert body["provider"]["require_parameters"]
        assert "test-key" not in request.content.decode()
        if variant == "error":
            return httpx.Response(503)
        fact = {
            "fragment_id": blocks[0]["id"],
            "kind": "payment",
            "excerpt": raw,
            "method": "pix",
            "amount": "90"
            if variant == "valid"
            else "1"
            if variant == "hallucinated"
            else "nonsense",
            "percent": None,
            "installment_count": None,
            "installment_price": None,
            "code": None,
        }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"facts": [fact]})}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 30},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        entry = next(a for a in load_agents() if a["slug"] == "commerce")
        gateway = OpenRouter(None, client)
        gateway.agent = AsyncMock(
            return_value={
                "id": 1,
                "slug": "commerce",
                "model_id": 1,
                "model": entry["model"],
                "prompt": entry["prompt"],
                "metadata": entry["metadata"],
                "structured_output_schema": entry["schema"],
            }
        )
        gateway._begin = AsyncMock(return_value=(1, uuid4()))
        gateway._finish = AsyncMock()
        result = await CommerceLLM(gateway).enrich(parsed, blocks)
    assert result.offer.price == 100
    if variant == "valid":
        assert result.offer.payment_options[0].total_price == 90
        assert result.offer.payment_options[0].extraction_method == "openrouter"
    else:
        assert not result.offer.payment_options


async def test_llm_disabled_without_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    parsed, blocks = extract_commerce(
        detail(), '<div id="pixPrice">Preço exclusivo com Pix</div>', "amazon_br"
    )
    async with httpx.AsyncClient() as client:
        entry = next(a for a in load_agents() if a["slug"] == "commerce")
        gateway = OpenRouter(None, client)
        gateway.agent = AsyncMock(
            return_value={
                "id": 1,
                "slug": "commerce",
                "model_id": 1,
                "model": entry["model"],
                "prompt": entry["prompt"],
                "metadata": entry["metadata"],
                "structured_output_schema": entry["schema"],
            }
        )
        gateway._begin = AsyncMock(return_value=(1, uuid4()))
        gateway._finish = AsyncMock()
        result = await CommerceLLM(gateway).enrich(parsed, blocks)
    assert result.offer.commercial_extraction.fallback_status == "disabled"


@pytest.mark.parametrize(
    "text,includes,base",
    [
        ("Sem cupom: R$ 100,00; com cupom: R$ 90,00", False, "100.00"),
        ("Sem cupom: R$ 120,00; com cupom: R$ 100,00", True, "120.00"),
        ("Cupom de 10% de desconto", None, None),
    ],
)
def test_coupon_price_inclusion_requires_explicit_matching_amount(text, includes, base):
    result, _ = extract_commerce(
        detail(), f'<div id="couponFeature">{text}</div>', "amazon_br"
    )
    assert result.offer.price_includes_coupon is includes
    assert result.offer.price_without_coupon == (Decimal(base) if base else None)
