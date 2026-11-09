"""Tests of the planning adapter's batched git reads (stdlib unittest, plan leaf F-09.4).

Run from the repository root:

    python -I -B -m unittest discover -s integrations/planning/tests -v

``planning_adapter.Git`` reads objects through one ``git cat-file --batch`` process per
read session (``BatchReader``), with memos that last only for that session. These tests
check what that must keep: the answers of the one-shot commands it replaces (``rev-parse
--verify --quiet REV^{commit}``, ``cat-file -t``, ``cat-file blob``), names that could break
the line protocol refused before anything reaches the process, the reader closed on a normal
exit, on an exception and on a timeout (killed, and every later read fails closed), and no
memo outliving its session. Stand-in processes play a git that hangs or answers out of
protocol; every other process is the real git.

A git on PATH may be a launcher that runs the real git as its child (Git for Windows'
``cmd\\git.exe``; round 4). ``fake_launcher.py`` plays one on any platform: through it, a reader
whose launcher exited fails closed before it writes, and a kill, a timeout, an exception and a
normal close each end the child too. Where Git for Windows' own launcher is installed, the same
is checked through it.
"""
import contextlib
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import two_task_fixture as fx  # noqa: E402
import fake_backlog  # noqa: E402

adapter = fx.adapter
PlanningError = adapter.PlanningError
DESIGN = f'openspec/changes/{fx.CHANGE}/design.md'
FAKE_BACKLOG = [sys.executable, '-I', '-B', str(HERE / 'fake_backlog.py')]
readiness = sys.modules.get('planning_readiness')
if readiness is None:
    _spec = importlib.util.spec_from_file_location('planning_readiness', HERE.parent / 'planning_readiness.py')
    readiness = importlib.util.module_from_spec(_spec)
    sys.modules['planning_readiness'] = readiness
    _spec.loader.exec_module(readiness)
assert readiness.adapter is adapter, 'the readiness module and the fixture must share one adapter'

# Every character the batch protocol cannot carry inside one name: the control characters
# (C0, LF, CR and NUL among them, and DEL).
CONTROL_CHARACTERS = [chr(c) for c in (0, 1, 9, 10, 11, 12, 13, 0x1b, 0x1f, 0x7f)]
# Without a %(rest) format git takes the whole request line as the name: a space (or other
# whitespace that is not a control character) is part of an object name, never of a revision.
WHITESPACE = [chr(c) for c in (0x20, 0x85, 0xa0, 0x2028, 0x3000)]
# A stand-in that reads a request and never answers, and one that answers out of protocol.
HANGS = [sys.executable, '-I', '-c', 'import sys, time; sys.stdin.readline(); time.sleep(300)']
GARBLES = [sys.executable, '-I', '-c',
           'import sys, time; sys.stdin.readline(); print("not an answer", flush=True); time.sleep(300)']
ANSWERS_ANOTHER = [sys.executable, '-I', '-c',
                   'import sys, time; sys.stdin.readline(); '
                   'sys.stdout.buffer.write(b"main^{commit} missing" + bytes([10])); sys.stdout.flush(); time.sleep(300)']
# A launcher that runs its command as a child (fake_launcher.py), and a child that never reads.
FAKE_LAUNCHER = [sys.executable, '-I', '-B', str(HERE / 'fake_launcher.py')]
SLEEPS = [sys.executable, '-I', '-c', 'import time; time.sleep(60)']
GONE_WITHIN_S = 5  # a ceiling for a killed process to be gone, not an expected duration

if os.name == 'nt':
    import ctypes
    from ctypes import wintypes

    class _ProcessEntry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]

    _K32 = ctypes.WinDLL('kernel32', use_last_error=True)
    for _name, _restype, _argtypes in (
            ('OpenProcess', wintypes.HANDLE, (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)),
            ('WaitForSingleObject', wintypes.DWORD, (wintypes.HANDLE, wintypes.DWORD)),
            ('CloseHandle', wintypes.BOOL, (wintypes.HANDLE,)),
            ('CreateToolhelp32Snapshot', wintypes.HANDLE, (wintypes.DWORD, wintypes.DWORD)),
            ('Process32FirstW', wintypes.BOOL, (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))),
            ('Process32NextW', wintypes.BOOL, (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)))):
        getattr(_K32, _name).restype, getattr(_K32, _name).argtypes = _restype, _argtypes


class Watch:
    """Whether process PID still runs, checked without the adapter's own mechanism: on Windows
    a handle opened at once (which also keeps the id from being reused) and waited on; on POSIX
    ``os.kill(pid, 0)``."""

    def __init__(self, test, pid):
        self.pid, self.handle = pid, None
        if os.name == 'nt':
            self.handle = _K32.OpenProcess(0x100000 | 0x1000, False, pid)  # SYNCHRONIZE, query
            if self.handle:
                test.addCleanup(_K32.CloseHandle, self.handle)

    def gone_within(self, seconds):
        if os.name == 'nt':
            return not self.handle or _K32.WaitForSingleObject(self.handle, int(seconds * 1000)) == 0
        deadline = time.monotonic() + seconds
        while True:
            try:
                os.kill(self.pid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def alive(self):
        return not self.gone_within(0)


def read_pid(pidfile, seconds=10):
    """The process id fake_launcher.py wrote, waiting (up to SECONDS) for the file to appear."""
    deadline = time.monotonic() + seconds
    while not pidfile.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f'the launcher wrote no {pidfile.name}')
        time.sleep(0.01)
    return int(pidfile.read_text(encoding='ascii'))


