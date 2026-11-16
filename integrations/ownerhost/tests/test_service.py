"""The Integration process's lifecycle, with a fake platform adapter (plan leaf U-01.3; decision 0011's verbs).

The server's environment is a fixed allowlist, so no credential, proxy or harness setting of the starting
environment reaches it; its configuration holds no secret-shaped key; ``up`` refuses a running environment and a
held port before it starts anything; ``down`` of nothing stops nothing; readiness is read from the processes and
the kernel's TCP table only, and fails when the server listens anywhere but 127.0.0.1:13310 or anything else holds
the port. The real start and stop are test_listener.py's.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

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
