"""Tests for integrations/store/integration_store.py (stdlib unittest).

Run from the repository root:

    python -I -B -m unittest discover -s integrations/store/tests -v

Every database lives in a fresh temporary directory outside the checkout. The
restart, crash and contention tests use real processes against one file
(store_worker.py); the parent waits on each worker's own output lines and exit,
never on a fixed sleep.
"""
from pathlib import Path
import dataclasses
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
STORE_DIR = HERE.parent
REPO = STORE_DIR.parents[1]
MODULE = STORE_DIR / 'integration_store.py'
WORKER = HERE / 'store_worker.py'

_spec = importlib.util.spec_from_file_location('integration_store', MODULE)
store_mod = importlib.util.module_from_spec(_spec)
sys.modules['integration_store'] = store_mod
_spec.loader.exec_module(store_mod)

WAIT_CEILING_S = 60  # bounds a hang; workers normally finish in well under a second
CONTENDERS = 8
GOLDEN_KEY = 'F-05.1/golden-operation-key'
GOLDEN_CONVERSATION_ID = 'e335cde2-58fc-514d-a760-627fa6bebce3'
INTENT = {'scoped_resources': {'repository': 'example/repo', 'worktree': 'task-1'},
          'request': {'agent': 'builder', 'prompt_digest': '0' * 64}}


def worker_cmd(*args):
    return [sys.executable, '-I', '-B', str(WORKER), *args]


def run_worker(*args):
    result = subprocess.run(worker_cmd(*args), capture_output=True, text=True,
                            encoding='utf-8', timeout=WAIT_CEILING_S)
    return result.returncode, [json.loads(line) for line in result.stdout.splitlines()], result.stderr


def start_worker(*args):
    return subprocess.Popen(worker_cmd(*args), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding='utf-8')


def read_message(proc):
    """Block on the worker's next output line: its own completion signal."""
    line = proc.stdout.readline()
    if not line:
        proc.wait(timeout=WAIT_CEILING_S)
        raise AssertionError(f'worker exited {proc.returncode} without output: {proc.stderr.read()}')
    return json.loads(line)


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-store-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = self.tmp / 'integration.sqlite'

    def open(self, **kwargs):
        store = store_mod.open_store(self.db, **kwargs)
        self.addCleanup(store.close)
        return store

    def copy_migrations(self):
        target = self.tmp / 'migrations'
        shutil.copytree(store_mod.MIGRATIONS_DIR, target)
        return target


