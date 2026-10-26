DROP INDEX scraping.scraping_search_term_criteria_idx;
ALTER TABLE scraping.search_term DROP CONSTRAINT search_term_site_configuration_uk;
ALTER TABLE scraping.search_term DROP COLUMN configuration_key;
ALTER TABLE scraping.search_term ADD CONSTRAINT search_term_site_term_uk UNIQUE(site,normalized_term);
DROP TABLE catalog.search_category;
ALTER TABLE "auth"."user" DROP COLUMN role;
