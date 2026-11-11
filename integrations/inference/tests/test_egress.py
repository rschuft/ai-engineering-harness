"""The broker's egress is a code-path control (decision 0015 section 5.1): it connects to the configured upstream
origin of the admitted token's family and nowhere else. Read from the module's syntax tree: one function opens a
connection, and the pass-through calls it only with that family's origin; nothing imports litellm or another
HTTP client, reads a proxy variable or the environment. connect_upstream itself admits only https or a
loopback http origin, and building its connection opens nothing.
"""
from __future__ import annotations

import ast
import unittest

import broker_support as S

CATEGORY = 'unit'
IB = S.IB
SOURCE = (S.HERE.parent / 'inference_broker.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
CONNECTORS = {'HTTPConnection', 'HTTPSConnection', 'create_connection', 'urlopen', 'socket', 'connect',
              'create_default_context', 'getaddrinfo', 'gethostbyname', 'getfqdn'}


def enclosing_functions():
    """{node id: name of the innermost function enclosing it}."""
    owner = {}

    def visit(node, name):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else name
            owner[id(child)] = inner
            visit(child, inner)
    visit(TREE, '<module>')
    return owner


class TestEgressCodePath(unittest.TestCase):
    def test_no_other_client_or_litellm_is_imported(self):
        imported = set()
        for node in ast.walk(TREE):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        for name in ('litellm', 'urllib.request', 'urllib3', 'requests', 'httpx', 'aiohttp', 'openai', 'anthropic'):
            self.assertNotIn(name, imported)
        self.assertFalse(any(name.startswith('litellm') for name in imported if name))

    def test_only_connect_upstream_opens_a_connection(self):
        owner = enclosing_functions()
        sites = {}
        for node in ast.walk(TREE):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', None)
                if name in CONNECTORS:
                    sites.setdefault(owner[id(node)], set()).add(name)
        self.assertEqual(sites, {'connect_upstream': {'HTTPConnection', 'HTTPSConnection',
                                                      'create_default_context'}})

    def test_the_pass_through_connects_only_to_its_family_upstream(self):
        calls = [node for node in ast.walk(TREE) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == '_connect']
        self.assertEqual([ast.unparse(call) for call in calls],
                         ['self._connect(family.upstream, self.config.upstream_timeout_s)'])
        relay = next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == '_relay')
        self.assertIn('family = admission.family', ast.unparse(relay))

    def test_no_environment_or_proxy_is_read(self):
        for node in ast.walk(TREE):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, ('environ', 'getenv', 'getproxies'))
        self.assertNotIn('proxy_', SOURCE.lower().replace('proxy-', ''))


class TestConnectUpstream(unittest.TestCase):
    def test_https_verifies_and_http_is_loopback_only(self):
        tls = IB.connect_upstream(IB.parse_origin('https://api.example.test'), 5)
        self.assertIsInstance(tls, IB.http.client.HTTPSConnection)
        self.assertEqual((tls.host, tls.port, tls.sock), ('api.example.test', 443, None))  # nothing opened
        self.assertEqual(tls._context.verify_mode, IB.ssl.CERT_REQUIRED)
        self.assertTrue(tls._context.check_hostname)
        again = IB.connect_upstream(IB.parse_origin('https://api.example.test:8443'), 5)
        self.assertIs(again._context, tls._context)   # one verifying context, built once
        self.assertIs(tls._context, IB._TLS)
        plain = IB.connect_upstream(IB.parse_origin('http://127.0.0.1:11434'), 5)
        self.assertEqual((type(plain), plain.host, plain.port, plain.sock),
                         (IB.http.client.HTTPConnection, '127.0.0.1', 11434, None))
        for origin in (IB.Origin('http', 'api.example.test', 80), IB.Origin('ftp', '127.0.0.1', 21)):
            with self.subTest(origin=origin):
                with self.assertRaises(IB.InferenceError) as caught:
                    IB.connect_upstream(origin, 5)
                self.assertEqual(caught.exception.code, 'UPSTREAM_NOT_CONFIGURED')


if __name__ == '__main__':
    unittest.main()
