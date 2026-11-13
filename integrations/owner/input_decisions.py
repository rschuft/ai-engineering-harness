"""The dispatch-input decision series and their verifier (plan leaf P-04.3): the read side of the
dispatch-input commands (``input_recorder.py``), importable without them.

Two kinds of decision approve dispatch inputs, each decided by the Owner (an ``owner-decision/v1``
record) or under decision 0018 point 3 (a ``delegated-decision/v1`` record):

- ``accept-design``: the design of one OpenSpec change of one manifest repository at an exact
  revision. The acceptances of one (repository, change) form one series; each is a write-ahead receipt
  in the integration store at ``dispatch-inputs/v1/design/<repository>/<change>/<sequence>``.
- ``promote-manifest``: an approved-input manifest. The promotions form one series whose position is
  the manifest's ``version`` (from 1, contiguous); each is a receipt at
  ``dispatch-inputs/v1/promotion/<version>`` that also keeps the manifest's exact text.

A receipt (intent format ``aieh-dispatch-input-decision/1``) is usable only when it is ``confirmed``. A
position is spent once reserved: a failed or unconfirmed position is never reused, and the next
decision takes the next free one. The link of a decision (``supersedes``, ``previous``) names the last
confirmed decision of its series.

``verify_manifest`` (or the callable ``verifier(store)``) answers whether a manifest, at its version and
sha256, is approved: the promotion at its version is confirmed, binds that digest, is the last
confirmed promotion, and each of its design entries has the confirmed acceptance the promotion bound.
It reads the integration store only (never a decision file, the live manifest or a repository), by
direct lookups: no scan. Its refusal codes (``REFUSALS``) are those ``load_manifest`` adds (P-04.3
slice 2).

Standard library only, plus ``owner_decision.py`` and ``delegated_decision.py``'s record formats. It
imports no store module: the store is passed in (``integration_store.IntegrationStore`` or anything with
its ``get``).
"""
import importlib.util
import json
import re
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

DESIGN, PROMOTION = 'accept-design', 'promote-manifest'
RECORDER = 'dispatch-input-recorder/1'  # the actor of every receipt the dispatch-input commands reserve
RECEIPT_FORMAT = 'aieh-dispatch-input-decision/1'
KEY_PREFIX = 'dispatch-inputs/v1/'
PROMOTION_PREFIX = KEY_PREFIX + 'promotion/'
DESIGN_PREFIX = KEY_PREFIX + 'design/'
APPROVAL_FORMAT = 'ai-engineering-harness/dispatch/manifest-approval/v1'
# The fields of each series' receipt intent (the store keeps an intent as canonical JSON: its keys sorted).
PROMOTION_INTENT = ('format', 'recorder', 'series', 'decision', 'schema', 'version', 'digest', 'previous', 'text')
DESIGN_INTENT = ('format', 'recorder', 'series', 'decision', 'repository', 'change', 'sequence')
SHA256_HEX = re.compile(r'^[0-9a-f]{64}$')

# load_manifest's refusals for an unapproved manifest (checked in this order).
REFUSALS = {
    'MANIFEST_NOT_PROMOTED': 'no decision source was given, the store holds no promotion receipt at this version, '
                             'or the manifest was not loaded by load_manifest',
    'DECISION_RECORD_INVALID': 'a receipt\'s decision is not a well-formed record of its format and kind, or does not '
                               'bind what the receipt says; also a verifier answer that is not well formed',
    'MANIFEST_PROMOTION_UNCONFIRMED': 'the promotion receipt exists but is not confirmed (run manifest resolve)',
    'MANIFEST_DIGEST_MISMATCH': 'the file\'s sha256 is not the decided digest',
    'DECISION_REPLAYED': 'a later promotion is confirmed',
    'DESIGN_ACCEPTANCE_MISSING': 'a design entry has no binding, or no confirmed design-acceptance receipt whose '
                                 'subject equals it',
}


