"""Crash, restart and concurrent-admission tests for typed reservations (plan leaf E-01.1.2).

Run from the repository root:

    python -I -B -m unittest discover -s integrations/store/tests -v

Every database lives in a fresh temporary directory outside the checkout. The crashes
are real processes (store_worker.py ``scripted``): the worker runs the real library
calls and stops at one SQL statement boundary, by ``os._exit`` (no rollback, no close,
no checkpoint) or by blocking until this test kills it. Only processes this test
started are ever killed. The parent waits on each worker's own output and exit, never
on a fixed sleep.
"""
from pathlib import Path
import dataclasses
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
STORE_DIR = HERE.parent
MODULE = STORE_DIR / 'integration_store.py'
WORKER = HERE / 'store_worker.py'

if 'integration_store' in sys.modules:
    store_mod = sys.modules['integration_store']
else:
    _spec = importlib.util.spec_from_file_location('integration_store', MODULE)
    store_mod = importlib.util.module_from_spec(_spec)
    sys.modules['integration_store'] = store_mod
    _spec.loader.exec_module(store_mod)
storecore = store_mod.storecore

WAIT_CEILING_S = 60  # bounds a hang; workers normally finish in well under a second
CONTENDERS = 8
NEWLINE = chr(10)
CRASH_EXIT, HOLD_EXIT = 9, 3

C40 = '8eacfa81953a9129f3a8ee4c943f3030fd1c4fb7'
DESIGN = f'openspec:changes/qual-02-search-freshness@{C40}'
BASE = {'work_id': 'TASK-1', 'design_revision': DESIGN, 'stage': 'implement', 'ordinal': 1,
        'profile_digest': hashlib.sha256(b'profile.json').hexdigest(),
        'planned_workspace': 'work/TASK-1/attempt-1', 'policy_digest': hashlib.sha256(b'policy').hexdigest()}
INTENT = {'outcomeRef': 'outcome:5c6f4c1e-8d3a-4a3b-9b2e-1f0e7d6c5b4a', 'request': {'agent': 'engineer'}}


def ident(**override):
    return store_mod.AttemptIdentity(**{**BASE, **override})


def fields(identity):
    return {f.name: getattr(identity, f.name) for f in dataclasses.fields(identity)}


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


def finish(procs):
    for proc in procs:
        if proc.poll() is None:
            proc.kill()  # only a worker this test started
            proc.wait(timeout=WAIT_CEILING_S)
        proc.stdout.close(), proc.stderr.close(), proc.stdin.close()


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-crash-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = self.tmp / 'integration.sqlite'
        store_mod.open_store(self.db).close()  # created and migrated; the WAL is checkpointed away

    def wal_size(self):
        wal = Path(str(self.db) + '-wal')
        return wal.stat().st_size if wal.exists() else 0

    def assert_store_verifies(self):
        """Integrity, foreign keys, current migrations and the store kind's own invariants."""
        with store_mod.open_store(self.db, apply_migrations=False) as store:
            conn = store.conn
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])
            storecore.check_current(conn, store_mod.KIND)
            store_mod.KIND.verify(conn)
            live = conn.execute('SELECT work_id, design_revision, stage, count(*) FROM attempt_identity '
                                'WHERE live = 1 GROUP BY 1, 2, 3 HAVING count(*) > 1').fetchall()
            self.assertEqual(live, [])

    def assert_same_identity(self, message, identity):
        """A reservation message carries the identity's derived key, IDs and revision."""
        key = identity.operation_key
        self.assertEqual(message['reservation']['operation_key'], key)
        self.assertEqual(message['reservation']['conversation_id'], store_mod.conversation_id_for(key))
        self.assertEqual(message['attempt']['attempt_id'], store_mod.attempt_id_for(key))
        self.assertEqual(message['attempt']['identity']['design_revision'], identity.design_revision)
        self.assertEqual(message['attempt']['identity'], fields(identity))


# ---------------------------------------------------------------------------
# The crash matrix

