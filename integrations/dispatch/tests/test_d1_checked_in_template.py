"""Tests for the D1 stage's create admission on the CHECKED-IN profile (plan leaf E-05.2, the pin), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -p test_d1_checked_in_template.py -v

The checked-in ``strong-windows-qemu-whpx`` profile pins the approved D1 create template
(``provisioning.agent_server.stage_create_template``: stage ``implement``, the path and sha256 of
``agent-server/d1-create.json``, the native execution profile). On that declaration, copied byte for byte into a
throwaway directory and approved by a throwaway manifest, the proof's clauses:

* the template's agent block is admitted: a native D1 create (E-05.9's four secrets, ``HTTPS_PROXY`` the profile's
  tunnel endpoint) passes admission and is sent once (``AdmitsTheApprovedBlock``), and the review stage keeps
  E-01.2.2's F-04.2 fixture;
* any other agent block is refused (``RefusesAnyOtherBlock``): ``BODY_NOT_TEMPLATE`` for every block the native
  stage's shared agent check admits, that check's code for the rest;
* the F-04.2 fixture pinned for the ``implement`` stage is ``STAGE_TEMPLATE_DISPOSABLE`` (``RefusesTheF042Fixture``);
* a template whose bytes differ from the pinned sha256 is ``PROFILE_ARTIFACT_DRIFTED`` (``RefusesADriftedTemplate``).

E-01.3.3's custody probe and E-01.2.2's live drill use the declaration with that pin removed and nothing else
(``declaration_support``; ``TheProbeDerivation``).

The Agent Server is the E-01.3.1 fake or the E-01.2.2 counting transport; the credential provider is in memory and
the native token synthetic. No broker, guest, provider, model or credential store is used.
"""
from pathlib import Path
import copy
import dataclasses
import hashlib
import importlib.util
import json
import sys
import unittest

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


native_tests = _load('test_native_d1_stage', HERE / 'test_native_d1_stage.py')
d1, cc, NS, NT = native_tests.d1, native_tests.cc, native_tests.NS, native_tests.NT
adm, base, di, store_mod = d1.adm, d1.base, d1.di, d1.store_mod
cs = di.secrets_check

REAL = 'strong-windows-qemu-whpx'
REAL_BYTES = (base.REPO / 'profiles' / REAL / 'profile.json').read_bytes()
REAL_DECLARED = json.loads(REAL_BYTES)
SERVER = REAL_DECLARED['provisioning']['agent_server']
PIN = SERVER[di.STAGE_TEMPLATE_KEY]
FIXTURE_PIN = {'path': SERVER['fixture']['path'], 'sha256': SERVER['fixture']['sha256']}
TEMPLATE_PATH = f'profiles/{REAL}/agent-server/d1-create.json'
TOKEN = native_tests.TOKEN          # the in-memory provider's synthetic native token (NativeFixture)
PROXY = cs.tunnel_endpoint(REAL_DECLARED, refused=di.DispatchRefused)
SPELLING = native_tests.SPELLING


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ThePin(unittest.TestCase):
    """The checked-in declaration pins the approved template for the native D1 stage, and nothing else changes."""
    category = 'unit'

    def test_the_checked_in_profile_pins_the_approved_template(self):
        self.assertEqual(di.stage_create_template(REAL_DECLARED, REAL),
                         {'stage': 'implement', 'path': TEMPLATE_PATH, 'sha256': sha(d1.D1_TEMPLATE_BYTES),
                          di.EXECUTION_PROFILE_KEY: di.NATIVE})
        self.assertEqual(set(PIN) - {'stage', 'path', 'sha256', di.EXECUTION_PROFILE_KEY}, {'plan_leaf', 'purpose'})
        self.assertNotIn(di.GRANT_KEY, PIN)      # the native profile takes no inference grant (decision 0023 s5)
        self.assertEqual(di.admission_policy(REAL_DECLARED, REAL, 'implement')['create_template'],
                         {'path': TEMPLATE_PATH, 'sha256': PIN['sha256']})
        for stage in (None, 'review'):
            with self.subTest(stage=stage):
                self.assertEqual(di.admission_policy(REAL_DECLARED, REAL, stage)['create_template'], FIXTURE_PIN)
        self.assertEqual(PROXY, 'http://172.17.0.1:8090')


