-- Migration 0003: an insert never replaces a row (the U-02.1 and U-02.2 review, finding S1).
--
-- Applied by conversation_store.py inside one BEGIN IMMEDIATE transaction, together with its
-- schema_migration row and PRAGMA user_version. Never edit an applied migration.
--
-- Migration 0002's triggers refuse every UPDATE and DELETE, but SQLite's REPLACE conflict
-- resolution (INSERT OR REPLACE, REPLACE) deletes the conflicting row without firing a delete
-- trigger (recursive_triggers is off), and an upsert (INSERT ... ON CONFLICT DO UPDATE) changes
-- a row without an UPDATE statement. Through either, a writer of the file could, for example,
-- flip a user message's role, add a second revision to it and flip it back. Here every insert
-- into the four append-only tables is refused before any conflict resolution runs when a row
-- with the same key already exists (its primary key, or any other unique key it has), so the
-- REPLACE, OR REPLACE and ON CONFLICT DO UPDATE forms are refused like UPDATE and DELETE.
-- Nothing is lost: the store's own writes never insert a key that exists (an append of the same
-- message is answered from the stored row, and a revision takes the next number).

CREATE TRIGGER thread_insert_never_replaces BEFORE INSERT ON thread
WHEN EXISTS (SELECT 1 FROM thread WHERE seq = NEW.seq OR thread_id = NEW.thread_id
                                        OR (session_id = NEW.session_id AND local_id = NEW.local_id))
BEGIN SELECT RAISE(ABORT, 'threads are append-only: an insert never replaces a thread'); END;

CREATE TRIGGER thread_event_insert_never_replaces BEFORE INSERT ON thread_event
WHEN EXISTS (SELECT 1 FROM thread_event WHERE seq = NEW.seq)
BEGIN SELECT RAISE(ABORT, 'thread events are append-only: an insert never replaces an event'); END;

CREATE TRIGGER message_insert_never_replaces BEFORE INSERT ON message
WHEN EXISTS (SELECT 1 FROM message WHERE thread_id = NEW.thread_id
                                     AND (message_id = NEW.message_id OR seq = NEW.seq))
BEGIN SELECT RAISE(ABORT, 'messages are append-only: an insert never replaces a message'); END;

CREATE TRIGGER message_revision_insert_never_replaces BEFORE INSERT ON message_revision
WHEN EXISTS (SELECT 1 FROM message_revision WHERE thread_id = NEW.thread_id AND message_id = NEW.message_id
                                              AND revision = NEW.revision)
BEGIN SELECT RAISE(ABORT, 'message revisions are append-only: an insert never replaces a revision'); END;
