"""Trusted dispatch input resolution, create admission and the native conversation create
(plan leaves E-01.2.1, E-01.2.2, E-01.3.1, E-05.2 and E-05.6, blueprint #execution-qualification).

Dispatch step 01 resolves the authoritative Work and profile before anything is reserved
or created: "Check Backlog readiness, accepted OpenSpec revision and executable
requirements; choose ... a qualified profile". This module is that step's trusted-side
resolver. It is pure: it reads, through injected sources, and changes nothing. Its
admission (``admit``, then ``send_create``) builds the one OpenHands create of a reserved
attempt from trusted policy only and validates it again immediately before the injected
transport; a refusal never reaches the transport (section "Admission" below).

``dispatch`` (E-01.3.1) runs the dispatcher's order on one request: resolve, reserve, admit,
send_create, with the reserved record re-read from the store, the host workspace created only
after admission, every Agent Server call checked against the profile's pinned route allowlist
(``AgentServerClient``), decision 0001's ``/server_info`` preconditions before the create, and
the returned conversation id recorded in the store; a refused attempt is marked failed.

For the D1 stage (E-05.6) the create also carries the attempt's inference token and the guest
inference endpoint as its ``secrets``: the token is requested from the inference broker's
control listener only after ``admit`` has admitted every other input, ``admit_secrets`` adds
the block, the check shared with S-03.3's qualification admission (``create_secrets``) refuses
any other shape at admission and again before the transport, the grant is revoked on any
refusal or failure and at the attempt's end (``end_attempt``), and records carry the token's
fingerprint only (integrations/dispatch/README.md).

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
  around the checkout, and (plan leaf P-04.3) any manifest a recorded decision did not
  promote: it asks an injected decision verifier (``decisions``; the dispatch-input
  commands' ``integrations/owner/input_decisions.verifier`` over the integration store)
  whether this manifest, at its version and digest, is the head of the promotion series and
  each design entry has its acceptance, and refuses without one. The loaded manifest carries
  the approval view: each entry names its approving record (``approving_record``).
  ``resolve`` and ``admit`` refuse a manifest ``load_manifest`` did not approve.
* **Output:** a ``ResolvedInputs`` record: the design revision, the profile digest, the
  agent manifest digest, the policy digest and the planned workspace, with the manifest
  version and digest that approved them. ``attempt_identity()`` and ``intent()`` feed
  ``IntegrationStore.reserve_attempt`` directly. Otherwise a ``DispatchRefused`` with a
  stable code (``REFUSALS``), raised before any reservation and before any external call.

Check order (the first failing check refuses): the request; the repository; the stage;
the stage's binding; the profile's approval and binding; the catalog pin (required); the
profile file's digest and qualification, and its admission policy (``admission_policy``,
E-01.2.2: runtime, caps within the ceilings, mounts); the Work's native readiness; the design
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
import math
import os
from pathlib import Path, PurePath, PurePosixPath
import re
import stat
import sys
import threading
import weakref
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
# The reference grammar integrations/lineage reads a reservation's outcomeRef with (decision 0008).
lineage = _load('lineage', REPO / 'integrations' / 'lineage' / 'lineage.py')
# E-05.6: the create's secrets block check, the one shared with S-03.3's qualification admission (not a copy). It
# loads the broker's token grammar on first use only; the D1 stage's other inference modules are loaded by
# ``_inference_modules`` when that stage is admitted: importing this module loads no inference or credential module.
secrets_check = _load('aieh_dispatch_create_secrets', HERE / 'create_secrets.py')

REQUEST_FORMAT = 'ai-engineering-harness/dispatch/request/v1'
MANIFEST_SCHEMA = 'ai-engineering-harness/dispatch/approved-inputs/v1'
# v2 (E-01.3.1): v1 plus outcome_ref, the Work's outcome reference (the reservation's outcomeRef).
RESOLVED_FORMAT = 'ai-engineering-harness/dispatch/resolved-inputs/v2'
# v2 (E-01.2.2): v1 plus the admission policy (runtime, create route and template, working
# directory, conversation caps, guest ceilings, declared mounts) under "admission".
POLICY_FORMAT = 'ai-engineering-harness/dispatch/policy-inputs/v2'
ADMITTED_FORMAT = 'ai-engineering-harness/dispatch/admitted-create/v1'
REFUSAL_FORMAT = 'ai-engineering-harness/dispatch/refusal/v1'
CHECK_FORMAT = 'ai-engineering-harness/dispatch/manifest-check/v1'
PROFILE_SCHEMA = 'ai-engineering-harness/profiles/profile/v1'
ROUTES_SCHEMA = 'ai-engineering-harness/profiles/agent-server-routes/v1'
INTENT_KEY = 'dispatchInputs'
# The reservation intent's correlation keys (blueprint #integration-contracts), the names
# integrations/lineage reads (lineage_trace.WORK_KEY, OUTCOME_KEY).
WORK_REF_KEY, OUTCOME_REF_KEY = store.WORK_REF_KEY, 'outcomeRef'
OUTCOME_SCHEME = 'outcome:'
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
    # P-04.3: a manifest is approved only by a recorded decision (load_manifest's decision verifier)
    'MANIFEST_NOT_PROMOTED': 'no decision source was given, the store holds no promotion receipt at this version, '
                             'or the manifest was not loaded by load_manifest',
    'DECISION_RECORD_INVALID': 'a receipt\'s decision is not a well-formed record of its format and kind, or does not '
                               'bind what the receipt says; also a verifier answer that is not well formed',
    'MANIFEST_PROMOTION_UNCONFIRMED': 'the promotion receipt exists but is not confirmed (run manifest resolve)',
    'MANIFEST_DIGEST_MISMATCH': 'the file\'s sha256 is not the decided digest',
    'DECISION_REPLAYED': 'a later promotion is confirmed',
    'DESIGN_ACCEPTANCE_MISSING': 'a design entry has no binding, or no confirmed design-acceptance receipt whose '
                                 'subject equals it',
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
    'OUTCOME_REF_ABSENT': 'the task carries no outcome reference (outcome:<id>), so the reservation could not '
                          'carry an outcomeRef',
    'OUTCOME_REF_INVALID': 'an outcome reference of the task is not a well-formed outcome:<uuid>[@<commit>]',
    'OUTCOME_REF_AMBIGUOUS': 'the task references more than one outcome (or one at several revisions)',
    'IDENTITY_INVALID': 'the resolved inputs do not form a valid attempt identity',
    # E-01.2.2: admission before the OpenHands create
    'PROFILE_ADMISSION_INVALID': 'the profile declares no complete, well-formed admission policy (Agent Server '
                                 'configuration, create template, conversation mounts, route allowlist, ceilings)',
    'PROFILE_ARTIFACT_MISSING': 'a profile artifact the admission policy pins (create template or route '
                                'allowlist) cannot be read',
    'PROFILE_ARTIFACT_DRIFTED': 'a pinned profile artifact no longer has the sha256 the approved profile declares',
    'PROFILE_ARTIFACT_INVALID': 'a pinned profile artifact is not strict JSON of its expected shape',
    'ADMISSION_MISMATCH': 'the resolved inputs or the admitted request do not match the approval they claim '
                          '(manifest, profile digest or policy digest)',
    'RUNTIME_NOT_DOCKER': 'the server configuration or the create body does not select the Docker runtime '
                          'only (a local or process runtime, a selectable runtime, or no explicit selector)',
    'CAPS_ABOVE_CEILING': 'the declared conversation caps, times the concurrent runs, exceed the guest ceilings',
    'CAPS_OVERRIDE_FORBIDDEN': 'the create body carries a resource cap other than the declared one, or a cap '
                               'field the policy does not establish',
    'MOUNT_POLICY_INVALID': 'the declared conversation mounts leave the source root, touch a forbidden source, '
                            'or do not provide the allowlisted working directory',
    'MOUNTS_NOT_DECLARED': 'the effective mount set is not exactly the declared one (an extra, missing or '
                           'altered mount, or a body field that would add one)',
    'WORKING_DIR_NOT_ALLOWED': 'the create body\'s workspace is not the server-provisioned working directory',
    'ROUTE_NOT_ALLOWLISTED': 'the call (the create or any other dispatcher call) does not target a route the '
                             'pinned route allowlist lists exactly once with dispatcher "allowed"',
    'ROUTE_PARAMETER_INVALID': 'a route\'s path parameters are not exactly its placeholders, each in its grammar',
    'BODY_MALFORMED': 'the create body is not a JSON object, or a bodyless call (GET, HEAD, DELETE) carries a body',
    'BODY_FIELD_UNKNOWN': 'the create body carries a field outside the allowlist',
    'BODY_NOT_TEMPLATE': 'an allowlisted create body field differs from the profile\'s pinned create template',
    'CONVERSATION_ID_MISMATCH': 'the create body does not carry the reserved conversation id',
    'WORKSPACE_CATEGORY_UNAVAILABLE': 'no usable workspaces category from integrations/paths',
    'WORKSPACE_PATH_INVALID': 'the planned workspace is not <repository>/<work_id>/<attempt_id> in canonical '
                              'grammar (absolute, drive, UNC, .., stream, trailing dot or space, case or '
                              'normalization variants are refused)',
    'WORKSPACE_RESERVED_NAME': 'a planned workspace part is a Windows reserved device name',
    'WORKSPACE_NOT_PLANNED': 'the planned workspace is not the fixed rule\'s workspace for this attempt',
    'WORKSPACE_PATH_UNSAFE': 'an existing part of the workspace path is a link, junction, reparse point or '
                             'not a directory',
    # E-01.3.1: the native conversation create
    'SERVER_PRECONDITION_FAILED': 'GET /server_info does not show decision 0001\'s preconditions P1 to P5 (the '
                                  'pinned version, conversation_runtime_routes_v1, idempotent_conversation_create_v1, '
                                  'runtime docker, no selectable runtime)',
    'RESERVATION_INVALID': 'the stored reservation is not a dispatch reservation consistent with its typed identity',
    'ATTEMPT_NOT_RESERVED': 'the stored attempt is no longer in the reserved state',
    'CREATE_REFUSED': 'the Agent Server answered the create with a 4xx refusal',
    # E-01.3.3: the stage's bot role token, in the dispatcher's attempt context only (attempt_tokens.py).
    'ATTEMPT_NOT_CONFIRMED': 'the stored attempt is not confirmed: no role token is delivered for it',
    'ROLE_TOKEN_MISSING': 'the credential provider holds no entry for the stage\'s bot',
    'ROLE_TOKEN_UNAVAILABLE': 'the credential provider could not be read',
    'ROLE_TOKEN_MISMATCH': 'the entry or its token is not exactly the stage\'s bot with its scopes',
    'ROLE_TOKEN_REJECTED': 'Gitea refuses the stage\'s bot token (401)',
    'ROLE_TOKEN_UNVERIFIED': 'Gitea\'s answer about the token was lost or not its token view',
    'ROLE_TOKEN_EXPOSURE': 'an Agent Server call would carry a delivered role token or its fingerprint',
    # E-05.2: the D1 stage's create template (the profile's stage_create_template)
    'STAGE_TEMPLATE_DISPOSABLE': 'the D1 stage\'s create template is a disposable fixture: the profile\'s F-04.2 '
                                 'conversation fixture (by path or sha256), or a template tagged disposable (the '
                                 'F-04.2 fixture\'s and the S-03.3 qualification create\'s tag)',
    'AGENT_BLOCK_NOT_ACP': 'the D1 stage\'s pinned create template does not carry an ACP agent block '
                           '(agent_settings with agent_kind acp)',
    # E-05.6: the D1 stage's create secrets (the attempt's inference token and endpoint). The secrets block's codes
    # and meanings are the check's shared with S-03.3's qualification admission (create_secrets.MEANINGS).
    **secrets_check.MEANINGS,
    'INFERENCE_INPUTS_INVALID': 'the D1 stage\'s inference inputs cannot be admitted: the pinned ACP registry '
                                'extract drifted or is not its shape, the template\'s ACP server is not the '
                                'registry entry\'s, its model is not one name of the broker\'s grammar, or the profile '
                                'declares no single guest inference endpoint',
    'INFERENCE_GRANT_UNAVAILABLE': 'the D1 stage\'s attempt token was not issued: no broker control listener was '
                                   'given, or the broker refused or did not answer the issue',
    'INFERENCE_REVOKER_INVALID': 'the dispatcher\'s revoker is not a revoker the broker takes (1 to 200 printable '
                                 'characters)',
    'SECRET_NOT_FROM_GRANT': 'the admitted create\'s token secret is not the slot the held grant\'s token fills at '
                             'the send: a token value in the admitted body is never sent',
    'INFERENCE_REVOCATION_FAILED': 'the attempt\'s inference grant was not revoked (the broker refused or did not '
                                   'answer): it stays live until revoked or expired; end_attempt tries again',
}


class DispatchRefused(Exception):
    """A typed refusal. Resolution refuses before any reservation; admission and the create's own
    checks refuse before the create is sent; only ``CREATE_REFUSED`` reports the server's answer."""

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


MANIFEST_SECTIONS = ('repositories', 'designs', 'profiles', 'catalog_pins', 'bindings')
# P-04.3: the approval view load_manifest attaches (integrations/owner/input_decisions.APPROVAL_FORMAT).
APPROVAL_FORMAT = 'ai-engineering-harness/dispatch/manifest-approval/v1'
# The decision verifier's refusals, in the order it checks them (input_decisions.REFUSALS).
DECISION_REFUSALS = ('MANIFEST_NOT_PROMOTED', 'DECISION_RECORD_INVALID', 'MANIFEST_PROMOTION_UNCONFIRMED',
                     'MANIFEST_DIGEST_MISMATCH', 'DECISION_REPLAYED', 'DESIGN_ACCEPTANCE_MISSING')
NAMED_RECORD_KEYS = ('decisionId', 'format', 'kind', 'receipt', 'authority')


@dataclass(frozen=True)
class ApprovedInputs:
    """A schema-checked approved-input manifest: its version, the sha256 of its bytes, its entries, and,
    when ``load_manifest`` approved it through a recorded decision, the approval view (``approval``):
    the promotion decision and each design entry's acceptance decision. ``parse_manifest``'s result has
    none, and ``resolve`` and ``admit`` refuse it."""
    version: int
    sha256: str
    data_json: str  # canonical JSON of the parsed manifest; the object is never mutated
    approval_json: str | None = None  # canonical JSON of the approval view, set only by load_manifest

    @property
    def data(self) -> dict:
        return json.loads(self.data_json)

    @property
    def approval(self) -> dict | None:
        """The approval view (``ai-engineering-harness/dispatch/manifest-approval/v1``), or None."""
        return None if self.approval_json is None else json.loads(self.approval_json)

    def approving_record(self, section: str, key) -> dict:
        """The record that approved entry KEY of SECTION (the key ``_index`` gives it: an id, or a
        (repository, change) or (repository, stage) pair): a design entry names its design-acceptance
        decision, every other entry the promotion decision; each with its decision id, format, kind,
        receipt key and authority. MANIFEST_NOT_PROMOTED when the manifest carries no approval; KeyError
        for an entry it does not have."""
        approval = self.approval
        if approval is None:
            raise DispatchRefused('MANIFEST_NOT_PROMOTED', 'the manifest was not loaded by load_manifest with a '
                                  'decision verifier: it names no approving record')
        if section not in MANIFEST_SECTIONS:
            raise KeyError(f'{section!r} is not a manifest section')
        entry = self._index()[section][key]  # KeyError for an entry the manifest does not have
        if section != 'designs':
            return dict(approval['promotion'])
        return next(dict(named) for named in approval['designs']
                    if (named['repository'], named['change'], named['commit'])
                    == (entry['repository'], entry['change'], entry['commit']))

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


