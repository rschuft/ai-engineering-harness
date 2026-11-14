"""The qualification-only commands (inference_qualification.py, S-03.2 slice 4), in this process only.

The launcher (`broker`): it refuses to start unless every configured family's upstream is plain http to a
loopback IP literal and one is keyed to its provider id; it reads the key from standard input only, refusing a
terminal and anything without the synthetic prefix; it runs the broker's own serve over the configuration it
read once, and the start receipt records the key's fingerprint with the source stdin-qualification, never the
key; serve has no flag for it, and the harness's credential factory never returns its provider. The fake
upstream (`fake-upstream`): loopback IPv4 only, a fixed answer the broker's usage extractor reads, records of
method, path, header names and credential fingerprints, never a header value or a body. Every key here is
synthetic, every listener is on an ephemeral 127.0.0.1 port of this process, and the store and logs are fixture
directories; nothing reads the managed root or a real credential provider.
"""
from __future__ import annotations

import ast
import contextlib
import http.client
import io
import json
import shutil
import socket
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import broker_support as S

CATEGORY = 'integration'
IB = S.IB
IC = S._load('aieh_inference_control', S.HERE.parent / 'inference_control.py')
IQ = S._load('aieh_inference_qualification', S.HERE.parent / 'inference_qualification.py')
CRED = IB.credentials
QUAL_SOURCE = (S.HERE.parent / 'inference_qualification.py').read_text(encoding='utf-8')
BROKER_SOURCE = (S.HERE.parent / 'inference_broker.py').read_text(encoding='utf-8')
PROVIDER_ID = 'qualification'
# A synthetic key of the launcher's shape, assembled at run time.
SYNTHETIC = IQ.SYNTHETIC_PREFIX + 'fixture-' + 'Qx7' * 6
HEADER_MARKER = 'SYNTHETIC-HEADER-VALUE-MARKER-5b2a'


class Stdin:
    """Standard input as a pipe (bytes), or a terminal; reads counted."""

    def __init__(self, data: bytes = b'', tty: bool = False):
        self._data, self.tty, self.reads = io.BytesIO(data), tty, 0

    def isatty(self):
        return self.tty

    @property
    def buffer(self):
        self.reads += 1
        return self._data


def refuse(*args, **kwargs):
    raise AssertionError('the launcher went past its refusal')


class Out(io.StringIO):
    """Standard output that counts its lines and flushes (a record must reach a pipe as it is written)."""

    def __init__(self):
        super().__init__()
        self.flushes = 0

    def flush(self):
        self.flushes += 1
        super().flush()


def config(**families) -> dict:
    """components.inference_broker on ephemeral ports: {family: (provider, upstream)}."""
    return {'control_port': 0, 'inference_port': 0, 'families': {
        family: {'provider': provider, 'upstream': upstream, 'models': [S.MODEL_A]}
        for family, (provider, upstream) in families.items()}}


def context(raw, stdin, **overrides):
    fields = dict(component=lambda: raw, provider=refuse, store=refuse, logs=refuse, stdin=stdin, out=io.StringIO(),
                  err=io.StringIO(), wait=refuse, allow_ephemeral=True)
    fields.update(overrides)
    return IB.Context(**fields)


