-- Migration: 006_create_indexing_runs_table.sql
-- Implements: [TBL-005], [ENT-005]
-- BA References: [DOM-001], [REF-004]

CREATE TABLE IF NOT EXISTS indexing_runs (
    run_id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    index_id VARCHAR NOT NULL,
    directory_id VARCHAR NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PLANNED',
    targeted_directory VARCHAR NOT NULL,
    files_processed INTEGER NOT NULL DEFAULT 0,
    files_skipped INTEGER NOT NULL DEFAULT 0,
    error_log VARCHAR NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_runs_completion_order CHECK (completed_at IS NULL OR completed_at >= started_at),
    CONSTRAINT chk_runs_files_processed CHECK (files_processed >= 0),
    CONSTRAINT chk_runs_files_skipped CHECK (files_skipped >= 0)
);

CREATE INDEX IF NOT EXISTS idx_runs_index_status ON indexing_runs(index_id, status);
CREATE INDEX IF NOT EXISTS idx_runs_directory ON indexing_runs(directory_id);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON indexing_runs(started_at);

-- DOWN
-- DROP TABLE IF EXISTS indexing_runs;
