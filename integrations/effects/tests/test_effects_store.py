"""Tests for integrations/effects/effects_store.py (stdlib unittest).

Run from the repository root:

    python -I -B -m unittest discover -s integrations/effects/tests -v

Every effects root is a fresh directory inside a new temporary directory. The
tests set that directory's DACL themselves with the Windows security API (only
on directories they created), so the custody template's principal is the test
process's own SID; they never change a permission anywhere else. The roots live
under %TEMP%, so the tests use the library-only fixture location policy, which
relaxes the user-profile rule and nothing else. The crash tests use real
processes (effects_worker.py); the parent waits on each worker's own output
lines and exit, never on a fixed sleep.
"""
from pathlib import Path
import ast
import dataclasses
import hashlib
import importlib.util
import inspect
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
EFFECTS_DIR = HERE.parent
REPO = EFFECTS_DIR.parents[1]
MODULE = EFFECTS_DIR / 'effects_store.py'
WORKER = HERE / 'effects_worker.py'
INTEGRATION_MODULE = REPO / 'integrations' / 'store' / 'integration_store.py'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


store_mod = _load('effects_store', MODULE)
integration_mod = _load('integration_store', INTEGRATION_MODULE)
custody = store_mod.custody
storecore = store_mod.storecore

WAIT_CEILING_S = 60  # bounds a hang; workers normally finish in well under a second
WINDOWS = sys.platform == 'win32'
ME = custody.current_user_sid() if WINDOWS else os.getuid()
FIXTURE = store_mod.fixture_location_policy()
AUTHORITY = store_mod.Authority(protected_ref='refs/heads/main', authorization_revision='auth-rev-7',
                                manifest_blob_digest='sha256:' + 'a' * 64, merged_by='verifier:owner',
                                policy_revision='policy-3')


def request(name, **inputs):
    return store_mod.EffectRequest('repository.protect-branch', f'gitea:example/{name}', AUTHORITY,
                                   {'name': name, **inputs})


def request_json(req):
    return json.dumps({'operation_kind': req.operation_kind, 'target_identity': req.target_identity,
                       'authority': dataclasses.asdict(req.authority), 'inputs': dict(req.inputs)})


# ---------------------------------------------------------------------------
# Fixture permissions: the Windows security API, on test-created directories only

def _set_protected_dacl(path, sddl):
    import ctypes
    from ctypes import wintypes
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.ULONG)]
    advapi.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                                                 ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    advapi.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
                                             ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi.SetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor, size = ctypes.c_void_p(), wintypes.ULONG()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor),
                                                                       ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, dacl, defaulted = wintypes.BOOL(), ctypes.c_void_p(), wintypes.BOOL()
        advapi.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl),
                                         ctypes.byref(defaulted))
        dacl_info, protected = 0x4, 0x80000000
        rc = advapi.SetNamedSecurityInfoW(str(path), 1, dacl_info | protected, None, None, dacl, None)
        if rc:
            raise ctypes.WinError(rc)
    finally:
        kernel.LocalFree(descriptor)


CONFORMING_SDDL = f'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;{ME})'
INTERIM_SDDL = 'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'  # decision 0004's interim template exactly


def make_root(path, sddl=CONFORMING_SDDL):
    path.mkdir()
    if WINDOWS:
        _set_protected_dacl(path, sddl)
    else:
        os.chmod(path, 0o700)
    return path


def restore_access(path):
    """Give the test's own SID access again (owner rights allow it) so cleanup works."""
    if WINDOWS and path.exists():
        _set_protected_dacl(path, CONFORMING_SDDL)


def worker_cmd(*args):
    return [sys.executable, '-I', '-B', str(WORKER), *args]


def run_worker(*args):
    result = subprocess.run(worker_cmd(*args), capture_output=True, text=True, encoding='utf-8',
                            timeout=WAIT_CEILING_S)
    return result.returncode, [json.loads(line) for line in result.stdout.splitlines()], result.stderr


def start_worker(*args):
    return subprocess.Popen(worker_cmd(*args), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding='utf-8')


def read_message(proc):
    line = proc.stdout.readline()
    if not line:
        proc.wait(timeout=WAIT_CEILING_S)
        raise AssertionError(f'worker exited {proc.returncode} without output: {proc.stderr.read()}')
    return json.loads(line)


def stop_worker(proc):
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=WAIT_CEILING_S)
    for stream in (proc.stdout, proc.stderr, proc.stdin):
        stream.close()


def table_rows(conn, table, where='1'):
    return conn.execute(f'SELECT * FROM "{table}" WHERE {where} ORDER BY 1').fetchall()


class EffectsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-effects-test-'))
        self.addCleanup(self._cleanup)
        self.root = make_root(self.tmp / 'effects-root')

    def _cleanup(self):
        for child in self.tmp.iterdir() if self.tmp.exists() else ():
            if child.is_dir():
                restore_access(child)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def open(self, root=None, **kwargs):
        kwargs.setdefault('principal', ME)
        kwargs.setdefault('policy', FIXTURE)
        kwargs.setdefault('create', True)
        store = store_mod.open_effects_store(root or self.root, **kwargs)
        self.addCleanup(store.close)
        return store

    def restore(self, manifest, **kwargs):
        return store_mod.restore_effects_store(self.root, manifest, actor='owner-elevated', principal=ME,
                                               policy=FIXTURE, **kwargs)


# ---------------------------------------------------------------------------

