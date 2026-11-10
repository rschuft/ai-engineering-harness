"""The acceptance recorder (plan leaf P-04.1; decision 0008), on throwaway fixture repositories.

Run from the repository root, under the tools interpreter (Dulwich is required: without it these
tests fail with REPOSITORY_NEEDS_DULWICH, never skip):

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

The plan's proof: a recorded acceptance resolves through the lineage objective resolver;
re-recording keeps the id; the decision record has the shared shape with kind accept-objective; a
missing or non-Owner acceptance, or a statement not attributed to the Owner, is refused. Each
refusal leaves the branch, the work tree and the index as they were. Every statement here is
synthetic: it stands in for an Owner statement and is no Owner decision. git, which builds the
fixture, is the oracle of the commit (``fsck --strict``, ``status``).
"""
import contextlib
import datetime
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
R, L, ra = A.R, A.L, A.ra
NOW = of.NOW
LATER = NOW + datetime.timedelta(minutes=5)
PROPOSED, HAND = of.PROPOSED, of.HAND_ACCEPTED
REF = of.statement()['reference']
AMENDED = 'conversation:fixture-owner/message-7'


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


class Fixture(unittest.TestCase):
    # SHARED: one project repository for the class, for tests whose every call is refused (each
    # asserts that nothing changed); otherwise a fresh copy for each test.
    SHARED = False

    @classmethod
    def setUpClass(cls):
        fx.require_repository_access()  # fail, never skip, without Dulwich
        if cls.SHARED:
            cls.shared_root = Path(tempfile.mkdtemp(prefix='ow-'))
            cls.shared_design = of.build_project(cls.shared_root / 'p')

    @classmethod
    def tearDownClass(cls):
        if cls.SHARED:
            fx.rmtree(cls.shared_root)

    def setUp(self):
        if self.SHARED:
            self.root, self.design = self.shared_root, self.shared_design
        else:
            self.root = Path(tempfile.mkdtemp(prefix='ow-'))
            self.addCleanup(fx.rmtree, self.root)
            self.design = of.build_project(self.root / 'p')
        self.repo = self.root / 'p'
        ceiling = fx.ceiling(self.root)
        ceiling.start()
        self.addCleanup(ceiling.stop)

    def prepare(self, change=PROPOSED, item='O1', **kwargs):
        kwargs.setdefault('now', NOW)
        return A.prepare(self.repo, change, item, **kwargs)

    def record(self, challenge, statement=None, **kwargs):
        kwargs.setdefault('recorded_by', of.RECORDED_BY)
        kwargs.setdefault('identity', of.IDENTITY)
        kwargs.setdefault('now', LATER)
        return A.record(self.repo, challenge, of.statement() if statement is None else statement, **kwargs)

    def head(self):
        return fx.loose_head(self.repo)

    def resolve(self, text, current=False):
        resolver = R.ObjectiveResolver(self.repo)
        reference = L.parse(text)
        return resolver.current(reference) if current else resolver.resolve(reference)

    @contextlib.contextmanager
    def unchanged(self):
        """The block must leave the branch, the work tree and the index as they were."""
        head, files = self.head(), worktree(self.repo)
        index = (self.repo / '.git' / 'index').read_bytes()
        yield
        self.assertEqual(self.head(), head)
        self.assertEqual(worktree(self.repo), files)
        self.assertEqual((self.repo / '.git' / 'index').read_bytes(), index)

    def refused(self, code, call, *args, **kwargs):
        with self.unchanged(), self.assertRaises(A.RecorderError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code, caught.exception)
        self.assertIn(f'Remedy: {A.REMEDIES[code]}', str(caught.exception))
        return caught.exception


