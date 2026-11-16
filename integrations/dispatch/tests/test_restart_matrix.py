"""The restart matrix (plan leaf E-01.4.2, slice 5c), offline, against the fixture catalog's cited core.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_restart_matrix.py -v

The rows, their transport events and their expected values are the table committed before this test first ran
(``integrations/dispatch/README.md``, "The restart matrix"); ``RuleBinding`` binds this module's expected counts to
that table. Each row is a native D1 attempt (E-05.9's fixture, as slices 5a and 5b use it) whose transport is ``Wire``
around ``AgentServerCore``: the wire forwards every request, except the transport events the row lists (a request
that never arrives: the core is not called; a response withheld: the core answered and the caller gets an exception),
and never answers itself. No test knob is used: every answer is the core's, from the catalog.

**The restart is a simulated death, not a process restart**: the act's continuation is dropped (``te.Crash``, a
``BaseException``), the dispatcher lock released as the act unwinds, and the integration store closed and reopened from
its file before ``recover`` runs. The real-process facts it rests on are E-01.1.2's crash matrix and slice 5a's
condition 2 (``test_dispatcher_lock.KilledHolder``); the live restart is E-01.6's.

In every row (``every_row``): at most one ``POST /api/conversations`` per operation key and at most one conversation
holding a message, by the core's call log and state; ``recover`` made GETs only; a second ``recover`` leaves the
store's canonical dump unchanged; the row's create and message counts are the table's.
"""
from pathlib import Path
import contextlib
import dataclasses
import importlib.util
import re
import sys
import unittest
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
tar, te, di, AE, store_mod, AR, cc = tdl.tar, tdl.te, tdl.di, tdl.AE, tdl.store_mod, tdl.AR, tdl.cc
RR = _load('restart_recovery', HERE.parent / 'restart_recovery.py')
AC = cc.AC

ACTOR = 'e-01.4.2-matrix'
CREATE = ('POST', '/api/conversations')
EPOCH_REASON = 'restore epoch: outcome uncertain after restore'
FOUND_REASON, NOT_FOUND_REASON = 'reconciled: observed in the external system', \
    'reconciled: not present in the external system'

# The table's two last columns, as committed (README "The restart matrix"): creates and messages received.
COUNTS = {'A': ('1', '1'), 'B': ('1', '1'), 'C': ('1', '1'), 'D': ('1', '1'), 'E': ('1', '1'), 'F': ('1', '1'),
          'G': ('1', '0'), 'H': ('1', '0'), 'I': ('1', '0'), 'J': ('1', '1'), 'K': ('1', '1'), 'L': ('1', '1'),
          "C'": ('1', '1'), "D'": ('1', '1'), "J'": ('1', '1'), 'Z': ('0 (as C); 1 (as D)', '0')}


def setUpModule():
    tar.setUpModule()


def tearDownModule():
    with contextlib.suppress(FileNotFoundError):
        tar.tearDownModule()


class Wire:
    """The transport between the dispatcher and the core. It forwards each request to the core, except the transport
    events of PLAN, consumed in order: ``('drop', method, path, exc)`` (the request never arrives: the core is not
    called, so the call log has no entry; EXC raised), ``('withhold', ...)`` (the core receives and answers; EXC
    raised instead of the answer) and ``('pass', method, path, None)`` (forwarded: a marker that orders the next
    event). It never makes an answer. ``log`` holds (phase, method, path) of every request it was given."""

    def __init__(self, core):
        self.core, self.plan, self.log, self.events, self.phase = core, [], [], [], 'act'

    def __call__(self, method, path, body=None, **kwargs):
        self.log.append((self.phase, method, path))
        if self.plan and (self.plan[0][1], self.plan[0][2]) == (method, path):
            kind, _, _, exc = self.plan.pop(0)
            if kind == 'drop':
                self.events.append(('never arrives', method, path))
                raise exc
            answer = self.core(method, path, body, **kwargs)
            if kind == 'withhold':
                self.events.append(('response withheld', method, path))
                raise exc
            return answer
        return self.core(method, path, body, **kwargs)


