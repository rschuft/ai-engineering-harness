"""Tests for the attempt's authority (plan leaf E-01.8; the I1 integration design, R8 and R11, as the engineering
manager's rulings of E-01.8 settled them; decision 0026 points 1, 2 and 4), offline.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_authority.py -v

An attempt's authority is ``live`` or ``fixture``, declared by its profile's pinned route allowlist and bound at
reservation by the allowlist's digest. Shown here, on the checked-in ``fixture-d1-replay`` profile (bound fixture) and
the checked-in ``strong-windows-qemu-whpx`` declaration (bound live, E-05.2's fixture), their creates answered by the
fixture catalog's cited core:

* the vocabulary and the two declarations' equality (``Vocabulary``);
* the client's equality, R8 point 4: a transport declaring another authority than the allowlist is
  TRANSPORT_AUTHORITY_MISMATCH when the client is built, with no call (``Client``);
* dispatch, R8 points 4 and 5: a fixture profile refused for a live transport and a live profile refused as fixture,
  each with a stable code; a credential provider of another authority refused before any entry is read; a fixture
  attempt dispatched and labelled; a live attempt's records without the key (``Dispatch``);
* the attempt run's observers, R8 point 5 (``Observers``), the result path's Gitea target and provider at the caller's
  seam (``Publication``);
* R11's labels on the launch receipt, the end journal and record and the stop receipts (``Labels``);
* ``recover`` settles an interrupted fixture attempt through its fixture transport, never holding it for its wrapper
  (``Recovery``);
* R8 point 7's census (``Census``).
"""
from pathlib import Path
import ast
import dataclasses
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


ci = _load('test_d1_checked_in_template', HERE / 'test_d1_checked_in_template.py')
tar = _load('test_attempt_run', HERE / 'test_attempt_run.py')
di, store_mod, cc, NT, NS = ci.di, ci.store_mod, ci.cc, ci.NT, ci.native_tests.NS
AC = cc.AC
AR, AE = tar.AR, tar.AE
LG = _load('launch_gate', HERE.parent / 'launch_gate.py')
RR = _load('restart_recovery', HERE.parent / 'restart_recovery.py')
RP = _load('result_path', HERE.parent / 'result_path.py')

FIX = 'fixture-d1-replay'
ACTOR = 'e-01.8-test'
SOURCE = 'agentfixture catalog container-inspect (F-04.2 4.3, 7; D1 5 (3), (5b))'
LOCK = REPO / 'profiles' / ci.REAL / 'provision.lock.json'
DECLARATION = {'authority': 'fixture', 'kind': 'loopback-fixture'}


class Seam:
    """A seam declaring AUTHORITY (R8 point 3) that calls CALL as it is, counting the calls."""

    def __init__(self, call, authority):
        self.call, self.authority, self.count = call, authority, 0

    def __call__(self, *args, **kwargs):
        self.count += 1
        return self.call(*args, **kwargs)


class Crash(BaseException):
    """A dispatcher dying at a point the test chooses (never caught as an Exception)."""


def provider(authority=None):
    """The native token's one entry in an observed in-memory provider, declaring AUTHORITY (none: live)."""
    held = NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, ci.TOKEN)})
    if authority is not None:
        held.authority = authority
    return held


def routes(name):
    return (REPO / 'profiles' / name / 'agent-server' / 'routes.json').read_bytes()


