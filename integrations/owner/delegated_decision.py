"""The delegated decision record (``delegated-decision/v1``): a decision an accepted decision record
delegates to a named lead, recorded beside the Owner's records and never as one (plan leaf P-04.3;
decision 0018 point 3; decision 0008 point 2, "delegated by an accepted decision record").

A decision of the Owner is an ``owner-decision/v1`` record (``owner_decision.py``): it carries the
challenge the recorder showed and a statement attributed to the Owner. A decision delegated by an
accepted record has neither, so it is this sibling format instead, with the same ``kind`` and the same
``subject`` (validated by the same function), and a ``delegation`` block where the Owner's record has
``shown`` and ``statement``. A record of this format is never an Owner decision, is never kept among the
Owner's records, and is never shown as the Owner's.

Fields, in this order (``FIELDS``):

``format``      ``delegated-decision/v1``
``decisionId``  a random UUID (version 4), canonical lower-case text
``kind``        a kind with a row in the delegation table (``DELEGATIONS``)
``subject``     what was decided on: the row's subject (for the P-04.3 kinds, the subject of the same
                kind in ``owner-decision/v1``)
``delegation``  ``record`` (the delegating record, such as ``decision:0018``), ``point`` (its point),
                ``revision`` (the full commit of the harness repository at which the record and the
                basis were read), ``digest`` (``sha256:`` of the record file's blob there) and ``basis``
                (what the decision rests on, of the row's basis type)
``decidedBy``   the role the row names
``recordedBy``  equal to ``decidedBy``: a delegated decision is recorded by the lead that made it
``recordedAt``  when, as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC)

**The delegation table** is data, one row per kind (``Delegation``): the delegating record, its point,
the decider and the basis type. A kind without a row cannot be recorded as delegated
(``DELEGATION_KIND_UNKNOWN``). Another leaf adds its kind by adding a row (and, where it needs one, a basis
type to ``BASIS_TYPES``); the record's fields do not change, and ``check_delegation``,
``read_authority`` and ``decide`` are not specific to any kind.

**What is checked at the act** (``check_delegation`` and ``read_authority``): the row exists, the decider
is the row's, the basis has the row's basis type's shape; the delegating record, read from the harness
repository's ``HEAD`` commit through the repository-access module (the committed blob, never the work
tree; decision 0014), has a ``Status:`` line beginning ``Status: Accepted (Owner) -``; and the basis is
recorded there as an authority of its type, structurally: its link names an anchored entry of the log's
Decisions (``evidence/bootstrap-log.md#<anchor>``); a ``commitment``'s entry is titled ``<date>: Commitment:
...`` (the title begins so) and contains the quote; an ``envelope``'s entry is titled ``<date>: Owner standing authorization: ...``
and the quote lies inside its verbatim block (the ``>`` lines). An absent anchor or quote is
``DELEGATION_BASIS_NOT_RECORDED``; an entry of another kind, or a quote outside it or its block, is
``DELEGATION_BASIS_NOT_AUTHORITY`` (fail closed). Who ran the command, that the decision lies inside the
commitment's scope or the envelope, and the authorship of a log entry are not checked: decision 0018
point 7 ("a log quote is checked for presence, not authorship").

**A basis recorded in the integration store** (plan leaf S-03.5, slice 2): a basis type may need the store
(``BasisType.needs_store``). ``read_authority`` passes the store it is given (a keyword); with none, such a type
refuses (``AUTHORITY_UNAVAILABLE``), never passes. The ``envelope-receipt`` basis of ``select-models`` (decision
0018 point 3: technical model selection inside an authorized model-access envelope, by the engineering manager)
is ``{type, receipt}``, recorded as an authority when the store holds that receipt as a confirmed
``provider-envelope`` authorization reserved by the authorization recorder. Its check reads the store itself,
with the recorder's constants repeated (a test asserts them equal): this module never loads the read side.

The record format and the table are standard library only and open no file; ``read_authority`` alone
loads the repository-access module (Dulwich, from the Python tools set), when it is called.
"""
import hashlib
import importlib.util
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Callable, NamedTuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


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

