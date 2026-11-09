"""Tests for the E-01.2.2 slice (b) drills (tools/guest.py drill, create --drill,
containment-probe --drill-defective-control; tools/guest_drill.py, the guest-side helper).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

stdlib unittest; no QEMU, no guest, no network. The guest side is replaced by fakes that keep
the state a drill acts on (units, stored files, an outer server that may act on them), so the
drills' own logic (sequence, verdicts, rollback checks) runs against both a guest that fails
closed and one that does not. The guest helper is loaded with a stand-in pwd module where the
host has none (Windows).
"""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO / 'profiles' / 'strong-windows-qemu-whpx'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guest = _load('guest', REPO / 'tools' / 'guest.py')
if 'pwd' not in sys.modules:
    try:
        import pwd  # noqa: F401
    except ImportError:
        sys.modules['pwd'] = types.ModuleType('pwd')
helper = _load('guest_drill', REPO / 'tools' / 'guest_drill.py')
tg = _load('test_guest_fixtures', REPO / 'tools' / 'tests' / 'test_guest.py')
nocloud_seed = _load('nocloud_seed', REPO / 'tools' / 'nocloud_seed.py')
PROFILE = json.loads((PROFILE_DIR / 'profile.json').read_text(encoding='utf-8'))
DRILL_RECORD = {'validation': {'mode': 'drill', 'plan_leaf': 'E-01.2.2 slice (b)'},
                'provisioning': {'image_id': tg.IMAGE_ID}, 'ports': {'ssh': 1, 'qmp': 2}}


# ---------------------------------------------------------------- the helper file


