"""Segregated Gitea role credentials and their authorization fixture (plan leaf S-01.2.2; decisions 0007,
0009 and 0010).

One Gitea account per role of policy/role-tokens.json that holds a Gitea credential: the planner, the
builder and the reviewer (cred-gitea-bot-*), and the authorization verifier's read-only identity
(cred-verifier-read). Each is created with Gitea's own CLI as a restricted, non-administrator account of
Gitea's Bot type (`admin user create --user-type Bot --restricted`, no password: it cannot sign in
interactively). Each role's token is minted with `admin user generate-access-token --raw --scopes ...`
using the narrowest scopes Gitea 28.3.0 can express for the role; the CLI's standard output is captured
in memory and written by CredWriteW (gitea_host.CredentialStore) into one generic Windows Credential
Manager entry, `AIEH Gitea bot <role>`. A token is never printed, logged, written to a file or put on a
command line; reports carry a fingerprint (a sha256 prefix) only.

The fixture is Gitea administration (op-gitea-administration): a disposable organization with one
private repository, its collaborators and branch protection. Gitea's CLI cannot create organizations,
collaborators or protection rules, so `fixture` mints a short-lived site-administrator token with the
CLI (narrowest scopes for those routes), holds it in memory, applies the fixture through the API, and
revokes the token with Gitea's own `DELETE /api/v1/token` before it returns, in every outcome; it then
checks that the token no longer authenticates. The site administrator's password is never used.
Gitea 28.3.0 refuses every API call of an account that must still change its password, the token's
own DELETE /api/v1/token included, so `fixture` works only after the Owner's first sign-in and
`task gitea:finish-first-login`; before that it stops at its first call (ADMIN_FIRST_LOGIN_PENDING)
and reports whether the token it minted could be revoked.

  python -I -B integrations/gitea/gitea_roles.py provision      # the bot accounts and missing tokens
  python -I -B integrations/gitea/gitea_roles.py fixture        # organization, repository, protection
  python -I -B integrations/gitea/gitea_roles.py rotate ROLE    # revoke a token, prove it fails closed, re-issue
  python -I -B integrations/gitea/gitea_roles.py status         # entries, fingerprints, token checks

Exit 0 done, 1 failed, 2 refused (a stable code). Windows only (Credential Manager).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

HERE = Path(os.path.realpath(__file__)).parent


def _load_host():
    if (module := sys.modules.get('aieh_gitea_host')) is None:
        spec = importlib.util.spec_from_file_location('aieh_gitea_host', HERE / 'gitea_host.py')
        module = sys.modules['aieh_gitea_host'] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


host = _load_host()
GiteaError = host.GiteaError

TARGET_PREFIX = 'AIEH Gitea bot '
# The narrowest Gitea 28.3.0 scopes per role (see policy/role-tokens.json and the S-01.2.2 evidence).
# Gitea's token scopes are categorical (repository, issue, organization, user, admin, ...), never per
# repository, branch or path: the per-repository and per-branch limits come from the account's
# collaborator permission and the branch protection of the fixture, not from the token.
ROLES = {
    'planner': {'user': host.BOT_ACCOUNTS['planner'], 'scopes': ('write:repository',),
                'credential': 'cred-gitea-bot-planner', 'permission': 'write'},
    'builder': {'user': host.BOT_ACCOUNTS['builder'], 'scopes': ('write:repository',),
                'credential': 'cred-gitea-bot-builder', 'permission': 'write'},
    'reviewer': {'user': host.BOT_ACCOUNTS['reviewer'], 'scopes': ('write:repository',),
                 'credential': 'cred-gitea-bot-reviewer', 'permission': 'read'},
    'verifier': {'user': host.BOT_ACCOUNTS['verifier'], 'scopes': ('read:repository',),
                 'credential': 'cred-verifier-read', 'permission': 'read'},
}
FIXTURE_ORG, FIXTURE_REPO, DEFAULT_BRANCH = 'aieh-authz-fixture', 'authz', 'main'
PROPOSAL_PATTERN = 'work/*'
# Organization and repository creation, collaborators and branch protection; nothing under /admin.
ADMIN_SCOPES = ('write:organization', 'write:repository')
TOKEN_SHAPE = re.compile(rb'[0-9a-f]{40}')


def now_stamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def target(role: str) -> str:
    return TARGET_PREFIX + role


def fingerprint(token: str) -> str:
    """What records carry instead of a token: a 16-hex-digit prefix of its sha256."""
    return 'sha256:' + hashlib.sha256(token.encode('ascii')).hexdigest()[:16]


def redact(text: str) -> str:
    """Remove anything shaped like a Gitea token from text that is about to be reported."""
    return re.sub(r'[0-9a-f]{40}', '<redacted>', text)


def protection_rules() -> list[dict]:
    """The fixture's branch protection, in priority order. The default branch: nobody pushes, nobody
    force-pushes, only aieh-owner merges, one approval from the reviewer bot is required, and the site
    administrator's merge override is blocked. work/*: the planner and builder bots push. Every other
    branch name: nobody pushes. Protected branches cannot be deleted."""
    reviewer, planner, builder = (ROLES[r]['user'] for r in ('reviewer', 'planner', 'builder'))
    return [
        {'rule_name': DEFAULT_BRANCH, 'priority': 1, 'enable_push': False, 'enable_force_push': False,
         'enable_merge_whitelist': True, 'merge_whitelist_usernames': [host.OWNER],
         'block_admin_merge_override': True, 'required_approvals': 1, 'enable_approvals_whitelist': True,
         'approvals_whitelist_username': [reviewer], 'block_on_rejected_reviews': True},
        {'rule_name': PROPOSAL_PATTERN, 'priority': 2, 'enable_push': True, 'enable_push_whitelist': True,
         'push_whitelist_usernames': [planner, builder], 'enable_force_push': False,
         'enable_merge_whitelist': True, 'merge_whitelist_usernames': [host.OWNER]},
        {'rule_name': '**', 'priority': 3, 'enable_push': False, 'enable_force_push': False,
         'enable_merge_whitelist': True, 'merge_whitelist_usernames': [host.OWNER]},
    ]


def collaborators() -> dict:
    """Repository permission per account: the bots per role; the Owner account writes, because Gitea
    admits only accounts with write access to a merge allowlist."""
    return {**{spec['user']: spec['permission'] for spec in ROLES.values()}, host.OWNER: 'write'}


# ---------------------------------------------------------------- the Gitea CLI


class Cli:
    """The pinned Gitea CLI against the managed instance, output captured in memory only."""

    def __init__(self, lay, pinned, run: Callable = subprocess.run):
        self.lay, self.pinned, self.run = lay, pinned, run

    def __call__(self, *args: str):
        with host.verified_binary(self.lay, self.pinned['sha256']) as binary:
            return host.run_quiet(host.gitea_argv(binary, self.lay, *args), host.child_env(self.lay),
                                  self.lay.home, self.run)

    def users(self) -> dict:
        with host.verified_binary(self.lay, self.pinned['sha256']) as binary:
            return host.gitea_users(binary, self.lay, self.run)

    def create_bot(self, user: str) -> None:
        result = self('admin', 'user', 'create', '--username', user, '--email', f'{user}@{host.EMAIL_DOMAIN}',
                      '--user-type', 'Bot', '--restricted')
        if result.returncode != 0:
            raise GiteaError('BOT_CREATE_FAILED', f'gitea admin user create {user} exited {result.returncode}: '
                             + redact(result.stderr.decode('utf-8', 'replace').strip()[-300:]), refusal=False)

    def mint(self, user: str, name: str, scopes) -> str:
        """A new token for user, from Gitea's --raw output; never shown. Failure reports the exit code and
        Gitea's error text with anything token-shaped removed."""
        result = self('admin', 'user', 'generate-access-token', '--username', user, '--token-name', name,
                      '--scopes', ','.join(scopes), '--raw')
        found = TOKEN_SHAPE.findall(result.stdout)
        if result.returncode != 0 or len(found) != 1 or result.stdout.strip() != found[0]:
            raise GiteaError('TOKEN_MINT_FAILED', f'generate-access-token for {user} exited {result.returncode} '
                             f'({len(found)} tokens seen; output withheld): '
                             + redact(result.stderr.decode('utf-8', 'replace').strip()[-300:]), refusal=False)
        token = found[0].decode('ascii')
        del found, result
        return token


