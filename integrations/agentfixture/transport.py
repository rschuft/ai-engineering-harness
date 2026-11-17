"""The fixture transport (plan leaf E-01.7; the I1 design's R8 point 6): the dispatcher's transport to the served
Agent Server fixture's dispatcher's face.

``FixtureTransport(port)`` is callable as the dispatch path's transport is (``transport(method, path, body)``, the
contract of ``integrations/dispatch/dispatch_inputs.py`` ``AgentServerClient``): it sends one request to the literal
``127.0.0.1`` and the fixture's port, with the dispatcher's face's public access value in ``X-Session-API-Key``,
and returns ``{"status", "body", "fixture"}``: the HTTP status, the JSON body (``None`` for none), and the fixture's
label from the answer's ``X-AIEH-Fixture`` header; ``body`` only when the fixture sent one (or a 204's ``None``), as the
core's answer in process has it. It can reach only a fixture:

- its target is the literal loopback address, never a name (no lookup) and never another host;
- an answer without the fixture's label is refused (``FixtureTransportError`` ``FIXTURE_LABEL_MISSING``): pointed at
  a real Agent Server by mistake it stops at the first answer, ``GET /server_info``, which precedes the create;
- it never calls the UI face: a path under ``/ui`` is refused before anything is sent (``FIXTURE_UI_FACE``);
- it declares ``authority = 'fixture'`` (decision 0026 point 2; the equality the dispatch path enforces is E-01.8's).

No answer (a refused connection, a withheld response at the ceiling) raises ``FixtureTransportError``
``NO_ANSWER``: to the dispatch path that is no answer, as the live transport's ``TransportError`` is. ``calls``
records each call's method, path, status and the answer's catalog name, never a body.

**The exchange delivery** (E-01.8's seam; the I1 integration design, R13; the engineering manager's rulings 3 and 5
of E-01.8). Given an exchange directory (``exchange=``) and the replayed execution profile's exchange bounds
(``bounds=``: its ``exchange.pull`` ``name_pattern`` and ``max_bytes``), a call that asks for the delivery
(``deliver={"part", "name"}``, as ``AgentServerClient`` passes a built command's) is sent as any other, and its answer
then goes through the API probe's own delivery rule, ``deliver(spec, entry)`` of ``tools/guest.py``'s ``API_PROBE``,
read from that file's source as data (``ast``) and never copied (``pinned_delivery``): the framed part of the answer's
``stdout`` checked against its stated sha256 and size, written exclusively into the exchange directory under the name,
and replaced in the answer by one ``AIEH-EXCHANGE-DELIVERED`` line; the answer carries ``delivered`` ``{name, sha256,
size}`` or ``{error}``, as the live transport's does. The bounds are ``exchange_delivery``'s: the smaller of
``max_bytes`` and ``tools/guest.py``'s ``EXCHANGE_DELIVERY_MAX_BYTES``. Nothing is invented: the part is the fixture's
labelled RESULT answer's, and the answer keeps its label. Without an exchange directory a delivery is refused before
anything is sent (``FIXTURE_DELIVERY_UNAVAILABLE``).

Standard library only; the served fixture's process never loads this module.
"""
from __future__ import annotations

import ast
import http.client
import json
import re
from pathlib import Path

LOOPBACK = '127.0.0.1'
DISPATCHER_ACCESS = 'agentfixture-dispatcher-face-public-value'
LABEL_HEADER = 'X-AIEH-Fixture'
UI_PREFIX = '/ui'
KEY_HEADER = 'X-Session-API-Key'
FIXTURE = 'ai-engineering-harness/agentfixture'
TIMEOUT_S = 600            # a ceiling on one request (as the live transport's), not an expected duration
GUEST = Path(__file__).resolve().parents[2] / 'tools' / 'guest.py'
DELIVERY_KEYS = ('name', 'part')
PART_RE = re.compile(r'[a-z][a-z0-9-]{0,31}')      # tools/guest.py EXCHANGE_PART_RE
_PINNED: dict = {}


