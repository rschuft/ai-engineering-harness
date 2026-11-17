"""The served fixture's scenarios, shown through the production paths over the listener (plan leaf E-01.7; the
engineering manager's ruling 6 of E-01.7's review): the dispatcher's own dispatch, E-01.4.1's reconcile, E-01.4.2's
recover and the attempt run, unmodified, through the fixture transport to a real 127.0.0.1 listener serving the core,
in the scenario under test. A withheld answer ends at the transport's injected ceiling (``CEILING_S``), never at a
sleep.

The base fixture is the restart matrix's (``integrations/dispatch/tests/test_restart_matrix.py`` ``Matrix``: a native
D1 attempt on a throwaway store), with its wire replaced by the fixture transport. A create goes through the
listener's validation, which needs the locked release openapi.json (never committed: decision 0005): these tests run
when ``AIEH_LOCKED_OPENAPI`` names it and are skipped otherwise, saying so.
"""
import unittest

import fixture_support as S

CATEGORY = 'integration'

TRM = S.load('test_restart_matrix', S.DISPATCH_TESTS / 'test_restart_matrix.py')
SERVER, TRANSPORT = S.SERVER, S.TRANSPORT
RR, AR, store_mod, di = TRM.RR, TRM.AR, TRM.store_mod, TRM.di
RC = RR.RC
OPENAPI = S.locked_openapi_path()
LOCKED = None if OPENAPI is None else SERVER.locked_document(OPENAPI)
CEILING_S = 3            # the transport's ceiling on one request: a withheld answer ends there


def setUpModule():
    TRM.setUpModule()


def tearDownModule():
    TRM.tearDownModule()


@unittest.skipIf(LOCKED is None, 'AIEH_LOCKED_OPENAPI is not given: a create through the listener needs the locked '
                                 'openapi.json, never committed (decision 0005)')
class OverTheListener(TRM.Matrix):
    scenario = 'finished'

    def setUp(self):
        super().setUp()
        self.listener = SERVER.Fixture(self.scenario, core=self.core, openapi=LOCKED)
        self.served = S.InThread(self.listener).start()
        self.addCleanup(self.served.stop)
        self.wire = self.served.transport(timeout=CEILING_S)
        self.fixture.server = self.wire

    def recover(self):
        before = len(self.wire.calls)
        report = RR.recover(self.store, transport=self.wire, actor=TRM.ACTOR, read_artifact=self.fixture.read_artifact)
        calls = [(c['method'], c['path']) for c in self.wire.calls[before:]]
        self.assertEqual([m for m, _ in calls if m != 'GET'], [], 'recover made GETs only')
        return report, calls

    def reconcile(self):
        return RC.reconcile_creates(self.store, transport=self.wire, actor=TRM.ACTOR,
                                    read_artifact=self.fixture.read_artifact)

    def events(self):
        return [entry['event'] for entry in self.listener.log]


class Unknown(OverTheListener):
    scenario = 'unknown'

    def test_the_attempt_stays_unknown_through_reconcile_and_recover(self):
        with self.assertRaises(TRANSPORT.FixtureTransportError):
            self.dispatch()
        attempt = self.only('unknown')
        self.assertEqual(self.store.events(attempt.operation_key)[-1].reason, 'create-unanswered')
        self.assertEqual(len(self.core.creates), 1, 'the create reached the core')
        report = self.reconcile()                                  # E-01.4.1: the lookup is withheld too
        self.assertIn(attempt.operation_key, report['still_unknown'])
        self.assertEqual((report['confirmed'], report['failed']), ([], []))
        self.only('unknown')
        report, calls = self.recover()                             # E-01.4.2: it asks once more and holds it
        self.assertEqual(calls, [self.lookup(attempt.conversation_id)])
        self.assertEqual([(h['operationKey'], h['code'], h['basis']) for h in report['held']],
                         [(attempt.operation_key, 'OUTCOME_UNKNOWN', 'no-answer')])
        self.assertEqual([e['verdict'] for e in report['entries']], ['indeterminate'])
        self.only('unknown')
        self.assertEqual(len(self.core.creates), 1, 'no second create')
        self.assertEqual(self.events().count('response withheld (the lookup reached the core)'), 2)


class LostAcknowledgement(OverTheListener):
    scenario = 'lost-create-acknowledgement'

    def test_the_lost_acknowledgement_is_settled_confirmed_on_its_reserved_conversation(self):
        with self.assertRaises(TRANSPORT.FixtureTransportError):
            self.dispatch()
        attempt = self.only('unknown')
        report = self.reconcile()                                  # E-01.4.1: the lookup is answered
        self.assertEqual(report['confirmed'], [attempt.operation_key])
        self.assertEqual(self.moves(attempt.operation_key, -1), [('unknown', 'confirmed', TRM.FOUND_REASON)])
        self.assertEqual(len(self.core.creates), 1, 'no second create')
        self.assertIn('response withheld (the create reached the core)', self.events())


class Pending(OverTheListener):
    scenario = 'pending'

    def test_the_message_never_arrives_and_the_attempt_is_held_on_its_idle_conversation(self):
        result = self.dispatch()
        key, cid = result.operation_key, result.conversation_id
        refusal = self.refused('TURN_UNRECONCILED', lambda: self.run_attempt(key))
        self.assertIn('nothing is sent again', refusal.detail)
        turn = self.turn(key)
        self.assertEqual((turn.state, self.store.events(turn.operation_key)[-1].reason), ('unknown', 'no-answer'))
        self.assertEqual(self.core.messages(), [], 'the message never reached the core')
        self.assertEqual(self.core.conversations[cid]['execution_status'], 'idle')
        self.assertIn('request never reaches the core (the message)', self.events())
        report, calls = self.recover()
        self.assertEqual(self.turn(key).state, 'unknown', 'held: never settled as sent')
        self.assertEqual(self.store.get(key).state, 'confirmed')
        self.assertEqual(self.core.messages(), [], 'nothing was sent again')


if __name__ == '__main__':
    unittest.main()
