"""An attempt's bound authority, read without the dispatcher (plan leaf U-04.1; the I1 integration design, R2 and R11;
the engineering manager's ruling on U-04.1's STOP, option B).

R11: readers compute an attempt's authority (``live`` or ``fixture``) from its reservation's pinned route allowlist,
never from a label or a caller's flag. The dispatcher computes it with ``dispatch_inputs.attempt_authority`` and
``bound_label``, which the Integration process may not load: dispatch_inputs holds the Agent Server client, and its
refusal type's vocabulary names the inference and native-token modules (R2's import census). So this module reads the
same records in the same order, transport-free, with stable codes of its own (``Unbound``) and no dispatch import.
``tests/test_bound_authority.py`` pins it to the dispatcher's two functions, case by case.

``bound_authority(reservation, read_artifact=None)`` takes one integration-store reservation (``Reservation``: its
``intent_json`` and ``intent_digest``) and

1. checks the stored intent against its digest and reads it as strict JSON (no duplicate key, no NaN):
   ``BINDING_RECORD_INVALID`` otherwise;
2. takes the dispatcher's record under ``dispatchInputs``: exactly the keys and types of ``resolved-inputs/v2``
   (``BINDING_RECORD_INVALID`` otherwise);
3. checks its policy inputs against the policy digest, their format (``policy-inputs/v2``) and their profile (the
   record's id and digest): ``BINDING_POLICY_MISMATCH`` otherwise;
4. takes the admission's route allowlist pin, ``{path, sha256}``: a ``profiles/<the profile>/...`` artifact path and
   a sha256 (``BINDING_ADMISSION_INVALID`` otherwise);
5. reads that file through READ_ARTIFACT (the checkout's ``profiles/`` by default) and checks its sha256:
   ``BINDING_ALLOWLIST_MISSING`` when it cannot be read, ``BINDING_ALLOWLIST_DRIFTED`` when it has another digest,
   ``BINDING_ALLOWLIST_INVALID`` when it is not a strict JSON object;
6. answers its top-level ``transport`` declaration's authority: ``live`` when there is none, ``fixture`` when it is
   exactly ``{"authority": "fixture", "kind": "loopback-fixture"}``, ``BINDING_DECLARATION_INVALID`` for anything
   else.

**The known divergence.** The dispatcher's ``_resolved_admission`` validates the whole admission policy
(``check_admission_policy``: the runtime, the caps against the ceilings, the mounts) before it reads the pin; this
reader checks only the pin it reads. A record whose other admission values are invalid but whose digests hold is
bound here and refused there. The dispatcher cannot reserve such a record: admission runs before the reservation, and
the record is bound by its policy digest and its intent digest. The equivalence test shows the divergence on a
record built for it.

Standard library only, plus the integration store's canonical JSON (storecore). Reads one file; writes nothing.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable

HERE = Path(os.path.realpath(__file__)).parent
REPO = HERE.parents[1]


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


integration_store = _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')
_canonical = integration_store.storecore.canonical_json

LIVE, FIXTURE = 'live', 'fixture'
AUTHORITIES = (LIVE, FIXTURE)
# The dispatcher's record formats and keys this reader reads (dispatch_inputs; the test pins them equal).
INTENT_KEY = 'dispatchInputs'
RESOLVED_FORMAT = 'ai-engineering-harness/dispatch/resolved-inputs/v2'
POLICY_FORMAT = 'ai-engineering-harness/dispatch/policy-inputs/v2'
MANIFEST_SCHEMA = 'ai-engineering-harness/dispatch/approved-inputs/v1'
TRANSPORT_KEY = 'transport'
DECLARATIONS = {FIXTURE: {'authority': FIXTURE, 'kind': 'loopback-fixture'}}
RECORD_STRINGS = ('work_id', 'repository', 'stage', 'design_revision', 'profile', 'profile_digest', 'catalog_pin',
                  'agent_manifest_digest', 'planned_workspace', 'policy_digest', 'outcome_ref')
RECORD_KEYS = frozenset({'format', 'ordinal', 'policy_inputs', 'approval', *RECORD_STRINGS})
APPROVAL_KEYS = frozenset({'manifest_schema', 'manifest_version', 'manifest_sha256'})
SHA256_RE = re.compile(r'[0-9a-f]{64}')
ARTIFACT_PATH_RE = re.compile(r'profiles/[a-z0-9]+(?:-[a-z0-9]+)*(?:/[A-Za-z0-9_-][A-Za-z0-9._-]*)+')
RESERVED_NAMES = frozenset(['CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$', 'CLOCK$'] + [
    f'{device}{n}' for device in ('COM', 'LPT') for n in list('0123456789') + [chr(0xB9), chr(0xB2), chr(0xB3)]])

CODES = {
    'BINDING_RECORD_INVALID': 'the reservation is not the dispatcher\'s digest-bound record of a typed attempt',
    'BINDING_POLICY_MISMATCH': 'the record\'s policy inputs do not have its policy digest, format or profile',
    'BINDING_ADMISSION_INVALID': 'the admission policy pins no route allowlist under the attempt\'s profile',
    'BINDING_ALLOWLIST_MISSING': 'the pinned route allowlist cannot be read',
    'BINDING_ALLOWLIST_DRIFTED': 'the route allowlist does not have its pinned sha256',
    'BINDING_ALLOWLIST_INVALID': 'the pinned route allowlist is not a strict JSON object',
    'BINDING_DECLARATION_INVALID': 'the route allowlist declares a transport outside the vocabulary',
}


class Unbound(Exception):
    """No bound authority can be read; CODE is one of CODES."""

    def __init__(self, code: str, detail: str):
        if code not in CODES:
            raise ValueError(f'unknown code {code!r}')
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}')


def _strict_object(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError('a duplicate object key')
    return dict(pairs)


def _no_constant(name):
    raise ValueError(f'non-standard JSON constant {name}')


def strict_loads(text):
    return json.loads(text, object_pairs_hook=_strict_object, parse_constant=_no_constant)


def _same(a, b) -> bool:
    try:
        return _canonical(a) == _canonical(b)
    except (TypeError, ValueError):
        return False


def is_artifact_path(path) -> bool:
    """A ``profiles/<id>/...`` path with no part that is a Windows device name."""
    return isinstance(path, str) and ARTIFACT_PATH_RE.fullmatch(path) is not None \
        and not any(part.split('.')[0].rstrip(' ').upper() in RESERVED_NAMES for part in path.split('/'))


def read_profile_artifact(path: str, *, repo_root=REPO) -> bytes:
    """The bytes of a profile-pinned artifact of the checkout, by its ``profiles/<id>/...`` path."""
    if not is_artifact_path(path):
        raise ValueError(f'not a profile artifact path: {path!r}')
    return Path(repo_root).joinpath(*path.split('/')).read_bytes()


def dispatch_record(reservation) -> dict:
    """The dispatcher's record (``resolved-inputs/v2``) of the typed attempt RESERVATION holds (steps 1 and 2)."""
    if reservation is None or not isinstance(getattr(reservation, 'intent_json', None), str):
        raise Unbound('BINDING_RECORD_INVALID', 'no reservation')
    if hashlib.sha256(reservation.intent_json.encode('utf-8')).hexdigest() != reservation.intent_digest:
        raise Unbound('BINDING_RECORD_INVALID', 'the stored intent does not have its digest')
    try:
        intent = strict_loads(reservation.intent_json)
    except ValueError:
        raise Unbound('BINDING_RECORD_INVALID', 'the stored intent is not strict JSON') from None
    record = intent.get(INTENT_KEY) if isinstance(intent, dict) else None
    if not isinstance(record, dict) or set(record) != RECORD_KEYS or record['format'] != RESOLVED_FORMAT:
        raise Unbound('BINDING_RECORD_INVALID', f'the stored intent holds no {RESOLVED_FORMAT} record')
    approval = record['approval']
    if not all(isinstance(record[k], str) for k in RECORD_STRINGS) or type(record['ordinal']) is not int \
            or not isinstance(record['policy_inputs'], dict) or not isinstance(approval, dict) \
            or set(approval) != APPROVAL_KEYS or approval['manifest_schema'] != MANIFEST_SCHEMA \
            or type(approval['manifest_version']) is not int or not isinstance(approval['manifest_sha256'], str):
        raise Unbound('BINDING_RECORD_INVALID', 'the dispatcher\'s record has a field of the wrong type')
    return record


