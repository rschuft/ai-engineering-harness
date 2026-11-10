"""The Owner authorization recorder (plan leaf P-04.2; decision 0012 as proposed; decisions 0007, 0008 and
0010).

A deterministic, non-model recorder of the Owner's authorization of one exact operation manifest. The
record of an authorization is a merge commit on the protected branch of the authorization repository,
merged by the Gitea account aieh-owner; the act of the Owner is a recorded decision, never a Gitea
operation. This recorder is the sole custodian of cred-gitea-owner-account: it reads the entry
"AIEH Gitea owner" from the harness's credential provider (integrations/credentials, plan leaf F-06.3)
by name, into memory, for each command, and authenticates to Gitea by HTTP basic authentication over
host loopback. It never mints a token, never sends a token, never uses sudo, force_merge or auto-merge,
and makes merge commits only. It has no agent-callable or MCP surface: it is a command line that is run
only in the main session on an Owner decision.

In two steps, as the Owner sees them:

1. ``prepare <repository> <pull>`` reads the pull request as aieh-owner and, unless a refusal applies,
   writes a **challenge** to the recorder's own state (``<state>/owner-authorization/challenges/
   <nonce>.json``): the operation, the pull request, its exact head, the manifest's sha256 digest, what
   the manifest declares (its kind, target and expiry), the summary to show the Owner, a random nonce
   and the challenge's expiry.
2. ``record --challenge <nonce> --statement <file>`` takes the Owner's statement (the text verbatim,
   attributed to ``owner``, its channel and the reference where it is kept) and refuses, each with a
   stable code and its remedy (``REMEDIES``), unless all of these hold:

   - authenticity: the nonce is one this recorder issued (its own state), unexpired and unconsumed;
     the statement is the Owner's (``owner_decision.statement_verdict``), names the operation id, and
     came through an admitted channel (``ADMITTED_CHANNELS``);
   - binding: the pull request is open against the protected branch; its head and the manifest
     blob's digest are the challenged ones; the manifest is the single file ``operations/<id>.json``
     it adds; the operation id is new (not on the protected branch, no live or confirmed receipt); its
     author is not aieh-owner;
   - freshness: the challenge's and the manifest's expiries are unpassed and the pull request is
     mergeable;
   - policy: what aieh-owner can observe of the repository and the protected branch is as expected
     (``Policy``; see "What the policy check can see" below);
   - identity: the credential authenticates as aieh-owner, a non-administrator holding zero tokens;
   - single use: no receipt exists for the nonce;
   - protection: the protection verifier answers ``verified`` (see "The protection verifier" below),
     asked as the last read before the receipt is reserved and the merge is sent.

   It then writes the Owner decision record (``owner_decision.py``, kind ``authorize-operation``) and,
   before anything is sent, a write-ahead receipt of its own append-only kind in the integration store
   (``owner-authorization/v1/<nonce>``, format ``aieh-owner-authorization/1``; never the effects
   store); merges with ``Do: merge`` and ``head_commit_id`` (Gitea answers 409 when the head moved), the
   message carrying the trailers ``TRAILERS``; and reads back the protected ref, the merge's parents,
   the manifest digest at the merge and ``merged_by``. The receipt ends confirmed (read back), failed
   (Gitea refused: nothing merged) or unknown (the answer was lost, or the read-back disagreed).
3. ``resolve --challenge <nonce>`` resolves an unknown outcome **by reading** the pull request and its
   merge commit, never by merging again.

``merged_by: aieh-owner`` is shown as "merged under Owner authority by the recorder on decision <id>",
never as merged by the Owner. The bootstrap channel (``main-session``) is the Owner's verbatim reply in
the main-session conversation after the challenge is shown, transcribed by the Overseer and logged with
the decision id: it proves a declared decision bound to an exact revision, not an authenticated Owner.

**What the policy check can see.** Gitea 28.3.0 serves a repository's branch protection rules
(``GET /repos/{owner}/{repo}/branch_protections``) to repository administrators and site
administrators only (``reqToken(), reqAdmin()`` in routers/api/v1/api.go). aieh-owner is neither, so
the recorder compares what a write collaborator can read: the repository's merge settings and its own
permission (``GET /repos/{owner}/{repo}``), and the protected branch's view (``GET /repos/{owner}/{repo}/
branches/{branch}``: protected, required approvals, status checks, whether aieh-owner can push and can
merge). The rule's allowlists of other accounts and its override flags (``Policy.unobservable``) are not
compared here.

**The protection verifier (fail closed).** Decision 0012 point 6 (Owner decision OA-15a): the recorder
does not merge unless every security-relevant protection rule is verified by a narrowly scoped, trusted,
read-only check immediately before the merge. That check's mechanism is undecided (Owner action OA-16),
so the recorder calls it through a mechanism-neutral seam: ``Context.verifier``, a callable
``verifier(repository, base, phase)`` returning a ``ProtectionVerdict`` (``verified``, ``drift`` or
``unverified``, a detail, and optionally the sha256 digest of what it observed). It is given no
credential, session or state of the recorder. ``record`` asks it (phase ``before-merge``) as the last read
before the receipt is reserved and the merge is sent, and refuses unless the answer is ``verified``:
``drift`` is ``PROTECTION_DRIFT``; ``unverified``, an exception, a malformed answer or **no verifier
configured** is ``PROTECTION_UNVERIFIED``; in each case nothing is sent and no receipt is written. After
the read-back it asks once more (phase ``after-merge``); both answers go into the receipt (``protection``
in the intent and in the confirmed detail, additively), and an answer that differs from the first is
recorded as the disclosure ``PROTECTION_CHANGED_AFTER_MERGE`` (``DISCLOSURES``): the merge stands and the
receipt stays confirmed. ``prepare`` asks it too (phase ``prepare``) and reports the answer; it refuses
nothing on it, since it sends nothing. The command line's context (``managed_context``) configures **no
verifier**, so the command line refuses every merge until OA-16's mechanism is built and qualified. The
observable checks above stay, as an additional layer.

Usage (from the repository root, under the tools interpreter):

    <tools python> -I -B integrations/owner/authorization_recorder.py prepare OWNER/NAME PULL \\
        [--expires-in-minutes N] [--port PORT]
    <tools python> -I -B integrations/owner/authorization_recorder.py record --challenge NONCE \\
        --statement FILE --recorded-by ATTRIBUTION [--port PORT]
    <tools python> -I -B integrations/owner/authorization_recorder.py resolve --challenge NONCE [--port PORT]

Exit status: 0 done (JSON on standard output), 2 refused (the code and its remedy on standard error),
1 failed or unknown (the receipt says which; never retried by merging).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import http.client
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
roles = _load('aieh_gitea_roles', REPO / 'integrations' / 'gitea' / 'gitea_roles.py')
host = roles.host
contract = host.contract

KIND = 'authorize-operation'
RECORDER = 'authorization-recorder/1'
CHALLENGE_FORMAT = 'owner-authorization-challenge/v1'
CHALLENGE_SUBJECT = ('repository', 'pull', 'base', 'head', 'manifest', 'digest', 'operation', 'operationKind',
                     'target', 'expiresAt', 'author', 'title')
RECEIPT_FORMAT = 'aieh-owner-authorization/1'
RECEIPT_PREFIX = 'owner-authorization/v1/'
STATE_COMPONENT = 'owner-authorization'
CREDENTIAL = 'cred-gitea-owner-account'
OWNER = host.OWNER
OWNER_ENTRY = host.FINAL_TARGETS[host.OWNER]
BOT_ACCOUNTS = tuple(host.BOT_ACCOUNTS.values())
ADMITTED_CHANNELS = ('main-session',)  # the bootstrap channel (decision 0012 point 7)
MANIFEST_DIR = 'operations'
MANIFEST_FIELDS = ('operation', 'kind', 'target', 'expiresAt')  # read here; the typed manifest is G-04.1.1's
MANIFEST_MAX_BYTES = 64 * 1024
DEFAULT_EXPIRY_MINUTES = 30
MAX_EXPIRY_MINUTES = 24 * 60
TIMEOUT_S = 30.0
TRAILERS = ('AIEH-Decision-Id', 'AIEH-Decision-Channel', 'AIEH-Approved-Head', 'AIEH-Manifest-Digest',
            'AIEH-Statement-Ref', 'AIEH-Recorder')
TRAILER_LINE = re.compile(r'^(AIEH-[A-Za-z-]+): (\S+)$')
TOKEN_SHAPED = re.compile(r'^[0-9a-fA-F]{40}$')

REMEDIES = {
    'CHALLENGE_MISSING': 'run prepare, show its summary to the Owner, and pass the nonce it printed',
    'CHALLENGE_INVALID': 'pass the nonce exactly as prepare printed it (32 lower-case hex digits)',
    'CHALLENGE_UNKNOWN': 'this recorder did not issue that challenge: run prepare and show its summary to the Owner',
    'CHALLENGE_EXPIRED': 'run prepare again and show the new summary to the Owner',
    'CHALLENGE_CONSUMED': 'a decision was already recorded on this challenge: read its receipt (resolve), or '
                          'prepare a new challenge for a new Owner decision',
    'STATEMENT_MISSING': 'record only an Owner statement that exists: its text verbatim and the reference where '
                         'it is kept',
    'STATEMENT_MODEL_AUTHORED': 'a model cannot authorize: obtain the Owner\'s own statement',
    'STATEMENT_NOT_OWNER': 'only the Owner authorizes an operation: record a statement attributed to owner',
    'STATEMENT_INVALID': 'give the statement as {text, attributedTo, channel, reference}, the channel a lower-case '
                         'token and the reference a scheme:reference',
    'STATEMENT_OPERATION_MISSING': 'the Owner\'s statement must name the operation id the challenge shows',
    'CHANNEL_NOT_ADMITTED': 'record a statement given through an admitted channel (main-session during bootstrap)',
    'RECORDED_BY_INVALID': 'name who runs the recorder as owner, agent:<id> or person:<id>',
    'REPOSITORY_NOT_ADMITTED': 'name a repository whose protected-branch policy the recorder knows (Policy)',
    'CREDENTIAL_MISSING': 'the Owner account\'s credential is not in the credential provider: run task '
                          'gitea:finalize-credentials as an Owner-approved act',
    'CREDENTIAL_REFUSED': 'the recorder takes only aieh-owner\'s password from its own entry, never a token or '
                          'another account: repair the entry as an Owner-approved act',
    'CREDENTIAL_REJECTED': 'Gitea refused aieh-owner\'s credential: check the account (finalize-credentials) as an '
                           'Owner-approved act',
    'IDENTITY_NOT_OWNER': 'the credential authenticates as another account: repair the entry as an Owner-approved '
                          'act',
    'OWNER_IS_ADMIN': 'aieh-owner must not be an administrator: remove the flag as site administration',
    'OWNER_HAS_TOKEN': 'aieh-owner must hold zero tokens: delete them (finalize-credentials revokes them), then '
                       'investigate how they were made',
    'POLICY_DRIFT': 'the repository or the protected branch differs from the expected policy: restore the policy '
                    'as site administration, then prepare again',
    'PROTECTION_UNVERIFIED': 'the recorder does not merge until every security-relevant protection rule is verified '
                             'by a trusted read-only check (decision 0012 point 6); its mechanism is Owner action '
                             'OA-16, and the command line configures none until it is built and qualified. Nothing '
                             'was sent: configure the qualified protection verifier, or repair what kept it from '
                             'verifying, then record again on an unexpired challenge',
    'PROTECTION_DRIFT': 'a protection rule differs from its declaration: restore it as site administration (task '
                        'gitea:roles -- fixture for the authorization fixture), then record again on an unexpired '
                        'challenge',
    'GITEA_UNAVAILABLE': 'start Gitea (task gitea:up) and check its answers, then rerun',
    'PULL_NOT_FOUND': 'name an open pull request of the repository',
    'PULL_NOT_OPEN': 'only an open pull request is authorized: open a new one with a new operation manifest',
    'PULL_BASE_WRONG': 'the pull request must come from a branch of the repository into its protected branch',
    'PULL_AUTHOR_OWNER': 'aieh-owner never proposes: the proposal is opened by a bot',
    'HEAD_STALE': 'the pull request\'s head is not the challenged one (Gitea answers 409): prepare again and show '
                  'the new head to the Owner',
    'DIGEST_CHANGED': 'the manifest is not the challenged one: prepare again and show it to the Owner',
    'MANIFEST_NOT_SINGLE': 'the pull request must add exactly one file, operations/<id>.json, and nothing else',
    'MANIFEST_INVALID': 'the manifest must be a UTF-8 JSON object with operation (its file name\'s id), kind, '
                        'target and expiresAt (YYYY-MM-DDTHH:MM:SSZ)',
    'MANIFEST_EXPIRED': 'the operation manifest has expired: propose a new one',
    'OPERATION_NOT_NEW': 'this operation id is already on the protected branch or has a receipt: propose a new '
                         'operation id (resolve an unknown receipt first)',
    'PULL_NOT_MERGEABLE': 'Gitea does not report the pull request mergeable (conflict, checks or work in '
                          'progress): fix it, then prepare again',
    'MERGE_REFUSED': 'Gitea refused the merge; nothing was merged: read its message, fix the cause, and prepare a '
                     'new challenge for a new Owner decision',
    'OUTCOME_UNKNOWN': 'the merge\'s answer was lost or did not read back as recorded: run resolve, which reads '
                       'the pull request and never merges again',
    'RECEIPT_MISSING': 'no receipt exists for this challenge: nothing was recorded or sent',
}

# Codes recorded in a receipt's detail that are no refusal: the merge stands and the receipt stays confirmed.
DISCLOSURES = {
    'PROTECTION_CHANGED_AFTER_MERGE': 'the protection verifier answered differently after the merge than '
                                      'immediately before it: the merge stands and the receipt is confirmed, but a '
                                      'protection rule changed (or could no longer be verified) across it; '
                                      'investigate the change as site administration (decision 0012 point 6)',
}


class RecorderError(Exception):
    """A refusal or failure with a stable code and its remedy. ``refusal`` is True when nothing was sent to
    Gitea's merge (exit 2); False for a failed or unknown outcome (exit 1)."""

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


