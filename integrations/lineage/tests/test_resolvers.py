"""Tests for integrations/lineage/lineage_resolve.py: the read-only resolvers and the
command line (stdlib unittest, plan leaves P-03.1 and U-02.2).

Offline. Every resolver is exercised for each outcome it declares, against throwaway git
repositories, the P-02 fake Backlog.md and its recorded fixtures (and Backlog.md 1.55.3's own
recorded output for an archived task, gate G11), F-05.2 effects-store fixtures, and
throwaway Owner conversation stores made by the store's own API. The effects fixtures reuse
the effects tests' own permission helpers, which set the DACL of directories these tests
create (custody principal: the test process's SID), and the library-only fixture location
policy.
"""
import contextlib
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
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
# Backlog.md 1.55.3's own output in a throwaway project where TASK-1 was archived (gate G11, I1 slice 6): its
# task view --json reads the archived task ("archived": true), its task list --json does not list it.
ARCHIVED = HERE / 'fixtures' / 'archived-task'
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

    def test_an_archived_task_resolves_through_the_work_resolver(self):
        # Gate G11: Backlog.md lists the live TASK-2 only; its task view reads the archived TASK-1.
        listed = json.loads((ARCHIVED / 'task-list.json').read_text(encoding='utf-8'))['tasks']
        self.assertEqual([t['id'] for t in listed], ['TASK-2'])
        viewed = json.loads((ARCHIVED / 'task-view-TASK-1.json').read_text(encoding='utf-8'))['task']
        self.assertEqual((viewed['id'], viewed['archived'], viewed['path'].split('/')[:3]),
                         ('TASK-1', True, ['backlog', 'archive', 'tasks']))
        with mock.patch.dict(os.environ, {'FAKE_BACKLOG_SNAPSHOT': str(ARCHIVED)}):
            for task in ('TASK-1', 'TASK-2'):
                with self.subTest(task=task):
                    for method in (self.resolver.resolve, self.resolver.current):
                        result = method(L.parse(f'backlog:{task}'))
                        self.assertEqual((result.outcome, result.code), (L.RESOLVED, None))
                        self.assertIn(task, result.detail)
            missing = self.resolve('backlog:TASK-9')
        self.assertEqual((missing.outcome, missing.code), (L.MISSING, 'WORK_MISSING'))

    def test_an_archived_task_reference_that_does_not_resolve_is_a_failure(self):
        # The same project after the archived task's file was removed: Backlog.md cannot view it, so the
        # reference answers missing, an explicit failure, never a silent success.
        gone = self.tmp / 'archived-task-removed'
        shutil.copytree(ARCHIVED, gone, dirs_exist_ok=True)
        (gone / 'task-view-TASK-1.json').unlink()
        with mock.patch.dict(os.environ, {'FAKE_BACKLOG_SNAPSHOT': str(gone)}):
            result = self.resolve('backlog:TASK-1')
        self.assertEqual((result.outcome, result.code), (L.MISSING, 'WORK_MISSING'))
        self.assertFalse(result.resolved)
        with self.assertRaises(TypeError):
            bool(result)

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

# ---------------------------------------------------------------------------
# message and conversation: the Owner conversation store (plan leaf U-02.2)

def _example():
    """The lineage example module (its Owner conversation store builder), loaded once."""
    sys.path.insert(0, str(HERE))
    import lineage_example  # noqa: E402
    return lineage_example


def assistant_item(message_id, parent, status='complete', content=None):
    return {'parentId': parent, 'message': {
        'id': message_id, 'role': 'assistant', 'createdAt': '2026-11-07T00:00:01.000Z',
        'status': {'type': status, 'reason': 'unknown' if status == 'complete' else 'tool-calls'},
        'content': content or [{'type': 'text', 'text': 'Recorded.'}], 'metadata': {'custom': {}}}}


def store_state(path):
    """The database file's bytes and the store's canonical content, read without the resolver."""
    cs = R._conversation_module()
    conn = cs.storecore.open_read_only(Path(path))
    try:
        dump = cs._canonical_dump(conn)
    finally:
        conn.close()
    return hashlib.sha256(Path(path).read_bytes()).hexdigest(), hashlib.sha256(dump).hexdigest()


