"""Tests for integrations/lineage/lineage_resolve.py: the read-only resolvers and the
command line (stdlib unittest, plan leaf P-03.1).

Offline. Every resolver is exercised for each outcome it declares, against throwaway git
repositories, the P-02 fake Backlog.md and its recorded fixtures, and F-05.2 effects-store
fixtures. The effects fixtures reuse the effects tests' own permission helpers, which set
the DACL of directories these tests create (custody principal: the test process's SID),
and the library-only fixture location policy.
"""
import contextlib
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
LINEAGE_DIR = HERE.parent
REPO = LINEAGE_DIR.parents[1]
PLANNING_TESTS = REPO / 'integrations' / 'planning' / 'tests'
EFFECTS_TESTS = REPO / 'integrations' / 'effects' / 'tests'


def _load(name, path, fresh=False):
    module = None if fresh else sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


# The effects tests' module first: it registers the effects_store module that the
# resolver then uses, so fixtures and resolver share one module.
effects_tests = _load('aieh_lineage_effects_helpers', EFFECTS_TESTS / 'test_effects_store.py')
R = _load('lineage_resolve', LINEAGE_DIR / 'lineage_resolve.py')
L = R.lineage
planning = R.planning
sys.path.insert(0, str(PLANNING_TESTS))
import two_task_fixture as fx  # noqa: E402
import fake_backlog  # noqa: E402

FAKE_BACKLOG = [sys.executable, '-I', '-B', str(PLANNING_TESTS / 'fake_backlog.py')]
RECORDED = PLANNING_TESTS / 'fixtures'
CHANGE = fx.CHANGE
CLI = [sys.executable, '-I', '-B', str(LINEAGE_DIR / 'lineage_resolve.py')]
WAIT_CEILING_S = 120
ABSENT = '0123456789abcdef0123456789abcdef01234567'
OUTCOME = '5c6f4c1e-8d3a-4a3b-9b2e-1f0e7d6c5b4a'


def git(repo, *args):
    return fx.git(repo, *args)


def tree_state(repo):
    """What a read-only resolver must leave unchanged in a repository."""
    return (git(repo, 'status', '--porcelain', '--untracked-files=all', '--ignored'),
            git(repo, 'for-each-ref'), fx.head(repo),  # HEAD's commit, read from its ref
            git(repo, 'count-objects', '-v'))


class TempDirCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fx.require_repository_access()  # without Dulwich: REPOSITORY_NEEDS_DULWICH, never a skip
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-lineage-test-'))

    @classmethod
    def tearDownClass(cls):
        fx.rmtree(cls.tmp)


# ---------------------------------------------------------------------------
# design

class DesignResolution(TempDirCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.repo = cls.tmp / 'project'
        cls.commit = fx.build_repo(cls.repo)
        g = planning.Git(cls.repo)
        cls.pointer = planning.make_pointer(g, CHANGE, 'design.md', cls.commit)
        cls.ref = L.parse(cls.pointer.text)
        cls.other_digest = planning.make_pointer(g, CHANGE, 'proposal.md', cls.commit).digest
        cls.resolver = R.DesignResolver(cls.repo)

    def test_resolved_reports_the_pinned_revision_and_digest(self):
        before = tree_state(self.repo)
        result = self.resolver.resolve(self.ref)
        self.assertEqual(result.outcome, L.RESOLVED)
        self.assertEqual((result.observed_revision, result.observed_digest), (self.commit, self.pointer.digest))
        self.assertEqual((result.reference, result.kind, result.authority), (self.ref.text, 'design', 'OpenSpec'))
        self.assertEqual(tree_state(self.repo), before)

    def test_missing_artifact(self):
        ref = L.DesignRef(CHANGE, 'nope.md', self.commit, self.pointer.digest)
        result = self.resolver.resolve(ref)
        self.assertEqual((result.outcome, result.code), (L.MISSING, 'POINTER_ARTIFACT_MISSING'))

    def test_changed_sha_is_a_revision_mismatch(self):
        ref = L.DesignRef(CHANGE, 'design.md', ABSENT, self.pointer.digest)
        result = self.resolver.resolve(ref)
        self.assertEqual((result.outcome, result.code), (L.REVISION_MISMATCH, 'POINTER_REVISION_MISSING'))

    def test_digest_mismatch_reports_the_observed_digest(self):
        ref = L.DesignRef(CHANGE, 'design.md', self.commit, self.other_digest)
        result = self.resolver.resolve(ref)
        self.assertEqual((result.outcome, result.code), (L.DIGEST_MISMATCH, 'POINTER_DIGEST_MISMATCH'))
        self.assertEqual(result.observed_digest, self.pointer.digest)

    def test_authority_unavailable(self):
        empty = self.tmp / 'not-a-repo'
        empty.mkdir(exist_ok=True)
        for resolver in (R.DesignResolver(empty), R.DesignResolver(self.tmp / 'absent')):
            for method in (resolver.resolve, resolver.current):
                with self.subTest(method=method.__name__), fx.ceiling(self.tmp):
                    result = method(self.ref)
                    self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'PROJECT_UNAVAILABLE'))
        with mock.patch.object(planning.Git, 'blob', side_effect=planning.PlanningError('GIT_FAILED', 'boom')):
            result = self.resolver.resolve(self.ref)
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'GIT_FAILED'))

    def test_a_new_design_revision_keeps_the_pin_and_shows_in_current(self):
        repo = self.tmp / 'revised'
        first = fx.build_repo(repo)
        ref = L.parse(planning.make_pointer(planning.Git(repo), CHANGE, 'design.md', first).text)
        resolver = R.DesignResolver(repo)
        current = resolver.current(ref)
        self.assertEqual((current.outcome, current.query, current.observed_revision, current.observed_digest),
                         (L.RESOLVED, 'current', first, ref.digest))
        path = repo / 'openspec' / 'changes' / CHANGE / 'design.md'
        path.write_bytes(path.read_bytes() + b'\nRevised.\n')
        second = fx.commit_all(repo, 'revise the design')
        pinned = resolver.resolve(ref)
        self.assertEqual((pinned.outcome, pinned.observed_revision), (L.RESOLVED, first))
        current = resolver.current(ref)
        self.assertEqual(current.outcome, L.RESOLVED)
        self.assertEqual(current.observed_revision, second)
        self.assertNotEqual(current.observed_digest, ref.digest)
        (repo / 'openspec' / 'changes' / CHANGE / 'design.md').unlink()
        fx.commit_all(repo, 'remove the design')
        gone = resolver.current(ref)
        self.assertEqual((gone.outcome, gone.code), (L.MISSING, 'POINTER_ARTIFACT_MISSING'))
        self.assertEqual(resolver.resolve(ref).outcome, L.RESOLVED)  # the pinned revision is still there


