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

**The native profile** (decision 0023 section 3; plan leaves E-05.9 and E-05.11): ``check_native_secrets`` is the
one check of a native create's secrets and agent block, shared by the dispatcher's D1 stage on the native profile
(``dispatch_inputs``) and E-05.11's qualification admission (which calls this function, as S-03.3's admission
calls ``check_secrets``: not a copy). It admits exactly decision 0023's four names, each a ``StaticSecret`` of
exactly kind and value, with ``secrets_encrypted`` false: ``CLAUDE_CODE_OAUTH_TOKEN``, a value of the native
token's shape (``native_token.token_rule``); ``HTTPS_PROXY``, the profile's tunnel endpoint (``tunnel_endpoint``);
and the two switches with their declared spellings (``NATIVE_SWITCHES``). It refuses with stable codes
(``NATIVE_MEANINGS``) a mix of the native and brokered sets (NATIVE_SECRETS_MIXED); any other, additional or
missing name (NATIVE_SECRET_NAMES); another kind or shape (SECRET_KIND_FORBIDDEN, as E-05.6); ``secrets_encrypted``
not false (SECRETS_ENCRYPTED, as E-05.6); a token without the shape (NATIVE_TOKEN_NOT_SHAPED); the token, its body
after the public prefix or any run of FRAGMENT of its body's characters anywhere else (NATIVE_TOKEN_OUTSIDE_SECRET);
a second authentication method anywhere else in the body, an ``ANTHROPIC_API_KEY``, ``ANTHROPIC_BASE_URL`` or
``ANTHROPIC_AUTH_TOKEN`` name or another provider credential's value (NATIVE_SECOND_AUTH_METHOD); another proxy
endpoint, or another network destination anywhere (NATIVE_PROXY_NOT_TUNNEL); a switch value other than its declared
spelling (NATIVE_SWITCH_NOT_DECLARED); an MCP configuration (NATIVE_MCP_FORBIDDEN); an ACP server, command or
arguments other than the pinned ``claude-agent-acp`` (NATIVE_ACP_COMMAND_NOT_PINNED); and a setting that relocates
the per-conversation configuration directory (NATIVE_CONFIG_DIR_RELOCATED). Given the held token's fingerprint
(the D1 stage's), a token that is not the held one is NATIVE_TOKEN_NOT_HELD. The native token's grammar is
``native_token``'s, loaded on first use.
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


def native():
    """The native token's module (its grammar and fingerprint, E-05.9), loaded on first use: standard library only."""
    return _load('aieh_dispatch_native_token', HERE / 'native_token.py')


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


def body_fragments(body: str) -> frozenset:
    """Every run of FRAGMENT characters of BODY."""
    return frozenset(body[i:i + FRAGMENT] for i in range(len(body) - FRAGMENT + 1))


def fragments(token) -> frozenset:
    """Every run of FRAGMENT characters of an attempt token's body, or of a native token's body after its public
    prefix (E-05.9); empty for anything else."""
    if not isinstance(token, str):
        return frozenset()
    shapes = broker()
    if shapes.TOKEN_SHAPE.fullmatch(token):
        return body_fragments(token[len(shapes.TOKEN_PREFIX):])
    if native().is_token(token):
        return body_fragments(native().secret_body(token))
    return frozenset()


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


# ---------------------------------------------------------------------------
# The native profile (decision 0023 section 3; E-05.9, shared with E-05.11's qualification admission)

NATIVE_TOKEN_NAME = 'CLAUDE_CODE_OAUTH_TOKEN'
NATIVE_PROXY_NAME = 'HTTPS_PROXY'
# The switches' declared spelling (decision 0023 section 3: collision-free, never 1 or true; the SDK masks every
# secret value in the agent's output by substring). At the pinned CLI (claude 2.1.220) CLAUDE_CODE_PROXY_RESOLVES_HOSTS
# is read through its environment parser's bool, true for "1", "true", "yes" or "on" after lower-casing and
# trimming; CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC is read as any non-empty value, and its declared accessor is the
# same bool. "tRuE" is accepted by every reader of both, is neither "1" nor "true", and does not occur in the pinned
# CLI's own code and text (E-05.9's report gives the source locations).
SWITCH_SPELLING = 'tRuE'
NATIVE_SWITCHES = {'CLAUDE_CODE_PROXY_RESOLVES_HOSTS': SWITCH_SPELLING,
                   'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': SWITCH_SPELLING}
NATIVE_NAMES = (NATIVE_TOKEN_NAME, NATIVE_PROXY_NAME, *NATIVE_SWITCHES)
# The brokered profile's set: the pinned registry entry's two names (acp_qualification.registry_secret_names).
BROKERED_NAMES = ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL')
# A second authentication method (decision 0023 section 3): none of these is set on the native profile.
SECOND_AUTH_NAMES = ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN')
# The profile's tunnel endpoint (decision 0023 sections 3 and 4.4): one network.endpoints entry of this class, the
# docker0 gateway address and the tunnel's port. E-05.10 declares it in the profile, P7 and properties.json.
TUNNEL_CLASS = 'provider-tunnel'
TUNNEL_ADDRESS = '172.17.0.1'
# The pinned ACP block's run shape (decision 0023 section 3; the registry extract's claude-code entry).
PINNED_ACP = {'agent_kind': 'acp', 'acp_server': 'claude-code', 'acp_command': ['claude-agent-acp']}
# The per-conversation, empty configuration directory: the SDK's isolation on, and nothing that names the variable
# it sets (the SDK's ACPAgent overwrites CLAUDE_CONFIG_DIR when acp_isolate_data_dir is true, decision 0023).
ISOLATE_SETTING = 'acp_isolate_data_dir'
CONFIG_DIR_NAME = 'CLAUDE_CONFIG_DIR'
MCP_NAME = re.compile(r'mcp', re.IGNORECASE)
NATIVE_MEANINGS = {
    'NATIVE_SECRETS_MIXED': 'the create mixes the native secret set and the brokered one (ANTHROPIC_API_KEY, '
                            'ANTHROPIC_BASE_URL)',
    'NATIVE_SECRET_NAMES': 'secrets are not exactly CLAUDE_CODE_OAUTH_TOKEN, HTTPS_PROXY, '
                           'CLAUDE_CODE_PROXY_RESOLVES_HOSTS and CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC',
    'SECRET_KIND_FORBIDDEN': MEANINGS['SECRET_KIND_FORBIDDEN'],
    'SECRETS_ENCRYPTED': MEANINGS['SECRETS_ENCRYPTED'],
    'NATIVE_TOKEN_NOT_SHAPED': 'the native token is not a value of its shape (in CLAUDE_CODE_OAUTH_TOKEN or in its '
                               'entry)',
    'NATIVE_TOKEN_NOT_HELD': 'CLAUDE_CODE_OAUTH_TOKEN is not the token the dispatcher read from the native entry',
    'NATIVE_TOKEN_OUTSIDE_SECRET': 'the native token, or a part of it, appears in the create outside '
                                   'CLAUDE_CODE_OAUTH_TOKEN',
    'NATIVE_SECOND_AUTH_METHOD': 'the create carries a second authentication method (an ANTHROPIC_API_KEY, '
                                 'ANTHROPIC_BASE_URL or ANTHROPIC_AUTH_TOKEN, or another provider credential)',
    'NATIVE_PROXY_NOT_TUNNEL': 'HTTPS_PROXY is not the profile\'s tunnel endpoint, or the create names another '
                               'network destination',
    'NATIVE_SWITCH_NOT_DECLARED': 'a switch is not its declared spelling (never 1 or true)',
    'NATIVE_MCP_FORBIDDEN': 'the create configures an MCP server',
    'NATIVE_ACP_COMMAND_NOT_PINNED': 'the agent block is not the pinned ACP run shape: agent_kind acp, acp_server '
                                     'claude-code, acp_command exactly ["claude-agent-acp"], no acp_args',
    'NATIVE_CONFIG_DIR_RELOCATED': 'the create relocates the per-conversation configuration directory '
                                   '(acp_isolate_data_dir not true, or a CLAUDE_CONFIG_DIR setting)',
    'NATIVE_TUNNEL_UNDECLARED': 'the profile declares no single tunnel endpoint (class provider-tunnel) with the '
                                'docker0 gateway address 172.17.0.1 and a port',
}


def tunnel_endpoint(profile, *, refused: Callable[[str, str], Exception]) -> str:
    """The profile's tunnel endpoint, ``http://172.17.0.1:<port>``, from its one ``network.endpoints`` entry of class
    TUNNEL_CLASS (decision 0023 section 3); NATIVE_TUNNEL_UNDECLARED otherwise."""
    endpoints = (profile.get('network') or {}).get('endpoints') if isinstance(profile, dict) else None
    entries = [e for e in endpoints or [] if isinstance(e, dict) and e.get('class') == TUNNEL_CLASS]
    if len(entries) != 1:
        raise refused('NATIVE_TUNNEL_UNDECLARED', f'{len(entries)} {TUNNEL_CLASS} endpoints declared')
    address, port = entries[0].get('guest_address'), entries[0].get('guest_port')
    if address != TUNNEL_ADDRESS or type(port) is not int or not 1 <= port <= 65535:
        raise refused('NATIVE_TUNNEL_UNDECLARED', f'the tunnel endpoint needs guest_address {TUNNEL_ADDRESS} and a '
                                                  'port')
    return f'http://{address}:{port}'


def check_native_secrets(body: dict, *, endpoint: str, refused: Callable[[str, str], Exception],
                         held: str | None = None) -> str:
    """Refuse a native create BODY (a JSON object) unless its secrets block is exactly NATIVE_NAMES, each a
    StaticSecret, with secrets_encrypted false, the token of the native token's shape (the held one, when HELD, its
    fingerprint, is given) and nowhere else, no second authentication method, HTTPS_PROXY ENDPOINT and no other
    destination, each switch its declared spelling, and its agent block the pinned ACP run shape with no MCP
    configuration and the per-conversation configuration directory kept; raise ``refused(code, detail)``
    (NATIVE_MEANINGS). Returns the token."""
    secrets = body.get('secrets')
    names = set(secrets) if isinstance(secrets, dict) else set()
    if names & set(NATIVE_NAMES) and names & set(BROKERED_NAMES):
        raise refused('NATIVE_SECRETS_MIXED', 'the native and brokered secret sets are mixed')
    if not isinstance(secrets, dict) or sorted(secrets) != sorted(NATIVE_NAMES):
        raise refused('NATIVE_SECRET_NAMES', f'secrets must be exactly {list(NATIVE_NAMES)}')
    for name in NATIVE_NAMES:
        source = secrets[name]
        if not isinstance(source, dict) or set(source) != {'kind', 'value'} or source['kind'] != STATIC_SECRET \
                or not isinstance(source['value'], str):
            raise refused('SECRET_KIND_FORBIDDEN', f'{name} must be a StaticSecret of kind and value')
    if body.get('secrets_encrypted') is not False:
        raise refused('SECRETS_ENCRYPTED', 'secrets_encrypted must be false')
    grammar = native()
    token = secrets[NATIVE_TOKEN_NAME]['value']
    rule = grammar.token_rule(token)
    if rule is not None:
        raise refused('NATIVE_TOKEN_NOT_SHAPED', f'{NATIVE_TOKEN_NAME} is {grammar.rule_detail(rule)}')
    if held is not None and grammar.fingerprint(token) != held:
        raise refused('NATIVE_TOKEN_NOT_HELD', f'{NATIVE_TOKEN_NAME} is not the held token')
    token_at, proxy_at = ('secrets', NATIVE_TOKEN_NAME, 'value'), ('secrets', NATIVE_PROXY_NAME, 'value')
    secret, parts = grammar.secret_body(token), fragments(token)
    texts = list(strings(body))
    for where, text in texts:
        if where != token_at and (token in text or secret in text or any(part in text for part in parts)):
            raise refused('NATIVE_TOKEN_OUTSIDE_SECRET', f'at {location(where, token)}')
    for where, text in texts:
        if where != token_at and (PROVIDER_KEY_SHAPE.search(text) or 'sk-ant' in text
                                  or any(name in text for name in SECOND_AUTH_NAMES)):
            raise refused('NATIVE_SECOND_AUTH_METHOD', f'at {location(where, token)}')
    for where, text in texts:
        if where != proxy_at and ('://' in text or text.startswith('//')):
            raise refused('NATIVE_PROXY_NOT_TUNNEL', f'a destination at {location(where, token)}')
    if secrets[NATIVE_PROXY_NAME]['value'] != endpoint:
        raise refused('NATIVE_PROXY_NOT_TUNNEL', f'{NATIVE_PROXY_NAME} must be {endpoint}')
    for name, spelling in NATIVE_SWITCHES.items():
        if secrets[name]['value'] != spelling:
            raise refused('NATIVE_SWITCH_NOT_DECLARED', f'{name} must be its declared spelling')
    check_native_agent(body, refused=refused, token=token)
    return token


def check_native_agent(body: dict, *, refused: Callable[[str, str], Exception], token=None) -> None:
    """The agent block of a native create BODY (``check_native_secrets`` ends with it; the D1 stage also runs it on
    its pinned template before the token is read): no MCP configuration anywhere (NATIVE_MCP_FORBIDDEN), the pinned
    ACP run shape (NATIVE_ACP_COMMAND_NOT_PINNED) and the per-conversation configuration directory kept
    (NATIVE_CONFIG_DIR_RELOCATED). TOKEN, when given, is redacted from a refusal's location."""
    texts = list(strings(body))
    for where, _ in texts:
        if where and where[-1] == '#key' and MCP_NAME.search(str(where[-2])) \
                and where[:-1] != ('agent_settings', 'mcp_config'):
            raise refused('NATIVE_MCP_FORBIDDEN', f'at {location(where[:-1], token)}')
    settings = body.get('agent_settings')
    if isinstance(settings, dict) and settings.get('mcp_config', {}) != {}:
        raise refused('NATIVE_MCP_FORBIDDEN', 'agent_settings.mcp_config must be empty')
    if not isinstance(settings, dict) or any(settings.get(k) != v for k, v in PINNED_ACP.items()) \
            or settings.get('acp_args', []) != []:
        raise refused('NATIVE_ACP_COMMAND_NOT_PINNED', 'the agent block must be the pinned claude-agent-acp')
    if settings.get(ISOLATE_SETTING) is not True or any(CONFIG_DIR_NAME in text for _, text in texts):
        raise refused('NATIVE_CONFIG_DIR_RELOCATED', f'{ISOLATE_SETTING} must be true and nothing may set '
                                                     f'{CONFIG_DIR_NAME}')
