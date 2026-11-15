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

The harness log is ``fixtures/recorded-statement-log.md``: a byte-for-byte copy of the real entry anchored
``owner-direction-d1-planning-2026-11-15`` (a multi-line verbatim block, the real target of E-05.1) among
SYNTHETIC entries. Every statement recorded here is a test's: no Owner decision is recorded, and nothing is
written to the real harness log, the demo repository or the managed data root. One test reads this checkout's
own log at its HEAD, read-only, to show that the copy is the real entry and that the real entry admits E-05.1's
statement.
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

ANCHOR = 'owner-direction-d1-planning-2026-11-15'
REF = f'harness:evidence/bootstrap-log.md#{ANCHOR}'
REACCEPT = 'harness:evidence/bootstrap-log.md#fixture-owner-reaccept-2026-11-16'
REQUEST = 'harness:evidence/bootstrap-log.md#owner-decision-oa-31-2026-11-14'  # add-slugify's Q1 source
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
REACCEPT_TEXT = 'SYNTHETIC FIXTURE, not an Owner decision: accept O1 again, as amended.'
REQUEST_TEXT = 'OA-25: use aieh-d1-demo, a small Python package with unittest tests.'
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


def build_harness(repo, log=None, commit=True):
    """A throwaway harness repository at REPO holding LOG (the fixture log's bytes by default) as
    evidence/bootstrap-log.md: committed, or (COMMIT false) only in the work tree beside a committed README.
    Returns HEAD's commit, or None when nothing is committed."""
    Path(repo).mkdir(parents=True)
    fx.git(repo, 'init', '--quiet', '-b', 'main')
    data = LOG_FIXTURE.read_bytes() if log is None else log
    if commit:
        fx.write(repo, {'README.md': b'Throwaway harness repository (E-05.12 fixture).\n',
                        'evidence/bootstrap-log.md': data})
        return fx.commit_all(repo, 'The fixture log')
    fx.write(repo, {'evidence/bootstrap-log.md': data})
    return None


