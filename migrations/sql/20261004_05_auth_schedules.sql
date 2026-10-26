-- depends: 20261004_04_discovery
CREATE SCHEMA "auth";
CREATE TABLE "auth"."user" (
 id BIGINT GENERATED ALWAYS AS IDENTITY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid(),
 email TEXT NOT NULL, name TEXT NOT NULL, password_hash TEXT NOT NULL,
 active BOOLEAN NOT NULL DEFAULT true,
 CONSTRAINT auth_user_pk PRIMARY KEY (id),
 CONSTRAINT auth_user_public_id_uk UNIQUE(public_id),
 CONSTRAINT auth_user_email_uk UNIQUE(email)
);
COMMENT ON COLUMN "auth"."user".password_hash IS '[Encrypted] Argon2 password hash';
CREATE TABLE "auth"."session" (
 id BIGINT GENERATED ALWAYS AS IDENTITY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid(),
 user_id BIGINT NOT NULL, refresh_hash TEXT NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ,
 CONSTRAINT auth_session_pk PRIMARY KEY(id),
 CONSTRAINT auth_session_public_id_uk UNIQUE(public_id),
 CONSTRAINT auth_session_user_fk FOREIGN KEY(user_id) REFERENCES "auth"."user"(id)
);
COMMENT ON COLUMN "auth"."session".refresh_hash IS '[Encrypted] SHA256 current refresh token';
CREATE TABLE "scraping"."scheduled_routine" (
 id BIGINT GENERATED ALWAYS AS IDENTITY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid(),
 name TEXT NOT NULL, search_term_id BIGINT NOT NULL,
 mode TEXT NOT NULL, schedule JSONB NOT NULL, enabled BOOLEAN NOT NULL DEFAULT true,
 next_run_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT scheduled_routine_pk PRIMARY KEY(id),
 CONSTRAINT scheduled_routine_public_id_uk UNIQUE(public_id),
 CONSTRAINT scheduled_routine_term_fk FOREIGN KEY(search_term_id) REFERENCES "scraping"."search_term"(id),
 CONSTRAINT scheduled_routine_mode_ck CHECK(mode IN ('discover','refresh'))
);
CREATE INDEX scraping_scheduled_routine_due_idx ON "scraping"."scheduled_routine"(next_run_at) WHERE enabled;