# The one "inside or around the checkout" comparison is aieh_paths' (F-07.1): load_manifest uses it, and the
# input recorder's candidate check runs load_manifest's rules. The names stay here for this module's tests.
inside_or_around = paths.inside_or_around
_comparable = paths._comparable


def _approval(manifest: ApprovedInputs, answer) -> str:
    """The canonical approval view of a decision verifier's ANSWER for MANIFEST, or DispatchRefused: the
    verifier's own refusal, or DECISION_RECORD_INVALID for an answer that is not well formed."""
    def malformed(detail):
        return DispatchRefused('DECISION_RECORD_INVALID', f'the decision verifier\'s answer {detail}')

    try:
        code, detail, approval = answer
    except (TypeError, ValueError):
        raise malformed('is not (code, detail, approval)') from None
    if code is not None:
        if code not in DECISION_REFUSALS or not isinstance(detail, str):
            raise malformed(f'names {code!r}, not one of its refusals')
        raise DispatchRefused(code, detail)
    designs = [(e['repository'], e['change'], e['commit']) for e in manifest.data['designs']]

    def named(record):
        return isinstance(record, dict) and all(k in record for k in NAMED_RECORD_KEYS) \
            and isinstance(record['decisionId'], str) and isinstance(record['receipt'], str) \
            and isinstance(record['authority'], dict) and record['authority'].get('authority') in ('owner', 'delegated')

    if not isinstance(approval, dict) or approval.get('format') != APPROVAL_FORMAT \
            or approval.get('version') != manifest.version or approval.get('digest') != f'sha256:{manifest.sha256}' \
            or not named(approval.get('promotion')) or not isinstance(approval.get('designs'), list) \
            or not all(named(d) for d in approval['designs']) \
            or [(d.get('repository'), d.get('change'), d.get('commit')) for d in approval['designs']] != designs:
        raise malformed(f'is not a {APPROVAL_FORMAT} view of this manifest (version {manifest.version}, '
                        f'sha256:{manifest.sha256}, its designs entries in order)')
    return _canonical(approval)


def load_manifest(path, *, decisions=None, repo_root=REPO) -> ApprovedInputs:
    """Read the live manifest from an absolute path outside the checkout, schema-check it, and approve it
    through DECISIONS, the decision verifier (plan leaf P-04.3).

    DECISIONS is a callable ``(version, sha256, designs) -> (code, detail, approval)``: the manifest's
    version, the sha256 of its bytes and its ``designs`` entries ``[{repository, change, commit}]``; it
    answers a refusal code of ``DECISION_REFUSALS`` with its detail, or None and the approval view (the
    dispatch-input commands' ``input_decisions.verifier(store)``). In this order: the path rules
    (``MANIFEST_PATH_INVALID``, ``MANIFEST_INSIDE_CHECKOUT``, before anything is read), the read
    (``MANIFEST_MISSING``, ``MANIFEST_UNREADABLE``), the schema (``MANIFEST_INVALID``), then no DECISIONS
    is ``MANIFEST_NOT_PROMOTED``, and the verifier's answer: its refusal, or ``DECISION_RECORD_INVALID``
    when it raises or answers anything but a well-formed view of this manifest. The result carries the
    approval view."""
    text = os.fspath(path) if isinstance(path, (str, os.PathLike)) else None
    candidate = Path(text) if text else None
    if candidate is None or not candidate.is_absolute() or any(part in ('.', '..') for part in candidate.parts):
        raise DispatchRefused('MANIFEST_PATH_INVALID', f'not an absolute path without . or .. parts: {path!r}')
    repo = Path(os.path.realpath(repo_root))
    if inside_or_around(candidate, repo) or inside_or_around(os.path.realpath(candidate), repo):
        raise DispatchRefused('MANIFEST_INSIDE_CHECKOUT', f'{candidate} is inside or contains the checkout')
    try:
        with open(candidate, 'rb') as handle:
            raw = handle.read(MAX_MANIFEST_BYTES + 1)
    except FileNotFoundError:
        raise DispatchRefused('MANIFEST_MISSING', f'no manifest at {candidate}') from None
    except OSError as exc:
        raise DispatchRefused('MANIFEST_UNREADABLE', f'{candidate}: {type(exc).__name__}') from None
    manifest = parse_manifest(raw)
    if decisions is None:
        raise DispatchRefused('MANIFEST_NOT_PROMOTED', 'no decision source was given: a manifest loads only when a '
                              'recorded decision promoted it (P-04.3)')
    designs = [{k: e[k] for k in ('repository', 'change', 'commit')} for e in manifest.data['designs']]
    failure = None
    try:
        answer = decisions(manifest.version, manifest.sha256, designs)
    except Exception as exc:  # noqa: BLE001 - whatever the verifier raises is an answer that is not well formed
        failure = exc
    if failure is not None:
        raise DispatchRefused('DECISION_RECORD_INVALID', f'the decision verifier raised {type(failure).__name__}')
    approved = dataclasses.replace(manifest, approval_json=_approval(manifest, answer))
    _LOADED[id(approved)] = approved
    return approved


# The ApprovedInputs objects load_manifest returned in this process, by identity. A caller cannot add one:
# dataclasses.replace, a copy or a hand-built ApprovedInputs is another object, which is not here. It is a guard
# against convenience and accident (a driver that parses the file itself), not against code of the same account in
# this process, which decision 0010 point 1 places outside the threat model.
_LOADED: 'weakref.WeakValueDictionary[int, ApprovedInputs]' = weakref.WeakValueDictionary()


def _require_promoted(manifest: ApprovedInputs) -> None:
    """MANIFEST_NOT_PROMOTED unless MANIFEST is an object load_manifest returned in this process, with its approval
    view still well formed for this version, digest and designs."""
    if _LOADED.get(id(manifest)) is not manifest:
        raise DispatchRefused('MANIFEST_NOT_PROMOTED', 'the manifest was not returned by load_manifest in this '
                              'process with a decision verifier (parse_manifest\'s result is for checking only)')
    failure = None
    try:
        _approval(manifest, (None, '', manifest.approval))
    except DispatchRefused as exc:
        failure = exc.detail
    if failure is not None:
        raise DispatchRefused('MANIFEST_NOT_PROMOTED', f'the manifest\'s approval view is not well formed: {failure}')


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
        # One readiness evaluation is one adapter operation (F-09.4): one git batch reader, and
        # Backlog.md's reads made once each (the task view below is the readiness read's, memoized).
        with planning.operation():
            listed = [t['id'] for t in self.backlog.list_tasks() if t['id'].upper() == work_id.upper()]
            if not listed:
                return None
            report = readiness.read_readiness(self.backlog, self.git, [listed[0]])
            references = self.backlog.view(listed[0]).get('references')
            # The task's own references (E-01.3.1: its outcome reference), as Backlog.md reports them.
            return {**report['tasks'][0], 'references': list(references) if isinstance(references, list) else None}


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
    outcome_ref: str

    @property
    def policy_inputs(self) -> dict:
        return json.loads(self.policy_inputs_json)

    @property
    def work_ref(self) -> str:
        return f'{store.WORK_REF_PREFIX}{self.work_id}'

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
                'policy_inputs': self.policy_inputs, 'outcome_ref': self.outcome_ref,
                'approval': {'manifest_schema': MANIFEST_SCHEMA, 'manifest_version': self.manifest_version,
                             'manifest_sha256': self.manifest_sha256}}

    def intent(self) -> dict:
        """The reservation intent: the record under ``dispatchInputs``, with the correlation keys
        ``workRef`` (``backlog:<work_id>``) and ``outcomeRef`` (the Work's ``outcome:`` reference)
        that integrations/lineage reads. Its digest therefore covers the approval provenance, so a
        later audit ties the attempt to the manifest that approved it."""
        return {INTENT_KEY: self.to_json(), WORK_REF_KEY: self.work_ref, OUTCOME_REF_KEY: self.outcome_ref}

    @classmethod
    def from_json(cls, record) -> 'ResolvedInputs':
        """The record ``to_json`` wrote (as the store holds it), checked strictly: exactly its keys
        and types, and ``to_json`` of the result equal to it. RESERVATION_INVALID otherwise."""
        def invalid(detail):
            raise DispatchRefused('RESERVATION_INVALID', f'the stored dispatch record {detail}')

        strings = ('work_id', 'repository', 'stage', 'design_revision', 'profile', 'profile_digest', 'catalog_pin',
                   'agent_manifest_digest', 'planned_workspace', 'policy_digest', 'outcome_ref')
        keys = {'format', 'ordinal', 'policy_inputs', 'approval', *strings}
        if not isinstance(record, dict) or set(record) != keys or record['format'] != RESOLVED_FORMAT:
            invalid(f'is not {RESOLVED_FORMAT}')
        approval = record['approval']
        if not all(isinstance(record[k], str) for k in strings) or type(record['ordinal']) is not int \
                or not isinstance(record['policy_inputs'], dict) or not isinstance(approval, dict) \
                or set(approval) != {'manifest_schema', 'manifest_version', 'manifest_sha256'} \
                or approval['manifest_schema'] != MANIFEST_SCHEMA or type(approval['manifest_version']) is not int \
                or not isinstance(approval['manifest_sha256'], str):
            invalid('has a field of the wrong type')
        resolved = cls(**{k: record[k] for k in strings}, ordinal=record['ordinal'],
                       policy_inputs_json=_canonical(record['policy_inputs']),
                       manifest_version=approval['manifest_version'], manifest_sha256=approval['manifest_sha256'])
        if _canonical(resolved.to_json()) != _canonical(record):
            invalid('does not round-trip')
        return resolved


def policy_inputs(repository: dict, stage: str, design: dict, profile: dict, catalog_pin: dict,
                  admission: dict) -> dict:
    """What ``policy_digest`` covers: exactly the approved manifest entries this attempt was
    admitted under (the repository, the stage, the accepted design revision, the profile with its
    approved sha256, the catalog pin) and, since v2 (E-01.2.2), the admission policy read from that
    approved profile (``admission_policy``: runtime, create route, pinned create template and route
    allowlist, working directory, conversation caps, guest ceilings, declared mounts), under a
    format tag. Not the manifest's version or digest (provenance, carried beside it), not the
    binding lists, not the Work or the ordinal (the attempt identity)."""
    return {'format': POLICY_FORMAT,
            'repository': {'id': repository['id']},
            'stage': stage,
            'design': {'repository': design['repository'], 'change': design['change'],
                       'commit': design['commit']},
            'profile': {'id': profile['id'], 'sha256': profile['sha256']},
            'catalog_pin': {'id': catalog_pin['id'], 'repository': catalog_pin['repository'],
                            'commit': catalog_pin['commit'], 'manifest_sha256': catalog_pin['manifest_sha256']},
            'admission': admission}


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


def _check_profile(profile_id: str, approved_sha256: str, read_profile: Callable[[str], bytes]) -> tuple[str, dict]:
    _, digest, declared = _read_checked_profile(profile_id, approved_sha256, read_profile)
    return digest, declared


def _read_checked_profile(profile_id: str, approved_sha256: str,
                          read_profile: Callable[[str], bytes]) -> tuple[bytes, str, dict]:
    """The approved profile's bytes, their sha256 and its checked declaration, or a refusal."""
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
    return raw, digest, declared


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


def _outcome_ref(work_id: str, entry: dict) -> str:
    """The Work's outcome reference: the one ``outcome:`` reference among the task's own Backlog.md
    references (decision 0008 point 4: a change serving an outcome references it, a Backlog
    ``--ref``), in the grammar integrations/lineage reads; or a refusal."""
    references = entry.get('references')
    texts = sorted({r for r in references if isinstance(r, str) and r.startswith(OUTCOME_SCHEME)}) \
        if isinstance(references, list) else []
    if not texts:
        raise DispatchRefused('OUTCOME_REF_ABSENT', f'{work_id} carries no {OUTCOME_SCHEME}<id> reference')
    for text in texts:
        try:
            reference = lineage.parse(text)
        except lineage.MalformedReference as exc:
            raise DispatchRefused('OUTCOME_REF_INVALID', f'{work_id}: {exc.code}: {text!r}', reference=text) from None
        if not isinstance(reference, lineage.ObjectiveRef):
            raise DispatchRefused('OUTCOME_REF_INVALID', f'{work_id}: not an outcome reference: {text!r}',
                                  reference=text)
    if len(texts) != 1:
        raise DispatchRefused('OUTCOME_REF_AMBIGUOUS', f'{work_id} references {len(texts)} outcomes: {texts}',
                              references=texts)
    return texts[0]


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
    _require_promoted(manifest)  # P-04.3: before anything is read or reserved
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

    profile_digest, declared = _check_profile(profile, profile_entry['sha256'], read_profile)
    admission = admission_policy(declared, profile, stage)

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
    outcome_ref = _outcome_ref(work_id, entry)

    inputs = policy_inputs(repo_entry, stage, design_entry, profile_entry, pin_entry, admission)
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
        manifest_sha256=manifest.sha256, outcome_ref=outcome_ref)


# ---------------------------------------------------------------------------
# Admission before the OpenHands create (E-01.2.2)
#
# resolve -> reserve_attempt -> admit -> send_create(transport). ``admit`` builds the one create
# request (route and body) from trusted policy only: the approved profile's admission policy (in
# policy_inputs v2, so covered by the reserved policy digest), its sha256-pinned create template
# and route allowlist, and the reserved conversation id. Nothing caller-supplied reaches it: it
# has no parameter for a path, mount, cap, runtime, working directory, route or body field.
# ``send_create`` validates the admitted request again against the same policy immediately before
# it calls the injected transport, exactly once.
#
# The D1 stage (E-05.2): a profile may pin one stage's create template
# (``provisioning.agent_server.stage_create_template``: stage, path, sha256). For that stage the pin
# replaces the F-04.2 fixture as ``create_template`` (same policy shape, so the policy digest binds the
# template's sha256), the F-04.2 fixture and any template tagged disposable are refused, the template must
# carry an ACP agent block, and the body's agent block must be exactly the template's (BODY_NOT_TEMPLATE).
# A profile without the declaration, and every other stage, keep E-01.2.2's behaviour.
# E-05.6: the D1 stage's create carries the attempt's secrets, added by admit_secrets after the token is issued.

CREATE_ROUTE = {'method': 'POST', 'path': '/api/conversations'}  # docker_runtime/routers.py start_conversation
WORKSPACE_CATEGORY = 'workspaces'      # aieh_paths category (persistent/, class C, decision 0009)
WORKING_DIR = '/workspace'             # the Docker runtime's server-provisioned workspace: no host path
WORKSPACE_BODY_KIND = 'LocalWorkspace'
DOCKER_RUNTIME = 'docker'
HEX_PLACEHOLDER = '{conversation_hex}'
BACKSLASH = chr(92)
# The create body allowlist: the fields of the profile's pinned create template (the F-04.2
# fixture's, as tools/check_profile.py FIXTURE_KEYS states them). Within "container": the browser
# switch, and the two caps the locked server's container options take (F-04.2 section 7).
BODY_FIELDS = ('conversation_id', 'conversation_runtime', 'workspace', 'agent_settings', 'autotitle',
               'container', 'tags')
