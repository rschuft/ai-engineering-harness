"""Owner act OA-30's live module (plan leaf E-05.7; decision 0022), offline: built and tested on fakes, never run.

``gitea_roles.authorization_repository`` (command ``gitea_roles.py authorization-repository --owner-act OA-30``)
against ``LedgerGitea``, a fake Gitea 28.3.0 holding the site administrator's routes for the authorization repository
(the organization, the repository, its settings, collaborators, rules, teams, deploy keys, protected branch, commits
and pull requests, and the administrator's tokens) and the protection auditor's reads of both the authorization
repository and the S-01.2.2 fixture (protection_fake.ProtectionGitea, the real protection check reading them).
Covered: every step in order as the administrator by basic authentication with no token minted; the read-back
field for field; the auditor's read-only check and its baseline digest; the fixture's recorded baseline; each stop
condition (a non-2xx answer at each write, a read-back difference, a verdict that is not verified, the administrator
holding a token, the fixture no longer verifying, an existing organization or repository, a recorder receipt in the
store, missing bots or aieh-owner) with nothing sent after it; the idempotent second run; the refusal without the
Owner act's flag; the read-only receipt check on a throwaway store; the command line. Every value is synthetic.
"""
from __future__ import annotations

import base64
import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


G = _load('aieh_gitea_host', HERE.parent / 'gitea_host.py')
R = _load('aieh_gitea_roles', HERE.parent / 'gitea_roles.py')
PC = _load('aieh_gitea_protection_check', HERE.parent / 'protection_check.py')
PF = _load('aieh_gitea_protection_fake', HERE / 'protection_fake.py')
TR = _load('aieh_test_gitea_roles', HERE / 'test_gitea_roles.py')  # its FakeCli and MemoryProvider (not collected)
ED = _load('envelope_decisions', REPO / 'integrations' / 'owner' / 'envelope_decisions.py')

LEDGER, FIXTURE = R.AUTHORIZATION_REPOSITORY, R.FIXTURE_REPOSITORY
INITIAL = 'c' * 40  # the initial commit (protection_fake's branch view names it too)
PORT = TR.PORT


