"""The D1 demo repository's provisioning act and its read-only verifier (gitea_roles.py demo-repository, demo-verify,
demo-clone; plan leaf E-05.1, OA-22 (h)), offline: built and tested on fakes, never run live.

``DemoGitea`` is a fake Gitea 28.3.0 holding the site administrator's routes for the organization ``aieh-demo`` and
its repository (created, settings, collaborators, rules, teams, deploy keys, main, commits, pull requests, the
administrator's tokens) and a stand-in for the smart-HTTP push. The clone is a real local repository whose main is
C0 to C3 (test_demo_repository.build_sequence: the seed, the placement, record-from-log from this checkout's committed
log, read only, and a synthetic task file). Covered: every write in order as the administrator by basic
authentication with no token minted, the push of exactly C0 to C3 before any collaborator or rule, the window's
start, end and pushed commit, the read-back judged by protection_check.judge; the idempotent second run; each refusal
before any write (the act's name, the clone not the sequence, missing bots or aieh-owner, an administrator token, an
existing organization or repository in another state, main holding other commits) with nothing sent; each stop
after a write with nothing sent after it; the verifier's drift and unverified answers; the clone as the
administrator; the command line's no-exposure scan of a report holding commit ids. Every value is synthetic.
"""
from __future__ import annotations

import base64
import contextlib
import copy
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


TD = _load('aieh_test_demo_repository', HERE / 'test_demo_repository.py')  # build_sequence (its tests not collected)
G = _load('aieh_gitea_host', HERE.parent / 'gitea_host.py')
R = _load('aieh_gitea_roles', HERE.parent / 'gitea_roles.py')
PF = _load('aieh_gitea_protection_fake', HERE / 'protection_fake.py')
TR = _load('aieh_test_gitea_roles', HERE / 'test_gitea_roles.py')  # its FakeCli and MemoryProvider (not collected)
DR, fx = TD.DR, TD.fx
DEMO, PORT = R.DEMO_REPOSITORY, TR.PORT
REPO_PATH = f'/repos/{DEMO}'


