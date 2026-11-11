"""Tests for the containment observation of a conversation container (plan leaf S-03.3, slice 1), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -v

``conversation_containment.py`` collects a process inventory inside a conversation container and from the guest
root, and judges both against the admitted caps and the profile's job confinement, with the before/after sets of
containers and conversations. Shown here, over an in-memory /proc and cgroup tree shaped as the pinned image's
processes are expected to be (the inner server, the Claude Code adapter, its CLI and a shell it started, and the
collector's own chain through the bash route):

* the parsers (``stat`` with spaces and parentheses in the command name, ``status``, cgroup v2, the argument
  summary that keeps no argument value but a path, the TCP listener tables in IPv4 and IPv6);
* a passing container view, host view and set comparison; and, as negative controls, each one fact changed at a
  time: every check fails on its own fact (an adapter missing or elsewhere, an orphan, an entered process, a
  capability, no_new_privs, seccomp, a user, a cgroup, an npx start, an ambiguous or missing inner server, a lost
  parent, the limits, a host-side cgroup or executable, an escaped child, a new container, a new outer
  conversation, an inner conversation of another parent);
* the shape checks, which refuse a malformed snapshot rather than judging it, and the command line.

Every value is synthetic. No guest, container, process launch, socket or network.
"""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('aieh_conversation_containment',
                                               HERE.parent / 'conversation_containment.py')
CC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CC)

UID, GID = 999, 989
CAP0 = '0000000000000000'
EXPECTED_LIMITS = CC.expected_limits('4g', 2.0, 512)
CGROUP_LIMITS = {'memory.max': '4294967296', 'cpu.max': '200000 100000', 'pids.max': '512'}
DOCKER_SCOPE = '/system.slice/docker-0123abcd.scope'
CONTAINER_NS, HOST_NS = 'pid:[4026532999]', 'pid:[4026531836]'
CLI = '/acp-node/lib/node_modules/@agentclientprotocol/claude-agent-acp/node_modules/@anthropic-ai/' \
      'claude-agent-sdk-linux-x64/claude'


def expected(provider='claude-code', **over):
    out = {'uid': UID, 'gid': GID, 'capabilities': CAP0, 'no_new_privs': '1', 'seccomp': '2',
           'limits': EXPECTED_LIMITS, 'provider': provider}
    out.update(over)
    return out


class FakeFs:
    """An in-memory file system: files (bytes) and links (targets); directories are implied by paths."""

    def __init__(self):
        self.files, self.links, self.denied = {}, {}, set()

    def _names(self, path):
        prefix = path.rstrip('/') + '/'
        names = {p[len(prefix):].split('/', 1)[0] for p in list(self.files) + list(self.links)
                 if p.startswith(prefix)}
        if not names:
            raise FileNotFoundError(path)
        return names

    def listdir(self, path):
        if path in self.denied:
            raise PermissionError(path)
        return sorted(self._names(path))

    def read_bytes(self, path):
        if path in self.denied:
            raise PermissionError(path)
        try:
            return self.files[path]
        except KeyError:
            raise FileNotFoundError(path) from None

    def readlink(self, path):
        if path in self.denied:
            raise PermissionError(path)
        try:
            return self.links[path]
        except KeyError:
            raise FileNotFoundError(path) from None


def status_text(uid=UID, gid=GID, cap=CAP0, nnp='1', seccomp='2', nspid=None):
    lines = ['Name:\tx', f'Uid:\t{uid}\t{uid}\t{uid}\t{uid}', f'Gid:\t{gid}\t{gid}\t{gid}\t{gid}',
             f'Groups:\t{gid} ', f'CapInh:\t{cap}', f'CapPrm:\t{cap}', f'CapEff:\t{cap}', f'CapBnd:\t{cap}',
             f'CapAmb:\t{cap}', f'NoNewPrivs:\t{nnp}', f'Seccomp:\t{seccomp}', 'Seccomp_filters:\t1']
    if nspid:
        lines.append('NSpid:\t' + '\t'.join(str(n) for n in nspid))
    return '\n'.join(lines) + '\n'


def add_process(fs, pid, ppid, exe, argv, *, proc='/proc', cgroup='/', status=None, comm='x', pidns=None,
                fds=None):
    base = f'{proc}/{pid}'
    fs.files[base + '/stat'] = f'{pid} ({comm}) S {ppid} {pid} {pid} 0 -1'.encode()
    fs.files[base + '/status'] = (status or status_text()).encode()
    fs.files[base + '/cgroup'] = f'0::{cgroup}\n'.encode()
    fs.files[base + '/cmdline'] = b''.join(a.encode() + b'\0' for a in argv)
    if exe is not None:
        fs.links[base + '/exe'] = exe
    if pidns is not None:
        fs.links[base + '/ns/pid'] = pidns
    for fd, target in (fds or {}).items():
        fs.links[f'{base}/fd/{fd}'] = target


# inner pid: (ppid, exe, argv)
CONTAINER = {
    1: (0, '/usr/bin/tini', ['tini', '--', '/usr/local/bin/openhands-agent-server']),
    7: (1, '/usr/local/bin/openhands-agent-server', ['/usr/local/bin/openhands-agent-server']),
    8: (7, '/usr/local/bin/openhands-agent-server', ['/usr/local/bin/openhands-agent-server']),
    20: (8, '/acp-node/bin/node', ['node', '/acp-node/bin/claude-agent-acp']),
    21: (20, CLI, ['claude', '--output-format', 'stream-json']),
    22: (21, '/usr/bin/bash', ['bash', '-c', 'ls']),
    30: (8, '/usr/bin/bash', ['/bin/bash']),
    31: (30, '/usr/bin/python3.13', ['python3', '/tmp/aieh-containment.py', 'collect', 'container']),
}
SELF = 31
TCP = ('  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n'
       '   0: 0100007F:1F40 00000000:0000 0A 00000000:00000000 00:00000000 00000000   999        0 5001 1\n'
       '   1: 0100007F:A1B2 0100007F:1F40 01 00000000:00000000 00:00000000 00000000   999        0 5002 1\n')
TCP6 = ('  sl  local_address                         remote_address                        st\n'
        '   0: 00000000000000000000000001000000:0BB8 00000000000000000000000000000000:0000'
        ' 0A 00000000:00000000 00:00000000 00000000   999        0 7001 1\n')


def container_fs(processes=None, *, socket_owner=8):
    fs = FakeFs()
    for pid, (ppid, exe, argv) in (processes or CONTAINER).items():
        add_process(fs, pid, ppid, exe, argv, fds={'0': '/dev/null', '3': 'socket:[5001]'}
                    if pid == socket_owner else {'0': '/dev/null'})
    fs.files['/proc/net/tcp'] = TCP.encode()
    fs.files['/proc/self/stat'] = b'ignored'
    for name, value in CGROUP_LIMITS.items():
        fs.files[f'/sys/fs/cgroup/{name}'] = (value + '\n').encode()
    return fs


HOST_BASE = 4100     # host pid = HOST_BASE + inner pid


