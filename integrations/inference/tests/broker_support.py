"""Shared fixtures of the inference broker's tests (plan leaf S-03.2, slice 1).

Everything here is synthetic: the provider key, the model names, the attempt and conversation ids and the
upstreams. FakeUpstream is one in-process ThreadingHTTPServer on an ephemeral 127.0.0.1 port that plays one
declared API family's provider: it records what it receives and answers as JSON or as a server-sent event
stream with that family's usage events. No real credential store, provider, network or managed root is
touched: every broker here gets its own integration store and audit directory in a temporary directory, and an
in-memory credential provider.
"""
from __future__ import annotations

import email.message
import http.client
import http.server
import importlib.util
import json
import shutil
import sys
import tempfile
import threading
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


IB = _load('aieh_inference_broker', HERE.parent / 'inference_broker.py')
STORE = _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')
C = IB.contract

PROVIDER = 'synthetic-provider'
OTHER_PROVIDER = 'other-synthetic-provider'
KEY = 'synthetic-provider-key-NOT-A-REAL-CREDENTIAL-0f1e2d3c'
MODEL_A, MODEL_B, MODEL_C = 'syn-model-a', 'syn-model-b', 'syn-model-c'
PROMPT_MARKER = 'SYNTHETIC-PROMPT-MARKER-7d41'
ANSWER_MARKER = 'SYNTHETIC-ANSWER-MARKER-2c9e'
FAMILIES = ('anthropic-messages', 'openai-responses', 'openai-chat')
ROUTE = {'anthropic-messages': '/v1/messages', 'openai-responses': '/v1/responses',
         'openai-chat': '/v1/chat/completions'}


def new_id() -> str:
    return str(uuid.uuid4())


class MemoryProvider(C.CredentialProvider):
    """An in-memory credential provider: one dict entry per name."""
    name = 'memory-fake'

    def __init__(self, entries=None):
        self.entries = dict(entries or {})

    def get(self, name):
        return self.entries.get(name)

    def set(self, name, user, secret, comment=''):
        self.entries[name] = (user, secret)

    def delete(self, name):
        return self.entries.pop(name, None) is not None


class Clock:
    """A settable clock for expiry: no test waits for time to pass."""

    def __init__(self, now=1_900_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def headers(*pairs) -> email.message.Message:
    message = email.message.Message()
    for name, value in pairs:
        message[name] = value
    return message


def auth(family: str, token: str) -> tuple:
    return ('x-api-key', token) if family == 'anthropic-messages' else ('Authorization', f'Bearer {token}')


# ---------------------------------------------------------------- the fake upstreams


def usage_events(family: str, *, with_usage: bool = True) -> list:
    """The SSE events of one streamed answer, in the family's shape (synthetic counts: input 11, output 7)."""
    if family == 'anthropic-messages':
        events = [{'type': 'message_start', 'message': {'id': 'msg_syn', 'usage': {'input_tokens': 11,
                                                                                    'output_tokens': 1}}},
                  {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': ANSWER_MARKER}}]
        events.append({'type': 'message_delta', 'usage': {'output_tokens': 7}} if with_usage
                      else {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}})
        events.append({'type': 'message_stop'})
        return [(e['type'], e) for e in events]
    if family == 'openai-responses':
        done = {'type': 'response.completed', 'response': {'id': 'resp_syn', 'usage': {
            'input_tokens': 11, 'output_tokens': 7, 'total_tokens': 18}} if with_usage else {'id': 'resp_syn'}}
        return [(None, {'type': 'response.created', 'response': {'id': 'resp_syn', 'usage': None}}),
                (None, {'type': 'response.output_text.delta', 'delta': ANSWER_MARKER}), (None, done)]
    chunks = [(None, {'id': 'chat_syn', 'choices': [{'delta': {'content': ANSWER_MARKER}}], 'usage': None})]
    if with_usage:
        chunks.append((None, {'id': 'chat_syn', 'choices': [], 'usage': {'prompt_tokens': 11,
                                                                         'completion_tokens': 7,
                                                                         'total_tokens': 18}}))
    return chunks


def json_answer(family: str, *, with_usage: bool = True) -> dict:
    if family == 'anthropic-messages':
        answer = {'id': 'msg_syn', 'type': 'message', 'content': [{'type': 'text', 'text': ANSWER_MARKER}]}
        usage = {'input_tokens': 11, 'output_tokens': 7}
    elif family == 'openai-responses':
        answer = {'id': 'resp_syn', 'object': 'response', 'output_text': ANSWER_MARKER}
        usage = {'input_tokens': 11, 'output_tokens': 7, 'total_tokens': 18}
    else:
        answer = {'id': 'chat_syn', 'object': 'chat.completion',
                  'choices': [{'message': {'content': ANSWER_MARKER}}]}
        usage = {'prompt_tokens': 11, 'completion_tokens': 7, 'total_tokens': 18}
    if with_usage:
        answer['usage'] = usage
    return answer


class FakeUpstream:
    """One declared family's fake provider on 127.0.0.1:<ephemeral>. Behaviour by the request body:
    stream true answers SSE (chunked, one write per event), else JSON with a Content-Length; model
    'syn-no-usage' answers without usage; 'syn-error' answers 500; 'syn-gated' streams its first event, then
    waits for the test's release (no sleep) before the rest."""

    def __init__(self, family: str):
        self.family = family
        self.requests = []
        self.release = threading.Event()
        self.first_sent = threading.Event()
        upstream = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('content-length') or 0))
                upstream.requests.append({'method': self.command, 'path': self.path,
                                          'headers': list(self.headers.items()), 'body': body})
                document = json.loads(body)
                model = document.get('model')
                if model == 'syn-error':
                    data = json.dumps({'error': {'message': 'synthetic upstream error'}}).encode()
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                with_usage = model != 'syn-no-usage'
                if not document.get('stream'):
                    data = json.dumps(json_answer(upstream.family, with_usage=with_usage)).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('X-Synthetic-Upstream', upstream.family)
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                events = usage_events(upstream.family, with_usage=with_usage)
                for index, (name, event) in enumerate(events):
                    text = (f'event: {name}\n' if name else '') + f'data: {json.dumps(event)}\n\n'
                    data = text.encode()
                    self.wfile.write(b'%x\r\n%s\r\n' % (len(data), data))
                    self.wfile.flush()
                    if index == 0 and model == 'syn-gated':
                        upstream.first_sent.set()
                        upstream.release.wait(30)  # a bound against a hang, released by the test
                if upstream.family != 'anthropic-messages':
                    data = b'data: [DONE]\n\n'
                    self.wfile.write(b'%x\r\n%s\r\n' % (len(data), data))
                self.wfile.write(b'0\r\n\r\n')

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.origin = f'http://127.0.0.1:{self.port}'
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01},
                                       daemon=True)
        self.thread.start()

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


