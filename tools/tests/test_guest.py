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
import io
import json
import os
import re
import shutil
import socket
import stat
import struct
import subprocess
import tarfile
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

    def test_destroy_removes_read_only_files(self):
        """Git for Windows writes pack files read-only; the exchange's verification
        repository lives in the instance directory (F-03.3.1 defect, fixed forward)."""
        self.populate()
        pack = self.state / 'instances' / 'aa' / 'exchange' / 'verify' / 'x.git' / 'pack.idx'
        pack.parent.mkdir(parents=True)
        pack.write_bytes(b'pack')
        os.chmod(pack, stat.S_IREAD)
        outside = self.state / 'keep-read-only.txt'
        outside.write_bytes(b'keep')
        os.chmod(outside, stat.S_IREAD)
        self.addCleanup(os.chmod, outside, stat.S_IWRITE | stat.S_IREAD)
        result = guest.destroy(self.ctx(), 'aa')
        self.assertEqual(result['result'], 'destroyed')
        self.assertFalse((self.state / 'instances' / 'aa').exists())
        self.assertTrue(outside.exists())
        self.assertFalse(os.access(outside, os.W_OK))          # untouched outside the instance

    def test_remove_tree_reraises_other_errors(self):
        with self.assertRaises(FileNotFoundError):
            guest.remove_tree(self.state / 'missing')

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


# Probe outputs shaped as the F-03.3.1 reconnaissance guest printed them (Debian 13
# genericcloud under this profile, 2026-11-06), used by the passing observation.
GIB = 1024 ** 3
RECON_MOUNTS = [
    ('/sys', 'sysfs', 'sysfs'), ('/proc', 'proc', 'proc'), ('/dev', 'udev', 'devtmpfs'),
    ('/dev/pts', 'devpts', 'devpts'), ('/run', 'tmpfs', 'tmpfs'), ('/', '/dev/vda1', 'ext4'),
    ('/sys/kernel/security', 'securityfs', 'securityfs'), ('/dev/shm', 'tmpfs', 'tmpfs'),
    ('/sys/fs/cgroup', 'cgroup2', 'cgroup2'), ('/sys/fs/pstore', 'pstore', 'pstore'),
    ('/sys/fs/bpf', 'bpf', 'bpf'), ('/proc/sys/fs/binfmt_misc', 'systemd-1', 'autofs'),
    ('/dev/mqueue', 'mqueue', 'mqueue'), ('/dev/hugepages', 'hugetlbfs', 'hugetlbfs'),
    ('/run/lock', 'tmpfs', 'tmpfs'), ('/sys/kernel/debug', 'debugfs', 'debugfs'),
    ('/sys/kernel/tracing', 'tracefs', 'tracefs'), ('/tmp', 'tmpfs', 'tmpfs'),
    ('/run/credentials/systemd-journald.service', 'tmpfs', 'tmpfs'),
    ('/sys/kernel/config', 'configfs', 'configfs'),
    ('/sys/fs/fuse/connections', 'fusectl', 'fusectl'),
    ('/run/credentials/systemd-resolved.service', 'tmpfs', 'tmpfs'),
    ('/boot/efi', '/dev/vda15', 'vfat'),
    ('/proc/sys/fs/binfmt_misc', 'binfmt_misc', 'binfmt_misc'),
    ('/run/credentials/systemd-networkd.service', 'tmpfs', 'tmpfs'),
    ('/srv/scratch', '/dev/vdb', 'ext4'),
    ('/run/credentials/getty@tty1.service', 'tmpfs', 'tmpfs'),
    ('/run/credentials/serial-getty@ttyS0.service', 'tmpfs', 'tmpfs'),
    ('/run/user/1000', 'tmpfs', 'tmpfs'),
]


def findmnt_json(mounts):
    return json.dumps({'filesystems': [{'target': t, 'source': s, 'fstype': f,
                                        'options': 'rw,relatime'} for t, s, f in mounts]})


def lsblk_json(extra=()):
    return json.dumps({'blockdevices': [
        {'name': 'vda', 'path': '/dev/vda', 'size': 40 * GIB, 'type': 'disk', 'ro': False,
         'serial': 'root', 'mountpoints': [], 'children': [
             {'name': 'vda1', 'path': '/dev/vda1', 'type': 'part', 'ro': False, 'serial': None,
              'fstype': 'ext4', 'mountpoints': ['/']},
             {'name': 'vda14', 'path': '/dev/vda14', 'type': 'part', 'ro': False, 'serial': None,
              'mountpoints': []},
             {'name': 'vda15', 'path': '/dev/vda15', 'type': 'part', 'ro': False, 'serial': None,
              'fstype': 'vfat', 'mountpoints': ['/boot/efi']}]},
        {'name': 'vdb', 'path': '/dev/vdb', 'size': 120 * GIB, 'type': 'disk', 'ro': False,
         'serial': 'scratch', 'fstype': 'ext4', 'mountpoints': ['/srv/scratch']},
        {'name': 'vdc', 'path': '/dev/vdc', 'size': 57344, 'type': 'disk', 'ro': True,
         'serial': 'cidata', 'fstype': 'iso9660', 'mountpoints': []}] + list(extra)})


RECON_SOCKETS = [
    '/run/dbus/system_bus_socket', '/run/ssh-unix-local/socket', '/run/systemd/journal/socket',
    '/run/systemd/private', '/run/udev/control', '/run/user/1000/openssh_agent',
    '/run/user/1000/systemd/private', '/run/uuidd/request']
RECON_SS = '\n'.join(f'u_str LISTEN 0      4096 {s} {4890 + i} * 0'
                     for i, s in enumerate(RECON_SOCKETS))
MGMT_ENV_UNSET = '\n'.join(f'{scope} {v}=unset' for scope in ('session', 'login')
                           for v in guest.MGMT_ENV)


def passing_p5():
    return {
        'control': {'path': '/srv/scratch/agent/.aieh-p5-control-0a0b0c0d0e0f', 'planted_rc': 0,
                    'planted': '/srv/scratch/agent/.aieh-p5-control-0a0b0c0d0e0f 260',
                    'removed': 'absent', 'expected_classes': guest.OWNER_CLASSES},
        'collection': {'rc': 0, 'bytes': 466920, 'roots': list(guest.COLLECT_ROOTS), 'stderr': [],
                       'env_files': ['aieh-env/login-shell.env', 'aieh-env/pid1.err',
                                     'aieh-env/pid1.status', 'aieh-env/ssh-session.env'],
                       'pid1_environ': 'unreadable'},
        'canaries': [{'label': 'env:AIEH_CANARY_ENV', 'sha256': '0' * 64}],
        'summary': {'members': 900, 'bytes': 3000000, 'truncated': [],
                    'control_classes': list(guest.OWNER_CLASSES), 'owner_hits': [],
                    'canary_hits': [], 'key_hits': []},
    }


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
        'findmnt': findmnt_json(RECON_MOUNTS),
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
        'virtio_devices': '0x1af4 0x0002\n0x1af4 0x0002\n0x1af4 0x0002\n0x1af4 0x0001\n'
                          '0x1af4 0x0004\nend',
        'vsock': 'local_cid 1\ncid2 ECONNRESET',
        'socket_inventory': '\n'.join(RECON_SOCKETS + ['end']),
        'unix_sockets': RECON_SS,
        'mgmt_paths': 'end',
        'mgmt_env': MGMT_ENV_UNSET,
        'guest_ssh_agent': 'The agent has no identities.',
        'qemu_ga': 'qemu-ga absent\ninactive',
        'storage_dirs': '/home/agent/exchange|agent|agent|750|directory|/\n'
                        '/srv/scratch/agent|agent|agent|750|directory|/srv/scratch',
        'forbidden_paths': 'absent /mnt/c\nabsent /mnt/wslg',
        'egress_tcp_10.0.2.2_qmp': '',
        'x11_unix': 'type=directory\nend',
        'control_tcp_guest_sshd': '',
        'control_dns_localhost': '::1 localhost',
        'egress_tcp_1.1.1.1_443': '',
        'egress_dns_getent': '',
        'egress_udp_dns': 'control loopback udp REPLY\n8.8.8.8 udp/53 NO-REPLY timeout',
    }
    g['lsblk'] = lsblk_json()
    rc = {'sudo_check': 1, 'virtio_ports': 2, 'egress_tcp_1.1.1.1_443': 124,
          'egress_dns_getent': 2, 'egress_udp_dns': 10, 'egress_tcp_10.0.2.2_qmp': 124,
          'guest_ssh_agent': 1, 'qemu_ga': 3}
    guest_obs = {k: {'rc': rc.get(k, 0), 'out': v} for k, v in g.items()}
    idir = record['instance']['instance_dir']
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
                {'node-name': 'seed', 'ro': True, 'file': record['inputs']['seed']['path']},
                {'node-name': 'seed-file', 'ro': True, 'file': record['inputs']['seed']['path']},
                {'node-name': 'base', 'ro': True, 'file': image},
                {'node-name': 'base-file', 'ro': True, 'file': image},
                {'node-name': 'root', 'ro': False, 'file': f'{idir}/root.qcow2'},
                {'node-name': 'root-file', 'ro': False, 'file': f'{idir}/root.qcow2'},
                {'node-name': 'scratch', 'ro': False, 'file': f'{idir}/scratch.qcow2'},
                {'node-name': 'scratch-file', 'ro': False, 'file': f'{idir}/scratch.qcow2'}],
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
        'p5': passing_p5(),
        'artifacts': {name: {'labels': dict(record['labels']), 'problems': []}
                      for name in ('launch.json', 'process.json', 'records/create-1.json',
                                   'stderr.log#header1')},
    }


class Evaluate(LaunchRecord):
    def verdicts(self, obs):
        return {p['property']: p['verdict'] for p in guest.evaluate(PROFILE, self.record, obs)}

    def test_passing_observation(self):
        v = self.verdicts(passing_observation(self.record))
        # P7: the committed profile's enforcement point is qualified (F-03.3.2)
        for pid in ('P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8', 'P9', 'P11', 'P12'):
            self.assertEqual(v[f'profiles {pid}'], 'PASS', pid)
        self.assertEqual(v['profiles P10'], 'UNKNOWN')            # owned by F-03.4

    def test_every_surface_check_passes(self):
        """Each P3-P6 check, not only the property verdict, is PASS on the recon shape."""
        props = guest.evaluate(PROFILE, self.record, passing_observation(self.record))
        for p in props:
            if p['property'] in guest.SURFACE_PROPERTIES:
                for c in p['checks']:
                    self.assertEqual(c['verdict'], 'PASS', (p['property'], c['check'], c['observed']))

    def test_p5_unknown_without_canaries_or_collection(self):
        obs = passing_observation(self.record)
        obs['p5']['canaries'] = None
        self.assertEqual(self.verdicts(obs)['profiles P5'], 'UNKNOWN')
        obs = passing_observation(self.record)
        del obs['p5']
        self.assertEqual(self.verdicts(obs)['profiles P5'], 'UNKNOWN')
        obs = passing_observation(self.record)
        obs['p5'] = {'collection': {'error': 'TarError: truncated'}, 'control': {}}
        self.assertEqual(self.verdicts(obs)['profiles P5'], 'UNKNOWN')

    def assertFailsWith(self, pid, mutate):
        obs = passing_observation(self.record)
        mutate(obs)
        self.assertEqual(self.verdicts(obs)[f'profiles {pid}'], 'FAIL')

    def test_x11_unix_cases(self):
        """P6 as amended 2026-11-06: no socket under /tmp/.X11-unix (x11_unix probe output)."""
        cases = {
            'absent': True,                                          # path does not exist
            'type=directory\nend': True,                             # empty, as tmpfiles.d makes it
            'type=directory\r\nend\r\n': True,                       # CRLF-tolerant
            'type=directory\ns /tmp/.X11-unix/X0\nend': False,       # an X11 socket
            'type=directory\nf /tmp/.X11-unix/.X0-lock\nend': False,  # another non-directory entry
            'type=directory\nl /tmp/.X11-unix/X0\nend': False,       # a symlink inside
            'symlink': False,                                        # the path is a symlink
            'type=socket\nend': False,                               # the path is a socket
            'type=regular empty file\nend': False,
            'type=directory\nfind: permission denied\nend': False,   # incomplete listing
            'type=directory': False,                                 # truncated output
            '': False,                                               # probe missing
        }
        for text, clean in cases.items():
            self.assertEqual(guest.x11_unix_clean(text), clean, repr(text))
        # and through the P6 verdict
        for text, verdict in (('type=directory\nend', 'PASS'), ('absent', 'PASS'),
                              ('type=directory\ns /tmp/.X11-unix/X0\nend', 'FAIL'),
                              ('symlink', 'FAIL')):
            obs = passing_observation(self.record)
            obs['guest']['x11_unix'] = {'rc': 0, 'out': text}
            self.assertEqual(self.verdicts(obs)['profiles P6'], verdict, repr(text))

    def test_x11_unix_probe_is_listed(self):
        snippet = dict(guest.guest_probes(PORTS, [], None))['x11_unix']
        self.assertIn('[ -L "$x" ]', snippet)
        self.assertIn("! -type d -printf '%y %p\\n'", snippet)

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


