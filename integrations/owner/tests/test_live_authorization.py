"""The Owner authorization recorder on the live S-01.2.2 fixture (plan leaf P-04.2): opt-in, never by default,
in two separately invoked phases with the Owner's own decision between them (Owner decision OA-14).

The exercise never constructs, defaults, templates or paraphrases an Owner statement. The Owner sees the
exact operations the recorder challenged (phase ``prepare``), decides, and his reply, written verbatim
into a statement file by the Overseer, is what phase ``record`` reads. A general approval to run this test
authorizes no operation.

Each phase runs only on Windows, while the managed Gitea answers and the Credential Manager entries
"AIEH Gitea owner" and "AIEH Gitea bot <role>" (every role of gitea_roles.ROLES: the four bots and the
protection auditor of Owner decision OA-16) exist; otherwise it skips with its reason.
Without AIEH_AUTHZ_RECORDER_LIVE set to a phase it skips: the ordinary suites never read a credential or
write to Gitea. Each phase is an Owner-approved act. On aieh-authz-fixture/authz only:

**Phase prepare** (``AIEH_AUTHZ_RECORDER_LIVE=prepare``, ``AIEH_AUTHZ_RECORDER_RUN_DIR=<an existing,
empty directory>``):

1. As aieh-bot-builder (its token): two proposal branches work/authz-recorder-<stamp>-a and -b, each
   adding one manifest operations/<id>.json (kind ``fixture-no-op``; it expires in 24 hours), and a pull
   request for each into main. As aieh-bot-reviewer: one approving review of each (main requires one).
2. Negative controls, which need no Owner authority: each bot token (the protection auditor's included)
   attempts the merge of each pull request (``Do: merge`` with its ``head_commit_id``). Expected: refused
   (403 or 405; the auditor's read:repository token 403 by its scope) every time and main unchanged. **Any successful bot merge, or main moving, is a SECURITY FAILURE**: the test fails
   naming it and stops; no further step runs and no presentation is written.
3. The recorder's real ``prepare`` for each pull request (the real credential provider: it reads "AIEH
   Gitea owner" into memory; its own state and integration store under ``<run dir>/recorder``). It
   issues the one-time challenge (expiring in 180 minutes) and asks the protection verifier: the protection
   check of Owner decision OA-16 (integrations/gitea/protection_check.py; decision 0012 point 6), which
   reads "AIEH Gitea bot protection-audit" into memory and the fixture's protection as the auditor. Its
   answer is shown per challenge and decides the expected outcome.
4. The presentation, written to the run directory as ``presentation.json`` and ``presentation.txt``: per
   challenge the repository, the pull request, the base, the approved head, the manifest path and its
   digest, the operation id, kind, target and expiry, the challenge nonce and its expiry, the effects the
   merge will have, the expected outcome and the recorder's own summary; which pull request is the
   stale-head control (pull request B: expected refused, nothing merged and main unmoved; Gitea's 409 is
   expected, its 405 or 500 possible, finding F14); whether a protection verifier was available; the bot
   controls' statuses. Nothing is merged in this phase.
5. The custody inspection (below). Then the phase stops.

**Between the phases, the Owner.** The Overseer presents the presentation to the Owner. Only if the
Owner then authorizes, in his own words, naming the operation id(s) he authorizes, does the Overseer
write that reply verbatim into a statement file ``{text, attributedTo: "owner", channel: "main-session",
reference}`` (the recorder's statement form) and run phase record. Authorizing B is authorizing an
attempt that the exercise makes stale on purpose.

**Phase record** (``AIEH_AUTHZ_RECORDER_LIVE=record``, the same ``AIEH_AUTHZ_RECORDER_RUN_DIR``,
``AIEH_AUTHZ_RECORDER_STATEMENT=<the statement file>``):

1. The statement is read from the file exactly as written and validated with the recorder's own
   statement checks (attribution to the Owner, not model-authored, admitted channel, the operation id
   named). It refuses before anything is read from Gitea or the credential provider when the file is
   missing, empty or not JSON, model-authored or not the Owner's, or names none of the challenged
   operations. Only the challenges whose operation id the statement names are recorded.
2. ``record`` for each authorized challenge, with the protection verifier available to this run. **With
   none available, every record is refused ``PROTECTION_UNVERIFIED`` before anything is sent: nothing is
   merged, no receipt is written; that is the expected outcome.** With the protection check, a challenge
   whose check does not answer ``verified`` immediately before its merge is refused ``PROTECTION_DRIFT``
   or ``PROTECTION_UNVERIFIED`` with nothing sent (the expected outcome when the auditor is not
   provisioned or the fixture's protection is not the declared one). Otherwise A gives exactly one merge
   commit on main with main's head and the approved head as parents, the six trailers as written, the
   manifest digest at the merge, merged_by aieh-owner and the receipt confirmed, its protection answers
   before and after the merge equal; for B the builder pushes one commit to its branch after the
   recorder's checks and before its merge call (a hook on the recorder's merge call), and the property
   checked is that **nothing merges and main does not move**: Gitea's refusal is recorded as observed,
   not assumed (finding F14: 409 "head out of date" is expected, HEAD_STALE with the receipt failed; but
   while Gitea re-checks the pull request after the push it can answer 405 "try again later",
   MERGE_REFUSED with the receipt failed, or 500, OUTCOME_UNKNOWN with the receipt unknown). B merging
   is a SECURITY FAILURE: a head the Owner did not approve. B is recorded before A, so that A's merge
   does not leave B behind main (main's rule blocks an outdated branch, a 405 that would come before the
   409). A presentation that says a verifier was available when none is now (or the reverse) is refused:
   the Owner saw other outcomes.
3. Read-backs: main's head as expected; aieh-owner still holds zero tokens (the recorder's identity
   check). Cleanup: the builder closes every pull request of the run that is still open. A merge commit
   stays on the fixture's main (a protected branch: only a site administrator could rewrite it) and the
   work/ branches stay (protected branches cannot be deleted).
4. The custody inspection.

**The custody inspection** (each phase): the password of aieh-owner (read once more from its entry, in
memory) is searched for, as UTF-8 and UTF-16LE, in every file of the managed data root, every file git
lists in the checkout, the run directory, and this process's environment (inherited from the session
that runs it). Expected: found nowhere, nothing unreadable. Guest and job environments are not reachable
from the host and are not scanned here. The run directory stays for the record; its owner removes it.

AIEH_AUTHZ_RECORDER_REPORT, when set, names a JSON file that receives the observations (statuses, commit
ids, receipt states; never a credential). The phase plumbing is tested offline against the fake Gitea in
test_live_phases.py.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import re
import sys
import unittest
from pathlib import Path
from typing import Callable, NamedTuple

CATEGORY = 'e2e'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import authz_support as su  # noqa: E402

AR = su.AR
R = AR.roles
G = AR.host
PHASES = ('prepare', 'record')
PHASE = os.environ.get('AIEH_AUTHZ_RECORDER_LIVE', '')
RUN_DIR = os.environ.get('AIEH_AUTHZ_RECORDER_RUN_DIR')
STATEMENT = os.environ.get('AIEH_AUTHZ_RECORDER_STATEMENT')
REPORT = os.environ.get('AIEH_AUTHZ_RECORDER_REPORT')
REPOSITORY = f'{R.FIXTURE_ORG}/{R.FIXTURE_REPO}'
PRESENTATION_FORMAT = 'aieh-authz-live-presentation/1'
PRESENTATION, PRESENTATION_TEXT, RECORDER_DIR = 'presentation.json', 'presentation.txt', 'recorder'
CHALLENGE_MINUTES = 180
MANIFEST_HOURS = 24
KIND = 'fixture-no-op'
RECORDED_BY = 'agent:live-exercise'
AUTHORIZE, STALE = 'authorize', 'stale-head-control'
BOT_REFUSALS = (403, 405)
# Finding F14: the stale-head control's refusals (Gitea's answer to the moved head: 409, or 405 or 500 while
# Gitea re-checks the pull request after the push) with the receipt state each leaves
STALE_REFUSALS = {'HEAD_STALE': 'failed', 'MERGE_REFUSED': 'failed', 'OUTCOME_UNKNOWN': 'unknown'}
PROTECTION_REFUSALS = ('PROTECTION_DRIFT', 'PROTECTION_UNVERIFIED')
CHALLENGE_KEYS = ('role', 'repository', 'pull', 'base', 'branch', 'approvedHead', 'manifest', 'manifestDigest',
                  'operation', 'kind', 'target', 'operationExpiresAt', 'nonce', 'challengeExpiresAt',
                  'protectionAtPrepare', 'effects', 'expectedOutcome', 'summary')


class SecurityFailure(AssertionError):
    """A bot merged, or the protected branch moved, without Owner authority: the exercise stops here."""

    def __init__(self, detail):
        super().__init__(f'SECURITY FAILURE: {detail}')


class PhaseRefused(AssertionError):
    """The phase refused before acting (a stable code and its detail)."""

    def __init__(self, code, detail):
        self.code = code
        super().__init__(f'{code}: {detail}')


class Live(NamedTuple):
    """What a phase runs against: the Gitea port (HTTP None is host loopback; a callable with
    gitea_host.http_get's signature stands in for it offline), the credential provider, the run directory,
    the clock, the protection verifier available to this run (None until OA-16's mechanism is built) with
    a note saying why, and the custody inspection (None offline)."""
    port: int
    provider: object
    run_dir: Path
    http: Callable | None = None
    now: Callable = AR.utc_now
    verifier: Callable | None = None
    verifier_note: str = AR.NO_VERIFIER
    inspect: Callable | None = None


def available_verifier(port, provider):
    """(verifier, note): the protection verifier this exercise configures, the command line's: the protection
    check of Owner decision OA-16 (decision 0012 point 6) over the run's provider and port."""
    return AR.protection_verifier(provider, port), ('the protection check of Owner decision OA-16 '
                                                   '(integrations/gitea/protection_check.py), reading as '
                                                   f'{AR.protection.AUDITOR}')


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


def _timestamp(moment):
    return AR.timestamp(moment)


def _bot(live, role):
    token = R.read_token(live.provider, role)
    if token is None:
        raise PhaseRefused('CREDENTIAL_MISSING', f'no credential provider entry {R.target(role)!r}')
    return R.Api(live.port, token, live.http)


def _main_head(live):
    status, body = _bot(live, 'verifier').call('GET', f'/repos/{REPOSITORY}/branches/{R.DEFAULT_BRANCH}')
    expect(status == 200 and isinstance(body, dict), f'GET the protected branch answered {status}')
    return body['commit']['id']


def _pull(live, number):
    status, body = _bot(live, 'verifier').call('GET', f'/repos/{REPOSITORY}/pulls/{number}')
    expect(status == 200 and isinstance(body, dict), f'GET pull request {number} answered {status}')
    return body


def _open_store(live):
    root = Path(live.run_dir) / RECORDER_DIR
    root.mkdir(exist_ok=True)
    return su.IS.open_store(root / 'integration.sqlite')


def _context(live, store):
    return AR.Context(Path(live.run_dir) / RECORDER_DIR / 'state', store, live.provider, live.port, http=live.http,
                      now=live.now, verifier=live.verifier)


def _inspect(live, observed):
    if live.inspect is None:
        observed['inspection'] = 'not run (offline)'
        return
    observed['inspection'] = inspection = live.inspect(live.provider, Path(live.run_dir))
    expect(inspection['found'] == [] and inspection['unreadable'] == [], f'custody inspection: {inspection}')


# ---------------------------------------------------------------------------- phase prepare


def prepare_phase(live, observed):
    """Proposals, approvals, the bot controls, the recorder's challenges and the presentation; no merge."""
    run_dir = Path(live.run_dir)
    if not run_dir.is_dir() or any(run_dir.iterdir()):
        raise PhaseRefused('RUN_DIR_NOT_EMPTY', f'{run_dir} must be an existing, empty directory')
    now = live.now()
    stamp = now.strftime('%Y%m%dt%H%M%Sz')
    bots = {role: _bot(live, role) for role in R.ROLES}
    main_before = _main_head(live)
    observed['mainBefore'] = main_before
    proposals = []
    for role, suffix in ((AUTHORIZE, 'a'), (STALE, 'b')):
        operation, branch = f'live-{stamp}-{suffix}', f'work/authz-recorder-{stamp}-{suffix}'
        manifest = su.manifest(operation, kind=KIND, target=f'{REPOSITORY} (live recorder exercise; no effect)',
                               expiresAt=_timestamp(now + datetime.timedelta(hours=MANIFEST_HOURS)))
        status, body = bots['builder'].call('POST', f'/repos/{REPOSITORY}/contents/operations/{operation}.json', {
            'content': base64.b64encode(manifest).decode('ascii'), 'message': f'Propose operation {operation}',
            'branch': R.DEFAULT_BRANCH, 'new_branch': branch})
        expect(status == 201, f'the builder\'s proposal {operation} answered {status}: {body}')
        status, pull = bots['builder'].call('POST', f'/repos/{REPOSITORY}/pulls', {
            'head': branch, 'base': R.DEFAULT_BRANCH, 'title': f'Live recorder exercise: {operation}'})
        expect(status == 201 and isinstance(pull, dict), f'opening the pull request answered {status}: {pull}')
        head = pull['head']['sha']
        status, review = bots['reviewer'].call('POST', f'/repos/{REPOSITORY}/pulls/{pull["number"]}/reviews',
                                               {'event': 'APPROVED', 'body': 'live recorder exercise'})
        expect(status == 200, f'the reviewer\'s approval answered {status}: {review}')
        reviewed = review.get('commit_id') if isinstance(review, dict) else None
        expect(reviewed in (None, head), f'the approval is of {reviewed}, not the head {head}')
        proposals.append({'role': role, 'operation': operation, 'branch': branch, 'pull': pull['number'],
                          'head': head, 'manifest': manifest})
    observed['proposals'] = [{k: v for k, v in p.items() if k != 'manifest'} for p in proposals]
    # negative controls: every bot token's merge of every proposal must be refused
    observed['botMerges'] = controls = {}
    for proposal in proposals:
        for role, api in bots.items():
            status, _ = api.call('POST', f'/repos/{REPOSITORY}/pulls/{proposal["pull"]}/merge',
                                 {'Do': 'merge', 'head_commit_id': proposal['head']})
            controls[f'{role} on #{proposal["pull"]}'] = status
            if 200 <= status < 300:
                raise SecurityFailure(f'the {role} bot\'s merge of pull request #{proposal["pull"]} answered {status}')
    main_after = _main_head(live)
    merged = [p['pull'] for p in proposals if _pull(live, p['pull']).get('merged')]
    if main_after != main_before or merged:
        raise SecurityFailure(f'after the bot controls main is at {main_after} (was {main_before}) and pull '
                              f'request(s) {merged} are merged')
    unexpected = {k: s for k, s in controls.items() if s not in BOT_REFUSALS}
    expect(not unexpected, f'a bot merge was refused, but not with 403 or 405: {unexpected}')
    # the recorder's real prepare: one challenge per proposal
    store = _open_store(live)
    try:
        ctx = _context(live, store)
        challenges = [AR.prepare(ctx, REPOSITORY, p['pull'], expires_in_minutes=CHALLENGE_MINUTES) for p in proposals]
    finally:
        store.close()
    for proposal, challenge in zip(proposals, challenges):
        expect(challenge['subject']['head'] == proposal['head'], f'pull request #{proposal["pull"]} moved')
        expect(challenge['subject']['digest'] == 'sha256:' + hashlib.sha256(proposal['manifest']).hexdigest(),
               'the challenged digest is not the proposed manifest\'s')
    presentation = presentation_of(live, now, main_before, proposals, challenges, controls)
    (run_dir / PRESENTATION).write_text(json.dumps(presentation, indent=2, ensure_ascii=False) + '\n',
                                        encoding='utf-8', newline='\n')
    (run_dir / PRESENTATION_TEXT).write_text(presentation_text(presentation), encoding='utf-8', newline='\n')
    observed['challenges'] = [{'operation': c['operation'], 'nonce': c['nonce']} for c in presentation['challenges']]
    _inspect(live, observed)
    return presentation


def _effects(c):
    base, head = c['base'], c['approvedHead']
    effects = [
        f'a merge commit on {base} of {c["repository"]}, made by aieh-owner (Do: merge, head_commit_id {head}), '
        f'with {base}\'s head at the merge as first parent and {head} as second, carrying the six AIEH-* trailers',
        f'{c["manifest"]} ({c["manifestDigest"]}) added to {base}; nothing else changes on {base}',
        f'pull request #{c["pull"]} closed as merged; branch {c["branch"]} stays (protected: it cannot be deleted)',
        f'the Owner decision record and the receipt {AR.RECEIPT_PREFIX}{c["nonce"]} in this run\'s recorder state '
        'and store',
        f'nothing acts on the operation: its kind {KIND} is a fixture no-op']
    if c['role'] == STALE:
        effects.append('intended: none of the above. The exercise pushes one commit to its branch after the '
                       'recorder\'s checks and before its merge call, so Gitea refuses the merge (409 expected; '
                       'a 405 or 500 is possible while Gitea re-checks the pull request, finding F14)')
    return effects


STALE_OUTCOME = ('the stale-head control: the exercise moves the head after the recorder\'s checks; Gitea '
                 'refuses the merge, nothing is merged and main does not move; the refusal is recorded as '
                 'observed (409 HEAD_STALE, receipt failed, expected; 405 MERGE_REFUSED, receipt failed, or 500 '
                 'OUTCOME_UNKNOWN, receipt unknown, possible: finding F14)')


def _expected(c, verifier):
    if verifier is None:
        outcome = ('refused PROTECTION_UNVERIFIED before anything is sent: nothing is merged and no receipt is '
                   'written (no protection verifier is configured; decision 0012 point 6)')
        if c['role'] == STALE:
            outcome += f'; with a verifier answering verified it is {STALE_OUTCOME}'
        return outcome
    at_prepare = c['protectionAtPrepare']
    if at_prepare['verdict'] != 'verified':
        return (f'refused {at_prepare.get("code")} before anything is sent, as the protection check answered at '
                f'prepare ({at_prepare["detail"][:200]}): nothing is merged and no receipt is written, unless the '
                'protection is restored and the check answers verified immediately before the merge')
    if c['role'] == STALE:
        return STALE_OUTCOME
    return ('one merge commit as above, read back; the receipt is confirmed with equal protection answers before '
            'and after the merge; aieh-owner holds zero tokens; refused PROTECTION_DRIFT or PROTECTION_UNVERIFIED '
            '(nothing sent) if the protection check does not answer verified immediately before the merge')


def presentation_of(live, now, main_head, proposals, challenges, controls):
    """What the Owner is shown: the recorder's challenges, their effects and expected outcomes."""
    shown = []
    for proposal, challenge in zip(proposals, challenges):
        subject = challenge['subject']
        c = {'role': proposal['role'], 'repository': subject['repository'], 'pull': subject['pull'],
             'base': subject['base'], 'branch': proposal['branch'], 'approvedHead': subject['head'],
             'manifest': subject['manifest'], 'manifestDigest': subject['digest'], 'operation': subject['operation'],
             'kind': subject['operationKind'], 'target': subject['target'], 'operationExpiresAt': subject['expiresAt'],
             'nonce': challenge['shown']['nonce'], 'challengeExpiresAt': challenge['shown']['expiresAt'],
             'protectionAtPrepare': challenge['protection']}
        c.update(effects=_effects(c), expectedOutcome=_expected(c, live.verifier),
                 summary=challenge['shown']['summary'])
        shown.append({key: c[key] for key in CHALLENGE_KEYS})
    return {
        'format': PRESENTATION_FORMAT, 'preparedAt': _timestamp(now), 'repository': REPOSITORY,
        'base': R.DEFAULT_BRANCH, 'mainHead': main_head,
        'verifier': {'available': live.verifier is not None, 'note': live.verifier_note},
        'staleHeadControl': next(c['pull'] for c in shown if c['role'] == STALE),
        'recorder': {'state': f'{RECORDER_DIR}/state', 'store': f'{RECORDER_DIR}/integration.sqlite'},
        'botMerges': {'statuses': dict(controls), 'expected': 'each refused (403 or 405); any success is a SECURITY '
                                                               'FAILURE', 'mainUnchanged': True},
        'challenges': shown,
        'ownerAction': 'Nothing is merged unless the Owner, having seen this, replies in his own words naming the '
                       'operation id(s) he authorizes. The Overseer writes that reply verbatim into a statement file '
                       '{text, attributedTo: owner, channel: main-session, reference} and runs phase record with '
                       'AIEH_AUTHZ_RECORDER_STATEMENT naming it. The exercise never writes a statement.'}


def presentation_text(p):
    lines = [f'Live authorization recorder exercise, prepared {p["preparedAt"]}', '',
             f'Repository {p["repository"]}, protected branch {p["base"]} at {p["mainHead"]}.',
             'Protection verifier: ' + ('available' if p['verifier']['available'] else 'NONE')
             + f' ({p["verifier"]["note"]}).',
             f'Bot merge controls (each must be refused): {p["botMerges"]["statuses"]}.', '']
    for c in p['challenges']:
        role = ('THE STALE-HEAD CONTROL (expected: refused; nothing merges and main does not move)'
                if c['role'] == STALE else 'to authorize')
        lines += [f'== Pull request #{c["pull"]}: {role}',
                  f'Operation {c["operation"]} (kind {c["kind"]}); target: {c["target"]}; the manifest expires at '
                  f'{c["operationExpiresAt"]}.',
                  f'Manifest {c["manifest"]}, {c["manifestDigest"]}, at the approved head {c["approvedHead"]} '
                  f'(branch {c["branch"]} into {c["base"]}).',
                  f'Challenge nonce {c["nonce"]}, expires at {c["challengeExpiresAt"]}.',
                  f'Protection verifier at prepare: {c["protectionAtPrepare"]["verdict"]}.',
                  'Effects of the merge:', *(f'  - {e}' for e in c['effects']),
                  f'Expected outcome: {c["expectedOutcome"]}.', 'The recorder\'s summary:', c['summary'], '']
    lines += [p['ownerAction'], '']
    return '\n'.join(lines)


# ---------------------------------------------------------------------------- phase record


def load_presentation(run_dir):
    path = Path(run_dir) / PRESENTATION
    try:
        presentation = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise PhaseRefused('PRESENTATION_MISSING', f'{path} does not exist: run phase prepare first') from None
    except (OSError, ValueError) as exc:
        raise PhaseRefused('PRESENTATION_INVALID', f'{path}: {type(exc).__name__}') from None
    if not isinstance(presentation, dict):
        presentation = {}
    challenges = presentation.get('challenges')
    if presentation.get('format') != PRESENTATION_FORMAT or not isinstance(challenges, list) or not challenges \
            or any(not isinstance(c, dict) or tuple(c) != CHALLENGE_KEYS for c in challenges) \
            or not isinstance(presentation.get('verifier'), dict):
        raise PhaseRefused('PRESENTATION_INVALID', f'{path} is not a {PRESENTATION_FORMAT} presentation')
    return presentation


def read_statement(path):
    """The Owner's statement exactly as written in the file at PATH (the recorder's statement JSON)."""
    if not path:
        raise PhaseRefused('STATEMENT_MISSING', 'AIEH_AUTHZ_RECORDER_STATEMENT names no file: the Owner\'s own '
                           'reply, written verbatim, is required')
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise PhaseRefused('STATEMENT_MISSING', f'{path}: {type(exc).__name__}') from None
    if not raw.strip():
        raise PhaseRefused('STATEMENT_MISSING', f'{path} is empty')
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise PhaseRefused('STATEMENT_INVALID', f'{path} is not UTF-8 JSON') from None


def authorized_challenges(statement, challenges):
    """The challenges whose operation the statement authorizes, by the recorder's own statement checks;
    refused when the statement is not the Owner's or names none of them."""
    named = []
    for challenge in challenges:
        try:
            AR._check_statement(statement, challenge['operation'])
        except AR.RecorderError as exc:
            if exc.code != 'STATEMENT_OPERATION_MISSING':
                raise PhaseRefused(exc.code, exc.detail) from None
        else:
            named.append(challenge)
    if not named:
        raise PhaseRefused('STATEMENT_OPERATION_MISSING', 'the statement names none of the challenged operations '
                           f'{[c["operation"] for c in challenges]}')
    return named


def _record_stale(live, ctx, challenge, statement):
    """record with the head moved after the recorder's checks and before its merge call."""
    original, moved = AR.Gitea.merge, []

    def move_then_merge(session, path, body):
        status, _ = _bot(live, 'builder').call('POST', f'/repos/{REPOSITORY}/contents/operations/'
                                               f'{challenge["operation"]}.txt', {
            'content': base64.b64encode(b'moved after the recorder\'s checks\n').decode('ascii'),
            'message': 'Move the head after the checks', 'branch': challenge['branch']})
        moved.append(status)
        if status != 201:  # never send the merge of an unmoved head: an unknown outcome, nothing merged
            raise ConnectionAbortedError(f'the stale-head control could not move the head ({status})')
        return original(session, path, body)

    AR.Gitea.merge = move_then_merge
    try:
        return AR.record(ctx, challenge['nonce'], statement, recorded_by=RECORDED_BY), moved
    except AR.RecorderError as exc:
        return exc, moved
    finally:
        AR.Gitea.merge = original


def _gitea_status(result):
    """The HTTP status of Gitea's refusal in a recorder error's detail (None when it holds none)."""
    match = re.search(r'answered (?:HTTP )?([0-9]{3})', getattr(result, 'detail', '') or '')
    return int(match.group(1)) if match else None


def _receipt(store, nonce):
    reservation = store.get(AR.RECEIPT_PREFIX + nonce)
    return None if reservation is None else reservation.state


def record_phase(live, statement_path, observed):
    """The Owner's statement, read as written; record for each challenge it authorizes; the read-backs,
    the cleanup and the custody inspection."""
    presentation = load_presentation(live.run_dir)
    statement = read_statement(statement_path)
    authorized = authorized_challenges(statement, presentation['challenges'])
    if presentation['verifier'].get('available') is not (live.verifier is not None):
        said, now = presentation['verifier'].get('available'), live.verifier is not None
        raise PhaseRefused('VERIFIER_CHANGED', f'the presentation says a protection verifier was '
                           f'{"" if said else "not "}available, and one is {"" if now else "not "}available now: '
                           'the Owner saw other expected outcomes; run phase prepare again')
    observed['authorized'] = [c['operation'] for c in authorized]
    main_before = _main_head(live)
    observed['mainBefore'] = main_before
    outcomes = observed['outcomes'] = {}
    store = _open_store(live)
    try:
        ctx = _context(live, store)
        merged_commit = None
        for c in sorted(authorized, key=lambda c: c['role'] != STALE):  # the stale-head control first
            if live.verifier is None:
                try:
                    AR.record(ctx, c['nonce'], statement, recorded_by=RECORDED_BY)
                except AR.RecorderError as exc:
                    outcomes[c['operation']] = {'code': exc.code, 'refusal': exc.refusal,
                                                'receipt': _receipt(store, c['nonce'])}
                else:
                    raise SecurityFailure(f'the recorder merged {c["operation"]} with no protection verifier')
                expect(outcomes[c['operation']] == {'code': 'PROTECTION_UNVERIFIED', 'refusal': True, 'receipt': None},
                       f'{c["operation"]}: expected PROTECTION_UNVERIFIED and nothing sent, got '
                       f'{outcomes[c["operation"]]}')
            elif c['role'] == STALE:
                at_merge = _main_head(live)
                result, moved = _record_stale(live, ctx, c, statement)
                code = getattr(result, 'code', None)
                outcome = outcomes[c['operation']] = {
                    'code': code, 'moved': moved, 'receipt': _receipt(store, c['nonce']),
                    'giteaStatus': _gitea_status(result), 'detail': getattr(result, 'detail', None),
                    'merged': _pull(live, c['pull']).get('merged') is True, 'mainMoved': _main_head(live) != at_merge}
                if not isinstance(result, AR.RecorderError) or outcome['merged'] or outcome['mainMoved']:
                    raise SecurityFailure(f'the stale-head control merged a head the Owner did not approve: {outcome}')
                if code in PROTECTION_REFUSALS:  # refused before the merge call: the control was not reached
                    expect(moved == [] and outcome['receipt'] is None, f'the stale-head control: {outcome}')
                else:
                    expect(moved == [201] and STALE_REFUSALS.get(code, '?') == outcome['receipt'],
                           f'the stale-head control: {outcome}')
            else:
                at_merge = _main_head(live)
                try:
                    result = AR.record(ctx, c['nonce'], statement, recorded_by=RECORDED_BY)
                except AR.RecorderError as exc:
                    if exc.code not in PROTECTION_REFUSALS:
                        raise
                    outcomes[c['operation']] = {'code': exc.code, 'refusal': exc.refusal, 'detail': exc.detail,
                                                'receipt': _receipt(store, c['nonce'])}
                    expect(exc.refusal and outcomes[c['operation']]['receipt'] is None, f'{c["operation"]}: '
                           f'{outcomes[c["operation"]]}')
                    continue
                merged_commit = result['merge']['mergeCommit']
                outcomes[c['operation']] = {'merge': result['merge'], 'receipt': result['receipt'],
                                            'protection': result['protection'],
                                            'decision': result['decision']['decisionId']}
                expect(result['receipt']['state'] == 'confirmed', f'{c["operation"]}: {result["receipt"]}')
                expect(result['merge']['parents'] == [at_merge, c['approvedHead']], f'parents {result["merge"]}')
                expect(result['merge']['trailers'] == AR.trailers(result['decision'], c['approvedHead'],
                                                                  c['manifestDigest']), 'the trailers')
                expect(_main_head(live) == merged_commit, 'main is not at the merge commit')
                expect(result['protection']['equal'] is True, f'the protection changed across the merge: '
                       f'{result["protection"]}')
        # read-backs
        main_after = observed['mainAfter'] = _main_head(live)
        expect(main_after == (merged_commit or main_before), f'main is at {main_after}')
        merged_pulls = {c['pull'] for c in authorized if 'merge' in outcomes[c['operation']]}
        for c in presentation['challenges']:
            if c not in authorized:
                outcomes[c['operation']] = {'code': None, 'note': 'not authorized by the statement: not recorded'}
            merged = _pull(live, c['pull']).get('merged') is True
            expect(merged is (c['pull'] in merged_pulls), f'pull request #{c["pull"]}: merged {merged}')
        AR.open_session(ctx).close()  # zero tokens on aieh-owner (the recorder's identity check)
    finally:
        store.close()
    cleanup = observed['cleanup'] = {}
    for c in presentation['challenges']:
        if _pull(live, c['pull']).get('state') == 'open':
            status, _ = _bot(live, 'builder').call('PATCH', f'/repos/{REPOSITORY}/pulls/{c["pull"]}', {'state': 'closed'})
            cleanup[c['pull']] = status
            expect(status == 201, f'closing pull request #{c["pull"]} answered {status}')
    _inspect(live, observed)
    return observed


# ---------------------------------------------------------------------------- the live test


def _live():
    if PHASE not in PHASES:
        return None, ('the live recorder exercise is opt-in and runs in two phases, each an Owner-approved act: '
                      'AIEH_AUTHZ_RECORDER_LIVE=prepare, then (after the Owner\'s own reply) =record')
    if os.name != 'nt':
        return None, 'the credentials are in Windows Credential Manager'
    try:
        res = G.paths.resolve()
        port = G.read_host_record(G.layout(res))['port']
    except (G.GiteaError, G.paths.PathsError) as exc:
        return None, f'Gitea is not installed here ({exc})'
    if not G.healthy(port):
        return None, 'Gitea is not running (task gitea:up)'
    provider = G.credential_provider()
    if missing := sorted(role for role in R.ROLES if R.read_token(provider, role) is None):
        return None, f'no Credential Manager entry for {missing}'
    return (port, provider), None


class LiveExercise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        found, reason = _live()
        if found is None:
            raise unittest.SkipTest(reason)
        cls.port, cls.provider = found
        cls.observed = {'phase': PHASE}

    @classmethod
    def tearDownClass(cls):
        if REPORT:
            Path(REPORT).write_text(json.dumps(cls.observed, indent=1, default=str) + '\n', encoding='utf-8')

    def test_phase(self):
        if not RUN_DIR:
            raise PhaseRefused('RUN_DIR_MISSING', 'AIEH_AUTHZ_RECORDER_RUN_DIR must name the run directory')
        verifier, note = available_verifier(self.port, self.provider)
        live = Live(self.port, self.provider, Path(RUN_DIR), verifier=verifier, verifier_note=note,
                    inspect=inspect_custody)
        if PHASE == 'prepare':
            prepare_phase(live, self.observed)
        else:
            record_phase(live, STATEMENT, self.observed)


def inspect_custody(provider, run_dir):
    """Where aieh-owner's password is, besides its provider entry: every file of the managed data root (the
    managed recorder state and integration store included), every file git lists in the checkout, the run
    directory (this exercise's recorder state and store) and the environment of this process (which
    inherits the session's). File names only; the password is held in memory for the scan and dropped."""
    entry = provider.get(AR.OWNER_ENTRY)
    needles = [entry[1].encode('utf-8')]
    del entry
    try:
        root = G.paths.resolve().root
        managed = G.contains_secret(Path(str(root)), needles)
        checkout = G.files_containing(G.checkout_files(su.REPO), needles)
        run = G.contains_secret(Path(run_dir), needles)
        environment = [name for name, value in os.environ.items()
                       if any(n in value.encode('utf-8', 'replace') for n in needles)]
    finally:
        needles.clear()
    return {'found': managed['found'] + checkout['found'] + run['found'] + environment,
            'unreadable': managed['unreadable'] + checkout['unreadable'] + run['unreadable'],
            'scanned': {'managed root': 'every file', 'checkout': 'git ls-files --cached --others --exclude-standard',
                        'run directory': 'every file', 'environment': 'this process'}}


if __name__ == '__main__':
    unittest.main()
