"""Tests for tools/test_profile.py (plan leaf F-09.1).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The unit cases drive the launch naming, the verbose-log parser, the Taskfile reader, the
category lookup, the recorder and the aggregation in-process with synthetic data. The child
cases run the profiling child and a plain unittest run on a small generated suite in a
temporary directory and check the exact counters, the attribution and that both give the
same ids and outcomes. The checkout is only read.
"""
from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / 'tools' / 'test_profile.py'

_spec = importlib.util.spec_from_file_location('test_profile', TOOL)
tp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tp)

CATEGORY = 'unit'


def fake_frame(filename, name='f', back=None, module_name='m'):
    return types.SimpleNamespace(f_code=types.SimpleNamespace(co_filename=filename, co_name=name),
                                 f_back=back, f_globals={'__name__': module_name}, f_locals={})


class ProgramKeyTests(unittest.TestCase):
    def test_git_subcommand_skips_global_options(self):
        self.assertEqual(tp.program_key(['git', '-c', 'a=b', '-C', 'x', '--no-pager', 'rev-parse',
                                         'HEAD']), 'git rev-parse')
        self.assertEqual(tp.program_key([r'C:\Program Files\Git\cmd\git.exe', 'cat-file', '-p']),
                         'git cat-file')
        self.assertEqual(tp.program_key(['git']), 'git')
        self.assertEqual(tp.program_key(['git', '--git-dir', 'x/.git', 'log']), 'git log')
        self.assertEqual(tp.program_key(['git', r'C:\tmp\origin.git']), 'git <path>')

    def test_python_script_module_and_command(self):
        self.assertEqual(tp.program_key([sys.executable, '-I', '-B', 'x/fake_backlog.py', 'task']),
                         'python fake_backlog.py')
        self.assertEqual(tp.program_key(['python3', '-I', '-m', 'unittest', 'discover']),
                         'python -m unittest')
        self.assertEqual(tp.program_key(['py', '-X', 'utf8', '-c', 'pass']), 'python -c')
        self.assertEqual(tp.program_key(['python']), 'python')

    def test_other_programs_are_named_without_a_path(self):
        self.assertEqual(tp.program_key(['/opt/tools/gitleaks', 'dir']), 'gitleaks')
        self.assertEqual(tp.program_key([r'D:\x\stub.cmd']), 'stub.cmd')
        self.assertEqual(tp.program_key([]), '?')

    def test_launch_argv_from_each_event(self):
        self.assertEqual(tp.launch_argv('subprocess.Popen', ('git', ['g', 'status'], None, None)),
                         ['git', 'status'])
        self.assertEqual(tp.launch_argv('subprocess.Popen', (None, 'git log -1', None, None)),
                         ['git', 'log', '-1'])
        self.assertEqual(tp.launch_argv('_winapi.CreateProcess',
                                        (None, '"C:\\a b\\python.exe" -c pass', None)),
                         ['C:\\a b\\python.exe', '-c', 'pass'])
        self.assertEqual(tp.launch_argv('os.spawn', (0, '/bin/git', ['git', 'status'], {})),
                         ['/bin/git', 'status'])
        self.assertEqual(tp.launch_argv('os.system', ('echo hi',)), ['os.system'])
        self.assertEqual(tp.launch_argv('subprocess.Popen', ()), ['subprocess.Popen'])


class VerboseParseTests(unittest.TestCase):
    LOG = textwrap.dedent("""\
        test_a (mod.Case.test_a) ... ok
        test_b (mod.Case.test_b)
        The first docstring line. ... skipped 'no tool'
        test_c (mod.Case.test_c) ... a stray warning from the test
        ok
          test_d (mod.Case.test_d) [one] (i=1) ... FAIL
        test_e (mod.Case.test_e) ... expected failure
        setUpClass (mod.Broken) ... ERROR
        test_f (mod.Case.test_f) ... unexpected success

        ======================================================================
        FAIL: test_x (mod.Case.test_x) ... ok
        ----------------------------------------------------------------------
        Ran 6 tests in 0.010s

        FAILED (failures=1, errors=1)
        """)

    def test_every_outcome_is_parsed(self):
        results, ran = tp.parse_verbose(self.LOG)
        self.assertEqual(ran, 6)
        self.assertEqual(results, {
            'mod.Case.test_a': 'ok', 'mod.Case.test_b': 'skip', 'mod.Case.test_c': 'ok',
            'mod.Case.test_d': 'fail', 'mod.Case.test_e': 'xfail',
            'setUpClass (mod.Broken)': 'error', 'mod.Case.test_f': 'xpass'})

    def test_a_failing_subtest_outranks_success(self):
        results, _ = tp.parse_verbose('  test_a (m.C.test_a) (i=1) ... ERROR\n'
                                      'test_a (m.C.test_a) ... ok\n')
        self.assertEqual(results, {'m.C.test_a': 'error'})


