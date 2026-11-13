"""Tests for the ACP qualification create and its admission (plan leaf S-03.3, slice 2), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -v

``acp_qualification.py`` holds the disposable create of the Claude Code qualification run, pinned by sha256 with
an extract of the pinned OpenHands registry, and admits exactly that create with its four values. Shown here:

* the positive control: the fixture filled with a synthetic conversation id, model and attempt token and the
  checked-in profile's guest inference endpoint; the pins hold and the extract's wheels are the lock's;
* a real dispatch stage refuses it: the dispatcher's own body check against the checked-in profile's template and
  admission policy, and its artifact reader, which reads only ``profiles/<id>/...``;
* the negative controls, one fact each, each with its code: agent profiles, tools, MCP, another ACP server or
  command (the empty command, the ``npx`` form, a path, a shell, arguments), another model, another secret name or
  kind (``LookupSecret``), encrypted secrets, provider-key-shaped values, a value that is not an attempt token, the
  token elsewhere, any other destination, the conversation id and every other fixture field;
* the pins: a drifted, malformed or self-inconsistent fixture or extract is refused.

Every value is synthetic. No guest, container, process launch, socket or network.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'unit'
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROFILE_ID = 'strong-windows-qemu-whpx'


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


aq = _load('acp_qualification', HERE.parent / 'acp_qualification.py')
di = _load('dispatch_inputs', HERE.parent / 'dispatch_inputs.py')

PROFILE = json.loads((REPO / 'profiles' / PROFILE_ID / 'profile.json').read_text(encoding='utf-8'))
CONVERSATION = '6f1c2b0e-3d4a-4f5b-8c6d-7e8f9a0b1c2d'
TOKEN = 'aieh-inf-' + 'Q' * 20 + '_' + 'r' * 22          # the broker's shape: aieh-inf- and 43 URL-safe characters
OTHER_TOKEN = 'aieh-inf-' + 'z' * 43
MODEL = 'synthetic-model-1'
APPROVED = [MODEL, 'synthetic-model-2']
ENDPOINT = 'http://172.17.0.1:8090'
PROVIDER_KEY = 'sk-ant-api03-' + 'x' * 40 + '-synthetic'


def build(**overrides):
    values = dict(conversation_id=CONVERSATION, attempt_token=TOKEN, acp_model=MODEL, approved_models=APPROVED,
                  profile=PROFILE)
    values.update(overrides)
    return aq.build_create(**values)


def check(body, **overrides):
    values = dict(conversation_id=CONVERSATION, approved_models=APPROVED, profile=PROFILE)
    values.update(overrides)
    aq.check_create(body, **values)


class Base(unittest.TestCase):
    def refused(self, code, body, **overrides):
        with self.assertRaises(aq.QualificationRefused) as caught:
            check(body, **overrides)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        return caught.exception

    def altered(self, change):
        body = build()
        change(body)
        return body


class PositiveControl(Base):
    def test_the_filled_fixture_is_admitted(self):
        body = build()
        self.assertEqual(body, {
            'conversation_id': CONVERSATION, 'conversation_runtime': 'docker',
            'workspace': {'kind': 'LocalWorkspace', 'working_dir': '/workspace'},
            'agent_settings': {'agent_kind': 'acp', 'acp_server': 'claude-code', 'acp_command': ['claude-agent-acp'],
                               'acp_args': [], 'acp_model': MODEL, 'acp_session_mode': None,
                               'acp_isolate_data_dir': True, 'mcp_config': {}},
            'secrets': {'ANTHROPIC_API_KEY': {'kind': 'StaticSecret', 'value': TOKEN},
                        'ANTHROPIC_BASE_URL': {'kind': 'StaticSecret', 'value': ENDPOINT}},
            'secrets_encrypted': False, 'autotitle': False, 'container': {'browser': False},
            'tags': {'aieh': 's-03.3-disposable'}})
        check(body)
        check(json.loads(json.dumps(body)))
        check(build(acp_model='synthetic-model-2'))

    def test_the_endpoint_is_the_profile_s_guest_inference_endpoint(self):
        self.assertEqual(aq.inference_endpoint(PROFILE), ENDPOINT)

    def test_a_token_holding_a_key_like_run_is_still_a_token(self):
        token = 'aieh-inf-sk-' + 'a' * 40
        self.assertTrue(aq.broker.TOKEN_SHAPE.fullmatch(token))
        check(build(attempt_token=token))

    def test_the_pins_hold_and_the_extract_is_of_the_locked_wheels(self):
        for path, pin in ((aq.FIXTURE_PATH, aq.FIXTURE_SHA256), (aq.REGISTRY_PATH, aq.REGISTRY_SHA256)):
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256((REPO / path).read_bytes()).hexdigest(), pin)
        lock = json.loads((REPO / 'composition' / 'lock' / 'components.lock.json').read_text(encoding='utf-8'))
        locked = {}

        def walk(node):
            if isinstance(node, dict):
                if isinstance(node.get('wheel'), str) and isinstance(node.get('sha256'), str):
                    locked[node['wheel']] = node['sha256']
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(lock)
        extract = json.loads((REPO / aq.REGISTRY_PATH).read_text(encoding='utf-8'))
        self.assertEqual(len(extract['wheels']), 2)
        for wheel, digest in extract['wheels'].items():
            with self.subTest(wheel=wheel):
                self.assertEqual(locked.get(wheel), digest)
        facts = extract['facts']
        self.assertEqual((facts['api_key_env_var']['value'], facts['base_url_env_var']['value'],
                          facts['binary_name']['value']), ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'claude-agent-acp'))
        for name in ('blank_secret_is_none', 'registry_exports_non_empty_only', 'acp_subprocess_environment',
                     'env_conflicts', 'sanitized_env_strips', 'container_environment'):   # finding F-3's sources
            with self.subTest(fact=name):
                self.assertIn('.py:', facts[name]['source'])

    def test_nothing_is_launched_or_connected(self):
        tree = ast.parse((HERE.parent / 'acp_qualification.py').read_text(encoding='utf-8'))
        imported = {alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        imported |= {node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imported, {'__future__', 'hashlib', 'importlib', 'ipaddress', 'json', 're', 'sys',
                                    'pathlib', 'typing'})


class RealStageRefusal(Base):
    """The dispatcher's admission of a real stage never admits the qualification create."""

    @classmethod
    def setUpClass(cls):
        cls.admission = di.admission_policy(PROFILE, PROFILE_ID)
        cls.template = json.loads(di.read_profile_artifact(cls.admission['create_template']['path']))

    def stage_check(self, body):
        with self.assertRaises(di.DispatchRefused) as caught:
            di.check_create_body(body, admission=self.admission, template=self.template,
                                 conversation_id=CONVERSATION)
        return caught.exception

    def test_the_stage_body_check_refuses_it(self):
        body = build()
        refusal = self.stage_check(body)
        self.assertEqual((refusal.code, refusal.context), ('BODY_FIELD_UNKNOWN', {'field': 'secrets'}))
        del body['secrets'], body['secrets_encrypted']
        refusal = self.stage_check(body)
        self.assertEqual((refusal.code, refusal.context), ('BODY_NOT_TEMPLATE', {'field': 'agent_settings'}))
        # Negative control: the profile's own template with the conversation id passes the same check.
        di.check_create_body(dict(self.template, conversation_id=CONVERSATION), admission=self.admission,
                             template=self.template, conversation_id=CONVERSATION)

    def test_the_stage_artifact_reader_cannot_read_it(self):
        for path in (aq.FIXTURE_PATH, aq.REGISTRY_PATH):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    di.read_profile_artifact(path)
                with self.assertRaises(di.DispatchRefused) as caught:
                    di._read_pinned(di.read_profile_artifact, {'path': path, 'sha256': aq.FIXTURE_SHA256},
                                    'create template')
                self.assertEqual(caught.exception.code, 'PROFILE_ARTIFACT_MISSING')

    def test_the_qualification_check_refuses_the_stage_template(self):
        self.refused('TOOLS_FORBIDDEN', dict(self.template, conversation_id=CONVERSATION))
        settings = {k: v for k, v in self.template['agent_settings'].items() if k != 'tools'}
        self.refused('ACP_SERVER_NOT_PINNED', dict(self.template, conversation_id=CONVERSATION,
                                                   agent_settings=settings))


