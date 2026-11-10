"""The integration-store receipt of a credential act (plan leaf F-06.3; decision 0007 point 5), against a
real integration store (integrations/store/integration_store.py) in a fixture database of a temporary
directory: reserved before anything changes, dispatched, confirmed or failed or unknown, read back,
fingerprints only. The role bots' rotate and retire (gitea_roles.py) run end to end against the fake Gitea
CLI and API of integrations/gitea/tests/test_gitea_roles.py with an in-memory credential provider, writing
their receipts into the fixture store; nothing touches Gitea, a credential store or the managed root.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


K = _load('aieh_credential_provider', HERE.parent / 'credential_provider.py')
C = K.contract
STORE = _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')
GT = _load('aieh_gitea_roles_tests', REPO / 'integrations' / 'gitea' / 'tests' / 'test_gitea_roles.py')
R = GT.R
BEFORE, AFTER = K.fingerprint('synthetic-old-value'), K.fingerprint('synthetic-new-value')


class FixtureStore(unittest.TestCase):
    """One fixture integration store per class, in a temporary directory."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-credentials-'))
        cls.store = STORE.open_store(cls.tmp / 'integration.sqlite')

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def receipt(self, **overrides):
        fields = dict(verb='rotate', service='gitea', entry='AIEH Gitea bot builder', user='aieh-bot-builder',
                      role='builder', fingerprint_before=BEFORE, provider='memory-fake', trigger='owner direction',
                      revoker='harness: a test', actor='test')
        fields.update(overrides)
        return K.ActReceipt(self.store, **fields)

    def states(self, key):
        return [event.to_state for event in self.store.events(key)]


class TestActReceipt(FixtureStore):
    def test_a_completed_act_is_confirmed_and_read_back(self):
        receipt = self.receipt().begin()
        self.assertEqual(self.store.get(receipt.key).state, 'reserved')  # before anything changes
        receipt.dispatched()
        result = receipt.finish({'fingerprint_after': AFTER})
        self.assertEqual(result, {'operation_key': receipt.key, 'format': 'aieh-credential-act/1',
                                  'state': 'confirmed', 'events': ['reserved', 'dispatched', 'confirmed'],
                                  'read_back': True})
        intent = json.loads(self.store.get(receipt.key).intent_json)
        self.assertEqual({k: intent[k] for k in ('verb', 'service', 'role', 'fingerprint_before', 'trigger',
                                                 'affected_attempts')},
                         {'verb': 'rotate', 'service': 'gitea', 'role': 'builder', 'fingerprint_before': BEFORE,
                          'trigger': 'owner direction', 'affected_attempts': []})
        self.assertEqual(json.loads(self.store.events(receipt.key)[-1].detail_json), {'fingerprint_after': AFTER})
        self.assertRegex(receipt.key, r'^credential/gitea/rotate/builder/\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ-[0-9a-f]{8}$')

    def test_an_act_with_nothing_to_change_is_still_confirmed(self):
        receipt = self.receipt(verb='retire', fingerprint_before=None).begin()
        receipt.finish({'state': 'retired (no entry: nothing to revoke)'})
        events = self.store.events(receipt.key)
        self.assertEqual([e.to_state for e in events], ['reserved', 'dispatched', 'confirmed'])
        self.assertIn('nothing upstream', events[1].reason)

    def test_a_stop_is_recorded_failed_or_unknown(self):
        refused = self.receipt().begin()
        refused.abort(C.LifecycleError('ENTRY_MISSING', 'x'))
        self.assertEqual(self.states(refused.key), ['reserved', 'failed'])
        observed = self.receipt().begin()
        observed.dispatched()
        observed.abort(C.LifecycleError('REVOCATION_FAILED', 'x', refusal=False))
        self.assertEqual(self.states(observed.key), ['reserved', 'dispatched', 'failed'])
        uncertain = self.receipt().begin()
        uncertain.dispatched()
        uncertain.abort(ConnectionResetError('lost'))
        self.assertEqual(self.states(uncertain.key), ['reserved', 'dispatched', 'unknown'])
        self.assertEqual(self.store.get(uncertain.key).reconciliation_status, 'required')
        self.assertEqual(json.loads(self.store.events(uncertain.key)[-1].detail_json),
                         {'code': 'ConnectionResetError'})

    def test_only_credential_verbs(self):
        with self.assertRaises(ValueError):
            self.receipt(verb='upgrade')

    def test_a_receipt_that_cannot_be_read_back_fails_the_act(self):
        class Forgetful:
            def __init__(self, store):
                self.store = store

            def __getattr__(self, name):
                return getattr(self.store, name)

            def get(self, key):
                return None
        receipt = K.ActReceipt(Forgetful(self.store), verb='retire', service='gitea', entry='e', user='u', role=None,
                               fingerprint_before=None, provider='p', trigger='t', revoker='r', actor='test').begin()
        with self.assertRaises(C.LifecycleError) as caught:
            receipt.finish({'state': 'retired'})
        self.assertEqual((caught.exception.code, caught.exception.refusal), ('CREDENTIAL_RECEIPT_UNREAD', False))
        self.assertIn('remedy:', str(caught.exception))

    def test_a_receipt_never_holds_a_secret_the_act_holds(self):
        guard = C.ExposureGuard()
        guard.hold('synthetic-secret-the-act-holds')
        receipt = self.receipt(guard=guard).begin()
        receipt.dispatched()
        with self.assertRaises(C.LifecycleError) as caught:
            receipt.finish({'oops': 'synthetic-secret-the-act-holds'})
        self.assertEqual(caught.exception.code, 'EXPOSURE_FOUND')
        self.assertEqual(self.store.get(receipt.key).state, 'dispatched')  # nothing with the secret was written
        self.assertNotIn('synthetic-secret-the-act-holds', self.store.canonical_dump().decode('utf-8'))


