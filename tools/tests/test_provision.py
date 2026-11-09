"""Tests for the guest side of provisioning (F-04.1b; stdlib unittest; no guest, no network).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

- The seeded root step: the committed user-data template carries the script and the three
  units; the script is parsed (never run: it is Linux-only and needs root) and its paths,
  its step sequence and its daemon.json source are compared with the profile.
- create --provision's manifest, built from a synthetic lock staged by provision-fetch
  with fakes (the fixtures of test_provision_fetch.py).
- The provision operation against a fake SSH and SFTP that stand for the guest: bounds,
  refusals, the READY marker, the fetched RESULT.json and its checks.
- smoke --provision and the CLI wiring.
"""
from pathlib import Path
import ast
import base64
import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
PROFILE_NAME = 'strong-windows-qemu-whpx'
PROFILE_DIR = REPO / 'profiles' / PROFILE_NAME


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch_tests = _load('aieh_test_provision_fetch', REPO / 'tools' / 'tests' / 'test_provision_fetch.py')
guest = fetch_tests.guest          # one module instance shared with the fixtures
nocloud_seed = _load('aieh_nocloud_seed', REPO / 'tools' / 'nocloud_seed.py')
PROFILE = json.loads((PROFILE_DIR / 'profile.json').read_text(encoding='utf-8'))
PCONF = PROFILE['provisioning']
TEMPLATE = (REPO / 'profiles' / 'seed' / 'user-data.tmpl').read_text(encoding='utf-8')
ARCHIVE_TAG = 'ghcr.io/openhands/agent-server:i-was-a-digest'
SESSION_KEY = 'S' * 43                     # a synthetic session API key (fake guest only)


def write_file_entries(text):
    """{path: content} of the template's write_files block scalars (two-space list items,
    six-space content), read without a YAML parser."""
    out, path, body, in_body = {}, None, [], False
    for line in text.split('\n'):
        if line.startswith('  - path: '):
            if path:
                out[path] = '\n'.join(body)
            path, body, in_body = line[len('  - path: '):], [], False
        elif path and line.startswith('    content: |'):
            in_body = True
        elif path and in_body and (line.startswith('      ') or line == ''):
            body.append(line[6:])
        elif path and in_body:
            out[path], path, in_body = '\n'.join(body), None, False
    if path:
        out[path] = '\n'.join(body)
    return {k: v.rstrip('\n') + '\n' for k, v in out.items()}


FILES = write_file_entries(TEMPLATE)
SCRIPT = FILES['/usr/local/sbin/aieh-provision']


def script_constants():
    tree = ast.parse(SCRIPT)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def unit(name):
    lines = FILES[f'/etc/systemd/system/{name}'].splitlines()
    return [line for line in lines if '=' in line]


class SeededRootStep(unittest.TestCase):
    def test_template_carries_the_script_and_units(self):
        self.assertEqual(set(FILES), {
            '/etc/ssh/sshd_config.d/10-aieh.conf', '/etc/aieh/provision.json',
            '/usr/local/sbin/aieh-provision',
            '/etc/systemd/system/aieh-provision.service', '/etc/systemd/system/aieh-provision.path',
            '/etc/systemd/system/aieh-docker-facts.service',
            '/usr/local/sbin/aieh-agent-server-ready',
            '/etc/systemd/system/aieh-agent-server.service',
            '/etc/systemd/system/aieh-conversation-facts.path',
            '/etc/systemd/system/aieh-conversation-facts.service',
            '/usr/local/sbin/aieh-container-guard',
            '/etc/systemd/system/aieh-container-guard.service',
            '/etc/systemd/system/aieh-egress-route.path',
            '/etc/systemd/system/aieh-egress-route.service',
            '/etc/systemd/system/docker.service.d/10-aieh-container-guard.conf',
            '/usr/local/sbin/aieh-agent-server-keycheck'})
        self.assertIn('  - path: /etc/aieh/provision.json\n    owner: root:root\n'
                      "    permissions: '0600'\n    encoding: b64\n"
                      '    content: "{{provision_manifest}}"\n', TEMPLATE)
        self.assertNotIn('\t', TEMPLATE)
        TEMPLATE.encode('ascii')

    def test_script_parses_and_has_no_placeholder_braces(self):
        ast.parse(SCRIPT)
        self.assertTrue(SCRIPT.startswith('#!/usr/bin/python3\n'))
        self.assertNotIn('{{', SCRIPT)
        self.assertNotIn('}}', SCRIPT)
        # nothing in the root step reaches for the network or a repository
        for word in ('apt-get update', 'curl', 'wget', 'docker pull', 'urllib', 'socket.',
                     'trusted=yes', 'allow-unauthenticated', '--force', 'sudo', 'git '):
            self.assertNotIn(word, SCRIPT)

    def test_script_paths_equal_the_profile(self):
        c = script_constants()
        self.assertEqual(c['MANIFEST'], PCONF['root_step']['manifest'])
        self.assertEqual(c['UPLOAD'], PCONF['upload']['guest_dir'])
        self.assertEqual(c['READY'], PCONF['upload']['ready_marker'])
        self.assertEqual(c['STAGING'], PCONF['root_step']['staging'])
        self.assertEqual(c['RESULT_DIR'] + '/RESULT.json', PCONF['root_step']['result'])
        self.assertEqual(c['FACTS_DIR'] + '/docker-facts.json', PCONF['facts']['path'])
        self.assertEqual(c['FACTS_UNIT'], PCONF['facts']['service'])
        self.assertEqual(c['PATH_UNIT'], PCONF['root_step']['trigger'])
        self.assertEqual(c['MANIFEST_SCHEMA'], guest.PROVISION_MANIFEST_SCHEMA)
        self.assertEqual(c['RESULT_SCHEMA'], guest.PROVISION_RESULT_SCHEMA)
        self.assertEqual(c['FACTS_SCHEMA'], guest.MOBY_FACTS_SCHEMA)
        self.assertEqual(c['ROLES'], tuple(PCONF['upload']['roles']))
        self.assertEqual(c['DAEMON_JSON'], '/etc/docker/daemon.json')
        self.assertEqual(c['MOBY_SOCKET_DIRS'], guest.MOBY_SOCKET_DIRS)
        self.assertEqual(c['SYSCTL_FILE'], PCONF['moby']['sysctl']['path'])
        self.assertEqual(c['CONTAINERD_CONFIG'], PCONF['moby']['containerd_config']['path'])
        self.assertEqual(c['MOBY_PROCESSES'], guest.MOBY_PROCESSES)

    def test_script_step_sequence_equals_the_profile(self):
        tree = ast.parse(SCRIPT)
        steps = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                     and getattr(n.targets[0], 'id', None) == 'STEPS')
        names = [elt.elts[0].value for elt in steps.elts]
        self.assertEqual(names + ['facts', 'cleanup'], PCONF['root_step']['sequence'])
        # the trigger is disabled and RESULT.json is written in the finally block, last
        provision = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                         and n.name == 'provision')
        final = next(n for n in ast.walk(provision) if isinstance(n, ast.Try)).finalbody
        calls = [ast.unparse(n) for n in final]
        self.assertIn('disable_trigger()', calls[0])
        self.assertIn('write_json(RESULT, result, 420)', calls[-2])

    def test_units(self):
        service = unit('aieh-provision.service')
        path = unit('aieh-provision.path')
        facts = unit('aieh-docker-facts.service')
        for lines in (service, path):
            self.assertIn('ConditionFileNotEmpty=/etc/aieh/provision.json', lines)
            self.assertIn('ConditionPathExists=!/var/lib/aieh/provision/RESULT.json', lines)
        self.assertIn('ConditionFileNotEmpty=/etc/aieh/provision.json', facts)
        self.assertIn(f'PathExists={PCONF["upload"]["guest_dir"]}/{PCONF["upload"]["ready_marker"]}',
                      path)
        self.assertIn('Unit=aieh-provision.service', path)
        self.assertIn('Type=oneshot', service)
        self.assertIn('StandardOutput=journal+console', service)
        self.assertIn('ExecStart=/usr/bin/python3 -I /usr/local/sbin/aieh-provision provision',
                      service)
        self.assertIn('ExecStart=/usr/bin/python3 -I /usr/local/sbin/aieh-provision facts', facts)
        self.assertNotIn('[Install]', FILES['/etc/systemd/system/aieh-provision.service'])
        # the trigger is enabled by runcmd only when the manifest is not empty
        runcmd = [l for l in TEMPLATE.splitlines() if 'aieh-provision.path' in l and 'runcmd' not in l
                  and l.startswith('  - [sh')]
        self.assertEqual(len(runcmd), 1)
        self.assertIn('if [ -s /etc/aieh/provision.json ]; then', runcmd[0])

    def test_daemon_json_comes_from_the_manifest_and_has_no_tcp_socket(self):
        self.assertIn("manifest['docker']['daemon_json']", SCRIPT)
        self.assertNotIn('hosts', PCONF['moby']['daemon_json'])
        self.assertEqual(PCONF['moby']['daemon_json']['data-root'], PCONF['moby']['data_root'])


