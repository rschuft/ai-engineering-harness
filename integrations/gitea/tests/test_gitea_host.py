"""Tests of the host-loopback Gitea lifecycle (plan leaf F-06.1).

Every test works in a temporary managed root named through an injected AIEH_DATA_ROOT, never the real
one. None touches the real Windows Credential Manager: the identity and credential-finalization tests
use an in-memory credential provider, a fake Gitea CLI and a fake Gitea (web forms and basic-auth API). The Windows tests exercise the real Job Object, socket-table and
token code against child Python processes. The live test runs the pinned Gitea end to end on a free
port in a temporary root, only when AIEH_GITEA_BINARY names a copy of the pinned binary.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WINDOWS = sys.platform == 'win32'


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


G = _load('aieh_gitea_host', HERE.parent / 'gitea_host.py')
P = G.paths
PIN = G.pin()
FAKE_BINARY = b'not gitea, a fixture'
FAKE_PIN = dict(PIN, sha256=hashlib.sha256(FAKE_BINARY).hexdigest())
SECRETS = {name: f'{name.lower()}-fixture-value' for name in G.SECRET_NAMES}
windows_only = unittest.skipUnless(WINDOWS, 'Windows process, job and socket APIs')


class Root(unittest.TestCase):
    """A temporary managed root resolved through AIEH_DATA_ROOT; never the real LOCALAPPDATA root."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='gh-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = {'AIEH_DATA_ROOT': str(self.tmp / 'root')}
        if WINDOWS:
            env['LOCALAPPDATA'] = str(self.tmp / 'lad')
        else:
            env['HOME'] = str(self.tmp / 'home')
        self.res = P.resolve(env, config={})
        self.lay = G.layout(self.res)
        P.init(self.res)
        G.ensure_dirs(self.res, self.lay)

    def acquire_fake(self):
        source = self.tmp / 'source.exe'
        source.write_bytes(FAKE_BINARY)
        return G.acquire(self.res, self.lay, FAKE_PIN, from_file=source)


class FakeRun:
    """Stands in for subprocess.run on the Gitea CLI; records each argv."""

    def __init__(self, users=(), password_line=True, fail=False):
        self.calls, self.users, self.password_line, self.fail = [], dict(users), password_line, fail
        self.generated = {}

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        assert kwargs.get('stdout') == subprocess.PIPE and kwargs.get('stderr') == subprocess.PIPE
        args = argv[argv.index('--config') + 2:] if '--config' in argv else argv[1:]
        out = b''
        if args[:2] == ['generate', 'secret']:
            out = f'{args[2].lower()}-generated\n'.encode()
        elif args[:3] == ['admin', 'user', 'list']:
            out = b'ID   Username         Email                  IsActive IsAdmin 2FA\n' + b''.join(
                f'{i}  {u}  {u}@x.invalid  true  {str(a).lower()}  false\n'.encode()
                for i, (u, a) in enumerate(self.users.items(), 1))
        elif args[:3] == ['admin', 'user', 'create']:
            user = args[args.index('--username') + 1]
            password = f'Temp-{user}-Pw-0123456789'
            self.generated[user] = password
            self.users[user] = '--admin' in args
            out = ((f"generated random password is '{password}'\n" if self.password_line else '')
                   + f"New user '{user}' has been successfully created!\n").encode()
        return SimpleNamespace(returncode=1 if self.fail else 0, stdout=out, stderr=b'')


class MemoryStore:
    def __init__(self, entries=None):
        self.entries = dict(entries or {})

    def write(self, target, user, secret, comment):
        assert target not in self.entries
        self.entries[target] = (user, bytes(secret))

    def read(self, target):
        return self.entries.get(target)

    def delete(self, target):
        return self.entries.pop(target, None) is not None


class TestPin(unittest.TestCase):
    category = 'contract'

    def test_lock_entry(self):
        self.assertEqual(PIN['name'], G.ASSET_NAME)
        self.assertRegex(PIN['sha256'], '^[0-9a-f]{64}$')
        self.assertEqual(PIN['url'] + '.sha256', PIN['checksum_file'])
        self.assertTrue(PIN['url'].startswith('https://github.com/go-gitea/gitea/releases/download/v28.3.0/'))
        self.assertEqual(PIN['method'], 'per-asset-checksum-file')

    def test_recorded_in_matrix_and_candidates(self):
        matrix = (REPO / 'composition' / 'compatibility-matrix.md').read_text(encoding='utf-8')
        self.assertIn(f'| Release | `{G.ASSET_NAME}` | `sha256:{PIN["sha256"]}` |', matrix)
        candidates = json.loads((REPO / 'composition' / 'candidates.json').read_text(encoding='utf-8'))
        gitea = next(c for c in candidates['components'] if c['id'] == 'gitea')
        self.assertIn({'name': G.ASSET_NAME, 'digest': f'sha256:{PIN["sha256"]}'},
                      [{'name': a['name'], 'digest': a['digest']} for a in gitea['artifacts']])

    def test_missing_pin_refused(self):
        repo = Path(tempfile.mkdtemp(prefix='gh-'))
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        (repo / 'composition' / 'lock').mkdir(parents=True)
        (repo / G.LOCK).write_text(json.dumps({'release_assets': []}), encoding='utf-8')
        with self.assertRaises(G.GiteaError) as caught:
            G.pin(repo)
        self.assertEqual(caught.exception.code, 'PIN_MISSING')


class TestLayout(Root):
    def test_every_path_from_the_resolver_and_outside_the_checkout(self):
        cats = {c: Path(str(self.res.paths[c])) for c in ('assets', 'gitea', 'logs', 'tmp')}
        self.assertEqual(self.lay.asset_dir, cats['assets'] / 'release-binaries' / 'gitea' / '28.3.0')
        self.assertEqual(self.lay.home, cats['gitea'])
        self.assertEqual(self.lay.logs, cats['logs'] / 'gitea')
        self.assertEqual(self.lay.tmp, cats['tmp'] / 'gitea')
        for name, path in self.lay.items():
            if name != 'repo':
                self.assertTrue(path.is_relative_to(self.tmp / 'root'), name)
                self.assertFalse(path.is_relative_to(REPO), name)
        for directory in (self.lay.asset_dir, self.lay.config.parent, self.lay.data, self.lay.repositories,
                          self.lay.run, self.lay.logs, self.lay.tmp):
            self.assertTrue(directory.is_dir(), directory)

    def test_ensure_dirs_reports_only_new_directories(self):
        self.assertEqual(G.ensure_dirs(self.res, self.lay), [])

    def test_layout_refuses_a_category_inside_the_checkout(self):
        res = SimpleNamespace(root=REPO.parent, repo_root=REPO, paths={
            'assets': REPO / 'assets', 'gitea': REPO.parent / 'g', 'logs': REPO.parent / 'l', 'tmp': REPO.parent / 't'})
        with self.assertRaises(G.GiteaError) as caught:
            G.layout(res)
        self.assertEqual(caught.exception.code, 'PATH_INSIDE_CHECKOUT')

    def test_child_env(self):
        env = G.child_env(self.lay, {'GITEA_CUSTOM': 'x', 'gitea__server__HTTP_ADDR': '0.0.0.0', 'HOME': 'h',
                                     'USERPROFILE': 'u', 'APPDATA': 'a', 'LOCALAPPDATA': 'l', 'PATH': 'p'})
        self.assertEqual(env['GITEA_CUSTOM'], str(self.lay.custom))
        self.assertNotIn('gitea__server__HTTP_ADDR', env)
        self.assertEqual((env['HOME'], env['USERPROFILE'], env['APPDATA'], env['LOCALAPPDATA']), ('h', 'u', 'a', 'l'))
        self.assertEqual((env['TMP'], env['TEMP'], env['GITEA_WORK_DIR']), (str(self.lay.tmp),) * 2 + (str(self.lay.home),))

    def test_argv_names_work_custom_and_config_paths(self):
        argv = G.gitea_argv(self.lay.binary, self.lay, 'web')
        self.assertEqual(argv[1:7], ['--work-path', str(self.lay.home), '--custom-path', str(self.lay.custom),
                                     '--config', str(self.lay.config)])


