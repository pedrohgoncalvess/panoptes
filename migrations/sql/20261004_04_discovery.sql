-- Search aggregation, executable discovery/refresh requests and private assets.
-- depends: 20261004_03_extraction
CREATE TABLE "scraping"."search_term" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    site TEXT NOT NULL,
    term TEXT NOT NULL,
    normalized_term TEXT NOT NULL,
    criteria JSONB NOT NULL,
    max_pages_qt INTEGER NOT NULL DEFAULT 1,
    refresh_interval_seconds INTEGER NOT NULL DEFAULT 86400,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT search_term_pk PRIMARY KEY (id),
    CONSTRAINT search_term_public_id_uk UNIQUE (public_id),
    CONSTRAINT search_term_site_term_uk UNIQUE (site, normalized_term),
    CONSTRAINT search_term_pages_ck CHECK (max_pages_qt BETWEEN 1 AND 20),
    CONSTRAINT search_term_interval_ck CHECK (refresh_interval_seconds >= 60)
);

CREATE TABLE "scraping"."tracking_target" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    entity_id BIGINT NOT NULL,
    product_url TEXT NOT NULL,
    criteria JSONB NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    refresh_interval_seconds INTEGER NOT NULL,
    next_poll_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tracking_target_pk PRIMARY KEY (id),
    CONSTRAINT tracking_target_public_id_uk UNIQUE (public_id),
    CONSTRAINT tracking_target_entity_uk UNIQUE (entity_id),
    CONSTRAINT tracking_target_entity_fk FOREIGN KEY (entity_id) REFERENCES "scraping"."entity" (id),
    CONSTRAINT tracking_target_interval_ck CHECK (refresh_interval_seconds >= 60)
);
CREATE INDEX scraping_tracking_target_due_idx ON "scraping"."tracking_target" (next_poll_at) WHERE enabled;

CREATE TABLE "scraping"."scrape_request" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    correlation_id UUID NOT NULL DEFAULT gen_random_uuid(),
    mode TEXT NOT NULL,
    search_term_id BIGINT,
    tracking_target_id BIGINT,
    status TEXT NOT NULL DEFAULT 'pending',
    lease_owner UUID,
    lease_expires_at TIMESTAMPTZ,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT scrape_request_pk PRIMARY KEY (id),
    CONSTRAINT scrape_request_public_id_uk UNIQUE (public_id),
    CONSTRAINT scrape_request_search_term_fk FOREIGN KEY (search_term_id) REFERENCES "scraping"."search_term" (id),
    CONSTRAINT scrape_request_tracking_target_fk FOREIGN KEY (tracking_target_id) REFERENCES "scraping"."tracking_target" (id),
    CONSTRAINT scrape_request_mode_ck CHECK (
        (mode = 'discover' AND search_term_id IS NOT NULL AND tracking_target_id IS NULL) OR
        (mode = 'refresh' AND tracking_target_id IS NOT NULL AND search_term_id IS NULL)),
    CONSTRAINT scrape_request_status_ck CHECK (status IN ('pending', 'running', 'completed', 'partial', 'failed', 'blocked')),
    CONSTRAINT scrape_request_lease_ck CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL))
);
CREATE UNIQUE INDEX scraping_scrape_request_active_term_idx ON "scraping"."scrape_request" (search_term_id)
    WHERE status IN ('pending', 'running') AND mode = 'discover';
CREATE UNIQUE INDEX scraping_scrape_request_active_target_idx ON "scraping"."scrape_request" (tracking_target_id)
    WHERE status IN ('pending', 'running') AND mode = 'refresh';
CREATE INDEX scraping_scrape_request_claim_idx ON "scraping"."scrape_request" (status, lease_expires_at, created_at);