class Recording(Fixture):
    """Recording mints the id once, writes the shared record, and resolves through lineage."""

    def test_a_recorded_acceptance_resolves_through_the_lineage_objective_resolver(self):
        result = self.record(self.prepare())
        self.assertTrue(result['minted'])
        self.assertEqual(result['reference'], f'outcome:{result["outcome"]}@{result["commit"]}')
        self.assertEqual(self.head(), result['commit'])
        for current in (False, True):
            with self.subTest(current=current):
                answer = self.resolve(result['reference'], current=current)
                self.assertTrue(answer.resolved, answer)
                self.assertEqual(answer.observed_revision, result['commit'])
                self.assertEqual(answer.facts['change'], f'openspec/changes/{PROPOSED}')
                self.assertEqual(answer.facts['item'], 'O1')
                self.assertEqual(answer.facts['acceptance'], REF)
                self.assertEqual(answer.facts['source'], ['Q1'])
        # Pinned before the acceptance, the outcome did not exist.
        before = self.resolve(f'outcome:{result["outcome"]}@{self.design}')
        self.assertEqual((before.outcome, before.code), (L.MISSING, 'OUTCOME_MISSING'))

    def test_the_commit_holds_the_record_the_item_and_the_declaration(self):
        result = self.record(self.prepare())
        base = f'openspec/changes/{PROPOSED}'
        self.assertEqual(result['path'], f'{base}/owner-decisions/{result["decision"]["decisionId"]}.json')
        self.assertEqual(fx.git(self.repo, 'diff', '--name-only', self.design, result['commit']).splitlines(),
                         [f'{base}/.openspec.yaml', f'{base}/owner-decisions/{result["decision"]["decisionId"]}.json',
                          f'{base}/proposal.md'])
        fx.git(self.repo, 'fsck', '--strict', '--no-progress')
        self.assertEqual(fx.git(self.repo, 'status', '--porcelain', '--untracked-files=all'), '')
        message = fx.git(self.repo, 'log', '-1', '--format=%an <%ae>%n%B')
        self.assertTrue(message.startswith(f'{of.IDENTITY}\nAccept O1 of {PROPOSED}: outcome {result["outcome"]}'))
        self.assertIn(f'AIEH-Decision-Id: {result["decision"]["decisionId"]}\nAIEH-Outcome-Id: {result["outcome"]}\n'
                      f'AIEH-Recorder: {A.RECORDER}', message)
        with ra.open_repository(self.repo, config='repository') as repo:
            stored = repo.blob(result['commit'], result['path'])
            meta = repo.blob(result['commit'], f'{base}/.openspec.yaml')
        self.assertEqual(stored, D.dumps(result['decision']).encode('utf-8'))
        self.assertEqual(R.read_x_outcomes(meta), {result['outcome']: {'item': 'O1', 'acceptance': REF}})

    def test_the_decision_record_has_the_shared_shape_with_kind_accept_objective(self):
        challenge = self.prepare()
        result = self.record(challenge)
        record = result['decision']
        self.assertEqual(D.check_record(record), [])
        self.assertEqual(list(record), list(D.FIELDS))
        self.assertEqual(record['kind'], 'accept-objective')
        self.assertTrue(D.UUID4.match(record['decisionId']))
        self.assertTrue(D.UUID4.match(result['outcome']))
        self.assertEqual(record['subject'], {'change': PROPOSED, 'item': 'O1', 'outcome': result['outcome'],
                                             'revision': self.design, 'proposal': challenge['subject']['proposal']})
        self.assertEqual(record['shown'], challenge['shown'])
        self.assertEqual(record['statement'], of.statement())
        self.assertEqual((record['recordedBy'], record['recordedAt']), (of.RECORDED_BY, '2026-11-10T12:05:00Z'))
        # With a fixed clock, nonce and ids, the record is the committed example byte for byte.
        work = self.root / 'x'
        work.mkdir()
        self.assertEqual(D.dumps(of.example(work)['decision']), of.EXAMPLE.read_text(encoding='utf-8'))

    def test_re_recording_keeps_the_id(self):
        first = self.record(self.prepare())
        never = mock.Mock(side_effect=AssertionError('a second outcome id was minted'))
        second = self.record(self.prepare(), of.statement(reference=AMENDED), amend=True, new_outcome=never)
        never.assert_not_called()
        self.assertFalse(second['minted'])
        self.assertEqual(second['outcome'], first['outcome'])
        self.assertNotEqual(second['decision']['decisionId'], first['decision']['decisionId'])
        self.assertEqual(self.resolve(second['reference']).facts['acceptance'], AMENDED)
        # The earlier pinned reading is immutable: the same id, the earlier acceptance.
        earlier = self.resolve(first['reference'])
        self.assertTrue(earlier.resolved, earlier)
        self.assertEqual(earlier.facts['acceptance'], REF)
        with ra.open_repository(self.repo, config='repository') as repo:
            meta = repo.blob(second['commit'], f'openspec/changes/{PROPOSED}/.openspec.yaml')
            records = repo.files(second['commit'], f'openspec/changes/{PROPOSED}/owner-decisions')
        self.assertEqual(R.read_x_outcomes(meta), {first['outcome']: {'item': 'O1', 'acceptance': AMENDED}})
        self.assertEqual(sorted(records), sorted([first['path'], second['path']]))

    def test_re_minting_is_refused(self):
        first = self.record(self.prepare())
        never = mock.Mock(side_effect=AssertionError('a second outcome id was minted'))
        error = self.refused('OUTCOME_ALREADY_MINTED', self.record, self.prepare(), of.statement(reference=AMENDED),
                             new_outcome=never)
        never.assert_not_called()
        self.assertIn(first['outcome'], error.detail)

    def test_an_objective_accepted_by_hand_gets_its_id_once(self):
        # qual-02's O1 was accepted by hand (the P-01.2 fixture standing in for the Owner), with no id.
        result = self.record(self.prepare(HAND), of.statement(reference='conversation:qual-02/message-2'))
        self.assertTrue(result['minted'])
        answer = self.resolve(result['reference'])
        self.assertTrue(answer.resolved, answer)
        self.assertEqual(answer.facts['acceptance_criteria'], ['AC1'])
        self.refused('OUTCOME_ALREADY_MINTED', self.record, self.prepare(HAND))

    def test_amendments_need_an_id_and_a_new_acceptance(self):
        self.refused('OUTCOME_NOT_MINTED', self.record, self.prepare(), amend=True)
        self.record(self.prepare())
        self.refused('ACCEPTANCE_ALREADY_RECORDED', self.record, self.prepare(), amend=True)

    def test_the_checkout_is_clean_under_core_autocrlf(self):
        # The files are written as their blob bytes (LF); git cleans them to the same blobs.
        fx.git(self.repo, 'config', 'core.autocrlf', 'true')
        result = self.record(self.prepare())
        self.assertEqual(fx.git(self.repo, 'status', '--porcelain', '--untracked-files=all'), '')
        with ra.open_repository(self.repo, config='repository') as repo:
            self.assertEqual(repo.status(untracked='all'), [])
        self.assertTrue(self.resolve(result['reference']).resolved)

    def test_no_process_is_launched(self):
        with mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('a process was launched')):
            result = self.record(self.prepare())
        self.assertTrue(result['minted'])


