"""Run with `uv run --package panoptes-mcp panoptes-mcp` (stdio)."""

import json
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from panoptes_contracts.alerts import Webhook, WebhookConfig, WebhookDelivery
from panoptes_contracts.sources import SourceId, SourceSelection
from pydantic import Field

from . import responses as out
from .client import PanoptesClient
from .instructions import GUIDE, INSTRUCTIONS
from .models import (
    AnalyticsTermId,
    CanonicalId,
    CollectedEndAt,
    CollectedStartAt,
    CreateTerms,
    EndAt,
    EndDate,
    EntityId,
    Limit,
    OfferId,
    Offset,
    QueryText,
    RequestId,
    RoutineCreate,
    RoutineId,
    RoutineUpdate,
    Sites,
    StartAt,
    StartDate,
    TermId,
    TermText,
)

READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
)


def api(ctx: Context) -> PanoptesClient:
    return ctx.request_context.lifespan_context


def period(start_at, end_at):
    if start_at and end_at and start_at >= end_at:
        raise ToolError("start_at deve ser anterior a end_at.")


def price_period(start, end, collected_start_at, collected_end_at):
    period(collected_start_at, collected_end_at)
    if (start is not None or end is not None) and (
        collected_start_at is not None or collected_end_at is not None
    ):
        raise ToolError("Use start/end OU collected_start_at/collected_end_at.")
    if (
        collected_start_at
        and collected_end_at
        and collected_end_at - collected_start_at > timedelta(days=366)
    ):
        raise ToolError("A janela de coleta deve ter no máximo 366 dias.")


