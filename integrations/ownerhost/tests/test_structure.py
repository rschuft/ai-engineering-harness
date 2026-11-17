"""R2's structural tests (decision 0025 point 2): the Integration process opens no outbound connection and
imports no credential, Gitea, authorization-recorder or dispatch-transport module.

- **No client socket** (read from the syntax trees, the pattern of integrations/inference/tests/test_egress.py): the
  modules the server process loads (app.py and the modules it loads by file name, transitively) import no network
  client and call no connector; the one socket constructor is ``bind_listener``'s, which binds and listens and never
  connects. The lifecycle command (service.py) and the enroll command open no socket either. Since P-01.3 the server
  loads the capture (capture.py) and, through it, the shared repository-access module, whose remote operations
  (push, fetch) import a network client: those imports are pinned to the two functions that build a remote
  transport, and the capture calls only local repository reads and the commit (tests/test_capture.py, which also
  audits a whole capture: no socket, no process). Since P-04.4 the server loads the objective acceptance
  (acceptance.py) and, through it, the acceptance recorder (integrations/owner/acceptance_recorder.py with its two
  owner modules, owner_decision.py and delegated_decision.py, and the lineage resolvers, lineage_resolve.py, which
  name the effects store's two modules for the effect-receipt resolver; the attempt resolver, which names the
  dispatcher, is lineage_attempt.py, outside the census). The recorder's one network-module import, urllib.parse
  (a URL parser), is pinned to its two functions, without_userinfo and recordable_origin.
- **The import census** (the pattern of the input recorder's): a fresh interpreter loads app.py and builds the
  application; the repository files it has then loaded are exactly the server's modules (the four of U-01.3 and,
  since P-01.3, the capture's), none under integrations/credentials, integrations/gitea, integrations/dispatch or
  integrations/inference, and no authorization recorder; no network client module is loaded. Of
  integrations/owner only the acceptance recorder and its two modules may be loaded (OWNER_ALLOWED, exact names). The supervisor's too: a fresh interpreter loads service.py and selects the platform
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
# The server's modules: U-01.3's four, and since P-01.3 the capture's (capture.py, the integration store, the planning
# adapter's grammars and the shared repository-access module, the lineage span anchor, the intent-record checker).
# LIVE_SERVER_MODULES is what loading them loads; the planning adapter names the no-window helper, which it loads
# only to start a tool (the capture starts none).
LIVE_SERVER_MODULES = {'integrations/ownerhost/app.py', 'integrations/ownerhost/session.py',
                       'integrations/conversation/conversation_store.py', 'integrations/storecore/storecore.py',
                       'integrations/ownerhost/capture.py', 'integrations/store/integration_store.py',
                       'integrations/planning/planning_adapter.py', 'integrations/repository/repository_access.py',
                       'integrations/lineage/lineage.py', 'tools/check_intent_record.py',
                       # since P-04.4: the objective acceptance and the acceptance recorder
                       'integrations/ownerhost/acceptance.py', 'integrations/owner/acceptance_recorder.py',
                       'integrations/owner/owner_decision.py', 'integrations/owner/delegated_decision.py',
                       'integrations/lineage/lineage_resolve.py'}
# The effects store's two modules, named (never loaded on this path) by lineage_resolve.py for the effect-receipt
# resolver: admitted as exact entries (the engineering manager's ruling A on P-04.4; R2 forbids credential, Gitea,
# authorization-recorder and dispatch-transport modules), each checked to import no network client, call no connector
# and name no credential module.
EFFECTS_MODULES = {'integrations/effects/effects_store.py', 'integrations/effects/effects_custody.py'}
SERVER_MODULES = LIVE_SERVER_MODULES | {'integrations/platform/no_window.py'} | EFFECTS_MODULES
# The one server module with network-client imports, each pinned to the function that holds it: Dulwich's local
# modules (dulwich_modules), the remote transport (_transport_modules, _transport_class) and URL parsing (_origin,
# _remote). Any other import of a network module there fails this census.
REPOSITORY_ACCESS = 'integrations/repository/repository_access.py'
REPOSITORY_NETWORK_IMPORTS = {('dulwich', 'dulwich_modules'), ('dulwich.file', 'dulwich_modules'),
                              ('dulwich', '_transport_modules'), ('urllib.parse', '_origin'),
                              ('urllib.parse', '_remote'), ('urllib3', '_transport_class/Transport/__init__')}
# The acceptance recorder's one network-module import (P-04.4): the URL parser, in its two functions only.
ACCEPTANCE_RECORDER = 'integrations/owner/acceptance_recorder.py'
ACCEPTANCE_RECORDER_NETWORK_IMPORTS = {('urllib.parse', 'without_userinfo'), ('urllib.parse', 'recordable_origin')}
NETWORK_CLIENT_MODULES = ('dulwich.client', 'dulwich.protocol', 'urllib3', 'http.client', 'requests', 'httpx')
SUPERVISOR_MODULES = (SERVER_MODULES - EFFECTS_MODULES) | {
    'integrations/ownerhost/service.py', 'integrations/platform/platform_contract.py',
    'integrations/platform/platform_windows.py', 'integrations/platform/no_window.py', 'integrations/paths/aieh_paths.py'}
FORBIDDEN_PREFIXES = ('integrations/credentials/', 'integrations/gitea/', 'integrations/dispatch/',
                      'integrations/inference/')
# integrations/owner stays forbidden but for these exact files (P-04.4; the engineering manager's ruling 1): the
# authorization recorder, the dispatch-input commands and every other owner module are never loaded.
OWNER_PREFIX = 'integrations/owner/'
OWNER_ALLOWED = {'integrations/owner/acceptance_recorder.py', 'integrations/owner/owner_decision.py',
                 'integrations/owner/delegated_decision.py'}


def forbidden(names) -> list:
    """The names of NAMES under a forbidden prefix, or under integrations/owner/ and not in OWNER_ALLOWED."""
    return sorted(n for n in names if n.startswith(FORBIDDEN_PREFIXES)
                  or (n.startswith(OWNER_PREFIX) and n not in OWNER_ALLOWED))


def tree(path: Path):
    return ast.parse(path.read_text(encoding='utf-8'))


def loaded_sources(path: Path) -> set:
    """The repository modules PATH loads by file name: string constants naming a .py file that exists in the
    package, its sibling packages or a path joined in the call (REPO / 'integrations' / X / 'y.py')."""
    found = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith('.py'):
            for candidate in ([path.parent / node.value] + list(T.REPO.glob(f'integrations/*/{node.value}'))
                              + list(T.REPO.glob(f'tools/{node.value}'))):
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


def network_imports(path: Path) -> set:
    """{(imported network module, enclosing function path)} of PATH."""
    found = set()

    def visit(node, where):
        for child in ast.iter_child_nodes(node):
            inner = where + [child.name] if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                                ast.ClassDef)) else where
            names = ([alias.name for alias in child.names] if isinstance(child, ast.Import)
                     else [child.module or ''] if isinstance(child, ast.ImportFrom) else [])
            found.update((name, '/'.join(where)) for name in names if name.split('.')[0] in NETWORK_MODULES)
            visit(child, inner)
    visit(tree(path), [])
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
                if relative(path) == REPOSITORY_ACCESS:   # its remote transport only (P-01.3; see the docstring)
                    self.assertEqual(network_imports(path), REPOSITORY_NETWORK_IMPORTS)
                elif relative(path) == ACCEPTANCE_RECORDER:   # the URL parser in two functions only (P-04.4)
                    self.assertEqual(network_imports(path), ACCEPTANCE_RECORDER_NETWORK_IMPORTS)
                else:
                    self.assertEqual(imported(path) & set(NETWORK_MODULES), set())
                self.assertEqual(connector_calls(path) - DATABASE_CONNECTS, set())

    def test_the_effects_modules_are_exact_entries_with_no_client_connector_or_credential(self):
        """P-04.4 ruling A: the two effects modules are in the census by name, never by prefix, and neither
        imports a network client, calls a connector or names a credential, dispatch or inference module."""
        census = {relative(p): p for p in server_census()}
        self.assertEqual(sorted(n for n in census if n.startswith('integrations/effects/')), sorted(EFFECTS_MODULES))
        for name in sorted(EFFECTS_MODULES):
            with self.subTest(module=name):
                path = census[name]
                self.assertEqual(imported(path) & set(NETWORK_MODULES), set())
                self.assertEqual(connector_calls(path) - DATABASE_CONNECTS, set())
                self.assertEqual(forbidden(relative(p) for p in loaded_sources(path)), [])

    def test_no_server_module_is_forbidden_and_the_attempt_resolver_is_outside_the_census(self):
        """P-04.4: the census holds no credential, Gitea, dispatch or inference module, of integrations/owner only
        OWNER_ALLOWED, and not the lineage attempt resolver (which names the dispatcher)."""
        names = {relative(p) for p in server_census()}
        self.assertEqual(forbidden(names), [])
        self.assertEqual(sorted(n for n in names if n.startswith(OWNER_PREFIX)), sorted(OWNER_ALLOWED))
        self.assertNotIn('integrations/lineage/lineage_attempt.py', names)
        self.assertNotIn('integrations/owner/authorization_recorder.py', names)

    def test_only_the_acceptance_passes_a_session_binding_to_the_recorder(self):
        """P-04.4 (review note N2): the recorder admits the owner-ui channel only with a session-binding verifier, and
        the one production caller that passes one is the Integration process's acceptance: no other module under
        integrations/ or tools/ (tests aside) calls anything with session_binding=. The census sees the literal
        keyword only (a binding passed through **kwargs or positionally is not seen; accepted by the engineering
        manager)."""
        callers = set()
        sources = [p for p in T.REPO.glob('integrations/**/*.py') if 'tests' not in p.relative_to(T.REPO).parts]
        for path in sorted(sources + list(T.REPO.glob('tools/*.py'))):
            for node in ast.walk(tree(path)):
                if isinstance(node, ast.Call) and any(k.arg == 'session_binding' for k in node.keywords):
                    callers.add(relative(path))
        self.assertEqual(callers, {'integrations/ownerhost/acceptance.py'})
        acceptance = ast.unparse(tree(T.PACKAGE / 'acceptance.py'))
        self.assertIn('recorder.record(', acceptance)
        self.assertIn('session_binding=binding', acceptance)

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


class ExclusiveListener(unittest.TestCase):
    """While the server's listener holds 127.0.0.1:<port>, no other socket can bind that address and port, not even
    with SO_REUSEADDR. Measured on Windows 11 (2026-11-16): a listener bound without any option refuses that second
    bind too (WSAEACCES), so removing SO_EXCLUSIVEADDRUSE alone (the review's mutant M18) is equivalent on this host;
    a listener that shares its address (SO_REUSEADDR, as uvicorn's own bind sets) lets the second bind through, and
    this test fails for it. Another address of the port (0.0.0.0) is not excluded either way; up and the readiness
    record cover that (test_service)."""
    category = 'integration'

    @unittest.skipUnless(sys.platform == 'win32', 'SO_EXCLUSIVEADDRUSE is Windows\' (elsewhere the default refuses)')
    def test_a_reuse_bind_of_the_held_address_and_port_is_refused(self):
        import socket
        listener = T.A.bind_listener(0)
        self.addCleanup(listener.close)
        address, port = listener.getsockname()
        self.assertEqual(address, '127.0.0.1')
        other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(other.close)
        other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with self.assertRaises(OSError):
            other.bind(('127.0.0.1', port))


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
        self.assertEqual(loaded, LIVE_SERVER_MODULES)
        self.assertEqual(forbidden(loaded), [])
        packages = {part for f in files for part in f.parts[:-1]}     # a network client's package directory
        self.assertTrue(packages.isdisjoint({'urllib3', 'httpx', 'requests', 'aiohttp'}), 'a network client was loaded')
        self.assertFalse([f for f in files if f.parent.name == 'dulwich' and f.stem in ('client', 'protocol')],
                         'dulwich.client was loaded')

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
        self.assertEqual(forbidden(before), [])
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
