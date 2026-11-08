"""Tests for the typed attempt identity and the one-live-claim rule (plan leaf E-01.1.1).

Run from the repository root:

    python -I -B -m unittest discover -s integrations/store/tests -v

Every database lives in a fresh temporary directory outside the checkout. The
multi-process tests use store_worker.py against one file and wait on each worker's
own output lines and exit, never on a fixed sleep.
"""
from pathlib import Path
import dataclasses
import hashlib
import importlib.util
import json
import random
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
NEWLINE, BACKSLASH = chr(10), chr(92)

C40 = '8eacfa81953a9129f3a8ee4c943f3030fd1c4fb7'
C64 = 'ab' * 32
DESIGN = f'openspec:changes/qual-02-search-freshness@{C40}'
OTHER_DESIGN = f'openspec:changes/qual-02-search-freshness@{C64}'
PROFILE = hashlib.sha256(b'profiles/strong-windows-qemu-whpx/profile.json').hexdigest()
POLICY = hashlib.sha256(b'policy').hexdigest()
MANIFEST = hashlib.sha256(b'catalog manifest').hexdigest()
BASE = {'work_id': 'TASK-1', 'design_revision': DESIGN, 'stage': 'implement', 'ordinal': 1,
        'profile_digest': PROFILE, 'planned_workspace': 'work/TASK-1/attempt-1', 'policy_digest': POLICY}
INTENT = {'outcomeRef': 'outcome:5c6f4c1e-8d3a-4a3b-9b2e-1f0e7d6c5b4a',
          'request': {'agent': 'engineer', 'prompt_digest': '0' * 64}}

GOLDEN_KEY = f'attempt/v1/TASK-1/qual-02-search-freshness@{C40}/implement/1'
GOLDEN_ATTEMPT_ID = 'b2bde220-1c3c-53d9-9bee-d716536e919b'
GOLDEN_CONVERSATION_ID = '3ff145a6-889c-5cdd-8613-bb01e4d0f705'
# The F-05.2 dump format: the canonical tables before migration 0003.
TABLES_BEFORE_0003 = ('schema_migration', 'attempt_state', 'attempt_transition', 'reconciliation_status',
                      'attempt', 'attempt_event', 'restore_epoch', 'restore_epoch_closure')


def ident(**override):
    return store_mod.AttemptIdentity(**{**BASE, **override})


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
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-attempt-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = self.tmp / 'integration.sqlite'

    def open(self, **kwargs):
        store = store_mod.open_store(self.db, **kwargs)
        self.addCleanup(store.close)
        return store

    def migrations_up_to(self, version):
        target = self.tmp / f'migrations-v{version}'
        target.mkdir()
        for migration in store_mod.load_migrations()[:version]:
            shutil.copy2(store_mod.MIGRATIONS_DIR / migration.name, target)
        return target

    def count(self, store, table):
        return store.conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]

    def raw_identity(self, conn, identity, live=1, key=None):
        conn.execute(
            'INSERT INTO attempt_identity (operation_key, attempt_id, work_id, design_revision, stage, ordinal, '
            'profile_digest, agent_manifest_digest, planned_workspace, policy_digest, live) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (key or identity.operation_key, store_mod.attempt_id_for(key or identity.operation_key),
             identity.work_id, identity.design_revision, identity.stage, identity.ordinal,
             identity.profile_digest, identity.agent_manifest_digest, identity.planned_workspace,
             identity.policy_digest, live))

    def raw_attempt(self, conn, key, intent, state='reserved'):
        canonical = store_mod.canonical_intent(intent)
        conn.execute(
            'INSERT INTO attempt (operation_key, intent_digest, intent_json, conversation_id, state, '
            "reconciliation_status, state_seq, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'none', 0, 'now', 'now')",
            (key, hashlib.sha256(canonical.encode()).hexdigest(), canonical, store_mod.conversation_id_for(key),
             state))

    @staticmethod
    def stored_intent(identity, intent=INTENT):
        return {**intent, 'workRef': identity.work_ref, 'attemptIdentity': identity.as_intent()}


