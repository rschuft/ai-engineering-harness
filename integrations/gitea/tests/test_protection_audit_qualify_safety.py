"""The live protection-auditor qualify phase's stop rules (test_protection_audit_live.py ``Qualification``; Owner
authorization OA-16 Act D), offline.

The live test method itself runs here against ``QualifyGitea``: protection_fake.ProtectionGitea (the auditor's
reads, in memory with gitea_host.http_get's signature, no socket) plus the site administrator's routes by basic
authentication (``GET /user``, the organization, the repository and its PATCH, the collaborators and their
PUT, the rules with POST, PATCH and DELETE), which apply each write to the fake's state. ``hooks`` replace an
administrator's answer (a status, a write swallowed, an exception after or before applying it). The protection
check is the real protection_check.verify against that fake, through ``Verifier``, which can replace the n-th
verdict (a fake verifier).

Covered: a full pass sends exactly the five injections and five restorations, in order; a failing precondition
(identity, scope, baseline digest, verdict, read-back, an exception) sends no mutation; after (a) a failed
restoration, (b) a read-back difference, (c) an unexpected verdict or digest, (d) a missing or unnamed drift,
(e) an injection answering non-2xx and (f) an exception (an uncertain outcome) no later injection is sent,
exactly one restoration is attempted for the stopped injection, nothing is retried, the final state is read
and reported with the injections not sent, and the run fails; the latch holds when the driver is called again.
Every value is synthetic.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import sys
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


L = _load('test_protection_audit_live', HERE / 'test_protection_audit_live.py')
PF = _load('aieh_gitea_protection_fake', HERE / 'protection_fake.py')
R, PC, G = L.R, L.PC, L.G
REPO = f'/repos/{PF.REPOSITORY}'
ADMIN_PASSWORD = 'synthetic-site-admin-password'
ADMIN_AUTH = 'Basic ' + base64.b64encode(f'{G.SITE_ADMIN}:{ADMIN_PASSWORD}'.encode()).decode()
QUALIFY_TEST = 'test_injected_drift_is_detected_and_restored'
VERIFIER = R.ROLES['verifier']['user']
LABELS = [s.label for s in L.injections()]


class Provider:
    """The credential provider: the auditor's token entry and the site administrator's password entry."""

    def get(self, target):
        return {R.target('protection-audit'): (PF.AUDITOR, PF.AUDIT_TOKEN),
                G.FINAL_TARGETS[G.SITE_ADMIN]: (G.SITE_ADMIN, ADMIN_PASSWORD)}.get(target)


PROVIDER = Provider()


class QualifyGitea(PF.ProtectionGitea):
    """ProtectionGitea with the site administrator's routes. ``admin_writes`` lists every write of the
    administrator (method, route, body) in order, sent or failed; ``hooks`` are called before a request of the
    administrator is applied, ``hook(fake, method, route, body)``: an answer replaces it, an exception is raised
    to the caller, None applies it."""

    def __init__(self):
        super().__init__(R)
        self.admin_writes, self.hooks, self.created = [], [], 10

    def _handle(self, method, path, headers, body):
        if headers.get('authorization') != ADMIN_AUTH:
            return super()._handle(method, path, headers, body)
        route = urllib.parse.unquote(urllib.parse.urlsplit(path).path.removeprefix('/api/v1'))
        payload = json.loads(body) if body else None
        if method != 'GET':
            self.admin_writes.append((method, route, payload))
        for hook in self.hooks:
            answer = hook(self, method, route, payload)
            if answer is not None:
                return answer
        return self.administer(method, route, payload)

    def administer(self, method, route, body):
        if (method, route) == ('GET', '/user'):
            return self.reply(200, {'login': G.SITE_ADMIN, 'is_admin': True})
        if (method, route) == ('GET', f'/orgs/{R.FIXTURE_ORG}'):
            return self.reply(200, {'username': R.FIXTURE_ORG})
        if route == REPO:
            if method == 'PATCH':
                self.repo.update({k: v for k, v in body.items() if k in self.repo})
            return self.reply(200, {**self.repo, 'permissions': {'admin': True, 'push': True, 'pull': True}})
        if route == f'{REPO}/collaborators':
            return self.reply(200, [{'id': n, 'login': u} for n, u in enumerate(self.collaborators)],
                              {'x-total-count': str(len(self.collaborators))})
        if route.startswith(f'{REPO}/collaborators/'):
            user = route[len(f'{REPO}/collaborators/'):]
            if method == 'GET' and user.endswith('/permission'):
                level = self.collaborators.get(user[:-len('/permission')], 'none')
                return self.reply(200, {'permission': level, 'role_name': level, 'user': {'login': user}})
            if method == 'PUT':
                self.collaborators[user] = body['permission']
                return self.reply(204, None)
        if route == f'{REPO}/branch_protections':
            if method == 'POST':
                self.created += 1
                self.rules.append(PF.rule_view({f: body[f] for f in R.PROTECTION_FIELDS}, self.created))
                return self.reply(201, self.rules[-1])
            return self.reply(200, sorted(self.rules, key=PF._order))
        if route.startswith(f'{REPO}/branch_protections/'):
            name = route[len(f'{REPO}/branch_protections/'):]
            rule = next((r for r in self.rules if r['rule_name'] == name), None)
            if rule is None:
                return self.reply(404, {'message': 'branch protection does not exist'})
            if method == 'DELETE':
                self.rules.remove(rule)
                return self.reply(204, None)
            if method == 'PATCH':
                rule.update({k: v for k, v in body.items() if k in R.PROTECTION_FIELDS and k != 'rule_name'})
                return self.reply(200, rule)
        return self.reply(404, {'message': f'no route {method} {route}'})


class Verifier:
    """The protection check (protection_check.verify against the fake), counting its calls; ``script[n]``
    replaces the n-th answer (from 0): a Verdict, or an exception to raise."""

    def __init__(self, fake):
        self.fake, self.script, self.calls = fake, {}, 0

    def __call__(self):
        n, self.calls = self.calls, self.calls + 1
        scripted = self.script.get(n)
        if isinstance(scripted, BaseException):
            raise scripted
        if scripted is not None:
            return scripted
        return PC.verify(PROVIDER, 3000, PF.REPOSITORY, R.DEFAULT_BRANCH, http=self.fake)


# The verifier's calls in a full pass: 0 the baseline; scenario k (from 0) 1 + 2k its drift, 2 + 2k its
# restoration; 11 the last.
def drift_call(k):
    return 1 + 2 * k


def restored_call(k):
    return 2 + 2 * k


def trace(fake):
    """The administrator's writes as 'inject N', 'restore' (apply_fixture's PATCH of the repository, one per
    restoration) and 'delete RULE'; apply_fixture's other writes are left out."""
    scenarios = L.injections()
    out = []
    for method, route, body in fake.admin_writes:
        n = next((n for n, s in enumerate(scenarios) if (s.method, s.path, s.body) == (method, route, body)), None)
        if n is not None:
            out.append(f'inject {n + 1}')
        elif (method, route, body) == ('PATCH', REPO, R.repository_settings()):
            out.append('restore')
        elif method == 'DELETE':
            out.append('delete ' + route.rsplit('/branch_protections/', 1)[1])
    return out


