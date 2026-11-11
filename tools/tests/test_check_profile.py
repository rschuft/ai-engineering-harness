"""Tests for tools/check_profile.py (stdlib unittest).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The checked-in profiles are checked as they are. Every negative case works on a
temporary copy of profiles/ (the checker reads pinned files relative to a root), so
the checkout is only read: one copy shared by the cases that only read it, and a
private copy for each case that writes into it.
"""
from pathlib import Path
import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / 'tools' / 'check_profile.py'
QEMU = 'strong-windows-qemu-whpx'
INCUS = 'strong-incus-vm'

_spec = importlib.util.spec_from_file_location('check_profile', CHECKER)
check_profile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_profile)


def run_checker(*args):
    return subprocess.run([sys.executable, '-I', '-B', str(CHECKER), *args],
                          capture_output=True, text=True, encoding='utf-8')


def load(name, root=REPO):
    return json.loads((root / 'profiles' / name / 'profile.json').read_text(encoding='utf-8'))


def replace_arg(profile, old, new):
    argv = profile['launch']['argv']
    argv[argv.index(old)] = new


class CheckedInProfiles(unittest.TestCase):
    category = 'contract'

    def test_both_profiles_pass(self):
        result = run_checker()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'PASS {QEMU}\n', result.stdout)
        self.assertIn(f'PASS {INCUS} (', result.stdout)
        self.assertNotIn('FAIL', result.stdout)

    def test_strict_passes_qemu_and_fails_incus_only_on_unknown_pins(self):
        self.assertEqual(run_checker('--strict', str(REPO / 'profiles' / QEMU)).returncode, 0)
        result = run_checker('--strict', str(REPO / 'profiles' / INCUS))
        self.assertEqual(result.returncode, 1)
        failures = [line for line in result.stdout.splitlines() if line.startswith('FAIL')]
        self.assertEqual(failures, [f'FAIL {INCUS} (4 unresolved pin(s))'])

    def test_qemu_profile_has_no_unresolved_pins(self):
        report = check_profile.check(load(QEMU))
        self.assertEqual((report.errors, report.unresolved), ([], []))


def tree_digest(root):
    """Every file under ROOT, by relative path, with its bytes' sha256."""
    return {path.relative_to(root).as_posix(): check_profile.sha256_file(path)
            for path in sorted(root.rglob('*')) if path.is_file()}


