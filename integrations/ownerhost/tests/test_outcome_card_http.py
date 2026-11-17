"""The outcome card end to end over HTTP (plan leaf U-04.2): the Integration process's application, in this process
as ``test_projection.Route``'s is, serves the real projection of a published fixture attempt on a free loopback port
(never 13310, 13320 or 13330), and the Owner host's card renders it from that port: the shell's own card and
Integration client (``apps/owner-host/src/areas/outcome-card.http.test.mjs``, run by the Owner host's pinned Vitest
under Node.js), its one request a GET with the session header and the shell's Origin, through every guard.

The card is rendered, torn down and rendered again (a reload): both renders show the same outcome, each from its own
read of the projection, and the application decided exactly those two GETs and nothing else.

It runs when Node.js is on PATH and the Owner host's dependencies are installed (``apps/owner-host/node_modules``, by
``npm ci`` there); otherwise it is skipped with that reason. No browser is used, and nothing leaves loopback: the
card's fetch is a loopback ``node:http`` request to the port chosen here.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import socket
import subprocess
import threading
import unittest
from pathlib import Path

import outcome_card_fixtures as F

CATEGORY = 'integration'
TP, A, S = F.TP, F.A, F.S
APP = F.REPO / 'apps' / 'owner-host'
VITEST = APP / 'node_modules' / 'vitest' / 'vitest.mjs'
CARD_TEST = 'src/areas/outcome-card.http.test.mjs'
NODE = shutil.which('node')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
RESERVED_PORTS = (13310, 13320, 13330)
CEILING_S = 300          # bounds a hang of the Vitest run; it normally ends within seconds
STOP_CEILING_S = 15


def free_port() -> int:
    """A free loopback port, never one of the harness's declared ones."""
    while True:
        probe = socket.socket()
        try:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        finally:
            probe.close()
        if port not in RESERVED_PORTS:
            return port


class InThread:
    """The application BUILD(port, lifespan) makes, served by uvicorn on a free loopback port in a thread of this process
    (the outcome projection's backlog patches stay in force); ``start`` returns once the lifespan has started (its own
    signal), and the lifespan's end calls AT_EXIT in the server's thread."""

    def __init__(self, build, at_exit=lambda: None):
        self.build, self.at_exit, self.server, self.thread, self.port = build, at_exit, None, None, None

    def start(self) -> 'InThread':
        import uvicorn
        started = threading.Event()

        @contextlib.asynccontextmanager
        async def lifespan(_app):
            started.set()
            yield
            self.at_exit()
        self.port = free_port()
        listener = A.bind_listener(self.port)
        app = self.build(self.port, lifespan)
        config = uvicorn.Config(app, log_config=None, access_log=False, server_header=False, date_header=False,
                                ws='none', http='h11', loop='asyncio', lifespan='on', timeout_graceful_shutdown=2)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=lambda: asyncio.run(self.server.serve(sockets=[listener])), daemon=True)
        self.thread.start()
        if not started.wait(STOP_CEILING_S):
            raise RuntimeError('the in-thread Integration process did not start')
        return self

    def stop(self):
        if self.server is not None:
            self.server.should_exit = True
            self.thread.join(STOP_CEILING_S)


@unittest.skipIf(TP.tar.BASH is None, 'no Git Bash (Windows) or bash: RESULT runs the harness\'s script')
@unittest.skipUnless(NODE and VITEST.is_file(), 'Node.js on PATH and apps/owner-host/node_modules (npm ci there) are '
                                                'needed to render the Owner host\'s card')
class CardOverHttp(F.Exporter):

    def test_the_card_renders_the_served_projection_of_a_published_fixture_attempt_and_again_after_a_reload(self):
        sources = F.sources_for(self)
        result, _, published, _ = self.go()
        self.assertEqual(getattr(published, 'outcome', published), 'confirmed')
        served, held = {}, {}

        def sessions():
            # the conversation store's connection belongs to the thread that opened it: the server's own
            if 'store' not in held:
                held['store'] = F.T.CS.open_store(served['app'].session.dir / F.T.CS.DB_NAME)
            return held['store']

        def build(port, lifespan):
            served['app'] = F.Served(self, sources, port=port, lifespan=lifespan, sessions=sessions)
            return served['app'].app
        server = InThread(build, at_exit=lambda: held.pop('store').close() if 'store' in held else None)
        report = self.scratch / 'card-report.json'
        with F.backlog_of(sources):
            server.start()
            try:
                self.assertNotIn(server.port, RESERVED_PORTS)
                app = served['app']
                given = {'port': server.port, 'credential': app.credential, 'outcome': F.OUTCOME_ID,
                         'report': str(report), 'commit': published.receipt['commit']}
                env = dict(os.environ, AIEH_OUTCOME_CARD_HTTP=json.dumps(given))
                # without Vitest's caches: nothing is written under node_modules (as owner-host:test:if-node)
                argv = [NODE, str(VITEST), 'run', CARD_TEST, '--no-color', '--no-cache', '--no-fsModuleCache']
                ran = subprocess.run(argv, cwd=APP, env=env, capture_output=True, timeout=CEILING_S,
                                     creationflags=NO_WINDOW)
            finally:
                server.stop()
        output = (ran.stdout + ran.stderr).decode('utf-8', 'replace')
        self.assertEqual(ran.returncode, 0, '\n'.join([output[-3000:], *app.requests]))
        self.assertIn('1 passed', output)
        card = json.loads(report.read_text(encoding='utf-8'))
        # the application decided two requests, each the card's GET with its session, and nothing else
        route = f'/outcomes/{F.OUTCOME_ID}'
        self.assertEqual(len(app.requests), 2, app.requests)
        for line in app.requests:
            self.assertTrue(line.startswith('accepted GET /outcomes/{outcome_id} 200 session='), line)
        self.assertEqual([(r['method'], r['path'], r['session']) for r in card['requests']],
                         [('GET', route, True)] * 2)
        # both renders the same card, from the published attempt's projection
        self.assertEqual(card['first'], card['second'])
        self.assertEqual((card['state'], card['status'], card['code'], card['authority']),
                         ('shown', 'succeeded', 'RESULT_PUBLISHED', 'fixture'))
        self.assertTrue(card['fixtureLabel'] and card['attemptFixtureLabel'])
        self.assertIn(published.receipt['commit'], card['observed'])
        self.assertIn('ARCHIVED_TASKS_NOT_ENUMERABLE', card['coverage'])
        self.assertIn(F.P.FIXTURE_AUTHORITY, card['uncertainties'])
        # what the card shows is what the projection answers
        projection = sources.project(self)
        [attempt] = projection['attempts']
        self.assertEqual(attempt['operationKey'], result.operation_key)
        self.assertEqual(card['uncertainties'], [u['code'] for u in projection['lineageUncertainties']])


if __name__ == '__main__':
    unittest.main()
