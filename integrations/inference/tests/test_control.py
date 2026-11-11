"""The dispatcher's side of the broker (inference_control.py, S-03.2 slice 3): the listener ports read through
the broker's own configuration loader, the forward target (the inference listener only; the control listener's
port is refused by name), the token fingerprint, and the control client against a real broker on ephemeral
127.0.0.1 ports (status, one grant's state, revocation, issuance, the broker's refusals passed on by code, an
unreachable or foreign port), and the issue command (S-03.2 slice 4: the token to a pipe only; a terminal, a file
or a device refused before anything is asked). Its only connection is to 127.0.0.1, read from the module's syntax
tree.
"""
from __future__ import annotations

import ast
import http.server
import io
import json
import os
import threading
import unittest
from unittest import mock

import broker_support as S

CATEGORY = 'integration'
IB = S.IB
IC = S._load('aieh_inference_control', S.HERE.parent / 'inference_control.py')
SOURCE = (S.HERE.parent / 'inference_control.py').read_text(encoding='utf-8')


class TestPortsAndTokens(unittest.TestCase):
    def test_dispatcher_ports_come_from_the_broker_loader(self):
        raw = {'control_port': 18431, 'inference_port': 18432}
        self.assertEqual(IC.dispatcher_ports(raw), {'control_port': 18431, 'inference_port': 18432})
        for bad, code in (({'control_port': 18431}, 'CONFIG_INCOMPLETE'), (None, 'CONFIG_INCOMPLETE'),
                          ({'control_port': 18431, 'inference_port': 18431}, 'CONFIG_PORT_INVALID'),
                          ({'control_port': 18431, 'inference_port': 18432, 'api_key': 'x'},
                           'CONFIG_SECRET_SHAPED_KEY')):
            with self.subTest(raw=bad):
                with self.assertRaises(IC.ControlError) as caught:
                    IC.dispatcher_ports(bad)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.broker_code, code != 'CONFIG_INCOMPLETE')

    def test_managed_component_is_the_config_entry(self):
        resolution = mock.Mock(components={'inference_broker': {'control_port': 18431}, 'other': {}})
        with mock.patch.object(IC.broker.paths, 'resolve', return_value=resolution) as resolve:
            self.assertEqual(IC.managed_component(), {'control_port': 18431})
        resolve.assert_called_once_with()
        resolution.components = {}
        with mock.patch.object(IC.broker.paths, 'resolve', return_value=resolution):
            self.assertIsNone(IC.managed_component())

    def test_forward_target_is_the_inference_listener_only(self):
        ports = {'control_port': 18431, 'inference_port': 18432}
        self.assertEqual(IC.forward_target(ports), 18432)
        self.assertEqual(IC.forward_target(ports, 18432), 18432)
        for port, code in ((18431, 'CONTROL_PORT_REFUSED'), (18433, 'FORWARD_PORT_REFUSED'),
                           (22, 'FORWARD_PORT_REFUSED')):
            with self.subTest(port=port):
                with self.assertRaises(IC.ControlError) as caught:
                    IC.forward_target(ports, port)
                self.assertEqual(caught.exception.code, code)
                self.assertIn('Remedy:', str(caught.exception))

    def test_token_fingerprint(self):
        token = IB.TOKEN_PREFIX + 'A' * 43
        self.assertEqual(IC.token_fingerprint(token), IB.contract.fingerprint(token))
        self.assertRegex(IC.token_fingerprint(token), r'^sha256:[0-9a-f]{16}$')
        for bad in (token + 'x', token[:-1], 'Bearer ' + token, None, S.KEY):
            with self.assertRaises(IC.ControlError) as caught:
                IC.token_fingerprint(bad)
            self.assertEqual(caught.exception.code, 'TOKEN_SHAPE_INVALID')
            self.assertNotIn(str(bad), str(caught.exception))

    def test_client_refuses_a_port_that_is_not_one(self):
        for port in (None, 0, 70000, True, '18431'):
            with self.assertRaises(IC.ControlError):
                IC.ControlClient(port)

    def test_the_only_connection_is_to_loopback(self):
        tree = ast.parse(SOURCE)
        calls = [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr in ('HTTPConnection', 'HTTPSConnection', 'create_connection', 'socket',
                                        'urlopen', 'getaddrinfo')]
        self.assertEqual(calls, ['http.client.HTTPConnection(LOOPBACK, self.port, timeout=self.timeout)'])
        self.assertEqual(IC.LOOPBACK, '127.0.0.1')
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, ('environ', 'getenv', 'getproxies'))


