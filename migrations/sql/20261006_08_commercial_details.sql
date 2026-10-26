-- depends: 20261005_07_extraction_logs
ALTER TABLE catalog.product DROP CONSTRAINT catalog_product_category_ck;
ALTER TABLE catalog.product ADD CONSTRAINT catalog_product_category_ck CHECK(category IN ('book','television','refrigerator','school_supplies','other'));
ALTER TABLE pricing.observation
 ADD COLUMN stock_lower_bound_qt INTEGER CHECK(stock_lower_bound_qt >= 0),
 ADD COLUMN units_per_pack INTEGER CHECK(units_per_pack >= 1),
 ADD COLUMN minimum_purchase_qt INTEGER CHECK(minimum_purchase_qt >= 1),
 ADD COLUMN maximum_purchase_qt INTEGER CHECK(maximum_purchase_qt >= 1),
 ADD COLUMN commercial_extraction JSONB,
 ADD COLUMN shipping_options JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE pricing.payment_option
 ADD COLUMN total_is_derived BOOLEAN NOT NULL DEFAULT false,
 ADD COLUMN extraction_method TEXT NOT NULL DEFAULT 'deterministic' CHECK(extraction_method IN ('deterministic','openrouter'));
ALTER TABLE pricing.promotion
 ADD COLUMN maximum_discount_vl NUMERIC(18,4) CHECK(maximum_discount_vl >= 0),
 ADD COLUMN extraction_method TEXT NOT NULL DEFAULT 'deterministic' CHECK(extraction_method IN ('deterministic','openrouter'));
ALTER TABLE pricing.shipping_quote
 ADD COLUMN delivery_text TEXT,
 ADD COLUMN extraction_method TEXT NOT NULL DEFAULT 'deterministic' CHECK(extraction_method IN ('deterministic','openrouter'));
CREATE INDEX pricing_payment_method_price_idx ON pricing.payment_option(method,total_price_vl);
CREATE INDEX pricing_observation_commerce_idx ON pricing.observation USING gin(commercial_extraction);
-- Conditional prices remain separate from the advertised price. Coupons are never applied implicitly.
CREATE VIEW pricing.payment_history AS
 SELECT o.public_id AS observation_id, o.observed_at,e.public_id AS entity_id,e.site,e.source_key,
        c.public_id AS product_id,v.public_id AS variant_id,f.seller,f.condition,o.currency,
        o.price_vl AS advertised_price_vl,p.method,p.total_price_vl,p.installment_qt,
        p.installment_price_vl,p.interest_free,p.total_is_derived,p.conditions,p.extraction_method,
        o.units_per_pack,
        CASE WHEN o.units_per_pack IS NOT NULL THEN p.total_price_vl/o.units_per_pack END AS unit_price_vl,
        s.destination_postal_code,s.price_vl AS shipping_price_vl,s.is_free AS shipping_is_free
 FROM pricing.observation o JOIN pricing.offer f ON f.id=o.offer_id
 JOIN catalog.listing l ON l.id=f.listing_id JOIN scraping.entity e ON e.id=l.entity_id
 JOIN catalog.variant v ON v.id=l.variant_id JOIN catalog.product c ON c.id=v.product_id
 JOIN pricing.payment_option p ON p.observation_id=o.id
 LEFT JOIN pricing.shipping_quote s ON s.observation_id=o.id;
