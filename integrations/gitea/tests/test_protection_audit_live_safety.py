"""The live protection-auditor tests' write safety (test_protection_audit_live.py; OA-16 Act C), offline.

The negative phase's write probes are run here, through the live module's own test methods, against fakes:
``ProbeGitea``, protection_fake.ProtectionGitea (called in memory with gitea_host.http_get's signature, no
socket) with the snapshot's further routes and three ways a Gitea could wrongly let a write past the
read:repository scope: ``accept`` (every write answered 201), ``reject`` (every write answered 422) and
``validate`` (Gitea 28.3.0's body binding and handler checks as modelled here: ``Required`` and
``AlphaDashDot`` names, ``GitRefName`` branches, an absent branch, pull request, rule, collaborator or team;
an accepted write is applied, and a create recorded). The git push probes run through the repository module
against a smart-HTTP server on 127.0.0.1 in this process (Dulwich's ``dulwich.web``), which refuses the
auditor's credential on receive-pack (403, as Gitea does for a read token) or wrongly serves it.

Covered: the circuit breaker (a 2xx on the first write trips it and no later write is sent, counted at the
fake; a later class sends none; swallowing the failure does not reopen it; a snapshot change trips it;
tearDownModule fails the run and reports the trip and every write not sent; a refusal other than 403 fails
without tripping it); each write probe harmless or rejected by the modelled validation, while the bodies the
probes used before would have created something; the current values repeated; nothing sent on an incomplete
snapshot or a permission a PUT cannot repeat; the token probe; the push probes refused, withheld by the
module when wrongly authorized (no update sent, the remote unchanged), a succeeding push a security failure;
the skip without the opt-in. Every value is synthetic.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


L = _load('test_protection_audit_live', HERE / 'test_protection_audit_live.py')
PF = _load('aieh_gitea_protection_fake', HERE / 'protection_fake.py')
RA = _load('repository_access', HERE.parents[1] / 'repository' / 'repository_access.py')
R, PC = L.R, L.PC
REPO_ROUTE = f'/repos/{PF.REPOSITORY}'
WRITE_TEST = 'test_every_write_is_refused_by_the_scope'
PUSH_TEST = 'test_git_push_through_the_repository_module_is_refused'
TOKEN_TEST = 'test_no_password_and_no_more_as_a_password'
CREATED_TOKEN = 'e' * 40
SCOPES = {f'{level}:{category}' for level in ('read', 'write')
          for category in ('activitypub', 'admin', 'issue', 'misc', 'notification', 'organization', 'package',
                           'repository', 'user')} | {'all', 'public-only'}


def refname_ok(name):
    """git check-ref-format's rules for a branch name (Gitea's GitRefName binding), as far as the probes need."""
    return (bool(name) and '..' not in name and '@{' not in name and '//' not in name
            and not re.search(r'[\x00-\x20\x7f~^:?*\[\\]', name) and not name.startswith('/')
            and not name.endswith(('/', '.', '.lock')) and not any(p.startswith('.') for p in name.split('/')))


class ProbeGitea(PF.ProtectionGitea):
    """ProtectionGitea with the snapshot's further routes (branches, tags, hooks, /repos/search) and a MODE
    for writes: ``gitea`` (the scope refuses them, 403: the base fake), or past a broken scope check:
    ``accept``, ``reject`` or ``validate`` (see the module docstring). ``created`` lists every durable object
    an accepted write created; ``on_write(fake)`` runs on each write; ``DELETE /token`` revokes the caller."""

    def __init__(self, mode='gitea'):
        super().__init__(R)
        self.mode = mode
        self.branch_list = {'main': 'c' * 40}
        self.tags, self.hooks, self.visible, self.created = [], [], [PF.REPOSITORY], []
        self.on_write = None

    @property
    def writes(self):
        return [r for r in self.requests if r['method'] not in ('GET', 'HEAD')]

    def state(self):
        return copy.deepcopy((self.rules, self.collaborators, self.repo, self.branch_list, self.keys, self.hooks,
                              self.teams, self.tags, self.visible, self.created))

    def _handle(self, method, path, headers, body):
        route = urllib.parse.urlsplit(path).path.removeprefix('/api/v1')
        write = method not in ('GET', 'HEAD')
        extra = {f'{REPO_ROUTE}/branches': 'branches', f'{REPO_ROUTE}/tags': 'tags', f'{REPO_ROUTE}/hooks': 'hooks',
                 '/repos/search': 'search'}.get(route)
        if not (write and (self.mode != 'gitea' or route == '/token')) and not (not write and extra):
            if write and self.on_write is not None:
                self.on_write(self)
            return super()._handle(method, path, headers, body)
        doer, kind = self.doer(headers)
        self.requests.append({'method': method, 'path': path.removeprefix('/api/v1'), 'auth': kind,
                              'doer': doer['login'] if doer else None})
        if doer is None:
            return self.reply(401, {'message': 'token is required'})
        if not write:
            fault = self.fault(extra)
            if fault is not None:
                return fault
            return self.reply(200, {
                'branches': [{'name': n, 'commit': {'id': c}} for n, c in self.branch_list.items()],
                'tags': self.tags, 'hooks': self.hooks,
                'search': {'ok': True, 'data': [{'full_name': f} for f in self.visible]}}[extra])
        if self.on_write is not None:
            self.on_write(self)
        if route == '/token':
            token = headers.get('authorization', '').removeprefix('token ')
            self.tokens.pop(token, None)
            return self.reply(204, None)
        return self.past_the_scope(method, route, json.loads(body) if body else None)

    def past_the_scope(self, method, route, body):
        if self.mode == 'accept':
            if route.endswith('/tokens'):
                self.tokens[CREATED_TOKEN] = {'login': PF.AUDITOR, 'scopes': ['all'], 'name': 'created'}
                self.created.append(('token', route))
                return self.reply(201, {'id': 11, 'name': 'created', 'sha1': CREATED_TOKEN})
            self.created.append((method, route))
            return self.reply(201, {'id': 99})
        if self.mode == 'reject':
            return self.reply(422, {'message': 'the fake rejects every write (reject mode)'})
        status, payload = self.validate(method, route, body if isinstance(body, dict) else {})
        return self.reply(status, payload)

    def create(self, kind, route, payload=None):
        self.created.append((kind, route))
        return 201, payload or {'id': 99}

    def validate(self, method, route, body):
        """Gitea 28.3.0's answer to a write past the scope check: the route's body binding (422), then its
        handler (an absent object 404; otherwise the write is applied)."""
        def missing(*fields):
            absent = [f for f in fields if not body.get(f)]
            return (422, {'message': f'[{", ".join(absent)}]: Required'}) if absent else None

        if method == 'POST' and (route == '/user/repos' or re.fullmatch(r'/orgs/[^/]+/repos', route)):
            name = body.get('name')
            if not name:
                return 422, {'message': '[Name]: Required'}
            if not re.fullmatch(r'[\w.-]+', name) or len(name) > 100:
                return 422, {'message': '[Name]: AlphaDashDot'}
            return self.create('repository', route)
        if method == 'POST' and re.fullmatch(r'/users/[^/]+/tokens', route):
            if not body.get('name'):
                return 422, {'message': '[Name]: Required'}
            if not body.get('scopes') or any(s not in SCOPES for s in body['scopes']):
                return 400, {'message': 'invalid access token scope'}
            self.tokens[CREATED_TOKEN] = {'login': PF.AUDITOR, 'scopes': list(body['scopes']), 'name': body['name']}
            return self.create('token', route, {'id': 11, 'name': body['name'], 'sha1': CREATED_TOKEN})
        if not (route == REPO_ROUTE or route.startswith(REPO_ROUTE + '/')):
            return 404, {'message': 'not found'}
        rest = urllib.parse.unquote(route[len(REPO_ROUTE):])
        if method == 'POST' and rest.startswith('/contents/'):
            branch, new = body.get('branch') or 'main', body.get('new_branch')
            if not refname_ok(branch) or (new and not refname_ok(new)):
                return 422, {'message': '[BranchName]: GitRefName'}
            if branch not in self.branch_list:
                return 404, {'message': f'branch does not exist [name: {branch}]'}
            self.branch_list[new or branch] = 'd' * 40
            return self.create('commit', route)
        if method == 'POST' and rest == '/keys':
            return missing('title', 'key') or self.create('deploy key', route)
        if method == 'POST' and rest == '/keys/tokens':
            return missing('title') or self.create('deploy token', route)
        if method == 'POST' and rest == '/hooks':
            return missing('type', 'config') or self.create('webhook', route)
        if method == 'POST' and re.fullmatch(r'/pulls/\d+/merge', rest):
            return 404, {'message': 'pull request does not exist'}
        if method == 'POST' and rest == '/branch_protections/priority':
            ids = body.get('ids') or []
            return (204, None) if not ids else (200, {'reordered': ids})
        if rest.startswith('/branch_protections/'):
            name = rest[len('/branch_protections/'):]
            rule = next((r for r in self.rules if r['rule_name'] == name), None)
            if rule is None:
                return 404, {'message': 'branch protection does not exist'}
            if method == 'DELETE':
                self.rules.remove(rule)
                return 204, None
            rule.update({k: v for k, v in body.items() if k in R.PROTECTION_FIELDS})
            return 200, rule
        if rest.startswith('/collaborators/'):
            user = rest[len('/collaborators/'):]
            if method == 'PUT':
                self.collaborators[user] = body.get('permission')
                return 204, None
            if user not in self.collaborators:
                return 404, {'message': 'user does not exist'}
            del self.collaborators[user]
            return 204, None
        if rest.startswith('/teams/'):
            name = rest[len('/teams/'):]
            if not any(t['name'] == name for t in self.teams):
                return 404, {'message': 'team does not exist'}
            self.teams = [t for t in self.teams if t['name'] != name]
            return 204, None
        if method == 'PATCH' and rest == '':
            self.repo.update(body)
            return 200, self.repo
        return 404, {'message': f'no route {method} {route}'}


def context(fake, port=3000):
    return SimpleNamespace(port=port, provider=None, token=PF.AUDIT_TOKEN, http=fake)


def live_case(cls, method, ctx):
    case = getattr(L, cls)(method)
    case.ctx = ctx
    return case


class Fresh(unittest.TestCase):
    """Each test with its own breaker, results and no report file, so the live module's state is untouched."""

    def setUp(self):
        self.breaker, self.results = L.Breaker(), []
        for patch in (mock.patch.object(L, 'BREAKER', self.breaker), mock.patch.object(L, 'RESULTS', self.results),
                      mock.patch.object(L, 'REPORT', None),
                      mock.patch.object(L.G, 'http_get', side_effect=AssertionError('a real HTTP request'))):
            patch.start()
            self.addCleanup(patch.stop)

    def run_live(self, cls, method, ctx):
        case = live_case(cls, method, ctx)
        try:
            getattr(case, method)()
        finally:
            case.doCleanups()

    def not_sent(self):
        return [r['action'] for r in self.results if r.get('status') == 'not sent']

    def snapshot_of(self, fake):
        return live_case('TestWrites', WRITE_TEST, context(fake)).snapshot()


