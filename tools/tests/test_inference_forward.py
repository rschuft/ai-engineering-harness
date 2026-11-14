"""The inference forward session of tools/guest.py (plan leaf S-03.2, slice 3; decision 0015 sections
4.1, 4.3 and 4.4), offline: no real ssh, no guest, no broker, no managed state.

A fake ssh (a Python script under the base interpreter, written into the test's own temporary
directory) prints the lines OpenSSH's client prints with -v and then holds, or refuses the forward,
or says nothing. The holder (forward_hold) runs in a thread of the test process with that fake as its
ssh, except in one test that starts it as the real detached process. Every instance directory, broker
and record is a fixture.
"""
import base64
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO / 'profiles' / 'strong-windows-qemu-whpx'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import module_code  # noqa: E402
guest = module_code.load('guest', REPO / 'tools' / 'guest.py')

PROFILE = json.loads((PROFILE_DIR / 'profile.json').read_text(encoding='utf-8'))
INF = PROFILE['network']['inference_composition']
SESSION = INF['forward_session']
BROKER_PORTS = {'control_port': 18431, 'inference_port': 18432}
BASE_PYTHON = getattr(sys, '_base_executable', sys.executable)
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)     # no console window on Windows
REAL_POPEN = subprocess.Popen
LAUNCH = {'schema': guest.LAUNCH_SCHEMA, 'binary': 'D:/x/qemu-system-x86_64.exe',
          'ports': {'ssh': 40001, 'qmp': 40002, 'bind': '127.0.0.1'},
          'inference': {'composition': 'inference', 'status': 'planned'}}

# What OpenSSH's client prints with -v around a remote forward (ssh.c ssh_confirm_remote_forward),
# then it holds the session; AIEH_TEST_FAKE_SSH=refuse ends it as ExitOnForwardFailure does, and
# silent never reports the forward.
FAKE_SSH = r'''import os, sys, threading
args = sys.argv[1:]
host, port, to_host, to_port = args[args.index('-R') + 1].split(':')
mode = os.environ.get('AIEH_TEST_FAKE_SSH', 'hold')
err = sys.stderr
err.write('OpenSSH_for_Windows_9.5p1 (a test fake)\n')
err.write('debug1: Authentication succeeded (publickey).\n')
if mode == 'refuse':
    err.write('debug1: remote forward failure for: listen %s:%s, connect %s:%s\n' % (host, port, to_host, to_port))
    err.write('Error: remote port forwarding failed for listen port %s\n' % port)
    err.flush()
    sys.exit(255)
if mode != 'silent':
    err.write('debug1: remote forward success for: listen %s:%s, connect %s:%s\n' % (host, port, to_host, to_port))
    err.write('debug1: All remote forwarding requests processed\n')
    err.write('a non-debug line the holder keeps\n')
err.flush()
threading.Event().wait()
'''


class FakeSsh:
    """Stands in for guest.Ssh: the per-instance channel's argv, ending with the destination."""

    def __init__(self, script):
        self.script = script

    def argv(self, user, command):
        return [BASE_PYTHON, '-I', '-B', str(self.script), '-F', 'none', '-i', 'id_ed25519', '-p',
                '40001', f'{user}@127.0.0.1'] + list(command)


class FakeBroker:
    """Stands in for BrokerAccess: the configured ports and the control listener's status."""

    def __init__(self, inference=18432, refuse=None):
        self.ports = dict(BROKER_PORTS)
        self.listening, self.refuse, self.calls = inference, refuse, []

    def call(self, method, *args):
        self.calls.append(method)
        if self.refuse:
            raise guest.Refused('BROKER', self.refuse)
        return {'listeners': {'control': {'port': 18431}, 'inference': {'port': self.listening}}}


def threaded_spawn(threads, pid=0):
    """forward_spawn's stand-in: the holder in a thread of this process (``pid`` for its record),
    its report line read through a pipe as from the real detached holder."""
    def spawn(spec, cwd):
        r, w = os.pipe()
        reader, writer = os.fdopen(r, 'rb'), os.fdopen(w, 'w', encoding='utf-8')
        text = base64.b64encode(json.dumps(spec).encode()).decode()
        box = {}

        def hold():
            try:
                box['rc'] = guest.forward_hold(text, out=writer, pid=pid)
            finally:
                writer.close()
        thread = threading.Thread(target=hold, daemon=True)
        thread.start()
        threads.append((thread, box))
        return types.SimpleNamespace(stdout=reader, kill=lambda: None, pid=pid)
    return spawn


class ProcessLedger:
    """Every process a test starts (through subprocess.Popen, which guest uses, and the pids its
    records name) is ended in cleanup, whole tree, and none may be left alive; every launch must
    carry the flags the shared no-window helper gives this process (CREATE_NO_WINDOW where it has no
    console), and none DETACHED_PROCESS or CREATE_NEW_CONSOLE, so that none opens a console window."""

    def ledger(self):
        self.launched, self.pids = [], set()
        test = self

        class Recording(REAL_POPEN):
            def __init__(self, *args, **kwargs):
                test.launched.append(kwargs.get('creationflags', 0))
                super().__init__(*args, **kwargs)
                test.pids.add(self.pid)
        patcher = mock.patch.object(subprocess, 'Popen', Recording)
        patcher.start()
        self.addCleanup(self.end_processes)
        self.addCleanup(patcher.stop)

    def end_processes(self):
        left = []
        for pid in sorted(self.pids):
            try:
                handle = guest.WinProcess(pid)
            except OSError:
                continue                             # gone (or never alive)
            try:
                if handle.alive():
                    handle.terminate()
                    if not handle.wait(10):
                        left.append(pid)
            finally:
                handle.close()
        self.assertEqual(left, [], 'processes left alive')
        for pid in sorted(self.pids):
            try:
                handle = guest.WinProcess(pid)
            except OSError:
                continue
            try:
                self.assertFalse(handle.alive(), pid)
            finally:
                handle.close()
        if os.name == 'nt':
            want = guest._no_window().no_window_flags()
            opens = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_CONSOLE
            self.assertTrue(all(flags & want == want and not flags & opens for flags in self.launched),
                            self.launched)


