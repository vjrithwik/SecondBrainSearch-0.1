-- Migration: 003_create_directories_table.sql
-- Implements: [TBL-002], [ENT-002]
-- BA References: [DOM-001]

CREATE TABLE IF NOT EXISTS directories (
    directory_id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    directory_path VARCHAR NOT NULL UNIQUE,
    selected_at TIMESTAMP NOT NULL DEFAULT NOW(),
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_directories_path_length CHECK (LENGTH(directory_path) > 0)
);

CREATE INDEX IF NOT EXISTS idx_directories_path ON directories(directory_path);
CREATE INDEX IF NOT EXISTS idx_directories_default ON directories(is_default);

-- DOWN
-- DROP TABLE IF EXISTS directories;
