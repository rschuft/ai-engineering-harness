"""The traversal's git access (stdlib unittest, plan leaf F-09.4).

A traversal (``lineage_trace.Traversal.run``) is one adapter operation
(``planning_adapter.operation``): every resolver and the enumeration share one
``planning_adapter.Git`` per project with one read session, so one work-tree check and one
``git cat-file --batch`` process serve the whole traversal, and Backlog.md's reads are made once
each; all of it is closed when the traversal ends. These tests check that on a normal end, an
exception and a timeout no process is left, that nothing is kept for the next traversal, and that
the traversal launches only git's read commands. ``OneTraversal`` is the leaf's benchmark: one
traversal of the two-task example, whose result is its launch count, with projections equal to
``integrations/lineage/examples/`` byte for byte.
"""
import collections
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lineage_example as E  # noqa: E402

T, R, L, fx = E.T, E.R, E.L, E.fx
planning = R.planning
HANGS = [sys.executable, '-I', '-c', 'import sys, time; sys.stdin.readline(); time.sleep(300)']
MAX_LAUNCHES = 10  # the leaf's acceptance: one traversal of the two-task example


class Recorded(planning.BatchReader):
    made = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        type(self).made.append(self)


class Launches:
    """A subprocess.Popen that records every argv (subprocess.run goes through it too)."""

    def __init__(self):
        self.argvs = []
        real = subprocess.Popen
        recorder = self

        class Popen(real):
            def __init__(self, args, *a, **k):
                recorder.argvs.append([str(x) for x in args])
                super().__init__(args, *a, **k)

        self.patch = mock.patch.object(subprocess, 'Popen', Popen)

    def __enter__(self):
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()

    def kinds(self):
        out = collections.Counter()
        for argv in self.argvs:
            if Path(argv[0]).name.lower() in ('git', 'git.exe') and argv[1] == '-C':
                out[' '.join(argv[3:5]) if argv[3] == 'cat-file' else argv[3]] += 1
            else:
                out[Path(argv[0]).name] += 1
        return out


class ExampleCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-trace-git-'))
        cls.addClassCleanup(fx.rmtree, cls.tmp)
        cls.repo, cls.store, cls.declared = E.build(cls.tmp)
        cls.outcome = f'outcome:{E.OUTCOME}@{cls.declared}'

    def setUp(self):
        Recorded.made = []
        for patch in (mock.patch.object(planning, 'BatchReader', Recorded), E.in_process_backlog()):
            patch.start()
            self.addCleanup(patch.stop)

    def trace(self, samples=True, repo=None):
        repo = repo or self.repo
        return E.run_trace(self.outcome, E.authorities(repo, samples), repo, self.store)

    def assertEnded(self, readers):
        self.assertTrue(readers)
        for reader in readers:
            self.assertIsNotNone(reader.process.poll(), f'process {reader.process.pid} is still running')


class OneTraversal(ExampleCase):
    """The F-09.4 benchmark: the result is the number of processes one traversal launches, with
    the fake Backlog.md answered in this process and launched as Backlog.md is."""
    category = 'performance'

    def test_one_traversal_of_the_two_task_example(self):
        python = Path(sys.executable).name
        for backlog in ('in-process', 'launched'):
            for name in ('sample', 'real'):
                with self.subTest(backlog=backlog, name=name):
                    patch = mock.patch.object(planning.Backlog, 'runner', None) if backlog == 'launched'                         else mock.patch.object(planning.Backlog, 'runner', planning.Backlog.runner)
                    with patch, Launches() as launches:
                        projection = self.trace(samples=name == 'sample')
                    self.assertEqual(E.dumps(projection).encode('utf-8'),
                                     (E.EXAMPLES / E.FILES[name]).read_bytes())
                    self.assertLessEqual(len(launches.argvs), MAX_LAUNCHES, launches.kinds())
                    # The work-tree check, one batch reader, the two file lists; and, launched,
                    # Backlog.md's three reads (task list once, task view once per task).
                    expected = {'rev-parse': 1, 'cat-file --batch': 1, 'ls-tree': 2}
                    if backlog == 'launched':
                        expected[python] = 3
                    self.assertEqual(launches.kinds(), expected)
        self.assertEqual(len(Recorded.made), 4)
        self.assertEnded(Recorded.made)


