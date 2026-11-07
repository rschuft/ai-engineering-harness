-- Effects store migration 0001: privileged effect receipts, the hash-chained journal,
-- reconciliation records and restore epochs (plan leaf F-05.2, decision 0004).
--
-- Applied by effects_store.py inside one BEGIN IMMEDIATE transaction, together with
-- its schema_migration row and PRAGMA user_version. Never edit an applied migration:
-- the store refuses to open a database whose recorded checksum differs from the
-- file. This is the effects store's own migration line; it shares nothing with the
-- integration store's migrations.
--
-- Every table is canonical: there are no projections in this store. Nothing is ever
-- deleted; receipt identity never changes; the journal, reconciliation records and
-- restore epochs are append-only.

-- 1095059032 = 0x41454658 ('AEFX'): identifies the file as an effects store.
PRAGMA application_id = 1095059032;

CREATE TABLE schema_migration (
    version    INTEGER PRIMARY KEY CHECK (version >= 1),
    name       TEXT NOT NULL UNIQUE,
    sha256     TEXT NOT NULL CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    applied_at TEXT NOT NULL
) STRICT;

-- The closed set of receipt states.
CREATE TABLE effect_state (
    state       TEXT PRIMARY KEY,
    terminal    INTEGER NOT NULL CHECK (terminal IN (0, 1)),
    description TEXT NOT NULL
) STRICT;

INSERT INTO effect_state (state, terminal, description) VALUES
    ('reserved',  0, 'one-time effect key, its inputs and the Owner authority committed; no effect started'),
    ('applying',  0, 'the executor has started the effect; its outcome is not yet observed'),
    ('completed', 1, 'the effect was observed in the target'),
    ('failed',    1, 'the effect was refused before it started, or observed not to have happened'),
    ('unknown',   0, 'outcome uncertain: never reissued; resolved only by a recorded reconciliation or Owner attestation'),
    ('observed',  1, 'created by reconciliation: the target shows the effect, which this store had no receipt for');

-- Who may cause a state change.
CREATE TABLE effect_origin (
    origin      TEXT PRIMARY KEY,
    description TEXT NOT NULL
) STRICT;

INSERT INTO effect_origin (origin, description) VALUES
    ('executor',          'the protected executor, in the normal course of an effect'),
    ('reconciliation',    'reconciliation against the observed target by the store''s owner identity'),
    ('owner_attestation', 'a recorded Owner attestation resolving a permanently unknown outcome');

-- Allowed state changes, per origin. Every receipt_transition event names one of
-- these triples (foreign key) and a trigger applies the pair rule to effect_receipt.
CREATE TABLE effect_transition (
    from_state TEXT NOT NULL REFERENCES effect_state (state),
    to_state   TEXT NOT NULL REFERENCES effect_state (state),
    origin     TEXT NOT NULL REFERENCES effect_origin (origin),
    PRIMARY KEY (from_state, to_state, origin),
    CHECK (from_state <> to_state)
) STRICT;

INSERT INTO effect_transition (from_state, to_state, origin) VALUES
    ('reserved',  'applying',  'executor'),
    ('reserved',  'failed',    'executor'),
    ('applying',  'completed', 'executor'),
    ('applying',  'failed',    'executor'),
    ('applying',  'unknown',   'executor'),
    ('reserved',  'completed', 'reconciliation'),
    ('reserved',  'unknown',   'reconciliation'),
    ('applying',  'completed', 'reconciliation'),
    ('applying',  'failed',    'reconciliation'),
    ('applying',  'unknown',   'reconciliation'),
    ('unknown',   'completed', 'reconciliation'),
    ('unknown',   'failed',    'reconciliation'),
    ('unknown',   'completed', 'owner_attestation'),
    ('unknown',   'failed',    'owner_attestation');

