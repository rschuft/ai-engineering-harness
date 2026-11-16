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
as it is. A delivery receipt left ``dispatched`` is read by nothing and stays so (a residual).
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
        key = {'intake': AR.INTAKE_KEY, 'pull': AR.PULL_KEY}[which].format(attempt_id=attempt_id)
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


if __name__ == '__main__':
    unittest.main()
