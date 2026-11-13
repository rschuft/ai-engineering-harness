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
decision file, Gitea or a credential. Standard library only, plus the record formats of ``owner_decision.py``
and ``delegated_decision.py``; it imports no store module (the store is passed in: anything with
``attempts``, ``events`` and ``get``).

The model selection (slice 2): ``verify_selection`` answers the governing ``select-models`` record of the
one series ``model-selection/v1/<sequence>`` (``SELECTION_REFUSALS``); the source that ``verifier(store)``
returns answers both (``Source``).
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
G = _load('delegated_decision', HERE / 'delegated_decision.py')

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


class Governing(NamedTuple):
    """The governing authorization (CODE None) with the confirmed candidates before it, or CODE one of
    ``ENVELOPE_RECORD_INVALID``, ``ENVELOPE_NOT_AUTHORIZED`` and ``ENVELOPE_AUTHORIZATION_UNRESOLVED`` with its
    DETAIL."""
    code: str | None
    detail: str
    candidate: Candidate | None
    confirmed: list


def governing(store):
    """The governing provider-envelope authorization: the last confirmed candidate, unless a receipt cannot be
    trusted, none is confirmed and none unsettled, or a later one is unsettled (in that order)."""
    found, problem = candidates(store)
    if problem is not None:
        return Governing('ENVELOPE_RECORD_INVALID', problem, None, [])
    confirmed = [c for c in found if c.state == 'confirmed']
    after = found[found.index(confirmed[-1]) + 1:] if confirmed else found
    unsettled = [c for c in after if c.state in UNSETTLED]
    if not confirmed and not unsettled:
        return Governing('ENVELOPE_NOT_AUTHORIZED', f'the store holds no confirmed {OPERATION_KIND} authorization '
                         f'({len(found)} receipt(s), none confirmed or unsettled)', None, [])
    if unsettled:
        names = ', '.join(f'{c.key} ({c.state})' for c in unsettled)
        return Governing('ENVELOPE_AUTHORIZATION_UNRESOLVED', f'a later {OPERATION_KIND} decision is not settled: '
                         f'{names}; resolve it (authorization_recorder.py resolve --challenge <nonce>)', None, [])
    return Governing(None, '', confirmed[-1], confirmed)


def basis_problem(store, receipt, now):
    """Why RECEIPT (a recorder receipt key) is not the governing, unexpired provider-envelope authorization at
    NOW, or None when it is: what a model selection may rest on (decision 0018 point 3)."""
    answer = governing(store)
    if answer.code is not None:
        return f'{answer.code}: {answer.detail}'
    held = answer.candidate
    if held.key != receipt:
        later = 'a later authorization supersedes it' if any(c.key == receipt for c in answer.confirmed) \
            else 'it is not a confirmed provider-envelope authorization'
        return f'{receipt} does not govern ({later}); the governing authorization is {held.key}'
    expires = held.decision['subject']['expiresAt']
    if now >= _expiry(expires):
        return f'{receipt} expired at {expires}'
    return None


def verify_envelope(store, target, manifest_digest: Callable[[str], str], now):
    """Whether the live envelope, whose canonical digest is TARGET (``sha256:<64 hex>``), is authorized at NOW
    (an aware datetime). MANIFEST_DIGEST(operation) gives the sha256 (``sha256:<64 hex>``) of the canonical
    manifest of the live envelope under that operation id. A ``Verdict``; see the module's docstring."""
    if not isinstance(target, str) or not D.DIGEST.match(target) or not callable(manifest_digest) \
            or not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise ValueError('verify_envelope takes the live digest, the manifest digest function and an aware time')
    answer = governing(store)
    if answer.code is not None:
        return _refused(answer.code, answer.detail)
    confirmed, held = answer.confirmed, answer.candidate
    subject = held.decision['subject']
    if subject['target'] != target:
        earlier = [c for c in confirmed[:-1] if c.decision['subject']['target'] == target]
        if earlier:
            return _refused('ENVELOPE_REPLAYED', f'the live envelope {target} was authorized by {earlier[-1].key}, '
                            f'which {held.key} (operation {subject["operation"]}) supersedes')
        return _refused('ENVELOPE_MISMATCH', f'the live envelope is {target}; the governing authorization '
                        f'{held.key} (operation {subject["operation"]}) is for {subject["target"]}')
    canonical = manifest_digest(subject['operation'])
    if canonical != held.intent['digest']:
        return _refused('ENVELOPE_MISMATCH', f'the manifest merged under {held.key} is '
                        f'{held.intent["digest"]}, not the canonical manifest of the live envelope '
                        f'({canonical})')
    if now >= _expiry(subject['expiresAt']):
        return _refused('ENVELOPE_EXPIRED', f'the authorization {held.key} expired at {subject["expiresAt"]}')
    return Verdict(None, '', {'receipt': held.key, 'operation': subject['operation'],
                              'decisionId': held.decision['decisionId'], 'target': subject['target'],
                              'digest': held.intent['digest'], 'expiresAt': subject['expiresAt']})