class FieldRefusals(Base):
    def test_fields_outside_the_fixture(self):
        for field, code in (('agent_profile_id', 'AGENT_PROFILE_FORBIDDEN'), ('llm_profile_ref', 'AGENT_PROFILE_FORBIDDEN'),
                            ('client_tools', 'TOOLS_FORBIDDEN'), ('tool_module_qualnames', 'TOOLS_FORBIDDEN'),
                            ('agent_definitions', 'TOOLS_FORBIDDEN'), ('plugins', 'TOOLS_FORBIDDEN'),
                            ('hook_config', 'TOOLS_FORBIDDEN'), ('agent_launch_additions', 'TOOLS_FORBIDDEN'),
                            ('mcp_servers', 'MCP_FORBIDDEN'), ('initial_message', 'BODY_FIELD_UNKNOWN'),
                            ('parent_conversation_id', 'BODY_FIELD_UNKNOWN'), ('worktree', 'BODY_FIELD_UNKNOWN'),
                            ('confirmation_policy', 'BODY_FIELD_UNKNOWN')):
            with self.subTest(field=field):
                self.refused(code, self.altered(lambda body: body.__setitem__(field, 'x')))

    def test_agent_settings_fields_outside_the_fixture(self):
        for field, code in (('tools', 'TOOLS_FORBIDDEN'), ('agent_context', 'TOOLS_FORBIDDEN'),
                            ('skills', 'TOOLS_FORBIDDEN'), ('agent_profile_id', 'AGENT_PROFILE_FORBIDDEN'),
                            ('acp_file_secrets', 'BODY_FIELD_UNKNOWN'), ('acp_env', 'BODY_FIELD_UNKNOWN'),
                            ('llm', 'BODY_FIELD_UNKNOWN'), ('verification', 'BODY_FIELD_UNKNOWN'),
                            ('acp_resume_session_id', 'BODY_FIELD_UNKNOWN')):
            with self.subTest(field=field):
                self.refused(code, self.altered(lambda body: body['agent_settings'].__setitem__(field, [])))

    def test_malformed_bodies(self):
        for body in (None, [], 'body', 1):
            with self.subTest(body=body):
                self.refused('BODY_MALFORMED', body)
        for settings in (None, [], 'acp'):
            with self.subTest(settings=settings):
                self.refused('BODY_MALFORMED', self.altered(lambda body: body.__setitem__('agent_settings', settings)))
        self.refused('BODY_MALFORMED', self.altered(lambda body: body.pop('agent_settings')))

    def test_the_acp_server(self):
        for field, value in (('agent_kind', 'openhands'), ('agent_kind', 'llm'), ('acp_server', 'custom'),
                             ('acp_server', 'codex'), ('acp_server', None)):
            with self.subTest(field=field, value=value):
                self.refused('ACP_SERVER_NOT_PINNED',
                             self.altered(lambda body: body['agent_settings'].__setitem__(field, value)))
        self.refused('ACP_SERVER_NOT_PINNED', self.altered(lambda body: body['agent_settings'].pop('agent_kind')))

    def test_the_command(self):
        refusal = self.refused('ACP_COMMAND_NOT_PINNED',
                               self.altered(lambda body: body['agent_settings'].__setitem__('acp_command', [])))
        self.assertIn('npx', refusal.detail)
        refusal = self.refused('ACP_COMMAND_NOT_PINNED',
                               self.altered(lambda body: body['agent_settings'].pop('acp_command')))
        self.assertIn('npx', refusal.detail)
        for command in (['npx', '-y', '--prefer-offline', '@agentclientprotocol/claude-agent-acp@0.63.0'],
                        ['/usr/local/bin/claude-agent-acp'], ['/acp-node/bin/claude-agent-acp'],
                        ['claude-agent-acp', '--debug'], ['sh', '-c', 'claude-agent-acp'],
                        ['env', '-u', 'OH_SECRET_KEY', 'claude-agent-acp'], ['codex-acp'], 'claude-agent-acp'):
            with self.subTest(command=command):
                refusal = self.refused('ACP_COMMAND_NOT_PINNED', self.altered(
                    lambda body: body['agent_settings'].__setitem__('acp_command', command)))
                self.assertNotIn('npx form', refusal.detail)
        for args in (['--debug'], [''], 'x'):
            with self.subTest(args=args):
                self.refused('ACP_COMMAND_NOT_PINNED',
                             self.altered(lambda body: body['agent_settings'].__setitem__('acp_args', args)))

    def test_mcp(self):
        for config in ({'fs': {'command': 'npx', 'args': ['x']}}, {'remote': {'url': 'http://example.test/mcp'}},
                       None, []):
            with self.subTest(config=config):
                self.refused('MCP_FORBIDDEN',
                             self.altered(lambda body: body['agent_settings'].__setitem__('mcp_config', config)))

    def test_the_model(self):
        for model in ('synthetic-model-3', None, 7, '', 'SYNTHETIC-MODEL-1'):
            with self.subTest(model=model):
                self.refused('MODEL_NOT_APPROVED',
                             self.altered(lambda body: body['agent_settings'].__setitem__('acp_model', model)))
        for approved in ([], None, (), 'synthetic-model-1', [MODEL, MODEL], [MODEL, 'synthetic-*'], [MODEL, 'a?'],
                         [MODEL, None], [MODEL, ' bad'], {MODEL: 1}):
            with self.subTest(approved=approved):
                self.refused('MODEL_NOT_APPROVED', build(approved_models=[MODEL]), approved_models=approved)
        check(build(approved_models=(MODEL,)), approved_models=(MODEL,))
        with self.assertRaises(aq.QualificationRefused) as caught:
            build(acp_model='synthetic-model-3')
        self.assertEqual(caught.exception.code, 'MODEL_NOT_APPROVED')


