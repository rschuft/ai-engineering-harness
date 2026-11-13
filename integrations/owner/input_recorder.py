"""The dispatch-input commands of the authorization recorder (plan leaf P-04.3; decision 0018 points 3.2,
3.3, 4.3, 5 and 7; decision 0012 points 4 to 6 and 9; decision 0008 points 2 and 5).

A deterministic, non-model recorder of the two decisions that approve dispatch inputs:

- **design acceptance** (``accept-design``): the design of one OpenSpec change of one manifest
  repository at an exact revision, bound to the sha256 of the change's folder there;
- **manifest promotion** (``promote-manifest``): one approved-input manifest
  (``ai-engineering-harness/dispatch/approved-inputs/v1``, unchanged), bound to the sha256 of its bytes,
  at the next position of the promotion series (its ``version``), and to the design acceptance each of
  its ``designs`` entries rests on.

Each is decided by the Owner (an ``owner-decision/v1`` record, through a challenge as the other recorders
take one: ``prepare``, then ``record``) or, under decision 0018 point 3.2 or 3.3, by the lead the
delegation table names (a ``delegated-decision/v1`` record, in one step: ``delegate``). A delegated
decision is never recorded as an Owner decision, never kept among the Owner's records and never shown as
the Owner's. Every decision is a write-ahead receipt in the integration store at its position of its
series (``input_decisions.py``); the store's unique key makes a position single-use.

This module is the only writer of the live manifest (``<state>/dispatch/approved-inputs.json``, decision
0009): ``manifest record`` and ``manifest delegate`` reserve the receipt, mark it dispatched, replace the
live file atomically in its own directory, read its digest back and confirm. A write that did not land
leaves a failed receipt and the live file as it was (``PROMOTION_FAILED``); an outcome it cannot read
back as decided leaves an unknown receipt (``OUTCOME_UNKNOWN``), which ``manifest resolve`` settles **by
reading** the live file. A failed or unconfirmed position is spent: the next promotion takes the next
version. ``load_manifest`` (integrations/dispatch, P-04.3 slice 2) trusts the store's confirmed receipts
only (``input_decisions.verifier``), never a file beside the manifest.

The module imports no Gitea and no credential module and reads no credential: it cannot reach the
protected merge path. An Owner-kind ``record`` is run only in the main session, on the Owner's decision,
with the statement transcribed verbatim (decision 0012 point 9). A ``delegate`` is run by the lead the
delegation table names, in its own session; who actually ran it, that the decision lies inside the
commitment or the envelope, and who wrote a log quote are not checked (decision 0018 point 7; decision
0010 point 1).

Usage (from the repository root, under the tools interpreter: Dulwich is required):

    <tools python> -I -B integrations/owner/input_recorder.py design prepare --project DIR --repository ID \\
        --change NAME --commit FULL [--expires-in-minutes N]
    <tools python> -I -B integrations/owner/input_recorder.py design record --challenge NONCE \\
        --statement FILE --recorded-by ATTRIBUTION
    <tools python> -I -B integrations/owner/input_recorder.py design delegate --project DIR --repository ID \\
        --change NAME --commit FULL --decided-by agent:product-manager --basis FILE
    <tools python> -I -B integrations/owner/input_recorder.py manifest prepare --candidate FILE \\
        [--expires-in-minutes N]
    <tools python> -I -B integrations/owner/input_recorder.py manifest record --challenge NONCE \\
        --statement FILE --recorded-by ATTRIBUTION
    <tools python> -I -B integrations/owner/input_recorder.py manifest delegate --candidate FILE \\
        --decided-by agent:product-manager --basis FILE
    <tools python> -I -B integrations/owner/input_recorder.py manifest resolve --version N
    <tools python> -I -B integrations/owner/input_recorder.py status

Exit status: 0 done (JSON on standard output), 2 refused (the code and its remedy on standard error;
nothing recorded or written), 1 failed or unknown (the receipt says which).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import importlib.util
import json
import os
import re
import secrets
import sys
import uuid
from pathlib import Path
from typing import Callable, NamedTuple

HERE = Path(os.path.realpath(__file__)).parent
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
G = _load('delegated_decision', HERE / 'delegated_decision.py')
I = _load('input_decisions', HERE / 'input_decisions.py')  # noqa: E741 - the read side, as D and G are formats
DI = _load('dispatch_inputs', REPO / 'integrations' / 'dispatch' / 'dispatch_inputs.py')
store_module = DI.store
paths = DI.paths
ra = G._repository_access()

DESIGN, PROMOTION = I.DESIGN, I.PROMOTION
RECORDER = I.RECORDER  # the actor of its receipts, which the verifier checks
CHALLENGE_FORMAT = 'owner-dispatch-input-challenge/v1'
CHALLENGE_FIELDS = ('format', 'kind', 'subject', 'position', 'shown', 'candidate')
OWNER_STATE = ('owner-authorization', 'dispatch-inputs')        # decision 0012 point 4: the recorder's own state
DELEGATED_STATE = ('delegated-decisions', 'dispatch-inputs')    # never under owner-authorization/
ADMITTED_CHANNELS = ('main-session',)  # authorization_recorder.ADMITTED_CHANNELS (a test asserts they are equal)
CHANGES_DIR = 'openspec/changes'
MANIFEST_SECTIONS = ('repositories', 'designs', 'profiles', 'catalog_pins', 'bindings')
DEFAULT_EXPIRY_MINUTES = 30
MAX_EXPIRY_MINUTES = 24 * 60
MAX_BASIS_BYTES = 64 * 1024

REMEDIES = {
    # shared with the other recorders: same names, same meanings
    'CHALLENGE_MISSING': 'run prepare, show its summary to the Owner, and pass the nonce it printed',
    'CHALLENGE_INVALID': 'pass the nonce exactly as prepare printed it, to the record command of the same kind',
    'CHALLENGE_UNKNOWN': 'this recorder did not issue that challenge: run prepare and show its summary to the Owner',
    'CHALLENGE_EXPIRED': 'run prepare again and show the new summary to the Owner',
    'CHALLENGE_CONSUMED': 'this challenge was already used: its position holds a receipt of it, confirmed or not (the '
                          'detail gives its state; status shows each series\' head, its failed positions and its '
                          'unsettled ones). A challenge is single-use: prepare a new challenge for a new Owner '
                          'decision, after manifest resolve if the receipt is an unsettled promotion',
    'CHALLENGE_STALE': 'another decision took this challenge\'s position, or the series changed after the summary was '
                       'shown: run prepare again and show the new summary to the Owner',
    'STATEMENT_MISSING': 'record only an Owner statement that exists: its text verbatim and the reference where it '
                         'is kept',
    'STATEMENT_MODEL_AUTHORED': 'a model cannot decide for the Owner: obtain the Owner\'s own statement, or record a '
                                'decision delegated by an accepted record with delegate',
    'STATEMENT_NOT_OWNER': 'only the Owner decides an Owner decision: record a statement attributed to owner',
    'STATEMENT_INVALID': 'give the statement as {text, attributedTo, channel, reference}, the channel a lower-case '
                         'token and the reference a scheme:reference',
    'CHANNEL_NOT_ADMITTED': 'record a statement given through an admitted channel (main-session during bootstrap)',
    'RECORDED_BY_INVALID': 'name who runs the recorder as owner, agent:<id> or person:<id>',
    'PROJECT_UNAVAILABLE': 'name the work tree root of the project repository, and run under the tools interpreter '
                           '(task tools:install)',
    'GIT_FAILED': 'repair the project repository (git fsck), then prepare again',
    'CHANGE_MISSING': 'name an OpenSpec change (lower-case letters, digits and hyphens) that has files under '
                      'openspec/changes/<change>/ at the commit',
    'OUTCOME_UNKNOWN': 'the live manifest did not read back as decided: run manifest resolve, which reads it and '
                       'never writes it again',
    'RECEIPT_MISSING': 'no promotion receipt exists at this version: nothing was recorded or written',
    # new for the dispatch-input commands
    'STATEMENT_SUBJECT_MISSING': 'the Owner\'s statement must name what the challenge shows: the change, or the token '
                                 'approved-inputs-v<version>',
    'REVISION_INVALID': 'name the exact revision: a full commit id (40 or 64 lower-case hex digits) of the project '
                        'repository',
    'CANDIDATE_UNREADABLE': 'name an absolute path to a readable candidate manifest file of at most 1 MiB',
    'CANDIDATE_INVALID': 'make the candidate a UTF-8, strict-JSON approved-inputs/v1 manifest (dispatch_inputs.py '
                         'check-manifest), then prepare again',
    'CANDIDATE_INSIDE_CHECKOUT': 'write the candidate outside the checkout (a throwaway directory)',
    'MANIFEST_LOCATION_INVALID': 'the live manifest\'s path is refused by load_manifest (not absolute, or inside or '
                                 'around the checkout): repair the managed data root',
    'VERSION_NOT_NEXT': 'give the candidate (or the decision) the next position of its series: read status',
    'DESIGN_ACCEPTANCE_MISSING': 'accept the design of each designs entry at its exact commit first (design prepare '
                                 'and record, or design delegate)',
    'DECISION_REPLAYED': 'the design entry names a revision whose acceptance a later one superseded: name the '
                         'currently accepted revision, or accept this one again',
    'PROMOTION_FAILED': 'the live manifest was not written and is as it was; the receipt is failed and its version '
                        'spent: repair the cause, then promote the candidate again at the next version',
    'PROMOTION_UNRESOLVED': 'an earlier promotion is not settled: run manifest resolve --version N first (for each '
                            'version the detail names), then prepare, record or delegate again',
    'DELEGATION_NOT_ACCEPTED': 'the delegating record is not Accepted (Owner) at the harness repository\'s HEAD: the '
                               'decision is the Owner\'s (prepare and record)',
    'AUTHORITY_UNAVAILABLE': 'the harness repository could not be read at HEAD: run from a full clone under the '
                             'tools interpreter',
    'DELEGATION_KIND_UNKNOWN': 'no accepted record delegates this kind: the decision is the Owner\'s',
    'DECIDER_NOT_DELEGATED': 'only the role the delegating record names decides this kind (for both P-04.3 kinds, '
                             'agent:product-manager; the engineering manager never promotes)',
    'DELEGATION_BASIS_INVALID': 'give the basis as {type, link, quote}: the type the delegation names (commitment or '
                                'envelope), link evidence/bootstrap-log.md#<anchor> of the Decisions entry quoted, and '
                                'the quote verbatim (a commitment\'s contains "Commitment: ")',
    'DELEGATION_BASIS_NOT_RECORDED': 'quote the commitment or the Owner\'s standing authorization exactly as it is '
                                     'committed in evidence/bootstrap-log.md at HEAD, and link the anchor of its '
                                     'Decisions entry (the work tree is not read)',
    'DELEGATION_BASIS_NOT_AUTHORITY': 'the anchored entry is not an authority of the basis type: a commitment rests on '
                                      'a "<date>: Commitment: ..." entry and quotes it; a promotion rests on a "<date>: '
                                      'Owner standing authorization: ..." entry and quotes its verbatim block. Without '
                                      'one, the decision is the Owner\'s (prepare and record)',
    # slice 2b
    'OWNER_ACCEPTANCE_HEAD': 'the change\'s current acceptance is the Owner\'s: a delegated acceptance cannot supersede '
                             'it (decision 0018 point 4.8); the next acceptance is the Owner\'s (prepare and record)',
    'IO_FAILED': 'a file could not be written or read (the detail says which); nothing was recorded unless a receipt '
                 'is named, and a named receipt is failed and its position spent: repair the cause and act again',
}


class RecorderError(Exception):
    """A refusal or failure with a stable code and its remedy. ``refusal`` is True when nothing was recorded
    or written (exit 2); False for a failed or unknown promotion (exit 1), whose receipt says which."""

    def __init__(self, code, detail, *, refusal=True, **details):
        self.code, self.detail, self.remedy, self.refusal, self.details = code, detail, REMEDIES[code], refusal, details
        super().__init__(f'{code}: {detail}. Remedy: {self.remedy}.')


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def timestamp(moment):
    return moment.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_timestamp(text):
    if not isinstance(text, str) or not D.TIMESTAMP.match(text):
        return None
    try:
        return datetime.datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------- context


class Context(NamedTuple):
    """Where the commands keep their state and write. STATE_ROOT is the managed ``state`` category (the
    Owner challenges and decision copies go under ``owner-authorization/dispatch-inputs/``, the delegated
    decision copies under ``delegated-decisions/dispatch-inputs/``); STORE the integration store holding the
    receipts; MANIFEST_PATH the live manifest; HARNESS the harness repository whose ``HEAD`` holds the
    delegating record and the log; CHECKOUT the checkout ``load_manifest`` refuses a manifest inside of.
    REPLACE stands in for ``os.replace`` in tests. A test passes its own state root, store, manifest path
    and harness repository; only main() builds the managed context (managed_context)."""
    state_root: Path
    store: object
    manifest_path: Path
    harness: Path
    checkout: Path = REPO
    now: Callable = utc_now
    replace: Callable = os.replace


def _check_context(ctx):
    if not isinstance(ctx, Context) or ctx.state_root is None or ctx.store is None or ctx.harness is None \
            or ctx.manifest_path is None or ctx.checkout is None:
        raise ValueError('a context needs its own state root, integration store, live manifest path, harness '
                         'repository and checkout')
    if not Path(ctx.manifest_path).is_absolute():
        raise ValueError('a context\'s live manifest path is absolute')


@contextlib.contextmanager
def managed_context():
    """The command line's context: the managed data root's ``state`` category, the integration store at its
    managed location (``<state>/integration/integration.sqlite``, the file the other recorders use), the
    live manifest at ``<state>/dispatch/approved-inputs.json`` (its directory created), and this checkout as
    the harness repository. It opens no Gitea and reads no credential."""
    res = paths.resolve()
    state = paths.ensure('state', res)
    paths.ensure('state', res, DI.MANIFEST_COMPONENT)
    with store_module.open_store(paths.ensure('state', res, 'integration') / 'integration.sqlite') as store:
        yield Context(state, store, DI.manifest_path(res), REPO, REPO)


def _owner_dir(ctx, *parts):
    return Path(ctx.state_root).joinpath(*OWNER_STATE, *parts)


def _write_new(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(text)


def _write_copy(ctx, decision):
    """The decision's JSON copy, for people and backups (the verifier never reads it)."""
    if decision['format'] == D.FORMAT:
        _write_new(_owner_dir(ctx, 'decisions', f'{decision["decisionId"]}.json'), D.dumps(decision))
    else:
        _write_new(Path(ctx.state_root).joinpath(*DELEGATED_STATE, f'{decision["decisionId"]}.json'),
                   G.dumps(decision))