CONTAINER_FIELDS = ('browser',)
CONTAINER_CAPS = ('memory', 'cpus')
# Never the source of a conversation bind, nor inside or around one (decision 0003: never the
# Docker or containerd socket). The profile's forbidden list must name at least these.
MANDATORY_FORBIDDEN = ('/run/docker.sock', '/var/run/docker.sock', '/run/containerd')
# A field outside the allowlist is always refused; its name only picks the refusal code.
OVERRIDE_CLASSES = (
    (re.compile(r'mount|volume|bind', re.IGNORECASE), 'MOUNTS_NOT_DECLARED'),
    (re.compile(r'mem|cpu|pid|ulimit|shm|resource|limit|quota|swap', re.IGNORECASE), 'CAPS_OVERRIDE_FORBIDDEN'),
    (re.compile(r'runtime|docker|local|process|sandbox', re.IGNORECASE), 'RUNTIME_NOT_DOCKER'),
    (re.compile(r'work_?dir|workspace|path|dir', re.IGNORECASE), 'WORKING_DIR_NOT_ALLOWED'),
)
# E-05.2: the D1 stage's create template. One declaration per profile, for one stage (the D1 stage only;
# A-01.2 owns the general per-stage materialization): provisioning.agent_server.stage_create_template.
STAGE_TEMPLATE_KEY = 'stage_create_template'
ACP_AGENT_KIND = 'acp'
# The tag both disposable create fixtures carry: f-04.2-disposable (F-04.2) and s-03.3-disposable (S-03.3).
DISPOSABLE_TAG_SUFFIX = '-disposable'
# E-05.6: the D1 stage's create secrets. Only the D1 stage's create carries the two secret fields; the pinned
# template carries none (admit_secrets adds them). The token's value stands in the admitted body as TOKEN_SLOT, and
# is put in its place, in memory only, by the check immediately before the transport. The grant's budgets and
# lifetime are declared beside the stage template's pin (GRANT_KEY: requests, tokens, ttl_s), bound by the profile
# digest; the family and the model come from the pinned template's ACP block.
SECRET_FIELDS = secrets_check.SECRET_FIELDS
TOKEN_SLOT = '{attempt_token}'
GRANT_KEY = 'inference_grant'
GRANT_FIELDS = ('requests', 'tokens', 'ttl_s')
GRANT_FORMAT = 'ai-engineering-harness/dispatch/inference-grant/v1'
REVOCATION_FORMAT = 'ai-engineering-harness/dispatch/inference-revocation/v1'
REVOCATION_TRIGGER = 'attempt end'     # decision 0007 point 5 (the broker's TRIGGERS): a refused attempt ends too
REVOCATION_KEY = 'dispatch/attempt/{attempt_id}/inference-revocation/{n}'
GRANT_JOURNAL_FORMAT = 'ai-engineering-harness/dispatch/inference-grant-journal/v1'
GRANT_JOURNAL_KEY = 'dispatch/attempt/{attempt_id}/inference-grant'
CODE_RE = re.compile(r'[A-Z][A-Z0-9_]{0,63}')
ARTIFACT_PATH_RE = re.compile(r'profiles/[a-z0-9]+(?:-[a-z0-9]+)*(?:/[A-Za-z0-9_-][A-Za-z0-9._-]*)+')
GUEST_PATH_RE = re.compile(r'(?:/[A-Za-z0-9._-]+)+')
MEMORY_RE = re.compile(r'([1-9][0-9]{0,15})([bkmg]?)')
MEMORY_UNITS = {'': 1, 'b': 1, 'k': 1 << 10, 'm': 1 << 20, 'g': 1 << 30}  # Docker's binary units
UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
# Windows device names, reserved in any path part with or without an extension.
RESERVED_NAMES = frozenset(['CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$', 'CLOCK$'] + [
    f'{device}{n}' for device in ('COM', 'LPT') for n in list('0123456789') + [chr(0xB9), chr(0xB2), chr(0xB3)]])


def _strict_loads(text):
    return json.loads(text, object_pairs_hook=_strict_object, parse_constant=_no_constant)


def _same(a, b) -> bool:
    """Equal as canonical JSON: types matter (2 is not 2.0, true is not 1)."""
    try:
        return _canonical(a) == _canonical(b)
    except (TypeError, ValueError):
        return False


def _is_guest_path(text) -> bool:
    return (isinstance(text, str) and GUEST_PATH_RE.fullmatch(text) is not None
            and not any(part in ('.', '..') for part in text.split('/')[1:]))


def _overlap_posix(a: str, b: str) -> bool:
    return _overlaps(PurePosixPath(a), PurePosixPath(b))


def memory_bytes(value) -> int | None:
    """Docker's memory notation (``4g``) in bytes, or None."""
    match = MEMORY_RE.fullmatch(value) if isinstance(value, str) else None
    return None if match is None else int(match.group(1)) * MEMORY_UNITS[match.group(2)]


def _positive_int(value) -> bool:
    return type(value) is int and value > 0


def _positive_number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _binds_for(binds: list, conversation_hex: str) -> list[dict]:
    return [{'type': b['type'], 'source': b['source'].replace(HEX_PLACEHOLDER, conversation_hex),
             'destination': b['destination'].replace(HEX_PLACEHOLDER, conversation_hex), 'rw': b['rw']}
            for b in binds]


def check_admission_policy(policy, profile: str) -> None:
    """Refuse an admission policy (policy_inputs v2 ``admission``) that is malformed or outside
    the rules: Docker only and not selectable; the one create route; profile-pinned template and
    route allowlist; the server-provisioned working directory; caps that, times the concurrent
    runs, stay within the guest ceilings; binds strictly under the source root, none inside or
    around a forbidden source, one of them providing the working directory."""
    def invalid(detail):
        raise DispatchRefused('PROFILE_ADMISSION_INVALID', f'{profile}: {detail}', profile=profile)

    keys = {'runtime', 'route', 'routes', 'create_template', 'workspace', 'caps', 'ceilings', 'mounts'}
    if not isinstance(policy, dict) or set(policy) != keys or not all(isinstance(policy[k], dict) for k in keys):
        invalid('the admission policy is not the policy-inputs/v2 shape')
    runtime = policy['runtime']
    if set(runtime) != {'conversation_runtime', 'selectable'} or type(runtime['conversation_runtime']) is not str \
            or runtime['conversation_runtime'] != DOCKER_RUNTIME or runtime['selectable'] is not False:
        raise DispatchRefused('RUNTIME_NOT_DOCKER', f'{profile}: the Agent Server configuration declares '
                              f'{runtime!r}; required: docker, not selectable (decision 0001 s2)', profile=profile)
    if not _same(policy['route'], CREATE_ROUTE):
        raise DispatchRefused('ROUTE_NOT_ALLOWLISTED', f'{profile}: the create route must be {CREATE_ROUTE}',
                              profile=profile)
    for name in ('routes', 'create_template'):
        pin = policy[name]
        if set(pin) != {'path', 'sha256'} or not isinstance(pin['path'], str) \
                or not ARTIFACT_PATH_RE.fullmatch(pin['path']) or not pin['path'].startswith(f'profiles/{profile}/') \
                or not isinstance(pin['sha256'], str) or not SHA256_RE.fullmatch(pin['sha256']):
            invalid(f'{name} must pin a file under profiles/{profile}/ by sha256')
    if not _same(policy['workspace'], {'category': WORKSPACE_CATEGORY, 'working_dir': WORKING_DIR}):
        raise DispatchRefused('WORKING_DIR_NOT_ALLOWED', f'{profile}: the workspace policy must be the '
                              f'{WORKSPACE_CATEGORY} category and working_dir {WORKING_DIR}', profile=profile)
    caps, ceilings = policy['caps'], policy['ceilings']
    memory = memory_bytes(caps.get('memory'))
    if set(caps) != {'memory', 'cpus', 'pids_limit', 'max_concurrent_runs'} or memory is None \
            or not _positive_number(caps['cpus']) or not _positive_int(caps['pids_limit']) \
            or not _positive_int(caps['max_concurrent_runs']) or set(ceilings) != {'vcpu', 'memory_mib'} \
            or not _positive_int(ceilings['vcpu']) or not _positive_int(ceilings['memory_mib']):
        invalid('explicit conversation caps (memory, cpus, pids_limit, max_concurrent_runs) and guest '
                'ceilings (vcpu, memory_mib) are required')
    runs = caps['max_concurrent_runs']
    if runs * memory > ceilings['memory_mib'] << 20 or runs * caps['cpus'] > ceilings['vcpu']:
        raise DispatchRefused('CAPS_ABOVE_CEILING', f'{profile}: {runs} x (memory {caps["memory"]}, cpus '
                              f'{caps["cpus"]}) exceeds the ceilings {ceilings}', profile=profile)
    mounts = policy['mounts']
    root, binds, forbidden = mounts.get('source_root'), mounts.get('binds'), mounts.get('forbidden_sources')
    if set(mounts) != {'source_root', 'binds', 'forbidden_sources'} or not _is_guest_path(root) \
            or not isinstance(forbidden, list) or not all(_is_guest_path(f) for f in forbidden) \
            or not isinstance(binds, list) or not binds or not all(
                isinstance(b, dict) and set(b) == {'type', 'source', 'destination', 'rw'} and b['type'] == 'bind'
                and type(b['rw']) is bool and isinstance(b['source'], str) and isinstance(b['destination'], str)
                for b in binds):
        invalid('conversations: source_root, forbidden_sources and a non-empty list of bind mounts '
                '{type bind, source, destination, rw} are required')
    if not set(MANDATORY_FORBIDDEN) <= set(forbidden):
        raise DispatchRefused('MOUNT_POLICY_INVALID', f'{profile}: forbidden_sources must name '
                              f'{list(MANDATORY_FORBIDDEN)}', profile=profile)
    expanded = _binds_for(binds, '0' * 32)
    for bind in expanded:
        source = bind['source']
        if not (_is_guest_path(source) and _is_guest_path(bind['destination'])) \
                or not PurePosixPath(source).is_relative_to(root) or source == root \
                or any(_overlap_posix(source, f) for f in forbidden):
            raise DispatchRefused('MOUNT_POLICY_INVALID', f'{profile}: bind {bind} must lie strictly under '
                                  f'{root} and clear of {forbidden}', profile=profile)
    destinations = [bind['destination'] for bind in expanded]
    if len(set(destinations)) != len(destinations) or WORKING_DIR not in destinations:
        raise DispatchRefused('MOUNT_POLICY_INVALID', f'{profile}: bind destinations must be distinct and '
                              f'include the working directory {WORKING_DIR}', profile=profile)


def _check_stage_create_template(pin, fixture, profile: str) -> dict:
    """The profile's D1 stage template declaration, normalized to ``{stage, path, sha256, inference_grant}``
    (E-05.2, E-05.6); refused when malformed (``PROFILE_ADMISSION_INVALID``: the grant's ``requests``, ``tokens``
    and ``ttl_s`` are required positive integers, the broker bounds them at issuance) or when it pins the profile's
    F-04.2 fixture, by path or by sha256 (``STAGE_TEMPLATE_DISPOSABLE``). Other keys of the declaration are
    descriptive and ignored."""
    if not isinstance(pin, dict) or pin.get('stage') not in STAGES or not isinstance(pin.get('path'), str) \
            or not ARTIFACT_PATH_RE.fullmatch(pin['path']) or not pin['path'].startswith(f'profiles/{profile}/') \
            or not isinstance(pin.get('sha256'), str) or not SHA256_RE.fullmatch(pin['sha256']):
        raise DispatchRefused('PROFILE_ADMISSION_INVALID', f'{profile}: agent_server.{STAGE_TEMPLATE_KEY} must name '
                              f'one of {STAGES} and pin a file under profiles/{profile}/ by sha256', profile=profile)
    if pin['path'] == fixture.get('path') or pin['sha256'] == fixture.get('sha256'):
        raise DispatchRefused('STAGE_TEMPLATE_DISPOSABLE', f'{profile}: the {pin["stage"]} stage\'s create template '
                              'is the profile\'s F-04.2 disposable fixture', profile=profile, stage=pin['stage'])
    grant = pin.get(GRANT_KEY)
    if not isinstance(grant, dict) or set(grant) != set(GRANT_FIELDS) \
            or not all(_positive_int(grant[name]) for name in GRANT_FIELDS):
        raise DispatchRefused('PROFILE_ADMISSION_INVALID', f'{profile}: agent_server.{STAGE_TEMPLATE_KEY}.{GRANT_KEY} '
                              f'must declare exactly {list(GRANT_FIELDS)}, each a positive integer (E-05.6)',
                              profile=profile)
    return {'stage': pin['stage'], 'path': pin['path'], 'sha256': pin['sha256'],
            GRANT_KEY: {name: grant[name] for name in GRANT_FIELDS}}


def stage_create_template(declared: dict, profile: str) -> dict | None:
    """The D1 stage's create template pin the approved profile declares (``provisioning.agent_server.
    stage_create_template``: ``{stage, path, sha256}``), checked as ``admission_policy`` checks it, or None when
    the profile declares none (E-01.2.2's behaviour, for every stage)."""
    provisioning = declared.get('provisioning') if isinstance(declared, dict) else None
    server = provisioning.get('agent_server') if isinstance(provisioning, dict) else None
    if not isinstance(server, dict) or STAGE_TEMPLATE_KEY not in server:
        return None
    fixture = server.get('fixture')
    return _check_stage_create_template(server[STAGE_TEMPLATE_KEY], fixture if isinstance(fixture, dict) else {},
                                        profile)


def check_stage_template(template: dict, stage: str) -> None:
    """The D1 stage's pinned create template, read and digest-checked (E-05.2): not tagged disposable
    (``STAGE_TEMPLATE_DISPOSABLE``), and carrying an ACP agent block (``AGENT_BLOCK_NOT_ACP``). The block's
    content is approved by the template's digest, never re-derived here (no role-profile materialization)."""
    tags = template.get('tags')
    if isinstance(tags, dict) and any(isinstance(v, str) and v.endswith(DISPOSABLE_TAG_SUFFIX) for v in tags.values()):
        raise DispatchRefused('STAGE_TEMPLATE_DISPOSABLE', f'the {stage} stage\'s create template is tagged '
                              f'disposable ({tags})', stage=stage)
    settings = template.get('agent_settings')
    if not isinstance(settings, dict) or settings.get('agent_kind') != ACP_AGENT_KIND:
        kind = settings.get('agent_kind') if isinstance(settings, dict) else None
        raise DispatchRefused('AGENT_BLOCK_NOT_ACP', f'the {stage} stage\'s create template has agent_kind {kind!r}, '
                              f'not {ACP_AGENT_KIND!r}', stage=stage)