# ---------------------------------------------------------------- the API


class Api:
    """JSON over HTTP to 127.0.0.1:<port>/api/v1 with an optional token (Authorization: token ...)."""

    def __init__(self, port: int, token: str | None = None, http: Callable = None):
        self.port, self.token, self.http = port, token, http or host.http_get

    def call(self, method: str, path: str, body=None, headers=None) -> tuple[int, object]:
        sent = {'Accept': 'application/json', **(headers or {})}
        if self.token is not None:
            sent['Authorization'] = 'token ' + self.token
        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            sent['Content-Type'] = 'application/json'
        status, _headers, raw = self.http(self.port, '/api/v1' + path, method=method, body=data, headers=sent,
                                          timeout=30.0)
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, raw.decode('utf-8', 'replace')[:300]


def require(status: int, expected, what: str, payload=None) -> None:
    if status not in (expected if isinstance(expected, tuple) else (expected,)):
        message = payload.get('message') if isinstance(payload, dict) else payload
        raise GiteaError('API_UNEXPECTED', f'{what}: HTTP {status} ({redact(str(message))[:300]})', refusal=False)


def revoke_current(port: int, token: str, http: Callable = None) -> dict:
    """Gitea 28's DELETE /api/v1/token deletes the token that authenticates the call; then the same
    token must be refused (401) on its next call."""
    api = Api(port, token, http)
    deleted, _ = api.call('DELETE', '/token')
    after, _ = api.call('GET', '/token')
    return {'delete_status': deleted, 'next_call_status': after, 'revoked': deleted == 204 and after == 401}


