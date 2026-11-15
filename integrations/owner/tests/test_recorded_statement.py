"""The acceptance recorder's recorded-statement path (plan leaf E-05.12; decision 0018 points 4.3 and 7), on
throwaway project repositories and a throwaway harness log.

Run from the repository root, under the tools interpreter (Dulwich is required: without it these tests fail
with REPOSITORY_NEEDS_DULWICH, never skip):

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

The plan's proof: an objective acceptance whose statement reference names an anchored, dated Decisions entry of
evidence/bootstrap-log.md at the harness's committed revision, with the statement's text inside that entry's
verbatim Owner block, is recorded with kind accept-objective, its outcome is minted once and resolves through the
lineage objective resolver, and the record names the entry and the revision and states that no challenge was
shown. An absent anchor, an entry without a dated title, text outside the verbatim block, a log not committed at
that revision, a statement attributed to anyone but the Owner and the request itself are each refused with a
stable code and change nothing (neither the project repository nor the harness repository). P-04.1's paths are
test_acceptance_recorder.py's, unchanged.

The review rulings of 2026-11-15 (dispatch E-05.12-2), each with the reviewer's probe as a test: only an entry
whose dated title begins "Owner " is the Owner's, and only its first run of "> " lines outside code fences is his
block (R1; probes P1, P2, P3, P3b); the statement is at least 12 characters and names the change or the project
repository (R2; P4, P4b, P4c); the request's own text is refused like its reference (R3; P6); the harness's HEAD
is refs/heads/main, and its origin is recorded without userinfo (R4; P5, P8b); a reference to a missing object is
HARNESS_UNAVAILABLE (N1; P8).

The harness log is ``fixtures/recorded-statement-log.md``: a byte-for-byte copy of the real entry anchored
``owner-direction-d1-planning-2026-11-15`` (a multi-line verbatim block, the real target of E-05.1) among
SYNTHETIC entries. Every statement recorded here is a test's: no Owner decision is recorded, and nothing is
written to the real harness log, the demo repository or the managed data root. Two tests read this checkout's
own log at its HEAD, read only.
"""
import contextlib
import datetime
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import owner_fixture as of  # noqa: E402

A, D, fx = of.A, of.D, of.fx
G, R, L, ra = A.G, A.R, A.L, A.ra
NOW = of.NOW
LATER = NOW + datetime.timedelta(minutes=5)
PROPOSED, HAND = of.PROPOSED, of.HAND_ACCEPTED
LOG_FIXTURE = HERE / 'fixtures' / 'recorded-statement-log.md'
D1_DESIGN = of.REPO / 'evidence' / 'D1-demo-design' / 'openspec' / 'changes' / 'add-slugify'
D1_CHANGE = 'add-slugify'
# The project is a clone of the demo repository (its origin ends in aieh-d1-demo.git); the harness's origin
# carries a user name, which the record leaves out.
PROJECT_ORIGIN = 'https://example.invalid/demo/aieh-d1-demo.git'
HARNESS_ORIGIN = 'https://fixture-user@example.invalid/harness/ai-engineering-harness.git'
HARNESS_ORIGIN_RECORDED = 'https://example.invalid/harness/ai-engineering-harness.git'

ANCHOR = 'owner-direction-d1-planning-2026-11-15'
LOG_REF = 'harness:evidence/bootstrap-log.md#'
REF = LOG_REF + ANCHOR
REACCEPT = LOG_REF + 'fixture-owner-reaccept-2026-11-16'
REQUEST = LOG_REF + 'owner-decision-oa-31-2026-11-14'  # add-slugify's Q1 source
# E-05.1's statement: several lines of the entry's verbatim block, as the Owner wrote them (blank lines included).
TEXT = ('Finalize and accept the OpenSpec change for\n'
        'aieh-d1-demo:\n'
        '\n'
        'Implement slugify(text) as a small Python function,\n'
        'with appropriate unittest coverage.\n'
        '\n'
        'Choose sensible, explicit behavior for normalization,\n'
        'whitespace, punctuation, case, empty input, and\n'
        'non-ASCII text.\n'
        '\n'
        'Keep the demonstration intentionally small.')
REACCEPT_TEXT = ('SYNTHETIC FIXTURE, not an Owner decision: accept O1 of qual-05-api-rate-limiting again, '
                 'as amended.')
REQUEST_TEXT = 'OA-25: use aieh-d1-demo, a small Python package with unittest tests.'
QUAL05_REQUEST = ('Please add rate limiting to the public API so a single client can\'t take it down for everyone else. '
                  'Use a fixed window of 100 requests per minute per IP.')
OUTCOME = '6a1f0e2d-3c4b-4a59-8d7e-0f1e2d3c4b5a'


