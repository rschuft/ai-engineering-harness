"""The ACP qualification create and its admission (plan leaf S-03.3, slice 2), offline.

S-03.3 qualifies the first ACP coding provider (Claude Code) through the inference broker with "a disposable
pinned create fixture" (the leaf's proof). That create is not a dispatch stage's: it carries an ACP
``agent_settings`` block and the create's ``secrets``, which the dispatcher's admission refuses for every real
stage (``dispatch_inputs.check_create_body``: the body must be the profile's pinned template, whose fields have
no ``secrets``; ``read_profile_artifact``: a pinned artifact lives under ``profiles/<id>/``). So the fixture lives
here, beside its own admission, and the two never meet (the Overseer's ruling on the slice plan's D-3).

* ``qualification/acp-claude-code-create.json``: the fixture, pinned by ``FIXTURE_SHA256``; four placeholders,
  the reserved conversation id, the approved model, the attempt token and the guest inference endpoint.
* ``qualification/acp-registry-claude-code-1.60.1.json``: the facts of the pinned OpenHands registry the fixture
  relies on, with the locked wheels' sha256 and the source lines, pinned by ``REGISTRY_SHA256``. The fixture's
  secret names and command are checked against it on every load.

``check_create`` admits exactly the fixture with its four values and refuses every other shape with a stable code
(``REFUSALS``): any field outside the fixture; ``agent_profile_id`` (a profile resolution would bring the server's
stored settings and MCP servers); tools, skills, plugins, hooks and MCP servers; another ``agent_kind`` or
``acp_server`` (``custom`` included); any ``acp_command`` but exactly ``["claude-agent-acp"]`` (an empty command is
the registry's ``npx`` form, which the SDK keeps when the wrapper is not found: the Owner's "Do not silently fall
back to runtime npx installation") and any ``acp_args``; secrets other than exactly the registry's two names, or of
any kind but ``StaticSecret`` (a ``LookupSecret`` makes the outer server fetch a URL the body names, finding F-2);
a provider-key-shaped value anywhere; an ``ANTHROPIC_API_KEY`` that is not one broker-issued attempt token, or that
token anywhere else; a model outside the family's configured allowlist; and any network destination but the
profile's guest inference endpoint. ``build_create`` fills the fixture and checks the result.

Standard library only (plus the broker's token and model grammars, loaded by path). Nothing here sends, reads a
credential or runs a process.
"""
from __future__ import annotations

import hashlib
import importlib.util
import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load(name: str, path: Path):
    """A sibling module, loaded by path (``python -I`` adds no script directory)."""
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


# The attempt token's shape and the model grammar are the broker's own (decision 0015 section 3.1).
broker = _load('aieh_inference_broker', REPO / 'integrations' / 'inference' / 'inference_broker.py')

FIXTURE_FORMAT = 'ai-engineering-harness/dispatch/acp-qualification-create/v1'
REGISTRY_FORMAT = 'ai-engineering-harness/dispatch/acp-registry-extract/v1'
REFUSAL_FORMAT = 'ai-engineering-harness/dispatch/acp-qualification-refusal/v1'
FIXTURE_PATH = 'integrations/dispatch/qualification/acp-claude-code-create.json'
FIXTURE_SHA256 = '44685659f22b1c75fd15a8c5b6bd9ded851baebdeca629d15c5363f657114de6'
REGISTRY_PATH = 'integrations/dispatch/qualification/acp-registry-claude-code-1.60.1.json'
REGISTRY_SHA256 = 'aa402bbb418fed47a86a377207511be6a7a4f03dd4ea1d7a77b4514438345574'
ACP_SERVER = 'claude-code'
PLACEHOLDERS = {'conversation_id': '{conversation_id}', 'acp_model': '{acp_model}',
                'attempt_token': '{attempt_token}', 'inference_endpoint': '{inference_endpoint}'}
UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
# Provider keys as the guest's P5 needles name them (sk-ant-..., sk-proj-..., any long sk-...).
PROVIDER_KEY_SHAPE = re.compile(r'sk-(?:ant|proj)-|sk-[A-Za-z0-9_-]{20,}')
# A field outside the fixture is always refused; its name only picks the code.
FIELD_CLASSES = (
    (re.compile(r'profile', re.IGNORECASE), 'AGENT_PROFILE_FORBIDDEN'),
    (re.compile(r'mcp', re.IGNORECASE), 'MCP_FORBIDDEN'),
    (re.compile(r'tool|skill|plugin|hook|agent_definition|agent_context|launch_addition', re.IGNORECASE),
     'TOOLS_FORBIDDEN'),
)