# ---------------------------------------------------------------- commands


def context(store=None, run: Callable = subprocess.run):
    res = host.paths.resolve()
    lay, pinned = host.layout(res), host.pin()
    port = host.read_host_record(lay)['port']
    if not host.healthy(port):
        raise GiteaError('NOT_RUNNING', 'Gitea does not answer; run task gitea:up')
    return lay, pinned, port, store or host.CredentialStore(), Cli(lay, pinned, run)


def read_token(store, role: str) -> str | None:
    entry = store.read(target(role))
    if entry is None:
        return None
    user, blob = entry
    if user != ROLES[role]['user']:
        raise GiteaError('ENTRY_MISMATCH', f'{target(role)!r} names {user!r}, not {ROLES[role]["user"]!r}')
    return host.password_bytes(blob).decode('ascii')


def store_token(store, role: str, token: str, port: int) -> None:
    spec = ROLES[role]
    store.write(target(role), spec['user'], token.encode('utf-16-le'),
                f'Gitea access token of {spec["user"]} ({role}; scopes {",".join(spec["scopes"])}) on the AIEH '
                f'Gitea at http://{host.LOOPBACK}:{port}/ (plan leaf S-01.2.2). Bootstrap custody: the Owner '
                'account; the management dispatcher is its planned custodian.')


def token_check(port: int, token: str, http: Callable = None) -> dict:
    """What Gitea says about a token: GET /api/v1/token (its own name and scopes)."""
    status, body = Api(port, token, http).call('GET', '/token')
    report = {'status': status}
    if status == 200 and isinstance(body, dict):
        report.update(name=body.get('name'), scopes=sorted(body.get('scopes') or []))
    return report


