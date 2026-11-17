"""The served Agent Server fixture (plan leaf E-01.7, slice 9): the cited core on one host-loopback listener, with two
faces and its scripted scenarios.

A Starlette application on uvicorn (the I1 design's R1 and R12), run under the tools interpreter, bound to
``127.0.0.1`` only, on the one declared port ``PORT`` (13320) or, in a test, a free port the test chose. It answers
from the one fixture catalog (``observations.json``) through ``core.AgentServerCore``; it never executes what it
receives (the core recognizes the harness's own SEED and RESULT scripts only, ``result.py``).

**Two faces on one port.**

- *The dispatcher's face*, at the root: the outer, Docker-mode routes of the dispatcher's allowlist, answered by the
  core (``AgentServerCore.__call__``). ``GET /server_info`` is public, as the pinned server's is; every other request
  needs ``X-Session-API-Key`` equal to ``DISPATCHER_ACCESS``, a public labelled value, and is otherwise answered
  ``unauthorized`` (S-01.3.1's observed ``401 {"detail": "Unauthorized"}``): the UI face's value is refused here, as
  E-01.3.3 step (4) observed of the runtime credential on the outer server.
- *The UI face*, under ``UI_PREFIX`` (``/ui``): the read-only view a conversation's own server gives the Owner UI and
  Agent Canvas (``AgentServerCore.ui_answer``, ``ui_session``). Every method but ``GET`` is refused with the label
  before anything else, and so is every inbound message on its session socket but the authentication frame (the
  pinned socket would run it: G10). Its access value is ``UI_ACCESS``; the dispatcher's value is refused there. The
  dispatcher never calls it, and nothing it serves is read by the dispatch path.

**Every answer carries the label**: the response header ``LABEL_HEADER`` (``X-AIEH-Fixture``, the catalog's label as
JSON, naming the catalog answer, the face and, on the UI face, the source-derived fields), on every HTTP answer and on
the session socket's handshake. A request outside the catalog, or whose answer would need a field no class admits, is
refused: HTTP 501 with the label (``FIXTURE_NO_OBSERVATION``). The dispatcher's face's one source-derived entry (the
event that records the dispatcher's own initial message, ``message-event``) is answered by the core in process only:
**the listener refuses the request that would need it** (an event search whose answer would hold it).

**Create validation** (E-01.4.2's carried item, the engineering manager's ruling 2): a create body is validated
against the locked release document's ``StartConversationRequest`` (``openapi.json`` of release v1.60.1, never
committed: decision 0005; the process is given its path, and its sha256 must equal the lock's) with the harness's
standard-library schema subset (``tools/check_profile.py`` ``schema_errors``) before the core sees it. A body that does
not validate, or any create while no document is given, is refused with the label and never answered 201.

**Scenarios** (``SCENARIOS``), chosen when the process starts, advance by call count, never by a clock or a control
route. A transport event (a response withheld, a request that never reaches the core) is not an answer: the listener
holds the request until the client goes away and sends nothing. The provenance table lists each with its scenario.

**What it never does**: it opens no outbound connection (an audit hook refuses every ``socket.connect`` and
``getaddrinfo`` in the process once its event loop exists, the Integration process's pattern), it imports no client
module, and no route reaches a guest, a model or a credential. The call log (``--log``, a file outside the checkout)
records each request's face, method, path, the catalog answer or the transport event, never a body.

    <tools python> -I -B integrations/agentfixture/server.py serve --port PORT --scenario NAME --log FILE
        [--openapi FILE] [--state-dir DIR]

It stops when ``<state-dir>/stop-request`` exists. Standard library, Starlette and uvicorn.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import errno
import hashlib
import importlib.util
import json
import os
import re
import socket
import sys
from pathlib import Path
from urllib.parse import parse_qs

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LOOPBACK = '127.0.0.1'
PORT = 13320
UI_PREFIX = '/ui'
DISPATCHER_ACCESS = 'agentfixture-dispatcher-face-public-value'
UI_ACCESS = 'agentfixture-ui-face-public-value'
LABEL_HEADER = 'X-AIEH-Fixture'
KEY_HEADER = 'x-session-api-key'
SCENARIOS = ('finished', 'running', 'pending', 'failed', 'lost-create-acknowledgement', 'unknown')
RUNNING_READS = 7                  # the running scenario's UI window: D1's wait read the conversation seven times
MAX_BODY_DEPTH = 64                # a body nested deeper is malformed: the core copies and walks bodies recursively
# the origins the pinned CORS middleware always allows: host localhost or 127.0.0.1
# (as:openhands/agent_server/middleware.py:52-60); http only, any port
LOOPBACK_ORIGIN = re.compile(r'http://(localhost|127\.0\.0\.1)(:[0-9]{1,5})?')


class OriginRefused(ValueError):
    """A configured UI origin that is not a loopback http origin (UI_ORIGIN_NOT_LOOPBACK)."""
    code = 'UI_ORIGIN_NOT_LOOPBACK'


def depth(value) -> int:
    """VALUE's nesting depth (a scalar 0), walked without recursion."""
    deepest, stack = 0, [(value, 1)]
    while stack:
        item, level = stack.pop()
        if isinstance(item, (dict, list)):
            deepest = max(deepest, level)
            stack.extend((child, level + 1) for child in (item.values() if isinstance(item, dict) else item))
    return deepest