class ForwardBase(unittest.TestCase):
    """One temporary state per class; each test its own instance directory."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-forward-test-'))
        cls.addClassCleanup(guest.remove_tree, cls.tmp)
        cls.state = cls.tmp / 'state'
        (cls.state / 'instances').mkdir(parents=True)
        cls.script = cls.tmp / 'fake_ssh.py'
        cls.script.write_text(FAKE_SSH, encoding='utf-8')
        home = cls.tmp / 'home'
        home.mkdir()
        patcher = mock.patch.dict(os.environ, {'USERPROFILE': str(home), 'HOME': str(home)})
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        cls.ctx = guest.Context(str(PROFILE_DIR), str(cls.state))
        cls.count = 0

    def instance(self, launch=LAUNCH):
        type(self).count += 1
        name = f'inst-{type(self).count}'
        idir = self.ctx.instance_dir(name)
        idir.mkdir()
        (idir / 'launch.json').write_text(json.dumps(launch), encoding='utf-8')
        return name, idir

    def record_path(self, idir):
        return idir / 'inference-forward.json'

    def session(self, **change):
        session = {'schema': guest.FORWARD_SCHEMA, 'instance': 'x', 'pid': 4242,
                   'binary': BASE_PYTHON, 'created_epoch': 1.0, 'holder_pid': 4343,
                   'started_at': 'now', 'ports': {}, 'argv': []}
        session.update(change)
        return session


class ForwardRecords(ForwardBase):
    """The record's state, its stale removal and the ssh command line, without processes."""

    def test_state_none_unreadable_stale_and_held(self):
        _, idir = self.instance()
        state = guest.forward_state(PROFILE, idir)
        self.assertEqual((state['held'], state['stale'], state['session']), (False, None, None))
        self.assertEqual(state['path'], guest.posix(self.record_path(idir)))
        for text, fragment in (('{not json', 'unreadable'),
                               (json.dumps(self.session(schema='other')), 'not a forward-session'),
                               (json.dumps(dict(self.session(), extra=1)), 'not a forward-session'),
                               (json.dumps([1]), 'not a forward-session')):
            self.record_path(idir).write_text(text, encoding='utf-8')
            state = guest.forward_state(PROFILE, idir)
            self.assertFalse(state['held'])
            self.assertIn(fragment, state['stale'])
        self.record_path(idir).write_text(json.dumps(self.session()), encoding='utf-8')
        with mock.patch.object(guest, 'forward_process', return_value=None):
            state = guest.forward_state(PROFILE, idir)
        self.assertEqual((state['held'], state['stale']), (False, 'its ssh process is gone'))
        self.assertEqual(state['session'], self.session())
        handle = mock.Mock()
        with mock.patch.object(guest, 'forward_process', return_value=handle):
            state = guest.forward_state(PROFILE, idir)
        self.assertEqual((state['held'], state['stale']), (True, None))
        handle.close.assert_called_once_with()
        self.assertTrue(self.record_path(idir).is_file())          # reading changes nothing

    def test_remove_stale_never_removes_a_held_session(self):
        _, idir = self.instance()
        self.record_path(idir).write_text('{}', encoding='utf-8')
        path = guest.posix(self.record_path(idir))
        held = {'path': path, 'held': True, 'stale': None, 'session': {}}
        self.assertIsNone(guest.remove_stale_forward(PROFILE, idir, held))
        self.assertIsNone(guest.remove_stale_forward(PROFILE, idir, dict(held, held=False)))
        self.assertTrue(self.record_path(idir).is_file())
        stale = dict(held, held=False, stale='gone', session={'pid': 1})
        self.assertEqual(guest.remove_stale_forward(PROFILE, idir, stale),
                         {'why': 'gone', 'session': {'pid': 1}})
        self.assertFalse(self.record_path(idir).exists())
        self.assertEqual(guest.remove_stale_forward(PROFILE, idir, stale)['why'], 'gone')

    def test_forward_process_trusts_pid_binary_and_creation_time(self):
        class Proc:
            closed = 0

            def __init__(self, pid, alive=True, image=BASE_PYTHON, created=100.0):
                self.pid, self._alive, self._image, self._created = pid, alive, image, created

            def alive(self):
                return self._alive

            def image(self):
                return self._image

            def created(self):
                return self._created

            def close(self):
                Proc.closed += 1
        good = self.session(created_epoch=100.4)
        for proc, held in ((Proc(1), True), (Proc(1, alive=False), False),
                           (Proc(1, image='C:/other.exe'), False), (Proc(1, created=102.0), False)):
            with mock.patch.object(guest, 'WinProcess', return_value=proc):
                self.assertEqual(guest.forward_process(good) is proc, held)
        with mock.patch.object(guest, 'WinProcess', side_effect=OSError(87, 'gone')):
            self.assertIsNone(guest.forward_process(good))
        self.assertIsNone(guest.forward_process({'pid': 'x'}))
        with mock.patch.object(guest.os, 'name', 'posix'):
            with self.assertRaises(guest.Refused):
                guest.forward_process(good)

    def test_forward_argv(self):
        argv = guest.forward_argv(PROFILE, FakeSsh(self.script), 18432)
        self.assertEqual(argv[-1], 'agent@127.0.0.1')
        self.assertEqual(argv[-3:-1], ['-R', '172.17.0.1:8090:127.0.0.1:18432'])
        self.assertEqual(argv[-3 - len(SESSION['ssh_options']):-3], SESSION['ssh_options'])
        self.assertIn('ExitOnForwardFailure=yes', argv)
        self.assertEqual(argv[:4], [BASE_PYTHON, '-I', '-B', str(self.script)])
        broken = json.loads(json.dumps(PROFILE))
        broken['network']['inference_composition']['forward_session']['ssh_options'] = ['-N']
        with self.assertRaises(guest.Refused):
            guest.forward_argv(broken, FakeSsh(self.script), 18432)
        bare = json.loads(json.dumps(PROFILE))
        bare['network']['endpoints'] = []
        with self.assertRaises(guest.Refused):
            guest.forward_argv(bare, FakeSsh(self.script), 18432)

    def test_forward_argv_over_the_instance_channel(self):
        """The exact command line with the real per-instance channel (guest.Ssh), its ssh -G check
        and the OpenSSH lookup stood in for: no ssh runs."""
        _, idir = self.instance()
        (idir / 'ssh').mkdir()
        for name in ('id_ed25519', 'known_hosts'):
            (idir / 'ssh' / name).write_text('synthetic\n', encoding='utf-8')
        exe = 'C:/Windows/System32/OpenSSH/ssh.exe'
        with mock.patch.object(guest, 'openssh', return_value=exe), \
                mock.patch.object(guest.Ssh, 'check_effective', autospec=True) as checked:
            ssh = guest.Ssh(PROFILE, idir, 40001)
            argv = guest.forward_argv(PROFILE, ssh, 18432)
        checked.assert_called_once()
        known = guest.posix(idir) + '/ssh/known_hosts'
        self.assertEqual(argv, [
            exe, '-F', 'none', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', f'UserKnownHostsFile={known}', '-o', 'BatchMode=yes', '-o', 'IdentityAgent=none',
            '-o', 'GlobalKnownHostsFile=none', '-o', 'ConnectTimeout=15',
            '-i', str(idir / 'ssh' / 'id_ed25519'), '-p', '40001',
            '-N', '-v', '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15',
            '-o', 'ServerAliveCountMax=3', '-R', '172.17.0.1:8090:127.0.0.1:18432',
            'agent@127.0.0.1'])

    def test_launches_open_no_console_window(self):
        """The holder and the ssh it starts: CREATE_NO_WINDOW, never DETACHED_PROCESS (whose
        console-less process would give ssh a window of its own); no process is started."""
        seen = []

        class Stop(Exception):
            pass

        def popen(argv, **kwargs):
            seen.append((argv, kwargs))
            raise Stop
        spec = {'argv': ['ssh.exe', '-N'], 'record': 'x', 'log': 'y', 'instance': 'i',
                'listen': 'a:1', 'connect': 'b:2', 'ceiling': 1, 'ports': {}}
        _, idir = self.instance()
        with mock.patch.object(guest.subprocess, 'Popen', popen):
            with self.assertRaises(Stop):
                guest.forward_spawn(spec, idir)
            with self.assertRaises(Stop):
                guest.forward_hold(base64.b64encode(json.dumps(spec).encode()).decode(),
                                   out=io.StringIO(), pid=0)
        (holder, holder_kw), (ssh, ssh_kw) = seen
        self.assertEqual(holder[3:5], [str(REPO / 'tools' / 'guest.py'), 'inference-forward-hold'])
        self.assertEqual(ssh, ['ssh.exe', '-N'])
        if os.name == 'nt':
            self.assertEqual(holder_kw['creationflags'],
                             subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
            self.assertEqual(ssh_kw['creationflags'], guest._no_window().no_window_flags())
            for kwargs in (holder_kw, ssh_kw):
                self.assertFalse(kwargs['creationflags'] & subprocess.DETACHED_PROCESS)
                self.assertFalse(kwargs['creationflags'] & subprocess.CREATE_NEW_CONSOLE)
        self.assertEqual((holder_kw['stdin'], ssh_kw['stdin']), (subprocess.DEVNULL,) * 2)

    def test_write_json_new_is_whole_and_exclusive(self):
        _, idir = self.instance()
        path = idir / 'x.json'
        guest.write_json_new(path, {'a': 1})
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'a': 1})
        with self.assertRaises(FileExistsError):
            guest.write_json_new(path, {'a': 2})
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'a': 1})
        self.assertEqual(sorted(p.name for p in idir.iterdir()), ['launch.json', 'x.json'])

    def test_read_line_within(self):
        self.assertEqual(guest.read_line_within(io.BytesIO(b'one\ntwo\n'), 5), b'one\n')
        blocked = threading.Event()

        class Never:
            def readline(self):
                blocked.wait(5)
                return b''
        self.assertIsNone(guest.read_line_within(Never(), 0.05))
        blocked.set()


