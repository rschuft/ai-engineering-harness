"""The native bytes guard of plan leaf E-01.8 (the review's item 3; the I1 integration design's R11: a live record is
byte for byte what it was), offline: a live-bound attempt, on the checked-in strong-windows-qemu-whpx declaration,
run end to end on the fixture catalog's in-process core (dispatch, the launch gate, the attempt run with the probe's
own delivery, the intake, the result path to E-05.4's in-process Gitea fakes), and an ended one: no record, report or
pull request body carries an ``authority`` key. It lives here, not beside the dispatch modules, because its RESULT and
its answer copies are outside what the dispatch suite's read binding admits of the in-process core.
"""
import dataclasses
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import fixture_support as S

CATEGORY = 'integration'

REPO = S.REPO
HERE = S.DISPATCH_TESTS
TA = S.load('test_authority', S.DISPATCH_TESTS / 'test_authority.py')
di, AR, AE, LG, RP, NT, ci = TA.di, TA.AR, TA.AE, TA.LG, TA.RP, TA.NT, TA.ci
tar, provider, ACTOR, SOURCE = TA.tar, TA.provider, TA.ACTOR, TA.SOURCE
_load = S.load


def authority_keys(value, where='$'):
    """Every path in VALUE (parsed JSON) at which a key ``authority`` stands."""
    if isinstance(value, dict):
        return [f'{where}.authority'] * ('authority' in value) + [
            p for k, v in value.items() for p in authority_keys(v, f'{where}.{k}')]
    if isinstance(value, list):
        return [p for n, v in enumerate(value) for p in authority_keys(v, f'{where}[{n}]')]
    return []


class LiveWire:
    """The in-process core as a live transport (no declared authority) with the probe's own exchange delivery
    (``transport.pinned_delivery``), as the live transport delivers in the guest."""

    def __init__(self, core, exchange):
        self.core, self.exchange = core, Path(exchange)

    def __call__(self, method, path, body=None, deliver=None):
        answer = dict(self.core(method, path, body))
        if deliver is not None:
            fixture_transport = sys.modules.get('agentfixture_transport') or _load(
                'agentfixture_transport', REPO / 'integrations' / 'agentfixture' / 'transport.py')
            rule, limit = fixture_transport.pinned_delivery()
            entry = {'body': answer.get('body')}
            answer['delivered'] = rule({'field': 'stdout', 'part': deliver['part'], 'name': deliver['name'],
                                        'dir': str(self.exchange), 'name_pattern': '^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$',
                                        'max_bytes': limit}, entry)
            answer['body'] = entry['body']
        return answer


