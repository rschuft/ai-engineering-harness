"""Tests of the managed data root resolver (plan leaf F-07.1, decision 0009).

Every test injects its environment and a temporary repository anchor. None reads the real
LOCALAPPDATA, creates anything at a volume root, or reads the checkout's config.yml. The tests
that need PyYAML skip, counted, when it is not importable: run them under the tools venv
(task tools:install). The criterion numbers are those of the Owner directive's section 9.
"""
from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
PATHS_DIR = HERE.parent
REPO = PATHS_DIR.parents[1]
EXAMPLE = REPO / 'example_config.yml'
WINDOWS = sys.platform == 'win32'
BS = chr(92)


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


P = _load('aieh_paths', PATHS_DIR / 'aieh_paths.py')
T = _load('aieh_tools_install', PATHS_DIR / 'tools_install.py')
storecore = _load('aieh_storecore', REPO / 'integrations' / 'storecore' / 'storecore.py')
gate = _load('aieh_publication_gate_for_paths', REPO / 'tools' / 'publication_gate.py')

try:
    import yaml  # noqa: F401
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False
needs_yaml = unittest.skipUnless(HAVE_YAML, 'PyYAML is not importable; run under the tools venv (task tools:install)')

# Literal anchors for platforms other than the host: generic, never a real machine path.
FOREIGN = {
    'win32': ('C:/src/aieh', {'LOCALAPPDATA': 'C:/profile/AppData/Local', 'USERPROFILE': 'C:/profile'}),
    'linux': ('/srv/src/aieh', {'HOME': '/home/user'}),
    'darwin': ('/srv/src/aieh', {'HOME': '/home/user'}),
}
CATEGORY_LINES = {name: f'#{name}: {category.default}' for name, category in P.CATEGORIES.items()}


class Base(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='aieh-paths-'))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.repo = self.base / 'checkout'
        self.repo.mkdir()
        profile = self.base / 'profile'
        self.env = {'LOCALAPPDATA': str(profile / 'AppData' / 'Local'), 'APPDATA': str(profile / 'AppData' / 'Roaming'),
                    'USERPROFILE': str(profile), 'HOME': str(profile)}

    def resolve(self, env=None, **kwargs):
        return P.resolve(self.env if env is None else env, repo_root=self.repo, **kwargs)

    def rooted(self, root):
        return dict(self.env, AIEH_DATA_ROOT=str(root))

    def tree(self):
        return sorted(str(p.relative_to(self.base)) for p in self.base.rglob('*'))

    def case(self, platform):
        """(environ, repository anchor) for a platform: temporary ones on the host, literals elsewhere."""
        if platform == sys.platform:
            return dict(self.env), self.repo
        repo, env = FOREIGN[platform]
        return dict(env), repo

    def assertRefused(self, code, func, *args, **kwargs):
        with self.assertRaises(P.PathsError) as caught:
            func(*args, **kwargs)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertEqual(caught.exception.remedy, P.REMEDIES[code])
        self.assertIn('Remedy: ' + P.REMEDIES[code], str(caught.exception))
        return caught.exception

    def clone(self):
        """A temporary clone holding the resolver, so its repository anchor is that clone."""
        clone = self.base / 'clone'
        for rel in ('integrations/paths/aieh_paths.py', 'integrations/storecore/storecore.py'):
            (clone / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, clone / rel)
        return clone

    def run_cli(self, clone, cwd, env, *args):
        child_env = dict(env, SYSTEMROOT=os.environ['SYSTEMROOT']) if WINDOWS else dict(env)
        return subprocess.run([sys.executable, '-I', '-B', str(clone / 'integrations/paths/aieh_paths.py'), *args],
                              cwd=cwd, env=child_env, capture_output=True, timeout=60)