def admission_policy(declared: dict, profile: str, stage: str | None = None) -> dict:
    """The admission policy an approved, operational profile declares, normalized for
    policy_inputs v2: from ``provisioning.agent_server`` (``config.content``: runtime and caps;
    ``fixture``: the pinned create template; ``conversations``: the mount policy;
    ``admission.routes``: the pinned route allowlist) and ``ceilings``. For the stage that the
    profile's ``stage_create_template`` names (the D1 stage, E-05.2) the create template is that
    pin instead of ``fixture``; the policy's shape is the same."""
    def obj(value, where: str) -> dict:
        if not isinstance(value, dict):
            raise DispatchRefused('PROFILE_ADMISSION_INVALID', f'{profile}: {where} is not declared',
                                  profile=profile)
        return value

    server = obj(obj(declared.get('provisioning'), 'provisioning').get('agent_server'), 'provisioning.agent_server')
    config = obj(obj(server.get('config'), 'agent_server.config').get('content'), 'agent_server.config.content')
    fixture = obj(server.get('fixture'), 'agent_server.fixture')
    conversations = obj(server.get('conversations'), 'agent_server.conversations')
    routes = obj(obj(server.get('admission'), 'agent_server.admission').get('routes'), 'agent_server.admission.routes')
    ceilings = obj(declared.get('ceilings'), 'ceilings')
    staged = stage_create_template(declared, profile)
    template = staged if staged is not None and staged['stage'] == stage else fixture
    policy = {
        'runtime': {'conversation_runtime': config.get('conversation_runtime'),
                    'selectable': config.get('conversation_runtime_selectable')},
        'route': dict(CREATE_ROUTE),
        'routes': {'path': routes.get('path'), 'sha256': routes.get('sha256')},
        'create_template': {'path': template.get('path'), 'sha256': template.get('sha256')},
        'workspace': {'category': WORKSPACE_CATEGORY, 'working_dir': WORKING_DIR},
        'caps': {'memory': config.get('conversation_container_memory'),
                 'cpus': config.get('conversation_container_cpus'),
                 'pids_limit': config.get('conversation_container_pids_limit'),
                 'max_concurrent_runs': config.get('max_concurrent_runs')},
        'ceilings': {'vcpu': ceilings.get('vcpu'), 'memory_mib': ceilings.get('memory_mib')},
        'mounts': {'source_root': conversations.get('source_root'), 'binds': conversations.get('mounts'),
                   'forbidden_sources': conversations.get('forbidden_sources')},
    }
    check_admission_policy(policy, profile)
    return json.loads(_canonical(policy))


def read_profile_artifact(path: str, *, repo_root=REPO) -> bytes:
    """The bytes of a profile-pinned artifact, by its repository-relative ``profiles/<id>/...`` path."""
    if not (isinstance(path, str) and ARTIFACT_PATH_RE.fullmatch(path)):
        raise ValueError(f'not a profile artifact path: {path!r}')
    return Path(repo_root).joinpath(*path.split('/')).read_bytes()


def _read_pinned(read_artifact: Callable[[str], bytes], pin: dict, what: str) -> bytes:
    try:
        raw = read_artifact(pin['path'])
    except (OSError, ValueError) as exc:
        raise DispatchRefused('PROFILE_ARTIFACT_MISSING', f'{what} {pin["path"]}: {type(exc).__name__}',
                              path=pin['path']) from None
    if not isinstance(raw, bytes):
        raise DispatchRefused('PROFILE_ARTIFACT_MISSING', f'{what} {pin["path"]}: the source returned no bytes')
    digest = hashlib.sha256(raw).hexdigest()
    if digest != pin['sha256']:
        raise DispatchRefused('PROFILE_ARTIFACT_DRIFTED', f'{what} {pin["path"]} has sha256 {digest}, pinned '
                              f'{pin["sha256"]}', path=pin['path'], actual=digest, pinned=pin['sha256'])
    return raw


def _artifact_object(raw: bytes, what: str) -> dict:
    try:
        data = _strict_loads(raw.decode('utf-8'))
    except ValueError as exc:  # UnicodeDecodeError is a ValueError
        raise DispatchRefused('PROFILE_ARTIFACT_INVALID', f'{what}: {type(exc).__name__}') from None
    if not isinstance(data, dict):
        raise DispatchRefused('PROFILE_ARTIFACT_INVALID', f'{what} is not a JSON object')
    return data


def _check_route_allowlist(raw: bytes, route: dict) -> None:
    """The route allowlist (profiles/<id>/agent-server/routes.json, S-01.3.1) admits the create route:
    exactly one entry for it, with dispatcher "allowed" (fd-session-key-not-fine-grained)."""
    data = _artifact_object(raw, 'route allowlist')
    if data.get('schema') != ROUTES_SCHEMA or not isinstance(data.get('routes'), list):
        raise DispatchRefused('PROFILE_ARTIFACT_INVALID', f'the route allowlist is not {ROUTES_SCHEMA}')
    entries = [r for r in data['routes'] if isinstance(r, dict)
               and r.get('method') == route['method'] and r.get('path') == route['path']]
    if len(entries) != 1 or entries[0].get('dispatcher') != 'allowed':
        raise DispatchRefused('ROUTE_NOT_ALLOWLISTED', f'{route["method"]} {route["path"]} is not the one '
                              'dispatcher-allowed entry of the route allowlist',
                              dispatcher=[r.get('dispatcher') for r in entries])


def _override_code(key) -> str:
    for pattern, code in OVERRIDE_CLASSES:
        if pattern.search(str(key)):
            return code
    return 'BODY_FIELD_UNKNOWN'


def check_create_body(body, *, admission: dict, template: dict, conversation_id: str,
                      secrets: Mapping | None = None) -> None:
    """Refuse a create body that is not exactly the pinned template with the reserved conversation
    id: an allowlist of fields; the Docker runtime named explicitly (decision 0001 s2: every create
    sends it); the server-provisioned working directory; within ``container`` no cap but the
    declared one; every other field equal to the template's.

    ``secrets`` (the D1 stage's, E-05.6: ``names``, ``endpoint`` and ``binding``, ``StageInference.secrets``)
    admits the two secret fields beside the template's, checked first by the check shared with S-03.3's
    qualification admission (``create_secrets.check_secrets``); without it, as for every other stage, they are
    fields outside the allowlist (BODY_FIELD_UNKNOWN)."""
    if not isinstance(body, dict):
        raise DispatchRefused('BODY_MALFORMED', 'the create body is not a JSON object')
    allowed = BODY_FIELDS + (SECRET_FIELDS if secrets is not None else ())
    for key in body:
        if key not in allowed:
            raise DispatchRefused(_override_code(key), f'the create body may not carry {key!r}', field=key)
    if secrets is not None:
        secrets_check.check_secrets(body, names=secrets['names'], endpoint=secrets['endpoint'],
                                    binding=secrets['binding'], refused=DispatchRefused)
    if body.get('conversation_id') != conversation_id:
        raise DispatchRefused('CONVERSATION_ID_MISMATCH', f'the create body must carry the reserved '
                              f'conversation id {conversation_id}')
    runtime = body.get('conversation_runtime')
    if type(runtime) is not str or runtime != DOCKER_RUNTIME:
        raise DispatchRefused('RUNTIME_NOT_DOCKER', f'conversation_runtime is {runtime!r}; every create '
                              f'selects {DOCKER_RUNTIME!r} explicitly')
    working = {'kind': WORKSPACE_BODY_KIND, 'working_dir': admission['workspace']['working_dir']}
    if not _same(body.get('workspace'), working):
        raise DispatchRefused('WORKING_DIR_NOT_ALLOWED', f'workspace must be {working}')
    if 'container' in body:
        container = body['container']
        if not isinstance(container, dict):
            raise DispatchRefused('BODY_MALFORMED', 'container is not an object')
        for key, value in container.items():
            if key in CONTAINER_CAPS:
                if not _same(value, admission['caps'][key]):
                    raise DispatchRefused('CAPS_OVERRIDE_FORBIDDEN', f'container.{key} is {value!r}; only the '
                                          f'declared {admission["caps"][key]!r} may be sent', field=key)
            elif key not in CONTAINER_FIELDS:
                raise DispatchRefused(_override_code(key), f'the create body may not carry container.{key}',
                                      field=f'container.{key}')
    fields = set(body) - set(SECRET_FIELDS) if secrets is not None else set(body)
    if fields != set(template):
        raise DispatchRefused('BODY_NOT_TEMPLATE', f'the body fields {sorted(fields)} are not the template\'s '
                              f'{sorted(template)}')
    for key in (key for key in body if key in fields):
        mine, theirs = body[key], template[key]
        if key == 'conversation_id':
            continue
        if key == 'container' and isinstance(theirs, dict):
            mine = {k: v for k, v in mine.items() if k not in CONTAINER_CAPS}
            theirs = {k: v for k, v in theirs.items() if k not in CONTAINER_CAPS}
        if not _same(mine, theirs):
            raise DispatchRefused('BODY_NOT_TEMPLATE', f'{key} differs from the pinned create template', field=key)


def _workspace_parts(planned) -> list[str]:
    """The three parts of a planned workspace. A part whose name before any extension (spaces
    trimmed, any case) is a Windows device name is refused first; then the fixed rule's exact
    grammar: a lower-case repository id, a canonical upper-case Work id, a lower-case uuid."""
    parts = planned.replace(BACKSLASH, '/').split('/') if isinstance(planned, str) else []
    for part in parts:
        if part.split('.')[0].rstrip(' ').upper() in RESERVED_NAMES:
            raise DispatchRefused('WORKSPACE_RESERVED_NAME', f'{part!r} is a Windows reserved device name',
                                  part=part)
    parts = planned.split('/') if isinstance(planned, str) else []
    if len(parts) != 3 or not _is_id(parts[0]) or not store.valid_work_id(parts[1]) \
            or UUID_RE.fullmatch(parts[2]) is None:
        raise DispatchRefused('WORKSPACE_PATH_INVALID', f'not <repository>/<WORK-ID>/<attempt uuid>: {planned!r}')
    return parts


def _operation_key(resolved: ResolvedInputs) -> str:
    try:
        return store.AttemptIdentity(
            work_id=resolved.work_id, design_revision=resolved.design_revision, stage=resolved.stage,
            ordinal=resolved.ordinal, profile_digest=resolved.profile_digest, planned_workspace='pending',
            policy_digest=resolved.policy_digest, agent_manifest_digest=resolved.agent_manifest_digest).operation_key
    except store.InvalidIdentity as exc:
        raise DispatchRefused('IDENTITY_INVALID', str(exc)) from None


def workspace_host_path(resolved: ResolvedInputs, workspaces, operation_key: str) -> Path:
    """The attempt's host workspace: ``planned_workspace`` under the ``workspaces`` category of
    the integrations/paths resolution. Refuses a planned workspace outside the fixed rule's grammar
    or not this attempt's, a reserved device name, and an existing link, junction, reparse point
    or non-directory from the category down. Reads only (lstat); creates nothing."""
    parts = _workspace_parts(resolved.planned_workspace)
    expected = planned_workspace(resolved.repository, resolved.work_id, store.attempt_id_for(operation_key))
    if resolved.planned_workspace != expected:
        raise DispatchRefused('WORKSPACE_NOT_PLANNED', f'{resolved.planned_workspace!r} is not this attempt\'s '
                              f'workspace {expected!r}')
    if not isinstance(workspaces, paths.Resolution) or workspaces.platform != sys.platform \
            or WORKSPACE_CATEGORY not in workspaces.paths or not workspaces.paths[WORKSPACE_CATEGORY].is_absolute():
        raise DispatchRefused('WORKSPACE_CATEGORY_UNAVAILABLE', 'workspaces must be this host\'s integrations/paths '
                              'resolution with an absolute workspaces category')
    category = Path(str(workspaces.paths[WORKSPACE_CATEGORY]))
    for depth in range(len(parts) + 1):
        step = category.joinpath(*parts[:depth])
        try:
            info = os.lstat(step)
        except FileNotFoundError:
            break
        except OSError as exc:
            raise DispatchRefused('WORKSPACE_PATH_UNSAFE', f'{step}: {type(exc).__name__}') from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT \
                or not stat.S_ISDIR(info.st_mode):
            raise DispatchRefused('WORKSPACE_PATH_UNSAFE', f'{step} is a link, junction, reparse point or not a '
                                  'directory', path=str(step))
    return category.joinpath(*parts)


# ---------------------------------------------------------------------------
# E-05.6: the D1 stage's inference grant, held in memory, and the broker's control listener

def _inference_modules():
    """(acp_qualification, inference_control): the pinned ACP registry and the guest inference endpoint, and the
    broker's control listener. Loaded on first use by the D1 stage only, so that importing this module loads no
    inference or credential module (the owner recorders' import census)."""
    return (_load('acp_qualification', HERE / 'acp_qualification.py'),
            _load('aieh_inference_control', REPO / 'integrations' / 'inference' / 'inference_control.py'))


class InferenceGrant:
    """One attempt's inference grant, as the broker's control listener issued it (decision 0015 section 3). The
    token is held in memory only, from the issue to the create's transport call, and is never shown: ``repr`` and
    ``record()`` carry its fingerprint; ``token()`` is the only way to it until ``drop()``."""

    __slots__ = ('fingerprint', 'conversation_id', 'attempt_id', 'family', 'models', 'budget', 'expires_at',
                 '_token')

    def __init__(self, *, token, fingerprint, conversation_id, attempt_id, family, models, budget, expires_at):
        self.fingerprint, self.conversation_id, self.attempt_id = fingerprint, conversation_id, attempt_id
        self.family, self.models, self.budget, self.expires_at = family, models, budget, expires_at
        self._token = token

    @classmethod
    def from_answer(cls, answer) -> 'InferenceGrant':
        """The grant of the control listener's issue answer (``ControlClient.issue`` checked the token's shape,
        its fingerprint and the attempt); its other fields are kept as answered, for the binding check."""
        token = answer.get('token') if isinstance(answer, Mapping) else None
        if not isinstance(token, str) or not secrets_check.broker().TOKEN_SHAPE.fullmatch(token) \
                or answer.get('token_fingerprint') != secrets_check.fingerprint(token):
            raise DispatchRefused('INFERENCE_GRANT_UNAVAILABLE', 'the issue answer does not carry one attempt token')

        def text(name):
            value = answer.get(name)
            return value if isinstance(value, str) else None
        budget = answer.get('budget')
        return cls(token=token, fingerprint=answer['token_fingerprint'], conversation_id=text('conversation_id'),
                   attempt_id=text('attempt_id'), family=text('family'),
                   models=[m for m in answer.get('models') or [] if isinstance(m, str)],
                   budget=_json_value(budget) if isinstance(budget, Mapping) else None,
                   expires_at=text('expires_at'))

    def __repr__(self):
        return f'InferenceGrant(fingerprint={self.fingerprint!r}, attempt_id={self.attempt_id!r}, open={self.open})'

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError('an inference grant is not serializable')

    @property
    def open(self) -> bool:
        return self._token is not None

    def token(self) -> str:
        if self._token is None:
            raise ValueError('the inference grant\'s token is no longer held')
        return self._token

    def drop(self) -> None:
        """Release the in-memory token (this is not revocation: the broker's grant is revoked by its fingerprint)."""
        self._token = None

    def binding(self) -> dict:
        """What the shared check binds the token to: the grant's fingerprint, conversation and attempt."""
        return {'token_fingerprint': self.fingerprint, 'conversation_id': self.conversation_id,
                'attempt_id': self.attempt_id}

    def record(self) -> dict:
        """What a record may carry: the grant's identity by the token's fingerprint, never the token."""
        return {'format': GRANT_FORMAT, 'tokenFingerprint': self.fingerprint, 'conversationId': self.conversation_id,
                'attemptId': self.attempt_id, 'family': self.family, 'models': list(self.models),
                'budget': self.budget, 'expiresAt': self.expires_at}


@dataclass(frozen=True)
class InferenceAccess:
    """The dispatcher's way to the inference broker (E-05.6): its control listener (``inference_control.
    ControlClient`` on 127.0.0.1, or a test's stand-in with ``issue``, ``revoke`` and ``revoke_attempt``) and the
    revoker every revocation names, checked at construction with the broker's own revoker grammar
    (INFERENCE_REVOKER_INVALID). Never the provider key: the dispatcher reads no provider credential."""
    control: object
    revoker: str

    def __post_init__(self):
        if not secrets_check.broker().valid_revoker(self.revoker):
            raise DispatchRefused('INFERENCE_REVOKER_INVALID', 'the revoker must be 1 to '
                                  f'{secrets_check.broker().REVOKER_LIMIT} printable characters')

    @classmethod
    def from_component(cls, raw, *, revoker: str) -> 'InferenceAccess':
        """The control listener of ``components.inference_broker`` (its port through
        ``inference_control.dispatcher_ports``)."""
        _, control = _inference_modules()
        ports = control.dispatcher_ports(raw)
        return cls(control=control.ControlClient(ports['control_port']), revoker=revoker)