class ForwardCommand(ProcessLedger, ForwardBase):
    """inference_forward: its refusals and its decisions, the holder in a thread of this process
    and a fake ssh process."""
    category = 'integration'

    def setUp(self):
        self.threads = []
        self.addCleanup(self.join_holders)
        self.ledger()
        patcher = mock.patch.object(guest, 'running_process', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def join_holders(self):
        for thread, _ in self.threads:
            thread.join(30)

    def start(self, name, mode='hold', broker=None, port=None, ceiling=None):
        profile = PROFILE
        if ceiling is not None:
            profile = json.loads(json.dumps(PROFILE))
            profile['network']['inference_composition']['forward_session']['establish_ceiling_s'] = \
                ceiling
        ctx = types.SimpleNamespace(profile=profile, instance_dir=self.ctx.instance_dir)
        with mock.patch.dict(os.environ, {'AIEH_TEST_FAKE_SSH': mode}):
            return guest.inference_forward(ctx, name, 'start', port, broker or FakeBroker(),
                                           threaded_spawn(self.threads), FakeSsh(self.script))

    def test_refused_for_an_instance_without_the_composition(self):
        launch = dict(LAUNCH)
        del launch['inference']
        name, _ = self.instance(launch)
        for action in guest.FORWARD_ACTIONS:
            with self.assertRaises(guest.Refused) as cm:
                guest.inference_forward(self.ctx, name, action, broker=FakeBroker())
            self.assertIn('--inference', str(cm.exception))
        with self.assertRaises(guest.Refused) as cm:
            guest.inference_forward(self.ctx, 'inst-absent', 'status')
        self.assertIn('no such instance', str(cm.exception))
        name, _ = self.instance()
        with self.assertRaises(guest.Refused) as cm:
            guest.inference_forward(self.ctx, name, 'restart', broker=FakeBroker())
        self.assertIn('--action must be one of', str(cm.exception))
        bare = json.loads(json.dumps(PROFILE))
        bare['network']['inference_composition']['forward_session']['record'] = 'C:/x.json'
        with self.assertRaises(guest.Refused) as cm:
            guest.inference_forward(types.SimpleNamespace(profile=bare, instance_dir=self.ctx.instance_dir),
                                    name, 'status')
        self.assertIn('no forward-session record', str(cm.exception))

    def test_broker_port_and_readiness_refusals(self):
        name, idir = self.instance()
        for port, code in ((18431, 'CONTROL_PORT_REFUSED'), (18433, 'FORWARD_PORT_REFUSED')):
            with self.assertRaises(guest.Refused) as cm:
                self.start(name, port=port)
            self.assertEqual(cm.exception.detail, {'code': code})
        for broker in (FakeBroker(inference=19999), FakeBroker(refuse='down')):
            with self.assertRaises(guest.Refused) as cm:
                self.start(name, broker=broker)
            self.assertIn(cm.exception.code, ('BROKER_NOT_READY', 'BROKER'))
        with mock.patch.object(guest, 'running_process', return_value=None):
            with self.assertRaises(guest.Refused) as cm:
                self.start(name)
            self.assertEqual(cm.exception.code, 'NOT_RUNNING')
        self.assertFalse(self.record_path(idir).exists())
        self.assertEqual(self.threads, [])                  # nothing was started

    def test_start_status_idempotent_start_stop(self):
        name, idir = self.instance()
        out = self.start(name, port=18432)
        self.assertEqual((out['result'], out['existing'], out['replaced_stale']), ('held', False, None))
        session = out['session']
        self.assertEqual(sorted(session), sorted(SESSION['fields']))
        self.assertEqual(session['ports'], {'endpoint': {'address': '172.17.0.1', 'port': 8090},
                                            'broker': {'address': '127.0.0.1', 'port': 18432},
                                            'hostfwd': {'address': '127.0.0.1', 'port': 40001}})
        self.assertEqual(session['argv'][-3:], ['-R', '172.17.0.1:8090:127.0.0.1:18432',
                                                'agent@127.0.0.1'])
        self.assertEqual(json.loads(self.record_path(idir).read_text(encoding='utf-8')), session)
        self.assertTrue(Path(out['record']).is_file())
        status = guest.inference_forward(self.ctx, name, 'status')
        self.assertEqual((status['result'], status['session'], status['removed_stale']),
                         ('held', session, None))
        again = self.start(name)
        self.assertEqual((again['result'], again['existing'], again['session']), ('held', True, session))
        self.assertEqual(len(self.threads), 1)               # no second holder
        log = (idir / guest.FORWARD_LOG).read_text(encoding='utf-8')
        self.assertIn('forward established', log)
        self.assertIn('a non-debug line the holder keeps', log)
        self.assertNotIn('debug1', log)
        stopped = guest.inference_forward(self.ctx, name, 'stop')
        self.assertEqual(stopped['result'], 'stopped')
        self.join_holders()
        self.assertEqual(self.threads[0][1]['rc'], 0)
        self.assertFalse(self.record_path(idir).exists())
        self.assertIn('session ended', (idir / guest.FORWARD_LOG).read_text(encoding='utf-8'))
        status = guest.inference_forward(self.ctx, name, 'status')
        self.assertEqual((status['result'], status['session']), ('not-held', None))
        self.assertEqual(guest.inference_forward(self.ctx, name, 'stop')['result'], 'not-held')

    def test_a_dropped_session_leaves_no_record_and_a_stale_one_is_replaced(self):
        name, idir = self.instance()
        session = self.start(name)['session']
        handle = guest.WinProcess(session['pid'])
        try:
            handle.terminate()                         # the session drops (ssh ends)
            handle.wait(30)
        finally:
            handle.close()
        self.join_holders()
        self.assertFalse(self.record_path(idir).exists())
        # a stale record (its process gone): status removes it, start replaces it
        self.record_path(idir).write_text(json.dumps(dict(session, created_epoch=1.0)),
                                          encoding='utf-8')
        status = guest.inference_forward(self.ctx, name, 'status')
        self.assertEqual(status['result'], 'not-held')
        self.assertEqual(status['removed_stale']['why'], 'its ssh process is gone')
        self.assertFalse(self.record_path(idir).exists())
        self.record_path(idir).write_text(json.dumps(dict(session, created_epoch=1.0)),
                                          encoding='utf-8')
        out = self.start(name)
        self.assertEqual((out['result'], out['existing']), ('held', False))
        self.assertEqual(out['replaced_stale']['session']['pid'], session['pid'])
        self.assertNotEqual(out['session']['pid'], session['pid'])
        self.assertEqual(guest.inference_forward(self.ctx, name, 'stop')['result'], 'stopped')
        self.join_holders()
        self.assertFalse(self.record_path(idir).exists())

    def test_refused_forward_and_no_report_leave_no_record(self):
        name, idir = self.instance()
        with self.assertRaises(guest.Refused) as cm:
            self.start(name, mode='refuse')
        self.assertEqual(cm.exception.code, 'FORWARD_FAILED')
        self.assertEqual(cm.exception.detail['rc'], 255)
        self.assertIn('Error: remote port forwarding failed for listen port 8090',
                      cm.exception.detail['stderr'])
        self.assertFalse(self.record_path(idir).exists())
        with self.assertRaises(guest.Refused) as cm:
            self.start(name, mode='silent', ceiling=0.2)
        self.assertIn('no establishment within', cm.exception.detail['reason'])
        self.join_holders()
        self.assertEqual([box['rc'] for _, box in self.threads], [1, 1])
        self.assertFalse(self.record_path(idir).exists())
        self.assertIn('not established', (idir / guest.FORWARD_LOG).read_text(encoding='utf-8'))

        killed = []

        def mute(spec, cwd):
            return types.SimpleNamespace(stdout=io.BytesIO(b'garbage\n'),
                                         kill=lambda: killed.append('kill'))
        ctx = types.SimpleNamespace(profile=PROFILE, instance_dir=self.ctx.instance_dir)
        with self.assertRaises(guest.Refused) as cm:
            guest.inference_forward(ctx, name, 'start', None, FakeBroker(), mute, FakeSsh(self.script))
        self.assertIn('reported nothing', str(cm.exception))
        self.assertEqual(killed, ['kill'])

        def raced(spec, cwd):
            # another start won the record meanwhile
            self.record_path(idir).write_text(json.dumps(self.session()), encoding='utf-8')
            return types.SimpleNamespace(stdout=io.BytesIO(b'{"result": "already-held"}\n'),
                                         kill=lambda: killed.append('kill'))
        with mock.patch.object(guest, 'forward_process', return_value=mock.Mock()):
            out = guest.inference_forward(ctx, name, 'start', None, FakeBroker(), raced,
                                          FakeSsh(self.script))
        self.assertEqual((out['result'], out['existing'], out['session']),
                         ('held', True, self.session()))
        with mock.patch.object(guest, 'forward_process', return_value=None):
            with self.assertRaises(guest.Refused) as cm:
                guest.inference_forward(ctx, name, 'start', None, FakeBroker(), raced,
                                        FakeSsh(self.script))
            self.assertEqual(cm.exception.code, 'FORWARD_FAILED')
        self.assertEqual(killed, ['kill'])

    def test_the_holder_removes_only_its_own_record(self):
        """When its session ends, the holder leaves a record that names another ssh process, even one
        with its own holder id (from the mutation check)."""
        name, idir = self.instance()
        session = self.start(name)['session']
        other = dict(session, pid=session['pid'] + 4)
        self.record_path(idir).write_text(json.dumps(other), encoding='utf-8')
        handle = guest.WinProcess(session['pid'])
        try:
            handle.terminate()
            handle.wait(30)
        finally:
            handle.close()
        self.join_holders()
        self.assertEqual(json.loads(self.record_path(idir).read_text(encoding='utf-8')), other)
        self.record_path(idir).unlink()

    def test_the_holder_refuses_a_second_record(self):
        name, idir = self.instance()
        self.record_path(idir).write_text(json.dumps(self.session()), encoding='utf-8')
        spec = {'argv': guest.forward_argv(PROFILE, FakeSsh(self.script), 18432),
                'record': str(self.record_path(idir)), 'log': str(idir / guest.FORWARD_LOG),
                'instance': name, 'listen': '172.17.0.1:8090', 'connect': '127.0.0.1:18432',
                'ceiling': 30, 'ports': {}}
        out = io.StringIO()
        rc = guest.forward_hold(base64.b64encode(json.dumps(spec).encode()).decode(), out=out, pid=0)
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out.getvalue()), {'result': 'already-held'})
        self.assertEqual(json.loads(self.record_path(idir).read_text(encoding='utf-8')), self.session())

    def test_stop_without_a_holder_removes_the_record_itself(self):
        name, idir = self.instance()
        session = self.session()
        self.record_path(idir).write_text(json.dumps(session), encoding='utf-8')
        proc = mock.Mock()
        proc.wait.return_value = True
        with mock.patch.object(guest, 'forward_process', return_value=proc), \
                mock.patch.object(guest, 'WinProcess', side_effect=OSError(87, 'gone')):
            out = guest.inference_forward(self.ctx, name, 'stop')
        self.assertEqual((out['result'], out['record_removed_by']), ('stopped', 'stop'))
        proc.terminate.assert_called_once_with()
        self.assertFalse(self.record_path(idir).exists())
        self.record_path(idir).write_text(json.dumps(session), encoding='utf-8')
        proc.wait.return_value = False
        with mock.patch.object(guest, 'forward_process', return_value=proc), \
                mock.patch.object(guest, 'WinProcess', side_effect=OSError(87, 'gone')):
            with self.assertRaises(guest.Refused) as cm:
                guest.inference_forward(self.ctx, name, 'stop')
        self.assertEqual(cm.exception.code, 'STOP_FAILED')


