"""The proposal act of the authorization repository (plan leaf E-05.7; decision 0022 point 4).

A deterministic act that opens the pull request the authorization recorder later reads (``prepare``), with
role-bot tokens only. Given the bytes of one operation manifest (``operations/<id>.json``; the four fields the
recorder reads, ``authorization_recorder.read_manifest``) and a repository its context admits, it:

1. reads the proposing bot's and the reviewer bot's tokens from their own credential provider entries
   (``gitea_roles.read_token``: a role's entry only; an entry naming another account is refused) and checks with
   ``GET /token`` that each authenticates as its bot: the builder bot ``aieh-bot-builder`` proposes and the reviewer
   bot ``aieh-bot-reviewer`` approves, as in P-04.2's live exercise (OA-14);
2. refuses an operation id that is not new (``OPERATION_NOT_NEW``), before anything is written: its manifest on
   the protected branch, its branch ``work/<id>`` present, or its manifest in an open pull request;
3. as the proposing bot, adds the manifest with the given bytes on the new branch ``work/<id>`` made from the
   protected branch and opens one pull request from it into the protected branch;
4. reads back what Gitea holds: the pull request (open, unmerged, from ``work/<id>`` of the repository into the
   protected branch, opened by the proposing bot), its files (exactly ``operations/<id>.json``, added) and the
   manifest at its head, whose sha256 must equal the given bytes' (``DIGEST_CHANGED`` otherwise: nothing is
   approved), so that the Owner is never shown bytes other than those given;
5. as the reviewer bot, approves exactly that head.

It never merges: no merge route is in its allowlist (``BOT_ROUTES``, separate from the recorder's read and merge
allowlist), and it never reads ``aieh-owner``'s or the site administrator's entry, never uses basic authentication,
a password or ``sudo``. Each request carries one bot's token in its Authorization header and nothing else. The
command line's context admits exactly the authorization repository (``authorization_recorder.managed_policies``,
decision 0022 point 2); an exercise context admits the S-01.2.2 fixture.

Usage (from the repository root, under the tools interpreter):

    <tools python> -I -B integrations/owner/authorization_proposal.py propose MANIFEST [--port PORT]

Exit status: 0 done (JSON on standard output), 2 refused (nothing written), 1 failed after a write (the report
says what was written; nothing is retried or undone).
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Callable, NamedTuple

HERE = Path(os.path.realpath(__file__)).parent


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


AR = _load('authorization_recorder', HERE / 'authorization_recorder.py')
roles, host = AR.roles, AR.host
contract = host.contract

PROPOSER, REVIEWER = 'builder', 'reviewer'  # the roles of P-04.2's live exercise (OA-14)
BRANCH_PREFIX = 'work/'                     # gitea_roles.PROPOSAL_PATTERN: the bots' branches
OPERATION_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,127}')  # the recorder's operations/<id>.json
TIMEOUT_S = 30.0
PAGE = 'page=1&limit=50'
_SEGMENT = AR._SEGMENT
_REPO = rf'/repos/{_SEGMENT}/{_SEGMENT}'
_MANIFEST = rf'{AR.MANIFEST_DIR}/[a-z0-9][a-z0-9-]{{0,127}}\.json'
# Every request the act can send (method, path); anything else is a ValueError before sending. Separate from the
# recorder's aieh-owner allowlist (authorization_recorder._READS and _MERGE): no merge, no token, no user route.
BOT_ROUTES = tuple((method, re.compile(pattern)) for method, pattern in (
    ('GET', r'^/token$'),
    ('GET', rf'^{_REPO}/branches/[A-Za-z0-9._%-]+$'),
    ('GET', rf'^{_REPO}/raw/{_MANIFEST}\?ref=[0-9a-f]{{40}}$'),
    ('GET', rf'^{_REPO}/pulls\?state=open&{re.escape(PAGE)}$'),
    ('GET', rf'^{_REPO}/pulls/[0-9]+$'),
    ('GET', rf'^{_REPO}/pulls/[0-9]+/files$'),
    ('POST', rf'^{_REPO}/contents/{_MANIFEST}$'),
    ('POST', rf'^{_REPO}/pulls$'),
    ('POST', rf'^{_REPO}/pulls/[0-9]+/reviews$'),
))

REMEDIES = {
    'REPOSITORY_NOT_ADMITTED': 'propose into a repository the context admits: the command line admits the '
                               'authorization repository alone (decision 0022)',
    'MANIFEST_INVALID': 'give a UTF-8 JSON object of at most 64 KiB with operation (a lower-case id), kind, target '
                        'and expiresAt (YYYY-MM-DDTHH:MM:SSZ)',
    'CREDENTIAL_MISSING': 'the bot\'s token is not in the credential provider: gitea_roles.py provision, an Owner act',
    'CREDENTIAL_REFUSED': 'a bot\'s entry must name that bot and hold a Gitea token: repair it with gitea_roles.py '
                          'rotate, an Owner act',
    'BOT_IDENTITY_INVALID': 'Gitea does not accept the bot\'s token as that bot: check it with gitea_roles.py status',
    'OPERATION_NOT_NEW': 'this operation id is on the protected branch, has a branch or is in an open pull request: '
                         'propose a new operation id',
    'PROPOSALS_NOT_READ': 'the open pull requests could not be read whole (50 or more): close the stale ones as an '
                          'operator act, then propose again',
    'GITEA_UNAVAILABLE': 'start Gitea (task gitea:up) and check its answers, then rerun',
    'PROPOSAL_FAILED': 'Gitea refused a write of the proposal: read its message; what was written is in the detail '
                       'and is not undone',
    'PROPOSAL_READBACK': 'the pull request does not read back as proposed: inspect it as an operator; it is not '
                         'approved and is not to be authorized',
    'MANIFEST_NOT_SINGLE': 'the pull request must add exactly one file, operations/<id>.json: inspect it as an '
                           'operator; it is not approved',
    'DIGEST_CHANGED': 'the manifest Gitea holds at the pull request\'s head is not the given bytes: it is not '
                      'approved and the Owner is not to be shown it; close it as an operator and propose again',
}


class ProposalError(Exception):
    """A refusal (nothing written; exit 2) or a failure after a write (exit 1), with a stable code and its remedy."""

    def __init__(self, code, detail, *, refusal=True):
        self.code, self.detail, self.refusal, self.remedy = code, detail, refusal, REMEDIES[code]
        super().__init__(f'{code}: {detail}. Remedy: {self.remedy}.')


class Context(NamedTuple):
    """The credential provider, the Gitea port, the admitted set {repository: authorization_recorder.Policy}
    (managed_policies on the command line, exercise_policies in an exercise) and HTTP: None for
    gitea_host.http_get to 127.0.0.1:PORT, or a callable with its signature (tests)."""
    provider: object
    port: int
    policies: dict
    http: Callable | None = None


class BotSession:
    """One role bot's requests: its token in the Authorization header of the requests in BOT_ROUTES only."""

    def __init__(self, ctx, role, token):
        self._ctx, self.role, self.user, self._token = ctx, role, roles.ROLES[role]['user'], token

    def close(self):
        self._token = None

    def call(self, method, path, body=None, *, raw=False):
        """(status, parsed JSON, or the bytes when RAW). A failure to reach Gitea is GITEA_UNAVAILABLE."""
        if self._token is None or not any(m == method and p.match(path) for m, p in BOT_ROUTES):
            raise ValueError(f'{method} {path} is not a request of the proposal act')
        headers = {'Accept': 'application/json', 'Authorization': 'token ' + self._token}
        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        send = self._ctx.http or host.http_get
        try:
            status, _headers, payload = send(self._ctx.port, '/api/v1' + path, method=method, body=data,
                                             headers=headers, timeout=TIMEOUT_S)
        except OSError as exc:
            raise ProposalError('GITEA_UNAVAILABLE', f'{method} {path}: {type(exc).__name__}',
                                refusal=method == 'GET') from None
        if raw:
            return status, payload
        try:
            return status, json.loads(payload) if payload else None
        except ValueError:
            return status, None


