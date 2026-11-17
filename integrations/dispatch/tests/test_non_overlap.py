"""Tests for execution non-overlap (plan leaf E-01.5; ``attempt_end.admit_new_attempt``, run by ``dispatch`` before
the next ordinal is reserved), offline, against the fixture catalog's cited core.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_non_overlap.py -v

The engineering manager's rulings (dispatch 18 of unit I1), each shown here:

* (a) the restart-recovery design's R22 point 1: every earlier ordinal of the triple whose history holds a
  ``dispatched`` event is asked of the Agent Server, whatever the store's final state for it (``failed`` included);
  ordinal N+1 is refused while that conversation is executing (``PRIOR_CONVERSATION_RUNNING``: the server holds it
  with its runtime not stopped) or its execution state is unknown (``PRIOR_CONVERSATION_UNOBSERVED``)
  (``NativeOrdinals``);
* (b) the 404 race: a refusal test includes a conversation that appears after E-01.4.1's lookup answered 404
  (``InFlight``, a test knob outside the catalog, derived from the pinned handler's order, named as such);
* (c) an earlier ordinal whose grant journal is not revoked refuses ordinal N+1 (``PRIOR_GRANT_UNREVOKED``), and a
  brokered attempt is held to the same non-overlap (``BrokeredOrdinals``, ``GrantJournal``).

Each refusal comes before the reservation: nothing is reserved, no create is sent, no credential is read or issued.
"""
from pathlib import Path
import contextlib
import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest

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


tar = _load('test_attempt_run', HERE / 'test_attempt_run.py')
secrets_tests = _load('test_d1_stage_secrets', HERE / 'test_d1_stage_secrets.py')
te, di, AE, store_mod = tar.te, tar.di, tar.AE, tar.store_mod
cc = te.cc
AC = cc.AC
RC = _load('aieh_dispatch_reconcile', HERE.parent / 'reconcile.py')

ACTOR = 'e-01.5-test'
CREATE = ('POST', '/api/conversations')
# The pinned handler's order (openhands_agent_server 1.60.1, sha256 df80a622...76f6, as the agentfixture README cites
# it): as:openhands/agent_server/docker_runtime/routers.py:173 (the provisioning identity), :184 (the container
# started), :187 (the create forwarded to it), :218 (the outer catalog refreshed, last); and
# as:openhands/agent_server/conversation_router.py:229-231 (a lookup answers 404 while the catalog lacks it).
HANDLER_ORDER = ('routers.py:173', 'routers.py:184', 'routers.py:187', 'routers.py:218',
                 'conversation_router.py:229-231')


def setUpModule():
    tar.setUpModule()


def tearDownModule():
    with contextlib.suppress(FileNotFoundError):
        tar.tearDownModule()


class InFlight:
    """A test knob (an answer no cited run gave, outside the catalog), derived from the pinned handler's order
    (HANDLER_ORDER): the server has received the create and is still processing it (its container started, the
    create forwarded) while its outer catalog does not hold the conversation yet, so that a lookup meanwhile answers
    404, and the dispatcher's own wait for the create's answer ends without one. Here the create is held back from
    the core (which so answers the lookup with its own ``conversation-absent``), the dispatcher gets a transport
    exception, and ``complete()`` is the handler's end: the core receives the create, and the conversation appears
    with its runtime ``available``. Every other request goes to the core."""

    def __init__(self, core):
        self.core, self.held = core, None

    def __call__(self, method, path, body=None, **kwargs):
        if (method, path) == CREATE and self.held is None:
            self.held = copy.deepcopy(body)
            raise TimeoutError('the create\'s answer did not come back in time')
        return self.core(method, path, body, **kwargs)

    def complete(self):
        answer = self.core(*CREATE, self.held)
        assert answer['status'] == 201, answer
        return self.held['conversation_id']


class Dropping:
    """A transport event: the requests named (method, path) never arrive (the core is not called; the caller gets an
    exception). Everything else goes to the core."""

    def __init__(self, core, *dropped):
        self.core, self.dropped = core, set(dropped)

    def __call__(self, method, path, body=None, **kwargs):
        if (method, path) in self.dropped:
            raise ConnectionError('the request did not arrive')
        return self.core(method, path, body, **kwargs)