# ---------------------------------------------------------------------------
# objective (decision 0008)

CHANGE_DIR = f'openspec/changes/{CHANGE}'
ARCHIVED_DIR = f'openspec/changes/archive/2026-11-07-{CHANGE}'
ACCEPTANCE = 'conversation:qual-02/message-2'


def declaration(outcome=OUTCOME, item='O1', acceptance=ACCEPTANCE):
    return f'x-outcomes:\n  {outcome}:\n    item: {item}\n    acceptance: {acceptance}\n'.encode('utf-8')


def declare(repo, change_dir=CHANGE_DIR, data=None):
    """Append an x-outcomes declaration to a change's .openspec.yaml in a throwaway
    repository (never the P-01.2 fixture itself, whose bytes the P-02.1 capture pins)."""
    meta = repo / change_dir / '.openspec.yaml'
    meta.write_bytes(meta.read_bytes() + (declaration() if data is None else data))


def edit(repo, path, old, new):
    target = repo / path
    text = target.read_bytes()
    assert text.count(old) >= 1, (path, old)
    target.write_bytes(text.replace(old, new, 1))


class ObjectiveResolution(TempDirCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.repo = cls.tmp / 'project'
        cls.undeclared = fx.build_repo(cls.repo)
        declare(cls.repo)
        cls.declared = fx.commit_all(cls.repo, 'accept O1 of qual-02: declare its outcome id')
        cls.proposal_digest = hashlib.sha256((cls.repo / CHANGE_DIR / 'proposal.md').read_bytes()).hexdigest()
        cls.resolver = R.ObjectiveResolver(cls.repo)

    def scenario(self, name, change):
        """A fresh repository: the qual-02 change, CHANGE(repo) applied, committed."""
        repo = self.tmp / name
        fx.build_repo(repo)
        change(repo)
        return repo, fx.commit_all(repo, name)

    def ask(self, text, repo=None, current=False):
        resolver = R.ObjectiveResolver(repo) if repo else self.resolver
        return (resolver.current if current else resolver.resolve)(L.parse(text))

    def test_resolved_pinned_unpinned_and_current(self):
        before = tree_state(self.repo)
        for text, query in ((f'outcome:{OUTCOME}@{self.declared}', 'reference'), (f'outcome:{OUTCOME}', 'reference'),
                            (f'outcome:{OUTCOME}@{self.undeclared}', 'current')):
            with self.subTest(text=text, query=query):
                result = self.ask(text, current=query == 'current')
                self.assertEqual((result.outcome, result.authority, result.query), (L.RESOLVED, 'OpenSpec', query))
                self.assertEqual((result.observed_revision, result.observed_digest),
                                 (self.declared, self.proposal_digest))
                self.assertEqual(result.facts, {
                    'change': CHANGE_DIR, 'item': 'O1', 'acceptance': ACCEPTANCE,
                    'statement': 'A product added to the catalogue appears in search results within 5 minutes of '
                                 'being added, so customers can find new stock.',
                    'source': ['Q1', ACCEPTANCE], 'acceptance_criteria': ['AC1']})
        self.assertEqual(tree_state(self.repo), before)

    def test_missing(self):
        other = '0d9e8f7a-6b5c-4d3e-8f1a-2b3c4d5e6f70'
        result = self.ask(f'outcome:{other}')
        self.assertEqual((result.outcome, result.code), (L.MISSING, 'OUTCOME_MISSING'))
        result = self.ask(f'outcome:{OUTCOME}@{self.undeclared}')  # before the acceptance was recorded
        self.assertEqual((result.outcome, result.code), (L.MISSING, 'OUTCOME_MISSING'))

    def test_revision_missing(self):
        result = self.ask(f'outcome:{OUTCOME}@{ABSENT}')
        self.assertEqual((result.outcome, result.code), (L.REVISION_MISMATCH, 'OUTCOME_REVISION_MISSING'))

    def test_two_declaring_changes_are_ambiguous(self):
        def copy_change(repo):
            declare(repo)
            shutil.copytree(repo / CHANGE_DIR, repo / 'openspec' / 'changes' / 'qual-02-copy')
        repo, _ = self.scenario('amb', copy_change)
        result = self.ask(f'outcome:{OUTCOME}', repo)
        self.assertEqual((result.outcome, result.code), (L.AMBIGUOUS, 'OUTCOME_AMBIGUOUS'))
        self.assertIn('qual-02-copy', result.detail)

    def test_not_accepted(self):
        cases = {
            'proposed item': lambda repo: (declare(repo), edit(
                repo, f'{CHANGE_DIR}/proposal.md',
                b'- authority: accepted\n- acceptance: conversation:qual-02/message-2\n',
                b'- authority: proposed\n')),
            'proposed item keeping its acceptance': lambda repo: (declare(repo), edit(
                repo, f'{CHANGE_DIR}/proposal.md', b'- authority: accepted\n- acceptance: conversation:qual-02/message-2\n',
                b'- authority: proposed\n- acceptance: conversation:qual-02/message-2\n')),
            'other acceptance': lambda repo: declare(repo, data=declaration(acceptance='conversation:qual-02/message-9')),
            'absent item': lambda repo: declare(repo, data=declaration(item='O7')),
        }
        for number, (name, change) in enumerate(cases.items()):
            with self.subTest(case=name):
                repo, commit = self.scenario(f'n{number}', change)
                result = self.ask(f'outcome:{OUTCOME}', repo)
                self.assertEqual((result.outcome, result.code, result.observed_revision),
                                 (L.MISSING, 'OUTCOME_NOT_ACCEPTED', commit))

    def test_metadata_invalid(self):
        cases = {
            'flow mapping': lambda repo: declare(repo, data=b'x-outcomes: {}\n'),
            'no proposal': lambda repo: (declare(repo), (repo / CHANGE_DIR / 'proposal.md').unlink()),
            'unreadable intent record': lambda repo: (declare(repo), edit(
                repo, f'{CHANGE_DIR}/proposal.md', b'## Intent Record', b'## Intent Notes')),
            'another change is malformed': lambda repo: (declare(repo), shutil.copytree(
                repo / CHANGE_DIR, repo / 'openspec' / 'changes' / 'other'), declare(
                repo, 'openspec/changes/other', b'x-outcomes:\n  not-a-uuid:\n    item: O1\n')),
        }
        for number, (name, change) in enumerate(cases.items()):
            with self.subTest(case=name):
                repo, _ = self.scenario(f'i{number}', change)
                result = self.ask(f'outcome:{OUTCOME}', repo)
                self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'OUTCOME_METADATA_INVALID'))

    def test_the_declaration_reader_is_strict(self):
        good = declaration()
        self.assertEqual(R.read_x_outcomes(b'schema: intent-driven\n' + good + b'other: 1\n'),
                         {OUTCOME: {'item': 'O1', 'acceptance': ACCEPTANCE}})
        self.assertEqual(R.read_x_outcomes(b'schema: intent-driven\n'), {})
        self.assertEqual(R.read_x_outcomes(good + b'other:\n  nested: 1\n'),  # a later top-level key ends it
                         {OUTCOME: {'item': 'O1', 'acceptance': ACCEPTANCE}})
        self.assertEqual(R.read_x_outcomes(b'x-outcomes:\n  # a comment\n\n' + good[len(b'x-outcomes:\n'):]),
                         {OUTCOME: {'item': 'O1', 'acceptance': ACCEPTANCE}})
        bad = {
            'flow': b'x-outcomes: {}\n',
            'empty': b'x-outcomes:\nschema: x\n',
            'twice': good + good,
            'mentioned elsewhere': b'# x-outcomes\n' + good,
            'duplicate id': good + good[len(b'x-outcomes:\n'):],
            'upper-case id': good.replace(OUTCOME.encode(), OUTCOME.upper().encode()),
            'unknown key': good + b'    note: x\n',
            'repeated key': good + b'    item: O2\n',
            'missing key': f'x-outcomes:\n  {OUTCOME}:\n    item: O1\n'.encode(),
            'not an objective item': declaration(item='AC1'),
            'not a reference': declaration(acceptance='yes'),
            'missing source': declaration(acceptance='missing:owner-statement'),
            'quoted': declaration(acceptance='"conversation:qual-02/message-2"'),
            'trailing comment': good.replace(b'item: O1', b'item: O1 # the objective'),
            'tab indentation': good.replace(b'    item', b'\titem'),
            'tab-indented line after a complete entry': good + b'\t    note: x\n',
            'fields less indented than ids': (b'x-outcomes:\n    ' + OUTCOME.encode() + b':\n  item: O1\n'
                                              b'  acceptance: ' + ACCEPTANCE.encode() + b'\n'),
            'tab inside': good.replace(b'item: O1', b'item:\tO1'),
            'third level': good + b'      deeper: x\n',
            'field before entry': b'x-outcomes:\n    item: O1\n  ' + OUTCOME.encode() + b':\n',
            'uneven fields': good.replace(b'    acceptance', b'     acceptance'),
            'not utf-8': good + b'\xff\n',
        }
        for name, data in bad.items():
            with self.subTest(case=name), self.assertRaises(R.OutcomeMetadataInvalid):
                R.read_x_outcomes(data)

    def test_archive_move_keeps_resolving(self):
        def archive(repo):
            declare(repo)
        repo, declared = self.scenario('arc', archive)
        (repo / 'openspec' / 'changes' / 'archive').mkdir()
        fx.git(repo, 'mv', CHANGE_DIR, ARCHIVED_DIR)
        archived = fx.commit_all(repo, 'archive qual-02')
        current = self.ask(f'outcome:{OUTCOME}', repo, current=True)
        self.assertEqual((current.outcome, current.observed_revision, current.facts['change']),
                         (L.RESOLVED, archived, ARCHIVED_DIR))
        pinned = self.ask(f'outcome:{OUTCOME}@{declared}', repo)
        self.assertEqual((pinned.outcome, pinned.facts['change']), (L.RESOLVED, CHANGE_DIR))
        self.assertEqual(current.observed_digest, pinned.observed_digest)  # the move changed no bytes

    def test_amendment_keeps_the_id_and_changes_the_digest(self):
        repo, declared = self.scenario('amd', declare)
        edit(repo, f'{CHANGE_DIR}/proposal.md',
             b'within 5 minutes of being added, so customers can find new stock.\n- claim_type: requirement',
             b'within 2 minutes of being added, so customers can find new stock.\n- claim_type: requirement')
        edit(repo, f'{CHANGE_DIR}/proposal.md', b'- authority: accepted\n- acceptance: conversation:qual-02/message-2\n',
             b'- authority: accepted\n- acceptance: conversation:qual-02/message-4\n')
        edit(repo, f'{CHANGE_DIR}/.openspec.yaml', b'acceptance: conversation:qual-02/message-2',
             b'acceptance: conversation:qual-02/message-4')
        amended = fx.commit_all(repo, 'amend O1 with a new acceptance')
        pinned = self.ask(f'outcome:{OUTCOME}@{declared}', repo)
        current = self.ask(f'outcome:{OUTCOME}', repo, current=True)
        self.assertEqual((pinned.outcome, current.outcome), (L.RESOLVED, L.RESOLVED))
        self.assertEqual((pinned.observed_revision, current.observed_revision), (declared, amended))
        self.assertNotEqual(pinned.observed_digest, current.observed_digest)
        self.assertEqual((pinned.facts['acceptance'], current.facts['acceptance']),
                         (ACCEPTANCE, 'conversation:qual-02/message-4'))
        self.assertIn('within 2 minutes', current.facts['statement'])

    def test_acceptance_criteria_are_the_accepted_ones_citing_the_item(self):
        ac2 = (b'- source: O1, CL3\n- authority: proposed\n')
        cases = {b'- source: CL3\n- authority: accepted\n': ['AC1'],      # accepted, not citing O1
                 b'- source: O1, CL3\n- authority: accepted\n': ['AC1', 'AC2']}
        for number, (replacement, expected) in enumerate(cases.items()):
            with self.subTest(expected=expected):
                repo, _ = self.scenario(f'c{number}', lambda r: (declare(r), edit(
                    r, f'{CHANGE_DIR}/proposal.md', ac2, replacement)))
                self.assertEqual(self.ask(f'outcome:{OUTCOME}', repo).facts['acceptance_criteria'], expected)

    def test_the_archive_folder_itself_is_not_a_change(self):
        def stray(repo):
            declare(repo)
            (repo / 'openspec' / 'changes' / 'archive').mkdir()
            (repo / 'openspec' / 'changes' / 'archive' / '.openspec.yaml').write_bytes(declaration())
        repo, _ = self.scenario('str', stray)
        result = self.ask(f'outcome:{OUTCOME}', repo)
        self.assertEqual((result.outcome, result.facts['change']), (L.RESOLVED, CHANGE_DIR))

    def test_reads_git_objects_never_the_working_tree(self):
        repo, commit = self.scenario('wt', declare)
        (repo / CHANGE_DIR / '.openspec.yaml').write_bytes(b'schema: intent-driven\n')  # uncommitted
        result = self.ask(f'outcome:{OUTCOME}', repo)
        self.assertEqual((result.outcome, result.observed_revision), (L.RESOLVED, commit))

    def test_authority_unavailable(self):
        empty = self.tmp / 'not-a-repo-objective'
        empty.mkdir(exist_ok=True)
        resolver = R.ObjectiveResolver(empty)
        for method in (resolver.resolve, resolver.current):
            with fx.ceiling(self.tmp):
                result = method(L.parse(f'outcome:{OUTCOME}'))
            self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'PROJECT_UNAVAILABLE'))
        with mock.patch.object(planning.Git, 'blob', side_effect=planning.PlanningError('GIT_FAILED', 'boom')):
            result = self.ask(f'outcome:{OUTCOME}')
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'GIT_FAILED'))
        unborn = self.tmp / 'unborn'
        unborn.mkdir(exist_ok=True)
        fx.git(unborn, 'init', '--quiet', '-b', 'main')
        result = self.ask(f'outcome:{OUTCOME}', unborn)
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'GIT_FAILED'))


