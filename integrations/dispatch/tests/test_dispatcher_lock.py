"""Tests for the dispatcher lock (plan leaf E-01.4.2, slice 5a: ``dispatcher_lock.py`` and its held regions in
``dispatch``, ``run_attempt`` and ``send_message``), offline.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_dispatcher_lock.py -v

Shown here, against slice 5a's falsifiable completion conditions (the restart-recovery design, section 2):

1. with the lock held elsewhere (a second handle, another thread, a real second process): ``dispatch`` raises
   DISPATCHER_BUSY with nothing reserved, the store's canonical dump unchanged and zero transport calls;
   ``run_attempt`` before any call; ``send_message`` with no journal reserved (``Busy``);
2. a holder process killed after its ``dispatched`` transition leaves the lock free once its exit is observed (the
   test waits on the process, never on a duration) (``KilledHolder``);
3. a BaseException in the transport during the create, and during the message, leaves the lock free and the row
   ``dispatched`` (``Interrupted``); the lock is held at the create and the message and not while the turn is
   waited for (``Windows``);
4. I-1 and I-2 as a property of production code: the call sites (``StaticCensus``) and a recording wrapper around the
   store under the dispatch suite's modules that reach them (``DynamicCensus``, ``lock_census_runner.py`` in a
   process of its own), each with a negative control;
5. the lock file is beside the store, never in the checkout, 0 bytes, never deleted; a backup and a restore with it
   present (``LockFile``);
6. fail closed: a lock file that cannot be opened or created is DISPATCHER_LOCK_UNAVAILABLE, never a pass and never
   busy (``FailClosed``).

G12, the operating-system facts the lock rests on, on this host (``OperatingSystemFacts``): a second handle in the
same process is refused; a killed holder's lock is free once its exit is observed; an orphaned child does not keep
it (on Windows, also with the handle inheritable and ``close_fds=False``).
"""
from pathlib import Path
import ast
import contextlib
import dataclasses
import errno
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BASE_PYTHON = getattr(sys, '_base_executable', sys.executable)
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
WAIT_CEILING_S = 60          # bounds a hang; a holder answers in well under a second
CENSUS_CEILING_S = 600       # bounds the census run's hang, never an estimate of it


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


tar = _load('test_attempt_run', HERE / 'test_attempt_run.py')
te, di, AE, store_mod, AR = tar.te, tar.di, tar.AE, tar.store_mod, tar.AR
cc = te.cc
DL = di._dispatcher_lock_module()
HOLDER = HERE / 'lock_holder.py'
RUNNER = HERE / 'lock_census_runner.py'
# The dispatch suite's modules that reach the write-ahead sites (the create's, the message's), run under the census.
CENSUS_MODULES = ('test_conversation_create.py', 'test_reconcile.py', 'test_attempt_run.py:Turn,Run',
                  'test_d1_stage_secrets.py', 'test_restart_recovery.py')


def setUpModule():
    tar.setUpModule()


def tearDownModule():
    with contextlib.suppress(FileNotFoundError):
        tar.tearDownModule()


# ---------------------------------------------------------------------------
# Holders elsewhere

class Holder:
    """lock_holder.py in a process of its own, under the base interpreter (no venv launcher between the test and the
    holder: the pid killed is the holder's)."""

    def __init__(self, test, command, store_path, *args):
        self.proc = subprocess.Popen([BASE_PYTHON, '-I', '-B', str(HOLDER), command, str(store_path), *args],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     creationflags=NO_WINDOW)
        test.addCleanup(self.stop)
        line = self.proc.stdout.readline()          # the holder's own signal that it holds the lock
        if not line:
            self.proc.wait(timeout=WAIT_CEILING_S)
            raise AssertionError(f'the holder did not take the lock: {self.proc.stderr.read()!r}')
        self.info = json.loads(line)
        test.assertEqual(self.info['pid'], self.proc.pid, 'the holder is the process started')

    def kill(self):
        self.proc.kill()
        return self.proc.wait(timeout=WAIT_CEILING_S)       # its exit, observed

    def stop(self):
        if self.proc.poll() is None:
            with contextlib.suppress(OSError):
                self.proc.stdin.close()
            try:
                self.proc.wait(timeout=WAIT_CEILING_S)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=WAIT_CEILING_S)
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            with contextlib.suppress(OSError):
                stream.close()


