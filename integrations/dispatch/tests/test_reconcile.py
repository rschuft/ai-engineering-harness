"""Tests for the reconciliation of a lost create acknowledgement (plan leaf E-01.4.1), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -p test_reconcile.py -v

The proof, sentence by sentence:

* "Lost acknowledgement does not trigger immediate blind new request." A create whose answer is lost leaves the
  attempt ``unknown``; another dispatch on the same task is a live claim and calls nothing; reconciliation makes one
  ``GET /api/conversations/{reserved id}`` and no create, whatever it finds; the fake's call log shows exactly one
  create (``LostAcknowledgement``). Found, the attempt is ``confirmed`` on its reserved conversation (reattached);
  not found (404), it is ``failed`` as the store's reconcile contract says, and a further attempt is a new ordinal
  with a new conversation id; an inconclusive lookup leaves it ``unknown`` with reconciliation ``required``, and a
  later reconciliation settles it (``InconclusiveLookup``).
* "Reconcile settles only attempts in its own operation-key namespace: its oracle answers indeterminate for any other
  key, so the P-04.2 and P-04.3 recorders' receipts are never settled by it, shown with a recorder receipt present
  after a restore epoch." Receipts under the recorders' own key builders (``owner-authorization/v1/<nonce>``,
  ``dispatch-inputs/v1/promotion/<n>``, ``dispatch-inputs/v1/design/...``) and a dispatch journal, in flight when
  the store was backed up, are ``unknown`` after the restore and stay so, with no transport call for any of them,
  even through a transport that would answer every lookup "found"; the typed attempt beside them is settled
  (``NamespaceRule``).

The Agent Server is the existing fakes, unchanged: E-05.8's ``ConversationServer`` (E-01.3.1's ``FakeAgentServer``
plus each created conversation's ``GET``, and a 404 for one it never created), on the E-01.3.1 dispatch fixture. A
lost answer is the transport raising after the server handled the call. No guest, Agent Server, network or LLM.
"""
from pathlib import Path
import copy
import importlib.util
import json
import sys
import unittest
import uuid

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


te = _load('test_attempt_end', HERE / 'test_attempt_end.py')
cc, di, store_mod = te.cc, te.di, te.store_mod
RC = _load('aieh_dispatch_reconcile', HERE.parent / 'reconcile.py')
AR = _load('authorization_recorder', REPO / 'integrations' / 'owner' / 'authorization_recorder.py')   # P-04.2
ID = _load('input_decisions', REPO / 'integrations' / 'owner' / 'input_decisions.py')                 # P-04.3

ACTOR = 'e-01.4.1-test'
EPOCH_REASON = 'restore epoch: outcome uncertain after restore'


class LostAnswer:
    """The call reaches the server and the create's answer is lost on the way back (the transport raises)."""

    def __init__(self, server, error=TimeoutError):
        self.server, self.error = server, error

    def __call__(self, method, path, body):
        answer = self.server(method, path, body)
        if (method, path) == cc.CREATE:
            raise self.error('the create answer was lost')
        return answer


