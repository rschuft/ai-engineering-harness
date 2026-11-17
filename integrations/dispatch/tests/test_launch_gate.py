"""Tests for the launch gate (plan leaf E-01.5; the I1 integration design, R11: ``integrations/dispatch/launch_gate.py``),
offline, against the fixture catalog's cited core.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_launch_gate.py -v

The attempt is a native D1 attempt on the checked-in ``strong-windows-qemu-whpx`` declaration (E-05.2's fixture), its
create answered by ``AgentServerCore``; the container inspect is the core's ``container-inspect`` entry (cited to
F-04.2 section 4.3 and 7 and to the D1 run record's steps (3) and (5b)). Shown here:

* the gate passes on the cited inspect document, and writes its launch receipt (``Passes``);
* an altered copy of each of the five compared fields (caps, image ID, mounts, NetworkMode, ExtraHosts) marks the
  attempt ``not-launched``, and so does an inspect that cannot be obtained or compared, or admitted values that
  raise, each with its receipt; a receipt that cannot be written is answered as a problem (``NotLaunched``); the
  altered copies are test knobs (``Altered``), answers no cited run gave, made by editing a copy of the core's answer;
* the limit values are the recorded ones of ``fd-container-network-deviations`` and F-04.2 section 7
  (``Limits``);
* wired as ``run_attempt``'s ``inspect`` (its step 1, before SEED and the message): a launched attempt goes on to SEED
  and its message; an attempt with an unauthorized workspace path, with no container to inspect (a local-runtime
  fallback), with a document the gate cannot compare, or whose receipt cannot be written, is ended
  ``INSPECTION_FAILED`` with no SEED and no message, and is never reported launched (``Wired``).
"""
from pathlib import Path
import copy
import dataclasses
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
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


ci = _load('test_d1_checked_in_template', HERE / 'test_d1_checked_in_template.py')
tar = _load('test_attempt_run', HERE / 'test_attempt_run.py')
di, store_mod, cc, NT = ci.di, ci.store_mod, ci.cc, ci.NT
AC = cc.AC
AR, AE = tar.AR, tar.AE
LG = _load('launch_gate', HERE.parent / 'launch_gate.py')

ACTOR = 'e-01.5-test'
SOURCE = 'agentfixture catalog container-inspect (F-04.2 4.3, 7; D1 5 (3), (5b))'
LOCK = REPO / 'profiles' / ci.REAL / 'provision.lock.json'
IMAGE = 'sha256:e8959dfc8e184f629b63dcd709f39b1cb0c804c8d19f34ba7a9e2cc8854042cb'


class Altered:
    """A test knob: the core's container inspect with EDIT applied to a copy of its body (an answer no cited run
    gave). EDIT gets the body and edits it in place; the core's own answer is not changed."""

    def __init__(self, core, edit):
        self.core, self.edit = core, edit

    def __call__(self, conversation_id):
        answer = copy.deepcopy(self.core.container_inspect(conversation_id))
        self.edit(answer['body'])
        return answer


class Attempt(ci.CheckedInFixture):
    """A confirmed native D1 attempt on the checked-in declaration, its create answered by the core."""

    def setUp(self):
        super().setUp()
        self.scratch = Path(tempfile.mkdtemp(prefix='aieh-launch-gate-'))
        self.addCleanup(shutil.rmtree, self.scratch, True)
        self.core = AC.AgentServerCore(scratch=self.scratch / 'agentfixture')
        self.addCleanup(self.core.close)
        self.manifest = self.approve_real()
        # the provision lock the checked-in profile pins (provider.provision_lock), beside it, byte for byte
        (self.profiles / ci.REAL / 'provision.lock.json').write_bytes(LOCK.read_bytes())

    def dispatched(self):
        result = di.dispatch(self.real_request(), manifest=self.manifest, work_sources=self.d1_sources.get,
                             integration_store=self.store, workspaces=self.workspaces, transport=self.core,
                             actor=ACTOR, read_profile=self.read_profile, read_artifact=self.read_artifact,
                             inference=ci.native_tests.NoBroker(), native_credentials=self.provider,
                             catalog_sources=self.catalog.sources)
        self.assertEqual(self.store.get(result.operation_key).state, 'confirmed')
        return result

    def gate(self, result, inspect_source=None):
        return LG.gate(self.store, result.operation_key, inspect_source=inspect_source or self.core.container_inspect,
                       source=SOURCE, actor=ACTOR, read_profile=self.read_profile, read_artifact=self.read_artifact)

    def receipt(self, result):
        return LG.launch_record(self.store, store_mod.attempt_id_for(result.operation_key))

    def not_launched(self, result, inspect_source, *fields):
        problems = self.gate(result, inspect_source)(result.conversation_id)
        self.assertTrue(problems)
        record = self.receipt(result)
        self.assertEqual(record['verdict'], LG.NOT_LAUNCHED)
        self.assertEqual(sorted(f['field'] for f in record['fields'] if not f['equal']), sorted(fields))
        return record, problems