def passed_through(k):
    """The trace of scenarios 1..K passing (each injection, then its restoration)."""
    out = []
    for n in range(1, k + 1):
        out += [f'inject {n}'] + (['delete aieh-qualify/*'] if n == 3 else []) + ['restore']
    return out


def when(method, route_suffix, nth=1, body=None):
    """A hook predicate: the NTH request of METHOD to REPO + ROUTE_SUFFIX (and, when given, with BODY)."""
    seen = [0]

    def match(method_, route, payload):
        if (method_, route) == (method, REPO + route_suffix) and (body is None or payload == body):
            seen[0] += 1
            return seen[0] == nth
        return False
    return match


def answer(predicate, status, payload=None):
    def hook(fake, method, route, body):
        return fake.reply(status, payload or {'message': 'a fault of the fake'}) if predicate(method, route, body) \
            else None
    return hook


def swallow(predicate, status=200):
    """The write answers STATUS but is not applied."""
    def hook(fake, method, route, body):
        return fake.reply(status, {}) if predicate(method, route, body) else None
    return hook


def raise_after(predicate, exc):
    """The write is applied, then the answer is lost."""
    def hook(fake, method, route, body):
        if predicate(method, route, body):
            fake.administer(method, route, body)
            raise exc
        return None
    return hook


