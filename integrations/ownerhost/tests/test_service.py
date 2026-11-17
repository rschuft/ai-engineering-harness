"""The Integration process's lifecycle, with a fake platform adapter (plan leaf U-01.3; decision 0011's verbs).

The server's environment is a fixed allowlist, so no credential, proxy or harness setting of the starting
environment reaches it; its configuration holds no secret-shaped key; ``up`` refuses a running environment and a
held port before it starts anything; ``down`` of nothing stops nothing; readiness is read from the processes and
the kernel's TCP table only, and fails when the server listens anywhere but 127.0.0.1:13310 or anything else holds
the port. The real start and stop are test_listener.py's.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import ownerhost_support as T

CATEGORY = 'unit'
SV = T._load('aieh_ownerhost_service', T.PACKAGE / 'service.py')
paths = SV.paths


class FakeProc:
    def __init__(self, pid, *, in_job=True):
        self.pid, self.in_job, self.terminated = pid, in_job, False

    def in_any_job(self):
        return self.in_job

    def image(self):
        return 'python.exe'

    def alive(self):
        return not self.terminated

    def wait(self, seconds):
        return self.terminated

    def terminate(self):
        self.terminated = True


class FakeAdapter:
    asset_key = 'windows-amd64'

    def __init__(self, *, procs=None, rows=None, port_in_use=False):
        self.procs, self.rows, self.in_use, self.launched = procs or {}, rows or [], port_in_use, []

    def process_maybe(self, pid, created):
        return self.procs.get((pid, created))

    def listeners(self, pid=None):
        return [r for r in self.rows if pid is None or r['pid'] == pid]

    def port_in_use(self, port, address):
        return self.in_use

    def user_identity(self, pid):
        return {}

    def launch_supervisor(self, argv, log, cwd, env=None):
        self.launched.append(argv)
        raise AssertionError('nothing may be started')


def row(address, port, pid, proto='tcp'):
    return {'proto': proto, 'family': 'ipv4', 'address': address, 'port': port, 'pid': pid}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix='aieh-ownerhost-service-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.lay = SV.Layout(tmp / 'state', tmp / 'logs')
        self.lay.state.mkdir()
        self.lay.logs.mkdir()

    def record(self, **extra):
        data = {'format': SV.RUN_FORMAT, 'service': 'owner-host', 'state': 'running',
                'supervisor': {'pid': 10, 'created': 1}, 'server': {'pid': 20, 'created': 2, 'in_supervisor_job': True}}
        data.update(extra)
        self.lay.run_record.write_text(json.dumps(data), encoding='utf-8')

    def running(self, rows, **kw):
        self.record()
        return FakeAdapter(procs={(10, 1): FakeProc(10), (20, 2): FakeProc(20, **kw)}, rows=rows)


class Environment(unittest.TestCase):
    def test_the_server_gets_only_the_allowlisted_variables(self):
        planted = dict(T.samples(), **{'OWNER_SESSION': T.E.mint(), 'HTTPS_PROXY': 'http://proxy.invalid:8080',
                                       'AIEH_DATA_ROOT': 'D:/elsewhere', 'PATH': 'C:/Windows'})
        environ = {'SystemRoot': 'C:\\Windows', 'TEMP': 'C:\\Temp', 'TMP': 'C:\\Temp',
                   'NUMBER_OF_PROCESSORS': '8', **{k.upper().replace('-', '_'): v for k, v in planted.items()}}
        child = SV.child_environment(environ)
        self.assertEqual(child, {'SystemRoot': 'C:\\Windows', 'TEMP': 'C:\\Temp', 'TMP': 'C:\\Temp',
                                 'NUMBER_OF_PROCESSORS': '8'})
        self.assertEqual(T.exposures(json.dumps(child), planted.values()), [])
        self.assertTrue(all(not paths.SECRET_SHAPED.search(name) for name in SV.ENVIRONMENT_NAMES))

    def test_the_configuration_holds_no_secret_shaped_key_and_names_the_one_port(self):
        lay = SV.Layout(Path('C:/managed/persistent/state/owner-host'), Path('C:/managed/persistent/logs/owner-host'))
        config = SV.configuration(lay)
        self.assertEqual((config['address'], config['port']), ('127.0.0.1', 13310))
        self.assertEqual([k for k in config if paths.SECRET_SHAPED.search(k)], [])

    def test_the_server_argv_names_the_app_and_the_two_directories_only(self):
        lay = SV.Layout(Path('C:/s'), Path('C:/l'))
        argv = SV.server_argv(lay, 'python.exe')
        self.assertEqual(argv[1:], ['-I', '-B', str(SV.APP), 'serve', '--state-dir', str(Path('C:/s')),
                                    '--logs-dir', str(Path('C:/l'))])

    def test_the_port_is_declared_once(self):
        self.assertIs(SV.app, T.A)
        self.assertEqual((SV.PORT, SV.LOOPBACK), (T.A.PORT, T.A.LOOPBACK))
        self.assertEqual(T.A.PORT, 13310)



class CaptureConfiguration(Base):
    """P-01.3: service.py, never the server, reads components.owner_host; it reaches the supervisor and the server as
    JSON with the managed integration store's path, and appears in the configuration snapshot."""
    RAW = {'project_repository': 'C:/projects/demo', 'project_repository_id': 'aieh-d1-demo',
           'backlog_command': 'backlog', 'git_identities': {'owner': 'Test Owner <12345+test-owner@users.noreply.github.com>'}}

    def captured_layout(self):
        return SV.Layout(self.lay.state, self.lay.logs, SV.owner_host_json({'owner_host': self.RAW}),
                         Path('C:/managed/state/integration/integration.sqlite'))

    def test_components_owner_host_reaches_the_server_as_json_with_the_integration_store(self):
        lay = self.captured_layout()
        argv = SV.server_argv(lay, 'python.exe')
        self.assertEqual(argv[:9], ['python.exe', '-I', '-B', str(SV.APP), 'serve', '--state-dir', str(lay.state),
                                    '--logs-dir', str(lay.logs)])
        self.assertEqual(argv[9:], ['--owner-host-config', lay.owner_host, '--integration-store',
                                    str(lay.integration_store)])
        self.assertEqual(T.A.owner_host_config(argv[10]), self.RAW)
        config = SV.configuration(lay)
        self.assertEqual((config['owner_host'], config['integration_store']), (self.RAW, str(lay.integration_store)))
        self.assertEqual([k for k in config if paths.SECRET_SHAPED.search(k)], [])

    def test_absent_owner_host_passes_nothing_and_the_capture_refuses_unconfigured(self):
        for components in ({}, {'owner_host': None}, None):
            with self.subTest(components=components):
                self.assertIsNone(SV.owner_host_json(components))
        self.assertEqual(SV.capture_argv(SV.Layout(self.lay.state, self.lay.logs)), [])
        with self.assertRaises(T.A.capture.CaptureRefused) as caught:
            T.A.capture.project_config(T.A.owner_host_config(None))
        self.assertEqual(caught.exception.code, 'CAPTURE_PROJECT_UNCONFIGURED')

    def test_a_value_json_cannot_hold_becomes_a_value_the_capture_refuses(self):
        import datetime
        text = SV.owner_host_json({'owner_host': {**self.RAW, 'project_repository': datetime.date(2026, 11, 16)}})
        with self.assertRaises(T.A.capture.CaptureRefused) as caught:
            T.A.capture.project_config(T.A.owner_host_config(text))
        self.assertEqual(caught.exception.code, 'CAPTURE_CONFIG_INVALID')
        with self.assertRaises(T.A.capture.CaptureRefused) as caught:
            T.A.capture.project_config(T.A.owner_host_config('{not json'))
        self.assertEqual(caught.exception.code, 'CAPTURE_CONFIG_INVALID')

    def test_up_and_the_supervisor_pass_the_capture_arguments_on(self):
        lay = self.captured_layout()
        adapter = FakeAdapter()
        with self.assertRaises(AssertionError):     # the fake starts nothing; it records the argv
            SV.up(lay, adapter)
        (argv,) = adapter.launched
        self.assertEqual(argv[-4:], SV.capture_argv(lay))
        seen = []
        with mock.patch.object(SV, 'supervise', lambda layout, adapter, launch: seen.append(layout) or 0),                 mock.patch.object(SV.contract, 'select_adapter', lambda: adapter):
            self.assertEqual(SV.main(argv[4:]), 0)
        self.assertEqual(seen, [lay])


