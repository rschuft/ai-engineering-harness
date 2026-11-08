"""Tests for the pytest configuration: pyproject.toml, the root conftest.py and the dev lock (plan
leaf F-09.2).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The contract cases read the committed configuration: the pytest suites equal the Taskfile's,
every category is a declared marker, collection matches unittest discovery, and the dev lock pins
exactly the locked set with hashes. The integration cases copy conftest.py, pyproject.toml and
tools/test_profile.py into a generated project in a temporary directory and run pytest on it in a
child process, serially and with two xdist workers: the unit guard fails a unit test that
launches a process (the launch itself is refused), opens a socket or changes directory, in a test
or a class fixture, and lets an integration test launch; an uncategorized or unknown category is
refused; a run that would write bytecode is refused; and the recorded ids and outcomes equal a
stdlib profile of the same suite (the conformance check), and differ when the profile does. They
need pytest and pytest-xdist in the running interpreter (the dev tools venv, task dev:install)
and are skipped, counted, otherwise. The checkout is only read.
"""
from pathlib import Path
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location('test_profile_for_pytest_conftest', REPO / 'tools' / 'test_profile.py')
tp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tp)

CATEGORY = 'integration'
HAVE_PYTEST = all(importlib.util.find_spec(name) is not None for name in ('pytest', 'xdist'))
needs_pytest = unittest.skipUnless(
    HAVE_PYTEST, 'pytest and pytest-xdist are not importable here; run under the dev tools venv '
                 '(task dev:install, then task test:all)')
TIMEOUT = 300
TASKFILE = ("version: '3'\n\ntasks:\n  test:\n    cmds:\n"
            "      - '{{.PYTHON}} -I -B -m unittest discover -s tools/tests -v'\n")


def pytest_ini():
    return tomllib.loads((REPO / 'pyproject.toml').read_text(encoding='utf-8'))['tool']['pytest']['ini_options']


class Configuration(unittest.TestCase):
    """The committed pytest configuration and dev lock, read only."""

    category = 'contract'

    def test_the_pytest_suites_are_the_taskfile_suites(self):
        self.assertEqual(pytest_ini()['testpaths'], [start for _, start in tp.select_suites([])])

    def test_every_category_is_a_declared_marker_and_nothing_else(self):
        names = [line.split(':', 1)[0] for line in pytest_ini()['markers']]
        self.assertEqual(names, list(tp.CATEGORIES))

    def test_collection_matches_unittest_discovery_and_writes_nothing(self):
        ini = pytest_ini()
        self.assertEqual(ini['python_files'], ['test*.py'])
        self.assertEqual(ini['python_classes'], [])
        self.assertEqual(ini['python_functions'], [])
        self.assertGreaterEqual(float(ini['minversion']), 9.0)
        addopts = ini['addopts']
        for option in ('--strict-markers', '--assert=plain', '--import-mode=prepend'):
            self.assertIn(option, addopts)
        self.assertEqual(addopts[addopts.index('-p') + 1], 'no:cacheprovider')

    def test_the_dev_lock_pins_exactly_the_locked_set_with_hashes(self):
        text = (REPO / 'composition' / 'lock' / 'python' / 'dev-requirements.txt').read_text(encoding='utf-8')
        pins = {}
        for block in re.split(r'\n(?=\S)', text.strip()):
            head = block.splitlines()[0]
            match = re.match(r'^([a-z0-9-]+)==(\S+)( ; .*)? \\$', head)
            self.assertIsNotNone(match, head)
            hashes = re.findall(r'--hash=sha256:([0-9a-f]{64})', block)
            self.assertGreaterEqual(len(hashes), 1, head)
            pins[match.group(1)] = (match.group(2), (match.group(3) or '').strip(' ;'))
        self.assertEqual(set(pins), {'pytest', 'pytest-xdist', 'execnet', 'pluggy', 'iniconfig', 'pygments',
                                     'packaging', 'colorama', 'pyyaml'})
        self.assertEqual(pins['pytest-xdist'][0], '3.8.0')
        self.assertGreaterEqual(int(pins['pytest'][0].split('.')[0]), 9)
        self.assertEqual(pins['colorama'][1], "sys_platform == 'win32'")
        self.assertEqual({marker for name, (_, marker) in pins.items() if name != 'colorama'}, {''})
        source = (REPO / 'composition' / 'lock' / 'python' / 'dev-requirements.in').read_text(encoding='utf-8')
        self.assertEqual(source.split(), ['pytest>=9.0', 'pytest-xdist==3.8.0', 'pyyaml==6.0.3'])

    def test_the_dev_lock_admits_exactly_the_tools_lock_pyyaml(self):
        # PyYAML is in the dev set only so that the config.yml tests run under the parallel
        # runner too; it admits the files the tools lock (F-07.1) admits, no other.
        def pyyaml(name):
            text = (REPO / 'composition' / 'lock' / 'python' / name).read_text(encoding='utf-8')
            block = re.search(r'^pyyaml==(\S+) \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n?)+)', text, re.M)
            self.assertIsNotNone(block, name)
            return block.group(1), re.findall(r'sha256:([0-9a-f]{64})', block.group(2))
        dev, tools = pyyaml('dev-requirements.txt'), pyyaml('tools-requirements.txt')
        self.assertEqual(dev[0], '6.0.3')
        self.assertGreater(len(dev[1]), 1)
        self.assertEqual(dev, tools)


