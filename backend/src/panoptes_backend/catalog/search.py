"""Public, paginated product search; embeddings are generated inside the API."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from panoptes_contracts.sources import SourceId
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from .router import session_dependency

router = APIRouter(tags=["catalog"])


class ProductQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str | None = Field(None, max_length=300)
    mode: Literal["semantic", "text", "recent"] = "semantic"
    term_id: UUID | None = None
    site: SourceId | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    min_similarity: float = Field(0.25, ge=-1, le=1)
    limit: int = Field(25, ge=1, le=100)
    offset: int = Field(0, ge=0)

    @model_validator(mode="after")
    def validate_search(self):
        self.q = " ".join((self.q or "").split()) or None
        if self.mode != "recent" and not self.q:
            raise ValueError("q é obrigatório para busca semantic ou text")
        if self.mode == "recent" and self.q:
            raise ValueError("Use semantic ou text para pesquisar q")
        if self.start_at and self.end_at and self.start_at >= self.end_at:
            raise ValueError("start_at deve ser anterior a end_at")
        return self


async def search_products(session, search, filters):
    from ..auth.mcp_policy import observation_scope, scoped_clause

    scope, scope_params = scoped_clause(session, observation_scope())
    params = {**filters.model_dump(), **scope_params}
    # Bind an explicit nullable model/vector even for searches that do not use AI.
    params.update(model=None, vector=None)
    similarity = "NULL::double precision"
    if filters.mode == "semantic":
        await search.configure()
        agent, version = search.agent, search.version
        vector = (await search.encode([filters.q], agent=agent, version=version))[0]
        params.update(model=version, vector=str(vector))
        similarity = (
            "1-(s.embedding OPERATOR(extensions.<=>) "
            "CAST(:vector AS extensions.vector))"
        )
    base = f"""
      FROM scraping.entity e
      LEFT JOIN catalog.listing l ON l.entity_id=e.id
      LEFT JOIN scraping.tracking_target t ON t.entity_id=e.id
      LEFT JOIN catalog.product_search s ON s.entity_id=e.id AND s.model=:model
      JOIN LATERAL (
        SELECT o.public_id,o.created_at,o.payload FROM scraping.observation o
        WHERE o.entity_id=e.id {scope}
          AND (CAST(:start_at AS timestamptz) IS NULL OR o.created_at>=:start_at)
          AND (CAST(:end_at AS timestamptz) IS NULL OR o.created_at<:end_at)
        ORDER BY o.created_at DESC,o.id DESC LIMIT 1
      ) latest ON true
      WHERE (CAST(:site AS text) IS NULL OR e.site=:site)
        AND NOT EXISTS (SELECT 1 FROM scraping.excluded_page x
          WHERE x.site=e.site AND x.source_key=e.source_key)
        AND (CAST(:term_id AS uuid) IS NULL OR EXISTS (
          SELECT 1 FROM scraping.search_term_entity link
          JOIN scraping.search_term st ON st.id=link.search_term_id
          WHERE link.entity_id=e.id AND st.public_id=:term_id))
    """
    if filters.mode == "semantic":
        base += f" AND ({similarity})>=:min_similarity"
    elif filters.mode == "text":
        base += """ AND position(lower(:q) in lower(concat_ws(' ',l.title,
          e.source_key,latest.payload->'entity'->>'title',
          latest.payload->'entity'->>'description')))>0"""
    total = (
        await session.execute(text("SELECT count(*) " + base), params)
    ).scalar_one()
    order = "similarity DESC," if filters.mode == "semantic" else ""
    items = (
        (
            await session.execute(
                text(f"""
          SELECT e.public_id,e.site,e.source_key,
            coalesce(l.title,latest.payload->'entity'->>'title',e.source_key) AS title,
            coalesce(l.url,t.product_url) AS url,
            latest.public_id AS observation_id,latest.created_at AS observed_at,
            latest.payload AS data,{similarity} AS similarity
          {base} ORDER BY {order} latest.created_at DESC,e.public_id
          LIMIT :limit OFFSET :offset
        """),
                params,
            )
        )
        .mappings()
        .all()
    )
    return dict(
        items=items,
        total=total,
        limit=filters.limit,
        offset=filters.offset,
        mode=filters.mode,
    )


@router.get("/products/search")
async def products_search(
    request: Request,
    filters: Annotated[ProductQuery, Query()],
    session=Depends(session_dependency),
):
    if filters.term_id:
        from .repository import find_term

        if await find_term(session, filters.term_id) is None:
            raise HTTPException(404, "Search term not found")
    return await search_products(session, request.app.state.product_search, filters)