class Readiness(Base):
    def test_ready_when_the_server_listens_on_the_declared_port_only(self):
        adapter = self.running([row('127.0.0.1', 13310, 20)])
        checks = SV.readiness_checks(adapter, SV.contract.read_run_record(self.lay.run_record))
        self.assertTrue(all(checks.values()), checks)

    def test_not_ready_for_each_way_the_listener_can_be_wrong(self):
        cases = {
            'listener_on_declared_port': [row('127.0.0.1', 13311, 20)],
            'loopback_only': [row('0.0.0.0', 13310, 20)],
            'port_held_by_server': [row('127.0.0.1', 13310, 20), row('0.0.0.0', 13310, 99)],
        }
        for check, rows in cases.items():
            with self.subTest(check=check):
                adapter = self.running(rows)
                checks = SV.readiness_checks(adapter, SV.contract.read_run_record(self.lay.run_record))
                self.assertFalse(checks[check], checks)
        adapter = self.running([row('127.0.0.1', 13310, 20), row('127.0.0.1', 5353, 20, 'udp')])
        self.assertFalse(SV.readiness_checks(adapter, SV.contract.read_run_record(self.lay.run_record))['loopback_only'])
        adapter = self.running([row('127.0.0.1', 13310, 20)], in_job=False)
        self.assertFalse(SV.readiness_checks(adapter, SV.contract.read_run_record(self.lay.run_record))
                         ['server_supervised'])

    def test_nothing_runs_without_a_record(self):
        checks = SV.readiness_checks(FakeAdapter(), None)
        self.assertEqual(set(checks.values()), {False})

    def test_the_check_names_are_platform_neutral(self):
        record = SV.contract.readiness_record('owner-host', _Platform(), SV.readiness_checks(FakeAdapter(), None))
        self.assertFalse(record['passed'])


