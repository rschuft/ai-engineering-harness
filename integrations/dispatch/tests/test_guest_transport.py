"""Tests for the dispatcher's live transport (plan leaf E-01.3.3; decision 0013 point 1, bootstrap reading), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -v

``guest_transport.GuestTransport`` is the transport of ``dispatch_inputs.AgentServerClient`` over
``tools/guest.py``'s ``GuestApi``. Shown here:

* the transport seam: ``{"status", "body"}`` for any HTTP answer, ``TransportError`` for none, for a malformed
  probe result and for an answer that carried the management key; ``calls`` holds the body's digest only;
* the custody it requires: the profile's guest login is the key file's group (root:<login> 0440 in
  root:<login> 0750), and the API channel runs as that login;
* a fake ssh and the real API probe (``guest.API_PROBE``, run locally under the base interpreter against a
  loopback fake Agent Server that answers as the pinned 1.60.1 server did): the key is read from the "guest"
  file only and sent on the guest side; it is never on the ssh command line or in the script, never in an
  answer, a record or a refusal, and the host process never opens the host custody copy (which holds the same
  synthetic key); the dispatcher's order (``dispatch``) runs over it end to end.

Every value is synthetic. No guest, ssh, Agent Server or network beyond the test's own loopback listener.
"""
from pathlib import Path
import builtins
import copy
import http.server
import importlib.util
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BASE_PYTHON = getattr(sys, '_base_executable', sys.executable)
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


gt = _load('guest_transport', HERE.parent / 'guest_transport.py')
cc = _load('test_conversation_create', HERE / 'test_conversation_create.py')
adm, di = cc.adm, cc.di
guest = _load('aieh_guest_for_dispatch_tests', REPO / 'tools' / 'guest.py')
PROFILE = json.loads((REPO / 'profiles' / 'strong-windows-qemu-whpx' / 'profile.json').read_text(encoding='utf-8'))
KEY_FILE = PROFILE['provisioning']['agent_server']['session_key']['guest_path']
SYNTHETIC_KEY = 'synthetic-session-key-' + 'Q' * 21  # 43 characters, as the real key is


def answer(status=200, body=None, hits=0, **extra):
    return {'responses': [{'status': status, 'body': body, 'seconds': 0.01, **extra}],
            'session_key_occurrences': hits}


class FakeApi:
    """GuestApi's call shape: a list of requests in, the probe's JSON line out."""

    def __init__(self, *answers, error=None):
        self.answers, self.error, self.requests = list(answers), error, []

    def __call__(self, requests, timeout=900, secret=None):
        self.requests.append(copy.deepcopy(requests))
        if self.error is not None:
            raise self.error
        return self.answers.pop(0)


def transport(api, profile=PROFILE):
    return gt.GuestTransport(api, profile, api_login='agent')