def child_processes(pid):
    """[(process id, executable name)] of the processes whose parent is PID (Windows)."""
    snapshot = _K32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    found = []
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        more = _K32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32ParentProcessID == pid:
                found.append((entry.th32ProcessID, entry.szExeFile))
            more = _K32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _K32.CloseHandle(snapshot)
    return found


def git_for_windows_launcher():
    """Git for Windows' launcher ``cmd\\git.exe`` when it is installed, else None: the git on
    PATH when it is the launcher (a Windows shell's default PATH), or the ``cmd\\git.exe`` of
    the installation whose real git PATH resolves (Git Bash: ``mingw64\\bin\\git.exe``). Found
    from the path alone, without a launch, so that the class's counters are the same in both."""
    if os.name != 'nt':
        return None
    found = shutil.which('git')
    for root in Path(found).parents[:3] if found else ():
        launcher = root / 'cmd' / 'git.exe'
        if launcher.is_file():
            return launcher
    return None


class Recorded(adapter.BatchReader):
    """A BatchReader that keeps every instance, so a test can check each process ended."""
    made = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        type(self).made.append(self)


class WriteRecorder:
    """Stands in for a reader's standard input and keeps what was written to it."""

    def __init__(self, stream):
        self.stream, self.written = stream, bytearray()

    def write(self, data):
        self.written.extend(data)
        return self.stream.write(data)

    def flush(self):
        return self.stream.flush()

    def close(self):
        return self.stream.close()


def bare_git():
    """A Git that never ran (no project): only argument checks can be exercised on it."""
    git = adapter.Git.__new__(adapter.Git)
    git.project, git._session = Path('no-project'), None
    return git


class BatchLine(unittest.TestCase):
    category = 'unit'

    def test_object_names_and_revisions_are_accepted(self):
        for name in ('HEAD', 'main', 'a' * 40, 'a' * 40 + ':openspec/changes/x/design.md', 'HEAD^{commit}',
                     'HEAD~2:README.md', 'v1.0^{}', 'é:ü/ö.md', 'a' * 40 + ':docs/a b.md', 'HEAD: lead',
                     'HEAD:trail ') + tuple(f'HEAD:x{ch}y' for ch in WHITESPACE):
            with self.subTest(name=name):
                self.assertEqual(adapter.batch_line(name), name.encode('utf-8'))

    def test_names_that_could_break_a_line_are_refused(self):
        bad = [f'HEAD{ch}' for ch in CONTROL_CHARACTERS] + [f'{ch}HEAD' for ch in CONTROL_CHARACTERS]
        bad += ['', '-', '--batch-all-objects', 'HEAD:x' + chr(0xd800), None, b'HEAD', 7]
        for name in bad:
            with self.subTest(name=name):
                with self.assertRaises(PlanningError) as ctx:
                    adapter.batch_line(name)
                self.assertEqual(ctx.exception.code, 'OBJECT_NAME_INVALID')

    def test_refused_revisions_never_reach_a_reader(self):
        git = bare_git()
        with mock.patch.object(adapter, 'BatchReader', side_effect=AssertionError('a reader was started')), \
                mock.patch.object(adapter.subprocess, 'Popen', side_effect=AssertionError('launched')):
            for revision in [f'HEAD{ch}' for ch in CONTROL_CHARACTERS + WHITESPACE] + ['', '-x', '--all', None]:
                with self.subTest(revision=revision):
                    with self.assertRaises(PlanningError) as ctx:
                        git.commit(revision)
                    self.assertEqual(ctx.exception.code, 'REVISION_INVALID')
            for path in [f'a{ch}b' for ch in CONTROL_CHARACTERS]:
                for read in (git.object_type, git.blob):
                    with self.subTest(read=read.__name__, path=path):
                        with self.assertRaises(PlanningError) as ctx:
                            read('a' * 40, path)
                        self.assertEqual(ctx.exception.code, 'OBJECT_NAME_INVALID')