class Ordinals(unittest.TestCase):
    def typed_of(self, store):
        return sorted((a for a in store.attempts() if a.operation_key.startswith('attempt/')),
                      key=lambda a: store.attempt_identity(a.operation_key).identity.ordinal)

    def refused(self, code, act):
        with self.assertRaises(di.DispatchRefused) as caught:
            act()
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        self.assertIn(code, di.REFUSALS)
        return caught.exception


class NativeOrdinals(Ordinals):
    """A native D1 attempt (E-05.9's fixture) on the core: rulings (a) and (b)."""
    category = 'integration'

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-non-overlap-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fixture = tar.attempt_fixture(self)
        self.core = AC.AgentServerCore(scratch=self.tmp / 'agentfixture')
        self.addCleanup(self.core.close)

    def dispatch(self, transport):
        return self.fixture.run_native(transport, manifest=self.fixture.manifest)

    def lost_then_reconciled(self):
        """Ordinal 1: its create in flight (InFlight) when the dispatcher's wait ended (``unknown``), then E-01.4.1's
        reconcile: the lookup answers 404 (the core's conversation-absent) and the attempt is ``failed``."""
        wire = InFlight(self.core)
        with self.assertRaises(TimeoutError):
            self.dispatch(wire)
        (first,) = self.typed_of(self.fixture.store)
        self.assertEqual(self.fixture.store.get(first.operation_key).state, 'unknown')
        RC.reconcile_creates(self.fixture.store, transport=wire, actor=ACTOR, read_artifact=self.fixture.read_artifact)
        self.assertEqual(self.fixture.store.get(first.operation_key).state, 'failed')
        cid = store_mod.conversation_id_for(first.operation_key)
        self.assertEqual(self.core.calls[-1][:2], ('GET', f'/api/conversations/{cid}'))
        self.assertNotIn(cid, self.core.conversations, 'the lookup was answered 404, the core\'s conversation-absent')
        return wire, first, cid

    def assertNothingNew(self, before_attempts, before_creates):
        self.assertEqual(len(self.typed_of(self.fixture.store)), before_attempts, 'nothing was reserved')
        self.assertEqual(len(self.core.creates), before_creates, 'no create was sent')

    def test_a_conversation_that_appears_after_the_404_refuses_the_next_ordinal(self):
        """Rulings (a) and (b): the failed ordinal 1 is asked whatever the store says; once the in-flight create
        completes, its conversation executes, and ordinal 2 is refused before it is reserved."""
        wire, first, cid = self.lost_then_reconciled()
        self.assertEqual(self.core.creates, [], 'the create is still in flight: the core has not received it')
        self.assertEqual(wire.complete(), cid)                    # the handler's end: the conversation appears
        reads, entries = len(self.core.calls), list(self.fixture.provider.reads)
        refusal = self.refused('PRIOR_CONVERSATION_RUNNING', lambda: self.dispatch(wire))
        self.assertEqual((refusal.context['attempt_id'], refusal.context['runtime_status']),
                         (store_mod.attempt_id_for(first.operation_key), 'available'))
        self.assertIn('failed', refusal.detail)
        self.assertEqual([c[:2] for c in self.core.calls[reads:]],
                         [('GET', f'/api/conversations/{cid}'), ('GET', f'/api/conversations/{cid}/runtime')])
        self.assertNothingNew(1, 1)
        self.assertEqual(self.fixture.provider.reads, entries, 'no credential was read for the refused ordinal')
        # once its runtime is stopped, nothing of it executes: ordinal 2 is admitted and dispatched
        self.core('DELETE', f'/api/conversations/{cid}/runtime')
        second = self.dispatch(wire)
        self.assertEqual(self.fixture.store.attempt_identity(second.operation_key).identity.ordinal, 2)
        self.assertEqual(self.fixture.store.get(second.operation_key).state, 'confirmed')

    def test_a_failed_attempt_whose_conversation_never_appeared_does_not_block(self):
        """The same failed ordinal 1, its create never completed: the server holds no such conversation (404)."""
        wire, first, cid = self.lost_then_reconciled()
        second = self.dispatch(wire)
        self.assertEqual(self.fixture.store.get(second.operation_key).state, 'confirmed')
        self.assertIn(('GET', f'/api/conversations/{cid}'), [c[:2] for c in self.core.calls])

    def test_an_unknown_execution_state_refuses_the_next_ordinal(self):
        """Ruling (a): the lookup, or the runtime read of a conversation the server holds, never arrives (a
        transport event): the execution state is unknown."""
        wire, first, cid = self.lost_then_reconciled()
        self.refused('PRIOR_CONVERSATION_UNOBSERVED',
                     lambda: self.dispatch(Dropping(self.core, ('GET', f'/api/conversations/{cid}'))))
        self.assertNothingNew(1, 0)
        wire.complete()
        self.refused('PRIOR_CONVERSATION_UNOBSERVED',
                     lambda: self.dispatch(Dropping(self.core, ('GET', f'/api/conversations/{cid}/runtime'))))
        self.assertNothingNew(1, 1)

    def test_an_attempt_that_sent_no_create_is_never_asked(self):
        """Its history holds no dispatched event (refused at admission): nothing to ask, and no call is made."""
        manifest = self.fixture.manifest
        with self.assertRaises(di.DispatchRefused):
            self.fixture.run_native(self.core, manifest=manifest, provider=te.NS.ObservedProvider({}))
        (first,) = self.typed_of(self.fixture.store)
        self.assertEqual(self.fixture.store.get(first.operation_key).state, 'failed')
        self.assertNotIn('dispatched', [e.to_state for e in self.fixture.store.events(first.operation_key)])
        calls = len(self.core.calls)
        second = self.dispatch(self.core)
        cid = store_mod.conversation_id_for(first.operation_key)
        self.assertNotIn(cid, ' '.join(c[1] for c in self.core.calls[calls:]))
        self.assertEqual(self.fixture.store.get(second.operation_key).state, 'confirmed')