def promotion_key(version):
    return f'{PROMOTION_PREFIX}{version}'


def design_key(repository, change, sequence):
    return f'{DESIGN_PREFIX}{repository}/{change}/{sequence}'


class Receipt(NamedTuple):
    """One receipt of a series: its key, position, state and intent (None when it is not JSON)."""
    key: str
    position: int
    state: str
    intent: dict | None


def _ordered(value, fields):
    """VALUE (a dict) with FIELDS first, in their order, then any other key as it came: an extra or a
    missing field still fails the record's check."""
    if not isinstance(value, dict):
        return value
    return {**{name: value[name] for name in fields if name in value},
            **{name: item for name, item in value.items() if name not in fields}}


def stored_record(decision):
    """DECISION as read from a receipt, with its fields in its format's order again. The store keeps an
    intent as canonical JSON, whose object keys are sorted; the formats' checks also check the order of
    the fields, which the store does not keep. Nothing but the order changes."""
    if not isinstance(decision, dict):
        return decision
    def reorder(parent, name, fields):
        if isinstance(parent, dict) and name in parent:
            parent[name] = _ordered(parent[name], fields)
            return parent[name]
        return None

    kind = decision.get('kind')
    if decision.get('format') == D.FORMAT:
        record = _ordered(decision, D.FIELDS)
        reorder(record, 'shown', D.SHOWN_FIELDS)
        reorder(record, 'statement', D.STATEMENT_FIELDS)
    elif decision.get('format') == G.FORMAT:
        record = _ordered(decision, G.FIELDS)
        reorder(reorder(record, 'delegation', G.DELEGATION_FIELDS), 'basis', G.QUOTE_FIELDS)
    else:
        return decision
    subject = reorder(record, 'subject', D.SUBJECT_FIELDS[kind]) if kind in D.SUBJECT_FIELDS else None
    if kind == PROMOTION and isinstance(subject, dict):
        reorder(subject, 'previous', D.PREVIOUS_FIELDS)
        if isinstance(subject.get('designs'), list):
            subject['designs'] = [_ordered(b, D.DESIGN_BINDING_FIELDS) for b in subject['designs']]
    return record


def read_receipt(store, key, position):
    reservation = store.get(key)
    if reservation is None:
        return None
    try:
        intent = json.loads(reservation.intent_json)
    except (TypeError, ValueError):
        intent = None
    if not isinstance(intent, dict):
        intent = None
    elif 'decision' in intent:
        intent['decision'] = stored_record(intent['decision'])
    return Receipt(key, position, reservation.state, intent)


def _series(store, key_of):
    """Every receipt of a series, from position 1 to the first free one."""
    out, position = [], 1
    while (receipt := read_receipt(store, key_of(position), position)) is not None:
        out.append(receipt)
        position += 1
    return out


def promotions(store):
    """The promotion series, in version order."""
    return _series(store, promotion_key)


def design_series(store, repository, change):
    """The acceptances of one change, in sequence order."""
    return _series(store, lambda sequence: design_key(repository, change, sequence))


def next_position(series):
    """The next free position of SERIES (positions are contiguous from 1)."""
    return len(series) + 1


def last_confirmed(series):
    """The last confirmed receipt of SERIES, or None."""
    return next((r for r in reversed(series) if r.state == 'confirmed'), None)


# ---------------------------------------------------------------------------- decisions


def decision_problems(decision, kind):
    """The problems of DECISION as a well-formed record of KIND in either format."""
    if not isinstance(decision, dict):
        return ['the decision must be an object']
    fmt = decision.get('format')
    if fmt == D.FORMAT:
        problems = D.check_record(decision)
    elif fmt == G.FORMAT:
        problems = G.check_record(decision)
    else:
        return [f'format must be {D.FORMAT} or {G.FORMAT}']
    if decision.get('kind') != kind:
        problems.append(f'kind must be {kind}')
    return problems