# ---------------------------------------------------------------------------
# work

def fake_state(*task_ids):
    return json.dumps({'tasks': [{'id': t, 'title': f'Task {t}', 'status': 'To Do', 'description': None,
                                  'references': [], 'dependencies': []} for t in task_ids]})


class TrappedView(dict):
    """A task view that fails the test if a status-like field is read."""

    def __getitem__(self, key):
        if key in ('status', 'completed', 'readiness', 'isReady'):
            raise AssertionError(f'the work resolver read {key!r}')
        return super().__getitem__(key)

    get = None  # the resolver must not .get() fields either


class WorkResolution(TempDirCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.repo = cls.tmp / 'project'
        cls.repo.mkdir()
        git(cls.repo, 'init', '--quiet', '-b', 'main')
        (cls.repo / '.fake-backlog.json').write_text(fake_state('TASK-1'), encoding='utf-8')
        cls.first = fx.commit_all(cls.repo, 'TASK-1')
        (cls.repo / '.fake-backlog.json').write_text(fake_state('TASK-1', 'TASK-2'), encoding='utf-8')
        cls.second = fx.commit_all(cls.repo, 'TASK-2')
        (cls.repo / '.fake-backlog.json').write_text(fake_state('TASK-1', 'TASK-2', 'TASK-1'), encoding='utf-8')
        cls.duplicated = fx.commit_all(cls.repo, 'a duplicate TASK-1, as when two branches meet')
        (cls.repo / '.fake-backlog.json').write_text(fake_state('TASK-1', 'TASK-2'), encoding='utf-8')
        cls.head = fx.commit_all(cls.repo, 'back to two tasks')
        cls.resolver = R.WorkResolver(cls.repo, FAKE_BACKLOG)

    def setUp(self):
        # The fake Backlog.md answers in this process (the Backlog runner seam); a missing
        # command still fails to launch, and RegistryAndCommandLine launches the fake.
        patch = mock.patch.object(planning.Backlog, 'runner', fake_backlog.InProcessRunner(FAKE_BACKLOG))
        patch.start()
        self.addCleanup(patch.stop)
        log = self.repo / '.fake-backlog-argv.jsonl'
        if log.exists():
            log.unlink()
        self.state = (self.repo / '.fake-backlog.json').read_bytes()

    def tearDown(self):
        self.assertEqual((self.repo / '.fake-backlog.json').read_bytes(), self.state)
        log = self.repo / '.fake-backlog-argv.jsonl'
        if log.exists():
            for line in log.read_text(encoding='utf-8').splitlines():
                argv = json.loads(line)
                self.assertIn(tuple(argv[:2]), {('task', 'list'), ('task', 'view')}, argv)
                self.assertNotIn('-s', argv)

    def resolve(self, text):
        return self.resolver.resolve(L.parse(text))

    def test_resolved_in_the_working_tree(self):
        result = self.resolve('backlog:TASK-2')
        self.assertEqual((result.outcome, result.authority, result.observed_revision), (L.RESOLVED, 'Backlog.md', None))
        self.assertIn('TASK-2', result.detail)

    def test_missing(self):
        result = self.resolve('backlog:TASK-9')
        self.assertEqual((result.outcome, result.code), (L.MISSING, 'WORK_MISSING'))

    def test_pinned_revision_is_read_by_backlog_at_that_commit(self):
        result = self.resolve(f'backlog:TASK-2@{self.second}')
        self.assertEqual((result.outcome, result.observed_revision), (L.RESOLVED, self.second))
        result = self.resolve(f'backlog:TASK-2@{self.first}')
        self.assertEqual((result.outcome, result.code), (L.MISSING, 'WORK_MISSING'))
        self.assertIn(self.first, result.detail)
        current = self.resolver.current(L.parse(f'backlog:TASK-2@{self.first}'))
        self.assertEqual((current.outcome, current.query, current.observed_revision), (L.RESOLVED, 'current', None))

    def test_changed_sha_is_a_revision_mismatch(self):
        result = self.resolve(f'backlog:TASK-2@{ABSENT}')
        self.assertEqual((result.outcome, result.code), (L.REVISION_MISMATCH, 'WORK_REVISION_MISSING'))

    def test_duplicate_ids_are_ambiguous(self):
        result = self.resolve(f'backlog:TASK-1@{self.duplicated}')
        self.assertEqual((result.outcome, result.code), (L.AMBIGUOUS, 'WORK_AMBIGUOUS'))
        self.assertEqual(self.resolve(f'backlog:TASK-2@{self.duplicated}').outcome, L.RESOLVED)

    def test_authority_unavailable(self):
        cases = {
            'BACKLOG_UNAVAILABLE': R.WorkResolver(self.repo, [str(self.tmp / 'no-such-backlog.exe')]),
            'PROJECT_UNAVAILABLE': R.WorkResolver(self.tmp / 'absent', FAKE_BACKLOG),
        }
        for code, resolver in cases.items():
            with self.subTest(code=code):
                result = resolver.resolve(L.parse('backlog:TASK-1'))
                self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, code))
        not_repo = self.tmp / 'plain'
        not_repo.mkdir(exist_ok=True)
        with fx.ceiling(self.tmp):
            result = R.WorkResolver(not_repo, FAKE_BACKLOG).resolve(L.parse(f'backlog:TASK-1@{self.head}'))
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'PROJECT_UNAVAILABLE'))
        with mock.patch.dict(os.environ, {'FAKE_BACKLOG_MODE': 'bad-envelope'}):
            result = self.resolve('backlog:TASK-1')
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'BACKLOG_LIST_FAILED'))
        for code in ('BACKLOG_OUTPUT', 'BACKLOG_FAILED'):
            with self.subTest(view_error=code), \
                    mock.patch.object(R.ReadOnlyBacklog, 'view', side_effect=planning.PlanningError(code, 'x')):
                result = self.resolve('backlog:TASK-1')  # listed, but its view failed
            self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'BACKLOG_VIEW_FAILED'))
        with mock.patch.object(R.ReadOnlyBacklog, 'view',
                               side_effect=planning.PlanningError('BACKLOG_OUTPUT', 'garbled')):
            result = self.resolve('backlog:TASK-9')  # not listed, but the view did not say so
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'BACKLOG_VIEW_FAILED'))

    def test_only_reads_and_never_a_status(self):
        backlog = R.ReadOnlyBacklog(FAKE_BACKLOG, self.repo)
        for args in (('task', 'create', '--', 'x'), ('task', 'edit', 'TASK-1', '-s', 'Done'), ('init', 'x')):
            with self.subTest(args=args), self.assertRaises(planning.PlanningError) as caught:
                backlog.run(*args)
            self.assertEqual(caught.exception.code, 'ADAPTER_REFUSED')
        trapped = TrappedView({'id': 'TASK-1', 'status': 'Done', 'readiness': {}, 'isReady': True})
        with mock.patch.object(R.ReadOnlyBacklog, 'view', return_value=trapped), \
                mock.patch.object(R.ReadOnlyBacklog, 'list_tasks', return_value=[trapped]):
            result = self.resolve('backlog:TASK-1')
        self.assertEqual(result.outcome, L.RESOLVED)
        self.assertNotIn('Done', json.dumps(result.to_json()))

    def test_recorded_p02_fixtures(self):
        cases = [('two-task/recorded', 'TASK-1', L.RESOLVED), ('two-task/recorded', 'TASK-2', L.RESOLVED),
                 ('readiness/missing', 'TASK-3', L.RESOLVED), ('readiness/missing', 'TASK-2', L.MISSING),
                 ('readiness/blocked', 'TASK-2', L.RESOLVED)]
        for stage, task, outcome in cases:
            with self.subTest(stage=stage, task=task), \
                    mock.patch.dict(os.environ, {'FAKE_BACKLOG_SNAPSHOT': str(RECORDED / stage)}):
                self.assertEqual(self.resolve(f'backlog:{task}').outcome, outcome)