class AcceptanceTests(StoreTestCase):
    """E-01.1.1: two identical reservations resolve to one persisted intended conversation UUID."""
    category = 'integration'

    def assert_one_persisted(self, conversation_ids):
        self.assertEqual(set(conversation_ids), {store_mod.conversation_id_for(GOLDEN_KEY)})
        with self.open() as store:
            self.assertEqual((self.count(store, 'attempt'), self.count(store, 'attempt_identity'),
                              self.count(store, 'attempt_event')), (1, 1, 1))
            self.assertEqual(store.get(GOLDEN_KEY).conversation_id, GOLDEN_CONVERSATION_ID)

    def test_two_identical_reservations_in_one_process(self):
        store = self.open()
        first = store.reserve_attempt(ident(), INTENT, actor='dispatcher')
        second = store.reserve_attempt(ident(), json.loads(json.dumps(INTENT)), actor='another-dispatcher')
        self.assertEqual((first.created, second.created), (True, False))
        self.assertEqual(second.reservation, first.reservation)
        self.assertEqual(second.attempt, first.attempt)
        self.assertEqual(first.reservation.operation_key, GOLDEN_KEY)
        self.assertEqual(first.attempt.attempt_id, GOLDEN_ATTEMPT_ID)
        store.close()
        self.assert_one_persisted([first.reservation.conversation_id, second.reservation.conversation_id])

    def test_two_identical_reservations_in_two_processes(self):
        store_mod.open_store(self.db).close()
        identity = json.dumps(BASE)
        code, [first], err = run_worker('reserve-attempt-and-exit', str(self.db), identity, json.dumps(INTENT))
        self.assertEqual(code, 0, err)
        self.assertEqual(first['outcome'], 'created')
        code, [second], err = run_worker('reserve-attempt', str(self.db), identity, json.dumps(INTENT))
        self.assertEqual(code, 0, err)
        self.assertEqual(second['outcome'], 'existing')
        self.assertEqual(second['reservation'], first['reservation'])
        self.assertEqual(second['attempt'], first['attempt'])
        code, [seen], err = run_worker('get', str(self.db), GOLDEN_KEY)
        self.assertEqual(code, 0, err)
        self.assertEqual((seen['reservation'], seen['attempt']), (first['reservation'], first['attempt']))
        self.assert_one_persisted([first['reservation']['conversation_id'], second['reservation']['conversation_id']])

    def test_concurrent_identical_reservations_from_many_processes(self):
        store_mod.open_store(self.db).close()
        procs = [start_worker('contend-attempt', str(self.db), json.dumps(BASE), json.dumps(INTENT))
                 for _ in range(CONTENDERS)]
        try:
            for proc in procs:
                self.assertEqual(read_message(proc), {'ready': True})
            for proc in procs:  # every one is open and waiting: release them together
                proc.stdin.write('go' + NEWLINE)
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
        self.assertEqual(sorted(o['outcome'] for o in outcomes), ['created'] + ['existing'] * (CONTENDERS - 1))
        self.assertEqual(len({json.dumps(o['attempt'], sort_keys=True) for o in outcomes}), 1)
        self.assert_one_persisted([o['reservation']['conversation_id'] for o in outcomes])


