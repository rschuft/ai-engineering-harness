"""Tests for the native qualification create and its admission (plan leaf E-05.11; decision 0023), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -v

``native_qualification.py`` holds the disposable create of the native Claude Code qualification run, pinned by
sha256, and admits exactly that create with its three values. Shown here:

* the positive control: the fixture filled with the reserved conversation id, a synthetic native token and the
  checked-in profile's tunnel endpoint; its model is the engineering manager's model record's primary;
* a real dispatch stage refuses it: the D1 stage's template check (tagged disposable), the dispatcher's own body
  check against the checked-in profile's template (also with the native secrets admitted), its artifact reader;
* the secrets and agent blocks are checked by the one function shared with the dispatcher's D1 stage
  (``create_secrets.check_native_secrets``), with this module's refusal type and the same codes;
* every refusal of its own, one fact each (the nested ``workspace``, ``container`` and ``tags`` closed, carried NIT-a),
  and a refusal's detail never repeats the token;
* the pin: a drifted or malformed fixture is refused.

Every value is synthetic (native_support builds the token at run time). No guest, container, socket or network.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
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


nq = _load('native_qualification', HERE.parent / 'native_qualification.py')
di = _load('dispatch_inputs', HERE.parent / 'dispatch_inputs.py')
NS = _load('native_support', HERE / 'native_support.py')
cs = nq.secrets_check
NT = cs.native()

PROFILE = json.loads((REPO / 'profiles' / PROFILE_ID / 'profile.json').read_text(encoding='utf-8'))
CONVERSATION = 'a0333c00-0000-4000-8000-0000000e0511'
TOKEN = NS.token('E-05.11 synthetic native token')
OTHER = NS.token('another E-05.11 token')
PROXY = 'http://172.17.0.1:8090'


def build(**overrides):
    values = dict(conversation_id=CONVERSATION, native_token=TOKEN, profile=PROFILE)
    values.update(overrides)
    return nq.build_create(**values)


class Base(unittest.TestCase):
    def refused(self, code, body, **overrides):
        values = dict(conversation_id=CONVERSATION, profile=PROFILE)
        values.update(overrides)
        with self.assertRaises(nq.QualificationRefused) as caught:
            nq.check_create(body, **values)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        for needle in (TOKEN, NT.secret_body(TOKEN)):
            self.assertNotIn(needle, json.dumps(caught.exception.to_json()))
        return caught.exception

    def altered(self, change):
        body = build()
        change(body)
        return body


class PositiveControl(Base):
    def test_the_filled_fixture_is_admitted(self):
        body = build(held=NT.fingerprint(TOKEN))
        self.assertEqual(nq.check_create(body, conversation_id=CONVERSATION, profile=PROFILE), TOKEN)
        self.assertEqual(body['secrets']['CLAUDE_CODE_OAUTH_TOKEN'], {'kind': 'StaticSecret', 'value': TOKEN})
        self.assertEqual(body['secrets']['HTTPS_PROXY']['value'], PROXY)
        self.assertEqual(sorted(body['secrets']), sorted(cs.NATIVE_NAMES))
        self.assertEqual(body['agent_settings']['acp_model'], 'claude-sonnet-5')
        self.assertEqual(body['conversation_id'], CONVERSATION)

    def test_the_model_is_the_model_records_primary(self):
        record = (REPO / 'evidence' / 'D1-native-model-record.md').read_text(encoding='utf-8')
        self.assertEqual(re.search(r'\*\*Primary\*\* `([^`]+)`', record).group(1), nq.MODEL)

    def test_the_pin_holds(self):
        raw = (REPO / nq.FIXTURE_PATH).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), nq.FIXTURE_SHA256)
        self.assertNotIn(b'\r\n', raw)

    def test_the_run_shape_is_d1s_but_the_tag_and_the_model(self):
        """'as D1 runs it': the agent block and the top-level fields are the D1 template's (E-05.2's pin)."""
        d1 = json.loads((REPO / 'profiles' / PROFILE_ID / 'agent-server' / 'd1-create.json').read_text('utf-8'))
        body = nq.load_fixture()
        self.assertEqual(sorted(set(body) - {'secrets', 'secrets_encrypted'}), sorted(d1))
        self.assertEqual({k: v for k, v in body['agent_settings'].items() if k != 'acp_model'},
                         {k: v for k, v in d1['agent_settings'].items() if k != 'acp_model'})
        for key in ('conversation_runtime', 'workspace', 'autotitle', 'container'):
            self.assertEqual(body[key], d1[key])


class RealStageRefusal(Base):
    """The dispatcher's admission of a real stage never admits the native qualification create."""

    def test_the_d1_stage_refuses_it_as_its_template(self):
        with self.assertRaises(di.DispatchRefused) as caught:
            di.check_stage_template(nq.load_fixture(), 'implement')
        self.assertEqual(caught.exception.code, 'STAGE_TEMPLATE_DISPOSABLE')

    def test_the_stage_body_check_refuses_it(self):
        admission = di.admission_policy(PROFILE, PROFILE_ID)
        template = json.loads(di.read_profile_artifact(admission['create_template']['path']))
        with self.assertRaises(di.DispatchRefused) as caught:
            di.check_create_body(build(), admission=admission, template=template, conversation_id=CONVERSATION)
        self.assertEqual((caught.exception.code, caught.exception.context), ('BODY_FIELD_UNKNOWN', {'field': 'secrets'}))
        native = {di.EXECUTION_PROFILE_KEY: di.NATIVE, 'endpoint': PROXY, 'held': NT.fingerprint(TOKEN)}
        with self.assertRaises(di.DispatchRefused) as caught:
            di.check_create_body(build(), admission=admission, template=template, conversation_id=CONVERSATION,
                                 secrets=native)
        self.assertEqual(caught.exception.code, 'BODY_NOT_TEMPLATE')

    def test_the_stage_artifact_reader_cannot_read_it(self):
        with self.assertRaises(ValueError):
            di.read_profile_artifact(nq.FIXTURE_PATH)


