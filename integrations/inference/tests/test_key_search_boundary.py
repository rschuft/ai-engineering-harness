"""The provider-key containment search end to end at the broker's exposure boundary (S-03.2 slice 5), offline.

The broker runs under the qualification launcher (inference_qualification.py broker) with a synthetic key read
from a fixture standard input, in this process: one family on the qualification's own fake upstream, another on a
streaming fake upstream (broker_support.FakeUpstream), both on ephemeral 127.0.0.1 ports. The test plays the
conversation's job and the dispatcher: it issues tokens on the control listener, sends inference requests that
are forwarded, refused and revoked, and keeps every byte that crossed each listener in each direction (what the
SSH forward relays unchanged to and from a container is exactly what crosses the inference listener). The bytes
the broker sends to its upstreams are kept too: the one surface that must hold the key, a natural positive control
beside the planted ones.

The search then covers every surface where the key could reach something a container or guest can read: the
answers on the forward, the requests, the control answers (the token handed to the job), the broker's standard
output and error, the fake upstream's records, the store and the audit directory (every file, the store also row
by row), and this process's environment. Expected: not found on any of them, found on the upstream bytes, every
control valid. A planted leak (an upstream that reflects the key in base64, which the broker relays untranslated;
a copy written into the audit directory and into a database there) is found where it was planted.
"""
from __future__ import annotations

import base64
import binascii
import contextlib
import http.server
import io
import json
import secrets
import shutil
import socket
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import broker_support as S

CATEGORY = 'integration'
IB = S.IB
KS = S._load('aieh_inference_key_search', S.HERE.parent / 'inference_key_search.py')
IQ = S._load('aieh_inference_qualification', S.HERE.parent / 'inference_qualification.py')
PROVIDER_ID = 'qualification'
SMALL = 4096


class Stdin:
    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)

    def isatty(self):
        return False


def exchange(port: int, method: str, path: str, body=None, headers=()) -> tuple:
    """One request on a new connection (Connection: close); (request bytes, every byte answered)."""
    data = b'' if body is None else json.dumps(body).encode('utf-8')
    lines = [f'{method} {path} HTTP/1.1', f'Host: 127.0.0.1:{port}', 'Connection: close']
    lines += [f'{name}: {value}' for name, value in headers]
    if body is not None:
        lines += ['Content-Type: application/json', f'Content-Length: {len(data)}']
    request = ('\r\n'.join(lines) + '\r\n\r\n').encode('ascii') + data
    answer = bytearray()
    with socket.create_connection(('127.0.0.1', port), timeout=30) as connection:
        connection.sendall(request)
        while chunk := connection.recv(65536):
            answer += chunk
    return request, bytes(answer)


def status_of(answer: bytes) -> int:
    return int(answer.split(b' ', 2)[1])


def json_of(answer: bytes) -> dict:
    return json.loads(answer.partition(b'\r\n\r\n')[2])