def host_fs(processes=None):
    fs = FakeFs()
    add_process(fs, 1, 0, '/usr/lib/systemd/systemd', ['/sbin/init'], cgroup='/init.scope', pidns=HOST_NS,
                status=status_text(uid=0, gid=0, cap='000001ffffffffff', nnp='0', seccomp='0', nspid=[1]))
    add_process(fs, 4090, 1, '/usr/bin/containerd-shim-runc-v2', ['containerd-shim-runc-v2'],
                cgroup='/system.slice/containerd.service', pidns=HOST_NS,
                status=status_text(uid=0, gid=0, cap='000001ffffffffff', nnp='0', seccomp='0', nspid=[4090]))
    for pid, (ppid, exe, argv) in (processes or CONTAINER).items():
        hp = HOST_BASE + pid
        add_process(fs, hp, 4090 if ppid == 0 else HOST_BASE + ppid, exe, argv, cgroup=DOCKER_SCOPE,
                    pidns=CONTAINER_NS, status=status_text(nspid=[hp, pid]))
    for name, value in CGROUP_LIMITS.items():
        fs.files[f'/sys/fs/cgroup{DOCKER_SCOPE}/{name}'] = (value + '\n').encode()
    return fs


INSPECT = {'Id': '0123abcd', 'State': {'Pid': HOST_BASE + 1},
           'HostConfig': {'Memory': 4294967296, 'NanoCpus': 2000000000, 'PidsLimit': 512}}


def container_snapshot(fs=None):
    return CC.collect('container', fs=fs or container_fs(), self_pid=SELF)


def host_snapshot(fs=None):
    return CC.collect('host', fs=fs or host_fs(), target_pid=HOST_BASE + 1, self_pid=1)


def check(verdict, prefix):
    found = [c for c in verdict['checks'] if c['check'].startswith(prefix)]
    assert len(found) == 1, (prefix, [c['check'] for c in verdict['checks']])
    return found[0]


def failed(verdict):
    return sorted(c['check'].split(':')[0] for c in verdict['checks'] if not c['ok'])


class Parsers(unittest.TestCase):
    def test_stat_reads_after_the_last_parenthesis(self):
        self.assertEqual(CC.parse_stat('42 (a b) c)) S 7 42 42'), ('S', 7))
        self.assertEqual(CC.parse_stat('1 (tini) S 0 1 1'), ('S', 0))
        for bad in ('42 tini S 7', '42 (x) S', '42 (x) S x'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                CC.parse_stat(bad)

    def test_status_keeps_the_declared_fields_normalized(self):
        st = CC.parse_status(status_text(nspid=[4120, 20]) + 'VmRSS:\t12 kB\nUid  : x\n')
        self.assertEqual(st['Uid'], '999 999 999 999')
        self.assertEqual(st['Groups'], '989')
        self.assertEqual(st['NSpid'], '4120 20')
        self.assertNotIn('VmRSS', st)
        self.assertNotIn('Seccomp_filters', st)
        self.assertEqual(set(st), set(CC.STATUS_FIELDS))

    def test_cgroup_v2_line_only(self):
        self.assertEqual(CC.parse_cgroup('12:cpu:/x\n0::/system.slice/a.scope\n'), '/system.slice/a.scope')
        self.assertEqual(CC.parse_cgroup('0::/\n'), '/')
        self.assertIsNone(CC.parse_cgroup('12:cpu:/x\n'))

    def test_cmdline_and_the_argument_summary_keep_no_value_but_a_path(self):
        self.assertEqual(CC.parse_cmdline(b'node\0/acp-node/bin/claude-agent-acp\0'),
                         ['node', '/acp-node/bin/claude-agent-acp'])
        self.assertEqual(CC.parse_cmdline(b'a\0b'), ['a', 'b'])
        self.assertEqual(CC.parse_cmdline(b''), [])
        self.assertEqual(CC.summarize_argv(['/usr/bin/env', '--flag', 'aieh-inf-secret', '/x/script.js', '/later']),
                         {'argv0': 'env', 'script': '/x/script.js', 'argc': 5})
        self.assertEqual(CC.summarize_argv(['curl', '-H', 'x-api-key: aieh-inf-secret', 'http://h/']),
                         {'argv0': 'curl', 'script': None, 'argc': 4})
        self.assertEqual(CC.summarize_argv(['a', 'b', 'c', 'd', '/fourth']), {'argv0': 'a', 'script': None,
                                                                              'argc': 5})
        self.assertEqual(CC.summarize_argv([]), {'argv0': '', 'script': None, 'argc': 0})
        long = '/' + 'p' * 400
        self.assertEqual(len(CC.summarize_argv(['/' + 'q' * 400, long])['script']), CC.ARG_MAX)
        self.assertEqual(len(CC.summarize_argv(['/' + 'q' * 400, long])['argv0']), CC.ARG_MAX)

    def test_listener_tables(self):
        self.assertEqual(CC.parse_net_tcp(TCP), [{'inode': '5001', 'address': '127.0.0.1', 'port': 8000}])
        self.assertEqual(CC.parse_net_tcp(TCP6), [{'inode': '7001', 'address': '0:0:0:0:0:0:0:1', 'port': 3000}])
        self.assertEqual(CC.parse_net_tcp('header\n   0: 00000000:1F40 00000000:0000 0A\n'), [])


class Collection(unittest.TestCase):
    def test_container_snapshot(self):
        snap = container_snapshot()
        self.assertEqual(snap['format'], CC.SNAPSHOT_FORMAT)
        self.assertEqual(snap['mode'], 'container')
        self.assertEqual([p['pid'] for p in snap['processes']], sorted(CONTAINER))
        adapter = next(p for p in snap['processes'] if p['pid'] == 20)
        self.assertEqual(adapter, {'pid': 20, 'ppid': 8, 'state': 'S', 'exe': '/acp-node/bin/node',
                                   'argv0': 'node', 'script': '/acp-node/bin/claude-agent-acp', 'argc': 2,
                                   'cgroup': '/', 'status': CC.parse_status(status_text())})
        self.assertEqual(snap['listeners'], [{'address': '127.0.0.1', 'port': 8000, 'pids': [8]}])
        self.assertEqual(snap['limits'], CGROUP_LIMITS)
        self.assertEqual(snap['fd_unreadable'], [])
        self.assertEqual(snap['vanished'], 0)
        self.assertEqual(snap['self'], SELF)
        # nothing of the argument values but paths reaches the snapshot
        self.assertNotIn('stream-json', json.dumps(snap))
        self.assertNotIn('ls', [p.get('script') for p in snap['processes']])

    def test_tcp6_listeners_are_listed_and_unknown_owners_are_empty(self):
        fs = container_fs()
        fs.files['/proc/net/tcp6'] = TCP6.encode()
        self.assertIn({'address': '0:0:0:0:0:0:0:1', 'port': 3000, 'pids': []}, container_snapshot(fs)['listeners'])

    def test_vanished_and_unreadable_processes(self):
        fs = container_fs()
        del fs.files['/proc/22/status']              # ended between its stat and its status
        fs.files['/proc/40/stat'] = b'40 (gone'      # unparsable: kept with an error
        fs.denied.add('/proc/21/cgroup')
        fs.denied.add('/proc/21/fd')
        fs.denied.add('/proc/21/exe')
        fs.denied.add('/proc/20/cmdline')
        fs.denied.add('/proc/20/status')
        snap = container_snapshot(fs)
        pids = {p['pid']: p for p in snap['processes']}
        self.assertEqual(snap['vanished'], 1)
        self.assertNotIn(22, pids)
        self.assertEqual(pids[40], {'pid': 40, 'ppid': None, 'error': 'stat: ValueError'})
        self.assertEqual((pids[21]['cgroup'], pids[21]['cgroup_error']), (None, 'PermissionError'))
        self.assertEqual((pids[21]['exe'], pids[21]['exe_error']), (None, 'PermissionError'))
        self.assertEqual(pids[20]['status'], {'error': 'PermissionError'})
        self.assertEqual(pids[20]['cmdline_error'], 'PermissionError')
        self.assertIsNone(pids[20]['argv0'])
        self.assertEqual(snap['fd_unreadable'], [21])

    def test_each_file_of_a_process_that_ended_drops_it(self):
        for part in ('stat', 'status', 'cgroup', 'cmdline'):
            with self.subTest(part=part):
                fs = container_fs()
                del fs.files[f'/proc/22/{part}']
                snap = container_snapshot(fs)
                self.assertEqual(snap['vanished'], 1)
                self.assertNotIn(22, [p['pid'] for p in snap['processes']])
        fs = container_fs()
        del fs.links['/proc/22/exe']                 # a kernel thread has no executable: kept
        self.assertIsNone(next(p for p in container_snapshot(fs)['processes'] if p['pid'] == 22)['exe'])

    def test_missing_tables_and_limits(self):
        fs = container_fs()
        del fs.files['/proc/net/tcp']
        del fs.files['/sys/fs/cgroup/pids.max']
        snap = container_snapshot(fs)
        self.assertEqual(snap['listeners'], [])
        self.assertIsNone(snap['limits']['pids.max'])

    def test_host_snapshot(self):
        snap = host_snapshot()
        self.assertEqual(snap['mode'], 'host')
        self.assertEqual(snap['target_pid'], HOST_BASE + 1)
        self.assertEqual(snap['target_pidns'], CONTAINER_NS)
        self.assertEqual(sorted(p['pid'] for p in snap['processes']), sorted(HOST_BASE + p for p in CONTAINER))
        self.assertEqual(snap['outside_children'], [])
        self.assertEqual(snap['limits'], CGROUP_LIMITS)
        self.assertNotIn('listeners', snap)

    def test_host_snapshot_lists_a_child_outside_the_namespace(self):
        fs = host_fs()
        add_process(fs, 5000, HOST_BASE + 21, '/usr/bin/sleep', ['sleep'], cgroup='/user.slice', pidns=HOST_NS)
        add_process(fs, 5001, 4090, '/usr/bin/x', ['x'], pidns=HOST_NS)
        fs.denied.add('/proc/5002/ns/pid')
        add_process(fs, 5002, 1, '/usr/bin/y', ['y'])
        snap = host_snapshot(fs)
        self.assertEqual([p['pid'] for p in snap['outside_children']], [5000])
        self.assertNotIn(5002, [p['pid'] for p in snap['processes']])

    def test_host_snapshot_target_errors(self):
        for target in (0, -1, True, None, '4101'):
            with self.subTest(target=target), self.assertRaises(CC.ContainmentError) as cm:
                CC.collect('host', fs=host_fs(), target_pid=target)
            self.assertEqual(cm.exception.code, 'TARGET_INVALID')
        with self.assertRaises(CC.ContainmentError) as cm:
            CC.collect('host', fs=host_fs(), target_pid=9999)
        self.assertEqual(cm.exception.code, 'TARGET_INVALID')
        fs = host_fs()
        del fs.files['/proc/4101/cgroup']            # the init itself vanished: no limits are read
        snap = CC.collect('host', fs=fs, target_pid=HOST_BASE + 1)
        self.assertIsNone(snap['limits'])
        with self.assertRaises(CC.ContainmentError) as cm:
            CC.collect('other', fs=host_fs())
        self.assertEqual(cm.exception.code, 'MODE_INVALID')

    def test_os_fs_reads_real_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, '12').mkdir()
            Path(tmp, '12', 'stat').write_bytes(b'12 (a) S 1 12')
            fs = CC.OsFs()
            self.assertEqual(fs.listdir(tmp), ['12'])
            self.assertEqual(fs.read_bytes(os.path.join(tmp, '12', 'stat')), b'12 (a) S 1 12')
            with mock.patch.object(CC.os, 'readlink', return_value='/bin/x') as rl:
                self.assertEqual(fs.readlink('/proc/12/exe'), '/bin/x')
            rl.assert_called_once_with('/proc/12/exe')

    def test_self_defaults_to_the_collecting_process(self):
        self.assertEqual(CC.collect('container', fs=container_fs())['self'], os.getpid())


