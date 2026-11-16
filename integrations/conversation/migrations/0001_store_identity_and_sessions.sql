-- Migration 0001: store identity and the Owner UI session table (plan leaf U-01.3; Proposed
-- decision 0025, points 3 and 6).
--
-- Applied by conversation_store.py inside one BEGIN IMMEDIATE transaction, together with its
-- schema_migration row and PRAGMA user_version. Never edit an applied migration: the store refuses
-- to open a database whose recorded checksum differs from the file. Change the schema with a new,
-- higher-numbered migration (threads and messages are U-02.1's migration 0002).
--
-- application_id identifies the file as an Owner conversation store, so the integration and effects
-- stores (and any other tool using integrations/storecore) refuse to open it, and this store refuses
-- theirs. 1095320406 = 0x41494356 ('AICV').
PRAGMA application_id = 1095320406;

-- Applied migrations, one row per file, with the sha256 of its LF-normalised text.
CREATE TABLE schema_migration (
    version    INTEGER PRIMARY KEY CHECK (version >= 1),
    name       TEXT NOT NULL UNIQUE,
    sha256     TEXT NOT NULL CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    applied_at TEXT NOT NULL
) STRICT;

-- One row per enrollment of the Owner UI session credential (cred-owner-ui-session), written only by
-- the Owner's enroll command. The credential itself is never stored: only its verifier (the sha256 of
-- a fixed domain line and the credential), the session's public id and its validity. Append-only:
-- nothing is updated or deleted. Exactly one session is current, the last one; a new enrollment
-- names the current session it supersedes, and a superseded session is refused afterwards
-- (SESSION_CREDENTIAL_REVOKED). An expired session is kept, so that expired and foreign stay
-- distinguishable. The validity is at most 7 days.
CREATE TABLE owner_session (
    seq        INTEGER PRIMARY KEY CHECK (seq >= 1),
    session_id TEXT NOT NULL UNIQUE
               CHECK (length(session_id) = 36 AND session_id GLOB
                      '[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]-[0-9a-f][0-9a-f][0-9a-f][0-9a-f]-4[0-9a-f][0-9a-f][0-9a-f]-[89ab][0-9a-f][0-9a-f][0-9a-f]-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
    verifier   TEXT NOT NULL UNIQUE CHECK (length(verifier) = 64 AND verifier NOT GLOB '*[^0-9a-f]*'),
    issued_at  TEXT NOT NULL
               CHECK (issued_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
                      AND julianday(issued_at) IS NOT NULL),
    expires_at TEXT NOT NULL
               CHECK (expires_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
                      AND julianday(expires_at) IS NOT NULL),
    supersedes TEXT UNIQUE REFERENCES owner_session (session_id),
    CHECK (expires_at > issued_at AND julianday(expires_at) - julianday(issued_at) <= 7)
) STRICT;

-- The current session is the last row; a new row supersedes exactly it (none for the first).
CREATE TRIGGER owner_session_supersedes_the_current BEFORE INSERT ON owner_session
WHEN NEW.supersedes IS NOT (SELECT session_id FROM owner_session ORDER BY seq DESC LIMIT 1)
     OR NEW.seq IS NOT (SELECT coalesce(max(seq), 0) + 1 FROM owner_session)
BEGIN SELECT RAISE(ABORT, 'a new session supersedes exactly the current one'); END;

CREATE TRIGGER owner_session_no_update BEFORE UPDATE ON owner_session
BEGIN SELECT RAISE(ABORT, 'owner sessions are append-only'); END;

CREATE TRIGGER owner_session_no_delete BEFORE DELETE ON owner_session
BEGIN SELECT RAISE(ABORT, 'owner sessions are append-only'); END;
