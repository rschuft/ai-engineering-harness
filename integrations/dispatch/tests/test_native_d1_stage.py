"""Tests for the D1 stage's create on the native profile: the native token's read and its secrets block (plan leaf
E-05.9, decision 0023), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -p test_native_d1_stage.py -v

The proof, clause by clause:

* For the D1 stage on the native profile, E-01.2.2's admission (``admit``, then ``admit_secrets``) accepts a create
  whose secrets block holds exactly decision 0023's four names, each a StaticSecret, with ``secrets_encrypted``
  false: the native token, HTTPS_PROXY equal to the profile's tunnel endpoint, and the two switches with their
  declared spellings (``Accepts``).
* Every other shape (another, additional or missing name, ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL,
  ANTHROPIC_AUTH_TOKEN, an OH_ name and the brokered names included; another kind, a LookupSecret included;
  secrets_encrypted true; another proxy endpoint; a switch other than its spelling, 1 and true included; a token
  without the shape; the token or a part of it outside its secret; an MCP configuration; another ACP command; a
  relocated configuration directory) is refused with a stable code at admission and again by ``send_create`` before
  the transport, which is then called zero times; a create mixing the native and brokered sets is refused
  (``Refusals``, ``Mixing``).
* Every other stage still refuses secrets (BODY_FIELD_UNKNOWN), and the S-03.3 qualification fixture is still
  refused for a native D1 stage (``OtherStages``; E-05.6's and E-05.2's own suites show the brokered profile).
* The check is the one shared with E-05.11's qualification admission, not a copy (``SharedCheck``).
* The dispatcher reads the native token entry only after the reservation and every other input are admitted
  (``ReadOrder``), and reads no other credential entry and no host Claude configuration, shown by a negative
  control with positive controls (``NoOtherCredential``).
* No store record, admitted-create record, report or log carries the token, only its fingerprint (``Custody``).

The template is E-05.2's candidate with a synthetic model, pinned by a synthetic profile in a throwaway directory
that declares the native profile and a tunnel endpoint (no checked-in profile declares either yet: E-05.10 declares
the tunnel). The Agent Server is the E-01.3.1 fake. The credential provider is in memory; the token is synthetic,
built at run time. No broker, guest, provider, model or credential store is used.
"""
from pathlib import Path
import ast
import contextlib
import copy
import dataclasses
import importlib.util
import io
import json
import logging
import os
import pickle
import sys
import tempfile
import unittest
from unittest import mock

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


secrets_tests = _load('test_d1_stage_secrets', HERE / 'test_d1_stage_secrets.py')
d1, cc = secrets_tests.d1, secrets_tests.cc
adm, base, di, store_mod = d1.adm, d1.base, d1.di, d1.store_mod
cs = di.secrets_check
NS = _load('native_support', HERE / 'native_support.py')
NT = di._native_module()
TOKEN = NS.token()
OTHER = NS.token('another native token')
API_KEY = 'sk-ant-' + 'api03-' + 'k' * 60 + '-synthetic'
PORT = 8443
TUNNEL = {'class': 'provider-tunnel', 'guest_address': '172.17.0.1', 'guest_port': PORT}
PROXY = f'http://172.17.0.1:{PORT}'
SPELLING = 'tRuE'
NAMES = ('CLAUDE_CODE_OAUTH_TOKEN', 'HTTPS_PROXY', 'CLAUDE_CODE_PROXY_RESOLVES_HOSTS',
         'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC')


class NoBroker:
    """The native profile involves no broker: any call to the inference access fails the test."""

    def __getattr__(self, name):
        raise AssertionError(f'the native D1 stage called the broker ({name})')


