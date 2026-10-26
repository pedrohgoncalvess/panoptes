import unicodedata

from panoptes_contracts.discovery import ProductMatchCriteria
from panoptes_contracts.pricing import with_composition
from panoptes_contracts.sources import SOURCES

from ..core.errors import ConflictError, NotFoundError
from . import repository


async def create_term(session, value, *, frozen=False):
    if value.criteria.match_mode == "profile" and not frozen:
        from sqlalchemy import text

        category = (
            (
                await session.execute(
                    text(
                        "SELECT name,keywords FROM catalog.search_category WHERE slug=:slug AND active"
                    ),
                    {"slug": value.criteria.category},
                )
            )
            .mappings()
            .one_or_none()
        )
        if category is None:
            raise ConflictError("Escolha uma categoria ativa.")
        # Freeze the taxonomy used for this search; subsequent admin edits must not rewrite it.
        value = value.model_copy(
            update={
                "criteria": value.criteria.model_copy(
                    update={
                        "category_name": category["name"],
                        "category_keywords": tuple(category["keywords"]),
                    }
                )
            }
        )
    normalized = " ".join(unicodedata.normalize("NFKC", value.term).casefold().split())
    if not normalized:
        raise ConflictError("Search term cannot be blank")
    row = await repository.insert_term(session, value, normalized)
    if (
        ProductMatchCriteria.model_validate(row["criteria"]) != value.criteria
        or row["max_pages_qt"] != value.max_pages
        or row["refresh_interval_seconds"] != value.refresh_interval_seconds
        or row.get("max_candidates_qt", 100) != value.max_candidates
    ):
        raise ConflictError("Term already exists with a different configuration")
    from ..auth.mcp_policy import grant_term

    await grant_term(session, row["public_id"])
    return {
        "public_id": row["public_id"],
        "site": row["site"],
        "term": row["term"],
        "criteria": row["criteria"],
        "max_pages": row["max_pages_qt"],
        "max_candidates": row.get("max_candidates_qt", 100),
        "refresh_interval_seconds": row["refresh_interval_seconds"],
    }


async def discover(session, public_id, correlation_id=None):
    row = await repository.find_term(session, public_id)
    if row is None:
        raise NotFoundError("Search term not found")
    return await repository.enqueue(session, "discover", row["id"], correlation_id)


async def create_terms(session, value, correlation_id):
    from .models import SearchTermCreate

    terms, requests = [], []
    for site in value.sites:
        config = value.model_dump(exclude={"sites", "discover", "site"})
        term = await create_term(session, SearchTermCreate(**config, site=site))
        terms.append(term)
        if value.discover:
            accepted = await discover(session, term["public_id"], correlation_id)
            requests.append(
                {**dict(accepted), "site": site, "search_term_id": term["public_id"]}
            )
    return {"terms": terms, "requests": requests}


async def discover_sources(session, public_id, selection, correlation_id=None):
    from .models import SearchTermCreate

    original = await repository.find_term(session, public_id)
    if original is None:
        raise NotFoundError("Search term not found")
    sites = tuple(SOURCES) if selection.sites == "all" else selection.sites
    requests = []
    for site in sites:
        value = SearchTermCreate(
            site=site,
            term=original["term"],
            criteria=original["criteria"],
            max_pages=original["max_pages_qt"],
            max_candidates=original.get("max_candidates_qt", 100),
            refresh_interval_seconds=original["refresh_interval_seconds"],
        )
        # Reuse per-source configurations and active requests without rewriting history.
        term = await create_term(session, value, frozen=True)
        accepted = await discover(session, term["public_id"], correlation_id)
        requests.append(
            {**dict(accepted), "site": site, "search_term_id": term["public_id"]}
        )
    return {"requests": requests}


async def refresh(session, entity_id, correlation_id=None):
    target = await repository.find_target(session, entity_id)
    if target is None:
        raise NotFoundError("Product tracking target not found")
    return await repository.enqueue(session, "refresh", target["id"], correlation_id)


async def products(session, public_id, limit, offset):
    term = await repository.find_term(session, public_id)
    if term is None:
        raise NotFoundError("Search term not found")
    return {
        "search_term_id": public_id,
        "term": term["term"],
        "products": await repository.list_products(session, term["id"], limit, offset),
    }


async def configure_tracking(session, entity_id, value):
    target = await repository.find_target(session, entity_id)
    if target is None:
        raise NotFoundError("Product tracking target not found")
    await repository.update_target(session, target["id"], value)
    return {"public_id": target["public_id"], **value.model_dump()}


async def offers(session, entity_id, limit, offset):
    from . import pricing_repository

    if await repository.find_target(session, entity_id) is None:
        raise NotFoundError("Product tracking target not found")
    return [
        with_composition(row)
        for row in await pricing_repository.list_offers(
            session, entity_id, limit, offset
        )
    ]


async def offer_history(session, offer_id, limit, offset):
    from . import pricing_repository

    if not await pricing_repository.offer_exists(session, offer_id):
        raise NotFoundError("Offer not found")
    return [
        with_composition(row)
        for row in await pricing_repository.history(session, offer_id, limit, offset)
    ]


async def product_listings(session, product_id, limit, offset):
    from . import products_repository

    if not await products_repository.exists(session, product_id):
        raise NotFoundError("Catalog product not found")
    return await products_repository.listings(session, product_id, limit, offset)