class RepoCase(unittest.TestCase):
    """A design repository per class (read only by these tests unless a test copies it)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-batch-test-'))
        cls.addClassCleanup(fx.rmtree, cls.tmp)
        cls.repo = cls.tmp / 'project'
        cls.commit = fx.build_repo(cls.repo)

    def setUp(self):
        Recorded.made = []
        patch = mock.patch.object(adapter, 'BatchReader', Recorded)
        patch.start()
        self.addCleanup(patch.stop)
        self.git = adapter.Git(self.repo)

    def assertEnded(self, readers):
        self.assertTrue(readers)
        for reader in readers:
            self.assertIsNotNone(reader.process.poll(), f'process {reader.process.pid} is still running')

    def expect(self, code, func, *args):
        with self.assertRaises(PlanningError) as ctx:
            func(*args)
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)
        return ctx.exception


class Equivalence(RepoCase):
    """The batch reader answers as the one-shot commands it replaces, run as before."""

    def one_shot(self, *args):
        result = subprocess.run(['git', '-C', str(self.repo), *args], capture_output=True,
                                stdin=subprocess.DEVNULL, timeout=adapter.TOOL_TIMEOUT_S, env=adapter.tool_env())
        return result.stdout if result.returncode == 0 else None

    def ambiguous_prefix(self):
        """A four-digit prefix shared by two blobs written here (found by hashing, one launch)."""
        if getattr(type(self), 'prefix', None) is None:
            type(self).prefix = self._write_ambiguous_blobs()
        return type(self).prefix

    def _write_ambiguous_blobs(self):
        seen = {}
        for number in range(100000):
            data = f'ambiguous {number}'.encode()
            oid = hashlib.sha1(b'blob %d' % len(data) + bytes([0]) + data).hexdigest()
            if oid[:4] in seen:
                other = seen[oid[:4]]
                break
            seen[oid[:4]] = data
        with tempfile.TemporaryDirectory(prefix='aieh-batch-amb-') as tmp:
            paths = []
            for index, payload in enumerate((other, data)):
                path = Path(tmp, f'{index}.txt')
                path.write_bytes(payload)
                paths.append(str(path))
            written = subprocess.run(['git', '-C', str(self.repo), 'hash-object', '-w', '--stdin-paths'],
                                     input='\n'.join(paths).encode(), capture_output=True, check=True,
                                     timeout=adapter.TOOL_TIMEOUT_S, env=adapter.tool_env())
        self.assertEqual(written.stdout.split()[1].decode()[:4], oid[:4])
        return oid[:4]

    def test_revisions(self):
        tree = self.one_shot('rev-parse', f'{self.commit}^{{tree}}').decode().strip()
        blob = self.one_shot('rev-parse', f'{self.commit}:{DESIGN}').decode().strip()
        revisions = ['HEAD', 'main', 'refs/heads/main', self.commit, self.commit[:12], self.commit[:4], '@',
                     'HEAD~0', 'HEAD~1', 'HEAD^2', 'no-such-branch', '0' * 40, 'f' * 64, tree, blob,
                     f'HEAD:{DESIGN}', 'HEAD:openspec', 'main@{0}', 'HEAD^{tree}', self.ambiguous_prefix()]
        with self.git.session():
            for revision in revisions:
                with self.subTest(revision=revision):
                    expected = self.one_shot('rev-parse', '--verify', '--quiet', f'{revision}^{{commit}}')
                    self.assertEqual(self.git.commit(revision), expected.decode('ascii').strip() if expected else None)
        self.assertEqual(self.git.commit('HEAD'), self.commit)
        self.assertEnded(Recorded.made)

    def test_object_types_and_blobs(self):
        names = [DESIGN, 'openspec', 'openspec/', f'openspec/changes/{fx.CHANGE}/no-such.md', 'README.md',
                 'no/such/dir', f'openspec/changes/{fx.CHANGE}', 'openspec/config.yaml']
        with self.git.session():
            for revision in (self.commit, 'HEAD', '0' * 40):
                for path in names:
                    with self.subTest(revision=revision, path=path):
                        name = f'{revision}:{path}'
                        kind = self.one_shot('cat-file', '-t', name)
                        self.assertEqual(self.git.object_type(revision, path), kind.decode().strip() if kind else None)
                        data = self.one_shot('cat-file', 'blob', name)
                        if data is None:
                            self.expect('GIT_FAILED', self.git.blob, revision, path)
                        else:
                            self.assertEqual(self.git.blob(revision, path), data)
            for name in (self.commit, self.commit[:7], '0' * 40, self.ambiguous_prefix()):
                with self.subTest(name=name):
                    kind = self.one_shot('cat-file', '-t', name)
                    self.assertEqual(self.git.object_kind(name), kind.decode().strip() if kind else None)
        self.assertEnded(Recorded.made)

    def test_names_with_spaces(self):
        # A tree made with git's plumbing (Windows cannot hold some of these names in a working
        # tree): leading, inner and trailing spaces, other whitespace, a directory with a space.
        names = ['a b.md', ' lead.md', 'trail .md', 'x' + chr(0xa0) + 'y.md', 'x' + chr(0x2028) + 'y.md']
        blob = self.plumbing(['hash-object', '-w', '--stdin'], b'spaced').strip()
        inner = self.plumbing(['mktree'], f'100644 blob {blob}{chr(9)}inner file.md{chr(10)}'.encode()).strip()
        listing = ''.join(f'100644 blob {blob}{chr(9)}{n}{chr(10)}' for n in names)
        listing += f'040000 tree {inner}{chr(9)}dir with space{chr(10)}'
        tree = self.plumbing(['mktree'], listing.encode('utf-8')).strip()
        commit = self.plumbing(['commit-tree', tree, '-m', 'spaced'], b'').strip()
        paths = names + ['dir with space', 'dir with space/inner file.md', 'no such file.md', 'a  b.md',
                         'dir with space/']
        with self.git.session():
            for path in paths:
                with self.subTest(path=path):
                    name = f'{commit}:{path}'
                    kind = self.one_shot('cat-file', '-t', name)
                    self.assertEqual(self.git.object_type(commit, path), kind.decode().strip() if kind else None)
                    data = self.one_shot('cat-file', 'blob', name)
                    if data is None:
                        self.expect('GIT_FAILED', self.git.blob, commit, path)
                    else:
                        self.assertEqual(self.git.blob(commit, path), data)
            out = self.one_shot('ls-tree', '-r', '-z', '--name-only', commit, '--', 'dir with space/')
            self.assertEqual(self.git.files(commit, 'dir with space'),
                             [n.decode() for n in out.split(bytes([0])) if n])
        self.assertEqual(len(Recorded.made), 1)  # a missing spaced name kept the protocol in step
        self.assertEnded(Recorded.made)

    def plumbing(self, args, data):
        return subprocess.run(['git', '-C', str(self.repo), *args], input=data, capture_output=True, check=True,
                              timeout=adapter.TOOL_TIMEOUT_S, env={**adapter.tool_env(), **fx.GIT_ENV}).stdout.decode()

    def test_file_lists(self):
        with self.git.session():
            for directory in ('openspec/changes', f'openspec/changes/{fx.CHANGE}', 'no/such', DESIGN):
                with self.subTest(directory=directory):
                    out = self.one_shot('ls-tree', '-r', '-z', '--name-only', self.commit, '--', directory + '/')
                    expected = [n.decode() for n in out.split(bytes([0])) if n]
                    self.assertEqual(self.git.files(self.commit, directory), expected)
                    self.assertEqual(self.git.files(self.commit, directory), expected)  # the memo


class InputSafety(RepoCase):
    def test_a_refused_name_is_never_written_to_the_process(self):
        with self.git.session():
            self.assertEqual(self.git.commit('HEAD'), self.commit)
            reader = self.git._session.reader
            recorder = WriteRecorder(reader.process.stdin)
            reader.process.stdin = recorder
            for ch in WHITESPACE:
                with self.subTest(ch=ord(ch)):
                    self.expect('REVISION_INVALID', self.git.commit, f'main{ch}HEAD')
            for ch in CONTROL_CHARACTERS:
                with self.subTest(ch=ord(ch)):
                    self.expect('REVISION_INVALID', self.git.commit, f'main{ch}HEAD')
                    self.expect('OBJECT_NAME_INVALID', self.git.object_type, self.commit, f'README.md{ch}x')
                    self.expect('OBJECT_NAME_INVALID', self.git.blob, self.commit, f'{ch}README.md')
                    self.expect('OBJECT_NAME_INVALID', self.git.object_kind, f'{self.commit}{ch}')
                    self.expect('OBJECT_NAME_INVALID', reader.read, f'HEAD{ch}')
            self.assertEqual(bytes(recorder.written), b'')
            # The protocol is still in step: the next request gets its own answer.
            self.assertEqual(self.git.object_type(self.commit, 'README.md'), 'blob')
            self.assertEqual(bytes(recorder.written), f'{self.commit}:README.md'.encode() + bytes([10]))
        self.assertEqual(len(Recorded.made), 1)
        self.assertEnded(Recorded.made)

    def test_a_refused_name_starts_no_process(self):
        with mock.patch.object(adapter.subprocess, 'Popen', side_effect=AssertionError('launched')):
            for ch in CONTROL_CHARACTERS:
                with self.subTest(ch=ord(ch)):
                    self.expect('REVISION_INVALID', self.git.commit, f'HEAD{ch}')
                    self.expect('OBJECT_NAME_INVALID', self.git.object_type, self.commit, f'a{ch}')
            for ch in WHITESPACE:
                with self.subTest(ch=ord(ch)):
                    self.expect('REVISION_INVALID', self.git.commit, f'HEAD{ch}')
        self.assertEqual(Recorded.made, [])


class Lifecycle(RepoCase):
    def test_a_normal_exit_ends_the_process(self):
        with self.git.session():
            self.assertEqual(self.git.commit('HEAD'), self.commit)
            self.assertEqual(self.git.object_type(self.commit, DESIGN), 'blob')
            (reader,) = Recorded.made
            self.assertIsNone(reader.process.poll())
        self.assertEnded([reader])
        self.expect('GIT_FAILED', reader.read, 'HEAD')  # closed: it fails closed

    def test_an_exception_ends_the_process(self):
        with self.assertRaises(RuntimeError):
            with self.git.session():
                self.git.commit('HEAD')
                raise RuntimeError('boom')
        self.assertEnded(Recorded.made)
        self.assertIsNone(self.git._session)

    def test_calls_outside_a_session_each_end_their_process(self):
        self.assertEqual(self.git.commit(self.commit), self.commit)
        self.assertEqual(self.git.blob(self.commit, 'README.md')[:9], b'Throwaway')
        self.expect('GIT_FAILED', self.git.blob, self.commit, 'openspec')
        self.assertEqual(len(Recorded.made), 3)
        self.assertEnded(Recorded.made)

    def test_a_timeout_kills_the_process_and_fails_closed(self):
        with mock.patch.object(adapter.Git, 'batch_argv', return_value=HANGS), \
                mock.patch.object(adapter, 'TOOL_TIMEOUT_S', 0.2):
            with self.git.session():
                started = time.monotonic()
                with self.assertRaises(subprocess.TimeoutExpired) as ctx:
                    self.git.commit('HEAD')
                self.assertGreaterEqual(time.monotonic() - started, 0.2)
                self.assertEqual(ctx.exception.timeout, 0.2)
                (reader,) = Recorded.made
                self.assertEnded([reader])  # killed at once, not at the end of the session
                error = self.expect('GIT_FAILED', self.git.object_type, self.commit, DESIGN)
                self.assertIn('killed', error.message)
            self.assertEnded(Recorded.made)
            self.assertEqual(len(Recorded.made), 1)

    def test_an_answer_out_of_protocol_fails_closed(self):
        with mock.patch.object(adapter.Git, 'batch_argv', return_value=GARBLES):
            with self.git.session():
                error = self.expect('GIT_FAILED', self.git.commit, 'HEAD')
                self.assertIn('unexpected answer', error.message)
                self.assertEnded(Recorded.made)
                self.expect('GIT_FAILED', self.git.commit, 'HEAD')
        self.assertEnded(Recorded.made)

    def test_an_answer_for_another_name_fails_closed(self):
        # "<name> missing" must echo the name asked; another name means the protocol is out of step.
        with mock.patch.object(adapter.Git, 'batch_argv', return_value=ANSWERS_ANOTHER):
            with self.git.session():
                error = self.expect('GIT_FAILED', self.git.commit, 'HEAD')
                self.assertIn('unexpected answer', error.message)
        self.assertEnded(Recorded.made)

    def test_a_reader_that_exits_fails_closed(self):
        with self.git.session():
            self.git.commit('HEAD')
            (reader,) = Recorded.made
            reader.process.kill()
            reader.process.wait(adapter.TOOL_TIMEOUT_S)
            error = self.expect('GIT_FAILED', self.git.object_type, self.commit, DESIGN)
            self.assertIn('exited', error.message)
        self.assertEnded(Recorded.made)


class Memo(RepoCase):
    def reads(self):
        return mock.patch.object(Recorded, 'read', autospec=True, side_effect=adapter.BatchReader.read)

    def test_a_session_reads_each_immutable_object_once(self):
        with self.reads() as read, self.git.session():
            for _ in range(3):
                self.assertEqual(self.git.commit('HEAD'), self.commit)
                self.assertEqual(self.git.object_type(self.commit, DESIGN), 'blob')
                self.git.blob(self.commit, DESIGN)
                self.assertIsNone(self.git.object_type(self.commit, 'no-such'))
        self.assertEqual([call.args[1] for call in read.call_args_list],
                         ['HEAD^{commit}', f'{self.commit}:{DESIGN}', f'{self.commit}:no-such'])

    def test_names_that_can_change_are_not_memoized(self):
        with self.reads() as read, self.git.session():
            for _ in range(2):
                self.assertEqual(self.git.object_type('HEAD', DESIGN), 'blob')
                self.assertEqual(self.git.object_type('main', DESIGN), 'blob')
        self.assertEqual(len(read.call_args_list), 4)

    def test_revisions_are_a_snapshot_of_one_session_only(self):
        repo = self.tmp / 'moving'
        fx.build_repo(repo)
        git = adapter.Git(repo)
        with git.session():
            self.assertEqual(git.commit('HEAD'), self.commit)
            fx.write(repo, {'README.md': b'moved on\n'})
            later = fx.commit_all(repo, 'later', date='2026-11-08T00:00:00Z')
            self.assertEqual(git.commit('HEAD'), self.commit)  # the session's snapshot
            self.assertEqual(git.commit(later), later)
        with git.session():
            self.assertEqual(git.commit('HEAD'), later)  # nothing kept from the last session
        self.assertEqual(git.commit('HEAD'), later)
        self.assertEqual(len(Recorded.made), 3)
        self.assertEnded(Recorded.made)

    def test_file_lists_are_kept_for_the_session_only(self):
        runs = []
        real_run = adapter.Git._run

        def counting(git, *args, **kwargs):
            runs.append(args[0])
            return real_run(git, *args, **kwargs)

        with mock.patch.object(adapter.Git, '_run', autospec=True, side_effect=counting):
            for _ in range(2):
                with self.git.session():
                    for _ in range(3):
                        self.assertIn(DESIGN, self.git.files(self.commit, 'openspec'))
                        self.assertIn(DESIGN, self.git.files('HEAD', 'openspec'))
        self.assertEqual(runs, ['ls-tree'] * 8)


class BacklogSnapshot(unittest.TestCase):
    """Within one operation Backlog.md's reads are a snapshot: each command once (ruling R3)."""
    category = 'unit'

    LIST = json.dumps({'schemaVersion': 1, 'kind': 'task-list', 'tasks': [{'id': 'TASK-1'}]}).encode()
    VIEW = json.dumps({'schemaVersion': 1, 'kind': 'task-view', 'task': {'id': 'TASK-1'}}).encode()

    def setUp(self):
        self.calls = []

    def runner(self, argv, **kwargs):
        self.calls.append(argv[1:])
        if argv[1:3] == ['task', 'create']:
            return subprocess.CompletedProcess(argv, 0, b'Created TASK-2', b'')
        if argv[1:4] == ['task', 'view', 'TASK-9']:
            return subprocess.CompletedProcess(argv, 1, b'', b'no such task')
        return subprocess.CompletedProcess(argv, 0, self.LIST if argv[2] == 'list' else self.VIEW, b'')

    def test_each_read_once_per_operation_and_nothing_after(self):
        backlog = adapter.Backlog(['backlog'], Path('p'), runner=self.runner)
        with adapter.operation():
            for _ in range(3):
                self.assertEqual(backlog.list_tasks(), [{'id': 'TASK-1'}])
                self.assertEqual(backlog.view('TASK-1')['id'], 'TASK-1')
                with self.assertRaises(PlanningError) as ctx:
                    backlog.view('TASK-9')
                self.assertEqual((ctx.exception.code, ctx.exception.message),
                                 ('BACKLOG_FAILED', 'backlog task view exited 1: no such task'))
            # another directory is another read
            adapter.Backlog(['backlog'], Path('q'), runner=self.runner).list_tasks()
        self.assertEqual(len(self.calls), 4)
        self.assertIsNone(adapter.current_operation())
        backlog.list_tasks()  # outside any operation: read again
        self.assertEqual(len(self.calls), 5)

    def test_a_create_ends_the_snapshot(self):
        backlog = adapter.Backlog(['backlog'], Path('p'), runner=self.runner)
        with adapter.operation():
            backlog.list_tasks()
            backlog.run('task', 'create', '--plain', '--', 'A title')
            backlog.list_tasks()
        self.assertEqual([c[:2] for c in self.calls], [['task', 'list'], ['task', 'create'], ['task', 'list']])

    def test_outside_an_operation_every_read_runs(self):
        backlog = adapter.Backlog(['backlog'], Path('p'), runner=self.runner)
        backlog.list_tasks()
        backlog.list_tasks()
        self.assertEqual(len(self.calls), 2)

    def test_an_exception_ends_the_operation(self):
        with self.assertRaises(RuntimeError):
            with adapter.operation():
                adapter.Backlog(['backlog'], Path('p'), runner=self.runner).list_tasks()
                raise RuntimeError('boom')
        self.assertIsNone(adapter.current_operation())
        adapter.Backlog(['backlog'], Path('p'), runner=self.runner).list_tasks()
        self.assertEqual(len(self.calls), 2)