class SharedCheck(Base):
    def test_the_one_function_with_this_refusal_type(self):
        self.assertIs(cs, sys.modules['aieh_dispatch_create_secrets'])
        self.assertIs(di.secrets_check, cs)
        for code, meaning in cs.NATIVE_MEANINGS.items():
            self.assertEqual(nq.REFUSALS[code], meaning)
        body = build()
        with mock.patch.object(cs, 'check_native_secrets', wraps=cs.check_native_secrets) as spy:
            nq.check_create(body, conversation_id=CONVERSATION, profile=PROFILE, held=NT.fingerprint(TOKEN))
        [call] = spy.call_args_list
        self.assertEqual((call.kwargs['refused'], call.kwargs['endpoint'], call.kwargs['held']),
                         (nq.QualificationRefused, PROXY, NT.fingerprint(TOKEN)))

        def refuse(body, *, refused, **kwargs):
            raise refused('NATIVE_SWITCH_NOT_DECLARED', 'the shared function refused')
        with mock.patch.object(cs, 'check_native_secrets', refuse):
            self.assertEqual(self.refused('NATIVE_SWITCH_NOT_DECLARED', body).detail, 'the shared function refused')

    def test_the_shared_codes_come_through(self):
        def put(path, value):
            def change(body):
                node = body
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
            return change
        cases = [
            ('NATIVE_SECRETS_MIXED', put(('secrets', 'ANTHROPIC_API_KEY'), {'kind': 'StaticSecret', 'value': 'x'})),
            ('NATIVE_SWITCH_NOT_DECLARED', put(('secrets', 'CLAUDE_CODE_PROXY_RESOLVES_HOSTS', 'value'), '1')),
            ('NATIVE_PROXY_NOT_TUNNEL', put(('secrets', 'HTTPS_PROXY', 'value'), 'http://172.17.0.1:8091')),
            ('NATIVE_MCP_FORBIDDEN', put(('agent_settings', 'mcp_config'), {'servers': {}})),
            ('NATIVE_AGENT_CONTEXT_FORBIDDEN', put(('agent_settings', 'agent_context'), {'secrets': {}})),
            ('NATIVE_FILE_SECRETS_FORBIDDEN', put(('agent_settings', 'acp_file_secrets'), [{'name': 'x'}])),
            ('NATIVE_ACP_COMMAND_NOT_PINNED', put(('agent_settings', 'acp_command'), [])),
            ('NATIVE_CONFIG_DIR_RELOCATED', put(('agent_settings', 'acp_isolate_data_dir'), False)),
            ('NATIVE_TOKEN_OUTSIDE_SECRET', put(('tags', 'aieh'), TOKEN[:30])),
            ('NATIVE_TOKEN_NOT_SHAPED', put(('secrets', 'CLAUDE_CODE_OAUTH_TOKEN', 'value'), 'sk-ant-api03-' + 'k' * 50)),
            ('NATIVE_BODY_FIELD_FORBIDDEN', put(('initial_message',), 'hello')),
            ('SECRET_KIND_FORBIDDEN', put(('secrets', 'HTTPS_PROXY', 'kind'), 'LookupSecret')),
            ('SECRETS_ENCRYPTED', put(('secrets_encrypted',), True)),
        ]
        for code, change in cases:
            with self.subTest(code=code):
                self.refused(code, self.altered(change))
        self.refused('NATIVE_TOKEN_NOT_HELD', build(), held=NT.fingerprint(OTHER))
        bare = copy.deepcopy(PROFILE)
        bare['network']['endpoints'] = [e for e in bare['network']['endpoints'] if e.get('class') != 'provider-tunnel']
        self.refused('NATIVE_TUNNEL_UNDECLARED', build(), profile=bare)


