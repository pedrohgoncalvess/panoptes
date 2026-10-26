from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from panoptes_contracts.base import Contract
from panoptes_contracts.discovery import AttributeRequirement, ProductMatchCriteria
from panoptes_contracts.schedules import RoutineSchedule
from panoptes_contracts.sources import SourceId
from pydantic import AwareDatetime, Field, model_validator

Limit = Annotated[
    int,
    Field(
        ge=1,
        le=100,
        description="Tamanho da página, de 1 a 100; não limita o acervo total.",
    ),
]
Offset = Annotated[
    int,
    Field(
        ge=0,
        description="Quantidade de registros a pular. Próxima página: offset + limit.",
    ),
]
QueryText = Annotated[
    str,
    Field(
        min_length=1,
        max_length=300,
        description="Texto da consulta; não envie embedding. Em relatórios é semântico.",
    ),
]
TermText = Annotated[
    str,
    Field(min_length=1, max_length=200, description="Texto do termo/nome; não é UUID."),
]
Sites = Annotated[
    list[SourceId],
    Field(
        min_length=1,
        max_length=5,
        description="IDs únicos de lojas retornados por list_sources; não nomes nem URLs.",
    ),
]
TermId = Annotated[
    UUID,
    Field(
        description="public_id de list_search_terms ou terms de create_search_terms. Identifica uma configuração e loja exatas."
    ),
]
AnalyticsTermId = Annotated[
    UUID,
    Field(
        description="UUID de termo usado para resolver seu texto. Relatórios agrupam termos por lower(btrim(term)), inclusive outras configurações/lojas; combine site para limitar loja."
    ),
]
EntityId = Annotated[
    UUID,
    Field(
        description="UUID da entidade/anúncio: search_products.items[].public_id ou listing_entity_id de um anúncio canônico; não use UUID canônico, listing_id ou observation_id."
    ),
]
OfferId = Annotated[
    UUID,
    Field(
        description="list_product_offers[].public_id; identifica oferta por vendedor, não produto nem observação."
    ),
]
CanonicalId = Annotated[
    UUID,
    Field(
        description="list_canonical_products[].public_id; agrupa anúncios equivalentes entre lojas. Não é entity_id."
    ),
]
RequestId = Annotated[
    UUID,
    Field(
        description="requests[].public_id da descoberta/cadastro, ou public_id retornado por refresh_product."
    ),
]
RoutineId = Annotated[
    UUID,
    Field(
        description="public_id retornado por list_routines/get_routine/create_routine."
    ),
]
StartAt = Annotated[
    AwareDatetime,
    Field(
        description="Timestamp ISO 8601 COM fuso. Início inclusivo do período de observações."
    ),
]
EndAt = Annotated[
    AwareDatetime,
    Field(
        description="Timestamp ISO 8601 COM fuso. Fim exclusivo; deve ser posterior ao início."
    ),
]
StartDate = Annotated[
    date,
    Field(
        description="Data YYYY-MM-DD inclusiva em America/Sao_Paulo; padrão 29 dias antes de end; período máximo 366 dias."
    ),
]
CollectedStartAt = Annotated[
    AwareDatetime,
    Field(
        description="Horário de persistência da coleta ISO 8601 COM fuso, inclusivo. Não combine com start/end. Janela máxima 366 dias; omitido usa 30 dias antes de collected_end_at."
    ),
]
CollectedEndAt = Annotated[
    AwareDatetime,
    Field(
        description="Horário de persistência da coleta ISO 8601 COM fuso, exclusivo. Não combine com start/end. Omitido usa 30 dias após collected_start_at."
    ),
]
EndDate = Annotated[
    date,
    Field(
        description="Data YYYY-MM-DD inclusiva em America/Sao_Paulo; padrão hoje. Diferente de end_at exclusivo."
    ),
]


