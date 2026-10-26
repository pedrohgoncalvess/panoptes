-- Extraction domain and per-HTML LLM accounting.
-- depends: 20260930_02_agents
CREATE SCHEMA IF NOT EXISTS "extensions";
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA "extensions";
CREATE SCHEMA "scraping";

CREATE TABLE "scraping"."routine" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL,
    version TEXT NOT NULL,
    definition JSONB NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT routine_pk PRIMARY KEY (id),
    CONSTRAINT routine_public_id_uk UNIQUE (public_id),
    CONSTRAINT routine_slug_version_uk UNIQUE (slug, version)
);

CREATE TABLE "scraping"."parser" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL,
    version TEXT NOT NULL,
    manifest JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT parser_pk PRIMARY KEY (id),
    CONSTRAINT parser_public_id_uk UNIQUE (public_id),
    CONSTRAINT parser_slug_version_uk UNIQUE (slug, version)
);

CREATE TABLE "scraping"."html_snapshot" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    parent_snapshot_id BIGINT,
    source_url TEXT NOT NULL,
    final_url TEXT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    artifact_uri TEXT NOT NULL,
    capture_metadata JSONB NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT html_snapshot_pk PRIMARY KEY (id),
    CONSTRAINT html_snapshot_public_id_uk UNIQUE (public_id),
    CONSTRAINT html_snapshot_parent_fk FOREIGN KEY (parent_snapshot_id)
        REFERENCES "scraping"."html_snapshot" (id),
    CONSTRAINT html_snapshot_sha256_ck CHECK (sha256 ~ '^[a-f0-9]{64}$')
);
CREATE INDEX scraping_html_snapshot_sha256_idx ON "scraping"."html_snapshot" (sha256);

CREATE TABLE "scraping"."job" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    routine_id BIGINT NOT NULL,
    parser_id BIGINT NOT NULL,
    html_snapshot_id BIGINT NOT NULL,
    correlation_id UUID NOT NULL,
    idempotency_key TEXT NOT NULL,
    policy JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_qt INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT job_pk PRIMARY KEY (id),
    CONSTRAINT job_public_id_uk UNIQUE (public_id),
    CONSTRAINT job_id_snapshot_uk UNIQUE (id, html_snapshot_id),
    CONSTRAINT job_idempotency_key_uk UNIQUE (idempotency_key),
    CONSTRAINT job_routine_fk FOREIGN KEY (routine_id) REFERENCES "scraping"."routine" (id),
    CONSTRAINT job_parser_fk FOREIGN KEY (parser_id) REFERENCES "scraping"."parser" (id),
    CONSTRAINT job_html_snapshot_fk FOREIGN KEY (html_snapshot_id) REFERENCES "scraping"."html_snapshot" (id),
    CONSTRAINT job_attempt_qt_ck CHECK (attempt_qt >= 0),
    CONSTRAINT job_status_ck CHECK (status IN ('pending', 'running', 'completed', 'exhausted', 'blocked', 'failed')),
    CONSTRAINT job_lease_ck CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL))
);
CREATE INDEX scraping_job_claim_idx ON "scraping"."job" (status, lease_expires_at, created_at);

CREATE TABLE "scraping"."layer_attempt" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    job_id BIGINT NOT NULL,
    layer TEXT NOT NULL,
    result JSONB NOT NULL,
    duration_ms INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT layer_attempt_pk PRIMARY KEY (id),
    CONSTRAINT layer_attempt_public_id_uk UNIQUE (public_id),
    CONSTRAINT layer_attempt_job_fk FOREIGN KEY (job_id) REFERENCES "scraping"."job" (id),
    CONSTRAINT layer_attempt_duration_ck CHECK (duration_ms >= 0),
    CONSTRAINT layer_attempt_layer_ck CHECK (layer IN ('structured_data', 'site_parser', 'rendered_dom', 'llm'))
);

