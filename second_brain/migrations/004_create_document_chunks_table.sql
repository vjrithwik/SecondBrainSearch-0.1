
-- Migration: 004_create_documents_table.sql
-- Implements: [TBL-003], [ENT-003]
-- BA References: [DOM-001], [REF-001], [REF-003]

CREATE TABLE IF NOT EXISTS documents (
    file_id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    index_id VARCHAR NOT NULL,
    directory_id VARCHAR NOT NULL,
    file_path VARCHAR NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_format VARCHAR(20) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    last_modified TIMESTAMP NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'REGISTERED',
    indexed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_documents_file_size CHECK (file_size_bytes > 0),
    CONSTRAINT chk_documents_last_modified CHECK (last_modified <= NOW()),
    CONSTRAINT chk_documents_indexed_at CHECK (indexed_at IS NULL OR indexed_at >= created_at),
    UNIQUE (index_id, file_path)
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_last_modified ON documents(last_modified);
CREATE INDEX IF NOT EXISTS idx_documents_directory ON documents(directory_id);

-- DOWN
-- DROP TABLE IF EXISTS documents;
