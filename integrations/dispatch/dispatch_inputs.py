"""Trusted dispatch input resolution (plan leaf E-01.2.1, blueprint #execution-qualification).

Dispatch step 01 resolves the authoritative Work and profile before anything is reserved
or created: "Check Backlog readiness, accepted OpenSpec revision and executable
requirements; choose ... a qualified profile". This module is that step's trusted-side
resolver. It is pure: it reads, through injected sources, and changes nothing.

* **Input:** a dispatch request (``ai-engineering-harness/dispatch/request/v1``) that names
  identifiers only: the Work (a Backlog.md task id), the repository, the stage, the
  execution profile and the agent catalog pin. It never takes a path, a digest, a mount,
  a resource or a runtime choice; any field outside the five, or a value outside its
  identifier grammar, is a refusal, never ignored.
* **Approval source:** the approved-input manifest
  (``ai-engineering-harness/dispatch/approved-inputs/v1``), an authorization record that
  in live use lives under the managed data root's ``state`` category
  (``<state>/dispatch/approved-inputs.json``, decision 0009 points 1 and 2), never in the
  checkout and never in the request. ``load_manifest`` refuses a manifest inside or
  around the checkout.
* **Output:** a ``ResolvedInputs`` record: the design revision, the profile digest, the
  agent manifest digest, the policy digest and the planned workspace, with the manifest
  version and digest that approved them. ``attempt_identity()`` and ``intent()`` feed
  ``IntegrationStore.reserve_attempt`` directly. Otherwise a ``DispatchRefused`` with a
  stable code (``REFUSALS``), raised before any reservation and before any external call.

Check order (the first failing check refuses): the request; the repository; the stage;
the stage's binding; the profile's approval and binding; the catalog pin (required); the
profile file's digest and qualification; the Work's native readiness; the design
pointers and the accepted design revision; the ordinal. Every manifest check runs before
any file, Backlog.md or git read.

Command line (from the repository root)::

    python -I -B integrations/dispatch/dispatch_inputs.py check-manifest --manifest FILE
    python -I -B integrations/dispatch/dispatch_inputs.py manifest-path

``check-manifest`` validates a manifest file and prints a JSON report (exit 0 PASS,
1 FAIL, 2 could not run); it admits nothing. ``manifest-path`` prints where the live
manifest is expected under the managed data root; it creates and reads nothing there.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import dataclasses
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePath
import re
import sys
from typing import Callable, Mapping, Protocol, Sequence

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


store = _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')
readiness = _load('planning_readiness', REPO / 'integrations' / 'planning' / 'planning_readiness.py')
planning = readiness.adapter
paths = _load('aieh_paths', REPO / 'integrations' / 'paths' / 'aieh_paths.py')

REQUEST_FORMAT = 'ai-engineering-harness/dispatch/request/v1'
MANIFEST_SCHEMA = 'ai-engineering-harness/dispatch/approved-inputs/v1'
RESOLVED_FORMAT = 'ai-engineering-harness/dispatch/resolved-inputs/v1'
POLICY_FORMAT = 'ai-engineering-harness/dispatch/policy-inputs/v1'
REFUSAL_FORMAT = 'ai-engineering-harness/dispatch/refusal/v1'
CHECK_FORMAT = 'ai-engineering-harness/dispatch/manifest-check/v1'
PROFILE_SCHEMA = 'ai-engineering-harness/profiles/profile/v1'
INTENT_KEY = 'dispatchInputs'
MANIFEST_CATEGORY = 'state'           # aieh_paths category (persistent/, class B)
MANIFEST_COMPONENT = 'dispatch'       # the <component>/ layout of the state category
MANIFEST_NAME = 'approved-inputs.json'
MAX_MANIFEST_BYTES = 1 << 20
MAX_ID = 64
STAGES = store.STAGES

ID_RE = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
CHANGE_RE = re.compile(planning.CHANGE_ID)
COMMIT_RE = re.compile(planning.COMMIT)
SHA256_RE = re.compile(r'[0-9a-f]{64}')

REQUEST_FIELDS = ('format', 'work_id', 'repository', 'stage', 'profile', 'catalog_pin')
# Field names that try to choose what the resolver alone derives: a host path, a mount, a
# digest, a resource ceiling, a runtime, a revision or an ordinal. Any extra field is refused;
# these are named as overrides.
OVERRIDE_HINT = re.compile(
    r'path|dir|folder|workspace|worktree|mount|volume|bind|digest|sha|hash|checksum|runtime|docker|'
    r'image|container|cpu|memory|mem|ram|disk|resource|limit|ceiling|network|host|port|env|secret|'
    r'token|credential|ordinal|design|revision|commit|policy|manifest|conversation|attempt|agent|'
    r'skill|model|llm|tool', re.IGNORECASE)

REFUSALS = {
    'REQUEST_MALFORMED': 'the request is not a request/v1 object with its five identifier fields',
    'REQUEST_UNKNOWN_FIELD': 'the request carries a field outside the request/v1 contract',
    'REQUEST_OVERRIDE_FORBIDDEN': 'the request tries to supply a path, mount, digest, resource, runtime, '
                                  'revision or ordinal; the resolver derives these itself',
    'REQUEST_FIELD_INVALID': 'a request field is not an identifier of its grammar',
    'MANIFEST_PATH_INVALID': 'the manifest path is not an absolute path without . or .. parts',
    'MANIFEST_INSIDE_CHECKOUT': 'the manifest lies inside or contains the checkout; a live approval '
                                'record lives under the managed data root',
    'MANIFEST_MISSING': 'no approved-input manifest exists at the path',
    'MANIFEST_UNREADABLE': 'the manifest cannot be read as one UTF-8 file of at most 1 MiB',
    'MANIFEST_INVALID': 'the manifest fails its schema check',
    'REPOSITORY_NOT_APPROVED': 'the repository is not in the manifest',
    'STAGE_UNKNOWN': 'the stage is not in the integration store\'s stage set',
    'STAGE_NOT_BOUND': 'no binding approves this stage for this repository',
    'PROFILE_NOT_APPROVED': 'the profile is not in the manifest',
    'PROFILE_NOT_BOUND': 'the profile is approved but not bound to this repository and stage',
    'NO_APPROVED_CATALOG': 'the manifest approves no catalog pin, so no attempt can be admitted',
    'CATALOG_PIN_REQUIRED': 'the request names no catalog pin; an attempt needs an approved agent/Skill pin',
    'CATALOG_PIN_UNKNOWN': 'the catalog pin is not in the manifest',
    'CATALOG_PIN_NOT_BOUND': 'the catalog pin is approved but not bound to this repository and stage',
    'PROFILE_MISSING': 'the approved profile has no readable profile.json',
    'PROFILE_DRIFTED': 'the profile.json bytes no longer have the approved sha256',
    'PROFILE_INVALID': 'the profile.json is not this profile\'s profile/v1 declaration',
    'PROFILE_NOT_OPERATIONAL': 'the profile does not declare itself operational (contract C6)',
    'WORK_SOURCE_UNAVAILABLE': 'no Backlog.md source is available for the approved repository',
    'WORK_NOT_FOUND': 'Backlog.md lists no task with this id',
    'WORK_UNREADABLE': 'Backlog.md\'s task or readiness could not be read',
    'WORK_NOT_READY': 'Backlog.md does not report the task ready (blocked, missing, unknown or inconsistent)',
    'DESIGN_POINTER_ABSENT': 'the task carries no OpenSpec source pointer',
    'DESIGN_UNRESOLVED': 'a source pointer of the task does not resolve in the repository',
    'DESIGN_AMBIGUOUS': 'the task\'s source pointers pin more than one change or commit',
    'DESIGN_NOT_ACCEPTED': 'the manifest records no accepted revision of the task\'s OpenSpec change',
    'DESIGN_REVISION_MISMATCH': 'the task pins a revision other than the accepted one',
    'IDENTITY_INVALID': 'the resolved inputs do not form a valid attempt identity',
}


class DispatchRefused(Exception):
    """A typed refusal, raised before any reservation and before any external call."""

    def __init__(self, code: str, detail: str, **context):
        if code not in REFUSALS:
            raise ValueError(f'unknown refusal code {code!r}')
        self.code, self.detail, self.context = code, detail, context
        super().__init__(f'{code}: {detail}')

    def to_json(self) -> dict:
        return {'format': REFUSAL_FORMAT, 'code': self.code, 'meaning': REFUSALS[self.code],
                'detail': self.detail, 'context': self.context}


def _canonical(value) -> str:
    return store.storecore.canonical_json(value)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _is_id(value) -> bool:
    return isinstance(value, str) and len(value) <= MAX_ID and ID_RE.fullmatch(value) is not None


# ---------------------------------------------------------------------------
# The approved-input manifest

def check_manifest(data) -> list[tuple[str, str]]:
    """Schema problems of a parsed manifest, as (code, message); empty when it is valid.

    Shape (v1), every key required and no other key anywhere::

        {"schema": MANIFEST_SCHEMA, "version": <int >= 1>,
         "repositories": [{"id": ID}],
         "designs": [{"repository": ID, "change": CHANGE, "commit": FULL_COMMIT}],
         "profiles": [{"id": ID, "sha256": HEX64}],
         "catalog_pins": [{"id": ID, "repository": ID, "commit": FULL_COMMIT, "manifest_sha256": HEX64}],
         "bindings": [{"repository": ID, "stage": STAGE, "profiles": [ID, ...], "catalog_pins": [ID, ...]}]}
    """
    problems: list[tuple[str, str]] = []

    def add(code: str, message: str) -> None:
        problems.append((code, message))

    if not isinstance(data, dict):
        add('MANIFEST_SCHEMA', 'the manifest is not a JSON object')
        return problems
    top = ('schema', 'version', 'repositories', 'designs', 'profiles', 'catalog_pins', 'bindings')
    for key in data:
        if key not in top:
            add('MANIFEST_SCHEMA', f'unknown key {key!r}')
    for key in top:
        if key not in data:
            add('MANIFEST_SCHEMA', f'missing key {key!r}')
    if data.get('schema') != MANIFEST_SCHEMA:
        add('MANIFEST_SCHEMA', f'schema must be {MANIFEST_SCHEMA!r}')
    if 'version' in data and (type(data['version']) is not int or data['version'] < 1):
        add('MANIFEST_VERSION', 'version must be an integer of at least 1')

    shapes = {
        'repositories': {'id': 'id'},
        'designs': {'repository': 'id', 'change': 'change', 'commit': 'commit'},
        'profiles': {'id': 'id', 'sha256': 'sha256'},
        'catalog_pins': {'id': 'id', 'repository': 'id', 'commit': 'commit', 'manifest_sha256': 'sha256'},
        'bindings': {'repository': 'id', 'stage': 'stage', 'profiles': 'ids', 'catalog_pins': 'ids'},
    }
    entries: dict[str, list[dict]] = {}
    for section, shape in shapes.items():
        value = data.get(section)
        if section in data and not isinstance(value, list):
            add('MANIFEST_SCHEMA', f'{section} must be a list')
        entries[section] = []
        for index, entry in enumerate(value if isinstance(value, list) else []):
            where = f'{section}[{index}]'
            if not isinstance(entry, dict):
                add('MANIFEST_SCHEMA', f'{where} is not an object')
                continue
            for key in entry:
                if key not in shape:
                    add('MANIFEST_SCHEMA', f'{where}: unknown key {key!r}')
            valid = True
            for key, kind in shape.items():
                if key not in entry:
                    add('MANIFEST_SCHEMA', f'{where}: missing key {key!r}')
                    valid = False
                    continue
                field = entry[key]
                if kind == 'id' and not _is_id(field):
                    add('MANIFEST_ID_INVALID', f'{where}.{key} is not an identifier '
                                               f'([a-z0-9]+(-[a-z0-9]+)*, at most {MAX_ID})')
                    valid = False
                elif kind == 'change' and not (isinstance(field, str) and len(field) <= store.MAX_CHANGE_ID
                                               and CHANGE_RE.fullmatch(field)):
                    add('MANIFEST_ID_INVALID', f'{where}.{key} is not an OpenSpec change id')
                    valid = False
                elif kind == 'commit' and not (isinstance(field, str) and COMMIT_RE.fullmatch(field)):
                    add('MANIFEST_COMMIT_NOT_FULL', f'{where}.{key} is not a full commit id '
                                                    '(40 or 64 lower-case hex digits)')
                    valid = False
                elif kind == 'sha256' and not (isinstance(field, str) and SHA256_RE.fullmatch(field)):
                    add('MANIFEST_DIGEST_INVALID', f'{where}.{key} is not a sha256 (64 lower-case hex digits)')
                    valid = False
                elif kind == 'stage' and field not in STAGES:
                    add('MANIFEST_STAGE_UNKNOWN', f'{where}.{key} is not one of {STAGES}')
                    valid = False
                elif kind == 'ids':
                    if not isinstance(field, list) or not all(_is_id(item) for item in field):
                        add('MANIFEST_ID_INVALID', f'{where}.{key} must be a list of identifiers')
                        valid = False
                    elif len(set(field)) != len(field):
                        add('MANIFEST_DUPLICATE', f'{where}.{key} names an identifier twice')
            if valid:
                entries[section].append(entry)

    def unique(section: str, key: Callable[[dict], tuple]) -> None:
        seen = set()
        for entry in entries[section]:
            if key(entry) in seen:
                add('MANIFEST_DUPLICATE', f'{section}: {"/".join(key(entry))} appears twice')
            seen.add(key(entry))

    unique('repositories', lambda e: (e['id'],))
    unique('designs', lambda e: (e['repository'], e['change']))
    unique('profiles', lambda e: (e['id'],))
    unique('catalog_pins', lambda e: (e['id'],))
    unique('bindings', lambda e: (e['repository'], e['stage']))

    repositories = {e['id'] for e in entries['repositories']}
    profiles = {e['id'] for e in entries['profiles']}
    pins = {e['id'] for e in entries['catalog_pins']}
    for entry in entries['designs']:
        if entry['repository'] not in repositories:
            add('MANIFEST_UNKNOWN_REFERENCE', f'designs: {entry["repository"]!r} is not an approved repository')
    for entry in entries['bindings']:
        where = f'bindings {entry["repository"]}/{entry["stage"]}'
        if entry['repository'] not in repositories:
            add('MANIFEST_UNKNOWN_REFERENCE', f'{where}: {entry["repository"]!r} is not an approved repository')
        if not entry['profiles']:
            add('MANIFEST_SCHEMA', f'{where}: binds no profile')
        for name in entry['profiles']:
            if name not in profiles:
                add('MANIFEST_UNKNOWN_REFERENCE', f'{where}: profile {name!r} is not approved')
        for name in entry['catalog_pins']:
            if name not in pins:
                add('MANIFEST_UNKNOWN_REFERENCE', f'{where}: catalog pin {name!r} is not approved')
    return problems


def _strict_object(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError(f'duplicate object key among {sorted(keys)}')
    return dict(pairs)


def _no_constant(name):
    raise ValueError(f'non-standard JSON constant {name}')


@dataclass(frozen=True)
class ApprovedInputs:
    """A schema-checked approved-input manifest: its version, the sha256 of its bytes, its entries."""
    version: int
    sha256: str
    data_json: str  # canonical JSON of the parsed manifest; the object is never mutated

    @property
    def data(self) -> dict:
        return json.loads(self.data_json)

    def _index(self) -> dict:
        data = self.data
        return {
            'repositories': {e['id']: e for e in data['repositories']},
            'designs': {(e['repository'], e['change']): e for e in data['designs']},
            'profiles': {e['id']: e for e in data['profiles']},
            'catalog_pins': {e['id']: e for e in data['catalog_pins']},
            'bindings': {(e['repository'], e['stage']): e for e in data['bindings']},
        }


def parse_manifest(raw: bytes) -> ApprovedInputs:
    """Parse and schema-check manifest bytes; MANIFEST_UNREADABLE or MANIFEST_INVALID on failure."""
    if not isinstance(raw, bytes) or len(raw) > MAX_MANIFEST_BYTES:
        raise DispatchRefused('MANIFEST_UNREADABLE', f'the manifest must be at most {MAX_MANIFEST_BYTES} bytes')
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_strict_object, parse_constant=_no_constant)
    except UnicodeDecodeError:
        raise DispatchRefused('MANIFEST_UNREADABLE', 'the manifest is not UTF-8') from None
    except ValueError as exc:
        raise DispatchRefused('MANIFEST_INVALID', f'the manifest is not strict JSON: {exc}',
                              problems=[['MANIFEST_JSON', str(exc)]]) from None
    problems = check_manifest(data)
    if problems:
        raise DispatchRefused('MANIFEST_INVALID', f'{len(problems)} schema problem(s); first: '
                              f'{problems[0][0]}: {problems[0][1]}', problems=[list(p) for p in problems])
    return ApprovedInputs(data['version'], hashlib.sha256(raw).hexdigest(), _canonical(data))


def manifest_path(res=None) -> Path:
    """Where the live manifest is expected: ``<state>/dispatch/approved-inputs.json`` of the
    managed data root (decision 0009). Computes a path; creates and reads nothing there."""
    res = paths.resolve() if res is None else res
    return Path(str(res.paths[MANIFEST_CATEGORY])) / MANIFEST_COMPONENT / MANIFEST_NAME


def _overlaps(a: PurePath, b: PurePath) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def load_manifest(path, *, repo_root=REPO) -> ApprovedInputs:
    """Read the live manifest from an absolute path outside the checkout and schema-check it."""
    text = os.fspath(path) if isinstance(path, (str, os.PathLike)) else None
    candidate = Path(text) if text else None
    if candidate is None or not candidate.is_absolute() or any(part in ('.', '..') for part in candidate.parts):
        raise DispatchRefused('MANIFEST_PATH_INVALID', f'not an absolute path without . or .. parts: {path!r}')
    repo = Path(os.path.realpath(repo_root))
    if _overlaps(candidate, repo) or _overlaps(Path(os.path.realpath(candidate)), repo):
        raise DispatchRefused('MANIFEST_INSIDE_CHECKOUT', f'{candidate} is inside or contains the checkout')
    try:
        with open(candidate, 'rb') as handle:
            raw = handle.read(MAX_MANIFEST_BYTES + 1)
    except FileNotFoundError:
        raise DispatchRefused('MANIFEST_MISSING', f'no manifest at {candidate}') from None
    except OSError as exc:
        raise DispatchRefused('MANIFEST_UNREADABLE', f'{candidate}: {type(exc).__name__}') from None
    return parse_manifest(raw)


# ---------------------------------------------------------------------------
# Injected sources

class WorkSource(Protocol):
    """Backlog.md and git of one approved repository, read only."""

    def read(self, work_id: str) -> dict | None:
        """The task's planning-readiness/v1 entry with its resolved pointers, or None when
        Backlog.md lists no such task. Raises planning_adapter.PlanningError when unreadable."""


class PlanningWorkSource:
    """The planning adapter's native readiness read (P-02.2) over one repository's Backlog.md
    (``planning_adapter.Backlog`` or anything with ``list_tasks`` and ``view``) and git
    (``planning_adapter.Git``), which resolves every OpenSpec source pointer."""

    def __init__(self, backlog, git):
        self.backlog, self.git = backlog, git

    def read(self, work_id: str) -> dict | None:
        listed = [t['id'] for t in self.backlog.list_tasks() if t['id'].upper() == work_id.upper()]
        if not listed:
            return None
        report = readiness.read_readiness(self.backlog, self.git, [listed[0]])
        return report['tasks'][0]


def read_profile_file(profile_id: str, *, profiles_root=REPO / 'profiles') -> bytes:
    """The bytes of ``<profiles_root>/<id>/profile.json`` (checked out byte-exact: profiles/.gitattributes)."""
    if not _is_id(profile_id):
        raise ValueError(f'not a profile id: {profile_id!r}')
    return (Path(profiles_root) / profile_id / 'profile.json').read_bytes()


def store_next_ordinal(integration_store) -> Callable[[str, str, str], int]:
    """The next ordinal on (work, design revision, stage) from the store's typed claims (a read).
    ``reserve_attempt`` remains the arbiter: a live claim or a race is refused there."""
    def next_ordinal(work_id: str, design_revision: str, stage: str) -> int:
        claims = integration_store.claims(work_id, design_revision, stage)
        return max((c.identity.ordinal for c in claims), default=0) + 1
    return next_ordinal


# ---------------------------------------------------------------------------
# The resolved record

@dataclass(frozen=True)
class ResolvedInputs:
    """The resolved, immutable inputs of one attempt, ready for ``reserve_attempt``."""
    work_id: str
    repository: str
    stage: str
    ordinal: int
    design_revision: str
    profile: str
    profile_digest: str
    catalog_pin: str
    agent_manifest_digest: str
    planned_workspace: str
    policy_digest: str
    policy_inputs_json: str
    manifest_version: int
    manifest_sha256: str

    @property
    def policy_inputs(self) -> dict:
        return json.loads(self.policy_inputs_json)

    def attempt_identity(self):
        return store.AttemptIdentity(
            work_id=self.work_id, design_revision=self.design_revision, stage=self.stage, ordinal=self.ordinal,
            profile_digest=self.profile_digest, planned_workspace=self.planned_workspace,
            policy_digest=self.policy_digest, agent_manifest_digest=self.agent_manifest_digest)

    def to_json(self) -> dict:
        return {'format': RESOLVED_FORMAT, 'work_id': self.work_id, 'repository': self.repository,
                'stage': self.stage, 'ordinal': self.ordinal, 'design_revision': self.design_revision,
                'profile': self.profile, 'profile_digest': self.profile_digest,
                'catalog_pin': self.catalog_pin, 'agent_manifest_digest': self.agent_manifest_digest,
                'planned_workspace': self.planned_workspace, 'policy_digest': self.policy_digest,
                'policy_inputs': self.policy_inputs,
                'approval': {'manifest_schema': MANIFEST_SCHEMA, 'manifest_version': self.manifest_version,
                             'manifest_sha256': self.manifest_sha256}}

    def intent(self) -> dict:
        """The reservation intent: the record under ``dispatchInputs``. Its digest therefore covers
        the approval provenance, so a later audit ties the attempt to the manifest that approved it."""
        return {INTENT_KEY: self.to_json()}


def policy_inputs(repository: dict, stage: str, design: dict, profile: dict, catalog_pin: dict) -> dict:
    """What ``policy_digest`` covers: exactly the approved manifest entries this attempt was
    admitted under (the repository, the stage, the accepted design revision, the profile with its
    approved sha256, the catalog pin), under a format tag. Not the manifest's version or digest
    (provenance, carried beside it), not the binding lists, not the Work or the ordinal (the
    attempt identity). E-01.2.2 adds its workspace, mount, resource and runtime ceilings here."""
    return {'format': POLICY_FORMAT,
            'repository': {'id': repository['id']},
            'stage': stage,
            'design': {'repository': design['repository'], 'change': design['change'],
                       'commit': design['commit']},
            'profile': {'id': profile['id'], 'sha256': profile['sha256']},
            'catalog_pin': {'id': catalog_pin['id'], 'repository': catalog_pin['repository'],
                            'commit': catalog_pin['commit'], 'manifest_sha256': catalog_pin['manifest_sha256']}}


def planned_workspace(repository: str, work_id: str, attempt_id: str) -> str:
    """The fixed rule: ``<repository>/<work_id>/<attempt_id>``, relative to the managed root's
    ``workspaces`` category. Never from the caller; E-01.2.2 resolves and validates the host path."""
    return f'{repository}/{work_id}/{attempt_id}'


# ---------------------------------------------------------------------------
# Resolution

def parse_request(request) -> tuple[str, str, str, str, str]:
    """(work_id, repository, stage, profile, catalog_pin) of a request/v1, or a refusal."""
    if not isinstance(request, Mapping):
        raise DispatchRefused('REQUEST_MALFORMED', 'the request is not a JSON object')
    if not all(isinstance(key, str) for key in request):
        raise DispatchRefused('REQUEST_MALFORMED', 'a request key is not a string')
    extra = sorted(key for key in request if key not in REQUEST_FIELDS)
    overrides = [key for key in extra if OVERRIDE_HINT.search(key)]
    if overrides:
        raise DispatchRefused('REQUEST_OVERRIDE_FORBIDDEN', f'the request may not supply {overrides}',
                              fields=overrides)
    if extra:
        raise DispatchRefused('REQUEST_UNKNOWN_FIELD', f'unknown request fields {extra}', fields=extra)
    if request.get('format') != REQUEST_FORMAT:
        raise DispatchRefused('REQUEST_MALFORMED', f'format must be {REQUEST_FORMAT!r}')
    if request.get('catalog_pin') in (None, ''):
        raise DispatchRefused('CATALOG_PIN_REQUIRED', 'the request names no catalog pin')
    missing = [key for key in REQUEST_FIELDS if key not in request]
    if missing:
        raise DispatchRefused('REQUEST_MALFORMED', f'missing request fields {missing}', fields=missing)
    work_id = request['work_id']
    if not (isinstance(work_id, str) and len(work_id) <= store.MAX_WORK_ID
            and planning.TASK_ID_RE.fullmatch(work_id)):
        raise DispatchRefused('REQUEST_FIELD_INVALID', 'work_id is not a Backlog.md task id', field='work_id')
    for key in ('repository', 'stage', 'profile', 'catalog_pin'):
        if not _is_id(request[key]):
            raise DispatchRefused('REQUEST_FIELD_INVALID', f'{key} is not an identifier', field=key)
    return work_id.upper(), request['repository'], request['stage'], request['profile'], request['catalog_pin']


def _check_profile(profile_id: str, approved_sha256: str, read_profile: Callable[[str], bytes]) -> str:
    try:
        raw = read_profile(profile_id)
    except (OSError, ValueError) as exc:
        raise DispatchRefused('PROFILE_MISSING', f'{profile_id}: {type(exc).__name__}', profile=profile_id) from None
    if not isinstance(raw, bytes):
        raise DispatchRefused('PROFILE_MISSING', f'{profile_id}: the profile source returned no bytes')
    digest = hashlib.sha256(raw).hexdigest()
    if digest != approved_sha256:
        raise DispatchRefused('PROFILE_DRIFTED', f'{profile_id}/profile.json has sha256 {digest}, approved '
                              f'{approved_sha256}', profile=profile_id, actual=digest, approved=approved_sha256)
    try:
        declared = json.loads(raw.decode('utf-8'), object_pairs_hook=_strict_object, parse_constant=_no_constant)
    except ValueError as exc:  # UnicodeDecodeError is a ValueError
        raise DispatchRefused('PROFILE_INVALID', f'{profile_id}/profile.json: {type(exc).__name__}') from None
    if not isinstance(declared, dict) or declared.get('schema') != PROFILE_SCHEMA \
            or declared.get('name') != profile_id:
        raise DispatchRefused('PROFILE_INVALID', f'{profile_id}/profile.json is not the profile/v1 declaration '
                              f'named {profile_id}', profile=profile_id)
    status = declared.get('status')
    if not isinstance(status, dict) or status.get('operational') is not True:
        raise DispatchRefused('PROFILE_NOT_OPERATIONAL', f'{profile_id} declares status.operational '
                              f'{status.get("operational") if isinstance(status, dict) else None!r}',
                              profile=profile_id)
    return digest


def _design_revision(work_id: str, entry: dict) -> tuple[str, str, str]:
    """(design revision, change, commit) the task's resolved pointers pin, or a refusal."""
    pointers = entry.get('pointers')
    if not isinstance(pointers, list) or not pointers:
        raise DispatchRefused('DESIGN_POINTER_ABSENT', f'{work_id} carries no OpenSpec source pointer')
    failed = [p for p in pointers if not (isinstance(p, dict) and p.get('resolved') is True)]
    if failed:
        codes = sorted({str(p.get('code')) if isinstance(p, dict) else 'POINTER_MALFORMED' for p in failed})
        raise DispatchRefused('DESIGN_UNRESOLVED', f'{work_id}: {len(failed)} source pointer(s) do not resolve '
                              f'({", ".join(codes)})', codes=codes)
    texts = [p.get('pointer') for p in pointers]
    pinned = set()
    for text in texts:
        try:
            pointer = planning.Pointer.parse(text)
        except planning.PlanningError as exc:
            raise DispatchRefused('DESIGN_UNRESOLVED', f'{work_id}: {exc.code}', codes=[exc.code]) from None
        pinned.add((pointer.change, pointer.revision))
    if len(pinned) != 1:
        raise DispatchRefused('DESIGN_AMBIGUOUS', f'{work_id} pins {len(pinned)} changes or commits: '
                              f'{sorted(f"{c}@{r}" for c, r in pinned)}')
    try:
        revision = store.design_revision_from_pointers(texts)
    except store.InvalidIdentity as exc:
        raise DispatchRefused('DESIGN_UNRESOLVED', f'{work_id}: {exc}') from None
    (change, commit), = pinned
    return revision, change, commit