class OwnRefusals(Base):
    def test_the_conversation_id(self):
        self.refused('CONVERSATION_ID_MISMATCH', build(), conversation_id='not-a-uuid')
        self.refused('CONVERSATION_ID_MISMATCH', build(), conversation_id='b0333c00-0000-4000-8000-0000000e0511')

    def test_malformed(self):
        self.refused('BODY_MALFORMED', [build()])
        self.refused('BODY_MALFORMED', self.altered(lambda b: b.update(container=['browser'])))

    def test_the_runtime(self):
        for value in ('process', None, ['docker']):
            with self.subTest(value=value):
                self.refused('RUNTIME_NOT_DOCKER', self.altered(lambda b: b.update(conversation_runtime=value)))

    def test_the_model(self):
        for value in ('claude-opus-5', 'sonnet', 'claude-sonnet-4-6'):
            with self.subTest(value=value):
                self.refused('MODEL_NOT_RECORDED',
                             self.altered(lambda b: b['agent_settings'].update(acp_model=value)))

    def test_the_nested_workspace(self):
        for workspace in ({'kind': 'LocalWorkspace', 'working_dir': '/'},
                          {'kind': 'LocalWorkspace', 'working_dir': '/workspace', 'host_path': '/'},
                          {'kind': 'RemoteWorkspace', 'working_dir': '/workspace'}, None):
            with self.subTest(workspace=workspace):
                self.refused('WORKSPACE_NOT_FIXTURE', self.altered(lambda b: b.update(workspace=workspace)))

    def test_the_nested_container(self):
        self.refused('CAPS_OVERRIDE_FORBIDDEN', self.altered(lambda b: b['container'].update(memory='64g')))
        self.refused('CAPS_OVERRIDE_FORBIDDEN', self.altered(lambda b: b['container'].update(pids_limit=0)))
        self.refused('CONTAINER_NOT_FIXTURE', self.altered(lambda b: b['container'].update(browser=True)))
        self.refused('CONTAINER_NOT_FIXTURE', self.altered(lambda b: b['container'].update(network='host')))
        self.refused('CONTAINER_NOT_FIXTURE', self.altered(lambda b: b.update(container={})))

    def test_the_nested_tags(self):
        for tags in ({'aieh': 'e-05.11'}, {'aieh': 'e-05.11-disposable', 'stage': 'implement'}, {}, None):
            with self.subTest(tags=tags):
                self.refused('TAGS_NOT_FIXTURE', self.altered(lambda b: b.update(tags=tags)))

    def test_every_other_field_is_the_fixtures(self):
        self.refused('BODY_NOT_FIXTURE', self.altered(lambda b: b.pop('autotitle')))
        self.refused('BODY_NOT_FIXTURE', self.altered(lambda b: b.update(autotitle=True)))
        self.refused('BODY_NOT_FIXTURE', self.altered(lambda b: b.pop('container')))


class Pin(Base):
    def test_drift_and_shape(self):
        raw = (REPO / nq.FIXTURE_PATH).read_bytes()
        body = build()
        self.refused('FIXTURE_DRIFTED', body, read=lambda path: raw + b' ')
        fixture = json.loads(raw)

        def repinned(change):
            data = copy.deepcopy(fixture)
            change(data)
            text = json.dumps(data).encode('utf-8')
            return text, hashlib.sha256(text).hexdigest()
        for change in (lambda f: f.update(format='other'),
                       lambda f: f['body']['agent_settings'].update(acp_model='claude-opus-5'),
                       lambda f: f['body']['secrets'].pop('HTTPS_PROXY'),
                       lambda f: f['body'].update(conversation_id='fixed')):
            text, digest = repinned(change)
            with mock.patch.object(nq, 'FIXTURE_SHA256', digest):
                self.refused('FIXTURE_INVALID', body, read=lambda path, t=text: t)
        with mock.patch.object(nq, 'FIXTURE_SHA256', hashlib.sha256(b'{"a": 1, "a": 2}').hexdigest()):
            self.refused('FIXTURE_INVALID', body, read=lambda path: b'{"a": 1, "a": 2}')

    def test_codes_and_shape(self):
        for code in nq.REFUSALS:
            self.assertEqual(nq.QualificationRefused(code, 'd').to_json()['code'], code)
        with self.assertRaises(ValueError):
            nq.QualificationRefused('NOT_A_CODE', 'd')


if __name__ == '__main__':
    unittest.main()
