-- Migration 0003: typed attempt identity and the one-live-claim rule (plan leaf E-01.1.1).
--
-- Applied by integration_store.py inside one BEGIN IMMEDIATE transaction, together
-- with its schema_migration row and PRAGMA user_version. Never edit an applied
-- migration; add a new one. Migrations 0001 and 0002, the attempt states and their
-- transitions are unchanged.
--
-- Blueprint #execution-qualification, dispatch step 02: "Persist Work ID, immutable
-- design revision, attempt UUID, preselected conversation UUID, planned workspace and
-- policy digest. Prevent concurrent claims of the same Work revision/stage."
--
-- A typed attempt is an `attempt` row whose operation key is the canonical
--     attempt/v1/<work_id>/<design change>@<design commit>/<stage>/<ordinal>
-- together with exactly one `attempt_identity` row holding the same identity as
-- typed, immutable columns. Every part of the key has a grammar without '/', so the
-- encoding is unambiguous without escaping. The `attempt/` key namespace belongs to
-- typed attempts alone. Rows reserved through the opaque-key API (all rows of a store
-- created before this migration) stay valid and are untyped ('legacy-untyped').

-- Refuse the migration, and change nothing, when an untyped attempt already uses the
-- reserved namespace: it could not be given an identity and would evade the claim rule.
CREATE TABLE migration_0003_guard (
    legacy_keys INTEGER NOT NULL,
    CONSTRAINT legacy_attempt_keys_in_reserved_attempt_namespace CHECK (legacy_keys = 0)
) STRICT;
INSERT INTO migration_0003_guard (legacy_keys)
    SELECT count(*) FROM attempt WHERE operation_key GLOB 'attempt/*';
DROP TABLE migration_0003_guard;

-- The closed set of attempt stages. A later migration adds a stage by dropping the
-- guards below, inserting a row and recreating them, as for attempt_state.
CREATE TABLE attempt_stage (
    stage       TEXT PRIMARY KEY
                CHECK (length(stage) BETWEEN 1 AND 32 AND stage NOT GLOB '*[^a-z]*'),
    description TEXT NOT NULL
) STRICT;

INSERT INTO attempt_stage (stage, description) VALUES
    ('implement', 'scoped implementation of the Work item; rework after a review is another implement ordinal'),
    ('review',    'independent review of an exact revision in a separate run; a fresh review is another review ordinal');

CREATE TRIGGER attempt_stage_frozen_insert BEFORE INSERT ON attempt_stage
BEGIN SELECT RAISE(ABORT, 'attempt_stage changes only by migration'); END;
CREATE TRIGGER attempt_stage_frozen_update BEFORE UPDATE ON attempt_stage
BEGIN SELECT RAISE(ABORT, 'attempt_stage changes only by migration'); END;
CREATE TRIGGER attempt_stage_frozen_delete BEFORE DELETE ON attempt_stage
BEGIN SELECT RAISE(ABORT, 'attempt_stage changes only by migration'); END;

