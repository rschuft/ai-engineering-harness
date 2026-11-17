"""The Integration process's outbound guard (decision 0025 point 2; app.py ``OutboundGuard``): once ``serve``'s
lifespan has armed it, every ``socket.connect`` (``connect`` and ``connect_ex``) and ``socket.getaddrinfo`` in the
process is refused before the call, and the process keeps serving.

An audit hook cannot be removed, so this test never arms one in its own process: it starts a real server process
(serve_outbound_probe.py: ``app.serve`` on a free loopback port, never 127.0.0.1:13310, with its capture replaced by
a probe that tries to open a transport) and talks to it over HTTP. The probe aims at a listener this test holds, so
a connection the guard failed to refuse is seen here too. The process is stopped by its stop request.
"""
from __future__ import annotations

import json
import select
import shutil
import socket
import tempfile
import unittest
from pathlib import Path

import ownerhost_support as T
import test_pending_decision as PD

CATEGORY = 'integration'
A, CS, E = T.A, T.CS, PD.E
PROBE = Path(__file__).resolve().parent / 'serve_outbound_probe.py'
DIGEST = '0' * 64


class ArmedServerProcess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-ownerhost-outbound-'))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.state, cls.logs = cls.tmp / 'state' / 'owner-host', cls.tmp / 'logs' / 'owner-host'
        cls.state.mkdir(parents=True)
        cls.logs.mkdir(parents=True)
        cls.store = CS.open_store(cls.state / CS.DB_NAME)
        cls.addClassCleanup(cls.store.close)
        cls.credential, _ = E.enroll(cls.store, hours=1)
        cls.target = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cls.addClassCleanup(cls.target.close)
        cls.target.bind((A.LOOPBACK, 0))
        cls.target.listen(8)
        cls.port = PD.free_port()
        cls.server = PD.Server(cls.state, cls.logs, cls.port, child=PROBE, extra=[str(cls.target.getsockname()[1])])
        cls.obs = {}
        try:
            cls.obs['up'] = cls.server.start()
            browser = PD.Browser(cls.port, cls.credential)
            cls.obs['session_before'] = browser.request('POST', '/session')
            for probe in ('connect', 'connect-ex', 'getaddrinfo'):
                cls.obs[probe] = browser.request('POST', f'/threads/t/messages/{probe}/capture', {'sha256': DIGEST})
            cls.obs['session_after'] = browser.request('POST', '/session')
            cls.obs['threads_after'] = browser.request('GET', '/threads')
            cls.obs['target_reached'] = bool(select.select([cls.target], [], [], 0)[0])
        finally:
            cls.obs['stopped'] = cls.server.stop()
            cls.obs['service_log'] = (cls.logs / 'service.log').read_text(encoding='utf-8', errors='replace')

    def test_every_outbound_call_is_refused_before_it_is_made(self):
        for probe in ('connect', 'connect-ex', 'getaddrinfo'):
            with self.subTest(probe=probe):
                status, answer = self.obs[probe]
                self.assertEqual((status, (answer or {}).get('code')), (500, 'OUTBOUND_REFUSED'), answer)
        self.assertFalse(self.obs['target_reached'], 'a connection reached the target')

    def test_the_process_keeps_serving_its_ordinary_routes(self):
        self.assertEqual(self.obs['session_before'][0], 200)
        self.assertEqual(self.obs['session_after'][0], 200)
        self.assertEqual(self.obs['threads_after'], (200, {'threads': []}))
        self.assertEqual(self.obs['stopped'], 0)
        self.assertEqual(self.server.record()['state'], 'stopped')

    def test_the_guard_is_armed_by_the_lifespan_after_the_loop_exists(self):
        log = self.obs['service_log']
        self.assertEqual(log.count('outbound guard armed'), 1, 'the guard was not armed once')
        # serve logs "listening on" before uvicorn runs; the lifespan arms the guard inside the running loop
        self.assertTrue(log.index('listening on') < log.index('outbound guard armed'), 'armed before the loop')


class InThisProcess(unittest.TestCase):
    """The test process never arms the guard; the route's refusal is mapped without it."""

    def test_the_test_process_has_not_armed_the_guard(self):
        self.assertFalse(A.OUTBOUND_GUARD.armed)

    def test_an_outbound_refusal_is_answered_with_its_stable_code(self):
        class Refusing:
            def capture(self, *_args):
                raise A.OutboundRefused(13, 'socket.connect refused')
        scratch = T.Scratch(prefix='aieh-outbound-')
        self.addCleanup(scratch.close)
        credential, _ = scratch.enroll(at=T.utc(2026, 11, 16, 12, 0, 0))
        app = A.create_app(lambda: scratch.store, clock=lambda: T.stamp(T.utc(2026, 11, 16, 12, 0, 0)),
                           capturer=Refusing())
        status, _, body = T.call(app, 'POST', '/threads/t/messages/m/capture',
                                 (T.HOST, (T.S.HEADER, credential), ('content-type', 'application/json')),
                                 body=json.dumps({'sha256': DIGEST}).encode())
        self.assertEqual((status, T.code_of(body)), (500, 'OUTBOUND_REFUSED'))


if __name__ == '__main__':
    unittest.main()
