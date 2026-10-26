-- depends: 20261006_09_product_profiles
CREATE TABLE catalog.product_search (
 entity_id BIGINT PRIMARY KEY REFERENCES scraping.entity(id) ON DELETE CASCADE,
 model TEXT NOT NULL, document_hash TEXT NOT NULL, document TEXT NOT NULL,
 embedding extensions.vector(384) NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX product_search_embedding_idx ON catalog.product_search
 USING hnsw (embedding extensions.vector_cosine_ops);