class TestAppIni(Root):
    def test_required_settings(self):
        ini_path = self.tmp / 'app.ini'
        ini_path.write_text(G.render_app_ini(self.lay, 13300, SECRETS), encoding='utf-8')
        ini = G.read_ini(ini_path)
        expected = {
            ('server', 'HTTP_ADDR'): '127.0.0.1', ('server', 'HTTP_PORT'): '13300',
            ('server', 'ROOT_URL'): 'http://127.0.0.1:13300/', ('server', 'DISABLE_SSH'): 'true',
            ('server', 'START_SSH_SERVER'): 'false', ('server', 'OFFLINE_MODE'): 'true',
            ('server', 'LFS_START_SERVER'): 'false', ('service', 'DISABLE_REGISTRATION'): 'true',
            ('service', 'REQUIRE_SIGNIN_VIEW'): 'true', ('security', 'INSTALL_LOCK'): 'true',
            ('database', 'DB_TYPE'): 'sqlite3', ('mailer', 'ENABLED'): 'false',
            ('cron.update_checker', 'ENABLED'): 'false', ('federation', 'ENABLED'): 'false',
            ('actions', 'ENABLED'): 'false', ('oauth2', 'ENABLED'): 'false',
            ('openid', 'ENABLE_OPENID_SIGNIN'): 'false', ('security', 'SECRET_KEY'): SECRETS['SECRET_KEY'],
            ('security', 'INTERNAL_TOKEN'): SECRETS['INTERNAL_TOKEN'], ('oauth2', 'JWT_SECRET'): SECRETS['JWT_SECRET']}
        for (section, key), value in expected.items():
            self.assertEqual(ini[section][key], value, f'[{section}] {key}')
        self.assertNotIn('picture', ini)  # Gitea 28 ignores these keys; OFFLINE_MODE governs avatars
        for section, key in (('', 'WORK_PATH'), ('server', 'APP_DATA_PATH'), ('database', 'PATH'),
                             ('repository', 'ROOT'), ('log', 'ROOT_PATH'), ('lfs', 'PATH')):
            self.assertTrue(Path(ini[section][key]).is_relative_to(self.tmp / 'root'), key)
        self.assertEqual(Path(ini['database']['PATH']), self.lay.db)

    def test_incomplete_secrets_refused(self):
        with self.assertRaises(G.GiteaError):
            G.render_app_ini(self.lay, 13300, {k: v for k, v in SECRETS.items() if k != 'JWT_SECRET'})
        with self.assertRaises(G.GiteaError):
            G.render_app_ini(self.lay, 13300, dict(SECRETS, SECRET_KEY=''))

    def test_configure_uses_gitea_generate_and_writes_once(self):
        self.acquire_fake()
        run = FakeRun()
        result = G.configure(self.res, self.lay, FAKE_PIN, 13300, run=run)
        self.assertTrue(result['written'])
        self.assertEqual([c[1:] for c in run.calls], [['generate', 'secret', n] for n in G.SECRET_NAMES])
        ini = G.read_ini(self.lay.config)
        self.assertEqual(ini['security']['SECRET_KEY'], 'secret_key-generated')
        record = G.read_host_record(self.lay)
        self.assertEqual((record['port'], record['bind'], record['sha256']), (13300, '127.0.0.1', FAKE_PIN['sha256']))
        for name in G.SECRET_NAMES:  # no secret value in the host record
            self.assertNotIn(f'{name.lower()}-generated', json.dumps(record))
        again = G.configure(self.res, self.lay, FAKE_PIN, 14000, run=run)
        self.assertEqual((again['written'], again['port']), (False, 13300))
        self.assertEqual(len(run.calls), 3)

    def test_port_range_refused(self):
        self.acquire_fake()
        for port in (80, 50000, 59292):
            with self.assertRaises(G.GiteaError) as caught:
                G.configure(self.res, self.lay, FAKE_PIN, port, run=FakeRun())
            self.assertEqual(caught.exception.code, 'PORT_INVALID')

    def test_host_record_must_match_a_loopback_config(self):
        self.acquire_fake()
        G.configure(self.res, self.lay, FAKE_PIN, 13300, run=FakeRun())
        text = self.lay.config.read_text(encoding='utf-8').replace('HTTP_ADDR = 127.0.0.1', 'HTTP_ADDR = 0.0.0.0')
        self.lay.config.write_text(text, encoding='utf-8')
        with self.assertRaises(G.GiteaError) as caught:
            G.read_host_record(self.lay)
        self.assertEqual(caught.exception.code, 'CONFIG_NOT_LOOPBACK')


class TestAcquire(Root):
    def test_download_verified_then_recorded(self):
        opener = mock.Mock(return_value=io.BytesIO(FAKE_BINARY))
        result = G.acquire(self.res, self.lay, FAKE_PIN, opener=opener)
        self.assertTrue(result['acquired'])
        self.assertEqual(opener.call_args[0][0].full_url, PIN['url'])
        self.assertEqual(self.lay.binary.read_bytes(), FAKE_BINARY)
        record = P.read_asset_record(self.lay.asset_dir)
        self.assertEqual(record['integrity']['sha256'], {G.ASSET_NAME: FAKE_PIN['sha256']})
        self.assertEqual((record['kind'], record['name'], record['version']), ('release-binaries', 'gitea', '28.3.0'))
        self.assertEqual(record['provenance']['source'], PIN['url'])
        self.assertIn('task gitea:install', record['reacquire'])
        self.assertEqual(sorted(p.name for p in self.lay.asset_dir.iterdir()), sorted([G.ASSET_NAME, 'aieh-asset.json']))
        self.assertFalse(G.acquire(self.res, self.lay, FAKE_PIN, opener=opener)['acquired'])
        self.assertEqual(opener.call_count, 1)

    def test_mismatch_never_enters_the_assets(self):
        with self.assertRaises(G.GiteaError) as caught:
            G.acquire(self.res, self.lay, FAKE_PIN, opener=mock.Mock(return_value=io.BytesIO(b'tampered')))
        self.assertEqual(caught.exception.code, 'DOWNLOAD_MISMATCH')
        self.assertEqual(list(self.lay.asset_dir.iterdir()), [])
        self.assertEqual(len(list(self.lay.tmp.glob('*.partial'))), 1)  # left for controlled cleanup

    def test_unrecorded_binary_refused(self):
        self.lay.binary.write_bytes(FAKE_BINARY)
        with self.assertRaises(G.GiteaError) as caught:
            self.acquire_fake()
        self.assertEqual(caught.exception.code, 'ASSET_UNRECORDED')