class KeyAndIdentityTests(StoreTestCase):
    def test_key_encoding_and_pinned_derivations(self):
        identity = ident()
        self.assertEqual(identity.operation_key, GOLDEN_KEY)
        self.assertEqual(store_mod.attempt_id_for(GOLDEN_KEY), GOLDEN_ATTEMPT_ID)
        self.assertEqual(store_mod.conversation_id_for(GOLDEN_KEY), GOLDEN_CONVERSATION_ID)
        self.assertNotEqual(store_mod.ATTEMPT_NAMESPACE, store_mod.CONVERSATION_NAMESPACE)
        self.assertEqual(str(store_mod.CONVERSATION_NAMESPACE), '7a215c37-e96b-473f-bc67-fa5786423cc1')
        self.assertEqual(ident(stage='review', ordinal=12, design_revision=OTHER_DESIGN, work_id='task-7.2')
                         .operation_key, f'attempt/v1/TASK-7.2/qual-02-search-freshness@{C64}/review/12')

    def test_longest_identity_fits_the_key_limit(self):
        longest = ident(work_id='T' * 61 + '-99', design_revision=f'openspec:changes/{"c" * 128}@{C64}',
                        stage='implement', ordinal=store_mod.MAX_ORDINAL)
        self.assertLessEqual(len(longest.operation_key), 512)
        # A stage name may grow to 32 characters (attempt_stage CHECK) and still fit.
        self.assertLessEqual(len(longest.operation_key) - len('implement') + 32, 512)
        store = self.open()
        first = dataclasses.replace(longest, ordinal=1)
        self.assertTrue(store.reserve_attempt(first, INTENT, actor='t').created)

    def test_work_id_is_canonical_upper_case(self):
        store = self.open()
        store.reserve_attempt(ident(work_id='task-1'), INTENT, actor='t')
        again = store.reserve_attempt(ident(work_id='Task-1'), INTENT, actor='t')
        self.assertFalse(again.created)
        self.assertEqual(again.attempt.identity.work_id, 'TASK-1')
        self.assertEqual(json.loads(again.reservation.intent_json)['workRef'], 'backlog:TASK-1')

    def test_stored_intent_carries_work_ref_and_identity(self):
        store = self.open()
        result = store.reserve_attempt(ident(), INTENT, actor='t')
        stored = json.loads(result.reservation.intent_json)
        self.assertEqual(stored, self.stored_intent(ident()))
        self.assertIsNone(stored['attemptIdentity']['agent_manifest_digest'])
        self.assertEqual(result.reservation.intent_digest, store_mod.intent_digest(self.stored_intent(ident())))
        self.assertEqual(store.identity_form(GOLDEN_KEY), 'typed')
        self.assertEqual(store.claims('task-1', DESIGN, 'implement'), [result.attempt])

    def test_invalid_identity_fields_are_refused(self):
        bad = {
            'work_id': ['', 'TASK', '-1', 'TASK-', 'TASK-1.', 'TASK-1..2', 'TASK_1', 'TA SK-1', 'TASK-1' + NEWLINE,
                        'TASK-1/2', 'T' * 62 + '-99', 7, None],
            'design_revision': ['', DESIGN.replace('openspec:', ''), f'openspec:changes/Qual@{C40}',
                                f'openspec:changes/-x@{C40}', f'openspec:changes/x--y@{C40}',
                                f'openspec:changes/x@{C40[:12]}', f'openspec:changes/x@{C40.upper()}',
                                f'openspec:changes/x/design.md@{C40}', f'openspec:changes/{"c" * 129}@{C40}',
                                DESIGN + NEWLINE, f'openspec:changes/x@{C40}#sha256={"0" * 64}'],
            'stage': ['', 'Implement', 'deliver', 'rework', None],
            'ordinal': [0, -1, store_mod.MAX_ORDINAL + 1, True, 1.0, '1', None],
            'profile_digest': ['', PROFILE.upper(), 'sha256:' + PROFILE, PROFILE[:63], None],
            'policy_digest': ['', POLICY.upper(), POLICY + '0', None],
            'agent_manifest_digest': ['', MANIFEST.upper(), 'sha256:' + MANIFEST],
            'planned_workspace': ['', '/abs/path', 'C:' + BACKSLASH + 'work', 'C:/work', '../escape', 'a/../b',
                                  '.hidden', 'a/.git', '-flag', 'a//b', 'a/', 'a' + BACKSLASH + 'b', 'a b',
                                  'w' * 256, 'work' + NEWLINE],
        }
        store = self.open()
        for field, values in bad.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(store_mod.InvalidIdentity):
                    ident(**{field: value})
        self.assertEqual(self.count(store, 'attempt'), 0)

    def test_valid_identity_variants(self):
        for override in ({'work_id': 'DRAFT-12.3.4'}, {'design_revision': OTHER_DESIGN}, {'stage': 'review'},
                         {'agent_manifest_digest': MANIFEST}, {'planned_workspace': 'w_1/TASK-1.a-b'},
                         {'ordinal': store_mod.MAX_ORDINAL}):
            with self.subTest(override=override):
                ident(**override)

    def test_design_revision_from_task_pointers(self):
        digest = '1' * 64
        pointers = [f'openspec:changes/qual-02-search-freshness/{name}@{C40}#sha256={digest}'
                    for name in ('proposal.md', 'design.md', 'specs/a/spec.md')]
        self.assertEqual(store_mod.design_revision_from_pointers(pointers), DESIGN)
        refused = [
            [], 'not-a-list', [pointers[0], pointers[1].replace(C40, C64)],
            [pointers[0], pointers[0].replace('qual-02-search-freshness', 'other-change')],
            [pointers[0] + NEWLINE], ['openspec:changes/x@' + C40],
        ]
        for value in refused:
            with self.subTest(value=value), self.assertRaises(store_mod.InvalidIdentity):
                store_mod.design_revision_from_pointers(value)

    def test_grammars_are_the_planning_adapters(self):
        planning = store_mod.planning
        self.assertTrue(Path(planning.__file__).samefile(STORE_DIR.parent / 'planning' / 'planning_adapter.py'))
        self.assertEqual(planning.TASK_ID_RE.pattern, r'^[A-Za-z]+-[0-9]+(?:\.[0-9]+)*$')
        self.assertEqual(planning.CHANGE_ID, r'[a-z0-9]+(?:-[a-z0-9]+)*')
        self.assertEqual(planning.COMMIT, r'[0-9a-f]{40}|[0-9a-f]{64}')
        self.assertEqual(planning.ARTIFACT_PATH, r'[A-Za-z0-9_][A-Za-z0-9._-]*(?:/[A-Za-z0-9_][A-Za-z0-9._-]*)*')