FORMAT = 'delegated-decision/v1'
FIELDS = ('format', 'decisionId', 'kind', 'subject', 'delegation', 'decidedBy', 'recordedBy', 'recordedAt')
DELEGATION_FIELDS = ('record', 'point', 'revision', 'digest', 'basis')
RECORD = re.compile(r'^decision:([0-9]{4})$')
POINT = re.compile(r'^[1-9][0-9]*(?:\.[1-9][0-9]*)*$')
DECISIONS_DIR = 'decisions'
LOG = 'evidence/bootstrap-log.md'
STATUS_PREFIX = 'Status:'
ACCEPTED_BY_OWNER = 'Status: Accepted (Owner) -'  # exactly this, then the date: a qualified variant is not accepted
QUOTE_MIN = 12
COMMITMENT_MARK = 'Commitment: '


class DelegationRefused(Exception):
    """A delegated decision that cannot be made, with a stable code (the recorder's)."""

    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}')


# ---------------------------------------------------------------------------- basis types


class HarnessView(NamedTuple):
    """What ``read_authority`` read at the harness repository's ``HEAD``: the commit, the delegating
    record's text and blob digest, and the log's text (None when the log is absent)."""
    revision: str
    record_path: str
    record_text: str
    record_digest: str
    log_text: str | None


class BasisType(NamedTuple):
    """A kind of basis: ``problems(basis)`` lists what is wrong with its shape; ``unrecorded(basis, view)``
    answers why it is not recorded as an authority of its type at the harness's ``HEAD`` (a ``HarnessView``),
    as ``(code, detail)``, or None when it is. A type with NEEDS_STORE is asked ``unrecorded(basis, view,
    store)`` with the integration store ``read_authority`` was given (None when it was given none)."""
    name: str
    problems: Callable[[object], list]
    unrecorded: Callable[..., tuple[str, str] | None]
    needs_store: bool = False


QUOTE_FIELDS = ('type', 'link', 'quote')
ANCHOR = re.compile(r'^[a-z0-9][a-z0-9-]{0,127}$')
DECISIONS_HEADING = '## Decisions'
# A Decisions entry of the log: a top-level list item opening with its anchor and its bold, dated title.
ENTRY_START = re.compile(r'^- <a id="(?P<anchor>[a-z0-9][a-z0-9-]*)"></a>\*\*(?P<title>.+?)\*\*')
DATED_TITLE = re.compile(r'^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}): (?P<rest>.*)$')
STANDING_TITLE = 'Owner standing authorization:'
COMMITMENT_TITLE = 'Commitment:'
VERBATIM_LINE = re.compile(r'^\s*>\s?(?P<text>.*)$')


def _collapsed(text):
    return ' '.join(text.split())


def _quote_problems(name, mark=None):
    """A log quote ``{type, link, quote}``, in the shape of the network matrix's ``owner_approval``
    (tools/check_network_matrix.py), anchored: the link is ``evidence/bootstrap-log.md#<anchor>``, naming the
    Decisions entry the quote is taken from; the quote is verbatim and at least 12 characters."""
    def problems(basis):
        if not isinstance(basis, dict) or list(basis) != list(QUOTE_FIELDS):
            return [f'the basis must be exactly {{{", ".join(QUOTE_FIELDS)}}}']
        out = []
        if basis['type'] != name:
            out.append(f'the basis type must be {name}')
        link = basis['link']
        if not isinstance(link, str) or not link.startswith(f'{LOG}#') or not ANCHOR.match(link[len(LOG) + 1:]):
            out.append(f'the basis link must be {LOG}#<anchor>, the anchor of the Decisions entry it quotes')
        quote = basis['quote']
        if not isinstance(quote, str) or len(quote.strip()) < QUOTE_MIN:
            out.append(f'the basis quote must be the text recorded in {LOG}, verbatim, at least {QUOTE_MIN} '
                       'characters')
        elif mark is not None and mark not in quote:
            out.append(f'the basis quote of a {name} must contain {mark!r}')
        return out
    return problems


class LogEntry(NamedTuple):
    """One anchored Decisions entry of the log: its anchor, its date (None when the title has no ``<date>:``
    prefix), its title without the date, its whole text and its verbatim block (its ``>`` lines with the
    prefixes stripped, joined by newlines)."""
    anchor: str
    date: str | None
    title: str
    text: str
    verbatim: str