-- One receipt per one-time effect key. The key is derived from key_inputs_json
-- (fx1- + sha256 of its canonical JSON); the code re-derives and checks it.
CREATE TABLE effect_receipt (
    effect_key                TEXT PRIMARY KEY
                              CHECK (length(effect_key) = 68 AND substr(effect_key, 1, 4) = 'fx1-'
                                     AND substr(effect_key, 5) NOT GLOB '*[^0-9a-f]*'),
    key_inputs_json           TEXT NOT NULL CHECK (json_valid(key_inputs_json)),
    operation_kind            TEXT NOT NULL CHECK (length(operation_kind) BETWEEN 1 AND 128),
    target_identity           TEXT NOT NULL CHECK (length(target_identity) BETWEEN 1 AND 1024),
    authority_protected_ref   TEXT NOT NULL CHECK (length(authority_protected_ref) BETWEEN 1 AND 512),
    authority_revision        TEXT NOT NULL CHECK (length(authority_revision) BETWEEN 1 AND 256),
    authority_manifest_digest TEXT NOT NULL CHECK (length(authority_manifest_digest) BETWEEN 1 AND 256),
    authority_merged_by       TEXT NOT NULL CHECK (length(authority_merged_by) BETWEEN 1 AND 256),
    authority_policy_revision TEXT NOT NULL CHECK (length(authority_policy_revision) BETWEEN 1 AND 256),
    origin                    TEXT NOT NULL CHECK (origin IN ('executor', 'reconciliation'))
                              REFERENCES effect_origin (origin),
    actor                     TEXT NOT NULL CHECK (length(actor) BETWEEN 1 AND 256),
    state                     TEXT NOT NULL REFERENCES effect_state (state),
    reconciliation_status     TEXT NOT NULL CHECK (reconciliation_status IN ('none', 'required', 'reconciled')),
    result_json               TEXT CHECK (result_json IS NULL OR json_valid(result_json)),
    state_seq                 INTEGER NOT NULL CHECK (state_seq >= 0),
    created_seq               INTEGER NOT NULL UNIQUE,
    created_at                TEXT NOT NULL,
    updated_at                TEXT NOT NULL,
    CHECK ((state = 'unknown') = (reconciliation_status = 'required')),
    CHECK (state NOT IN ('completed', 'failed', 'observed') OR result_json IS NOT NULL),
    CHECK (state <> 'observed' OR origin = 'reconciliation')
) STRICT;

CREATE INDEX effect_receipt_state_idx ON effect_receipt (state);

-- The journal: every receipt creation, receipt transition, reconciliation verdict
-- and restore-epoch event, in order. hash = sha256(prev_hash || LF || content_json),
-- computed and verified by effects_store.py; the trigger below enforces contiguous
-- sequence numbers and the link to the previous hash.
CREATE TABLE effect_event (
    seq          INTEGER PRIMARY KEY CHECK (seq >= 1),
    kind         TEXT NOT NULL CHECK (kind IN ('receipt_created', 'receipt_transition', 'reconciliation',
                                               'epoch_opened', 'epoch_closed')),
    effect_key   TEXT,
    epoch_id     INTEGER,
    from_state   TEXT,
    to_state     TEXT,
    origin       TEXT,
    actor        TEXT NOT NULL CHECK (length(actor) BETWEEN 1 AND 256),
    content_json TEXT NOT NULL CHECK (json_valid(content_json)),
    prev_hash    TEXT NOT NULL CHECK (length(prev_hash) = 64 AND prev_hash NOT GLOB '*[^0-9a-f]*'),
    hash         TEXT NOT NULL UNIQUE CHECK (length(hash) = 64 AND hash NOT GLOB '*[^0-9a-f]*'),
    recorded_at  TEXT NOT NULL,
    FOREIGN KEY (from_state, to_state, origin) REFERENCES effect_transition (from_state, to_state, origin),
    CHECK (kind <> 'receipt_transition'
           OR (effect_key IS NOT NULL AND from_state IS NOT NULL AND to_state IS NOT NULL AND origin IS NOT NULL)),
    CHECK (kind <> 'receipt_created'
           OR (effect_key IS NOT NULL AND from_state IS NULL
               AND ((to_state = 'reserved' AND origin = 'executor')
                    OR (to_state = 'observed' AND origin = 'reconciliation')
                    OR (to_state = 'unknown' AND origin = 'reconciliation')))),
    CHECK (kind IN ('receipt_created', 'receipt_transition') OR (from_state IS NULL AND to_state IS NULL)),
    CHECK (kind NOT IN ('epoch_opened', 'epoch_closed') OR epoch_id IS NOT NULL)
) STRICT;

CREATE TRIGGER effect_event_chain BEFORE INSERT ON effect_event
WHEN NEW.seq <> (SELECT coalesce(max(seq), 0) + 1 FROM effect_event)
  OR NEW.prev_hash <> coalesce((SELECT hash FROM effect_event WHERE seq = NEW.seq - 1),
                               '0000000000000000000000000000000000000000000000000000000000000000')
BEGIN
    SELECT RAISE(ABORT, 'effect journal events must extend the chain');
END;

