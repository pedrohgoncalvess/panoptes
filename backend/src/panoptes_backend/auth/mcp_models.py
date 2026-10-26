from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from panoptes_contracts.base import Contract
from panoptes_contracts.sources import SourceId
from pydantic import AwareDatetime, Field, field_validator, model_validator


class MCPPermissions(Contract):
    create_routines: bool = False
    manage_routines: bool = False
    create_extractions: bool = False
    view_extractions: bool = False
    create_alerts: bool = False
    max_routines: int | None = Field(default=0, ge=0, le=100000)
    sites: list[SourceId] = Field(default_factory=list, max_length=5)


class MCPKeyCreate(Contract):
    name: str = Field(min_length=1, max_length=100)
    admin: bool = False
    permissions: MCPPermissions = Field(default_factory=MCPPermissions)
    routine_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    expiration: Literal["1w", "2w", "1m", "6m", "1y", "never", "custom"] = "1m"
    expires_at: AwareDatetime | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("Informe um nome para a chave")
        return value.strip()

    @model_validator(mode="after")
    def validate_expiration(self):
        if self.expiration == "custom":
            if self.expires_at is None or self.expires_at <= datetime.now(UTC):
                raise ValueError("Escolha uma data futura")
        elif self.expires_at is not None:
            raise ValueError("Use expiration=custom para uma data personalizada")
        return self