class SqlGrammarDifferentialTests(StoreTestCase):
    """The SQLite CHECKs accept exactly what the Python validators accept."""

    FIELDS = {
        'work_id': ('work_id_grammar', lambda v: store_mod.valid_work_id(v), 'TASK-1',
                    'ABCXYZabcxyz0123456789.-_/ @' + NEWLINE),
        'design_revision': ('design_revision_grammar', lambda v: store_mod.valid_design_revision(v), DESIGN,
                            'abcdef0123456789-@/:#Az.' + NEWLINE),
        'planned_workspace': ('planned_workspace_grammar', lambda v: store_mod.valid_planned_workspace(v),
                              'work/TASK-1/a_1', 'aZ09._-/' + BACKSLASH + ': ' + NEWLINE),
        'profile_digest': ('profile_digest_sha256', store_mod._is_sha256_hex, PROFILE, '0123456789abcdefABg'),
    }
    EDGES = {
        'work_id': ['A-1', 'a-1', 'AB-12.3', 'AB-12.', 'AB-.3', 'AB-1..3', 'AB--1', '1-1', 'A-1-2', 'A1-1',
                    'T' * 62 + '-1', 'T' * 61 + '-1', 'TASK-1' + NEWLINE, 'TASK-١'],
        'design_revision': [DESIGN, OTHER_DESIGN, f'openspec:changes/a@{C40}', f'openspec:changes/@{C40}',
                            f'openspec:changes/a@{C40}@{C40}', f'openspec:changes/{"c" * 128}@{C40}',
                            f'openspec:changes/{"c" * 129}@{C40}', f'openspec:changes/a-@{C40}',
                            f'openspec:changes/a@{C40}0', f'openspec:changes/a@{C64}', f'openspec:changes/a@{C64}a',
                            f'xopenspec:changes/a@{C40}', f'openspec:changesa@{C40}',
                            f'openspec:changes/a--b@{C40}', f'openspec:changes/-a@{C40}', f'openspec:changes/a-b@{C40}',
                            f'openspec:changes/a_b@{C40}', f'openspec:changes/A@{C40}', f'openspec:changes/a@{C40.upper()}',
                            f'openspec:changes/a@{C40[:39]}g'],
        'planned_workspace': ['a', '_', '.', '-', 'a/b', 'a/.b', 'a/-b', 'a/_b', 'a/b.', 'a//b', '/a', 'a/',
                              'w' * 255, 'w' * 256, 'a-', 'a.b/c-d_e'],
        'profile_digest': [PROFILE, PROFILE.upper(), PROFILE[:-1], PROFILE + 'a', 'g' * 64],
    }

    def sql_accepts(self, conn, field, value, constraint):
        values = {**BASE, 'agent_manifest_digest': None, field: value}
        conn.execute('BEGIN')
        try:
            conn.execute(
                "INSERT INTO attempt_identity (operation_key, attempt_id, work_id, design_revision, stage, ordinal, "
                "profile_digest, agent_manifest_digest, planned_workspace, policy_digest, live) VALUES "
                "('attempt/v1/' || :work_id || '/' || substr(:design_revision, 18) || '/' || :stage || '/' "
                "|| printf('%d', :ordinal), '00000000-0000-0000-0000-000000000000', :work_id, :design_revision, "
                ":stage, :ordinal, :profile_digest, :agent_manifest_digest, :planned_workspace, :policy_digest, 1)",
                values)
            return True
        except sqlite3.IntegrityError as exc:
            if f'CHECK constraint failed: {constraint}' in str(exc):
                return False
            raise AssertionError(f'{field}={value!r}: unexpected refusal {exc}') from None
        finally:
            conn.execute('ROLLBACK')

    def mutations(self, valid, alphabet, rng, count):
        for _ in range(count):
            text = list(valid)
            for _ in range(rng.randint(1, 3)):
                op = rng.randrange(3)
                i = rng.randrange(len(text) + 1)
                if op == 0:
                    text.insert(i, rng.choice(alphabet))
                elif text and op == 1:
                    del text[min(i, len(text) - 1)]
                elif text:
                    text[min(i, len(text) - 1)] = rng.choice(alphabet)
            yield ''.join(text)
        for _ in range(count):
            yield ''.join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))

    def test_sql_checks_agree_with_python_validators(self):
        conn = self.open().conn
        rng = random.Random(20261107)
        for field, (constraint, python_ok, valid, alphabet) in self.FIELDS.items():
            candidates = list(self.EDGES[field]) + list(self.mutations(valid, alphabet, rng, 300))
            accepted = 0
            for value in candidates:
                expected = python_ok(value)
                accepted += expected
                with self.subTest(field=field, value=value):
                    self.assertEqual(self.sql_accepts(conn, field, value, constraint), expected)
            self.assertGreater(accepted, 5, field)  # both verdicts were exercised
        self.assertEqual(conn.execute('SELECT count(*) FROM attempt_identity').fetchone()[0], 0)

    def test_sql_ordinal_and_digest_types(self):
        conn = self.open().conn
        for value in (0, store_mod.MAX_ORDINAL + 1, -5):
            with self.subTest(ordinal=value):
                # The admission trigger (next ordinal) or the range CHECK refuses it.
                with self.assertRaisesRegex(AssertionError, 'ordinal'):
                    self.sql_accepts(conn, 'ordinal', value, 'ordinal_range')
        self.assertFalse(self.sql_accepts(conn, 'agent_manifest_digest', 'x' * 64, 'agent_manifest_digest_sha256'))
        self.assertFalse(self.sql_accepts(conn, 'policy_digest', POLICY.upper(), 'policy_digest_sha256'))
        self.assertTrue(self.sql_accepts(conn, 'agent_manifest_digest', MANIFEST, 'agent_manifest_digest_sha256'))
        conn.execute('BEGIN')
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY'):  # stage not in attempt_stage
                conn.execute(
                    "INSERT INTO attempt_identity (operation_key, attempt_id, work_id, design_revision, stage, "
                    "ordinal, profile_digest, planned_workspace, policy_digest, live) VALUES "
                    "(?, ?, 'TASK-1', ?, 'deliver', 1, ?, 'w', ?, 1)",
                    (GOLDEN_KEY.replace('/implement/', '/deliver/'), GOLDEN_ATTEMPT_ID, DESIGN, PROFILE, POLICY))
        finally:
            conn.execute('ROLLBACK')