class TaskfileSuitesTests(unittest.TestCase):
    def test_the_committed_taskfile_gives_the_task_test_suites_in_order(self):
        suites = tp.select_suites([])
        self.assertEqual(suites[0], ('tools', 'tools/tests'))
        names = [name for name, _ in suites]
        self.assertEqual(len(names), len(set(names)))
        for name, start_dir in suites[1:]:
            self.assertEqual(start_dir, f'integrations/{name}/tests')
            self.assertTrue((REPO / start_dir).is_dir(), start_dir)
        self.assertIn('dispatch', names)

    def test_direct_and_referenced_discoveries(self):
        text = textwrap.dedent("""\
            tasks:
              test:
                cmds:
                  - '{{.PYTHON}} -I -B -m unittest discover -s tools/tests -v'
                  - task: a:test

              a:test:
                desc: x
                cmds:
                  - '{{.PYTHON}} -I -B -m unittest discover -s integrations/a/tests -v'
            """)
        self.assertEqual(tp.taskfile_suites(text),
                         [('tools', 'tools/tests'), ('a', 'integrations/a/tests')])

    def test_scratch_removes_only_what_it_created(self):
        # Faked, so that this unit test creates no directory itself.
        made = mock.MagicMock()
        made.__enter__.return_value = 'made'
        with mock.patch.object(tp.tempfile, 'TemporaryDirectory', return_value=made) as factory:
            with tp.scratch() as workdir:
                self.assertEqual(workdir, Path('made'))
                made.__exit__.assert_not_called()
        factory.assert_called_once_with(prefix='aieh-test-profile-', ignore_cleanup_errors=True)
        made.__exit__.assert_called_once()
        with mock.patch.object(tp, '_workdir', return_value=Path('given')) as given,                 mock.patch.object(tp.tempfile, 'TemporaryDirectory') as factory:
            with tp.scratch('given') as workdir:
                self.assertEqual(workdir, Path('given'))
        given.assert_called_once_with('given')
        factory.assert_not_called()

    def test_unreadable_targets_are_refused(self):
        with self.assertRaises(tp.ProfileError):
            tp.taskfile_suites('tasks:\n  setup:\n    cmds: []\n')
        with self.assertRaises(tp.ProfileError):
            tp.taskfile_suites('tasks:\n  test:\n    cmds:\n      - task: b\n  b:\n    cmds: []\n')
        with self.assertRaises(tp.ProfileError):
            tp.select_suites(['no-such-suite'])