# ---------------------------------------------------------------------------- the model-selection series


# The model selections (decision 0018 point 3, kind select-models; S-03.5 slice 2) form ONE series: each is a
# write-ahead receipt of the selection recorder (selection_recorder.py) at the next position of
# model-selection/v1/<sequence>, from 1, contiguous. A position is spent once reserved. The last confirmed
# position governs a start (verify_selection).
SELECTION_PREFIX = 'model-selection/v1/'
SELECTION_RECORDER = 'selection-recorder/1'
SELECTION_FORMAT = 'aieh-model-selection/1'
SELECTION_INTENT = ('format', 'recorder', 'series', 'decision', 'sequence', 'receipt')


def selection_key(sequence):
    return f'{SELECTION_PREFIX}{sequence}'


class Selection(NamedTuple):
    """One receipt of the model-selection series: its key, position, state and intent (None when it is not a
    JSON object)."""
    key: str
    position: int
    state: str
    intent: dict | None


def selections(store):
    """The model-selection series, from position 1 to the first free one, by direct lookups."""
    out, position = [], 1
    while (reservation := store.get(selection_key(position))) is not None:
        try:
            intent = json.loads(reservation.intent_json)
        except (TypeError, ValueError):
            intent = None
        out.append(Selection(reservation.operation_key, position, reservation.state,
                             intent if isinstance(intent, dict) else None))
        position += 1
    return out


def last_confirmed_selection(series):
    """The last confirmed receipt of the series, or None."""
    return next((s for s in reversed(series) if s.state == 'confirmed'), None)


# verify_selection's refusals, in the order they are checked (beside REFUSALS: the broker's codes).
SELECTION_REFUSALS = {
    'MODEL_SELECTION_MISSING': 'the model-selection series has no confirmed record',
    'MODEL_SELECTION_NOT_AUTHORIZED': 'the governing selection is not a select-models record the delegation admits, '
                                      'written by the selection recorder',
    'MODEL_SELECTION_RECEIPT_MISMATCH': 'the governing selection rests on another provider-envelope authorization',
}
SELECTION_VIEW = ('receipt', 'decisionId', 'record', 'point', 'basis', 'models')
SELECTION_KIND = 'select-models'


def stored_selection(decision):
    """DECISION as read from a selection receipt, with the fields of ``delegated-decision/v1`` and of the
    ``select-models`` subject in their order again (the store sorts an intent's keys). Nothing but the order
    changes; a record of another format is returned as it is."""
    if not isinstance(decision, dict) or decision.get('format') != G.FORMAT:
        return decision
    record = _ordered(decision, G.FIELDS)
    delegation = record.get('delegation')
    if isinstance(delegation, dict):
        record['delegation'] = delegation = _ordered(delegation, G.DELEGATION_FIELDS)
        basis = delegation.get('basis')
        delegation['basis'] = _ordered(basis, G.RECEIPT_FIELDS if isinstance(basis, dict) and 'receipt' in basis
                                       else G.QUOTE_FIELDS)
    subject = record.get('subject')
    kind = record.get('kind')
    if kind != SELECTION_KIND:
        # another kind (a record the head may hold by mistake or by hand): its own field order, so that the
        # kind, not the order, is what refuses it
        if isinstance(subject, dict) and kind in D.SUBJECT_FIELDS:
            record['subject'] = subject = _ordered(subject, D.SUBJECT_FIELDS[kind])
            if isinstance(subject.get('previous'), dict):
                subject['previous'] = _ordered(subject['previous'], D.PREVIOUS_FIELDS)
            if isinstance(subject.get('designs'), list):
                subject['designs'] = [_ordered(b, D.DESIGN_BINDING_FIELDS) for b in subject['designs']]
        return record
    if isinstance(subject, dict):
        record['subject'] = subject = _ordered(subject, G.SELECTION_FIELDS)
        subject['verified'] = _ordered(subject.get('verified'), G.VERIFIED_FIELDS)
        if isinstance(subject.get('models'), dict):
            subject['models'] = {family: [_ordered(entry, G.SELECTED_MODEL_FIELDS) for entry in entries]
                                 if isinstance(entries, list) else entries
                                 for family, entries in subject['models'].items()}
    return record