def display(decision_id):
    """How ``merged_by: aieh-owner`` is shown (decision 0012 point 3)."""
    return f'merged under Owner authority by the recorder on decision {decision_id}'


# ---------------------------------------------------------------------------- policy


class Policy(NamedTuple):
    """The expected policy of one admitted repository, as aieh-owner can observe it in Gitea 28.3.0."""
    base: str          # the protected branch
    repository: dict   # expected fields of GET /repos/{owner}/{repo}
    branch: dict       # expected fields of GET /repos/{owner}/{repo}/branches/{base}
    unobservable: tuple  # protection fields only repository or site administrators can read


UNOBSERVABLE = ('merge_whitelist_usernames (who else may merge)', 'push_whitelist_usernames',
                'enable_force_push and its allowlist', 'block_admin_merge_override', 'block_on_outdated_branch',
                'approvals_whitelist_username', 'block_on_rejected_reviews',
                'enable_bypass_allowlist and its allowlists (who may force-merge past every gate)',
                'block_on_codeowner_reviews', 'the effective rule\'s name')


def admitted_policies():
    """{repository: Policy}: the S-01.2.2 authorization fixture, whose protection gitea_roles declares (the
    authorization repository and its G-03.1 settings are not built yet)."""
    rule = next(r for r in roles.protection_rules() if r['rule_name'] == roles.DEFAULT_BRANCH)
    return {f'{roles.FIXTURE_ORG}/{roles.FIXTURE_REPO}': Policy(
        base=roles.DEFAULT_BRANCH,
        repository={'private': True, 'archived': False, 'default_branch': roles.DEFAULT_BRANCH,
                    'allow_merge_commits': True, 'permissions': {'admin': False, 'push': True, 'pull': True}},
        branch={'protected': True, 'user_can_push': rule['enable_push'], 'user_can_merge': True,
                'required_approvals': rule['required_approvals'], 'enable_status_check': False,
                'status_check_contexts': []},
        unobservable=UNOBSERVABLE)}


