"""Tests for the D1 stage's create admission (plan leaf E-05.2), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -p test_d1_stage_admission.py -v

The proof, clause by clause: E-01.2.2's admission, extended for the D1 stage, accepts exactly the
agent block of the approved create template, bound by its digest; it refuses any other block, and
refuses the F-04.2 disposable fixture template for a real stage (and, here too, the S-03.3
qualification create). The D1 stage is the stage an approved profile's
``provisioning.agent_server.stage_create_template`` names.

The approved template is the CANDIDATE ``profiles/strong-windows-qemu-whpx/agent-server/d1-create.json``
(S-03.3 slice 2's ACP block, its model a sentinel, tagged ``e-05.2-d1-candidate``), pinned by a
synthetic profile in a throwaway directory: no checked-in profile pins it yet. Every create goes
through the E-01.2.2 counting fake transport; each refusal asserts it was called zero times.
"""
from pathlib import Path
import copy
import dataclasses
import hashlib
import importlib.util
import json
import sys
import unittest
import unittest.mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


adm = _load('test_dispatch_admission', HERE / 'test_dispatch_admission.py')
base = adm.base
di = base.di
store_mod = base.store_mod

D1 = 'strong-d1-profile'
D1_PATH = f'profiles/{D1}/agent-server/d1-create.json'
FIXTURE_PATH = f'profiles/{D1}/agent-server/conversation-create.json'
CANDIDATE_FILE = base.AGENT_SERVER / 'd1-create.json'
CANDIDATE_BYTES = CANDIDATE_FILE.read_bytes()
CANDIDATE = json.loads(CANDIDATE_BYTES)
FIXTURE_BYTES = base.TEMPLATE_BYTES          # the F-04.2 disposable fixture
FIXTURE = json.loads(FIXTURE_BYTES)
QUALIFICATION_PATH = 'integrations/dispatch/qualification/acp-claude-code-create.json'
QUALIFICATION_BYTES = base.REPO.joinpath(*QUALIFICATION_PATH.split('/')).read_bytes()
QUALIFICATION = json.loads(QUALIFICATION_BYTES)
DEFAULT = object()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def as_bytes(body):
    return json.dumps(body, indent=2).encode('utf-8')


def candidate_with(change):
    body = copy.deepcopy(CANDIDATE)
    change(body)
    return as_bytes(body)


class D1Fixture(adm.AdmissionFixture):
    """The E-01.2.2 admission fixture with one more approved profile, strong-d1-profile: the synthetic
    strong declaration plus a stage_create_template, bound to demo-app/implement and other-app/review."""

    def setUp(self):
        super().setUp()
        self.d1_sources = {'demo-app': self.sources['demo-app'], 'other-app': self.sources['demo-app']}

    def approve_d1(self, template=CANDIDATE_BYTES, pin=DEFAULT):
        """Write strong-d1-profile (F-04.2 fixture, route allowlist, the stage template TEMPLATE at D1_PATH
        and the declaration pinning it, or PIN) and return a manifest approving its exact bytes."""
        directory = self.profiles / D1
        base.write_agent_server(directory)
        if template is not None:
            (directory / 'agent-server' / 'd1-create.json').write_bytes(template)
        declared = json.loads(base.profile_bytes(D1))
        if pin is DEFAULT:
            pin = {'stage': 'implement', 'path': D1_PATH, 'sha256': sha(template), 'plan_leaf': 'E-05.2'}
        declared['provisioning']['agent_server'][di.STAGE_TEMPLATE_KEY] = pin
        (directory / 'profile.json').write_bytes(as_bytes(declared))
        data = self.manifest_data()
        data['designs'].append({'repository': 'other-app', 'change': base.CHANGE, 'commit': self.commit})
        data['profiles'].append({'id': D1, 'sha256': self.profile_sha(D1)})
        for binding in data['bindings']:
            binding['profiles'].append(D1)
        return self.write_manifest(data, self.fresh('d1'))

    def d1_request(self, **changes):
        return self.request(profile=D1, **changes)

    def resolve_d1(self, manifest, **changes):
        return self.resolve(self.d1_request(**changes), manifest, self.d1_sources)

    def reserved_d1(self, template=CANDIDATE_BYTES):
        manifest = self.approve_d1(template)
        resolved = self.resolve_d1(manifest)
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='d1-test')
        return manifest, resolved, self.admit(resolved, manifest)

    def body_for(self, resolved, template):
        body = copy.deepcopy(template)
        body['conversation_id'] = store_mod.conversation_id_for(resolved.attempt_identity().operation_key)
        return body

    def tampered(self, admitted, body):
        return dataclasses.replace(admitted, body_json=di._canonical(body))


