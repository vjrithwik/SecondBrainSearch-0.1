-- Migration: 001_create_bootstrap_reference.sql
-- Creates schema_version and all reference tables first.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS supported_formats (
    code VARCHAR(20) PRIMARY KEY,
    label VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS index_statuses (
    code VARCHAR(20) PRIMARY KEY,
    label VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS document_statuses (
    code VARCHAR(20) PRIMARY KEY,
    label VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS indexing_run_statuses (
    code VARCHAR(20) PRIMARY KEY,
    label VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS query_types (
    code VARCHAR(30) PRIMARY KEY,
    label VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS protected_system_paths (
    code VARCHAR(30) PRIMARY KEY,
    label VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

-- DOWN
-- DROP TABLE IF EXISTS schema_version;
-- DROP TABLE IF EXISTS supported_formats;
-- DROP TABLE IF EXISTS index_statuses;
-- DROP TABLE IF EXISTS document_statuses;
-- DROP TABLE IF EXISTS indexing_run_statuses;
-- DROP TABLE IF EXISTS query_types;
-- DROP TABLE IF EXISTS protected_system_paths;
