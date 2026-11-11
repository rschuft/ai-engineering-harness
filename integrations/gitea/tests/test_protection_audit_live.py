"""Live tests of the protection auditor (Owner decision OA-16; decision 0012 point 6): opt-in, never by default.

Each phase is a separate Owner act and runs only when AIEH_PROTECTION_AUDIT_LIVE names it, on Windows, under
the tools interpreter, while the managed Gitea answers and the Credential Manager entry "AIEH Gitea bot
protection-audit" exists (gitea_roles.py provision) and the fixture repository answers the auditor
(gitea_roles.py fixture). Otherwise every class skips with its reason, so the ordinary suites never read
Credential Manager or reach Gitea. Tokens are read from the credential provider into memory by the product
code (gitea_roles.read_token) and sent only in Authorization headers; nothing prints, logs or asserts on a
token. AIEH_PROTECTION_AUDIT_REPORT, when set, names a JSON file that receives every probe (action,
expectation, HTTP status or module code, Gitea's message).

**Phase ``negative``** (``AIEH_PROTECTION_AUDIT_LIVE=negative``; reads the auditor's and the verifier bot's
entries; writes nothing if Gitea behaves as read at the pinned source). The auditor's token
(read:repository, of a repository administrator of the fixture) must:

- identify itself: ``GET /token`` answers its login aieh-bot-protection-audit and scopes exactly
  ``read:repository``; a password (random, or the token itself as a basic-authentication password on a
  user route) gets no more;
- read: the fixture's rules (200, exactly the declared rule names) and its repository view with
  ``permissions.admin`` true; control: the verifier bot's token (a read collaborator) gets 403 on the rules
  (``reqAdmin``);
- be refused every write, each by its scope (403 "token does not have at least one of required scope(s)"):
  modify the protection (PATCH main with its declared value, DELETE an absent rule, POST the priorities with
  no ids), change collaborators or permissions (PUT its own and the verifier's current permission, DELETE an
  absent collaborator, DELETE an absent team), change the repository's settings (PATCH its declared value),
  add a deploy key or deploy token, a webhook (invalid bodies), push (an API file write on main, and a git
  push over smart HTTP through the repository module to main and to a work/ branch: ``PUSH_REFUSED``),
  merge (an absent pull request), create a repository (its own, or in the fixture organization);
- not escape its repository: ``GET /repos/search`` lists the fixture only; the organization, user and admin
  routes are refused (403 by scope); ``sudo`` is refused ("Only administrators allowed to sudo."); every
  repository named in AIEH_PROTECTION_AUDIT_OTHER_REPOS (comma-separated; the auditor is no collaborator of
  them) answers 404 or 403 on its rules. **Without such a repository that probe fails as not exercised**:
  naming one (for example a private repository the site administrator creates for the purpose) is part of
  this act.

The bodies are chosen so that a write Gitea wrongly accepted would change nothing (a declared value, an
absent object, an invalid body), except the git push and the API file write, which the branch rules refuse
as well. **Any write that answers 2xx, a push that succeeds, or main, the rules or the roster changing, is a
SECURITY FAILURE: the test fails naming it and stops; the remedy is to revoke the token at once
(``gitea_roles.py retire protection-audit``, an Owner-approved act) and report.** A refusal other than 403
(for example 404 or 422) fails the test without being a security failure: the scope did not refuse it.
``DELETE /api/v1/token`` is never sent: it needs no scope and would revoke the token itself.

**Phase ``qualify``** (``AIEH_PROTECTION_AUDIT_LIVE=qualify``; site administration as aieh-site-admin by
basic authentication with its harness-held password, as ``gitea_roles.py fixture`` does): the protection
check (protection_check.verify) must answer ``verified`` on the fixture as declared (its digest the
baseline); then each injected drift is detected, naming it, and restored: main's
``block_admin_merge_override`` false, main's priority 5 (Gitea then enforces ``**`` on main: precedence), an
extra rule ``aieh-qualify/*``, the verifier bot raised to admin, squash merges allowed. After each
restoration (``gitea_roles.apply_fixture`` re-applies the total declaration; the extra rule is deleted) the
check answers ``verified`` with the baseline digest. The restorations run in a ``finally`` too. These API
changes leave no audit event at Gitea 28.3.0 (finding F-B).
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import secrets
import shutil
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

CATEGORY = 'e2e'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


G = _load('aieh_gitea_host', HERE.parent / 'gitea_host.py')
R = _load('aieh_gitea_roles', HERE.parent / 'gitea_roles.py')
PC = _load('aieh_gitea_protection_check', HERE.parent / 'protection_check.py')
PHASES = ('negative', 'qualify')
PHASE = os.environ.get('AIEH_PROTECTION_AUDIT_LIVE', '')
REPORT = os.environ.get('AIEH_PROTECTION_AUDIT_REPORT')
OTHER_REPOS = [r.strip() for r in os.environ.get('AIEH_PROTECTION_AUDIT_OTHER_REPOS', '').split(',') if r.strip()]
REPOSITORY = f'{R.FIXTURE_ORG}/{R.FIXTURE_REPO}'
REPO = f'/repos/{REPOSITORY}'
MAIN = f'refs/heads/{R.DEFAULT_BRANCH}'
RESULTS: list[dict] = []
SCOPE_REFUSAL = 'token does not have at least one of required scope(s)'
_LIVE: list = []


class SecurityFailure(AssertionError):
    """The read-only token wrote, or the fixture changed under it: stop, revoke the token, report."""

    def __init__(self, detail):
        super().__init__(f'SECURITY FAILURE: {detail}. Remedy: revoke the token at once (gitea_roles.py retire '
                         'protection-audit, an Owner-approved act) and report')


def live(phase):
    """(context, None) when PHASE can run, else (None, the reason it skips)."""
    if not _LIVE:
        _LIVE.append(_probe_live())
    ctx, reason = _LIVE[0]
    if ctx is not None and PHASE != phase:
        return None, f'phase {PHASE!r} runs; this class belongs to phase {phase!r}'
    return ctx, reason


def _probe_live():
    if PHASE not in PHASES:
        return None, ('the live protection-auditor tests are opt-in, each phase an Owner act: '
                      'AIEH_PROTECTION_AUDIT_LIVE=negative or =qualify')
    if os.name != 'nt':
        return None, 'the tokens are in Windows Credential Manager'
    try:
        res = G.paths.resolve()
        port = G.read_host_record(G.layout(res))['port']
    except (G.GiteaError, G.paths.PathsError) as exc:
        return None, f'Gitea is not installed here ({exc})'
    if not G.healthy(port):
        return None, 'Gitea is not running (task gitea:up)'
    provider = G.credential_provider()
    token = R.read_token(provider, 'protection-audit')
    if token is None:
        return None, f'no Credential Manager entry {PC.ENTRY!r} (gitea_roles.py provision, an Owner act)'
    status = R.Api(port, token).call('GET', REPO)[0]
    if status != 200:
        return None, f'the fixture answers {status} to the auditor (gitea_roles.py fixture, an Owner act)'
    return SimpleNamespace(port=port, provider=provider, token=token), None


def tearDownModule():
    if REPORT and RESULTS:
        Path(REPORT).write_text(json.dumps(RESULTS, indent=1) + '\n', encoding='utf-8')


def message(payload) -> str:
    if isinstance(payload, dict):
        return R.redact(str(payload.get('message', '')))[:200]
    if isinstance(payload, list):
        return f'list of {len(payload)}'
    return R.redact(str(payload))[:200]


class Live(unittest.TestCase):
    PHASE_OF_CLASS = ''

    @classmethod
    def setUpClass(cls):
        ctx, reason = live(cls.PHASE_OF_CLASS)
        if ctx is None:
            raise unittest.SkipTest(reason)
        cls.ctx = ctx

    def call(self, action, expect, method, path, body=None, headers=None, token=None):
        api = R.Api(self.ctx.port, self.ctx.token if token is None else token)
        status, payload = api.call(method, path, body, headers)
        RESULTS.append({'action': action, 'expected': expect, 'status': status, 'message': message(payload)})
        return status, payload

    def snapshot(self):
        """What a wrongly accepted write would change: main's head, the rules, the roster, the settings."""
        branch = self.call('read main', 'allowed', 'GET', f'{REPO}/branches/{R.DEFAULT_BRANCH}')[1]
        rules = self.call('read the rules', 'allowed', 'GET', f'{REPO}/branch_protections')[1]
        roster = self.call('read the collaborators', 'allowed', 'GET', f'{REPO}/collaborators?{PC.PAGE}')[1]
        repo = self.call('read the repository', 'allowed', 'GET', REPO)[1]
        return {'main': branch['commit']['id'], 'rules': [{k: r.get(k) for k in PC.FIELDS} for r in rules],
                'roster': sorted(c['login'] for c in roster),
                'settings': {k: repo.get(k) for k in R.repository_settings()}}


