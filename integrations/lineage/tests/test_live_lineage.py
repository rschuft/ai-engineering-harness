"""Live tests of the work, design and objective resolvers against the pinned Backlog.md
1.55.3 and OpenSpec 1.16.0 (stdlib unittest, plan leaf P-03.1).

LiveWork is skipped unless AIEH_BACKLOG and AIEH_OPENSPEC name the tools' entry points,
LiveObjective unless AIEH_OPENSPEC does; install them outside the checkout as
integrations/planning/README.md describes. The project is the P-02.1 two-task fixture,
built in a throwaway directory; the tools' per-user state is kept inside it. Backlog.md
is run only with task list and task view. LiveObjective adds the decision 0008
declaration to the throwaway copy only, then runs openspec validate --strict and
openspec archive --yes there. LiveTrace (P-03.2) runs the lineage traversal over the tasks
the pinned Backlog.md created and lists itself, then again after a real openspec archive.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'e2e'

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
        fx.require_repository_access()  # without Dulwich: REPOSITORY_NEEDS_DULWICH, never a skip
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


OUTCOME = '5c6f4c1e-8d3a-4a3b-9b2e-1f0e7d6c5b4a'
DECLARATION = (f'x-outcomes:\n  {OUTCOME}:\n    item: O1\n'
               f'    acceptance: conversation:qual-02/message-2\n').encode('utf-8')


@unittest.skipUnless(OPENSPEC, 'set AIEH_OPENSPEC to run the live OpenSpec tests')
class LiveObjective(unittest.TestCase):
    """Decision 0008's two unverified points: x-outcomes under openspec validate --strict,
    and the .openspec.yaml bytes across openspec archive."""

    @classmethod
    def setUpClass(cls):
        fx.require_repository_access()
        cls.openspec = fx.adapter.tool_argv(OPENSPEC)
        cls.work = Path(tempfile.mkdtemp(prefix='aieh-lineage-os-'))
        (cls.work / 'home').mkdir()
        cls.env = fx.isolated_env(cls.work / 'home')
        cls.repo = cls.work / 'p'
        with mock.patch.dict(os.environ, cls.env):
            if fx.tool_version(cls.openspec, cls.work) != fx.OPENSPEC_VERSION:
                raise unittest.SkipTest('not the pinned OpenSpec')
            fx.build_repo(cls.repo)
            meta = cls.repo / 'openspec' / 'changes' / fx.CHANGE / '.openspec.yaml'
            meta.write_bytes(meta.read_bytes() + DECLARATION)
            cls.meta_bytes = meta.read_bytes()
            cls.declared = fx.commit_all(cls.repo, 'declare the outcome of O1')

    @classmethod
    def tearDownClass(cls):
        fx.rmtree(cls.work)

    def openspec_run(self, *args):
        with mock.patch.dict(os.environ, self.env):
            return subprocess.run([*self.openspec, *args], cwd=self.repo, capture_output=True, text=True,
                                  encoding='utf-8', stdin=subprocess.DEVNULL, timeout=fx.WAIT_CEILING_S)

    def test_validate_strict_then_archive_keeps_the_declaration(self):
        valid = self.openspec_run('validate', fx.CHANGE, '--strict')
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        report = json.loads(self.openspec_run('validate', fx.CHANGE, '--strict', '--json').stdout)
        self.assertEqual(report['summary']['totals'], {'items': 1, 'passed': 1, 'failed': 0})

        archived = self.openspec_run('archive', fx.CHANGE, '--yes')
        self.assertEqual(archived.returncode, 0, archived.stdout + archived.stderr)
        self.assertFalse((self.repo / 'openspec' / 'changes' / fx.CHANGE).exists())
        moved = sorted((self.repo / 'openspec' / 'changes' / 'archive').glob(f'*-{fx.CHANGE}/.openspec.yaml'))
        self.assertEqual(len(moved), 1)
        self.assertRegex(moved[0].parent.name, rf'^\d{{4}}-\d{{2}}-\d{{2}}-{fx.CHANGE}$')
        self.assertEqual(moved[0].read_bytes(), self.meta_bytes)
        with mock.patch.dict(os.environ, self.env):
            archived_commit = fx.commit_all(self.repo, 'openspec archive')
        resolver = R.ObjectiveResolver(self.repo)
        current = resolver.current(L.parse(f'outcome:{OUTCOME}'))
        self.assertEqual((current.outcome, current.observed_revision), (L.RESOLVED, archived_commit))
        self.assertEqual(current.facts['change'], f'openspec/changes/archive/{moved[0].parent.name}')
        pinned = resolver.resolve(L.parse(f'outcome:{OUTCOME}@{self.declared}'))
        self.assertEqual((pinned.outcome, pinned.facts['change']), (L.RESOLVED, f'openspec/changes/{fx.CHANGE}'))
        self.assertEqual(current.observed_digest, pinned.observed_digest)


@unittest.skipUnless(BACKLOG and OPENSPEC, 'set AIEH_BACKLOG and AIEH_OPENSPEC to run the live tests')
class LiveTrace(unittest.TestCase):
    """The P-03.2 traversal over tasks the pinned Backlog.md created and lists itself, then
    after a real openspec archive (moved, not gone)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(HERE))
        import lineage_example as example
        fx.require_repository_access()
        cls.E = example
        cls.T = example.T
        cls.backlog = fx.adapter.tool_argv(BACKLOG)
        cls.openspec = fx.adapter.tool_argv(OPENSPEC)
        cls.work = Path(tempfile.mkdtemp(prefix='lt-'))  # short: the archived paths are deep
        (cls.work / 'home').mkdir()
        cls.env = fx.isolated_env(cls.work / 'home')
        with mock.patch.dict(os.environ, cls.env):
            if fx.tool_version(cls.backlog, cls.work) != fx.BACKLOG_VERSION:
                raise unittest.SkipTest('not the pinned Backlog.md')
            cls.repo, cls.design_commit, _capture = fx.live_capture(cls.backlog, cls.openspec, cls.work)
            fx.commit_all(cls.repo, 'Backlog.md tasks')
            example.declare(cls.repo)
            cls.declared = fx.commit_all(cls.repo, 'declare the outcome of O1')
        cls.store = cls.work / 'st' / 'integration.sqlite'
        example.build_store(cls.store, [(example.operation_key(t), example.task_intent(t)) for t in ('TASK-1', 'TASK-2')])

    @classmethod
    def tearDownClass(cls):
        fx.rmtree(cls.work)

    def trace(self, outcome):
        with mock.patch.dict(os.environ, self.env):
            auth = self.T.Authorities(R.build_registry(project=self.repo, backlog=self.backlog),
                                      self.E.S.sample_authorities())
            before = fx.git(self.repo, 'status', '--porcelain', '--untracked-files=all', '--ignored')
            projection = self.T.trace(outcome, auth, project=self.repo, backlog=self.backlog, store=self.store)
            self.assertEqual(fx.git(self.repo, 'status', '--porcelain', '--untracked-files=all', '--ignored'), before)
        return projection

    def test_the_chain_through_live_backlog_then_after_archive(self):
        projection = self.trace(f'outcome:{OUTCOME}@{self.declared}')
        self.assertEqual({u['reason'] for u in projection['uncertainties']}, {'sample-authority'},
                         json.dumps(projection['uncertainties'], indent=1))
        tasks = {e['to'] for e in projection['edges'] if e['relation'] == self.T.FULFILLED_BY}
        self.assertEqual(tasks, {'backlog:TASK-1', 'backlog:TASK-2'})
        cited = {e['to'] for e in projection['edges'] if e['relation'] == self.T.CITES}
        self.assertTrue(cited)
        self.assertTrue(all(f'@{self.design_commit}#' in text for text in cited))
        self.assertEqual(len([e for e in projection['edges'] if e['relation'] == self.T.EXECUTED_BY]), 2)

        with mock.patch.dict(os.environ, self.env):
            archived = subprocess.run([*self.openspec, 'archive', fx.CHANGE, '--yes'], cwd=self.repo,
                                      capture_output=True, text=True, encoding='utf-8', stdin=subprocess.DEVNULL,
                                      timeout=fx.WAIT_CEILING_S)
            self.assertEqual(archived.returncode, 0, archived.stdout + archived.stderr)
            fx.commit_all(self.repo, 'openspec archive')
        projection = self.trace(f'outcome:{OUTCOME}')
        nodes = {n['reference']: n for n in projection['nodes']}
        for text in cited:
            with self.subTest(pointer=text):
                self.assertEqual((nodes[text]['resolution']['outcome'], nodes[text]['freshness']),
                                 (L.RESOLVED, self.T.MOVED))
                self.assertRegex(nodes[text]['moved_to']['path'],
                                 rf'^openspec/changes/archive/\d{{4}}-\d{{2}}-\d{{2}}-{fx.CHANGE}/')
        reasons = {u['reason'] for u in projection['uncertainties']}
        self.assertNotIn('gone', reasons)
        self.assertIn('moved', reasons)


if __name__ == '__main__':
    unittest.main()
