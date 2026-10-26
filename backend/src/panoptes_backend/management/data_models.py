from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Amount = Decimal


class DataFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str | None = Field(None, max_length=300)
    site: str | None = Field(None, max_length=100)
    request_id: UUID | None = None
    price_operator: Literal["gt", "eq", "lt", "between"] | None = None
    price: Amount | None = Field(None, ge=0, max_digits=18, decimal_places=4)
    price_to: Amount | None = Field(None, ge=0, max_digits=18, decimal_places=4)
    currency: str = Field("BRL", pattern="^[A-Z]{3}$")

    @model_validator(mode="after")
    def validate_prices(self):
        if self.price_operator and self.price is None:
            raise ValueError("Informe o preço para filtrar.")
        if not self.price_operator and (
            self.price is not None or self.price_to is not None
        ):
            raise ValueError("Escolha a comparação de preço.")
        if self.price_operator == "between":
            if self.price_to is None or self.price_to < self.price:
                raise ValueError("Informe um intervalo de preços válido.")
        elif self.price_to is not None:
            raise ValueError("O preço final só é permitido no filtro entre.")
        return self


class DataQuery(DataFilters):
    limit: int = Field(25, ge=1, le=100)
    offset: int = Field(0, ge=0)


class BulkDataAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["exclude", "purge"]
    ids: list[UUID] = Field(default_factory=list, max_length=10000)
    all_matching: bool = False
    filters: DataFilters | None = None
    excluded_ids: list[UUID] = Field(default_factory=list, max_length=10000)
    expected_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.all_matching:
            if self.ids or self.filters is None:
                raise ValueError(
                    "Informe os filtros para selecionar todos os resultados."
                )
        elif not self.ids or self.filters is not None or self.excluded_ids:
            raise ValueError("Selecione os produtos para esta ação.")
        return self
