-- Reindex after rollback; vectors from a different model cannot be reused.
DELETE FROM catalog.product_search;
ALTER TABLE catalog.product_search ALTER COLUMN embedding TYPE extensions.vector(384);
CREATE INDEX product_search_embedding_idx ON catalog.product_search
 USING hnsw (embedding extensions.vector_cosine_ops);
DROP TABLE ai.audit_outbox;
UPDATE ai.interaction SET html_snapshot_id=NULL WHERE job_id IS NULL;
ALTER TABLE ai.interaction DROP CONSTRAINT interaction_snapshot_pair_ck;
ALTER TABLE ai.interaction ADD CONSTRAINT interaction_snapshot_pair_ck CHECK((job_id IS NULL)=(html_snapshot_id IS NULL));
ALTER TABLE ai.interaction
 DROP COLUMN context, DROP COLUMN audit_bucket, DROP COLUMN audit_object_key,
 DROP COLUMN audit_sha256, DROP COLUMN audit_uploaded_at, DROP COLUMN finished_at,
 DROP COLUMN scrape_request_id, DROP COLUMN requested_model_id, DROP CONSTRAINT interaction_snapshot_fk;
UPDATE ai.agent SET structured_output_schema = '{}'::jsonb WHERE structured_output_schema IS NULL;
ALTER TABLE ai.agent ALTER COLUMN structured_output_schema SET NOT NULL;
ALTER TABLE ai.model_price DROP COLUMN pricing, DROP COLUMN source, DROP COLUMN checked_at;
DROP INDEX ai.model_input_modalities_idx;
DROP INDEX ai.model_output_modalities_idx;
ALTER TABLE ai.model DROP COLUMN input_modalities, DROP COLUMN output_modalities,
 DROP COLUMN default_parameters, DROP COLUMN expiration_date, DROP COLUMN catalog_synced_at;
