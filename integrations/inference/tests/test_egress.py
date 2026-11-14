"""The broker's egress is a code-path control (decision 0015 section 5.1): it connects to the configured upstream
origin of the admitted token's family and nowhere else. Read from the module's syntax tree: one function opens a
connection, and the pass-through calls it only with that family's origin; nothing imports litellm or another
HTTP client, reads a proxy variable or the environment. connect_upstream itself admits only https or a
loopback http origin, and building its connection opens nothing. Its connection classes add one thing to
http.client's (S-03.2): after http.client's own connect, the socket is reported to on_connect, where the
pass-through writes the upstream-connect audit line with the peer reached.
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
              'create_default_context', 'getaddrinfo', 'gethostbyname', 'getfqdn', '_UpstreamHTTPConnection',
              '_UpstreamHTTPSConnection'}


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
        self.assertEqual(sites, {'connect_upstream': {'_UpstreamHTTPConnection', '_UpstreamHTTPSConnection',
                                                      'create_default_context'},
                                 'connect': {'connect'}})

    def test_the_connect_hook_only_calls_http_client_s_own_connect(self):
        hook = next(n for n in ast.walk(TREE) if isinstance(n, ast.ClassDef) and n.name == '_UpstreamConnection')
        (method,) = [n for n in hook.body if isinstance(n, ast.FunctionDef)]
        self.assertEqual(method.name, 'connect')
        calls = sorted(ast.unparse(n) for n in ast.walk(method) if isinstance(n, ast.Call))
        self.assertEqual(calls, ['self.on_connect(self.sock)', 'super()', 'super().connect()'])
        self.assertEqual(IB._UpstreamHTTPConnection.__mro__[1:3], (IB._UpstreamConnection,
                                                                   IB.http.client.HTTPConnection))
        self.assertEqual(IB._UpstreamHTTPSConnection.__mro__[1:3], (IB._UpstreamConnection,
                                                                    IB.http.client.HTTPSConnection))

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


NETWORK_MODULES = ('socket', 'ssl', 'http', 'urllib', 'urllib3', 'requests', 'httpx', 'aiohttp', 'litellm',
                   'subprocess', 'asyncio', 'smtplib', 'ftplib')


def loaded_sources(path) -> set:
    """The sibling and owner modules PATH loads by file name (its string constants naming a .py file there)."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
             and node.value.endswith('.py')}
    places = (S.HERE.parent, S.REPO / 'integrations' / 'owner')
    return {place / name for name in names for place in places if (place / name).is_file()}


class TestEnvelopeModulesOpenNothing(unittest.TestCase):
    """The census covers every module serve loads from integrations/inference/ beside the broker (the provider
    envelope, S-03.5) and the read side it is handed (integrations/owner/envelope_decisions.py and the record
    format it loads): none imports a network or process module or calls a connector."""

    def census(self) -> set:
        broker = S.HERE.parent / 'inference_broker.py'   # its own census is the tests above
        modules = loaded_sources(broker) - {broker}
        for module in list(modules):
            modules |= loaded_sources(module) - {broker}
        return modules

    def test_the_census_is_the_envelope_and_its_read_side(self):
        self.assertEqual({path.name for path in self.census()},
                         {'inference_envelope.py', 'envelope_decisions.py', 'owner_decision.py',
                          'delegated_decision.py'})

    def test_none_of_them_imports_a_network_module_or_calls_a_connector(self):
        for path in sorted(self.census()):
            with self.subTest(module=path.name):
                tree = ast.parse(path.read_text(encoding='utf-8'))
                imported = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name.split('.')[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        imported.add((node.module or '').split('.')[0])
                self.assertEqual(imported & set(NETWORK_MODULES), set())
                calls = {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', None)
                         for node in ast.walk(tree) if isinstance(node, ast.Call)}
                self.assertEqual(calls & CONNECTORS, set())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute):
                        self.assertNotIn(node.attr, ('environ', 'getenv', 'getproxies'))


class TestSelectionActOpensNothing(unittest.TestCase):
    """The model-selection act (integrations/owner/selection_recorder.py, S-03.5 slice 2) and the owner modules it
    loads open no connection: no network or process module imported, no connector called, no environment or
    proxy read. (It reads the harness repository through the repository-access module, outside this census.)"""

    def test_the_act_and_its_owner_modules_open_nothing(self):
        act = S.REPO / 'integrations' / 'owner' / 'selection_recorder.py'
        modules = {act} | loaded_sources(act)
        for module in list(modules):
            modules |= loaded_sources(module)
        self.assertEqual({path.name for path in modules},
                         {'selection_recorder.py', 'owner_decision.py', 'delegated_decision.py',
                          'envelope_decisions.py'})
        for path in sorted(modules):
            with self.subTest(module=path.name):
                tree = ast.parse(path.read_text(encoding='utf-8'))
                imported = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name.split('.')[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        imported.add((node.module or '').split('.')[0])
                self.assertEqual(imported & set(NETWORK_MODULES), set())
                calls = {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', None)
                         for node in ast.walk(tree) if isinstance(node, ast.Call)}
                self.assertEqual(calls & CONNECTORS, set())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute):
                        self.assertNotIn(node.attr, ('environ', 'getenv', 'getproxies'))


class TestConnectUpstream(unittest.TestCase):
    def test_https_verifies_and_http_is_loopback_only(self):
        tls = IB.connect_upstream(IB.parse_origin('https://api.example.test'), 5)
        self.assertIsInstance(tls, IB._UpstreamHTTPSConnection)
        self.assertIsInstance(tls, IB.http.client.HTTPSConnection)
        self.assertIsNone(tls.on_connect)
        self.assertEqual((tls.host, tls.port, tls.sock), ('api.example.test', 443, None))  # nothing opened
        self.assertEqual(tls._context.verify_mode, IB.ssl.CERT_REQUIRED)
        self.assertTrue(tls._context.check_hostname)
        again = IB.connect_upstream(IB.parse_origin('https://api.example.test:8443'), 5)
        self.assertIs(again._context, tls._context)   # one verifying context, built once
        self.assertIs(tls._context, IB._TLS)
        plain = IB.connect_upstream(IB.parse_origin('http://127.0.0.1:11434'), 5)
        self.assertEqual((type(plain), plain.host, plain.port, plain.sock),
                         (IB._UpstreamHTTPConnection, '127.0.0.1', 11434, None))
        self.assertIsInstance(plain, IB.http.client.HTTPConnection)
        for origin in (IB.Origin('http', 'api.example.test', 80), IB.Origin('ftp', '127.0.0.1', 21)):
            with self.subTest(origin=origin):
                with self.assertRaises(IB.InferenceError) as caught:
                    IB.connect_upstream(origin, 5)
                self.assertEqual(caught.exception.code, 'UPSTREAM_NOT_CONFIGURED')


if __name__ == '__main__':
    unittest.main()