class TheCandidate(unittest.TestCase):
    """The candidate template is S-03.3 slice 2's ACP block, inside E-01.2.2's body allowlist."""
    category = 'unit'

    def test_the_candidate_block_is_the_qualification_block_but_the_model(self):
        mine, qualified = CANDIDATE['agent_settings'], QUALIFICATION['body']['agent_settings']
        self.assertEqual({k: v for k, v in mine.items() if k != 'acp_model'},
                         {k: v for k, v in qualified.items() if k != 'acp_model'})
        self.assertEqual((mine['agent_kind'], mine['acp_server'], mine['acp_command']),
                         ('acp', 'claude-code', ['claude-agent-acp']))
        # No model is selected yet (S-03.3, decision 0018 point 3): a sentinel, never a name from memory.
        self.assertEqual((mine['acp_model'], qualified['acp_model']), ('candidate-unselected', '{acp_model}'))

    def test_the_candidate_is_an_admissible_body_marked_candidate(self):
        self.assertEqual(set(CANDIDATE), set(di.BODY_FIELDS))
        self.assertNotIn('secrets', CANDIDATE)
        self.assertEqual(CANDIDATE['tags'], {'aieh': 'e-05.2-d1-candidate'})
        for key in ('conversation_runtime', 'workspace', 'autotitle', 'container'):
            with self.subTest(key):
                self.assertEqual(CANDIDATE[key], FIXTURE[key])
        self.assertTrue(CANDIDATE_BYTES.endswith(b'}\n') and b'\r' not in CANDIDATE_BYTES)
        di.check_stage_template(CANDIDATE, 'implement')  # ACP, not disposable


class AcceptsTheApprovedBlock(D1Fixture):
    def test_the_d1_stage_admits_exactly_the_approved_template(self):
        manifest = self.approve_d1()
        resolved = self.resolve_d1(manifest)
        pin = {'path': D1_PATH, 'sha256': sha(CANDIDATE_BYTES)}
        self.assertEqual(resolved.policy_inputs['admission']['create_template'], pin)
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='d1-test')
        admitted = self.admit(resolved, manifest)
        self.send(admitted, resolved)
        expected = self.body_for(resolved, CANDIDATE)
        self.assertEqual(self.transport.calls, [('POST', '/api/conversations', expected)])
        self.assertEqual(self.transport.calls[0][2]['agent_settings'], CANDIDATE['agent_settings'])
        self.assertEqual(admitted.to_json()['create_template_sha256'], pin['sha256'])

    def test_the_digest_binds_the_block_into_the_attempt(self):
        """Another approved ACP block (re-pinned by its digest) is admitted as itself, under another policy
        digest; bytes changed after approval, without a new pin, are refused."""
        other = candidate_with(lambda body: body['agent_settings'].update(acp_model='another-unselected'))
        first = self.resolve_d1(self.approve_d1())
        manifest = self.approve_d1(other)
        second = self.resolve_d1(manifest)
        self.assertNotEqual(first.policy_digest, second.policy_digest)
        self.assertEqual(second.policy_inputs['admission']['create_template']['sha256'], sha(other))
        self.store.reserve_attempt(second.attempt_identity(), second.intent(), actor='d1-test')
        self.send(self.admit(second, manifest), second)
        self.assertEqual(self.transport.calls[0][2]['agent_settings']['acp_model'], 'another-unselected')

        self.transport = adm.CountingTransport()
        manifest = self.approve_d1()
        resolved = self.resolve_d1(manifest)
        (self.profiles / D1 / 'agent-server' / 'd1-create.json').write_bytes(other)  # drift, no new pin
        refusal = self.assertDenied('PROFILE_ARTIFACT_DRIFTED', self.admit, resolved, manifest)
        self.assertEqual(refusal.context['pinned'], sha(CANDIDATE_BYTES))

    def test_a_stage_the_declaration_does_not_name_keeps_e_01_2_2(self):
        """The boundary: E-05.2 is the D1 stage only. The same profile's review stage, and the policy of a
        profile without the declaration, are E-01.2.2's (the general case is A-01.2's)."""
        manifest = self.approve_d1()
        resolved = self.resolve_d1(manifest, repository='other-app', stage='review', catalog_pin='reviewer-pin')
        self.assertEqual(resolved.policy_inputs['admission']['create_template'],
                         {'path': FIXTURE_PATH, 'sha256': sha(FIXTURE_BYTES)})
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='d1-test')
        self.send(self.admit(resolved, manifest), resolved)
        self.assertEqual(self.transport.calls[0][2], self.body_for(resolved, FIXTURE))
        declared = json.loads(base.profile_bytes('strong-test-profile'))
        for stage in (None, 'implement', 'review'):
            with self.subTest(stage=stage):
                self.assertEqual(di.admission_policy(declared, 'strong-test-profile', stage),
                                 base.expected_admission('strong-test-profile'))