def differing_paths(a, b, path=()):
    """The paths at which two JSON values differ (a key present on one side only counts at its own path)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = set()
        for key in set(a) | set(b):
            if key not in a or key not in b:
                out.add(path + (key,))
            else:
                out |= differing_paths(a[key], b[key], path + (key,))
        return out
    return set() if di._same(a, b) else {path}


class TheProbeDerivation(unittest.TestCase):
    """E-01.3.3's custody probe and E-01.2.2's live drill use the checked-in declaration with exactly one derivation,
    the implement stage's D1 template pin removed (declaration_support; the engineering manager's ruling of
    2026-11-15): the derived declaration differs from the checked-in one by that key only, so any other drift of
    the checked-in declaration reaches them unchanged."""
    category = 'unit'

    def setUp(self):
        self.ds = _load('declaration_support', HERE / 'declaration_support.py')

    def test_the_derived_declaration_differs_by_the_pin_only(self):
        derived = json.loads(self.ds.derived_declaration_bytes())
        self.assertEqual(self.ds.checked_in_bytes(), REAL_BYTES)
        self.assertEqual(differing_paths(REAL_DECLARED, derived), {self.ds.DERIVED_PATH})
        self.assertEqual(self.ds.DERIVED_PATH, ('provisioning', 'agent_server', di.STAGE_TEMPLATE_KEY))
        self.assertIn(di.STAGE_TEMPLATE_KEY, REAL_DECLARED['provisioning']['agent_server'])
        self.assertNotIn(di.STAGE_TEMPLATE_KEY, derived['provisioning']['agent_server'])
        # Its implement stage is E-01.2.2's: no D1 stage, the F-04.2 fixture.
        self.assertIsNone(di.stage_create_template(derived, REAL))
        self.assertEqual(di.admission_policy(derived, REAL, 'implement')['create_template'], FIXTURE_PIN)
        self.assertEqual(di.admission_policy(derived, REAL, 'implement'),
                         di.admission_policy(REAL_DECLARED, REAL, 'review'))

    def test_every_byte_outside_the_removed_member_is_the_checked_in_declarations(self):
        """Review S1: the removal is textual; the result is the checked-in bytes with exactly the member's span cut
        out, and it parses with the dispatcher's strict reader to the checked-in declaration less that key."""
        text = REAL_BYTES.decode('utf-8')
        start, end = self.ds.removed_span(text)
        derived = self.ds.derived_declaration_bytes()
        self.assertEqual(derived, REAL_BYTES[:len(text[:start].encode('utf-8'))] +
                         REAL_BYTES[len(text[:end].encode('utf-8')):])
        self.assertEqual(len(REAL_BYTES) - len(derived), len(text[start:end].encode('utf-8')))
        removed = text[start:end]
        self.assertTrue(removed.lstrip().startswith('"stage_create_template": {'), removed[:40])
        self.assertTrue(removed.endswith('},\n'), removed[-10:])
        self.assertEqual(di._canonical(di._strict_loads(derived.decode('utf-8'))),
                         di._canonical(self.ds.without_d1_stage_pin(di._strict_loads(text))))
        # the member as the last of its object: the preceding comma goes with it
        last = '{\n  "a": 1,\n  "stage_create_template": {"stage": "implement"}\n}\n'
        s, e = self.ds.removed_span(last)
        self.assertEqual(last[:s] + last[e:], '{\n  "a": 1\n}\n')

    def test_drift_the_dispatcher_refuses_fails_the_derivation(self):
        """Review S1, the reviewer's reproduction: a duplicate status.operational (false first) in the source. The
        dispatcher's strict reader refuses it (PROFILE_INVALID); the derivation refuses it too, never hiding it."""
        text = REAL_BYTES.decode('utf-8')
        duplicate = text.replace('"status": {', '"status": {\n    "operational": false,', 1)
        with self.assertRaises(ValueError):
            di._strict_loads(duplicate)
        cases = {
            'a duplicate status.operational': duplicate,
            'a duplicate key inside the pin': text.replace('"stage": "implement",',
                                                           '"stage": "implement",\n        "stage": "implement",', 1),
            'a non-standard constant': text.replace('"ipv6": false', '"ipv6": NaN', 1),
            'the key elsewhere too': text.replace('"status": {', '"status": {\n    "stage_create_template": 1,', 1),
        }
        for name, source in cases.items():
            with self.subTest(name):
                self.assertNotEqual(source, text)
                with self.assertRaises(ValueError):
                    self.ds.derived_declaration_bytes(source.encode('utf-8'))

    def test_the_derivation_is_one_removal_never_a_pass_through(self):
        without = copy.deepcopy(REAL_DECLARED)
        del without['provisioning']['agent_server'][di.STAGE_TEMPLATE_KEY]
        other_stage = copy.deepcopy(REAL_DECLARED)
        other_stage['provisioning']['agent_server'][di.STAGE_TEMPLATE_KEY]['stage'] = 'review'
        for name, declared in {'no pin': without, 'a pin for another stage': other_stage,
                               'no provisioning': {'name': REAL}}.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    self.ds.without_d1_stage_pin(declared)
        self.assertEqual(differing_paths(REAL_DECLARED, self.ds.without_d1_stage_pin(REAL_DECLARED)),
                         {self.ds.DERIVED_PATH})
        self.assertIn('stage_create_template', self.ds.DERIVATION)

    def test_the_probe_and_the_drill_build_their_declaration_through_it(self):
        for script in ('live_custody_probe.py', 'live_admitted_create.py'):
            with self.subTest(script):
                text = (HERE / script).read_text(encoding='utf-8')
                self.assertIn('declaration.derived_declaration_bytes()', text)
                self.assertIn("'declaration_derivation'", text)
                self.assertNotIn("/ 'profile.json').read_bytes()", text)