class Matrix(tar.Scratch):
    """One row: a native D1 attempt on the core, its death, the restart, ``recover``, then the row's act."""
    category = 'integration'

    def setUp(self):
        super().setUp()
        self.fixture = tar.attempt_fixture(self)
        self.core = AC.AgentServerCore(scratch=self.tmp / 'agentfixture')
        self.addCleanup(self.core.close)
        self.wire = Wire(self.core)
        self.fixture.server = self.wire
        self.store = self.fixture.store
        resolved = self.fixture.resolve_d1(self.fixture.manifest)
        self.base, _ = self.demo(work_id=resolved.work_id, change=AR._design(resolved)['change'],
                                 repository=resolved.repository)
        self.base = dataclasses.replace(self.base, design_commit=AR._design(resolved)['commit'])
        self.observe = None

    # -- the acts ------------------------------------------------------------------------------------------------
    def dispatch(self):
        return self.fixture.run_native(self.wire, manifest=self.fixture.manifest)

    def run_attempt(self, key):
        def observe(phase, **facts):
            return self.observe(phase) if self.observe else ()
        return AR.run_attempt(self.store, key, transport=self.wire, base=self.base, actor=ACTOR,
                              inspect=lambda cid: (), pull=lambda name: self.fail('no pull expected'), observe=observe,
                              ceiling_s=0, clock=lambda: 0.0, wait=lambda s: self.fail('no wait expected'),
                              read_artifact=self.fixture.read_artifact)

    def result_step(self, key):
        return AR.resume_result(self.store, key, transport=self.wire, base=self.base, actor=ACTOR,
                                pull=lambda name: self.fail('no pull expected'), exists=lambda name: False,
                                read_artifact=self.fixture.read_artifact)

    def end(self, key):
        attempt_id = store_mod.attempt_id_for(key)
        return AE.end_interrupted_attempt(self.store, key, transport=self.wire, actor=ACTOR,
                                          trigger=AE.ATTEMPT_STOPPED, dispatcher_records=[{
                                              'kind': 'run-not-started', 'code': 'TURN_RUN_NOT_STARTED',
                                              'ref': f'attempt:{attempt_id}#turn'}],
                                          read_artifact=self.fixture.read_artifact)

    def refused(self, code, act):
        with self.assertRaises(di.DispatchRefused) as caught:
            act()
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        return caught.exception

    # -- the restart ---------------------------------------------------------------------------------------------
    def restart(self):
        """The simulated death's restart: the store closed and reopened from its file (the lock was released as the
        act unwound)."""
        path = Path(self.store.path)
        self.store.close()
        self.fixture.store = self.store = store_mod.open_store(path)
        self.addCleanup(self.store.close)

    def restore(self):
        """The store restored from a backup taken now: a restore epoch open (as slice 5b's tests restore it)."""
        path = Path(self.store.path)
        manifest = self.store.backup(actor='owner')
        self.store.close()
        store_mod.restore_store(path, path.parent / 'backups' / (manifest['backup_file'] + '.manifest.json'),
                                actor='owner')
        self.fixture.store = self.store = store_mod.open_store(path)
        self.addCleanup(self.store.close)
        self.assertEqual(len(self.store.open_epochs()), 1)

    def recover(self):
        before = len(self.wire.log)
        self.wire.phase = 'recover'
        try:
            report = RR.recover(self.store, transport=self.wire, actor=ACTOR, read_artifact=self.fixture.read_artifact)
        finally:
            self.wire.phase = 'act'
        calls = [(m, p) for _, m, p in self.wire.log[before:]]
        self.assertEqual([m for m, _ in calls if m != 'GET'], [], 'recover made GETs only')
        return report, calls

    # -- reading the store ---------------------------------------------------------------------------------------
    def typed(self):
        return [a for a in self.store.attempts() if a.operation_key.startswith(store_mod.KEY_PREFIX)]

    def ordinal(self, key):
        return self.store.attempt_identity(key).identity.ordinal

    def only(self, state=None):
        (attempt,) = self.typed()
        if state is not None:
            self.assertEqual(attempt.state, state)
        return attempt

    def turn(self, key):
        return self.store.get(AR.TURN_KEY.format(attempt_id=store_mod.attempt_id_for(key)))

    def moves(self, key, since):
        return [(e.from_state, e.to_state, e.reason) for e in self.store.events(key)[since:]]

    @staticmethod
    def lookup(cid):
        return ('GET', f'/api/conversations/{cid}')

    @staticmethod
    def read_events(cid):
        return [('GET', f'/api/conversations/{cid}'), ('GET', f'/api/conversations/{cid}/events/search')]

    # -- every row -----------------------------------------------------------------------------------------------
    def every_row(self, row, report):
        creates = {}
        for _, _, body in self.core.creates:
            creates[body['conversation_id']] = creates.get(body['conversation_id'], 0) + 1
        self.assertTrue(all(n <= 1 for n in creates.values()), 'at most one create per operation key')
        holding = [cid for cid, held in self.core.conversations.items() if held.get('events')]
        self.assertLessEqual(len(holding), 1, 'at most one conversation holds a message')
        self.assertEqual((str(len(self.core.creates)), str(len(self.core.messages()))), COUNTS[row])
        dump = self.store.canonical_dump()
        self.recover()
        self.assertEqual(self.store.canonical_dump(), dump, 'a second recover changes nothing')
        self.assertEqual(report['conflicts'], [])

    def then_run(self, key, ordinal):
        """The run (the table's "run"): the inspection, SEED, the message, the wait (finished), then RESULT, refused by
        the core's label: RESULT_COMMAND_FAILED, the turn confirmed."""
        self.assertEqual(self.ordinal(key), ordinal)
        self.refused('RESULT_COMMAND_FAILED', lambda: self.run_attempt(key))
        self.assertEqual(self.turn(key).state, 'confirmed')
        cid = store_mod.conversation_id_for(key)
        self.assertEqual(self.core.conversations[cid]['execution_status'], 'finished')
        self.assertEqual(len(self.core.messages(cid)), 1)

    def then_result_step(self, key):
        """The result step (the table's): the conversation finished, its runtime available, exactly one RESULT,
        refused by the label: RESULT_COMMAND_FAILED."""
        before = len(self.wire.log)
        self.refused('RESULT_COMMAND_FAILED', lambda: self.result_step(key))
        cid = store_mod.conversation_id_for(key)
        self.assertEqual([(m, p) for _, m, p in self.wire.log[before:]], [
            ('GET', f'/api/conversations/{cid}'), ('GET', f'/api/conversations/{cid}/runtime'),
            ('POST', f'/api/conversations/{cid}/bash/execute_bash_command')])
        self.assertEqual(self.turn(key).state, 'confirmed')

    # -- the deaths ----------------------------------------------------------------------------------------------
    def dies_before_the_reservation(self):
        with mock.patch.object(self.store, 'reserve_attempt', side_effect=te.Crash('dies before the reservation')), \
                self.assertRaises(te.Crash):
            self.dispatch()
        self.assertEqual(self.typed(), [])

    def dies_reserved(self):
        with mock.patch.object(di, 'create_workspace', side_effect=te.Crash('dies reserved')), \
                self.assertRaises(te.Crash):
            self.dispatch()
        return self.only('reserved')

    def dies_at_create(self, kind):
        self.wire.plan = [(kind, *CREATE, te.Crash(f'dies: the create {kind}'))]
        with self.assertRaises(te.Crash):
            self.dispatch()
        return self.only('dispatched')

    def dies_at_message(self, plan, death=te.Crash):
        """A confirmed attempt whose run is ended at the message by PLAN (the message's path filled in)."""
        result = self.dispatch()
        cid = result.conversation_id
        paths = {'events': f'/api/conversations/{cid}/events', 'conversation': f'/api/conversations/{cid}'}
        self.wire.plan = [(kind, method, paths[name], exc) for kind, method, name, exc in plan]
        with self.assertRaises(death):
            self.run_attempt(result.operation_key)
        self.assertEqual(self.wire.plan, [], 'every planned transport event happened')
        return result