def policy_drift(policy, repository_view, branch_view):
    """[(field, expected, observed)] where what Gitea shows differs from POLICY."""
    drift = []
    for prefix, expected, observed in (('repository', policy.repository, repository_view),
                                       ('branch', policy.branch, branch_view)):
        for key, value in expected.items():
            seen = observed.get(key) if isinstance(observed, dict) else None
            if isinstance(value, dict) and isinstance(seen, dict):
                seen = {k: seen.get(k) for k in value}
            if value == [] and seen is None:  # Go serializes an empty list it never set as null
                seen = []
            if seen != value:
                drift.append((f'{prefix}.{key}', value, seen))
    return drift


# ---------------------------------------------------------------------------- the protection verifier

PROTECTION_VERDICTS = ('verified', 'drift', 'unverified')
PROTECTION_PHASES = ('prepare', 'before-merge', 'after-merge')
NO_VERIFIER = ('no protection verifier is configured: the trusted read-only check of every security-relevant '
               'protection rule (decision 0012 point 6) is not built yet (Owner action OA-16)')


class ProtectionVerdict(NamedTuple):
    """A protection verifier's answer: STATUS is one of PROTECTION_VERDICTS, DETAIL says what it found, and
    DIGEST (``sha256:<64 hex>`` or None) identifies what it observed, so two answers can be compared."""
    status: str
    detail: str
    digest: str | None = None


def check_protection(ctx, repository, base, phase):
    """The verifier's answer for PHASE as {verdict, detail, digest}; never raises for the verifier: no
    verifier, an exception or a malformed answer is ``unverified``."""
    if ctx.verifier is None:
        return {'verdict': 'unverified', 'detail': NO_VERIFIER, 'digest': None}
    try:
        answer = ctx.verifier(repository, base, phase)
    except Exception as exc:  # noqa: BLE001 - whatever the mechanism raises is an unverified answer
        return {'verdict': 'unverified', 'detail': f'the protection verifier raised {type(exc).__name__}',
                'digest': None}
    if not isinstance(answer, ProtectionVerdict) or answer.status not in PROTECTION_VERDICTS \
            or not isinstance(answer.detail, str) \
            or not (answer.digest is None or (isinstance(answer.digest, str) and D.DIGEST.match(answer.digest))):
        return {'verdict': 'unverified', 'detail': f'the protection verifier answered {type(answer).__name__}, not a '
                                                   'well-formed ProtectionVerdict', 'digest': None}
    return {'verdict': answer.status, 'detail': answer.detail[:500], 'digest': answer.digest}


def protection_code(verdict):
    """The refusal code of a verdict that is not ``verified`` (None when it is)."""
    if verdict['verdict'] == 'verified':
        return None
    return 'PROTECTION_DRIFT' if verdict['verdict'] == 'drift' else 'PROTECTION_UNVERIFIED'


def require_verified(verdict):
    """Refuse (nothing sent) unless the verdict is ``verified``."""
    if verdict['verdict'] == 'drift':
        raise RecorderError('PROTECTION_DRIFT', f'the protection verifier found drift: {verdict["detail"]}')
    if verdict['verdict'] != 'verified':
        raise RecorderError('PROTECTION_UNVERIFIED', verdict['detail'])


# ---------------------------------------------------------------------------- context


class Context(NamedTuple):
    """Where the recorder keeps its own state, the integration store that holds its receipts, the
    credential provider, and the Gitea it talks to (host loopback, PORT). A test passes its own state
    directory, an integration store of its own and a fixture provider; only main() builds the managed
    context (managed_context). HTTP None is one keep-alive connection to 127.0.0.1:PORT per command; a
    callable with gitea_host.http_get's signature stands in for it in tests. VERIFIER is the protection
    verifier (see "The protection verifier" above); None, as in the managed context until OA-16's
    mechanism is built, makes record refuse every merge with PROTECTION_UNVERIFIED."""
    state_dir: Path
    store: object
    provider: object
    port: int
    http: Callable | None = None
    now: Callable = utc_now
    policies: dict | None = None
    verifier: Callable | None = None


def _check_context(ctx):
    if not isinstance(ctx, Context) or ctx.state_dir is None or ctx.store is None or ctx.provider is None:
        raise ValueError('a context needs its own state directory, its own integration store and a provider')
    if not isinstance(ctx.port, int) or isinstance(ctx.port, bool) or not 0 < ctx.port < 65536:
        raise ValueError('a context needs the Gitea port')
    if ctx.verifier is not None and not callable(ctx.verifier):
        raise ValueError('a context\'s protection verifier is a callable or None')


@contextlib.contextmanager
def managed_context(port=None, guard=None):
    """The command line's context: the recorder's state under <state>/owner-authorization of the managed
    data root, the integration store at its managed location (decision 0009), the platform's credential
    provider (held by GUARD for the I7 scan) and the managed Gitea's port from its host record. It
    configures no protection verifier: the mechanism of decision 0012 point 6 is undecided (OA-16), so
    record refuses with PROTECTION_UNVERIFIED and merges nothing."""
    res = host.paths.resolve()
    if port is None:
        port = host.read_host_record(host.layout(res))['port']
    state = host.paths.ensure('state', res, STATE_COMPONENT)
    provider = host.credential_provider()
    if guard is not None:
        provider = contract.WatchedProvider(provider, guard)
    with host.credential_receipts(res) as store:
        yield Context(state, store, provider, port)


# ---------------------------------------------------------------------------- Gitea, as aieh-owner

_SEGMENT = r'[A-Za-z0-9][A-Za-z0-9._-]*'
_READS = tuple(re.compile(p) for p in (
    r'^/user$',
    rf'^/users/{re.escape(OWNER)}/tokens$',
    rf'^/repos/{_SEGMENT}/{_SEGMENT}$',
    rf'^/repos/{_SEGMENT}/{_SEGMENT}/branches/[A-Za-z0-9._/%-]+$',
    rf'^/repos/{_SEGMENT}/{_SEGMENT}/pulls/[0-9]+$',
    rf'^/repos/{_SEGMENT}/{_SEGMENT}/pulls/[0-9]+/files$',
    rf'^/repos/{_SEGMENT}/{_SEGMENT}/raw/{MANIFEST_DIR}/[a-z0-9-]+\.json\?ref=[0-9a-f]{{40}}$',
    rf'^/repos/{_SEGMENT}/{_SEGMENT}/git/commits/[0-9a-f]{{40}}\?stat=false&verification=false&files=false$',
))
_MERGE = re.compile(rf'^/repos/{_SEGMENT}/{_SEGMENT}/pulls/[0-9]+/merge$')
MERGE_BODY_KEYS = ('Do', 'merge_title_field', 'merge_message_field', 'head_commit_id', 'delete_branch_after_merge')


