"""The outcome projection (plan leaf U-04.1; the I1 integration design, R6, R11 and slice 12): projection.py and its
endpoint, ``GET /outcomes/{outcome_id}``.

Every attempt here is written by the dispatcher's own writers on a throwaway integration store, through the test
bases of the dispatch suite (``test_authority.Bound``: the checked-in fixture profile ``fixture-d1-replay`` and the
checked-in live declaration, their Agent Server answered by the fixture catalog's in-process core), never by hand:
``dispatch_inputs.dispatch``, the launch gate, ``attempt_run.run_attempt`` with the probe's own exchange delivery
(``test_live_bytes.LiveWire``'s pattern), the result path to E-05.4's in-process Gitea fakes, ``attempt_end``'s end
and stop writers, and ``restart_recovery``. The projection reads them read-only and asks no Agent Server.

U-04.1's proof, clause by clause:

- **"Pending/running/failed/unknown represent observed state, not agent exit claims"**: ``StateTable`` (one test per
  status of the README's table, each from real records), ``ExitClaims`` (the core's ``finished`` and a delivered
  result never make a success; the projection makes no Agent Server call), ``EndMapping`` (an ``error``, ``stuck`` or
  ``paused`` turn's end, unit-tested only, as the plan's note says), ``Labels`` (R11);
- **"The lineage message and statement resolvers resolve, and archived tasks resolve; an unresolved message,
  statement or archived-task reference is a failure"**: ``Outcome`` (over a throwaway project, the Owner conversation
  store and Backlog.md's own recorded output for an archived, a deleted and a reused task id);
- **"The attempt's result receipt (E-05.4's) is joined as evidence; its commit, diff and test output referenced, not
  copied"**: ``EndToEnd`` (a fixture and a live attempt run to a published receipt, projected ``succeeded``).

``ReadOnly`` shows the stores' bytes unchanged, Backlog.md asked ``task list`` and ``task view`` only, and no process
or socket; ``Route`` the endpoint behind the session, Host and Origin guards with its stable refusals.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ownerhost_support as T

CATEGORY = 'integration'
REPO = T.REPO
DISPATCH_TESTS = REPO / 'integrations' / 'dispatch' / 'tests'
TA = T._load('test_authority', DISPATCH_TESTS / 'test_authority.py')
di, AR, AE, LG, RP, RR, NT, ci, tar = TA.di, TA.AR, TA.AE, TA.LG, TA.RP, TA.RR, TA.NT, TA.ci, TA.tar
store_mod = TA.store_mod
E = T._load('lineage_example', REPO / 'integrations' / 'lineage' / 'tests' / 'lineage_example.py')
fx = E.fx
BACKEND = T._load('agentfixture_backend', REPO / 'integrations' / 'agentfixture' / 'backend.py')
P = T._load('aieh_ownerhost_projection', T.PACKAGE / 'projection.py')
A, S = T.A, T.S
ACTOR = 'u-04.1-test'
SOURCE = TA.SOURCE
# The dispatch fixtures' outcome (integrations/dispatch/tests/test_dispatch_inputs.py OUTCOME) and task.
OUTCOME_ID = '3f6a2c1d-9b4e-4f7a-8c2d-5e1b0a9f7d63'
OUTCOME = f'outcome:{OUTCOME_ID}'
WORK = 'TASK-2'
RECORDED = Path(__file__).resolve().parent / 'fixtures' / 'backlog-archive'
NOW = T.utc(2026, 11, 17, 12, 0, 0)


class Crash(BaseException):
    """The dispatcher ending at a point the test chooses (never caught as an Exception)."""


class Wire:
    """The in-process core as the transport, with the probe's own exchange delivery (``transport.pinned_delivery``,
    as ``test_live_bytes.LiveWire``), declaring AUTHORITY (none: live). FAIL(method, path) may raise before the core
    is asked; EDIT(method, path, answer) may change an answer (a test's own observation, never the catalog's)."""

    def __init__(self, core, exchange, authority=None, fail=None, edit=None):
        self.core, self.exchange, self.fail, self.edit = core, Path(exchange), fail, edit
        if authority is not None:
            self.authority = authority

    def __call__(self, method, path, body=None, deliver=None):
        if self.fail is not None:
            self.fail(method, path)
        answer = dict(self.core(method, path, body))
        if self.edit is not None:
            answer = self.edit(method, path, answer)
        if deliver is not None:
            transport = T._load('agentfixture_transport', REPO / 'integrations' / 'agentfixture' / 'transport.py')
            rule, limit = transport.pinned_delivery()
            entry = {'body': answer.get('body')}
            answer['delivered'] = rule({'field': 'stdout', 'part': deliver['part'], 'name': deliver['name'],
                                        'dir': str(self.exchange), 'name_pattern': '^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$',
                                        'max_bytes': limit}, entry)
            answer['body'] = entry['body']
        return answer


def raiser(error):
    def call(*args, **kwargs):
        raise error
    return call


class Base(TA.Bound):
    """The dispatch suite's bound fixture (both checked-in profiles approved, the core answering) and the projection's
    view of one attempt."""

    def setUp(self):
        super().setUp()
        self.runs = 0

    def view(self, key=None):
        """The projection's view of the attempt KEY (the only typed attempt when none is named), read-only."""
        with P.R.ReadOnlyIntegrationStore(Path(self.store.path)) as held:
            rows = held.attempts()
            if key is None:
                (key,) = [r.operation_key for r in rows if r.operation_key.startswith(store_mod.KEY_PREFIX)]
            typed = held.attempt_identity(key)
            return P.attempt_view(held.get(key), rows, held.events, identity=typed.identity if typed else None,
                                  read_artifact=self.read_artifact)

    def assertStatus(self, view, status, code, authority='fixture'):
        self.assertEqual((view['status'], view['code']), (status, code), json.dumps(view, indent=1)[:3000])
        self.assertEqual(view['authority']['shown'], authority, view['authority'])

    def fixture(self) -> bool:
        return True

    def dispatched(self, transport=None, live=False, credentials=None):
        if live:
            return self.dispatch(transport or self.core, credentials or TA.provider(), profile=ci.REAL,
                                 manifest=self.approve_real())
        return self.dispatch(transport or TA.Seam(self.core, 'fixture'), credentials or BACKEND.FixtureCredentials())

    def project_for(self, resolved):
        """A throwaway project repository holding the attempt's base (``test_live_bytes.LiveBytes.project``)."""
        demo = T._load('aieh_gitea_demo_repository', REPO / 'integrations' / 'gitea' / 'demo_repository.py')
        change = AR._design(resolved)['change']
        c0 = demo.template_files()
        c1 = {**c0, f'openspec/changes/{change}/proposal.md': b'# A change\n'}
        task = (f'---\nid: {resolved.work_id}\ntitle: Implement slugify\nstatus: To Do\n---\n\nslugify\n').encode()
        c2 = {**c1, f'backlog/tasks/{resolved.work_id.lower()} - Implement-slugify.md': task}
        path = self.scratch / f'project-{self.runs}'
        commits = tar.make_repository(path, [('C0', c0), ('C1', c1), ('C2', c2)])
        base = AR.read_base(path, repository=resolved.repository, design_commit=commits['C1'])
        import dataclasses
        return path, dataclasses.replace(base, design_commit=AR._design(resolved)['commit'])

    def go(self, *, live=False, fail=None, edit=None, observe=None, pull=None, hook=True, publish=True,
            inspect_edit=None, gitea_fail=None):
        """One attempt dispatched and run by the dispatcher's own path on the in-process core; with PUBLISH its result
        published to E-05.4's in-process Gitea fakes. Returns (the dispatch result, the run's outcome or the exception
        it ended with, the published outcome or None, the report directory)."""
        self.runs += 1
        authority = None if live else 'fixture'
        exchange = self.scratch / f'exchange-{self.runs}'
        exchange.mkdir()
        wire = Wire(self.core, exchange, authority, fail=fail, edit=edit)
        credentials = TA.provider() if live else BACKEND.FixtureCredentials()
        result = self.dispatched(wire, live=live, credentials=credentials)
        resolved = di.stored_inputs(self.store, result.operation_key, state='confirmed')
        source, base = self.project_for(resolved)

        def inspect_source(cid):
            answer = self.core.container_inspect(cid)
            return inspect_edit(answer) if inspect_edit is not None else answer
        gate = LG.gate(self.store, result.operation_key, inspect_source=inspect_source, source=SOURCE, actor=ACTOR,
                       read_profile=self.read_profile, read_artifact=self.read_artifact)
        host = self.scratch / f'host-{self.runs}'
        host.mkdir()
        puller = pull or tar.Puller(host, exchange)

        def seam(call):
            return call if live else TA.Seam(call, 'fixture')
        report = self.scratch / f'report-{self.runs}'
        try:
            outcome = AR.run_attempt(self.store, result.operation_key, transport=wire, base=base, actor=ACTOR,
                                     inspect=seam(gate), pull=seam(puller), read_artifact=self.read_artifact,
                                     observe=observe, identity=None if live else TA.IDENTITY,
                                     reserve_result=RP.result_hook(self.store, result.operation_key, actor=ACTOR)
                                     if hook else None)
        except (Exception, Crash) as exc:        # noqa: BLE001 - the run's own end, observed by the projection
            return result, exc, None, report
        published = None
        if publish and outcome.outcome == 'verified':
            rp = T._load('test_result_path', DISPATCH_TESTS / 'test_result_path.py')
            remote = rp.DemoRemote(self.scratch, source, base.commit)
            self.addCleanup(remote.close)
            gitea = rp.DemoGitea(remote)
            if gitea_fail is not None:
                gitea = gitea_fail(gitea)
            if live:
                target = RP.GiteaTarget(repository_id=resolved.repository, full_name=rp.DEMO, port=rp.PORT,
                                        git_url=remote.url, http=gitea)
                bot = rp.fg.FixtureProvider({RP.roles.target('builder'): (rp.BUILDER, rp.fg.BOT_TOKENS[rp.BUILDER])})
                native = NT.NativeToken(ci.TOKEN)
            else:
                target = RP.GiteaTarget(repository_id=resolved.repository, full_name=rp.DEMO, port=rp.PORT,
                                        git_url=remote.url, http=gitea, authority='fixture')
                bot, native = credentials, NT.read(credentials)
            with mock.patch.dict(RP.ADMITTED_REPOSITORIES, {resolved.repository: rp.DEMO}):
                try:
                    published = RP.publish_result(self.store, result.operation_key, verified=outcome.result,
                                                  native=native, provider=bot, target=target, actor=ACTOR,
                                                  report_dir=report, read_artifact=self.read_artifact)
                except di.DispatchRefused as refusal:
                    published = refusal
        return result, outcome, published, report