class NativeFixture(d1.D1Fixture):
    def setUp(self):
        super().setUp()
        self.provider = NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, TOKEN)})

    def approve_native(self, template=d1.TEST_TEMPLATE_BYTES, endpoints=(TUNNEL,), change=None):
        """strong-d1-profile on the native profile: the stage template's pin declares execution_profile native
        and no inference grant; the profile declares the tunnel endpoint (ENDPOINTS); CHANGE, then, the
        declaration."""
        def native(declared):
            pin = declared['provisioning']['agent_server'][di.STAGE_TEMPLATE_KEY]
            del pin[di.GRANT_KEY]
            pin[di.EXECUTION_PROFILE_KEY] = di.NATIVE
            declared['network'] = {'endpoints': [dict(e) for e in endpoints]}
            if change is not None:
                change(declared)
        return self.approve_d1(template, change=native)

    def run_native(self, transport, provider=None, manifest=None, request=None, **kwargs):
        return di.dispatch(self.d1_request() if request is None else request,
                           manifest=manifest or self.approve_native(), work_sources=self.d1_sources.get,
                           integration_store=self.store, workspaces=self.workspaces, transport=transport,
                           actor='e-05.9-test', read_profile=self.read_profile, read_artifact=self.read_artifact,
                           inference=NoBroker(), native_credentials=self.provider if provider is None else provider,
                           **kwargs)

    def reserved_pre(self, manifest=None):
        manifest = manifest or self.approve_native()
        resolved = self.resolve_d1(manifest)
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='e-05.9-test')
        return manifest, resolved, self.admit(resolved, manifest)

    def reserved_native(self):
        manifest, resolved, pre = self.reserved_pre()
        return manifest, resolved, di.admit_secrets(pre, resolved=resolved, workspaces=self.workspaces,
                                                    grant=NT.NativeToken(TOKEN))

    def native_body(self, resolved, template=None):
        """The admitted body of a native D1 create: the template, the reserved conversation id, the four secrets
        (the token's value the slot the held token takes at the send)."""
        body = copy.deepcopy(d1.TEST_TEMPLATE if template is None else template)
        body['conversation_id'] = store_mod.conversation_id_for(resolved.attempt_identity().operation_key)
        body['secrets'] = {'CLAUDE_CODE_OAUTH_TOKEN': {'kind': 'StaticSecret', 'value': di.NATIVE_SLOT},
                           'HTTPS_PROXY': {'kind': 'StaticSecret', 'value': PROXY},
                           'CLAUDE_CODE_PROXY_RESOLVES_HOSTS': {'kind': 'StaticSecret', 'value': SPELLING},
                           'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': {'kind': 'StaticSecret', 'value': SPELLING}}
        body['secrets_encrypted'] = False
        return body

    def at_admission(self, body, admitted, resolved):
        """The admission validator on BODY with the held token in place (as admit_secrets and send_create run it)."""
        staged = di.stage_inference(admitted, resolved=resolved)
        with self.assertRaises(di.DispatchRefused) as caught:
            di.check_create_body(di._wire_body(body, staged, admitted.inference),
                                 admission=resolved.policy_inputs['admission'],
                                 template=json.loads(admitted.template_bytes), conversation_id=admitted.conversation_id,
                                 secrets=staged.secrets(admitted.inference, admitted.operation_key))
        return caught.exception

    def tampered(self, admitted, body):
        return dataclasses.replace(admitted, body_json=di._canonical(body))

    def detail(self, key, to_state):
        events = [e for e in self.store.events(key) if e.to_state == to_state]
        self.assertEqual(len(events), 1)
        return json.loads(events[0].detail_json)

    def assertNoToken(self, *texts):
        for text in texts:
            for needle in (TOKEN, TOKEN[len(NS.PREFIX):]):
                self.assertNotIn(needle, text)


class Accepts(NativeFixture):
    def test_the_native_create_carries_exactly_the_four_static_secrets(self):
        server = cc.FakeAgentServer()
        result = self.run_native(server)
        [(_, _, body)] = server.creates
        self.assertEqual(body['secrets'], {'CLAUDE_CODE_OAUTH_TOKEN': {'kind': 'StaticSecret', 'value': TOKEN},
                                           'HTTPS_PROXY': {'kind': 'StaticSecret', 'value': PROXY},
                                           'CLAUDE_CODE_PROXY_RESOLVES_HOSTS': {'kind': 'StaticSecret',
                                                                                'value': SPELLING},
                                           'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': {'kind': 'StaticSecret',
                                                                                        'value': SPELLING}})
        self.assertIs(body['secrets_encrypted'], False)
        rest = {k: v for k, v in body.items() if k not in ('secrets', 'secrets_encrypted')}
        self.assertEqual(rest, dict(d1.TEST_TEMPLATE, conversation_id=result.conversation_id))
        for name in ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN'):
            self.assertNotIn(name, json.dumps(body))
        fingerprint = NT.fingerprint(TOKEN)
        self.assertEqual(result.to_json()['native_token']['tokenFingerprint'], fingerprint)
        self.assertNotIn('inference_grant', result.to_json())
        self.assertEqual(self.detail(result.operation_key, 'dispatched')['nativeToken']['tokenFingerprint'],
                         fingerprint)
        self.assertEqual(self.provider.reads, [NT.ENTRY])

    def test_the_declared_values(self):
        self.assertEqual(cs.NATIVE_NAMES, NAMES)
        self.assertEqual(cs.NATIVE_SWITCHES, {NAMES[2]: SPELLING, NAMES[3]: SPELLING})
        for spelling in cs.NATIVE_SWITCHES.values():   # collision-free: never 1 or true (decision 0023 section 3)
            self.assertNotIn(spelling, ('1', 'true'))
            self.assertIn(spelling.lower().strip(), ('1', 'true', 'yes', 'on'))   # what the pinned CLI accepts
        aq = di._inference_modules()[0]
        self.assertEqual(list(cs.BROKERED_NAMES), aq.registry_secret_names())
        _, resolved, pre = self.reserved_pre()
        staged = di.stage_inference(pre, resolved=resolved)
        self.assertIsInstance(staged, di.StageNative)
        self.assertEqual(staged.endpoint, PROXY)
        self.assertNotIn('secrets', pre.body)


