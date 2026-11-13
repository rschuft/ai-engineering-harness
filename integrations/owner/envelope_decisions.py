"""The provider-envelope authorizations and their verifier (plan leaf S-03.5, slice 1): the read side the
inference broker asks before it starts a family whose upstream is not loopback.

The Owner authorizes a provider envelope through the authorization recorder (``authorization_recorder.py``,
plan leaf P-04.2) as any operation: a manifest ``operations/<id>.json`` of kind ``provider-envelope`` whose
target is the envelope's canonical digest (``integrations/inference/inference_envelope.py``). The recorder
does not change and knows nothing of the kind. Its receipts are keyed by a random nonce, so the current
authorization of a kind cannot be found by a direct lookup: this module lists the recorder's receipts, as the
recorder itself does for its own check.

**Candidates**: the receipts under ``owner-authorization/v1/`` whose decision is a well-formed
``owner-decision/v1`` of kind ``authorize-operation`` with ``operationKind`` ``provider-envelope``, reserved by
``authorization-recorder/1``, in reservation order (the first event's ``event_id``). The **governing**
authorization is the last confirmed candidate (merged as ``aieh-owner`` and read back, decision 0012 point
8). A later provider-envelope authorization ends an earlier one at the broker's next start, whatever the
earlier one's expiry; no revocation record is invented.

``verify_envelope`` (or the callable ``verifier(store)``) answers, in this order (``REFUSALS``):

- ``ENVELOPE_RECORD_INVALID``: a receipt under the recorder's prefix whose kind cannot be read; a
  provider-envelope receipt that is not the recorder's (another actor, another receipt format, a decision that
  fails ``owner_decision.check_record``, a decision that does not bind its receipt's key, operation and digest,
  a repeated ``decisionId``);
- ``ENVELOPE_NOT_AUTHORIZED``: no candidate, or none confirmed and none unsettled;
- ``ENVELOPE_AUTHORIZATION_UNRESOLVED``: a candidate reserved after the last confirmed one (or with none
  confirmed) is ``reserved``, ``dispatched`` or ``unknown``: the Owner's later decision may be in force (remedy:
  ``authorization_recorder.py resolve``);
- ``ENVELOPE_REPLAYED``: the live digest is not the governing receipt's target but an earlier confirmed
  candidate's (a superseded authorization put back);
- ``ENVELOPE_MISMATCH``: the live digest is no confirmed candidate's target; or it is the governing one's and
  the receipt's manifest digest is not the canonical manifest's (so what the Owner was shown is exactly what
  is enforced);
- ``ENVELOPE_EXPIRED``: the clock has reached the governing receipt's ``expiresAt``.

Otherwise the view (``VIEW_FIELDS``) of the governing receipt. It reads the integration store only, never a
decision file, Gitea or a credential. Standard library only, plus ``owner_decision.py``'s record format; it
imports no store module (the store is passed in: anything with ``attempts``, ``events`` and ``get``).
"""
import datetime
import importlib.util
import json
import sys
from pathlib import Path
from typing import Callable, NamedTuple

HERE = Path(__file__).resolve().parent


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


D = _load('owner_decision', HERE / 'owner_decision.py')

OPERATION_KIND = 'provider-envelope'
# authorization_recorder.KIND, RECORDER, RECEIPT_FORMAT and RECEIPT_PREFIX, repeated so that the read side
# loads no Gitea or credential module (a test asserts that they are equal).
KIND = 'authorize-operation'
RECORDER = 'authorization-recorder/1'
RECEIPT_FORMAT = 'aieh-owner-authorization/1'
RECEIPT_PREFIX = 'owner-authorization/v1/'
UNSETTLED = ('reserved', 'dispatched', 'unknown')
VIEW_FIELDS = ('receipt', 'operation', 'decisionId', 'target', 'digest', 'expiresAt')