def raise_before(predicate, exc):
    def hook(fake, method, route, body):
        if predicate(method, route, body):
            raise exc
        return None
    return hook


class Qualify(unittest.TestCase):
    def setUp(self):
        self.results = []
        for patch in (mock.patch.object(L, 'RESULTS', self.results), mock.patch.object(L, 'REPORT', None),
                      mock.patch.object(L, 'BASELINE', None),
                      mock.patch.object(L.G, 'http_get', side_effect=AssertionError('a real HTTP request'))):
            patch.start()
            self.addCleanup(patch.stop)
        self.fake = QualifyGitea()
        self.verifier = Verifier(self.fake)
        self.digest = PC.verify(PROVIDER, 3000, PF.REPOSITORY, R.DEFAULT_BRANCH, http=QualifyGitea()).digest

    def run_live(self):
        """The live test method against the fake; the QualificationStopped it raised, or None."""
        case = L.QualifyLive(QUALIFY_TEST)
        case.ctx = SimpleNamespace(port=3000, provider=PROVIDER, token=PF.AUDIT_TOKEN, http=self.fake)
        case.verify = self.verifier
        try:
            getattr(case, QUALIFY_TEST)()
        except L.QualificationStopped as exc:
            return exc
        finally:
            case.doCleanups()
        return None

    def stop_row(self):
        rows = [r for r in self.results if r['action'] == 'qualify: STOPPED']
        self.assertEqual(len(rows), 1)
        return rows[0]

    def assert_stopped(self, stopped, check, sent, restored_last=True):
        """Stopped at CHECK after SENT injections (labels), the later ones not sent and reported so."""
        self.assertIsInstance(stopped, L.QualificationStopped)
        self.assertIsInstance(stopped, AssertionError)   # the test fails
        row = self.stop_row()
        self.assertEqual(row['failed_check'], check)
        self.assertEqual(row['not_sent'], LABELS[sent:])
        self.assertEqual([r['action'] for r in self.results if r.get('status') == 'not sent'],
                         [f'inject: {label}' for label in LABELS[sent:]])
        self.assertIn('read_back', row['final_state'])
        self.assertIn('verdict', row['final_state'])
        self.assertIn('Not a PASS', str(stopped))
        injections = [t for t in trace(self.fake) if t.startswith('inject')]
        self.assertEqual(injections, [f'inject {n}' for n in range(1, sent + 1)])   # each once, in order
        return row

    def assert_no_mutation(self):
        self.assertEqual(self.fake.admin_writes, [])


class FullPass(Qualify):
    def test_five_injections_and_five_restorations_in_order(self):
        self.assertIsNone(self.run_live())
        self.assertEqual(trace(self.fake), passed_through(5))
        self.assertEqual(self.verifier.calls, 12)
        rows = {r['action']: r for r in self.results}
        for label in LABELS:
            row = rows[f'inject: {label}']
            self.assertEqual(row['result'], 'passed')
            self.assertIn(row['injection']['status'], (200, 201, 204))
            self.assertEqual(row['drift']['status'], 'drift')
            self.assertEqual(row['read_back'], [])
            self.assertEqual(row['verdict']['digest'], self.digest)
            self.assertTrue(row['verdict']['digest_equals_baseline'])
            self.assertTrue(row['restoration'])
        baseline = rows['qualify: baseline precondition (no mutation is sent unless it passes)']
        self.assertEqual(baseline['baseline'], {'digest': self.digest, 'source': 'the first verdict'})
        self.assertEqual(baseline['auditor'], {'status': 200, 'login': PF.AUDITOR, 'scopes': ['read:repository']})
        final = rows['qualify: after the last injection']
        self.assertEqual((final['result'], final['probe_rule_present'], final['verifier_permission']),
                         ('passed', False, 'read'))
        self.assertNotIn('qualify: STOPPED', rows)
        self.assertEqual(self.fake.collaborators, dict(R.collaborators()))

    def test_the_baseline_from_the_environment(self):
        with mock.patch.object(L, 'BASELINE', self.digest):
            self.assertIsNone(self.run_live())
        row = self.results[0]
        self.assertEqual(row['baseline'], {'digest': self.digest, 'source': L.BASELINE_VARIABLE})

    def test_each_drift_is_named(self):
        """Control on the fake: each injection, applied alone, is drift naming it."""
        for scenario in L.injections():
            with self.subTest(scenario=scenario.label):
                fake = QualifyGitea()
                api = R.Api(3000, http=fake, basic=(G.SITE_ADMIN, ADMIN_PASSWORD))
                self.assertIn(api.call(scenario.method, scenario.path, scenario.body)[0], (200, 201, 204))
                verdict = PC.verify(PROVIDER, 3000, PF.REPOSITORY, R.DEFAULT_BRANCH, http=fake)
                self.assertEqual(verdict.status, 'drift')
                self.assertTrue(any(scenario.names in p for p in verdict.problems), verdict.problems)
                self.assertTrue(L.declaration_differences(L.read_back(api)))


