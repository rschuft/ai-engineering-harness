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
    }


class Evaluate(LaunchRecord):
    def verdicts(self, obs):
        return {p['property']: p['verdict'] for p in guest.evaluate(PROFILE, self.record, obs)}

    def test_passing_observation(self):
        v = self.verdicts(passing_observation(self.record))
        for pid in ('P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P8', 'P9', 'P11', 'P12'):
            self.assertEqual(v[f'profiles {pid}'], 'PASS', pid)
        # owned by later leaves, or (P7) no allowlisted endpoint to positively control yet
        for pid in ('P7', 'P10'):
            self.assertEqual(v[f'profiles {pid}'], 'UNKNOWN', pid)

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


if __name__ == '__main__':
    unittest.main()