def at_phase(name):
    """An observer that ends the dispatcher at the run's phase NAME (``before-message``, ``after-message``, ...)."""
    def observe(phase, **facts):
        if phase == name:
            raise Crash(f'the dispatcher ended at {name}')
        return ()
    return observe


@unittest.skipIf(tar.BASH is None, 'no Git Bash (Windows) or bash: RESULT runs the harness\'s script')
class StateTable(Base):
    """Each status of the README's state table, from records the dispatcher's own writers made."""

    def test_pending_reserved(self):
        held = BACKEND.FixtureCredentials()
        held.get = raiser(Crash('the dispatcher died reading the entry'))
        with self.assertRaises(Crash):
            self.dispatched(credentials=held)
        self.assertStatus(self.view(), 'pending', 'ATTEMPT_RESERVED')

    def test_pending_created(self):
        self.fixture_attempt()
        view = self.view()
        self.assertStatus(view, 'pending', 'CREATED')
        self.assertEqual(view['shownBy']['state'], 'confirmed')

    def test_pending_launched(self):
        result, ended, _, _ = self.go(observe=at_phase('before-message'), publish=False)
        self.assertIsInstance(ended, Crash)
        self.assertStatus(self.view(result.operation_key), 'pending', 'LAUNCHED')

    def test_running_create_sent(self):
        def after_the_create(method, path, body=None, **kwargs):
            answer = self.core(method, path, body, **kwargs)
            if (method, path) == ('POST', '/api/conversations'):
                raise Crash('the dispatcher died after the create reached the server')
            return answer
        with self.assertRaises(Crash):
            self.dispatched(TA.Seam(after_the_create, 'fixture'))
        self.assertStatus(self.view(), 'running', 'CREATE_SENT')

    def test_running_turn_sent(self):
        result, ended, _, _ = self.go(observe=at_phase('after-message'), publish=False)
        self.assertIsInstance(ended, Crash)
        view = self.view(result.operation_key)
        self.assertStatus(view, 'running', 'TURN_SENT')
        self.assertEqual(view['shownBy']['record'], AR.TURN_KEY.format(attempt_id=result.attempt_id))

    def test_running_result_delivered(self):
        result, ended, _, _ = self.go(pull=raiser(Crash('the pull never ended')), publish=False)
        self.assertIsInstance(ended, Crash)
        view = self.view(result.operation_key)
        self.assertStatus(view, 'running', 'RESULT_DELIVERED')
        self.assertEqual(view['result']['reported']['basis'], 'reported')
        self.assertIsNone(view['result']['verified'])

    def test_running_result_verified_by_the_intake(self):
        result, outcome, _, _ = self.go(hook=False, publish=False)
        self.assertEqual(outcome.outcome, 'verified')
        view = self.view(result.operation_key)
        self.assertStatus(view, 'running', 'RESULT_VERIFIED')
        self.assertEqual(view['shownBy']['record'], AR.INTAKE_KEY.format(attempt_id=result.attempt_id))
        self.assertEqual(view['result']['verified']['commit'], outcome.result.commit)

    def test_running_result_verified_and_its_journal_reserved(self):
        result, outcome, _, _ = self.go(publish=False)
        view = self.view(result.operation_key)
        self.assertStatus(view, 'running', 'RESULT_VERIFIED')
        self.assertEqual((view['shownBy']['record'], view['shownBy']['state']),
                         (RP.RESULT_KEY.format(attempt_id=result.attempt_id), 'reserved'))

    def test_failed_refused_create(self):
        def refused(method, path, body=None, **kwargs):
            if (method, path) == ('POST', '/api/conversations'):
                return {'status': 401, 'body': {'detail': 'Unauthorized'}}
            return self.core(method, path, body, **kwargs)
        with self.assertRaises(di.DispatchRefused):
            self.dispatched(TA.Seam(refused, 'fixture'))
        view = self.view()
        self.assertStatus(view, 'failed', 'ATTEMPT_FAILED')
        self.assertEqual(view['cause'], 'CREATE_REFUSED')

    def test_failed_the_gate_s_not_launched(self):
        def other_memory(answer):
            answer = copy.deepcopy(dict(answer))
            answer['body']['HostConfig']['Memory'] = answer['body']['HostConfig']['Memory'] * 2
            return answer
        result, outcome, _, _ = self.go(inspect_edit=other_memory, publish=False)
        launch = LG.launch_record(self.store, result.attempt_id)
        self.assertEqual(launch['verdict'], LG.NOT_LAUNCHED)
        view = self.view(result.operation_key)
        self.assertStatus(view, 'failed', 'LAUNCH_NOT_LAUNCHED')
        self.assertIsNone(self.store.get(AR.TURN_KEY.format(attempt_id=result.attempt_id)), 'no message was sent')

    def test_unknown_the_create_s_outcome(self):
        def no_answer(method, path, body=None, **kwargs):
            if (method, path) == ('POST', '/api/conversations'):
                raise OSError('no answer')
            return self.core(method, path, body, **kwargs)
        with self.assertRaises(OSError):
            self.dispatched(TA.Seam(no_answer, 'fixture'))
        self.assertStatus(self.view(), 'unknown', 'CREATE_OUTCOME_UNKNOWN')

    def test_unknown_a_lost_turn_outcome(self):
        def lost(method, path):
            if method == 'POST' and path.endswith('/events'):
                raise OSError('the message\'s answer was lost before it reached the server')
        result, ended, _, _ = self.go(fail=lost, publish=False)
        self.assertEqual(getattr(ended, 'code', None), 'TURN_UNRECONCILED')
        self.assertStatus(self.view(result.operation_key), 'unknown', 'TURN_OUTCOME_UNKNOWN')

    def test_unknown_a_lost_result_write(self):
        class Lost:
            def __init__(self, gitea):
                self.gitea = gitea

            def __call__(self, port, path, *args, **kwargs):
                if kwargs.get('method') == 'POST' and path.endswith('/pulls'):
                    raise OSError('the pull request\'s answer was lost')
                return self.gitea(port, path, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self.gitea, name)
        result, outcome, published, _ = self.go(gitea_fail=Lost)
        self.assertEqual(getattr(published, 'code', None), 'RESULT_WRITE_UNSETTLED', published)
        self.assertStatus(self.view(result.operation_key), 'unknown', 'RESULT_WRITE_UNSETTLED')

    def test_the_restore_epoch_sweep_is_unknown(self):
        """The store's restore epoch sweeps an attempt left dispatched to unknown: the projection says unknown."""
        def after_the_create(method, path, body=None, **kwargs):
            answer = self.core(method, path, body, **kwargs)
            if (method, path) == ('POST', '/api/conversations'):
                raise Crash('died')
            return answer
        with self.assertRaises(Crash):
            self.dispatched(TA.Seam(after_the_create, 'fixture'))
        path = Path(self.store.path)
        manifest = self.store.backup(actor='owner')
        self.store.close()
        store_mod.restore_store(path, path.parent / 'backups' / (manifest['backup_file'] + '.manifest.json'),
                                actor='owner')
        self.store = store_mod.open_store(path)
        self.addCleanup(self.store.close)
        RR.RC.reconcile_creates(self.store, transport=TA.Seam(raiser(OSError('down')), 'fixture'), actor=ACTOR,
                                read_artifact=self.read_artifact)
        view = self.view()
        self.assertEqual(view['status'], 'unknown', view)