class SchemaAndReceiptTests(EffectsTestCase):
    def test_init_summary_echoes_the_fixture_policy_kind_and_template(self):
        summary = store_mod.init_effects_store(self.root, principal=ME, policy=FIXTURE)
        self.assertTrue(summary['location_policy'].startswith('fixture (tests only)'), summary['location_policy'])
        self.assertEqual(summary['store_kind'], 'effects')
        self.assertEqual(summary['application_id'], store_mod.APPLICATION_ID)
        self.assertEqual(summary['schema_version'], 1)
        self.assertEqual(summary['pragmas']['journal_mode'], 'wal')
        self.assertEqual(summary['high_water_mark'], 0)
        self.assertEqual(summary['chain_head'], storecore.GENESIS_DIGEST)
        if WINDOWS:
            self.assertEqual(summary['custody_template']['allowed_sids'],
                             sorted({custody.SYSTEM_SID, custody.ADMINISTRATORS_SID, ME}))
        self.assertTrue((self.root / 'backups' / 'superseded').is_dir())
        with self.open() as store:
            strict = dict(store.conn.execute("SELECT name, strict FROM pragma_table_list WHERE schema = 'main' "
                                             "AND name NOT LIKE 'sqlite_%'"))
            self.assertTrue(strict and all(strict.values()), strict)

    def test_reserve_commits_key_inputs_authority_and_actor_before_any_effect(self):
        store = self.open()
        req = request('alpha', branch='main')
        result = store.reserve(req, actor='executor')
        self.assertTrue(result.created)
        r = result.receipt
        self.assertEqual(r.effect_key, req.effect_key())
        self.assertEqual(r.effect_key, store_mod.derive_effect_key(json.loads(r.key_inputs_json)))
        self.assertEqual(json.loads(r.key_inputs_json)['inputs'], {'name': 'alpha', 'branch': 'main'})
        self.assertEqual((r.operation_kind, r.target_identity), ('repository.protect-branch', 'gitea:example/alpha'))
        self.assertEqual((r.authority_protected_ref, r.authority_revision, r.authority_manifest_digest,
                          r.authority_merged_by, r.authority_policy_revision),
                         tuple(dataclasses.asdict(AUTHORITY).values()))
        self.assertEqual((r.state, r.origin, r.actor, r.result_json), ('reserved', 'executor', 'executor', None))
        again = store.reserve(request('alpha', branch='main'), actor='someone-else')
        self.assertFalse(again.created)
        self.assertEqual(again.receipt, r)
        self.assertEqual(len(store.events()), 1)

    def test_lifecycle_records_the_observed_result_independent_of_exit_status(self):
        store = self.open()
        key = store.reserve(request('beta'), actor='executor').receipt.effect_key
        store.begin(key, actor='executor')
        done = store.finish(key, 'completed', actor='executor',
                            result=store_mod.EffectResult('performed', {'protected': True}, exit_status=1))
        self.assertEqual(json.loads(done.result_json),
                         {'exit_status': 1, 'observed_target_state': {'protected': True}, 'outcome': 'performed'})
        with self.assertRaises(store_mod.StoreError):  # completed must match the observed outcome
            store.finish(store.begin(store.reserve(request('gamma'), actor='e').receipt.effect_key,
                                     actor='e').effect_key, 'completed', actor='e',
                         result=store_mod.EffectResult('not_performed', {}))
        self.assertEqual([e['kind'] for e in store.events(key)],
                         ['receipt_created', 'receipt_transition', 'receipt_transition'])
        self.assertEqual(store.verify_chain()['chain_head'], store.chain_head())

    def test_disallowed_transitions_and_raw_sql_edits_are_refused(self):
        store = self.open()
        key = store.reserve(request('delta'), actor='e').receipt.effect_key
        before = store.canonical_dump()
        for target, origin in (('completed', 'executor'), ('observed', 'reconciliation'), ('reserved', 'executor'),
                               ('applying', 'reconciliation'), ('failed', 'owner_attestation')):
            with self.subTest(target=target, origin=origin), self.assertRaises(store_mod.IllegalTransition):
                store._transition(key, target, origin, 'e', result=store_mod.EffectResult(
                    'performed' if target == 'completed' else 'not_performed', {}))
            self.assertEqual(store.canonical_dump(), before)
        store.begin(key, actor='e')
        store.finish(key, 'unknown', actor='e')
        with self.assertRaises(store_mod.IllegalTransition):  # unknown never resolved by the executor
            store._transition(key, 'completed', 'executor', 'e', result=store_mod.EffectResult('performed', {}))
        conn = store.conn
        refused = [
            'DELETE FROM effect_receipt',
            "UPDATE effect_receipt SET target_identity = 'elsewhere'",
            "UPDATE effect_receipt SET key_inputs_json = '{}'",
            "UPDATE effect_receipt SET state = 'reserved'",
            "UPDATE effect_receipt SET state = 'observed'",
            "UPDATE effect_event SET actor = 'forger'",
            'DELETE FROM effect_event',
            "INSERT INTO effect_event (seq, kind, actor, content_json, prev_hash, hash, recorded_at) "
            "VALUES (99, 'epoch_closed', 'x', '{}', '" + '0' * 64 + "', '" + '1' * 64 + "', 'now')",
            "INSERT INTO effect_transition VALUES ('completed', 'reserved', 'executor')",
            "DELETE FROM effect_state WHERE state = 'unknown'",
        ]
        snapshot = store.canonical_dump()
        for sql in refused:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                conn.execute(sql)
        self.assertEqual(store.canonical_dump(), snapshot)
        conn.execute('BEGIN')
        conn.execute("UPDATE effect_receipt SET result_json = '{\"outcome\":\"performed\"}'")  # first result: allowed
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE effect_receipt SET result_json = '{\"outcome\":\"x\"}'")
        conn.execute('ROLLBACK')

    def test_verify_chain_detects_an_edited_event(self):
        store = self.open()
        for name in ('e1', 'e2', 'e3'):
            store.reserve(request(name), actor='e')
        head = store.verify_chain()
        self.assertEqual((head['events'], head['receipts']), (3, 3))
        store.close()
        raw = sqlite3.connect(self.root / 'effects.sqlite')
        raw.execute('DROP TRIGGER effect_event_no_update')
        raw.execute("UPDATE effect_event SET content_json = replace(content_json, '\"e2\"', '\"e9\"') WHERE seq = 2")
        raw.commit()
        raw.close()
        with self.assertRaisesRegex(store_mod.ChainError, 'CHAIN_HASH: event 2'):
            store_mod.verify_chain(self.open().conn)


