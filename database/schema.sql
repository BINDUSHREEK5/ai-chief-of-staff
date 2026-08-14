-- Reference schema for the Chief of Staff agent's memory store.
--
-- This mirrors the SQLAlchemy models in app/memory.py exactly. The app
-- creates these tables automatically at startup (Base.metadata.create_all),
-- so you never need to run this file by hand — it's here so the schema
-- can be reviewed, diffed, or applied manually (e.g. `sqlite3 agent.db <
-- database/schema.sql`) without reading ORM code.
--
-- Migrating to Postgres: see docs/DEPLOYMENT.md for the two dialect
-- differences (AUTOINCREMENT -> not needed with SERIAL/IDENTITY, and
-- TIMESTAMP handling), which SQLAlchemy's async engine already abstracts
-- over for you at runtime.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS contacts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    email             TEXT UNIQUE NOT NULL,
    name              TEXT,
    relationship_label TEXT,
    importance_score  REAL NOT NULL DEFAULT 0.5,
    notes             TEXT,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS preferences (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    channel                  TEXT NOT NULL,             -- 'email' | 'telegram'
    external_conversation_id TEXT NOT NULL,              -- Caspian's conversation_id
    contact_id               INTEGER REFERENCES contacts(id),
    subject                  TEXT,
    status                   TEXT NOT NULL DEFAULT 'open',
    created_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (channel, external_conversation_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    direction       TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    channel         TEXT NOT NULL,
    sender          TEXT NOT NULL,
    text            TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS approved_response_patterns (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_description  TEXT NOT NULL,
    example_input        TEXT NOT NULL,
    response_template    TEXT NOT NULL,
    times_approved       INTEGER NOT NULL DEFAULT 1,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT 1,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Explainability log: every automated decision, with the reasoning that
-- produced it. This is what the daily summary and any "why did you do
-- that?" debugging pulls from.
CREATE TABLE IF NOT EXISTS decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER REFERENCES conversations(id),
    decision        TEXT NOT NULL,   -- auto_reply | draft_for_approval | notify_only | ignore
    urgency_score   REAL,
    reasoning       TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS approvals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_code   TEXT UNIQUE NOT NULL,
    conversation_id INTEGER REFERENCES conversations(id),
    draft_text      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | edited | rejected
    final_text      TEXT,
    requested_via   TEXT NOT NULL DEFAULT 'telegram',
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at     TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_decisions_conversation ON decisions(conversation_id);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);