@unittest.skipIf(tar.BASH is None, 'no Git Bash (Windows) or bash: RESULT runs the harness\'s script')
class EndToEnd(Base):
    """A fixture and a live attempt run to a published result receipt (E-05.4's), projected succeeded /
    RESULT_PUBLISHED, with the receipt joined as evidence: the commit, the diff and the test output referenced with
    digests, never copied."""

    def published(self, live):
        result, outcome, published, report = self.go(live=live)
        self.assertEqual(getattr(published, 'outcome', published), 'confirmed')
        return result, outcome, published, report

    def check(self, live):
        result, outcome, published, report = self.published(live)
        view = self.view(result.operation_key)
        self.assertStatus(view, 'succeeded', 'RESULT_PUBLISHED', authority='live' if live else 'fixture')
        # a successful attempt writes no end and no stop record (rows 5 to 7 cannot precede row 10 for it)
        prefix = f'dispatch/attempt/{result.attempt_id}/'
        kinds = sorted({r.operation_key[len(prefix):].split('/')[0] for r in self.store.attempts()
                        if r.operation_key.startswith(prefix)})
        self.assertEqual(kinds, ['delivery', 'intake', 'launch', 'pull', 'result', 'turn'])
        receipt = published.receipt
        evidence = view['evidence']
        self.assertEqual(evidence['commit'], {'basis': 'verified', 'reference': receipt['resultRef'],
                                              'commit': receipt['commit'], 'branch': receipt['branch']})
        self.assertEqual((evidence['diff']['from'], evidence['diff']['to']), (receipt['baseRef'], receipt['resultRef']))
        report_json = (report / 'report.json').read_bytes()
        self.assertEqual(evidence['diff']['ownerReport']['jsonSha256'], hashlib.sha256(report_json).hexdigest())
        self.assertEqual(evidence['diff']['ownerReport']['markdownSha256'],
                         hashlib.sha256((report / 'report.md').read_bytes()).hexdigest())
        self.assertEqual(evidence['testOutput']['output'], {'sha256': receipt['tests']['outputDigest']['sha256'],
                                                            'bytes': receipt['tests']['outputDigest']['bytes']})
        self.assertEqual(evidence['testOutput']['basis'], 'reported')
        self.assertEqual(evidence['receipt']['sha256'],
                         hashlib.sha256(di._canonical(receipt).encode('utf-8')).hexdigest())
        # referenced, not copied: no text of the diff, the test output or the commit message is in the projection
        data = json.loads(report_json)
        text = json.dumps(view)
        copies = [data['diff']['text'], data['tests']['output'], data['commitMessage']]
        for copied in copies:
            self.assertTrue(isinstance(copied, str) and len(copied) > 20)
            self.assertFalse(copied in text or json.dumps(copied)[1:-1] in text, 'a copy of the result is in the view')
        for line in [l for l in data['diff']['text'].splitlines() if len(l) > 12][:20]:
            self.assertFalse(line in text, 'a line of the diff is in the view')
        # reported and verified apart: the host's commit, and the attempt's own tests
        self.assertEqual(view['result']['verified']['commit'], receipt['commit'])
        self.assertEqual(view['result']['reported']['commit'], receipt['commit'])
        self.assertEqual(view['result']['tests']['basis'], 'reported')
        # every record's label, as the projection reads it, is the dispatcher's own (record_label)
        for row in self.store.attempts():
            if row.operation_key == result.operation_key or row.operation_key.startswith(prefix):
                with self.subTest(record=row.operation_key):
                    record = P.Record(row, self.store.events(row.operation_key), 'typed'
                                      if row.operation_key == result.operation_key
                                      else row.operation_key[len(prefix):].split('/')[0])
                    labels, carried = P._labels_of(record)
                    expected = di.record_label(self.store, row.operation_key, self.read_artifact)
                    self.assertEqual({v for _, v in labels}, set(expected.values()))
                    self.assertTrue(carried or live)
        return result, view

    def test_a_fixture_attempt_published_is_succeeded_with_its_receipt_as_evidence(self):
        self.check(live=False)

    def test_a_live_attempt_published_is_succeeded_and_trips_no_label_rule(self):
        _, view = self.check(live=True)
        self.assertIsNone(view['authority']['code'])

    def test_the_outcome_projection_joins_the_published_attempt(self):
        result, _, published, _ = self.published(live=False)
        outcome = Outcome.build(self, 'listed')
        projection = outcome.project(self)
        [attempt] = [a for a in projection['attempts'] if a['operationKey'] == result.operation_key]
        self.assertEqual((attempt['status'], attempt['code']), ('succeeded', 'RESULT_PUBLISHED'))
        self.assertEqual(attempt['evidence']['commit']['commit'], published.receipt['commit'])
        [task] = [t for t in projection['tasks'] if t['reference'] == f'backlog:{WORK}']
        self.assertEqual(task['execution'], {'status': 'succeeded', 'code': 'RESULT_PUBLISHED',
                                             'attempt': result.operation_key})
        self.assertEqual(projection['coverage'], P.COVERAGE)


