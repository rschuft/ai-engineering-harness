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

    def test_the_helper_holds_nothing_the_p5_scans_find(self):
        """It travels in the seed, which the profiles P5 scan searches for Owner-class patterns,
        canaries and the instance key (found on the first official drill guest: fixed forward)."""
        literals, patterns = guest.p5_needles(None, None, environ={}, principal='HOST\\someone')
        self.assertEqual(guest.scan_bytes(guest.drill_script(), literals, patterns), set())
        owner = {k: [re.compile(rx) for rx in v] for k, v in helper.OWNER_PATTERNS.items()}
        hits = {}
        helper.scan_data(guest.drill_script(), 0, {}, {}, hits, {}, owner, 'helper')
        self.assertEqual(hits, {})

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
            'state-discard', 'root-scan', 'quiesce-break', 'quiesce-restore', 'server-kill',
            'start-window', 'container-kill', 'quarantine-list', 'quarantine-return',
            'sentinel-plant', 'sentinel-check'})
        self.assertEqual(set(helper.QUIESCE_VARIANTS), set(guest.DRILL_QUIESCE_VARIANTS))
        quiesce = PROFILE['provisioning']['agent_server']['quiesce']
        self.assertEqual((helper.QUIESCE_UNIT, helper.QUARANTINE),
                         (quiesce['unit'], quiesce['quarantine']['path']))
        self.assertEqual(guest.DRILL_QUIESCE_UNIT, quiesce['unit'])
        self.assertIn(helper.QUIESCE_UNIT, helper.UNITS)
        for text in helper.QUIESCE_VARIANTS.values():
            self.assertIn('[Service]', text)
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
                           processes=0, moby=('containerd',),
                           journal=['systemd[1]: Dependency failed for aieh-agent-server.service'])
        rows = guest.guard_drill_checks(boot, boot, {'error': 'ECONNREFUSED'}, {'error': 'ECONNREFUSED'})
        self.assertTrue(all(r['ok'] for r in rows), rows)
        # Moby stopped, but the Agent Server serving (slice (b)'s Wants=): those checks fail
        boot = observation(guard='failed', docker='inactive', moby=('containerd',))
        rows = guest.guard_drill_checks(boot, boot, {'status': 200}, {'status': 502})
        self.assertEqual([r['check'] for r in rows if not r['ok']],
                         ['Agent Server stopped', 'Agent Server start refused with result dependency (journal)'])
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

    def test_a_restart_record_keeps_the_journal_of_a_failed_start_only(self):
        ok = {'rc': 0, 'unit': {'ActiveState': 'active'},
              'invocation': {'lines': ['a', 'x Resumed conversation y', 'b']}}
        bad = {'rc': 1, 'unit': {'ActiveState': 'activating'}, 'invocation': {'lines': ['a', 'boom']}}
        self.assertEqual(guest.restart_summary(ok)['journal'], ['x Resumed conversation y'])
        self.assertEqual(guest.restart_summary(bad)['journal'], ['a', 'boom'])
        answers = iter([{'ok': True, 'detail': bad}, {'ok': True, 'detail': ok}])
        out = guest.restart_server(lambda action: next(answers))
        self.assertFalse(out['failed'])
        self.assertTrue(out['first_attempt']['failed'])
        out = guest.restart_server(lambda action: {'ok': True, 'detail': bad})
        self.assertTrue(out['failed'])

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
                        {'path': '/usr/bin/ssh-keygen', 'count': 1},
                        {'path': '/srv/scratch/openhands/tmp/_MEI00000881ymd8JC/botocore/x.json', 'count': 1},
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
        outside = scan()          # the server's home and scratch are not its binary's extraction
        outside['hits']['owner:cloud-token'] = [{'path': '/srv/scratch/openhands/home/x', 'count': 1},
                                                {'path': '/srv/scratch/openhands/tmp/x', 'count': 1}]
        for case in (canary, stray, foreign, leaked, raw, pattern, outside):
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
    """The state the drills act on: units, a key, a guard and (slice (c)) a quiesce step that
    may be broken, the stored files of conversations, and an outer server that hydrates a
    RUNNING record at its start (creating the stored working directory and reading through a
    planted link) when ``hydrates`` is set. ``quiesce`` models the fixed guest: the step runs
    before every server start, removes every container, rewrites running to error and moves
    aside a record that is a link or claims another id; the server Requires it and Moby.
    ``serves_without_moby`` models slice (b)'s server, which started although Moby failed."""

    HOME = '/srv/scratch/openhands/home'
    CONV = '/srv/scratch/openhands/conversations/'

    def __init__(self, hydrates=False, serves_without_moby=False, quiesce=None):
        self.hydrates, self.serves_without_moby = hydrates, serves_without_moby
        self.quiesce = (not serves_without_moby) if quiesce is None else quiesce
        self.key_broken, self.guard_broken, self.quiesce_broken, self.restarts = None, None, None, 0
        self.files, self.snapshots, self.created_dirs = {}, {}, set()
        self.quarantine, self.loops, self.sentinels = {}, set(), {}
        self.containers, self.hydrated, self.runs, self.loop_marker = {}, False, [], {}
        self.boot()

    def boot(self):
        self.guard_up = not self.guard_broken
        self.docker_up = self.guard_up
        self.containers, self.runs = {}, []
        self.server_start()

    def start_refused(self):
        if self.key_broken:
            return None
        if self.serves_without_moby or not self.quiesce:
            return None if (self.docker_up or self.serves_without_moby) else 'docker'
        return 'docker' if not self.docker_up else 'quiesce' if self.quiesce_broken else None

    def quiesce_step(self):
        summary = {'ok': True, 'containers_removed': len(self.containers), 'containers_remaining': 0,
                   'rewritten': [], 'quarantined': [], 'unparseable': [], 'unchanged': 0,
                   'not_a_record': 0}
        self.containers = {}
        for hex_id in sorted(self.files):
            files = self.files[hex_id]
            reason = None
            if '__link__' in files:
                reason = 'link' if files['__link__'] == 'symlink' else 'hard-linked'
            elif json.loads(files['meta.json']).get('id', '').replace('-', '') != hex_id:
                reason = 'id-mismatch'
            if reason:
                self.quarantine[f'{hex_id}.20261109T000000Z.{len(self.quarantine):08x}'] = \
                    self.files.pop(hex_id)
                summary['quarantined'].append({'id': hex_id, 'reason': reason})
                continue
            base = json.loads(files['base_state.json'])
            if base.get('execution_status') == 'running':
                base['execution_status'] = 'error'
                files['base_state.json'] = json.dumps(base)
                summary['rewritten'].append(hex_id)
            else:
                summary['unchanged'] += 1
        self.runs.append(summary)
        return summary

    def server_start(self, killed=False):
        self.hydrated = False
        for hex_id in list(self.loops):          # a live job's loop keeps writing the pair
            if hex_id in self.containers and hex_id in self.files:
                self.job_pair(hex_id, self.loop_marker[hex_id])
        removed = []
        refused = self.start_refused()
        self.server_up = not self.key_broken and refused is None
        self.window = {'quiesce_unit': {'Result': None}, 'runs_this_boot': len(self.runs),
                       'last_run': None, 'times': {}, 'events': {
                           'during_quiesce': [], 'quiesce_exit_to_server_exec_start': [],
                           'server_exec_start_to_active': []}}
        if self.quiesce and self.docker_up and not self.key_broken:
            if self.quiesce_broken:
                self.window['quiesce_unit'] = {'Result': 'exit-code'}
            else:
                removed = list(self.containers)
                summary = self.quiesce_step()
                self.window.update(quiesce_unit={'Result': 'success'}, runs_this_boot=len(self.runs),
                                   last_run={'summary': summary},
                                   times={'quiesce_start': 1.0, 'quiesce_exit': 2.0,
                                          'server_exec_start': 3.0, 'server_active': 4.0})
                self.window['events']['during_quiesce'] = [{'action': 'destroy', 'id': h[:12]}
                                                           for h in removed]
        self.loops &= set(self.containers)
        if not self.server_up:
            return
        if self.containers:                       # the server's own start-up cleanup
            self.window['events']['server_exec_start_to_active'] = [
                {'action': 'destroy', 'id': h[:12]} for h in self.containers]
            self.containers = {}
        self.window['server_unit'] = {'ActiveState': 'active'}
        for hex_id, files in self.files.items():
            if '__link__' in files:
                if self.hydrates:
                    self.sentinels[(hex_id, files['__link__'])]['read'] = True
                continue
            base = json.loads(files['base_state.json'])
            if self.hydrates and base.get('execution_status') == 'running':
                wd = json.loads(files['meta.json'])['workspace']['working_dir']
                if wd.startswith('/srv/scratch/openhands/'):
                    self.created_dirs.add(wd)
                files['owner_lease.json'] = '{"owner": "outer"}'
                self.hydrated = True

    def job_pair(self, hex_id, marker):
        files = self.files[hex_id]
        base = json.loads(files['base_state.json'])
        base['execution_status'] = 'running'
        files['base_state.json'] = json.dumps(base)
        meta = json.loads(files['meta.json'])
        meta['workspace']['working_dir'] = marker
        files['meta.json'] = json.dumps(meta)

    def obs(self, paths=()):
        server = 'activating' if self.key_broken else 'active' if self.server_up else 'failed'
        refused = self.start_refused()
        journal = ['aieh-agent-server-keycheck: refused: x'] if self.key_broken else \
            ['systemd[1]: Dependency failed for aieh-agent-server.service'] if refused else []

        def path_state(p):
            if p == self.HOME:
                return {'state': 'dir', 'entries': sorted(
                    d.rsplit('/', 1)[1] for d in self.created_dirs if d.rsplit('/', 1)[0] == self.HOME)}
            if p.startswith(self.CONV):
                return {'state': 'dir' if p[len(self.CONV):] in self.files else 'absent'}
            return {'state': 'dir' if p in self.created_dirs else 'absent'}
        out = observation(server=server,
                          guard='active' if self.guard_up else 'failed',
                          docker='active' if self.docker_up else 'inactive',
                          listening=self.server_up, processes=2 if self.server_up else 0,
                          restarts=self.restarts, journal=journal,
                          moby=('dockerd', 'containerd') if self.docker_up else ('containerd',),
                          dropin='d' if self.guard_broken else None) | {
            'paths': {p: path_state(p) for p in paths},
            'containers': {h[:12]: {'keys': {'OH_SECRET_KEY': 'sha256:' + h[:4]}} for h in self.containers},
            'server_invocation': {'lines': ['INFO Resumed conversation x'] if self.hydrated else []},
            'quiesce_dropin_sha256': 'q' if self.quiesce_broken else None}
        out['units'][guest.DRILL_QUIESCE_UNIT] = {
            'ActiveState': 'failed' if self.quiesce_broken else 'inactive',
            'Result': (self.window.get('quiesce_unit') or {}).get('Result') or 'success'}
        return out

    def restart_detail(self):
        return {'rc': 0 if self.server_up else 1, 'unit': {
                    'ActiveState': 'active' if self.server_up else 'inactive',
                    'NRestarts': str(self.restarts)},
                'stderr': '' if self.server_up else 'A dependency job failed.',
                'invocation': {'lines': ['INFO Uvicorn running'] +
                               (['INFO Resumed conversation x'] if self.hydrated else [])}}

    def req(self, action, params=None, ceiling=None):
        params = params or {}
        detail, ok = None, True
        hex_id = params.get('hex')
        if action == 'observe':
            if self.key_broken:
                self.restarts += 1
            detail = self.obs(params.get('paths') or ())
        elif action == 'key-break':
            self.key_broken, self.server_up = params['variant'], False
            detail = {'variant': params['variant']}
        elif action == 'key-restore':
            self.key_broken = None
            self.server_start()
            detail = {'copy_removed': True}
        elif action == 'guard-break':
            self.guard_broken = params['variant']
            detail = {'variant': params['variant']}
        elif action == 'guard-restore':
            self.guard_broken = None
            detail = {'removed': True}
        elif action == 'quiesce-break':
            self.quiesce_broken = params['variant']
            detail = {'variant': params['variant']}
        elif action == 'quiesce-restore':
            self.quiesce_broken = None
            detail = {'removed': True}
        elif action == 'server-restart':
            self.containers = {}                  # the server's graceful stop stops its containers
            self.server_start()
            detail = self.restart_detail()
        elif action == 'server-kill':
            self.restarts += 1                    # containers stay alive; systemd restarts it
            self.server_start()
            detail = self.restart_detail()
        elif action == 'start-window':
            detail = copy.deepcopy(self.window)
        elif action == 'container-kill':
            gone = [hex_id] if self.containers.pop(hex_id, 'absent') != 'absent' else []
            detail = {'containers': [h[:12] for h in gone], 'remaining': []}
        elif action == 'quarantine-list':
            detail = {'entries': [{'name': n, 'kind': 'dir'} for n in sorted(self.quarantine)]}
        elif action == 'quarantine-return':
            name = sorted(n for n in self.quarantine if n.startswith(hex_id + '.'))[-1]
            self.files[hex_id] = self.quarantine.pop(name)
            detail = {'returned': name}
        elif action == 'sentinel-plant':
            self.files[hex_id]['__link__'] = params['kind']
            self.sentinels[(hex_id, params['kind'])] = {'read': False}
            detail = {'base_is_link': params['kind'] == 'symlink',
                      'base_nlink': 2 if params['kind'] == 'hardlink' else 1}
        elif action == 'sentinel-check':
            read = self.sentinels[(hex_id, params['kind'])]['read']
            detail = {'unread': not read, 'unwritten': True, 'sha256_equal': True,
                      'control_read_moved_atime': True}
        elif action == 'state-read':
            if hex_id not in self.files:
                return {'id': 'x', 'action': action, 'ok': False, 'error': 'FileNotFoundError'}
            files = {k: v for k, v in self.files[hex_id].items() if not k.startswith('__')}
            detail = {'entries': [{'path': k, 'kind': 'file', 'sha256': hashlib.sha256(v.encode()).hexdigest()}
                                  for k, v in sorted(files.items())],
                      'content': {k: json.loads(v) for k, v in files.items()}}
        elif action == 'state-snapshot':
            self.snapshots[hex_id] = dict(self.files[hex_id])
            detail = {'files': {k: hashlib.sha256(v.encode()).hexdigest()
                                for k, v in sorted(self.files[hex_id].items())}}
        elif action == 'state-alter':
            files = self.files[hex_id]
            if params['op'] == 'plant':
                files[params['file']] = json.dumps(params['value'])
            else:
                doc = json.loads(files[params['file']])
                parent, key = helper.walk_pointer(doc, params['pointer'])
                parent[key] = params['value']
                files[params['file']] = json.dumps(doc)
            detail = {'ok': True}
        elif action == 'state-rollback':
            self.files[hex_id] = dict(self.snapshots[hex_id])
            detail = {'equal': True, 'removed': [], 'rewritten': []}
        elif action == 'state-discard':
            self.snapshots.pop(hex_id, None)
            detail = {'present_after': False}
        return {'id': 'x', 'action': action, 'ok': ok, 'detail': detail}

    def catalog(self):
        """{conversation id hex: record files}: keyed by the stored meta.json id, the last
        directory winning (the 1.60.1 catalog)."""
        out = {}
        for hex_id in sorted(self.files):
            meta = json.loads(self.files[hex_id]['meta.json'])
            out[str(meta.get('id', '')).replace('-', '')] = self.files[hex_id]
        return out

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
                    'meta.json': json.dumps({'id': r['json']['conversation_id'], 'title': None,
                                             'workspace': {'kind': 'LocalWorkspace',
                                                           'working_dir': '/workspace'}})})
                memory = (r['json'].get('container') or {}).get('memory')
                self.containers[hex_id] = memory
                out.append({'status': 201, 'body': {'id': r['json']['conversation_id']}})
            elif path.startswith('/api/conversations/search'):
                items = [{'id': json.loads(f['meta.json'])['id']} for f in self.catalog().values()]
                out.append({'status': 200, 'body': {'items': items}})
            elif m and m.group(2) == '' and method == 'GET':
                record = self.catalog().get(m.group(1).replace('-', ''))
                if not r.get('auth', True):
                    out.append({'status': 401})
                elif record is None:
                    out.append({'status': 404})
                else:
                    meta = json.loads(record['meta.json'])
                    out.append({'status': 200, 'body': {'id': meta.get('id'), 'title': meta.get('title'),
                                                        'execution_status': 'idle'}})
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
                script = __import__('base64').b64decode(r['json']['command'].split()[1]).decode()
                inner = re.search(r"b64decode\('([^']+)'\)", script)
                if inner:                          # the detached rewrite loop (variant C)
                    script = __import__('base64').b64decode(inner.group(1)).decode()
                    self.loops.add(hex_id)
                marker = re.search(r"working_dir'\] = '([^']+)'", script).group(1)
                self.loop_marker = dict(getattr(self, 'loop_marker', {}), **{hex_id: marker})
                self.job_pair(hex_id, marker)
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




