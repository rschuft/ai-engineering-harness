"""The acceptance recorder (plan leaf P-04.1; decision 0008).

A deterministic, non-model recorder of the Owner's acceptance of an Objective item of an
intent-driven OpenSpec change. In two steps, as the Owner sees them:

1. ``prepare`` reads the change at the project repository's HEAD and returns a **challenge**: the
   summary to show the Owner (the objective, the acceptance criteria that cite it, its current
   authority and outcome), a nonce and an expiry, bound to that revision and to the sha256 of the
   change's ``proposal.md``. It writes nothing.
2. ``record`` takes that challenge and the Owner's **statement** (the text verbatim, attributed to
   ``owner``, the channel and the reference where it is kept). It refuses, each with a stable code
   and its remedy (``REMEDIES``), unless the statement is the Owner's, the challenge is the one
   ``prepare`` gives for that revision, unexpired, unconsumed and still current, and the item is in
   the state the request needs. It then, in one commit made in process (decision 0014 sections 6
   and 8; no hook, no process):

   - writes the Owner decision record (``owner_decision.py``, kind ``accept-objective``) at
     ``openspec/changes/<change>/owner-decisions/<decisionId>.json``;
   - sets the item's ``authority: accepted`` and ``acceptance: <the statement's reference>`` in
     the change's ``proposal.md`` (intent-record/v1);
   - mints the outcome id (a random UUID, version 4) and declares it under ``x-outcomes`` in the
     change's ``.openspec.yaml`` as ``{item, acceptance}`` (decision 0008, point 4); re-recording
     (``--amend``: a new acceptance of an accepted objective, decision 0008 point 5) keeps the id
     and updates the acceptance in both places;
   - before the branch moves, resolves ``outcome:<id>@<new commit>`` through the lineage objective
     resolver (``integrations/lineage/lineage_resolve.py``), which must answer resolved with the
     declared item and acceptance; otherwise nothing visible changes (``RESOLUTION_FAILED``).

The outcome id is minted only here, only when an acceptance reference exists, and never again for
the same item (decision 0008, point 2): an item that already has one is refused
(``OUTCOME_ALREADY_MINTED``) unless the request is an amendment, which keeps it.

**The recorded-statement path** (plan leaf E-05.12; decision 0018 points 4.3 and 7):
``record_from_log`` records the Owner's acceptance of an objective from his statement already recorded
verbatim, dated and anchored in the Decisions of the harness log (``evidence/bootstrap-log.md``),
without a challenge. The statement's reference is ``harness:evidence/bootstrap-log.md#<anchor>``. The
recorder reads the log at the harness repository's ``HEAD`` commit, which must be on ``refs/heads/main``,
through the repository-access module (the committed blob, never the work tree; decision 0014) and admits
the statement only when the anchor names a Decisions entry (``delegated_decision.decisions_entry``, the
P-04.3 pattern) whose title is dated and begins, after its date, with ``Owner `` and whose Owner block
(``owner_block``: the entry's first contiguous run of ``>`` lines, outside code fences) holds the
statement's text wholly, by this rule (``verbatim_admits``): the statement's words, each of its lines
read without a leading ``>`` quote marker and the text split on any whitespace (line breaks included),
are a contiguous run of the block's words, compared exactly (case and punctuation kept). The statement
must also be at least 12 characters and name the change or the project repository (its ``origin``
basename, else its directory's) as a whole token of at least 3 characters (``names``), and must not be
the request itself, by reference or by text. The commit is the one ``record`` makes; the decision record
has ``recorded`` (the entry, its date, the harness revision and its network ``origin``, the log's digest, the name the statement names and ``challengeShown:
false``) in place of ``shown`` (``owner_decision.py``) and its commit message says that no challenge was
shown.

Usage (from the repository root, under the tools interpreter: Dulwich is required):

    <tools python> -I -B integrations/owner/acceptance_recorder.py prepare --project DIR \\
        --change NAME --item O<n> [--expires-in-minutes N] [--out FILE]
    <tools python> -I -B integrations/owner/acceptance_recorder.py record --project DIR \\
        --challenge FILE --statement FILE --recorded-by ATTRIBUTION --identity "Name <email>" [--amend]
    <tools python> -I -B integrations/owner/acceptance_recorder.py record-from-log --project DIR \\
        --change NAME --item O<n> --statement FILE --recorded-by ATTRIBUTION --identity "Name <email>" \\
        [--harness DIR] [--amend]

Exit status: 0 done (JSON on standard output), 2 refused (the code and its remedy on standard
error).
"""
import argparse
import datetime
import hashlib
import json
import re
import secrets
import sys
import urllib.parse
import uuid
from pathlib import Path
from typing import NamedTuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load(name, path):
    import importlib.util
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


D = _load('owner_decision', HERE / 'owner_decision.py')
R = _load('lineage_resolve', REPO / 'integrations' / 'lineage' / 'lineage_resolve.py')
L = R.L
ra = R.planning.repository_access
G = _load('delegated_decision', HERE / 'delegated_decision.py')  # the log's anchored Decisions entries (P-04.3)

KIND = 'accept-objective'
CHALLENGE_FORMAT = 'owner-decision-challenge/v1'
CHALLENGE_SUBJECT = ('change', 'item', 'revision', 'proposal')
RECORDER = 'acceptance-recorder/1'
DECISIONS_DIR = 'owner-decisions'
CONFIG_POLICY = 'repository'  # the project's own configuration only (decision 0014 section 5)
DEFAULT_EXPIRY_MINUTES = 60
MAX_EXPIRY_MINUTES = 7 * 24 * 60
LOG_REFERENCE = f'harness:{G.LOG}#'  # + <anchor>: the statement's reference on the recorded-statement path
OWNER_TITLE = 'Owner '  # an Owner entry's dated title begins so, after '<date>: '
HARNESS_BRANCH = 'refs/heads/main'  # the harness's HEAD must be this symbolic reference
OPENS_FENCE = re.compile(r'^\s*(?:```|~~~)')
SCP_LIKE = re.compile(r'^[^/@:]+@(?P<rest>[^/:]+:.*)$')
ORIGIN_SCHEMES = ('https', 'http', 'ssh', 'git')  # an origin the record keeps (recordable_origin)
NAME_CHAR = '[A-Za-z0-9_.-]'  # a name's characters: a whole-token match is bounded by anything else
NAME_MIN = 3  # a shorter change or repository name never names the statement's subject

