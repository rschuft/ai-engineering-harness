"""The Integration process: the Owner UI's backend on the host (plan leaf U-01.3; decision 0025).

A Starlette application on uvicorn, run under the tools interpreter, bound to ``127.0.0.1:13310`` only (one fixed
port, declared in the network matrix's ``nm-owner-ui-integration`` and read by the host census; a busy port is a
refusal, never another port). service.py starts it inside the platform contract's supervision (decision 0011);
``serve`` is what runs in that process.

Every request passes three checks, outermost first, and a refusal changes nothing:

1. **Host and Origin, against literals.** ``Host`` must be exactly ``127.0.0.1:13310`` (``HOST_NOT_ALLOWED``, 400:
   DNS rebinding); ``Origin``, when present, must be one of the shell's two origins, ``http://127.0.0.1:4173`` and
   ``http://127.0.0.1:5173`` (``ORIGIN_NOT_ALLOWED``, 403).
2. **CORS** (Starlette's CORSMiddleware): only those origins, never credentials mode, only the session header and
   ``Content-Type``. It answers the CORS preflight itself, which a browser cannot authenticate: the preflight is the
   one request answered without the credential, and it carries no data.
3. **The Owner UI session credential** (session.py): the ``X-AIEH-Owner-Session`` header on every request, never a
   cookie; ``SESSION_CREDENTIAL_MISSING``, ``_FOREIGN``, ``_EXPIRED`` or ``_REVOKED`` (401) otherwise. An unknown
   path or method is refused here too before routing, so nothing is told without the credential.

Routes (all behind the credential): ``POST /session`` answers the authenticated session's public id, issue time and
expiry (the login's one verified request). The process keeps no session table of its own: the conversation store's
verifier is all it reads, so a restart loses nothing.

What it never does (decision 0025 point 2): it opens no outbound connection (its one socket is the listener that
``bind_listener`` binds); it imports no credential, Gitea, authorization-recorder or dispatch-transport module; it
reads no credential and no ``config.yml``; it has no dispatch endpoint. The credential is never logged: the service
log records each request's outcome code, its method (one of the common ones, else OTHER), the path of the route it
matched (else ``unmatched``; never the client's path) and the session's public id.

  <tools python> -I -B integrations/ownerhost/app.py serve --state-dir DIR --logs-dir DIR

is the server process; run it through service.py (``up``), which gives it the managed root's
``<state>/owner-host`` and ``<logs>/owner-host`` and a minimal environment.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime
import importlib.util
import json
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Callable

HERE = Path(os.path.realpath(__file__)).parent
REPO = HERE.parents[1]


def _load(name: str, path: Path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


session = _load('aieh_ownerhost_session', HERE / 'session.py')
conversation = _load('aieh_conversation_store', REPO / 'integrations' / 'conversation' / 'conversation_store.py')

from starlette.applications import Starlette          # noqa: E402  (the tools set; decision 0025 point 1)
from starlette.middleware import Middleware            # noqa: E402
from starlette.middleware.cors import CORSMiddleware   # noqa: E402
from starlette.responses import JSONResponse           # noqa: E402
from starlette.routing import Match, Route             # noqa: E402

LOOPBACK = '127.0.0.1'
PORT = 13310                       # the Integration process's one fixed port (nm-owner-ui-integration)
SHELL_ORIGINS = ('http://127.0.0.1:4173', 'http://127.0.0.1:5173')   # vite preview and dev (nm-owner-ui-shell)
ALLOWED_METHODS = ('GET', 'POST')
ALLOWED_HEADERS = (session.HEADER, 'Content-Type')
PREFLIGHT_MAX_AGE_S = 600
SERVER_RECORD_FORMAT = 'aieh-owner-host-server/1'
STOP_POLL_S = 0.2                  # how often the server looks for service.py's stop request
SECURITY_HEADERS = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}

REMEDIES = {
    'HOST_NOT_ALLOWED': f'address the Integration process as http://{LOOPBACK}:{PORT} exactly',
    'ORIGIN_NOT_ALLOWED': f'only the Owner UI shell may call it, from {" or ".join(SHELL_ORIGINS)}',
    'NOT_FOUND': 'the Integration process has no such route',
    'METHOD_NOT_ALLOWED': 'the route does not take this method',
    'PORT_IN_USE': f'stop what holds {LOOPBACK}:{PORT} (the Integration process uses no other port)',
}


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def refusal(code: str, detail: str, status: int, remedy: str | None = None) -> JSONResponse:
    return JSONResponse({'code': code, 'detail': detail, 'remedy': remedy or REMEDIES[code]}, status_code=status,
                        headers=SECURITY_HEADERS)


def _values(scope, key: bytes) -> list[bytes]:
    return [value for name, value in scope.get('headers') or () if name.lower() == key]


async def _refuse_scope(scope, receive, send, response: JSONResponse) -> None:
    if scope['type'] == 'websocket':
        await send({'type': 'websocket.close', 'code': 1008})
        return
    await response(scope, receive, send)


class HostOriginGuard:
    """Refuses a request whose Host is not the literal ``127.0.0.1:<port>`` or whose Origin, when present, is not
    one of the shell's origins. Outermost: nothing else runs for a refused request."""

    def __init__(self, app, *, port: int, log: Callable[[str], None]):
        self.app, self.host, self.log = app, f'{LOOPBACK}:{port}'.encode('ascii'), log

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        hosts = _values(scope, b'host')
        if hosts != [self.host]:
            self.log(f'refused HOST_NOT_ALLOWED {described(scope)}')
            return await _refuse_scope(scope, receive, send, refusal(
                'HOST_NOT_ALLOWED', f'the Host header must be {self.host.decode()}', 400))
        origins = _values(scope, b'origin')
        if origins and (len(origins) != 1 or origins[0].decode('latin-1') not in SHELL_ORIGINS):
            self.log(f'refused ORIGIN_NOT_ALLOWED {described(scope)}')
            return await _refuse_scope(scope, receive, send, refusal(
                'ORIGIN_NOT_ALLOWED', 'the request comes from an origin other than the Owner UI shell', 403))
        return await self.app(scope, receive, send)