class Affirming:
    """A transport that answers every call 200 with the conversation id its path names, recording each call: a
    verdict it is never asked for cannot come from it."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, path, body):
        self.calls.append((method, path, copy.deepcopy(body)))
        return {'status': 200, 'body': {'id': path.rsplit('/', 1)[-1], 'execution_status': 'running'}}


class Fixture(cc.adm.AdmissionFixture):
    run_dispatch = cc.DispatchTests.run_dispatch
    only = cc.DispatchTests.only
    last_event = cc.DispatchTests.last_event

    def setUp(self):
        super().setUp()
        self.server = te.ConversationServer()

    def reconcile(self, transport=None, read_artifact=None):
        return RC.reconcile_creates(self.store, transport=self.server if transport is None else transport,
                                    actor=ACTOR, read_artifact=read_artifact or self.read_artifact)

    def lost(self, performed=True):
        """A dispatch whose create acknowledgement is lost: PERFORMED, the server created the conversation; else the
        create never reached it. Returns the unknown attempt."""
        if performed:
            transport = LostAnswer(self.server)
        else:
            self.server.create_error, transport = TimeoutError('the create never arrived'), self.server
        with self.assertRaises(TimeoutError):
            self.run_dispatch(transport)
        self.server.create_error = None
        attempt = self.only(['unknown'])
        self.assertEqual((attempt.reconciliation_status, self.last_event(attempt.operation_key).reason),
                         ('required', 'create-unanswered'))
        self.assertEqual(len(self.server.creates), 1)
        self.assertEqual(self.server.creates[0][2]['conversation_id'], attempt.conversation_id)
        self.assertEqual(sorted(self.server.conversations), [attempt.conversation_id] if performed else [])
        return attempt

    def lookup(self, conversation_id):
        return ('GET', f'/api/conversations/{conversation_id}', None)

    def assertNoNewCreate(self, attempt):
        """Exactly the one create, under the attempt's reserved id, in the fake's whole call log."""
        self.assertEqual([body['conversation_id'] for _, _, body in self.server.creates], [attempt.conversation_id])


class VerdictTable(unittest.TestCase):
    """The lookup's verdict per answer, and the namespace test, as the module's table states them."""
    category = 'unit'

    def test_each_answer_has_its_verdict(self):
        cid = str(uuid.uuid4())
        cases = {
            'found': ({'status': 200, 'body': {'id': cid, 'execution_status': 'idle'}}, RC.PERFORMED),
            'not found': ({'status': 404, 'body': {'detail': 'Conversation not found'}}, RC.NOT_PERFORMED),
            'not found, no body': ({'status': 404, 'body': None}, RC.NOT_PERFORMED),
            'another conversation': ({'status': 200, 'body': {'id': str(uuid.uuid4())}}, RC.INDETERMINATE),
            'no id': ({'status': 200, 'body': {}}, RC.INDETERMINATE),
            'the id in another form': ({'status': 200, 'body': {'id': cid.replace('-', '')}}, RC.INDETERMINATE),
            'a body that is a list': ({'status': 200, 'body': [cid]}, RC.INDETERMINATE),
            'no body': ({'status': 200, 'body': None}, RC.INDETERMINATE),
            '201': ({'status': 201, 'body': {'id': cid}}, RC.INDETERMINATE),
            '401': ({'status': 401, 'body': None}, RC.INDETERMINATE),
            '500': ({'status': 500, 'body': None}, RC.INDETERMINATE),
            '503': ({'status': 503, 'body': {'id': cid}}, RC.INDETERMINATE),
            'a status as text': ({'status': '200', 'body': {'id': cid}}, RC.INDETERMINATE),
            'a status as bool': ({'status': True, 'body': {'id': cid}}, RC.INDETERMINATE),
            'no status': ({'body': {'id': cid}}, RC.INDETERMINATE),
            'not a mapping': ('200', RC.INDETERMINATE),
            'nothing': (None, RC.INDETERMINATE),
        }
        for name, (answer, verdict) in cases.items():
            with self.subTest(name):
                self.assertEqual(RC.verdict_of(answer, cid), verdict)

    def test_the_namespace_is_the_typed_attempt_keys(self):
        self.assertEqual(store_mod.KEY_PREFIX, 'attempt/v1/')
        self.assertTrue(RC.in_namespace('attempt/v1/TASK-2/c@' + '0' * 40 + '/implement/1'))
        for key in (AR.RECEIPT_PREFIX + 'ab' * 16, ID.promotion_key(3), ID.design_key('demo-app', 'c', 1),
                    di.GRANT_JOURNAL_KEY.format(attempt_id=str(uuid.uuid4())), 'attempt/v2/x', 'attempt/', 'op-x',
                    'ATTEMPT/V1/x', ' attempt/v1/x', None, 7):
            with self.subTest(key=key):
                self.assertFalse(RC.in_namespace(key))


class LostAcknowledgement(Fixture):
    def test_a_lost_acknowledgement_sends_no_new_create(self):
        """The proof's first sentence: no blind new request, before or during reconciliation."""
        attempt = self.lost()
        key, cid = attempt.operation_key, attempt.conversation_id
        calls = list(self.server.calls)
        # Another dispatch of the same task while the outcome is unknown: a live claim, and no call at all.
        with self.assertRaises(store_mod.LiveClaim):
            self.run_dispatch(self.server)
        self.assertEqual(self.server.calls, calls)
        self.assertEqual([a.operation_key for a in self.store.attempts()], [key])
        # Reconciliation looks the reserved id up, once, and sends nothing else.
        report = self.reconcile()
        self.assertEqual(self.server.calls[len(calls):], [self.lookup(cid)])
        self.assertEqual(report['confirmed'], [key])
        self.assertNoNewCreate(attempt)

    def test_found_the_attempt_is_reattached_to_its_reserved_conversation(self):
        attempt = self.lost()
        key, cid = attempt.operation_key, attempt.conversation_id
        report = self.reconcile()
        self.assertEqual((report['confirmed'], report['failed'], report['still_unknown']), ([key], [], []))
        self.assertEqual(report['observations'], [{'operationKey': key, 'verdict': RC.PERFORMED, 'basis': RC.LOOKUP,
                                                   'conversationId': cid, 'httpStatus': 200}])
        held = self.store.get(key)
        self.assertEqual((held.state, held.reconciliation_status, held.conversation_id),
                         ('confirmed', 'reconciled', store_mod.conversation_id_for(key)))
        self.assertEqual([(e.from_state, e.to_state, e.reason) for e in self.store.events(key)],
                         [(None, 'reserved', 'reserved'), ('reserved', 'dispatched', 'create'),
                          ('dispatched', 'unknown', 'create-unanswered'),
                          ('unknown', 'confirmed', 'reconciled: observed in the external system')])
        # Reattached: the confirmed attempt's record reads as any confirmed attempt's, on the one conversation.
        resolved = di.stored_inputs(self.store, key, state='confirmed')
        self.assertEqual(resolved.attempt_identity().operation_key, key)
        self.assertEqual(sorted(self.server.conversations), [cid])
        self.assertNoNewCreate(attempt)
        # Nothing is unknown any more: a further reconciliation calls nothing.
        calls = list(self.server.calls)
        self.assertEqual(self.reconcile(), {'confirmed': [], 'failed': [], 'still_unknown': [], 'observations': []})
        self.assertEqual(self.server.calls, calls)

    def test_not_found_the_attempt_fails_and_a_further_attempt_is_a_new_ordinal(self):
        """404: not performed, so failed (IntegrationStore.reconcile); failed is terminal, so the reserved id is never
        sent again, and a further attempt (the caller's policy) is the next ordinal with its own conversation id."""
        attempt = self.lost(performed=False)
        key, cid = attempt.operation_key, attempt.conversation_id
        calls = len(self.server.calls)
        report = self.reconcile()
        self.assertEqual(self.server.calls[calls:], [self.lookup(cid)])
        self.assertEqual((report['confirmed'], report['failed'], report['still_unknown']), ([], [key], []))
        self.assertEqual(report['observations'][0]['httpStatus'], 404)
        held = self.store.get(key)
        self.assertEqual((held.state, held.reconciliation_status), ('failed', 'reconciled'))
        self.assertEqual(self.last_event(key).reason, 'reconciled: not present in the external system')
        self.assertNoNewCreate(attempt)
        with self.assertRaises(store_mod.IllegalTransition):   # terminal: never dispatched again
            self.store.transition(key, 'dispatched', actor=ACTOR)
        result = self.run_dispatch(self.server)
        self.assertEqual(self.store.attempt_identity(result.operation_key).identity.ordinal, 2)
        self.assertNotEqual(result.conversation_id, cid)
        self.assertEqual([body['conversation_id'] for _, _, body in self.server.creates], [cid, result.conversation_id])