class OperationScope(RepoCase):
    """One operation: one Git per project (one work-tree check), one batch reader, all ended
    when it ends, normally, by an exception or after a timeout (ruling R3)."""

    def test_one_git_and_one_reader_per_operation(self):
        with mock.patch.object(adapter.Git, '_run', autospec=True, side_effect=adapter.Git._run) as runs:
            for _ in range(2):
                with adapter.operation():
                    first, why = adapter.project_git(self.repo)
                    second, _ = adapter.project_git(self.repo)
                    self.assertIs(first, second)
                    self.assertIsNone(why)
                    self.assertEqual(first.commit('HEAD'), self.commit)
                    pointer = adapter.make_pointer(second, fx.CHANGE, 'design.md', self.commit)
                    self.assertEqual(adapter.resolve_pointer(second, pointer.text), pointer)
                self.assertIsNone(adapter.current_operation())
        self.assertEqual([c.args[1] for c in runs.call_args_list], ['rev-parse'] * 2)  # one check each
        self.assertEqual(len(Recorded.made), 2)  # one reader each, none shared between them
        self.assertEnded(Recorded.made)

    def test_an_unreadable_project_is_answered_once(self):
        empty = self.tmp / 'not-a-repo'
        empty.mkdir(exist_ok=True)
        with mock.patch.object(adapter.Git, '_run', autospec=True, side_effect=adapter.Git._run) as runs:
            with adapter.operation():
                answers = [adapter.project_git(empty) for _ in range(3)]
        self.assertEqual({(git, bool(why)) for git, why in answers}, {(None, True)})
        self.assertEqual(len(runs.call_args_list), 1)

    def test_an_exception_ends_the_operation_s_reader(self):
        with self.assertRaises(RuntimeError):
            with adapter.operation():
                git, _ = adapter.project_git(self.repo)
                git.commit('HEAD')
                raise RuntimeError('boom')
        self.assertEnded(Recorded.made)
        self.assertIsNone(adapter.current_operation())

    def test_a_timeout_in_an_operation_fails_closed_and_ends_the_reader(self):
        with mock.patch.object(adapter.Git, 'batch_argv', return_value=HANGS), \
                mock.patch.object(adapter, 'TOOL_TIMEOUT_S', 0.2):
            with adapter.operation():
                git, _ = adapter.project_git(self.repo)
                with self.assertRaises(subprocess.TimeoutExpired):
                    git.commit('HEAD')
                self.assertEnded(Recorded.made)
                self.expect('GIT_FAILED', adapter.project_git(self.repo)[0].commit, 'main')
        self.assertEqual(len(Recorded.made), 1)
        self.assertEnded(Recorded.made)

    def test_a_readiness_evaluation_is_one_operation(self):
        calls = []
        inner = fake_backlog.InProcessRunner(FAKE_BACKLOG)

        def counting(argv, **kwargs):
            calls.append(argv[len(FAKE_BACKLOG):])
            return inner(argv, **kwargs)

        backlog = adapter.Backlog(FAKE_BACKLOG, self.repo, runner=counting)
        snapshot = HERE / 'fixtures' / 'readiness' / 'unblocked'
        with mock.patch.dict(os.environ, {'FAKE_BACKLOG_SNAPSHOT': str(snapshot)}):
            report = readiness.read_readiness(backlog, self.git, ['TASK-2', 'TASK-2', 'TASK-1'])
        self.assertEqual([e['id'] for e in report['tasks']], ['TASK-2', 'TASK-2', 'TASK-1'])
        self.assertTrue(all(p['resolved'] for e in report['tasks'] for p in e['pointers']))
        self.assertEqual(calls, [['task', 'list', '--json'], ['task', 'view', 'TASK-2', '--json'],
                                 ['task', 'view', 'TASK-1', '--json']])
        self.assertEqual(len(Recorded.made), 1)
        self.assertEnded(Recorded.made)
        self.assertIsNone(adapter.current_operation())