class PragmaAndVersionTests(StoreTestCase):
    def test_opened_connection_has_wal_full_sync_foreign_keys_and_busy_timeout(self):
        store = self.open()
        conn = store.conn
        self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        self.assertEqual(conn.execute('PRAGMA synchronous').fetchone()[0], 2)  # FULL
        self.assertEqual(conn.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        self.assertEqual(conn.execute('PRAGMA busy_timeout').fetchone()[0],
                         store_mod.DEFAULT_BUSY_TIMEOUT_MS)

    def test_runtime_sqlite_meets_minimum_and_old_versions_are_refused(self):
        self.assertGreaterEqual(sqlite3.sqlite_version_info, store_mod.MIN_SQLITE_VERSION)
        with mock.patch.object(store_mod.sqlite3, 'sqlite_version_info', (3, 37, 2)), \
                mock.patch.object(store_mod.sqlite3, 'sqlite_version', '3.37.2'):
            with self.assertRaisesRegex(store_mod.UnsupportedSQLite, '3.37.2 is too old'):
                store_mod.open_store(self.db)
        self.assertFalse(self.db.exists())

    def test_tables_are_strict(self):
        store = self.open()
        strict = dict(store.conn.execute("SELECT name, strict FROM pragma_table_list WHERE schema = 'main'"))
        for table in store_mod.CANONICAL_TABLES + ('proj_cursor',):
            self.assertEqual(strict[table], 1, table)


class LocationTests(StoreTestCase):
    category = 'contract'

    def test_refuses_a_path_inside_the_repository(self):
        inside = STORE_DIR / 'tests' / 'refused-integration.sqlite'
        with self.assertRaises(store_mod.UnsafeLocation):
            store_mod.open_store(inside)
        self.assertFalse(inside.exists())

    def test_refuses_unc_memory_and_missing_parent(self):
        for bad in ('\\\\server\\share\\integration.sqlite', '//server/share/integration.sqlite',
                    ':memory:', 'file:integration.sqlite?mode=memory'):
            with self.subTest(bad=bad), self.assertRaises(store_mod.UnsafeLocation):
                store_mod.open_store(bad)
        with self.assertRaises(store_mod.UnsafeLocation):
            store_mod.open_store(self.tmp / 'missing' / 'integration.sqlite')
        self.assertFalse((self.tmp / 'missing').exists())

    def test_default_path_is_per_user_application_data_and_creates_nothing(self):
        win = store_mod.default_db_path({'LOCALAPPDATA': 'X:\\AppData\\Local'}, 'win32')
        self.assertEqual(win, Path('X:\\AppData\\Local') / 'ai-engineering-harness' / 'state' / 'integration.sqlite')
        xdg = store_mod.default_db_path({'XDG_DATA_HOME': '/data/home', 'HOME': '/h'}, 'linux')
        self.assertEqual(xdg, Path('/data/home/ai-engineering-harness/state/integration.sqlite'))
        fallback = store_mod.default_db_path({'HOME': '/h'}, 'darwin')
        self.assertEqual(fallback, Path('/h/.local/share/ai-engineering-harness/state/integration.sqlite'))
        with self.assertRaises(store_mod.UnsafeLocation):
            store_mod.default_db_path({}, 'win32')

    def test_cli_init_creates_and_reopens_at_an_explicit_path(self):
        target = self.tmp / 'nested' / 'integration.sqlite'
        cmd = [sys.executable, '-I', '-B', str(MODULE), 'init', '--db', str(target)]
        first = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=WAIT_CEILING_S)
        self.assertEqual(first.returncode, 0, first.stderr)
        summary = json.loads(first.stdout)
        self.assertEqual(summary['schema_version'], len(store_mod.load_migrations()))
        self.assertEqual(summary['pragmas']['journal_mode'], 'wal')
        second = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=WAIT_CEILING_S)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)['migrations'], summary['migrations'])
        refused = subprocess.run([sys.executable, '-I', '-B', str(MODULE), 'init', '--db',
                                  str(STORE_DIR / 'refused.sqlite')],
                                 capture_output=True, text=True, encoding='utf-8', timeout=WAIT_CEILING_S)
        self.assertEqual(refused.returncode, 1)
        self.assertIn('REFUSED', refused.stderr)
        self.assertFalse((STORE_DIR / 'refused.sqlite').exists())