class ContainerVerdict(unittest.TestCase):
    def verdict(self, fs=None, **over):
        return CC.container_verdict(container_snapshot(fs), expected=expected(**over))

    def test_passes(self):
        v = self.verdict()
        self.assertTrue(v['ok'], failed(v))
        self.assertEqual(v['inner_server']['pid'], 8)
        self.assertEqual(v['adapters'], [20])
        self.assertEqual([p['pid'] for p in v['provider_tree']], [20, 21, 22])
        self.assertEqual([p['pid'] for p in v['collector']], [31, 30])
        self.assertEqual(v['outside_inner_server'], [])
        self.assertEqual(v['listeners'], [{'address': '127.0.0.1', 'port': 8000, 'pids': [8], 'provider': False}])
        self.assertEqual(len(v['checks']), 10)

    def test_without_a_provider_the_adapter_checks_are_absent(self):
        procs = {k: v for k, v in CONTAINER.items() if k not in (20, 21, 22)}
        v = self.verdict(container_fs(procs), provider=None)
        self.assertTrue(v['ok'], failed(v))
        self.assertEqual(v['provider_tree'], [])
        self.assertNotIn('adapters', v)
        self.assertEqual(len(v['checks']), 8)

    def test_codex_adapter(self):
        procs = dict(CONTAINER)
        procs[20] = (8, '/acp-node/bin/node', ['node', '/acp-node/bin/codex-acp'])
        self.assertTrue(self.verdict(container_fs(procs), provider='codex')['ok'])
        self.assertEqual(failed(self.verdict(container_fs(procs))), ['adapter', 'adapter executable'])

    def assertFails(self, verdict, *names):
        self.assertFalse(verdict['ok'])
        self.assertEqual(failed(verdict), sorted(names))

    def test_adapter_missing_or_not_a_child_of_the_inner_server(self):
        procs = dict(CONTAINER)
        procs[20] = (8, '/acp-node/bin/node', ['node', '/elsewhere/claude-agent-acp'])
        self.assertFails(self.verdict(container_fs(procs)), 'adapter', 'adapter executable')
        procs[20] = (30, '/acp-node/bin/node', ['node', '/acp-node/bin/claude-agent-acp'])
        self.assertFails(self.verdict(container_fs(procs)), 'adapter', 'adapter executable')
        procs[20] = (8, '/acp-node/bin/node', ['nodejs', '/acp-node/bin/claude-agent-acp'])
        self.assertFails(self.verdict(container_fs(procs)), 'adapter', 'adapter executable')

    def test_adapter_executable(self):
        procs = dict(CONTAINER)
        procs[20] = (8, '/usr/local/bin/node', ['node', '/acp-node/bin/claude-agent-acp'])
        v = self.verdict(container_fs(procs))
        self.assertFails(v, 'adapter executable')
        fs = container_fs()
        fs.denied.add('/proc/20/exe')
        self.assertFails(self.verdict(fs), 'adapter executable')

    def test_orphan_reparented_outside_the_inner_server(self):
        procs = dict(CONTAINER)
        procs[22] = (1, '/usr/bin/bash', ['bash'])
        v = self.verdict(container_fs(procs))
        self.assertFails(v, 'ancestry')
        self.assertEqual([p['pid'] for p in v['outside_inner_server']], [22])
        procs[22] = (7, '/usr/bin/bash', ['bash'])   # a sibling of the server under its bootloader
        self.assertFails(self.verdict(container_fs(procs)), 'ancestry')

    def test_entered_from_outside(self):
        procs = dict(CONTAINER)
        procs[50] = (0, '/usr/bin/bash', ['bash'])
        self.assertFails(self.verdict(container_fs(procs)), 'entered', 'ancestry')

    def test_lost_parent_and_loop_are_unresolved(self):
        procs = dict(CONTAINER)
        procs[22] = (99, '/usr/bin/bash', ['bash'])
        v = self.verdict(container_fs(procs))
        self.assertFails(v, 'ancestry')
        self.assertEqual([p['pid'] for p in check(v, 'ancestry')['observed']['unresolved']], [22])
        procs = dict(CONTAINER)
        procs[60], procs[61] = (61, '/x', ['x']), (60, '/y', ['y'])
        self.assertFails(self.verdict(container_fs(procs)), 'ancestry')
        fs = container_fs()
        fs.files['/proc/22/stat'] = b'22 (x'
        self.assertFails(self.verdict(fs), 'ancestry', 'cgroup', 'identity')

    def test_identity_each_field(self):
        cases = {'uid': status_text(uid=0), 'gid': status_text().replace('Gid:\t989\t', 'Gid:\t0\t'),
                 'cap': status_text(cap='0000000000000400'), 'nnp': status_text(nnp='0'),
                 'seccomp': status_text(seccomp='0'),
                 'groups': status_text().replace('Groups:\t989 ', 'Groups:\t989 999')}
        for name, text in cases.items():
            with self.subTest(field=name):
                fs = container_fs()
                fs.files['/proc/21/status'] = text.encode()
                v = self.verdict(fs)
                self.assertFails(v, 'identity')
                self.assertEqual(list(check(v, 'identity')['observed']), ['21'])
        fs = container_fs()
        fs.files['/proc/21/status'] = status_text().replace('CapAmb:\t' + CAP0 + '\n', '').encode()
        self.assertFails(self.verdict(fs), 'identity')
        fs = container_fs()
        fs.denied.add('/proc/21/status')
        self.assertEqual(check(self.verdict(fs), 'identity')['observed'], {'21': ['status unreadable']})
        fs = container_fs()
        fs.files['/proc/21/status'] = b'Name:\tx\n'
        self.assertEqual(check(self.verdict(fs), 'identity')['observed'], {'21': ['status unreadable']})

    def test_identity_holds_for_the_init_too(self):
        fs = container_fs()
        fs.files['/proc/1/status'] = status_text(uid=0).encode()
        self.assertFails(self.verdict(fs), 'identity')

    def test_cgroup(self):
        fs = container_fs()
        fs.files['/proc/21/cgroup'] = b'0::/other\n'
        self.assertFails(self.verdict(fs), 'cgroup')
        fs = container_fs()
        fs.files['/proc/1/cgroup'] = b'1:name=x:/\n'
        self.assertFails(self.verdict(fs), 'cgroup')

    def test_npx_start(self):
        for argv in (['npx', '-y', '@agentclientprotocol/claude-agent-acp@0.63.0'],
                     ['node', '/acp-node/lib/node_modules/npm/bin/npx-cli.js', '-y'],
                     ['node', '/usr/local/bin/npm', 'exec'], ['/usr/local/bin/npm']):
            with self.subTest(argv=argv):
                procs = dict(CONTAINER)
                procs[23] = (8, '/acp-node/bin/node', argv)
                self.assertFails(self.verdict(container_fs(procs)), 'npx')

    def test_inner_server_missing_or_ambiguous(self):
        v = self.verdict(container_fs(socket_owner=None))
        self.assertIsNone(v['inner_server'])
        self.assertFails(v, 'inner server', 'ancestry', 'adapter', 'adapter executable')
        fs = container_fs()
        fs.links['/proc/30/fd/4'] = 'socket:[5001]'
        self.assertFails(self.verdict(fs), 'inner server', 'ancestry', 'adapter', 'adapter executable')
        v = self.verdict(container_fs(), inner_port=9000)
        self.assertFails(v, 'inner server', 'ancestry', 'adapter', 'adapter executable')
        fs = container_fs()
        fs.links['/proc/8/fd/3'] = 'socket:[9999]'
        self.assertFails(self.verdict(fs), 'inner server', 'ancestry', 'adapter', 'adapter executable')

    def test_a_provider_listener_is_reported(self):
        fs = container_fs()
        fs.files['/proc/net/tcp6'] = TCP6.encode()
        fs.links['/proc/21/fd/9'] = 'socket:[7001]'
        v = self.verdict(fs)
        self.assertTrue(v['ok'])
        self.assertIn({'address': '0:0:0:0:0:0:0:1', 'port': 3000, 'pids': [21], 'provider': True}, v['listeners'])

    def test_limits(self):
        for name in CGROUP_LIMITS:
            with self.subTest(file=name):
                fs = container_fs()
                fs.files[f'/sys/fs/cgroup/{name}'] = b'max\n'
                self.assertFails(self.verdict(fs), 'limits')
        snap = container_snapshot()
        snap['limits'] = None
        self.assertEqual(failed(CC.container_verdict(snap, expected=expected())), ['limits'])

    def test_init_missing_or_with_a_parent(self):
        procs = {k: v for k, v in CONTAINER.items() if k != 1}
        v = self.verdict(container_fs(procs))
        self.assertIn('init', failed(v))
        procs = dict(CONTAINER)
        procs[1] = (5, '/usr/bin/tini', ['tini'])
        self.assertIn('init', failed(self.verdict(container_fs(procs))))

    def test_the_collector_chain_is_named_but_not_exempt_from_identity(self):
        fs = container_fs()
        fs.files['/proc/31/status'] = status_text(seccomp='0').encode()
        self.assertFails(self.verdict(fs), 'identity')
        snap = container_snapshot()
        snap['self'] = 999
        v = CC.container_verdict(snap, expected=expected())
        self.assertEqual(v['collector'], [])
        self.assertTrue(v['ok'])
        procs = dict(CONTAINER)
        procs[30] = (1, '/usr/bin/bash', ['/bin/bash'])  # the route's shell reparented to the init
        v = self.verdict(container_fs(procs))
        self.assertTrue(v['ok'], failed(v))
        self.assertEqual([p['pid'] for p in v['collector']], [31, 30])
        snap = container_snapshot(container_fs(procs))
        snap['self'] = 22                                 # a collector claimed inside the provider tree
        self.assertTrue(CC.container_verdict(snap, expected=expected())['ok'] is False)


