-- depends: 20261019_13_product_normalization
CREATE TABLE scraping.routine_search_term (
 routine_id BIGINT NOT NULL REFERENCES scraping.scheduled_routine(id) ON DELETE CASCADE,
 search_term_id BIGINT NOT NULL REFERENCES scraping.search_term(id),
 PRIMARY KEY (routine_id, search_term_id)
);
INSERT INTO scraping.routine_search_term (routine_id, search_term_id)
 SELECT id, search_term_id FROM scraping.scheduled_routine;