class CategoryLookupTests(unittest.TestCase):
    def test_class_attribute_wins_over_the_module(self):
        module = types.ModuleType('fake_category_module')
        module.CATEGORY = 'contract'
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__)
        declared = type('Declared', (unittest.TestCase,), {'__module__': module.__name__,
                                                            'category': 'e2e'})
        inherited = type('Inherited', (unittest.TestCase,), {'__module__': module.__name__})
        self.assertEqual(tp.class_category(declared), ('e2e', 'class'))
        self.assertEqual(tp.class_category(inherited), ('contract', 'module'))
        del module.CATEGORY
        self.assertEqual(tp.class_category(inherited), (None, None))

    def test_this_module_is_categorized(self):
        self.assertEqual(tp.class_category(type(self)), ('unit', 'module'))


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.rec = tp.Recorder(REPO, REPO / 'tools' / 'tests')
        self.test_file = str(REPO / 'tools' / 'tests' / 'test_x.py')

    def test_events_count_into_the_running_test(self):
        self.rec.current = self.rec._new_record(id='t')
        frame = fake_frame(self.test_file)
        self.rec.on_event('subprocess.Popen', ('git', ['git', 'status'], None, None), frame)
        self.rec.on_event('tempfile.mkdtemp', ('x',), frame)
        self.rec.on_event('socket.__new__', (None, 2, 1, 0), frame)
        self.rec.on_event('os.chdir', ('x',), frame)
        self.rec.on_event('open', ('x', 'r', 0), frame)
        record = self.rec.current
        self.assertEqual({k: record[k] for k in tp.COUNTERS},
                         {'launches': 1, 'mkdtemp': 1, 'sockets': 1, 'chdir': 1})
        self.assertEqual(dict(record['programs']), {'git status @ tools/tests/test_x.py': 1})

    def test_create_process_from_subprocess_is_not_counted_twice(self):
        self.rec.current = self.rec._new_record(id='t')
        self.rec.on_event('_winapi.CreateProcess', (None, 'git status', None),
                          fake_frame('C:/Python/Lib/subprocess.py'))
        self.assertEqual(self.rec.current['launches'], 0)
        self.rec.on_event('_winapi.CreateProcess', (None, 'git status', None),
                          fake_frame('C:/Python/Lib/multiprocessing/popen_spawn_win32.py'))
        self.assertEqual(self.rec.current['launches'], 1)

    def test_fixture_import_and_other_scopes(self):
        self.rec.fixture = self.rec._new_record(kind='class', owner='m.C', wall=0.0)
        self.rec.on_event('tempfile.mkdtemp', ('x',), fake_frame(self.test_file))
        self.assertEqual(self.rec.fixture['mkdtemp'], 1)
        self.rec.fixture = None
        module_frame = fake_frame(self.test_file, name='<module>', module_name='test_x')
        self.rec.on_event('tempfile.mkdtemp', ('x',), fake_frame('lib.py', back=module_frame))
        self.assertEqual(self.rec.imports['test_x']['mkdtemp'], 1)
        self.rec.on_event('tempfile.mkdtemp', ('x',), fake_frame(str(REPO / 'tools' / 'x.py')))
        self.assertEqual(self.rec.other['mkdtemp'], 1)

    def test_origin_is_repository_relative_or_outside(self):
        inner = fake_frame(str(REPO / 'integrations' / 'lineage' / 'lineage_git.py'))
        self.assertEqual(self.rec._origin(inner), 'integrations/lineage/lineage_git.py')
        self.assertEqual(self.rec._origin(fake_frame(str(Path(tempfile.gettempdir()) / 'a.py'))),
                         '<outside>')


def child(name, cls, tests, fixtures=(), imports=(), wall=1.0, ok=True, category='unit'):
    rows = [{'id': cls, 'module': cls.rsplit('.', 1)[0], 'category': category,
             'source': 'module' if category else None, 'tests': len(tests)}]
    test_rows = []
    for t, extra in tests:
        row = dict({c: 0 for c in tp.COUNTERS}, id=f'{cls}.{t}', cls=cls, outcome='ok', wall=0.1,
                   programs={})
        row.update(extra)
        test_rows.append(row)
    return {'schema': tp.CHILD_SCHEMA, 'start_dir': name, 'discovery_wall': 0.1, 'run_wall': 0.5,
            'tests_run': len(tests), 'successful': ok, 'classes': rows, 'failed_imports': [],
            'tests': test_rows, 'fixtures': list(fixtures), 'imports': list(imports),
            'other': dict({c: 0 for c in tp.COUNTERS}, programs={}), 'wall': wall,
            'returncode': 0 if ok else 1}


