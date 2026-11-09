"""The traversal's repository access (stdlib unittest, plan leaves F-09.4 and F-10.3).

A traversal (``lineage_trace.Traversal.run``) is one adapter operation
(``planning_adapter.operation``): every resolver and the enumeration share one
``planning_adapter.Git`` per project with one read session, so one work-tree check and one opened
repository (the shared repository-access module over Dulwich, decision 0014) serve the whole
traversal, and Backlog.md's reads are made once each; all of it is closed when the traversal
ends. These tests check that on a normal end, an exception and a damaged repository nothing is
left open, that nothing is kept for the next traversal, and that the traversal launches no git.
``OneTraversal`` is the benchmark: one traversal of the two-task example, whose result is its
launch count (none in process), with projections equal to ``integrations/lineage/examples/``
byte for byte; and its repository access against the git oracle, measured interleaved in the
same run (decision 0014: at least 4x faster for the traversal, 8x for a one-shot resolve).
"""
import collections
import contextlib
import statistics
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
ra = planning.repository_access
MAX_LAUNCHES = 10  # F-09.4's acceptance: one traversal of the two-task example
# Decision 0014 (Consequences): against the git oracle measured interleaved in the same run, the
# traversal's repository access at least 4x faster and a one-shot resolve at least 8x faster.
TRAVERSAL_RATIO, ONE_SHOT_RATIO = 4, 8
TRAVERSAL_ROUNDS, ONE_SHOT_ROUNDS = 15, 30


class Recorded(planning._Session):
    """A read session that keeps every instance that opened its repository."""
    made = []

    def _open(self):
        first = self.repository is None and not self.closed
        repository = super()._open()
        if first:
            self.opened = repository
            type(self).made.append(self)
        return repository


@contextlib.contextmanager
def module_calls():
    """Record every read the module answers for the facade (commit, read, files), in order."""
    seen = []
    with contextlib.ExitStack() as stack:
        for method in ('commit', 'read', 'files'):
            real = getattr(ra.Repository, method)

            def spy(repository, *args, _real=real, _method=method):
                seen.append((_method, *args))
                return _real(repository, *args)

            stack.enter_context(mock.patch.object(ra.Repository, method, spy))
        yield seen


