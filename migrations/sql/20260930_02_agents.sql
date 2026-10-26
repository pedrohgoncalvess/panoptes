-- Platform agents. Requires the OpenRouter core migration.
-- depends: 20260930_01_openrouter

CREATE TABLE "ai"."agent" (
    id SERIAL PRIMARY KEY,
    public_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    default_model_id INTEGER NOT NULL REFERENCES "ai"."model" (id),
    prompt TEXT NOT NULL,
    structured_output_schema JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

ALTER TABLE "ai"."interaction"
    ADD COLUMN agent_id INTEGER REFERENCES "ai"."agent" (id);

CREATE INDEX interaction_agent_inserted_at_idx
    ON "ai"."interaction" (agent_id, inserted_at DESC);