def decisions_entry(log_text, anchor):
    """The anchored entry ANCHOR of the log's Decisions section, or None. An entry starts at a top-level list
    item ``- <a id="ANCHOR"></a>**<date>: <title>**`` and runs to the next top-level list item or heading."""
    lines = log_text.splitlines()
    try:
        start = lines.index(DECISIONS_HEADING)
    except ValueError:
        return None
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith('#'):
            return None  # the Decisions section ended
        match = ENTRY_START.match(line)
        if match is None or match.group('anchor') != anchor:
            continue
        end = index + 1
        while end < len(lines) and not lines[end].startswith(('- ', '#')):
            end += 1
        dated = DATED_TITLE.match(match.group('title'))
        body = lines[index:end]
        verbatim = [m.group('text') for m in (VERBATIM_LINE.match(text) for text in body[1:]) if m]
        return LogEntry(anchor, dated.group('date') if dated else None,
                        dated.group('rest') if dated else match.group('title'), '\n'.join(body), '\n'.join(verbatim))
    return None


def _anchored(basis, view):
    """(entry, refusal): the Decisions entry the basis's link names, or why the basis is not recorded."""
    if view.log_text is None:
        return None, ('DELEGATION_BASIS_NOT_RECORDED', f'{LOG} is not in the harness repository at {view.revision}')
    plain = '\n'.join(m.group('text') if (m := VERBATIM_LINE.match(line)) else line
                      for line in view.log_text.splitlines())  # a verbatim block read as its words
    if basis['quote'] not in view.log_text and _collapsed(basis['quote']) not in _collapsed(plain):
        return None, ('DELEGATION_BASIS_NOT_RECORDED', f'the quote is not in {LOG} at {view.revision} (the committed '
                      'log, not the work tree)')
    anchor = basis['link'][len(LOG) + 1:]
    entry = decisions_entry(view.log_text, anchor)
    if entry is None:
        return None, ('DELEGATION_BASIS_NOT_RECORDED', f'{LOG} at {view.revision} has no Decisions entry with the '
                      f'anchor {anchor!r}')
    return entry, None


def _undated(entry):
    return ('DELEGATION_BASIS_NOT_AUTHORITY', f'the entry {entry.anchor!r} has no "<date>: " title: a Decisions '
            'entry of the log is dated')


def _commitment_unrecorded(basis, view):
    """A commitment: the anchored entry's title begins, after its date, with ``Commitment:`` and the quote lies
    inside the entry."""
    entry, refusal = _anchored(basis, view)
    if refusal is not None:
        return refusal
    if entry.date is None:
        return _undated(entry)
    if not entry.title.startswith(COMMITMENT_TITLE):
        return ('DELEGATION_BASIS_NOT_AUTHORITY', f'the entry {entry.anchor!r} is {entry.title!r}, not a '
                f'"{COMMITMENT_TITLE} <milestone>" entry')
    if basis['quote'] not in entry.text:
        return ('DELEGATION_BASIS_NOT_AUTHORITY', f'the quote is not inside the entry {entry.anchor!r}')
    return None


def _envelope_unrecorded(basis, view):
    """A standing authorization: the anchored entry's title begins, after its date, with ``Owner standing
    authorization:``, and the quote lies inside its verbatim block (whitespace collapsed on both sides)."""
    entry, refusal = _anchored(basis, view)
    if refusal is not None:
        return refusal
    if entry.date is None:
        return _undated(entry)
    if not entry.title.startswith(STANDING_TITLE):
        return ('DELEGATION_BASIS_NOT_AUTHORITY', f'the entry {entry.anchor!r} is {entry.title!r}, not an '
                f'"{STANDING_TITLE} ..." entry')
    if not entry.verbatim.strip() or _collapsed(basis['quote']) not in _collapsed(entry.verbatim):
        return ('DELEGATION_BASIS_NOT_AUTHORITY', f'the quote is not inside the verbatim block (the "> " lines) of '
                f'the entry {entry.anchor!r}')
    return None


# The authorization recorder's receipts (authorization_recorder.RECEIPT_PREFIX, RECORDER and RECEIPT_FORMAT) and
# the provider envelope's operation kind (inference_envelope.KIND), repeated: this module loads neither the
# recorder nor the read side (a test asserts that they are equal).
ENVELOPE_RECEIPT_PREFIX = 'owner-authorization/v1/'
ENVELOPE_RECORDER = 'authorization-recorder/1'
ENVELOPE_RECEIPT_FORMAT = 'aieh-owner-authorization/1'
ENVELOPE_KIND = 'provider-envelope'
RECEIPT_FIELDS = ('type', 'receipt')
ENVELOPE_RECEIPT = re.compile(r'^owner-authorization/v1/[0-9a-f]{32}$')


