from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from panoptes_contracts.taxonomy import TaxonEdit, TaxonomyAssignment, TaxonomyPolicy
from panoptes_database import taxonomy as repository
from sqlalchemy import text

from ..core.errors import NotFoundError
from .categories import administrator
from .router import session_dependency

router = APIRouter(tags=["taxonomy"])


@router.get("/catalog/taxonomy")
async def taxonomy(session=Depends(session_dependency)):
    return {
        "nodes": await repository.nodes(session),
        "policy": await repository.policy(session),
    }


@router.put("/admin/taxonomy/policy", dependencies=[Depends(administrator)])
async def save_policy(value: TaxonomyPolicy, session=Depends(session_dependency)):
    await repository.lock(session)
    await session.execute(
        text("""
      UPDATE catalog.taxonomy_policy SET category_target=:category_target,
        subcategory_target=:subcategory_target,allow_creation=:allow_creation WHERE id
    """),
        value.model_dump(),
    )
    return value


@router.post("/admin/taxonomy", status_code=201, dependencies=[Depends(administrator)])
async def create_node(value: TaxonEdit, session=Depends(session_dependency)):
    try:
        node_id = await repository.save_node(session, None, value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"id": node_id}


@router.put("/admin/taxonomy/{node_id}", dependencies=[Depends(administrator)])
async def update_node(
    node_id: UUID, value: TaxonEdit, session=Depends(session_dependency)
):
    try:
        await repository.save_node(session, node_id, value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"id": node_id}


@router.get("/catalog/canonical-products/{product_id}/taxonomy")
async def product_taxonomy(product_id: UUID, session=Depends(session_dependency)):
    row = await repository.assignment(session, product_id)
    if row is None:
        raise NotFoundError("Produto não encontrado.")
    return row


@router.get("/admin/taxonomy/products", dependencies=[Depends(administrator)])
async def taxonomy_products(
    q: str = Query("", max_length=200),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session=Depends(session_dependency),
):
    return (
        (
            await session.execute(
                text("""
      SELECT c.public_id,c.name,t.status,t.result,
        coalesce((SELECT jsonb_agg(a.taxon_id ORDER BY a.taxon_id)
          FROM catalog.product_taxonomy a WHERE a.product_id=c.id),'[]'::jsonb) AS taxon_ids
      FROM catalog.canonical_product c LEFT JOIN catalog.taxonomy_task t ON t.product_id=c.id
      WHERE c.name ILIKE '%' || :q || '%' ORDER BY c.id DESC LIMIT :limit OFFSET :offset
    """),
                {"q": q.strip(), "limit": limit, "offset": offset},
            )
        )
        .mappings()
        .all()
    )


@router.put(
    "/admin/taxonomy/products/{product_id}", dependencies=[Depends(administrator)]
)
async def assign_product(
    product_id: UUID, value: TaxonomyAssignment, session=Depends(session_dependency)
):
    try:
        await repository.manual_assignment(session, product_id, value.taxon_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return await repository.assignment(session, product_id)


@router.post(
    "/admin/taxonomy/products/{product_id}/reclassify",
    dependencies=[Depends(administrator)],
)
async def reclassify(product_id: UUID, session=Depends(session_dependency)):
    await repository.lock(session)
    row = (
        await session.execute(
            text("""
      INSERT INTO catalog.taxonomy_task(product_id,evidence)
      SELECT c.id,jsonb_build_object('name',c.name,'identity',c.identity,
        'source',coalesce((SELECT n.input FROM catalog.product_normalization n
          WHERE n.canonical_product_id=c.id AND n.status='completed' ORDER BY n.listing_id LIMIT 1),'{}'::jsonb))
      FROM catalog.canonical_product c WHERE c.public_id=:id
      ON CONFLICT(product_id) DO UPDATE SET evidence=excluded.evidence,status='pending',
        attempts=0,available_at=now(),lease_token=NULL,result=NULL,updated_at=now()
      RETURNING product_id
    """),
            {"id": product_id},
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Produto não encontrado.")
    return {"status": "pending"}
