"""The native qualification create and its admission (plan leaf E-05.11; decision 0023), offline.

E-05.11 qualifies the pinned Claude Code on the native execution profile, as D1 runs it, with "a disposable pinned
qualification create refused for a real stage" (the leaf's action). That create carries the native secret set
(decision 0023 section 3: ``CLAUDE_CODE_OAUTH_TOKEN``, ``HTTPS_PROXY`` and the two switches), which the dispatcher's
admission refuses for every stage but D1 on the native profile, and its tag ends ``-disposable``, which the D1
stage refuses as its template (``dispatch_inputs``: STAGE_TEMPLATE_DISPOSABLE; ``read_profile_artifact`` reads only
``profiles/<id>/...``). So the fixture lives here, beside its own admission, as S-03.3's does
(``acp_qualification.py``), and the two never meet.

* ``qualification/native-claude-code-create.json``: the fixture, pinned by ``FIXTURE_SHA256``; three placeholders,
  the reserved conversation id, the native token and the profile's tunnel endpoint. Its ``acp_model`` is pinned in
  the file: the engineering manager's model record's primary, ``MODEL`` (evidence/D1-native-model-record.md).

``check_create`` admits exactly the fixture with its three values. The secrets block and the agent block are checked
first by the check shared with the dispatcher's D1 stage on the native profile (``create_secrets.check_native_secrets``
and, through it, ``check_native_agent``; E-05.9): one function of one module, loaded under one name, not a copy,
with this module's refusal type, so the codes and meanings are the same on both sides (``create_secrets.NATIVE_MEANINGS``).
Then, as ``dispatch_inputs.check_create_body`` closes them for D1 (E-05.9's review NIT-a, carried to E-05.11), the
nested objects are closed: ``workspace`` exactly the fixture's (WORKSPACE_NOT_FIXTURE), ``container`` only the
fixture's members at its values (a resource cap: CAPS_OVERRIDE_FORBIDDEN; any other: CONTAINER_NOT_FIXTURE), and
``tags`` exactly the fixture's (TAGS_NOT_FIXTURE); ``conversation_runtime`` docker (RUNTIME_NOT_DOCKER); the model the
recorded one (MODEL_NOT_RECORDED); every top-level field present (BODY_NOT_FIXTURE); and the whole body equal to the
filled fixture (BODY_NOT_FIXTURE). Given the held token's fingerprint (the driver's, from the dispatcher's read of
the entry), a token that is not the held one is NATIVE_TOKEN_NOT_HELD (the shared check's).

Standard library only. Nothing here reads a credential, sends, or runs a process; the native token's grammar is
``native_token``'s, loaded by the shared check on first use.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load(name: str, path: Path):
    """A sibling module, loaded by path under one name (``python -I`` adds no script directory)."""
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


# The native check, shared with the dispatcher's D1 stage on the native profile (E-05.9): one module, one name.
secrets_check = _load('aieh_dispatch_create_secrets', HERE / 'create_secrets.py')

FIXTURE_FORMAT = 'ai-engineering-harness/dispatch/native-qualification-create/v1'
REFUSAL_FORMAT = 'ai-engineering-harness/dispatch/native-qualification-refusal/v1'
FIXTURE_PATH = 'integrations/dispatch/qualification/native-claude-code-create.json'
FIXTURE_SHA256 = '03400881065df5acf31d8753294ef3dc1b2a4762f49585a5690db18f0cc25417'
# The engineering manager's model record (evidence/D1-native-model-record.md, "Primary"), approved with OA-31 (c1).
MODEL = 'claude-sonnet-5'
PLACEHOLDERS = {'conversation_id': '{conversation_id}', 'native_token': '{native_token}',
                'tunnel_endpoint': '{tunnel_endpoint}'}
UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
DOCKER_RUNTIME = 'docker'
CAP_NAME = re.compile(r'mem|cpu|pid|ulimit|shm|resource|limit|quota|swap', re.IGNORECASE)   # dispatch_inputs' class

REFUSALS = {
    'FIXTURE_DRIFTED': 'the native qualification fixture no longer has its pinned sha256',
    'FIXTURE_INVALID': 'the native qualification fixture is not its strict JSON shape (format, placeholders, the '
                       'native secret names, the recorded model)',
    'CONVERSATION_ID_MISMATCH': 'the create does not carry the reserved conversation id',
    'BODY_MALFORMED': 'the create body is not a JSON object, or a nested member is not one',
    'RUNTIME_NOT_DOCKER': 'conversation_runtime is not docker',
    'WORKSPACE_NOT_FIXTURE': 'workspace is not exactly the fixture\'s (LocalWorkspace at /workspace)',
    'CAPS_OVERRIDE_FORBIDDEN': 'container carries a resource cap: the qualification create sends none',
    'CONTAINER_NOT_FIXTURE': 'container carries a member outside the fixture, or one at another value',
    'TAGS_NOT_FIXTURE': 'tags is not exactly the fixture\'s',
    'MODEL_NOT_RECORDED': 'agent_settings.acp_model is not the model record\'s primary (' + MODEL + ')',
    'BODY_NOT_FIXTURE': 'the create differs from the pinned native qualification fixture',
    # The secrets and agent blocks' codes and meanings are the shared check's (create_secrets.NATIVE_MEANINGS), the
    # same in dispatch_inputs.REFUSALS.
    **secrets_check.NATIVE_MEANINGS,
}


class QualificationRefused(Exception):
    """A typed refusal of the native qualification create; nothing is sent. Its detail never carries the token."""

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
    """The fixture's body template, after its pin and shape are checked."""
    raw = read(FIXTURE_PATH)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != FIXTURE_SHA256:
        raise QualificationRefused('FIXTURE_DRIFTED', f'{FIXTURE_PATH} has sha256 {digest}, pinned {FIXTURE_SHA256}')
    try:
        fixture = json.loads(raw.decode('utf-8'), object_pairs_hook=_strict_object)
    except ValueError as exc:
        raise QualificationRefused('FIXTURE_INVALID', f'{FIXTURE_PATH}: {type(exc).__name__}') from None
    body = fixture.get('body') if isinstance(fixture, dict) else None
    if not isinstance(fixture, dict) or fixture.get('format') != FIXTURE_FORMAT or \
            fixture.get('placeholders') != list(PLACEHOLDERS.values()) or not isinstance(body, dict):
        raise QualificationRefused('FIXTURE_INVALID', f'the fixture is not {FIXTURE_FORMAT} with its placeholders')
    found = [text for _, text in secrets_check.strings(body) if text in PLACEHOLDERS.values()]
    if sorted(found) != sorted(PLACEHOLDERS.values()):
        raise QualificationRefused('FIXTURE_INVALID', 'each placeholder must appear in the body exactly once')
    secrets, settings = body.get('secrets'), body.get('agent_settings')
    if not isinstance(secrets, dict) or sorted(secrets) != sorted(secrets_check.NATIVE_NAMES) or \
            (secrets.get(secrets_check.NATIVE_TOKEN_NAME) or {}).get('value') != PLACEHOLDERS['native_token'] or \
            (secrets.get(secrets_check.NATIVE_PROXY_NAME) or {}).get('value') != PLACEHOLDERS['tunnel_endpoint'] or \
            not isinstance(settings, dict) or settings.get('acp_model') != MODEL:
        raise QualificationRefused('FIXTURE_INVALID', 'the fixture\'s secret names, slots or model are not the native '
                                   'set\'s and the model record\'s')
    return body


