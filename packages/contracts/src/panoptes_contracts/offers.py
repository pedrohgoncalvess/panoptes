from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from .base import Contract
from .catalog import CatalogProduct
from .extraction import ExtractedEntity

RetailMoney = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4)]


class PaymentOption(Contract):
    method: Literal["pix", "cash", "card", "installment"]
    text: str = Field(min_length=1)
    total_price: RetailMoney | None = None
    installment_count: int | None = Field(default=None, ge=1)
    installment_price: RetailMoney | None = None
    interest_free: bool | None = None
    conditions: tuple[str, ...] = ()
    total_is_derived: bool = False
    extraction_method: Literal["deterministic", "openrouter"] = "deterministic"


class ShippingQuote(Contract):
    text: str = Field(min_length=1)
    price: RetailMoney | None = None
    is_free: bool | None = None
    destination_postal_code: str | None = None
    conditions: tuple[str, ...] = ()
    delivery_text: str | None = None
    extraction_method: Literal["deterministic", "openrouter"] = "deterministic"


class Promotion(Contract):
    kind: Literal["coupon", "discount", "promotion", "installment", "shipping"]
    text: str = Field(min_length=1)
    code: str | None = None
    expires_at: AwareDatetime | None = None
    requires_activation: bool | None = None
    discount_amount: RetailMoney | None = None
    discount_percent: Decimal | None = Field(
        default=None, ge=0, le=100, decimal_places=4
    )
    minimum_spend: RetailMoney | None = None
    conditions: tuple[str, ...] = ()
    maximum_discount: RetailMoney | None = None
    extraction_method: Literal["deterministic", "openrouter"] = "deterministic"


class CommercialEvidence(Contract):
    field: str
    locator: str
    excerpt: str = Field(min_length=1, max_length=2000)
    method: Literal["deterministic", "openrouter"] = "deterministic"


class CommercialExtraction(Contract):
    version: str = "1.0.1"
    evidence: tuple[CommercialEvidence, ...] = ()
    unresolved: tuple[str, ...] = ()
    fallback_status: Literal["not_needed", "disabled", "completed", "failed"] = (
        "not_needed"
    )
    model: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class ProductOffer(Contract):
    price: RetailMoney | None = None
    list_price: RetailMoney | None = None
    price_without_coupon: RetailMoney | None = None
    price_includes_coupon: bool | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    availability: Literal["in_stock", "out_of_stock", "unknown"] = "unknown"
    availability_text: str | None = None
    stock_qt: int | None = Field(default=None, ge=0)
    seller: str | None = None
    ships_from: str | None = None
    condition: str | None = None
    promotions: tuple[Promotion, ...] = ()
    image_urls: tuple[HttpUrl, ...] = ()
    payment_options: tuple[PaymentOption, ...] = ()
    shipping: ShippingQuote | None = None
    shipping_options: tuple[ShippingQuote, ...] = ()
    stock_lower_bound_qt: int | None = Field(default=None, ge=0)
    units_per_pack: int | None = Field(default=None, ge=1)
    minimum_purchase_qt: int | None = Field(default=None, ge=1)
    maximum_purchase_qt: int | None = Field(default=None, ge=1)
    commercial_extraction: CommercialExtraction | None = None

    @model_validator(mode="after")
    def validate_prices(self):
        monetary = [self.price, self.list_price, self.price_without_coupon]
        monetary.extend(p.total_price for p in self.payment_options)
        monetary.extend(p.installment_price for p in self.payment_options)
        monetary.extend(p.discount_amount for p in self.promotions)
        monetary.extend(p.minimum_spend for p in self.promotions)
        monetary.extend(p.maximum_discount for p in self.promotions)
        monetary.extend(s.price for s in self.shipping_options)
        if self.shipping:
            monetary.append(self.shipping.price)
        if any(value is not None for value in monetary) and self.currency is None:
            raise ValueError("a priced offer needs currency")
        return self


class ProductDetail(Contract):
    entity: ExtractedEntity
    offer: ProductOffer
    authors: tuple[str, ...] = ()
    isbn: tuple[str, ...] = ()
    specifications: dict[str, str] = Field(default_factory=dict)
    rating_text: str | None = None
    review_count_text: str | None = None
    catalog: CatalogProduct | None = None