class LedgerGitea:
    """The site administrator's view of the authorization repository and the protection auditor's of it and of the
    fixture. ``fail[(method, path)] = status`` answers a request with that status instead; ``ignore`` names settings a
    PATCH does not apply; ``admin_tokens`` the administrator's tokens; ``extra_collaborators`` collaborators Gitea
    would add at creation."""

    def __init__(self):
        self.orgs = {R.FIXTURE_ORG: {'visibility': 'private', 'repo_admin_change_team_access': False}}
        self.fixture = PF.ProtectionGitea(R)          # the fixture as declared (the administrator never touches it)
        self.ledger = None                            # the authorization repository, once created
        self.pulls, self.admin_tokens, self.requests = [], [], []
        self.fail, self.ignore, self.extra_collaborators = {}, set(), {}

    # ------------------------------------------------------------------ helpers for the tests

    def provisioned(self):
        """The authorization repository as the act leaves it (for the states a test starts from)."""
        self.orgs[R.AUTHORIZATION_ORG] = dict(R.AUTHORIZATION_ORG_SETTINGS)
        self.create_repository(private=True)
        declared = R.authorization_declaration()
        self.ledger.repo.update(declared['settings'])
        self.ledger.collaborators.update(declared['collaborators'])
        self.ledger.rules.extend(PF.rule_view(rule, n + 2) for n, rule in enumerate(declared['rules']))

    def create_repository(self, private):
        ledger = PF.ProtectionGitea(R, LEDGER)
        ledger.repo = PF.repository_view({'private': private}, LEDGER)  # Gitea's defaults for a new repository
        ledger.rules, ledger.collaborators, ledger.keys = [], dict(self.extra_collaborators), []
        ledger.teams = [PF.team_view('Owners', 'owner')]
        self.ledger = ledger

    def writes(self):
        return [(r['method'], r['path']) for r in self.requests if r['method'] != 'GET']

    def by(self, auth):
        return [r for r in self.requests if r['auth'] == auth]

    # ------------------------------------------------------------------ HTTP

    def __call__(self, port, path, *, method='GET', body=None, headers=None, timeout=5.0):
        headers = headers or {}
        auth = headers.get('Authorization', '')
        route = path.removeprefix('/api/v1')
        if auth.startswith('token '):  # the protection auditor: its own fake per repository
            self.requests.append({'method': method, 'path': route, 'auth': 'token'})
            target = self.ledger if route.startswith(f'/repos/{LEDGER}') else self.fixture
            if target is None:
                return self.reply(404, {'message': 'not found'})
            return target(port, path, method=method, body=body, headers=headers, timeout=timeout)
        self.requests.append({'method': method, 'path': route, 'auth': 'basic' if auth.startswith('Basic ') else None})
        user, _, password = base64.b64decode(auth[6:]).decode().partition(':') if auth.startswith('Basic ')             else ('', '', '')
        if (user, password) != (G.SITE_ADMIN, TR.ADMIN_PASSWORD):
            return self.reply(401, {'message': 'unauthorized'})
        if (method, route) in self.fail:
            return self.reply(self.fail[(method, route)], {'message': 'a fault of the fake'})
        return self.admin(method, route, json.loads(body) if body else None)

    @staticmethod
    def reply(status, payload, extra=None):
        return status, {'content-type': 'application/json', **(extra or {})}, \
            b'' if payload is None else json.dumps(payload).encode()

    def admin(self, method, route, data):
        base, _, query = route.partition('?')
        repo = f'/repos/{LEDGER}'
        if (method, base) == ('GET', '/user'):
            return self.reply(200, {'login': G.SITE_ADMIN, 'is_admin': True})
        if (method, base) == ('GET', f'/users/{G.SITE_ADMIN}/tokens'):
            return self.reply(200, [{'id': n + 1, 'name': name} for n, name in enumerate(self.admin_tokens)])
        if base.startswith('/orgs/') and base.count('/') == 2 and method == 'GET':
            org = self.orgs.get(base.split('/')[2])
            return self.reply(200, {'id': 5, 'username': base.split('/')[2], **org}) if org else \
                self.reply(404, {'message': 'not found'})
        if (method, base) == ('POST', '/orgs'):
            if data['username'] in self.orgs:
                return self.reply(422, {'message': 'user already exists'})
            self.orgs[data['username']] = {k: data[k] for k in R.AUTHORIZATION_ORG_SETTINGS}
            return self.reply(201, {'username': data['username']})
        if (method, base) == ('POST', f'/orgs/{R.AUTHORIZATION_ORG}/repos'):
            if R.AUTHORIZATION_ORG not in self.orgs or self.ledger is not None or data['name'] != R.AUTHORIZATION_REPO:
                return self.reply(409, {'message': 'refused by the fake'})
            assert (data['auto_init'], data['default_branch']) == (True, 'main'), data
            self.create_repository(bool(data['private']))
            return self.reply(201, {'full_name': LEDGER})
        if not (base == repo or base.startswith(repo + '/')):
            return self.reply(403, {'message': f'the fake administrator does not address {route}'})
        if self.ledger is None:
            return self.reply(404, {'message': 'not found'})
        rest, ledger = base[len(repo):], self.ledger
        if rest == '' and method == 'GET':
            return self.reply(200, {**ledger.repo, 'permissions': {'admin': True, 'push': True, 'pull': True}})
        if rest == '' and method == 'PATCH':
            ledger.repo.update({k: v for k, v in data.items() if k not in self.ignore})
            return self.reply(200, ledger.repo)
        if rest.startswith('/collaborators/') and method == 'PUT':
            ledger.collaborators[rest.split('/')[2]] = data['permission']
            return self.reply(204, None)
        if rest == '/collaborators' and method == 'GET':
            assert query == R.LIST_PAGE, query
            return self.reply(200, [{'login': u} for u in ledger.collaborators],
                              {'x-total-count': str(len(ledger.collaborators))})
        if rest.startswith('/collaborators/') and rest.endswith('/permission') and method == 'GET':
            user = rest.split('/')[2]
            return self.reply(200, {'permission': ledger.collaborators.get(user, 'none'), 'role_name': '',
                                    'user': {'login': user}})
        if rest == '/branch_protections' and method == 'POST':
            ledger.rules.append(PF.rule_view(data, len(ledger.rules) + 2))
            return self.reply(201, data)
        if rest == '/branch_protections' and method == 'GET':
            return self.reply(200, copy.deepcopy(ledger.rules))
        if rest == '/teams' and method == 'GET':
            return self.reply(200, copy.deepcopy(ledger.teams))
        if rest == '/keys' and method == 'GET':
            return self.reply(200, copy.deepcopy(ledger.keys))
        if rest == '/branches/main' and method == 'GET':
            return self.reply(200, {'name': 'main', 'commit': {'id': INITIAL}, 'protected': bool(ledger.rules)})
        if rest.startswith('/git/commits/') and method == 'GET':
            assert query == 'stat=false&verification=false&files=false', query
            sha = rest.split('/')[3]
            return self.reply(200, {'sha': sha, 'parents': [] if sha == INITIAL else [{'sha': INITIAL}]})
        if rest == '/pulls' and method == 'GET':
            assert query == f'state=all&{R.LIST_PAGE}', query
            return self.reply(200, list(self.pulls))
        return self.reply(404, {'message': f'no route {method} {route}'})


