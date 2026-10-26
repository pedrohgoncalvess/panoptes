"""Atomic taxonomy operations shared by workers and the management API."""

import json
import re
import unicodedata

from sqlalchemy import text


def normalized_name(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", " ", value).strip()


async def lock(session):
    # All taxonomy mutations share one short lock; no lock is held during inference.
    await session.execute(text("SELECT pg_advisory_xact_lock(74201915)"))


async def nodes(session):
    return (
        (
            await session.execute(
                text("""
      SELECT t.id,t.parent_id,t.name,t.description,t.active,t.origin,p.name AS parent_name,
        (SELECT count(*) FROM catalog.product_taxonomy a WHERE a.taxon_id=t.id) AS products
      FROM catalog.taxon t LEFT JOIN catalog.taxon p ON p.id=t.parent_id
      ORDER BY t.parent_id NULLS FIRST,t.name,t.id
    """)
            )
        )
        .mappings()
        .all()
    )


async def policy(session):
    return dict(
        (
            await session.execute(
                text("""
      SELECT category_target,subcategory_target,allow_creation FROM catalog.taxonomy_policy WHERE id
    """)
            )
        )
        .mappings()
        .one()
    )


async def save_node(session, node_id, value):
    await lock(session)
    all_nodes = {row["id"]: row for row in await nodes(session)}
    if node_id and node_id not in all_nodes:
        raise ValueError("Classificação não encontrada.")
    if value.parent_id:
        parent = all_nodes.get(value.parent_id)
        if not parent or parent["parent_id"] is not None or value.parent_id == node_id:
            raise ValueError(
                "A subcategoria precisa pertencer a uma categoria principal."
            )
        if not parent["active"] and value.active:
            raise ValueError("Ative a categoria principal antes da subcategoria.")
    if node_id and all_nodes[node_id]["parent_id"] != value.parent_id:
        # Moving assigned subcategories needs their implied category memberships updated.
        # Keep hierarchy stable; rename freely or replace assignments with another node.
        raise ValueError(
            "O vínculo principal é estável; crie outra subcategoria e ajuste os produtos."
        )
    key = normalized_name(value.name)
    if not key:
        raise ValueError("Informe um nome com letras ou números.")
    if any(
        row["id"] != node_id
        and row["parent_id"] == value.parent_id
        and normalized_name(row["name"]) == key
        for row in all_nodes.values()
    ):
        raise ValueError("Já existe uma classificação com esse nome nesse nível.")
    if node_id:
        await session.execute(
            text("""
          UPDATE catalog.taxon SET name=:name,normalized_name=:key,description=:description,
            active=:active,updated_at=now() WHERE id=:id
        """),
            {"id": node_id, "key": key, **value.model_dump()},
        )
        return node_id
    return (
        await session.execute(
            text("""
      INSERT INTO catalog.taxon(name,normalized_name,parent_id,description,active)
      VALUES (:name,:key,:parent_id,:description,:active) RETURNING id
    """),
            {"key": key, **value.model_dump()},
        )
    ).scalar_one()


async def assignment(session, public_id):
    row = (
        (
            await session.execute(
                text("""
      SELECT c.public_id,c.name,t.status,t.result,
        coalesce((SELECT jsonb_agg(jsonb_build_object('id',n.id,'name',n.name,
          'parent_id',n.parent_id,'active',n.active) ORDER BY n.name)
          FROM catalog.product_taxonomy a JOIN catalog.taxon n ON n.id=a.taxon_id
          WHERE a.product_id=c.id),'[]'::jsonb) AS taxa
      FROM catalog.canonical_product c LEFT JOIN catalog.taxonomy_task t ON t.product_id=c.id
      WHERE c.public_id=:id
    """),
                {"id": public_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return row


async def manual_assignment(session, public_id, taxon_ids):
    await lock(session)
    product_id = (
        await session.execute(
            text("""
      SELECT id FROM catalog.canonical_product WHERE public_id=:id
    """),
            {"id": public_id},
        )
    ).scalar_one_or_none()
    if product_id is None:
        raise ValueError("Produto não encontrado.")
    all_nodes = {row["id"]: row for row in await nodes(session)}
    selected = set(taxon_ids)
    for node_id in list(selected):
        node = all_nodes.get(node_id)
        if not node or not node["active"]:
            raise ValueError("Selecione apenas categorias e subcategorias ativas.")
        if node["parent_id"]:
            if not all_nodes[node["parent_id"]]["active"]:
                raise ValueError("A categoria principal está inativa.")
            selected.add(node["parent_id"])
    # Lock task BEFORE replacing memberships; worker takes the same lock order.
    await session.execute(
        text("""
      INSERT INTO catalog.taxonomy_task(product_id,evidence,status,result)
      VALUES (:id,'{}','manual','{"source":"manual"}')
      ON CONFLICT(product_id) DO UPDATE SET status='manual',lease_token=NULL,
        result='{"source":"manual"}',updated_at=now()
    """),
        {"id": product_id},
    )
    await replace_memberships(session, product_id, selected)


async def replace_memberships(session, product_id, selected):
    await session.execute(
        text("DELETE FROM catalog.product_taxonomy WHERE product_id=:id"),
        {"id": product_id},
    )
    for node_id in sorted(selected, key=str):
        await session.execute(
            text("""
          INSERT INTO catalog.product_taxonomy(product_id,taxon_id) VALUES (:product,:taxon)
        """),
            {"product": product_id, "taxon": node_id},
        )


def resolve_choices(result, all_nodes, limits):
    """Validate the full proposal before writing anything; include implied parents."""
    from uuid import uuid4

    existing = {str(row["id"]): row for row in all_nodes}
    by_name = {
        (
            str(row["parent_id"]) if row["parent_id"] else None,
            normalized_name(row["name"]),
        ): row
        for row in all_nodes
    }
    counts = {
        False: sum(n["parent_id"] is None for n in all_nodes),
        True: sum(n["parent_id"] is not None for n in all_nodes),
    }
    selected, proposed = set(), []

    def resolve(choice, parent):
        row = (
            existing.get(str(choice.id))
            if choice.id
            else by_name.get(
                (str(parent) if parent else None, normalized_name(choice.name))
            )
        )
        if choice.id and row is None:
            raise ValueError("O agente indicou uma classificação inexistente.")
        if row:
            if not row["active"] or row["parent_id"] != parent:
                raise ValueError(
                    "Classificação inativa ou categoria principal incorreta."
                )
            return row["id"]
        if not limits["allow_creation"]:
            raise ValueError("Criação automática desativada; revise a sugestão.")
        if not normalized_name(choice.name) or not choice.creation_reason.strip():
            raise ValueError("Nova classificação exige nome e justificativa.")
        child = parent is not None
        target = limits["subcategory_target" if child else "category_target"]
        if counts[child] >= target and (
            not choice.exceptional
            or result.confidence < 0.97
            or len(choice.creation_reason.strip()) < 40
        ):
            raise ValueError(
                "Meta atingida; reutilize existentes ou justifique uma exceção com alta confiança."
            )
        row = {
            "id": uuid4(),
            "parent_id": parent,
            "name": choice.name.strip(),
            "active": True,
            "description": choice.creation_reason,
        }
        proposed.append(row)
        existing[str(row["id"])] = row
        by_name[(str(parent) if parent else None, normalized_name(choice.name))] = row
        counts[child] += 1
        return row["id"]

    for choice in result.categories:
        category = resolve(choice, None)
        selected.add(category)
        for child in choice.subcategories:
            selected.add(resolve(child, category))
    return selected, proposed


async def apply_classification(session, product_id, result, all_nodes, limits):
    selected, proposed = resolve_choices(result, all_nodes, limits)
    for node in proposed:
        await session.execute(
            text("""
          INSERT INTO catalog.taxon(id,parent_id,name,normalized_name,description,origin)
          VALUES (:id,:parent_id,:name,:key,:description,'agent')
        """),
            {**node, "key": normalized_name(node["name"])},
        )
    await replace_memberships(session, product_id, selected)


async def enqueue(session, product_id, source):
    await session.execute(
        text("""
      INSERT INTO catalog.taxonomy_task(product_id,evidence)
      SELECT id,jsonb_build_object('name',name,'identity',identity,'source',CAST(:source AS jsonb))
      FROM catalog.canonical_product WHERE id=:id ON CONFLICT(product_id) DO NOTHING
    """),
        {"id": product_id, "source": json.dumps(source, ensure_ascii=False)},
    )
