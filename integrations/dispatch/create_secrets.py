"""The create's secrets block, checked: one check shared by S-03.3's qualification admission and the dispatcher's
D1 stage (plan leaves S-03.3 and E-05.6; decision 0015 amendment 1 item 2).

The pinned OpenHands create carries an ACP agent's inference credentials in its ``secrets``: under the pinned
registry entry's ``api_key_env_var`` the attempt token the inference broker issued, under its ``base_url_env_var``
the profile's guest inference endpoint, each a ``StaticSecret`` of exactly ``kind`` and ``value``, with
``secrets_encrypted`` false. ``check_secrets`` refuses every other shape with a stable code (``MEANINGS``):

* the names are not exactly the registry entry's two (an ``OH_`` name, another provider's or a missing one):
  SECRET_NAMES;
* a secret is not a ``StaticSecret`` of exactly kind and value (a ``LookupSecret`` makes the outer server fetch a
  URL the body names): SECRET_KIND_FORBIDDEN;
* ``secrets_encrypted`` is not false: SECRETS_ENCRYPTED;
* a value anywhere in the body (keys included) is shaped like a provider key: SECRET_PROVIDER_KEY_SHAPED;
* the token secret is not one attempt token of the broker's shape: SECRET_NOT_ATTEMPT_TOKEN;
* given a ``binding``, the token is not the grant's, or the grant is not of the reserved conversation and attempt:
  SECRET_TOKEN_NOT_BOUND (the dispatcher's D1 stage, E-05.6; the qualification passes none);
* the token, or any part of it, appears anywhere but in its own secret: the whole token, its body after the
  prefix, any token-shaped text, or any run of FRAGMENT (8) or more consecutive characters of the token's body:
  TOKEN_OUTSIDE_SECRET (E-05.6, "the token, or any part of it"). Eight characters of the body's URL-safe
  alphabet carry 48 bits, so a chance match with the body's other text (the pinned template's fixed strings) is
  negligible, while any part long enough to help guess the token is refused;
* a network destination appears anywhere but in the endpoint secret, or that secret is not the endpoint:
  DESTINATION_NOT_ENDPOINT.

``acp_qualification.check_create`` and ``dispatch_inputs.check_create_body`` (the D1 stage) both call
``check_secrets`` of this one module, loaded under one name (``aieh_dispatch_create_secrets``): not a copy. Each
caller passes its own refusal type (``refused(code, detail)``), so the codes and their meanings are the same on both
sides.

A refusal's detail never carries the token, any part of it of FRAGMENT or more characters, or a word shaped like a
provider key, for either caller: every word of a reported location that holds one is ``REDACTED`` (``redact``).

Standard library only. The broker's token grammar and the fingerprint are the broker's own (decision 0015 section
3.1), loaded on first use: importing this module loads no inference or credential module.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Callable, Mapping

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

# The create fields that carry the secrets block.
SECRET_FIELDS = ('secrets', 'secrets_encrypted')
STATIC_SECRET = 'StaticSecret'
# Provider keys as the guest's P5 needles name them (sk-ant-..., sk-proj-..., any long sk-...).
PROVIDER_KEY_SHAPE = re.compile(r'sk-(?:ant|proj)-|sk-[A-Za-z0-9_-]{20,}')
# The shortest part of the token's body refused outside its secret: 8 characters of the URL-safe alphabet, 48 bits
# (module docstring).
FRAGMENT = 8
REDACTED = '<redacted>'
WORD = re.compile(r'[A-Za-z0-9_-]+')   # the token's and a provider key's characters: a word holds either whole
# The codes and their meanings, the same in acp_qualification.REFUSALS and dispatch_inputs.REFUSALS.
MEANINGS = {
    'SECRET_NAMES': 'secrets are not exactly the registry\'s ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL',
    'SECRET_KIND_FORBIDDEN': 'a secret is not a StaticSecret of exactly kind and value (a LookupSecret makes the '
                             'outer server fetch a URL the body names)',
    'SECRETS_ENCRYPTED': 'secrets_encrypted is not false',
    'SECRET_PROVIDER_KEY_SHAPED': 'a value in the create is shaped like a provider key',
    'SECRET_NOT_ATTEMPT_TOKEN': 'ANTHROPIC_API_KEY is not one broker-issued attempt token',
    'SECRET_TOKEN_NOT_BOUND': 'the attempt token is not the one the broker issued for the reserved conversation and '
                              'attempt (no grant is held, the token is another grant\'s, or the grant is of another '
                              'conversation or attempt)',
    'TOKEN_OUTSIDE_SECRET': 'an attempt token appears in the create outside ANTHROPIC_API_KEY',
    'DESTINATION_NOT_ENDPOINT': 'ANTHROPIC_BASE_URL is not the profile\'s guest inference endpoint, or the create '
                                'names another network destination',
}


def _load(name: str, path: Path):
    """A sibling module, loaded by path (``python -I`` adds no script directory)."""
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


def broker():
    """The inference broker's module (its token grammar and the fingerprint), loaded on first use."""
    return _load('aieh_inference_broker', REPO / 'integrations' / 'inference' / 'inference_broker.py')


