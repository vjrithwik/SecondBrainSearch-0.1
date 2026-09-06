-- Migration: 007_seed_reference_data.sql
-- Populates reference data tables required by business rules.

INSERT INTO supported_formats (code, label, description, active) VALUES
('PDF', 'PDF document', 'Portable Document Format', TRUE),
('DOC', 'Word 97-2003', 'Legacy Microsoft Word document', TRUE),
('DOCX', 'Word document', 'Modern Microsoft Word document', TRUE),
('TXT', 'Plain text', 'Unformatted text file', TRUE),
('MD', 'Markdown', 'Markdown text file', TRUE),
('XLS', 'Excel 97-2003', 'Legacy Microsoft Excel workbook', TRUE),
('XLSX', 'Excel workbook', 'Modern Microsoft Excel workbook', TRUE),
('CSV', 'CSV file', 'Comma-separated values', TRUE),
('PPT', 'PowerPoint 97-2003', 'Legacy Microsoft PowerPoint presentation', TRUE),
('PPTX', 'PowerPoint presentation', 'Modern Microsoft PowerPoint presentation', TRUE),
('ODF', 'ODF document', 'OpenDocument format (text, spreadsheet or presentation)', TRUE)
ON CONFLICT (code) DO NOTHING;

INSERT INTO index_statuses (code, label, description, active) VALUES
('EMPTY', 'Empty', 'Index exists but contains no documents', TRUE),
('ACTIVE', 'Active', 'Index contains at least one indexed document and can be searched', TRUE)
ON CONFLICT (code) DO NOTHING;

INSERT INTO document_statuses (code, label, description, active) VALUES
('REGISTERED', 'Registered', 'Document metadata is known but the document has not yet been indexed', TRUE),
('INDEXED', 'Indexed', 'Document has been successfully chunked and embedded', TRUE),
('STALE', 'Stale', 'Document is known to have changed on disk and must be reprocessed', TRUE),
('REMOVED', 'Removed', 'Original file no longer exists; chunks must be deleted', TRUE)
ON CONFLICT (code) DO NOTHING;

INSERT INTO indexing_run_statuses (code, label, description, active) VALUES
('PLANNED', 'Planned', 'Run is queued but has not started', TRUE),
('RUNNING', 'Running', 'Run is currently processing files', TRUE),
('COMPLETED', 'Completed', 'Run finished normally', TRUE),
('FAILED', 'Failed', 'Run stopped because of an unrecoverable error', TRUE),
('CANCELLED', 'Cancelled', 'Run was cancelled by the end user', TRUE)
ON CONFLICT (code) DO NOTHING;

INSERT INTO query_types (code, label, description, active) VALUES
('NATURAL_LANGUAGE', 'Natural-language query', 'Query expresses a concept or topic', TRUE),
('FILENAME_KEYWORD', 'Filename keyword', 'Query targets the file name', TRUE)
ON CONFLICT (code) DO NOTHING;

INSERT INTO protected_system_paths (code, label, description, active) VALUES
('WIN_WINDOWS', 'Windows directory', 'C:\\Windows and C:\\Windows\\System32', TRUE),
('WIN_PROGRAM_FILES', 'Program Files', 'C:\\Program Files and C:\\Program Files (x86)', TRUE),
('MAC_SYSTEM', 'macOS System', '/System and /usr', TRUE),
('LIN_SYSTEM', 'Linux system', '/bin, /boot, /etc, /lib, /proc, /sys, /usr', TRUE)
ON CONFLICT (code) DO NOTHING;

-- DOWN
-- DELETE FROM supported_formats WHERE code IN ('PDF','DOC','DOCX','TXT','MD','XLS','XLSX','CSV','PPT','PPTX','ODF');
-- DELETE FROM index_statuses WHERE code IN ('EMPTY','ACTIVE');
-- DELETE FROM document_statuses WHERE code IN ('REGISTERED','INDEXED','STALE','REMOVED');
-- DELETE FROM indexing_run_statuses WHERE code IN ('PLANNED','RUNNING','COMPLETED','FAILED','CANCELLED');
-- DELETE FROM query_types WHERE code IN ('NATURAL_LANGUAGE','FILENAME_KEYWORD');
-- DELETE FROM protected_system_paths WHERE code IN ('WIN_WINDOWS','WIN_PROGRAM_FILES','MAC_SYSTEM','LIN_SYSTEM');