def authority(decision):
    """Who decided: the Owner (with the statement's channel and reference), or the delegation (the
    delegating record, its point, the revision it was read at, the decider and the basis)."""
    if decision['format'] == D.FORMAT:
        statement = decision['statement']
        return {'authority': 'owner', 'channel': statement['channel'], 'reference': statement['reference'],
                'recordedBy': decision['recordedBy']}
    delegation = decision['delegation']
    return {'authority': 'delegated', 'record': delegation['record'], 'point': delegation['point'],
            'revision': delegation['revision'], 'decidedBy': decision['decidedBy'], 'basis': delegation['basis']}


def _named(decision, key):
    return {'decisionId': decision['decisionId'], 'format': decision['format'], 'kind': decision['kind'],
            'receipt': key, 'authority': authority(decision)}


def promotion_problems(receipt):
    """The problems of a promotion receipt's intent and decision (it binds its own version and digest)."""
    intent = receipt.intent
    if intent is None or set(intent) != set(PROMOTION_INTENT) or intent['format'] != RECEIPT_FORMAT \
            or intent['series'] != 'promotion':
        return [f'{receipt.key} is not an {RECEIPT_FORMAT} promotion receipt']
    decision = intent['decision']
    problems = decision_problems(decision, PROMOTION)
    if problems:
        return problems
    subject = decision['subject']
    if not (intent['version'] == subject['version'] == receipt.position and intent['digest'] == subject['digest']
            and intent['previous'] == subject['previous'] and intent['schema'] == subject['schema']):
        return [f'{receipt.key}: the decision does not bind the receipt\'s version, digest and previous']
    return []


def design_problems(receipt, repository, change):
    """The problems of a design-acceptance receipt's intent and decision (it binds its own change and
    sequence)."""
    intent = receipt.intent
    if intent is None or set(intent) != set(DESIGN_INTENT) or intent['format'] != RECEIPT_FORMAT \
            or intent['series'] != 'design':
        return [f'{receipt.key} is not an {RECEIPT_FORMAT} design receipt']
    decision = intent['decision']
    problems = decision_problems(decision, DESIGN)
    if problems:
        return problems
    subject = decision['subject']
    if not (intent['repository'] == subject['repository'] == repository
            and intent['change'] == subject['change'] == change and intent['sequence'] == receipt.position):
        return [f'{receipt.key}: the decision does not bind the receipt\'s change and sequence']
    return []


class DesignAnswer(NamedTuple):
    """The acceptance a design entry rests on: CODE is None and BINDING the promotion subject's binding
    ``{repository, change, commit, acceptance, sequence}``, or CODE is ``DESIGN_ACCEPTANCE_MISSING``,
    ``DECISION_REPLAYED`` or ``DECISION_RECORD_INVALID`` with its DETAIL."""
    code: str | None
    detail: str
    binding: dict | None


def design_binding(store, repository, change, commit):
    """The current acceptance of CHANGE of REPOSITORY at COMMIT: the last confirmed acceptance of the change,
    when it names COMMIT. A commit only an earlier, superseded acceptance names is ``DECISION_REPLAYED``;
    none at all is ``DESIGN_ACCEPTANCE_MISSING``."""
    series = design_series(store, repository, change)
    confirmed = [r for r in series if r.state == 'confirmed']
    for receipt in confirmed:
        problems = design_problems(receipt, repository, change)
        if problems:
            return DesignAnswer('DECISION_RECORD_INVALID', problems[0], None)
    if not confirmed:
        return DesignAnswer('DESIGN_ACCEPTANCE_MISSING', f'{repository}/{change} has no confirmed design '
                            'acceptance', None)
    head = confirmed[-1]
    decision = head.intent['decision']
    if decision['subject']['commit'] == commit:
        return DesignAnswer(None, '', {'repository': repository, 'change': change, 'commit': commit,
                                       'acceptance': decision['decisionId'], 'sequence': head.position})
    if any(r.intent['decision']['subject']['commit'] == commit for r in confirmed[:-1]):
        return DesignAnswer('DECISION_REPLAYED', f'{repository}/{change} at {commit} was accepted, but that '
                            f'acceptance is superseded by {decision["decisionId"]} (sequence {head.position}, at '
                            f'{decision["subject"]["commit"]})', None)
    return DesignAnswer('DESIGN_ACCEPTANCE_MISSING', f'{repository}/{change} has no acceptance at {commit}; its '
                        f'current acceptance is at {decision["subject"]["commit"]}', None)


