"""Tests for ``recover``, the restart procedure (plan leaf E-01.4.2, slice 5b: ``restart_recovery.py``), offline.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_restart_recovery.py -v

On the existing fakes, unchanged (E-05.8's ``ConversationServer`` with the attempt run's ``RunServer``, on E-05.9's
native fixture), as E-01.4.1's tests use them. A dispatcher's death is a BaseException at the point the test chooses
(``te.Crash``): the act's continuation is dropped and, with it, the lock (a simulated death; the real-process facts
are E-01.1.2's crash matrix and slice 5a's KilledHolder). Shown here, against slice 5b's completion conditions:

1. each row of R18's table, with the store's event history (states, reasons, details) and the transport's calls
   (``Table``);
2. with the lock held elsewhere: DISPATCHER_BUSY, the canonical dump unchanged, zero calls (``Busy``);
3. the namespace: outside an epoch, the recorders', the credential provider's, the broker's and the dispatcher's
   other receipts, each left reserved, dispatched and unknown, are byte for byte what they were, with no call for
   them; inside an epoch, exactly the store's own sweep and the turn arm (``Namespace``);
4. no send: every call ``recover`` makes is a GET, and its module names no sender (``NoSend``);
5. idempotent and crash-safe: a second recover changes nothing, and a BaseException at each of its transitions, then
   a re-run, converges on the same store (``Convergence``);
6. refused clients settle nothing (``RefusedClients``);
7. a row another writer moved between recover's read and its transition is reported and left, never retried
   (``Conflicts``);
and R21's holds (G, H, I) with the grant journal's report (``Holds``).
"""
from pathlib import Path
import ast
import contextlib
import copy
import importlib.util
import json
import sys
import unittest
import uuid
from unittest import mock

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


tdl = _load('test_dispatcher_lock', HERE / 'test_dispatcher_lock.py')
tar, te, di, AE, store_mod, AR, cc, DL = tdl.tar, tdl.te, tdl.di, tdl.AE, tdl.store_mod, tdl.AR, tdl.cc, tdl.DL
RR = _load('restart_recovery', HERE.parent / 'restart_recovery.py')
RC = RR.RC
OWNER_AR = _load('authorization_recorder', REPO / 'integrations' / 'owner' / 'authorization_recorder.py')   # P-04.2
OWNER_ID = _load('input_decisions', REPO / 'integrations' / 'owner' / 'input_decisions.py')                # P-04.3

ACTOR = 'e-01.4.2-test'
EPOCH_REASON = 'restore epoch: outcome uncertain after restore'
FOUND_REASON, NOT_FOUND_REASON = 'reconciled: observed in the external system', \
    'reconciled: not present in the external system'


def setUpModule():
    tar.setUpModule()


def tearDownModule():
    with contextlib.suppress(FileNotFoundError):
        tar.tearDownModule()


class Recording:
    """The transport recover is given: each call recorded (what the fake received), then answered by the server."""

    def __init__(self, server):
        self.server, self.calls = server, []

    def __call__(self, method, path, body, **kwargs):
        self.calls.append((method, path))
        return self.server(method, path, body, **kwargs)