class TestControlClient(unittest.TestCase):
    """Against one real broker (ephemeral ports, a fixture store) for the class."""

    @classmethod
    def setUpClass(cls):
        cls.upstream = S.FakeUpstream('openai-chat')
        cls.rig = S.Rig(S.component({'openai-chat': cls.upstream.origin})).start()
        cls.client = IC.ControlClient(cls.rig.control)

    @classmethod
    def tearDownClass(cls):
        cls.rig.close()
        cls.upstream.close()

    def test_status_grant_and_revoke(self):
        status = self.client.status()
        self.assertEqual(status['listeners']['inference']['port'], self.rig.inference)
        issued = self.rig.issue()
        fingerprint = IC.token_fingerprint(issued['token'])
        self.assertEqual(fingerprint, issued['token_fingerprint'])
        grant = self.client.grant(fingerprint)
        self.assertEqual((grant['state'], grant['family'], grant['models']), ('live', 'openai-chat', [S.MODEL_A]))
        self.assertNotIn(issued['token'], repr(grant))
        revoked = self.client.revoke(fingerprint, 'attempt end', 'tools/guest.py (test)')
        self.assertEqual(revoked['state'], 'revoked')
        self.assertEqual(revoked['revocation']['trigger'], 'attempt end')
        with self.assertRaises(IC.ControlError) as caught:
            self.client.revoke(fingerprint, 'attempt end', 'tools/guest.py (test)')
        self.assertEqual((caught.exception.code, caught.exception.status, caught.exception.broker_code),
                         ('GRANT_ALREADY_REVOKED', 409, True))
        answer = S.request(self.rig.inference, 'POST', '/v1/chat/completions', {'model': S.MODEL_A},
                           [S.auth('openai-chat', issued['token'])])
        self.assertEqual(answer[0], 401)

    def live(self):
        return self.client.status()['grants']['live']

    def issue_argv(self, *extra, model=S.MODEL_A):
        return ['issue', '--conversation-id', S.new_id(), '--family', 'openai-chat', '--model', model,
                '--requests', '2', '--tokens', '100', '--ttl-s', '60', *extra]

    def ports(self):
        return {'control_port': self.rig.control, 'inference_port': self.rig.inference}

    def test_issue_returns_one_checked_grant(self):
        conversation, attempt = S.new_id(), S.new_id()
        grant = self.client.issue(conversation, attempt, 'openai-chat', [S.MODEL_A, S.MODEL_B], 3, 50, 60)
        self.assertEqual((grant['conversation_id'], grant['attempt_id'], grant['models'], grant['budget']),
                         (conversation, attempt, [S.MODEL_A, S.MODEL_B], {'requests': 3, 'tokens': 50}))
        self.assertEqual(IC.token_fingerprint(grant['token']), grant['token_fingerprint'])
        self.assertEqual(self.client.grant(grant['token_fingerprint'])['state'], 'live')
        with self.assertRaises(IC.ControlError) as caught:
            self.client.issue(conversation, attempt, 'openai-chat', [S.MODEL_A], 3, 50, 60)
        self.assertEqual(caught.exception.code, 'ATTEMPT_HAS_GRANT')
        token = IB.TOKEN_PREFIX + 'B' * 43
        good = {'token': token, 'token_fingerprint': IB.contract.fingerprint(token), 'attempt_id': attempt}
        for answer in ({**good, 'token': None}, {**good, 'token': token + 'x'}, {**good, 'token': S.KEY},
                       {**good, 'token_fingerprint': 'sha256:' + '0' * 16}, {**good, 'attempt_id': S.new_id()}):
            with self.subTest(answer=sorted(answer.items())[1:]):
                with mock.patch.object(IC.ControlClient, 'call', return_value=answer):
                    with self.assertRaises(IC.ControlError) as caught:
                        self.client.issue(conversation, attempt, 'openai-chat', [S.MODEL_A], 3, 50, 60)
                self.assertEqual(caught.exception.code, 'CONTROL_ANSWER_INVALID')
                self.assertNotIn(token, str(caught.exception))
        with mock.patch.object(IC.ControlClient, 'call', return_value=good) as call:
            self.assertIs(self.client.issue(conversation, attempt, 'openai-chat', (S.MODEL_A,), 3, 50, 60), good)
        call.assert_called_once_with('POST', '/v1/grants', {
            'conversation_id': conversation, 'attempt_id': attempt, 'family': 'openai-chat', 'models': [S.MODEL_A],
            'budget': {'requests': 3, 'tokens': 50}, 'ttl_s': 60})

    def test_the_issue_command_writes_the_token_to_a_pipe_only(self):
        read_end, write_end = os.pipe()
        reader = os.fdopen(read_end, 'rb')
        try:
            with os.fdopen(write_end, 'w', encoding='ascii', newline='\n') as out:
                err = io.StringIO()
                before = self.live()
                attempt = S.new_id()
                code = IC.main(self.issue_argv('--attempt-id', attempt),
                               IC.Context(component=self.ports, out=out, err=err))
            data = reader.read()
        finally:
            reader.close()
        self.assertEqual(code, 0, err.getvalue())
        token = data.decode('ascii')[:-1]
        self.assertEqual(data[-1:], b'\n')
        fingerprint = IC.token_fingerprint(token)
        self.assertEqual(self.live(), before + 1)
        self.assertNotIn(token, err.getvalue())
        (line,) = err.getvalue().splitlines()
        self.assertEqual(json.loads(line.partition('inference-control: issued: ')[2]),
                         {'attempt_id': attempt, 'token_fingerprint': fingerprint})
        answer = S.request(self.rig.inference, 'POST', '/v1/chat/completions', {'model': S.MODEL_A},
                           [S.auth('openai-chat', token)])
        self.assertEqual(answer[0], 200)
        self.client.revoke(fingerprint, 'attempt end', 'test')

    def test_the_issue_command_refuses_a_terminal_a_file_and_a_broker_refusal(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True

        def unread():
            raise AssertionError('the configuration was read before the output was checked')
        before = self.live()
        with open(os.devnull, 'w', encoding='ascii') as device:   # Windows' NUL is a character device: a tty
            for out, code in ((Terminal(), 'TOKEN_STDOUT_TERMINAL'), (io.StringIO(), 'TOKEN_STDOUT_NOT_PIPE'),
                              (device, 'TOKEN_STDOUT_TERMINAL' if device.isatty() else 'TOKEN_STDOUT_NOT_PIPE')):
                with self.subTest(code=code):
                    err = io.StringIO()
                    self.assertEqual(IC.main(self.issue_argv(), IC.Context(component=unread, out=out, err=err)), 2)
                    self.assertIn(code, err.getvalue())
                    if isinstance(out, io.StringIO):
                        self.assertEqual(out.getvalue(), '')
        self.assertEqual(self.live(), before)
        read_end, write_end = os.pipe()
        with os.fdopen(read_end, 'rb') as reader:
            with os.fdopen(write_end, 'w', encoding='ascii') as out:
                for argv, component, code in ((self.issue_argv(model=S.MODEL_C), self.ports, 'MODEL_NOT_ALLOWLISTED'),
                                              (self.issue_argv(), lambda: None, 'CONFIG_INCOMPLETE')):
                    with self.subTest(code=code):
                        err = io.StringIO()
                        self.assertEqual(IC.main(argv, IC.Context(component=component, out=out, err=err)), 2)
                        self.assertIn(code, err.getvalue())
            self.assertEqual(reader.read(), b'')
        self.assertEqual(self.live(), before)

    def test_refusals_carry_the_broker_code(self):
        with self.assertRaises(IC.ControlError) as caught:
            self.client.grant('sha256:' + '0' * 16)
        self.assertEqual((caught.exception.code, caught.exception.status), ('GRANT_UNKNOWN', 404))
        with self.assertRaises(IC.ControlError) as caught:
            self.client.revoke('sha256:' + '0' * 16, 'no such trigger', 'x')
        self.assertEqual(caught.exception.code, 'TRIGGER_UNKNOWN')
        with self.assertRaises(IC.ControlError) as caught:
            self.client.grant('../status')
        self.assertEqual(caught.exception.code, 'TOKEN_SHAPE_INVALID')

    def test_an_unreachable_or_foreign_port(self):
        # a refused connect, as the client sees it (a real one costs Windows about 2 s of SYN retries)
        def refused(*args, **kwargs):
            raise ConnectionRefusedError(10061, 'refused')
        with mock.patch.object(IC.http.client.HTTPConnection, 'connect', refused):
            with self.assertRaises(IC.ControlError) as caught:
                IC.ControlClient(18431, timeout=5).status()
        self.assertEqual(caught.exception.code, 'CONTROL_UNREACHABLE')
        self.assertNotIn('Traceback', str(caught.exception))

        answers = [(200, b'not json'), (500, b'{"detail": "x"}'), (200, b'[1]'),
                   (403, b'{"aieh_refusal": {"code": "NOT_A_CODE"}}')]

        class Foreign(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                status, body = answers.pop(0)
                self.send_response(status)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = http.server.HTTPServer(('127.0.0.1', 0), Foreign)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        try:
            client = IC.ControlClient(server.server_address[1], timeout=5)
            for _ in range(4):
                with self.assertRaises(IC.ControlError) as caught:
                    client.status()
                self.assertEqual(caught.exception.code, 'CONTROL_ANSWER_INVALID')
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
