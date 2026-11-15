"""Tests for the prepared D1 run driver (D1 slice C: tools/guest.py d1_run under D1_RUN_RULE; NOT RUN live).

Run from the repository root:  <tools python> -I -B -m unittest discover -s tools/tests -p test_d1_run_driver.py -v

stdlib unittest; no QEMU, no guest, no ssh, no tunnel, no network, no credential. The guest, the tunnel and the
forward are E-05.11's driver fakes (tools/tests/test_native_qualification_driver.py, loaded, not re-run); the
dispatcher's side is a fake that follows attempt_run's order (inspect, SEED, the before-message observation, the
message, the after-message observation, the turn, the after-turn observation, RESULT and the after-result
observation, the runtime stop) and records every act. Shown: the rule's PASS and its step order, with no (11d); the
native token read once and every later call sealed with it; E-01.3.2's inspection failing sends no message and ends
the attempt; each stop class ends the attempt with its dispatcher record (and runs the persisted-token search first);
a dispatcher refusal after the turn tears nothing down; a resumed result step and a resumed result path; the gate;
the read-only resolution refusing dispatches nothing; the record never holds the token.
"""
from pathlib import Path
import json
import sys
import tempfile
import types
import unittest
from unittest import mock

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import module_code  # noqa: E402
guest = module_code.load('guest', REPO / 'tools' / 'guest.py')
nqd = module_code.load('test_native_qualification_driver_fixtures',
                       REPO / 'tools' / 'tests' / 'test_native_qualification_driver.py')
NT, NS = guest.native_token_module(), nqd.NS
AE_KINDS = ('containment-stop', 'credential-stop', 'egress-stop', 'model-stop', 'provider-stop')
CID, HEX, TOKEN, FP = nqd.CID, nqd.HEX, nqd.TOKEN, nqd.FP
OPERATION = 'attempt/d1-run-fixture'
ATTEMPT = '0a1b2c3d-0000-4000-8000-00000000d1d1'


class D1Guest(nqd.FakeGuest):
    """E-05.11's fake guest with the runtime route the inspection reads."""

    def __init__(self, test):
        super().__init__(test)
        self.runtime = 'available'
        self.statuses = ['running', 'running', 'finished']

    def answer(self, method, path, body):
        if path == f'/api/conversations/{CID}/runtime':
            self.calls.append((method, path))
            return 200, {'runtime_status': self.runtime, 'can_resume': True}
        return super().answer(method, path, body)


class Outcome:
    def __init__(self, outcome, result=None, runtime=None, problems=(), end=None):
        self.outcome, self.result, self.runtime, self.problems, self.end = outcome, result, runtime, problems, end

    def to_json(self):
        return {'outcome': self.outcome, 'result': None if self.result is None else self.result.to_json(),
                'runtime': self.runtime, 'problems': list(self.problems), 'end': self.end}


class Verified:
    def to_json(self):
        return {'format': 'test', 'commit': 'c' * 40, 'bundle': {'sha256': 'b' * 64}}