def pinned_delivery(path: Path = GUEST):
    """(deliver, EXCHANGE_DELIVERY_MAX_BYTES) of tools/guest.py, read as data: the ``API_PROBE`` string's own
    ``deliver`` function with the import and the part markers it uses, compiled from that text alone, and the module's
    bound; LookupError when the source no longer has that shape."""
    if path in _PINNED:
        return _PINNED[path]
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    probe = limit = None
    for node in tree.body:
        names = [getattr(t, 'id', None) for t in node.targets] if isinstance(node, ast.Assign) else []
        if names == ['API_PROBE']:
            probe = ast.literal_eval(node.value)
        elif names == ['EXCHANGE_DELIVERY_MAX_BYTES'] and isinstance(node.value, ast.BinOp) \
                and isinstance(node.value.op, ast.LShift):
            limit = ast.literal_eval(node.value.left) << ast.literal_eval(node.value.right)
    if not isinstance(probe, str) or type(limit) is not int:
        raise LookupError('tools/guest.py has no API_PROBE string or EXCHANGE_DELIVERY_MAX_BYTES bound')
    kept = [n for n in ast.parse(probe).body if isinstance(n, ast.Import)
            or isinstance(n, ast.FunctionDef) and n.name == 'deliver'
            or isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Tuple)
            and [getattr(e, 'id', None) for e in n.targets[0].elts] == ['PART_BEGIN', 'PART_END', 'PART_DONE']]
    if [type(n).__name__ for n in kept] != ['Import', 'Assign', 'FunctionDef']:
        raise LookupError('API_PROBE no longer holds its import, its part markers and its deliver function')
    namespace: dict = {}
    exec(compile(ast.Module(body=kept, type_ignores=[]), f'{path}:API_PROBE', 'exec'), namespace)
    _PINNED[path] = (namespace['deliver'], limit)
    return _PINNED[path]


class _NameRefused(Exception):
    def __init__(self, code, detail):
        super().__init__(f'{code}: {detail}')


def pinned_name_check(path: Path = GUEST):
    """tools/guest.py's ``check_exchange_name`` (what ``exchange_delivery`` applies to a delivery's name before the
    live transport sends anything), read as data from that file's source and compiled alone, its ``Refused`` the
    local ``_NameRefused``; LookupError when the source no longer has it."""
    key = (path, 'check_exchange_name')
    if key not in _PINNED:
        found = [n for n in ast.parse(Path(path).read_text(encoding='utf-8')).body
                 if isinstance(n, ast.FunctionDef) and n.name == 'check_exchange_name']
        if len(found) != 1:
            raise LookupError('tools/guest.py has no check_exchange_name')
        namespace: dict = {'re': re, 'Refused': _NameRefused}
        exec(compile(ast.Module(body=found, type_ignores=[]), f'{path}:check_exchange_name', 'exec'), namespace)
        _PINNED[key] = namespace['check_exchange_name']
    return _PINNED[key]


class FixtureTransportError(Exception):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}')