class CheckedInFixture(native_tests.NativeFixture):
    """The E-01.2.2 admission fixture with the checked-in strong-windows-qemu-whpx declaration, byte for byte unless
    a test names other bytes, its pinned F-04.2 fixture, route allowlist and D1 template, bound to demo-app/implement
    and other-app/review."""

    def approve_real(self, declared=REAL_BYTES, template=d1.D1_TEMPLATE_BYTES):
        directory = self.profiles / REAL
        if not directory.exists():
            directory.mkdir()
            self.addCleanup(base.rmtree, directory)
        base.write_agent_server(directory)
        (directory / 'agent-server' / 'd1-create.json').write_bytes(template)
        (directory / 'profile.json').write_bytes(declared)
        data = self.manifest_data()
        data['designs'].append({'repository': 'other-app', 'change': base.CHANGE, 'commit': self.commit})
        data['profiles'].append({'id': REAL, 'sha256': self.profile_sha(REAL)})
        for binding in data['bindings']:
            binding['profiles'].append(REAL)
        return self.write_manifest(data, self.fresh('checked-in'))

    def real_request(self, **changes):
        return self.request(profile=REAL, **changes)

    def resolve_real(self, manifest, **changes):
        return self.resolve(self.real_request(**changes), manifest, self.d1_sources)

    def review(self, manifest):
        return self.resolve_real(manifest, repository='other-app', stage='review', catalog_pin='reviewer-pin')

    def reserved_real(self):
        """A reserved native D1 attempt on the checked-in profile and its create, admitted with its secrets."""
        manifest = self.approve_real()
        resolved = self.resolve_real(manifest)
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='e-05.2-test')
        pre = self.admit(resolved, manifest)
        return manifest, resolved, di.admit_secrets(pre, resolved=resolved, workspaces=self.workspaces,
                                                    grant=NT.NativeToken(TOKEN))

    def sent_body(self, conversation_id):
        """The native D1 create as sent: the approved template, the reserved id and the four secrets."""
        body = copy.deepcopy(d1.D1_TEMPLATE)
        body['conversation_id'] = conversation_id
        body['secrets'] = {'CLAUDE_CODE_OAUTH_TOKEN': {'kind': 'StaticSecret', 'value': TOKEN},
                           'HTTPS_PROXY': {'kind': 'StaticSecret', 'value': PROXY},
                           'CLAUDE_CODE_PROXY_RESOLVES_HOSTS': {'kind': 'StaticSecret', 'value': SPELLING},
                           'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': {'kind': 'StaticSecret', 'value': SPELLING}}
        body['secrets_encrypted'] = False
        return body


