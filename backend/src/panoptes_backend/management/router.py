from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AwareDatetime

from ..catalog import products_repository
from ..catalog import repository as catalog_repository
from ..catalog.router import session_dependency
from ..core.errors import NotFoundError
from . import data_repository, price_analytics, repository
from .data_models import BulkDataAction, DataQuery
from .models import AnalyticsResponse, ExtractionPage, RequestStatus

router = APIRouter(tags=["management"])


@router.get("/data")
async def data_rows(
    filters: Annotated[DataQuery, Query()],
    session=Depends(session_dependency),
):
    return await data_repository.rows(
        session,
        filters.q or None,
        filters.site or None,
        filters.request_id,
        filters.limit,
        filters.offset,
        filters=filters,
    )


@router.post("/data/bulk")
async def bulk_data(value: BulkDataAction, session=Depends(session_dependency)):
    return await data_repository.bulk_remove(session, value)


@router.delete("/data/{entity_id}")
async def remove_data(
    entity_id: UUID,
    purge: bool = False,
    session=Depends(session_dependency),
):
    return await data_repository.remove(session, entity_id, purge)


def price_filters(
    start: date | None = None,
    end: date | None = None,
    term_id: UUID | None = None,
    product_id: UUID | None = None,
    site: str | None = Query(None, max_length=100),
    q: Annotated[str | None, Query(max_length=300)] = None,
    canonical_product_id: UUID | None = None,
    collected_start_at: AwareDatetime | None = None,
    collected_end_at: AwareDatetime | None = None,
    currency: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$")] = None,
):
    zone = ZoneInfo(price_analytics.ZONE)
    collection_window = collected_start_at is not None or collected_end_at is not None
    if collection_window and (start is not None or end is not None):
        raise HTTPException(
            422,
            "Use datas start/end OU timestamps collected_start_at/collected_end_at.",
        )
    if collection_window:
        try:
            until = collected_end_at or collected_start_at + timedelta(days=30)
            since = collected_start_at or until - timedelta(days=30)
        except OverflowError:
            raise HTTPException(
                422, "Janela de coleta fora do intervalo de datas suportado."
            ) from None
        if since >= until or until - since > timedelta(days=366):
            raise HTTPException(
                422, "Informe uma janela de coleta válida de até 366 dias."
            )
        return {
            "start_at": since,
            "end_at": until,
            "time_basis": "collected_at",
            "term_id": term_id,
            "product_id": product_id,
            "site": site or None,
            "q": (q or "").strip(),
            "product_ids": None,
            "canonical_product_id": canonical_product_id,
            "currency": currency,
        }
    end = end or datetime.now(zone).date()
    start = start or end - timedelta(days=29)
    if start > end or (end - start).days > 365:
        raise HTTPException(422, "Informe um período válido de até 366 dias.")
    return {
        "start_at": datetime.combine(start, time.min, zone),
        "end_at": datetime.combine(end + timedelta(days=1), time.min, zone),
        "term_id": term_id,
        "product_id": product_id,
        "site": site or None,
        "q": (q or "").strip(),
        "product_ids": None,
        "canonical_product_id": canonical_product_id,
        "currency": currency,
    }


@router.get("/analytics/prices/dashboard")
async def price_dashboard(
    request: Request,
    filters=Depends(price_filters),
    session=Depends(session_dependency),
):
    await resolve_price_search(request, session, filters)
    return await price_analytics.dashboard(session, filters)


async def resolve_price_search(request, session, filters):
    if filters.get("canonical_product_id"):
        filters["product_ids"] = list(
            await products_repository.canonical_entity_ids(
                session, filters["canonical_product_id"]
            )
        )
    if filters["q"]:
        matches = await request.app.state.product_search.search(
            session, filters["q"], filters["term_id"], filters["site"], limit=None
        )
        ids = [row["public_id"] for row in matches]
        if filters["product_ids"] is not None:
            allowed = set(filters["product_ids"])
            ids = [item for item in ids if item in allowed]
        filters["product_ids"] = ids


@router.get("/analytics/prices/products")
async def price_products(
    request: Request,
    term_id: UUID | None = None,
    site: str | None = Query(None, max_length=100),
    q: str | None = Query(None, max_length=300),
    selected: UUID | None = None,
    session=Depends(session_dependency),
):
    if q and q.strip():
        return await request.app.state.product_search.search(
            session, q, term_id, site or None, selected
        )
    return await price_analytics.options(session, term_id, site or None)


@router.get("/analytics/detail")
async def price_detail(
    request: Request,
    filters=Depends(price_filters),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    latest: bool = False,
    sort_by: Literal["observed_at", "collected_at", "price"] = "observed_at",
    sort_order: Literal["asc", "desc"] = "desc",
    session=Depends(session_dependency),
):
    if sort_by == "price" and not filters.get("currency"):
        raise HTTPException(
            422, "Informe currency para ordenar por preço sem misturar moedas."
        )
    await resolve_price_search(request, session, filters)
    options = {}
    if latest:
        options["latest"] = True
    if sort_by != "observed_at" or sort_order != "desc":
        options.update(sort_by=sort_by, sort_order=sort_order)
    return await price_analytics.detail(session, filters, limit, offset, **options)


@router.get("/analytics/prices")
async def prices(
    term_id: UUID,
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session=Depends(session_dependency),
):
    term = await catalog_repository.find_term(session, term_id)
    if term is None:
        raise NotFoundError("Search term not found")
    return await repository.prices(session, term["id"], limit, offset)


@router.get("/analytics", response_model=AnalyticsResponse)
async def analytics(
    days: int = Query(7, ge=1, le=90), session=Depends(session_dependency)
):
    return await repository.analytics(session, days)


@router.get("/scrape-requests", response_model=ExtractionPage)
async def extractions(
    group_key: str | None = Query(None, max_length=500),
    status: RequestStatus | None = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session=Depends(session_dependency),
):
    return await repository.extractions(session, status, limit, offset, group_key)


@router.get("/extraction-groups")
async def extraction_groups(
    status: RequestStatus | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session=Depends(session_dependency),
):
    return await repository.extraction_groups(session, status, limit, offset)