def check_create(body, *, conversation_id: str, profile, held: str | None = None,
                 read: Callable[[str], bytes] = read_repository_file) -> str:
    """Refuse a native qualification create that is not exactly the pinned fixture with the reserved conversation
    id, one native token (the held one, when HELD, its fingerprint, is given) and the profile's tunnel endpoint.
    Returns the token."""
    template = load_fixture(read)
    endpoint = secrets_check.tunnel_endpoint(profile, refused=QualificationRefused)
    if not isinstance(conversation_id, str) or not UUID_RE.fullmatch(conversation_id):
        raise QualificationRefused('CONVERSATION_ID_MISMATCH', 'the reserved conversation id is not a uuid')
    if not isinstance(body, dict):
        raise QualificationRefused('BODY_MALFORMED', 'the create body is not a JSON object')
    # The shared check: the secrets block, the agent block and the top-level allowlist (E-05.9, not a copy).
    token = secrets_check.check_native_secrets(body, endpoint=endpoint, refused=QualificationRefused, held=held)
    if body.get('conversation_id') != conversation_id:
        raise QualificationRefused('CONVERSATION_ID_MISMATCH', f'the create must carry {conversation_id}')
    if body.get('conversation_runtime') != DOCKER_RUNTIME or type(body.get('conversation_runtime')) is not str:
        raise QualificationRefused('RUNTIME_NOT_DOCKER', f'conversation_runtime must be {DOCKER_RUNTIME!r}')
    if body['agent_settings'].get('acp_model') != MODEL:
        raise QualificationRefused('MODEL_NOT_RECORDED', f'acp_model must be {MODEL}')
    # The nested objects, closed (review NIT-a of E-05.9, as check_create_body closes them for D1).
    if not _same(body.get('workspace'), template['workspace']):
        raise QualificationRefused('WORKSPACE_NOT_FIXTURE', f'workspace must be {template["workspace"]}')
    container = body.get('container', template['container'])
    if not isinstance(container, dict):
        raise QualificationRefused('BODY_MALFORMED', 'container is not an object')
    for key, value in container.items():
        if key not in template['container']:
            code = 'CAPS_OVERRIDE_FORBIDDEN' if CAP_NAME.search(str(key)) else 'CONTAINER_NOT_FIXTURE'
            raise QualificationRefused(code, f'container may not carry {str(key)[:64]!r}')
        if not _same(value, template['container'][key]):
            raise QualificationRefused('CONTAINER_NOT_FIXTURE', f'container.{key} must be {template["container"][key]!r}')
    if 'container' in body and sorted(container) != sorted(template['container']):
        raise QualificationRefused('CONTAINER_NOT_FIXTURE', f'container must hold {sorted(template["container"])}')
    if not _same(body.get('tags'), template['tags']):
        raise QualificationRefused('TAGS_NOT_FIXTURE', f'tags must be {template["tags"]}')
    missing = sorted(set(template) - set(body))
    if missing:
        raise QualificationRefused('BODY_NOT_FIXTURE', f'the create lacks {missing}')
    expected = _fill(template, {PLACEHOLDERS['conversation_id']: conversation_id, PLACEHOLDERS['native_token']: token,
                                PLACEHOLDERS['tunnel_endpoint']: endpoint})
    for key in expected:
        if not _same(body[key], expected[key]):
            raise QualificationRefused('BODY_NOT_FIXTURE', f'{key} differs from the pinned fixture')
    return token


def build_create(*, conversation_id: str, native_token: str, profile, held: str | None = None,
                 read: Callable[[str], bytes] = read_repository_file) -> dict:
    """The native qualification create: the pinned fixture with its three values, checked by ``check_create``."""
    template = load_fixture(read)
    endpoint = secrets_check.tunnel_endpoint(profile, refused=QualificationRefused)
    body = _fill(template, {PLACEHOLDERS['conversation_id']: conversation_id,
                            PLACEHOLDERS['native_token']: native_token, PLACEHOLDERS['tunnel_endpoint']: endpoint})
    check_create(body, conversation_id=conversation_id, profile=profile, held=held, read=read)
    return body