class SecretRefusals(Base):
    def test_the_secret_names(self):
        changes = (lambda s: s.pop('ANTHROPIC_BASE_URL'), lambda s: s.pop('ANTHROPIC_API_KEY'),
                   lambda s: s.__setitem__('OPENAI_API_KEY', {'kind': 'StaticSecret', 'value': 'x'}),
                   lambda s: s.__setitem__('OH_SECRET_KEY', {'kind': 'StaticSecret', 'value': 'placeholder'}),
                   lambda s: s.__setitem__('OH_SESSION_API_KEYS_0', {'kind': 'StaticSecret', 'value': 'x'}),
                   lambda s: s.__setitem__('CLAUDE_CODE_OAUTH_TOKEN', {'kind': 'StaticSecret', 'value': 'x'}),
                   lambda s: s.__setitem__('anthropic_api_key', s.pop('ANTHROPIC_API_KEY')))
        for index, change in enumerate(changes):
            with self.subTest(change=index):
                self.refused('SECRET_NAMES', self.altered(lambda body: change(body['secrets'])))
        for secrets in (None, [], 'ANTHROPIC_API_KEY', {}):
            with self.subTest(secrets=secrets):
                self.refused('SECRET_NAMES', self.altered(lambda body: body.__setitem__('secrets', secrets)))
        self.refused('SECRET_NAMES', self.altered(lambda body: body.pop('secrets')))

    def test_only_a_static_secret(self):
        lookup = {'kind': 'LookupSecret', 'url': 'http://172.17.0.1:8090/token', 'headers': {}}
        for name in ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL'):
            for source in (lookup, {'kind': 'LookupSecret', 'value': ENDPOINT},
                           {'kind': 'StaticSecret', 'value': TOKEN, 'description': 'd'},
                           {'kind': 'StaticSecret'}, {'value': TOKEN}, {'kind': 'StaticSecret', 'value': None},
                           {'kind': 'StaticSecret', 'value': ['x']}, TOKEN, None):
                with self.subTest(name=name, source=source):
                    refusal = self.refused('SECRET_KIND_FORBIDDEN', self.altered(
                        lambda body: body['secrets'].__setitem__(name, copy.deepcopy(source))))
                    self.assertIn(name, refusal.detail)

    def test_secrets_are_sent_in_the_clear_to_the_admission(self):
        for value in (True, None, 0, 'false'):
            with self.subTest(value=value):
                self.refused('SECRETS_ENCRYPTED',
                             self.altered(lambda body: body.__setitem__('secrets_encrypted', value)))
        self.refused('SECRETS_ENCRYPTED', self.altered(lambda body: body.pop('secrets_encrypted')))

    def test_provider_key_shaped_values(self):
        for key in (PROVIDER_KEY, 'sk-proj-' + 'y' * 30, 'sk-' + 'Z' * 24):
            for where in ('token', 'tag', 'tag-key', 'endpoint'):
                def change(body):
                    if where == 'token':
                        body['secrets']['ANTHROPIC_API_KEY']['value'] = key
                    elif where == 'tag':
                        body['tags']['aieh'] = f'x {key}'
                    elif where == 'tag-key':
                        body['tags'][key] = 'x'
                    else:
                        body['secrets']['ANTHROPIC_BASE_URL']['value'] = f'{ENDPOINT}/{key}'
                with self.subTest(key=key[:8], where=where):
                    self.refused('SECRET_PROVIDER_KEY_SHAPED', self.altered(change))

    def test_values_inside_lists_are_scanned_and_located(self):
        for value, code, detail in ((['x', PROVIDER_KEY], 'SECRET_PROVIDER_KEY_SHAPED', 'at tags.aieh.1'),
                                    ([TOKEN], 'TOKEN_OUTSIDE_SECRET', 'at tags.aieh.0'),
                                    ([[ENDPOINT]], 'DESTINATION_NOT_ENDPOINT', 'a destination at tags.aieh.0.0')):
            with self.subTest(code=code):
                refusal = self.refused(code, self.altered(lambda body: body['tags'].__setitem__('aieh', value)))
                self.assertEqual(refusal.detail, detail)
        refusal = self.refused('TOKEN_OUTSIDE_SECRET', self.altered(lambda body: body['tags'].__setitem__(TOKEN, 'x')))
        self.assertEqual(refusal.detail, 'at tags.<redacted>.#key')   # E-05.6: a detail never repeats the token

    def test_a_part_of_the_token_outside_the_api_key(self):
        """E-05.6 (the shared check): any run of 8 or more characters of the token's body is refused outside its
        secret, at the start, the middle or the end of the body; 7 characters are not (the boundary is
        deliberate: 8 characters carry 48 bits)."""
        body = TOKEN[len('aieh-inf-'):]
        self.assertEqual(aq.secrets_check.FRAGMENT, 8)
        for name, part in (('start', body[:8]), ('middle', body[16:24]), ('end', body[-8:]), ('longer', body[3:20])):
            for where in ('tag', 'tag-key'):
                with self.subTest(part=name, where=where):
                    change = (lambda b: b['tags'].__setitem__('aieh', 'x' + part + 'y')) if where == 'tag' else \
                        (lambda b: b['tags'].__setitem__('x' + part, 'x'))
                    refusal = self.refused('TOKEN_OUTSIDE_SECRET', self.altered(change))
                    self.assertNotIn(part, refusal.detail)
        for name, part in (('start', body[:7]), ('middle', body[16:23]), ('end', body[-7:])):
            with self.subTest(seven=name):
                altered = self.altered(lambda b: b['tags'].__setitem__('aieh', 'x' + part + 'y'))
                self.assertEqual(aq.secrets_check.check_secrets(
                    altered, names=['ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL'], endpoint=ENDPOINT,
                    refused=aq.QualificationRefused), TOKEN)
                self.refused('BODY_NOT_FIXTURE', altered)   # refused only as not the fixture, not as a secret

    def test_no_refusal_detail_repeats_a_secret(self):
        """E-05.6: the shared check's details redact every word that holds the token, a part of it of 8 or more
        characters, or a provider key's shape."""
        for key, code in ((TOKEN, 'TOKEN_OUTSIDE_SECRET'), ('x' + TOKEN[9:17], 'TOKEN_OUTSIDE_SECRET'),
                          (OTHER_TOKEN, 'TOKEN_OUTSIDE_SECRET'), (PROVIDER_KEY, 'SECRET_PROVIDER_KEY_SHAPED')):
            with self.subTest(code=code, key=key[:12]):
                refusal = self.refused(code, self.altered(lambda body: body['tags'].__setitem__(key, 'x')))
                self.assertEqual(refusal.detail, 'at tags.<redacted>.#key')

    def test_the_api_key_is_one_attempt_token(self):
        for value in ('', ' ', TOKEN[:-1], TOKEN + 'a', ' ' + TOKEN, TOKEN.replace('aieh-inf-', 'aieh-inf_'),
                      'aieh-inf-' + 'a' * 42 + '=', 'Bearer ' + TOKEN, 'placeholder'):
            with self.subTest(value=value):
                self.refused('SECRET_NOT_ATTEMPT_TOKEN', self.altered(
                    lambda body: body['secrets']['ANTHROPIC_API_KEY'].__setitem__('value', value)))
        with self.assertRaises(aq.QualificationRefused) as caught:
            build(attempt_token=PROVIDER_KEY)
        self.assertEqual(caught.exception.code, 'SECRET_PROVIDER_KEY_SHAPED')

    def test_no_token_outside_the_api_key(self):
        for change in (lambda body: body['tags'].__setitem__('aieh', TOKEN),
                       lambda body: body['tags'].__setitem__(TOKEN, 'x'),
                       lambda body: body['tags'].__setitem__('aieh', 'prefix' + TOKEN[9:]),
                       lambda body: body['tags'].__setitem__('aieh', OTHER_TOKEN),
                       lambda body: body['secrets']['ANTHROPIC_BASE_URL'].__setitem__('value', ENDPOINT + '/' + TOKEN)):
            with self.subTest(change=change):
                self.refused('TOKEN_OUTSIDE_SECRET', self.altered(change))