# ---------------------------------------------------------------- E-01.4.3: restart series


def ready_line(start='clean', seconds=4.4, restarts=0, ready=True):
    if ready:
        return (f'[ 9.1] g python3[7]: aieh-agent-server-ready: ready start={start} '
                f'seconds={seconds} restarts={restarts}')
    return (f'[ 9.1] g python3[7]: aieh-agent-server-ready: not ready start={start} '
            f'seconds={seconds} restarts={restarts} last_status=None')


class FakeRestarts:
    """The root helper's server-restart, server-kill and observe for a restart series: a
    server whose start fails (the main process exits at import) on the listed restarts, and
    which systemd's Restart=on-failure then starts again; ``reports_retried`` False stands for
    a readiness wait that would call that start clean."""

    def __init__(self, fail_on=(), reports_retried=True, retry_fails=False):
        self.fail_on, self.reports_retried, self.retry_fails = set(fail_on), reports_retried, retry_fails
        self.n, self.restarts, self.pending_retry, self.calls = 0, 0, False, []

    def active_unit(self):
        return {'ActiveState': 'active', 'SubState': 'running', 'Result': 'success',
                'NRestarts': str(self.restarts), 'ExecMainStatus': '0', 'MainPID': '1500'}

    def retried_line(self):
        return ready_line('retried' if self.reports_retried else 'clean', 4.6, self.restarts)

    def __call__(self, action, params=None, ceiling=None):
        self.calls.append(action)
        if action == 'server-restart':
            self.n += 1
            self.restarts = 0                          # a manual start flushes the counter
            if self.n in self.fail_on:
                self.pending_retry = True
                unit = {'ActiveState': 'activating', 'SubState': 'auto-restart',
                        'Result': 'exit-code', 'NRestarts': '0', 'ExecMainStatus': '1'}
                lines = ['[ 8.0] g agent-server[9]: ImportError: cannot import name ...',
                         '[ 8.0] g agent-server[9]: [PYI-9:ERROR] Failed to execute script '
                         "'__main__' due to unhandled exception!",
                         ready_line('main-exited', 1.4, 0, ready=False)]
                return {'ok': True, 'action': action,
                        'detail': {'rc': 1, 'seconds': 1.9, 'stderr': 'Job failed', 'unit': unit,
                                   'invocation': {'lines': lines}}}
            return {'ok': True, 'action': action,
                    'detail': {'rc': 0, 'seconds': 4.9, 'stderr': '', 'unit': self.active_unit(),
                               'invocation': {'lines': ['[ 5.0] g agent-server[9]: started',
                                                        ready_line(seconds=4.3 + self.n % 3)]}}}
        if action == 'observe':
            if self.pending_retry:
                self.pending_retry = False
                self.restarts += 1
                if self.retry_fails:
                    obs = observation(server='failed', restarts=self.restarts)
                    obs['server_invocation'] = {'lines': []}
                    return {'ok': True, 'action': action, 'detail': obs}
            unit = self.active_unit()
            obs = observation(restarts=self.restarts)
            obs['units'][guest.DRILL_SERVER_UNIT] = unit
            obs['server_invocation'] = {'lines': [self.retried_line()] if self.restarts else
                                        [ready_line()]}
            return {'ok': True, 'action': action, 'detail': obs}
        if action == 'server-kill':
            self.restarts += 1
            return {'ok': True, 'action': action,
                    'detail': {'rc': 0, 'seconds': 10.2, 'stderr': '', 'restarts_before': 0,
                               'unit': self.active_unit(),
                               'invocation': {'lines': [self.retried_line()]}}}
        raise AssertionError(action)