class SeamTests(unittest.TestCase):
    """The transport contract of AgentServerClient, over a fake GuestApi."""
    category = 'unit'

    def test_one_request_per_call_and_the_answer_as_status_and_body(self):
        api = FakeApi(answer(200, {'version': '1.60.1'}), answer(201, {'id': 'x'}))
        t = transport(api)
        self.assertEqual(t('GET', '/server_info', None), {'status': 200, 'body': {'version': '1.60.1'}})
        self.assertEqual(t('POST', '/api/conversations', {'b': 1, 'a': [2]}), {'status': 201, 'body': {'id': 'x'}})
        self.assertEqual(api.requests, [
            [{'method': 'GET', 'path': '/server_info', 'timeout': gt.CALL_TIMEOUT_S}],
            [{'method': 'POST', 'path': '/api/conversations', 'timeout': gt.CALL_TIMEOUT_S, 'json': {'b': 1, 'a': [2]}}]])
        self.assertEqual([(c['method'], c['path'], c['status']) for c in t.calls],
                         [('GET', '/server_info', 200), ('POST', '/api/conversations', 201)])
        self.assertIsNone(t.calls[0]['body_sha256'])
        self.assertEqual(t.calls[1]['body_sha256'], gt.body_sha256({'a': [2], 'b': 1}))
        self.assertNotIn('"a"', json.dumps(t.calls))

    def test_every_http_status_is_an_answer(self):
        for status in (401, 404, 422, 500, 503):
            with self.subTest(status=status):
                self.assertEqual(transport(FakeApi(answer(status, 'text')))('GET', '/x', None),
                                 {'status': status, 'body': 'text'})

    def test_no_answer_is_raised(self):
        cases = {'refused': {'responses': [{'error': 'ECONNREFUSED'}], 'session_key_occurrences': 0},
                 'a status of another type': answer('200'), 'a bool status': answer(True),
                 'no responses': {'responses': [], 'session_key_occurrences': 0},
                 'two responses': {'responses': [{'status': 200}] * 2, 'session_key_occurrences': 0},
                 'no count': {'responses': [{'status': 200}]}, 'a list': [], 'a response list': answer(200) | {
                     'responses': [[200]]}}
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(gt.TransportError) as caught:
                transport(FakeApi(data))('GET', '/x', None)
            self.assertEqual(caught.exception.code, 'NO_ANSWER')

    def test_an_answer_that_carried_the_key_is_refused(self):
        t = transport(FakeApi(answer(200, {'echo': '<OH_SESSION_API_KEYS_0 redacted>'}, hits=1)))
        with self.assertRaises(gt.TransportError) as caught:
            t('GET', '/x', None)
        self.assertEqual(caught.exception.code, 'SECRET_IN_ANSWER')
        self.assertEqual(t.calls[0]['error'], 'SECRET_IN_ANSWER')

    def test_a_failing_channel_is_re_raised_and_recorded(self):
        t = transport(FakeApi(error=subprocess.TimeoutExpired(['ssh'], 900)))
        with self.assertRaises(subprocess.TimeoutExpired):
            t('POST', '/api/conversations', {})
        self.assertEqual(t.calls[0]['error'], 'TimeoutExpired')
        self.assertIsNone(t.calls[0]['status'])

    def test_the_body_digest_is_canonical(self):
        self.assertEqual(gt.body_sha256({'a': 1, 'b': [1, 'é']}), gt.body_sha256({'b': [1, 'é'], 'a': 1}))
        self.assertNotEqual(gt.body_sha256({'a': 1}), gt.body_sha256({'a': '1'}))
        self.assertIsNone(gt.body_sha256(None))
        with self.assertRaises(ValueError):
            gt.body_sha256({'a': float('nan')})