# ---------------------------------------------------------------------------- checks shared by the kinds


def _expiry(expires_in_minutes):
    if isinstance(expires_in_minutes, bool) or not isinstance(expires_in_minutes, int) \
            or not 1 <= expires_in_minutes <= MAX_EXPIRY_MINUTES:
        raise ValueError(f'expires_in_minutes must be 1 to {MAX_EXPIRY_MINUTES}')


def _check_statement(statement, token):
    verdict, detail = D.statement_verdict(statement)
    code = {D.MISSING: 'STATEMENT_MISSING', D.MODEL: 'STATEMENT_MODEL_AUTHORED', D.NOT_OWNER: 'STATEMENT_NOT_OWNER',
            D.INVALID: 'STATEMENT_INVALID'}.get(verdict)
    if code is not None:
        raise RecorderError(code, detail)
    if statement['channel'] not in ADMITTED_CHANNELS:
        raise RecorderError('CHANNEL_NOT_ADMITTED', f'channel {statement["channel"]!r} is not one of '
                            f'{list(ADMITTED_CHANNELS)}')
    if not re.search(rf'(?<![A-Za-z0-9-]){re.escape(token)}(?![A-Za-z0-9-])', statement['text']):
        raise RecorderError('STATEMENT_SUBJECT_MISSING', f'the statement does not name {token}')