class FakeDispatcher:
    """The dispatcher's side, following attempt_run's order; every act recorded in ``acts``."""

    def __init__(self, test, guest_):
        self.test, self.guest = test, guest_
        self.acts, self.ends, self.published, self.reads = [], [], [], 0
        self.prepared = {'verdict': 'PASS', 'conversation_id': CID, 'policy_digest': 'sha256:' + '1' * 64}
        self.refuse_at = None              # 'run' or 'publish': a dispatcher refusal that is not a stop
        self.turn = 'confirmed'
        self.status = 'finished'
        self.journal = None

    def prepare(self):
        self.acts.append('prepare')
        if isinstance(self.prepared, Exception):
            raise self.prepared
        return dict(self.prepared)

    def dispatch(self, transport, on_token):
        self.acts.append('dispatch')
        self.reads += 1
        on_token(NT.NativeToken(TOKEN))              # the dispatcher's one read, handed to the verifier
        secrets_ = {name: {'kind': 'StaticSecret', 'value': 'x'} for name in
                    guest.native_qualification().secrets_check.NATIVE_NAMES}
        secrets_['CLAUDE_CODE_OAUTH_TOKEN']['value'] = TOKEN
        transport('POST', '/api/conversations', {'conversation_id': CID, 'secrets': secrets_})
        return {'operation_key': OPERATION, 'attempt_id': ATTEMPT, 'conversation_id': CID, 'created': True}

    def _stop(self, records, outcome='stopped', problems=()):
        self.ends.append(('attempt-stopped', records))
        return Outcome(outcome, problems=problems, end={'classification': 'non-retryable', 'causes': ['x']})

    def run(self, key, transport, inspect, pull, observe):
        self.acts.append('run')
        problems = list(inspect(CID))
        if problems:
            return self._stop([{'kind': 'containment-stop', 'code': 'INSPECTION_FAILED', 'ref': 'a'}],
                              'inspection-failed', problems)
        self.acts.append('seed')
        records = observe('before-message')
        if records:
            return self._stop(records)
        self.acts.append('message')
        self.guest.sent = True
        records = observe('after-message')
        if records:
            return self._stop(records)
        self.test.turn_done = True
        records = observe('after-turn', status=self.status)
        if records:
            return self._stop(records)
        if self.status != 'finished':
            return Outcome('turn-not-finished')
        if self.refuse_at == 'run':
            raise guest.Refused('RESULT_PULL_FAILED', 'the pull failed')
        self.acts.append('result')
        records = observe('after-result', result=Verified())
        if records:
            return self._stop(records)
        self.acts.append('runtime-stop')
        self.journal = 'reserved'
        return Outcome('verified', result=Verified(), runtime='missing')

    def resume(self, key, transport, pull, exists, observe):
        self.acts.append('resume')
        records = observe('after-result', result=Verified())
        if records:
            return self._stop(records)
        self.journal = 'reserved'
        return Outcome('verified', result=Verified(), runtime='missing')

    def recorded(self, key):
        self.acts.append('recorded')
        return Verified()

    def state(self, key):
        return {'operation_key': OPERATION, 'attempt_id': ATTEMPT, 'conversation_id': CID, 'turn': self.turn,
                'result': self.journal, 'end': bool(self.ends)}

    def end(self, key, transport, records, trigger):
        self.acts.append(f'end {trigger}')
        self.ends.append((trigger, records))
        return {'classification': 'non-retryable' if records else 'unclassified', 'causes': []}

    def delete(self, key, transport):
        self.acts.append('delete')
        return transport('DELETE', f'/api/conversations/{CID}', None)['status']

    def read_native(self, on_token, key=None):
        self.acts.append('read-native')
        self.reads += 1
        on_token(NT.NativeToken(TOKEN))

    def publish(self, key, verified, native, observations, extra_texts, report_dir):
        self.acts.append('publish')
        self.test.assertEqual(native.fingerprint, FP)
        self.test.assertTrue(native.open)
        self.published.append((observations, extra_texts))
        if self.refuse_at == 'publish':
            raise guest.Refused('RESULT_WRITE_UNSETTLED', 'the push answer was lost')
        self.journal = 'confirmed'
        return {'outcome': 'confirmed', 'pushed': True, 'opened': True}


