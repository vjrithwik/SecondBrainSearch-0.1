-- Migration: 005_create_document_chunks_table.sql
-- Implements: [TBL-004], [ENT-004]
-- BA References: [DOM-001]

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id VARCHAR NOT NULL,
    chunk_index INTEGER NOT NULL,
    is_filename_entry BOOLEAN NOT NULL DEFAULT FALSE,
    chunk_text VARCHAR NOT NULL,
    embedding FLOAT[384] NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_chunks_chunk_index CHECK (chunk_index >= 0),
    CONSTRAINT chk_chunks_text_not_empty CHECK (LENGTH(TRIM(chunk_text)) > 0),
    UNIQUE (file_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_file_index ON document_chunks(file_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_chunks_filename ON document_chunks(file_id, is_filename_entry);

-- DOWN
-- DROP TABLE IF EXISTS document_chunks;
