"""Shared support of the served fixture's conformance tests (plan leaf E-01.7): loading by path, the served process
started on a free loopback port and stopped by its stop-request file, a D1-shaped project repository built in
process, and the locked release document when its path is given. Not a test module.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
REPO = PACKAGE.parents[1]
DISPATCH_TESTS = REPO / 'integrations' / 'dispatch' / 'tests'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
STOP_CEILING_S = 60        # a ceiling on the served process's stop, not an expected duration
LOCKED_DOCUMENT_SHA256 = '3de49fac4670eff9c8b6635ffd8bc5b6d4219788877747135333cec9f8c5e0d0'
CID = '055b27f3-903e-5eb9-8758-197c1029ade7'         # D1's conversation id (D1 run record section 2)


def load(name: str, path: Path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


AC = load('agentfixture_core', PACKAGE / 'core.py')
SERVER = load('agentfixture_server', PACKAGE / 'server.py')
TRANSPORT = load('agentfixture_transport', PACKAGE / 'transport.py')
RESULT = load('aieh_agentfixture_result', PACKAGE / 'result.py')
CATALOG = AC.load_catalog()
SERVED = CATALOG['served']


def locked_openapi_path() -> Path | None:
    """The locked release openapi.json, when AIEH_LOCKED_OPENAPI names it (never committed: decision 0005); its sha256
    must be the lock's, else the run is refused (ValueError), never quietly skipped."""
    named = os.environ.get('AIEH_LOCKED_OPENAPI')
    if not named:
        return None
    data = Path(named).read_bytes()
    if hashlib.sha256(data).hexdigest() != LOCKED_DOCUMENT_SHA256:
        raise ValueError(f'{named} is not the locked openapi.json')
    return Path(named)


def free_port() -> int:
    probe = socket.socket()
    try:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


class Served:
    """The served fixture as a process of its own (``server.py serve``) on a free loopback port, never 13310 or the
    declared 13320: started by ``start``, stopped by its stop-request file (``stop``); its call log and server
    record in a throwaway directory."""

    def __init__(self, scenario: str = 'finished', *, openapi: Path | None = None):
        self.scenario, self.openapi = scenario, openapi
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-fx-'))
        self.state, self.log, self.scratch = self.tmp / 'state', self.tmp / 'calls.jsonl', self.tmp / 'scratch'
        self.port = None
        self.process = None

    def start(self) -> 'Served':
        for _ in range(5):
            self.port = free_port()
            if self.port in (13310, SERVER.PORT):
                continue
            argv = [sys.executable, '-I', '-B', str(PACKAGE / 'server.py'), 'serve', '--port', str(self.port),
                    '--scenario', self.scenario, '--log', str(self.log), '--state-dir', str(self.state),
                    '--scratch', str(self.scratch)]
            if self.openapi is not None:
                argv += ['--openapi', str(self.openapi)]
            self.process = subprocess.Popen(argv, cwd=REPO, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
            # the server prints one line once its listener is bound (its own signal; EOF if it exits first)
            line = self.process.stdout.readline().decode('ascii', 'replace')
            if line.startswith('listening '):
                return self
            self.stop()
        raise RuntimeError('the served fixture did not start')

    def record(self) -> dict:
        return json.loads((self.state / 'server.json').read_text(encoding='utf-8'))

    def calls(self) -> list[dict]:
        if not self.log.is_file():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines() if line]

    def transport(self, **kwargs):
        return TRANSPORT.FixtureTransport(self.port, **kwargs)

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.state.mkdir(parents=True, exist_ok=True)
            (self.state / 'stop-request').write_text('', encoding='utf-8')
            try:
                self.process.wait(STOP_CEILING_S)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(STOP_CEILING_S)
        if self.process is not None and self.process.stdout is not None:
            self.process.stdout.close()

    def close(self) -> None:
        self.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


def d1_create(cid: str = CID) -> dict:
    """The D1 stage's create template with CID (the profile's pinned d1-create.json; secrets as the dispatcher adds
    them are not needed by the fixture, which never serves them)."""
    body = json.loads((REPO / 'profiles' / 'strong-windows-qemu-whpx' / 'agent-server' / 'd1-create.json')
                      .read_text(encoding='utf-8'))
    body['conversation_id'] = cid
    return body


MESSAGE = {'role': 'user', 'content': [{'type': 'text', 'text': 'Implement the change as designed.'}], 'run': True}


class InThread:
    """The served application on a free loopback port, in a thread of the test process (no outbound guard: an audit
    hook cannot be removed, so only the served process arms it), so that a test can hold the Fixture and its core.
    ``start`` returns once uvicorn's lifespan has started (its own signal), ``stop`` asks it to exit and joins it."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.port = None
        self.server = None
        self.thread = None

    def start(self) -> 'InThread':
        import asyncio
        import contextlib
        import threading
        import uvicorn
        started = threading.Event()

        @contextlib.asynccontextmanager
        async def lifespan():
            started.set()
            yield
        listener = SERVER.bind_listener(free_port())
        self.port = listener.getsockname()[1]
        config = uvicorn.Config(SERVER.create_app(self.fixture, lifespan=lifespan), log_config=None, access_log=False,
                                server_header=False, date_header=False, ws='websockets-sansio', http='h11',
                                loop='asyncio', lifespan='on', timeout_graceful_shutdown=2)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=lambda: asyncio.run(self.server.serve(sockets=[listener])), daemon=True)
        self.thread.start()
        if not started.wait(STOP_CEILING_S):
            raise RuntimeError('the in-thread fixture did not start')
        return self

    def transport(self, **kwargs):
        return TRANSPORT.FixtureTransport(self.port, **kwargs)

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
            self.thread.join(STOP_CEILING_S)


def http(port: int, method: str, path: str, *, key: str | None = None, body=None, headers: dict | None = None,
         timeout: float = 30) -> dict:
    """One raw HTTP request to the listener (the UI face's client in tests): {status, headers, label, body}."""
    import http.client
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    sent = dict(headers or {})
    if key is not None:
        sent['X-Session-API-Key'] = key
    data = None if body is None else json.dumps(body).encode('utf-8')
    if data is not None:
        sent['Content-Type'] = 'application/json'
    try:
        connection.request(method, path, body=data, headers=sent)
        response = connection.getresponse()
        raw = response.read()
        label = response.getheader('X-AIEH-Fixture')
        return {'status': response.status, 'headers': {k.lower(): v for k, v in response.getheaders()},
                'label': json.loads(label) if label else None,
                'body': json.loads(raw.decode('utf-8')) if raw else None}
    finally:
        connection.close()


UI_ACCESS = SERVER.UI_ACCESS
DISPATCHER_ACCESS = SERVER.DISPATCHER_ACCESS