class CircuitBreaker(Fresh):
    def test_a_2xx_on_the_first_write_trips_the_breaker_and_no_later_write_is_sent(self):
        fake = ProbeGitea('accept')
        with self.assertRaises(L.SecurityFailure) as caught:
            self.run_live('TestWrites', WRITE_TEST, context(fake))
        self.assertNotIsInstance(caught.exception, L.BreakerOpen)
        self.assertEqual(len(fake.writes), 1)
        probes = L.write_probes(self.snapshot_of(ProbeGitea()), 'absent')
        self.assertIn(probes[0].action, self.breaker.tripped_by)
        self.assertIn('answered 201', self.breaker.tripped_by)
        self.assertEqual(self.breaker.withheld, [p.action for p in probes[1:]])
        self.assertEqual(self.not_sent(), [p.action for p in probes[1:]])

    def test_once_tripped_no_class_sends_a_write(self):
        L.SecurityFailure('an earlier probe answered 201')
        fake = ProbeGitea('accept')
        with self.assertRaises(L.BreakerOpen):
            self.run_live('TestWrites', WRITE_TEST, context(fake))
        with self.assertRaises(L.BreakerOpen):
            self.run_live('TestIdentity', TOKEN_TEST, context(fake))
        repo = mock.Mock()
        with self.assertRaises(L.BreakerOpen):
            live_case('TestWrites', PUSH_TEST, context(fake)).push_refused(
                RA, repo, 'http://127.0.0.1:1/x.git', None, L.push_probes('0' * 40, 'absent')[0])
        repo.push.assert_not_called()
        self.assertEqual(fake.writes, [])
        self.assertTrue(fake.requests)   # the reads still answered
        self.assertEqual(self.breaker.tripped_by, 'an earlier probe answered 201')
        self.assertEqual(len(self.breaker.withheld), len(L.write_probes(self.snapshot_of(ProbeGitea()), 'a')) + 2)

    def test_a_swallowed_security_failure_does_not_reopen_the_breaker(self):
        fake = ProbeGitea('accept')
        case = live_case('TestWrites', WRITE_TEST, context(fake))
        with case.subTest(probe='first'):   # what unittest would do: record it and carry on
            try:
                case.refused('a write', 'POST', f'{REPO_ROUTE}/keys', {'title': ''})
            except L.SecurityFailure:
                pass
        with self.assertRaises(L.BreakerOpen):
            case.refused('a later write', 'POST', f'{REPO_ROUTE}/hooks', {'type': ''})
        self.assertEqual(len(fake.writes), 1)

    def test_a_snapshot_change_trips_the_breaker(self):
        fake = ProbeGitea()

        def push_a_branch(f):
            f.branch_list['work/unexpected'] = 'd' * 40
        fake.on_write = push_a_branch
        with self.assertRaises(L.SecurityFailure) as caught:
            self.run_live('TestWrites', WRITE_TEST, context(fake))
        self.assertIn('the fixture changed during the write probes: branches', str(caught.exception))
        self.assertIsNotNone(self.breaker.tripped_by)
        self.assertEqual(len(fake.writes), len(L.write_probes(self.snapshot_of(ProbeGitea()), 'a')))
        changed = next(r for r in self.results if r.get('status') == 'changed')
        self.assertEqual(list(changed['changed']), ['branches'])

    def test_a_refusal_other_than_403_fails_without_tripping_and_sends_every_probe(self):
        fake = ProbeGitea('reject')
        with self.assertRaises(AssertionError) as caught:
            self.run_live('TestWrites', WRITE_TEST, context(fake))
        self.assertNotIsInstance(caught.exception, L.SecurityFailure)
        self.assertIn('refused with 422, not by the scope', str(caught.exception))
        self.assertIsNone(self.breaker.tripped_by)
        self.assertEqual(len(fake.writes), len(L.write_probes(self.snapshot_of(ProbeGitea()), 'a')))
        self.assertEqual(fake.created, [])

    def test_tear_down_module_fails_the_run_and_reports_the_trip(self):
        L.tearDownModule()   # not tripped: nothing raised, nothing written
        tmp = Path(tempfile.mkdtemp(prefix='aieh-audit-safety-'))
        self.addCleanup(shutil.rmtree, tmp)
        report = tmp / 'report.json'
        fake = ProbeGitea('accept')
        with self.assertRaises(L.SecurityFailure):
            self.run_live('TestWrites', WRITE_TEST, context(fake))
        with mock.patch.object(L, 'REPORT', str(report)), self.assertRaises(AssertionError) as caught:
            L.tearDownModule()
        self.assertIn('SECURITY FAILURE in this run', str(caught.exception))
        rows = json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual(rows[-1], {'action': 'circuit breaker', 'tripped_by': self.breaker.tripped_by,
                                    'not_sent': self.breaker.withheld})
        self.assertEqual(len(rows[-1]['not_sent']), len(L.write_probes(self.snapshot_of(ProbeGitea()), 'a')) - 1)
        self.assertNotIn(PF.AUDIT_TOKEN, report.read_text(encoding='utf-8'))


