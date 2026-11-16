"""Tests for the result step's receipts left ``dispatched`` (defect 3 of the restart-recovery design, 2026-11-16,
``unrelated-but-detected``), offline.

Run from the repository root, under the tools interpreter (Dulwich and a real shell are required):

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_result_receipts.py -v

``attempt_run._receipt`` marks a delivery, pull or intake receipt ``dispatched`` and ``confirmed`` in two
transactions. A step interrupted between them left the receipt ``dispatched``, and nothing completed it: an intake
then read as no intake (``recorded_result``: RESULT_STAGED_UNVERIFIED although the intake was taken), and the resumed
step was refused (RESULT_RECEIPT_CONFLICT: the resumed intake's record differs) or could not pull again
(RESULT_NOT_VERIFIED). Reproduced here first, on the attempt run's fakes (``RunServer``, the real SEED and RESULT
commands and the retained verifier), and fixed forward: ``resume_result`` settles a ``dispatched`` pull or intake
receipt by reading what it records (``_settled_receipt``: the staged bundle and the verify repository against its
digests) and resumes from it, as decision 0024 point 6.4 resumes from the receipts; one that no longer checks is left
as it is. A delivery receipt left ``dispatched`` was read as none, which skipped the delivered digest's cross-check
(the review of dispatch 10, N1): it is now settled the same way, against the verified pull's staged bundle, and
where it cannot be re-checked the resume is refused RESULT_DELIVERY_UNSETTLED (``DeliveryReceipt``).
"""
from pathlib import Path
import contextlib
import importlib.util
import sys
import unittest
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


tar = _load('test_attempt_run', HERE / 'test_attempt_run.py')
te, di, AE, store_mod, AR = tar.te, tar.di, tar.AE, tar.store_mod, tar.AR


def setUpModule():
    tar.setUpModule()


def tearDownModule():
    with contextlib.suppress(FileNotFoundError):
        tar.tearDownModule()


class InterruptedReceipt(unittest.TestCase):
    category = 'integration'

    def interrupted(self, which):
        """A run whose dispatcher dies between WHICH receipt's dispatched and confirmed transitions."""
        case = tar.Run('test_the_whole_run_makes_exactly_the_declared_calls')
        case.setUp()
        self.addCleanup(case.doCleanups)
        puller = case.real()
        attempt_id = store_mod.attempt_id_for(case.key)
        key = {'intake': AR.INTAKE_KEY, 'pull': AR.PULL_KEY, 'delivery': AR.DELIVERY_KEY}[which].format(
            attempt_id=attempt_id)
        real = di._mark

        def dying(integration_store, k, from_state, to_state, *args):
            if k == key and to_state == 'confirmed':
                raise te.Crash(f'dies with the {which} receipt dispatched')
            return real(integration_store, k, from_state, to_state, *args)
        with mock.patch.object(di, '_mark', dying), self.assertRaises(te.Crash):
            case.run_attempt(pull=puller)
        self.assertEqual(case.store.get(key).state, 'dispatched')
        self.assertIsNone(case.store.get(AE.RESULT_KEY.format(attempt_id=attempt_id)))
        return case, puller, key

    def test_an_intake_left_dispatched_is_settled_by_a_read_and_the_steps_after_it_resume(self):
        case, puller, key = self.interrupted('intake')
        # the defect: the intake taken reads as no intake
        with self.assertRaises(di.DispatchRefused) as caught:
            AR.recorded_result(case.store, case.key, base=case.base)
        self.assertEqual(caught.exception.code, 'RESULT_STAGED_UNVERIFIED')
        commands = case.server.log.count(('POST', 'bash/execute_bash_command'))
        outcome = case.resume(pull=puller, exists=lambda name: True)
        self.assertEqual(outcome.outcome, 'verified')
        self.assertEqual([(e.from_state, e.to_state, e.reason) for e in case.store.events(key)][-1],
                         ('dispatched', 'confirmed', 'settled-by-read'))
        self.assertEqual(len(puller.names), 1, 'never pulled again')
        self.assertEqual(case.server.log.count(('POST', 'bash/execute_bash_command')), commands, 'no RESULT again')
        self.assertEqual(AR.recorded_result(case.store, case.key, base=case.base).commit, outcome.result.commit)
        self.assertEqual(len(case.reserved), 1)

    def test_a_pull_left_dispatched_is_settled_by_a_read_and_reused(self):
        case, puller, key = self.interrupted('pull')
        outcome = case.resume(pull=puller, exists=lambda name: True)
        self.assertEqual(outcome.outcome, 'verified')
        self.assertEqual(case.store.events(key)[-1].reason, 'settled-by-read')
        self.assertEqual(len(puller.names), 1, 'the verified pull is reused, never pulled again')
        intake = AR.INTAKE_KEY.format(attempt_id=store_mod.attempt_id_for(case.key))
        self.assertEqual(case.store.get(intake).state, 'confirmed')

    def test_a_receipt_that_no_longer_checks_is_left_dispatched(self):
        case, puller, key = self.interrupted('intake')
        pull = AR._receipt_of(case.store, AR.PULL_KEY.format(attempt_id=store_mod.attempt_id_for(case.key)),
                              AR.PULL_FORMAT)
        staged = Path(pull['staged'])
        staged.write_bytes(staged.read_bytes() + b'changed')
        events = case.store.events(key)
        with self.assertRaises(di.DispatchRefused):
            case.resume(pull=puller, exists=lambda name: True)
        self.assertEqual((case.store.get(key).state, case.store.events(key)), ('dispatched', events))