# (label, steps, crash, persisted state or None, persisted event states, live or None)
# A crash is STEP|before-or-after|statement prefix|exit-or-hold (store_worker.py scripted).
MATRIX = [
    ('reserve: before the library call', 'reserve', '0|before|CALL|exit', None, [], None),
    ('reserve: at BEGIN IMMEDIATE', 'reserve', '0|before|BEGIN IMMEDIATE|exit', None, [], None),
    ('reserve: after the identity row, before the attempt row', 'reserve',
     '0|after|INSERT INTO attempt_identity|exit', None, [], None),
    ('reserve: killed holding the write lock after the identity row', 'reserve',
     '0|after|INSERT INTO attempt_identity|hold', None, [], None),
    ('reserve: after the attempt row, before its event', 'reserve',
     '0|after|INSERT INTO attempt (|exit', None, [], None),
    ('reserve: every row written, before COMMIT', 'reserve', '0|before|COMMIT|exit', None, [], None),
    ('reserve: after COMMIT, before the caller sees the result', 'reserve', '0|after|COMMIT|exit',
     'reserved', ['reserved'], True),
    ('dispatch: before the library call', 'reserve,dispatched', '1|before|CALL|exit',
     'reserved', ['reserved'], True),
    ('dispatch: after the state update, before its event', 'reserve,dispatched',
     '1|after|UPDATE attempt SET state|exit', 'reserved', ['reserved'], True),
    ('dispatch: killed holding the write lock before COMMIT', 'reserve,dispatched', '1|before|COMMIT|hold',
     'reserved', ['reserved'], True),
    ('dispatch: after COMMIT', 'reserve,dispatched', '1|after|COMMIT|exit',
     'dispatched', ['reserved', 'dispatched'], True),
    ('dispatched, before confirmed or unknown', 'reserve,dispatched,confirmed', '2|before|CALL|exit',
     'dispatched', ['reserved', 'dispatched'], True),
    ('confirm: after the state update (live 0 inside the transaction), before its event',
     'reserve,dispatched,confirmed', '2|after|UPDATE attempt SET state|exit',
     'dispatched', ['reserved', 'dispatched'], True),
    ('confirm: after its event, before COMMIT', 'reserve,dispatched,confirmed',
     '2|after|INSERT INTO attempt_event|exit', 'dispatched', ['reserved', 'dispatched'], True),
    ('confirm: after COMMIT', 'reserve,dispatched,confirmed', '2|after|COMMIT|exit',
     'confirmed', ['reserved', 'dispatched', 'confirmed'], False),
    ('unknown: after the state update, before its event', 'reserve,dispatched,unknown',
     '2|after|UPDATE attempt SET state|exit', 'dispatched', ['reserved', 'dispatched'], True),
    ('unknown: after COMMIT', 'reserve,dispatched,unknown', '2|after|COMMIT|exit',
     'unknown', ['reserved', 'dispatched', 'unknown'], True),
    ('fail before any call: before COMMIT', 'reserve,failed', '1|before|COMMIT|exit',
     'reserved', ['reserved'], True),
    ('fail before any call: after COMMIT', 'reserve,failed', '1|after|COMMIT|exit',
     'failed', ['reserved', 'failed'], False),
]