class MatchCriteria(ProductMatchCriteria):
    """Critérios avançados; omita para usar intenção de term/description.

    exact_product exige title; intent exige query (API substitui pelo term);
    profile exige category ativo de list_categories e usa characteristics;
    category é legado e usa required_attributes e categorias fixas do contrato.
    Se informado, este objeto controla description/reference_price: inclua-os aqui.
    """

    match_mode: Literal["exact_product", "category", "profile", "intent"] = Field(
        "exact_product",
        description="intent requer query; exact_product requer title; profile requer category ativo e usa characteristics; category usa required_attributes legados.",
    )
    query: str | None = Field(
        None,
        min_length=1,
        max_length=200,
        description="Obrigatório em intent; a API o substitui pelo term externo.",
    )
    title: str | None = Field(
        None,
        min_length=1,
        description="Título obrigatório em exact_product. Não é filtro sobre dados coletados.",
    )
    category: str | None = Field(
        None,
        min_length=1,
        max_length=60,
        description="profile: slug ativo de list_categories. category/exact_product: apenas categorias legadas do contrato.",
    )
    description: str = Field(
        "",
        max_length=1000,
        description="Intenção e inclusões/exclusões do critério explícito; description externo não é mesclado aqui.",
    )
    reference_price: Decimal | None = Field(
        None,
        gt=0,
        le=999999999,
        description="Referência de qualificação em BRL; não filtra preços retornados pela busca.",
    )
    characteristics: tuple[AttributeRequirement, ...] = Field(
        default=(),
        max_length=30,
        description="Perfil: lista name/value/unit/operator (eq,gte,lte,contains). Não combine profile com required_attributes.",
    )


class Schedule(RoutineSchedule):
    """Escolha apenas os campos do tipo de agenda; fuso IANA validado."""

    kind: Literal["fixed", "random_daily", "interval"] = Field(
        description="fixed: times; random_daily: times_per_day; interval: interval_minutes. Não misture os campos."
    )
    timezone: str = Field(
        "America/Sao_Paulo",
        description="Fuso IANA dos horários, por exemplo America/Sao_Paulo.",
    )
    times: list[str] = Field(
        default_factory=list,
        max_length=1440,
        description="Apenas fixed: horários HH:MM distintos, exemplo ['09:00','18:00'].",
    )
    times_per_day: int | None = Field(
        None,
        ge=1,
        le=1440,
        description="Obrigatório apenas em random_daily: execuções distribuídas no dia.",
    )
    interval_minutes: int | None = Field(
        None,
        ge=1,
        le=525600,
        description="Obrigatório apenas em interval: intervalo em minutos (não segundos).",
    )


class CreateTerms(Contract):
    term: TermText
    sites: Sites
    description: str = Field(
        default="",
        max_length=1000,
        description="Intenção, inclusões e exclusões. Usado quando criteria é omitido; com criteria explícito, informe criteria.description.",
    )
    reference_price: Decimal | None = Field(
        None,
        gt=0,
        le=999999999,
        description="Referência em BRL para qualificação, não filtro nem preço coletado. Com criteria explícito, informe criteria.reference_price.",
    )
    max_pages: int = Field(
        1,
        ge=1,
        le=20,
        description="Máximo de páginas de busca por fonte em cada descoberta.",
    )
    max_candidates: int = Field(
        100,
        ge=1,
        le=1000,
        description="Limite de candidatos por fonte, não garantia de produtos aceitos.",
    )
    refresh_interval_seconds: int = Field(
        86400,
        ge=60,
        description="Intervalo de acompanhamento em segundos; 86400 = 1 dia. Não é agenda de descoberta.",
    )
    discover: bool = Field(
        False,
        description="true cadastra e enfileira coleta na mesma transação; false somente cadastra. Não implica conclusão da coleta.",
    )
    criteria: MatchCriteria | None = Field(
        None,
        description="Critérios avançados opcionais. Omita no fluxo por intenção. Não misture description/reference_price externos com critérios explícitos.",
    )

    @model_validator(mode="after")
    def validate_term(self):
        if not self.term.strip():
            raise ValueError("term cannot be blank")
        if len(set(self.sites)) != len(self.sites):
            raise ValueError("sites must be unique")
        return self


class RoutineCreate(Contract):
    name: TermText
    search_term_id: TermId
    mode: Literal["discover", "refresh"] = Field(
        "refresh",
        description="discover encontra produtos novos; refresh atualiza produtos já vinculados.",
    )
    schedule: Schedule = Field(
        description="Agenda completa: fixed, interval ou random_daily."
    )
    enabled: bool = Field(True, description="false cria a rotina pausada.")
    sites: Sites | None = Field(
        None,
        description="Selecione fontes de list_term_sources; omitido usa a loja do termo. Exige primeira descoberta enfileirada.",
    )


class RoutineUpdate(Contract):
    """Substitui nome/agenda/enabled. Leia get_routine antes; não é PATCH."""

    name: TermText
    schedule: Schedule = Field(
        description="Envie a agenda completa preservando os campos desejados."
    )
    enabled: bool = Field(
        description="Obrigatório: preserve o valor lido; false pausa e true ativa.",
    )
    sites: Sites | None = Field(
        None,
        description="Omitido/null preserva fontes atuais; lista substitui pelas fontes selecionadas de list_term_sources.",
    )