class _Platform:
    system, machine, asset_key = 'Windows', 'AMD64', 'windows-amd64'
    supervision, credentials = {'mechanism': 'job-object'}, {}


class Instance(Base):
    """One instance: the supervisor's lock on <state>/owner-host/instance.lock."""

    def test_a_second_holder_is_refused_until_the_first_releases(self):
        first, second = SV.InstanceLock(self.lay.instance_lock), SV.InstanceLock(self.lay.instance_lock)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        self.assertTrue(second.held_elsewhere())
        first.release()
        self.assertFalse(second.held_elsewhere())
        self.assertTrue(second.acquire())
        second.release()

    def test_a_supervisor_that_finds_the_lock_held_touches_nothing(self):
        holder = SV.InstanceLock(self.lay.instance_lock)
        self.assertTrue(holder.acquire())
        self.addCleanup(holder.release)
        for name, text in (('run.json', '{"other": true}'), ('server.json', '{"other": true}'), ('stop-request', 'x')):
            (self.lay.state / name).write_text(text, encoding='utf-8')
        def files():     # the lock file itself is locked for reading while held
            return {p.name: p.read_bytes() for p in self.lay.state.iterdir() if p.name != 'instance.lock'}
        before = files()

        class Untouchable:
            def __getattr__(self, name):
                raise AssertionError(f'the adapter was used: {name}')
        self.assertEqual(SV.supervise(self.lay, Untouchable(), 'launch'), SV.LOCK_HELD_EXIT)
        self.assertEqual(files(), before)
        self.assertEqual(sorted(before), ['run.json', 'server.json', 'stop-request'])
        self.assertEqual(list(self.lay.logs.iterdir()), [])

    def test_up_refuses_while_another_holds_the_lock_and_starts_nothing(self):
        holder = SV.InstanceLock(self.lay.instance_lock)
        self.assertTrue(holder.acquire())
        self.addCleanup(holder.release)
        adapter = FakeAdapter()
        with self.assertRaises(SV.LifecycleError) as caught:
            SV.up(self.lay, adapter)
        self.assertEqual((caught.exception.code, caught.exception.refusal), ('ALREADY_RUNNING', True))
        self.assertEqual(adapter.launched, [])