@unittest.skipIf(tar.BASH is None, 'no Git Bash (Windows) or bash: RESULT runs the harness\'s script')
class ExitClaims(Base):
    """Observed state, not exit claims: the Agent Server's ``finished`` (the core answers it at the first read after
    the message) and a result the container reported never make a success, and the projection asks no Agent Server."""

    def test_a_finished_turn_without_the_host_s_verification_is_not_a_success(self):
        result, ended, _, _ = self.go(observe=at_phase('after-turn'), publish=False)
        self.assertIsInstance(ended, Crash)
        view = self.view(result.operation_key)
        self.assertNotEqual(view['status'], 'succeeded')
        self.assertStatus(view, 'running', 'TURN_SENT')

    def test_the_projection_makes_no_agent_server_call(self):
        result = self.fixture_attempt()
        calls = len(self.core.calls)
        self.view(result.operation_key)
        self.assertEqual(len(self.core.calls), calls)
        self.assertFalse(hasattr(P, 'AgentServerClient'))


class EndMapping(Base):
    """Decision 0024 point 7.5's mapping, unit-tested only (the plan's note: E-01.7 serves no error, stuck or paused
    turn): an attempt ended with the conversation's observed status ``error``, ``stuck`` or ``paused`` is failed,
    ATTEMPT_ENDED, with that status as the end record surfaced it."""

    def test_an_error_stuck_or_paused_turn_s_end_is_failed(self):
        for status in ('error', 'stuck', 'paused'):
            with self.subTest(status=status):
                self.doCleanups()
                self.setUp()
                result = self.fixture_attempt()

                def edit(method, path, answer, status=status):
                    if method == 'GET' and path == f'/api/conversations/{result.conversation_id}' \
                            and isinstance(answer.get('body'), dict):
                        answer = {**answer, 'body': {**answer['body'], 'execution_status': status}}
                    return answer
                wire = Wire(self.core, self.scratch, 'fixture', edit=edit)
                AE.end_interrupted_attempt(self.store, result.operation_key, transport=wire, actor=ACTOR,
                                           trigger=AE.CONVERSATION_ENDED, read_artifact=self.read_artifact)
                view = self.view(result.operation_key)
                self.assertStatus(view, 'failed', 'ATTEMPT_ENDED')
                self.assertEqual(view['end']['executionStatus'], status)

    def test_a_stopped_attempt_and_the_end_cause_record(self):
        """A stop receipt is failed ATTEMPT_STOPPED; the engineering manager's end-cause receipt, which the
        dispatcher writes without a label by design, trips no label rule."""
        result = self.fixture_attempt()
        stop = {'kind': 'containment-stop', 'code': 'INSPECTION_FAILED', 'ref': f'attempt:{result.attempt_id}#x'}
        AE.record_stop(self.store, result.operation_key, [stop], actor=ACTOR, read_artifact=self.read_artifact)
        self.assertStatus(self.view(result.operation_key), 'failed', 'ATTEMPT_STOPPED')
        self.doCleanups()
        self.setUp()
        result = self.fixture_attempt()
        AE.end_interrupted_attempt(self.store, result.operation_key, transport=TA.Seam(self.core, 'fixture'),
                                   actor=ACTOR, trigger=AE.ATTEMPT_STOPPED, read_artifact=self.read_artifact)
        AE.record_end_cause(self.store, result.operation_key, cause=AE.END_CAUSE_INTERRUPTION, actor=ACTOR)
        view = self.view(result.operation_key)
        self.assertStatus(view, 'failed', 'ATTEMPT_ENDED')
        self.assertIn(AE.END_CAUSE_KEY.format(attempt_id=result.attempt_id), view['records'])