class CrashTests(EffectsTestCase):
    category = 'integration'

    def setUp(self):
        super().setUp()
        store_mod.init_effects_store(self.root, principal=ME, policy=FIXTURE)

    def test_reservation_survives_os_exit_after_commit(self):
        req = request('crash-commit')
        code, [message], err = run_worker('reserve-and-exit', str(self.root), ME, request_json(req))
        self.assertEqual(code, 0, err)
        self.assertTrue(message['created'])
        wal = self.root / 'effects.sqlite-wal'
        self.assertTrue(wal.exists() and wal.stat().st_size > 0)  # the commit lives in the WAL
        store = self.open(create=False)
        self.assertEqual(dataclasses.asdict(store.get(req.effect_key())), message['receipt'])
        self.assertEqual(store.get(req.effect_key()).state, 'reserved')
        self.assertEqual(store.verify_chain()['receipts'], 1)

    def test_kill_inside_the_reservation_transaction_leaves_nothing(self):
        req = request('crash-uncommitted')
        proc = start_worker('hold-uncommitted', str(self.root), ME, request_json(req))
        try:
            self.assertEqual(read_message(proc), {'ready': True, 'in_transaction': True})
        finally:
            stop_worker(proc)
        self.assertNotEqual(proc.returncode, 3)  # killed, not its own exit
        store = self.open(create=False)
        self.assertIsNone(store.get(req.effect_key()))
        self.assertEqual(store.events(), [])
        self.assertEqual(store.chain_head(), storecore.GENESIS_DIGEST)
        store.reserve(request('after'), actor='e')  # the write lock was released

    def test_applying_receipt_survives_crash_and_is_flagged_for_reconciliation(self):
        req = request('crash-applying')
        code, [message], err = run_worker('applying-and-exit', str(self.root), ME, request_json(req))
        self.assertEqual(code, 0, err)
        self.assertEqual(message['receipt']['state'], 'applying')
        store = self.open(create=False)
        self.assertEqual(store.get(req.effect_key()).state, 'applying')
        self.assertEqual(store.reconciliation_required(),
                         [{'effect_key': req.effect_key(), 'state': 'applying',
                           'reason': 'effect started; outcome not recorded'}])
        self.assertEqual(store.summary()['reconciliation_required'][0]['effect_key'], req.effect_key())
        store.verify_chain()


class FixtureOracle:
    """Stands in for probing the real target (G-04.4.2, G-04.5): a dict of verdicts."""

    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.probed = []

    def __call__(self, key, key_inputs):
        self.probed.append(key)
        name = key_inputs['inputs']['name']
        verdict = self.verdicts[name]
        observation = {'target': key_inputs['target_identity'],
                       'protected': verdict == 'performed' if verdict != 'indeterminate' else None}
        return store_mod.Probe(verdict, observation, oracle='fixture-oracle')


