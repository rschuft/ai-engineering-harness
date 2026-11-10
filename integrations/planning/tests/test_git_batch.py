"""Tests of the planning adapter's repository access (stdlib unittest, plan leaves F-09.4 and F-10.3).

Run from the repository root, under the tools interpreter (``tools_install.py --python``):

    <tools python> -I -B -m unittest discover -s integrations/planning/tests -v

``planning_adapter.Git`` is a facade over the shared repository-access module
(``integrations/repository/``, decision 0014): every answer is read in this process over Dulwich,
through one opened repository per read session, with memos that last only for that session; no
git process is started. These tests keep F-09.4's test ids and check what the facade must keep:
the answers of the one-shot git commands it replaces (``rev-parse --verify --quiet
REV^{commit}``, ``cat-file -t``, ``cat-file blob``, ``ls-tree``; git is the oracle here), names
refused before anything is opened or read, the repository closed on a normal exit and on an
exception, a damaged or unreadable repository failing visibly (``GIT_FAILED``) at once, and no
memo outliving its session.

The upstream command-line tools (Backlog.md, OpenSpec) are still launched, as one process tree
each (``ProcessTree``, ``run_tree``). A command on ``PATH`` may be a launcher that runs the real
program as its child (an npm shim; Git for Windows' ``cmd\\git.exe``). ``fake_launcher.py``
plays one on any platform: through it, a kill, a timeout, an exception and a normal close each
end the child too. Where Git for Windows' own launcher is installed, the same is checked through
it.
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
ra = adapter.repository_access
PlanningError = adapter.PlanningError
DESIGN = f'openspec/changes/{fx.CHANGE}/design.md'
FAKE_BACKLOG = [sys.executable, '-I', '-B', str(HERE / 'fake_backlog.py')]
FAKE_OPENSPEC = [sys.executable, '-I', '-B', str(HERE / 'fake_openspec.py')]
readiness = sys.modules.get('planning_readiness')
if readiness is None:
    _spec = importlib.util.spec_from_file_location('planning_readiness', HERE.parent / 'planning_readiness.py')
    readiness = importlib.util.module_from_spec(_spec)
    sys.modules['planning_readiness'] = readiness
    _spec.loader.exec_module(readiness)
assert readiness.adapter is adapter, 'the readiness module and the fixture must share one adapter'

# The control characters (C0, LF, CR and NUL among them, and DEL): refused in every name.
CONTROL_CHARACTERS = [chr(c) for c in (0, 1, 9, 10, 11, 12, 13, 0x1b, 0x1f, 0x7f)]
# A space (or other whitespace that is not a control character) is part of an object name, never
# of a revision.
WHITESPACE = [chr(c) for c in (0x20, 0x85, 0xa0, 0x2028, 0x3000)]
# A launcher that runs its command as a child (fake_launcher.py), and children that never end.
FAKE_LAUNCHER = [sys.executable, '-I', '-B', str(HERE / 'fake_launcher.py')]
SLEEPS = [sys.executable, '-I', '-c', 'import time; time.sleep(60)']
GONE_WITHIN_S = 5  # a ceiling for a killed process to be gone, not an expected duration
CLOSE_CEILING_S = 10  # a ceiling for a process whose input closed to end itself

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


def is_open(repository):
    """Whether the module's repository is still open (its Dulwich repository not yet released)."""
    return repository._dul is not None


class Recorded(adapter._Session):
    """A read session that keeps every instance that opened its repository (as F-09.4 kept every
    batch reader it started), so a test can check each one ended."""
    made = []

    def _open(self):
        first = self.repository is None and not self.closed
        repository = super()._open()
        if first:
            self.opened = repository
            type(self).made.append(self)
        return repository


@contextlib.contextmanager
def module_calls():
    """Record every read the module answers for the facade (commit, read, files), in order."""
    seen = []
    with contextlib.ExitStack() as stack:
        for method in ('commit', 'read', 'files'):
            real = getattr(ra.Repository, method)

            def spy(repository, *args, _real=real, _method=method):
                seen.append((_method, *args))
                return _real(repository, *args)

            stack.enter_context(mock.patch.object(ra.Repository, method, spy))
        yield seen


def bare_git():
    """A Git that never opened anything (no project): only argument checks can be exercised on it."""
    git = adapter.Git.__new__(adapter.Git)
    git.project, git._session = Path('no-project'), None
    return git