GUARD_SUITE = '''
import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path

CATEGORY = 'unit'
MARKER = Path(__file__).with_name('launched.marker')


class Launches(unittest.TestCase):
    def test_launch(self):
        subprocess.run([sys.executable, '-c', f'open({str(MARKER)!r}, "w").close()'])


class SwallowsTheRefusal(unittest.TestCase):
    def test_launch_in_try(self):
        try:
            subprocess.run([sys.executable, '-c', 'pass'])
        except Exception:
            pass


class Socket(unittest.TestCase):
    def test_socket(self):
        socket.socket().close()


class Chdir(unittest.TestCase):
    def test_chdir(self):
        os.chdir(os.getcwd())


class LaunchesInSetUpClass(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, '-c', 'pass'])

    def test_never_runs(self):
        pass


class Clean(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(1 + 1, 2)


class IntegrationLaunches(unittest.TestCase):
    category = 'integration'

    def test_launch(self):
        self.assertEqual(subprocess.run([sys.executable, '-c', 'pass']).returncode, 0)
'''

CONFORMANCE_SUITE = '''
import unittest

CATEGORY = 'unit'


class Plain(unittest.TestCase):
    def test_ok(self):
        pass

    @unittest.skip('skipped by its decorator')
    def test_skipped(self):
        pass

    @unittest.expectedFailure
    def test_expected_failure(self):
        self.assertEqual(1, 2)

    def test_subtests(self):
        for i in range(3):
            with self.subTest(i=i):
                self.assertLess(i, 3)


class SkipsInSetUpClass(unittest.TestCase):
    category = 'e2e'

    @classmethod
    def setUpClass(cls):
        raise unittest.SkipTest('no live service')

    def test_a(self):
        pass

    def test_b(self):
        pass


@unittest.skip('the whole class')
class SkippedClass(unittest.TestCase):
    category = 'contract'

    def test_c(self):
        pass
'''