# ---------------------------------------------------------------------------
# commit

class CommitResolution(TempDirCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.repo = cls.tmp / 'repo'
        cls.repo.mkdir()
        git(cls.repo, 'init', '--quiet', '-b', 'main')
        (cls.repo / 'a.txt').write_text('a\n', encoding='utf-8')
        cls.first = fx.commit_all(cls.repo, 'first')
        (cls.repo / 'a.txt').write_text('b\n', encoding='utf-8')
        cls.second = fx.commit_all(cls.repo, 'second')
        cls.tree = git(cls.repo, 'rev-parse', 'HEAD^{tree}')
        cls.other = cls.tmp / 'other'
        cls.other.mkdir()
        git(cls.other, 'init', '--quiet', '-b', 'main')
        (cls.other / 'x.txt').write_text('x\n', encoding='utf-8')
        cls.foreign = fx.commit_all(cls.other, 'elsewhere')
        cls.resolver = R.CommitResolver({'example/repo': cls.repo, 'plain': cls.tmp / 'plain'})
        (cls.tmp / 'plain').mkdir()

    def resolve(self, text):
        return self.resolver.resolve(L.parse(text))

    def test_resolved(self):
        before = tree_state(self.repo)
        for commit in (self.first, self.second):
            result = self.resolve(f'git:example/repo@{commit}')
            self.assertEqual((result.outcome, result.observed_revision, result.authority), (L.RESOLVED, commit, 'Git'))
            current = self.resolver.current(L.parse(f'git:example/repo@{commit}'))
            self.assertEqual((current.outcome, current.query), (L.RESOLVED, 'current'))
        self.assertEqual(tree_state(self.repo), before)

    def test_missing(self):
        cases = {ABSENT: 'COMMIT_MISSING', self.foreign: 'COMMIT_MISSING', self.tree: 'COMMIT_NOT_A_COMMIT',
                 'ab' * 32: 'COMMIT_MISSING'}
        for commit, code in cases.items():
            with self.subTest(commit=commit):
                result = self.resolve(f'git:example/repo@{commit}')
                self.assertEqual((result.outcome, result.code), (L.MISSING, code))

    def test_a_sha1_length_id_in_a_sha256_repository(self):
        repo = self.tmp / 'sha256'
        repo.mkdir()
        git(repo, 'init', '--quiet', '-b', 'main', '--object-format=sha256')
        (repo / 'a.txt').write_text('a\n', encoding='utf-8')
        full = fx.commit_all(repo, 'first')
        self.assertEqual(len(full), 64)
        resolver = R.CommitResolver({'r': repo})
        self.assertEqual(resolver.resolve(L.parse(f'git:r@{full}')).outcome, L.RESOLVED)
        result = resolver.resolve(L.parse(f'git:r@{full[:40]}'))
        self.assertEqual((result.outcome, result.code), (L.MISSING, 'COMMIT_ID_MISMATCH'))

    def test_authority_unavailable(self):
        for text, code in ((f'git:unregistered@{self.first}', 'REPOSITORY_NOT_REGISTERED'),
                           (f'git:plain@{self.first}', 'REPOSITORY_UNAVAILABLE')):
            with self.subTest(text=text), fx.ceiling(self.tmp):
                result = self.resolve(text)
                self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, code))
        with mock.patch.object(planning.Git, 'commit', side_effect=subprocess.TimeoutExpired('git', 1)):
            result = self.resolve(f'git:example/repo@{self.first}')
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'GIT_FAILED'))