REMEDIES = {
    'PROJECT_UNAVAILABLE': 'name the work tree of the project repository, with a commit on a branch, and run '
                           'under the tools interpreter (task tools:install)',
    'GIT_FAILED': 'repair the project repository (git fsck), then prepare again',
    'CHANGE_MISSING': 'name an active change under openspec/changes/ that has proposal.md and .openspec.yaml',
    'ITEM_NOT_OBJECTIVE': 'name an Objective item (O<n>) of the change\'s intent record',
    'INTENT_RECORD_INVALID': 'make the proposal a valid intent-record/v1 record (tools/check_intent_record.py), '
                             'commit it, then prepare again',
    'OUTCOME_METADATA_INVALID': 'make the change\'s x-outcomes block the decision-0008 form, with at most one '
                                'id per item, then prepare again',
    'CHALLENGE_MISSING': 'run prepare, show its summary to the Owner, and pass the challenge it printed',
    'CHALLENGE_INVALID': 'pass the challenge exactly as prepare printed it for this project',
    'CHALLENGE_EXPIRED': 'run prepare again and show the new summary to the Owner',
    'CHALLENGE_STALE': 'the proposal changed after the summary was shown: run prepare again and show the new '
                       'summary to the Owner',
    'CHALLENGE_CONSUMED': 'a decision was already recorded on this challenge: read it from the change\'s '
                          'owner-decisions/, or prepare a new one',
    'ACCEPTANCE_MISSING': 'record only an Owner statement that exists: its text verbatim and the reference '
                          'where it is kept',
    'ACCEPTANCE_MODEL_AUTHORED': 'a model cannot accept: obtain the Owner\'s own statement',
    'STATEMENT_NOT_OWNER': 'only the Owner accepts an objective: record a statement attributed to owner',
    'STATEMENT_INVALID': 'give the statement as {text, attributedTo, channel, reference}, the channel a '
                         'lower-case token and the reference a scheme:reference',
    'ACCEPTANCE_REFERENCE_INVALID': 'reference the Owner\'s message (conversation:<thread>/<message>) or an '
                                    'accepted decision record (decision:<id>), not the request itself',
    'ACCEPTANCE_ALREADY_RECORDED': 'this acceptance is already recorded; the outcome id stands',
    'OUTCOME_ALREADY_MINTED': 'the item already has its outcome id: to record a new Owner acceptance of it, '
                              'rerun with --amend, which keeps the id',
    'OUTCOME_NOT_MINTED': 'the item has no outcome id yet: record its first acceptance without --amend',
    'RECORDED_BY_INVALID': 'name who runs the recorder as owner, agent:<id> or person:<id>',
    'IDENTITY_INVALID': 'give the commit identity as "Name <email>"',
    'RESOLUTION_FAILED': 'nothing was committed: report it; the recorder and the lineage resolver disagree',
    'HOOKS_UNSUPPORTED': 'the recorder commits without hooks and refuses a repository that has them: record '
                         'by hand in the decision-0008 form, or in a repository without client hooks',
    'COMMIT_REFUSED': 'clean, commit or move aside the change\'s files, check out its branch, then prepare again',
    'OBJECT_NAME_INVALID': 'name the change and the item as the intent record and OpenSpec write them',
    # The recorded-statement path (plan leaf E-05.12).
    'STATEMENT_REFERENCE_NOT_LOG': 'reference the Owner\'s statement as the anchored Decisions entry of the harness '
                                   'log that records it: harness:evidence/bootstrap-log.md#<anchor>',
    'HARNESS_UNAVAILABLE': 'name the work tree of the harness repository (--harness) and run under the tools '
                           'interpreter (task tools:install)',
    'STATEMENT_LOG_NOT_COMMITTED': 'commit evidence/bootstrap-log.md in the harness repository, then record again: '
                                   'the recorder reads the log at the harness\'s HEAD commit, never the work tree',
    'STATEMENT_ANCHOR_ABSENT': 'reference an anchored entry of the log\'s Decisions section that is committed at the '
                               'harness\'s HEAD',
    'STATEMENT_ENTRY_UNDATED': 'reference a Decisions entry whose bold title begins with its date, "YYYY-MM-DD: "',
    'STATEMENT_OUTSIDE_VERBATIM': 'give the statement\'s text as the entry\'s verbatim Owner block (its "> " lines) '
                                  'records it: the Owner\'s words, not a reading of them',
    'ACCEPTANCE_IS_REQUEST': 'the acceptance must be a separate statement: reference the entry where the Owner '
                             'accepted, not the source of an Original Quote, and not its text '
                             '(intent-record/v1 invariant 4)',
    'STATEMENT_ENTRY_NOT_OWNER': 'reference an entry that records the Owner\'s own words: its dated title begins '
                                 '"YYYY-MM-DD: Owner " (an Owner direction, decision or authorization)',
    'STATEMENT_NOT_ABOUT_CHANGE': 'record a statement of at least 12 characters that names the change or the '
                                  'project repository it accepts',
    'HARNESS_NOT_ON_MAIN': 'check out main in the harness repository (HEAD the symbolic reference '
                           'refs/heads/main), then record again',
}


class RecorderError(Exception):
    """A refusal with a stable code and its remedy; nothing was committed (``GIT_FAILED`` with
    ``details['committed']`` excepted, see ``repository_access.Repository.write_commit``)."""

    def __init__(self, code, detail, **details):
        self.code, self.detail, self.remedy, self.details = code, detail, REMEDIES[code], details
        super().__init__(f'{code}: {detail}. Remedy: {self.remedy}.')


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def timestamp(moment):
    return moment.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_timestamp(text):
    if not isinstance(text, str) or not D.TIMESTAMP.match(text):
        return None
    try:
        return datetime.datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def _paths(change):
    base = f'openspec/changes/{change}'
    return base, f'{base}/proposal.md', f'{base}/.openspec.yaml'