class DestinationRefusals(Base):
    def test_the_base_url_is_the_guest_endpoint_only(self):
        for url in ('https://api.anthropic.com', ENDPOINT + '/', ENDPOINT + '/v1', 'http://127.0.0.1:8090',
                    'http://172.17.0.1:8091', 'https://172.17.0.1:8090', 'http://172.17.0.1', '172.17.0.1:8090',
                    'HTTP://172.17.0.1:8090', 'http://host.docker.internal:8090', ''):
            with self.subTest(url=url):
                self.refused('DESTINATION_NOT_ENDPOINT', self.altered(
                    lambda body: body['secrets']['ANTHROPIC_BASE_URL'].__setitem__('value', url)))

    def test_no_other_destination_anywhere(self):
        for text in ('https://api.anthropic.com', ENDPOINT, '//evil.example.test', 'ws://x'):
            for where in ('tag', 'tag-key', 'workspace'):
                def change(body):
                    if where == 'tag':
                        body['tags']['aieh'] = text
                    elif where == 'tag-key':
                        body['tags'][text] = 'x'
                    else:
                        body['workspace']['working_dir'] = text
                with self.subTest(text=text, where=where):
                    self.refused('DESTINATION_NOT_ENDPOINT', self.altered(change))

    def test_the_endpoint_declaration(self):
        def profile_with(*entries):
            return {'network': {'endpoints': list(entries)}}
        good = {'class': 'inference', 'guest_address': '172.17.0.1', 'guest_port': 8090}
        self.assertEqual(aq.inference_endpoint(profile_with({'class': 'management'}, good)), ENDPOINT)
        for profile in (None, {}, {'network': None}, {'network': {}}, profile_with(), profile_with(good, good),
                        profile_with(dict(good, guest_address='localhost')),
                        profile_with(dict(good, guest_address='172.017.0.1')),
                        profile_with(dict(good, guest_address='::1')),
                        profile_with(dict(good, guest_address=None)),
                        profile_with(dict(good, guest_port='8090')), profile_with(dict(good, guest_port=True)),
                        profile_with(dict(good, guest_port=0)), profile_with(dict(good, guest_port=65536)),
                        profile_with(dict(good, guest_port=None)), profile_with('inference'), [], ['network'],
                        'network'):
            with self.subTest(profile=profile):
                with self.assertRaises(aq.QualificationRefused) as caught:
                    aq.inference_endpoint(profile)
                self.assertEqual(caught.exception.code, 'ENDPOINT_UNDECLARED')
        self.assertEqual(aq.inference_endpoint(profile_with(dict(good, guest_port=1))), 'http://172.17.0.1:1')
        self.assertEqual(aq.inference_endpoint(profile_with(dict(good, guest_port=65535))), 'http://172.17.0.1:65535')
        other = profile_with(dict(good, guest_port=9000))
        self.refused('DESTINATION_NOT_ENDPOINT', build(), profile=other)
        check(build(profile=other), profile=other)