def statement(**changes):
    """A statement whose text is quoted from the fixture log (a test's, recording no Owner decision)."""
    return {'text': TEXT, 'attributedTo': 'owner', 'channel': 'main-session', 'reference': REF, **changes}


def worktree(repo):
    """Every file below REPO outside .git: {relative path: bytes}."""
    out = {}
    for directory, dirs, files in os.walk(repo):
        if '.git' in dirs:
            dirs.remove('.git')
        for name in files:
            path = Path(directory, name)
            out[path.relative_to(repo).as_posix()] = path.read_bytes()
    return out


def build_harness(repo, log=None, commit=True, origin=None):
    """A throwaway harness repository at REPO holding LOG (the fixture log's bytes by default) as
    evidence/bootstrap-log.md: committed, or (COMMIT false) only in the work tree beside a committed README, on
    main, with ORIGIN as its origin remote when given. Returns HEAD's commit, or None when nothing is committed."""
    Path(repo).mkdir(parents=True)
    fx.git(repo, 'init', '--quiet', '-b', 'main')
    if origin:
        fx.git(repo, 'remote', 'add', 'origin', origin)
    data = LOG_FIXTURE.read_bytes() if log is None else log
    if commit:
        fx.write(repo, {'README.md': b'Throwaway harness repository (E-05.12 fixture).\n',
                        'evidence/bootstrap-log.md': data})
        return fx.commit_all(repo, 'The fixture log')
    fx.write(repo, {'evidence/bootstrap-log.md': data})
    return None


def build_project(repo, origin=PROJECT_ORIGIN):
    """The acceptance recorder's fixture project at REPO, with ORIGIN as its origin remote when given."""
    design = of.build_project(repo)
    if origin:
        fx.git(repo, 'remote', 'add', 'origin', origin)
    return design


def add_d1_change(repo):
    """Commit a copy of the D1 demo design (evidence/D1-demo-design, read only) as a change of REPO."""
    files = {}
    for path in sorted(D1_DESIGN.rglob('*')):
        if path.is_file():
            files[f'openspec/changes/{D1_CHANGE}/{path.relative_to(D1_DESIGN).as_posix()}'] = path.read_bytes()
    fx.write(repo, files)
    return fx.commit_all(repo, 'The D1 demo design (a copy)')


def committed_log(repo):
    """(HEAD's commit, the log's text there) of the repository REPO, read only."""
    with ra.open_repository(repo, config='repository', ceilings=[str(Path(repo).parent)]) as handle:
        commit = handle.head().commit
        return commit, handle.blob(commit, G.LOG).decode('utf-8')


class Fixture(unittest.TestCase):
    # SHARED: one set of repositories for the class, for tests whose every call is refused (each asserts that
    # nothing changed); otherwise a fresh set for each test.
    SHARED = False

    @classmethod
    def setUpClass(cls):
        fx.require_repository_access()  # fail, never skip, without Dulwich
        if cls.SHARED:
            cls.shared_root = Path(tempfile.mkdtemp(prefix='ow-'))
            cls.shared = cls.build(cls.shared_root)

    @classmethod
    def tearDownClass(cls):
        if cls.SHARED:
            fx.rmtree(cls.shared_root)

    @staticmethod
    def build(root):
        design = build_project(root / 'p')
        return design, build_harness(root / 'h', origin=HARNESS_ORIGIN)

    def setUp(self):
        if self.SHARED:
            self.root, (self.design, self.harness_head) = self.shared_root, self.shared
        else:
            self.root = Path(tempfile.mkdtemp(prefix='ow-'))
            self.addCleanup(fx.rmtree, self.root)
            self.design, self.harness_head = self.build(self.root)
        self.repo, self.harness = self.root / 'p', self.root / 'h'
        ceiling = fx.ceiling(self.root)
        ceiling.start()
        self.addCleanup(ceiling.stop)

    def record(self, change=PROPOSED, item='O1', said=None, project=None, **kwargs):
        kwargs.setdefault('recorded_by', of.RECORDED_BY)
        kwargs.setdefault('identity', of.IDENTITY)
        kwargs.setdefault('now', LATER)
        kwargs.setdefault('harness', self.harness)
        return A.record_from_log(project or self.repo, change, item, statement() if said is None else said,
                                 **kwargs)

    def resolve(self, text, current=False, repo=None):
        resolver = R.ObjectiveResolver(repo or self.repo)
        reference = L.parse(text)
        return resolver.current(reference) if current else resolver.resolve(reference)

    @staticmethod
    def snapshot(repo):
        index = Path(repo) / '.git' / 'index'
        return fx.loose_head(repo), worktree(repo), index.read_bytes() if index.exists() else None

    @contextlib.contextmanager
    def unchanged(self, *others):
        """The block must leave the project's and the harness's branches, work trees and indexes as they were."""
        repos = (self.repo, self.harness, *others)
        before = [self.snapshot(repo) for repo in repos]
        yield
        self.assertEqual([self.snapshot(repo) for repo in repos], before)

    def refused(self, code, call, *args, **kwargs):
        with self.unchanged(), self.assertRaises(A.RecorderError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code, caught.exception)
        self.assertIn(f'Remedy: {A.REMEDIES[code]}', str(caught.exception))
        return caught.exception