def git_oracle(repo, requests):
    """The traversal's repository access through git, launched as the adapter launched it before
    F-10.3 (each process one tree): the work-tree check, one ``cat-file --batch`` for every
    revision and object read, one ``ls-tree`` per file list. Returns git's answers."""
    git = ['git', '-C', str(repo)]
    env = planning.tool_env()
    if planning.run_tree([*git, 'rev-parse', '--show-toplevel'], env=env).returncode != 0:
        raise AssertionError('git: not a work tree')
    names = [args[0] + '^{commit}' if op == 'commit' else args[0] for op, *args in requests if op != 'files']
    tree = planning.ProcessTree([*git, 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env)
    try:
        out, _ = tree.process.communicate(''.join(name + chr(10) for name in names).encode('utf-8'),
                                          timeout=planning.TOOL_TIMEOUT_S)
    finally:
        tree.close(planning.TOOL_TIMEOUT_S)
    objects = iter(_batch_answers(out))
    answers = []
    for op, *args in requests:
        if op == 'files':
            listed = planning.run_tree([*git, 'ls-tree', '-r', '-z', '--name-only', args[0], '--', args[1] + '/'],
                                       env=env).stdout
            answers.append([name.decode('utf-8') for name in listed.split(bytes([0])) if name])
        else:
            found = next(objects)
            answers.append(None if found is None else found[0] if op == 'commit' else found)
    return answers


def _batch_answers(out):
    """(oid, type, bytes) or None per request of a ``cat-file --batch`` output."""
    answers, at = [], 0
    while at < len(out):
        end = out.index(bytes([10]), at)
        fields = out[at:end].split(bytes([32]))
        at = end + 1
        if fields[-1] in (b'missing', b'ambiguous'):
            answers.append(None)
            continue
        size = int(fields[2])
        answers.append((fields[0].decode('ascii'), fields[1].decode('ascii'), out[at:at + size]))
        at += size + 1
    return answers


def module_access(repo, requests):
    """The same access through the facade's module: the work-tree check (open and close), then
    one opened repository answering every request."""
    planning.check_work_tree(repo)
    with ra.open_repository(repo, config=planning.CONFIG_POLICY) as repository:
        return [getattr(repository, op)(*args) for op, *args in requests]


def interleaved(rounds, first, second):
    """Median seconds of FIRST and SECOND, run alternately ROUNDS times each."""
    times = ([], [])
    for _ in range(rounds):
        for index, work in enumerate((first, second)):
            started = time.perf_counter()
            work()
            times[index].append(time.perf_counter() - started)
    return statistics.median(times[0]), statistics.median(times[1])


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
        fx.require_repository_access()  # without Dulwich: REPOSITORY_NEEDS_DULWICH, never a skip
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-trace-git-'))
        cls.addClassCleanup(fx.rmtree, cls.tmp)
        cls.repo, cls.store, cls.declared = E.build(cls.tmp)
        cls.outcome = f'outcome:{E.OUTCOME}@{cls.declared}'

    def setUp(self):
        Recorded.made = []
        for patch in (mock.patch.object(planning, '_Session', Recorded), E.in_process_backlog()):
            patch.start()
            self.addCleanup(patch.stop)

    def trace(self, samples=True, repo=None):
        repo = repo or self.repo
        return E.run_trace(self.outcome, E.authorities(repo, samples), repo, self.store)

    def assertEnded(self, sessions):
        self.assertTrue(sessions)
        for session in sessions:
            self.assertTrue(session.closed, 'the session is still open')
            self.assertIsNone(session.opened._dul, 'its repository is still open')


class OneTraversal(ExampleCase):
    """The F-09.4 benchmark: the result is the number of processes one traversal launches, with
    the fake Backlog.md answered in this process and launched as Backlog.md is; and (F-10.3) the
    repository access against the git oracle, interleaved in this run (``measured``)."""
    category = 'performance'
    measured = None

    def test_one_traversal_of_the_two_task_example(self):
        python = Path(sys.executable).name
        for backlog in ('in-process', 'launched'):
            for name in ('sample', 'real'):
                with self.subTest(backlog=backlog, name=name):
                    patch = mock.patch.object(planning.Backlog, 'runner', None) if backlog == 'launched' \
                        else mock.patch.object(planning.Backlog, 'runner', planning.Backlog.runner)
                    with patch, Launches() as launches:
                        projection = self.trace(samples=name == 'sample')
                    self.assertEqual(E.dumps(projection).encode('utf-8'),
                                     (E.EXAMPLES / E.FILES[name]).read_bytes())
                    self.assertLessEqual(len(launches.argvs), MAX_LAUNCHES, launches.kinds())
                    # No git (the repository is read in this process); launched, Backlog.md's
                    # three reads (task list once, task view once per task).
                    expected = {python: 3} if backlog == 'launched' else {}
                    self.assertEqual(launches.kinds(), expected)
        self.assertEqual(len(Recorded.made), 4)
        self.assertEnded(Recorded.made)
        self.check_against_the_git_oracle()

    def check_against_the_git_oracle(self):
        with module_calls() as requests:
            self.assertEqual(self.trace(), E.recorded()['sample'])
        requests = list(requests)
        self.assertEqual(module_access(self.repo, requests), git_oracle(self.repo, requests))  # equal answers
        git_s, module_s = interleaved(TRAVERSAL_ROUNDS, lambda: git_oracle(self.repo, requests),
                                      lambda: module_access(self.repo, requests))
        resolve = ['git', '-C', str(self.repo), 'rev-parse', '--verify', '--quiet', 'HEAD^{commit}']
        env = planning.tool_env()

        def module_resolve():
            with ra.open_repository(self.repo, config=planning.CONFIG_POLICY) as repository:
                return repository.commit('HEAD')

        self.assertEqual(planning.run_tree(resolve, env=env).stdout.decode('ascii').strip(), module_resolve())
        git_one, module_one = interleaved(ONE_SHOT_ROUNDS, lambda: planning.run_tree(resolve, env=env),
                                          module_resolve)
        type(self).measured = measured = {
            'requests': dict(collections.Counter(op for op, *_ in requests)),
            'traversal_ms': {'git': round(git_s * 1000, 2), 'module': round(module_s * 1000, 2),
                             'ratio': round(git_s / module_s, 1), 'rounds': TRAVERSAL_ROUNDS},
            'one_shot_ms': {'git': round(git_one * 1000, 3), 'module': round(module_one * 1000, 3),
                            'ratio': round(git_one / module_one, 1), 'rounds': ONE_SHOT_ROUNDS}}
        self.assertGreaterEqual(git_s, TRAVERSAL_RATIO * module_s, measured)
        self.assertGreaterEqual(git_one, ONE_SHOT_RATIO * module_one, measured)


class SpacedChangeFolder(unittest.TestCase):
    """An OpenSpec change folder whose name holds a space resolves as it did at 352920a, before
    the batch reader (the Overseer's ruling R1): the outcome, code and declaring change below
    were observed there with the same repositories."""

    @classmethod
    def setUpClass(cls):
        fx.require_repository_access()
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
        (session,) = Recorded.made
        self.assertEnded([session])
        self.assertIsNone(planning.current_operation())

    def test_an_exception_ends_the_reader(self):
        with mock.patch.object(T._Projection, 'to_json', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.trace()
        self.assertEqual(len(Recorded.made), 1)
        self.assertEnded(Recorded.made)
        self.assertIsNone(planning.current_operation())

    def test_a_timeout_fails_closed_and_leaves_no_process(self):
        # Every object of the project damaged (no zlib stream): each read fails visibly at once
        # (GIT_FAILED; there is no process to wait on), and the repository is closed at the end.
        repo = self.tmp / 'damaged'
        E.build_project(repo)
        for oid in fx.loose_objects(repo):
            fx.damage_object(repo, oid, 'zlib')
        with mock.patch.object(planning, 'TOOL_TIMEOUT_S', 0.2):
            started = time.monotonic()
            projection = self.trace(samples=False, repo=repo)
            elapsed = time.monotonic() - started
        (session,) = Recorded.made
        self.assertEnded([session])
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
        # Since F-10.3 the traversal launches no git at all (decision 0014): with Backlog.md
        # answered in this process it launches nothing.
        with Launches() as launches:
            self.trace(samples=False)
        self.assertEqual(launches.argvs, [])


class ResolverOperation(unittest.TestCase):
    """A resolver entry point called on its own is one operation (ruling R3): one work-tree check
    and one opened repository, ended when it returns, raises or meets a damaged repository."""

    @classmethod
    def setUpClass(cls):
        fx.require_repository_access()
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-trace-op-'))
        cls.addClassCleanup(fx.rmtree, cls.tmp)
        cls.repo = cls.tmp / 'p'
        cls.design, cls.declared = E.build_project(cls.repo)
        cls.pointer = planning.make_pointer(planning.Git(cls.repo), E.CHANGE, 'design.md', cls.design).text

    def setUp(self):
        Recorded.made = []
        patch = mock.patch.object(planning, '_Session', Recorded)
        patch.start()
        self.addCleanup(patch.stop)
        self.resolver = R.DesignResolver(self.repo)
        self.reference = L.parse(self.pointer)

    def assertEnded(self, count):
        self.assertEqual(len(Recorded.made), count)
        for session in Recorded.made:
            self.assertTrue(session.closed, 'the session is still open')
            self.assertIsNone(session.opened._dul, 'its repository is still open')
        self.assertIsNone(planning.current_operation())

    def test_each_call_is_one_operation(self):
        with mock.patch.object(planning, 'check_work_tree', wraps=planning.check_work_tree) as checks:
            for method in (self.resolver.resolve, self.resolver.current):
                self.assertEqual(method(self.reference).outcome, L.RESOLVED)
        self.assertEqual(checks.call_count, 2)
        self.assertEnded(2)

    def test_an_exception_ends_the_reader(self):
        with mock.patch.object(planning.Git, 'blob', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.resolver.resolve(self.reference)
        self.assertEnded(1)

    def test_a_timeout_fails_closed_and_ends_the_reader(self):
        # The design commit's object damaged (no zlib stream): GIT_FAILED at once, and the
        # repository is closed when the call returns.
        repo = self.tmp / 'damaged'
        if not repo.exists():
            E.build_project(repo)
            fx.damage_object(repo, self.design, 'zlib')
        result = R.DesignResolver(repo).resolve(self.reference)
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'GIT_FAILED'))
        self.assertEnded(1)


if __name__ == '__main__':
    unittest.main()