class Passes(Attempt):
    def test_the_gate_passes_on_the_cited_document_and_records_it(self):
        result = self.dispatched()
        self.assertEqual(self.gate(result)(result.conversation_id), [])
        record = self.receipt(result)
        self.assertEqual((record['verdict'], record['conversationId'], record['limitFinding']),
                         (LG.LAUNCHED, result.conversation_id, 'fd-container-network-deviations'))
        self.assertEqual([f['field'] for f in record['fields']], list(LG.FIELDS))
        self.assertTrue(all(f['equal'] for f in record['fields']))
        fields = {f['field']: f for f in record['fields']}
        hexed = result.conversation_id.replace('-', '')
        self.assertEqual(fields['caps']['expected'], {'Memory': 4294967296, 'NanoCpus': 2000000000, 'PidsLimit': 512})
        self.assertEqual(fields['image']['expected'], IMAGE)
        self.assertEqual(fields['mounts']['expected'], sorted([
            ['bind', f'/srv/scratch/openhands/conversations/{hexed}', f'/var/openhands/conversations/{hexed}', True],
            ['bind', f'/srv/scratch/openhands/persistence/runtime-data/{hexed}/persistence',
             '/var/openhands/.openhands', True],
            ['bind', f'/srv/scratch/openhands/persistence/runtime-data/{hexed}/workspace', '/workspace', True]]))
        self.assertEqual((fields['network-mode']['basis'], fields['network-mode']['expected']), ('limit', 'bridge'))
        self.assertEqual(fields['extra-hosts']['expected'], ['host.docker.internal:host-gateway'])
        for f in record['fields']:
            with self.subTest(field=f['field']):
                self.assertEqual(f['observed'], f['expected'])
        document = LG._plain(self.core.container_inspect(result.conversation_id)['body'])
        self.assertEqual(record['inspect'], {'source': SOURCE, 'obtained': True, 'sha256': hashlib.sha256(
            di._canonical(document).encode('utf-8')).hexdigest()})
        self.assertEqual(record['problems'], [])
        self.assertEqual(self.store.get(LG.LAUNCH_KEY.format(attempt_id=record['attemptId'])).state, 'confirmed')

    def test_the_admitted_values_come_from_the_reserved_record_and_the_pinned_lock(self):
        result = self.dispatched()
        values = LG.admitted(self.store, result.operation_key, read_profile=self.read_profile,
                             read_artifact=self.read_artifact)
        lock = json.loads(LOCK.read_bytes())
        self.assertEqual(values['image'], lock['image']['image_id'])
        # a lock other than the pinned bytes is refused, so the gate does not launch
        (self.profiles / ci.REAL / 'provision.lock.json').write_bytes(LOCK.read_bytes() + b' ')
        with self.assertRaises(di.DispatchRefused) as caught:
            LG.admitted(self.store, result.operation_key, read_profile=self.read_profile,
                        read_artifact=self.read_artifact)
        self.assertEqual(caught.exception.code, 'PROFILE_ARTIFACT_DRIFTED')
        problems = self.gate(result)(result.conversation_id)
        self.assertEqual(problems, ['the admitted values could not be read (PROFILE_ARTIFACT_DRIFTED)'])
        self.assertEqual(self.receipt(result)['verdict'], LG.NOT_LAUNCHED)

    def test_a_repeated_gate_finds_its_receipt_and_another_observation_is_not_launched(self):
        result = self.dispatched()
        gate = self.gate(result)
        self.assertEqual(gate(result.conversation_id), [])
        self.assertEqual(gate(result.conversation_id), [])
        keys = [a.operation_key for a in self.store.attempts() if a.operation_key.endswith('/launch')]
        self.assertEqual(len(keys), 1)

        def image(body):
            body['Image'] = 'sha256:' + '1' * 64
        problems = self.gate(result, Altered(self.core, image))(result.conversation_id)
        self.assertIn('a launch receipt with another observation is recorded for the attempt', problems)
        self.assertEqual(self.receipt(result)['verdict'], LG.LAUNCHED, 'the first receipt stands')