class MigrationTests(StoreTestCase):
    def test_fresh_init_records_every_migration_with_its_checksum(self):
        store = self.open()
        known = store_mod.load_migrations()
        self.assertEqual(store.schema_version(), len(known))
        self.assertEqual([(v, n, s) for v, n, s, _ in store.applied_migrations()],
                         [(m.version, m.name, m.sha256) for m in known])

    def test_reopen_is_a_no_op(self):
        store = self.open()
        before = (store.canonical_dump(), store.applied_migrations())
        store.close()
        again = self.open()
        self.assertEqual((again.canonical_dump(), again.applied_migrations()), before)

    def test_tampered_applied_migration_is_refused(self):
        migrations = self.copy_migrations()
        self.open(migrations_dir=migrations).close()
        path = migrations / '0001_receipts_and_projections.sql'
        path.write_text(path.read_text(encoding='utf-8') + '\n-- edited after it was applied\n',
                        encoding='utf-8')
        with self.assertRaisesRegex(store_mod.MigrationError, 'has changed'):
            store_mod.open_store(self.db, migrations_dir=migrations)

    def test_crlf_checkout_has_the_same_checksum(self):
        migrations = self.copy_migrations()
        path = migrations / '0001_receipts_and_projections.sql'
        path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
        self.open().close()
        self.open(migrations_dir=migrations)  # recorded from the LF files; opens unchanged

    def test_future_schema_version_is_refused(self):
        migrations = self.copy_migrations()
        current = len(store_mod.load_migrations())
        (migrations / f'{current + 1:04d}_future.sql').write_text(
            'CREATE TABLE future_thing (id INTEGER PRIMARY KEY) STRICT;\n', encoding='utf-8')
        with self.open(migrations_dir=migrations) as newer:
            self.assertEqual(newer.schema_version(), current + 1)
        with self.assertRaisesRegex(store_mod.MigrationError, 'newer than this code knows'):
            store_mod.open_store(self.db)  # the code's own migrations know only up to `current`

    def test_raw_future_user_version_is_refused(self):
        self.open().close()
        raw = sqlite3.connect(self.db)
        raw.execute('PRAGMA user_version = 99')
        raw.close()
        with self.assertRaisesRegex(store_mod.MigrationError, 'newer than this code knows'):
            store_mod.open_store(self.db)

    def test_pending_migration_applies_and_a_failing_one_rolls_back_entirely(self):
        migrations = self.copy_migrations()
        current = len(store_mod.load_migrations())
        self.open(migrations_dir=migrations).close()
        (migrations / f'{current + 1:04d}_broken.sql').write_text(
            'CREATE TABLE half_done (id INTEGER PRIMARY KEY) STRICT;\n'
            'INSERT INTO no_such_table VALUES (1);\n', encoding='utf-8')
        with self.assertRaises(sqlite3.OperationalError):
            store_mod.open_store(self.db, migrations_dir=migrations)
        with self.open() as store:
            self.assertEqual(store.schema_version(), current)
            self.assertIsNone(store.conn.execute(
                "SELECT name FROM sqlite_schema WHERE name = 'half_done'").fetchone())
        (migrations / f'{current + 1:04d}_broken.sql').unlink()
        (migrations / f'{current + 1:04d}_fixed.sql').write_text(
            'CREATE TABLE later_thing (id INTEGER PRIMARY KEY) STRICT;\n', encoding='utf-8')
        with self.assertRaisesRegex(store_mod.MigrationError, f'version {current}; {current + 1} expected'):
            store_mod.open_store(self.db, migrations_dir=migrations, apply_migrations=False)
        with self.open(migrations_dir=migrations) as store:
            self.assertEqual(store.schema_version(), current + 1)

    def test_foreign_database_is_refused(self):
        raw = sqlite3.connect(self.db)
        raw.execute('CREATE TABLE something_else (x)')
        raw.close()
        with self.assertRaisesRegex(store_mod.MigrationError, 'not an integration store'):
            store_mod.open_store(self.db)

    def test_statement_splitter_keeps_trigger_bodies_and_quoted_semicolons(self):
        statements = store_mod.split_statements(
            "-- a comment; with a semicolon\nCREATE TABLE t (x TEXT);\n"
            "INSERT INTO t VALUES ('a;b');\n"
            "CREATE TRIGGER g BEFORE DELETE ON t BEGIN SELECT RAISE(ABORT, 'no; never'); END;\n")
        self.assertEqual(len(statements), 3)
        self.assertTrue(statements[2].endswith('END;'))