class ClaimRuleTests(StoreTestCase):
    def advance(self, store, key, path):
        for state in path:
            store.transition(key, state, actor='t')

    def test_no_new_ordinal_while_one_is_live(self):
        for path in ([], ['dispatched'], ['dispatched', 'unknown']):
            with self.subTest(path=path):
                store = store_mod.open_store(self.tmp / f'claim-{len(path)}.sqlite')
                self.addCleanup(store.close)
                first = store.reserve_attempt(ident(), INTENT, actor='t')
                self.advance(store, first.reservation.operation_key, path)
                before = store.canonical_dump()
                with self.assertRaisesRegex(store_mod.LiveClaim, 'reconcile an unknown outcome first'):
                    store.reserve_attempt(ident(ordinal=2), INTENT, actor='t')
                self.assertEqual(store.canonical_dump(), before)
                self.assertFalse(store.conn.in_transaction)

    def test_new_ordinal_after_failed_or_confirmed(self):
        store = self.open()
        one = store.reserve_attempt(ident(), INTENT, actor='t').reservation.operation_key
        store.transition(one, 'failed', actor='t', reason='refused before any external call')
        two = store.reserve_attempt(ident(ordinal=2), INTENT, actor='t').reservation.operation_key
        self.advance(store, two, ['dispatched', 'confirmed'])
        three = store.reserve_attempt(ident(ordinal=3), {**INTENT, 'rework': 'review findings'}, actor='t')
        self.assertTrue(three.created)  # rework after a confirmed attempt is another implement ordinal
        self.advance(store, three.reservation.operation_key, ['dispatched', 'unknown', 'failed'])
        self.assertTrue(store.reserve_attempt(ident(ordinal=4), INTENT, actor='t').created)
        claims = store.claims('TASK-1', DESIGN, 'implement')
        self.assertEqual([(c.identity.ordinal, c.live) for c in claims],
                         [(1, False), (2, False), (3, False), (4, True)])
        self.assertEqual(len({c.attempt_id for c in claims}), 4)

    def test_ordinal_gaps_are_refused(self):
        store = self.open()
        with self.assertRaisesRegex(store_mod.OrdinalOutOfSequence, 'the next ordinal is 1'):
            store.reserve_attempt(ident(ordinal=2), INTENT, actor='t')
        one = store.reserve_attempt(ident(), INTENT, actor='t').reservation.operation_key
        store.transition(one, 'failed', actor='t')
        with self.assertRaisesRegex(store_mod.OrdinalOutOfSequence, 'the next ordinal is 2'):
            store.reserve_attempt(ident(ordinal=3), INTENT, actor='t')
        # Reusing ordinal 1 is its existing key: identical is idempotent, different conflicts.
        self.assertFalse(store.reserve_attempt(ident(), INTENT, actor='t').created)
        with self.assertRaises(store_mod.ConflictingReservation):
            store.reserve_attempt(ident(), {**INTENT, 'request': 'another'}, actor='t')
        self.assertEqual(self.count(store, 'attempt_identity'), 1)

    def test_claims_are_per_work_design_revision_and_stage(self):
        store = self.open()
        for override in ({}, {'stage': 'review'}, {'design_revision': OTHER_DESIGN}, {'work_id': 'TASK-2'}):
            with self.subTest(override=override):
                self.assertTrue(store.reserve_attempt(ident(**override), INTENT, actor='t').created)
        self.assertEqual(self.count(store, 'attempt_identity'), 4)

    def test_raw_sql_cannot_bypass_the_claim_rule(self):
        store = self.open()
        store.reserve_attempt(ident(), INTENT, actor='t')
        conn = store.conn
        before = store.canonical_dump()
        second = ident(ordinal=2)
        cases = {
            'live claim': (lambda: self.raw_identity(conn, second), 'live claim'),
            'gap': (lambda: self.raw_identity(conn, ident(ordinal=5, stage='review')), 'ordinal out of sequence'),
            'starts not live': (lambda: self.raw_identity(conn, ident(stage='review'), live=0), 'reserved live'),
            'wrong key': (lambda: self.raw_identity(conn, ident(stage='review'), key=GOLDEN_KEY + 'x'),
                          'canonical attempt/v1 encoding'),
            'attempt without identity': (lambda: self.raw_attempt(conn, ident(stage='review').operation_key,
                                                                  self.stored_intent(ident(stage='review'))),
                                         'needs its typed identity'),
        }
        for label, (action, message) in cases.items():
            with self.subTest(label):
                conn.execute('BEGIN')
                try:
                    with self.assertRaisesRegex(sqlite3.IntegrityError, message):
                        action()
                finally:
                    conn.execute('ROLLBACK')
        # An identity without its attempt cannot commit (deferred reference).
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY'):
            self.raw_identity(conn, ident(stage='review'))
        self.assertFalse(conn.in_transaction)
        self.assertEqual(store.canonical_dump(), before)

    def test_partial_unique_index_holds_without_the_admission_trigger(self):
        store = self.open()
        store.reserve_attempt(ident(), INTENT, actor='t')
        conn = store.conn
        conn.execute('DROP TRIGGER attempt_identity_admission')  # this throwaway store only
        conn.execute('BEGIN')
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError,
                                        'UNIQUE constraint failed: attempt_identity.work_id, '
                                        'attempt_identity.design_revision, attempt_identity.stage'):
                self.raw_identity(conn, ident(ordinal=2))
        finally:
            conn.execute('ROLLBACK')

    def test_raw_typed_attempt_must_carry_its_identity_and_start_reserved(self):
        store = self.open()
        conn = store.conn
        identity = ident()
        good = self.stored_intent(identity)
        bad_intents = {
            'workRef': {**good, 'workRef': 'backlog:TASK-2'},
            'no workRef': {k: v for k, v in good.items() if k != 'workRef'},
            'profile': {**good, 'attemptIdentity': {**identity.as_intent(), 'profile_digest': POLICY}},
            'manifest key missing': {**good, 'attemptIdentity': {k: v for k, v in identity.as_intent().items()
                                                                 if k != 'agent_manifest_digest'}},
            'ordinal as text': {**good, 'attemptIdentity': {**identity.as_intent(), 'ordinal': '1'}},
            'format': {**good, 'attemptIdentity': {**identity.as_intent(), 'format': 'attempt-identity/v2'}},
        }
        for label, intent in bad_intents.items():
            with self.subTest(label):
                conn.execute('BEGIN')
                try:
                    self.raw_identity(conn, identity)
                    with self.assertRaisesRegex(sqlite3.IntegrityError, 'does not carry its identity'):
                        self.raw_attempt(conn, identity.operation_key, intent)
                finally:
                    conn.execute('ROLLBACK')
        conn.execute('BEGIN')
        try:
            self.raw_identity(conn, identity)
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'starts reserved'):
                self.raw_attempt(conn, identity.operation_key, good, state='confirmed')
        finally:
            conn.execute('ROLLBACK')
        # The same rows, written correctly, are accepted.
        conn.execute('BEGIN')
        self.raw_identity(conn, identity)
        self.raw_attempt(conn, identity.operation_key, good)
        conn.execute('COMMIT')
        self.assertEqual(store.identity_form(identity.operation_key), 'typed')