class Labels(Base):
    """R11's reader rule: the attempt's authority is its binding; a label that disagrees is unknown, shown as neither."""

    def turn(self, result, authority):
        """A turn journal written by the dispatcher's own intent builder and transitions, with AUTHORITY's label."""
        base = self.project_for(di.stored_inputs(self.store, result.operation_key, state='confirmed'))[1]
        key = AR.TURN_KEY.format(attempt_id=result.attempt_id)
        self.store.reserve(key, AR.turn_intent(result.operation_key, base, 'text', authority, TA.IDENTITY), actor=ACTOR)
        di._mark(self.store, key, 'reserved', 'dispatched', ACTOR, 'send-message', None)
        di._mark(self.store, key, 'dispatched', 'confirmed', ACTOR, 'sent', {'status': 200})

    def test_a_fixture_answered_attempt_is_shown_fixture_never_live(self):
        result = self.fixture_attempt()
        self.turn(result, 'fixture')
        view = self.view(result.operation_key)
        self.assertStatus(view, 'running', 'TURN_SENT', authority='fixture')

    def test_a_fixture_attempt_with_one_record_s_label_stripped_is_unknown(self):
        result = self.fixture_attempt()
        stop = {'kind': 'containment-stop', 'code': 'INSPECTION_FAILED', 'ref': f'attempt:{result.attempt_id}#x'}
        AE.record_stop(self.store, result.operation_key, [stop], actor=ACTOR)     # no reader: written unlabelled
        view = self.view(result.operation_key)
        self.assertStatus(view, 'unknown', 'ATTEMPT_LABEL_MISSING', authority='unknown')
        self.assertEqual(view['authority']['code'], 'ATTEMPT_LABEL_MISSING')

    def test_a_fixture_attempt_whose_turn_journal_lacks_the_label_is_unknown(self):
        result = self.fixture_attempt()
        self.turn(result, 'live')
        self.assertStatus(self.view(result.operation_key), 'unknown', 'ATTEMPT_LABEL_MISSING', authority='unknown')

    def test_a_record_carrying_another_label_is_unknown(self):
        result = self.fixture_attempt()
        self.turn(result, 'elsewhere')
        self.assertStatus(self.view(result.operation_key), 'unknown', 'ATTEMPT_LABEL_MISMATCH', authority='unknown')

    def test_a_live_attempt_with_a_label_added_is_unknown(self):
        result = self.dispatched(live=True)
        self.assertStatus(self.view(result.operation_key), 'pending', 'CREATED', authority='live')
        self.turn(result, 'fixture')
        self.assertStatus(self.view(result.operation_key), 'unknown', 'ATTEMPT_LABEL_ON_LIVE', authority='unknown')

    def test_an_unbound_attempt(self):
        """The admission refusal with an unreadable allowlist is unlabelled by design: failed, its code, and the
        authority shown as neither with ATTEMPT_AUTHORITY_UNBOUND. A confirmed attempt whose allowlist can no longer
        be read is unknown."""
        manifest = self.fixture_manifest
        routes = self.profiles / TA.FIX / 'agent-server' / 'routes.json'
        raw = routes.read_bytes()
        routes.unlink()
        with self.assertRaises(di.DispatchRefused):
            self.dispatch(TA.Seam(self.core, 'fixture'), TA.provider('fixture'), manifest=manifest)
        view = self.view()
        self.assertStatus(view, 'failed', 'ATTEMPT_FAILED', authority='unknown')
        self.assertEqual((view['cause'], view['authority']['code'], view['authority']['reason']),
                         ('PROFILE_ARTIFACT_MISSING', 'ATTEMPT_AUTHORITY_UNBOUND', 'BINDING_ALLOWLIST_MISSING'))
        self.doCleanups()
        self.setUp()
        result = self.fixture_attempt()
        (self.profiles / TA.FIX / 'agent-server' / 'routes.json').write_bytes(raw + b'\n')
        self.assertStatus(self.view(result.operation_key), 'unknown', 'ATTEMPT_AUTHORITY_UNBOUND', authority='unknown')