class BrokeredOrdinals(secrets_tests.SecretsFixture, Ordinals):
    """The brokered profile (E-05.6: a broker grant per attempt, a real broker in process), its creates answered by
    the core: ruling (c), and non-overlap for every profile."""
    category = 'integration'

    def setUp(self):
        super().setUp()
        self.scratch = Path(tempfile.mkdtemp(prefix='aieh-non-overlap-'))
        self.addCleanup(shutil.rmtree, self.scratch, True)
        self.core = AC.AgentServerCore(scratch=self.scratch / 'agentfixture')
        self.addCleanup(self.core.close)
        self.manifest = self.approve_d1()

    def test_an_unrevoked_grant_then_an_executing_conversation_refuse_the_next_ordinal(self):
        spy = self.spy()
        first = self.run_dispatch(self.core, spy, manifest=self.manifest)
        attempt_id = store_mod.attempt_id_for(first.operation_key)
        self.assertEqual(AE.grant_unrevoked(self.store, attempt_id), 'confirmed')
        issued, calls = len(spy.issued), len(self.core.calls)
        refusal = self.refused('PRIOR_GRANT_UNREVOKED', lambda: self.run_dispatch(self.core, spy,
                                                                                manifest=self.manifest))
        self.assertEqual((refusal.context['attempt_id'], refusal.context['reason']), (attempt_id, 'confirmed'))
        self.assertEqual((len(spy.issued), len(self.core.calls)), (issued, calls), 'no issue and no call')
        self.assertEqual(len(self.typed_of(self.store)), 1, 'nothing was reserved')
        # the grant revoked by its end: the next refusal is the conversation, still executing at the server
        di.end_attempt(self.store, first.operation_key, inference=self.access_for(spy), actor=ACTOR)
        self.assertIsNone(AE.grant_unrevoked(self.store, attempt_id))
        refusal = self.refused('PRIOR_CONVERSATION_RUNNING', lambda: self.run_dispatch(self.core, spy,
                                                                                     manifest=self.manifest))
        self.assertEqual(refusal.context['runtime_status'], 'available')
        self.assertEqual((len(spy.issued), len(self.typed_of(self.store))), (issued, 1))
        self.core('DELETE', f'/api/conversations/{first.conversation_id}/runtime')
        second = self.run_dispatch(self.core, spy, manifest=self.manifest)
        self.assertEqual((self.store.get(second.operation_key).state,
                          self.store.attempt_identity(second.operation_key).identity.ordinal), ('confirmed', 2))


