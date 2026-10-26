"""Normalized category attributes; raw specifications remain in ProductDetail."""

import re
from decimal import Decimal
from typing import Literal

from pydantic import Field, StrictBool, model_validator

from .base import Contract

Category = Literal["book", "television", "refrigerator", "school_supplies", "other"]
Attribute = str | int | Decimal | StrictBool | None


class TelevisionAttributes(Contract):
    screen_size_inches: Decimal | None = Field(default=None, gt=0, le=200)
    resolution: str | None = None
    panel_technology: str | None = None
    product_line: str | None = None
    refresh_rate_hz: Decimal | None = Field(default=None, gt=0)
    smart: StrictBool | None = None
    voltage: str | None = None
    color: str | None = None


class RefrigeratorAttributes(Contract):
    capacity_liters: Decimal | None = Field(default=None, gt=0)
    voltage: str | None = None
    color: str | None = None
    frost_free: StrictBool | None = None
    door_count: int | None = Field(default=None, ge=1)


class BookAttributes(Contract):
    isbn: str | None = None
    edition: str | None = None
    format: str | None = None
    language: str | None = None
    page_count: int | None = Field(default=None, ge=1)


class SchoolSuppliesAttributes(Contract):
    item_type: str | None = None
    units_per_pack: int | None = Field(default=None, ge=1)
    material: str | None = None
    color: str | None = None
    volume_ml: Decimal | None = Field(default=None, gt=0)
    sheet_count: int | None = Field(default=None, ge=1)


CATEGORY_ATTRIBUTES = {
    "television": TelevisionAttributes,
    "refrigerator": RefrigeratorAttributes,
    "book": BookAttributes,
    "school_supplies": SchoolSuppliesAttributes,
}


def validate_attributes(category, attributes):
    if category == "other":
        if attributes:
            raise ValueError("Unclassified products cannot have category attributes")
        return {}
    result = (
        CATEGORY_ATTRIBUTES[category]
        .model_validate(attributes)
        .model_dump(exclude_none=True)
    )
    for key, value in result.items():
        if isinstance(value, Decimal):
            result[key] = Decimal(format(value.normalize(), "f"))
    if result.get("voltage"):
        result["voltage"] = re.sub(r"\s+", "", result["voltage"]).casefold()
    if result.get("resolution"):
        value = result["resolution"]
        match = re.fullmatch(r"\s*(\d+)\s*[x×]\s*(\d+)\s*", value, re.I)
        if match:
            result["resolution"] = f"{match.group(1)}x{match.group(2)}"
    return result


class CatalogProduct(Contract):
    category: Category
    brand: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    identifiers: dict[str, str] = Field(default_factory=dict)
    attributes: dict[str, Attribute] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_category_attributes(self):
        normalized = validate_attributes(self.category, self.attributes)
        object.__setattr__(self, "attributes", normalized)
        return self