@dataclass(frozen=True)
class StageInference:
    """The D1 stage's inference inputs, from trusted, digest-bound sources only (E-05.6): the pinned ACP registry
    entry's two secret names (the token's, the endpoint's), the profile's guest inference endpoint, the broker
    family of the registry entry, the model of the pinned template's ACP block, and the grant's budgets and
    lifetime declared beside the stage template's pin."""
    names: tuple
    endpoint: str
    family: str
    models: tuple
    requests: int
    tokens: int
    ttl_s: int

    def secrets(self, grant: InferenceGrant | None, operation_key: str) -> dict:
        """``check_create_body``'s ``secrets``: the names, the endpoint and the binding to the reserved
        conversation and attempt (a missing grant binds nothing: SECRET_TOKEN_NOT_BOUND)."""
        return {'names': list(self.names), 'endpoint': self.endpoint,
                'binding': {'grant': None if grant is None else grant.binding(),
                            'conversation_id': store.conversation_id_for(operation_key),
                            'attempt_id': store.attempt_id_for(operation_key)}}

    def block(self) -> dict:
        """The secrets block of an admitted body: the token's value as TOKEN_SLOT, the endpoint as itself."""
        token_name, endpoint_name = self.names
        return {token_name: {'kind': secrets_check.STATIC_SECRET, 'value': TOKEN_SLOT},
                endpoint_name: {'kind': secrets_check.STATIC_SECRET, 'value': self.endpoint}}


def _stage_inference(declared: dict, staged: dict, template: dict, stage: str) -> StageInference:
    """The D1 stage's inference inputs (StageInference), or INFERENCE_INPUTS_INVALID."""
    qualification, _ = _inference_modules()

    def invalid(detail):
        return DispatchRefused('INFERENCE_INPUTS_INVALID', f'the {stage} stage: {detail}', stage=stage)

    try:
        names = qualification.registry_secret_names()
    except qualification.QualificationRefused as exc:
        raise invalid(f'the pinned ACP registry extract ({exc.code})') from None
    try:
        endpoint = qualification.inference_endpoint(declared)
    except qualification.QualificationRefused as exc:
        raise invalid(f'the profile\'s guest inference endpoint ({exc.code})') from None
    settings = template.get('agent_settings') if isinstance(template.get('agent_settings'), dict) else {}
    if settings.get('acp_server') != qualification.ACP_SERVER:
        raise invalid(f'the template\'s acp_server is not the pinned registry entry\'s {qualification.ACP_SERVER!r}')
    model, broker = settings.get('acp_model'), secrets_check.broker()
    if not isinstance(model, str) or not broker.MODEL_NAME.fullmatch(model) or broker.WILDCARD.search(model):
        raise invalid('the template\'s acp_model is not one model name of the broker\'s grammar')
    grant = staged[GRANT_KEY]
    return StageInference(names=tuple(names), endpoint=endpoint, family=qualification.ACP_FAMILY, models=(model,),
                          requests=grant['requests'], tokens=grant['tokens'], ttl_s=grant['ttl_s'])


@dataclass(frozen=True)
class AdmittedCreate:
    """The one admitted OpenHands create of an attempt, built from trusted policy only. For the D1 stage
    (E-05.6) the body carries the secrets block with the token's value as TOKEN_SLOT, and ``inference`` the grant
    whose token takes its place, in memory only, immediately before the transport."""
    operation_key: str
    conversation_id: str
    method: str
    path: str
    body_json: str
    mounts_json: str          # the effective mount set the conversation container must have
    planned_workspace: str
    host_workspace: str
    policy_digest: str
    template_bytes: bytes     # the pinned create template, re-checked against its sha256 on send
    routes_bytes: bytes       # the pinned route allowlist every Agent Server call is checked against (E-01.3.1)
    profile_bytes: bytes      # the approved profile.json, re-checked against the profile digest on send (E-05.2)
    inference: InferenceGrant | None = None   # the D1 stage's grant (E-05.6); its token is never in body_json

    @property
    def body(self) -> dict:
        return json.loads(self.body_json)

    @property
    def mounts(self) -> list:
        return json.loads(self.mounts_json)

    def to_json(self) -> dict:
        """The admitted create as a record. Its body is the admitted one (the token's value is the slot) with,
        besides, every word that holds an attempt token, a part of the held one or a provider key's shape
        redacted: a record never carries a token, whatever the body holds (E-05.6)."""
        held = self.inference.token() if self.inference is not None and self.inference.open else None

        def clean(node):
            if isinstance(node, dict):
                return {clean(key): clean(value) for key, value in node.items()}
            if isinstance(node, list):
                return [clean(value) for value in node]
            return secrets_check.redact(node, held) if isinstance(node, str) else node
        record = {'format': ADMITTED_FORMAT, 'operation_key': self.operation_key,
                  'conversation_id': self.conversation_id, 'route': {'method': self.method, 'path': self.path},
                  'body': clean(self.body), 'mounts': self.mounts,
                  'workspace': {'planned': self.planned_workspace, 'host': self.host_workspace},
                  'policy_digest': self.policy_digest,
                  'create_template_sha256': hashlib.sha256(self.template_bytes).hexdigest(),
                  'routes_sha256': hashlib.sha256(self.routes_bytes).hexdigest()}
        if self.inference is not None:   # the D1 stage: the grant by its token's fingerprint (E-05.6)
            record['inference_grant'] = self.inference.record()
        return record


def _resolved_admission(resolved: ResolvedInputs) -> dict:
    """The admission policy the attempt was reserved under, from its digest-bound policy inputs."""
    if _sha256(resolved.policy_inputs_json) != resolved.policy_digest:
        raise DispatchRefused('ADMISSION_MISMATCH', 'the policy inputs do not have the policy digest')
    try:
        inputs = _strict_loads(resolved.policy_inputs_json)
    except ValueError:
        raise DispatchRefused('ADMISSION_MISMATCH', 'the policy inputs are not strict JSON') from None
    if not isinstance(inputs, dict) or inputs.get('format') != POLICY_FORMAT \
            or not _same(inputs.get('profile'), {'id': resolved.profile, 'sha256': resolved.profile_digest}):
        raise DispatchRefused('ADMISSION_MISMATCH', f'the policy inputs are not {POLICY_FORMAT} of profile '
                              f'{resolved.profile} at {resolved.profile_digest}')
    admission = inputs.get('admission')
    check_admission_policy(admission, resolved.profile)
    return admission


def _check_stage_content(declared: dict, resolved: ResolvedInputs, admission: dict,
                         template: dict) -> StageInference | None:
    """For the D1 stage (the stage the approved profile's stage_create_template names, E-05.2): the reserved
    policy's create template is that pin (``ADMISSION_MISMATCH`` otherwise), the template's content passes
    ``check_stage_template``, and its inference inputs are admissible (E-05.6); returns them. None for any other
    stage."""
    staged = stage_create_template(declared, resolved.profile)
    if staged is None or staged['stage'] != resolved.stage:
        return None
    if not _same({'path': staged['path'], 'sha256': staged['sha256']}, admission['create_template']):
        raise DispatchRefused('ADMISSION_MISMATCH', f'the reserved create template is not the {resolved.stage} '
                              'stage\'s pinned template')
    check_stage_template(template, resolved.stage)
    for name in SECRET_FIELDS:   # E-05.6: the secrets are the attempt's, added at admission, never pinned
        if name in template:
            raise DispatchRefused('BODY_FIELD_UNKNOWN', f'the {resolved.stage} stage\'s pinned create template may '
                                  f'not carry {name!r}: admit_secrets adds the attempt\'s', field=name)
    return _stage_inference(declared, staged, template, resolved.stage)


SCRUBBED_DETAIL = '<withheld: the text held a part of the attempt token>'
_OUTSIDE_TOKEN_ALPHABET = re.compile(r'[^A-Za-z0-9_-]')


