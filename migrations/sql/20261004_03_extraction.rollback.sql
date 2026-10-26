DROP VIEW "scraping"."html_cost";
DROP INDEX "ai"."ai_interaction_html_snapshot_id_idx";
DROP INDEX "ai"."ai_interaction_provider_request_id_idx";
ALTER TABLE "ai"."interaction"
    DROP CONSTRAINT interaction_job_snapshot_fk,
    DROP CONSTRAINT interaction_snapshot_pair_ck,
    DROP CONSTRAINT interaction_attempt_qt_ck,
    DROP CONSTRAINT interaction_cost_status_ck,
    DROP CONSTRAINT interaction_cost_ck,
    DROP COLUMN job_id, DROP COLUMN html_snapshot_id,
    DROP COLUMN agent_version, DROP COLUMN prompt_sha256,
    DROP COLUMN attempt_qt, DROP COLUMN provider,
    DROP COLUMN price_snapshot, DROP COLUMN cost_status;
DROP TABLE "scraping"."embedding";
DROP TABLE "scraping"."observation";
DROP TABLE "scraping"."entity";
DROP TABLE "scraping"."layer_attempt";
DROP TABLE "scraping"."job";
DROP TABLE "scraping"."html_snapshot";
DROP TABLE "scraping"."parser";
DROP TABLE "scraping"."routine";
DROP SCHEMA "scraping";
-- Keep vector and extensions: other domains may depend on this shared extension.
