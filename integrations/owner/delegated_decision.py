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
tree; decision 0014), has a ``Status:`` line beginning ``Accepted (Owner)``; and the basis is recorded
there (for a log quote, present verbatim in ``evidence/bootstrap-log.md`` at that commit). Who ran the
command, that the decision lies inside the commitment's scope or the envelope, and the authorship of a log
quote are not checked: decision 0018 point 7 ("a log quote is checked for presence, not authorship").

The record format and the table are standard library only and open no file; ``read_authority`` alone
loads the repository-access module (Dulwich, from the Python tools set), when it is called.
"""
import hashlib
import importlib.util
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
ACCEPTED_BY_OWNER = 'Status: Accepted (Owner)'
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
    says why it is not recorded at the harness's ``HEAD`` (a ``HarnessView``), or None when it is."""
    name: str
    problems: Callable[[object], list]
    unrecorded: Callable[[dict, HarnessView], str | None]


QUOTE_FIELDS = ('type', 'link', 'quote')


def _quote_problems(name, mark=None):
    """A log quote ``{type, link, quote}``, the shape of the network matrix's ``owner_approval``
    (tools/check_network_matrix.py): the link is the log, the quote verbatim and at least 12 characters."""
    def problems(basis):
        if not isinstance(basis, dict) or list(basis) != list(QUOTE_FIELDS):
            return [f'the basis must be exactly {{{", ".join(QUOTE_FIELDS)}}}']
        out = []
        if basis['type'] != name:
            out.append(f'the basis type must be {name}')
        if basis['link'] != LOG:
            out.append(f'the basis link must be {LOG}')
        quote = basis['quote']
        if not isinstance(quote, str) or len(quote.strip()) < QUOTE_MIN:
            out.append(f'the basis quote must be the text recorded in {LOG}, verbatim, at least {QUOTE_MIN} '
                       'characters')
        elif mark is not None and mark not in quote:
            out.append(f'the basis quote of a {name} must contain {mark!r}')
        return out
    return problems


def _quote_unrecorded(basis, view):
    if view.log_text is None:
        return f'{LOG} is not in the harness repository at {view.revision}'
    if basis['quote'] not in view.log_text:
        return f'the quote is not in {LOG} at {view.revision} (the committed log, not the work tree)'
    return None


BASIS_TYPES = {
    # decision 0018 point 3.2: the log's "Commitment: <milestone>" entry whose scope the design lies in.
    'commitment': BasisType('commitment', _quote_problems('commitment', COMMITMENT_MARK), _quote_unrecorded),
    # decision 0018 point 3.3: the Owner's standing authorization (point 5), verbatim in the log.
    'envelope': BasisType('envelope', _quote_problems('envelope'), _quote_unrecorded),
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
    """Whether a decision record's text is accepted by the Owner: its ``Status:`` line begins
    ``Status: Accepted (Owner)``."""
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


def read_authority(harness, kind, decided_by, basis):
    """The authority for a delegated decision of KIND by DECIDED_BY on BASIS: ``check_delegation``, then the
    delegating record and the basis at the harness repository's ``HEAD`` (``read_harness``).
    DelegationRefused (``DELEGATION_NOT_ACCEPTED``, ``AUTHORITY_UNAVAILABLE``,
    ``DELEGATION_BASIS_NOT_RECORDED``, or a code of ``check_delegation``)."""
    row = check_delegation(kind, decided_by, basis)
    view = read_harness(harness, row.record)
    if not accepted_by_owner(view.record_text):
        raise DelegationRefused('DELEGATION_NOT_ACCEPTED', f'{view.record_path} at {view.revision} is '
                                f'{record_status(view.record_text)!r}, not "{ACCEPTED_BY_OWNER} ..."')
    reason = BASIS_TYPES[row.basis_type].unrecorded(basis, view)
    if reason is not None:
        raise DelegationRefused('DELEGATION_BASIS_NOT_RECORDED', reason)
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
