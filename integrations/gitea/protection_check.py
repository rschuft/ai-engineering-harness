"""The protection check before each protected merge (decision 0012 point 6, Proposed; Owner decision OA-16).

A bounded, read-only adapter of the Gitea integration, not a policy service: it reads what Gitea 28.3.0
reports about one declared repository as the protection auditor, compares it with the harness's total
declaration of that repository (one entry per repository, ``gitea_roles.DECLARATIONS``: the S-01.2.2 fixture's
and the authorization repository's, each its rules, settings, collaborators and teams and no deploy key) and
answers ``Verdict(status, code, detail, digest, problems)``, ``status`` one of ``verified``, ``drift`` or
``unverified``. Anything it cannot establish is ``unverified``, never ``verified``. The authorization recorder
(integrations/owner) asks it as the last read before each merge and once more after it (its ``Context.verifier``
seam).

**The auditor.** Gitea 28.3.0 serves branch protection rules (``GET /repos/{owner}/{repo}/branch_protections``)
to repository and site administrators only (routers/api/v1/api.go: ``reqToken(), reqAdmin()``). The check
therefore reads as ``aieh-bot-protection-audit``: a restricted Gitea Bot account without a password, a
collaborator with ``admin`` permission on the repositories it audits only (``gitea_roles.AUDITED_REPOSITORIES``),
holding one token of scope exactly
``read:repository``. Gitea decides the required scope by HTTP method (``tokenRequiresScopes``): GET needs the
read scope, every POST, PUT, PATCH and DELETE under ``/repos`` the write scope, and the scope binds a token
presented as a basic-authentication password too (services/auth/basic.go), so the token reads and can write
nothing. It is no administrator credential. The token is read by name from the credential provider entry
``AIEH Gitea bot protection-audit`` (gitea_roles.read_token: an entry naming another account is refused),
into memory, for one check; it is sent only in the Authorization header of this module's fixed GET requests
and never returned, shown or written. The one state change the token could make is deleting itself
(``DELETE /api/v1/token`` needs no scope); this module never sends it, and a deleted token only makes the
check answer ``unverified``.

**What it reads** (``AuditSession``; any other method or path is a ValueError before anything is sent):
``GET /token`` (its own login and scopes: no scope is needed), the repository, its branch protection rules,
the protected branch (with ``effective_branch_protection_name``, which Gitea shows to repository
administrators), the collaborators (``X-Total-Count`` must equal the number listed), each collaborator's
permission, the teams with access, and the deploy keys (deploy tokens included: Gitea 28.3.0 stores both
as deploy keys).

**What it compares** (the closed list):

- the auditor: ``GET /token`` names ``aieh-bot-protection-audit`` with scopes exactly ``read:repository``,
  and the repository view shows ``permissions.admin`` true; otherwise ``AUDITOR_INVALID``;
- every rule: all 34 fields of Gitea 28.3.0's BranchProtection view but ``branch_name`` (a deprecated
  alias, checked for consistency), ``created_at`` and ``updated_at`` (``FIELDS``), the bypass allowlist
  included; ``null`` and ``[]`` compare equal for list fields and lists compare as multisets; a field
  outside the 37 known names, or one of them missing, is ``unverified`` (a setting this pin does not know:
  an upgrade that changes the view stops merges until the list is revisited);
- the exact rule set: no declared rule missing, no other rule;
- rule precedence at the pin (models/git/protected_branch_list.go): Gitea orders the rules by ``priority``
  (lower first), then a plain name before a glob, then the earlier created; a plain name matches a branch
  case-insensitively, a glob with ``/`` as separator (modules/glob); the first rule that matches is the one
  Gitea enforces. The check computes, from the observed rules, every rule that matches the protected branch
  and the first of them, and requires Gitea's own ``effective_branch_protection_name`` to be that rule
  (otherwise ``PRECEDENCE_UNVERIFIED``) and the declared one (otherwise drift);
- the repository's settings of ``repository_settings()`` (privacy, archive flag, default branch, merge
  styles, manual merge); its view's top-level fields must be exactly 28.3.0's (``REPOSITORY_KEYS``);
- the collaborators with their permissions, exactly; the teams with access and their permission, exactly;
  no deploy key.

**The digest** is ``sha256:`` of the canonical JSON of the observed values (the auditor, the settings, the
rules, the effective rule, the roster, the teams and the deploy keys; never a token, a time or a commit), so
two answers around a merge can be compared.

**Limits** (disclosed, not closed): team membership is not readable with ``read:repository`` (``/teams`` and
``/orgs`` need the organization scope), so who belongs to the Owners team is not compared; each listed
collaborator's permission is effective, team membership included. The allowlist names Gitea shows are
resolved among the repository's current readers (services/convert/convert.go ``getWhitelistEntities``): an
id of an account without access is not shown, and cannot merge, since it cannot reach the private repository.
Webhooks are not read. Between this read and Gitea's own evaluation at merge time there is no transaction
(time of check to time of use): a repository administrator can change a rule in between; the recorder
discloses a change it sees after the merge (``PROTECTION_CHANGED_AFTER_MERGE``).

Usage (the qualification command; it reads the auditor's entry and prints the verdict, never the token):

    python -I -B integrations/gitea/protection_check.py verify OWNER/NAME [--base BRANCH] [--port PORT]

Exit 0 verified, 1 drift, 2 unverified or refused.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.util
import json
import os
import re
import sys
import types
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


roles = _load('aieh_gitea_roles', HERE / 'gitea_roles.py')
host = roles.host

ROLE = 'protection-audit'
AUDITOR = roles.ROLES[ROLE]['user']
ENTRY = roles.target(ROLE)
CREDENTIAL = roles.ROLES[ROLE]['credential']
SCOPES = ['read:repository']
TIMEOUT_S = 30.0
PAGE = 'page=1&limit=50'  # Gitea's default MAX_RESPONSE_ITEMS is 50
TOKEN = re.compile(r'[0-9a-f]{40}')
LOGIN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,39}')
SEGMENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')
BRANCH = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/-]*')
VERDICTS = ('verified', 'drift', 'unverified')
FORMAT = 'aieh-protection-observation/1'

# Gitea 28.3.0's views (modules/structs), read in the pinned source: the field names the check knows.
FIELDS = roles.PROTECTION_FIELDS  # the 34 compared fields of BranchProtection
RULE_KEYS = frozenset(FIELDS) | {'branch_name', 'created_at', 'updated_at'}
LIST_FIELDS = frozenset(f for f in FIELDS if f.endswith(('_usernames', '_username', '_teams'))
                        or f == 'status_check_contexts')
NUMBER_FIELDS = frozenset(('priority', 'required_approvals'))
TEXT_FIELDS = frozenset(('rule_name', 'protected_file_patterns', 'unprotected_file_patterns'))
REPOSITORY_KEYS = frozenset((
    'id', 'owner', 'name', 'full_name', 'description', 'empty', 'private', 'fork', 'template', 'parent', 'mirror',
    'size', 'language', 'languages_url', 'html_url', 'url', 'link', 'ssh_url', 'clone_url', 'original_url',
    'website', 'stars_count', 'forks_count', 'watchers_count', 'branch_count', 'open_issues_count',
    'open_pr_counter', 'release_counter', 'default_branch', 'default_target_branch', 'archived', 'created_at',
    'updated_at', 'archived_at', 'permissions', 'has_code', 'has_issues', 'internal_tracker', 'external_tracker',
    'has_wiki', 'external_wiki', 'has_pull_requests', 'has_projects', 'projects_mode', 'has_releases',
    'has_packages', 'has_actions', 'ignore_whitespace_conflicts', 'allow_merge_commits', 'allow_rebase',
    'allow_rebase_explicit', 'allow_squash_merge', 'allow_fast_forward_only_merge', 'allow_merge_update',
    'allow_rebase_update', 'allow_manual_merge', 'autodetect_manual_merge', 'default_delete_branch_after_merge',
    'default_merge_style', 'default_update_style', 'default_allow_maintainer_edit', 'avatar_url', 'internal',
    'mirror_interval', 'object_format_name', 'mirror_updated', 'mirror_last_sync_at', 'repo_transfer', 'topics',
    'licenses'))
# omitempty in the struct; permissions is required of the auditor's view below
REPOSITORY_OPTIONAL = frozenset(('parent', 'default_target_branch', 'permissions', 'internal_tracker',
                                 'external_tracker', 'external_wiki', 'repo_transfer'))
BRANCH_KEYS = frozenset(('name', 'commit', 'protected', 'required_approvals', 'enable_status_check',
                         'status_check_contexts', 'user_can_push', 'user_can_merge',
                         'effective_branch_protection_name'))
TOKEN_KEYS = frozenset(('id', 'name', 'scopes', 'created_at', 'last_used_at', 'user'))
TEAM_KEYS = frozenset(('id', 'name', 'description', 'organization', 'includes_all_repositories', 'permission',
                       'units', 'units_map', 'can_create_org_repo', 'visibility'))
PERMISSION_KEYS = frozenset(('permission', 'role_name', 'user'))
ACCESS_LEVELS = ('none', 'read', 'write', 'admin', 'owner')
_NOT_JSON = object()


class Verdict(NamedTuple):
    """The check's answer: STATUS one of VERDICTS; CODE a stable reason (VERIFIED, DRIFT, or why it is
    unverified); DETAIL what it found (never a credential); DIGEST ``sha256:<64 hex>`` of the canonical
    observed state when every read succeeded (None when unverified); PROBLEMS each difference or defect."""
    status: str
    code: str
    detail: str
    digest: str | None = None
    problems: tuple = ()


class Unverifiable(Exception):
    """Something the check cannot establish: its answer is unverified."""

    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}')


# ---------------------------------------------------------------------------- the declaration


def declaration(repository, base):
    """The total declaration of a declared repository, one entry per repository (gitea_roles.DECLARATIONS): the
    S-01.2.2 authorization fixture, and the authorization repository of decision 0022 (plan leaf E-05.7), whose
    entry is its own so that G-03.1 can change one without the other. Any other repository, or another branch, is
    NOT_DECLARED."""
    builder = roles.DECLARATIONS.get(repository) if isinstance(repository, str) else None
    if builder is None:
        raise Unverifiable('NOT_DECLARED', f'{repository!r} has no protection declaration (declared: '
                           f'{", ".join(roles.DECLARATIONS)})')
    declared = builder()
    if base != declared['base']:
        raise Unverifiable('NOT_DECLARED', f'{base!r} is not the protected branch of {repository} '
                           f'({declared["base"]})')
    return {'repository': repository, 'base': base, 'rules': declared['rules'], 'settings': declared['settings'],
            'collaborators': declared['collaborators'], 'teams': declared['teams'],
            'deploy_keys': declared['deploy_keys']}


# The baseline digest each repository's check was recorded with: the fixture's from Owner decision OA-16, Act B
# (2026-11-12; decision 0012, Current facts 1), equal before and after P-04.2's recorded merge. The authorization
# repository's is recorded by Owner act OA-30's read-only check, not here.
RECORDED_BASELINES = types.MappingProxyType({
    roles.FIXTURE_REPOSITORY: 'sha256:5dd7ace780ca0878146915ed74e8761b432e4489f20cdfe9a243804ad5aa6e42'})


# ---------------------------------------------------------------------------- precedence at the pin


def is_plain(rule_name):
    """Gitea 28.3.0 IsRuleNameSpecial: a name with none of * ? \\ [ ] { } is a plain branch name."""
    return not any(c in rule_name for c in '*?\\[]{}')


def glob_regex(pattern):
    """modules/glob Compile(pattern, '/') of Gitea 28.3.0 as a Python regular expression: ``**`` any sequence,
    ``*`` any sequence without ``/``, ``?`` one character but ``/``, ``[...]`` (``[!...]``) a class, ``{a,b}``
    alternatives, ``\\`` escapes the next character. Unverifiable when it does not compile."""
    out, pos, depth = ['^'], 0, 0
    try:
        while pos < len(pattern):
            c = pattern[pos]
            pos += 1
            if depth and c == '}':
                out.append(')')
                depth -= 1
            elif c == '*':
                if pos < len(pattern) and pattern[pos] == '*':
                    pos += 1
                    out.append('.*')
                else:
                    out.append('[^/]*')
            elif c == '?':
                out.append('[^/]')
            elif c == '[':
                out.append('[')
                if pos < len(pattern) and pattern[pos] == '!':
                    pos += 1
                    out.append('^')
                while True:
                    c = pattern[pos]  # IndexError: an unterminated class
                    pos += 1
                    if c == ']':
                        out.append(']')
                        break
                    if c == '\\':
                        out.append('\\' + pattern[pos])
                        pos += 1
                    else:
                        out.append('\\[' if c == '[' else c)
            elif c == '{':
                out.append('(?:')
                depth += 1
            elif c == ',' and depth:
                out.append('|')
            elif c == '\\':
                out.append(re.escape(pattern[pos]))
                pos += 1
            else:
                out.append(re.escape(c))
        if depth:
            raise ValueError('an unterminated alternative')
        out.append('$')
        return re.compile(''.join(out))
    except (IndexError, ValueError, re.error) as exc:
        raise Unverifiable('PRECEDENCE_UNVERIFIED', f'the rule name {pattern!r} is a glob the check cannot '
                           f'evaluate ({type(exc).__name__})') from None


def matches(rule_name, branch):
    if is_plain(rule_name):
        return rule_name.casefold() == branch.casefold()
    return glob_regex(rule_name).match(branch) is not None


def precedence(rules, branch):
    """The rules that match BRANCH, in the order Gitea 28.3.0 evaluates them (priority, then a plain name
    before a glob, then the earlier created; the first is enforced)."""
    ordered = sorted(rules, key=lambda r: (r['priority'], not is_plain(r['rule_name']), str(r.get('created_at'))))
    return [r['rule_name'] for r in ordered if matches(r['rule_name'], branch)]


# ---------------------------------------------------------------------------- the session


class AuditSession:
    """The auditor's API session for one check: the token in the Authorization header of a fixed set of
    GET requests over one keep-alive connection to 127.0.0.1:PORT (HTTP, a callable with
    gitea_host.http_get's signature, stands in for it in tests). Nothing but those reads can be sent."""

    def __init__(self, port, token, repository, base, http: Callable | None = None):
        if not SEGMENT.fullmatch(repository.partition('/')[0]) or not SEGMENT.fullmatch(repository.partition('/')[2]) \
                or not BRANCH.fullmatch(base):
            raise ValueError(f'{repository!r} {base!r} is not a repository and branch the check reads')
        repo = re.escape(f'/repos/{repository}')
        self._reads = tuple(re.compile(p) for p in (
            r'/token', repo, repo + r'/branch_protections', repo + '/branches/' + re.escape(urllib.parse.quote(base)),
            repo + r'/collaborators\?' + re.escape(PAGE), repo + r'/collaborators/' + LOGIN.pattern + '/permission',
            repo + r'/teams', repo + r'/keys\?' + re.escape(PAGE)))
        self._port, self._token, self._http, self._connection = port, token, http, None

    def close(self):
        self._token = None
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def request(self, method, path):
        """(status, lower-cased headers, parsed JSON or _NOT_JSON) of one of the fixed reads."""
        if method != 'GET' or self._token is None or not any(p.fullmatch(path) for p in self._reads):
            raise ValueError(f'{method} {path} is not a read of the protection check')
        headers = {'Accept': 'application/json', 'Authorization': 'token ' + self._token}
        try:
            status, answer_headers, payload = self._send(path, headers)
        except (OSError, http.client.HTTPException) as exc:
            raise Unverifiable('READ_FAILED', f'GET {path}: the answer was lost ({type(exc).__name__})') from None
        try:
            parsed = json.loads(payload) if payload else None
        except ValueError:
            parsed = _NOT_JSON
        return status, answer_headers, parsed

    def get(self, path):
        return self.request('GET', path)

    def _send(self, path, headers):
        if self._http is not None:
            status, answer_headers, payload = self._http(self._port, '/api/v1' + path, method='GET', body=None,
                                                         headers=headers, timeout=TIMEOUT_S)
            return status, {k.lower(): v for k, v in answer_headers.items()}, payload
        # One keep-alive connection per check; a read on a connection Gitea closed while idle is sent once more.
        reused = self._connection is not None
        if not reused:
            self._connection = http.client.HTTPConnection(host.LOOPBACK, self._port, timeout=TIMEOUT_S)
        try:
            return self._exchange(path, headers)
        except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            self._connection.close()
            self._connection = None
            if not reused:
                raise
        self._connection = http.client.HTTPConnection(host.LOOPBACK, self._port, timeout=TIMEOUT_S)
        return self._exchange(path, headers)

    def _exchange(self, path, headers):
        self._connection.request('GET', '/api/v1' + path, headers=headers)
        response = self._connection.getresponse()
        payload = response.read()
        if response.will_close:
            self._connection.close()
            self._connection = None
        return response.status, {k.lower(): v for k, v in response.getheaders()}, payload


# ---------------------------------------------------------------------------- reading


def read_entry(provider):
    """The auditor's token from its entry: missing, naming another account or not token-shaped is refused
    before anything is sent."""
    try:
        token = roles.read_token(provider, ROLE)
    except roles.GiteaError as exc:
        raise Unverifiable('CREDENTIAL_REFUSED', f'{ENTRY!r} is refused ({exc.code}): it must name {AUDITOR}') \
            from None
    if token is None:
        raise Unverifiable('CREDENTIAL_MISSING', f'no credential provider entry {ENTRY!r} ({CREDENTIAL}): the '
                           'protection auditor is not provisioned (gitea_roles.py provision, an Owner act under '
                           'OA-16)')
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise Unverifiable('CREDENTIAL_REFUSED', f'{ENTRY!r} does not hold a Gitea token (40 lower-case '
                           'hexadecimal digits)')
    return token


def _ok(status, payload, what, kind):
    if status != 200:
        message = payload.get('message') if isinstance(payload, dict) else None
        raise Unverifiable('READ_FAILED', f'{what} answered {status}' + (f' ({str(message)[:120]})' if message else ''))
    if payload is _NOT_JSON or not isinstance(payload, kind):
        raise Unverifiable('READ_FAILED', f'{what} answered 200 without a JSON {kind.__name__}')
    return payload


def _keys(view, known, what, optional=frozenset()):
    unknown, missing = sorted(set(view) - known), sorted(known - optional - set(view))
    if unknown:
        raise Unverifiable('VIEW_INVALID', f'{what} has field(s) Gitea 28.3.0 does not have: {unknown}')
    if missing:
        raise Unverifiable('VIEW_INVALID', f'{what} lacks field(s): {missing}')


def _total(headers, items, what):
    total = headers.get('x-total-count')
    if total is None or not str(total).isdigit() or int(total) != len(items):
        raise Unverifiable('VIEW_INVALID', f'{what}: X-Total-Count is {total!r} and {len(items)} are listed: the '
                           'list is not read whole')


def _rule(view, index):
    what = f'branch protection rule #{index + 1}'
    if not isinstance(view, dict):
        raise Unverifiable('VIEW_INVALID', f'{what} is not an object')
    name = view.get('rule_name')
    if isinstance(name, str):
        what = f'branch protection rule {name!r}'
    _keys(view, RULE_KEYS, what)
    rule = {}
    for field in FIELDS:
        value = view[field]
        if field in LIST_FIELDS:
            value = [] if value is None else value
            ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
        elif field in NUMBER_FIELDS:
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif field in TEXT_FIELDS:
            ok = isinstance(value, str)
        else:
            ok = isinstance(value, bool)
        if not ok:
            raise Unverifiable('VIEW_INVALID', f'{what}: {field} is {type(value).__name__}')
        rule[field] = value
    if view['branch_name'] != ('' if not is_plain(rule['rule_name']) else rule['rule_name']):
        raise Unverifiable('VIEW_INVALID', f'{what}: branch_name {view["branch_name"]!r} is not what Gitea derives '
                           'from its rule name')
    rule['created_at'] = view['created_at']
    return rule


def observe(session, repository, base):
    """What Gitea reports, read as the auditor; Unverifiable on anything the check cannot establish."""
    status, _, token = session.get('/token')
    if status == 401:
        raise Unverifiable('CREDENTIAL_REJECTED', 'GET /token answered 401: Gitea does not accept the auditor\'s '
                           'token (revoked, or not this instance\'s)')
    token = _ok(status, token, 'GET /token', dict)
    _keys(token, TOKEN_KEYS, 'GET /token')
    login = token['user'].get('login') if isinstance(token['user'], dict) else None
    scopes = token['scopes']
    if login != AUDITOR:
        raise Unverifiable('AUDITOR_INVALID', f'the token authenticates as {login!r}, not {AUDITOR}')
    if not isinstance(scopes, list) or sorted(map(str, scopes)) != SCOPES:
        raise Unverifiable('AUDITOR_INVALID', f'the token\'s scopes are {scopes!r}, not exactly {SCOPES}')

    status, _, repo = session.get(f'/repos/{repository}')
    repo = _ok(status, repo, f'GET /repos/{repository}', dict)
    _keys(repo, REPOSITORY_KEYS, f'the repository {repository}', REPOSITORY_OPTIONAL)
    if repo['full_name'] != repository:
        raise Unverifiable('VIEW_INVALID', f'the repository answers as {repo["full_name"]!r}, not {repository}')
    permissions = repo.get('permissions')
    if not isinstance(permissions, dict) or permissions.get('admin') is not True:
        raise Unverifiable('AUDITOR_INVALID', f'{AUDITOR} is not a repository administrator of {repository} '
                           f'(permissions {permissions!r}): Gitea does not serve it the protection rules')

    status, _, views = session.get(f'/repos/{repository}/branch_protections')
    views = _ok(status, views, 'GET branch_protections', list)
    rules = [_rule(view, n) for n, view in enumerate(views)]
    names = [r['rule_name'] for r in rules]
    if len(set(names)) != len(names):
        raise Unverifiable('VIEW_INVALID', f'the rule names repeat: {names}')

    status, _, branch = session.get(f'/repos/{repository}/branches/{urllib.parse.quote(base)}')
    branch = _ok(status, branch, f'GET the branch {base}', dict)
    _keys(branch, BRANCH_KEYS, f'the branch {base}')
    if not isinstance(branch['protected'], bool) or not isinstance(branch['effective_branch_protection_name'], str):
        raise Unverifiable('VIEW_INVALID', f'the branch {base}: protected or effective_branch_protection_name has '
                           'another type')

    status, headers, listed = session.get(f'/repos/{repository}/collaborators?{PAGE}')
    listed = _ok(status, listed, 'GET collaborators', list)
    _total(headers, listed, 'the collaborators')
    logins = [c.get('login') if isinstance(c, dict) else None for c in listed]
    if not all(isinstance(x, str) and LOGIN.fullmatch(x) for x in logins) or len(set(logins)) != len(logins):
        raise Unverifiable('VIEW_INVALID', f'the collaborators are not a list of distinct logins: {logins!r}')
    collaborators = {}
    for user in logins:
        status, _, view = session.get(f'/repos/{repository}/collaborators/{user}/permission')
        view = _ok(status, view, f'GET the permission of {user}', dict)
        _keys(view, PERMISSION_KEYS, f'the permission of {user}')
        if view['permission'] not in ACCESS_LEVELS:
            raise Unverifiable('VIEW_INVALID', f'the permission of {user} is {view["permission"]!r}')
        collaborators[user] = view['permission']

    status, _, teams_view = session.get(f'/repos/{repository}/teams')
    teams_view = _ok(status, teams_view, 'GET teams', list)
    teams = {}
    for team in teams_view:
        if not isinstance(team, dict):
            raise Unverifiable('VIEW_INVALID', 'a team is not an object')
        _keys(team, TEAM_KEYS, f'the team {team.get("name")!r}')
        if not isinstance(team['name'], str) or team['name'] in teams or team['permission'] not in ACCESS_LEVELS:
            raise Unverifiable('VIEW_INVALID', f'the team {team["name"]!r} (permission {team["permission"]!r})')
        teams[team['name']] = team['permission']

    status, headers, keys = session.get(f'/repos/{repository}/keys?{PAGE}')
    keys = _ok(status, keys, 'GET keys', list)
    _total(headers, keys, 'the deploy keys')
    deploy_keys = [{k: key.get(k) for k in ('id', 'title', 'key_type', 'read_only', 'fingerprint')}
                   if isinstance(key, dict) else {'malformed': True} for key in keys]
    return {'auditor': {'login': login, 'scopes': sorted(scopes), 'admin': True}, 'repository': repo,
            'rules': rules, 'branch': branch, 'collaborators': collaborators, 'teams': teams,
            'deploy_keys': deploy_keys}


# ---------------------------------------------------------------------------- judging


def _normal(rule):
    return {f: sorted(rule[f]) if f in LIST_FIELDS else rule[f] for f in FIELDS}


def judge(expected, observed):
    """The verdict on OBSERVED against the declaration EXPECTED."""
    problems = []
    base = expected['base']
    declared = {r['rule_name']: _normal(r) for r in expected['rules']}
    seen = {r['rule_name']: _normal(r) for r in observed['rules']}
    for name in sorted(set(seen) - set(declared)):
        problems.append(f'rule {name!r} (priority {seen[name]["priority"]}) is not declared')
    for name in sorted(set(declared) - set(seen)):
        problems.append(f'the declared rule {name!r} is missing')
    for name in sorted(set(declared) & set(seen)):
        for field in FIELDS:
            if seen[name][field] != declared[name][field]:
                problems.append(f'{name}.{field} is {seen[name][field]!r}, declared {declared[name][field]!r}')
    # precedence: the rules that match the protected branch, in Gitea's order, and the one it enforces
    observed_order = precedence(observed['rules'], base)
    declared_order = precedence(expected['rules'], base)
    effective = observed['branch']['effective_branch_protection_name']
    if (observed_order[0] if observed_order else '') != effective:
        raise Unverifiable('PRECEDENCE_UNVERIFIED', f'Gitea enforces {effective!r} on {base}, but the rules it '
                           f'reports order as {observed_order} at this pin: the check\'s precedence model '
                           'disagrees with Gitea')
    if observed_order != declared_order:
        problems.append(f'the rules matching {base} in Gitea\'s order are {observed_order}, declared '
                        f'{declared_order}')
    if effective != declared_order[0]:
        problems.append(f'Gitea enforces the rule {effective!r} on {base}, declared {declared_order[0]!r}')
    if observed['branch']['protected'] is not True:
        problems.append(f'the branch {base} is not protected')
    repo = observed['repository']
    settings = {k: repo[k] for k in expected['settings']}
    for key, want in expected['settings'].items():
        if settings[key] != want:
            problems.append(f'the repository\'s {key} is {settings[key]!r}, declared {want!r}')
    collaborators = observed['collaborators']
    for user in sorted(set(collaborators) | set(expected['collaborators'])):
        got, want = collaborators.get(user), expected['collaborators'].get(user)
        if got != want:
            problems.append(f'collaborator {user}: {got or "absent"}, declared {want or "absent"}')
    for name in sorted(set(observed['teams']) | set(expected['teams'])):
        got, want = observed['teams'].get(name), expected['teams'].get(name)
        if got != want:
            problems.append(f'team {name}: {got or "absent"}, declared {want or "absent"}')
    for key in observed['deploy_keys']:
        problems.append(f'a deploy key is present ({key})')
    state = {'format': FORMAT, 'repository': expected['repository'], 'base': base, 'auditor': observed['auditor'],
             'settings': settings, 'rules': [seen[name] for name in sorted(seen)], 'effective': effective,
             'protected': observed['branch']['protected'], 'collaborators': collaborators,
             'teams': observed['teams'], 'deploy_keys': sorted(observed['deploy_keys'], key=json.dumps)}
    digest = 'sha256:' + hashlib.sha256(json.dumps(state, sort_keys=True, separators=(',', ':'),
                                                   ensure_ascii=True).encode('ascii')).hexdigest()
    if problems:
        return Verdict('drift', 'DRIFT', f'{len(problems)} difference(s) from the declaration: '
                       + '; '.join(problems), digest, tuple(problems))
    return Verdict('verified', 'VERIFIED', f'as declared: {len(seen)} rules x {len(FIELDS)} fields and the exact '
                   f'rule set; {base} enforces {effective!r} (matching in order: {observed_order}); '
                   f'{len(settings)} repository settings; {len(collaborators)} collaborators; teams '
                   f'{sorted(observed["teams"])}; no deploy key; read as {AUDITOR} (read:repository, repository '
                   'administrator)', digest)


def verify(provider, port, repository, base, *, http: Callable | None = None):
    """The check, once: read the auditor's entry, read Gitea, judge. Never raises Unverifiable: whatever the
    check cannot establish is an unverified Verdict."""
    try:
        expected = declaration(repository, base)
        token = read_entry(provider)
        session = AuditSession(port, token, repository, base, http)
        del token
        try:
            observed = observe(session, repository, base)
        finally:
            session.close()
        return judge(expected, observed)
    except Unverifiable as exc:
        return Verdict('unverified', exc.code, exc.detail, None, (exc.detail,))


# ---------------------------------------------------------------------------- command line


def main(argv=None, out=None, err=None) -> int:
    parser = argparse.ArgumentParser(prog='protection_check.py', description='The read-only protection check of '
                                     'decision 0012 point 6 (Owner decision OA-16), as the protection auditor. Exit 0 '
                                     'verified, 1 drift, 2 unverified or refused.')
    sub = parser.add_subparsers(dest='command', required=True)
    v = sub.add_parser('verify', help='read and compare the protection of an admitted repository; prints the verdict')
    v.add_argument('repository', help='OWNER/NAME')
    v.add_argument('--base', default=roles.DEFAULT_BRANCH, help='the protected branch (default: main)')
    v.add_argument('--port', type=int, help='the Gitea port (default: the managed Gitea\'s host record)')
    args = parser.parse_args(argv)
    out, err = out or sys.stdout, err or sys.stderr
    if out is sys.stdout and hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')
    guard = host.ACT_GUARD = host.contract.ExposureGuard()  # the provider holds the token it reads
    report, message, code = None, '', 2
    try:
        port = args.port
        if port is None:
            port = host.read_host_record(host.layout(host.paths.resolve()))['port']
        verdict = verify(host.credential_provider(), port, args.repository, args.base)
        report = verdict._asdict()
        code = {'verified': 0, 'drift': 1}.get(verdict.status, 2)
    except host.paths.PathsError as exc:
        message = f'protection-check: {exc}\n'
    except host.GiteaError as exc:
        message = f'protection-check: {roles.redact(str(exc))}\n'
    finally:
        host.ACT_GUARD = None
    text = '' if report is None else json.dumps(report, indent=2, ensure_ascii=False) + '\n'
    scan = host.exposure_scan(guard, text, message)
    guard.clear()
    if scan['found_in']:
        err.write('protection-check: EXPOSURE_FOUND: a secret the check held is in its '
                  + ' and '.join(scan['found_in']) + '\n')
        return 1
    err.write(message)
    out.write(text)
    err.write(f'protection-check: I7 no-exposure scan: clean ({scan["secrets_held"]} secrets held; '
              f'{scan["scanned"]} outputs scanned)\n')
    return code


if __name__ == '__main__':
    sys.exit(main())