def resolve(request, *, manifest: ApprovedInputs, work_sources: Callable[[str], WorkSource | None],
            next_ordinal: Callable[[str, str, str], int],
            read_profile: Callable[[str], bytes] = read_profile_file) -> ResolvedInputs:
    """Resolve a dispatch request against the approved-input manifest, or raise DispatchRefused.

    ``work_sources(repository)`` gives the approved repository's Backlog.md and git source;
    ``next_ordinal(work_id, design_revision, stage)`` the next ordinal (``store_next_ordinal``);
    ``read_profile(profile_id)`` the profile.json bytes. Nothing is written anywhere.
    """
    if not isinstance(manifest, ApprovedInputs):
        raise TypeError('manifest must be ApprovedInputs (load_manifest or parse_manifest)')
    work_id, repository, stage, profile, pin = parse_request(request)
    index = manifest._index()

    repo_entry = index['repositories'].get(repository)
    if repo_entry is None:
        raise DispatchRefused('REPOSITORY_NOT_APPROVED', f'{repository!r} is not an approved repository')
    if stage not in STAGES:
        raise DispatchRefused('STAGE_UNKNOWN', f'{stage!r} is not one of {STAGES}')
    binding = index['bindings'].get((repository, stage))
    if binding is None:
        raise DispatchRefused('STAGE_NOT_BOUND', f'no binding approves {stage!r} for {repository!r}')
    profile_entry = index['profiles'].get(profile)
    if profile_entry is None:
        raise DispatchRefused('PROFILE_NOT_APPROVED', f'{profile!r} is not an approved profile')
    if profile not in binding['profiles']:
        raise DispatchRefused('PROFILE_NOT_BOUND', f'{profile!r} is not bound to {repository}/{stage}')
    if not index['catalog_pins']:
        raise DispatchRefused('NO_APPROVED_CATALOG', 'the manifest approves no catalog pin (A-01.1 promotes them)')
    pin_entry = index['catalog_pins'].get(pin)
    if pin_entry is None:
        raise DispatchRefused('CATALOG_PIN_UNKNOWN', f'{pin!r} is not an approved catalog pin')
    if pin not in binding['catalog_pins']:
        raise DispatchRefused('CATALOG_PIN_NOT_BOUND', f'{pin!r} is not bound to {repository}/{stage}')

    profile_digest = _check_profile(profile, profile_entry['sha256'], read_profile)

    source = work_sources(repository)
    if source is None:
        raise DispatchRefused('WORK_SOURCE_UNAVAILABLE', f'no Backlog.md source for {repository!r}')
    try:
        entry = source.read(work_id)
    except planning.PlanningError as exc:
        raise DispatchRefused('WORK_UNREADABLE', f'{work_id}: {exc.code}', planning_code=exc.code) from None
    if entry is None:
        raise DispatchRefused('WORK_NOT_FOUND', f'Backlog.md lists no task {work_id}')
    reasons = entry.get('reasons') if isinstance(entry, dict) else None
    if not isinstance(reasons, list):
        raise DispatchRefused('WORK_UNREADABLE', f'{work_id}: no readiness entry')
    work_reasons = [r for r in reasons if not str(r).startswith('POINTER_')]
    if work_reasons:  # the Work's own readiness is decided before its design pointers
        raise DispatchRefused('WORK_NOT_READY', f'{work_id}: {", ".join(map(str, work_reasons))}',
                              reasons=work_reasons)
    design_revision, change, commit = _design_revision(work_id, entry)
    if entry.get('eligible') is not True:
        raise DispatchRefused('WORK_NOT_READY', f'{work_id} is not eligible', reasons=reasons)
    design_entry = index['designs'].get((repository, change))
    if design_entry is None:
        raise DispatchRefused('DESIGN_NOT_ACCEPTED', f'no accepted revision of {change!r} in {repository!r}')
    if design_entry['commit'] != commit:
        raise DispatchRefused('DESIGN_REVISION_MISMATCH', f'{work_id} pins {change}@{commit}; the accepted '
                              f'revision is {change}@{design_entry["commit"]}',
                              pinned=commit, accepted=design_entry['commit'])

    inputs = policy_inputs(repo_entry, stage, design_entry, profile_entry, pin_entry)
    inputs_json = _canonical(inputs)
    policy_digest = _sha256(inputs_json)
    try:
        ordinal = next_ordinal(work_id, design_revision, stage)
        provisional = store.AttemptIdentity(
            work_id=work_id, design_revision=design_revision, stage=stage, ordinal=ordinal,
            profile_digest=profile_digest, planned_workspace='pending', policy_digest=policy_digest,
            agent_manifest_digest=pin_entry['manifest_sha256'])
        workspace = planned_workspace(repository, work_id, store.attempt_id_for(provisional.operation_key))
        identity = dataclasses.replace(provisional, planned_workspace=workspace)
    except store.InvalidIdentity as exc:
        raise DispatchRefused('IDENTITY_INVALID', str(exc)) from None
    return ResolvedInputs(
        work_id=identity.work_id, repository=repository, stage=stage, ordinal=identity.ordinal,
        design_revision=design_revision, profile=profile, profile_digest=profile_digest, catalog_pin=pin,
        agent_manifest_digest=identity.agent_manifest_digest, planned_workspace=identity.planned_workspace,
        policy_digest=policy_digest, policy_inputs_json=inputs_json, manifest_version=manifest.version,
        manifest_sha256=manifest.sha256)