class WriteProbes(Fresh):
    def probes(self, fake=None):
        return L.write_probes(self.snapshot_of(fake or ProbeGitea()), 'aieh-probe-absent-0123')

    def test_the_scope_refuses_every_probe_and_the_test_passes(self):
        fake = ProbeGitea()
        self.run_live('TestWrites', WRITE_TEST, context(fake))
        probes = self.probes()

        def absent(path):
            return re.sub(r'aieh-probe-absent-[0-9a-f]+', 'ABSENT', path)
        self.assertEqual([(w['method'], absent(w['path'])) for w in fake.writes],
                         [(p.method, absent(p.path)) for p in probes])
        rows = [r for r in self.results if 'if accepted' in r]
        self.assertEqual([r['status'] for r in rows], [403] * len(probes))
        self.assertEqual([r['if accepted'] for r in rows], [p.if_accepted for p in probes])
        self.assertIsNone(self.breaker.tripped_by)

    def test_every_probe_is_harmless_or_rejected_by_gitea_s_validation(self):
        kinds = set()
        for probe in self.probes():
            with self.subTest(probe=probe.action):
                fake = ProbeGitea('validate')
                before = fake.state()
                status, _payload = R.Api(3000, PF.AUDIT_TOKEN, fake).call(probe.method, probe.path, probe.body)
                self.assertEqual(fake.created, [])
                if probe.if_accepted.startswith('made non-mutating'):
                    kinds.add('non-mutating')
                    self.assertIn(status, (400, 404, 422))
                else:
                    self.assertTrue(probe.if_accepted.startswith('harmless'), probe.if_accepted)
                    kinds.add('harmless')
                self.assertEqual(fake.state(), before)
        self.assertEqual(kinds, {'harmless', 'non-mutating'})

    def test_the_former_bodies_would_have_created_something(self):
        """A control on the modelled validation: the bodies the probes used before this correction."""
        former = [('POST', f'{REPO_ROUTE}/contents/aieh-audit-probe.txt',
                   {'content': 'cHJvYmUK', 'message': 'probe', 'branch': 'main'}),
                  ('POST', '/user/repos', {'name': 'aieh-probe-absent-0123', 'private': True}),
                  ('POST', f'/orgs/{R.FIXTURE_ORG}/repos', {'name': 'aieh-probe-absent-0123', 'private': True}),
                  ('POST', f'/users/{PF.AUDITOR}/tokens', {'name': 'aieh-probe', 'scopes': ['all']}),
                  ('PATCH', f'{REPO_ROUTE}/branch_protections/main', {'required_approvals': 2}),
                  ('PUT', f'{REPO_ROUTE}/collaborators/{R.ROLES["verifier"]["user"]}', {'permission': 'write'})]
        for method, path, body in former:
            with self.subTest(path=path):
                fake = ProbeGitea('validate')
                before = fake.state()
                status = R.Api(3000, PF.AUDIT_TOKEN, fake).call(method, path, body)[0]
                self.assertIn(status, (200, 201, 204))
                self.assertNotEqual(fake.state(), before)

    def test_the_probe_bodies(self):
        probes = {p.action: p for p in self.probes()}
        contents = next(p for p in probes.values() if '/contents/' in p.path)
        self.assertNotIn('new_branch', contents.body)
        self.assertFalse(refname_ok(contents.body['branch']))
        self.assertNotEqual(contents.body['branch'], R.DEFAULT_BRANCH)
        creations = [p for p in probes.values() if p.path in ('/user/repos', f'/orgs/{R.FIXTURE_ORG}/repos')]
        self.assertEqual(len(creations), 2)
        self.assertTrue(all(p.body['name'] == '' for p in creations))
        self.assertEqual(L.TOKEN_PROBE_BODY['name'], '')
        self.assertTrue(set(L.TOKEN_PROBE_BODY['scopes']) - SCOPES)
        self.assertEqual({p.method for p in probes.values()}, {'PATCH', 'DELETE', 'POST', 'PUT'})

    def test_the_patch_and_put_bodies_repeat_what_was_read(self):
        fake = ProbeGitea()
        fake.rule('main')['required_approvals'] = 2
        fake.collaborators[R.ROLES['verifier']['user']] = 'write'
        fake.repo['allow_merge_commits'] = False
        bodies = {p.path: p.body for p in self.probes(fake) if p.method in ('PATCH', 'PUT')}
        self.assertEqual(bodies, {f'{REPO_ROUTE}/branch_protections/main': {'required_approvals': 2},
                                  f'{REPO_ROUTE}/collaborators/{PF.AUDITOR}': {'permission': 'admin'},
                                  f'{REPO_ROUTE}/collaborators/{R.ROLES["verifier"]["user"]}': {'permission': 'write'},
                                  REPO_ROUTE: {'allow_merge_commits': False}})

    def test_nothing_is_sent_when_a_current_value_cannot_be_repeated(self):
        fake = ProbeGitea()
        fake.collaborators[PF.AUDITOR] = 'owner'
        with self.assertRaises(AssertionError) as caught:
            self.run_live('TestWrites', WRITE_TEST, context(fake))
        self.assertIn('not exercised', str(caught.exception))
        self.assertEqual(fake.writes, [])

    def test_nothing_is_sent_on_an_incomplete_snapshot(self):
        for route, fault in (('hooks', 403), ('search', 500), ('branches', 'wrong-kind')):
            with self.subTest(route=route):
                fake = ProbeGitea()
                fake.faults[route] = fault
                with self.assertRaises(AssertionError) as caught:
                    self.run_live('TestWrites', WRITE_TEST, context(fake))
                self.assertIn('not exercised: the snapshot before the write probes is incomplete',
                              str(caught.exception))
                self.assertEqual(fake.writes, [])
        fake = ProbeGitea()
        fake.tags = [{'name': f't{n}', 'id': f'{n:040x}'} for n in range(L.LIST_LIMIT)]
        with self.assertRaises(AssertionError) as caught:
            self.run_live('TestWrites', WRITE_TEST, context(fake))
        self.assertIn('a full page', str(caught.exception))
        self.assertEqual(fake.writes, [])

    def test_the_snapshot_fields(self):
        snap = self.snapshot_of(ProbeGitea())
        self.assertEqual(set(snap), {'main', 'rules', 'roster', 'settings', 'branches', 'tags', 'deploy_keys',
                                     'webhooks', 'teams', 'repositories', 'permissions'})
        self.assertEqual(L.incomplete(snap), [])
        self.assertEqual(snap['repositories'], [PF.REPOSITORY])
        self.assertEqual(snap['permissions'], dict(R.collaborators()))
        self.assertEqual(snap['branches'], [['main', 'c' * 40]])