class Shapes(unittest.TestCase):
    def code(self, fn, *args, **kwargs):
        with self.assertRaises(CC.ContainmentError) as cm:
            fn(*args, **kwargs)
        return cm.exception.code

    def test_snapshot_shapes(self):
        good = container_snapshot()
        for mutate in (lambda s: s.update(format='x'), lambda s: s.update(mode='host'),
                       lambda s: s.update(processes=[]), lambda s: s.update(processes='x'),
                       lambda s: s['processes'].append({'pid': 0}),
                       lambda s: s['processes'].append({'pid': True}),
                       lambda s: s['processes'].append({'pid': '5'}),
                       lambda s: s['processes'].append('x'),
                       lambda s: s['processes'].append(dict(s['processes'][0])),
                       lambda s: s['processes'][0].update(ppid='1'),
                       lambda s: s['processes'][0].update(ppid=False),
                       lambda s: s['processes'][0].update(status='x')):
            snap = copy.deepcopy(good)
            mutate(snap)
            self.assertEqual(self.code(CC.container_verdict, snap, expected=expected()), 'SNAPSHOT_INVALID')
        self.assertEqual(self.code(CC.container_verdict, None, expected=expected()), 'SNAPSHOT_INVALID')

    def test_expected_shapes(self):
        snap = container_snapshot()
        for exp in (None, {k: v for k, v in expected().items() if k != 'uid'}, expected(provider='custom'),
                    expected(limits={'cgroup': {}}), expected(limits=None),
                    expected(limits={'cgroup': {}, 'inspect': []})):
            self.assertEqual(self.code(CC.container_verdict, snap, expected=exp), 'EXPECTED_INVALID')

    def test_limit_values(self):
        self.assertEqual(EXPECTED_LIMITS, {'cgroup': CGROUP_LIMITS,
                                           'inspect': {'Memory': 4294967296, 'NanoCpus': 2000000000,
                                                       'PidsLimit': 512}})
        self.assertEqual(CC.expected_limits('512m', 1.5, 1)['cgroup'],
                         {'memory.max': str(512 * 1024 ** 2), 'cpu.max': '150000 100000', 'pids.max': '1'})
        self.assertEqual(CC.expected_limits('2048', 1, 7)['inspect'],
                         {'Memory': 2048, 'NanoCpus': 1000000000, 'PidsLimit': 7})
        self.assertEqual(CC.memory_bytes(' 4G '), 4 * 1024 ** 3)
        self.assertEqual(CC.memory_bytes('3k'), 3072)
        self.assertEqual(CC.memory_bytes('5b'), 5)
        for args in (('4x', 2.0, 512), ('g', 2.0, 512), ('0g', 2.0, 512), ('-1g', 2.0, 512), ('4g', 0, 512),
                     ('4g', True, 512), ('4g', '2', 512), ('4g', 1025, 512), ('4g', 2.0, 0), ('4g', 2.0, True),
                     ('4g', 2.0, 5.0)):
            with self.subTest(args=args):
                self.assertEqual(self.code(CC.expected_limits, *args), 'LIMITS_INVALID')
        self.assertEqual(CC.expected_limits('1g', 1024, 1)['inspect']['NanoCpus'], 1024 * 10 ** 9)

    def test_output_parsing(self):
        snap = container_snapshot()
        text = 'noise\n' + CC.MARKER + '{"a": 1}\n' + CC.MARKER + json.dumps(snap) + '\ntrailer\n'
        self.assertEqual(CC.parse_output(text), snap)
        self.assertEqual(self.code(CC.parse_output, 'noise only'), 'NO_SNAPSHOT')
        self.assertEqual(self.code(CC.parse_output, None), 'NO_SNAPSHOT')
        self.assertEqual(self.code(CC.parse_output, CC.MARKER + '{bad'), 'NO_SNAPSHOT')