def _message(payload):
    return str(payload.get('message', ''))[:200] if isinstance(payload, dict) else ''


def read_operation(blob):
    """The operation id the manifest BLOB names, and its declared fields; MANIFEST_INVALID otherwise."""
    if not isinstance(blob, bytes):
        raise ProposalError('MANIFEST_INVALID', 'the manifest is not bytes')
    try:
        operation = json.loads(blob.decode('utf-8')).get('operation')
    except (UnicodeDecodeError, ValueError, AttributeError):
        raise ProposalError('MANIFEST_INVALID', 'the manifest is not a UTF-8 JSON object') from None
    if not isinstance(operation, str) or not OPERATION_ID.fullmatch(operation):
        raise ProposalError('MANIFEST_INVALID', f'its operation {operation!r} is not a lower-case id')
    try:
        declared = AR.read_manifest(blob, operation)
    except AR.RecorderError as exc:
        raise ProposalError('MANIFEST_INVALID', exc.detail) from None
    return operation, declared


def bot_session(ctx, role):
    """ROLE's session after its entry and identity checks (GET /token names the role's bot)."""
    try:
        token = roles.read_token(ctx.provider, role)
    except roles.GiteaError as exc:
        raise ProposalError('CREDENTIAL_REFUSED', f'{roles.target(role)!r}: {exc.code}') from None
    if token is None:
        raise ProposalError('CREDENTIAL_MISSING', f'no credential provider entry {roles.target(role)!r}')
    if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{40}', token):
        raise ProposalError('CREDENTIAL_REFUSED', f'{roles.target(role)!r} does not hold a Gitea token')
    session = BotSession(ctx, role, token)
    del token
    status, view = session.call('GET', '/token')
    login = ((view or {}).get('user') or {}).get('login') if isinstance(view, dict) else None
    if status != 200 or login != session.user:
        session.close()
        raise ProposalError('BOT_IDENTITY_INVALID', f'GET /token with the {role} bot\'s token answered {status} as '
                            f'{login!r}, not {session.user}')
    return session


