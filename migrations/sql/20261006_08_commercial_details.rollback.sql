DROP VIEW pricing.payment_history;
DROP INDEX pricing.pricing_payment_method_price_idx;
DROP INDEX pricing.pricing_observation_commerce_idx;
ALTER TABLE pricing.shipping_quote DROP COLUMN delivery_text, DROP COLUMN extraction_method;
ALTER TABLE pricing.promotion DROP COLUMN maximum_discount_vl, DROP COLUMN extraction_method;
ALTER TABLE pricing.payment_option DROP COLUMN total_is_derived, DROP COLUMN extraction_method;
ALTER TABLE pricing.observation DROP COLUMN stock_lower_bound_qt, DROP COLUMN units_per_pack,
 DROP COLUMN minimum_purchase_qt, DROP COLUMN maximum_purchase_qt,
 DROP COLUMN commercial_extraction, DROP COLUMN shipping_options;
-- Retain the widened category constraint to preserve any newly collected unclassified products.