class HostVerdict(unittest.TestCase):
    def verdict(self, hfs=None, cfs=None, inspect=None, **over):
        return CC.host_verdict(host_snapshot(hfs), inspect=inspect or copy.deepcopy(INSPECT),
                               container=container_snapshot(cfs), expected=expected(**over))

    def test_passes(self):
        v = self.verdict()
        self.assertTrue(v['ok'], failed(v))
        self.assertEqual(v['provider_seen'], [20, 21, 22])
        self.assertEqual(v['provider_vanished'], [])
        self.assertEqual(v['appeared'], [])
        self.assertEqual(len(v['checks']), 8)

    def assertFails(self, verdict, *names):
        self.assertFalse(verdict['ok'])
        self.assertEqual(failed(verdict), sorted(names))

    def test_target_must_be_the_inspected_init(self):
        inspect = copy.deepcopy(INSPECT)
        inspect['State']['Pid'] = HOST_BASE + 8
        self.assertFails(self.verdict(inspect=inspect), 'target')
        inspect['State']['Pid'] = 0
        self.assertIn('target', failed(self.verdict(inspect=inspect)))
        inspect['State']['Pid'] = '4101'
        self.assertIn('target', failed(self.verdict(inspect=inspect)))
        snap = host_snapshot()
        snap['processes'] = [p for p in snap['processes'] if p['pid'] != HOST_BASE + 1]
        v = CC.host_verdict(snap, inspect=copy.deepcopy(INSPECT), container=container_snapshot(),
                            expected=expected())
        self.assertIn('target', failed(v))
        self.assertIn('members', failed(v))

    def test_inspected_caps(self):
        for key, value in (('Memory', 0), ('NanoCpus', 4000000000), ('PidsLimit', None)):
            with self.subTest(key=key):
                inspect = copy.deepcopy(INSPECT)
                inspect['HostConfig'][key] = value
                self.assertFails(self.verdict(inspect=inspect), 'inspect')

    def test_host_cgroup_limits(self):
        fs = host_fs()
        fs.files[f'/sys/fs/cgroup{DOCKER_SCOPE}/memory.max'] = b'max\n'
        self.assertFails(self.verdict(hfs=fs), 'host cgroup')

    def test_member_cgroup_and_identity(self):
        fs = host_fs()
        fs.files[f'/proc/{HOST_BASE + 21}/cgroup'] = b'0::/user.slice\n'
        self.assertFails(self.verdict(hfs=fs), 'members')
        fs = host_fs()
        fs.files[f'/proc/{HOST_BASE + 21}/status'] = status_text(cap='0000000000000001',
                                                                 nspid=[HOST_BASE + 21, 21]).encode()
        v = self.verdict(hfs=fs)
        self.assertFails(v, 'members')
        self.assertEqual(list(check(v, 'members: the')['observed']), [str(HOST_BASE + 21)])

    def test_escaped_child(self):
        fs = host_fs()
        add_process(fs, 5000, HOST_BASE + 21, '/usr/bin/sleep', ['sleep'], cgroup='/user.slice', pidns=HOST_NS)
        self.assertFails(self.verdict(hfs=fs), 'no escape')

    def test_namespaced_pid(self):
        fs = host_fs()
        fs.files[f'/proc/{HOST_BASE + 30}/status'] = status_text().encode()
        self.assertFails(self.verdict(hfs=fs), 'members')
        fs = host_fs()
        fs.files[f'/proc/{HOST_BASE + 30}/status'] = status_text(nspid=['x', 30]).encode()
        self.assertFails(self.verdict(hfs=fs), 'members')

    def test_cross_view(self):
        fs = host_fs()
        fs.links[f'/proc/{HOST_BASE + 20}/exe'] = '/usr/local/bin/node'
        v = self.verdict(hfs=fs)
        self.assertFails(v, 'cross-view')
        procs = {k: v for k, v in CONTAINER.items() if k != 20}
        procs[21] = (8, CLI, ['claude'])
        v = self.verdict(hfs=host_fs(procs))
        self.assertFails(v, 'cross-view')
        procs = {k: v for k, v in CONTAINER.items() if k != 22}   # a transient child ended between the views
        v = self.verdict(hfs=host_fs(procs))
        self.assertTrue(v['ok'], failed(v))
        self.assertEqual(v['provider_vanished'], [_summ(22)])
        procs = dict(CONTAINER)
        procs[45] = (8, '/usr/bin/bash', ['bash'])                  # started after the inside view
        self.assertEqual(self.verdict(hfs=host_fs(procs))['appeared'], [45])

    def test_two_host_processes_with_one_inner_pid(self):
        fs = host_fs()
        add_process(fs, 6000, HOST_BASE + 8, CLI, ['claude'], cgroup=DOCKER_SCOPE, pidns=CONTAINER_NS,
                    status=status_text(nspid=[6000, 21]))
        self.assertFails(self.verdict(hfs=fs), 'cross-view')

    def test_without_a_provider_there_is_no_cross_view_check(self):
        v = self.verdict(provider=None)
        self.assertTrue(v['ok'])
        self.assertEqual(len(v['checks']), 7)

    def test_shapes(self):
        for inspect in ({}, {'State': {}}, {'HostConfig': {}}, {'State': [], 'HostConfig': {}}):
            with self.assertRaises(CC.ContainmentError) as cm:
                CC.host_verdict(host_snapshot(), inspect=inspect, container=container_snapshot(),
                                expected=expected())
            self.assertEqual(cm.exception.code, 'INSPECT_INVALID')
        with self.assertRaises(CC.ContainmentError) as cm:
            CC.host_verdict(container_snapshot(), inspect=INSPECT, container=container_snapshot(),
                            expected=expected())
        self.assertEqual(cm.exception.code, 'SNAPSHOT_INVALID')
        with self.assertRaises(CC.ContainmentError) as cm:
            CC.host_verdict(host_snapshot(), inspect=INSPECT, container=host_snapshot(), expected=expected())
        self.assertEqual(cm.exception.code, 'SNAPSHOT_INVALID')


