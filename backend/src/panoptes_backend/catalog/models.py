from decimal import Decimal
from uuid import UUID

from panoptes_contracts.base import Contract
from panoptes_contracts.discovery import ProductMatchCriteria
from panoptes_contracts.sources import SourceId
from panoptes_contracts.sources import SourceSelection as SourceSelection
from pydantic import Field, model_validator


class SearchTermCreate(Contract):
    site: SourceId = "amazon_br"
    term: str = Field(min_length=1, max_length=200)
    criteria: ProductMatchCriteria | None = None
    max_pages: int = Field(default=1, ge=1, le=20)
    max_candidates: int = Field(default=100, ge=1, le=1000)
    refresh_interval_seconds: int = Field(default=86400, ge=60)
    description: str = Field(default="", max_length=1000)
    reference_price: Decimal | None = Field(default=None, gt=0, le=999999999)

    @model_validator(mode="before")
    @classmethod
    def mapping_criteria(cls, data):
        if isinstance(data, dict):
            data = dict(data)
            criteria = data.get("criteria")
            query = data.get("term", "")
            query = query.strip() if isinstance(query, str) else query
            description = data.get("description", "")
            description = (
                description.strip() if isinstance(description, str) else description
            )
            if criteria is None:
                data["criteria"] = {
                    "match_mode": "intent",
                    "query": query,
                    "description": description,
                    "reference_price": data.get("reference_price"),
                }
            elif isinstance(criteria, dict) and criteria.get("match_mode") == "intent":
                data["criteria"] = {**criteria, "query": query}
        return data


class TrackingUpdate(Contract):
    enabled: bool
    refresh_interval_seconds: int = Field(ge=60)


class SearchTermsCreate(SearchTermCreate):
    """Create every selected source in one database transaction."""

    sites: tuple[SourceId, ...] = Field(min_length=1, max_length=5)
    discover: bool = False

    @model_validator(mode="after")
    def unique_sites(self):
        if len(set(self.sites)) != len(self.sites):
            raise ValueError("sites must be unique")
        if "site" in self.model_fields_set:
            raise ValueError("Use sites instead of site for batch creation")
        return self


class RequestAccepted(Contract):
    public_id: UUID
    status: str
