"""The launch gate (plan leaf E-01.5; the I1 integration design, R11): an attempt is launched only when an independent
docker inspect of its conversation's container shows the admitted caps, image ID and mounts, and the recorded limit
values of ``fd-container-network-deviations`` for its NetworkMode and ExtraHosts.

``gate(store, operation_key, inspect_source=, source=, actor=)`` returns the ``inspect`` callable that
``attempt_run.run_attempt`` takes at its inspect step (step 1: before SEED and before the message; ``run_attempt``
itself is unchanged). Called with the attempt's conversation id, it

1. reads what the attempt was admitted with, from the reserved record only (``admitted``): the caps of the policy
   inputs (``conversation_container_memory``, ``_cpus`` and ``_pids_limit``, as Docker's ``Memory``, ``NanoCpus`` and
   ``PidsLimit``), the declared mounts expanded with the conversation's hex (``dispatch_inputs._binds_for``, the
   admission's own rule), and the image ID the approved profile pins (its ``provider.provision_lock``, read by its
   pinned sha256: ``image.image_id``);
2. obtains the container's docker inspect from INSPECT_SOURCE (``inspect_source(conversation_id)`` answers a mapping
   whose ``body`` is the container's inspect object), independently of the Agent Server's own answers;
3. compares the five fields (``compare``): ``caps``, ``image``, ``mounts`` (exactly the declared binds, as
   ``(Type, Source, Destination, RW)``), ``network-mode`` (``bridge``) and ``extra-hosts``
   (``["host.docker.internal:host-gateway"]``); any other value, or an inspect it cannot obtain, parse or compare
   (any exception while it reads the admitted values or obtains, parses or compares the document: its type is the
   reason in the receipt's problems), is ``not-launched``;
4. writes the launch receipt ``dispatch/attempt/<attempt id>/launch`` (``attempt-launch/v1``: the verdict, each
   compared field with its admitted or limit value and the observed one, the inspect document's sha256 and its
   SOURCE), confirmed, before it answers; a receipt already there with another observation is ``not-launched``, and
   a receipt it cannot write is answered as a problem, so the attempt never reaches SEED without its receipt;
5. answers ``[]`` when launched, else one problem sentence per failed field (no observed value in the sentence: the
   receipt holds them, bounded), and ``run_attempt`` then ends the attempt (``INSPECTION_FAILED``, a
   ``containment-stop`` record) with no SEED and no message.

The limit values are the recorded ones of ``fd-container-network-deviations`` (``security/inventory.json``), as
F-04.2 observed them on every container (``evidence/F-04.2-conversation-lifecycle.md`` section 7): the pinned server
adds ``--add-host host.docker.internal:host-gateway`` unconditionally and passes no ``--network``. A test binds the
constants to both records.

The receipt's verdict is the container gate's. ``run_attempt``'s API half (the count, the conversation, its runtime)
is its own: an attempt whose API half fails is ended ``INSPECTION_FAILED`` whatever the receipt says, and its end
record is the attempt's state.

Standard library only. It reads the store, the approved profile and the artifacts it pins, and calls INSPECT_SOURCE
once; it writes only its receipt.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from pathlib import Path
from typing import Callable, Mapping

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


di = _load('dispatch_inputs', HERE / 'dispatch_inputs.py')
store = di.store
DispatchRefused = di.DispatchRefused

LAUNCH_KEY = 'dispatch/attempt/{attempt_id}/launch'
LAUNCH_FORMAT = 'ai-engineering-harness/dispatch/attempt-launch/v1'
LAUNCHED, NOT_LAUNCHED = 'launched', 'not-launched'
VERDICTS = (LAUNCHED, NOT_LAUNCHED)
FIELDS = ('caps', 'image', 'mounts', 'network-mode', 'extra-hosts')

# The recorded limit values of fd-container-network-deviations (security/inventory.json), as F-04.2 section 7 observed
# them: HostConfig.NetworkMode bridge (no --network) and HostConfig.ExtraHosts host.docker.internal:host-gateway.
NETWORK_MODE_LIMIT = 'bridge'
EXTRA_HOSTS_LIMIT = ('host.docker.internal:host-gateway',)
DEVIATION_FINDING = 'fd-container-network-deviations'

IMAGE_ID_RE = re.compile(r'sha256:[0-9a-f]{64}')
SOURCE_RE = re.compile(r'[A-Za-z0-9._:/@#(),; -]{1,256}')
OBSERVED_MAX = 1024        # an observed value larger than this, as canonical JSON, is recorded by its digest only


def _canonical(value) -> str:
    return di._canonical(value)


def _plain(value):
    """VALUE as plain JSON values: each mapping read whole, once (its ``items``), each list element in turn."""
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _bounded(value):
    """An observed VALUE as the receipt records it: itself when small, else its sha256 and size."""
    try:
        text = _canonical(value)
    except (TypeError, ValueError):
        return {'unrecordable': type(value).__name__}
    if len(text) <= OBSERVED_MAX:
        return value
    return {'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'size': len(text)}


# ---------------------------------------------------------------------------
# What the attempt was admitted with

def admitted(integration_store, operation_key: str, *, read_profile: Callable[[str], bytes],
             read_artifact: Callable[[str], bytes]) -> dict:
    """The admitted values the gate compares, from the attempt's reserved record (confirmed) and the approved
    profile it pins: {'caps': {Memory, NanoCpus, PidsLimit}, 'image': <image ID>, 'mounts': [(Type, Source,
    Destination, RW), ...] sorted}. A DispatchRefused when any of them cannot be read."""
    resolved = di.stored_inputs(integration_store, operation_key, state='confirmed')
    admission = di._resolved_admission(resolved)
    caps = admission['caps']
    memory = di.memory_bytes(caps.get('memory'))
    cpus, pids = caps.get('cpus'), caps.get('pids_limit')
    if memory is None or type(cpus) not in (int, float) or type(pids) is not int:
        raise DispatchRefused('ADMISSION_MISMATCH', 'the admitted caps are not memory, cpus and pids_limit')
    hexed = store.conversation_id_for(operation_key).replace('-', '')
    mounts = sorted((b['type'], b['source'], b['destination'], b['rw'])
                    for b in di._binds_for(admission['mounts']['binds'], hexed))
    _, _, declared = di._read_checked_profile(resolved.profile, resolved.profile_digest, read_profile)
    lock_pin = ((declared.get('provider') or {}) if isinstance(declared, dict) else {}).get('provision_lock')
    if not isinstance(lock_pin, dict) or not di.is_artifact_path(lock_pin.get('path')) \
            or not isinstance(lock_pin.get('sha256'), str):
        raise DispatchRefused('PROFILE_ADMISSION_INVALID', f'{resolved.profile}: provider.provision_lock is not a '
                              'pinned profile artifact', profile=resolved.profile)
    lock = di._artifact_object(di._read_pinned(read_artifact, lock_pin, 'provision lock'), 'provision lock')
    image = lock.get('image') if isinstance(lock.get('image'), dict) else {}
    image_id = image.get('image_id')
    if not isinstance(image_id, str) or IMAGE_ID_RE.fullmatch(image_id) is None \
            or image_id != image.get('config_digest'):
        raise DispatchRefused('PROFILE_ADMISSION_INVALID', f'{resolved.profile}: the provision lock pins no image ID '
                              '(image.image_id, its config digest)', profile=resolved.profile)
    return {'caps': {'Memory': memory, 'NanoCpus': int(round(float(cpus) * 1e9)), 'PidsLimit': pids},
            'image': image_id, 'mounts': [list(m) for m in mounts]}


# ---------------------------------------------------------------------------
# The comparison

def _mounts(document) -> list | None:
    """The document's Mounts as sorted [Type, Source, Destination, RW], or None when they are not a list of
    mappings."""
    mounts = document.get('Mounts')
    if not isinstance(mounts, list) or not all(isinstance(m, dict) for m in mounts):
        return None
    return sorted([m.get('Type'), m.get('Source'), m.get('Destination'), m.get('RW')] for m in mounts)


def _exact(observed, expected) -> bool:
    """Equal, and of the same JSON types throughout (True is not 1; 2.0 is not 2); a value JSON cannot hold is
    never equal."""
    try:
        return _canonical(observed) == _canonical(expected)
    except (TypeError, ValueError):
        return False


def compare(document: dict, admitted_values: dict) -> list[dict]:
    """The five compared fields of DOCUMENT (a plain inspect object) against ADMITTED_VALUES and the limit values:
    [{'field', 'basis' (admitted or limit), 'expected', 'observed', 'equal'}], in FIELDS order."""
    host = document.get('HostConfig') if isinstance(document.get('HostConfig'), dict) else {}
    caps = {name: host.get(name) for name in ('Memory', 'NanoCpus', 'PidsLimit')}
    observed = {
        'caps': caps,
        'image': document.get('Image'),
        'mounts': _mounts(document),
        'network-mode': host.get('NetworkMode'),
        'extra-hosts': host.get('ExtraHosts'),
    }
    expected = {
        'caps': admitted_values['caps'],
        'image': admitted_values['image'],
        'mounts': admitted_values['mounts'],
        'network-mode': NETWORK_MODE_LIMIT,
        'extra-hosts': list(EXTRA_HOSTS_LIMIT),
    }
    out = []
    for name in FIELDS:
        equal = _exact(observed[name], expected[name])
        if name == 'caps':
            equal = equal and all(type(v) is int for v in caps.values())
        out.append({'field': name, 'basis': 'limit' if name in ('network-mode', 'extra-hosts') else 'admitted',
                    'expected': expected[name], 'observed': _bounded(observed[name]), 'equal': equal})
    return out


# ---------------------------------------------------------------------------
# The gate

def launch_record(integration_store, attempt_id: str) -> dict | None:
    """The attempt's launch receipt (``attempt-launch/v1``), confirmed, or None."""
    held = integration_store.get(LAUNCH_KEY.format(attempt_id=attempt_id))
    if held is None or held.state != 'confirmed':
        return None
    try:
        record = di._strict_loads(held.intent_json)
    except ValueError:
        return None
    return record if isinstance(record, dict) and record.get('format') == LAUNCH_FORMAT else None


