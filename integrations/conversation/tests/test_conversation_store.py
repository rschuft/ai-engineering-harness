"""The Owner conversation store, migration 0001 (plan leaf U-01.3; decision 0025, points 3 and 6).

A store kind of its own on integrations/storecore: its application_id identifies it, so the integration store refuses
it and it refuses an integration store; the connection policy is storecore's; the migration ledger refuses an edited
migration. The session table is append-only (no update, no delete), keeps a verifier and never a credential, holds
exactly one current session (each enrollment supersedes exactly the current one, which SQLite enforces whatever
writes the row), and bounds the validity to 7 days. Every database lives in a fresh temporary directory outside the
checkout.
"""
from __future__ import annotations

import importlib.util
import shutil
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

CATEGORY = 'unit'
HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
REPO = PACKAGE.parents[1]


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


CS = _load('aieh_conversation_store', PACKAGE / 'conversation_store.py')
IS = _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')
storecore = CS.storecore


def session_args(verifier_digit='a', issued='2026-11-16T00:00:00Z', expires='2026-11-16T12:00:00Z'):
    return {'session_id': str(uuid.uuid4()), 'verifier': verifier_digit * 64, 'issued_at': issued,
            'expires_at': expires}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-conversation-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = CS.open_store(self.tmp / CS.DB_NAME)
        self.addCleanup(self.store.close)


class Identity(Base):
    def test_the_store_kind_and_its_migration(self):
        summary = self.store.summary()
        self.assertEqual((summary['store_kind'], summary['application_id'], summary['schema_version']),
                         ('conversation', 0x41494356, 3))
        self.assertEqual([m['name'] for m in summary['migrations']], ['0001_store_identity_and_sessions.sql',
                                                                      '0002_threads_and_messages.sql',
                                                                      '0003_insert_never_replaces.sql'])
        self.assertEqual(summary['pragmas'], {'journal_mode': 'wal', 'synchronous': 2, 'foreign_keys': 1,
                                              'busy_timeout': storecore.DEFAULT_BUSY_TIMEOUT_MS})
        tables = [r[0] for r in self.store.conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table' "
                                                        'ORDER BY name')]
        self.assertEqual(tables, ['message', 'message_revision', 'owner_session', 'schema_migration', 'thread',
                                  'thread_event'])            # migration 0002 (U-02.1) added the last four
        self.assertEqual({0x41494356, IS.APPLICATION_ID, 0x41454658}.__len__(), 3)   # unlike the other two kinds
        self.assertEqual(CS.store_path(Path('C:/managed/state')), Path('C:/managed/state/owner-host/conversation.sqlite'))

    def test_reopening_is_idempotent_and_the_dump_is_stable(self):
        self.store.enroll_session(**session_args())
        dump = self.store.canonical_dump()
        self.store.close()
        again = CS.open_store(self.tmp / CS.DB_NAME, apply_migrations=False)
        self.addCleanup(again.close)
        self.assertEqual(again.canonical_dump(), dump)

    def test_other_store_kinds_refuse_each_other(self):
        other = IS.open_store(self.tmp / 'integration.sqlite')
        other.close()
        with self.assertRaises(CS.WrongStoreKind):
            CS.open_store(self.tmp / 'integration.sqlite')
        with self.assertRaises(storecore.WrongStoreKind):
            IS.open_store(self.tmp / CS.DB_NAME)

    def test_an_edited_migration_is_refused(self):
        self.store.close()
        edited = self.tmp / 'migrations'
        edited.mkdir()
        text = (CS.MIGRATIONS_DIR / '0001_store_identity_and_sessions.sql').read_text(encoding='utf-8')
        (edited / '0001_store_identity_and_sessions.sql').write_text(text + '\n-- edited\n', encoding='utf-8')
        with self.assertRaises(CS.MigrationError):
            CS.open_store(self.tmp / CS.DB_NAME, migrations_dir=edited)

    def test_a_location_inside_the_checkout_or_in_memory_is_refused(self):
        for path in (REPO / 'conversation.sqlite', ':memory:', 'file:x.sqlite'):
            with self.subTest(path=str(path)), self.assertRaises(CS.UnsafeLocation):
                CS.open_store(path)
        with self.assertRaises(CS.UnsafeLocation):
            CS.open_store(self.tmp / 'missing' / CS.DB_NAME)

    def test_backup_and_restore_are_not_decided(self):
        with self.assertRaises(storecore.RestoreRefused):
            CS.KIND.after_restore(self.store.conn, None)