class ReservationTests(StoreTestCase):
    category = 'integration'

    def test_reserve_commits_key_intent_digest_and_conversation_id(self):
        store = self.open()
        result = store.reserve('op-1', INTENT, actor='test')
        self.assertTrue(result.created)
        r = result.reservation
        self.assertEqual(r.state, 'reserved')
        self.assertEqual(r.reconciliation_status, 'none')
        self.assertEqual(r.intent_digest, hashlib.sha256(store_mod.canonical_intent(INTENT).encode()).hexdigest())
        self.assertEqual(json.loads(r.intent_json), INTENT)
        self.assertEqual(r.conversation_id, store_mod.conversation_id_for('op-1'))
        [event] = store.events('op-1')
        self.assertEqual((event.seq, event.from_state, event.to_state, event.actor), (0, None, 'reserved', 'test'))

    def test_same_intent_is_idempotent_whatever_the_key_order(self):
        store = self.open()
        first = store.reserve('op-1', INTENT, actor='a')
        reordered = json.loads(json.dumps(INTENT), object_pairs_hook=lambda kv: dict(reversed(kv)))
        again = store.reserve('op-1', reordered, actor='b')
        self.assertFalse(again.created)
        self.assertEqual(again.reservation, first.reservation)
        self.assertEqual(len(store.events('op-1')), 1)

    def test_conflicting_duplicate_is_refused_and_changes_nothing(self):
        store = self.open()
        store.reserve('op-1', INTENT, actor='a')
        before = store.canonical_dump()
        with self.assertRaises(store_mod.ConflictingReservation):
            store.reserve('op-1', {**INTENT, 'request': {'agent': 'other'}}, actor='b')
        self.assertEqual(store.canonical_dump(), before)
        self.assertFalse(store.conn.in_transaction)

    def test_conversation_id_is_pinned_and_stable_across_processes(self):
        self.assertEqual(store_mod.conversation_id_for(GOLDEN_KEY), GOLDEN_CONVERSATION_ID)
        for _ in range(2):
            code, [message], err = run_worker('conversation-id', str(self.db), GOLDEN_KEY)
            self.assertEqual(code, 0, err)
            self.assertEqual(message['conversation_id'], GOLDEN_CONVERSATION_ID)
        self.assertFalse(self.db.exists())

    def test_conversation_id_is_unique_in_the_schema(self):
        store = self.open()
        store.reserve('op-1', INTENT, actor='a')
        with self.assertRaises(sqlite3.IntegrityError):
            store.conn.execute(
                "INSERT INTO attempt (operation_key, intent_digest, intent_json, conversation_id, "
                "created_at, updated_at) VALUES ('op-2', ?, '{}', ?, 'now', 'now')",
                ('0' * 64, store_mod.conversation_id_for('op-1')))

    def test_bad_keys_and_intents_are_refused(self):
        store = self.open()
        for key in ('', 'x' * 513, 7):
            with self.subTest(key=key), self.assertRaises(store_mod.StoreError):
                store.reserve(key, INTENT, actor='a')
        for intent in (['not', 'an', 'object'], {'x': float('nan')}, {'x': object()}):
            with self.subTest(intent=intent), self.assertRaises(store_mod.StoreError):
                store.reserve('op-1', intent, actor='a')
        self.assertEqual(store.attempts(), [])


class RestartAndCrashTests(StoreTestCase):
    category = 'integration'

    def test_restart_retains_a_reserved_receipt(self):
        store_mod.open_store(self.db).close()  # initialise; the worker then reserves
        code, [reserved], err = run_worker('reserve-and-exit', str(self.db), 'op-restart', json.dumps(INTENT))
        self.assertEqual(code, 0, err)
        self.assertTrue(reserved['created'])
        # The worker hard-exited with its connection open: the commit lives in the WAL.
        wal = Path(str(self.db) + '-wal')
        self.assertTrue(wal.exists() and wal.stat().st_size > 0)

        code, [seen], err = run_worker('get', str(self.db), 'op-restart')
        self.assertEqual(code, 0, err)
        self.assertEqual(seen['reservation'], reserved['reservation'])
        self.assertEqual(seen['reservation']['state'], 'reserved')
        self.assertEqual(seen['reservation']['conversation_id'], store_mod.conversation_id_for('op-restart'))
        self.assertEqual([e['to_state'] for e in seen['events']], ['reserved'])

        with self.open() as store:
            self.assertEqual(dataclasses.asdict(store.get('op-restart')), reserved['reservation'])

    def test_kill_inside_an_open_write_transaction_leaves_no_partial_reservation(self):
        store_mod.open_store(self.db).close()
        proc = start_worker('hold-uncommitted', str(self.db), 'op-partial', json.dumps(INTENT))
        try:
            message = read_message(proc)
            self.assertEqual(message, {'ready': True, 'in_transaction': True})
        finally:
            proc.kill()
            proc.wait(timeout=WAIT_CEILING_S)
            proc.stdout.close(), proc.stderr.close(), proc.stdin.close()
        self.assertNotEqual(proc.returncode, 3)  # killed, not its own exit
        with self.open() as store:
            self.assertIsNone(store.get('op-partial'))
            self.assertEqual(store.events('op-partial'), [])
            store.reserve('op-after', INTENT, actor='test')  # the write lock was released