@unittest.skipUnless(sys.platform == 'win32', 'the refusal is Windows\' (a reader without FILE_SHARE_DELETE)')
class SharedRecord(Base):
    """The flake of dispatch 11 (test_listener's START_FAILED under the parallel run): the supervisor's os.replace of
    run.json was refused (WinError 5) while ``up``'s poll had the file open, and the supervisor exited 1. A record's
    replacement now waits for the reader to let go, and a reader that meets a replacement reads again, each bounded
    by app.SHARED_FILE_CEILING_S. Shown with a handle this process holds (Windows refuses it like another's)."""

    def test_a_record_replaced_while_another_handle_reads_it_is_written_once_the_reader_lets_go(self):
        path = self.lay.run_record
        path.write_text('{"old": true}\n', encoding='utf-8')
        reader = open(path, 'rb')
        self.addCleanup(reader.close)
        refused, attempts, errors = threading.Event(), [], []
        real = os.replace

        def replace(src, dst):
            attempts.append(dst)
            try:
                return real(src, dst)
            except PermissionError:
                refused.set()                 # the reader still holds it: the writer was refused and retries
                raise

        def write():
            try:
                SV._write_json(path, {'new': True})
            except BaseException as exc:      # noqa: BLE001 - reported to the main thread
                errors.append(exc)
        with mock.patch.object(SV.app.os, 'replace', replace):
            writer = threading.Thread(target=write, daemon=True)
            writer.start()
            self.assertTrue(refused.wait(SV.app.SHARED_FILE_CEILING_S), 'the reader\'s handle refuses the replace')
            reader.close()                    # the reader lets go
            writer.join(SV.app.SHARED_FILE_CEILING_S * 2)
        self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        self.assertGreater(len(attempts), 1)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'new': True})
        self.assertFalse(path.with_name(path.name + '.partial').exists())

    def test_a_reader_that_never_lets_go_fails_the_write_at_the_ceiling(self):
        path = self.lay.run_record
        path.write_text('{"old": true}\n', encoding='utf-8')
        partial = path.with_name(path.name + '.partial')
        partial.write_text('{"new": true}\n', encoding='utf-8')
        with open(path, 'rb'):
            with self.assertRaises(PermissionError) as caught:
                SV.app.replace_shared(partial, path, ceiling_s=0)
        self.assertIn(caught.exception.winerror, SV.app.SHARING_WINERRORS)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'old': True})

    def test_any_other_refusal_of_the_replace_is_raised_at_once(self):
        calls = []

        def replace(src, dst):
            calls.append(dst)
            raise PermissionError(13, 'not a sharing refusal')        # no winerror: a real permission error
        with mock.patch.object(SV.app.os, 'replace', replace), self.assertRaises(PermissionError):
            SV._write_json(self.lay.run_record, {'new': True})
        self.assertEqual(len(calls), 1)

    def test_a_read_that_meets_a_replacement_is_made_again(self):
        record = {'format': SV.RUN_FORMAT, 'state': 'running'}
        answers = []

        def read(path):
            answers.append(path)
            if len(answers) == 1:
                try:
                    raise PermissionError(13, 'the replacement runs')
                except PermissionError:
                    raise SV.LifecycleError('RUN_RECORD_INVALID', f'{path} is unreadable') from None
            return record
        with mock.patch.object(SV.contract, 'read_run_record', read):
            self.assertEqual(SV.read_run_record(self.lay.run_record), record)
        self.assertEqual(len(answers), 2)

    def test_an_unreadable_record_is_still_run_record_invalid(self):
        self.lay.run_record.write_text('{not json', encoding='utf-8')
        started = time.monotonic()
        with self.assertRaises(SV.LifecycleError) as caught:
            SV.read_run_record(self.lay.run_record)
        self.assertEqual(caught.exception.code, 'RUN_RECORD_INVALID')
        self.assertLess(time.monotonic() - started, SV.app.SHARED_FILE_CEILING_S, 'not retried: it is no sharing')


class OtherLaunch(FakeAdapter):
    """launch_supervisor plants a ready run record of ANOTHER launch (a concurrent up's), and its own supervisor then
    exits having lost the instance lock (the review's mutant M32: up accepting any launch's record)."""

    def __init__(self, lay):
        super().__init__(rows=[row('127.0.0.1', 13310, 20)])
        self.lay = lay

    def launch_supervisor(self, argv, log, cwd, env=None):
        self.lay.run_record.write_text(json.dumps({
            'format': SV.RUN_FORMAT, 'service': 'owner-host', 'state': 'running', 'launch_id': 'another-launch',
            'supervisor': {'pid': 10, 'created': 1}, 'server': {'pid': 20, 'created': 2, 'in_supervisor_job': True}}),
            encoding='utf-8')
        self.procs = {(10, 1): FakeProc(10), (20, 2): FakeProc(20)}
        polls = iter([None, None, None, SV.LOCK_HELD_EXIT])

        class Lost:
            pid, returncode = 99, None

            def poll(self):
                self.returncode = next(polls, SV.LOCK_HELD_EXIT)
                return self.returncode
        return Lost()