class NegativeLive(Live):
    PHASE_OF_CLASS = 'negative'

    def refused(self, action, method, path, body=None, headers=None):
        """A write the token must not make: 2xx is a SECURITY FAILURE; a refusal must be its scope's 403."""
        status, payload = self.call(action, 'refused by scope (403)', method, path, body, headers)
        if 200 <= status < 300:
            raise SecurityFailure(f'{action} ({method} {path}) answered {status}')
        self.assertEqual(status, 403, f'{action}: refused with {status}, not by the scope ({message(payload)})')
        return payload


class TestIdentity(NegativeLive):
    def test_get_token_shows_its_login_and_exact_scope(self):
        status, body = self.call('GET /token', 'allowed', 'GET', '/token')
        self.assertEqual(status, 200)
        self.assertEqual(body['user']['login'], PC.AUDITOR)
        self.assertEqual(sorted(body['scopes']), PC.SCOPES)

    def test_no_password_and_no_more_as_a_password(self):
        for label, password in (('a random password', secrets.token_urlsafe(18)), ('an empty password', '')):
            basic = base64.b64encode(f'{PC.AUDITOR}:{password}'.encode()).decode()
            status = G.http_get(self.ctx.port, '/api/v1/repos/search', headers={'Authorization': 'Basic ' + basic})[0]
            RESULTS.append({'action': f'basic authentication with {label}', 'expected': 401, 'status': status})
            self.assertEqual(status, 401)
        basic = base64.b64encode(f'{PC.AUDITOR}:{self.ctx.token}'.encode()).decode()
        for method, path, body in (('GET', '/user', None),
                                   ('POST', f'/users/{PC.AUDITOR}/tokens', {'name': 'aieh-probe', 'scopes': ['all']})):
            status, payload = R.Api(self.ctx.port).call(method, path, body, {'Authorization': 'Basic ' + basic})
            RESULTS.append({'action': f'{method} {path} with the token as a basic-authentication password',
                            'expected': 'refused', 'status': status, 'message': message(payload)})
            if status == 201 and isinstance(payload, dict) and payload.get('sha1'):
                R.revoke_current(self.ctx.port, payload.pop('sha1'))
            if 200 <= status < 300:
                raise SecurityFailure(f'{method} {path} with the token as a password answered {status}')
            self.assertIn(status, (401, 403))
        del basic


