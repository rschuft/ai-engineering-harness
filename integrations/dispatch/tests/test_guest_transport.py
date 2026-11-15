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
import hashlib
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

    def test_a_body_with_secrets_gets_no_digest_and_every_body_is_sealed(self):
        """R7 (E-05.11 review N4, now in the transport): a body that carries secrets is recorded without a digest;
        any other body keeps its digest. Every body goes sealed (standard input): the body's secret word, else a
        fresh nonce that is not in the body; a bodyless call goes unsealed."""
        seals = []

        def api(requests, timeout=900, secret=None):
            seals.append(secret)
            return answer(201, {})
        t = transport(api)
        t('POST', '/api/conversations', copy.deepcopy(SECRET_BODY))
        t('POST', '/api/conversations', {'secrets': {}})
        t('POST', '/api/conversations/x/events', {'role': 'user'})
        t('GET', '/server_info', None)
        self.assertEqual([c['body_sha256'] for c in t.calls],
                         [None, None, gt.body_sha256({'role': 'user'}), None])
        self.assertEqual(seals[0], TOKEN)
        for nonce in seals[1:3]:
            self.assertRegex(nonce, r'^[A-Za-z0-9_-]{43}$')
        self.assertNotEqual(seals[1], seals[2])
        self.assertIsNone(seals[3])
        self.assertNotIn(TOKEN, json.dumps(t.calls))

    def test_a_delivery_is_passed_on_and_its_answer_checked(self):
        delivered = {'name': 'work-1.bundle', 'sha256': 'a' * 64, 'size': 10}
        api = FakeApi(answer(200, {'stdout': 'AIEH-EXCHANGE-DELIVERED bundle ' + 'a' * 64 + ' 10'},
                             delivered=delivered))
        t = transport(api)
        got = t('POST', '/api/conversations/x/bash/execute_bash_command', {'command': 'c'},
                deliver={'part': 'bundle', 'name': 'work-1.bundle'})
        self.assertEqual(api.requests[0][0]['deliver'], {'part': 'bundle', 'name': 'work-1.bundle'})
        self.assertEqual(got['delivered'], delivered)
        self.assertEqual(t.calls[0]['delivered'], delivered)
        for bad in ({'name': 'other.bundle', 'sha256': 'a' * 64, 'size': 10}, {'name': 'work-1.bundle'},
                    {'name': 'work-1.bundle', 'sha256': 'A' * 64, 'size': 10},
                    {'name': 'work-1.bundle', 'sha256': 'a' * 64, 'size': -1},
                    {'name': 'work-1.bundle', 'sha256': 'a' * 64, 'size': True}, None, 'x',
                    {'error': 5}, {'error': 'EXISTS', 'size': 1}):
            with self.subTest(delivered=bad):
                t = transport(FakeApi(answer(200, {}, delivered=bad)))
                got = t('POST', '/p', {'command': 'c'}, deliver={'part': 'bundle', 'name': 'work-1.bundle'})
                self.assertEqual(got['delivered'], {'error': 'MALFORMED'})
        t = transport(FakeApi(answer(200, {}, delivered={'error': 'EXISTS'})))
        self.assertEqual(t('POST', '/p', {'c': 1}, deliver={'part': 'b', 'name': 'n'})['delivered'],
                         {'error': 'EXISTS'})
        for deliver, body in (({'part': 'b'}, {'c': 1}), ({'part': 'b', 'name': 'n', 'dir': '/'}, {'c': 1}),
                              ({'part': 'b', 'name': 5}, {'c': 1}), ('n', {'c': 1}),
                              ({'part': 'b', 'name': 'n'}, None)):
            with self.subTest(deliver=deliver), self.assertRaises(gt.TransportError) as caught:
                transport(FakeApi())('POST', '/p', body, deliver=deliver)
            self.assertEqual(caught.exception.code, 'DELIVERY_INVALID')
        # without a delivery the answer is {status, body} only, as before
        self.assertEqual(transport(FakeApi(answer(200, {})))('POST', '/p', {'c': 1}), {'status': 200, 'body': {}})

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
                if self.command == 'POST' and self.path.endswith('/bash/execute_bash_command'):
                    return self.reply(200, {'command': body.get('command'), 'exit_code': 0,
                                            'stdout': server.stdout, 'stderr': server.stderr})
                return self.reply(404, {'detail': 'Not Found'})

            def do_GET(self):
                self.handle_any()

            def do_POST(self):
                self.handle_any(json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0)))))

        super().__init__(('127.0.0.1', 0), Handler)
        self.seen, self.stdout, self.stderr = [], '', ''


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
        # the bodyless GET in the probe's argument form; the create, a body, sealed in the script on standard input
        # (D1 work design G2), its argv the key file, the address and the port only
        self.assertEqual(self.ssh.runs[0]['script'], guest.API_PROBE)
        self.assertEqual(len(self.ssh.runs[1]['argv']), 5)
        self.assertTrue(self.ssh.runs[1]['script'].startswith('SEALED = (')
                        and self.ssh.runs[1]['script'].endswith(guest.API_PROBE))
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