class SectionNineCriteria(Base):
    category = 'integration'

    def test_c1_fresh_clone_without_config_or_env_resolves_and_creates_nothing(self):
        before = self.tree()
        for fmt in ('json', 'sh', 'ps1'):
            out, err = io.StringIO(), io.StringIO()
            self.assertEqual(P.main(['show', '--format', fmt], environ=self.env, repo_root=self.repo, out=out, err=err),
                             0, err.getvalue())
            root = str(self.resolve().root)
            if fmt == 'json':
                self.assertEqual((json.loads(out.getvalue())['root'], json.loads(out.getvalue())['root_source']),
                                 (root, 'default'))
            else:
                self.assertIn(root, out.getvalue())
        if WINDOWS:
            self.assertEqual(root, str(Path(self.env['LOCALAPPDATA']) / 'AIEH'))
        self.assertEqual(self.tree(), before)
        self.assertFalse((self.repo / 'config.yml').exists())

    def test_c1_dotenv_is_never_read(self):
        (self.repo / '.env').write_text(f'AIEH_DATA_ROOT={self.base / "from-dotenv"}\n', encoding='utf-8')
        res = self.resolve()
        self.assertEqual(res.root_source, 'default')
        self.assertNotIn('from-dotenv', str(res.root))

    def test_c2_default_lies_outside_the_checkout_on_every_platform(self):
        for platform in ('win32', 'linux', 'darwin'):
            with self.subTest(platform=platform):
                env, repo = self.case(platform)
                res = P.resolve(env, platform=platform, repo_root=repo)
                anchor = P._norm(platform, repo)
                for path in [res.root, *res.paths.values()]:
                    self.assertFalse(P._overlaps(path, anchor), path)
                profile = env['LOCALAPPDATA'] if platform == 'win32' else env['HOME']
                self.assertTrue(res.root.is_relative_to(P._norm(platform, profile)))

    def test_c3_platform_conventions(self):
        env, repo = self.case('win32')
        self.assertEqual(P.resolve(env, platform='win32', repo_root=repo).root,
                         PureWindowsPath(env['LOCALAPPDATA'], 'AIEH'))
        env, repo = self.case('linux')
        self.assertEqual(P.resolve(env, platform='linux', repo_root=repo).root,
                         PurePosixPath(env['HOME'], '.local', 'share', 'aieh'))
        self.assertEqual(P.resolve(dict(env, XDG_DATA_HOME='/srv/data'), platform='linux', repo_root=repo).root,
                         PurePosixPath('/srv/data/aieh'))
        self.assertEqual(P.resolve(dict(env, XDG_DATA_HOME='relative/data'), platform='linux', repo_root=repo).root,
                         PurePosixPath(env['HOME'], '.local', 'share', 'aieh'), 'a relative XDG_DATA_HOME is ignored')
        env, repo = self.case('darwin')
        self.assertEqual(P.resolve(dict(env, XDG_DATA_HOME='/srv/data'), platform='darwin', repo_root=repo).root,
                         PurePosixPath(env['HOME'], 'Library', 'Application Support', 'aieh'))
        for platform in ('win32', 'linux', 'darwin'):
            env, repo = self.case(platform)
            res = P.resolve(env, platform=platform, repo_root=repo)
            tops = {path.relative_to(res.root).parts[0] for path in res.paths.values()}
            self.assertEqual(tops, set(P.LIFECYCLES))
            for name, path in res.paths.items():
                self.assertEqual(path, P._norm(platform, res.root / P.CATEGORIES[name].default))
                self.assertEqual(path.relative_to(res.root).parts[0], P.CATEGORIES[name].lifecycle)

    def test_c4_data_root_relocates_the_whole_root_and_leaves_external_unchanged(self):
        external = {'effects_root': str(self.base / 'effects'), 'guest_state': str(self.base / 'guests')}
        config = {'version': 1, 'paths': external}
        default = self.resolve(config=config)
        moved = self.resolve(self.rooted(self.base / 'elsewhere'), config=config)
        self.assertEqual(moved.root_source, 'env')
        self.assertEqual(moved.root, P._norm(sys.platform, self.base / 'elsewhere'))
        for name, path in moved.paths.items():
            self.assertTrue(path.is_relative_to(moved.root), name)
            self.assertEqual(path.relative_to(moved.root), default.paths[name].relative_to(default.root))
        self.assertEqual(moved.external, default.external)
        self.assertEqual(moved.to_json()['external'], {k: str(P._norm(sys.platform, v)) for k, v in external.items()})

    def test_c5_relative_root_resolves_against_the_clone_from_any_cwd(self):
        clone = self.clone()
        env = dict(self.env, AIEH_DATA_ROOT='../aieh-data')
        expected = str(P._norm(sys.platform, Path(os.path.realpath(clone)).parent / 'aieh-data'))
        for cwd in (self.base, self.repo, clone / 'integrations'):
            with self.subTest(cwd=cwd):
                done = self.run_cli(clone, cwd, env, 'show')
                self.assertEqual(done.returncode, 0, done.stderr)
                data = json.loads(done.stdout)
                self.assertEqual((data['root'], data['root_source']), (expected, 'env-relative'))
        previous = os.path.realpath(os.curdir)
        self.addCleanup(os.chdir, previous)
        roots = set()
        for cwd in (self.base, self.repo):
            os.chdir(cwd)
            roots.add(self.resolve(env).root)
        self.assertEqual(roots, {P._norm(sys.platform, self.base / 'aieh-data')})

    def test_c6_relative_override_resolves_against_the_effective_root(self):
        config = {'version': 1, 'paths': {'logs': 'logs-elsewhere', 'cache': '../shared-cache'}}
        res = self.resolve(self.rooted(self.base / 'root'), config=config)
        self._check_relative_overrides(res)

    @needs_yaml
    def test_c6_relative_override_from_config_yml(self):
        (self.repo / 'config.yml').write_text('version: 1\npaths:\n  logs: logs-elsewhere\n  cache: ../shared-cache\n',
                                              encoding='utf-8')
        self._check_relative_overrides(self.resolve(self.rooted(self.base / 'root')))

    def _check_relative_overrides(self, res):
        root = P._norm(sys.platform, self.base / 'root')
        data = res.to_json()['paths']
        self.assertEqual(res.paths['logs'], root / 'logs-elsewhere')
        self.assertEqual((data['logs']['source'], data['logs']['outside_root']), ('config', False))
        self.assertEqual(res.paths['cache'], P._norm(sys.platform, self.base / 'shared-cache'))
        self.assertEqual((data['cache']['source'], data['cache']['outside_root']), ('config', True))
        self.assertTrue(any('paths.cache' in warning for warning in res.warnings))
        self.assertEqual(data['state']['source'], 'root')

    def test_c7_absolute_override_is_used_as_given(self):
        target = self.base / 'state-volume' / 'aieh-state'
        res = self.resolve(config={'version': 1, 'paths': {'state': str(target)}})
        self.assertEqual(res.paths['state'], P._norm(sys.platform, target))

    @needs_yaml
    def test_c7_absolute_override_from_config_yml(self):
        target = self.base / 'state-volume' / 'aieh-state'
        (self.repo / 'config.yml').write_text(f'version: 1\npaths:\n  state: {json.dumps(str(target))}\n',
                                              encoding='utf-8')
        res = self.resolve(self.rooted(self.base / 'root'))
        self.assertEqual((res.paths['state'], res.sources['state']), (P._norm(sys.platform, target), 'config'))
        self.assertTrue(res.outside_root('state'))

    def test_c8_identical_json_from_two_working_directories(self):
        clone = self.clone()
        (self.base / 'cwd-a').mkdir()
        (self.base / 'cwd-b' / 'deeper').mkdir(parents=True)
        for env in (self.env, dict(self.env, AIEH_DATA_ROOT='../aieh-data')):
            outputs = {self.run_cli(clone, self.base / cwd, env, 'show').stdout for cwd in ('cwd-a', 'cwd-b/deeper')}
            self.assertEqual(len(outputs), 1)
            self.assertEqual(json.loads(outputs.pop())['format'], 'aieh-paths/v1')

    def test_c8_the_sources_never_consult_the_working_directory_or_delete(self):
        for module in ('aieh_paths.py', 'tools_install.py'):
            source = (PATHS_DIR / module).read_text(encoding='utf-8')
            for needle in ('getcwd', 'Path.cwd', '.cwd(', 'abspath', '.absolute(', 'chdir', "'.env'", 'dotenv',
                           'rmtree', 'remove(', 'unlink', 'rmdir', 'rename', 'os.replace', 'makedirs'):
                self.assertNotIn(needle, source, f'{module} uses {needle}')

    def test_c10_ensure_never_creates_a_direct_child_of_a_volume_root(self):
        anchor = Path(self.base.anchor)
        for config in (None, {'version': 1, 'paths': {'scratch': str(anchor / 'aieh-f071-never-created-scratch')}}):
            with self.subTest(config=config), mock.patch('os.path.realpath', side_effect=lambda p, **_: p), \
                    mock.patch.object(P, '_drive_type', return_value=3):
                env = self.rooted(anchor / 'aieh-f071-never-created') if config is None else self.env
                res = self.resolve(env, config=config or {})
                with mock.patch('os.path.isdir', return_value=False), mock.patch('os.mkdir') as mkdir:
                    self.assertRefused('DRIVE_ROOT_CREATE', P.ensure, 'scratch', res)
                mkdir.assert_not_called()

    def test_c10_only_init_may_create_a_root_directly_below_a_volume_root(self):
        anchor = Path(self.base.anchor)
        root = anchor / 'aieh-f071-never-created'
        with mock.patch('os.path.isdir', side_effect=lambda p: Path(p) == anchor), mock.patch('os.mkdir') as mkdir:
            self.assertRefused('DRIVE_ROOT_CREATE', P._make, root, root / 'persistent', volume_child_ok=False)
            mkdir.assert_not_called()
            self.assertEqual(P._make(root, root, volume_child_ok=True), [str(root)])
            mkdir.assert_called_once_with(root) if WINDOWS else mkdir.assert_called_once_with(root, 0o700)

    def test_c10_init_creates_exactly_the_lifecycle_directories_and_the_marker(self):
        root = self.base / 'data-root'
        res = self.resolve(self.rooted(root))
        before = set(self.tree())
        result = P.init(res)
        expected = {root, root / 'aieh-root.json', root / 'persistent', root / 'ephemeral', root / 'assets'}
        self.assertEqual({Path(p) for p in result['created']}, expected)
        self.assertEqual(set(self.tree()) - before, {str(p.relative_to(self.base)) for p in expected})
        text = (root / 'aieh-root.json').read_text(encoding='utf-8')
        marker = json.loads(text)
        self.assertEqual(set(marker), {'format', 'created_at', 'resolver_version'})
        self.assertEqual(marker['format'], 'aieh-root/1')
        self.assertNotIn(str(self.repo), text)
        self.assertNotIn(self.repo.name, text)
        self.assertEqual(P.init(res)['created'], [])
        self.assertEqual(P.doctor(res, self.env)['marker'], 'present')

    def test_c10_ensure_creates_below_the_root_and_never_above_it(self):
        root = self.base / 'data-root'
        res = self.resolve(self.rooted(root))
        self.assertEqual(P.ensure('state', res, 'integration'), Path(str(root)) / 'persistent' / 'state' / 'integration')
        self.assertEqual(set(self.tree()), {'checkout', 'data-root', str(Path('data-root/persistent')),
                                            str(Path('data-root/persistent/state')),
                                            str(Path('data-root/persistent/state/integration'))})
        outside = self.resolve(self.rooted(root), config={'version': 1, 'paths': {'scratch': '../aieh-scratch'}})
        self.assertEqual(P.ensure('scratch', outside), self.base / 'aieh-scratch')
        missing = self.resolve(self.rooted(self.base / 'no-parent' / 'root'))
        before = self.tree()
        self.assertRefused('ROOT_PARENT_MISSING', P.ensure, 'state', missing)
        self.assertRefused('ROOT_PARENT_MISSING', P.init, missing)
        self.assertEqual(self.tree(), before)
        with self.assertRaises(KeyError):
            P.ensure('effects_root', res)
        for part in ('..', '.', 'a/b', 'a' + BS + 'b', ''):
            with self.assertRaises(ValueError):
                P.ensure('state', res, part)
        env, repo = self.case('linux' if WINDOWS else 'win32')
        with self.assertRaises(ValueError):
            P.ensure('state', P.resolve(env, platform='linux' if WINDOWS else 'win32', repo_root=repo))