class TokenProbe(Fresh):
    def test_refused_by_the_scope(self):
        fake = ProbeGitea()
        self.run_live('TestIdentity', TOKEN_TEST, context(fake))
        self.assertEqual([(w['method'], w['path'], w['auth']) for w in fake.writes],
                         [('POST', f'/users/{PF.AUDITOR}/tokens', 'basic')])

    def test_past_a_broken_scope_the_body_is_rejected_and_nothing_is_created(self):
        fake = ProbeGitea('validate')
        with self.assertRaises(AssertionError) as caught:
            self.run_live('TestIdentity', TOKEN_TEST, context(fake))
        self.assertNotIsInstance(caught.exception, L.SecurityFailure)
        self.assertEqual(fake.created, [])
        self.assertNotIn(CREATED_TOKEN, fake.tokens)

    def test_a_created_token_trips_the_breaker_and_is_revoked(self):
        fake = ProbeGitea('accept')
        with self.assertRaises(L.SecurityFailure):
            self.run_live('TestIdentity', TOKEN_TEST, context(fake))
        self.assertIsNotNone(self.breaker.tripped_by)
        self.assertNotIn(CREATED_TOKEN, fake.tokens)   # the last resort ran
        self.assertEqual([w['method'] + ' ' + w['path'] for w in fake.writes],
                         [f'POST /users/{PF.AUDITOR}/tokens', 'DELETE /token'])