class Gitea:
    """aieh-owner's API session for one command: HTTP basic authentication with the password read from the
    credential provider into memory; never a token, never sudo. Only the reads in _READS and, when
    MAY_MERGE, the one merge call are possible."""

    def __init__(self, ctx, password, *, may_merge):
        self._ctx, self._password, self.may_merge = ctx, password, may_merge
        self._connection = None

    def close(self):
        self._password = None
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _send(self, method, path, body=None):
        headers = {'Accept': 'application/json', **host.basic_header(OWNER, self._password)}
        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if self._ctx.http is not None:
            return self._ctx.http(self._ctx.port, '/api/v1' + path, method=method, body=data, headers=headers,
                                  timeout=TIMEOUT_S)
        # One keep-alive connection per command. A read on a connection Gitea closed while it was idle is
        # sent once more on a new one; the merge never is (its lost answer is resolved by reading).
        reused = self._connection is not None
        if not reused:
            self._connection = http.client.HTTPConnection(host.LOOPBACK, self._ctx.port, timeout=TIMEOUT_S)
        try:
            return self._exchange(method, path, data, headers)
        except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            self._connection.close()
            self._connection = None
            if method != 'GET' or not reused:
                raise
        self._connection = http.client.HTTPConnection(host.LOOPBACK, self._ctx.port, timeout=TIMEOUT_S)
        return self._exchange(method, path, data, headers)

    def _exchange(self, method, path, data, headers):
        self._connection.request(method, '/api/v1' + path, body=data, headers=headers)
        response = self._connection.getresponse()
        payload = response.read()
        if response.will_close:
            self._connection.close()
            self._connection = None
        return response.status, {k.lower(): v for k, v in response.getheaders()}, payload

    def get(self, path, *, raw=False):
        """(status, parsed JSON, or the bytes when RAW). A failure to reach Gitea is GITEA_UNAVAILABLE."""
        if self._password is None or not any(p.match(path) for p in _READS):
            raise ValueError(f'GET {path} is not a call of the recorder')
        failure = None
        try:
            status, _headers, payload = self._send('GET', path)
        except (OSError, http.client.HTTPException) as exc:
            failure = exc
        if failure is not None:
            raise RecorderError('GITEA_UNAVAILABLE', f'GET {path}: {type(failure).__name__}')
        if raw:
            return status, payload
        try:
            return status, json.loads(payload) if payload else None
        except ValueError:
            return status, None

    def merge(self, path, body):
        """POST the merge: (status, parsed JSON); a lost answer raises OSError or HTTPException to the caller."""
        if self._password is None or not self.may_merge or not _MERGE.match(path):
            raise ValueError(f'POST {path} is not the recorder\'s merge')
        head = body.get('head_commit_id') if isinstance(body, dict) else None
        if tuple(body) != MERGE_BODY_KEYS or body['Do'] != 'merge' or body['delete_branch_after_merge'] is not False \
                or not isinstance(head, str) or not D.COMMIT.match(head):
            raise ValueError('the merge body is exactly Do: merge, its title and message, head_commit_id, and no '
                             'branch deletion')
        status, _headers, payload = self._send('POST', path, body)
        try:
            return status, json.loads(payload) if payload else None
        except ValueError:
            return status, None


def _message(payload):
    return str(payload.get('message', '')) if isinstance(payload, dict) else ''


def open_session(ctx, *, may_merge=False):
    """aieh-owner's session after the credential and identity checks: the entry is aieh-owner's own, holds a
    password (never a token), authenticates as aieh-owner, a non-administrator holding zero tokens."""
    entry = ctx.provider.get(OWNER_ENTRY)
    if entry is None:
        raise RecorderError('CREDENTIAL_MISSING', f'no credential provider entry {OWNER_ENTRY!r} ({CREDENTIAL})')
    user, secret = entry
    del entry
    if user != OWNER:
        what = 'a role bot' if user in BOT_ACCOUNTS else 'another account'
        raise RecorderError('CREDENTIAL_REFUSED', f'{OWNER_ENTRY!r} names {what} ({user!r}), not {OWNER}')
    if not isinstance(secret, str) or not secret or TOKEN_SHAPED.match(secret):
        raise RecorderError('CREDENTIAL_REFUSED', f'{OWNER_ENTRY!r} holds a token-shaped or empty secret: the '
                            'recorder authenticates with aieh-owner\'s password only, never a token')
    session = Gitea(ctx, secret, may_merge=may_merge)
    del secret
    try:
        status, me = session.get('/user')
        if status in (401, 403):
            raise RecorderError('CREDENTIAL_REJECTED', f'GET /user answered {status} ({_message(me)[:120]})')
        if status != 200 or not isinstance(me, dict):
            raise RecorderError('GITEA_UNAVAILABLE', f'GET /user answered {status}')
        if me.get('login') != OWNER:
            raise RecorderError('IDENTITY_NOT_OWNER', f'the credential authenticates as {me.get("login")!r}, not '
                                f'{OWNER}')
        if me.get('is_admin') is not False:
            raise RecorderError('OWNER_IS_ADMIN', f'{OWNER} has is_admin {me.get("is_admin")!r}')
        status, tokens = session.get(f'/users/{OWNER}/tokens')
        if status != 200 or not isinstance(tokens, list):
            raise RecorderError('GITEA_UNAVAILABLE', f'listing {OWNER}\'s tokens answered {status}')
        if tokens:
            names = [t.get('name') if isinstance(t, dict) else None for t in tokens]
            raise RecorderError('OWNER_HAS_TOKEN', f'{OWNER} holds {len(tokens)} token(s): {names!r}')
    except BaseException:
        session.close()
        raise
    return session


# ---------------------------------------------------------------------------- the pull request


def _policy_for(ctx, repository):
    policies = admitted_policies() if ctx.policies is None else ctx.policies
    if not isinstance(repository, str) or repository not in policies:
        raise RecorderError('REPOSITORY_NOT_ADMITTED', f'{repository!r} is not one of {sorted(policies)}')
    return policies[repository]


def check_policy(session, repository, policy):
    """POLICY_DRIFT unless what aieh-owner can observe is POLICY; returns the base branch's view."""
    status, repo_view = session.get(f'/repos/{repository}')
    if status != 200 or not isinstance(repo_view, dict):
        raise RecorderError('GITEA_UNAVAILABLE', f'GET /repos/{repository} answered {status}')
    status, branch_view = session.get(f'/repos/{repository}/branches/{policy.base}')
    if status != 200 or not isinstance(branch_view, dict):
        raise RecorderError('POLICY_DRIFT' if status == 404 else 'GITEA_UNAVAILABLE',
                            f'GET the protected branch {policy.base} answered {status}')
    drift = policy_drift(policy, repo_view, branch_view)
    if drift:
        raise RecorderError('POLICY_DRIFT', '; '.join(f'{f} is {seen!r}, expected {want!r}' for f, want, seen in drift))
    base_head = (branch_view.get('commit') or {}).get('id')
    if not isinstance(base_head, str) or not D.COMMIT.match(base_head):
        raise RecorderError('GITEA_UNAVAILABLE', f'the protected branch {policy.base} has no commit id')
    return base_head


class Proposal(NamedTuple):
    repository: str
    pull: int
    base: str
    base_head: str
    head: str
    author: str
    title: str
    operation: str
    manifest: str
    blob: bytes
    digest: str
    declared: dict
    mergeable: bool


