"""The provider-envelope read side (plan leaf S-03.5, slice 1; ``envelope_decisions.py``), in the test process
only.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

The receipts are made by the REAL authorization recorder against the fake Gitea, called in memory (no socket),
with the fake protection verifier, into a throwaway integration store (authz_support.Fixture); hand-written
receipts appear only where a test says so. The manifests here declare kind ``provider-envelope`` and a target
that stands in for an envelope's digest: the read side compares digests and never parses the envelope. Every
statement is synthetic.
"""
import ast
import datetime
import hashlib
import json
import sys
import unittest
from pathlib import Path

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import authz_support as su  # noqa: E402

AR, D, fg = su.AR, su.D, su.fg
ED = su._load('envelope_decisions', su.OWNER_DIR / 'envelope_decisions.py')

UTC = datetime.timezone.utc
TARGET_1, TARGET_2, TARGET_3 = ('sha256:' + c * 64 for c in '123')
BEFORE = datetime.datetime(2026, 11, 11, 11, 59, 59, tzinfo=UTC)   # su.EXPIRES less one second
AT_EXPIRY = datetime.datetime(2026, 11, 11, 12, 0, 0, tzinfo=UTC)


def setUpModule():
    su.start()


def tearDownModule():
    su.stop()


def envelope_manifest(operation, target, **changes):
    data = {'operation': operation, 'kind': ED.OPERATION_KIND, 'target': target, 'expiresAt': su.EXPIRES,
            'envelope': {'format': 'aieh-provider-envelope/1', 'stand-in': True}, **changes}
    return (json.dumps(data, indent=2) + '\n').encode('utf-8')


class ReadSide(su.Fixture):
    def gitea_for_test(self):
        gitea = fg.FakeGitea()
        return gitea, 3000, gitea

    def setUp(self):
        super().setUp()
        self.blobs = {}

    def authorize(self, operation, target=TARGET_1, *, blob=None, on_merge=None):
        """The real recorder on a provider-envelope manifest: (the record's result or RecorderError, nonce)."""
        blob = blob or envelope_manifest(operation, target)
        self.blobs[operation] = blob
        number = self.propose(operation, files={f'operations/{operation}.json': blob}, branch=f'work/{operation}')
        nonce = self.prepare(number)['shown']['nonce']
        self.gitea.on_merge = on_merge
        try:
            return self.record(nonce, su.statement(operation)), nonce
        except AR.RecorderError as exc:
            return exc, nonce
        finally:
            self.gitea.on_merge = None

    def manifest_digest(self, operation):
        return 'sha256:' + hashlib.sha256(self.blobs[operation]).hexdigest()

    def verify(self, target=TARGET_1, now=BEFORE):
        return ED.verify_envelope(self.store, target, self.manifest_digest, now)

    def assertVerdict(self, code, target=TARGET_1, now=BEFORE):
        verdict = self.verify(target, now)
        self.assertEqual(verdict.code, code, verdict.detail)
        self.assertIn(code, ED.REFUSALS)
        self.assertIsNone(verdict.view)
        return verdict

    def hand_written(self, source_nonce, *, actor=ED.RECORDER, state='confirmed', change=None, nonce='ab' * 16,
                     decision_id='0b1c2d3e-4f50-4617-8293-a4b5c6d7e8f9'):
        """A receipt written by hand under the recorder's prefix: a copy of SOURCE_NONCE's intent with its own
        nonce and decisionId, changed by CHANGE(intent), reserved by ACTOR and moved to STATE."""
        intent = json.loads(self.store.get(AR.RECEIPT_PREFIX + source_nonce).intent_json)
        intent['decision']['shown']['nonce'] = nonce
        intent['decision']['decisionId'] = decision_id
        if change is not None:
            change(intent)
        key = AR.RECEIPT_PREFIX + nonce
        self.store.reserve(key, intent, actor=actor)
        if state in ('dispatched', 'confirmed', 'unknown'):
            self.store.transition(key, 'dispatched', actor=actor, reason='by hand', expected_from='reserved')
        if state in ('confirmed', 'unknown'):
            self.store.transition(key, state, actor=actor, reason='by hand', expected_from='dispatched')
        return key


