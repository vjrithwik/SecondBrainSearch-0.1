-- Migration: 010_add_directory_display_name.sql
-- Add a user-defined short display name for each indexed directory.

ALTER TABLE directories ADD COLUMN IF NOT EXISTS display_name VARCHAR(10);

-- DOWN
-- ALTER TABLE directories DROP COLUMN IF EXISTS display_name;