class HelperFile(unittest.TestCase):
    def test_ascii_lf_shebang_and_compiles(self):
        raw = guest.drill_script()
        self.assertTrue(raw.startswith(b'#!/usr/bin/python3\n'))
        compile(raw, 'guest_drill.py', 'exec')
        self.assertEqual(raw, (REPO / 'tools' / 'guest_drill.py').read_bytes())

    def test_checked_out_verbatim(self):
        """A clone with core.autocrlf=true would otherwise write CRLF, which the guest refuses."""
        rules = (REPO / 'tools' / '.gitattributes').read_text(encoding='utf-8').splitlines()
        self.assertIn('/guest_drill.py -text', rules)

    def test_drill_script_refuses_cr_non_ascii_and_a_missing_shebang(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tools' / 'guest_drill.py'
            path.parent.mkdir()
            for bad in (b'#!/usr/bin/python3\r\nx = 1\r\n', b'#!/usr/bin/python3\nx = "\xc3\xa9"\n',
                        b'x = 1\n'):
                path.write_bytes(bad)
                with self.assertRaises(guest.Refused):
                    guest.drill_script(tmp)

    def test_variants_and_actions_agree_with_the_host_side(self):
        self.assertEqual(set(helper.GUARD_VARIANTS), set(guest.DRILL_GUARD_VARIANTS))
        self.assertLessEqual(set(guest.DRILL_KEY_VARIANTS), set(helper.KEY_VARIANTS))
        self.assertEqual(set(helper.ACTIONS), {
            'observe', 'guard-break', 'guard-restore', 'key-break', 'key-restore',
            'server-restart', 'state-read', 'state-alter', 'state-snapshot', 'state-rollback',
            'state-discard', 'root-scan'})
        self.assertEqual((helper.REQUEST_DIR, helper.RESULTS), (guest.DRILL_REQUEST_DIR,
                                                               guest.DRILL_RESULTS))
        for text in helper.GUARD_VARIANTS.values():      # a drop-in, never the guard script itself
            self.assertIn('[Service]', text)
            self.assertNotIn('aieh-container-guard\n', text.replace('guard check', ''))

    def test_owner_patterns_agree_and_every_class_is_prefiltered(self):
        for cls, patterns in guest.OWNER_PATTERNS.items():
            self.assertEqual(helper.OWNER_PATTERNS[cls], patterns)
        self.assertEqual(set(helper.OWNER_PREFILTER), set(helper.OWNER_PATTERNS))
        text, _ = guest.control_samples('abc123')
        owner = {k: [re.compile(rx) for rx in v] for k, v in helper.OWNER_PATTERNS.items()}
        hits = {}
        helper.scan_data(text.encode(), 0, {}, {}, hits, {}, owner, 'control')
        self.assertEqual(sorted(hits), sorted(f'owner:{k}' for k in helper.OWNER_PATTERNS))


class HelperScan(unittest.TestCase):
    def test_values_cores_keys_and_patterns_counted_once_across_windows(self):
        secret = b'S' * 43
        core = b'0123456789abcdef0123456789abcdef'
        key_body = b'QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo='
        data = (b'x' * 5000 + secret + b'\n' + b'aieh-canary-env-' + core + b'\n' +
                b'-----BEGIN OPENSSH PRIVATE KEY-----\n' + key_body +
                b'\n-----END OPENSSH PRIVATE KEY-----\n' + b'ghp_' + b'a' * 36 + b'\n' + secret)
        cores = {hashlib.sha256(core).hexdigest(): 'canary:env'}
        owner = {k: [re.compile(rx) for rx in v] for k, v in helper.OWNER_PATTERNS.items()}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'f'
            path.write_bytes(data)
            hits, keys = {}, {}
            with mock.patch.object(helper, 'CHUNK', 1024), mock.patch.object(helper, 'OVERLAP', 256), \
                    mock.patch.object(helper.os, 'O_NOFOLLOW', 0, create=True), \
                    mock.patch.object(helper.os, 'O_NONBLOCK', 0, create=True):
                total = helper.scan_file(str(path), {'secret:x': secret}, cores, hits, keys, owner)
        self.assertEqual(total, len(data))
        self.assertEqual({k: {p: len(v) for p, v in w.items()} for k, w in hits.items()},
                         {'secret:x': {str(path): 2}, 'canary:env': {str(path): 1},
                          'owner:private-key-header': {str(path): 1},
                          'owner:git-host-token': {str(path): 1}})
        self.assertEqual([d for (_, d) in keys], [hashlib.sha256(key_body).hexdigest()])

    def test_a_random_hex_run_is_not_a_canary(self):
        hits = {}
        helper.scan_data(b'f' * 64 + b' ' + b'a' * 32, 0, {}, {'0' * 64: 'canary:x'}, hits, {}, {}, 'p')
        self.assertEqual(hits, {})

    def test_walk_pointer(self):
        doc = {'a': {'b': [1, {'c': 2}]}}
        parent, key = helper.walk_pointer(doc, ['a', 'b', 1, 'c'])
        self.assertEqual((parent, key), ({'c': 2}, 'c'))
        parent, key = helper.walk_pointer(doc, ['a', 'new'])
        self.assertEqual(key, 'new')
        for bad in ([], ['x', 'y'], ['a', 'b', 5], 'a'):
            with self.assertRaises(helper.Failed):
                helper.walk_pointer(doc, bad)

    def test_redact_counts_and_replaces_long_values_only(self):
        text, count = helper.redact('k=' + 'A' * 43 + ' k2=' + 'A' * 43 + ' short=abc', ['A' * 43, 'abc'])
        self.assertEqual(count, 2)
        self.assertNotIn('A' * 43, text)
        self.assertIn('short=abc', text)


# ---------------------------------------------------------------- seed, create, start


class DrillSeed(tg.TempState):
    def manifest(self):
        return json.dumps({'schema': nocloud_seed.MANIFEST_SCHEMA, 'files': []}).encode('ascii')

    def test_the_seed_is_the_provisioned_one_plus_the_helper_part(self):
        idir = self.state / 'instances' / 'abc'
        (idir / 'ssh').mkdir(parents=True)
        pub = idir / 'ssh' / 'id_ed25519.pub'
        pub.write_text('ssh-ed25519 ' + tg.ed25519_b64(b'\x01' * 32) + ' abc\n', encoding='ascii')
        script = guest.drill_script()
        manifest = self.manifest()
        seed = guest.drill_seed(PROFILE_DIR / 'profile.json', idir, 'abc', pub, script, manifest)
        image = (idir / 'seed.iso').read_bytes()
        self.assertEqual(seed['provision_manifest_sha256'], hashlib.sha256(manifest).hexdigest())
        self.assertIn(b'filename="aieh-drill.py"', image)
        self.assertIn(guest.DRILL_BOUNDARY.encode(), image)
        self.assertIn(script, image)
        self.assertIn('aieh-drill.py', seed['validation']['user_data'])
        self.assertEqual(seed['validation']['script_part_sha256'], hashlib.sha256(script).hexdigest())

    def test_netprobe_user_data_is_unchanged_by_the_generalization(self):
        data = guest.netprobe_user_data(b'#cloud-config\n', b'#!/usr/bin/python3\n')
        self.assertTrue(data.startswith(b'Content-Type: multipart/mixed; boundary="'
                                        + guest.NETPROBE_BOUNDARY.encode()))
        self.assertIn(b'filename="aieh-netprobe.py"', data)
        with self.assertRaisesRegex(guest.Refused, 'netprobe user-data'):
            guest.netprobe_user_data(b'a\r\n', b'b')

    def test_create_takes_drill_only_with_provision(self):
        with self.assertRaisesRegex(guest.Refused, '--drill'):
            guest.create(self.ctx(), 'abc', drill=True)
        with self.assertRaisesRegex(guest.Refused, '--drill'):
            guest.create(self.ctx(), 'abc', drill=True, provision=True,
                         netprobe=guest.NetprobeSession())
        self.assertFalse((self.state / 'instances').exists())

    def test_the_command_line_refuses_drill_without_provision(self):
        code = guest.main(['create', '--profile', str(PROFILE_DIR), '--state-dir', str(self.state),
                           '--name', 'abc', '--drill'])
        self.assertEqual(code, 1)

    def test_start_boots_a_drill_instance_again_but_never_a_netprobe_one(self):
        idir = self.state / 'instances' / 'abc'
        idir.mkdir(parents=True)
        for mode, refused in (('drill', False), ('netprobe', True)):
            (idir / 'launch.json').write_text(json.dumps({'schema': guest.LAUNCH_SCHEMA,
                                                          'validation': {'mode': mode}}))
            with mock.patch.object(guest, 'launch', side_effect=guest.Refused('LAUNCHED', 'x')):
                with self.assertRaises(guest.Refused) as caught:
                    guest.start(self.ctx(), 'abc')
            self.assertEqual(caught.exception.code, 'REFUSED' if refused else 'LAUNCHED')

    def test_a_drill_record_declares_no_forwarding(self):
        record = {'argv': ['-netdev', 'user,id=n,restrict=on'], 'validation': {'mode': 'drill'}}
        self.assertEqual(guest.check_forwarding(record), [])
        record['argv'][1] += ',guestfwd=tcp:10.0.2.100:7000-tcp:127.0.0.1:9'
        with self.assertRaisesRegex(guest.Refused, 'drill'):
            guest.check_forwarding(record)


class DrillOnlyOnDrillInstances(tg.TempState):
    def test_drill_and_defective_controls_refuse_any_other_instance(self):
        for record in ({'provisioning': {}}, {'validation': {'mode': 'netprobe'}, 'provisioning': {}},
                       {'validation': {'mode': 'drill'}}):
            with mock.patch.object(guest, 'running_instance', return_value=(self.state, record)):
                with self.assertRaises(guest.Refused):
                    guest.drill(self.ctx(), 'abc', 'fail-closed')
                if 'validation' not in record:
                    with self.assertRaisesRegex(guest.Refused, 'drill instance only'):
                        guest.containment_probe(self.ctx(), 'abc',
                                                defective_controls=['ctl-list-own-dir'])

    def test_unknown_kind_and_the_admitted_create_without_its_driver(self):
        with self.assertRaisesRegex(guest.Refused, '--kind'):
            guest.drill(self.ctx(), 'abc', 'bogus')
        with mock.patch.object(guest, 'running_instance', return_value=(self.state, DRILL_RECORD)):
            with self.assertRaisesRegex(guest.Refused, 'live_admitted_create'):
                guest.drill(self.ctx(), 'abc', 'admitted-create',
                            channels=lambda rec: (None, None, None))
        with self.assertRaises(SystemExit):
            guest.main(['drill', '--profile', str(PROFILE_DIR), '--state-dir', str(self.state),
                        '--name', 'abc', '--kind', 'admitted-create'])


# ---------------------------------------------------------------- the defective control


class DefectiveControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ctx = types.SimpleNamespace(repo=REPO)
        cls.catalogue, _, _ = guest.load_containment_catalogue(ctx)

    def test_the_control_is_replaced_in_a_copy_with_its_dependents_recorded(self):
        out, injected = guest.defective_catalogue(self.catalogue, ['ctl-list-own-dir', 'ctl-read-own-file'])
        by_id = {c['id']: c for c in out['cases']}
        self.assertEqual(by_id['ctl-list-own-dir']['probe'], guest.DRILL_DEFECTIVE_PROBE)
        original = {c['id']: c for c in self.catalogue['cases']}['ctl-list-own-dir']
        self.assertEqual(original['probe']['op'], 'list')
        self.assertEqual([i['control'] for i in injected], ['ctl-list-own-dir', 'ctl-read-own-file'])
        self.assertEqual(len(injected[0]['dependent_cases']), 14)
        self.assertEqual(len(injected[1]['dependent_cases']), 8)

    def test_only_a_control_the_runner_executes_itself(self):
        for cid in ('ctl-own-inner-server', 'file-shadow', 'no-such-case'):
            with self.assertRaises(guest.Refused):
                guest.defective_catalogue(self.catalogue, [cid])

    def test_dependents_are_unknown_never_pass_and_the_control_fails(self):
        out, injected = guest.defective_catalogue(self.catalogue, ['ctl-list-own-dir'])
        by_id = {c['id']: c for c in out['cases']}
        control = by_id['ctl-list-own-dir']
        verdict, _, _ = guest.containment_verdict(control, [{'where': 'a', 'outcome': 'ENOENT'}], None)
        self.assertEqual(verdict, 'FAIL')
        for cid in injected[0]['dependent_cases']:
            case = by_id[cid]
            expected = (case['expected']['outcomes'] or ['?'])[0]
            got, _, _ = guest.containment_verdict(case, [{'where': 'a', 'outcome': expected}], 'FAIL',
                                                  {c: 'PASS' for c in case.get('compensated_by') or []})
            self.assertEqual(got, 'UNKNOWN', cid)


# ---------------------------------------------------------------- fail-closed checks

def observation(server='active', guard='active', docker='active', listening=True, processes=2,
                restarts=0, journal=(), moby=('dockerd', 'containerd'), dropin=None):
    return {'units': {guest.DRILL_SERVER_UNIT: {'ActiveState': server, 'NRestarts': str(restarts)},
                      guest.DRILL_GUARD_UNIT: {'ActiveState': guard},
                      'docker.service': {'ActiveState': docker}},
            'listeners': ['127.0.0.1:8000 users:(("agent-server",pid=9,fd=3))'] if listening else [],
            'agent_server': {'processes': [{'comm': 'agent-server', 'pid': i} for i in range(processes)]},
            'moby_processes': [{'comm': c, 'pid': 1} for c in moby],
            'journal': {guest.DRILL_SERVER_UNIT: list(journal)}, 'paths': {}, 'containers': {},
            'guard_dropin_sha256': dropin}


class FailClosedChecks(unittest.TestCase):
    def test_a_refusing_key_check(self):
        during = observation(server='activating', listening=False, processes=0, restarts=3,
                             journal=['aieh-agent-server-keycheck: refused: OH_SESSION_API_KEYS_0 ...'])
        rows = guest.key_drill_checks(during, {'error': 'ECONNREFUSED'}, {'error': 'ECONNREFUSED'}, True)
        self.assertTrue(all(r['ok'] for r in rows), rows)
        rows = guest.key_drill_checks(observation(), {'status': 200}, {'status': 201}, False)
        self.assertEqual([r['ok'] for r in rows], [False] * 7)

    def test_a_failing_guard(self):
        boot = observation(server='failed', guard='failed', docker='inactive', listening=False,
                           processes=0, moby=('containerd',))
        rows = guest.guard_drill_checks(boot, boot, {'error': 'ECONNREFUSED'}, {'error': 'ECONNREFUSED'})
        self.assertTrue(all(r['ok'] for r in rows), rows)
        # Moby stopped, but the Agent Server serving: that check, and only that one, fails
        boot = observation(guard='failed', docker='inactive', moby=('containerd',))
        rows = guest.guard_drill_checks(boot, boot, {'status': 200}, {'status': 502})
        self.assertEqual([r['check'] for r in rows if not r['ok']], ['Agent Server stopped'])
        rows = guest.guard_drill_checks(observation(guard='failed'), observation(), {'status': 200},
                                        {'status': 201})
        self.assertIn('no conversation created (no 2xx, no container)',
                      [r['check'] for r in rows if not r['ok']])


# ---------------------------------------------------------------- stored state

SAMPLE_STATE = {
    'meta.json': {'id': 'e0122b0000004000800000000000d001', 'title': None, 'autotitle': False,
                  'max_iterations': 500, 'created_at': '2026-11-09T09:01:17.438886Z',
                  'workspace': {'kind': 'LocalWorkspace', 'working_dir': '/workspace'},
                  'tags': {'aieh': 'x'}, 'secrets': {}, 'client_tools': [],
                  'agent_definitions': [{'name': 'a'}]},
    'base_state.json': {'execution_status': 'idle', 'stuck_detection': True,
                        'persistence_dir': '/var/openhands/conversations/x',
                        'stats': {'usage_to_metrics': {}}, 'agent': {'llm': {'timeout': 300,
                                                                             'retry_multiplier': 8.0}}},
}


class StoredStateAlterations(unittest.TestCase):
    def test_mutations(self):
        m = 'MARK'
        cases = [('autotitle', False, True), ('max_iterations', 500, 507), ('retry_multiplier', 8.0, 1008.0),
                 ('execution_status', 'idle', 'running'), ('execution_status', 'running', 'idle'),
                 ('working_dir', '/workspace', m), ('persistence_dir', '/var/x', m), ('kind', 'Agent', 'Agent-aieh-drill'),
                 ('id', 'e0122b0000004000800000000000d001', guest.DRILL_FOREIGN_UUID.replace('-', '')),
                 ('id', 'e0122b00-0000-4000-8000-00000000d001', guest.DRILL_FOREIGN_UUID),
                 ('created_at', '2026-11-09T09:01:17Z', '2001-11-09T09:01:17Z'),
                 ('title', None, 'aieh-drill'), ('container', None, guest.DRILL_CONTAINER_OPTIONS),
                 ('worktree_root', None, m), ('conversation_runtime', None, 'local'),
                 ('secrets', {}, {'aieh-drill': 'x'}), ('tags', ['a'], ['a', 'aieh-drill'])]
        for key, old, new in cases:
            self.assertEqual(guest.mutate_value(key, old, m), new, key)

    def test_every_field_once_then_the_additions_and_the_startup_pair(self):
        alts = guest.state_alterations(SAMPLE_STATE)
        leaves = [a for a in alts if 'combination' not in a and a['old'] != '<absent>']
        pointers = [(a['file'], tuple(a['pointer'])) for a in leaves]
        self.assertEqual(len(pointers), len(set(pointers)))
        self.assertIn(('meta.json', ('workspace', 'working_dir')), pointers)
        self.assertIn(('meta.json', ('agent_definitions', 0, 'name')), pointers)
        self.assertIn(('base_state.json', ('stats', 'usage_to_metrics')), pointers)
        self.assertNotIn(('meta.json', ('workspace',)), pointers)
        self.assertEqual(len(leaves), 17)          # 11 in meta.json, 6 in base_state.json
        for a in leaves:
            if a['marker']:
                self.assertTrue(a['value'].startswith(guest.DRILL_MARKER_ROOT))
        additions = [a for a in alts if a.get('old') == '<absent>']
        self.assertEqual([(a['file'], a['op']) for a in additions],
                         [('meta.json', 'set'), ('meta.json', 'set'), ('owner_lease.json', 'plant')])
        combo = alts[-1]['combination']
        self.assertEqual([(c['file'], c['pointer'], c['value']) for c in combo],
                         [('base_state.json', ['execution_status'], 'running'),
                          ('meta.json', ['workspace', 'working_dir'], alts[-1]['marker'])])
        self.assertEqual([a['n'] for a in alts], list(range(len(alts))))

    def cycle(self, **change):
        container = tg.conversation_container()
        entry = {'shape': guest.container_shape(container),
                 'container_keys': {'OH_SECRET_KEY': 'sha256:a', 'OH_SESSION_API_KEYS_0': 'sha256:b'},
                 'view': {'conversation_runtime': 'docker', 'available_runtimes': [],
                          'unauthenticated_status': 401},
                 'server_processes': [{'comm': 'agent-server'}, {'comm': 'agent-server'}],
                 'marker': {'/m': {'state': 'absent'}}}
        for key, value in change.items():
            if key == 'memory':
                entry['shape']['host']['Memory'] = value
            else:
                entry[key] = value
        return entry

    def test_the_cycle_verdict(self):
        base = self.cycle()
        self.assertEqual(guest.state_cycle_verdict(base, self.cycle(), '/m')[0], 'unchanged')
        self.assertEqual(guest.state_cycle_verdict(base, self.cycle(shape=None), '/m')[0], 'unknown')
        for change in ({'memory': 1},
                       {'container_keys': {'OH_SECRET_KEY': 'sha256:c'}},
                       {'view': {'conversation_runtime': 'local', 'unauthenticated_status': 401}},
                       {'view': {'conversation_runtime': 'docker', 'unauthenticated_status': 200}},
                       {'server_processes': [{'comm': 'agent-server'}] * 2 + [{'comm': 'git'}]},
                       {'marker': {'/m': {'state': 'dir'}}}):
            verdict, rows = guest.state_cycle_verdict(base, self.cycle(**change), '/m')
            self.assertEqual(verdict, 'steered', change)

    def test_the_shape_normalizes_the_conversation(self):
        a = tg.conversation_container()
        b = copy.deepcopy(a)
        hex_a = guest.conversation_hex(a)
        text = json.dumps(b).replace(hex_a, 'f' * 32)
        self.assertEqual(guest.container_shape(a), guest.container_shape(json.loads(text)))


# ---------------------------------------------------------------- the guest-root P5 scan

CID = 'c' * 64


def scan(**change):
    control = {'path': '/var/lib/aieh-drill/control/p5-control-1', 'key_body_sha256': 'k' * 64}
    out = {'complete': True, 'files': 10, 'bytes': 100, 'proc_files': 4, 'seconds': 1.0,
           'control': control, 'mounts_walked': ['/', '/srv/scratch'],
           'hits': {'control:canary': [{'path': control['path'], 'count': 1}],
                    'control:secret': [{'path': control['path'] + '.secret', 'count': 1}],
                    'secret:server:OH_SECRET_KEY': [
                        {'path': '/etc/aieh/agent-server/secrets.env', 'count': 1},
                        {'path': '/proc/77/environ', 'count': 1}],
                    'secret:server:OH_SESSION_API_KEYS_0': [
                        {'path': '/etc/aieh/agent-server/secrets.env', 'count': 1},
                        {'path': '/var/lib/aieh/agent-server/session.key', 'count': 1}],
                    f'secret:container:{CID[:12]}:OH_SECRET_KEY': [
                        {'path': f'/srv/scratch/docker/containers/{CID}/config.v2.json', 'count': 1},
                        {'path': guest.CONTAINERD_METADATA, 'count': 1},
                        {'path': '/proc/90/environ', 'count': 1}],
                    'owner:private-key-header': [
                        {'path': '/etc/ssh/ssh_host_ed25519_key', 'count': 1},
                        {'path': f'/srv/scratch/docker/overlay2/{"d" * 64}/diff/usr/share/doc/x', 'count': 2}]},
           'key_blocks': [{'path': control['path'], 'body_sha256': 'k' * 64, 'kind': 'OPENSSH'},
                          {'path': '/etc/ssh/ssh_host_ed25519_key', 'body_sha256': 'h' * 64}],
           'process_owners': {'/proc/77/environ': {'cgroup': '/system.slice/aieh-agent-server.service'},
                              '/proc/90/environ': {'cgroup': f'/system.slice/docker-{CID}.scope'}},
           'raw': {}}
    out.update(change)
    return out


class RootScanVerdict(unittest.TestCase):
    containers = {CID: 'e' * 32}

    def test_a_clean_scan(self):
        verdict, detail = guest.root_scan_verdict(scan(), 'i' * 64, self.containers)
        self.assertEqual(verdict, 'PASS', [r for r in detail['checks'] if not r['ok']])
        self.assertIn('owner:private-key-header', detail['owner_patterns'])

    def test_failures(self):
        canary = scan()
        canary['hits']['canary:env:X#0'] = [{'path': '/var/log/syslog', 'count': 1}]
        stray = scan()
        stray['hits']['secret:server:OH_SECRET_KEY'].append({'path': '/var/log/journal/x', 'count': 1})
        foreign = scan()
        foreign['hits'][f'secret:container:{CID[:12]}:OH_SECRET_KEY'].append(
            {'path': '/srv/scratch/openhands/home/x', 'count': 1})
        leaked = scan(key_blocks=[{'path': '/home/agent/k', 'body_sha256': 'i' * 64}])
        raw = scan(raw={'/dev/vda1': {'mount': '/', 'counts': {'secret:server:OH_SECRET_KEY': 3}}})
        pattern = scan()
        pattern['hits']['owner:llm-provider-key'] = [{'path': '/root/.bash_history', 'count': 1}]
        for case in (canary, stray, foreign, leaked, raw, pattern):
            verdict, _ = guest.root_scan_verdict(case, 'i' * 64, self.containers)
            self.assertEqual(verdict, 'FAIL')

    def test_a_missing_control_is_unknown_never_pass(self):
        broken = scan()
        del broken['hits']['control:canary']
        verdict, _ = guest.root_scan_verdict(broken, 'i' * 64, self.containers)
        self.assertEqual(verdict, 'UNKNOWN')

    def test_raw_counts_compare_with_the_files_on_that_device(self):
        ok = scan(raw={'/dev/vda1': {'mount': '/', 'counts': {'secret:server:OH_SECRET_KEY': 1}},
                       '/dev/vdb': {'mount': '/srv/scratch', 'counts': {}}})
        verdict, detail = guest.root_scan_verdict(ok, 'i' * 64, self.containers)
        self.assertEqual(verdict, 'PASS', detail['raw'])
        self.assertEqual(detail['raw'], [{'device': '/dev/vda1', 'mount': '/', 'label':
                                          'secret:server:OH_SECRET_KEY', 'raw': 1, 'files': 1,
                                          'residue': 0}])

    def test_canary_digests_and_the_key_body(self):
        needles = {'env:A': 'aieh-canary-env-' + 'a' * 32, 'home:x': 'no core here'}
        out = guest.canary_core_digests({'needles': needles})
        self.assertEqual(out, {'env:A#0': hashlib.sha256(b'a' * 32).hexdigest()})
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / 'k'
            key.write_text('-----BEGIN OPENSSH PRIVATE KEY-----\nAB C\nDE\n'
                           '-----END OPENSSH PRIVATE KEY-----\n', encoding='ascii')
            self.assertEqual(guest.instance_key_body_sha256(key), hashlib.sha256(b'ABCDE').hexdigest())


# ---------------------------------------------------------------- the admitted create


class AdmittedCreate(unittest.TestCase):
    def admitted(self, container):
        hex_id = guest.conversation_hex(container)
        cid = f'{hex_id[:8]}-{hex_id[8:12]}-{hex_id[12:16]}-{hex_id[16:20]}-{hex_id[20:]}'
        binds = PROFILE['provisioning']['agent_server']['conversations']['mounts']
        body, _, _ = guest._fixture(types.SimpleNamespace(profile=PROFILE, repo=REPO))
        return {'conversation_id': cid, 'body': dict(body, conversation_id=cid),
                'mounts': [{'source': m['source'].replace('{conversation_hex}', hex_id),
                            'destination': m['destination'].replace('{conversation_hex}', hex_id),
                            'rw': m['rw']} for m in binds]}

    def check(self, admitted, container, sent=None):
        record = {'provisioning': {'image_id': tg.IMAGE_ID, 'local_tag': tg.LOCAL_TAG}}
        report = tg.conversation_facts_report([container], [tg.proxy_line()], [tg.proxy_entry()])
        return guest.admitted_container_check(PROFILE, record, report, admitted,
                                              admitted['body'] if sent is None else sent)

    def test_the_container_equals_the_admitted_create(self):
        container = tg.conversation_container()
        ok, rows = self.check(self.admitted(container), container)
        self.assertTrue(ok, [r for r in rows if not r['ok']])

    def test_differences_are_caught(self):
        container = tg.conversation_container()
        admitted = self.admitted(container)
        wrong_mounts = copy.deepcopy(admitted)
        wrong_mounts['mounts'][0]['source'] = '/srv/scratch/docker'
        wrong_caps = copy.deepcopy(admitted)
        wrong_caps['body']['container'] = {'memory': '8g'}
        for adm, sent in ((wrong_mounts, None), (wrong_caps, None), (admitted, {'other': 1})):
            ok, _ = self.check(adm, container, sent)
            self.assertFalse(ok)
        policy = copy.deepcopy(admitted)          # the reserved policy's caps, when given, rule
        policy['admission_caps'] = {'memory': '4g', 'cpus': 2.0, 'pids_limit': 256}
        ok, rows = self.check(policy, container)
        self.assertEqual([r['check'] for r in rows if not r['ok']], ['caps equal the admitted ones'])
        policy['admission_caps']['pids_limit'] = 512
        self.assertTrue(self.check(policy, container)[0])
        other = copy.deepcopy(admitted)
        other['conversation_id'] = 'e0122b00-0000-4000-8000-00000000ffff'
        ok, rows = self.check(other, container)
        self.assertFalse(ok)

    def test_the_transport_sends_once(self):
        calls = []

        def api(requests):
            calls.append(requests)
            return {'responses': [{'status': 201, 'body': {'id': 'x'}}], 'session_key_occurrences': 0}
        transport = guest.GuestCreateTransport(api)
        self.assertEqual(transport('POST', '/api/conversations', {'a': 1})['status'], 201)
        with self.assertRaises(guest.Refused):
            transport('POST', '/api/conversations', {'a': 1})
        self.assertEqual(len(calls), 1)
        failing = guest.GuestCreateTransport(lambda r: {'responses': [{'status': 502}],
                                                        'session_key_occurrences': 0})
        with self.assertRaisesRegex(guest.Refused, '502'):
            failing('POST', '/api/conversations', {})


# ---------------------------------------------------------------- the drills against a fake guest


class FakeGuest:
    """The state the drills act on: units, a key and a guard that may be broken, the stored
    files of conversations, and an outer server that hydrates a RUNNING record at its start
    (creating the stored working directory) when ``hydrates`` is set. ``serves_without_moby``
    models a server that starts although Moby failed."""

    def __init__(self, hydrates=False, serves_without_moby=False):
        self.hydrates, self.serves_without_moby = hydrates, serves_without_moby
        self.key_broken, self.guard_broken, self.restarts = None, None, 0
        self.files, self.snapshots, self.created_dirs = {}, {}, set()
        self.containers, self.hydrated = {}, False
        self.boot()

    def boot(self):
        self.guard_up = not self.guard_broken
        self.docker_up = self.guard_up
        self.server_up = not self.key_broken and (self.docker_up or self.serves_without_moby)
        self.containers = {}
        self.server_start()

    def server_start(self):
        self.hydrated = False
        for hex_id, files in self.files.items():
            base = json.loads(files['base_state.json'])
            if self.hydrates and base.get('execution_status') == 'running':
                wd = json.loads(files['meta.json'])['workspace']['working_dir']
                if wd.startswith('/srv/scratch/openhands/'):
                    self.created_dirs.add(wd)
                files['owner_lease.json'] = '{"owner": "outer"}'
                self.hydrated = True

    def obs(self, paths=()):
        server = 'activating' if self.key_broken else 'active' if self.server_up else 'failed'
        return observation(server=server,
                           guard='active' if self.guard_up else 'failed',
                           docker='active' if self.docker_up else 'inactive',
                           listening=self.server_up, processes=2 if self.server_up else 0,
                           restarts=self.restarts,
                           journal=['aieh-agent-server-keycheck: refused: x'] if self.key_broken else [],
                           moby=('dockerd', 'containerd') if self.docker_up else ('containerd',),
                           dropin='d' if self.guard_broken else None) | {
            'paths': {p: {'state': 'dir' if p in self.created_dirs else 'absent'} for p in paths},
            'containers': {h[:12]: {'keys': {'OH_SECRET_KEY': 'sha256:' + h[:4]}} for h in self.containers},
            'server_invocation': {'lines': ['INFO Resumed conversation x'] if self.hydrated else []}}

    def req(self, action, params=None, ceiling=None):
        params = params or {}
        detail = None
        if action == 'observe':
            if self.key_broken:
                self.restarts += 1
            detail = self.obs(params.get('paths') or ())
        elif action == 'key-break':
            self.key_broken, self.server_up = params['variant'], False
            detail = {'variant': params['variant']}
        elif action == 'key-restore':
            self.key_broken, self.server_up = None, True
            detail = {'copy_removed': True}
        elif action == 'guard-break':
            self.guard_broken = params['variant']
            detail = {'variant': params['variant']}
        elif action == 'guard-restore':
            self.guard_broken = None
            detail = {'removed': True}
        elif action == 'server-restart':
            self.containers = {}
            self.server_start()
            detail = {'rc': 0}
        elif action == 'state-read':
            files = self.files[params['hex']]
            detail = {'entries': [{'path': k, 'kind': 'file', 'sha256': hashlib.sha256(v.encode()).hexdigest()}
                                  for k, v in sorted(files.items())],
                      'content': {k: json.loads(v) for k, v in files.items()}}
        elif action == 'state-snapshot':
            self.snapshots[params['hex']] = dict(self.files[params['hex']])
            detail = {'files': {k: hashlib.sha256(v.encode()).hexdigest()
                                for k, v in sorted(self.files[params['hex']].items())}}
        elif action == 'state-alter':
            files = self.files[params['hex']]
            if params['op'] == 'plant':
                files[params['file']] = json.dumps(params['value'])
            else:
                doc = json.loads(files[params['file']])
                parent, key = helper.walk_pointer(doc, params['pointer'])
                parent[key] = params['value']
                files[params['file']] = json.dumps(doc)
            detail = {'ok': True}
        elif action == 'state-rollback':
            self.files[params['hex']] = dict(self.snapshots[params['hex']])
            detail = {'equal': True, 'removed': [], 'rewritten': []}
        elif action == 'state-discard':
            self.snapshots.pop(params['hex'], None)
            detail = {'present_after': False}
        return {'id': 'x', 'action': action, 'ok': True, 'detail': detail}

    def api(self, requests):
        out = []
        for r in requests:
            path, method = r['path'], r['method']
            if not self.server_up:
                out.append({'method': method, 'path': path, 'error': 'ECONNREFUSED'})
                continue
            m = re.match(r'/api/conversations/([0-9a-f-]{36})(.*)', path)
            if path == '/ready':
                out.append({'status': 200})
            elif path == '/server_info':
                out.append({'status': 200, 'body': {'conversation_runtime': 'docker',
                                                    'available_conversation_runtimes': []}})
            elif path == '/api/conversations' and method == 'POST':
                hex_id = r['json']['conversation_id'].replace('-', '')
                if not self.docker_up:
                    out.append({'status': 502})
                    continue
                self.files.setdefault(hex_id, {
                    'base_state.json': json.dumps({'execution_status': 'idle', 'stuck_detection': True}),
                    'meta.json': json.dumps({'workspace': {'kind': 'LocalWorkspace', 'working_dir': '/workspace'},
                                             'title': None})})
                memory = (r['json'].get('container') or {}).get('memory')
                self.containers[hex_id] = memory
                out.append({'status': 201, 'body': {'id': r['json']['conversation_id']}})
            elif path.startswith('/api/conversations/search'):
                out.append({'status': 200, 'body': {'items': []}})
            elif m and m.group(2) == '' and method == 'GET':
                out.append({'status': 401} if not r.get('auth', True) else
                           {'status': 200, 'body': {'id': m.group(1), 'execution_status': 'idle'}})
            elif m and m.group(2) == '' and method == 'DELETE':
                hex_id = m.group(1).replace('-', '')
                self.containers.pop(hex_id, None)
                out.append({'status': 200 if self.files.pop(hex_id, None) else 404})
            elif m and m.group(2) == '/runtime' and method == 'DELETE':
                self.containers.pop(m.group(1).replace('-', ''), None)
                out.append({'status': 204})
            elif m and m.group(2) == '/runtime':
                out.append({'status': 200, 'body': {'runtime_status': 'missing'}})
            elif m and m.group(2) == '/runtime/reprovision':
                self.containers[m.group(1).replace('-', '')] = None
                out.append({'status': 200, 'body': {'runtime_status': 'available'}})
            elif m and m.group(2) == '/bash/execute_bash_command':
                hex_id = m.group(1).replace('-', '')
                files = self.files[hex_id]
                base = json.loads(files['base_state.json'])
                base['execution_status'] = 'running'
                files['base_state.json'] = json.dumps(base)
                meta = json.loads(files['meta.json'])
                script = __import__('base64').b64decode(r['json']['command'].split()[1]).decode()
                meta['workspace']['working_dir'] = re.search(r"working_dir'\] = '([^']+)'", script).group(1)
                files['meta.json'] = json.dumps(meta)
                out.append({'status': 200, 'body': {'exit_code': 0, 'stdout': '{"uid": 999}'}})
            else:
                out.append({'status': 404})
        return {'responses': out, 'session_key_occurrences': 0}

    def facts(self):
        containers = []
        for hex_id, memory in self.containers.items():
            c = tg.conversation_container()
            text = json.dumps(c).replace(guest.conversation_hex(c), hex_id)
            c = json.loads(text)
            if memory:
                c['HostConfig']['Memory'] = guest.memory_bytes(memory)
            containers.append(c)
        return tg.conversation_facts_report(containers, [], [])

    def channels(self, record):
        return self.api, self.facts, self.req

    def stop(self):
        return {'result': 'stopped'}

    def start(self):
        self.boot()
        return {'result': 'ready', 'seconds': 1}


class DrillRuns(tg.TempState):
    def run_drill(self, fake, kind, **kwargs):
        idir = self.state / 'instances' / 'abc'
        idir.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(guest, 'running_instance', return_value=(idir, DRILL_RECORD)), \
                mock.patch.object(guest, 'POLL_S', 0):
            return guest.drill(self.ctx(), 'abc', kind, channels=fake.channels, stop_fn=fake.stop,
                               start_fn=fake.start, **kwargs)

    def test_fail_closed_on_a_guest_that_fails_closed(self):
        out = self.run_drill(FakeGuest(), 'fail-closed')
        self.assertEqual(out['result'], 'PASS', out['failed_steps'])
        names = [s['step'] for s in out['steps']]
        self.assertEqual(len(names), 5)
        self.assertTrue(Path(out['record']).is_file())

    def test_fail_closed_reports_a_server_that_serves_without_moby(self):
        out = self.run_drill(FakeGuest(serves_without_moby=True), 'fail-closed')
        self.assertEqual(out['result'], 'FAIL')
        self.assertEqual(out['failed_steps'], ['guard fails closed (fail-pre)', 'guard fails closed (check-only)'])
        rows = out['steps'][2]['detail']['checks']
        self.assertEqual([r['check'] for r in rows if not r['ok']], ['Agent Server stopped'])
        self.assertIsNone(out['broken'])

    def test_stored_state_on_a_server_that_ignores_the_files(self):
        out = self.run_drill(FakeGuest(), 'stored-state')
        self.assertEqual(out['result'], 'PASS', out['failed_steps'])
        rows = out['steps'][3]['detail']['rows']
        self.assertTrue(rows and not [r for r in rows if r['steered']])

    def test_stored_state_finds_the_startup_hydration(self):
        out = self.run_drill(FakeGuest(hydrates=True), 'stored-state')
        self.assertEqual(out['result'], 'FAIL')
        detail = out['steps'][3]['detail']
        steered = [r['alteration'] for r in detail['rows'] if r['steered']]
        self.assertEqual([('combination' in a, a.get('pointer')) for a in steered],
                         [(False, ['execution_status']), (True, None)])
        for index in (4, 5):
            job = out['steps'][index]['detail']['summary']
            self.assertEqual(job, {'job_wrote': True, 'execution_status_survived': True,
                                   'working_dir_survived': True, 'outer_server_resumed_it': True,
                                   'outer_server_created_the_working_dir': True})
        self.assertEqual(len(out['failed_steps']), 3)

    def test_stored_state_limit(self):
        out = self.run_drill(FakeGuest(), 'stored-state', limit=2)
        self.assertEqual(out['steps'][3]['detail']['run'], 2)


if __name__ == '__main__':
    unittest.main()