CREATE TABLE "scraping"."search_candidate" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    scrape_request_id BIGINT NOT NULL,
    html_snapshot_id BIGINT NOT NULL,
    source_key TEXT NOT NULL,
    validation JSONB NOT NULL,
    detail_validation JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT search_candidate_pk PRIMARY KEY (id),
    CONSTRAINT search_candidate_public_id_uk UNIQUE (public_id),
    CONSTRAINT search_candidate_request_source_uk UNIQUE (scrape_request_id, source_key),
    CONSTRAINT search_candidate_scrape_request_fk FOREIGN KEY (scrape_request_id) REFERENCES "scraping"."scrape_request" (id),
    CONSTRAINT search_candidate_html_snapshot_fk FOREIGN KEY (html_snapshot_id) REFERENCES "scraping"."html_snapshot" (id)
);

CREATE TABLE "scraping"."search_term_entity" (
    search_term_id BIGINT NOT NULL,
    entity_id BIGINT NOT NULL,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT search_term_entity_pk PRIMARY KEY (search_term_id, entity_id),
    CONSTRAINT search_term_entity_search_term_fk FOREIGN KEY (search_term_id) REFERENCES "scraping"."search_term" (id),
    CONSTRAINT search_term_entity_entity_fk FOREIGN KEY (entity_id) REFERENCES "scraping"."entity" (id)
);
CREATE INDEX scraping_search_term_entity_entity_idx ON "scraping"."search_term_entity" (entity_id);

CREATE TABLE "scraping"."product_validation" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    scrape_request_id BIGINT NOT NULL,
    html_snapshot_id BIGINT NOT NULL,
    source_key TEXT NOT NULL,
    validation JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT product_validation_pk PRIMARY KEY (id),
    CONSTRAINT product_validation_public_id_uk UNIQUE (public_id),
    CONSTRAINT product_validation_request_snapshot_uk UNIQUE (scrape_request_id, html_snapshot_id),
    CONSTRAINT product_validation_scrape_request_fk FOREIGN KEY (scrape_request_id) REFERENCES "scraping"."scrape_request" (id),
    CONSTRAINT product_validation_html_snapshot_fk FOREIGN KEY (html_snapshot_id) REFERENCES "scraping"."html_snapshot" (id)
);

CREATE TABLE "scraping"."asset" (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    kind TEXT NOT NULL,
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    byte_qt BIGINT NOT NULL,
    media_type TEXT NOT NULL,
    source_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT asset_pk PRIMARY KEY (id),
    CONSTRAINT asset_public_id_uk UNIQUE (public_id),
    CONSTRAINT asset_bucket_object_key_uk UNIQUE (bucket, object_key),
    CONSTRAINT asset_sha_ck CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    CONSTRAINT asset_byte_qt_ck CHECK (byte_qt >= 0),
    CONSTRAINT asset_kind_ck CHECK (kind IN ('html', 'image', 'document', 'screenshot', 'other'))
);
ALTER TABLE "scraping"."html_snapshot"
    ADD COLUMN asset_id BIGINT,
    ADD COLUMN scrape_request_id BIGINT,
    ADD CONSTRAINT html_snapshot_asset_fk FOREIGN KEY (asset_id) REFERENCES "scraping"."asset" (id),
    ADD CONSTRAINT html_snapshot_scrape_request_fk FOREIGN KEY (scrape_request_id) REFERENCES "scraping"."scrape_request" (id);
CREATE INDEX scraping_html_snapshot_request_idx ON "scraping"."html_snapshot" (scrape_request_id);
ALTER TABLE "scraping"."job"
    ADD COLUMN scrape_request_id BIGINT,
    ADD CONSTRAINT job_scrape_request_fk FOREIGN KEY (scrape_request_id) REFERENCES "scraping"."scrape_request" (id);
CREATE TABLE "scraping"."observation_asset" (
    observation_id BIGINT NOT NULL,
    asset_id BIGINT NOT NULL,
    CONSTRAINT observation_asset_pk PRIMARY KEY (observation_id, asset_id),
    CONSTRAINT observation_asset_observation_fk FOREIGN KEY (observation_id) REFERENCES "scraping"."observation" (id),
    CONSTRAINT observation_asset_asset_fk FOREIGN KEY (asset_id) REFERENCES "scraping"."asset" (id)
);