def _require(status, expected, what, payload, *, refusal):
    if status != expected:
        code = 'GITEA_UNAVAILABLE' if refusal else 'PROPOSAL_FAILED'
        raise ProposalError(code, f'{what} answered {status} ({_message(payload)})', refusal=refusal)


def check_new(session, repository, base, operation, manifest, branch):
    """OPERATION_NOT_NEW when the manifest is on the protected branch, the branch exists, or an open pull request
    changes the manifest; returns the protected branch's head."""
    status, view = session.call('GET', f'/repos/{repository}/branches/{urllib.parse.quote(base, safe="")}')
    _require(status, 200, f'GET the protected branch {base}', view, refusal=True)
    base_head = ((view or {}).get('commit') or {}).get('id') if isinstance(view, dict) else None
    if not isinstance(base_head, str) or not re.fullmatch(r'[0-9a-f]{40}', base_head):
        raise ProposalError('GITEA_UNAVAILABLE', f'the protected branch {base} names no commit')
    status, _ = session.call('GET', f'/repos/{repository}/raw/{manifest}?ref={base_head}', raw=True)
    if status == 200:
        raise ProposalError('OPERATION_NOT_NEW', f'{manifest} is on {base} already')
    _require(status, 404, f'GET {manifest} at {base}', None, refusal=True)
    status, _ = session.call('GET', f'/repos/{repository}/branches/{urllib.parse.quote(branch, safe="")}')
    if status == 200:
        raise ProposalError('OPERATION_NOT_NEW', f'the branch {branch} exists already')
    _require(status, 404, f'GET the branch {branch}', None, refusal=True)
    status, pulls = session.call('GET', f'/repos/{repository}/pulls?state=open&{PAGE}')
    _require(status, 200, 'GET the open pull requests', pulls, refusal=True)
    if not isinstance(pulls, list):
        raise ProposalError('GITEA_UNAVAILABLE', 'the open pull requests are not a list')
    if len(pulls) >= 50:
        raise ProposalError('PROPOSALS_NOT_READ', f'{len(pulls)} open pull requests are listed: the list may not be '
                            'whole')
    for pull in pulls:
        number = pull.get('number') if isinstance(pull, dict) else None
        if not isinstance(number, int) or isinstance(number, bool):
            raise ProposalError('GITEA_UNAVAILABLE', 'an open pull request has no number')
        status, files = session.call('GET', f'/repos/{repository}/pulls/{number}/files')
        _require(status, 200, f'GET the files of pull request {number}', files, refusal=True)
        if any(isinstance(f, dict) and f.get('filename') == manifest for f in files or []):
            raise ProposalError('OPERATION_NOT_NEW', f'the open pull request #{number} changes {manifest}')
    return base_head


