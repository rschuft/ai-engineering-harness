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

    # ------------------------------------------------------------------ helpers for the tests

    def provisioned(self, clone, commits):
        """The repository as the act leaves it."""
        self.orgs[R.DEMO_ORG] = dict(R.DEMO_ORG_SETTINGS)
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
            return self.reply(201, {'username': data['username']})
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
            return self.reply(200, [{'login': u} for u in self.collaborators],
                              {'x-total-count': str(len(self.collaborators))})
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
            return self.reply(200, copy.deepcopy(self.keys))
        if rest == '/branches/main' and method == 'GET':
            if self.main is None:
                return self.reply(404, {'message': 'branch not found'})
            names = [r['rule_name'] for r in self.rules]
            return self.reply(200, {'name': 'main', 'commit': {'id': self.main}, 'protected': bool(self.rules),
                                    'effective_branch_protection_name': 'main' if 'main' in names else ''})
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
        return R.demo_check(http=self.gitea, ctx=(None, None, PORT, self.provider, self.cli), main=main)

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


@unittest.skipUnless(os.name == 'nt', 'the command line runs on Windows only')
class CommandLine(unittest.TestCase):
    category = 'unit'

    def test_a_report_with_commit_ids_is_shown_and_still_scanned_for_the_held_secret(self):
        report = {'status': 'verified', 'main': 'a' * 40, 'problems': []}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(R, 'demo_check', return_value=report), mock.patch.object(sys, 'stdout', out), \
                mock.patch.object(sys, 'stderr', err):
            self.assertEqual(R.main(['demo-verify']), 0)
        self.assertEqual(json.loads(out.getvalue()), report)
        self.assertIn('I7 no-exposure scan: clean', err.getvalue())

        def leaking(main=None):
            G.ACT_GUARD.hold('the-held-secret-value')
            return {'status': 'verified', 'echo': 'the-held-secret-value'}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(R, 'demo_check', side_effect=leaking), mock.patch.object(sys, 'stdout', out), \
                mock.patch.object(sys, 'stderr', err):
            self.assertEqual(R.main(['demo-verify']), 1)
        self.assertEqual(out.getvalue(), '')
        self.assertIn('EXPOSURE_FOUND', err.getvalue())


if __name__ == '__main__':
    unittest.main()