@unittest.skipIf(TA.tar.BASH is None, 'no Git Bash (Windows) or bash: RESULT runs the harness\'s script')
class LiveBytes(TA.Bound):
    """The review's item 3: a live-bound attempt run end to end on the in-process core (dispatch, the launch gate,
    the attempt run, the intake, the result path) and an ended one: no record carries an ``authority`` key."""

    def project(self, resolved):
        demo = _load('aieh_gitea_demo_repository', REPO / 'integrations' / 'gitea' / 'demo_repository.py')
        change = AR._design(resolved)['change']
        c0 = demo.template_files()
        c1 = {**c0, f'openspec/changes/{change}/proposal.md': b'# A change\n'}
        task = (f'---\nid: {resolved.work_id}\ntitle: Implement slugify\nstatus: To Do\n---\n\nslugify\n').encode()
        c2 = {**c1, f'backlog/tasks/{resolved.work_id.lower()} - Implement-slugify.md': task}
        path = self.scratch / 'project'
        commits = tar.make_repository(path, [('C0', c0), ('C1', c1), ('C2', c2)])
        base = AR.read_base(path, repository=resolved.repository, design_commit=commits['C1'])
        return path, dataclasses.replace(base, design_commit=AR._design(resolved)['commit'])

    def assertUnlabelled(self):
        for reservation in self.store.attempts():
            with self.subTest(record=reservation.operation_key):
                self.assertEqual(authority_keys(json.loads(reservation.intent_json)), [])
                for event in self.store.events(reservation.operation_key):
                    detail = json.loads(event.detail_json) if event.detail_json else None
                    self.assertEqual(authority_keys(detail), [], event.to_state)

    def test_a_live_attempt_end_to_end_records_no_authority(self):
        rp = _load('test_result_path', HERE / 'test_result_path.py')
        exchange = self.scratch / 'exchange'
        exchange.mkdir()
        wire = LiveWire(self.core, exchange)
        result = self.dispatch(wire, provider(), profile=ci.REAL, manifest=self.approve_real())
        resolved = di.stored_inputs(self.store, result.operation_key, state='confirmed')
        source, base = self.project(resolved)
        gate = LG.gate(self.store, result.operation_key, inspect_source=self.core.container_inspect, source=SOURCE,
                       actor=ACTOR, read_profile=self.read_profile, read_artifact=self.read_artifact)
        host = self.scratch / 'host'
        host.mkdir()
        outcome = AR.run_attempt(self.store, result.operation_key, transport=wire, base=base, actor=ACTOR,
                                 inspect=gate, pull=tar.Puller(host, exchange), read_artifact=self.read_artifact,
                                 reserve_result=RP.result_hook(self.store, result.operation_key, actor=ACTOR))
        self.assertEqual(outcome.outcome, 'verified', outcome.problems)
        self.assertEqual(outcome.result.authority, 'live')
        remote = rp.DemoRemote(self.scratch, source, base.commit)
        self.addCleanup(remote.close)
        gitea = rp.DemoGitea(remote)
        target = RP.GiteaTarget(repository_id=resolved.repository, full_name=rp.DEMO, port=rp.PORT,
                                git_url=remote.url, http=gitea)
        bot = rp.fg.FixtureProvider({RP.roles.target('builder'): (rp.BUILDER, rp.fg.BOT_TOKENS[rp.BUILDER])})
        with mock.patch.dict(RP.ADMITTED_REPOSITORIES, {resolved.repository: rp.DEMO}):
            published = RP.publish_result(self.store, result.operation_key, verified=outcome.result,
                                          native=NT.NativeToken(ci.TOKEN), provider=bot, target=target, actor=ACTOR,
                                          report_dir=self.scratch / 'report', read_artifact=self.read_artifact)
        self.assertEqual(published.outcome, 'confirmed')
        self.assertUnlabelled()
        report = json.loads((self.scratch / 'report' / 'report.json').read_text(encoding='utf-8'))
        self.assertEqual(authority_keys(report), [])
        self.assertNotIn('Authority', (self.scratch / 'report' / 'report.md').read_text(encoding='utf-8'))
        [pull] = gitea.pulls.values()
        self.assertNotIn('Authority', pull['body'])
        self.assertEqual(authority_keys(outcome.result.to_json()), [])
        turn = json.loads(self.store.get(AR.TURN_KEY.format(attempt_id=result.attempt_id)).intent_json)
        self.assertNotIn('identity', turn, 'a live turn journal records no identity')
        commit = remote.repo[published.receipt['commit'].encode('ascii')]
        self.assertEqual(commit.author, f'{AR.BOT_NAME} <{AR.BOT_EMAIL}>'.encode(), 'decision 0024 point 4, unchanged')

    def test_a_live_attempts_reconcile_and_recovery_write_no_authority(self):
        """The store's reconcile, given recover's and reconcile_creates' label, writes no detail for a live attempt."""
        def lost(method, path, body=None, **kwargs):
            answer = self.core(method, path, body, **kwargs)
            if (method, path) == ('POST', '/api/conversations'):
                raise OSError('the answer was lost')
            return answer
        with self.assertRaises(OSError):
            self.dispatch(lost, provider(), profile=ci.REAL, manifest=self.approve_real())
        [attempt] = self.store.attempts()
        report = TA.RR.RC.reconcile_creates(self.store, transport=self.core, actor=ACTOR,
                                            read_artifact=self.read_artifact)
        self.assertEqual(report['confirmed'], [attempt.operation_key])
        [last] = self.store.events(attempt.operation_key)[-1:]
        self.assertEqual((last.to_state, last.detail_json), ('confirmed', None))
        self.assertUnlabelled()

    def test_a_live_attempts_end_journal_and_record_carry_no_authority(self):
        result = self.dispatch(self.core, provider(), profile=ci.REAL, manifest=self.approve_real())
        stop = {'kind': 'containment-stop', 'code': 'INSPECTION_FAILED', 'ref': f'attempt:{result.attempt_id}#x'}
        record = AE.end_interrupted_attempt(self.store, result.operation_key, transport=self.core, actor=ACTOR,
                                            trigger=AE.ATTEMPT_STOPPED, dispatcher_records=[stop],
                                            read_artifact=self.read_artifact)
        self.assertEqual(authority_keys(record), [])
        self.assertUnlabelled()