def _receipt_problems(basis):
    """A recorder receipt ``{type, receipt}``: the type ``envelope-receipt`` and the receipt's store key."""
    if not isinstance(basis, dict) or list(basis) != list(RECEIPT_FIELDS):
        return [f'the basis must be exactly {{{", ".join(RECEIPT_FIELDS)}}}']
    out = []
    if basis['type'] != 'envelope-receipt':
        out.append('the basis type must be envelope-receipt')
    if not isinstance(basis['receipt'], str) or not ENVELOPE_RECEIPT.match(basis['receipt']) \
            or '\n' in basis['receipt']:
        out.append(f'the basis receipt must be the key {ENVELOPE_RECEIPT_PREFIX}<32 hex digits> of the provider '
                   'envelope\'s authorization')
    return out


def _envelope_receipt_unrecorded(basis, view, store):
    """An envelope receipt: the integration store holds it, reserved by the authorization recorder, as an
    authorization of operation kind provider-envelope, and confirmed."""
    key = basis['receipt']
    if store is None:
        return ('AUTHORITY_UNAVAILABLE', f'no integration store was given: {key} cannot be read')
    reservation = store.get(key)
    if reservation is None:
        return ('DELEGATION_BASIS_NOT_RECORDED', f'the integration store holds no receipt {key}')
    events = store.events(key)
    actor = events[0].actor if events else None
    try:
        intent = json.loads(reservation.intent_json)
    except (TypeError, ValueError):
        intent = None
    decision = intent.get('decision') if isinstance(intent, dict) else None
    subject = decision.get('subject') if isinstance(decision, dict) else None
    kind = subject.get('operationKind') if isinstance(subject, dict) else None
    if actor != ENVELOPE_RECORDER or not isinstance(intent, dict) or intent.get('format') != ENVELOPE_RECEIPT_FORMAT \
            or intent.get('recorder') != ENVELOPE_RECORDER:
        return ('DELEGATION_BASIS_NOT_AUTHORITY', f'{key} is not a receipt the authorization recorder reserved')
    if kind != ENVELOPE_KIND:
        return ('DELEGATION_BASIS_NOT_AUTHORITY', f'{key} authorizes an operation of kind {kind!r}, not '
                f'{ENVELOPE_KIND}')
    if reservation.state != 'confirmed':
        return ('DELEGATION_BASIS_NOT_AUTHORITY', f'{key} is {reservation.state}, not confirmed')
    return None


BASIS_TYPES = {
    # decision 0018 point 3.2: the log's "Commitment: <milestone>" entry whose scope the design lies in.
    'commitment': BasisType('commitment', _quote_problems('commitment', COMMITMENT_MARK), _commitment_unrecorded),
    # decision 0018 point 3.3: the Owner's standing authorization (point 5), recorded verbatim in the log as an
    # "Owner standing authorization:" entry.
    'envelope': BasisType('envelope', _quote_problems('envelope'), _envelope_unrecorded),
    # decision 0018 point 3 (S-03.5): the Owner's authorization of the model-access envelope, a confirmed
    # provider-envelope receipt of the authorization recorder in the integration store.
    'envelope-receipt': BasisType('envelope-receipt', _receipt_problems, _envelope_receipt_unrecorded,
                                  needs_store=True),
}


# ---------------------------------------------------------------------------- the delegation table


class Delegation(NamedTuple):
    """One row of the delegation table: KIND is decided by DECIDER under POINT of RECORD, resting on a basis
    of BASIS_TYPE; SUBJECT_PROBLEMS validates the kind's subject."""
    kind: str
    record: str
    point: str
    decider: str
    basis_type: str
    subject_problems: Callable[[object], list]


def _owner_subject(kind):
    return lambda subject: D.subject_problems(kind, subject)


# select-models (S-03.5): the subject, its grammars and the inference broker's (FAMILY_ID, MODEL_NAME, WILDCARD),
# repeated (this module imports nothing of the broker; a test asserts that they are equal).
SELECTION_FIELDS = ('leaf', 'models', 'verified', 'supersedes')
SELECTED_MODEL_FIELDS = ('id', 'use', 'cost')
VERIFIED_FIELDS = ('source', 'at')
LEAF = re.compile(r'^[A-Z]-[0-9]{2}(?:\.[0-9]+)*$')
FAMILY_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
MODEL_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}')
WILDCARD = re.compile(r'[*?\[\]]')
TEXT_MAX = 500