class AgentServerSeed(unittest.TestCase):
    """F-04.1 slice (c): the seeded Agent Server unit, its readiness wait and the root
    step's constants against provisioning.agent_server."""
    SERVER = PCONF['agent_server']

    def test_script_constants_equal_the_profile(self):
        c, s = script_constants(), self.SERVER
        self.assertEqual(c['AS_USER'], s['user']['name'])
        self.assertEqual(c['AS_SHELL'], s['user']['shell'])
        self.assertEqual(c['AS_BINARY'], s['binary']['path'])
        self.assertEqual(c['AS_CONFIG'], s['config']['path'])
        self.assertEqual(c['AS_SECRETS'], s['secrets']['env_file'])
        self.assertEqual(c['AS_SESSION_DIR'] + '/session.key', s['session_key']['guest_path'])
        self.assertEqual(c['AS_UNIT'], s['service']['unit'])
        self.assertEqual(c['AS_PROCESS'], s['listener']['process'])
        self.assertEqual(c['AS_SECRET_VARS'], tuple(s['secrets']['variables']))

    def test_unit(self):
        s = self.SERVER
        text = FILES[f"/etc/systemd/system/{s['service']['unit']}"]
        lines = unit(s['service']['unit'])
        self.assertIn(f"User={s['user']['name']}", lines)
        self.assertIn(f"ExecStart={s['binary']['path']} {' '.join(s['service']['argv'])}", lines)
        listener = s['listener']
        self.assertIn(f"ExecStartPost=/usr/bin/python3 -I {s['service']['ready']} "
                      f"{listener['address']} {listener['port']} 280", lines)
        self.assertIn(f"EnvironmentFile={s['secrets']['env_file']}", lines)
        env = {l.split('=', 1)[1].split('=', 1)[0]: l.split('=', 2)[2] for l in lines
               if l.startswith('Environment=')}
        self.assertEqual(env, s['environment'])
        for option in s['service']['hardening']['options']:
            self.assertIn(option, lines)
        self.assertIn('ConditionFileNotEmpty=/etc/aieh/provision.json', lines)
        self.assertIn('WantedBy=multi-user.target', lines)
        for word in ('OH_SECRET_KEY', 'OH_SESSION_API_KEYS', '0.0.0.0', 'SupplementaryGroups',
                     'AmbientCapabilities=CAP'):
            self.assertNotIn(word, text)
        facts = unit('aieh-docker-facts.service')
        self.assertIn(f"After=docker.service {s['service']['unit']}", facts)

    def test_the_server_requires_moby(self):
        """E-01.2.2 finding F-1: with Wants= a failing guard stopped Moby but not the server.
        Requires= and After= make the server's start fail (result dependency) whenever
        docker.service does not start; no BindsTo=, no Requisite=, no edge to the guard."""
        lines = unit(self.SERVER['service']['unit'])
        tokens = {key: [t for l in lines if l.startswith(key + '=') for t in l.split('=', 1)[1].split()]
                  for key in ('Requires', 'After', 'Wants', 'BindsTo', 'Requisite')}
        self.assertIn('docker.service', tokens['Requires'])
        self.assertIn('docker.service', tokens['After'])
        self.assertEqual(tokens['Wants'] + tokens['BindsTo'] + tokens['Requisite'], [])
        self.assertNotIn('aieh-container-guard.service', tokens['Requires'] + tokens['After'])

    def test_ready_wait_sends_no_credential(self):
        script = FILES[self.SERVER['service']['ready']]
        ast.parse(script)
        self.assertIn("conn.request('GET', '/ready')", script)
        self.assertNotIn('Session-API-Key', script)
        self.assertNotIn('environ', script)

    def test_root_step_prints_no_secret(self):
        tree = ast.parse(SCRIPT)
        prints = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and
                  getattr(n.func, 'id', None) == 'print']
        self.assertEqual(len(prints), 1)                   # only say()
        secrets_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                          and n.name == 'agent_server_secrets')
        returned = [ast.unparse(n.value) for n in ast.walk(secrets_fn) if isinstance(n, ast.Return)]
        self.assertEqual(len(returned), 1)
        self.assertNotIn('values', returned[0])           # fingerprints only
        self.assertIn('token_urlsafe(32)', SCRIPT)
        self.assertIn("write_secret_file(AS_SECRETS", SCRIPT)


def script_function(name):
    return next(n for n in ast.parse(SCRIPT).body if isinstance(n, ast.FunctionDef)
                and n.name == name)


def script_functions(*names):
    """The named functions of the seeded script, executed (only those, as text) in a
    namespace with the modules they use; the script itself is Linux- and root-only."""
    namespace = {'json': json, 're': re, 'os': os, 'hashlib': hashlib}
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name):
            try:
                exec(compile(ast.Module([node], []), 'seed', 'exec'), namespace)
            except Exception:
                pass
    for name in names:
        exec(compile(ast.Module([script_function(name)], []), 'seed', 'exec'), namespace)
    return namespace