class FixtureRefusals(Base):
    def test_the_conversation_id(self):
        self.refused('CONVERSATION_ID_MISMATCH', build(), conversation_id='0f1c2b0e-3d4a-4f5b-8c6d-7e8f9a0b1c2d')
        for value in (CONVERSATION.upper(), CONVERSATION.replace('-', ''), None, 1, ''):
            with self.subTest(value=value):
                self.refused('CONVERSATION_ID_MISMATCH', build(), conversation_id=value)
                self.refused('CONVERSATION_ID_MISMATCH',
                             self.altered(lambda body: body.__setitem__('conversation_id', value)))
        self.refused('CONVERSATION_ID_MISMATCH', self.altered(lambda body: body.pop('conversation_id')))
        for value in (CONVERSATION.upper(), CONVERSATION.replace('-', ''), 'not-a-uuid'):
            with self.subTest(both=value):
                self.refused('CONVERSATION_ID_MISMATCH',
                             self.altered(lambda body: body.__setitem__('conversation_id', value)),
                             conversation_id=value)

    def test_every_other_field_is_the_fixture_s(self):
        changes = {
            'conversation_runtime': lambda body: body.__setitem__('conversation_runtime', 'local'),
            'workspace': lambda body: body['workspace'].__setitem__('working_dir', '/home'),
            'autotitle': lambda body: body.__setitem__('autotitle', True),
            'container': lambda body: body['container'].__setitem__('browser', True),
            'tags': lambda body: body['tags'].__setitem__('aieh', 'f-04.2-disposable'),
            'agent_settings': lambda body: body['agent_settings'].__setitem__('acp_isolate_data_dir', False),
        }
        for key, change in changes.items():
            with self.subTest(key=key):
                refusal = self.refused('BODY_NOT_FIXTURE', self.altered(change))
                self.assertIn(key, refusal.detail)
        for change in (lambda body: body['container'].__setitem__('memory', '8g'),
                       lambda body: body['agent_settings'].__setitem__('acp_session_mode', 'default'),
                       lambda body: body['agent_settings'].pop('acp_args'),
                       lambda body: body['agent_settings'].pop('mcp_config'),
                       lambda body: body['agent_settings'].__setitem__('acp_isolate_data_dir', 1),
                       lambda body: body.__setitem__('autotitle', 0),
                       lambda body: body.pop('autotitle'), lambda body: body.pop('tags'),
                       lambda body: body.pop('workspace'), lambda body: body.__setitem__('container', {1, 2})):
            with self.subTest(change=change):
                self.refused('BODY_NOT_FIXTURE', self.altered(change))