class ContentionTests(StoreTestCase):
    category = 'integration'

    def contend(self, intents):
        store_mod.open_store(self.db).close()
        procs = [start_worker('contend', str(self.db), 'op-contended', json.dumps(intent)) for intent in intents]
        try:
            for proc in procs:
                self.assertEqual(read_message(proc), {'ready': True})
            for proc in procs:  # all are open and waiting: release them together
                proc.stdin.write('go\n')
                proc.stdin.flush()
            outcomes = [read_message(proc) for proc in procs]
            for proc in procs:
                self.assertEqual(proc.wait(timeout=WAIT_CEILING_S), 0, proc.stderr.read())
        finally:
            for proc in procs:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=WAIT_CEILING_S)
                proc.stdout.close(), proc.stderr.close(), proc.stdin.close()
        return outcomes

    def test_same_digest_from_many_processes_yields_one_reservation(self):
        outcomes = self.contend([INTENT] * CONTENDERS)
        self.assertEqual(sorted(o['outcome'] for o in outcomes),
                         ['created'] + ['existing'] * (CONTENDERS - 1))
        self.assertEqual({o['conversation_id'] for o in outcomes},
                         {store_mod.conversation_id_for('op-contended')})
        with self.open() as store:
            self.assertEqual(store.conn.execute('SELECT count(*) FROM attempt').fetchone()[0], 1)
            self.assertEqual(len(store.events('op-contended')), 1)

    def test_different_digests_from_many_processes_one_wins_the_rest_conflict(self):
        intents = [{**INTENT, 'request': {'variant': i}} for i in range(CONTENDERS)]
        outcomes = self.contend(intents)
        self.assertEqual(sorted(o['outcome'] for o in outcomes), ['conflict'] * (CONTENDERS - 1) + ['created'])
        winner = intents[[o['outcome'] for o in outcomes].index('created')]
        with self.open() as store:
            self.assertEqual(store.conn.execute('SELECT count(*) FROM attempt').fetchone()[0], 1)
            self.assertEqual(store.get('op-contended').intent_digest, store_mod.intent_digest(winner))
            self.assertEqual(len(store.events('op-contended')), 1)


class TransitionTests(StoreTestCase):
    def test_legal_path_appends_history_and_tracks_reconciliation(self):
        store = self.open()
        store.reserve('op-1', INTENT, actor='reserver')
        store.transition('op-1', 'dispatched', actor='dispatcher', reason='create sent')
        store.transition('op-1', 'unknown', actor='dispatcher', reason='acknowledgement lost')
        self.assertEqual(store.get('op-1').reconciliation_status, 'required')
        final = store.transition('op-1', 'confirmed', actor='reconciler', expected_from='unknown',
                                 detail={'observed_conversation_id': store.get('op-1').conversation_id})
        self.assertEqual((final.state, final.reconciliation_status, final.state_seq),
                         ('confirmed', 'reconciled', 3))
        events = store.events('op-1')
        self.assertEqual([(e.seq, e.from_state, e.to_state, e.reconciliation_status, e.actor) for e in events], [
            (0, None, 'reserved', 'none', 'reserver'),
            (1, 'reserved', 'dispatched', 'none', 'dispatcher'),
            (2, 'dispatched', 'unknown', 'required', 'dispatcher'),
            (3, 'unknown', 'confirmed', 'reconciled', 'reconciler'),
        ])
        self.assertEqual(json.loads(events[3].detail_json)['observed_conversation_id'], final.conversation_id)

    def test_every_transition_outside_the_allowed_set_is_refused(self):
        self.assertEqual(store_mod.TRANSITIONS, frozenset(self.open().conn.execute(
            'SELECT from_state, to_state FROM attempt_transition').fetchall()))
        paths = {'reserved': [], 'dispatched': ['dispatched'], 'unknown': ['dispatched', 'unknown'],
                 'confirmed': ['dispatched', 'confirmed'], 'failed': ['failed']}
        store = self.open()
        for i, (state, path) in enumerate(paths.items()):
            key = f'op-{i}'
            store.reserve(key, INTENT, actor='t')
            for step in path:
                store.transition(key, step, actor='t')
            for target in store_mod.STATES:
                if (state, target) in store_mod.TRANSITIONS:
                    continue
                before = store.canonical_dump()
                with self.subTest(source=state, target=target), self.assertRaises(store_mod.IllegalTransition):
                    store.transition(key, target, actor='t')
                self.assertEqual(store.canonical_dump(), before)
        with self.assertRaises(store_mod.IllegalTransition):
            store.transition('op-0', 'dispatched', actor='t', expected_from='dispatched')
        with self.assertRaises(store_mod.UnknownAttempt):
            store.transition('no-such-op', 'dispatched', actor='t')
        with self.assertRaises(store_mod.IllegalTransition):
            store.transition('op-0', 'cancelled', actor='t')

    def test_schema_enforces_transitions_append_only_history_and_no_deletes(self):
        store = self.open()
        store.reserve('op-1', INTENT, actor='t')
        store.transition('op-1', 'dispatched', actor='t')
        conn = store.conn
        refused = [
            "UPDATE attempt SET state = 'reserved' WHERE operation_key = 'op-1'",
            "UPDATE attempt SET state = 'bogus' WHERE operation_key = 'op-1'",
            "UPDATE attempt SET conversation_id = '00000000-0000-0000-0000-000000000000'",
            "UPDATE attempt SET intent_digest = '" + 'f' * 64 + "'",
            "UPDATE attempt SET reconciliation_status = 'required'",
            "DELETE FROM attempt",
            "UPDATE attempt_event SET actor = 'someone else'",
            "DELETE FROM attempt_event",
            "INSERT INTO attempt_event (operation_key, seq, from_state, to_state, reconciliation_status, "
            "actor, recorded_at) VALUES ('op-1', 9, 'confirmed', 'reserved', 'none', 't', 'now')",
            "INSERT INTO attempt_transition VALUES ('confirmed', 'reserved')",
            "DELETE FROM attempt_state WHERE state = 'unknown'",
        ]
        before = store.canonical_dump()
        for sql in refused:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                conn.execute(sql)
        self.assertEqual(store.canonical_dump(), before)