class Launcher(RepoCase):
    """A git behind a launcher (fake_launcher.py, round 4): the reader's state, not what the
    child would still answer, decides that it fails closed, and no child outlives the reader."""

    def through_launcher(self, name, argv):
        pidfile = self.tmp / f'{name}.pid'
        if pidfile.exists():
            pidfile.unlink()
        return [*FAKE_LAUNCHER, str(pidfile), *argv], pidfile

    def batch(self, name):
        return self.through_launcher(name, ['git', '-C', str(self.repo), 'cat-file', '--batch'])

    def test_a_launcher_that_exits_fails_closed_and_its_child_ends(self):
        argv, pidfile = self.batch('exits')
        with mock.patch.object(adapter.Git, 'batch_argv', return_value=argv), self.git.session():
            self.assertEqual(self.git.commit('HEAD'), self.commit)
            child = Watch(self, read_pid(pidfile))
            (reader,) = Recorded.made
            recorder = WriteRecorder(reader.process.stdin)
            reader.process.stdin = recorder
            reader.process.kill()
            reader.process.wait(adapter.TOOL_TIMEOUT_S)
            self.assertTrue(child.alive())  # the launcher alone was killed: its child still answers
            error = self.expect('GIT_FAILED', self.git.object_type, self.commit, DESIGN)
            self.assertIn('exited', error.message)
            self.assertTrue(child.gone_within(GONE_WITHIN_S), f'the child {child.pid} outlived its reader')
            self.expect('GIT_FAILED', self.git.commit, 'main')
            self.assertEqual(bytes(recorder.written), b'')  # nothing written after the exit
        self.assertEnded(Recorded.made)

    def test_a_timeout_through_a_launcher_ends_its_child(self):
        argv, pidfile = self.through_launcher('timeout', HANGS)
        with adapter.BatchReader(argv, adapter.tool_env(), timeout=0.5) as reader:
            child = Watch(self, read_pid(pidfile))
            with self.assertRaises(subprocess.TimeoutExpired):
                reader.read('HEAD')
            self.assertTrue(child.gone_within(GONE_WITHIN_S), f'the child {child.pid} outlived the timeout')
            self.assertIsNotNone(reader.process.poll())
            recorder = WriteRecorder(reader.process.stdin)
            reader.process.stdin = recorder
            error = self.expect('GIT_FAILED', reader.read, 'main')
            self.assertIn('killed', error.message)
            self.assertEqual(bytes(recorder.written), b'')

    def test_an_exception_ends_the_launcher_and_its_child(self):
        argv, pidfile = self.batch('exception')
        with mock.patch.object(adapter.Git, 'batch_argv', return_value=argv), self.assertRaises(RuntimeError):
            with self.git.session():
                self.git.commit('HEAD')
                child = Watch(self, read_pid(pidfile))
                raise RuntimeError('boom')
        self.assertTrue(child.gone_within(GONE_WITHIN_S), f'the child {child.pid} outlived its reader')
        self.assertEqual(Recorded.made[0].process.returncode, 0)  # its input closed: it ended itself

    def test_a_normal_close_ends_the_launcher_and_its_child(self):
        argv, pidfile = self.batch('close')
        reader = adapter.BatchReader(argv, adapter.tool_env(), timeout=10)
        try:
            self.assertEqual(reader.read('HEAD^{commit}')[0], self.commit)
            child = Watch(self, read_pid(pidfile))
        finally:
            reader.close()
        self.assertEqual(reader.process.returncode, 0)  # its input closed: it ended itself
        self.assertTrue(child.gone_within(GONE_WITHIN_S), f'the child {child.pid} outlived its reader')

    def test_a_one_shot_command_through_a_launcher_is_ended_whole_at_its_ceiling(self):
        argv, pidfile = self.through_launcher('one-shot', SLEEPS)
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired) as ctx:
            adapter.run_tree(argv, timeout=1, env=adapter.tool_env())
        # The child sleeps 60 s holding the pipes; waiting for their end would wait for it.
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(ctx.exception.timeout, 1)
        child = Watch(self, read_pid(pidfile, 0))
        self.assertTrue(child.gone_within(GONE_WITHIN_S), f'the child {child.pid} outlived the call')

    def test_the_one_shot_commands_run_as_process_trees(self):
        with mock.patch.object(adapter, 'run_tree', wraps=adapter.run_tree) as tree:
            git = adapter.Git(self.repo)
            self.assertIn(DESIGN, git.files(self.commit, 'openspec'))
        self.assertEqual([c.args[0][3] for c in tree.call_args_list], ['rev-parse', 'ls-tree'])


