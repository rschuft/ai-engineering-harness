"""The dispatcher's live transport to the guest's Agent Server (plan leaf E-01.3.3; decision 0013 point 1 in its
bootstrap reading, the Overseer's ruling F-2 of 2026-11-11).

During bootstrap the dispatcher principal is the Owner's account acting through this package over
``tools/guest.py``'s ``GuestApi``, as the guest login the profile declares (``identity.guest_user``, ``agent``).
That login is the one that reads the management key, from its ``root:<login> 0440`` file in a ``root:<login> 0750``
directory (``provisioning.agent_server.session_key``; ruling R9 keeps the file where it is). The cut-over is the
code path: op-as-* on Work goes only through the dispatch module (``dispatch_inputs.AgentServerClient`` over this
transport). ``tools/guest.py``'s own probes keep their vantage. Separating an operator login from the dispatcher's
guest login waits for the dispatcher's own host identity, which no leaf builds (routed to the Owner).

``GuestTransport(api, profile, api_login=)`` is the transport seam of ``AgentServerClient``:
``transport(method, path, body)`` sends one request through ``api`` (a ``GuestApi``: SSH over the instance's
host-loopback forward with its per-instance key, the API probe run as the login in the guest) and returns
``{"status": <int>, "body": <parsed JSON or text>}``. It raises ``TransportError`` when there is no answer.

The key:

* is read in the guest only, by the API probe, from its file. It is never on a command line: the SSH command line
  and the guest python's arguments carry the key file's path, the listener and the request, never the key;
* never enters the host process. The probe sends it as ``X-Session-API-Key`` on the guest's loopback, redacts it
  from every answer and counts it, and an answer that carried it is refused here (``SECRET_IN_ANSWER``). This
  module never opens the host custody copy (``session_key.host_path``): that copy is the provision and inspect
  steps' fingerprint source, disclosed under decision 0013 point 6.

Every call with a body uses ``GuestApi``'s sealed form: the request travels in the probe's text on ssh's standard
input, never on a command line (D1 work design G2: a seed or a result command does not fit a command line, which
Windows caps near 32767 characters; before, only a body with ``secrets`` was sealed). The seal is the body's one
secret word when it carries ``secrets`` (the D1 create's attempt token, E-05.6; ``sealed_secret``), else a fresh
nonce. A bodyless call keeps the probe's argument form.

``calls`` records each call's method, path, status and seconds, and the sha256 of its canonical body
(``body_sha256``), never a body, a key or an answer. A body that carries ``secrets`` gets no digest (``None``): it
would fingerprint the secret with the body's known text (E-05.11 review N4, the engineering manager's ruling R7 of
2026-11-15 moving it from the driver into the transport).

``transport(method, path, body, deliver={"part", "name"})`` asks the API probe for the exchange delivery of that
call's answer (``tools/guest.py`` ``GuestApi``, D1 work design G2): the framed part of the answer's standard output
is written, exclusively and bounded, into the guest exchange under ``name``, and the answer carries only its
``delivered`` ``{"name", "sha256", "size"}`` (or ``{"error"}``), never the part's bytes. Standard library only; it
imports nothing of ``tools/guest.py`` unless ``for_instance`` is given that module.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import secrets
import sys
import time
from pathlib import Path

CALL_TIMEOUT_S = 600  # the per-request ceiling inside the guest (a create can take minutes)
DELIVERY_KEYS = ('part', 'name')
DELIVERED_KEYS = ('name', 'sha256', 'size')


def _native_token():
    """integrations/dispatch/native_token.py (standard library only), the native token's grammar: its length bound is
    the sealed word's (E-05.11 review item 4)."""
    name = 'aieh_dispatch_native_token'
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / 'native_token.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