class Precondition(Qualify):
    def test_a_failing_precondition_sends_no_mutation(self):
        bad = 'sha256:' + '1' * 64
        cases = {
            'auditor identity': [lambda f: f.tokens[PF.AUDIT_TOKEN].update(scopes=['read:repository',
                                                                                     'write:repository'])],
            'baseline verdict': [lambda f: f.repo.update(allow_squash_merge=True)],
        }
        for check, setups in cases.items():
            with self.subTest(check=check):
                self.setUp()
                for setup in setups:
                    setup(self.fake)
                stopped = self.run_live()
                self.assert_stopped(stopped, check, 0)
                self.assert_no_mutation()
        for value, detail, calls in ((bad, 'is not AIEH_PROTECTION_AUDIT_BASELINE', 2),
                                     ('', 'not sha256:<64 hex>', 1), ('sha256:abc', 'not sha256:<64 hex>', 1)):
            with self.subTest(baseline=value):
                self.setUp()
                with mock.patch.object(L, 'BASELINE', value):
                    row = self.assert_stopped(self.run_live(), 'baseline digest', 0)
                self.assertIn(detail, row['detail'])
                self.assertEqual(self.verifier.calls, calls)   # a malformed value: refused before the check
                self.assert_no_mutation()

    def test_another_login_is_refused(self):
        self.fake.tokens[PF.AUDIT_TOKEN]['login'] = PF.VERIFIER
        self.assert_stopped(self.run_live(), 'auditor identity', 0)
        self.assert_no_mutation()
        self.assertEqual(self.verifier.calls, 1)   # the final state's verdict only

    def test_a_read_back_difference_or_an_exception_before_any_mutation(self):
        verified = PC.Verdict('verified', 'VERIFIED', '', self.digest)
        self.fake.collaborators['aieh-stranger'] = 'read'   # read back; the check is scripted verified
        self.verifier.script[0] = verified
        row = self.assert_stopped(self.run_live(), 'baseline read-back', 0)
        self.assertIn('aieh-stranger', ' '.join(self.results[0]['read_back']))
        self.assertEqual(row['restoration_after_stop'], 'none owed: no injection of this step was sent')
        self.assert_no_mutation()
        self.setUp()
        self.verifier.script[0] = ConnectionResetError('lost')
        stopped = self.run_live()
        self.assert_stopped(stopped, 'baseline verdict', 0)
        self.assertIn('uncertain outcome: ConnectionResetError', str(stopped))
        self.assert_no_mutation()


