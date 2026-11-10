"""Tests of the role-bot provisioning, fixture and rotation (plan leaf S-01.2.2), offline.

A fake Gitea CLI and a fake Gitea API stand in for the instance and an in-memory credential provider
for Windows Credential Manager, so nothing here touches the real Credential Manager, the managed root or the
network. The live checks are in test_authorization_live.py. The last class checks the guest profile's
declaration: no host share, and no path of the managed root or of a credential store, reaches a guest.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import re
import sys
import unittest
import urllib.parse
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
FakeReceipts = _load('aieh_gitea_receipt_fakes', HERE / 'receipt_fakes.py').FakeReceipts
PORT = 13300


class FakeCli:
    """The Gitea CLI as gitea_roles.Cli uses it: user list (with Type), Bot create, token minting."""

    def __init__(self, users=None, fail_mint=False):
        self.users_ = dict(users or {G.SITE_ADMIN: {'admin': True, 'type': 'User'},
                                     G.OWNER: {'admin': False, 'type': 'User'}})
        self.calls, self.minted, self.fail_mint = [], [], fail_mint
        self.gitea = None

    def __call__(self, *args):
        self.calls.append(list(args))
        if args[:3] == ('admin', 'user', 'create'):
            user = args[args.index('--username') + 1]
            self.users_[user] = {'admin': '--admin' in args,
                                 'type': args[args.index('--user-type') + 1] if '--user-type' in args else 'User'}
            return SimpleNamespace(returncode=0, stdout=f"New user '{user}' has been successfully created!\n".encode(),
                                   stderr=b'')
        if args[:3] == ('admin', 'user', 'generate-access-token'):
            user, scopes = args[args.index('--username') + 1], args[args.index('--scopes') + 1].split(',')
            token = hashlib.sha1(f'{user}{len(self.minted)}'.encode()).hexdigest()
            if self.fail_mint:
                return SimpleNamespace(returncode=1, stdout=token.encode(), stderr=f'bad scope {token}'.encode())
            self.minted.append(token)
            if self.gitea is not None:
                self.gitea.tokens[token] = {'user': user, 'scopes': scopes,
                                            'name': args[args.index('--token-name') + 1]}
            return SimpleNamespace(returncode=0, stdout=token.encode() + b'\n', stderr=b'')
        raise AssertionError(f'unexpected CLI call {args}')

    def users(self):
        return {u: dict(v) for u, v in self.users_.items()}

    create_bot = R.Cli.create_bot
    mint = R.Cli.mint


ADMIN_PASSWORD = 'admin-final-password-for-the-fake'


class FakeGitea:
    """A minimal Gitea API: token authentication, DELETE /token, the site administrator by basic
    authentication, organizations, repositories, collaborators and branch protection."""

    def __init__(self, fail_path=None, admin_password=ADMIN_PASSWORD):
        self.tokens, self.orgs, self.repos, self.collab, self.rules = {}, set(), set(), {}, {}
        self.fail_path, self.requests, self.admin_password = fail_path, [], admin_password

    def __call__(self, port, path, method='GET', body=None, headers=None, timeout=5.0):
        assert port == PORT
        headers = headers or {}
        auth = headers.get('Authorization', '')
        self.requests.append((method, path, auth[:6]))
        if auth.startswith('Basic '):
            user, _, password = base64.b64decode(auth[6:]).decode().partition(':')
            if (user, password) != (G.SITE_ADMIN, self.admin_password):
                return self.reply(401, {'message': 'unauthorized'})
            entry, token = {'user': G.SITE_ADMIN}, None
        else:
            token = auth.removeprefix('token ')
            entry = self.tokens.get(token)
            if entry is None:
                return self.reply(401, {'message': 'token is required'})
        if self.fail_path and path.endswith(self.fail_path):
            return self.reply(500, {'message': 'boom'})
        data = json.loads(body) if body else None
        route = path.removeprefix('/api/v1')
        if route == '/user' and token is None:
            return self.reply(200, {'login': G.SITE_ADMIN, 'is_admin': True})
        if route == f'/users/{G.SITE_ADMIN}/tokens' and token is None:
            return self.reply(200, [{'id': 1, 'name': t['name']} for t in self.tokens.values()
                                    if t['user'] == G.SITE_ADMIN])
        if route == '/token' and token is not None:
            if method == 'DELETE':
                del self.tokens[token]
                return self.reply(204, None)
            return self.reply(200, {'name': entry['name'], 'scopes': entry['scopes']})
        repo = f'/repos/{R.FIXTURE_ORG}/{R.FIXTURE_REPO}'
        if route == f'/orgs/{R.FIXTURE_ORG}':
            return self.reply(200 if R.FIXTURE_ORG in self.orgs else 404, {})
        if route == '/orgs' and method == 'POST':
            self.orgs.add(data['username'])
            return self.reply(201, {})
        if route == f'/orgs/{R.FIXTURE_ORG}/repos' and method == 'POST':
            self.repos.add(data['name'])
            return self.reply(201, {})
        if route == repo:
            if R.FIXTURE_REPO not in self.repos:
                return self.reply(404, {})
            return self.reply(200, {'full_name': f'{R.FIXTURE_ORG}/{R.FIXTURE_REPO}', 'private': True,
                                    'default_branch': R.DEFAULT_BRANCH})
        if route.startswith(f'{repo}/collaborators/'):
            user = route.split('/')[5]
            if method == 'PUT':
                self.collab[user] = data['permission']
                return self.reply(204, None)
            return self.reply(200, {'permission': self.collab.get(user)})
        if route == f'{repo}/branch_protections':
            if method == 'POST':
                self.rules[data['rule_name']] = data
                return self.reply(201, data)
            return self.reply(200, list(self.rules.values()))
        if route.startswith(f'{repo}/branch_protections/') and method == 'PATCH':
            name = urllib.parse.unquote(route.split('/branch_protections/', 1)[1])
            self.rules[name].update(data)
            return self.reply(200, self.rules[name])
        return self.reply(404, {'message': 'not found'})

    @staticmethod
    def reply(status, payload):
        return status, {}, b'' if payload is None else json.dumps(payload).encode()


class MemoryProvider(G.CredentialProvider):
    def __init__(self, entries=None):
        self.entries, self.reads = dict(entries or {}), []

    def get(self, name):
        self.reads.append(name)
        return self.entries.get(name)

    def set(self, name, user, secret, comment=''):
        assert isinstance(secret, str)
        self.entries[name] = (user, secret)

    def delete(self, name):
        return self.entries.pop(name, None) is not None


def ctx(cli, provider):
    return None, None, PORT, provider, cli


class Base(unittest.TestCase):
    def setUp(self):
        self.gitea, self.cli = FakeGitea(), FakeCli()
        self.store = MemoryProvider({G.FINAL_TARGETS[G.SITE_ADMIN]: (G.SITE_ADMIN, ADMIN_PASSWORD)})
        self.cli.gitea = self.gitea
        self.receipts = FakeReceipts()

    def provision(self, **kwargs):
        return R.provision(http=self.gitea, ctx=ctx(self.cli, self.store), **kwargs)

    def bot_entries(self):
        return {k: v for k, v in self.store.entries.items() if k.startswith(R.TARGET_PREFIX)}

    def assert_no_token(self, text):
        for token in self.cli.minted:
            self.assertNotIn(token, text)
        self.assertIsNone(re.search(r'[0-9a-f]{40}', text))
        self.assertNotIn(ADMIN_PASSWORD, text)


class TestProvision(Base):
    def test_bots_tokens_and_entries_without_exposure(self):
        report = self.provision()
        self.assertEqual(sorted(report['created_accounts']), sorted(s['user'] for s in R.ROLES.values()))
        for argv in (c for c in self.cli.calls if c[:3] == ['admin', 'user', 'create']):
            self.assertEqual(argv[argv.index('--user-type') + 1], 'Bot')
            self.assertIn('--restricted', argv)
            for flag in ('--admin', '--password', '--random-password', '--access-token'):
                self.assertNotIn(flag, argv)
        mints = [c for c in self.cli.calls if c[:3] == ['admin', 'user', 'generate-access-token']]
        self.assertEqual(len(mints), len(R.ROLES))
        for role, spec in R.ROLES.items():
            argv = next(c for c in mints if c[c.index('--username') + 1] == spec['user'])
            self.assertIn('--raw', argv)
            self.assertEqual(argv[argv.index('--scopes') + 1], ','.join(spec['scopes']))
            user, token = self.store.get(R.target(role))
            self.assertEqual(user, spec['user'])
            self.assertIn(token, self.cli.minted)
            self.assertEqual(report['tokens'][role]['fingerprint'], R.fingerprint(token))
            self.assertEqual(report['tokens'][role]['check']['scopes'], sorted(spec['scopes']))
        self.assert_no_token(json.dumps(report))
        for token in self.cli.minted:
            for argv in self.cli.calls:
                self.assertNotIn(token, ' '.join(argv))
        self.assertFalse(any(name in self.store.reads for name in G.FINAL_TARGETS.values()))

    def test_existing_entries_are_kept(self):
        self.provision()
        before, calls = dict(self.store.entries), len(self.cli.calls)
        report = self.provision()
        self.assertEqual(self.store.entries, before)
        self.assertFalse(any(t['minted'] for t in report['tokens'].values()))
        self.assertFalse(any(c[:3] == ['admin', 'user', 'generate-access-token'] for c in self.cli.calls[calls:]))

    def test_an_existing_non_bot_account_is_refused(self):
        for state in ({'admin': True, 'type': 'Bot'}, {'admin': False, 'type': 'User'}):
            self.cli.users_[R.ROLES['builder']['user']] = state
            with self.subTest(state=state), self.assertRaises(G.GiteaError) as caught:
                self.provision()
            self.assertEqual(caught.exception.code, 'ACCOUNT_NOT_A_BOT')
            self.assertEqual(self.bot_entries(), {})

    def test_mint_failure_withholds_the_output(self):
        self.cli.fail_mint = True
        with self.assertRaises(G.GiteaError) as caught:
            self.provision()
        self.assertEqual(caught.exception.code, 'TOKEN_MINT_FAILED')
        self.assertIsNone(re.search(r'[0-9a-f]{40}', str(caught.exception)))
        self.assertEqual(self.bot_entries(), {})


class TestFixture(Base):
    def setUp(self):
        super().setUp()
        self.provision()
        self.minted_before = len(self.cli.minted)

    def run_fixture(self, **kwargs):
        return R.fixture(http=self.gitea, ctx=ctx(self.cli, self.store), **kwargs)

    def test_applied_as_the_administrator_with_basic_auth_and_no_token(self):
        report = self.run_fixture()
        self.assertEqual(len(self.cli.minted), self.minted_before)  # no administration token
        self.assertEqual(report['admin_tokens_after'], [])
        self.assertEqual(self.gitea.collab, R.collaborators())
        self.assertEqual(set(self.gitea.rules), {r['rule_name'] for r in R.protection_rules()})
        self.assertEqual(report['fixture']['collaborator_permissions'], R.collaborators())
        self.assert_no_token(json.dumps(report))
        self.assertFalse(any('/admin/' in path for _m, path, _a in self.gitea.requests))
        admin_calls = {a for _m, _p, a in self.gitea.requests if _p.startswith('/api/v1/orgs') or 'branch_' in _p}
        self.assertEqual(admin_calls, {'Basic '})

    def test_rerun_updates_instead_of_duplicating(self):
        self.run_fixture()
        report = self.run_fixture()
        self.assertTrue(any(a['method'] == 'PATCH' for a in report['actions']))
        self.assertTrue(any(a['path'].endswith('/branch_protections/work%2F%2A') for a in report['actions']))
        self.assertFalse(any(a['path'] == '/orgs' for a in report['actions']))

    def test_unfinalized_or_rejected_administrator_refused(self):
        del self.store.entries[G.FINAL_TARGETS[G.SITE_ADMIN]]
        with self.assertRaises(G.GiteaError) as caught:
            self.run_fixture()
        self.assertEqual(caught.exception.code, 'ADMIN_NOT_FINALIZED')
        self.store.entries[G.FINAL_TARGETS[G.SITE_ADMIN]] = (G.SITE_ADMIN, 'wrong')
        with self.assertRaises(G.GiteaError) as caught:
            self.run_fixture()
        self.assertEqual(caught.exception.code, 'ADMIN_UNUSABLE')
        self.assertNotIn('wrong', str(caught.exception))
        self.assertEqual([p for _m, p, _a in self.gitea.requests if 'collaborators' in p], [])

    def test_a_failure_midway_reports_without_secrets(self):
        self.gitea.fail_path = f'/collaborators/{G.OWNER}'
        with self.assertRaises(G.GiteaError) as caught:
            self.run_fixture()
        self.assertEqual(caught.exception.code, 'API_UNEXPECTED')
        self.assert_no_token(str(caught.exception))

    def test_missing_bots_or_owner_refused(self):
        del self.cli.users_[R.ROLES['reviewer']['user']]
        with self.assertRaises(G.GiteaError) as caught:
            self.run_fixture()
        self.assertEqual(caught.exception.code, 'BOTS_MISSING')


class TestRotate(Base):
    def test_revoke_fail_closed_reissue(self):
        self.provision()
        old = self.store.get(R.target('builder'))[1]
        report = R.rotate('builder', http=self.gitea, ctx=ctx(self.cli, self.store), receipts=self.receipts)
        self.assertEqual(report['revocation'], {'delete_status': 204, 'next_call_status': 401, 'revoked': True})
        self.assertEqual(report['old_on_repository_read'], 401)
        self.assertNotIn(old, self.gitea.tokens)
        new = self.store.get(R.target('builder'))[1]
        self.assertNotEqual(new, old)
        self.assertEqual(report['new_fingerprint'], R.fingerprint(new))
        self.assertEqual(report['new_check']['status'], 200)
        self.assert_no_token(json.dumps(report))

    def test_refusals(self):
        with self.assertRaises(G.GiteaError) as caught:
            R.rotate('owner', http=self.gitea, ctx=ctx(self.cli, self.store), receipts=self.receipts)
        self.assertEqual(caught.exception.code, 'ROLE_UNKNOWN')
        with self.assertRaises(G.GiteaError) as caught:
            R.rotate('builder', http=self.gitea, ctx=ctx(self.cli, self.store), receipts=self.receipts)
        self.assertEqual(caught.exception.code, 'ENTRY_MISSING')

    def test_entry_naming_another_account_refused(self):
        self.store.entries[R.target('builder')] = ('aieh-owner', 'x' * 40)
        with self.assertRaises(G.GiteaError) as caught:
            R.read_token(self.store, 'builder')
        self.assertEqual(caught.exception.code, 'ENTRY_MISMATCH')

    def test_the_human_entries_are_not_reachable_as_a_role(self):
        for name in ('site-admin', 'owner', G.SITE_ADMIN, G.OWNER):
            with self.assertRaises(G.GiteaError) as caught:
                R.read_token(self.store, name)
            self.assertEqual(caught.exception.code, 'ROLE_UNKNOWN')
        self.assertFalse(any(R.target(role) in G.FINAL_TARGETS.values() for role in R.ROLES))


class TestRetire(Base):
    """The contract's retire for a role credential (plan leaf F-06.2)."""

    def retire(self, role='builder'):
        return R.retire(role, http=self.gitea, ctx=ctx(self.cli, self.store), receipts=self.receipts)

    def test_revoke_prove_fail_closed_then_delete_the_entry(self):
        self.provision()
        old = self.store.get(R.target('builder'))[1]
        report = self.retire()
        self.assertEqual(report['revocation'], {'delete_status': 204, 'next_call_status': 401, 'revoked': True})
        self.assertEqual((report['state'], report['entry_deleted'], report['fingerprint']),
                         ('retired', True, R.fingerprint(old)))
        self.assertNotIn(old, self.gitea.tokens)
        self.assertNotIn(R.target('builder'), self.store.entries)
        self.assertIn(R.target('planner'), self.store.entries)  # one credential only
        self.assert_no_token(json.dumps(report))

    def test_a_rerun_resumes(self):
        self.provision()
        token = self.store.get(R.target('builder'))[1]
        del self.gitea.tokens[token]  # an earlier run revoked it and stopped before deleting the entry
        report = self.retire()
        self.assertEqual((report['before']['status'], report['state']), (401, 'retired'))
        self.assertIn('already refused', report['revocation'])
        self.assertNotIn(R.target('builder'), self.store.entries)
        self.assertEqual(self.retire()['state'], 'retired (no entry: nothing to revoke)')

    def test_a_failed_revocation_keeps_the_entry(self):
        self.provision()
        self.gitea.fail_path = '/token'
        with self.assertRaises(G.GiteaError) as caught:
            self.retire()
        self.assertEqual(caught.exception.code, 'REVOCATION_FAILED')
        self.assertIn(R.target('builder'), self.store.entries)
        self.assert_no_token(str(caught.exception))

    def test_refusals(self):
        with self.assertRaises(G.GiteaError) as caught:
            self.retire('site-admin')
        self.assertEqual(caught.exception.code, 'ROLE_UNKNOWN')