class ForwardSpawned(ProcessLedger, ForwardBase):
    """The holder as the real process (forward_spawn), once: start, then stop."""
    category = 'integration'

    def test_spawned_holder(self):
        self.ledger()
        name, idir = self.instance()
        ctx = types.SimpleNamespace(profile=PROFILE, instance_dir=self.ctx.instance_dir)
        with mock.patch.object(guest, 'running_process', return_value=True):
            out = guest.inference_forward(ctx, name, 'start', None, FakeBroker(), None,
                                          FakeSsh(self.script))
        session = out['session']
        self.pids.update((session['pid'], session['holder_pid']))      # its own children
        self.assertEqual(out['result'], 'held')
        self.assertNotEqual(session['holder_pid'], os.getpid())
        self.assertTrue(guest.forward_state(PROFILE, idir)['held'])
        stopped = guest.inference_forward(ctx, name, 'stop')
        self.assertEqual((stopped['result'], stopped['record_removed_by']), ('stopped', 'holder'))
        self.assertFalse(self.record_path(idir).exists())


class RecreateAndDestroy(ForwardBase):
    """recreate carries the composition from the launch record; destroy ends a held forward."""

    def test_recreate_carries_the_composition(self):
        name, _ = self.instance()
        calls = []
        with mock.patch.object(guest, 'destroy', side_effect=lambda c, n: calls.append('destroy')), \
                mock.patch.object(guest, 'create', side_effect=lambda *a, **k: calls.append(k)):
            guest.recreate(self.ctx, name, provision=True)
            self.assertEqual(calls, ['destroy', {'provision': True, 'inference': True}])
            calls.clear()
            with self.assertRaises(guest.Refused) as cm:
                guest.recreate(self.ctx, name)               # never dropped silently
            self.assertIn('needs --provision', str(cm.exception))
            self.assertEqual(calls, [])                      # refused before destroy
            launch = dict(LAUNCH)
            del launch['inference']
            plain, _ = self.instance(launch)
            guest.recreate(self.ctx, plain, provision=True)
            guest.recreate(self.ctx, plain)
            guest.recreate(self.ctx, 'inst-absent', provision=True)
            self.assertEqual(calls, ['destroy', {'provision': True, 'inference': False}, 'destroy', {},
                                     'destroy', {'provision': True, 'inference': False}])
            calls.clear()
            broken, idir = self.instance()
            (idir / 'launch.json').write_text('{not json', encoding='utf-8')
            with self.assertRaises(guest.Refused) as cm:
                guest.recreate(self.ctx, broken, provision=True)
            self.assertIn('cannot read the launch record', str(cm.exception))
            (idir / 'launch.json').write_text('[]', encoding='utf-8')
            guest.recreate(self.ctx, broken, provision=True)
            self.assertEqual(calls, ['destroy', {'provision': True, 'inference': False}])

    def test_destroy_ends_a_held_forward(self):
        name, idir = self.instance()
        stopped = []
        state = {'held': True, 'session': {}, 'path': None, 'stale': None}
        with mock.patch.object(guest, 'forward_state', return_value=state), \
                mock.patch.object(guest, 'forward_stop',
                                  side_effect=lambda p, i, s: stopped.append(i) or {'result': 'stopped'}), \
                mock.patch.object(guest, 'running_process', return_value=None), \
                mock.patch.object(guest, 'reparse_points', return_value=[]):
            out = guest.destroy(self.ctx, name)
        self.assertEqual(stopped, [idir])
        self.assertEqual(out['inference_forward'], {'result': 'stopped'})
        self.assertEqual(out['result'], 'destroyed')