# The verifier's refusals, in the order they are checked.
REFUSALS = {
    'ENVELOPE_RECORD_INVALID': 'a receipt under the recorder\'s prefix cannot be read, or a provider-envelope '
                               'receipt is not one the authorization recorder wrote',
    'ENVELOPE_NOT_AUTHORIZED': 'no confirmed provider-envelope authorization, and none unsettled',
    'ENVELOPE_AUTHORIZATION_UNRESOLVED': 'a provider-envelope authorization decided after the last confirmed one '
                                         'is not settled',
    'ENVELOPE_REPLAYED': 'the live envelope is that of a superseded authorization',
    'ENVELOPE_MISMATCH': 'the live envelope, or its canonical manifest, is not the authorized one',
    'ENVELOPE_EXPIRED': 'the governing authorization has expired',
}


class Candidate(NamedTuple):
    """One provider-envelope receipt of the recorder: its key, reservation order, state, intent and decision
    (the decision's fields in their format's order again)."""
    key: str
    order: int
    state: str
    intent: dict
    decision: dict


class Verdict(NamedTuple):
    """The verifier's answer: CODE None and VIEW the governing receipt's view ({receipt, operation, decisionId,
    target, digest, expiresAt}), or CODE one of ``REFUSALS`` with its DETAIL."""
    code: str | None
    detail: str
    view: dict | None


def _refused(code, detail):
    return Verdict(code, detail, None)


def _ordered(value, fields):
    if not isinstance(value, dict):
        return value
    return {**{name: value[name] for name in fields if name in value},
            **{name: item for name, item in value.items() if name not in fields}}


def stored_decision(decision):
    """DECISION as read from a receipt, with its fields in ``owner-decision/v1``'s order again. The store keeps
    an intent as canonical JSON, whose object keys are sorted; ``check_record`` also checks the order of the
    fields. Nothing but the order changes."""
    if not isinstance(decision, dict) or decision.get('format') != D.FORMAT:
        return decision
    record = _ordered(decision, D.FIELDS)
    for name, fields in (('shown', D.SHOWN_FIELDS), ('statement', D.STATEMENT_FIELDS)):
        if name in record:
            record[name] = _ordered(record[name], fields)
    if record.get('kind') in D.SUBJECT_FIELDS and 'subject' in record:
        record['subject'] = _ordered(record['subject'], D.SUBJECT_FIELDS[record['kind']])
    return record


def _kind_of(intent):
    """The receipt's declared operation kind (its decision's subject.operationKind), or None."""
    decision = intent.get('decision') if isinstance(intent, dict) else None
    subject = decision.get('subject') if isinstance(decision, dict) else None
    kind = subject.get('operationKind') if isinstance(subject, dict) else None
    return kind if isinstance(kind, str) else None


def candidates(store):
    """(the provider-envelope candidates in reservation order, None), or ([], why a receipt under the recorder's
    prefix is not readable or not the recorder's)."""
    found, ids = [], {}
    for reservation in store.attempts():
        key = reservation.operation_key
        if not key.startswith(RECEIPT_PREFIX):
            continue
        try:
            intent = json.loads(reservation.intent_json)
        except (TypeError, ValueError):
            intent = None
        kind = _kind_of(intent)
        if kind is None:
            return [], f'{key}: its operation kind cannot be read'
        if kind != OPERATION_KIND:
            continue
        events = store.events(key)
        actor = events[0].actor if events else None
        if actor != RECORDER:
            return [], f'{key} was reserved by {actor!r}, not {RECORDER}'
        if intent.get('format') != RECEIPT_FORMAT or intent.get('recorder') != RECORDER:
            return [], f'{key} is not an {RECEIPT_FORMAT} receipt of {RECORDER}'
        decision = stored_decision(intent['decision'])
        problems = D.check_record(decision)
        if not problems and decision['kind'] != KIND:
            problems = [f'kind must be {KIND}']
        if problems:
            return [], f'{key}: its decision is not a well-formed {D.FORMAT} record: {problems[0]}'
        subject = decision['subject']
        if key != RECEIPT_PREFIX + decision['shown']['nonce'] or intent.get('operation') != subject['operation'] \
                or intent.get('digest') != subject['digest']:
            return [], f'{key}: its decision does not bind the receipt\'s key, operation and manifest digest'
        if decision['decisionId'] in ids:
            return [], f'{key} repeats the decisionId {decision["decisionId"]} of {ids[decision["decisionId"]]}'
        ids[decision['decisionId']] = key
        found.append(Candidate(key, events[0].event_id, reservation.state, intent, decision))
    found.sort(key=lambda candidate: candidate.order)
    return found, None