class Fixture(tdl.Attempt):
    """A native D1 attempt on the fakes, with the dispatcher's deaths at the points the table needs."""

    def recover(self, transport=None, read_artifact=None):
        transport = transport or Recording(self.server)
        report = RR.recover(self.store, transport=transport, actor=ACTOR,
                            read_artifact=read_artifact or self.fixture.read_artifact)
        calls = getattr(transport, 'calls', [])
        self.assertEqual([m for m, _ in calls if m != 'GET'], [], 'recover makes GETs only')
        json.dumps(report)
        return report, calls

    def lookup(self, cid):
        return ('GET', f'/api/conversations/{cid}')

    def moves(self, key, since=0):
        return [(e.from_state, e.to_state, e.reason, json.loads(e.detail_json) if e.detail_json else None)
                for e in self.store.events(key)[since:]]

    def only_attempt(self):
        (attempt,) = [a for a in self.store.attempts() if a.operation_key.startswith(store_mod.KEY_PREFIX)]
        return attempt

    # -- deaths --------------------------------------------------------------------------------------------------
    def dies_reserved(self):
        with mock.patch.object(di, 'create_workspace', side_effect=te.Crash('dies reserved')), \
                self.assertRaises(te.Crash):
            self.dispatch()
        attempt = self.only_attempt()
        self.assertEqual(attempt.state, 'reserved')
        return attempt

    def dies_at_create(self, received):
        def transport(method, path, body, **kwargs):
            if (method, path) == cc.CREATE and not received:
                raise te.Crash('dies before the create is sent')
            answer = self.server(method, path, body, **kwargs)
            if (method, path) == cc.CREATE:
                raise te.Crash('dies after the server handled the create')
            return answer
        with self.assertRaises(te.Crash):
            self.dispatch(transport)
        attempt = self.only_attempt()
        self.assertEqual(attempt.state, 'dispatched')
        self.assertEqual(len(self.server.creates), 1 if received else 0)
        return attempt

    def dies_at_message(self, received, error=None):
        """A confirmed attempt whose run dies at the message (RECEIVED: after the server handled it); ERROR, an
        Exception instead of the death: the answer lost, the dispatcher alive."""
        result = self.confirmed()

        def transport(method, path, body, **kwargs):
            if method == 'POST' and path.endswith('/events'):
                if not received:
                    raise error or te.Crash('dies before the message is sent')
                self.server(method, path, body, **kwargs)
                raise error or te.Crash('dies after the server handled the message')
            return self.server(method, path, body, **kwargs)
        self.server.after_message = 'running'
        with contextlib.suppress(te.Crash, di.DispatchRefused):
            self.run_attempt(result.operation_key, transport)
        return result, self.turn(result.operation_key)

    def turn_key(self, result):
        return AR.TURN_KEY.format(attempt_id=store_mod.attempt_id_for(result.operation_key))


# ---------------------------------------------------------------------------
# 1. R18's table, row by row