class StopCases(Qualify):
    def test_a_failed_restoration_stops_before_the_next_injection(self):
        # apply_fixture's PATCH of the repository in scenario 2's restoration answers 500
        self.fake.hooks.append(answer(when('PATCH', '', nth=2, body=R.repository_settings()), 500))
        row = self.assert_stopped(self.run_live(), 'restoration', 2)
        self.assertEqual(trace(self.fake), passed_through(1) + ['inject 2', 'restore'])
        self.assertEqual(row['restoration_after_stop'],
                         'not attempted again: its one restoration was already attempted')
        scenario = next(r for r in self.results if r['action'] == f'inject: {LABELS[1]}')
        self.assertIn('API_UNEXPECTED', scenario['restoration_failed'])
        self.assertEqual(scenario['restoration'][-1]['status'], 500)

    def test_a_restoration_that_raises_stops_too(self):
        self.fake.hooks.append(raise_before(when('DELETE', '/branch_protections/aieh-qualify/*'),
                                            ConnectionResetError('lost')))
        self.assert_stopped(self.run_live(), 'restoration', 3)
        self.assertEqual(trace(self.fake), passed_through(2) + ['inject 3', 'delete aieh-qualify/*'])
        scenario = next(r for r in self.results if r['action'] == f'inject: {LABELS[2]}')
        self.assertEqual(scenario['restoration'][-1]['status'], 'uncertain: ConnectionResetError: lost')
        # the probe rule is still there and reported, not repaired
        self.assertIn("rule 'aieh-qualify/*' is not declared", self.stop_row()['final_state']['read_back'])

    def test_a_refused_deletion_of_the_probe_rule_ends_the_restoration(self):
        self.fake.hooks.append(answer(when('DELETE', '/branch_protections/aieh-qualify/*'), 500))
        row = self.assert_stopped(self.run_live(), 'restoration', 3)
        self.assertEqual(trace(self.fake), passed_through(2) + ['inject 3', 'delete aieh-qualify/*'])
        self.assertIn('answered 500', row['detail'])

    def test_a_read_back_difference_stops(self):
        # scenario 1's restoration PATCH of main answers 200 but is not applied
        self.fake.hooks.append(swallow(when('PATCH', '/branch_protections/main', nth=2)))
        row = self.assert_stopped(self.run_live(), 'read-back', 1)
        self.assertEqual(trace(self.fake), ['inject 1', 'restore'])
        self.assertIn('main.block_admin_merge_override is False, declared True', row['detail'])
        self.assertEqual(self.verifier.calls, 3)   # baseline, drift, final state: no restored verdict asked
        self.assertIn('main.block_admin_merge_override is False, declared True', row['final_state']['read_back'])
        self.assertEqual(row['final_state']['verdict']['status'], 'drift')

    def test_an_undeclared_collaborator_in_the_read_back_stops(self):
        def add_stranger(fake, method, route, body):
            if (method, route, body) == ('PATCH', REPO, R.repository_settings()):
                fake.collaborators['aieh-stranger'] = 'read'
        self.fake.hooks.append(add_stranger)
        self.assert_stopped(self.run_live(), 'read-back', 1)
        self.assertEqual(trace(self.fake), ['inject 1', 'restore'])

    def test_an_unexpected_verdict_or_digest_stops(self):
        other = 'sha256:' + '2' * 64
        for verdict in (PC.Verdict('verified', 'VERIFIED', '', other),
                        PC.Verdict('drift', 'DRIFT', '', other, ('something',)),
                        PC.Verdict('unverified', 'READ_FAILED', 'x', None, ('x',))):
            with self.subTest(status=verdict.status):
                self.setUp()
                self.verifier.script[restored_call(1)] = verdict
                row = self.assert_stopped(self.run_live(), 'restored verdict', 2)
                self.assertEqual(trace(self.fake), passed_through(2))
                self.assertEqual(row['restoration_after_stop'],
                                 'not attempted again: its one restoration was already attempted')

    def test_an_unexpected_final_verdict_stops_without_another_restoration(self):
        self.verifier.script[11] = PC.Verdict('verified', 'VERIFIED', '', 'sha256:' + '3' * 64)
        row = self.assert_stopped(self.run_live(), 'final verdict', 5)
        self.assertEqual(trace(self.fake), passed_through(5))
        self.assertEqual(row['restoration_after_stop'], 'none owed: no injection of this step was sent')

    def test_a_missing_drift_stops_after_one_restoration(self):
        # the extra rule's POST answers 201 but is not applied: the check answers verified
        self.fake.hooks.append(swallow(when('POST', '/branch_protections'), 201))
        row = self.assert_stopped(self.run_live(), 'drift detection', 3)
        self.assertEqual(trace(self.fake), passed_through(2) + ['inject 3', 'restore'])
        self.assertEqual(row['restoration_after_stop'], 'attempted once and completed (final state below)')
        self.assertEqual(row['final_state']['read_back'], [])

    def test_a_drift_not_naming_the_injection_stops(self):
        self.verifier.script[drift_call(0)] = PC.Verdict('drift', 'DRIFT', '', 'sha256:' + '4' * 64,
                                                         ("the repository's allow_rebase is True",))
        self.assert_stopped(self.run_live(), 'drift detection', 1)
        self.assertEqual(trace(self.fake), ['inject 1', 'restore'])

    def test_an_unverified_answer_naming_the_injection_is_no_drift(self):
        names = L.injections()[0].names
        self.verifier.script[drift_call(0)] = PC.Verdict('unverified', 'READ_FAILED', names, None, (names,))
        row = self.assert_stopped(self.run_live(), 'drift detection', 1)
        self.assertIn('answered unverified', row['detail'])
        self.assertEqual(trace(self.fake), ['inject 1', 'restore'])

    def test_an_injection_answering_non_2xx_stops_after_one_restoration(self):
        for status in (422, 500, 302):
            with self.subTest(status=status):
                self.setUp()
                self.fake.hooks.append(answer(when('PUT', f'/collaborators/{VERIFIER}', body={'permission': 'admin'}),
                                              status))
                row = self.assert_stopped(self.run_live(), 'injection', 4)
                self.assertEqual(trace(self.fake), passed_through(3) + ['inject 4', 'restore'])
                self.assertEqual(self.verifier.calls, 1 + 2 * 3 + 1)   # no drift check of scenario 4
                self.assertEqual(row['final_state']['verdict']['digest'], self.digest)

    def test_an_exception_is_an_uncertain_outcome_that_stops(self):
        # the injection is applied, then its answer is lost
        self.fake.hooks.append(raise_after(when('PATCH', '', body={'allow_squash_merge': True}),
                                           ConnectionResetError('lost')))
        row = self.assert_stopped(self.run_live(), 'injection', 5)
        self.assertEqual(trace(self.fake), passed_through(4) + ['inject 5', 'restore'])
        self.assertIn('uncertain outcome: the injection raised ConnectionResetError', row['detail'])
        self.assertEqual(row['final_state']['read_back'], [])   # the one restoration undid it
        self.assertFalse(self.fake.repo['allow_squash_merge'])

    def test_an_exception_in_a_check_stops(self):
        for call, check, sent in ((drift_call(0), 'drift detection', 1), (restored_call(2), 'restored verdict', 3)):
            with self.subTest(check=check):
                self.setUp()
                self.verifier.script[call] = OSError('the check lost its connection')
                row = self.assert_stopped(self.run_live(), check, sent)
                self.assertIn('uncertain outcome: OSError', row['detail'])
                expected = passed_through(sent)
                self.assertEqual(trace(self.fake), expected)   # one restoration of the last injection, no more

    def test_an_exception_in_the_read_back_stops_without_another_restoration(self):
        def fail_read_back(fake, method, route, body):
            if (method, route) == ('GET', f'{REPO}/collaborators') and trace(fake) == passed_through(1):
                raise ConnectionResetError('lost')
        self.fake.hooks.append(fail_read_back)
        row = self.assert_stopped(self.run_live(), 'read-back', 1)
        self.assertEqual(trace(self.fake), passed_through(1))
        self.assertEqual(row['restoration_after_stop'],
                         'not attempted again: its one restoration was already attempted')