class BackupRestoreTests(EffectsTestCase):
    category = 'integration'

    def test_backup_more_receipts_restore_epoch_reconcile_and_close(self):
        store = self.open()
        a, b, c, d = (request(n) for n in ('a-done', 'b-reserved', 'c-applying', 'd-unknown'))
        key_a = store.reserve(a, actor='executor').receipt.effect_key
        store.begin(key_a, actor='executor')
        store.finish(key_a, 'completed', actor='executor', result=store_mod.EffectResult('performed', {'p': 1}))
        store.reserve(b, actor='executor')
        store.begin(store.reserve(c, actor='executor').receipt.effect_key, actor='executor')
        key_d = store.reserve(d, actor='executor').receipt.effect_key
        store.begin(key_d, actor='executor')
        store.finish(key_d, 'unknown', actor='executor', detail={'why': 'acknowledgement lost'})

        manifest = store.backup(actor='owner-elevated')
        manifest_path = self.root / 'backups' / (manifest['backup_file'] + '.manifest.json')
        at_backup = {t: table_rows(store.conn, t) for t in ('effect_receipt', 'effect_event')}
        hw_b, head_b = store.high_water_mark(), store.chain_head()
        self.assertEqual((manifest['high_water_mark'], manifest['chain_head']), (hw_b, head_b))
        self.assertEqual(manifest['store_kind'], 'effects')

        # The lost tail: effects that happen after the backup.
        e, f = request('e-lost-performed'), request('f-lost-not-performed')
        key_e = store.reserve(e, actor='executor').receipt.effect_key
        store.begin(key_e, actor='executor')
        store.finish(key_e, 'completed', actor='executor', result=store_mod.EffectResult('performed', {'p': 1}))
        store.reserve(f, actor='executor')
        store.begin(b.effect_key(), actor='executor')
        store.finish(b.effect_key(), 'completed', actor='executor',
                     result=store_mod.EffectResult('performed', {'p': 1}))
        live_head, live_hw = store.chain_head(), store.high_water_mark()
        live_dump = store.canonical_dump()
        store.close()

        # Live is ahead of the backup: a rollback, refused without explicit acceptance.
        with self.assertRaisesRegex(store_mod.RollbackRefused, 'ROLLBACK_REFUSED: the live store is ahead'):
            self.restore(manifest_path)
        self.assertEqual(os.listdir(self.root / 'backups' / 'superseded'), [])
        with self.open(create=False) as unchanged:
            self.assertEqual(unchanged.canonical_dump(), live_dump)

        report = self.restore(manifest_path, accept_rollback=True)
        self.assertTrue(report.rollback_accepted)
        self.assertEqual(report.previous_live, {'high_water_mark': live_hw, 'history_digest': live_head,
                                                'schema_version': 1})
        # The superseded live content is preserved aside, verifiably, and never deleted.
        aside = self.root / 'backups' / 'superseded' / report.superseded_copy
        aside_meta = json.loads((aside.parent / (aside.name + '.json')).read_text(encoding='utf-8'))
        self.assertEqual(aside_meta['sha256'], storecore.sha256_file(aside))
        ro = storecore.open_read_only(aside)
        self.assertEqual(store_mod._chain_head(ro), live_head)
        self.assertIsNotNone(ro.execute('SELECT 1 FROM effect_receipt WHERE effect_key = ?', (key_e,)).fetchone())
        ro.close()

        restored = self.open(create=False)
        # Receipts present at backup time are byte-identical; the chain head at the
        # backup's high-water mark is the backup's; one epoch event follows it.
        self.assertEqual(table_rows(restored.conn, 'effect_receipt'), at_backup['effect_receipt'])
        self.assertEqual(table_rows(restored.conn, 'effect_event', f'seq <= {hw_b}'), at_backup['effect_event'])
        self.assertEqual(store_mod._history_digest(restored.conn, hw_b), head_b)
        self.assertEqual(restored.high_water_mark(), hw_b + 1)
        [epoch] = restored.open_epochs()
        self.assertEqual((epoch['backup_file'], epoch['backup_high_water'], epoch['backup_chain_head'],
                          epoch['previous_live_high_water'], epoch['previous_live_chain_head'],
                          epoch['rollback_accepted'], epoch['reconciliation_status'], epoch['superseded_copy']),
                         (manifest['backup_file'], hw_b, head_b, live_hw, live_head, 1, 'required',
                          report.superseded_copy))
        self.assertIsNone(restored.get(key_e))  # knowledge lost; the effect was not

        # While the epoch is open: no reservation, no effect start (code and trigger).
        with self.assertRaises(store_mod.RestoreEpochOpen):
            restored.reserve(request('g-new'), actor='executor')
        with self.assertRaises(store_mod.RestoreEpochOpen):
            restored.begin(b.effect_key(), actor='executor')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'restore epoch is open'):
            restored.conn.execute("UPDATE effect_receipt SET state = 'applying' WHERE effect_key = ?",
                                  (b.effect_key(),))
        with self.assertRaises(store_mod.EpochNotReconciled):
            restored.close_epoch(actor='owner-elevated')

        oracle = FixtureOracle({'b-reserved': 'performed', 'c-applying': 'not_performed',
                                'd-unknown': 'indeterminate', 'e-lost-performed': 'performed',
                                'f-lost-not-performed': 'not_performed'})
        result = restored.reconcile(oracle, actor='owner-elevated', candidates=[e, f])
        self.assertEqual(result['completed'], [b.effect_key()])
        self.assertEqual(result['failed'], [c.effect_key()])
        self.assertEqual(result['unknown'], [key_d])
        self.assertEqual(result['observed_created'], [key_e])
        self.assertEqual(result['cleared'], [f.effect_key()])
        self.assertEqual(restored.get(key_e).state, 'observed')
        self.assertEqual(restored.get(key_e).origin, 'reconciliation')
        self.assertEqual(restored.get(key_d).state, 'unknown')
        # Indeterminate stops: the epoch stays open and reservations stay refused.
        with self.assertRaisesRegex(store_mod.EpochNotReconciled, 'applying or unknown'):
            restored.close_epoch(actor='owner-elevated')
        with self.assertRaises(store_mod.RestoreEpochOpen):
            restored.reserve(request('g-new'), actor='executor')

        # Only a recorded Owner attestation resolves the permanently unknown outcome.
        attested = restored.attest(key_d, outcome='performed', attested_by='owner',
                                   statement='Checked the branch protection by hand; it is in place.')
        self.assertEqual((attested.state, attested.reconciliation_status), ('completed', 'reconciled'))
        self.assertEqual(restored.close_epoch(actor='owner-elevated'), [epoch['epoch_id']])
        self.assertEqual(restored.open_epochs(), [])

        # After the epoch: reservations accepted; a performed effect is never reissued.
        self.assertTrue(restored.reserve(request('g-new'), actor='executor').created)
        again_e = restored.reserve(e, actor='executor')
        self.assertFalse(again_e.created)
        self.assertEqual(again_e.receipt.state, 'observed')
        self.assertTrue(restored.reserve(f, actor='executor').created)  # cleared: reserved normally
        verdicts = [(r['effect_key'], r['verdict'], r['action']) for r in restored.reconciliation_records()]
        self.assertEqual(verdicts, [
            (b.effect_key(), 'performed', 'transitioned'), (c.effect_key(), 'not_performed', 'transitioned'),
            (key_d, 'indeterminate', 'left_unknown'), (key_e, 'performed', 'observed_receipt_created'),
            (f.effect_key(), 'not_performed', 'cleared'), (key_d, 'attested_performed', 'transitioned')])
        chain = restored.verify_chain()
        self.assertEqual(chain['chain_head'], restored.chain_head())
        self.assertTrue(aside.exists())

    def test_a_restore_that_is_not_a_rollback_needs_no_acceptance_and_still_preserves_live(self):
        store = self.open()
        store.reserve(request('only'), actor='e')
        manifest = store.backup(actor='owner-elevated')
        store.close()
        path = self.root / 'backups' / (manifest['backup_file'] + '.manifest.json')
        report = self.restore(path)
        self.assertIsNone(report.rollback)
        self.assertTrue((self.root / 'backups' / 'superseded' / report.superseded_copy).exists())
        with self.open(create=False) as restored:
            self.assertEqual(len(restored.open_epochs()), 1)
        with self.assertRaisesRegex(store_mod.RollbackRefused, 'ahead'):  # the epoch event is newer history
            self.restore(path)

    def test_restore_needs_exclusive_custody(self):
        store = self.open()
        store.reserve(request('held'), actor='e')
        manifest = store.backup(actor='owner-elevated')
        store.close()
        proc = start_worker('hold-open', str(self.root), ME)
        try:
            self.assertEqual(read_message(proc), {'ready': True})
            with self.assertRaisesRegex(store_mod.RestoreRefused, 'EXCLUSIVE_CUSTODY'):
                self.restore(self.root / 'backups' / (manifest['backup_file'] + '.manifest.json'))
        finally:
            stop_worker(proc)
        self.assertEqual(os.listdir(self.root / 'backups' / 'superseded'), [])

    def test_backup_and_restore_never_copy_live_files(self):
        store = self.open()
        store.reserve(request('copy-check'), actor='e')

        def forbidden(*args, **kwargs):
            raise AssertionError(f'file copy used: {args}')
        patches = [mock.patch.object(shutil, name, forbidden)
                   for name in ('copy', 'copy2', 'copyfile', 'copyfileobj', 'copytree', 'move')]
        patches.append(mock.patch.object(os, 'link', forbidden))
        for p in patches:
            p.start()
        try:
            manifest = store.backup(actor='owner-elevated')
            store.close()
            self.restore(self.root / 'backups' / (manifest['backup_file'] + '.manifest.json'))
        finally:
            for p in patches:
                p.stop()
        backup = self.root / 'backups' / manifest['backup_file']
        self.assertEqual(backup.read_bytes()[18:20], b'\x01\x01')  # rollback journal: a backup-API copy
        # A copy of the live WAL-mode file, even with a matching manifest, is refused.
        fake_dir = self.tmp / 'fake'
        fake_dir.mkdir()
        fake = fake_dir / manifest['backup_file']
        fake.write_bytes((self.root / 'effects.sqlite').read_bytes())
        fake_manifest = dict(manifest, sha256=storecore.sha256_file(fake), size=fake.stat().st_size)
        (fake_dir / (fake.name + '.manifest.json')).write_text(json.dumps(fake_manifest), encoding='utf-8')
        with self.assertRaisesRegex(store_mod.BackupError, 'BACKUP_NOT_A_BACKUP_COPY'):
            storecore.verify_backup(fake_dir / (fake.name + '.manifest.json'), store_mod.KIND)