class DeliveryReceipt(unittest.TestCase):
    """The review of dispatch 10, N1: a delivery receipt left ``dispatched`` read as none, so the delivered digest's
    cross-check (``_staged_again``) was silently skipped and the resume verified (the review's R1). Now it is settled
    by reading what it records against the verified pull's staged bundle (reason ``settled-by-read``) under the same
    re-checks as a pull or an intake; where there is nothing to read it against, or the read does not match, it is
    held: the resume is refused RESULT_DELIVERY_UNSETTLED, never verified."""
    category = 'integration'

    def left_dispatched(self, *, delivered=None):
        """A run whose delivery receipt's confirmed transition was lost while the step went on (the state an earlier
        resume left in the review's R1: the delivery dispatched beside a confirmed pull), then dies with the intake
        dispatched. DELIVERED, when given, is the digest the delivery receipt records instead of the printed one."""
        case = tar.Run('test_the_whole_run_makes_exactly_the_declared_calls')
        case.setUp()
        self.addCleanup(case.doCleanups)
        puller = case.real()
        attempt_id = store_mod.attempt_id_for(case.key)
        delivery, intake = AR.DELIVERY_KEY.format(attempt_id=attempt_id), AR.INTAKE_KEY.format(attempt_id=attempt_id)
        real_mark, real_receipt = di._mark, AR._receipt

        def mark(integration_store, k, from_state, to_state, *args):
            if k == delivery and to_state == 'confirmed':
                return None                          # its confirmed transition lost
            if k == intake and to_state == 'confirmed':
                raise te.Crash('dies with the intake receipt dispatched')
            return real_mark(integration_store, k, from_state, to_state, *args)

        def receipt(integration_store, k, intent, actor):
            if k == delivery and delivered is not None:
                intent = dict(intent, bundle=delivered)
            return real_receipt(integration_store, k, intent, actor)
        with mock.patch.object(di, '_mark', mark), mock.patch.object(AR, '_receipt', receipt), \
                self.assertRaises(te.Crash):
            case.run_attempt(pull=puller)
        pull = AR.PULL_KEY.format(attempt_id=attempt_id)
        self.assertEqual([case.store.get(k).state for k in (delivery, pull, intake)],
                         ['dispatched', 'confirmed', 'dispatched'])
        return case, puller, delivery, intake

    def test_a_delivery_left_dispatched_is_settled_by_a_read_against_the_verified_pull(self):
        case, puller, delivery, intake = self.left_dispatched()
        commands = case.server.log.count(('POST', 'bash/execute_bash_command'))
        outcome = case.resume(pull=puller, exists=lambda name: True)
        self.assertEqual(outcome.outcome, 'verified')
        self.assertEqual([(e.from_state, e.to_state, e.reason) for e in case.store.events(delivery)][-1],
                         ('dispatched', 'confirmed', 'settled-by-read'))
        self.assertEqual(case.store.events(intake)[-1].reason, 'settled-by-read')
        self.assertEqual(len(puller.names), 1, 'never pulled again')
        self.assertEqual(case.server.log.count(('POST', 'bash/execute_bash_command')), commands, 'no RESULT again')

    def test_the_delivered_digest_is_cross_checked_when_the_delivery_is_settled(self):
        """The cross-check runs: a delivery receipt recording another digest than the verified pull's is not settled
        and holds the resume (with the receipt read as none, as before, the resume verified)."""
        case, puller, delivery, intake = self.left_dispatched(delivered={'sha256': '0' * 64, 'size': 1})
        events = {k: case.store.events(k) for k in (delivery, intake)}
        with self.assertRaises(di.DispatchRefused) as caught:
            case.resume(pull=puller, exists=lambda name: True)
        self.assertEqual(caught.exception.code, 'RESULT_DELIVERY_UNSETTLED')
        self.assertEqual({k: case.store.events(k) for k in events}, events)
        self.assertEqual((len(puller.names), case.reserved), (1, []))

    def test_a_delivery_left_dispatched_with_nothing_to_read_it_against_is_held(self):
        """The dispatcher dies between the delivery receipt's dispatched and confirmed transitions, before any pull:
        nothing records what was delivered but the receipt itself, so it cannot be re-checked. The resume is refused
        before any pull or command; the review's R1 resumed to verified here."""
        case, puller, key = InterruptedReceipt.interrupted(self, 'delivery')
        events = case.store.events(key)
        commands = case.server.log.count(('POST', 'bash/execute_bash_command'))
        with self.assertRaises(di.DispatchRefused) as caught:
            case.resume(pull=puller, exists=lambda name: True)
        self.assertEqual(caught.exception.code, 'RESULT_DELIVERY_UNSETTLED')
        self.assertEqual((case.store.get(key).state, case.store.events(key)), ('dispatched', events))
        self.assertEqual((puller.names, case.reserved), ([], []))
        self.assertEqual(case.server.log.count(('POST', 'bash/execute_bash_command')), commands, 'no RESULT again')

    def died_at_the_pull(self, *, delivered=None):
        """A run whose delivery receipt is confirmed (recording DELIVERED instead of the printed digest when given)
        and whose dispatcher dies in the pull, before any pull receipt: the resumed step pulls afresh."""
        case = tar.Run('test_the_whole_run_makes_exactly_the_declared_calls')
        case.setUp()
        self.addCleanup(case.doCleanups)
        puller = case.real()
        attempt_id = store_mod.attempt_id_for(case.key)
        delivery = AR.DELIVERY_KEY.format(attempt_id=attempt_id)
        real_receipt = AR._receipt

        def receipt(integration_store, k, intent, actor):
            if k == delivery and delivered is not None:
                intent = dict(intent, bundle=delivered)
            return real_receipt(integration_store, k, intent, actor)

        def dying(name):
            raise te.Crash('dies in the pull')
        with mock.patch.object(AR, '_receipt', receipt), self.assertRaises(te.Crash):
            case.run_attempt(pull=dying)
        self.assertEqual(case.store.get(delivery).state, 'confirmed')
        self.assertIsNone(case.store.get(AR.PULL_KEY.format(attempt_id=attempt_id)))
        return case, puller

    def test_a_fresh_pull_on_resume_is_cross_checked_against_the_confirmed_delivery(self):
        """The same skip with the delivery confirmed: the resumed step's fresh pull was compared with no recorded
        delivery. Another digest is now RESULT_NOT_VERIFIED, with no pull receipt and no intake; the same digest
        resumes to verified."""
        case, puller = self.died_at_the_pull(delivered={'sha256': '0' * 64, 'size': 1})
        attempt_id = store_mod.attempt_id_for(case.key)
        with self.assertRaises(di.DispatchRefused) as caught:
            case.resume(pull=puller, exists=lambda name: True)
        self.assertEqual(caught.exception.code, 'RESULT_NOT_VERIFIED')
        self.assertEqual([case.store.get(k.format(attempt_id=attempt_id)) for k in (AR.PULL_KEY, AR.INTAKE_KEY)],
                         [None, None])
        self.assertEqual(case.reserved, [])
        case, puller = self.died_at_the_pull()
        self.assertEqual(case.resume(pull=puller, exists=lambda name: True).outcome, 'verified')

    def test_a_recorded_result_never_reads_a_dispatched_delivery_as_none(self):
        """recorded_result (the result path's reader) on an intake taken beside a delivery left dispatched: refused,
        where before the delivery read as none and the cross-check was skipped."""
        case, puller, delivery, intake = self.left_dispatched()
        case.store.transition(intake, 'confirmed', actor='test', reason='the intake taken', expected_from='dispatched')
        with self.assertRaises(di.DispatchRefused) as caught:
            AR.recorded_result(case.store, case.key, base=case.base)
        self.assertEqual(caught.exception.code, 'RESULT_DELIVERY_UNSETTLED')


if __name__ == '__main__':
    unittest.main()