class TokenScriptAgainstTheBroker(unittest.TestCase):
    """The in-job request script (JOB_INFERENCE_TOKEN) as a process, against the real broker of
    integrations/inference on ephemeral 127.0.0.1 ports (a fixture store, a synthetic key, a fake
    upstream): the token on standard input is forwarded, refused once revoked through the
    dispatcher's control client, and a request without a token is refused by admission."""
    category = 'integration'

    @classmethod
    def setUpClass(cls):
        support = REPO / 'integrations' / 'inference' / 'tests' / 'broker_support.py'
        spec = importlib.util.spec_from_file_location('aieh_test_broker_support', support)
        cls.S = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.S)
        cls.upstream = cls.S.FakeUpstream('anthropic-messages')
        cls.addClassCleanup(cls.upstream.close)
        cls.rig = cls.S.Rig(cls.S.component({'anthropic-messages': cls.upstream.origin})).start()
        cls.addClassCleanup(cls.rig.close)
        cls.status = guest.inference_control().ControlClient(cls.rig.control).status()

    def request(self, token, family=None, model='syn-model-a'):
        family = family or next(f for f in self.status['families'] if f['id'] == 'anthropic-messages')
        spec = guest.inference_token_spec(PROFILE, family, model, token is not None)
        spec['endpoint'] = ['127.0.0.1', self.rig.inference]
        arg = base64.b64encode(json.dumps(spec).encode()).decode()
        proc = subprocess.run([sys.executable, '-I', '-', arg],
                              input=(guest.JOB_INFERENCE_TOKEN + '\n').encode(), capture_output=True,
                              timeout=60, creationflags=NO_WINDOW) \
            if token is None else self.run_with_token(arg, token)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if token:
            self.assertNotIn(token.encode(), proc.stdout)
        return guest._job_json(proc.stdout.decode())

    def run_with_token(self, arg, token):
        # as in the job: the script from a file, the token on its standard input
        script = Path(tempfile.mkdtemp(prefix='aieh-token-script-')) / 'aieh-job.py'
        self.addCleanup(guest.remove_tree, script.parent)
        script.write_text(guest.JOB_INFERENCE_TOKEN, encoding='utf-8')
        return subprocess.run([sys.executable, '-I', str(script), arg], input=(token + '\n').encode(),
                              capture_output=True, timeout=60, creationflags=NO_WINDOW)

    def test_forwarded_then_revoked_and_admission_without_a_token(self):
        issued = self.rig.issue(family='anthropic-messages', models=('syn-model-a',))
        token = issued['token']
        forwarded = self.request(token)
        self.assertEqual((forwarded['outcome'], forwarded['status'], forwarded['refusal'],
                          forwarded['token_in_answer']), ('answered', 200, None, False))
        self.assertEqual(self.upstream.requests[-1]['path'], '/v1/messages')
        self.assertIn(('x-api-key', self.S.KEY), self.upstream.requests[-1]['headers'])
        self.assertEqual(json.loads(self.upstream.requests[-1]['body'])['messages'][0]['content'],
                         guest.INFERENCE_PROBE_PROMPT)
        client = guest.inference_control().ControlClient(self.rig.control)
        fingerprint = guest.inference_control().token_fingerprint(token)
        self.assertEqual(client.revoke(fingerprint, 'attempt end', guest.INFERENCE_REVOKER)['state'],
                         'revoked')
        refused = self.request(token)
        self.assertEqual((refused['status'], refused['refusal']), (401, 'TOKEN_REVOKED'))
        login = self.request(None, {'routes': [{'method': 'GET', 'path': '/'}],
                                    'auth': {'header': 'authorization', 'scheme': None}}, None)
        self.assertEqual((login['status'], login['refusal']), (401, 'TOKEN_MISSING'))