class ConversationFactsSeed(unittest.TestCase):
    """F-04.2: the on-demand conversation facts reporter and its units against
    provisioning.agent_server.conversations.facts, with the Overseer's limits: an agent
    trigger with no parameters (its existence is the only input), no container command but
    docker ps and docker container inspect, a bounded rate, and no secret value written."""
    CONV = PCONF['agent_server']['conversations']
    FACTS = CONV['facts']

    def test_constants_equal_the_profile(self):
        c = script_constants()
        self.assertEqual(c['REQUEST_DIR'] + '/conversation-facts', self.FACTS['request'])
        self.assertEqual(c['FACTS_DIR'] + '/conversation-facts.json', self.FACTS['report'])
        self.assertIn("REQUEST = REQUEST_DIR + '/conversation-facts'", SCRIPT)
        self.assertIn("CONV_FACTS = FACTS_DIR + '/conversation-facts.json'", SCRIPT)
        self.assertEqual(c['CONV_FACTS_UNIT'], self.FACTS['service'])
        self.assertEqual(c['CONV_PATH_UNIT'], self.FACTS['path_unit'])
        self.assertEqual(c['CONV_FACTS_SCHEMA'], guest.CONVERSATION_FACTS_SCHEMA)
        self.assertEqual(c['OWNER_LABEL'], self.CONV['owner_label'])
        self.assertEqual(c['AS_PERSISTENCE'],
                         PCONF['agent_server']['environment']['OH_PERSISTENCE_DIR'])
        request_dir = [d for d in PROFILE['guest_storage']['directories']
                       if d['role'] == 'facts-request']
        self.assertEqual([d['path'] for d in request_dir], [c['REQUEST_DIR']])
        self.assertEqual((request_dir[0]['owner'], request_dir[0]['group'], request_dir[0]['mode']),
                         ('root', 'agent', '730'))

    def test_units(self):
        path = unit(self.FACTS['path_unit'])
        service = unit(self.FACTS['service'])
        rate = self.FACTS['rate']
        self.assertIn(f"PathExists={self.FACTS['request']}", path)
        self.assertIn(f"Unit={self.FACTS['service']}", path)
        self.assertIn(f"TriggerLimitIntervalSec={rate['interval_s']}", path)
        self.assertIn(f"TriggerLimitBurst={rate['burst']}", path)
        self.assertIn(f"StartLimitIntervalSec={rate['interval_s']}", service)
        self.assertIn(f"StartLimitBurst={rate['burst']}", service)
        self.assertIn('ExecStart=/usr/bin/python3 -I /usr/local/sbin/aieh-provision '
                      'conversation-facts', service)
        self.assertIn('Type=oneshot', service)
        for option in ('NoNewPrivileges=yes', 'ProtectSystem=strict', 'PrivateTmp=yes',
                       'IPAddressDeny=any', 'RuntimeDirectory=aieh',
                       'ReadWritePaths=-/var/lib/aieh/facts-request'):
            self.assertIn(option, service)
        for lines in (path, service):
            self.assertIn('ConditionFileNotEmpty=/etc/aieh/provision.json', lines)
        # the unit passes nothing from the request: ExecStart has no specifier or variable
        exec_start = next(l for l in service if l.startswith('ExecStart='))
        self.assertNotRegex(exec_start, r'[%$]')
        self.assertNotIn('[Install]', FILES[f"/etc/systemd/system/{self.FACTS['service']}"])

    def test_the_request_is_only_removed(self):
        fn = script_function('conversation_facts')
        uses = [n for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == 'REQUEST']
        self.assertEqual(len(uses), 1)
        call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call) and
                    any(isinstance(a, ast.Name) and a.id == 'REQUEST' for a in n.args))
        self.assertEqual(ast.unparse(call.func), 'os.unlink')
        for name in ('REQUEST', 'REQUEST_DIR'):
            for other in ('container_view', 'container_files', 'tree_inventory',
                          'event_summaries', 'conversation_storage', 'listener_facts'):
                self.assertNotIn(name, ast.unparse(script_function(other)), (name, other))

    def test_container_commands_are_ps_and_inspect_only(self):
        source = '\n'.join(ast.unparse(script_function(n)) for n in (
            'conversation_facts', 'container_view', 'container_files', 'listener_facts',
            'conversation_storage', 'tree_inventory', 'event_summaries'))
        docker = re.findall(r"docker_json\(\[('[^']+')(?:, ('[^']+'))?", source)
        self.assertEqual(sorted({d[0] for d in docker}), ["'container'", "'ps'"])
        self.assertIn("['container', 'inspect']", source)
        self.assertIn("run(['docker', 'ps', '--all', '--quiet', '--no-trunc']", source)
        for word in ('exec', "'rm'", "'stop'", "'kill'", "'run'", "'logs'", "'cp'", 'subprocess'):
            self.assertNotIn(f"'docker', {word}", source)
            self.assertNotIn(f"docker_json([{word}", source)

    def test_container_environment_is_reported_by_name_and_redacted(self):
        ns = script_functions('container_view', 'container_secret_values', 'redact')
        secret, session = 'S' * 43, 'T' * 43
        inspected = {'Id': 'f' * 64, 'Image': 'sha256:' + 'e' * 64,
                     'Config': {'User': '999:989', 'Env': [
                         f'OH_SECRET_KEY={secret}', f'OH_SESSION_API_KEYS_0={session}',
                         'OH_ENABLE_BROWSER=0', 'PATH=/usr/bin', 'LMNR_PROJECT_API_KEY=short']},
                     'HostConfig': {'CapDrop': ['ALL']}, 'Mounts': [], 'NetworkSettings': {},
                     'State': {'Running': True}}
        view = ns['container_view'](inspected)
        text = json.dumps(view)
        self.assertNotIn(secret, text)
        self.assertNotIn(session, text)
        self.assertEqual(view['Config']['EnvNames'], ['LMNR_PROJECT_API_KEY', 'OH_ENABLE_BROWSER',
                                                      'OH_SECRET_KEY', 'OH_SESSION_API_KEYS_0',
                                                      'PATH'])
        values = ns['container_secret_values'](inspected)
        self.assertEqual(sorted(values.values()), sorted([secret, session]))   # short ones skipped
        log = json.dumps({'log': [f'server started with key {session}']})
        redacted, counts = ns['redact'](log, values)
        self.assertNotIn(session, redacted)
        self.assertEqual(sum(counts.values()), 1)
        json.loads(redacted)

    def test_step_creates_the_request_directory_and_enables_the_path_unit(self):
        source = ast.unparse(script_function('enable_conversation_facts'))
        self.assertIn('os.mkdir(REQUEST_DIR, 472)', source)            # 0o730
        self.assertIn('os.chown(REQUEST_DIR, 0, agent_gid', source)
        self.assertIn("['systemctl', 'enable', '--now', CONV_PATH_UNIT]", source)
        self.assertIn("data.get('containers') != []", source)