class InvalidConfiguration(Base):
    """Criterion 9: each refusal has a stable code and names its remedy."""
    category = 'integration'

    def cases(self):
        env, repo, base = self.env, self.repo, self.base
        anchor = base.anchor
        unc = BS * 2 + 'server' + BS + 'share' + BS + 'aieh' if WINDOWS else '//server/share/aieh'
        root = self.rooted

        def with_config(config, environ=None):
            return lambda: P.resolve(env if environ is None else environ, repo_root=repo, config=config)

        def with_paths(paths):
            return with_config({'version': 1, 'paths': paths})
        win_env, win_repo = self.case('win32')
        yield 'DEFAULT_ROOT_UNAVAILABLE', lambda: P.resolve({}, repo_root=repo)
        yield 'DEFAULT_ROOT_UNAVAILABLE', lambda: P.resolve({'LOCALAPPDATA': 'relative'}, platform='win32',
                                                            repo_root=win_repo)
        yield 'DEFAULT_ROOT_UNAVAILABLE', lambda: P.resolve({'HOME': 'relative'}, platform='linux', repo_root='/srv/x')
        yield 'ROOT_NOT_ABSOLUTE_AFTER_ANCHOR', lambda: P.resolve(dict(win_env, AIEH_DATA_ROOT='Z:data'),
                                                                  platform='win32', repo_root=win_repo)
        yield 'ROOT_NOT_ABSOLUTE_AFTER_ANCHOR', lambda: P.resolve(dict(win_env, AIEH_DATA_ROOT=BS + 'data'),
                                                                  platform='win32', repo_root=win_repo)
        yield 'ROOT_IS_DRIVE_ROOT', with_config({}, root(anchor))
        for var in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME'):
            yield 'ROOT_IS_PROFILE_ROOT', with_config({}, root(env[var]))
        yield 'ROOT_INSIDE_CHECKOUT', with_config({}, root('data'))
        yield 'ROOT_INSIDE_CHECKOUT', with_config({}, root('.'))
        yield 'ROOT_INSIDE_CHECKOUT', with_config({}, root(base))
        yield 'ROOT_UNC_OR_NETWORK', with_config({}, root(unc))
        yield 'CONFIG_UNREADABLE', self._config_directory
        yield 'CONFIG_NEEDS_YAML', self._yaml_hidden
        yield 'CONFIG_NOT_A_MAPPING', with_config(['a list'])
        yield 'CONFIG_NOT_A_MAPPING', with_config({'version': 1, 'paths': ['state']})
        yield 'CONFIG_NOT_A_MAPPING', with_config({'version': 1, 'components': {'gitea': 'not a mapping'}})
        for version in (2, True, '1', None):
            yield 'CONFIG_VERSION_UNSUPPORTED', with_config({'version': version, 'paths': {}})
        yield 'CONFIG_UNKNOWN_KEY', with_config({'version': 1, 'extra': 1})
        yield 'CONFIG_UNKNOWN_KEY', with_config({'version': 1, 'data_root': '/srv/aieh'})
        yield 'CONFIG_UNKNOWN_KEY', with_paths({'data_root': '/srv/aieh'})
        yield 'CONFIG_UNKNOWN_KEY', with_paths({'databases': 'x'})
        for value in (5, '', '   ', None, ['x'], 'a' + chr(0)):
            yield 'CONFIG_PATH_TYPE', with_paths({'state': value})
        yield 'CONFIG_PATH_TYPE', with_paths({'effects_root': 'relative/effects'})
        if WINDOWS:
            yield 'CONFIG_PATH_TYPE', with_paths({'state': BS + 'rooted'})
            yield 'CONFIG_PATH_TYPE', with_paths({'state': 'Z:drive-relative'})
        yield 'CONFIG_SECRET_SHAPED_KEY', with_config({'version': 1, 'components': {'gitea': {'admin_token': 'x'}}})
        yield 'CONFIG_SECRET_SHAPED_KEY', with_config({'version': 1, 'password': 'x'})
        yield 'CONFIG_SECRET_SHAPED_KEY', with_config({'version': 1, 'components': {'a': {'l': [{'Api_Key': 1}]}}})
        yield 'CONFIG_SECRET_SHAPED_KEY', with_config({'version': 1, 'components': {'b': {'credentials': {}}}})
        yield 'PATH_INSIDE_CHECKOUT', with_paths({'state': str(repo / 'state')})
        yield 'PATH_INSIDE_CHECKOUT', with_paths({'cache': str(base)})
        yield 'PATH_IS_DRIVE_ROOT', with_paths({'tmp': anchor})
        yield 'PATH_OVERLAP', with_paths({'cache': 'persistent'})
        yield 'PATH_OVERLAP', with_paths({'logs': 'persistent/state/logs'})
        yield 'PATH_OVERLAP', with_paths({'tmp': '.'})
        yield 'PATH_NETWORK_FOR_STORE', with_paths({'state': unc})
        yield 'PATH_NETWORK_FOR_STORE', with_paths({'gitea': unc})
        yield 'DRIVE_ROOT_CREATE', self._drive_root_create
        yield 'ROOT_PARENT_MISSING', lambda: P.ensure('logs', self.resolve(root(base / 'gone' / 'root')))
        yield 'ROOT_MARKER_MISMATCH', self._marker_mismatch
        yield 'LOCATION_MANAGED_ROOT', lambda: P.check_effects_root(base / 'r' / 'effects', self.resolve(root(base / 'r')))
        yield 'LOCATION_MANAGED_ROOT', lambda: P.check_effects_root(base, self.resolve(root(base / 'r')))
        yield 'ASSET_RECORD_INVALID', lambda: P.check_asset_record({'format': 'aieh-asset/0'})

    def _config_directory(self):
        (self.repo / 'config.yml').mkdir()
        try:
            self.resolve()
        finally:
            (self.repo / 'config.yml').rmdir()

    def _yaml_hidden(self):
        (self.repo / 'config.yml').write_text('version: 1\n', encoding='utf-8')
        try:
            with mock.patch.dict(sys.modules, {'yaml': None}):
                self.resolve()
        finally:
            (self.repo / 'config.yml').unlink()

    def _drive_root_create(self):
        with mock.patch('os.path.realpath', side_effect=lambda p, **_: p), \
                mock.patch.object(P, '_drive_type', return_value=3):
            res = self.resolve(self.rooted(Path(self.base.anchor) / 'aieh-f071-never-created'))
        with mock.patch('os.path.isdir', return_value=False), mock.patch('os.mkdir') as mkdir:
            try:
                P.ensure('tmp', res)
            finally:
                mkdir.assert_not_called()

    def _marker_mismatch(self):
        res = self.resolve(self.rooted(self.base / 'marked'))
        P.init(res)
        (self.base / 'marked' / 'aieh-root.json').write_text('{"format": "aieh-root/0"}\n', encoding='utf-8')
        try:
            P.ensure('tmp', res)
        finally:
            self.assertRefused('ROOT_MARKER_MISMATCH', P.init, res)

    def test_c9_every_code_is_refused_with_its_remedy(self):
        seen = set()
        for index, (code, func) in enumerate(self.cases()):
            with self.subTest(index=index, code=code):
                self.assertRefused(code, func)
                seen.add(code)
        self.assertEqual(seen, set(P.REMEDIES), 'every code has a test')

    @unittest.skipUnless(WINDOWS, 'volume types are checked on Windows')
    def test_c9_network_or_non_fixed_volumes_by_drive_type(self):
        for kind in P.NON_FIXED:
            with self.subTest(kind=kind):
                with mock.patch.object(P, '_drive_type', return_value=kind):
                    self.assertRefused('ROOT_UNC_OR_NETWORK', self.resolve)
                with mock.patch.object(P, '_drive_type', side_effect=[storecore.DRIVE_FIXED, kind]):
                    self.assertRefused('PATH_NETWORK_FOR_STORE', self.resolve)

    def test_c9_messages_name_the_custody_and_never_a_secret_value(self):
        error = self.assertRefused('CONFIG_SECRET_SHAPED_KEY', self.resolve,
                                   config={'version': 1, 'components': {'gitea': {'admin_token': 'VALUE-1234'}}})
        self.assertIn('components.gitea.admin_token', str(error))
        self.assertIn('decision 0007', str(error))
        self.assertNotIn('VALUE-1234', str(error))
        error = self.assertRefused('CONFIG_UNKNOWN_KEY', self.resolve, config={'version': 1, 'data_root': 'x'})
        self.assertIn('AIEH_DATA_ROOT', str(error))
        error = self.assertRefused('CONFIG_UNKNOWN_KEY', self.resolve, config={'version': 1, 'paths': {'db': 'x'}})
        for name in P.CATEGORIES:
            self.assertIn(name, str(error))

    def test_c9_cli_reports_the_code_and_remedy_and_exits_2(self):
        out, err = io.StringIO(), io.StringIO()
        code = P.main(['show'], environ=self.rooted('.'), repo_root=self.repo, out=out, err=err)
        self.assertEqual((code, out.getvalue()), (2, ''))
        self.assertIn('ROOT_INSIDE_CHECKOUT', err.getvalue())
        self.assertIn(P.REMEDIES['ROOT_INSIDE_CHECKOUT'], err.getvalue())

    @unittest.skipUnless(WINDOWS, 'directory junctions are a Windows mechanism')
    def test_c9_a_junction_into_the_checkout_is_refused_after_the_lexical_checks(self):
        link = self.base / 'junction'
        done = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(self.repo)], capture_output=True)
        if done.returncode != 0:
            self.skipTest('mklink /J is unavailable')
        self.assertRefused('ROOT_INSIDE_CHECKOUT', self.resolve, self.rooted(link / 'data'))

    @needs_yaml
    def test_c9_unreadable_yaml_reports_only_the_line(self):
        (self.repo / 'config.yml').write_text('version: 1\npaths: [unclosed SECRETVALUE\n', encoding='utf-8')
        error = self.assertRefused('CONFIG_UNREADABLE', self.resolve)
        self.assertNotIn('SECRETVALUE', str(error))
        (self.repo / 'config.yml').write_text('version: 1\nkey_material: x\n', encoding='utf-8')
        self.assertRefused('CONFIG_SECRET_SHAPED_KEY', self.resolve)


