"""Shared classification contracts; taxonomy never changes product identity."""

from uuid import UUID

from pydantic import Field, field_validator

from .base import Contract


class TaxonChoice(Contract):
    id: UUID | None
    name: str = Field(min_length=1, max_length=100)
    evidence: str = Field(min_length=1, max_length=800)
    creation_reason: str = Field(max_length=800)
    exceptional: bool


class CategoryChoice(TaxonChoice):
    subcategories: list[TaxonChoice] = Field(max_length=10)


class Classification(Contract):
    categories: list[CategoryChoice] = Field(min_length=1, max_length=8)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=1000)


class TaxonEdit(Contract):
    name: str = Field(min_length=1, max_length=100)
    parent_id: UUID | None = None
    description: str = Field(default="", max_length=1000)
    active: bool = True

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        if not value.strip():
            raise ValueError("Nome vazio")
        return value.strip()


class TaxonomyPolicy(Contract):
    category_target: int = Field(default=20, ge=1, le=1000)
    subcategory_target: int = Field(default=200, ge=1, le=10000)
    allow_creation: bool = True


class TaxonomyAssignment(Contract):
    taxon_ids: list[UUID] = Field(max_length=100)