REFUSALS = {
    'FIXTURE_DRIFTED': 'the qualification fixture or the registry extract no longer has its pinned sha256',
    'FIXTURE_INVALID': 'the qualification fixture or the registry extract is not its strict JSON shape, or they '
                       'disagree',
    'ENDPOINT_UNDECLARED': 'the profile declares no single inference endpoint with an IPv4 address and a port',
    'MODEL_NOT_APPROVED': 'acp_model is not one identifier of the family\'s configured allowlist (an empty '
                          'allowlist, a wildcard or a name outside it)',
    'CONVERSATION_ID_MISMATCH': 'the create does not carry the reserved conversation id',
    'BODY_MALFORMED': 'the create body is not a JSON object, or agent_settings is not one',
    'BODY_FIELD_UNKNOWN': 'the create carries a field outside the qualification fixture',
    'AGENT_PROFILE_FORBIDDEN': 'the create names an agent profile: its resolution would bring the server\'s stored '
                               'settings and MCP servers',
    'TOOLS_FORBIDDEN': 'the create carries tools, skills, plugins, hooks, client tools, agent definitions or an '
                       'agent context',
    'MCP_FORBIDDEN': 'the create configures an MCP server',
    'ACP_SERVER_NOT_PINNED': 'agent_kind is not acp, or acp_server is not claude-code (custom is refused)',
    'ACP_COMMAND_NOT_PINNED': 'acp_command is not exactly ["claude-agent-acp"], or acp_args is not empty (an empty '
                              'command is the registry\'s npx form)',
    'SECRET_NAMES': 'secrets are not exactly the registry\'s ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL',
    'SECRET_KIND_FORBIDDEN': 'a secret is not a StaticSecret of exactly kind and value (a LookupSecret makes the '
                             'outer server fetch a URL the body names)',
    'SECRETS_ENCRYPTED': 'secrets_encrypted is not false',
    'SECRET_PROVIDER_KEY_SHAPED': 'a value in the create is shaped like a provider key',
    'SECRET_NOT_ATTEMPT_TOKEN': 'ANTHROPIC_API_KEY is not one broker-issued attempt token',
    'TOKEN_OUTSIDE_SECRET': 'an attempt token appears in the create outside ANTHROPIC_API_KEY',
    'DESTINATION_NOT_ENDPOINT': 'ANTHROPIC_BASE_URL is not the profile\'s guest inference endpoint, or the create '
                                'names another network destination',
    'BODY_NOT_FIXTURE': 'the create differs from the pinned qualification fixture',
}


class QualificationRefused(Exception):
    """A typed refusal of the qualification create; nothing is sent."""

    def __init__(self, code: str, detail: str):
        if code not in REFUSALS:
            raise ValueError(f'unknown refusal code {code!r}')
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}')

    def to_json(self) -> dict:
        return {'format': REFUSAL_FORMAT, 'code': self.code, 'meaning': REFUSALS[self.code], 'detail': self.detail}


def read_repository_file(path: str) -> bytes:
    return REPO.joinpath(*path.split('/')).read_bytes()


def _strict_object(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f'duplicate key {key!r}')
        data[key] = value
    return data


def _pinned(read: Callable[[str], bytes], path: str, sha256: str) -> dict:
    raw = read(path)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != sha256:
        raise QualificationRefused('FIXTURE_DRIFTED', f'{path} has sha256 {digest}, pinned {sha256}')
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_strict_object)
    except ValueError as exc:
        raise QualificationRefused('FIXTURE_INVALID', f'{path}: {type(exc).__name__}') from None
    if not isinstance(data, dict):
        raise QualificationRefused('FIXTURE_INVALID', f'{path} is not a JSON object')
    return data