class Refusals(NativeFixture):
    """Each refusal at admission (the admission validator with the stage's secrets) and again at send_create, before
    the transport."""

    def cases(self):
        def secret(value, kind='StaticSecret'):
            return {'kind': kind, 'value': value}

        def put(path, value):
            def change(body):
                node = body
                for part in path[:-1]:
                    node = node[part]
                node[path[-1]] = value
            return change

        def drop(path):
            def change(body):
                node = body
                for part in path[:-1]:
                    node = node[part]
                del node[path[-1]]
            return change
        token_at, proxy_at = ('secrets', NAMES[0], 'value'), ('secrets', NAMES[1], 'value')
        body_of = TOKEN[len(NS.PREFIX):]
        return [
            ('NATIVE_SECRETS_MIXED', 'ANTHROPIC_API_KEY added', put(('secrets', 'ANTHROPIC_API_KEY'), secret('x'))),
            ('NATIVE_SECRETS_MIXED', 'ANTHROPIC_BASE_URL added', put(('secrets', 'ANTHROPIC_BASE_URL'), secret(PROXY))),
            ('NATIVE_SECRET_NAMES', 'ANTHROPIC_AUTH_TOKEN added', put(('secrets', 'ANTHROPIC_AUTH_TOKEN'), secret('x'))),
            ('NATIVE_SECRET_NAMES', 'the brokered set instead', put(('secrets',), {
                'ANTHROPIC_API_KEY': secret('x'), 'ANTHROPIC_BASE_URL': secret(PROXY)})),
            ('NATIVE_SECRET_NAMES', 'an OH_ name added', put(('secrets', 'OH_SECRET_KEY'), secret('x'))),
            ('NATIVE_SECRET_NAMES', 'CLAUDE_CONFIG_DIR as a secret', put(('secrets', 'CLAUDE_CONFIG_DIR'), secret('/x'))),
            ('NATIVE_SECRET_NAMES', 'the token missing', drop(('secrets', NAMES[0]))),
            ('NATIVE_SECRET_NAMES', 'a switch missing', drop(('secrets', NAMES[3]))),
            ('NATIVE_SECRET_NAMES', 'no secrets field', drop(('secrets',))),
            ('NATIVE_SECRET_NAMES', 'secrets null', put(('secrets',), None)),
            ('SECRET_KIND_FORBIDDEN', 'the token a LookupSecret', put(('secrets', NAMES[0]), {
                'kind': 'LookupSecret', 'url': PROXY + '/token', 'headers': {}})),
            ('SECRET_KIND_FORBIDDEN', 'a switch a LookupSecret', put(('secrets', NAMES[2]), secret(SPELLING,
                                                                                                    'LookupSecret'))),
            ('SECRET_KIND_FORBIDDEN', 'a description beside', put(('secrets', NAMES[1], 'description'), 'd')),
            ('SECRET_KIND_FORBIDDEN', 'a bare string', put(('secrets', NAMES[1]), PROXY)),
            ('SECRETS_ENCRYPTED', 'secrets_encrypted true', put(('secrets_encrypted',), True)),
            ('SECRETS_ENCRYPTED', 'secrets_encrypted missing', drop(('secrets_encrypted',))),
            ('NATIVE_TOKEN_NOT_SHAPED', 'an empty token', put(token_at, '')),
            ('NATIVE_TOKEN_NOT_SHAPED', 'an API key as the token', put(token_at, API_KEY)),
            ('NATIVE_TOKEN_NOT_SHAPED', 'an attempt token as the token', put(token_at, 'aieh-inf-' + 'a' * 43)),
            ('NATIVE_TOKEN_NOT_SHAPED', 'a bearer header', put(token_at, 'Bearer ' + TOKEN)),
            ('NATIVE_TOKEN_NOT_SHAPED', 'the token with a line break', put(token_at, TOKEN + '\n')),
            ('NATIVE_TOKEN_OUTSIDE_SECRET', 'the token in a tag', put(('tags', 'aieh'), TOKEN)),
            ('NATIVE_TOKEN_OUTSIDE_SECRET', 'the token as a tag key', put(('tags', TOKEN), 'x')),
            ('NATIVE_TOKEN_OUTSIDE_SECRET', 'the token\'s body in a tag', put(('tags', 'aieh'), 'p' + body_of)),
            ('NATIVE_TOKEN_OUTSIDE_SECRET', '8 characters of it in a tag', put(('tags', 'aieh'),
                                                                                '.' + body_of[20:28] + '.')),
            ('NATIVE_TOKEN_OUTSIDE_SECRET', 'the token in the proxy', put(proxy_at, f'{PROXY}/{TOKEN}')),
            ('NATIVE_SECOND_AUTH_METHOD', 'an API key in a tag', put(('tags', 'aieh'), API_KEY)),
            ('NATIVE_SECOND_AUTH_METHOD', 'another native token in a tag', put(('tags', 'aieh'), OTHER)),
            ('NATIVE_SECOND_AUTH_METHOD', 'ANTHROPIC_BASE_URL named in a tag', put(('tags', 'ANTHROPIC_BASE_URL'), 'x')),
            ('NATIVE_SECOND_AUTH_METHOD', 'ANTHROPIC_AUTH_TOKEN named in the model', put(
                ('agent_settings', 'acp_model'), 'ANTHROPIC_AUTH_TOKEN')),
            ('NATIVE_PROXY_NOT_TUNNEL', 'the provider\'s origin', put(proxy_at, 'https://api.anthropic.com')),
            ('NATIVE_PROXY_NOT_TUNNEL', 'another port', put(proxy_at, 'http://172.17.0.1:8444')),
            ('NATIVE_PROXY_NOT_TUNNEL', 'the broker\'s endpoint', put(proxy_at, 'http://172.17.0.1:8090')),
            ('NATIVE_PROXY_NOT_TUNNEL', 'the host loopback', put(proxy_at, f'http://127.0.0.1:{PORT}')),
            ('NATIVE_PROXY_NOT_TUNNEL', 'a trailing slash', put(proxy_at, PROXY + '/')),
            ('NATIVE_PROXY_NOT_TUNNEL', 'an empty proxy', put(proxy_at, '')),
            ('NATIVE_PROXY_NOT_TUNNEL', 'a destination in a tag', put(('tags', 'aieh'), 'http://198.51.100.7/')),
            ('NATIVE_SWITCH_NOT_DECLARED', 'resolves-hosts 1', put(('secrets', NAMES[2], 'value'), '1')),
            ('NATIVE_SWITCH_NOT_DECLARED', 'resolves-hosts true', put(('secrets', NAMES[2], 'value'), 'true')),
            ('NATIVE_SWITCH_NOT_DECLARED', 'nonessential 1', put(('secrets', NAMES[3], 'value'), '1')),
            ('NATIVE_SWITCH_NOT_DECLARED', 'nonessential true', put(('secrets', NAMES[3], 'value'), 'true')),
            ('NATIVE_SWITCH_NOT_DECLARED', 'nonessential TRUE', put(('secrets', NAMES[3], 'value'), 'TRUE')),
            ('NATIVE_SWITCH_NOT_DECLARED', 'an empty switch', put(('secrets', NAMES[2], 'value'), '')),
            ('NATIVE_MCP_FORBIDDEN', 'an MCP server', put(('agent_settings', 'mcp_config'), {
                'mcpServers': {'fetch': {'command': 'uvx', 'args': ['mcp-fetch']}}})),
            ('NATIVE_MCP_FORBIDDEN', 'an mcp_servers field', put(('agent_settings', 'mcp_servers'), [])),
            ('NATIVE_ACP_COMMAND_NOT_PINNED', 'another command', put(('agent_settings', 'acp_command'),
                                                                     ['npx', '-y', 'claude-agent-acp'])),
            ('NATIVE_ACP_COMMAND_NOT_PINNED', 'the npx form', put(('agent_settings', 'acp_command'), [])),
            ('NATIVE_ACP_COMMAND_NOT_PINNED', 'acp_args', put(('agent_settings', 'acp_args'), ['--verbose'])),
            ('NATIVE_ACP_COMMAND_NOT_PINNED', 'a custom server', put(('agent_settings', 'acp_server'), 'custom')),
            ('NATIVE_CONFIG_DIR_RELOCATED', 'a shared data dir', put(('agent_settings', 'acp_isolate_data_dir'),
                                                                     False)),
            ('NATIVE_CONFIG_DIR_RELOCATED', 'the isolation missing', drop(('agent_settings',
                                                                           'acp_isolate_data_dir'))),
            ('NATIVE_CONFIG_DIR_RELOCATED', 'CLAUDE_CONFIG_DIR named', put(('tags', 'CLAUDE_CONFIG_DIR'), '/data')),
        ]

    def test_every_other_create_is_refused_at_admission_and_at_send(self):
        _, resolved, admitted = self.reserved_native()
        cases = self.cases()
        self.assertEqual({code for code, _, _ in cases} | {'NATIVE_TOKEN_NOT_HELD', 'NATIVE_TUNNEL_UNDECLARED'},
                         set(cs.NATIVE_MEANINGS))
        for code, name, change in cases:
            with self.subTest(code=code, case=name):
                body = self.native_body(resolved)
                change(body)
                refusal = self.at_admission(body, admitted, resolved)
                self.assertEqual(refusal.code, code, refusal.detail)
                refusal = self.assertDenied(code, self.send, self.tampered(admitted, body), resolved)
                self.assertNoToken(*secrets_tests.SecretsFixture.texts_of(self, refusal))
        # The positive control on the same admitted create: it is sent, once, with the token in place.
        self.send(admitted, resolved)
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.transport.calls[0][2]['secrets'][NAMES[0]]['value'], TOKEN)

    def test_a_token_not_the_held_one_is_refused(self):
        _, resolved, admitted = self.reserved_native()
        literal = self.native_body(resolved)
        literal['secrets'][NAMES[0]]['value'] = OTHER   # a token in the body, not the slot, and not the held one
        self.assertEqual(self.at_admission(literal, admitted, resolved).code, 'NATIVE_TOKEN_NOT_HELD')
        self.assertDenied('NATIVE_TOKEN_NOT_HELD', self.send, self.tampered(admitted, literal), resolved)
        literal['secrets'][NAMES[0]]['value'] = TOKEN   # the held one itself, but from the body: never sent
        refusal = self.assertDenied('NATIVE_SECRET_NOT_FROM_ENTRY', self.send, self.tampered(admitted, literal),
                                    resolved)
        self.assertNoToken(*secrets_tests.SecretsFixture.texts_of(self, refusal))
        # A create without its token held cannot fill the slot.
        self.assertDenied('NATIVE_TOKEN_NOT_SHAPED', self.send, dataclasses.replace(admitted, inference=None), resolved)
        self.fail_live()
        _, resolved_pre, pre = self.reserved_pre()
        self.assertDenied('NATIVE_SECRET_NAMES', self.send, pre, resolved_pre)   # no secrets block at all

    def test_profile_and_template_refusals_come_before_any_read(self):
        def template_with(**changes):
            return d1.candidate_with(lambda body: body['agent_settings'].update(acp_model=d1.TEST_MODEL, **changes))
        cases = {
            'NATIVE_TUNNEL_UNDECLARED': [dict(endpoints=()), dict(endpoints=(TUNNEL, dict(TUNNEL, guest_port=9))),
                                         dict(endpoints=(dict(TUNNEL, guest_address='127.0.0.1'),)),
                                         dict(endpoints=(dict(TUNNEL, guest_port='8443'),)),
                                         dict(endpoints=(d1.INFERENCE_ENDPOINT,))],
            'NATIVE_MCP_FORBIDDEN': [dict(template=template_with(mcp_config={'mcpServers': {'x': {}}}))],
            'NATIVE_ACP_COMMAND_NOT_PINNED': [dict(template=template_with(acp_command=['claude']))],
            'NATIVE_CONFIG_DIR_RELOCATED': [dict(template=template_with(acp_isolate_data_dir=False))],
        }
        for code, variants in cases.items():
            for n, variant in enumerate(variants):
                with self.subTest(code=code, variant=n):
                    manifest = self.approve_native(**variant)
                    self.assertDenied(code, self.admit, self.resolve_d1(manifest), manifest)
                    with self.assertRaises(di.DispatchRefused) as caught:
                        self.run_native(cc.FakeAgentServer(), manifest=manifest)
                    self.assertEqual(caught.exception.code, code)
                    self.assertEqual(self.provider.reads, [])

    def test_the_declaration(self):
        def declared(**pin_changes):
            def change(declared):
                declared['provisioning']['agent_server'][di.STAGE_TEMPLATE_KEY].update(pin_changes)
            return change
        cases = {
            'the native profile with an inference grant': declared(inference_grant={'ttl_s': 600}),
            'an unknown execution profile': declared(execution_profile='hybrid'),
            'a native profile spelled otherwise': declared(execution_profile='Native'),
        }
        for name, change in cases.items():
            with self.subTest(name):
                manifest = self.approve_native(change=change)
                self.assertRefused('PROFILE_ADMISSION_INVALID', self.d1_request(), manifest, self.d1_sources)
        self.assertEqual(self.provider.reads, [])