class RefusesAnyOtherBlock(D1Fixture):
    def other_blocks(self):
        acp = CANDIDATE['agent_settings']

        def variant(**changes):
            return {**copy.deepcopy(acp), **changes}

        return {
            'the F-04.2 bare agent': copy.deepcopy(FIXTURE['agent_settings']),
            'agent_kind openhands': variant(agent_kind='openhands'),
            'another acp_server': variant(acp_server='custom'),
            'the npx form (empty command)': variant(acp_command=[]),
            'an npx command': variant(acp_command=['npx', '-y', 'claude-agent-acp']),
            'a wrapper command': variant(acp_command=['env', '-u', 'OH_SECRET_KEY', 'claude-agent-acp']),
            'acp_args': variant(acp_args=['--verbose']),
            'another model': variant(acp_model='another-unselected'),
            'another session mode': variant(acp_session_mode='default'),
            'a shared data dir': variant(acp_isolate_data_dir=False),
            'an MCP server': variant(mcp_config={'mcpServers': {'fetch': {'command': 'uvx', 'args': ['mcp-fetch']}}}),
            'tools': variant(tools=[{'name': 'terminal'}]),
            'an agent profile': variant(agent_profile_id='default'),
            'an agent context': variant(agent_context={'skills': []}),
            'a key missing': {k: v for k, v in acp.items() if k != 'acp_isolate_data_dir'},
            'model as a number': variant(acp_model=1),
            'not an object': 'acp',
            'null': None,
        }

    def test_a_body_with_any_other_agent_block_is_refused_before_the_create(self):
        _, resolved, admitted = self.reserved_d1()
        for name, block in self.other_blocks().items():
            with self.subTest(name):
                body = self.body_for(resolved, CANDIDATE)
                body['agent_settings'] = block
                refusal = self.assertDenied('BODY_NOT_TEMPLATE', self.send, self.tampered(admitted, body), resolved)
                self.assertEqual(refusal.context['field'], 'agent_settings')
                template = json.loads(admitted.template_bytes)
                with self.assertRaises(di.DispatchRefused) as caught:
                    di.check_create_body(body, admission=resolved.policy_inputs['admission'], template=template,
                                         conversation_id=admitted.conversation_id)
                self.assertEqual(caught.exception.code, 'BODY_NOT_TEMPLATE')

    def test_another_agent_source_beside_the_block_is_refused(self):
        _, resolved, admitted = self.reserved_d1()
        for field in ('agent', 'agent_profile_id', 'initial_message'):
            with self.subTest(field):
                body = self.body_for(resolved, CANDIDATE)
                body[field] = {'kind': 'Agent'}
                self.assertDenied('BODY_FIELD_UNKNOWN', self.send, self.tampered(admitted, body), resolved)

    def test_an_approved_template_without_an_acp_block_is_refused_at_admission(self):
        cases = {
            'the F-04.2 bare agent, untagged': lambda body: body.update(
                agent_settings=copy.deepcopy(FIXTURE['agent_settings'])),
            'agent_kind openhands': lambda body: body['agent_settings'].update(agent_kind='openhands'),
            'agent_kind in another case': lambda body: body['agent_settings'].update(agent_kind='ACP'),
            'no agent_kind': lambda body: body['agent_settings'].pop('agent_kind'),
            'no agent block': lambda body: body.pop('agent_settings'),
            'a block that is not an object': lambda body: body.update(agent_settings=['acp']),
        }
        for name, change in cases.items():
            with self.subTest(name):
                manifest = self.approve_d1(candidate_with(change))
                resolved = self.resolve_d1(manifest)
                self.assertDenied('AGENT_BLOCK_NOT_ACP', self.admit, resolved, manifest)