class AdmitsTheApprovedBlock(CheckedInFixture):
    def test_the_native_d1_create_is_dispatched_with_the_approved_block(self):
        """The dispatcher's whole order (resolve, reserve, admit, the native token read, admit_secrets, send) on
        the checked-in declaration: one create, the approved template with the native secret set."""
        server = cc.FakeAgentServer()
        result = di.dispatch(self.real_request(), manifest=self.approve_real(), work_sources=self.d1_sources.get,
                             integration_store=self.store, workspaces=self.workspaces, transport=server,
                             actor='e-05.2-test', read_profile=self.read_profile, read_artifact=self.read_artifact,
                             inference=native_tests.NoBroker(), native_credentials=self.provider)
        [(_, _, body)] = server.creates
        self.assertEqual(body, self.sent_body(result.conversation_id))
        self.assertEqual(body['agent_settings'], d1.qualified_create()['agent_settings'])
        self.assertEqual(self.provider.reads, [NT.ENTRY])

    def test_admission_binds_the_pinned_digest(self):
        manifest, resolved, admitted = self.reserved_real()
        self.assertEqual(resolved.policy_inputs['admission']['create_template'],
                         {'path': TEMPLATE_PATH, 'sha256': PIN['sha256']})
        staged = di.stage_inference(admitted, resolved=resolved)
        self.assertIsInstance(staged, di.StageNative)
        self.assertEqual(staged.endpoint, PROXY)
        self.send(admitted, resolved)
        self.assertEqual(self.transport.calls, [('POST', '/api/conversations',
                                                 self.sent_body(admitted.conversation_id))])
        self.assertEqual(admitted.to_json()['create_template_sha256'], PIN['sha256'])
        self.assertEqual(admitted.profile_bytes, REAL_BYTES)

    def test_the_review_stage_keeps_the_f042_fixture(self):
        """The boundary: E-05.2 is the D1 stage only; the checked-in profile's review stage keeps E-01.2.2."""
        manifest = self.approve_real()
        resolved = self.review(manifest)
        self.assertEqual(resolved.policy_inputs['admission']['create_template'], FIXTURE_PIN)
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='e-05.2-test')
        self.send(self.admit(resolved, manifest), resolved)
        expected = dict(copy.deepcopy(d1.FIXTURE),
                        conversation_id=store_mod.conversation_id_for(resolved.attempt_identity().operation_key))
        self.assertEqual(self.transport.calls, [('POST', '/api/conversations', expected)])


class RefusesAnyOtherBlock(CheckedInFixture):
    def approved(self):
        return copy.deepcopy(d1.D1_TEMPLATE['agent_settings'])

    def variant(self, **changes):
        return {**self.approved(), **changes}

    def without(self, name):
        return {k: v for k, v in self.approved().items() if k != name}

    def native_admissible(self):
        """Blocks the native stage's shared agent check admits (create_secrets.AGENT_SETTING_RULES) that are not the
        template's: only the template comparison tells them apart."""
        return {
            'another model': self.variant(acp_model='claude-other-model'),
            'acp_args omitted': self.without('acp_args'),
            'acp_session_mode omitted': self.without('acp_session_mode'),
            'mcp_config omitted': self.without('mcp_config'),
            'agent_context null': self.variant(agent_context=None),
            'acp_file_secrets empty': self.variant(acp_file_secrets=[]),
        }

    def refused_by_the_shared_check(self):
        """Blocks the shared native agent check refuses first (check_create_body runs it before the comparison)."""
        return {
            'the F-04.2 bare agent': (copy.deepcopy(d1.FIXTURE['agent_settings']), 'NATIVE_ACP_COMMAND_NOT_PINNED'),
            'agent_kind openhands': (self.variant(agent_kind='openhands'), 'NATIVE_ACP_COMMAND_NOT_PINNED'),
            'another acp_server': (self.variant(acp_server='custom'), 'NATIVE_ACP_COMMAND_NOT_PINNED'),
            'the npx form (empty command)': (self.variant(acp_command=[]), 'NATIVE_ACP_COMMAND_NOT_PINNED'),
            'an npx command': (self.variant(acp_command=['npx', '-y', 'claude-agent-acp']),
                               'NATIVE_ACP_COMMAND_NOT_PINNED'),
            'acp_args': (self.variant(acp_args=['--verbose']), 'NATIVE_ACP_COMMAND_NOT_PINNED'),
            'another session mode': (self.variant(acp_session_mode='default'), 'NATIVE_AGENT_SETTING_FORBIDDEN'),
            'a shared data dir': (self.variant(acp_isolate_data_dir=False), 'NATIVE_CONFIG_DIR_RELOCATED'),
            'an MCP server': (self.variant(mcp_config={'mcpServers': {'fetch': {'command': 'uvx'}}}),
                              'NATIVE_MCP_FORBIDDEN'),
            'tools': (self.variant(tools=[{'name': 'terminal'}]), 'NATIVE_AGENT_SETTING_FORBIDDEN'),
            'an agent context': (self.variant(agent_context={'skills': []}), 'NATIVE_AGENT_CONTEXT_FORBIDDEN'),
            'the data-dir key missing': (self.without('acp_isolate_data_dir'), 'NATIVE_CONFIG_DIR_RELOCATED'),
            'model as a number': (self.variant(acp_model=1), 'NATIVE_AGENT_SETTING_FORBIDDEN'),
            'not an object': ('acp', 'NATIVE_ACP_COMMAND_NOT_PINNED'),
            'null': (None, 'NATIVE_ACP_COMMAND_NOT_PINNED'),
        }

    def test_a_block_the_shared_check_admits_is_body_not_template(self):
        _, resolved, admitted = self.reserved_real()
        for name, block in self.native_admissible().items():
            with self.subTest(name):
                body = dict(admitted.body, agent_settings=block)
                refusal = self.assertDenied('BODY_NOT_TEMPLATE', self.send, self.tampered(admitted, body), resolved)
                self.assertEqual(refusal.context['field'], 'agent_settings')

    def test_every_other_block_is_refused_before_the_create(self):
        _, resolved, admitted = self.reserved_real()
        for name, (block, code) in self.refused_by_the_shared_check().items():
            with self.subTest(name):
                body = dict(admitted.body, agent_settings=block)
                self.assertDenied(code, self.send, self.tampered(admitted, body), resolved)
                self.assertIn(code, cs.NATIVE_MEANINGS)


