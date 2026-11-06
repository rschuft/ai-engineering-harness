"""Tests for tools/check_profile.py (stdlib unittest).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The checked-in profiles are checked as they are. Every negative case works on a
temporary copy of profiles/ (the checker reads pinned files relative to a root), so
the checkout is only read.
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


class Negative(unittest.TestCase):
    """Each mutation must produce a FAIL that names the broken rule."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-profile-test-'))
        shutil.copytree(REPO / 'profiles', self.tmp / 'profiles')
        self.qemu = load(QEMU, self.tmp)
        self.incus = load(INCUS, self.tmp)
        point = self.qemu['network']['enforcement_point']
        if isinstance(point, dict) and point.get('evidence'):       # cited evidence, read only
            (self.tmp / 'evidence').mkdir(exist_ok=True)
            shutil.copy(REPO / point['evidence'], self.tmp / point['evidence'])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

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
        path = self.tmp / 'profiles' / 'seed' / 'user-data.tmpl'
        path.write_bytes(path.read_bytes() + b'# changed\n')
        self.assertFails(self.qemu, 'seed.templates.user-data')
        self.assertFails(self.incus, 'seed.templates.user-data')

    def test_tampered_provider_lock(self):
        path = self.tmp / 'profiles' / QEMU / 'qemu-msys2-ucrt64.lock.json'
        path.write_bytes(path.read_bytes().replace(b'11.1.3-1', b'11.1.2-1', 1))
        self.assertFails(self.qemu, 'provider.artifact_lock')

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
        self.assertFails(self.qemu, 'operational must be false until C6')

    def test_mutations_do_not_leak_between_tests(self):
        self.assertEqual(self.errors(copy.deepcopy(self.qemu)), [])
        self.assertEqual(self.errors(copy.deepcopy(self.incus)), [])

    # enforcement point (profiles P7; F-03.3.2)
    def qualified(self):
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
        endpoint = next(e for e in self.qemu['network']['endpoints'] if e['class'] == 'inference')
        endpoint['host_port'] = 4000
        self.assertFails(self.qemu, 'deferred inference endpoint declares a host port')

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

    def test_wildcard_only_as_last_component(self):
        self.qemu['guest_storage']['mounts'].append(
            {'target': '/run/*/x', 'fstype': 'tmpfs', 'source': 'tmpfs'})
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


class CommandLine(unittest.TestCase):
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