def _check_recorded_by(recorded_by):
    if not isinstance(recorded_by, str) or not D.ATTRIBUTION.match(recorded_by):
        raise RecorderError('RECORDED_BY_INVALID', f'{recorded_by!r} is not owner, agent:<id> or person:<id>')


def _authority(ctx, kind, decided_by, basis):
    failure = None
    try:
        return G.read_authority(ctx.harness, kind, decided_by, basis)
    except G.DelegationRefused as exc:
        failure = exc
    raise RecorderError(failure.code, failure.detail)


def _challenge_path(ctx, nonce):
    return _owner_dir(ctx, 'challenges', f'{nonce}.json')


def _write_challenge(ctx, challenge):
    """Write the challenge to the recorder's state: IO_FAILED (nothing recorded) when it cannot be written."""
    path = _challenge_path(ctx, challenge['shown']['nonce'])
    failure = None
    try:
        _write_new(path, json.dumps(challenge, indent=2, ensure_ascii=False) + '\n')
    except OSError as exc:
        failure = f'the challenge {path.name} could not be written: {type(exc).__name__}'
    if failure is not None:
        raise RecorderError('IO_FAILED', failure)


def load_challenge(ctx, nonce, kind):
    """The challenge of KIND this recorder issued under NONCE, from its own state."""
    if nonce is None or nonce == '':
        raise RecorderError('CHALLENGE_MISSING', 'no challenge was given')
    if not isinstance(nonce, str) or not D.NONCE.match(nonce):
        raise RecorderError('CHALLENGE_INVALID', f'{nonce!r} is not a nonce')
    try:
        challenge = json.loads(_challenge_path(ctx, nonce).read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise RecorderError('CHALLENGE_UNKNOWN', f'no challenge {nonce} in the recorder\'s state') from None
    except (OSError, ValueError) as exc:
        raise RecorderError('CHALLENGE_INVALID', f'challenge {nonce}: {type(exc).__name__}') from None
    invalid = RecorderError('CHALLENGE_INVALID', f'challenge {nonce} in the recorder\'s state is not a {CHALLENGE_FORMAT} '
                            f'challenge of kind {kind}')
    if not isinstance(challenge, dict) or list(challenge) != list(CHALLENGE_FIELDS) \
            or challenge['format'] != CHALLENGE_FORMAT or challenge['kind'] != kind:
        raise invalid
    subject, shown, position = challenge['subject'], challenge['shown'], challenge['position']
    if D.subject_problems(kind, subject) or isinstance(position, bool) or not isinstance(position, int) \
            or position < 1 or not isinstance(shown, dict) or list(shown) != list(D.SHOWN_FIELDS) \
            or shown['nonce'] != nonce or not isinstance(shown['summary'], str) \
            or parse_timestamp(shown['expiresAt']) is None:
        raise invalid
    if kind == DESIGN and challenge['candidate'] is not None:
        raise invalid
    if kind == PROMOTION:
        text = challenge['candidate']
        if not isinstance(text, str) or subject['version'] != position \
                or f'sha256:{_sha256(text.encode("utf-8"))}' != subject['digest']:
            raise invalid
    return challenge


def _check_unused(ctx, key, nonce):
    """CHALLENGE_CONSUMED when KEY holds this challenge's decision; CHALLENGE_STALE when it holds another."""
    existing = ctx.store.get(key)
    if existing is None:
        return
    try:
        held = json.loads(existing.intent_json)['decision'].get('shown', {}).get('nonce')
    except (TypeError, ValueError, KeyError, AttributeError):
        held = None
    if held == nonce:
        raise RecorderError('CHALLENGE_CONSUMED', f'challenge {nonce} already has receipt {key}, {existing.state}'
                            + ('' if existing.state == 'confirmed' else ': its decision was not confirmed'))
    raise RecorderError('CHALLENGE_STALE', f'{key} holds another decision ({existing.state})')


def _reserve(ctx, key, intent, nonce):
    """Reserve KEY with INTENT: the position is taken once. A key taken meanwhile is CHALLENGE_CONSUMED or
    CHALLENGE_STALE for an Owner decision (its nonce), VERSION_NOT_NEXT for a delegated one."""
    taken = None
    try:
        reserved = ctx.store.reserve(key, intent, actor=RECORDER)
    except store_module.ConflictingReservation as exc:
        taken = str(exc)
    else:
        if reserved.created:
            return
        taken = f'{key} already exists'
    if nonce is not None:
        _check_unused(ctx, key, nonce)
        raise RecorderError('CHALLENGE_STALE', taken)
    raise RecorderError('VERSION_NOT_NEXT', f'another decision took {key} meanwhile')


def _receipt_report(store, key):
    reservation = store.get(key)
    return {'operation_key': key, 'format': I.RECEIPT_FORMAT, 'state': reservation.state,
            'events': [event.to_state for event in store.events(key)]}


def _owner_decision(kind, subject, shown, statement, recorded_by, now, new_decision_id):
    decision = {'format': D.FORMAT, 'decisionId': str((new_decision_id or uuid.uuid4)()), 'kind': kind,
                'subject': subject, 'shown': {name: shown[name] for name in D.SHOWN_FIELDS},
                'statement': {name: statement[name] for name in D.STATEMENT_FIELDS},
                'recordedBy': recorded_by, 'recordedAt': timestamp(now)}
    problems = D.check_record(decision)
    if problems:  # the recorder's own invariant
        raise ValueError(f'the decision record is malformed: {problems[0]}')
    return decision


def _delegated_decision(authority, subject, now, new_decision_id):
    return G.decide(authority, subject, recorded_at=timestamp(now),
                    decision_id=None if new_decision_id is None else str(new_decision_id()))


# ---------------------------------------------------------------------------- design acceptance


def _guarded(call, *args):
    failure = None
    try:
        return call(*args)
    except ra.RepositoryError as exc:
        failure = exc
    raise RecorderError('GIT_FAILED', str(failure))


def _exact(check, value):
    """CHECK(VALUE) for a string without a line break: the shared grammars end in ``$``, which also matches
    before a final newline."""
    return isinstance(value, str) and '\n' not in value and check(value)


def read_design(project, repository, change, commit):
    """(content, files) of CHANGE at COMMIT of the project repository PROJECT (its work tree's root; the upward
    search stops there), read through the repository-access module (decision 0014): FILES is
    ``[(path relative to the change's folder, sha256 of its blob)]`` in ascending path order, and CONTENT
    ``sha256:`` over the lines ``<sha256>  <path>\\n`` of FILES."""
    if not _exact(D._manifest_id, repository):
        raise ValueError(f'{repository!r} is not a manifest repository id ([a-z0-9]+(-[a-z0-9]+)*, at most '
                         f'{D.MANIFEST_ID_MAX})')
    if not _exact(D._design_change, change):
        raise RecorderError('CHANGE_MISSING', f'{change!r} is not an OpenSpec change id')
    if not _exact(D._full_commit, commit):
        raise RecorderError('REVISION_INVALID', f'{commit!r} is not a full commit id')
    project = Path(project)
    failure = None
    try:
        repo = ra.open_repository(project, config='repository', ceilings=[str(project.parent)])
    except (ra.CannotRun, ra.RepositoryError) as exc:
        failure = str(exc)
    if failure is not None:
        raise RecorderError('PROJECT_UNAVAILABLE', failure)
    base = f'{CHANGES_DIR}/{change}'
    with repo:
        if _guarded(repo.commit, commit) != commit:
            raise RecorderError('REVISION_INVALID', f'{commit} is not a commit of {project}')
        found = _guarded(repo.files, commit, base)
        if not found:
            raise RecorderError('CHANGE_MISSING', f'{base}/ has no files at {commit}')
        files = sorted(((path[len(base) + 1:], _sha256(_guarded(repo.blob, commit, path))) for path in found),
                       key=lambda item: item[0].encode('utf-8'))
    lines = ''.join(f'{digest}  {path}\n' for path, digest in files)
    return f'sha256:{_sha256(lines.encode("utf-8"))}', files


def _design_head(ctx, repository, change):
    series = I.design_series(ctx.store, repository, change)
    head = I.last_confirmed(series)
    if head is not None and (problems := I.design_problems(head, repository, change)):
        raise ValueError(f'the integration store\'s receipt {head.key} is malformed: {problems[0]}')
    return series, head


def _design_subject(ctx, project, repository, change, commit):
    content, files = read_design(project, repository, change, commit)
    series, head = _design_head(ctx, repository, change)
    subject = {'repository': repository, 'change': change, 'commit': commit, 'content': content,
               'supersedes': None if head is None else head.intent['decision']['decisionId']}
    return subject, I.next_position(series), files, head


def design_summary(subject, position, files, head, expires):
    """The text shown to the Owner: a function of the subject, the position, the files, the superseded
    acceptance and the challenge's expiry only."""
    if head is None:
        superseded = 'none: this is the change\'s first acceptance.'
    else:
        prior = head.intent['decision']
        superseded = (f'{prior["decisionId"]} (sequence {head.position}, at {prior["subject"]["commit"]}, '
                      f'{I.authority(prior)["authority"]}).')
    return '\n'.join([
        f'Owner decision: accept a design ({DESIGN}).',
        f'Repository: {subject["repository"]}; OpenSpec change: {subject["change"]} at commit {subject["commit"]}.',
        f'The change\'s folder ({CHANGES_DIR}/{subject["change"]}/) at that commit, {len(files)} file(s), '
        f'{subject["content"]}:',
        *(f'- {digest}  {path}' for path, digest in files),
        f'Supersedes: {superseded}',
        f'Position: sequence {position} of this change\'s acceptances.',
        'If you accept it, the dispatch-input recorder records your decision in the integration store; a manifest '
        'promotion can then name this revision of the change.',
        f'To accept, reply in this conversation naming the change {subject["change"]}. This challenge expires at '
        f'{expires}.'])


def design_prepare(ctx, project, repository, change, commit, *, expires_in_minutes=DEFAULT_EXPIRY_MINUTES,
                   nonce=None):
    """Write a challenge for accepting the design of CHANGE at COMMIT to the recorder's own state and return
    it. Nothing is recorded."""
    _check_context(ctx)
    _expiry(expires_in_minutes)
    subject, position, files, head = _design_subject(ctx, project, repository, change, commit)
    now = ctx.now()
    nonce = nonce or secrets.token_hex(16)
    expires = timestamp(now + datetime.timedelta(minutes=expires_in_minutes))
    challenge = {'format': CHALLENGE_FORMAT, 'kind': DESIGN, 'subject': subject, 'position': position,
                 'shown': {'summary': design_summary(subject, position, files, head, expires), 'nonce': nonce,
                           'expiresAt': expires},
                 'candidate': None}
    _write_challenge(ctx, challenge)
    return challenge


def _record_design(ctx, decision, position, nonce):
    subject = decision['subject']
    key = I.design_key(subject['repository'], subject['change'], position)
    intent = {'format': I.RECEIPT_FORMAT, 'recorder': RECORDER, 'series': 'design', 'decision': decision,
              'repository': subject['repository'], 'change': subject['change'], 'sequence': position}
    _reserve(ctx, key, intent, nonce)
    try:
        _write_copy(ctx, decision)
        ctx.store.transition(key, 'dispatched', actor=RECORDER, reason='the decision is recorded',
                             detail={'recordedAt': decision['recordedAt']}, expected_from='reserved')
        ctx.store.transition(key, 'confirmed', actor=RECORDER, reason='the design acceptance is recorded',
                             detail={'decisionId': decision['decisionId']}, expected_from='dispatched')
    except Exception as exc:  # noqa: BLE001 - whatever stopped the act, its position is spent: mark it failed
        _fail_design(ctx, key, exc)
        if isinstance(exc, OSError):
            raise RecorderError('IO_FAILED', f'{type(exc).__name__} after {key} was reserved; the receipt is '
                                f'{ctx.store.get(key).state} and its position spent', refusal=False,
                                receipt=key) from None
        raise
    return {'decision': decision, 'receipt': _receipt_report(ctx.store, key), 'authority': I.authority(decision)}


def _fail_design(ctx, key, exc):
    """Mark a design receipt failed when the act stopped after its reservation, when the store lets us: a design
    acceptance has no external effect, so an unconfirmed one is simply spent."""
    with contextlib.suppress(Exception):
        current = ctx.store.get(key)
        if current is not None and current.state in ('reserved', 'dispatched'):
            ctx.store.transition(key, 'failed', actor=RECORDER, reason='the act stopped before it was confirmed',
                                 detail={'code': 'IO_FAILED' if isinstance(exc, OSError) else 'ACT_FAILED',
                                         'error': type(exc).__name__}, expected_from=current.state)


def design_record(ctx, nonce, statement, *, recorded_by, new_decision_id=None):
    """Record the Owner's STATEMENT accepting the design challenged under NONCE."""
    _check_context(ctx)
    challenge = load_challenge(ctx, nonce, DESIGN)
    subject, shown, position = challenge['subject'], challenge['shown'], challenge['position']
    now = ctx.now()
    if now >= parse_timestamp(shown['expiresAt']):
        raise RecorderError('CHALLENGE_EXPIRED', f'the challenge expired at {shown["expiresAt"]}')
    _check_unused(ctx, I.design_key(subject['repository'], subject['change'], position), nonce)
    _check_statement(statement, subject['change'])
    _check_recorded_by(recorded_by)
    series, head = _design_head(ctx, subject['repository'], subject['change'])
    current = None if head is None else head.intent['decision']['decisionId']
    if I.next_position(series) != position or current != subject['supersedes']:
        raise RecorderError('CHALLENGE_STALE', f'{subject["repository"]}/{subject["change"]} changed after the '
                            f'challenge: next sequence {I.next_position(series)}, current acceptance {current}')
    decision = _owner_decision(DESIGN, subject, shown, statement, recorded_by, now, new_decision_id)
    return _record_design(ctx, decision, position, nonce)


def design_delegate(ctx, project, repository, change, commit, *, decided_by, basis, new_decision_id=None):
    """Record the design acceptance DECIDED_BY makes under the delegation table's row for ``accept-design``
    (decision 0018 point 3.2), resting on BASIS."""
    _check_context(ctx)
    authority = _authority(ctx, DESIGN, decided_by, basis)
    subject, position, _files, head = _design_subject(ctx, project, repository, change, commit)
    if head is not None and head.intent['decision']['format'] == D.FORMAT:
        raise RecorderError('OWNER_ACCEPTANCE_HEAD', f'{repository}/{change}\'s current acceptance '
                            f'{head.intent["decision"]["decisionId"]} (sequence {head.position}) is the Owner\'s')
    decision = _delegated_decision(authority, subject, ctx.now(), new_decision_id)
    return _record_design(ctx, decision, position, None)


# ---------------------------------------------------------------------------- manifest promotion


def _location(ctx, path, codes):
    """Run load_manifest's path rules (and its read) on PATH; a refusal in CODES becomes its recorder code."""
    try:
        DI.load_manifest(path, repo_root=ctx.checkout)
    except DI.DispatchRefused as exc:
        if exc.code in codes:
            raise RecorderError(codes[exc.code], exc.detail) from None


def check_live_location(ctx):
    """MANIFEST_LOCATION_INVALID when load_manifest's own path rules refuse the live manifest's path."""
    _location(ctx, ctx.manifest_path, {'MANIFEST_PATH_INVALID': 'MANIFEST_LOCATION_INVALID',
                                       'MANIFEST_INSIDE_CHECKOUT': 'MANIFEST_LOCATION_INVALID'})


def read_candidate(ctx, candidate):
    """(text, ApprovedInputs) of the candidate manifest file CANDIDATE: outside the checkout, readable,
    strict JSON of the v1 schema (dispatch_inputs.parse_manifest)."""
    _location(ctx, candidate, {'MANIFEST_PATH_INVALID': 'CANDIDATE_UNREADABLE',
                               'MANIFEST_INSIDE_CHECKOUT': 'CANDIDATE_INSIDE_CHECKOUT'})
    failure = None
    try:
        with open(candidate, 'rb') as handle:
            raw = handle.read(DI.MAX_MANIFEST_BYTES + 1)
    except OSError as exc:
        failure = f'{candidate}: {type(exc).__name__}'
    if failure is None and len(raw) > DI.MAX_MANIFEST_BYTES:
        failure = f'{candidate} has more than {DI.MAX_MANIFEST_BYTES} bytes'
    if failure is not None:
        raise RecorderError('CANDIDATE_UNREADABLE', failure)
    try:
        approved = DI.parse_manifest(raw)
    except DI.DispatchRefused as exc:
        failure = exc.detail
    if failure is not None:
        raise RecorderError('CANDIDATE_INVALID', failure)
    return raw.decode('utf-8'), approved


def _promotion_head(ctx):
    series = I.promotions(ctx.store)
    head = I.last_confirmed(series)
    if head is not None and (problems := I.promotion_problems(head)):
        raise ValueError(f'the integration store\'s receipt {head.key} is malformed: {problems[0]}')
    return series, head


def _promotion_subject(ctx, approved):
    """The promote-manifest subject of APPROVED at the next position, and the head it replaces."""
    series, head = _promotion_head(ctx)
    # Resolving a receipt reads the live file; once a later promotion replaced it, a promotion that landed would
    # be recorded failed. So no promotion is decided while an earlier one is unsettled.
    unsettled = [r for r in series if r.state not in ('confirmed', 'failed')]
    if unsettled:
        raise RecorderError('PROMOTION_UNRESOLVED', 'the promotion series has unsettled receipts: '
                            + ', '.join(f'version {r.position} ({r.state})' for r in unsettled))
    position = I.next_position(series)
    if approved.version != position:
        raise RecorderError('VERSION_NOT_NEXT', f'the candidate is version {approved.version}; the next position of '
                            f'the promotion series is {position}')
    designs = []
    for entry in approved.data['designs']:
        answer = I.design_binding(ctx.store, entry['repository'], entry['change'], entry['commit'])
        if answer.code == 'DECISION_RECORD_INVALID':
            raise ValueError(f'the integration store holds a malformed design receipt: {answer.detail}')
        if answer.code is not None:
            raise RecorderError(answer.code, answer.detail)
        designs.append(answer.binding)
    previous = None if head is None else {'version': head.position, 'digest': head.intent['digest']}
    subject = {'schema': DI.MANIFEST_SCHEMA, 'version': approved.version, 'digest': f'sha256:{approved.sha256}',
               'previous': previous, 'designs': designs}
    return subject, head


def _entries(text):
    data = json.loads(text)
    return {section: {json.dumps(entry, sort_keys=True, separators=(',', ':')) for entry in data[section]}
            for section in MANIFEST_SECTIONS}


def manifest_summary(subject, text, head, expires):
    """The text shown to the Owner: a function of the subject, the candidate's text, the promotion it replaces
    and the challenge's expiry only."""
    lines = [f'Owner decision: promote an approved-input manifest ({PROMOTION}).',
             f'Manifest version {subject["version"]} ({subject["schema"]}), {subject["digest"]}.']
    if head is None:
        lines.append('It replaces nothing: this is the first promotion.')
    else:
        lines.append(f'It replaces version {head.position}, {head.intent["digest"]} '
                     f'({I.authority(head.intent["decision"])["authority"]} decision '
                     f'{head.intent["decision"]["decisionId"]}).')
    lines.append('Design entries and the acceptances they rest on:')
    lines.extend(f'- {b["repository"]}/{b["change"]} at {b["commit"]}: acceptance {b["acceptance"]} (sequence '
                 f'{b["sequence"]})' for b in subject['designs'])
    if not subject['designs']:
        lines.append('- none')
    if head is not None:
        old, new = _entries(head.intent['text']), _entries(text)
        changes = [f'{sign} {section}: {entry}' for section in MANIFEST_SECTIONS
                   for sign, entries in (('-', old[section] - new[section]), ('+', new[section] - old[section]))
                   for entry in sorted(entries)]
        lines.append(f'What changes from version {head.position}:')
        lines.extend(changes or ['- no entry changes'])
    lines.append('The manifest, exactly:')
    lines.append(text.rstrip('\n'))
    lines.append('If you promote it, the dispatch-input recorder writes exactly these bytes as the live manifest and '
                 'records your decision; dispatch then loads only this version.')
    lines.append(f'To promote, reply in this conversation naming approved-inputs-v{subject["version"]}. This '
                 f'challenge expires at {expires}.')
    return '\n'.join(lines)


def manifest_prepare(ctx, candidate, *, expires_in_minutes=DEFAULT_EXPIRY_MINUTES, nonce=None):
    """Write a challenge for promoting the candidate manifest file CANDIDATE to the recorder's own state (with
    the candidate's exact text) and return it. Nothing is recorded or written to the live manifest."""
    _check_context(ctx)
    _expiry(expires_in_minutes)
    check_live_location(ctx)
    text, approved = read_candidate(ctx, candidate)
    subject, head = _promotion_subject(ctx, approved)
    now = ctx.now()
    nonce = nonce or secrets.token_hex(16)
    expires = timestamp(now + datetime.timedelta(minutes=expires_in_minutes))
    challenge = {'format': CHALLENGE_FORMAT, 'kind': PROMOTION, 'subject': subject, 'position': subject['version'],
                 'shown': {'summary': manifest_summary(subject, text, head, expires), 'nonce': nonce,
                           'expiresAt': expires},
                 'candidate': text}
    _write_challenge(ctx, challenge)
    return challenge


def _live_digest(path):
    """``sha256:`` of the live manifest's bytes; None when it is absent; ``unreadable`` when it cannot be read."""
    try:
        with open(path, 'rb') as handle:
            return f'sha256:{_sha256(handle.read())}'
    except FileNotFoundError:
        return None
    except OSError:
        return 'unreadable'


def _discard(path):
    with contextlib.suppress(OSError):
        os.unlink(path)


def _promote(ctx, decision, text, nonce):
    """Reserve the promotion's receipt, write the live manifest atomically, read it back and confirm."""
    subject = decision['subject']
    key = I.promotion_key(subject['version'])
    intent = {'format': I.RECEIPT_FORMAT, 'recorder': RECORDER, 'series': 'promotion', 'decision': decision,
              'schema': subject['schema'], 'version': subject['version'], 'digest': subject['digest'],
              'previous': subject['previous'], 'text': text}
    _reserve(ctx, key, intent, nonce)
    failure = None
    try:
        _write_copy(ctx, decision)
    except OSError as exc:
        failure = exc
    if failure is not None:  # nothing was written to the live manifest: the position is spent, the receipt failed
        ctx.store.transition(key, 'failed', actor=RECORDER, reason='the decision copy could not be written',
                             detail={'code': 'PROMOTION_FAILED', 'stage': 'copy', 'error': type(failure).__name__},
                             expected_from='reserved')
        raise RecorderError('PROMOTION_FAILED', f'copy: {type(failure).__name__}; the live manifest is as it was; '
                            f'receipt {key} is failed', refusal=False, receipt=key)
    ctx.store.transition(key, 'dispatched', actor=RECORDER, reason='the live manifest is written',
                         detail={'sentAt': timestamp(ctx.now())}, expected_from='reserved')
    live = Path(ctx.manifest_path)
    before = _live_digest(live)
    temporary = live.parent / f'.{live.name}.{uuid.uuid4().hex}.tmp'

    def fail(stage, exc):
        ctx.store.transition(key, 'failed', actor=RECORDER, reason='the live manifest was not written',
                             detail={'code': 'PROMOTION_FAILED', 'stage': stage, 'error': type(exc).__name__,
                                     'live': before}, expected_from='dispatched')
        return RecorderError('PROMOTION_FAILED', f'{stage}: {type(exc).__name__}; the live manifest is as it was; '
                             f'receipt {key} is failed', refusal=False, receipt=key)

    def unknown(detail):
        ctx.store.transition(key, 'unknown', actor=RECORDER, reason='the live manifest did not read back as decided',
                             detail={'code': 'OUTCOME_UNKNOWN', 'detail': detail}, expected_from='dispatched')
        return RecorderError('OUTCOME_UNKNOWN', f'{detail}; receipt {key} is unknown', refusal=False, receipt=key)

    try:
        with open(temporary, 'xb') as handle:
            handle.write(text.encode('utf-8'))
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        _discard(temporary)
        raise fail('write', exc) from None
    try:
        ctx.replace(temporary, live)
    except OSError as exc:
        _discard(temporary)
        after = _live_digest(live)
        if after == before:
            raise fail('replace', exc) from None
        raise unknown(f'the replace raised {type(exc).__name__} and the live manifest is {after}') from None
    after = _live_digest(live)
    if after != subject['digest']:
        raise unknown(f'the live manifest reads back as {after}, not the decided {subject["digest"]}')
    ctx.store.transition(key, 'confirmed', actor=RECORDER, reason='written and read back',
                         detail={'digest': after, 'replaced': before}, expected_from='dispatched')
    return {'decision': decision, 'receipt': _receipt_report(ctx.store, key), 'authority': I.authority(decision),
            'manifest': {'version': subject['version'], 'digest': subject['digest']}}


def manifest_record(ctx, nonce, statement, *, recorded_by, new_decision_id=None):
    """Record the Owner's STATEMENT promoting the manifest challenged under NONCE, and write it as the live
    manifest."""
    _check_context(ctx)
    challenge = load_challenge(ctx, nonce, PROMOTION)
    subject, shown, position = challenge['subject'], challenge['shown'], challenge['position']
    now = ctx.now()
    if now >= parse_timestamp(shown['expiresAt']):
        raise RecorderError('CHALLENGE_EXPIRED', f'the challenge expired at {shown["expiresAt"]}')
    _check_unused(ctx, I.promotion_key(position), nonce)
    _check_statement(statement, f'approved-inputs-v{position}')
    _check_recorded_by(recorded_by)
    check_live_location(ctx)
    text = challenge['candidate']
    try:
        approved = DI.parse_manifest(text.encode('utf-8'))
    except DI.DispatchRefused as exc:  # a challenge altered in the recorder's state with a matching digest
        raise RecorderError('CHALLENGE_INVALID', f'challenge {nonce}\'s candidate is not a manifest: {exc.code}') \
            from None
    try:
        current, _head = _promotion_subject(ctx, approved)
    except RecorderError as exc:
        if exc.code != 'VERSION_NOT_NEXT':
            raise
        raise RecorderError('CHALLENGE_STALE', exc.detail) from None
    if current != subject:
        raise RecorderError('CHALLENGE_STALE', 'the promotion series or a design acceptance changed after the summary '
                            'was shown')
    decision = _owner_decision(PROMOTION, subject, shown, statement, recorded_by, now, new_decision_id)
    return _promote(ctx, decision, text, nonce)


def manifest_delegate(ctx, candidate, *, decided_by, basis, new_decision_id=None):
    """Record the promotion DECIDED_BY makes under the delegation table's row for ``promote-manifest`` (decision
    0018 point 3.3), resting on BASIS, and write the candidate as the live manifest."""
    _check_context(ctx)
    authority = _authority(ctx, PROMOTION, decided_by, basis)
    check_live_location(ctx)
    text, approved = read_candidate(ctx, candidate)
    subject, _head = _promotion_subject(ctx, approved)
    decision = _delegated_decision(authority, subject, ctx.now(), new_decision_id)
    return _promote(ctx, decision, text, None)


def manifest_resolve(ctx, version):
    """Settle the promotion receipt at VERSION by reading the live manifest, never by writing it: confirmed
    when its digest is the decided one, failed otherwise. A receipt left reserved (nothing was written)
    becomes failed."""
    _check_context(ctx)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError('version must be an integer of at least 1')
    key = I.promotion_key(version)
    reservation = ctx.store.get(key)
    if reservation is None:
        raise RecorderError('RECEIPT_MISSING', f'no receipt {key}')
    if reservation.state in ('confirmed', 'failed'):
        return {'receipt': _receipt_report(ctx.store, key), 'changed': False}
    if reservation.state == 'reserved':
        ctx.store.transition(key, 'failed', actor=RECORDER, reason='resolved: the live manifest was never written',
                             detail={'code': 'NOT_SENT'}, expected_from='reserved')
        return {'receipt': _receipt_report(ctx.store, key), 'changed': True}
    if reservation.state == 'dispatched':
        ctx.store.transition(key, 'unknown', actor=RECORDER, reason='resolved: the write\'s outcome was never recorded',
                             detail={'code': 'OUTCOME_UNKNOWN', 'detail': 'not recorded'}, expected_from='dispatched')
    decided = json.loads(reservation.intent_json)['digest']
    after = _live_digest(Path(ctx.manifest_path))
    if after == decided:
        ctx.store.transition(key, 'confirmed', actor=RECORDER, reason='resolved by reading: the live manifest is '
                             'the decided one', detail={'digest': after}, expected_from='unknown')
    else:
        ctx.store.transition(key, 'failed', actor=RECORDER, reason='resolved by reading: the live manifest is not '
                             'the decided one', detail={'code': 'NOT_WRITTEN', 'live': after, 'decided': decided},
                             expected_from='unknown')
    return {'receipt': _receipt_report(ctx.store, key), 'changed': True}


# ---------------------------------------------------------------------------- status


def status(ctx):
    """Each series' head with its authority, its next position, its failed positions and its unsettled ones
    (reserved, dispatched or unknown). Reads only."""
    _check_context(ctx)
    series, head = _promotion_head(ctx)
    promotion = None if head is None else {
        'version': head.position, 'digest': head.intent['digest'], 'receipt': head.key,
        'decisionId': head.intent['decision']['decisionId'], 'authority': I.authority(head.intent['decision'])}
    changes = sorted({tuple(r.operation_key[len(I.DESIGN_PREFIX):].split('/')[:2]) for r in ctx.store.attempts()
                      if r.operation_key.startswith(I.DESIGN_PREFIX)})
    designs = []
    for repository, change in changes:
        design_series, design_head = _design_head(ctx, repository, change)
        designs.append({'repository': repository, 'change': change, 'next': I.next_position(design_series),
                        'head': None if design_head is None else {
                            'sequence': design_head.position, 'receipt': design_head.key,
                            'commit': design_head.intent['decision']['subject']['commit'],
                            'decisionId': design_head.intent['decision']['decisionId'],
                            'authority': I.authority(design_head.intent['decision'])},
                        'failed': [r.position for r in design_series if r.state == 'failed'],
                        'unsettled': [{'sequence': r.position, 'state': r.state} for r in design_series
                                      if r.state not in ('confirmed', 'failed')]})
    return {'promotion': {'head': promotion, 'next': I.next_position(series),
                          'failed': [r.position for r in series if r.state == 'failed'],
                          'unsettled': [{'version': r.position, 'state': r.state} for r in series
                                        if r.state not in ('confirmed', 'failed')]},
            'designs': designs}


# ---------------------------------------------------------------------------- command line


def _read_json(path, code):
    if path is None:
        return None
    try:
        data = Path(path).read_bytes()
        if len(data) > MAX_BASIS_BYTES:
            raise ValueError('too large')
        return json.loads(data.decode('utf-8'))
    except (OSError, ValueError) as exc:
        raise RecorderError(code, f'{path}: {type(exc).__name__}') from None


def run(args, ctx):
    if args.command == 'status':
        return status(ctx)
    if args.command == 'design':
        if args.step == 'prepare':
            return design_prepare(ctx, os.path.abspath(args.project), args.repository, args.change, args.commit,
                                  expires_in_minutes=args.expires_in_minutes)
        if args.step == 'record':
            return design_record(ctx, args.challenge, _read_json(args.statement, 'STATEMENT_INVALID'),
                                 recorded_by=args.recorded_by)
        return design_delegate(ctx, os.path.abspath(args.project), args.repository, args.change, args.commit,
                               decided_by=args.decided_by, basis=_read_json(args.basis, 'DELEGATION_BASIS_INVALID'))
    if args.step == 'prepare':
        return manifest_prepare(ctx, os.path.abspath(args.candidate), expires_in_minutes=args.expires_in_minutes)
    if args.step == 'record':
        return manifest_record(ctx, args.challenge, _read_json(args.statement, 'STATEMENT_INVALID'),
                               recorded_by=args.recorded_by)
    if args.step == 'delegate':
        return manifest_delegate(ctx, os.path.abspath(args.candidate), decided_by=args.decided_by,
                                 basis=_read_json(args.basis, 'DELEGATION_BASIS_INVALID'))
    return manifest_resolve(ctx, args.version)


def parser():
    top = argparse.ArgumentParser(prog='input_recorder.py', description='Record design acceptances and manifest '
                                  'promotions (plan leaf P-04.3), by the Owner (prepare, record) or under decision '
                                  '0018 point 3 (delegate). Exit 0 done, 2 refused, 1 failed or unknown.')
    commands = top.add_subparsers(dest='command', required=True)
    design = commands.add_parser('design', help='accept the design of an OpenSpec change at an exact revision')
    manifest = commands.add_parser('manifest', help='promote an approved-input manifest')
    commands.add_parser('status', help='the head of each series; reads only')
    d = design.add_subparsers(dest='step', required=True)
    m = manifest.add_subparsers(dest='step', required=True)
    dp = d.add_parser('prepare', help='write the challenge to show the Owner to the recorder\'s state')
    dd = d.add_parser('delegate', help='record the acceptance delegated by decision 0018 point 3.2')
    for each in (dp, dd):
        each.add_argument('--project', required=True, help='the project repository\'s work tree root')
        each.add_argument('--repository', required=True, help='the manifest repository id')
        each.add_argument('--change', required=True, help='the OpenSpec change id')
        each.add_argument('--commit', required=True, help='the exact revision, a full commit id')
    mp = m.add_parser('prepare', help='write the challenge to show the Owner to the recorder\'s state')
    md = m.add_parser('delegate', help='record the promotion delegated by decision 0018 point 3.3 and write it')
    for each in (mp, md):
        each.add_argument('--candidate', required=True, help='the candidate manifest file, outside the checkout')
    for each in (dp, mp):
        each.add_argument('--expires-in-minutes', type=int, default=DEFAULT_EXPIRY_MINUTES)
    for sub in (d, m):
        r = sub.add_parser('record', help='record the Owner\'s statement on a challenge')
        r.add_argument('--challenge', help='the nonce prepare printed')
        r.add_argument('--statement', help='{text, attributedTo, channel, reference} as JSON')
        r.add_argument('--recorded-by', required=True)
    for each in (dd, md):
        each.add_argument('--decided-by', required=True, help='the role the delegation names')
        each.add_argument('--basis', required=True, help='{type, link, quote} as JSON')
    s = m.add_parser('resolve', help='settle an unconfirmed promotion by reading the live manifest; never writes')
    s.add_argument('--version', type=int, required=True)
    return top


def main(argv=None, out=None, err=None, context=None):
    """The command line. CONTEXT (a context manager factory taking nothing) stands in for managed_context in
    tests."""
    args = parser().parse_args(argv)
    out, err = out or sys.stdout, err or sys.stderr
    if out is sys.stdout and hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')
    try:
        with (context or managed_context)() as ctx:
            result = run(args, ctx)
    except RecorderError as exc:
        err.write(f'input-recorder: {exc}\n')
        return 2 if exc.refusal else 1
    except DI.DispatchRefused as exc:  # load_manifest's or parse_manifest's own refusal, by its code
        err.write(f'input-recorder: {exc.code}: {exc.detail}\n')
        return 2
    except OSError as exc:  # a file outside the recorder's own handling; nothing it reports was recorded
        err.write(f'input-recorder: IO_FAILED: {type(exc).__name__}: {exc}. Remedy: {REMEDIES["IO_FAILED"]}.\n')
        return 2
    except (ValueError, paths.PathsError, store_module.StoreError) as exc:
        err.write(f'input-recorder: {exc}\n')
        return 2
    out.write(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