class BatchLine(unittest.TestCase):
    """The names the facade takes (F-09.4's batch-line checks, now the module's grammar,
    decision 0014 section 2), refused before anything is opened."""
    category = 'unit'

    def test_object_names_and_revisions_are_accepted(self):
        for name in ('HEAD', 'main', 'a' * 40, 'a' * 40 + ':openspec/changes/x/design.md', 'HEAD^{commit}',
                     'HEAD~2:README.md', 'v1.0^{}', 'é:ü/ö.md', 'a' * 40 + ':docs/a b.md', 'HEAD: lead',
                     'HEAD:trail ') + tuple(f'HEAD:x{ch}y' for ch in WHITESPACE):
            with self.subTest(name=name):
                self.assertEqual(adapter.check_object_name(name), name)

    def test_names_that_could_break_a_line_are_refused(self):
        bad = [f'HEAD{ch}' for ch in CONTROL_CHARACTERS] + [f'{ch}HEAD' for ch in CONTROL_CHARACTERS]
        bad += ['', '-', '--batch-all-objects', 'HEAD:x' + chr(0xd800), None, b'HEAD', 7]
        for name in bad:
            with self.subTest(name=name):
                with self.assertRaises(PlanningError) as ctx:
                    adapter.check_object_name(name)
                self.assertEqual(ctx.exception.code, 'OBJECT_NAME_INVALID')

    def test_refused_revisions_never_reach_a_reader(self):
        git = bare_git()
        with mock.patch.object(adapter, 'open_project', side_effect=AssertionError('a repository was opened')), \
                mock.patch.object(adapter.subprocess, 'Popen', side_effect=AssertionError('launched')):
            # ... and every documented gap form of decision 0014 section 2, before any access.
            gaps = [':/x', 'HEAD^{/x}', 'main@{yesterday}', '@{upstream}', 'main@{push}', '@{-1}', 'A..B', '^HEAD',
                    'HEAD^@']
            for revision in [f'HEAD{ch}' for ch in CONTROL_CHARACTERS + WHITESPACE] + ['', '-x', '--all', None] + gaps:
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
        patch = mock.patch.object(adapter, '_Session', Recorded)
        patch.start()
        self.addCleanup(patch.stop)
        self.git = adapter.Git(self.repo)

    def assertEnded(self, sessions):
        self.assertTrue(sessions)
        for session in sessions:
            self.assertTrue(session.closed, 'the session is still open')
            self.assertFalse(is_open(session.opened), 'its repository is still open')

    def expect(self, code, func, *args):
        with self.assertRaises(PlanningError) as ctx:
            func(*args)
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)
        return ctx.exception

    def damaged(self, name, how, oid=None):
        """A copy of the design repository whose object OID (the design commit) is damaged."""
        repo = self.tmp / name
        fx.build_repo(repo)
        fx.damage_object(repo, oid or self.commit, how)
        return repo


class Equivalence(RepoCase):
    """The facade answers as the one-shot git commands it replaces, run as before (the oracle)."""

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
        self.assertEqual(len(Recorded.made), 1)  # one repository served every spaced name
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
        # No process remains to write to: a refused name never reaches the repository.
        with self.git.session():
            self.assertEqual(self.git.commit('HEAD'), self.commit)
            session = self.git._session
            with module_calls() as seen:
                for ch in WHITESPACE:
                    with self.subTest(ch=ord(ch)):
                        self.expect('REVISION_INVALID', self.git.commit, f'main{ch}HEAD')
                for ch in CONTROL_CHARACTERS:
                    with self.subTest(ch=ord(ch)):
                        self.expect('REVISION_INVALID', self.git.commit, f'main{ch}HEAD')
                        self.expect('OBJECT_NAME_INVALID', self.git.object_type, self.commit, f'README.md{ch}x')
                        self.expect('OBJECT_NAME_INVALID', self.git.blob, self.commit, f'{ch}README.md')
                        self.expect('OBJECT_NAME_INVALID', self.git.object_kind, f'{self.commit}{ch}')
                        self.expect('OBJECT_NAME_INVALID', session.read, f'HEAD{ch}')
                self.assertEqual(seen, [])
                # The next request gets its own answer.
                self.assertEqual(self.git.object_type(self.commit, 'README.md'), 'blob')
                self.assertEqual(seen, [('read', f'{self.commit}:README.md')])
        self.assertEqual(len(Recorded.made), 1)
        self.assertEnded(Recorded.made)

    def test_a_refused_name_starts_no_process(self):
        with mock.patch.object(adapter.subprocess, 'Popen', side_effect=AssertionError('launched')), \
                mock.patch.object(adapter, 'open_project', side_effect=AssertionError('a repository was opened')):
            for ch in CONTROL_CHARACTERS:
                with self.subTest(ch=ord(ch)):
                    self.expect('REVISION_INVALID', self.git.commit, f'HEAD{ch}')
                    self.expect('OBJECT_NAME_INVALID', self.git.object_type, self.commit, f'a{ch}')
            for ch in WHITESPACE:
                with self.subTest(ch=ord(ch)):
                    self.expect('REVISION_INVALID', self.git.commit, f'HEAD{ch}')
        self.assertEqual(Recorded.made, [])


