"""The proof of plan leaf S-03.5, slice 2: the model selection at the broker's start and per request.

Run from the repository root, under the tools interpreter (Dulwich is required):

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -v

The C rows of the work design's proof table (answer.md section 6.4). The provider-envelope receipts are made by
the REAL authorization recorder against the owner suite's fake Gitea (envelope_support.py); the selections by the
REAL act (integrations/owner/selection_recorder.py, decided by agent:engineering-manager) on the dispatch-input
commands' fixture harness repository whose decision 0018 is Accepted (Owner) (integrations/owner/tests/
input_fixture.py); both are read by the REAL read side (integrations/owner/envelope_decisions.py). A
hand-written record appears only where a test says so. Rows C1 and C2's two slice-1 cases are in
test_envelope.py (test_the_model_selection_is_part_of_the_digest, test_b1_..., and the two
..._is_missing tests). Every statement, basis and selection is SYNTHETIC.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
import unittest

import envelope_support as V

S, IB, E, ED, AR = V.S, V.IB, V.E, V.ED, V.AR
sys.path.insert(0, str(S.REPO / 'integrations' / 'owner' / 'tests'))
import input_fixture as fi  # noqa: E402

SR = fi._load('selection_recorder', fi.OWNER / 'selection_recorder.py')
CATEGORY = 'integration'
EM, PM = fi.EM, fi.PM
ORIGIN_TEXT = 'https://api.provider.test:443'
COMMIT_RUN = re.compile(r'(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])')


def setUpModule():
    fi.start()


def tearDownModule():
    fi.stop()


def delegated(models=(S.MODEL_A,), **block):
    """A component whose envelope delegates the model selection, with MODELS configured for its family."""
    return V.component(models=models, envelope=V.block(selection='delegation', **block))


def chosen(*models, family='anthropic-messages'):
    return {'leaf': 'S-03.3',
            'models': {family: [{'id': m, 'use': 'the coding turn (SYNTHETIC)', 'cost': 'about 1 USD (SYNTHETIC)'}
                                for m in models]},
            'verified': {'source': 'https://provider.example.test/models (SYNTHETIC)', 'at': '2026-11-30T11:00:00Z'}}


class SelectionCase(V.EnvelopeCase):
    def receipt(self, raw, operation=V.OPERATION):
        return self.confirmed(raw, operation)['receipt']['operation_key']

    def select(self, receipt, *models):
        """The real act: agent:engineering-manager selects MODELS on RECEIPT (the fixture harness repository)."""
        store = S.STORE.open_store(self.db)
        try:
            ctx = SR.Context(self.tmp / 'state', store, fi._SHARED[-1][2].harness['accepted'],
                             now=lambda: datetime.datetime.fromtimestamp(V.DURING, V.UTC))
            return SR.delegate(ctx, chosen(*models), decided_by=EM, basis={'type': 'envelope-receipt',
                                                                           'receipt': receipt})
        finally:
            store.close()

    def hand_head(self, change, actor=ED.SELECTION_RECORDER):
        """A selection receipt written by hand at the next position: a copy of position 1's intent with its own
        decisionId, changed by CHANGE(intent), reserved by ACTOR and confirmed."""
        store = self.open_store()
        intent = json.loads(store.get(ED.selection_key(1)).intent_json)
        position = len(ED.selections(store)) + 1
        intent['sequence'] = position
        intent['decision']['decisionId'] = '0b1c2d3e-4f50-4617-8293-a4b5c6d7e8f9'
        change(intent, store)
        key = ED.selection_key(position)
        store.reserve(key, intent, actor=actor)
        store.transition(key, 'dispatched', actor=actor, reason='by hand', expected_from='reserved')
        store.transition(key, 'confirmed', actor=actor, reason='by hand', expected_from='dispatched')
        store.close()


class AtStart(SelectionCase):
    def test_c3_a_delegated_record_naming_the_receipt_and_decision_0018_starts_the_broker(self):
        raw = delegated()
        receipt = self.receipt(raw)
        selection = self.select(receipt, S.MODEL_A, S.MODEL_B)            # the record may select more
        self.assertEqual(selection['decision']['delegation']['basis']['receipt'], receipt)
        seen = {}
        code, ctx = self.serve(raw, lambda broker: seen.update(broker.status()))
        self.assertEqual(code, 0, ctx.err.getvalue())
        expected = {'by': 'delegation', 'models': {'anthropic-messages': [S.MODEL_A]}, 'record': 'decision:0018',
                    'point': '3', 'receipt': 'model-selection/v1/1',
                    'decision': selection['decision']['decisionId']}
        self.assertEqual(seen['authorization']['selection'], expected)
        self.assertEqual(seen['authorization']['receipt'], receipt)
        (start,) = self.start_receipts()
        self.assertEqual(start['authorization']['selection'], expected)
        text = json.dumps(start)
        self.assertIsNone(COMMIT_RUN.search(text))                         # no commit id (the record's revision)
        self.assertNotIn(selection['decision']['delegation']['revision'], text)

    def test_c2_a_delegated_record_that_leaves_no_configured_model_is_missing(self):
        raw = delegated(models=())
        self.select(self.receipt(raw), S.MODEL_A)
        self.assertStartRefused(raw, 'MODEL_SELECTION_MISSING')

    def test_c4_a_head_reserved_by_another_actor(self):
        raw = delegated()
        self.select(self.receipt(raw), S.MODEL_A)
        self.hand_head(lambda intent, store: None, actor='someone-else')
        self.assertStartRefused(raw, 'MODEL_SELECTION_NOT_AUTHORIZED')

    def test_c4_a_head_decided_by_the_product_manager(self):
        raw = delegated()
        self.select(self.receipt(raw), S.MODEL_A)

        def product_manager(intent, store):
            intent['decision'].update(decidedBy=PM, recordedBy=PM)
        self.hand_head(product_manager)
        self.assertStartRefused(raw, 'MODEL_SELECTION_NOT_AUTHORIZED')

    def test_c4_a_head_in_owner_decision_v1(self):
        raw = delegated()
        receipt = self.receipt(raw)
        self.select(receipt, S.MODEL_A)

        def owner_record(intent, store):
            intent['decision'] = json.loads(store.get(receipt).intent_json)['decision']   # an Owner's record
        self.hand_head(owner_record)
        self.assertStartRefused(raw, 'MODEL_SELECTION_NOT_AUTHORIZED')

    def test_c5_a_selection_under_an_earlier_envelope(self):
        first = delegated()
        self.select(self.receipt(first, 'op-envelope-0001'), S.MODEL_A)
        second = delegated(expires_at='2026-12-02T00:00:00Z')        # another envelope: a later expiry
        self.receipt(second, 'op-envelope-0002')
        self.assertStartRefused(second, 'MODEL_SELECTION_RECEIPT_MISMATCH')

    def test_c6_a_configured_model_the_record_does_not_select(self):
        self.select(self.receipt(delegated()), S.MODEL_A)
        detail = self.assertStartRefused(delegated(models=(S.MODEL_A, S.MODEL_B)), 'MODEL_NOT_SELECTED').err.getvalue()
        self.assertIn(S.MODEL_B, detail)

    def test_a_source_that_reads_no_selection_or_answers_badly(self):
        raw = delegated()
        receipt = self.receipt(raw)
        self.select(receipt, S.MODEL_A)
        real = ED.verifier(self.open_store())
        view = real.selection(receipt).view
        self.assertEqual(tuple(view), ED.SELECTION_VIEW)

        def source(selection):
            def decisions(store):
                verify = ED.verifier(store)
                if selection is None:
                    return lambda *args: verify(*args)                   # slice 1's protocol only
                holder = type('Source', (), {'__call__': lambda self, *args: verify(*args),
                                             'selection': lambda self, r: selection(r)})
                return holder()
            return decisions

        def raising(receipt):
            raise RuntimeError('synthetic selection failure')
        self.assertStartRefused(raw, 'MODEL_SELECTION_MISSING', decisions=source(None))
        for name, selection, code in (
                ('raises', raising, 'ENVELOPE_RECORD_INVALID'),
                ('a list', lambda r: [None, '', view], 'ENVELOPE_RECORD_INVALID'),
                ('an unknown code', lambda r: ED.Verdict('SOMETHING_ELSE', '', None), 'ENVELOPE_RECORD_INVALID'),
                ('another basis', lambda r: ED.Verdict(None, '', {**view, 'basis': AR.RECEIPT_PREFIX + 'ab' * 16}),
                 'ENVELOPE_RECORD_INVALID'),
                ('another point', lambda r: ED.Verdict(None, '', {**view, 'point': '3.3'}), 'ENVELOPE_RECORD_INVALID'),
                ('a wildcard', lambda r: ED.Verdict(None, '', {**view, 'models': {'anthropic-messages': ['syn-*']}}),
                 'ENVELOPE_RECORD_INVALID'),
                ('its own refusal', lambda r: ED.Verdict('MODEL_SELECTION_RECEIPT_MISMATCH', 'synthetic', None),
                 'MODEL_SELECTION_RECEIPT_MISMATCH')):
            with self.subTest(name):
                self.assertStartRefused(raw, code, decisions=source(selection))

    def test_the_repeated_codes_and_view_equal_the_read_sides(self):
        self.assertEqual(IB.SELECTION_REFUSALS, tuple(ED.SELECTION_REFUSALS))
        self.assertEqual(IB.SELECTION_VIEW, ED.SELECTION_VIEW)
        self.assertTrue(IB.SELECTION_KEY.fullmatch(ED.selection_key(12)))
        for code in IB.SELECTION_REFUSALS + ('MODEL_NOT_SELECTED',):
            self.assertIn(code, IB.CODES)


class PerRequest(SelectionCase):
    def test_c7_a_request_or_an_issuance_outside_the_held_selection(self):
        upstream = S.FakeUpstream('anthropic-messages')
        self.addCleanup(upstream.close)
        wide, narrow = delegated(models=(S.MODEL_A, S.MODEL_B)), delegated(models=(S.MODEL_A,))
        receipt = self.receipt(wide)
        self.select(receipt, S.MODEL_A, S.MODEL_B)
        held_wide = V.minted(wide, self.db)
        self.select(receipt, S.MODEL_A)                                       # a later, narrower selection
        held_narrow = V.minted(narrow, self.db)
        self.assertEqual(dict(held_narrow.models), {'anthropic-messages': (S.MODEL_A,)})
        connector = V.Connector({ORIGIN_TEXT: upstream})
        rig = V.BoundRig(wide, held_wide, connect=connector)                  # configuration wider than held
        self.addCleanup(rig.close)
        rig.start()
        token = rig.issue(family='anthropic-messages', models=(S.MODEL_A, S.MODEL_B), ttl=3600)['token']
        rig.broker.authorization = held_narrow                                # the grant is wider than held

        def send(model):
            return S.request(rig.inference, 'POST', '/v1/messages', {'model': model},
                             [S.auth('anthropic-messages', token)])
        status, _, body = send(S.MODEL_B)
        self.assertEqual((status, json.loads(body)['aieh_refusal']['code']), (403, 'MODEL_NOT_SELECTED'))
        status, refusal = S.control(rig, 'POST', '/v1/grants', {
            'conversation_id': S.new_id(), 'attempt_id': S.new_id(), 'family': 'anthropic-messages',
            'models': [S.MODEL_B], 'ttl_s': 60})
        self.assertEqual((status, refusal['aieh_refusal']['code']), (403, 'MODEL_NOT_SELECTED'))
        self.assertEqual(len(upstream.requests), 0)
        status, _, _ = send(S.MODEL_A)                                         # a selected model passes
        self.assertEqual(status, 200)
        self.assertEqual(connector.seen, [ORIGIN_TEXT])
        self.assertEqual(json.loads(upstream.requests[-1]['body'])['model'], S.MODEL_A)
        self.assertIn(('x-api-key', S.KEY), upstream.requests[-1]['headers'])
        self.assertNotIn(token, json.dumps([list(map(list, upstream.requests[-1]['headers']))]))
        codes = [line['code'] for line in rig.audit_lines() if line.get('event') == 'request']
        self.assertEqual(codes, ['MODEL_NOT_SELECTED', None])


if __name__ == '__main__':
    unittest.main()