class ManifestCheckTests(EffectsTestCase):
    def setUp(self):
        super().setUp()
        store = self.open()
        store.reserve(request('m1'), actor='e')
        self.manifest = store.backup(actor='owner-elevated')
        self.manifest_path = self.root / 'backups' / (self.manifest['backup_file'] + '.manifest.json')
        store.reserve(request('m2'), actor='e')
        store.close()
        with self.open(create=False) as live:
            self.live_dump = live.canonical_dump()

    def assert_live_unchanged(self):
        with self.open(create=False) as live:
            self.assertEqual(live.canonical_dump(), self.live_dump)
            self.assertEqual(live.open_epochs(), [])
        self.assertEqual(os.listdir(self.root / 'backups' / 'superseded'), [])

    def test_tampered_backup_file_is_refused(self):
        backup = self.root / 'backups' / self.manifest['backup_file']
        data = bytearray(backup.read_bytes())
        data[-100] ^= 0xFF
        backup.write_bytes(bytes(data))
        with self.assertRaisesRegex(store_mod.BackupError, 'BACKUP_TAMPERED'):
            self.restore(self.manifest_path, accept_rollback=True)
        self.assert_live_unchanged()

    def test_manifest_and_copy_disagreeing_is_refused(self):
        manifest = dict(self.manifest, chain_head='f' * 64)
        self.manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaisesRegex(store_mod.BackupError, 'BACKUP_TAMPERED: chain_head'):
            self.restore(self.manifest_path, accept_rollback=True)
        self.assert_live_unchanged()

    def test_backup_of_the_other_store_kind_is_refused_both_ways(self):
        db_dir = self.tmp / 'integration-state'
        db_dir.mkdir()
        with integration_mod.open_store(db_dir / 'integration.sqlite') as integration:
            integration.reserve('op-1', {'x': 1}, actor='t')
            integration_manifest = integration.backup(actor='owner')
        path = db_dir / 'backups' / (integration_manifest['backup_file'] + '.manifest.json')
        with self.assertRaisesRegex(store_mod.WrongStoreKind, 'BACKUP_WRONG_KIND'):
            self.restore(path, accept_rollback=True)
        self.assert_live_unchanged()
        with self.assertRaisesRegex(integration_mod.WrongStoreKind, 'BACKUP_WRONG_KIND'):
            integration_mod.restore_store(db_dir / 'integration.sqlite', self.manifest_path, actor='owner')

    def test_backup_from_a_newer_schema_is_refused(self):
        migrations = self.tmp / 'migrations'
        shutil.copytree(store_mod.MIGRATIONS_DIR, migrations)
        (migrations / '0002_future.sql').write_text('CREATE TABLE future_thing (id INTEGER PRIMARY KEY) STRICT;\n',
                                                    encoding='utf-8')
        newer_kind = dataclasses.replace(store_mod.KIND, migrations_dir=migrations)
        newer_dir = make_root(self.tmp / 'newer-root')
        conn = storecore.connect(newer_dir / 'effects.sqlite')
        self.addCleanup(conn.close)
        storecore.migrate(conn, newer_kind)
        (newer_dir / 'backups').mkdir()
        newer_manifest = storecore.backup_store(conn, newer_kind, newer_dir / 'backups', actor='owner')
        self.assertEqual(newer_manifest['schema_version'], 2)
        path = newer_dir / 'backups' / (newer_manifest['backup_file'] + '.manifest.json')
        with self.assertRaisesRegex(store_mod.MigrationError, 'BACKUP_SCHEMA_NEWER'):
            self.restore(path, accept_rollback=True)
        self.assert_live_unchanged()

    def test_retention_keeps_the_newest_and_an_open_epochs_source(self):
        with self.open(create=False) as store:
            second = store.backup(actor='owner')
            third = store.backup(actor='owner')
        self.restore(self.manifest_path, accept_rollback=True)  # the oldest is now an open epoch's source
        with self.open(create=False) as store:
            deleted = store.prune_backups(keep_last=1)
            self.assertEqual(deleted, [second['backup_file']])
            remaining = sorted(p.name for p in (self.root / 'backups').glob('*.sqlite'))
            self.assertEqual(remaining, sorted([self.manifest['backup_file'], third['backup_file']]))
            self.assertEqual(len(list((self.root / 'backups' / 'superseded').glob('*.sqlite'))), 1)
            with self.assertRaises(store_mod.BackupError):
                store.prune_backups(keep_last=0)