class NotLaunched(Attempt):
    def test_an_altered_copy_of_each_compared_field_is_not_launched(self):
        other_hex = 'f' * 32
        cases = {
            'caps': [lambda b: b['HostConfig'].__setitem__('Memory', 8589934592),
                     lambda b: b['HostConfig'].__setitem__('NanoCpus', 4000000000),
                     lambda b: b['HostConfig'].__setitem__('PidsLimit', 1024),
                     lambda b: b['HostConfig'].__setitem__('Memory', 4294967296.0),
                     lambda b: b['HostConfig'].__setitem__('PidsLimit', None)],
            'image': [lambda b: b.__setitem__('Image', 'sha256:' + '0' * 64),
                      lambda b: b.__setitem__('Image', 'aieh/agent-server:1.60.1-b43ee580')],
            'mounts': [lambda b: b['Mounts'][2].__setitem__('Source', '/srv/scratch/openhands/other/workspace'),
                       lambda b: b['Mounts'][0].__setitem__('Source',
                                                            f'/srv/scratch/openhands/conversations/{other_hex}'),
                       lambda b: b['Mounts'].append({'Type': 'bind', 'Source': '/var/run/docker.sock',
                                                     'Destination': '/var/run/docker.sock', 'RW': True}),
                       lambda b: b['Mounts'][1].__setitem__('RW', False),
                       lambda b: b['Mounts'][1].__setitem__('Type', 'volume'),
                       lambda b: b['Mounts'].pop()],
            'network-mode': [lambda b: b['HostConfig'].__setitem__('NetworkMode', 'host'),
                             lambda b: b['HostConfig'].__setitem__('NetworkMode', 'none'),
                             lambda b: b['HostConfig'].__setitem__('NetworkMode', 'container:other')],
            'extra-hosts': [lambda b: b['HostConfig'].__setitem__('ExtraHosts', []),
                            lambda b: b['HostConfig'].__setitem__('ExtraHosts', None),
                            lambda b: b['HostConfig']['ExtraHosts'].append('gitea:10.0.2.2')],
        }
        self.assertEqual(sorted(cases), sorted(LG.FIELDS))
        for field, edits in cases.items():
            for n, edit in enumerate(edits):
                with self.subTest(field=field, case=n):
                    result = self.dispatched()
                    record, problems = self.not_launched(result, Altered(self.core, edit), field)
                    self.assertEqual(problems, [f'the container\'s {field} is not the '
                                                f'{"limit" if field in ("network-mode", "extra-hosts") else "admitted"}'
                                                ' value'])
                    self.setUp_next()

    def setUp_next(self):
        """A fresh store and core for the next case (one attempt each)."""
        self.store.close()
        path = Path(self.store.path)
        path.unlink()
        shutil.copyfile(self.empty_store, path)
        self.store = store_mod.open_store(path)
        self.addCleanup(self.store.close)
        self.core.close()
        self.core = AC.AgentServerCore(scratch=self.scratch / f'agentfixture-{len(list(self.scratch.iterdir()))}')
        self.addCleanup(self.core.close)

    def test_an_inspect_that_cannot_be_obtained_is_not_launched(self):
        def raises(conversation_id):
            raise OSError('the guest facts report could not be read')

        def no_object(conversation_id):
            return {'body': ['not', 'an', 'inspect', 'object']}

        def no_body(conversation_id):
            return 'not an answer'
        sources = {'raises': raises, 'no object': no_object, 'no body': no_body,
                   'refused (no container)': lambda cid: self.core.container_inspect('0' * 8 + '-0000-4000-8000-'
                                                                                     + '0' * 12)}
        for name, source in sources.items():
            with self.subTest(source=name):
                result = self.dispatched()
                record, problems = self.not_launched(result, source)
                self.assertEqual(record['fields'], [])
                self.assertEqual(record['inspect']['obtained'], False)
                self.assertIsNone(record['inspect']['sha256'])
                self.assertTrue(problems[0].startswith('the container inspect could not be obtained'), problems)
                self.setUp_next()

    def test_a_stopped_runtime_has_no_container_to_inspect(self):
        """F-04.2 4.6: after the runtime stop no container exists; the core refuses the inspect, with its label."""
        result = self.dispatched()
        client = AE._client(di.stored_inputs(self.store, result.operation_key, state='confirmed'),
                            self.core)(self.read_artifact)
        self.assertEqual(AE.stop_runtime(client, result.conversation_id), AE.STOPPED)
        answer = self.core.container_inspect(result.conversation_id)
        self.assertEqual((answer['status'], answer['fixture']['answer']), (501, 'refusal'))
        self.not_launched(result, self.core.container_inspect)

    def test_a_document_the_gate_cannot_compare_is_recorded_not_launched(self):
        """Review of dispatch 19, S3 (probe P1): a Mounts entry whose Source is null cannot be sorted with the others
        (a TypeError inside the comparison). The gate records the not-launched receipt, with the reason, and answers
        it; the document was obtained, and its digest is recorded."""
        result = self.dispatched()

        def null_source(body):
            body['Mounts'][0]['Source'] = None
        source = Altered(self.core, null_source)
        problems = self.gate(result, source)(result.conversation_id)
        self.assertEqual(problems, ['the container inspect could not be compared (TypeError)'])
        record = self.receipt(result)
        self.assertIsNotNone(record, 'the not-launched receipt is recorded')
        self.assertEqual((record['verdict'], record['fields'], record['problems']),
                         (LG.NOT_LAUNCHED, [], ['the container inspect could not be compared (TypeError)']))
        document = LG._plain(source(result.conversation_id)['body'])
        self.assertEqual(record['inspect'], {'source': SOURCE, 'obtained': True, 'sha256': hashlib.sha256(
            di._canonical(document).encode('utf-8')).hexdigest()})
        self.assertEqual(self.store.get(LG.LAUNCH_KEY.format(attempt_id=record['attemptId'])).state, 'confirmed')

    def test_admitted_values_that_raise_are_recorded_not_launched(self):
        """S3: an exception other than a refusal while the admitted values are read is not launched, recorded."""
        result = self.dispatched()
        with mock.patch.object(LG, 'admitted', side_effect=KeyError('caps')):
            problems = self.gate(result)(result.conversation_id)
        self.assertEqual(problems, ['the admitted values could not be read (KeyError)'])
        record = self.receipt(result)
        self.assertEqual((record['verdict'], record['fields']), (LG.NOT_LAUNCHED, []))

    def test_a_receipt_that_cannot_be_written_is_answered_as_a_problem(self):
        """S3: on the cited (launched) document, a receipt write that fails is a problem the gate answers: there is
        no launch without its receipt."""
        result = self.dispatched()
        with mock.patch.object(LG, '_write_receipt', side_effect=OSError('the store could not be written')):
            problems = self.gate(result)(result.conversation_id)
        self.assertEqual(problems, ['the launch receipt could not be written (OSError)'])
        self.assertIsNone(self.receipt(result))

    def test_an_inspect_asked_for_another_conversation_is_not_launched(self):
        result = self.dispatched()
        problems = self.gate(result)('0' * 8 + '-0000-4000-8000-' + '0' * 12)
        self.assertEqual(problems, ['the inspect was asked for another conversation than the attempt\'s'])
        self.assertEqual(self.receipt(result)['verdict'], LG.NOT_LAUNCHED)
        self.assertEqual(self.core.inspected, [], 'no inspect was made for another conversation')


