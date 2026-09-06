-- Migration: 002_create_indexes_table.sql
-- Implements: [TBL-001], [ENT-001]
-- BA References: [DOM-001], [REF-002]

CREATE TABLE IF NOT EXISTS indexes (
    index_id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    storage_path VARCHAR NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'EMPTY',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_sync_at TIMESTAMP NULL,
    CONSTRAINT chk_indexes_last_sync CHECK (last_sync_at IS NULL OR last_sync_at >= created_at)
);

CREATE INDEX IF NOT EXISTS idx_indexes_status ON indexes(status);

-- DOWN
-- DROP TABLE IF EXISTS indexes;