class Rows(Matrix):
    def test_a_dies_before_the_reservation(self):
        self.dies_before_the_reservation()
        self.restart()
        report, calls = self.recover()
        self.assertEqual((calls, report['entries'], report['held']), ([], [], []))
        result = self.dispatch()
        self.assertEqual((result.created, self.store.get(result.operation_key).state), (True, 'confirmed'))
        self.then_run(result.operation_key, 1)
        self.every_row('A', report)

    def test_b_dies_reserved(self):
        k1 = self.dies_reserved()
        self.restart()
        report, calls = self.recover()
        self.assertEqual(calls, [self.lookup(k1.conversation_id)])
        self.assertEqual(self.moves(k1.operation_key, 1), [('reserved', 'failed', RR.REASON_NOT_SENT)])
        self.assertEqual(report['held'], [])
        result = self.dispatch()
        self.then_run(result.operation_key, 2)
        self.assertEqual(self.core.creates[0][2]['conversation_id'], result.conversation_id)
        self.every_row('B', report)

    def test_c_dies_dispatched_its_create_not_received(self):
        k1 = self.dies_at_create('drop')
        self.assertEqual(self.core.creates, [])
        self.restart()
        report, calls = self.recover()
        self.assertEqual(calls, [self.lookup(k1.conversation_id)])
        self.assertEqual(self.moves(k1.operation_key, 2), [('dispatched', 'unknown', RR.REASON_CREATE_UNKNOWN),
                                                           ('unknown', 'failed', NOT_FOUND_REASON)])
        result = self.dispatch()
        self.then_run(result.operation_key, 2)
        self.every_row('C', report)

    def test_d_dies_dispatched_its_create_received(self):
        k1 = self.dies_at_create('withhold')
        self.restart()
        report, calls = self.recover()
        self.assertEqual(calls, [self.lookup(k1.conversation_id)])
        self.assertEqual(self.moves(k1.operation_key, 2), [('dispatched', 'unknown', RR.REASON_CREATE_UNKNOWN),
                                                           ('unknown', 'confirmed', FOUND_REASON)])
        before, typed = len(self.wire.log), self.typed()
        self.refused('PRIOR_ATTEMPT_NOT_ENDED', self.dispatch)
        self.assertEqual([(m, p) for _, m, p in self.wire.log[before:]], [self.lookup(k1.conversation_id)])
        self.assertEqual(self.typed(), typed, 'nothing reserved')
        self.then_run(k1.operation_key, 1)
        self.every_row('D', report)

    def test_e_the_creates_answer_is_lost(self):
        self.wire.plan = [('withhold', *CREATE, TimeoutError('no answer'))]
        with self.assertRaises(TimeoutError):
            self.dispatch()
        k1 = self.only('unknown')
        self.assertEqual(self.store.events(k1.operation_key)[-1].reason, 'create-unanswered')
        self.restart()
        report, calls = self.recover()
        self.assertEqual(calls, [self.lookup(k1.conversation_id)])
        self.assertEqual(self.moves(k1.operation_key, -1), [('unknown', 'confirmed', FOUND_REASON)])
        self.then_run(k1.operation_key, 1)
        self.every_row('E', report)

    def test_f_dies_confirmed_before_the_run(self):
        result = self.dispatch()
        self.restart()
        report, calls = self.recover()
        self.assertEqual((calls, report['entries']), ([], []))
        self.then_run(result.operation_key, 1)
        self.every_row('F', report)

    def test_g_dies_after_seed_before_the_turn_journal(self):
        result = self.dispatch()
        key = result.operation_key
        def dying(phase):
            if phase == 'before-message':
                raise te.Crash('dies after SEED, before the turn journal')
            return ()
        self.observe = dying
        with self.assertRaises(te.Crash):
            self.run_attempt(key)
        self.observe = None
        self.assertIsNone(self.turn(key))
        self.assertTrue(self.core.conversations[result.conversation_id]['seeded'])
        self.restart()
        report, calls = self.recover()
        self.assertEqual((calls, report['entries'], report['held']), ([], [], []))
        self.refused('SEED_FAILED', lambda: self.run_attempt(key))
        self.assertEqual(self.core.calls[-1][1], f'/api/conversations/{result.conversation_id}/bash/'
                                                 'execute_bash_command')
        self.assertIsNone(self.turn(key))
        self.assertEqual(self.end(key)['classification'], AE.INTERRUPTION)
        after, calls = self.recover()
        self.assertEqual((after['held'], after['ended'], calls), ([], [], []))
        self.every_row('G', report)

    def test_h_dies_with_the_turn_journal_reserved(self):
        result = self.dispatch()
        key, turn_key = result.operation_key, AR.TURN_KEY.format(attempt_id=store_mod.attempt_id_for(
            result.operation_key))
        real = di._mark

        def dying(integration_store, k, from_state, to_state, *args):
            if k == turn_key and to_state == 'dispatched':
                raise te.Crash('dies with the journal reserved')
            return real(integration_store, k, from_state, to_state, *args)
        with mock.patch.object(di, '_mark', dying), self.assertRaises(te.Crash):
            self.run_attempt(key)
        self.restart()
        report, calls = self.recover()
        self.assertEqual(calls, [])
        self.assertEqual([(h['operationKey'], h['code']) for h in report['held']], [(turn_key, 'TURN_NOT_SENT')])
        before = len(self.wire.log)
        self.refused('TURN_ALREADY_SENT', lambda: self.run_attempt(key))
        self.assertEqual(self.wire.log[before:], [], 'refused with zero calls')
        self.end(key)
        after, calls = self.recover()
        self.assertEqual((after['held'], calls), ([], []))
        self.assertEqual([(e['operationKey'], e['state']) for e in after['ended']], [(turn_key, 'reserved')])
        self.every_row('H', report)

    def test_i_dies_with_the_turn_dispatched_its_message_not_received(self):
        result = self.dies_at_message([('drop', 'POST', 'events', te.Crash('dies: the message never arrives'))])
        key, cid = result.operation_key, result.conversation_id
        self.assertEqual(self.turn(key).state, 'dispatched')
        self.restart()
        report, calls = self.recover()
        self.assertEqual(calls, self.read_events(cid))
        turn_key = self.turn(key).operation_key
        self.assertEqual((self.turn(key).state, [(h['operationKey'], h['code']) for h in report['held']]),
                         ('unknown', [(turn_key, 'TURN_UNRECONCILED')]))
        self.refused('TURN_NOT_CONFIRMED', lambda: self.result_step(key))
        self.end(key)
        after, calls = self.recover()
        self.assertEqual((after['held'], calls), ([], []))
        self.assertEqual([(e['operationKey'], e['state']) for e in after['ended']], [(turn_key, 'unknown')])
        self.every_row('I', report)

    def test_j_dies_with_the_turn_dispatched_its_message_received(self):
        result = self.dies_at_message([('withhold', 'POST', 'events', te.Crash('dies: the answer withheld'))])
        key, cid = result.operation_key, result.conversation_id
        self.assertEqual(self.turn(key).state, 'dispatched')
        self.restart()
        report, calls = self.recover()
        self.assertEqual(calls, self.read_events(cid))
        self.assertEqual(self.moves(self.turn(key).operation_key, 2), [
            ('dispatched', 'unknown', RR.REASON_TURN_UNKNOWN), ('unknown', 'confirmed', 'reconciled-from-events')])
        self.assertEqual(report['held'], [])
        self.then_result_step(key)
        self.every_row('J', report)

    def test_k_the_messages_answer_is_lost_then_a_death(self):
        result = self.dies_at_message([('withhold', 'POST', 'events', OSError('the answer was lost')),
                                       ('drop', 'GET', 'conversation', te.Crash('dies at the next request'))])
        key, cid = result.operation_key, result.conversation_id
        turn = self.turn(key)
        self.assertEqual((turn.state, self.store.events(turn.operation_key)[-1].reason), ('unknown', 'no-answer'))
        self.restart()
        report, calls = self.recover()
        self.assertEqual(calls, self.read_events(cid))
        self.assertEqual(self.moves(turn.operation_key, -1), [('unknown', 'confirmed', 'reconciled-from-events')])
        self.then_result_step(key)
        self.every_row('K', report)

    def test_l_dies_with_the_turn_confirmed_during_the_wait(self):
        result = self.dies_at_message([('pass', 'POST', 'events', None),
                                       ('drop', 'GET', 'conversation', te.Crash('dies during the wait'))])
        key = result.operation_key
        self.assertEqual(self.turn(key).state, 'confirmed')
        self.restart()
        report, calls = self.recover()
        self.assertEqual((calls, report['entries']), ([], []))
        self.then_result_step(key)
        self.every_row('L', report)

    def test_c_prime_as_c_then_a_restore(self):
        k1 = self.dies_at_create('drop')
        self.restore()
        report, calls = self.recover()
        self.assertTrue(report['epoch'])
        self.assertEqual(calls, [self.lookup(k1.conversation_id)])
        self.assertEqual(self.moves(k1.operation_key, 2), [('dispatched', 'unknown', EPOCH_REASON),
                                                           ('unknown', 'failed', NOT_FOUND_REASON)])
        self.assertEqual(len(self.store.close_restore_epoch(actor='owner')), 1)
        result = self.dispatch()
        self.then_run(result.operation_key, 2)
        self.every_row("C'", report)

    def test_d_prime_as_d_then_a_restore(self):
        k1 = self.dies_at_create('withhold')
        self.restore()
        report, calls = self.recover()
        self.assertTrue(report['epoch'])
        self.assertEqual(calls, [self.lookup(k1.conversation_id)])
        self.assertEqual(self.moves(k1.operation_key, 2), [('dispatched', 'unknown', EPOCH_REASON),
                                                           ('unknown', 'confirmed', FOUND_REASON)])
        self.assertEqual(len(self.store.close_restore_epoch(actor='owner')), 1)
        self.refused('PRIOR_ATTEMPT_NOT_ENDED', self.dispatch)
        self.then_run(k1.operation_key, 1)
        self.every_row("D'", report)

    def test_j_prime_as_j_then_a_restore(self):
        result = self.dies_at_message([('withhold', 'POST', 'events', te.Crash('dies: the answer withheld'))])
        key, cid = result.operation_key, result.conversation_id
        self.restore()
        report, calls = self.recover()
        self.assertTrue(report['epoch'])
        self.assertEqual(calls, self.read_events(cid))
        self.assertEqual(self.moves(self.turn(key).operation_key, 2), [
            ('dispatched', 'unknown', EPOCH_REASON), ('unknown', 'confirmed', 'reconciled-from-events')])
        self.assertEqual(len(self.store.close_restore_epoch(actor='owner')), 1)
        self.then_result_step(key)
        self.every_row("J'", report)

    def test_z_another_holder_has_the_lock(self):
        for kind, creates in (('drop', 0), ('withhold', 1)):
            with self.subTest(kind=kind):
                case = Rows('test_z_another_holder_has_the_lock')
                case.setUp()
                self.addCleanup(case.doCleanups)
                case.dies_at_create(kind)
                case.restart()
                dump, before = case.store.canonical_dump(), len(case.wire.log)
                with tdl.held_by_handle(case.store.path):
                    case.refused('DISPATCHER_BUSY', case.recover)
                self.assertEqual((case.store.canonical_dump(), case.wire.log[before:]), (dump, []))
                self.assertEqual((len(case.core.creates), len(case.core.messages())), (creates, 0))
        self.assertEqual(COUNTS['Z'], ('0 (as C); 1 (as D)', '0'))


class RuleBinding(unittest.TestCase):
    """The expected counts here are the README's committed table's, and no row of it is untested."""
    category = 'unit'

    def test_the_counts_are_the_committed_tables(self):
        text = (HERE.parent / 'README.md').read_text(encoding='utf-8')
        start = text.index('## The restart matrix (E-01.4.2, slice 5c)')
        table = text[start:text.index('\n## ', start + 5)]
        rows = {}
        for line in table.splitlines():
            match = re.match(r"\| ([A-L]|[CDJ]'|Z) \|", line)
            if match:
                cells = [c.strip() for c in line[1:-1].split('|')]
                rows[cells[0]] = (cells[-2], cells[-1])
        self.assertEqual(rows, COUNTS)
        tested = {name.split('_')[1].upper() + ("'" if '_prime_' in name else '')
                  for name in dir(Rows) if name.startswith('test_')}
        self.assertEqual(tested, set(COUNTS))


if __name__ == '__main__':
    unittest.main()