# A secret GuestApi's sealed form takes (tools/guest.py SEALED_SECRET): one URL-safe word of 16 characters up to the
# native token's longest (native_token.TOKEN_LENGTH, 512; a broker attempt token is 52), so that on the D1 path on the
# native profile the token itself is sealed and redacted from the answer, never a nonce in its place (E-05.11 review
# item 4; before, a native token longer than 128 characters was sealed with a nonce and its echo not redacted).
SEALABLE = re.compile(r'[A-Za-z0-9_-]{16,%d}' % _native_token().TOKEN_LENGTH[1])
SHA256_HEX = re.compile(r'[0-9a-f]{64}')
# The declared custody of the management key that this transport requires, with the login put in.
CUSTODY_FIELDS = ('owner', 'group', 'mode', 'guest_dir_owner', 'guest_dir_group', 'guest_dir_mode')


class TransportError(Exception):
    """No usable answer: the request was not answered, the answer carried the key, or the declared custody is not
    the bootstrap one. ``code`` is stable."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}')


def body_sha256(body) -> str | None:
    """The sha256 of BODY's canonical JSON (sorted keys, no whitespace, UTF-8); None for no body."""
    if body is None:
        return None
    text = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def sealed_secret(body: dict) -> str:
    """The secret a sealed call of BODY redacts from its answer: the one value of ``body['secrets']`` that is a
    single URL-safe word (SEALABLE: an attempt token, or on the native profile the native token, up to 512 characters;
    the endpoint is a URL and the switches' spelling is shorter than 16), else a fresh nonce (the call is sealed all
    the same)."""
    secrets_block = body.get('secrets')
    values = [source.get('value') for source in (secrets_block.values() if isinstance(secrets_block, dict) else ())
              if isinstance(source, dict)]
    words = [v for v in values if isinstance(v, str) and SEALABLE.fullmatch(v)]
    return words[0] if len(words) == 1 else secrets.token_urlsafe(32)


def declared_custody(profile) -> dict:
    """The dispatcher's guest login and the management key's declared custody: the profile's ``identity.guest_user``
    is the key file's group, the file is ``root`` ``440`` and its directory ``root`` ``750`` of that group
    (decision 0013 point 1, bootstrap; ruling R9). Anything else is KEY_CUSTODY_UNDECLARED."""
    identity = profile.get('identity') if isinstance(profile, dict) else None
    login = identity.get('guest_user') if isinstance(identity, dict) else None
    provisioning = profile.get('provisioning') if isinstance(profile, dict) else None
    server = provisioning.get('agent_server') if isinstance(provisioning, dict) else None
    key = server.get('session_key') if isinstance(server, dict) else None
    if not isinstance(login, str) or not login or not isinstance(key, dict):
        raise TransportError('KEY_CUSTODY_UNDECLARED', 'the profile declares no guest login and session key')
    want = dict(zip(CUSTODY_FIELDS, ('root', login, '440', 'root', login, '750')))
    differs = sorted(k for k, v in want.items() if key.get(k) != v)
    path = key.get('guest_path')
    if differs or not isinstance(path, str) or not path.startswith('/'):
        raise TransportError('KEY_CUSTODY_UNDECLARED', f'the session key is not declared readable by {login!r} '
                             f'alone among the logins (root:{login} 0440 in root:{login} 0750): {differs or "path"}')
    return {'login': login, 'key_file': path, **want}