class LocationTests(EffectsTestCase):
    category = 'contract'

    def assert_refused(self, root, code, policy=FIXTURE, **kwargs):
        with self.assertRaises(store_mod.LocationRefused) as caught:
            store_mod.open_effects_store(root, principal=ME, policy=policy, create=True, **kwargs)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        return caught.exception

    def test_lexical_refusals_never_touch_the_filesystem(self):
        guest_root = store_mod.declared_guest_state_roots()
        self.assertIn(Path('D:\\aieh-guest-state'), guest_root)  # declared by the QEMU/WHPX profile
        integration_tree = storecore.harness_state_root() if WINDOWS or os.environ.get('HOME') else None
        cases = [
            ('', 'LOCATION_MEMORY_OR_URI'), (':memory:', 'LOCATION_MEMORY_OR_URI'),
            ('file:effects.sqlite?mode=memory', 'LOCATION_MEMORY_OR_URI'),
            ('\\\\server\\share\\effects', 'LOCATION_UNC'), ('//server/share/effects', 'LOCATION_UNC'),
            (str(REPO / 'integrations' / 'effects'), 'LOCATION_REPOSITORY'),
            (str(REPO.parent), 'LOCATION_REPOSITORY'),  # a root containing the checkout
            ('D:\\aieh-guest-state\\effects', 'LOCATION_GUEST_STATE'),
            (str(integration_tree / 'state' / 'effects'), 'LOCATION_INTEGRATION_TREE'),
        ]
        with mock.patch.object(store_mod, '_filesystem_checks',
                               side_effect=AssertionError('filesystem touched for a lexical refusal')):
            for root, code in cases:
                with self.subTest(root=root):
                    self.assert_refused(root, code)
            with self.subTest('profile root, live policy'):
                self.assert_refused(self.root, 'LOCATION_PROFILE_ROOT', policy=store_mod.LIVE_POLICY)
            with self.subTest('caller-declared guest-state root'):
                self.assert_refused(self.root, 'LOCATION_GUEST_STATE', extra_guest_roots=[self.tmp])
            with self.subTest('caller-declared integration tree'):
                self.assert_refused(self.root, 'LOCATION_INTEGRATION_TREE', integration_roots=[self.root / 'x'])

    def test_missing_root_is_refused_and_never_created(self):
        missing = self.tmp / 'not-created'
        self.assert_refused(missing, 'LOCATION_MISSING_ROOT')
        self.assertFalse(missing.exists())

    def test_co_located_integration_store_is_refused(self):
        (self.root / 'integration.sqlite').write_bytes(b'')
        self.assert_refused(self.root, 'LOCATION_CO_LOCATED')

    def test_profile_rules_cover_windows_and_posix_profile_roots(self):
        win = store_mod.user_profile_roots({'USERPROFILE': 'C:\\Users\\you', 'LOCALAPPDATA':
                                            'C:\\Users\\you\\AppData\\Local', 'SystemDrive': 'C:'}, 'win32')
        self.assertIn(Path('C:\\Users\\you'), win)
        self.assertIn(Path('C:\\Users'), win)
        self.assertIn(Path('C:\\Users\\you\\AppData\\Local'), win)
        posix = store_mod.user_profile_roots({'HOME': '/home/user'}, 'linux')
        self.assertEqual(posix[:2], [Path('/home/user'), Path('/home')])

    def test_cli_has_no_fixture_policy_and_refuses_a_profile_root(self):
        cmd = [sys.executable, '-I', '-B', str(MODULE)]
        refused = subprocess.run(cmd + ['init', '--root', str(self.root)], capture_output=True, text=True,
                                 encoding='utf-8', timeout=WAIT_CEILING_S)
        self.assertEqual(refused.returncode, 1)
        self.assertIn('REFUSED: LOCATION_PROFILE_ROOT', refused.stderr)
        self.assertFalse((self.root / 'effects.sqlite').exists())
        for flag in ('--policy', '--fixture', '--fixture-policy'):
            with self.subTest(flag=flag):
                unknown = subprocess.run(cmd + ['init', '--root', str(self.root), flag, 'fixture'],
                                         capture_output=True, text=True, encoding='utf-8', timeout=WAIT_CEILING_S)
                self.assertEqual(unknown.returncode, 2)
                self.assertIn('unrecognized arguments', unknown.stderr)
        source = inspect.getsource(store_mod.main)
        self.assertNotIn('fixture', source)
        self.assertIn("'policy': LIVE_POLICY", source)
        missing = subprocess.run(cmd + ['init'], capture_output=True, text=True, encoding='utf-8',
                                 timeout=WAIT_CEILING_S)
        self.assertEqual(missing.returncode, 2)  # --root is required: there is no default path
        self.assertIn('--root', missing.stderr)