class LifecycleAndImmutabilityTests(StoreTestCase):
    PATHS = {'reserved': [], 'dispatched': ['dispatched'], 'unknown': ['dispatched', 'unknown'],
             'confirmed': ['dispatched', 'confirmed'], 'failed': ['failed'],
             'reconciled-confirmed': ['dispatched', 'unknown', 'confirmed'],
             'reconciled-failed': ['dispatched', 'unknown', 'failed']}

    def test_live_follows_every_transition(self):
        store = self.open()
        for n, (label, path) in enumerate(self.PATHS.items(), start=1):
            key = store.reserve_attempt(ident(work_id=f'TASK-{n}'), INTENT, actor='t').reservation.operation_key
            with self.subTest(label):
                self.assertTrue(store.attempt_identity(key).live)
                for state in path:
                    store.transition(key, state, actor='t')
                    self.assertEqual(store.attempt_identity(key).live, state in store_mod.LIVE_STATES)
        store_mod._verify_kind_invariants(store.conn)

    def test_live_cannot_drift_and_identity_is_immutable(self):
        store = self.open()
        live_key = store.reserve_attempt(ident(), INTENT, actor='t').reservation.operation_key
        done_key = store.reserve_attempt(ident(stage='review'), INTENT, actor='t').reservation.operation_key
        store.transition(done_key, 'failed', actor='t')
        refused = [
            ("UPDATE attempt_identity SET live = 0 WHERE operation_key = ?", live_key, 'live follows'),
            ("UPDATE attempt_identity SET live = 1 WHERE operation_key = ?", done_key, 'live follows'),
            ("UPDATE attempt_identity SET live = 2 WHERE operation_key = ?", live_key, 'live follows'),
            ("UPDATE attempt_identity SET ordinal = 2 WHERE operation_key = ?", live_key, 'immutable'),
            ("UPDATE attempt_identity SET profile_digest = '" + POLICY + "' WHERE operation_key = ?", live_key,
             'immutable'),
            ("UPDATE attempt_identity SET attempt_id = '00000000-0000-0000-0000-000000000000' "
             "WHERE operation_key = ?", live_key, 'immutable'),
            ("UPDATE attempt_identity SET planned_workspace = 'elsewhere' WHERE operation_key = ?", live_key,
             'immutable'),
            ("DELETE FROM attempt_identity WHERE operation_key = ?", done_key, 'never deleted'),
            ("UPDATE attempt SET intent_json = '{}' WHERE operation_key = ?", live_key, 'immutable'),
            ("UPDATE attempt SET state = 'reserved' WHERE operation_key = ?", done_key, 'illegal'),
        ]
        before = store.canonical_dump()
        for sql, key, message in refused:
            with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, message):
                store.conn.execute(sql, (key,))
        # A write that agrees with the state changes nothing and is allowed.
        store.conn.execute('UPDATE attempt_identity SET live = 1 WHERE operation_key = ?', (live_key,))
        self.assertEqual(store.canonical_dump(), before)

    def test_stage_vocabulary_is_a_frozen_table(self):
        store = self.open()
        self.assertEqual(tuple(r[0] for r in store.conn.execute('SELECT stage FROM attempt_stage ORDER BY stage')),
                         store_mod.STAGES)
        for sql in ("INSERT INTO attempt_stage VALUES ('deliver', 'x')",
                    "UPDATE attempt_stage SET description = 'x'", "DELETE FROM attempt_stage"):
            with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, 'only by migration'):
                store.conn.execute(sql)

    def test_conflicting_intent_under_the_same_key_changes_nothing(self):
        store = self.open()
        store.reserve_attempt(ident(), INTENT, actor='t')
        before = store.canonical_dump()
        for identity, intent in ((ident(profile_digest=POLICY), INTENT), (ident(policy_digest=PROFILE), INTENT),
                                 (ident(agent_manifest_digest=MANIFEST), INTENT),
                                 (ident(planned_workspace='work/other'), INTENT),
                                 (ident(), {**INTENT, 'request': 'other'})):
            with self.subTest(identity=identity, intent=intent), \
                    self.assertRaises(store_mod.IntentConflict):
                store.reserve_attempt(identity, intent, actor='t')
        self.assertEqual(store.canonical_dump(), before)
        self.assertIs(store_mod.IntentConflict, store_mod.ConflictingReservation)

    def test_intent_and_api_refusals(self):
        store = self.open()
        cases = [
            (ident(), {**INTENT, 'workRef': 'backlog:TASK-2'}, store_mod.InvalidIdentity),
            (ident(), {**INTENT, 'attemptIdentity': {}}, store_mod.InvalidIdentity),
            (BASE, INTENT, store_mod.InvalidIdentity),
            (ident(), ['not', 'an', 'object'], store_mod.StoreError),
            (ident(), {'x': float('nan')}, store_mod.StoreError),
        ]
        for identity, intent, error in cases:
            with self.subTest(intent=intent), self.assertRaises(error):
                store.reserve_attempt(identity, intent, actor='t')
        with self.assertRaises(store_mod.StoreError):
            store.reserve_attempt(ident(), INTENT, actor='')
        with self.assertRaisesRegex(store_mod.InvalidIdentity, 'reserved for typed attempts'):
            store.reserve(GOLDEN_KEY, INTENT, actor='t')
        # A matching workRef supplied by the caller is accepted as is.
        self.assertTrue(store.reserve_attempt(ident(), {**INTENT, 'workRef': 'backlog:TASK-1'}, actor='t').created)
        self.assertEqual(self.count(store, 'attempt'), 1)

    def test_open_restore_epoch_refuses_new_typed_reservations(self):
        store = self.open()
        store.reserve_attempt(ident(), INTENT, actor='t')
        store.conn.execute(
            'INSERT INTO restore_epoch (backup_manifest_sha256, backup_file, backup_high_water, '
            'backup_history_digest, rollback_accepted, projections_dropped_json, actor, opened_at) '
            "VALUES (?, 'b.sqlite', 0, ?, 0, '[]', 'owner', 'now')", ('0' * 64, '0' * 64))
        with self.assertRaises(store_mod.RestoreEpochOpen):
            store.reserve_attempt(ident(stage='review'), INTENT, actor='t')
        self.assertFalse(store.reserve_attempt(ident(), INTENT, actor='t').created)
        self.assertEqual(self.count(store, 'attempt_identity'), 1)

    def test_backup_of_a_typed_store_verifies_and_restores_the_identity(self):
        store = self.open()
        reserved = store.reserve_attempt(ident(), INTENT, actor='t')
        store.transition(reserved.reservation.operation_key, 'dispatched', actor='t')
        manifest = store.backup(actor='owner')
        store.close()
        manifest_path = self.db.parent / 'backups' / (manifest['backup_file'] + '.manifest.json')
        storecore.verify_backup(manifest_path, store_mod.KIND)
        store_mod.restore_store(self.db, manifest_path, actor='owner')
        with self.open() as restored:
            self.assertEqual(restored.attempt_identity(GOLDEN_KEY), reserved.attempt)
            report = restored.reconcile(lambda r: 'performed', actor='reconciler')
            self.assertEqual(report['confirmed'], [GOLDEN_KEY])
            self.assertFalse(restored.attempt_identity(GOLDEN_KEY).live)
            restored.close_restore_epoch(actor='owner')
            self.assertTrue(restored.reserve_attempt(ident(ordinal=2), INTENT, actor='t').created)