class GuestTransport:
    """``transport(method, path, body)`` for ``AgentServerClient`` over a ``GuestApi`` (module docstring)."""

    def __init__(self, api, profile, *, api_login: str, timeout: int = CALL_TIMEOUT_S):
        if not callable(api):
            raise TypeError('api must be callable as api(requests) (tools/guest.py GuestApi)')
        self.custody = declared_custody(profile)
        if api_login != self.custody['login']:
            raise TransportError('LOGIN_MISMATCH', f'the API channel runs as {api_login!r}, not as the login that '
                                 f'holds the key ({self.custody["login"]!r})')
        self.api, self.timeout, self.calls = api, timeout, []

    def __call__(self, method: str, path: str, body, *, deliver=None):
        request = {'method': method, 'path': path, 'timeout': self.timeout}
        if body is not None:
            request['json'] = body
        if deliver is not None:
            if not isinstance(deliver, dict) or sorted(deliver) != sorted(DELIVERY_KEYS)                     or not all(isinstance(deliver[k], str) for k in DELIVERY_KEYS) or body is None:
                raise TransportError('DELIVERY_INVALID', f'{method} {path}: an exchange delivery is {{part, name}} '
                                     'on a call with a body')
            request['deliver'] = {k: deliver[k] for k in DELIVERY_KEYS}
        carries_secrets = isinstance(body, dict) and 'secrets' in body
        # R7 (E-05.11 review N4): no digest of a body that carries secrets
        entry = {'method': method, 'path': path, 'body_sha256': None if carries_secrets else body_sha256(body),
                 'status': None}
        self.calls.append(entry)
        t0 = time.monotonic()
        try:
            if body is not None:
                # Every body goes sealed: the request travels in the probe's text on ssh's standard input, never in
                # an argument of ssh or of the guest's python3, where its size is capped and a refusal or a
                # TimeoutExpired would show it (E-05.6; D1 work design G2). The seal is the body's one URL-safe
                # secret value when it carries secrets (the token, then redacted from the answer), else a fresh nonce.
                data = self.api([request], secret=sealed_secret(body) if carries_secrets else secrets.token_urlsafe(32))
            else:
                data = self.api([request])
        except BaseException as exc:
            entry.update(error=type(exc).__name__, seconds=round(time.monotonic() - t0, 2))
            raise
        entry['seconds'] = round(time.monotonic() - t0, 2)
        responses = data.get('responses') if isinstance(data, dict) else None
        hits = data.get('session_key_occurrences') if isinstance(data, dict) else None
        if not isinstance(responses, list) or len(responses) != 1 or not isinstance(responses[0], dict) \
                or type(hits) is not int:
            entry['error'] = 'MALFORMED'
            raise TransportError('NO_ANSWER', f'{method} {path}: the API probe gave no single answer')
        if hits:
            entry['error'] = 'SECRET_IN_ANSWER'
            raise TransportError('SECRET_IN_ANSWER', f'{method} {path}: the answer carried the management key '
                                 f'({hits} occurrence(s), redacted in the guest); it is not used')
        response = responses[0]
        status = response.get('status')
        if type(status) is not int:
            entry['error'] = str(response.get('error') or 'no status')[:64]
            raise TransportError('NO_ANSWER', f'{method} {path}: not answered ({entry["error"]})')
        entry['status'] = status
        if deliver is None:
            return {'status': status, 'body': response.get('body')}
        delivered = response.get('delivered')
        if not (isinstance(delivered, dict) and (
                (sorted(delivered) == sorted(DELIVERED_KEYS) and delivered['name'] == deliver['name']
                 and isinstance(delivered['sha256'], str) and SHA256_HEX.fullmatch(delivered['sha256'])
                 and type(delivered['size']) is int and delivered['size'] >= 0)
                or (sorted(delivered) == ['error'] and isinstance(delivered['error'], str)))):
            delivered = {'error': 'MALFORMED'}
        else:
            delivered = {k: delivered[k] for k in sorted(delivered)}
        entry['delivered'] = delivered
        return {'status': status, 'body': response.get('body'), 'delivered': delivered}


def for_instance(guest, ctx, name: str, *, timeout: int = CALL_TIMEOUT_S) -> GuestTransport:
    """The live transport of the running provisioned instance NAME: ``guest`` is the loaded ``tools/guest.py``,
    ``ctx`` its ``Context``. ``guest.Ssh`` over the instance's host-loopback forward with its per-instance key, as
    ``guest.GUEST_API_LOGIN``, and ``guest.GuestApi`` on it."""
    _, record = guest.running_instance(ctx, name)
    if not record.get('provisioning'):
        raise TransportError('NOT_PROVISIONED', f'{name} was not created with --provision; it runs no Agent Server')
    ssh = guest.Ssh(ctx.profile, ctx.instance_dir(name), record['ports']['ssh'])
    return GuestTransport(guest.GuestApi(ssh, ctx.profile), ctx.profile, api_login=guest.GUEST_API_LOGIN,
                          timeout=timeout)