class Negative(unittest.TestCase):
    """Each mutation must produce a FAIL that names the broken rule.

    The copy of profiles/ (with the pinned lock and the cited evidence it reads) is made
    once per class and shared by the tests that only read it; mutations are made to the
    loaded profiles in memory. A test that writes into the tree first takes a private copy
    (private_tree), and every test checks that the shared copy is unchanged (plan leaf
    F-09.3)."""

    @classmethod
    def setUpClass(cls):
        cls.shared = Path(tempfile.mkdtemp(prefix='aieh-profile-test-'))
        cls.addClassCleanup(shutil.rmtree, cls.shared, ignore_errors=True)
        shutil.copytree(REPO / 'profiles', cls.shared / 'profiles')
        lock = Path('composition') / 'lock' / 'components.lock.json'   # the openapi pin, read only
        (cls.shared / lock.parent).mkdir(parents=True)
        shutil.copy(REPO / lock, cls.shared / lock)
        point = load(QEMU, cls.shared)['network']['enforcement_point']
        if isinstance(point, dict) and point.get('evidence'):       # cited evidence, read only
            (cls.shared / 'evidence').mkdir(exist_ok=True)
            shutil.copy(REPO / point['evidence'], cls.shared / point['evidence'])
        cls.shared_digest = tree_digest(cls.shared)

    def setUp(self):
        self.tmp = self.shared
        self.qemu = load(QEMU, self.tmp)
        self.incus = load(INCUS, self.tmp)

    def tearDown(self):
        self.assertEqual(tree_digest(self.shared), self.shared_digest,
                         'a test wrote into the shared copy: it must call private_tree() first')

    def private_tree(self):
        """A private copy of the tree, for a test that writes into it."""
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-profile-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shutil.copytree(self.shared, self.tmp, dirs_exist_ok=True)
        return self.tmp

    def errors(self, profile):
        return check_profile.check(profile, self.tmp).errors

    def assertFails(self, profile, fragment):
        errors = self.errors(profile)
        self.assertTrue(any(fragment in e for e in errors),
                        f'expected an error containing {fragment!r}, got {errors}')

    # unpinned inputs
    def test_unpinned_image(self):
        del self.qemu['boot_inputs']['image']['sha256']
        self.assertFails(self.qemu, 'boot_inputs.image: not pinned by sha256')

    def test_unpinned_firmware_without_declared_unknown(self):
        self.qemu['boot_inputs']['firmware']['sha256'] = None
        self.assertFails(self.qemu, 'boot_inputs.firmware: not pinned by digest')

    def test_unknown_pin_needs_a_reason(self):
        del self.incus['boot_inputs']['firmware']['unpinned_reason']
        self.assertFails(self.incus, 'boot_inputs.firmware: not pinned by digest')

    def test_missing_boot_input(self):
        del self.qemu['boot_inputs']['seed']
        self.assertFails(self.qemu, 'boot_inputs: seed missing')

    def test_tampered_seed_template(self):
        self.private_tree()
        path = self.tmp / 'profiles' / 'seed' / 'user-data.tmpl'
        path.write_bytes(path.read_bytes() + b'# changed\n')
        self.assertFails(self.qemu, 'seed.templates.user-data')
        self.assertFails(self.incus, 'seed.templates.user-data')

    def test_tampered_provider_lock(self):
        self.private_tree()
        path = self.tmp / 'profiles' / QEMU / 'qemu-msys2-ucrt64.lock.json'
        path.write_bytes(path.read_bytes().replace(b'11.1.3-1', b'11.1.2-1', 1))
        self.assertFails(self.qemu, 'provider.artifact_lock')

    def test_tampered_provision_lock(self):
        self.private_tree()
        path = self.tmp / 'profiles' / QEMU / 'provision.lock.json'
        path.write_bytes(path.read_bytes().replace(b'"tini"', b'"tinj"', 1))
        self.assertFails(self.qemu, 'provider.provision_lock: profiles/')

    def repinned_provision_lock(self, mutate):
        """Mutate the provision lock, then re-pin it, so only its shape check can fail."""
        self.private_tree()
        path = self.tmp / 'profiles' / QEMU / 'provision.lock.json'
        lock = json.loads(path.read_text(encoding='utf-8'))
        mutate(lock)
        data = (json.dumps(lock, indent=2) + '\n').encode('utf-8')
        path.write_bytes(data)
        self.qemu['provider']['provision_lock']['sha256'] = check_profile.sha256_file(path)
        return self.qemu

    def test_provision_lock_http_url(self):
        def mutate(lock):
            lock['debian']['packages'][0]['url'] = lock['debian']['packages'][0]['url'] \
                .replace('https://', 'http://')
        self.assertFails(self.repinned_provision_lock(mutate),
                         'provider.provision_lock: debian.packages.runc: url must start with')

    def test_provision_lock_package_at_another_timestamp(self):
        def mutate(lock):
            lock['debian']['packages'][0]['url'] = lock['debian']['packages'][0]['url'] \
                .replace('20261106T143859Z', '20261001T000000Z')
        self.assertFails(self.repinned_provision_lock(mutate), 'debian.packages.runc: url')

    def test_provision_lock_image_id_differs_from_config(self):
        def mutate(lock):
            lock['image']['image_id'] = 'sha256:' + '0' * 64
        self.assertFails(self.repinned_provision_lock(mutate),
                         'image.image_id: must equal config_digest')

    def test_provision_lock_unpinned_crane(self):
        def mutate(lock):
            del lock['tools']['crane']['member']['sha256']
        self.assertFails(self.repinned_provision_lock(mutate), 'tools.crane.member')

    def test_provider_binary_pin_disagrees(self):
        self.qemu['boot_inputs']['provider_binary']['sha256'] = '0' * 64
        self.assertFails(self.qemu, 'differs from the provider binary pin')

    def test_drive_option_is_refused(self):
        self.qemu['launch']['argv'] += ['-drive', 'file={instance_dir}/root.qcow2,if=virtio']
        self.assertFails(self.qemu, '-drive is not an allowed option')

    def test_literal_path_bypasses_pins(self):
        replace_arg(self.qemu, 'driver=file,node-name=base-file,filename={input:image},read-only=on',
                    'driver=file,node-name=base-file,filename=D:/images/other.qcow2,read-only=on')
        self.assertFails(self.qemu, 'literal host path')

    def test_undeclared_per_instance_disk(self):
        replace_arg(self.qemu, 'driver=file,node-name=scratch-file,filename={instance_dir}/scratch.qcow2',
                    'driver=file,node-name=scratch-file,filename={instance_dir}/extra.qcow2')
        self.assertFails(self.qemu, 'undeclared per-instance disk extra.qcow2')

    def test_option_rom_must_be_disabled(self):
        replace_arg(self.qemu, 'virtio-net-pci,netdev=net0,romfile=', 'virtio-net-pci,netdev=net0')
        self.assertFails(self.qemu, 'romfile=')

    # host shares
    def test_virtfs_share(self):
        self.qemu['launch']['argv'] += ['-virtfs', 'local,path=C:/Users/x,mount_tag=h,security_model=none']
        self.assertFails(self.qemu, '-virtfs is not an allowed option')

    def test_vvfat_share(self):
        replace_arg(self.qemu, 'driver=raw,node-name=seed,file=seed-file,read-only=on',
                    'driver=vvfat,node-name=seed,dir=C:/Users/x,read-only=on')
        self.assertFails(self.qemu, "driver 'vvfat' is not allowed")

    def test_smb_share(self):
        replace_arg(self.qemu, 'user,id=net0,restrict=on,ipv6=off,hostfwd=tcp:127.0.0.1:{ssh_port}-:22',
                    'user,id=net0,restrict=on,ipv6=off,smb=C:/Users/x,hostfwd=tcp:127.0.0.1:{ssh_port}-:22')
        self.assertFails(self.qemu, 'smb= exposes host files')

    def test_declared_host_share(self):
        self.qemu['host_shares'] = [{'path': 'D:/exchange'}]
        self.assertFails(self.qemu, 'host_shares: must be an empty list')

    def test_usb_device(self):
        self.qemu['launch']['argv'] += ['-device', 'qemu-xhci']
        self.assertFails(self.qemu, '-device qemu-xhci is not allowed')

    def test_incus_host_path_disk(self):
        self.private_tree()
        path = self.tmp / 'profiles' / INCUS / 'incus-profile.yaml'
        text = path.read_text(encoding='utf-8').replace(
            '"source": "agent:config"', '"source": "/home/owner", "path": "/mnt/home"')
        path.write_text(text, encoding='utf-8', newline='\n')
        self.assertFails(self.incus, 'disk device agent is a host share')

    # forwards
    def test_hostfwd_on_all_interfaces(self):
        replace_arg(self.qemu, 'user,id=net0,restrict=on,ipv6=off,hostfwd=tcp:127.0.0.1:{ssh_port}-:22',
                    'user,id=net0,restrict=on,ipv6=off,hostfwd=tcp::{ssh_port}-:22')
        self.assertFails(self.qemu, 'must bind to 127.0.0.1')

    def test_hostfwd_on_lan_address(self):
        replace_arg(self.qemu, 'user,id=net0,restrict=on,ipv6=off,hostfwd=tcp:127.0.0.1:{ssh_port}-:22',
                    'user,id=net0,restrict=on,ipv6=off,hostfwd=tcp:0.0.0.0:{ssh_port}-:22')
        self.assertFails(self.qemu, 'hostfwd=tcp:0.0.0.0:{ssh_port}-:22 must bind to 127.0.0.1')

    def test_qmp_on_all_interfaces(self):
        replace_arg(self.qemu, 'socket,id=qmp,host=127.0.0.1,port={qmp_port},server=on,wait=off',
                    'socket,id=qmp,host=0.0.0.0,port={qmp_port},server=on,wait=off')
        self.assertFails(self.qemu, 'must bind to 127.0.0.1')

    # monitors
    def test_deprecated_mon_is_refused(self):
        argv = self.qemu['launch']['argv']
        index = argv.index('-object')
        argv[index:index + 2] = ['-mon', 'chardev=qmp,mode=control']
        self.assertFails(self.qemu, '-mon is not an allowed option')

    def test_hmp_monitor_object_is_refused(self):
        replace_arg(self.qemu, 'monitor-qmp,id=qmp-monitor,chardev=qmp',
                    'monitor-hmp,id=qmp-monitor,chardev=qmp')
        self.assertFails(self.qemu, "-object 'monitor-hmp' is not allowed")

    def test_other_object_type_is_refused(self):
        self.qemu['launch']['argv'] += [
            '-object', 'memory-backend-file,id=m,size=1G,mem-path=C:/Users/x,share=on']
        self.assertFails(self.qemu, "-object 'memory-backend-file' is not allowed")

    def test_qmp_monitor_unknown_property(self):
        replace_arg(self.qemu, 'monitor-qmp,id=qmp-monitor,chardev=qmp',
                    'monitor-qmp,id=qmp-monitor,chardev=qmp,mode=readline')
        self.assertFails(self.qemu, "property ['mode'] is not allowed")

    def test_qmp_monitor_needs_id_and_chardev(self):
        replace_arg(self.qemu, 'monitor-qmp,id=qmp-monitor,chardev=qmp', 'monitor-qmp,chardev=qmp')
        self.assertFails(self.qemu, 'needs id= and chardev=')

    def test_qmp_monitor_on_a_file_chardev(self):
        replace_arg(self.qemu, 'monitor-qmp,id=qmp-monitor,chardev=qmp',
                    'monitor-qmp,id=qmp-monitor,chardev=serial0')
        self.assertFails(self.qemu, 'monitor-qmp must use a loopback socket chardev')

    def test_qmp_monitor_on_an_undeclared_chardev(self):
        replace_arg(self.qemu, 'monitor-qmp,id=qmp-monitor,chardev=qmp',
                    'monitor-qmp,id=qmp-monitor,chardev=other')
        self.assertFails(self.qemu, 'monitor-qmp must use a loopback socket chardev')

    def test_declared_endpoint_off_loopback(self):
        self.qemu['network']['endpoints'][0]['host_bind'] = '0.0.0.0'
        self.assertFails(self.qemu, 'management endpoint binds to 0.0.0.0')

    def test_restrict_off(self):
        replace_arg(self.qemu, 'user,id=net0,restrict=on,ipv6=off,hostfwd=tcp:127.0.0.1:{ssh_port}-:22',
                    'user,id=net0,restrict=off,ipv6=off,hostfwd=tcp:127.0.0.1:{ssh_port}-:22')
        self.assertFails(self.qemu, 'needs restrict=on')

    def test_tap_network(self):
        replace_arg(self.qemu, 'user,id=net0,restrict=on,ipv6=off,hostfwd=tcp:127.0.0.1:{ssh_port}-:22',
                    'tap,id=net0,ifname=tap0')
        self.assertFails(self.qemu, 'only user-mode NAT is allowed')

    def test_incus_proxy_on_all_interfaces(self):
        self.private_tree()
        path = self.tmp / 'profiles' / INCUS / 'incus-profile.yaml'
        text = path.read_text(encoding='utf-8').replace(
            '"eth0": {', '"ssh": {"type": "proxy", "listen": "tcp:0.0.0.0:2222", '
            '"connect": "tcp:127.0.0.1:22"},\n    "eth0": {')
        path.write_text(text, encoding='utf-8', newline='\n')
        self.assertFails(self.incus, 'proxy ssh must listen on 127.0.0.1')

    # accelerator
    def test_tcg_as_second_accelerator(self):
        self.qemu['launch']['argv'] += ['-accel', 'tcg']
        self.assertFails(self.qemu, 'TCG fallback')
        self.assertFails(self.qemu, 'exactly one accelerator')

    def test_tcg_through_machine_accel(self):
        replace_arg(self.qemu, 'type=pc-q35-11.1', 'type=pc-q35-11.1,accel=whpx:tcg')
        self.assertFails(self.qemu, 'TCG fallback')

    def test_no_accelerator_means_tcg(self):
        argv = self.qemu['launch']['argv']
        index = argv.index('-accel')
        del argv[index:index + 2]
        self.assertFails(self.qemu, "exactly one accelerator (whpx) required, found []")

    def test_declared_fallback(self):
        self.qemu['accelerator']['fallback'] = 'tcg'
        self.assertFails(self.qemu, 'fallback must be "none"')

    # labels
    def test_missing_tier(self):
        del self.qemu['labels']['tier']
        self.assertFails(self.qemu, 'labels: missing tier')

    def test_missing_nesting(self):
        del self.incus['labels']['nesting']
        self.assertFails(self.incus, 'labels: missing nesting')

    def test_unknown_tier(self):
        self.qemu['labels']['tier'] = 'medium'
        self.assertFails(self.qemu, "tier 'medium' is not one of")

    def test_name_without_tier_prefix(self):
        self.qemu['name'] = 'windows-qemu-whpx'
        self.assertFails(self.qemu, 'does not carry the tier prefix strong-')

    # ceilings
    def test_missing_ceiling(self):
        del self.qemu['ceilings']['scratch_disk_gib']
        self.assertFails(self.qemu, 'ceilings: scratch_disk_gib must be a positive integer')

    def test_smp_differs_from_ceiling(self):
        self.qemu['ceilings']['vcpu'] = 4
        self.assertFails(self.qemu, 'does not match ceilings.vcpu')

    def test_memory_differs_from_ceiling(self):
        self.incus['ceilings']['memory_mib'] = 8192
        self.assertFails(self.incus, 'limits.memory does not match')

    # other contract rules
    def test_nested_virtualization_not_masked(self):
        replace_arg(self.qemu, 'max,vmx=off,svm=off', 'max')
        self.assertFails(self.qemu, 'must turn vmx off')

    def test_incus_nesting_not_masked(self):
        self.private_tree()
        path = self.tmp / 'profiles' / INCUS / 'incus-profile.yaml'
        text = path.read_text(encoding='utf-8').replace(
            '"security.nesting": "false"', '"security.nesting": "true"')
        path.write_text(text, encoding='utf-8', newline='\n')
        self.assertFails(self.incus, 'security.nesting must be "false"')

    def test_state_dir_defaulted(self):
        self.qemu['state_dir']['default'] = 'D:\\aieh-guest-state'
        self.assertFails(self.qemu, 'must not be defaulted')

    def test_state_dir_in_owner_profile(self):
        self.qemu['state_dir']['proposed'] = 'C:\\Users\\owner\\aieh'
        self.assertFails(self.qemu, "inside the Owner's profile")

    def test_lifecycle_not_closed_set(self):
        self.qemu['lifecycle']['operations'].append('snapshot')
        self.assertFails(self.qemu, 'lifecycle: operations must be exactly')

    def test_stop_timeout_above_contract_maximum(self):
        self.qemu['lifecycle']['stop_timeout_s'] = 301
        self.assertFails(self.qemu, 'stop_timeout_s must be an integer from 1 to 300')

    def test_operational_without_evidence(self):
        self.qemu['status']['operational'] = True
        self.qemu['status'].pop('operational_evidence', None)
        self.assertFails(self.qemu, 'operational must be false until C6')

    def test_mutations_do_not_leak_between_tests(self):
        self.assertEqual(self.errors(copy.deepcopy(self.qemu)), [])
        self.assertEqual(self.errors(copy.deepcopy(self.incus)), [])

    # enforcement point (profiles P7; F-03.3.2)
    def qualified(self):
        self.private_tree()
        (self.tmp / 'evidence').mkdir(exist_ok=True)
        (self.tmp / 'evidence' / 'net.md').write_text('x', encoding='utf-8')
        net = self.qemu['network']
        net['enforcement_point'] = {'mechanism': 'SLIRP restrict=on', 'status': 'qualified',
                                    'qualified_by': 'F-03.3.2', 'evidence': 'evidence/net.md'}
        net['reachability'] = {
            'permitted': [{'path': 'guestfwd', 'protocol': 'tcp', 'observed': 'exchanged'}],
            'denied': [{'path': '1.1.1.1:443', 'protocol': 'tcp', 'observed': 'timeout'}]}
        return self.qemu

    def test_qualified_enforcement_point_passes(self):
        self.assertEqual(self.errors(self.qualified()), [])

    def test_enforcement_point_status(self):
        self.qualified()['network']['enforcement_point']['status'] = 'probably'
        self.assertFails(self.qemu, 'enforcement_point.status must be one of')

    def test_enforcement_point_mechanism(self):
        self.qualified()['network']['enforcement_point']['mechanism'] = ' '
        self.assertFails(self.qemu, 'enforcement_point.mechanism must be named')

    def test_qualified_needs_evidence(self):
        point = self.qualified()['network']['enforcement_point']
        for value, fragment in ((None, 'cites its evidence'), ('notes/net.md', 'cites its evidence'),
                                ('evidence/absent.md', 'evidence/absent.md is missing')):
            point['evidence'] = value
            self.assertFails(self.qemu, fragment)

    def test_qualified_needs_the_leaf(self):
        del self.qualified()['network']['enforcement_point']['qualified_by']
        self.assertFails(self.qemu, 'names the leaf that tested it')

    def test_qualified_needs_a_reachability_table(self):
        net = self.qualified()['network']
        net['reachability']['denied'] = []
        self.assertFails(self.qemu, 'reachability.denied must list at least one path')
        net['reachability']['denied'] = [{'path': 'x', 'protocol': 'tcp'}]
        self.assertFails(self.qemu, 'reachability.denied[0] needs')
        del net['reachability']
        self.assertFails(self.qemu, 'needs a reachability table')

    def test_failed_needs_evidence_not_a_table(self):
        net = self.qualified()['network']
        net['enforcement_point']['status'] = 'failed'
        del net['reachability']
        self.assertEqual(self.errors(self.qemu), [])

    def test_validation_overlay_is_pinned(self):
        point = self.qualified()['network']['enforcement_point']
        point['validation_overlay'] = {
            'path': 'profiles/strong-windows-qemu-whpx/validation/netprobe/netprobe.py',
            'sha256': '0' * 64}
        self.assertFails(self.qemu, 'does not match its pinned sha256')

    def test_guestfwd_without_an_active_endpoint(self):
        old = 'user,id=net0,restrict=on,ipv6=off,hostfwd=tcp:127.0.0.1:{ssh_port}-:22'
        replace_arg(self.qemu, old, old + ',guestfwd=tcp:10.0.2.100:7000-tcp:127.0.0.1:4000')
        self.assertFails(self.qemu, 'active guestfwd endpoint(s) are declared')

    def test_deferred_endpoint_with_a_port(self):
        endpoint = next(e for e in self.qemu['network']['endpoints'] if e['class'] == 'provision')
        endpoint['host_port'] = 4000
        self.assertFails(self.qemu, 'deferred provision endpoint declares a host port')

    # the inference endpoint and its opt-in composition (decision 0015; S-03.2 slice 2)
    def inference(self, profile=None):
        profile = profile or self.qemu
        return (next(e for e in profile['network']['endpoints'] if e['class'] == 'inference'),
                profile['network']['inference_composition'])

    def test_inference_endpoint_is_a_remote_forward_never_a_guestfwd(self):
        entry, _ = self.inference()
        self.assertEqual((entry['mechanism'], entry['guest_address'], entry['guest_port']),
                         ('ssh-remote-forward', '172.17.0.1', 8090))
        self.assertTrue(entry['status'].startswith('planned'))
        for key, value, fragment in (
                ('mechanism', 'guestfwd=tcp:172.17.0.1:8090-tcp:127.0.0.1:1', 'not a guestfwd'),
                ('mechanism', 'ssh-local-forward', 'not a guestfwd'),
                ('status', 'enabled', 'status must start with'),
                ('status', 'active: observed', 'cites the evidence of its qualification'),
                ('guest_address', '172.17.0', 'docker0 gateway'),
                ('guest_port', 22, 'guest_port must be'),
                ('guest_port', 8000, 'guest_port must be'),
                ('guest_port', '8090', 'guest_port must be'),
                ('forward_owner', ' ', 'forward_owner'),
                ('direction', 'host-to-guest', 'forward_owner')):
            saved = entry[key]
            entry[key] = value
            self.assertFails(self.qemu, fragment)
            entry[key] = saved
        old = 'user,id=net0,restrict=on,ipv6=off,hostfwd=tcp:127.0.0.1:{ssh_port}-:22'
        replace_arg(self.qemu, old, old + ',guestfwd=tcp:172.17.0.1:8090-tcp:127.0.0.1:4000')
        self.assertFails(self.qemu, 'guestfwd rule count stays zero')
        self.assertFails(self.qemu, 'active guestfwd endpoint(s) are declared')

    def test_inference_composition_declarations(self):
        entry, comp = self.inference()
        self.assertEqual(self.errors(self.qemu), [])
        for path, value, fragment in (
                (('option',), 'create --provision', '.option'),
                (('status',), 'active: x', '.status'),
                (('default',), '', '.default: required'),
                (('cost_map_control',), None, '.cost_map_control: required'),
                (('sshd', 'replaces'), 'AllowTcpForwarding yes', '.sshd:'),
                (('sshd', 'directives'), ['AllowTcpForwarding yes', 'GatewayPorts yes',
                                          'PermitListen 172.17.0.1:8090'], '.sshd:'),
                (('sshd', 'effective', 'permitlisten'), 'any', '.sshd:'),
                (('sshd', 'listener_processes'), ['sshd-session'], '.sshd:'),
                (('container_guard_allow', 'families'), ['iptables', 'ip6tables'],
                 '.container_guard_allow'),
                (('container_guard_allow', 'rule'), '-i docker0 -p tcp -m tcp --dport 8090 -j ACCEPT',
                 '.container_guard_allow'),
                (('daemon_json',), {'bip': '172.17.0.1/16'}, '.daemon_json'),
                (('daemon_json', 'dns'), ['8.8.8.8'], '.daemon_json'),
                (('forward_session', 'record'), 'C:/x/inference-forward.json', '.forward_session'),
                (('job_sweep', 'edges'), [['tcp', '172.17.0.1', 8090, 'the endpoint itself']],
                 '.job_sweep.edges'),
                (('job_sweep', 'edges'), [['tcp', '1.1.1.1', 443, 'off-host']], '.job_sweep.edges'),
                (('job_sweep', 'edges'), [], '.job_sweep.edges'),
                (('job_sweep', 'rule'), '', '.job_sweep: endpoint'),
                (('inspection',), [], '.inspection')):
            node = comp
            for part in path[:-1]:
                node = node[part]
            saved = copy.deepcopy(node.get(path[-1]))
            node[path[-1]] = value
            self.assertFails(self.qemu, fragment)
            node[path[-1]] = saved
        self.assertEqual(self.errors(self.qemu), [])
        self.qemu['provisioning']['moby']['daemon_json']['dns'] = ['172.17.0.1']
        self.assertFails(self.qemu, 'provisioning.moby.daemon_json must not carry')
        del self.qemu['provisioning']['moby']['daemon_json']['dns']
        del self.qemu['network']['inference_composition']
        self.assertFails(self.qemu, 'network.inference_composition: required')
        entry['status'], entry['host_port'] = 'deferred: for the test', None
        self.qemu['network']['inference_composition'] = comp
        self.assertFails(self.qemu, 'declared while the inference endpoint is deferred')
        del self.qemu['network']['inference_composition']
        self.assertNotIn('inference', ' '.join(self.errors(self.qemu)))

    def test_inference_forward_session_declarations(self):
        """S-03.2 slice 3: the record's fields, the forward's ssh options and its ceiling."""
        _, comp = self.inference()
        session = comp['forward_session']
        self.assertEqual(session['fields'], check_profile.FORWARD_FIELDS)
        self.assertEqual(check_profile.forward_option_problems(session['ssh_options']), [])
        for key, value, fragment in (
                ('fields', check_profile.FORWARD_FIELDS[:-1], '.forward_session.fields'),
                ('ssh_options', ['-N', '-v', '-o', 'ExitOnForwardFailure=no', '-o',
                                 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3'],
                 '-o ExitOnForwardFailure=no'),
                ('ssh_options', session['ssh_options'] + ['-L', '1:2:3'], "'-L'"),
                ('ssh_options', session['ssh_options'] + ['-o', 'GatewayPorts=yes'], 'GatewayPorts'),
                ('ssh_options', session['ssh_options'][1:], "missing ['-N']"),
                ('ssh_options', session['ssh_options'][:-2], "missing ['ServerAliveCountMax']"),
                ('ssh_options', session['ssh_options'] + ['-N'], "['-N']"),
                ('ssh_options', ['-N', '-v', '-o', 'ExitOnForwardFailure=yes', '-o',
                                 'ServerAliveInterval=0', '-o', 'ServerAliveCountMax=3'],
                 'ServerAliveInterval=0'),
                ('ssh_options', ['-N', '-v', '-o', 'ExitOnForwardFailure=yes', '-o',
                                 'ServerAliveInterval=x', '-o', 'ServerAliveCountMax=3'],
                 'ServerAliveInterval=x'),
                ('ssh_options', ['-N', '-v', '-o', 'ExitOnForwardFailure=yes', '-o',
                                 'ServerAliveInterval=15', '-o', 'ServerAliveInterval=15', '-o',
                                 'ServerAliveCountMax=3'], 'ServerAliveInterval=15'),
                ('ssh_options', ['-N', '-v', '-o', 'ExitOnForwardFailure', '-o',
                                 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3'],
                 '-o ExitOnForwardFailure'),
                ('ssh_options', ['-N', '-v', '-o'], "'-o'"),
                ('ssh_options', '-N -v', 'a list of strings'),
                ('establish_ceiling_s', 4, 'establish_ceiling_s'),
                ('establish_ceiling_s', 601, 'establish_ceiling_s'),
                ('establish_ceiling_s', True, 'establish_ceiling_s'),
                ('established_signal', ' ', '.forward_session.established_signal: required'),
                ('broker_port', None, '.forward_session.broker_port: required')):
            saved = copy.deepcopy(session.get(key))
            session[key] = value
            self.assertFails(self.qemu, fragment)
            session[key] = saved
        self.assertEqual(self.errors(self.qemu), [])

    def test_inference_composition_states_from_the_pinned_overlay(self):
        """Off and on, as the generator composes them: each overlay loosening is named."""
        _, comp = self.inference()
        tmp = self.private_tree()
        path = tmp / comp['seed_overlay']['path']
        original = json.loads(path.read_text(encoding='utf-8'))

        def with_overlay(edit, fragment):
            overlay = copy.deepcopy(original)
            edit(overlay['edits'])
            data = (json.dumps(overlay, indent=2) + '\n').encode()
            path.write_bytes(data)
            comp['seed_overlay']['sha256'] = check_profile.hashlib.sha256(data).hexdigest()
            self.assertFails(self.qemu, fragment)

        def edit_of(edits, ident):
            return next(e for e in edits if e['id'] == ident)
        with_overlay(lambda e: edit_of(e, 'sshd-forwarding')['replacement'].append(
            '      PermitOpen any'), 'on, /etc/ssh/sshd_config.d/10-aieh.conf must be')
        with_overlay(lambda e: edit_of(e, 'sshd-forwarding').update(
            replacement=['      AllowTcpForwarding yes', '      GatewayPorts clientspecified',
                         '      PermitListen {{inference_address}}:{{inference_port}}']),
            'on, /etc/ssh/sshd_config.d/10-aieh.conf must be')
        with_overlay(lambda e: edit_of(e, 'guard-allow')['replacement'].__setitem__(
            3, "      INPUT_ALLOW = {'iptables': ('-d {{inference_address}}/32 -i docker0 -p tcp "
               "-m tcp --dport {{inference_port}} -j ACCEPT',), 'ip6tables': ('-j ACCEPT',)}"),
            'in iptables only')
        with_overlay(lambda e: e.remove(edit_of(e, 'guard-observe')), 'install and verify the one ACCEPT')
        with_overlay(lambda e: e.remove(edit_of(e, 'guard-install')), 'install and verify the one ACCEPT')
        with_overlay(lambda e: e.remove(edit_of(e, 'facts-call')), 'sshd -T')
        with_overlay(lambda e: edit_of(e, 'facts-function')['replacement'].insert(1, '      def ('),
                     'does not compile')
        with_overlay(lambda e: edit_of(e, 'guard-install').update(anchor=['          for x in RULES:']),
                     'the seed overlay does not apply')
        path.write_bytes(json.dumps(original).encode())
        self.assertFails(self.qemu, 'does not match its pinned sha256')
        # off: a template whose guard installs other rules is refused
        template = tmp / 'profiles' / 'seed' / 'user-data.tmpl'
        base = template.read_text(encoding='utf-8')
        fewer = base.replace("               '-p tcp -j REJECT --reject-with tcp-reset',\n"
                             "               '-j REJECT')\n      EGRESS_CHAIN",
                             "               '-j REJECT')\n      EGRESS_CHAIN")
        self.assertNotEqual(fewer, base)
        template.write_bytes(fewer.encode())
        pin = self.qemu['boot_inputs']['seed']['templates']['user-data']['sha256']
        self.qemu['boot_inputs']['seed']['templates']['user-data']['sha256'] = \
            check_profile.hashlib.sha256(fewer.encode()).hexdigest()
        path.write_bytes(json.dumps(original).encode())
        comp['seed_overlay']['sha256'] = check_profile.sha256_file(path)
        self.assertFails(self.qemu, 'off, /usr/local/sbin/aieh-container-guard must install')
        template.write_bytes(base.encode())
        self.qemu['boot_inputs']['seed']['templates']['user-data']['sha256'] = pin
        # off: a template whose drop-in already forwards is refused
        text = template.read_text(encoding='utf-8').replace(
            '      PermitTunnel no\n', '      PermitTunnel no\n      GatewayPorts yes\n')
        template.write_bytes(text.encode())
        self.qemu['boot_inputs']['seed']['templates']['user-data']['sha256'] = \
            check_profile.hashlib.sha256(text.encode()).hexdigest()
        path.write_bytes(json.dumps(original).encode())
        comp['seed_overlay']['sha256'] = check_profile.sha256_file(path)
        self.assertFails(self.qemu, 'off, the seed\'s /etc/ssh/sshd_config.d/10-aieh.conf')

    def test_guard_rules_of_reads_the_seeded_script(self):
        rules = check_profile.guard_rules_of(
            "RULES = ('a', 'b')\nINPUT_ALLOW = {'iptables': ('x',)}\n"
            "def rules(tool):\n    return RULES[:1] + INPUT_ALLOW.get(tool, ()) + RULES[1:]\n"
            "if __name__ == '__main__':\n    raise SystemExit('never run')\n")
        self.assertEqual(rules, {'RULES': ['a', 'b'], 'iptables': ['a', 'x', 'b'],
                                 'ip6tables': ['a', 'b']})
        self.assertEqual(check_profile.guard_rules_of("RULES = ('a',)\n"), {'RULES': ['a']})
        # without both an install and an observe function nothing is simulated
        self.assertEqual(check_profile.guard_rules_of(
            "RULES = ('a',)\nCHAIN = 'X'\ndef install(tool):\n    raise SystemExit('never')\n"),
            {'RULES': ['a']})

    # guest storage and exchange (profiles P3, P4; F-03.3.1)
    def test_guest_storage_required_for_qemu(self):
        del self.qemu['guest_storage']
        self.assertFails(self.qemu, 'guest_storage: missing')

    def test_exchange_required_for_qemu(self):
        del self.qemu['exchange']
        self.assertFails(self.qemu, 'exchange: missing')

    def test_share_fstype_in_mount_table(self):
        self.qemu['guest_storage']['mounts'].append(
            {'target': '/mnt/host', 'fstype': '9p', 'source': 'host0'})
        self.assertFails(self.qemu, "file system type '9p' is a share type")

    def test_fuse_subtype_in_mount_table(self):
        self.qemu['guest_storage']['mounts'].append(
            {'target': '/mnt/host', 'fstype': 'fuse.sshfs', 'source': 'x'})
        self.assertFails(self.qemu, 'is a share type')

    def test_forbidden_path_in_mount_table(self):
        self.qemu['guest_storage']['mounts'].append(
            {'target': '/mnt/c', 'fstype': 'ext4', 'disk': 'scratch'})
        self.assertFails(self.qemu, '/mnt/c is a forbidden path')

    def test_contract_share_types_must_be_forbidden(self):
        self.qemu['guest_storage']['forbidden_fstypes'].remove('virtiofs')
        self.assertFails(self.qemu, 'forbidden_fstypes: must include')

    def test_mount_on_configuration_medium(self):
        self.qemu['guest_storage']['mounts'].append(
            {'target': '/mnt/seed', 'fstype': 'iso9660', 'disk': 'seed'})
        self.assertFails(self.qemu, "disk 'seed' is not the root or scratch device")

    def test_writable_configuration_medium(self):
        self.qemu['guest_storage']['block_devices']['seed']['read_only'] = False
        self.assertFails(self.qemu, 'configuration medium must be read-only')

    def test_optional_mount_needs_a_reason(self):
        self.qemu['guest_storage']['mounts'][-1]['optional'] = True
        self.assertFails(self.qemu, 'optional must give the reason')

    # provisioning (F-04.1b)
    def test_provisioning_daemon_json_tcp_socket(self):
        self.qemu['provisioning']['moby']['daemon_json']['hosts'] = ['tcp://0.0.0.0:2375']
        self.assertFails(self.qemu, 'hosts is not allowed')

    def test_provisioning_no_new_privileges(self):
        self.qemu['provisioning']['moby']['daemon_json']['no-new-privileges'] = False
        self.assertFails(self.qemu, 'no-new-privileges must be true')

    def test_provisioning_data_root_off_scratch(self):
        self.qemu['provisioning']['moby']['daemon_json']['data-root'] = '/var/lib/docker'
        self.assertFails(self.qemu, 'data-root differs from moby.data_root')
        dirs = self.qemu['guest_storage']['directories']
        next(d for d in dirs if d['role'] == 'moby-data-root')['mount'] = '/'
        self.assertFails(self.qemu, 'must be on the scratch disk')

    def test_provisioning_socket_open_to_others(self):
        self.qemu['provisioning']['moby']['sockets'][0]['mode'] = '666'
        self.assertFails(self.qemu, 'no access for others')
        self.qemu['provisioning']['moby']['sockets'][0].update(mode='660', group='agent')
        self.assertFails(self.qemu, 'no access for others')

    def test_provisioning_containerd_cri_and_docker0_ipv6(self):
        moby = self.qemu['provisioning']['moby']
        moby['containerd_config']['content'] = 'version = 2' + chr(10)
        self.assertFails(self.qemu, "containerd's CRI plugin")
        moby['sysctl']['content'] = '# nothing' + chr(10)
        self.assertFails(self.qemu, 'turn IPv6 off on docker0')

    def test_provisioning_agent_in_docker_group(self):
        self.qemu['provisioning']['moby']['agent_in_docker_group'] = True
        self.assertFails(self.qemu, 'agent_in_docker_group: must be false')

    def test_provisioning_image_tag(self):
        for tag in ('aieh/agent-server:latest', 'ghcr.io/openhands/agent-server:1.60.1',
                    'agent-server:1', 'aieh/agent-server'):
            self.qemu['provisioning']['image']['local_tag'] = tag
            self.assertFails(self.qemu, 'local repository:tag')

    def test_provisioning_server_version_follows_the_lock(self):
        self.qemu['provisioning']['moby']['server_version'] = '27.0.0'
        self.assertFails(self.qemu, 'upstream version of the locked docker.io')

    def test_provisioning_upload_outside_scratch_and_bounds(self):
        self.qemu['provisioning']['upload']['guest_dir'] = '/tmp/provision'
        self.assertFails(self.qemu, 'inside the agent scratch directory')
        self.qemu['provisioning']['upload']['max_bytes'] = 0
        self.assertFails(self.qemu, 'upload.max_bytes: must be a positive integer')
        self.qemu['provisioning']['upload']['roles'] = ['deb', 'script']
        self.assertFails(self.qemu, 'provisioning.upload.roles')

    def test_provisioned_only_directories(self):
        dirs = self.qemu['guest_storage']['directories']
        next(d for d in dirs if d['role'] == 'moby-data-root').pop('provisioned_only')
        self.assertFails(self.qemu, 'marked provisioned_only: true')
        next(d for d in dirs if d['role'] == 'scratch')['provisioned_only'] = True
        self.assertFails(self.qemu, 'never provisioned_only')
        del self.qemu['provisioning']
        self.assertFails(self.qemu, 'needs a provisioning block')

    def test_committed_provisioning_passes(self):
        self.assertEqual([e for e in self.errors(self.qemu) if 'provision' in e], [])

    def test_wildcard_only_as_whole_component(self):
        self.qemu['guest_storage']['mounts'].append(
            {'target': '/run/x*/y', 'fstype': 'tmpfs', 'source': 'tmpfs'})
        self.assertFails(self.qemu, 'wildcard is allowed only')

    def test_block_device_host_path(self):
        self.qemu['guest_storage']['block_devices']['scratch']['file'] = 'C:/Users/x/disk.qcow2'
        self.assertFails(self.qemu, 'no host path')

    def test_undeclared_blockdev_in_argv(self):
        self.qemu['launch']['argv'] += [
            '-blockdev', 'driver=file,node-name=extra-file,filename={instance_dir}/scratch.qcow2']
        self.assertFails(self.qemu, '-blockdev extra-file is not in guest_storage')

    def test_undeclared_virtio_blk_device(self):
        self.qemu['launch']['argv'] += ['-device', 'virtio-blk-pci,drive=base,serial=base']
        self.assertFails(self.qemu, 'virtio-blk devices')

    def test_declared_node_missing_from_argv(self):
        self.qemu['guest_storage']['block_devices']['extra'] = {
            'role': 'configuration-medium', 'serial': 'extra', 'read_only': True, 'mounted': False,
            'node': 'extra', 'file_node': 'extra-file', 'file': '{instance_dir}/extra.iso'}
        self.assertFails(self.qemu, 'node extra has no -blockdev')

    def test_read_only_flag_disagrees_with_argv(self):
        self.qemu['guest_storage']['block_devices']['scratch']['read_only'] = True
        self.assertFails(self.qemu, 'the scratch disk is writable')
        self.assertFails(self.qemu, 'read_only differs from -blockdev scratch')

    def test_serial_disagrees_with_argv(self):
        self.qemu['guest_storage']['block_devices']['seed']['serial'] = 'seed'
        self.assertFails(self.qemu, 'virtio-blk devices')

    def test_exchange_directory_must_match(self):
        self.qemu['guest_storage']['directories'][0]['path'] = '/home/agent/other'
        self.assertFails(self.qemu, 'differs from exchange.guest_dir')

    def test_scratch_directory_on_scratch_disk(self):
        self.qemu['guest_storage']['directories'][1]['mount'] = '/'
        self.qemu['guest_storage']['directories'][1]['path'] = '/srv/agent'
        self.assertFails(self.qemu, 'scratch directory must be on the scratch disk')

    def test_directory_mode(self):
        self.qemu['guest_storage']['directories'][0]['mode'] = 'rwx'
        self.assertFails(self.qemu, 'mode must be octal digits')

    def test_virtio_counts_match_argv(self):
        self.qemu['guest_storage']['virtio_devices']['block'] = 4
        self.assertFails(self.qemu, 'virtio_devices')

    def test_exchange_staging_outside_state(self):
        self.qemu['exchange']['host_staging'] = 'C:/Users/x/staging'
        self.assertFails(self.qemu, 'exchange.host_staging')

    def test_exchange_name_pattern_admits_separator(self):
        self.qemu['exchange']['pull']['name_pattern'] = '^[A-Za-z0-9/._-]+$'
        self.assertFails(self.qemu, 'exchange.pull.name_pattern')

    def test_exchange_push_one_branch(self):
        self.qemu['exchange']['push']['refs'] = 2
        self.assertFails(self.qemu, 'exactly one branch')

    def test_exchange_bounds_positive(self):
        self.qemu['exchange']['push']['max_bytes'] = 0
        self.assertFails(self.qemu, 'exchange.push.max_bytes')


class AgentServerBlock(unittest.TestCase):
    """F-04.1 slice (c): provisioning.agent_server, the agent-server directories and the
    conversation fixture; each mutation must FAIL naming the rule."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-profile-as-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(REPO / 'profiles', self.tmp / 'profiles')
        lock = Path('composition') / 'lock' / 'components.lock.json'
        (self.tmp / lock.parent).mkdir(parents=True)
        shutil.copy(REPO / lock, self.tmp / lock)
        point = load(QEMU)['network']['enforcement_point']
        (self.tmp / 'evidence').mkdir()
        shutil.copy(REPO / point['evidence'], self.tmp / point['evidence'])
        self.qemu = load(QEMU, self.tmp)
        self.server = self.qemu['provisioning']['agent_server']
        self.fixture_path = self.tmp / self.server['fixture']['path']

    def errors(self, profile=None):
        return check_profile.check(profile or self.qemu, self.tmp).errors

    def assertFails(self, fragment, profile=None):
        errors = self.errors(profile)
        self.assertTrue(any(fragment in e for e in errors),
                        f'expected an error containing {fragment!r}, got {errors}')

    def test_committed_block_passes(self):
        self.assertEqual(self.errors(), [])

    def test_conversation_container_declaration(self):
        """F-04.2: provisioning.agent_server.conversations and the facts-request directory."""
        conv = self.server['conversations']
        mounts = conv['mounts']
        for source in ('/run/docker.sock', '/srv/scratch/docker/volumes/x',
                       '/etc/aieh/agent-server', '/srv/scratch/agent/x',
                       '/srv/scratch/openhands/../docker'):
            conv['mounts'] = mounts[:2] + [dict(mounts[2], source=source)]
            self.assertFails('provisioning.agent_server.conversations.mounts[2]')
        conv['mounts'] = mounts[:2] + [dict(mounts[2], destination='/host')]
        self.assertFails('the destinations must be')
        conv['mounts'] = mounts
        conv['forbidden_sources'] = ['/etc']
        self.assertFails('forbidden_sources: must include')
        conv['forbidden_sources'] = load(QEMU, self.tmp)['provisioning']['agent_server'][
            'conversations']['forbidden_sources']
        conv['published'] = {'container_port': '8000/tcp', 'host_ip': '0.0.0.0'}
        self.assertFails('published: the container port on 127.0.0.1 only')
        conv['published'] = {'container_port': '8000/tcp', 'host_ip': '127.0.0.1'}
        conv['cap_drop'] = []
        self.assertFails('cap_drop [ALL]')
        conv['cap_drop'] = ['ALL']
        deviations = conv['deviations']
        conv['deviations'] = deviations[:2]
        self.assertFails('deviations: record')
        conv['deviations'] = deviations
        conv['facts']['rate'] = {'interval_s': 60, 'burst': 1000}
        self.assertFails('facts.rate')
        conv['facts']['rate'] = {'interval_s': 60, 'burst': 20}
        conv['facts']['report'] = '/var/lib/aieh/conversation-facts.json'
        self.assertFails('facts.report')
        conv['facts']['report'] = '/run/aieh/conversation-facts.json'
        self.assertEqual(self.errors(), [])
        request_dir = next(d for d in self.qemu['guest_storage']['directories']
                           if d['role'] == 'facts-request')
        request_dir['mode'] = '777'
        self.assertFails('facts.request: a file in the root:agent 730')

    def test_runtime_image_and_selectability(self):
        cfg = self.server['config']['content']
        cfg['conversation_runtime'] = 'local'
        self.assertFails('conversation_runtime docker')
        cfg['conversation_runtime'], cfg['conversation_runtime_selectable'] = 'docker', True
        self.assertFails('conversation_runtime_selectable')
        cfg['conversation_runtime_selectable'] = False
        cfg['conversation_image'] = 'ghcr.io/openhands/agent-server:latest-python'
        self.assertFails('conversation_image')

    def test_caps_are_explicit_and_inside_the_ceilings(self):
        cfg = self.server['config']['content']
        del cfg['conversation_container_pids_limit']
        self.assertFails('explicit conversation_container_memory')
        cfg['conversation_container_pids_limit'] = 512
        cfg['conversation_container_memory'] = '8g'
        self.assertFails('inside the guest ceilings')
        cfg['conversation_container_memory'], cfg['conversation_container_cpus'] = '4g', 4.0
        self.assertFails('inside the guest ceilings')

    def test_secrets_llm_webhooks_and_telemetry_stay_out_of_the_config(self):
        for key, value, fragment in (('secret_key', 'x', 'secret_key is not allowed'),
                                     ('session_api_keys', ['x'], 'session_api_keys is not allowed'),
                                     ('webhooks', [{'base_url': 'https://example.invalid'}],
                                      'no webhook'),
                                     ('telemetry', {'exporter': 'posthog'}, 'telemetry exporter'),
                                     ('enable_vscode', True, 'no VSCode'),
                                     ('llm', {'api_key': 'x'}, 'no LLM')):
            profile = copy.deepcopy(self.qemu)
            profile['provisioning']['agent_server']['config']['content'][key] = value
            self.assertFails(fragment, profile)

    def test_paths_must_be_declared_scratch_directories(self):
        self.server['config']['content']['conversation_worktree_root'] = '/tmp/conversation-worktrees'
        self.assertFails('config.conversation_worktree_root')
        profile = copy.deepcopy(load(QEMU, self.tmp))
        profile['provisioning']['agent_server']['environment']['OH_PERSISTENCE_DIR'] = '/var/lib/x'
        self.assertFails('environment.OH_PERSISTENCE_DIR', profile)
        profile = copy.deepcopy(load(QEMU, self.tmp))
        entry = next(d for d in profile['guest_storage']['directories'] if d['role'] == 'agent-server')
        entry['owner'] = 'agent'
        self.assertFails('owned by the service user', profile)
        entry['owner'], entry['mount'] = 'openhands', '/'
        self.assertFails('on the scratch disk', profile)

    def test_bind_user_and_secret_custody(self):
        for mutate, fragment in (
                (lambda s: s['service'].__setitem__('argv', ['--port', '8000']), 'service.argv'),
                (lambda s: s['listener'].__setitem__('address', '0.0.0.0'), 'listener'),
                (lambda s: s['user'].__setitem__('name', 'agent'), '.user'),
                (lambda s: s['user'].__setitem__('shell', '/bin/bash'), '.user'),
                (lambda s: s['user'].__setitem__('groups', ['docker', 'sudo']), '.user'),
                (lambda s: s['secrets'].__setitem__('mode', '640'), '.secrets'),
                (lambda s: s['session_key'].__setitem__('host_path', 'C:/keys/session.key'),
                 '.session_key'),
                (lambda s: s['environment'].__setitem__('OH_SECRET_KEY', 'x'), 'environment'),
                (lambda s: s['service']['hardening']['options'].remove('IPAddressDeny=any'),
                 'hardening'),
                (lambda s: s['binary'].__setitem__('upload_name', 'agent-server-1.59.0-linux-x86_64'),
                 'binary.upload_name')):
            profile = copy.deepcopy(load(QEMU, self.tmp))
            mutate(profile['provisioning']['agent_server'])
            self.assertFails(fragment, profile)

    def test_fixture_is_pinned_and_structural(self):
        body = json.loads(self.fixture_path.read_text(encoding='utf-8'))
        self.assertEqual(check_profile.fixture_problems(body), [])
        for mutate, fragment in (
                (lambda b: b.__setitem__('conversation_runtime', 'local'), 'conversation_runtime'),
                (lambda b: b.__setitem__('conversation_id', 'not-a-uuid'), 'conversation_id'),
                (lambda b: b.__setitem__('initial_message', {'role': 'user'}), 'initial message'),
                (lambda b: b['workspace'].__setitem__('working_dir', '/home/agent'), 'workspace'),
                (lambda b: b['container'].__setitem__('memory', '64g'), 'container'),
                (lambda b: b['agent_settings'].__setitem__('llm', {'model': 'x'}), 'no llm'),
                (lambda b: b['agent_settings'].__setitem__('api_key', 'x'), 'credential'),
                (lambda b: b.__setitem__('agent_profile_id', 'x'), 'one agent source')):
            mutated = copy.deepcopy(body)
            mutate(mutated)
            self.assertTrue(any(fragment in p for p in check_profile.fixture_problems(mutated)),
                            (fragment, check_profile.fixture_problems(mutated)))
        self.fixture_path.write_text(json.dumps(dict(body, autotitle=True)), encoding='utf-8')
        self.assertFails('fixture: profiles/')

    def test_openapi_pin_is_the_lock(self):
        self.server['fixture']['openapi']['sha256'] = '0' * 64
        self.assertFails('fixture.openapi.sha256')


class AdmissionBlock(unittest.TestCase):
    """S-01.3.1: provisioning.agent_server.admission and its pinned route inventory; each
    mutation must FAIL naming the rule."""
    setUp = AgentServerBlock.setUp
    errors = AgentServerBlock.errors
    assertFails = AgentServerBlock.assertFails

    def routes(self):
        return json.loads((self.tmp / self.server['admission']['routes']['path']).read_text(
            encoding='utf-8'))

    def write_routes(self, data):
        path = self.tmp / self.server['admission']['routes']['path']
        text = json.dumps(data, indent=1) + '\n'
        path.write_text(text, encoding='utf-8', newline='\n')
        self.server['admission']['routes']['sha256'] = check_profile.sha256_file(path)

    def test_committed_admission_passes(self):
        self.assertEqual(self.errors(), [])
        self.assertEqual(check_profile.route_problems(self.routes()), [])

    def test_routes_are_pinned(self):
        self.server['admission']['routes']['sha256'] = '0' * 64
        self.assertFails('admission.routes: profiles/')

    def test_route_rules(self):
        data = self.routes()
        gated = next(r for r in data['routes'] if r['admission'] == 'session-key')
        public = next(r for r in data['routes'] if r['admission'] == 'public')
        ws = next(r for r in data['routes'] if r['method'] == 'WEBSOCKET' and
                  set(r['expect']) == set(check_profile.ROUTE_WS_VARIANTS))
        cases = [
            (gated, dict(gated, expect={'no_key': 200, 'wrong_key': 401}), 'must not answer 2xx'),
            (gated, dict(gated, admission='open'), 'admission must be one of'),
            (gated, dict(gated, **{'class': 'public-read'}), 'go together'),
            (gated, dict(gated, dispatcher='sometimes'), 'dispatcher must be'),
            (gated, dict(gated, source='guess'), 'source must be'),
            (gated, dict(gated, expect={'no_key': 401}), 'expect no_key and wrong_key'),
            (public, dict(public, method='POST'), 'a public route must be a GET'),
            (ws, dict(ws, expect=dict(ws['expect'], no_auth_message=101)), 'never 101'),
            (ws, dict(ws, admission='public', **{'class': 'public-read'}), 'needs a credential'),
        ]
        for old, new, fragment in cases:
            changed = dict(data, routes=[new if r is old else r for r in data['routes']])
            problems = check_profile.route_problems(changed)
            self.assertTrue(any(fragment in p for p in problems), (fragment, problems))
        twice = dict(data, routes=data['routes'] + [gated])
        self.assertTrue(any('listed twice' in p for p in check_profile.route_problems(twice)))
        self.assertEqual(check_profile.route_problems({'schema': 'x'}),
                         [f'schema must be {check_profile.ROUTES_SCHEMA}'])
        self.write_routes(dict(data, routes=[dict(gated, expect={'no_key': 204, 'wrong_key': 401})]
                               + data['routes'][1:]))
        self.assertFails('admission.routes: ')

    def test_route_version_is_the_server_version(self):
        self.write_routes(dict(self.routes(), version='1.0.0'))
        self.assertFails('version must be the Agent Server version')

    def test_guard_and_icc(self):
        guard = self.server['admission']['network']['guard']
        rules = list(guard['rules'])
        guard['rules'] = rules[1:]
        self.assertFails('network.guard.rules')
        guard['rules'] = rules[:2] + ['-p tcp -j ACCEPT', rules[3]]
        self.assertFails('network.guard.rules')
        guard['rules'] = rules
        for key, value in (('families', ['iptables']), ('interfaces', ['br-+']),
                           ('log_prefix', 'x'), ('docker_dropin', '/etc/docker/x.conf'),
                           ('chain', 'x y')):
            saved = guard[key]
            guard[key] = value
            self.assertFails('admission.network.guard: an INPUT chain')
            guard[key] = saved
        daemon = self.qemu['provisioning']['moby']['daemon_json']
        daemon['icc'] = True
        self.assertFails('must set icc false')
        del daemon['icc']
        self.assertFails('must set icc false')
        daemon['icc'] = False
        self.assertEqual(self.errors(), [])

    def test_egress_guard(self):
        """S-01.4: the DOCKER-USER egress guard; each loosening FAILs naming the rule."""
        net = self.server['admission']['network']
        egress = net['egress_guard']
        self.assertEqual(egress['allowlist'], [])
        rules = list(egress['rules'])
        for changed in (rules[1:], rules[:2] + ['-p tcp -j ACCEPT', rules[3]],
                        [r.replace('egress', 'container') for r in rules]):
            egress['rules'] = changed
            self.assertFails('network.egress_guard.rules')
        egress['rules'] = rules
        for key, value, fragment in (
                ('chain', net['guard']['chain'], 'egress_guard.chain'),
                ('chain', 'DOCKER-USER', 'egress_guard.chain'),
                ('hook', 'FORWARD', 'egress_guard.hook'),
                ('interfaces', ['br-+'], 'egress_guard.interfaces'),
                ('hook_rules', ['-i docker0 -j AIEH-EGRESS-GUARD', '-i br-+ -j AIEH-EGRESS-GUARD',
                                '-j RETURN'], 'egress_guard.hook_rules'),
                ('hook_rules', egress['hook_rules'][:2], 'egress_guard.hook_rules'),
                ('families', ['iptables'], 'egress_guard.families'),
                ('log_prefix', 'aieh-container-guard: ', 'egress_guard.log_prefix'),
                ('unit', 'aieh-egress.service', 'installed by the container guard'),
                ('script', '/usr/local/sbin/other', 'installed by the container guard'),
                ('allowlist', [{'class': 'inference', 'rule': '-d 10.0.2.100 -j RETURN'}],
                 'egress_guard.allowlist[0]'),
                ('allowlist', None, 'egress_guard.allowlist: must be a list'),
                ('rule', '', 'egress_guard.rule: required')):
            saved = copy.deepcopy(egress[key])
            egress[key] = value
            self.assertFails(fragment)
            egress[key] = saved
        self.assertEqual(self.errors(), [])
        # an allowlist entry is accepted only for a class the profile enables for forwarded
        # container traffic (provision, once neither deferred nor planned); never inference,
        # whose endpoint the container guard allows on INPUT (decision 0015 section 4.2)
        provision = next(e for e in self.qemu['network']['endpoints'] if e['class'] == 'provision')
        provision['status'] = 'enabled for the test'
        provision['host_port'] = None
        egress['allowlist'] = [{'class': 'provision', 'rule': '-d 10.0.2.100 -p tcp -j RETURN'}]
        self.assertNotIn('egress_guard.allowlist', ' '.join(self.errors()))
        egress['allowlist'] = [{'class': 'inference', 'rule': '-d 172.17.0.1 -p tcp -j RETURN'}]
        self.assertFails('egress_guard.allowlist[0]')
        provision['status'] = 'planned: for the test'
        egress['allowlist'] = [{'class': 'provision', 'rule': '-d 10.0.2.100 -p tcp -j RETURN'}]
        self.assertFails('egress_guard.allowlist[0]')
        egress['allowlist'] = []
        daemon = self.qemu['provisioning']['moby']['daemon_json']
        for key in ('iptables', 'ip-forward'):
            daemon[key] = False
            self.assertFails('must not turn off iptables or ip-forward')
            del daemon[key]
        del net['egress_guard']
        self.assertFails('egress_guard: must be declared')

    def test_session_key_and_dispatcher(self):
        adm = self.server['admission']
        adm['session_key']['header'] = 'Authorization'
        self.assertFails('admission.session_key')
        adm['session_key']['header'] = 'X-Session-API-Key'
        adm['session_key']['start_check'] = '/tmp/check'
        self.assertFails('admission.session_key')
        adm['session_key']['start_check'] = '/usr/local/sbin/aieh-agent-server-keycheck'
        adm['dispatcher']['owner_ui'] = ''
        self.assertFails('admission.dispatcher')


class QuiesceBlock(unittest.TestCase):
    """E-01.2.2: provisioning.agent_server.service.dependencies and .quiesce, against the seed
    template; each mutation must FAIL naming the rule."""
    setUp = AgentServerBlock.setUp
    errors = AgentServerBlock.errors
    assertFails = AgentServerBlock.assertFails

    def test_committed_declaration_passes(self):
        self.assertEqual(self.errors(), [])
        q = self.server['quiesce']
        self.assertEqual([a['id'] for a in q['actions']], check_profile.QUIESCE_ACTIONS)
        self.assertEqual(q['order'][-2:], [q['unit'], self.server['service']['unit']])

    def test_declaration_mutations(self):
        def mutated(change):
            profile = copy.deepcopy(self.qemu)
            change(profile['provisioning']['agent_server'], profile)
            return profile
        cases = [
            (lambda s, p: s['service']['dependencies'].update(wants=['docker.service']), 'no Wants='),
            (lambda s, p: s['service']['dependencies'].update(requires=['docker.service']),
             'dependencies.requires'),
            (lambda s, p: s['service']['dependencies'].update(after=['aieh-agent-server-quiesce.service']),
             'dependencies.after'),
            (lambda s, p: s['service']['dependencies'].update(binds_to=['docker.service']), 'BindsTo='),
            (lambda s, p: s['service'].pop('dependencies'), 'declared together'),
            (lambda s, p: s['quiesce']['unit_settings'].update(RemainAfterExit='yes'), 'unit_settings'),
            (lambda s, p: s['quiesce']['unit_settings'].update(Before=[]), 'unit_settings'),
            (lambda s, p: s['quiesce']['unit_settings'].update(Type='simple'), 'unit_settings'),
            (lambda s, p: s['quiesce'].update(order=s['quiesce']['order'][::-1]), 'quiesce.order'),
            (lambda s, p: s['quiesce'].update(actions=s['quiesce']['actions'][::-1]), 'quiesce.actions'),
            (lambda s, p: s['quiesce'].update(rewrite={'field': 'execution_status', 'from': 'running',
                                                       'to': 'idle'}), 'record_files'),
            (lambda s, p: s['quiesce'].update(invariant='none'), 'the invariant'),
            (lambda s, p: s['quiesce'].update(unit='other.service'), 'quiesce: unit'),
            (lambda s, p: s['quiesce']['quarantine'].update(mode='755'), 'quiesce.quarantine'),
            (lambda s, p: s['quiesce']['quarantine'].update(path='/srv/scratch/openhands/q'),
             'quiesce.quarantine'),
        ]
        for change, fragment in cases:
            self.assertFails(fragment, mutated(change))

        def quarantine_inside_the_server(s, p):
            entry = next(d for d in p['guest_storage']['directories']
                         if d['role'] == 'agent-server-quarantine')
            entry['path'] = s['quiesce']['quarantine']['path'] = '/srv/scratch/openhands/home/q'
        self.assertFails('outside every agent-server directory', mutated(quarantine_inside_the_server))

        def no_directory(s, p):
            p['guest_storage']['directories'] = [d for d in p['guest_storage']['directories']
                                                 if d['role'] != 'agent-server-quarantine']
        self.assertFails('quiesce.quarantine', mutated(no_directory))

    def test_the_seed_template_must_say_the_same(self):
        path = self.tmp / 'profiles' / 'seed' / 'user-data.tmpl'
        original = path.read_text(encoding='utf-8')
        server_req = '      Requires=docker.service aieh-agent-server-quiesce.service\n'
        start = '      Type=oneshot\n      ExecStart=/usr/bin/python3 -I /usr/local/sbin/aieh-agent-server-quiesce\n'
        for old, new, fragment in (
                (server_req, server_req.replace('Requires=', 'Wants='),
                 'service.dependencies: the seed template'),
                ('      Before=aieh-agent-server.service\n', '\n', 'unit_settings: the seed template'),
                (start, start.replace('oneshot\n', 'oneshot\n      RemainAfterExit=yes\n'),
                 'unit_settings: the seed template'),
                ('      ReadWritePaths=/srv/scratch\n      ProtectHome=read-only\n',
                 '      ProtectHome=read-only\n', 'hardening: ReadWritePaths'),
                ("      QUARANTINE = '/srv/scratch/aieh-quarantine'\n      SERVICE_USER",
                 "      QUARANTINE = '/srv/scratch/elsewhere'\n      SERVICE_USER",
                 'quarantine or size bound')):
            self.assertEqual(original.count(old), 1, old)
            path.write_text(original.replace(old, new), encoding='utf-8', newline='\n')
            self.assertFails(fragment)
        path.write_text(original, encoding='utf-8', newline='\n')
        self.assertEqual(self.errors(), [])


class JobsBlock(unittest.TestCase):
    """S-01.3.2: provisioning.agent_server.jobs, the job environment's declared hardening and
    the CI constraints carried as planned; each mutation must FAIL naming the rule."""
    setUp = AgentServerBlock.setUp
    errors = AgentServerBlock.errors
    assertFails = AgentServerBlock.assertFails

    def test_committed_jobs_block_passes(self):
        self.assertEqual(self.errors(), [])

    def test_host_config_values(self):
        host = self.server['jobs']['host_config']
        for key, value in (('Privileged', True), ('CapDrop', []), ('CapAdd', ['NET_ADMIN']),
                           ('SecurityOpt', ['no-new-privileges', 'seccomp=unconfined']),
                           ('SecurityOpt', []), ('AppArmorProfile', 'unconfined'),
                           ('PidMode', 'host'), ('IpcMode', 'host'), ('UsernsMode', 'host'),
                           ('Devices', ['/dev/kvm']), ('GroupAdd', ['docker']),
                           ('Mounts', [{'Source': '/run/docker.sock'}])):
            saved = host[key]
            host[key] = value
            self.assertFails(f'jobs.host_config.{key}')
            host[key] = saved
        host['SecurityOpt'] = ['no-new-privileges', 'apparmor=unconfined']
        self.assertFails('no confinement option may be overridden')
        host['SecurityOpt'] = ['no-new-privileges']
        self.assertEqual(self.errors(), [])

    def test_process_names_sockets_and_ports(self):
        jobs = self.server['jobs']
        cases = [
            ('process', dict(jobs['process'], capabilities='00000000a80425fb'), 'jobs.process'),
            ('process', dict(jobs['process'], no_new_privs='0'), 'jobs.process'),
            ('environment', dict(jobs['environment'], credential_name_pattern='TOKEN'),
             'jobs.environment'),
            ('environment', dict(jobs['environment'], secret_names=['OH_SECRET_KEY', 'GITEA_TOKEN']),
             'jobs.environment'),
            ('engine_sockets', ['/run/docker.sock'], 'jobs.engine_sockets'),
            ('engine_sockets', jobs['engine_sockets'] + ['/home/x/docker.sock'], 'jobs.engine_sockets'),
            ('engine_tcp_ports', [2375], 'jobs.engine_tcp_ports'),
            ('host_alias', dict(jobs['host_alias'], host_ports=[13300]), 'jobs.host_alias'),
            ('credential_files', '^\\.netrc$', 'jobs.credential_files'),
            ('credential_files', '([', 'jobs.credential_files'),
            ('deviations', {'host-gateway': 'x'}, 'jobs.deviations'),
            ('sources', dict(jobs['sources'], moby=''), 'jobs.sources'),
            ('token_rule', '', 'jobs.token_rule'),
        ]
        for key, value, fragment in cases:
            saved = jobs[key]
            jobs[key] = value
            self.assertFails(fragment)
            jobs[key] = saved
        self.assertEqual(self.errors(), [])

    def test_moby_defaults_server_environment_and_browser(self):
        moby = self.qemu['provisioning']['moby']
        saved = list(moby['required_security_options'])
        moby['required_security_options'] = ['name=no-new-privileges']
        self.assertFails('Moby must default no-new-privileges and require')
        moby['required_security_options'] = saved
        self.server['environment']['DOCKER_HOST'] = 'tcp://127.0.0.1:2375'
        self.assertFails('may not set an engine variable')
        del self.server['environment']['DOCKER_HOST']
        self.server['config']['content']['enable_browser'] = True
        self.assertFails('enable_browser must be false')
        del self.server['config']['content']['enable_browser']
        self.assertFails('enable_browser must be false')
        self.server['config']['content']['enable_browser'] = False
        self.assertEqual(self.errors(), [])

    def test_ci_constraints_stay_planned_and_carried(self):
        ci = self.server['jobs']['ci']
        ci['status'] = 'observed'
        self.assertFails('jobs.ci')
        ci['status'] = 'planned'
        constraints = ci['constraints']
        ci['constraints'] = constraints[:3]
        self.assertFails('jobs.ci')
        ci['constraints'] = constraints
        ci['carried_to'] = ['Q-02.2.1']
        self.assertFails('jobs.ci')

    def test_jobs_block_is_optional_but_typed(self):
        del self.server['jobs']
        self.assertEqual(self.errors(), [])
        self.server['jobs'] = []
        self.assertFails('provisioning.agent_server.jobs: must be an object')


class OpenApiSubset(unittest.TestCase):
    """The standard-library JSON Schema subset that validates the fixture (synthetic
    documents; the locked openapi.json itself is downloaded, never committed)."""
    category = 'contract'

    DOC = {'components': {'schemas': {
        'Req': {'type': 'object', 'required': ['id', 'ws'], 'properties': {
            'id': {'anyOf': [{'type': 'string', 'format': 'uuid'}, {'type': 'null'}]},
            'rt': {'anyOf': [{'enum': ['local', 'docker'], 'type': 'string'}, {'type': 'null'}]},
            'ws': {'$ref': '#/components/schemas/Ws', 'description': 'x'},
            'n': {'type': 'integer', 'minimum': 1},
            'opts': {'additionalProperties': False, 'type': 'object',
                     'properties': {'mem': {'type': 'string', 'pattern': '^\\d+g$'}}},
            'tags': {'type': 'object', 'additionalProperties': {'type': 'string'}}}},
        'Ws': {'type': 'object', 'required': ['dir'], 'properties': {
            'kind': {'const': 'Local', 'type': 'string'}, 'dir': {'type': 'string'}}},
        'Odd': {'type': 'object', 'not': {'required': ['x']}}}}}
    GOOD = {'id': '929f0d8a-f3d8-4da3-8ac3-9d0017709d71', 'rt': 'docker',
            'ws': {'kind': 'Local', 'dir': '/w'}, 'n': 1, 'opts': {'mem': '4g'}, 'tags': {'a': 'b'}}

    def errors(self, value, name='Req'):
        return check_profile.schema_errors(value, {'$ref': f'#/components/schemas/{name}'}, self.DOC)

    def test_valid(self):
        self.assertEqual(self.errors(self.GOOD), [])

    def test_each_keyword_refuses(self):
        for change in ({'id': 'nope'}, {'rt': 'k8s'}, {'ws': {'kind': 'Other', 'dir': '/w'}},
                       {'ws': {'kind': 'Local'}}, {'n': 0}, {'n': True}, {'opts': {'mem': 'x'}},
                       {'opts': {'mem': '4g', 'cpus': 1}}, {'tags': {'a': 1}}):
            self.assertTrue(self.errors(dict(self.GOOD, **change)), change)
        missing = dict(self.GOOD)
        del missing['ws']
        self.assertIn("$: missing required 'ws'", self.errors(missing))

    def test_unsupported_keywords_and_references_fail_closed(self):
        self.assertIn('unsupported schema keywords', self.errors({}, 'Odd')[0])
        self.assertIn('unresolvable reference', self.errors({}, 'Missing')[0])

    def test_command_line_refuses_an_unpinned_openapi_file(self):
        tmp = Path(tempfile.mkdtemp(prefix='aieh-openapi-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        fake = tmp / 'openapi.json'
        fake.write_text(json.dumps(self.DOC), encoding='utf-8')
        result = run_checker('--openapi', str(fake), str(REPO / 'profiles' / QEMU))
        self.assertEqual(result.returncode, 1)
        self.assertIn('is not the locked openapi.json', result.stdout)


class CommandLine(unittest.TestCase):
    category = 'contract'

    def test_unpinned_input_fails_the_command(self):
        tmp = Path(tempfile.mkdtemp(prefix='aieh-profile-cli-'))
        try:
            shutil.copytree(REPO / 'profiles', tmp / 'profiles')
            path = tmp / 'profiles' / QEMU / 'profile.json'
            profile = json.loads(path.read_text(encoding='utf-8'))
            profile['boot_inputs']['image']['sha256'] = None
            path.write_text(json.dumps(profile), encoding='utf-8')
            result = run_checker('--root', str(tmp))
            self.assertEqual(result.returncode, 1)
            self.assertIn(f'FAIL {QEMU}: boot_inputs.image: not pinned by sha256', result.stdout)
            self.assertIn(f'FAIL {QEMU}\n', result.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