class Lifecycle(RepoCase):
    """The session's repository is closed when the session ends, and a repository that cannot be
    read fails visibly at once: there is no process to wait on, kill or fall out of step (the
    F-09.4 ids are kept; decision 0014 section 3)."""

    def test_a_normal_exit_ends_the_process(self):
        with self.git.session():
            self.assertEqual(self.git.commit('HEAD'), self.commit)
            self.assertEqual(self.git.object_type(self.commit, DESIGN), 'blob')
            (session,) = Recorded.made
            self.assertTrue(is_open(session.opened))
        self.assertEnded([session])
        self.expect('GIT_FAILED', session.read, 'HEAD')  # closed: it fails closed

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
        # A read the operating system refuses (the commit's object file is a directory) is
        # GIT_FAILED at once, naming the object: no ceiling is waited for and no
        # subprocess.TimeoutExpired is raised.
        git = adapter.Git(self.damaged('refused', 'directory'))
        with mock.patch.object(adapter, 'TOOL_TIMEOUT_S', 0.2):
            with git.session():
                error = self.expect('GIT_FAILED', git.commit, 'HEAD')
                self.assertEqual(error.details.get('object'), self.commit)
                error = self.expect('GIT_FAILED', git.object_type, self.commit, DESIGN)
                self.assertIn(self.commit, error.message)
                (session,) = Recorded.made
                self.assertTrue(is_open(session.opened))
        self.assertEnded(Recorded.made)
        self.assertEqual(len(Recorded.made), 1)

    def test_an_answer_out_of_protocol_fails_closed(self):
        # The object's bytes are no zlib stream: a damaged answer, never a wrong one.
        git = adapter.Git(self.damaged('garbled', 'zlib'))
        with git.session():
            error = self.expect('GIT_FAILED', git.commit, 'HEAD')
            self.assertEqual(error.details.get('object'), self.commit)
            self.expect('GIT_FAILED', git.commit, 'main')
        self.assertEnded(Recorded.made)

    def test_an_answer_for_another_name_fails_closed(self):
        # The commit's file holds another object (README.md's blob): its content does not hash to
        # the id asked for, so it is refused (decision 0014 section 3, G9), where git cat-file
        # answered with the other object.
        data = self.git.blob(self.commit, 'README.md')
        other = hashlib.sha1(b'blob %d' % len(data) + bytes([0]) + data).hexdigest()
        git = adapter.Git(self.damaged('another', ('another', other)))
        with git.session():
            error = self.expect('GIT_FAILED', git.commit, 'HEAD')
            self.assertIn('does not hash to its id', error.message)
            self.assertEqual(error.details.get('object'), self.commit)
        self.assertEnded(Recorded.made)

    def test_a_reader_that_exits_fails_closed(self):
        # The repository went away after the Git was made: the session cannot open it.
        repo = self.tmp / 'gone'
        fx.build_repo(repo)
        git = adapter.Git(repo)
        os.rename(repo / '.git', repo / 'git-was-here')
        try:
            with fx.ceiling(self.tmp), git.session():
                error = self.expect('GIT_FAILED', git.object_type, self.commit, DESIGN)
                self.assertIn('cannot open', error.message)
                self.expect('GIT_FAILED', git.commit, 'main')
        finally:
            os.rename(repo / 'git-was-here', repo / '.git')
        self.assertEqual(Recorded.made, [])  # nothing was opened, so nothing is left open