@needs_pytest
class GeneratedProject(unittest.TestCase):
    """pytest with this conftest.py on a generated project, in a child process."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='aieh-pytest-conftest-')
        cls.base = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def project(self, name, modules):
        root = self.base / name
        (root / 'tools' / 'tests').mkdir(parents=True)
        for path in ('conftest.py', 'pyproject.toml', 'tools/test_profile.py'):
            shutil.copyfile(REPO / path, root / path)
        (root / 'Taskfile.yml').write_text(TASKFILE, encoding='utf-8')
        for module, source in modules.items():
            (root / 'tools' / 'tests' / module).write_text(textwrap.dedent(source), encoding='utf-8')
        return root

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('PYTEST', 'PYTHON'))}
        env.update(PYTHONDONTWRITEBYTECODE='1', GIT_CEILING_DIRECTORIES=str(self.base), **extra)
        return env

    def pytest(self, root, *args, env=None, bytecode_flag=True):
        flags = ['-I', '-B'] if bytecode_flag else ['-I']
        proc = subprocess.run([sys.executable, *flags, '-m', 'pytest', '--basetemp', str(root / 'basetemp'),
                               *args], cwd=root, capture_output=True, env=env or self.env(), timeout=TIMEOUT)
        return proc.returncode, (proc.stdout + proc.stderr).decode('utf-8', 'replace')

    def outcomes(self, path):
        return {t['id']: t['outcome'] for t in json.loads(path.read_text(encoding='utf-8'))['tests']}

    def test_the_unit_guard_fails_launches_sockets_and_chdir_in_unit_tests_only(self):
        root = self.project('guard', {'test_injected.py': GUARD_SUITE})
        expected = {
            'test_injected.Launches.test_launch': 'error',
            'test_injected.SwallowsTheRefusal.test_launch_in_try': 'error',
            'test_injected.Socket.test_socket': 'error',
            'test_injected.Chdir.test_chdir': 'error',
            'setUpClass (test_injected.LaunchesInSetUpClass)': 'error',
            'test_injected.Clean.test_clean': 'ok',
            'test_injected.IntegrationLaunches.test_launch': 'ok',
        }
        for workers in ('0', '2'):
            with self.subTest(workers=workers):
                out_file = root / f'outcomes-{workers}.json'
                code, out = self.pytest(root, '-n', workers, f'--aieh-outcomes={out_file}')
                self.assertEqual(code, 1, out)
                self.assertEqual(self.outcomes(out_file), expected, out)
                document = json.loads(out_file.read_text(encoding='utf-8'))
                self.assertEqual(document['workers'], int(workers))
                self.assertLessEqual(set(document['worker_ids']), {f'gw{n}' for n in range(int(workers))})
                self.assertEqual(bool(document['worker_ids']), workers != '0')
                for event in ('subprocess.Popen', 'socket.__new__', 'os.chdir'):
                    self.assertIn(f'unit guard: {event} in the unit test tools/tests/test_injected.py::', out)
                self.assertIn('unit guard: the unit test tools/tests/test_injected.py::SwallowsTheRefusal::'
                              'test_launch_in_try made subprocess.Popen', out)
                self.assertFalse((root / 'tools' / 'tests' / 'launched.marker').exists(),
                                 'the guarded launch was refused before it ran')
                self.assertEqual(sorted(p.name for p in root.rglob('__pycache__')), [], 'no bytecode written')

    def test_an_uncategorized_or_unknown_category_is_refused(self):
        for name, declaration, shown in (('none', '', 'None'), ('bogus', "    category = 'bogus'\n", "'bogus'")):
            with self.subTest(case=name):
                root = self.project(f'category-{name}', {'test_c.py': (
                    'import unittest\n\n\nclass C(unittest.TestCase):\n' + declaration
                    + '    def test_x(self):\n        pass\n')})
                code, out = self.pytest(root, '-n', '0')
                self.assertEqual(code, 4, out)
                self.assertIn(f'class test_c.C has category {shown}', out)

    def test_a_run_that_would_write_bytecode_is_refused(self):
        root = self.project('bytecode', {'test_ok.py': CONFORMANCE_SUITE})
        env = self.env()
        del env['PYTHONDONTWRITEBYTECODE']
        code, out = self.pytest(root, '-n', '0', env=env, bytecode_flag=False)
        self.assertEqual(code, 4, out)
        self.assertIn('PYTHONDONTWRITEBYTECODE=1', out)

    def test_the_outcomes_equal_a_stdlib_profile_and_a_difference_fails(self):
        root = self.project('conformance', {'test_conformance.py': CONFORMANCE_SUITE})
        profile = root / 'stdlib-profile.json'
        proc = subprocess.run([sys.executable, '-I', '-B', str(root / 'tools' / 'test_profile.py'), 'run',
                               '--out', str(profile), '--workdir', str(root / 'profile-work')],
                              cwd=root, capture_output=True, env=self.env(), timeout=TIMEOUT)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode('utf-8', 'replace'))
        stdlib = json.loads(profile.read_text(encoding='utf-8'))
        self.assertIn('setUpClass (test_conformance.SkipsInSetUpClass)', {t['id'] for t in stdlib['tests']})
        for workers in ('0', '2'):
            with self.subTest(workers=workers):
                code, out = self.pytest(root, '-n', workers, f'--aieh-conformance={profile}')
                self.assertEqual(code, 0, out)
                self.assertIn('CONFORMANCE PASS: 6 ids, 5 tests run', out)
        for test in stdlib['tests']:
            if test['id'] == 'test_conformance.Plain.test_expected_failure':
                test['outcome'] = 'ok'
        changed = root / 'changed-profile.json'
        changed.write_text(json.dumps(stdlib), encoding='utf-8')
        code, out = self.pytest(root, '-n', '0', f'--aieh-conformance={changed}')
        self.assertEqual(code, 1, out)
        self.assertIn('CONFORMANCE DIFF: tools: test_conformance.Plain.test_expected_failure: stdlib ok, '
                      'pytest xfail', out)
        code, out = self.pytest(root, '-n', '0', '-m', 'not e2e', f'--aieh-conformance={profile}')
        self.assertEqual(code, 1, out)
        self.assertIn('2 tests deselected; conformance needs the whole collection', out)


if __name__ == '__main__':
    unittest.main()