class DemoGitea:
    """The site administrator's view of the demo organization and repository. ``fail[(method, path)] = status``
    answers that request so; ``ignore`` names settings a PATCH does not apply; ``admin_tokens`` the administrator's
    tokens; ``push_fails`` makes the push raise."""

    def __init__(self):
        self.orgs, self.repo, self.main, self.commits = {}, None, None, {}
        self.rules, self.collaborators, self.keys, self.pulls = [], {}, [], []
        self.teams = [PF.team_view('Owners', 'owner')]
        self.requests, self.pushes, self.admin_tokens = [], [], []
        self.fail, self.ignore, self.push_fails = {}, set(), None
        self.org_members, self.org_teams = [], [PF.team_view('Owners', 'owner', 1)]
        self.no_total = set()  # list routes answered without X-Total-Count

    # ------------------------------------------------------------------ helpers for the tests

    def provisioned(self, clone, commits):
        """The repository as the act leaves it."""
        self.orgs[R.DEMO_ORG] = dict(R.DEMO_ORG_SETTINGS)
        self.org_members = [G.SITE_ADMIN]
        self.create_repository()
        self.push(clone, R.demo_url(PORT), 'refs/heads/main:refs/heads/main', None, check=False)
        declared = R.demo_declaration()
        self.repo.update(declared['settings'])
        self.collaborators.update(declared['collaborators'])
        self.rules.extend(PF.rule_view(rule, n + 2) for n, rule in enumerate(declared['rules']))
        self.requests, self.pushes = [], []

    def create_repository(self):
        self.repo = PF.repository_view({'private': True, 'empty': True, 'allow_rebase': True}, DEMO)

    def writes(self):
        return [(r['method'], r['path']) for r in self.requests if r['method'] != 'GET']

    # ------------------------------------------------------------------ the push (the repository module's stand-in)

    def push(self, clone, url, refspec, credential, check=True):
        if check:
            assert isinstance(credential, DR._ra().Credential), credential
            assert (credential.username, credential.secret, credential.scheme) == \
                (G.SITE_ADMIN, TR.ADMIN_PASSWORD, 'basic')
            assert url == f'http://127.0.0.1:{PORT}/{DEMO}.git', url
        self.requests.append({'method': 'PUSH', 'path': refspec, 'auth': 'basic'})
        self.pushes.append({'refspec': refspec, 'rules': len(self.rules), 'collaborators': dict(self.collaborators)})
        if self.push_fails:
            raise DR._ra().RepositoryError(self.push_fails, 'a fault of the fake')
        assert refspec == 'refs/heads/main:refs/heads/main' and self.main is None and self.repo is not None
        sequence = DR.sequence_report(clone)
        names = ('C0', 'C1', 'C2', 'C3')
        for n, name in enumerate(names):
            self.commits[sequence['commits'][name]] = [sequence['commits'][names[n - 1]]] if n else []
        self.main = sequence['commits']['C3']
        self.repo['empty'] = False
        return SimpleNamespace(name='refs/heads/main', old=None, new=self.main)

    # ------------------------------------------------------------------ HTTP

    def listing(self, name, items):
        return self.reply(200, items, {} if name in self.no_total else {'x-total-count': str(len(items))})

    @staticmethod
    def reply(status, payload, extra=None):
        return status, {'content-type': 'application/json', **(extra or {})}, \
            b'' if payload is None else json.dumps(payload).encode()

    def __call__(self, port, path, *, method='GET', body=None, headers=None, timeout=5.0):
        auth = (headers or {}).get('Authorization', '')
        route = path.removeprefix('/api/v1')
        self.requests.append({'method': method, 'path': route, 'auth': 'basic' if auth.startswith('Basic ') else None})
        user, _, password = base64.b64decode(auth[6:]).decode().partition(':') if auth.startswith('Basic ') \
            else ('', '', '')
        if (user, password) != (G.SITE_ADMIN, TR.ADMIN_PASSWORD):
            return self.reply(401, {'message': 'unauthorized'})
        if (method, route) in self.fail:
            return self.reply(self.fail[(method, route)], {'message': 'a fault of the fake'})
        return self.admin(method, route, json.loads(body) if body else None)

    def admin(self, method, route, data):
        base, _, query = route.partition('?')
        if (method, base) == ('GET', '/user'):
            return self.reply(200, {'login': G.SITE_ADMIN, 'is_admin': True})
        if (method, base) == ('GET', f'/users/{G.SITE_ADMIN}/tokens'):
            return self.reply(200, [{'id': n + 1, 'name': name} for n, name in enumerate(self.admin_tokens)])
        if method == 'GET' and base.startswith('/orgs/') and base.count('/') == 2:
            org = self.orgs.get(base.split('/')[2])
            return self.reply(200, {'id': 7, 'username': base.split('/')[2], **org}) if org else \
                self.reply(404, {'message': 'not found'})
        if (method, base) == ('POST', '/orgs'):
            if data['username'] in self.orgs:
                return self.reply(422, {'message': 'user already exists'})
            self.orgs[data['username']] = {k: data[k] for k in R.DEMO_ORG_SETTINGS}
            self.org_members = [G.SITE_ADMIN]  # Gitea makes the creator an owner
            return self.reply(201, {'username': data['username']})
        if method == 'GET' and base == f'/orgs/{R.DEMO_ORG}/teams' and R.DEMO_ORG in self.orgs:
            return self.listing('org-teams', copy.deepcopy(self.org_teams))
        if method == 'GET' and base.startswith('/teams/') and base.endswith('/members') and R.DEMO_ORG in self.orgs:
            members = [{'id': 1, 'login': G.SITE_ADMIN}] if base == '/teams/1/members' else []
            return self.listing('team-members', members)
        if method == 'GET' and base == f'/orgs/{R.DEMO_ORG}/members' and R.DEMO_ORG in self.orgs:
            return self.listing('org-members', [{'id': n + 1, 'login': u} for n, u in enumerate(self.org_members)])
        if (method, base) == ('POST', f'/orgs/{R.DEMO_ORG}/repos'):
            if R.DEMO_ORG not in self.orgs or self.repo is not None or data['name'] != R.DEMO_REPO:
                return self.reply(409, {'message': 'refused by the fake'})
            assert (data['auto_init'], data['private'], data['default_branch']) == (False, True, 'main'), data
            self.create_repository()
            return self.reply(201, {'full_name': DEMO})
        if not (base == REPO_PATH or base.startswith(REPO_PATH + '/')):
            return self.reply(403, {'message': f'the fake does not address {route}'})
        if self.repo is None:
            return self.reply(404, {'message': 'not found'})
        rest = base[len(REPO_PATH):]
        if rest == '' and method == 'GET':
            return self.reply(200, {**self.repo, 'permissions': {'admin': True, 'push': True, 'pull': True}})
        if rest == '' and method == 'PATCH':
            self.repo.update({k: v for k, v in data.items() if k not in self.ignore})
            return self.reply(200, self.repo)
        if rest.startswith('/collaborators/') and method == 'PUT':
            self.collaborators[rest.split('/')[2]] = data['permission']
            return self.reply(204, None)
        if rest == '/collaborators' and method == 'GET':
            return self.listing('collaborators', [{'id': n + 20, 'login': u} for n, u in enumerate(self.collaborators)])
        if rest.startswith('/collaborators/') and rest.endswith('/permission') and method == 'GET':
            user = rest.split('/')[2]
            return self.reply(200, {'permission': self.collaborators.get(user, 'none'), 'role_name': '',
                                    'user': {'login': user}})
        if rest == '/branch_protections' and method == 'POST':
            self.rules.append(PF.rule_view(data, len(self.rules) + 2))
            return self.reply(201, data)
        if rest == '/branch_protections' and method == 'GET':
            return self.reply(200, copy.deepcopy(self.rules))
        if rest == '/teams' and method == 'GET':
            return self.reply(200, copy.deepcopy(self.teams))
        if rest == '/keys' and method == 'GET':
            return self.listing('keys', copy.deepcopy(self.keys))
        if rest == '/branches/main' and method == 'GET':
            if self.main is None:
                return self.reply(404, {'message': 'branch not found'})
            rule = next((r for r in self.rules if r['rule_name'] == 'main'), None)
            return self.reply(200, {'name': 'main', 'commit': {'id': self.main}, 'protected': rule is not None,
                                    'required_approvals': rule['required_approvals'] if rule else 0,
                                    'enable_status_check': False, 'status_check_contexts': [],
                                    'user_can_push': rule is None, 'user_can_merge': True,
                                    'effective_branch_protection_name': 'main' if rule else ''})
        if rest.startswith('/git/commits/') and method == 'GET':
            sha = rest.split('/')[3]
            if sha not in self.commits:
                return self.reply(404, {'message': 'no such commit'})
            return self.reply(200, {'sha': sha, 'parents': [{'sha': p} for p in self.commits[sha]]})
        if rest == '/pulls' and method == 'GET':
            return self.reply(200, list(self.pulls))
        return self.reply(404, {'message': f'no route {method} {route}'})


