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
``NO_ANSWER``: to the dispatch path that is no answer, as the live transport's ``TransportError`` is. A call that asks
for the exchange delivery (``deliver=``) is refused before anything is sent (``FIXTURE_DELIVERY_UNAVAILABLE``): the
delivery is E-01.8's seam. ``calls`` records each call's method, path, status and the answer's catalog name, never a
body. Standard library only; the served fixture's process never loads this module.
"""
from __future__ import annotations

import http.client
import json

LOOPBACK = '127.0.0.1'
DISPATCHER_ACCESS = 'agentfixture-dispatcher-face-public-value'
LABEL_HEADER = 'X-AIEH-Fixture'
UI_PREFIX = '/ui'
KEY_HEADER = 'X-Session-API-Key'
FIXTURE = 'ai-engineering-harness/agentfixture'
TIMEOUT_S = 600            # a ceiling on one request (as the live transport's), not an expected duration


class FixtureTransportError(Exception):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}')


class FixtureTransport:
    authority = 'fixture'

    def __init__(self, port: int, *, access: str = DISPATCHER_ACCESS, timeout: float = TIMEOUT_S):
        if type(port) is not int or not 0 < port < 65536:
            raise ValueError('the fixture transport needs the fixture\'s port')
        self.port, self.access, self.timeout = port, access, timeout
        self.calls: list[dict] = []

    def __call__(self, method: str, path: str, body=None, **kwargs):
        if kwargs:
            raise FixtureTransportError('FIXTURE_DELIVERY_UNAVAILABLE', 'the exchange delivery is not the fixture '
                                        'listener\'s (E-01.8\'s seam); nothing was sent')
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
        return answer