-- Restore epochs: one row per restore, appended to the restored copy before it
-- replaced the live store. While an epoch has no closure, new reservations and the
-- start of any effect are refused (triggers below).
CREATE TABLE restore_epoch (
    epoch_id                     INTEGER PRIMARY KEY CHECK (epoch_id >= 1),
    opened_seq                   INTEGER NOT NULL UNIQUE,
    backup_manifest_sha256       TEXT NOT NULL
                                 CHECK (length(backup_manifest_sha256) = 64
                                        AND backup_manifest_sha256 NOT GLOB '*[^0-9a-f]*'),
    backup_file                  TEXT NOT NULL CHECK (length(backup_file) BETWEEN 1 AND 256),
    backup_high_water            INTEGER NOT NULL CHECK (backup_high_water >= 0),
    backup_chain_head            TEXT NOT NULL CHECK (length(backup_chain_head) = 64),
    previous_live_high_water     INTEGER CHECK (previous_live_high_water IS NULL OR previous_live_high_water >= 0),
    previous_live_chain_head     TEXT CHECK (previous_live_chain_head IS NULL OR length(previous_live_chain_head) = 64),
    superseded_copy              TEXT,
    rollback_accepted            INTEGER NOT NULL CHECK (rollback_accepted IN (0, 1)),
    actor                        TEXT NOT NULL CHECK (length(actor) BETWEEN 1 AND 256),
    opened_at                    TEXT NOT NULL,
    reconciliation_status        TEXT NOT NULL DEFAULT 'required' CHECK (reconciliation_status = 'required'),
    CHECK ((previous_live_high_water IS NULL) = (previous_live_chain_head IS NULL))
) STRICT;

CREATE TABLE restore_epoch_closure (
    epoch_id     INTEGER PRIMARY KEY REFERENCES restore_epoch (epoch_id),
    closed_seq   INTEGER NOT NULL UNIQUE,
    actor        TEXT NOT NULL CHECK (length(actor) BETWEEN 1 AND 256),
    closed_at    TEXT NOT NULL,
    summary_json TEXT NOT NULL CHECK (json_valid(summary_json))
) STRICT;

-- Each reconciliation verdict: the probe of the observed target (or the Owner's
-- attestation) for one effect key, and what the store did about it.
CREATE TABLE reconciliation_record (
    record_id   INTEGER PRIMARY KEY,
    seq         INTEGER NOT NULL UNIQUE,
    epoch_id    INTEGER REFERENCES restore_epoch (epoch_id),
    effect_key  TEXT NOT NULL CHECK (length(effect_key) = 68 AND substr(effect_key, 1, 4) = 'fx1-'),
    verdict     TEXT NOT NULL CHECK (verdict IN ('performed', 'not_performed', 'indeterminate',
                                                 'attested_performed', 'attested_not_performed')),
    action      TEXT NOT NULL CHECK (action IN ('observed_receipt_created', 'unknown_receipt_created',
                                                'transitioned', 'cleared', 'left_unknown')),
    probe_json  TEXT NOT NULL CHECK (json_valid(probe_json)),
    actor       TEXT NOT NULL CHECK (length(actor) BETWEEN 1 AND 256),
    recorded_at TEXT NOT NULL
) STRICT;

CREATE INDEX reconciliation_record_key_idx ON reconciliation_record (effect_key, epoch_id);

-- Receipts are never deleted; identity never changes; a result is written once.
CREATE TRIGGER effect_receipt_no_delete BEFORE DELETE ON effect_receipt
BEGIN SELECT RAISE(ABORT, 'effect receipts are never deleted'); END;

CREATE TRIGGER effect_receipt_identity_immutable
BEFORE UPDATE OF effect_key, key_inputs_json, operation_kind, target_identity, authority_protected_ref,
                 authority_revision, authority_manifest_digest, authority_merged_by,
                 authority_policy_revision, origin, actor, created_seq, created_at ON effect_receipt
BEGIN SELECT RAISE(ABORT, 'effect receipt identity is immutable'); END;

CREATE TRIGGER effect_receipt_result_once BEFORE UPDATE OF result_json ON effect_receipt
WHEN OLD.result_json IS NOT NULL AND NEW.result_json IS NOT OLD.result_json
BEGIN SELECT RAISE(ABORT, 'an effect result is recorded once'); END;

CREATE TRIGGER effect_receipt_transition_allowed BEFORE UPDATE OF state ON effect_receipt
WHEN NEW.state IS NOT OLD.state
 AND NOT EXISTS (SELECT 1 FROM effect_transition WHERE from_state = OLD.state AND to_state = NEW.state)