@unittest.skipUnless(os.name == 'nt', 'job objects are Windows only')
class JobObject(RepoCase):
    """The Windows job's own failure paths: its documented resume path, and a process that
    cannot join its job is ended rather than left running outside it."""

    def test_the_documented_resume_path_starts_the_process(self):
        with mock.patch.object(adapter, '_nt_resume', return_value=False) as nt_resume:
            with adapter.BatchReader(self.git.batch_argv(), adapter.tool_env(), timeout=10) as reader:
                self.assertEqual(reader.read('HEAD^{commit}')[0], self.commit)
        self.assertEqual(nt_resume.call_count, 1)
        self.assertEqual(reader.process.returncode, 0)

    def test_a_process_that_cannot_join_its_job_is_ended(self):
        started, real_popen = [], subprocess.Popen

        def popen(*args, **kwargs):
            started.append(real_popen(*args, **kwargs))
            return started[-1]

        with mock.patch.object(adapter.subprocess, 'Popen', side_effect=popen), \
                mock.patch.object(adapter._kernel32(), 'AssignProcessToJobObject', return_value=0):
            with self.assertRaises(OSError):
                adapter.BatchReader(self.git.batch_argv(), adapter.tool_env())
        (process,) = started
        self.assertIsNotNone(process.poll())
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