class Adapters(Base):
    category = 'integration'

    TRICKY = "it's $HOME `x` & (dir)"

    def resolution(self):
        return self.resolve(self.rooted(self.base / self.TRICKY),
                            config={'version': 1, 'paths': {'effects_root': str(self.base / 'fx')}})

    def expected(self, res):
        values = {'AIEH_PATH_ROOT': str(res.root), 'AIEH_PATH_EFFECTS_ROOT': str(res.external['effects_root'])}
        values.update({'AIEH_PATH_' + name.upper(): str(path) for name, path in res.paths.items()})
        return values

    def test_emitters_quote_every_value(self):
        res = self.resolution()
        sh, ps1 = P.emit(res, 'sh'), P.emit(res, 'ps1')
        self.assertIn("export AIEH_PATH_ROOT='" + str(res.root).replace("'", "'" + BS + "''") + "'", sh)
        self.assertIn("$env:AIEH_PATH_ROOT = '" + str(res.root).replace("'", "''") + "'", ps1)
        self.assertNotIn('AIEH_PATH_GUEST_STATE', sh, 'an unset external location is not emitted')
        self.assertNotIn('AIEH_DATA_ROOT', sh + ps1, 'adapters never feed the override back')
        curly = P.Resolution(PureWindowsPath('C:/a' + chr(0x2019) + 'b'), 'env', PureWindowsPath('C:/src'), 'win32',
                             {}, {}, {}, {}, [])
        self.assertIn("'C:" + BS + 'a' + chr(0x2019) * 2 + "b'", P.emit(curly, 'ps1'))

    def run_shell(self, argv, adapter, timeout, **kwargs):
        """Run an adapter's shell by name; a shell that is not on PATH skips the test.

        The launch is attempted in every environment (a failed attempt still counts as a
        launch), so the counted launches of the F-09.1 test budgets do not depend on which
        shells PATH holds: PowerShell on Windows has no sh, Git Bash has one."""
        try:
            return subprocess.run(argv, capture_output=True, timeout=timeout, **kwargs)
        except FileNotFoundError:
            self.skipTest(f'no {argv[0]} on PATH: the {adapter} adapter round trip is unknown here')

    def test_sh_round_trip(self):
        res = self.resolution()
        expected = self.expected(res)
        script = P.emit(res, 'sh') + ''.join(f'printf "%s|" "${key}"\n' for key in expected)
        done = self.run_shell(['sh', '-s'], 'sh', 60, input=script.encode('utf-8'))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.decode('utf-8').split('|')[:-1], list(expected.values()))

    def test_ps1_round_trip(self):
        res = self.resolution()
        expected = self.expected(res)
        script = ('[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n' + P.emit(res, 'ps1')
                  + ''.join(f'[Console]::Out.Write($env:{key} + "|")\n' for key in expected))
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        done = self.run_shell(['pwsh', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], 'ps1', 120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.decode('utf-8').split('|')[:-1], list(expected.values()))


