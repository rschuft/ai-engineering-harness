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
        report = R.rotate('builder', http=self.gitea, ctx=ctx(self.cli, self.store))
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
            R.rotate('owner', http=self.gitea, ctx=ctx(self.cli, self.store))
        self.assertEqual(caught.exception.code, 'ROLE_UNKNOWN')
        with self.assertRaises(G.GiteaError) as caught:
            R.rotate('builder', http=self.gitea, ctx=ctx(self.cli, self.store))
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
