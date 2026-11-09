"""The traversal's git access (stdlib unittest, plan leaf F-09.4).

A traversal (``lineage_trace.Traversal.run``) opens one git scope (``lineage_resolve.
git_scope``): every resolver and the enumeration share one ``planning_adapter.Git`` per
project with one read session, so one ``git cat-file --batch`` process serves the whole
traversal, and it is closed when the traversal ends. These tests check that on a normal
end, an exception and a timeout no process is left, that nothing is kept for the next
traversal, and that the traversal launches only git's read commands. ``OneTraversal`` is
the leaf's benchmark: one traversal of the two-task example, whose result is its launch
count, with projections equal to ``integrations/lineage/examples/`` byte for byte.
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
    """The F-09.4 benchmark: the result is the number of processes one traversal launches."""
    category = 'performance'

    def test_one_traversal_of_the_two_task_example(self):
        for name in ('sample', 'real'):
            with self.subTest(name=name):
                with Launches() as launches:
                    projection = self.trace(samples=name == 'sample')
                self.assertEqual(E.dumps(projection).encode('utf-8'), (E.EXAMPLES / E.FILES[name]).read_bytes())
                self.assertLessEqual(len(launches.argvs), MAX_LAUNCHES, launches.kinds())
                # What they are: the work-tree check, one batch reader, the two file lists.
                self.assertEqual(launches.kinds(), {'rev-parse': 1, 'cat-file --batch': 1, 'ls-tree': 2})
        self.assertEqual(len(Recorded.made), 2)
        self.assertEnded(Recorded.made)


class GitAccess(ExampleCase):
    def test_one_reader_serves_the_traversal_and_ends_with_it(self):
        projection = self.trace()
        self.assertEqual(projection, E.recorded()['sample'])
        (reader,) = Recorded.made
        self.assertEnded([reader])
        self.assertIsNone(R._SCOPE.get())

    def test_an_exception_ends_the_reader(self):
        with mock.patch.object(T._Projection, 'to_json', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.trace()
        self.assertEqual(len(Recorded.made), 1)
        self.assertEnded(Recorded.made)
        self.assertIsNone(R._SCOPE.get())

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


if __name__ == '__main__':
    unittest.main()