def _strings(node, where=()):
    """Every key and string value of a JSON tree, with its location."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield where + (key, '#key'), key
            yield from _strings(value, where + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, where + (index,))
    elif isinstance(node, str):
        yield where, node


def _same(a, b) -> bool:
    """Equal as canonical JSON: types matter (2 is not 2.0, true is not 1)."""
    try:
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    except (TypeError, ValueError):
        return False


def _fill(node, values: dict):
    if isinstance(node, dict):
        return {key: _fill(value, values) for key, value in node.items()}
    if isinstance(node, list):
        return [_fill(value, values) for value in node]
    return values.get(node, node) if isinstance(node, str) else node


def load_fixture(read: Callable[[str], bytes] = read_repository_file) -> dict:
    """The fixture's body template, after both pins and their agreement are checked."""
    registry = _pinned(read, REGISTRY_PATH, REGISTRY_SHA256)
    fixture = _pinned(read, FIXTURE_PATH, FIXTURE_SHA256)
    facts = registry.get('facts')
    if registry.get('format') != REGISTRY_FORMAT or registry.get('acp_server') != ACP_SERVER \
            or not isinstance(facts, dict):
        raise QualificationRefused('FIXTURE_INVALID', f'the registry extract is not {REGISTRY_FORMAT} of {ACP_SERVER}')
    body = fixture.get('body')
    if fixture.get('format') != FIXTURE_FORMAT or fixture.get('placeholders') != list(PLACEHOLDERS.values()) \
            or not isinstance(body, dict):
        raise QualificationRefused('FIXTURE_INVALID', f'the fixture is not {FIXTURE_FORMAT} with its placeholders')
    found = [text for _, text in _strings(body) if text in PLACEHOLDERS.values()]
    if sorted(found) != sorted(PLACEHOLDERS.values()):
        raise QualificationRefused('FIXTURE_INVALID', 'each placeholder must appear in the body exactly once')
    settings, secrets = body.get('agent_settings') or {}, body.get('secrets') or {}
    names = [(facts.get(name) or {}).get('value') for name in ('api_key_env_var', 'base_url_env_var')]
    if settings.get('acp_server') != ACP_SERVER \
            or settings.get('acp_command') != [(facts.get('binary_name') or {}).get('value')] \
            or list(secrets) != names \
            or secrets[names[0]].get('value') != PLACEHOLDERS['attempt_token'] \
            or secrets[names[1]].get('value') != PLACEHOLDERS['inference_endpoint']:
        raise QualificationRefused('FIXTURE_INVALID', 'the fixture\'s command or secret names are not the registry '
                                   'extract\'s')
    return body


def inference_endpoint(profile) -> str:
    """The guest inference endpoint as a base URL, from the profile's one ``network.endpoints`` entry of class
    ``inference`` (decision 0015 section 4.1): ``http://<IPv4 literal>:<port>``."""
    endpoints = (profile.get('network') or {}).get('endpoints') if isinstance(profile, dict) else None
    entries = [e for e in endpoints or [] if isinstance(e, dict) and e.get('class') == 'inference']
    if len(entries) != 1:
        raise QualificationRefused('ENDPOINT_UNDECLARED', f'{len(entries)} inference endpoints declared')
    address, port = entries[0].get('guest_address'), entries[0].get('guest_port')
    try:
        literal = str(ipaddress.IPv4Address(address)) == address
    except ValueError:
        literal = False
    if not literal or type(port) is not int or not 1 <= port <= 65535:
        raise QualificationRefused('ENDPOINT_UNDECLARED', 'the inference endpoint needs an IPv4 literal and a port')
    return f'http://{address}:{port}'


def approved_model(model, approved_models) -> str:
    """``model`` when it is exactly one name of the family's configured allowlist (the broker's model grammar,
    which admits no wildcard character; no duplicate). The allowlist ships empty, so nothing is approved until the
    Owner names models."""
    names = list(approved_models) if isinstance(approved_models, (list, tuple)) else []
    if not all(isinstance(name, str) and broker.MODEL_NAME.fullmatch(name) for name in names) \
            or len(set(names)) != len(names):
        raise QualificationRefused('MODEL_NOT_APPROVED', 'no valid approved model list')
    if model not in names:
        raise QualificationRefused('MODEL_NOT_APPROVED', 'acp_model is not in the approved list')
    return model


def _field_code(key) -> str:
    for pattern, code in FIELD_CLASSES:
        if pattern.search(str(key)):
            return code
    return 'BODY_FIELD_UNKNOWN'


def _location(where) -> str:
    return '.'.join(str(part) for part in where)