class RecordingFromTheLog(Fixture):
    """The recorded-statement path records the shared record, mints once and resolves through lineage."""

    def test_an_acceptance_from_the_recorded_statement_resolves_through_the_lineage_objective_resolver(self):
        mint = mock.Mock(return_value=OUTCOME)
        result = self.record(new_outcome=mint)
        mint.assert_called_once_with()
        self.assertTrue(result['minted'])
        self.assertEqual(result['outcome'], OUTCOME)
        self.assertEqual(result['reference'], f'outcome:{OUTCOME}@{result["commit"]}')
        self.assertEqual(fx.loose_head(self.repo), result['commit'])
        for current in (False, True):
            with self.subTest(current=current):
                answer = self.resolve(result['reference'], current=current)
                self.assertTrue(answer.resolved, answer)
                self.assertEqual(answer.observed_revision, result['commit'])
                self.assertEqual(answer.facts['change'], f'openspec/changes/{PROPOSED}')
                self.assertEqual(answer.facts['item'], 'O1')
                self.assertEqual(answer.facts['acceptance'], REF)
        before = self.resolve(f'outcome:{OUTCOME}@{self.design}')
        self.assertEqual((before.outcome, before.code), (L.MISSING, 'OUTCOME_MISSING'))
        # The harness repository is only read.
        self.assertEqual(fx.loose_head(self.harness), self.harness_head)
        self.assertEqual(fx.git(self.harness, 'status', '--porcelain', '--untracked-files=all'), '')

    def test_the_record_names_the_entry_and_the_revision_and_that_no_challenge_was_shown(self):
        result = self.record()
        record = result['decision']
        self.assertEqual(D.check_record(record), [])
        self.assertEqual(list(record), list(D.RECORDED_FIELDS))
        self.assertNotIn('shown', record)
        self.assertEqual(record['kind'], 'accept-objective')
        with ra.open_repository(self.harness, config='repository') as repo:
            blob = repo.blob(self.harness_head, 'evidence/bootstrap-log.md')
        with ra.open_repository(self.repo, config='repository') as repo:
            proposal = repo.blob(self.design, f'openspec/changes/{PROPOSED}/proposal.md')
        self.assertEqual(blob, LOG_FIXTURE.read_bytes())
        self.assertEqual(record['recorded'], {
            'restsOn': 'recorded-statement', 'entry': f'evidence/bootstrap-log.md#{ANCHOR}', 'date': '2026-11-15',
            'revision': self.harness_head, 'origin': HARNESS_ORIGIN_RECORDED,
            'digest': 'sha256:' + hashlib.sha256(blob).hexdigest(),
            'about': {'name': 'aieh-d1-demo', 'as': 'repository'}, 'challengeShown': False})
        self.assertEqual(list(record['recorded']), list(D.RECORDED_BLOCK_FIELDS))
        self.assertNotIn('fixture-user', D.dumps(record))
        self.assertEqual(record['subject'], {'change': PROPOSED, 'item': 'O1', 'outcome': result['outcome'],
                                             'revision': self.design,
                                             'proposal': hashlib.sha256(proposal).hexdigest()})
        self.assertEqual(record['statement'], statement())
        self.assertEqual((record['recordedBy'], record['recordedAt']), (of.RECORDED_BY, '2026-11-10T12:05:00Z'))
        message = fx.git(self.repo, 'log', '-1', '--format=%B')
        self.assertIn(f'Statement: {REF} (main-session).', message)
        self.assertIn(f'It rests on the Owner\'s statement recorded in evidence/bootstrap-log.md#{ANCHOR} '
                      f'(2026-11-15),\nread at the harness revision {self.harness_head}. No challenge was shown.\n',
                      message)
        self.assertNotIn('nonce', message)
        self.assertEqual(fx.git(self.repo, 'diff', '--name-only', self.design, result['commit']).splitlines(),
                         sorted([f'openspec/changes/{PROPOSED}/.openspec.yaml', result['path'],
                                 f'openspec/changes/{PROPOSED}/proposal.md']))
        self.assertEqual((self.repo / result['path']).read_bytes(), D.dumps(record).encode('utf-8'))
        fx.git(self.repo, 'fsck', '--strict', '--no-progress')
        self.assertEqual(fx.git(self.repo, 'status', '--porcelain', '--untracked-files=all'), '')

    def test_the_outcome_is_minted_once(self):
        first = self.record()
        never = mock.Mock(side_effect=AssertionError('a second outcome id was minted'))
        error = self.refused('OUTCOME_ALREADY_MINTED', self.record, new_outcome=never)
        self.assertIn(first['outcome'], error.detail)
        reaccept = statement(text=REACCEPT_TEXT, reference=REACCEPT)
        self.refused('OUTCOME_ALREADY_MINTED', self.record, said=reaccept, new_outcome=never)
        self.refused('ACCEPTANCE_ALREADY_RECORDED', self.record, amend=True, new_outcome=never)
        second = self.record(said=reaccept, amend=True, new_outcome=never)
        never.assert_not_called()
        self.assertFalse(second['minted'])
        self.assertEqual(second['outcome'], first['outcome'])
        self.assertEqual(second['decision']['recorded']['entry'],
                         'evidence/bootstrap-log.md#fixture-owner-reaccept-2026-11-16')
        self.assertEqual(second['decision']['recorded']['date'], '2026-11-16')
        self.assertEqual(second['decision']['recorded']['about'], {'name': PROPOSED, 'as': 'change'})
        self.assertEqual(self.resolve(second['reference']).facts['acceptance'], REACCEPT)
        self.assertEqual(self.resolve(first['reference']).facts['acceptance'], REF)

    def test_an_objective_accepted_by_hand_gets_its_id_once(self):
        result = self.record(HAND)
        self.assertTrue(result['minted'])
        self.assertTrue(self.resolve(result['reference']).resolved)
        self.refused('OUTCOME_ALREADY_MINTED', self.record, HAND)

    def test_the_challenge_path_beside_a_recorded_statement_decision(self):
        # P-04.1's path is unchanged: it still refuses a log reference, and it reads a change that holds a
        # decision resting on a recorded statement (no nonce) as it reads any other.
        challenge = A.prepare(self.repo, PROPOSED, 'O1', now=NOW)
        with self.unchanged(), self.assertRaises(A.RecorderError) as caught:
            A.record(self.repo, challenge, of.statement(reference=REF), recorded_by=of.RECORDED_BY,
                     identity=of.IDENTITY, now=LATER)
        self.assertEqual(caught.exception.code, 'ACCEPTANCE_REFERENCE_INVALID')
        first = self.record()
        amended = A.record(self.repo, A.prepare(self.repo, PROPOSED, 'O1', now=NOW),
                           of.statement(reference='conversation:fixture-owner/message-7'), recorded_by=of.RECORDED_BY,
                           identity=of.IDENTITY, now=LATER, amend=True)
        self.assertEqual(amended['outcome'], first['outcome'])
        self.assertEqual(list(amended['decision']), list(D.FIELDS))
        self.assertTrue(self.resolve(amended['reference']).resolved)

    def test_the_d1_demo_change_is_accepted_from_the_real_entrys_shape(self):
        # A rehearsal of E-05.1 on a copy of the D1 demo design, in a clone of the demo repository (its origin
        # ends in aieh-d1-demo.git): O1 of add-slugify, accepted from the copy of the entry anchored
        # owner-direction-d1-planning-2026-11-15, which names aieh-d1-demo; the reference to its Q1's source is the
        # request itself.
        add_d1_change(self.repo)
        self.refused('ACCEPTANCE_IS_REQUEST', self.record, D1_CHANGE,
                     said=statement(text=REQUEST_TEXT, reference=REQUEST))
        result = self.record(D1_CHANGE)
        answer = self.resolve(result['reference'])
        self.assertTrue(answer.resolved, answer)
        self.assertEqual((answer.facts['change'], answer.facts['item'], answer.facts['acceptance']),
                         (f'openspec/changes/{D1_CHANGE}', 'O1', REF))
        self.assertEqual(answer.facts['source'], ['Q1'])
        self.assertEqual(result['decision']['recorded']['about'], {'name': 'aieh-d1-demo', 'as': 'repository'})

    def test_the_repository_name_without_an_origin_is_the_directorys(self):
        # A project without an origin, in a directory named aieh-d1-demo; a harness without an origin, whose
        # record then has no origin field.
        project, harness = self.root / 'aieh-d1-demo', self.root / 'bare-harness'
        build_project(project, origin=None)
        head = build_harness(harness)
        result = self.record(project=project, harness=harness)
        recorded = result['decision']['recorded']
        self.assertEqual(recorded['about'], {'name': 'aieh-d1-demo', 'as': 'repository'})
        self.assertNotIn('origin', recorded)
        self.assertEqual(recorded['revision'], head)
        self.assertEqual(D.check_record(result['decision']), [])
        self.assertTrue(self.resolve(result['reference'], repo=project).resolved)

    def test_the_command_line(self):
        said = self.root / 'statement.json'
        said.write_text(json.dumps(statement()), encoding='utf-8')
        out, err = io.StringIO(), io.StringIO()
        code = A.main(['record-from-log', '--project', str(self.repo), '--change', PROPOSED, '--item', 'O1',
                       '--statement', str(said), '--harness', str(self.harness), '--recorded-by', of.RECORDED_BY,
                       '--identity', of.IDENTITY], out=out, err=err)
        self.assertEqual((code, err.getvalue()), (0, ''))
        result = json.loads(out.getvalue())
        self.assertEqual(result['decision']['recorded']['revision'], self.harness_head)
        self.assertTrue(self.resolve(result['reference']).resolved)
        out, err = io.StringIO(), io.StringIO()
        with self.unchanged():
            code = A.main(['record-from-log', '--project', str(self.repo), '--change', PROPOSED, '--item', 'O1',
                           '--statement', str(said), '--harness', str(self.harness), '--recorded-by',
                           of.RECORDED_BY, '--identity', of.IDENTITY], out=out, err=err)
        self.assertEqual((code, out.getvalue()), (2, ''))
        self.assertTrue(err.getvalue().startswith('acceptance-recorder: OUTCOME_ALREADY_MINTED: '), err.getvalue())

    def test_no_process_is_launched(self):
        with mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('a process was launched')):
            result = self.record()
        self.assertTrue(result['minted'])


