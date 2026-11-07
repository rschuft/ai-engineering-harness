"""Live authorization tests of the role bots against the running Gitea (plan leaf S-01.2.2).

Opt-in: they run only with AIEH_GITEA_AUTHZ=1 (`task gitea:authz`), on Windows, while Gitea answers
and every bot's Credential Manager entry (`AIEH Gitea bot <role>`) exists. Otherwise each class skips
with its reason, so the ordinary suites never read Credential Manager or write to Gitea. The tests
that need the fixture repository (gitea_roles.py fixture) also skip, with their reason, while it is
absent: creating it is site administration, which Gitea refuses until the site administrator's first
sign-in.

Tokens are read from Credential Manager into memory and sent only in Authorization headers (git
receives an http.extraHeader through GIT_CONFIG_* environment variables of its own process); nothing
prints, logs or asserts on a token. AIEH_GITEA_AUTHZ_REPORT, when set, names a JSON file that
receives every probe (role, action, expectation, HTTP status or git exit code, Gitea's message).
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


G = _load('aieh_gitea_host', HERE.parent / 'gitea_host.py')
R = _load('aieh_gitea_roles', HERE.parent / 'gitea_roles.py')
OPT_IN = os.environ.get('AIEH_GITEA_AUTHZ') == '1'
REPORT = os.environ.get('AIEH_GITEA_AUTHZ_REPORT')
RESULTS: list[dict] = []
DENIED = (401, 403, 404, 405, 409, 422)
REPO = f'/repos/{R.FIXTURE_ORG}/{R.FIXTURE_REPO}'
_LIVE: list = []


def live():
    """(context, None) when the live suite can run, else (None, the reason it skips)."""
    if _LIVE:
        return _LIVE[0]
    result = _probe_live()
    _LIVE.append(result)
    return result


def _probe_live():
    if not OPT_IN:
        return None, 'live authorization tests are opt-in: AIEH_GITEA_AUTHZ=1 (task gitea:authz)'
    if os.name != 'nt':
        return None, 'the bot tokens are in Windows Credential Manager'
    try:
        res = G.paths.resolve()
        lay, pinned = G.layout(res), G.pin()
        port = G.read_host_record(lay)['port']
    except (G.GiteaError, G.paths.PathsError) as exc:
        return None, f'Gitea is not installed here ({exc})'
    if not G.healthy(port):
        return None, 'Gitea is not running (task gitea:up)'
    store = G.CredentialStore()
    tokens = {role: R.read_token(store, role) for role in R.ROLES}
    if missing := sorted(role for role, token in tokens.items() if token is None):
        return None, f'no Credential Manager entry for {missing} (gitea_roles.py provision)'
    return SimpleNamespace(port=port, tokens=tokens, cli=R.Cli(lay, pinned)), None


def tearDownModule():
    if REPORT and RESULTS:
        Path(REPORT).write_text(json.dumps(RESULTS, indent=1) + '\n', encoding='utf-8')


def message(payload) -> str:
    if isinstance(payload, dict):
        return R.redact(str(payload.get('message', '')))[:160]
    if isinstance(payload, list):
        return f'list of {len(payload)}'
    return R.redact(str(payload))[:160]


class Live(unittest.TestCase):
    """A class of the live suite: skips with the reason when it cannot run."""

    @classmethod
    def setUpClass(cls):
        ctx, reason = live()
        if ctx is None:
            raise unittest.SkipTest(reason)
        cls.ctx = ctx

    def api(self, role: str | None) -> R.Api:
        return R.Api(self.ctx.port, None if role is None else self.ctx.tokens[role])

    def call(self, role, action, expect, method, path, body=None, headers=None):
        status, payload = self.api(role).call(method, path, body, headers)
        RESULTS.append({'role': role or 'anonymous', 'action': action, 'expected': expect, 'status': status,
                        'message': message(payload)})
        return status, payload

    def denied(self, role, action, method, path, body=None, headers=None):
        status, payload = self.call(role, action, 'denied', method, path, body, headers)
        self.assertIn(status, DENIED, f'{role}: {action} answered {status} ({message(payload)})')
        return status, payload

    def allowed(self, role, action, method, path, body=None, headers=None, codes=(200, 201, 204)):
        status, payload = self.call(role, action, 'allowed', method, path, body, headers)
        self.assertIn(status, codes, f'{role}: {action} answered {status} ({message(payload)})')
        return status, payload


class TestTokens(Live):
    def test_each_token_is_its_own_bot_with_the_matrix_scopes(self):
        users = self.ctx.cli.users()
        for role, spec in R.ROLES.items():
            with self.subTest(role=role):
                status, body = self.allowed(role, 'read its own token (GET /token)', 'GET', '/token')
                self.assertEqual(sorted(body['scopes']), sorted(spec['scopes']))
                self.assertTrue(body['name'].startswith(f'aieh-{role}-'))
                self.assertEqual(users[spec['user']], {'admin': False, 'type': 'Bot'})

    def test_no_interactive_sign_in(self):
        for role, spec in R.ROLES.items():
            with self.subTest(role=role):
                for label, password in (('empty', ''), ('random', secrets.token_urlsafe(18))):
                    basic = base64.b64encode(f'{spec["user"]}:{password}'.encode()).decode()
                    status = G.http_get(self.ctx.port, '/api/v1/repos/search',
                                        headers={'Authorization': 'Basic ' + basic})[0]
                    RESULTS.append({'role': role, 'action': f'basic auth with an {label} password',
                                    'expected': 'denied', 'status': status, 'message': ''})
                    self.assertEqual(status, 401)
                form = urllib.parse.urlencode({'user_name': spec['user'], 'password': secrets.token_urlsafe(18)})
                status, _h, body = G.http_get(self.ctx.port, '/user/login', method='POST', body=form.encode(),
                                              headers={'Content-Type': 'application/x-www-form-urlencoded'})
                refused = status == 200 and b'Username or password is incorrect' in body
                RESULTS.append({'role': role, 'action': 'web sign-in form', 'expected': 'denied', 'status': status,
                                'message': 'Username or password is incorrect' if refused else ''})
                self.assertTrue(refused)


class TestInstanceWideDenials(Live):
    def test_admin_endpoints(self):
        for role, spec in R.ROLES.items():
            with self.subTest(role=role):
                for method, path, body in (
                        ('GET', '/admin/users', None), ('GET', '/admin/emails', None), ('GET', '/admin/orgs', None),
                        ('GET', '/admin/cron', None), ('GET', '/admin/hooks', None),
                        ('POST', '/admin/actions/runners/registration-token', None),
                        ('POST', '/admin/users', {'username': 'aieh-probe-user', 'password': 'Probe-only-0123456789',
                                                  'email': f'aieh-probe-user@{G.EMAIL_DOMAIN}'}),
                        ('PATCH', f'/admin/users/{spec["user"]}', {'login_name': spec['user'], 'source_id': 0,
                                                                  'admin': True}),
                        ('POST', f'/admin/users/{spec["user"]}/orgs', {'username': 'aieh-probe-org'})):
                    self.denied(role, f'{method} {path}', method, path, body)
        users = self.ctx.cli.users()
        self.assertNotIn('aieh-probe-user', users)
        self.assertFalse(any(users[spec['user']]['admin'] for spec in R.ROLES.values()))

    def test_tokens_of_self_and_others(self):
        for role, spec in R.ROLES.items():
            with self.subTest(role=role):
                for user in (spec['user'], G.OWNER, G.SITE_ADMIN):
                    self.denied(role, f'list tokens of {user}', 'GET', f'/users/{user}/tokens')
                    self.denied(role, f'create a token for {user}', 'POST', f'/users/{user}/tokens',
                                {'name': 'aieh-probe', 'scopes': ['all']})
                self.denied(role, f'delete a token of {G.OWNER}', 'DELETE', f'/users/{G.OWNER}/tokens/1')
                basic = base64.b64encode(f'{spec["user"]}:{self.ctx.tokens[role]}'.encode()).decode()
                status, payload = R.Api(self.ctx.port).call('POST', f'/users/{spec["user"]}/tokens',
                                                             {'name': 'aieh-probe', 'scopes': ['all']},
                                                             {'Authorization': 'Basic ' + basic})
                del basic
                RESULTS.append({'role': role, 'action': 'mint an all-scope token with the token as a basic-auth '
                                'password', 'expected': 'denied', 'status': status, 'message': message(payload)})
                if status == 201 and isinstance(payload, dict) and payload.get('sha1'):
                    R.revoke_current(self.ctx.port, payload.pop('sha1'))
                self.assertIn(status, DENIED)

    def test_other_users_and_emails(self):
        for role in R.ROLES:
            with self.subTest(role=role):
                for path in (f'/users/{G.OWNER}', f'/users/{G.SITE_ADMIN}', '/users/search?q=aieh', '/user/emails',
                             '/user', '/admin/emails'):
                    status, payload = self.denied(role, f'GET {path}', 'GET', path)
                    self.assertNotIn(f'@{G.EMAIL_DOMAIN}', json.dumps(payload))

    def test_no_sudo_and_no_impersonation_header(self):
        for role in R.ROLES:
            with self.subTest(role=role):
                for target in (G.OWNER, G.SITE_ADMIN):
                    status, payload = self.denied(role, f'GET /token?sudo={target}', 'GET', f'/token?sudo={target}')
                    self.assertEqual(payload.get('message'), 'Only administrators allowed to sudo.')
                    self.denied(role, f'GET /admin/users with Sudo: {target}', 'GET', '/admin/users',
                                headers={'Sudo': target})
                    status, payload = self.allowed(role, f'GET /token with X-WEBAUTH-USER: {target} (identity '
                                                   'must stay the bot)', 'GET', '/token',
                                                   headers={'X-WEBAUTH-USER': target})
                    self.assertTrue(payload['name'].startswith(f'aieh-{role}-'))
                    self.denied(None, f'anonymous GET /admin/users with X-WEBAUTH-USER: {target}', 'GET',
                                '/admin/users', headers={'X-WEBAUTH-USER': target})

    def test_no_new_repositories_or_organizations(self):
        for role, spec in R.ROLES.items():
            with self.subTest(role=role):
                self.denied(role, 'create a repository of its own', 'POST', '/user/repos',
                            {'name': f'aieh-probe-{role}', 'private': True})
                self.denied(role, 'create an organization', 'POST', '/orgs', {'username': f'aieh-probe-{role}'})
                self.denied(role, 'create a repository in the fixture organization', 'POST',
                            f'/orgs/{R.FIXTURE_ORG}/repos', {'name': f'aieh-probe-{role}'})
                self.assertEqual(self.api(role).call('GET', f'/repos/{spec["user"]}/aieh-probe-{role}')[0], 404)

    def test_user_secrets(self):
        for role in R.ROLES:
            with self.subTest(role=role):
                self.denied(role, 'list its own Actions secrets', 'GET', '/user/actions/secrets')
                self.denied(role, 'write an Actions secret', 'PUT', '/user/actions/secrets/AIEH_PROBE',
                            {'data': 'probe'})


# ---------------------------------------------------------------- the fixture repository


def git(ctx, role: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    """git as the role: the token reaches git only as an http.extraHeader in its own environment."""
    user = R.ROLES[role]['user']
    basic = base64.b64encode(f'{user}:{ctx.tokens[role]}'.encode()).decode()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never',
               GIT_AUTHOR_NAME=user, GIT_AUTHOR_EMAIL=f'{user}@{G.EMAIL_DOMAIN}', GIT_COMMITTER_NAME=user,
               GIT_COMMITTER_EMAIL=f'{user}@{G.EMAIL_DOMAIN}', NO_PROXY='127.0.0.1', GIT_CONFIG_COUNT='3',
               GIT_CONFIG_KEY_0='http.extraHeader', GIT_CONFIG_VALUE_0='Authorization: Basic ' + basic,
               GIT_CONFIG_KEY_1='credential.helper', GIT_CONFIG_VALUE_1='',
               GIT_CONFIG_KEY_2='core.autocrlf', GIT_CONFIG_VALUE_2='false')
    return subprocess.run(['git', *args], cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=120)


class Fixture(Live):
    """Needs the fixture: each role gets a clone; builder and planner push their proposal branch and
    open (or reuse) a PR; tearDownClass closes the PRs."""
    url = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        status = R.Api(cls.ctx.port, cls.ctx.tokens['verifier']).call('GET', REPO)[0]
        if status != 200:
            raise unittest.SkipTest(f'the fixture repository answers {status} to the verifier: it is created by '
                                    'gitea_roles.py fixture, which needs the site administrator\'s first sign-in')
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-authz-'))
        cls.url = f'http://{G.LOOPBACK}:{cls.ctx.port}/{R.FIXTURE_ORG}/{R.FIXTURE_REPO}.git'
        cls.clones, cls.pulls, cls.pushes = {}, {}, {}
        for role in R.ROLES:
            clone = cls.tmp / role
            result = git(cls.ctx, role, 'clone', '--quiet', cls.url, str(clone), cwd=cls.tmp)
            cls.clones[role] = clone if result.returncode == 0 else None
            RESULTS.append({'role': role, 'action': 'git clone', 'expected': 'allowed', 'status': result.returncode,
                            'message': R.redact(result.stderr.decode('utf-8', 'replace'))[-160:]})
        run_id = secrets.token_hex(4)
        for role in ('builder', 'planner'):
            branch = f'work/authz-{role}'
            cls.pushes[role] = cls.commit_and_push(role, branch, f'{role} {run_id}')
            api = R.Api(cls.ctx.port, cls.ctx.tokens[role])
            status, body = api.call('POST', f'{REPO}/pulls', {'head': branch, 'base': R.DEFAULT_BRANCH,
                                                               'title': f'authorization probe ({role})'})
            if status in (409, 422):
                _s, open_pulls = api.call('GET', f'{REPO}/pulls?state=open&limit=50')
                body = next((p for p in open_pulls or [] if p['head']['ref'] == branch), None)
            RESULTS.append({'role': role, 'action': 'open a proposal PR', 'expected': 'allowed', 'status': status,
                            'message': message(body)})
            cls.pulls[role] = (status, body.get('number') if isinstance(body, dict) else None)

    @classmethod
    def commit_and_push(cls, role, branch, text, refspec=None, force=False) -> int:
        clone = cls.clones[role]
        if clone is None:
            return -1
        remote = git(cls.ctx, role, 'ls-remote', '--heads', 'origin', branch, cwd=clone).stdout.strip()
        start = f'origin/{branch}' if remote else f'origin/{R.DEFAULT_BRANCH}'
        git(cls.ctx, role, 'fetch', '--quiet', 'origin', cwd=clone)
        git(cls.ctx, role, 'checkout', '--quiet', '-B', branch, start, cwd=clone)
        (clone / f'{role}.txt').write_text(text + '\n', encoding='utf-8')
        git(cls.ctx, role, 'add', f'{role}.txt', cwd=clone)
        git(cls.ctx, role, 'commit', '--quiet', '-m', text, cwd=clone)
        args = ['push', '--quiet', *(['--force'] if force else []), 'origin', refspec or f'HEAD:refs/heads/{branch}']
        result = git(cls.ctx, role, *args, cwd=clone)
        RESULTS.append({'role': role, 'action': f'git {" ".join(args[2:])}', 'expected': 'see test',
                        'status': result.returncode,
                        'message': R.redact(result.stderr.decode('utf-8', 'replace'))[-200:]})
        return result.returncode

    @classmethod
    def tearDownClass(cls):
        for role, (_status, number) in getattr(cls, 'pulls', {}).items():
            if number:
                R.Api(cls.ctx.port, cls.ctx.tokens[role]).call('PATCH', f'{REPO}/pulls/{number}', {'state': 'closed'})
        if getattr(cls, 'tmp', None):
            shutil.rmtree(cls.tmp, onexc=lambda f, p, e: (os.chmod(p, 0o700), f(p)))

    def head(self, branch=R.DEFAULT_BRANCH) -> str:
        return self.api('verifier').call('GET', f'{REPO}/branches/{urllib.parse.quote(branch, safe="")}')[1]['commit']['id']


class TestFixtureAllowed(Fixture):
    def test_every_role_reads_the_repository(self):
        for role in R.ROLES:
            with self.subTest(role=role):
                self.allowed(role, 'read the repository', 'GET', REPO)
                self.assertIsNotNone(self.clones[role], f'{role} could not clone')

    def test_builder_and_planner_push_a_proposal_branch_and_open_a_pr(self):
        for role in ('builder', 'planner'):
            with self.subTest(role=role):
                self.assertEqual(self.pushes[role], 0)
                status, number = self.pulls[role]
                self.assertIn(status, (201, 409, 422))
                self.assertIsNotNone(number)

    def test_reviewer_submits_a_review(self):
        number = self.pulls['builder'][1]
        self.allowed('reviewer', 'submit an approving review', 'POST', f'{REPO}/pulls/{number}/reviews',
                     {'event': 'APPROVED', 'body': 'authorization probe review'})

    def test_verifier_reads_the_protected_ref_the_pr_and_a_blob(self):
        _s, branch = self.allowed('verifier', 'read the protected default branch', 'GET',
                                  f'{REPO}/branches/{R.DEFAULT_BRANCH}')
        self.assertTrue(branch['protected'])
        _s, pull = self.allowed('verifier', 'read a PR (merged_by)', 'GET', f'{REPO}/pulls/{self.pulls["builder"][1]}')
        self.assertIn('merged_by', pull)
        self.allowed('verifier', 'read a blob', 'GET', f'{REPO}/raw/README.md?ref={R.DEFAULT_BRANCH}')


class TestFixtureDenied(Fixture):
    def test_nobody_merges_into_the_protected_branch(self):
        before = self.head()
        for number in {n for _s, n in self.pulls.values() if n}:
            for role in R.ROLES:
                with self.subTest(role=role, pull=number):
                    for body in ({'Do': 'merge'}, {'Do': 'merge', 'force_merge': True}, {'Do': 'squash'}):
                        self.denied(role, f'merge PR ({json.dumps(body)})', 'POST', f'{REPO}/pulls/{number}/merge',
                                    body)
            self.assertFalse(self.api('verifier').call('GET', f'{REPO}/pulls/{number}')[1]['merged'])
        self.assertEqual(self.head(), before)

    def test_no_push_force_push_or_deletion_of_protected_refs(self):
        before = self.head()
        for role in R.ROLES:
            with self.subTest(role=role):
                clone = self.clones[role]
                self.assertIsNotNone(clone)
                self.assertNotEqual(self.commit_and_push(role, R.DEFAULT_BRANCH, f'direct {role}'), 0)
                orphan = git(self.ctx, role, 'commit-tree', '4b825dc642cb6eb9a060e54bf8d69288fbee4904', '-m',
                             'orphan', cwd=clone).stdout.decode().strip()
                for args, label in ((['push', 'origin', f'+{orphan}:refs/heads/{R.DEFAULT_BRANCH}'], 'force-push'),
                                    (['push', 'origin', f':refs/heads/{R.DEFAULT_BRANCH}'], 'delete by push'),
                                    (['push', 'origin', f'HEAD:refs/heads/feature/authz-{role}'],
                                     'push a non-proposal branch')):
                    result = git(self.ctx, role, *args, cwd=clone)
                    RESULTS.append({'role': role, 'action': f'git {label}', 'expected': 'denied',
                                    'status': result.returncode,
                                    'message': R.redact(result.stderr.decode('utf-8', 'replace'))[-200:]})
                    self.assertNotEqual(result.returncode, 0, label)
                self.denied(role, 'delete the default branch (API)', 'DELETE', f'{REPO}/branches/{R.DEFAULT_BRANCH}')
        for role in ('reviewer', 'verifier'):
            with self.subTest(role=role, branch='work/*'):
                self.assertNotEqual(self.commit_and_push(role, f'work/authz-{role}', f'proposal {role}'), 0)
        self.assertEqual(self.head(), before)

    def test_no_change_to_protection_or_repository_settings(self):
        for role in R.ROLES:
            with self.subTest(role=role):
                user = R.ROLES[role]['user']
                for method, path, body in (
                        ('POST', f'{REPO}/branch_protections', {'rule_name': 'aieh-probe'}),
                        ('PATCH', f'{REPO}/branch_protections/{R.DEFAULT_BRANCH}', {'enable_push': True}),
                        ('DELETE', f'{REPO}/branch_protections/{R.DEFAULT_BRANCH}', None),
                        ('PATCH', REPO, {'description': 'aieh-probe', 'private': False}),
                        ('PUT', f'{REPO}/collaborators/{user}', {'permission': 'admin'}),
                        ('POST', f'{REPO}/hooks', {'type': 'gitea', 'config': {'url': 'http://127.0.0.1:9/',
                                                                              'content_type': 'json'}}),
                        ('POST', f'{REPO}/keys/tokens', {'name': 'aieh-probe', 'scopes': ['read:repository']}),
                        ('POST', f'{REPO}/transfer', {'new_owner': user}),
                        ('DELETE', REPO, None)):
                    self.denied(role, f'{method} {path}', method, path, body)
        _s, info = self.api('verifier').call('GET', REPO)
        self.assertTrue(info['private'])

    def test_no_repository_or_organization_secrets(self):
        for role in R.ROLES:
            with self.subTest(role=role):
                for method, path, body in (('GET', f'{REPO}/actions/secrets', None),
                                           ('PUT', f'{REPO}/actions/secrets/AIEH_PROBE', {'data': 'probe'}),
                                           ('GET', f'/orgs/{R.FIXTURE_ORG}/actions/secrets', None),
                                           ('GET', f'{REPO}/actions/variables', None)):
                    self.denied(role, f'{method} {path}', method, path, body)

    def test_verifier_and_reviewer_hold_no_proposal_rights(self):
        self.denied('verifier', 'open a PR', 'POST', f'{REPO}/pulls',
                    {'head': 'work/authz-builder', 'base': R.DEFAULT_BRANCH, 'title': 'verifier probe'})
        self.denied('verifier', 'submit a review', 'POST', f'{REPO}/pulls/{self.pulls["builder"][1]}/reviews',
                    {'event': 'COMMENT', 'body': 'verifier probe'})


class TestExecutor(unittest.TestCase):
    @unittest.skip('not applicable: no executor principal or executor API exists (G-04.x); executor-action denial '
                   'is carried to G-04.2.1')
    def test_bots_cannot_perform_executor_actions(self):
        pass