# ---------------------------------------------------------------------------
# effect-receipt

effects = R._effects_module()
FIXTURE_POLICY = effects.fixture_location_policy()
ME = effects_tests.ME
AUTHORITY = effects.Authority(protected_ref='refs/heads/authorized', authorization_revision='a' * 40,
                              manifest_blob_digest='sha256:' + 'b' * 64, merged_by='verifier:owner',
                              policy_revision='policy-1')


def request(name):
    return effects.EffectRequest('repository.protect-branch', f'gitea:example/{name}', AUTHORITY, {'name': name})


class EffectReceiptResolution(unittest.TestCase):
    category = 'unit'

    def setUp(self):
        self.assertIs(effects_tests.store_mod, effects, 'fixtures and resolver share one effects module')
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-lineage-effects-'))
        self.addCleanup(self._cleanup)
        self.root = effects_tests.make_root(self.tmp / 'effects-root')
        with self.open(create=True) as store:
            self.key = store.reserve(request('alpha'), actor='executor').receipt.effect_key
            store.begin(self.key, actor='executor')
            store.finish(self.key, 'completed', actor='executor', result=effects.EffectResult('performed', {'p': 1}))
            self.other = store.reserve(request('beta'), actor='executor').receipt.effect_key
            self.events = {e['seq']: e for e in store.events(self.key)}
        self.resolver = R.EffectReceiptResolver(lambda: self.open(), effects)

    def _cleanup(self):
        effects_tests.restore_access(self.root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def open(self, create=False, policy=None):
        return effects.open_effects_store(self.root, principal=ME, policy=policy or FIXTURE_POLICY, create=create)

    def dump(self):
        with self.open() as store:
            return store.canonical_dump()

    def resolve(self, text):
        return self.resolver.resolve(L.parse(text))

    def test_resolved_unpinned_reports_the_receipts_chain_position(self):
        before = self.dump()
        result = self.resolve(f'effect:{self.key}')
        self.assertEqual((result.outcome, result.authority), (L.RESOLVED, 'effects store'))
        self.assertEqual(sorted(self.events), [1, 2, 3])
        self.assertEqual((result.observed_revision, result.observed_digest), ('3', self.events[3]['hash']))
        self.assertIn('completed', result.detail)
        current = self.resolver.current(L.parse(f'effect:{self.key}@1#sha256:{self.events[1]["hash"]}'))
        self.assertEqual((current.outcome, current.query, current.observed_revision), (L.RESOLVED, 'current', '3'))
        self.assertEqual(self.dump(), before, 'resolution changed the store')

    def test_resolved_pinned_to_an_earlier_event(self):
        result = self.resolve(f'effect:{self.key}@1#sha256:{self.events[1]["hash"]}')
        self.assertEqual((result.outcome, result.observed_revision, result.observed_digest),
                         (L.RESOLVED, '1', self.events[1]['hash']))
        self.assertIn('reserved', result.detail)

    def test_missing(self):
        absent = request('never').effect_key()
        result = self.resolve(f'effect:{absent}')
        self.assertEqual((result.outcome, result.code), (L.MISSING, 'EFFECT_RECEIPT_MISSING'))
        self.assertIn('not evidence that the effect did not happen', result.detail)

    def test_changed_position_is_a_revision_mismatch(self):
        other_seq = 4  # the beta receipt's creation event, not an event of this receipt
        for seq in (other_seq, 99):
            with self.subTest(seq=seq):
                result = self.resolve(f'effect:{self.key}@{seq}#sha256:{self.events[3]["hash"]}')
                self.assertEqual((result.outcome, result.code), (L.REVISION_MISMATCH, 'EFFECT_EVENT_MISSING'))

    def test_digest_mismatch(self):
        result = self.resolve(f'effect:{self.key}@2#sha256:{self.events[3]["hash"]}')
        self.assertEqual((result.outcome, result.code), (L.DIGEST_MISMATCH, 'EFFECT_EVENT_DIGEST_MISMATCH'))
        self.assertEqual(result.observed_digest, self.events[2]['hash'])

    def test_authority_unavailable(self):
        cases = {
            'live policy (custody and location are the store\'s)': R.EffectReceiptResolver(
                lambda: effects.open_effects_store(self.root, principal=ME), effects),
            'no such root': R.EffectReceiptResolver(
                lambda: effects.open_effects_store(self.tmp / 'absent', principal=ME, policy=FIXTURE_POLICY), effects),
            'no store in the root': R.EffectReceiptResolver(
                lambda: effects.open_effects_store(effects_tests.make_root(self.tmp / f'empty-{os.urandom(4).hex()}'),
                                                   principal=ME, policy=FIXTURE_POLICY), effects),
            'another custody principal': R.EffectReceiptResolver(
                lambda: effects.open_effects_store(self.root, policy=FIXTURE_POLICY), effects),
        }
        for name, resolver in cases.items():
            with self.subTest(case=name):
                result = resolver.resolve(L.parse(f'effect:{self.key}'))
                self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'EFFECTS_STORE_UNAVAILABLE'))

    def test_a_journal_that_does_not_verify_is_unavailable(self):
        @contextlib.contextmanager
        def broken():
            with self.open() as store:
                with mock.patch.object(store, 'verify_chain', side_effect=effects.ChainError('CHAIN_HASH: x')):
                    yield store
        result = R.EffectReceiptResolver(broken, effects).resolve(L.parse(f'effect:{self.key}'))
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'EFFECTS_CHAIN_INVALID'))

        @contextlib.contextmanager
        def no_events():  # a receipt the journal does not show (verify_chain would refuse it)
            with self.open() as store:
                with mock.patch.object(store, 'events', return_value=[]):
                    yield store
        result = R.EffectReceiptResolver(no_events, effects).resolve(L.parse(f'effect:{self.key}'))
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'EFFECTS_CHAIN_INVALID'))

    def test_after_a_restore_knowledge_is_lost_never_invented(self):
        with self.open() as store:
            manifest = store.backup(actor='owner-elevated')
            third = store.reserve(request('gamma'), actor='executor').receipt.effect_key
            store.begin(self.other, actor='executor')
            beta_events = {e['seq']: e for e in store.events(self.other)}
        manifest_path = self.root / 'backups' / (manifest['backup_file'] + '.manifest.json')
        pinned = f'effect:{self.other}@{max(beta_events)}#sha256:{beta_events[max(beta_events)]["hash"]}'
        self.assertEqual(self.resolve(pinned).outcome, L.RESOLVED)
        effects.restore_effects_store(self.root, manifest_path, actor='owner-elevated', principal=ME,
                                      policy=FIXTURE_POLICY, accept_rollback=True)
        lost = self.resolve(f'effect:{third}')
        self.assertEqual((lost.outcome, lost.code), (L.MISSING, 'EFFECT_RECEIPT_MISSING'))
        self.assertIn('restore epochs', lost.detail)
        self.assertEqual(self.resolve(pinned).outcome, L.REVISION_MISMATCH)
        self.assertEqual(self.resolve(f'effect:{self.key}@3#sha256:{self.events[3]["hash"]}').outcome, L.RESOLVED)

    def test_the_resolver_sees_only_read_methods(self):
        with self.open() as store:
            view = R._ReadOnlyEffects(store)
            for name in ('reserve', 'begin', 'finish', 'reconcile', 'attest', 'close_epoch', 'backup',
                         'prune_backups', 'conn', 'fail_before_effect'):
                self.assertFalse(hasattr(view, name), name)