class Mixing(NativeFixture):
    def test_a_credential_of_the_other_profile_is_refused(self):
        _, resolved, pre = self.reserved_pre()
        broker_grant = di.InferenceGrant(token='aieh-inf-' + 'b' * 43, fingerprint='sha256:' + '0' * 16,
                                         conversation_id=pre.conversation_id, attempt_id='x', family='f',
                                         models=[], expires_at=None)
        self.assertDenied('ADMISSION_MISMATCH', di.admit_secrets, pre, resolved=resolved, workspaces=self.workspaces,
                          grant=broker_grant)
        admitted = di.admit_secrets(pre, resolved=resolved, workspaces=self.workspaces, grant=NT.NativeToken(TOKEN))
        self.assertDenied('ADMISSION_MISMATCH', self.send, dataclasses.replace(admitted, inference=broker_grant),
                          resolved)

    def test_the_brokered_stage_refuses_the_native_set_and_the_native_token(self):
        """E-05.6's profile (its own fixture: a real broker in process issues the attempt token)."""
        _, resolved, admitted = self.reserved_d1()
        body = self.body_for(resolved, d1.TEST_TEMPLATE)
        body['secrets'][NAMES[0]] = {'kind': 'StaticSecret', 'value': TOKEN}
        refusal = self.assertDenied('SECRET_NAMES', self.send, self.tampered(admitted, body), resolved)
        self.assertNoToken(*secrets_tests.SecretsFixture.texts_of(self, refusal))
        self.fail_live()
        manifest = self.approve_d1()
        resolved = self.resolve_d1(manifest)
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='e-05.9-test')
        self.assertDenied('ADMISSION_MISMATCH', di.admit_secrets, self.admit(resolved, manifest), resolved=resolved,
                          workspaces=self.workspaces, grant=NT.NativeToken(TOKEN))