class Rules(unittest.TestCase):
    """The state table's order and the record constants, on the projection's own functions."""
    category = 'unit'

    def test_the_formats_are_the_writers(self):
        self.assertEqual(P.FORMATS, {'turn': AR.TURN_FORMAT, 'launch': LG.LAUNCH_FORMAT, 'delivery': AR.DELIVERY_FORMAT,
                                     'pull': AR.PULL_FORMAT, 'intake': AR.INTAKE_FORMAT, 'result': RP.JOURNAL_FORMAT,
                                     'end': AE.END_JOURNAL_FORMAT, 'stop': AE.STOP_FORMAT})
        self.assertEqual((P.RESULT_RECEIPT_FORMAT, P.END_FORMAT), (RP.RECEIPT_FORMAT, AE.END_FORMAT))
        self.assertEqual((P.LAUNCHED, P.NOT_LAUNCHED), (LG.LAUNCHED, LG.NOT_LAUNCHED))
        self.assertEqual(P.EXECUTION_REF_PREFIX, di.EXECUTION_REF_PREFIX)
        for name, key in (('turn', AR.TURN_KEY), ('launch', LG.LAUNCH_KEY), ('delivery', AR.DELIVERY_KEY),
                          ('pull', AR.PULL_KEY), ('intake', AR.INTAKE_KEY), ('result', RP.RESULT_KEY),
                          ('end', AE.END_KEY)):
            self.assertEqual(key.format(attempt_id='X'), f'{P.RECORD_PREFIX}X/{name}')
        self.assertTrue(AE.STOP_KEY.startswith(P.RECORD_PREFIX + '{attempt_id}/stop/'))

    def test_the_backlog_pin_is_the_component_lock_s(self):
        lock = json.loads((REPO / 'composition' / 'lock' / 'npm' / 'package.json').read_text(encoding='utf-8'))
        self.assertEqual(P.BACKLOG_PIN, f'Backlog.md {lock["dependencies"]["backlog.md"]}')


