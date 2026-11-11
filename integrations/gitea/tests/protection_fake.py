"""A fake Gitea 28.3.0 for the protection check (protection_check.py; Owner decision OA-16).

``ProtectionGitea`` models what the protection auditor reads, with the behaviour read in the pinned source
(gitea-src-28.3.0; see evidence/P-04.2-protection-verifier.md): token authentication (a token of a Bot as
``Authorization: token`` or as a basic-authentication password, with the same scopes; any other basic
authentication 401); the scope rule of ``tokenRequiresScopes`` (the category from the route, the level from
the method: GET and HEAD read, POST, PUT, PATCH and DELETE write; ``all`` and a write scope imply the read
scope; ``/token`` needs none) with Gitea's 403 text; ``sudo`` refused to a non-administrator; ``reqAdmin``
(the branch protection rules and the deploy keys: repository administrators only, 403 with Gitea's text);
a restricted account sees only the repository it collaborates on (404 elsewhere); and the views of
``GET /token``, the repository (every top-level field of 28.3.0's Repository; its permissions from the
caller's collaboration), the rules (the full 37-field BranchProtection view, ``branch_name`` empty for a
glob), the branch (``effective_branch_protection_name`` for an administrator only), the collaborators and
the deploy keys with ``X-Total-Count``, a collaborator's permission (an administrator may ask for anyone's,
others only their own), and the teams with access.

Which rule a branch enforces is computed here independently of protection_check.py: the rules in Gitea's
order (priority, then a plain name before a glob, then creation) and a small matcher for the globs the
tests use (``*`` within a segment, ``**`` across segments, literals); ``effective`` overrides it.

Faults: ``faults[route] = status | 'drop' | 'not-json' | 'wrong-kind' | 'no-total'`` answers that read
instead (route one of ROUTES). Callable in memory with gitea_host.http_get's signature (a dropped answer
raises ConnectionResetError) and through ``handle`` (DROP) for an HTTP server. Every value is synthetic.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import threading
import urllib.parse

REPOSITORY = 'aieh-authz-fixture/authz'
AUDITOR = 'aieh-bot-protection-audit'
VERIFIER = 'aieh-bot-verifier'
OWNER = 'aieh-owner'


def synthetic_token(user):
    """The synthetic token of a fake bot (40 hex digits; the owner fake uses the same rule)."""
    return hashlib.sha1(f'synthetic token {user}'.encode()).hexdigest()


AUDIT_TOKEN = synthetic_token(AUDITOR)
VERIFIER_TOKEN = synthetic_token(VERIFIER)
DROP = object()
ROUTES = ('token', 'repository', 'rules', 'branch', 'collaborators', 'permission', 'teams', 'keys')
SCOPE_TEXT = 'token does not have at least one of required scope(s), required=[{required}], token scope={scope}'
ADMIN_TEXT = 'user should be an owner or a collaborator with admin write of a repository'
SUDO_TEXT = 'Only administrators allowed to sudo.'
CREATED = '2026-11-07T10:00:0{n}Z'


def repository_view(settings):
    """Every top-level field of Gitea 28.3.0's Repository view (omitempty ones absent), SETTINGS over it."""
    view = {
        'id': 2, 'owner': {'id': 3, 'login': 'aieh-authz-fixture'}, 'name': 'authz', 'full_name': REPOSITORY,
        'description': '', 'empty': False, 'private': True, 'fork': False, 'template': False, 'mirror': False,
        'size': 25, 'language': '', 'languages_url': '', 'html_url': '', 'url': '', 'link': '', 'ssh_url': '',
        'clone_url': '', 'original_url': '', 'website': '', 'stars_count': 0, 'forks_count': 0,
        'watchers_count': 1, 'branch_count': 3, 'open_issues_count': 0, 'open_pr_counter': 1, 'release_counter': 0,
        'default_branch': 'main', 'archived': False, 'created_at': CREATED.format(n=0),
        'updated_at': CREATED.format(n=1), 'archived_at': '1970-01-01T00:00:00Z', 'has_code': True,
        'has_issues': True, 'has_wiki': True, 'has_pull_requests': True, 'has_projects': True,
        'projects_mode': 'all', 'has_releases': True, 'has_packages': True, 'has_actions': False,
        'ignore_whitespace_conflicts': False, 'allow_merge_commits': True, 'allow_rebase': True,
        'allow_rebase_explicit': True, 'allow_squash_merge': True, 'allow_fast_forward_only_merge': True,
        'allow_merge_update': True, 'allow_rebase_update': True, 'allow_manual_merge': True,
        'autodetect_manual_merge': False, 'default_delete_branch_after_merge': False,
        'default_merge_style': 'merge', 'default_update_style': 'merge', 'default_allow_maintainer_edit': False,
        'avatar_url': '', 'internal': False, 'mirror_interval': '', 'object_format_name': 'sha1',
        'mirror_updated': '0001-01-01T00:00:00Z', 'mirror_last_sync_at': '0001-01-01T00:00:00Z', 'topics': [],
        'licenses': []}
    view.update(settings)
    return view