@contextlib.contextmanager
def held_by_handle(store_path):
    """The lock held by a second handle of this process (the operating system's refusal; no registry entry)."""
    fd = DL.open_handle(DL.lock_path(store_path))
    DL.lock_handle(fd)
    try:
        yield
    finally:
        DL.unlock_handle(fd)


@contextlib.contextmanager
def held_by_thread(store_path):
    """The lock taken through the module by another thread of this process, held for the block."""
    taken, done, errors = threading.Event(), threading.Event(), []

    def hold():
        try:
            with DL.held(store_path):
                taken.set()
                done.wait()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            errors.append(exc)
            taken.set()
    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    taken.wait()
    try:
        if errors:
            raise errors[0]
        yield
    finally:
        done.set()
        thread.join()


def free_elsewhere(store_path) -> bool:
    """Whether another thread could take the lock now (taken and released at once in a thread of its own)."""
    out = []

    def probe():
        try:
            with DL.held(store_path):
                out.append(True)
        except DL.Busy:
            out.append(False)
    thread = threading.Thread(target=probe)
    thread.start()
    thread.join()
    return out[0]


def alive(pid) -> bool:
    """Whether the process PID still runs (Windows: its handle not signalled; elsewhere: signal 0)."""
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x00100000 | 0x1000, False, pid)     # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 0x102     # WAIT_TIMEOUT
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def end_child(pid):
    """End the orphaned child PID and wait on its exit (Windows: its handle; the wait bounded by the ceiling)."""
    if os.name != 'nt':
        return
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x00100000 | 0x0001, False, pid)          # SYNCHRONIZE | TERMINATE
    if not handle:
        return
    try:
        kernel.TerminateProcess(ctypes.c_void_p(handle), 1)
        kernel.WaitForSingleObject(ctypes.c_void_p(handle), WAIT_CEILING_S * 1000)
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


