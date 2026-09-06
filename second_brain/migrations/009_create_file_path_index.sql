-- Migration: 009_create_file_path_index.sql
-- Add an index on documents.file_path to support directory-scoped search.

CREATE INDEX IF NOT EXISTS idx_documents_file_path ON documents(file_path);

-- DOWN
-- DROP INDEX IF EXISTS idx_documents_file_path;