def routes_pin(record: dict) -> dict:
    """The admission's route allowlist pin of RECORD (steps 3 and 4)."""
    policy_json = _canonical(record['policy_inputs'])
    if hashlib.sha256(policy_json.encode('utf-8')).hexdigest() != record['policy_digest']:
        raise Unbound('BINDING_POLICY_MISMATCH', 'the policy inputs do not have the policy digest')
    inputs = record['policy_inputs']
    if inputs.get('format') != POLICY_FORMAT \
            or not _same(inputs.get('profile'), {'id': record['profile'], 'sha256': record['profile_digest']}):
        raise Unbound('BINDING_POLICY_MISMATCH', f'the policy inputs are not {POLICY_FORMAT} of profile '
                                                 f'{record["profile"]} at {record["profile_digest"]}')
    admission = inputs.get('admission')
    pin = admission.get('routes') if isinstance(admission, dict) else None
    if not isinstance(pin, dict) or set(pin) != {'path', 'sha256'} or not is_artifact_path(pin['path']) \
            or not pin['path'].startswith(f'profiles/{record["profile"]}/') \
            or not isinstance(pin['sha256'], str) or not SHA256_RE.fullmatch(pin['sha256']):
        raise Unbound('BINDING_ADMISSION_INVALID', f'the admission policy pins no route allowlist under '
                                                   f'profiles/{record["profile"]}/ by sha256')
    return pin