class RecordedStatementRefusals(Fixture):
    """Each refusal has its stable code and remedy, and changes nothing (one shared set of repositories)."""
    SHARED = True

    @staticmethod
    def build(root):
        _, head = Fixture.build(root)
        add_d1_change(root / 'p')
        design = fx.loose_head(root / 'p')
        build_project(root / 'other', origin='https://example.invalid/demo/another-project.git')
        build_harness(root / 'untracked', commit=False)  # unborn HEAD, the log in the work tree only
        uncommitted = root / 'uncommitted'  # a commit without the log; the log in the work tree only
        uncommitted.mkdir()
        fx.git(uncommitted, 'init', '--quiet', '-b', 'main')
        fx.write(uncommitted, {'README.md': b'Throwaway harness repository (E-05.12 fixture).\n'})
        fx.commit_all(uncommitted, 'No log')
        fx.write(uncommitted, {'evidence/bootstrap-log.md': LOG_FIXTURE.read_bytes()})
        # A committed log whose work tree adds an entry that is not committed.
        edited = root / 'edited'
        build_harness(edited)
        added = (b'- <a id="fixture-work-tree-only-2026-11-15"></a>**2026-11-15: Owner direction (SYNTHETIC '
                 b'FIXTURE): an entry only in the work tree, verbatim.**\n\n  > SYNTHETIC FIXTURE, not an Owner '
                 b'decision: accept O1 of qual-05-api-rate-limiting as written.\n')
        log = LOG_FIXTURE.read_bytes().replace(b'\n## Owner-directed maintenance items', added + b'\n## Owner-directed '
                                               b'maintenance items')
        assert log != LOG_FIXTURE.read_bytes()
        (edited / 'evidence' / 'bootstrap-log.md').write_bytes(log)
        # P5: an Owner entry committed only on a side branch, which HEAD names.
        side = root / 'side'
        build_harness(side)
        fx.git(side, 'checkout', '--quiet', '-b', 'fabricated')
        fabricated = (b'- <a id="fixture-fabricated-2026-11-15"></a>**2026-11-15: Owner decision (SYNTHETIC '
                      b'FIXTURE): accept O1 of qual-05.** Verbatim:\n\n  > I accept O1 of qual-05-api-rate-limiting.\n')
        (side / 'evidence' / 'bootstrap-log.md').write_bytes(LOG_FIXTURE.read_bytes().replace(
            b'\n## Owner-directed maintenance items', fabricated + b'\n## Owner-directed maintenance items'))
        fx.commit_all(side, 'A fabricated entry on a side branch')
        # P8b: HEAD detached on main's commit.
        detached = root / 'detached'
        commit = build_harness(detached)
        fx.git(detached, 'checkout', '--quiet', '--detach', commit)
        # P8 (N1): main names a missing object.
        dangling = root / 'dangling'
        build_harness(dangling)
        (dangling / '.git' / 'refs' / 'heads' / 'main').write_text('0123456789abcdef0123456789abcdef01234567\n',
                                                                   encoding='ascii')
        return design, head

    def test_an_absent_anchor_is_refused(self):
        for anchor in ('no-such-entry', 'fixture-before-decisions', 'fixture-after-decisions-2026-11-15'):
            with self.subTest(anchor=anchor):
                self.refused('STATEMENT_ANCHOR_ABSENT', self.record, said=statement(reference=LOG_REF + anchor))

    def test_an_entry_only_in_the_work_tree_is_refused(self):
        said = statement(text='SYNTHETIC FIXTURE, not an Owner decision: accept O1 of qual-05-api-rate-limiting as '
                              'written.', reference=LOG_REF + 'fixture-work-tree-only-2026-11-15')
        with self.unchanged(self.root / 'edited'):
            self.refused('STATEMENT_ANCHOR_ABSENT', self.record, said=said, harness=self.root / 'edited')

    def test_an_entry_without_a_dated_title_is_refused(self):
        said = statement(text='SYNTHETIC FIXTURE, not an Owner decision: accept O1 as written.',
                         reference=LOG_REF + 'fixture-undated')
        self.refused('STATEMENT_ENTRY_UNDATED', self.record, said=said)

    def test_an_entry_that_is_not_the_owners_is_refused(self):
        # R1, probe P1: the engineering manager's verdict quoting the engineer, and an entry whose title begins
        # "Owner's", not "Owner ".
        text = 'I accept O1 of qual-05-api-rate-limiting as proposed.'
        for anchor in ('fixture-em-verdict-2026-11-15', 'fixture-owners-answers-2026-11-15'):
            with self.subTest(anchor=anchor):
                self.refused('STATEMENT_ENTRY_NOT_OWNER', self.record, said=statement(text=text,
                                                                                       reference=LOG_REF + anchor))

    def test_text_outside_the_verbatim_block_is_refused(self):
        cases = {
            # the product manager's reading, inside the entry but outside its "> " lines
            'reading': 'The E-05.1 design choices and the routine decisions are the product manager\'s',
            'title': 'Owner standing authorization: the D1 manifest\'s reconciliation inside OA-22 (j)',
            'another entry': REACCEPT_TEXT,
            'a word changed': TEXT.replace('intentionally small', 'deliberately small'),
            'case changed': TEXT.lower(),
            'a part of a word': TEXT[1:],
            'out of order': 'aieh-d1-demo: Finalize and accept the OpenSpec change for',
            'across the block\'s end': 'No further Owner approval is required for these planning decisions. The',
            'only markers': '>\n>',
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                self.refused('STATEMENT_OUTSIDE_VERBATIM', self.record, said=statement(text=text))
        said = statement(text='SYNTHETIC FIXTURE, not an Owner decision: accept O1 as written.',
                         reference=LOG_REF + 'fixture-no-verbatim-2026-11-15')
        self.refused('STATEMENT_OUTSIDE_VERBATIM', self.record, said=said)

    def test_only_the_owners_first_block_outside_code_fences_is_his(self):
        # R1, probes P2 (a "> " line inside a code fence), P3 (a question quoted after the Owner's block) and P3b
        # (a run straddling the two).
        cases = {
            'fixture-owner-fence-2026-11-15': ['accept O1 of qual-05-api-rate-limiting from the transcript'],
            'fixture-owner-nested-2026-11-15': ['Shall I accept O1 of qual-05-api-rate-limiting now?',
                                                'qual-05-api-rate-limiting small. Shall I accept O1'],
        }
        for anchor, texts in cases.items():
            for text in texts:
                with self.subTest(anchor=anchor, text=text):
                    self.refused('STATEMENT_OUTSIDE_VERBATIM', self.record,
                                 said=statement(text=text, reference=LOG_REF + anchor))

    def test_a_log_not_committed_at_the_revision_is_refused(self):
        for name in ('untracked', 'uncommitted'):
            with self.subTest(harness=name), self.unchanged(self.root / name):
                self.refused('STATEMENT_LOG_NOT_COMMITTED', self.record, harness=self.root / name)

    def test_a_harness_not_on_main_is_refused(self):
        # R4, probes P5 (HEAD on a side branch holding a fabricated Owner entry) and P8b (HEAD detached).
        said = statement(text='I accept O1 of qual-05-api-rate-limiting.',
                         reference=LOG_REF + 'fixture-fabricated-2026-11-15')
        for name, case in (('side', said), ('detached', statement())):
            with self.subTest(harness=name), self.unchanged(self.root / name):
                error = self.refused('HARNESS_NOT_ON_MAIN', self.record, said=case, harness=self.root / name)
                self.assertIn('refs/heads/main', error.detail)

    def test_a_reference_to_a_missing_object_is_unavailable(self):
        # N1, probe P8: main names an object the repository does not hold.
        with self.unchanged(self.root / 'dangling'):
            self.refused('HARNESS_UNAVAILABLE', self.record, harness=self.root / 'dangling')

    def test_a_statement_not_attributed_to_the_owner_is_refused(self):
        absent = {k: v for k, v in statement().items() if k != 'attributedTo'}
        for case in (statement(attributedTo='person:alice'), statement(attributedTo='Owner'), absent):
            with self.subTest(statement=case):
                self.refused('STATEMENT_NOT_OWNER', self.record, said=case)
        for case in (statement(attributedTo='agent:product-manager'), statement(attributedTo='agent:claude')):
            with self.subTest(statement=case):
                self.refused('ACCEPTANCE_MODEL_AUTHORED', self.record, said=case)

    def test_a_statement_not_about_the_change_is_refused(self):
        # R2, probes P4 ("done"), P4b ("Accept") and P4c ("Do not"): shorter than 12 characters, or naming
        # neither the change nor the project repository.
        terse = LOG_REF + 'fixture-owner-terse-2026-11-15'
        for text, reference in (('done.', terse), ('Accept', REF), ('Do not', REF),
                                ('Resolve the two outstanding planning items.', REF),
                                ('Resolve the two outstanding planning items.', terse)):
            with self.subTest(text=text):
                error = self.refused('STATEMENT_NOT_ABOUT_CHANGE', self.record,
                                     said=statement(text=text, reference=reference))
                self.assertTrue('fewer than 12' in error.detail or 'names neither' in error.detail, error.detail)
        # E-05.1's statement names aieh-d1-demo: refused for a project whose origin names another repository.
        other = self.root / 'other'
        with self.unchanged(other), self.assertRaises(A.RecorderError) as caught:
            self.record(project=other)
        self.assertEqual(caught.exception.code, 'STATEMENT_NOT_ABOUT_CHANGE')
        self.assertIn("'another-project'", caught.exception.detail)

    def test_the_request_itself_is_refused(self):
        said = statement(text=REQUEST_TEXT, reference=REQUEST)
        error = self.refused('ACCEPTANCE_IS_REQUEST', self.record, D1_CHANGE, said=said)
        self.assertIn('Original Quote', error.detail)

    def test_the_requests_own_text_is_refused(self):
        # R3, probe P6: Q1's text of qual-05 (whose source is a conversation), copied into an Owner entry; the
        # whole of its first paragraph, and a part of it.
        laundered = LOG_REF + 'fixture-owner-request-qual-05-2026-11-15'
        for text in (QUAL05_REQUEST, 'Use a fixed window of 100 requests per minute per IP.'):
            with self.subTest(text=text):
                error = self.refused('ACCEPTANCE_IS_REQUEST', self.record,
                                     said=statement(text=text, reference=laundered))
                self.assertIn('Q1', error.detail)

    def test_other_references_and_inputs_are_refused(self):
        for reference in ('conversation:fixture-owner/message-2', 'decision:0018', 'harness:evidence/other.md#x',
                          'harness:evidence/bootstrap-log.md', LOG_REF + 'Bad_Anchor',
                          f'harness:./evidence/bootstrap-log.md#{ANCHOR}'):
            with self.subTest(reference=reference):
                self.refused('STATEMENT_REFERENCE_NOT_LOG', self.record, said=statement(reference=reference))
        for case in (None, statement(text=' '), statement(reference='missing:the-entry')):
            with self.subTest(statement=case):
                with self.unchanged(), self.assertRaises(A.RecorderError) as caught:
                    A.record_from_log(self.repo, PROPOSED, 'O1', case, recorded_by=of.RECORDED_BY,
                                      identity=of.IDENTITY, harness=self.harness, now=LATER)
                self.assertEqual(caught.exception.code, 'ACCEPTANCE_MISSING')
        self.refused('STATEMENT_INVALID', self.record, said=statement(channel='Main Session'))
        self.refused('RECORDED_BY_INVALID', self.record, recorded_by='the engineering manager')
        self.refused('IDENTITY_INVALID', self.record, identity='recorder')
        self.refused('OBJECT_NAME_INVALID', self.record, '../x')
        self.refused('ITEM_NOT_OBJECTIVE', self.record, PROPOSED, 'AC1')
        self.refused('CHANGE_MISSING', self.record, 'qual-99-absent')
        outside = self.root / 'not-a-repository'
        outside.mkdir(exist_ok=True)
        self.refused('HARNESS_UNAVAILABLE', self.record, harness=outside)

    def test_the_real_logs_entries(self):
        # Read only: this checkout's own log at its HEAD (probes P4, P4b, P4c on the real entries). The Owner's act
        # OA-31 (e) is titled "the Owner's act ...": not an Owner entry by R1.
        _, text = committed_log(of.REPO)
        act = G.decisions_entry(text, 'owner-act-oa-31-e-2026-11-15')
        self.assertIsNotNone(act)
        self.assertFalse(act.title.startswith(A.OWNER_TITLE))
        real = G.decisions_entry(text, ANCHOR)
        self.assertTrue(real.title.startswith(A.OWNER_TITLE))
        for short in ('done', 'Accept', 'Do not'):
            with self.subTest(text=short), self.assertRaises(A.RecorderError) as caught:
                A._about(A.statement_words(short), PROPOSED, 'aieh-d1-demo')
            self.assertEqual(caught.exception.code, 'STATEMENT_NOT_ABOUT_CHANGE')


class TheTextMatchingRule(unittest.TestCase):
    """``verbatim_admits``: the Owner's first block, quote markers and line breaks normalized, words compared
    exactly and in order; the names and URLs the record keeps."""

    @classmethod
    def setUpClass(cls):
        fx.require_repository_access()  # fail, never skip, without Dulwich

    @staticmethod
    def entry(anchor=ANCHOR):
        return G.decisions_entry(LOG_FIXTURE.read_text(encoding='utf-8'), anchor)

    def test_quote_markers_and_line_breaks_are_normalized(self):
        entry = self.entry()
        quoted = '\n'.join(f'> {line}' if line else '>' for line in TEXT.split('\n'))
        indented = '\n'.join(f'  > {line}' if line else '  >' for line in TEXT.split('\n'))
        for name, text in {'as written': TEXT, 'one line': ' '.join(TEXT.split()), 'quoted': quoted,
                           'indented and quoted': indented, 'CRLF': TEXT.replace('\n', '\r\n'),
                           'tabs and runs of spaces': TEXT.replace(' ', ' \t  '),
                           'a list item of the block': '- No host filesystem or credential mounts.',
                           'the whole item 2': '2. E-05.1 design\n\n' + TEXT}.items():
            with self.subTest(case=name):
                self.assertTrue(A.verbatim_admits(entry, text), name)
        self.assertEqual(A.statement_words('> a  b\n>\n  > c\n'), ['a', 'b', 'c'])

    def test_what_is_not_admitted(self):
        entry = self.entry()
        for text in ('', '  \n', '>', 'inalize and accept', 'Finalize and accept the OpenSpec change for aieh-d1-demo',
                     'finalize and accept', 'Finalize, and accept'):
            with self.subTest(text=text):
                self.assertFalse(A.verbatim_admits(entry, text))

    def test_the_owners_block_is_the_first_run_outside_code_fences(self):
        self.assertEqual(A.owner_block(self.entry()), self.entry().verbatim)  # one run: the whole block
        fence = self.entry('fixture-owner-fence-2026-11-15')
        self.assertEqual(A.owner_block(fence),
                         'SYNTHETIC FIXTURE: accept O1 of qual-05-api-rate-limiting after the transcript.')
        self.assertTrue(A.verbatim_admits(fence, 'accept O1 of qual-05-api-rate-limiting after the transcript.'))
        self.assertEqual(A.owner_block(self.entry('fixture-owner-nested-2026-11-15')),
                         'Keep qual-05-api-rate-limiting small.')
        self.assertEqual(A.owner_block(self.entry('fixture-no-verbatim-2026-11-15')), '')

    def test_the_copy_is_the_real_entry_and_admits_e_05_1s_statement(self):
        # Read only: this checkout's own log at its HEAD, read whatever branch it is on.
        _, text = committed_log(of.REPO)
        real = G.decisions_entry(text, ANCHOR)
        self.assertEqual(real.date, '2026-11-15')
        self.assertEqual(real.text, self.entry().text)
        self.assertTrue(A.verbatim_admits(real, TEXT))
        self.assertFalse(A.verbatim_admits(real, 'The product manager\'s reading (not the Owner\'s words)'))

    def test_userinfo_is_left_out_of_the_origin(self):
        for url, expected in (
                ('https://fixture-user@example.invalid/h/x.git', 'https://example.invalid/h/x.git'),
                ('https://u:p@example.invalid:8443/h/x.git', 'https://example.invalid:8443/h/x.git'),
                ('ssh://git@example.invalid/h/x.git', 'ssh://example.invalid/h/x.git'),
                ('git@example.invalid:h/x.git', 'example.invalid:h/x.git'),
                ('https://example.invalid/h/x.git', 'https://example.invalid/h/x.git'),
                ('/srv/git/x.git', '/srv/git/x.git')):
            with self.subTest(url=url):
                self.assertEqual(A.without_userinfo(url), expected)

    def test_the_repository_name(self):
        for url, root, expected in (
                ('https://example.invalid/demo/aieh-d1-demo.git', '/w/p', 'aieh-d1-demo'),
                ('https://example.invalid/demo/aieh-d1-demo', '/w/p', 'aieh-d1-demo'),
                ('https://example.invalid/demo/aieh-d1-demo/', '/w/p', 'aieh-d1-demo'),
                ('git@example.invalid:demo/aieh-d1-demo.git', '/w/p', 'aieh-d1-demo'),
                (r'D:\repos\aieh-d1-demo', '/w/p', 'aieh-d1-demo'),
                (None, '/w/aieh-d1-demo', 'aieh-d1-demo'),
                ('https://example.invalid/.git', '/w/aieh-d1-demo', 'aieh-d1-demo')):
            with self.subTest(url=url):
                self.assertEqual(A.repository_name(url, root), expected)


if __name__ == '__main__':
    unittest.main()
