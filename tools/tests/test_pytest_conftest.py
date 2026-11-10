"""Tests for the pytest configuration: pyproject.toml, the root conftest.py and the dev lock (plan
leaf F-09.2), and the tools lock (plan leaves F-07.1, F-10.1 and F-06.3).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The contract cases read the committed configuration: the pytest suites equal the Taskfile's,
every category is a declared marker, collection matches unittest discovery, the dev and tools
locks each pin exactly the locked set with hashes, the dev lock admits exactly the tools
lock's files for PyYAML, Dulwich, urllib3 and the keyring closure, and the keyring closure's blocks
are those of the F-01.2 per-target locks, with their sys_platform markers. The integration cases copy conftest.py, pyproject.toml and
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


# The python-tools set (composition/lock/python/tools-requirements.txt), which the dev set includes.
TOOLS_PINS = {'dulwich': '1.2.21', 'pyyaml': '6.0.3', 'urllib3': '2.8.0'}
# keyring 25.7.0 and its closure (plan leaf F-06.3; draft decision 0011): copied with their hashes from
# the F-01.2 per-target locks, each with its sys_platform marker from keyring's and SecretStorage's own
# requirements ('' for every platform), and the lock it is copied from.
KEYRING_PINS = {
    'keyring': ('25.7.0', '', 'windows-x86_64.txt'),
    'jaraco-classes': ('3.4.0', '', 'windows-x86_64.txt'),
    'jaraco-context': ('6.1.2', '', 'windows-x86_64.txt'),
    'jaraco-functools': ('4.6.0', '', 'windows-x86_64.txt'),
    'more-itertools': ('11.2.1', '', 'windows-x86_64.txt'),
    'pywin32-ctypes': ('0.2.3', "sys_platform == 'win32'", 'windows-x86_64.txt'),
    'secretstorage': ('3.5.0', "sys_platform == 'linux'", 'linux-x86_64.txt'),
    'jeepney': ('0.9.0', "sys_platform == 'linux'", 'linux-x86_64.txt'),
    'cryptography': ('50.0.2', "sys_platform == 'linux'", 'linux-x86_64.txt'),
    'cffi': ('2.1.1', "sys_platform == 'linux'", 'linux-x86_64.txt'),
    'pycparser': ('3.12', "sys_platform == 'linux'", 'linux-x86_64.txt'),
}


def lock_markers(name):
    """Each pin of a lock file: its name -> its marker ('' when none)."""
    text = (REPO / 'composition' / 'lock' / 'python' / name).read_text(encoding='utf-8')
    return {m.group(1): (m.group(2) or '') for m in re.finditer(r'^([a-z0-9-]+)==\S+(?: ; ([^\\\n]*))? \\$',
                                                                   text, re.M)}


def lock_blocks(name):
    """Each pin of a lock file: its name -> (version, its hashes in order)."""
    text = (REPO / 'composition' / 'lock' / 'python' / name).read_text(encoding='utf-8')
    blocks = {}
    for match in re.finditer(r'^([a-z0-9-]+)==(\S+)(?: ; [^\\\n]*)? \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n?)+)',
                             text, re.M):
        blocks[match.group(1)] = (match.group(2), re.findall(r'sha256:([0-9a-f]{64})', match.group(3)))
    if len(blocks) != len([line for line in text.splitlines() if line and not line.startswith(' ')]):
        raise ValueError(f'{name}: a pin is not a hash-locked block')
    return blocks


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
                                     'packaging', 'colorama'} | set(TOOLS_PINS) | set(KEYRING_PINS))
        self.assertEqual(pins['pytest-xdist'][0], '3.8.0')
        self.assertGreaterEqual(int(pins['pytest'][0].split('.')[0]), 9)
        self.assertEqual(pins['colorama'][1], "sys_platform == 'win32'")
        for name, (version, marker, _source) in KEYRING_PINS.items():
            self.assertEqual(pins[name], (version, marker), name)
        self.assertEqual({marker for name, (_, marker) in pins.items()
                          if name != 'colorama' and name not in KEYRING_PINS}, {''})
        source = (REPO / 'composition' / 'lock' / 'python' / 'dev-requirements.in').read_text(encoding='utf-8')
        self.assertEqual(source.split(), ['dulwich==1.2.21', 'keyring==25.7.0', 'pytest>=9.0', 'pytest-xdist==3.8.0',
                                          'pyyaml==6.0.3', 'urllib3==2.8.0'])

    def test_the_tools_lock_pins_exactly_the_locked_set_with_hashes(self):
        # The python-tools set (F-07.1, F-10.1, F-06.3): PyYAML for config.yml, Dulwich with its one
        # runtime dependency on CPython 3.12, urllib3, without a platform marker; and the keyring closure
        # with its markers; every file PyPI publishes.
        blocks = lock_blocks('tools-requirements.txt')
        self.assertEqual({name: version for name, (version, _) in blocks.items()},
                         {**TOOLS_PINS, **{name: pin[0] for name, pin in KEYRING_PINS.items()}})
        markers = lock_markers('tools-requirements.txt')
        self.assertEqual({name: markers[name] for name in TOOLS_PINS}, dict.fromkeys(TOOLS_PINS, ''))
        self.assertEqual({name: markers[name] for name in KEYRING_PINS},
                         {name: pin[1] for name, pin in KEYRING_PINS.items()})
        self.assertGreater(len(blocks['dulwich'][1]), 9)  # the platform wheels, the pure wheel and the sdist
        self.assertEqual(len(blocks['urllib3'][1]), 2)    # the pure wheel and the sdist
        source = (REPO / 'composition' / 'lock' / 'python' / 'tools-requirements.in').read_text(encoding='utf-8')
        self.assertEqual(source.split(), ['dulwich==1.2.21', 'keyring==25.7.0', 'pyyaml==6.0.3', 'urllib3==2.8.0'])

    def test_the_keyring_closure_is_copied_from_the_component_locks(self):
        # F-06.3 resolved nothing: each block is the F-01.2 lock's, the same version and hashes in the same
        # order, in every per-target lock that has the package.
        tools = lock_blocks('tools-requirements.txt')
        targets = {name: lock_blocks(name) for name in ('windows-x86_64.txt', 'linux-x86_64.txt',
                                                        'linux-aarch64.txt')}
        for name, (_version, _marker, source) in KEYRING_PINS.items():
            self.assertEqual(tools[name], targets[source][name], name)
            for target, blocks in targets.items():
                if name in blocks:
                    self.assertEqual(blocks[name], tools[name], (name, target))

    def test_the_dev_lock_admits_exactly_the_tools_lock_files(self):
        # PyYAML, Dulwich, urllib3 and keyring are in the dev set so that every suite runs under the parallel
        # runner as under task test; for each, the dev lock admits exactly the files the tools lock
        # admits, in the same order, no other.
        dev, tools = lock_blocks('dev-requirements.txt'), lock_blocks('tools-requirements.txt')
        for name, version in {**TOOLS_PINS, **{name: pin[0] for name, pin in KEYRING_PINS.items()}}.items():
            self.assertEqual(dev[name][0], version, name)
            self.assertGreater(len(dev[name][1]), 1, name)
            self.assertEqual(dev[name], tools[name], name)


def taskfile_targets():
    """Each Taskfile.yml target: its name -> the lines of its body, stripped, without blank lines."""
    targets, name = {}, None
    for line in (REPO / 'Taskfile.yml').read_text(encoding='utf-8').splitlines():
        if header := re.match(r'^  ([\w:-]+):\s*$', line):
            name = header.group(1)
            targets[name] = []
        elif name is not None and line.startswith('    '):
            targets[name].append(line.strip())
        elif line.strip():
            name = None
    return targets


TOOLS_VARS = ['TOOLS_PYTHON:', "sh: '{{.PYTHON}} -I -B integrations/paths/tools_install.py --python'",
              'PYTHON: \'"{{.TOOLS_PYTHON}}"\'']
DISCOVERY = r"^- '\{\{\.PYTHON\}\} -I -B -m unittest discover -s \S+ -v'$"


class RequiredTargets(unittest.TestCase):
    """setup, test, every suite target run alone, test:profile, test:categories, test:budget and the gate's test
    suite in hooks:verify run under the python-tools interpreter, so that a Dulwich-dependent test
    never meets an interpreter without Dulwich; the basic-tier checks keep the plain interpreter
    (plan leaves F-10.1 and F-10.2, decision 0014 section 9). Reads Taskfile.yml only."""

    category = 'contract'

    def setUp(self):
        self.targets = taskfile_targets()

    def commands(self, name):
        body = self.targets[name]
        return body[body.index('cmds:') + 1:]

    def variables(self, name):
        body = self.targets[name]
        return body[body.index('vars:') + 1:body.index(next(k for k in ('env:', 'cmds:') if k in body))]

    def test_setup_runs_the_basic_tier_checks_then_installs_the_tools_set_then_test(self):
        self.assertEqual(self.commands('setup'), ['- task: prereqs', '- task: verify', '- task: verify:baseline',
                                                  '- task: tools:install', '- task: test'])
        self.assertEqual(self.commands('tools:install'), ["- '{{.PYTHON}} -I -B integrations/paths/tools_install.py'"])

    def test_test_runs_every_suite_under_the_tools_interpreter(self):
        self.assertEqual(self.variables('test'), TOOLS_VARS)
        commands = self.commands('test')
        self.assertEqual(commands[0], "- '{{.PYTHON}} -I -B -m unittest discover -s tools/tests -v'")
        calls = commands[1:]
        self.assertEqual(len(calls), len(tp.select_suites([])) - 1)
        self.assertTrue(all(call.startswith('- task: ') for call in calls), calls)
        self.assertIn('- task: repository:test', calls)

    def test_every_suite_target_resolves_the_tools_interpreter_when_run_alone(self):
        suites = [name for name in self.targets if name.endswith(':test') and name != 'owner-host:test']
        self.assertEqual(sorted(suites), sorted(call.removeprefix('- task: ') for call in self.commands('test')[1:]))
        for name in suites:
            with self.subTest(target=name):
                self.assertEqual(self.variables(name), TOOLS_VARS)
                self.assertEqual(len(self.commands(name)), 1)
                self.assertRegex(self.commands(name)[0], DISCOVERY)

    def test_the_profile_and_budget_targets_run_under_the_tools_interpreter(self):
        # test:categories imports every test module, and the credential provider tests import keyring.
        for name, script in (('test:profile', 'tools/test_profile.py run'),
                             ('test:categories', 'tools/test_profile.py categories'),
                             ('test:budget', 'tools/check_test_budget.py check --run')):
            with self.subTest(target=name):
                self.assertEqual(self.variables(name), TOOLS_VARS)
                self.assertEqual(self.commands(name), [f"- '{{{{.PYTHON}}}} -I -B {script} {{{{.CLI_ARGS}}}}'"])

    def test_the_commands_that_read_a_repository_run_under_the_tools_interpreter(self):
        # The planning and lineage commands read the project repository through the shared
        # repository-access module (Dulwich; plan leaf F-10.3, decision 0014 section 9); the acceptance
        # recorder also commits through it (plan leaf P-04.1).
        for name, script in (('planning:create', 'integrations/planning/planning_adapter.py create'),
                             ('planning:resolve', 'integrations/planning/planning_adapter.py resolve'),
                             ('planning:readiness', 'integrations/planning/planning_readiness.py'),
                             ('lineage:resolve', 'integrations/lineage/lineage_resolve.py resolve'),
                             ('lineage:trace', 'integrations/lineage/lineage_trace.py trace'),
                             ('lineage:example', 'integrations/lineage/tests/lineage_example.py'),
                             ('owner:accept', 'integrations/owner/acceptance_recorder.py')):
            with self.subTest(target=name):
                self.assertEqual(self.variables(name), TOOLS_VARS)
                (command,) = self.commands(name)
                self.assertTrue(command.startswith(f"- '{{{{.PYTHON}}}} -I -B {script}"), command)

    def test_the_guest_and_gitea_commands_that_read_a_repository_run_under_the_tools_interpreter(self):
        # Rows R5, R7, R8 and R9 of decision 0014 (plan leaf F-10.4): create and recreate record
        # the profile revision (smoke and netprobe create too), smoke takes the inventory
        # snapshots, push writes the exchange bundle, gitea:verify and finalize-credentials
        # list the checkout; all through the shared repository-access module (Dulwich).
        for name, script in (('guest:create', 'tools/guest.py create'),
                             ('guest:create-canaries', 'tools/guest.py create'),
                             ('guest:create-provisioned', 'tools/guest.py create'),
                             ('guest:recreate', 'tools/guest.py recreate'),
                             ('guest:netprobe', 'tools/guest.py netprobe'),
                             ('guest:smoke', 'tools/guest.py smoke'),
                             ('guest:push', 'tools/guest.py exchange-push'),
                             ('gitea:verify', 'integrations/gitea/gitea_host.py verify'),
                             ('gitea:finalize-credentials', 'integrations/gitea/gitea_host.py finalize-credentials')):
            with self.subTest(target=name):
                self.assertEqual(self.variables(name), TOOLS_VARS)
                (command,) = self.commands(name)
                self.assertTrue(command.startswith(f"- '{{{{.PYTHON}}}} -I -B {script}"), command)
                self.assertIn('(<tools python> -I -B ', self.targets[name][0])

    def test_hooks_verify_runs_the_gate_plain_and_its_tests_under_the_tools_interpreter(self):
        self.assertEqual(self.variables('hooks:verify'), TOOLS_VARS[:2])
        self.assertEqual(self.commands('hooks:verify'), [
            "- '{{.PYTHON}} -I -B tools/publication_gate.py verify'",
            "- '\"{{.TOOLS_PYTHON}}\" -I -B -m unittest discover -s tools/tests -p test_publication_gate.py -v'"])

    def test_the_basic_tier_checks_keep_the_plain_interpreter(self):
        # check_prereqs, verify_seed and the publication gate stay standard-library only and offline:
        # they run under the PYTHON the Taskfile is given, never a managed venv's.
        for name in ('prereqs', 'verify', 'verify:baseline', 'hooks:install', 'scan:history'):
            commands = self.commands(name)
            self.assertTrue(commands, name)
            for command in commands:
                self.assertTrue(command.startswith("- '{{.PYTHON}} -I ") or command.startswith('- task: '), command)
                self.assertNotIn('TOOLS_PYTHON', command)
                self.assertNotIn('DEV_PYTHON', command)
            self.assertNotIn('vars:', self.targets[name], name)


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
