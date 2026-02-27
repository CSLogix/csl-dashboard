-- CSL Document Tracker — Database Setup
-- Run as postgres superuser:
--   sudo -u postgres psql -f setup_db.sql

-- Create database and user
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'csl_admin') THEN
        CREATE ROLE csl_admin WITH LOGIN PASSWORD 'changeme';
    END IF;
END
$$;

SELECT 'CREATE DATABASE csl_doc_tracker OWNER csl_admin'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'csl_doc_tracker');
\gexec

\connect csl_doc_tracker;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE csl_doc_tracker TO csl_admin;
GRANT ALL ON SCHEMA public TO csl_admin;

-- ============================================================
-- Tables
-- ============================================================

CREATE TABLE IF NOT EXISTS loads (
    id              SERIAL PRIMARY KEY,
    load_number     VARCHAR(50) UNIQUE NOT NULL,   -- EFJ number
    customer_ref    VARCHAR(100),
    customer_name   VARCHAR(100),
    account         VARCHAR(50),                    -- EFJ-Operations, Boviet, Tolead
    status          VARCHAR(30) DEFAULT 'active',
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS load_references (
    id              SERIAL PRIMARY KEY,
    load_id         INTEGER NOT NULL REFERENCES loads(id) ON DELETE CASCADE,
    reference_type  VARCHAR(50) NOT NULL,           -- efj, container, po, bol, company_ref
    reference_value VARCHAR(100) NOT NULL,
    UNIQUE(reference_type, reference_value)
);

CREATE TABLE IF NOT EXISTS documents (
    id              SERIAL PRIMARY KEY,
    load_id         INTEGER NOT NULL REFERENCES loads(id) ON DELETE CASCADE,
    doc_type        VARCHAR(20) NOT NULL,           -- BOL, POD
    file_path       VARCHAR(500),
    file_name       VARCHAR(255),
    email_subject   VARCHAR(500),
    email_from      VARCHAR(255),
    email_date      TIMESTAMP,
    received_at     TIMESTAMP DEFAULT NOW(),
    source_mailbox  VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS document_checklist (
    id              SERIAL PRIMARY KEY,
    load_id         INTEGER NOT NULL REFERENCES loads(id) ON DELETE CASCADE,
    doc_type        VARCHAR(20) NOT NULL,           -- BOL, POD
    required        BOOLEAN DEFAULT TRUE,
    received        BOOLEAN DEFAULT FALSE,
    received_at     TIMESTAMP,
    alert_sent      BOOLEAN DEFAULT FALSE,
    alert_sent_at   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS email_log (
    id              SERIAL PRIMARY KEY,
    message_id      VARCHAR(255) UNIQUE,
    mailbox_origin  VARCHAR(100),
    subject         VARCHAR(500),
    sender          VARCHAR(255),
    received_date   TIMESTAMP,
    processed       BOOLEAN DEFAULT FALSE,
    processed_at    TIMESTAMP,
    matched_load_id INTEGER REFERENCES loads(id) ON DELETE SET NULL,
    attachments_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS unmatched_emails (
    id              SERIAL PRIMARY KEY,
    message_id      VARCHAR(255),
    subject         VARCHAR(500),
    sender          VARCHAR(255),
    received_date   TIMESTAMP,
    attachment_names TEXT,
    review_status   VARCHAR(20) DEFAULT 'pending',  -- pending, matched, ignored
    matched_load_id INTEGER REFERENCES loads(id) ON DELETE SET NULL,
    reviewed_at     TIMESTAMP
);

-- ============================================================
-- Indexes
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_loads_load_number ON loads(load_number);
CREATE INDEX IF NOT EXISTS idx_loads_account ON loads(account);
CREATE INDEX IF NOT EXISTS idx_loads_status ON loads(status);

CREATE INDEX IF NOT EXISTS idx_load_references_value ON load_references(reference_value);
CREATE INDEX IF NOT EXISTS idx_load_references_load_id ON load_references(load_id);

CREATE INDEX IF NOT EXISTS idx_documents_load_id ON documents(load_id);
CREATE INDEX IF NOT EXISTS idx_documents_doc_type ON documents(doc_type);

CREATE INDEX IF NOT EXISTS idx_document_checklist_load_id ON document_checklist(load_id);

CREATE INDEX IF NOT EXISTS idx_email_log_message_id ON email_log(message_id);
CREATE INDEX IF NOT EXISTS idx_email_log_matched_load ON email_log(matched_load_id);

CREATE INDEX IF NOT EXISTS idx_unmatched_review_status ON unmatched_emails(review_status);

-- Grant table ownership
ALTER TABLE loads OWNER TO csl_admin;
ALTER TABLE load_references OWNER TO csl_admin;
ALTER TABLE documents OWNER TO csl_admin;
ALTER TABLE document_checklist OWNER TO csl_admin;
ALTER TABLE email_log OWNER TO csl_admin;
ALTER TABLE unmatched_emails OWNER TO csl_admin;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO csl_admin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO csl_admin;