class RefusesTheF042Fixture(D1Fixture):
    def test_the_fixture_pinned_as_the_d1_template_is_refused_at_resolution(self):
        cases = {
            'its path and digest': {'path': FIXTURE_PATH, 'sha256': sha(FIXTURE_BYTES)},
            'its path, another digest': {'path': FIXTURE_PATH, 'sha256': sha(CANDIDATE_BYTES)},
            'its bytes at the D1 path': {'path': D1_PATH, 'sha256': sha(FIXTURE_BYTES)},
        }
        for name, pin in cases.items():
            with self.subTest(name):
                manifest = self.approve_d1(FIXTURE_BYTES, pin={'stage': 'implement', **pin})
                refusal = self.assertRefused('STAGE_TEMPLATE_DISPOSABLE', self.d1_request(), manifest,
                                             self.d1_sources)
                self.assertEqual(refusal.context['stage'], 'implement')

    def test_a_copy_of_the_fixture_is_refused_at_admission(self):
        """Its content under other bytes (another serialization), and its tag on an ACP template."""
        cases = {
            'the fixture re-serialized': json.dumps(FIXTURE, indent=1).encode('utf-8'),
            'the fixture\'s tag on the ACP block': candidate_with(
                lambda body: body.update(tags=copy.deepcopy(FIXTURE['tags']))),
        }
        for name, template in cases.items():
            with self.subTest(name):
                manifest = self.approve_d1(template)
                resolved = self.resolve_d1(manifest)
                self.assertDenied('STAGE_TEMPLATE_DISPOSABLE', self.admit, resolved, manifest)

    def test_a_create_built_from_the_fixture_is_refused_on_the_d1_stage(self):
        _, resolved, admitted = self.reserved_d1()
        fixture_body = self.body_for(resolved, FIXTURE)
        whole = dataclasses.replace(self.tampered(admitted, fixture_body), template_bytes=FIXTURE_BYTES)
        self.assertDenied('PROFILE_ARTIFACT_DRIFTED', self.send, whole, resolved)
        refusal = self.assertDenied('BODY_NOT_TEMPLATE', self.send, self.tampered(admitted, fixture_body), resolved)
        self.assertEqual(refusal.context['field'], 'agent_settings')


class RefusesTheQualificationFixture(D1Fixture):
    def filled_qualification(self, conversation_id):
        values = {'{conversation_id}': conversation_id, '{acp_model}': CANDIDATE['agent_settings']['acp_model'],
                  '{attempt_token}': 'synthetic-attempt-token', '{inference_endpoint}': 'http://172.17.0.1:8090'}

        def fill(node):
            if isinstance(node, dict):
                return {key: fill(value) for key, value in node.items()}
            return values.get(node, node) if isinstance(node, str) else node
        return fill(QUALIFICATION['body'])

    def test_the_qualification_file_cannot_be_pinned(self):
        for path in (QUALIFICATION_PATH, f'profiles/{D1}/../../{QUALIFICATION_PATH}',
                     f'profiles/strong-test-profile/agent-server/d1-create.json'):
            with self.subTest(path):
                manifest = self.approve_d1(pin={'stage': 'implement', 'path': path, 'sha256': sha(QUALIFICATION_BYTES)})
                self.assertRefused('PROFILE_ADMISSION_INVALID', self.d1_request(), manifest, self.d1_sources)
        with self.assertRaises(ValueError):
            di.read_profile_artifact(QUALIFICATION_PATH)

    def test_its_body_pinned_as_the_d1_template_is_refused(self):
        body = QUALIFICATION['body']
        manifest = self.approve_d1(as_bytes(body))
        self.assertDenied('STAGE_TEMPLATE_DISPOSABLE', self.admit, self.resolve_d1(manifest), manifest)
        untagged = dict(copy.deepcopy(body), tags=copy.deepcopy(CANDIDATE['tags']))
        manifest = self.approve_d1(as_bytes(untagged))
        refusal = self.assertDenied('BODY_FIELD_UNKNOWN', self.admit, self.resolve_d1(manifest), manifest)
        self.assertEqual(refusal.context['field'], 'secrets')

    def test_its_filled_create_is_refused_on_the_d1_stage(self):
        _, resolved, admitted = self.reserved_d1()
        body = self.filled_qualification(admitted.conversation_id)
        # Its agent block, the model filled, is the candidate's: what remains is not a D1 create.
        self.assertEqual(body['agent_settings'], CANDIDATE['agent_settings'])
        refusal = self.assertDenied('BODY_FIELD_UNKNOWN', self.send, self.tampered(admitted, body), resolved)
        self.assertEqual(refusal.context['field'], 'secrets')
        bare = {k: v for k, v in body.items() if k not in ('secrets', 'secrets_encrypted')}
        refusal = self.assertDenied('BODY_NOT_TEMPLATE', self.send, self.tampered(admitted, bare), resolved)
        self.assertEqual(refusal.context['field'], 'tags')