class SpacedChangeFolder(unittest.TestCase):
    """An OpenSpec change folder whose name holds a space resolves as it did at 352920a, before
    the batch reader (the Overseer's ruling R1): the outcome, code and declaring change below
    were observed there with the same repositories."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-trace-space-'))
        cls.addClassCleanup(fx.rmtree, cls.tmp)

    def setUp(self):
        patch = E.in_process_backlog()
        patch.start()
        self.addCleanup(patch.stop)

    def resolve_both(self, repo, revision):
        resolver = R.ObjectiveResolver(repo)
        reference = L.parse(f'outcome:{E.OUTCOME}@{revision}')
        out = {}
        for method in ('resolve', 'current'):
            r = getattr(resolver, method)(reference)
            out[method] = (r.outcome, r.code, (r.facts or {}).get('change'), r.observed_revision == revision)
        return out

    def test_the_declaring_change_in_a_folder_with_a_space(self):
        repo = self.tmp / 'a'
        E.build_project(repo)
        fx.git(repo, 'mv', E.CHANGE_DIR, 'openspec/changes/qual 02 spaced')
        moved = fx.commit_all(repo, 'rename', date='2026-11-08T00:00:00Z')
        expected = (L.RESOLVED, None, 'openspec/changes/qual 02 spaced', True)
        self.assertEqual(self.resolve_both(repo, moved), {'resolve': expected, 'current': expected})

    def test_a_sibling_change_folder_with_a_space(self):
        repo = self.tmp / 'b'
        E.build_project(repo)
        fx.write(repo, {'openspec/changes/other change/.openspec.yaml': b'schema: intent-driven' + bytes([10])})
        sibling = fx.commit_all(repo, 'sibling', date='2026-11-08T00:00:00Z')
        expected = (L.RESOLVED, None, E.CHANGE_DIR, True)
        self.assertEqual(self.resolve_both(repo, sibling), {'resolve': expected, 'current': expected})


class GitAccess(ExampleCase):
    def test_one_reader_serves_the_traversal_and_ends_with_it(self):
        projection = self.trace()
        self.assertEqual(projection, E.recorded()['sample'])
        (reader,) = Recorded.made
        self.assertEnded([reader])
        self.assertIsNone(planning.current_operation())

    def test_an_exception_ends_the_reader(self):
        with mock.patch.object(T._Projection, 'to_json', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.trace()
        self.assertEqual(len(Recorded.made), 1)
        self.assertEnded(Recorded.made)
        self.assertIsNone(planning.current_operation())

    def test_a_timeout_fails_closed_and_leaves_no_process(self):
        with mock.patch.object(planning.Git, 'batch_argv', return_value=HANGS), \
                mock.patch.object(planning, 'TOOL_TIMEOUT_S', 0.2):
            started = time.monotonic()
            projection = self.trace(samples=False)
            elapsed = time.monotonic() - started
        (reader,) = Recorded.made  # one wait: after it the reader fails closed at once
        self.assertEnded([reader])
        self.assertLess(elapsed, 60)
        self.assertIsNone(projection['sources']['project_head'])
        (objective,) = [n for n in projection['nodes'] if n['role'] == 'objective']
        self.assertEqual((objective['authority_mode'], objective['resolution']['outcome'],
                          objective['resolution']['code']), (T.UNAVAILABLE, L.AUTHORITY_UNAVAILABLE, 'GIT_FAILED'))
        self.assertEqual(projection['verdict'], 'incomplete')
        for node in projection['nodes']:
            if node['role'] in ('objective', 'design'):
                with self.subTest(node=node['reference']):
                    self.assertNotEqual(node['resolution']['outcome'], L.RESOLVED)

    def test_nothing_is_kept_for_the_next_traversal(self):
        repo = self.tmp / 'moving'
        E.build_project(repo)
        first = self.trace(repo=repo)
        fx.write(repo, {'README.md': b'moved on\n'})
        later = fx.commit_all(repo, 'later', date='2026-11-08T00:00:00Z')
        second = self.trace(repo=repo)
        self.assertEqual(first['sources']['project_head'], self.declared)
        self.assertEqual(second['sources']['project_head'], later)
        self.assertEqual(len(Recorded.made), 2)
        self.assertEnded(Recorded.made)

    def test_the_traversal_launches_only_git_reads(self):
        with Launches() as launches:
            self.trace(samples=False)
        for argv in launches.argvs:
            with self.subTest(argv=argv[:5]):
                self.assertEqual((Path(argv[0]).name.lower().removesuffix('.exe'), argv[1], argv[2]),
                                 ('git', '-C', str(self.repo)))
                self.assertIn(argv[3], ('rev-parse', 'cat-file', 'ls-tree', 'archive'))
                if argv[3] == 'cat-file':
                    self.assertEqual(argv[4:], ['--batch'])


class ResolverOperation(unittest.TestCase):
    """A resolver entry point called on its own is one operation (ruling R3): one work-tree check
    and one batch reader, ended when it returns, raises or times out."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-trace-op-'))
        cls.addClassCleanup(fx.rmtree, cls.tmp)
        cls.repo = cls.tmp / 'p'
        cls.design, cls.declared = E.build_project(cls.repo)
        cls.pointer = planning.make_pointer(planning.Git(cls.repo), E.CHANGE, 'design.md', cls.design).text

    def setUp(self):
        Recorded.made = []
        patch = mock.patch.object(planning, 'BatchReader', Recorded)
        patch.start()
        self.addCleanup(patch.stop)
        self.resolver = R.DesignResolver(self.repo)
        self.reference = L.parse(self.pointer)

    def assertEnded(self, count):
        self.assertEqual(len(Recorded.made), count)
        for reader in Recorded.made:
            self.assertIsNotNone(reader.process.poll(), f'process {reader.process.pid} is still running')
        self.assertIsNone(planning.current_operation())

    def test_each_call_is_one_operation(self):
        with mock.patch.object(planning.Git, '_run', autospec=True, side_effect=planning.Git._run) as runs:
            for method in (self.resolver.resolve, self.resolver.current):
                self.assertEqual(method(self.reference).outcome, L.RESOLVED)
        self.assertEqual([c.args[1] for c in runs.call_args_list], ['rev-parse', 'rev-parse'])
        self.assertEnded(2)

    def test_an_exception_ends_the_reader(self):
        with mock.patch.object(planning.Git, 'blob', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.resolver.resolve(self.reference)
        self.assertEnded(1)

    def test_a_timeout_fails_closed_and_ends_the_reader(self):
        with mock.patch.object(planning.Git, 'batch_argv', return_value=HANGS), \
                mock.patch.object(planning, 'TOOL_TIMEOUT_S', 0.2):
            result = self.resolver.resolve(self.reference)
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'GIT_FAILED'))
        self.assertEnded(1)


if __name__ == '__main__':
    unittest.main()
