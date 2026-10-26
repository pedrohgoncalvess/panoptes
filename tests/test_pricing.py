from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth.router import current_user
from panoptes_backend.catalog import pricing_repository, products_repository, repository
from panoptes_backend.catalog.router import session_dependency
from panoptes_backend.main import create_app
from panoptes_workers.amazon.product import parse_catalog_product
from panoptes_workers.workflow.pricing_repository import save_offer

FIXTURES = Path(__file__).resolve().parents[1] / "workers/parsers/amazon-product"


async def test_relational_offer_persistence_uses_decimal_and_captured_timestamp():
    detail = parse_catalog_product(
        (FIXTURES / "television.html").read_bytes(),
        "https://www.amazon.com.br/dp/B0TV500001",
        "B0TV500001",
    )
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one.side_effect = [7, 8]
    result.mappings.return_value.one_or_none.return_value = None
    session.execute.return_value = result
    await save_offer(session, 3, detail.offer, 4, 5)
    calls = session.execute.await_args_list
    financial = next(
        c for c in calls if 'INSERT INTO "pricing"."observation"' in str(c.args[0])
    )
    assert financial.args[1]["price"] == Decimal("2999.90")
    assert isinstance(financial.args[1]["price"], Decimal)
    assert financial.args[1]["job"] == 5 and financial.args[1]["source"] == 4
    assert "h.captured_at" in str(financial.args[0])
    coupon = next(
        c
        for c in calls
        if 'INSERT INTO "pricing"."promotion"' in str(c.args[0])
        and c.args[1]["kind"] == "coupon"
    )
    assert coupon.args[1]["id"] == 8 and coupon.args[1]["code"] == "TV10"
    assert coupon.args[1]["minimum"] == Decimal("2000.00")
    assert coupon.args[1]["activation"] is True
    installments = next(
        c
        for c in calls
        if 'INSERT INTO "pricing"."payment_option"' in str(c.args[0])
        and c.args[1]["method"] == "installment"
    )
    assert installments.args[1]["count"] == 10 and installments.args[1][
        "price"
    ] == Decimal("299.99")
    assert installments.args[1]["total"] is None
    shipping = next(
        c for c in calls if 'INSERT INTO "pricing"."shipping_quote"' in str(c.args[0])
    )
    assert (
        shipping.args[1]["price"] == Decimal("15.90")
        and shipping.args[1]["postal"] == "01001-000"
    )
    session.commit.assert_not_awaited()


async def test_catalog_and_offer_history_endpoints_are_authenticated(monkeypatch):
    uid, offer_id = uuid4(), uuid4()
    monkeypatch.setattr(repository, "find_target", AsyncMock(return_value={"id": 1}))
    monkeypatch.setattr(products_repository, "exists", AsyncMock(return_value=True))
    monkeypatch.setattr(
        products_repository,
        "listings",
        AsyncMock(return_value=[{"public_id": uid, "listing_entity_id": uid}]),
    )
    monkeypatch.setattr(
        products_repository,
        "list_products",
        AsyncMock(
            return_value=[{"public_id": uid, "category": "television", "variants": []}]
        ),
    )
    monkeypatch.setattr(
        pricing_repository,
        "list_offers",
        AsyncMock(
            return_value=[
                {
                    "public_id": offer_id,
                    "price": "2999.9000",
                    "currency": "BRL",
                    "is_current": True,
                    "price_includes_coupon": False,
                    "promotions": [{"kind": "coupon", "discount_percent": "10"}],
                    "shipping": {"price": "15.90"},
                }
            ]
        ),
    )
    monkeypatch.setattr(
        pricing_repository, "offer_exists", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        pricing_repository,
        "history",
        AsyncMock(return_value=[{"price": "2799.9000", "promotions": []}]),
    )
    app = create_app()
    paths = [
        "/catalog/products?category=television",
        f"/catalog/products/{uid}/listings",
        f"/products/{uid}/offers",
        f"/offers/{offer_id}/observations",
    ]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for path in paths:
            assert (await client.get(path)).status_code == 401
        app.dependency_overrides[current_user] = lambda: {"name": "admin"}

        async def session():
            yield object()

        app.dependency_overrides[session_dependency] = session
        for path in paths:
            result = await client.get(path)
            assert result.status_code == 200 and "id" not in result.json()[0]
            if path == f"/products/{uid}/offers":
                composition = result.json()[0]["price_composition"]
                assert composition["price_without_coupon"] == "2999.9000"
                assert (
                    composition["coupon_scenarios"][0]["total_with_shipping"]
                    == "2715.8100"
                )
        assert (
            await client.get("/catalog/products?category=invalid")
        ).status_code == 422
