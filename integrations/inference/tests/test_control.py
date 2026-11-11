"""The dispatcher's side of the broker (inference_control.py, S-03.2 slice 3): the listener ports read through
the broker's own configuration loader, the forward target (the inference listener only; the control listener's
port is refused by name), the token fingerprint, and the control client against a real broker on ephemeral
127.0.0.1 ports (status, one grant's state, revocation, the broker's refusals passed on by code, an unreachable
or foreign port). Its only connection is to 127.0.0.1, read from the module's syntax tree.
"""
from __future__ import annotations

import ast
import http.server
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