def _summ(pid):
    ppid, exe, argv = CONTAINER[pid]
    s = CC.summarize_argv(argv)
    return {'pid': pid, 'ppid': ppid, 'exe': exe, 'argv0': s['argv0'], 'script': s['script']}


CONV = '5f0c2a0e-58ac-4a5c-9c5b-6a1b0f6d2b11'


def sets(containers=('c1',), outer=('o1', CONV.replace('-', '')), inner=()):
    return {'containers': list(containers), 'outer': list(outer),
            'inner': [{'id': i, 'parent_conversation_id': p} for i, p in inner]}


class SetsVerdict(unittest.TestCase):
    def test_nothing_new(self):
        v = CC.sets_verdict(sets(inner=[(CONV, None)]), sets(inner=[(CONV, None)]), conversation_id=CONV)
        self.assertTrue(v['ok'])
        self.assertEqual(v['delegation'], {'children_route': [], 'outer_new': [], 'containers_new': []})

    def test_a_child_through_the_inner_route_is_classified_not_failed(self):
        v = CC.sets_verdict(sets(inner=[(CONV, None)]), sets(inner=[(CONV, None), ('k1', CONV)]),
                            conversation_id=CONV)
        self.assertTrue(v['ok'])
        self.assertEqual(v['delegation']['children_route'], ['k1'])

    def test_failures(self):
        cases = {'containers': (sets(), sets(containers=('c1', 'c2'))),
                 'outer server': (sets(), sets(outer=('o1', 'o2', CONV.replace('-', '')))),
                 'inner server': (sets(), sets(inner=[('k2', 'another')])),
                 'inner server ': (sets(), sets(inner=[('k3', None)]))}
        for name, (before, after) in cases.items():
            with self.subTest(case=name):
                v = CC.sets_verdict(before, after, conversation_id=CONV)
                self.assertFalse(v['ok'])
                self.assertEqual(failed(v), [name.strip()])
        v = CC.sets_verdict(sets(containers=('c1', 'c2')), sets(), conversation_id=CONV)
        self.assertTrue(v['ok'])     # a container that ended is not a new one

    def test_shapes(self):
        bad = [({'containers': [], 'outer': []}, sets()), (sets(), None), (sets(containers=('',)), sets()),
               (sets(), {'containers': 'c1', 'outer': [], 'inner': []}), (sets(), dict(sets(), inner='x')),
               (sets(), dict(sets(), inner=['x'])), (sets(), dict(sets(), inner=[{'id': ''}])),
               (sets(), dict(sets(), inner=[{'id': 'a', 'parent_conversation_id': 5}])),
               (sets(), dict(sets(), outer=[5])), (dict(sets(), extra=[]), sets())]
        for before, after in bad:
            with self.assertRaises(CC.ContainmentError) as cm:
                CC.sets_verdict(before, after, conversation_id=CONV)
            self.assertEqual(cm.exception.code, 'SETS_INVALID')
        for conv in ('', None, 5):
            with self.assertRaises(CC.ContainmentError):
                CC.sets_verdict(sets(), sets(), conversation_id=conv)


