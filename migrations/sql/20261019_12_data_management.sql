-- depends: 20261018_11_ai_runtime
-- Independent of entity lifetime: deleted pages must not be rediscovered.
CREATE TABLE scraping.excluded_page (
 site TEXT NOT NULL,
 source_key TEXT NOT NULL,
 excluded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (site, source_key)
);
CREATE TABLE scraping.asset_deletion (
 bucket TEXT NOT NULL,
 object_key TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (bucket, object_key)
);