class Table(Fixture):
    def test_a_reserved_attempt_whose_conversation_is_not_found_fails_not_sent(self):
        attempt = self.dies_reserved()
        key, cid = attempt.operation_key, attempt.conversation_id
        report, calls = self.recover()
        self.assertEqual(calls, [self.lookup(cid)])
        self.assertEqual(self.moves(key, 1), [('reserved', 'failed', RR.REASON_NOT_SENT, {
            'code': 'NOT_SENT', 'basis': RC.LOOKUP, 'conversationId': cid, 'httpStatus': 404})])
        self.assertEqual(report['entries'], [{'operationKey': key, 'class': RR.ATTEMPT, 'found': 'reserved',
                                              'basis': RC.LOOKUP, 'verdict': RC.NOT_PERFORMED, 'httpStatus': 404,
                                              'conversationId': cid, 'state': 'failed'}])
        self.assertEqual((report['held'], report['conflicts'], report['epoch']), ([], [], False))
        # the claim is released: the next dispatch is ordinal 2, with its own conversation, one create in all
        result = self.dispatch()
        self.assertEqual(self.store.attempt_identity(result.operation_key).identity.ordinal, 2)
        self.assertEqual([b['conversation_id'] for _, _, b in self.server.creates], [result.conversation_id])

    def test_a_reserved_attempt_whose_conversation_exists_is_held_unchanged(self):
        attempt = self.dies_reserved()
        key, cid = attempt.operation_key, attempt.conversation_id
        self.server.conversations[cid] = {'execution_status': 'idle', 'events': [], 'runtime': 'available'}
        events = self.store.events(key)
        report, calls = self.recover()
        self.assertEqual((calls, self.store.events(key)), ([self.lookup(cid)], events))
        self.assertEqual(report['held'], [{'operationKey': key, 'class': RR.ATTEMPT,
                                           'code': 'RESERVED_CONVERSATION_FOUND', 'conversationId': cid,
                                           'resolver': RR.RESOLVERS['RESERVED_CONVERSATION_FOUND']}])
        self.assertEqual(report['entries'][0]['state'], 'reserved')

    def test_a_reserved_attempt_with_any_other_answer_is_asked_again_at_the_next_recover(self):
        attempt = self.dies_reserved()
        key, cid = attempt.operation_key, attempt.conversation_id
        events = self.store.events(key)
        for name, failure in {'503': {'status': 503, 'body': None}, 'another id': {'status': 200, 'body': {
                'id': str(uuid.uuid4())}}, 'no answer': TimeoutError('no answer')}.items():
            with self.subTest(name):
                self.server.fail[('GET', 'info')] = failure
                report, calls = self.recover()
                self.assertEqual((calls, self.store.events(key)), ([self.lookup(cid)], events))
                self.assertEqual([(h['code'], h['resolver']) for h in report['held']],
                                 [('LOOKUP_INDETERMINATE', 'recover, which asks again')])
        self.server.fail.clear()
        self.recover()
        self.assertEqual(self.store.get(key).state, 'failed')

    def test_a_dispatched_attempt_whose_create_was_not_received_becomes_unknown_then_failed(self):
        attempt = self.dies_at_create(received=False)
        key, cid = attempt.operation_key, attempt.conversation_id
        report, calls = self.recover()
        self.assertEqual(calls, [self.lookup(cid)])
        self.assertEqual(self.moves(key, 2), [
            ('dispatched', 'unknown', RR.REASON_CREATE_UNKNOWN, {'code': 'OUTCOME_UNKNOWN', 'answer': 'not recorded',
                                                                  'basis': RR.LOCK_BASIS}),
            ('unknown', 'failed', NOT_FOUND_REASON, None)])
        self.assertEqual(report['creates']['failed'], [key])
        self.assertEqual(self.server.creates, [], 'no create, then or now')

    def test_a_dispatched_attempt_whose_create_was_received_is_reattached(self):
        attempt = self.dies_at_create(received=True)
        key, cid = attempt.operation_key, attempt.conversation_id
        report, calls = self.recover()
        self.assertEqual(calls, [self.lookup(cid)])
        self.assertEqual([m[:3] for m in self.moves(key, 2)], [
            ('dispatched', 'unknown', RR.REASON_CREATE_UNKNOWN), ('unknown', 'confirmed', FOUND_REASON)])
        self.assertEqual((report['creates']['confirmed'], report['entries'][0]['state']), ([key], 'confirmed'))
        self.assertEqual(len(self.server.creates), 1)
        # reattached: its record reads as any confirmed attempt's; a repeat of the dispatch reserves nothing
        di.stored_inputs(self.store, key, state='confirmed')
        with self.assertRaises(di.DispatchRefused):
            self.dispatch()
        self.assertEqual([a.operation_key for a in self.store.attempts() if a.operation_key.startswith(
            store_mod.KEY_PREFIX)], [key])
        self.assertEqual(len(self.server.creates), 1)

    def test_an_unknown_attempt_is_settled_by_e_01_4_1s_lookup_unchanged(self):
        with self.assertRaises(TimeoutError):
            self.dispatch(_lost_create(self.server))
        attempt = self.only_attempt()
        self.assertEqual(attempt.state, 'unknown')
        report, calls = self.recover()
        self.assertEqual(calls, [self.lookup(attempt.conversation_id)])
        self.assertEqual(self.moves(attempt.operation_key)[-1][:3], ('unknown', 'confirmed', FOUND_REASON))
        self.assertEqual(report['creates']['observations'], [{
            'operationKey': attempt.operation_key, 'verdict': RC.PERFORMED, 'basis': RC.LOOKUP,
            'conversationId': attempt.conversation_id, 'httpStatus': 200}])

    def test_a_dispatched_turn_whose_message_was_received_is_confirmed_from_the_events(self):
        result, turn = self.dies_at_message(received=True)
        key, cid = turn.operation_key, result.conversation_id
        self.assertEqual(turn.state, 'dispatched')
        report, calls = self.recover()
        self.assertEqual(self.moves(key, 2), [
            ('dispatched', 'unknown', RR.REASON_TURN_UNKNOWN, {'code': 'OUTCOME_UNKNOWN', 'answer': 'not recorded',
                                                                'basis': RR.LOCK_BASIS}),
            ('unknown', 'confirmed', 'reconciled-from-events', {'status': None})])
        self.assertEqual(calls, [('GET', f'/api/conversations/{cid}'), ('GET', f'/api/conversations/{cid}/events/'
                                                                                'search')])
        self.assertEqual(report['held'], [])
        self.assertEqual(self.server.log.count(('POST', 'events')), 1, 'the one message')

    def test_a_dispatched_turn_whose_message_was_not_received_stays_unknown_held(self):
        result, turn = self.dies_at_message(received=False)
        key = turn.operation_key
        report, calls = self.recover()
        self.assertEqual([m[:3] for m in self.moves(key, 2)], [('dispatched', 'unknown', RR.REASON_TURN_UNKNOWN)])
        self.assertEqual(self.store.get(key).state, 'unknown')
        self.assertEqual([(h['operationKey'], h['code']) for h in report['held']], [(key, 'TURN_UNRECONCILED')])
        self.assertEqual(self.server.log.count(('POST', 'events')), 0, 'never sent, then or now')
        # the result step is refused on it, and nothing sends the message
        with self.assertRaises(di.DispatchRefused) as caught:
            AR.resume_result(self.store, result.operation_key, transport=self.server, base=self.base, actor=ACTOR,
                             pull=lambda n: self.fail('no pull'), exists=lambda n: False,
                             read_artifact=self.fixture.read_artifact)
        self.assertEqual(caught.exception.code, 'TURN_NOT_CONFIRMED')
        # a later recover asks again, and confirms once the events hold the message
        self.server.set(result.conversation_id, events=[{'kind': 'MessageEvent', 'id': 'm1', 'source': 'user',
                                                         'llm_message': {'content': [{'type': 'text',
                                                                                      'text': _text(self, result)}]}}])
        report, _ = self.recover()
        self.assertEqual((self.store.get(key).state, report['held']), ('confirmed', []))

    def test_an_unknown_turn_is_reconciled_from_the_events(self):
        result, turn = self.dies_at_message(received=False, error=OSError('the answer was lost'))
        self.assertEqual(turn.state, 'unknown')         # send_message's own reconcile found nothing
        self.server.set(result.conversation_id, events=[{'kind': 'MessageEvent', 'id': 'm1', 'source': 'user',
                                                         'llm_message': {'content': [{'type': 'text',
                                                                                      'text': _text(self, result)}]}}])
        report, _ = self.recover()
        self.assertEqual(self.moves(turn.operation_key)[-1][:3], ('unknown', 'confirmed', 'reconciled-from-events'))
        self.assertEqual(report['entries'][-1]['found'], 'unknown')

    def test_every_other_state_is_left_and_asks_nothing(self):
        result = self.confirmed()                       # a confirmed attempt, no turn journal (F, and G)
        report, calls = self.recover()
        self.assertEqual((calls, report['entries'], report['held']), ([], [], []))
        self.assertEqual(self.store.get(result.operation_key).state, 'confirmed')