class InconclusiveLookup(Fixture):
    def test_an_inconclusive_lookup_stays_a_separate_unknown(self):
        attempt = self.lost()
        key, cid = attempt.operation_key, attempt.conversation_id
        events = self.store.events(key)
        other = str(uuid.uuid4())
        cases = {
            'no answer': (TimeoutError('no answer'), {'basis': RC.NO_ANSWER, 'error': 'TimeoutError'}),
            'a broken connection': (ConnectionResetError(), {'basis': RC.NO_ANSWER, 'error': 'ConnectionResetError'}),
            '503': ({'status': 503, 'body': None}, {'httpStatus': 503}),
            '500': ({'status': 500, 'body': {'id': cid}}, {'httpStatus': 500}),
            '401': ({'status': 401, 'body': None}, {'httpStatus': 401}),
            'another conversation': ({'status': 200, 'body': {'id': other}}, {'httpStatus': 200}),
            'no id': ({'status': 200, 'body': {'execution_status': 'idle'}}, {'httpStatus': 200}),
            'no body': ({'status': 200, 'body': None}, {'httpStatus': 200}),
            'not an HTTP answer': ('garbage', {'httpStatus': None}),
            'a status as text': ({'status': '404', 'body': None}, {'httpStatus': None}),
        }
        for name, (failure, observed) in cases.items():
            with self.subTest(name):
                self.server.fail[('GET', 'info')] = failure
                calls = len(self.server.calls)
                report = self.reconcile()
                self.assertEqual(self.server.calls[calls:], [self.lookup(cid)])
                self.assertEqual((report['confirmed'], report['failed'], report['still_unknown']), ([], [], [key]))
                (observation,) = report['observations']
                self.assertEqual(observation['verdict'], RC.INDETERMINATE)
                self.assertLessEqual(observed.items(), observation.items())
                held = self.store.get(key)
                self.assertEqual((held.state, held.reconciliation_status), ('unknown', 'required'))
                self.assertEqual(self.store.events(key), events)   # nothing recorded: a separate unknown
                with self.assertRaises(store_mod.LiveClaim):
                    self.run_dispatch(self.server)
                self.assertEqual(len(self.server.calls), calls + 1)
                self.assertNoNewCreate(attempt)
        # The server answers again: a later reconciliation settles it, still with no new create.
        self.server.fail.clear()
        self.assertEqual(self.reconcile()['confirmed'], [key])
        self.assertNoNewCreate(attempt)

    def test_no_lookup_without_the_pinned_allowlist(self):
        attempt = self.lost()
        calls = list(self.server.calls)
        drifted = {'path': None}

        def read_artifact(path):
            raw = self.read_artifact(path)
            if path.endswith('/routes.json'):
                drifted['path'] = path
                return raw + b' '
            return raw
        report = self.reconcile(read_artifact=read_artifact)
        self.assertIsNotNone(drifted['path'])
        self.assertEqual(report['still_unknown'], [attempt.operation_key])
        self.assertEqual(report['observations'], [{'operationKey': attempt.operation_key, 'verdict': RC.INDETERMINATE,
                                                   'basis': RC.CLIENT_UNAVAILABLE,
                                                   'code': 'PROFILE_ARTIFACT_DRIFTED'}])
        self.assertEqual(self.server.calls, calls)

    def test_no_lookup_for_a_typed_attempt_that_is_not_a_dispatch_record(self):
        identity = self.resolve().attempt_identity()
        key = identity.operation_key
        self.store.reserve_attempt(identity, {'kind': 'not a dispatch record'}, actor=ACTOR)
        self.store.transition(key, 'dispatched', actor=ACTOR)
        self.store.transition(key, 'unknown', actor=ACTOR)
        report = self.reconcile()
        self.assertEqual(report['still_unknown'], [key])
        self.assertEqual(report['observations'], [{'operationKey': key, 'verdict': RC.INDETERMINATE,
                                                   'basis': RC.RECORD_UNREADABLE, 'code': 'RESERVATION_INVALID'}])
        self.assertEqual(self.server.calls, [])

    def test_stored_inputs_reads_an_unknown_attempt_only(self):
        attempt = self.lost()
        resolved = di.stored_inputs(self.store, attempt.operation_key, state='unknown')
        self.assertEqual(resolved.attempt_identity().operation_key, attempt.operation_key)
        self.reconcile()
        with self.assertRaises(di.DispatchRefused) as caught:
            di.stored_inputs(self.store, attempt.operation_key, state='unknown')
        self.assertEqual((caught.exception.code, caught.exception.context['state']), ('ATTEMPT_NOT_UNKNOWN',
                                                                                      'confirmed'))
        self.assertIn('ATTEMPT_NOT_UNKNOWN', di.REFUSALS)