class AdmissionSeed(unittest.TestCase):
    """S-01.3.1: the seeded container guard, its unit and docker.service drop-in, the key
    check before the Agent Server starts, and the root step's admission step and facts,
    against provisioning.agent_server.admission."""
    ADM = PCONF['agent_server']['admission']
    GUARD = ADM['network']['guard']
    EGRESS = ADM['network']['egress_guard']

    def guard_module(self):
        """The guard script's definitions, executed (not its main) in a fresh namespace."""
        namespace = {'__name__': 'aieh_guard_test'}
        exec(compile(FILES[self.GUARD['script']], 'guard', 'exec'), namespace)
        return namespace

    def keycheck_module(self):
        namespace = {'__name__': 'aieh_keycheck_test'}
        exec(compile(FILES[self.ADM['session_key']['start_check']], 'keycheck', 'exec'), namespace)
        return namespace

    def test_guard_constants_equal_the_profile(self):
        g = self.guard_module()
        self.assertEqual(g['CHAIN'], self.GUARD['chain'])
        self.assertEqual(list(g['INTERFACES']), self.GUARD['interfaces'])
        self.assertEqual(g['LOG_PREFIX'], self.GUARD['log_prefix'])
        self.assertEqual(list(g['TOOLS']), self.GUARD['families'])
        self.assertEqual(list(g['RULES']), self.GUARD['rules'])
        # S-01.4: the egress guard of the same script
        self.assertEqual(g['EGRESS_CHAIN'], self.EGRESS['chain'])
        self.assertEqual(g['EGRESS_HOOK'], self.EGRESS['hook'])
        self.assertEqual(g['EGRESS_LOG_PREFIX'], self.EGRESS['log_prefix'])
        self.assertEqual(list(g['EGRESS_RULES']), self.EGRESS['rules'])
        self.assertEqual(list(g['EGRESS_ALLOWLIST']), self.EGRESS['allowlist'])
        self.assertEqual(list(g['INTERFACES']), self.EGRESS['interfaces'])
        self.assertEqual(g['egress_hook_rules'](),
                         [f"-A {self.EGRESS['hook']} {r}" for r in self.EGRESS['hook_rules']])
        self.assertEqual(self.EGRESS['script'], self.GUARD['script'])
        self.assertEqual(self.EGRESS['unit'], self.GUARD['unit'])
        c = script_constants()
        self.assertEqual(c['GUARD'], self.GUARD['script'])
        self.assertEqual(c['GUARD_UNIT'], self.GUARD['unit'])
        self.assertEqual(c['GUARD_CHAIN'], self.GUARD['chain'])
        self.assertEqual(c['GUARD_LOG_PREFIX'], self.GUARD['log_prefix'])
        self.assertEqual(list(c['GUARD_TOOLS']), self.GUARD['families'])
        self.assertEqual(c['GUARD_DROPIN'], self.GUARD['docker_dropin'])
        self.assertEqual(c['KEYCHECK'], self.ADM['session_key']['start_check'])
        self.assertEqual(c['EGRESS_CHAIN'], self.EGRESS['chain'])
        self.assertEqual(c['EGRESS_HOOK'], self.EGRESS['hook'])
        self.assertEqual(c['EGRESS_LOG_PREFIX'], self.EGRESS['log_prefix'])

    def test_guard_units(self):
        lines = unit(self.GUARD['unit'])
        self.assertIn('Before=docker.service', lines)
        self.assertIn('DefaultDependencies=no', lines)
        self.assertIn('Type=oneshot', lines)
        self.assertIn('RemainAfterExit=yes', lines)
        self.assertIn(f"ExecStart=/usr/bin/python3 -I {self.GUARD['script']}", lines)
        self.assertIn('ConditionFileNotEmpty=/etc/aieh/provision.json', lines)
        dropin = [line for line in FILES[self.GUARD['docker_dropin']].splitlines() if '=' in line]
        self.assertEqual(dropin, [f"Requires={self.GUARD['unit']}", f"After={self.GUARD['unit']}"])
        self.assertIn(f"  - path: {self.GUARD['script']}\n    owner: root:root\n"
                      "    permissions: '0755'\n", TEMPLATE)

    class FakeTables:
        """A per-family iptables of the filter table (-L, -N, -F, -A, -I, -D, -C, -S), enough
        for the guard script and for what Moby 26.1 does to DOCKER-USER and FORWARD at its
        start (create the chain if absent, add -j RETURN unless present, re-insert FORWARD's
        jump at the top)."""
        BUILTIN = ('INPUT', 'FORWARD', 'OUTPUT')

        def __init__(self):
            self.chains = {}                   # tool -> {chain: [rule text]}
            self.calls = []

        def table(self, tool):
            return self.chains.setdefault(tool, {c: [] for c in self.BUILTIN})

        @staticmethod
        def text(args):
            return ' '.join(f'"{x}"' if ' ' in x else x for x in args)

        def run(self, argv):
            self.calls.append(argv)
            tool = argv[0]
            args = [a for a in argv[1:] if a not in ('-w', '-n')]
            op, name, rest = args[0], (args[1] if len(args) > 1 else None), args[2:]
            chains = self.table(tool)
            if op == '-L':
                return (0 if name in chains else 1), '', ''
            if op == '-N':
                if name in chains:
                    return 1, '', 'Chain already exists.'
                chains[name] = []
                return 0, '', ''
            if name not in chains:
                return 1, '', f'No chain/target/match by that name ({name})'
            if op == '-F':
                chains[name] = []
            elif op == '-A':
                chains[name].append(self.text(rest))
            elif op == '-I':
                chains[name].insert(int(rest[0]) - 1, self.text(rest[1:]))
            elif op in ('-D', '-C'):
                rule = self.text(rest)
                if rule not in chains[name]:
                    return 1, '', 'Bad rule (does a matching rule exist in that chain?).'
                if op == '-D':
                    chains[name].remove(rule)
            elif op == '-S':
                head = f'-P {name} ACCEPT' if name in self.BUILTIN else f'-N {name}'
                return 0, head + '\n' + ''.join(f'-A {name} {r}\n' for r in chains[name]), ''
            return 0, '', ''

        def dockerd_starts(self, tool='iptables'):
            """Moby 26.1's DOCKER-USER handling at start (libnetwork, iptables on)."""
            chains = self.table(tool)
            chains.setdefault('DOCKER-USER', [])
            if '-j RETURN' not in chains['DOCKER-USER']:
                chains['DOCKER-USER'].append('-j RETURN')
            if '-j DOCKER-USER' in chains['FORWARD']:
                chains['FORWARD'].remove('-j DOCKER-USER')
            chains['FORWARD'].insert(0, '-j DOCKER-USER')
            chains.setdefault('DOCKER', [])
            chains['FORWARD'][1:1] = ['-j DOCKER-ISOLATION-STAGE-1',
                                      '-o docker0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT',
                                      '-i docker0 -o docker0 -j DROP']

    def test_guard_installs_and_verifies_both_families(self):
        g = self.guard_module()
        tables = self.FakeTables()
        g['run'] = tables.run
        with mock.patch('builtins.print') as printed:
            self.assertEqual(g['main']([]), 0)
        out = json.loads(printed.call_args[0][0])
        self.assertTrue(out['ok'])
        self.assertTrue(out['egress_ok'])
        self.assertEqual(set(out['families']), {'iptables', 'ip6tables'})
        added = [c for c in tables.calls if c[2] == '-A' and c[3] == g['CHAIN']]
        self.assertEqual(len(added), 2 * len(self.GUARD['rules']))
        self.assertIn(['iptables', '-w', '-A', g['CHAIN'], '-m', 'limit', '--limit', '10/min',
                       '--limit-burst', '20', '-j', 'LOG', '--log-prefix',
                       'aieh-container-guard: '], added)
        # the egress guard: DOCKER-USER created (no Moby yet), its hooks and RETURN, its chain
        # with the declared rules, and FORWARD's first rule the jump to DOCKER-USER
        for tool in ('iptables', 'ip6tables'):
            chains = tables.table(tool)
            self.assertEqual([f"-A {self.EGRESS['hook']} {r}" for r in self.EGRESS['hook_rules']],
                             [f"-A DOCKER-USER {r}" for r in chains['DOCKER-USER']])
            self.assertEqual(chains['FORWARD'], ['-j DOCKER-USER'])
            self.assertEqual(len(chains[self.EGRESS['chain']]), len(self.EGRESS['rules']))
        self.assertIn(['ip6tables', '-w', '-A', self.EGRESS['chain'], '-m', 'limit', '--limit',
                       '10/min', '--limit-burst', '20', '-j', 'LOG', '--log-prefix',
                       'aieh-egress-guard: '], tables.calls)
        self.assertIn(['iptables', '-w', '-N', 'DOCKER-USER'], tables.calls)
        # Moby's start changes nothing the check looks at: the rules survive it
        before = copy.deepcopy(tables.chains['iptables']['DOCKER-USER'])
        tables.dockerd_starts()
        self.assertEqual(tables.chains['iptables']['DOCKER-USER'], before)
        self.assertTrue(g['observe_egress']('iptables')['ok'])
        # a rerun (the unit restarted) leaves exactly one jump and the same chains
        with mock.patch('builtins.print') as printed:
            self.assertEqual(g['main']([]), 0)
        self.assertEqual(tables.chains['iptables']['FORWARD'].count('-j DOCKER-USER'), 1)
        self.assertEqual(tables.chains['iptables']['DOCKER-USER'], before)
        # a missing rule, an extra INPUT jump or a jump below another rule is not ok
        lines = {'iptables': [f"-A {g['CHAIN']} {r}" for r in self.GUARD['rules']]}

        def observed(chain_lines, input_lines):
            g['run'] = lambda argv: (0, '\n'.join(chain_lines if argv[3] == g['CHAIN']
                                                   else input_lines) + '\n', '')
            return g['observe']('iptables')['ok']
        jumps = [f"-A INPUT -i {i} -j {g['CHAIN']}" for i in reversed(self.GUARD['interfaces'])]
        want = lines['iptables'][:3] + [lines['iptables'][3] + ' --reject-with icmp-port-unreachable']
        self.assertTrue(observed(want, ['-P INPUT ACCEPT'] + jumps))
        self.assertFalse(observed(want[:3], ['-P INPUT ACCEPT'] + jumps))
        self.assertFalse(observed(want, ['-P INPUT ACCEPT', '-A INPUT -j ACCEPT'] + jumps))
        self.assertFalse(observed(want, ['-P INPUT ACCEPT'] + jumps[:1]))

    def test_egress_check_refuses_each_loosening(self):
        g = self.guard_module()
        chain = [f"-A {self.EGRESS['chain']} {r}" for r in self.EGRESS['rules']]
        chain[-1] += ' --reject-with icmp-port-unreachable'      # as iptables -S prints it
        hook = [f"-A DOCKER-USER {r}" for r in self.EGRESS['hook_rules']]
        forward = ['-P FORWARD DROP', '-A FORWARD -j DOCKER-USER',
                   '-A FORWARD -j DOCKER-ISOLATION-STAGE-1']

        def observed(chain_lines, hook_lines, forward_lines):
            listing = {self.EGRESS['chain']: chain_lines, 'DOCKER-USER': hook_lines,
                       'FORWARD': forward_lines}
            g['run'] = lambda argv: (0, '\n'.join(listing[argv[3]]) + '\n', '')
            return g['observe_egress']('iptables')['ok']
        self.assertTrue(observed(chain, hook, forward))
        self.assertFalse(observed(chain[:3], hook, forward))                    # a rule missing
        self.assertFalse(observed(chain[:1] + ['-A AIEH-EGRESS-GUARD -j RETURN'] + chain[1:],
                                  hook, forward))                               # an allow added
        self.assertFalse(observed(chain, hook[:1] + hook[2:], forward))        # a bridge unhooked
        self.assertFalse(observed(chain, ['-A DOCKER-USER -j RETURN'] + hook, forward))
        self.assertFalse(observed(chain, hook, ['-P FORWARD DROP', '-A FORWARD -j ACCEPT',
                                                '-A FORWARD -j DOCKER-USER']))  # not first
        self.assertFalse(observed(chain, hook, forward + ['-A FORWARD -j DOCKER-USER']))
        g['run'] = lambda argv: (1, '', 'iptables: No chain/target/match by that name.')
        self.assertFalse(g['observe_egress']('ip6tables')['ok'])

    def test_guard_failure_is_reported_and_nonzero(self):
        g = self.guard_module()
        g['run'] = lambda argv: (4, '', 'iptables: not available')
        with mock.patch('builtins.print') as printed:
            self.assertEqual(g['main']([]), 1)
        out = json.loads(printed.call_args[0][0])
        self.assertFalse(out['ok'])
        self.assertIn('exited 4', out['error'])

    def test_keycheck_refuses_without_a_valid_key(self):
        problems = self.keycheck_module()['problems']
        a, b = 'A' * 43, 'B' * 43
        self.assertEqual(problems({'OH_SESSION_API_KEYS_0': a, 'OH_SECRET_KEY': b}), [])
        for env in ({}, {'OH_SESSION_API_KEYS_0': '', 'OH_SECRET_KEY': b},
                    {'OH_SESSION_API_KEYS_0': 'short', 'OH_SECRET_KEY': b},
                    {'OH_SESSION_API_KEYS_0': a},
                    {'OH_SESSION_API_KEYS_0': a, 'OH_SECRET_KEY': a},
                    {'OH_SESSION_API_KEYS_0': a, 'OH_SECRET_KEY': b, 'OH_SESSION_API_KEYS_1': b},
                    {'OH_SESSION_API_KEYS_0': a, 'OH_SECRET_KEY': b, 'SESSION_API_KEY': a}):
            found = problems(env)
            self.assertTrue(found, env)
            for value in env.values():                       # names only, never a value
                if value:
                    self.assertFalse(any(value in p for p in found))

    def test_agent_server_starts_only_after_the_key_check(self):
        lines = unit(PCONF['agent_server']['service']['unit'])
        pre = f"ExecStartPre=/usr/bin/python3 -I {self.ADM['session_key']['start_check']}"
        self.assertIn(pre, lines)
        self.assertLess(lines.index(pre), next(i for i, l in enumerate(lines)
                                               if l.startswith('ExecStart=')))

    def test_root_step_admission_checks_everything_declared(self):
        fn = ast.unparse(script_function('check_admission'))
        for word in ("'active'", "'ok'", 'docker_requires_guard', 'docker_after_guard',
                     "bridge_enable_icc'] != 'false'", "'enable', GUARD_UNIT",
                     "get('egress_ok') is not True"):
            self.assertIn(word, fn)
        facts = ast.unparse(script_function('admission_facts'))
        for word in ("'check'", "'network', 'inspect', 'bridge'", 'com.docker.network.bridge.enable_icc',
                     "('Requires', 'After')", 'ExecStartPre', "'-u', GUARD_UNIT",
                     "'guard_install'", 'ExecMainExitTimestampMonotonic',
                     'ExecMainStartTimestampMonotonic'):
            self.assertIn(word, facts)
        counters = ast.unparse(script_function('admission_counters'))
        for word in ("'-v', '-x', '-L', GUARD_CHAIN", "'journalctl', '-k', '-b'",
                     "'HTTPException 401 on '", "'-v', '-x', '-L', EGRESS_CHAIN",
                     "'-g', EGRESS_LOG_PREFIX", "out['egress'] = egress"):
            self.assertIn(word, counters)
        self.assertIn("data['admission'] = admission_facts()", SCRIPT)
        self.assertIn("'admission': admission_counters(),", SCRIPT)


