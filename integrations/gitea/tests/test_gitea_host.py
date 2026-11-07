"""Tests of the host-loopback Gitea lifecycle (plan leaf F-06.1).

Every test works in a temporary managed root named through an injected AIEH_DATA_ROOT, never the real
one. None touches the real Windows Credential Manager: the identity and first-login tests use an
in-memory store and a fake Gitea CLI. The Windows tests exercise the real Job Object, socket-table and
token code against child Python processes. The live test runs the pinned Gitea end to end on a free
port in a temporary root, only when AIEH_GITEA_BINARY names a copy of the pinned binary.
"""
from __future__ import annotations

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
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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
        run, store = FakeRun(), MemoryStore()
        report = G.create_identities(self.res, self.lay, FAKE_PIN, store=store, run=run)
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
            name, blob = store.read(target)
            self.assertEqual(name, user)
            self.assertEqual(G.password_bytes(blob), run.generated[user].encode())
            self.assertEqual(blob, run.generated[user].encode('utf-16-le'))
        text = json.dumps(report)
        for password in run.generated.values():
            self.assertNotIn(password, text)
            for argv in run.calls:
                self.assertNotIn(password, ' '.join(argv))

    def test_refusals(self):
        with self.assertRaises(G.GiteaError) as caught:
            G.create_identities(self.res, self.lay, FAKE_PIN, run=FakeRun(),
                                store=MemoryStore({G.CRED_TARGETS[G.OWNER]: ('x', b'y')}))
        self.assertEqual(caught.exception.code, 'CREDENTIAL_EXISTS')
        with self.assertRaises(G.GiteaError) as caught:
            G.create_identities(self.res, self.lay, FAKE_PIN, store=MemoryStore(), run=FakeRun({G.OWNER: False}))
        self.assertEqual(caught.exception.code, 'ACCOUNT_EXISTS')
        with mock.patch.object(G, 'healthy', return_value=False), self.assertRaises(G.GiteaError) as caught:
            G.create_identities(self.res, self.lay, FAKE_PIN, store=MemoryStore(), run=FakeRun())
        self.assertEqual(caught.exception.code, 'NOT_RUNNING')

    def test_cli_failure_withholds_output(self):
        run, store = FakeRun(password_line=True), MemoryStore()
        original = run.__call__

        def failing(argv, **kwargs):
            result = original(argv, **kwargs)
            return SimpleNamespace(returncode=1, stdout=result.stdout, stderr=b'') if 'create' in argv else result
        with self.assertRaises(G.GiteaError) as caught:
            G.create_identities(self.res, self.lay, FAKE_PIN, store=store, run=failing)
        self.assertEqual(caught.exception.code, 'ACCOUNT_CREATE_FAILED')
        self.assertNotIn(run.generated[G.SITE_ADMIN], str(caught.exception))
        self.assertEqual(store.entries, {})

    def test_missing_password_line_fails_closed(self):
        with self.assertRaises(G.GiteaError) as caught:
            G.create_identities(self.res, self.lay, FAKE_PIN, store=MemoryStore(), run=FakeRun(password_line=False))
        self.assertEqual(caught.exception.code, 'ACCOUNT_CREATE_FAILED')

    def test_user_list_parsing(self):
        users = G.gitea_users(self.lay.binary, self.lay, FakeRun({G.SITE_ADMIN: True, G.OWNER: False}))
        self.assertEqual(users, {G.SITE_ADMIN: {'admin': True}, G.OWNER: {'admin': False}})


class TestFinishFirstLogin(Root):
    PASSWORDS = {G.SITE_ADMIN: b'Temp-site-admin-Pw-9876543210', G.OWNER: b'Temp-owner-Pw-9876543210'}

    def setUp(self):
        super().setUp()
        self.acquire_fake()
        G.configure(self.res, self.lay, FAKE_PIN, 13300, run=FakeRun())
        self.store = MemoryStore({G.CRED_TARGETS[u]: (u, p.decode().encode('utf-16-le'))
                                  for u, p in self.PASSWORDS.items()})
        for name, value in (('healthy', True), ('password_authenticates', False),
                            ('checkout_files', [])):
            patcher = mock.patch.object(G, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def finish(self, flags):
        with mock.patch.object(G, 'must_change_password', return_value=flags):
            return G.finish_first_login(self.res, self.lay, FAKE_PIN, store=self.store)

    def test_pending_first_login_refused_and_entries_kept(self):
        with self.assertRaises(G.GiteaError) as caught:
            self.finish({G.SITE_ADMIN: False, G.OWNER: True})
        self.assertEqual(caught.exception.code, 'FIRST_LOGIN_PENDING')
        self.assertEqual(len(self.store.entries), 2)
        with self.assertRaises(G.GiteaError) as caught:
            self.finish({G.SITE_ADMIN: False})
        self.assertEqual(caught.exception.code, 'ACCOUNTS_MISSING')

    def test_active_temporary_password_refused(self):
        with mock.patch.object(G, 'password_authenticates', return_value=True), self.assertRaises(G.GiteaError) as c:
            self.finish({G.SITE_ADMIN: False, G.OWNER: False})
        self.assertEqual(c.exception.code, 'TEMPORARY_PASSWORD_ACTIVE')
        self.assertEqual(len(self.store.entries), 2)

    def test_password_found_in_a_file_refused_by_name_only(self):
        for form in (self.PASSWORDS[G.OWNER], self.PASSWORDS[G.OWNER].decode().encode('utf-16-le')):
            leak = self.lay.logs / 'leak.log'
            leak.write_bytes(b'x' * (1 << 20) + form + b'y')  # across the 1 MiB read boundary
            with self.assertRaises(G.GiteaError) as caught:
                self.finish({G.SITE_ADMIN: False, G.OWNER: False})
            self.assertEqual(caught.exception.code, 'TEMPORARY_PASSWORD_FOUND')
            self.assertIn('leak.log', str(caught.exception))
            self.assertNotIn(self.PASSWORDS[G.OWNER].decode(), str(caught.exception))
            self.assertEqual(len(self.store.entries), 2)
            leak.unlink()

    def test_success_deletes_both_entries(self):
        report = self.finish({G.SITE_ADMIN: False, G.OWNER: False})
        self.assertEqual(report['found_in_managed_root'], [])
        self.assertEqual(sorted(report['deleted']), sorted(G.CRED_TARGETS.values()))
        self.assertEqual((report['entries_remaining'], self.store.entries), ([], {}))
        for password in self.PASSWORDS.values():
            self.assertNotIn(password.decode(), json.dumps(report))

    def test_checkout_search(self):
        repo = self.tmp / 'repo'
        repo.mkdir()
        (repo / 'tracked.txt').write_bytes(b'a ' + self.PASSWORDS[G.SITE_ADMIN] + b' b')
        self.assertEqual(G.files_containing([repo / 'tracked.txt'], [self.PASSWORDS[G.SITE_ADMIN]]),
                         [str(repo / 'tracked.txt')])
        self.assertEqual(G.files_containing([repo / 'tracked.txt'], [self.PASSWORDS[G.OWNER]]), [])


class TestCheckoutFiles(unittest.TestCase):
    def test_lists_tracked_files_of_this_checkout(self):
        names = {p.relative_to(REPO).as_posix() for p in G.checkout_files(REPO)}
        self.assertIn('integrations/gitea/gitea_host.py', names)
        self.assertNotIn('config.yml', names)


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