@unittest.skipUnless(WINDOWS, 'the custody fixtures use the Windows security API')
class CustodyTests(EffectsTestCase):
    category = 'integration'

    def assert_custody_refused(self, root, expected_codes, principal=ME, exact=False):
        with self.assertRaises(custody.CustodyRefused) as caught:
            store_mod.open_effects_store(root, principal=principal, policy=FIXTURE, create=True)
        codes = caught.exception.codes
        if exact:
            self.assertEqual(codes, expected_codes, str(caught.exception))
        else:
            for code in expected_codes:
                self.assertIn(code, codes, str(caught.exception))
        self.assertFalse((root / 'effects.sqlite').exists())
        return caught.exception

    def test_conforming_root_opens_and_reads_back_its_template(self):
        info = custody.read_security(self.root)
        self.assertEqual(info.owner_sid, ME)
        self.assertTrue(info.dacl_protected)
        self.assertEqual(sorted(a.sid for a in info.aces), sorted([custody.SYSTEM_SID, custody.ADMINISTRATORS_SID, ME]))
        self.assertFalse(any(a.inherited for a in info.aces))
        with self.open() as store:
            db_info = custody.read_security(store.path)
            self.assertTrue(all(a.inherited for a in db_info.aces))  # the file inherits from the protected root
        self.open(create=False).close()

    def test_extra_ace_is_refused_by_name(self):
        root = make_root(self.tmp / 'extra', CONFORMING_SDDL + '(A;OICI;0x1200a9;;;BU)')
        error = self.assert_custody_refused(root, [custody.EXTRA_ACE], exact=True)
        self.assertIn('S-1-5-32-545 (BUILTIN\\Users)', str(error))

    def test_default_temporary_directory_acl_is_refused(self):
        default = Path(tempfile.mkdtemp(dir=self.tmp))  # Python's own protected DACL includes OWNER RIGHTS
        error = self.assert_custody_refused(default, [custody.EXTRA_ACE])
        self.assertIn('S-1-3-4 (OWNER RIGHTS)', str(error))

    def test_inherited_aces_are_refused_by_name(self):
        root = make_root(self.tmp / 'inherits')
        result = subprocess.run(['icacls', str(root), '/inheritance:e'], capture_output=True, text=True,
                                timeout=WAIT_CEILING_S)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_custody_refused(root, [custody.INHERITANCE_ENABLED, custody.INHERITED_ACE_FOUND])

    def test_wrong_owner_is_refused_by_name(self):
        root = make_root(self.tmp / 'interim', INTERIM_SDDL)  # exactly SYSTEM and Administrators...
        # ...but owned by the (non-elevated) test account, not Administrators or SYSTEM.
        error = self.assert_custody_refused(root, [custody.WRONG_OWNER], principal=None, exact=True)
        self.assertIn(f'owner {ME} is not one of', str(error))

    def test_store_file_is_checked_on_every_open(self):
        store_mod.init_effects_store(self.root, principal=ME, policy=FIXTURE)
        db = self.root / 'effects.sqlite'
        result = subprocess.run(['icacls', str(db), '/grant', '*S-1-1-0:(R)'], capture_output=True, text=True,
                                timeout=WAIT_CEILING_S)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with self.assertRaises(custody.CustodyRefused) as caught:
            store_mod.open_effects_store(self.root, principal=ME, policy=FIXTURE)
        self.assertEqual(caught.exception.codes, [custody.EXTRA_ACE])
        self.assertIn('S-1-1-0 (Everyone)', str(caught.exception))