class NotLaunchedLabel(TA.Bound):
    """U-04.1's review (rv12, ruling 4): a launch receipt written ``not-launched`` because the gate could not read the
    admitted values still carries the bound authority, from the pinned route allowlist (``bound_label``'s source); a
    live one carries none, byte for byte as before; and with the allowlist unreadable too there is none to copy."""

    def gate(self, result):
        def unreadable(*args, **kwargs):
            raise OSError('the approved profile cannot be read')
        return LG.gate(self.store, result.operation_key, inspect_source=self.core.container_inspect, source=SOURCE,
                       actor=ACTOR, read_profile=unreadable, read_artifact=self.read_artifact)

    def test_a_fixture_not_launched_receipt_carries_the_bound_authority(self):
        result = self.fixture_attempt()
        problems = self.gate(result)(result.conversation_id)
        self.assertTrue(problems)
        record = LG.launch_record(self.store, result.attempt_id)
        self.assertEqual((record['verdict'], record['authority']), (LG.NOT_LAUNCHED, 'fixture'))

    def test_a_live_not_launched_receipt_carries_none(self):
        result = self.dispatch(self.core, provider(), profile=ci.REAL, manifest=self.approve_real())
        self.assertTrue(self.gate(result)(result.conversation_id))
        record = LG.launch_record(self.store, result.attempt_id)
        self.assertEqual(record['verdict'], LG.NOT_LAUNCHED)
        self.assertEqual(authority_keys(record), [])

    def test_with_the_allowlist_unreadable_too_the_receipt_is_unlabelled(self):
        result = self.fixture_attempt()
        (self.profiles / TA.FIX / 'agent-server' / 'routes.json').unlink()
        self.assertTrue(self.gate(result)(result.conversation_id))
        record = LG.launch_record(self.store, result.attempt_id)
        self.assertEqual(record['verdict'], LG.NOT_LAUNCHED)
        self.assertNotIn('authority', record)

    def test_a_defect_reading_the_bound_authority_is_a_visible_problem(self):
        """The review's re-check, ruling 4: the gate still writes its receipt (unlabelled), and the defect is named
        among its problems, never swallowed."""
        result = self.fixture_attempt()
        with mock.patch.object(di, 'bound_label', side_effect=TypeError('a defect')):
            problems = self.gate(result)(result.conversation_id)
        self.assertIn('the bound authority could not be read (TypeError)', problems)
        record = LG.launch_record(self.store, result.attempt_id)
        self.assertEqual(record['verdict'], LG.NOT_LAUNCHED)
        self.assertNotIn('authority', record)
        self.assertIn('the bound authority could not be read (TypeError)', record['problems'])


if __name__ == '__main__':
    unittest.main()