class OtherStages(NativeFixture):
    def test_every_other_stage_still_refuses_secrets_and_reads_no_token(self):
        manifest = self.approve_native()
        request = self.d1_request(repository='other-app', stage='review', catalog_pin='reviewer-pin')
        resolved = self.resolve(request, manifest, self.d1_sources)
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='e-05.9-test')
        admitted = self.admit(resolved, manifest)
        self.assertIsNone(di.stage_inference(admitted, resolved=resolved))
        for field in ('secrets', 'secrets_encrypted'):
            body = dict(admitted.body, **{field: self.native_body(resolved)[field]})
            refusal = self.assertDenied('BODY_FIELD_UNKNOWN', self.send, self.tampered(admitted, body), resolved)
            self.assertEqual(refusal.context['field'], field)
        self.assertDenied('ADMISSION_MISMATCH', di.admit_secrets, admitted, resolved=resolved,
                          workspaces=self.workspaces, grant=NT.NativeToken(TOKEN))
        self.fail_live()
        result = self.run_native(cc.FakeAgentServer(), manifest=manifest, request=request)
        self.assertNotIn('native_token', result.to_json())
        self.assertEqual(self.provider.reads, [])

    def test_the_qualification_fixture_is_still_refused_for_the_native_d1_stage(self):
        qualification = copy.deepcopy(d1.QUALIFICATION['body'])
        for name in ('secrets', 'secrets_encrypted'):
            qualification.pop(name)
        manifest = self.approve_native(d1.as_bytes(qualification))
        self.assertDenied('STAGE_TEMPLATE_DISPOSABLE', self.admit, self.resolve_d1(manifest), manifest)