-- The typed identity, 1:1 with its attempt. It is inserted BEFORE its attempt row
-- (the reference is deferred to COMMIT), so the attempt's insert trigger can check
-- the attempt against it; an identity without its attempt cannot commit.
--
-- Grammars (the Python library checks the same, and a differential test compares
-- the two):
--   work_id          Backlog.md task id, planning_adapter.TASK_ID_RE, upper case
--                    (Backlog.md and the planning adapter compare ids without case);
--                    at most 64 characters
--   design_revision  openspec:changes/<change>@<commit>: planning_adapter's CHANGE_ID
--                    (at most 128 characters) and a full COMMIT (40 or 64 hex)
--   stage            a row of attempt_stage
--   ordinal          1, 2, 3 ... per (work_id, design_revision, stage), no gaps
--   *_digest         64 lower-case hex digits (sha256); agent_manifest_digest is NULL
--                    while no approved agent/Skill catalog exists (E-01.2.1)
--   planned_workspace a relative identifier under the managed root's
--                    persistent/workspaces category (decision 0009), planning_adapter's
--                    ARTIFACT_PATH grammar, at most 255 characters; never a host path
--   live             1 while the attempt is reserved, dispatched or unknown, 0 once it
--                    is confirmed or failed; maintained by trigger only
CREATE TABLE attempt_identity (
    operation_key         TEXT PRIMARY KEY
                          REFERENCES attempt (operation_key) DEFERRABLE INITIALLY DEFERRED,
    attempt_id            TEXT NOT NULL UNIQUE
                          CHECK (length(attempt_id) = 36 AND attempt_id NOT GLOB '*[^0-9a-f-]*'),
    work_id               TEXT NOT NULL,
    design_revision       TEXT NOT NULL,
    stage                 TEXT NOT NULL REFERENCES attempt_stage (stage),
    ordinal               INTEGER NOT NULL,
    profile_digest        TEXT NOT NULL,
    agent_manifest_digest TEXT,
    planned_workspace     TEXT NOT NULL,
    policy_digest         TEXT NOT NULL,
    live                  INTEGER NOT NULL,
    UNIQUE (work_id, design_revision, stage, ordinal),
    CONSTRAINT work_id_grammar CHECK (
        length(work_id) BETWEEN 3 AND 64
        AND work_id = upper(work_id)
        AND work_id NOT GLOB '*[^A-Z0-9.-]*'
        AND instr(work_id, '-') > 1
        AND substr(work_id, 1, instr(work_id, '-') - 1) NOT GLOB '*[^A-Z]*'
        AND substr(work_id, instr(work_id, '-') + 1) <> ''
        AND substr(work_id, instr(work_id, '-') + 1) NOT GLOB '*[^0-9.]*'
        AND substr(work_id, instr(work_id, '-') + 1) NOT GLOB '.*'
        AND substr(work_id, instr(work_id, '-') + 1) NOT GLOB '*.'
        AND work_id NOT GLOB '*..*'),
    CONSTRAINT design_revision_grammar CHECK (
        design_revision GLOB 'openspec:changes/*@*'
        AND instr(design_revision, '@') BETWEEN 19 AND 146
        AND substr(design_revision, 18, instr(design_revision, '@') - 18) NOT GLOB '*[^a-z0-9-]*'
        AND substr(design_revision, 18, instr(design_revision, '@') - 18) NOT GLOB '-*'
        AND substr(design_revision, 18, instr(design_revision, '@') - 18) NOT GLOB '*-'
        AND substr(design_revision, 18, instr(design_revision, '@') - 18) NOT GLOB '*--*'
        AND length(substr(design_revision, instr(design_revision, '@') + 1)) IN (40, 64)
        AND substr(design_revision, instr(design_revision, '@') + 1) NOT GLOB '*[^0-9a-f]*'),
    CONSTRAINT ordinal_range CHECK (ordinal BETWEEN 1 AND 999999),
    CONSTRAINT profile_digest_sha256 CHECK (
        length(profile_digest) = 64 AND profile_digest NOT GLOB '*[^0-9a-f]*'),
    CONSTRAINT agent_manifest_digest_sha256 CHECK (
        agent_manifest_digest IS NULL
        OR (length(agent_manifest_digest) = 64 AND agent_manifest_digest NOT GLOB '*[^0-9a-f]*')),
    CONSTRAINT policy_digest_sha256 CHECK (
        length(policy_digest) = 64 AND policy_digest NOT GLOB '*[^0-9a-f]*'),
    CONSTRAINT planned_workspace_grammar CHECK (
        length(planned_workspace) BETWEEN 1 AND 255
        AND planned_workspace NOT GLOB '*[^A-Za-z0-9._/-]*'
        AND planned_workspace NOT GLOB '.*'
        AND planned_workspace NOT GLOB '-*'
        AND planned_workspace NOT GLOB '/*'
        AND planned_workspace NOT GLOB '*/.*'
        AND planned_workspace NOT GLOB '*/-*'
        AND planned_workspace NOT GLOB '*//*'
        AND planned_workspace NOT GLOB '*/'),
    CONSTRAINT live_flag CHECK (live IN (0, 1))
) STRICT;

-- The one-live-claim rule as a structure: at most one live attempt per
-- (work_id, design_revision, stage), whatever writes the rows.
CREATE UNIQUE INDEX attempt_identity_one_live_claim
    ON attempt_identity (work_id, design_revision, stage) WHERE live = 1;

-- Admission of a typed identity: canonical key, starts live, precedes its attempt,
-- no live claim on the triple, and the next ordinal with no gap. Every earlier
-- ordinal is then terminal (confirmed or failed): rework and fresh reviews are new
-- ordinals; whether one is warranted, and how many, is policy, not schema.
CREATE TRIGGER attempt_identity_admission BEFORE INSERT ON attempt_identity
BEGIN
    SELECT RAISE(ABORT, 'operation_key must be the canonical attempt/v1 encoding of the typed identity')
    WHERE NEW.operation_key IS NOT ('attempt/v1/' || NEW.work_id || '/' || substr(NEW.design_revision, 18)
                                    || '/' || NEW.stage || '/' || printf('%d', NEW.ordinal));
    SELECT RAISE(ABORT, 'a typed attempt identity is reserved live')
    WHERE NEW.live IS NOT 1;
    SELECT RAISE(ABORT, 'a typed attempt identity is inserted before its attempt row, never attached to one')
    WHERE EXISTS (SELECT 1 FROM attempt WHERE operation_key = NEW.operation_key);
    SELECT RAISE(ABORT, 'live claim: an attempt on this work, design revision and stage is still reserved, dispatched or unknown')
    WHERE EXISTS (SELECT 1 FROM attempt_identity
                  WHERE work_id = NEW.work_id AND design_revision = NEW.design_revision
                    AND stage = NEW.stage AND live = 1);
    SELECT RAISE(ABORT, 'ordinal out of sequence: the next ordinal on this work, design revision and stage is required')
    WHERE NEW.ordinal IS NOT (SELECT coalesce(max(ordinal), 0) + 1 FROM attempt_identity
                              WHERE work_id = NEW.work_id AND design_revision = NEW.design_revision
                                AND stage = NEW.stage);