class D1Run(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp(prefix='aieh-d1-'))
        self.addCleanup(nqd.tg.remove_tree, self.state)
        self.guest = D1Guest(self)
        self.tunnel = nqd.FakeTunnel(self.guest)
        self.dispatcher = FakeDispatcher(self, self.guest)
        self.session = {'ports': {'tunnel': '127.0.0.1:18433'}}
        self.turn_done = False

    def wait(self, fetch, done, ceiling):
        value = fetch()
        return value, done(value)

    def run_driver(self, **kw):
        written = {}
        ctx = types.SimpleNamespace(profile=nqd.PROFILE, repo=REPO, instance_dir=lambda n: self.state / n)
        args = dict(channels=lambda rec: (self.guest.api, self.guest.facts),
                    forward=types.SimpleNamespace(status=lambda: {'held': True, 'session': self.session}),
                    tunnel=self.tunnel, host_vantage=lambda rec, pid: nqd.aq.host_snapshot(), wait=self.wait,
                    start_wait=self.wait)
        args.update(kw)

        def no_wait(seconds):
            raise AssertionError('the facts limiter waited')
        with mock.patch.object(guest, 'running_instance', side_effect=lambda c, n: (None, nqd.RECORD)), \
                mock.patch.object(guest, 'write_record', side_effect=lambda i, op, out: written.update({op: out})), \
                mock.patch.object(guest, 'FACTS_WAIT', no_wait), mock.patch.object(guest, 'log'):
            out = guest.d1_run(ctx, 'g1', self.dispatcher, **args)
        text = json.dumps(written, default=str) + json.dumps(self.dispatcher.published, default=str)
        for secret in (TOKEN, TOKEN[len(NS.PREFIX):]):
            self.assertNotIn(secret, text)
        self.assertEqual(written['d1-run']['result'], out['result'])
        return out

    def verdicts(self, out):
        return {s['step'].split(' ', 1)[0]: s['verdict'] for s in out['steps']}

    def step(self, out, key):
        found = [s for s in out['steps'] if s['step'] == guest.D1_STEPS[key]]
        self.assertEqual(len(found), 1, key)
        return found[0]

    def test_the_rule_passes_and_publishes(self):
        out = self.run_driver()
        self.assertEqual(out['result'], 'PASS', [(s['step'][:6], s['verdict'], s.get('detail')) for s in out['steps']
                                                 if s['verdict'] != 'PASS'])
        self.assertEqual(list(self.verdicts(out)), ['(0)', '(1)', '(1a)', '(2)', '(3)', '(4)', '(5)', '(5a)', '(5b)',
                                                    '(5c)', '(6)', '(7a)', '(7b)', '(7c)', '(7d)', '(7e)', '(7h)', '(7f)',
                                                    '(7g)', '(8a)', '(8)', '(9)', '(10)', '(10a)', '(10b)', '(11)', '(12)'])
        self.assertNotIn('(11d)', json.dumps([s['step'] for s in out['steps']]))
        self.assertIn('(11d)', guest.D1_RUN_RULE)             # named, and excluded, by the rule
        self.assertEqual(self.dispatcher.acts, ['prepare', 'dispatch', 'run', 'seed', 'message', 'result',
                                                'runtime-stop', 'delete', 'publish'])
        self.assertEqual(self.dispatcher.reads, 1)              # one read of the native entry for the attempt
        create = self.guest.seals.index(('POST', '/api/conversations', True))
        self.assertTrue(all(sealed for _, _, sealed in self.guest.seals[create:]))
        self.assertFalse(any(sealed for _, _, sealed in self.guest.seals[:create]))
        self.assertEqual((out['disposition'], out['guest_may_be_destroyed']), ('published', True))
        self.assertEqual(out['interruption'], 'none: no interruption occurred')
        self.assertEqual(out['native_token']['fingerprint'], FP)
        inspection = self.step(out, '3')['detail']
        self.assertEqual(inspection['selected_profile'], {'acp_server': 'claude-code', 'acp_model': 'claude-sonnet-5'})
        self.assertEqual(inspection['runtime_identity']['conversation_hex'], HEX)
        self.assertEqual({c['verdict'] for c in out['clauses']}, {'PASS', 'OFFLINE'})
        observations, extra = self.dispatcher.published[0]
        self.assertEqual(observations['interruption'], 'none: no interruption occurred')
        self.assertEqual(observations['events']['agent_ran_its_tests'], 'not observed')
        self.assertEqual(list(extra), ['run-record-draft'])
        self.assertEqual(self.step(out, '11')['detail']['verdict'], 'not-found')

    def test_the_inspection_failing_sends_no_message_and_ends_the_attempt(self):
        for name, change in (('a runtime not available', lambda: setattr(self.guest, 'runtime', 'starting')),
                             ('another model', lambda: setattr(self.guest, 'agent',
                                                               dict(self.guest.agent, acp_model='claude-opus-5')))):
            with self.subTest(name):
                self.setUp()
                change()
                out = self.run_driver()
                self.assertEqual(self.step(out, '3')['verdict'], 'FAIL')
                self.assertNotIn('message', self.dispatcher.acts)
                self.assertFalse(self.guest.sent)
                self.assertEqual(self.dispatcher.ends[0][1][0]['code'], 'INSPECTION_FAILED')
                self.assertEqual(out['disposition'], 'ended')
                self.assertIn('delete', self.dispatcher.acts)         # an ended attempt is torn down
                self.assertNotIn('publish', self.dispatcher.acts)
                self.assertEqual(out['result'], 'FAIL')

    def test_a_selected_profile_not_named_is_unknown_never_a_stop(self):
        self.guest.agent = {'kind': 'ACPAgent'}
        out = self.run_driver()
        self.assertEqual(self.step(out, '3')['verdict'], 'UNKNOWN')
        self.assertIn('message', self.dispatcher.acts)
        self.assertEqual(out['result'], 'UNKNOWN')

    def test_each_stop_ends_the_attempt_with_its_record(self):
        cases = {
            'a connection elsewhere while the turn runs': (
                lambda: setattr(self.guest, 'during', nqd.aq.snapshot(rows=[nqd.aq.TO_ENDPOINT, nqd.aq.TO_ELSEWHERE])),
                'egress-stop', 'after-message'),
            'a model outside the record': (
                lambda: self.guest.probe['after']['transcript']['models'].update({'claude-instant-1': 1}),
                'model-stop', 'after-turn'),
            'the token echoed in an answer': (lambda: setattr(self.guest, 'echo_token', True), 'credential-stop',
                                              'before-message'),
        }
        for name, (change, kind, phase) in cases.items():
            with self.subTest(name):
                self.setUp()
                change()
                out = self.run_driver()
                self.assertEqual(out['result'], 'FAIL')
                trigger, records = self.dispatcher.ends[0]
                self.assertEqual(trigger, 'attempt-stopped')
                self.assertIn(kind, [r['kind'] for r in records])
                self.assertTrue(all(r['ref'] == f'attempt:{ATTEMPT}#{phase}' for r in records), records)
                self.assertNotIn('publish', self.dispatcher.acts)
                self.assertNotIn('result', self.dispatcher.acts)
                self.assertEqual(out['disposition'], 'ended')
                self.assertEqual(self.step(out, '7e')['verdict'] in ('PASS', 'UNKNOWN', 'FAIL'), True)  # it ran

    def test_a_turn_that_did_not_finish_is_ended_through_e_05_8(self):
        self.dispatcher.status = 'error'
        out = self.run_driver()
        self.assertEqual(self.dispatcher.ends, [('conversation-ended', [])])
        self.assertEqual(self.step(out, '6')['verdict'], 'FAIL')
        self.assertNotIn('result', self.dispatcher.acts)
        self.assertEqual(out['disposition'], 'ended')

    def test_a_refusal_after_the_turn_tears_nothing_down(self):
        self.dispatcher.refuse_at = 'run'
        out = self.run_driver()
        self.assertEqual(out['disposition'], 'held-for-resume')
        self.assertFalse(out['guest_may_be_destroyed'])
        self.assertNotIn('delete', self.dispatcher.acts)
        self.assertEqual(self.dispatcher.ends, [])
        self.assertNotIn(('DELETE', f'/api/conversations/{CID}'), self.guest.calls)
        self.assertEqual(out['refusal'], {'at': 'run', 'code': 'RESULT_PULL_FAILED'})

    def test_a_refused_result_path_is_held_for_resume(self):
        self.dispatcher.refuse_at = 'publish'
        out = self.run_driver()
        self.assertEqual((self.step(out, '12')['verdict'], out['disposition']), ('FAIL', 'held-for-resume'))
        self.assertFalse(out['guest_may_be_destroyed'])

    def test_the_resumed_result_step_and_result_path(self):
        self.guest.created = True
        out = self.run_driver(resume=OPERATION)
        self.assertEqual(self.dispatcher.acts, ['prepare', 'read-native', 'resume', 'delete', 'publish'])
        self.assertEqual(self.dispatcher.reads, 1)
        self.assertEqual(out['disposition'], 'published')
        self.assertEqual(out['resumed'], OPERATION)
        self.setUp()
        self.dispatcher.journal = 'dispatched'
        out = self.run_driver(resume=OPERATION)
        self.assertEqual(self.dispatcher.acts, ['prepare', 'read-native', 'recorded', 'publish'])
        self.assertNotIn('dispatch', self.dispatcher.acts)

    def test_an_ended_attempt_is_not_resumed(self):
        self.dispatcher.ends.append(('attempt-stopped', []))
        out = self.run_driver(resume=OPERATION)
        self.assertEqual(out['refusal']['code'], 'REFUSED')
        self.assertNotIn('publish', self.dispatcher.acts)

    def test_the_read_only_resolution_refusing_dispatches_nothing(self):
        for prepared in ({'verdict': 'FAIL', 'conversation_id': CID, 'checks': {'policy_digest': False}},
                         guest.Refused('REFUSED', 'the manifest is not promoted')):
            with self.subTest(prepared=str(prepared)[:40]):
                self.setUp()
                self.dispatcher.prepared = prepared
                out = self.run_driver()
                self.assertEqual(self.dispatcher.acts, ['prepare'])
                self.assertEqual(self.guest.calls, [])
                self.assertEqual(self.tunnel.census_calls, [])
                self.assertEqual((out['result'], out['disposition']), ('FAIL', 'not-dispatched'))

    def test_a_failed_census_before_the_dispatch_dispatches_nothing(self):
        self.tunnel.census_verdicts = ['FAIL']
        out = self.run_driver()
        self.assertNotIn('dispatch', self.dispatcher.acts)
        self.assertEqual(self.dispatcher.reads, 0)
        self.assertEqual(out['result'], 'FAIL')

    def test_a_stop_at_the_teardown_ends_the_attempt_before_the_result_path(self):
        self.tunnel.late_lines = [nqd.log_line(event='connection', conn=9, target='example.org:443',
                                               decision='admitted', reason=None, end='client-closed')]
        out = self.run_driver()
        self.assertIn(('attempt-stopped', [{'kind': 'egress-stop', 'code': 'OTHER_TARGET',
                                            'ref': f'attempt:{ATTEMPT}#teardown'}]), self.dispatcher.ends)
        self.assertNotIn('publish', self.dispatcher.acts)
        self.assertEqual(out['disposition'], 'ended')


