"""Tests for the native token's grammar, its entry and the dispatcher's read (plan leaf E-05.9), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -p test_native_token.py -v

Shown: a value of the native shape is admitted and every rule of the shape is named when it is not (empty,
whitespace, another character, another prefix, another provider credential, the length), never the value; the read
asks the provider for exactly the one entry, once, and refuses a missing entry, a failing provider and a value
without the shape by stable codes; the held token shows only its fingerprint (the credential provider's own form)
and is never serialized. Synthetic tokens only, built at run time; an in-memory provider only.
"""
from __future__ import annotations

import importlib.util
import pickle
import sys
import unittest
from pathlib import Path

CATEGORY = 'unit'

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


NT = _load('aieh_dispatch_native_token', HERE.parent / 'native_token.py')
NS = _load('native_support', HERE / 'native_support.py')
TOKEN = NS.token()


class Shape(unittest.TestCase):
    def test_values_of_the_shape(self):
        for value in (TOKEN, NS.token('a', 40), NS.token('b', 512), 'sk-ant-' + 'x9' + '-' + 'A_b-9' * 10):
            with self.subTest(length=len(value)):
                self.assertIsNone(NT.token_rule(value))
                self.assertTrue(NT.is_token(value))
        self.assertEqual(NT.public_prefix(TOKEN), NS.PREFIX)
        self.assertEqual(NT.secret_body(TOKEN), TOKEN[len(NS.PREFIX):])

    def test_each_rule_is_named(self):
        body = TOKEN[len(NS.PREFIX):]
        cases = {
            'empty': ('', None, b'x'),
            'whitespace': (TOKEN + '\n', ' ' + TOKEN, TOKEN[:30] + ' ' + TOKEN[30:], TOKEN + '\t', 'Bearer ' + TOKEN),
            'characters': (TOKEN + '=', TOKEN[:30] + '.' + TOKEN[30:], TOKEN + '/', TOKEN + 'é'),
            'prefix': ('aieh-inf-' + 'a' * 43, 'sk-proj-' + body, 'SK-ANT-OAT01-' + body, 'x' + TOKEN, 'sk-ant-X' + body,
                       'sk-ant-OAT01-' + body, NS.PREFIX),
            'other-credential': ('sk-ant-' + 'api03-' + body, 'sk-ant-' + 'admin01-' + body, 'sk-ant-' + 'sid01-' + body,
                                 'sk-ant-' + 'cc-' + body, 'sk-ant-' + 'si-' + body),
            'length': (NS.token('c', 39), NS.token('d', 513)),
        }
        for rule, values in cases.items():
            for value in values:
                with self.subTest(rule=rule, value=None if not isinstance(value, str) else len(value)):
                    self.assertEqual(NT.token_rule(value), rule)
        self.assertEqual([name for name, _ in NT.TOKEN_RULES], list(cases))
        for rule, _ in NT.TOKEN_RULES:   # a rule's detail names the rule, never a value
            self.assertIn(rule, NT.rule_detail(rule))

    def test_the_fingerprint_is_the_credential_provider_s(self):
        credentials = _load('aieh_credential_provider', REPO / 'integrations' / 'credentials' / 'credential_provider.py')
        self.assertEqual(NT.fingerprint(TOKEN), credentials.fingerprint(TOKEN))
        self.assertRegex(NT.fingerprint(TOKEN), NT.FINGERPRINT_SHAPE)


class Read(unittest.TestCase):
    def test_the_read_asks_for_exactly_the_one_entry(self):
        provider = NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, TOKEN), 'AIEH model provider': ('anthropic', 'x'),
                                        'other': ('u', NS.token('other'))})
        held = NT.read(provider)
        self.assertEqual(provider.reads, [NT.ENTRY])
        self.assertEqual((held.token(), held.fingerprint), (TOKEN, NT.fingerprint(TOKEN)))
        self.assertEqual(held.record(), {'format': NT.RECORD_FORMAT, 'entry': NT.ENTRY,
                                         'tokenFingerprint': NT.fingerprint(TOKEN)})
        for text in (repr(held), str(held), repr(held.record())):
            self.assertNotIn(TOKEN, text)
            self.assertNotIn(TOKEN[len(NS.PREFIX):], text)
        self.assertIn(held.fingerprint, repr(held))
        with self.assertRaises(TypeError):
            pickle.dumps(held)
        held.drop()
        self.assertFalse(held.open)
        with self.assertRaises(ValueError):
            held.token()

    def test_refusals(self):
        malformed = 'sk-ant-' + 'api03-' + TOKEN[len(NS.PREFIX):]
        cases = {
            'NATIVE_TOKEN_MISSING': NS.ObservedProvider({'other': ('u', TOKEN)}),
            'NATIVE_TOKEN_UNAVAILABLE': NS.ObservedProvider(error=OSError('the store says ' + TOKEN)),
            'NATIVE_TOKEN_NOT_SHAPED': NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, malformed)}),
        }
        for code, provider in cases.items():
            with self.subTest(code):
                with self.assertRaises(NT.NativeTokenError) as caught:
                    NT.read(provider)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(provider.reads, [NT.ENTRY])
                for needle in (TOKEN, malformed, TOKEN[len(NS.PREFIX):]):
                    self.assertNotIn(needle, str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
        for provider in (None, object()):
            with self.assertRaises(NT.NativeTokenError) as caught:
                NT.read(provider)
            self.assertEqual(caught.exception.code, 'NATIVE_TOKEN_UNAVAILABLE')

    def test_the_module_imports_the_standard_library_only(self):
        import ast
        tree = ast.parse((HERE.parent / 'native_token.py').read_text(encoding='utf-8'))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imported, {'__future__', 'hashlib', 're'})


if __name__ == '__main__':
    unittest.main()
