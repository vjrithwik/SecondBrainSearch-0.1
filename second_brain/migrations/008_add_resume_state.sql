-- Migration: 008_add_resume_state.sql
-- Adds resume tracking to indexing runs so interrupted runs (sleep, shutdown,
-- crash) can be continued from the last successfully processed file.

ALTER TABLE indexing_runs
ADD COLUMN IF NOT EXISTS last_processed_path VARCHAR NULL;

ALTER TABLE indexing_runs
ADD COLUMN IF NOT EXISTS checkpointed_at TIMESTAMP NULL;

-- DOWN
-- ALTER TABLE indexing_runs DROP COLUMN IF EXISTS last_processed_path;
-- ALTER TABLE indexing_runs DROP COLUMN IF EXISTS checkpointed_at;