class CustodyTests(unittest.TestCase):
    """The declared custody the transport requires (decision 0013 point 1, bootstrap; ruling R9)."""
    category = 'contract'

    def test_the_checked_in_profile_declares_the_bootstrap_custody(self):
        self.assertEqual(gt.declared_custody(PROFILE), {
            'login': 'agent', 'key_file': KEY_FILE, 'owner': 'root', 'group': 'agent', 'mode': '440',
            'guest_dir_owner': 'root', 'guest_dir_group': 'agent', 'guest_dir_mode': '750'})

    def test_another_declaration_is_refused(self):
        def variant(change):
            profile = copy.deepcopy(PROFILE)
            change(profile)
            return profile
        key = ('provisioning', 'agent_server', 'session_key')

        def set_key(field, value):
            def change(p):
                p[key[0]][key[1]][key[2]][field] = value
            return change
        cases = {'another group': set_key('group', 'dispatch'), 'a readable mode': set_key('mode', '444'),
                 'another owner': set_key('owner', 'agent'), 'another directory group': set_key('guest_dir_group', 'x'),
                 'an open directory': set_key('guest_dir_mode', '755'), 'a relative path': set_key('guest_path', 'k'),
                 'another login': lambda p: p['identity'].update(guest_user='operator'),
                 'no login': lambda p: p['identity'].pop('guest_user'),
                 'no key': lambda p: p[key[0]][key[1]].pop(key[2])}
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(gt.TransportError) as caught:
                transport(FakeApi(), variant(change))
            self.assertEqual(caught.exception.code, 'KEY_CUSTODY_UNDECLARED')
        for profile in (None, [], {'identity': 'agent'}):
            with self.assertRaises(gt.TransportError):
                gt.declared_custody(profile)

    def test_the_channel_must_run_as_the_login_that_holds_the_key(self):
        with self.assertRaises(gt.TransportError) as caught:
            gt.GuestTransport(FakeApi(), PROFILE, api_login='root')
        self.assertEqual(caught.exception.code, 'LOGIN_MISMATCH')
        with self.assertRaises(TypeError):
            gt.GuestTransport(None, PROFILE, api_login='agent')
        # tools/guest.py's channel login is the one GuestApi's ssh.run uses by default
        self.assertEqual(guest.GUEST_API_LOGIN, 'agent')
        for method in (guest.Ssh.run, guest.Ssh.run_raw):
            self.assertEqual(inspect.signature(method).parameters['user'].default, guest.GUEST_API_LOGIN)

    def test_for_instance_builds_the_instances_channel(self):
        made = []

        class Ssh:
            def __init__(self, profile, idir, port):
                made.append(('ssh', idir, port))

        class GuestApi:
            def __init__(self, ssh, profile):
                made.append(('api', type(ssh).__name__))

            def __call__(self, requests, timeout=900):
                return answer(200, {})
        ctx = types.SimpleNamespace(profile=PROFILE, instance_dir=lambda name: f'instances/{name}')
        fake = types.SimpleNamespace(Ssh=Ssh, GuestApi=GuestApi, GUEST_API_LOGIN='agent',
                                     running_instance=lambda c, n: (None, {'provisioning': {}, 'ports': {'ssh': 40022}}))
        with self.assertRaises(gt.TransportError) as caught:
            gt.for_instance(fake, ctx, 'g1')
        self.assertEqual(caught.exception.code, 'NOT_PROVISIONED')
        fake.running_instance = lambda c, n: (None, {'provisioning': {'image_id': 'x'}, 'ports': {'ssh': 40022}})
        t = gt.for_instance(fake, ctx, 'g1')
        self.assertEqual(made, [('ssh', 'instances/g1', 40022), ('api', 'Ssh')])
        self.assertEqual(t('GET', '/health', None), {'status': 200, 'body': {}})


class FakeAgentServer(http.server.ThreadingHTTPServer):
    """The guest's Agent Server on a loopback port: the recorded /server_info and create answers when the request
    carries the session key, 401 otherwise; /leak echoes the key. Every request's key header is recorded."""

    def __init__(self):
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def handle_any(self, body=None):
                key = self.headers.get('X-Session-API-Key')
                server.seen.append((self.command, self.path, key, body))
                if key != SYNTHETIC_KEY:
                    return self.reply(401, {'detail': 'Unauthorized'})
                if (self.command, self.path) == cc.INFO:
                    return self.reply(cc.SERVER_INFO['status'], cc.SERVER_INFO['body'])
                if self.path == '/leak':
                    return self.reply(200, {'echo': key})
                if (self.command, self.path) == cc.CREATE:
                    created = copy.deepcopy(cc.CREATE_ANSWER['body'])
                    created['id'] = body['conversation_id']
                    return self.reply(cc.CREATE_ANSWER['status'], created)
                return self.reply(404, {'detail': 'Not Found'})

            def do_GET(self):
                self.handle_any()

            def do_POST(self):
                self.handle_any(json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0)))))

        super().__init__(('127.0.0.1', 0), Handler)
        self.seen = []


