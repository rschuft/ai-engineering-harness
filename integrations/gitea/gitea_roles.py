"""Segregated Gitea role credentials and their authorization fixture (plan leaf S-01.2.2; decisions 0007,
0009 and 0010).

One Gitea account per role of policy/role-tokens.json that holds a Gitea credential: the planner, the
builder and the reviewer (cred-gitea-bot-*), the authorization verifier's read-only identity
(cred-verifier-read), and the protection auditor (cred-gitea-protection-audit; Owner decision OA-16): a
read:repository token of an account that is a repository administrator of the fixture only, which the
authorization recorder's protection check (protection_check.py) uses to read the branch protection rules
that Gitea 28.3.0 serves to repository administrators only. Each is created with Gitea's own CLI as a restricted, non-administrator account of
Gitea's Bot type (`admin user create --user-type Bot --restricted`, no password: it cannot sign in
interactively). Each role's token is minted with `admin user generate-access-token --raw --scopes ...`
using the narrowest scopes Gitea 28.3.0 can express for the role; the CLI's standard output is captured
in memory and written by the credential provider into one entry, `AIEH Gitea bot <role>` (on Windows a
generic Credential Manager entry, CredWriteW). The entry is checked against the Windows credential field
limits before the token is minted (check_entry; nothing is written to check it), and a store that fails
anyway after the mint makes the new token revoke itself once (store_minted). A token is never printed,
logged, written to a file or put on a command line; reports carry a fingerprint (a sha256 prefix) only.
Entries are reached through gitea_host's CredentialProvider, which the harness's factory chooses
(integrations/credentials/credential_provider.py, plan leaf F-06.3).

The fixture is Gitea administration (op-gitea-administration): a disposable organization with one
private repository, its merge settings, its collaborators and branch protection. Gitea's CLI cannot create organizations,
collaborators or protection rules, so `fixture` acts through the API as the site administrator, by HTTP
basic authentication with the harness-held password that `task gitea:finalize-credentials` stored
(Owner directive of 2026-11-07), read from the credential provider into memory. No token is minted for
administration, and the report shows that the administrator holds none afterwards. `escape-probe` acts the
same way, separately, to create the organization's second repository, escape-probe: private, empty and with
no collaborators, whose rules the protection auditor's live negative test must be refused; it never addresses
the fixture repository, and it refuses an existing escape-probe in any other state.

  python -I -B integrations/gitea/gitea_roles.py provision      # the bot accounts and missing tokens
  python -I -B integrations/gitea/gitea_roles.py fixture        # organization, repository, protection
  python -I -B integrations/gitea/gitea_roles.py escape-probe   # the auditor's escape-probe repository
  python -I -B integrations/gitea/gitea_roles.py rotate ROLE    # revoke a token, prove it fails closed, re-issue
  python -I -B integrations/gitea/gitea_roles.py retire ROLE    # revoke a token, prove it fails closed, drop the entry
  python -I -B integrations/gitea/gitea_roles.py status         # entries, fingerprints, token checks

These are the role credentials' realization of the lifecycle contract's credential verbs (plan leaf
F-06.2): provision, rotate and retire. Every act ends with the I7 no-exposure scan of what it shows. Every
rotate and retire act writes an integration-store receipt (fingerprint, role, trigger, revoker, affected
attempts: decision 0007 point 5; fingerprints only) into <state>/integration/integration.sqlite of the
managed root, reserved before anything changes and read back at the end; an act without a receipt read back
fails (CREDENTIAL_RECEIPT_UNREAD) (plan leaf F-06.3).

Exit 0 done, 1 failed, 2 refused (a stable code). Windows only (Credential Manager).
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
import subprocess
import sys
import urllib.parse
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
    # Owner decision OA-16: repository-administrator collaboration on the fixture only, so that Gitea serves
    # it the branch protection rules (reqAdmin), and a token that can only read (read:repository: every
    # POST, PUT, PATCH and DELETE under /repos needs the write scope). Its custodian is the authorization
    # recorder, whose protection check alone reads the entry (decision 0012 point 6, Proposed).
    'protection-audit': {'user': host.BOT_ACCOUNTS['protection-audit'], 'scopes': ('read:repository',),
                         'credential': 'cred-gitea-protection-audit', 'permission': 'admin',
                         'custodian': 'the authorization recorder (its protection check)'},
}
FIXTURE_ORG, FIXTURE_REPO, DEFAULT_BRANCH = 'aieh-authz-fixture', 'authz', 'main'
# A second repository of the fixture organization that no account is a collaborator of: the live negative test
# of the protection auditor (test_protection_audit_live.py) reads its rules and must be refused.
ESCAPE_PROBE_REPO = 'escape-probe'
PROPOSAL_PATTERN = 'work/*'
TOKEN_LENGTH = 40  # a Gitea access token: 40 hex digits
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


# Every field of Gitea 28.3.0's branch protection API view (modules/structs/repo_branch.go BranchProtection,
# in its order) but branch_name (a deprecated alias of rule_name), created_at and updated_at: 34 fields,
# each of which CreateBranchProtectionOption and EditBranchProtectionOption (rule_name excepted) accept.
PROTECTION_FIELDS = (
    'rule_name', 'priority', 'enable_push', 'enable_push_whitelist', 'push_whitelist_usernames',
    'push_whitelist_teams', 'push_whitelist_deploy_keys', 'enable_force_push', 'enable_force_push_allowlist',
    'force_push_allowlist_usernames', 'force_push_allowlist_teams', 'force_push_allowlist_deploy_keys',
    'enable_merge_whitelist', 'merge_whitelist_usernames', 'merge_whitelist_teams', 'enable_bypass_allowlist',
    'bypass_allowlist_usernames', 'bypass_allowlist_teams', 'enable_status_check', 'status_check_contexts',
    'required_approvals', 'enable_approvals_whitelist', 'approvals_whitelist_username', 'approvals_whitelist_teams',
    'block_on_rejected_reviews', 'block_on_official_review_requests', 'block_on_codeowner_reviews',
    'block_on_outdated_branch', 'dismiss_stale_approvals', 'ignore_stale_approvals', 'require_signed_commits',
    'protected_file_patterns', 'unprotected_file_patterns', 'block_admin_merge_override')
_LIST_FIELDS = frozenset(f for f in PROTECTION_FIELDS if f.endswith(('_usernames', '_username', '_teams'))
                         or f == 'status_check_contexts')
_TEXT_FIELDS = frozenset(('protected_file_patterns', 'unprotected_file_patterns'))
_NUMBER_FIELDS = frozenset(('priority', 'required_approvals'))


def _total_rule(rule_name: str, priority: int, **settings) -> dict:
    """One rule over every field of PROTECTION_FIELDS: SETTINGS as given, every other flag false, every other
    list empty, both pattern strings empty and no required approval (Gitea's own zero values), so that a
    PATCH re-applying it resets whatever it does not set."""
    unknown = sorted(set(settings) - set(PROTECTION_FIELDS))
    if unknown:
        raise ValueError(f'not a Gitea 28.3.0 branch protection field: {unknown}')
    zero = {f: [] if f in _LIST_FIELDS else '' if f in _TEXT_FIELDS else 0 if f in _NUMBER_FIELDS else False
            for f in PROTECTION_FIELDS}
    rule = {**zero, **settings, 'rule_name': rule_name, 'priority': priority}
    return {f: rule[f] for f in PROTECTION_FIELDS}


def protection_rules() -> list[dict]:
    """The fixture's branch protection, in priority order, total over PROTECTION_FIELDS. The default
    branch: nobody pushes, nobody force-pushes, only aieh-owner merges, one approval from the reviewer bot
    is required, a rejected review blocks, a branch behind it cannot be merged, and the site
    administrator's merge override is blocked. work/*: the planner and builder bots push. Every other
    branch name: nobody pushes. On every rule the bypass allowlist is disabled and empty. Stale approvals
    are not dismissed (dismiss_stale_approvals false) until G-03.1 decides the authorization branch's
    policy. Protected branches cannot be deleted."""
    reviewer, planner, builder = (ROLES[r]['user'] for r in ('reviewer', 'planner', 'builder'))
    only_owner_merges = {'enable_merge_whitelist': True, 'merge_whitelist_usernames': [host.OWNER]}
    return [
        _total_rule(DEFAULT_BRANCH, 1, enable_push=False, enable_force_push=False, **only_owner_merges,
                    block_admin_merge_override=True, required_approvals=1, enable_approvals_whitelist=True,
                    approvals_whitelist_username=[reviewer], block_on_rejected_reviews=True,
                    block_on_outdated_branch=True, dismiss_stale_approvals=False, enable_bypass_allowlist=False,
                    bypass_allowlist_usernames=[], bypass_allowlist_teams=[]),
        _total_rule(PROPOSAL_PATTERN, 2, enable_push=True, enable_push_whitelist=True,
                    push_whitelist_usernames=[planner, builder], enable_force_push=False, **only_owner_merges),
        _total_rule('**', 3, enable_push=False, enable_force_push=False, **only_owner_merges),
    ]


def collaborators() -> dict:
    """Repository permission per account: the bots per role (the protection auditor admin); the Owner
    account writes, because Gitea admits only accounts with write access to a merge allowlist."""
    return {**{spec['user']: spec['permission'] for spec in ROLES.values()}, host.OWNER: 'write'}


def repository_settings() -> dict:
    """The fixture repository's settings that protection depends on, as Gitea 28.3.0's repository view names
    them (modules/structs/repo.go): private, not archived, its default branch, and merge commits as the only
    merge style (G-03.1's authorization branch); no manual merge (a pull request marked merged without a
    merge). apply_fixture applies them with PATCH /repos/{owner}/{repo}; the protection check compares them."""
    return {'private': True, 'archived': False, 'default_branch': DEFAULT_BRANCH, 'allow_merge_commits': True,
            'allow_rebase': False, 'allow_rebase_explicit': False, 'allow_squash_merge': False,
            'allow_fast_forward_only_merge': False, 'allow_manual_merge': False, 'autodetect_manual_merge': False,
            'default_merge_style': 'merge'}


# The teams with access to the fixture repository, with their access level: the organization's Owners team
# only, which Gitea creates with the organization and gives every repository of it (includes all
# repositories). Not applied by apply_fixture; compared by the protection check.
FIXTURE_TEAMS = {'Owners': 'owner'}


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
    """JSON over HTTP to 127.0.0.1:<port>/api/v1, authenticated by a token (Authorization: token ...) or by
    HTTP basic authentication (basic=(user, password), the site administrator's fixture administration)."""

    def __init__(self, port: int, token: str | None = None, http: Callable = None, basic: tuple | None = None):
        self.port, self.token, self.http, self.basic = port, token, http or host.http_get, basic

    def call(self, method: str, path: str, body=None, headers=None) -> tuple[int, object]:
        sent = {'Accept': 'application/json', **(headers or {})}
        if self.token is not None:
            sent['Authorization'] = 'token ' + self.token
        elif self.basic is not None:
            sent.update(host.basic_header(*self.basic))
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


def context(provider=None, run: Callable = subprocess.run):
    res = host.paths.resolve()
    lay, pinned = host.layout(res), host.pin()
    port = host.read_host_record(lay)['port']
    if not host.healthy(port):
        raise GiteaError('NOT_RUNNING', 'Gitea does not answer; run task gitea:up')
    return lay, pinned, port, provider or host.credential_provider(), Cli(lay, pinned, run)


def read_token(provider, role: str) -> str | None:
    """A role bot's token from its provider entry. Only role entries are read here: the site
    administrator's and the Owner account's entries are not reachable through this function."""
    if role not in ROLES:
        raise GiteaError('ROLE_UNKNOWN', f'{role!r} is not one of {sorted(ROLES)}')
    entry = provider.get(target(role))
    if entry is None:
        return None
    user, token = entry
    if user != ROLES[role]['user']:
        raise GiteaError('ENTRY_MISMATCH', f'{target(role)!r} names {user!r}, not {ROLES[role]["user"]!r}')
    return token


def entry_comment(role: str, port: int) -> str:
    """The comment of the role's entry: the account, the scopes, the instance, and its custody. It fits the
    Windows Comment limit (256 characters) with margin for every role and port."""
    spec = ROLES[role]
    custodian = spec.get('custodian', 'the management dispatcher')
    return (f'AIEH Gitea token of {spec["user"]} (scopes {",".join(spec["scopes"])}) at '
            f'http://{host.LOOPBACK}:{port}/ (S-01.2.2). Bootstrap custody: the Owner account; {custodian} is its '
            'planned custodian.')


def check_entry(role: str, port: int) -> None:
    """Before any token is minted: the role's entry, exactly as store_token will write it (its target, user and
    comment, and a token's size), checked against the Windows credential field limits; CREDENTIAL_FIELD_LIMIT
    when it does not fit. It writes nothing, and passing it is no guarantee that the store succeeds
    (store_minted handles that failure)."""
    credentials = host.credentials
    credentials.check_credential_fields(target(role), ROLES[role]['user'], entry_comment(role, port),
                                        credentials.secret_blob_size(TOKEN_LENGTH))


def store_token(provider, role: str, token: str, port: int) -> None:
    provider.set(target(role), ROLES[role]['user'], token, entry_comment(role, port))


def store_minted(provider, role: str, token: str, name: str, port: int, http: Callable = None) -> None:
    """Store a token minted just now. When the store fails, the token revokes itself once (revoke_current:
    DELETE /api/v1/token, then its next call must get 401), with no retry of either the store or the mint, and the
    act fails: TOKEN_STORE_FAILED when the revocation is confirmed, TOKEN_ORPHANED when it is not, naming what an
    administrator must remove. The token's name, account and fingerprint identify it; its value is never shown,
    and its Gitea id is not known (the CLI's --raw output is the value alone)."""
    try:
        store_token(provider, role, token, port)
        return
    except Exception as exc:  # noqa: BLE001 - every store failure leaves a minted token to clean up
        failure = f'{getattr(exc, "code", type(exc).__name__)}: {redact(str(getattr(exc, "detail", exc)))[:200]}'
    user = ROLES[role]['user']
    outcome = {'role': role, 'user': user, 'entry': target(role), 'token_name': name, 'gitea_id': None,
               'fingerprint': fingerprint(token), 'store_error': failure}
    try:
        outcome['cleanup'] = revoke_current(port, token, http)
    except Exception as exc:  # noqa: BLE001 - an uncertain cleanup is reported, never retried
        outcome['cleanup'] = {'revoked': False, 'error': type(exc).__name__}
    del token
    told = (f'storing the token minted for {user} in {target(role)!r} failed ({failure}); the token (name {name!r}, '
            f'{outcome["fingerprint"]}; Gitea id not known) ')
    cleanup = json.dumps(outcome['cleanup'], sort_keys=True)
    if outcome['cleanup']['revoked']:
        error = GiteaError('TOKEN_STORE_FAILED', told + f'revoked itself once: {cleanup}; nothing was stored',
                           refusal=False)
    else:
        error = GiteaError('TOKEN_ORPHANED', told + f'was NOT confirmed revoked by its one attempt: {cleanup}',
                           refusal=False, remedy=f'a Gitea administrator must delete the access token {name!r} '
                           f'of the account {user} ({outcome["fingerprint"]}); this act does not retry it')
    error.outcome = outcome
    raise error


def token_check(port: int, token: str, http: Callable = None) -> dict:
    """What Gitea says about a token: GET /api/v1/token (its own name and scopes)."""
    status, body = Api(port, token, http).call('GET', '/token')
    report = {'status': status}
    if status == 200 and isinstance(body, dict):
        report.update(name=body.get('name'), scopes=sorted(body.get('scopes') or []))
    return report


def provision(provider=None, run: Callable = subprocess.run, roles=None, http: Callable = None,
              ctx=None) -> dict:
    """Create each missing bot account, then mint and store a token for each role whose entry is
    absent. An existing entry is kept (rotate replaces one). Every role's entry is checked against the Windows
    credential field limits first (check_entry), so an entry that cannot be written is refused before any Gitea
    change, account creation included; a store that fails anyway is cleaned up by store_minted."""
    lay, pinned, port, provider, cli = ctx or context(provider, run)
    roles = list(roles or ROLES)
    for role in roles:
        check_entry(role, port)
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
        token = read_token(provider, role)
        minted = token is None
        if minted:
            name = f'aieh-{role}-{now_stamp()}'
            token = cli.mint(spec['user'], name, spec['scopes'])
            store_minted(provider, role, token, name, port, http)
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

    status, payload = api.call('GET', f'/orgs/{FIXTURE_ORG}')
    if status == 404:
        call('POST', '/orgs', {'username': FIXTURE_ORG, 'visibility': 'private',
                               'repo_admin_change_team_access': False,
                               'description': 'Disposable authorization fixture (plan leaf S-01.2.2)'})
    else:
        require(status, 200, f'GET /orgs/{FIXTURE_ORG}', payload)
    repo = f'/repos/{FIXTURE_ORG}/{FIXTURE_REPO}'
    status, payload = api.call('GET', repo)
    if status == 404:
        call('POST', f'/orgs/{FIXTURE_ORG}/repos', {'name': FIXTURE_REPO, 'private': True, 'auto_init': True,
                                                    'default_branch': DEFAULT_BRANCH, 'readme': 'Default'})
    else:
        require(status, 200, f'GET {repo}', payload)
    call('PATCH', repo, repository_settings())
    for user, permission in collaborators().items():
        call('PUT', f'{repo}/collaborators/{user}', {'permission': permission})
    status, existing = call('GET', f'{repo}/branch_protections')
    names = {rule.get('rule_name') for rule in existing or []}
    for rule in protection_rules():
        name = rule['rule_name']
        if name in names:
            body = {k: v for k, v in rule.items() if k != 'rule_name'}
            call('PATCH', f'{repo}/branch_protections/{urllib.parse.quote(name, safe="")}', body)
        else:
            call('POST', f'{repo}/branch_protections', rule)
    return actions


def read_fixture(api: Api) -> dict:
    """The fixture as Gitea reports it: the repository's settings, collaborator permissions and protection
    rules."""
    repo = f'/repos/{FIXTURE_ORG}/{FIXTURE_REPO}'
    status, info = api.call('GET', repo)
    require(status, 200, f'GET {repo}', info)
    perms = {}
    for user in collaborators():
        status, body = api.call('GET', f'{repo}/collaborators/{user}/permission')
        perms[user] = body.get('permission') if status == 200 and isinstance(body, dict) else f'HTTP {status}'
    status, rules = api.call('GET', f'{repo}/branch_protections')
    require(status, 200, f'GET {repo}/branch_protections', rules)
    return {'repository': {'full_name': info.get('full_name'), 'private': info.get('private'),
                           'default_branch': info.get('default_branch')},
            'settings': {k: info.get(k) for k in repository_settings()},
            'collaborator_permissions': perms,
            'branch_protections': [{k: r.get(k) for k in PROTECTION_FIELDS} for r in rules or []]}


def admin_api(provider, port: int, http: Callable = None) -> Api:
    """The site administrator, by HTTP basic authentication with its harness-held password read from the
    credential provider into memory (Owner directive of 2026-11-07). No token is minted for administration."""
    entry = provider.get(host.FINAL_TARGETS[host.SITE_ADMIN])
    if entry is None or entry[0] != host.SITE_ADMIN:
        raise GiteaError('ADMIN_NOT_FINALIZED', f'{host.FINAL_TARGETS[host.SITE_ADMIN]!r} is missing; run task '
                         'gitea:finalize-credentials')
    api = Api(port, http=http, basic=(host.SITE_ADMIN, entry[1]))
    del entry
    status, body = api.call('GET', '/user')
    if status != 200 or not (isinstance(body, dict) and body.get('is_admin')):
        raise GiteaError('ADMIN_UNUSABLE', f'the site administrator gets HTTP {status}', refusal=False)
    return api


def fixture(provider=None, run: Callable = subprocess.run, http: Callable = None, ctx=None,
            probe: Callable | None = None) -> dict:
    """Apply and read back the fixture as the site administrator (basic authentication, password in memory
    only), optionally run probe(api) with it (the admin merge-override check), and show that the
    administrator still holds no access token."""
    lay, pinned, port, provider, cli = ctx or context(provider, run)
    users = cli.users()
    missing = sorted({spec['user'] for spec in ROLES.values()} - set(users))
    if missing:
        raise GiteaError('BOTS_MISSING', f'run provision first: {missing}')
    if host.OWNER not in users:
        raise GiteaError('OWNER_MISSING', f'{host.OWNER} does not exist; run task gitea:identities')
    api = admin_api(provider, port, http)
    report = {'admin_auth': {'user': host.SITE_ADMIN, 'method': 'HTTP basic authentication, password read from '
                             f'{host.FINAL_TARGETS[host.SITE_ADMIN]!r} into memory; no token minted'}}
    report['actions'] = apply_fixture(api)
    report['fixture'] = read_fixture(api)
    if probe is not None:
        report['probe'] = probe(api)
    status, tokens = api.call('GET', f'/users/{host.SITE_ADMIN}/tokens')
    report['admin_tokens_after'] = [t.get('name') for t in tokens] if status == 200 else f'HTTP {status}'
    return report


# The escape-probe repository as escape_probe_repository creates it, in the names of Gitea 28.3.0's repository
# view: private, empty (no auto_init), not archived; and no collaborator.
ESCAPE_PROBE_STATE = {'private': True, 'empty': True, 'archived': False}


def read_escape_probe(api: Api) -> dict:
    """The escape-probe repository as Gitea reports it: its view's ESCAPE_PROBE_STATE fields and its direct
    collaborators (the first page of 50: an empty first page means none)."""
    repo = f'/repos/{FIXTURE_ORG}/{ESCAPE_PROBE_REPO}'
    status, info = api.call('GET', repo)
    require(status, 200, f'GET {repo}', info)
    status, roster = api.call('GET', f'{repo}/collaborators?page=1&limit=50')
    require(status, 200, f'GET {repo}/collaborators', roster)
    if not isinstance(info, dict) or not isinstance(roster, list):
        raise GiteaError('API_UNEXPECTED', f'{repo}: a view of another kind', refusal=False)
    return {'full_name': info.get('full_name'), **{k: info.get(k) for k in ESCAPE_PROBE_STATE},
            'collaborators': sorted(str(c.get('login') if isinstance(c, dict) else c) for c in roster)}


def escape_probe_differences(observed: dict) -> list[str]:
    """How observed differs from the escape-probe repository as it is created ([] when it does not)."""
    wanted = {'full_name': f'{FIXTURE_ORG}/{ESCAPE_PROBE_REPO}', **ESCAPE_PROBE_STATE, 'collaborators': []}
    return [f'{k} is {observed.get(k)!r}, not {v!r}' for k, v in wanted.items() if observed.get(k) != v]


def escape_probe_repository(api: Api) -> dict:
    """Create the private, empty repository FIXTURE_ORG/ESCAPE_PROBE_REPO with no collaborators, or find it so.
    Bounded: it reads the organization and that repository only and its one write is the repository's
    creation; the fixture repository is never addressed. An existing repository as it is created is reported
    and left unchanged; one in any other state is refused (ESCAPE_PROBE_STATE) and left unchanged; a missing
    organization is refused (FIXTURE_MISSING): fixture creates it."""
    status, payload = api.call('GET', f'/orgs/{FIXTURE_ORG}')
    if status == 404:
        raise GiteaError('FIXTURE_MISSING', f'the organization {FIXTURE_ORG} does not exist; run fixture first')
    require(status, 200, f'GET /orgs/{FIXTURE_ORG}', payload)
    repo = f'/repos/{FIXTURE_ORG}/{ESCAPE_PROBE_REPO}'
    status, payload = api.call('GET', repo)
    actions = []
    if status == 404:
        path = f'/orgs/{FIXTURE_ORG}/repos'
        status, payload = api.call('POST', path, {
            'name': ESCAPE_PROBE_REPO, 'private': True, 'auto_init': False,
            'description': 'The protection auditor\'s escape probe: no collaborators (Owner decision OA-16)'})
        actions.append({'method': 'POST', 'path': path, 'status': status})
        require(status, 201, f'POST {path}', payload)
    else:
        require(status, 200, f'GET {repo}', payload)
    observed = read_escape_probe(api)
    differences = escape_probe_differences(observed)
    if differences and actions:
        raise GiteaError('ESCAPE_PROBE_READBACK', f'{FIXTURE_ORG}/{ESCAPE_PROBE_REPO} was created but reads back '
                         'otherwise: ' + '; '.join(differences), refusal=False)
    if differences:
        raise GiteaError('ESCAPE_PROBE_STATE', f'{FIXTURE_ORG}/{ESCAPE_PROBE_REPO} exists in another state; '
                         'nothing changed: ' + '; '.join(differences))
    return {'repository': f'{FIXTURE_ORG}/{ESCAPE_PROBE_REPO}',
            'state': 'created' if actions else 'already present with no collaborators; nothing changed',
            'actions': actions, 'observed': observed}


def escape_probe(provider=None, run: Callable = subprocess.run, http: Callable = None, ctx=None) -> dict:
    """The escape-probe repository (escape_probe_repository) as the site administrator, as fixture() acts
    (basic authentication, password in memory only), and the administrator's tokens afterwards (none)."""
    lay, pinned, port, provider, cli = ctx or context(provider, run)
    api = admin_api(provider, port, http)
    report = {'admin_auth': {'user': host.SITE_ADMIN, 'method': 'HTTP basic authentication, password read from '
                             f'{host.FINAL_TARGETS[host.SITE_ADMIN]!r} into memory; no token minted'}}
    report.update(escape_probe_repository(api))
    status, tokens = api.call('GET', f'/users/{host.SITE_ADMIN}/tokens')
    report['admin_tokens_after'] = [t.get('name') for t in tokens] if status == 200 else f'HTTP {status}'
    return report


TRIGGER ='owner direction'  # decision 0007 point 5: a command-line act is the Owner's direction (bootstrap)


def receipt_for(receipts, verb: str, role: str, provider, token: str | None):
    """The act's integration-store receipt (gitea_host.act_receipt), reserved before anything changes."""
    return host.act_receipt(receipts, verb, entry=target(role), user=ROLES[role]['user'], role=role, before=token,
                            provider=provider, trigger=TRIGGER, revoker=f'harness: gitea_roles.py {verb} (the token '
                            'revokes itself through DELETE /api/v1/token)', actor=f'gitea_roles {verb}').begin()


@contextlib.contextmanager
def receipt_store(receipts, ctx):
    """receipts when given (an open integration store); else, for the command line's own context only, the
    managed one, opened for the act. A given context (a fixture) without its own receipt store is refused, so
    that a fixture act never writes into the managed root's store."""
    if receipts is not None:
        yield receipts
        return
    if ctx is not None:
        raise ValueError('a given context needs its own receipt store (receipts=)')
    with host.credential_receipts(host.paths.resolve()) as store:
        yield store


def rotate(role: str, provider=None, run: Callable = subprocess.run, http: Callable = None, ctx=None,
           receipts=None) -> dict:
    """The revocation contract once: revoke the role's token through DELETE /api/v1/token, prove its
    next call fails closed, mint a new one and replace the entry, prove the new one works. It resumes, as
    retire does: a token Gitea already refuses (401: revoked by an earlier run or on another trigger) is not
    revoked again, and the new one is minted. The act's integration-store receipt is reserved before the
    revocation and confirmed and read back at the end. The new entry is checked against the Windows credential
    field limits before anything changes (check_entry); a store that fails anyway is cleaned up by
    store_minted."""
    if role not in ROLES:
        raise GiteaError('ROLE_UNKNOWN', f'{role!r} is not one of {sorted(ROLES)}')
    given = ctx
    lay, pinned, port, provider, cli = ctx or context(provider, run)
    check_entry(role, port)
    old = read_token(provider, role)
    if old is None:
        raise GiteaError('ENTRY_MISSING', f'{target(role)!r} does not exist; run provision')
    with receipt_store(receipts, given) as store:
        receipt = receipt_for(store, 'rotate', role, provider, old)
        try:
            report = {'role': role, 'user': ROLES[role]['user'], 'entry': target(role),
                      'old_fingerprint': fingerprint(old), 'old_before': token_check(port, old, http)}
            receipt.dispatched()
            if report['old_before']['status'] == 401:
                report['revocation'] = 'already refused by Gitea (revoked earlier)'
            else:
                report['revocation'] = revoke_current(port, old, http)
            report['old_on_repository_read'] = Api(port, old, http).call(
                'GET', f'/repos/{FIXTURE_ORG}/{FIXTURE_REPO}')[0]
            del old
            if isinstance(report['revocation'], dict) and not report['revocation']['revoked']:
                raise GiteaError('REVOCATION_FAILED', json.dumps(report), refusal=False)
            name = f'aieh-{role}-{now_stamp()}'
            new = cli.mint(ROLES[role]['user'], name, ROLES[role]['scopes'])
            store_minted(provider, role, new, name, port, http)
            report.update(new_fingerprint=fingerprint(new), new_check=token_check(port, new, http))
            del new
        except BaseException as exc:
            receipt.abort(exc)
            raise
        report['receipt'] = receipt.finish({'fingerprint_after': report['new_fingerprint'], 'revoked': True,
                                            'revocation': 'revoked' if isinstance(report['revocation'], dict)
                                            else report['revocation'],
                                            'new_token_status': report['new_check']['status']})
    return report


def retire(role: str, provider=None, run: Callable = subprocess.run, http: Callable = None, ctx=None,
           receipts=None) -> dict:
    """The contract's retire: revoke the role's token through DELETE /api/v1/token, prove its next call fails
    closed, then delete its entry (never before the revocation is shown). It resumes: a token Gitea already
    refuses is not revoked again, and a missing entry is reported as retired. The bot account is kept. Every
    run, a resumed one included, writes its integration-store receipt and reads it back."""
    if role not in ROLES:
        raise GiteaError('ROLE_UNKNOWN', f'{role!r} is not one of {sorted(ROLES)}')
    given = ctx
    lay, pinned, port, provider, cli = ctx or context(provider, run)
    report = {'role': role, 'user': ROLES[role]['user'], 'entry': target(role)}
    token = read_token(provider, role)
    with receipt_store(receipts, given) as store:
        receipt = receipt_for(store, 'retire', role, provider, token)
        try:
            if token is None:
                report['state'] = 'retired (no entry: nothing to revoke)'
            else:
                report.update(fingerprint=fingerprint(token), before=token_check(port, token, http))
                receipt.dispatched()
                if report['before']['status'] == 401:
                    report['revocation'] = 'already refused by Gitea (an earlier run revoked it)'
                else:
                    report['revocation'] = revoke_current(port, token, http)
                del token
                if isinstance(report['revocation'], dict) and not report['revocation']['revoked']:
                    raise GiteaError('REVOCATION_FAILED', json.dumps(report), refusal=False)
                report['entry_deleted'] = provider.delete(target(role))
                report['state'] = 'retired'
        except BaseException as exc:
            receipt.abort(exc)
            raise
        revocation = report.get('revocation')
        report['receipt'] = receipt.finish({'state': report['state'], 'entry_deleted': report.get('entry_deleted'),
                                            'revocation': revocation if isinstance(revocation, str) or revocation
                                            is None else 'revoked'})
    return report


def status(provider=None, run: Callable = subprocess.run, http: Callable = None, ctx=None) -> dict:
    lay, pinned, port, provider, cli = ctx or context(provider, run)
    users = cli.users()
    report = {}
    for role, spec in ROLES.items():
        token = read_token(provider, role)
        report[role] = {'user': spec['user'], 'account': users.get(spec['user']), 'entry': target(role),
                        'entry_present': token is not None}
        if token is not None:
            report[role].update(fingerprint=fingerprint(token), check=token_check(port, token, http))
        del token
    return report


def admin_merge_probe(provider, port: int, http: Callable = None) -> Callable:
    """The probe fixture() runs as the site administrator: a proposal PR from the builder bot, then the site
    administrator's merge and force-merge, both of which branch protection must refuse."""
    def probe(api: Api) -> dict:
        builder = Api(port, read_token(provider, 'builder'), http)
        repo = f'/repos/{FIXTURE_ORG}/{FIXTURE_REPO}'
        stamp = now_stamp().lower()
        branch = f'work/admin-probe-{stamp}'
        status, body = builder.call('POST', f'{repo}/contents/admin-probe-{stamp}.txt', {
            'content': 'YWRtaW4gbWVyZ2UtcHJvYmUK', 'message': 'admin merge-override probe',
            'branch': DEFAULT_BRANCH, 'new_branch': branch})
        result = {'builder_creates_proposal_branch': status}
        require(status, 201, 'builder creates the probe branch', body)
        status, pull = builder.call('POST', f'{repo}/pulls', {'head': branch, 'base': DEFAULT_BRANCH,
                                                              'title': 'admin merge-override probe'})
        require(status, 201, 'builder opens the probe PR', pull)
        number = pull['number']
        before = api.call('GET', f'{repo}/branches/{DEFAULT_BRANCH}')[1]['commit']['id']
        merge = api.call('POST', f'{repo}/pulls/{number}/merge', {'Do': 'merge'})
        force = api.call('POST', f'{repo}/pulls/{number}/merge', {'Do': 'merge', 'force_merge': True})
        result.update(pull=number, admin_merge=[merge[0], redact(str((merge[1] or {}).get('message', '')))[:160]],
                      admin_force_merge=[force[0], redact(str((force[1] or {}).get('message', '')))[:160]])
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
    fix = sub.add_parser('fixture', help='apply the fixture as the site administrator (credentials in memory)')
    fix.add_argument('--admin-merge-probe', action='store_true',
                     help='also check that the site administrator cannot merge or force-merge a proposal PR')
    sub.add_parser('escape-probe', help=f'create the private, empty repository {FIXTURE_ORG}/{ESCAPE_PROBE_REPO} '
                   'with no collaborators as the site administrator (the protection auditor\'s escape probe); '
                   'never touches the fixture repository')
    rot =sub.add_parser('rotate', help='revoke a role token, prove it fails closed, re-issue it')
    rot.add_argument('role', choices=sorted(ROLES))
    ret = sub.add_parser('retire', help='revoke a role token, prove it fails closed, delete its entry')
    ret.add_argument('role', choices=sorted(ROLES))
    sub.add_parser('status', help='entries, fingerprints and what Gitea says of each token; changes nothing')
    args = parser.parse_args(argv)
    out = sys.stdout
    if hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')
    if os.name != 'nt':
        sys.stderr.write('gitea-roles: REFUSED: only the Windows credential provider is implemented\n')
        return 2
    guard = host.ACT_GUARD = host.contract.ExposureGuard()  # the provider holds what the act reads or writes
    report, message, code = None, '', 0
    try:
        if args.command == 'provision':
            report = provision()
        elif args.command == 'fixture':
            ctx = context()
            probe = admin_merge_probe(ctx[3], ctx[2]) if args.admin_merge_probe else None
            report = fixture(ctx=ctx, probe=probe)
        elif args.command == 'escape-probe':
            report = escape_probe()
        elif args.command == 'rotate':
            report = rotate(args.role)
        elif args.command == 'retire':
            report = retire(args.role)
        else:
            report = status()
    except host.paths.PathsError as exc:
        message, code = f'gitea-roles: {exc}\n', 2
    except GiteaError as exc:
        message, code = f'gitea-roles: {redact(str(exc))}\n', 2 if exc.refusal else 1
    finally:
        host.ACT_GUARD = None
    text = '' if report is None else redact(json.dumps(report, indent=2, default=str)) + '\n'
    scan = host.exposure_scan(guard, text, message)
    guard.clear()
    if scan['found_in']:
        exposure = GiteaError('EXPOSURE_FOUND', 'a secret the act held is in its ' + ' and '.join(scan['found_in']),
                              refusal=False)
        sys.stderr.write(f'gitea-roles: {exposure}\n')
        return 1
    sys.stderr.write(message)
    out.write(text)
    sys.stderr.write(f'gitea-roles: I7 no-exposure scan: clean ({scan["secrets_held"]} secrets held; '
                     f'{scan["scanned"]} outputs scanned)\n')
    return code


if __name__ == '__main__':
    sys.exit(main())
