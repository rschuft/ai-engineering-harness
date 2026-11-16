"""Shared fixtures of the Integration process's tests (plan leaf U-01.3).

Everything here is throwaway: every credential is minted in process for one test and enrolled in a conversation
store under a temporary directory, never the managed data root's. The credential shapes of the security inventory
are built at run time from their grammars (no credential-shaped literal is committed).
"""
from __future__ import annotations

import asyncio
import datetime
import importlib.util
import json
import re
import secrets
import shutil
import string
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
REPO = HERE.parents[2]


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


S = _load('aieh_ownerhost_session', PACKAGE / 'session.py')
CS = _load('aieh_conversation_store', REPO / 'integrations' / 'conversation' / 'conversation_store.py')
A = _load('aieh_ownerhost_app', PACKAGE / 'app.py')
E = _load('aieh_ownerhost_enroll', PACKAGE / 'enroll.py')

HOST = ('host', f'{A.LOOPBACK}:{A.PORT}')
SHELL_ORIGIN = 'http://127.0.0.1:5173'
WAIT_CEILING_S = 120          # bounds a hang of a child process; each normally ends within seconds
INVENTORY = json.loads((REPO / 'security' / 'inventory.json').read_text(encoding='utf-8'))


def stamp(moment: datetime.datetime) -> str:
    return moment.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def utc(*args) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=datetime.timezone.utc)


class Scratch:
    """A temporary directory with a conversation store in it; close() removes both."""

    def __init__(self, prefix='aieh-ownerhost-'):
        self.dir = Path(tempfile.mkdtemp(prefix=prefix))
        self.store = CS.open_store(self.dir / CS.DB_NAME)

    def enroll(self, *, at: datetime.datetime, hours: int = 12):
        return E.enroll(self.store, hours=hours, clock=lambda: at)

    def dump(self) -> bytes:
        return self.store.canonical_dump()

    def close(self):
        self.store.close()
        shutil.rmtree(self.dir, ignore_errors=True)


# ---------------------------------------------------------------- driving the ASGI application in process


async def _call(app, method, path, headers, body=b'', query=b''):
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': 'http',
             'path': path, 'raw_path': path.encode('ascii'), 'query_string': query, 'root_path': '',
             'headers': [(k.lower().encode('latin-1'), v.encode('latin-1') if isinstance(v, str) else v)
                         for k, v in headers],
             'client': ('127.0.0.1', 50000), 'server': (A.LOOPBACK, A.PORT), 'state': {}}
    sent, delivered = [], []

    async def receive():
        if delivered:
            return {'type': 'http.disconnect'}
        delivered.append(True)
        return {'type': 'http.request', 'body': body, 'more_body': False}

    async def send(message):
        sent.append(message)
    await app(scope, receive, send)
    start = next(m for m in sent if m['type'] == 'http.response.start')
    headers = [(k.decode('latin-1').lower(), v.decode('latin-1')) for k, v in start.get('headers', [])]
    data = b''.join(m.get('body', b'') for m in sent if m['type'] == 'http.response.body')
    return start['status'], headers, data


def call(app, method, path, headers=(HOST,), **kw):
    """(status, [(header, value)], body) of one request to APP, run on a new event loop."""
    return asyncio.run(_call(app, method, path, list(headers), **kw))


def call_websocket(app, path, headers=(HOST,)):
    """The messages APP sends for a websocket connection attempt."""
    async def run():
        scope = {'type': 'websocket', 'asgi': {'version': '3.0'}, 'scheme': 'ws', 'path': path,
                 'raw_path': path.encode(), 'query_string': b'', 'root_path': '',
                 'headers': [(k.encode(), v.encode()) for k, v in headers], 'client': ('127.0.0.1', 50000),
                 'server': (A.LOOPBACK, A.PORT), 'subprotocols': [], 'state': {}}
        sent = []

        async def receive():
            return {'type': 'websocket.connect'}

        async def send(message):
            sent.append(message)
        await app(scope, receive, send)
        return sent
    return asyncio.run(run())


def code_of(body: bytes):
    try:
        return json.loads(body).get('code')
    except ValueError:
        return None


# ---------------------------------------------------------------- the inventory's credential shapes

URLSAFE = string.ascii_letters + string.digits + '-_'
ALNUM = string.ascii_letters + string.digits


def _draw(alphabet: str, count: int) -> str:
    return ''.join(secrets.choice(alphabet) for _ in range(count))


