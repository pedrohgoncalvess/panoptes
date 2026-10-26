-- depends: 20261004_05_auth_schedules
CREATE SCHEMA "catalog";
CREATE SCHEMA "pricing";
ALTER TABLE "scraping"."search_term" ADD COLUMN max_candidates_qt INTEGER NOT NULL DEFAULT 100;
ALTER TABLE "scraping"."search_term" ADD CONSTRAINT search_term_max_candidates_ck CHECK(max_candidates_qt BETWEEN 1 AND 1000);
CREATE TABLE "catalog"."product" (
 id BIGINT GENERATED ALWAYS AS IDENTITY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid(),
 identity_key TEXT NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL,
 brand TEXT, model TEXT, identifiers JSONB NOT NULL DEFAULT '{}',
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT catalog_product_pk PRIMARY KEY(id),
 CONSTRAINT catalog_product_public_id_uk UNIQUE(public_id),
 CONSTRAINT catalog_product_identity_key_uk UNIQUE(identity_key),
 CONSTRAINT catalog_product_category_ck CHECK(category IN ('book','television','refrigerator','school_supplies'))
);
CREATE TABLE "catalog"."variant" (
 id BIGINT GENERATED ALWAYS AS IDENTITY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid(),
 product_id BIGINT NOT NULL, identity_key TEXT NOT NULL,
 attributes JSONB NOT NULL DEFAULT '{}', identifiers JSONB NOT NULL DEFAULT '{}',
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT catalog_variant_pk PRIMARY KEY(id),
 CONSTRAINT catalog_variant_public_id_uk UNIQUE(public_id),
 CONSTRAINT catalog_variant_identity_uk UNIQUE(product_id,identity_key),
 CONSTRAINT catalog_variant_product_fk FOREIGN KEY(product_id) REFERENCES "catalog"."product"(id)
);
CREATE INDEX catalog_variant_attributes_idx ON "catalog"."variant" USING gin(attributes);
CREATE INDEX catalog_product_category_brand_idx ON "catalog"."product"(category,brand);
CREATE TABLE "catalog"."listing" (
 id BIGINT GENERATED ALWAYS AS IDENTITY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid(),
 entity_id BIGINT NOT NULL, variant_id BIGINT NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT catalog_listing_pk PRIMARY KEY(id),
 CONSTRAINT catalog_listing_public_id_uk UNIQUE(public_id),
 CONSTRAINT catalog_listing_entity_uk UNIQUE(entity_id),
 CONSTRAINT catalog_listing_entity_fk FOREIGN KEY(entity_id) REFERENCES "scraping"."entity"(id),
 CONSTRAINT catalog_listing_variant_fk FOREIGN KEY(variant_id) REFERENCES "catalog"."variant"(id)
);
CREATE INDEX catalog_listing_variant_idx ON "catalog"."listing"(variant_id);
CREATE TABLE "pricing"."offer" (
 id BIGINT GENERATED ALWAYS AS IDENTITY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid(),
 listing_id BIGINT NOT NULL, identity_key TEXT NOT NULL,
 seller TEXT, ships_from TEXT, condition TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT pricing_offer_pk PRIMARY KEY(id),
 CONSTRAINT pricing_offer_public_id_uk UNIQUE(public_id),
 CONSTRAINT pricing_offer_identity_uk UNIQUE(listing_id,identity_key),
 CONSTRAINT pricing_offer_listing_fk FOREIGN KEY(listing_id) REFERENCES "catalog"."listing"(id)
);
CREATE TABLE "pricing"."observation" (
 id BIGINT GENERATED ALWAYS AS IDENTITY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid(),
 offer_id BIGINT NOT NULL, source_observation_id BIGINT NOT NULL,
 observed_at TIMESTAMPTZ NOT NULL, price_vl NUMERIC(18,4), list_price_vl NUMERIC(18,4),
 currency CHAR(3), availability TEXT NOT NULL, availability_text TEXT, stock_qt INTEGER,
 CONSTRAINT pricing_observation_pk PRIMARY KEY(id),
 CONSTRAINT pricing_observation_public_id_uk UNIQUE(public_id),
 CONSTRAINT pricing_observation_source_uk UNIQUE(offer_id,source_observation_id),
 CONSTRAINT pricing_observation_offer_fk FOREIGN KEY(offer_id) REFERENCES "pricing"."offer"(id),
 CONSTRAINT pricing_observation_source_fk FOREIGN KEY(source_observation_id) REFERENCES "scraping"."observation"(id),
 CONSTRAINT pricing_observation_price_ck CHECK(price_vl>=0 AND list_price_vl>=0),
 CONSTRAINT pricing_observation_currency_ck CHECK(currency IS NULL OR currency ~ '^[A-Z]{3}$'),
 CONSTRAINT pricing_observation_priced_currency_ck CHECK((price_vl IS NULL AND list_price_vl IS NULL) OR currency IS NOT NULL),
 CONSTRAINT pricing_observation_stock_ck CHECK(stock_qt>=0),
 CONSTRAINT pricing_observation_availability_ck CHECK(availability IN ('in_stock','out_of_stock','unknown'))
);
CREATE INDEX pricing_observation_offer_time_idx ON "pricing"."observation"(offer_id,observed_at DESC,id DESC);
CREATE TABLE "pricing"."promotion" (
 id BIGINT GENERATED ALWAYS AS IDENTITY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid(),
 observation_id BIGINT NOT NULL, position_qt INTEGER NOT NULL,
 kind TEXT NOT NULL, text TEXT NOT NULL, code TEXT,
 discount_vl NUMERIC(18,4), discount_percent NUMERIC(7,4), minimum_spend_vl NUMERIC(18,4),
 expires_at TIMESTAMPTZ, requires_activation BOOLEAN, conditions JSONB NOT NULL DEFAULT '[]',
 CONSTRAINT pricing_promotion_pk PRIMARY KEY(id),
 CONSTRAINT pricing_promotion_public_id_uk UNIQUE(public_id),
 CONSTRAINT pricing_promotion_position_uk UNIQUE(observation_id,position_qt),
 CONSTRAINT pricing_promotion_observation_fk FOREIGN KEY(observation_id) REFERENCES "pricing"."observation"(id),
 CONSTRAINT pricing_promotion_kind_ck CHECK(kind IN ('coupon','discount','promotion','installment','shipping')),
 CONSTRAINT pricing_promotion_amount_ck CHECK(discount_vl>=0 AND minimum_spend_vl>=0 AND discount_percent BETWEEN 0 AND 100)
);
CREATE TABLE "pricing"."payment_option" (
 id BIGINT GENERATED ALWAYS AS IDENTITY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid(),
 observation_id BIGINT NOT NULL, position_qt INTEGER NOT NULL,
 method TEXT NOT NULL, text TEXT NOT NULL, total_price_vl NUMERIC(18,4),
 installment_qt INTEGER, installment_price_vl NUMERIC(18,4), interest_free BOOLEAN,
 conditions JSONB NOT NULL DEFAULT '[]',
 CONSTRAINT pricing_payment_option_pk PRIMARY KEY(id),
 CONSTRAINT pricing_payment_option_public_id_uk UNIQUE(public_id),
 CONSTRAINT pricing_payment_option_position_uk UNIQUE(observation_id,position_qt),
 CONSTRAINT pricing_payment_option_observation_fk FOREIGN KEY(observation_id) REFERENCES "pricing"."observation"(id),
 CONSTRAINT pricing_payment_option_method_ck CHECK(method IN ('pix','cash','card','installment')),
 CONSTRAINT pricing_payment_option_amount_ck CHECK(total_price_vl>=0 AND installment_price_vl>=0 AND installment_qt>=1)
);
CREATE TABLE "pricing"."shipping_quote" (
 id BIGINT GENERATED ALWAYS AS IDENTITY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid(),
 observation_id BIGINT NOT NULL, text TEXT NOT NULL, price_vl NUMERIC(18,4),
 is_free BOOLEAN, destination_postal_code TEXT, conditions JSONB NOT NULL DEFAULT '[]',
 CONSTRAINT pricing_shipping_quote_pk PRIMARY KEY(id),
 CONSTRAINT pricing_shipping_quote_public_id_uk UNIQUE(public_id),
 CONSTRAINT pricing_shipping_quote_observation_uk UNIQUE(observation_id),
 CONSTRAINT pricing_shipping_quote_observation_fk FOREIGN KEY(observation_id) REFERENCES "pricing"."observation"(id),
 CONSTRAINT pricing_shipping_quote_price_ck CHECK(price_vl>=0)
);
