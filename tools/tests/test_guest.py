"""Tests for tools/guest.py (stdlib unittest; no QEMU, no guest, no network).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The profile is the committed strong-windows-qemu-whpx declaration, read only. State
directories are temporary; because the tool refuses a state directory inside the
Owner's profile (where the temporary directory usually lives), the cases that build a
Context point USERPROFILE and HOME at a directory that does not contain it.
"""
from pathlib import Path
import base64
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO / 'profiles' / 'strong-windows-qemu-whpx'

_spec = importlib.util.spec_from_file_location('guest', REPO / 'tools' / 'guest.py')
guest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guest)

PROFILE = json.loads((PROFILE_DIR / 'profile.json').read_text(encoding='utf-8'))
PORTS = {'ssh': 40001, 'qmp': 40002}


def ed25519_b64(raw32):
    blob = struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32) + raw32
    return base64.b64encode(blob).decode('ascii')


def fingerprint(b64):
    digest = hashlib.sha256(base64.b64decode(b64)).digest()
    return 'SHA256:' + base64.b64encode(digest).decode('ascii').rstrip('=')


def tree_digest(root):
    """Every path under root with its file digest, for before/after comparisons."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            out[os.path.relpath(os.path.join(dirpath, d), root)] = 'dir'
        for f in filenames:
            p = os.path.join(dirpath, f)
            out[os.path.relpath(p, root)] = hashlib.sha256(Path(p).read_bytes()).hexdigest()
    return out


class TempState(unittest.TestCase):
    """A temporary state directory with USERPROFILE/HOME pointed elsewhere."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-guest-test-'))
        self.state = self.tmp / 'state'
        self.state.mkdir()
        elsewhere = self.tmp / 'home'
        elsewhere.mkdir()
        patcher = mock.patch.dict(os.environ, {'USERPROFILE': str(elsewhere),
                                               'HOME': str(elsewhere)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def ctx(self):
        return guest.Context(str(PROFILE_DIR), str(self.state))


# ---------------------------------------------------------------- argv rendering


class RenderArgv(unittest.TestCase):
    def values(self, profile=PROFILE):
        return guest.resolve_values(profile, 'D:/state', 'abc', PORTS)

    def test_full_argv(self):
        argv = guest.render_argv(PROFILE, self.values())
        self.assertEqual(argv[0], 'D:/state/providers/qemu/msys2-ucrt64-11.1.3-1/ucrt64/bin/'
                                  'qemu-system-x86_64.exe')
        self.assertEqual(len(argv), len(PROFILE['launch']['argv']) + 1)
        self.assertFalse([a for a in argv if '{' in a or '}' in a])
        self.assertIn('user,id=net0,restrict=on,ipv6=off,hostfwd=tcp:127.0.0.1:40001-:22', argv)
        self.assertIn('socket,id=qmp,host=127.0.0.1,port=40002,server=on,wait=off', argv)
        self.assertIn('driver=file,node-name=seed-file,filename=D:/state/instances/abc/seed.iso,'
                      'read-only=on', argv)
        self.assertIn('driver=file,node-name=base-file,filename=D:/state/images/'
                      'debian-13-genericcloud-amd64-20261103-2651.qcow2,read-only=on', argv)
        self.assertIn('file,id=serial0,path=D:/state/instances/abc/serial.log', argv)
        self.assertIn('guest=abc', argv)
        self.assertEqual([argv[i + 1] for i, a in enumerate(argv) if a == '-accel'], ['whpx'])

    def test_backslash_state_dir_is_written_with_slashes(self):
        values = guest.resolve_values(PROFILE, 'D:\\state', 'abc', PORTS)
        self.assertEqual(values['instance_dir'], 'D:/state/instances/abc')

    def test_unknown_placeholder_refused(self):
        profile = copy.deepcopy(PROFILE)
        profile['launch']['argv'].append('{bogus}')
        with self.assertRaises(guest.Refused):
            guest.render_argv(profile, self.values(profile))

    def test_ports_required(self):
        values = guest.resolve_values(PROFILE, 'D:/state', 'abc')
        with self.assertRaises(guest.Refused):
            guest.render_argv(PROFILE, values)

    def test_disk_commands(self):
        disks = guest.render_disk_commands(PROFILE, self.values())
        self.assertEqual(sorted(disks), ['root.qcow2', 'scratch.qcow2'])
        qemu_img = 'D:/state/providers/qemu/msys2-ucrt64-11.1.3-1/ucrt64/bin/qemu-img.exe'
        self.assertEqual(disks['root.qcow2'], [
            qemu_img, 'create', '-f', 'qcow2', '-b',
            'D:/state/images/debian-13-genericcloud-amd64-20261103-2651.qcow2', '-F', 'qcow2',
            'D:/state/instances/abc/root.qcow2', '40G'])
        self.assertEqual(disks['scratch.qcow2'], [
            qemu_img, 'create', '-f', 'qcow2', 'D:/state/instances/abc/scratch.qcow2', '120G'])

    def test_scrubbed_env(self):
        env = guest.scrubbed_env(self.values(), temp_dir='D:/state/instances/abc',
                                 environ={'SYSTEMROOT': 'C:\\Windows', 'SECRET_TOKEN': 'x',
                                          'USERPROFILE': 'E:\\profiles\\someone', 'PATH': 'x'})
        self.assertEqual(sorted(env), ['PATH', 'SYSTEMROOT', 'TEMP', 'TMP'])
        self.assertTrue(env['PATH'].startswith(str(Path('D:/state/providers/qemu/'
                                                        'msys2-ucrt64-11.1.3-1/ucrt64/bin'))))


# ---------------------------------------------------------------- launch record


class LaunchRecord(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-guest-rec-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inputs = {}
        for name in ('image', 'firmware', 'seed', 'provider_binary', 'qemu_img'):
            path = self.tmp / f'{name}.bin'
            path.write_bytes(name.encode() * 100)
            self.inputs[name] = {'path': guest.posix(path),
                                 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        values = guest.resolve_values(PROFILE, guest.posix(self.tmp), 'abc', PORTS)
        self.record = guest.build_launch_record(
            PROFILE, PROFILE_DIR / 'profile.json', values, 'abc',
            'abc-00000000-0000-4000-8000-000000000000', PORTS,
            {'kind': 'git-revision', 'head': '0' * 40, 'profiles_clean': True},
            self.inputs, guest.render_argv(PROFILE, values), {'PATH': 'x'},
            guest.render_disk_commands(PROFILE, values))

    def test_record_fields(self):
        r = self.record
        self.assertEqual(r['schema'], guest.LAUNCH_SCHEMA)
        self.assertEqual(r['labels'], {'tier': 'strong', 'provider': 'qemu-whpx', 'nesting': 'none'})
        self.assertEqual(r['profile']['path'], 'profiles/strong-windows-qemu-whpx/profile.json')
        self.assertEqual(r['profile']['sha256'],
                         hashlib.sha256((PROFILE_DIR / 'profile.json').read_bytes()).hexdigest())
        self.assertEqual(r['ports'], {'ssh': 40001, 'qmp': 40002, 'bind': '127.0.0.1'})
        self.assertEqual(r['binary'], r['argv'][0])
        for name, entry in r['inputs'].items():
            self.assertRegex(entry['sha256'], r'^[0-9a-f]{64}$', name)
        json.dumps(r)   # serialisable

    def test_verify_inputs_pass(self):
        result = guest.verify_inputs(self.record)
        self.assertEqual(sorted(result), sorted(self.inputs))
        self.assertTrue(all(v['match'] for v in result.values()))

    def test_tampered_input_refused(self):
        Path(self.inputs['seed']['path']).write_bytes(b'tampered')
        with self.assertRaises(guest.Refused) as cm:
            guest.verify_inputs(self.record)
        self.assertEqual(cm.exception.code, 'DIGEST_MISMATCH')
        self.assertIn('seed', str(cm.exception))

    def test_missing_input_refused(self):
        os.remove(self.inputs['firmware']['path'])
        with self.assertRaises(guest.Refused) as cm:
            guest.verify_inputs(self.record)
        self.assertEqual(cm.exception.code, 'DIGEST_MISMATCH')


# ---------------------------------------------------------------- refusals


class Refusals(TempState):
    def test_instance_names(self):
        for bad in ('A', 'x', '../x', 'a/b', 'a\\b', 'a' * 42, '-ab', 'ab_c', ''):
            with self.assertRaises(guest.Refused, msg=bad):
                guest.check_name(PROFILE, bad)
        self.assertEqual(guest.check_name(PROFILE, 'f0322b-a'), 'f0322b-a')

    def test_state_dir_rules(self):
        home = self.tmp / 'home'
        (home / 'sub').mkdir()
        comma = self.tmp / 'a,b'
        comma.mkdir()
        cases = {
            'relative': 'relative/dir',
            'missing': str(self.tmp / 'missing'),
            'comma': str(comma),
            'checkout': str(REPO / 'tools'),
            'profile': str(home / 'sub'),
        }
        for label, path in cases.items():
            with self.assertRaises(guest.Refused, msg=label) as cm:
                guest.check_state_dir(path)
            self.assertEqual(cm.exception.code, 'TIER_UNAVAILABLE', label)
            self.assertIn('A3', str(cm.exception), label)
        self.assertEqual(guest.check_state_dir(str(self.state)), self.state)

    def test_create_refuses_existing_instance_directory(self):
        idir = self.state / 'instances' / 'taken'
        idir.mkdir(parents=True)
        (idir / 'keep.txt').write_text('keep')
        before = tree_digest(self.state)
        with self.assertRaises(guest.Refused) as cm:
            guest.create(self.ctx(), 'taken')
        self.assertIn('exists', str(cm.exception))
        self.assertEqual(tree_digest(self.state), before)

    def test_start_refuses_tampered_input(self):
        idir = self.state / 'instances' / 'abc'
        idir.mkdir(parents=True)
        seed = idir / 'seed.iso'
        seed.write_bytes(b'seed')
        record = {'schema': guest.LAUNCH_SCHEMA, 'binary': 'x', 'ports': PORTS,
                  'instance': {'name': 'abc'},
                  'inputs': {'seed': {'path': guest.posix(seed), 'sha256': '0' * 64}}}
        (idir / 'launch.json').write_text(json.dumps(record))
        with self.assertRaises(guest.Refused) as cm:
            guest.start(self.ctx(), 'abc')
        self.assertEqual(cm.exception.code, 'DIGEST_MISMATCH')
        self.assertFalse((idir / 'process.json').exists())

    def test_dirty_profiles_refused(self):
        repo = self.tmp / 'repo'
        (repo / 'profiles').mkdir(parents=True)
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid',
                   GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid')
        with mock.patch.dict(os.environ, env):
            def git(*args):
                subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
            git('init', '-q')
            (repo / 'profiles' / 'p.json').write_text('{}')
            git('add', 'profiles/p.json')
            git('commit', '-q', '-m', 'init')
            clean = guest.profile_revision(repo)
            self.assertRegex(clean['head'], r'^[0-9a-f]{40}$')
            self.assertTrue(clean['profiles_clean'])
            (repo / 'other.txt').write_text('outside profiles/ does not count')
            guest.profile_revision(repo)
            (repo / 'profiles' / 'p.json').write_text('{"changed": true}')
            with self.assertRaises(guest.Refused):
                guest.profile_revision(repo)
            git('checkout', '--', 'profiles/p.json')
            (repo / 'profiles' / 'new.json').write_text('{}')
            with self.assertRaises(guest.Refused):
                guest.profile_revision(repo)


# ---------------------------------------------------------------- destroy


class Destroy(TempState):
    def populate(self):
        for name in ('aa', 'bb'):
            idir = self.state / 'instances' / name
            (idir / 'ssh').mkdir(parents=True)
            (idir / 'root.qcow2').write_bytes(name.encode() * 1000)
            (idir / 'ssh' / 'id_ed25519').write_text('not a real key')
            (idir / 'launch.json').write_text('{}')
        (self.state / 'images').mkdir()
        (self.state / 'images' / 'base.qcow2').write_bytes(b'base' * 1000)
        (self.state / 'providers').mkdir()
        (self.state / 'providers' / 'qemu.exe').write_bytes(b'bin')

    def test_destroy_removes_only_its_directory(self):
        self.populate()
        before = tree_digest(self.state)
        result = guest.destroy(self.ctx(), 'aa')
        self.assertEqual(result['result'], 'destroyed')
        self.assertEqual(result['stop'], 'not-running')
        self.assertFalse((self.state / 'instances' / 'aa').exists())
        after = tree_digest(self.state)
        expected = {k: v for k, v in before.items()
                    if not k.startswith(os.path.join('instances', 'aa'))}
        self.assertEqual(after, expected)

    def test_destroy_absent(self):
        self.populate()
        before = tree_digest(self.state)
        result = guest.destroy(self.ctx(), 'gone')
        self.assertEqual(result['result'], 'absent')
        self.assertEqual(tree_digest(self.state), before)
        # also when the instances directory itself does not exist
        shutil.rmtree(self.state / 'instances')
        self.assertEqual(guest.destroy(self.ctx(), 'gone')['result'], 'absent')
        self.assertFalse((self.state / 'instances').exists())

    def test_destroy_refuses_bad_name(self):
        self.populate()
        before = tree_digest(self.state)
        for bad in ('..', '../images', 'A', 'aa/../bb'):
            with self.assertRaises(guest.Refused, msg=bad):
                guest.destroy(self.ctx(), bad)
        self.assertEqual(tree_digest(self.state), before)

    @unittest.skipUnless(os.name == 'nt', 'junctions are a Windows construct')
    def test_destroy_refuses_a_junction_inside(self):
        self.populate()
        outside = self.tmp / 'outside'
        outside.mkdir()
        (outside / 'canary.txt').write_text('must survive')
        link = self.state / 'instances' / 'aa' / 'link'
        made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                              capture_output=True, text=True, check=False)
        if made.returncode != 0:
            self.skipTest(f'mklink /J failed: {made.stderr}')
        with self.assertRaises(guest.Refused):
            guest.destroy(self.ctx(), 'aa')
        self.assertTrue((outside / 'canary.txt').is_file())
        self.assertTrue((self.state / 'instances' / 'aa' / 'root.qcow2').is_file())
        os.rmdir(link)


# ---------------------------------------------------------------- host keys


KEY1 = ed25519_b64(bytes(range(32)))
KEY2 = ed25519_b64(bytes(range(1, 33)))
PREFIX = '<14>Nov  6 16:00:01 cloud-init[812]: '


def serial_text(fp_lines, key_lines, finished=True, crlf=True):
    lines = ['[    0.000000] Linux version 6.12.115-cloud-amd64', 'login: ']
    if fp_lines is not None:
        lines += [PREFIX + '#' * 61, PREFIX + '-----BEGIN SSH HOST KEY FINGERPRINTS-----']
        lines += [PREFIX + line for line in fp_lines]
        lines += [PREFIX + '-----END SSH HOST KEY FINGERPRINTS-----', PREFIX + '#' * 61]
    if key_lines is not None:
        lines += ['-----BEGIN SSH HOST KEY KEYS-----'] + key_lines + \
            ['-----END SSH HOST KEY KEYS-----']
    if finished:
        lines.append('[   12.3] cloud-init[900]: Cloud-init v. 25.1.4 finished at Fri, 06 Nov '
                     '2026 16:00:02 +0000. Datasource DataSourceNoCloud [seed=/dev/vdc]. Up 12 seconds')
    return ('\r\n' if crlf else '\n').join(lines) + '\r\n'


class HostKeys(unittest.TestCase):
    def test_parse_and_known_hosts(self):
        text = serial_text([f'256 {fingerprint(KEY1)} root@abc (ED25519)'],
                           [f'ssh-ed25519 {KEY1} root@abc'])
        parsed = guest.parse_serial_host_keys(text)
        self.assertTrue(parsed['complete'])
        self.assertTrue(parsed['finished'])
        self.assertEqual(parsed['fingerprints'][0]['fingerprint'], fingerprint(KEY1))
        trusted, source = guest.trusted_host_keys(parsed)
        self.assertEqual(source, 'serial key block')
        self.assertEqual(guest.known_hosts_lines(trusted, 40001),
                         [f'[127.0.0.1]:40001 ssh-ed25519 {KEY1}'])
        self.assertEqual(guest.key_fingerprint(KEY1), fingerprint(KEY1))

    def test_incomplete_blocks_wait(self):
        text = PREFIX + '-----BEGIN SSH HOST KEY FINGERPRINTS-----\r\n' + \
            PREFIX + f'256 {fingerprint(KEY1)} root@abc (ED25519)\r\n'
        self.assertFalse(guest.parse_serial_host_keys(text)['complete'])
        fp_only = serial_text([f'256 {fingerprint(KEY1)} root@abc (ED25519)'], None,
                              finished=False)
        self.assertFalse(guest.parse_serial_host_keys(fp_only)['complete'])
        self.assertFalse(guest.parse_serial_host_keys('')['complete'])

    def test_fingerprints_only_then_keyscan(self):
        parsed = guest.parse_serial_host_keys(
            serial_text([f'256 {fingerprint(KEY1)} root@abc (ED25519)'], None))
        self.assertTrue(parsed['complete'])
        scanned = guest.parse_keyscan(f'# 127.0.0.1:40001 SSH-2.0-OpenSSH_10.0\n'
                                      f'[127.0.0.1]:40001 ssh-ed25519 {KEY1}\n')
        trusted, source = guest.trusted_host_keys(parsed, scanned)
        self.assertIn('ssh-keyscan', source)
        self.assertEqual(trusted[0]['key'], KEY1)
        wrong = guest.parse_keyscan(f'[127.0.0.1]:40001 ssh-ed25519 {KEY2}\n')
        with self.assertRaises(guest.Refused):
            guest.trusted_host_keys(parsed, wrong)

    def test_key_not_vouched_refused(self):
        parsed = guest.parse_serial_host_keys(
            serial_text([f'256 {fingerprint(KEY1)} root@abc (ED25519)'],
                        [f'ssh-ed25519 {KEY2} root@abc']))
        with self.assertRaises(guest.Refused):
            guest.trusted_host_keys(parsed)

    def test_two_blocks_refused(self):
        one = serial_text([f'256 {fingerprint(KEY1)} root@abc (ED25519)'],
                          [f'ssh-ed25519 {KEY1} root@abc'])
        with self.assertRaises(guest.Refused):
            guest.parse_serial_host_keys(one + one)

    def test_no_fingerprints_refused(self):
        parsed = guest.parse_serial_host_keys(serial_text(None, None))
        self.assertFalse(parsed['complete'])
        with self.assertRaises(guest.Refused):
            guest.trusted_host_keys(parsed)


# ---------------------------------------------------------------- ports and QMP


class Ports(unittest.TestCase):
    def test_allocate_distinct_free_loopback_ports(self):
        for _ in range(5):
            ports = guest.allocate_ports(2)
            self.assertEqual(len(set(ports)), 2)
            for port in ports:
                self.assertTrue(1024 <= port <= 65535)
                self.assertTrue(guest.port_free(port))

    def test_port_in_use_detected(self):
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        sock.listen(1)
        try:
            self.assertFalse(guest.port_free(sock.getsockname()[1]))
        finally:
            sock.close()


class FakeQmp(threading.Thread):
    """Speaks just enough QMP: greeting, capabilities, an event before a reply, errors."""

    def __init__(self):
        super().__init__(daemon=True)
        self.server = socket.socket()
        self.server.bind(('127.0.0.1', 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.commands = []

    def run(self):
        conn, _ = self.server.accept()
        f = conn.makefile('rw', encoding='utf-8', newline='\n')
        f.write(json.dumps({'QMP': {'version': {}, 'capabilities': []}}) + '\n')
        f.flush()
        for line in f:
            cmd = json.loads(line)['execute']
            self.commands.append(cmd)
            if cmd == 'quit':
                f.write(json.dumps({'event': 'SHUTDOWN', 'data': {}}) + '\n')
                f.write(json.dumps({'return': {}}) + '\n')
            elif cmd == 'bogus':
                f.write(json.dumps({'error': {'class': 'CommandNotFound'}}) + '\n')
            else:
                f.write(json.dumps({'return': {'status': 'running'}}) + '\n')
            f.flush()
        conn.close()
        self.server.close()


class QmpClient(unittest.TestCase):
    def test_events_skipped_and_errors_raised(self):
        server = FakeQmp()
        server.start()
        with guest.Qmp(server.port, timeout=5) as qmp:
            self.assertEqual(qmp.execute('query-status'), {'status': 'running'})
            with self.assertRaises(guest.QmpError):
                qmp.execute('bogus')
            self.assertEqual(qmp.execute('quit'), {})
            self.assertEqual(qmp.events[0]['event'], 'SHUTDOWN')
        server.join(5)
        self.assertEqual(server.commands, ['qmp_capabilities', 'query-status', 'bogus', 'quit'])


# ---------------------------------------------------------------- probes and evaluation


class Probes(unittest.TestCase):
    def test_script_and_parse(self):
        probes = guest.guest_probes(PORTS, ['192.0.2.10'], '198.51.100.7')
        names = [n for n, _ in probes]
        self.assertEqual(len(names), len(set(names)))
        for required in ('egress_tcp_1.1.1.1_443', 'egress_tcp_8.8.8.8_53',
                         'egress_tcp_10.0.2.2_qmp', 'egress_tcp_10.0.2.2_ssh',
                         'egress_dns_getent', 'egress_udp_dns', 'egress_http_name',
                         'egress_http_ip', 'egress_tcp_host_192.0.2.10_ssh',
                         'control_tcp_guest_sshd', 'cpu_vmx_svm', 'machine_id'):
            self.assertIn(required, names)
        script = guest.probe_script(probes, '@@m')
        self.assertIn('/dev/tcp/$0/$1"\' 10.0.2.2 40002', script)
        self.assertEqual(script.count('</dev/null 2>&1'), len(probes))
        output = ('noise\n@@m BEGIN nproc\n8\n@@m END nproc rc=0\n'
                  '@@m BEGIN egress_tcp_1.1.1.1_443\nbash: connect: timed out\n'
                  '@@m END egress_tcp_1.1.1.1_443 rc=124\n@@m BEGIN cut\npartial')
        parsed = guest.parse_probe_output(output, '@@m')
        self.assertEqual(parsed, {'nproc': {'rc': 0, 'out': '8'},
                                  'egress_tcp_1.1.1.1_443': {'rc': 124,
                                                             'out': 'bash: connect: timed out'}})

    def test_ssh_sends_the_script_as_lf_bytes(self):
        """Regression (F-03.2.2b cycle 1): a text-mode pipe on Windows sent CRLF to bash."""
        tmp = Path(tempfile.mkdtemp(prefix='aieh-guest-ssh-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / 'ssh').mkdir()
        (tmp / 'ssh' / 'id_ed25519').write_text('k')
        (tmp / 'ssh' / 'known_hosts').write_text('h')
        ssh = guest.Ssh.__new__(guest.Ssh)
        ssh.argv = lambda user, command: ['ssh', f'{user}@127.0.0.1'] + list(command)
        script = guest.probe_script(guest.guest_probes(PORTS, [], None), '@@m')
        seen = {}

        def fake_run(argv, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, b'out\r\nline\n', b'')
        with mock.patch.object(guest.subprocess, 'run', fake_run):
            result = ssh.run(['bash', '-s'], input_text=script)
        self.assertIsInstance(seen['input'], bytes)
        self.assertNotIn(b'\r', seen['input'])
        self.assertNotIn('text', seen)
        self.assertEqual(result.stdout, 'out\nline\n')

    def test_probe_blocked(self):
        tcp, dns, udp = 'egress_tcp_1.1.1.1_443', 'egress_dns_getent', 'egress_udp_dns'
        self.assertTrue(guest.probe_blocked(tcp, {'rc': 124}))
        self.assertTrue(guest.probe_blocked(tcp, {'rc': 1}))
        self.assertFalse(guest.probe_blocked(tcp, {'rc': 0}))
        self.assertTrue(guest.probe_blocked(dns, {'rc': 2}))
        self.assertFalse(guest.probe_blocked(dns, {'rc': 0}))
        self.assertTrue(guest.probe_blocked(udp, {'rc': 10}))
        self.assertFalse(guest.probe_blocked(udp, {'rc': 3}))
        self.assertFalse(guest.probe_blocked(udp, {'rc': 1}))     # a crash is not "blocked"
        self.assertFalse(guest.probe_blocked(udp, {'rc': 0}))
        self.assertFalse(guest.probe_blocked(tcp, {'rc': None}))
        self.assertFalse(guest.probe_blocked(tcp, None))


def passing_observation(record):
    gib = 1024 ** 3
    kh = [fingerprint(KEY1)]
    g = {
        'uname': 'Linux 6.12.115-cloud-amd64 #1 SMP x86_64 GNU/Linux',
        'nproc': '8',
        'meminfo': 'MemTotal:       16374960 kB\nSwapTotal:             0 kB',
        'lsblk': json.dumps({'blockdevices': [
            {'name': 'vda', 'size': 40 * gib, 'serial': 'root', 'ro': False},
            {'name': 'vdb', 'size': 120 * gib, 'serial': 'scratch', 'ro': False},
            {'name': 'vdc', 'size': 57344, 'serial': 'cidata', 'ro': True}]}),
        'findmnt': json.dumps({'filesystems': [{'target': '/', 'fstype': 'ext4', 'children': [
            {'target': '/srv/scratch', 'fstype': 'ext4'}, {'target': '/proc', 'fstype': 'proc'}]}]}),
        'findmnt_shares': 'count=0',
        'mnt_c': 'absent',
        'cpu_vmx_svm': '0',
        'dev_kvm': 'absent',
        'machine_id': '0123456789abcdef0123456789abcdef',
        'hostname': 'abc',
        'id_agent': 'uid=1000(agent) gid=1000(agent) groups=1000(agent)',
        'sudo_check': 'sudo: a password is required',
        'sshd_dropin': 'PermitRootLogin no\nPasswordAuthentication no',
        'host_keys': f'256 {kh[0]} root@abc (ED25519)',
        'cloud_init_query': f'{record["instance"]["instance_id"]} abc nocloud config-disk (/dev/vdc)',
        'scratch_mount': '/dev/vdb ext4 rw,relatime',
        'exchange_dirs': '/home/agent/exchange agent 750\n/srv/scratch/agent agent 750',
        'ip6_addr': '1: lo: <LOOPBACK,UP>\n    inet6 ::1/128 scope host',
        'virtio_ports': 'ls: cannot access',
        'host_sockets': 'docker.sock absent\nDOCKER_HOST=unset\nX11 absent',
        'control_tcp_guest_sshd': '',
        'control_dns_localhost': '::1 localhost',
        'egress_tcp_1.1.1.1_443': '',
        'egress_dns_getent': '',
        'egress_udp_dns': 'control loopback udp REPLY\n8.8.8.8 udp/53 NO-REPLY timeout',
    }
    rc = {'sudo_check': 1, 'virtio_ports': 2, 'egress_tcp_1.1.1.1_443': 124,
          'egress_dns_getent': 2, 'egress_udp_dns': 10}
    guest_obs = {k: {'rc': rc.get(k, 0), 'out': v} for k, v in g.items()}
    image = record['inputs']['image']['path']
    digests = {k: {'match': True, 'sha256': v['sha256']} for k, v in record['inputs'].items()}
    pins = {'image': PROFILE['boot_inputs']['image']['sha256'],
            'firmware': PROFILE['boot_inputs']['firmware']['sha256'],
            'provider_binary': PROFILE['boot_inputs']['provider_binary']['sha256']}
    for key, pin in pins.items():
        digests[key]['sha256'] = pin
    return {
        'host_os': 'Windows-11-10.0.26300-SP0',
        'input_digests': digests,
        'qmp': {
            'query-accelerators': {'enabled': 'whpx'},
            'query-status': {'status': 'running'},
            'query-cpus-fast': [{'cpu-index': i} for i in range(8)],
            'query-memory-size-summary': {'base-memory': 16 * gib},
            'query-block': [{'inserted': {'node-name': n}} for n in ('root', 'scratch', 'seed')],
            'query-named-block-nodes': [
                {'node-name': 'seed', 'ro': True}, {'node-name': 'seed-file', 'ro': True},
                {'node-name': 'base', 'ro': True}, {'node-name': 'base-file', 'ro': True},
                {'node-name': 'root', 'ro': False}, {'node-name': 'scratch', 'ro': False}],
            'query-pci': [{'bus': 0, 'devices': [
                {'id': {'vendor': 0x8086, 'device': 0x29c0}},
                {'id': {'vendor': 0x1af4, 'device': 0x1042}},
                {'id': {'vendor': 0x1af4, 'device': 0x1042}},
                {'id': {'vendor': 0x1af4, 'device': 0x1042}},
                {'id': {'vendor': 0x1af4, 'device': 0x1041}},
                {'id': {'vendor': 0x1af4, 'device': 0x1044}},
                {'id': {'vendor': 0x8086, 'device': 0x2918}},
                {'id': {'vendor': 0x8086, 'device': 0x2922}},
                {'id': {'vendor': 0x8086, 'device': 0x2930}}]}],
            'query-chardev': [{'label': 'serial0'}, {'label': 'qmp'}],
            'cpu-flags': [{'cpu-index': i, 'vmx': False, 'svm': False} for i in range(8)],
        },
        'qemu_img': {'root.qcow2': {'virtual-size': 40 * gib, 'backing-filename': image},
                     'scratch.qcow2': {'virtual-size': 120 * gib}},
        'host': {'bindings': {'tcp_by_pid': [
            {'LocalAddress': '127.0.0.1', 'LocalPort': PORTS['ssh'], 'State': 'Listen'},
            {'LocalAddress': '127.0.0.1', 'LocalPort': PORTS['qmp'], 'State': 'Listen'},
            {'LocalAddress': '127.0.0.1', 'LocalPort': PORTS['ssh'], 'State': 'Established'}],
            'udp_by_pid': []},
            'non_loopback': {'192.0.2.10:40001': 'refused', '192.0.2.10:40002': 'refused'}},
        'guest': guest_obs,
        'root_login': {'rc': 255, 'stderr': 'root@127.0.0.1: Permission denied (publickey).'},
        'known_hosts_fingerprints': kh,
    }


class Evaluate(LaunchRecord):
    def verdicts(self, obs):
        return {p['property']: p['verdict'] for p in guest.evaluate(PROFILE, self.record, obs)}

    def test_passing_observation(self):
        v = self.verdicts(passing_observation(self.record))
        for pid in ('P1', 'P2', 'P3', 'P4', 'P6', 'P8', 'P9', 'P11', 'P12'):
            self.assertEqual(v[f'profiles {pid}'], 'PASS', pid)
        # owned by later leaves, or (P7) no allowlisted endpoint to positively control yet
        for pid in ('P5', 'P7', 'P10'):
            self.assertEqual(v[f'profiles {pid}'], 'UNKNOWN', pid)

    def assertFailsWith(self, pid, mutate):
        obs = passing_observation(self.record)
        mutate(obs)
        self.assertEqual(self.verdicts(obs)[f'profiles {pid}'], 'FAIL')

    def test_failures(self):
        g = lambda obs, k, v, rc=0: obs['guest'].__setitem__(k, {'rc': rc, 'out': v})  # noqa: E731
        self.assertFailsWith('P7', lambda o: g(o, 'egress_tcp_1.1.1.1_443', '', 0))
        self.assertFailsWith('P7', lambda o: g(o, 'egress_udp_dns', '8.8.8.8 udp/53 REPLY', 3))
        self.assertFailsWith('P7', lambda o: g(o, 'control_tcp_guest_sshd', 'refused', 1))
        self.assertFailsWith('P7', lambda o: o['host']['non_loopback'].__setitem__(
            '192.0.2.10:40001', 'connected'))
        self.assertFailsWith('P7', lambda o: o['host']['bindings']['tcp_by_pid'].append(
            {'LocalAddress': '0.0.0.0', 'LocalPort': 5900, 'State': 'Listen'}))
        self.assertFailsWith('P12', lambda o: g(o, 'cpu_vmx_svm', '8'))
        self.assertFailsWith('P3', lambda o: g(o, 'findmnt_shares', 'host0 /mnt 9p\ncount=1'))
        self.assertFailsWith('P2', lambda o: g(o, 'meminfo', 'MemTotal: 13000000 kB'))
        self.assertFailsWith('P2', lambda o: g(o, 'nproc', '4'))
        self.assertFailsWith('P4', lambda o: o['qmp']['query-pci'][0]['devices'].append(
            {'id': {'vendor': 0x1af4, 'device': 0x1043}}))
        self.assertFailsWith('P4', lambda o: o['qmp']['query-named-block-nodes'].__setitem__(
            0, {'node-name': 'seed', 'ro': False}))
        self.assertFailsWith('P8', lambda o: g(o, 'id_agent', 'uid=1000(agent) gid=1000(agent) '
                                               'groups=1000(agent),27(sudo)'))
        self.assertFailsWith('P8', lambda o: o.__setitem__('root_login', {'rc': 0, 'stderr': ''}))
        self.assertFailsWith('P8', lambda o: g(o, 'machine_id', 'uninitialized'))
        self.assertFailsWith('P9', lambda o: o['input_digests']['image'].__setitem__('match', False))


if __name__ == '__main__':
    unittest.main()
