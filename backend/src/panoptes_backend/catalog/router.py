from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from panoptes_contracts.catalog import Category
from panoptes_contracts.sources import SOURCES
from panoptes_database.session import unit_of_work
from pydantic import AwareDatetime

from ..core.errors import NotFoundError
from . import products_repository, repository, services
from .models import (
    RequestAccepted,
    SearchTermCreate,
    SearchTermsCreate,
    SourceSelection,
    TrackingUpdate,
)

router = APIRouter(tags=["catalog"])


async def session_dependency(request: Request):
    async with unit_of_work(request.app.state.sessions) as session:
        key = getattr(request.state, "principal", {}).get("mcp_key")
        if key:
            session.info["mcp_issuer"] = key
        if key and not key["admin"]:
            session.info["mcp_key"] = key
        yield session


@router.get("/catalog/canonical-products")
async def canonical_products(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session=Depends(session_dependency),
):
    return await products_repository.canonical_products(session, limit, offset)


@router.get("/catalog/canonical-products/{product_id}/listings")
async def canonical_listings(
    product_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session=Depends(session_dependency),
):
    return await products_repository.canonical_listings(
        session, product_id, limit, offset
    )


@router.get("/sources")
async def list_sources():
    return [{"id": source.id, "name": source.name} for source in SOURCES.values()]


@router.post("/search-terms", status_code=201)
async def create_term(value: SearchTermCreate, session=Depends(session_dependency)):
    return await services.create_term(session, value)


@router.post("/search-terms/batch", status_code=201)
async def create_terms(
    value: SearchTermsCreate, request: Request, session=Depends(session_dependency)
):
    return await services.create_terms(session, value, request.state.correlation_id)


@router.get("/search-terms")
async def list_terms(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=200),
    site: str | None = Query(None, max_length=100),
    session=Depends(session_dependency),
):
    return await repository.list_terms(session, limit, offset, q=q, site=site)


@router.get("/search-terms/{term_id}")
async def read_term(term_id: UUID, session=Depends(session_dependency)):
    term = await repository.find_term(session, term_id)
    if term is None:
        raise NotFoundError("Search term not found")
    return {key: value for key, value in term.items() if key != "id"}


@router.post(
    "/search-terms/{term_id}/discover", response_model=RequestAccepted, status_code=202
)
async def discover(
    term_id: UUID, request: Request, session=Depends(session_dependency)
):
    return await services.discover(session, term_id, request.state.correlation_id)


@router.get("/search-terms/{term_id}/routine-sources")
async def routine_sources(term_id: UUID, session=Depends(session_dependency)):
    from ..auth.mcp_policy import key_for

    if await repository.find_term(session, term_id) is None:
        raise NotFoundError("Search term not found")
    rows = await repository.routine_sources(session, term_id)
    if key_for(session):
        rows = [
            row
            for row in rows
            if row["site"] in key_for(session)["permissions"].get("sites", [])
        ]
    return [{"public_id": row["public_id"], "site": row["site"]} for row in rows]


@router.post("/search-terms/{term_id}/discover-sources", status_code=202)
async def discover_sources(
    term_id: UUID,
    value: SourceSelection,
    request: Request,
    session=Depends(session_dependency),
):
    return await services.discover_sources(
        session, term_id, value, request.state.correlation_id
    )


@router.get("/search-terms/{term_id}/products")
async def products(
    term_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session=Depends(session_dependency),
):
    return await services.products(session, term_id, limit, offset)


@router.post(
    "/products/{entity_id}/refresh", response_model=RequestAccepted, status_code=202
)
async def refresh(
    entity_id: UUID, request: Request, session=Depends(session_dependency)
):
    return await services.refresh(session, entity_id, request.state.correlation_id)


@router.patch("/products/{entity_id}/tracking")
async def configure_tracking(
    entity_id: UUID, value: TrackingUpdate, session=Depends(session_dependency)
):
    return await services.configure_tracking(session, entity_id, value)


@router.get("/products/{entity_id}/observations")
async def history(
    entity_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    start_at: AwareDatetime | None = None,
    end_at: AwareDatetime | None = None,
    session=Depends(session_dependency),
):
    if start_at and end_at and start_at >= end_at:
        raise HTTPException(422, "start_at deve ser anterior a end_at")
    return await repository.read_history(
        session, entity_id, limit, offset, start_at=start_at, end_at=end_at
    )


@router.get("/scrape-requests/{request_id}")
async def read_request(request_id: UUID, session=Depends(session_dependency)):
    row = await repository.read_request(session, request_id)
    if row is None:
        raise NotFoundError("Scrape request not found")
    return row


@router.get("/assets/{asset_id}/url")
async def asset_url(asset_id: UUID, session=Depends(session_dependency)):
    from panoptes_storage.client import create_storage, load_storage_settings

    asset = await repository.read_asset(session, asset_id)
    if asset is None:
        raise NotFoundError("Asset not found")
    params = {"Bucket": asset["bucket"], "Key": asset["object_key"]}
    if asset.get("kind") == "html":
        params["ResponseContentDisposition"] = (
            f'attachment; filename="panoptes-{asset_id}.html"'
        )
    async with create_storage(load_storage_settings(), public=True) as storage:
        url = await storage.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=300,
        )
    return {"url": url, "expires_in_seconds": 300}


@router.get("/catalog/products")
async def catalog_products(
    category: Category | None = None,
    brand: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session=Depends(session_dependency),
):
    return await products_repository.list_products(
        session, category, brand, limit, offset
    )


@router.get("/catalog/products/{product_id}/listings")
async def catalog_listings(
    product_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session=Depends(session_dependency),
):
    return await services.product_listings(session, product_id, limit, offset)


@router.get("/products/{entity_id}/offers")
async def product_offers(
    entity_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session=Depends(session_dependency),
):
    return await services.offers(session, entity_id, limit, offset)


@router.get("/offers/{offer_id}/observations")
async def offer_history(
    offer_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session=Depends(session_dependency),
):
    return await services.offer_history(session, offer_id, limit, offset)