class GrantJournal(unittest.TestCase):
    """``grant_unrevoked`` over the grant journal and the revocation receipts, as the dispatcher writes them (their
    keys and formats), in each state ``end_attempt`` reads."""
    category = 'unit'
    ATTEMPT = '0f1e2d3c-4b5a-4968-8776-655443322110'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-grant-journal-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = store_mod.open_store(self.tmp / 'integration.sqlite')
        self.addCleanup(self.store.close)
        self.key = di.GRANT_JOURNAL_KEY.format(attempt_id=self.ATTEMPT)

    def journal(self, *moves):
        self.store.reserve(self.key, {'format': di.GRANT_JOURNAL_FORMAT, 'attemptId': self.ATTEMPT}, actor=ACTOR)
        state = 'reserved'
        for to_state, detail in moves:
            self.store.transition(self.key, to_state, actor=ACTOR, reason='t', detail=detail, expected_from=state)
            state = to_state

    def revocation(self, n, *states):
        key = di.REVOCATION_KEY.format(attempt_id=self.ATTEMPT, n=n)
        self.store.reserve(key, {'format': di.REVOCATION_FORMAT, 'attemptId': self.ATTEMPT}, actor=ACTOR)
        state = 'reserved'
        for to_state in states:
            self.store.transition(key, to_state, actor=ACTOR, reason='t', detail=None, expected_from=state)
            state = to_state

    def test_each_state(self):
        self.assertIsNone(AE.grant_unrevoked(self.store, self.ATTEMPT), 'no journal: no grant')
        self.journal(('dispatched', None))
        self.assertEqual(AE.grant_unrevoked(self.store, self.ATTEMPT), 'dispatched', 'an issue whose outcome is unknown')
        self.store.transition(self.key, 'confirmed', actor=ACTOR, reason='issued', expected_from='dispatched',
                              detail={'format': di.GRANT_JOURNAL_FORMAT, 'tokenFingerprint': 'sha256:' + 'a' * 16})
        self.assertEqual(AE.grant_unrevoked(self.store, self.ATTEMPT), 'confirmed', 'issued, not revoked')
        self.revocation(1, 'dispatched')
        self.assertEqual(AE.grant_unrevoked(self.store, self.ATTEMPT), 'revocation-unsettled')
        self.store.transition(di.REVOCATION_KEY.format(attempt_id=self.ATTEMPT, n=1), 'failed', actor=ACTOR,
                              reason='t', expected_from='dispatched')
        self.assertEqual(AE.grant_unrevoked(self.store, self.ATTEMPT), 'confirmed', 'a failed revocation revokes nothing')
        self.revocation(2, 'dispatched', 'confirmed')
        self.assertIsNone(AE.grant_unrevoked(self.store, self.ATTEMPT), 'revoked')

    def test_a_refused_issue_is_no_grant(self):
        self.journal(('dispatched', None), ('failed', {'format': di.GRANT_JOURNAL_FORMAT, 'issued': False,
                                                       'code': 'GRANT_REFUSED'}))
        self.assertIsNone(AE.grant_unrevoked(self.store, self.ATTEMPT))
        self.revocation(1, 'dispatched')
        self.assertEqual(AE.grant_unrevoked(self.store, self.ATTEMPT), 'revocation-unsettled')


class Readme(unittest.TestCase):
    category = 'unit'

    def test_the_readme_states_which_earlier_attempts_are_asked(self):
        text = ' '.join((HERE.parent / 'README.md').read_text(encoding='utf-8').split())
        self.assertFalse('An earlier attempt that failed before or at its create created no conversation' in text,
                         'the README still says a failed attempt created no conversation')
        self.assertTrue('`PRIOR_GRANT_UNREVOKED`' in text, 'the README names PRIOR_GRANT_UNREVOKED')


if __name__ == '__main__':
    unittest.main()