class EdgeCases(unittest.TestCase):
    """Edges each verdict and parser must hold (several added from the slice's mutation check)."""

    def test_constants(self):
        self.assertEqual((CC.ARG_MAX, CC.SCRIPT_SCAN, CC.INNER_PORT, CC.CPU_PERIOD), (256, 4, 8000, 100000))
        self.assertEqual(CC.LIMIT_FILES, ('memory.max', 'cpu.max', 'pids.max'))

    def test_error_carries_code_and_detail(self):
        exc = CC.ContainmentError('SETS_INVALID', 'why')
        self.assertEqual((exc.code, exc.detail, str(exc)), ('SETS_INVALID', 'why', 'SETS_INVALID: why'))

    def test_stat_edges(self):
        self.assertEqual(CC.parse_stat('42 (x) S 7'), ('S', 7))
        with self.assertRaises(ValueError):
            CC.parse_stat('7 8 9')

    def test_status_ignores_lines_without_a_colon(self):
        st = CC.parse_status(status_text() + 'Groups\nSeccomp\n')
        self.assertEqual((st['Groups'], st['Seccomp']), ('989', '2'))

    def test_ipv6_address_groups(self):
        row = '   0: 000080FE00000000FFB3020229831EFE:0050 0 0A 0 0 0 0 0 0 1\n'
        self.assertEqual(CC.parse_net_tcp('header\n' + row)[0]['address'], 'fe80:0:0:0:202:b3ff:fe1e:8329')

    def test_only_socket_links_are_owners(self):
        fs = container_fs()
        fs.links['/proc/30/fd/5'] = 'pipe:x:[5001]'
        fs.links['/proc/30/fd/6'] = 'socket:[5001)'
        self.assertEqual(container_snapshot(fs)['listeners'], [{'address': '127.0.0.1', 'port': 8000, 'pids': [8]}])

    def test_default_file_system(self):
        fake = container_fs()
        with mock.patch.object(CC, 'OsFs', return_value=fake):
            self.assertEqual(CC.collect('container', self_pid=SELF), container_snapshot(fake))

    def test_host_target_one_and_vanished(self):
        snap = CC.collect('host', fs=host_fs(), target_pid=1)
        self.assertEqual(sorted(p['pid'] for p in snap['processes']), [1, 4090])
        fs = host_fs()
        del fs.files[f'/proc/{HOST_BASE + 22}/cmdline']
        snap = host_snapshot(fs)
        self.assertEqual(snap['vanished'], 1)
        self.assertNotIn(HOST_BASE + 22, [p['pid'] for p in snap['processes']])

    def test_listeners_absent_or_owned_by_no_listed_process(self):
        snap = container_snapshot()
        snap['listeners'] = None
        self.assertIn('inner server', failed(CC.container_verdict(snap, expected=expected())))
        snap = container_snapshot()
        snap['listeners'] = [{'address': '127.0.0.1', 'port': 8000, 'pids': [77]}]
        v = CC.container_verdict(snap, expected=expected())
        self.assertIn('inner server', failed(v))
        self.assertIsNone(v['inner_server'])

    def test_no_cgroup_anywhere_fails(self):
        fs = container_fs()
        for pid in CONTAINER:
            fs.files[f'/proc/{pid}/cgroup'] = b'1:name=systemd:/\n'
        self.assertIn('cgroup', failed(CC.container_verdict(container_snapshot(fs), expected=expected())))
        fs = host_fs()
        for pid in CONTAINER:
            fs.files[f'/proc/{HOST_BASE + pid}/cgroup'] = b'1:name=systemd:/\n'
        v = CC.host_verdict(host_snapshot(fs), inspect=copy.deepcopy(INSPECT), container=container_snapshot(),
                            expected=expected())
        self.assertIn('members', failed(v))

    def test_host_verdict_checks_its_expectations_and_inspection(self):
        with self.assertRaises(CC.ContainmentError) as cm:
            CC.host_verdict(host_snapshot(), inspect=INSPECT, container=container_snapshot(), expected={})
        self.assertEqual(cm.exception.code, 'EXPECTED_INVALID')
        with self.assertRaises(CC.ContainmentError) as cm:
            CC.host_verdict(host_snapshot(), inspect=None, container=container_snapshot(), expected=expected())
        self.assertEqual(cm.exception.code, 'INSPECT_INVALID')
        with self.assertRaises(CC.ContainmentError) as cm:
            CC.container_verdict(container_snapshot(), expected=expected(limits={'cgroup': [], 'inspect': {}}))
        self.assertEqual(cm.exception.code, 'EXPECTED_INVALID')

    def test_cross_view_compares_every_provider_process(self):
        fs = host_fs()
        fs.links[f'/proc/{HOST_BASE + 21}/exe'] = '/usr/bin/other'
        v = CC.host_verdict(host_snapshot(fs), inspect=copy.deepcopy(INSPECT), container=container_snapshot(),
                            expected=expected())
        self.assertEqual(failed(v), ['cross-view'])
        self.assertEqual(v['provider_seen'], [20, 22])

    def test_cross_view_needs_an_adapter_and_takes_a_lone_one(self):
        procs = {k: v for k, v in CONTAINER.items() if k not in (21, 22)}
        v = CC.host_verdict(host_snapshot(host_fs(procs)), inspect=copy.deepcopy(INSPECT),
                            container=container_snapshot(container_fs(procs)), expected=expected())
        self.assertTrue(v['ok'], failed(v))
        self.assertEqual(v['provider_seen'], [20])
        procs = {k: v for k, v in CONTAINER.items() if k not in (20, 21, 22)}
        v = CC.host_verdict(host_snapshot(host_fs(procs)), inspect=copy.deepcopy(INSPECT),
                            container=container_snapshot(container_fs(procs)), expected=expected())
        self.assertEqual(failed(v), ['cross-view'])

    def test_a_ten_field_listener_row(self):
        row = '   0: 0100007F:1F40 00000000:0000 0A 0:0 0:0 0 999 0 5001\n'
        self.assertEqual(CC.parse_net_tcp('header\n' + row),
                         [{'inode': '5001', 'address': '127.0.0.1', 'port': 8000}])

    def test_inner_rows_must_be_a_list(self):
        with self.assertRaises(CC.ContainmentError) as cm:
            CC.sets_verdict(sets(), dict(sets(), inner={}), conversation_id=CONV)
        self.assertEqual(cm.exception.code, 'SETS_INVALID')

    def test_output_is_canonical(self):
        out = io.StringIO()
        with mock.patch.object(CC, 'collect', return_value={'b': 1, 'a': [1, 2]}):
            CC.main(['collect', 'container'], out=out)
        self.assertEqual(out.getvalue(), CC.MARKER + '{"a":[1,2],"b":1}\n')