class TestLauncherRefusals(unittest.TestCase):
    """Nothing is read, opened or started on a refusal: the key stays unread, and the store, the logs, the
    provider and the wait are never called."""

    def launch(self, raw, provider_id=PROVIDER_ID, stdin=None):
        stdin = stdin or Stdin(SYNTHETIC.encode())
        ctx = context(raw, stdin)
        code = IQ.main(['broker', '--provider', provider_id], ctx)
        return code, ctx, stdin

    def test_every_configured_upstream_is_plain_http_to_a_loopback_ip_literal(self):
        loop = 'http://127.0.0.1:9'
        for raw, code in (
                (config(**{'anthropic-messages': (PROVIDER_ID, loop),
                           'openai-chat': ('other', 'https://api.example.invalid')}),
                 'QUALIFICATION_UPSTREAM_REFUSED'),
                (config(**{'anthropic-messages': (PROVIDER_ID, 'https://127.0.0.1:9')}),
                 'QUALIFICATION_UPSTREAM_REFUSED'),
                (config(**{'anthropic-messages': (PROVIDER_ID, 'http://localhost:9')}), 'CONFIG_ORIGIN_INVALID'),
                (config(**{'anthropic-messages': (PROVIDER_ID, 'http://192.0.2.1:9')}), 'CONFIG_ORIGIN_INVALID'),
                (config(**{'anthropic-messages': ('other', loop)}), 'QUALIFICATION_NO_FAMILY'),
                (config(), 'QUALIFICATION_NO_FAMILY'),
                ({'control_port': 0, 'inference_port': 0, 'api_key': 'x'}, 'CONFIG_SECRET_SHAPED_KEY')):
            with self.subTest(code=code, raw=raw):
                status, ctx, stdin = self.launch(raw)
                self.assertEqual(status, 2, ctx.err.getvalue())
                self.assertIn(code, ctx.err.getvalue())
                self.assertEqual(stdin.reads, 0)
                self.assertEqual(ctx.out.getvalue(), '')

    def test_check_upstreams_accepts_loopback_literals_only(self):
        for upstream in ('http://127.0.0.1:9', 'http://127.0.0.2:9', 'http://[::1]:9'):
            with self.subTest(upstream=upstream):
                loaded = IB.load_config(config(**{'openai-chat': (PROVIDER_ID, upstream)}), allow_ephemeral=True)
                self.assertEqual(IQ.check_upstreams(loaded, PROVIDER_ID), ['openai-chat'])
        loaded = IB.load_config(config(**{'openai-chat': (PROVIDER_ID, 'https://127.0.0.1:9')}),
                                allow_ephemeral=True)
        with self.assertRaises(IQ.QualificationError) as caught:
            IQ.check_upstreams(loaded, PROVIDER_ID)
        self.assertEqual(caught.exception.code, 'QUALIFICATION_UPSTREAM_REFUSED')
        self.assertIn('Remedy:', str(caught.exception))

    def test_a_provider_id_that_is_not_one(self):
        status, ctx, stdin = self.launch(config(**{'openai-chat': (PROVIDER_ID, 'http://127.0.0.1:9')}), 'Not An Id')
        self.assertEqual(status, 2)
        self.assertIn('PROVIDER_ID_INVALID', ctx.err.getvalue())
        self.assertEqual(stdin.reads, 0)

    def test_the_key_is_a_synthetic_key_from_standard_input_only(self):
        raw = config(**{'openai-chat': (PROVIDER_ID, 'http://127.0.0.1:9')})
        body = IQ.SYNTHETIC_PREFIX
        for data, tty, code in ((SYNTHETIC.encode(), True, 'KEY_STDIN_TTY'),
                                (S.KEY.encode(), False, 'KEY_NOT_SYNTHETIC'),
                                (('x' + SYNTHETIC).encode(), False, 'KEY_NOT_SYNTHETIC'),
                                ((body + 'A' * 15).encode(), False, 'KEY_NOT_SYNTHETIC'),
                                ((body + 'A' * 129).encode(), False, 'KEY_NOT_SYNTHETIC'),
                                ((body + 'A' * 15 + '.').encode(), False, 'KEY_NOT_SYNTHETIC'),
                                ((body + 'A' * 8 + ' ' + 'A' * 8).encode(), False, 'KEY_INVALID'),
                                (b'', False, 'KEY_INVALID')):
            with self.subTest(code=code, data=data[:12]):
                status, ctx, _ = self.launch(raw, stdin=Stdin(data, tty))
                self.assertEqual(status, 2, ctx.err.getvalue())
                self.assertIn(code, ctx.err.getvalue())
                if data:
                    self.assertNotIn(data.decode().strip(), ctx.err.getvalue() + ctx.out.getvalue())
        for key in (body + 'A' * 16, body + 'a_-9' * 32):
            self.assertEqual(IQ.read_synthetic_key(Stdin((key + '\r\n').encode())), key)

    def test_its_provider_holds_the_key_in_memory_and_writes_nothing(self):
        provider = IQ.SyntheticKeyProvider(PROVIDER_ID, SYNTHETIC)
        self.assertEqual(provider.get(IB.ENTRY), (PROVIDER_ID, SYNTHETIC))
        self.assertIsNone(provider.get('another entry'))
        for call in (lambda: provider.set(IB.ENTRY, PROVIDER_ID, 'x'), lambda: provider.delete(IB.ENTRY)):
            with self.assertRaises(IQ.QualificationError) as caught:
                call()
            self.assertEqual(caught.exception.code, 'KEY_NEVER_WRITTEN')
        self.assertEqual(CRED.describe(provider)['provider'], 'stdin-qualification')
        self.assertEqual(IQ.KEY_SOURCE, 'stdin-qualification')