# ---------------------------------------------------------------------------- the verifier


def reserved_by(store, key):
    """The actor of KEY's reservation (its first event), or None."""
    events = store.events(key)
    return events[0].actor if events else None


def series_problem(store, version):
    """Why the promotion series up to VERSION is not one the recorder writes, or None. Walked by direct
    lookups from position 1 to VERSION: every position is present (positions are contiguous), reserved by
    the recorder (``RECORDER``) and a well-formed promotion of its position; no ``decisionId`` and no Owner
    challenge (``shown.nonce``) appears twice; and each confirmed promotion's ``previous`` is the confirmed
    promotion before it. A store written by hand can still satisfy all of this (decision 0010 point 1), and
    a gap above VERSION cannot be seen without listing the store, which the verifier does not do."""
    ids, nonces, prior = {}, {}, None
    for position in range(1, version + 1):
        key = promotion_key(position)
        receipt = read_receipt(store, key, position)
        if receipt is None:
            return f'the promotion series has no receipt at position {position}, below version {version}'
        if (actor := reserved_by(store, key)) != RECORDER:
            return f'{key} was reserved by {actor!r}, not {RECORDER}'
        problems = promotion_problems(receipt)
        if problems:
            return f'position {position}: {problems[0]}'
        decision = receipt.intent['decision']
        if decision['decisionId'] in ids:
            return (f'position {position} repeats the decisionId {decision["decisionId"]} of position '
                    f'{ids[decision["decisionId"]]}')
        ids[decision['decisionId']] = position
        nonce = decision['shown']['nonce'] if decision['format'] == D.FORMAT else None
        if nonce is not None:
            if nonce in nonces:
                return f'position {position} repeats the challenge {nonce} of position {nonces[nonce]}'
            nonces[nonce] = position
        if receipt.state == 'confirmed':
            if decision['subject']['previous'] != prior:
                return (f'position {position} names previous {decision["subject"]["previous"]}, not the prior '
                        f'confirmed promotion {prior}')
            prior = {'version': position, 'digest': decision['subject']['digest']}
    return None



class Verdict(NamedTuple):
    """The verifier's answer: CODE None and APPROVAL the approval view
    (``ai-engineering-harness/dispatch/manifest-approval/v1``), or CODE one of ``REFUSALS`` with its
    DETAIL."""
    code: str | None
    detail: str
    approval: dict | None


def _refused(code, detail):
    return Verdict(code, detail, None)