class Limits(unittest.TestCase):
    category = 'unit'

    def test_the_limit_values_are_the_recorded_ones(self):
        inventory = json.loads((REPO / 'security' / 'inventory.json').read_text(encoding='utf-8'))
        (finding,) = [f for f in inventory['findings'] if f['id'] == LG.DEVIATION_FINDING]
        self.assertEqual(finding['kind'], 'limit')
        self.assertIn('E-01.5', finding['carried_to'])
        self.assertIn('--add-host host.docker.internal:host-gateway', finding['detail'])
        self.assertIn("Moby's default bridge instead of --network none", finding['detail'])
        text = (REPO / 'evidence' / 'F-04.2-conversation-lifecycle.md').read_text(encoding='utf-8')
        section = text[text.index('## 7. Containment deviations'):text.index('## 8.')]
        self.assertIn('`HostConfig.ExtraHosts` `["host.docker.internal:host-gateway"]`', section)
        self.assertIn('`HostConfig.NetworkMode` `bridge`', section)
        self.assertEqual((LG.NETWORK_MODE_LIMIT, LG.EXTRA_HOSTS_LIMIT), ('bridge', ('host.docker.internal:host-gateway',)))

    def test_compare_takes_any_other_value_as_unequal(self):
        values = {'caps': {'Memory': 1, 'NanoCpus': 2, 'PidsLimit': 3}, 'image': 'sha256:' + 'a' * 64,
                  'mounts': [['bind', '/s', '/d', True]]}
        document = {'Image': 'sha256:' + 'a' * 64, 'Mounts': [{'Type': 'bind', 'Source': '/s', 'Destination': '/d',
                                                                'RW': True}],
                    'HostConfig': {'Memory': 1, 'NanoCpus': 2, 'PidsLimit': 3, 'NetworkMode': 'bridge',
                                   'ExtraHosts': ['host.docker.internal:host-gateway']}}
        self.assertTrue(all(f['equal'] for f in LG.compare(document, values)))
        for change in ({'Image': None}, {'Mounts': None}, {'Mounts': [['bind', '/s', '/d', True]]},
                       {'HostConfig': None}, {'HostConfig': {**document['HostConfig'], 'Memory': True}},
                       {'HostConfig': {**document['HostConfig'], 'ExtraHosts': ('host.docker.internal:host-gateway',
                                                                                'x')}}):
            with self.subTest(change=change):
                self.assertFalse(all(f['equal'] for f in LG.compare({**document, **change}, values)))


