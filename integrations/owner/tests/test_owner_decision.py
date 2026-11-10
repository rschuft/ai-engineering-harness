"""The shared Owner decision record (owner-decision/v1, plan group P-04).

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

Pure tests of ``owner_decision.py``: the record's shape (its fields in order, the kinds, the
``accept-objective`` subject), and how a statement is judged: missing, authored by a model, not
attributed to the Owner, or malformed. Every statement here is synthetic.
"""
import json
import sys
import unittest
from pathlib import Path

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import owner_fixture as of  # noqa: E402

D = of.D


def good_record(**changes):
    record = json.loads(of.EXAMPLE.read_text(encoding='utf-8'))
    record.update(changes)
    return record


class Statement(unittest.TestCase):
    """statement_verdict: who said it decides whether it is an Owner decision at all."""

    def test_an_owner_statement_passes(self):
        self.assertEqual(D.statement_verdict(of.statement()), (None, ''))
        self.assertEqual(D.statement_verdict(of.statement(reference='decision:0015')), (None, ''))

    def test_each_verdict(self):
        cases = [
            (None, D.MISSING),
            (of.statement(text=''), D.MISSING),
            (of.statement(text=' \n\t'), D.MISSING),
            (of.statement(text=None), D.MISSING),
            (of.statement(reference=''), D.MISSING),
            (of.statement(reference='missing:the-owner-reply'), D.MISSING),
            ({k: v for k, v in of.statement().items() if k != 'reference'}, D.MISSING),
            (of.statement(attributedTo='agent:claude-opus-5-5'), D.MODEL),
            (of.statement(attributedTo='agent:overseer', text=''), D.MISSING),  # missing is reported first
            (of.statement(reference='openhands:conversation/2b5f0c1e-8d3a-4a3b-9b2e-1f0e7d6c5b4a'), D.MODEL),
            (of.statement(attributedTo='person:alice'), D.NOT_OWNER),
            (of.statement(attributedTo='Owner'), D.NOT_OWNER),
            (of.statement(attributedTo=''), D.NOT_OWNER),
            ({k: v for k, v in of.statement().items() if k != 'attributedTo'}, D.NOT_OWNER),
            (of.statement(signedBy='owner'), D.INVALID),
            (of.statement(channel='Main Session'), D.INVALID),
            (of.statement(channel=None), D.INVALID),
            (of.statement(reference='conversation:a b'), D.INVALID),
            ('I accept', D.INVALID),
        ]
        for statement, verdict in cases:
            with self.subTest(statement=statement):
                found, detail = D.statement_verdict(statement)
                self.assertEqual(found, verdict)
                self.assertTrue(detail)


class RecordShape(unittest.TestCase):
    """check_record: the shared shape, with kind accept-objective."""

    def test_the_recorded_example_has_the_shared_shape(self):
        record = good_record()
        self.assertEqual(D.check_record(record), [])
        self.assertEqual(list(record), list(D.FIELDS))
        self.assertEqual(list(D.FIELDS), ['format', 'decisionId', 'kind', 'subject', 'shown', 'statement',
                                          'recordedBy', 'recordedAt'])
        self.assertEqual(record['kind'], 'accept-objective')
        self.assertEqual(list(record['shown']), ['summary', 'nonce', 'expiresAt'])
        self.assertEqual(list(record['statement']), ['text', 'attributedTo', 'channel', 'reference'])
        self.assertEqual(record['statement']['attributedTo'], 'owner')
        self.assertTrue(record['statement']['text'].startswith('SYNTHETIC FIXTURE'))
        self.assertEqual(D.dumps(record), of.EXAMPLE.read_text(encoding='utf-8'))

    def test_problems_are_reported(self):
        cases = {
            'format': good_record(format='owner-decision/v2'),
            'decisionId': good_record(decisionId='9E8D7C6B-5A49-4382-A716-5F4E3D2C1B0A'),
            'kind': good_record(kind='accept'),
            'authorize-operation': good_record(kind='authorize-operation'),
            'recordedBy': good_record(recordedBy='the overseer'),
            'recordedAt': good_record(recordedAt='2026-11-10 12:05'),
            'statement': good_record(statement=of.statement(attributedTo='agent:x')),
        }
        subject = good_record()['subject']
        cases['subject.item'] = good_record(subject={**subject, 'item': 'AC1'})
        cases['subject.revision'] = good_record(subject={**subject, 'revision': 'HEAD'})
        cases['subject fields'] = good_record(subject={'change': subject['change']})
        shown = good_record()['shown']
        cases['shown.nonce'] = good_record(shown={**shown, 'nonce': 'abc'})
        reordered = good_record()
        reordered = {'kind': reordered.pop('kind'), **reordered}
        cases['order'] = reordered
        for name, record in cases.items():
            with self.subTest(case=name):
                self.assertTrue(D.check_record(record), name)
        self.assertEqual(D.check_record([]), ['the record must be an object'])

    def test_a_kept_hand_minted_outcome_id_is_accepted(self):
        subject = {**good_record()['subject'], 'outcome': '5c6f4c1e-8d3a-1a3b-0b2e-1f0e7d6c5b4a'}
        self.assertEqual(D.check_record(good_record(subject=subject)), [])

    def test_new_decision_ids_are_random_version_4_uuids(self):
        ids = {D.new_decision_id() for _ in range(5)}
        self.assertEqual(len(ids), 5)
        self.assertTrue(all(D.UUID4.match(i) for i in ids), ids)


if __name__ == '__main__':
    unittest.main()
