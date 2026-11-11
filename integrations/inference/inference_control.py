"""The dispatcher's side of the inference broker (plan leaf S-03.2, slice 3; decision 0015 sections 3.2, 3.3,
4.3 and 4.4, as amended by its amendment 1).

During bootstrap tools/guest.py performs the dispatcher's role (decision 0013 point 1). It needs three things of
the broker, and this module is all of them:

- the two listener ports of components.inference_broker (config.yml, decision 0009), read through the broker's
  own configuration loader (dispatcher_ports): the forward session targets the inference listener only, and
  forward_target refuses the control listener's port and any port that is not the inference listener's;
- a call of the control listener on 127.0.0.1 (ControlClient): the broker's status, one grant's state by its
  token fingerprint, and revocation (decision 0015 section 3.3: the dispatcher revokes at attempt end). It
  issues nothing: issuance belongs to the typed create's change (A-01.2, E-03.1), not to this slice;
- the fingerprint of an attempt token (token_fingerprint), after checking its shape, so that a record carries
  the fingerprint and never the token.

It connects to 127.0.0.1 only, to the port it is given, and nowhere else; it reads no environment, no proxy
variable and no credential. Standard library only.
"""
from __future__ import annotations

import http.client
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent


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


broker = _load('aieh_inference_broker', HERE / 'inference_broker.py')

LOOPBACK = broker.LOOPBACK
CONTROL_TIMEOUT_S = 10
ANSWER_LIMIT = 1024 * 1024
CODES = {
    'CONFIG_INCOMPLETE': 'set control_port and inference_port in components.inference_broker of config.yml',
    'CONTROL_PORT_REFUSED': 'the control listener is never forwarded: give the inference listener\'s port',
    'FORWARD_PORT_REFUSED': 'forward only to components.inference_broker.inference_port',
    'TOKEN_SHAPE_INVALID': 'give the attempt token exactly as the broker issued it (aieh-inf- and 43 URL-safe '
                           'characters)',
    'CONTROL_UNREACHABLE': 'start the broker (an Owner act) and check components.inference_broker.control_port',
    'CONTROL_ANSWER_INVALID': 'the control listener did not answer as the broker does: check the port',
}


class ControlError(Exception):
    """A refusal with a stable code: one of CODES, or the broker's own refusal code (broker True)."""

    def __init__(self, code: str, detail: str, *, broker_code: bool = False, status: int | None = None):
        self.code, self.detail, self.broker_code, self.status = code, detail, broker_code, status
        remedy = broker.REMEDIES.get(code, '') if broker_code else CODES[code]
        super().__init__(f'{code}: {detail}. Remedy: {remedy}.')


def managed_component():
    """components.inference_broker of the managed config.yml (decision 0009), or None."""
    return broker.paths.resolve().components.get(broker.COMPONENT)


def dispatcher_ports(raw) -> dict:
    """{'control_port', 'inference_port'} of components.inference_broker, validated by the broker's loader."""
    try:
        config = broker.load_config(raw)
    except broker.InferenceError as exc:
        raise ControlError(exc.code, exc.detail, broker_code=True) from None
    if config.control_port is None or config.inference_port is None:
        raise ControlError('CONFIG_INCOMPLETE', 'a listener port is not configured')
    return {'control_port': config.control_port, 'inference_port': config.inference_port}


def forward_target(ports: dict, port=None) -> int:
    """The broker port a forward session may target: the inference listener's. A given PORT must be exactly it;
    the control listener's port is refused by name."""
    if port is None:
        return ports['inference_port']
    if port == ports['control_port']:
        raise ControlError('CONTROL_PORT_REFUSED', f'{port} is the control listener\'s port')
    if port != ports['inference_port']:
        raise ControlError('FORWARD_PORT_REFUSED', f'{port} is not the inference listener\'s port')
    return port


def token_fingerprint(token) -> str:
    """The fingerprint of an attempt token of the broker's shape (sha256:<16 hex digits>); the token itself is
    never returned or printed."""
    if not isinstance(token, str) or not broker.TOKEN_SHAPE.fullmatch(token):
        raise ControlError('TOKEN_SHAPE_INVALID', 'not an attempt token')
    return broker.contract.fingerprint(token)


class ControlClient:
    """Direct calls of the broker's control listener on 127.0.0.1:PORT (its Host exactly that, no Origin, JSON
    bodies), as decision 0015 section 4.3 admits them."""

    def __init__(self, port: int, timeout: float = CONTROL_TIMEOUT_S):
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ControlError('CONFIG_INCOMPLETE', 'the control port is not a port')
        self.port, self.timeout = port, timeout

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode('utf-8')
        connection = http.client.HTTPConnection(LOOPBACK, self.port, timeout=self.timeout)
        try:
            headers = {'Accept': 'application/json'}
            if data is not None:
                headers['Content-Type'] = 'application/json'
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            status, raw = response.status, response.read(ANSWER_LIMIT + 1)
        except OSError as exc:
            raise ControlError('CONTROL_UNREACHABLE', f'{LOOPBACK}:{self.port}: {type(exc).__name__}') from None
        finally:
            connection.close()
        try:
            payload = json.loads(raw.decode('utf-8')) if len(raw) <= ANSWER_LIMIT else None
        except (UnicodeDecodeError, ValueError):
            payload = None
        if not isinstance(payload, dict):
            raise ControlError('CONTROL_ANSWER_INVALID', f'HTTP {status}, not a JSON object', status=status)
        refusal = payload.get('aieh_refusal')
        if status >= 400 or refusal is not None:
            code = refusal.get('code') if isinstance(refusal, dict) else None
            if not isinstance(code, str) or code not in broker.CODES:
                raise ControlError('CONTROL_ANSWER_INVALID', f'HTTP {status} without a broker refusal code',
                                   status=status)
            raise ControlError(code, str(refusal.get('detail', ''))[:300], broker_code=True, status=status)
        return payload

    def status(self) -> dict:
        return self.call('GET', '/v1/status')

    def grant(self, fingerprint: str) -> dict:
        if not isinstance(fingerprint, str) or not broker.FINGERPRINT_SHAPE.fullmatch(fingerprint):
            raise ControlError('TOKEN_SHAPE_INVALID', 'not a token fingerprint')
        return self.call('GET', f'/v1/grants/{fingerprint}')

    def revoke(self, fingerprint: str, trigger: str, revoker: str) -> dict:
        return self.call('POST', '/v1/grants/revoke', {'token_fingerprint': fingerprint, 'trigger': trigger,
                                                       'revoker': revoker})