class TempStore(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.dir = Path(tempfile.mkdtemp(prefix='aieh-dispatcher-lock-'))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = self.dir / 'integration.sqlite'


# ---------------------------------------------------------------------------
# G12: the operating system's facts, on this host

class OperatingSystemFacts(TempStore):
    category = 'integration'

    def test_a_second_handle_in_the_same_process_is_refused(self):
        lock = DL.lock_path(self.path)
        first, second = DL.open_handle(lock), DL.open_handle(lock)
        try:
            DL.lock_handle(first)
            with self.assertRaises(OSError) as caught:
                DL.lock_handle(second)
            self.assertIn(caught.exception.errno, DL.BUSY_ERRNOS)
            with self.assertRaises(DL.Busy):          # the module's acquire meets the same refusal
                DL.acquire(self.path)
        finally:
            os.close(second)
            DL.unlock_handle(first)
        with DL.held(self.path):                       # released: the next acquire succeeds
            self.assertTrue(DL.held_by_this_thread(self.path))

    def test_a_killed_holders_lock_is_free_once_its_exit_is_observed(self):
        holder = Holder(self, 'hold', self.path)
        with self.assertRaises(DL.Busy):
            DL.acquire(self.path)
        holder.kill()                                  # waited on: its exit is observed, no duration is guessed
        DL.acquire(self.path)                          # the first attempt after the exit succeeds
        DL.release(self.path)

    @unittest.skipUnless(os.name == 'nt', 'measured on Windows only: elsewhere flock belongs to the open file '
                                          'description, and a child that inherited the descriptor keeps it')
    def test_an_orphaned_child_does_not_keep_it_even_with_the_handle_inheritable(self):
        holder = Holder(self, 'orphan', self.path)
        child = holder.info['child']
        self.addCleanup(end_child, child)
        self.assertTrue(holder.info['inheritable'])
        with self.assertRaises(DL.Busy):
            DL.acquire(self.path)
        holder.proc.kill()
        holder.proc.wait(timeout=WAIT_CEILING_S)
        self.assertTrue(alive(child), 'the child outlives its parent, holding the inherited handle')
        DL.acquire(self.path)
        DL.release(self.path)
        self.assertTrue(alive(child), 'free while the child that inherited the handle still runs')


# ---------------------------------------------------------------------------
# The primitive

class Primitive(TempStore):
    category = 'unit'

    def test_it_is_re_entrant_in_the_holding_thread_and_refuses_another(self):
        with DL.held(self.path):
            with DL.held(self.path):
                self.assertTrue(DL.held_by_this_thread(self.path))
                self.assertFalse(free_elsewhere(self.path))
            self.assertTrue(DL.held_by_this_thread(self.path), 'still held after the inner release')
            self.assertFalse(free_elsewhere(self.path))
        self.assertFalse(DL.held_by_this_thread(self.path))
        self.assertTrue(free_elsewhere(self.path))

    def test_another_thread_is_refused_like_another_process(self):
        with held_by_thread(self.path):
            with self.assertRaises(DL.Busy) as caught:
                DL.acquire(self.path)
            self.assertEqual(caught.exception.code, 'DISPATCHER_BUSY')
            self.assertFalse(DL.held_by_this_thread(self.path))
        DL.acquire(self.path)
        DL.release(self.path)

    def test_a_release_without_the_lock_is_an_error(self):
        with self.assertRaises(RuntimeError):
            DL.release(self.path)
        with held_by_thread(self.path), self.assertRaises(RuntimeError):
            DL.release(self.path)

    def test_the_refusals_are_dispatch_refusals(self):
        self.assertEqual((DL.Busy.code, DL.Unavailable.code), ('DISPATCHER_BUSY', 'DISPATCHER_LOCK_UNAVAILABLE'))
        for code in ('DISPATCHER_BUSY', 'DISPATCHER_LOCK_UNAVAILABLE'):
            self.assertIn(code, di.REFUSALS)
        store = mock.Mock(path=self.path)
        with held_by_handle(self.path), self.assertRaises(di.DispatchRefused) as caught:
            with di.dispatcher_lock(store):
                self.fail('the block runs only with the lock')
        self.assertEqual(caught.exception.code, 'DISPATCHER_BUSY')
        with di.dispatcher_lock(store):
            self.assertTrue(DL.held_by_this_thread(self.path))
        self.assertFalse(DL.held_by_this_thread(self.path))


class FailClosed(TempStore):
    """Condition 6: a lock file that cannot be opened or created is a refusal of its own, never a pass, never busy."""
    category = 'unit'

    def assertUnavailable(self, store_path):
        with self.assertRaises(DL.Unavailable) as caught:
            DL.acquire(store_path)
        self.assertNotIsInstance(caught.exception, DL.Busy)
        self.assertFalse(DL.held_by_this_thread(store_path))
        with self.assertRaises(di.DispatchRefused) as refused, di.dispatcher_lock(mock.Mock(path=store_path)):
            self.fail('never a pass')
        self.assertEqual(refused.exception.code, 'DISPATCHER_LOCK_UNAVAILABLE')

    def test_a_lock_file_that_cannot_be_opened_or_created_is_unavailable(self):
        self.assertUnavailable(self.dir / 'missing-directory' / 'integration.sqlite')     # cannot be created
        DL.lock_path(self.path).mkdir()                                                   # cannot be opened
        self.assertUnavailable(self.path)

    def test_a_store_without_a_file_is_unavailable(self):
        for path in (None, 7, ''):
            with self.subTest(path=path), self.assertRaises(DL.Unavailable):
                DL.acquire(path)
        with self.assertRaises(di.DispatchRefused) as refused, di.dispatcher_lock(object()):
            self.fail('never a pass')
        self.assertEqual(refused.exception.code, 'DISPATCHER_LOCK_UNAVAILABLE')

    def test_a_lock_that_fails_otherwise_is_unavailable_not_busy(self):
        with mock.patch.object(DL, 'lock_handle', side_effect=OSError(errno.EBADF, 'bad handle')):
            self.assertUnavailable(self.path)
        with mock.patch.object(DL, 'lock_handle', side_effect=OSError(errno.EACCES, 'held')), \
                self.assertRaises(DL.Busy):
            DL.acquire(self.path)


# ---------------------------------------------------------------------------
# The held regions, on the native D1 fixture

class Counting:
    """The transport, counting every call (whatever the server then answers)."""

    def __init__(self, server):
        self.server, self.calls = server, []

    def __call__(self, method, path, body, **kwargs):
        self.calls.append((method, path))
        return self.server(method, path, body, **kwargs)


class Attempt(tar.Scratch):
    category = 'integration'

    def setUp(self):
        super().setUp()
        self.fixture = tar.attempt_fixture(self)
        self.server = tar.RunServer(self)
        self.fixture.server = self.server
        self.store = self.fixture.store
        resolved = self.fixture.resolve_d1(self.fixture.manifest)
        self.base, _ = self.demo(work_id=resolved.work_id, change=AR._design(resolved)['change'],
                                 repository=resolved.repository)
        self.base = dataclasses.replace(self.base, design_commit=AR._design(resolved)['commit'])

    def agent_edits(self, workspace):
        pass

    def dispatch(self, transport=None):
        return self.fixture.run_native(transport or self.server, manifest=self.fixture.manifest)

    def confirmed(self):
        result = self.dispatch()
        self.server.set(result.conversation_id, runtime=AR.RUNTIME_SERVING)
        self.server.log.clear()
        return result

    def run_attempt(self, key, transport=None, **kwargs):
        return AR.run_attempt(self.store, key, transport=transport or self.server, base=self.base, actor='5a-test',
                              inspect=lambda cid: (), pull=lambda name: self.fail('no pull expected'),
                              ceiling_s=0, clock=lambda: 0.0, wait=lambda s: None,
                              read_artifact=self.fixture.read_artifact, **kwargs)

    def client(self, key, transport):
        return AE._client(di.stored_inputs(self.store, key, state='confirmed'), transport)(self.fixture.read_artifact)

    def turn(self, key):
        return self.store.get(AR.TURN_KEY.format(attempt_id=store_mod.attempt_id_for(key)))


class Busy(Attempt):
    """Condition 1, with the lock held by a second handle, another thread and a real second process."""

    def elsewhere(self):
        path = self.store.path
        return {'a second handle': lambda: held_by_handle(path), 'another thread': lambda: held_by_thread(path),
                'another process': lambda: _process(self, path)}

    def assertBusy(self, act):
        with self.assertRaises(di.DispatchRefused) as caught:
            act()
        self.assertEqual(caught.exception.code, 'DISPATCHER_BUSY')

    def test_dispatch_is_busy_with_nothing_reserved_and_no_call(self):
        for name, holding in self.elsewhere().items():
            with self.subTest(name):
                dump, transport = self.store.canonical_dump(), Counting(self.server)
                with holding():
                    self.assertBusy(lambda: self.dispatch(transport))
                self.assertEqual(self.store.canonical_dump(), dump)
                self.assertEqual((transport.calls, self.store.attempts()), ([], []))
        self.assertEqual(self.dispatch().created, True)        # free again: the dispatch runs

    def test_run_attempt_is_busy_before_any_call(self):
        result = self.confirmed()
        for name, holding in self.elsewhere().items():
            with self.subTest(name):
                dump, transport = self.store.canonical_dump(), Counting(self.server)
                with holding():
                    self.assertBusy(lambda: self.run_attempt(result.operation_key, transport))
                self.assertEqual((transport.calls, self.store.canonical_dump()), ([], dump))
                self.assertIsNone(self.turn(result.operation_key))

    def test_send_message_is_busy_with_no_journal_reserved(self):
        result = self.confirmed()
        transport = Counting(self.server)
        client = self.client(result.operation_key, transport)
        for name, holding in self.elsewhere().items():
            with self.subTest(name):
                dump = self.store.canonical_dump()
                with holding():
                    self.assertBusy(lambda: AR.send_message(self.store, result.operation_key, client, self.base,
                                                            'the message', actor='5a-test'))
                self.assertEqual((transport.calls, self.store.canonical_dump()), ([], dump))
                self.assertIsNone(self.turn(result.operation_key))


@contextlib.contextmanager
def _process(test, path):
    holder = Holder(test, 'hold', path)
    try:
        yield holder
    finally:
        holder.stop()


class Windows(Attempt):
    """The held regions' extent: held at the create and the message (and the calls before them), not while the turn
    is waited for, and never after the act."""

    def test_the_lock_is_held_across_the_write_ahead_windows_only(self):
        seen = []

        def transport(method, path, body, **kwargs):
            seen.append((method, path.rsplit('/', 1)[-1], DL.held_by_this_thread(self.store.path)))
            return self.server(method, path, body, **kwargs)
        result = self.dispatch(transport)
        self.assertEqual(seen, [('GET', 'server_info', True), ('POST', 'conversations', True)])
        self.assertFalse(DL.held_by_this_thread(self.store.path))
        self.server.set(result.conversation_id, runtime=AR.RUNTIME_SERVING)
        self.server.after_message = 'running'
        seen.clear()
        with self.assertRaises(di.DispatchRefused) as caught:
            self.run_attempt(result.operation_key, transport)
        self.assertEqual(caught.exception.code, 'TURN_CEILING')
        message = next(n for n, (m, tail, _) in enumerate(seen) if (m, tail) == ('POST', 'events'))
        self.assertTrue(all(held for _, _, held in seen[:message + 1]), seen)      # inspect, SEED, the message
        self.assertTrue(seen[message + 1:] and not any(held for _, _, held in seen[message + 1:]), seen)  # the wait
        self.assertFalse(DL.held_by_this_thread(self.store.path))
        self.assertTrue(free_elsewhere(self.store.path))


class Interrupted(Attempt):
    """Condition 3: a BaseException in the transport leaves the lock free and the row dispatched."""

    def test_a_base_exception_during_the_create_leaves_the_lock_free_and_the_attempt_dispatched(self):
        def transport(method, path, body, **kwargs):
            if (method, path) == cc.CREATE:
                raise te.Crash('the dispatcher dies at the create')
            return self.server(method, path, body, **kwargs)
        with self.assertRaises(te.Crash):
            self.dispatch(transport)
        (attempt,) = self.store.attempts()
        self.assertEqual(attempt.state, 'dispatched')
        self.assertFalse(DL.held_by_this_thread(self.store.path))
        self.assertTrue(free_elsewhere(self.store.path))

    def test_a_base_exception_during_the_message_leaves_the_lock_free_and_the_journal_dispatched(self):
        result = self.confirmed()

        def transport(method, path, body, **kwargs):
            if method == 'POST' and path.endswith('/events'):
                raise te.Crash('the dispatcher dies at the message')
            return self.server(method, path, body, **kwargs)
        with self.assertRaises(te.Crash):
            self.run_attempt(result.operation_key, transport)
        self.assertEqual(self.turn(result.operation_key).state, 'dispatched')
        self.assertFalse(DL.held_by_this_thread(self.store.path))
        self.assertTrue(free_elsewhere(self.store.path))

    def test_a_base_exception_during_a_direct_send_leaves_the_lock_free_and_the_journal_dispatched(self):
        result = self.confirmed()

        def transport(method, path, body, **kwargs):
            if method == 'POST' and path.endswith('/events'):
                raise te.Crash('the dispatcher dies at the message')
            return self.server(method, path, body, **kwargs)
        with self.assertRaises(te.Crash):
            AR.send_message(self.store, result.operation_key, self.client(result.operation_key, transport),
                            self.base, 'the message', actor='5a-test')
        self.assertEqual(self.turn(result.operation_key).state, 'dispatched')
        self.assertFalse(DL.held_by_this_thread(self.store.path))
        self.assertTrue(free_elsewhere(self.store.path))


class KilledHolder(Attempt):
    """Condition 2: a holder process killed after its dispatched transition leaves the lock free once its exit is
    observed (waited on, never a duration); the row stays dispatched."""

    def test_a_holder_killed_after_its_dispatched_transition_leaves_the_lock_free(self):
        resolved = self.fixture.resolve_d1(self.fixture.manifest)
        identity = dataclasses.asdict(resolved.attempt_identity())
        holder = Holder(self, 'dispatched', self.store.path, json.dumps(identity))
        key = holder.info['dispatched']
        self.assertEqual(self.store.get(key).state, 'dispatched')
        with self.assertRaises(DL.Busy):
            DL.acquire(self.store.path)
        holder.kill()
        DL.acquire(self.store.path)
        DL.release(self.store.path)
        self.assertEqual(self.store.get(key).state, 'dispatched')


class LockFile(Attempt):
    """Condition 5."""

    def test_the_lock_file_is_beside_the_store_empty_and_kept(self):
        self.dispatch()
        lock = DL.lock_path(self.store.path)
        self.assertEqual((lock.parent, lock.name), (Path(self.store.path).parent,
                                                    Path(self.store.path).name + '.dispatcher.lock'))
        self.assertTrue(lock.is_file())
        self.assertEqual(lock.stat().st_size, 0)
        self.assertFalse(lock.resolve().is_relative_to(REPO), 'never in the checkout')
        with self.assertRaises(di.DispatchRefused):      # another act on the store: the same file again
            self.dispatch()
        self.assertTrue(lock.is_file(), 'never deleted')
        self.assertEqual(lock.stat().st_size, 0)

    def test_a_backup_and_a_restore_with_the_lock_file_present(self):
        self.dispatch()
        path = Path(self.store.path)
        lock = DL.lock_path(path)
        with DL.held(path):
            manifest = self.store.backup(actor='owner')
            self.store.close()
            store_mod.restore_store(path, path.parent / 'backups' / (manifest['backup_file'] + '.manifest.json'),
                                    actor='owner')
        self.fixture.store = self.store = store_mod.open_store(path)
        self.addCleanup(self.store.close)
        self.assertEqual(len(self.store.open_epochs()), 1)
        self.assertTrue(lock.is_file())
        self.assertEqual(lock.stat().st_size, 0)
        self.assertNotIn(lock.name, [p.name for p in (path.parent / 'backups').rglob('*')])


# ---------------------------------------------------------------------------
# Condition 4: I-1 and I-2 as a property of production code

PASS_THROUGH = {('dispatch_inputs.py', '_mark'), ('attempt_end.py', '_mark_end'), ('restart_recovery.py', 'move')}
# Every site in integrations/dispatch/*.py that reserves a typed attempt or moves a row into dispatched, by
# (module, function, call, key expression): the class of the key and, for a typed attempt or a turn journal, the held
# region it lies in. At a34ce77 the typed and turn sites are one reserve_attempt and one transition in dispatch and one
# transition in send_message (the design's search); dispatch's are in _dispatch since slice 5a.
SITES = {
    ('dispatch_inputs.py', '_dispatch', 'reserve_attempt', None): 'typed attempt: dispatch\'s held region',
    ('dispatch_inputs.py', '_dispatch', '_mark', 'key'): 'typed attempt: dispatch\'s held region',
    ('attempt_run.py', 'send_message', '_mark', 'key'): 'turn journal: send_message\'s held region',
    ('attempt_end.py', 'end_interrupted_attempt', '_mark_end', 'key'): 'the end journal (END_KEY), twice',
    ('attempt_end.py', '_write_cause', '_mark', 'key'): 'the cause, end-cause and escalation receipts',
    ('attempt_end.py', 'record_stop', '_mark', 'key'): 'the stop receipts (STOP_KEY)',
    ('attempt_run.py', '_receipt', '_mark', 'key'): 'the delivery, pull and intake receipts',
    ('dispatch_inputs.py', '_settle', '_mark', 'key'): 'the revocation receipts and the grant journal',
    ('dispatch_inputs.py', 'issue', '_mark', 'self.journal_key'): 'the grant journal (GRANT_JOURNAL_KEY)',
    ('dispatch_inputs.py', '_journaled_revocation', '_mark', 'receipt_key'): 'the revocation receipts',
    ('result_path.py', 'publish_result', '_mark', 'key'): 'the result journal (RESULT_KEY)',
}


def census(trees):
    """The write-ahead sites of TREES ({module name: syntax tree}): (sites, variable) where SITES are the
    (module, function, call, key) of each reserve_attempt and each move into a constant 'dispatched', and VARIABLE
    the (module, function) of each move whose target state is not a constant."""
    sites, variable = [], set()
    for name, tree in sorted(trees.items()):
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

        def function(node):
            while node in parents:
                node = parents[node]
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return node.name
            return '<module>'
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', None)
            if call == 'reserve_attempt':
                sites.append((name, function(node), call, None))
                continue
            position = {'_mark': 3, '_mark_end': 3, 'transition': 1, 'move': 2}.get(call)
            if position is None or len(node.args) <= position:
                continue
            target = node.args[position]
            values = [target.body, target.orelse] if isinstance(target, ast.IfExp) else [target]
            if not all(isinstance(v, ast.Constant) for v in values):
                variable.add((name, function(node)))
            elif any(v.value == 'dispatched' for v in values):
                sites.append((name, function(node), call, ast.unparse(node.args[0 if call in ('transition', 'move')
                                                                               else 1])))
    return sites, variable


def package_trees():
    return {path.name: ast.parse(path.read_text(encoding='utf-8')) for path in sorted(HERE.parent.glob('*.py'))}


def _with_lock_calls(tree, function_name):
    """The calls inside the ``with ...dispatcher_lock(...)`` blocks of FUNCTION_NAME in TREE."""
    (function,) = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function_name]
    inside = []
    for node in ast.walk(function):
        if isinstance(node, ast.With) and any(
                isinstance(item.context_expr, ast.Call) and ast.unparse(item.context_expr.func).endswith(
                    'dispatcher_lock') for item in node.items):
            inside += [n for n in ast.walk(node) if isinstance(n, ast.Call)]
    return inside


