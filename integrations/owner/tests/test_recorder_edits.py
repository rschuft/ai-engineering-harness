"""The acceptance recorder's edits of a change's files (plan leaf P-04.1).

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

Pure tests: ``set_acceptance`` rewrites only the Objective item's authority and acceptance lines of
``proposal.md``; ``declare_outcome`` writes ``x-outcomes`` in decision 0008's form into
``.openspec.yaml``, which the lineage resolver's strict reader reads back; every other byte is kept,
line endings included. The challenge's summary is a function of the change at one commit.
"""
import json
import sys
import unittest
from pathlib import Path

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import owner_fixture as of  # noqa: E402

A = of.A
R = A.R
OUTCOME = of.OUTCOME
OTHER = '11111111-2222-4333-8444-555555555555'
REF = 'conversation:fixture-owner/message-2'
CHANGES = of.INTENT_OPENSPEC / 'changes'


def proposal(change=of.PROPOSED):
    return (CHANGES / change / 'proposal.md').read_bytes()


class SetAcceptance(unittest.TestCase):

    def test_a_proposed_objective_becomes_accepted_and_nothing_else_changes(self):
        before = proposal()
        after = A.set_acceptance(before, 'O1', REF)
        self.assertEqual(after.replace(b'- authority: accepted\n- acceptance: ' + REF.encode() + b'\n',
                                       b'- authority: proposed\n', 1), before)
        self.assertEqual(A._record_problems(after), [])
        record, _ = R._intent_module()._Parser(after).parse()
        self.assertEqual((record.items['O1'].fields['authority'], record.items['O1'].fields['acceptance']),
                         ('accepted', REF))
        # The acceptance criteria and the other items keep their own authority.
        self.assertEqual({ac.fields['authority'] for ac in record.sections['Acceptance Criteria']}, {'proposed'})

    def test_an_existing_acceptance_is_rewritten_in_place(self):
        before = proposal(of.HAND_ACCEPTED)
        after = A.set_acceptance(before, 'O1', REF)
        self.assertEqual(len(after.splitlines()), len(before.splitlines()))
        self.assertEqual(after.replace(REF.encode(), b'conversation:qual-02/message-2', 1), before)
        self.assertEqual(A._record_problems(after), [])

    def test_crlf_line_endings_are_kept(self):
        before = proposal().replace(b'\n', b'\r\n')
        after = A.set_acceptance(before, 'O1', REF)
        self.assertNotIn(b'\n', after.replace(b'\r\n', b''))
        self.assertIn(b'- authority: accepted\r\n- acceptance: ' + REF.encode() + b'\r\n', after)

    def test_the_line_round_trip_is_exact(self):
        for data in (b'', b'a', b'a\n', b'a\r\nb', b'a\r\n\r\n', b'\n\n'):
            with self.subTest(data=data):
                self.assertEqual(A._join(A._split_lines(data)), data)


class DeclareOutcome(unittest.TestCase):

    def read(self, data):
        return R.read_x_outcomes(data)

    def test_a_new_block_is_appended(self):
        meta = b'schema: intent-driven\ncreated: 2026-11-06\n'
        after = A.declare_outcome(meta, OUTCOME, 'O1', REF)
        self.assertEqual(after, meta + f'x-outcomes:\n  {OUTCOME}:\n    item: O1\n    acceptance: {REF}\n'.encode())
        self.assertEqual(self.read(after), {OUTCOME: {'item': 'O1', 'acceptance': REF}})

    def test_a_file_without_a_final_line_break(self):
        after = A.declare_outcome(b'schema: intent-driven', OUTCOME, 'O1', REF)
        self.assertEqual(after, f'schema: intent-driven\nx-outcomes:\n  {OUTCOME}:\n    item: O1\n'
                                f'    acceptance: {REF}\n'.encode())

    def test_an_entry_is_added_to_an_existing_block_with_its_indentation(self):
        meta = (f'schema: intent-driven\nx-outcomes:\n    {OTHER}:\n        item: O2\n'
                f'        acceptance: decision:0015\n\n# a comment\nlater: key\n').encode()
        after = A.declare_outcome(meta, OUTCOME, 'O1', REF)
        self.assertEqual(self.read(after), {OTHER: {'item': 'O2', 'acceptance': 'decision:0015'},
                                            OUTCOME: {'item': 'O1', 'acceptance': REF}})
        self.assertIn(f'    {OUTCOME}:\n        item: O1\n        acceptance: {REF}\n\n# a comment\nlater: key\n'
                      .encode(), after)

    def test_an_amendment_rewrites_only_the_acceptance(self):
        meta = (f'x-outcomes:\n  {OTHER}:\n    item: O2\n    acceptance: decision:0015\n'
                f'  {OUTCOME}:\n    acceptance: {REF}\n    item: O1\nschema: intent-driven\n').encode()
        after = A.declare_outcome(meta, OUTCOME, 'O1', 'decision:0016')
        self.assertEqual(after, meta.replace(f'acceptance: {REF}'.encode(), b'acceptance: decision:0016'))
        self.assertEqual(self.read(after)[OUTCOME], {'item': 'O1', 'acceptance': 'decision:0016'})

    def test_crlf_is_kept(self):
        meta = b'schema: intent-driven\r\ncreated: 2026-11-06\r\n'
        after = A.declare_outcome(meta, OUTCOME, 'O1', REF)
        self.assertNotIn(b'\n', after.replace(b'\r\n', b''))
        self.assertEqual(self.read(after), {OUTCOME: {'item': 'O1', 'acceptance': REF}})


class Summary(unittest.TestCase):

    def test_every_refusal_code_has_a_remedy_in_its_message(self):
        for code, remedy in A.REMEDIES.items():
            with self.subTest(code=code):
                error = A.RecorderError(code, 'detail')
                self.assertTrue(remedy.strip())
                self.assertEqual(str(error), f'{code}: detail. Remedy: {remedy}.')
        with self.assertRaises(KeyError):
            A.RecorderError('NOT_A_CODE', 'detail')

    def test_the_commit_message_carries_the_trailers(self):
        decision = json.loads(of.EXAMPLE.read_text(encoding='utf-8'))
        message = A.commit_message(decision, True, decision['statement'])
        self.assertTrue(message.startswith(f'Accept O1 of {of.PROPOSED}: outcome {OUTCOME} (outcome id minted)\n'))
        self.assertTrue(message.endswith(f'AIEH-Decision-Id: {of.DECISION}\nAIEH-Outcome-Id: {OUTCOME}\n'
                                         f'AIEH-Recorder: {A.RECORDER}\n'))
        self.assertIn('Re-accept O1', A.commit_message(decision, False, decision['statement']))


if __name__ == '__main__':
    unittest.main()