class BrokerAccessAndForwardControl(unittest.TestCase):
    """The dispatcher's hold on the broker (its ports, its control client, the refusals) and the
    token step's hold on the forward session, without a broker or a process (from the mutation
    check)."""

    def test_broker_access(self):
        client = mock.Mock()
        client.status.return_value = {'listeners': {}}
        access = guest.BrokerAccess({'control_port': 18431, 'inference_port': 18432}, client)
        self.assertEqual(access.ports, BROKER_PORTS)
        self.assertIs(access.client, client)
        self.assertEqual(access.call('status'), {'listeners': {}})
        ic = guest.inference_control()
        client.grant.side_effect = ic.ControlError('GRANT_UNKNOWN', 'x', broker_code=True, status=404)
        with self.assertRaises(guest.Refused) as cm:
            access.call('grant', 'sha256:' + '0' * 16)
        self.assertEqual((cm.exception.code, cm.exception.detail), ('BROKER', {'code': 'GRANT_UNKNOWN',
                                                                              'status': 404}))
        own = guest.BrokerAccess({'control_port': 18431, 'inference_port': 18432})
        self.assertIsInstance(own.client, ic.ControlClient)
        self.assertEqual(own.client.port, 18431)
        for raw in (None, {'control_port': 18431}, {'control_port': 18431, 'inference_port': 18432,
                                                    'token': 'x'}):
            with self.assertRaises(guest.Refused) as cm:
                guest.BrokerAccess(raw, client)
            self.assertEqual(cm.exception.code, 'BROKER_CONFIG')
        with mock.patch.object(ic, 'managed_component', return_value=dict(BROKER_PORTS)) as managed:
            self.assertEqual(guest.BrokerAccess(client=client).ports, BROKER_PORTS)
        managed.assert_called_once_with()

    def test_forward_control(self):
        ctx = types.SimpleNamespace(profile=PROFILE, instance_dir=lambda name: Path('inst') / name)
        control = guest.ForwardControl(ctx, 'abc', 'ACCESS')
        with mock.patch.object(guest, 'forward_state', return_value={'held': True}) as state, \
                mock.patch.object(guest, 'inference_forward', side_effect=lambda *a, **k: (a, k)):
            self.assertEqual(control.status(), {'held': True})
            self.assertEqual(control.stop(), ((ctx, 'abc', 'stop'), {}))
            self.assertEqual(control.start(), ((ctx, 'abc', 'start'), {'broker': 'ACCESS'}))
        state.assert_called_once_with(PROFILE, Path('inst') / 'abc')