class RealLauncher(RepoCase):
    """The same through Git for Windows' own launcher, where it is installed: its child, the
    real git, ends with the reader, and a reader whose launcher exited fails closed."""

    @classmethod
    def setUpClass(cls):
        cls.launcher = git_for_windows_launcher()
        if cls.launcher is None:
            raise unittest.SkipTest('Git for Windows\' launcher (cmd\\git.exe) is not installed here')
        super().setUpClass()

    def start(self, *args, timeout=None):
        """A reader through the launcher, and a Watch on its one git child."""
        reader = adapter.BatchReader([str(self.launcher), '-C', str(self.repo), *args], adapter.tool_env(),
                                     timeout=timeout)
        self.addCleanup(reader.close)
        deadline = time.monotonic() + 10
        while True:
            children = [pid for pid, name in child_processes(reader.process.pid) if name.lower() == 'git.exe']
            if children or time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        self.assertEqual(len(children), 1, 'the launcher runs the real git as its one child')
        return reader, Watch(self, children[0])

    def test_a_launcher_that_exits_fails_closed_and_the_real_git_ends(self):
        reader, child = self.start('cat-file', '--batch')
        self.assertEqual(reader.read('HEAD^{commit}')[0], self.commit)
        recorder = WriteRecorder(reader.process.stdin)
        reader.process.stdin = recorder
        reader.process.kill()
        reader.process.wait(adapter.TOOL_TIMEOUT_S)
        self.assertTrue(child.alive())  # the launcher alone was killed: the real git still answers
        error = self.expect('GIT_FAILED', reader.read, f'{self.commit}:{DESIGN}')
        self.assertIn('exited', error.message)
        self.assertTrue(child.gone_within(GONE_WITHIN_S), f'git {child.pid} outlived its reader')
        self.assertEqual(bytes(recorder.written), b'')

    def test_a_timeout_ends_the_real_git(self):
        # hash-object --stdin reads the request and answers nothing until its input ends.
        reader, child = self.start('hash-object', '--stdin', timeout=0.5)
        with self.assertRaises(subprocess.TimeoutExpired):
            reader.read('HEAD')
        self.assertTrue(child.gone_within(GONE_WITHIN_S), f'git {child.pid} outlived the timeout')
        self.expect('GIT_FAILED', reader.read, 'HEAD')

    def test_an_exception_and_a_close_end_the_real_git(self):
        for raises in (True, False):
            with self.subTest(exception=raises):
                reader, child = self.start('cat-file', '--batch')
                with self.assertRaises(RuntimeError) if raises else contextlib.nullcontext():
                    with reader:
                        self.assertEqual(reader.read('HEAD^{commit}')[0], self.commit)
                        if raises:
                            raise RuntimeError('boom')
                self.assertEqual(reader.process.returncode, 0)  # its input closed: it ended itself
                self.assertTrue(child.gone_within(GONE_WITHIN_S), f'git {child.pid} outlived its reader')


if __name__ == '__main__':
    unittest.main()
