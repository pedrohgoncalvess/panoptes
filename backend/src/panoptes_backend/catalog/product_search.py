"""OpenRouter product embeddings, refreshed independently of scraping."""

import asyncio
import hashlib
import logging
import math
import os
import re

from panoptes_database.session import unit_of_work
from sqlalchemy import text

VERSION = "fields-v2"
logger = logging.getLogger(__name__)

# Keep only public product information. Authentication and commercial conditions
# remain in their original stores and never enter the embedding document.
DOCUMENTS = """
 SELECT e.id,e.public_id,e.site,e.source_key,l.title,p.title AS catalog_title,
 p.category,p.brand,latest.payload->'entity'->>'title' AS extracted_title,
 description.value AS description,
 (SELECT string_agg(DISTINCT coalesce(c.name,t.criteria->>'category_name',
     t.criteria->>'category'), ', ')
  FROM scraping.search_term_entity link
  JOIN scraping.search_term t ON t.id=link.search_term_id
  LEFT JOIN catalog.search_category c ON c.slug=t.criteria->>'category'
  WHERE link.entity_id=e.id) AS categories,
 indexed.document_hash,indexed.model
 FROM scraping.entity e
 LEFT JOIN catalog.listing l ON l.entity_id=e.id
 LEFT JOIN catalog.variant v ON v.id=l.variant_id
 LEFT JOIN catalog.product p ON p.id=v.product_id
 LEFT JOIN LATERAL (
   SELECT payload FROM scraping.observation WHERE entity_id=e.id
   ORDER BY created_at DESC,id DESC LIMIT 1
 ) latest ON true
 LEFT JOIN LATERAL (
   SELECT payload->'entity'->>'description' AS value
   FROM scraping.observation WHERE entity_id=e.id
     AND nullif(trim(payload->'entity'->>'description'),'') IS NOT NULL
   ORDER BY created_at DESC,id DESC LIMIT 1
 ) description ON true
 LEFT JOIN catalog.product_search indexed ON indexed.entity_id=e.id
 WHERE e.id>:after ORDER BY e.id LIMIT 100
"""


def document(row):
    names = dict.fromkeys(
        str(row.get(key) or "").strip()
        for key in ("title", "catalog_title", "extracted_title")
    )
    category = {
        "book": "Livros",
        "television": "Televisores Eletrônicos",
        "refrigerator": "Geladeiras Refrigeradores Eletrodomésticos",
        "school_supplies": "Material escolar",
        "other": "Outros",
    }.get(row.get("category"), row.get("category") or "")
    parts = [name for name in names if name]
    parts.extend(str(row.get(key) or "").strip() for key in ("categories", "brand"))
    parts.extend((category, str(row.get("description") or "").strip()))
    return "\n".join(part for part in parts if part) or row["source_key"]


def fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ProductSearch:
    def __init__(self, sessions, ai=None):
        self.sessions = sessions
        self.ai = ai
        self.version = VERSION
        self.agent = None

    async def configure(self):
        if self.ai is not None:
            self.agent = await self.ai.agent("product_embedding")
            settings = self.agent["metadata"].get("settings") or {}
            self.version = (
                f"{self.agent['model']}:{settings.get('dimensions', 'default')}:"
                f"{self.agent['metadata'].get('version', '1')}:{VERSION}"
            )

    async def encode(self, documents, *, agent=None, version=None):
        if self.ai is None:
            raise RuntimeError("OpenRouter gateway is required for product search")
        agent = agent or self.agent
        version = version or self.version
        chunks, lengths = [], []
        for value in documents:
            pieces = [value[i : i + 1800] for i in range(0, len(value), 1800)] or [
                value
            ]
            lengths.append(len(pieces))
            chunks.extend(pieces)
        embeddings = []
        for offset in range(0, len(chunks), 64):
            payload = await self.ai.invoke(
                "product_embedding",
                chunks[offset : offset + 64],
                agent=agent,
                context={
                    "purpose": "product_search",
                    "embedding_version": version,
                },
            )
            embeddings.extend(
                item["embedding"]
                for item in sorted(payload["data"], key=lambda i: i["index"])
            )
        result, offset = [], 0
        for length in lengths:
            vectors = embeddings[offset : offset + length]
            vector = [
                math.fsum(values) / length for values in zip(*vectors, strict=True)
            ]
            norm = math.sqrt(math.fsum(v * v for v in vector))
            if not math.isfinite(norm) or norm == 0:
                raise ValueError("Invalid product embedding")
            result.append([v / norm for v in vector])
            offset += length
        return result

    async def refresh(self):
        await self.configure()
        agent, version = self.agent, self.version
        after, count = 0, 0
        while True:
            async with unit_of_work(self.sessions) as session:
                rows = (
                    (await session.execute(text(DOCUMENTS), {"after": after}))
                    .mappings()
                    .all()
                )
            if not rows:
                return count
            after = rows[-1]["id"]
            changed = []
            for row in rows:
                value = document(row)
                digest = fingerprint(value)
                if row["model"] != version or row["document_hash"] != digest:
                    changed.append((row["id"], value, digest))
            if not changed:
                continue
            vectors = await self.encode(
                [value for _, value, _ in changed], agent=agent, version=version
            )
            async with unit_of_work(self.sessions) as session:
                for (entity_id, value, digest), vector in zip(
                    changed, vectors, strict=True
                ):
                    await session.execute(
                        text("""
                      INSERT INTO catalog.product_search(entity_id,model,document_hash,document,embedding)
                      SELECT id,:model,:hash,:document,CAST(:vector AS extensions.vector)
                      FROM scraping.entity WHERE id=:id
                      ON CONFLICT(entity_id) DO UPDATE SET model=excluded.model,
                        document_hash=excluded.document_hash,document=excluded.document,
                        embedding=excluded.embedding,updated_at=now()
                    """),
                        {
                            "id": entity_id,
                            "model": version,
                            "hash": digest,
                            "document": value,
                            "vector": str(vector),
                        },
                    )
            count += len(changed)

    async def run(self):
        while True:
            try:
                if not os.getenv("OPENROUTER_API_KEY"):
                    await asyncio.sleep(30)
                    continue
                count = await self.refresh()
                if count:
                    logger.info("Busca de produtos: %s embeddings atualizados.", count)
            except Exception:
                logger.exception(
                    "Não foi possível atualizar a busca de produtos; nova tentativa em 30 segundos."
                )
            await asyncio.sleep(30)

    async def search(
        self, session, query, term_id=None, site=None, selected=None, *, limit=100
    ):
        query = re.sub(r"\s+", " ", query).strip()
        await self.configure()
        agent, version = self.agent, self.version
        vector = (await self.encode([query], agent=agent, version=version))[0]
        return (
            (
                await session.execute(
                    text("""
          SELECT e.public_id,coalesce(l.title,e.source_key) AS title,e.site,
            1-(s.embedding OPERATOR(extensions.<=>) CAST(:vector AS extensions.vector)) AS similarity
          FROM scraping.entity e LEFT JOIN catalog.listing l ON l.entity_id=e.id
          LEFT JOIN catalog.product_search s ON s.entity_id=e.id AND s.model=:model
          WHERE (CAST(:site AS text) IS NULL OR e.site=:site)
            AND (CAST(:term_id AS uuid) IS NULL OR EXISTS (
              SELECT 1 FROM scraping.search_term_entity link
              JOIN scraping.search_term t ON t.id=link.search_term_id
              WHERE link.entity_id=e.id AND lower(btrim(t.term))=(SELECT lower(btrim(term)) FROM scraping.search_term WHERE public_id=CAST(:term_id AS uuid))))
            AND (e.public_id=CAST(:selected AS uuid)
              OR position(lower(:query) in lower(coalesce(s.document,l.title,e.source_key)))>0
              OR 1-(s.embedding OPERATOR(extensions.<=>) CAST(:vector AS extensions.vector))>=0.25)
          ORDER BY (e.public_id=CAST(:selected AS uuid)) DESC NULLS LAST,
            (position(lower(:query) in lower(coalesce(s.document,l.title,e.source_key)))>0) DESC,
            similarity DESC NULLS LAST,title,e.public_id LIMIT :limit
        """),
                    {
                        "query": query,
                        "vector": str(vector),
                        "model": version,
                        "site": site,
                        "term_id": term_id,
                        "selected": selected,
                        "limit": limit,
                    },
                )
            )
            .mappings()
            .all()
        )