def _line(value):
    return isinstance(value, str) and bool(value.strip()) and '\n' not in value and '\r' not in value \
        and len(value) <= TEXT_MAX


def selection_subject_problems(subject):
    """The problems of a ``select-models`` subject: ``leaf`` (the plan leaf that makes the paid call),
    ``models`` (``{<family>: [{id, use, cost}]}``: exact identifiers in the broker's grammar, no wildcard, no
    duplicate, no family empty), ``verified`` (``{source, at}``: where current provider information was read,
    and when) and ``supersedes`` (the decisionId of the selection it replaces, or null)."""
    if not isinstance(subject, dict) or list(subject) != list(SELECTION_FIELDS):
        return [f'subject must have exactly {", ".join(SELECTION_FIELDS)}']
    problems = []
    if not isinstance(subject['leaf'], str) or not LEAF.match(subject['leaf']) or '\n' in subject['leaf']:
        problems.append('subject.leaf must be a plan leaf id, such as S-03.3')
    models = subject['models']
    if not isinstance(models, dict) or not models:
        problems.append('subject.models must be a non-empty mapping {<family>: [{id, use, cost}]}')
    else:
        for family, entries in models.items():
            where = f'subject.models.{family}'
            if not isinstance(family, str) or not FAMILY_ID.fullmatch(family):
                problems.append(f'{where}: the family is not a declared family id')
            if not isinstance(entries, list) or not entries:
                problems.append(f'{where} must be a non-empty list')
                continue
            seen = set()
            for entry in entries:
                if not isinstance(entry, dict) or list(entry) != list(SELECTED_MODEL_FIELDS):
                    problems.append(f'{where}[] must have exactly {", ".join(SELECTED_MODEL_FIELDS)}')
                    continue
                model = entry['id']
                if not isinstance(model, str) or WILDCARD.search(model) or not MODEL_NAME.fullmatch(model):
                    problems.append(f'{where}[].id must be an exact model identifier (no wildcard)')
                elif model in seen:
                    problems.append(f'{where} names {model} twice')
                seen.add(model if isinstance(model, str) else None)
                if not _line(entry['use']) or not _line(entry['cost']):
                    problems.append(f'{where}[].use and .cost must be one line of text, at most {TEXT_MAX} '
                                    'characters')
    verified = subject['verified']
    if not isinstance(verified, dict) or list(verified) != list(VERIFIED_FIELDS) or not _line(verified['source']) \
            or not isinstance(verified['at'], str) or not D.TIMESTAMP.match(verified['at']):
        problems.append('subject.verified must be {source (one line), at (YYYY-MM-DDTHH:MM:SSZ)}')
    supersedes = subject['supersedes']
    if supersedes is not None and (not isinstance(supersedes, str) or not D.UUID4.match(supersedes)):
        problems.append('subject.supersedes must be null or a decisionId (a lower-case version 4 UUID)')
    return problems


DELEGATIONS = {row.kind: row for row in (
    # decision 0018 point 3.2: the product manager accepts the design of an OpenSpec change inside a recorded
    # commitment's scope, "naming this record, the commitment and the exact revision".
    Delegation('accept-design', 'decision:0018', '3.2', 'agent:product-manager', 'commitment',
               _owner_subject('accept-design')),
    # decision 0018 point 3.3: the product manager promotes a manifest whose every entry lies inside an envelope
    # the Owner granted, "bound to the manifest digest and naming the envelope". The engineering manager, which
    # dispatches with the manifest, never promotes one.
    Delegation('promote-manifest', 'decision:0018', '3.3', 'agent:product-manager', 'envelope',
               _owner_subject('promote-manifest')),
    # decision 0018 point 3 (S-03.5): the engineering manager selects the exact model identifiers inside the
    # model-access envelope the Owner authorized (a confirmed provider-envelope receipt). The product manager
    # never selects them.
    Delegation('select-models', 'decision:0018', '3', 'agent:engineering-manager', 'envelope-receipt',
               selection_subject_problems),
)}