class TestVerifiedBinary(Root):
    def test_tampered_binary_is_never_executed(self):
        self.acquire_fake()
        self.lay.binary.write_bytes(FAKE_BINARY + b'!')
        run = mock.Mock(side_effect=AssertionError('executed an unverified binary'))
        with self.assertRaises(G.GiteaError) as caught:
            G.configure(self.res, self.lay, FAKE_PIN, 13300, run=run)
        self.assertEqual(caught.exception.code, 'BINARY_MISMATCH')
        run.assert_not_called()

    def test_record_must_carry_the_pin(self):
        self.acquire_fake()
        with self.assertRaises(G.GiteaError) as caught:
            with G.verified_binary(self.lay, '0' * 64):
                pass
        self.assertEqual(caught.exception.code, 'BINARY_MISMATCH')

    def test_missing_binary(self):
        with self.assertRaises(G.GiteaError) as caught:
            with G.verified_binary(self.lay, FAKE_PIN['sha256']):
                pass
        self.assertEqual(caught.exception.code, 'BINARY_MISSING')

    @windows_only
    def test_binary_locked_against_change_while_verified(self):
        self.acquire_fake()
        with G.verified_binary(self.lay, FAKE_PIN['sha256']) as path:
            with self.assertRaises(PermissionError):
                open(path, 'r+b').close()
            with self.assertRaises(PermissionError):
                os.replace(path, self.tmp / 'moved.exe')
            with open(path, 'rb') as reader:  # reading (as the loader does) stays possible
                self.assertEqual(reader.read(), FAKE_BINARY)
        open(path, 'r+b').close()  # released after the block