class SharedCheck(NativeFixture):
    """One check, shared with E-05.11's qualification admission, not a copy."""

    def test_the_dispatcher_calls_the_one_function(self):
        self.assertIs(di.secrets_check, sys.modules['aieh_dispatch_create_secrets'])
        for code, meaning in cs.NATIVE_MEANINGS.items():
            self.assertEqual(di.REFUSALS[code], meaning)
        _, resolved, admitted = self.reserved_native()
        with mock.patch.object(cs, 'check_native_secrets', wraps=cs.check_native_secrets) as spy:
            self.send(admitted, resolved)
        [call] = spy.call_args_list
        self.assertEqual((call.kwargs['refused'], call.kwargs['endpoint'], call.kwargs['held']),
                         (di.DispatchRefused, PROXY, NT.fingerprint(TOKEN)))
        # Whatever the one function refuses, the dispatcher refuses with it: it holds no copy of its own.
        self.transport = adm.CountingTransport()

        def refuse(body, *, refused, **kwargs):
            raise refused('NATIVE_SWITCH_NOT_DECLARED', 'the shared function refused')
        with mock.patch.object(cs, 'check_native_secrets', refuse):
            refusal = self.assertDenied('NATIVE_SWITCH_NOT_DECLARED', self.send, admitted, resolved)
        self.assertEqual(refusal.detail, 'the shared function refused')

    def test_a_qualification_admission_takes_the_same_function_and_codes(self):
        """E-05.11's qualification admission (not built here) calls create_secrets.check_native_secrets with its own
        refusal type, as S-03.3's calls check_secrets: the same codes and meanings, the same body accepted."""
        aq = di._inference_modules()[0]
        _, resolved, admitted = self.reserved_native()
        wire = di._wire_body(admitted.body, di.stage_inference(admitted, resolved=resolved), admitted.inference)
        self.assertEqual(cs.check_native_secrets(wire, endpoint=PROXY, refused=aq.QualificationRefused), TOKEN)
        broken = copy.deepcopy(wire)
        broken['secrets'][NAMES[2]]['value'] = '1'
        with self.assertRaises(Exception) as caught:
            cs.check_native_secrets(broken, endpoint=PROXY, refused=lambda code, detail: ValueError(code))
        self.assertEqual(str(caught.exception), 'NATIVE_SWITCH_NOT_DECLARED')

    def test_the_native_set_is_declared_once(self):
        """The four names, the spelling and the tunnel class live in the shared module only."""
        for path in sorted((HERE.parent).glob('*.py')):
            if path.name == 'create_secrets.py':
                continue
            with self.subTest(module=path.name):
                tree = ast.parse(path.read_text(encoding='utf-8'))
                constants = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
                             and isinstance(n.value, str)}
                self.assertFalse(constants & {SPELLING, 'CLAUDE_CODE_PROXY_RESOLVES_HOSTS',
                                              'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC', 'provider-tunnel'})
                defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
                self.assertNotIn('check_native_secrets', defined)


