"""MCP output contracts; additive backend fields are preserved for compatibility.

Flexible JSON is confined to extracted data/assessments and evolving analytics
series. IDs, page envelopes, timestamps and entity relationships are typed.
"""

from datetime import date
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from panoptes_contracts.pricing import PriceComposition
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .models import (
    CanonicalId,
    EntityId,
    OfferId,
    RequestId,
    RoutineId,
    Schedule,
    TermId,
)

Status = Literal["pending", "running", "completed", "partial", "failed", "blocked"]
T = TypeVar("T")


class Response(BaseModel):
    model_config = ConfigDict(extra="allow")


class Page(Response, Generic[T]):
    items: list[T]
    total: int = Field(
        ge=0,
        description="Quantidade de registros de todas as páginas com os filtros aplicados.",
    )
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class Source(Response):
    id: str = Field(description="ID estável a enviar em site/sites; não é UUID.")
    name: str


class Category(Response):
    slug: str = Field(description="Use em criteria.category no modo profile.")
    name: str
    keywords: list[str]
    suggested_fields: list[str]
    active: bool


class TermSource(Response):
    public_id: TermId
    site: str


class SearchTerm(TermSource):
    term: str
    criteria: dict[str, Any] = Field(
        description="Critérios persistidos, incluindo intenção/descrição/preço de referência. Não são dados coletados."
    )
    refresh_interval_seconds: int


class StoredTerm(SearchTerm):
    max_pages_qt: int
    max_candidates_qt: int
    created_at: AwareDatetime


class CreatedTerm(SearchTerm):
    max_pages: int
    max_candidates: int


class Accepted(Response):
    public_id: RequestId
    status: Status


class SourceRequest(Accepted):
    site: str
    search_term_id: TermId


class Discovery(Response):
    requests: list[SourceRequest]


class CreatedTerms(Discovery):
    terms: list[CreatedTerm]


class Product(Response):
    public_id: EntityId
    site: str
    source_key: str


class SearchHit(Product):
    title: str
    url: str | None = Field(
        description="URL da loja; pode estar ausente. Nunca invente um link."
    )
    observation_id: UUID
    observed_at: AwareDatetime
    data: dict[str, Any] = Field(
        description="Payload extraído não confiável. Campos podem faltar; null/ausente não significa zero ou indisponível."
    )
    similarity: float | None = Field(
        description="Cosseno no modo semantic; null em text/recent. Não é probabilidade."
    )


class SearchPage(Page[SearchHit]):
    mode: Literal["semantic", "text", "recent"]


class TermProduct(Product):
    tracking_target_id: UUID | None
    product_url: str | None
    enabled: bool | None
    observation_id: UUID | None
    observed_at: AwareDatetime | None
    payload: dict[str, Any] | None


class TermProducts(Response):
    search_term_id: TermId
    term: str
    products: list[TermProduct]


class Observation(Response):
    public_id: UUID = Field(
        description="UUID da observação, não da entidade; não use como entity_id."
    )
    created_at: AwareDatetime
    payload: dict[str, Any]


class PriceObservation(Response):
    price_composition: PriceComposition | None = None
    public_id: UUID | None = Field(
        description="UUID da observação de preço; null em capturas sem oferta extraída no relatório detalhado."
    )
    observed_at: AwareDatetime
    price: str | None = Field(
        description="Decimal serializado como texto; null significa preço desconhecido. Moeda vem em currency."
    )
    list_price: str | None
    currency: str | None
    availability: str | None
    promotions: list[dict[str, Any]]
    payment_options: list[dict[str, Any]]
    shipping: dict[str, Any] | None


class Offer(Response):
    price_composition: PriceComposition | None = None
    public_id: OfferId
    listing_entity_id: EntityId
    listing_id: UUID = Field(
        description="UUID de catalog.listing; não pode substituir entity_id."
    )
    observation_id: UUID
    observed_at: AwareDatetime
    price: str | None
    currency: str | None
    seller: str | None
    is_current: bool = Field(
        description="Se corresponde à captura mais recente do anúncio; false pode ser oferta antiga de outro vendedor."
    )
    promotions: list[dict[str, Any]]
    payment_options: list[dict[str, Any]]
    shipping: dict[str, Any] | None


class Tracking(Response):
    public_id: UUID = Field(
        description="UUID do tracking_target; para atualizar use o entity_id original, não este UUID."
    )
    enabled: bool
    refresh_interval_seconds: int


class ScrapeRequest(Accepted):
    mode: Literal["discover", "refresh"]
    site: str | None
    search_term_id: TermId | None
    entity_id: EntityId | None
    term: str | None
    summary: dict[str, Any]
    created_at: AwareDatetime
    completed_at: AwareDatetime | None


class Qualification(Response):
    source_key: str
    assessment: dict[str, Any] | None = Field(
        description="Avaliação extraída; pode ainda não existir enquanto a coleta executa."
    )


class PriceDetail(PriceObservation):
    collected_at: AwareDatetime | None = Field(
        default=None,
        description="Horário de persistência da coleta; distinto de observed_at.",
    )
    product_id: EntityId
    title: str
    site: str
    url: str | None
    offer_public_id: OfferId | None
    capture_id: UUID
    request_id: RequestId | None


class PriceTotals(Response):
    products: int
    observations: int
    offers: int


class ExecutionTotals(Response):
    total: int
    completed: int
    failed: int
    partial: int
    in_progress: int


class PriceDashboard(Response):
    coupon_terms: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Cupons anunciados com desconto, mínimo, teto, ativação, validade e quantidade de ofertas; não aplicados aos preços médios.",
    )
    commerce: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Cupons e frete por loja/moeda, última observação de cada oferta no período. Ausência é desconhecido.",
    )
    totals: PriceTotals
    execution_totals: ExecutionTotals
    currencies: list[dict[str, Any]] = Field(
        description="Métricas separadas por moeda; não somar BRL com outras moedas."
    )
    daily: list[dict[str, Any]]
    executions: list[dict[str, Any]]
    sites: list[dict[str, Any]]
    payments: list[dict[str, Any]]
    opportunities: list[dict[str, Any]] = Field(
        description="Até 8 quedas comparadas à observação anterior DENTRO do período."
    )


class Activity(Response):
    date: date
    total: int
    completed: int
    failed: int


class Analytics(Response):
    period_days: int
    totals: dict[str, int]
    daily: list[Activity]


class CanonicalProduct(Response):
    public_id: CanonicalId
    name: str
    identity: dict[str, Any]
    listing_count: int
    sites: list[str]


class CanonicalListing(Response):
    public_id: UUID = Field(description="UUID do anúncio de catálogo, não da entidade.")
    title: str
    url: str
    listing_entity_id: EntityId
    site: str
    source_key: str
    canonical_product_id: CanonicalId
    canonical_name: str
    normalization: dict[str, Any]


class Routine(Response):
    public_id: RoutineId
    name: str
    search_term_id: TermId
    term: str
    site: str
    mode: Literal["discover", "refresh"]
    schedule: Schedule
    enabled: bool
    next_run_at: AwareDatetime
    created_at: AwareDatetime
    sites: list[str]