class CustodyEvaluationTests(unittest.TestCase):
    """The pure comparison, on synthetic read-backs (every platform)."""

    def test_windows_rules(self):
        template = custody.CustodyTemplate('S-1-5-21-1-2-3-1001')
        ace = custody.Ace
        good = custody.SecurityInfo(custody.ADMINISTRATORS_SID, True, True,
                                    (ace(0, 3, 0x1F01FF, custody.SYSTEM_SID),
                                     ace(0, 3, 0x1F01FF, custody.ADMINISTRATORS_SID),
                                     ace(0, 3, 0x1301BF, 'S-1-5-21-1-2-3-1001')))
        self.assertEqual(custody.evaluate_windows(good, template, is_root=True), [])
        null = dataclasses.replace(good, dacl_present=False, aces=())
        self.assertEqual([c for c, _ in custody.evaluate_windows(null, template, is_root=True)], [custody.NULL_DACL])
        odd = dataclasses.replace(good, aces=(ace(5, 0, 0x1, '<ace type 5>'),))
        self.assertIn(custody.UNSUPPORTED_ACE, [c for c, _ in custody.evaluate_windows(odd, template, is_root=True)])
        child = dataclasses.replace(good, dacl_protected=False, aces=tuple(
            dataclasses.replace(a, flags=0x10) for a in good.aces))
        self.assertEqual(custody.evaluate_windows(child, template, is_root=False), [])
        self.assertEqual([c for c, _ in custody.evaluate_windows(child, template, is_root=True)],
                         [custody.INHERITANCE_ENABLED] + [custody.INHERITED_ACE_FOUND] * 3)
        interim = custody.CustodyTemplate(None)
        self.assertEqual([c for c, _ in custody.evaluate_windows(good, interim, is_root=True)], [custody.EXTRA_ACE])

    def test_posix_rules(self):
        template = custody.CustodyTemplate(1001)
        self.assertEqual(custody.evaluate_posix(stat.S_IFDIR | 0o700, 1001, template, is_dir=True), [])
        self.assertEqual(custody.evaluate_posix(stat.S_IFREG | 0o600, 1001, template, is_dir=False), [])
        self.assertEqual([c for c, _ in custody.evaluate_posix(stat.S_IFDIR | 0o755, 1001, template, is_dir=True)],
                         [custody.WRONG_MODE])
        self.assertEqual([c for c, _ in custody.evaluate_posix(stat.S_IFDIR | 0o700, 0, template, is_dir=True)],
                         [custody.WRONG_OWNER])
        self.assertEqual(custody.evaluate_posix(stat.S_IFDIR | 0o700, 0, custody.CustodyTemplate(None),
                                                is_dir=True), [])


class IsolationTests(EffectsTestCase):
    def test_attach_is_impossible(self):
        store = self.open()
        other = self.tmp / 'other.sqlite'
        for sql in (f"ATTACH DATABASE '{other}' AS other", "ATTACH DATABASE ':memory:' AS other"):
            with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.OperationalError, 'too many attached'):
                store.conn.execute(sql)
        self.assertFalse(other.exists())

    def test_a_file_of_the_other_store_kind_is_refused_both_ways(self):
        integration_mod.open_store(self.root / 'effects.sqlite').close()  # an integration store in disguise
        with self.assertRaisesRegex(store_mod.WrongStoreKind, 'is not an effects store'):
            store_mod.open_effects_store(self.root, principal=ME, policy=FIXTURE)
        other = make_root(self.tmp / 'real-effects')
        store_mod.init_effects_store(other, principal=ME, policy=FIXTURE)
        with self.assertRaisesRegex(integration_mod.WrongStoreKind, 'is not an integration store'):
            integration_mod.open_store(other / 'effects.sqlite')


class SurfaceTests(unittest.TestCase):
    """Library and command line only: no network endpoint, no MCP tool, no agent surface."""
    category = 'contract'

    FORBIDDEN = {'socket', 'socketserver', 'http', 'urllib', 'asyncio', 'ssl', 'xmlrpc', 'selectors', 'ftplib',
                 'smtplib', 'wsgiref', 'multiprocessing', 'mcp', 'requests', 'aiohttp', 'flask', 'fastapi'}

    def test_no_network_or_server_imports(self):
        for path in (MODULE, EFFECTS_DIR / 'effects_custody.py', storecore.HERE / 'storecore.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split('.')[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split('.')[0])
            with self.subTest(path=path.name):
                self.assertEqual(imported & self.FORBIDDEN, set())

    def test_cli_commands_are_exactly_the_documented_ones(self):
        result = subprocess.run([sys.executable, '-I', '-B', str(MODULE), '--help'], capture_output=True, text=True,
                                encoding='utf-8', timeout=WAIT_CEILING_S)
        self.assertEqual(result.returncode, 0)
        self.assertIn('{init,status,backup,restore,verify-chain}', result.stdout)


if __name__ == '__main__':
    unittest.main()
