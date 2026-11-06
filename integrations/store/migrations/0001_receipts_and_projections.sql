-- Migration 0001: operational coordination receipts and projection bookkeeping.
--
-- Applied by integration_store.py inside one BEGIN IMMEDIATE transaction, together
-- with its schema_migration row and PRAGMA user_version. Never edit an applied
-- migration: the store refuses to open a database whose recorded checksum differs
-- from the file. Change the schema with a new, higher-numbered migration.
--
-- Canonical (receipt) tables: schema_migration, attempt_state, attempt_transition,
-- reconciliation_status, attempt, attempt_event. They are never dropped, rebuilt or
-- deleted from. Rebuildable projection tables all start with proj_ and carry no
-- authority (blueprint #infrastructure-state).

-- Applied migrations, one row per file, with the sha256 of its LF-normalised text.
CREATE TABLE schema_migration (
    version    INTEGER PRIMARY KEY CHECK (version >= 1),
    name       TEXT NOT NULL UNIQUE,
    sha256     TEXT NOT NULL CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    applied_at TEXT NOT NULL
) STRICT;

-- The closed set of attempt states.
CREATE TABLE attempt_state (
    state       TEXT PRIMARY KEY,
    terminal    INTEGER NOT NULL CHECK (terminal IN (0, 1)),
    description TEXT NOT NULL
) STRICT;

INSERT INTO attempt_state (state, terminal, description) VALUES
    ('reserved',   0, 'intent, attempt key and conversation ID committed; no external call made yet'),
    ('dispatched', 0, 'external create about to be or already sent; outcome not yet confirmed'),
    ('confirmed',  1, 'external create observed to have succeeded'),
    ('failed',     1, 'refused before any external call, or the external create observed to have failed'),
    ('unknown',    0, 'outcome uncertain; must be reconciled against the external system before any retry');

-- The allowed state transitions. Every attempt_event row with a from_state must name
-- one of these pairs (foreign key), and a trigger applies the same rule to attempt.
CREATE TABLE attempt_transition (
    from_state TEXT NOT NULL REFERENCES attempt_state (state),
    to_state   TEXT NOT NULL REFERENCES attempt_state (state),
    PRIMARY KEY (from_state, to_state),
    CHECK (from_state <> to_state)
) STRICT;

INSERT INTO attempt_transition (from_state, to_state) VALUES
    ('reserved',   'dispatched'),
    ('reserved',   'failed'),
    ('dispatched', 'confirmed'),
    ('dispatched', 'failed'),
    ('dispatched', 'unknown'),
    ('unknown',    'confirmed'),
    ('unknown',    'failed');

CREATE TABLE reconciliation_status (
    status      TEXT PRIMARY KEY,
    description TEXT NOT NULL
) STRICT;

INSERT INTO reconciliation_status (status, description) VALUES
    ('none',       'no reconciliation has been needed'),
    ('required',   'the attempt is unknown and must be reconciled before any retry'),
    ('reconciled', 'an unknown outcome was resolved to confirmed or failed');

-- One durable reservation per attempt key. Identity columns are immutable (trigger
-- below); state and reconciliation_status change only through recorded transitions.
CREATE TABLE attempt (
    operation_key         TEXT PRIMARY KEY
                          CHECK (length(operation_key) BETWEEN 1 AND 512),
    intent_digest         TEXT NOT NULL
                          CHECK (length(intent_digest) = 64 AND intent_digest NOT GLOB '*[^0-9a-f]*'),
    intent_json           TEXT NOT NULL CHECK (json_valid(intent_json)),
    conversation_id       TEXT NOT NULL UNIQUE
                          CHECK (length(conversation_id) = 36 AND conversation_id NOT GLOB '*[^0-9a-f-]*'),
    state                 TEXT NOT NULL DEFAULT 'reserved'
                          CHECK (state IN ('reserved', 'dispatched', 'confirmed', 'failed', 'unknown'))
                          REFERENCES attempt_state (state),
    reconciliation_status TEXT NOT NULL DEFAULT 'none'
                          CHECK (reconciliation_status IN ('none', 'required', 'reconciled'))
                          REFERENCES reconciliation_status (status),
    state_seq             INTEGER NOT NULL DEFAULT 0 CHECK (state_seq >= 0),
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    -- 'required' exactly while the outcome is unknown; 'reconciled' only on a
    -- terminal state reached from unknown.
    CHECK ((state = 'unknown') = (reconciliation_status = 'required')),
    CHECK (reconciliation_status <> 'reconciled' OR state IN ('confirmed', 'failed'))
) STRICT;

-- Append-only history: the reservation (seq 0, no from_state) and every transition.
CREATE TABLE attempt_event (
    event_id              INTEGER PRIMARY KEY,
    operation_key         TEXT NOT NULL REFERENCES attempt (operation_key),
    seq                   INTEGER NOT NULL CHECK (seq >= 0),
    from_state            TEXT,
    to_state              TEXT NOT NULL REFERENCES attempt_state (state),
    reconciliation_status TEXT NOT NULL REFERENCES reconciliation_status (status),
    actor                 TEXT NOT NULL CHECK (length(actor) BETWEEN 1 AND 256),
    reason                TEXT,
    detail_json           TEXT CHECK (detail_json IS NULL OR json_valid(detail_json)),
    recorded_at           TEXT NOT NULL,
    UNIQUE (operation_key, seq),
    FOREIGN KEY (from_state, to_state) REFERENCES attempt_transition (from_state, to_state),
    CHECK ((seq = 0) = (from_state IS NULL)),
    CHECK (from_state IS NOT NULL OR to_state = 'reserved')
) STRICT;

CREATE INDEX attempt_state_idx ON attempt (state, reconciliation_status);

-- Receipts are never deleted and history is never rewritten.
CREATE TRIGGER attempt_no_delete BEFORE DELETE ON attempt
BEGIN
    SELECT RAISE(ABORT, 'attempt receipts are never deleted');
END;

CREATE TRIGGER attempt_identity_immutable
BEFORE UPDATE OF operation_key, intent_digest, intent_json, conversation_id, created_at ON attempt
BEGIN
    SELECT RAISE(ABORT, 'attempt identity is immutable');
END;

CREATE TRIGGER attempt_state_transition_allowed BEFORE UPDATE OF state ON attempt
WHEN NOT EXISTS (SELECT 1 FROM attempt_transition
                 WHERE from_state = OLD.state AND to_state = NEW.state)
BEGIN
    SELECT RAISE(ABORT, 'illegal attempt state transition');
END;

CREATE TRIGGER attempt_event_no_update BEFORE UPDATE ON attempt_event
BEGIN
    SELECT RAISE(ABORT, 'attempt events are append-only');
END;

CREATE TRIGGER attempt_event_no_delete BEFORE DELETE ON attempt_event
BEGIN
    SELECT RAISE(ABORT, 'attempt events are append-only');
END;

-- The state and transition vocabularies change only through a migration that drops
-- and recreates these guards.
CREATE TRIGGER attempt_state_frozen_insert BEFORE INSERT ON attempt_state
BEGIN SELECT RAISE(ABORT, 'attempt_state changes only by migration'); END;
CREATE TRIGGER attempt_state_frozen_update BEFORE UPDATE ON attempt_state
BEGIN SELECT RAISE(ABORT, 'attempt_state changes only by migration'); END;
CREATE TRIGGER attempt_state_frozen_delete BEFORE DELETE ON attempt_state
BEGIN SELECT RAISE(ABORT, 'attempt_state changes only by migration'); END;
CREATE TRIGGER attempt_transition_frozen_insert BEFORE INSERT ON attempt_transition
BEGIN SELECT RAISE(ABORT, 'attempt_transition changes only by migration'); END;
CREATE TRIGGER attempt_transition_frozen_update BEFORE UPDATE ON attempt_transition
BEGIN SELECT RAISE(ABORT, 'attempt_transition changes only by migration'); END;
CREATE TRIGGER attempt_transition_frozen_delete BEFORE DELETE ON attempt_transition
BEGIN SELECT RAISE(ABORT, 'attempt_transition changes only by migration'); END;
CREATE TRIGGER reconciliation_status_frozen_insert BEFORE INSERT ON reconciliation_status
BEGIN SELECT RAISE(ABORT, 'reconciliation_status changes only by migration'); END;
CREATE TRIGGER reconciliation_status_frozen_update BEFORE UPDATE ON reconciliation_status
BEGIN SELECT RAISE(ABORT, 'reconciliation_status changes only by migration'); END;
CREATE TRIGGER reconciliation_status_frozen_delete BEFORE DELETE ON reconciliation_status
BEGIN SELECT RAISE(ABORT, 'reconciliation_status changes only by migration'); END;

-- Projection bookkeeping: one row per projection with the source cursor and the
-- indexing coverage of its last rebuild. Rebuildable like the projections themselves.
CREATE TABLE proj_cursor (
    projection    TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    cursor        TEXT,
    coverage_json TEXT NOT NULL CHECK (json_valid(coverage_json)),
    rebuilt_at    TEXT NOT NULL
) STRICT;
