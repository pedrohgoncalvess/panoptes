-- depends: 20261006_10_product_search
ALTER TABLE ai.model
 ADD COLUMN input_modalities TEXT[] NOT NULL DEFAULT '{}',
 ADD COLUMN output_modalities TEXT[] NOT NULL DEFAULT '{}',
 ADD COLUMN default_parameters JSONB,
 ADD COLUMN expiration_date DATE,
 ADD COLUMN catalog_synced_at TIMESTAMPTZ;
CREATE INDEX model_input_modalities_idx ON ai.model USING gin(input_modalities);
CREATE INDEX model_output_modalities_idx ON ai.model USING gin(output_modalities);
ALTER TABLE ai.model_price
 ADD COLUMN pricing JSONB NOT NULL DEFAULT '{}',
 ADD COLUMN source TEXT NOT NULL DEFAULT 'openrouter',
 ADD COLUMN checked_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE ai.agent ALTER COLUMN structured_output_schema DROP NOT NULL;
ALTER TABLE ai.interaction
 ADD COLUMN context JSONB NOT NULL DEFAULT '{}',
 ADD COLUMN audit_bucket TEXT,
 ADD COLUMN audit_object_key TEXT,
 ADD COLUMN audit_sha256 CHAR(64),
 ADD COLUMN audit_uploaded_at TIMESTAMPTZ,
 ADD COLUMN finished_at TIMESTAMPTZ,
 ADD COLUMN requested_model_id INTEGER REFERENCES ai.model(id),
 ADD COLUMN scrape_request_id BIGINT REFERENCES scraping.scrape_request(id),
 ADD CONSTRAINT interaction_snapshot_fk FOREIGN KEY(html_snapshot_id) REFERENCES scraping.html_snapshot(id);
ALTER TABLE ai.interaction DROP CONSTRAINT interaction_snapshot_pair_ck;
ALTER TABLE ai.interaction ADD CONSTRAINT interaction_snapshot_pair_ck CHECK(job_id IS NULL OR html_snapshot_id IS NOT NULL);
CREATE TABLE ai.audit_outbox (
 interaction_id INTEGER PRIMARY KEY REFERENCES ai.interaction(id),
 payload JSONB NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0,
 available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 last_error TEXT
);
CREATE INDEX audit_outbox_available_idx ON ai.audit_outbox(available_at);
-- Variable dimensions allow changing the embedding agent without padding vectors.
-- The model/version filter prevents comparisons across embedding spaces.
DROP INDEX catalog.product_search_embedding_idx;
ALTER TABLE catalog.product_search ALTER COLUMN embedding TYPE extensions.vector;