class Constants(unittest.TestCase):
    def test_the_repeated_constants_equal_the_recorders(self):
        self.assertEqual((ED.KIND, ED.RECORDER, ED.RECEIPT_FORMAT, ED.RECEIPT_PREFIX),
                         (AR.KIND, AR.RECORDER, AR.RECEIPT_FORMAT, AR.RECEIPT_PREFIX))
        self.assertEqual(list(ED.REFUSALS), ['ENVELOPE_RECORD_INVALID', 'ENVELOPE_NOT_AUTHORIZED',
                                             'ENVELOPE_AUTHORIZATION_UNRESOLVED', 'ENVELOPE_REPLAYED',
                                             'ENVELOPE_MISMATCH', 'ENVELOPE_EXPIRED'])

    def test_the_read_side_loads_no_gitea_credential_or_store_module(self):
        tree = ast.parse((su.OWNER_DIR / 'envelope_decisions.py').read_text(encoding='utf-8'))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imported, {'datetime', 'importlib.util', 'json', 'sys', 'pathlib', 'typing'})
        loaded = [node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and getattr(node.func, 'id', None) == '_load']
        self.assertEqual(loaded, ['owner_decision', 'delegated_decision'])


class Governing(ReadSide):
    def test_a_confirmed_authorization_governs(self):
        result, nonce = self.authorize('op-env-1')
        self.assertEqual(result['receipt']['state'], 'confirmed')
        verdict = self.verify()
        self.assertIsNone(verdict.code, verdict.detail)
        self.assertEqual(verdict.view, {'receipt': AR.RECEIPT_PREFIX + nonce, 'operation': 'op-env-1',
                                        'decisionId': result['decision']['decisionId'], 'target': TARGET_1,
                                        'digest': self.manifest_digest('op-env-1'), 'expiresAt': su.EXPIRES})
        self.assertEqual(tuple(verdict.view), ED.VIEW_FIELDS)
        self.assertEqual(ED.verifier(self.store)(TARGET_1, self.manifest_digest, BEFORE), verdict)

    def test_the_stored_decision_regains_its_field_order(self):
        self.authorize('op-env-1')
        (reservation,) = [r for r in self.store.attempts() if r.operation_key.startswith(AR.RECEIPT_PREFIX)]
        stored = json.loads(reservation.intent_json)['decision']
        self.assertNotEqual(D.check_record(stored), [])            # sorted keys: the order check fails
        self.assertEqual(D.check_record(ED.stored_decision(stored)), [])

    def test_the_expiry_is_reached_at_its_second(self):
        self.authorize('op-env-1')
        self.assertIsNone(self.verify(now=BEFORE).code)
        self.assertVerdict('ENVELOPE_EXPIRED', now=AT_EXPIRY)
        self.assertVerdict('ENVELOPE_EXPIRED', now=AT_EXPIRY + datetime.timedelta(days=1))

    def test_a_later_authorization_supersedes_and_an_earlier_one_is_a_replay(self):
        self.authorize('op-env-1', TARGET_1)
        self.authorize('op-env-2', TARGET_2)
        self.assertIsNone(self.verify(TARGET_2).code)
        self.assertVerdict('ENVELOPE_REPLAYED', TARGET_1)
        self.assertVerdict('ENVELOPE_MISMATCH', TARGET_3)

    def test_a_manifest_that_is_not_the_canonical_one_is_a_mismatch(self):
        self.authorize('op-env-1')
        canonical = self.blobs['op-env-1']
        self.blobs['op-env-1'] = canonical.replace(b'\n', b'\r\n')     # what the broker would regenerate
        self.assertVerdict('ENVELOPE_MISMATCH')

    def test_other_operation_kinds_are_not_candidates(self):
        self.propose('op-0001')
        nonce = self.prepare(1)['shown']['nonce']
        self.assertEqual(self.record(nonce)['receipt']['state'], 'confirmed')   # kind example-effect
        self.assertVerdict('ENVELOPE_NOT_AUTHORIZED')