def _lost_create(server):
    def transport(method, path, body, **kwargs):
        answer = server(method, path, body, **kwargs)
        if (method, path) == cc.CREATE:
            raise TimeoutError('the create answer was lost')
        return answer
    return transport


def _text(test, result):
    """The attempt's message text, rebuilt as run_attempt built it."""
    resolved = di.stored_inputs(test.store, result.operation_key, state='confirmed')
    return AR.prepare(resolved, test.base, store_mod.attempt_id_for(result.operation_key),
                      AR.attempt_time(test.store, result.operation_key)).text


# ---------------------------------------------------------------------------
# 2. Busy

class Busy(Fixture):
    def test_with_the_lock_held_elsewhere_nothing_is_read_or_changed(self):
        self.dies_at_create(received=True)
        for name, holding in {'a second handle': tdl.held_by_handle, 'another thread': tdl.held_by_thread}.items():
            with self.subTest(name):
                dump, transport = self.store.canonical_dump(), Recording(self.server)
                with holding(self.store.path), self.assertRaises(di.DispatchRefused) as caught:
                    RR.recover(self.store, transport=transport, actor=ACTOR, read_artifact=self.fixture.read_artifact)
                self.assertEqual(caught.exception.code, 'DISPATCHER_BUSY')
                self.assertEqual((self.store.canonical_dump(), transport.calls), (dump, []))
        with tdl._process(self, self.store.path):
            dump = self.store.canonical_dump()
            with self.assertRaises(di.DispatchRefused) as caught:
                RR.recover(self.store, transport=self.server, actor=ACTOR, read_artifact=self.fixture.read_artifact)
            self.assertEqual((caught.exception.code, self.store.canonical_dump()), ('DISPATCHER_BUSY', dump))