class FakeSsh:
    """guest.Ssh's run(): the remote command runs locally under the base interpreter, as the guest would run it,
    with the guest's key file and listener mapped to the test's own (the key file of a fake guest root, the
    loopback fake server). Every command line and script it is given is kept."""

    def __init__(self, guest_root, port):
        self.guest_root, self.port, self.runs = guest_root, port, []

    def run(self, command, user='agent', input_text=None, timeout=300):
        self.runs.append({'argv': list(command), 'user': user, 'script': input_text})
        assert command[:2] == ['python3', '-'], command
        key_path, _address, _port, *rest = command[2:]
        local = [BASE_PYTHON, '-I', '-', str(self.guest_root / key_path.lstrip('/')), '127.0.0.1',
                 str(self.port), *rest]
        done = subprocess.run(local, input=input_text.encode('utf-8'), capture_output=True, timeout=timeout,
                              creationflags=NO_WINDOW)
        return subprocess.CompletedProcess(command, done.returncode,
                                           done.stdout.decode('utf-8', 'replace').replace('\r\n', '\n'),
                                           done.stderr.decode('utf-8', 'replace'))


class OpenSpy:
    """Every path the host process opens (builtins.open, io.open, os.open; pathlib reads go through io.open)."""

    def __init__(self):
        self.paths = []

    def __enter__(self):
        real_open, real_os_open = io.open, os.open

        def spy(file, *args, **kwargs):
            self.note(file)
            return real_open(file, *args, **kwargs)

        def os_spy(path, *args, **kwargs):
            self.note(path)
            return real_os_open(path, *args, **kwargs)
        self.patches = [mock.patch.object(builtins, 'open', spy), mock.patch.object(io, 'open', spy),
                        mock.patch.object(os, 'open', os_spy)]
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self.patches):
            patch.stop()

    def note(self, file):
        if isinstance(file, (str, bytes, os.PathLike)):
            self.paths.append(os.path.normcase(os.path.abspath(os.fsdecode(file))))

    def opened(self, path):
        return os.path.normcase(os.path.abspath(path)) in self.paths