class Skips(Fresh):
    def test_every_class_skips_without_the_opt_in(self):
        with mock.patch.object(L, 'PHASE', ''), mock.patch.object(L, '_LIVE', []), \
                mock.patch.object(L.G, 'credential_provider', side_effect=AssertionError('read Credential Manager')):
            for name in ('TestIdentity', 'TestReads', 'TestWrites', 'TestNoEscape', 'QualifyLive'):
                with self.subTest(cls=name), self.assertRaises(unittest.SkipTest) as caught:
                    getattr(L, name).setUpClass()
                self.assertIn('opt-in', str(caught.exception))


# ---------------------------------------------------------------- the git push probes


class Quiet(WSGIRequestHandler):
    def log_message(self, *_args):
        pass


class GitServer:
    """A smart-HTTP server on 127.0.0.1 serving the fixture repository (one commit on main) at
    /aieh-authz-fixture/authz.git: the auditor's credential reads; receive-pack answers it 403 unless
    ``accept_push`` (a Gitea that wrongly authorizes the read token); anything else 401."""

    def __init__(self):
        RA.dulwich_modules()
        from dulwich import objects, repo, server, web
        from dulwich.config import StackedConfig
        self.repo = r = repo.MemoryRepo()
        r.get_config_stack = lambda: StackedConfig([r.get_config()])
        blob = objects.Blob.from_string(b'fixture\n')
        tree = objects.Tree()
        tree.add(b'README.md', 0o100644, blob.id)
        commit = objects.Commit()
        commit.tree, commit.parents = tree.id, []
        commit.author = commit.committer = b'Fixture <fixture@example.invalid>'
        commit.author_time = commit.commit_time = 1762992000
        commit.author_timezone = commit.commit_timezone = 0
        commit.message = b'fixture\n'
        for obj in (blob, tree, commit):
            r.object_store.add_object(obj)
        r.refs[b'refs/heads/main'] = commit.id
        r.refs.set_symbolic_ref(b'HEAD', b'refs/heads/main')
        app = web.make_wsgi_chain(server.DictBackend({f'/{PF.REPOSITORY}.git': r}))
        allowed = RA.Credential(PC.AUDITOR, PF.AUDIT_TOKEN).authorization()
        self.requests, self.accept_push = [], False

        def authorizing(environ, start_response):
            self.requests.append((environ['REQUEST_METHOD'], environ['PATH_INFO'], environ.get('QUERY_STRING', '')))
            if environ.get('HTTP_AUTHORIZATION') != allowed:
                start_response('401 Unauthorized', [('WWW-Authenticate', 'Basic realm="test"')])
                return [b'authentication required\n']
            if 'git-receive-pack' in environ['PATH_INFO'] + environ.get('QUERY_STRING', '') and not self.accept_push:
                start_response('403 Forbidden', [('Content-Type', 'text/plain')])
                return [b'read only\n']
            return app(environ, start_response)

        self.httpd = WSGIServer(('127.0.0.1', 0), Quiet)
        self.httpd.set_app(authorizing)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()

    def refs(self):
        return dict(self.repo.get_refs())

    def receive_pack(self):
        return [r for r in self.requests if 'git-receive-pack' in r[1] + r[2]]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.repo.close()


