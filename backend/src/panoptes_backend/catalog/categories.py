import json

from fastapi import APIRouter, Depends, HTTPException
from panoptes_contracts.discovery import CategoryDefinition
from sqlalchemy import text

from ..auth.router import current_user
from .router import session_dependency

router = APIRouter(tags=["categories"])


async def administrator(user=Depends(current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Apenas administradores podem gerenciar categorias.")
    return user


@router.get("/categories")
async def list_categories(session=Depends(session_dependency)):
    return (
        (
            await session.execute(
                text(
                    "SELECT slug,name,keywords,suggested_fields,active FROM catalog.search_category WHERE active ORDER BY name"
                )
            )
        )
        .mappings()
        .all()
    )


@router.get("/admin/categories", dependencies=[Depends(administrator)])
async def all_categories(session=Depends(session_dependency)):
    return (
        (
            await session.execute(
                text(
                    "SELECT slug,name,keywords,suggested_fields,active FROM catalog.search_category ORDER BY name"
                )
            )
        )
        .mappings()
        .all()
    )


@router.put("/admin/categories/{slug}", dependencies=[Depends(administrator)])
async def save_category(
    slug: str, value: CategoryDefinition, session=Depends(session_dependency)
):
    if slug != value.slug or not value.name.strip():
        raise HTTPException(422, "Confira o identificador e o nome da categoria.")
    await session.execute(
        text("""INSERT INTO catalog.search_category(slug,name,keywords,suggested_fields,active)
    VALUES (:slug,:name,CAST(:keywords AS jsonb),CAST(:fields AS jsonb),:active)
    ON CONFLICT(slug) DO UPDATE SET name=EXCLUDED.name,keywords=EXCLUDED.keywords,
      suggested_fields=EXCLUDED.suggested_fields,active=EXCLUDED.active,updated_at=now()"""),
        {
            "slug": slug,
            "name": value.name.strip(),
            "keywords": json.dumps(value.keywords),
            "fields": json.dumps(value.suggested_fields),
            "active": value.active,
        },
    )
    return value


@router.get("/scrape-requests/{request_id}/qualifications")
async def qualifications(request_id: str, session=Depends(session_dependency)):
    from uuid import UUID

    try:
        public_id = UUID(request_id)
    except ValueError:
        raise HTTPException(422, "Identificador inválido.") from None
    return (
        (
            await session.execute(
                text("""SELECT c.source_key,
      coalesce(c.detail_validation,c.validation) AS assessment
      FROM scraping.search_candidate c JOIN scraping.scrape_request r ON r.id=c.scrape_request_id
      WHERE r.public_id=:id ORDER BY c.id LIMIT 1000"""),
                {"id": public_id},
            )
        )
        .mappings()
        .all()
    )
