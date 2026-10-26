-- depends: 20261019_12_data_management
CREATE TABLE catalog.canonical_product (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
 identity_key TEXT NOT NULL UNIQUE,
 name TEXT NOT NULL,
 identity JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE catalog.product_normalization (
 listing_id BIGINT PRIMARY KEY REFERENCES catalog.listing(id) ON DELETE CASCADE,
 canonical_product_id BIGINT REFERENCES catalog.canonical_product(id),
 input_hash TEXT NOT NULL,
 input JSONB NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending'
   CHECK(status IN ('pending','processing','completed','uncertain','failed')),
 result JSONB,
 attempts INTEGER NOT NULL DEFAULT 0,
 available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 lease_token UUID,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX product_normalization_due_idx ON catalog.product_normalization(available_at)
 WHERE status IN ('pending','processing','failed');
CREATE INDEX product_normalization_canonical_idx ON catalog.product_normalization(canonical_product_id);
-- Existing listings enter the same queue as future captures. Only identity evidence
-- is hashed: price and image changes must not incur a new inference.
INSERT INTO catalog.product_normalization(listing_id,input_hash,input)
SELECT l.id,md5(evidence::text),evidence FROM catalog.listing l
JOIN LATERAL (
 SELECT jsonb_build_object('entity', jsonb_build_object('title',o.payload->'entity'->'title',
 'description',o.payload->'entity'->'description'), 'catalog',o.payload->'catalog',
 'specifications',coalesce(o.payload->'specifications','{}'::jsonb),
 'offer',jsonb_build_object('condition',o.payload->'offer'->'condition')) AS evidence
 FROM scraping.observation o WHERE o.entity_id=l.entity_id ORDER BY o.id DESC LIMIT 1
) latest ON true;
