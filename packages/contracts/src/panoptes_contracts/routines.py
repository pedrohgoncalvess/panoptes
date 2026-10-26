from typing import Literal
from uuid import UUID

from pydantic import Field, HttpUrl, model_validator

from .base import Contract
from .extraction import ExtractionPolicy, Version


class RoutineDefinition(Contract):
    contract_version: Literal["1.0"] = "1.0"
    public_id: UUID
    version: Version
    name: str = Field(min_length=1)
    site: str = Field(min_length=1)
    entity_kind: Literal["product", "service"]
    seed_urls: tuple[HttpUrl, ...] = Field(min_length=1)
    allowed_hosts: tuple[str, ...] = Field(min_length=1)
    parser_slug: Version
    parser_version: Version
    enabled: bool = False
    interval_seconds: int = Field(ge=1)
    concurrency_per_host: int = Field(default=1, ge=1)
    requests_per_second: float = Field(default=1, gt=0)
    policy: ExtractionPolicy = Field(default_factory=ExtractionPolicy)

    @model_validator(mode="after")
    def validate_hosts(self):
        if any(url.host not in self.allowed_hosts for url in self.seed_urls):
            raise ValueError("seed_urls must belong to allowed_hosts")
        return self


class ParserFixture(Contract):
    name: str = Field(min_length=1)
    html_path: str = Field(min_length=1)
    expected_path: str = Field(min_length=1)
    provenance: Literal["synthetic", "sanitized_capture"]


class ParserManifest(Contract):
    contract_version: Literal["1.0"] = "1.0"
    slug: Version
    version: Version
    hosts: tuple[str, ...] = Field(min_length=1)
    entity_kind: Literal["product", "service"]
    fixtures: tuple[ParserFixture, ...] = Field(min_length=1)
    entrypoint: str | None = None