class ReadOrder(NativeFixture):
    def test_the_token_is_read_only_after_the_reservation_and_every_other_input(self):
        order, seen = [], {}
        names = ('admit', 'stage_inference', 'admit_secrets', 'create_workspace', 'send_create')
        real = {name: getattr(di, name) for name in names}

        def spying(name):
            def wrapper(*args, **kwargs):
                order.append(name)
                return real[name](*args, **kwargs)
            return wrapper

        class Provider(NS.ObservedProvider):
            def get(inner, name):
                order.append('read')
                seen['states'] = [a.state for a in self.store.attempts()]
                seen['workspace'] = os.path.lexists(self.category)
                return super().get(name)
        provider = Provider({NT.ENTRY: (NT.ENTRY_USER, TOKEN)})
        with mock.patch.multiple(di, **{name: spying(name) for name in names}):
            self.run_native(cc.FakeAgentServer(), provider)
        self.assertEqual(order, ['admit', 'stage_inference', 'read', 'admit_secrets', 'create_workspace',
                                 'send_create'])
        self.assertEqual(seen, {'states': ['reserved'], 'workspace': False})
        self.assertEqual(provider.reads, [NT.ENTRY])

    def test_an_unreadable_entry_is_a_refused_attempt(self):
        malformed = 'sk-ant-' + 'api03-' + TOKEN[len(NS.PREFIX):]
        cases = {
            'NATIVE_TOKEN_MISSING': NS.ObservedProvider({'AIEH model provider': ('anthropic', API_KEY)}),
            'NATIVE_TOKEN_NOT_SHAPED': NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, malformed)}),
            'NATIVE_TOKEN_UNAVAILABLE': NS.ObservedProvider(error=OSError('locked')),
        }
        for code, provider in cases.items():
            with self.subTest(code):
                server = cc.FakeAgentServer()
                with self.assertRaises(di.DispatchRefused) as caught:
                    self.run_native(server, provider)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual((provider.reads, server.calls), ([NT.ENTRY], []))
                failed = max(self.store.attempts(['failed']),
                             key=lambda r: self.store.attempt_identity(r.operation_key).identity.ordinal)
                self.assertEqual(self.detail(failed.operation_key, 'failed')['code'], code)
                self.assertNotIn(malformed, self.store.canonical_dump().decode('utf-8'))
        with self.assertRaises(di.DispatchRefused) as caught:   # no provider given
            di.dispatch(self.d1_request(), manifest=self.approve_native(), work_sources=self.d1_sources.get,
                        integration_store=self.store, workspaces=self.workspaces, transport=cc.FakeAgentServer(),
                        actor='e-05.9-test', read_profile=self.read_profile, read_artifact=self.read_artifact)
        self.assertEqual(caught.exception.code, 'NATIVE_TOKEN_UNAVAILABLE')