def _expiry(text):
    return datetime.datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)


def verify_envelope(store, target, manifest_digest: Callable[[str], str], now):
    """Whether the live envelope, whose canonical digest is TARGET (``sha256:<64 hex>``), is authorized at NOW
    (an aware datetime). MANIFEST_DIGEST(operation) gives the sha256 (``sha256:<64 hex>``) of the canonical
    manifest of the live envelope under that operation id. A ``Verdict``; see the module's docstring."""
    if not isinstance(target, str) or not D.DIGEST.match(target) or not callable(manifest_digest) \
            or not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise ValueError('verify_envelope takes the live digest, the manifest digest function and an aware time')
    found, problem = candidates(store)
    if problem is not None:
        return _refused('ENVELOPE_RECORD_INVALID', problem)
    confirmed = [c for c in found if c.state == 'confirmed']
    after = found[found.index(confirmed[-1]) + 1:] if confirmed else found
    unsettled = [c for c in after if c.state in UNSETTLED]
    if not confirmed and not unsettled:
        return _refused('ENVELOPE_NOT_AUTHORIZED', f'the store holds no confirmed {OPERATION_KIND} authorization '
                        f'({len(found)} receipt(s), none confirmed or unsettled)')
    if unsettled:
        names = ', '.join(f'{c.key} ({c.state})' for c in unsettled)
        return _refused('ENVELOPE_AUTHORIZATION_UNRESOLVED', f'a later {OPERATION_KIND} decision is not settled: '
                        f'{names}; resolve it (authorization_recorder.py resolve --challenge <nonce>)')
    governing = confirmed[-1]
    subject = governing.decision['subject']
    if subject['target'] != target:
        earlier = [c for c in confirmed[:-1] if c.decision['subject']['target'] == target]
        if earlier:
            return _refused('ENVELOPE_REPLAYED', f'the live envelope {target} was authorized by {earlier[-1].key}, '
                            f'which {governing.key} (operation {subject["operation"]}) supersedes')
        return _refused('ENVELOPE_MISMATCH', f'the live envelope is {target}; the governing authorization '
                        f'{governing.key} (operation {subject["operation"]}) is for {subject["target"]}')
    canonical = manifest_digest(subject['operation'])
    if canonical != governing.intent['digest']:
        return _refused('ENVELOPE_MISMATCH', f'the manifest merged under {governing.key} is '
                        f'{governing.intent["digest"]}, not the canonical manifest of the live envelope '
                        f'({canonical})')
    if now >= _expiry(subject['expiresAt']):
        return _refused('ENVELOPE_EXPIRED', f'the authorization {governing.key} expired at {subject["expiresAt"]}')
    return Verdict(None, '', {'receipt': governing.key, 'operation': subject['operation'],
                              'decisionId': governing.decision['decisionId'], 'target': subject['target'],
                              'digest': governing.intent['digest'], 'expiresAt': subject['expiresAt']})


def verifier(store) -> Callable:
    """``verify_envelope`` over STORE, as the inference broker's ``Context.authorization`` gives it."""
    def verify(target, manifest_digest, now):
        return verify_envelope(store, target, manifest_digest, now)
    return verify