def fingerprint(token: str) -> str:
    """The token's fingerprint, as the broker records it (sha256:<16 hex digits>)."""
    return broker().contract.fingerprint(token)


def strings(node, where=()):
    """Every key and string value of a JSON tree, with its location."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield where + (key, '#key'), key
            yield from strings(value, where + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from strings(value, where + (index,))
    elif isinstance(node, str):
        yield where, node


def fragments(token) -> frozenset:
    """Every run of FRAGMENT characters of an attempt token's body (empty for anything else)."""
    shapes = broker()
    if not isinstance(token, str) or not shapes.TOKEN_SHAPE.fullmatch(token):
        return frozenset()
    body = token[len(shapes.TOKEN_PREFIX):]
    return frozenset(body[i:i + FRAGMENT] for i in range(len(body) - FRAGMENT + 1))


def _holds_secret(text: str, parts: frozenset) -> bool:
    return bool(broker().TOKEN_SHAPE.search(text) or PROVIDER_KEY_SHAPE.search(text)
                or any(part in text for part in parts))


def redact(text: str, token=None) -> str:
    """TEXT with every word that holds an attempt token, a provider key's shape or a part of TOKEN of FRAGMENT or
    more characters replaced by REDACTED."""
    parts = fragments(token)
    return WORD.sub(lambda m: REDACTED if _holds_secret(m.group(), parts) else m.group(), text)


def location(where, token=None) -> str:
    """WHERE as a dotted path, redacted (``redact``): a key may hold what a refusal must not repeat."""
    return redact('.'.join(str(part) for part in where), token)


def _bound(token: str, binding: Mapping) -> str | None:
    """Why TOKEN is not bound to the reserved conversation and attempt, or None. BINDING: the grant the caller
    holds from the broker's issue answer (``token_fingerprint``, ``conversation_id``, ``attempt_id``; None when no
    grant is held) and the reserved ``conversation_id`` and ``attempt_id``."""
    grant = binding.get('grant')
    if not isinstance(grant, Mapping):
        return 'no grant is held for this attempt'
    if grant.get('token_fingerprint') != fingerprint(token):
        return 'the token is not the held grant\'s'
    if grant.get('conversation_id') != binding.get('conversation_id'):
        return 'the grant is bound to another conversation'
    if grant.get('attempt_id') != binding.get('attempt_id'):
        return 'the grant is bound to another attempt'
    return None


def check_secrets(body: dict, *, names, endpoint: str, refused: Callable[[str, str], Exception],
                  binding: Mapping | None = None) -> str:
    """Refuse a create BODY (a JSON object) whose secrets block is not exactly NAMES (the token's, then the
    endpoint's), each a StaticSecret, with secrets_encrypted false, the token one attempt token (bound, when a
    BINDING is given) and the endpoint ENDPOINT; raise ``refused(code, detail)``. Returns the token."""
    names = list(names)
    secrets = body.get('secrets')
    if not isinstance(secrets, dict) or sorted(secrets) != sorted(names):
        raise refused('SECRET_NAMES', f'secrets must be exactly {names}')
    for name in names:
        source = secrets[name]
        if not isinstance(source, dict) or set(source) != {'kind', 'value'} or source['kind'] != STATIC_SECRET \
                or not isinstance(source['value'], str):
            raise refused('SECRET_KIND_FORBIDDEN', f'{name} must be a StaticSecret of kind and value')
    if body.get('secrets_encrypted') is not False:
        raise refused('SECRETS_ENCRYPTED', 'secrets_encrypted must be false')
    shapes = broker()
    token_name, endpoint_name = names
    token_at, endpoint_at = ('secrets', token_name, 'value'), ('secrets', endpoint_name, 'value')
    token = secrets[token_name]['value']
    texts = list(strings(body))
    for where, text in texts:
        if PROVIDER_KEY_SHAPE.search(text) and not shapes.TOKEN_SHAPE.fullmatch(text):
            raise refused('SECRET_PROVIDER_KEY_SHAPED', f'at {location(where, token)}')
    if not shapes.TOKEN_SHAPE.fullmatch(token):
        raise refused('SECRET_NOT_ATTEMPT_TOKEN', f'{token_name} is not an attempt token')
    if binding is not None:
        why = _bound(token, binding)
        if why is not None:
            raise refused('SECRET_TOKEN_NOT_BOUND', why)
    body_of_token, parts = token[len(shapes.TOKEN_PREFIX):], fragments(token)
    for where, text in texts:
        if where != token_at and (body_of_token in text or shapes.TOKEN_SHAPE.search(text)
                                  or any(part in text for part in parts)):
            raise refused('TOKEN_OUTSIDE_SECRET', f'at {location(where, token)}')
    for where, text in texts:
        if where != endpoint_at and ('://' in text or text.startswith('//')):
            raise refused('DESTINATION_NOT_ENDPOINT', f'a destination at {location(where, token)}')
    if secrets[endpoint_name]['value'] != endpoint:
        raise refused('DESTINATION_NOT_ENDPOINT', f'{endpoint_name} must be {endpoint}')
    return token