class MigrationTests(StoreTestCase):
    def test_fresh_store_is_at_0003(self):
        store = self.open()
        names = [n for _, n, _, _ in store.applied_migrations()]
        self.assertIn('0003_typed_attempt_identity.sql', names)
        self.assertEqual(store.schema_version(), len(store_mod.load_migrations()))
        self.assertEqual(store.summary()['typed_attempts'], 0)

    def test_upgrade_from_a_0002_store_keeps_legacy_receipts(self):
        v2 = self.migrations_up_to(2)
        with self.open(migrations_dir=v2) as old:
            self.assertEqual(old.schema_version(), 2)
            old.reserve('work-TASK-1/implement/revision-1', {'workRef': 'backlog:TASK-1'}, actor='t')
            old.transition('work-TASK-1/implement/revision-1', 'dispatched', actor='t')
            old.reserve('op-legacy', INTENT, actor='t')
            receipts = [old.conn.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall()
                        for t in ('attempt', 'attempt_event')]
        with self.open() as store:
            self.assertEqual(store.schema_version(), len(store_mod.load_migrations()))
            self.assertEqual([store.conn.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall()
                              for t in ('attempt', 'attempt_event')], receipts)
            for key in ('work-TASK-1/implement/revision-1', 'op-legacy'):
                self.assertEqual(store.identity_form(key), 'legacy-untyped')
                self.assertIsNone(store.attempt_identity(key))
            # Legacy attempts keep their lifecycle; new typed and opaque reservations work.
            store.transition('work-TASK-1/implement/revision-1', 'confirmed', actor='t')
            self.assertTrue(store.reserve_attempt(ident(), INTENT, actor='t').created)
            self.assertTrue(store.reserve('op-after', INTENT, actor='t').created)
            self.assertEqual(store.identity_form('op-after'), 'legacy-untyped')
            store_mod._verify_kind_invariants(store.conn)

    def test_upgrade_is_refused_when_a_legacy_key_uses_the_reserved_namespace(self):
        v2 = self.migrations_up_to(2)
        with self.open(migrations_dir=v2) as old:
            key = 'attempt/v1/legacy'
            old.conn.execute('BEGIN')
            self.raw_attempt(old.conn, key, INTENT)
            old.conn.execute("INSERT INTO attempt_event (operation_key, seq, to_state, reconciliation_status, "
                             "actor, recorded_at) VALUES (?, 0, 'reserved', 'none', 't', 'now')", (key,))
            old.conn.execute('COMMIT')
            before = old.canonical_dump()
        with self.assertRaisesRegex(store_mod.MigrationError, 'migration 0003 refused'):
            store_mod.open_store(self.db)
        with self.open(migrations_dir=v2, apply_migrations=False) as unchanged:
            self.assertEqual(unchanged.schema_version(), 2)
            self.assertEqual(unchanged.canonical_dump(), before)

    def test_dump_of_an_older_store_is_unchanged_so_old_manifests_verify(self):
        for version in (1, 2):
            with self.subTest(version=version):
                db = self.tmp / f'v{version}.sqlite'
                with store_mod.open_store(db, migrations_dir=self.migrations_up_to(version)) as old:
                    old.reserve('op-1', INTENT, actor='t')
                    current = old.canonical_dump()
                    with mock.patch.object(store_mod, 'CANONICAL_TABLES', TABLES_BEFORE_0003):
                        self.assertEqual(old.canonical_dump(), current)
                    self.assertNotIn(b'-- attempt_identity:', current)
                    self.assertNotIn(b'-- attempt_stage:', current)


if __name__ == '__main__':
    unittest.main()
