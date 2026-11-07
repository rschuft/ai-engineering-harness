"""Live tests of the work and design resolvers against the pinned Backlog.md 1.55.3 and
OpenSpec 1.16.0 (stdlib unittest, plan leaf P-03.1).

Skipped unless AIEH_BACKLOG and AIEH_OPENSPEC name the tools' entry points, installed
outside the checkout as integrations/planning/README.md describes. The project is the
P-02.1 two-task fixture, built in a throwaway directory; the tools' per-user state is
kept inside it. Backlog.md is run only with task list and task view.
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
LINEAGE_DIR = HERE.parent
REPO = LINEAGE_DIR.parents[1]
PLANNING_TESTS = REPO / 'integrations' / 'planning' / 'tests'


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


R = _load('lineage_resolve', LINEAGE_DIR / 'lineage_resolve.py')
L = R.lineage
sys.path.insert(0, str(PLANNING_TESTS))
import two_task_fixture as fx  # noqa: E402

BACKLOG = os.environ.get('AIEH_BACKLOG')
OPENSPEC = os.environ.get('AIEH_OPENSPEC')


@unittest.skipUnless(BACKLOG and OPENSPEC, 'set AIEH_BACKLOG and AIEH_OPENSPEC to run the live tests')
class LiveWork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backlog = fx.adapter.tool_argv(BACKLOG)
        openspec = fx.adapter.tool_argv(OPENSPEC)
        cls.work = Path(tempfile.mkdtemp(prefix='aieh-lineage-live-'))
        (cls.work / 'home').mkdir()
        cls.env = fx.isolated_env(cls.work / 'home')
        with mock.patch.dict(os.environ, cls.env):
            if fx.tool_version(cls.backlog, cls.work) != fx.BACKLOG_VERSION:
                raise unittest.SkipTest('not the pinned Backlog.md')
            cls.repo, cls.design_commit, cls.capture = fx.live_capture(cls.backlog, openspec, cls.work)
            cls.tasks_commit = fx.commit_all(cls.repo, 'Backlog.md tasks')
        cls.registry = R.build_registry(project=cls.repo, backlog=cls.backlog)

    @classmethod
    def tearDownClass(cls):
        fx.rmtree(cls.work)

    def resolve(self, text, current=False):
        with mock.patch.dict(os.environ, self.env):
            return (self.registry.current if current else self.registry.resolve)(text)

    def test_tasks_resolve_in_the_working_tree_and_at_the_commit(self):
        before = fx.git(self.repo, 'status', '--porcelain', '--untracked-files=all')
        for task in ('TASK-1', 'TASK-2'):
            with self.subTest(task=task):
                self.assertEqual(self.resolve(f'backlog:{task}').outcome, L.RESOLVED)
                pinned = self.resolve(f'backlog:{task}@{self.tasks_commit}')
                self.assertEqual((pinned.outcome, pinned.observed_revision), (L.RESOLVED, self.tasks_commit))
        self.assertEqual(fx.git(self.repo, 'status', '--porcelain', '--untracked-files=all'), before)

    def test_missing_and_mismatched(self):
        result = self.resolve('backlog:TASK-9')
        self.assertEqual((result.outcome, result.code), (L.MISSING, 'WORK_MISSING'))
        result = self.resolve(f'backlog:TASK-9@{self.tasks_commit}')
        self.assertEqual((result.outcome, result.code), (L.MISSING, 'WORK_MISSING'))
        result = self.resolve('backlog:TASK-1@' + '0' * 40)
        self.assertEqual((result.outcome, result.code), (L.REVISION_MISMATCH, 'WORK_REVISION_MISSING'))

    def test_before_backlog_existed_the_authority_is_unavailable(self):
        result = self.resolve(f'backlog:TASK-1@{self.design_commit}')
        self.assertEqual(result.outcome, L.AUTHORITY_UNAVAILABLE)
        self.assertIn(result.code, ('BACKLOG_LIST_FAILED', 'BACKLOG_VIEW_FAILED'))

    def test_a_tasks_design_references_resolve(self):
        view = self.capture['task-view-TASK-2.json']['task']
        pointers = [r for r in view['references'] if r.startswith('openspec:')]
        self.assertEqual(len(pointers), 2)
        for text in pointers:
            with self.subTest(pointer=text):
                result = self.resolve(text)
                self.assertEqual((result.outcome, result.observed_revision), (L.RESOLVED, self.design_commit))
                current = self.resolve(text, current=True)
                self.assertEqual((current.outcome, current.observed_revision), (L.RESOLVED, self.tasks_commit))
                self.assertEqual(current.observed_digest, result.observed_digest)  # the design did not change


if __name__ == '__main__':
    unittest.main()
