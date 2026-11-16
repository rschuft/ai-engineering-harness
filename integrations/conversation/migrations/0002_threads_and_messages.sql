-- Migration 0002: threads and messages (plan leaf U-02.1; decision 0025, point 6).
--
-- Applied by conversation_store.py inside one BEGIN IMMEDIATE transaction, together with its
-- schema_migration row and PRAGMA user_version. Never edit an applied migration.
--
-- Every table here is append-only: no row is ever updated or deleted (the triggers below), so
-- nothing is deleted, a thread's title and archive state are events, and an assistant message's
-- later states are revisions. Identity:
--   * the thread id is the store's, a UUID version 4 minted at initialize; the browser's local
--     thread id is kept beside it, unique per session, so a repeated initialize finds its thread;
--   * the message id is assistant-ui's native id (seven characters of [0-9A-Za-z]), unique per
--     thread; its lineage reference is conversation:<thread>/<message>;
--   * order is the store's per-thread sequence (seq), assigned at the first append: 1, 2, 3...
-- A user message (the Owner's statement, author 'owner') is immutable: it has exactly one revision,
-- whose content is the UTF-8 bytes of its one text part exactly as received. Those bytes are the
-- durable source of every quote and span anchor. An assistant message (display state the Owner
-- UI shell wrote, author 'owner-host') holds the message as canonical JSON, and an update appends
-- a revision. An edit in assistant-ui is a new message under the same parent: both are kept.

-- One row per thread.
CREATE TABLE thread (
    seq        INTEGER PRIMARY KEY CHECK (seq >= 1),
    thread_id  TEXT NOT NULL UNIQUE
               CHECK (length(thread_id) = 36 AND thread_id GLOB
                      '[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]-[0-9a-f][0-9a-f][0-9a-f][0-9a-f]-4[0-9a-f][0-9a-f][0-9a-f]-[89ab][0-9a-f][0-9a-f][0-9a-f]-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
    session_id TEXT NOT NULL REFERENCES owner_session (session_id),
    local_id   TEXT NOT NULL
               CHECK (length(local_id) BETWEEN 11 AND 74 AND substr(local_id, 1, 10) = '__LOCALID_'
                      AND substr(local_id, 11) NOT GLOB '*[^0-9A-Za-z]*'),
    created_at TEXT NOT NULL
               CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
                      AND julianday(created_at) IS NOT NULL),
    UNIQUE (session_id, local_id)
) STRICT;

-- A thread's title and archive state, as events; the latest of each kind is current.
CREATE TABLE thread_event (
    seq         INTEGER PRIMARY KEY CHECK (seq >= 1),
    thread_id   TEXT NOT NULL REFERENCES thread (thread_id),
    kind        TEXT NOT NULL CHECK (kind IN ('rename', 'archive', 'unarchive')),
    title       TEXT CHECK (title IS NULL OR (length(title) BETWEEN 1 AND 200)),
    session_id  TEXT NOT NULL REFERENCES owner_session (session_id),
    recorded_at TEXT NOT NULL
                CHECK (recorded_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
                       AND julianday(recorded_at) IS NOT NULL),
    CHECK ((kind = 'rename') = (title IS NOT NULL))
) STRICT;

-- One row per message: its identity, place and attribution. Its content is in message_revision.
CREATE TABLE message (
    thread_id   TEXT NOT NULL REFERENCES thread (thread_id),
    message_id  TEXT NOT NULL CHECK (length(message_id) = 7 AND message_id NOT GLOB '*[^0-9A-Za-z]*'),
    seq         INTEGER NOT NULL CHECK (seq >= 1),
    parent_id   TEXT,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    author      TEXT NOT NULL CHECK ((role = 'user' AND author = 'owner') OR (role = 'assistant' AND author = 'owner-host')),
    session_id  TEXT NOT NULL REFERENCES owner_session (session_id),
    created_at  TEXT,
    appended_at TEXT NOT NULL
                CHECK (appended_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
                       AND julianday(appended_at) IS NOT NULL),
    PRIMARY KEY (thread_id, message_id),
    UNIQUE (thread_id, seq),
    FOREIGN KEY (thread_id, parent_id) REFERENCES message (thread_id, message_id),
    CHECK (parent_id IS NULL OR parent_id <> message_id),
    -- a user message keeps here the createdAt the shell sent, as its content is its text alone, and an assistant
    -- message keeps it inside its JSON
    CHECK ((role = 'user') = (created_at IS NOT NULL)),
    CHECK (created_at IS NULL OR (length(created_at) = 24 AND created_at GLOB
           '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'))
) STRICT;

-- The content of a message, by revision. A user message has exactly revision 1.
CREATE TABLE message_revision (
    thread_id   TEXT NOT NULL,
    message_id  TEXT NOT NULL,
    revision    INTEGER NOT NULL CHECK (revision >= 1),
    content     BLOB NOT NULL CHECK (length(content) BETWEEN 1 AND 262144),
    sha256      TEXT NOT NULL CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    session_id  TEXT NOT NULL REFERENCES owner_session (session_id),
    recorded_at TEXT NOT NULL
                CHECK (recorded_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
                       AND julianday(recorded_at) IS NOT NULL),
    PRIMARY KEY (thread_id, message_id, revision),
    FOREIGN KEY (thread_id, message_id) REFERENCES message (thread_id, message_id)
) STRICT;

-- Threads are numbered 1, 2, 3...; so are a thread's events.
CREATE TRIGGER thread_seq_is_next BEFORE INSERT ON thread
WHEN NEW.seq IS NOT (SELECT coalesce(max(seq), 0) + 1 FROM thread)
BEGIN SELECT RAISE(ABORT, 'a thread takes the next sequence number'); END;

CREATE TRIGGER thread_event_seq_is_next BEFORE INSERT ON thread_event
WHEN NEW.seq IS NOT (SELECT coalesce(max(seq), 0) + 1 FROM thread_event)
BEGIN SELECT RAISE(ABORT, 'a thread event takes the next sequence number'); END;

-- A message takes its thread's next sequence number, and its parent is an earlier message of the thread.
CREATE TRIGGER message_seq_is_next BEFORE INSERT ON message
WHEN NEW.seq IS NOT (SELECT coalesce(max(seq), 0) + 1 FROM message WHERE thread_id = NEW.thread_id)
BEGIN SELECT RAISE(ABORT, 'a message takes its thread''s next sequence number'); END;

-- Revisions are numbered 1, 2, 3... per message; a user message has revision 1 only (it is immutable).
CREATE TRIGGER message_revision_is_next BEFORE INSERT ON message_revision
WHEN NEW.revision IS NOT (SELECT coalesce(max(revision), 0) + 1 FROM message_revision
                          WHERE thread_id = NEW.thread_id AND message_id = NEW.message_id)
BEGIN SELECT RAISE(ABORT, 'a revision takes the message''s next revision number'); END;

CREATE TRIGGER message_revision_user_is_immutable BEFORE INSERT ON message_revision
WHEN NEW.revision > 1 AND (SELECT role FROM message
                           WHERE thread_id = NEW.thread_id AND message_id = NEW.message_id) = 'user'
BEGIN SELECT RAISE(ABORT, 'a user message is immutable'); END;

-- Nothing is updated and nothing is deleted.
CREATE TRIGGER thread_no_update BEFORE UPDATE ON thread
BEGIN SELECT RAISE(ABORT, 'threads are append-only'); END;

CREATE TRIGGER thread_no_delete BEFORE DELETE ON thread
BEGIN SELECT RAISE(ABORT, 'threads are append-only'); END;

CREATE TRIGGER thread_event_no_update BEFORE UPDATE ON thread_event
BEGIN SELECT RAISE(ABORT, 'thread events are append-only'); END;

CREATE TRIGGER thread_event_no_delete BEFORE DELETE ON thread_event
BEGIN SELECT RAISE(ABORT, 'thread events are append-only'); END;

CREATE TRIGGER message_no_update BEFORE UPDATE ON message
BEGIN SELECT RAISE(ABORT, 'messages are append-only'); END;

CREATE TRIGGER message_no_delete BEFORE DELETE ON message
BEGIN SELECT RAISE(ABORT, 'messages are append-only'); END;

CREATE TRIGGER message_revision_no_update BEFORE UPDATE ON message_revision
BEGIN SELECT RAISE(ABORT, 'message revisions are append-only'); END;

CREATE TRIGGER message_revision_no_delete BEFORE DELETE ON message_revision
BEGIN SELECT RAISE(ABORT, 'message revisions are append-only'); END;