def check_delegation(kind, decided_by, basis):
    """The table row for KIND when DECIDED_BY may decide it on BASIS; DelegationRefused otherwise
    (``DELEGATION_KIND_UNKNOWN``, ``DECIDER_NOT_DELEGATED``, ``DELEGATION_BASIS_INVALID``). Reads nothing."""
    row = DELEGATIONS.get(kind) if isinstance(kind, str) else None
    if row is None:
        raise DelegationRefused('DELEGATION_KIND_UNKNOWN', f'no accepted record delegates {kind!r} '
                                f'(the table delegates {", ".join(sorted(DELEGATIONS))})')
    if decided_by != row.decider:
        raise DelegationRefused('DECIDER_NOT_DELEGATED', f'{row.record} point {row.point} delegates {kind} to '
                                f'{row.decider}, not {decided_by!r}')
    problems = BASIS_TYPES[row.basis_type].problems(basis)
    if problems:
        raise DelegationRefused('DELEGATION_BASIS_INVALID', '; '.join(problems))
    return row


# ---------------------------------------------------------------------------- the delegating record


def record_status(text):
    """The delegating record's ``Status:`` line (its first), or None."""
    for line in text.splitlines():
        if line.startswith(STATUS_PREFIX):
            return line.rstrip()
    return None


def accepted_by_owner(text):
    """Whether a decision record's text is accepted by the Owner: its first ``Status:`` line begins exactly
    ``Status: Accepted (Owner) -`` (decision 0018's own line does; ``Status: Accepted (Owner), superseded ...``,
    ``Status: Accepted (Owner)`` alone or ``Status: Accepted (Overseer) ...`` do not)."""
    status = record_status(text)
    return status is not None and status.startswith(ACCEPTED_BY_OWNER)


def _repository_access():
    """The shared repository-access module, under the name the planning adapter loads it with."""
    return _load('repository_access', REPO / 'integrations' / 'repository' / 'repository_access.py')


def read_harness(harness, record):
    """A ``HarnessView`` of RECORD (``decision:NNNN``) and the log at the ``HEAD`` commit of the harness
    repository HARNESS (its work tree's root), read through the repository-access module with the
    repository's own configuration only; the upward search stops at HARNESS. AUTHORITY_UNAVAILABLE when the
    repository cannot be read; DELEGATION_NOT_ACCEPTED when the record is not there (or not once)."""
    match = RECORD.match(record) if isinstance(record, str) else None
    if match is None:
        raise ValueError(f'{record!r} is not decision:NNNN')
    ra = _repository_access()
    harness = Path(harness)
    failure = None
    try:
        with ra.open_repository(harness, config='repository', ceilings=[str(harness.parent)]) as repo:
            head = repo.head()
            if head.commit is None:
                raise DelegationRefused('AUTHORITY_UNAVAILABLE', f'the harness repository {harness} has no commit '
                                        'at HEAD')
            pattern = re.compile(rf'^{DECISIONS_DIR}/{match.group(1)}-[^/]+\.md$')
            found = [path for path in repo.files(head.commit, DECISIONS_DIR) if pattern.match(path)]
            if len(found) != 1:
                raise DelegationRefused('DELEGATION_NOT_ACCEPTED', f'{record} is {len(found)} files under '
                                        f'{DECISIONS_DIR}/ at {head.commit}, not one')
            blob = repo.blob(head.commit, found[0])
            log = repo.blob(head.commit, LOG) if repo.object_kind(f'{head.commit}:{LOG}') == 'blob' else None
    except (ra.CannotRun, ra.RepositoryError) as exc:
        failure = exc
    if failure is not None:
        raise DelegationRefused('AUTHORITY_UNAVAILABLE', f'the harness repository {harness}: {failure}')
    try:
        text = blob.decode('utf-8')
        log_text = None if log is None else log.decode('utf-8')
    except UnicodeDecodeError:
        raise DelegationRefused('AUTHORITY_UNAVAILABLE', f'{found[0]} or {LOG} at {head.commit} is not UTF-8') \
            from None
    return HarnessView(head.commit, found[0], text, 'sha256:' + hashlib.sha256(blob).hexdigest(), log_text)


class Authority(NamedTuple):
    """The delegation as read at the act: the row, the harness commit and the record's blob digest."""
    row: Delegation
    revision: str
    digest: str
    basis: dict