class SessionGuard:
    """Every request needs the Owner UI session credential (session.check); the authenticated session's public
    record is put in ``scope['state']['owner_session']``. It runs inside the CORS middleware, which has already
    answered a preflight. A websocket is refused: the process has no websocket route."""

    def __init__(self, app, *, sessions, clock: Callable[[], str], log: Callable[[str], None]):
        self.app, self.sessions, self.clock, self.log = app, sessions, clock, log

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            self.log(f'refused WEBSOCKET {described(scope)}')
            return await send({'type': 'websocket.close', 'code': 1008})
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        where = described(scope)
        try:
            owner = session.check(self.sessions(), _values(scope, session.HEADER_KEY), self.clock())
        except session.SessionRefused as exc:
            self.log(f'refused {exc.code} {where}')
            return await refusal(exc.code, exc.detail, exc.status, exc.remedy)(scope, receive, send)
        scope.setdefault('state', {})['owner_session'] = owner.public()
        status = {}

        async def observe(message):
            if message['type'] == 'http.response.start':
                status['code'] = message['status']
                message.setdefault('headers', [])
                message['headers'] = list(message['headers']) + [
                    (k.lower().encode('ascii'), v.encode('ascii')) for k, v in SECURITY_HEADERS.items()
                    if not any(name.lower() == k.lower().encode('ascii') for name, _ in message['headers'])]
            await send(message)
        await self.app(scope, receive, observe)
        self.log(f'accepted {where} {status.get("code")} session={owner.session_id}')


async def start_session(request):
    """The login's one verified request: the authenticated session's public id and validity."""
    owner = request.scope['state']['owner_session']
    return JSONResponse({'sessionId': owner['sessionId'], 'issuedAt': owner['issuedAt'],
                         'expiresAt': owner['expiresAt']}, headers=SECURITY_HEADERS)


async def _not_found(request, exc):
    return refusal('NOT_FOUND', 'no route answers this path', 404)


async def _method_not_allowed(request, exc):
    return refusal('METHOD_NOT_ALLOWED', 'the route does not take this method', 405)


ROUTES = (Route('/session', start_session, methods=['POST']),)
LOGGED_METHODS = ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS')


def described(scope) -> str:
    """How a request is logged: its method if it is a common one (else OTHER) and the path of the route it matches
    (else ``unmatched``). Nothing the client wrote is logged verbatim, so no client can forge a log line or put a
    credential into the log through its path."""
    if scope['type'] == 'websocket':
        method = 'WEBSOCKET'
    else:
        method = scope.get('method') if scope.get('method') in LOGGED_METHODS else 'OTHER'
    for route in ROUTES:
        if scope['type'] == 'http' and route.matches(scope)[0] != Match.NONE:
            return f'{method} {route.path}'
    return f'{method} unmatched'


def create_app(sessions: Callable[[], object], *, port: int = PORT, clock: Callable[[], str] = now,
               log: Callable[[str], None] = lambda line: None, lifespan=None) -> Starlette:
    """The ASGI application. SESSIONS returns the object that answers ``session_by_verifier`` (the conversation
    store); CLOCK the current time (YYYY-MM-DDTHH:MM:SSZ); LOG takes one line per decided request."""
    return Starlette(
        routes=list(ROUTES),
        middleware=[
            Middleware(HostOriginGuard, port=port, log=log),
            Middleware(CORSMiddleware, allow_origins=list(SHELL_ORIGINS), allow_methods=list(ALLOWED_METHODS),
                       allow_headers=list(ALLOWED_HEADERS), allow_credentials=False, max_age=PREFLIGHT_MAX_AGE_S),
            Middleware(SessionGuard, sessions=sessions, clock=clock, log=log),
        ],
        exception_handlers={404: _not_found, 405: _method_not_allowed},
        lifespan=lifespan)