def sha(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


class Vocabulary(unittest.TestCase):
    category = 'unit'

    def test_the_declarations(self):
        self.assertEqual(di.declared_authority(None), di.LIVE)
        self.assertEqual(di.declared_authority(dict(DECLARATION)), di.FIXTURE)
        for other in ({'authority': 'fixture'}, {'authority': 'live', 'kind': 'loopback-fixture'},
                      {**DECLARATION, 'port': 13320}, 'fixture', []):
            with self.subTest(declaration=other):
                with self.assertRaises(di.DispatchRefused) as caught:
                    di.declared_authority(other)
                self.assertEqual(caught.exception.code, 'TRANSPORT_DECLARATION_MISMATCH')
        self.assertEqual((di.authority_label(di.LIVE), di.authority_label(di.FIXTURE)), ({}, {'authority': 'fixture'}))
        self.assertEqual((di.seam_authority(object()), di.seam_authority(Seam(None, 'fixture'))), ('live', 'fixture'))

    def test_the_two_declarations_must_agree(self):
        declared = json.loads((REPO / 'profiles' / FIX / 'profile.json').read_bytes())
        allowlist = json.loads(routes(FIX))
        self.assertEqual(di.check_transport_declarations(declared, allowlist), di.FIXTURE)
        live = json.loads((REPO / 'profiles' / ci.REAL / 'profile.json').read_bytes())
        self.assertEqual(di.check_transport_declarations(live, json.loads(routes(ci.REAL))), di.LIVE)
        for profile, allow in ((live, allowlist), (declared, json.loads(routes(ci.REAL)))):
            with self.assertRaises(di.DispatchRefused) as caught:
                di.check_transport_declarations(profile, allow)
            self.assertEqual(caught.exception.code, 'TRANSPORT_DECLARATION_MISMATCH')


class Client(unittest.TestCase):
    category = 'unit'

    def refused(self, raw, transport):
        with self.assertRaises(di.DispatchRefused) as caught:
            di.AgentServerClient(raw, transport, routes_sha256=sha(raw))
        return caught.exception

    def test_each_mismatch_is_refused_when_the_client_is_built(self):
        undeclared = Seam(lambda *a, **k: self.fail('called'), None)
        del undeclared.authority                              # no attribute: live
        claimed = Seam(lambda *a, **k: self.fail('called'), 'fixture')
        for raw, transport, declared, presented in ((routes(FIX), undeclared, 'fixture', 'live'),
                                                    (routes(ci.REAL), claimed, 'live', 'fixture'),
                                                    (routes(FIX), Seam(None, 'live'), 'fixture', 'live')):
            with self.subTest(declared=declared, presented=presented):
                refusal = self.refused(raw, transport)
                self.assertEqual((refusal.code, refusal.context), ('TRANSPORT_AUTHORITY_MISMATCH',
                                                                   {'declared': declared, 'presented': presented}))
                self.assertIn(refusal.code, di.REFUSALS)
        self.assertEqual((undeclared.count, claimed.count), (0, 0), 'zero transport calls')

    def test_an_agreeing_transport_is_taken(self):
        core = AC.AgentServerCore()
        self.addCleanup(core.close)
        client = di.AgentServerClient(routes(FIX), Seam(core, 'fixture'), routes_sha256=sha(routes(FIX)))
        self.assertEqual(client.authority, 'fixture')
        self.assertEqual(client.call('GET', '/server_info')['status'], 200)
        self.assertEqual(di.AgentServerClient(routes(ci.REAL), core, routes_sha256=sha(routes(ci.REAL))).authority,
                         'live')

    def test_a_declaration_out_of_the_vocabulary_is_refused(self):
        data = json.loads(routes(FIX))
        data['transport'] = {'authority': 'fixture', 'kind': 'elsewhere'}
        raw = json.dumps(data).encode('utf-8')
        self.assertEqual(self.refused(raw, Seam(None, 'fixture')).code, 'TRANSPORT_DECLARATION_MISMATCH')


class Bound(ci.CheckedInFixture):
    """The checked-in fixture profile (and the checked-in live one), approved; the core answering the creates."""

    def setUp(self):
        super().setUp()
        self.scratch = Path(tempfile.mkdtemp(prefix='aieh-authority-'))
        self.addCleanup(shutil.rmtree, self.scratch, True)
        self.core = AC.AgentServerCore(scratch=self.scratch / 'agentfixture')
        self.addCleanup(self.core.close)
        directory = self.profiles / FIX
        shutil.copytree(REPO / 'profiles' / FIX, directory)
        self.addCleanup(shutil.rmtree, directory, True)
        self.fixture_manifest = self.approve_fixture()
        (self.profiles / ci.REAL).mkdir(exist_ok=True)
        (self.profiles / ci.REAL / 'provision.lock.json').write_bytes(LOCK.read_bytes())

    def approve_fixture(self):
        data = self.manifest_data()
        data['profiles'].append({'id': FIX, 'sha256': self.profile_sha(FIX)})
        for binding in data['bindings']:
            binding['profiles'].append(FIX)
        return self.write_manifest(data, self.fresh('fixture'))

    def dispatch(self, transport, credentials, profile=FIX, manifest=None):
        return di.dispatch(self.request(profile=profile), manifest=manifest or self.fixture_manifest,
                           work_sources=self.d1_sources.get, integration_store=self.store, workspaces=self.workspaces,
                           transport=transport, actor=ACTOR, read_profile=self.read_profile,
                           read_artifact=self.read_artifact, inference=ci.native_tests.NoBroker(),
                           native_credentials=credentials, catalog_sources=self.catalog.sources)

    def refused(self, code, act):
        with self.assertRaises(di.DispatchRefused) as caught:
            act()
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        self.assertIn(code, di.REFUSALS)
        return caught.exception

    def details(self, key):
        return [(e.to_state, json.loads(e.detail_json) if e.detail_json else None) for e in self.store.events(key)]

    def fixture_attempt(self):
        """A confirmed fixture-bound attempt, its create answered by the core."""
        result = self.dispatch(Seam(self.core, 'fixture'), provider('fixture'))
        self.assertEqual(self.store.get(result.operation_key).state, 'confirmed')
        return result

    def base_for(self, result):
        resolved = di.stored_inputs(self.store, result.operation_key, state='confirmed')
        path = self.scratch / f'demo-{len(list(self.scratch.glob("demo-*")))}'
        commits = tar.make_repository(path, tar.demo_trees(resolved.work_id, AR._design(resolved)['change']))
        base = AR.read_base(path, repository=resolved.repository, design_commit=commits['C2'])
        return dataclasses.replace(base, design_commit=AR._design(resolved)['commit'])


class Dispatch(Bound):
    def test_a_fixture_attempt_is_dispatched_and_each_of_its_records_labelled(self):
        held = provider('fixture')
        result = self.dispatch(Seam(self.core, 'fixture'), held)
        self.assertEqual(result.to_json()['authority'], 'fixture')
        moves = self.details(result.operation_key)
        self.assertEqual([to for to, _ in moves], ['reserved', 'dispatched', 'confirmed'])
        for to, detail in moves[1:]:
            self.assertEqual(detail['authority'], 'fixture', to)
        self.assertEqual(held.reads, [NT.ENTRY])
        self.assertEqual(len(self.core.creates), 1)

    def test_a_fixture_profile_is_refused_for_a_live_transport(self):
        live = Seam(self.core, None)
        del live.authority
        refusal = self.refused('TRANSPORT_AUTHORITY_MISMATCH', lambda: self.dispatch(live, provider('fixture')))
        self.assertEqual((refusal.context['declared'], refusal.context['presented']), ('fixture', 'live'))
        self.assertEqual((live.count, self.core.calls), (0, []), 'zero transport calls')
        [attempt] = self.store.attempts()
        moves = self.details(attempt.operation_key)
        self.assertEqual(moves[-1][0], 'failed')
        self.assertEqual((moves[-1][1]['code'], moves[-1][1]['create_sent'], moves[-1][1]['authority']),
                         ('TRANSPORT_AUTHORITY_MISMATCH', False, 'fixture'))

    def test_a_live_profile_is_refused_as_fixture(self):
        manifest = self.approve_real()
        claimed = Seam(self.core, 'fixture')
        refusal = self.refused('TRANSPORT_AUTHORITY_MISMATCH',
                               lambda: self.dispatch(claimed, provider(), profile=ci.REAL, manifest=manifest))
        self.assertEqual((refusal.context['declared'], refusal.context['presented']), ('live', 'fixture'))
        self.assertEqual((claimed.count, self.core.calls), (0, []))
        held = provider('fixture')
        refusal = self.refused('CREDENTIAL_AUTHORITY_MISMATCH',
                               lambda: self.dispatch(claimed, held, profile=ci.REAL, manifest=manifest))
        self.assertEqual(refusal.context, {'declared': 'live', 'presented': 'fixture'})
        self.assertEqual((held.reads, claimed.count), ([], 0), 'no entry read, nothing sent')

    def test_a_live_provider_is_refused_for_a_fixture_attempt_with_no_entry_read(self):
        held, transport = provider(), Seam(self.core, 'fixture')
        refusal = self.refused('CREDENTIAL_AUTHORITY_MISMATCH', lambda: self.dispatch(transport, held))
        self.assertEqual(refusal.context, {'declared': 'fixture', 'presented': 'live'})
        self.assertEqual((held.reads, transport.count), ([], 0))
        [attempt] = self.store.attempts()
        self.assertEqual(self.details(attempt.operation_key)[-1][1]['authority'], 'fixture')

    def test_admission_refuses_a_profile_whose_two_declarations_differ(self):
        path = self.profiles / FIX / 'profile.json'
        declared = json.loads(path.read_bytes())
        declared['provisioning']['agent_server'].pop('transport')       # the allowlist still declares fixture
        path.write_bytes((json.dumps(declared, indent=2) + '\n').encode('utf-8'))
        transport = Seam(self.core, 'fixture')
        refusal = self.refused('TRANSPORT_DECLARATION_MISMATCH',
                               lambda: self.dispatch(transport, provider('fixture'), manifest=self.approve_fixture()))
        self.assertEqual((refusal.context['profile'], refusal.context['allowlist']), ('live', 'fixture'))
        self.assertEqual(transport.count, 0)

    def test_a_live_attempts_records_carry_no_authority(self):
        result = self.dispatch(self.core, provider(), profile=ci.REAL, manifest=self.approve_real())
        self.assertNotIn('authority', result.to_json())
        for to, detail in self.details(result.operation_key):
            self.assertFalse(isinstance(detail, dict) and 'authority' in detail, to)


class Observers(Bound):
    def run_with(self, result, inspect, pull):
        return AR.run_attempt(self.store, result.operation_key, transport=Seam(self.core, 'fixture'),
                              base=self.base_for(result), actor=ACTOR, inspect=inspect, pull=pull, ceiling_s=0,
                              clock=lambda: 0.0, wait=lambda s: self.fail('no wait'), read_artifact=self.read_artifact)

    def test_an_observer_of_another_authority_is_refused_before_any_call(self):
        result = self.fixture_attempt()
        for name in ('inspect', 'pull'):
            with self.subTest(observer=name):
                calls = len(self.core.calls)
                observers = {'inspect': Seam(lambda cid: [], 'fixture'), 'pull': Seam(lambda n: {}, 'fixture')}
                observers[name] = Seam(observers[name].call, 'live')
                refusal = self.refused('OBSERVER_AUTHORITY_MISMATCH', lambda: self.run_with(result, **observers))
                self.assertEqual(refusal.context, {'declared': 'fixture', 'presented': 'live'})
                self.assertEqual(len(self.core.calls), calls, 'no Agent Server call')
                self.assertEqual([o.count for o in observers.values()], [0, 0], 'no observer called')
                self.assertIsNone(self.store.get(AR.TURN_KEY.format(attempt_id=result.attempt_id)))

    def test_resume_result_refuses_an_observer_of_another_authority(self):
        result = self.fixture_attempt()
        calls = len(self.core.calls)
        refusal = self.refused('OBSERVER_AUTHORITY_MISMATCH', lambda: AR.resume_result(
            self.store, result.operation_key, transport=Seam(self.core, 'fixture'), base=self.base_for(result),
            actor=ACTOR, pull=Seam(lambda n: {}, 'fixture'), exists=lambda n: False,
            read_artifact=self.read_artifact))
        self.assertEqual(refusal.context['presented'], 'live')
        self.assertEqual(len(self.core.calls), calls)


class Publication(Bound):
    """The result path's seams (R8 point 5, the engineering manager's ruling B): the caller of attempt_role_token
    (publish_result) checks the provider and the target against the bound authority the verified result carries,
    before anything is read or written."""

    def verified(self, result, authority='fixture'):
        resolved = di.stored_inputs(self.store, result.operation_key, state='confirmed')
        return AR.VerifiedResult(attempt_id=result.attempt_id, conversation_id=result.conversation_id,
                                 repository=resolved.repository, base='b' * 40, commit='c' * 40, tree='d' * 40,
                                 ref=AR.result_ref(result.attempt_id), bundle_sha256='e' * 64, bundle_bytes=1,
                                 staged='nowhere', verify_repo='nowhere', files=1, inflated_bytes=1,
                                 tests={'status': '0'}, excluded=(), authority=authority)

    def publish(self, result, verified, target, bot, **kwargs):
        return RP.publish_result(self.store, result.operation_key, verified=verified, native=NT.NativeToken(ci.TOKEN),
                                 provider=bot, target=target, actor=ACTOR, **kwargs)

    def test_a_target_or_provider_of_another_authority_is_refused_with_nothing_read_or_written(self):
        result = self.fixture_attempt()
        verified = self.verified(result)
        http = Seam(lambda *a, **k: self.fail('Gitea was called'), 'fixture')

        def target(authority):
            return RP.GiteaTarget(repository_id='demo-app', full_name='aieh-demo/demo', port=1,
                                  git_url='http://127.0.0.1:1/x.git', http=http, authority=authority)
        bot = provider('fixture')
        refusal = self.refused('RESULT_TARGET_AUTHORITY_MISMATCH',
                               lambda: self.publish(result, verified, target('live'), bot))
        self.assertEqual(refusal.context, {'declared': 'fixture', 'presented': 'live'})
        live_bot = provider()
        refusal = self.refused('CREDENTIAL_AUTHORITY_MISMATCH',
                               lambda: self.publish(result, verified, target('fixture'), live_bot))
        self.assertEqual(refusal.context, {'declared': 'fixture', 'presented': 'live'})
        self.assertEqual((bot.reads, live_bot.reads, http.count), ([], [], 0), 'no entry read, no Gitea call')
        self.assertIsNone(self.store.get(RP.RESULT_KEY.format(attempt_id=result.attempt_id)), 'nothing written')

    def test_a_verified_result_that_is_not_the_binding_is_refused_given_the_reader(self):
        result = self.fixture_attempt()
        target = RP.GiteaTarget(repository_id='demo-app', full_name='aieh-demo/demo', port=1,
                                git_url='http://127.0.0.1:1/x.git', http=None)
        refusal = self.refused('RESULT_NOT_RESERVED', lambda: self.publish(
            result, self.verified(result, authority='live'), target, provider(), read_artifact=self.read_artifact))
        self.assertIn('pinned route allowlist', refusal.detail)


class Labels(Bound):
    def gate(self, result):
        return LG.gate(self.store, result.operation_key, inspect_source=self.core.container_inspect, source=SOURCE,
                       actor=ACTOR, read_profile=self.read_profile, read_artifact=self.read_artifact)

    def test_the_launch_receipt_carries_the_fixture_authority(self):
        result = self.fixture_attempt()
        self.assertEqual(self.gate(result)(result.conversation_id), [])
        record = LG.launch_record(self.store, result.attempt_id)
        self.assertEqual((record['verdict'], record['authority']), (LG.LAUNCHED, 'fixture'))

    def test_a_live_launch_receipt_carries_none(self):
        live = self.dispatch(self.core, provider(), profile=ci.REAL, manifest=self.approve_real())
        self.assertEqual(self.gate(live)(live.conversation_id), [])
        self.assertNotIn('authority', LG.launch_record(self.store, live.attempt_id))

    def test_the_end_journal_and_record_and_the_stop_receipts_carry_it(self):
        result = self.fixture_attempt()
        stop = {'kind': 'containment-stop', 'code': 'INSPECTION_FAILED', 'ref': f'attempt:{result.attempt_id}#x'}
        record = AE.end_interrupted_attempt(self.store, result.operation_key, transport=Seam(self.core, 'fixture'),
                                            actor=ACTOR, trigger=AE.ATTEMPT_STOPPED, dispatcher_records=[stop],
                                            read_artifact=self.read_artifact)
        self.assertEqual(record['authority'], 'fixture')
        journal = self.store.get(AE.END_KEY.format(attempt_id=result.attempt_id))
        self.assertEqual(json.loads(journal.intent_json)['authority'], 'fixture')
        [key] = AE.record_stop(self.store, result.operation_key, [stop], actor=ACTOR, read_artifact=self.read_artifact)
        self.assertEqual(json.loads(self.store.get(key).intent_json)['authority'], 'fixture')

    def test_without_the_reader_a_stop_receipt_is_written_as_the_native_driver_writes_it(self):
        result = self.dispatch(self.core, provider(), profile=ci.REAL, manifest=self.approve_real())
        stop = {'kind': 'containment-stop', 'code': 'INSPECTION_FAILED', 'ref': 'attempt:x#y'}
        [key] = AE.record_stop(self.store, result.operation_key, [stop], actor=ACTOR)
        self.assertEqual(sorted(json.loads(self.store.get(key).intent_json)),
                         ['attemptId', 'code', 'format', 'kind', 'workId'])


class Recovery(Bound):
    def test_recover_settles_an_interrupted_fixture_attempt_through_its_fixture_transport(self):
        def dies_after_the_create(method, path, body=None, **kwargs):
            answer = self.core(method, path, body, **kwargs)
            if (method, path) == ('POST', '/api/conversations'):
                raise Crash('the dispatcher died after the create reached the server')
            return answer
        with self.assertRaises(Crash):
            self.dispatch(Seam(dies_after_the_create, 'fixture'), provider('fixture'))
        [attempt] = self.store.attempts()
        self.assertEqual(attempt.state, 'dispatched')
        report = RR.recover(self.store, transport=Seam(self.core, 'fixture'), actor=ACTOR,
                            read_artifact=self.read_artifact)
        self.assertEqual(report['held'], [], 'settled, not held for its wrapper (CLIENT_UNAVAILABLE)')
        self.assertEqual(self.store.get(attempt.operation_key).state, 'confirmed')
        self.assertEqual(len(self.core.creates), 1, 'no second create')


class Census(unittest.TestCase):
    """R8 point 7: the dispatch modules compare declared values and contain no fixture-specific path. In each module
    the string ``fixture`` occurs only in the authority vocabulary, the refusals' texts and the profile's pre-existing
    F-04.2 fixture template (its declaration key and its refusal texts); no module compares anything with it, and none
    imports the fixture package."""
    category = 'contract'
    MODULES = ('dispatch_inputs.py', 'attempt_run.py', 'attempt_end.py', 'result_path.py', 'attempt_tokens.py',
               'launch_gate.py', 'restart_recovery.py', 'reconcile.py')
    # the authority vocabulary (dispatch_inputs: FIXTURE and TRANSPORT_DECLARATIONS' kind) and the F-04.2 fixture
    # template's declaration key and path, which predate the authority
    ALLOWED = {'fixture', 'loopback-fixture', 'agent_server.fixture'}

    def test_the_string_occurs_only_in_the_vocabulary_and_refusal_texts(self):
        for name in self.MODULES:
            source = (HERE.parent / name).read_text(encoding='utf-8')
            tree = ast.parse(source)
            docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                          if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                          and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
            meanings = set(di.REFUSALS.values())
            with self.subTest(module=name):
                self.assertNotIn('agentfixture', source.replace('agentfixture catalog', ''), 'no fixture import')
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings \
                            and 'fixture' in node.value.lower():
                        self.assertTrue(node.value in self.ALLOWED or node.value in meanings
                                        or 'F-04.2' in node.value or 'disposable fixture' in node.value,
                                        f'{name}:{node.lineno}: {node.value[:80]!r}')
                    if isinstance(node, ast.Compare):
                        operands = [node.left, *node.comparators]
                        self.assertFalse(any(isinstance(o, ast.Constant) and o.value == 'fixture'
                                             or isinstance(o, ast.Name) and o.id == 'FIXTURE'
                                             or isinstance(o, ast.Attribute) and o.attr == 'FIXTURE'
                                             for o in operands), f'{name}:{node.lineno}: a branch on fixture')


if __name__ == '__main__':
    unittest.main()
