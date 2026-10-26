"""Canonical identities are conservative; source listings always remain distinct."""

import hashlib
import json
from decimal import Decimal

from sqlalchemy import text

from ..common.matching import normalize


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def identity_keys(detail, site="amazon_br"):
    product = detail.catalog
    fallback = (site, detail.entity.source_key)
    if product.brand and product.model:
        identity = (
            product.category,
            normalize(product.brand),
            normalize(product.model),
        )
    elif product.category == "book" and product.identifiers.get("isbn"):
        identity = ("book", "isbn", product.identifiers["isbn"])
    else:
        identity = (product.category, *fallback)
    # Unknown attributes must not merge variants across different listings.
    variant_identifier = next(
        (
            (key, value)
            for key, value in sorted(product.identifiers.items())
            if key.startswith("gtin") or key == "isbn"
        ),
        None,
    )
    variant_identity = variant_identifier or fallback
    return fingerprint(identity), fingerprint(variant_identity)


def validate_existing(existing, product):
    if existing["category"] != product.category:
        raise ValueError("listing_category_changed")
    for key in ("brand", "model"):
        old, new = existing[key], getattr(product, key)
        if old and new and normalize(old) != normalize(new):
            raise ValueError("listing_identity_changed")
    for key, value in product.attributes.items():
        old = existing["attributes"].get(key)
        if old is None:
            continue
        matches = normalize(str(old)) == normalize(str(value))
        if isinstance(value, (Decimal, int)) and not isinstance(value, bool):
            matches = Decimal(str(old)) == Decimal(str(value))
        # JSONB numeric values are persisted as decimal strings by the contract.
        if not matches:
            raise ValueError("listing_variant_changed")
    for key, value in product.identifiers.items():
        previous = existing.get("identifiers", {}).get(key)
        if previous and normalize(previous) != normalize(value):
            raise ValueError("listing_identifier_changed")


async def save_listing(session, entity_id, detail, site="amazon_br"):
    product = detail.catalog
    existing = (
        (
            await session.execute(
                text("""SELECT l.id,l.variant_id,p.id AS product_id,p.category,p.brand,p.model,v.attributes,v.identifiers
        FROM "catalog"."listing" l JOIN "catalog"."variant" v ON v.id=l.variant_id
        JOIN "catalog"."product" p ON p.id=v.product_id WHERE l.entity_id=:entity FOR UPDATE OF l"""),
                {"entity": entity_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        if product.category == "other" and existing["category"] != "other":
            # A missing category in a later capture must not erase a known identity.
            from panoptes_contracts.catalog import CatalogProduct

            product = CatalogProduct(
                category=existing["category"],
                brand=existing["brand"],
                model=existing["model"],
                attributes=existing["attributes"],
                identifiers=existing.get("identifiers", {}),
            )
        validate_existing(existing, product)
        await session.execute(
            text("""UPDATE "catalog"."product" SET brand=coalesce(brand,:brand),model=coalesce(model,:model)
            WHERE id=:id"""),
            {
                "id": existing["product_id"],
                "brand": product.brand,
                "model": product.model,
            },
        )
        await session.execute(
            text("""UPDATE "catalog"."variant" SET attributes=attributes || CAST(:attrs AS jsonb),
            identifiers=identifiers || CAST(:identifiers AS jsonb)
            WHERE id=:id"""),
            {
                "id": existing["variant_id"],
                "attrs": json.dumps(product.model_dump(mode="json")["attributes"]),
                "identifiers": json.dumps(product.identifiers),
            },
        )
        await session.execute(
            text(
                """UPDATE "catalog"."listing" SET title=:title,url=:url,updated_at=now() WHERE id=:id"""
            ),
            {
                "id": existing["id"],
                "title": detail.entity.title,
                "url": str(detail.entity.url),
            },
        )
        return existing["id"]
    product_key, variant_key = identity_keys(detail, site)
    product_id = (
        await session.execute(
            text("""INSERT INTO "catalog"."product"
        (identity_key,category,title,brand,model,identifiers)
        VALUES (:key,:category,:title,:brand,:model,CAST(:identifiers AS jsonb))
        ON CONFLICT(identity_key) DO UPDATE SET identity_key=EXCLUDED.identity_key RETURNING id"""),
            {
                "key": product_key,
                "category": product.category,
                "title": detail.entity.title,
                "brand": product.brand,
                "model": product.model,
                "identifiers": json.dumps(product.identifiers),
            },
        )
    ).scalar_one()
    variant = (
        (
            await session.execute(
                text("""INSERT INTO "catalog"."variant" (product_id,identity_key,attributes,identifiers)
        VALUES (:product,:key,CAST(:attrs AS jsonb),CAST(:identifiers AS jsonb))
        ON CONFLICT(product_id,identity_key) DO UPDATE SET identity_key=EXCLUDED.identity_key RETURNING id,attributes,identifiers"""),
                {
                    "product": product_id,
                    "key": variant_key,
                    "attrs": json.dumps(product.model_dump(mode="json")["attributes"]),
                    "identifiers": json.dumps(product.identifiers),
                },
            )
        )
        .mappings()
        .one()
    )
    validate_existing(
        {
            "category": product.category,
            "brand": product.brand,
            "model": product.model,
            "attributes": variant["attributes"],
            "identifiers": variant["identifiers"],
        },
        product,
    )
    return (
        await session.execute(
            text("""INSERT INTO "catalog"."listing" (entity_id,variant_id,url,title)
        VALUES (:entity,:variant,:url,:title) ON CONFLICT(entity_id) DO UPDATE
        SET title=EXCLUDED.title,url=EXCLUDED.url,updated_at=now() RETURNING id"""),
            {
                "entity": entity_id,
                "variant": variant["id"],
                "url": str(detail.entity.url),
                "title": detail.entity.title,
            },
        )
    ).scalar_one()