class CrashMatrixTests(StoreTestCase):
    """Each row: crash a real process at one statement, reopen, and check what persisted."""

    def crash(self, steps, crash):
        proc = start_worker('scripted', str(self.db), json.dumps(BASE), json.dumps(INTENT), steps, crash)
        try:
            messages = []
            while True:
                message = read_message(proc)
                messages.append(message)
                if 'crashed_at' in message or 'error' in message:
                    break
            self.assertEqual(messages[-1].get('crashed_at'), crash, messages)
            if crash.endswith('|hold'):
                proc.kill()  # the worker this test started, blocked inside the transaction
            code = proc.wait(timeout=WAIT_CEILING_S)
        finally:
            finish([proc])
        self.assertNotEqual(code, 0)
        if not crash.endswith('|hold'):
            self.assertEqual(code, CRASH_EXIT, proc)
        return messages

    def test_crash_matrix(self):
        identity = ident()
        key = identity.operation_key
        for label, steps, crash, state, events, live in MATRIX:
            with self.subTest(label):
                self.setUp()  # a fresh store per row
                messages = self.crash(steps, crash)
                committed_in_worker = [m for m in messages if 'done' in m]
                if state is not None and committed_in_worker:
                    # the commits are in a WAL nobody checkpointed: they must survive the reopen
                    self.assertGreater(self.wal_size(), 0)

                # 1. What persisted, read by a fresh process.
                code, [seen], err = run_worker('get', str(self.db), key)
                self.assertEqual(code, 0, err)
                if state is None:
                    self.assertIsNone(seen['reservation'])
                    self.assertIsNone(seen['attempt'])
                    self.assertEqual(seen['events'], [])
                else:
                    self.assertEqual(seen['reservation']['state'], state)
                    self.assertEqual([e['to_state'] for e in seen['events']], events)
                    self.assertEqual(seen['reservation']['state_seq'], len(events) - 1)
                    self.assertEqual(seen['attempt']['live'], live)
                    self.assert_same_identity(seen, identity)
                with store_mod.open_store(self.db) as store:
                    counts = [store.conn.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
                              for t in ('attempt', 'attempt_identity', 'attempt_event')]
                self.assertEqual(counts, [0, 0, 0] if state is None else [1, 1, len(events)])
                self.assert_store_verifies()

                # 2. An identical re-request, in another process.
                code, [again], err = run_worker('reserve-attempt', str(self.db), json.dumps(BASE),
                                                json.dumps(INTENT))
                self.assertEqual(code, 0, err)
                self.assertEqual(again['outcome'], 'created' if state is None else 'existing')
                self.assert_same_identity(again, identity)
                self.assertEqual(again['reservation']['state'], state or 'reserved')

                # 3. The claim rule after the crash: the next ordinal only once it is terminal.
                with store_mod.open_store(self.db) as store:
                    if state in (None, 'reserved', 'dispatched', 'unknown'):
                        with self.assertRaises(store_mod.LiveClaim):
                            store.reserve_attempt(ident(ordinal=2), INTENT, actor='t')
                    else:
                        self.assertTrue(store.reserve_attempt(ident(ordinal=2), INTENT, actor='t').created)
                self.assert_store_verifies()

    def test_killed_writer_releases_the_lock(self):
        """A kill inside the reservation transaction leaves nothing, and the next writer proceeds."""
        self.crash('reserve', '0|after|INSERT INTO attempt (|hold')
        with store_mod.open_store(self.db, busy_timeout_ms=2000) as store:
            result = store.reserve_attempt(ident(), INTENT, actor='after-kill')
            self.assertTrue(result.created)
            self.assertEqual([e.actor for e in store.events(result.reservation.operation_key)], ['after-kill'])
        self.assert_store_verifies()


# ---------------------------------------------------------------------------
# Restart semantics