class StatementRefusals(Fixture):
    """Each refusal has its stable code and remedy, and changes nothing (one shared repository)."""
    SHARED = True

    def test_a_missing_acceptance_is_refused(self):
        challenge = self.prepare()
        statement = {k: v for k, v in of.statement().items() if k != 'reference'}
        for case in (None, of.statement(text=''), of.statement(text='  '), statement,
                     of.statement(reference='missing:the-owner-reply')):
            with self.subTest(statement=case):
                self.refused('ACCEPTANCE_MISSING', A.record, self.repo, challenge, case,
                             recorded_by=of.RECORDED_BY, identity=of.IDENTITY, now=LATER)

    def test_an_acceptance_authored_by_a_model_is_refused(self):
        challenge = self.prepare()
        for case in (of.statement(attributedTo='agent:claude-opus-5-5'), of.statement(attributedTo='agent:overseer'),
                     of.statement(reference='openhands:conversation/2b5f0c1e-8d3a-4a3b-9b2e-1f0e7d6c5b4a')):
            with self.subTest(statement=case):
                self.refused('ACCEPTANCE_MODEL_AUTHORED', self.record, challenge, case)

    def test_a_statement_not_attributed_to_the_owner_is_refused(self):
        challenge = self.prepare()
        absent = {k: v for k, v in of.statement().items() if k != 'attributedTo'}
        for case in (of.statement(attributedTo='person:alice'), of.statement(attributedTo='Owner'), absent):
            with self.subTest(statement=case):
                self.refused('STATEMENT_NOT_OWNER', self.record, challenge, case)

    def test_malformed_statements_and_references_are_refused(self):
        challenge = self.prepare()
        self.refused('STATEMENT_INVALID', self.record, challenge, of.statement(via='chat'))
        self.refused('STATEMENT_INVALID', self.record, challenge, of.statement(channel='Main Session'))
        for reference in ('backlog:TASK-1', 'conversation:fixture-owner', 'nonsense:x',
                          'conversation:qual-05/message-1'):  # the last is the request itself (Q1)
            with self.subTest(reference=reference):
                self.refused('ACCEPTANCE_REFERENCE_INVALID', self.record, challenge, of.statement(reference=reference))
        self.refused('RECORDED_BY_INVALID', self.record, challenge, recorded_by='the overseer')
        self.refused('IDENTITY_INVALID', self.record, challenge, identity='recorder')

    def test_names_and_items_are_refused(self):
        self.refused('CHANGE_MISSING', self.prepare, 'qual-99-absent')
        self.refused('ITEM_NOT_OBJECTIVE', self.prepare, PROPOSED, 'AC1')
        self.refused('ITEM_NOT_OBJECTIVE', self.prepare, PROPOSED, 'O9')
        self.refused('OBJECT_NAME_INVALID', self.prepare, 'archive')
        self.refused('OBJECT_NAME_INVALID', self.prepare, '../x')
        outside = self.root / 'not-a-repository'
        outside.mkdir()
        with self.assertRaises(A.RecorderError) as caught:
            A.prepare(outside, PROPOSED, 'O1')
        self.assertEqual(caught.exception.code, 'PROJECT_UNAVAILABLE')