class EgressRouteSeed(unittest.TestCase):
    """S-01.4 fix-forward: the seeded route-present falsification unit. Only a falsification
    guest enables it; root always deletes the temporary default route it adds, and refuses
    without the manifest flag or when a default route exists already."""
    FALS = PCONF['agent_server']['admission']['network']['egress_guard']['falsification']
    ROUTES = ['10.0.2.0/24 dev enp0s4 proto kernel scope link src 10.0.2.15',
              '172.17.0.0/16 dev docker0 proto kernel scope link src 172.17.0.1']

    def test_constants_equal_the_profile_and_the_tool(self):
        c = script_constants()
        self.assertEqual(c['EGRESS_ROUTE_REQUEST'], self.FALS['request'])
        self.assertEqual(c['EGRESS_ROUTE_OFF'], self.FALS['off_request'])
        self.assertEqual(c['EGRESS_ROUTE_REPORT'], self.FALS['report'])
        self.assertEqual(c['EGRESS_ROUTE_GATEWAY'], self.FALS['gateway'])
        self.assertEqual(c['EGRESS_ROUTE_CEILING_S'], self.FALS['ceiling_s'])
        self.assertEqual(c['EGRESS_ROUTE_PATH_UNIT'], self.FALS['path_unit'])
        for name in ('EGRESS_ROUTE_REQUEST', 'EGRESS_ROUTE_OFF', 'EGRESS_ROUTE_REPORT',
                     'EGRESS_ROUTE_GATEWAY', 'EGRESS_ROUTE_CEILING_S'):
            self.assertEqual(getattr(guest, name), c[name], name)
        self.assertTrue(c['EGRESS_ROUTE_REQUEST'].startswith(c['REQUEST_DIR'] + '/'))

    def test_units(self):
        path = unit(self.FALS['path_unit'])
        self.assertIn(f"PathExists={self.FALS['request']}", path)
        self.assertIn(f"Unit={self.FALS['service']}", path)
        self.assertIn('TriggerLimitBurst=5', path)
        service = unit(self.FALS['service'])
        self.assertIn('ExecStart=/usr/bin/python3 -I /usr/local/sbin/aieh-provision egress-route',
                      service)
        self.assertIn('Type=oneshot', service)
        self.assertIn('IPAddressDeny=any', service)
        self.assertIn('ReadWritePaths=-/var/lib/aieh/facts-request', service)
        self.assertIn("if argv == ['egress-route']:", SCRIPT)
        # enabled only for a falsification guest, by the root step
        fn = ast.unparse(script_function('enable_conversation_facts'))
        self.assertIn('if egress_route_enabled(manifest):', fn)
        self.assertIn("'enable', '--now', EGRESS_ROUTE_PATH_UNIT", fn)
        # never enabled elsewhere
        self.assertEqual(SCRIPT.count('EGRESS_ROUTE_PATH_UNIT]'), 1)

    def namespace(self, manifest, routes=None, fail_add=False, sleep_raises=False):
        ns = script_functions('egress_route', 'egress_route_enabled', 'ipv4_routes', 'tail')

        class Failed(Exception):
            pass
        state = {'routes': list(routes or self.ROUTES), 'calls': [], 'written': []}

        def run(argv, timeout, cwd=None):
            state['calls'].append(argv)
            if argv[:4] == ['ip', '-4', 'route', 'show']:
                return 0, '\n'.join(state['routes']) + '\n', ''
            if argv[:4] == ['ip', '-4', 'route', 'add']:
                if fail_add:
                    return 2, '', 'RTNETLINK answers: File exists'
                state['routes'].insert(0, 'default via 10.0.2.2 dev ' + argv[-1])
                return 0, '', ''
            if argv[:4] == ['ip', '-4', 'route', 'del']:
                state['routes'] = [r for r in state['routes'] if not r.startswith('default')]
                return 0, '', ''
            return 1, '', 'unexpected'

        def must(step, argv, timeout, cwd=None):
            rc, out, err = run(argv, timeout, cwd)
            if rc != 0:
                raise Failed(step + ': ' + err)
            return out

        class Clock:
            t = 0.0

            @staticmethod
            def monotonic():
                return Clock.t

            @staticmethod
            def sleep(s):
                if sleep_raises:
                    raise KeyboardInterrupt('interrupted')
                Clock.t += s
        fake_os = mock.MagicMock()
        fake_os.path.lexists.return_value = False
        fake_os.unlink.side_effect = FileNotFoundError
        ns.update(Failed=Failed, run=run, must=must, load_manifest=lambda: manifest,
                  write_json=lambda path, data, mode: state['written'].append(json.loads(
                      json.dumps(data))),
                  say=lambda text: None, now=lambda: 'T', time=Clock, os=fake_os,
                  FACTS_DIR='/run/aieh')
        return ns, state

    def test_adds_then_always_deletes_the_route(self):
        ns, state = self.namespace({'validation': {'egress_route': True}})
        self.assertEqual(ns['egress_route'](), 0)       # the ceiling ends the wait
        present, final = state['written']
        self.assertEqual(present['state'], 'present')
        self.assertIn('default via 10.0.2.2 dev enp0s4', present['present'])
        self.assertEqual(present['before'], self.ROUTES)
        self.assertEqual(final['state'], 'removed')
        self.assertEqual(final['after'], self.ROUTES)
        self.assertEqual(final['ended_by'], 'ceiling')
        self.assertIn(['ip', '-4', 'route', 'add', 'default', 'via', '10.0.2.2', 'dev', 'enp0s4'],
                      state['calls'])
        self.assertIn(['ip', '-4', 'route', 'del', 'default', 'via', '10.0.2.2', 'dev', 'enp0s4'],
                      state['calls'])

    def test_deletes_the_route_even_when_interrupted(self):
        ns, state = self.namespace({'validation': {'egress_route': True}}, sleep_raises=True)
        with self.assertRaises(KeyboardInterrupt):
            ns['egress_route']()
        self.assertFalse(any(r.startswith('default') for r in state['routes']))
        self.assertEqual(state['written'][-1]['state'], 'removed')

    def test_refusals(self):
        for manifest in ({}, {'validation': {'egress_route': 'yes'}}, {'validation': None}):
            ns, state = self.namespace(manifest)
            self.assertEqual(ns['egress_route'](), 1)
            self.assertEqual(state['written'][-1]['state'], 'refused')
            self.assertFalse([c for c in state['calls'] if c[:4] == ['ip', '-4', 'route', 'add']])
        ns, state = self.namespace({'validation': {'egress_route': True}},
                                   routes=['default via 10.0.2.2 dev enp0s4'] + self.ROUTES)
        self.assertEqual(ns['egress_route'](), 1)
        self.assertIn('a default route exists already', state['written'][-1]['error'])
        self.assertFalse([c for c in state['calls'] if c[:4] == ['ip', '-4', 'route', 'del']])
        ns, state = self.namespace({'validation': {'egress_route': True}}, fail_add=True)
        self.assertEqual(ns['egress_route'](), 1)
        self.assertEqual(state['written'][-1]['state'], 'refused')