class StopRecords(unittest.TestCase):
    def test_every_stop_maps_to_a_dispatcher_kind_in_its_grammar(self):
        texts = list(guest.NATIVE_STOPS.values()) + [guest.ACP_CONFIRMATION_STOP, 'an npx or npm process',
                                                     'a process outside the container\'s lineage (entered)',
                                                     'something no entry names']
        for text in texts:
            record = guest.d1_stop_record({'stop': text}, ATTEMPT, 'after-turn')
            self.assertIn(record['kind'], AE_KINDS, text)
            self.assertRegex(record['code'], r'^[A-Z][A-Z0-9_]{0,63}$')
            self.assertRegex(record['ref'], r'^[A-Za-z0-9._:/@#-]{1,256}$')
        self.assertEqual(guest.d1_stop_record({'stop': 'something no entry names'}, 'a', 'p')['kind'],
                         'containment-stop')
        self.assertEqual(guest.d1_stop_record({'stop': guest.NATIVE_STOPS['provider-after']}, 'a', 'p')['kind'],
                         'provider-stop')

    def test_the_clauses_are_judged_by_their_steps(self):
        steps = [{'step': v, 'verdict': 'PASS'} for v in guest.D1_STEPS.values()]
        verdicts = {c['clause']: c['verdict'] for c in guest.d1_clause_verdicts(steps)}
        self.assertEqual(set(verdicts.values()), {'PASS', 'OFFLINE'})
        steps[[s['step'] for s in steps].index(guest.D1_STEPS['3'])]['verdict'] = 'FAIL'
        judged = guest.d1_clause_verdicts(steps)
        self.assertEqual({c['verdict'] for c in judged if c['leaf'] == 'E-01.3.2'}, {'FAIL'})
        self.assertEqual(guest.d1_clause_verdicts([])[0]['verdict'], 'UNKNOWN')

    def test_the_event_facts_hold_no_event_text(self):
        events = [{'kind': guest.ACP_TOOL_CALL_KIND, 'title': 'Bash', 'raw': 'python -m unittest discover -s tests '
                   'and a secret-looking sk-ant-oat01-xyz'},
                  {'kind': 'MessageEvent', 'text': 'uses claude-sonnet-5'},
                  {'kind': 'ConversationErrorEvent', 'code': 'ACPPromptError'}]
        facts = guest.d1_event_facts(events)
        self.assertEqual(facts, {'agent_ran_its_tests': 'observed', 'test_command_events': 1,
                                 'model_identifiers_in_events': ['claude-sonnet-5'],
                                 'error_events': ['ACPPromptError']})


if __name__ == '__main__':
    unittest.main()