def tunnel_run_dir(test, port=18433, pid=None):
    """A run directory holding a provider-tunnel run record (a live pid: this process's) on PORT."""
    run = Path(tempfile.mkdtemp(prefix='aieh-tunnel-run-'))
    test.addCleanup(guest.remove_tree, run)
    pt = guest.provider_tunnel()
    pt.write_new(run / pt.RUN_NAME, {'format': pt.RUN_FORMAT, 'pid': os.getpid() if pid is None else pid,
                                     'address': '127.0.0.1', 'port': port, 'log': 'x'})
    return run


class NativeForward(ProcessLedger, ForwardBase):
    """E-05.10 (decision 0023 section 4.3): the forward holder targets the provider tunnel's port only for a
    profile that declares the native profile (its provider-tunnel endpoint), started with --execution-profile
    native; every other port is still FORWARD_PORT_REFUSED, and the brokered start is unchanged."""
    category = 'integration'

    def setUp(self):
        self.threads = []
        self.addCleanup(lambda: [t.join(30) for t, _ in self.threads])
        self.ledger()
        patcher = mock.patch.object(guest, 'running_process', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def start(self, name, profile=PROFILE, port=None, tunnel=None, broker=None):
        ctx = types.SimpleNamespace(profile=profile, instance_dir=self.ctx.instance_dir)
        with mock.patch.dict(os.environ, {'AIEH_TEST_FAKE_SSH': 'hold'}):
            return guest.inference_forward(ctx, name, 'start', port, broker, threaded_spawn(self.threads),
                                           FakeSsh(self.script), execution_profile='native',
                                           tunnel=tunnel or guest.TunnelAccess(profile, tunnel_run_dir(self)))

    def test_native_targets_the_tunnels_declared_port(self):
        name, idir = self.instance()
        broker = FakeBroker()
        with mock.patch.object(guest, 'BrokerAccess', side_effect=AssertionError('the broker is not read')):
            out = self.start(name, broker=broker)
        self.assertEqual((out['result'], out['existing']), ('held', False))
        session = out['session']
        self.assertEqual(sorted(session), sorted(SESSION['fields']))
        self.assertEqual(session['ports'], {'endpoint': {'address': '172.17.0.1', 'port': 8090},
                                            'tunnel': {'address': '127.0.0.1', 'port': 18433},
                                            'hostfwd': {'address': '127.0.0.1', 'port': 40001}})
        self.assertEqual(session['argv'][-3:], ['-R', '172.17.0.1:8090:127.0.0.1:18433', 'agent@127.0.0.1'])
        self.assertEqual(guest.forward_target(session), guest.TUNNEL_TARGET)
        self.assertEqual(broker.calls, [])                    # the broker is never asked
        again = self.start(name, port=18433)
        self.assertEqual((again['result'], again['existing']), ('held', True))
        with self.assertRaises(guest.Refused) as cm:          # one forward at a time
            guest.inference_forward(self.ctx, name, 'start', broker=FakeBroker())
        self.assertEqual(cm.exception.detail, {'code': 'FORWARD_TARGET_DIFFERS'})
        self.assertEqual(guest.inference_forward(self.ctx, name, 'stop')['result'], 'stopped')

    def test_native_refuses_every_other_port(self):
        name, idir = self.instance()
        for port in (18432, 18431, 8090, 443, 18434):
            with self.assertRaises(guest.Refused) as cm:
                self.start(name, port=port)
            self.assertEqual(cm.exception.detail, {'code': 'FORWARD_PORT_REFUSED'}, port)
        self.assertFalse(self.record_path(idir).exists())
        self.assertEqual(self.threads, [])

    def test_native_only_for_a_profile_that_declares_it(self):
        name, idir = self.instance()
        undeclared = json.loads(json.dumps(PROFILE))
        undeclared['network']['endpoints'] = [e for e in undeclared['network']['endpoints']
                                              if e['class'] != 'provider-tunnel']
        ci = json.loads((REPO / 'profiles' / 'strong-windows-qemu-whpx-ci' / 'profile.json').read_text(
            encoding='utf-8'))
        for profile in (undeclared, dict(PROFILE, network=dict(PROFILE['network'], endpoints=ci['network']['endpoints']))):
            with self.assertRaises(guest.Refused) as cm:
                guest.inference_forward(types.SimpleNamespace(profile=profile, instance_dir=self.ctx.instance_dir),
                                        name, 'start', execution_profile='native',
                                        spawn=threaded_spawn(self.threads), ssh=FakeSsh(self.script))
            self.assertEqual(cm.exception.code, 'NATIVE_PROFILE_UNDECLARED')
        with self.assertRaises(guest.Refused) as cm:
            guest.inference_forward(self.ctx, name, 'start', execution_profile='other')
        self.assertIn('--execution-profile must be one of', str(cm.exception))
        self.assertEqual(self.threads, [])

    def test_native_needs_the_tunnel_running_first(self):
        name, idir = self.instance()
        empty = Path(tempfile.mkdtemp(prefix='aieh-tunnel-run-'))
        self.addCleanup(guest.remove_tree, empty)
        dead = 2 ** 31 - 7                                     # no such process
        for run in (empty, tunnel_run_dir(self, port=18499), tunnel_run_dir(self, pid=dead)):
            with self.assertRaises(guest.Refused) as cm:
                self.start(name, tunnel=guest.TunnelAccess(PROFILE, run))
            self.assertEqual(cm.exception.code, 'TUNNEL_NOT_READY', run)
        self.assertFalse(self.record_path(idir).exists())
        self.assertEqual(self.threads, [])

    def test_brokered_is_unchanged_and_refuses_the_tunnels_port(self):
        name, idir = self.instance()
        ctx = types.SimpleNamespace(profile=PROFILE, instance_dir=self.ctx.instance_dir)
        with self.assertRaises(guest.Refused) as cm:
            guest.inference_forward(ctx, name, 'start', 18433, FakeBroker(), threaded_spawn(self.threads),
                                    FakeSsh(self.script))
        self.assertEqual(cm.exception.detail, {'code': 'FORWARD_PORT_REFUSED'})
        with self.assertRaises(guest.Refused) as cm:
            guest.inference_forward(ctx, name, 'start', None, FakeBroker(inference=19999),
                                    threaded_spawn(self.threads), FakeSsh(self.script))
        self.assertEqual(cm.exception.code, 'BROKER_NOT_READY')
        out = guest.inference_forward(ctx, name, 'start', None, FakeBroker(), threaded_spawn(self.threads),
                                      FakeSsh(self.script))
        self.assertIn('broker', out['session']['ports'])
        self.assertEqual(guest.forward_target(out['session']), 'broker')
        with self.assertRaises(guest.Refused) as cm:          # one forward at a time
            self.start(name)
        self.assertEqual(cm.exception.detail, {'code': 'FORWARD_TARGET_DIFFERS'})
        guest.inference_forward(self.ctx, name, 'stop')


class JobScriptAgainstTheTunnel(unittest.TestCase):
    """The sweep's tunnel rows (the job script, run here under this interpreter) against the real tunnel in this
    process, through 127.0.0.1: every refused row gives the outcome and the code TUNNEL_MATRIX expects, from a real
    TLS stack's ClientHello where one is sent. The admitted row needs the provider's certificate: live only."""
    category = 'integration'

    def test_refused_rows(self):
        pt = guest.provider_tunnel()
        connects = []
        tunnel = pt.Tunnel(0, pt.MemoryLog(), resolve=lambda h, p: connects.append((h, p)) or [],
                           connect=lambda *a: (_ for _ in ()).throw(AssertionError('no outbound connection')))
        address = tunnel.start()
        self.addCleanup(tunnel.stop, 'test')
        rows = [m for m in guest.TUNNEL_MATRIX if m[0] != guest.TUNNEL_ORIGIN_WHAT]
        spec = {'items': [['tunnel', 'tcp', '127.0.0.1', address[1], what] for what, *_ in rows],
                'tunnel': {what: {'connect': c, 'sni': s} for what, c, s, _, _ in rows}, 'timeout': 10}
        arg = base64.b64encode(json.dumps(spec).encode('utf-8')).decode('ascii')
        out = subprocess.run([sys.executable, '-I', '-c', guest.JOB_INFERENCE_SWEEP, arg], capture_output=True,
                             text=True, timeout=120, creationflags=NO_WINDOW)
        self.assertEqual(out.returncode, 0, out.stderr)
        line = next(x for x in out.stdout.splitlines() if x.startswith('AIEH-JOB-JSON '))
        results = json.loads(line[len('AIEH-JOB-JSON '):])['results']
        for row in results:
            want, code = guest.TUNNEL_EXPECTED[row['what']]
            self.assertEqual((row['outcome'], row['refusal']), (want, code), row)
        self.assertEqual(len(results), len(rows))
        # the mismatched and the absent server name reached the hello check (Python's own ClientHello)
        reasons = sorted(x['reason'] for x in tunnel.log.lines if x['event'] == 'connection')
        self.assertIn('TUNNEL_SNI_MISMATCH', reasons)
        self.assertIn('TUNNEL_SNI_ABSENT', reasons)
        self.assertEqual(connects, [])


class ForwardCli(ForwardBase):
    """The command line reaches inference_forward and the holder."""

    def test_cli(self):
        with mock.patch.object(guest, 'inference_forward', return_value={'result': 'held'}) as fn, \
                mock.patch('sys.stdout', new_callable=io.StringIO):
            rc = guest.main(['inference-forward', '--profile', str(PROFILE_DIR), '--state-dir',
                             str(self.state), '--name', 'inst-x', '--action', 'start',
                             '--broker-port', '18432'])
        self.assertEqual(rc, 0)
        self.assertEqual(fn.call_args[0][1:], ('inst-x', 'start', 18432))
        self.assertEqual(fn.call_args[1], {'execution_profile': 'brokered'})
        with mock.patch.object(guest, 'inference_forward', return_value={'result': 'held'}) as fn, \
                mock.patch('sys.stdout', new_callable=io.StringIO):
            rc = guest.main(['inference-forward', '--profile', str(PROFILE_DIR), '--state-dir',
                             str(self.state), '--name', 'inst-x', '--action', 'start',
                             '--execution-profile', 'native'])
        self.assertEqual((rc, fn.call_args[0][1:], fn.call_args[1]),
                         (0, ('inst-x', 'start', None), {'execution_profile': 'native'}))
        with mock.patch.object(guest, 'forward_hold', return_value=0) as fn:
            self.assertEqual(guest.main(['inference-forward-hold', '--spec', 'abc']), 0)
        fn.assert_called_once_with('abc')


if __name__ == '__main__':
    unittest.main()