def _scrubbed(refusal: DispatchRefused, token: str | None) -> DispatchRefused:
    """A new refusal of REFUSAL's code, with no ``__context__`` or ``__cause__`` (the caller raises it outside the
    ``except`` that caught REFUSAL), whose detail and context strings are cleaned: a string that, with every
    character outside the token's alphabet removed, still holds a part of the held TOKEN of
    ``create_secrets.FRAGMENT`` or more characters is replaced whole by SCRUBBED_DETAIL (a token split by dots or
    spaces is caught); in any other, every word that holds an attempt token, a part of TOKEN or a provider key's
    shape is redacted (``create_secrets.redact``, as the shared check redacts its own). A refusal of a body that
    held the token reaches the store and the caller without it, whichever check refused it."""
    parts = secrets_check.fragments(token)

    def clean(value):
        if isinstance(value, str):
            joined = _OUTSIDE_TOKEN_ALPHABET.sub('', value)
            if any(part in joined for part in parts):
                return SCRUBBED_DETAIL
            return secrets_check.redact(value, token)
        if isinstance(value, Mapping):
            return {clean(str(k)): clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return value
    return DispatchRefused(refusal.code, clean(refusal.detail), **clean(dict(refusal.context)))


def _token_value(body: dict, inference: StageInference):
    """The token secret's value in BODY, or None."""
    secrets = body.get('secrets')
    source = secrets.get(inference.names[0]) if isinstance(secrets, dict) else None
    return source.get('value') if isinstance(source, dict) else None


def _wire_body(body: dict, inference: StageInference, grant: InferenceGrant | None) -> dict:
    """BODY with the grant's token in the token secret's place (TOKEN_SLOT), in memory only; any other body as is."""
    secrets = body.get('secrets')
    source = secrets.get(inference.names[0]) if isinstance(secrets, dict) else None
    if grant is not None and grant.open and isinstance(source, dict) and source.get('value') == TOKEN_SLOT:
        body = {**body, 'secrets': {**secrets, inference.names[0]: {**source, 'value': grant.token()}}}
    return body


def _admitted_checks(admitted: AdmittedCreate, *, resolved: ResolvedInputs, admission: dict, workspaces,
                     secrets: bool) -> tuple[dict, StageInference | None]:
    """Every admission check on a built request; returns the validated body (the one to send) and, for the D1
    stage, its inference inputs. With SECRETS false (``admit``: every input but the secrets) the D1 stage's body
    carries no secrets block and no grant; with SECRETS true (``admit_secrets``, ``send_create``) it must carry the
    block, checked with the grant's token in place and bound to this attempt (E-05.6)."""
    key = _operation_key(resolved)
    conversation_id = store.conversation_id_for(key)
    if (admitted.operation_key, admitted.conversation_id, admitted.policy_digest) != \
            (key, conversation_id, resolved.policy_digest):
        raise DispatchRefused('ADMISSION_MISMATCH', 'the admitted request is not this reserved attempt\'s')
    host = workspace_host_path(resolved, workspaces, key)
    if (admitted.planned_workspace, admitted.host_workspace) != (resolved.planned_workspace, str(host)):
        raise DispatchRefused('WORKSPACE_NOT_PLANNED', f'the admitted workspace {admitted.host_workspace!r} is '
                              f'not {str(host)!r}')
    template_raw = admitted.template_bytes if isinstance(admitted.template_bytes, bytes) else b''
    if hashlib.sha256(template_raw).hexdigest() != admission['create_template']['sha256']:
        raise DispatchRefused('PROFILE_ARTIFACT_DRIFTED', 'the admitted create template is not the pinned one')
    template = _artifact_object(template_raw, 'create template')
    # E-05.2: the approved profile the admitted create carries (its bytes must have the reserved profile digest)
    # says whether this is the D1 stage; if so the template's content is checked again here.
    profile_raw = admitted.profile_bytes
    _, _, declared = _read_checked_profile(resolved.profile, resolved.profile_digest, lambda _name: profile_raw)
    inference = _check_stage_content(declared, resolved, admission, template)
    if admitted.inference is not None and (inference is None or not secrets):
        raise DispatchRefused('ADMISSION_MISMATCH', 'the admitted create holds an inference grant where no secrets '
                              'are admitted (another stage, or before admit_secrets)')
    routes_raw = admitted.routes_bytes if isinstance(admitted.routes_bytes, bytes) else b''
    if hashlib.sha256(routes_raw).hexdigest() != admission['routes']['sha256']:
        raise DispatchRefused('PROFILE_ARTIFACT_DRIFTED', 'the admitted route allowlist is not the pinned one')
    _check_route_allowlist(routes_raw, admission['route'])
    if not _same({'method': admitted.method, 'path': admitted.path}, admission['route']):
        raise DispatchRefused('ROUTE_NOT_ALLOWLISTED', f'{admitted.method} {admitted.path} is not the admitted '
                              f'create route {admission["route"]}')
    try:
        body = _strict_loads(admitted.body_json)
    except (TypeError, ValueError):
        raise DispatchRefused('BODY_MALFORMED', 'the create body is not strict JSON') from None
    if inference is None or not secrets:
        check_create_body(body, admission=admission, template=template, conversation_id=conversation_id)
    else:
        slot = _token_value(body, inference) == TOKEN_SLOT
        body, caught = _wire_body(body, inference, admitted.inference), None
        try:
            check_create_body(body, admission=admission, template=template, conversation_id=conversation_id,
                              secrets=inference.secrets(admitted.inference, key))
            if not slot:   # the token passed the check, but it came from the admitted body, not the held grant
                raise DispatchRefused('SECRET_NOT_FROM_GRANT', f'{inference.names[0]} in the admitted body is not '
                                      f'the slot {TOKEN_SLOT}')
        except DispatchRefused as refusal:
            caught = refusal
        if caught is not None:   # raised outside the except: the scrubbed refusal holds no chain to the original
            held = admitted.inference.token() if admitted.inference is not None and admitted.inference.open else None
            scrubbed, caught = _scrubbed(caught, held), None
            raise scrubbed
    expected = _binds_for(admission['mounts']['binds'], conversation_id.replace('-', ''))
    try:
        mounts = _strict_loads(admitted.mounts_json)
    except (TypeError, ValueError):
        mounts = None
    if not _same(mounts, expected):
        raise DispatchRefused('MOUNTS_NOT_DECLARED', 'the admitted mount set is not exactly the declared one',
                              declared=expected)
    return body, inference


def _check_admitted(admitted: AdmittedCreate, *, resolved: ResolvedInputs, admission: dict, workspaces,
                    secrets: bool = True) -> dict:
    """Every admission check on a built request; returns the validated body (the one to send)."""
    return _admitted_checks(admitted, resolved=resolved, admission=admission, workspaces=workspaces,
                            secrets=secrets)[0]


def stage_inference(admitted: AdmittedCreate, *, resolved: ResolvedInputs) -> StageInference | None:
    """The D1 stage's inference inputs of an admitted create (E-05.6), re-derived from the approved profile and
    the pinned template it carries; None for every other stage."""
    admission = _resolved_admission(resolved)
    template_raw = admitted.template_bytes if isinstance(admitted.template_bytes, bytes) else b''
    if hashlib.sha256(template_raw).hexdigest() != admission['create_template']['sha256']:
        raise DispatchRefused('PROFILE_ARTIFACT_DRIFTED', 'the admitted create template is not the pinned one')
    template = _artifact_object(template_raw, 'create template')
    _, _, declared = _read_checked_profile(resolved.profile, resolved.profile_digest,
                                           lambda _name: admitted.profile_bytes)
    return _check_stage_content(declared, resolved, admission, template)


def admit(resolved: ResolvedInputs, *, manifest: ApprovedInputs, workspaces,
          read_profile: Callable[[str], bytes] = read_profile_file,
          read_artifact: Callable[[str], bytes] = read_profile_artifact) -> AdmittedCreate:
    """Admit the OpenHands create of a resolved (and reserved) attempt, or raise DispatchRefused.

    ``workspaces`` is the host's ``aieh_paths`` resolution (``aieh_paths.resolve()`` in live use);
    ``read_profile`` and ``read_artifact`` read the approved profile and the artifacts it pins.
    The request is built from trusted policy only; nothing is written and nothing is sent.

    For the D1 stage (E-05.6) this admits every input but the secrets: the body carries no secrets block yet,
    and its inference inputs (``stage_inference``) are checked. The token is requested only after this, and
    ``admit_secrets`` adds the block; ``send_create`` refuses a D1 create without it.
    """
    if not isinstance(resolved, ResolvedInputs):
        raise TypeError('resolved must be ResolvedInputs (resolve)')
    if not isinstance(manifest, ApprovedInputs):
        raise TypeError('manifest must be ApprovedInputs (load_manifest or parse_manifest)')
    _require_promoted(manifest)  # P-04.3: before anything is read
    entry = manifest._index()['profiles'].get(resolved.profile)
    if (resolved.manifest_sha256, resolved.manifest_version) != (manifest.sha256, manifest.version) \
            or entry is None or entry['sha256'] != resolved.profile_digest:
        raise DispatchRefused('ADMISSION_MISMATCH', 'the resolved inputs were not approved by this manifest')
    profile_raw, _, declared = _read_checked_profile(resolved.profile, resolved.profile_digest, read_profile)
    admission = _resolved_admission(resolved)
    if not _same(admission, admission_policy(declared, resolved.profile, resolved.stage)):
        raise DispatchRefused('ADMISSION_MISMATCH', 'the policy inputs do not carry the approved profile\'s '
                              'admission policy')
    key = _operation_key(resolved)
    host = workspace_host_path(resolved, workspaces, key)
    template_raw = _read_pinned(read_artifact, admission['create_template'], 'create template')
    template = _artifact_object(template_raw, 'create template')
    _check_stage_content(declared, resolved, admission, template)  # the D1 stage (E-05.2)
    routes_raw = _read_pinned(read_artifact, admission['routes'], 'route allowlist')
    _check_route_allowlist(routes_raw, admission['route'])
    conversation_id = store.conversation_id_for(key)
    body = json.loads(_canonical(template))
    body['conversation_id'] = conversation_id
    admitted = AdmittedCreate(
        operation_key=key, conversation_id=conversation_id, method=admission['route']['method'],
        path=admission['route']['path'], body_json=_canonical(body),
        mounts_json=_canonical(_binds_for(admission['mounts']['binds'], conversation_id.replace('-', ''))),
        planned_workspace=resolved.planned_workspace, host_workspace=str(host),
        policy_digest=resolved.policy_digest, template_bytes=template_raw, routes_bytes=routes_raw,
        profile_bytes=profile_raw)
    _check_admitted(admitted, resolved=resolved, admission=admission, workspaces=workspaces, secrets=False)
    return admitted


def admit_secrets(admitted: AdmittedCreate, *, resolved: ResolvedInputs, workspaces,
                  grant: InferenceGrant) -> AdmittedCreate:
    """The D1 stage's create with its secrets (E-05.6): ADMITTED (``admit``'s, checked again without secrets) with
    the secrets block of exactly the pinned registry entry's two names, each a StaticSecret, ``secrets_encrypted``
    false: the token's value TOKEN_SLOT (GRANT's token takes its place only in the checks and the send), the
    endpoint the profile's guest inference endpoint. The result is checked as ``send_create`` will check it: the
    shared secrets check, the token bound to GRANT and GRANT to this reserved conversation and attempt. Refuses a
    stage that carries no secrets (ADMISSION_MISMATCH)."""
    if not isinstance(admitted, AdmittedCreate):
        raise TypeError('admitted must be AdmittedCreate (admit)')
    if not isinstance(grant, InferenceGrant):
        raise TypeError('grant must be an InferenceGrant (the broker\'s issue answer)')
    admission = _resolved_admission(resolved)
    body, inference = _admitted_checks(admitted, resolved=resolved, admission=admission, workspaces=workspaces,
                                       secrets=False)
    if inference is None:
        raise DispatchRefused('ADMISSION_MISMATCH', f'the {resolved.stage} stage\'s create carries no secrets')
    body = {**body, 'secrets': inference.block(), 'secrets_encrypted': False}
    with_secrets = dataclasses.replace(admitted, body_json=_canonical(body), inference=grant)
    _check_admitted(with_secrets, resolved=resolved, admission=admission, workspaces=workspaces)
    return with_secrets


def send_create(admitted: AdmittedCreate, *, resolved: ResolvedInputs, workspaces,
                transport: Callable[[str, str, dict | None], object]):
    """Validate the admitted create again, against the policy the attempt was reserved under
    (``resolved``, the record ``reserve_attempt`` stored), immediately before the transport; then,
    through an ``AgentServerClient`` on the pinned route allowlist, read ``GET /server_info`` and
    refuse unless decision 0001's preconditions P1 to P5 hold (``server_preconditions``); then send
    the create exactly once and return the transport's answer. A refusal never sends the create
    (an admission refusal calls the transport zero times). Nothing is retried and no other runtime
    is ever tried.

    For the D1 stage (E-05.6) the body checked and sent is the admitted one with the grant's token in the
    token secret's place, built in memory here: the secrets block is checked again by the shared check, the
    token bound to the admitted grant and the grant to this reserved conversation and attempt. A D1 create
    without its secrets block or its grant is refused."""
    if not isinstance(admitted, AdmittedCreate):
        raise TypeError('admitted must be AdmittedCreate (admit)')
    if not isinstance(resolved, ResolvedInputs):
        raise TypeError('resolved must be ResolvedInputs (resolve)')
    admission = _resolved_admission(resolved)
    body = _check_admitted(admitted, resolved=resolved, admission=admission, workspaces=workspaces)
    client = AgentServerClient(admitted.routes_bytes, transport, routes_sha256=admission['routes']['sha256'])
    try:
        info = client.call(SERVER_INFO_ROUTE['method'], SERVER_INFO_ROUTE['path'])
    except DispatchRefused:
        raise
    except Exception as exc:  # no answer: no precondition is established, and nothing was created
        raise DispatchRefused('SERVER_PRECONDITION_FAILED', f'GET /server_info was not answered: '
                              f'{type(exc).__name__}', failed=list(PRECONDITIONS), observed=None) from None
    server_preconditions(info, client.version)
    return client.call(admitted.method, admitted.path, body=body)


# ---------------------------------------------------------------------------
# The native conversation create (E-01.3.1)
#
# dispatch(): resolve -> reserve_attempt -> (the reserved record re-read from the store) -> admit
# -> create_workspace -> transition dispatched -> send_create (GET /server_info, P1 to P5, POST)
# -> the returned conversation id recorded in the store. Every Agent Server call goes through
# AgentServerClient, which refuses any route the profile's pinned allowlist does not list exactly
# once as dispatcher "allowed", before the transport is called.

SERVER_INFO_ROUTE = {'method': 'GET', 'path': '/server_info'}   # server_details_router.py, public
REQUIRED_CAPABILITIES = ('conversation_runtime_routes_v1', 'idempotent_conversation_create_v1')
# Decision 0001 s1 and s2, as GET /server_info shows them (observed at 1.60.1: F-04.1c section 3).
PRECONDITIONS = {
    'P1': '/server_info answers 2xx with a JSON object whose version is the pinned API version (the version of '
          'the pinned route allowlist, decision 0001 s1)',
    'P2': 'capabilities include conversation_runtime_routes_v1 (decision 0001 s2)',
    'P3': 'capabilities include idempotent_conversation_create_v1 (decision 0001 s2, the retry rule)',
    'P4': 'conversation_runtime is docker (decision 0001 s2, required configuration)',
    'P5': 'available_conversation_runtimes is empty: the runtime is not selectable (decision 0001 s2, '
          'conversation_runtime_selectable=false; hybrid mode only by recorded exception, and none is recorded)',
}
# Path parameters of the dispatcher-allowed routes, each in a grammar that cannot leave its segment.
ROUTE_PARAMETERS = {'conversation_id': UUID_RE, 'event_id': re.compile(r'[A-Za-z0-9_-]{1,128}')}
PLACEHOLDER_RE = re.compile(r'\{([^{}]*)\}')
BODYLESS_METHODS = ('GET', 'HEAD', 'DELETE')
CREATE_STATUSES = {201: True, 200: False}  # status -> created; 200 returns the existing one (F-04.2 s4.5)
EXECUTION_REF_PREFIX = 'openhands:conversation/'
DISPATCHED_FORMAT = 'ai-engineering-harness/dispatch/create-dispatched/v1'
RECEIPT_FORMAT = 'ai-engineering-harness/dispatch/create-receipt/v1'
RESULT_FORMAT = 'ai-engineering-harness/dispatch/dispatch-result/v1'


class AgentServerClient:
    """The dispatcher's only way to the Agent Server: ``call(method, route, params=, body=)`` sends
    ``transport(method, path, body)`` only when ``(method, route)`` is listed exactly once in the
    profile's pinned route allowlist (``agent-server/routes.json``, S-01.3.1) with ``dispatcher``
    ``allowed``, and its path parameters are exactly the route's placeholders, each in its grammar.
    Anything else is refused before the transport is called. ``version`` is the allowlist's API
    version (the pinned one, decision 0001 s1).

    The transport contract: ``transport(method, path, body)`` returns the HTTP answer as
    ``{"status": <int>, "body": <parsed JSON>}`` (the shape tools/guest.py's API calls return) and
    raises when there is no answer. The live one is ``guest_transport.GuestTransport`` (E-01.3.3): over
    tools/guest.py's GuestApi as the guest login that holds the management key, the key read in the guest
    only (decision 0013 point 1, bootstrap); tests inject fakes. While a role token is delivered
    (attempt_tokens.py, E-01.3.3), a call whose path or body carries it or its fingerprint is
    ROLE_TOKEN_EXPOSURE."""

    def __init__(self, routes_raw: bytes, transport: Callable[[str, str, dict | None], object], *,
                 routes_sha256: str):
        if not callable(transport):
            raise TypeError('transport must be callable as transport(method, path, body)')
        raw = routes_raw if isinstance(routes_raw, bytes) else b''
        if hashlib.sha256(raw).hexdigest() != routes_sha256:
            raise DispatchRefused('PROFILE_ARTIFACT_DRIFTED', 'the route allowlist is not the pinned one')
        data = _artifact_object(raw, 'route allowlist')
        routes, version = data.get('routes'), data.get('version')
        if data.get('schema') != ROUTES_SCHEMA or not isinstance(routes, list) \
                or not isinstance(version, str) or not version:
            raise DispatchRefused('PROFILE_ARTIFACT_INVALID', f'the route allowlist is not {ROUTES_SCHEMA} with a '
                                  'version')
        listed = [(r.get('method'), r.get('path'), r.get('dispatcher')) for r in routes if isinstance(r, dict)]
        counts: dict = {}
        for method, path, _ in listed:
            counts[(method, path)] = counts.get((method, path), 0) + 1
        self._allowed = frozenset((m, p) for m, p, d in listed
                                  if d == 'allowed' and isinstance(m, str) and isinstance(p, str)
                                  and counts[(m, p)] == 1)
        self._transport, self.version, self.routes_sha256 = transport, version, routes_sha256

    def allows(self, method, route) -> bool:
        return (method, route) in self._allowed

    def call(self, method: str, route: str, *, params: Mapping[str, str] | None = None, body: dict | None = None):
        if not (isinstance(method, str) and isinstance(route, str)) or not self.allows(method, route):
            raise DispatchRefused('ROUTE_NOT_ALLOWLISTED', f'{method} {route} is not a dispatcher-allowed route of '
                                  'the pinned route allowlist', method=str(method), route=str(route))
        params = {} if params is None else params
        names = PLACEHOLDER_RE.findall(route)
        if not isinstance(params, Mapping) or sorted(params) != sorted(set(names)) or len(set(names)) != len(names):
            raise DispatchRefused('ROUTE_PARAMETER_INVALID', f'{route} takes {sorted(names)}, not '
                                  f'{sorted(map(str, params)) if isinstance(params, Mapping) else params!r}')
        path = route
        for name in names:
            value, grammar = params[name], ROUTE_PARAMETERS.get(name)
            if grammar is None or not isinstance(value, str) or grammar.fullmatch(value) is None:
                raise DispatchRefused('ROUTE_PARAMETER_INVALID', f'{name} of {route} is not in its grammar',
                                      parameter=name)
            path = path.replace('{' + name + '}', value)
        if method in BODYLESS_METHODS and body is not None:
            raise DispatchRefused('BODY_MALFORMED', f'{method} {route} takes no body')
        if _carries_held_role_token(path, body):
            raise DispatchRefused('ROLE_TOKEN_EXPOSURE', f'{method} {route} would carry a delivered role token or its '
                                  'fingerprint into the guest', method=method, route=route)
        return self._transport(method, path, body)


# The role tokens open in a dispatcher attempt context (attempt_tokens.py, E-01.3.3), held here as the sha256
# of the token and its fingerprint only. No Agent Server call may carry one: a conversation container never
# holds a role token (decision 0013 point 7). Checked at the client, the dispatcher's one way to the server.
# Two attempts of one stage hold the same standing token: each hold is counted. A release ends the guard's
# hold only; it is not Gitea revocation (the standing token stays valid; attempt_tokens.py, lifecycle 2).
_HELD_ROLE_TOKENS: dict[str, list] = {}
_HELD_LOCK = threading.Lock()
_HEX_RUN = re.compile(r'[0-9a-f]{40,}')


def hold_role_token(token_sha256: str, fingerprint: str) -> None:
    with _HELD_LOCK:
        _HELD_ROLE_TOKENS.setdefault(token_sha256, [fingerprint, 0])[1] += 1


def release_role_token(token_sha256: str) -> None:
    with _HELD_LOCK:
        held = _HELD_ROLE_TOKENS.get(token_sha256)
        if held is not None:
            held[1] -= 1
            if held[1] <= 0:
                del _HELD_ROLE_TOKENS[token_sha256]


def _carries_held_role_token(path: str, body) -> bool:
    """Whether the call's path or body holds an open role token (any 40 consecutive lower-case hex digits,
    wherever they stand, whose sha256 is held) or the fingerprint of one (with or without ``sha256:``)."""
    with _HELD_LOCK:
        held = {digest: fingerprint for digest, (fingerprint, _count) in _HELD_ROLE_TOKENS.items()}
    if not held:
        return False
    try:
        text = path + '\n' + json.dumps(body, sort_keys=True, ensure_ascii=True)
    except (TypeError, ValueError):
        text = path + '\n' + repr(body)
    for run in _HEX_RUN.findall(text):
        for start in range(len(run) - 39):
            if hashlib.sha256(run[start:start + 40].encode('ascii')).hexdigest() in held:
                return True
    return any(fp in text or fp.partition(':')[2] in text for fp in held.values())


def _json_value(value):
    """``value`` when it is plain JSON, else its type name (refusal context reaches the store)."""
    try:
        _canonical(value)
        return value
    except (TypeError, ValueError):
        return f'<{type(value).__name__}>'


def server_preconditions(response, pinned_version: str) -> dict:
    """Decision 0001's preconditions on a ``GET /server_info`` answer (``PRECONDITIONS``, P1 to
    P5). Returns the observed fields, or raises SERVER_PRECONDITION_FAILED naming every failed one."""
    status = response.get('status') if isinstance(response, Mapping) else None
    body = response.get('body') if isinstance(response, Mapping) else None
    answered = type(status) is int and 200 <= status < 300 and isinstance(body, dict)
    info = body if answered else {}
    capabilities = info.get('capabilities')
    listed = isinstance(capabilities, list) and all(isinstance(c, str) for c in capabilities)
    runtime, runtimes = info.get('conversation_runtime'), info.get('available_conversation_runtimes')
    results = {
        'P1': answered and type(info.get('version')) is str and info['version'] == pinned_version,
        'P2': listed and REQUIRED_CAPABILITIES[0] in capabilities,
        'P3': listed and REQUIRED_CAPABILITIES[1] in capabilities,
        'P4': type(runtime) is str and runtime == DOCKER_RUNTIME,
        'P5': type(runtimes) is list and runtimes == [],
    }
    observed = {'status': status if type(status) is int else None, 'pinned_version': pinned_version,
                **{key: _json_value(info.get(key)) for key in (
                    'version', 'conversation_runtime', 'available_conversation_runtimes', 'capabilities')}}
    failed = [name for name, ok in results.items() if not ok]
    if failed:
        raise DispatchRefused('SERVER_PRECONDITION_FAILED', f'/server_info fails {", ".join(failed)}',
                              failed=failed, observed=observed)
    return observed


def reserved_inputs(integration_store, operation_key: str) -> ResolvedInputs:
    """The attempt's dispatch record re-read from the store: the stored intent, checked against its
    digest, its typed identity row and the record's own intent (``workRef``, ``outcomeRef`` and the
    identity included), and the attempt still ``reserved``. RESERVATION_INVALID or
    ATTEMPT_NOT_RESERVED otherwise."""
    return stored_inputs(integration_store, operation_key, state='reserved')


# The refusal of an attempt found in another state than the reader needs.
_STATE_REFUSALS = {'reserved': 'ATTEMPT_NOT_RESERVED', 'confirmed': 'ATTEMPT_NOT_CONFIRMED'}


def stored_inputs(integration_store, operation_key: str, *, state: str) -> ResolvedInputs:
    """``reserved_inputs`` for an attempt that must be in STATE (``reserved``, or ``confirmed`` for the
    role-token delivery of E-01.3.3): the same checks of the stored record; ATTEMPT_NOT_RESERVED or
    ATTEMPT_NOT_CONFIRMED when the attempt is in another state."""
    if state not in _STATE_REFUSALS:
        raise ValueError(f'state must be one of {sorted(_STATE_REFUSALS)}')
    reservation = integration_store.get(operation_key)
    if reservation is None:
        raise DispatchRefused('RESERVATION_INVALID', f'no reservation under {operation_key!r}')
    if reservation.state != state:
        raise DispatchRefused(_STATE_REFUSALS[state], f'{operation_key!r} is {reservation.state}',
                              state=reservation.state)
    if _sha256(reservation.intent_json) != reservation.intent_digest:
        raise DispatchRefused('RESERVATION_INVALID', 'the stored intent does not have its digest')
    try:
        intent = _strict_loads(reservation.intent_json)
    except ValueError:
        raise DispatchRefused('RESERVATION_INVALID', 'the stored intent is not strict JSON') from None
    resolved = ResolvedInputs.from_json(intent.get(INTENT_KEY) if isinstance(intent, dict) else None)
    try:
        identity = resolved.attempt_identity()
    except store.InvalidIdentity as exc:
        raise DispatchRefused('RESERVATION_INVALID', f'the stored record: {exc}') from None
    typed = integration_store.attempt_identity(operation_key)
    if identity.operation_key != operation_key or typed is None or typed.identity != identity:
        raise DispatchRefused('RESERVATION_INVALID', 'the stored record is not the typed identity reserved under '
                              f'{operation_key!r}')
    expected = _canonical({**resolved.intent(), store.IDENTITY_INTENT_KEY: identity.as_intent()})
    if expected != reservation.intent_json:
        raise DispatchRefused('RESERVATION_INVALID', 'the stored intent is not exactly the dispatch record with its '
                              'workRef, outcomeRef and typed identity')
    return resolved


def _real_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise DispatchRefused('WORKSPACE_PATH_UNSAFE', f'{path}: {type(exc).__name__}') from None
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT \
            or not stat.S_ISDIR(info.st_mode):
        raise DispatchRefused('WORKSPACE_PATH_UNSAFE', f'{path} is a link, junction, reparse point or not a directory',
                              path=str(path))


def create_workspace(admitted: AdmittedCreate, *, resolved: ResolvedInputs, workspaces) -> Path:
    """Create the admitted attempt's host workspace, after admission and without following links:
    the ``workspaces`` category (through ``aieh_paths.ensure`` when it is missing), then one
    directory per part, each created with a single ``mkdir`` under a parent just checked (``lstat``)
    to be a plain directory, and checked again after it; then the whole walk again. An existing link,
    junction, reparse point or file anywhere from the category down is WORKSPACE_PATH_UNSAFE."""
    if not isinstance(admitted, AdmittedCreate):
        raise TypeError('admitted must be AdmittedCreate (admit)')
    key = _operation_key(resolved)
    host = workspace_host_path(resolved, workspaces, key)
    if (admitted.operation_key, admitted.planned_workspace, admitted.host_workspace) != \
            (key, resolved.planned_workspace, str(host)):
        raise DispatchRefused('WORKSPACE_NOT_PLANNED', f'the admitted workspace {admitted.host_workspace!r} is '
                              f'not {str(host)!r}')
    category = Path(str(workspaces.paths[WORKSPACE_CATEGORY]))
    if not os.path.lexists(category):
        try:
            paths.ensure(WORKSPACE_CATEGORY, workspaces)
        except (paths.PathsError, OSError, ValueError, KeyError) as exc:
            raise DispatchRefused('WORKSPACE_CATEGORY_UNAVAILABLE', f'{category}: {exc}') from None
    step = category
    _real_directory(step)
    for part in _workspace_parts(resolved.planned_workspace):
        step = step / part
        try:
            os.mkdir(step)
        except FileExistsError:
            pass
        except OSError as exc:
            raise DispatchRefused('WORKSPACE_PATH_UNSAFE', f'{step}: {type(exc).__name__}') from None
        _real_directory(step)
    if workspace_host_path(resolved, workspaces, key) != step:
        raise DispatchRefused('WORKSPACE_NOT_PLANNED', f'{step} is not the planned workspace')
    return step


class CreateOutcomeUnknown(Exception):
    """The create was sent and its outcome is not known (no answer, a 5xx, or a 2xx that is not the
    reserved conversation): the attempt is ``unknown`` and must be reconciled by its reserved
    conversation id before anything else (store lifecycle contract; blueprint step 05)."""

    def __init__(self, operation_key: str, detail: str, **context):
        self.operation_key, self.detail, self.context = operation_key, detail, context
        super().__init__(f'{operation_key}: {detail}')


@dataclass(frozen=True)
class DispatchResult:
    """A confirmed create: the returned native identifiers, and nothing else of the answer."""
    operation_key: str
    attempt_id: str
    conversation_id: str
    execution_ref: str
    http_status: int
    created: bool
    host_workspace: str
    inference_grant: dict | None = None   # the D1 stage's grant record, by fingerprint (E-05.6)

    def to_json(self) -> dict:
        record = {'format': RESULT_FORMAT, 'operation_key': self.operation_key, 'attempt_id': self.attempt_id,
                  'conversation_id': self.conversation_id, 'execution_ref': self.execution_ref,
                  'http_status': self.http_status, 'created': self.created, 'host_workspace': self.host_workspace}
        if self.inference_grant is not None:
            record['inference_grant'] = self.inference_grant
        return record


def create_receipt(answer, conversation_id: str) -> dict | None:
    """The typed identifiers of a create answer (ConversationInfo, observed at 1.60.1: F-04.2
    section 4.2): its native ``id``, the HTTP status and whether it was created (201) or already
    existed (200). None unless the answer is 200 or 201 with an object whose ``id`` is the
    reserved conversation id. Nothing else of the answer is kept."""
    status = answer.get('status') if isinstance(answer, Mapping) else None
    body = answer.get('body') if isinstance(answer, Mapping) else None
    if type(status) is not int or status not in CREATE_STATUSES or not isinstance(body, Mapping) \
            or not isinstance(body.get('id'), str) or body['id'] != conversation_id:
        return None
    return {'format': RECEIPT_FORMAT, 'executionRef': f'{EXECUTION_REF_PREFIX}{body["id"]}',
            'conversationId': body['id'], 'httpStatus': status, 'created': CREATE_STATUSES[status]}


def _refusal_detail(refusal: DispatchRefused, **extra) -> dict:
    """The refusal as a transition detail: refusal/v1, its context reduced to plain JSON."""
    return {**refusal.to_json(), 'context': _json_value(refusal.context), **extra}


def _mark(integration_store, key: str, from_state: str, to_state: str, actor: str, reason: str, detail) -> None:
    integration_store.transition(key, to_state, actor=actor, reason=reason, detail=detail, expected_from=from_state)


def _code_of(exc) -> str:
    """A stable code of a failed broker call (the control listener's own code), never its message."""
    code = getattr(exc, 'code', None)
    return code if isinstance(code, str) and CODE_RE.fullmatch(code) else type(exc).__name__


def _issue(inference: InferenceAccess, resolved: ResolvedInputs, staged: StageInference) -> InferenceGrant:
    """The D1 stage's attempt token from the broker's control listener (decision 0015 section 3.2, E-05.6), for
    the reserved conversation and attempt, of the stage's family and model, with its budgets and lifetime. Raises
    what the control call raises; ``_GrantCustody.issue`` journals the call and decides what its failure means."""
    key = _operation_key(resolved)
    answer = inference.control.issue(store.conversation_id_for(key), store.attempt_id_for(key), staged.family,
                                     list(staged.models), staged.requests, staged.tokens, staged.ttl_s)
    return InferenceGrant.from_answer(answer)


def _revoke(inference: InferenceAccess, selectors: list, conversation_id: str, attempt_id: str,
            trigger: str = REVOCATION_TRIGGER) -> dict:
    """Revoke through the broker's control listener by each of SELECTORS in turn (``('fingerprint', fp)``, or
    ``('attempt', None)``: the attempt's one grant, by its conversation and attempt); the outcome as a record
    (``inference-revocation/v1``). ``revoked`` is whether no live grant remains: a call revoked it, or the broker
    answers that it is already revoked (GRANT_ALREADY_REVOKED) or holds no such grant (GRANT_UNKNOWN; for the
    attempt's selector, nothing was issued or the grant ended with the broker). The last selector, when it is the
    attempt's, settles the outcome. Never raises: a failure is ``revoked`` false and its code, for the caller to
    record and surface."""
    record = {'format': REVOCATION_FORMAT, 'tokenFingerprint': None, 'attemptId': attempt_id,
              'conversationId': conversation_id, 'selectors': [fp if kind == 'fingerprint' else 'attempt'
                                                               for kind, fp in selectors],
              'trigger': trigger, 'revoker': inference.revoker if isinstance(inference, InferenceAccess) else None}
    outcomes = []
    for kind, fingerprint in selectors:
        try:
            if not isinstance(inference, InferenceAccess):
                raise DispatchRefused('INFERENCE_GRANT_UNAVAILABLE', 'no broker control listener was given')
            if kind == 'fingerprint':
                answer = inference.control.revoke(fingerprint, trigger, inference.revoker)
            else:
                answer = inference.control.revoke_attempt(conversation_id, attempt_id, trigger, inference.revoker)
        except Exception as exc:  # recorded, never swallowed: the caller records and raises it
            code = _code_of(exc)
            outcome = {'GRANT_ALREADY_REVOKED': 'already revoked', 'GRANT_UNKNOWN': 'no grant'}.get(code, 'failed')
            outcomes.append((outcome, code))
            if kind == 'fingerprint' and record['tokenFingerprint'] is None and outcome != 'no grant':
                record['tokenFingerprint'] = fingerprint
            continue
        named = answer.get('token_fingerprint') if isinstance(answer, Mapping) else None
        revoked = isinstance(answer, Mapping) and answer.get('state') == 'revoked' \
            and (kind == 'attempt' or named == fingerprint)
        outcomes.append(('revoked', None) if revoked else ('failed', 'REVOCATION_UNCONFIRMED'))
        if isinstance(named, str):
            record['tokenFingerprint'] = named
    if any(outcome == 'revoked' for outcome, _ in outcomes):
        outcome, code = 'revoked', None
    elif selectors and selectors[-1][0] == 'attempt':
        outcome, code = outcomes[-1]
    else:
        outcome, code = next(((o, c) for o, c in outcomes if o == 'failed'), outcomes[-1])
    return {**record, 'outcome': outcome, 'revoked': outcome != 'failed', 'code': code}


def _last_detail(integration_store, key: str):
    events = integration_store.events(key)
    try:
        return _strict_loads(events[-1].detail_json or 'null') if events else None
    except ValueError:
        return None


def _settle(integration_store, key: str, held_state: str, ok: bool, actor: str, reason: str, detail) -> None:
    """Move a receipt from HELD_STATE to confirmed (OK) or failed, through dispatched when it is reserved."""
    if held_state == 'reserved' and ok:
        _mark(integration_store, key, 'reserved', 'dispatched', actor, 'resumed', None)
        held_state = 'dispatched'
    _mark(integration_store, key, held_state, 'confirmed' if ok else 'failed', actor, reason, detail)


def _revocation_receipts(integration_store, attempt_id: str) -> list:
    """(key, reservation) of the attempt's revocation receipts, in order."""
    out, n = [], 1
    while (held := integration_store.get(REVOCATION_KEY.format(attempt_id=attempt_id, n=n))) is not None:
        out.append((REVOCATION_KEY.format(attempt_id=attempt_id, n=n), held))
        n += 1
    return out


def _journaled_revocation(integration_store, operation_key: str, inference, selectors: list, actor: str) -> dict:
    """``_revoke`` with its receipt in the integration store (``dispatch/attempt/<attempt id>/inference-revocation/
    <n>``): an unsettled receipt of the attempt is resumed, whatever its revoker, else the next one is reserved and
    dispatched before the call; after it, the receipt and every other unsettled one of the attempt are confirmed
    (no live grant remains) or failed, with the record. The call is made even when the store cannot be written;
    the record then says so (``journal``)."""
    attempt_id, conversation_id = store.attempt_id_for(operation_key), store.conversation_id_for(operation_key)
    intent = {'format': REVOCATION_FORMAT, 'operationKey': operation_key, 'attemptId': attempt_id,
              'conversationId': conversation_id, 'trigger': REVOCATION_TRIGGER,
              'revoker': inference.revoker if isinstance(inference, InferenceAccess) else None}
    opened, journal_error = [], None
    try:
        receipts = _revocation_receipts(integration_store, attempt_id)
        opened = [(k, h.state) for k, h in receipts if h.state in ('reserved', 'dispatched')]
        if not opened:
            receipt_key = REVOCATION_KEY.format(attempt_id=attempt_id, n=len(receipts) + 1)
            integration_store.reserve(receipt_key, intent, actor=actor)
            _mark(integration_store, receipt_key, 'reserved', 'dispatched', actor, 'revoke', None)
            opened = [(receipt_key, 'dispatched')]
    except Exception as exc:  # the revocation is made all the same
        journal_error = type(exc).__name__
    record = _revoke(inference, selectors, conversation_id, attempt_id)
    try:
        for receipt_key, state in opened:
            _settle(integration_store, receipt_key, state, record['revoked'], actor, record['code'] or 'revoked',
                    record)
    except Exception as exc:
        journal_error = journal_error or type(exc).__name__
    if journal_error is not None:
        record = {**record, 'journal': f'not written ({journal_error})'}
    return record


class _GrantCustody:
    """One attempt's inference grant in the dispatcher's custody (E-05.6). The issue is journaled in the integration
    store before the call (``dispatch/attempt/<attempt id>/inference-grant``: reserved, dispatched; confirmed with
    the grant's fingerprint, or failed when the broker refused to issue), so that a grant whose answer was lost, or
    whose dispatcher stopped, can still be found and revoked by its attempt. Every revocation is journaled too
    (``_journaled_revocation``)."""

    def __init__(self, integration_store, operation_key: str, inference, actor: str):
        self.store, self.key, self.inference, self.actor = integration_store, operation_key, inference, actor
        self.attempt_id = store.attempt_id_for(operation_key)
        self.journal_key = GRANT_JOURNAL_KEY.format(attempt_id=self.attempt_id)
        self.grant = None          # the InferenceGrant, once its answer is admitted
        self.uncertain = False     # an issue was sent and whether it issued a grant is not known
        self.named = []            # fingerprints an answer that was not a valid grant named
        self.revocation = None

    def issue(self, resolved: ResolvedInputs, staged: StageInference) -> InferenceGrant:
        if not isinstance(self.inference, InferenceAccess):
            raise DispatchRefused('INFERENCE_GRANT_UNAVAILABLE', f'the {resolved.stage} stage carries the attempt\'s '
                                  'inference token, and no broker control listener was given')
        intent = {'format': GRANT_JOURNAL_FORMAT, 'operationKey': self.key, 'attemptId': self.attempt_id,
                  'conversationId': store.conversation_id_for(self.key), 'family': staged.family,
                  'revoker': self.inference.revoker}
        self.store.reserve(self.journal_key, intent, actor=self.actor)
        _mark(self.store, self.journal_key, 'reserved', 'dispatched', self.actor, 'issue', None)
        self.uncertain = True   # from here a grant may exist
        try:
            grant = _issue(self.inference, resolved, staged)
        except Exception as exc:  # fail closed: whatever the control call raises, nothing is admitted
            code = _code_of(exc)
            named = getattr(exc, 'fingerprint', None)
            if isinstance(named, str) and secrets_check.broker().FINGERPRINT_SHAPE.fullmatch(named):
                self.named.append(named)
            if getattr(exc, 'broker_code', False) is True and code != 'ATTEMPT_HAS_GRANT':
                self.uncertain = False   # the broker refused the issue: nothing was issued
                _mark(self.store, self.journal_key, 'dispatched', 'failed', self.actor, code,
                      {'format': GRANT_JOURNAL_FORMAT, 'issued': False, 'code': code})
            raise DispatchRefused('INFERENCE_GRANT_UNAVAILABLE', f'the broker\'s control listener did not issue the '
                                  f'grant ({code})', broker_code=code) from None
        self.grant, self.uncertain = grant, False
        _mark(self.store, self.journal_key, 'dispatched', 'confirmed', self.actor, 'issued', grant.record())
        return grant

    def needs_end(self) -> bool:
        return self.revocation is None and (self.grant is not None or self.uncertain)

    def selectors(self) -> list:
        if self.grant is not None:
            return [('fingerprint', self.grant.fingerprint)]
        return [('fingerprint', fp) for fp in self.named] + [('attempt', None)]

    def end(self) -> dict | None:
        """Revoke the grant once (trigger ``attempt end``: a refused attempt ends too); never raises an
        Exception. An uncertain issue is settled in its journal by the revocation's outcome."""
        if not self.needs_end():
            return self.revocation
        uncertain = self.grant is None
        self.revocation = _journaled_revocation(self.store, self.key, self.inference, self.selectors(), self.actor)
        if uncertain:
            _settle_journal(self.store, self.journal_key, self.revocation, self.actor)
        return self.revocation

    def ended(self, refusal: DispatchRefused) -> DispatchRefused:
        """REFUSAL after the grant's revocation, with the grant and its revocation (by fingerprint) in its context."""
        revocation = self.end()
        if revocation is not None:
            if self.grant is not None:
                refusal.context['inference_grant'] = self.grant.record()
            refusal.context['inference_revocation'] = revocation
        return refusal

    def detail(self) -> dict:
        """The grant and its revocation for an unknown outcome's transition detail, after the revocation."""
        revocation = self.end()
        if revocation is None:
            return {}
        return {**({'inferenceGrant': self.grant.record()} if self.grant is not None else {}),
                'inferenceRevocation': revocation}


def _settle_journal(integration_store, journal_key: str, revocation: dict, actor: str) -> None:
    """Settle an unsettled grant journal by a revocation by its attempt: confirmed when a grant was found (and is
    no longer live), failed when the broker holds none; left as it is while the outcome is unknown."""
    try:
        held = integration_store.get(journal_key)
        if held is None or held.state not in ('reserved', 'dispatched') or not revocation['revoked']:
            return
        issued = revocation['outcome'] != 'no grant'
        _settle(integration_store, journal_key, held.state, issued, actor, 'settled by revocation',
                {'format': GRANT_JOURNAL_FORMAT, 'issued': issued, 'tokenFingerprint': revocation['tokenFingerprint'],
                 'settledBy': revocation['outcome']})
    except Exception:  # the revocation stands; the journal is settled by a later end_attempt
        pass


def dispatch(request, *, manifest: ApprovedInputs, work_sources: Callable[[str], WorkSource | None],
             integration_store, workspaces, transport: Callable[[str, str, dict | None], object], actor: str,
             read_profile: Callable[[str], bytes] = read_profile_file,
             read_artifact: Callable[[str], bytes] = read_profile_artifact,
             inference: InferenceAccess | None = None) -> DispatchResult:
    """One native Docker conversation create for a dispatch request, in the dispatcher's order:

    1. ``resolve`` (a refusal reserves nothing);
    2. ``reserve_attempt`` with ``ResolvedInputs.intent()`` (``workRef`` and ``outcomeRef`` included);
    3. the record re-read from the store (``reserved_inputs``), ``admit`` on it, and the host
       workspace created only then (``create_workspace``); a refusal marks the attempt ``failed``;
    4. ``dispatched``, immediately before ``send_create`` (on the re-read record): ``GET
       /server_info`` and P1 to P5, then the create; a refusal there marks it ``failed`` (the create
       was not sent);
    5. the answer: 200 or 201 with the reserved id is ``confirmed`` with the returned identifiers
       (``create_receipt``) as the transition's detail, and returned; a 4xx is ``failed`` and
       CREATE_REFUSED; no answer, a 5xx or any other answer is ``unknown`` and CreateOutcomeUnknown
       (a transport exception is re-raised). Nothing is retried and no event history is stored.

    The D1 stage (E-05.6): after ``admit`` has admitted every other input, and only then, the attempt token is
    requested from the broker's control listener (``inference``, an ``InferenceAccess``), the call journaled before
    it is made (``_GrantCustody``), and ``admit_secrets`` adds the secrets block; then the workspace,
    ``dispatched`` (its detail carries the grant by fingerprint) and ``send_create``. From the issue on, the grant
    is revoked (trigger ``attempt end``) on any refusal or failure, whatever is raised (KeyboardInterrupt and
    SystemExit included), before the attempt's outcome is recorded; a lost or invalid issue answer is revoked by the
    attempt. The revocation is journaled and its outcome is in the attempt's record and on the raised exception;
    a confirmed attempt keeps its grant until ``end_attempt``. The token is held in memory only, until the
    transport call; every record carries its fingerprint. Every other stage takes no token and never calls
    ``inference``.
    """
    resolved = resolve(request, manifest=manifest, work_sources=work_sources,
                       next_ordinal=store_next_ordinal(integration_store), read_profile=read_profile)
    identity = resolved.attempt_identity()
    key = identity.operation_key
    integration_store.reserve_attempt(identity, resolved.intent(), actor=actor)
    try:
        reserved = reserved_inputs(integration_store, key)
        admitted = admit(reserved, manifest=manifest, workspaces=workspaces, read_profile=read_profile,
                         read_artifact=read_artifact)
        staged = stage_inference(admitted, resolved=reserved)   # the D1 stage's inference inputs, or None
    except DispatchRefused as refusal:
        if refusal.code != 'ATTEMPT_NOT_RESERVED':
            _mark(integration_store, key, 'reserved', 'failed', actor, refusal.code, _refusal_detail(refusal))
        raise
    custody, grant = _GrantCustody(integration_store, key, inference, actor), None
    try:
        try:
            if staged is not None:
                grant = custody.issue(reserved, staged)   # only now: the reservation and every input admitted
                admitted = admit_secrets(admitted, resolved=reserved, workspaces=workspaces, grant=grant)
            host = create_workspace(admitted, resolved=reserved, workspaces=workspaces)
        except DispatchRefused as refusal:
            _mark(integration_store, key, 'reserved', 'failed', actor, refusal.code,
                  _refusal_detail(custody.ended(refusal)))
            raise
        dispatched = {'format': DISPATCHED_FORMAT, 'conversationId': admitted.conversation_id,
                      'route': {'method': admitted.method, 'path': admitted.path}}
        if grant is not None:
            dispatched['inferenceGrant'] = grant.record()
        _mark(integration_store, key, 'reserved', 'dispatched', actor, 'create', dispatched)
        try:
            answer = send_create(admitted, resolved=reserved, workspaces=workspaces, transport=transport)
        except DispatchRefused as refusal:
            _mark(integration_store, key, 'dispatched', 'failed', actor, refusal.code,
                  _refusal_detail(custody.ended(refusal), create_sent=False))
            raise
        except Exception as exc:
            detail = {'error': type(exc).__name__, **custody.detail()}
            if 'inferenceRevocation' in detail:
                exc.add_note('inference revocation: ' + _canonical(detail['inferenceRevocation']))
            _mark(integration_store, key, 'dispatched', 'unknown', actor, 'create-unanswered', detail)
            raise
        if grant is not None:
            grant.drop()   # held only until the transport call; the broker's grant is revoked by fingerprint
        receipt = create_receipt(answer, admitted.conversation_id)
        if receipt is not None:
            _mark(integration_store, key, 'dispatched', 'confirmed', actor,
                  'created' if receipt['created'] else 'existing', receipt)
            return DispatchResult(operation_key=key, attempt_id=store.attempt_id_for(key),
                                  conversation_id=receipt['conversationId'], execution_ref=receipt['executionRef'],
                                  http_status=receipt['httpStatus'], created=receipt['created'],
                                  host_workspace=str(host), inference_grant=None if grant is None else grant.record())
        status = answer.get('status') if isinstance(answer, Mapping) else None
        status = status if type(status) is int else None
        if status is not None and 400 <= status < 500:
            refusal = custody.ended(DispatchRefused('CREATE_REFUSED', f'the Agent Server answered the create with '
                                                    f'{status}', status=status))
            _mark(integration_store, key, 'dispatched', 'failed', actor, refusal.code,
                  _refusal_detail(refusal, create_sent=True))
            raise refusal
        detail = {'httpStatus': status, 'reason': 'no 200 or 201 answer carrying the reserved conversation id',
                  **custody.detail()}
        _mark(integration_store, key, 'dispatched', 'unknown', actor, 'create-outcome-uncertain', detail)
        ended = {} if custody.revocation is None else {
            **({'inference_grant': grant.record()} if grant is not None else {}),
            'inference_revocation': custody.revocation}
        raise CreateOutcomeUnknown(key, detail['reason'], http_status=status, **ended)
    except BaseException as exc:
        if custody.needs_end():   # any other failure after the issue, KeyboardInterrupt and SystemExit included
            exc.add_note('inference revocation: ' + _canonical(custody.end()))
        raise
    finally:
        if grant is not None:
            grant.drop()


def end_attempt(integration_store, operation_key: str, *, inference: InferenceAccess, actor: str) -> dict | None:
    """The attempt's end (decision 0015 section 3.3, E-05.6): revoke the attempt's issued, not yet revoked
    inference grant through the broker's control listener (trigger ``attempt end``, the access's revoker), whatever
    the attempt's state: confirmed, failed, unknown, or reserved or dispatched as an interrupted dispatcher left it.
    Ending an attempt still in flight revokes its grant (fail closed).

    The grant is the one the attempt's grant journal (``dispatch/attempt/<attempt id>/inference-grant``) records:
    by its fingerprint when the journal has it, else by the attempt (a lost or interrupted issue). An attempt
    with no journal (every other stage, or a D1 attempt refused before the issue) or whose issue the broker refused
    has no grant: None. When a revocation receipt of the attempt is already confirmed and none is unsettled, its
    record is returned without a call. Otherwise the revocation is journaled (``_journaled_revocation``: an
    unsettled receipt of the attempt is resumed and settled whatever its revoker, else the next one is written) and
    returned; an unsettled grant journal is settled by it. A failed revocation is INFERENCE_REVOCATION_FAILED, with
    the record; a later call tries again. The broker writes its own revocation receipt; nothing here reads or holds
    the token."""
    if not isinstance(inference, InferenceAccess):
        raise TypeError('inference must be an InferenceAccess (the broker\'s control listener)')
    if integration_store.get(operation_key) is None or integration_store.attempt_identity(operation_key) is None:
        raise DispatchRefused('RESERVATION_INVALID', f'no dispatch reservation under {operation_key!r}')
    attempt_id = store.attempt_id_for(operation_key)
    journal_key = GRANT_JOURNAL_KEY.format(attempt_id=attempt_id)
    journal = integration_store.get(journal_key)
    if journal is None:
        return None
    detail = _last_detail(integration_store, journal_key)
    receipts = _revocation_receipts(integration_store, attempt_id)
    unsettled = [k for k, h in receipts if h.state in ('reserved', 'dispatched')]
    confirmed = [k for k, h in receipts if h.state == 'confirmed']
    if confirmed and not unsettled and journal.state not in ('reserved', 'dispatched'):
        return _last_detail(integration_store, confirmed[-1])
    if journal.state == 'failed' and isinstance(detail, dict) and detail.get('issued') is False and not unsettled:
        return None
    fingerprint = detail.get('tokenFingerprint') if isinstance(detail, dict) and journal.state == 'confirmed' else None
    if isinstance(fingerprint, str) and secrets_check.broker().FINGERPRINT_SHAPE.fullmatch(fingerprint):
        selectors = [('fingerprint', fingerprint)]
    else:
        selectors = [('attempt', None)]
    record = _journaled_revocation(integration_store, operation_key, inference, selectors, actor)
    if selectors[0][0] == 'attempt':
        _settle_journal(integration_store, journal_key, record, actor)
    if not record['revoked']:
        raise DispatchRefused('INFERENCE_REVOCATION_FAILED', f'the inference grant of attempt {attempt_id} was not '
                              f'revoked ({record["code"]})', inference_revocation=record)
    return record


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