class Memo(RepoCase):
    def test_a_session_reads_each_immutable_object_once(self):
        with module_calls() as seen, self.git.session():
            for _ in range(3):
                self.assertEqual(self.git.commit('HEAD'), self.commit)
                self.assertEqual(self.git.object_type(self.commit, DESIGN), 'blob')
                self.git.blob(self.commit, DESIGN)
                self.assertIsNone(self.git.object_type(self.commit, 'no-such'))
        self.assertEqual(seen, [('commit', 'HEAD'), ('read', f'{self.commit}:{DESIGN}'),
                                ('read', f'{self.commit}:no-such')])

    def test_names_that_can_change_are_not_memoized(self):
        with module_calls() as seen, self.git.session():
            for _ in range(2):
                self.assertEqual(self.git.object_type('HEAD', DESIGN), 'blob')
                self.assertEqual(self.git.object_type('main', DESIGN), 'blob')
        self.assertEqual(len(seen), 4)

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
        with module_calls() as seen:
            for _ in range(2):
                with self.git.session():
                    for _ in range(3):
                        self.assertIn(DESIGN, self.git.files(self.commit, 'openspec'))
                        self.assertIn(DESIGN, self.git.files('HEAD', 'openspec'))
        self.assertEqual([call[0] for call in seen], ['files'] * 8)


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
    """One operation: one Git per project (one work-tree check), one opened repository, all ended
    when it ends, normally, by an exception or after a failed read (ruling R3)."""

    def test_one_git_and_one_reader_per_operation(self):
        with mock.patch.object(adapter, 'check_work_tree', wraps=adapter.check_work_tree) as checks:
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
                # The repository policy (decision 0014 section 5): its own configuration only.
                self.assertEqual(adapter.CONFIG_POLICY, 'repository')
                self.assertEqual(first.config_sources, (str(self.repo / '.git' / 'config'),))
        self.assertEqual(checks.call_count, 2)  # one check each
        self.assertEqual(len(Recorded.made), 2)  # one repository each, none shared between them
        self.assertEnded(Recorded.made)

    def test_an_unreadable_project_is_answered_once(self):
        empty = self.tmp / 'not-a-repo'
        empty.mkdir(exist_ok=True)
        with mock.patch.object(adapter, 'check_work_tree', wraps=adapter.check_work_tree) as checks:
            with fx.ceiling(self.tmp), adapter.operation():
                answers = [adapter.project_git(empty) for _ in range(3)]
        self.assertEqual({(git, bool(why)) for git, why in answers}, {(None, True)})
        self.assertIn('NOT_A_WORK_TREE', answers[0][1])
        self.assertEqual(checks.call_count, 1)

    def test_an_exception_ends_the_operation_s_reader(self):
        with self.assertRaises(RuntimeError):
            with adapter.operation():
                git, _ = adapter.project_git(self.repo)
                git.commit('HEAD')
                raise RuntimeError('boom')
        self.assertEnded(Recorded.made)
        self.assertIsNone(adapter.current_operation())

    def test_a_timeout_in_an_operation_fails_closed_and_ends_the_reader(self):
        # A damaged repository (the commit's bytes no zlib stream) fails visibly, at once and
        # every time, within the operation; its repository is closed when the operation ends.
        repo = self.damaged('damaged-operation', 'zlib')
        with adapter.operation():
            git, _ = adapter.project_git(repo)
            self.expect('GIT_FAILED', git.commit, 'HEAD')
            self.expect('GIT_FAILED', adapter.project_git(repo)[0].commit, 'main')
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
    """A command behind a launcher (fake_launcher.py): every process the adapter starts is one
    process tree (``ProcessTree``, ``run_tree``), and no child outlives a kill, a timeout, an
    exception or a normal close. The upstream CLIs run on it (decision 0014 section 8)."""

    def through_launcher(self, name, argv):
        pidfile = self.tmp / f'{name}.pid'
        if pidfile.exists():
            pidfile.unlink()
        return [*FAKE_LAUNCHER, str(pidfile), *argv], pidfile

    def tree(self, argv, **popen_args):
        tree = adapter.ProcessTree(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=adapter.tool_env(),
                                   **popen_args)
        self.addCleanup(self.close, tree)
        return tree

    @staticmethod
    def close(tree):
        tree.close(CLOSE_CEILING_S)
        for stream in (tree.process.stdin, tree.process.stdout, tree.process.stderr):
            if stream is not None:
                stream.close()

    def test_a_launcher_that_exits_fails_closed_and_its_child_ends(self):
        argv, pidfile = self.through_launcher('exits', SLEEPS)
        tree = self.tree(argv, stdin=subprocess.DEVNULL)
        child = Watch(self, read_pid(pidfile))
        tree.process.kill()
        tree.process.wait(adapter.TOOL_TIMEOUT_S)
        self.assertFalse(tree.running())  # decided by the started process
        self.assertTrue(child.alive())  # the launcher alone was killed: its child still runs
        tree.kill(GONE_WITHIN_S)
        self.assertTrue(child.gone_within(GONE_WITHIN_S), f'the child {child.pid} outlived its tree')

    def test_a_timeout_through_a_launcher_ends_its_child(self):
        # Backlog.md behind a launcher (an npm shim) that never answers: the Backlog wrapper's
        # default runner ends the whole tree at the ceiling.
        argv, pidfile = self.through_launcher('timeout', SLEEPS)
        work = self.tmp / 'timeout-cwd'
        work.mkdir(exist_ok=True)
        with mock.patch.object(adapter, 'TOOL_TIMEOUT_S', 1):
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired) as ctx:
                adapter.Backlog(argv, work).list_tasks()
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(ctx.exception.timeout, 1)
        child = Watch(self, read_pid(pidfile, 0))
        self.assertTrue(child.gone_within(GONE_WITHIN_S), f'the child {child.pid} outlived the timeout')

    def test_an_exception_ends_the_launcher_and_its_child(self):
        argv, pidfile = self.through_launcher('exception', SLEEPS)
        watched = []

        def boom(process, *args, **kwargs):
            watched.append(Watch(self, read_pid(pidfile)))  # the child runs
            raise RuntimeError('boom')

        with mock.patch.object(subprocess.Popen, 'communicate', autospec=True, side_effect=boom), \
                self.assertRaises(RuntimeError):
            adapter.run_tree(argv, timeout=60, env=adapter.tool_env())
        (child,) = watched
        self.assertTrue(child.gone_within(GONE_WITHIN_S), f'the child {child.pid} outlived its tree')

    def test_a_normal_close_ends_the_launcher_and_its_child(self):
        argv, pidfile = self.through_launcher('close', [sys.executable, '-I', '-c',
                                                        'import time; time.sleep(1); print("done")'])
        tree = self.tree(argv, stdin=subprocess.DEVNULL)
        child = Watch(self, read_pid(pidfile))
        out, _ = tree.process.communicate(timeout=adapter.TOOL_TIMEOUT_S)
        self.close(tree)
        self.assertEqual((tree.process.returncode, out.strip()), (0, b'done'))
        self.assertTrue(child.gone_within(GONE_WITHIN_S), f'the child {child.pid} outlived its tree')

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
        # The upstream CLI launches (Backlog.md, OpenSpec) go through run_tree; no git is launched.
        work = self.tmp / 'trees-cwd'
        work.mkdir(exist_ok=True)
        with mock.patch.object(adapter, 'run_tree', wraps=adapter.run_tree) as tree, \
                mock.patch.object(adapter.subprocess, 'run', side_effect=AssertionError('subprocess.run')):
            self.assertEqual(adapter.Backlog(FAKE_BACKLOG, work).list_tasks(), [])
            state = adapter.openspec_apply_state(self.git, fx.CHANGE, self.commit, FAKE_OPENSPEC)
        self.assertIs(state['taskTrackingConfigured'], False)
        self.assertEqual([c.args[0] for c in tree.call_args_list],
                         [[*FAKE_BACKLOG, 'task', 'list', '--json'],
                          [*FAKE_OPENSPEC, 'instructions', 'apply', '--change', fx.CHANGE, '--json']])
        self.assertEqual([c.kwargs['cwd'] for c in tree.call_args_list][0], work)