class LegacyAndDoctor(Base):
    def test_legacy_table_matches_the_former_defaults(self):
        rows = {row['name']: row for row in P.legacy_locations(self.env, sys.platform)}
        self.assertEqual(rows['integration-store']['path'],
                         str(storecore.harness_state_root(self.env, sys.platform) / 'state'))
        self.assertEqual(rows['gitleaks-cache']['path'], str(gate.tool_dir(self.env).parent))
        posix = {row['name']: row['path'] for row in P.legacy_locations({'HOME': '/home/user'}, 'linux')}
        self.assertEqual(posix, {'integration-store': '/home/user/.local/share/ai-engineering-harness/state',
                                 'gitleaks-cache': '/home/user/.cache/ai-engineering-harness/tools/gitleaks'})
        xdg = {'HOME': '/home/user', 'XDG_DATA_HOME': '/srv/d', 'XDG_CACHE_HOME': '/srv/c'}
        self.assertEqual([row['path'] for row in P.legacy_locations(xdg, 'linux')],
                         ['/srv/d/ai-engineering-harness/state', '/srv/c/ai-engineering-harness/tools/gitleaks'])
        self.assertEqual([row['path'] for row in P.legacy_locations({}, 'win32')], [None, None])
        for row in rows.values():
            self.assertIn('Owner act', row['migration'])
            self.assertIn(row['classification'], ('service database', 'installed binary (regenerable)'))

    def test_doctor_reports_and_moves_nothing(self):
        legacy = Path(P.legacy_locations(self.env, sys.platform)[0]['path'])
        legacy.mkdir(parents=True)
        (legacy / 'integration.sqlite').write_bytes(b'not a real store')
        root = self.base / 'data-root'
        res = self.resolve(self.rooted(root), config={'version': 1, 'paths': {'effects_root': str(root / 'fx')}})
        before = self.tree()
        report = P.doctor(res, self.env)
        self.assertEqual(self.tree(), before)
        self.assertEqual((report['format'], report['root_exists'], report['marker']), ('aieh-paths-doctor/1', False,
                                                                                       'missing'))
        self.assertEqual(report['effects_root_check'], 'LOCATION_MANAGED_ROOT')
        self.assertTrue(any('paths:init' in warning for warning in report['warnings']))
        legacy_rows = {row['name']: row['exists'] for row in report['legacy']}
        self.assertEqual(legacy_rows, {'integration-store': True, 'gitleaks-cache': False})
        self.assertEqual([row['name'] for row in report['categories']], list(P.CATEGORIES))
        for row in report['categories']:
            category = P.CATEGORIES[row['name']]
            self.assertEqual((row['lifecycle'], row['class'], row['layout'], row['creator'], row['consumer']),
                             (category.lifecycle, category.cls, category.layout, category.creator, category.consumer))
        P.init(res)
        self.assertEqual(P.doctor(res, self.env)['marker'], 'present')
        out = io.StringIO()
        self.assertEqual(P.main(['doctor'], environ=self.rooted(root), repo_root=self.repo, out=out), 0)
        self.assertEqual(json.loads(out.getvalue())['root'], str(root))

    def test_category_table(self):
        self.assertEqual(set(P.CATEGORIES), {'state', 'gitea', 'installs', 'logs', 'workspaces', 'assets', 'cache',
                                             'scratch', 'tmp'})
        for name, category in P.CATEGORIES.items():
            self.assertEqual(category.default.split('/')[0], category.lifecycle, name)
            self.assertIn(category.cls, 'BCDE', name)
            self.assertTrue(category.creator and category.consumer, name)
        self.assertEqual(P.STORE_CATEGORIES, {'state', 'gitea'})
        self.assertEqual(P.EXTERNAL, ('effects_root', 'guest_state'))
        res = self.resolve(config={'version': 1, 'paths': {'effects_root': str(self.base / 'fx')}})
        P.check_effects_root(self.base / 'fx', res)  # outside the managed root: accepted