class NamespaceRule(Fixture):
    def receipt(self, key, actor, *states):
        self.store.reserve(key, {'format': 'e-01.4.1-fixture', 'key': key}, actor=actor)
        for state in states:
            self.store.transition(key, state, actor=actor, reason=f'the recorder\'s act: {state}')
        return key

    def restore(self):
        """Back the store up, restore it over itself: an open restore epoch."""
        path = self.store.path
        manifest = self.store.backup(actor='owner')
        self.store.close()
        store_mod.restore_store(path, Path(path).parent / 'backups' / (manifest['backup_file'] + '.manifest.json'),
                                actor='owner')
        self.store = store_mod.open_store(path)
        self.addCleanup(self.store.close)
        self.assertEqual(len(self.store.open_epochs()), 1)

    def test_recorder_receipts_after_a_restore_epoch_are_never_settled(self):
        """The proof's second sentence."""
        # A typed attempt whose dispatcher died after the create was sent: dispatched, its answer never recorded.
        with self.assertRaises(te.Crash):
            self.run_dispatch(LostAnswer(self.server, error=te.Crash))
        attempt = self.only(['dispatched'])
        # The recorders' receipts in flight, under their own key builders and actors.
        authorization = self.receipt(AR.RECEIPT_PREFIX + 'ab' * 16, AR.RECORDER, 'dispatched')        # P-04.2
        promotion = self.receipt(ID.promotion_key(3), ID.RECORDER, 'dispatched', 'unknown')            # P-04.3
        design = self.receipt(ID.design_key('demo-app', 'change-x', 1), ID.RECORDER, 'dispatched')    # P-04.3
        journal = self.receipt(di.GRANT_JOURNAL_KEY.format(attempt_id=str(uuid.uuid4())), 'dispatch-test',
                               'dispatched')                                                         # any other key
        receipts = [authorization, promotion, design, journal]
        self.restore()
        before = {key: self.store.events(key) for key in receipts}
        transport = Affirming()
        report = self.reconcile(transport)
        # The typed attempt is settled; every other key stays unknown, and the transport saw no call for it.
        self.assertEqual(report['confirmed'], [attempt.operation_key])
        self.assertEqual((report['failed'], sorted(report['still_unknown'])), ([], sorted(receipts)))
        self.assertEqual(transport.calls, [self.lookup(attempt.conversation_id)])
        for key in receipts:
            with self.subTest(key=key):
                held = self.store.get(key)
                self.assertEqual((held.state, held.reconciliation_status), ('unknown', 'required'))
                moved = [(e.from_state, e.to_state, e.reason) for e in self.store.events(key)[len(before[key]):]]
                self.assertEqual(moved, [] if key == promotion else [('dispatched', 'unknown', EPOCH_REASON)])
                self.assertFalse({e.to_state for e in self.store.events(key)} & {'confirmed', 'failed'})
                self.assertIn({'operationKey': key, 'verdict': RC.INDETERMINATE, 'basis': RC.NOT_IN_NAMESPACE},
                              report['observations'])
        # The receipts hold the epoch open until their own recorders settle them.
        with self.assertRaises(store_mod.EpochNotReconciled):
            self.store.close_restore_epoch(actor='owner')
        # Asked again, the oracle still answers indeterminate for each, with no call.
        oracle = RC.create_oracle(self.store, transport=transport, read_artifact=self.read_artifact)
        self.assertEqual({key: oracle(self.store.get(key)) for key in receipts},
                         dict.fromkeys(receipts, RC.INDETERMINATE))
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(json.loads(self.store.get(authorization).intent_json)['key'], authorization)
        # Negative control: the receipts were settleable, so their staying unknown is the oracle's doing. An oracle
        # that answered for every key would have settled them (and closed the epoch).
        self.assertEqual(sorted(self.store.reconcile(lambda reservation: 'performed', actor=ACTOR)['confirmed']),
                         sorted(receipts))
        self.assertEqual(len(self.store.close_restore_epoch(actor='owner')), 1)


if __name__ == '__main__':
    unittest.main()