@unittest.skipUnless(os.name == 'nt', 'job objects are Windows only')
class JobObject(RepoCase):
    """The Windows job's own failure paths: its documented resume path, and a process that
    cannot join its job is ended rather than left running outside it."""

    def test_the_documented_resume_path_starts_the_process(self):
        with mock.patch.object(adapter, '_nt_resume', return_value=False) as nt_resume:
            result = adapter.run_tree([sys.executable, '-I', '-c', 'print("resumed")'], timeout=CLOSE_CEILING_S)
        self.assertEqual(nt_resume.call_count, 1)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, b'resumed'))

    def test_a_process_that_cannot_join_its_job_is_ended(self):
        started, real_popen = [], subprocess.Popen

        def popen(*args, **kwargs):
            started.append(real_popen(*args, **kwargs))
            return started[-1]

        with mock.patch.object(adapter.subprocess, 'Popen', side_effect=popen), \
                mock.patch.object(adapter._kernel32(), 'AssignProcessToJobObject', return_value=0):
            with self.assertRaises(OSError):
                adapter.ProcessTree(SLEEPS, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=adapter.tool_env())
        (process,) = started
        self.assertIsNotNone(process.poll())
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


class RealLauncher(RepoCase):
    """The same through Git for Windows' own launcher, where it is installed: its child, the
    real git, ends with the tree, also when the launcher alone exited."""

    @classmethod
    def setUpClass(cls):
        cls.launcher = git_for_windows_launcher()
        if cls.launcher is None:
            raise unittest.SkipTest('Git for Windows\' launcher (cmd\\git.exe) is not installed here')
        super().setUpClass()

    def start(self, *args):
        """A process tree through the launcher, and a Watch on its one git child."""
        tree = adapter.ProcessTree([str(self.launcher), '-C', str(self.repo), *args], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=adapter.tool_env())
        self.addCleanup(self.close, tree)
        deadline = time.monotonic() + 10
        while True:
            children = [pid for pid, name in child_processes(tree.process.pid) if name.lower() == 'git.exe']
            if children or time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        self.assertEqual(len(children), 1, 'the launcher runs the real git as its one child')
        return tree, Watch(self, children[0])

    @staticmethod
    def close(tree):
        """Close the input, wait for git to end itself (up to a ceiling), and close the tree."""
        try:
            tree.process.stdin.close()
        except OSError:
            pass
        try:
            tree.process.wait(timeout=CLOSE_CEILING_S)
        except subprocess.TimeoutExpired:
            pass
        tree.close(CLOSE_CEILING_S)
        for stream in (tree.process.stdout, tree.process.stderr):
            stream.close()

    def ask(self, tree, name):
        tree.process.stdin.write(name.encode() + bytes([10]))
        tree.process.stdin.flush()
        return tree.process.stdout.readline()

    def test_a_launcher_that_exits_fails_closed_and_the_real_git_ends(self):
        tree, child = self.start('cat-file', '--batch')
        self.assertTrue(self.ask(tree, 'HEAD^{commit}').startswith(self.commit.encode()))
        tree.process.kill()
        tree.process.wait(adapter.TOOL_TIMEOUT_S)
        self.assertFalse(tree.running())
        self.assertTrue(child.alive())  # the launcher alone was killed: the real git still runs
        tree.kill(GONE_WITHIN_S)
        self.assertTrue(child.gone_within(GONE_WITHIN_S), f'git {child.pid} outlived its tree')

    def test_a_timeout_ends_the_real_git(self):
        # hash-object --stdin answers nothing until its input ends.
        tree, child = self.start('hash-object', '--stdin')
        with self.assertRaises(subprocess.TimeoutExpired):
            tree.process.wait(timeout=0.5)
        tree.kill(GONE_WITHIN_S)
        self.assertTrue(child.gone_within(GONE_WITHIN_S), f'git {child.pid} outlived the timeout')

    def test_an_exception_and_a_close_end_the_real_git(self):
        for raises in (True, False):
            with self.subTest(exception=raises):
                tree, child = self.start('cat-file', '--batch')
                with self.assertRaises(RuntimeError) if raises else contextlib.nullcontext():
                    try:
                        self.assertTrue(self.ask(tree, 'HEAD^{commit}').startswith(self.commit.encode()))
                        if raises:
                            raise RuntimeError('boom')
                    finally:
                        self.close(tree)
                self.assertEqual(tree.process.returncode, 0)  # its input closed: it ended itself
                self.assertTrue(child.gone_within(GONE_WITHIN_S), f'git {child.pid} outlived its tree')


if __name__ == '__main__':
    unittest.main()