def special(name):
    return any(c in name for c in '*?\\[]{}')


def rule_view(rule, n):
    """Gitea's API view of a rule: the 34 fields, branch_name ('' for a glob), created_at and updated_at."""
    return {'branch_name': '' if special(rule['rule_name']) else rule['rule_name'], **copy.deepcopy(rule),
            'created_at': CREATED.format(n=n), 'updated_at': CREATED.format(n=n)}


def team_view(name, permission, team_id=1):
    return {'id': team_id, 'name': name, 'description': '', 'organization': None,
            'includes_all_repositories': name == 'Owners', 'permission': permission,
            'units': ['repo.code', 'repo.pulls'], 'units_map': {'repo.code': permission, 'repo.pulls': permission},
            'can_create_org_repo': name == 'Owners', 'visibility': 'private'}


def _order(rule):
    """Gitea's order of the rules (a rule a test damaged sorts last)."""
    try:
        if isinstance(rule['priority'], int) and isinstance(rule['rule_name'], str):
            return 0, rule['priority'], special(rule['rule_name']), str(rule['created_at'])
    except (KeyError, TypeError):
        pass
    return 1, 0, False, ''


def _fake_match(name, branch):
    if not special(name):
        return name.lower() == branch.lower()
    pattern = ''.join('.*' if part == '**' else '[^/]*' if part == '*' else re.escape(part)
                      for part in re.split(r'(\*\*|\*)', name))
    return re.fullmatch(pattern, branch) is not None