class AggregationTests(unittest.TestCase):
    SUITES = [('a', 'a/tests'), ('b', 'b/tests')]

    def runs(self, launches=2):
        fixture = dict({c: 0 for c in tp.COUNTERS}, kind='class', owner='ma.A', wall=0.2,
                       launches=1, programs={'git init @ a/tests/t.py': 1})
        return {'a': child('a', 'ma.A', [('test_1', {'launches': launches,
                                                      'programs': {'git log @ x': launches}}),
                                          ('test_2', {'mkdtemp': 3})], fixtures=[fixture]),
                'b': child('b', 'mb.B', [('test_1', {})], category='contract', wall=2.0)}

    def test_counters_roll_up_to_classes_categories_suites_and_total(self):
        profile = tp.build_profile([self.runs(), self.runs(), self.runs()], self.SUITES)
        self.assertEqual(profile['totals']['tests'], 3)
        self.assertEqual(profile['totals']['launches'], 3)
        self.assertEqual(profile['totals']['mkdtemp'], 3)
        self.assertEqual(profile['categories']['unit']['launches'], 3)
        self.assertEqual(profile['categories']['contract']['tests'], 1)
        self.assertEqual(profile['totals']['wall']['median'], 3.0)
        cls = next(r for r in profile['classes'] if r['id'] == 'ma.A')
        self.assertEqual(cls['programs'], {'git log @ x': 2, 'git init @ a/tests/t.py': 1})
        self.assertEqual(profile['determinism'], [])
        self.assertEqual(tp.profile_ok(profile), [])

    def test_counters_that_differ_between_runs_are_reported(self):
        profile = tp.build_profile([self.runs(), self.runs(launches=3)], self.SUITES)
        self.assertEqual(profile['determinism'][0]['counter'], 'launches')
        self.assertTrue(tp.profile_ok(profile))

    def test_uncategorized_and_failing_suites_fail(self):
        runs = self.runs()
        runs['b'] = child('b', 'mb.B', [('test_1', {})], category=None, ok=False)
        profile = tp.build_profile([runs], self.SUITES)
        self.assertEqual(profile['uncategorized'], ['mb.B'])
        reasons = tp.profile_ok(profile)
        self.assertTrue(any('no category' in r for r in reasons))
        self.assertTrue(any('failing' in r for r in reasons))

    def test_compact_form_keeps_aggregates_and_drops_tests(self):
        profile = tp.build_profile([self.runs()], self.SUITES)
        small = tp.compact(profile)
        self.assertEqual(small['schema'], tp.COMPACT_SCHEMA)
        self.assertNotIn('tests', small)
        self.assertEqual(small['totals'], profile['totals'])
        self.assertEqual(small['top_launch_programs'][0], {'program': 'git log @ x', 'launches': 2})
        self.assertNotIn('programs', small['classes'][0])
        self.assertEqual(small['outcomes_digest'], profile['outcomes_digest'])


FIXTURE_SUITE = '''\
import subprocess, sys, tempfile, unittest

CATEGORY = 'integration'


def launch():
    subprocess.run([sys.executable, '-c', 'pass'], check=True)


class Launching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        launch()

    def test_launch_twice_and_one_temporary_directory(self):
        launch()
        launch()
        with tempfile.TemporaryDirectory():
            pass

    def test_skipped(self):
        self.skipTest('fixture skip')


class Quiet(unittest.TestCase):
    category = 'unit'

    def test_nothing(self):
        """A docstring line."""
        self.assertTrue(True)
'''


class ChildRunTests(unittest.TestCase):
    category = 'integration'

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='tp-')
        cls.root = Path(cls.tmp.name)
        suite = cls.root / 's'
        suite.mkdir()
        (suite / 'test_fixture_suite.py').write_text(FIXTURE_SUITE, encoding='utf-8')
        cls.start_dir = str(suite)
        cls.data = tp.run_child('fixture', cls.start_dir, cls.root, 'run1')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_exact_counters_and_attribution(self):
        tests = {t['id'].rsplit('.', 2)[-2] + '.' + t['id'].rsplit('.', 1)[-1]: t
                 for t in self.data['tests']}
        busy = tests['Launching.test_launch_twice_and_one_temporary_directory']
        self.assertEqual((busy['launches'], busy['mkdtemp'], busy['outcome']), (2, 1, 'ok'))
        self.assertEqual(tests['Launching.test_skipped']['outcome'], 'skip')
        self.assertEqual(tests['Quiet.test_nothing']['launches'], 0)
        fixtures = {f['owner'].rsplit('.', 1)[-1]: f for f in self.data['fixtures']}
        self.assertEqual(fixtures['Launching']['launches'], 1)
        self.assertEqual(self.data['returncode'], 0)
        self.assertEqual(sum(t['launches'] for t in self.data['tests']), 2)

    def test_categories_are_reported_per_class(self):
        cats = {r['id'].rsplit('.', 1)[-1]: (r['category'], r['source'])
                for r in self.data['classes']}
        self.assertEqual(cats, {'Launching': ('integration', 'module'), 'Quiet': ('unit', 'class')})

    def test_a_plain_run_gives_the_same_ids_and_outcomes(self):
        (plain, ran), returncode = tp.run_plain('fixture', self.start_dir, self.root)
        self.assertEqual(returncode, 0)
        self.assertEqual(ran, 3)
        self.assertEqual(plain, {t['id']: t['outcome'] for t in self.data['tests']})


if __name__ == '__main__':
    unittest.main()