def read_manifest(blob, operation):
    """The manifest's declared fields (MANIFEST_FIELDS), or MANIFEST_INVALID."""
    if len(blob) > MANIFEST_MAX_BYTES:
        raise RecorderError('MANIFEST_INVALID', f'the manifest has {len(blob)} bytes, more than {MANIFEST_MAX_BYTES}')
    try:
        data = json.loads(blob.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise RecorderError('MANIFEST_INVALID', 'the manifest is not UTF-8 JSON') from None
    if not isinstance(data, dict) or any(key not in data for key in MANIFEST_FIELDS):
        raise RecorderError('MANIFEST_INVALID', f'the manifest must be an object with {", ".join(MANIFEST_FIELDS)}')
    if data['operation'] != operation:
        raise RecorderError('MANIFEST_INVALID', f'the manifest names operation {data["operation"]!r}, its file '
                            f'{operation!r}')
    if not isinstance(data['kind'], str) or not D.OPERATION_KIND.match(data['kind']):
        raise RecorderError('MANIFEST_INVALID', 'its kind must be a lower-case token')
    target = data['target']
    if not isinstance(target, str) or not target.strip() or target.splitlines() != [target] or len(target) > 500:
        raise RecorderError('MANIFEST_INVALID', 'its target must be one line of text')
    if parse_timestamp(data['expiresAt']) is None:
        raise RecorderError('MANIFEST_INVALID', 'its expiresAt must be YYYY-MM-DDTHH:MM:SSZ')
    return {'kind': data['kind'], 'target': target, 'expiresAt': data['expiresAt']}


def read_proposal(session, repository, pull, policy, base_head, expected_head=None):
    """The pull request's binding facts, refusing what can never be authorized (an unopen or foreign pull
    request, aieh-owner's own, anything but one added manifest, an invalid manifest), and HEAD_STALE when
    EXPECTED_HEAD is given and the head is another."""
    status, pr = session.get(f'/repos/{repository}/pulls/{pull}')
    if status == 404:
        raise RecorderError('PULL_NOT_FOUND', f'{repository} has no pull request {pull}')
    if status != 200 or not isinstance(pr, dict):
        raise RecorderError('GITEA_UNAVAILABLE', f'GET pull request {pull} answered {status}')
    if pr.get('state') != 'open' or pr.get('merged'):
        raise RecorderError('PULL_NOT_OPEN', f'pull request {pull} is {pr.get("state")!r}'
                            + (' and merged' if pr.get('merged') else ''))
    base, head = pr.get('base') or {}, pr.get('head') or {}
    repo_name = lambda side: (side.get('repo') or {}).get('full_name')  # noqa: E731
    if base.get('ref') != policy.base or repo_name(base) != repository or repo_name(head) != repository:
        raise RecorderError('PULL_BASE_WRONG', f'pull request {pull} goes from {repo_name(head)!r} '
                            f'{head.get("ref")!r} into {repo_name(base)!r} {base.get("ref")!r}, not from a branch '
                            f'of {repository} into {policy.base}')
    author = (pr.get('user') or {}).get('login')
    if author == OWNER:
        raise RecorderError('PULL_AUTHOR_OWNER', f'pull request {pull} was opened by {OWNER}')
    sha = head.get('sha')
    if not isinstance(sha, str) or not D.COMMIT.match(sha):
        raise RecorderError('GITEA_UNAVAILABLE', f'pull request {pull} reports no head commit id')
    if expected_head is not None and sha != expected_head:
        raise RecorderError('HEAD_STALE', f'pull request {pull} is at {sha}, not the challenged {expected_head}')
    status, files = session.get(f'/repos/{repository}/pulls/{pull}/files')
    if status != 200 or not isinstance(files, list):
        raise RecorderError('GITEA_UNAVAILABLE', f'GET the files of pull request {pull} answered {status}')
    names = [(f.get('filename'), f.get('status')) if isinstance(f, dict) else (None, None) for f in files]
    match = re.fullmatch(rf'{MANIFEST_DIR}/([a-z0-9][a-z0-9-]{{0,127}})\.json', str(names[0][0])) \
        if len(names) == 1 else None
    if match is None or names[0][1] != 'added':
        raise RecorderError('MANIFEST_NOT_SINGLE', f'pull request {pull} changes {names!r}, not one added file '
                            f'{MANIFEST_DIR}/<id>.json')
    operation, manifest = match.group(1), names[0][0]
    status, blob = session.get(f'/repos/{repository}/raw/{manifest}?ref={sha}', raw=True)
    if status != 200 or not isinstance(blob, bytes):
        raise RecorderError('MANIFEST_INVALID', f'{manifest} at {sha} answered {status}')
    declared = read_manifest(blob, operation)
    status, _ = session.get(f'/repos/{repository}/raw/{manifest}?ref={base_head}', raw=True)
    if status != 404:
        raise RecorderError('OPERATION_NOT_NEW' if status == 200 else 'GITEA_UNAVAILABLE',
                            f'{manifest} at the protected branch ({base_head}) answered {status}')
    return Proposal(repository, pull, policy.base, base_head, sha, str(author), str(pr.get('title') or ''),
                    operation, manifest, blob, 'sha256:' + hashlib.sha256(blob).hexdigest(), declared,
                    pr.get('mergeable') is True)


def _receipts(store):
    """{nonce: (reservation, intent)} of this recorder's receipts."""
    out = {}
    for reservation in store.attempts():
        if reservation.operation_key.startswith(RECEIPT_PREFIX):
            out[reservation.operation_key[len(RECEIPT_PREFIX):]] = (reservation, json.loads(reservation.intent_json))
    return out


def check_new_operation(store, repository, operation):
    """OPERATION_NOT_NEW when a receipt that is not failed names the operation of REPOSITORY."""
    for nonce, (reservation, intent) in _receipts(store).items():
        if intent.get('repository') == repository and intent.get('operation') == operation \
                and reservation.state != 'failed':
            raise RecorderError('OPERATION_NOT_NEW', f'operation {operation} has receipt {RECEIPT_PREFIX}{nonce} '
                                f'({reservation.state})')


def check_unexpired(now, declared):
    if now >= parse_timestamp(declared['expiresAt']):
        raise RecorderError('MANIFEST_EXPIRED', f'the manifest expired at {declared["expiresAt"]}')


# ---------------------------------------------------------------------------- prepare


def summary(proposal, nonce_expiry):
    """The text shown to the Owner: a function of the proposal and the challenge's expiry only."""
    d = proposal.declared
    return '\n'.join([
        f'Owner decision: authorize an operation ({KIND}).',
        f'Repository: {proposal.repository}; pull request #{proposal.pull} into {proposal.base}, opened by '
        f'{proposal.author}: {proposal.title}',
        f'Operation: {proposal.operation} (kind {d["kind"]}); target: {d["target"]}; the manifest expires at '
        f'{d["expiresAt"]}.',
        f'Manifest: {proposal.manifest} at head {proposal.head}, {proposal.digest}:',
        proposal.blob.decode('utf-8').rstrip('\n'),
        f'If you authorize it, the authorization recorder merges exactly this head as {OWNER} (a merge commit; '
        'Gitea refuses it if the head changes) and records your decision. "merged_by: aieh-owner" then means '
        '"merged under Owner authority by the recorder on decision <id>", never "merged by the Owner".',
        f'To authorize, reply in this conversation naming the operation id {proposal.operation}. This challenge '
        f'expires at {nonce_expiry}.'])


def _challenge_path(ctx, nonce):
    return Path(ctx.state_dir) / 'challenges' / f'{nonce}.json'


def prepare(ctx, repository, pull, *, expires_in_minutes=DEFAULT_EXPIRY_MINUTES, nonce=None):
    """Write a challenge for authorizing pull request PULL of REPOSITORY to the recorder's own state and
    return it, with the protection verifier's answer under ``protection`` (reported, not written to the
    challenge: record asks again before the merge). Nothing is merged; nothing is written to Gitea."""
    _check_context(ctx)
    if not isinstance(expires_in_minutes, int) or not 1 <= expires_in_minutes <= MAX_EXPIRY_MINUTES:
        raise ValueError(f'expires_in_minutes must be 1 to {MAX_EXPIRY_MINUTES}')
    if isinstance(pull, bool) or not isinstance(pull, int) or pull < 1:
        raise RecorderError('PULL_NOT_FOUND', f'{pull!r} is not a pull request number')
    policy = _policy_for(ctx, repository)
    now = ctx.now()
    session = open_session(ctx)
    try:
        base_head = check_policy(session, repository, policy)
        proposal = read_proposal(session, repository, pull, policy, base_head)
    finally:
        session.close()
    check_new_operation(ctx.store, repository, proposal.operation)
    check_unexpired(now, proposal.declared)
    protection = check_protection(ctx, repository, policy.base, 'prepare')
    if (code := protection_code(protection)) is not None:
        protection = {**protection, 'code': code, 'note': f'record refuses with {code} unless the verifier answers '
                                                          'verified immediately before the merge'}
    nonce = nonce or secrets.token_hex(16)
    expires = timestamp(now + datetime.timedelta(minutes=expires_in_minutes))
    challenge = {'format': CHALLENGE_FORMAT, 'kind': KIND,
                 'subject': {'repository': repository, 'pull': pull, 'base': proposal.base, 'head': proposal.head,
                             'manifest': proposal.manifest, 'digest': proposal.digest, 'operation': proposal.operation,
                             'operationKind': proposal.declared['kind'], 'target': proposal.declared['target'],
                             'expiresAt': proposal.declared['expiresAt'], 'author': proposal.author,
                             'title': proposal.title},
                 'shown': {'summary': summary(proposal, expires), 'nonce': nonce, 'expiresAt': expires}}
    path = _challenge_path(ctx, nonce)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(challenge, indent=2, ensure_ascii=False) + '\n')
    return {**challenge, 'protection': protection}