# ---------------------------------------------------------------------------- the server process


class ServeError(Exception):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail} (remedy: {REMEDIES.get(code, "see the service log")})')


def bind_listener(port: int = PORT) -> socket.socket:
    """The process's one socket: a TCP listener on 127.0.0.1:PORT, never connected anywhere. On Windows it is bound
    with SO_EXCLUSIVEADDRUSE: no other socket can bind 127.0.0.1:PORT while it is held, not even with SO_REUSEADDR.
    That excludes the same address only: a socket of another address of the port (0.0.0.0, [::]) can still be bound,
    so service.py's up refuses a port in use on any address and its readiness fails when any other socket holds the
    port. PORT_IN_USE when 127.0.0.1:PORT cannot be bound."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((LOOPBACK, port))
        listener.listen(128)
    except OSError as exc:
        listener.close()
        raise ServeError('PORT_IN_USE', f'{LOOPBACK}:{port} could not be bound ({exc.strerror or exc})') from None
    listener.set_inheritable(False)
    return listener


def _write_json(path: Path, data: dict) -> None:
    partial = path.with_name(path.name + '.partial')
    partial.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    os.replace(partial, path)


def harness_modules() -> list[str]:
    """The repository files this process has loaded, repository-relative (its live import census)."""
    found = set()
    for module in list(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if not name:
            continue
        path = Path(os.path.realpath(name))
        if path.is_relative_to(REPO):
            found.add(path.relative_to(REPO).as_posix())
    return sorted(found)


def console_window() -> bool | None:
    """Whether this process's console has a window (Windows: GetConsoleWindow); None off Windows."""
    if os.name != 'nt':
        return None
    import ctypes
    return bool(ctypes.WinDLL('kernel32').GetConsoleWindow())


def _logger(logs_dir: Path) -> logging.Logger:
    """The service log, <logs>/owner-host/service.log: uvicorn's own lines and one line per decided request."""
    handler = logging.FileHandler(logs_dir / 'service.log', encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s'))
    for name in ('uvicorn', 'uvicorn.error', 'aieh.ownerhost'):
        logger = logging.getLogger(name)
        logger.handlers[:] = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logging.getLogger('aieh.ownerhost')


def serve(state_dir: Path, logs_dir: Path, *, port: int = PORT) -> int:
    """The server process: open the conversation store, bind the listener, write the server record, serve until
    service.py asks it to stop (the stop-request file), then record the stop."""
    import uvicorn
    state_dir, logs_dir = Path(state_dir), Path(logs_dir)
    log = _logger(logs_dir)
    store = conversation.open_store(state_dir / conversation.DB_NAME)
    listener = bind_listener(port)
    record_path, stop_request = state_dir / 'server.json', state_dir / 'stop-request'
    holder = {}

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async def watch():
            while not stop_request.exists():
                await asyncio.sleep(STOP_POLL_S)
            log.info('stop requested')
            holder['server'].should_exit = True
        task = asyncio.create_task(watch())
        try:
            yield
        finally:
            task.cancel()

    app = create_app(lambda: store, port=port, log=log.info, lifespan=lifespan)
    config = uvicorn.Config(app, log_config=None, access_log=False, proxy_headers=False, server_header=False,
                            date_header=True, ws='none', http='h11', loop='asyncio', lifespan='on',
                            timeout_graceful_shutdown=5)
    server = holder['server'] = uvicorn.Server(config)
    record = {'format': SERVER_RECORD_FORMAT, 'state': 'listening', 'pid': os.getpid(), 'address': LOOPBACK,
              'port': port, 'started_at': now(), 'console_window': console_window(),
              'store': conversation.DB_NAME, 'harness_modules': harness_modules()}
    _write_json(record_path, record)
    log.info(f'listening on {LOOPBACK}:{port} (pid {os.getpid()})')
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
        store.close()
        record.update(state='stopped', stopped_at=now(), harness_modules=harness_modules())
        _write_json(record_path, record)
        log.info('stopped')
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='The Integration process (U-01.3): run it through service.py up.')
    sub = parser.add_subparsers(dest='verb', required=True)
    run = sub.add_parser('serve', help='serve on 127.0.0.1:13310 (the server process service.py starts)')
    run.add_argument('--state-dir', required=True, type=Path, help='<state>/owner-host of the managed root')
    run.add_argument('--logs-dir', required=True, type=Path, help='<logs>/owner-host of the managed root')
    args = parser.parse_args(argv)
    try:
        return serve(args.state_dir, args.logs_dir)
    except ServeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