def _write_receipt(integration_store, key: str, intent: dict, actor: str) -> bool:
    """The receipt written and confirmed (or found, the same) by the attempt run's own receipt writer
    (``attempt_run._receipt``, the delivery, pull and intake receipts' writer, a listed write-ahead site of the
    dispatcher lock's census); one an interruption left ``dispatched`` is confirmed. False when KEY holds another
    one."""
    try:
        _attempt_run()._receipt(integration_store, key, intent, actor)
    except DispatchRefused as refusal:
        if refusal.code != 'RESULT_RECEIPT_CONFLICT':
            raise
        return False
    held = integration_store.get(key)
    if held.state == 'dispatched':
        di._mark(integration_store, key, 'dispatched', 'confirmed', actor, 'record', None)
        held = integration_store.get(key)
    return held.state == 'confirmed'


def _attempt_run():
    return _load('attempt_run', HERE / 'attempt_run.py')


def gate(integration_store, operation_key: str, *, inspect_source: Callable[[str], Mapping], source: str, actor: str,
         read_profile: Callable[[str], bytes] = di.read_profile_file,
         read_artifact: Callable[[str], bytes] = di.read_profile_artifact) -> Callable[[str], list]:
    """The ``inspect`` callable of ``run_attempt`` for the attempt OPERATION_KEY (the module docstring): it answers []
    when the attempt is launched, else its problems, and writes the launch receipt first. SOURCE names where the
    inspect documents come from (recorded in the receipt; a short text)."""
    if not isinstance(source, str) or SOURCE_RE.fullmatch(source) is None:
        raise ValueError('source must be 1 to 256 characters of a short text naming the inspect source')
    attempt_id = store.attempt_id_for(operation_key)
    reserved_conversation = store.conversation_id_for(operation_key)

    def inspect(conversation_id: str) -> list:
        problems, values, document, fields, label = [], None, None, [], {}
        try:
            values = admitted(integration_store, operation_key, read_profile=read_profile, read_artifact=read_artifact)
            # E-01.8, R11: the receipt carries the attempt's bound authority (its pinned route allowlist's) when it is
            # not live; a live receipt is byte for byte what it was
            label = di.authority_label(di.attempt_authority(
                di.stored_inputs(integration_store, operation_key, state='confirmed'), read_artifact))
        except DispatchRefused as refusal:
            problems.append(f'the admitted values could not be read ({refusal.code})')
        except Exception as exc:  # noqa: BLE001 - no admitted values: nothing is compared
            problems.append(f'the admitted values could not be read ({type(exc).__name__})')
        if conversation_id != reserved_conversation:
            problems.append('the inspect was asked for another conversation than the attempt\'s')
        else:
            try:
                answer = inspect_source(conversation_id)
                body = answer.get('body') if isinstance(answer, Mapping) else None
                document = _plain(body) if isinstance(body, Mapping) else None
            except Exception as exc:  # noqa: BLE001 - no inspect: nothing is inferred from it
                problems.append(f'the container inspect could not be obtained ({type(exc).__name__})')
            else:
                if document is None:
                    problems.append('the container inspect could not be obtained (no inspect object)')
        if document is not None and values is not None:
            try:
                fields = compare(document, values)
            except Exception as exc:  # noqa: BLE001 - a document the gate cannot compare is not launched (S3)
                fields = []
                problems.append(f'the container inspect could not be compared ({type(exc).__name__})')
        problems += [f'the container\'s {f["field"]} is not the {f["basis"]} value' for f in fields if not f['equal']]
        verdict = NOT_LAUNCHED if problems else LAUNCHED
        intent = {'format': LAUNCH_FORMAT, 'operationKey': operation_key, 'attemptId': attempt_id,
                  'conversationId': reserved_conversation, 'verdict': verdict, 'fields': fields,
                  'inspect': {'source': source, 'obtained': document is not None, 'sha256': _digest(document)},
                  'limitFinding': DEVIATION_FINDING,
                  'problems': list(problems), **label}
        try:
            written = _write_receipt(integration_store, LAUNCH_KEY.format(attempt_id=attempt_id), intent, actor)
        except Exception as exc:  # noqa: BLE001 - no receipt: never launched, whatever the comparison found
            return problems + [f'the launch receipt could not be written ({type(exc).__name__})']
        if not written:
            problems.append('a launch receipt with another observation is recorded for the attempt')
        return problems

    return inspect


def _digest(document) -> str | None:
    """The sha256 of the inspect document as canonical JSON; None when there is none or JSON cannot hold it."""
    if document is None:
        return None
    try:
        return hashlib.sha256(_canonical(document).encode('utf-8')).hexdigest()
    except (TypeError, ValueError):
        return None