def read_authority(harness, kind, decided_by, basis, *, store=None):
    """The authority for a delegated decision of KIND by DECIDED_BY on BASIS: ``check_delegation``, then the
    delegating record and the basis at the harness repository's ``HEAD`` (``read_harness``), and, for a basis
    type that needs it, the integration store STORE (none: ``AUTHORITY_UNAVAILABLE``).
    DelegationRefused (``DELEGATION_NOT_ACCEPTED``, ``AUTHORITY_UNAVAILABLE``,
    ``DELEGATION_BASIS_NOT_RECORDED``, ``DELEGATION_BASIS_NOT_AUTHORITY``, or a code of ``check_delegation``)."""
    row = check_delegation(kind, decided_by, basis)
    view = read_harness(harness, row.record)
    if not accepted_by_owner(view.record_text):
        raise DelegationRefused('DELEGATION_NOT_ACCEPTED', f'{view.record_path} at {view.revision} is '
                                f'{record_status(view.record_text)!r}, not "{ACCEPTED_BY_OWNER} ..."')
    basis_type = BASIS_TYPES[row.basis_type]
    refusal = basis_type.unrecorded(basis, view, store) if basis_type.needs_store \
        else basis_type.unrecorded(basis, view)
    if refusal is not None:
        raise DelegationRefused(*refusal)
    return Authority(row, view.revision, view.record_digest, {name: basis[name] for name in basis})


def decide(authority, subject, *, recorded_at, decision_id=None):
    """The delegated decision record of AUTHORITY's kind on SUBJECT (``read_authority``'s answer), recorded
    at RECORDED_AT (``YYYY-MM-DDTHH:MM:SSZ``). ValueError when it is not a well-formed record (the caller
    validates the subject first)."""
    row = authority.row
    record = {'format': FORMAT, 'decisionId': decision_id or str(uuid.uuid4()), 'kind': row.kind,
              'subject': subject,
              'delegation': {'record': row.record, 'point': row.point, 'revision': authority.revision,
                             'digest': authority.digest, 'basis': authority.basis},
              'decidedBy': row.decider, 'recordedBy': row.decider, 'recordedAt': recorded_at}
    problems = check_record(record)
    if problems:
        raise ValueError(f'the delegated decision record is malformed: {problems[0]}')
    return record


# ---------------------------------------------------------------------------- the record


def check_record(record):
    """The problems of RECORD as a delegated decision record (an empty list when it has the shape)."""
    if not isinstance(record, dict):
        return ['the record must be an object']
    problems = []
    if list(record) != list(FIELDS):
        problems.append(f'the fields must be exactly {", ".join(FIELDS)}, in that order')
    if record.get('format') != FORMAT:
        problems.append(f'format must be {FORMAT}')
    if not isinstance(record.get('decisionId'), str) or not D.UUID4.match(record['decisionId']):
        problems.append('decisionId must be a lower-case version 4 UUID')
    kind = record.get('kind')
    row = DELEGATIONS.get(kind) if isinstance(kind, str) else None
    if row is None:
        problems.append(f'kind must be a delegated kind: {", ".join(sorted(DELEGATIONS))}')
    else:
        problems.extend(row.subject_problems(record.get('subject')))
    delegation = record.get('delegation')
    if not isinstance(delegation, dict) or list(delegation) != list(DELEGATION_FIELDS):
        problems.append(f'delegation must have exactly {", ".join(DELEGATION_FIELDS)}')
    elif row is not None:
        if delegation['record'] != row.record or delegation['point'] != row.point:
            problems.append(f'delegation must name {row.record} point {row.point}, the row of {kind}')
        if not isinstance(delegation['revision'], str) or not D.FULL_COMMIT.match(delegation['revision']):
            problems.append('delegation.revision must be a full commit id')
        if not isinstance(delegation['digest'], str) or not D.DIGEST.match(delegation['digest']):
            problems.append('delegation.digest must be sha256:<64 hex digits>')
        problems.extend(f'delegation.basis: {p}' for p in BASIS_TYPES[row.basis_type].problems(delegation['basis']))
    if row is not None and record.get('decidedBy') != row.decider:
        problems.append(f'decidedBy must be {row.decider}, the decider of {kind}')
    if record.get('recordedBy') != record.get('decidedBy'):
        problems.append('recordedBy must equal decidedBy: a delegated decision is recorded by the lead that made it')
    if not isinstance(record.get('recordedAt'), str) or not D.TIMESTAMP.match(record['recordedAt']):
        problems.append('recordedAt must be YYYY-MM-DDTHH:MM:SSZ')
    return problems


def dumps(record):
    """The record's file text, as ``owner_decision.dumps`` writes an Owner record."""
    return D.dumps(record)