TOKEN = 'aieh-inf-' + 'Kq7_' * 10 + 'Zz9'        # an attempt token's shape (synthetic)
SECRET_BODY = {'conversation_id': cc.CONVERSATION, 'x': 'body-marker-7b1c',
               'secrets': {'ANTHROPIC_API_KEY': {'kind': 'StaticSecret', 'value': TOKEN},
                           'ANTHROPIC_BASE_URL': {'kind': 'StaticSecret', 'value': 'http://172.17.0.1:8090'}},
               'secrets_encrypted': False}


def needles(body):
    """What must never be on a command line: the token, its body, the body's marker, and the request in the
    form the unsealed probe takes it (base64 JSON of the request list)."""
    request = [{'method': 'POST', 'path': '/api/conversations', 'timeout': gt.CALL_TIMEOUT_S, 'json': body}]
    spec = guest.base64.b64encode(json.dumps(request).encode('utf-8')).decode('ascii')
    return [TOKEN, TOKEN[9:], body['x'], spec, spec[:40]]


class SealedSecretsTests(unittest.TestCase):
    """E-05.6 (review R1): a call whose body carries secrets (the D1 create's attempt token) goes through
    GuestApi's sealed form: the request is on ssh's standard input, never in its argv or the guest python's, so
    neither a command line nor a TimeoutExpired raised by the real Ssh.run shows it."""
    category = 'integration'

    def ssh(self):
        """The real guest.Ssh over a throwaway instance directory, its ssh -G check and the ssh.exe lookup faked;
        its subprocess.run is faked by each test."""
        tmp = Path(tempfile.mkdtemp(prefix='aieh-sealed-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / 'ssh').mkdir()
        (tmp / 'ssh' / 'id_ed25519').write_text('synthetic', encoding='ascii')
        (tmp / 'ssh' / 'known_hosts').write_text('synthetic', encoding='ascii')
        with mock.patch.object(guest, 'openssh', return_value='ssh.exe'):
            ssh = guest.Ssh(PROFILE, tmp, 40022)
        ssh._checked = True
        return ssh

    def test_a_timeout_shows_no_part_of_a_body_with_secrets(self):
        runs = []

        def times_out(argv, input=None, timeout=None, **kwargs):
            runs.append((list(argv), input))
            raise subprocess.TimeoutExpired(argv, timeout, output=b'', stderr=b'')
        live = gt.GuestTransport(guest.GuestApi(self.ssh(), PROFILE), PROFILE, api_login='agent')
        with mock.patch.object(guest.subprocess, 'run', times_out):
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                live('POST', '/api/conversations', copy.deepcopy(SECRET_BODY))
        argv, stdin = runs[0]
        shown = json.dumps([argv, str(caught.exception), repr(caught.exception), caught.exception.cmd])
        for needle in needles(SECRET_BODY):
            self.assertNotIn(needle, shown)
        self.assertIn(TOKEN.encode(), stdin)   # it travelled on standard input, in the sealed probe's text
        # python3 - <key file> <address> <port>: no request argument
        self.assertEqual((argv[-5:-3], argv[-3]), (['python3', '-'], KEY_FILE))
        self.assertEqual(live.calls[0]['error'], 'TimeoutExpired')
        # A body without secrets is sealed too (D1 work design G2: every body on standard input), with a nonce.
        runs.clear()
        plain_body = {'conversation_id': cc.CONVERSATION, 'x': 'body-marker-7b1c'}
        with mock.patch.object(guest.subprocess, 'run', times_out):
            with self.assertRaises(subprocess.TimeoutExpired) as plain:
                live('POST', '/api/conversations', plain_body)
        shown = json.dumps([runs[0][0], str(plain.exception), repr(plain.exception)])
        for needle in needles(plain_body)[2:]:
            self.assertNotIn(needle, shown)
        self.assertIn(needles(plain_body)[3].encode(), runs[0][1])   # on standard input, in the sealed text
        # Negative control: GuestApi's unsealed form (its own probes' channel, never the transport's for a body):
        # the same search finds the request in argv.
        runs.clear()
        request = [{'method': 'POST', 'path': '/api/conversations', 'timeout': gt.CALL_TIMEOUT_S, 'json': plain_body}]
        with mock.patch.object(guest.subprocess, 'run', times_out):
            with self.assertRaises(subprocess.TimeoutExpired) as unsealed:
                guest.GuestApi(self.ssh(), PROFILE)(request)
        self.assertIn(needles(plain_body)[3], str(unsealed.exception))

    def test_a_long_native_token_is_sealed_itself(self):
        """E-05.11 review item 4: on the D1 path on the native profile the native token, up to its grammar's 512
        characters (native_token.TOKEN_LENGTH, the one source), is the sealed secret, never a nonce; the switches and
        the endpoint are not words of the seal."""
        ns = _load('native_support', HERE / 'native_support.py')
        nt = gt._native_token()
        self.assertEqual(gt.SEALABLE.pattern, r'[A-Za-z0-9_-]{16,%d}' % nt.TOKEN_LENGTH[1])
        for length in (129, 300, 512):
            token = ns.token(f'long native token {length}', length)
            self.assertTrue(nt.is_token(token))
            body = {'conversation_id': cc.CONVERSATION, 'secrets': {
                'CLAUDE_CODE_OAUTH_TOKEN': {'kind': 'StaticSecret', 'value': token},
                'HTTPS_PROXY': {'kind': 'StaticSecret', 'value': 'http://172.17.0.1:8090'},
                'CLAUDE_CODE_PROXY_RESOLVES_HOSTS': {'kind': 'StaticSecret', 'value': 'tRuE'},
                'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': {'kind': 'StaticSecret', 'value': 'tRuE'}}}
            self.assertEqual(gt.sealed_secret(body), token)
            seen = []
            t = transport(lambda requests, timeout=900, secret=None: seen.append(secret) or answer(201, {}))
            t('POST', '/api/conversations', body)
            self.assertEqual(seen, [token])
            # the real GuestApi's sealed probe takes it (SEALED_SECRET, one whole word up to 512)
            self.assertIn(repr(token), guest.sealed_api_probe('e30=', token))
        for bad in ('x' * 513, 'x' * 20 + '\n', 'x' * 15):
            with self.assertRaises(guest.Refused):
                guest.sealed_api_probe('e30=', bad)

    def test_the_sealed_secret_is_the_token_or_a_nonce(self):
        self.assertEqual(gt.sealed_secret(SECRET_BODY), TOKEN)
        two = copy.deepcopy(SECRET_BODY)
        two['secrets']['OTHER'] = {'kind': 'StaticSecret', 'value': 'another-url-safe-word-1234'}
        for body in (two, {'secrets': {}}, {'secrets': None}):
            with self.subTest(body=json.dumps(body)[:40]):
                nonce = gt.sealed_secret(body)
                self.assertRegex(nonce, r'^[A-Za-z0-9_-]{43}$')
                self.assertNotIn(nonce, json.dumps(body))
        api = FakeApi(answer(201, {'id': cc.CONVERSATION}), answer(200, {}))
        t = transport(api)
        calls = []
        real = api.__call__

        def recording(requests, timeout=900, secret=None):
            calls.append(secret)
            return real(requests, timeout, secret)
        t.api = recording
        t('POST', '/api/conversations', copy.deepcopy(SECRET_BODY))
        t('GET', '/server_info', None)
        self.assertEqual(calls, [TOKEN, None])


def framed(data, part='bundle', digest=None, size=None, width=76):
    """DATA as a command prints a part for the exchange delivery: tools/guest.py's frame, the payload in hex lines."""
    hexed = data.hex()
    return '\n'.join([guest.EXCHANGE_PART_BEGIN.format(part=part, sha256=digest or hashlib.sha256(data).hexdigest(),
                                                       size=len(data) if size is None else size),
                      *[hexed[i:i + width] for i in range(0, len(hexed), width)],
                      guest.EXCHANGE_PART_END.format(part=part)])


def _deliver_command(name='work-1.bundle', part='bundle'):
    """A test builder (D1's RESULT builder is slice A2's): a fixed command whose answer the transport delivers."""
    return {'command': 'make-the-bundle', 'timeout': 60, 'deliver': {'part': part, 'name': name}}


# registered once per process
cc.di.allow_test_builders('test-a1-delivery')   # tests only (D1 review S6)
deliver_command = cc.di._COMMAND_BUILDERS.get('test-a1-delivery') or \
    cc.di.command_builder('test-a1-delivery')(_deliver_command)


class ExchangeDeliveryTests(unittest.TestCase):
    """The API probe's exchange delivery (D1 work design G2), end to end: a built command through the dispatcher's
    client, GuestTransport, GuestApi, a fake ssh and the real probe against a fake Agent Server. The part is
    written exclusively and bounded into the exchange; only its name, sha256 and size come back."""
    category = 'integration'

    PAYLOAD = bytes(range(256)) * 40

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-delivery-'))
        guest_key = cls.tmp / 'guest' / KEY_FILE.lstrip('/')
        guest_key.parent.mkdir(parents=True)
        guest_key.write_text(SYNTHETIC_KEY + '\n', encoding='ascii')
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
        self.exchange = Path(tempfile.mkdtemp(prefix='exchange-', dir=self.tmp))
        self.profile = copy.deepcopy(PROFILE)
        self.profile['exchange']['guest_dir'] = str(self.exchange)   # the guest's exchange directory, here
        self.ssh = FakeSsh(self.tmp / 'guest', self.server.server_address[1])
        self.transport = gt.GuestTransport(guest.GuestApi(self.ssh, self.profile), PROFILE, api_login='agent')

    def run_command(self, stdout, name='work-1.bundle', part='bundle'):
        self.server.stdout = stdout
        return cc.client(self.transport).call(
            'POST', '/api/conversations/{conversation_id}/{tail}', body=deliver_command(name, part),
            params={'conversation_id': cc.CONVERSATION, 'tail': 'bash/execute_bash_command'})

    def files(self):
        return sorted(p.name for p in self.exchange.iterdir())

    def host_side(self, *values):
        return json.dumps([values, self.transport.calls, self.ssh.runs], default=repr)

    def test_the_part_is_written_and_only_its_digest_and_size_return(self):
        digest = hashlib.sha256(self.PAYLOAD).hexdigest()
        answer = self.run_command('Ran 3 tests\nOK\n' + framed(self.PAYLOAD) + '\ncommit 1234\n')
        self.assertEqual(answer['status'], 200)
        self.assertEqual(answer['delivered'], {'name': 'work-1.bundle', 'sha256': digest, 'size': len(self.PAYLOAD)})
        self.assertEqual((self.exchange / 'work-1.bundle').read_bytes(), self.PAYLOAD)
        self.assertEqual(answer['body']['stdout'], 'Ran 3 tests\nOK\n' + guest.EXCHANGE_PART_DELIVERED.format(
            part='bundle', sha256=digest, size=len(self.PAYLOAD)) + '\ncommit 1234\n')
        # no payload byte in anything the host process holds; the command went sealed, on standard input
        for needle in (self.PAYLOAD.hex()[:64], self.PAYLOAD.hex()[-64:]):
            self.assertNotIn(needle, self.host_side(answer))
        self.assertEqual(len(self.ssh.runs[0]['argv']), 5)
        self.assertEqual(self.transport.calls[0]['delivered']['sha256'], digest)
        # the wire body the server received is the client's exact grammar
        self.assertEqual(self.server.seen[-1][3], {'command': 'make-the-bundle', 'cwd': '/workspace', 'timeout': 60})
        # exclusive: the same name again is refused and the file is unchanged
        again = self.run_command(framed(b'other bytes'))
        self.assertEqual(again['delivered'], {'error': 'EXISTS'})
        self.assertEqual((self.exchange / 'work-1.bundle').read_bytes(), self.PAYLOAD)
        self.assertNotIn(b'other bytes'.hex(), self.host_side(again))

    def test_a_part_that_does_not_verify_is_not_written(self):
        upper = framed(self.PAYLOAD).split('\n')
        upper = '\n'.join([upper[0], *[line.upper() for line in upper[1:-1]], upper[-1]])
        cases = {
            'a digest mismatch': (framed(self.PAYLOAD, digest='0' * 64), 'DIGEST_MISMATCH'),
            'a size that is not the payload': (framed(self.PAYLOAD, size=len(self.PAYLOAD) - 1), 'PART_SIZE'),
            'two parts': (framed(self.PAYLOAD) + '\n' + framed(self.PAYLOAD), 'PART_MALFORMED'),
            'no end': (framed(self.PAYLOAD).rsplit('\n', 1)[0], 'PART_MALFORMED'),
            'upper-case hex': (upper, 'PART_MALFORMED'),
            'base64, not hex': ('AIEH-EXCHANGE-PART bundle ' + '0' * 64 + ' 3\nQUJD\nAIEH-EXCHANGE-END bundle',
                                'PART_MALFORMED'),
            'another part': (framed(self.PAYLOAD, part='other'), 'PART_MALFORMED'),
            'no part at all': ('Ran 3 tests\n', 'NO_PART'),
            'a failed step, no frame': ('AIEH-RESULT failed add 6e6f\n', 'NO_PART'),
            'an end marker alone': ('AIEH-EXCHANGE-END bundle\n', 'PART_MALFORMED'),
        }
        for number, (name, (stdout, code)) in enumerate(cases.items()):
            with self.subTest(name):
                answer = self.run_command(stdout, name=f'case-{number}.bundle')
                self.assertEqual(answer['delivered'], {'error': code})
                self.assertEqual(self.files(), [])
                self.assertNotIn(self.PAYLOAD.hex()[:64], self.host_side(answer))
                if code == 'PART_MALFORMED':
                    self.assertIsNone(answer['body']['stdout'])   # withheld: its frame could not be cut out
                if code == 'NO_PART':                              # D1 review S5: no marker, kept whole
                    self.assertEqual(answer['body']['stdout'], stdout)

    def test_a_frame_in_another_field_refuses_the_delivery(self):
        """Review A4 N-c (the reviewer's probe_s5): the frame is read from stdout only; a frame marker in any other
        field refuses the delivery and withholds that field (and stdout's frame, when it has one)."""
        self.server.stderr = framed(self.PAYLOAD)
        try:
            answer = self.run_command('Ran 3 tests\n' + framed(self.PAYLOAD) + '\n')
        finally:
            self.server.stderr = ''
        self.assertEqual(answer['delivered'], {'error': 'PART_ELSEWHERE'})
        self.assertIsNone(answer['body']['stderr'])
        self.assertIsNone(answer['body']['stdout'])
        self.assertEqual(self.files(), [])
        self.assertNotIn(self.PAYLOAD.hex()[:64], self.host_side(answer))

    def test_a_frame_beside_a_stdout_that_is_not_text_is_withheld(self):
        """Review A4 N-c (probe_s5's last case): no stdout string, the frame in another field: refused, withheld."""
        body = {'stdout': None, 'output': framed(self.PAYLOAD)}
        entry = {'body': body}
        spec = dict(guest.exchange_delivery(PROFILE, {'part': 'bundle', 'name': 'w.bundle'}), dir=str(self.exchange))
        namespace = {}
        probe = guest.API_PROBE
        exec(probe[:probe.index('# sealed (decision 0015)')].replace('key_path, host, port = sys.argv[1], sys.argv[2], '
                                                                    'int(sys.argv[3])', ''), namespace)
        self.assertEqual(namespace['deliver'](spec, entry), {'error': 'PART_ELSEWHERE'})
        self.assertEqual(body, {'stdout': None, 'output': None})
        self.assertEqual(self.files(), [])

    def test_the_file_appears_whole_and_a_leftover_partial_is_refused(self):
        """Review A4 N-e: the delivery writes <name>.partial and links it to <name>; no .partial remains, and a
        leftover .partial refuses the delivery (never completed, never pulled)."""
        answer = self.run_command(framed(self.PAYLOAD))
        self.assertEqual(answer['delivered']['size'], len(self.PAYLOAD))
        self.assertEqual(self.files(), ['work-1.bundle'])
        (self.exchange / 'work-2.bundle.partial').write_bytes(b'half')
        again = self.run_command(framed(self.PAYLOAD), name='work-2.bundle')
        self.assertEqual(again['delivered'], {'error': 'PARTIAL_EXISTS'})
        self.assertEqual(self.files(), ['work-1.bundle', 'work-2.bundle.partial'])
        self.assertEqual((self.exchange / 'work-2.bundle.partial').read_bytes(), b'half')

    def test_a_frame_with_crlf_lines_is_delivered(self):
        """D1 review S5: a frame whose lines end in CRLF is taken."""
        answer = self.run_command('Ran 3 tests\r\n' + framed(self.PAYLOAD).replace('\n', '\r\n') + '\r\n')
        self.assertEqual(answer['delivered']['sha256'], hashlib.sha256(self.PAYLOAD).hexdigest())
        self.assertEqual((self.exchange / 'work-1.bundle').read_bytes(), self.PAYLOAD)
        self.assertNotIn(self.PAYLOAD.hex()[:64], self.host_side(answer))

    def test_the_bound_is_the_profiles_pull_bound(self):
        self.profile['exchange']['pull']['max_bytes'] = len(self.PAYLOAD) - 1
        self.transport = gt.GuestTransport(guest.GuestApi(self.ssh, self.profile), PROFILE, api_login='agent')
        self.assertEqual(self.run_command(framed(self.PAYLOAD))['delivered'], {'error': 'PART_SIZE'})
        self.assertEqual(self.files(), [])
        self.assertEqual(guest.exchange_delivery(PROFILE, {'part': 'bundle', 'name': 'w.bundle'})['max_bytes'],
                         guest.EXCHANGE_DELIVERY_MAX_BYTES)

    def test_a_name_outside_the_grammar_is_refused_before_anything_is_sent(self):
        for name in ('../work.bundle', 'a/b.bundle', '.hidden', 'work.bundle.partial', '', 'x' * 101):
            with self.subTest(name=name), self.assertRaises(guest.Refused):
                self.transport('POST', f'/api/conversations/{cc.CONVERSATION}/bash/execute_bash_command',
                               {'command': 'c', 'cwd': '/workspace', 'timeout': 60},
                               deliver={'part': 'bundle', 'name': name})
        for deliver in ({'part': 'Bundle', 'name': 'w.bundle'}, {'part': 'bundle', 'name': 'w', 'x': 1}):
            with self.subTest(deliver=deliver), self.assertRaises(guest.Refused):
                guest.exchange_delivery(PROFILE, deliver)
        self.assertEqual(self.ssh.runs, [])
        self.assertEqual(self.files(), [])
        self.assertEqual(guest.exchange_delivery(PROFILE, {'part': 'bundle', 'name': 'w.bundle'}),
                         {'field': 'stdout', 'part': 'bundle', 'name': 'w.bundle', 'dir': PROFILE['exchange']['guest_dir'],
                          'name_pattern': PROFILE['exchange']['pull']['name_pattern'],
                          'max_bytes': guest.EXCHANGE_DELIVERY_MAX_BYTES})

    def test_a_large_body_travels_on_standard_input(self):
        """D1 work design G2: a command far above a command line's size (Windows caps one near 32767 characters)
        travels in the sealed probe's text, and the server receives it whole."""
        command = 'echo ' + 'x' * 200000
        self.server.stdout = 'done'
        answer = self.transport('POST', f'/api/conversations/{cc.CONVERSATION}/bash/execute_bash_command',
                                {'command': command, 'cwd': '/workspace', 'timeout': 60})
        self.assertEqual(answer, {'status': 200, 'body': {'command': command, 'exit_code': 0, 'stdout': 'done',
                                                          'stderr': ''}})
        self.assertEqual(self.server.seen[-1][3]['command'], command)
        self.assertLess(len(' '.join(self.ssh.runs[-1]['argv'])), 200)
        self.assertGreater(len(self.ssh.runs[-1]['script']), len(command))


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
                             read_artifact=self.read_artifact, catalog_sources=self.catalog.sources)
        self.assertEqual(self.store.get(result.operation_key).state, 'confirmed')
        self.assertEqual([(m, p, k == SYNTHETIC_KEY) for m, p, k, _ in server.seen],
                         [('GET', '/server_info', True), ('POST', '/api/conversations', True)])
        self.assertEqual(server.seen[1][3]['conversation_id'], result.conversation_id)
        self.assertNotIn(SYNTHETIC_KEY, json.dumps([live.calls, ssh.runs]))
        self.assertNotIn(SYNTHETIC_KEY, self.store.canonical_dump().decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