class Refusals(Fixture):
    """Refusals around recordings, hooks and local changes: each changes nothing."""

    def test_challenge_refusals(self):
        challenge = self.prepare()
        self.refused('CHALLENGE_MISSING', A.record, self.repo, None, of.statement(), recorded_by=of.RECORDED_BY,
                     identity=of.IDENTITY, now=LATER)
        tampered = json.loads(json.dumps(challenge))
        tampered['shown']['summary'] += '\nand AC1 too'
        other = json.loads(json.dumps(challenge))
        other['subject']['revision'] = '0' * 40
        for case in (tampered, other, {**challenge, 'format': 'x'}, {'kind': 'accept-objective'},
                     {**challenge, 'shown': {**challenge['shown'], 'nonce': 'abc'}},
                     {**challenge, 'subject': {**challenge['subject'], 'change': '../x'}}):
            with self.subTest(challenge=case):
                self.refused('CHALLENGE_INVALID', self.record, case)
        self.refused('CHALLENGE_EXPIRED', self.record, challenge, now=NOW + datetime.timedelta(hours=1))
        result = self.record(challenge)
        self.refused('CHALLENGE_CONSUMED', self.record, challenge, of.statement(reference=AMENDED), amend=True)
        # The proposal changed after the summary was shown: stale.
        fresh = self.prepare()
        proposal = self.repo / 'openspec' / 'changes' / PROPOSED / 'proposal.md'
        proposal.write_bytes(proposal.read_bytes().replace(b'## Why\n', b'## Why\n\nEdited after the summary.\n'))
        fx.commit_all(self.repo, 'edit the proposal')
        self.refused('CHALLENGE_STALE', self.record, fresh, of.statement(reference=AMENDED), amend=True)
        self.assertTrue(self.resolve(result['reference']).resolved)

    def test_a_repository_with_client_hooks_is_refused(self):
        challenge = self.prepare()
        (self.repo / '.git' / 'hooks' / 'pre-commit').write_text('#!/bin/sh\nexit 0\n', encoding='ascii')
        error = self.refused('HOOKS_UNSUPPORTED', self.record, challenge)
        self.assertEqual(error.details['hook'], 'hooks/pre-commit')

    def test_local_changes_to_the_change_are_refused(self):
        challenge = self.prepare()
        meta = self.repo / 'openspec' / 'changes' / PROPOSED / '.openspec.yaml'
        meta.write_bytes(meta.read_bytes() + b'# a local edit\n')
        error = self.refused('COMMIT_REFUSED', self.record, challenge)
        self.assertEqual(error.details['reason'], 'local-changes')

    def test_a_resolution_failure_moves_nothing(self):
        challenge = self.prepare()

        def missing(resolver, reference):
            return L.answer(reference, L.MISSING, resolver.authority, 'OUTCOME_MISSING', 'stand-in')

        with mock.patch.object(R.ObjectiveResolver, 'resolve', missing):
            self.refused('RESOLUTION_FAILED', self.record, challenge)
        self.assertTrue(self.record(challenge)['minted'])


class CommandLine(Fixture):
    """acceptance_recorder.py prepare and record (task owner:accept)."""

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = A.main(list(argv), out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def test_prepare_then_record(self):
        challenge = self.root / 'challenge.json'
        code, out, err = self.run_main('prepare', '--project', str(self.repo), '--change', PROPOSED, '--item', 'O1',
                                       '--out', str(challenge))
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out), json.loads(challenge.read_text(encoding='utf-8')))
        statement = self.root / 'statement.json'
        statement.write_text(json.dumps(of.statement()), encoding='utf-8')
        code, out, err = self.run_main('record', '--project', str(self.repo), '--challenge', str(challenge),
                                       '--statement', str(statement), '--recorded-by', of.RECORDED_BY,
                                       '--identity', of.IDENTITY)
        self.assertEqual((code, err), (0, ''))
        result = json.loads(out)
        self.assertTrue(self.resolve(result['reference']).resolved)

    def test_a_refusal_exits_2_with_its_code_and_remedy(self):
        challenge = self.root / 'challenge.json'
        self.run_main('prepare', '--project', str(self.repo), '--change', PROPOSED, '--item', 'O1',
                      '--out', str(challenge))
        with self.unchanged():
            code, out, err = self.run_main('record', '--project', str(self.repo), '--challenge', str(challenge),
                                           '--recorded-by', of.RECORDED_BY, '--identity', of.IDENTITY)
        self.assertEqual((code, out), (2, ''))
        self.assertTrue(err.startswith('acceptance-recorder: ACCEPTANCE_MISSING: '), err)
        self.assertIn(f'Remedy: {A.REMEDIES["ACCEPTANCE_MISSING"]}', err)


if __name__ == '__main__':
    unittest.main()