class FakeReceipts:
    def __init__(self, keys=()):
        self.keys, self.calls = list(keys), 0

    def __call__(self):
        self.calls += 1
        return list(self.keys)


class Act(unittest.TestCase):
    def setUp(self):
        self.gitea, self.cli = LedgerGitea(), TR.FakeCli()
        for spec in R.ROLES.values():
            self.cli.users_[spec['user']] = {'admin': False, 'type': 'Bot'}
        self.provider = TR.MemoryProvider({G.FINAL_TARGETS[G.SITE_ADMIN]: (G.SITE_ADMIN, TR.ADMIN_PASSWORD),
                                           PC.ENTRY: (PF.AUDITOR, PF.AUDIT_TOKEN)})
        self.receipts = FakeReceipts()

    def run_act(self, owner_act=R.OWNER_ACT, **kw):
        return R.authorization_repository(owner_act=owner_act, http=self.gitea, ctx=(None, None, PORT, self.provider,
                                                                                     self.cli),
                                          receipts=self.receipts, **kw)

    def stopped(self, code, refusal=False, **kw):
        with self.assertRaises(G.GiteaError) as caught:
            self.run_act(**kw)
        self.assertEqual((caught.exception.code, caught.exception.refusal), (code, refusal), str(caught.exception))
        self.assertNotIn(TR.ADMIN_PASSWORD, str(caught.exception))
        self.assertNotIn(PF.AUDIT_TOKEN, str(caught.exception))
        return caught.exception

    def assertNoTokenMinted(self):
        self.assertEqual(self.cli.minted, [])
        self.assertEqual(self.gitea.admin_tokens, [])
        self.assertFalse(any(r['path'].endswith('/tokens') and r['method'] != 'GET' for r in self.gitea.requests))
        self.assertFalse(any(c[:3] == ['admin', 'user', 'generate-access-token'] for c in self.cli.calls))

    def assertFixtureUntouched(self):
        fixture = f'/repos/{FIXTURE}'
        self.assertEqual([r for r in self.gitea.requests if r['path'].startswith(fixture) and r['auth'] != 'token'],
                         [])
        self.assertEqual({r['method'] for r in self.gitea.by('token')} or {'GET'}, {'GET'})