class CommandLine(unittest.TestCase):
    def run_main(self, argv):
        out = io.StringIO()
        with mock.patch.object(CC, 'collect', return_value={'format': 'x'}) as collect:
            code = CC.main(argv, out=out)
        return code, out.getvalue(), collect

    def test_collect_prints_one_marker_line(self):
        code, text, collect = self.run_main(['collect', 'container'])
        self.assertEqual((code, text), (0, CC.MARKER + '{"format":"x"}\n'))
        collect.assert_called_once_with('container', target_pid=None)
        code, text, collect = self.run_main(['collect', 'host', '--pid', '4101'])
        collect.assert_called_once_with('host', target_pid=4101)

    def test_argument_errors(self):
        for argv in ([], ['collect'], ['collect', 'other'], ['collect', 'host'],
                     ['collect', 'container', '--pid', '5'], ['collect', 'host', '--pid', 'x']):
            with self.subTest(argv=argv), mock.patch('sys.stderr', io.StringIO()), \
                    self.assertRaises(SystemExit) as cm:
                CC.main(argv, out=io.StringIO())
            self.assertEqual(cm.exception.code, 2)

    def test_a_refusal_is_reported_without_a_result_line(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(CC, 'collect', side_effect=CC.ContainmentError('TARGET_INVALID', 'gone')), \
                mock.patch('sys.stderr', err):
            self.assertEqual(CC.main(['collect', 'host', '--pid', '9'], out=out), 2)
        self.assertEqual(out.getvalue(), '')
        self.assertIn('TARGET_INVALID', err.getvalue())

    def test_main_writes_to_stdout_by_default(self):
        with mock.patch.object(CC, 'collect', return_value={}), mock.patch('sys.stdout', io.StringIO()) as out:
            self.assertEqual(CC.main(['collect', 'container']), 0)
        self.assertEqual(out.getvalue(), CC.MARKER + '{}\n')

    def test_the_module_is_standalone(self):
        """It is sent to the guest as one file: standard library only, no harness import."""
        import ast
        tree = ast.parse((HERE.parent / 'conversation_containment.py').read_text(encoding='utf-8'))
        names = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertEqual(names, {'__future__', 'argparse', 'ipaddress', 'json', 'os', 'sys'})


ENDPOINT = ('172.17.0.1', 8090)
HEADER = '  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n'


def tcp_row(local, remote, state, inode):
    return f'   0: {local} {remote} {state} 00000000:00000000 00:00000000 00000000   999        0 {inode} 1\n'


# 172.17.0.2 (the container) to 172.17.0.1:8090 (the endpoint), the outer server into the inner server's 8000,
# and loopback; 1.1.1.1:443 in each state of interest
TO_ENDPOINT = tcp_row('020011AC:C350', '010011AC:1F9A', '01', 6001)
INBOUND = tcp_row('020011AC:1F40', '010011AC:D431', '01', 6002)
ELSEWHERE = {state: tcp_row('020011AC:C351', '01010101:01BB', code, 6003)
             for state, code in (('ESTABLISHED', '01'), ('SYN_SENT', '02'), ('TIME_WAIT', '06'),
                                 ('CLOSE_WAIT', '08'), ('CLOSE', '07'), ('FIN_WAIT1', '04'))}


def net_snapshot(*rows, tcp6=None):
    fs = container_fs()
    fs.files['/proc/net/tcp'] = (TCP + ''.join(rows)).encode()
    if tcp6 is not None:
        fs.files['/proc/net/tcp6'] = tcp6.encode()
    fs.links['/proc/8/fd/7'] = 'socket:[6002]'
    fs.links['/proc/21/fd/9'] = 'socket:[6001]'
    fs.links['/proc/21/fd/10'] = 'socket:[6003]'
    return container_snapshot(fs)


class NetworkVerdict(unittest.TestCase):
    """S-03.3 slice 5: the connections of the container view against its one permitted destination."""

    def test_connection_table_and_owners(self):
        self.assertEqual(CC.parse_net_connections(HEADER + TO_ENDPOINT + TCP.split('\n', 1)[1]),
                         [{'inode': '6001', 'local': '172.17.0.2', 'local_port': 50000, 'remote': '172.17.0.1',
                           'remote_port': 8090, 'state': 'ESTABLISHED'},
                          {'inode': '5002', 'local': '127.0.0.1', 'local_port': 41394, 'remote': '127.0.0.1',
                           'remote_port': 8000, 'state': 'ESTABLISHED'}])
        self.assertEqual(CC.parse_net_connections(HEADER + tcp_row('0100007F:1', '0100007F:2', '0D', 1))[0]['state'],
                         '0D')
        self.assertEqual(CC.parse_net_connections('header\n   0: 0100007F:1F40 00000000:0000 01\n'), [])
        snap = net_snapshot(TO_ENDPOINT, INBOUND)
        self.assertIn({'local': '172.17.0.2', 'local_port': 50000, 'remote': '172.17.0.1', 'remote_port': 8090,
                       'state': 'ESTABLISHED', 'pids': [21]}, snap['connections'])
        self.assertIn({'local': '172.17.0.2', 'local_port': 8000, 'remote': '172.17.0.1', 'remote_port': 54321,
                       'state': 'ESTABLISHED', 'pids': [8]}, snap['connections'])
        self.assertEqual(snap['tables_unread'], [{'table': 'tcp6', 'error': 'FileNotFoundError'}])
        self.assertNotIn('6001', json.dumps(snap['connections']))   # no inode is kept

    def test_the_endpoint_loopback_and_inbound_pass(self):
        verdict = CC.network_verdict(net_snapshot(TO_ENDPOINT, INBOUND), endpoint=ENDPOINT)
        self.assertTrue(verdict['ok'], verdict['checks'])
        self.assertEqual(sorted(c['kind'] for c in verdict['connections']),
                         ['inbound to the inner server', 'loopback', 'the inference endpoint'])
        self.assertEqual((verdict['other_reached'], verdict['attempted']), ([], []))
        self.assertEqual(verdict['vantage'], 'network')
        self.assertTrue(CC.network_verdict(net_snapshot(), endpoint=list(ENDPOINT))['ok'])

    def test_any_other_destination_the_peer_answered_fails(self):
        for state in ('ESTABLISHED', 'TIME_WAIT', 'CLOSE_WAIT', 'FIN_WAIT1'):
            with self.subTest(state=state):
                verdict = CC.network_verdict(net_snapshot(TO_ENDPOINT, ELSEWHERE[state]), endpoint=ENDPOINT)
                self.assertFalse(verdict['ok'])
                self.assertEqual([r['remote'] for r in verdict['other_reached']], ['1.1.1.1'])
                self.assertEqual(failed(verdict), ['network'])
                self.assertFalse(check(verdict, 'network: no connection reached')['ok'])
                self.assertTrue(check(verdict, 'network: every connection state')['ok'])
        # another port of the endpoint's address, or the endpoint's port elsewhere, is another destination
        for row in (tcp_row('020011AC:C352', '010011AC:1F9B', '01', 6004),
                    tcp_row('020011AC:C352', '0F02000A:1F9A', '01', 6004)):
            with self.subTest(row=row):
                self.assertEqual(len(CC.network_verdict(net_snapshot(row), endpoint=ENDPOINT)['other_reached']), 1)

    def test_an_attempt_is_recorded_not_failed_and_close_is_ambiguous(self):
        verdict = CC.network_verdict(net_snapshot(ELSEWHERE['SYN_SENT']), endpoint=ENDPOINT)
        self.assertTrue(verdict['ok'])
        self.assertEqual([r['state'] for r in verdict['attempted']], ['SYN_SENT'])
        for row in (ELSEWHERE['CLOSE'], tcp_row('020011AC:C352', '01010101:01BB', '0D', 6005)):
            with self.subTest(row=row):
                verdict = CC.network_verdict(net_snapshot(row), endpoint=ENDPOINT)
                self.assertFalse(verdict['ok'])
                self.assertEqual(verdict['other_reached'], [])
                self.assertFalse(check(verdict, 'network: every connection state')['ok'])

    def test_ipv6_mapped_and_ipv6_loopback(self):
        tcp6 = (HEADER + tcp_row('0000000000000000FFFF0000020011AC:C353', '0000000000000000FFFF0000010011AC:1F9A',
                                 '01', 6006)
                + tcp_row('00000000000000000000000001000000:C354', '00000000000000000000000001000000:1F40', '01',
                          6007))
        verdict = CC.network_verdict(net_snapshot(tcp6=tcp6), endpoint=ENDPOINT)
        self.assertTrue(verdict['ok'], verdict['checks'])
        self.assertEqual(sorted(c['kind'] for c in verdict['connections'] if c['local_port'] > 50000),
                         ['loopback', 'the inference endpoint'])
        self.assertEqual(net_snapshot(tcp6=tcp6)['tables_unread'], [])

    def test_unread_tables(self):
        fs = container_fs()
        del fs.files['/proc/net/tcp']
        verdict = CC.network_verdict(container_snapshot(fs), endpoint=ENDPOINT)
        self.assertFalse(verdict['ok'])
        self.assertEqual(check(verdict, 'network: every connection state')['observed']['tables_unread'],
                         [{'table': 'tcp', 'error': 'FileNotFoundError'}])
        fs = container_fs()
        fs.denied.add('/proc/net/tcp6')
        fs.files['/proc/net/tcp6'] = b''
        self.assertFalse(CC.network_verdict(container_snapshot(fs), endpoint=ENDPOINT)['ok'])

    def test_shapes(self):
        snap = net_snapshot()
        for endpoint in (None, ('172.17.0.1',), ('not an address', 8090), ('172.17.0.1', '8090'),
                         ('172.17.0.1', True)):
            with self.subTest(endpoint=endpoint), self.assertRaises(CC.ContainmentError) as cm:
                CC.network_verdict(snap, endpoint=endpoint)
            self.assertEqual(cm.exception.code, 'EXPECTED_INVALID')
        for bad in (dict(snap, connections=None), dict(snap, connections=[1]), dict(snap, mode='host')):
            with self.subTest(bad=bad), self.assertRaises(CC.ContainmentError) as cm:
                CC.network_verdict(bad, endpoint=ENDPOINT)
            self.assertEqual(cm.exception.code, 'SNAPSHOT_INVALID')
        odd = dict(snap, connections=[{'local': 'x', 'local_port': 1, 'remote': 'not-an-ip', 'remote_port': 2,
                                       'state': 'ESTABLISHED'}])
        self.assertEqual(len(CC.network_verdict(odd, endpoint=ENDPOINT)['other_reached']), 1)
        self.assertEqual(CC.network_verdict(snap, endpoint=ENDPOINT, inner_port=9)['ok'], True)


if __name__ == '__main__':
    unittest.main()
