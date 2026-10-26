import json

from panoptes_database.alerts import price_event
from sqlalchemy import text

from ..common.matching import normalize
from .catalog_repository import fingerprint


def conflict_update(columns, enabled):
    return (
        "DO UPDATE SET " + ",".join(f"{column}=EXCLUDED.{column}" for column in columns)
        if enabled
        else "DO NOTHING"
    )


async def save_offer(
    session, listing_id, offer, source_observation_id, job_id, *, enrich_existing=False
):
    key = fingerprint(
        tuple(
            normalize(v) if v else None
            for v in (offer.seller, offer.ships_from, offer.condition)
        )
    )
    offer_id = (
        await session.execute(
            text("""INSERT INTO "pricing"."offer"
        (listing_id,identity_key,seller,ships_from,condition) VALUES (:listing,:key,:seller,:ships,:condition)
        ON CONFLICT(listing_id,identity_key) DO UPDATE SET identity_key=EXCLUDED.identity_key RETURNING id"""),
            {
                "listing": listing_id,
                "key": key,
                "seller": offer.seller,
                "ships": offer.ships_from,
                "condition": offer.condition,
            },
        )
    ).scalar_one()
    observation_id = (
        await session.execute(
            text(f"""INSERT INTO "pricing"."observation"
        (offer_id,source_observation_id,observed_at,price_vl,list_price_vl,currency,availability,availability_text,stock_qt,
         stock_lower_bound_qt,units_per_pack,minimum_purchase_qt,maximum_purchase_qt,commercial_extraction,shipping_options)
        SELECT :offer,:source,h.captured_at,:price,:list_price,:currency,:availability,:text,:stock,
         :stock_lower,:units,:minimum_qt,:maximum_qt,CAST(:extraction AS jsonb),CAST(:shipping_options AS jsonb)
        FROM "scraping"."job" j JOIN "scraping"."html_snapshot" h ON h.id=j.html_snapshot_id WHERE j.id=:job
        ON CONFLICT(offer_id,source_observation_id) {
                conflict_update(
                    (
                        "offer_id",
                        "stock_qt",
                        "stock_lower_bound_qt",
                        "units_per_pack",
                        "minimum_purchase_qt",
                        "maximum_purchase_qt",
                        "commercial_extraction",
                        "shipping_options",
                    ),
                    True,
                )
                if enrich_existing
                else "DO UPDATE SET offer_id=EXCLUDED.offer_id"
            } RETURNING id"""),
            {
                "offer": offer_id,
                "source": source_observation_id,
                "job": job_id,
                "price": offer.price,
                "list_price": offer.list_price,
                "currency": offer.currency,
                "availability": offer.availability,
                "text": offer.availability_text,
                "stock": offer.stock_qt,
                "stock_lower": offer.stock_lower_bound_qt,
                "units": offer.units_per_pack,
                "minimum_qt": offer.minimum_purchase_qt,
                "maximum_qt": offer.maximum_purchase_qt,
                "extraction": offer.commercial_extraction.model_dump_json()
                if offer.commercial_extraction
                else None,
                "shipping_options": json.dumps(
                    [s.model_dump(mode="json") for s in offer.shipping_options]
                ),
            },
        )
    ).scalar_one()
    if not enrich_existing:
        await price_event(session, observation_id)
    await save_promotions(
        session, observation_id, offer.promotions, enrich_existing=enrich_existing
    )
    await save_payments(
        session, observation_id, offer.payment_options, enrich_existing=enrich_existing
    )
    if enrich_existing:
        for table, count in (
            ("payment_option", len(offer.payment_options)),
            ("promotion", len(offer.promotions)),
        ):
            await session.execute(
                text(
                    f"DELETE FROM pricing.{table} WHERE observation_id=:id AND position_qt>:count"
                ),
                {"id": observation_id, "count": count},
            )
    if offer.shipping:
        shipping = offer.shipping
        await session.execute(
            text(f"""INSERT INTO "pricing"."shipping_quote"
            (observation_id,text,price_vl,is_free,destination_postal_code,conditions,delivery_text,extraction_method)
            VALUES (:id,:text,:price,:free,:postal,CAST(:conditions AS jsonb),:delivery,:method)
            ON CONFLICT(observation_id) {conflict_update(("text", "price_vl", "is_free", "destination_postal_code", "conditions", "delivery_text", "extraction_method"), enrich_existing)}"""),
            {
                "id": observation_id,
                "text": shipping.text,
                "price": shipping.price,
                "free": shipping.is_free,
                "postal": shipping.destination_postal_code,
                "conditions": json.dumps(shipping.conditions),
                "delivery": shipping.delivery_text,
                "method": shipping.extraction_method,
            },
        )


async def save_promotions(
    session, observation_id, promotions, *, enrich_existing=False
):
    for position, promo in enumerate(promotions, 1):
        await session.execute(
            text(f"""INSERT INTO "pricing"."promotion"
            (observation_id,position_qt,kind,text,code,discount_vl,discount_percent,minimum_spend_vl,expires_at,requires_activation,conditions,maximum_discount_vl,extraction_method)
            VALUES (:id,:position,:kind,:text,:code,:amount,:percent,:minimum,:expires,:activation,CAST(:conditions AS jsonb),:maximum,:method)
            ON CONFLICT(observation_id,position_qt) {conflict_update(("kind", "text", "code", "discount_vl", "discount_percent", "minimum_spend_vl", "expires_at", "requires_activation", "conditions", "maximum_discount_vl", "extraction_method"), enrich_existing)}"""),
            {
                "id": observation_id,
                "position": position,
                "kind": promo.kind,
                "text": promo.text,
                "code": promo.code,
                "amount": promo.discount_amount,
                "percent": promo.discount_percent,
                "minimum": promo.minimum_spend,
                "expires": promo.expires_at,
                "activation": promo.requires_activation,
                "conditions": json.dumps(promo.conditions),
                "maximum": promo.maximum_discount,
                "method": promo.extraction_method,
            },
        )


async def save_payments(session, observation_id, payments, *, enrich_existing=False):
    for position, payment in enumerate(payments, 1):
        await session.execute(
            text(f"""INSERT INTO "pricing"."payment_option"
            (observation_id,position_qt,method,text,total_price_vl,installment_qt,installment_price_vl,interest_free,conditions,total_is_derived,extraction_method)
            VALUES (:id,:position,:method,:text,:total,:count,:price,:free,CAST(:conditions AS jsonb),:derived,:extraction_method)
            ON CONFLICT(observation_id,position_qt) {conflict_update(("method", "text", "total_price_vl", "installment_qt", "installment_price_vl", "interest_free", "conditions", "total_is_derived", "extraction_method"), enrich_existing)}"""),
            {
                "id": observation_id,
                "position": position,
                "method": payment.method,
                "text": payment.text,
                "total": payment.total_price,
                "count": payment.installment_count,
                "price": payment.installment_price,
                "free": payment.interest_free,
                "conditions": json.dumps(payment.conditions),
                "derived": payment.total_is_derived,
                "extraction_method": payment.extraction_method,
            },
        )