class ProtectionGitea:
    def __init__(self, roles):
        self.tokens = {AUDIT_TOKEN: {'login': AUDITOR, 'scopes': ['read:repository'], 'name': 'aieh-protection-audit-x'},
                       VERIFIER_TOKEN: {'login': VERIFIER, 'scopes': ['read:repository'], 'name': 'aieh-verifier-x'}}
        self.repo = repository_view(roles.repository_settings())
        self.rules = [rule_view(rule, n + 2) for n, rule in enumerate(roles.protection_rules())]
        self.collaborators = dict(roles.collaborators())
        self.teams = [team_view('Owners', 'owner')]
        self.keys = []
        self.effective = None   # overrides the rule the branch enforces
        self.faults = {}
        self.requests = []
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ helpers for the tests

    def rule(self, name):
        return next(r for r in self.rules if r['rule_name'] == name)

    def enforced(self, branch):
        if self.effective is not None:
            return self.effective
        ordered = sorted(self.rules, key=_order)
        return next((r['rule_name'] for r in ordered if _order(r)[0] == 0 and isinstance(r['rule_name'], str)
                     and _fake_match(r['rule_name'], branch)), '')

    # ------------------------------------------------------------------ HTTP

    def __call__(self, port, path, *, method='GET', body=None, headers=None, timeout=5.0):
        answer = self.handle(method, path, headers or {}, body)
        if answer is DROP:
            raise ConnectionResetError('the fake Gitea dropped the connection without an answer')
        return answer

    def handle(self, method, path, headers, body):
        with self.lock:
            return self._handle(method, path, {k.lower(): v for k, v in headers.items()}, body)

    @staticmethod
    def reply(status, payload, extra=None):
        data = b'' if payload is None else json.dumps(payload).encode()
        return status, {'content-type': 'application/json', **(extra or {})}, data

    def doer(self, headers):
        auth = headers.get('authorization', '')
        if auth.startswith('token '):
            entry = self.tokens.get(auth[6:])
            return (entry, 'token') if entry else (None, 'token')
        if auth.startswith('Basic '):
            user, _, password = base64.b64decode(auth[6:]).decode('utf-8', 'replace').partition(':')
            entry = self.tokens.get(password)
            return (entry, 'basic') if entry and entry['login'] == user else (None, 'basic')
        return None, None

    @staticmethod
    def category(route):
        for prefix, name in (('/repos', 'repository'), ('/repositories', 'repository'), ('/user', 'user'),
                             ('/users', 'user'), ('/admin', 'admin'), ('/orgs', 'organization'),
                             ('/teams', 'organization')):
            if route == prefix or route.startswith(prefix + '/') or route.startswith(prefix + '?'):
                return name
        return None

    @staticmethod
    def has_scope(scopes, level, category):
        return 'all' in scopes or f'{level}:{category}' in scopes or (level == 'read' and f'write:{category}' in scopes)

    def fault(self, route):
        fault = self.faults.get(route)
        if fault is None:
            return None
        if fault == 'drop':
            return DROP
        if fault == 'not-json':
            return 200, {'content-type': 'text/html'}, b'<html>not json</html>'
        if fault == 'wrong-kind':
            return self.reply(200, {'not': 'the expected kind'} if route not in ('token', 'repository', 'branch',
                                                                                 'permission') else ['a list'])
        if isinstance(fault, int):
            return self.reply(fault, {'message': f'a fault of the fake ({fault})'})
        return None

    def _handle(self, method, path, headers, body):
        doer, kind = self.doer(headers)
        parsed = urllib.parse.urlsplit(path)
        route = parsed.path.removeprefix('/api/v1')
        query = dict(urllib.parse.parse_qsl(parsed.query))
        self.requests.append({'method': method, 'path': path.removeprefix('/api/v1'), 'auth': kind,
                              'doer': doer['login'] if doer else None})
        if doer is None:
            return self.reply(401, {'message': 'token is required'})
        if 'sudo' in headers or 'sudo' in query:
            return self.reply(403, {'message': SUDO_TEXT})
        category = self.category(route)
        if category is not None:
            level = 'read' if method in ('GET', 'HEAD') else 'write'
            if not self.has_scope(doer['scopes'], level, category):
                return self.reply(403, {'message': SCOPE_TEXT.format(required=f'{level}:{category}',
                                                                     scope=','.join(doer['scopes']))})
        login = doer['login']
        if route == '/token':
            if method != 'GET':
                return self.reply(405, {'message': 'the fake does not delete tokens'})
            return self.fault('token') or self.reply(200, {
                'id': 7, 'name': doer['name'], 'scopes': list(doer['scopes']), 'created_at': CREATED.format(n=5),
                'last_used_at': CREATED.format(n=6), 'user': {'id': 9, 'login': login}})
        repo = f'/repos/{REPOSITORY}'
        if not (route == repo or route.startswith(repo + '/')):
            return self.reply(404, {'message': 'not found (a restricted account sees only its repositories)'})
        permission = self.collaborators.get(login)
        if permission is None:
            return self.reply(404, {'message': 'not found'})
        admin = permission in ('admin', 'owner')
        if method != 'GET':
            return self.reply(405, {'message': f'the fake models no write ({method} {route})'})
        rest = route[len(repo):]
        if rest == '':
            return self.fault('repository') or self.reply(200, {
                **self.repo, 'permissions': {'admin': admin, 'push': permission != 'read', 'pull': True}})
        if rest == '/branch_protections':
            if not admin:
                return self.reply(403, {'message': ADMIN_TEXT})
            ordered = sorted(self.rules, key=_order)
            return self.fault('rules') or self.reply(200, copy.deepcopy(ordered))
        if rest.startswith('/branches/'):
            name = urllib.parse.unquote(rest[len('/branches/'):])
            if name != 'main':
                return self.reply(404, {'message': 'branch not found'})
            effective = self.enforced(name)
            rule = next((r for r in self.rules if r['rule_name'] == effective), None)
            return self.fault('branch') or self.reply(200, {
                'name': name, 'commit': {'id': 'c' * 40}, 'protected': rule is not None,
                'required_approvals': rule['required_approvals'] if rule else 0,
                'enable_status_check': rule['enable_status_check'] if rule else False,
                'status_check_contexts': rule['status_check_contexts'] if rule else [],
                'user_can_push': False, 'user_can_merge': False,
                'effective_branch_protection_name': effective if admin else ''})
        if rest == '/collaborators':
            listed = [{'id': n + 20, 'login': user, 'full_name': '', 'email': ''}
                      for n, user in enumerate(self.collaborators)]
            total = {'x-total-count': str(len(listed))}
            if self.faults.get('collaborators') == 'no-total':
                total = {}
            return self.fault('collaborators') or self.reply(200, listed, total)
        if rest.startswith('/collaborators/') and rest.endswith('/permission'):
            user = rest[len('/collaborators/'):-len('/permission')]
            if not admin and user != login:
                return self.reply(403, {'message': 'Only admins can query all permissions, repo admins can query all '
                                                   'repo permissions, collaborators can query only their own'})
            level = self.collaborators.get(user, 'none')
            return self.fault('permission') or self.reply(200, {'permission': level, 'role_name': level,
                                                                'user': {'login': user}})
        if rest == '/teams':
            return self.fault('teams') or self.reply(200, copy.deepcopy(self.teams))
        if rest == '/keys':
            if not admin:
                return self.reply(403, {'message': ADMIN_TEXT})
            total = {} if self.faults.get('keys') == 'no-total' else {'x-total-count': str(len(self.keys))}
            return self.fault('keys') or self.reply(200, copy.deepcopy(self.keys), total)
        return self.reply(404, {'message': f'no route {method} {route}'})