def check_create(body, *, conversation_id: str, approved_models, profile,
                 read: Callable[[str], bytes] = read_repository_file) -> None:
    """Refuse a qualification create that is not exactly the pinned fixture with the reserved conversation id,
    one approved model, one attempt token and the profile's guest inference endpoint."""
    template = load_fixture(read)
    endpoint = inference_endpoint(profile)
    if not isinstance(conversation_id, str) or not UUID_RE.fullmatch(conversation_id):
        raise QualificationRefused('CONVERSATION_ID_MISMATCH', 'the reserved conversation id is not a uuid')
    if not isinstance(body, dict):
        raise QualificationRefused('BODY_MALFORMED', 'the create body is not a JSON object')
    for key in body:
        if key not in template:
            raise QualificationRefused(_field_code(key), f'the create may not carry {key!r}')
    if body.get('conversation_id') != conversation_id:
        raise QualificationRefused('CONVERSATION_ID_MISMATCH', f'the create must carry {conversation_id}')
    settings = body.get('agent_settings')
    if not isinstance(settings, dict):
        raise QualificationRefused('BODY_MALFORMED', 'agent_settings is not an object')
    for key in settings:
        if key not in template['agent_settings']:
            raise QualificationRefused(_field_code(key), f'agent_settings may not carry {key!r}')
    if settings.get('agent_kind') != 'acp' or settings.get('acp_server') != ACP_SERVER:
        raise QualificationRefused('ACP_SERVER_NOT_PINNED', f'agent_kind acp and acp_server {ACP_SERVER} only')
    command = settings.get('acp_command', [])
    if command != template['agent_settings']['acp_command'] or settings.get('acp_args', []) != []:
        detail = 'an empty acp_command is the registry\'s npx form' if command == [] else \
            'acp_command must be exactly ["claude-agent-acp"] with no acp_args'
        raise QualificationRefused('ACP_COMMAND_NOT_PINNED', detail)
    if settings.get('mcp_config', {}) != {}:
        raise QualificationRefused('MCP_FORBIDDEN', 'mcp_config must be empty')
    model = approved_model(settings.get('acp_model'), approved_models)
    secrets, names = body.get('secrets'), list(template['secrets'])
    if not isinstance(secrets, dict) or sorted(secrets) != sorted(names):
        raise QualificationRefused('SECRET_NAMES', f'secrets must be exactly {names}')
    for name in names:
        source = secrets[name]
        if not isinstance(source, dict) or set(source) != {'kind', 'value'} or source['kind'] != 'StaticSecret' \
                or not isinstance(source['value'], str):
            raise QualificationRefused('SECRET_KIND_FORBIDDEN', f'{name} must be a StaticSecret of kind and value')
    if body.get('secrets_encrypted') is not False:
        raise QualificationRefused('SECRETS_ENCRYPTED', 'secrets_encrypted must be false')
    token_name, endpoint_name = names
    token_at, endpoint_at = ('secrets', token_name, 'value'), ('secrets', endpoint_name, 'value')
    texts = list(_strings(body))
    for where, text in texts:
        if PROVIDER_KEY_SHAPE.search(text) and not broker.TOKEN_SHAPE.fullmatch(text):
            raise QualificationRefused('SECRET_PROVIDER_KEY_SHAPED', f'at {_location(where)}')
    token = secrets[token_name]['value']
    if not broker.TOKEN_SHAPE.fullmatch(token):
        raise QualificationRefused('SECRET_NOT_ATTEMPT_TOKEN', f'{token_name} is not an attempt token')
    body_of_token = token[len(broker.TOKEN_PREFIX):]
    for where, text in texts:
        if where != token_at and (body_of_token in text or broker.TOKEN_SHAPE.search(text)):
            raise QualificationRefused('TOKEN_OUTSIDE_SECRET', f'at {_location(where)}')
    for where, text in texts:
        if where != endpoint_at and ('://' in text or text.startswith('//')):
            raise QualificationRefused('DESTINATION_NOT_ENDPOINT', f'a destination at {_location(where)}')
    if secrets[endpoint_name]['value'] != endpoint:
        raise QualificationRefused('DESTINATION_NOT_ENDPOINT', f'{endpoint_name} must be {endpoint}')
    expected = _fill(template, {PLACEHOLDERS['conversation_id']: conversation_id, PLACEHOLDERS['acp_model']: model,
                                PLACEHOLDERS['attempt_token']: token, PLACEHOLDERS['inference_endpoint']: endpoint})
    for key in expected:
        if key not in body or not _same(body[key], expected[key]):
            raise QualificationRefused('BODY_NOT_FIXTURE', f'{key} differs from the pinned fixture')


def build_create(*, conversation_id: str, attempt_token: str, acp_model: str, approved_models, profile,
                 read: Callable[[str], bytes] = read_repository_file) -> dict:
    """The qualification create: the pinned fixture with its four values, checked by ``check_create``."""
    template = load_fixture(read)
    body = _fill(template, {PLACEHOLDERS['conversation_id']: conversation_id, PLACEHOLDERS['acp_model']: acp_model,
                            PLACEHOLDERS['attempt_token']: attempt_token,
                            PLACEHOLDERS['inference_endpoint']: inference_endpoint(profile)})
    check_create(body, conversation_id=conversation_id, approved_models=approved_models, profile=profile, read=read)
    return body