END;

-- Identity columns never change; `live` changes only to agree with the attempt's state.
CREATE TRIGGER attempt_identity_columns_immutable
BEFORE UPDATE OF operation_key, attempt_id, work_id, design_revision, stage, ordinal, profile_digest,
                 agent_manifest_digest, planned_workspace, policy_digest ON attempt_identity
BEGIN
    SELECT RAISE(ABORT, 'attempt identity is immutable');
END;

CREATE TRIGGER attempt_identity_live_follows_state BEFORE UPDATE OF live ON attempt_identity
WHEN NEW.live IS NOT (SELECT 1 - s.terminal FROM attempt a JOIN attempt_state s ON s.state = a.state
                      WHERE a.operation_key = NEW.operation_key)
BEGIN
    SELECT RAISE(ABORT, 'live follows the attempt state; it is never written to disagree with it');
END;

CREATE TRIGGER attempt_identity_no_delete BEFORE DELETE ON attempt_identity
BEGIN
    SELECT RAISE(ABORT, 'attempt identities are never deleted');
END;

-- Keep `live` in step with every state change of a typed attempt.
CREATE TRIGGER attempt_identity_live_sync AFTER UPDATE OF state ON attempt
BEGIN
    UPDATE attempt_identity
       SET live = (SELECT 1 - terminal FROM attempt_state WHERE state = NEW.state)
     WHERE operation_key = NEW.operation_key;
END;

-- An attempt in the attempt/ namespace is typed: its identity row must already exist,
-- it starts reserved, and its intent carries the same identity (attemptIdentity) and
-- workRef = backlog:<work_id>, which the lineage reader follows.
CREATE TRIGGER attempt_typed_admission BEFORE INSERT ON attempt
WHEN NEW.operation_key GLOB 'attempt/*'
BEGIN
    SELECT RAISE(ABORT, 'a key in the attempt/ namespace needs its typed identity')
    WHERE NOT EXISTS (SELECT 1 FROM attempt_identity WHERE operation_key = NEW.operation_key);
    SELECT RAISE(ABORT, 'a typed attempt starts reserved')
    WHERE NEW.state IS NOT 'reserved' OR NEW.reconciliation_status IS NOT 'none' OR NEW.state_seq IS NOT 0;
    SELECT RAISE(ABORT, 'the typed attempt intent does not carry its identity')
    WHERE NOT EXISTS (
        SELECT 1 FROM attempt_identity i
         WHERE i.operation_key = NEW.operation_key
           AND json_valid(NEW.intent_json)
           AND json_extract(NEW.intent_json, '$.workRef') IS 'backlog:' || i.work_id
           AND json_extract(NEW.intent_json, '$.attemptIdentity.format') IS 'attempt-identity/v1'
           AND json_extract(NEW.intent_json, '$.attemptIdentity.work_id') IS i.work_id
           AND json_extract(NEW.intent_json, '$.attemptIdentity.design_revision') IS i.design_revision
           AND json_extract(NEW.intent_json, '$.attemptIdentity.stage') IS i.stage
           AND json_type(NEW.intent_json, '$.attemptIdentity.ordinal') IS 'integer'
           AND json_extract(NEW.intent_json, '$.attemptIdentity.ordinal') IS i.ordinal
           AND json_extract(NEW.intent_json, '$.attemptIdentity.profile_digest') IS i.profile_digest
           AND json_type(NEW.intent_json, '$.attemptIdentity.agent_manifest_digest') IS NOT NULL
           AND json_extract(NEW.intent_json, '$.attemptIdentity.agent_manifest_digest') IS i.agent_manifest_digest
           AND json_extract(NEW.intent_json, '$.attemptIdentity.planned_workspace') IS i.planned_workspace
           AND json_extract(NEW.intent_json, '$.attemptIdentity.policy_digest') IS i.policy_digest);
END;

-- Which attempts are typed. 'legacy-untyped': reserved under an opaque key, either
-- before this migration or later through the opaque-key API; such rows are never
-- rewritten, never given an identity, and stay outside the claim rule.
CREATE VIEW attempt_typing AS
SELECT a.operation_key,
       CASE WHEN i.operation_key IS NULL THEN 'legacy-untyped' ELSE 'typed' END AS identity_form
  FROM attempt a LEFT JOIN attempt_identity i ON i.operation_key = a.operation_key;