class Outcome(Base):
    """Criterion 2 over the whole projection: a throwaway project whose change declares the dispatch fixtures'
    outcome (decision 0008) and cites Owner statements of the conversation store, Backlog.md's recorded output, and the
    integration store of the dispatched attempts."""

    @staticmethod
    def build(case, snapshot, statements=True):
        work = Path(tempfile.mkdtemp(prefix='u41-p-'))
        case.addCleanup(fx.rmtree, work)
        repo = work / 'p'
        fx.build_repo(repo)
        E.declare(repo, data=E.declaration(outcome=OUTCOME_ID))
        fx.commit_all(repo, E.DECLARE_MESSAGE, date=E.DECLARED_DATE)
        conversations = E.build_conversations(E.conversations_path(repo), statements=statements)
        E.cite_store(repo)
        fx.commit_all(repo, E.CITE_MESSAGE, date=E.CITED_DATE)
        return OutcomeSources(repo, conversations, snapshot)

    def test_the_statement_resolvers_resolve_and_the_attempt_is_joined(self):
        result = self.fixture_attempt()
        projection = Outcome.build(self, 'listed').project(self)
        self.assertEqual(projection['format'], 'outcome-projection/v1')
        self.assertEqual(projection['failures'], [])
        self.assertNotEqual(projection['verdict'], 'failed')
        self.assertTrue(projection['statements'])
        for node in projection['statements']:
            self.assertEqual((node['kind'] in ('message', 'conversation'), node['resolution']['outcome']),
                             (True, 'resolved'), node['reference'])
        self.assertEqual(projection['objective']['resolution']['outcome'], 'resolved')
        [attempt] = projection['attempts']
        self.assertEqual((attempt['operationKey'], attempt['status'], attempt['code']),
                         (result.operation_key, 'pending', 'CREATED'))
        self.assertEqual(projection['coverage'], P.COVERAGE)

    def test_an_unresolved_message_or_statement_reference_is_a_failure(self):
        self.fixture_attempt()
        projection = Outcome.build(self, 'listed', statements=False).project(self)
        self.assertEqual(projection['verdict'], 'failed')
        failed = {(f['role'], f['outcome'], f['code']) for f in projection['failures']}
        self.assertTrue(failed)
        self.assertTrue(all(role == 'statement' for role, _, _ in failed), failed)
        self.assertIn(('statement', 'missing', 'CONVERSATION_MISSING'), failed)

    def test_an_archived_task_resolves_by_reference(self):
        result = self.fixture_attempt()
        projection = Outcome.build(self, 'archived').project(self)
        [task] = [t for t in projection['tasks'] if t['reference'] == f'backlog:{WORK}']
        self.assertEqual((task['resolution'], task['reachedThrough']), ('resolved', 'attempt'))
        self.assertEqual(task['attempts'], [result.operation_key])
        self.assertEqual(projection['failures'], [])
        self.assertEqual(projection['coverage']['archivedTasksEnumerable'], False)

    def test_a_removed_archived_task_is_a_failure(self):
        self.fixture_attempt()
        projection = Outcome.build(self, 'deleted').project(self)
        self.assertEqual(projection['verdict'], 'failed')
        self.assertIn({'reference': f'backlog:{WORK}', 'role': 'work', 'kind': 'work', 'outcome': 'missing',
                       'code': 'WORK_MISSING'},
                      [{k: f[k] for k in ('reference', 'role', 'kind', 'outcome', 'code')}
                       for f in projection['failures']])

    def test_a_deleted_task_s_id_reused_by_a_later_task_resolves_to_that_task(self):
        """A known hazard of the pin, recorded: ``task delete`` releases an archived task's id, and the next task takes
        it, so a work reference resolves to the later task (a work reference carries no digest). Shown, not fixed."""
        self.fixture_attempt()
        projection = Outcome.build(self, 'reused').project(self)
        [task] = [t for t in projection['tasks'] if t['reference'] == f'backlog:{WORK}']
        self.assertEqual(task['resolution'], 'resolved')

    def test_the_coverage_field_is_always_present(self):
        self.fixture_attempt()
        for snapshot in ('listed', 'archived', 'deleted'):
            with self.subTest(snapshot=snapshot):
                projection = Outcome.build(self, snapshot).project(self)
                self.assertEqual(projection['coverage'], {
                    'archivedTasksEnumerable': False, 'code': 'ARCHIVED_TASKS_NOT_ENUMERABLE',
                    'basis': 'Backlog.md 1.55.3 task list --json', 'detail': P.COVERAGE['detail']})
                self.assertFalse([u for u in projection['uncertainties']
                                  if u['code'] == 'ARCHIVED_TASKS_NOT_ENUMERABLE'], 'not a node uncertainty')


class OutcomeSources:
    SNAPSHOTS = {'listed': E.RECORDED_TASKS, 'archived': RECORDED / 'archived', 'deleted': RECORDED / 'deleted',
                 'reused': RECORDED / 'reused'}

    def __init__(self, repo, conversations, snapshot):
        self.repo, self.conversations, self.snapshot = repo, conversations, self.SNAPSHOTS[snapshot]

    def project(self, case, outcome=OUTCOME):
        patch = E.in_process_backlog()
        patch.start()
        try:
            with mock.patch.dict(os.environ, {'FAKE_BACKLOG_SNAPSHOT': str(self.snapshot)}):
                return P.project(outcome, project=self.repo, backlog=E.FAKE_BACKLOG, store=Path(case.store.path),
                                 conversations=self.conversations, read_artifact=case.read_artifact)
        finally:
            patch.stop()


class Audit:
    armed, events = False, []

    @classmethod
    def hook(cls, event, args):
        if cls.armed and event in ('subprocess.Popen', 'socket.connect', 'socket.getaddrinfo', 'os.system'):
            cls.events.append(event)


sys.addaudithook(Audit.hook)