class TheAct(Act):
    def test_every_step_in_order_as_the_administrator_with_no_token(self):
        report = self.run_act()
        repo = f'/repos/{LEDGER}'
        declared = R.authorization_declaration()
        self.assertEqual(self.gitea.writes(), [
            ('POST', '/orgs'), ('POST', f'/orgs/{R.AUTHORIZATION_ORG}/repos'), ('PATCH', repo),
            *(('PUT', f'{repo}/collaborators/{user}') for user in declared['collaborators']),
            *(('POST', f'{repo}/branch_protections') for _rule in declared['rules'])])
        self.assertEqual([(a['method'], a['path'], a['status']) for a in report['actions']],
                         [(m, p, {'POST': 201, 'PATCH': 200, 'PUT': 204}[m]) for m, p in self.gitea.writes()])
        # the administrator by basic authentication only, the auditor's token for GETs only
        self.assertEqual({r['auth'] for r in self.gitea.requests}, {'basic', 'token'})
        self.assertEqual({r['method'] for r in self.gitea.by('token')}, {'GET'})
        self.assertNoTokenMinted()
        self.assertEqual(report['admin_tokens_after'], [])
        self.assertEqual(report['admin_auth']['user'], G.SITE_ADMIN)
        self.assertIn('no token minted', report['admin_auth']['method'])
        # the read-back equals the declaration field for field; main holds its initial commit alone; no pull request
        self.assertEqual(report['state'], 'created')
        self.assertEqual(report['differences'], [])
        readback = report['readback']
        self.assertEqual(readback['collaborators'], declared['collaborators'])
        self.assertEqual(readback['rules'], {r['rule_name']: R._normal_rule(r) for r in declared['rules']})
        self.assertEqual({k: readback['repository'][k] for k in declared['settings']}, declared['settings'])
        self.assertEqual((readback['branch']['head_parents'], readback['pulls'], readback['deploy_keys']), (0, 0, 0))
        self.assertEqual(readback['organization'], R.AUTHORIZATION_ORG_SETTINGS)
        # the auditor's read-only check, its baseline, and the fixture's recorded baseline
        self.assertEqual((report['protection']['status'], report['protection']['code']), ('verified', 'VERIFIED'))
        self.assertRegex(report['protection']['baseline'], r'^sha256:[0-9a-f]{64}$')
        self.assertEqual(report['protection']['baseline'],
                         PC.verify(self.provider, PORT, LEDGER, 'main', http=PF.ProtectionGitea(R, LEDGER)).digest)
        self.assertEqual(report['fixture'], {'repository': FIXTURE, 'status': 'verified', 'code': 'VERIFIED',
                                             'baseline': PC.RECORDED_BASELINES[FIXTURE],
                                             'recorded_baseline': PC.RECORDED_BASELINES[FIXTURE], 'equal': True})
        audited = [r['path'] for r in self.gitea.by('token') if r['path'] != '/token']
        self.assertEqual({p.split('/')[2] + '/' + p.split('/')[3] for p in audited}, {LEDGER, FIXTURE})
        self.assertFixtureUntouched()
        self.assertEqual(self.receipts.calls, 1)
        self.assertEqual(report['recorder_receipts'], [])
        # never a merge, a pull request, a token or an Owner statement
        self.assertFalse(any('/pulls' in p and m != 'GET' or '/merge' in p for m, p in self.gitea.writes()))
        self.assertIsNone(__import__('re').search(r'(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])', json.dumps(report)))

    def test_a_second_run_reports_and_writes_nothing(self):
        first = self.run_act()
        sent = len(self.gitea.requests)
        second = self.run_act()
        self.assertEqual(second['state'], 'already present; nothing written')
        self.assertEqual(second['actions'], [])
        self.assertEqual({r['method'] for r in self.gitea.requests[sent:]}, {'GET'})
        self.assertEqual(second['protection']['baseline'], first['protection']['baseline'])
        self.assertEqual(second['fixture']['equal'], True)
        self.assertNoTokenMinted()

    def test_the_receipts_are_checked_read_only_before_anything_is_sent(self):
        self.receipts = FakeReceipts([R.RECORDER_RECEIPT_PREFIX + 'ab' * 16])
        error = self.stopped('RECORDER_RECEIPTS_PRESENT', refusal=True)
        self.assertIn('nothing was sent', error.detail)
        self.assertEqual((self.gitea.requests, self.provider.reads), ([], []))

    def test_without_the_owner_act_nothing_is_read_or_sent(self):
        for owner_act in (None, '', 'OA-16', 'oa-30', 'OA-30 '):
            with self.subTest(owner_act=owner_act), \
                    mock.patch.object(R, 'context', side_effect=AssertionError('nothing is read')):
                with self.assertRaises(G.GiteaError) as caught:
                    R.authorization_repository(owner_act=owner_act, receipts=self.receipts)
                self.assertEqual((caught.exception.code, caught.exception.refusal), ('OWNER_ACT_REQUIRED', True))
        self.assertEqual((self.gitea.requests, self.provider.reads, self.receipts.calls), ([], [], 0))

    def test_missing_bots_or_owner_refused_before_any_write(self):
        del self.cli.users_[R.ROLES['protection-audit']['user']]
        self.stopped('BOTS_MISSING', refusal=True)
        self.cli.users_[R.ROLES['protection-audit']['user']] = {'admin': False, 'type': 'Bot'}
        del self.cli.users_[G.OWNER]
        self.stopped('OWNER_MISSING', refusal=True)
        self.assertEqual(self.gitea.requests, [])