class Latch(Qualify):
    def driver(self):
        admin = R.admin_api(PROVIDER, 3000, self.fake)
        auditor = R.Api(3000, PF.AUDIT_TOKEN, self.fake)
        return L.Qualification(admin, self.verifier, lambda: auditor.call('GET', '/token'), rows=self.results)

    def test_once_stopped_no_injection_is_sent(self):
        q = self.driver()
        self.verifier.script[restored_call(0)] = PC.Verdict('verified', 'VERIFIED', '', 'sha256:' + '5' * 64)
        with self.assertRaises(L.QualificationStopped):
            q.run()
        writes = list(self.fake.admin_writes)
        for again in (q.run, lambda: q.scenario(q.scenarios[1]), lambda: q.scenario(q.scenarios[0])):
            with self.assertRaises(L.QualificationStopped) as caught:
                again()
            self.assertIn('stopped earlier', str(caught.exception))
        self.assertEqual(self.fake.admin_writes, writes)
        self.assertEqual(q.sent, [LABELS[0]])
        self.assertEqual(q.restorations, [LABELS[0]])

    def test_the_last_step_checks_the_probe_rule_and_the_verifier_s_permission_itself(self):
        """Beyond the read-back's differences (here made empty): the probe rule absent, the verifier bot read."""
        for scenario, check in ((L.injections()[2], 'present'), (L.injections()[3], f"{VERIFIER}: 'admin'")):
            with self.subTest(scenario=scenario.label):
                self.setUp()
                api = R.Api(3000, http=self.fake, basic=(G.SITE_ADMIN, ADMIN_PASSWORD))
                api.call(scenario.method, scenario.path, scenario.body)
                q = self.driver()
                q.baseline = self.digest
                with mock.patch.object(L, 'declaration_differences', return_value=[]), \
                        self.assertRaises(L.QualificationStopped):
                    q.final()
                row = self.stop_row()
                self.assertEqual(row['failed_check'], 'final read-back')
                self.assertIn(check, row['detail'])
                self.assertEqual(trace(self.fake), [f'inject {L.injections().index(scenario) + 1}'])

    def test_the_rows_name_the_stop(self):
        self.verifier.script[drift_call(1)] = PC.Verdict('verified', 'VERIFIED', '', self.digest)
        with self.assertRaises(L.QualificationStopped):
            self.driver().run()
        stopped = self.stop_row()
        self.assertEqual(set(stopped), {'action', 'failed_check', 'scenario', 'detail', 'restoration_after_stop',
                                        'final_state', 'not_sent'})
        self.assertEqual(stopped['scenario'], LABELS[1])
        self.assertEqual(stopped['final_state']['verdict']['digest_equals_baseline'], True)
        json.dumps(self.results)   # the report is JSON
        self.assertNotIn(PF.AUDIT_TOKEN, json.dumps(self.results))
        self.assertNotIn(ADMIN_PASSWORD, json.dumps(self.results))