def _check_names(change, item):
    if not isinstance(change, str) or not D.CHANGE.match(change) or change == 'archive':
        raise RecorderError('OBJECT_NAME_INVALID', f'{change!r} is not an active OpenSpec change name')
    if not isinstance(item, str) or not D.OBJECTIVE_ITEM.match(item):
        raise RecorderError('ITEM_NOT_OBJECTIVE', f'{item!r} is not an Objective item id (O<n>)')


def _open(project):
    failure = None
    try:
        return ra.open_repository(project, config=CONFIG_POLICY)
    except (ra.CannotRun, ra.RepositoryError) as exc:
        failure = str(exc)
    raise RecorderError('PROJECT_UNAVAILABLE', failure)


def _read(repo, commit, path):
    """The bytes of PATH at COMMIT, or None when it is not a blob there."""
    if repo.object_kind(f'{commit}:{path}') != 'blob':
        return None
    return repo.blob(commit, path)


class _Change:
    """One change at one commit: its proposal (parsed), its x-outcomes and the item."""

    def __init__(self, repo, commit, change, item):
        base, proposal_path, meta_path = _paths(change)
        self.change, self.item_id, self.commit = change, item, commit
        self.base, self.proposal_path, self.meta_path = base, proposal_path, meta_path
        self.proposal = _read(repo, commit, proposal_path)
        self.meta = _read(repo, commit, meta_path)
        if self.proposal is None or self.meta is None:
            raise RecorderError('CHANGE_MISSING', f'{base} has no proposal.md and .openspec.yaml at {commit}')
        self.digest = hashlib.sha256(self.proposal).hexdigest()
        intent = R._intent_module()
        try:
            self.record, _ = intent._Parser(self.proposal).parse()
        except UnicodeDecodeError:
            raise RecorderError('INTENT_RECORD_INVALID', f'{proposal_path} is not UTF-8') from None
        problems = _record_problems(self.proposal)
        if problems:
            raise RecorderError('INTENT_RECORD_INVALID', f'{proposal_path} at {commit}: ' + '; '.join(problems[:3]))
        self.item = self.record.items.get(item)
        if self.item is None or self.item.section != 'Objective':
            raise RecorderError('ITEM_NOT_OBJECTIVE', f'{proposal_path} has no Objective item {item}')
        try:
            self.outcomes = R.read_x_outcomes(self.meta)
        except R.OutcomeMetadataInvalid as exc:
            raise RecorderError('OUTCOME_METADATA_INVALID', f'{meta_path} at {commit}: {exc}') from None
        declared = sorted(oid for oid, entry in self.outcomes.items() if entry['item'] == item)
        if len(declared) > 1:
            raise RecorderError('OUTCOME_METADATA_INVALID', f'{meta_path} declares {item} {len(declared)} times: '
                                + ', '.join(declared))
        self.outcome = declared[0] if declared else None

    def summary(self):
        """The text shown to the Owner: a function of the change at this commit only."""
        intent = R._intent_module()
        f = self.item.fields
        lines = [f'Owner decision: accept an objective ({KIND}).',
                 f'Change: {self.base} at {self.commit}',
                 f'Objective {self.item_id}: {f.get("statement")}',
                 f'Attributed to: {f.get("attributed_to")}; source: {f.get("source")}',
                 f'Current authority: {f.get("authority")}'
                 + (f'; acceptance: {f["acceptance"]}' if 'acceptance' in f else '')]
        if self.outcome is None:
            lines.append('Outcome: none yet; recording this acceptance mints its id.')
        else:
            lines.append(f'Outcome: {self.outcome}; recording a new acceptance keeps this id.')
        lines.append(f'Acceptance criteria citing {self.item_id}:')
        cited = [ac for ac in self.record.sections.get('Acceptance Criteria', [])
                 if self.item_id in intent._split_list(ac.fields.get('source', ''))]
        lines.extend(f'- {ac.id} ({ac.fields.get("authority")}): {ac.fields.get("statement")}' for ac in cited)
        if not cited:
            lines.append('- none')
        lines.append(f'Proposal sha256: {self.digest}')
        return '\n'.join(lines)


def _record_problems(proposal):
    """The intent-record/v1 problems of PROPOSAL that the recorder can decide: every check but
    the quotes' sources, which need the statement store (``source-unavailable``)."""
    intent = R._intent_module()
    return [str(p) for p in intent.check(proposal, {}) if p.code != 'source-unavailable']


def prepare(project, change, item, *, now=None, expires_in_minutes=DEFAULT_EXPIRY_MINUTES, nonce=None):
    """The challenge for accepting ITEM of CHANGE at the project's HEAD. Writes nothing."""
    _check_names(change, item)
    if not isinstance(expires_in_minutes, int) or not 1 <= expires_in_minutes <= MAX_EXPIRY_MINUTES:
        raise ValueError(f'expires_in_minutes must be 1 to {MAX_EXPIRY_MINUTES}')
    now = now or utc_now()
    with _open(project) as repo:
        head = repo.head()
        if head.commit is None:
            raise RecorderError('PROJECT_UNAVAILABLE', 'the project repository has no commit at HEAD')
        state = _guarded(_Change, repo, head.commit, change, item)
        summary = state.summary()
    return {'format': CHALLENGE_FORMAT, 'kind': KIND,
            'subject': {'change': change, 'item': item, 'revision': head.commit, 'proposal': state.digest},
            'shown': {'summary': summary, 'nonce': nonce or secrets.token_hex(16),
                      'expiresAt': timestamp(now + datetime.timedelta(minutes=expires_in_minutes))}}


def _guarded(call, *args):
    """CALL(*ARGS) with the repository module's read failures as GIT_FAILED refusals."""
    failure = None
    try:
        return call(*args)
    except ra.RepositoryError as exc:
        failure = exc
    raise RecorderError('GIT_FAILED', str(failure))


def _check_owner(statement):
    """The statement as an Owner's decision (``owner_decision.statement_verdict``), or its refusal."""
    verdict, detail = D.statement_verdict(statement)
    code = {D.MISSING: 'ACCEPTANCE_MISSING', D.MODEL: 'ACCEPTANCE_MODEL_AUTHORED', D.NOT_OWNER: 'STATEMENT_NOT_OWNER',
            D.INVALID: 'STATEMENT_INVALID'}.get(verdict)
    if code is not None:
        raise RecorderError(code, detail)


