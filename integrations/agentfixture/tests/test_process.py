"""The served fixture as a process (plan leaf E-01.7): it listens on 127.0.0.1 only (the kernel's tables, by the
process's own pid), loads no client and no dispatch module, has no outbound call site, and stops on its stop-request
file. And the fixture transport: it reaches only a labelled fixture on the literal loopback address.
"""
import ast
import http.server
import json
import threading
import unittest

import fixture_support as S

CATEGORY = 'integration'

SERVER, TRANSPORT = S.SERVER, S.TRANSPORT
CENSUS = S.load('aieh_inference_census_for_fixture', S.REPO / 'integrations' / 'inference' / 'inference_census.py')
# The harness's client modules and the third-party clients. The standard library's http.client is loaded by Starlette
# itself (starlette.exceptions, for the status phrases: measured with -X importtime), so the census of its use is the
# syntax-tree census below: no served source imports it or opens a connection.
CLIENT_MODULES = ('agentfixture_transport', 'fixture_transport', 'urllib.request', 'ftplib', 'smtplib', 'requests',
                  'httpx', 'websockets.sync.client', 'websockets.asyncio.client')
SERVED_SOURCES = ('server.py', 'core.py', 'result.py')


class Process(unittest.TestCase):
    category = 'integration'

    @classmethod
    def setUpClass(cls):
        cls.served = S.Served('finished').start()
        try:
            cls.answer = cls.served.transport(timeout=30)('GET', '/server_info')
            cls.record = cls.served.record()
            cls.rows = [row for row in CENSUS.read_tables() if row.pid == cls.record['pid']]
        finally:
            cls.served.stop()
        cls.exit = cls.served.process.returncode

    @classmethod
    def tearDownClass(cls):
        cls.served.close()

    def test_it_listens_on_127_0_0_1_only_and_on_nothing_else(self):
        self.assertEqual(self.answer['status'], 200)
        listening = [row for row in self.rows if row.protocol == 'udp' or row.state == 'LISTEN']
        self.assertEqual([(r.protocol, r.local_address, r.local_port) for r in listening],
                         [('tcp', '127.0.0.1', self.served.port)])
        self.assertNotIn(self.served.port, (13310, SERVER.PORT))

    def test_it_loads_no_client_and_no_dispatch_module(self):
        modules = set(self.record['modules'])
        self.assertFalse(modules & set(CLIENT_MODULES), sorted(modules & set(CLIENT_MODULES)))
        self.assertFalse({m for m in modules if m in ('dispatch_inputs', 'attempt_run', 'attempt_end',
                                                      'guest_transport', 'reconcile')})
        self.assertIn('agentfixture_core', modules)

    def test_it_stops_on_its_stop_request(self):
        self.assertEqual(self.exit, 0)


class Census(unittest.TestCase):
    """No outbound call site in the served sources (a syntax-tree census), and the guard the process arms."""
    category = 'unit'

    def test_the_served_sources_have_no_outbound_call_site(self):
        forbidden_calls = {'connect', 'connect_ex', 'create_connection', 'getaddrinfo', 'urlopen', 'HTTPConnection',
                           'HTTPSConnection'}
        for name in SERVED_SOURCES:
            tree = ast.parse((S.PACKAGE / name).read_text(encoding='utf-8'))
            with self.subTest(source=name):
                calls = {getattr(n.func, 'attr', getattr(n.func, 'id', None)) for n in ast.walk(tree)
                         if isinstance(n, ast.Call)}
                self.assertFalse(calls & forbidden_calls, sorted(calls & forbidden_calls))
                imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | \
                    {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
                self.assertFalse(imported & {'http.client', 'urllib.request', 'requests', 'httpx'}, imported)
                self.assertNotIn('transport.py', (S.PACKAGE / name).read_text(encoding='utf-8'))

    def test_the_armed_guard_refuses_a_connect_and_a_lookup(self):
        for event in ('socket.connect', 'socket.getaddrinfo'):
            with self.subTest(event=event):
                with self.assertRaises(SERVER.OutboundRefused):
                    SERVER.OutboundGuard._hook(event, ())
        SERVER.OutboundGuard._hook('socket.bind', ())


class _Unlabelled(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        data = json.dumps({'version': '1.60.1'}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class Transport(unittest.TestCase):
    category = 'integration'

    def test_an_answer_without_the_label_is_refused(self):
        server = http.server.HTTPServer(('127.0.0.1', 0), _Unlabelled)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with self.assertRaises(TRANSPORT.FixtureTransportError) as caught:
            TRANSPORT.FixtureTransport(server.server_address[1], timeout=30)('GET', '/server_info')
        self.assertEqual(caught.exception.code, 'FIXTURE_LABEL_MISSING')

    def test_a_delivery_or_the_ui_face_is_refused_before_anything_is_sent(self):
        transport = TRANSPORT.FixtureTransport(S.free_port(), timeout=30)
        for args, kwargs, code in ((('POST', '/api/conversations/x/bash/execute_bash_command', {}),
                                    {'deliver': {'part': 'bundle', 'name': 'x'}}, 'FIXTURE_DELIVERY_UNAVAILABLE'),
                                   (('GET', '/ui/server_info'), {}, 'FIXTURE_UI_FACE')):
            with self.subTest(code=code):
                with self.assertRaises(TRANSPORT.FixtureTransportError) as caught:
                    transport(*args, **kwargs)
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(transport.calls, [])

    def test_it_targets_the_literal_loopback_address_and_declares_fixture(self):
        self.assertEqual((TRANSPORT.LOOPBACK, TRANSPORT.FixtureTransport.authority), ('127.0.0.1', 'fixture'))
        source = (S.PACKAGE / 'transport.py').read_text(encoding='utf-8')
        self.assertEqual(source.count('HTTPConnection('), 1)
        self.assertIn('HTTPConnection(LOOPBACK, self.port', source)


if __name__ == '__main__':
    unittest.main()