class ProbePairTests(unittest.TestCase):
    """GuestApi with a fake ssh and the real API probe: the key stays in the "guest"."""
    category = 'integration'

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-guest-transport-'))
        guest_key = cls.tmp / 'guest' / KEY_FILE.lstrip('/')
        guest_key.parent.mkdir(parents=True)
        guest_key.write_text(SYNTHETIC_KEY + '\n', encoding='ascii')
        # the host custody copy (session_key.host_path) holds the same value: the dispatcher never opens it
        cls.custody = cls.tmp / 'instances' / 'g1' / 'agent-server' / 'session.key'
        cls.custody.parent.mkdir(parents=True)
        cls.custody.write_text(SYNTHETIC_KEY + '\n', encoding='ascii')
        cls.server = FakeAgentServer()
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(10)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.server.seen.clear()
        self.ssh = FakeSsh(self.tmp / 'guest', self.server.server_address[1])
        self.transport = gt.GuestTransport(guest.GuestApi(self.ssh, PROFILE), PROFILE, api_login=guest.GUEST_API_LOGIN)

    def host_side_text(self, *outputs):
        """Everything the host process kept or printed: the outputs given, the transport's records, and every ssh
        command line and script."""
        return json.dumps([outputs, self.transport.calls, self.ssh.runs], default=repr)

    def test_the_key_is_read_and_sent_in_the_guest_only(self):
        client = cc.client(self.transport)
        with OpenSpy() as spy:
            info = client.call('GET', '/server_info')
            created = client.call('POST', '/api/conversations', body={'conversation_id': cc.CONVERSATION, 'x': 1})
        self.assertEqual(info, {'status': 200, 'body': cc.SERVER_INFO['body']})
        self.assertEqual((created['status'], created['body']['id']), (201, cc.CONVERSATION))
        # the server saw the key on the guest side, on both calls (the positive control of the key's path)
        self.assertEqual([(m, p, k) for m, p, k, _ in self.server.seen],
                         [('GET', '/server_info', SYNTHETIC_KEY), ('POST', '/api/conversations', SYNTHETIC_KEY)])
        # never on a command line, in a script, an answer or a record of the host process
        self.assertEqual([r['user'] for r in self.ssh.runs], ['agent', 'agent'])
        self.assertTrue(all(r['argv'][2] == KEY_FILE for r in self.ssh.runs))
        self.assertTrue(all(r['script'] == guest.API_PROBE for r in self.ssh.runs))
        self.assertNotIn(SYNTHETIC_KEY, self.host_side_text(info, created))
        # the host custody copy, holding the same value, was never opened by the host process
        self.assertFalse(spy.opened(self.custody), 'the dispatcher opened the host custody copy')
        self.assertEqual([c['status'] for c in self.transport.calls], [200, 201])

    def test_the_checks_would_see_a_leak(self):
        """Negative controls: an open of the custody copy is seen by the spy, and a host-side text holding the
        key is found."""
        with OpenSpy() as spy:
            self.custody.read_bytes()
        self.assertTrue(spy.opened(self.custody))
        self.transport('GET', '/server_info', None)
        self.ssh.runs[0]['argv'].append(SYNTHETIC_KEY)
        self.assertIn(SYNTHETIC_KEY, self.host_side_text())

    def test_an_answer_carrying_the_key_is_redacted_in_the_guest_and_refused(self):
        with self.assertRaises(gt.TransportError) as caught:
            self.transport('GET', '/leak', None)
        self.assertEqual(caught.exception.code, 'SECRET_IN_ANSWER')
        self.assertNotIn(SYNTHETIC_KEY, self.host_side_text(str(caught.exception)))

    def test_a_wrong_key_file_gets_the_servers_refusal_as_an_answer(self):
        ssh = FakeSsh(self.tmp / 'nowhere', self.server.server_address[1])
        broken = gt.GuestTransport(guest.GuestApi(ssh, PROFILE), PROFILE, api_login='agent')
        with self.assertRaises(guest.Refused) as caught:  # the probe cannot open the key file: no result line
            broken('GET', '/server_info', None)
        self.assertEqual(caught.exception.code, 'API')
        self.assertEqual(broken.calls[0]['error'], 'Refused')


class DispatchOverTheProbePairTests(adm.AdmissionFixture):
    """The dispatcher's order (dispatch) over GuestTransport, end to end through the fake ssh and the real probe:
    op-as-conversation-create on Work goes through the dispatch module over GuestApi."""

    def test_dispatch_creates_through_the_live_transport(self):
        server = FakeAgentServer()
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        root = self.case / 'guest'
        key = root / KEY_FILE.lstrip('/')
        key.parent.mkdir(parents=True)
        key.write_text(SYNTHETIC_KEY + '\n', encoding='ascii')
        ssh = FakeSsh(root, server.server_address[1])
        live = gt.GuestTransport(guest.GuestApi(ssh, PROFILE), PROFILE, api_login='agent')
        result = di.dispatch(self.request(), manifest=self.write_manifest(self.manifest_data(), self.fresh('m')),
                             work_sources=self.sources.get, integration_store=self.store, workspaces=self.workspaces,
                             transport=live, actor='transport-test', read_profile=self.read_profile,
                             read_artifact=self.read_artifact)
        self.assertEqual(self.store.get(result.operation_key).state, 'confirmed')
        self.assertEqual([(m, p, k == SYNTHETIC_KEY) for m, p, k, _ in server.seen],
                         [('GET', '/server_info', True), ('POST', '/api/conversations', True)])
        self.assertEqual(server.seen[1][3]['conversation_id'], result.conversation_id)
        self.assertNotIn(SYNTHETIC_KEY, json.dumps([live.calls, ssh.runs]))
        self.assertNotIn(SYNTHETIC_KEY, self.store.canonical_dump().decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