class TestActReceipts(Base):
    """Every rotate or retire act writes an integration-store receipt, fingerprints only, and reads it back
    (plan leaf F-06.3; decision 0007 point 5), here against the in-memory stand-in of the store."""

    def setUp(self):
        super().setUp()
        self.provision()

    def act(self, verb, role='builder', receipts=None):
        return getattr(R, verb)(role, http=self.gitea, ctx=ctx(self.cli, self.store),
                                receipts=receipts or self.receipts)

    def only_receipt(self):
        (key, states), = self.receipts.states().items()
        return key, states, json.loads(self.receipts.get(key).intent_json), self.receipts.events(key)

    def test_rotate_writes_its_receipt_and_reads_it_back(self):
        old = self.store.get(R.target('builder'))[1]
        report = self.act('rotate')
        new = self.store.get(R.target('builder'))[1]
        key, states, intent, events = self.only_receipt()
        self.assertEqual(states, ['reserved', 'dispatched', 'confirmed'])
        self.assertEqual(report['receipt'], {'operation_key': key, 'format': 'aieh-credential-act/1',
                                             'state': 'confirmed', 'events': states, 'read_back': True})
        self.assertTrue(key.startswith('credential/gitea/rotate/builder/'))
        self.assertEqual((intent['verb'], intent['role'], intent['user'], intent['entry'], intent['trigger']),
                         ('rotate', 'builder', R.ROLES['builder']['user'], R.target('builder'), 'owner direction'))
        self.assertEqual(intent['fingerprint_before'], R.fingerprint(old))
        self.assertEqual(intent['affected_attempts'], [])
        self.assertIn('revoker', intent)
        self.assertEqual(json.loads(events[-1].detail_json)['fingerprint_after'], R.fingerprint(new))
        for secret in (old, new, ADMIN_PASSWORD):
            self.assertNotIn(secret, self.receipts.text())
        self.assertIsNone(re.search(r'[0-9a-f]{40}', self.receipts.text()))

    def test_retire_and_its_resumed_runs_each_write_a_receipt(self):
        old = self.store.get(R.target('builder'))[1]
        self.act('retire')
        self.act('retire')  # resumed: nothing left to revoke
        receipts = list(self.receipts.states().values())
        self.assertEqual(receipts, [['reserved', 'dispatched', 'confirmed']] * 2)
        details = [json.loads(self.receipts.events(k)[-1].detail_json) for k in self.receipts.states()]
        self.assertEqual([d['state'] for d in details], ['retired', 'retired (no entry: nothing to revoke)'])
        intents = [json.loads(self.receipts.get(k).intent_json) for k in self.receipts.states()]
        self.assertEqual([i['fingerprint_before'] for i in intents], [R.fingerprint(old), None])
        self.assertNotIn(old, self.receipts.text())

    def test_a_failed_revocation_is_recorded_failed(self):
        self.gitea.fail_path = '/token'
        for verb in ('rotate', 'retire'):
            with self.subTest(verb=verb), self.assertRaises(G.GiteaError) as caught:
                self.act(verb)
            self.assertEqual(caught.exception.code, 'REVOCATION_FAILED')
        self.assertEqual(list(self.receipts.states().values()), [['reserved', 'dispatched', 'failed']] * 2)
        for key in self.receipts.states():
            self.assertEqual(json.loads(self.receipts.events(key)[-1].detail_json), {'code': 'REVOCATION_FAILED'})

    def test_a_mint_failure_after_the_revocation_is_recorded_failed(self):
        self.cli.fail_mint = True
        with self.assertRaises(G.GiteaError) as caught:
            self.act('rotate')
        self.assertEqual(caught.exception.code, 'TOKEN_MINT_FAILED')
        self.assertEqual(list(self.receipts.states().values()), [['reserved', 'dispatched', 'failed']])

    def test_an_uncertain_outcome_is_recorded_unknown(self):
        def lost(port, path, method='GET', **kwargs):  # the connection drops on the revocation itself
            if method == 'DELETE':
                raise ConnectionResetError('the connection was reset')
            return self.gitea(port, path, method=method, **kwargs)
        with self.assertRaises(ConnectionResetError):
            R.rotate('builder', http=lost, ctx=ctx(self.cli, self.store), receipts=self.receipts)
        (key, states), = self.receipts.states().items()
        self.assertEqual(states, ['reserved', 'dispatched', 'unknown'])
        self.assertEqual(json.loads(self.receipts.events(key)[-1].detail_json), {'code': 'ConnectionResetError'})

    def test_no_receipt_no_act(self):
        before, requests = dict(self.store.entries), len(self.gitea.requests)
        for verb in ('rotate', 'retire'):
            with self.subTest(verb=verb), self.assertRaises(OSError):
                self.act(verb, receipts=FakeReceipts(fail_reserve=True))
        self.assertEqual(self.store.entries, before)
        self.assertEqual(len(self.gitea.requests), requests)  # nothing was sent to Gitea

    def test_a_receipt_not_read_back_as_written_fails_the_act(self):
        for verb in ('rotate', 'retire'):
            with self.subTest(verb=verb), self.assertRaises(G.GiteaError) as caught:
                self.act(verb, role='planner' if verb == 'rotate' else 'reviewer',
                         receipts=FakeReceipts(corrupt_detail=True))
            self.assertEqual((caught.exception.code, caught.exception.refusal), ('CREDENTIAL_RECEIPT_UNREAD', False))

    def test_a_fixture_context_never_reaches_the_managed_store(self):
        with mock.patch.object(G, 'credential_receipts', side_effect=AssertionError('the managed store')):
            for verb in ('rotate', 'retire'):
                with self.subTest(verb=verb), self.assertRaises(ValueError):
                    getattr(R, verb)('builder', http=self.gitea, ctx=ctx(self.cli, self.store))
        self.assertIn(R.target('builder'), self.store.entries)


