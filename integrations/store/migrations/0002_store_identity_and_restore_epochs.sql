-- Migration 0002: store-kind identity and restore epochs (plan leaf F-05.2, decision 0004).
--
-- Applied by integration_store.py inside one BEGIN IMMEDIATE transaction, together
-- with its schema_migration row and PRAGMA user_version. Never edit an applied
-- migration; add a new one. Migration 0001 and its states and transitions are
-- unchanged.
--
-- application_id identifies the file as an integration store, so the effects store
-- (and any other tool using integrations/storecore) refuses to open it, and this
-- store refuses an effects store file. 1095323220 = 0x41494E54 ('AINT').
PRAGMA application_id = 1095323220;

-- One row per restore: which verified backup was restored, its canonical high-water
-- mark and history digest, the superseded live store's mark and digest (if there
-- was one), the name of the superseded copy preserved aside, whether a rollback was
-- explicitly accepted, the projections dropped, who restored it and when.
-- Append-only. While an epoch has no closure row, new attempt reservations are
-- refused (trigger below): a restore loses knowledge, never effects.
CREATE TABLE restore_epoch (
    epoch_id                     INTEGER PRIMARY KEY CHECK (epoch_id >= 1),
    backup_manifest_sha256       TEXT NOT NULL
                                 CHECK (length(backup_manifest_sha256) = 64
                                        AND backup_manifest_sha256 NOT GLOB '*[^0-9a-f]*'),
    backup_file                  TEXT NOT NULL CHECK (length(backup_file) BETWEEN 1 AND 256),
    backup_high_water            INTEGER NOT NULL CHECK (backup_high_water >= 0),
    backup_history_digest        TEXT NOT NULL CHECK (length(backup_history_digest) = 64),
    previous_live_high_water     INTEGER CHECK (previous_live_high_water IS NULL OR previous_live_high_water >= 0),
    previous_live_history_digest TEXT CHECK (previous_live_history_digest IS NULL
                                             OR length(previous_live_history_digest) = 64),
    superseded_copy              TEXT,
    rollback_accepted            INTEGER NOT NULL CHECK (rollback_accepted IN (0, 1)),
    projections_dropped_json     TEXT NOT NULL CHECK (json_valid(projections_dropped_json)),
    actor                        TEXT NOT NULL CHECK (length(actor) BETWEEN 1 AND 256),
    opened_at                    TEXT NOT NULL,
    reconciliation_status        TEXT NOT NULL DEFAULT 'required'
                                 CHECK (reconciliation_status = 'required'),
    CHECK ((previous_live_high_water IS NULL) = (previous_live_history_digest IS NULL))
) STRICT;

-- The epoch's closure: recorded once reconciliation has resolved every attempt whose
-- outcome the restore made uncertain. Append-only; at most one per epoch.
CREATE TABLE restore_epoch_closure (
    epoch_id     INTEGER PRIMARY KEY REFERENCES restore_epoch (epoch_id),
    actor        TEXT NOT NULL CHECK (length(actor) BETWEEN 1 AND 256),
    closed_at    TEXT NOT NULL,
    summary_json TEXT NOT NULL CHECK (json_valid(summary_json))
) STRICT;

CREATE TRIGGER restore_epoch_no_update BEFORE UPDATE ON restore_epoch
BEGIN SELECT RAISE(ABORT, 'restore epochs are append-only'); END;
CREATE TRIGGER restore_epoch_no_delete BEFORE DELETE ON restore_epoch
BEGIN SELECT RAISE(ABORT, 'restore epochs are append-only'); END;
CREATE TRIGGER restore_epoch_closure_no_update BEFORE UPDATE ON restore_epoch_closure
BEGIN SELECT RAISE(ABORT, 'restore epoch closures are append-only'); END;
CREATE TRIGGER restore_epoch_closure_no_delete BEFORE DELETE ON restore_epoch_closure
BEGIN SELECT RAISE(ABORT, 'restore epoch closures are append-only'); END;

-- The reservation gate: no new attempt while any restore epoch is open.
CREATE TRIGGER attempt_reservation_gate BEFORE INSERT ON attempt
WHEN EXISTS (SELECT 1 FROM restore_epoch e
             WHERE NOT EXISTS (SELECT 1 FROM restore_epoch_closure c WHERE c.epoch_id = e.epoch_id))
BEGIN
    SELECT RAISE(ABORT, 'a restore epoch is open: new attempt reservations are refused until it is reconciled');
END;