class ExampleConfiguration(Base):
    category = 'contract'

    TEXT = EXAMPLE.read_text(encoding='utf-8')

    @staticmethod
    def uncommented(text):
        lines = []
        for line in text.splitlines():
            stripped = line.lstrip(' ')
            if stripped.startswith('#') and stripped[1:2].isalpha():
                line = line[:len(line) - len(stripped)] + stripped[1:]
            lines.append(line)
        return '\n'.join(lines) + '\n'

    def test_example_shows_every_category_default_commented_out(self):
        for name, line in CATEGORY_LINES.items():
            self.assertIn('  ' + line + '\n', self.TEXT, name)
        for name in P.EXTERNAL:
            self.assertIn(f'  # {name}: /absolute/path/named/by/the/Owner\n', self.TEXT)

    def test_example_is_secret_free_and_has_no_drive_path(self):
        for number, line in enumerate(self.TEXT.splitlines(), 1):
            key = line.strip().lstrip('#').strip().split(':', 1)[0]
            if ':' in line and key.isidentifier():
                self.assertIsNone(P.SECRET_SHAPED.search(key), f'line {number}: {key}')
            for index in range(len(line) - 2):
                self.assertFalse(line[index].isalpha() and line[index + 1] == ':' and line[index + 2] in ('/', BS)
                                 and (index == 0 or not line[index - 1].isalnum()), f'drive path on line {number}')
            self.assertNotIn('Users' + BS, line)
            self.assertNotIn('/home/', line)

    def test_gitignore_ignores_config_yml(self):
        self.assertIn('config.yml', (REPO / '.gitignore').read_text(encoding='utf-8').splitlines())

    @needs_yaml
    def test_example_copied_as_config_yml_resolves_to_the_defaults(self):
        default = self.resolve()
        (self.repo / 'config.yml').write_text(self.TEXT, encoding='utf-8')
        res = self.resolve()
        self.assertEqual((res.paths, set(res.sources.values()), res.external), (default.paths, {'root'},
                                                                                 default.external))
        (self.repo / 'config.yml').write_text(self.uncommented(self.TEXT), encoding='utf-8')
        res = self.resolve()
        self.assertEqual((res.paths, set(res.sources.values())), (default.paths, {'config'}))
        P.validate_config(yaml.safe_load(self.uncommented(self.TEXT)))


