"""Tests of the host-service lifecycle contract (plan leaf F-06.2): the verbs, the records, the refusal
codes and their remedies, adapter selection, the write-ahead transitions and their orchestration over a
fake service, and the I7 exposure guard. Offline and standard library only; the transition records are
written in one temporary directory per class."""
from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


C = _load('aieh_platform_contract', HERE.parent / 'platform_contract.py')
NEW_CODES = ('PLATFORM_UNSUPPORTED', 'PLATFORM_MISMATCH', 'SUPERVISION_UNAVAILABLE', 'NO_CREDENTIAL_PROVIDER',
             'CREDENTIAL_PROVIDER_LOCKED', 'VERSION_MISMATCH', 'DOWNGRADE_REFUSED', 'TRANSITION_PENDING',
             'UNINSTALL_RUNNING')


class TempDir(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='aieh-platform-'))
        cls.count = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def fresh(self) -> Path:
        type(self).count += 1
        path = self.base / str(self.count)
        path.mkdir()
        return path


class TestVerbsAndCodes(unittest.TestCase):
    def test_the_verbs_of_the_plan(self):
        self.assertEqual(C.VERBS, ('install', 'up', 'down', 'restart', 'status', 'inspect', 'verify', 'provision',
                                   'rotate', 'retire', 'upgrade', 'recover', 'uninstall'))
        self.assertEqual(C.SERVICE_VERBS + C.CREDENTIAL_VERBS + C.TRANSITION_VERBS, C.VERBS)
        self.assertEqual(C.CREDENTIAL_VERBS, ('provision', 'rotate', 'retire'))

    def test_the_record_formats(self):
        self.assertEqual((C.PLATFORM_FORMAT, C.ASSET_FORMAT, C.SERVICE_RUN_FORMAT, C.READINESS_FORMAT,
                          C.TRANSITION_FORMAT), ('aieh-platform/1', 'aieh-asset/1', 'aieh-service-run/1',
                                                 'aieh-readiness/1', 'aieh-service-transition/1'))
        self.assertEqual(C.RUN_FORMATS, ('aieh-service-run/1', 'aieh-gitea-run/1'))

    def test_every_new_code_has_a_remedy_in_its_message(self):
        for code in NEW_CODES:
            with self.subTest(code=code):
                self.assertTrue(C.REMEDIES[code].strip())
                error = C.LifecycleError(code, 'detail')
                self.assertEqual((error.code, error.detail, error.refusal, error.remedy),
                                 (code, 'detail', True, C.REMEDIES[code]))
                self.assertEqual(str(error), f'{code}: detail (remedy: {C.REMEDIES[code]})')

    def test_an_existing_code_keeps_its_message(self):
        error = C.LifecycleError('NOT_INSTALLED', 'x; run install', refusal=False)
        self.assertEqual((str(error), error.remedy, error.refusal), ('NOT_INSTALLED: x; run install', None, False))