class TestIdentities(Root):
    def setUp(self):
        super().setUp()
        self.acquire_fake()
        G.configure(self.res, self.lay, FAKE_PIN, 13300, run=FakeRun())
        patcher = mock.patch.object(G, 'healthy', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_two_accounts_and_two_entries_without_exposure(self):
        run, store = FakeRun(), MemoryProvider()
        report = G.create_identities(self.res, self.lay, FAKE_PIN, provider=store, run=run)
        self.assertEqual(report['created'], [G.SITE_ADMIN, G.OWNER])
        self.assertEqual(report['admin'], {G.SITE_ADMIN: True, G.OWNER: False})
        creates = [c for c in run.calls if 'create' in c]
        self.assertEqual(len(creates), 2)
        for argv in creates:
            self.assertIn('--random-password', argv)
            self.assertIn('--must-change-password=true', argv)
            self.assertNotIn('--password', argv)
            self.assertTrue(argv[argv.index('--email') + 1].endswith('@localhost.invalid'))
        self.assertIn('--admin', creates[0])
        self.assertNotIn('--admin', creates[1])
        for user, target in G.CRED_TARGETS.items():
            name, secret = store.get(target)
            self.assertEqual((name, secret), (user, run.generated[user]))
        text = json.dumps(report)
        for password in run.generated.values():
            self.assertNotIn(password, text)
            for argv in run.calls:
                self.assertNotIn(password, ' '.join(argv))

    def test_refusals(self):
        with self.assertRaises(G.GiteaError) as caught:
            G.create_identities(self.res, self.lay, FAKE_PIN, run=FakeRun(),
                                provider=MemoryProvider({G.CRED_TARGETS[G.OWNER]: ('x', 'y')}))
        self.assertEqual(caught.exception.code, 'CREDENTIAL_EXISTS')
        with self.assertRaises(G.GiteaError) as caught:
            G.create_identities(self.res, self.lay, FAKE_PIN, run=FakeRun(),
                                provider=MemoryProvider({G.FINAL_TARGETS[G.SITE_ADMIN]: ('x', 'y')}))
        self.assertEqual(caught.exception.code, 'CREDENTIAL_EXISTS')
        with self.assertRaises(G.GiteaError) as caught:
            G.create_identities(self.res, self.lay, FAKE_PIN, provider=MemoryProvider(), run=FakeRun({G.OWNER: False}))
        self.assertEqual(caught.exception.code, 'ACCOUNT_EXISTS')
        with mock.patch.object(G, 'healthy', return_value=False), self.assertRaises(G.GiteaError) as caught:
            G.create_identities(self.res, self.lay, FAKE_PIN, provider=MemoryProvider(), run=FakeRun())
        self.assertEqual(caught.exception.code, 'NOT_RUNNING')

    def test_cli_failure_withholds_output(self):
        run, store = FakeRun(password_line=True), MemoryProvider()
        original = run.__call__

        def failing(argv, **kwargs):
            result = original(argv, **kwargs)
            return SimpleNamespace(returncode=1, stdout=result.stdout, stderr=b'') if 'create' in argv else result
        with self.assertRaises(G.GiteaError) as caught:
            G.create_identities(self.res, self.lay, FAKE_PIN, provider=store, run=failing)
        self.assertEqual(caught.exception.code, 'ACCOUNT_CREATE_FAILED')
        self.assertNotIn(run.generated[G.SITE_ADMIN], str(caught.exception))
        self.assertEqual(store.entries, {})

    def test_missing_password_line_fails_closed(self):
        with self.assertRaises(G.GiteaError) as caught:
            G.create_identities(self.res, self.lay, FAKE_PIN, provider=MemoryProvider(), run=FakeRun(password_line=False))
        self.assertEqual(caught.exception.code, 'ACCOUNT_CREATE_FAILED')

    def test_user_list_parsing(self):
        users = G.gitea_users(self.lay.binary, self.lay, FakeRun({G.SITE_ADMIN: True, G.OWNER: False}))
        self.assertEqual(users, {G.SITE_ADMIN: {'admin': True}, G.OWNER: {'admin': False}})


class FakeAccounts:
    """Gitea's accounts as finalize-credentials meets them: basic-auth API (/api/v1/user, token listing and
    deletion) and the web sign-in and forced-change forms, on one fake loopback server. Every request is
    logged by path only."""

    def __init__(self, passwords, tokens=None, fail_change=False, login_redirect='/'):
        self.accounts = {u: {'password': p, 'must_change': True, 'admin': u == G.SITE_ADMIN}
                         for u, p in passwords.items()}
        self.tokens = {u: list(t) for u, t in (tokens or {}).items()}
        self.sessions, self.log, self.fail_change, self.next_id = {}, [], fail_change, 100
        self.login_redirect = login_redirect

    def who(self, headers):
        auth = (headers or {}).get('Authorization', '')
        if not auth.startswith('Basic '):
            return None, 'none'
        user, _, password = base64.b64decode(auth[6:]).decode().partition(':')
        account = self.accounts.get(user)
        if account is None or account['password'] != password:
            return None, 'wrong'
        return user, 'must-change' if account['must_change'] else 'ok'

    def __call__(self, port, path, method='GET', body=None, headers=None, timeout=5.0):
        self.log.append((method, path))
        user, state = self.who(headers)
        if state in ('none', 'wrong'):
            return 401, {}, b'{"message":"unauthorized"}'
        if state == 'must-change':
            return 403, {}, b'{"message":"You must change your password. Change it at: x"}'
        route = path.removeprefix('/api/v1')
        if route == '/user':
            return 200, {}, json.dumps({'login': user, 'is_admin': self.accounts[user]['admin']}).encode()
        if route == f'/users/{user}/tokens' and method == 'GET':
            return 200, {}, json.dumps([{'id': i, 'name': n} for i, n in self.tokens.get(user, [])]).encode()
        if route.startswith(f'/users/{user}/tokens/') and method == 'DELETE':
            ident = int(route.rsplit('/', 1)[1])
            self.tokens[user] = [(i, n) for i, n in self.tokens.get(user, []) if i != ident]
            return 204, {}, b''
        return 404, {}, b'{}'

    def connection(self):
        """Gitea 28.3.0's web behaviour as observed on a disposable instance (S-01.2.2): a correct sign-in
        answers 303 to the redirect_to target, which is / (login_redirect), even when the account must
        change its password; the next page request then answers 303 to the change form; the form is 200;
        a wrong password answers 200 with the sign-in form."""
        fake = self

        class Response:
            def __init__(self, status, location, cookie, body=b''):
                self.status, self._location, self._body = status, location, body
                self.msg = SimpleNamespace(get_all=lambda name: [cookie] if cookie and name == 'Set-Cookie' else None)

            def getheader(self, name):
                return self._location if name == 'Location' else None

            def read(self):
                return self._body

        class Connection:
            def request(self, method, path, body=None, headers=None):
                fake.log.append((method, path))
                form = dict(urllib.parse.parse_qsl(body.decode())) if body else {}
                cookie = (headers or {}).get('Cookie', '')
                sid = dict(part.split('=', 1) for part in cookie.split('; ') if '=' in part).get('i_like_gitea')
                session = fake.sessions.get(sid)
                must = session is not None and fake.accounts[session]['must_change']
                if path == '/user/login' and method == 'POST':
                    account = fake.accounts.get(form.get('user_name'))
                    if account is None or account['password'] != form.get('password'):
                        self.response = Response(200, '', None, b'Username or password is incorrect.')
                    else:
                        sid = f'sid{len(fake.sessions)}'
                        fake.sessions[sid] = form['user_name']
                        self.response = Response(303, fake.login_redirect,
                                                 f'i_like_gitea={sid}; Path=/; HttpOnly')
                elif path == '/user/settings/change_password' and session and method == 'GET':
                    self.response = Response(200, '', None, b'<input name="password"><input name="retype">')
                elif path == '/user/settings/change_password' and session and method == 'POST':
                    if fake.fail_change or form['password'] != form['retype']:
                        self.response = Response(200, '', None)
                    else:
                        fake.accounts[session].update(password=form['password'], must_change=False)
                        self.response = Response(303, '/', None)
                elif method == 'GET' and must:
                    self.response = Response(303, '/user/settings/change_password', None)
                elif method == 'GET' and session:
                    self.response = Response(200, '', None, b'dashboard')
                else:
                    self.response = Response(404, '', None)

            def getresponse(self):
                return self.response

            def close(self):
                pass
        return Connection()


class MemoryProvider(G.CredentialProvider):
    def __init__(self, entries=None, events=None):
        self.entries, self.events = dict(entries or {}), events if events is not None else []

    def get(self, name):
        return self.entries.get(name)

    def set(self, name, user, secret, comment=''):
        self.events.append(('set', name))
        self.entries[name] = (user, secret)

    def delete(self, name):
        self.events.append(('delete', name))
        return self.entries.pop(name, None) is not None


class TestCredentialProvider(unittest.TestCase):
    def test_windows_provider_wraps_the_store_as_utf16(self):
        store = MemoryStore()
        provider = G.WindowsCredentialProvider(store)
        self.assertFalse(provider.exists('AIEH x'))
        provider.set('AIEH x', 'u', 'pässword', 'c')
        self.assertEqual(store.entries['AIEH x'], ('u', 'pässword'.encode('utf-16-le')))
        self.assertEqual(provider.get('AIEH x'), ('u', 'pässword'))
        self.assertTrue(provider.exists('AIEH x'))
        self.assertTrue(provider.delete('AIEH x'))
        self.assertFalse(provider.delete('AIEH x'))

    def test_interface(self):
        for name in ('get', 'set', 'delete', 'exists'):
            self.assertTrue(callable(getattr(G.CredentialProvider, name)))
        with self.assertRaises(NotImplementedError):
            G.CredentialProvider().get('x')


class TestFinalizeCredentials(Root):
    TEMP = {G.SITE_ADMIN: 'Temp-site-admin-Pw-9876543210', G.OWNER: 'Temp-owner-Pw-9876543210'}

    def setUp(self):
        super().setUp()
        self.acquire_fake()
        G.configure(self.res, self.lay, FAKE_PIN, 13300, run=FakeRun())
        self.events = []
        self.provider = MemoryProvider({G.CRED_TARGETS[u]: (u, p) for u, p in self.TEMP.items()}, self.events)
        self.gitea = FakeAccounts(self.TEMP, tokens={G.SITE_ADMIN: [(7, 'aieh-s0122-fixture-20261107T175000Z')]})
        self.repo = self.tmp / 'repo'
        self.repo.mkdir()
        for name, value in (('healthy', True), ('checkout_files', [])):
            patcher = mock.patch.object(G, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def finalize(self, gitea=None):
        gitea = gitea or self.gitea
        return G.finalize_credentials(self.res, self.lay, FAKE_PIN, provider=self.provider, http=gitea,
                                      connection=gitea.connection, repo=self.repo)

    def finals(self):
        return {u: self.provider.get(G.FINAL_TARGETS[u]) for u in self.TEMP}

    def test_both_accounts_finalized_without_exposure(self):
        report = self.finalize()
        for user, (name, final) in self.finals().items():
            self.assertEqual(name, user)
            self.assertGreaterEqual(len(final), 43)
            self.assertEqual(self.gitea.accounts[user], {'password': final, 'must_change': False,
                                                         'admin': user == G.SITE_ADMIN})
            self.assertIsNone(self.provider.get(G.CRED_TARGETS[user]))
        self.assertNotEqual(*[f for _u, f in self.finals().values()])
        admin, owner = report['accounts']
        self.assertEqual(admin['tokens'], {'found': ['aieh-s0122-fixture-20261107T175000Z'],
                                           'deleted': ['aieh-s0122-fixture-20261107T175000Z'], 'remaining': []})
        self.assertEqual(owner['tokens'], {'found': [], 'deleted': [], 'remaining': []})
        self.assertEqual((admin['is_admin'], owner['is_admin']), (True, False))
        self.assertEqual({a['temporary_password'] for a in report['accounts']}, {'rejected'})
        self.assertEqual((report['found_in_managed_root'], report['found_in_checkout'], report['found_in_report']),
                         ([], [], False))
        text = json.dumps(report)
        for secret in [*self.TEMP.values(), *(f for _u, f in self.finals().values())]:
            self.assertNotIn(secret, text)

    def test_final_password_stored_before_the_change_and_tokens_revoked_first(self):
        self.finalize()
        for user in self.TEMP:
            stored = self.events.index(('set', G.FINAL_TARGETS[user]))
            deleted = self.events.index(('delete', G.CRED_TARGETS[user]))
            self.assertLess(stored, deleted)
        change = self.gitea.log.index(('POST', '/user/settings/change_password'))
        after = [entry for entry in self.gitea.log[change + 1:] if entry[1].startswith('/api/v1')]
        self.assertEqual(after[0], ('GET', f'/api/v1/users/{G.SITE_ADMIN}/tokens'))
        self.assertEqual(after[1], ('DELETE', f'/api/v1/users/{G.SITE_ADMIN}/tokens/7'))

    def test_a_failed_change_keeps_both_entries_and_a_rerun_completes(self):
        failing = FakeAccounts(self.TEMP, fail_change=True)
        with self.assertRaises(G.GiteaError) as caught:
            self.finalize(failing)
        self.assertEqual(caught.exception.code, 'PASSWORD_CHANGE_FAILED')
        stored = self.provider.get(G.FINAL_TARGETS[G.SITE_ADMIN])
        self.assertIsNotNone(stored)
        self.assertIsNotNone(self.provider.get(G.CRED_TARGETS[G.SITE_ADMIN]))
        failing.fail_change = False
        report = self.finalize(failing)
        self.assertEqual(self.provider.get(G.FINAL_TARGETS[G.SITE_ADMIN]), stored)
        self.assertEqual(failing.accounts[G.SITE_ADMIN]['password'], stored[1])
        self.assertEqual(report['accounts'][0]['stored_before_change'], 'by an earlier run')

    def test_a_rerun_after_the_change_resumes_and_an_already_final_account_is_verified(self):
        self.finalize()
        report = self.finalize()
        self.assertEqual([a['state'] for a in report['accounts']], ['already final'] * 2)
        self.provider.entries[G.CRED_TARGETS[G.OWNER]] = (G.OWNER, self.TEMP[G.OWNER])
        report = self.finalize()
        self.assertEqual(report['accounts'][1]['change'], 'already applied by an earlier run')
        self.assertIsNone(self.provider.get(G.CRED_TARGETS[G.OWNER]))

    def test_rejected_temporary_password_changes_nothing(self):
        self.provider.entries[G.CRED_TARGETS[G.SITE_ADMIN]] = (G.SITE_ADMIN, 'not-the-password')
        with self.assertRaises(G.GiteaError) as caught:
            self.finalize()
        self.assertEqual(caught.exception.code, 'TEMPORARY_PASSWORD_REJECTED')
        self.assertTrue(self.gitea.accounts[G.SITE_ADMIN]['must_change'])
        self.assertNotIn('not-the-password', str(caught.exception))

    def test_password_found_in_the_managed_root_is_reported_by_name_only(self):
        leak = self.lay.logs / 'leak.log'
        leak.write_bytes(b'x' * (1 << 20) + self.TEMP[G.OWNER].encode('utf-16-le') + b'y')
        with self.assertRaises(G.GiteaError) as caught:
            self.finalize()
        self.assertEqual(caught.exception.code, 'PASSWORD_FOUND')
        self.assertIn('leak.log', str(caught.exception))
        self.assertNotIn(self.TEMP[G.OWNER], str(caught.exception))

    def test_missing_entries_refused(self):
        self.provider.entries.clear()
        with self.assertRaises(G.GiteaError) as caught:
            self.finalize()
        self.assertEqual(caught.exception.code, 'ENTRIES_MISSING')

    def test_sign_in_redirects_to_root_then_gitea_demands_the_change(self):
        # Observed on Gitea 28.3.0: the sign-in answers 303 to / (not to the form); GET / answers 303 to it.
        result = G.change_password_by_web(13300, G.SITE_ADMIN, self.TEMP[G.SITE_ADMIN], 'N' * 43,
                                          self.gitea.connection)
        self.assertEqual(result['trail'], ['sign-in 303 /', 'GET / 303 /user/settings/change_password',
                                           'GET /user/settings/change_password 200', 'change 303 /'])
        self.assertEqual(self.gitea.accounts[G.SITE_ADMIN], {'password': 'N' * 43, 'must_change': False,
                                                             'admin': True})
        self.assertNotIn('N' * 43, json.dumps(result))

    def test_a_direct_redirect_to_the_form_also_works(self):
        gitea = FakeAccounts(self.TEMP, login_redirect='/user/settings/change_password')
        result = G.change_password_by_web(13300, G.OWNER, self.TEMP[G.OWNER], 'M' * 43, gitea.connection)
        self.assertEqual(result['trail'][0], 'sign-in 303 /user/settings/change_password')
        self.assertFalse(gitea.accounts[G.OWNER]['must_change'])

    def test_wrong_password_or_no_change_demand_refused_without_submitting(self):
        with self.assertRaises(G.GiteaError) as caught:
            G.change_password_by_web(13300, G.SITE_ADMIN, 'wrong-password', 'N' * 43, self.gitea.connection)
        self.assertEqual(caught.exception.code, 'SIGN_IN_FAILED')
        self.gitea.accounts[G.OWNER]['must_change'] = False
        with self.assertRaises(G.GiteaError) as caught:
            G.change_password_by_web(13300, G.OWNER, self.TEMP[G.OWNER], 'N' * 43, self.gitea.connection)
        self.assertEqual(caught.exception.code, 'CHANGE_NOT_DEMANDED')
        self.assertNotIn(('POST', '/user/settings/change_password'), self.gitea.log)
        for secret in (self.TEMP[G.OWNER], 'N' * 43, 'wrong-password'):
            self.assertNotIn(secret, str(caught.exception))

    def test_rerun_after_a_failed_sign_in_reuses_the_stored_final_password(self):
        # The live run of 2026-11-07: the final password was stored, then the sign-in step raised.
        stored = 'S' * 43
        self.provider.entries[G.FINAL_TARGETS[G.SITE_ADMIN]] = (G.SITE_ADMIN, stored)
        report = self.finalize()
        self.assertEqual(report['accounts'][0]['stored_before_change'], 'by an earlier run')
        self.assertEqual(self.gitea.accounts[G.SITE_ADMIN]['password'], stored)
        self.assertEqual(report['accounts'][0]['tokens']['remaining'], [])

    def test_checkout_search(self):
        (self.repo / 'tracked.txt').write_bytes(b'a ' + self.TEMP[G.SITE_ADMIN].encode() + b' b')
        self.assertEqual(G.files_containing([self.repo / 'tracked.txt'], [self.TEMP[G.SITE_ADMIN].encode()]),
                         {'found': [str(self.repo / 'tracked.txt')], 'unreadable': [], 'absent': []})
        self.assertEqual(G.files_containing([self.repo / 'tracked.txt'], [self.TEMP[G.OWNER].encode()]),
                         {'found': [], 'unreadable': [], 'absent': []})

    # Review finding 2 (2026-11-07): the revocation postcondition is enforced on both paths.

    def test_a_token_still_listed_after_a_204_delete_fails_the_change_path_and_a_rerun_resumes(self):
        gitea = RevocationFake(self.TEMP, tokens={G.SITE_ADMIN: [(7, 'aieh-s0122-fixture-20261107T175000Z')]},
                               sticky={7})
        with self.assertRaises(G.GiteaError) as caught:
            self.finalize(gitea)
        self.assertEqual(caught.exception.code, 'TOKENS_REMAIN')
        self.assertIn('aieh-s0122-fixture-20261107T175000Z', caught.exception.detail)
        stored = self.provider.get(G.FINAL_TARGETS[G.SITE_ADMIN])
        # Raised after the password change and before the temporary entry is deleted: both entries remain.
        self.assertEqual(gitea.accounts[G.SITE_ADMIN]['password'], stored[1])
        self.assertIsNotNone(self.provider.get(G.CRED_TARGETS[G.SITE_ADMIN]))
        self.assertNotIn(('delete', G.CRED_TARGETS[G.SITE_ADMIN]), self.events)
        for secret in (*self.TEMP.values(), stored[1]):
            self.assertNotIn(secret, str(caught.exception))
        gitea.sticky.clear()
        report = self.finalize(gitea)
        admin = report['accounts'][0]
        self.assertEqual(admin['stored_before_change'], 'by an earlier run')
        self.assertEqual(admin['change'], 'already applied by an earlier run')
        self.assertEqual(admin['tokens']['remaining'], [])
        self.assertIsNone(self.provider.get(G.CRED_TARGETS[G.SITE_ADMIN]))
        self.assertEqual(self.provider.get(G.FINAL_TARGETS[G.SITE_ADMIN]), stored)

    def test_an_unverifiable_listing_fails_the_change_path_and_a_rerun_resumes(self):
        for relist in ((500, b'{"message":"boom"}'), (200, b'{"not":"a list"}')):
            with self.subTest(relist=relist):
                gitea = RevocationFake(self.TEMP, relist=relist)
                provider = self.provider = MemoryProvider(
                    {G.CRED_TARGETS[u]: (u, p) for u, p in self.TEMP.items()})
                with self.assertRaises(G.GiteaError) as caught:
                    self.finalize(gitea)
                self.assertEqual(caught.exception.code, 'TOKEN_REVOCATION_UNVERIFIED')
                self.assertIsNotNone(provider.get(G.CRED_TARGETS[G.SITE_ADMIN]))
                self.assertFalse(gitea.accounts[G.SITE_ADMIN]['must_change'])
                gitea.relist = None
                report = self.finalize(gitea)
                self.assertEqual(report['accounts'][0]['change'], 'already applied by an earlier run')
                self.assertIsNone(provider.get(G.CRED_TARGETS[G.SITE_ADMIN]))

    def test_the_already_final_path_also_fails_closed(self):
        gitea = RevocationFake(self.TEMP)
        self.finalize(gitea)
        gitea.tokens[G.OWNER] = [(9, 'minted-after-finalization')]
        gitea.sticky = {9}
        with self.assertRaises(G.GiteaError) as caught:
            self.finalize(gitea)
        self.assertEqual(caught.exception.code, 'TOKENS_REMAIN')
        self.assertIn('minted-after-finalization', caught.exception.detail)
        gitea.sticky.clear()
        gitea.relist = (403, b'{"message":"forbidden"}')
        with self.assertRaises(G.GiteaError) as caught:
            self.finalize(gitea)
        self.assertEqual(caught.exception.code, 'TOKEN_REVOCATION_UNVERIFIED')
        gitea.relist = None
        report = self.finalize(gitea)
        self.assertEqual([a['state'] for a in report['accounts']], ['already final'] * 2)
        self.assertEqual([a['tokens']['remaining'] for a in report['accounts']], [[], []])

    # Review finding 3 (2026-11-07): an incomplete secret scan is never a clean result.

    def test_an_unreadable_checkout_file_refuses_as_an_incomplete_scan(self):
        G.checkout_files.return_value = [UnreadablePath(self.repo / 'locked.bin'), self.repo / 'deleted.txt']
        with self.assertRaises(G.GiteaError) as caught:
            self.finalize()
        self.assertEqual(caught.exception.code, 'SECRET_SCAN_INCOMPLETE')
        detail = json.loads(caught.exception.detail)
        self.assertEqual(detail, {'managed_root': [],
                                  'checkout': [f'{self.repo / "locked.bin"} (file not read: PermissionError)']})
        self.assertNotIn('deleted.txt', caught.exception.detail)

    def test_an_unlisted_managed_root_directory_refuses_as_an_incomplete_scan(self):
        with mock.patch.object(os, 'scandir', denying_scandir(self.lay.logs)):
            with self.assertRaises(G.GiteaError) as caught:
                self.finalize()
        self.assertEqual(caught.exception.code, 'SECRET_SCAN_INCOMPLETE')
        detail = json.loads(caught.exception.detail)
        self.assertEqual(detail['checkout'], [])
        self.assertEqual(detail['managed_root'], [f'{self.lay.logs} (directory not listed: PermissionError)'])

    def test_a_missing_tracked_file_is_reported_as_absent_not_as_a_failure(self):
        G.checkout_files.return_value = [self.repo / 'deleted.txt']
        report = self.finalize()
        self.assertEqual(report['absent_from_checkout'], [str(self.repo / 'deleted.txt')])
        self.assertEqual(report['scan_incomplete'], {'managed_root': [], 'checkout': []})


class RevocationFake(FakeAccounts):
    """FakeAccounts whose token deletion can answer 204 without deleting (sticky ids), and whose listing
    after the deletions (the second listing of one revocation) can answer `relist` (status, body)."""

    def __init__(self, passwords, tokens=None, sticky=(), relist=None):
        super().__init__(passwords, tokens)
        self.sticky, self.relist, self.listings = set(sticky), relist, {}

    def __call__(self, port, path, method='GET', body=None, headers=None, timeout=5.0):
        user, state = self.who(headers)
        route = path.removeprefix('/api/v1')
        if state == 'ok' and method == 'DELETE' and route.startswith(f'/users/{user}/tokens/'):
            if int(route.rsplit('/', 1)[1]) in self.sticky:
                self.log.append((method, path))
                return 204, {}, b''
        if state == 'ok' and method == 'GET' and route == f'/users/{user}/tokens':
            self.listings[user] = self.listings.get(user, 0) + 1
            if self.relist is not None and self.listings[user] % 2 == 0:
                self.log.append((method, path))
                return self.relist[0], {}, self.relist[1]
        return super().__call__(port, path, method, body, headers, timeout)


class UnreadablePath:
    """A listed checkout path whose read fails like a file held open without sharing (no Windows ACL needed)."""

    def __init__(self, path):
        self.path = path

    def read_bytes(self):
        raise PermissionError(13, 'Permission denied', str(self.path))

    def __str__(self):
        return str(self.path)


def denying_scandir(denied):
    """os.scandir that refuses to list one directory, as an ACL would; os.walk reaches it through scandir."""
    real = os.scandir

    def scandir(path='.'):
        if os.path.normcase(os.fspath(path)) == os.path.normcase(os.fspath(denied)):
            raise PermissionError(13, 'Permission denied', os.fspath(path))
        return real(path)
    return scandir


class TestRevokeAllTokens(unittest.TestCase):
    """Review finding 2: revoke_all_tokens enforces 'no token remains' instead of only reporting it."""
    PASSWORDS = {G.SITE_ADMIN: 'Final-site-admin-Pw-0123456789'}

    def gitea(self, tokens=(), **kwargs):
        fake = RevocationFake(self.PASSWORDS, tokens={G.SITE_ADMIN: list(tokens)}, **kwargs)
        fake.accounts[G.SITE_ADMIN]['must_change'] = False
        return fake

    def revoke(self, fake):
        return G.revoke_all_tokens(13300, G.SITE_ADMIN, self.PASSWORDS[G.SITE_ADMIN], fake)

    def test_an_empty_listing_after_revocation_passes(self):
        fake = self.gitea([(1, 'one'), (2, 'two')])
        self.assertEqual(self.revoke(fake), {'found': ['one', 'two'], 'deleted': ['one', 'two'], 'remaining': []})
        self.assertEqual(fake.tokens[G.SITE_ADMIN], [])

    def test_a_remaining_token_raises_with_its_name_only(self):
        fake = self.gitea([(1, 'one')])
        real = fake.__call__

        def mint_during_revocation(port, path, method='GET', **kwargs):
            answer = real(port, path, method, **kwargs)
            if method == 'DELETE':
                fake.tokens[G.SITE_ADMIN].append((3, 'minted-meanwhile'))
            return answer
        with self.assertRaises(G.GiteaError) as caught:
            self.revoke(mint_during_revocation)
        self.assertEqual(caught.exception.code, 'TOKENS_REMAIN')
        self.assertFalse(caught.exception.refusal)
        self.assertIn("'minted-meanwhile'", caught.exception.detail)
        self.assertNotIn(self.PASSWORDS[G.SITE_ADMIN], str(caught.exception))

    def test_a_204_delete_whose_token_is_still_listed_raises(self):
        fake = self.gitea([(1, 'one'), (2, 'sticky')], sticky={2})
        with self.assertRaises(G.GiteaError) as caught:
            self.revoke(fake)
        self.assertEqual(caught.exception.code, 'TOKENS_REMAIN')
        self.assertIn("still listed after revocation: ['sticky']", caught.exception.detail)
        self.assertIn(('DELETE', f'/api/v1/users/{G.SITE_ADMIN}/tokens/2'), fake.log)

    def test_an_unverifiable_listing_after_revocation_raises(self):
        for relist in ((500, b'{"message":"boom"}'), (401, b''), (200, b'{"tokens":[]}'), (200, b'not json')):
            with self.subTest(relist=relist):
                fake = self.gitea([(1, 'one')], relist=relist)
                with self.assertRaises(G.GiteaError) as caught:
                    self.revoke(fake)
                self.assertEqual(caught.exception.code, 'TOKEN_REVOCATION_UNVERIFIED')
                self.assertIn(f'answered {relist[0]}', caught.exception.detail)

    def test_the_first_listing_failing_is_still_token_list_failed(self):
        fake = self.gitea([(1, 'one')], relist=(500, b''))
        fake.listings[G.SITE_ADMIN] = 1  # the next listing is the "after" one
        with self.assertRaises(G.GiteaError) as caught:
            self.revoke(fake)
        self.assertEqual(caught.exception.code, 'TOKEN_LIST_FAILED')
        self.assertNotIn(('DELETE', f'/api/v1/users/{G.SITE_ADMIN}/tokens/1'), fake.log)


class TestSecretScans(unittest.TestCase):
    """Review finding 3: what the scans cannot read is reported as incomplete, never skipped."""
    NEEDLE = b'needle-value-0123456789'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='gh-scan-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_files_containing_reports_an_unreadable_file(self):
        readable = self.tmp / 'readable.txt'
        readable.write_bytes(b'clean')
        result = G.files_containing([readable, UnreadablePath(self.tmp / 'held.bin')], [self.NEEDLE])
        self.assertEqual(result, {'found': [], 'unreadable': [f'{self.tmp / "held.bin"} (file not read: '
                                                              'PermissionError)'], 'absent': []})

    def test_files_containing_through_a_patched_read(self):
        held = self.tmp / 'held.bin'
        held.write_bytes(self.NEEDLE)
        with mock.patch.object(Path, 'read_bytes', side_effect=PermissionError(13, 'Permission denied')):
            result = G.files_containing([held], [self.NEEDLE])
        self.assertEqual((result['found'], len(result['unreadable'])), ([], 1))

    def test_files_containing_reports_a_missing_tracked_file_as_absent(self):
        result = G.files_containing([self.tmp / 'deleted.txt'], [self.NEEDLE])
        self.assertEqual(result, {'found': [], 'unreadable': [], 'absent': [str(self.tmp / 'deleted.txt')]})

    def test_contains_secret_reports_an_unlisted_directory(self):
        (self.tmp / 'open').mkdir()
        (self.tmp / 'open' / 'a.log').write_bytes(b'clean')
        (self.tmp / 'denied').mkdir()
        (self.tmp / 'denied' / 'b.log').write_bytes(self.NEEDLE)
        with mock.patch.object(os, 'scandir', denying_scandir(self.tmp / 'denied')):
            result = G.contains_secret(self.tmp, [self.NEEDLE])
        self.assertEqual(result, {'found': [],
                                  'unreadable': [f'{self.tmp / "denied"} (directory not listed: PermissionError)']})

    def test_contains_secret_reports_an_unreadable_file_but_not_an_unreadable_empty_one(self):
        (self.tmp / 'LOCK').write_bytes(b'')
        (self.tmp / 'held.bin').write_bytes(b'x' * 64)
        (self.tmp / 'leak.log').write_bytes(b'a ' + self.NEEDLE.decode().encode('utf-16-le'))
        real = open

        def held_open(path, *args, **kwargs):
            if Path(path).name in ('LOCK', 'held.bin'):
                raise PermissionError(13, 'The process cannot access the file', str(path))
            return real(path, *args, **kwargs)
        with mock.patch('builtins.open', held_open):
            result = G.contains_secret(self.tmp, [self.NEEDLE])
        self.assertEqual(result, {'found': [str(self.tmp / 'leak.log')],
                                  'unreadable': [f'{self.tmp / "held.bin"} (file not read: PermissionError)']})


class TestVerifyCheckoutScan(Root):
    """Review finding 3: verify's checkout check fails on an incomplete scan, with the paths visible."""

    def setUp(self):
        super().setUp()
        self.acquire_fake()
        G.configure(self.res, self.lay, FAKE_PIN, 13300, run=FakeRun())
        gitea = {'pid': 41, 'image': str(self.lay.binary), 'in_supervisor_job_at_start': True,
                 'listeners': [{'proto': 'tcp', 'address': G.LOOPBACK, 'port': 13300, 'pid': 41}],
                 'token': {'elevated': False}}
        probes = {'sign_up_post': 403, 'sign_up_page_says_disabled': True, 'login_post_control_reached_handler': True,
                  'api /api/v1/user': 401, 'explore_users': 303}
        for name, value in (('status', {'running': True, 'gitea': gitea, 'job': {'kill_on_job_close': True}}),
                            ('sockets', []), ('anonymous_probes', probes), ('gitea_users', {}),
                            ('checkout_files', [])):
            patcher = mock.patch.object(G, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.repo = self.tmp / 'repo'
        self.repo.mkdir()
        (self.repo / 'clean.txt').write_bytes(b'clean')

    def test_a_complete_clean_scan_passes(self):
        G.checkout_files.return_value = [self.repo / 'clean.txt', self.repo / 'deleted.txt']
        result = G.verify(self.res, self.lay, FAKE_PIN)
        self.assertTrue(result['passed'], [k for k, v in result['checks'].items() if not v])
        self.assertEqual(result['checkout_scan'], {'found': [], 'unreadable': [],
                                                   'absent': [str(self.repo / 'deleted.txt')]})

    def test_an_unreadable_checkout_file_fails_the_check_with_its_path(self):
        G.checkout_files.return_value = [self.repo / 'clean.txt', UnreadablePath(self.repo / 'held.bin')]
        result = G.verify(self.res, self.lay, FAKE_PIN)
        self.assertFalse(result['checks']['no_gitea_secret_in_checkout'])
        self.assertFalse(result['passed'])
        self.assertEqual([k for k, v in result['checks'].items() if not v], ['no_gitea_secret_in_checkout'])
        self.assertEqual(result['checkout_scan']['unreadable'],
                         [f'{self.repo / "held.bin"} (file not read: PermissionError)'])
        secret = G.read_ini(self.lay.config)['security']['SECRET_KEY']
        self.assertNotIn(secret, json.dumps(result, default=str))


class TestCheckoutFiles(unittest.TestCase):
    category = 'integration'

    def test_lists_tracked_files_of_this_checkout(self):
        names = {p.relative_to(REPO).as_posix() for p in G.checkout_files(REPO)}
        self.assertIn('integrations/gitea/gitea_host.py', names)
        self.assertNotIn('config.yml', names)

    def test_the_listing_of_this_checkout_is_gits(self):
        """decision 0014 row R9: the module's listing, under the host policy, is the path set of
        git ls-files -z --cached --others --exclude-standard (git asked as the oracle)."""
        try:
            git = subprocess.run(['git', '-C', str(REPO), 'ls-files', '-z', '--cached', '--others',
                                  '--exclude-standard'], capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
        except FileNotFoundError:
            self.skipTest('git is not on PATH: the oracle comparison needs it')
        self.assertEqual(git.returncode, 0, git.stderr)
        theirs = [name for name in git.stdout.decode('utf-8').split('\0') if name]
        # A nested repository is listed as 'dir/'; checkout_files returns paths, which drop the '/'.
        mine = [p.relative_to(REPO).as_posix() for p in G.checkout_files(REPO)]
        self.assertEqual(len(mine), len(set(mine)))
        self.assertEqual(set(mine), {name.rstrip('/') for name in theirs})

    def test_never_a_strict_subset_of_gits_on_the_ignore_rule_corpus(self):
        """Negation, directory patterns, **, nested .gitignore files, info/exclude and a
        core.excludesFile, from the repository module's contract corpus with git's recorded
        listing: a path git lists and the scan does not would go unscanned."""
        corpus = _load('repository_corpus', REPO / 'integrations' / 'repository' / 'tests' / 'repository_corpus.py')
        root = corpus.corpus()
        env = {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'XDG_CONFIG_HOME': str(root / 'xdg empty'),
               'GIT_CEILING_DIRECTORIES': str(root.parent)}
        cases = {name: data for name, data in corpus.expected()['cases'].items() if name.startswith('ignore ')}
        self.assertEqual(len(cases), 10)
        with mock.patch.dict(os.environ, env):
            for name, data in sorted(cases.items()):
                (git,) = [want for cached, others, exclude, want in data['listing'] if cached and others and exclude]
                with self.subTest(case=name):
                    listed = G.checkout_files(root / name)
                    mine = {p.relative_to(root / name).as_posix() for p in listed}
                    theirs = {path.rstrip('/') for path in git}
                    self.assertEqual(theirs - mine, set())
                    self.assertEqual(mine, theirs)

    def test_an_unlistable_checkout_is_a_failure_never_an_empty_scan(self):
        # The temporary directory is git's ceiling: the search for a repository from the directory
        # inside it never examines it or anything above it.
        with tempfile.TemporaryDirectory(prefix='aieh-gitea-unlisted-') as tmp, \
                mock.patch.dict(os.environ, {'GIT_CEILING_DIRECTORIES': tmp}):
            (Path(tmp) / 'checkout').mkdir()
            with self.assertRaises(G.GiteaError) as caught:
                G.checkout_files(Path(tmp) / 'checkout')
        self.assertEqual((caught.exception.code, caught.exception.refusal), ('CHECKOUT_UNLISTED', False))


SUPERVISOR = textwrap.dedent('''
    import importlib.util, subprocess, sys, time
    spec = importlib.util.spec_from_file_location('gh', sys.argv[1])
    gh = importlib.util.module_from_spec(spec); spec.loader.exec_module(gh)
    use_job = sys.argv[2] == 'job'
    if use_job:
        job = gh.KillOnCloseJob(); job.assign_current()
    child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(600)'],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    print(child.pid, flush=True)
    sys.stdin.readline()  # exit when the test closes stdin
''')


@windows_only
class TestJobObject(unittest.TestCase):
    """The mechanism: a kill-on-close job held by the supervisor ends its child when the supervisor ends."""
    category = 'integration'

    def start(self, mode):
        script = Path(tempfile.mkdtemp(prefix='gh-')) / 'supervisor.py'
        self.addCleanup(shutil.rmtree, script.parent, ignore_errors=True)
        script.write_text(SUPERVISOR, encoding='utf-8')
        sup = subprocess.Popen([sys.executable, '-I', '-B', str(script), str(HERE.parent / 'gitea_host.py'), mode],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(sup.stdout.close)
        self.addCleanup(lambda: sup.stdin.closed or sup.stdin.close())
        self.addCleanup(lambda: sup.poll() is None and sup.kill())
        child = G.Proc(int(sup.stdout.readline()))
        self.addCleanup(lambda: child.alive() and child.terminate())
        self.assertTrue(child.alive())
        return sup, child

    def test_hard_kill_of_the_supervisor_ends_the_child(self):
        sup, child = self.start('job')
        self.assertTrue(child.in_any_job())
        sup.kill()  # TerminateProcess
        self.assertTrue(child.wait(30), 'the child outlived its killed supervisor')

    def test_clean_exit_of_the_supervisor_ends_the_child(self):
        sup, child = self.start('job')
        sup.stdin.close()
        sup.wait(30)
        self.assertTrue(child.wait(30), 'the child outlived its exited supervisor')

    def test_control_without_the_job_the_child_survives(self):
        sup, child = self.start('none')
        sup.kill()
        self.assertFalse(child.wait(1.0), 'control: without the job the child should survive')
        child.terminate()

    def test_limit_flags(self):
        job = G.KillOnCloseJob()
        self.assertEqual(job.limit_flags() & G.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, G.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        self.assertEqual(job.limit_flags() & (G.JOB_OBJECT_LIMIT_BREAKAWAY_OK | G.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK), 0)


@windows_only
class TestSocketsAndToken(unittest.TestCase):
    category = 'integration'

    def test_own_listener_and_udp_endpoint_are_seen(self):
        tcp = socket.socket()
        tcp.bind(('127.0.0.1', 0))
        tcp.listen()
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(('127.0.0.1', 0))
        try:
            rows = G.sockets(os.getpid())
            self.assertIn({'proto': 'tcp', 'family': 'ipv4', 'address': '127.0.0.1', 'port': tcp.getsockname()[1],
                           'pid': os.getpid()}, rows)
            self.assertIn({'proto': 'udp', 'family': 'ipv4', 'address': '127.0.0.1', 'port': udp.getsockname()[1],
                           'pid': os.getpid()}, rows)
            self.assertTrue(G.port_in_use(tcp.getsockname()[1]))
        finally:
            tcp.close()
            udp.close()

    def test_ipv6_listener(self):
        if not socket.has_ipv6:
            self.skipTest('no IPv6')
        tcp = socket.socket(socket.AF_INET6)
        try:
            tcp.bind(('::1', 0))
        except OSError:
            tcp.close()
            self.skipTest('::1 unavailable')
        tcp.listen()
        try:
            self.assertIn({'proto': 'tcp', 'family': 'ipv6', 'address': '::1', 'port': tcp.getsockname()[1],
                           'pid': os.getpid()}, G.sockets(os.getpid()))
        finally:
            tcp.close()

    def test_token_report(self):
        report = G.token_report(os.getpid())
        self.assertIsInstance(report['elevated'], bool)
        self.assertIn(report['elevation_type'], ('default', 'full', 'limited'))
        self.assertRegex(report['integrity_rid'], '^0x[0-9a-f]+$')

    def test_process_identity(self):
        me = G.Proc(os.getpid())
        self.assertTrue(G.Proc.maybe(os.getpid(), me.created()))
        self.assertIsNone(G.Proc.maybe(os.getpid(), me.created() + 1))
        self.assertIsNone(G.Proc.maybe(None, 0))


class TestCommandLine(unittest.TestCase):
    def test_status_before_install_refused(self):
        tmp = Path(tempfile.mkdtemp(prefix='gh-'))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        err = io.StringIO()
        with mock.patch.dict(os.environ, {'AIEH_DATA_ROOT': str(tmp / 'root')}), mock.patch('sys.stderr', err), \
                mock.patch.object(G.paths, 'load_config', return_value=None), mock.patch('sys.stdout', io.StringIO()):
            code = G.main(['status'])
        self.assertEqual(code, 2)
        self.assertIn('NOT_INSTALLED' if WINDOWS else 'Windows only', err.getvalue())
        self.assertFalse((tmp / 'root').exists())  # status creates nothing


@windows_only
@unittest.skipUnless(os.environ.get('AIEH_GITEA_BINARY'), 'set AIEH_GITEA_BINARY to a copy of the pinned binary')
class TestLive(Root):
    """The pinned Gitea end to end in a temporary root on a free port: install, up, verify, a clean down,
    up again, and a hard kill of the supervisor."""
    category = 'e2e'

    def test_lifecycle(self):
        port = next(p for p in range(23300, 23400) if not G.port_in_use(p))
        report = G.install(self.res, self.lay, PIN, port, Path(os.environ['AIEH_GITEA_BINARY']))
        self.assertEqual(report['config']['port'], port)
        with mock.patch.object(G.paths, 'resolve', return_value=self.res), \
                mock.patch.dict(os.environ, {'AIEH_DATA_ROOT': str(self.tmp / 'root')}):
            try:
                up = G.up(self.res, self.lay, PIN)
                self.assertTrue(up['running'])
                result = G.verify(self.res, self.lay, PIN)
                self.assertTrue(result['passed'], {k: v for k, v in result['checks'].items() if not v})
                stopped = G.down(self.res, self.lay, PIN)
                self.assertEqual((stopped['method'], stopped['gitea_alive'], stopped['port_open']),
                                 ('gitea manager shutdown', False, False))
                up = G.up(self.res, self.lay, PIN)
                sup, gitea = G.Proc(up['supervisor']['pid']), G.Proc(up['gitea']['pid'])
                sup.terminate()
                self.assertTrue(gitea.wait(30), 'Gitea outlived its killed supervisor')
                self.assertFalse(G.port_in_use(port))
                self.assertTrue(G.status(self.res, self.lay, PIN)['stale_record'])
            finally:
                G.down(self.res, self.lay, PIN)


if __name__ == '__main__':
    unittest.main()