def _check_statement(statement):
    _check_owner(statement)
    reference = statement['reference']
    if reference.startswith('decision:'):
        return
    try:
        parsed = L.parse(reference)
    except L.MalformedReference as exc:
        raise RecorderError('ACCEPTANCE_REFERENCE_INVALID', f'{reference}: {exc}') from None
    if not isinstance(parsed, L.MessageRef):
        raise RecorderError('ACCEPTANCE_REFERENCE_INVALID', f'{reference} is a {parsed.kind} reference, not an '
                            'Owner message or an accepted decision record')


def _check_challenge(challenge):
    if challenge is None:
        raise RecorderError('CHALLENGE_MISSING', 'no challenge was given')
    if (not isinstance(challenge, dict) or list(challenge) != ['format', 'kind', 'subject', 'shown']
            or challenge['format'] != CHALLENGE_FORMAT or challenge['kind'] != KIND):
        raise RecorderError('CHALLENGE_INVALID', f'not a {CHALLENGE_FORMAT} challenge of kind {KIND}')
    subject, shown = challenge['subject'], challenge['shown']
    if not isinstance(subject, dict) or list(subject) != list(CHALLENGE_SUBJECT):
        raise RecorderError('CHALLENGE_INVALID', f'its subject must have exactly {", ".join(CHALLENGE_SUBJECT)}')
    if not isinstance(shown, dict) or list(shown) != list(D.SHOWN_FIELDS):
        raise RecorderError('CHALLENGE_INVALID', f'its shown block must have exactly {", ".join(D.SHOWN_FIELDS)}')
    try:
        _check_names(subject['change'], subject['item'])
    except RecorderError as exc:
        raise RecorderError('CHALLENGE_INVALID', exc.detail) from None
    if not isinstance(subject['revision'], str) or not D.COMMIT.match(subject['revision']):
        raise RecorderError('CHALLENGE_INVALID', 'its revision must be a full commit id')
    if not isinstance(subject['proposal'], str) or not D.SHA256.match(subject['proposal']):
        raise RecorderError('CHALLENGE_INVALID', 'its proposal digest must be a sha256')
    if not isinstance(shown['nonce'], str) or not D.NONCE.match(shown['nonce']):
        raise RecorderError('CHALLENGE_INVALID', 'its nonce must be 32 lower-case hex digits')
    if not isinstance(shown['summary'], str) or _parse_timestamp(shown['expiresAt']) is None:
        raise RecorderError('CHALLENGE_INVALID', 'its summary must be text and its expiry YYYY-MM-DDTHH:MM:SSZ')