class TestPlatform(unittest.TestCase):
    def test_asset_keys(self):
        for system, machine, key in (('Windows', 'AMD64', 'windows-amd64'), ('Windows', 'ARM64', 'windows-arm64'),
                                     ('Linux', 'x86_64', 'linux-amd64'), ('Linux', 'aarch64', 'linux-arm64'),
                                     ('Darwin', 'arm64', 'darwin-arm64')):
            self.assertEqual(C.asset_key(system, machine), key)
        for system, machine in (('SunOS', 'amd64'), ('Linux', 'riscv64')):
            with self.assertRaises(C.LifecycleError) as caught:
                C.asset_key(system, machine)
            self.assertEqual(caught.exception.code, 'PLATFORM_UNSUPPORTED')

    def test_only_windows_has_an_adapter_so_far(self):
        for system in ('Linux', 'Darwin', 'FreeBSD'):
            with self.assertRaises(C.LifecycleError) as caught:
                C.select_adapter(system, 'x86_64')
            self.assertEqual(caught.exception.code, 'PLATFORM_UNSUPPORTED')
            self.assertIn('Windows only', str(caught.exception))
        adapter = C.select_adapter('Windows', 'AMD64')  # imports on any platform: no Windows call at import
        self.assertIsInstance(adapter, C.PlatformAdapter)
        self.assertEqual(adapter.asset_key, 'windows-amd64')

    def test_the_platform_record(self):
        record = C.platform_record(C.select_adapter('Windows', 'AMD64'))
        self.assertEqual(set(record), {'format', 'system', 'machine', 'asset_key', 'supervision', 'credentials'})
        self.assertEqual((record['format'], record['system'], record['machine'], record['asset_key']),
                         ('aieh-platform/1', 'Windows', 'AMD64', 'windows-amd64'))
        self.assertEqual(record['supervision']['mechanism'], 'job-object')
        self.assertEqual(record['credentials']['provider'], 'windows-credential-manager')
        json.dumps(record)

    def test_asset_key_check(self):
        adapter = C.select_adapter('Windows', 'AMD64')
        C.check_asset_key(None, adapter)
        C.check_asset_key('windows-amd64', adapter)
        with self.assertRaises(C.LifecycleError) as caught:
            C.check_asset_key('linux-amd64', adapter)
        self.assertEqual(caught.exception.code, 'PLATFORM_MISMATCH')

    def test_the_base_adapter_has_no_credential_provider(self):
        with self.assertRaises(C.LifecycleError) as caught:
            C.PlatformAdapter().credential_provider()
        self.assertEqual(caught.exception.code, 'NO_CREDENTIAL_PROVIDER')

    def test_the_contract_names_no_platform_mechanism(self):
        """Decision 0011 point 1: no PowerShell, Windows API, Job Object, Credential Manager, /proc or
        launchctl in the contract's code (its docstrings may say what it leaves to the adapters)."""
        tree = ast.parse((HERE.parent / 'platform_contract.py').read_text(encoding='utf-8'))
        imports = {alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                   for alias in node.names}
        imports |= {node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse(imports & {'ctypes', 'msvcrt', 'winreg', '_winapi', 'pwd', 'grp', 'fcntl', 'termios'})
        docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body
                      and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
        # The neutrality check's own list of mechanism words is the one place that names them.
        docstrings |= {id(c) for node in ast.walk(tree) if isinstance(node, ast.Assign)
                       and [getattr(t, 'id', None) for t in node.targets] == ['PLATFORM_WORDS']
                       for c in ast.walk(node.value)}
        words =('kernel32', 'advapi32', 'iphlpapi', 'createjobobject', 'credwrite', 'credread', '/proc',
                 'launchctl', 'systemd-run', 'powershell', 'lsof')
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                self.assertFalse([w for w in words if w in node.value.lower()], node.value)


class TestRunAndReadiness(TempDir):
    def test_both_run_formats_are_read(self):
        tmp = self.fresh()
        for fmt in ('aieh-service-run/1', 'aieh-gitea-run/1'):
            (tmp / 'run.json').write_text(json.dumps({'format': fmt, 'state': 'running'}), encoding='utf-8')
            self.assertEqual(C.read_run_record(tmp / 'run.json')['format'], fmt)
        (tmp / 'run.json').write_text(json.dumps({'format': 'other/1'}), encoding='utf-8')
        self.assertIsNone(C.read_run_record(tmp / 'run.json'))
        self.assertIsNone(C.read_run_record(tmp / 'absent.json'))
        (tmp / 'run.json').write_text('{', encoding='utf-8')
        with self.assertRaises(C.LifecycleError) as caught:
            C.read_run_record(tmp / 'run.json')
        self.assertEqual(caught.exception.code, 'RUN_RECORD_INVALID')

    def test_a_readiness_record_carries_its_platform(self):
        adapter = C.select_adapter('Windows', 'AMD64')
        record = C.readiness_record('gitea', adapter, {'listeners_loopback_only': True, 'service_not_elevated': True},
                                    checked_at='2026-11-10T00:00:00Z')
        self.assertEqual(record, {'format': 'aieh-readiness/1', 'service': 'gitea',
                                  'platform': C.platform_record(adapter), 'checked_at': '2026-11-10T00:00:00Z',
                                  'checks': {'listeners_loopback_only': True, 'service_not_elevated': True},
                                  'passed': True})
        self.assertFalse(C.readiness_record('gitea', adapter, {'a': True, 'b': False})['passed'])

    def test_readiness_check_names_are_platform_neutral(self):
        adapter = C.select_adapter('Windows', 'AMD64')
        for name in ('token_not_elevated', 'gitea_in_kill_on_close_job', 'windows_listener', 'CamelCase', 'pid_ok'):
            with self.subTest(name=name), self.assertRaises(C.LifecycleError) as caught:
                C.readiness_record('gitea', adapter, {name: True})
            self.assertEqual(caught.exception.code, 'CHECK_NAME_NOT_NEUTRAL')
        with self.assertRaises(C.LifecycleError) as caught:
            C.readiness_record('gitea', adapter, {'ok': 1})
        self.assertEqual(caught.exception.code, 'CHECK_NOT_BOOLEAN')


class TestVersions(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(C.parse_version('28.3.0'), (28, 3, 0))
        self.assertLess(C.parse_version('28.3.0'), C.parse_version('28.10.0'))
        for bad in ('28', 'v28.3.0', '../28.3.0', '28.3.0-rc1', None):
            with self.assertRaises(C.LifecycleError) as caught:
                C.parse_version(bad)
            self.assertEqual(caught.exception.code, 'VERSION_MISMATCH')

    def test_plan_upgrade(self):
        pinned = ['28.3.0', '28.4.0', '27.0.0']
        self.assertEqual(C.plan_upgrade(desired='28.3.0', running='28.3.0', target='28.4.0', pinned=pinned), 'upgrade')
        self.assertEqual(C.plan_upgrade(desired='28.3.0', running=None, target='28.3.0', pinned=pinned), 'noop')
        for kwargs, code in ((dict(target='29.0.0'), 'VERSION_MISMATCH'),
                             (dict(target='28.4.0', running='27.0.0'), 'VERSION_MISMATCH'),
                             (dict(target='28.4.0', running='unknown'), 'VERSION_MISMATCH'),
                             (dict(target='27.0.0'), 'DOWNGRADE_REFUSED')):
            with self.subTest(**kwargs), self.assertRaises(C.LifecycleError) as caught:
                C.plan_upgrade(**{'desired': '28.3.0', 'running': '28.3.0', 'pinned': pinned, **kwargs})
            self.assertEqual(caught.exception.code, code)


class FakeService(C.ServiceOperations):
    """A service in memory: running or not, at a version; every operation is logged; fail names an
    operation that raises, or 'ready' to make readiness fail for one version."""

    def __init__(self, running=True, version='28.3.0', fail=None, not_ready=None):
        self.running, self.version, self.desired = running, version, version
        self.fail, self.not_ready, self.log, self.db = fail, not_ready, [], 'v1-data'
        self.backups, self.ephemeral = {}, True

    def _op(self, name):
        self.log.append(name)
        if self.fail == name:
            self.fail = None  # once: the rollback's own call of it succeeds
            raise C.LifecycleError('BOOM', name, refusal=False)

    def observe(self):
        return {'running': self.running, 'ready': self.running,
                'running_version': self.version if self.running else None, 'desired_version': self.desired}

    def stop(self):
        self._op('stop')
        self.running = False
        return {'stopped': True}

    def start(self, version=None):
        self._op('start')
        self.running, self.version = True, version or self.desired
        return {'running': True, 'version': self.version}

    def ready(self, version=None):
        return self.running and self.version != self.not_ready and (version is None or version == self.version)

    def stage(self, version):
        self._op('stage')
        return {'asset': version}

    def backup(self, transition_id):
        self._op('backup')
        self.backups[transition_id] = self.db
        return {'backup': transition_id}

    def restore(self, transition_id):
        self._op('restore')
        self.db = self.backups[transition_id]
        return {'restored': transition_id}

    def set_desired(self, version):
        self._op('set_desired')
        self.desired = version
        if version != '28.3.0':
            self.db = 'migrated'
        return {'desired': version}

    def pinned_versions(self):
        return ['28.3.0', '28.4.0', '27.0.0']

    def remove_ephemeral(self):
        self._op('remove_ephemeral')
        self.ephemeral = False
        return {'removed': ['tmp']}

    def retained(self):
        return {'persistent': ['home'], 'assets': ['28.3.0']}


class TestTransitions(TempDir):
    def log(self):
        return C.TransitionLog(self.fresh() / 'transitions', 'gitea', 'windows-amd64')

    def test_the_record_is_written_before_any_step_and_one_is_pending_at_most(self):
        log = self.log()
        record = log.begin('restart', {'desired': '28.3.0', 'running': '28.3.0'}, was_running=True)
        on_disk = json.loads((log.directory / f'{record["id"]}.json').read_text(encoding='utf-8'))
        self.assertEqual((on_disk['format'], on_disk['state'], on_disk['verb'], on_disk['steps']),
                         ('aieh-service-transition/1', 'pending', 'restart', []))
        self.assertEqual(on_disk['platform'], {'asset_key': 'windows-amd64'})
        with self.assertRaises(C.LifecycleError) as caught:
            log.begin('upgrade', {})
        self.assertEqual(caught.exception.code, 'TRANSITION_PENDING')
        log.step(record, 'stopped', result={'ok': True})
        log.finish(record, 'completed')
        self.assertIsNone(log.pending())
        self.assertEqual(log.latest()['state'], 'completed')
        self.assertEqual(C.done_steps(log.latest()), ['stopped'])
        self.assertEqual(sorted(p.name.endswith('.json') for p in log.directory.iterdir()), [True])
        with self.assertRaises(C.LifecycleError):
            log.finish(record, 'pending')

    def test_restart(self):
        log, svc = self.log(), FakeService()
        record = C.restart(log, svc)
        self.assertEqual((record['state'], C.done_steps(record), svc.log), ('completed', ['stopped', 'started'],
                                                                             ['stop', 'start']))
        stopped = FakeService(running=False)
        self.assertEqual(C.done_steps(C.restart(self.log(), stopped)), ['started'])

    def test_a_restart_that_is_not_ready_fails(self):
        log, svc = self.log(), FakeService(not_ready='28.3.0')
        with self.assertRaises(C.LifecycleError) as caught:
            C.restart(log, svc)
        self.assertEqual(caught.exception.code, 'RESTART_NOT_READY')
        self.assertEqual(log.latest()['state'], 'failed')

    def test_upgrade_completes_in_order(self):
        log, svc = self.log(), FakeService()
        record = C.upgrade(log, svc, '28.4.0')
        self.assertEqual(record['state'], 'completed')
        self.assertEqual(C.done_steps(record), ['staged', 'stopped', 'backed-up', 'desired-set', 'started', 'verified'])
        self.assertEqual(record['versions'], {'desired': '28.4.0', 'staged': '28.4.0', 'running': '28.4.0',
                                              'target': '28.4.0'})
        self.assertEqual((svc.version, svc.desired), ('28.4.0', '28.4.0'))

    def test_upgrade_noop_and_refusals_write_no_record(self):
        log, svc = self.log(), FakeService()
        self.assertEqual(C.upgrade(log, svc, '28.3.0')['upgrade'], 'noop')
        for target, code in (('27.0.0', 'DOWNGRADE_REFUSED'), ('29.0.0', 'VERSION_MISMATCH')):
            with self.assertRaises(C.LifecycleError) as caught:
                C.upgrade(log, svc, target)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(log.records(), [])
        self.assertEqual(svc.log, [])

    def test_a_failure_before_verification_rolls_back_automatically(self):
        for fail, not_ready in (('start', None), (None, '28.4.0')):
            with self.subTest(fail=fail, not_ready=not_ready):
                log, svc = self.log(), FakeService(fail=fail, not_ready=not_ready)
                record = C.upgrade(log, svc, '28.4.0')
                self.assertEqual(record['state'], 'rolled-back')
                self.assertIn('restored', C.done_steps(record))
                self.assertEqual((svc.desired, svc.version, svc.db, svc.running), ('28.3.0', '28.3.0', 'v1-data', True))
                self.assertEqual(record['versions']['desired'], '28.3.0')

    def test_uninstall(self):
        log, svc = self.log(), FakeService(running=True)
        with self.assertRaises(C.LifecycleError) as caught:
            C.uninstall(log, svc)
        self.assertEqual(caught.exception.code, 'UNINSTALL_RUNNING')
        self.assertEqual(log.records(), [])
        svc.running = False
        record = C.uninstall(log, svc)
        self.assertEqual((record['state'], record['retained'], svc.ephemeral), ('completed', svc.retained(), False))

    def test_recover_with_nothing_pending_only_observes(self):
        svc = FakeService()
        self.assertEqual(C.recover(self.log(), svc), {'pending': None, 'observed': svc.observe()})
        self.assertEqual(svc.log, [])

    def test_recover_resumes_an_interrupted_restart(self):
        log, svc = self.log(), FakeService()
        record = log.begin('restart', {'desired': '28.3.0', 'running': '28.3.0'}, was_running=True)
        svc.stop()
        log.step(record, 'stopped')
        with self.assertRaises(C.LifecycleError) as caught:  # nothing else while it is pending
            C.upgrade(log, svc, '28.4.0')
        self.assertEqual(caught.exception.code, 'TRANSITION_PENDING')
        result = C.recover(log, svc)
        self.assertEqual((result['verb'], result['transition']['state'], svc.running), ('restart', 'completed', True))
        self.assertIn('recover-observed', C.done_steps(result['transition']))

    def test_recover_rolls_back_an_upgrade_interrupted_before_verification(self):
        log, svc = self.log(), FakeService()
        record = log.begin('upgrade', {'desired': '28.3.0', 'running': '28.3.0', 'target': '28.4.0'},
                           was_running=True, previous='28.3.0')
        for name, call in (('staged', lambda: svc.stage('28.4.0')), ('stopped', svc.stop),
                           ('backed-up', lambda: svc.backup(record['id'])),
                           ('desired-set', lambda: svc.set_desired('28.4.0'))):
            log.step(record, name, result=call())
        result = C.recover(log, svc)  # interrupted before the start: rolled back from the record
        self.assertEqual(result['transition']['state'], 'rolled-back')
        self.assertEqual((svc.desired, svc.db, svc.running, svc.version), ('28.3.0', 'v1-data', True, '28.3.0'))

    def test_recover_completes_an_upgrade_whose_target_runs_and_is_ready(self):
        log, svc = self.log(), FakeService()
        record = log.begin('upgrade', {'desired': '28.3.0', 'running': '28.3.0', 'target': '28.4.0'},
                           was_running=True, previous='28.3.0')
        for name, call in (('staged', lambda: svc.stage('28.4.0')), ('stopped', svc.stop),
                           ('backed-up', lambda: svc.backup(record['id'])),
                           ('desired-set', lambda: svc.set_desired('28.4.0')), ('started', lambda: svc.start('28.4.0'))):
            log.step(record, name, result=call())
        result = C.recover(log, svc)
        self.assertEqual((result['transition']['state'], svc.version), ('completed', '28.4.0'))

    def test_recover_refuses_to_finish_an_uninstall_while_running(self):
        log, svc = self.log(), FakeService(running=False)
        log.begin('uninstall', {'desired': '28.3.0'})
        svc.start()
        with self.assertRaises(C.LifecycleError) as caught:
            C.recover(log, svc)
        self.assertEqual(caught.exception.code, 'UNINSTALL_RUNNING')
        svc.stop()
        self.assertEqual(C.recover(log, svc)['transition']['state'], 'completed')


class FakeProvider(C.CredentialProvider):
    def __init__(self):
        self.entries = {}

    def get(self, name):
        return self.entries.get(name)

    def set(self, name, user, secret, comment=''):
        self.entries[name] = (user, secret)

    def delete(self, name):
        return self.entries.pop(name, None) is not None


class TestExposureGuard(TempDir):
    SECRET = 'S3cret-fixture-value-for-the-guard'

    def test_a_held_secret_is_found_in_either_encoding_and_never_reported(self):
        guard = C.ExposureGuard()
        guard.hold(self.SECRET)
        self.assertTrue(guard.scan_text('clean', '{"ok": true}'))
        self.assertFalse(guard.scan_text('utf8', f'x {self.SECRET} y'))
        self.assertFalse(guard.scan_text('utf16', self.SECRET.encode('utf-16-le')))
        report = guard.report()
        self.assertEqual((report['found_in'], report['scanned'], report['secrets_held'], report['clean']),
                         (['utf8', 'utf16'], 3, 1, False))
        self.assertNotIn(self.SECRET, json.dumps(report))
        guard.clear()
        self.assertEqual(guard.held, 0)

    def test_token_shaped_strings(self):
        guard = C.ExposureGuard()
        self.assertFalse(guard.scan_text('token', 'a' * 40))
        self.assertTrue(guard.scan_text('sha256', 'b' * 64))
        self.assertTrue(guard.scan_text('shape off', 'c' * 40, token_shape=False))

    def test_files(self):
        tmp = self.fresh()
        (tmp / 'leak.txt').write_text(f'.. {self.SECRET} ..', encoding='utf-8')
        (tmp / 'commit.txt').write_text('d' * 40, encoding='utf-8')
        guard = C.ExposureGuard()
        guard.hold(self.SECRET)
        guard.scan_files([tmp / 'leak.txt', tmp / 'commit.txt', tmp / 'absent.txt'])
        self.assertEqual(guard.report()['found_in'], [str(tmp / 'leak.txt')])

    def test_the_watched_provider_holds_what_the_act_reads_and_writes(self):
        guard, inner = C.ExposureGuard(), FakeProvider()
        provider = C.WatchedProvider(inner, guard)
        provider.set('entry', 'user', self.SECRET)
        inner.entries['other'] = ('user', 'read-secret-value')
        self.assertEqual(provider.get('other'), ('user', 'read-secret-value'))
        self.assertIsNone(provider.get('absent'))
        self.assertTrue(provider.exists('entry'))
        self.assertEqual(guard.held, 2)
        self.assertFalse(guard.scan_text('report', 'read-secret-value'))
        self.assertTrue(provider.delete('entry'))
        self.assertEqual(C.fingerprint('x'), 'sha256:2d711642b726b044')


if __name__ == '__main__':
    unittest.main()