def fake_projection(source_rows, cursor, populate=None, ddl=None, tables=('proj_fake', 'proj_fake_tag')):
    def default_populate(conn):
        for item_id, title, tags in source_rows:
            conn.execute('INSERT INTO proj_fake (item_id, title) VALUES (?, ?)', (item_id, title))
            for tag in tags:
                conn.execute('INSERT INTO proj_fake_tag (item_id, tag) VALUES (?, ?)', (item_id, tag))
        return cursor, {'items': len(source_rows), 'complete': True}
    return store_mod.Projection(
        name='fake', source='fake-source', tables=tables,
        ddl=ddl or ('CREATE TABLE proj_fake (item_id TEXT PRIMARY KEY, title TEXT NOT NULL) STRICT',
                    'CREATE TABLE proj_fake_tag (item_id TEXT NOT NULL, tag TEXT NOT NULL, '
                    'PRIMARY KEY (item_id, tag)) STRICT',
                    'CREATE INDEX proj_fake_tag_by_tag ON proj_fake_tag (tag)'),
        populate=populate or default_populate)


class ProjectionTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.store = self.open()
        self.store.reserve('op-1', INTENT, actor='t')
        self.store.transition('op-1', 'dispatched', actor='t')
        self.store.reserve('op-2', {**INTENT, 'n': 2}, actor='t')
        self.before = self.store.canonical_dump()
        self.before_digest = hashlib.sha256(self.before).hexdigest()

    def assert_canonical_unchanged(self):
        after = self.store.canonical_dump()
        self.assertEqual(after, self.before)
        self.assertEqual(hashlib.sha256(after).hexdigest(), self.before_digest)

    def projected(self):
        return (self.store.conn.execute('SELECT item_id, title FROM proj_fake ORDER BY item_id').fetchall(),
                self.store.conn.execute('SELECT item_id, tag FROM proj_fake_tag ORDER BY 1, 2').fetchall())

    def test_rebuild_leaves_receipts_and_events_byte_for_byte_unchanged(self):
        rows = [('a', 'Alpha', ['x', 'y']), ('b', 'Beta', [])]
        self.store.rebuild_projection(fake_projection(rows, 'cursor-1'))
        self.assert_canonical_unchanged()
        self.assertEqual(self.projected(), ([('a', 'Alpha'), ('b', 'Beta')], [('a', 'x'), ('a', 'y')]))
        name, source, cursor, coverage, _ = self.store.projection_cursor('fake')
        self.assertEqual((name, source, cursor, json.loads(coverage)),
                         ('fake', 'fake-source', 'cursor-1', {'complete': True, 'items': 2}))

        changed = [('b', 'Beta 2', ['z']), ('c', 'Gamma', [])]
        self.store.rebuild_projection(fake_projection(changed, 'cursor-2'))
        self.assert_canonical_unchanged()
        self.assertEqual(self.projected(), ([('b', 'Beta 2'), ('c', 'Gamma')], [('b', 'z')]))
        self.assertEqual(self.store.projection_cursor('fake')[2], 'cursor-2')

    def test_rebuild_that_touches_canonical_data_is_refused_and_rolled_back(self):
        self.store.rebuild_projection(fake_projection([('a', 'Alpha', [])], 'cursor-1'))
        good = self.projected()
        attacks = {
            'delete receipts': "DELETE FROM attempt",
            'update receipts': "UPDATE attempt SET state = 'failed'",
            'insert event': "INSERT INTO attempt_event (operation_key, seq, to_state, reconciliation_status, "
                            "actor, recorded_at) VALUES ('op-2', 5, 'reserved', 'none', 'x', 'now')",
            'drop canonical': "DROP TABLE attempt_event",
            'drop trigger': "DROP TRIGGER attempt_no_delete",
            'create trigger': "CREATE TRIGGER proj_fake_t AFTER INSERT ON proj_fake "
                              "BEGIN DELETE FROM attempt; END",
            'writable schema': "PRAGMA writable_schema = ON",
            'commit early': "COMMIT",
            'attach': "ATTACH DATABASE ':memory:' AS other",
            'other projection': "CREATE TABLE proj_other (x) STRICT",
        }
        for label, sql in attacks.items():
            def populate(conn, sql=sql):
                conn.execute('INSERT INTO proj_fake (item_id, title) VALUES (?, ?)', ('evil', 'Evil'))
                conn.execute(sql)
                return 'never', {}
            with self.subTest(label):
                with self.assertRaises(store_mod.ProjectionError):
                    self.store.rebuild_projection(fake_projection([], 'x', populate=populate))
                self.assertFalse(self.store.conn.in_transaction)
                self.assert_canonical_unchanged()
                self.assertEqual(self.projected(), good)
                self.assertEqual(self.store.projection_cursor('fake')[2], 'cursor-1')

    def test_projection_ddl_and_ownership_are_checked(self):
        with self.assertRaises(store_mod.ProjectionError):
            self.store.rebuild_projection(fake_projection([], 'x', ddl=(
                'CREATE TABLE proj_fake (item_id TEXT PRIMARY KEY, title TEXT) STRICT',
                'CREATE TABLE sneaky (x) STRICT')))
        for tables in (('attempt',), ('proj_other',), ('proj_fake', 'proj_fake_tag', 'proj_cursor'), ()):
            with self.subTest(tables=tables), self.assertRaises(store_mod.ProjectionError):
                self.store.rebuild_projection(fake_projection([], 'x', tables=tables))
        self.assert_canonical_unchanged()
        self.assertIsNone(self.store.conn.execute(
            "SELECT name FROM sqlite_schema WHERE name IN ('sneaky', 'proj_fake')").fetchone())

    def test_fts5_projection_can_be_rebuilt(self):
        try:
            sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(body)')
        except sqlite3.OperationalError:
            self.skipTest('this SQLite build has no FTS5')

        def populate(conn):
            conn.execute("INSERT INTO proj_search (key, body) VALUES ('a', 'reserved receipt')")
            return 'c1', {'documents': 1}
        projection = store_mod.Projection(
            name='search', source='fake-source', tables=('proj_search',),
            ddl=('CREATE VIRTUAL TABLE proj_search USING fts5(key UNINDEXED, body)',), populate=populate)
        self.store.rebuild_projection(projection)
        self.store.rebuild_projection(projection)
        self.assertEqual(self.store.conn.execute(
            "SELECT key FROM proj_search WHERE proj_search MATCH 'receipt'").fetchall(), [('a',)])
        self.assert_canonical_unchanged()


if __name__ == '__main__':
    unittest.main()