class ConversationResolution(TempDirCase):
    """The message and conversation resolvers against a real Owner conversation store, read-only."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.E = _example()
        cls.cs = R._conversation_module()
        cls.path = cls.E.build_conversations(cls.tmp / 'cv' / 'conversation.sqlite')
        cls.thread = cls.E.THREADS['qual-02']
        cls.other = cls.E.THREADS['qual-08']
        with cls.cs.open_store(cls.path) as store:
            # A reply (display state the shell wrote) after the first statement's thread went on.
            store.append_message(cls.thread, assistant_item('A000001', 'Q02msg2'), session_id=cls.E.SESSION,
                                 at=cls.E.STORE_AT)
            empty, _ = store.initialize_thread(session_id=cls.E.SESSION, local_id='__LOCALID_empty',
                                               at=cls.E.STORE_AT, mint=lambda: '2b3c4d5e-6f70-4182-93a4-b5c6d7e8f901')
        cls.empty = empty.thread_id
        cls.content = cls.E.corpus_bytes('conversation:qual-02/message-1')
        cls.message = R.MessageResolver(cls.path)
        cls.conversation = R.ConversationResolver(cls.path)
        cls.registry = R.build_registry(conversations=cls.path)

    def setUp(self):
        self.before = store_state(self.path)

    def tearDown(self):
        self.assertEqual(store_state(self.path), self.before)  # every resolution only read

    def both(self, text):
        """(resolve, current) of TEXT through the registry."""
        return self.registry.resolve(text), self.registry.current(text)

    def test_an_owner_statement_resolves_authoritatively_by_digest_and_span(self):
        base = f'conversation:{self.thread}/Q02msg1'
        whole = hashlib.sha256(self.content).hexdigest()
        start = self.content.index(b'new stock')
        span = L.span_reference(self.thread, 'Q02msg1', self.content, start, len(b'new stock')).text
        cases = {
            base: (L.RESOLVED, None, whole),
            f'{base}#sha256:{whole}': (L.RESOLVED, None, whole),
            f'{base}#sha256:{"0" * 64}': (L.DIGEST_MISMATCH, 'MESSAGE_DIGEST_MISMATCH', whole),
            span: (L.RESOLVED, None, hashlib.sha256(b'new stock').hexdigest()),
            span.replace(f'#span:{start}+', f'#span:{start + 1}+'): (L.DIGEST_MISMATCH, 'SPAN_DIGEST_MISMATCH', None),
            f'{base}#span:{len(self.content)}+1:sha256:{whole}': (L.DIGEST_MISMATCH, 'SPAN_OUT_OF_RANGE', whole),
        }
        for text, (outcome, code, digest) in cases.items():
            with self.subTest(text=text):
                for result in self.both(text):
                    self.assertEqual((result.outcome, result.code, result.kind, result.authority),
                                     (outcome, code, 'message', 'Owner conversation store'))
                    if digest:
                        self.assertEqual(result.observed_digest, digest)
        self.assertEqual(self.message.content(L.parse(base)), self.content)
        # The content is the store's bytes, checked by lineage.check_message_content unchanged.
        expected = L.check_message_content(L.parse(span), self.content)
        result = self.message.resolve(L.parse(span))
        self.assertEqual((result.outcome, result.code, result.observed_digest),
                         (expected.outcome, expected.code, expected.observed_digest))

    def test_a_span_that_splits_a_character(self):
        text = self.E.corpus_bytes('conversation:qual-08/message-1')
        start = text.index('\u00a0'.encode()) + 1          # inside the two bytes of U+00A0
        digest = hashlib.sha256(text[start:start + 2]).hexdigest()
        result = self.registry.resolve(f'conversation:{self.other}/Q08msg1#span:{start}+2:sha256:{digest}')
        self.assertEqual((result.outcome, result.code), (L.DIGEST_MISMATCH, 'SPAN_NOT_ON_CHARACTER_BOUNDARY'))

    def test_what_is_not_an_owner_statement_is_missing(self):
        cases = {
            f'conversation:{self.thread}/Q02msg9': 'MESSAGE_MISSING',
            f'conversation:{self.thread}/message-1': 'MESSAGE_MISSING',            # not an assistant-ui id
            f'conversation:{self.empty}/Q02msg1': 'MESSAGE_MISSING',
            f'conversation:{self.thread}/A000001': 'MESSAGE_NOT_A_STATEMENT',        # an assistant message
            'conversation:3f2a9c1e-7b4d-4e8a-9c0b-1d2e3f405162/Q02msg1': 'CONVERSATION_MISSING',
            'conversation:qual-02/message-1': 'CONVERSATION_MISSING',               # a corpus id, not a store id
            'conversation:..%2Fcv/Q02msg1': 'CONVERSATION_MISSING',
        }
        for text, code in cases.items():
            with self.subTest(text=text):
                for result in self.both(text):
                    self.assertEqual((result.outcome, result.code), (L.MISSING, code))
                    self.assertFalse(result.resolved)
                self.assertIsNone(self.message.content(L.parse(text)))

    def test_a_thread_resolves_at_its_last_message_or_through_a_pinned_one(self):
        with self.cs.open_store(self.path, apply_migrations=False) as store:
            last = store.messages(self.other)[-1]
            first = store.message(self.thread, 'Q02msg1')
        # Unpinned, at its last message, an Owner statement (a thread whose last message is a reply: see
        # test_an_unpinned_thread_whose_last_message_is_a_reply_is_not_a_statement).
        resolved, current = self.both(f'conversation:{self.other}')
        for result in (resolved, current):
            self.assertEqual((result.outcome, result.kind, result.observed_revision, result.observed_digest),
                             (L.RESOLVED, 'conversation', 'Q08msg1', last.sha256))
        pinned, current = self.both(f'conversation:{self.thread}@Q02msg1')
        self.assertEqual((pinned.outcome, pinned.observed_revision, pinned.observed_digest),
                         (L.RESOLVED, 'Q02msg1', first.sha256))
        self.assertEqual((current.outcome, current.query, current.observed_revision), (L.RESOLVED, 'current', 'A000001'))
        result = self.registry.resolve(f'conversation:{self.thread}@Q02msg7')
        self.assertEqual((result.outcome, result.code), (L.REVISION_MISMATCH, 'CONVERSATION_MESSAGE_MISSING'))
        self.assertEqual(self.registry.current(f'conversation:{self.thread}@Q02msg7').outcome, L.RESOLVED)
        for text in ('conversation:qual-02', 'conversation:3f2a9c1e-7b4d-4e8a-9c0b-1d2e3f405162'):
            with self.subTest(text=text):
                for result in self.both(text):
                    self.assertEqual((result.outcome, result.code), (L.MISSING, 'CONVERSATION_MISSING'))
        empty = self.registry.resolve(f'conversation:{self.empty}')
        self.assertEqual((empty.outcome, empty.code, empty.observed_revision, empty.observed_digest),
                         (L.MISSING, 'CONVERSATION_EMPTY', None, None))

    # B1 (I1 work design, R5): a conversation reference stands in the statement role, so it resolves only at an
    # Owner statement: its anchor (the pinned message, or unpinned the last message) is a user message, author owner.

    def test_a_thread_pinned_at_an_owner_statement_resolves(self):
        content = self.E.corpus_bytes('conversation:qual-02/message-2')
        for message, corpus in (('Q02msg2', 'conversation:qual-02/message-2'),
                                ('Q02msg1', 'conversation:qual-02/message-1')):
            text = f'conversation:{self.thread}@{message}'
            with self.subTest(text=text):
                result = self.registry.resolve(text)
                stored = self.E.corpus_bytes(corpus)
                expected = L.check_message_content(L.MessageRef(self.thread, message), stored)
                self.assertEqual((result.outcome, result.code, result.kind, result.authority, result.observed_revision,
                                  result.observed_digest),
                                 (L.RESOLVED, None, 'conversation', 'Owner conversation store', message,
                                  expected.observed_digest))
        self.assertEqual(self.registry.resolve(f'conversation:{self.thread}@Q02msg2').observed_digest,
                         hashlib.sha256(content).hexdigest())
        # The thread went on after the pin (a reply): current reads its last message for freshness only.
        current = self.registry.current(f'conversation:{self.thread}@Q02msg2')
        self.assertEqual((current.outcome, current.observed_revision), (L.RESOLVED, 'A000001'))

    def test_an_unpinned_thread_whose_last_message_is_a_reply_is_not_a_statement(self):
        text = f'conversation:{self.thread}'
        for result in self.both(text):
            with self.subTest(query=result.query):
                self.assertEqual((result.outcome, result.code, result.kind), (L.MISSING, 'CONVERSATION_NOT_A_STATEMENT',
                                                                              'conversation'))
                self.assertFalse(result.resolved)
                self.assertIn('A000001', result.detail)
        # Pinned at the reply itself: the anchor is the assistant message, which is never a statement.
        result = self.registry.resolve(f'{text}@A000001')
        self.assertEqual((result.outcome, result.code), (L.MISSING, 'CONVERSATION_NOT_A_STATEMENT'))

    def test_an_empty_thread_is_missing(self):
        for result in self.both(f'conversation:{self.empty}'):
            with self.subTest(query=result.query):
                self.assertEqual((result.outcome, result.code, result.observed_revision),
                                 (L.MISSING, 'CONVERSATION_EMPTY', None))
        pinned = self.registry.resolve(f'conversation:{self.empty}@Q02msg1')
        self.assertEqual((pinned.outcome, pinned.code), (L.REVISION_MISMATCH, 'CONVERSATION_MESSAGE_MISSING'))
        self.assertEqual(self.registry.current(f'conversation:{self.empty}@Q02msg1').code, 'CONVERSATION_EMPTY')

    def test_an_unavailable_store_is_explicit_and_unchanged(self):
        def absent(path):
            return path / 'conversation.sqlite'

        def other_kind(path):
            target = path / 'conversation.sqlite'
            conn = sqlite3.connect(target)
            conn.execute('CREATE TABLE thread (x)')
            conn.commit()
            conn.close()
            return target

        def needs_migration(path):
            old = path / 'migrations'
            old.mkdir()
            shutil.copy(self.cs.MIGRATIONS_DIR / '0001_store_identity_and_sessions.sql', old)
            target = path / 'conversation.sqlite'
            self.cs.open_store(target, migrations_dir=old).close()
            return target

        def altered(path):
            target = path / 'conversation.sqlite'
            shutil.copy(self.path, target)
            conn = sqlite3.connect(target)
            conn.executescript('DROP TRIGGER message_revision_no_update;')
            conn.close()
            return target

        def content_changed(path):
            # A same-account writer that keeps the schema (decision 0010 point 1): it lifts the trigger, changes the
            # content without its digest and puts the trigger back as it was, so that the digest invariant, not an
            # altered schema, is what refuses the store (as the conversation suite's
            # test_a_changed_byte_without_its_digest_is_refused_at_open does).
            target = path / 'conversation.sqlite'
            shutil.copy(self.path, target)
            conn = sqlite3.connect(target)
            trigger = conn.execute("SELECT sql FROM sqlite_schema WHERE name = 'message_revision_no_update'").fetchone()[0]
            conn.executescript('DROP TRIGGER message_revision_no_update;')
            conn.execute("UPDATE message_revision SET content = CAST('x' AS BLOB) WHERE message_id = 'Q02msg1'")
            conn.executescript(trigger + ';')
            conn.commit()
            self.cs.check_schema(conn)                  # the schema is exactly as migrated
            conn.close()
            return target

        for name, make in (('absent', absent), ('another kind', other_kind), ('needs a migration', needs_migration),
                           ('altered', altered), ('a content that does not match its digest', content_changed)):
            with self.subTest(case=name):
                where = self.tmp / f'unavailable-{name.replace(" ", "-")}'
                where.mkdir()
                path = make(where)
                before = path.read_bytes() if path.exists() else None
                for resolver, text in ((R.MessageResolver(path), f'conversation:{self.thread}/Q02msg1'),
                                       (R.ConversationResolver(path), f'conversation:{self.thread}')):
                    for method in (resolver.resolve, resolver.current):
                        result = method(L.parse(text))
                        self.assertEqual((result.outcome, result.code),
                                         (L.AUTHORITY_UNAVAILABLE, 'CONVERSATION_STORE_UNAVAILABLE'))
                self.assertIsNone(R.MessageResolver(path).content(L.parse(f'conversation:{self.thread}/Q02msg1')))
                self.assertEqual(path.read_bytes() if path.exists() else None, before)
                self.assertEqual(path.exists(), before is not None)    # an absent store is not created

    def test_reads_beside_an_open_writer_and_cannot_write(self):
        target = self.tmp / 'writer' / 'conversation.sqlite'
        self.E.build_conversations(target)
        with self.cs.open_store(target) as writer:
            writer.append_message(self.thread, assistant_item('A000009', 'Q02msg2'), session_id=self.E.SESSION,
                                  at=self.E.STORE_AT)                           # in the WAL, not yet checkpointed
            database = hashlib.sha256(target.read_bytes()).hexdigest()
            # The thread's head, read for freshness (current of a pinned reference): the reply only in the WAL file.
            result = R.ConversationResolver(target).current(L.parse(f'conversation:{self.thread}@Q02msg1'))
            self.assertEqual((result.outcome, result.observed_revision), (L.RESOLVED, 'A000009'))
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), database)
            with R.ReadOnlyConversationStore(target) as view:
                for name in ('append_message', 'update_message', 'initialize_thread', 'enroll_session',
                             'archive_thread', 'conn'):
                    self.assertFalse(hasattr(view, name), name)
                with self.assertRaises(sqlite3.Error):
                    view._conn.execute("DELETE FROM message")
                with self.assertRaises(sqlite3.Error):
                    view._conn.execute("INSERT INTO thread_event (seq, thread_id, kind, title, session_id, "
                                       "recorded_at) VALUES (99, 'x', 'archive', NULL, 'x', '2026-11-07T00:00:00Z')")

    def test_the_registry_holds_both_resolvers_to_the_schema(self):
        self.assertEqual(sorted(self.registry.resolvers), ['conversation', 'message'])
        kinds = L.schema_kinds(L.load_schema())
        for kind in ('message', 'conversation'):
            with self.subTest(kind=kind):
                self.assertEqual(kinds[kind]['status'], 'implemented')
                self.assertEqual(set(self.registry.resolvers[kind].outcomes), set(kinds[kind]['outcomes']))
        unconfigured = R.build_registry().resolve(f'conversation:{self.thread}/Q02msg1')
        self.assertEqual((unconfigured.outcome, unconfigured.code),
                         (L.AUTHORITY_UNAVAILABLE, 'RESOLVER_NOT_CONFIGURED'))


class AttemptResolution(unittest.TestCase):
    """The attempt resolver (plan leaf E-01.5): the dispatched attempt resolved against the Agent Server fixture's
    cited core, its authority mode stated (fixture_attempts: the dispatcher's records, made through the store's own
    API, bound to a route allowlist that declares the fixture authority, R8 point 2)."""
    category = 'integration'

    def setUp(self):
        sys.path.insert(0, str(HERE))
        import fixture_attempts
        self.FA = fixture_attempts
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-lineage-attempt-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.core = fixture_attempts.AC.AgentServerCore()
        self.addCleanup(self.core.close)
        (self.tmp / 'st').mkdir()
        self.path = self.tmp / 'st' / 'integration.sqlite'

    def attempts(self, live=False, confirm=True, work_id='TASK-1'):
        attempts = self.FA.FixtureAttempts(self.tmp / ('live' if live else 'fixture'), live=live)
        store = self.FA.store_mod.open_store(self.path)
        try:
            key, cid = attempts.attempt(store, self.core, work_id, change=CHANGE, design_commit='a' * 40,
                                        outcome_ref='outcome:5c6f4c1e-8d3a-4a3b-9b2e-1f0e7d6c5b4a', confirm=confirm)
        finally:
            store.close()
        return attempts, key, cid

    def ask(self, text, attempts, transport=None, method='resolve'):
        registry = R.build_registry(attempts=R.AttemptResolver(self.path, transport or self.core,
                                                                attempts.read_artifact))
        return getattr(registry, method)(L.parse(text))

    def test_the_dispatched_attempt_resolves_with_its_mode_stated(self):
        attempts, key, cid = self.attempts()
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        calls = len(self.core.calls)
        for method in ('resolve', 'current'):
            with self.subTest(method=method):
                result = self.ask(f'openhands:conversation/{cid}', attempts, method=method)
                self.assertEqual((result.outcome, result.code), (L.RESOLVED, None))
                self.assertEqual(result.authority, L.fixture_authority(R.ATTEMPT_AUTHORITY))
                self.assertTrue(result.authority.startswith(L.FIXTURE_PREFIX))
                self.assertEqual(result.observed_digest, hashlib.sha256(
                    json.dumps({'id': cid}, separators=(',', ':')).encode()).hexdigest())
        self.assertEqual([c[:2] for c in self.core.calls[calls:]], [('GET', f'/api/conversations/{cid}')] * 2,
                         'one GET a question, nothing else')
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before, 'read-only')

    def test_each_unresolved_answer(self):
        attempts, key, cid = self.attempts()
        other, _, unconfirmed = self.attempts(confirm=False, work_id='TASK-2')
        gone = self.FA.store_mod.conversation_id_for(key)
        self.core('DELETE', f'/api/conversations/{gone}/runtime')
        cases = {
            'openhands:conversation/00000000-0000-4000-8000-000000000000': (L.MISSING, 'ATTEMPT_MISSING'),
            f'openhands:conversation/{unconfirmed}': (L.MISSING, 'ATTEMPT_NOT_CONFIRMED'),
            f'openhands:conversation/{cid}@evt-17': (L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_EVENT_UNOBSERVED'),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                result = self.ask(text, attempts)
                self.assertEqual((result.outcome, result.code), expected)
        # the server no longer holds it: 404 (F-04.2 4.9, the core's conversation-absent)
        del self.core.conversations[cid]
        result = self.ask(f'openhands:conversation/{cid}', attempts)
        self.assertEqual((result.outcome, result.code), (L.MISSING, 'ATTEMPT_CONVERSATION_MISSING'))
        self.assertTrue(result.authority.startswith(L.FIXTURE_PREFIX), 'the fixture answered the 404')

    def test_the_bound_and_the_answering_authority_must_agree(self):
        """R11: a fixture-bound attempt answered without the label, or a label on a live-bound attempt, is
        neither: authority-unavailable."""
        attempts, _, cid = self.attempts()

        def unlabelled(method, path, body=None, **kwargs):
            answer = dict(self.core(method, path, body, **kwargs))
            answer.pop('fixture')
            return answer
        result = self.ask(f'openhands:conversation/{cid}', attempts, transport=unlabelled)
        self.assertEqual((result.outcome, result.code, result.authority),
                         (L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_AUTHORITY_MISMATCH', R.ATTEMPT_AUTHORITY))
        self.path.unlink()
        live, _, cid = self.attempts(live=True, work_id='TASK-3')
        result = self.ask(f'openhands:conversation/{cid}', live)
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_AUTHORITY_MISMATCH'))
        result = self.ask(f'openhands:conversation/{cid}', live, transport=unlabelled)
        self.assertEqual((result.outcome, result.code, result.authority), (L.RESOLVED, None, R.ATTEMPT_AUTHORITY),
                         'live-bound, answered without a label: live')

    def test_declared_and_answering_authority(self):
        self.assertEqual(R.declared_authority(b'{"routes": []}'), R.LIVE)
        self.assertEqual(R.declared_authority(b'{"transport": {"authority": "fixture", "kind": "x"}}'), R.FIXTURE)
        for raw in (b'{"transport": {"authority": "other"}}', b'{"transport": "fixture"}', b'[]', b'\xff'):
            with self.subTest(raw=raw):
                self.assertIsNone(R.declared_authority(raw))
        self.assertEqual(R.answering_authority({'status': 200}), R.LIVE)
        self.assertEqual(R.answering_authority({'fixture': {'authority': 'fixture'}}), R.FIXTURE)
        self.assertIsNone(R.answering_authority({'fixture': {'authority': 'elsewhere'}}))
        self.assertIsNone(R.answering_authority({'fixture': 'fixture'}))

    def test_an_unreadable_record_or_allowlist_or_no_answer_is_unavailable(self):
        attempts, key, cid = self.attempts()
        text = f'openhands:conversation/{cid}'

        def silent(method, path, body=None, **kwargs):
            raise ConnectionError('no answer')
        self.assertEqual(self.ask(text, attempts, transport=silent).code, 'ATTEMPT_UNANSWERED')

        def other(method, path, body=None, **kwargs):
            answer = self.core(method, path, body, **kwargs)
            return {**answer, 'body': {'id': '00000000-0000-4000-8000-000000000000'}}
        self.assertEqual(self.ask(text, attempts, transport=other).code, 'ATTEMPT_UNOBSERVED')
        routes = attempts.root / 'profiles' / self.FA.PROFILE / 'agent-server' / 'routes.json'
        routes.write_bytes(routes.read_bytes() + b' ')
        self.assertEqual(self.ask(text, attempts).code, 'ATTEMPT_ALLOWLIST_UNREADABLE')
        result = R.AttemptResolver(self.tmp / 'nowhere.sqlite', self.core, attempts.read_artifact).resolve(
            L.parse(text))
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'INTEGRATION_STORE_UNAVAILABLE'))

    def test_a_reservation_that_is_not_the_dispatchers_record(self):
        store = self.FA.store_mod.open_store(self.path)
        try:
            store.reserve('work-TASK-1/implement/revision-1', {'workRef': 'backlog:TASK-1'}, actor='t')
            for state in ('dispatched', 'confirmed'):
                store.transition('work-TASK-1/implement/revision-1', state, actor='t', reason='t')
        finally:
            store.close()
        cid = self.FA.store_mod.conversation_id_for('work-TASK-1/implement/revision-1')
        result = self.ask(f'openhands:conversation/{cid}', self.FA.FixtureAttempts(self.tmp / 'f'))
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_RECORD_INVALID'))
        self.assertEqual(self.core.calls, [], 'not asked of the Agent Server')

    def test_the_resolver_is_configured_only_with_a_transport(self):
        self.assertEqual(R.build_registry().resolve(L.parse('openhands:conversation/'
                                                            '00000000-0000-4000-8000-000000000000')).code,
                         'RESOLVER_NOT_CONFIGURED')
        with self.assertRaises(TypeError):
            R.build_registry(attempts=object())


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

    def test_resolve_command_reads_the_owner_conversation_store(self):
        example = _example()
        path = example.build_conversations(self.tmp / 'cli-cv' / 'conversation.sqlite')
        thread = example.THREADS['qual-02']
        before = store_state(path)
        ok = self.cli('resolve', f'conversation:{thread}/Q02msg1', f'conversation:{thread}@Q02msg2',
                      '--conversations', str(path))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        rows = [json.loads(line) for line in ok.stdout.splitlines()]
        self.assertEqual([(r['kind'], r['outcome'], r['authority']) for r in rows],
                         [('message', L.RESOLVED, 'Owner conversation store'),
                          ('conversation', L.RESOLVED, 'Owner conversation store')])
        # An unresolved statement is a failure: exit 1 and a FAIL line naming its code.
        failing = self.cli('resolve', f'conversation:{thread}/Q02msg9', '--conversations', str(path))
        self.assertEqual(failing.returncode, 1)
        self.assertIn(f'FAIL conversation:{thread}/Q02msg9: missing MESSAGE_MISSING', failing.stderr)
        absent = self.cli('resolve', f'conversation:{thread}/Q02msg1', '--conversations', str(self.tmp / 'no.sqlite'))
        self.assertEqual(absent.returncode, 1)
        self.assertEqual(json.loads(absent.stdout)['code'], 'CONVERSATION_STORE_UNAVAILABLE')
        self.assertFalse((self.tmp / 'no.sqlite').exists())
        self.assertEqual(store_state(path), before)

    def test_resolve_command_uses_the_live_effects_policy(self):
        root = self.tmp / 'effects-root'
        result = self.cli('resolve', 'effect:fx1-' + 'a' * 64, '--effects-root', str(root))
        self.assertEqual(result.returncode, 1)
        row = json.loads(result.stdout)
        self.assertEqual((row['outcome'], row['code']), (L.AUTHORITY_UNAVAILABLE, 'EFFECTS_STORE_UNAVAILABLE'))


if __name__ == '__main__':
    unittest.main()