class AssetRecords(Base):
    def record(self, **changes):
        record = P.asset_record('vm-image', 'debian', '13.1', source='https://example.org/images/',
                                reacquire='download and verify against the pin', sha256={'disk.qcow2': 'a' * 64},
                                pin='profiles/example lock entry', consumers=['guest provisioning'])
        record.update(changes)
        return record

    def test_round_trip_and_exclusive_write(self):
        directory = self.base / 'assets' / 'vm-image' / 'debian' / '13.1'
        directory.mkdir(parents=True)
        path = P.write_asset_record(directory, self.record())
        self.assertEqual(path.name, 'aieh-asset.json')
        self.assertEqual(P.read_asset_record(directory)['integrity']['sha256'], {'disk.qcow2': 'a' * 64})
        with self.assertRaises(FileExistsError):
            P.write_asset_record(directory, self.record())
        pinned = P.asset_record('model', 'weights', 'v1', source='registry.example/models', reacquire='pull', pin='x')
        self.assertEqual(pinned['integrity'], {'pin': 'x'})

    def test_invalid_records_are_refused(self):
        bad = [{}, self.record(format='aieh-asset/2'), self.record(extra=1), self.record(kind='..'),
               self.record(name='a/b'), self.record(version=''), self.record(provenance={}),
               self.record(provenance={'source': 'x', 'other': 1}), self.record(integrity={}),
               self.record(integrity={'sha256': {'f': 'A' * 64}}), self.record(integrity={'sha256': {}}),
               self.record(integrity={'pin': ''}), self.record(integrity={'pin': 'x', 'md5': 'y'}),
               self.record(reacquire=''), self.record(acquired_at=None), self.record(consumers='all')]
        bad.append({k: v for k, v in self.record().items() if k != 'consumers'})
        for index, record in enumerate(bad):
            with self.subTest(index=index):
                self.assertRefused('ASSET_RECORD_INVALID', P.check_asset_record, record)
        self.assertRefused('ASSET_RECORD_INVALID', P.read_asset_record, self.base)