class StaticCensus(unittest.TestCase):
    """Condition 4, by the call sites (G14: a site the design does not list fails here)."""
    category = 'contract'

    def test_the_write_ahead_sites_are_exactly_the_listed_ones(self):
        sites, variable = census(package_trees())
        self.assertEqual(sorted(set(sites)), sorted(SITES))
        self.assertEqual(sites.count(('attempt_end.py', 'end_interrupted_attempt', '_mark_end', 'key')), 2)
        self.assertEqual(len(sites), len(SITES) + 1)
        self.assertLessEqual(variable, PASS_THROUGH, 'a move with a computed target state outside the helpers')
        typed = [s for s in sites if SITES[s].startswith(('typed attempt', 'turn journal'))]
        self.assertEqual(typed, [('attempt_run.py', 'send_message', '_mark', 'key'),
                                 ('dispatch_inputs.py', '_dispatch', 'reserve_attempt', None),
                                 ('dispatch_inputs.py', '_dispatch', '_mark', 'key')])

    def test_the_typed_and_turn_sites_lie_in_held_regions(self):
        trees = package_trees()
        # dispatch: _dispatch is called once in the package, inside dispatch's `with dispatcher_lock(...)`
        calls = [(name, n) for name, tree in trees.items() for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and ast.unparse(n.func).split('.')[-1] == '_dispatch']
        self.assertEqual(len(calls), 1)
        self.assertIn(calls[0][1], _with_lock_calls(trees['dispatch_inputs.py'], 'dispatch'))
        # send_message: its reservation, its dispatched transition and its POST inside its own held block
        inside = [ast.unparse(n) for n in _with_lock_calls(trees['attempt_run.py'], 'send_message')]
        self.assertTrue(any("'reserved', 'dispatched'" in c for c in inside))
        self.assertTrue(any(c.startswith('integration_store.reserve(') for c in inside))
        self.assertTrue(any(c.startswith("client.call('POST'") for c in inside))
        # the store's typed reservation is refused for any other key form: reserve() refuses attempt/ keys
        with self.assertRaises(store_mod.InvalidIdentity):
            store_mod.IntegrationStore.reserve(mock.Mock(), 'attempt/v1/x', {}, actor='t')

    def test_the_census_would_see_an_unlisted_site(self):
        """Negative control: a move into dispatched planted in a copy of a module is a site the list lacks."""
        trees = package_trees()
        source = (HERE.parent / 'attempt_end.py').read_text(encoding='utf-8')
        trees['attempt_end.py'] = ast.parse(source + "\n\ndef planted(s, k):\n    di._mark(s, k, 'reserved', "
                                                     "'dispatched', 'a', 'r', None)\n    s.reserve_attempt(1, {}, "
                                                     "actor='a')\n    di._mark(s, k, 'x', state, 'a', 'r', None)\n")
        sites, variable = census(trees)
        self.assertIn(('attempt_end.py', 'planted', '_mark', 'k'), sites)
        self.assertIn(('attempt_end.py', 'planted', 'reserve_attempt', None), sites)
        self.assertIn(('attempt_end.py', 'planted'), variable)