# ---------------------------------------------------------------------------
# 3. The namespace

def other_keys(n):
    """Keys of every other resolver, each with its own key builder (N distinguishes a set): (key, actor)."""
    def attempt():
        return str(uuid.uuid4())
    keys = [(OWNER_AR.RECEIPT_PREFIX + uuid.uuid4().hex, OWNER_AR.RECORDER),                       # P-04.2
            (OWNER_ID.promotion_key(7 + n), OWNER_ID.RECORDER),                                     # P-04.3
            (OWNER_ID.design_key('demo-app', 'change-x', 2 + n), OWNER_ID.RECORDER),                # P-04.3
            (f'credential/dispatch-native-token/write/entry/20261116T000000Z-{uuid.uuid4().hex[:8]}', 'provider'),
            (f'inference/attempt/{attempt()}/grant', 'inference-broker')]
    for builder in (AE.END_KEY, AE.RESULT_KEY, di.GRANT_JOURNAL_KEY, AR.DELIVERY_KEY, AR.PULL_KEY, AR.INTAKE_KEY):
        keys.append((builder.format(attempt_id=attempt()), 'dispatch'))
    keys.append((di.REVOCATION_KEY.format(attempt_id=attempt(), n=1), 'dispatch'))
    keys.append((AR.TURN_KEY.format(attempt_id=attempt()), 'dispatch'))      # the turn's form, not a turn's intent
    return keys


