-- Persistent execution events, replayed to authenticated clients through SSE.
-- depends: 20261004_06_catalog_pricing
CREATE TABLE scraping.extraction_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id BIGINT NOT NULL REFERENCES scraping.scrape_request(id),
    correlation_id UUID NOT NULL,
    site TEXT,
    level TEXT NOT NULL CHECK (level IN ('INFO','WARNING','ERROR')),
    event TEXT NOT NULL,
    message TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX extraction_log_request_cursor_idx ON scraping.extraction_log(request_id,id);
CREATE INDEX extraction_log_site_cursor_idx ON scraping.extraction_log(site,id);

-- Older executions retain their existing summary; detailed stages begin now.
INSERT INTO scraping.extraction_log(request_id,correlation_id,site,level,event,message,details)
SELECT r.id,r.correlation_id,coalesce(t.site,e.site),
    CASE WHEN r.status IN ('failed','blocked') THEN 'ERROR' ELSE 'INFO' END,
    'historical_summary','Resumo de execução anterior ao registro detalhado.',
    jsonb_build_object('status',r.status,'reason',r.summary->'reason',
      'error',r.summary->'error','error_id',r.summary->'error_id')
FROM scraping.scrape_request r
LEFT JOIN scraping.search_term t ON t.id=r.search_term_id
LEFT JOIN scraping.tracking_target target ON target.id=r.tracking_target_id
LEFT JOIN scraping.entity e ON e.id=target.entity_id
WHERE r.status NOT IN ('pending','running');