class Settlement(ReadSide):
    def test_an_empty_store_or_a_failed_receipt_only_is_not_authorized(self):
        self.assertVerdict('ENVELOPE_NOT_AUTHORIZED')
        result, _nonce = self.authorize('op-env-1', on_merge='move-head')
        self.assertEqual(result.code, 'HEAD_STALE')
        self.assertVerdict('ENVELOPE_NOT_AUTHORIZED')

    def test_an_unsettled_receipt_alone_or_after_the_confirmed_one_is_unresolved(self):
        result, _nonce = self.authorize('op-env-1', on_merge='drop')
        self.assertEqual(result.code, 'OUTCOME_UNKNOWN')
        self.assertIn('resolve', self.assertVerdict('ENVELOPE_AUTHORIZATION_UNRESOLVED').detail)

    def test_an_unknown_receipt_after_the_confirmed_one_is_unresolved(self):
        self.authorize('op-env-1', TARGET_1)
        result, _nonce = self.authorize('op-env-2', TARGET_2, on_merge='drop')
        self.assertEqual(result.code, 'OUTCOME_UNKNOWN')
        self.assertVerdict('ENVELOPE_AUTHORIZATION_UNRESOLVED', TARGET_1)
        self.assertVerdict('ENVELOPE_AUTHORIZATION_UNRESOLVED', TARGET_2)

    def test_a_receipt_left_reserved_after_the_confirmed_one_is_unresolved(self):
        _result, nonce = self.authorize('op-env-1')
        self.hand_written(nonce, state='reserved')
        self.assertVerdict('ENVELOPE_AUTHORIZATION_UNRESOLVED')

    def test_a_failed_receipt_after_the_confirmed_one_changes_nothing(self):
        self.authorize('op-env-1', TARGET_1)
        result, _nonce = self.authorize('op-env-2', TARGET_2, on_merge='move-head')
        self.assertEqual(result.code, 'HEAD_STALE')
        self.assertIsNone(self.verify(TARGET_1).code)


class NotTheRecorders(ReadSide):
    """Hand-written receipts under the recorder's prefix: refused, whatever else the store holds."""

    def test_a_receipt_whose_kind_cannot_be_read(self):
        self.authorize('op-env-1')
        self.store.reserve(AR.RECEIPT_PREFIX + 'cd' * 16, {'format': AR.RECEIPT_FORMAT, 'decision': None},
                           actor=ED.RECORDER)
        self.assertVerdict('ENVELOPE_RECORD_INVALID')

    def test_a_receipt_reserved_by_another_actor(self):
        _result, nonce = self.authorize('op-env-1')
        self.hand_written(nonce, actor='someone-else')
        self.assertIn('someone-else', self.assertVerdict('ENVELOPE_RECORD_INVALID').detail)

    def test_a_statement_attributed_to_an_agent(self):
        _result, nonce = self.authorize('op-env-1')

        def agent(intent):
            intent['decision']['statement']['attributedTo'] = 'agent:fixture-model'
        self.hand_written(nonce, change=agent)
        self.assertIn('well-formed', self.assertVerdict('ENVELOPE_RECORD_INVALID').detail)

    def assertRefusedByHand(self, **kw):
        _result, nonce = self.authorize('op-env-1')
        self.assertIsNone(self.verify().code)
        self.hand_written(nonce, **kw)
        self.assertVerdict('ENVELOPE_RECORD_INVALID')

    def test_another_receipt_format(self):
        self.assertRefusedByHand(change=lambda i: i.update(format='aieh-something-else/1'))

    def test_a_decision_that_does_not_bind_its_key_or_operation(self):
        self.assertRefusedByHand(change=lambda i: i['decision']['shown'].update(nonce='ef' * 16))

    def test_a_decision_that_does_not_bind_its_operation(self):
        self.assertRefusedByHand(change=lambda i: i.update(operation='op-other'))

    def test_a_repeated_decision_id(self):
        _result, nonce = self.authorize('op-env-1')
        decision_id = json.loads(self.store.get(AR.RECEIPT_PREFIX + nonce).intent_json)['decision']['decisionId']
        self.hand_written(nonce, decision_id=decision_id)
        self.assertIn('repeats', self.assertVerdict('ENVELOPE_RECORD_INVALID').detail)

    def test_the_arguments_are_checked(self):
        for args in (('sha256:short', self.manifest_digest, BEFORE), (TARGET_1, None, BEFORE),
                     (TARGET_1, self.manifest_digest, BEFORE.replace(tzinfo=None))):
            with self.subTest(args=args[0]), self.assertRaises(ValueError):
                ED.verify_envelope(self.store, *args)


if __name__ == '__main__':
    unittest.main()
