"""The inference broker's family declarations and its configuration (components.inference_broker of config.yml,
decision 0009): the shipped declarations, every refusal of the declaration file and of the component, the
decision 0009 loader's refusal of secret-shaped keys under the component, and the config command.
"""
from __future__ import annotations

import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import broker_support as S

CATEGORY = 'unit'
IB = S.IB


def code_of(callable_, *args, **kwargs) -> str:
    try:
        callable_(*args, **kwargs)
    except IB.InferenceError as exc:
        return exc.code
    raise AssertionError('no refusal')


class TestShippedDeclarations(unittest.TestCase):
    def test_three_provisional_families_with_their_auth_shapes_and_extractors(self):
        families = IB.load_declarations()
        self.assertEqual(list(families), ['anthropic-messages', 'openai-responses', 'openai-chat'])
        self.assertEqual({f.status for f in families.values()}, {'provisional'})
        self.assertEqual({(f.id, f.auth_header, f.auth_scheme, f.usage, f.query) for f in families.values()},
                         {('anthropic-messages', 'x-api-key', None, 'anthropic-messages', 'refuse'),
                          ('openai-responses', 'authorization', 'Bearer', 'openai-responses', 'refuse'),
                          ('openai-chat', 'authorization', 'Bearer', 'openai-chat', 'refuse')})
        self.assertEqual({f.id: sorted(f.routes) for f in families.values()},
                         {'anthropic-messages': [('POST', '/v1/messages')],
                          'openai-responses': [('POST', '/v1/responses')],
                          'openai-chat': [('POST', '/v1/chat/completions')]})

    def test_nothing_is_configured_by_default_and_every_model_allowlist_is_empty(self):
        config = IB.load_config(None)
        self.assertIsNone(config.control_port)
        self.assertIsNone(config.inference_port)
        for family in config.families.values():
            self.assertEqual((family.provider, family.upstream, family.models), (None, None, ()))
        self.assertEqual(config.max_request_bytes, 32 * 1024 * 1024)
        self.assertEqual(config.max_ttl_s, 86400)
        self.assertEqual(config.upstream_timeout_s, 600)

    def test_the_declaration_file_names_no_model_upstream_or_provider(self):
        text = IB.FAMILIES_PATH.read_text(encoding='utf-8')
        data = json.loads(text)
        for entry in data['families']:
            self.assertNotIn('models', entry)
            self.assertNotIn('upstream', entry)
            self.assertNotIn('provider', entry)


