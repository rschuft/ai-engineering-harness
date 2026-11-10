"""Tests of gitea_host.py composed over the host-service lifecycle contract (plan leaf F-06.2).

Every test works in a temporary managed root named through an injected AIEH_DATA_ROOT, never the real one,
with a fake Gitea binary and CLI; no Gitea runs, no socket is opened and no credential store is touched
(the processes are faked through gitea_host.live and the health probe through gitea_host.healthy). The
transitions run end to end over a real SQLite database and app.ini in that root. The pinned Gitea's restart,
inspect, readiness, recover and uninstall are exercised live by test_gitea_host.TestLive (opt-in).
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
WINDOWS = sys.platform == 'win32'


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


G = _load('aieh_gitea_host', HERE.parent / 'gitea_host.py')
C, W, P = G.contract, G.windows, G.paths
K = G.credentials  # integrations/credentials/credential_provider.py (plan leaf F-06.3)
PIN = G.pin()
FAKE_BINARY = b'not gitea, a fixture'
FAKE_PIN = dict(PIN, sha256=hashlib.sha256(FAKE_BINARY).hexdigest())
NEXT = '28.4.0'
NEXT_BINARY = b'not gitea either, the next fixture'
NEXT_PIN = dict(PIN, name=G.asset_name(NEXT), sha256=hashlib.sha256(NEXT_BINARY).hexdigest())
windows_only = unittest.skipUnless(WINDOWS, 'the Windows adapter')


def fake_pin(repo=G.REPO, version=G.VERSION):
    return {G.VERSION: FAKE_PIN, NEXT: NEXT_PIN}[version]


class FakeRun:
    """subprocess.run on the Gitea CLI: generate secret only."""

    def __call__(self, argv, **kwargs):
        args = argv[argv.index('--config') + 2:] if '--config' in argv else argv[1:]
        out = f'{args[2].lower()}-generated\n'.encode() if args[:2] == ['generate', 'secret'] else b''
        return SimpleNamespace(returncode=0, stdout=out, stderr=b'')


SHARED = {}  # the module's one managed root (setUpModule), shared by the Root classes


def setUpModule():
    """One temporary managed root for the module, with the fake asset acquired, app.ini written and a
    SQLite database (F-09.3: a shared fixture)."""
    tmp = Path(tempfile.mkdtemp(prefix='gl-'))
    env = {'AIEH_DATA_ROOT': str(tmp / 'root')}
    env['LOCALAPPDATA' if WINDOWS else 'HOME'] = str(tmp / 'home')
    res = P.resolve(env, config={})
    lay = G.layout(res)
    SHARED.update(tmp=tmp, res=res, lay=lay)
    P.init(res)
    G.ensure_dirs(res, lay)
    source = tmp / 'source.exe'
    source.write_bytes(FAKE_BINARY)
    G.acquire(res, lay, FAKE_PIN, from_file=source)
    G.configure(res, lay, FAKE_PIN, 13300, run=FakeRun())
    db = sqlite3.connect(lay.db)
    with db:
        db.execute('create table t (v text)')
        db.execute("insert into t values ('before')")
    db.close()
    SHARED['snapshot'] = {path: path.read_bytes() for path in (lay.host_record, lay.config, lay.db)}
    SHARED['added'] = (lay.run / 'transitions', lay.home / 'backups', G.layout(res, NEXT).asset_dir, lay.run_record)


def tearDownModule():
    if 'tmp' in SHARED:
        shutil.rmtree(SHARED['tmp'], ignore_errors=True)


class Root(unittest.TestCase):
    """The module's managed root, with live, healthy and pin faked. setUp puts back every file a test may
    change and removes everything a test may add, so each test starts from the same state."""

    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.res, cls.lay = SHARED['tmp'], SHARED['res'], SHARED['lay']
        cls.snapshot, cls.added = SHARED['snapshot'], SHARED['added']
        cls.patchers = [mock.patch.object(G, 'live', return_value=None),
                        mock.patch.object(G, 'healthy', return_value=False),
                        mock.patch.object(G, 'pin', side_effect=fake_pin)]
        for patcher in cls.patchers:
            patcher.start()

    @classmethod
    def tearDownClass(cls):
        for patcher in cls.patchers:
            patcher.stop()

    def setUp(self):
        for path, data in self.snapshot.items():
            path.write_bytes(data)
        for path in self.added:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        for child in self.lay.tmp.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()

    def host_record(self):
        return json.loads(self.lay.host_record.read_text(encoding='utf-8'))


class TestComposition(unittest.TestCase):
    def test_one_error_kind_and_the_moved_names(self):
        self.assertIs(G.GiteaError, C.LifecycleError)
        self.assertIs(G.CredentialProvider, C.CredentialProvider)
        for name in ('Proc', 'KillOnCloseJob', 'JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE'):
            self.assertIs(getattr(G, name), getattr(W, name))
        for name in ('CredentialStore', 'WindowsCredentialProvider'):  # moved on to integrations/credentials
            self.assertIs(getattr(G, name), getattr(K, name))
        self.assertIs(K.CredentialProvider, C.CredentialProvider)
        self.assertEqual(G.RUN_FORMAT, 'aieh-service-run/1')
        self.assertEqual((G.ASSET_NAME, G.asset_name('28.4.0')), ('gitea-28.3.0-windows-amd64.exe',
                                                                 'gitea-28.4.0-windows-amd64.exe'))

    def test_the_lock_pins_one_windows_version(self):
        self.assertEqual(G.pinned_versions(), ['28.3.0'])

    @windows_only
    def test_the_adapter_and_its_credential_provider(self):
        self.assertIsInstance(G.platform(), W.WindowsAdapter)
        self.assertEqual(G.platform().asset_key, G.ASSET_KEY)
        self.assertIsInstance(G.credential_provider(), K.WindowsCredentialProvider)
        guard = C.ExposureGuard()
        with mock.patch.object(G, 'ACT_GUARD', guard):  # inside an act every secret it handles is held
            provider = G.credential_provider()
        self.assertIsInstance(provider, C.WatchedProvider)
        self.assertIs(provider.guard, guard)

    def test_without_an_adapter_there_is_no_credential_provider(self):
        unsupported = C.LifecycleError('PLATFORM_UNSUPPORTED', 'no lifecycle adapter for this system')
        with mock.patch.object(G, '_ADAPTER', None), \
                mock.patch.object(C, 'select_adapter', side_effect=unsupported), \
                self.assertRaises(G.GiteaError) as caught:
            G.credential_provider()
        self.assertEqual(caught.exception.code, 'NO_CREDENTIAL_PROVIDER')


class TestRecords(Root):
    def test_install_records_the_platform_asset_key(self):
        self.assertEqual(self.host_record()['platform'], {'asset_key': 'windows-amd64'})

    @windows_only
    def test_a_record_of_another_platform_is_refused(self):
        self.assertEqual(G.check_platform(self.lay), 'windows-amd64')
        record = self.host_record()
        record['platform']['asset_key'] = 'linux-amd64'
        self.lay.host_record.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaises(G.GiteaError) as caught:
            G.check_platform(self.lay)
        self.assertEqual(caught.exception.code, 'PLATFORM_MISMATCH')
        del record['platform']  # an F-06.1 record carries no key and passes
        self.lay.host_record.write_text(json.dumps(record), encoding='utf-8')
        self.assertIsNone(G.check_platform(self.lay))

    def test_both_run_record_formats_are_read(self):
        for fmt in ('aieh-gitea-run/1', 'aieh-service-run/1'):
            self.lay.run_record.write_text(json.dumps({'format': fmt, 'state': 'stopped'}), encoding='utf-8')
            self.assertEqual(G.read_run_record(self.lay)['format'], fmt)
        self.lay.run_record.write_text(json.dumps({'format': 'other/1'}), encoding='utf-8')
        self.assertIsNone(G.read_run_record(self.lay))

    def test_the_desired_layout_follows_the_host_record(self):
        self.assertEqual(G.desired_layout(self.res).version, G.VERSION)
        record = self.host_record()
        record['version'] = NEXT
        self.lay.host_record.write_text(json.dumps(record), encoding='utf-8')
        lay = G.desired_layout(self.res)
        self.assertEqual((lay.version, lay.binary.name, lay.config), (NEXT, G.asset_name(NEXT), self.lay.config))
        record['version'] = '../28.3.0'
        self.lay.host_record.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaises(G.GiteaError) as caught:
            G.desired_layout(self.res)
        self.assertEqual(caught.exception.code, 'VERSION_MISMATCH')

    @windows_only
    def test_readiness_carries_the_platform_and_verify_s_verdicts(self):
        checks = {name: True for name in G.READINESS_NAMES}
        checks['token_not_elevated'] = False
        record = G.readiness({'checks': checks, 'passed': False})
        self.assertEqual(record['format'], 'aieh-readiness/1')
        self.assertEqual(record['platform'], C.platform_record(G.platform()))
        self.assertEqual(set(record['checks']), set(G.READINESS_NAMES.values()))
        self.assertEqual(len(set(G.READINESS_NAMES.values())), len(G.READINESS_NAMES))
        self.assertEqual((record['checks']['service_not_elevated'], record['passed']), (False, False))
        for broken in ({k: v for k, v in checks.items() if k != 'config_settings'}, {**checks, 'new_check': True}):
            with self.assertRaises(G.GiteaError) as caught:
                G.readiness({'checks': broken})
            self.assertEqual(caught.exception.code, 'READINESS_UNMAPPED')


@windows_only
class TestInspect(Root):
    def test_a_stopped_instance(self):
        report = G.inspect(self.res, self.lay, FAKE_PIN)
        self.assertEqual(report['platform'], C.platform_record(G.platform()))
        self.assertEqual(report['versions'], {'desired': G.VERSION, 'staged': [G.VERSION], 'running': None})
        self.assertEqual((report['running'], report['healthz'], report['service_process'], report['supervision']),
                         (False, False, None, None))
        self.assertEqual(report['transitions'], {'pending': None, 'latest': None})
        self.assertEqual(report['host_record']['platform_asset_key'], 'windows-amd64')

    def test_it_writes_nothing(self):
        before = sorted(str(p) for p in self.lay.root.rglob('*'))
        G.inspect(self.res, self.lay, FAKE_PIN)
        self.assertEqual(sorted(str(p) for p in self.lay.root.rglob('*')), before)

    def test_running_version_names_the_staged_asset_of_the_image(self):
        self.assertEqual(G.running_version(self.res, self.lay, str(self.lay.binary)), G.VERSION)
        self.assertEqual(G.running_version(self.res, self.lay, str(self.tmp / 'gitea.exe')), 'unknown')
        self.assertIsNone(G.running_version(self.res, self.lay, None))


@windows_only
class TestOperations(Root):
    def setUp(self):
        super().setUp()
        self.ops = G.GiteaOperations(self.res)

    def rows(self):
        db = sqlite3.connect(self.lay.db)
        try:
            return [r[0] for r in db.execute('select v from t')]
        finally:
            db.close()

    def test_backup_and_restore_of_the_database_and_app_ini(self):
        ini = self.lay.config.read_bytes()
        report = self.ops.backup('t1')
        self.assertEqual(set(report['bytes']), {'gitea.db', 'app.ini'})
        self.assertTrue(Path(report['directory']).is_relative_to(self.lay.home))
        db = sqlite3.connect(self.lay.db)
        with db:
            db.execute("update t set v = 'after'")
        db.close()
        self.lay.config.write_bytes(ini + b'; changed\n')
        self.ops.restore('t1')
        self.assertEqual((self.rows(), self.lay.config.read_bytes()), (['before'], ini))

    def test_set_desired_keeps_everything_but_the_version(self):
        before = self.host_record()
        self.ops.set_desired(NEXT)
        after = self.host_record()
        self.assertEqual((after['version'], after['asset'], after['sha256']),
                         (NEXT, G.asset_name(NEXT), NEXT_PIN['sha256']))
        self.assertEqual({k: v for k, v in after.items() if k not in ('version', 'asset', 'sha256')},
                         {k: v for k, v in before.items() if k not in ('version', 'asset', 'sha256')})

    def test_stage_verifies_the_target_against_its_pin(self):
        source = self.tmp / 'next.exe'
        source.write_bytes(NEXT_BINARY)
        ops = G.GiteaOperations(self.res, from_file=source)
        self.assertTrue(ops.stage(NEXT)['acquired'])
        self.assertEqual(G.staged_versions(self.lay), [G.VERSION, NEXT])
        self.assertEqual(P.read_asset_record(G.layout(self.res, NEXT).asset_dir)['integrity']['sha256'],
                         {G.asset_name(NEXT): NEXT_PIN['sha256']})
        self.assertTrue(self.lay.binary.is_file())  # side by side: the current asset is untouched

    def test_a_staged_asset_that_does_not_match_its_pin_never_enters_the_assets(self):
        source = self.tmp / 'next.exe'
        source.write_bytes(b'tampered')
        with self.assertRaises(G.GiteaError) as caught:
            G.GiteaOperations(self.res, from_file=source).stage(NEXT)
        self.assertEqual(caught.exception.code, 'DOWNLOAD_MISMATCH')
        self.assertFalse(G.layout(self.res, NEXT).binary.exists())

    def test_upgrade_refusals_write_no_record(self):
        for target, pinned, code in ((NEXT, None, 'VERSION_MISMATCH'),
                                     ('27.0.0', ['27.0.0', G.VERSION], 'DOWNGRADE_REFUSED')):
            with self.subTest(target=target), \
                    mock.patch.object(G, 'pinned_versions', return_value=pinned or [G.VERSION]), \
                    self.assertRaises(G.GiteaError) as caught:
                G.upgrade(self.res, self.lay, FAKE_PIN, target)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(G.upgrade(self.res, self.lay, FAKE_PIN, G.VERSION)['upgrade'], 'noop')
        self.assertEqual(G.transitions(self.lay).records(), [])

    def test_an_upgrade_that_never_becomes_ready_is_rolled_back_from_its_backup(self):
        source = self.tmp / 'next.exe'
        source.write_bytes(NEXT_BINARY)
        started = []

        def up(res, lay, pinned):
            started.append(lay.version)
            if lay.version == NEXT:  # the "new version" migrates the database, then never answers
                db = sqlite3.connect(self.lay.db)
                with db:
                    db.execute("update t set v = 'migrated'")
                db.close()
            return {'running': True, 'supervisor': {'pid': 1}, 'gitea': {'pid': 2}}
        with mock.patch.object(G, 'pinned_versions', return_value=[G.VERSION, NEXT]), \
                mock.patch.object(G, 'up', side_effect=up):
            record = G.upgrade(self.res, self.lay, FAKE_PIN, NEXT, from_file=source)
        self.assertEqual(record['state'], 'rolled-back')
        self.assertEqual(C.done_steps(record), ['staged', 'backed-up', 'desired-set', 'started', 'rollback-started',
                                                'restored', 'desired-reset'])
        self.assertEqual((started, self.rows(), self.host_record()['version']), ([NEXT], ['before'], G.VERSION))
        self.assertTrue(G.layout(self.res, NEXT).binary.is_file())  # the staged asset stays
        self.assertEqual(G.transitions(self.lay).latest()['id'], record['id'])

    def test_uninstall_keeps_persistent_state_and_assets(self):
        (self.lay.tmp / 'scratch.txt').write_text('x', encoding='utf-8')
        running = SimpleNamespace(image=lambda: str(self.lay.binary))
        with mock.patch.object(G, 'live', return_value=running), self.assertRaises(G.GiteaError) as caught:
            G.uninstall(self.res, self.lay, FAKE_PIN)
        self.assertEqual(caught.exception.code, 'UNINSTALL_RUNNING')
        record = G.uninstall(self.res, self.lay, FAKE_PIN)
        self.assertEqual(record['state'], 'completed')
        self.assertEqual(list(self.lay.tmp.iterdir()), [])  # emptied; the directory stays for Gitea's TMP
        self.assertEqual(record['steps'][0]['result']['removed'], [str(self.lay.tmp / 'scratch.txt')])
        for kept in (self.lay.config, self.lay.db, self.lay.host_record, self.lay.binary,
                     self.lay.asset_dir / P.ASSET_RECORD_NAME):
            self.assertTrue(kept.is_file(), kept)
        self.assertEqual(record['retained']['assets'], [str(self.lay.asset_dir)])

    def test_a_pending_transition_refuses_others_until_recover(self):
        log = G.transitions(self.lay)
        log.begin('uninstall', {'desired': G.VERSION})
        for verb in (lambda: G.uninstall(self.res, self.lay, FAKE_PIN),
                     lambda: G.upgrade(self.res, self.lay, FAKE_PIN, G.VERSION),
                     lambda: G.restart(self.res, self.lay, FAKE_PIN)):
            with self.assertRaises(G.GiteaError) as caught:
                verb()
            self.assertEqual(caught.exception.code, 'TRANSITION_PENDING')
        result = G.recover(self.res, self.lay, FAKE_PIN)
        self.assertEqual((result['verb'], result['transition']['state']), ('uninstall', 'completed'))
        self.assertEqual(G.recover(self.res, self.lay, FAKE_PIN)['pending'], None)


class TestCommandLine(unittest.TestCase):
    """main(): every act ends with the I7 scan of what it shows; an exposure withholds the output."""

    def run_main(self, argv, status=None):
        tmp = Path(tempfile.mkdtemp(prefix='gl-'))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        out, err = io.StringIO(), io.StringIO()
        patches = [mock.patch.dict(os.environ, {'AIEH_DATA_ROOT': str(tmp / 'root')}),
                   mock.patch.object(G.paths, 'load_config', return_value=None),
                   mock.patch('sys.stdout', out), mock.patch('sys.stderr', err)]
        if status is not None:
            patches.append(mock.patch.object(G, 'status', side_effect=status))
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        code = G.main(argv)
        return code, out.getvalue(), err.getvalue()

    @windows_only
    def test_a_clean_act_is_shown_with_the_scan_result(self):
        code, out, err = self.run_main(['status'], status=lambda *a: {'state': 'fine'})
        self.assertEqual((code, json.loads(out)), (0, {'state': 'fine'}))
        self.assertIn('I7 no-exposure scan: clean (0 secrets held; 2 outputs scanned)', err)

    @windows_only
    def test_a_token_shaped_string_withholds_the_output(self):
        code, out, err = self.run_main(['status'], status=lambda *a: {'leak': 'ab' * 20})
        self.assertEqual((code, out), (1, ''))
        self.assertIn('EXPOSURE_FOUND', err)
        self.assertIn('remedy:', err)
        self.assertNotIn('ab' * 20, err)

    @windows_only
    def test_a_secret_the_act_held_withholds_the_output(self):
        def leaky(*args):
            G.ACT_GUARD.hold('fixture-secret-held-by-the-act')
            return {'oops': 'x fixture-secret-held-by-the-act'}
        code, out, err = self.run_main(['status'], status=leaky)
        self.assertEqual((code, out), (1, ''))
        self.assertIn('EXPOSURE_FOUND', err)
        self.assertNotIn('fixture-secret-held-by-the-act', err)
        self.assertIsNone(G.ACT_GUARD)

    def test_an_unsupported_platform_is_refused(self):
        unsupported = C.LifecycleError('PLATFORM_UNSUPPORTED', 'host services run on Windows only until the Linux '
                                                               'and macOS adapters exist')
        with mock.patch.object(G, '_ADAPTER', None), mock.patch.object(C, 'select_adapter', side_effect=unsupported):
            code, out, err = self.run_main(['status'])
        self.assertEqual((code, out), (2, ''))
        self.assertIn('PLATFORM_UNSUPPORTED', err)
        self.assertIn('Windows only', err)


if __name__ == '__main__':
    unittest.main()
