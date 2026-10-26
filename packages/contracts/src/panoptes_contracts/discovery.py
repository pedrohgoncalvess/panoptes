"""Search terms group distinct products; observations belong to products."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, HttpUrl, model_validator

from .base import Contract
from .catalog import Attribute, validate_attributes
from .sources import SOURCES, SourceId, validate_source_key


class AttributeRequirement(Contract):
    name: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=300)
    unit: str = Field(default="", max_length=30)
    operator: Literal["eq", "gte", "lte", "contains"] = "eq"


class CategoryDefinition(Contract):
    slug: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    name: str = Field(min_length=1, max_length=100)
    keywords: tuple[str, ...] = Field(default=(), max_length=100)
    suggested_fields: tuple[str, ...] = Field(default=(), max_length=30)
    active: bool = True


class ProductMatchCriteria(Contract):
    match_mode: Literal["exact_product", "category", "profile", "intent"] = "exact_product"
    query: str | None = Field(default=None, min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    title: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, min_length=1, max_length=60)
    category_name: str | None = None
    category_keywords: tuple[str, ...] = ()
    reference_price: Decimal | None = Field(default=None, gt=0, le=999999999)
    currency: Literal["BRL"] = "BRL"
    characteristics: tuple[AttributeRequirement, ...] = Field(default=(), max_length=30)
    notes: str = Field(default="", max_length=2000)
    required_attributes: dict[str, Attribute] = Field(default_factory=dict)
    brands: tuple[str, ...] = ()
    exclude_accessories: bool = True
    authors: tuple[str, ...] = ()
    isbn: tuple[str, ...] = ()
    excluded_title_terms: tuple[str, ...] = (
        "summary",
        "workbook",
        "study guide",
        "resumo",
        "analysis",
        "review",
    )

    @model_validator(mode="after")
    def validate_match_mode(self):
        if self.match_mode == "intent":
            if not self.query or not self.query.strip():
                raise ValueError("intent requires query")
            return self
        if self.match_mode == "profile":
            if not self.category:
                raise ValueError("profile requires category")
            if self.required_attributes:
                raise ValueError("Use characteristics for profile matching")
            if any(
                not item.name.strip() or not item.value.strip()
                for item in self.characteristics
            ):
                raise ValueError("Characteristics cannot be blank")
            return self
        if self.category not in (
            None,
            "book",
            "television",
            "refrigerator",
            "school_supplies",
            "other",
        ):
            raise ValueError("Legacy matching requires a supported parser category")
        if self.match_mode == "exact_product":
            if not self.title or not self.title.strip():
                raise ValueError("exact_product requires title")
            if self.required_attributes or self.brands:
                raise ValueError("Category filters require category mode")
        else:
            if self.category is None:
                raise ValueError("category mode requires category")
            if self.authors or self.isbn:
                raise ValueError("Use exact_product for author/ISBN matching")
            if any(value is None for value in self.required_attributes.values()):
                raise ValueError("Required attributes cannot be null")
            attrs = validate_attributes(self.category, self.required_attributes)
            object.__setattr__(self, "required_attributes", attrs)
        return self


class SearchTerm(Contract):
    public_id: UUID
    site: SourceId = "amazon_br"
    term: str = Field(min_length=1)
    criteria: ProductMatchCriteria
    max_pages: int = Field(default=1, ge=1, le=20)
    max_candidates: int = Field(default=100, ge=1, le=1000)
    refresh_interval_seconds: int = Field(default=86400, ge=60)


class SearchCandidate(Contract):
    site: SourceId = "amazon_br"
    source_key: str = Field(min_length=1)
    url: HttpUrl
    title: str = Field(min_length=1)
    authors: tuple[str, ...] = ()
    search_snapshot_id: UUID
    page_qt: int = Field(ge=1)
    position_qt: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_source(self):
        validate_source_key(self.site, self.source_key)
        if (
            self.url.scheme != "https"
            or self.url.host not in SOURCES[self.site].page_hosts
        ):
            raise ValueError("invalid_product_host")
        return self


class TrackedCandidate(Contract):
    site: SourceId = "amazon_br"
    source_key: str = Field(min_length=1)
    url: HttpUrl
    title: str = Field(min_length=1)
    authors: tuple[str, ...] = ()
    snapshot_id: UUID | None = None

    @model_validator(mode="after")
    def validate_source(self):
        validate_source_key(self.site, self.source_key)
        if (
            self.url.scheme != "https"
            or self.url.host not in SOURCES[self.site].page_hosts
        ):
            raise ValueError("invalid_product_host")
        return self


class QualificationCheck(Contract):
    name: str
    expected: str
    actual: str | None = None
    status: Literal["matched", "mismatch", "missing", "info"]
    evidence: str | None = None


class CandidateValidation(Contract):
    candidate: SearchCandidate | TrackedCandidate
    decision: Literal["accepted", "rejected", "uncertain"]
    reason: str = Field(min_length=1)
    validator_version: str = "amazon_book_match/1.0.0"
    confidence: Decimal = Field(ge=0, le=1)
    checks: tuple[QualificationCheck, ...] = ()


class ProductTrackingTarget(Contract):
    public_id: UUID
    entity_id: UUID
    site: SourceId = "amazon_br"
    source_key: str = Field(min_length=1)
    product_url: HttpUrl
    refresh_interval_seconds: int = Field(ge=60)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_source(self):
        validate_source_key(self.site, self.source_key)
        if (
            self.product_url.scheme != "https"
            or self.product_url.host not in SOURCES[self.site].page_hosts
        ):
            raise ValueError("invalid_product_host")
        return self


class ScrapeRequest(Contract):
    contract_version: Literal["1.1", "1.2"] = "1.2"
    public_id: UUID
    correlation_id: UUID
    mode: Literal["discover", "refresh"]
    search_term_id: UUID | None = None
    tracking_target_id: UUID | None = None

    @model_validator(mode="after")
    def validate_mode(self):
        if self.mode == "discover" and (
            self.search_term_id is None or self.tracking_target_id is not None
        ):
            raise ValueError("discovery requires search_term_id only")
        if self.mode == "refresh" and (
            self.tracking_target_id is None or self.search_term_id is not None
        ):
            raise ValueError("refresh requires tracking_target_id only")
        return self