def verify_selection(store, receipt):
    """The governing model selection (the last confirmed position of the series) for the provider-envelope
    authorization RECEIPT (its key), in this order: none confirmed is ``MODEL_SELECTION_MISSING``; a head not
    reserved by the selection recorder, not its receipt format, or whose decision is not a well-formed
    ``delegated-decision/v1`` of kind ``select-models`` (the delegation table's row: decision:0018 point 3,
    decided by the engineering manager) binding the receipt's position and basis is
    ``MODEL_SELECTION_NOT_AUTHORIZED``; a head resting on another receipt is
    ``MODEL_SELECTION_RECEIPT_MISMATCH``. Otherwise the view: the selection's receipt key, its decisionId, the
    delegating record and point, the basis receipt and the selected identifiers per family (never the record's
    revision, a commit id)."""
    if not isinstance(receipt, str):
        raise ValueError('verify_selection takes the governing receipt\'s key')
    head = last_confirmed_selection(selections(store))
    if head is None:
        return _refused('MODEL_SELECTION_MISSING', 'the model-selection series holds no confirmed selection')
    events = store.events(head.key)
    actor = events[0].actor if events else None
    if actor != SELECTION_RECORDER:
        return _refused('MODEL_SELECTION_NOT_AUTHORIZED', f'{head.key} was reserved by {actor!r}, not '
                        f'{SELECTION_RECORDER}')
    intent = head.intent
    if intent is None or set(intent) != set(SELECTION_INTENT) or intent['format'] != SELECTION_FORMAT \
            or intent['recorder'] != SELECTION_RECORDER or intent['series'] != 'selection' \
            or intent['sequence'] != head.position:
        return _refused('MODEL_SELECTION_NOT_AUTHORIZED', f'{head.key} is not an {SELECTION_FORMAT} receipt of its '
                        'position')
    decision = stored_selection(intent['decision'])
    problems = G.check_record(decision) if isinstance(decision, dict) and decision.get('format') == G.FORMAT \
        else [f'the decision is not a {G.FORMAT} record']
    if not problems and decision['kind'] != SELECTION_KIND:
        problems = [f'kind must be {SELECTION_KIND}']
    basis = decision.get('delegation', {}).get('basis') if isinstance(decision, dict) else None
    if not problems and (not isinstance(basis, dict) or basis.get('receipt') != intent['receipt']):
        problems = ['the decision\'s basis is not the receipt its receipt names']
    if problems:
        return _refused('MODEL_SELECTION_NOT_AUTHORIZED', f'{head.key}: {problems[0]}')
    if intent['receipt'] != receipt:
        return _refused('MODEL_SELECTION_RECEIPT_MISMATCH', f'{head.key} (decision {decision["decisionId"]}) rests on '
                        f'{intent["receipt"]}, not the governing authorization {receipt}')
    delegation = decision['delegation']
    return Verdict(None, '', {'receipt': head.key, 'decisionId': decision['decisionId'],
                              'record': delegation['record'], 'point': delegation['point'],
                              'basis': intent['receipt'],
                              'models': {family: [entry['id'] for entry in entries]
                                         for family, entries in decision['subject']['models'].items()}})


class Source:
    """The decision source the inference broker's ``Context.authorization`` gives for one store: called as
    ``verify_envelope`` (slice 1's protocol, unchanged), and ``selection(receipt)``: ``verify_selection``."""

    def __init__(self, store):
        self._store = store

    def __call__(self, target, manifest_digest, now):
        return verify_envelope(self._store, target, manifest_digest, now)

    def selection(self, receipt):
        return verify_selection(self._store, receipt)


def verifier(store) -> Source:
    """The decision source over STORE, as the inference broker's ``Context.authorization`` gives it."""
    return Source(store)
