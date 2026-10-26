"""Shared webhook configuration and public responses for REST and MCP."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, HttpUrl, field_validator, model_validator

from .base import Contract

Event = Literal[
    "extraction_started",
    "extraction_finished",
    "extraction_error",
    "price_threshold",
    "price_drop",
    "price_increase",
]


class AlertRule(Contract):
    event: Event = Field(description="Evento que dispara esta regra.")
    routine_ids: list[UUID] = Field(
        default_factory=list,
        max_length=100,
        description="UUIDs de list_routines. Vazio inclui todas as extrações, inclusive manuais.",
    )
    entity_id: UUID | None = Field(
        default=None,
        description="Opcional para preços: public_id de search_products; não é produto canônico.",
    )
    currency: str = Field(default="BRL", pattern=r"^[A-Z]{3}$")
    threshold: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=4
    )
    direction: Literal["below", "above"] = "below"
    percent: Decimal | None = Field(
        default=None, gt=0, le=100000, max_digits=12, decimal_places=4
    )

    @model_validator(mode="after")
    def valid_rule(self):
        if len(self.routine_ids) != len(set(self.routine_ids)):
            raise ValueError("Rotinas duplicadas")
        if (self.threshold is not None) != (self.event == "price_threshold"):
            raise ValueError("threshold é obrigatório somente para price_threshold")
        if (self.percent is not None) != (
            self.event in {"price_drop", "price_increase"}
        ):
            raise ValueError("percent é obrigatório somente para queda/aumento")
        if self.event.startswith("extraction_") and self.entity_id:
            raise ValueError("entity_id só pode filtrar eventos de preço")
        if self.event != "price_threshold" and self.direction != "below":
            raise ValueError("direction só se aplica ao limite nominal")
        return self


class WebhookConfig(Contract):
    name: str = Field(min_length=1, max_length=200)
    url: HttpUrl = Field(
        description="Destino HTTP(S) que receberá POST JSON. Sem credenciais ou fragmento."
    )
    enabled: bool = True
    rules: list[AlertRule] = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("Informe um nome")
        return value.strip()

    @field_validator("url")
    @classmethod
    def clean_url(cls, value):
        if value.username or value.password or value.fragment:
            raise ValueError("URL não pode conter credenciais ou fragmento")
        return value


class Webhook(WebhookConfig):
    public_id: UUID
    created_at: AwareDatetime
    updated_at: AwareDatetime


class WebhookDelivery(Contract):
    public_id: UUID
    event: Event
    status: Literal["pending", "delivered", "failed", "cancelled"]
    attempts: int
    http_status: int | None
    last_error: str | None
    created_at: AwareDatetime
    delivered_at: AwareDatetime | None
    next_attempt_at: AwareDatetime