# ---------------------------------------------------------------------------- record


def load_challenge(ctx, nonce):
    """The challenge this recorder issued under NONCE, from its own state."""
    if nonce is None or nonce == '':
        raise RecorderError('CHALLENGE_MISSING', 'no challenge was given')
    if not isinstance(nonce, str) or not D.NONCE.match(nonce):
        raise RecorderError('CHALLENGE_INVALID', f'{nonce!r} is not a nonce')
    path = _challenge_path(ctx, nonce)
    try:
        challenge = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise RecorderError('CHALLENGE_UNKNOWN', f'no challenge {nonce} in the recorder\'s state') from None
    except (OSError, ValueError) as exc:
        raise RecorderError('CHALLENGE_INVALID', f'challenge {nonce}: {type(exc).__name__}') from None
    subject, shown = (challenge.get('subject'), challenge.get('shown')) if isinstance(challenge, dict) else (None, None)
    if (not isinstance(challenge, dict) or list(challenge) != ['format', 'kind', 'subject', 'shown']
            or challenge['format'] != CHALLENGE_FORMAT or challenge['kind'] != KIND
            or not isinstance(subject, dict) or list(subject) != list(CHALLENGE_SUBJECT)
            or not isinstance(shown, dict) or list(shown) != list(D.SHOWN_FIELDS) or shown['nonce'] != nonce
            or parse_timestamp(shown['expiresAt']) is None
            or D.operation_subject_problems({k: subject[k] for k in D.SUBJECT_FIELDS[KIND]})):
        raise RecorderError('CHALLENGE_INVALID', f'challenge {nonce} in the recorder\'s state is not a '
                            f'{CHALLENGE_FORMAT} challenge')
    return challenge


def _check_statement(statement, operation):
    verdict, detail = D.statement_verdict(statement)
    code = {D.MISSING: 'STATEMENT_MISSING', D.MODEL: 'STATEMENT_MODEL_AUTHORED', D.NOT_OWNER: 'STATEMENT_NOT_OWNER',
            D.INVALID: 'STATEMENT_INVALID'}.get(verdict)
    if code is not None:
        raise RecorderError(code, detail)
    if statement['channel'] not in ADMITTED_CHANNELS:
        raise RecorderError('CHANNEL_NOT_ADMITTED', f'channel {statement["channel"]!r} is not one of '
                            f'{list(ADMITTED_CHANNELS)}')
    if not re.search(rf'(?<![a-z0-9-]){re.escape(operation)}(?![a-z0-9-])', statement['text']):
        raise RecorderError('STATEMENT_OPERATION_MISSING', f'the statement does not name operation {operation}')


def trailers(decision, approved_head, digest):
    """The trailer block of the merge commit, in TRAILERS order."""
    statement = decision['statement']
    values = (decision['decisionId'], statement['channel'], approved_head, digest, statement['reference'], RECORDER)
    return dict(zip(TRAILERS, values))


def merge_message(decision, trailer_values):
    """(title, body) of the merge commit: Gitea writes title, a blank line, then the body."""
    subject = decision['subject']
    title = f'Authorize operation {subject["operation"]} (Owner decision {decision["decisionId"]})'
    shown = display(decision['decisionId'])
    body = (f'{shown[0].upper()}{shown[1:]}.\n'
            f'Operation {subject["operation"]} ({subject["operationKind"]}), {subject["manifest"]}, pull request '
            f'#{subject["pull"]} of {subject["repository"]}.\n\n'
            + ''.join(f'{key}: {value}\n' for key, value in trailer_values.items()))
    return title, body


def parse_trailers(message):
    """{key: value} of the AIEH trailers in the last paragraph of a commit message (None for a key given
    twice)."""
    paragraphs = [p for p in message.replace('\r\n', '\n').strip('\n').split('\n\n') if p.strip()]
    found = {}
    for line in paragraphs[-1].split('\n') if paragraphs else []:
        match = TRAILER_LINE.match(line.rstrip())
        if match:
            found[match.group(1)] = None if match.group(1) in found else match.group(2)
    return found


def _receipt_key(nonce):
    return RECEIPT_PREFIX + nonce


