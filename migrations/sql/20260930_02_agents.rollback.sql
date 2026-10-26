DROP INDEX IF EXISTS "ai"."interaction_agent_inserted_at_idx";
ALTER TABLE "ai"."interaction" DROP COLUMN IF EXISTS agent_id;
DROP TABLE IF EXISTS "ai"."agent";