class TestPolicy(unittest.TestCase):
    category = 'contract'

    POLICY = json.loads((REPO / 'policy' / 'role-tokens.json').read_text(encoding='utf-8'))

    def test_roles_match_the_matrix_credentials(self):
        held = {c for r in self.POLICY['roles'] for c in r['grants']['credentials']}
        for role, spec in R.ROLES.items():
            self.assertIn(spec['credential'], held, role)
        self.assertEqual(R.ROLES['verifier']['scopes'], ('read:repository',))

    def test_no_role_scope_reaches_users_admin_or_organizations(self):
        for role, spec in R.ROLES.items():
            for scope in spec['scopes']:
                self.assertRegex(scope, r'^(read|write):repository$', role)

    def test_protection_rules(self):
        rules = {r['rule_name']: r for r in R.protection_rules()}
        main = rules[R.DEFAULT_BRANCH]
        self.assertEqual((main['enable_push'], main['enable_force_push']), (False, False))
        self.assertEqual(main['merge_whitelist_usernames'], [G.OWNER])
        self.assertTrue(main['enable_merge_whitelist'] and main['block_admin_merge_override'])
        self.assertEqual(main['approvals_whitelist_username'], [R.ROLES['reviewer']['user']])
        work = rules[R.PROPOSAL_PATTERN]
        self.assertEqual(sorted(work['push_whitelist_usernames']),
                         sorted(R.ROLES[r]['user'] for r in ('planner', 'builder')))
        self.assertFalse(work['enable_force_push'])
        self.assertFalse(rules['**']['enable_push'])
        for rule in rules.values():
            self.assertEqual(rule['merge_whitelist_usernames'], [G.OWNER])
        self.assertEqual(R.collaborators()[R.ROLES['reviewer']['user']], 'read')
        self.assertEqual(R.collaborators()[R.ROLES['verifier']['user']], 'read')

    # The JSON names of Gitea 28.3.0's BranchProtection (modules/structs/repo_branch.go), in its order,
    # without branch_name (deprecated alias), created_at and updated_at.
    GITEA_28_3_0_FIELDS = (
        'rule_name', 'priority', 'enable_push', 'enable_push_whitelist', 'push_whitelist_usernames',
        'push_whitelist_teams', 'push_whitelist_deploy_keys', 'enable_force_push', 'enable_force_push_allowlist',
        'force_push_allowlist_usernames', 'force_push_allowlist_teams', 'force_push_allowlist_deploy_keys',
        'enable_merge_whitelist', 'merge_whitelist_usernames', 'merge_whitelist_teams', 'enable_bypass_allowlist',
        'bypass_allowlist_usernames', 'bypass_allowlist_teams', 'enable_status_check', 'status_check_contexts',
        'required_approvals', 'enable_approvals_whitelist', 'approvals_whitelist_username',
        'approvals_whitelist_teams', 'block_on_rejected_reviews', 'block_on_official_review_requests',
        'block_on_codeowner_reviews', 'block_on_outdated_branch', 'dismiss_stale_approvals', 'ignore_stale_approvals',
        'require_signed_commits', 'protected_file_patterns', 'unprotected_file_patterns',
        'block_admin_merge_override')

    def test_the_protection_declaration_is_total(self):
        """Every rule names every field (finding F-C of the P-04.2 protection-check recommendation), so a
        PATCH re-applying the fixture resets a drifted field; the values are pinned field by field."""
        self.assertEqual(len(self.GITEA_28_3_0_FIELDS), 34)
        self.assertEqual(R.PROTECTION_FIELDS, self.GITEA_28_3_0_FIELDS)
        zero = {f: False for f in self.GITEA_28_3_0_FIELDS}
        zero.update({f: [] for f in ('push_whitelist_usernames', 'push_whitelist_teams',
                                     'force_push_allowlist_usernames', 'force_push_allowlist_teams',
                                     'merge_whitelist_usernames', 'merge_whitelist_teams', 'bypass_allowlist_usernames',
                                     'bypass_allowlist_teams', 'status_check_contexts', 'approvals_whitelist_username',
                                     'approvals_whitelist_teams')})
        zero.update(protected_file_patterns='', unprotected_file_patterns='', required_approvals=0)
        owner_merges = {'enable_merge_whitelist': True, 'merge_whitelist_usernames': [G.OWNER]}
        expected = [
            {**zero, 'rule_name': R.DEFAULT_BRANCH, 'priority': 1, **owner_merges, 'required_approvals': 1,
             'enable_approvals_whitelist': True, 'approvals_whitelist_username': [R.ROLES['reviewer']['user']],
             'block_on_rejected_reviews': True, 'block_on_outdated_branch': True, 'block_admin_merge_override': True},
            {**zero, 'rule_name': R.PROPOSAL_PATTERN, 'priority': 2, 'enable_push': True, 'enable_push_whitelist': True,
             'push_whitelist_usernames': [R.ROLES['planner']['user'], R.ROLES['builder']['user']], **owner_merges},
            {**zero, 'rule_name': '**', 'priority': 3, **owner_merges},
        ]
        rules = R.protection_rules()
        for rule, want in zip(rules, expected, strict=True):
            with self.subTest(rule=rule['rule_name']):
                self.assertEqual(tuple(rule), self.GITEA_28_3_0_FIELDS)
                self.assertEqual(rule, want)
                # the bypass allowlist grants a force merge past every gate: disabled and empty everywhere
                self.assertEqual((rule['enable_bypass_allowlist'], rule['bypass_allowlist_usernames'],
                                  rule['bypass_allowlist_teams']), (False, [], []))
                self.assertFalse(rule['dismiss_stale_approvals'])  # open to G-03.1
        with self.assertRaises(ValueError):
            R._total_rule('x', 4, enable_bypass=True)

    def test_the_fixture_reads_back_every_field(self):
        api = SimpleNamespace(calls=[])
        rules = R.protection_rules()

        def call(method, path, body=None):
            api.calls.append((method, path))
            if path.endswith('/branch_protections'):
                return 200, [{**rule, 'branch_name': rule['rule_name'], 'created_at': 'then'} for rule in rules]
            if path.endswith('/permission'):
                return 200, {'permission': 'read'}
            return 200, {'full_name': 'x', 'private': True, 'default_branch': R.DEFAULT_BRANCH}

        api.call = call
        self.assertEqual(R.read_fixture(api)['branch_protections'], rules)

    def test_redaction_and_fingerprint(self):
        token = 'a' * 40
        self.assertEqual(R.redact(f'x {token} y'), 'x <redacted> y')
        self.assertRegex(R.fingerprint(token), r'^sha256:[0-9a-f]{16}$')
        self.assertNotIn(token, R.fingerprint(token))