def read_back(session, repository, base, branch, number, manifest, digest):
    """The pull request as Gitea holds it, against what was proposed: its head; PROPOSAL_READBACK,
    MANIFEST_NOT_SINGLE or DIGEST_CHANGED (nothing approved) otherwise."""
    status, pr = session.call('GET', f'/repos/{repository}/pulls/{number}')
    _require(status, 200, f'GET pull request {number}', pr, refusal=False)
    pr = pr if isinstance(pr, dict) else {}
    side = lambda name: pr.get(name) if isinstance(pr.get(name), dict) else {}  # noqa: E731
    full = lambda name: (side(name).get('repo') or {}).get('full_name')  # noqa: E731
    head = side('head').get('sha')
    seen = {'state': pr.get('state'), 'merged': pr.get('merged'), 'author': (pr.get('user') or {}).get('login'),
            'base': (full('base'), side('base').get('ref')), 'head': (full('head'), side('head').get('ref'))}
    wanted = {'state': 'open', 'merged': False, 'author': session.user, 'base': (repository, base),
              'head': (repository, branch)}
    differences = [f'{k} is {seen[k]!r}, not {v!r}' for k, v in wanted.items() if seen[k] != v]
    if not isinstance(head, str) or not re.fullmatch(r'[0-9a-f]{40}', head):
        differences.append('it names no head commit')
    if differences:
        raise ProposalError('PROPOSAL_READBACK', f'pull request #{number}: ' + '; '.join(differences), refusal=False)
    status, files = session.call('GET', f'/repos/{repository}/pulls/{number}/files')
    _require(status, 200, f'GET the files of pull request {number}', files, refusal=False)
    names = [(f.get('filename'), f.get('status')) if isinstance(f, dict) else (None, None) for f in files or []]
    if names != [(manifest, 'added')]:
        raise ProposalError('MANIFEST_NOT_SINGLE', f'pull request #{number} changes {names!r}, not one added '
                            f'{manifest}', refusal=False)
    status, blob = session.call('GET', f'/repos/{repository}/raw/{manifest}?ref={head}', raw=True)
    _require(status, 200, f'GET {manifest} at the head', None, refusal=False)
    seen_digest = 'sha256:' + hashlib.sha256(blob).hexdigest() if isinstance(blob, bytes) else None
    if seen_digest != digest:
        raise ProposalError('DIGEST_CHANGED', f'{manifest} at the head of pull request #{number} is {seen_digest}, '
                            f'not the given {digest}', refusal=False)
    return head


def propose(ctx, repository, blob):
    """Open one pull request adding operations/<id>.json with the bytes BLOB to REPOSITORY, by the proposing bot,
    read it back and approve it by the reviewer bot. Returns what was proposed (no token); raises ProposalError."""
    if not isinstance(ctx, Context) or not isinstance(ctx.policies, dict) or not ctx.policies:
        raise ValueError('a proposal context names the repositories it admits')
    if not isinstance(repository, str) or repository not in ctx.policies:
        raise ProposalError('REPOSITORY_NOT_ADMITTED', f'{repository!r} is not one of {sorted(ctx.policies)}')
    base = ctx.policies[repository].base
    operation, declared = read_operation(blob)
    manifest, branch = f'{AR.MANIFEST_DIR}/{operation}.json', f'{BRANCH_PREFIX}{operation}'
    digest = 'sha256:' + hashlib.sha256(blob).hexdigest()
    proposer = bot_session(ctx, PROPOSER)
    reviewer = None
    written = []
    try:
        reviewer = bot_session(ctx, REVIEWER)
        base_head = check_new(proposer, repository, base, operation, manifest, branch)
        status, body = proposer.call('POST', f'/repos/{repository}/contents/{manifest}', {
            'content': base64.b64encode(blob).decode('ascii'), 'message': f'Propose operation {operation}',
            'branch': base, 'new_branch': branch})
        _require(status, 201, f'adding {manifest} on {branch}', body, refusal=False)
        written.append(f'the branch {branch} with {manifest}')
        status, pull = proposer.call('POST', f'/repos/{repository}/pulls', {
            'head': branch, 'base': base, 'title': f'Operation {operation}',
            'body': f'Proposes {manifest} ({digest}) for an Owner authorization.'})
        _require(status, 201, 'opening the pull request', pull, refusal=False)
        number = pull.get('number') if isinstance(pull, dict) else None
        if not isinstance(number, int) or isinstance(number, bool):
            raise ProposalError('PROPOSAL_READBACK', 'the opened pull request has no number', refusal=False)
        written.append(f'pull request #{number}')
        head = read_back(proposer, repository, base, branch, number, manifest, digest)
        status, review = reviewer.call('POST', f'/repos/{repository}/pulls/{number}/reviews', {
            'event': 'APPROVED', 'body': f'Approves {manifest} ({digest}) as proposed.', 'commit_id': head})
        _require(status, 200, f'approving pull request #{number}', review, refusal=False)
        reviewed = review.get('commit_id') if isinstance(review, dict) else None
        if reviewed not in (None, head):
            raise ProposalError('PROPOSAL_READBACK', f'the approval is of {reviewed}, not the head {head}',
                                refusal=False)
        written.append(f'the approval of #{number}')
    except ProposalError as exc:
        if written:
            exc.detail += f'; written before it, not undone: {", ".join(written)}'
            exc.args = (f'{exc.code}: {exc.detail}. Remedy: {exc.remedy}.',)
        raise
    finally:
        proposer.close()
        if reviewer is not None:
            reviewer.close()
    return {'repository': repository, 'operation': operation, 'kind': declared['kind'], 'manifest': manifest,
            'digest': digest, 'branch': branch, 'base': base, 'baseHead': base_head, 'pull': number, 'head': head,
            'proposedBy': proposer.user, 'approvedBy': reviewer.user}


