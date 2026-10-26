-- depends: 20261006_08_commercial_details
ALTER TABLE "auth"."user" ADD COLUMN role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin'));
UPDATE "auth"."user" SET role='admin' WHERE email='admin@panoptes.com';
CREATE TABLE catalog.search_category (
 slug TEXT PRIMARY KEY CHECK(slug ~ '^[a-z][a-z0-9_]{0,59}$'),
 name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 100),
 keywords JSONB NOT NULL DEFAULT '[]', suggested_fields JSONB NOT NULL DEFAULT '[]',
 active BOOLEAN NOT NULL DEFAULT true, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO catalog.search_category(slug,name,keywords,suggested_fields) VALUES
 ('book','Livros','["livro","book"]','["Idioma","Formato","Edição"]'),
 ('appliances','Eletrodomésticos','["geladeira","refrigerador","freezer","fogão","microondas","micro ondas","lavadora","lava louças","liquidificador","aspirador","cafeteira","air fryer","ar condicionado"]','["Capacidade","Voltagem","Potência"]'),
 ('electronics','Eletrônicos','["tv","televisão","televisor","smartphone","celular","tablet","fone","câmera","notebook","monitor"]','["Tamanho da tela","Resolução","Voltagem"]'),
 ('hardware','Hardware','["ssd","hd","hdd","placa mãe","processador","memória ram","placa de vídeo","gpu","cpu","fonte de alimentação"]','["Capacidade de armazenamento","Velocidade de gravação","Interface"]'),
 ('school_supplies','Material escolar','["caderno","lápis","caneta","borracha","estojo"]','["Quantidade de itens","Material"]'),
 ('other','Outros','[]','[]');
CREATE INDEX scraping_search_term_criteria_idx ON scraping.search_term USING gin(criteria);
ALTER TABLE scraping.search_term ADD COLUMN configuration_key TEXT GENERATED ALWAYS AS (md5(criteria::text)) STORED;
ALTER TABLE scraping.search_term DROP CONSTRAINT search_term_site_term_uk;
ALTER TABLE scraping.search_term ADD CONSTRAINT search_term_site_configuration_uk UNIQUE(site,normalized_term,configuration_key);
