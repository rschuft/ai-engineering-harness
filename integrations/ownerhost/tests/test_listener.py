"""The Integration process, started and stopped for real (plan leaf U-01.3's proof; Proposed decision 0025).

One scenario, observed first and judged by the tests: the service is started through ``service.up`` on a throwaway
managed layout (a temporary directory; never the managed data root), with the starting environment planted with the
throwaway credentials and a value of every other credential shape; the observations are made; ``service.down``
stops it. Then:

- **binds 127.0.0.1 only**: the server's rows of the kernel's TCP and UDP tables are exactly the TCP listener
  127.0.0.1:13310; nothing else holds the port; the readiness record passes; and the host census by port
  (tools/guest.py host-census, HOST_CENSUS_PORTS) finds the listener on 127.0.0.1 only;
- **every request needs the credential**, over HTTP: every route and method, and paths that are no route, answer
  ``SESSION_CREDENTIAL_MISSING`` without it; the preflight is the one exception and carries no data;
- **missing, foreign, expired and revoked** are refused with their codes and change nothing (the store's canonical
  dump is equal before and after each), and every other credential shape of the inventory is foreign;
- **no credential present**: the server's and the supervisor's environment blocks and command lines (read from
  outside, from their process parameters), the records (run.json, server.json: the configuration snapshot) and the
  logs hold no throwaway credential and no credential shape, although the environment that ran ``up`` held them all
  (so the allowlist did the filtering);
- **the live import censuses**: the server's, at start and at stop, is its four modules; the supervisor's, at start,
  running and stop, has nothing under integrations/credentials, gitea, dispatch, inference or owner;
- **no visible console window** (the supervisor's and the server's console has none: GetConsoleWindow) and **no
  orphan**: after down, the supervisor, the server and its launcher have exited and the port is free.

Windows only (the platform contract's only adapter). It fails, rather than skips, when 127.0.0.1:13310 is already
held: stop the service (service.py down) before running it.
"""
from __future__ import annotations

import datetime
import http.client
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ownerhost_support as T