# ---------------------------------------------------------------------------- command line


@contextlib.contextmanager
def managed_context(port=None, guard=None):
    """The command line's context: the platform's credential provider (held by GUARD for the I7 scan), the managed
    Gitea's port from its host record, and exactly the authorization repository admitted."""
    if port is None:
        port = host.read_host_record(host.layout(host.paths.resolve()))['port']
    provider = host.credential_provider()
    if guard is not None:
        provider = contract.WatchedProvider(provider, guard)
    yield Context(provider, port, AR.managed_policies())


def main(argv=None, out=None, err=None, context=None):
    """The command line. CONTEXT (a context manager factory taking the port and the guard) stands in for
    managed_context in tests."""
    parser = argparse.ArgumentParser(prog='authorization_proposal.py', description='Open the pull request of one '
                                     'operation manifest in the authorization repository with bot tokens only, read it '
                                     'back and approve it (plan leaf E-05.7); never merges. Exit 0 done, 2 refused, 1 '
                                     'failed after a write.')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('propose', help='propose operations/<id>.json with the bytes of MANIFEST')
    p.add_argument('manifest', help='the manifest file; its bytes are proposed exactly')
    p.add_argument('--repository', default=AR.AUTHORIZATION_REPOSITORY, help='OWNER/NAME (default: the authorization '
                   'repository, the one the command line admits)')
    p.add_argument('--port', type=int, help='the Gitea port (default: the managed Gitea\'s host record)')
    args = parser.parse_args(argv)
    out, err = out or sys.stdout, err or sys.stderr
    if out is sys.stdout and hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')
    guard = contract.ExposureGuard()
    result, message, code = None, '', 0
    try:
        blob = Path(args.manifest).read_bytes()
        with (context or managed_context)(args.port, guard) as ctx:
            result = propose(ctx, args.repository, blob)
    except ProposalError as exc:
        message, code = f'authorization-proposal: {exc}\n', 2 if exc.refusal else 1
    except OSError as exc:
        message, code = f'authorization-proposal: the manifest {args.manifest}: {type(exc).__name__}\n', 2
    except (host.GiteaError, host.paths.PathsError, ValueError) as exc:
        message, code = f'authorization-proposal: {exc}\n', 2
    text = '' if result is None else json.dumps(result, indent=2, ensure_ascii=False) + '\n'
    # I7: commit ids are token-shaped, so the scan looks for the secrets the command held (the bots' tokens).
    guard.scan_text('report', text, token_shape=False)
    guard.scan_text('message', message, token_shape=False)
    scan = guard.report()
    guard.clear()
    if scan['found_in']:
        err.write('authorization-proposal: EXPOSURE_FOUND: a secret the command held is in its '
                  + ' and '.join(scan['found_in']) + '\n')
        return 1
    err.write(message)
    out.write(text)
    return code


if __name__ == '__main__':
    sys.exit(main())