def _recorded_decisions(repo, commit, base):
    """The decision records already committed in the change at COMMIT."""
    out = []
    for path in repo.files(commit, f'{base}/{DECISIONS_DIR}'):
        try:
            record = json.loads(repo.blob(commit, path).decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise RecorderError('OUTCOME_METADATA_INVALID', f'{path} at {commit} is not a JSON decision record') \
                from None
        problems = D.check_record(record)
        if problems:
            raise RecorderError('OUTCOME_METADATA_INVALID', f'{path} at {commit}: {problems[0]}')
        out.append(record)
    return out


def record(project, challenge, statement, *, recorded_by, identity, amend=False, now=None,
           new_outcome=None, new_decision_id=None):
    """Record the Owner's acceptance STATEMENT on CHALLENGE (``prepare``'s) in the project
    repository and commit it. Returns ``{decision, outcome, minted, commit, path, reference}``.
    NEW_OUTCOME and NEW_DECISION_ID (callables) stand in for the random UUIDs in tests."""
    _check_statement(statement)
    if not isinstance(recorded_by, str) or not D.ATTRIBUTION.match(recorded_by):
        raise RecorderError('RECORDED_BY_INVALID', f'{recorded_by!r} is not owner, agent:<id> or person:<id>')
    if not isinstance(identity, str) or not ra.IDENTITY.fullmatch(identity):
        raise RecorderError('IDENTITY_INVALID', f'{identity!r} is not "Name <email>"')
    _check_challenge(challenge)
    now = now or utc_now()
    subject, shown = challenge['subject'], challenge['shown']
    if now >= _parse_timestamp(shown['expiresAt']):
        raise RecorderError('CHALLENGE_EXPIRED', f'the challenge expired at {shown["expiresAt"]}')
    change, item = subject['change'], subject['item']
    reference = statement['reference']
    with _open(project) as repo:
        head = repo.head()
        if head.commit is None:
            raise RecorderError('PROJECT_UNAVAILABLE', 'the project repository has no commit at HEAD')
        if _guarded(repo.commit, subject['revision']) != subject['revision']:
            raise RecorderError('CHALLENGE_INVALID', f'the project has no commit {subject["revision"]}')
        shown_state = _guarded(_Change, repo, subject['revision'], change, item)
        if shown_state.digest != subject['proposal'] or shown_state.summary() != shown['summary']:
            raise RecorderError('CHALLENGE_INVALID', 'its summary or proposal digest is not what prepare shows for '
                                f'{change} at {subject["revision"]}')
        state = _guarded(_Change, repo, head.commit, change, item)
        recorded = _guarded(_recorded_decisions, repo, head.commit, state.base)
        # A decision resting on a recorded statement (E-05.12) had no challenge, hence has no nonce.
        if any(r.get('shown', {}).get('nonce') == shown['nonce'] for r in recorded):
            raise RecorderError('CHALLENGE_CONSUMED', f'a decision on nonce {shown["nonce"]} is already recorded')
        if state.digest != subject['proposal']:
            raise RecorderError('CHALLENGE_STALE', f'{state.proposal_path} changed after the challenge was prepared')
        if reference in _quote_sources(state):
            raise RecorderError('ACCEPTANCE_REFERENCE_INVALID', f'{reference} is the request itself; the acceptance '
                                'must be a separate statement (intent-record/v1 invariant 4)')
        return _accept(repo, head, state, statement, ('shown', {name: shown[name] for name in D.SHOWN_FIELDS}),
                       revision=subject['revision'], proposal_digest=subject['proposal'], recorded_by=recorded_by,
                       identity=identity, amend=amend, now=now, new_outcome=new_outcome,
                       new_decision_id=new_decision_id)


def _quote_sources(state):
    """The sources of the change's Original Quotes: the request itself."""
    return {q.fields.get('source') for q in state.record.sections.get('Original Quote', [])}


def _accept(repo, head, state, statement, provenance, *, revision, proposal_digest, recorded_by, identity, amend,
            now, new_outcome, new_decision_id):
    """The commit of an acceptance of STATE's item on STATEMENT, whose PROVENANCE is ``('shown', <the challenge
    shown>)`` (``record``) or ``('recorded', <the log entry it rests on>)`` (``record_from_log``); REVISION and
    PROPOSAL_DIGEST are the subject's. Shared by both paths, after their own checks."""
    change, item, reference = state.change, state.item_id, statement['reference']
    current = state.item.fields.get('acceptance')
    if state.outcome is not None and not amend:
        raise RecorderError('OUTCOME_ALREADY_MINTED', f'{item} of {change} has outcome {state.outcome}')
    if state.outcome is None and amend:
        raise RecorderError('OUTCOME_NOT_MINTED', f'{item} of {change} has no outcome id to keep')
    if amend and current == reference:
        raise RecorderError('ACCEPTANCE_ALREADY_RECORDED', f'{item} of {change} is already accepted by {reference}')
    minted = state.outcome is None
    outcome = str((new_outcome or uuid.uuid4)()) if minted else state.outcome
    decision_id = str((new_decision_id or uuid.uuid4)())
    block, value = provenance
    decision = {
        'format': D.FORMAT, 'decisionId': decision_id, 'kind': KIND,
        'subject': {'change': change, 'item': item, 'outcome': outcome, 'revision': revision,
                    'proposal': proposal_digest},
        block: value,
        'statement': {name: statement[name] for name in D.STATEMENT_FIELDS},
        'recordedBy': recorded_by, 'recordedAt': timestamp(now)}
    problems = D.check_record(decision)
    if problems:  # the recorder's own invariant
        raise RecorderError('RESOLUTION_FAILED', f'the decision record is malformed: {problems[0]}')
    proposal = set_acceptance(state.proposal, item, reference)
    problems = _record_problems(proposal)
    if problems:
        raise RecorderError('INTENT_RECORD_INVALID', f'accepting {item} would leave {state.proposal_path} '
                            'invalid: ' + '; '.join(problems[:3]))
    meta = declare_outcome(state.meta, outcome, item, reference)
    expected = {**state.outcomes, outcome: {'item': item, 'acceptance': reference}}
    if R.read_x_outcomes(meta) != expected:
        raise RecorderError('RESOLUTION_FAILED', f'the x-outcomes block written for {state.meta_path} does not '
                            'read back as declared')
    path = f'{state.base}/{DECISIONS_DIR}/{decision_id}.json'
    files = {state.proposal_path: proposal, state.meta_path: meta, path: D.dumps(decision).encode('utf-8')}

    def verify(commit):
        answer = R.ObjectiveResolver(repo.root).resolve(L.parse(f'outcome:{outcome}@{commit}'))
        facts = answer.facts or {}
        if (not answer.resolved or facts.get('change') != state.base or facts.get('item') != item
                or facts.get('acceptance') != reference):
            raise RecorderError('RESOLUTION_FAILED', f'outcome:{outcome}@{commit} answers {answer.outcome} '
                                f'{answer.code or ""} {answer.detail}'.rstrip())

    message = commit_message(decision, minted, statement)
    failure = None
    try:
        commit = repo.write_commit(files, message, identity=identity, expected_head=head.commit,
                                   when=(int(now.timestamp()), 0), check=verify)
    except ra.RepositoryError as exc:
        failure = exc
    if failure is not None:
        code = failure.code if failure.code in REMEDIES else 'GIT_FAILED'
        raise RecorderError(code, failure.message, **failure.details)
    return {'decision': decision, 'outcome': outcome, 'minted': minted, 'commit': commit, 'path': path,
            'reference': f'outcome:{outcome}@{commit}'}


# ---------------------------------------------------------------------------- the recorded-statement path

class RecordedEntry(NamedTuple):
    """The Decisions entry a recorded statement rests on, as read at the harness repository's ``HEAD`` on
    ``refs/heads/main``: the entry (``delegated_decision.LogEntry``), the harness commit, the log blob's digest
    and the harness's ``origin`` URL without its userinfo (None when it has no ``origin``)."""
    entry: object
    revision: str
    digest: str
    origin: object = None


def statement_words(text):
    """The words of a statement's TEXT as the recorded-statement path compares them: each line read without a
    leading ``>`` quote marker (after optional whitespace, one space after it dropped), then the text split on
    any whitespace, line breaks included."""
    lines = (m.group('text') if (m := G.VERBATIM_LINE.match(line)) else line for line in text.splitlines())
    return [word for line in lines for word in line.split()]


def _within(words, block):
    """Whether WORDS is a non-empty contiguous run of BLOCK (both lists of words)."""
    count = len(words)
    return count > 0 and any(block[start:start + count] == words for start in range(len(block) - count + 1))


def owner_block(entry):
    """The Owner's verbatim block of ENTRY: its FIRST contiguous run of ``>`` lines after the title line (a blank
    ``>`` line inside it counts; any other line, a blank one included, ends it), outside any code fence (a line
    opening with three backticks or tildes opens or closes one), each line without its marker, joined by
    newlines. Empty when the entry has no such run. A later quote in the entry (a reading, a question quoted
    to the Owner) is never part of it."""
    run, fenced = [], False
    for line in entry.text.splitlines()[1:]:
        match = G.VERBATIM_LINE.match(line)
        if match is None and OPENS_FENCE.match(line):
            if run:
                break
            fenced = not fenced
            continue
        if fenced:
            continue
        if match is not None:
            run.append(match.group('text'))
        elif run:
            break
    return '\n'.join(run)


def verbatim_admits(entry, text):
    """Whether TEXT lies wholly inside ENTRY's Owner block (``owner_block``): its words (``statement_words``) are
    a contiguous run of the block's words (split on any whitespace), compared exactly."""
    return _within(statement_words(text), owner_block(entry).split())


def _log_anchor(reference):
    """The anchor of a recorded-statement reference ``harness:evidence/bootstrap-log.md#<anchor>``, or the
    refusal."""
    anchor = reference[len(LOG_REFERENCE):] if reference.startswith(LOG_REFERENCE) else None
    if anchor is None or not G.ANCHOR.match(anchor):
        raise RecorderError('STATEMENT_REFERENCE_NOT_LOG', f'{reference} is not {LOG_REFERENCE}<anchor>')
    return anchor


def origin_url(repo):
    """REPO's ``remote.origin.url`` from its own configuration (the policy it was opened with), or None.
    The repository-access module has no public reader of it; its configuration stack is read here."""
    try:
        value = repo._config().get((b'remote', b'origin'), b'url')
    except KeyError:
        return None
    text = value.decode('utf-8', 'replace').strip() if isinstance(value, bytes) else str(value).strip()
    return text or None


def without_userinfo(url):
    """URL without its userinfo: ``scheme://user:secret@host/path`` -> ``scheme://host/path``, and the scp-like
    ``user@host:path`` -> ``host:path``; any other text is returned as it is."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme and parts.netloc:
        return urllib.parse.urlunsplit(parts._replace(netloc=parts.netloc.rpartition('@')[2]))
    scp = SCP_LIKE.match(url)
    return scp.group('rest') if scp else url


def recordable_origin(url):
    """The harness's origin URL as the record keeps it, or None: only a URL with a network scheme
    (``ORIGIN_SCHEMES``: https, http, ssh, git) and a host, or the scp-like ``user@host:path``, each without its
    userinfo. A local filesystem path or a ``file://`` URL is never recorded: it would name a machine path."""
    if not url:
        return None
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() in ORIGIN_SCHEMES and parts.netloc.rpartition('@')[2]:
        return without_userinfo(url)
    if '://' not in url and SCP_LIKE.match(url):
        return without_userinfo(url)
    return None


def repository_name(url, root):
    """The project repository's name: the basename of its ``origin`` URL (URL), without ``.git``, or, when it
    has none (or an empty basename), the basename of its work tree ROOT."""
    if url:
        name = re.split(r'[/\\:]', url.rstrip('/\\'))[-1]
        name = name[:-len('.git')] if name.endswith('.git') else name
        if name:
            return name
    return Path(root).name


def read_log_entry(harness, anchor):
    """The Decisions entry ANCHOR of the log at the ``HEAD`` commit of the harness repository HARNESS (its work
    tree's root), read through the repository-access module with the repository's own configuration only (the
    upward search stops at HARNESS): the committed blob, never the work tree. ``HEAD`` must be the symbolic
    reference ``refs/heads/main``. Whether that commit is published is not checked: the recorder does not fetch.
    A ``RecordedEntry``, or the refusal: ``HARNESS_UNAVAILABLE``, ``HARNESS_NOT_ON_MAIN``,
    ``STATEMENT_LOG_NOT_COMMITTED``, ``STATEMENT_ANCHOR_ABSENT``, ``STATEMENT_ENTRY_UNDATED``,
    ``STATEMENT_ENTRY_NOT_OWNER``."""
    harness = Path(harness).absolute()
    failure = None
    try:
        with ra.open_repository(harness, config=CONFIG_POLICY, ceilings=[str(harness.parent)]) as repo:
            head = repo.head()
            if head.ref != HARNESS_BRANCH:
                raise RecorderError('HARNESS_NOT_ON_MAIN', f'the harness repository {harness} has HEAD on '
                                    f'{head.ref or "a detached commit"}, not {HARNESS_BRANCH}')
            commit = head.commit
            if commit is None:
                raise RecorderError('STATEMENT_LOG_NOT_COMMITTED', f'the harness repository {harness} has no commit at '
                                    'HEAD')
            if repo.object_kind(commit) != 'commit':
                raise RecorderError('HARNESS_UNAVAILABLE', f'the harness repository {harness}: {HARNESS_BRANCH} names '
                                    f'{commit}, which is not a commit there')
            blob = _read(repo, commit, G.LOG)
            origin = origin_url(repo)
    except (ra.CannotRun, ra.RepositoryError) as exc:
        failure = exc
    if failure is not None:
        raise RecorderError('HARNESS_UNAVAILABLE', f'the harness repository {harness}: {failure}')
    if blob is None:
        raise RecorderError('STATEMENT_LOG_NOT_COMMITTED', f'{G.LOG} is not committed at the harness\'s HEAD {commit}')
    try:
        text = blob.decode('utf-8')
    except UnicodeDecodeError:
        raise RecorderError('HARNESS_UNAVAILABLE', f'{G.LOG} at {commit} is not UTF-8') from None
    entry = G.decisions_entry(text, anchor)
    if entry is None:
        raise RecorderError('STATEMENT_ANCHOR_ABSENT', f'{G.LOG} at {commit} has no Decisions entry with the anchor '
                            f'{anchor!r} (the committed log, not the work tree)')
    if entry.date is None:
        raise RecorderError('STATEMENT_ENTRY_UNDATED', f'the entry {anchor!r} of {G.LOG} at {commit} has no '
                            '"<date>: " title')
    if not entry.title.startswith(OWNER_TITLE):
        raise RecorderError('STATEMENT_ENTRY_NOT_OWNER', f'the entry {anchor!r} is {entry.title[:80]!r}: its title, '
                            f'after its date, does not begin with {OWNER_TITLE!r}')
    return RecordedEntry(entry, commit, 'sha256:' + hashlib.sha256(blob).hexdigest(), recordable_origin(origin))


def names(text, name):
    """Whether TEXT names NAME as a whole token: NAME, at least ``NAME_MIN`` characters, bounded on each side by
    the text's start or end or a character outside ``[A-Za-z0-9_.-]`` (so ``aieh-d1-demo:`` names
    ``aieh-d1-demo``, and ``aieh-d1-demo-2`` or ``xaieh-d1-demo`` do not)."""
    if not isinstance(name, str) or len(name) < NAME_MIN:
        return False
    return re.search(rf'(?<!{NAME_CHAR}){re.escape(name)}(?!{NAME_CHAR})', text) is not None


def _about(words, change, name):
    """{name, as}: the name the statement names (the change's, else the project repository's), or the refusal."""
    text = ' '.join(words)
    if len(text) < G.QUOTE_MIN:
        raise RecorderError('STATEMENT_NOT_ABOUT_CHANGE', f'the statement is {len(text)} characters, fewer than '
                            f'{G.QUOTE_MIN}')
    for value, kind in ((change, 'change'), (name, 'repository')):
        if names(text, value):
            return {'name': value, 'as': kind}
    raise RecorderError('STATEMENT_NOT_ABOUT_CHANGE', f'the statement names neither the change {change!r} nor the '
                        f'project repository {name!r} as a whole token (a name of at least {NAME_MIN} characters)')


def record_from_log(project, change, item, statement, *, recorded_by, identity, harness=REPO, amend=False, now=None,
                    new_outcome=None, new_decision_id=None):
    """Record the Owner's acceptance of ITEM of CHANGE from STATEMENT, his statement recorded verbatim in the
    Decisions entry its reference names (``harness:evidence/bootstrap-log.md#<anchor>``) of the log at the
    ``HEAD`` commit of the harness repository HARNESS, and commit it in the project repository at its ``HEAD``.
    No challenge is shown: the record rests on the recorded statement (``recorded``, never ``shown``). Returns
    what ``record`` returns. NEW_OUTCOME and NEW_DECISION_ID (callables) stand in for the random UUIDs in tests."""
    _check_owner(statement)
    reference = statement['reference']
    anchor = _log_anchor(reference)
    if not isinstance(recorded_by, str) or not D.ATTRIBUTION.match(recorded_by):
        raise RecorderError('RECORDED_BY_INVALID', f'{recorded_by!r} is not owner, agent:<id> or person:<id>')
    if not isinstance(identity, str) or not ra.IDENTITY.fullmatch(identity):
        raise RecorderError('IDENTITY_INVALID', f'{identity!r} is not "Name <email>"')
    _check_names(change, item)
    now = now or utc_now()
    found = read_log_entry(harness, anchor)
    if not verbatim_admits(found.entry, statement['text']):
        raise RecorderError('STATEMENT_OUTSIDE_VERBATIM', 'the statement\'s text is not wholly inside the Owner\'s '
                            f'block (the first run of "> " lines) of the entry {anchor!r} at {found.revision}')
    words = statement_words(statement['text'])
    with _open(project) as repo:
        head = repo.head()
        if head.commit is None:
            raise RecorderError('PROJECT_UNAVAILABLE', 'the project repository has no commit at HEAD')
        state = _guarded(_Change, repo, head.commit, change, item)
        _guarded(_recorded_decisions, repo, head.commit, state.base)  # the committed records are well formed
        if reference in _quote_sources(state):
            raise RecorderError('ACCEPTANCE_IS_REQUEST', f'{reference} is the source of an Original Quote of {change}: '
                                'the request itself')
        for quote in state.record.sections.get('Original Quote', []):
            if quote.quote is not None and _within(words, quote.quote.decode('utf-8', 'replace').split()):
                raise RecorderError('ACCEPTANCE_IS_REQUEST', f'the statement\'s text is the text of {quote.id}, an '
                                    f'Original Quote of {change}: the request itself')
        about = _about(words, change, repository_name(origin_url(repo), repo.root))
        recorded = {'restsOn': D.RESTS_ON, 'entry': f'{G.LOG}#{anchor}', 'date': found.entry.date,
                    'revision': found.revision, **({'origin': found.origin} if found.origin else {}),
                    'digest': found.digest, 'about': about, 'challengeShown': False}
        return _accept(repo, head, state, statement, ('recorded', recorded), revision=head.commit,
                       proposal_digest=state.digest, recorded_by=recorded_by, identity=identity, amend=amend,
                       now=now, new_outcome=new_outcome, new_decision_id=new_decision_id)


def commit_message(decision, minted, statement):
    subject = decision['subject']
    verb = 'Accept' if minted else 'Re-accept'
    tail = 'outcome id minted' if minted else 'outcome id kept'
    recorded = decision.get('recorded')
    rests = '' if recorded is None else (
        f'It rests on the Owner\'s statement recorded in {recorded["entry"]} ({recorded["date"]}),\n'
        f'read at the harness revision {recorded["revision"]}. No challenge was shown.\n\n')
    return (f'{verb} {subject["item"]} of {subject["change"]}: outcome {subject["outcome"]} ({tail})\n\n'
            f'Owner decision {decision["decisionId"]} ({KIND}), recorded by {decision["recordedBy"]} with the\n'
            f'acceptance recorder. Statement: {statement["reference"]} ({statement["channel"]}).\n\n'
            f'{rests}'
            f'AIEH-Decision-Id: {decision["decisionId"]}\n'
            f'AIEH-Outcome-Id: {subject["outcome"]}\n'
            f'AIEH-Recorder: {RECORDER}\n')


# ---------------------------------------------------------------------------- edits

def _split_lines(data):
    """[(text, line ending)] of DATA (UTF-8): each ending '\\n', '\\r\\n' or '' (the last line), so
    that ``_join`` gives DATA back byte for byte. A file ending with a line break ends with
    ('', '')."""
    parts = data.decode('utf-8').split('\n')
    out = []
    for index, part in enumerate(parts):
        if index == len(parts) - 1:
            out.append((part, ''))
        elif part.endswith('\r'):
            out.append((part[:-1], '\r\n'))
        else:
            out.append((part, '\n'))
    return out


def _join(lines):
    return ''.join(text + end for text, end in lines).encode('utf-8')


def set_acceptance(proposal, item, reference):
    """PROPOSAL with Objective item ITEM set to ``authority: accepted`` and ``acceptance:
    REFERENCE``: the existing field lines are rewritten in place; an absent acceptance line is
    added after the authority line. Every other byte is kept."""
    intent = R._intent_module()
    record, _ = intent._Parser(proposal).parse()
    heading = record.items[item].line - 1
    lines = _split_lines(proposal)
    fields = {}
    index = heading + 1
    while index < len(lines):
        text = lines[index][0]
        if text.startswith('#'):
            break
        match = intent.FIELD_LINE.match(text)
        if match:
            fields[match.group(1)] = index
        index += 1
    authority = fields['authority']
    lines[authority] = ('- authority: accepted', lines[authority][1])
    if 'acceptance' in fields:
        lines[fields['acceptance']] = (f'- acceptance: {reference}', lines[fields['acceptance']][1])
    else:
        lines.insert(authority + 1, (f'- acceptance: {reference}', lines[authority][1] or '\n'))
    return _join(lines)


def declare_outcome(meta, outcome, item, reference):
    """META (a ``.openspec.yaml``) declaring OUTCOME as ``{item: ITEM, acceptance: REFERENCE}``
    under ``x-outcomes`` (decision 0008, point 4): an existing entry's acceptance is rewritten in
    place; a new entry is added at the end of the block, or a new block at the end of the file."""
    lines = _split_lines(meta)
    head = next((i for i, (text, _) in enumerate(lines) if text.rstrip(' ') == f'{R.X_OUTCOMES}:'), None)
    eol = next((end for _, end in lines if end), '\n')
    if head is None:
        if lines and lines[-1] == ('', ''):
            lines.pop()
        if lines and not lines[-1][1]:
            lines[-1] = (lines[-1][0], eol)
        lines += [(f'{R.X_OUTCOMES}:', eol), (f'  {outcome}:', eol), (f'    item: {item}', eol),
                  (f'    acceptance: {reference}', eol), ('', '')]
        return _join(lines)
    end, entry_indent, field_indent, entry_at = head + 1, None, None, None
    while end < len(lines):
        text = lines[end][0]
        stripped = text.strip(' ')
        if stripped and not stripped.startswith('#'):
            indent = len(text) - len(text.lstrip(' '))
            if indent == 0:
                break
            if entry_indent is None:
                entry_indent = indent
            elif indent > entry_indent and field_indent is None:
                field_indent = indent
            if indent == entry_indent and stripped == f'{outcome}:':
                entry_at = end
        end += 1
    if entry_at is not None:
        for index in range(entry_at + 1, end):
            text, ending = lines[index]
            stripped = text.strip(' ')
            if stripped and not stripped.startswith('#') and len(text) - len(text.lstrip(' ')) <= entry_indent:
                break  # the next entry: this one has no acceptance line (read_x_outcomes refuses that)
            if stripped.startswith('acceptance: '):
                lines[index] = (text[:len(text) - len(stripped)] + f'acceptance: {reference}', ending)
                break
        return _join(lines)
    entry_indent = entry_indent or 2
    field_indent = field_indent or entry_indent * 2
    last = end  # the new entry goes after the block's last entry line (not after blanks or comments)
    while last > head + 1 and (not lines[last - 1][0].strip(' ') or lines[last - 1][0].strip(' ').startswith('#')):
        last -= 1
    if not lines[last - 1][1]:  # the file ended without a line break
        lines[last - 1] = (lines[last - 1][0], eol)
        lines.append(('', ''))
    lines[last:last] = [(' ' * entry_indent + f'{outcome}:', eol), (' ' * field_indent + f'item: {item}', eol),
                        (' ' * field_indent + f'acceptance: {reference}', eol)]
    return _join(lines)


# ---------------------------------------------------------------------------- command line

def _read_json(path, code):
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise RecorderError(code, f'{path}: {type(exc).__name__}: {exc}') from None


def main(argv=None, out=None, err=None):
    parser = argparse.ArgumentParser(prog='acceptance_recorder.py', description='Record the Owner\'s acceptance of '
                                     'an objective and mint its outcome id (plan leaves P-04.1 and E-05.12; '
                                     'decision 0008). Exit 0 done, 2 refused (a stable code and its remedy).')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare', help='print the challenge to show the Owner; writes nothing')
    p.add_argument('--project', required=True)
    p.add_argument('--change', required=True)
    p.add_argument('--item', required=True)
    p.add_argument('--expires-in-minutes', type=int, default=DEFAULT_EXPIRY_MINUTES)
    p.add_argument('--out', help='also write the challenge to this new file')
    r = sub.add_parser('record', help='record the Owner\'s statement on a challenge and commit')
    r.add_argument('--project', required=True)
    r.add_argument('--challenge', help='the challenge file prepare wrote')
    r.add_argument('--statement', help='{text, attributedTo, channel, reference} as JSON')
    r.add_argument('--recorded-by', required=True)
    r.add_argument('--identity', required=True, help='the commit identity, "Name <email>"')
    r.add_argument('--amend', action='store_true', help='record a new acceptance of an item that has its outcome id')
    g = sub.add_parser('record-from-log', help='record the Owner\'s acceptance from his statement recorded verbatim in '
                       'the harness log\'s Decisions, without a challenge, and commit')
    g.add_argument('--project', required=True)
    g.add_argument('--change', required=True)
    g.add_argument('--item', required=True)
    g.add_argument('--statement', help='{text, attributedTo, channel, reference} as JSON, the reference '
                   'harness:evidence/bootstrap-log.md#<anchor>')
    g.add_argument('--harness', default=str(REPO), help='the harness repository whose committed log is read '
                   '(default: this checkout)')
    g.add_argument('--recorded-by', required=True)
    g.add_argument('--identity', required=True, help='the commit identity, "Name <email>"')
    g.add_argument('--amend', action='store_true', help='record a new acceptance of an item that has its outcome id')
    args = parser.parse_args(argv)
    out, err = out or sys.stdout, err or sys.stderr
    if out is sys.stdout and hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')
    try:
        if args.command == 'prepare':
            result = prepare(args.project, args.change, args.item, expires_in_minutes=args.expires_in_minutes)
            if args.out:
                with open(args.out, 'x', encoding='utf-8', newline='\n') as handle:
                    handle.write(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
        elif args.command == 'record-from-log':
            statement = _read_json(args.statement, 'STATEMENT_INVALID')
            result = record_from_log(args.project, args.change, args.item, statement, recorded_by=args.recorded_by,
                                     identity=args.identity, harness=args.harness, amend=args.amend)
        else:
            challenge = _read_json(args.challenge, 'CHALLENGE_INVALID')
            statement = _read_json(args.statement, 'STATEMENT_INVALID')
            result = record(args.project, challenge, statement, recorded_by=args.recorded_by, identity=args.identity,
                            amend=args.amend)
    except RecorderError as exc:
        err.write(f'acceptance-recorder: {exc}\n')
        return 2
    except ValueError as exc:
        err.write(f'acceptance-recorder: {exc}\n')
        return 2
    out.write(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