class Wired(Attempt):
    """The gate as run_attempt's inspect: step 1, before SEED and the message."""

    def base_for(self, result):
        resolved = di.stored_inputs(self.store, result.operation_key, state='confirmed')
        path = self.scratch / f'demo-{len(list(self.scratch.glob("demo-*")))}'
        commits = tar.make_repository(path, tar.demo_trees(resolved.work_id, AR._design(resolved)['change']))
        base = AR.read_base(path, repository=resolved.repository, design_commit=commits['C2'])
        return dataclasses.replace(base, design_commit=AR._design(resolved)['commit'])

    def run_attempt(self, result, inspect):
        return AR.run_attempt(self.store, result.operation_key, transport=self.core, base=self.base_for(result),
                              actor=ACTOR, inspect=inspect, pull=lambda name: self.fail('no pull expected'),
                              ceiling_s=0, clock=lambda: 0.0, wait=lambda s: self.fail('no wait expected'),
                              read_artifact=self.read_artifact)

    def seeds_and_messages(self, conversation_id):
        seeds = [c for c in self.core.calls if c[0] == 'POST' and c[1].endswith('/bash/execute_bash_command')]
        return seeds, self.core.messages(conversation_id)

    def test_a_launched_attempt_goes_on_to_seed_and_its_message(self):
        result = self.dispatched()
        with self.assertRaises(di.DispatchRefused):   # RESULT is refused by the core (agentfixture reading 3)
            self.run_attempt(result, self.gate(result))
        self.assertEqual(self.receipt(result)['verdict'], LG.LAUNCHED)
        seeds, messages = self.seeds_and_messages(result.conversation_id)
        self.assertEqual((len(seeds) >= 1, len(messages)), (True, 1))
        [(at, inspected)] = self.core.inspected
        self.assertEqual(inspected, result.conversation_id)
        first_seed = self.core.calls.index(seeds[0])
        self.assertLessEqual(at, first_seed, 'the container inspect came before SEED')
        self.assertLess(at, self.core.calls.index(messages[0]), 'and before the message')

    def test_an_unauthorized_workspace_path_is_never_reported_launched(self):
        result = self.dispatched()

        def elsewhere(body):
            body['Mounts'][2]['Source'] = '/home/agent/workspace'
        outcome = self.run_attempt(result, self.gate(result, Altered(self.core, elsewhere)))
        self.assertEqual(outcome.outcome, 'inspection-failed')
        self.assertIn('the container\'s mounts is not the admitted value', outcome.problems)
        self.assertEqual(self.receipt(result)['verdict'], LG.NOT_LAUNCHED)
        self.assertEqual(outcome.end['surfaced']['dispatcherRecords'],
                         [{'kind': 'containment-stop', 'code': 'INSPECTION_FAILED',
                           'ref': f'attempt:{store_mod.attempt_id_for(result.operation_key)}#inspection'}])
        self.assertEqual(self.seeds_and_messages(result.conversation_id), ([], []))

    def test_a_document_the_gate_cannot_compare_ends_the_attempt_with_its_receipt(self):
        """Review of dispatch 19, S3 (probe P1), wired: the attempt is ended INSPECTION_FAILED with no SEED and no
        message, and its not-launched receipt is recorded."""
        result = self.dispatched()

        def null_source(body):
            body['Mounts'][0]['Source'] = None
        outcome = self.run_attempt(result, self.gate(result, Altered(self.core, null_source)))
        self.assertEqual(outcome.outcome, 'inspection-failed')
        self.assertIn('the container inspect could not be compared (TypeError)', outcome.problems)
        self.assertEqual(self.receipt(result)['verdict'], LG.NOT_LAUNCHED)
        self.assertEqual(self.seeds_and_messages(result.conversation_id), ([], []))

    def test_a_receipt_that_cannot_be_written_never_reaches_seed(self):
        """S3: the receipt write fails on the cited document: the attempt is ended INSPECTION_FAILED, no SEED."""
        result = self.dispatched()
        with mock.patch.object(LG, '_write_receipt', side_effect=OSError('the store could not be written')):
            outcome = self.run_attempt(result, self.gate(result))
        self.assertEqual(outcome.outcome, 'inspection-failed')
        self.assertIn('the launch receipt could not be written (OSError)', outcome.problems)
        self.assertIsNone(self.receipt(result))
        self.assertEqual(self.seeds_and_messages(result.conversation_id), ([], []))

    def test_a_local_runtime_fallback_has_no_container_and_is_never_reported_launched(self):
        """A conversation the server runs with no conversation container: there is no container inspect to obtain
        (the source answers no inspect object)."""
        result = self.dispatched()
        outcome = self.run_attempt(result, self.gate(result, lambda cid: {'body': None}))
        self.assertEqual(outcome.outcome, 'inspection-failed')
        self.assertIn('the container inspect could not be obtained (no inspect object)', outcome.problems)
        self.assertEqual(self.receipt(result)['verdict'], LG.NOT_LAUNCHED)
        self.assertEqual(self.seeds_and_messages(result.conversation_id), ([], []))


if __name__ == '__main__':
    unittest.main()