class TestDeclarationRefusals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-inference-decl-'))
        cls.good = json.loads(IB.FAMILIES_PATH.read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def variant(self, change) -> str:
        data = copy.deepcopy(self.good)
        change(data)
        path = self.tmp / 'families.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        try:
            IB.load_declarations(path)
        except IB.InferenceError as exc:
            self.assertFalse(exc.refusal)
            return exc.code
        return 'accepted'

    def test_the_unchanged_copy_is_accepted(self):
        self.assertEqual(self.variant(lambda d: None), 'accepted')

    def test_each_malformed_declaration_is_refused(self):
        def fam(**kw):
            def change(d):
                d['families'][0].update(kw)
            return change
        cases = {
            'format': lambda d: d.update(format='aieh-inference-families/2'),
            'extra top key': lambda d: d.update(models=[]),
            'no families': lambda d: d.update(families=[]),
            'extra family key': fam(models=['syn-model-a']),
            'missing key': lambda d: d['families'][0].pop('usage'),
            'duplicate id': lambda d: d['families'][1].update(id='anthropic-messages'),
            'upper-case id': fam(id='Anthropic'),
            'status': fam(status='observed'),
            'consumer': fam(consumer=5),
            'no routes': fam(routes=[]),
            'dot segment': fam(routes=[{'method': 'POST', 'path': '/v1/../admin'}]),
            'relative path': fam(routes=[{'method': 'POST', 'path': 'v1/messages'}]),
            'trailing slash': fam(routes=[{'method': 'POST', 'path': '/v1/messages/'}]),
            'percent': fam(routes=[{'method': 'POST', 'path': '/v1/%2e%2e'}]),
            'method': fam(routes=[{'method': 'post', 'path': '/v1/messages'}]),
            'route key': fam(routes=[{'method': 'POST', 'path': '/v1/messages', 'query': True}]),
            'duplicate route': fam(routes=[{'method': 'POST', 'path': '/v1/x'}, {'method': 'POST', 'path': '/v1/x'}]),
            'query': fam(query='allow'),
            'auth scheme': fam(auth={'header': 'authorization', 'scheme': 'Basic'}),
            'auth header': fam(auth={'header': 'X-Api-Key', 'scheme': None}),
            'auth keys': fam(auth={'header': 'x-api-key'}),
            'usage': fam(usage='litellm'),
            'not a list': lambda d: d.update(families={}),
            'family not a mapping': lambda d: d['families'].append(5),
            'auth not a mapping': fam(auth=5),
            'route not a mapping': fam(routes=[5]),
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.assertEqual(self.variant(change), 'DECLARATION_INVALID')

    def test_an_unreadable_file_is_refused(self):
        path = self.tmp / 'broken.json'
        path.write_text('{', encoding='utf-8')
        self.assertEqual(code_of(IB.load_declarations, path), 'DECLARATION_INVALID')
        self.assertEqual(code_of(IB.load_declarations, self.tmp / 'absent.json'), 'DECLARATION_INVALID')


class TestComponentConfiguration(unittest.TestCase):
    def load(self, raw, **kwargs):
        return IB.load_config(raw, **kwargs)

    def test_a_full_configuration(self):
        config = self.load({'control_port': 18431, 'inference_port': 18432, 'max_request_bytes': 1024,
                            'max_ttl_s': 60, 'upstream_timeout_s': 2.5, 'families': {
                                'anthropic-messages': {'provider': 'synthetic', 'upstream': 'https://API.Example.test',
                                                       'models': [S.MODEL_A, 'syn/model:b@1']},
                                'openai-chat': {'upstream': 'http://127.0.0.1:11434', 'models': []},
                                'openai-responses': {'upstream': 'http://[::1]:8080', 'provider': 'p'}}})
        anthropic = config.families['anthropic-messages']
        self.assertEqual(anthropic.upstream.text(), 'https://api.example.test:443')
        self.assertEqual(anthropic.models, (S.MODEL_A, 'syn/model:b@1'))
        self.assertEqual(config.families['openai-chat'].upstream.text(), 'http://127.0.0.1:11434')
        self.assertIsNone(config.families['openai-chat'].provider)
        self.assertEqual(config.families['openai-responses'].upstream.text(), 'http://[::1]:8080')
        self.assertEqual((config.control_port, config.inference_port, config.max_request_bytes, config.max_ttl_s,
                          config.upstream_timeout_s), (18431, 18432, 1024, 60, 2.5))
        self.assertEqual(json.loads(json.dumps(config.describe()))['format'], 'aieh-inference-config/1')

    def test_each_refusal(self):
        cases = [
            ('CONFIG_NOT_A_MAPPING', ['x']),
            ('CONFIG_NOT_A_MAPPING', {'families': ['openai-chat']}),
            ('CONFIG_NOT_A_MAPPING', {'families': {'openai-chat': 'x'}}),
            ('CONFIG_UNKNOWN_KEY', {'listen': '0.0.0.0'}),
            ('CONFIG_UNKNOWN_KEY', {'families': {'openai-chat': {'routes': []}}}),
            ('CONFIG_SECRET_SHAPED_KEY', {'api_key': 'x'}),
            ('CONFIG_SECRET_SHAPED_KEY', {'families': {'openai-chat': {'provider_key': 'x'}}}),
            ('CONFIG_SECRET_SHAPED_KEY', {'families': {'openai-chat': {'models': [{'Token': 'x'}]}}}),
            ('CONFIG_SECRET_SHAPED_KEY', {'Password': 'x'}),
            ('CONFIG_FAMILY_UNKNOWN', {'families': {'gemini': {}}}),
            ('CONFIG_PORT_INVALID', {'control_port': 80}),
            ('CONFIG_PORT_INVALID', {'inference_port': 70000}),
            ('CONFIG_PORT_INVALID', {'control_port': True}),
            ('CONFIG_PORT_INVALID', {'control_port': '18431'}),
            ('CONFIG_PORT_INVALID', {'control_port': 0}),
            ('CONFIG_PORT_INVALID', {'control_port': 18431, 'inference_port': 18431}),
            ('CONFIG_LIMIT_INVALID', {'max_request_bytes': 0}),
            ('CONFIG_LIMIT_INVALID', {'max_request_bytes': 1.5}),
            ('CONFIG_LIMIT_INVALID', {'max_ttl_s': 8 * 86400}),
            ('CONFIG_LIMIT_INVALID', {'upstream_timeout_s': True}),
            ('CONFIG_LIMIT_INVALID', {'upstream_timeout_s': 0}),
            ('CONFIG_PROVIDER_INVALID', {'families': {'openai-chat': {'provider': 'Synthetic'}}}),
            ('CONFIG_PROVIDER_INVALID', {'families': {'openai-chat': {'provider': 5}}}),
            ('CONFIG_PROVIDER_REQUIRED', {'families': {'openai-chat': {'upstream': 'https://api.example.test'}}}),
            ('CONFIG_MODEL_INVALID', {'families': {'openai-chat': {'models': ['*']}}}),
            ('CONFIG_MODEL_INVALID', {'families': {'openai-chat': {'models': ['syn-*']}}}),
            ('CONFIG_MODEL_INVALID', {'families': {'openai-chat': {'models': ['syn-model-?']}}}),
            ('CONFIG_MODEL_INVALID', {'families': {'openai-chat': {'models': ['syn[ab]']}}}),
            ('CONFIG_MODEL_INVALID', {'families': {'openai-chat': {'models': [S.MODEL_A, S.MODEL_A]}}}),
            ('CONFIG_MODEL_INVALID', {'families': {'openai-chat': {'models': ['']}}}),
            ('CONFIG_MODEL_INVALID', {'families': {'openai-chat': {'models': [5]}}}),
            ('CONFIG_MODEL_INVALID', {'families': {'openai-chat': {'models': 'syn-model-a'}}}),
            ('CONFIG_MODEL_INVALID', {'families': {'openai-chat': {'models': 'syn'}}}),
            ('CONFIG_MODEL_INVALID', {'families': {'openai-chat': {'models': ['syn model']}}}),
        ]
        for expected, raw in cases:
            with self.subTest(raw=raw):
                self.assertEqual(code_of(self.load, raw), expected)

    def test_each_inadmissible_upstream_origin(self):
        for origin in ('ftp://api.example.test', 'https://user:pw@api.example.test', 'https://user@api.example.test',
                       'https://api.example.test/v1', 'https://api.example.test?x=1', 'https://api.example.test#f',
                       'http://api.example.test', 'http://10.0.0.1:8080', 'https://', 'https://api example.test',
                       'https://api.example.test:99999', 'https://a_b.example.test', 'api.example.test', '', 5,
                       'https://' + 'a' * 300):
            with self.subTest(origin=origin):
                self.assertEqual(code_of(IB.parse_origin, origin), 'CONFIG_ORIGIN_INVALID')
        self.assertEqual(IB.parse_origin('https://api.example.test/').text(), 'https://api.example.test:443')
        self.assertEqual(IB.parse_origin('http://127.0.0.2').text(), 'http://127.0.0.2:80')
        self.assertTrue(IB.parse_origin('http://127.0.0.2').loopback)
        self.assertFalse(IB.parse_origin('https://api.example.test').loopback)

    def test_ephemeral_ports_are_for_tests_only(self):
        self.assertEqual(code_of(self.load, {'control_port': 0}), 'CONFIG_PORT_INVALID')
        config = self.load({'control_port': 0, 'inference_port': 0}, allow_ephemeral=True)
        self.assertEqual((config.control_port, config.inference_port), (0, 0))


class TestDecision0009Loader(unittest.TestCase):
    """config.yml reaches the broker through the decision 0009 loader, which refuses a secret-shaped key
    anywhere, the component included, before the component sees it."""

    def test_the_loader_refuses_a_secret_shaped_key_under_the_component(self):
        for raw in ({'api_key': 'x'}, {'families': {'openai-chat': {'credential': 'x'}}},
                    {'families': {'anthropic-messages': {'secret': 'x'}}}):
            with self.subTest(raw=raw):
                with self.assertRaises(IB.paths.PathsError) as caught:
                    IB.paths.validate_config({'version': 1, 'components': {'inference_broker': raw}})
                self.assertEqual(caught.exception.code, 'CONFIG_SECRET_SHAPED_KEY')

    def test_the_loader_passes_the_component_through(self):
        raw = {'control_port': 18431, 'families': {'openai-chat': {'upstream': 'http://127.0.0.1:11434'}}}
        _, _, components = IB.paths.validate_config({'version': 1, 'components': {'inference_broker': raw}})
        self.assertEqual(IB.load_config(components['inference_broker']).families['openai-chat'].upstream.port,
                         11434)


class TestConfigCommand(unittest.TestCase):
    def context(self, raw):
        def refuse(*args):
            raise AssertionError('the config command touched a credential, store or log')
        return IB.Context(component=lambda: raw, provider=refuse, store=refuse, logs=refuse, stdin=None,
                          out=io.StringIO(), err=io.StringIO(), wait=refuse)

    def test_it_prints_the_effective_families_and_touches_nothing_else(self):
        ctx = self.context({'families': {'openai-chat': {'upstream': 'http://127.0.0.1:11434',
                                                         'models': [S.MODEL_A]}}})
        self.assertEqual(IB.main(['config'], ctx), 0)
        report = json.loads(ctx.out.getvalue())
        self.assertEqual(report['format'], 'aieh-inference-config/1')
        self.assertEqual([f['models'] for f in report['families']], [[], [], [S.MODEL_A]])
        self.assertIn('I7 no-exposure scan: clean', ctx.err.getvalue())

    def test_a_refused_configuration_exits_2_with_its_code(self):
        ctx = self.context({'families': {'openai-chat': {'models': ['*']}}})
        self.assertEqual(IB.main(['config'], ctx), 2)
        self.assertIn('CONFIG_MODEL_INVALID', ctx.err.getvalue())
        self.assertEqual(ctx.out.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