class NoOtherCredential(NativeFixture):
    """Negative control: other credential entries, the provider and OAuth environment names and a host Claude
    configuration are all present with sentinels; a full native dispatch reads only its one entry, no environment
    name of a credential and no file of the host Claude configuration, and no sentinel appears anywhere. Positive
    controls show each observation would see such a read."""

    SENTINEL = NS.token('E-05.9 sentinel: never read')
    NAMES = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_OAUTH_TOKEN',
             'CLAUDE_CONFIG_DIR', 'AIEH_MODEL_PROVIDER_KEY')

    def test_the_dispatcher_reads_its_one_entry_and_nothing_else(self):
        home = Path(tempfile.mkdtemp(prefix='aieh-e059-home-', dir=self.case))
        config = home / '.claude'
        config.mkdir()
        (config / '.credentials.json').write_text(json.dumps({'claudeAiOauth': {'accessToken': self.SENTINEL}}),
                                                  encoding='utf-8')
        (config / 'settings.json').write_text('{}', encoding='utf-8')
        provider = NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, TOKEN),
                                        'AIEH model provider': ('anthropic', self.SENTINEL),
                                        'AIEH Gitea bot builder': ('aieh-bot-builder', self.SENTINEL),
                                        'Claude Code-credentials': ('owner', self.SENTINEL)})
        opened, environ_reads, watching = [], [], [False]

        def audit(event, args):
            if watching[0] and event in ('open', 'os.listdir', 'os.scandir') and args and args[0] is not None:
                opened.append(os.fspath(args[0]) if isinstance(args[0], (str, bytes, os.PathLike)) else '')
        sys.addaudithook(audit)
        real_getitem, real_get = type(os.environ).__getitem__, type(os.environ).get

        def getitem(environ, name):
            environ_reads.append(name)
            return real_getitem(environ, name)

        def get(environ, name, default=None):
            environ_reads.append(name)
            return real_get(environ, name, default)
        server = cc.FakeAgentServer()
        sentinels = {name: self.SENTINEL for name in self.NAMES}
        with mock.patch.dict(os.environ, {'HOME': str(home), 'USERPROFILE': str(home), **sentinels}), \
                mock.patch.object(type(os.environ), '__getitem__', getitem), \
                mock.patch.object(type(os.environ), 'get', get):
            watching[0] = True
            try:
                result = self.run_native(server, provider)
                dispatched = (list(opened), list(environ_reads))
                # positive controls: each observation sees such a read
                (config / '.credentials.json').read_bytes()
                os.environ.get('CLAUDE_CODE_OAUTH_TOKEN')
            finally:
                watching[0] = False
        self.assertEqual(provider.reads, [NT.ENTRY])
        files, names = dispatched
        self.assertEqual([p for p in files if os.path.normcase(str(config)) in os.path.normcase(p)], [])
        self.assertEqual([p for p in files if '.claude' in p or '.credentials' in p], [])
        self.assertEqual(sorted(set(names) & set(self.NAMES)), [])
        self.assertTrue(any(os.path.normcase(str(config)) in os.path.normcase(p) for p in opened))
        self.assertIn('CLAUDE_CODE_OAUTH_TOKEN', environ_reads)
        texts = [json.dumps(server.calls), self.store.canonical_dump().decode('utf-8'), json.dumps(result.to_json())]
        for text in texts:
            self.assertNotIn(self.SENTINEL, text)
        [(_, _, body)] = server.creates
        self.assertEqual(body['secrets'][NAMES[0]]['value'], TOKEN)


class Custody(NativeFixture):
    """No record carries the token: only its fingerprint."""

    @contextlib.contextmanager
    def captured(self):
        with secrets_tests.SecretsFixture.captured(self) as box:
            yield box

    def test_records_reports_and_logs_carry_the_fingerprint_only(self):
        fingerprint = NT.fingerprint(TOKEN)
        server = cc.FakeAgentServer()
        with self.captured() as out:
            result = self.run_native(server)
        dump = self.store.canonical_dump().decode('utf-8')
        self.assertIn(fingerprint, dump)
        self.assertNoToken(dump, json.dumps(result.to_json()), out['text'])
        self.assertEqual([TOKEN in json.dumps(body) for _, _, body in server.calls], [False, True])
        # the admitted create as a record, and the held token
        _, resolved, admitted = self.reserved_native()
        record = admitted.to_json()
        self.assertEqual(record['body']['secrets'][NAMES[0]], {'kind': 'StaticSecret', 'value': di.NATIVE_SLOT})
        self.assertEqual(record['native_token']['tokenFingerprint'], fingerprint)
        self.assertNoToken(json.dumps(record), admitted.body_json, repr(admitted), str(admitted.inference))
        with self.assertRaises(TypeError):
            pickle.dumps(admitted.inference)

    def test_a_refused_or_unanswered_create_records_the_fingerprint_only(self):
        fingerprint = NT.fingerprint(TOKEN)
        cases = {
            'CREATE_REFUSED': cc.FakeAgentServer(create={'status': 409, 'body': {'detail': 'x'}}),
            'unknown': cc.FakeAgentServer(create={'status': 500, 'body': {}}),
            'unanswered': cc.FakeAgentServer(create_error=ConnectionError('lost')),
        }
        for name, server in cases.items():
            with self.subTest(name):
                with self.captured() as out, self.assertRaises(Exception) as caught:
                    self.run_native(server)
                texts = secrets_tests.SecretsFixture.texts_of(self, caught.exception)
                self.assertNoToken(self.store.canonical_dump().decode('utf-8'), out['text'], *texts)
                if name == 'CREATE_REFUSED':   # a refusal after the read carries the fingerprint in its context
                    self.assertEqual(caught.exception.context['native_token']['tokenFingerprint'], fingerprint)
                for held in self.store.attempts(['unknown']):   # reconciled, so that the next attempt may start
                    self.store.transition(held.operation_key, 'failed', actor='e-05.9-test', reason='reconciled')
        detail = [json.loads(e.detail_json) for a in self.store.attempts() for e in self.store.events(a.operation_key)
                  if e.to_state == 'unknown']
        self.assertEqual([d['nativeToken']['tokenFingerprint'] for d in detail], [fingerprint, fingerprint])
        self.assertIn(fingerprint, self.store.canonical_dump().decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