class Reflecting(http.server.BaseHTTPRequestHandler):
    """An upstream that answers with the credential it received, base64-encoded: a planted leak."""
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get('content-length') or 0))
        echo = base64.b64encode((self.headers.get('x-api-key') or '').encode()).decode()
        data = json.dumps({'type': 'message', 'content': [{'type': 'text', 'text': echo}],
                           'usage': {'input_tokens': 1, 'output_tokens': 1}}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Boundary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-key-boundary-'))
        (self.tmp / 'logs').mkdir()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.key = KS.SYNTHETIC_PREFIX + secrets.token_urlsafe(48)[:48]
        self.fake_out = io.StringIO()
        self.fake = IQ.FakeUpstream(IB.load_declarations()['anthropic-messages'], '127.0.0.1', 0, self.fake_out)
        self.fake.start()
        self.addCleanup(self.fake.stop)
        self.stream = S.FakeUpstream('openai-chat')
        self.addCleanup(self.stream.close)
        self.forward, self.control, self.upstream = [], [], []

    def config(self, anthropic_origin: str) -> dict:
        return {'control_port': 0, 'inference_port': 0, 'families': {
            'anthropic-messages': {'provider': PROVIDER_ID, 'upstream': anthropic_origin, 'models': [S.MODEL_A]},
            'openai-chat': {'provider': PROVIDER_ID, 'upstream': self.stream.origin,
                            'models': [S.MODEL_A, 'syn-error']}}}

    def recording(self, origin, timeout):
        """connect_upstream, with every byte the broker sends upstream kept."""
        connection = self.real_connect(origin, timeout)
        send = connection.send

        def kept(data):
            self.upstream.append(bytes(data))
            return send(data)
        connection.send = kept
        return connection

    def run_broker(self, origin: str, job) -> IB.Context:
        """The launcher's broker over this test's fixture store and logs; JOB(control port, inference port) plays
        the dispatcher and the job while it serves."""
        def wait(broker):
            job(broker.listeners['control']['port'], broker.listeners['inference']['port'])
        ctx = IB.Context(component=lambda: self.config(origin), provider=None,
                         store=lambda: S.STORE.open_store(self.tmp / 'integration.sqlite'),
                         logs=lambda: self.tmp / 'logs', stdin=Stdin((self.key + '\n').encode()), out=io.StringIO(),
                         err=io.StringIO(), wait=wait, allow_ephemeral=True)
        self.real_connect = IB.connect_upstream
        with mock.patch.object(IB, 'connect_upstream', self.recording):
            self.assertEqual(IQ.main(['broker', '--provider', PROVIDER_ID], ctx), 0, ctx.err.getvalue())
        return ctx

    def call(self, port, method, path, body=None):
        request, answer = exchange(port, method, path, body)
        self.control.append((request, answer))
        return answer

    def infer(self, port, family, token, model=S.MODEL_A, path=None, header=None, **extra):
        headers = [] if token is None else [header or S.auth(family, token)]
        request, answer = exchange(port, 'POST', path or S.ROUTE[family],
                                   {'model': model, 'messages': [S.PROMPT_MARKER], **extra}, headers)
        self.forward.append((request, answer))
        return status_of(answer), answer

    def grant(self, port, family, models):
        answer = self.call(port, 'POST', '/v1/grants', {
            'conversation_id': S.new_id(), 'attempt_id': S.new_id(), 'family': family, 'models': models,
            'ttl_s': 600})
        self.assertEqual(status_of(answer), 201)
        return json_of(answer)

    def search(self, ctx, chunk=None) -> dict:
        search = KS.Search(self.key, chunk=chunk)
        search.http('forward: inference listener -> job (answers)', b''.join(a for _, a in self.forward))
        search.http('forward: job -> inference listener (requests)', b''.join(r for r, _ in self.forward))
        search.http('control listener answers (the token handed on)', b''.join(a for _, a in self.control))
        search.http('control listener requests', b''.join(r for r, _ in self.control))
        search.capture('broker standard output (its report)', ctx.out.getvalue().encode())
        search.capture('launcher and broker standard error', ctx.err.getvalue().encode())
        search.capture('fake upstream records', self.fake_out.getvalue().encode())
        search.tree('broker store and audit directory', self.tmp)
        search.environ('this process environment')
        search.http('broker -> upstreams (holds the key by design)', b''.join(self.upstream), expect='present')
        search.controls()
        return search.report()

    def test_the_key_is_on_no_surface_a_container_can_read(self):
        seen = {}

        def job(cport, iport):
            a = self.grant(cport, 'anthropic-messages', [S.MODEL_A])
            b = self.grant(cport, 'openai-chat', [S.MODEL_A, 'syn-error'])
            seen['statuses'] = [
                self.infer(iport, 'anthropic-messages', None)[0],
                self.infer(iport, 'anthropic-messages', a['token'])[0],
                self.infer(iport, 'anthropic-messages', a['token'], model=S.MODEL_B)[0],
                self.infer(iport, 'anthropic-messages', a['token'], path='/v1/other')[0],
                self.infer(iport, 'anthropic-messages', a['token'],
                           header=('Authorization', f'Bearer {a["token"]}'))[0],
                self.infer(iport, 'openai-chat', b['token'], stream=True)[0],
                self.infer(iport, 'openai-chat', b['token'], model='syn-error')[0]]
            revoked = self.call(cport, 'POST', '/v1/grants/revoke', {
                'token_fingerprint': a['token_fingerprint'], 'trigger': 'attempt end', 'revoker': 'the test'})
            self.assertEqual(status_of(revoked), 200)
            seen['statuses'].append(self.infer(iport, 'anthropic-messages', a['token'])[0])
            self.assertEqual(status_of(self.call(cport, 'GET', f'/v1/grants/{b["token_fingerprint"]}')), 200)
            self.assertEqual(status_of(self.call(cport, 'GET', '/v1/status')), 200)
            seen['tokens'] = (a['token'], b['token'])
        ctx = self.run_broker(f'http://127.0.0.1:{self.fake.port}', job)
        self.assertEqual(seen['statuses'], [401, 200, 403, 404, 401, 200, 500, 401])
        self.assertIn(b'text/event-stream', self.forward[5][1])
        self.assertIn(b'Transfer-Encoding: chunked', self.forward[5][1])
        self.assertIn(KS.fingerprint(self.key), ctx.err.getvalue())
        report = self.search(ctx)
        surfaces = {s['label']: s for s in report['surfaces']}
        self.assertEqual(report['verdict'], 'not-found', json.dumps(report, indent=1)[:4000])
        self.assertTrue(report['controls']['valid'])
        for label, surface in surfaces.items():
            with self.subTest(surface=label):
                self.assertTrue(surface['searched'] and surface['complete'], surface)
                self.assertGreater(surface['bytes_total'], 0)
                if surface['expect'] == 'absent':
                    self.assertEqual(surface['found'], 0)
        answers = surfaces['forward: inference listener -> job (answers)']
        self.assertEqual(answers['items'], 8)
        self.assertGreater(answers['bytes']['http-body'], 0)
        store = surfaces['broker store and audit directory']
        self.assertGreater(store['bytes']['sqlite'], 0)
        self.assertGreaterEqual(store['items'], 2)
        upstream = surfaces['broker -> upstreams (holds the key by design)']
        # one anthropic and two openai-chat requests, each with the key in its auth header, whole
        self.assertEqual((upstream['matches']['key/raw'], upstream['matches']['body/raw']), (3, 3))
        self.assertEqual(upstream['items'], 3)
        self.assertIn('not proof that the key is absent anywhere else', report['statement'])
        # the tokens, not the key, crossed to the job; the report holds neither the key nor any part of it
        self.assertIn(seen['tokens'][0].encode(), self.control[0][1])
        text = json.dumps(report)
        self.assertFalse(KS.Search(self.key).holds(text))
        for start in range(len(self.key) - 23):
            self.assertNotIn(self.key[start:start + 24], text)

    def test_a_planted_leak_is_found_where_it_was_planted(self):
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Reflecting)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def job(cport, iport):
            a = self.grant(cport, 'anthropic-messages', [S.MODEL_A])
            self.assertEqual(self.infer(iport, 'anthropic-messages', a['token'])[0], 200)
        ctx = self.run_broker(f'http://127.0.0.1:{server.server_address[1]}', job)
        (self.tmp / 'logs' / 'planted.log').write_bytes(b'key=' + binascii.hexlify(self.key.encode()).upper())
        planted = sqlite3.connect(self.tmp / 'planted.sqlite')
        with contextlib.closing(planted):
            planted.execute('CREATE TABLE t (v TEXT)')
            planted.execute('INSERT INTO t VALUES (?)', (json.dumps({'k': self.key}),))
            planted.commit()
        with contextlib.redirect_stdout(io.StringIO()) as printed, contextlib.redirect_stderr(io.StringIO()) as err:
            report = self.search(ctx, chunk=SMALL)
        self.assertEqual((printed.getvalue(), err.getvalue()), ('', ''))
        self.assertEqual(report['verdict'], 'found')
        surfaces = {s['label']: s for s in report['surfaces']}
        answers = surfaces['forward: inference listener -> job (answers)']
        self.assertEqual(answers['where'], ['forward: inference listener -> job (answers)',
                                            'forward: inference listener -> job (answers) message 1'])
        self.assertTrue(any(label.startswith('key/base64@') for label in answers['matches']), answers['matches'])
        tree = surfaces['broker store and audit directory']
        self.assertEqual(sorted(tree['where']), ['logs/planted.log', 'planted.sqlite'])
        self.assertIn('key/raw', tree['matches_by_view']['sqlite'])
        self.assertIn('key/HEX', tree['matches_by_view']['raw'])
        for label in ('broker standard output (its report)', 'launcher and broker standard error',
                      'fake upstream records', 'control listener answers (the token handed on)'):
            self.assertEqual(surfaces[label]['found'], 0)
        self.assertFalse(KS.Search(self.key).holds(json.dumps(report)))


if __name__ == '__main__':
    unittest.main()