class TestCommandLine(unittest.TestCase):
    def test_required_options_and_the_managed_defaults(self):
        for argv in ([], ['broker'], ['fake-upstream', '--family', 'openai-chat'],
                     ['fake-upstream', '--port', '18433']):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    IQ.main(argv, context(None, Stdin()))
                self.assertEqual(caught.exception.code, 2)
        # without a context: the fake upstream admits no ephemeral port, and the launcher's managed context
        # failing to resolve is a refusal on standard error
        with mock.patch.object(IQ, '_FakeServer', refuse), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(IQ.main(['fake-upstream', '--family', 'openai-chat', '--port', '0']), 2)
        self.assertIn('FAKE_PORT_INVALID', err.getvalue())
        failing = IB.paths.PathsError('DEFAULT_ROOT_UNAVAILABLE', 'synthetic')
        with mock.patch.object(IB, 'managed_context', side_effect=failing), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(IQ.main(['broker', '--provider', PROVIDER_ID]), 2)
        self.assertIn('DEFAULT_ROOT_UNAVAILABLE', err.getvalue())


class TestSeparateCommand(unittest.TestCase):
    """Constraint 4: never a flag or variable on serve; the credential factory never returns the launcher's
    provider."""

    def test_serve_takes_no_flag_and_names_no_qualification(self):
        for argv in (['serve', '--provider', PROVIDER_ID], ['serve', '--synthetic-key'], ['serve', 'stdin'],
                     ['serve-qualification'], ['broker']):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    IB.main(argv, context(None, Stdin()))
                self.assertEqual(caught.exception.code, 2)
        tree = ast.parse(BROKER_SOURCE)
        serve = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_parser'
                 and node.args and getattr(node.args[0], 'value', None) == 'serve']
        self.assertEqual(len(serve), 1)
        statements = [node for node in ast.walk(tree) if isinstance(node, ast.Expr) and node.value is serve[0]]
        self.assertEqual(len(statements), 1, 'the serve subparser is bound to a name, so it could take a flag')
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertFalse(attributes & {'environ', 'getenv', 'environb'})
        for name in ('stdin-qualification', 'inference_qualification', 'SyntheticKeyProvider', 'aieh-qualification'):
            self.assertNotIn(name, BROKER_SOURCE)

    def test_the_credential_factory_never_returns_the_launchers_provider(self):
        class Backend:
            priority = 1

            def get_credential(self, service, username):
                return None
        base = type('KeyringBackend', (), {'get_credential': lambda self, service, username: None})
        modules = {'keyring.backend': types.SimpleNamespace(KeyringBackend=base),
                   'keyring.backends.SecretService': types.SimpleNamespace(Keyring=Backend),
                   'keyring.backends.macOS': types.SimpleNamespace(Keyring=Backend)}
        chosen = [CRED.select_provider('Windows', windows_store=object)]
        for system in ('Linux', 'Darwin'):
            chosen.append(CRED.select_provider(system, import_module=modules.__getitem__))
        self.assertEqual([type(p).__name__ for p in chosen],
                         ['WindowsCredentialProvider', 'KeyringProvider', 'KeyringProvider'])
        for provider in chosen:
            self.assertNotIsInstance(provider, IQ.SyntheticKeyProvider)
            self.assertNotEqual(CRED.describe(provider)['provider'], IQ.KEY_SOURCE)
        with self.assertRaises(CRED.LifecycleError) as caught:
            CRED.select_provider('Plan9')
        self.assertEqual(caught.exception.code, 'NO_CREDENTIAL_PROVIDER')
        factory = Path(CRED.__file__).read_text(encoding='utf-8')
        for name in ('stdin-qualification', 'inference_qualification', 'SyntheticKeyProvider', 'aieh-qualification'):
            self.assertNotIn(name, factory)
        # the broker's managed context takes its provider from the factory, and the launcher never calls it
        managed = next(node for node in ast.walk(ast.parse(BROKER_SOURCE))
                       if isinstance(node, ast.FunctionDef) and node.name == 'managed_context')
        providers = [ast.unparse(k.value) for node in ast.walk(managed) if isinstance(node, ast.Call)
                     for k in node.keywords if k.arg == 'provider']
        self.assertEqual(providers, ['credentials.select_provider'])
        names = {getattr(node, 'attr', getattr(node, 'id', None)) for node in ast.walk(ast.parse(QUAL_SOURCE))}
        self.assertNotIn('select_provider', names)

    def test_the_qualification_module_opens_no_outbound_connection(self):
        calls = [ast.unparse(node) for node in ast.walk(ast.parse(QUAL_SOURCE)) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr in ('HTTPConnection', 'HTTPSConnection', 'create_connection', 'connect',
                                        'urlopen', 'getaddrinfo', 'socket')]
        self.assertEqual(calls, [])