class Affirming:
    """Answers every call 200 with the conversation its path names, recording each: a verdict it is never asked for
    cannot come from it."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, path, body, **kwargs):
        self.calls.append((method, path))
        return {'status': 200, 'body': {'id': path.rsplit('/', 1)[-1], 'execution_status': 'running'}}


class Namespace(Fixture):
    def receipts(self):
        made = {}
        for n, state in enumerate(('reserved', 'dispatched', 'unknown')):
            for key, actor in other_keys(n):
                self.store.reserve(key, {'format': 'e-01.4.2-fixture', 'key': key}, actor=actor)
                for step in {'reserved': (), 'dispatched': ('dispatched',),
                             'unknown': ('dispatched', 'unknown')}[state]:
                    self.store.transition(key, step, actor=actor, reason=f'its own act: {step}')
                made[key] = state
        return made

    def test_outside_an_epoch_every_other_key_is_untouched_and_never_asked_about(self):
        attempt = self.dies_at_create(received=True)
        made = self.receipts()
        before = {k: (self.store.get(k), self.store.events(k)) for k in made}
        transport = Affirming()
        report, calls = self.recover(transport)
        self.assertEqual(calls, [self.lookup(attempt.conversation_id)])
        self.assertEqual(self.store.get(attempt.operation_key).state, 'confirmed')
        for key in made:
            with self.subTest(key=key, state=made[key]):
                self.assertEqual((self.store.get(key), self.store.events(key)), before[key])
        reported = {e['operationKey'] for e in report['entries']} | {h['operationKey'] for h in report['held']}
        self.assertEqual(reported, {attempt.operation_key})
        self.assertEqual({o['operationKey'] for o in report['creates']['observations']}, {attempt.operation_key})

    def test_inside_an_epoch_exactly_the_stores_sweep_and_the_turn_arm(self):
        result, turn = self.dies_at_message(received=True)
        made = self.receipts()
        self.restore()
        before = {k: self.store.events(k) for k in made}
        report, calls = self.recover()
        self.assertTrue(report['epoch'])
        for key, state in made.items():
            with self.subTest(key=key, state=state):
                moved = [(e.from_state, e.to_state, e.reason) for e in self.store.events(key)[len(before[key]):]]
                self.assertEqual(moved, [('dispatched', 'unknown', EPOCH_REASON)] if state == 'dispatched' else [])
        # the turn: the sweep's unknown (not recover's own), then the turn arm's confirmation from the events
        self.assertEqual([m[:3] for m in self.moves(turn.operation_key, 2)], [
            ('dispatched', 'unknown', EPOCH_REASON), ('unknown', 'confirmed', 'reconciled-from-events')])
        self.assertEqual([c for c in calls if 'conversations/' not in c[1]], [])

    def test_inside_an_epoch_the_turn_arm_lets_the_epoch_close(self):
        result, turn = self.dies_at_message(received=True)
        self.restore()
        with self.assertRaises(store_mod.EpochNotReconciled):
            self.store.reconcile(lambda r: 'indeterminate', actor=ACTOR)
            self.store.close_restore_epoch(actor='owner')        # without the turn arm: the swept turn holds it open
        self.recover()
        self.assertEqual(self.store.get(turn.operation_key).state, 'confirmed')
        self.assertEqual(len(self.store.close_restore_epoch(actor='owner')), 1)

    def test_a_dispatched_create_inside_an_epoch_is_the_sweeps_then_e_01_4_1s(self):
        attempt = self.dies_at_create(received=False)
        self.restore()
        self.recover()
        self.assertEqual([m[:3] for m in self.moves(attempt.operation_key, 2)], [
            ('dispatched', 'unknown', EPOCH_REASON), ('unknown', 'failed', NOT_FOUND_REASON)])
        self.assertEqual(len(self.store.close_restore_epoch(actor='owner')), 1)

    def restore(self):
        path = Path(self.store.path)
        manifest = self.store.backup(actor='owner')
        self.store.close()
        store_mod.restore_store(path, path.parent / 'backups' / (manifest['backup_file'] + '.manifest.json'),
                                actor='owner')
        self.fixture.store = self.store = store_mod.open_store(path)
        self.addCleanup(self.store.close)
        self.assertEqual(len(self.store.open_epochs()), 1)


# ---------------------------------------------------------------------------
# 4. No send

class NoSend(unittest.TestCase):
    category = 'contract'

    def test_the_module_names_no_sender_and_calls_only_gets(self):
        tree = ast.parse((HERE.parent / 'restart_recovery.py').read_text(encoding='utf-8'))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
            n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {'send_create', 'send_message', 'dispatch', '_dispatch', 'end_attempt',
                                  'end_interrupted_attempt', 'reserve', 'reserve_attempt', 'stop_runtime',
                                  'control', 'revoke', 'issue'})
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == 'call']
        self.assertEqual([ast.unparse(c.args[0]) for c in calls], ["'GET'"])

    def test_the_read_only_transport_refuses_anything_but_a_get(self):
        seen = []
        reads = RR._ReadOnly(lambda method, path, body: seen.append((method, path, body)) or {'status': 200})
        self.assertEqual(reads('GET', '/x', None), {'status': 200})
        for method, body, kwargs in (('POST', {}, {}), ('DELETE', None, {}), ('GET', {'a': 1}, {}),
                                     ('GET', None, {'deliver': {'name': 'x'}})):
            with self.subTest(method=method), self.assertRaises(RR.ReadOnlyRefused):
                reads(method, '/x', body, **kwargs)
        self.assertEqual(seen, [('GET', '/x', None)])


# ---------------------------------------------------------------------------
# 5. Idempotent and crash-safe

class Convergence(Fixture):
    def snapshot(self):
        """Each key's state and its (from, to, reason) history."""
        return {a.operation_key: (a.state, [(e.from_state, e.to_state, e.reason)
                                            for e in self.store.events(a.operation_key)])
                for a in self.store.attempts()}

    def case(self):
        case = Convergence('test_a_death_at_each_transition_then_a_re_run_converges')
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_a_second_recover_changes_nothing_and_asks_only_about_what_is_unsettled(self):
        self.dies_at_create(received=True)
        self.recover()
        dump = self.store.canonical_dump()
        report, calls = self.recover()
        self.assertEqual((self.store.canonical_dump(), calls, report['entries']), (dump, [], []))
        held = self.case()
        attempt = held.dies_at_create(received=True)
        held.server.fail[('GET', 'info')] = {'status': 503, 'body': None}
        held.recover()
        dump = held.store.canonical_dump()
        _, calls = held.recover()
        self.assertEqual((held.store.canonical_dump(), calls), (dump, [held.lookup(attempt.conversation_id)]))

    def scenarios(self):
        return {'a create received': lambda case: case.dies_at_create(received=True),
                'a create not received': lambda case: case.dies_at_create(received=False),
                'a reserved attempt': lambda case: case.dies_reserved(),
                'a message received': lambda case: case.dies_at_message(received=True)}

    def test_a_death_at_each_transition_then_a_re_run_converges(self):
        for name, arrange in self.scenarios().items():
            clean = self.case()
            arrange(clean)
            real_clean, transitions = clean.store.transition, [0]

            def counting(*args, **kwargs):
                transitions[0] += 1
                return real_clean(*args, **kwargs)
            with mock.patch.object(clean.store, 'transition', counting):
                clean.recover()
            expected = clean.snapshot()
            self.assertGreater(transitions[0], 0, name)
            for n in range(1, transitions[0] + 1):
                with self.subTest(name, death_at=n):
                    case = self.case()
                    arrange(case)
                    real, count = case.store.transition, [0]

                    def dying(*args, **kwargs):
                        count[0] += 1
                        if count[0] == n:
                            raise te.Crash(f'recover dies at its transition {n}')
                        return real(*args, **kwargs)
                    with mock.patch.object(case.store, 'transition', dying), self.assertRaises(te.Crash):
                        case.recover()
                    self.assertTrue(tdl.free_elsewhere(case.store.path))
                    case.recover()
                    self.assertEqual(case.snapshot(), expected)