def record(ctx, nonce, statement, *, recorded_by, new_decision_id=None):
    """Record the Owner's STATEMENT on challenge NONCE and merge the challenged head as aieh-owner. Returns
    the decision, the receipt, the read-back and the protection answers around the merge; raises
    RecorderError on a refusal (nothing sent: PROTECTION_UNVERIFIED unless the verifier answers verified),
    a refusal by Gitea (receipt failed) or an unknown outcome (receipt unknown)."""
    _check_context(ctx)
    challenge = load_challenge(ctx, nonce)
    subject, shown = challenge['subject'], challenge['shown']
    now = ctx.now()
    if now >= parse_timestamp(shown['expiresAt']):
        raise RecorderError('CHALLENGE_EXPIRED', f'the challenge expired at {shown["expiresAt"]}')
    existing = ctx.store.get(_receipt_key(nonce))
    if existing is not None:
        raise RecorderError('CHALLENGE_CONSUMED', f'challenge {nonce} already has receipt {existing.operation_key} '
                            f'({existing.state})')
    _check_statement(statement, subject['operation'])
    if not isinstance(recorded_by, str) or not D.ATTRIBUTION.match(recorded_by):
        raise RecorderError('RECORDED_BY_INVALID', f'{recorded_by!r} is not owner, agent:<id> or person:<id>')
    check_unexpired(now, subject)
    repository = subject['repository']
    policy = _policy_for(ctx, repository)
    check_new_operation(ctx.store, repository, subject['operation'])
    session = open_session(ctx, may_merge=True)
    try:
        base_head = check_policy(session, repository, policy)
        proposal = read_proposal(session, repository, subject['pull'], policy, base_head, subject['head'])
        if proposal.manifest != subject['manifest'] or proposal.digest != subject['digest']:
            raise RecorderError('DIGEST_CHANGED', f'{proposal.manifest} is {proposal.digest}, not the challenged '
                                f'{subject["manifest"]} {subject["digest"]}')
        check_unexpired(now, proposal.declared)
        if not proposal.mergeable:
            raise RecorderError('PULL_NOT_MERGEABLE', f'Gitea reports pull request {subject["pull"]} not mergeable')
        decision = {
            'format': D.FORMAT, 'decisionId': str((new_decision_id or uuid.uuid4)()), 'kind': KIND,
            'subject': {name: subject[name] for name in D.SUBJECT_FIELDS[KIND]},
            'shown': {name: shown[name] for name in D.SHOWN_FIELDS},
            'statement': {name: statement[name] for name in D.STATEMENT_FIELDS},
            'recordedBy': recorded_by, 'recordedAt': timestamp(now)}
        problems = D.check_record(decision)
        if problems:  # the recorder's own invariant
            raise ValueError(f'the decision record is malformed: {problems[0]}')
        values = trailers(decision, subject['head'], subject['digest'])
        title, body = merge_message(decision, values)
        # The protection verifier: the last read before the receipt is reserved and the merge is sent.
        before = check_protection(ctx, repository, policy.base, 'before-merge')
        require_verified(before)
        intent = {'format': RECEIPT_FORMAT, 'recorder': RECORDER, 'decision': decision, 'repository': repository,
                  'pull': subject['pull'], 'base': policy.base, 'baseHead': base_head, 'operation': subject['operation'],
                  'approvedHead': subject['head'], 'manifest': subject['manifest'], 'digest': subject['digest'],
                  'trailers': values, 'merge': {'Do': 'merge', 'head_commit_id': subject['head']},
                  'credential': {'id': CREDENTIAL, 'entry': OWNER_ENTRY, 'user': OWNER,
                                 'method': 'HTTP basic authentication, in memory, for this command'},
                  'protection': {'before': before}}
        key = _receipt_key(nonce)
        try:
            reserved = ctx.store.reserve(key, intent, actor=RECORDER)
        except Exception as exc:  # noqa: BLE001 - a conflicting reservation means the nonce was used meanwhile
            if type(exc).__name__ == 'ConflictingReservation':
                raise RecorderError('CHALLENGE_CONSUMED', f'{key} was reserved by another decision') from None
            raise
        if not reserved.created:
            raise RecorderError('CHALLENGE_CONSUMED', f'{key} already exists')
        _write_decision(ctx, decision)
        ctx.store.transition(key, 'dispatched', actor=RECORDER, reason='the merge is sent',
                             detail={'sentAt': timestamp(now)}, expected_from='reserved')
        body_fields = {'Do': 'merge', 'merge_title_field': title, 'merge_message_field': body,
                       'head_commit_id': subject['head'], 'delete_branch_after_merge': False}
        path = f'/repos/{repository}/pulls/{subject["pull"]}/merge'
        lost = None
        try:
            status, payload = session.merge(path, body_fields)
        except (OSError, http.client.HTTPException) as exc:
            lost, status, payload = exc, None, None
        if lost is not None or status >= 500:
            reason = type(lost).__name__ if lost is not None else f'HTTP {status}'
            ctx.store.transition(key, 'unknown', actor=RECORDER, reason='the merge answer was lost',
                                 detail={'code': 'OUTCOME_UNKNOWN', 'answer': reason}, expected_from='dispatched')
            raise RecorderError('OUTCOME_UNKNOWN', f'the merge of pull request {subject["pull"]} answered {reason}; '
                                f'receipt {key} is unknown', refusal=False, receipt=key)
        if status != 200:
            code = 'HEAD_STALE' if status == 409 else 'MERGE_REFUSED'
            ctx.store.transition(key, 'failed', actor=RECORDER, reason='Gitea refused the merge',
                                 detail={'code': code, 'status': status, 'message': _message(payload)[:200]},
                                 expected_from='dispatched')
            raise RecorderError(code, f'Gitea answered {status} ({_message(payload)[:200]}); nothing was merged; '
                                f'receipt {key} is failed', refusal=False, receipt=key)
        try:
            readback = read_back(session, intent)
        except RecorderError as exc:
            ctx.store.transition(key, 'unknown', actor=RECORDER, reason='the merge did not read back as recorded',
                                 detail={'code': exc.code, 'detail': exc.detail[:300]}, expected_from='dispatched')
            raise RecorderError('OUTCOME_UNKNOWN', f'merged (200), but the read-back failed: {exc.code}: '
                                f'{exc.detail}', refusal=False, receipt=key) from None
        protection = bracket(before, check_protection(ctx, repository, policy.base, 'after-merge'))
        ctx.store.transition(key, 'confirmed', actor=RECORDER, reason='merged and read back',
                             detail={**readback, 'protection': protection}, expected_from='dispatched')
    finally:
        session.close()
    return {'decision': decision, 'receipt': _receipt_report(ctx.store, key), 'merge': readback,
            'protection': protection, 'display': display(decision['decisionId'])}


def bracket(before, after):
    """The protection answers around the merge: equal when the verdict and the digest are the same; when they
    differ, the disclosure PROTECTION_CHANGED_AFTER_MERGE (the merge stands; no refusal)."""
    equal = (after['verdict'], after['digest']) == (before['verdict'], before['digest'])
    out = {'before': before, 'after': after, 'equal': equal}
    if not equal:
        out.update(code='PROTECTION_CHANGED_AFTER_MERGE', disclosure=DISCLOSURES['PROTECTION_CHANGED_AFTER_MERGE'])
    return out


def _write_decision(ctx, decision):
    path = Path(ctx.state_dir) / 'decisions' / f'{decision["decisionId"]}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(D.dumps(decision))


def _receipt_report(store, key):
    reservation = store.get(key)
    events = store.events(key)
    return {'operation_key': key, 'format': RECEIPT_FORMAT, 'state': reservation.state,
            'events': [event.to_state for event in events]}


def read_back(session, intent, *, require_ref=True):
    """The merge as Gitea shows it: the pull request merged by aieh-owner, its merge commit (the protected
    ref when REQUIRE_REF) with the approved head as its second parent and exactly the recorded trailers,
    and the manifest at the merge with the recorded digest."""
    repository, pull = intent['repository'], intent['pull']

    def mismatch(detail):
        return RecorderError('OUTCOME_UNKNOWN', detail, refusal=False)

    status, pr = session.get(f'/repos/{repository}/pulls/{pull}')
    if status != 200 or not isinstance(pr, dict):
        raise mismatch(f'GET pull request {pull} answered {status}')
    merged_by = (pr.get('merged_by') or {}).get('login')
    merge_sha = pr.get('merge_commit_sha')
    if pr.get('merged') is not True or merged_by != OWNER or not isinstance(merge_sha, str) \
            or not D.COMMIT.match(merge_sha):
        raise mismatch(f'pull request {pull}: merged {pr.get("merged")!r}, merged_by {merged_by!r}, merge commit '
                       f'{merge_sha!r}')
    status, branch = session.get(f'/repos/{repository}/branches/{intent["base"]}')
    ref = ((branch or {}).get('commit') or {}).get('id') if status == 200 and isinstance(branch, dict) else None
    if require_ref and ref != merge_sha:
        raise mismatch(f'{intent["base"]} is at {ref!r}, not the merge commit {merge_sha}')
    status, commit = session.get(f'/repos/{repository}/git/commits/{merge_sha}?stat=false&verification=false'
                                 '&files=false')
    if status != 200 or not isinstance(commit, dict):
        raise mismatch(f'GET commit {merge_sha} answered {status}')
    parents = [p.get('sha') for p in commit.get('parents') or [] if isinstance(p, dict)]
    if len(parents) != 2 or parents[1] != intent['approvedHead']:
        raise mismatch(f'{merge_sha} has parents {parents!r}; the approved head {intent["approvedHead"]} must be '
                       'its second parent')
    message = (commit.get('commit') or {}).get('message') or ''
    found = parse_trailers(message)
    if found != intent['trailers']:
        raise mismatch(f'{merge_sha} carries the trailers {found!r}, not those recorded')
    status, blob = session.get(f'/repos/{repository}/raw/{intent["manifest"]}?ref={merge_sha}', raw=True)
    digest = 'sha256:' + hashlib.sha256(blob).hexdigest() if status == 200 and isinstance(blob, bytes) else None
    if digest != intent['digest']:
        raise mismatch(f'{intent["manifest"]} at {merge_sha} is {digest!r}, not {intent["digest"]}')
    return {'ref': ref, 'mergeCommit': merge_sha, 'parents': parents, 'digest': digest, 'mergedBy': merged_by,
            'trailers': found, 'display': display(intent['decision']['decisionId'])}