class DynamicCensus(unittest.TestCase):
    """Condition 4, by a recording wrapper around the store under the dispatch suite's modules that reach the sites:
    every production call finds the lock held by the calling thread."""
    category = 'integration'

    def test_every_production_write_ahead_call_holds_the_lock(self):
        out = Path(tempfile.mkdtemp(prefix='aieh-lock-census-'))
        self.addCleanup(shutil.rmtree, out, True)
        done = subprocess.run([sys.executable, '-I', '-B', str(RUNNER), str(out / 'census.json'), *CENSUS_MODULES],
                              capture_output=True, text=True, timeout=CENSUS_CEILING_S, stdin=subprocess.DEVNULL,
                              creationflags=NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stderr[-4000:])
        report = json.loads((out / 'census.json').read_text(encoding='utf-8'))
        self.assertEqual(report['failures'], [])
        self.assertGreater(report['run'], 100)
        production = [c for c in report['calls'] if c['production']]
        self.assertEqual([c for c in production if not c['held']], [])
        kinds = {(c['kind'], c['module'], c['function']) for c in production}
        self.assertEqual(kinds, {('reserve_attempt', 'dispatch_inputs.py', '_dispatch'),
                                 ('typed-dispatched', 'dispatch_inputs.py', '_dispatch'),
                                 ('turn-dispatched', 'attempt_run.py', 'send_message')})
        self.assertTrue(any(not c['production'] for c in report['calls']), 'the tests\' own writes are told apart')

    def test_the_wrapper_would_see_an_unheld_call(self):
        """Negative control: with the lock taken out of dispatch (a no-op context), the same recorder finds the
        reservation and the dispatched transition unheld."""
        runner = _load('lock_census_runner', RUNNER)
        fixture = tar.attempt_fixture(self)
        transition, reserve_attempt = store_mod.IntegrationStore.transition, store_mod.IntegrationStore.reserve_attempt
        calls = []

        def recording_transition(store, key, to_state, **kwargs):
            if to_state == 'dispatched' and key.startswith(store_mod.KEY_PREFIX):
                calls.append(('dispatched', runner.site_of(sys._getframe(1)),
                              DL.held_by_this_thread(store.path)))
            return transition(store, key, to_state, **kwargs)

        def recording_reserve(store, identity, intent, *, actor):
            calls.append(('reserve', runner.site_of(sys._getframe(1)), DL.held_by_this_thread(store.path)))
            return reserve_attempt(store, identity, intent, actor=actor)
        with mock.patch.object(store_mod.IntegrationStore, 'transition', recording_transition), \
                mock.patch.object(store_mod.IntegrationStore, 'reserve_attempt', recording_reserve), \
                mock.patch.object(di, 'dispatcher_lock', lambda store: contextlib.nullcontext()):
            fixture.dispatch_native()
        self.assertEqual(calls, [('reserve', ('dispatch_inputs.py', '_dispatch', True), False),
                                 ('dispatched', ('dispatch_inputs.py', '_dispatch', True), False)])


if __name__ == '__main__':
    unittest.main()
