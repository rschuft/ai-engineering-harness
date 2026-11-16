"""R2's structural tests (Proposed decision 0025 point 2): the Integration process opens no outbound connection and
imports no credential, Gitea, authorization-recorder or dispatch-transport module.

- **No client socket** (read from the syntax trees, the pattern of integrations/inference/tests/test_egress.py): the
  modules the server process loads (app.py and the modules it loads by file name, transitively) import no network
  client and call no connector; the one socket constructor is ``bind_listener``'s, which binds and listens and never
  connects. The lifecycle command (service.py) and the enroll command open no socket either.
- **The import census** (the pattern of the input recorder's): a fresh interpreter loads app.py and builds the
  application; the repository files it has then loaded are exactly the server's four modules, none under
  integrations/credentials, integrations/gitea, integrations/dispatch or integrations/inference, and no
  authorization recorder. The supervisor's too: a fresh interpreter loads service.py and selects the platform
  adapter, and loads nothing under those packages (the Windows adapter loads its credential provider only when one
  is asked for). The live processes' own censuses (their records, at start and at stop) are test_listener.py's.
- **One declared port**: app.PORT is the host census's port (tools/guest.py HOST_CENSUS_PORTS) and the network
  matrix's nm-owner-ui-integration address.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

import ownerhost_support as T

CATEGORY = 'unit'
CONNECTORS = {'HTTPConnection', 'HTTPSConnection', 'create_connection', 'urlopen', 'connect', 'connect_ex',
              'getaddrinfo', 'gethostbyname', 'getfqdn', 'create_default_context', 'open_connection',
              'create_datagram_endpoint', 'socketpair', 'fromfd', 'request', 'urlretrieve', 'sendto'}
NETWORK_MODULES = ('http', 'urllib', 'urllib3', 'requests', 'httpx', 'aiohttp', 'websockets', 'ssl', 'smtplib',
                   'ftplib', 'xmlrpc', 'dulwich')
# The database calls of the store's own SQLite file are the only "connect" calls allowed.
DATABASE_CONNECTS = {'sqlite3.connect', 'storecore.connect'}
SERVER_MODULES = {'integrations/ownerhost/app.py', 'integrations/ownerhost/session.py',
                  'integrations/conversation/conversation_store.py', 'integrations/storecore/storecore.py'}
SUPERVISOR_MODULES = SERVER_MODULES | {'integrations/ownerhost/service.py', 'integrations/platform/platform_contract.py',
                                       'integrations/platform/platform_windows.py', 'integrations/platform/no_window.py',
                                       'integrations/paths/aieh_paths.py'}
FORBIDDEN_PREFIXES = ('integrations/credentials/', 'integrations/gitea/', 'integrations/dispatch/',
                      'integrations/inference/', 'integrations/owner/')


def tree(path: Path):
    return ast.parse(path.read_text(encoding='utf-8'))


def loaded_sources(path: Path) -> set:
    """The repository modules PATH loads by file name: string constants naming a .py file that exists in the
    package, its sibling packages or a path joined in the call (REPO / 'integrations' / X / 'y.py')."""
    found = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith('.py'):
            for candidate in [path.parent / node.value] + list(T.REPO.glob(f'integrations/*/{node.value}')):
                if candidate.is_file():
                    found.add(candidate.resolve())
    return found


def server_census() -> set:
    modules = {(T.PACKAGE / 'app.py').resolve()}
    while True:
        more = set().union(*(loaded_sources(m) for m in modules)) - modules
        if not more:
            return modules
        modules |= more


def imported(path: Path) -> set:
    names = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or '').split('.')[0])
    return names


def calls(path: Path) -> dict:
    """{called name: [enclosing function names]}."""
    owner = {}

    def visit(node, name):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else name
            owner[id(child)] = inner
            visit(child, inner)
    root = tree(path)
    visit(root, '<module>')
    found = {}
    for node in ast.walk(root):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', None)
            found.setdefault(name, []).append(owner[id(node)])
    return found


def connector_calls(path: Path) -> set:
    """The calls of PATH whose called name is a connector, as written (``sqlite3.connect``, ``sock.connect``)."""
    return {ast.unparse(node.func) for node in ast.walk(tree(path)) if isinstance(node, ast.Call)
            and (node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', None))
            in CONNECTORS}


def relative(path: Path) -> str:
    return path.resolve().relative_to(T.REPO).as_posix()


class NoClientSocket(unittest.TestCase):
    def test_the_server_census_is_its_four_modules(self):
        self.assertEqual({relative(p) for p in server_census()}, SERVER_MODULES)

    def test_no_server_module_imports_a_network_client_or_calls_a_connector(self):
        for path in sorted(server_census()):
            with self.subTest(module=relative(path)):
                self.assertEqual(imported(path) & set(NETWORK_MODULES), set())
                self.assertEqual(connector_calls(path) - DATABASE_CONNECTS, set())

    def test_the_one_socket_is_the_listener_which_binds_and_never_connects(self):
        app = T.PACKAGE / 'app.py'
        found = calls(app)
        self.assertEqual(found['socket'], ['bind_listener'])
        self.assertEqual(sorted(found['bind']), ['bind_listener'])
        self.assertEqual(sorted(found['listen']), ['bind_listener'])
        listener = next(n for n in ast.walk(tree(app)) if isinstance(n, ast.FunctionDef) and n.name == 'bind_listener')
        text = ast.unparse(listener)
        self.assertIn('listener.bind((LOOPBACK, port))', text)
        self.assertIn("LOOPBACK = '127.0.0.1'", (T.PACKAGE / 'app.py').read_text(encoding='utf-8'))
        for name in ('connect', 'sendto', 'create_connection'):
            self.assertNotIn(f'.{name}(', text)

    def test_the_uvicorn_server_is_given_the_listener_and_no_host(self):
        serve = next(n for n in ast.walk(tree(T.PACKAGE / 'app.py'))
                     if isinstance(n, ast.FunctionDef) and n.name == 'serve')
        text = ast.unparse(serve)
        self.assertIn('server.run(sockets=[listener])', text)
        config = next(n for n in ast.walk(serve) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'uvicorn.Config')
        keywords = {k.arg: ast.unparse(k.value) for k in config.keywords}
        self.assertNotIn('host', keywords)
        self.assertNotIn('port', keywords)
        self.assertEqual((keywords['proxy_headers'], keywords['ws'], keywords['access_log']), ('False', "'none'", 'False'))

    def test_the_lifecycle_and_enroll_commands_open_no_socket(self):
        for name in ('service.py', 'enroll.py', 'session.py'):
            path = T.PACKAGE / name
            with self.subTest(module=name):
                self.assertEqual(imported(path) & set(NETWORK_MODULES) - {'dulwich'}, set())
                self.assertEqual(connector_calls(path), set())
                self.assertEqual(set(calls(path)) & {'socket', 'bind', 'listen'}, set())

    def test_no_cookie_is_read_or_set(self):
        for name in ('app.py', 'session.py'):
            text = (T.PACKAGE / name).read_text(encoding='utf-8').lower()
            self.assertNotIn('set_cookie', text)
            self.assertNotIn('request.cookies', text)


class OnePort(unittest.TestCase):
    def test_the_port_is_the_census_s_and_the_matrix_s(self):
        guest = tree(T.REPO / 'tools' / 'guest.py')
        census = next(n for n in guest.body if isinstance(n, ast.Assign)
                      and [ast.unparse(t) for t in n.targets] == ['HOST_CENSUS_PORTS'])
        self.assertIn(T.A.PORT, ast.literal_eval(census.value))
        matrix = json.loads((T.REPO / 'policy' / 'network-matrix.json').read_text(encoding='utf-8'))
        (edge,) = [e for e in matrix['edges'] if e['id'] == 'nm-owner-ui-integration']
        self.assertIn(f'{T.A.LOOPBACK}:{T.A.PORT}', edge['protocol'])
        self.assertIn(f'{T.A.LOOPBACK}:{T.A.PORT}', ' '.join(m['mechanism'] for m in edge['enforcement']))


IMPORT_CENSUS = r'''
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('aieh_ownerhost_app', sys.argv[1])
app = importlib.util.module_from_spec(spec); sys.modules[spec.name] = app; spec.loader.exec_module(app)
application = app.create_app(lambda: None)
print(json.dumps(sorted(getattr(m, '__file__', None) or '' for m in list(sys.modules.values()))))
'''


class ImportCensus(unittest.TestCase):
    category = 'integration'

    def test_building_the_server_loads_only_its_four_modules(self):
        result = subprocess.run([sys.executable, '-I', '-B', '-c', IMPORT_CENSUS, str(T.PACKAGE / 'app.py')],
                                capture_output=True, text=True, encoding='utf-8', timeout=T.WAIT_CEILING_S,
                                stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 0, result.stderr)
        files = [Path(f) for f in json.loads(result.stdout) if f]
        loaded = {relative(f) for f in files if f.resolve().is_relative_to(T.REPO)}
        self.assertEqual(loaded, SERVER_MODULES)
        self.assertEqual([f for f in loaded if f.startswith(FORBIDDEN_PREFIXES)], [])

    def test_the_supervisor_loads_no_credential_gitea_dispatch_inference_or_owner_module(self):
        code = ('import importlib.util, json, sys\n'
                'spec = importlib.util.spec_from_file_location("aieh_ownerhost_service", sys.argv[1])\n'
                'sv = importlib.util.module_from_spec(spec); sys.modules[spec.name] = sv; spec.loader.exec_module(sv)\n'
                'adapter = sv.contract.select_adapter()\n'
                'def files(): return sorted(getattr(m, "__file__", None) or "" for m in list(sys.modules.values()))\n'
                'before = files()\n'
                'windows = sys.modules["aieh_platform_windows"]\n'
                'windows.credentials\n'
                'print(json.dumps([before, files()]))\n')
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(T.PACKAGE / 'service.py')],
                                capture_output=True, text=True, encoding='utf-8', timeout=T.WAIT_CEILING_S,
                                stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 0, result.stderr)
        before, after = ({relative(Path(f)) for f in found if f and Path(f).resolve().is_relative_to(T.REPO)}
                         for found in json.loads(result.stdout))
        self.assertEqual(before, SUPERVISOR_MODULES)
        self.assertEqual([f for f in before if f.startswith(FORBIDDEN_PREFIXES)], [])
        # the adapter still supplies the provider when asked: the module is loaded then, and only then
        self.assertEqual(after - before, {'integrations/credentials/credential_provider.py'})

    def test_loading_the_enroll_command_loads_no_broker_until_its_console_check(self):
        code = IMPORT_CENSUS.replace("application = app.create_app(lambda: None)\n", '')
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(T.PACKAGE / 'enroll.py')],
                                capture_output=True, text=True, encoding='utf-8', timeout=T.WAIT_CEILING_S,
                                stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = {relative(Path(f)) for f in json.loads(result.stdout) if f and Path(f).resolve().is_relative_to(T.REPO)}
        self.assertEqual(loaded, {'integrations/ownerhost/enroll.py', 'integrations/ownerhost/session.py',
                                  'integrations/conversation/conversation_store.py',
                                  'integrations/storecore/storecore.py'})


if __name__ == '__main__':
    unittest.main()