def provision(store=None, run: Callable = subprocess.run, roles=None, http: Callable = None,
              ctx=None) -> dict:
    """Create each missing bot account, then mint and store a token for each role whose entry is
    absent. An existing entry is kept (rotate replaces one)."""
    lay, pinned, port, store, cli = ctx or context(store, run)
    roles = list(roles or ROLES)
    users = cli.users()
    for role in roles:
        user = ROLES[role]['user']
        if user in users and (users[user]['admin'] or users[user].get('type') != 'Bot'):
            raise GiteaError('ACCOUNT_NOT_A_BOT', f'{user} exists but is not a non-administrator Bot account')
    created = []
    for role in roles:
        if ROLES[role]['user'] not in users:
            cli.create_bot(ROLES[role]['user'])
            created.append(ROLES[role]['user'])
    after = cli.users()
    report = {'created_accounts': created, 'accounts': {}, 'tokens': {}}
    for role in roles:
        spec = ROLES[role]
        report['accounts'][spec['user']] = after.get(spec['user'])
        token = read_token(store, role)
        minted = token is None
        if minted:
            token = cli.mint(spec['user'], f'aieh-{role}-{now_stamp()}', spec['scopes'])
            store_token(store, role, token, port)
        report['tokens'][role] = {'user': spec['user'], 'entry': target(role), 'minted': minted,
                                  'requested_scopes': list(spec['scopes']), 'fingerprint': fingerprint(token),
                                  'check': token_check(port, token, http)}
        del token
    return report


def apply_fixture(api: Api) -> list[dict]:
    """Idempotent: create what is missing, update what exists. Returns each call (method, path, status)."""
    actions = []

    def call(method, path, body=None, expected=(200, 201, 204)):
        status, payload = api.call(method, path, body)
        actions.append({'method': method, 'path': path, 'status': status})
        require(status, expected, f'{method} {path}', payload)
        return status, payload

    if api.call('GET', f'/orgs/{FIXTURE_ORG}')[0] == 404:
        call('POST', '/orgs', {'username': FIXTURE_ORG, 'visibility': 'private',
                               'repo_admin_change_team_access': False,
                               'description': 'Disposable authorization fixture (plan leaf S-01.2.2)'})
    repo = f'/repos/{FIXTURE_ORG}/{FIXTURE_REPO}'
    if api.call('GET', repo)[0] == 404:
        call('POST', f'/orgs/{FIXTURE_ORG}/repos', {'name': FIXTURE_REPO, 'private': True, 'auto_init': True,
                                                    'default_branch': DEFAULT_BRANCH, 'readme': 'Default'})
    for user, permission in collaborators().items():
        call('PUT', f'{repo}/collaborators/{user}', {'permission': permission})
    status, existing = call('GET', f'{repo}/branch_protections')
    names = {rule.get('rule_name') for rule in existing or []}
    for rule in protection_rules():
        name = rule['rule_name']
        if name in names:
            body = {k: v for k, v in rule.items() if k != 'rule_name'}
            call('PATCH', f'{repo}/branch_protections/{name}', body)
        else:
            call('POST', f'{repo}/branch_protections', rule)
    return actions


def read_fixture(api: Api) -> dict:
    """The fixture as Gitea reports it: collaborator permissions and protection rules."""
    repo = f'/repos/{FIXTURE_ORG}/{FIXTURE_REPO}'
    status, info = api.call('GET', repo)
    require(status, 200, f'GET {repo}', info)
    perms = {}
    for user in collaborators():
        status, body = api.call('GET', f'{repo}/collaborators/{user}/permission')
        perms[user] = body.get('permission') if status == 200 and isinstance(body, dict) else f'HTTP {status}'
    status, rules = api.call('GET', f'{repo}/branch_protections')
    require(status, 200, f'GET {repo}/branch_protections', rules)
    keep = ('rule_name', 'priority', 'enable_push', 'enable_push_whitelist', 'push_whitelist_usernames',
            'enable_force_push', 'enable_merge_whitelist', 'merge_whitelist_usernames',
            'block_admin_merge_override', 'required_approvals', 'enable_approvals_whitelist',
            'approvals_whitelist_username', 'block_on_rejected_reviews')
    return {'repository': {'full_name': info.get('full_name'), 'private': info.get('private'),
                           'default_branch': info.get('default_branch')},
            'collaborator_permissions': perms,
            'branch_protections': [{k: r.get(k) for k in keep} for r in rules or []]}