class TestLaunch(unittest.TestCase):
    """The launcher end to end: a fake upstream of this module, the broker's own serve, one issued token
    (ControlClient.issue), one request passed through with the synthetic key in place of the token."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-inference-qual-'))
        (self.tmp / 'logs').mkdir()
        self.fake_out = io.StringIO()
        family = IB.load_declarations()['anthropic-messages']
        self.fake = IQ.FakeUpstream(family, '127.0.0.1', 0, self.fake_out)
        self.fake.start()

    def tearDown(self):
        self.fake.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_synthetic_key_is_substituted_and_only_its_fingerprint_recorded(self):
        raw = config(**{'anthropic-messages': (PROVIDER_ID, f'http://127.0.0.1:{self.fake.port}')})
        reads, seen = [], {}

        def component():
            reads.append(True)
            return raw if len(reads) == 1 else config(**{'anthropic-messages': (PROVIDER_ID, 'https://a.invalid')})

        def wait(broker):
            seen['status'] = broker.status()
            client = IC.ControlClient(broker.listeners['control']['port'])
            seen['grant'] = client.issue(S.new_id(), S.new_id(), 'anthropic-messages', [S.MODEL_A], 60)
            seen['answer'] = S.request(broker.listeners['inference']['port'], 'POST', '/v1/messages',
                                       {'model': S.MODEL_A, 'messages': [S.PROMPT_MARKER]},
                                       [('x-api-key', seen['grant']['token'])])
        stdin = Stdin((SYNTHETIC + '\n').encode())
        ctx = context(None, stdin, component=component, store=lambda: S.STORE.open_store(self.tmp / 'i.sqlite'),
                      logs=lambda: self.tmp / 'logs', wait=wait)
        self.assertEqual(IQ.main(['broker', '--provider', PROVIDER_ID], ctx), 0, ctx.err.getvalue())
        self.assertEqual(len(reads), 1, 'the configuration was read more than once')
        fingerprint, token = IB.contract.fingerprint(SYNTHETIC), seen['grant']['token']
        status, _, body = seen['answer']
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['content'][0]['text'], IQ.FAKE_TEXT)
        self.assertEqual(seen['status']['provider_key'], {'provider': PROVIDER_ID, 'fingerprint': fingerprint,
                                                          'source': 'stdin-qualification'})
        records = [json.loads(line) for line in self.fake_out.getvalue().splitlines()]
        (request,) = [r for r in records if r['event'] == 'request']
        self.assertEqual((request['method'], request['path'], request['status']), ('POST', '/v1/messages', 200))
        self.assertEqual(request['credential_fingerprints'], [fingerprint])
        self.assertNotEqual(fingerprint, seen['grant']['token_fingerprint'])
        self.assertIn('x-api-key', request['header_names'])
        self.assertIn('substitution shown with a synthetic key', ctx.err.getvalue())
        self.assertIn(fingerprint, ctx.err.getvalue())
        report = json.loads(ctx.out.getvalue())
        self.assertEqual(report['grants']['live'], 1)
        (audit,) = (self.tmp / 'logs').glob('audit-*.jsonl')
        everything = (ctx.out.getvalue() + ctx.err.getvalue() + self.fake_out.getvalue()
                      + audit.read_text(encoding='utf-8'))
        for secret in (SYNTHETIC, token, S.PROMPT_MARKER):
            self.assertNotIn(secret, everything)
        store = S.STORE.open_store(self.tmp / 'i.sqlite')
        try:
            (start,) = [a for a in store.attempts() if a.operation_key.startswith('inference/broker-start/')]
            intent = json.loads(start.intent_json)
            self.assertEqual(intent['format'], 'aieh-inference-broker-start/1')
            self.assertEqual(intent['provider_key'], {'entry': 'AIEH model provider', 'provider': PROVIDER_ID,
                                                      'fingerprint': fingerprint, 'source': 'stdin-qualification'})
            self.assertNotIn(SYNTHETIC, store.canonical_dump().decode('utf-8', 'replace'))
        finally:
            store.close()


class TestFakeUpstream(unittest.TestCase):
    def run_fake(self, argv, wait=refuse, allow_ephemeral=True):
        ctx = types.SimpleNamespace(out=Out(), err=io.StringIO(), wait=wait, allow_ephemeral=allow_ephemeral)
        return IQ.main(['fake-upstream', *argv], ctx), ctx

    def test_refusals_come_before_any_bind(self):
        with mock.patch.object(IQ, '_FakeServer', refuse):
            for argv, code in ((['--family', 'no-such-family', '--port', '18433'], 'FAKE_FAMILY_UNKNOWN'),
                               (['--family', 'openai-chat', '--port', '18433', '--address', '0.0.0.0'],
                                'FAKE_ADDRESS_REFUSED'),
                               (['--family', 'openai-chat', '--port', '18433', '--address', '192.0.2.1'],
                                'FAKE_ADDRESS_REFUSED'),
                               (['--family', 'openai-chat', '--port', '18433', '--address', 'localhost'],
                                'FAKE_ADDRESS_REFUSED'),
                               (['--family', 'openai-chat', '--port', '18433', '--address', '::1'],
                                'FAKE_ADDRESS_REFUSED'),
                               (['--family', 'openai-chat', '--port', '18433', '--address', '127.0.0.1 '],
                                'FAKE_ADDRESS_REFUSED'),
                               (['--family', 'openai-chat', '--port', '80'], 'FAKE_PORT_INVALID'),
                               (['--family', 'openai-chat', '--port', '70000'], 'FAKE_PORT_INVALID')):
                with self.subTest(argv=argv):
                    status, ctx = self.run_fake(argv)
                    self.assertEqual(status, 2, ctx.err.getvalue())
                    self.assertIn(code, ctx.err.getvalue())
                    self.assertEqual(ctx.out.getvalue(), '')
            status, ctx = self.run_fake(['--family', 'openai-chat', '--port', '0'], allow_ephemeral=False)
            self.assertIn('FAKE_PORT_INVALID', ctx.err.getvalue())
        self.assertEqual(IQ.fake_address('127.0.0.1'), '127.0.0.1')
        self.assertEqual(IQ.fake_address('127.1.2.3'), '127.1.2.3')

    def test_each_answer_is_well_formed_and_read_by_the_usage_extractor(self):
        for family in IB.load_declarations().values():
            with self.subTest(family=family.id):
                answer = IQ.fake_answer(family)
                self.assertIn(IQ.FAKE_TEXT, json.dumps(answer))
                reader = IB.UsageReader(family.usage, 'application/json')
                reader.feed(json.dumps(answer).encode())
                self.assertEqual(reader.finish(), {'input': 1, 'output': 1, 'total': 2})

    def test_records_names_and_fingerprints_never_values_or_bodies(self):
        answers, ports = [], []

        def wait(fake):
            port, route = fake.port, '/v1/chat/completions'
            ports.append(port)
            bearer = [('Authorization', f'Bearer {SYNTHETIC}'), ('X-Synthetic-Marker', HEADER_MARKER)]
            answers.append(S.request(port, 'POST', route, {'model': S.MODEL_A, 'prompt': S.PROMPT_MARKER}, bearer))
            answers.append(S.request(port, 'POST', '/v1/other', {'model': S.MODEL_A}, bearer))
            answers.append(S.request(port, 'GET', route))
            answers.append(S.request(port, 'HEAD', route))
            answers.append(S.request(port, 'POST', route + '?x=1', {'model': S.MODEL_A}))
            answers.append(S.request(port, 'POST', route, None, [('Transfer-Encoding', 'chunked')]))
            answers.append(S.request(port, 'POST', route, None, [('Content-Length', 'many')]))
            answers.append(S.request(port, 'POST', route, {}, [('Authorization', SYNTHETIC),
                                                               ('Authorization', 'Bearer other')]))
        status, ctx = self.run_fake(['--family', 'openai-chat', '--port', '0'], wait)
        self.assertEqual(status, 0, ctx.err.getvalue())
        self.assertEqual([a[0] for a in answers], [200, 404, 404, 404, 404, 411, 411, 200])
        self.assertEqual({a[1]['content-type'] for a in answers}, {'application/json'})
        self.assertEqual([a[1].get('connection') for a in answers],
                         [None, None, None, None, None, 'close', 'close', None])
        self.assertIn(f'serving openai-chat on 127.0.0.1:{ports[0]} until interrupted', ctx.err.getvalue())
        self.assertGreaterEqual(ctx.out.flushes, 10)
        # stopped when the wait returned: the port is free again
        IQ.FakeUpstream(IB.load_declarations()['openai-chat'], '127.0.0.1', ports[0], io.StringIO()).stop()
        self.assertEqual(json.loads(answers[0][2])['usage'], {'prompt_tokens': 1, 'completion_tokens': 1,
                                                              'total_tokens': 2})
        records = [json.loads(line) for line in ctx.out.getvalue().splitlines()]
        self.assertEqual([r['event'] for r in records], ['start'] + ['request'] * 8 + ['stop'])
        self.assertEqual({r['format'] for r in records}, {'aieh-inference-fake-upstream/1'})
        self.assertEqual((records[0]['address'], records[0]['routes']),
                         ('127.0.0.1', [{'method': 'POST', 'path': '/v1/chat/completions'}]))
        self.assertEqual(records[-1]['requests'], 8)
        requests = records[1:-1]
        self.assertEqual([(r['method'], r['path'], r['status']) for r in requests],
                         [('POST', '/v1/chat/completions', 200), ('POST', None, 404), ('GET', None, 404),
                          ('HEAD', None, 404),
                          ('POST', None, 404), ('POST', '/v1/chat/completions', 411),
                          ('POST', '/v1/chat/completions', 411), ('POST', '/v1/chat/completions', 200)])
        fingerprint = IB.contract.fingerprint(SYNTHETIC)
        self.assertEqual(requests[0]['credential_fingerprints'], [fingerprint])
        self.assertEqual(requests[2]['credential_fingerprints'], [])
        self.assertEqual(requests[7]['credential_fingerprints'],[fingerprint, IB.contract.fingerprint('other')])
        self.assertIn('x-synthetic-marker', requests[0]['header_names'])
        self.assertIn('authorization', requests[0]['header_names'])
        for value in (SYNTHETIC, HEADER_MARKER, S.PROMPT_MARKER, S.MODEL_A, 'x=1'):
            self.assertNotIn(value, ctx.out.getvalue() + ctx.err.getvalue())

    def test_its_port_is_exclusive_and_freed_at_stop(self):
        family = IB.load_declarations()['openai-chat']
        holder = IQ.FakeUpstream(family, '127.0.0.1', 0, io.StringIO())
        try:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                self.assertEqual(holder.server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE), 1)
            status, ctx = self.run_fake(['--family', 'openai-chat', '--port', str(holder.port)])
        finally:
            holder.stop()
        self.assertEqual(status, 1)
        self.assertIn('FAILED: ', ctx.err.getvalue())
        IQ.FakeUpstream(family, '127.0.0.1', holder.port, io.StringIO()).stop()

    def test_bodies_are_drained_on_a_kept_alive_connection_and_handler_errors_recorded(self):
        family = IB.load_declarations()['anthropic-messages']
        out = Out()
        fake = IQ.FakeUpstream(family, '127.0.0.1', 0, out)
        fake.start()
        try:
            connection = http.client.HTTPConnection('127.0.0.1', fake.port, timeout=30)
            try:
                for body in (b'{"pad": "' + b'x' * 200_000 + b'"}', b'{}', b'{}'):
                    connection.request('POST', '/v1/messages' if body == b'{}' else '/v1/other', body)
                    response = connection.getresponse()
                    response.read()
                    self.assertEqual(response.status, 200 if body == b'{}' else 404)
            finally:
                connection.close()
            with mock.patch.object(IQ, 'credential_fingerprints', side_effect=RuntimeError('synthetic')):
                with self.assertRaises((OSError, http.client.HTTPException)):
                    S.request(fake.port, 'POST', '/v1/messages', {})
        finally:
            fake.stop()
        records = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([r['event'] for r in records], ['request'] * 3 + ['handler-error'])
        self.assertEqual(records[-1]['error'], 'RuntimeError')
        self.assertEqual(fake.requests, 3)


if __name__ == '__main__':
    unittest.main()