class ToolsInstall(Base):
    def setUp(self):
        super().setUp()
        lock = self.repo / T.TOOLS_LOCK
        lock.parent.mkdir(parents=True)
        shutil.copyfile(REPO / T.TOOLS_LOCK, lock)
        self.root = self.base / 'data-root'
        self.res = self.resolve(self.rooted(self.root), config={})
        self.calls, self.flags = [], []

    def fake_run(self, command, env, creationflags):
        self.calls.append((command, env))
        self.flags.append(creationflags)
        if 'download' in command:
            Path(command[command.index('--dest') + 1], 'pyyaml-6.0.3-cp312-cp312-win_amd64.whl').write_bytes(b'w')
        if 'venv' in command:
            Path(command[-1]).mkdir()
            Path(command[-1], 'pyvenv.cfg').write_text('home = x\n', encoding='utf-8')
        return subprocess.CompletedProcess(command, 0)

    def test_wheels_are_an_asset_and_the_venv_an_install(self):
        result = T.tools_install(self.res, run=self.fake_run, python='python-under-test')
        version = Path(result['venv']).name
        self.assertTrue(version.startswith(f'cp{sys.version_info[0]}{sys.version_info[1]}-'))
        wheels = self.root / 'assets' / 'python-wheels' / 'python-tools' / version
        self.assertEqual(Path(result['assets']), wheels)
        self.assertEqual(Path(result['venv']), self.root / 'persistent' / 'installs' / 'python-tools' / version)
        download, venv, install = (command for command, _ in self.calls)
        lock = str(self.repo / T.TOOLS_LOCK)
        hashed = ['--require-hashes', '--only-binary=:all:', '-r', lock]
        self.assertEqual(download, ['python-under-test', '-m', 'pip', 'download', '--dest', str(wheels), *hashed])
        self.assertEqual(venv, ['python-under-test', '-m', 'venv', result['venv']])
        self.assertEqual(install, [result['python'], '-m', 'pip', 'install', '--no-index', '--find-links', str(wheels),
                                   *hashed])
        for _, env in self.calls:
            self.assertEqual(env['PIP_CACHE_DIR'], str(self.root / 'ephemeral' / 'cache' / 'pip'))
        # no console window on Windows (the Owner's rule of 2026-11-11); 0 elsewhere
        self.assertEqual(self.flags, [getattr(subprocess, 'CREATE_NO_WINDOW', 0)] * 3)
        record = P.read_asset_record(wheels)
        self.assertEqual(record['integrity']['sha256'], {'pyyaml-6.0.3-cp312-cp312-win_amd64.whl': T.sha256_file(
            wheels / 'pyyaml-6.0.3-cp312-cp312-win_amd64.whl')})
        self.assertTrue(record['integrity']['pin'].startswith(T.TOOLS_LOCK + ' sha256:'))
        self.assertEqual(P.marker_state(self.root), 'present')
        self.calls.clear()
        T.tools_install(self.res, run=self.fake_run, python='python-under-test')
        self.assertEqual([c[3] for c, _ in self.calls], ['install'], 'a recorded asset is reused, not refetched')
        (wheels / 'pyyaml-6.0.3-cp312-cp312-win_amd64.whl').write_bytes(b'tampered')
        self.assertRefused('ASSET_RECORD_INVALID', T.tools_install, self.res, run=self.fake_run)

    def test_the_dev_tools_set_has_its_own_lock_asset_and_install(self):
        lock = self.repo / T.DEV_LOCK
        shutil.copyfile(REPO / T.DEV_LOCK, lock)
        self.assertIsNone(T.installed_python(self.res, 'python-dev-tools'))
        self.assertFalse(self.root.exists(), 'locating the interpreter creates nothing')
        result = T.tools_install(self.res, run=self.fake_run, python='python-under-test', name='python-dev-tools')
        self.assertIsNone(T.installed_python(self.res, 'python-dev-tools'), 'the fake run made no interpreter')
        Path(result['python']).parent.mkdir()
        Path(result['python']).write_bytes(b'')
        self.assertEqual(T.installed_python(self.res, 'python-dev-tools'), Path(result['python']))
        self.assertIsNone(T.installed_python(self.res), 'python-tools is another venv')
        version = Path(result['venv']).name
        wheels = self.root / 'assets' / 'python-wheels' / 'python-dev-tools' / version
        self.assertEqual(Path(result['assets']), wheels)
        self.assertEqual(Path(result['venv']), self.root / 'persistent' / 'installs' / 'python-dev-tools' / version)
        download, _, install = (command for command, _ in self.calls)
        hashed = ['--require-hashes', '--only-binary=:all:', '-r', str(lock)]
        self.assertEqual(download[-4:], hashed)
        self.assertEqual(install[-4:], hashed)
        record = P.read_asset_record(wheels)
        self.assertEqual(record['name'], 'python-dev-tools')
        self.assertEqual(record['consumers'], ['installs/python-dev-tools'])
        self.assertTrue(record['integrity']['pin'].startswith(T.DEV_LOCK + ' sha256:'))
        self.assertTrue(record['reacquire'].startswith('task dev:install ('))
        tools_version = T.tools_install(self.res, run=self.fake_run, python='python-under-test')['venv']
        self.assertNotEqual(Path(tools_version).name, version, 'each lock has its own version')

    def test_the_command_line_names_only_a_known_set(self):
        for argv in (['--set'], ['--set', 'python'], ['python-dev-tools'], ['--set', 'python-tools', 'x'],
                     ['--python', '--python'], ['--python', '--set']):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(T.main(argv), 2)
                self.assertIn('--set python-tools|python-dev-tools] [--python]', err.getvalue())

    def test_a_failed_step_stops(self):
        def failing(command, env, creationflags):
            return subprocess.CompletedProcess(command, 1)
        with self.assertRaises(subprocess.CalledProcessError):
            T.tools_install(self.res, run=failing)
        self.assertEqual(list((self.root / 'assets').rglob('aieh-asset.json')), [], 'no record without the download')


if __name__ == '__main__':
    unittest.main()