def add_d1_change(repo):
    """Commit a copy of the D1 demo design (evidence/D1-demo-design, read only) as a change of REPO."""
    files = {}
    for path in sorted(D1_DESIGN.rglob('*')):
        if path.is_file():
            files[f'openspec/changes/{D1_CHANGE}/{path.relative_to(D1_DESIGN).as_posix()}'] = path.read_bytes()
    fx.write(repo, files)
    return fx.commit_all(repo, 'The D1 demo design (a copy)')


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
        design = of.build_project(root / 'p')
        return design, build_harness(root / 'h')

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

    def record(self, change=PROPOSED, item='O1', said=None, **kwargs):
        kwargs.setdefault('recorded_by', of.RECORDED_BY)
        kwargs.setdefault('identity', of.IDENTITY)
        kwargs.setdefault('now', LATER)
        kwargs.setdefault('harness', self.harness)
        return A.record_from_log(self.repo, change, item, statement() if said is None else said, **kwargs)

    def resolve(self, text, current=False):
        resolver = R.ObjectiveResolver(self.repo)
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
            'revision': self.harness_head, 'digest': 'sha256:' + hashlib.sha256(blob).hexdigest(),
            'challengeShown': False})
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
        # A rehearsal of E-05.1 on a copy of the D1 demo design: O1 of add-slugify, accepted from the copy of
        # the entry anchored owner-direction-d1-planning-2026-11-15; the reference to its Q1's source is the
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
        design, head = Fixture.build(root)
        add_d1_change(root / 'p')
        design = fx.loose_head(root / 'p')
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
        added = (b'- <a id="fixture-work-tree-only-2026-11-15"></a>**2026-11-15: SYNTHETIC FIXTURE: an entry only in '
                 b'the work tree, verbatim.**\n\n  > SYNTHETIC FIXTURE, not an Owner decision: accept O1 as written.\n')
        log = LOG_FIXTURE.read_bytes().replace(b'\n## Owner-directed maintenance items', added + b'\n## Owner-directed '
                                               b'maintenance items')
        assert log != LOG_FIXTURE.read_bytes()
        (edited / 'evidence' / 'bootstrap-log.md').write_bytes(log)
        return design, head

    def test_an_absent_anchor_is_refused(self):
        for anchor in ('no-such-entry', 'fixture-before-decisions', 'fixture-after-decisions-2026-11-15'):
            with self.subTest(anchor=anchor):
                self.refused('STATEMENT_ANCHOR_ABSENT', self.record,
                             said=statement(reference=f'harness:evidence/bootstrap-log.md#{anchor}'))

    def test_an_entry_only_in_the_work_tree_is_refused(self):
        said = statement(text='SYNTHETIC FIXTURE, not an Owner decision: accept O1 as written.',
                         reference='harness:evidence/bootstrap-log.md#fixture-work-tree-only-2026-11-15')
        with self.unchanged(self.root / 'edited'):
            self.refused('STATEMENT_ANCHOR_ABSENT', self.record, said=said, harness=self.root / 'edited')

    def test_an_entry_without_a_dated_title_is_refused(self):
        said = statement(text='SYNTHETIC FIXTURE, not an Owner decision: accept O1 as written.',
                         reference='harness:evidence/bootstrap-log.md#fixture-undated')
        self.refused('STATEMENT_ENTRY_UNDATED', self.record, said=said)

    def test_text_outside_the_verbatim_block_is_refused(self):
        cases = {
            # the product manager's reading, inside the entry but outside its "> " lines
            'reading': 'The E-05.1 design choices and the routine decisions are the product manager\'s',
            'title': 'Owner standing authorization: the D1 manifest\'s reconciliation inside OA-22 (j)',
            'another entry': 'SYNTHETIC FIXTURE, not an Owner decision: accept O1 again, as amended.',
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
                         reference='harness:evidence/bootstrap-log.md#fixture-no-verbatim-2026-11-15')
        self.refused('STATEMENT_OUTSIDE_VERBATIM', self.record, said=said)

    def test_a_log_not_committed_at_the_revision_is_refused(self):
        for name in ('untracked', 'uncommitted'):
            with self.subTest(harness=name), self.unchanged(self.root / name):
                self.refused('STATEMENT_LOG_NOT_COMMITTED', self.record, harness=self.root / name)

    def test_a_statement_not_attributed_to_the_owner_is_refused(self):
        absent = {k: v for k, v in statement().items() if k != 'attributedTo'}
        for case in (statement(attributedTo='person:alice'), statement(attributedTo='Owner'), absent):
            with self.subTest(statement=case):
                self.refused('STATEMENT_NOT_OWNER', self.record, said=case)
        for case in (statement(attributedTo='agent:product-manager'), statement(attributedTo='agent:claude')):
            with self.subTest(statement=case):
                self.refused('ACCEPTANCE_MODEL_AUTHORED', self.record, said=case)

    def test_the_request_itself_is_refused(self):
        said = statement(text=REQUEST_TEXT, reference=REQUEST)
        error = self.refused('ACCEPTANCE_IS_REQUEST', self.record, D1_CHANGE, said=said)
        self.assertIn('Original Quote', error.detail)

    def test_other_references_and_inputs_are_refused(self):
        for reference in ('conversation:fixture-owner/message-2', 'decision:0018', 'harness:evidence/other.md#x',
                          'harness:evidence/bootstrap-log.md', 'harness:evidence/bootstrap-log.md#Bad_Anchor',
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


class TheTextMatchingRule(unittest.TestCase):
    """``verbatim_admits``: quote markers and line breaks normalized, words compared exactly and in order."""

    @classmethod
    def setUpClass(cls):
        fx.require_repository_access()  # fail, never skip, without Dulwich

    def entry(self):
        return G.decisions_entry(LOG_FIXTURE.read_text(encoding='utf-8'), ANCHOR)

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

    def test_the_copy_is_the_real_entry_and_admits_e_05_1s_statement(self):
        # Read-only: this checkout's own log at its HEAD, through the recorder's reader.
        real = A.read_log_entry(of.REPO, ANCHOR)
        self.assertEqual(real.entry.date, '2026-11-15')
        self.assertEqual(real.entry.text, self.entry().text)
        self.assertTrue(A.verbatim_admits(real.entry, TEXT))
        self.assertFalse(A.verbatim_admits(real.entry, 'The product manager\'s reading (not the Owner\'s words)'))


if __name__ == '__main__':
    unittest.main()