class SurfaceNegativeControls(Evaluate):
    """F-03.3.1 negative controls: each sample observation holds one violation of profiles
    P3, P4, P5 or P6, and that property must FAIL. No violation is created on a host."""

    def set_out(self, obs, key, out, rc=0):
        obs['guest'][key] = {'rc': rc, 'out': out}

    # profiles P3: no automatic host shares
    def test_p3_share_mount(self):
        self.assertFailsWith('P3', lambda o: self.set_out(o, 'findmnt', findmnt_json(
            RECON_MOUNTS + [('/mnt/host', 'hostshare', '9p')])))

    def test_p3_virtiofs_and_fuse_share(self):
        for fstype in ('virtiofs', 'fuse.sshfs', 'cifs', 'nfs4', 'drvfs'):
            self.assertFailsWith('P3', lambda o, t=fstype: self.set_out(o, 'findmnt', findmnt_json(
                RECON_MOUNTS + [('/srv/x', 'share', t)])))

    def test_p3_unlisted_mount_of_an_allowed_type(self):
        # a tmpfs or ext4 mount that the allowlist does not name is caught by the exact table
        self.assertFailsWith('P3', lambda o: self.set_out(o, 'findmnt', findmnt_json(
            RECON_MOUNTS + [('/mnt/c', 'tmpfs', 'tmpfs')])))
        self.assertFailsWith('P3', lambda o: self.set_out(o, 'findmnt', findmnt_json(
            RECON_MOUNTS + [('/home/agent/exchange', '/dev/vdb', 'ext4')])))

    def test_p3_declared_mount_missing(self):
        self.assertFailsWith('P3', lambda o: self.set_out(o, 'findmnt', findmnt_json(
            [m for m in RECON_MOUNTS if m[0] != '/srv/scratch'])))

    def test_p3_mount_on_the_wrong_disk(self):
        swapped = [('/srv/scratch', '/dev/vda1', 'ext4') if m[0] == '/srv/scratch' else m
                   for m in RECON_MOUNTS]
        self.assertFailsWith('P3', lambda o: self.set_out(o, 'findmnt', findmnt_json(swapped)))

    def test_p3_seed_mounted(self):
        self.assertFailsWith('P3', lambda o: self.set_out(o, 'findmnt', findmnt_json(
            RECON_MOUNTS + [('/mnt/seed', '/dev/vdc', 'iso9660')])))

    def test_p3_forbidden_path_present(self):
        self.assertFailsWith('P3', lambda o: self.set_out(o, 'forbidden_paths',
                                                          'present /mnt/c\nabsent /mnt/wslg'))
        self.assertFailsWith('P3', lambda o: self.set_out(o, 'mnt_c', 'present'))

    def test_p3_virtio_9p_or_fs_device(self):
        for ident in ('0x0009', '0x001a'):
            self.assertFailsWith('P3', lambda o, i=ident: self.set_out(
                o, 'virtio_devices', o['guest']['virtio_devices']['out'].replace(
                    'end', f'0x1af4 {i}\nend')))

    def test_p3_share_count(self):
        self.assertFailsWith('P3', lambda o: self.set_out(o, 'findmnt_shares',
                                                          'host0 /mnt 9p\ncount=1'))

    # profiles P4: repository exchange and scratch only
    def test_p4_extra_guest_disk(self):
        extra = {'name': 'vdd', 'path': '/dev/vdd', 'size': 1, 'type': 'disk', 'ro': False,
                 'serial': 'owner-repo', 'mountpoints': []}
        self.assertFailsWith('P4', lambda o: self.set_out(o, 'lsblk', lsblk_json([extra])))

    def test_p4_extra_block_node(self):
        self.assertFailsWith('P4', lambda o: o['qmp']['query-named-block-nodes'].append(
            {'node-name': 'share-file', 'ro': False, 'file': 'C:/Users/user/repo.img'}))
        self.assertFailsWith('P4', lambda o: o['qmp']['query-block'].append(
            {'inserted': {'node-name': 'share'}}))

    def test_p4_block_node_file_elsewhere(self):
        def mutate(o):
            for node in o['qmp']['query-named-block-nodes']:
                if node['node-name'] == 'scratch-file':
                    node['file'] = 'C:/Users/user/scratch.qcow2'
        self.assertFailsWith('P4', mutate)

    def test_p4_writable_seed_or_base(self):
        for name in ('seed', 'seed-file', 'base', 'base-file'):
            def mutate(o, n=name):
                for node in o['qmp']['query-named-block-nodes']:
                    if node['node-name'] == n:
                        node['ro'] = False
            self.assertFailsWith('P4', mutate)

    def test_p4_seed_not_read_only_in_guest(self):
        self.assertFailsWith('P4', lambda o: self.set_out(o, 'lsblk', lsblk_json().replace(
            '"ro": true, "serial": "cidata"', '"ro": false, "serial": "cidata"')))

    def test_p4_exchange_directory_wrong(self):
        good = '/home/agent/exchange|agent|agent|750|directory|/\n' \
               '/srv/scratch/agent|agent|agent|750|directory|/srv/scratch'
        for bad in (good.replace('|agent|agent|750|directory|/\n', '|root|root|750|directory|/\n'),
                    good.replace('750|directory|/\n', '777|directory|/\n'),
                    good.replace('750|directory|/\n', '750|symbolic link|/\n'),
                    good.replace('|directory|/srv/scratch', '|directory|/'),
                    good.split('\n')[0]):
            self.assertFailsWith('P4', lambda o, b=bad: self.set_out(o, 'storage_dirs', b))

    # profiles P5: no Owner secrets
    def test_p5_canary_found(self):
        self.assertFailsWith('P5', lambda o: o['p5']['summary']['canary_hits'].append(
            {'label': 'canary:env:AIEH_CANARY_ENV', 'where': 'guest:aieh-env/login-shell.env'}))

    def test_p5_canary_in_the_seed(self):
        self.assertFailsWith('P5', lambda o: o['p5']['summary']['canary_hits'].append(
            {'label': 'canary:home:.git-credentials', 'where': 'host:seed.iso:seed.iso'}))

    def test_p5_owner_class_found(self):
        for cls in guest.OWNER_CLASSES:
            self.assertFailsWith('P5', lambda o, c=cls: o['p5']['summary']['owner_hits'].append(
                {'class': c, 'where': 'guest:etc/environment'}))

    def test_p5_private_key_found(self):
        self.assertFailsWith('P5', lambda o: o['p5']['summary']['key_hits'].append(
            {'where': 'guest:home/agent/.ssh/id_ed25519'}))

    def test_p5_positive_control_incomplete(self):
        self.assertFailsWith('P5', lambda o: o['p5']['summary']['control_classes'].remove(
            'cloud-token'))
        self.assertFailsWith('P5', lambda o: o['p5']['control'].__setitem__('removed', 'present'))
        self.assertFailsWith('P5', lambda o: o['p5']['control'].__setitem__('planted_rc', 1))

    def test_p5_collection_incomplete(self):
        self.assertFailsWith('P5', lambda o: o['p5']['collection']['env_files'].remove(
            'aieh-env/login-shell.env'))
        self.assertFailsWith('P5', lambda o: o['p5']['collection'].__setitem__('rc', 255))
        self.assertFailsWith('P5', lambda o: o['p5']['summary']['truncated'].append('var/log/x'))

    def test_p5_unscrubbed_launch_environment(self):
        obs = passing_observation(self.record)
        record = copy.deepcopy(self.record)
        record['env']['GITHUB_TOKEN'] = 'ghp_x'
        verdicts = {p['property']: p['verdict'] for p in guest.evaluate(PROFILE, record, obs)}
        self.assertEqual(verdicts['profiles P5'], 'FAIL')

    # profiles P6: no host-management sockets or interop
    def test_p6_docker_socket_path(self):
        self.assertFailsWith('P6', lambda o: self.set_out(o, 'mgmt_paths',
                                                          'present /var/run/docker.sock\nend'))
        self.assertFailsWith('P6', lambda o: self.set_out(o, 'mgmt_paths', 'present /mnt/wslg\nend'))

    def test_p6_socket_inventory(self):
        for sock in ('/tmp/.X11-unix/X0', '/run/docker.sock', '/run/user/1000/wayland-0',
                     '/var/lib/incus/unix.socket', '/run/libvirt/libvirt-sock',
                     '/mnt/wslg/PulseServer'):
            self.assertFailsWith('P6', lambda o, s=sock: self.set_out(
                o, 'socket_inventory', '\n'.join(RECON_SOCKETS + [s, 'end'])))

    def test_p6_listening_socket(self):
        self.assertFailsWith('P6', lambda o: self.set_out(
            o, 'unix_sockets', RECON_SS + '\nu_str LISTEN 0 4096 /run/containerd/containerd.sock 1 * 0'))

    def test_p6_incomplete_socket_inventory(self):
        obs = passing_observation(self.record)
        self.set_out(obs, 'socket_inventory', '\n'.join(RECON_SOCKETS))     # no 'end'
        self.assertNotEqual(self.verdicts(obs)['profiles P6'], 'PASS')

    def test_p6_management_environment(self):
        for var in ('DOCKER_HOST', 'DISPLAY', 'SSH_AUTH_SOCK', 'WAYLAND_DISPLAY'):
            self.assertFailsWith('P6', lambda o, v=var: self.set_out(
                o, 'mgmt_env', MGMT_ENV_UNSET.replace(f'login {v}=unset', f'login {v}=set')))

    def test_p6_vsock_transport(self):
        self.assertFailsWith('P6', lambda o: self.set_out(o, 'vsock', 'local_cid 3\ncid2 ECONNRESET'))
        self.assertFailsWith('P6', lambda o: self.set_out(o, 'vsock', 'local_cid 1\ncid2 CONNECTED'))
        self.assertFailsWith('P6', lambda o: self.set_out(o, 'vsock', 'Traceback (most recent call last):'))

    def test_p6_virtio_channel_device(self):
        for ident in ('0x0003', '0x0013'):
            self.assertFailsWith('P6', lambda o, i=ident: self.set_out(
                o, 'virtio_devices', o['guest']['virtio_devices']['out'].replace(
                    'end', f'0x1af4 {i}\nend')))

    def test_p6_virtio_serial_ports(self):
        self.assertFailsWith('P6', lambda o: self.set_out(o, 'virtio_ports', 'org.qemu.guest_agent.0'))

    def test_p6_extra_chardev(self):
        self.assertFailsWith('P6', lambda o: o['qmp']['query-chardev'].append({'label': 'qga0'}))

    def test_p6_qmp_reachable_from_guest(self):
        self.assertFailsWith('P6', lambda o: self.set_out(o, 'egress_tcp_10.0.2.2_qmp', '', 0))

    def test_p6_ssh_agent_with_identities(self):
        self.assertFailsWith('P6', lambda o: self.set_out(
            o, 'guest_ssh_agent', '256 SHA256:abc owner@host (ED25519)'))

    def test_p6_guest_agent_present(self):
        self.assertFailsWith('P6', lambda o: self.set_out(o, 'qemu_ga', '/usr/sbin/qemu-ga\nactive'))

    def test_p6_x11_socket(self):
        self.assertFailsWith('P6', lambda o: self.set_out(
            o, 'x11_unix', 'type=directory\ns /tmp/.X11-unix/X0\nend'))


class MountTable(unittest.TestCase):
    STORAGE = PROFILE['guest_storage']

    def serials(self):
        return guest.lsblk_disks(lsblk_json())[0]

    def mounts(self, extra=()):
        return guest.flatten_mounts(findmnt_json(RECON_MOUNTS + list(extra)))

    def test_recon_table_matches_exactly(self):
        diff = guest.compare_mounts(self.STORAGE, self.mounts(), self.serials())
        self.assertEqual((diff['unlisted'], diff['missing']), ([], []))
        self.assertEqual(diff['matched'], len(RECON_MOUNTS))

    def test_wildcard_is_one_component(self):
        diff = guest.compare_mounts(self.STORAGE, self.mounts(
            [('/run/credentials/a/b', 'tmpfs', 'tmpfs')]), self.serials())
        self.assertEqual([m['target'] for m in diff['unlisted']], ['/run/credentials/a/b'])

    def test_exact_entry_matches_once(self):
        diff = guest.compare_mounts(self.STORAGE, self.mounts([('/tmp', 'tmpfs', 'tmpfs')]),
                                    self.serials())
        self.assertEqual([m['target'] for m in diff['unlisted']], ['/tmp'])

    def test_optional_entries_may_be_absent(self):
        required = [m for m in RECON_MOUNTS if not m[0].startswith(('/run/credentials/', '/run/user/'))
                    and m[2] != 'binfmt_misc']
        diff = guest.compare_mounts(self.STORAGE, guest.flatten_mounts(findmnt_json(required)),
                                    self.serials())
        self.assertEqual((diff['unlisted'], diff['missing']), ([], []))

    def test_lsblk_partitions_map_to_their_disk(self):
        serials = self.serials()
        self.assertEqual((serials['/dev/vda1'], serials['/dev/vda15'], serials['/dev/vdb'],
                          serials['/dev/vdc']), ('root', 'root', 'scratch', 'cidata'))

    def test_probes_cover_declared_directories(self):
        probes = dict(guest.guest_probes(PORTS, [], None, self.STORAGE))
        self.assertIn("'/home/agent/exchange' '/srv/scratch/agent'", probes['storage_dirs'])
        self.assertIn("'/mnt/c' '/mnt/wslg'", probes['forbidden_paths'])
        for name in ('virtio_devices', 'vsock', 'socket_inventory', 'mgmt_paths', 'mgmt_env',
                     'guest_ssh_agent', 'qemu_ga', 'egress_tcp_10.0.2.2_qmp'):
            self.assertIn(name, probes)