def fixture(store=None, run: Callable = subprocess.run, http: Callable = None, ctx=None,
            probe: Callable | None = None) -> dict:
    """Mint a short-lived site-administrator token, apply and read back the fixture, optionally run
    probe(api) with it (the admin merge-override check), then revoke the token in every outcome."""
    lay, pinned, port, store, cli = ctx or context(store, run)
    users = cli.users()
    missing = sorted({spec['user'] for spec in ROLES.values()} - set(users))
    if missing:
        raise GiteaError('BOTS_MISSING', f'run provision first: {missing}')
    if host.OWNER not in users:
        raise GiteaError('OWNER_MISSING', f'{host.OWNER} does not exist; run task gitea:identities')
    name = f'aieh-s0122-fixture-{now_stamp()}'
    token = cli.mint(host.SITE_ADMIN, name, ADMIN_SCOPES)
    report = {'admin_token': {'user': host.SITE_ADMIN, 'name': name, 'scopes': list(ADMIN_SCOPES),
                              'fingerprint': fingerprint(token), 'minted_by': 'gitea admin user generate-access-token'}}
    failure = None
    try:
        api = Api(port, token, http)
        status_code, body = api.call('GET', '/token')
        report['admin_token']['check'] = {'status': status_code}
        if status_code != 200:
            message = redact(str(body.get('message') if isinstance(body, dict) else body))[:200]
            code = 'ADMIN_FIRST_LOGIN_PENDING' if 'change your password' in message else 'ADMIN_TOKEN_UNUSABLE'
            raise GiteaError(code, f'the site administrator token gets HTTP {status_code} ({message})', refusal=False)
        report['actions'] = apply_fixture(api)
        report['fixture'] = read_fixture(api)
        if probe is not None:
            report['probe'] = probe(api)
    except Exception as exc:  # every outcome reports the revocation below
        failure = exc
    finally:
        revocation = revoke_current(port, token, http)
        del token
    report['admin_token']['revocation'] = revocation
    if failure is not None or not revocation['revoked']:
        code, detail = (failure.code, failure.detail) if isinstance(failure, GiteaError) else (
            'ADMIN_TOKEN_NOT_REVOKED' if failure is None else 'FIXTURE_FAILED',
            '' if failure is None else f'{type(failure).__name__}: {redact(str(failure))[:300]}')
        tail = '' if revocation['revoked'] else (
            f'; NOT REVOKED: delete the token {name!r} in the site administrator\'s Settings > Applications')
        raise GiteaError(code, f'{detail}; admin token {name!r} revocation {json.dumps(revocation)}{tail}',
                         refusal=False)
    return report


def rotate(role: str, store=None, run: Callable = subprocess.run, http: Callable = None, ctx=None) -> dict:
    """The revocation contract once: revoke the role's token through DELETE /api/v1/token, prove its
    next call fails closed, mint a new one and replace the entry, prove the new one works."""
    if role not in ROLES:
        raise GiteaError('ROLE_UNKNOWN', f'{role!r} is not one of {sorted(ROLES)}')
    lay, pinned, port, store, cli = ctx or context(store, run)
    old = read_token(store, role)
    if old is None:
        raise GiteaError('ENTRY_MISSING', f'{target(role)!r} does not exist; run provision')
    report = {'role': role, 'user': ROLES[role]['user'], 'entry': target(role), 'old_fingerprint': fingerprint(old),
              'old_before': token_check(port, old, http)}
    report['revocation'] = revoke_current(port, old, http)
    report['old_on_repository_read'] = Api(port, old, http).call('GET', f'/repos/{FIXTURE_ORG}/{FIXTURE_REPO}')[0]
    del old
    if not report['revocation']['revoked']:
        raise GiteaError('REVOCATION_FAILED', json.dumps(report), refusal=False)
    new = cli.mint(ROLES[role]['user'], f'aieh-{role}-{now_stamp()}', ROLES[role]['scopes'])
    store.delete(target(role))
    store_token(store, role, new, port)
    report.update(new_fingerprint=fingerprint(new), new_check=token_check(port, new, http))
    del new
    return report