class Sessions(Base):
    def test_each_enrollment_supersedes_exactly_the_current_one(self):
        one = self.store.enroll_session(**session_args('a'))
        two = self.store.enroll_session(**session_args('b'))
        three = self.store.enroll_session(**session_args('c'))
        self.assertEqual([one.supersedes, two.supersedes, three.supersedes], [None, one.session_id, two.session_id])
        self.assertEqual([s.superseded_by for s in self.store.sessions()], [two.session_id, three.session_id, None])
        self.assertEqual(self.store.current_session().session_id, three.session_id)
        self.assertEqual(self.store.session_by_verifier('a' * 64).current, False)
        self.assertEqual(three.public(), {'sessionId': three.session_id, 'issuedAt': three.issued_at,
                                          'expiresAt': three.expires_at, 'supersedes': two.session_id,
                                          'current': True})

    def test_sqlite_enforces_the_chain_whatever_writes_the_row(self):
        one = self.store.enroll_session(**session_args('a'))
        insert = 'INSERT INTO owner_session VALUES (?, ?, ?, ?, ?, ?)'
        for seq, supersedes in ((2, None), (2, str(uuid.uuid4())), (3, one.session_id)):
            with self.subTest(seq=seq, supersedes=supersedes), self.assertRaises(sqlite3.IntegrityError):
                self.store.conn.execute(insert, (seq, str(uuid.uuid4()), 'b' * 64, '2026-11-16T00:00:00Z',
                                                 '2026-11-16T01:00:00Z', supersedes))
        dump = self.store.canonical_dump()
        for statement in ("UPDATE owner_session SET expires_at = '2026-11-17T00:00:00Z'", 'DELETE FROM owner_session'):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                self.store.conn.execute(statement)
        self.assertEqual(self.store.canonical_dump(), dump)

    def test_values_are_checked_before_and_by_the_store(self):
        dump = self.store.canonical_dump()
        for change in ({'session_id': 'not-a-uuid'}, {'session_id': str(uuid.uuid4()).upper()},
                       {'session_id': str(uuid.uuid1())}, {'verifier': 'A' * 64}, {'verifier': 'a' * 63},
                       {'issued_at': '2026-11-16 00:00:00'}, {'expires_at': '2026-11-16T00:00:00Z'},
                       {'expires_at': '2026-11-23T00:00:01Z'}, {'issued_at': '2026-13-40T00:00:00Z'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.store.enroll_session(**{**session_args(), **change})
        self.assertEqual(self.store.canonical_dump(), dump)
        self.store.enroll_session(**session_args(expires='2026-11-23T00:00:00Z'))    # 7 days is the ceiling

    def test_a_verifier_or_session_id_is_used_once(self):
        first = session_args('a')
        self.store.enroll_session(**first)
        dump = self.store.canonical_dump()
        for again in ({**session_args('a')}, {**session_args('b'), 'session_id': first['session_id']}):
            with self.assertRaises(CS.SessionConflict):
                self.store.enroll_session(**again)
        self.assertEqual(self.store.canonical_dump(), dump)

    def test_lookup_of_a_malformed_verifier_reads_nothing(self):
        self.store.enroll_session(**session_args('a'))
        for bad in (None, '', 'a' * 63, 'A' * 64, "' OR 1=1 --", 42):
            self.assertIsNone(self.store.session_by_verifier(bad))
        self.assertIsNone(self.store.session_by_verifier('b' * 64))


class AlteredSchema(Base):
    """A writer outside this module that drops or replaces a trigger (the review's probe_triggers scenario: drop the
    no-delete and no-update triggers, delete the superseding row, extend the superseded one) leaves a store that
    open_store refuses, CONVERSATION_STORE_ALTERED, so no reader accepts the resurrected session. A writer that keeps
    the schema is the same-account limit (decision 0010 point 1), not detected here."""

    def tamper(self, script):
        self.store.enroll_session(**session_args('a'))
        self.store.enroll_session(**session_args('b'))
        self.store.close()
        conn = sqlite3.connect(self.tmp / CS.DB_NAME)
        conn.executescript(script)
        conn.commit()
        conn.close()
        with self.assertRaises(CS.SchemaAltered) as caught:
            CS.open_store(self.tmp / CS.DB_NAME)
        self.assertEqual(caught.exception.code, 'CONVERSATION_STORE_ALTERED')
        self.assertTrue(str(caught.exception).startswith('CONVERSATION_STORE_ALTERED: '))
        with self.assertRaises(CS.SchemaAltered):
            CS.open_store(self.tmp / CS.DB_NAME, apply_migrations=False)

    def test_a_fresh_and_a_reopened_store_have_exactly_the_migrated_schema(self):
        CS.check_schema(self.store.conn)
        self.assertEqual({row[1] for row in CS.expected_schema() if row[0] == 'trigger'},
                         {'owner_session_supersedes_the_current', 'owner_session_no_update', 'owner_session_no_delete',
                          # migration 0002 (U-02.1)
                          'thread_seq_is_next', 'thread_event_seq_is_next', 'message_seq_is_next',
                          'message_revision_is_next', 'message_revision_user_is_immutable', 'thread_no_update',
                          'thread_no_delete', 'thread_event_no_update', 'thread_event_no_delete', 'message_no_update',
                          'message_no_delete', 'message_revision_no_update', 'message_revision_no_delete',
                          # migration 0003 (the U-02.1 and U-02.2 review, finding S1)
                          'thread_insert_never_replaces', 'thread_event_insert_never_replaces',
                          'message_insert_never_replaces', 'message_revision_insert_never_replaces'})

    def test_resurrecting_a_superseded_session_by_dropping_the_triggers_is_refused_at_open(self):
        self.tamper('DROP TRIGGER owner_session_no_delete; DROP TRIGGER owner_session_no_update; '
                    'DELETE FROM owner_session WHERE seq = 2; '
                    "UPDATE owner_session SET expires_at = '2026-11-17T00:00:00Z' WHERE seq = 1;")

    def test_a_replaced_trigger_is_refused_at_open(self):
        self.tamper('DROP TRIGGER owner_session_no_update; CREATE TRIGGER owner_session_no_update BEFORE UPDATE ON '
                    "owner_session WHEN 0 BEGIN SELECT RAISE(ABORT, 'x'); END;")

    def test_an_added_object_is_refused_at_open(self):
        self.tamper('CREATE TABLE extra (x INTEGER) STRICT;')


if __name__ == '__main__':
    unittest.main()
