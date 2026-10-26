DROP TABLE alerting.delivery;
DROP TABLE alerting.webhook;
DROP SCHEMA alerting;
ALTER TABLE scraping.scrape_request DROP COLUMN routine_public_id;