class ManifestFixture(unittest.TestCase):
    """A temporary repository with a synthetic lock, staged by provision-fetch with fakes,
    whose image archive carries crane's placeholder tag as the real one does."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-provision-b-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = self.tmp / 'home'
        home.mkdir()
        patcher = mock.patch.dict(os.environ, {'USERPROFILE': str(home), 'HOME': str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        quiet = mock.patch.object(guest, 'log')
        quiet.start()
        self.addCleanup(quiet.stop)
        self.state = self.tmp / 'state'
        self.state.mkdir()
        self.fx = fetch_tests.Fixture()
        pdir = self.tmp / 'repo' / 'profiles' / PROFILE_NAME
        pdir.mkdir(parents=True)
        data = (json.dumps(self.fx.lock, indent=2) + '\n').encode()
        (pdir / 'provision.lock.json').write_bytes(data)
        profile = json.loads(json.dumps(PROFILE))
        profile['provider']['provision_lock'] = {
            'path': f'profiles/{PROFILE_NAME}/provision.lock.json',
            'sha256': hashlib.sha256(data).hexdigest()}
        (pdir / 'profile.json').write_text(json.dumps(profile, indent=2), encoding='utf-8')
        self.lock_sha = hashlib.sha256(data).hexdigest()
        archive = self.tagged_archive()
        guest.provision_fetch(self.ctx(), fetch_tests.FakeOpener(self.fx.urls),
                              fetch_tests.FakeCrane(self.fx, archive=archive))
        self.staged = self.state / 'provision' / self.lock_sha

    def tagged_archive(self):
        raw = self.fx.archive()
        import io
        import tarfile
        members = []
        with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
            for m in tf.getmembers():
                data = tf.extractfile(m).read()
                if m.name == 'manifest.json':
                    entry = json.loads(data)
                    entry[0]['RepoTags'] = [ARCHIVE_TAG]
                    data = json.dumps(entry).encode()
                members.append((m.name, data))
        return fetch_tests.tar_bytes(members)

    def ctx(self):
        return guest.Context(str(self.tmp / 'repo' / 'profiles' / PROFILE_NAME), str(self.state))


class Manifest(ManifestFixture):
    def test_manifest_from_the_verified_stage(self):
        built = guest.build_provision_manifest(self.ctx())
        m = built['manifest']
        self.assertEqual(m['schema'], guest.PROVISION_MANIFEST_SCHEMA)
        self.assertEqual(m['lock_sha256'], self.lock_sha)
        self.assertEqual([f['role'] for f in m['files']], ['deb', 'deb', 'image-archive',
                                                          'release-binary'])
        names = [f['name'] for f in m['files']]
        self.assertEqual(names, ['tini_0.19.0-3+b8_amd64.deb',
                                 'docker.io_26.1.5+dfsg1-9+deb13u1_amd64.deb',
                                 'agent-server.tar', 'agent-server-1.60.1-linux-x86_64'])
        for f in m['files']:                         # every digest is the staged file's own
            source = built['sources'][f['name']]
            self.assertEqual((source.stat().st_size, guest.sha256_file(source)),
                             (f['size'], f['sha256']))
            self.assertTrue(guest.inside(source, self.staged))
        self.assertNotIn('InRelease', json.dumps(m))  # the index files stay on the host
        self.assertEqual(m['image']['id'], self.fx.lock['image']['config_digest'])
        self.assertEqual(m['image']['archive_repo_tags'], [ARCHIVE_TAG])
        self.assertEqual(m['image']['local_tag'], PCONF['image']['local_tag'])
        self.assertEqual(m['docker']['daemon_json'], PCONF['moby']['daemon_json'])
        self.assertEqual(m['docker']['sysctl'], PCONF['moby']['sysctl']['content'])
        self.assertEqual(m['docker']['containerd_config'],
                         PCONF['moby']['containerd_config']['content'])
        server = m['agent_server']                   # F-04.1 slice (c): no secret, only config
        binary = next(f for f in m['files'] if f['role'] == 'release-binary')
        self.assertEqual(server['binary'], {'name': binary['name'], 'sha256': binary['sha256']})
        self.assertEqual(server['config'], PCONF['agent_server']['config']['content'])
        self.assertEqual([d['path'] for d in server['directories']][0], '/srv/scratch/openhands')
        self.assertEqual(server['listener'], {'address': '127.0.0.1', 'port': 8000})
        self.assertNotIn('OH_SECRET_KEY', json.dumps(server))
        self.assertEqual(built['record']['agent_server']['binary_sha256'], binary['sha256'])
        self.assertEqual(built['sha256'], hashlib.sha256(built['bytes']).hexdigest())
        self.assertEqual(built['record']['manifest_sha256'], built['sha256'])
        self.assertNotIn(str(self.state).replace('\\', '/'), built['bytes'].decode())
        # deterministic, and accepted by the seed generator
        self.assertEqual(guest.build_provision_manifest(self.ctx())['bytes'], built['bytes'])
        value = nocloud_seed.provision_manifest_value(built['bytes'])
        self.assertEqual(base64.b64decode(value), built['bytes'])

    def test_egress_falsification_marks_only_its_own_manifest(self):
        """S-01.4 fix-forward: create --provision --egress-falsification alone carries
        validation.egress_route; an ordinary provisioned manifest is unchanged by it."""
        plain = guest.build_provision_manifest(self.ctx())
        marked = guest.build_provision_manifest(self.ctx(), egress_falsification=True)
        self.assertNotIn('validation', plain['manifest'])
        self.assertIs(plain['record']['egress_falsification'], False)
        self.assertEqual(marked['manifest']['validation'],
                         {'egress_route': True, 'gateway': '10.0.2.2', 'ceiling_s': 300})
        self.assertIs(marked['record']['egress_falsification'], True)
        self.assertNotEqual(marked['sha256'], plain['sha256'])
        with self.assertRaises(guest.Refused):
            guest.create(self.ctx(), 'abc', egress_falsification=True)

    def test_a_changed_stage_is_refused(self):
        deb = self.staged / 'debs' / 'tini_0.19.0-3+b8_amd64.deb'
        deb.write_bytes(b'deb tinX')
        with self.assertRaises(guest.Refused) as caught:
            guest.build_provision_manifest(self.ctx())
        self.assertEqual(caught.exception.code, 'STAGED_MISMATCH')

    def test_no_stage_is_refused(self):
        shutil.rmtree(self.staged)
        with self.assertRaises(guest.Refused) as caught:
            guest.build_provision_manifest(self.ctx())
        self.assertIn('run provision-fetch', str(caught.exception))


class FakeGuest:
    """The guest as the provision operation sees it: SSH commands and SFTP batches act on
    a temporary directory; the READY marker runs a stand-in for the seeded root step."""

    def __init__(self, root, conf, outcome='provisioned', corrupt=None, armed='active',
                 published=None):
        self.root, self.conf, self.outcome, self.corrupt, self.armed = root, conf, outcome, corrupt, armed
        self.published = published
        self.calls = []

    def path(self, guest_path):
        return self.root / guest_path.lstrip('/')

    def ssh(self, profile, idir, port):
        fake = self

        class _Ssh:
            exe = 'ssh.exe'

            def run(self, command, user='agent', input_text=None, timeout=300):
                fake.calls.append(('ssh', command, input_text))
                return fake.handle(command, input_text)
        return _Ssh()

    def sftp(self, ssh):
        fake = self

        class _Sftp:
            def batch(self, commands, work_dir, timeout=600):
                fake.calls.append(('sftp', commands))
                for command in commands:
                    verb, *args = re.findall(r'"[^"]*"|\S+', command)
                    args = [a.strip('"') for a in args]
                    if verb == 'mkdir':
                        fake.path(args[0]).mkdir(parents=True)
                    elif verb == 'put':
                        shutil.copyfile(args[0], fake.path(args[1]))
                        if fake.corrupt and args[1].endswith(fake.corrupt):
                            fake.path(args[1]).write_bytes(b'corrupted')
                    elif verb == 'get':
                        shutil.copyfile(fake.path(args[0]), args[1])
                return {'rc': 0, 'commands': commands, 'stderr': ''}
        return _Sftp()

    def completed(self, rc, out=''):
        return subprocess.CompletedProcess([], rc, out, '')

    def handle(self, command, script):
        up, root = self.conf['upload'], self.conf['root_step']
        if command == ['bash', '-s'] and 'sha256sum' in script:
            names = re.findall(r"'([^']+)'", script.split('for f in ', 1)[1].split('; do', 1)[0])
            base = self.path(up['guest_dir'])
            out = [f'{n} {(base / n).stat().st_size}' for n in names]
            out += [f'{guest.sha256_file(base / n)}  {n}' for n in names]
            return self.completed(0, '\n'.join(out) + '\n')
        if command == ['bash', '-s']:
            lines = []
            for p in re.findall(r"p='([^']+)'", script):
                lines.append(f'{"present" if self.path(p).exists() else "absent"} {p}')
            return self.completed(0, '\n'.join(lines) + '\n')
        if command[:2] == ['systemctl', 'is-active']:
            return self.completed(0, self.armed + '\n')
        if command[:2] == ['bash', '-c'] and up['ready_marker'] in command[2]:
            ready = self.path(up['guest_dir']) / up['ready_marker']
            ready.touch()
            self.root_step()
            return self.completed(0)
        if command[:2] == ['python3', '-']:
            return self.completed(0 if self.path(root['result']).exists() else 5,
                                  'result present\n')
        raise AssertionError(f'unexpected guest command {command}')

    def root_step(self):
        """What the seeded step reports: the manifest digest, every file verified, the tag."""
        m = self.manifest
        ok = self.outcome == 'provisioned'
        result = {'schema': guest.PROVISION_RESULT_SCHEMA, 'result': self.outcome,
                  'failed_step': None if ok else 'verify', 'error': None if ok else 'mismatch',
                  'manifest': {'sha256': hashlib.sha256(self.manifest_bytes).hexdigest()},
                  'steps': [{'step': 'verify', 'ok': True, 'seconds': 1.0, 'detail': {'files': [
                      dict(f, match=True) for f in m['files']]}},
                            {'step': 'tag', 'ok': True, 'seconds': 0.1, 'detail': {'image': {
                                'Id': m['image']['id'], 'RepoTags': [m['image']['local_tag']]}}},
                            {'step': 'run', 'ok': True, 'seconds': 0.5, 'detail': {'rc': 0}}]
                  if ok else [], 'trigger': {'path_unit_file': 'absent'},
                  'upload_present': not ok, 'staging_present': not ok, 'seconds': 3.0}
        if ok:                                   # the Agent Server steps (F-04.1 slice (c))
            server = self.conf['agent_server']
            key = self.path(server['session_key']['guest_path'])
            key.parent.mkdir(parents=True, exist_ok=True)
            key.write_text(SESSION_KEY, encoding='ascii')
            published = SESSION_KEY if self.published is None else self.published
            result['steps'] += [
                {'step': 'agent-server-secrets', 'ok': True, 'seconds': 0.0, 'detail': {
                    'fingerprints': {'OH_SECRET_KEY': guest.secret_fingerprint('K' * 43),
                                     'OH_SESSION_API_KEYS_0': guest.secret_fingerprint(published)}}},
                {'step': 'agent-server-start', 'ok': True, 'seconds': 9.0, 'detail': {
                    'agent_server_listeners': [f"{server['listener']['address']}:"
                                               f"{server['listener']['port']}"]}}]
        target = self.path(self.conf['root_step']['result'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result), encoding='utf-8')


class ProvisionOperation(ManifestFixture):
    def setUp(self):
        super().setUp()
        self.built = guest.build_provision_manifest(self.ctx())
        self.idir = self.state / 'instances' / 'abc'
        self.idir.mkdir(parents=True)
        self.record = {'labels': PROFILE['labels'], 'ports': {'ssh': 40001, 'qmp': 40002},
                       'provisioning': dict(self.built['record'])}
        self.guest_root = self.tmp / 'guest'
        self.guest_root.mkdir()

    def run_provision(self, record=None, **fake_kw):
        fake = FakeGuest(self.guest_root, PCONF, **fake_kw)
        fake.manifest, fake.manifest_bytes = self.built['manifest'], self.built['bytes']
        with mock.patch.object(guest, 'running_instance',
                               return_value=(self.idir, record or self.record)), \
                mock.patch.object(guest, 'Ssh', fake.ssh), \
                mock.patch.object(guest, 'Sftp', fake.sftp):
            return guest.provision(self.ctx(), 'abc'), fake

    def refused(self, code, **kw):
        with self.assertRaises(guest.Refused) as caught:
            self.run_provision(**kw)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        return caught.exception

    def test_transfer_ready_wait_and_result(self):
        result, fake = self.run_provision()
        self.assertEqual(result['result'], 'provisioned', result['checks'])
        self.assertTrue(all(result['checks'].values()))
        self.assertEqual(guest.label_problems(result['labels'], PROFILE['labels']), [])
        uploaded = sorted(p.name for p in (self.guest_root / 'srv/scratch/agent/provision').iterdir())
        self.assertEqual(uploaded, sorted([f['name'] for f in self.built['manifest']['files']] +
                                          ['READY']))
        puts = [c for c in fake.calls if c[0] == 'sftp'][0][1]
        self.assertEqual(puts[0], 'mkdir "/srv/scratch/agent/provision"')
        self.assertEqual(len(puts), 1 + len(self.built['manifest']['files']))
        order = [c[1][:2] for c in fake.calls if c[0] == 'ssh']
        self.assertEqual(order[-2:], [['bash', '-c'], ['python3', '-']])  # READY, then the wait
        fetched = Path(result['result_file'])
        self.assertTrue(guest.inside(fetched, self.idir / 'provision'))
        self.assertEqual(json.loads(fetched.read_text(encoding='utf-8'))['result'], 'provisioned')
        records = list((self.idir / 'records').glob('provision-*.json'))
        self.assertEqual(len(records), 1)
        for key in ('upload_s', 'guest_check_s', 'root_step_s', 'wait_s', 'total_s'):
            self.assertIn(key, result['timings'])
        # profiles P5 (amended): the session key is exported into the instance directory
        # only, by SFTP as agent; no record carries it
        custody = self.idir / 'agent-server' / 'session.key'
        self.assertEqual(custody.read_text(encoding='ascii'), SESSION_KEY)
        self.assertEqual(result['session_key'], {'host_path': guest.posix(custody),
                                                 'fetched': True, 'fingerprint_matches': True})
        gets = [c[1] for c in fake.calls if c[0] == 'sftp' and c[1][0].startswith('get ')]
        self.assertEqual(gets[-1][0].split()[1].strip('"'),
                         PCONF['agent_server']['session_key']['guest_path'])
        for path in self.idir.rglob('*.json'):
            self.assertNotIn(SESSION_KEY, path.read_text(encoding='utf-8'), path)

    def test_session_key_whose_fingerprint_differs_fails(self):
        error = self.refused('PROVISION_FAILED', published='Z' * 43)
        self.assertFalse(error.detail['checks']['session_key_exported'])
        self.assertTrue(error.detail['session_key']['fetched'])

    def test_not_created_with_provision(self):
        record = dict(self.record)
        del record['provisioning']
        self.assertIn('not created with --provision', str(self.refused('REFUSED', record=record)))

    def test_stage_differs_from_the_seeded_manifest(self):
        record = dict(self.record, provisioning=dict(self.record['provisioning'],
                                                     manifest_sha256='0' * 64))
        self.refused('STAGED_MISMATCH', record=record)

    def test_single_use_and_armed_trigger(self):
        (self.guest_root / 'var/lib/aieh/provision').mkdir(parents=True)
        (self.guest_root / 'var/lib/aieh/provision/RESULT.json').write_text('{}')
        self.refused('REFUSED')
        (self.guest_root / 'var/lib/aieh/provision/RESULT.json').unlink()
        self.refused('REFUSED', armed='inactive')

    def test_bounds(self):
        small = json.loads(json.dumps(PROFILE))
        small['provisioning']['upload']['max_bytes'] = 10
        with mock.patch.object(guest, 'provisioning_config', return_value=small['provisioning']):
            self.refused('BOUNDS')

    def test_corrupted_transfer_is_caught_before_ready(self):
        error = self.refused('HASH_MISMATCH', corrupt='agent-server.tar')
        self.assertEqual(error.detail['guest_check']['mismatched'], ['agent-server.tar'])
        self.assertFalse((self.guest_root / 'srv/scratch/agent/provision/READY').exists())

    def test_failed_root_step_is_reported_and_recorded(self):
        error = self.refused('PROVISION_FAILED', outcome='failed')
        self.assertIn("step 'verify'", str(error))
        self.assertEqual(error.detail['result'], 'failed')
        self.assertEqual(len(list((self.idir / 'records').glob('provision-*.json'))), 1)


class SmokeAndCli(unittest.TestCase):
    def test_smoke_runs_provision_after_create_and_recreate(self):
        src = (REPO / 'tools' / 'guest.py').read_text(encoding='utf-8')
        body = src[src.index('def smoke('):src.index('# ---------------------------------------------------------------- netprobe')]
        self.assertIn("run('provision', lambda: provision(ctx, name), provisioned)", body)
        self.assertIn("run('provision (after recreate)', lambda: provision(ctx, name), provisioned)",
                      body)
        self.assertLess(body.index("run('provision',"), body.index("do_inspect('A (after create)')"))
        self.assertLess(body.index("'provision (after recreate)'"),
                        body.index("do_inspect('C (after recreate)')"))

    def test_cli(self):
        tmp = Path(tempfile.mkdtemp(prefix='aieh-provision-cli-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        state = tmp / 'state'
        state.mkdir()
        env = {'USERPROFILE': str(tmp / 'h'), 'HOME': str(tmp / 'h')}
        base = ['--profile', str(PROFILE_DIR), '--state-dir', str(state), '--name', 'abc']
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(guest, 'create', return_value={'operation': 'create',
                                                                 'result': 'ready'}) as create, \
                mock.patch.object(guest, 'provision', return_value={'operation': 'provision',
                                                                    'result': 'provisioned'}) as prov, \
                mock.patch.object(guest, 'smoke', return_value={'operation': 'smoke',
                                                                'result': 'PASS'}) as smoke:
            self.assertEqual(guest.main(['create'] + base + ['--provision']), 0)
            self.assertIs(create.call_args.kwargs.get('provision'), True)
            self.assertEqual(guest.main(['create'] + base), 0)
            self.assertNotIn('provision', create.call_args.kwargs)
            self.assertEqual(guest.main(['provision'] + base), 0)
            self.assertEqual(prov.call_args.args[1], 'abc')
            self.assertEqual(guest.main(['smoke'] + base + ['--canaries', 'C', '--durable', 'D',
                                                            '--provision']), 0)
            self.assertIs(smoke.call_args.args[6], True)

    def test_validation_instances_are_never_provisioned(self):
        with self.assertRaises(guest.Refused):
            guest.create(None, 'abc', netprobe=object(), provision=True)


if __name__ == '__main__':
    unittest.main()