class PushProbes(Fresh):
    category = 'contract'

    @classmethod
    def setUpClass(cls):
        cls.server = GitServer()
        cls.addClassCleanup(cls.server.close)

    def setUp(self):
        super().setUp()
        self.server.requests.clear()
        self.server.accept_push = False
        self.before = self.server.refs()
        patch = mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('a process was launched'))
        patch.start()
        self.addCleanup(patch.stop)

    def run_push(self):
        self.run_live('TestWrites', PUSH_TEST, context(ProbeGitea(), self.server.port))

    def test_refused_at_the_advertisement_and_no_update_sent(self):
        self.run_push()
        self.assertEqual([(m, q) for m, _p, q in self.server.receive_pack()], [('GET', 'service=git-receive-pack')] * 2)
        self.assertEqual(self.server.refs(), self.before)
        rows = [r for r in self.results if r['action'].startswith('git push')]
        self.assertEqual([r['status'] for r in rows], ['PUSH_REFUSED'] * 2)
        self.assertEqual([r['if accepted'] for r in rows], [L.NOT_FAST_FORWARD, L.ABSENT_DELETE])

    def test_wrongly_authorized_the_module_sends_no_update(self):
        self.server.accept_push = True
        with self.assertRaises(AssertionError) as caught:
            self.run_push()
        self.assertNotIsInstance(caught.exception, L.SecurityFailure)
        self.assertIn('PUSH_REJECTED, not refused by the scope', str(caught.exception))
        self.assertEqual([m for m, _p, _q in self.server.receive_pack()], ['GET', 'GET'])   # no POST: no update
        self.assertEqual(self.server.refs(), self.before)
        self.assertIsNone(self.breaker.tripped_by)
        self.assertEqual([r['status'] for r in self.results if r['action'].startswith('git push')],
                         ['PUSH_REJECTED'] * 2)

    def test_once_tripped_no_push_is_sent(self):
        L.SecurityFailure('an earlier probe answered 201')
        with self.assertRaises(L.BreakerOpen):
            self.run_push()
        self.assertEqual(self.server.receive_pack(), [])
        self.assertEqual(self.not_sent(), [p.action for p in L.push_probes('0' * 40, 'a')])

    def test_a_push_that_succeeds_is_a_security_failure(self):
        repo = mock.Mock()
        repo.push.return_value = RA.RefUpdate('refs/heads/main', 'a' * 40, 'b' * 40)
        case = live_case('TestWrites', PUSH_TEST, context(ProbeGitea()))
        probes = L.push_probes('b' * 40, 'absent')
        with self.assertRaises(L.SecurityFailure):
            case.sequence(probes, lambda p: case.push_refused(RA, repo, 'http://127.0.0.1:1/x.git', None, p))
        self.assertEqual(repo.push.call_count, 1)
        self.assertEqual(self.breaker.withheld, [probes[1].action])

    def test_the_push_probes(self):
        main, delete = L.push_probes('b' * 40, 'aieh-probe-absent-00')
        self.assertEqual(main.path, f'{"b" * 40}:refs/heads/main')   # no '+': never forced
        self.assertEqual(delete.path, ':refs/heads/work/aieh-probe-absent-00')


if __name__ == '__main__':
    unittest.main()