# ---------------------------------------------------------------------------
# Command line

def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('check-manifest', help='schema-check an approved-input manifest file; admits nothing')
    check.add_argument('--manifest', required=True)
    sub.add_parser('manifest-path', help='print where the live manifest is expected; creates nothing')
    args = parser.parse_args(argv)
    if args.command == 'manifest-path':
        try:
            print(manifest_path(paths.resolve(environ)))
        except paths.PathsError as exc:
            print(f'REFUSED {exc}', file=sys.stderr)
            return 2
        return 0
    try:
        raw = Path(args.manifest).read_bytes()
    except OSError as exc:
        print(f'could not read {args.manifest}: {type(exc).__name__}', file=sys.stderr)
        return 2
    report = {'format': CHECK_FORMAT, 'schema': MANIFEST_SCHEMA, 'sha256': hashlib.sha256(raw).hexdigest(),
              'version': None, 'problems': []}
    try:
        report['version'] = parse_manifest(raw).version
    except DispatchRefused as exc:
        report['problems'] = exc.context.get('problems') or [[exc.code, exc.detail]]
    print(json.dumps(report, indent=2))
    for code, message in report['problems']:
        print(f'FAIL {code}: {message}', file=sys.stderr)
    return 1 if report['problems'] else 0


if __name__ == '__main__':
    sys.exit(main())
