-- depends: 20261019_14_routine_sources
CREATE TABLE catalog.taxon (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 parent_id UUID REFERENCES catalog.taxon(id),
 name TEXT NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 100),
 normalized_name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 active BOOLEAN NOT NULL DEFAULT true,
 origin TEXT NOT NULL DEFAULT 'manual' CHECK(origin IN ('manual','agent','seed')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CHECK(parent_id IS NULL OR parent_id<>id)
);
CREATE UNIQUE INDEX taxon_category_name_uk ON catalog.taxon(normalized_name) WHERE parent_id IS NULL;
CREATE UNIQUE INDEX taxon_subcategory_name_uk ON catalog.taxon(parent_id,normalized_name) WHERE parent_id IS NOT NULL;
CREATE TABLE catalog.taxonomy_policy (
 id BOOLEAN PRIMARY KEY DEFAULT true CHECK(id),
 category_target INTEGER NOT NULL DEFAULT 20 CHECK(category_target BETWEEN 1 AND 1000),
 subcategory_target INTEGER NOT NULL DEFAULT 200 CHECK(subcategory_target BETWEEN 1 AND 10000),
 allow_creation BOOLEAN NOT NULL DEFAULT true
);
INSERT INTO catalog.taxonomy_policy(id) VALUES(true);
INSERT INTO catalog.taxon(name,normalized_name,origin) VALUES
 ('Livros','livros','seed'),('Hardware','hardware','seed'),
 ('Eletrônicos','eletronicos','seed'),('Eletrodomésticos','eletrodomesticos','seed'),
 ('Material escolar','material escolar','seed');
CREATE TABLE catalog.product_taxonomy (
 product_id BIGINT NOT NULL REFERENCES catalog.canonical_product(id) ON DELETE CASCADE,
 taxon_id UUID NOT NULL REFERENCES catalog.taxon(id),
 PRIMARY KEY(product_id,taxon_id)
);
CREATE INDEX product_taxonomy_taxon_idx ON catalog.product_taxonomy(taxon_id,product_id);
CREATE TABLE catalog.taxonomy_task (
 product_id BIGINT PRIMARY KEY REFERENCES catalog.canonical_product(id) ON DELETE CASCADE,
 evidence JSONB NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending'
   CHECK(status IN ('pending','processing','completed','needs_review','failed','manual')),
 result JSONB,
 attempts INTEGER NOT NULL DEFAULT 0,
 lease_token UUID,
 available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX taxonomy_task_due_idx ON catalog.taxonomy_task(available_at)
 WHERE status IN ('pending','processing','failed');
INSERT INTO catalog.taxonomy_task(product_id,evidence)
SELECT c.id,jsonb_build_object('name',c.name,'identity',c.identity,'source',coalesce((
 SELECT n.input FROM catalog.product_normalization n WHERE n.canonical_product_id=c.id
 AND n.status='completed' ORDER BY n.listing_id LIMIT 1),'{}'::jsonb))
FROM catalog.canonical_product c;