# ---------------------------------------------------------------------------- resolve


def resolve(ctx, nonce):
    """Resolve the receipt of challenge NONCE by reading Gitea, never by merging: confirmed when the pull
    request was merged by aieh-owner with this decision's trailers, approved head and digest; failed only on a
    definitive read that it was not (merged otherwise, or closed without being merged). An open, unmerged pull
    request leaves the receipt unknown however long ago the merge was sent: the request may still be
    completing on the server, and closing the pull request is an Owner or operator act outside the
    recorder. A receipt left reserved (nothing was sent) becomes failed."""
    _check_context(ctx)
    if not isinstance(nonce, str) or not D.NONCE.match(nonce):
        raise RecorderError('CHALLENGE_INVALID', f'{nonce!r} is not a nonce')
    key = _receipt_key(nonce)
    reservation = ctx.store.get(key)
    if reservation is None:
        raise RecorderError('RECEIPT_MISSING', f'no receipt {key}')
    if reservation.state in ('confirmed', 'failed'):
        return {'receipt': _receipt_report(ctx.store, key), 'changed': False}
    if reservation.state == 'reserved':
        ctx.store.transition(key, 'failed', actor=RECORDER, reason='resolved: the merge was never sent',
                             detail={'code': 'NOT_SENT'}, expected_from='reserved')
        return {'receipt': _receipt_report(ctx.store, key), 'changed': True}
    changed = reservation.state == 'dispatched'
    if changed:
        ctx.store.transition(key, 'unknown', actor=RECORDER, reason='resolved: the merge answer was never recorded',
                             detail={'code': 'OUTCOME_UNKNOWN', 'answer': 'not recorded'}, expected_from='dispatched')
    intent = json.loads(reservation.intent_json)
    session = open_session(ctx)
    try:
        status, pr = session.get(f'/repos/{intent["repository"]}/pulls/{intent["pull"]}')
        if status != 200 or not isinstance(pr, dict):
            raise RecorderError('GITEA_UNAVAILABLE', f'GET pull request {intent["pull"]} answered {status}')
        if pr.get('merged') is True:
            try:
                readback = read_back(session, intent, require_ref=False)
            except RecorderError as exc:
                ctx.store.transition(key, 'failed', actor=RECORDER, reason='resolved: merged, but not by this decision',
                                     detail={'code': 'MERGED_OTHERWISE', 'detail': exc.detail[:300]},
                                     expected_from='unknown')
            else:
                ctx.store.transition(key, 'confirmed', actor=RECORDER, reason='resolved by reading: merged',
                                     detail=readback, expected_from='unknown')
        elif pr.get('state') == 'closed':
            ctx.store.transition(key, 'failed', actor=RECORDER, reason='resolved by reading: closed, not merged',
                                 detail={'code': 'NOT_MERGED', 'state': 'closed'}, expected_from='unknown')
        else:
            return {'receipt': _receipt_report(ctx.store, key), 'changed': changed,
                    'detail': 'still unknown: the pull request is open and not merged, and the outcome stays unknown '
                              'until a read finds it merged or closed (closing it is an Owner or operator act outside '
                              'the recorder); resolve again then'}
    finally:
        session.close()
    return {'receipt': _receipt_report(ctx.store, key), 'changed': True}


# ---------------------------------------------------------------------------- command line


def _read_statement(path):
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise RecorderError('STATEMENT_INVALID', f'{path}: {type(exc).__name__}') from None


def run(args, ctx):
    if args.command == 'prepare':
        return prepare(ctx, args.repository, args.pull, expires_in_minutes=args.expires_in_minutes)
    if args.command == 'record':
        return record(ctx, args.challenge, _read_statement(args.statement), recorded_by=args.recorded_by)
    return resolve(ctx, args.challenge)


def main(argv=None, out=None, err=None, context=None):
    """The command line. CONTEXT (a context manager factory taking the port and the guard) stands in for
    managed_context in tests."""
    parser = argparse.ArgumentParser(prog='authorization_recorder.py', description='Record an Owner authorization '
                                     'and merge the exact operation manifest as aieh-owner (plan leaf P-04.2). Exit '
                                     '0 done, 2 refused, 1 failed or unknown.')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare', help='write the challenge to show the Owner to the recorder\'s state')
    p.add_argument('repository', help='OWNER/NAME of the authorization repository')
    p.add_argument('pull', type=int, help='the pull request number')
    p.add_argument('--expires-in-minutes', type=int, default=DEFAULT_EXPIRY_MINUTES)
    r = sub.add_parser('record', help='record the Owner\'s statement on a challenge and merge')
    r.add_argument('--challenge', help='the nonce prepare printed')
    r.add_argument('--statement', help='{text, attributedTo, channel, reference} as JSON')
    r.add_argument('--recorded-by', required=True)
    s = sub.add_parser('resolve', help='resolve an unknown outcome by reading the pull request; never merges')
    s.add_argument('--challenge', required=True)
    for each in (p, r, s):
        each.add_argument('--port', type=int, help='the Gitea port (default: the managed Gitea\'s host record)')
    args = parser.parse_args(argv)
    out, err = out or sys.stdout, err or sys.stderr
    if out is sys.stdout and hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')
    guard = contract.ExposureGuard()
    result, message, code = None, '', 0
    try:
        with (context or managed_context)(args.port, guard) as ctx:
            result = run(args, ctx)
    except RecorderError as exc:
        message, code = f'authorization-recorder: {exc}\n', 2 if exc.refusal else 1
    except (host.GiteaError, host.paths.PathsError, ValueError) as exc:
        message, code = f'authorization-recorder: {exc}\n', 2
    disclosed = (result or {}).get('protection', {}).get('code') if args.command == 'record' else None
    if disclosed is not None:  # the merge stands (exit 0); the disclosure is said, not only kept in the receipt
        message = f'authorization-recorder: {disclosed} (not a refusal): {DISCLOSURES[disclosed]}.\n'
    text = '' if result is None else json.dumps(result, indent=2, ensure_ascii=False) + '\n'
    # I7: commit ids are token-shaped, so the scan looks for the secrets the command held (its password).
    guard.scan_text('report', text, token_shape=False)
    guard.scan_text('message', message, token_shape=False)
    scan = guard.report()
    guard.clear()
    if scan['found_in']:
        err.write('authorization-recorder: EXPOSURE_FOUND: a secret the command held is in its '
                  + ' and '.join(scan['found_in']) + '\n')
        return 1
    err.write(message)
    out.write(text)
    return code


if __name__ == '__main__':
    sys.exit(main())