def verify_manifest(store, version, sha256, designs):
    """Whether the manifest at VERSION whose bytes have SHA256 (64 lower-case hex digits) and whose
    ``designs`` entries are DESIGNS (``[{repository, change, commit}]``, in manifest order) is approved.

    In this order: no receipt at the version is ``MANIFEST_NOT_PROMOTED``; a receipt whose decision is not
    a well-formed ``promote-manifest`` record binding the receipt's version and digest is
    ``DECISION_RECORD_INVALID``, and so is a promotion series that is not one the recorder writes, walked by
    direct lookups from position 1 to VERSION (``series_problem``); one not confirmed is ``MANIFEST_PROMOTION_UNCONFIRMED``; another digest is
    ``MANIFEST_DIGEST_MISMATCH``; a confirmed promotion at a later version is ``DECISION_REPLAYED``; a design
    entry without the confirmed acceptance the promotion bound for it is ``DESIGN_ACCEPTANCE_MISSING``.
    Otherwise the approval view: the promotion decision and each design entry's acceptance decision, with
    their receipts and authority."""
    if isinstance(version, bool) or not isinstance(version, int) or version < 1 or not isinstance(sha256, str) \
            or not SHA256_HEX.fullmatch(sha256) or not isinstance(designs, list):
        raise ValueError('verify_manifest takes a version of at least 1, a sha256 and the designs entries')
    key = promotion_key(version)
    receipt = read_receipt(store, key, version)
    if receipt is None:
        return _refused('MANIFEST_NOT_PROMOTED', f'the store holds no promotion receipt {key}')
    problems = promotion_problems(receipt)
    if problems:
        return _refused('DECISION_RECORD_INVALID', problems[0])
    problem = series_problem(store, version)
    if problem is not None:
        return _refused('DECISION_RECORD_INVALID', problem)
    if receipt.state != 'confirmed':
        return _refused('MANIFEST_PROMOTION_UNCONFIRMED', f'{key} is {receipt.state}, not confirmed')
    decision = receipt.intent['decision']
    decided = decision['subject']['digest']
    if decided != f'sha256:{sha256}':
        return _refused('MANIFEST_DIGEST_MISMATCH', f'the manifest is sha256:{sha256}; {key} decided {decided}')
    later = version + 1
    while (after := read_receipt(store, promotion_key(later), later)) is not None:
        if after.state == 'confirmed':
            return _refused('DECISION_REPLAYED', f'version {version} was promoted, but {after.key} is confirmed '
                            'after it')
        later += 1
    bindings = {(b['repository'], b['change']): b for b in decision['subject']['designs']}
    named = []
    for entry in designs:
        if not isinstance(entry, dict) or not {'repository', 'change', 'commit'} <= set(entry):
            raise ValueError('each designs entry has repository, change and commit')
        binding = bindings.get((entry['repository'], entry['change']))
        where = f'{entry["repository"]}/{entry["change"]} at {entry["commit"]}'
        if binding is None or binding['commit'] != entry['commit']:
            return _refused('DESIGN_ACCEPTANCE_MISSING', f'{where}: {key} binds no design acceptance for it')
        design = read_receipt(store, design_key(binding['repository'], binding['change'], binding['sequence']),
                              binding['sequence'])
        if design is None or design.state != 'confirmed':
            return _refused('DESIGN_ACCEPTANCE_MISSING', f'{where}: no confirmed design-acceptance receipt at '
                            f'sequence {binding["sequence"]}')
        problems = design_problems(design, binding['repository'], binding['change'])
        if problems:
            return _refused('DECISION_RECORD_INVALID', problems[0])
        if (actor := reserved_by(store, design.key)) != RECORDER:
            return _refused('DECISION_RECORD_INVALID', f'{design.key} was reserved by {actor!r}, not {RECORDER}')
        accepted = design.intent['decision']
        if accepted['decisionId'] != binding['acceptance'] or accepted['subject']['commit'] != entry['commit']:
            return _refused('DESIGN_ACCEPTANCE_MISSING', f'{where}: {design.key} is not the acceptance {key} bound')
        named.append({'repository': entry['repository'], 'change': entry['change'], 'commit': entry['commit'],
                      'sequence': binding['sequence'], **_named(accepted, design.key)})
    return Verdict(None, '', {'format': APPROVAL_FORMAT, 'version': version, 'digest': decided,
                              'promotion': _named(decision, key), 'designs': named})


def verifier(store) -> Callable[[int, str, list], Verdict]:
    """``verify_manifest`` over STORE, as the callable ``load_manifest(path, decisions=...)`` asks."""
    def verify(version, sha256, designs):
        return verify_manifest(store, version, sha256, designs)
    return verify