class ReadBack(unittest.TestCase):
    def test_declaration_differences(self):
        api = R.Api(3000, http=QualifyGitea(), basic=(G.SITE_ADMIN, ADMIN_PASSWORD))
        observed = L.read_back(api)
        self.assertEqual(L.declaration_differences(observed), [])
        main = next(r for r in observed['branch_protections'] if r['rule_name'] == 'main')
        main['approvals_whitelist_username'] = list(reversed(main['approvals_whitelist_username']))
        main['status_check_contexts'] = None
        self.assertEqual(L.declaration_differences(observed), [])   # list fields sorted, null equal to []
        changes = [
            (lambda o: o['settings'].update(allow_rebase=True), "the repository's allow_rebase is True"),
            (lambda o: o['collaborator_permissions'].update({VERIFIER: 'write'}), f'collaborator {VERIFIER}'),
            (lambda o: o['roster'].append('aieh-stranger'), 'the collaborators are'),
            (lambda o: o['branch_protections'].append(R._total_rule('x/*', 4)), "rule 'x/*' is not declared"),
            (lambda o: o['branch_protections'].pop(), 'the declared rule'),
            (lambda o: o['branch_protections'][0].update(require_signed_commits=True), '.require_signed_commits is'),
            (lambda o: o['branch_protections'][0].update(merge_whitelist_usernames=['someone']),
             '.merge_whitelist_usernames is'),
            (lambda o: o['repository'].update(full_name='other/repo'), 'the repository answers as'),
        ]
        for change, expected in changes:
            with self.subTest(expected=expected):
                copy = json.loads(json.dumps(observed))
                change(copy)
                differences = L.declaration_differences(copy)
                self.assertTrue(any(expected in d for d in differences), differences)


class Skips(unittest.TestCase):
    def test_the_qualify_class_skips_without_the_opt_in(self):
        fake = QualifyGitea()
        with mock.patch.object(L, 'PHASE', ''), mock.patch.object(L, '_LIVE', []), \
                mock.patch.object(L, 'RESULTS', []), mock.patch.object(L, 'REPORT', None), \
                mock.patch.object(L, 'BASELINE', 'sha256:' + '6' * 64), \
                mock.patch.object(L.G, 'credential_provider', side_effect=AssertionError('read Credential Manager')):
            result = unittest.TestResult()
            unittest.defaultTestLoader.loadTestsFromTestCase(L.QualifyLive).run(result)
        # the class skips in setUpClass: its one test is not run
        self.assertEqual((result.testsRun, len(result.skipped), result.failures, result.errors), (0, 1, [], []))
        self.assertIn('opt-in', result.skipped[0][1])
        self.assertEqual(fake.requests, [])


if __name__ == '__main__':
    unittest.main()