def declared(data: dict) -> str:
    """The authority a parsed route allowlist declares (step 6)."""
    declaration = data.get(TRANSPORT_KEY)
    if declaration is None:
        return LIVE
    for authority, form in DECLARATIONS.items():
        if _same(declaration, form):
            return authority
    raise Unbound('BINDING_DECLARATION_INVALID', 'the route allowlist declares a transport that is not one of '
                                                 f'{sorted(DECLARATIONS)}')


def bound_authority(reservation, read_artifact: Callable[[str], bytes] | None = None) -> str:
    """``live`` or ``fixture``: what the reservation's pinned route allowlist declares (the module docstring);
    ``Unbound`` with a stable code when it cannot be read."""
    pin = routes_pin(dispatch_record(reservation))
    try:
        raw = (read_artifact or read_profile_artifact)(pin['path'])
    except (OSError, ValueError) as exc:
        raise Unbound('BINDING_ALLOWLIST_MISSING', f'{pin["path"]}: {type(exc).__name__}') from None
    if not isinstance(raw, bytes):
        raise Unbound('BINDING_ALLOWLIST_MISSING', f'{pin["path"]}: the source returned no bytes')
    digest = hashlib.sha256(raw).hexdigest()
    if digest != pin['sha256']:
        raise Unbound('BINDING_ALLOWLIST_DRIFTED', f'{pin["path"]} has sha256 {digest}, pinned {pin["sha256"]}')
    try:
        data = strict_loads(raw.decode('utf-8'))
    except ValueError:
        raise Unbound('BINDING_ALLOWLIST_INVALID', f'{pin["path"]} is not strict JSON') from None
    if not isinstance(data, dict):
        raise Unbound('BINDING_ALLOWLIST_INVALID', f'{pin["path"]} is not a JSON object')
    return declared(data)
