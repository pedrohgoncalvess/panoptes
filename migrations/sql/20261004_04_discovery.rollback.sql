DROP TABLE "scraping"."observation_asset";
ALTER TABLE "scraping"."job" DROP CONSTRAINT job_scrape_request_fk, DROP COLUMN scrape_request_id;
ALTER TABLE "scraping"."html_snapshot" DROP CONSTRAINT html_snapshot_asset_fk, DROP COLUMN asset_id,
    DROP CONSTRAINT html_snapshot_scrape_request_fk, DROP COLUMN scrape_request_id;
DROP TABLE "scraping"."asset";
DROP TABLE "scraping"."search_term_entity";
DROP TABLE "scraping"."product_validation";
DROP TABLE "scraping"."search_candidate";
DROP TABLE "scraping"."scrape_request";
DROP TABLE "scraping"."tracking_target";
DROP TABLE "scraping"."search_term";