CATEGORY = 'integration'
SV = T._load('aieh_ownerhost_service', T.PACKAGE / 'service.py')
A, S, E, CS = T.A, T.S, T.E, T.CS
ALLOWED_NAMES = {n.upper() for n in SV.ENVIRONMENT_NAMES}
METHODS = ('GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'HEAD')
PATHS = ('/session', '/', '/sessions', '/api/conversations', '/dispatch', '/docs')


def request(method, path, headers=None):
    connection = http.client.HTTPConnection(A.LOOPBACK, A.PORT, timeout=10)
    try:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        connection.close()


@unittest.skipUnless(sys.platform == 'win32', 'the platform contract has a Windows adapter only')
class Listener(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-ownerhost-listener-'))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.lay = SV.Layout(cls.tmp / 'state' / 'owner-host', cls.tmp / 'logs' / 'owner-host')
        cls.lay.state.mkdir(parents=True)
        cls.lay.logs.mkdir(parents=True)
        cls.adapter = SV.contract.select_adapter()
        if cls.adapter.port_in_use(A.PORT, A.LOOPBACK):
            raise AssertionError(f'{A.LOOPBACK}:{A.PORT} is already held: stop the Integration process '
                                 '(service.py down) before running the listener tests')
        cls.store = CS.open_store(cls.lay.store)
        cls.addClassCleanup(cls.store.close)
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        cls.revoked, cls.revoked_record = E.enroll(cls.store, hours=12, clock=lambda: now - datetime.timedelta(minutes=1))
        cls.expired, _ = E.enroll(cls.store, hours=1, clock=lambda: now - datetime.timedelta(days=2))
        cls.samples = {cid: value for cid, value in T.samples().items() if '\n' not in value}
        planted = {f'AIEH_PLANTED_{i}': value for i, value in enumerate([cls.revoked, cls.expired,
                                                                          *cls.samples.values()])}
        cls.held = [cls.revoked, cls.expired, *cls.samples.values()]
        cls.obs = {}
        try:
            with mock.patch.dict(os.environ, planted):
                cls.obs['planted_in_caller'] = all(os.environ.get(k) == v for k, v in planted.items())
                cls.obs['up'] = SV.up(cls.lay, cls.adapter)
            cls.observe_running()
        finally:
            cls.stop()

    @classmethod
    def observe_running(cls):
        obs, adapter = cls.obs, cls.adapter
        run = json.loads(cls.lay.run_record.read_text(encoding='utf-8'))
        obs['run'] = run
        obs['server_record_at_start'] = json.loads(cls.lay.server_record.read_text(encoding='utf-8'))
        server_pid, supervisor_pid = run['server']['pid'], run['supervisor']['pid']
        obs['handles'] = {name: adapter.process(pid) for name, pid in (
            ('server', server_pid), ('supervisor', supervisor_pid), ('server launcher', run['server_launch']['pid']))}
        obs['server_rows'] = adapter.listeners(server_pid)
        obs['port_rows'] = [r for r in adapter.listeners() if r['proto'] == 'tcp' and r['port'] == A.PORT]
        obs['readiness'] = SV.readiness(cls.lay, adapter)
        guest = T._load('aieh_guest_for_ownerhost_census', T.REPO / 'tools' / 'guest.py')
        obs['census'] = guest.host_census()
        # every request needs the credential
        obs['walk'] = {(m, p): request(m, p) for m in METHODS for p in PATHS}
        obs['preflight'] = request('OPTIONS', '/session', {
            'Origin': T.SHELL_ORIGIN, 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'x-aieh-owner-session'})

        def refused(*headers):
            before = cls.store.canonical_dump()
            answer = request('POST', '/session', dict(headers))
            return answer, before == cls.store.canonical_dump()
        foreign = E.mint()
        cls.held.append(foreign)
        obs['refusals'] = {
            'SESSION_CREDENTIAL_MISSING': refused(),
            'SESSION_CREDENTIAL_FOREIGN': refused((S.HEADER, foreign)),
            'SESSION_CREDENTIAL_EXPIRED': refused((S.HEADER, cls.expired)),
            'SESSION_CREDENTIAL_REVOKED': refused((S.HEADER, cls.revoked)),
        }
        obs['shapes'] = {cid: refused((S.HEADER, value)) for cid, value in cls.samples.items()}
        cls.current, cls.current_record = E.enroll(cls.store, hours=1)
        cls.held.append(cls.current)
        obs['accepted'] = request('POST', '/session', {S.HEADER: cls.current, 'Origin': T.SHELL_ORIGIN})
        obs['expired_after_new_enrollment'] = refused((S.HEADER, cls.expired))
        # what the processes hold, read from outside
        probe = T._load('aieh_ownerhost_process_probe', T.HERE / 'process_probe.py')
        obs['server_parameters'] = probe.parameters(server_pid)
        obs['supervisor_parameters'] = probe.parameters(supervisor_pid)

    @classmethod
    def stop(cls):
        try:
            cls.obs['down'] = SV.down(cls.lay, cls.adapter)
        finally:
            run = SV.contract.read_run_record(cls.lay.run_record) or {}
            supervisor = SV.live(cls.adapter, run, 'supervisor')
            if supervisor is not None:           # started by this test: never left behind
                supervisor.terminate()
                supervisor.wait(SV.STOP_CEILING_S)
        cls.obs['port_open_after'] = cls.adapter.port_in_use(A.PORT, A.LOOPBACK)
        cls.obs['alive_after'] = {name: proc.alive() for name, proc in cls.obs.get('handles', {}).items()}
        if cls.lay.server_record.exists():
            cls.obs['server_record_at_stop'] = json.loads(cls.lay.server_record.read_text(encoding='utf-8'))
        cls.obs['logs'] = {p.name: p.read_text(encoding='utf-8', errors='replace') for p in cls.lay.logs.iterdir()}
        cls.obs['records'] = {p.name: p.read_text(encoding='utf-8') for p in cls.lay.state.glob('*.json')}

    # -------------------------------------------------------------- binds 127.0.0.1 only

    def test_the_server_listens_on_127_0_0_1_13310_and_nowhere_else(self):
        server_pid = self.obs['run']['server']['pid']
        self.assertEqual([(r['proto'], r['address'], r['port']) for r in self.obs['server_rows']],
                         [('tcp', '127.0.0.1', 13310)])
        self.assertEqual({r['pid'] for r in self.obs['port_rows']}, {server_pid})
        self.assertTrue(self.obs['readiness']['passed'], self.obs['readiness']['checks'])
        self.assertTrue(self.obs['run']['server']['in_supervisor_job'])

    def test_the_host_census_by_port_finds_it_on_loopback_only(self):
        census = self.obs['census']
        rows = [r for r in census['listeners'] if r['port'] == A.PORT]
        self.assertTrue(rows, census)
        self.assertEqual({(r['address'], r['pid'], r['found_by']) for r in rows},
                         {('127.0.0.1', self.obs['run']['server']['pid'], 'port')})
        self.assertEqual([p for p in census['problems'] if p.get('port') == A.PORT], [])

    # -------------------------------------------------------------- every request needs the credential

    def test_every_route_and_method_without_the_credential_is_refused_as_missing(self):
        for (method, path), (status, headers, body) in self.obs['walk'].items():
            with self.subTest(method=method, path=path):
                self.assertEqual(status, 401)
                if method != 'HEAD':
                    self.assertEqual(T.code_of(body), 'SESSION_CREDENTIAL_MISSING')
                self.assertNotIn('set-cookie', headers)

    def test_the_preflight_carries_no_data(self):
        status, headers, body = self.obs['preflight']
        self.assertEqual((status, body), (200, b'OK'))
        self.assertEqual(headers['access-control-allow-origin'], T.SHELL_ORIGIN)
        self.assertNotIn('access-control-allow-credentials', headers)
        self.assertNotIn('set-cookie', headers)

    # -------------------------------------------------------------- refusals change nothing

    def test_missing_foreign_expired_and_revoked_each_refused_with_its_code_changing_nothing(self):
        for code, ((status, headers, body), unchanged) in self.obs['refusals'].items():
            with self.subTest(code=code):
                self.assertEqual((status, T.code_of(body)), (401, code))
                self.assertTrue(unchanged, f'{code} changed the store')
        (status, _, body), unchanged = self.obs['expired_after_new_enrollment']
        self.assertEqual((status, T.code_of(body), unchanged), (401, 'SESSION_CREDENTIAL_REVOKED', True))

    def test_every_other_inventory_credential_shape_is_foreign(self):
        self.assertEqual(set(self.obs['shapes']), {cid for cid, make in T.SHAPES.items() if make is not None}
                         - {'cred-guest-ssh-key', 'cred-guest-host-keys'})
        for cid, ((status, _, body), unchanged) in self.obs['shapes'].items():
            with self.subTest(credential=cid):
                self.assertEqual((status, T.code_of(body), unchanged), (401, 'SESSION_CREDENTIAL_FOREIGN', True))

    def test_the_enrolled_current_session_is_accepted(self):
        status, headers, body = self.obs['accepted']
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['sessionId'], self.current_record.session_id)
        self.assertEqual(headers['access-control-allow-origin'], T.SHELL_ORIGIN)

    # -------------------------------------------------------------- no credential present

    def test_the_server_and_supervisor_environments_and_command_lines_hold_no_credential(self):
        # the falsifier is live: the environment that ran up held every planted value
        self.assertTrue(self.obs['planted_in_caller'])
        for process in ('server', 'supervisor'):
            with self.subTest(process=process):
                parameters = self.obs[f'{process}_parameters']
                names = {name.upper() for name in parameters['environment']}
                self.assertLessEqual(names - {'__PYVENV_LAUNCHER__'}, ALLOWED_NAMES, names)
                text = json.dumps(parameters)
                self.assertEqual(T.exposures(text, self.held), [])
                self.assertNotIn('AIEH_PLANTED', text)

    def test_the_records_and_the_logs_hold_no_credential(self):
        texts = {**self.obs['records'], **self.obs['logs']}
        self.assertLessEqual({'run.json', 'server.json', 'service.log', 'console.log', 'supervisor.log'},
                             set(texts))
        for name, text in texts.items():
            with self.subTest(file=name):
                self.assertEqual(T.exposures(text, self.held), [])
        self.assertIn(f'accepted POST /session 200 session={self.current_record.session_id}',
                      self.obs['logs']['service.log'])
        self.assertIn('refused SESSION_CREDENTIAL_FOREIGN POST /session', self.obs['logs']['service.log'])
        config = self.obs['run']['configuration']
        self.assertEqual((config['address'], config['port']), ('127.0.0.1', 13310))

    def test_the_live_import_census_is_the_server_s_four_modules(self):
        expected = ['integrations/conversation/conversation_store.py', 'integrations/ownerhost/app.py',
                    'integrations/ownerhost/session.py', 'integrations/storecore/storecore.py']
        self.assertEqual(self.obs['server_record_at_start']['harness_modules'], expected)
        self.assertEqual(self.obs['server_record_at_stop']['harness_modules'], expected)

    def test_the_supervisor_s_live_import_census_has_no_credential_module(self):
        forbidden = ('integrations/credentials/', 'integrations/gitea/', 'integrations/dispatch/',
                     'integrations/inference/', 'integrations/owner/')
        for when, record in (('running', self.obs['run']), ('stopped', json.loads(self.obs['records']['run.json']))):
            with self.subTest(when=when):
                modules = record['supervisor_modules']
                self.assertIn('integrations/ownerhost/service.py', modules)
                self.assertIn('integrations/platform/platform_windows.py', modules)
                self.assertEqual([m for m in modules if m.startswith(forbidden)], [])

    # -------------------------------------------------------------- no window, no orphan

    def test_no_console_window(self):
        self.assertIs(self.obs['run']['console_window'], False)
        self.assertIs(self.obs['server_record_at_start']['console_window'], False)

    def test_down_leaves_no_process_and_frees_the_port(self):
        self.assertEqual(self.obs['down']['method'], 'stop request')
        self.assertEqual(self.obs['alive_after'], {'server': False, 'supervisor': False, 'server launcher': False})
        self.assertFalse(self.obs['port_open_after'])
        self.assertEqual(self.obs['server_record_at_stop']['state'], 'stopped')
        self.assertEqual(json.loads(self.obs['records']['run.json'])['state'], 'stopped')
        self.assertFalse(self.lay.stop_request.exists())


if __name__ == '__main__':
    unittest.main()