class RestartTests(StoreTestCase):
    def test_restart_finds_the_same_uuid_and_revision(self):
        identity = ident()
        # Reserve and dispatch in one process that exits without closing (WAL not checkpointed).
        code, messages, err = run_worker('scripted', str(self.db), json.dumps(BASE), json.dumps(INTENT),
                                         'reserve,dispatched', 'none')
        self.assertEqual(code, 0, err)
        self.assertEqual([m['done'] for m in messages], ['reserve', 'dispatched'])
        self.assertGreater(self.wal_size(), 0)

        # A new process: attempts() and the identity lookup.
        code, [listed], err = run_worker('attempts', str(self.db))
        self.assertEqual(code, 0, err)
        [entry] = listed['attempts']
        self.assert_same_identity(entry, identity)
        self.assertEqual(entry['reservation']['state'], 'dispatched')
        code, [seen], err = run_worker('get', str(self.db), identity.operation_key)
        self.assertEqual(code, 0, err)
        self.assertEqual((seen['reservation'], seen['attempt']), (entry['reservation'], entry['attempt']))

        # Reopened here, after a clean close, and once more: the same answer and the same bytes.
        dumps = []
        for _ in range(2):
            with store_mod.open_store(self.db) as store:
                [reservation] = store.attempts()
                self.assertEqual(dataclasses.asdict(reservation), entry['reservation'])
                self.assertEqual(dataclasses.asdict(store.attempt_identity(identity.operation_key)),
                                 entry['attempt'])
                dumps.append(store.canonical_dump())
        self.assertEqual(dumps[0], dumps[1])
        self.assertEqual(self.wal_size(), 0)  # the clean close checkpointed it
        self.assert_store_verifies()

    def test_restart_after_each_lifecycle_state(self):
        for path in ('reserve', 'reserve,dispatched', 'reserve,dispatched,unknown',
                     'reserve,dispatched,unknown,confirmed', 'reserve,failed'):
            with self.subTest(path=path):
                self.setUp()
                code, _, err = run_worker('scripted', str(self.db), json.dumps(BASE), json.dumps(INTENT),
                                          path, 'none')
                self.assertEqual(code, 0, err)
                code, [again], err = run_worker('reserve-attempt', str(self.db), json.dumps(BASE),
                                                json.dumps(INTENT))
                self.assertEqual(code, 0, err)
                self.assertEqual(again['outcome'], 'existing')
                self.assertEqual(again['reservation']['state'], path.split(',')[-1].replace('reserve', 'reserved'))
                self.assert_same_identity(again, ident())
                self.assert_store_verifies()


# ---------------------------------------------------------------------------
# Concurrent admission