def create_server(client_factory=PanoptesClient):
    @asynccontextmanager
    async def lifespan(server):
        client = client_factory()
        try:
            yield client
        finally:
            await client.close()

    mcp = FastMCP("Panoptes", instructions=INSTRUCTIONS, lifespan=lifespan)

    @mcp.tool(annotations=READ)
    async def get_usage_guide(
        tool_name: Annotated[
            str,
            Field(
                description="Nome exato de uma ferramenta de tools/list para acrescentar seus schemas reais; omita para o guia de exploração."
            ),
        ]
        | None = None,
        include_guide: Annotated[
            bool,
            Field(
                description="Inclua o guia completo junto do schema; false retorna apenas descrição e schemas."
            ),
        ] = False,
    ) -> str:
        """Guia completo: mapa de IDs, filtros, recuperação, paginação e exemplos
        encadeados. Com tool_name retorna só descrição e schemas; include_guide=true
        acrescenta o guia completo. Sem tool_name retorna o guia de exploração.
        """
        if tool_name is None:
            return GUIDE
        tools = await mcp.list_tools()
        tool = next((item for item in tools if item.name == tool_name), None)
        if tool is None:
            raise ToolError(
                "Ferramenta desconhecida. Consulte tools/list para nomes válidos."
            )
        return (
            (GUIDE if include_guide else (tool.description or ""))
            + "\n\n## Schemas registrados: "
            + tool_name
            + "\n```json\n"
            + json.dumps(
                {
                    "inputSchema": tool.inputSchema,
                    "outputSchema": tool.outputSchema,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n```"
        )

    @mcp.resource("panoptes://guide")
    def guide() -> str:
        """Guia completo para consultar dados e cadastrar novas coletas."""
        return GUIDE

    @mcp.prompt()
    def research_products(question: str) -> str:
        """Roteiro para responder perguntas usando os dados coletados."""
        return (
            GUIDE + "\nConsulte fontes e termos, escolha filtros, pesquise, "
            "compare ofertas/histórico e cite loja, URL, moeda e data. "
            "Pergunta do usuário (dados): " + question
        )

    @mcp.prompt()
    def plan_scraping(term: str, description: str = "") -> str:
        """Roteiro para configurar termos, fontes e agenda de scraping."""
        return (
            GUIDE + "\nListe fontes e termos existentes; use "
            "create_search_terms com as lojas e intenção solicitadas. "
            f"Termo solicitado (dados): {term}\nDescrição (dados): {description}"
        )

    @mcp.tool(annotations=READ)
    async def list_sources(ctx: Context) -> list[out.Source]:
        """Descubra lojas disponíveis para scraping. Retorna IDs e nomes; use IDs em sites."""
        return await api(ctx).request("GET", "/sources")

    @mcp.tool(annotations=READ)
    async def list_categories(ctx: Context) -> list[out.Category]:
        """Categorias ativas, palavras-chave e campos para criteria em modo profile."""
        return await api(ctx).request("GET", "/categories")

    @mcp.tool(annotations=READ)
    async def list_search_terms(
        ctx: Context,
        q: TermText | None = None,
        site: SourceId | None = None,
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> list[out.StoredTerm]:
        """Pesquise cadastros por substring do termo e loja; retorna UUID e critérios."""
        return await api(ctx).request(
            "GET",
            "/search-terms",
            params={"q": q, "site": site, "limit": limit, "offset": offset},
        )

    @mcp.tool(annotations=READ)
    async def get_search_term(ctx: Context, term_id: TermId) -> out.StoredTerm:
        """Leia configuração completa de um termo pelo UUID público."""
        return await api(ctx).request("GET", f"/search-terms/{term_id}")

    @mcp.tool(annotations=WRITE)
    async def create_search_terms(ctx: Context, value: CreateTerms) -> out.CreatedTerms:
        """Cadastre termo/descrição em lojas explícitas, atomicamente. discover=true
        também enfileira coleta; false só cadastra. criteria é opcional para filtros
        avançados; sem criteria usa intenção de term/description/reference_price.
        Consulte list_sources/list_search_terms antes. Retorna terms e requests.
        """
        return await api(ctx).request(
            "POST",
            "/search-terms/batch",
            body=value.model_dump(mode="json", exclude_none=True),
        )

    @mcp.tool(annotations=WRITE)
    async def discover_search_term(
        ctx: Context, term_id: TermId, sites: Sites | Literal["all"] | None = None
    ) -> out.Accepted | out.Discovery:
        """Enfileire descoberta de novos produtos. Sem sites usa a loja do cadastro;
        lista explícita seleciona lojas; 'all' solicita todas. Não aguarda conclusão.
        """
        if sites is None:
            return await api(ctx).request("POST", f"/search-terms/{term_id}/discover")
        selection = SourceSelection(sites=sites)
        return await api(ctx).request(
            "POST",
            f"/search-terms/{term_id}/discover-sources",
            body=selection.model_dump(mode="json"),
        )

    @mcp.tool(annotations=READ)
    async def list_term_sources(ctx: Context, term_id: TermId) -> list[out.TermSource]:
        """Fontes associadas à primeira coleta desta configuração, para criar rotinas."""
        return await api(ctx).request("GET", f"/search-terms/{term_id}/routine-sources")

    @mcp.tool(annotations=READ)
    async def search_products(
        ctx: Context,
        q: QueryText | None = None,
        mode: Annotated[
            Literal["semantic", "text", "recent"],
            Field(
                description="semantic: cosseno estrito >= min_similarity, q obrigatório; text: substring literal, q obrigatório; recent: omita q, ordena observações recentes."
            ),
        ] = "semantic",
        term_id: TermId | None = None,
        site: SourceId | None = None,
        start_at: StartAt | None = None,
        end_at: EndAt | None = None,
        min_similarity: Annotated[
            float,
            Field(
                ge=-1,
                le=1,
                description="Corte de cosseno somente em semantic. Não é probabilidade; alterar amplia/restringe o escopo e deve ser informado.",
            ),
        ] = 0.25,
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> out.SearchPage:
        """Busque produtos por similaridade (embedding gerado pela aplicação), texto
        literal ou observações recentes. Combine termo exato, loja e período ISO com
        fuso [start_at,end_at). Retorna total, score e última observação NO intervalo.
        Semantic exige índice/IA configurados; text/recent funcionam sem embeddings.
        """
        period(start_at, end_at)
        if mode != "recent" and not (q or "").strip():
            raise ToolError("Informe q para busca semantic ou text.")
        if mode == "recent" and q:
            raise ToolError("Use semantic ou text para pesquisar q.")
        return await api(ctx).request(
            "GET",
            "/products/search",
            params={
                "q": q,
                "mode": mode,
                "term_id": term_id,
                "site": site,
                "start_at": start_at,
                "end_at": end_at,
                "min_similarity": min_similarity,
                "limit": limit,
                "offset": offset,
            },
        )

    @mcp.tool(annotations=READ)
    async def list_term_products(
        ctx: Context, term_id: TermId, limit: Limit = 25, offset: Offset = 0
    ) -> out.TermProducts:
        """Produtos vinculados exatamente a um cadastro, com última observação e tracking."""
        return await api(ctx).request(
            "GET",
            f"/search-terms/{term_id}/products",
            params={"limit": limit, "offset": offset},
        )

    @mcp.tool(annotations=READ)
    async def get_product_history(
        ctx: Context,
        entity_id: EntityId,
        limit: Limit = 25,
        offset: Offset = 0,
        start_at: StartAt | None = None,
        end_at: EndAt | None = None,
    ) -> list[out.Observation]:
        """Observações completas do produto, mais recentes primeiro; filtre período
        ISO com fuso [start_at,end_at) e pagine para obter todo o histórico.
        """
        period(start_at, end_at)
        return await api(ctx).request(
            "GET",
            f"/products/{entity_id}/observations",
            params={
                "limit": limit,
                "offset": offset,
                "start_at": start_at,
                "end_at": end_at,
            },
        )

    @mcp.tool(annotations=READ)
    async def list_product_offers(
        ctx: Context, entity_id: EntityId, limit: Limit = 25, offset: Offset = 0
    ) -> list[out.Offer]:
        """Ofertas por vendedor, preço/moeda, estoque, frete, cupons e parcelamento."""
        return await api(ctx).request(
            "GET",
            f"/products/{entity_id}/offers",
            params={"limit": limit, "offset": offset},
        )

    @mcp.tool(annotations=READ)
    async def get_offer_history(
        ctx: Context, offer_id: OfferId, limit: Limit = 25, offset: Offset = 0
    ) -> list[out.PriceObservation]:
        """Evolução dos preços e condições de uma oferta, mais recentes primeiro."""
        return await api(ctx).request(
            "GET",
            f"/offers/{offer_id}/observations",
            params={"limit": limit, "offset": offset},
        )

    @mcp.tool(annotations=WRITE)
    async def refresh_product(ctx: Context, entity_id: EntityId) -> out.Accepted:
        """Enfileire nova coleta de um produto já acompanhado; acompanhe o request retornado."""
        return await api(ctx).request("POST", f"/products/{entity_id}/refresh")

    @mcp.tool(annotations=WRITE)
    async def configure_tracking(
        ctx: Context,
        entity_id: EntityId,
        enabled: bool,
        refresh_interval_seconds: Annotated[int, Field(ge=60)],
    ) -> out.Tracking:
        """Ative/pause acompanhamento e defina intervalo de atualização em segundos (>=60)."""
        return await api(ctx).request(
            "PATCH",
            f"/products/{entity_id}/tracking",
            body={
                "enabled": enabled,
                "refresh_interval_seconds": refresh_interval_seconds,
            },
        )

    @mcp.tool(annotations=READ)
    async def get_scrape_request(
        ctx: Context, request_id: RequestId
    ) -> out.ScrapeRequest:
        """Status, resumo, termo e datas de uma coleta assíncrona. pending/running é incompleto."""
        return await api(ctx).request("GET", f"/scrape-requests/{request_id}")

    @mcp.tool(annotations=READ)
    async def list_scrape_requests(
        ctx: Context,
        status: Literal[
            "pending", "running", "completed", "partial", "failed", "blocked"
        ]
        | None = None,
        group_key: str | None = None,
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> out.Page[out.ScrapeRequest]:
        """Liste coletas por estado ou grupo, com paginação."""
        return await api(ctx).request(
            "GET",
            "/scrape-requests",
            params={
                "status": status,
                "group_key": group_key,
                "limit": limit,
                "offset": offset,
            },
        )

    @mcp.tool(annotations=READ)
    async def get_request_qualifications(
        ctx: Context, request_id: RequestId
    ) -> list[out.Qualification]:
        """Consulte avaliação dos candidatos para explicar inclusões/exclusões na coleta."""
        return await api(ctx).request(
            "GET", f"/scrape-requests/{request_id}/qualifications"
        )

    @mcp.tool(annotations=READ)
    async def price_dashboard(
        ctx: Context,
        start: StartDate | None = None,
        end: EndDate | None = None,
        term_id: AnalyticsTermId | None = None,
        product_id: EntityId | None = None,
        site: SourceId | None = None,
        q: QueryText | None = None,
        canonical_product_id: CanonicalId | None = None,
        collected_start_at: CollectedStartAt | None = None,
        collected_end_at: CollectedEndAt | None = None,
        currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None,
    ) -> out.PriceDashboard:
        """Agregações de preços por período, termo, produto ou loja. q é semântico.
        Datas locais São Paulo inclusivas; padrão 30 dias, máximo 366 dias.
        term_id agrupa por lower(btrim(term)), incluindo configurações e lojas
        diferentes; combine site/product_id. product_id é UUID de entidade;
        canonical_product_id é UUID canônico. Filtros se intersectam.
        collected_start_at/collected_end_at selecionam horários de coleta [início,fim),
        com fuso, em alternativa a start/end. Janela máxima 366 dias.
        """
        price_period(start, end, collected_start_at, collected_end_at)
        return await api(ctx).request(
            "GET",
            "/analytics/prices/dashboard",
            params={
                "start": start,
                "end": end,
                "term_id": term_id,
                "product_id": product_id,
                "site": site,
                "q": q,
                "canonical_product_id": canonical_product_id,
                "collected_start_at": collected_start_at,
                "collected_end_at": collected_end_at,
                "currency": currency,
            },
        )

    @mcp.tool(annotations=READ)
    async def price_details(
        ctx: Context,
        start: StartDate | None = None,
        end: EndDate | None = None,
        term_id: AnalyticsTermId | None = None,
        product_id: EntityId | None = None,
        site: SourceId | None = None,
        q: QueryText | None = None,
        canonical_product_id: CanonicalId | None = None,
        limit: Limit = 25,
        offset: Offset = 0,
        collected_start_at: CollectedStartAt | None = None,
        collected_end_at: CollectedEndAt | None = None,
        sort_by: Annotated[
            Literal["observed_at", "collected_at", "price"],
            Field(
                description="Ordene por preço numérico, horário da coleta ou observação. price exige currency."
            ),
        ] = "collected_at",
        sort_order: Annotated[
            Literal["asc", "desc"],
            Field(
                description="asc: menores/mais antigos primeiro; desc: maiores/mais recentes primeiro. Preços desconhecidos ficam no fim."
            ),
        ] = "desc",
        currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None,
        latest: Annotated[
            bool,
            Field(
                description="true seleciona a última coleta de cada produto dentro da janela antes de ordenar/paginar; false retorna histórico."
            ),
        ] = False,
    ) -> out.Page[out.PriceDetail]:
        """Dados detalhados de preços, paginados. term_id agrupa pelo texto do termo,
        não configuração exata; site/product_id restringem loja/entidade. start/end
        são datas locais inclusivas; q é semântico. Valores null são desconhecidos.
        collected_start_at/collected_end_at usam horários de coleta com fuso,
        intervalo [início,fim), em alternativa às datas start/end. limit 1..100
        limita a página após ordenação; offset avança. price exige currency.
        """
        price_period(start, end, collected_start_at, collected_end_at)
        if sort_by == "price" and currency is None:
            raise ToolError("Informe currency (ex.: BRL) para ordenar por preço.")
        return await api(ctx).request(
            "GET",
            "/analytics/detail",
            params={
                "start": start,
                "end": end,
                "term_id": term_id,
                "product_id": product_id,
                "site": site,
                "q": q,
                "canonical_product_id": canonical_product_id,
                "limit": limit,
                "offset": offset,
                "collected_start_at": collected_start_at,
                "collected_end_at": collected_end_at,
                "sort_by": sort_by,
                "sort_order": sort_order,
                "currency": currency,
                "latest": latest,
            },
        )

    @mcp.tool(annotations=READ)
    async def get_analytics(
        ctx: Context, days: Annotated[int, Field(ge=1, le=90)] = 7
    ) -> out.Analytics:
        """Resumo operacional de coletas e resultados nos últimos 1..90 dias."""
        return await api(ctx).request("GET", "/analytics", params={"days": days})

    @mcp.tool(annotations=READ)
    async def list_canonical_products(
        ctx: Context, limit: Limit = 25, offset: Offset = 0
    ) -> list[out.CanonicalProduct]:
        """Produtos normalizados para comparar anúncios equivalentes de diferentes lojas."""
        return await api(ctx).request(
            "GET",
            "/catalog/canonical-products",
            params={"limit": limit, "offset": offset},
        )

    @mcp.tool(annotations=READ)
    async def list_canonical_listings(
        ctx: Context, product_id: CanonicalId, limit: Limit = 25, offset: Offset = 0
    ) -> list[out.CanonicalListing]:
        """Anúncios de todas as lojas associados ao mesmo produto canônico."""
        return await api(ctx).request(
            "GET",
            f"/catalog/canonical-products/{product_id}/listings",
            params={"limit": limit, "offset": offset},
        )

    @mcp.tool(annotations=READ)
    async def list_routines(
        ctx: Context, scheduled: bool = False, limit: Limit = 25, offset: Offset = 0
    ) -> list[out.Routine]:
        """Agendas de scraping existentes; scheduled=true consulta a visão de agendadas."""
        return await api(ctx).request(
            "GET",
            "/routines",
            params={"scheduled": scheduled, "limit": limit, "offset": offset},
        )

    @mcp.tool(annotations=READ)
    async def get_routine(ctx: Context, routine_id: RoutineId) -> out.Routine:
        """Leia agenda, fontes, modo e estado de uma rotina pelo UUID."""
        return await api(ctx).request("GET", f"/routines/{routine_id}")

    @mcp.tool(annotations=WRITE)
    async def create_routine(ctx: Context, value: RoutineCreate) -> out.Routine:
        """Agende discover/refresh para termo e lojas. schedule aceita fixed (times HH:MM),
        interval (interval_minutes) ou random_daily (times_per_day), com fuso IANA.
        Consulte list_term_sources antes de escolher sites. Retorna rotina criada.
        """
        return await api(ctx).request(
            "POST", "/routines", body=value.model_dump(mode="json")
        )

    @mcp.tool(annotations=WRITE)
    async def update_routine(
        ctx: Context, routine_id: RoutineId, value: RoutineUpdate
    ) -> out.Routine:
        """Substitua nome/agenda/enabled, não é PATCH. Leia get_routine e preserve
        nome e agenda completos ao pausar com enabled=false. sites omitido/null
        preserva fontes; lista substitui. enabled é obrigatório. Não envie campos
        somente de leitura (public_id, mode, search_term_id, created_at, next_run_at).
        """
        return await api(ctx).request(
            "PUT", f"/routines/{routine_id}", body=value.model_dump(mode="json")
        )

    @mcp.tool(annotations=READ)
    async def list_webhooks(
        ctx: Context, limit: Limit = 25, offset: Offset = 0
    ) -> list[Webhook]:
        """Liste destinos e regras de alerta. Pagine até retornar menos que limit."""
        return await api(ctx).request(
            "GET", "/alerts/webhooks", params={"limit": limit, "offset": offset}
        )

    @mcp.tool(annotations=READ)
    async def get_webhook(ctx: Context, webhook_id: UUID) -> Webhook:
        """Leia configuração completa antes de editar; webhook_id vem de list_webhooks."""
        return await api(ctx).request("GET", f"/alerts/webhooks/{webhook_id}")

    @mcp.tool(annotations=WRITE)
    async def create_webhook(ctx: Context, value: WebhookConfig) -> Webhook:
        """Cadastre endereço e regras por evento/rotina. Consulte list_routines antes.
        routine_ids vazio inclui manuais. Preço nominal exige threshold/direction;
        variação exige percent, comparado à observação anterior da mesma oferta/moeda.
        """
        return await api(ctx).request(
            "POST", "/alerts/webhooks", body=value.model_dump(mode="json")
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    async def update_webhook(
        ctx: Context, webhook_id: UUID, value: WebhookConfig
    ) -> Webhook:
        """Substitua configuração completa: leia get_webhook e preserve campos.
        enabled=false pausa. Editar cancela entregas pendentes; não envia retroativamente.
        """
        return await api(ctx).request(
            "PUT", f"/alerts/webhooks/{webhook_id}", body=value.model_dump(mode="json")
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    async def delete_webhook(ctx: Context, webhook_id: UUID) -> dict[str, bool]:
        """Remova destino e seu histórico de entregas somente quando solicitado."""
        return await api(ctx).request("DELETE", f"/alerts/webhooks/{webhook_id}")

    @mcp.tool(annotations=READ)
    async def list_webhook_deliveries(
        ctx: Context, webhook_id: UUID, limit: Limit = 25, offset: Offset = 0
    ) -> list[WebhookDelivery]:
        """Histórico de envios: pending/delivered/failed/cancelled, tentativas e HTTP.
        Recebedor deve deduplicar por public_id, id estável também nas novas tentativas.
        """
        return await api(ctx).request(
            "GET",
            f"/alerts/webhooks/{webhook_id}/deliveries",
            params={"limit": limit, "offset": offset},
        )

    # FastMCP otherwise silently discards unknown top-level arguments. Keep
    # runtime validation and advertised schemas aligned for every tool.
    for tool in mcp._tool_manager.list_tools():
        model = tool.fn_metadata.arg_model
        model.model_config = {**model.model_config, "extra": "forbid"}
        model.model_rebuild(force=True)
        tool.parameters = model.model_json_schema(by_alias=True)
    return mcp


def main():
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
