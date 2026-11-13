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

A call whose body carries ``secrets`` (the D1 create's attempt token, E-05.6) uses ``GuestApi``'s sealed form: the
request travels in the probe's text on ssh's standard input, never on a command line (``sealed_secret``).

``calls`` records each call's method, path, status, seconds and the sha256 of its canonical body (``body_sha256``),
never a body, a key or an answer. Standard library only; it imports nothing of ``tools/guest.py`` unless
``for_instance`` is given that module.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time

CALL_TIMEOUT_S = 600  # the per-request ceiling inside the guest (a create can take minutes)
# A secret GuestApi's sealed form takes (tools/guest.py SEALED_SECRET): one URL-safe word of 16 to 128 characters.
SEALABLE = re.compile(r'[A-Za-z0-9_-]{16,128}')
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
    single URL-safe word of 16 to 128 characters (an attempt token; the endpoint is a URL), else a fresh nonce
    (the call is sealed all the same)."""
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

    def __call__(self, method: str, path: str, body):
        request = {'method': method, 'path': path, 'timeout': self.timeout}
        if body is not None:
            request['json'] = body
        entry = {'method': method, 'path': path, 'body_sha256': body_sha256(body), 'status': None}
        self.calls.append(entry)
        t0 = time.monotonic()
        try:
            if isinstance(body, dict) and 'secrets' in body:
                # E-05.6: a body that carries secrets (the D1 create's attempt token) goes sealed: the request
                # travels in the probe's text on ssh's standard input, never in an argument of ssh or of the
                # guest's python3, where a refusal or a TimeoutExpired would show it. The sealed secret is the
                # body's one URL-safe secret value (the token, then redacted from the answer), else a fresh nonce.
                data = self.api([request], secret=sealed_secret(body))
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
        return {'status': status, 'body': response.get('body')}


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