class ConcurrencyTests(StoreTestCase):
    def race(self, commands):
        """Start every worker, wait until each is open and ready, release them together."""
        procs = [start_worker(*command) for command in commands]
        try:
            for proc in procs:
                self.assertEqual(read_message(proc), {'ready': True})
            for proc in procs:
                proc.stdin.write('go' + NEWLINE)
                proc.stdin.flush()
            outcomes = [read_message(proc) for proc in procs]
            for proc in procs:
                self.assertEqual(proc.wait(timeout=WAIT_CEILING_S), 0, proc.stderr.read())
        finally:
            finish(procs)
        self.assertEqual([o for o in outcomes if o['outcome'].startswith('raw:')], [])  # no SQLITE_BUSY, no raw error
        return outcomes

    def contend_attempt(self, identity, intent=INTENT):
        return ('contend-attempt', str(self.db), json.dumps(fields(identity)), json.dumps(intent))

    def live_rows(self):
        with store_mod.open_store(self.db) as store:
            return store.conn.execute('SELECT operation_key FROM attempt_identity WHERE live = 1 '
                                      'ORDER BY operation_key').fetchall()

    def test_identical_requests_resolve_to_one_reserved_key(self):
        outcomes = self.race([self.contend_attempt(ident())] * CONTENDERS)
        self.assertEqual(sorted(o['outcome'] for o in outcomes), ['created'] + ['existing'] * (CONTENDERS - 1))
        for outcome in outcomes:
            self.assert_same_identity(outcome, ident())
        self.assertEqual(self.live_rows(), [(ident().operation_key,)])
        self.assert_store_verifies()

    def test_competing_ordinals_give_exactly_one_live_claim(self):
        outcomes = self.race([self.contend_attempt(ident(ordinal=n)) for n in range(1, CONTENDERS + 1)])
        self.assertEqual(outcomes[0]['outcome'], 'created')  # only ordinal 1 can ever be admitted first
        for outcome in outcomes[1:]:
            self.assertIn(outcome['outcome'], ('LiveClaim', 'OrdinalOutOfSequence'))
        self.assertEqual(self.live_rows(), [(ident().operation_key,)])
        self.assert_store_verifies()

    def test_competing_ordinals_after_a_terminal_one(self):
        with store_mod.open_store(self.db) as store:
            store.transition(store.reserve_attempt(ident(), INTENT, actor='t').reservation.operation_key,
                             'failed', actor='t')
        outcomes = self.race([self.contend_attempt(ident(ordinal=n)) for n in range(1, CONTENDERS + 1)])
        self.assertEqual(outcomes[0]['outcome'], 'existing')  # ordinal 1 is its existing key
        self.assertEqual(outcomes[1]['outcome'], 'created')   # ordinal 2 is the only admissible one
        for outcome in outcomes[2:]:
            self.assertIn(outcome['outcome'], ('LiveClaim', 'OrdinalOutOfSequence'))
        self.assertEqual(self.live_rows(), [(ident(ordinal=2).operation_key,)])
        self.assert_store_verifies()

    def test_same_ordinal_with_different_intents_one_wins(self):
        outcomes = self.race([self.contend_attempt(ident(planned_workspace=f'work/TASK-1/w{n}'))
                              for n in range(CONTENDERS)])
        self.assertEqual(sorted(o['outcome'] for o in outcomes),
                         ['ConflictingReservation'] * (CONTENDERS - 1) + ['created'])
        self.assertEqual(len(self.live_rows()), 1)
        self.assert_store_verifies()

    def test_different_triples_all_succeed(self):
        identities = [ident(work_id=f'TASK-{n}') for n in range(1, CONTENDERS // 2 + 1)]
        identities += [ident(work_id=f'TASK-{n}', stage='review') for n in range(1, CONTENDERS // 2 + 1)]
        outcomes = self.race([self.contend_attempt(i) for i in identities])
        self.assertEqual([o['outcome'] for o in outcomes], ['created'] * CONTENDERS)
        self.assertEqual(sorted(self.live_rows()), sorted((i.operation_key,) for i in identities))
        self.assert_store_verifies()

    def test_reserve_races_the_transition_that_frees_the_triple(self):
        key = ident().operation_key
        with store_mod.open_store(self.db) as store:
            store.reserve_attempt(ident(), INTENT, actor='t')
            store.transition(key, 'dispatched', actor='t')
        # The reservers are released first and the transition last, so both orders occur.
        commands = [self.contend_attempt(ident(ordinal=2))] * (CONTENDERS - 1)
        commands += [('contend-transition', str(self.db), key, 'confirmed', 'dispatched')]
        outcomes = self.race(commands)
        self.assertEqual(outcomes[-1], {'outcome': 'transitioned', 'state': 'confirmed'})
        reservers = sorted(o['outcome'] for o in outcomes[:-1])
        created = reservers.count('created')
        # Before the transition commits a reserver sees a live claim; after it, exactly one
        # reserver creates ordinal 2 and the later ones find it.
        self.assertLessEqual(created, 1)
        self.assertEqual(set(reservers) - {'LiveClaim', 'created', 'existing'}, set())
        if created == 0:
            self.assertEqual(set(reservers), {'LiveClaim'})
        with store_mod.open_store(self.db) as store:
            self.assertEqual(store.get(key).state, 'confirmed')
            second = store.get(ident(ordinal=2).operation_key)
            self.assertEqual(second is not None, created == 1)
            if second is None:  # whatever the timing, a request after the race is admitted
                self.assertTrue(store.reserve_attempt(ident(ordinal=2), INTENT, actor='t').created)
        self.assertEqual(self.live_rows(), [(ident(ordinal=2).operation_key,)])
        self.assert_store_verifies()

    def test_competing_transitions_of_one_attempt(self):
        key = ident().operation_key
        with store_mod.open_store(self.db) as store:
            store.reserve_attempt(ident(), INTENT, actor='t')
            store.transition(key, 'dispatched', actor='t')
        targets = ['confirmed', 'unknown', 'failed'] * 3
        outcomes = self.race([('contend-transition', str(self.db), key, target, 'dispatched')
                              for target in targets[:CONTENDERS]])
        winners = [o for o in outcomes if o['outcome'] == 'transitioned']
        self.assertEqual(len(winners), 1)
        self.assertEqual({o['outcome'] for o in outcomes if o not in winners}, {'IllegalTransition'})
        with store_mod.open_store(self.db) as store:
            self.assertEqual(store.get(key).state, winners[0]['state'])
            self.assertEqual(len(store.events(key)), 3)
            self.assertEqual(store.attempt_identity(key).live, winners[0]['state'] == 'unknown')
        self.assert_store_verifies()


if __name__ == '__main__':
    unittest.main()