BEGIN SELECT RAISE(ABORT, 'illegal effect receipt state transition'); END;

-- The reservation gate: while any restore epoch is open, no new executor reservation
-- and no effect may start.
CREATE TRIGGER effect_reservation_gate BEFORE INSERT ON effect_receipt
WHEN NEW.origin = 'executor'
 AND EXISTS (SELECT 1 FROM restore_epoch e
             WHERE NOT EXISTS (SELECT 1 FROM restore_epoch_closure c WHERE c.epoch_id = e.epoch_id))
BEGIN
    SELECT RAISE(ABORT, 'a restore epoch is open: new effect reservations are refused until it is reconciled');
END;

CREATE TRIGGER effect_apply_gate BEFORE UPDATE OF state ON effect_receipt
WHEN NEW.state = 'applying'
 AND EXISTS (SELECT 1 FROM restore_epoch e
             WHERE NOT EXISTS (SELECT 1 FROM restore_epoch_closure c WHERE c.epoch_id = e.epoch_id))
BEGIN
    SELECT RAISE(ABORT, 'a restore epoch is open: no effect may start until it is reconciled');
END;

CREATE TRIGGER effect_event_no_update BEFORE UPDATE ON effect_event
BEGIN SELECT RAISE(ABORT, 'the effect journal is append-only'); END;
CREATE TRIGGER effect_event_no_delete BEFORE DELETE ON effect_event
BEGIN SELECT RAISE(ABORT, 'the effect journal is append-only'); END;
CREATE TRIGGER restore_epoch_no_update BEFORE UPDATE ON restore_epoch
BEGIN SELECT RAISE(ABORT, 'restore epochs are append-only'); END;
CREATE TRIGGER restore_epoch_no_delete BEFORE DELETE ON restore_epoch
BEGIN SELECT RAISE(ABORT, 'restore epochs are append-only'); END;
CREATE TRIGGER restore_epoch_closure_no_update BEFORE UPDATE ON restore_epoch_closure
BEGIN SELECT RAISE(ABORT, 'restore epoch closures are append-only'); END;
CREATE TRIGGER restore_epoch_closure_no_delete BEFORE DELETE ON restore_epoch_closure
BEGIN SELECT RAISE(ABORT, 'restore epoch closures are append-only'); END;
CREATE TRIGGER reconciliation_record_no_update BEFORE UPDATE ON reconciliation_record
BEGIN SELECT RAISE(ABORT, 'reconciliation records are append-only'); END;
CREATE TRIGGER reconciliation_record_no_delete BEFORE DELETE ON reconciliation_record
BEGIN SELECT RAISE(ABORT, 'reconciliation records are append-only'); END;

-- The vocabularies change only through a migration that drops and recreates these guards.
CREATE TRIGGER effect_state_frozen_insert BEFORE INSERT ON effect_state
BEGIN SELECT RAISE(ABORT, 'effect_state changes only by migration'); END;
CREATE TRIGGER effect_state_frozen_update BEFORE UPDATE ON effect_state
BEGIN SELECT RAISE(ABORT, 'effect_state changes only by migration'); END;
CREATE TRIGGER effect_state_frozen_delete BEFORE DELETE ON effect_state
BEGIN SELECT RAISE(ABORT, 'effect_state changes only by migration'); END;
CREATE TRIGGER effect_origin_frozen_insert BEFORE INSERT ON effect_origin
BEGIN SELECT RAISE(ABORT, 'effect_origin changes only by migration'); END;
CREATE TRIGGER effect_origin_frozen_update BEFORE UPDATE ON effect_origin
BEGIN SELECT RAISE(ABORT, 'effect_origin changes only by migration'); END;
CREATE TRIGGER effect_origin_frozen_delete BEFORE DELETE ON effect_origin
BEGIN SELECT RAISE(ABORT, 'effect_origin changes only by migration'); END;
CREATE TRIGGER effect_transition_frozen_insert BEFORE INSERT ON effect_transition
BEGIN SELECT RAISE(ABORT, 'effect_transition changes only by migration'); END;
CREATE TRIGGER effect_transition_frozen_update BEFORE UPDATE ON effect_transition
BEGIN SELECT RAISE(ABORT, 'effect_transition changes only by migration'); END;
CREATE TRIGGER effect_transition_frozen_delete BEFORE DELETE ON effect_transition
BEGIN SELECT RAISE(ABORT, 'effect_transition changes only by migration'); END;
