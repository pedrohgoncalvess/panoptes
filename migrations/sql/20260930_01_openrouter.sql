-- OpenRouter core: model catalog, price history and recorded interactions.
-- depends:

CREATE SCHEMA IF NOT EXISTS "ai";

CREATE TABLE "ai"."model" (
    id SERIAL PRIMARY KEY,
    public_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    provider_id TEXT NOT NULL UNIQUE,
    canonical_slug TEXT,
    name TEXT NOT NULL,
    description TEXT,
    context_length INTEGER,
    architecture JSONB NOT NULL DEFAULT '{}'::jsonb,
    top_provider JSONB NOT NULL DEFAULT '{}'::jsonb,
    per_request_limits JSONB,
    supported_parameters TEXT[] NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE TABLE "ai"."model_price" (
    id SERIAL PRIMARY KEY,
    public_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    model_id INTEGER NOT NULL REFERENCES "ai"."model" (id),
    prompt NUMERIC(24, 16),
    completion NUMERIC(24, 16),
    request NUMERIC(24, 16),
    image NUMERIC(24, 16),
    web_search NUMERIC(24, 16),
    internal_reasoning NUMERIC(24, 16),
    input_cache_read NUMERIC(24, 16),
    input_cache_write NUMERIC(24, 16),
    currency CHAR(3) NOT NULL DEFAULT 'USD',
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX model_price_current_model_idx
    ON "ai"."model_price" (model_id)
    WHERE deleted_at IS NULL;

CREATE TABLE "ai"."interaction" (
    id SERIAL PRIMARY KEY,
    public_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    model_id INTEGER REFERENCES "ai"."model" (id),
    provider_request_id TEXT,
    trace_id UUID,
    request JSONB NOT NULL,
    response JSONB,
    structured_output JSONB,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    cost NUMERIC(24, 16),
    latency_ms INTEGER,
    status TEXT NOT NULL,
    error JSONB,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT interaction_status_ck
        CHECK (status IN ('pending', 'completed', 'failed', 'cancelled'))
);

CREATE INDEX interaction_model_inserted_at_idx
    ON "ai"."interaction" (model_id, inserted_at DESC);