# ---------------------------------------------------------------------------
# 6. Refused clients settle nothing

class RefusedClients(Fixture):
    def test_an_unreadable_or_drifted_allowlist_settles_nothing(self):
        reserved = self.dies_reserved()
        for name, change in {'drifted': lambda raw: raw + b' ', 'unreadable': None}.items():
            with self.subTest(name):
                def read_artifact(path):
                    if path.endswith('/routes.json'):
                        if change is None:
                            raise OSError('unreadable')
                        return change(self.fixture.read_artifact(path))
                    return self.fixture.read_artifact(path)
                dump = self.store.canonical_dump()
                report, calls = self.recover(read_artifact=read_artifact)
                self.assertEqual((calls, self.store.canonical_dump()), ([], dump))
                self.assertEqual([(h['operationKey'], h['code'], h['basis']) for h in report['held']],
                                 [(reserved.operation_key, 'LOOKUP_INDETERMINATE', RC.CLIENT_UNAVAILABLE)])

    def test_a_call_the_client_refuses_settles_nothing(self):
        attempt = self.dies_at_create(received=True)
        refused = di.DispatchRefused('ROUTE_NOT_ALLOWLISTED', 'refused by the client')
        with mock.patch.object(di.AgentServerClient, 'call', side_effect=refused):
            report, calls = self.recover()
        self.assertEqual(calls, [])
        self.assertEqual(self.store.get(attempt.operation_key).state, 'unknown')   # the lock's move only
        self.assertEqual([(h['code'], h['basis']) for h in report['held']], [('OUTCOME_UNKNOWN', RC.CALL_REFUSED)])
        report, _ = self.recover()
        self.assertEqual(self.store.get(attempt.operation_key).state, 'confirmed')

    def test_a_turn_whose_client_cannot_be_built_stays_unknown(self):
        result, turn = self.dies_at_message(received=True)
        report, calls = self.recover(read_artifact=lambda path: b'{}')
        self.assertEqual((self.store.get(turn.operation_key).state, calls), ('unknown', []))
        self.assertEqual([(h['code'], h['basis']) for h in report['held']],
                         [('TURN_UNRECONCILED', RC.CLIENT_UNAVAILABLE)])


# ---------------------------------------------------------------------------
# 7. A row another writer moved