def file_state(path: Path):
    """A database file's bytes (its -wal sidecar folded in by a read-only checkpoint-free read of the main file)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ReadOnly(Base):
    """Read-only throughout: the integration store's and the conversation store's bytes and content and the project
    repository are unchanged; Backlog.md is asked task list and task view only; no process is started and no socket
    connected (OpenSpec never runs; git is read through the repository-access module)."""

    def test_a_projection_changes_nothing_and_asks_only_reads(self):
        self.fixture_attempt()
        sources = Outcome.build(self, 'listed')
        store_path = Path(self.store.path)
        tree = (fx.git(sources.repo, 'status', '--porcelain', '--untracked-files=all', '--ignored'),
                fx.git(sources.repo, 'for-each-ref'), fx.head(sources.repo))
        before = (file_state(store_path), self.store.canonical_dump(), file_state(sources.conversations))
        log = sources.repo / '.fake-backlog-argv.jsonl'
        Audit.events.clear()
        Audit.armed = True
        try:
            projection = sources.project(self)
        finally:
            Audit.armed = False
        self.assertEqual(Audit.events, [], 'no process, no socket')
        self.assertEqual((file_state(store_path), self.store.canonical_dump(), file_state(sources.conversations)),
                         before)
        asked = {tuple(json.loads(line)[:2]) for line in log.read_text(encoding='utf-8').splitlines()}
        self.assertEqual(asked, {('task', 'list'), ('task', 'view')})
        log.unlink()
        excluded = ['--', '.', ':(exclude).fake-backlog.json', ':(exclude).fake-backlog-argv.jsonl']
        self.assertEqual((fx.git(sources.repo, 'status', '--porcelain', '--untracked-files=all', '--ignored', *excluded),
                          fx.git(sources.repo, 'for-each-ref'), fx.head(sources.repo)),
                         (fx.git(sources.repo, 'status', '--porcelain', '--untracked-files=all', '--ignored',
                                 *excluded), tree[1], tree[2]))
        self.assertEqual(projection['sources']['integrationStore'], 'read')

    def test_the_read_only_backlog_refuses_any_other_command(self):
        backlog = P.R.ReadOnlyBacklog(E.FAKE_BACKLOG, self.scratch)
        for args in (('task', 'create', 'x'), ('task', 'edit', 'TASK-1'), ('task', 'archive', 'TASK-1'),
                     ('init', 'x')):
            with self.subTest(args=args):
                with self.assertRaises(P.planning.PlanningError) as caught:
                    backlog.run(*args)
                self.assertEqual(caught.exception.code, 'ADAPTER_REFUSED')


class Route(Base):
    """``GET /outcomes/{outcome_id}`` behind the session, Host and Origin guards, with its stable refusals."""

    def setUp(self):
        super().setUp()
        self.session = T.Scratch(prefix='u41-route-')
        self.addCleanup(self.session.close)
        self.credential, _ = self.session.enroll(at=NOW)

    def app(self, config=None, store=True, conversations=None):
        projector = P.Projection(config, Path(self.store.path) if store else None, conversations,
                                 read_artifact=self.read_artifact)
        return A.create_app(lambda: self.session.store, clock=lambda: T.stamp(NOW), projector=projector)

    def get(self, app, path, *headers, credential=True):
        hdrs = [T.HOST, *headers] + ([(S.HEADER, self.credential)] if credential else [])
        status, headers_out, body = T.call(app, 'GET', path, hdrs)
        return status, json.loads(body), dict(headers_out)

    def test_the_projection_answers_behind_the_guards(self):
        self.fixture_attempt()
        sources = Outcome.build(self, 'listed')
        config = {'project_repository': str(sources.repo), 'project_repository_id': 'aieh-d1-demo',
                  'backlog_command': 'backlog'}
        app = self.app(config, conversations=sources.conversations)
        patch = E.in_process_backlog()
        patch.start()
        self.addCleanup(patch.stop)
        with mock.patch.dict(os.environ, {'FAKE_BACKLOG_SNAPSHOT': str(sources.snapshot)}), \
                mock.patch.object(P.planning, 'tool_argv', lambda spec: list(E.FAKE_BACKLOG)):
            status, answer, headers = self.get(app, f'/outcomes/{OUTCOME_ID}')
            self.assertEqual(status, 200, answer)
            self.assertEqual(answer, json.loads(json.dumps(sources.project(self))))
            self.assertEqual(headers['cache-control'], 'no-store')
            self.assertEqual(answer['coverage']['code'], 'ARCHIVED_TASKS_NOT_ENUMERABLE')
            for path, headers_, code, expected in (
                    (f'/outcomes/{OUTCOME_ID}', (), 'SESSION_CREDENTIAL_MISSING', 401),
                    (f'/outcomes/{OUTCOME_ID}', (('origin', 'http://127.0.0.1:9999'),), 'ORIGIN_NOT_ALLOWED', 403)):
                with self.subTest(code=code):
                    status, answer, _ = self.get(app, path, *headers_, credential=code != 'SESSION_CREDENTIAL_MISSING')
                    self.assertEqual((status, answer['code']), (expected, code))
            status, _, body = T.call(app, 'GET', f'/outcomes/{OUTCOME_ID}', [('host', 'localhost:13310'),
                                                                             (S.HEADER, self.credential)])
            self.assertEqual((status, T.code_of(body)), (400, 'HOST_NOT_ALLOWED'))
            status, _, body = T.call(app, 'POST', f'/outcomes/{OUTCOME_ID}', [T.HOST, (S.HEADER, self.credential)])
            self.assertEqual((status, T.code_of(body)), (405, 'METHOD_NOT_ALLOWED'))

    def test_each_refusal_has_its_stable_code(self):
        config = {'project_repository': str(self.scratch), 'project_repository_id': 'aieh-d1-demo',
                  'backlog_command': 'no-such-backlog-command-u41'}
        cases = [(self.app(config), f'/outcomes/{OUTCOME_ID}@{"a" * 40}', 400, 'OUTCOME_INVALID'),
                 (self.app(config), '/outcomes/not-an-outcome', 400, 'OUTCOME_INVALID'),
                 (self.app(None), f'/outcomes/{OUTCOME_ID}', 503, 'PROJECTION_PROJECT_UNCONFIGURED'),
                 (self.app({'project_repository': 'relative'}), f'/outcomes/{OUTCOME_ID}', 503,
                  'PROJECTION_CONFIG_INVALID'),
                 (self.app(config, store=False), f'/outcomes/{OUTCOME_ID}', 503, 'PROJECTION_STORE_UNCONFIGURED'),
                 (self.app(config), f'/outcomes/{OUTCOME_ID}', 503, 'PROJECTION_BACKLOG_UNAVAILABLE')]
        before = (file_state(Path(self.store.path)), self.session.dump())
        for app, path, status, code in cases:
            with self.subTest(code=code, path=path):
                got, answer, _ = self.get(app, path)
                self.assertEqual((got, answer['code']), (status, code))
                self.assertEqual(answer['remedy'], P.REMEDIES[code])
        self.assertEqual((file_state(Path(self.store.path)), self.session.dump()), before)


if __name__ == '__main__':
    unittest.main()