class Transitions(Base):
    """D2: a restart that cannot finish closes its record as failed, with the cause, and never stays pending; a
    record a killed restart left pending is refused TRANSITION_PENDING, whose remedy names recover, a verb that
    exists here."""

    def log(self):
        return SV.contract.TransitionLog(self.lay.transitions, SV.SERVICE, 'windows-amd64')

    def test_a_restart_refused_at_its_start_is_closed_failed_with_its_cause(self):
        adapter = FakeAdapter(port_in_use=True)
        with self.assertRaises(SV.LifecycleError) as caught:
            SV.restart(self.lay, adapter)
        self.assertEqual(caught.exception.code, 'PORT_IN_USE')
        (record,) = self.log().records()
        self.assertEqual((record['state'], record['cause']['code']), ('failed', 'PORT_IN_USE'))
        self.assertIsNone(self.log().pending())
        with self.assertRaises(SV.LifecycleError) as again:     # the next restart runs: refused for the port only
            SV.restart(self.lay, adapter)
        self.assertEqual(again.exception.code, 'PORT_IN_USE')
        self.assertEqual([r['state'] for r in self.log().records()], ['failed', 'failed'])

    def test_a_pending_record_names_recover_which_exists_and_recover_closes_it(self):
        self.log().begin('restart', {'desired': 'checkout', 'running': None}, was_running=False)   # a killed restart
        with self.assertRaises(SV.LifecycleError) as caught:
            SV.restart(self.lay, FakeAdapter())
        self.assertEqual(caught.exception.code, 'TRANSITION_PENDING')
        self.assertIn('run recover', str(caught.exception))
        self.assertIn("('recover',", (T.PACKAGE / 'service.py').read_text(encoding='utf-8'))
        self.assertIs(SV.main.__globals__['recover'], SV.recover)
        with self.assertRaises(SV.LifecycleError) as recovered:   # recover resumes it; its start is refused here
            SV.recover(self.lay, FakeAdapter(port_in_use=True))
        self.assertEqual(recovered.exception.code, 'PORT_IN_USE')
        self.assertIsNone(self.log().pending())
        self.assertEqual(self.log().records()[0]['state'], 'failed')

    def test_up_never_reports_another_launch_s_server_as_its_own(self):
        adapter = OtherLaunch(self.lay)
        with self.assertRaises(SV.LifecycleError) as caught:
            SV.up(self.lay, adapter)
        self.assertEqual((caught.exception.code, caught.exception.refusal), ('ALREADY_RUNNING', True))


class Verbs(Base):
    def test_up_refuses_a_running_environment_and_starts_nothing(self):
        adapter = self.running([row('127.0.0.1', 13310, 20)])
        with self.assertRaises(SV.LifecycleError) as caught:
            SV.up(self.lay, adapter)
        self.assertEqual((caught.exception.code, caught.exception.refusal), ('ALREADY_RUNNING', True))
        self.assertEqual(adapter.launched, [])

    def test_up_refuses_a_held_port_and_never_another_port(self):
        adapter = FakeAdapter(port_in_use=True)
        with self.assertRaises(SV.LifecycleError) as caught:
            SV.up(self.lay, adapter)
        self.assertEqual(caught.exception.code, 'PORT_IN_USE')
        self.assertEqual(adapter.launched, [])
        self.assertIn('13310', str(caught.exception))

    def test_down_of_nothing_stops_nothing(self):
        self.assertEqual(SV.down(self.lay, FakeAdapter()), {'stopped': False, 'detail': 'not running',
                                                           'port_open': False})
        self.assertFalse(self.lay.stop_request.exists())

    def test_down_asks_the_server_to_stop_then_terminates_the_supervisor_past_the_ceiling(self):
        adapter = self.running([row('127.0.0.1', 13310, 20)])
        supervisor = adapter.procs[(10, 1)]
        original = SV.STOP_CEILING_S
        SV.STOP_CEILING_S = 0.0
        self.addCleanup(setattr, SV, 'STOP_CEILING_S', original)
        report = SV.down(self.lay, adapter)
        self.assertTrue(supervisor.terminated)
        self.assertIn('supervisor terminated', report['method'])
        self.assertFalse(self.lay.stop_request.exists())

    def test_linux_and_macos_are_unsupported(self):
        for system in ('Linux', 'Darwin'):
            with self.subTest(system=system), self.assertRaises(SV.LifecycleError) as caught:
                SV.contract.select_adapter(system, 'x86_64')
            self.assertEqual(caught.exception.code, 'PLATFORM_UNSUPPORTED')

    def test_the_verbs_are_the_contract_s_service_verbs_without_install(self):
        self.assertEqual(set(SV.contract.SERVICE_VERBS) - {'install'}, {'up', 'down', 'restart', 'status', 'inspect',
                                                                       'verify'})
        text = (T.PACKAGE / 'service.py').read_text(encoding='utf-8')
        for verb in ('install', 'upgrade', 'uninstall', 'provision', 'rotate', 'retire'):
            self.assertNotIn(f"('{verb}',", text)


if __name__ == '__main__':
    unittest.main()