class Conflicts(Fixture):
    def test_a_row_moved_between_the_read_and_the_transition_is_reported_and_left(self):
        attempt = self.dies_at_create(received=True)
        key = attempt.operation_key
        real, tried = self.store.transition, []

        def racing(operation_key, to_state, **kwargs):
            if operation_key == key and kwargs.get('expected_from') == 'dispatched' and to_state == 'unknown':
                tried.append(to_state)
                real(key, 'confirmed', actor='another-writer', reason='its own act', expected_from='dispatched')
            return real(operation_key, to_state, **kwargs)
        with mock.patch.object(self.store, 'transition', racing):
            report, calls = self.recover()
        self.assertEqual(tried, ['unknown'], 'never retried')
        self.assertEqual(self.store.get(key).state, 'confirmed')
        self.assertEqual(self.moves(key, 2)[0][:3], ('dispatched', 'confirmed', 'its own act'))
        self.assertEqual(len(self.moves(key, 2)), 1)
        self.assertEqual(report['conflicts'], [{'operationKey': key, 'expected': 'dispatched', 'to': 'unknown',
                                                'found': 'confirmed', 'error': 'IllegalTransition'}])
        self.assertEqual(calls, [])

    def test_a_conflict_in_the_lookup_arm_is_reported_and_the_other_rows_go_on(self):
        attempt = self.dies_at_create(received=True)
        key = attempt.operation_key
        real = self.store.transition

        def racing(operation_key, to_state, **kwargs):
            if operation_key == key and kwargs.get('expected_from') == 'unknown':
                real(key, 'failed', actor='another-writer', reason='its own act', expected_from='unknown')
            return real(operation_key, to_state, **kwargs)
        with mock.patch.object(self.store, 'transition', racing):
            report, calls = self.recover()
        self.assertEqual(calls, [self.lookup(attempt.conversation_id)], 'asked once')
        self.assertEqual(self.store.get(key).state, 'failed')
        self.assertEqual(report['conflicts'], [{'operationKey': key, 'expected': 'unknown', 'found': 'failed',
                                                'error': 'IllegalTransition'}])


# ---------------------------------------------------------------------------
# R21's holds, and the grant journal's report

class Holds(Fixture):
    def test_h_a_reserved_turn_is_held_not_sent(self):
        result = self.confirmed()
        real = di._mark

        def dying(integration_store, key, from_state, to_state, *args):
            if key == self.turn_key(result) and to_state == 'dispatched':
                raise te.Crash('dies with the journal reserved')
            return real(integration_store, key, from_state, to_state, *args)
        with mock.patch.object(di, '_mark', dying), self.assertRaises(te.Crash):
            self.run_attempt(result.operation_key)
        key = self.turn_key(result)
        events = self.store.events(key)
        report, calls = self.recover()
        self.assertEqual((calls, self.store.events(key)), ([], events))
        self.assertEqual([(h['operationKey'], h['code'], h['resolver']) for h in report['held']],
                         [(key, 'TURN_NOT_SENT', RR.RESOLVERS['TURN_NOT_SENT'])])
        with self.assertRaises(di.DispatchRefused) as caught:      # the run refuses with zero calls
            self.run_attempt(result.operation_key, tdl.Counting(self.server))
        self.assertEqual(caught.exception.code, 'TURN_ALREADY_SENT')
        self.assertEqual(self.server.log.count(('POST', 'events')), 0)

    def test_a_turn_of_an_ended_attempt_is_held_and_not_asked_about(self):
        result, turn = self.dies_at_message(received=False, error=OSError('lost'))
        AE.end_interrupted_attempt(self.store, result.operation_key, transport=self.server, actor=ACTOR,
                                   trigger=AE.ATTEMPT_STOPPED, dispatcher_records=[{
                                       'kind': 'run-not-started', 'code': 'TURN_RUN_NOT_STARTED',
                                       'ref': 'attempt:x#turn'}], read_artifact=self.fixture.read_artifact)
        report, calls = self.recover()
        self.assertEqual((calls, self.store.get(turn.operation_key).state), ([], 'unknown'))
        self.assertEqual([(h['code'], h['basis']) for h in report['held']],
                         [('TURN_UNRECONCILED', RR.ATTEMPT_NOT_RUNNABLE)])

    def test_a_grant_journal_is_reported_with_its_resolver_and_left(self):
        attempt = self.dies_at_create(received=False)
        journal = di.GRANT_JOURNAL_KEY.format(attempt_id=store_mod.attempt_id_for(attempt.operation_key))
        self.store.reserve(journal, {'format': 'e-01.4.2-fixture'}, actor='dispatch')
        self.store.transition(journal, 'dispatched', actor='dispatch', reason='issue')
        events = self.store.events(journal)
        report, _ = self.recover()
        self.assertEqual(report['grants'], [{'attemptId': store_mod.attempt_id_for(attempt.operation_key),
                                             'operationKey': attempt.operation_key, 'journal': journal,
                                             'state': 'dispatched', 'resolver': 'end_attempt'}])
        self.assertEqual(self.store.events(journal), events)


if __name__ == '__main__':
    unittest.main()