class TestHostAccounts(unittest.TestCase):
    def test_user_list_with_type_column(self):
        out = (b'ID Username IsActive IsAdmin 2FA Type\n1 aieh-site-admin true true false User\n'
               b'3 aieh-bot-builder true false false Bot\n')
        run = lambda argv, **kw: SimpleNamespace(returncode=0, stdout=out, stderr=b'')
        lay = G.Layout(home=Path('.'), custom=Path('.'), config=Path('app.ini'), tmp=Path('.'))
        users = G.gitea_users(Path('gitea.exe'), lay, run)
        self.assertEqual(users['aieh-bot-builder'], {'admin': False, 'type': 'Bot'})
        self.assertEqual(G.BOT_ACCOUNTS, {r: s['user'] for r, s in R.ROLES.items()})


class TestNoTokenStoreReachesTheGuest(unittest.TestCase):
    """The declared guest surfaces (profiles P3-P5; F-03.3.1 observed them): no host share at all, and
    every host file the launch names is a pinned input or lives in the per-instance directory."""
    category = 'contract'
    PROFILE = json.loads((REPO / 'profiles' / 'strong-windows-qemu-whpx' / 'profile.json').read_text(encoding='utf-8'))

    def test_no_host_share_device(self):
        self.assertEqual(self.PROFILE['host_shares'], [])
        argv = ' '.join(self.PROFILE['launch']['argv'])
        for forbidden in ('-virtfs', '-fsdev', 'virtio-9p', 'vhost-user-fs', 'virtiofs', 'smb=', 'guestfwd',
                          'virtserialport', 'vhost-vsock'):
            self.assertNotIn(forbidden, argv)

    def test_every_host_file_is_a_pinned_input_or_per_instance(self):
        allowed = ('{instance_dir}/', '{input:', '{qemu_prefix}/')
        for arg in self.PROFILE['launch']['argv']:
            for value in re.findall(r'(?:filename|path)=([^,]+)', arg):
                self.assertTrue(value.startswith(allowed), value)
        text = json.dumps(self.PROFILE['launch']) + json.dumps(self.PROFILE.get('exchange'))
        for marker in ('AIEH_DATA_ROOT', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'Credential', 'gitea',
                       'persistent/'):
            self.assertNotIn(marker, text)

    def test_seed_templates_name_no_gitea_credential_or_managed_root(self):
        for name in ('user-data.tmpl', 'meta-data.tmpl', 'network-config.yaml'):
            text = (REPO / 'profiles' / 'seed' / name).read_text(encoding='utf-8')
            self.assertIsNone(re.search(r'(?i)gitea|AIEH_DATA_ROOT|LOCALAPPDATA|' + re.escape(R.TARGET_PREFIX), text),
                              name)


if __name__ == '__main__':
    unittest.main()