class TestReads(NegativeLive):
    def test_the_auditor_reads_the_rules_and_is_a_repository_administrator(self):
        status, rules = self.call('read the rules', 'allowed', 'GET', f'{REPO}/branch_protections')
        self.assertEqual(status, 200)
        self.assertEqual(sorted(r['rule_name'] for r in rules), sorted(r['rule_name'] for r in R.protection_rules()))
        status, repo = self.call('read the repository', 'allowed', 'GET', REPO)
        self.assertEqual((status, repo['permissions']['admin']), (200, True))

    def test_a_read_collaborator_cannot_read_the_rules(self):
        verifier = R.read_token(self.ctx.provider, 'verifier')
        if verifier is None:
            self.fail('not exercised: no entry for the verifier bot (the control needs a read collaborator)')
        status, payload = self.call('the verifier bot reads the rules (control)', 'refused (reqAdmin)', 'GET',
                                    f'{REPO}/branch_protections', token=verifier)
        self.assertEqual(status, 403, message(payload))


class TestWrites(NegativeLive):
    def test_every_write_is_refused_by_the_scope(self):
        before = self.snapshot()
        main = next(r for r in R.protection_rules() if r['rule_name'] == R.DEFAULT_BRANCH)
        absent = f'aieh-probe-absent-{secrets.token_hex(3)}'
        writes = [
            ('modify the protection: PATCH main (its declared value)', 'PATCH', f'{REPO}/branch_protections/main',
             {'required_approvals': main['required_approvals']}),
            ('modify the protection: DELETE an absent rule', 'DELETE', f'{REPO}/branch_protections/{absent}', None),
            ('modify the protection: POST the priorities with no ids', 'POST', f'{REPO}/branch_protections/priority',
             {'ids': []}),
            ('change permissions: PUT its own (current) permission', 'PUT', f'{REPO}/collaborators/{PC.AUDITOR}',
             {'permission': 'admin'}),
            ('change permissions: PUT the verifier bot\'s (current) permission', 'PUT',
             f'{REPO}/collaborators/{R.ROLES["verifier"]["user"]}', {'permission': 'read'}),
            ('change collaborators: DELETE an absent collaborator', 'DELETE', f'{REPO}/collaborators/{absent}', None),
            ('change teams: DELETE an absent team', 'DELETE', f'{REPO}/teams/{absent}', None),
            ('change the settings: PATCH the repository (its declared value)', 'PATCH', REPO,
             {'allow_merge_commits': R.repository_settings()['allow_merge_commits']}),
            ('add a deploy key (invalid body)', 'POST', f'{REPO}/keys', {'title': '', 'key': ''}),
            ('add a deploy token (invalid body)', 'POST', f'{REPO}/keys/tokens', {'title': ''}),
            ('add a webhook (invalid body)', 'POST', f'{REPO}/hooks', {'type': '', 'config': {}}),
            ('push through the API: a file on main', 'POST', f'{REPO}/contents/aieh-audit-probe.txt',
             {'content': base64.b64encode(b'probe\n').decode(), 'message': 'probe', 'branch': R.DEFAULT_BRANCH}),
            ('merge: an absent pull request', 'POST', f'{REPO}/pulls/999999/merge', {'Do': 'merge'}),
            ('create a repository of its own', 'POST', '/user/repos', {'name': absent, 'private': True}),
            ('create a repository in the fixture organization', 'POST', f'/orgs/{R.FIXTURE_ORG}/repos',
             {'name': absent, 'private': True}),
        ]
        for action, method, path, body in writes:
            with self.subTest(action=action):
                payload = self.refused(action, method, path, body)
                self.assertIn(SCOPE_REFUSAL, message(payload))
        after = self.snapshot()
        if after != before:
            raise SecurityFailure(f'the fixture changed during the write probes: {before} -> {after}')

    def test_git_push_through_the_repository_module_is_refused(self):
        RA = _load('repository_access', HERE.parents[1] / 'repository' / 'repository_access.py')
        try:
            RA.dulwich_modules()
        except RA.CannotRun as exc:
            self.fail(f'not exercised: {exc.code} (run under the tools interpreter)')
        before = self.snapshot()
        url = f'http://{G.LOOPBACK}:{self.ctx.port}/{R.FIXTURE_ORG}/{R.FIXTURE_REPO}.git'
        credential = RA.Credential(PC.AUDITOR, self.ctx.token)
        tmp = Path(tempfile.mkdtemp(prefix='aieh-protection-audit-live-'))
        self.addCleanup(shutil.rmtree, tmp, onexc=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
        refs = RA.clone(url, tmp / 'clone.git', credential)
        head = refs[MAIN]
        from dulwich import objects
        with RA.open_repository(tmp / 'clone.git', config='repository', work_tree=False, ceilings=[tmp]) as repo:
            store = repo._dul.object_store
            tree = objects.Tree()
            for item in store[store[head.encode()].tree].iteritems():
                tree.add(item.path, item.mode, item.sha)
            blob = objects.Blob.from_string(b'protection auditor probe\n')
            tree.add(b'aieh-audit-probe.txt', 0o100644, blob.id)
            commit = objects.Commit()
            commit.tree, commit.parents = tree.id, [head.encode()]
            commit.author = commit.committer = f'{PC.AUDITOR} <{PC.AUDITOR}@{G.EMAIL_DOMAIN}>'.encode()
            commit.author_time = commit.commit_time = int(time.time())
            commit.author_timezone = commit.commit_timezone = 0
            commit.message = b'protection auditor probe\n'
            for obj in (blob, tree, commit):
                store.add_object(obj)
            tip = commit.id.decode()
            for label, refspec in (('push to main', f'{tip}:{MAIN}'),
                                   ('push a proposal branch', f'{tip}:refs/heads/work/authz-protection-audit')):
                with self.subTest(push=label):
                    try:
                        repo.push(url, refspec, credential)
                    except RA.RepositoryError as exc:
                        RESULTS.append({'action': f'git {label} (repository module)', 'expected': 'PUSH_REFUSED',
                                        'status': exc.code, 'message': R.redact(str(exc))[-200:]})
                        self.assertEqual(exc.code, 'PUSH_REFUSED')
                    else:
                        raise SecurityFailure(f'git {label} with the read:repository token succeeded')
        if self.snapshot() != before:
            raise SecurityFailure('the fixture changed during the push probes')


class TestNoEscape(NegativeLive):
    def test_it_sees_the_fixture_only(self):
        status, found = self.call('GET /repos/search', 'the fixture only', 'GET', '/repos/search?limit=50')
        self.assertEqual(status, 200)
        self.assertEqual([r['full_name'] for r in found['data']], [REPOSITORY])

    def test_user_organization_and_admin_routes_and_sudo(self):
        for action, path, headers in (('GET /user', '/user', None), ('GET /admin/users', '/admin/users', None),
                                      ('GET the organization\'s teams', f'/orgs/{R.FIXTURE_ORG}/teams', None),
                                      ('GET the organization\'s members', f'/orgs/{R.FIXTURE_ORG}/members', None),
                                      ('GET /user/orgs', '/user/orgs', None)):
            with self.subTest(action=action):
                self.refused(action, 'GET', path, headers=headers)
        for target in (G.OWNER, G.SITE_ADMIN):
            with self.subTest(sudo=target):
                status, payload = self.call(f'sudo {target}', 'refused', 'GET', '/token', headers={'Sudo': target})
                self.assertEqual((status, message(payload)), (403, 'Only administrators allowed to sudo.'))

    def test_another_repository_s_rules(self):
        if not OTHER_REPOS:
            self.fail('not exercised: name a repository the auditor is no collaborator of in '
                      'AIEH_PROTECTION_AUDIT_OTHER_REPOS (part of this act)')
        for other in OTHER_REPOS:
            with self.subTest(repository=other):
                path = f'/repos/{urllib.parse.quote(other)}/branch_protections'
                status, payload = self.call(f'read the rules of {other}', 'refused', 'GET', path)
                if 200 <= status < 300:
                    raise SecurityFailure(f'the auditor read the rules of {other}')
                self.assertIn(status, (403, 404), message(payload))


class QualifyLive(Live):
    """The verifier qualification: drift injected as the site administrator is detected, then restored."""
    PHASE_OF_CLASS = 'qualify'

    def verify(self):
        return PC.verify(self.ctx.provider, self.ctx.port, REPOSITORY, R.DEFAULT_BRANCH)

    def test_injected_drift_is_detected_and_restored(self):
        baseline = self.verify()
        RESULTS.append({'action': 'baseline', 'status': baseline.status, 'code': baseline.code,
                        'digest': baseline.digest})
        self.assertEqual(baseline.status, 'verified', baseline.detail)
        admin = R.admin_api(self.ctx.provider, self.ctx.port)
        repo = REPO
        probe_rule = 'aieh-qualify/*'

        def restore():
            names = {r.get('rule_name') for r in admin.call('GET', f'{repo}/branch_protections')[1] or []}
            if probe_rule in names:
                admin.call('DELETE', f'{repo}/branch_protections/{urllib.parse.quote(probe_rule, safe="")}')
            R.apply_fixture(admin)

        injections = [
            ('main.block_admin_merge_override false', 'main.block_admin_merge_override is False',
             lambda: admin.call('PATCH', f'{repo}/branch_protections/main', {'block_admin_merge_override': False})),
            ('main lowered below the catch-all (precedence)', "Gitea enforces the rule '**' on main",
             lambda: admin.call('PATCH', f'{repo}/branch_protections/main', {'priority': 5})),
            ('an extra rule', f"rule '{probe_rule}'",
             lambda: admin.call('POST', f'{repo}/branch_protections', R._total_rule(probe_rule, 9))),
            ('the verifier bot raised to admin', f'collaborator {R.ROLES["verifier"]["user"]}: admin',
             lambda: admin.call('PUT', f'{repo}/collaborators/{R.ROLES["verifier"]["user"]}', {'permission': 'admin'})),
            ('squash merges allowed', "the repository's allow_squash_merge is True",
             lambda: admin.call('PATCH', repo, {'allow_squash_merge': True})),
        ]
        try:
            for label, expected, inject in injections:
                with self.subTest(injection=label):
                    status = inject()[0]
                    drift = self.verify()
                    restore()
                    restored = self.verify()
                    RESULTS.append({'action': f'inject: {label}', 'status': status, 'drift': drift.status,
                                    'problems': list(drift.problems), 'restored': restored.status,
                                    'digest_equal': restored.digest == baseline.digest})
                    self.assertIn(status, (200, 201, 204))
                    self.assertEqual(drift.status, 'drift', drift.detail)
                    self.assertTrue(any(expected in p for p in drift.problems), drift.problems)
                    self.assertEqual((restored.status, restored.digest), ('verified', baseline.digest))
        finally:
            restore()
        final = self.verify()
        self.assertEqual((final.status, final.digest), ('verified', baseline.digest))


if __name__ == '__main__':
    unittest.main()