def status(store=None, run: Callable = subprocess.run, http: Callable = None, ctx=None) -> dict:
    lay, pinned, port, store, cli = ctx or context(store, run)
    users = cli.users()
    report = {}
    for role, spec in ROLES.items():
        token = read_token(store, role)
        report[role] = {'user': spec['user'], 'account': users.get(spec['user']), 'entry': target(role),
                        'entry_present': token is not None}
        if token is not None:
            report[role].update(fingerprint=fingerprint(token), check=token_check(port, token, http))
        del token
    return report


def admin_merge_probe(store, port: int, http: Callable = None) -> Callable:
    """The probe fixture() runs with the admin token: a proposal PR from the builder bot, then the site
    administrator's merge and force-merge, both of which branch protection must refuse."""
    def probe(api: Api) -> dict:
        builder = Api(port, read_token(store, 'builder'), http)
        repo = f'/repos/{FIXTURE_ORG}/{FIXTURE_REPO}'
        branch = f'work/admin-probe-{now_stamp().lower()}'
        status, body = builder.call('POST', f'{repo}/contents/probe-{branch.rsplit("-", 1)[1]}.txt', {
            'content': 'YWRtaW4gbWVyZ2UtcHJvYmUK', 'message': 'admin merge-override probe',
            'branch': DEFAULT_BRANCH, 'new_branch': branch})
        result = {'builder_creates_proposal_branch': status}
        require(status, 201, 'builder creates the probe branch', body)
        status, pull = builder.call('POST', f'{repo}/pulls', {'head': branch, 'base': DEFAULT_BRANCH,
                                                              'title': 'admin merge-override probe'})
        require(status, 201, 'builder opens the probe PR', pull)
        number = pull['number']
        before = api.call('GET', f'{repo}/branches/{DEFAULT_BRANCH}')[1]['commit']['id']
        result.update(pull=number,
                      admin_merge=api.call('POST', f'{repo}/pulls/{number}/merge', {'Do': 'merge'})[0],
                      admin_force_merge=api.call('POST', f'{repo}/pulls/{number}/merge',
                                                 {'Do': 'merge', 'force_merge': True})[0])
        after = api.call('GET', f'{repo}/branches/{DEFAULT_BRANCH}')[1]['commit']['id']
        result['default_branch_unchanged'] = before == after
        result['pull_merged'] = api.call('GET', f'{repo}/pulls/{number}')[1].get('merged')
        result['builder_closes_probe_pr'] = builder.call('PATCH', f'{repo}/pulls/{number}', {'state': 'closed'})[0]
        return result
    return probe


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='gitea_roles.py', description='Segregated Gitea role credentials and '
                                     'the authorization fixture (S-01.2.2). Exit 0 done, 1 failed, 2 refused.')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('provision', help='create the bot accounts and mint the tokens that are missing')
    fix = sub.add_parser('fixture', help='apply the fixture with a short-lived, revoked site-admin token')
    fix.add_argument('--admin-merge-probe', action='store_true',
                     help='also check that the site administrator cannot merge or force-merge a proposal PR')
    rot = sub.add_parser('rotate', help='revoke a role token, prove it fails closed, re-issue it')
    rot.add_argument('role', choices=sorted(ROLES))
    sub.add_parser('status', help='entries, fingerprints and what Gitea says of each token; changes nothing')
    args = parser.parse_args(argv)
    out = sys.stdout
    if hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')
    if os.name != 'nt':
        sys.stderr.write('gitea-roles: REFUSED: Windows Credential Manager custody is implemented for Windows only\n')
        return 2
    try:
        if args.command == 'provision':
            report = provision()
        elif args.command == 'fixture':
            ctx = context()
            probe = admin_merge_probe(ctx[3], ctx[2]) if args.admin_merge_probe else None
            report = fixture(ctx=ctx, probe=probe)
        elif args.command == 'rotate':
            report = rotate(args.role)
        else:
            report = status()
    except host.paths.PathsError as exc:
        sys.stderr.write(f'gitea-roles: {exc}\n')
        return 2
    except GiteaError as exc:
        sys.stderr.write(f'gitea-roles: {redact(str(exc))}\n')
        return 2 if exc.refusal else 1
    out.write(redact(json.dumps(report, indent=2, default=str)) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
