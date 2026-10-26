-- depends: 20261019_15_taxonomy
CREATE SCHEMA alerting;
ALTER TABLE scraping.scrape_request ADD COLUMN routine_public_id UUID;
CREATE TABLE alerting.webhook (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
 name TEXT NOT NULL,
 url TEXT NOT NULL,
 enabled BOOLEAN NOT NULL DEFAULT true,
 rules JSONB NOT NULL CHECK(jsonb_typeof(rules)='array'),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE alerting.delivery (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 public_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
 webhook_id BIGINT NOT NULL REFERENCES alerting.webhook(id) ON DELETE CASCADE,
 event TEXT NOT NULL,
 event_key TEXT NOT NULL,
 destination_url TEXT NOT NULL,
 payload JSONB NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','delivered','failed','cancelled')),
 attempts INTEGER NOT NULL DEFAULT 0,
 http_status INTEGER,
 last_error TEXT,
 next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 delivered_at TIMESTAMPTZ,
 UNIQUE(webhook_id,event_key)
);
CREATE INDEX alerting_delivery_due_idx ON alerting.delivery(next_attempt_at,id) WHERE status='pending';