class SendCreateRechecks(D1Fixture):
    """The independent review's R1 (fixed forward): send_create re-runs the D1 stage's content checks, from the
    approved profile the admitted create carries, so an admitted create built without admit's check is refused
    and nothing is sent."""

    def admitted_without_the_content_check(self, template):
        manifest = self.approve_d1(template)
        resolved = self.resolve_d1(manifest)
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='d1-test')
        with unittest.mock.patch.object(di, 'check_stage_template', lambda template, stage: None):
            admitted = self.admit(resolved, manifest)
        self.assertEqual(self.transport.calls, [])
        return manifest, resolved, admitted

    def test_an_admitted_create_that_skipped_the_content_check_is_refused_at_send(self):
        cases = {
            'AGENT_BLOCK_NOT_ACP': candidate_with(lambda body: body['agent_settings'].update(agent_kind='openhands')),
            'STAGE_TEMPLATE_DISPOSABLE': json.dumps(FIXTURE, indent=1).encode('utf-8'),
        }
        for code, template in cases.items():
            with self.subTest(code):
                self.transport = adm.CountingTransport()
                manifest, resolved, admitted = self.admitted_without_the_content_check(template)
                self.assertDenied(code, self.admit, resolved, manifest)  # admit itself refuses it
                self.assertDenied(code, self.send, admitted, resolved)
                self.fail_live()

    def test_the_carried_profile_must_be_the_approved_one(self):
        _, resolved, admitted = self.reserved_d1()
        other = (self.profiles / 'strong-test-profile' / 'profile.json').read_bytes()
        for name, raw in {'another profile': other, 'one byte more': admitted.profile_bytes + b' ',
                          'empty': b''}.items():
            with self.subTest(name):
                self.assertDenied('PROFILE_DRIFTED', self.send, dataclasses.replace(admitted, profile_bytes=raw),
                                  resolved)
        self.assertDenied('PROFILE_MISSING', self.send, dataclasses.replace(admitted, profile_bytes=None), resolved)
        self.send(admitted, resolved)
        self.assertEqual(len(self.transport.calls), 1)


class DeclarationRefusals(D1Fixture):
    def test_a_malformed_declaration_is_refused_at_resolution(self):
        good = {'stage': 'implement', 'path': D1_PATH, 'sha256': sha(CANDIDATE_BYTES)}
        cases = {
            'not an object': ['implement', D1_PATH],
            'no stage': {k: v for k, v in good.items() if k != 'stage'},
            'an unknown stage': dict(good, stage='deploy'),
            'a stage in another case': dict(good, stage='Implement'),
            'no path': {k: v for k, v in good.items() if k != 'path'},
            'an absolute path': dict(good, path=f'/{D1_PATH}'),
            'a backslash path': dict(good, path=D1_PATH.replace('/', chr(92))),
            'another profile\'s directory': dict(good, path='profiles/strong-test-profile/agent-server/d1-create.json'),
            'a short digest': dict(good, sha256=sha(CANDIDATE_BYTES)[:63]),
            'an upper-case digest': dict(good, sha256=sha(CANDIDATE_BYTES).upper()),
            'no digest': {k: v for k, v in good.items() if k != 'sha256'},
        }
        for name, pin in cases.items():
            with self.subTest(name):
                manifest = self.approve_d1(pin=pin)
                self.assertRefused('PROFILE_ADMISSION_INVALID', self.d1_request(), manifest, self.d1_sources)
                # The declaration is checked whichever stage is asked for.
                self.assertRefused('PROFILE_ADMISSION_INVALID',
                                   self.d1_request(repository='other-app', stage='review', catalog_pin='reviewer-pin'),
                                   manifest, self.d1_sources)

    def test_a_missing_template_is_refused_at_admission(self):
        manifest = self.approve_d1(template=None, pin={'stage': 'implement', 'path': f'profiles/{D1}/agent-server/absent.json',
                                                       'sha256': sha(CANDIDATE_BYTES)})
        self.assertDenied('PROFILE_ARTIFACT_MISSING', self.admit, self.resolve_d1(manifest), manifest)


if __name__ == '__main__':
    unittest.main()