class RestartSeries(unittest.TestCase):
    """E-01.4.3: the restart-series drill's counts, retry following, reporting step and
    verdict (RESTART_SERIES_RULE) against fake guests with and without start failures."""

    def run_series(self, fake, count=12):
        steps = guest.DrillSteps('drill restart-series')
        chan = lambda: (None, None, fake)                       # noqa: E731
        with mock.patch.object(guest.time, 'sleep', lambda s: None):
            memo = guest.drill_restart_series(None, 'abc', steps, chan, count)
        return steps, memo

    def test_a_series_without_failures_passes(self):
        fake = FakeRestarts()
        steps, memo = self.run_series(fake)
        self.assertEqual(steps.failed, [])
        s = memo['summary']
        self.assertEqual((s['verdict'], s['restarts'], s['main_process_exits_during_start'],
                          s['failed_starts'], s['outcome_classes']), ('PASS', 12, 0, 0, {'clean': 12}))
        self.assertEqual(s['ready_wait_seconds']['n'], 12)
        self.assertEqual(s['ready_wait_seconds']['max'], 6.3)
        self.assertEqual(fake.calls.count('server-restart'), 13)       # 12 + the manual one after
        self.assertEqual(memo['retried_report']['outcome']['start'], 'retried')
        self.assertEqual(memo['manual_after_retry']['outcome']['start'], 'clean')
        self.assertTrue(all('journal' not in r for r in memo['rows']))   # clean rows stay small
        detail = steps.steps[1]['detail']
        self.assertEqual(len(detail['rows']), 12)

    def test_a_failed_start_is_followed_to_its_retry_and_fails_the_series(self):
        fake = FakeRestarts(fail_on=(3, 9))
        steps, memo = self.run_series(fake)
        s = memo['summary']
        self.assertEqual(s['verdict'], 'FAIL')
        self.assertEqual(steps.failed, ['12 consecutive restarts (systemctl restart)'])
        self.assertEqual((s['main_process_exits_during_start'], s['exit_restarts'], s['failed_starts'],
                          s['failed_starts_retried_to_readiness']), (2, [3, 9], 2, 2))
        self.assertEqual(s['outcome_classes'], {'clean': 10, 'main-exited': 2})
        row = memo['rows'][2]
        self.assertTrue(row['exit_during_start'] and row['failed'])
        self.assertIn('Failed to execute script', ' '.join(row['journal']))
        self.assertEqual(row['retry']['outcome']['start'], 'retried')
        self.assertTrue(row['retry']['reached_readiness'])
        self.assertEqual(s['failed_start_to_readiness_seconds']['n'], 2)

    def test_a_retry_that_never_becomes_ready_is_recorded(self):
        fake = FakeRestarts(fail_on=(2,), retry_fails=True)
        steps, memo = self.run_series(fake, count=3)
        retry = memo['rows'][1]['retry']
        self.assertFalse(retry['reached_readiness'])
        self.assertEqual(memo['summary']['failed_starts_retried_to_readiness'], 0)
        self.assertEqual(memo['summary']['verdict'], 'FAIL')

    def test_a_retried_start_reported_clean_fails_the_reporting_step(self):
        steps, memo = self.run_series(FakeRestarts(reports_retried=False), count=2)
        self.assertEqual(steps.failed, ['a Restart=on-failure start (SIGKILL) is reported start=retried'])
        self.assertEqual(memo['summary']['verdict'], 'PASS')

    def test_fewer_restarts_than_requested_or_a_non_clean_outcome(self):
        rows = [guest.restart_row(1, {'rc': 0, 'seconds': 5.0, 'unit': {'ActiveState': 'active'},
                                      'invocation': {'lines': [ready_line('slow', 31.0)]}})]
        s = guest.series_summary(rows, 2)
        self.assertEqual(s['verdict'], 'FAIL')                     # 1 of 2
        self.assertEqual(s['outcome_classes'], {'slow': 1})
        self.assertIn('journal', rows[0])                          # a non-clean start keeps it
        # a start whose wait printed nothing is a failed start
        row = guest.restart_row(1, {'rc': 0, 'unit': {'ActiveState': 'active'},
                                    'invocation': {'lines': []}})
        self.assertTrue(row['failed'])
        self.assertEqual(guest.series_summary([row], 1)['verdict'], 'FAIL')

    def test_distribution(self):
        d = guest.distribution([5.0, 1.0, 2.0, 4.0, 3.0, None, 'x'])
        self.assertEqual((d['n'], d['min'], d['p50'], d['p90'], d['max'], d['mean']),
                         (5, 1.0, 3.0, 5.0, 5.0, 3.0))
        self.assertEqual(d['buckets_s'], {'1-2': 1, '2-3': 1, '3-4': 1, '4-5': 1, '5-6': 1})
        self.assertEqual(guest.distribution([]), {'n': 0})
        self.assertEqual(guest.distribution([float(i) for i in range(1, 101)])['p99'], 99.0)

    def test_limit_and_cli(self):
        with self.assertRaises(guest.Refused):
            guest.drill_restart_series(None, 'abc', guest.DrillSteps('x'), lambda: None, 0)
        self.assertIn('restart-series', guest.DRILL_KINDS[:5])
        self.assertNotIn('admitted-create', guest.DRILL_KINDS[:5])
        with mock.patch.object(guest, 'Context', side_effect=guest.Refused('X', 'stop here')), \
                mock.patch('sys.stdout'):
            self.assertEqual(guest.main(['drill', '--profile', 'p', '--state-dir', 's', '--name', 'n',
                                         '--kind', 'restart-series', '--limit', '3']), 1)
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
        self.assertEqual(len(names), 6)
        self.assertIn('quiesce step fails closed (fail-pre)', names)
        quiesce = out['steps'][4]['detail']
        self.assertEqual(quiesce['verdict'], 'PASS')
        # restored by a boot, so that inspect's boot-time facts are those of the restored chain
        self.assertEqual(quiesce['reboot_after_restore']['start']['result'], 'ready')
        self.assertTrue(any(r['check'] == 'after a guest boot: Agent Server start refused with '
                            'result dependency (journal)' and r['ok'] for r in quiesce['checks']))
        self.assertTrue(Path(out['record']).is_file())

    def test_fail_closed_reports_a_server_that_serves_without_moby(self):
        out = self.run_drill(FakeGuest(serves_without_moby=True), 'fail-closed')
        self.assertEqual(out['result'], 'FAIL')
        self.assertEqual(out['failed_steps'], ['guard fails closed (fail-pre)', 'guard fails closed (check-only)',
                                               'quiesce step fails closed (fail-pre)'])
        rows = out['steps'][2]['detail']['checks']
        self.assertEqual([r['check'] for r in rows if not r['ok']],
                         ['Agent Server stopped', 'Agent Server start refused with result dependency (journal)'])
        self.assertIsNone(out['broken'])

    def test_stored_state_on_a_server_that_ignores_the_files(self):
        out = self.run_drill(FakeGuest(), 'stored-state')
        self.assertEqual(out['result'], 'PASS', out['failed_steps'])
        detail = out['steps'][3]['detail']
        rows = detail['rows']
        self.assertTrue(rows and not [r for r in rows if r['steered']])
        # slice (c): meta.json's id altered alone is moved aside by the quiesce step, recorded
        # and returned, never reopened
        moved = [r['alteration']['pointer'] for r in rows if r['verdict'] == 'quarantined']
        self.assertEqual(moved, [['id']])
        self.assertEqual(detail['quarantined'], [r['n'] for r in rows if r['verdict'] == 'quarantined'])
        cycle = next(r['cycle'] for r in rows if r['verdict'] == 'quarantined')
        self.assertNotIn('reopen', cycle)
        self.assertIn('returned', cycle)

    def test_stored_state_finds_the_startup_hydration(self):
        out = self.run_drill(FakeGuest(hydrates=True, quiesce=False), 'stored-state')
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

    def test_stored_state_with_the_quiesce_step_on_a_hydrating_server(self):
        out = self.run_drill(FakeGuest(hydrates=True), 'stored-state')
        self.assertEqual(out['result'], 'PASS', out['failed_steps'])
        detail = out['steps'][3]['detail']
        self.assertEqual(detail['steering'], [])
        rewritten = [r['alteration'] for r in detail['rows'] if r['n'] in detail['rewritten_by_quiesce']]
        self.assertEqual([('combination' in a, a.get('pointer')) for a in rewritten],
                         [(False, ['execution_status']), (True, None)])

    def test_f2_closed_on_the_fixed_guest(self):
        out = self.run_drill(FakeGuest(hydrates=True), 'f2-closed')
        failing = [(s['step'], [r['check'] for r in (s.get('detail') or {}).get('checks') or []
                                if not r['ok']], (s.get('detail') or {}).get('message'))
                   for s in out['steps'] if not s['ok']]
        self.assertEqual(out['result'], 'PASS', failing)
        self.assertEqual(len(out['steps']), 8)

    def test_f2_closed_fails_on_a_guest_without_the_step(self):
        out = self.run_drill(FakeGuest(hydrates=True, quiesce=False), 'f2-closed')
        self.assertEqual(out['result'], 'FAIL')
        self.assertEqual(len(out['failed_steps']), 8, out['failed_steps'])
        self.assertIsNone(out['broken'])
        failing = {s['step'][:3]: {r['check'] for r in s['detail']['checks'] if not r['ok']}
                   for s in out['steps']}
        self.assertIn("no resume line in the server's start invocation", failing['A: '])
        self.assertIn('the stored working directory was not created', failing['A: '])
        self.assertIn("the real conversation's GET answers from its own record", failing['F: '])
        self.assertIn("the server's own start-up cleanup found 0 (no removal event from its "
                      'ExecStart to active)', failing['C: '])

    def test_stored_state_limit(self):
        out = self.run_drill(FakeGuest(), 'stored-state', limit=2)
        self.assertEqual(out['steps'][3]['detail']['run'], 2)


if __name__ == '__main__':
    unittest.main()