def make_tar(members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def keygen(directory):
    path = Path(directory) / 'id_ed25519'
    subprocess.run([guest.openssh('ssh-keygen.exe'), '-q', '-t', 'ed25519', '-N', '', '-C', 'abc',
                    '-f', str(path)], check=True, capture_output=True)
    return path


class P5Scan(unittest.TestCase):
    ENV = {'USERNAME': 'user', 'USERPROFILE': 'C:\\Users\\user'}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-p5-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_positive_control_hits_every_class(self):
        text, account = guest.control_samples('0a0b0c')
        literals, patterns = guest.p5_needles(None, None, self.ENV, None, account)
        scan = guest.scan_tar(make_tar({'srv/scratch/agent/.aieh-p5-control-0a0b0c': text.encode()}),
                              literals, patterns)
        summary = guest.summarize_p5(scan, 'srv/scratch/agent/.aieh-p5-control-0a0b0c', {})
        self.assertEqual(summary['control_classes'], guest.OWNER_CLASSES)
        self.assertEqual(summary['owner_hits'], [])

    def test_owner_classes_outside_the_control_are_hits(self):
        literals, patterns = guest.p5_needles(None, None, self.ENV, None, None)
        samples = {
            'etc/a': b'-' * 5 + b'BEGIN RSA PRIVATE KEY' + b'-' * 5,
            'etc/b': b'token=ghp_' + b'a' * 36,
            'etc/c': b'AKIA' + b'B' * 16,
            'etc/d': b'key sk-ant-api03-' + b'x' * 30,
            'etc/e': b'path C:\\Users\\user\\.ssh',
            'etc/f': b'/mnt/c/Users/user/src',
            'etc/g': b'USER logged in',
        }
        scan = guest.scan_tar(make_tar(samples), literals, patterns)
        summary = guest.summarize_p5(scan, 'none', {})
        found = {h['where'].split(':', 1)[1]: h['class'] for h in summary['owner_hits']}
        self.assertEqual(found, {'etc/a': 'private-key-header', 'etc/b': 'git-host-token',
                                 'etc/c': 'cloud-token', 'etc/d': 'llm-provider-key',
                                 'etc/e': 'host-account', 'etc/f': 'host-account',
                                 'etc/g': 'host-account'})

    def test_account_name_inside_a_longer_word_is_not_a_hit(self):
        literals, patterns = guest.p5_needles(None, None, self.ENV, None, None)
        scan = guest.scan_tar(make_tar({'etc/x': b'usernames and xuser',
                                        'etc/host-key': b'-----BEGIN SSH HOST KEY KEYS-----'}),
                              literals, patterns)
        self.assertEqual(scan['hits'], [])

    def test_canaries_found_by_value_and_core(self):
        out = make_canaries_in(self.tmp)
        data = guest.load_canaries(out)
        literals, patterns = guest.p5_needles(data, None, self.ENV, None, None)
        value = data['env']['AIEH_CANARY_ENV']
        core = value.rsplit('-', 1)[1]
        scan = guest.scan_tar(make_tar({'aieh-env/proc-1.environ': value.encode(),
                                        'home/agent/x': f'prefix {core} suffix'.encode(),
                                        'etc/clean': b'nothing'}), literals, patterns)
        summary = guest.summarize_p5(scan, 'none', {})
        self.assertEqual(sorted(h['where'] for h in summary['canary_hits']),
                         ['guest:aieh-env/proc-1.environ', 'guest:home/agent/x'])
        self.assertTrue(all(h['label'] == 'canary:env:AIEH_CANARY_ENV' for h in summary['canary_hits']))
        # the summary carries labels, never values
        self.assertNotIn(value, json.dumps(summary))

    def test_private_key_needles(self):
        key = keygen(self.tmp)
        needles = guest.private_key_needles(key)
        body = [line for line in key.read_text().splitlines() if not line.startswith('-----')]
        self.assertTrue(set(line.encode() for line in body if len(line) >= 20) <= set(needles))
        literals, patterns = guest.p5_needles(None, key, self.ENV, None, None)
        pub = (self.tmp / 'id_ed25519.pub').read_bytes()
        clean = guest.scan_tar(make_tar({'home/agent/.ssh/authorized_keys': pub}), literals, patterns)
        self.assertEqual(clean['hits'], [])                       # the public key is not a hit
        leaked = guest.scan_tar(make_tar({'tmp/k': key.read_bytes()}), literals, patterns)
        self.assertIn('instance-private-key', {h['label'] for h in leaked['hits']})
        for needle in needles:
            self.assertGreaterEqual(len(needle), 20)

    def test_seed_variants_found_at_any_alignment(self):
        key = keygen(self.tmp)
        needles = set(guest.private_key_needles(key))
        seeds = [n for n in needles if len(n) == 32 and n.hex().encode() in needles]
        self.assertEqual(len(seeds), 1)
        seed = seeds[0]
        for pad in (b'', b'x', b'xy'):
            encoded = base64.b64encode(pad + seed + b'tail')
            self.assertTrue(any(n in encoded for n in needles), pad)
        self.assertIn(seed.hex().encode(), needles)

    def test_host_file_scan_skips_owner_classes_for_launch_json(self):
        path = self.tmp / 'launch.json'
        path.write_bytes(b'{"host_principal": "HOST\\\\user"}')
        literals, patterns = guest.p5_needles(None, None, self.ENV, None, None)
        self.assertEqual(guest.scan_host_file(path, literals, patterns, owner=False), [])
        self.assertTrue(guest.scan_host_file(path, literals, patterns, owner=True))

    def test_collect_script_reads_the_contract_locations(self):
        script = guest.collect_script()
        for root in ('etc', 'home', 'srv/scratch', 'run/cloud-init', 'var/lib/cloud', 'var/log'):
            self.assertIn(f' {root} ', script)
        self.assertIn('/proc/1/environ', script)
        self.assertIn('bash -lc env', script)
        self.assertNotIn('sudo', script)


def make_canaries_in(tmp):
    out = Path(tmp) / 'canary-set'
    guest.make_canaries(out)
    return out


class Canaries(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-canary-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_set_and_fake_home(self):
        out = make_canaries_in(self.tmp)
        data = guest.load_canaries(out)
        home = Path(data['home'])
        for rel in ('.ssh/id_ed25519', '.ssh/config', '.git-credentials', '.aws/credentials',
                    '.gitconfig'):
            self.assertIn(data['needles'][f'home:{rel}'], (home / rel).read_text())
        self.assertIn('SetEnv LC_AIEH_CANARY_SSHCONFIG=', (home / '.ssh/config').read_text())
        self.assertIn('LC_AIEH_CANARY', data['env'])            # sshd's AcceptEnv LC_* tripwire
        values = list(data['needles'].values())
        self.assertEqual(len(set(values)), len(values))
        cores = [re.findall(r'[0-9a-f]{32}', v) for v in values if 'AKIA' not in v]
        self.assertTrue(all(cores))

    def test_summary_has_no_values(self):
        summary = guest.make_canaries(self.tmp / 'second')
        data = guest.load_canaries(self.tmp / 'second')
        text = json.dumps(summary)
        for value in data['needles'].values():
            self.assertNotIn(value, text)

    def test_refusals(self):
        out = make_canaries_in(self.tmp)
        with self.assertRaises(guest.Refused):
            guest.make_canaries(out)                               # never reused
        with self.assertRaises(guest.Refused):
            guest.make_canaries(REPO / 'canaries-must-not-be-here')
        self.assertFalse((REPO / 'canaries-must-not-be-here').exists())
        with self.assertRaises(guest.Refused):
            guest.load_canaries(self.tmp / 'missing')

    def test_apply_plants_environment_and_home(self):
        data = guest.load_canaries(make_canaries_in(self.tmp))
        environ = {'PATH': 'x'}
        planted = guest.apply_canaries(data, environ)
        self.assertEqual(environ['HOME'], data['home'])
        self.assertEqual(environ['GITHUB_TOKEN'], data['env']['GITHUB_TOKEN'])
        self.assertIn('HOME', planted)
        # the QEMU launch environment drops every planted value
        env = guest.scrubbed_env({'qemu_prefix': 'D:/q'}, environ=dict(environ, SYSTEMROOT='C:\\W'))
        self.assertFalse(set(data['env']) & set(env))
        self.assertNotIn('HOME', env)


GIT_TEST_ENV = {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_AUTHOR_NAME': 'fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
                'GIT_COMMITTER_NAME': 'fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid'}


def fixture_repo(path, commits=2):
    env = dict(os.environ, **GIT_TEST_ENV)
    path.mkdir(parents=True)
    run = lambda *a: subprocess.run(['git', '-C', str(path), *a], check=True, env=env,  # noqa: E731
                                    capture_output=True)
    run('init', '-q', '-b', 'main')
    for i in range(commits):
        (path / f'file{i}.txt').write_text(f'synthetic fixture {i}\n', encoding='ascii')
        run('add', f'file{i}.txt')
        run('commit', '-q', '-m', f'fixture {i}')
    run('tag', 'v1')
    return subprocess.run(['git', '-C', str(path), 'rev-parse', 'HEAD'], check=True, env=env,
                          capture_output=True, text=True).stdout.strip()


class Exchange(TempState):
    """exchange push and pull against a fixture repository; the guest side (ssh, sftp) is
    replaced by fakes, so bounds, refusals and verification are exercised offline."""

    def setUp(self):
        super().setUp()
        self.context = self.ctx()
        self.idir = self.context.instance_dir('abc')
        (self.idir / 'ssh').mkdir(parents=True)
        self.repo = self.tmp / 'fixture'
        self.head = fixture_repo(self.repo)
        self.guest_files = {}
        record = {'ports': {'ssh': 1, 'qmp': 2}}
        for target, value in (('running_instance', (self.idir, record)),):
            patcher = mock.patch.object(guest, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(guest, 'guest_file_state', side_effect=self.fake_state)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(guest.Sftp, 'batch', autospec=True, side_effect=self.fake_sftp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_state(self, ssh, path):
        data = self.guest_files.get(path)
        if data is None:
            return 'absent'
        if data == 'symlink':
            return 'symlink'
        return ('file', len(data), hashlib.sha256(data).hexdigest())

    def fake_sftp(self, sftp, commands, work_dir, timeout=600):
        for command in commands:
            verb, src, dst = command.split(' ', 2)
            src, dst = src.strip('"'), dst.strip('"')
            if verb == 'put':
                self.guest_files[dst] = Path(src).read_bytes()
            elif verb == 'rename':
                self.guest_files[dst] = self.guest_files.pop(src)
            elif verb == 'get':
                Path(dst).write_bytes(self.guest_files[src])
        return {'rc': 0, 'commands': commands, 'stderr': ''}

    def push(self, **kw):
        return guest.exchange_push(self.context, 'abc', str(self.repo), kw.pop('ref', 'main'), **kw)

    def test_push_one_branch_bundle(self):
        result = self.push()
        self.assertEqual(result['result'], 'pushed')
        bundle = result['bundle']
        self.assertEqual(bundle['header']['refs'], [[self.head, 'refs/heads/main']])
        self.assertEqual(bundle['header']['prerequisites'], [])
        guest_path = '/home/agent/exchange/' + bundle['name']
        self.assertEqual(hashlib.sha256(self.guest_files[guest_path]).hexdigest(), bundle['sha256'])
        self.assertEqual(result['source']['commits'], 2)
        self.assertTrue(Path(bundle['host_path']).is_file())
        self.assertTrue(guest.inside(bundle['host_path'], self.idir))
        records = list((self.idir / 'records').glob('exchange-push-*.json'))
        self.assertEqual(len(records), 1)

    def test_push_refuses_non_branches(self):
        for ref in ('v1', self.head, 'HEAD~1', 'refs/tags/v1', 'missing'):
            with self.assertRaises(guest.Refused, msg=ref) as cm:
                self.push(ref=ref)
            self.assertEqual(cm.exception.code, 'REFUSED', ref)

    def test_push_bounds(self):
        profile = copy.deepcopy(self.context.profile)
        profile['exchange']['push']['max_commits'] = 1
        self.context.profile = profile
        with self.assertRaises(guest.Refused) as cm:
            self.push()
        self.assertEqual(cm.exception.code, 'BOUNDS')
        profile['exchange']['push']['max_commits'] = 10
        profile['exchange']['push']['max_bytes'] = 10
        with self.assertRaises(guest.Refused) as cm:
            self.push()
        self.assertEqual(cm.exception.code, 'BOUNDS')
        self.assertEqual(list((self.idir / 'exchange' / 'outbound').glob('*.bundle')), [])
        self.assertEqual(self.guest_files, {})

    def test_push_refuses_bad_names_and_overwrites(self):
        for name in ('../x.bundle', 'x/y.bundle', 'X.bundle', 'x.tar', 'x.bundle.partial'):
            with self.assertRaises(guest.Refused, msg=name):
                self.push(bundle_name=name)
        self.guest_files['/home/agent/exchange/fixed.bundle'] = b'guest data'
        with self.assertRaises(guest.Refused):
            self.push(bundle_name='fixed.bundle')
        self.assertEqual(self.guest_files['/home/agent/exchange/fixed.bundle'], b'guest data')

    def test_push_reads_the_repository_only(self):
        before = tree_digest(self.repo / '.git')
        self.push()
        self.assertEqual(tree_digest(self.repo / '.git'), before)

    def test_push_refuses_a_repository_in_the_state_directory(self):
        inner = self.state / 'repo'
        fixture_repo(inner, 1)
        with self.assertRaises(guest.Refused):
            guest.exchange_push(self.context, 'abc', str(inner), 'main')

    def test_round_trip_pull_verifies_the_bundle(self):
        pushed = self.push()
        result = guest.exchange_pull(self.context, 'abc', pushed['bundle']['name'])
        self.assertEqual(result['result'], 'pulled')
        self.assertTrue(result['digest_match'])
        self.assertEqual(result['staged']['sha256'], pushed['bundle']['sha256'])
        self.assertTrue(result['bundle']['verified'])
        self.assertEqual(result['bundle']['refs'], [{'ref': 'refs/heads/main', 'header': self.head,
                                                     'fetched': self.head, 'match': True}])
        self.assertTrue(guest.inside(result['staged']['path'], self.idir))

    def test_pull_evidence_file(self):
        self.guest_files['/home/agent/exchange/receipt.txt'] = b'abc  file\n'
        result = guest.exchange_pull(self.context, 'abc', 'receipt.txt')
        self.assertEqual(result['result'], 'pulled')
        self.assertNotIn('bundle', result)

    def test_pull_refusals(self):
        for name in ('../etc/passwd', 'a/b', '.hidden', 'x.partial', ''):
            with self.assertRaises(guest.Refused, msg=name):
                guest.exchange_pull(self.context, 'abc', name)
        self.guest_files['/home/agent/exchange/link'] = 'symlink'
        with self.assertRaises(guest.Refused):
            guest.exchange_pull(self.context, 'abc', 'link')
        with self.assertRaises(guest.Refused):
            guest.exchange_pull(self.context, 'abc', 'absent.bundle')
        profile = copy.deepcopy(self.context.profile)
        profile['exchange']['pull']['max_bytes'] = 4
        self.context.profile = profile
        self.guest_files['/home/agent/exchange/big.txt'] = b'12345'
        with self.assertRaises(guest.Refused) as cm:
            guest.exchange_pull(self.context, 'abc', 'big.txt')
        self.assertEqual(cm.exception.code, 'BOUNDS')

    def test_pull_never_overwrites(self):
        self.guest_files['/home/agent/exchange/r.txt'] = b'one'
        guest.exchange_pull(self.context, 'abc', 'r.txt')
        with self.assertRaises(guest.Refused):
            guest.exchange_pull(self.context, 'abc', 'r.txt')

    def test_tampered_bundle_does_not_verify(self):
        pushed = self.push()
        path = '/home/agent/exchange/' + pushed['bundle']['name']
        data = bytearray(self.guest_files[path])
        data[-30] ^= 0xff
        self.guest_files['/home/agent/exchange/tampered.bundle'] = bytes(data)
        with self.assertRaises(guest.Refused) as cm:
            guest.exchange_pull(self.context, 'abc', 'tampered.bundle')
        self.assertEqual(cm.exception.code, 'EXCHANGE')
        self.assertFalse(cm.exception.detail['bundle']['verified'])

    def test_incremental_bundle_verifies_against_the_pushed_history(self):
        pushed = self.push()
        env = dict(os.environ, **GIT_TEST_ENV)
        (self.repo / 'file9.txt').write_text('candidate\n', encoding='ascii')
        for args in (('add', 'file9.txt'), ('commit', '-q', '-m', 'candidate')):
            subprocess.run(['git', '-C', str(self.repo), *args], check=True, env=env,
                           capture_output=True)
        inc = self.tmp / 'inc.bundle'
        subprocess.run(['git', '-C', str(self.repo), 'bundle', 'create', '-q', str(inc),
                        f'{self.head}..main'], check=True, env=env, capture_output=True)
        self.guest_files['/home/agent/exchange/candidate.bundle'] = inc.read_bytes()
        result = guest.exchange_pull(self.context, 'abc', 'candidate.bundle')
        self.assertTrue(result['bundle']['verified'])
        self.assertEqual(result['bundle']['header']['prerequisites'], [self.head])
        self.assertEqual(result['bundle']['prerequisite_sources'], [pushed['bundle']['name']])

    def test_bundle_header_parser(self):
        pushed = self.push()
        header = guest.parse_bundle_header(pushed['bundle']['host_path'])
        self.assertIn(header['version'], (2, 3))
        bad = self.tmp / 'bad.bundle'
        for data in (b'not a bundle\n', b'# v2 git bundle\n' + b'x' * 10,
                     b'# v2 git bundle\nzz refs/heads/x\n\n'):
            bad.write_bytes(data)
            with self.assertRaises(guest.Refused):
                guest.parse_bundle_header(bad)
        bad.write_bytes(b'# v2 git bundle\n-' + b'a' * 40 + b' base\n' + b'b' * 40 +
                        b' refs/heads/x\n\nPACK')
        header = guest.parse_bundle_header(bad)
        self.assertEqual(header['prerequisites'], ['a' * 40])

    def test_sftp_argv_uses_profile_options_and_the_instance_key(self):
        (self.idir / 'ssh' / 'id_ed25519').write_text('k')
        (self.idir / 'ssh' / 'known_hosts').write_text('h')
        ssh = guest.Ssh(self.context.profile, self.idir, 2222)
        ssh._checked = True                                        # no ssh -G offline
        argv = guest.Sftp(ssh).argv('batch.txt')
        self.assertTrue(argv[0].lower().endswith('sftp.exe'))
        self.assertEqual(argv[1:3], ['-S', ssh.exe])
        self.assertEqual(argv[3:5], ['-F', 'none'])
        self.assertIn('IdentitiesOnly=yes', argv)
        self.assertIn('IdentityAgent=none', argv)
        self.assertEqual(argv[argv.index('-i') + 1], str(self.idir / 'ssh' / 'id_ed25519'))
        self.assertEqual(argv[-5:], ['-P', '2222', '-b', 'batch.txt', 'agent@127.0.0.1'])
        self.assertNotIn('-p', argv)


# ---------------------------------------------------------------- netprobe (F-03.3.2)

NETPROBE_FILE = PROFILE_DIR / 'validation' / 'netprobe' / 'netprobe.py'
NP_PORTS = {'listener': 40003, 'decoy_tcp': 40004, 'decoy_udp': 40005}


def load_netprobe_module():
    """The guest probe program, imported on the host (its main() never runs here)."""
    spec = importlib.util.spec_from_file_location('aieh_netprobe', NETPROBE_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NP = load_netprobe_module()


def sample_params():
    return guest.netprobe_params(PORTS, NP_PORTS, ['192.0.2.10'], ['2001:db8::10'],
                                 ('192.0.2.80', '2001:db8::80'))


class NetprobeOverlay(unittest.TestCase):
    def test_pin_matches_the_committed_script(self):
        self.assertEqual(hashlib.sha256(NETPROBE_FILE.read_bytes()).hexdigest(),
                         guest.NETPROBE_SCRIPT_SHA256)
        overlay = PROFILE['network']['enforcement_point']['validation_overlay']
        self.assertEqual(overlay['sha256'], guest.NETPROBE_SCRIPT_SHA256)
        self.assertEqual(REPO / overlay['path'], NETPROBE_FILE)
        self.assertEqual(guest.netprobe_script_path(PROFILE_DIR / 'profile.json'), NETPROBE_FILE)
        self.assertEqual(NP.PARAMS_JSON, '{}')
        self.assertEqual(NP.V6_ADDR, guest.NETPROBE_V6_ADDR)
        self.assertEqual(NP.MARKER, guest.NETPROBE_MARKER)

    def test_render_replaces_only_the_parameter_line(self):
        raw = NETPROBE_FILE.read_bytes()
        out = guest.render_netprobe_script(raw, sample_params())
        old, new = raw.decode('ascii').split('\n'), out.decode('ascii').split('\n')
        self.assertEqual(len(old), len(new))
        diff = [(a, b) for a, b in zip(old, new) if a != b]
        self.assertEqual(len(diff), 1)
        self.assertEqual(diff[0][0], guest.NETPROBE_PARAMS_LINE)
        namespace = {}
        exec(diff[0][1], namespace)                              # one assignment of a literal
        self.assertEqual(json.loads(namespace['PARAMS_JSON']), sample_params())
        compile(out, 'aieh-netprobe.py', 'exec')

    def test_render_refuses_a_changed_script(self):
        raw = NETPROBE_FILE.read_bytes()
        with self.assertRaises(guest.Refused) as cm:
            guest.render_netprobe_script(raw + b'# extra\n', sample_params())
        self.assertEqual(cm.exception.code, 'DIGEST_MISMATCH')
        for variant in (raw.replace(b'\n', b'\r\n'),
                        raw + guest.NETPROBE_PARAMS_LINE.encode('ascii') + b'\n',
                        raw.replace(guest.NETPROBE_PARAMS_LINE.encode('ascii'), b'PARAMS_JSON = 1')):
            with mock.patch.object(guest, 'NETPROBE_SCRIPT_SHA256',
                                   hashlib.sha256(variant).hexdigest()):
                with self.assertRaises(guest.Refused):
                    guest.render_netprobe_script(variant, sample_params())

    def test_params_are_literals_only(self):
        good = sample_params()
        mutations = [
            lambda p: p['host_ipv4'].append('192.0.2.1; reboot'),
            lambda p: p['host_ipv6'].append('192.0.2.1'),
            lambda p: p['host_ports'].__setitem__('ssh', 0),
            lambda p: p['host_ports'].__setitem__('qmp', True),
            lambda p: p['guestfwd'].__setitem__('addr', '10.0.2.2'),
            lambda p: p['guestfwd'].__setitem__('addr', '192.0.2.100'),
            lambda p: p.__setitem__('extra', 1),
            lambda p: p.__setitem__('marker', "x'; import os"),
            lambda p: p['public_ipv4_tcp'].append(['1.1.1.1']),
            lambda p: p.__setitem__('debian_ipv4', 'deb.debian.org'),
        ]
        for mutate in mutations:
            params = copy.deepcopy(good)
            mutate(params)
            with self.assertRaises(guest.Refused):
                guest.validate_netprobe_params(params)

    def test_user_data_parts(self):
        import email
        ordinary = (REPO / 'profiles' / 'seed' / 'user-data.tmpl').read_bytes()
        script = guest.render_netprobe_script(NETPROBE_FILE.read_bytes(), sample_params())
        data = guest.netprobe_user_data(ordinary, script)
        message = email.message_from_bytes(data)
        self.assertTrue(message.is_multipart())
        parts = message.get_payload()
        self.assertEqual([p.get_content_type() for p in parts],
                         ['text/cloud-config', 'text/x-shellscript'])
        self.assertEqual([p.get_filename() for p in parts], ['cloud-config.yaml', 'aieh-netprobe.py'])
        self.assertEqual(parts[0].get_payload(decode=True), ordinary)     # byte-identical
        self.assertEqual(parts[1].get_payload(decode=True), script)
        for bad in (ordinary + guest.NETPROBE_BOUNDARY.encode('ascii'), ordinary + b'\r\n',
                    ordinary + '\u00e9'.encode('utf-8')):
            with self.assertRaises(guest.Refused):
                guest.netprobe_user_data(bad, script)


class NetprobeSeed(TempState):
    def test_seed_wraps_only_the_user_data(self):
        idir = self.tmp / 'inst'
        (idir / 'ssh').mkdir(parents=True)
        key = keygen(idir / 'ssh')
        script = guest.render_netprobe_script(NETPROBE_FILE.read_bytes(), sample_params())
        seed = guest.netprobe_seed(PROFILE_DIR / 'profile.json', idir, 'abc',
                                   key.with_suffix('.pub'), script)
        gen = guest.load_seed_generator()
        profile, root = gen.load_profile(str(PROFILE_DIR))
        values = {'agent_ssh_public_key': gen.read_public_key(str(key.with_suffix('.pub'))),
                  'scratch_device': gen.scratch_device(profile),
                  'instance_id': seed['instance_id'], 'instance_name': 'abc'}
        ordinary = gen.render(gen.read_templates(profile, root), values)
        self.assertEqual(seed['validation']['ordinary_user_data_sha256'],
                         hashlib.sha256(ordinary['user-data']).hexdigest())
        for name in ('meta-data', 'network-config'):
            self.assertEqual(seed['rendered_sha256'][name],
                             hashlib.sha256(ordinary[name]).hexdigest(), name)
        self.assertEqual(seed['templates'], {k: v['sha256'] for k, v in
                                             PROFILE['boot_inputs']['seed']['templates'].items()})
        image = (idir / 'seed.iso').read_bytes()
        self.assertEqual(hashlib.sha256(image).hexdigest(), seed['sha256'])
        self.assertIn(guest.netprobe_user_data(ordinary['user-data'], script), image)
        with self.assertRaises(FileExistsError):                  # never overwritten
            guest.netprobe_seed(PROFILE_DIR / 'profile.json', idir, 'abc',
                                key.with_suffix('.pub'), script)


class NetprobeArgv(unittest.TestCase):
    def argv(self):
        return guest.render_argv(PROFILE, guest.resolve_values(PROFILE, 'D:/state', 'abc', PORTS))

    def test_one_guestfwd_appended_to_the_netdev(self):
        argv = self.argv()
        rule = guest.netprobe_guestfwd_rule(40003)
        self.assertEqual(rule, 'tcp:10.0.2.100:7000-tcp:127.0.0.1:40003')
        effective, changes = guest.netprobe_argv(argv, rule)
        diffs = [i for i, (a, b) in enumerate(zip(argv, effective)) if a != b]
        self.assertEqual(len(argv), len(effective))
        self.assertEqual(diffs, [changes[0]['index']])
        self.assertEqual(effective[diffs[0]], argv[diffs[0]] + ',guestfwd=' + rule)
        self.assertEqual(effective[diffs[0] - 1], '-netdev')
        self.assertEqual(guest.forwarding_rules(effective), [rule])
        self.assertEqual(guest.forwarding_rules(argv), [])

    def test_the_profile_and_the_seed_templates_carry_no_validation_input(self):
        self.assertNotIn('guestfwd', json.dumps(PROFILE['launch']['argv']))
        for name in ('user-data.tmpl', 'meta-data.tmpl', 'network-config.yaml'):
            text = (REPO / 'profiles' / 'seed' / name).read_text(encoding='utf-8')
            for word in ('netprobe', 'x-shellscript', 'multipart'):
                self.assertNotIn(word, text, name)

    def test_effective_netdev_passes_the_profile_network_rules(self):
        spec = importlib.util.spec_from_file_location('check_profile', REPO / 'tools' / 'check_profile.py')
        cp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cp)
        effective, changes = guest.netprobe_argv(self.argv(), guest.netprobe_guestfwd_rule(40003))
        report = cp.Report('x')
        cp.check_qemu_net(report, '-netdev', changes[0]['effective'])
        self.assertEqual(report.errors, [])

    def test_refusals(self):
        argv = self.argv()
        rule = guest.netprobe_guestfwd_rule(40003)
        for bad_rule in ('tcp:10.0.2.100:7000-tcp:192.0.2.1:80', 'tcp:10.0.2.100:7000-cmd:nc x 1',
                         'tcp:192.0.2.100:7000-tcp:127.0.0.1:1'):
            with self.assertRaises(guest.Refused, msg=bad_rule):
                guest.netprobe_argv(argv, bad_rule)
        no_netdev = [a for a in argv if not a.startswith('user,') and a != '-netdev']
        with self.assertRaises(guest.Refused):
            guest.netprobe_argv(no_netdev, rule)
        twice, _ = guest.netprobe_argv(argv, rule)
        with self.assertRaises(guest.Refused):
            guest.netprobe_argv(twice, rule)


def validation_record(record, listener_port=40003):
    """A netprobe launch record built from an ordinary one, as create builds it."""
    out = copy.deepcopy(record)
    ports = dict(NP_PORTS, listener=listener_port)
    script = guest.render_netprobe_script(NETPROBE_FILE.read_bytes(), sample_params())
    out['argv'], out['validation'] = guest.netprobe_validation(
        record['argv'], ports, 5000, 'profiles/strong-windows-qemu-whpx/validation/netprobe/netprobe.py',
        script, {'ordinary_user_data_sha256': '0' * 64}, sample_params())
    return out


class ForwardingGuard(LaunchRecord):
    def test_ordinary_record(self):
        self.assertEqual(guest.check_forwarding(self.record), [])
        bad = copy.deepcopy(self.record)
        bad['argv'], _ = guest.netprobe_argv(bad['argv'], guest.netprobe_guestfwd_rule(40003))
        with self.assertRaises(guest.Refused):
            guest.check_forwarding(bad)                       # guestfwd without a validation mode

    def test_validation_record_declares_exactly_its_rule(self):
        rec = validation_record(self.record)
        self.assertEqual(guest.check_forwarding(rec), [rec['validation']['guestfwd']['rule']])
        other = copy.deepcopy(rec)
        other['validation']['guestfwd']['rule'] = guest.netprobe_guestfwd_rule(40009)
        with self.assertRaises(guest.Refused):
            guest.check_forwarding(other)
        twice = copy.deepcopy(rec)
        i = rec['validation']['argv_changes'][0]['index']
        twice['argv'][i] += ',guestfwd=' + guest.netprobe_guestfwd_rule(40009)
        with self.assertRaises(guest.Refused):
            guest.check_forwarding(twice)
        wrong_mode = copy.deepcopy(rec)
        wrong_mode['validation']['mode'] = 'other'
        with self.assertRaises(guest.Refused):
            guest.check_forwarding(wrong_mode)

    def test_launch_refuses_before_starting_anything(self):
        bad = copy.deepcopy(self.record)
        bad['argv'], _ = guest.netprobe_argv(bad['argv'], guest.netprobe_guestfwd_rule(40003))
        with mock.patch.object(guest.subprocess, 'Popen') as popen:
            with self.assertRaises(guest.Refused):
                guest.launch(None, self.tmp, bad, 'start')
        popen.assert_not_called()


class OrdinaryPathRefusesValidation(TempState):
    def test_create_takes_no_overlay(self):
        with self.assertRaises(guest.Refused):
            guest.create(self.ctx(), 'abc', netprobe={'guestfwd': 'x'})
        self.assertFalse((self.state / 'instances' / 'abc').exists())

    def test_cli_create_has_no_netprobe_option(self):
        import contextlib
        err = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
        out = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out),                 self.assertRaises(SystemExit) as cm:
            guest.main(['create', '--profile', str(PROFILE_DIR), '--state-dir', str(self.state),
                        '--name', 'abc', '--netprobe'])
        self.assertEqual(cm.exception.code, 2)
        err.flush()
        self.assertIn('unrecognized arguments: --netprobe', err.buffer.getvalue().decode('utf-8'))
        self.assertFalse((self.state / 'instances').exists())

    def test_start_refuses_a_validation_instance(self):
        idir = self.state / 'instances' / 'abc'
        idir.mkdir(parents=True)
        (idir / 'launch.json').write_text(json.dumps(
            {'schema': guest.LAUNCH_SCHEMA, 'validation': {'mode': 'netprobe'}}), encoding='utf-8')
        with mock.patch.object(guest, 'launch') as launch:
            with self.assertRaises(guest.Refused) as cm:
                guest.start(self.ctx(), 'abc')
        launch.assert_not_called()
        self.assertIn('single boot', str(cm.exception))


class NetprobeListener(unittest.TestCase):
    """The real listener process on 127.0.0.1, driven by the guest program's own client
    functions (no QEMU, no guest, nothing beyond loopback)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-netprobe-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = self.tmp / 'listener.jsonl'
        import sys
        self.proc = subprocess.Popen([sys.executable, '-I', '-B', str(REPO / 'tools' / 'guest.py'),
                                      'netprobe-listen', '--log', str(self.log)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.addCleanup(self.cleanup)
        self.ready = json.loads(self.proc.stdout.readline())

    def cleanup(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(10)
        self.proc.stdout.close()
        if not self.proc.stdin.closed:
            self.proc.stdin.close()

    def stop(self):
        self.proc.stdin.close()
        rc = self.proc.wait(timeout=30)
        return rc, [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()]

    def test_exchange_decoys_and_stop(self):
        out = NP.exchange('127.0.0.1', self.ready['listener'], 'guest')
        self.assertEqual(out['result'], 'exchanged', out)
        self.assertRegex(out['nonce'], r'^[0-9a-f]{32}$')
        decoy = NP.tcp('127.0.0.1', self.ready['decoy_tcp'])
        self.assertEqual((decoy['result'], decoy['banner']), ('connected', 'AIEH-DECOY\n'))
        self.assertEqual(NP.udp_send('127.0.0.1', self.ready['decoy_udp'], 'guest')['result'],
                         'no-reply')
        rc, events = self.stop()
        self.assertEqual(rc, 0)
        self.assertEqual(events[0]['event'], 'ready')
        self.assertEqual(events[0]['bind'], '127.0.0.1')
        self.assertEqual(events[-1]['event'], 'stop')
        exchanges = [e for e in events if e.get('event') == 'exchange']
        self.assertEqual([(e['label'], e['nonce'], e['echoed'], e['matched']) for e in exchanges],
                         [('guest', out['nonce'], out['nonce'], True)])
        self.assertTrue(any(e.get('socket') == 'decoy-tcp' and e.get('event') == 'accept'
                            for e in events))
        datagrams = [e for e in events if e.get('event') == 'datagram']
        self.assertEqual([d['data'] for d in datagrams], ['AIEH-NETPROBE UDP guest\n'])
        for e in events:
            if 'peer' in e:
                self.assertEqual(e['peer'][0], '127.0.0.1')

    def test_one_stream_carries_consecutive_exchanges(self):
        """QEMU's guestfwd chardev is one connection that carries every guest connection."""
        with socket.create_connection(('127.0.0.1', self.ready['listener']), timeout=10) as s:
            nonces = []
            for label in ('guest', 'netns'):
                s.sendall(f'AIEH-NETPROBE HELLO {label}\n'.encode())
                nonce = NP.read_line(s, NP.time.monotonic() + 10).split()[2]
                s.sendall(f'AIEH-NETPROBE ECHO {nonce}\n'.encode())
                self.assertEqual(NP.read_line(s, NP.time.monotonic() + 10), f'AIEH-NETPROBE OK {label}')
                nonces.append(nonce)
            s.sendall(b'AIEH-NETPROBE HELLO guest\n')
            NP.read_line(s, NP.time.monotonic() + 10)
            s.sendall(b'AIEH-NETPROBE ECHO ' + b'0' * 32 + b'\n')      # a wrong echo
            self.assertEqual(NP.read_line(s, NP.time.monotonic() + 10), 'AIEH-NETPROBE BAD')
        rc, events = self.stop()
        self.assertEqual(len(set(nonces)), 2)                           # a fresh nonce each time
        self.assertEqual([(e['label'], e['matched']) for e in events if e.get('event') == 'exchange'],
                         [('guest', True), ('netns', True), ('guest', False)])

    def test_client_results(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            closed = s.getsockname()[1]                                 # bound, not listening
            self.assertEqual(NP.tcp('127.0.0.1', closed)['result'], 'refused')
            self.assertEqual(NP.exchange('127.0.0.1', closed, 'guest')['result'], 'refused')
        self.assertEqual(NP.exchange('127.0.0.1', self.ready['decoy_tcp'], 'guest')['result'],
                         'connected-no-exchange')
        self.stop()


def link_stats(tx):
    return {'out': json.dumps([{'ifname': 'enp0s4', 'stats64': {'tx': {'packets': tx}}}]), 'rc': 0}


def snapshot(default, tx):
    return {'ip_route': {'out': ('default via 10.0.2.2 dev enp0s4 \n' if default else '') +
                         '10.0.2.0/24 dev enp0s4 proto kernel scope link src 10.0.2.15', 'rc': 0},
            'ip6_route': {'out': 'fec0::/64 dev enp0s4 proto kernel metric 256 pref medium\n'
                                 'default via fec0::2 dev enp0s4 metric 1024 pref medium'
                          if default else '', 'rc': 0},
            'link_stats': link_stats(tx)}


DENIED_RESULT = {'tcp': 'timeout', 'tcp-dns': 'timeout', 'udp-dns': 'no-reply', 'udp': 'no-reply',
                 'icmp': 'no-reply', 'resolve': 'not-found'}


def passing_netprobe():
    params = sample_params()

    def probes(scope):
        return [dict(row, result='reply' if row['expect'] == 'info' else DENIED_RESULT[row['kind']])
                for row in NP.probe_table(params, scope)]

    n1, n2 = 'a' * 32, 'b' * 32
    gr = {'uid': 0, 'before': snapshot(False, 10), 'after_setup': snapshot(True, 100),
          'after_probes': snapshot(True, 400), 'after': snapshot(True, 500),
          'guest': {'positive': {'result': 'exchanged', 'nonce': n1, 'target': '10.0.2.100:7000',
                                 'lines': []}, 'probes': probes('guest')},
          'netns': {'configured': True, 'setup': [{'argv': ['ip'], 'rc': 0}],
                    'positive': {'result': 'exchanged', 'nonce': n2, 'target': '10.0.2.100:7000',
                                 'lines': []}, 'probes': probes('netns')}}
    qemu_peer = ['127.0.0.1', 60000]
    log = [{'event': 'ready', 'bind': '127.0.0.1', 'ports': NP_PORTS},
           {'socket': 'decoy-tcp', 'event': 'accept', 'peer': ['127.0.0.1', 50001]},
           {'socket': 'decoy-udp', 'event': 'datagram', 'peer': ['127.0.0.1', 50002], 'bytes': 20},
           {'socket': 'listener', 'event': 'accept', 'peer': qemu_peer},
           {'socket': 'listener', 'event': 'exchange', 'peer': qemu_peer, 'label': 'guest',
            'nonce': n1, 'echoed': n1, 'matched': True},
           {'socket': 'listener', 'event': 'exchange', 'peer': qemu_peer, 'label': 'netns',
            'nonce': n2, 'echoed': n2, 'matched': True},
           {'socket': 'decoy-tcp', 'event': 'accept', 'peer': ['127.0.0.1', 50003]},
           {'socket': 'decoy-udp', 'event': 'datagram', 'peer': ['127.0.0.1', 50004], 'bytes': 19},
           {'event': 'stop'}]
    listener = {
        'pid': 5000, 'ports': dict(NP_PORTS), 'exit': 0, 'killed': False, 'log': log,
        'bindings_before': {
            'tcp_by_pid': [{'LocalAddress': '127.0.0.1', 'LocalPort': 40003, 'State': 'Listen'},
                           {'LocalAddress': '127.0.0.1', 'LocalPort': 40004, 'State': 'Listen'}],
            'udp_by_pid': {'LocalAddress': '127.0.0.1', 'LocalPort': 40005}},   # one, unwrapped
        'bindings_after': {'tcp_by_pid': [], 'udp_by_pid': [], 'tcp_by_port': [], 'udp_by_port': []},
        'selfchecks': [{'phase': 'before', 'tcp_local_port': 50001, 'udp_local_port': 50002},
                       {'phase': 'after', 'tcp_local_port': 50003, 'udp_local_port': 50004}]}
    return {'guest_result': gr, 'listener': listener, 'qemu_pid': 4242,
            'guestfwd_connections': {'tcp_to_listener': [
                {'LocalAddress': '127.0.0.1', 'LocalPort': 60000, 'RemotePort': 40003,
                 'OwningProcess': 4242, 'State': 'Established'}]}}


class NetprobeFixture(Evaluate):
    def setUp(self):
        super().setUp()
        self.vrecord = validation_record(self.record)

    def observation(self):
        obs = passing_observation(self.vrecord)
        obs['qmp']['query-chardev'].append({'label': 'guestfwd.tcp.7000'})
        obs['netprobe'] = passing_netprobe()
        return obs

    def p7(self, obs, profile=PROFILE, record=None):
        props = guest.evaluate(profile, record or self.vrecord, obs)
        return next(p for p in props if p['property'] == 'profiles P7')

    def test_passing_validation_instance(self):
        p7 = self.p7(self.observation())
        self.assertEqual(p7['verdict'], 'PASS', [(c['check'], c['observed']) for c in p7['checks']
                                                  if c['verdict'] != 'PASS'])
        names = [c['check'] for c in p7['checks']]
        for want in ('positive control: guest to the test listener through guestfwd',
                     'decoy host-loopback services: no connection from the guest',
                     'denied: IPv6, with an address and a default route added by guest root',
                     'denied from the container namespace: IPv4, ICMP, DNS, host loopback, LAN, '
                     'allowlist edges'):
            self.assertIn(want, names)
        v = {p['property']: p['verdict'] for p in guest.evaluate(PROFILE, self.vrecord,
                                                                  self.observation())}
        self.assertEqual(v['profiles P6'], 'PASS')                     # the guestfwd chardev

    def assertP7(self, mutate, verdict='FAIL'):
        obs = self.observation()
        mutate(obs)
        self.assertEqual(self.p7(obs)['verdict'], verdict)

    def probe(self, obs, scope, cls, result, nth=0):
        part = obs['netprobe']['guest_result'][scope]
        rows = [p for p in part['probes'] if p['class'] == cls and p['expect'] == 'denied']
        rows[nth]['result'] = result


class NetprobeVerdict(NetprobeFixture):
    """F-03.3.2 negative controls: one violation per sample observation, and P7 must FAIL
    (or, where nothing is shown either way, must not PASS)."""

    def test_public_ipv4_reachable(self):
        self.assertP7(lambda o: self.probe(o, 'guest', 'ipv4-direct', 'connected'))

    def test_icmp_reply(self):
        def mutate(o):
            row = next(p for p in o['netprobe']['guest_result']['guest']['probes']
                       if p['kind'] == 'icmp' and p['class'] == 'ipv4-direct')
            row['result'] = 'reply'
        self.assertP7(mutate)

    def test_dns_reply_or_resolution(self):
        def reply(o):
            next(p for p in o['netprobe']['guest_result']['guest']['probes']
                 if p['kind'] == 'udp-dns')['result'] = 'reply'
        self.assertP7(reply)

        def resolved(o):
            next(p for p in o['netprobe']['guest_result']['guest']['probes']
                 if p['kind'] == 'resolve')['result'] = 'resolved'
        self.assertP7(resolved)

    def test_host_loopback_through_slirp(self):
        for nth in range(5):          # ssh, qmp, decoy_tcp, listener, decoy_udp via 10.0.2.2
            with self.subTest(nth=nth):
                self.assertP7(lambda o: self.probe(o, 'guest', 'host-loopback', 'connected', nth))

    def test_host_lan_reachable(self):
        self.assertP7(lambda o: self.probe(o, 'guest', 'host-lan', 'connected'))

    def test_ipv6_reachable(self):
        self.assertP7(lambda o: self.probe(o, 'guest', 'ipv6', 'connected'))

    def test_allowlist_edge_reachable(self):
        self.assertP7(lambda o: self.probe(o, 'guest', 'allowlist-edge', 'connected', 1))

    def test_namespace_probe_reachable(self):
        self.assertP7(lambda o: self.probe(o, 'netns', 'host-loopback', 'connected'))

    def test_decoy_reached(self):
        self.assertP7(lambda o: o['netprobe']['listener']['log'].append(
            {'socket': 'decoy-tcp', 'event': 'accept', 'peer': ['127.0.0.1', 61000]}))
        self.assertP7(lambda o: o['netprobe']['listener']['log'].append(
            {'socket': 'decoy-udp', 'event': 'datagram', 'peer': ['127.0.0.1', 61001]}))

    def test_positive_control_missing_or_mismatched(self):
        def missing(o):
            o['netprobe']['guest_result']['guest']['positive'] = {'result': 'timeout'}
        self.assertP7(missing)

        def mismatched(o):
            ex = next(e for e in o['netprobe']['listener']['log'] if e.get('event') == 'exchange')
            ex['matched'] = False
        self.assertP7(mismatched)

        def other_nonce(o):
            o['netprobe']['guest_result']['guest']['positive']['nonce'] = 'c' * 32
        self.assertP7(other_nonce)

    def test_namespace_positive_control_failed(self):
        def failed(o):
            o['netprobe']['guest_result']['netns']['positive'] = {'result': 'timeout'}
        self.assertP7(failed)

    def test_listener_not_on_loopback_or_left_running(self):
        self.assertP7(lambda o: o['netprobe']['listener']['bindings_before']['tcp_by_pid'].append(
            {'LocalAddress': '0.0.0.0', 'LocalPort': 40003, 'State': 'Listen'}))
        self.assertP7(lambda o: o['netprobe']['listener']['bindings_after']['tcp_by_port'].append(
            {'LocalAddress': '127.0.0.1', 'LocalPort': 40003, 'State': 'Listen'}))

    def test_listener_connection_not_from_qemu(self):
        self.assertP7(lambda o: o['netprobe']['listener']['log'].append(
            {'socket': 'listener', 'event': 'accept', 'peer': ['127.0.0.1', 62000]}))
        self.assertP7(lambda o: o['netprobe'].__setitem__('qemu_pid', 9999))

    def test_no_default_route(self):
        def no_route(o):
            o['netprobe']['guest_result']['after_setup'] = snapshot(False, 100)
        self.assertP7(no_route)

    def test_effective_argv_not_as_declared(self):
        rec = copy.deepcopy(self.vrecord)
        rec['validation']['argv_changes'][0]['profile'] += ',hostfwd=tcp:127.0.0.1:1-:23'
        self.assertEqual(self.p7(self.observation(), record=rec)['verdict'], 'FAIL')

    def test_not_shown_is_not_a_pass(self):
        self.assertP7(lambda o: self.probe(o, 'guest', 'ipv4-direct', 'unreachable'), 'UNKNOWN')
        self.assertP7(lambda o: o['netprobe']['guest_result'].__setitem__(
            'netns', {'configured': False, 'setup': [{'argv': ['iptables'], 'rc': 4}]}), 'UNKNOWN')
        self.assertP7(lambda o: o.__setitem__('netprobe', None), 'UNKNOWN')

        def no_after_selfcheck(o):                    # the decoys were not shown listening after
            lst = o['netprobe']['listener']
            gone = lst['selfchecks'].pop()
            lst['log'] = [e for e in lst['log'] if (e.get('peer') or [0, 0])[1] not in
                          (gone['tcp_local_port'], gone['udp_local_port'])]
        self.assertP7(no_after_selfcheck, 'UNKNOWN')
        # an unknown peer on a decoy is a FAIL even when a self-check is missing
        self.assertP7(lambda o: o['netprobe']['listener']['selfchecks'].pop())

    def test_guest_error_or_not_root(self):
        self.assertP7(lambda o: o['netprobe']['guest_result'].__setitem__('uid', 1000))
        self.assertP7(lambda o: o['netprobe']['guest_result'].__setitem__('error', 'Traceback'))

    def test_reachability_table(self):
        rows = guest.netprobe_reachability(passing_netprobe())
        self.assertEqual([r['result'] for r in rows if r['class'] == 'allowlisted'],
                         ['exchanged', 'exchanged'])
        self.assertTrue(all(r['verdict'] == 'denied' for r in rows if r['expect'] == 'denied'))
        self.assertEqual({r['scope'] for r in rows}, {'guest', 'netns'})


NETNS_MOUNTS = [('/run/netns', 'tmpfs[/netns]', 'tmpfs'),
                ('/run/netns/aieh-np', 'nsfs[net:[4026532443]]', 'nsfs'),
                ('/run/netns/aieh-np', 'nsfs[net:[4026532443]]', 'nsfs')]
NETNS_IPV6 = ('1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536\n    inet6 ::1/128 scope host noprefixroute\n'
              '2: enp0s4: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500\n'
              '    inet6 fec0::15/64 scope site nodad\n'
              '3: aieh-h@enp0s4: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500\n'
              '    inet6 fe80::a43e:daff:feaf:ffbe/64 scope link proto kernel_ll')


class NetprobeCycleOneRegressions(NetprobeFixture):
    """Defects found by the first real netprobe cycle (f0332-n), fixed forward."""

    def test_time_wait_after_stop_is_not_a_listener_socket(self):
        tw = {'LocalAddress': '127.0.0.1', 'LocalPort': 40004, 'RemoteAddress': '127.0.0.1',
              'RemotePort': 58920, 'State': 'TimeWait', 'OwningProcess': 0}
        self.assertP7(lambda o: o['netprobe']['listener']['bindings_after']['tcp_by_port'].append(tw),
                      'PASS')
        owned = dict(tw, State='Established', OwningProcess=5000)
        self.assertP7(lambda o: o['netprobe']['listener']['bindings_after']['tcp_by_port'].append(
            owned))

    def test_resolver_timeout_is_a_denial(self):
        def timed_out(o):
            for scope in ('guest', 'netns'):
                next(p for p in o['netprobe']['guest_result'][scope]['probes']
                     if p['kind'] == 'resolve')['result'] = 'timeout'
        self.assertP7(timed_out, 'PASS')
        with mock.patch.object(NP, 'run', return_value={'rc': None, 'out': '',
                                                        'err': 'timeout after 40 s'}):
            self.assertEqual(NP.resolve('deb.debian.org')['result'], 'timeout')
        with mock.patch.object(NP, 'run', return_value={'rc': 1, 'out': '', 'err': 'x'}):
            self.assertEqual(NP.resolve('deb.debian.org')['result'], 'error')

    def test_namespace_mounts_and_addresses_of_a_validation_instance(self):
        obs = self.observation()
        obs['guest']['findmnt'] = {'rc': 0, 'out': findmnt_json(RECON_MOUNTS + NETNS_MOUNTS)}
        obs['guest']['ip6_addr'] = {'rc': 0, 'out': NETNS_IPV6}
        v = {p['property']: p['verdict'] for p in guest.evaluate(PROFILE, self.vrecord, obs)}
        self.assertEqual((v['profiles P3'], v['profiles P7']), ('PASS', 'PASS'))
        # other mounts or addresses still fail
        obs['guest']['findmnt'] = {'rc': 0, 'out': findmnt_json(
            RECON_MOUNTS + NETNS_MOUNTS + [('/run/netns/other', 'nsfs[net:[1]]', 'nsfs')])}
        obs['guest']['ip6_addr'] = {'rc': 0, 'out': NETNS_IPV6.replace(
            'scope site nodad\n', 'scope site nodad\n    inet6 2001:db8::5/64 scope global\n')}
        v = {p['property']: p['verdict'] for p in guest.evaluate(PROFILE, self.vrecord, obs)}
        self.assertEqual((v['profiles P3'], v['profiles P7']), ('FAIL', 'FAIL'))

    def test_ordinary_instance_gets_no_namespace_allowance(self):
        obs = passing_observation(self.record)
        obs['guest']['findmnt'] = {'rc': 0, 'out': findmnt_json(RECON_MOUNTS + NETNS_MOUNTS)}
        self.assertEqual(self.verdicts(obs)['profiles P3'], 'FAIL')
        obs = passing_observation(self.record)
        obs['guest']['ip6_addr'] = {'rc': 0, 'out': NETNS_IPV6}
        self.assertEqual(self.verdicts(obs)['profiles P7'], 'FAIL')


class OrdinaryP7(Evaluate):
    def p7(self, profile, obs=None, record=None):
        props = guest.evaluate(profile, record or self.record, obs or passing_observation(self.record))
        return next(p for p in props if p['property'] == 'profiles P7')

    def profile_with(self, status):
        profile = copy.deepcopy(PROFILE)
        profile['network']['enforcement_point'] = {'mechanism': 'x', 'status': status,
                                                   'evidence': 'evidence/x.md'}
        return profile

    def test_enforcement_point_reference(self):
        self.assertEqual(self.p7(self.profile_with('qualified'))['verdict'], 'PASS')
        self.assertEqual(self.p7(self.profile_with('failed'))['verdict'], 'FAIL')
        self.assertEqual(self.p7(self.profile_with('candidate'))['verdict'], 'UNKNOWN')

    def test_ordinary_instance_has_no_guest_forwarding_or_extra_ipv6(self):
        profile = self.profile_with('qualified')
        rec = copy.deepcopy(self.record)
        rec['argv'], _ = guest.netprobe_argv(rec['argv'], guest.netprobe_guestfwd_rule(40003))
        self.assertEqual(self.p7(profile, record=rec)['verdict'], 'FAIL')
        obs = passing_observation(self.record)
        obs['guest']['ip6_addr'] = {'rc': 0, 'out': '2: enp0s4\n    inet6 fec0::15/64 scope site'}
        self.assertEqual(self.p7(profile, obs)['verdict'], 'FAIL')

    def test_ordinary_p6_refuses_a_guestfwd_chardev(self):
        obs = passing_observation(self.record)
        obs['qmp']['query-chardev'].append({'label': 'guestfwd.tcp.7000'})
        self.assertEqual(self.verdicts(obs)['profiles P6'], 'FAIL')


class NetprobeSessionSockets(TempState):
    """NetprobeSession with the real listener process; the PowerShell binding queries are
    replaced by fabricated observations (the binding verdict is binding_problems)."""

    def bindings(self, pid, ports):
        return {'tcp_by_pid': [{'LocalAddress': '127.0.0.1', 'LocalPort': ports['listener'],
                                'State': 'Listen'},
                               {'LocalAddress': '127.0.0.1', 'LocalPort': ports['decoy_tcp'],
                                'State': 'Listen'}],
                'udp_by_pid': [{'LocalAddress': '127.0.0.1', 'LocalPort': ports['decoy_udp']}]}

    def test_start_selfcheck_stop_report(self):
        idir = self.state / 'instances' / 'abc'
        idir.mkdir(parents=True)
        session = guest.NetprobeSession()
        with mock.patch.object(guest, 'listener_bindings', side_effect=self.bindings):
            ports = session.start(idir)
            session.selfcheck('after')
            session.stop()
        report = session.report()
        self.assertEqual(report['exit'], 0)
        self.assertEqual(set(ports), {'listener', 'decoy_tcp', 'decoy_udp'})
        accepts = {e['peer'][1] for e in report['log'] if e.get('socket') == 'decoy-tcp'
                   and e.get('event') == 'accept'}
        datagrams = {e['peer'][1] for e in report['log'] if e.get('event') == 'datagram'}
        self.assertEqual(accepts, {s['tcp_local_port'] for s in report['selfchecks']})
        self.assertEqual(datagrams, {s['udp_local_port'] for s in report['selfchecks']})
        self.assertEqual([s['tcp_banner'] for s in report['selfchecks']], ['AIEH-DECOY'] * 2)

    def test_start_refuses_a_non_loopback_binding(self):
        idir = self.state / 'instances' / 'abc'
        idir.mkdir(parents=True)

        def wide(pid, ports):
            out = self.bindings(pid, ports)
            out['tcp_by_pid'][0]['LocalAddress'] = '0.0.0.0'
            return out
        session = guest.NetprobeSession()
        with mock.patch.object(guest, 'listener_bindings', side_effect=wide):
            with self.assertRaises(guest.Refused) as cm:
                session.start(idir)
        self.assertEqual(cm.exception.code, 'NETPROBE_LISTENER')
        self.assertTrue(session.stopped)
        self.assertIsNotNone(session.proc.poll())                # the listener was stopped

    def test_binding_problems(self):
        good = self.bindings(1, NP_PORTS)
        self.assertEqual(guest.binding_problems(good, NP_PORTS), [])
        extra = copy.deepcopy(good)
        extra['tcp_by_pid'].append({'LocalAddress': '127.0.0.1', 'LocalPort': 5, 'State': 'Listen'})
        udp6 = copy.deepcopy(good)
        udp6['udp_by_pid'] = [{'LocalAddress': '::', 'LocalPort': NP_PORTS['decoy_udp']}]
        for bad in (extra, udp6, {'error': 'x'}, None):
            self.assertTrue(guest.binding_problems(bad, NP_PORTS), bad)


# ---------------------------------------------------------------- F-03.4: P11 over the artifacts


LABELS = {'tier': 'strong', 'provider': 'qemu-whpx', 'nesting': 'none'}


class ArtifactLabels(unittest.TestCase):
    def setUp(self):
        self.idir = Path(tempfile.mkdtemp(prefix='aieh-p11-'))
        self.addCleanup(shutil.rmtree, self.idir, True)
        (self.idir / 'records').mkdir()
        for rel in ('launch.json', 'process.json', 'records/create-1.json', 'records/stop-2.json'):
            (self.idir / rel).write_text(json.dumps({'labels': LABELS, 'x': 1}), encoding='utf-8')
        header = guest.log_header(LABELS, 'create', 'abc')
        (self.idir / 'stderr.log').write_text(
            header + '2026-11-06T00:00:00.000Z qemu: warning: Ignoring request for interrupt '
            'vector 0\n' + guest.log_header(LABELS, 'start', 'abc') + 'WHPX: something\n',
            encoding='utf-8')

    def test_label_problems(self):
        self.assertEqual(guest.label_problems(LABELS, LABELS), [])
        self.assertEqual(guest.label_problems(guest.labels(PROFILE)), [])
        self.assertTrue(guest.label_problems(None))
        self.assertTrue(guest.label_problems({'tier': 'strong', 'provider': 'qemu-whpx'}))
        self.assertTrue(guest.label_problems(dict(LABELS, tier='weak')))
        self.assertTrue(guest.label_problems(dict(LABELS, nesting='maybe')))
        self.assertTrue(guest.label_problems(LABELS, dict(LABELS, provider='incus-vm')))

    def test_stderr_headers_are_not_qemu_lines(self):
        err = guest.stderr_findings(self.idir)
        self.assertTrue(err['first_line_is_header'])
        self.assertEqual([h['operation'] for h in err['headers']], ['create', 'start'])
        self.assertEqual(err['headers'][0]['labels'], LABELS)
        self.assertEqual(err['headers'][0]['schema'], guest.LOG_HEADER_SCHEMA)
        self.assertEqual(len(err['lines']), 2)
        self.assertEqual(err['interrupt_vector_0'], 1)
        self.assertEqual(err['whpx'], ['WHPX: something'])

    def test_every_artifact_is_clean(self):
        arts = guest.artifact_labels(self.idir, LABELS)
        self.assertEqual(sorted(arts), ['launch.json', 'process.json', 'records/create-1.json',
                                        'records/stop-2.json', 'stderr.log#header1',
                                        'stderr.log#header2'])
        self.assertTrue(guest.artifacts_clean(arts))

    def test_missing_labels_and_header(self):
        (self.idir / 'records' / 'exec-3.json').write_text('{"operation": "exec"}', encoding='utf-8')
        (self.idir / 'stderr.log').write_text('qemu output first\n', encoding='utf-8')
        arts = guest.artifact_labels(self.idir, LABELS)
        self.assertFalse(guest.artifacts_clean(arts))
        self.assertEqual(arts['records/exec-3.json']['problems'], ['no labels'])
        self.assertIn('stderr.log', arts)
        self.assertFalse(guest.artifacts_clean({}))

    def test_p11_verdicts(self):
        rec = LaunchRecord('test_record_fields')
        rec.setUp()
        self.addCleanup(rec.doCleanups)
        obs = passing_observation(rec.record)
        prop = lambda o: next(p for p in guest.evaluate(PROFILE, rec.record, o)        # noqa: E731
                              if p['property'] == 'profiles P11')
        self.assertEqual(prop(obs)['verdict'], 'PASS')
        obs['artifacts'] = guest.artifact_labels(self.idir, LABELS)
        self.assertEqual(prop(obs)['verdict'], 'PASS')
        obs['artifacts']['records/x.json'] = {'labels': None, 'problems': ['no labels']}
        self.assertEqual(prop(obs)['verdict'], 'FAIL')
        del obs['artifacts']
        self.assertEqual(prop(obs)['verdict'], 'UNKNOWN')

    def test_operation_results_carry_labels(self):
        with mock.patch.object(guest, 'destroy', return_value={'result': 'absent'}), \
                mock.patch.object(guest, 'create', return_value={'result': 'ready'}):
            ctx = mock.Mock(profile=PROFILE)
            self.assertEqual(guest.recreate(ctx, 'abc')['labels'], LABELS)

    def test_launch_writes_the_header_first(self):
        source = Path(guest.__file__).read_text(encoding='utf-8')
        body = source[source.index('def launch(ctx'):source.index('def wait_ready(')]
        self.assertLess(body.index('log_header('), body.index('subprocess.Popen('))


# ---------------------------------------------------------------- F-03.4: XSAVE detector


SERIAL_OK = ('[    0.000000] Linux version 6.12.115-cloud-amd64\n'
             "[    0.827496] x86/fpu: Supporting XSAVE feature 0x001: 'x87 floating point registers'\n"
             "[    0.841900] x86/fpu: Enabled xstate features 0x8e7, context size is 2440 bytes, "
             "using 'compacted' format.\n")
MISORDERED = '[    0.771086] x86/fpu: misordered xstate at 1408\n'
CONSISTENCY = '[    0.771086] XSAVE consistency problem: size 832 != kernel_size 576\n'
DISABLED = '[    0.771099] x86/fpu: XSAVE disabled\n'


class XsaveDetector(unittest.TestCase):
    def verdict(self, serial, dmesg=None):
        return guest.xsave_findings({'serial': serial, 'dmesg': dmesg})

    def test_clean_boot_passes(self):
        out = self.verdict(SERIAL_OK)
        self.assertEqual(out['verdict'], 'PASS')
        self.assertEqual(out['labels'], [])
        self.assertIn("'compacted' format", out['xstate_enabled'][0]['line'])
        self.assertEqual(out['sources'], {'serial': 'kernel messages', 'dmesg': 'unavailable'})

    def test_misordered_is_a_limitation(self):
        out = self.verdict(MISORDERED + SERIAL_OK)
        self.assertEqual(out['verdict'], 'LIMITATION')
        self.assertEqual(out['labels'], ['misordered-xstate'])

    def test_consistency_problem_and_disabled_fail(self):
        for text, label in ((CONSISTENCY, 'xsave-consistency-problem'), (DISABLED, 'xsave-disabled')):
            out = self.verdict(MISORDERED + text + SERIAL_OK)
            self.assertEqual(out['verdict'], 'FAIL', label)
            self.assertIn(label, out['labels'])
        self.assertEqual(self.verdict(SERIAL_OK, CONSISTENCY)['verdict'], 'FAIL')    # guest side

    def test_no_kernel_messages_is_unknown(self):
        self.assertEqual(self.verdict(None)['verdict'], 'UNKNOWN')
        self.assertEqual(self.verdict('cloud-init only\n')['verdict'], 'UNKNOWN')

    def test_guest_kernel_log(self):
        self.assertIsNone(guest.guest_kernel_log('dmesg unreadable\ndmesg_restrict=1'))
        self.assertIsNone(guest.guest_kernel_log(''))
        self.assertEqual(guest.guest_kernel_log('dmesg readable\n' + MISORDERED + 'dmesg_restrict=0'),
                         MISORDERED.rstrip('\n'))

    def test_probes_listed(self):
        probes = dict(guest.guest_probes(PORTS, [], None))
        self.assertIn('dmesg', probes['kernel_log'])
        self.assertIn('^flags', probes['cpu_flags'])


# ---------------------------------------------------------------- F-03.4: host XSAVES (preflight)


def fake_whv(mask, vendor=0, hr=0):
    def get(code):
        value = {guest.WHV_CAP_HYPERVISOR_PRESENT: 1, guest.WHV_CAP_PROCESSOR_VENDOR: vendor,
                 guest.WHV_CAP_PROCESSOR_XSAVE_FEATURES: mask}[code]
        return hr, value.to_bytes(8, 'little')
    return get


class HostXsaves(unittest.TestCase):
    def test_qualification_host_mask(self):
        info = guest.whpx_xsave_features(fake_whv(0x41ffffdf))       # observed (F-03.4)
        self.assertTrue(info['xsaves'])
        self.assertEqual(info['vendor'], 'AMD')
        self.assertIn('xsavec', info['features'])
        self.assertIn('avx512_vp2intersect', info['features'])
        self.assertNotIn('mpx', info['features'])
        self.assertEqual(guest.xsaves_check(info)[0], 'ok')

    def test_host_without_xsaves_fails(self):
        info = guest.whpx_xsave_features(fake_whv(0x41ffffdf & ~(1 << 12), vendor=1))
        self.assertFalse(info['xsaves'])
        status, detail, act = guest.xsaves_check(info)
        self.assertEqual(status, 'fail')
        self.assertIn('-cpu max', detail)
        self.assertTrue(act)

    def test_query_failure_is_disclosed_unknown(self):
        info = guest.whpx_xsave_features(fake_whv(0, hr=0x80070057))
        self.assertIsNone(info['xsaves'])
        status, detail, act = guest.xsaves_check(info)
        self.assertEqual((status, act), ('unknown', None))
        self.assertIn('disclosed', detail)

        def broken(code):
            raise OSError('no WinHvPlatform.dll')
        self.assertIsNone(guest.whpx_xsave_features(broken)['xsaves'])

    def test_availability(self):
        ok = {'status': 'ok'}
        self.assertTrue(guest.preflight_available([ok, {'status': 'unknown'}]))
        self.assertFalse(guest.preflight_available([ok, {'status': 'fail'}]))


# ---------------------------------------------------------------- F-03.4: inspect comparison


def identity_record(base_record, token, pid=4242, port_shift=0, memtotal_kb=None):
    """An ordinary inspect record whose identity (machine-id, host keys, instance id, seed,
    SSH key) derives from token; everything else is the passing observation."""
    record = copy.deepcopy(base_record)
    digest = lambda s: hashlib.sha256(f'{token}:{s}'.encode()).hexdigest()        # noqa: E731
    record['instance']['instance_id'] = f'abc-{digest("id")[:8]}-0000-4000-8000-000000000000'
    record['inputs']['seed']['sha256'] = digest('seed')
    obs = passing_observation(record)
    key = ed25519_b64(hashlib.sha256(token.encode()).digest())
    obs['guest']['machine_id']['out'] = digest('mid')[:32]
    obs['guest']['host_keys']['out'] = f'256 {fingerprint(key)} root@abc (ED25519)'
    obs['known_hosts_fingerprints'] = [fingerprint(key)]
    obs['input_digests']['seed']['sha256'] = digest('seed')
    obs['input_digests']['ssh_public_key'] = {'match': True, 'sha256': digest('pub')}
    obs['guest']['cpu_flags'] = {'rc': 0, 'out': 'flags : fpu xsave xsaves avx512f'}
    if memtotal_kb is not None:
        obs['guest']['meminfo']['out'] = f'MemTotal:       {memtotal_kb} kB'
    if port_shift:
        for c in obs['host']['bindings']['tcp_by_pid']:
            c['LocalPort'] += port_shift
        record['ports'] = {k: (v + port_shift if isinstance(v, int) else v)
                           for k, v in record['ports'].items()}
        obs['host']['non_loopback'] = {f'192.0.2.10:{40001 + port_shift}': 'refused',
                                       f'192.0.2.10:{40002 + port_shift}': 'refused'}
    props = guest.evaluate(PROFILE, record, obs)
    return {'schema': guest.INSPECT_SCHEMA, 'labels': dict(record['labels']),
            'instance_id': record['instance']['instance_id'], 'pid': pid,
            'launch_record_sha256': digest('launch'), 'inspected_at': f'{token}-time',
            'seconds': 1.0, 'verdicts': {p['property']: p['verdict'] for p in props},
            'compatibility': {'verdict': 'LIMITATION', 'xsave': {'labels': ['misordered-xstate']}},
            'properties': props, 'observations': obs}


class CompareInspect(LaunchRecord):
    def test_every_ordinary_check_is_classified(self):
        rec = identity_record(self.record, 'one')
        keys = {(p['property'], c['check']) for p in rec['properties'] for c in p['checks']}
        self.assertEqual(keys - set(guest.CHECK_CLASSES), set())
        self.assertEqual(set(guest.CHECK_CLASSES) - keys, set())   # no stale entry either
        for klass, norm in guest.CHECK_CLASSES.values():
            self.assertIn(klass, (guest.STABLE, guest.PER_INSTANCE, guest.VOLATILE))
            self.assertTrue(norm is None or norm in guest.NORMALIZERS)

    def test_start_keeps_identity(self):
        a = identity_record(self.record, 'one', pid=1)
        b = identity_record(self.record, 'one', pid=2)
        out = guest.compare_inspect(PROFILE, a, b, 'start')
        self.assertEqual(out['result'], 'PASS', out['not_ok'])
        self.assertEqual(guest.compare_inspect(PROFILE, a, b, 'recreate')['result'], 'FAIL')

    def test_recreate_changes_identity_only(self):
        a = identity_record(self.record, 'one')
        c = identity_record(self.record, 'two', pid=99, port_shift=7)
        out = guest.compare_inspect(PROFILE, a, c, 'recreate')
        self.assertEqual(out['result'], 'PASS', out['not_ok'])
        per = {f['field'] for f in out['fields'] if f['class'] == guest.PER_INSTANCE}
        self.assertEqual(per, {'profiles P8 / machine-id', 'profiles P8 / cloud-init instance id',
                               'profiles P8 / host keys', 'profiles P9 / seed digest recorded',
                               'instance id', 'launch record sha256', 'ssh public key sha256',
                               'seed sha256'})
        self.assertEqual(guest.compare_inspect(PROFILE, a, c, 'start')['result'], 'FAIL')

    def test_a_stable_difference_fails(self):
        a = identity_record(self.record, 'one')
        c = identity_record(self.record, 'two')
        c['observations']['guest']['cpu_flags']['out'] = 'flags : fpu xsave'
        out = guest.compare_inspect(PROFILE, a, c, 'recreate')
        self.assertEqual(out['not_ok'], ['guest cpu flags'])
        d = identity_record(self.record, 'two')
        for p in d['properties']:
            for chk in p['checks']:
                if chk['check'] == 'guest kernel':
                    chk['observed'] = 'Linux 6.12.999-cloud-amd64'    # verdict still PASS
        out = guest.compare_inspect(PROFILE, a, d, 'recreate')
        self.assertEqual(out['not_ok'], ['profiles P1 / guest kernel'])

    def test_memtotal_varies_within_its_band_only(self):
        """Observed in F-03.4: MemTotal 16382796 kB, then 16382792 kB after recreate."""
        a = identity_record(self.record, 'one', memtotal_kb=16382796)
        for kb, expected in ((16382792, 'PASS'), (1000000, 'FAIL')):
            c = identity_record(self.record, 'two', memtotal_kb=kb)
            self.assertEqual(guest.compare_inspect(PROFILE, a, c, 'recreate')['result'],
                             expected, kb)

    def test_volatile_and_normalised_differences_pass(self):
        a = identity_record(self.record, 'one')
        c = identity_record(self.record, 'two')
        for p in c['properties']:
            for chk in p['checks']:
                if chk['check'] == 'collection':
                    chk['observed'] = dict(chk['observed'], bytes=123456, members=999)
                if chk['check'] == 'mount table file systems':
                    chk['observed'] = sorted(chk['observed'] + ['binfmt_misc'])
                if chk['check'] == 'QMP from the guest':
                    chk['observed'] = {k: 1 if v == 124 else 124 for k, v in chk['observed'].items()}
        self.assertEqual(guest.compare_inspect(PROFILE, a, c, 'recreate')['result'], 'PASS')

    def test_verdict_change_and_unclassified_check_fail(self):
        a = identity_record(self.record, 'one')
        c = identity_record(self.record, 'two')
        c['properties'][0]['checks'][0]['verdict'] = 'FAIL'
        self.assertIn('profiles P1 / accelerator',
                      guest.compare_inspect(PROFILE, a, c, 'recreate')['not_ok'])
        d = identity_record(self.record, 'two')
        d['properties'][0]['checks'].append(guest.check('new', 1, 1, 'x', True))
        out = guest.compare_inspect(PROFILE, a, d, 'recreate')
        self.assertEqual(out['not_ok'], ['profiles P1 / new'])
        with self.assertRaises(ValueError):
            guest.compare_inspect(PROFILE, a, d, 'other')


# ---------------------------------------------------------------- F-03.4: inventory


def fake_state_shared(state):
    """The profile's image and provider files at their layout paths in a temp state."""
    values = guest.resolve_values(PROFILE, state)
    paths = [values['input:image'], values['input:firmware']] + \
        [e['path'] for e in guest.binaries(PROFILE, values).values()] + \
        [values['qemu_prefix'] + '/ucrt64/share/doc/readme.txt']
    for path in paths:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(path.encode())


def sentinel_tree(root):
    (root / 'nested' / 'deeper').mkdir(parents=True)
    (root / 'a.txt').write_bytes(b'sentinel a\n')
    (root / 'nested' / 'b.bin').write_bytes(bytes(range(256)))
    (root / 'nested' / 'deeper' / 'c.txt').write_bytes(b'sentinel c\n')
    ro = root / 'read-only.txt'
    ro.write_bytes(b'read only\n')
    os.chmod(ro, stat.S_IREAD)
    return root


def clear_read_only(root):
    for dirpath, _, files in os.walk(root):
        for f in files:
            os.chmod(os.path.join(dirpath, f), stat.S_IWRITE | stat.S_IREAD)


class Inventory(TempState):
    def setUp(self):
        super().setUp()
        fake_state_shared(self.state)
        self.durable = sentinel_tree(self.tmp / 'durable')
        self.addCleanup(clear_read_only, self.tmp)

    def populate(self, names=('aa', 'bb')):
        for name in names:
            idir = self.state / 'instances' / name
            (idir / 'ssh').mkdir(parents=True)
            (idir / 'root.qcow2').write_bytes(name.encode() * 1000)
            (idir / 'launch.json').write_text('{}')
        (self.state / 'instances' / 'sentinel_not.an-instance').mkdir()
        (self.state / 'instances' / 'sentinel_not.an-instance' / 'keep.txt').write_text('keep')

    def test_tree_inventory_records_content_mode_and_links(self):
        inv = guest.tree_inventory(self.durable)
        self.assertEqual(sorted(inv), ['.', 'a.txt', 'nested', 'nested/b.bin', 'nested/deeper',
                                       'nested/deeper/c.txt', 'read-only.txt'])
        self.assertEqual(inv['a.txt']['sha256'], hashlib.sha256(b'sentinel a\n').hexdigest())
        self.assertFalse(inv['read-only.txt']['mode'] & stat.S_IWRITE)
        vol = guest.tree_inventory(self.durable, volatile=('a.txt',))
        self.assertEqual(vol['a.txt'], {'type': 'file', 'volatile': 'written by the running QEMU'})
        self.assertIn('sha256', vol['nested/deeper/c.txt'])          # only top-level names

    def test_diff_detects_each_kind_of_change(self):
        before = guest.inventory(self.ctx(), 'aa', [self.durable])
        self.assertEqual(guest.diff_inventory(before, guest.inventory(self.ctx(), 'aa', [self.durable])), [])
        (self.durable / 'nested' / 'b.bin').write_bytes(b'changed')
        os.chmod(self.durable / 'read-only.txt', stat.S_IWRITE | stat.S_IREAD)
        (self.durable / 'new.txt').write_text('x')
        after = guest.inventory(self.ctx(), 'aa', [self.durable])
        paths = {d['path'] for d in guest.diff_inventory(before, after)}
        root = guest.posix(self.durable)
        self.assertIn(f'durable_roots/{root}/nested/b.bin/sha256', paths)
        self.assertIn(f'durable_roots/{root}/read-only.txt/mode', paths)
        self.assertIn(f'durable_roots/{root}/new.txt', paths)

    def test_state_shared_and_provider_listing(self):
        before = guest.state_inventory(self.ctx())
        self.assertEqual(before['provider']['files'], 4)
        self.assertEqual(set(before['provider']['binaries']), {'qemu-system-x86_64', 'qemu-img'})
        doc = Path(guest.resolve_values(PROFILE, self.state)['qemu_prefix']) / 'ucrt64' / 'extra.dll'
        doc.write_bytes(b'x')
        after = guest.state_inventory(self.ctx())
        self.assertNotEqual(before['provider']['listing_sha256'], after['provider']['listing_sha256'])

    def test_destroy_leaves_every_other_source_unchanged(self):
        self.populate()
        roots = [self.durable]
        before = guest.inventory(self.ctx(), 'aa', roots)
        self.assertEqual(sorted(before['instances']), ['bb', 'sentinel_not.an-instance'])
        self.assertEqual(before['instances']['bb']['state'], {'instance': False})   # '{}' is no record
        self.assertEqual(guest.destroy(self.ctx(), 'aa')['result'], 'destroyed')
        self.assertEqual(guest.diff_inventory(before, guest.inventory(self.ctx(), 'aa', roots)), [])
        # the same inventory sees a destroy that reaches a sibling
        (self.state / 'instances' / 'bb' / 'root.qcow2').unlink()
        diff = guest.diff_inventory(before, guest.inventory(self.ctx(), 'aa', roots))
        self.assertEqual([d['path'] for d in diff],
                         ['instances/bb/tree/./mtime_ns', 'instances/bb/tree/root.qcow2'])

    def test_running_sibling_files_are_volatile(self):
        self.populate(('bb',))
        idir = self.state / 'instances' / 'bb'
        (idir / 'serial.log').write_text('boot')
        running = {'instance': True, 'running': True, 'pid': 7, 'qmp_status': 'running',
                   'qmp_error': None}
        with mock.patch.object(guest, 'sibling_state', return_value=running):
            before = guest.instances_inventory(self.ctx(), 'aa')
            (idir / 'root.qcow2').write_bytes(b'guest wrote')
            (idir / 'serial.log').write_text('boot and more console')
            after = guest.instances_inventory(self.ctx(), 'aa')
            self.assertEqual(guest.diff_inventory(before, after), [])
            (idir / 'launch.json').write_text('{"changed": 1}')          # not volatile
            changed = guest.instances_inventory(self.ctx(), 'aa')
        self.assertTrue(any(d['path'].startswith('bb/tree/launch.json')
                            for d in guest.diff_inventory(before, changed)))
        stopped = guest.instances_inventory(self.ctx(), 'aa')          # stopped: hashed
        self.assertIn('sha256', stopped['bb']['tree']['root.qcow2'])

    def test_repository_inventory(self):
        repo = self.tmp / 'repo'
        head = fixture_repo(repo)
        inv = guest.repo_inventory(repo)
        self.assertEqual((inv['head'], inv['status_porcelain_v2'], inv['rc']), (head, [], [0, 0, 0]))
        self.assertEqual(inv['ls_files_count'], 2)
        (repo / 'file0.txt').write_text('edited\n', encoding='ascii')
        self.assertNotEqual(guest.repo_inventory(repo)['status_porcelain_v2'], [])


# ---------------------------------------------------------------- F-03.4: smoke orchestration


class Smoke(TempState):
    """The smoke sequence with the guest operations faked and destroy, recreate and the
    inventories real (they act on the temporary state directory only)."""

    def setUp(self):
        super().setUp()
        fake_state_shared(self.state)
        self.durable = sentinel_tree(self.tmp / 'durable')
        self.addCleanup(clear_read_only, self.tmp)
        self.canaries = make_canaries_in(self.tmp)
        rec = LaunchRecord('test_record_fields')
        rec.setUp()
        self.addCleanup(rec.doCleanups)
        self.base = rec.record
        self.token = None
        self.calls = []
        self.inspect_hook = None

    def fake_create(self, ctx, name, ready_timeout=600, canaries=None):
        self.calls.append(('create', canaries is not None))
        idir = ctx.instance_dir(name)
        idir.mkdir(parents=True)
        (idir / 'launch.json').write_text('{}')
        self.token = secrets_token()
        return {'operation': 'create', 'result': 'ready', 'instance_id': self.token}

    def fake_inspect(self, ctx, name, canaries=None):
        self.calls.append(('inspect', canaries is not None))
        record = identity_record(self.base, self.token, pid=len(self.calls))
        if self.inspect_hook:
            self.inspect_hook(record)
        return record

    def fake_stop(self, ctx, name, force=False):
        self.calls.append(('stop', force))
        return {'result': 'stopped', 'phases': [
            {'exited_after': 'quit' if force else 'system_powerdown', 'seconds': 1.0}]}

    def fake_start(self, ctx, name, ready_timeout=600):
        self.calls.append(('start',))
        return {'result': 'ready'}

    def smoke(self, **kw):
        avail = {'result': 'available', 'checks': [{'check': 'host-xsaves', 'status': 'ok',
                                                    'detail': 'XSAVES'}]}
        with mock.patch.object(guest, 'preflight', return_value=avail), \
                mock.patch.object(guest, 'create', self.fake_create), \
                mock.patch.object(guest, 'inspect', self.fake_inspect), \
                mock.patch.object(guest, 'stop', self.fake_stop), \
                mock.patch.object(guest, 'start', self.fake_start):
            return guest.smoke(self.ctx(), 'abc', str(self.canaries), [str(self.durable)], **kw)

    def test_pass_sequence_and_record(self):
        out_file = self.tmp / 'smoke.json'
        result = self.smoke(out_path=str(out_file))
        self.assertEqual(result['result'], 'PASS', result['failed_steps'])
        self.assertEqual(result['p10']['verdict'], 'PASS')
        self.assertEqual([s['step'] for s in result['steps']], [
            'preflight', 'inventory before create', 'create', 'inspect A (after create)',
            'stop (graceful)', 'start', 'inspect B (after start)', 'compare A-B (start)',
            'stop (forced)', 'inventory before recreate', 'recreate', 'inventory after recreate',
            'inspect C (after recreate)', 'compare A-C (recreate)', 'destroy', 'destroy (absent)',
            'inventory after destroy'])
        self.assertEqual(self.calls, [('create', True), ('inspect', True), ('stop', False),
                                      ('start',), ('inspect', True), ('stop', True),
                                      ('create', True), ('inspect', True)])
        self.assertFalse((self.state / 'instances' / 'abc').exists())
        self.assertEqual(set(result['inventory_diffs']), {
            'before create -> before recreate', 'before recreate -> after recreate',
            'after recreate -> after destroy', 'before create -> after destroy'})
        self.assertFalse(any(result['inventory_diffs'].values()))
        saved = json.loads(out_file.read_text(encoding='utf-8'))
        self.assertEqual(saved['schema'], guest.SMOKE_SCHEMA)
        self.assertEqual(guest.label_problems(saved['labels'], LABELS), [])
        self.assertEqual(saved['result'], 'PASS')

    def test_a_failed_inspect_stops_and_cleans_up(self):
        def hook(record):
            record['verdicts']['profiles P6'] = 'FAIL'
        self.inspect_hook = hook
        result = self.smoke()
        self.assertEqual(result['result'], 'FAIL')
        self.assertEqual(result['failed_steps'], ['inspect A (after create)'])
        self.assertIn({'step': 'stop (graceful)', 'skipped': 'an earlier step failed'}, result['steps'])
        self.assertEqual(result['steps'][-2], {'step': 'cleanup destroy', 'result': 'destroyed'})
        self.assertEqual(result['steps'][-1]['step'], 'inventory after destroy')
        self.assertFalse((self.state / 'instances' / 'abc').exists())

    def test_xsave_fail_fails_the_inspect_step(self):
        def hook(record):
            record['compatibility'] = {'verdict': 'FAIL', 'xsave': {'labels': ['xsave-disabled']}}
        self.inspect_hook = hook
        self.assertEqual(self.smoke()['failed_steps'], ['inspect A (after create)'])

    def test_a_touched_durable_root_fails(self):
        real_destroy = guest.destroy

        def careless_destroy(ctx, name):
            (self.durable / 'a.txt').write_bytes(b'overwritten')
            return real_destroy(ctx, name)
        with mock.patch.object(guest, 'destroy', careless_destroy):
            result = self.smoke()
        self.assertEqual(result['result'], 'FAIL')
        self.assertIn('inventory comparison', result['failed_steps'])
        self.assertEqual(result['p10']['verdict'], 'FAIL')
        by_check = {c['check']: c['verdict'] for c in result['p10']['checks']}
        self.assertEqual(by_check['Owner data roots untouched'], 'FAIL')

    def test_refusals(self):
        ctx = self.ctx()
        with self.assertRaises(guest.Refused):
            guest.smoke(ctx, 'abc', str(self.canaries), [])
        with self.assertRaises(guest.Refused):
            guest.smoke(ctx, 'abc', str(self.canaries), [str(self.tmp / 'missing')])
        with self.assertRaises(guest.Refused):     # overlaps the instance directory
            guest.smoke(ctx, 'abc', str(self.canaries), [str(self.state)])
        with self.assertRaises(guest.Refused):     # the record never goes into the checkout
            guest.smoke(ctx, 'abc', str(self.canaries), [str(self.durable)],
                        out_path=str(REPO / 'smoke.json'))
        (self.state / 'instances' / 'abc').mkdir(parents=True)
        with self.assertRaises(guest.Refused):     # a fresh instance name only
            guest.smoke(ctx, 'abc', str(self.canaries), [str(self.durable)])

    def test_cli(self):
        with mock.patch.object(guest, 'smoke', return_value={'operation': 'smoke', 'result': 'FAIL'}) as m:
            rc = guest.main(['smoke', '--profile', str(PROFILE_DIR), '--state-dir', str(self.state),
                             '--name', 'abc', '--canaries', str(self.canaries), '--durable', 'X',
                             '--durable', 'Y'])
        self.assertEqual(rc, 1)
        self.assertEqual(m.call_args.args[3], ['X', 'Y'])


def secrets_token():
    return os.urandom(8).hex()


if __name__ == '__main__':
    unittest.main()