class Act(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TD.fx.require_repository_access()
        cls.root = Path(tempfile.mkdtemp(prefix='aieh-demo-act-'))
        with mock.patch.dict(os.environ, {'GIT_CEILING_DIRECTORIES': str(cls.root)}):
            cls.clone, cls.commits, _ = TD.build_sequence(cls.root)

    @classmethod
    def tearDownClass(cls):
        fx.rmtree(cls.root)

    def setUp(self):
        ceiling = fx.ceiling(self.root)
        ceiling.start()
        self.addCleanup(ceiling.stop)
        self.gitea, self.cli = DemoGitea(), TR.FakeCli()
        for spec in R.ROLES.values():
            self.cli.users_[spec['user']] = {'admin': False, 'type': 'Bot'}
        self.provider = TR.MemoryProvider({G.FINAL_TARGETS[G.SITE_ADMIN]: (G.SITE_ADMIN, TR.ADMIN_PASSWORD)})

    def run_act(self, owner_act=R.DEMO_ACT, clone=None):
        return R.demo_repository(owner_act=owner_act, clone=clone or self.clone, http=self.gitea,
                                 ctx=(None, None, PORT, self.provider, self.cli), push=self.gitea.push)

    def stopped(self, code, refusal=False, **kw):
        with self.assertRaises(G.GiteaError) as caught:
            self.run_act(**kw)
        error = caught.exception
        self.assertEqual((error.code, error.refusal), (code, refusal), str(error))
        self.assertNotIn(TR.ADMIN_PASSWORD, str(error) + json.dumps(error.report))
        report = error.report
        self.assertEqual((report['stopped']['code'], report['stopped']['after_writes']), (code, not refusal))
        self.assertEqual([(a['method'], a['path']) for a in report['actions']],
                         [(m, p if m != 'PUSH' else f'{REPO_PATH}.git {p}') for m, p in self.gitea.writes()])
        return error


class TheAct(Act):
    def test_every_step_in_order_as_the_administrator_with_no_token(self):
        report = self.run_act()
        declared = R.demo_declaration()
        self.assertEqual(self.gitea.writes(), [
            ('POST', '/orgs'), ('POST', f'/orgs/{R.DEMO_ORG}/repos'), ('PUSH', 'refs/heads/main:refs/heads/main'),
            ('PATCH', REPO_PATH), *(('PUT', f'{REPO_PATH}/collaborators/{u}') for u in declared['collaborators']),
            *(('POST', f'{REPO_PATH}/branch_protections') for _rule in declared['rules'])])
        # the push comes before any collaborator or rule, and pushes exactly C0 to C3
        self.assertEqual(self.gitea.pushes, [{'refspec': 'refs/heads/main:refs/heads/main', 'rules': 0,
                                              'collaborators': {}}])
        self.assertEqual(self.gitea.main, self.commits['C3'])
        self.assertEqual(report['window']['pushed'], self.commits['C3'])
        self.assertEqual(report['push'], {'ref': 'refs/heads/main', 'old': None, 'new': self.commits['C3']})
        self.assertLessEqual(report['window']['opened'], report['window']['closed'])
        self.assertEqual(report['window']['pushed_by'], G.SITE_ADMIN)
        self.assertEqual(report['sequence'], self.commits)
        # the declaration: the fixture's rules and settings, Actions disabled, no auditor, no verifier
        self.assertEqual(declared['rules'], R.protection_rules())
        self.assertEqual(declared['settings'], {**R.repository_settings(), 'has_actions': False})
        self.assertEqual(declared['collaborators'], {'aieh-bot-planner': 'write', 'aieh-bot-builder': 'write',
                                                     'aieh-bot-reviewer': 'read', G.OWNER: 'write'})
        self.assertNotIn(R.ROLES['protection-audit']['user'], self.gitea.collaborators)
        self.assertNotIn(R.ROLES['verifier']['user'], self.gitea.collaborators)
        self.assertNotIn(DEMO, R.DECLARATIONS)
        self.assertNotIn(DEMO, R.AUDITED_REPOSITORIES)
        # the read-back: verified, judged by protection_check.judge, main at C3 over four commits
        found = report['verification']
        self.assertEqual((found['status'], found['code'], found['problems'], found['main']),
                         ('verified', 'VERIFIED', [], self.commits['C3']))
        self.assertEqual([h['parents'] for h in found['history']], [1, 1, 1, 0])
        self.assertRegex(found['digest'], r'^sha256:[0-9a-f]{64}$')
        self.assertEqual((report['state'], report['admin_tokens_before'], report['admin_tokens_after']),
                         ('created', [], []))
        self.assertEqual({r['auth'] for r in self.gitea.requests}, {'basic'})
        self.assertEqual(self.cli.minted, [])
        self.assertFalse(any('/pulls' in p and m != 'GET' or '/merge' in p for m, p in self.gitea.writes()))
        first_write = next(n for n, r in enumerate(self.gitea.requests) if r['method'] != 'GET')
        self.assertTrue(any(r['path'] == f'/users/{G.SITE_ADMIN}/tokens' for r in self.gitea.requests[:first_write]))

    def test_a_second_run_reports_and_writes_nothing(self):
        self.run_act()
        sent = len(self.gitea.requests)
        second = self.run_act()
        self.assertEqual((second['state'], second['actions']), ('already present; nothing written', []))
        self.assertEqual({r['method'] for r in self.gitea.requests[sent:]}, {'GET'})
        self.assertEqual(second['verification']['status'], 'verified')

    def test_refused_before_any_write(self):
        for owner_act in (None, 'OA-22 (h)', 'OA-30', 'oa-22h'):
            with self.subTest(owner_act=owner_act), \
                    mock.patch.object(R, 'context', side_effect=AssertionError('nothing is read')):
                with self.assertRaises(G.GiteaError) as caught:
                    R.demo_repository(owner_act=owner_act, clone=self.clone)
                self.assertEqual((caught.exception.code, caught.exception.refusal), ('OWNER_ACT_REQUIRED', True))
        with self.assertRaises(G.GiteaError) as caught:
            R.demo_repository(owner_act=R.DEMO_ACT)
        self.assertEqual(caught.exception.code, 'CLONE_NOT_THE_SEQUENCE')
        self.stopped('CLONE_NOT_THE_SEQUENCE', refusal=True, clone=self.root / 'aieh-d1-demo.git' / 'absent')
        del self.cli.users_['aieh-bot-reviewer']
        self.stopped('BOTS_MISSING', refusal=True)
        self.cli.users_['aieh-bot-reviewer'] = {'admin': False, 'type': 'Bot'}
        del self.cli.users_[G.OWNER]
        self.stopped('OWNER_MISSING', refusal=True)
        self.cli.users_[G.OWNER] = {'admin': False, 'type': 'User'}
        self.gitea.admin_tokens = ['left-over']
        self.stopped('ADMIN_HOLDS_TOKEN', refusal=True)
        self.assertEqual(self.gitea.writes(), [])
        self.assertEqual(self.gitea.pushes, [])

    def test_a_clone_that_is_not_exactly_c0_to_c3_is_refused(self):
        with tempfile.TemporaryDirectory(prefix='aieh-demo-more-') as tmp, \
                mock.patch.dict(os.environ, {'GIT_CEILING_DIRECTORIES': tmp}):
            clone, _, _ = TD.build_sequence(tmp)
            fx.write(clone, {'README.md': b'a fifth commit\n'})
            fx.commit_all(clone, 'a fifth commit')
            error = self.stopped('CLONE_NOT_THE_SEQUENCE', refusal=True, clone=clone)
        self.assertIn('not exactly C0 to C3', error.detail)
        self.assertEqual(self.gitea.requests, [])

    def test_an_existing_organization_or_repository_is_never_adopted(self):
        self.gitea.orgs[R.DEMO_ORG] = dict(R.DEMO_ORG_SETTINGS)
        self.stopped('DEMO_REPOSITORY_EXISTS', refusal=True)
        self.gitea.provisioned(self.clone, self.commits)
        self.gitea.collaborators[R.ROLES['verifier']['user']] = 'read'
        error = self.stopped('DEMO_REPOSITORY_EXISTS', refusal=True)
        self.assertIn('collaborator aieh-bot-verifier', error.detail)
        del self.gitea.collaborators[R.ROLES['verifier']['user']]
        self.gitea.commits['f' * 40] = [self.gitea.main]
        self.gitea.main = 'f' * 40
        error = self.stopped('MAIN_NOT_THE_SEQUENCE', refusal=True)
        self.assertIn('main\'s head', error.detail)
        self.assertEqual(self.gitea.writes(), [])

    def test_stops_after_a_write_send_nothing_further(self):
        self.gitea.fail[('PATCH', REPO_PATH)] = 500
        error = self.stopped('API_UNEXPECTED')
        self.assertEqual(self.gitea.writes()[-1], ('PATCH', REPO_PATH))
        self.assertEqual(error.report['window']['pushed'], self.commits['C3'])
        self.assertNotIn('closed', error.report['window'])
        self.setUp()
        self.gitea.push_fails = 'PUSH_REJECTED'
        error = self.stopped('PUSH_FAILED')
        self.assertEqual(self.gitea.writes()[-1], ('PUSH', 'refs/heads/main:refs/heads/main'))
        self.assertIn('PUSH_REJECTED: may have been written', error.report['actions'][-1]['status'])
        self.setUp()
        self.gitea.ignore = {'has_actions'}
        original = self.gitea.create_repository

        def actions_on():
            original()
            self.gitea.repo['has_actions'] = True
        self.gitea.create_repository = actions_on
        error = self.stopped('READBACK_DIFFERENT')
        self.assertIn('has_actions', error.detail)
        self.assertEqual(self.gitea.writes()[-1], ('POST', f'{REPO_PATH}/branch_protections'))


class Verifier(Act):
    def setUp(self):
        super().setUp()
        self.gitea.provisioned(self.clone, self.commits)

    def check(self, main=None):
        return R.demo_check(http=self.gitea, ctx=(None, None, PORT, self.provider, self.cli),
                            main=self.commits['C3'] if main is None else main)

    def test_verified_and_read_only(self):
        found = self.check(main=self.commits['C3'])
        self.assertEqual((found['status'], found['read_as']), ('verified', G.SITE_ADMIN))
        self.assertEqual({r['method'] for r in self.gitea.requests}, {'GET'})
        self.assertEqual(self.check()['status'], 'verified')

    def test_each_difference_is_drift(self):
        for mutate, needle in (
                (lambda g: g.collaborators.update({'aieh-bot-protection-audit': 'admin'}), 'aieh-bot-protection-audit'),
                (lambda g: g.repo.update(private=False), 'private'),
                (lambda g: g.orgs[R.DEMO_ORG].update(visibility='public'), 'visibility'),
                (lambda g: g.rules[0].update(enable_push=True), 'enable_push'),
                (lambda g: g.rules.pop(), 'missing'),
                (lambda g: g.keys.append({'id': 1, 'title': 'k', 'read_only': True}), 'deploy key')):
            with self.subTest(needle=needle):
                self.gitea = DemoGitea()
                self.gitea.provisioned(self.clone, self.commits)
                mutate(self.gitea)
                found = self.check(main=self.commits['C3'])
                self.assertEqual(found['status'], 'drift', found)
                self.assertTrue(any(needle in p for p in found['problems']), found['problems'])
        self.gitea = DemoGitea()
        self.gitea.provisioned(self.clone, self.commits)
        self.assertEqual(self.check(main='e' * 40)['status'], 'drift')
        with self.assertRaises(G.GiteaError):
            self.check(main='C3')

    def test_a_read_that_fails_is_unverified(self):
        self.gitea.fail[('GET', f'{REPO_PATH}/branch_protections')] = 500
        found = self.check()
        self.assertEqual((found['status'], found['code']), ('unverified', 'READ_FAILED'))
        self.gitea = DemoGitea()
        found = self.check()
        self.assertEqual(found['status'], 'unverified')

    def test_the_clone_as_the_administrator(self):
        seen = {}

        def clone(url, destination, credential):
            seen.update(url=url, destination=destination, user=credential.username, scheme=credential.scheme)
            return {'refs/heads/main': self.commits['C3']}
        result = R.demo_clone(self.root / 'fresh.git', ctx=(None, None, PORT, self.provider, self.cli), clone=clone)
        self.assertEqual(seen, {'url': f'http://127.0.0.1:{PORT}/{DEMO}.git', 'destination': self.root / 'fresh.git',
                                'user': G.SITE_ADMIN, 'scheme': 'basic'})
        self.assertEqual(result['refs'], {'refs/heads/main': self.commits['C3']})


class ReviewFixes(Act):
    """Dispatch 3: the reviewer's probes as tests (SF-1 to SF-4, N3)."""

    def hooked_clone(self):
        tmp = tempfile.mkdtemp(prefix='aieh-demo-hook-')
        self.addCleanup(fx.rmtree, tmp)
        hooked = Path(tmp) / 'aieh-d1-demo'
        fx.git(tmp, 'clone', '--quiet', '-c', 'core.autocrlf=false', str(self.clone), str(hooked))
        (hooked / '.git' / 'hooks' / 'pre-push').write_text('#!/bin/sh\nexit 0\n', encoding='ascii')
        return hooked

    def test_sf1_a_push_side_refusal_comes_before_any_write(self):
        error = self.stopped('CLONE_NOT_PUSHABLE', refusal=True, clone=self.hooked_clone())
        self.assertIn('HOOKS_UNSUPPORTED', error.detail)
        self.assertEqual(self.gitea.requests, [])
        # with the real push as well (no stand-in): still nothing sent
        with self.assertRaises(G.GiteaError) as caught:
            R.demo_repository(owner_act=R.DEMO_ACT, clone=self.hooked_clone(), http=self.gitea,
                              ctx=(None, None, PORT, self.provider, self.cli))
        self.assertEqual((caught.exception.code, caught.exception.refusal), ('CLONE_NOT_PUSHABLE', True))
        self.assertEqual(self.gitea.requests, [])
        self.assertEqual(R.demo_push_preconditions(self.clone, self.commits['C3']),
                         {'hooks': None, 'main': self.commits['C3']})
        with self.assertRaises(G.GiteaError) as caught:
            R.demo_push_preconditions(self.clone, self.commits['C2'])
        self.assertIn('not the sequence', caught.exception.detail)

    def test_sf2_a_stop_with_the_window_open_says_so_and_resume_closes_it(self):
        self.gitea.fail[('POST', f'{REPO_PATH}/branch_protections')] = 500
        error = self.stopped('API_UNEXPECTED')
        window = error.report['window']
        self.assertTrue(error.report['stopped']['window_open'])
        self.assertTrue(window['open'])
        self.assertIn('the write collaborators', window['pushes_main'])
        for user in ('aieh-bot-planner', 'aieh-bot-builder', G.OWNER):
            self.assertIn(user, window['pushes_main'])
        self.assertTrue(error.detail.startswith('THE WINDOW IS OPEN'))
        self.assertIn('--resume', error.detail)
        # without --resume the partial repository is refused; with it only the missing rules are written
        del self.gitea.fail[('POST', f'{REPO_PATH}/branch_protections')]
        self.gitea.requests = []
        self.stopped('DEMO_REPOSITORY_EXISTS', refusal=True)
        self.gitea.requests = []
        report = R.demo_repository(owner_act=R.DEMO_ACT, clone=self.clone, http=self.gitea, resume=True,
                                   ctx=(None, None, PORT, self.provider, self.cli), push=self.gitea.push)
        self.assertEqual(self.gitea.writes(), [('POST', f'{REPO_PATH}/branch_protections')] * 3)
        self.assertEqual((report['state'], report['window']['open'], report['verification']['status']),
                         ('resumed', False, 'verified'))
        # a second resume on the verified repository writes nothing
        self.gitea.requests = []
        again = R.demo_repository(owner_act=R.DEMO_ACT, clone=self.clone, http=self.gitea, resume=True,
                                  ctx=(None, None, PORT, self.provider, self.cli), push=self.gitea.push)
        self.assertEqual((again['state'], self.gitea.writes()), ('already present; nothing written', []))

    def test_sf2_resume_after_a_stop_between_collaborators(self):
        self.gitea.fail[('PUT', f'{REPO_PATH}/collaborators/aieh-bot-reviewer')] = 500
        error = self.stopped('API_UNEXPECTED')
        self.assertTrue(error.report['stopped']['window_open'])
        del self.gitea.fail[('PUT', f'{REPO_PATH}/collaborators/aieh-bot-reviewer')]
        self.gitea.requests = []
        report = R.demo_repository(owner_act=R.DEMO_ACT, clone=self.clone, http=self.gitea, resume=True,
                                   ctx=(None, None, PORT, self.provider, self.cli), push=self.gitea.push)
        self.assertEqual(self.gitea.writes(), [('PUT', f'{REPO_PATH}/collaborators/aieh-bot-reviewer'),
                                               ('PUT', f'{REPO_PATH}/collaborators/{G.OWNER}'),
                                               *[('POST', f'{REPO_PATH}/branch_protections')] * 3])
        self.assertEqual(report['verification']['status'], 'verified')

    def test_sf2_resume_never_changes_what_is_present(self):
        def resume():
            return R.demo_repository(owner_act=R.DEMO_ACT, clone=self.clone, http=self.gitea, resume=True,
                                     ctx=(None, None, PORT, self.provider, self.cli), push=self.gitea.push)
        with self.assertRaises(G.GiteaError) as caught:
            resume()
        self.assertEqual(caught.exception.code, 'RESUME_REFUSED')  # nothing to resume
        self.gitea.fail[('POST', f'{REPO_PATH}/branch_protections')] = 500
        self.stopped('API_UNEXPECTED')
        del self.gitea.fail[('POST', f'{REPO_PATH}/branch_protections')]
        for mutate, needle in ((lambda g: g.collaborators.update({'aieh-bot-verifier': 'read'}), 'aieh-bot-verifier'),
                               (lambda g: g.collaborators.update({'aieh-bot-reviewer': 'write'}), 'aieh-bot-reviewer'),
                               (lambda g: g.org_members.append('someone'), 'members'),
                               (lambda g: g.rules.append(PF.rule_view(dict(R.protection_rules()[2],
                                                                          enable_push=True), 9)), '**')):
            with self.subTest(needle=needle):
                saved = (dict(self.gitea.collaborators), list(self.gitea.org_members), list(self.gitea.rules))
                mutate(self.gitea)
                self.gitea.requests = []
                with self.assertRaises(G.GiteaError) as caught:
                    resume()
                self.assertEqual((caught.exception.code, caught.exception.refusal), ('RESUME_REFUSED', True))
                self.assertIn(needle, caught.exception.detail)
                self.assertEqual(self.gitea.writes(), [])
                self.gitea.collaborators, self.gitea.org_members, self.gitea.rules = \
                    dict(saved[0]), list(saved[1]), list(saved[2])

    def test_a_completed_act_reports_the_window_closed(self):
        report = self.run_act()
        self.assertEqual((report['window']['open'], report['window']['pushes_main']),
                         (False, 'nobody (the rules apply)'))


class VerifierFailsClosed(Act):
    """SF-3, SF-4, N3: demo-verify fails closed as protection_check.observe does, and reads the organization."""

    def setUp(self):
        super().setUp()
        self.gitea.provisioned(self.clone, self.commits)

    def check(self, main=None):
        return R.demo_check(http=self.gitea, ctx=(None, None, PORT, self.provider, self.cli),
                            main=self.commits['C3'] if main is None else main)

    def test_every_view_is_checked(self):
        cases = (
            ('a non-object team', lambda g: g.teams.append('not-a-team-object'), 'unverified'),
            ('a repository view without has_actions', lambda g: g.repo.pop('has_actions'), 'unverified'),
            ('a repository view with an unknown field', lambda g: g.repo.update(surprise=1), 'unverified'),
            ('a wider rule Gitea would order first', lambda g: g.rules.append(
                PF.rule_view(dict(R.protection_rules()[1], rule_name='m*', priority=0), 9)), 'unverified'),
            ('a repeated rule name', lambda g: g.rules.append(copy.deepcopy(g.rules[0])), 'unverified'),
            ('a collaborator list read in part', lambda g: g.no_total.add('collaborators'), 'unverified'),
            ('a deploy key list read in part', lambda g: g.no_total.add('keys'), 'unverified'),
            ('a login outside the grammar', lambda g: g.collaborators.update({'../x': 'read'}), 'unverified'),
            ('an extra team with access', lambda g: g.teams.append(PF.team_view('Writers', 'write', 2)), 'drift'),
            ('an extra organization member', lambda g: g.org_members.append('someone-else'), 'drift'),
            ('an extra organization team', lambda g: g.org_teams.append(PF.team_view('Pushers', 'write', 2)), 'drift'),
        )
        for name, mutate, status in cases:
            with self.subTest(name=name):
                self.gitea = DemoGitea()
                self.gitea.provisioned(self.clone, self.commits)
                mutate(self.gitea)
                found = self.check()
                self.assertEqual(found['status'], status, (name, found))
                self.assertEqual({r['method'] for r in self.gitea.requests}, {'GET'})
        self.gitea = DemoGitea()
        self.gitea.provisioned(self.clone, self.commits)
        self.assertEqual(self.check()['status'], 'verified')
        self.assertTrue(any(r['path'].startswith(f'/orgs/{R.DEMO_ORG}/members') for r in self.gitea.requests))
        self.assertTrue(any(r['path'].startswith('/teams/1/members') for r in self.gitea.requests))

    def test_an_unexpected_error_is_unverified(self):
        with mock.patch.object(R, '_demo_observe', side_effect=KeyError('surprise')):
            found = self.check()
        self.assertEqual((found['status'], found['code']), ('unverified', 'UNEXPECTED_ERROR'))

    def test_main_is_required(self):
        for main in ('', 'C3', 'a' * 39):
            with self.subTest(main=main), self.assertRaises(G.GiteaError) as caught:
                self.check(main=main)
            self.assertEqual(caught.exception.code, 'MAIN_REQUIRED')
        with self.assertRaises(G.GiteaError) as caught:
            R.demo_check(http=self.gitea, ctx=(None, None, PORT, self.provider, self.cli))
        self.assertEqual(caught.exception.code, 'MAIN_REQUIRED')

    def test_the_clone_s_failures_are_stable_codes(self):
        ra = DR._ra()
        for raised, code in ((ra.RepositoryError('REMOTE_REFUSED', 'x'), 'CLONE_REFUSED'),
                             (ra.RepositoryError('REMOTE_FAILED', 'x'), 'CLONE_FAILED'),
                             (ValueError('exists'), 'CLONE_DESTINATION'), (OSError('boom'), 'CLONE_FAILED')):
            with self.subTest(code=code), self.assertRaises(G.GiteaError) as caught:
                R.demo_clone(self.root / 'x.git', ctx=(None, None, PORT, self.provider, self.cli),
                             clone=mock.Mock(side_effect=raised))
            self.assertEqual(caught.exception.code, code)


@unittest.skipUnless(os.name == 'nt', 'the command line runs on Windows only')
class CommandLine(unittest.TestCase):
    category = 'unit'

    def test_a_report_with_commit_ids_is_shown_and_still_scanned_for_the_held_secret(self):
        report = {'status': 'verified', 'main': 'a' * 40, 'problems': []}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(R, 'demo_check', return_value=report), mock.patch.object(sys, 'stdout', out), \
                mock.patch.object(sys, 'stderr', err):
            self.assertEqual(R.main(['demo-verify', '--main', 'a' * 40]), 0)
        self.assertEqual(json.loads(out.getvalue()), report)
        self.assertIn('I7 no-exposure scan: clean', err.getvalue())

        def leaking(main=None):
            G.ACT_GUARD.hold('the-held-secret-value')
            return {'status': 'verified', 'echo': 'the-held-secret-value'}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(R, 'demo_check', side_effect=leaking), mock.patch.object(sys, 'stdout', out), \
                mock.patch.object(sys, 'stderr', err):
            self.assertEqual(R.main(['demo-verify', '--main', 'a' * 40]), 1)
        self.assertEqual(out.getvalue(), '')
        self.assertIn('EXPOSURE_FOUND', err.getvalue())

    def test_an_unexpected_error_exits_2_and_is_still_scanned(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(R, 'demo_check', side_effect=KeyError('has_actions')), \
                mock.patch.object(sys, 'stdout', out), mock.patch.object(sys, 'stderr', err):
            self.assertEqual(R.main(['demo-verify', '--main', 'a' * 40]), 2)
        self.assertEqual(json.loads(out.getvalue())['status'], 'unverified')
        self.assertIn('UNEXPECTED_ERROR', err.getvalue())
        self.assertIn('I7 no-exposure scan: clean', err.getvalue())
        with mock.patch.object(sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit):
            R.main(['demo-verify'])  # --main is required


if __name__ == '__main__':
    unittest.main()