LOCKED_DOCUMENT_SHA256 = '3de49fac4670eff9c8b6635ffd8bc5b6d4219788877747135333cec9f8c5e0d0'
CREATE_SCHEMA = '#/components/schemas/StartConversationRequest'
SOCKET_ROUTE = '/sockets/session/'
STOP_POLL_S = 0.2                  # the stop-request file's poll interval (a service's own loop, not a wait in a test)
REFUSED_CLOSE = 1008               # a socket refusal's close code (policy violation), its reason the label's
CONVERSATIONS = '/api/conversations'


def _load(name: str, path: Path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


def core_module():
    return _load('agentfixture_core', HERE / 'core.py')


def schema_errors(value, ref: str, document: dict) -> list[str]:
    """tools/check_profile.py's standard-library JSON Schema subset (2020-12, as OpenAPI 3.1 uses it), loaded by
    path."""
    return _load('aieh_check_profile', REPO / 'tools' / 'check_profile.py').schema_errors(value, {'$ref': ref},
                                                                                       document)


def locked_document(path) -> dict:
    """The locked release openapi.json at PATH, checked against the lock's sha256 (ValueError otherwise)."""
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != LOCKED_DOCUMENT_SHA256:
        raise ValueError(f'{path} is not the locked openapi.json (sha256 {LOCKED_DOCUMENT_SHA256})')
    return json.loads(data.decode('utf-8'))


def in_catalog(routes: list, face: str, method: str, path: str) -> bool:
    """Whether METHOD PATH (the face's prefix removed) is a route the catalog serves on FACE (``served.routes``, by
    method and path template); a request outside them is refused with the label before anything else."""
    for route in routes:
        if route['face'] == face and route['method'] == method:
            pattern = re.escape(route['path']).replace(r'\{conversation_id\}', '[^/]+')
            if re.fullmatch(pattern, path):
                return True
    return False


class Fixture:
    """One served fixture: the core, the scenario and its counters, the locked document, the call log."""

    def __init__(self, scenario: str = 'finished', *, core=None, openapi: dict | None = None, log: Path | None = None,
                 scratch: Path | None = None, ui_origins=()):
        if scenario not in SCENARIOS:
            raise ValueError(f'not a scenario: {scenario!r}')
        self.scenario = scenario
        self.ui_origins = tuple(ui_origins)
        refused = [o for o in self.ui_origins if not isinstance(o, str) or LOOPBACK_ORIGIN.fullmatch(o) is None]
        if refused:
            # only an origin the pinned CORS middleware allows (host localhost or 127.0.0.1:
            # as:openhands/agent_server/middleware.py:52-60), so that ui-preflight's 200 stays derivable from it
            # (criterion 8; review round 2); [::1] is not one, so it is refused
            raise OriginRefused(f'{OriginRefused.code}: {refused!r}: a UI origin must be http on localhost or '
                                '127.0.0.1')
        self._lock = None
        self.core = core if core is not None else core_module().AgentServerCore(
            scratch=scratch, ui_running_reads=RUNNING_READS if scenario == 'running' else 0)
        self.openapi, self.log_path = openapi, (Path(log) if log is not None else None)
        self.log: list[dict] = []
        self.creates = 0
        self.messages = 0
        self.withheld_lookups: set[str] = set()
        self.routes = self.core.catalog['served']['routes']

    def call(self, method: str, path: str, body):
        """One request into the core (its call log, then its answer): the dispatcher's face's one entry to it."""
        return self.core(method, path, body)

    async def serialized(self, work):
        """WORK (a function of no argument) run off the event loop, in a worker thread, one at a time: the core's
        state is not shared between threads, and SEED and RESULT run a process (review N-e). The loop meanwhile
        goes on serving what needs no core state (a refusal outside the catalog, a preflight, a withheld response,
        the stop request)."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            return await asyncio.to_thread(work)

    # -- CORS (the engineering manager's ruling 2 of E-01.7's review) ---------------------------------------------
    def preflight(self, face: str, path: str, headers: dict) -> tuple[dict, list]:
        """(the answer, its CORS headers) for an OPTIONS request. The dispatcher's face has no CORS at all: no browser
        drives it, so its preflight is the labelled refusal. On the UI face a preflight is answered only from an
        explicitly configured origin (``ui_origins``; none by default), for ``GET`` of a UI route the catalog serves,
        asking for no header but the access value's; no credentials are ever allowed. Anything else is the labelled
        refusal."""
        core = self.core
        origin = headers.get('origin')
        method = headers.get('access-control-request-method')
        asked = {h.strip().lower() for h in headers.get('access-control-request-headers', '').split(',') if h.strip()}
        if face != 'ui':
            return core.refuse('a preflight on the dispatcher\'s face: no browser drives it'), []
        if origin not in self.ui_origins or method != 'GET' or not in_catalog(self.routes, 'ui', 'GET', path) \
                or not asked <= {KEY_HEADER}:
            return core.refuse('a preflight the UI face does not allow (an origin not configured, a method but GET, '
                               'a route outside its catalog, or a header but the access value\'s)'), []
        cors = [(b'access-control-allow-origin', origin.encode('latin-1')), (b'access-control-allow-methods', b'GET'),
                (b'vary', b'Origin')]
        if asked:
            cors.append((b'access-control-allow-headers', KEY_HEADER.encode('ascii')))
        return core.ui_preflight(), cors

    def cors(self, face: str, headers: dict) -> list:
        """The CORS headers of a UI-face answer to a configured origin's request; none otherwise."""
        origin = headers.get('origin')
        if face == 'ui' and origin in self.ui_origins:
            return [(b'access-control-allow-origin', origin.encode('latin-1')), (b'vary', b'Origin')]
        return []

    def note(self, **entry) -> None:
        self.log.append(entry)
        if self.log_path is not None:
            with open(self.log_path, 'a', encoding='utf-8') as handle:
                handle.write(json.dumps(entry, sort_keys=True) + '\n')

    # -- the dispatcher's face ----------------------------------------------------------------------------------
    def dispatcher(self, method: str, path: str, query: str, key: str | None, body) -> tuple[dict | None, str]:
        """(the answer, or None for a response withheld; the event) for one request on the dispatcher's face."""
        core = self.core
        target = f'{path}?{query}' if query else path
        if not in_catalog(self.routes, 'dispatcher', method, path):
            return core.refuse(f'{method} {path}: not in the catalog'), 'answered'
        if (method, path, query) != ('GET', '/server_info', ''):
            if self.scenario == 'failed' or key != DISPATCHER_ACCESS:
                return core.unauthorized('dispatcher'), 'answered'
        if (method, path) == ('POST', CONVERSATIONS) and not query:
            refused = self.create_refusal(body)
            if refused is not None:
                return core.refuse(refused), 'answered'
            self.creates += 1
            answer = self.call(method, target, body)
            if self.creates == 1 and self.scenario in ('lost-create-acknowledgement', 'unknown'):
                if isinstance(body, dict) and isinstance(body.get('conversation_id'), str):
                    self.withheld_lookups.add(body['conversation_id'])
                return None, 'response withheld (the create reached the core)'
            return answer, 'answered'
        if method == 'POST' and path.startswith(CONVERSATIONS + '/') and path.endswith('/events') and not query:
            self.messages += 1
            if self.messages == 1 and self.scenario == 'pending':
                return None, 'request never reaches the core (the message)'
        answer = self.call(method, target, body)
        if self.scenario == 'unknown' and method == 'GET' and not query \
                and path.rpartition('/')[2] in self.withheld_lookups and path.count('/') == 3:
            return None, 'response withheld (the lookup reached the core)'
        if answer.get('fixture', {}).get('sourceDerived'):
            return core.refuse('an answer that needs the dispatcher face\'s source-derived entry (message-event): '
                               'answered in process only, never by this listener'), 'answered'
        return answer, 'answered'

    def create_refusal(self, body) -> str | None:
        """Why a create body is refused before the core sees it (ruling 2), or None when it validates."""
        if self.openapi is None:
            return 'a create while the locked openapi.json is not given: it cannot be validated'
        if not isinstance(body, dict):
            return 'a create body that is not a JSON object'
        errors = schema_errors(body, CREATE_SCHEMA, self.openapi)
        if errors:
            return f'a create body that does not validate against StartConversationRequest ({len(errors)} error(s))'
        return None

    # -- the UI face --------------------------------------------------------------------------------------------
    def ui(self, method: str, path: str, query: str, key: str | None) -> dict:
        core = self.core
        if method != 'GET':
            return core.refuse(f'{method} {path}: the UI face is read only')
        if not in_catalog(self.routes, 'ui', method, path):
            return core.refuse(f'{method} {path}: not in the UI face\'s catalog')
        if (path, query) != ('/server_info', '') and key != UI_ACCESS:
            return core.unauthorized('ui')
        return core.ui_answer(method, f'{path}?{query}' if query else path)


def label_header(answer: dict) -> tuple[bytes, bytes]:
    return LABEL_HEADER.lower().encode('ascii'), json.dumps(answer['fixture'], sort_keys=True,
                                                           separators=(',', ':')).encode('ascii')


def _plain(value):
    """An answer as plain JSON data."""
    return json.loads(json.dumps(value))


def create_app(fixture: Fixture, *, lifespan=None):
    """The ASGI application: one handler for both faces' HTTP and the UI face's session socket. Its CORS is its own
    and narrow (``Fixture.preflight``, ``Fixture.cors``): none on the dispatcher's face; on the UI face, GET only, from
    configured origins only, never with credentials. Agent Canvas needs none of it: it reaches the UI face through
    upstream's static server, whose reverse proxy makes its requests same-origin (the I1 design's R14 fact 2)."""

    async def app(scope, receive, send):
        if scope['type'] == 'lifespan':
            return await _lifespan(scope, receive, send, lifespan)
        if scope['type'] == 'websocket':
            return await _socket(fixture, scope, receive, send)
        return await _http(fixture, scope, receive, send)

    return app


async def _lifespan(scope, receive, send, lifespan):
    message = await receive()
    context = lifespan() if lifespan is not None else contextlib.nullcontext()
    async with contextlib.AsyncExitStack() as stack:
        if hasattr(context, '__aenter__'):
            await stack.enter_async_context(context)
        else:
            stack.enter_context(context)
        await send({'type': 'lifespan.startup.complete'})
        while message['type'] != 'lifespan.shutdown':
            message = await receive()
    await send({'type': 'lifespan.shutdown.complete'})


def host_allowed(scope, headers: dict) -> bool:
    """The UI face's Host rule (U-01.2's review, N2: DNS rebinding): the request's Host must be the literal address of
    the listener that received it, ``127.0.0.1:<its port>`` (13320 when served; a test's own free port), exactly what
    upstream's static server sends through its proxy (``changeOrigin``: the target's host and port)."""
    server = scope.get('server')
    return bool(server) and server[0] == LOOPBACK and headers.get('host') == f'{LOOPBACK}:{server[1]}'


HOST_REFUSED = 'a Host that is not this listener\'s own address, 127.0.0.1:<port> (DNS rebinding)'


def _split(path: str) -> tuple[str, str]:
    if path == UI_PREFIX or path.startswith(UI_PREFIX + '/'):
        return 'ui', path[len(UI_PREFIX):] or '/'
    return 'dispatcher', path


async def _body(receive) -> tuple[bytes, bool]:
    chunks, more = [], True
    while more:
        message = await receive()
        if message['type'] == 'http.disconnect':
            return b''.join(chunks), False
        chunks.append(message.get('body', b''))
        more = message.get('more_body', False)
    return b''.join(chunks), True


async def _withhold(receive) -> None:
    """A transport event: the response is withheld until the client goes away (nothing is sent)."""
    while (await receive())['type'] != 'http.disconnect':
        pass


async def _http(fixture: Fixture, scope, receive, send):
    method, (face, path) = scope['method'], _split(scope['path'])
    query = scope.get('query_string', b'').decode('latin-1')
    headers = {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in scope.get('headers', [])}
    raw, connected = await _body(receive)
    if not connected:
        return
    if face == 'ui' and not host_allowed(scope, headers):
        answer = fixture.core.refuse(HOST_REFUSED)
        fixture.note(face=face, method=method, path=path, event='answered', answer='refusal', status=answer['status'])
        return await _respond(send, answer)
    if method == 'OPTIONS':
        answer, cors = fixture.preflight(face, path, headers)
        fixture.note(face=face, method=method, path=path, event='answered', answer=answer['fixture']['answer'],
                     status=answer.get('status'))
        return await _respond(send, answer, cors)
    body = None
    if raw:
        try:
            body = json.loads(raw.decode('utf-8'))
            if depth(body) > MAX_BODY_DEPTH:
                raise ValueError('nested past the fixture\'s depth')
        except (ValueError, RecursionError):
            answer = fixture.core.malformed()
            fixture.note(face=face, method=method, path=path, event='answered', answer='malformed',
                         status=answer['status'])
            return await _respond(send, answer)
    key = headers.get(KEY_HEADER)
    if face == 'ui' and method != 'GET':
        answer, event = fixture.core.refuse(f'{method} {path}: the UI face is read only'), 'answered'
    elif not in_catalog(fixture.routes, face, method, path):
        answer, event = fixture.core.refuse(f'{method} {path}: not in the catalog'), 'answered'
    elif face == 'dispatcher':
        answer, event = await fixture.serialized(lambda: fixture.dispatcher(method, path, query, key, body))
    else:
        answer, event = await fixture.serialized(lambda: fixture.ui(method, path, query, key)), 'answered'
    fixture.note(face=face, method=method, path=path, event=event,
                 answer=None if answer is None else answer['fixture']['answer'],
                 status=None if answer is None else answer.get('status'))
    if answer is None:
        return await _withhold(receive)
    await _respond(send, answer, fixture.cors(face, headers))


async def _respond(send, answer: dict, extra=()) -> None:
    answer = _plain(answer)
    status = answer.get('status')
    data = b'' if 'body' not in answer or status == 204 else json.dumps(answer['body']).encode('utf-8')
    headers = [label_header(answer), *extra]
    if data:
        headers.append((b'content-type', b'application/json'))
    await send({'type': 'http.response.start', 'status': status, 'headers': headers})
    await send({'type': 'http.response.body', 'body': data})


async def _socket(fixture: Fixture, scope, receive, send):
    """The UI face's session socket (``/ui/sockets/session/<id>?after_seq=<n>``): authenticated by the access value
    in the first frame (or, deprecated upstream, the header or query); then one ``sync`` frame and the replay, as the
    pinned server sends them (G10); every inbound frame but an authentication frame is refused, the socket closed."""
    core = fixture.core
    face, path = _split(scope['path'])
    params = parse_qs(scope.get('query_string', b'').decode('latin-1'))
    headers = {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in scope.get('headers', [])}
    if (await receive())['type'] != 'websocket.connect':
        return
    cid = path[len(SOCKET_ROUTE):] if path.startswith(SOCKET_ROUTE) else None
    refusal = None
    if face != 'ui' or not cid or set(params) - {'after_seq', 'session_api_key'}:
        refusal = 'a socket outside the catalog'
    elif not host_allowed(scope, headers):
        refusal = HOST_REFUSED
    after_seq = None
    if refusal is None and 'after_seq' in params:
        try:
            after_seq = int(params['after_seq'][-1])
        except ValueError:
            refusal = 'an after_seq that is not an integer'
    fixture.note(face=face, method='WEBSOCKET', path=path, event='connect')
    given = params['session_api_key'][-1] if 'session_api_key' in params else headers.get(KEY_HEADER)
    if refusal is None and given is not None and given != UI_ACCESS:
        # a wrong key in the query or header: the handshake is refused (S-01.3.1 section 3.4: 403), labelled
        denied = core.answers['ui-socket-denied']
        fixture.note(face=face, method='WEBSOCKET', path=path, event='denied', answer='ui-socket-denied',
                     status=denied['status'])
        await send({'type': 'websocket.http.response.start', 'status': denied['status'],
                    'headers': [label_header({'fixture': core.ui_label('ui-socket-denied', [])})]})
        return await send({'type': 'websocket.http.response.body', 'body': b''})
    label = core.ui_label('ui-socket', []) if face == 'ui' else core.label('socket-refusal')
    await send({'type': 'websocket.accept', 'headers': [label_header({'fixture': label})]})
    if refusal is not None:
        return await _close(fixture, send, REFUSED_CLOSE, refusal, face, path)
    if given is None:
        first = await receive()
        if first['type'] != 'websocket.receive':
            return
        try:
            data = json.loads(first.get('text') or first.get('bytes') or b'')
        except ValueError:
            data = None
        given = data.get('session_api_key') if isinstance(data, dict) and data.get('type') == 'auth' else ''
    if given != UI_ACCESS:
        unauthorized = core.answers['ui-socket-unauthorized']
        return await _close(fixture, send, unauthorized['code'], unauthorized['reason'], face, path,
                            answer='ui-socket-unauthorized')
    frames, refused = await fixture.serialized(lambda: core.ui_session(cid, after_seq))
    if frames is None:
        return await _close(fixture, send, REFUSED_CLOSE, refused, face, path)
    for frame in frames:
        frame = _plain(frame)
        await send({'type': 'websocket.send', 'text': json.dumps(frame['body'])})
        fixture.note(face=face, method='WEBSOCKET', path=path, event='frame', answer=frame['fixture']['answer'])
    while True:
        message = await receive()
        if message['type'] != 'websocket.receive':
            return
        try:
            data = json.loads(message.get('text') or message.get('bytes') or b'')
        except ValueError:
            data = None
        if isinstance(data, dict) and data.get('type') == 'auth':
            continue
        return await _close(fixture, send, REFUSED_CLOSE, 'an inbound message on the read-only UI face', face, path)


async def _close(fixture, send, code: int, reason: str, face: str, path: str, answer: str = 'socket-refusal'):
    text = reason if answer != 'socket-refusal' else f'FIXTURE_NO_OBSERVATION: {reason}'
    fixture.note(face=face, method='WEBSOCKET', path=path, event='closed', answer=answer, code=code)
    await send({'type': 'websocket.close', 'code': code, 'reason': text.encode('utf-8')[:123].decode('utf-8',
                                                                                                   'ignore')})


# ---------------------------------------------------------------------------------------------- the server process

OUTBOUND_EVENTS = frozenset({'socket.connect', 'socket.getaddrinfo'})


class OutboundRefused(PermissionError):
    """An outbound connection or name lookup in the served fixture's process once its guard is armed."""


class OutboundGuard:
    """The process opens no outbound connection: an audit hook, armed in the lifespan once uvicorn's event loop and
    its self-pipe exist (the Integration process's measured pattern, integrations/ownerhost/app.py), refuses every
    ``socket.connect`` and ``socket.getaddrinfo`` from then on. Only the server process arms it."""

    def __init__(self):
        self.armed = False

    def arm(self) -> None:
        if not self.armed:
            sys.addaudithook(self._hook)
            self.armed = True

    @staticmethod
    def _hook(event, _args):
        if event in OUTBOUND_EVENTS:
            raise OutboundRefused(errno.EACCES, f'{event} refused: the served fixture opens no outbound connection')


OUTBOUND_GUARD = OutboundGuard()


def bind_listener(port: int) -> socket.socket:
    """The process's one socket: a TCP listener on 127.0.0.1:PORT (SO_EXCLUSIVEADDRUSE on Windows)."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((LOOPBACK, port))
        listener.listen(128)
    except OSError:
        listener.close()
        raise
    listener.set_inheritable(False)
    return listener


def guard_probe(port: int) -> str:
    """The armed guard shown in the process itself (review ruling 4): one connect to the process's own listener,
    which the guard must refuse before any packet is sent. 'refused' when it did, else what happened instead (a
    connect that went through means the guard is not armed). It is the served sources' one connect call site."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.connect((LOOPBACK, port))
        return 'connected'
    except OutboundRefused:
        return 'refused'
    except OSError as exc:
        return f'error: {type(exc).__name__}'
    finally:
        probe.close()


def serve(*, port: int, scenario: str, log: Path, openapi: Path | None = None, state_dir: Path | None = None,
          scratch: Path | None = None, ui_origins=()) -> int:
    """The server process: bind, write ``<state-dir>/server.json`` (pid, address, port, the loaded modules), arm the
    outbound guard once the event loop exists and record its probe (``<state-dir>/guard.json``), then print its ready
    line and serve until ``<state-dir>/stop-request`` exists."""
    import uvicorn
    document = locked_document(openapi) if openapi is not None else None
    fixture = Fixture(scenario, openapi=document, log=log, scratch=scratch, ui_origins=ui_origins)
    listener = bind_listener(port)
    holder = {}
    state = Path(state_dir) if state_dir is not None else None

    @contextlib.asynccontextmanager
    async def lifespan():
        OUTBOUND_GUARD.arm()
        if state is not None:
            (state / 'guard.json').write_text(json.dumps({'armed': OUTBOUND_GUARD.armed,
                                                          'probe': guard_probe(port)}) + '\n', encoding='utf-8')
        print(f'listening {LOOPBACK}:{port}', flush=True)  # the starter's signal: bound, the guard armed
        async def watch():
            while state is None or not (state / 'stop-request').exists():
                await asyncio.sleep(STOP_POLL_S)
            holder['server'].should_exit = True
        task = asyncio.create_task(watch())
        try:
            yield
        finally:
            task.cancel()

    config = uvicorn.Config(create_app(fixture, lifespan=lifespan), log_config=None, access_log=False,
                            proxy_headers=False, server_header=False, date_header=False, ws='websockets-sansio',
                            http='h11', loop='asyncio', lifespan='on', timeout_graceful_shutdown=2)
    server = holder['server'] = uvicorn.Server(config)
    if state is not None:
        state.mkdir(parents=True, exist_ok=True)
        modules = sorted(name for name in sys.modules)
        (state / 'server.json').write_text(json.dumps({'pid': os.getpid(), 'address': LOOPBACK, 'port': port,
                                                       'scenario': scenario, 'modules': modules}) + '\n',
                                           encoding='utf-8')
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
        fixture.core.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='The served Agent Server fixture (E-01.7).')
    sub = parser.add_subparsers(dest='verb', required=True)
    run = sub.add_parser('serve', help='serve the fixture on 127.0.0.1')
    run.add_argument('--port', type=int, default=PORT)
    run.add_argument('--scenario', choices=SCENARIOS, default='finished')
    run.add_argument('--log', type=Path, required=True, help='the call log (JSON lines), outside the checkout')
    run.add_argument('--openapi', type=Path, help='the locked release openapi.json (downloaded, sha256-checked)')
    run.add_argument('--state-dir', type=Path, help='server.json and the stop-request file')
    run.add_argument('--scratch', type=Path, help='the core\'s scratch directory (SEED and RESULT)')
    run.add_argument('--ui-origin', action='append', default=[],
                     help='an origin whose browser requests the UI face answers with CORS (GET only; none by default)')
    args = parser.parse_args(argv)
    bad = [o for o in args.ui_origin if LOOPBACK_ORIGIN.fullmatch(o) is None]
    if bad:
        print(f'{OriginRefused.code}: {bad!r}: a UI origin must be http on localhost or 127.0.0.1',
              file=sys.stderr)
        return 2
    return serve(port=args.port, scenario=args.scenario, log=args.log, openapi=args.openapi, state_dir=args.state_dir,
                 scratch=args.scratch, ui_origins=args.ui_origin)


if __name__ == '__main__':
    sys.exit(main())