class TestRoleActsOnTheFixtureStore(FixtureStore):
    """gitea_roles rotate and retire, end to end over the fakes, with their receipts in the fixture store."""

    def setUp(self):
        self.gitea, self.cli = GT.FakeGitea(), GT.FakeCli()
        self.cli.gitea = self.gitea
        self.provider = GT.MemoryProvider({R.host.FINAL_TARGETS[R.host.SITE_ADMIN]: (R.host.SITE_ADMIN,
                                                                                      GT.ADMIN_PASSWORD)})
        self.ctx = GT.ctx(self.cli, self.provider)
        R.provision(http=self.gitea, ctx=self.ctx)

    def test_rotate_then_retire_each_write_a_receipt_read_back_from_the_store(self):
        old = self.provider.get(R.target('builder'))[1]
        rotated = R.rotate('builder', http=self.gitea, ctx=self.ctx, receipts=self.store)
        new = self.provider.get(R.target('builder'))[1]
        retired = R.retire('builder', http=self.gitea, ctx=self.ctx, receipts=self.store)
        for report, verb in ((rotated, 'rotate'), (retired, 'retire')):
            key = report['receipt']['operation_key']
            self.assertEqual(self.store.get(key).state, 'confirmed')
            self.assertEqual(self.states(key), ['reserved', 'dispatched', 'confirmed'])
            self.assertEqual(json.loads(self.store.get(key).intent_json)['verb'], verb)
        rotate_key, retire_key = rotated['receipt']['operation_key'], retired['receipt']['operation_key']
        self.assertEqual(json.loads(self.store.get(rotate_key).intent_json)['fingerprint_before'], R.fingerprint(old))
        self.assertEqual(json.loads(self.store.events(rotate_key)[-1].detail_json)['fingerprint_after'],
                         R.fingerprint(new))
        self.assertEqual(json.loads(self.store.get(retire_key).intent_json)['fingerprint_before'], R.fingerprint(new))
        dump = self.store.canonical_dump().decode('utf-8')
        for secret in (old, new, GT.ADMIN_PASSWORD):
            self.assertNotIn(secret, dump)

    def test_a_failed_revocation_is_failed_in_the_store(self):
        self.gitea.fail_path = '/token'
        with self.assertRaises(C.LifecycleError):
            R.retire('planner', http=self.gitea, ctx=self.ctx, receipts=self.store)
        (failed,) = [r for r in self.store.attempts(['failed'])
                     if json.loads(r.intent_json)['role'] == 'planner']
        self.assertEqual(self.states(failed.operation_key), ['reserved', 'dispatched', 'failed'])


if __name__ == '__main__':
    unittest.main()