def _hex(count: int) -> str:
    return secrets.token_hex(count // 2)


def _jwt() -> str:
    def part(n):
        return _draw(URLSAFE, n)
    return '.'.join(('ey' + part(34), 'ey' + part(80), part(43)))


def _pem() -> str:
    tag = ' '.join(('OPENSSH', 'PRIVATE', 'KEY'))
    return f'-----BEGIN {tag}-----\n{_draw(ALNUM + "+/", 70)}\n-----END {tag}-----\n'


# Every credential of security/inventory.json but the Owner UI session credential itself: a generator of a value of
# its shape, or None with the reason it has no value that could be presented in a header. The shapes are the
# harness's own grammars (integrations/inference/inference_broker.py TOKEN_SHAPE, integrations/dispatch/native_token.py,
# the Agent Server's secrets.token_urlsafe(32) keys, Gitea's 40-hexadecimal tokens) and the providers' documented
# prefixes.
SHAPES = {
    'cred-uac-consent': None,                                                  # an interactive consent, no value
    'cred-owner-github': lambda: 'ghp_' + _draw(ALNUM, 36),
    'cred-owner-provider-login': lambda: 'sk-' + 'ant-oat01-' + _draw(URLSAFE, 95),
    'cred-guest-ssh-key': _pem,
    'cred-guest-host-keys': _pem,
    'cred-agent-server-session-key': lambda: _draw(URLSAFE, 43),
    'cred-oh-secret-key': lambda: _draw(URLSAFE, 43),
    'cred-conversation-keys': lambda: _draw(URLSAFE, 43),
    'cred-moby-docker-group': None,                                            # a group membership, no value
    'cred-gitea-owner-account': lambda: _draw(URLSAFE, 43),                    # gitea_host: token_urlsafe(32)
    'cred-gitea-admin': lambda: _draw(URLSAFE, 43),
    'cred-gitea-bot-builder': lambda: _hex(40),
    'cred-gitea-bot-planner': lambda: _hex(40),
    'cred-gitea-bot-reviewer': lambda: _hex(40),
    'cred-gitea-bot-ci': lambda: _hex(40),
    'cred-ci-job-token': lambda: _hex(40),
    'cred-ci-runtime-token': _jwt,
    'cred-runner-registration': lambda: _draw(ALNUM, 40),
    'cred-runner-token': lambda: _hex(40),
    'cred-verifier-read': lambda: _hex(40),
    'cred-gitea-protection-audit': lambda: _hex(40),
    'cred-executor-identity': lambda: _draw(URLSAFE, 43),                      # planned: no shape decided yet
    'cred-executor-target-secrets': lambda: _draw(URLSAFE, 64),                # planned: no shape decided yet
    'cred-llm-provider-key': lambda: 'sk-' + 'ant-api03-' + _draw(URLSAFE, 95),
    'cred-inference-attempt-token': lambda: 'aieh-' + 'inf-' + _draw(URLSAFE, 43),
    'cred-native-claude-code-token': lambda: 'sk-' + 'ant-oat01-' + _draw(URLSAFE, 95),
    'cred-conversation-runtime-access': lambda: _draw(URLSAFE, 43),
}
OWN = 'cred-owner-ui-session'
# Shapes the exposure scans look for, beside the throwaway credentials themselves.
SCAN_SHAPES = (
    S.SHAPE,                                                           # cred-owner-ui-session
    re.compile(r'aieh-inf-[A-Za-z0-9_-]{43}'),                         # attempt tokens
    re.compile(r'sk-(?:ant|proj)-[A-Za-z0-9_-]{8,}'),                  # provider keys and the native token
    re.compile(r'gh[pousr]_[A-Za-z0-9]{36}'),                          # GitHub tokens
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),                 # private keys
)


def samples() -> dict:
    """{credential id: one fresh value of its shape} for every inventory credential that has a value."""
    return {cid: make() for cid, make in SHAPES.items() if make is not None}


def inventory_credential_ids() -> set:
    return {c['id'] for c in INVENTORY['credentials']}


def exposures(text: str, secrets_held) -> list[str]:
    """What TEXT holds of SECRETS_HELD (exact values) or of SCAN_SHAPES; [] when nothing."""
    found = [f'a held secret ({value[:9]}...)' for value in secrets_held if value and value in text]
    found += [f'shape {shape.pattern}' for shape in SCAN_SHAPES if shape.search(text)]
    return found