class FixtureTransport:
    authority = 'fixture'

    def __init__(self, port: int, *, access: str = DISPATCHER_ACCESS, timeout: float = TIMEOUT_S, exchange=None,
                 bounds=None):
        if type(port) is not int or not 0 < port < 65536:
            raise ValueError('the fixture transport needs the fixture\'s port')
        if (exchange is None) != (bounds is None) or bounds is not None and not (
                isinstance(bounds, dict) and isinstance(bounds.get('name_pattern'), str)
                and type(bounds.get('max_bytes')) is int and bounds['max_bytes'] > 0):
            raise ValueError('an exchange delivery needs the exchange directory and the profile\'s exchange.pull '
                             'bounds (name_pattern, max_bytes)')
        self.port, self.access, self.timeout = port, access, timeout
        self.exchange, self.bounds = (None if exchange is None else Path(exchange)), bounds
        self.calls: list[dict] = []

    def _spec(self, deliver) -> dict:
        """The delivery's spec, as tools/guest.py exchange_delivery makes it for the API probe."""
        if self.exchange is None:
            raise FixtureTransportError('FIXTURE_DELIVERY_UNAVAILABLE', 'no exchange directory was given to the '
                                        'fixture transport; nothing was sent')
        if not isinstance(deliver, dict) or sorted(deliver) != list(DELIVERY_KEYS) \
                or not all(isinstance(deliver[k], str) for k in DELIVERY_KEYS) \
                or not PART_RE.fullmatch(deliver['part']):
            raise FixtureTransportError('DELIVERY_INVALID', 'an exchange delivery is {part, name}; nothing was sent')
        try:   # the name checked before anything is sent, as tools/guest.py exchange_delivery checks it (review 7)
            pinned_name_check()(deliver['name'], self.bounds['name_pattern'], 'exchange delivery name')
        except _NameRefused as exc:
            raise FixtureTransportError('DELIVERY_INVALID', f'{exc}; nothing was sent') from None
        _, limit = pinned_delivery()
        return {'field': 'stdout', 'part': deliver['part'], 'name': deliver['name'], 'dir': str(self.exchange),
                'name_pattern': self.bounds['name_pattern'], 'max_bytes': min(self.bounds['max_bytes'], limit)}

    def __call__(self, method: str, path: str, body=None, **kwargs):
        if set(kwargs) - {'deliver'}:
            raise FixtureTransportError('FIXTURE_DELIVERY_UNAVAILABLE', f'unknown arguments {sorted(kwargs)}; '
                                        'nothing was sent')
        spec = self._spec(kwargs['deliver']) if 'deliver' in kwargs else None
        if not isinstance(path, str) or not path.startswith('/') or path == UI_PREFIX \
                or path.startswith(UI_PREFIX + '/') or path.startswith(UI_PREFIX + '?'):
            raise FixtureTransportError('FIXTURE_UI_FACE', 'the dispatcher never calls the UI face; nothing was sent')
        data = None if body is None else json.dumps(body).encode('utf-8')
        headers = {KEY_HEADER: self.access}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        connection = http.client.HTTPConnection(LOOPBACK, self.port, timeout=self.timeout)
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            status, label = response.status, response.getheader(LABEL_HEADER)
        except (OSError, http.client.HTTPException) as exc:
            self.calls.append({'method': method, 'path': path, 'status': None, 'answer': None})
            raise FixtureTransportError('NO_ANSWER', f'{method} {path}: no answer ({type(exc).__name__})') from None
        finally:
            connection.close()
        try:
            fixture = json.loads(label) if label else None
        except ValueError:
            fixture = None
        if not isinstance(fixture, dict) or fixture.get('fixture') != FIXTURE or fixture.get('authority') != 'fixture':
            self.calls.append({'method': method, 'path': path, 'status': status, 'answer': None})
            raise FixtureTransportError('FIXTURE_LABEL_MISSING', f'{method} {path} answered {status} without the '
                                        'fixture\'s label: not the fixture')
        try:
            parsed = json.loads(raw.decode('utf-8')) if raw else None
        except ValueError:
            parsed = raw.decode('utf-8', 'replace')
        self.calls.append({'method': method, 'path': path, 'status': status, 'answer': fixture.get('answer')})
        # a body only when the fixture sent one, or a 204's none (the runtime stop's served null): an answer the
        # catalog serves without a body (a refusal, the 404, the message's) arrives without one, as in process
        answer = {'status': status, 'fixture': fixture}
        if raw or status == 204:
            answer['body'] = parsed
        if spec is not None:   # the API probe's own rule over the labelled answer (module docstring)
            deliver, _ = pinned_delivery()
            entry = {'body': answer.get('body')}
            answer['delivered'] = deliver(spec, entry)
            answer['body'] = entry['body']
            self.calls[-1]['delivered'] = dict(answer['delivered'])
        return answer