CREATE TABLE "scraping"."entity" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    site TEXT NOT NULL,
    source_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT entity_pk PRIMARY KEY (id),
    CONSTRAINT entity_public_id_uk UNIQUE (public_id),
    CONSTRAINT entity_site_source_key_uk UNIQUE (site, source_key),
    CONSTRAINT entity_kind_ck CHECK (kind IN ('product', 'service'))
);

CREATE TABLE "scraping"."observation" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    entity_id BIGINT NOT NULL,
    job_id BIGINT NOT NULL,
    payload JSONB NOT NULL,
    evidence JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT observation_pk PRIMARY KEY (id),
    CONSTRAINT observation_public_id_uk UNIQUE (public_id),
    CONSTRAINT observation_entity_job_uk UNIQUE (entity_id, job_id),
    CONSTRAINT observation_entity_fk FOREIGN KEY (entity_id) REFERENCES "scraping"."entity" (id),
    CONSTRAINT observation_job_fk FOREIGN KEY (job_id) REFERENCES "scraping"."job" (id)
);

CREATE TABLE "scraping"."embedding" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    html_snapshot_id BIGINT NOT NULL,
    model TEXT NOT NULL,
    dimensions_qt INTEGER NOT NULL,
    embedding "extensions".vector NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT embedding_pk PRIMARY KEY (id),
    CONSTRAINT embedding_public_id_uk UNIQUE (public_id),
    CONSTRAINT embedding_snapshot_model_uk UNIQUE (html_snapshot_id, model),
    CONSTRAINT embedding_html_snapshot_fk FOREIGN KEY (html_snapshot_id) REFERENCES "scraping"."html_snapshot" (id),
    CONSTRAINT embedding_dimensions_ck CHECK (dimensions_qt > 0 AND "extensions".vector_dims(embedding) = dimensions_qt)
);

ALTER TABLE "ai"."interaction"
    ADD COLUMN job_id BIGINT,
    ADD COLUMN html_snapshot_id BIGINT,
    ADD COLUMN agent_version TEXT,
    ADD COLUMN prompt_sha256 CHAR(64),
    ADD COLUMN attempt_qt INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN provider TEXT,
    ADD COLUMN price_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN cost_status TEXT NOT NULL DEFAULT 'unknown';
UPDATE "ai"."interaction" SET cost_status = 'reported' WHERE cost IS NOT NULL;
ALTER TABLE "ai"."interaction"
    ADD CONSTRAINT interaction_job_snapshot_fk FOREIGN KEY (job_id, html_snapshot_id)
        REFERENCES "scraping"."job" (id, html_snapshot_id),
    ADD CONSTRAINT interaction_snapshot_pair_ck CHECK ((job_id IS NULL) = (html_snapshot_id IS NULL)),
    ADD CONSTRAINT interaction_attempt_qt_ck CHECK (attempt_qt > 0),
    ADD CONSTRAINT interaction_cost_status_ck CHECK (cost_status IN ('unknown', 'estimated', 'reported', 'reconciled')),
    ADD CONSTRAINT interaction_cost_ck CHECK ((cost IS NULL) = (cost_status = 'unknown') AND (cost IS NULL OR cost >= 0));
CREATE UNIQUE INDEX ai_interaction_provider_request_id_idx
    ON "ai"."interaction" (provider_request_id) WHERE provider_request_id IS NOT NULL;
CREATE INDEX ai_interaction_html_snapshot_id_idx ON "ai"."interaction" (html_snapshot_id);

CREATE VIEW "scraping"."html_cost" AS
SELECT s.public_id AS snapshot_id,
       coalesce(sum(i.cost), 0) AS known_cost_usd,
       count(i.id) FILTER (WHERE i.cost_status = 'unknown') AS unknown_interactions_qt,
       count(i.id) FILTER (WHERE i.cost_status = 'estimated') AS estimated_interactions_qt,
       count(i.id) AS interactions_qt,
       count(i.id) FILTER (WHERE i.cost_status IN ('unknown', 'estimated')) = 0 AS complete
FROM "scraping"."html_snapshot" s
LEFT JOIN "ai"."interaction" i ON i.html_snapshot_id = s.id
GROUP BY s.public_id;
