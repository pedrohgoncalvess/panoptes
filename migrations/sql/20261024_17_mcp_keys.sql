-- depends: 20261024_16_alerts
-- Existing sessions must also respect the new maximum remaining lifetime.
UPDATE auth.session SET expires_at=least(expires_at,now() + interval '10 hours')
WHERE revoked_at IS NULL;
CREATE TABLE auth.mcp_key (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
 user_id BIGINT NOT NULL REFERENCES auth."user"(id),
 name TEXT NOT NULL,
 token_hash TEXT NOT NULL UNIQUE,
 admin BOOLEAN NOT NULL DEFAULT false,
 permissions JSONB NOT NULL DEFAULT '{}'::jsonb,
 expires_at TIMESTAMPTZ,
 revoked_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON COLUMN auth.mcp_key.token_hash IS '[Encrypted] SHA256 MCP credential; plaintext returned only on creation';
CREATE TABLE auth.mcp_key_routine (
 key_id BIGINT NOT NULL REFERENCES auth.mcp_key(id) ON DELETE CASCADE,
 routine_id BIGINT NOT NULL REFERENCES scraping.scheduled_routine(id) ON DELETE CASCADE,
 created_by_key BOOLEAN NOT NULL DEFAULT false,
 PRIMARY KEY(key_id,routine_id)
);
CREATE TABLE auth.mcp_key_term (
 key_id BIGINT NOT NULL REFERENCES auth.mcp_key(id) ON DELETE CASCADE,
 term_id BIGINT NOT NULL REFERENCES scraping.search_term(id) ON DELETE CASCADE,
 PRIMARY KEY(key_id,term_id)
);
ALTER TABLE alerting.webhook ADD COLUMN mcp_key_id BIGINT REFERENCES auth.mcp_key(id);