# ---------------------------------------------------------------- brokers


def component(upstreams: dict, *, models=(MODEL_A, MODEL_B, 'syn-no-usage', 'syn-error', 'syn-gated'),
              provider=PROVIDER, **settings) -> dict:
    """components.inference_broker for the fake upstreams {family: origin}: ephemeral ports."""
    raw = {'control_port': 0, 'inference_port': 0, **settings, 'families': {}}
    for family, origin in upstreams.items():
        raw['families'][family] = {'provider': provider, 'upstream': origin, 'models': list(models)}
    return raw


class Rig:
    """One broker over a fixture integration store and audit directory in its own temporary directory (or a
    store shared by the rigs of one test module). Its clock is settable; connect stands in for connect_upstream
    when given."""

    def __init__(self, raw: dict | None, *, provider_key=(PROVIDER, KEY), connect=None, store_factory=None,
                 db: Path | None = None):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-inference-'))
        (self.tmp / 'logs').mkdir()
        self.db = db or self.tmp / 'integration.sqlite'   # db: a store several rigs of one module share
        self.clock = Clock()
        self.guard = IB.BrokerGuard()
        self.config = IB.load_config(raw, allow_ephemeral=True)
        self.journal = IB.Journal(store_factory or (lambda: STORE.open_store(self.db)), self.guard)
        self.audit = IB.AuditLog(self.tmp / 'logs', self.guard, clock=self.clock)
        key = None if provider_key is None else IB.ProviderKey(*provider_key, source=MemoryProvider.name)
        self.broker = IB.Broker(self.config, provider_key=key, journal=self.journal, audit=self.audit,
                                guard=self.guard, clock=self.clock, connect=connect)
        self.started = False

    def start(self):
        self.broker.start()
        self.started = True
        self.control = self.broker.listeners['control']['port']
        self.inference = self.broker.listeners['inference']['port']
        return self

    def close(self):
        if self.started:
            self.broker.stop()
        else:
            self.journal.close()
            self.audit.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def issue(self, family='openai-chat', models=(MODEL_A,), requests=10, tokens=1000, ttl=600, **overrides):
        body = {'conversation_id': new_id(), 'attempt_id': new_id(), 'family': family, 'models': list(models),
                'budget': {'requests': requests, 'tokens': tokens}, 'ttl_s': ttl, **overrides}
        return self.broker.issue(body)

    def audit_lines(self) -> list:
        return [json.loads(line) for line in self.audit.path.read_text(encoding='utf-8').splitlines()]

    def store_records(self, key):
        store = STORE.open_store(self.db)
        try:
            return store.get(key), store.events(key)
        finally:
            store.close()


def request(port: int, method: str, path: str, body=None, header_pairs=(), *, host=None, raw_body=None):
    """One HTTP request to 127.0.0.1:PORT; (status, headers, body bytes)."""
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
    try:
        data = raw_body if raw_body is not None else (None if body is None else json.dumps(body).encode())
        connection.putrequest(method, path, skip_host=host is not None, skip_accept_encoding=True)
        if host is not None:
            connection.putheader('Host', host)
        names = {name.lower() for name, _ in header_pairs}
        for name, value in header_pairs:
            connection.putheader(name, value)
        if data is not None and 'content-length' not in names and 'transfer-encoding' not in names:
            connection.putheader('Content-Length', str(len(data)))
        connection.endheaders(data)
        response = connection.getresponse()
        return response.status, dict((k.lower(), v) for k, v in response.getheaders()), response.read()
    finally:
        connection.close()


def control(rig: Rig, method: str, path: str, body=None, *, content_type='application/json', extra=()):
    pairs = ([('Content-Type', content_type)] if body is not None else []) + list(extra)
    status, _, data = request(rig.control, method, path, body, pairs)
    return status, json.loads(data)