class PinRefusals(Base):
    def reader(self, replacements):
        def read(path):
            return replacements[path] if path in replacements else aq.read_repository_file(path)
        return read

    def edited(self, path, edit):
        data = json.loads((REPO / path).read_text(encoding='utf-8'))
        edit(data)
        return json.dumps(data).encode('utf-8')

    def assert_refused(self, code, read, body):
        for call in (lambda: aq.load_fixture(read), lambda: aq.build_create(
                conversation_id=CONVERSATION, attempt_token=TOKEN, acp_model=MODEL, approved_models=APPROVED,
                profile=PROFILE, read=read), lambda: check(body, read=read)):
            with self.assertRaises(aq.QualificationRefused) as caught:
                call()
            self.assertEqual(caught.exception.code, code, caught.exception.detail)

    def test_drift(self):
        for path in (aq.FIXTURE_PATH, aq.REGISTRY_PATH):
            raw = (REPO / path).read_bytes()
            for altered in (raw + b'\n', raw.replace(b'\n', b'\r\n'), raw[:-2], b''):
                with self.subTest(path=path, size=len(altered)):
                    self.assert_refused('FIXTURE_DRIFTED', self.reader({path: altered}), build())

    def repinned(self, path, raw):
        attribute = 'FIXTURE_SHA256' if path == aq.FIXTURE_PATH else 'REGISTRY_SHA256'
        return mock.patch.object(aq, attribute, hashlib.sha256(raw).hexdigest())

    def test_a_repinned_but_invalid_file(self):
        def body(edit):
            return lambda data: edit(data['body'])
        cases = {
            aq.FIXTURE_PATH: [b'{', b'[]', b'{"a": 1, "a": 2}', b'\xff',
                              self.edited(aq.FIXTURE_PATH, lambda d: d.__setitem__('format', 'other/v1')),
                              self.edited(aq.FIXTURE_PATH, lambda d: d['placeholders'].pop()),
                              self.edited(aq.FIXTURE_PATH, lambda d: d.__setitem__('body', [])),
                              self.edited(aq.FIXTURE_PATH, body(lambda b: b['tags'].__setitem__('x', '{acp_model}'))),
                              self.edited(aq.FIXTURE_PATH, body(lambda b: b['agent_settings'].__setitem__(
                                  'acp_model', 'fixed'))),
                              self.edited(aq.FIXTURE_PATH, body(lambda b: b['agent_settings'].__setitem__(
                                  'acp_command', ['claude-agent-acp', '--x']))),
                              self.edited(aq.FIXTURE_PATH, body(lambda b: b['agent_settings'].__setitem__(
                                  'acp_server', 'custom'))),
                              self.edited(aq.FIXTURE_PATH, body(lambda b: b.__setitem__('secrets', {
                                  'ANTHROPIC_BASE_URL': b['secrets']['ANTHROPIC_BASE_URL'],
                                  'ANTHROPIC_API_KEY': b['secrets']['ANTHROPIC_API_KEY']}))),
                              self.edited(aq.FIXTURE_PATH, body(lambda b: b.__setitem__('secrets', {
                                  'ANTHROPIC_API_KEY': b['secrets']['ANTHROPIC_BASE_URL'],
                                  'ANTHROPIC_BASE_URL': b['secrets']['ANTHROPIC_API_KEY']}))),
                              self.edited(aq.FIXTURE_PATH, body(lambda b: (
                                  b['secrets']['ANTHROPIC_API_KEY'].__setitem__('value', 'fixed'),
                                  b['tags'].__setitem__('t', '{attempt_token}')))),
                              self.edited(aq.FIXTURE_PATH, body(lambda b: (
                                  b['secrets']['ANTHROPIC_BASE_URL'].__setitem__('value', 'fixed'),
                                  b['tags'].__setitem__('t', '{inference_endpoint}')))),
                              self.edited(aq.FIXTURE_PATH, body(lambda b: (
                                  b.pop('agent_settings'), b['tags'].__setitem__('t', '{acp_model}')))),
                              self.edited(aq.FIXTURE_PATH, body(lambda b: (
                                  b.pop('secrets'), b['tags'].__setitem__('t', '{attempt_token}'),
                                  b['tags'].__setitem__('u', '{inference_endpoint}')))),
                              (REPO / aq.FIXTURE_PATH).read_bytes().replace(
                                  b'"format":', b'"format": "other/v1",\n  "format":', 1)],
            aq.REGISTRY_PATH: [b'[]', self.edited(aq.REGISTRY_PATH, lambda d: d.__setitem__('format', 'x')),
                               self.edited(aq.REGISTRY_PATH, lambda d: d.__setitem__('acp_server', 'codex')),
                               self.edited(aq.REGISTRY_PATH, lambda d: d.__setitem__('facts', [])),
                               self.edited(aq.REGISTRY_PATH, lambda d: d['facts']['api_key_env_var'].__setitem__(
                                   'value', 'OPENAI_API_KEY')),
                               self.edited(aq.REGISTRY_PATH, lambda d: d['facts']['base_url_env_var'].__setitem__(
                                   'value', 'OPENAI_BASE_URL')),
                               self.edited(aq.REGISTRY_PATH, lambda d: d['facts'].pop('binary_name')),
                               self.edited(aq.REGISTRY_PATH, lambda d: d['facts'].pop('api_key_env_var')),
                               (REPO / aq.REGISTRY_PATH).read_bytes().replace(
                                   b'"format":', b'"format": "other/v1",\n  "format":', 1),
                               self.edited(aq.REGISTRY_PATH, lambda d: d['facts']['binary_name'].__setitem__(
                                   'value', 'codex-acp'))],
        }
        good = build()
        for path, variants in cases.items():
            for index, raw in enumerate(variants):
                with self.subTest(path=path, variant=index), self.repinned(path, raw):
                    self.assert_refused('FIXTURE_INVALID', self.reader({path: raw}), good)

    def test_a_repinned_equivalent_file_is_admitted(self):
        raw = json.dumps(json.loads((REPO / aq.FIXTURE_PATH).read_text(encoding='utf-8'))).encode('utf-8')
        read = self.reader({aq.FIXTURE_PATH: raw})
        with self.repinned(aq.FIXTURE_PATH, raw):
            check(aq.build_create(conversation_id=CONVERSATION, attempt_token=TOKEN, acp_model=MODEL,
                                  approved_models=APPROVED, profile=PROFILE, read=read), read=read)


class Refusals(unittest.TestCase):
    def test_codes_and_shape(self):
        with self.assertRaises(ValueError):
            aq.QualificationRefused('NOT_A_CODE', 'x')
        refusal = aq.QualificationRefused('MCP_FORBIDDEN', 'detail')
        self.assertEqual(refusal.to_json(), {'format': 'ai-engineering-harness/dispatch/acp-qualification-refusal/v1',
                                             'code': 'MCP_FORBIDDEN',
                                             'meaning': aq.REFUSALS['MCP_FORBIDDEN'], 'detail': 'detail'})
        self.assertEqual(str(refusal), 'MCP_FORBIDDEN: detail')


if __name__ == '__main__':
    unittest.main()