class Stops(Act):
    """Each stop condition: the act stops there and sends nothing further."""

    def assertNothingAfter(self, method, path):
        last = [(r['method'], r['path']) for r in self.gitea.requests if r['auth'] == 'basic'][-1]
        self.assertEqual(last, (method, path))
        self.assertEqual(self.gitea.by('token'), [])  # no check ran

    def test_a_non_2xx_answer_at_each_write(self):
        repo = f'/repos/{LEDGER}'
        first_user = next(iter(R.collaborators()))
        for method, path in (('POST', '/orgs'), ('POST', f'/orgs/{R.AUTHORIZATION_ORG}/repos'), ('PATCH', repo),
                             ('PUT', f'{repo}/collaborators/{first_user}'), ('POST', f'{repo}/branch_protections')):
            for status in (300, 403, 422, 500):
                with self.subTest(method=method, path=path, status=status):
                    self.setUp()
                    self.gitea.fail[(method, path)] = status
                    error = self.stopped('API_UNEXPECTED')
                    self.assertIn(f'{method} {path}: HTTP {status}', error.detail)
                    self.assertIn('sent before it', error.detail)
                    self.assertNothingAfter(method, path)
                    self.assertNoTokenMinted()

    def test_a_read_back_difference(self):
        damages = {
            "the repository's allow_squash_merge": lambda g: g.ignore.add('allow_squash_merge'),
            'collaborator aieh-intruder': lambda g: g.extra_collaborators.update({'aieh-intruder': 'write'}),
        }
        for named, damage in damages.items():
            with self.subTest(difference=named):
                self.setUp()
                damage(self.gitea)
                error = self.stopped('READBACK_DIFFERENT')
                self.assertIn(named, error.detail)
                self.assertEqual(self.gitea.by('token'), [])
                self.assertEqual(self.gitea.writes()[-1][0], 'POST')  # the last rule; nothing sent after the reads
                self.assertFalse(any(r['path'].endswith('/tokens') for r in self.gitea.requests))

    def test_a_rule_that_reads_back_otherwise(self):
        original = self.gitea.admin

        def admin(method, route, data):
            if method == 'POST' and route.endswith('/branch_protections') and data['rule_name'] == 'work/*':
                data = {**data, 'push_whitelist_usernames': []}
            return original(method, route, data)

        self.gitea.admin = admin
        error = self.stopped('READBACK_DIFFERENT')
        self.assertIn('work/*.push_whitelist_usernames is []', error.detail)

    def test_a_verdict_that_is_not_verified(self):
        del self.provider.entries[PC.ENTRY]  # the auditor's entry missing
        error = self.stopped('PROTECTION_NOT_VERIFIED')
        self.assertIn('CREDENTIAL_MISSING', error.detail)
        self.assertEqual(self.gitea.by('token'), [])
        # the auditor's own view of the repository fails (a fault the administrator's reads do not see)
        self.setUp()
        create = self.gitea.create_repository

        def faulty(private):
            create(private)
            self.gitea.ledger.faults['teams'] = 500

        self.gitea.create_repository = faulty
        error = self.stopped('PROTECTION_NOT_VERIFIED')
        self.assertIn('READ_FAILED', error.detail)
        self.assertFalse(any(r['path'].startswith(f'/repos/{FIXTURE}') for r in self.gitea.requests))

    def test_the_administrator_holding_a_token_afterwards(self):
        self.gitea.admin_tokens.append('left-behind')
        error = self.stopped('ADMIN_HOLDS_TOKEN')
        self.assertIn('left-behind', error.detail)
        self.assertNothingAfter('GET', f'/users/{G.SITE_ADMIN}/tokens')

    def test_the_fixture_no_longer_verifying(self):
        self.gitea.fixture.rule('main')['enable_push'] = True
        error = self.stopped('FIXTURE_NOT_VERIFIED')
        self.assertIn('drift', error.detail)
        self.setUp()
        with mock.patch.object(PC, 'RECORDED_BASELINES', {FIXTURE: 'sha256:' + '0' * 64}):
            error = self.stopped('FIXTURE_NOT_VERIFIED')
        self.assertIn('verified', error.detail)
        self.assertIn('sha256:0000000000000000', error.detail)

    def test_an_existing_organization_or_repository_is_never_adopted(self):
        def org_alone(g):
            g.orgs[R.AUTHORIZATION_ORG] = dict(R.AUTHORIZATION_ORG_SETTINGS)

        def other_collaborator(g):
            g.provisioned()
            g.ledger.collaborators['aieh-bot-verifier'] = 'write'

        def a_pull_request(g):
            g.provisioned()
            g.pulls.append({'number': 1})

        def public_org(g):
            g.provisioned()
            g.orgs[R.AUTHORIZATION_ORG]['visibility'] = 'public'

        for name, state in (('the organization alone', org_alone), ('another permission', other_collaborator),
                            ('a pull request', a_pull_request), ('a public organization', public_org)):
            with self.subTest(state=name):
                self.setUp()
                state(self.gitea)
                error = self.stopped('AUTHORIZATION_REPOSITORY_EXISTS', refusal=True)
                self.assertIn('nothing was written', error.detail)
                self.assertEqual(self.gitea.writes(), [])
                self.assertEqual(self.gitea.by('token'), [])

    def test_a_provisioned_repository_is_reported_without_a_write(self):
        self.gitea.provisioned()
        report = self.run_act()
        self.assertEqual((report['state'], report['actions'], self.gitea.writes()),
                         ('already present; nothing written', [], []))
        self.assertEqual(report['protection']['status'], 'verified')