# ---------------------------------------------------------------------------
# registry and command line

class RegistryAndCommandLine(TempDirCase):
    category = 'contract'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.repo = cls.tmp / 'project'
        cls.commit = fx.build_repo(cls.repo)
        cls.pointer = planning.make_pointer(planning.Git(cls.repo), CHANGE, 'design.md', cls.commit).text

    def cli(self, *args):
        return subprocess.run([*CLI, *args], cwd=REPO, capture_output=True, text=True, encoding='utf-8',
                              stdin=subprocess.DEVNULL, timeout=WAIT_CEILING_S)

    def test_build_registry_configures_the_resolvers(self):
        registry = R.build_registry(project=self.repo, backlog=FAKE_BACKLOG, repositories={'p': self.repo})
        self.assertEqual(sorted(registry.resolvers), ['commit', 'design', 'objective', 'work'])
        self.assertEqual(registry.resolve(self.pointer).outcome, L.RESOLVED)
        self.assertEqual(registry.resolve(f'git:p@{self.commit}').outcome, L.RESOLVED)
        self.assertEqual(registry.resolve('backlog:TASK-1').outcome, L.MISSING)  # the fake has no tasks here
        self.assertEqual(registry.resolve('conversation:t/m').outcome, L.AUTHORITY_UNAVAILABLE)
        log = self.repo / '.fake-backlog-argv.jsonl'
        if log.exists():
            log.unlink()

    def test_schema_command(self):
        result = self.cli('schema')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), len(L.load_schema()['kinds']))

    def test_parse_command(self):
        result = self.cli('parse', self.pointer, 'conversation:qual-02/message-1')
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r['kind'] for r in rows], ['design', 'message'])
        self.assertEqual(rows[0]['reference'], self.pointer)
        bad = self.cli('parse', 'backlog:task-1')
        self.assertEqual(bad.returncode, 1)
        self.assertIn('FAIL REFERENCE_MALFORMED', bad.stderr)

    def test_resolve_command(self):
        ok = self.cli('resolve', self.pointer, f'git:p@{self.commit}', '--project', str(self.repo),
                      '--repo', f'p={self.repo}')
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual([json.loads(line)['outcome'] for line in ok.stdout.splitlines()], [L.RESOLVED] * 2)
        current = self.cli('resolve', '--current', self.pointer, '--project', str(self.repo))
        self.assertEqual(json.loads(current.stdout)['query'], 'current')
        failing = self.cli('resolve', f'git:p@{ABSENT}', f'outcome:{OUTCOME}', '--repo', f'p={self.repo}')
        self.assertEqual(failing.returncode, 1)
        self.assertEqual([json.loads(line)['outcome'] for line in failing.stdout.splitlines()],
                         [L.MISSING, L.AUTHORITY_UNAVAILABLE])
        self.assertIn(f'FAIL outcome:{OUTCOME}: authority-unavailable RESOLVER_NOT_CONFIGURED', failing.stderr)
        self.assertEqual(self.cli('resolve', 'backlog:TASK-1', '--backlog', 'x').returncode, 2)
        self.assertEqual(self.cli('resolve', 'backlog:TASK-1', '--repo', 'nameonly').returncode, 2)
        self.assertEqual(self.cli('resolve', 'effect:fx1-' + 'a' * 64, '--effects-principal', 'S-1').returncode, 2)

    def test_resolve_command_uses_the_live_effects_policy(self):
        root = self.tmp / 'effects-root'
        result = self.cli('resolve', 'effect:fx1-' + 'a' * 64, '--effects-root', str(root))
        self.assertEqual(result.returncode, 1)
        row = json.loads(result.stdout)
        self.assertEqual((row['outcome'], row['code']), (L.AUTHORITY_UNAVAILABLE, 'EFFECTS_STORE_UNAVAILABLE'))


if __name__ == '__main__':
    unittest.main()