class RefusesTheF042Fixture(CheckedInFixture):
    def test_the_fixture_pinned_for_the_implement_stage_is_refused_at_resolution(self):
        cases = {
            'its path and digest': FIXTURE_PIN,
            'its path, the template\'s digest': {'path': FIXTURE_PIN['path'], 'sha256': PIN['sha256']},
            'its digest at the template\'s path': {'path': TEMPLATE_PATH, 'sha256': FIXTURE_PIN['sha256']},
        }
        for name, change in cases.items():
            with self.subTest(name):
                declared = copy.deepcopy(REAL_DECLARED)
                declared['provisioning']['agent_server'][di.STAGE_TEMPLATE_KEY].update(change)
                manifest = self.approve_real(declared=(json.dumps(declared, indent=2) + '\n').encode('utf-8'))
                refusal = self.assertRefused('STAGE_TEMPLATE_DISPOSABLE', self.real_request(), manifest,
                                             self.d1_sources)
                self.assertEqual(refusal.context['stage'], 'implement')

    def test_a_create_built_from_the_fixture_is_refused_on_the_implement_stage(self):
        _, resolved, admitted = self.reserved_real()
        body = {**copy.deepcopy(d1.FIXTURE), 'conversation_id': admitted.conversation_id,
                'secrets': admitted.body['secrets'], 'secrets_encrypted': False}
        self.assertDenied('PROFILE_ARTIFACT_DRIFTED', self.send, dataclasses.replace(
            self.tampered(admitted, body), template_bytes=base.TEMPLATE_BYTES), resolved)
        self.assertDenied('NATIVE_ACP_COMMAND_NOT_PINNED', self.send, self.tampered(admitted, body), resolved)


class RefusesADriftedTemplate(CheckedInFixture):
    def test_template_bytes_other_than_the_pin_are_refused(self):
        others = {
            'one byte more': d1.D1_TEMPLATE_BYTES + b'\n',
            're-serialized': json.dumps(d1.D1_TEMPLATE, indent=1).encode('utf-8'),
            'another model': d1.template_with(lambda body: body['agent_settings'].update(acp_model='claude-other')),
            'another tag': d1.template_with(lambda body: body.update(tags={'aieh': 'e-05.2-d1-other'})),
        }
        for name, other in others.items():
            with self.subTest(name):
                manifest = self.approve_real(template=other)        # the checked-in declaration, unchanged
                refusal = self.assertDenied('PROFILE_ARTIFACT_DRIFTED', self.admit, self.resolve_real(manifest),
                                            manifest)
                self.assertEqual((refusal.context['pinned'], refusal.context['actual']), (PIN['sha256'], sha(other)))

    def test_an_admitted_create_carrying_other_template_bytes_is_refused_at_send(self):
        _, resolved, admitted = self.reserved_real()
        other = d1.template_with(lambda body: body['agent_settings'].update(acp_model='claude-other'))
        self.assertDenied('PROFILE_ARTIFACT_DRIFTED', self.send, dataclasses.replace(admitted, template_bytes=other),
                          resolved)
        self.send(admitted, resolved)
        self.assertEqual(len(self.transport.calls), 1)


if __name__ == '__main__':
    unittest.main()