class Receipts(unittest.TestCase):
    """The read-only check of the managed integration store, on throwaway stores."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='aieh-ledger-')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'integration.sqlite'

    def test_the_prefix_is_the_recorder_s(self):
        self.assertEqual(R.RECORDER_RECEIPT_PREFIX, ED.RECEIPT_PREFIX)

    def test_a_missing_store_has_none(self):
        self.assertEqual(R.recorder_receipts(self.path), [])
        self.assertFalse(self.path.exists())

    def test_it_lists_the_recorder_s_receipts_and_writes_nothing(self):
        store_module = G._load_integration_store()
        with store_module.open_store(self.path) as store:
            store.reserve('owner-authorization/v1/' + 'ab' * 16, {'kind': 'x'}, actor='authorization-recorder/1')
            store.reserve('credential-act/v1/rotate-1', {'kind': 'y'}, actor='gitea_roles rotate')
        before = self.path.read_bytes()
        self.assertEqual(R.recorder_receipts(self.path), ['owner-authorization/v1/' + 'ab' * 16])
        self.assertEqual(self.path.read_bytes(), before)
        with store_module.open_store(self.path) as store:
            self.assertEqual(len(store.attempts()), 2)

    def test_the_managed_store_is_resolved_without_creating_anything(self):
        state = Path(self.tmp.name) / 'state'
        with mock.patch.object(G.paths, 'resolve', return_value=SimpleNamespace(paths={'state': state})), \
                mock.patch.object(G.paths, 'ensure', side_effect=AssertionError('nothing is created')):
            self.assertEqual(R.managed_recorder_receipts(), [])
        self.assertFalse(state.exists())
        state.joinpath('integration').mkdir(parents=True)
        store_module = G._load_integration_store()
        with store_module.open_store(state / 'integration' / 'integration.sqlite') as store:
            store.reserve('owner-authorization/v1/' + 'cd' * 16, {'kind': 'x'}, actor='authorization-recorder/1')
        with mock.patch.object(G.paths, 'resolve', return_value=SimpleNamespace(paths={'state': state})):
            self.assertEqual(R.managed_recorder_receipts(), ['owner-authorization/v1/' + 'cd' * 16])


class CommandLine(unittest.TestCase):
    def main(self, argv, **patches):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(R, 'os', SimpleNamespace(name='nt')), mock.patch.object(sys, 'stdout', out), \
                mock.patch.object(sys, 'stderr', err), mock.patch.object(R, 'context',
                                                                         side_effect=AssertionError('not read')):
            code = R.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_refused_without_the_owner_act(self):
        for argv in (['authorization-repository'], ['authorization-repository', '--owner-act', 'OA-16']):
            with self.subTest(argv=argv):
                code, out, err = self.main(argv)
                self.assertEqual((code, out), (2, ''))
                self.assertIn('OWNER_ACT_REQUIRED', err)
                self.assertIn('nothing was read or sent', err)

    def test_the_act_s_report_is_shown_whole(self):
        digest = 'sha256:' + 'ab' * 32
        with mock.patch.object(R, 'authorization_repository', return_value={'protection': {'baseline': digest}}) as act:
            code, out, err = self.main(['authorization-repository', '--owner-act', 'OA-30'])
        self.assertEqual(code, 0, err)
        act.assert_called_once_with(owner_act='OA-30')
        self.assertEqual(json.loads(out)['protection']['baseline'], digest)  # not cut by the token redaction
        self.assertIn('I7 no-exposure scan: clean', err)
        leaky = {'commit': 'c' * 40}
        with mock.patch.object(R, 'authorization_repository', return_value=leaky):
            code, out, err = self.main(['authorization-repository', '--owner-act', 'OA-30'])
        self.assertEqual((code, out), (1, ''))
        self.assertIn('EXPOSURE_FOUND', err)

    def test_the_help_names_the_owner_act(self):
        out = io.StringIO()
        with mock.patch.object(sys, 'stdout', out), self.assertRaises(SystemExit):
            R.main(['authorization-repository', '--help'])
        self.assertIn('This is Owner act OA-30', out.getvalue())
        self.assertIn('--owner-act', out.getvalue())
        out = io.StringIO()
        with mock.patch.object(sys, 'stdout', out), self.assertRaises(SystemExit):
            R.main(['--help'])
        self.assertIn('Owner act OA-30', ' '.join(out.getvalue().split()))


if __name__ == '__main__':
    unittest.main()
