"""Planning adapter: OpenSpec design references into Backlog.md tasks (plan leaf P-02.1).

Blueprint section ``#authority``: OpenSpec owns the accepted objective and the design;
Backlog.md owns tasks, dependencies and status. This adapter maps a small task plan
for one OpenSpec change into Backlog.md tasks through Backlog.md's own command line,
and gives every task source pointers that resolve the exact design revision:

    openspec:changes/<change-id>/<artifact-path>@<commit>#sha256=<digest>

``<commit>`` is the full git commit id of the design revision (40 or 64 hex digits),
``<artifact-path>`` is relative to ``openspec/changes/<change-id>/`` in that commit,
and ``<digest>`` is the sha256 of the artifact's blob bytes in that commit. The
pointer resolves in the project's own git repository, the one that holds both
``openspec/`` and Backlog.md's directory. Resolving it fails visibly when the commit
is missing, the artifact is missing at that commit, or its bytes differ from the
digest.

What the adapter never does:

- write Backlog.md's markdown files (only ``backlog task create``, ``task list
  --json`` and ``task view --json`` are run);
- pass, derive, mirror or report a task status: Backlog.md assigns its own default
  status and is the only owner of it;
- accept an OpenSpec change that carries its own implementation checklist
  (``tasks.md``) or whose schema tracks one (``apply.tracks``).

Usage (from the repository root):
    python -I -B integrations/planning/planning_adapter.py create --project DIR --plan FILE --revision REV --backlog CMD [--openspec CMD]
    python -I -B integrations/planning/planning_adapter.py resolve --project DIR (--pointer P ... | --backlog CMD [--task ID ...])
    python -I -B integrations/planning/planning_adapter.py pointer --project DIR --change ID --artifact PATH --revision REV

CMD is a Backlog.md (or OpenSpec) executable, or its ``.js`` entry point, which is
run with ``node``. Exit status: 0 PASS, 1 FAIL (a visible failure), 2 could not run.
The standard library, plus the shared repository-access module
(``integrations/repository/``, decision 0014), which reads the repository in this process
over Dulwich: run it with the tools interpreter (``tools_install.py --python``). Without
Dulwich every repository read is the stable CannotRun ``REPOSITORY_NEEDS_DULWICH`` (exit 2).
"""
import argparse
import contextlib
import contextvars
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

if os.name == 'nt':
    import ctypes
    from ctypes import wintypes


def _load_repository_access():
    """The shared repository-access module, loaded by path once per process (standard library
    at import; Dulwich only when a repository is opened)."""
    module = sys.modules.get('repository_access')
    if module is None:
        path = Path(__file__).resolve().parents[1] / 'repository' / 'repository_access.py'
        spec = importlib.util.spec_from_file_location('repository_access', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules['repository_access'] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules['repository_access']
            raise
    return module


repository_access = _load_repository_access()
# The configuration policy of every repository the adapter opens (decision 0014 section 5):
# the repository's own configuration only. No host setting changes an answer the adapter gives:
# object reads, file lists and exports (blob bytes, section 4) consult no configuration git
# would take from the user or the system files, and replace references fail closed.
CONFIG_POLICY = 'repository'

PLAN_FORMAT = 'planning-map/v1'
RESULT_FORMAT = 'planning-map-result/v1'
RESOLVE_FORMAT = 'planning-resolve/v1'
POINTER_PREFIX = 'openspec:'
CHANGES_DIR = 'openspec/changes'
TOOL_TIMEOUT_S = 120  # a ceiling that bounds a hung tool, not an expected duration
CHECKLIST_NAME = 'tasks.md'

CHANGE_ID = r'[a-z0-9]+(?:-[a-z0-9]+)*'
# A path part never starts with a dot, so '.', '..' and hidden files cannot be named.
PATH_PART = r'[A-Za-z0-9_][A-Za-z0-9._-]*'
ARTIFACT_PATH = rf'{PATH_PART}(?:/{PATH_PART})*'
COMMIT = r'[0-9a-f]{40}|[0-9a-f]{64}'
OBJECT_ID_RE = re.compile(rf'^(?:{COMMIT})$')
POINTER_RE = re.compile(
    rf'^openspec:changes/(?P<change>{CHANGE_ID})/(?P<artifact>{ARTIFACT_PATH})'
    rf'@(?P<revision>{COMMIT})#sha256=(?P<digest>[0-9a-f]{{64}})$')
CHANGE_ID_RE = re.compile(rf'^{CHANGE_ID}$')
ARTIFACT_RE = re.compile(rf'^{ARTIFACT_PATH}$')
TASK_ID_RE = re.compile(r'^[A-Za-z]+-[0-9]+(?:\.[0-9]+)*$')
# These grammars are checked with fullmatch: Python's $ also matches before a final newline,
# so .match would accept a task id or a pointer followed by a newline.

PLAN_KEYS = {'format', 'change', 'tasks'}
TASK_KEYS = {'key', 'title', 'description', 'artifacts', 'depends_on'}
# Status belongs to Backlog.md alone (blueprint #authority); a plan that tries to set
# or carry one is refused, never silently dropped.
STATUS_KEYS = {'status', 'state', 'done', 'completed', 'complete', 'checked', 'progress'}

# The only Backlog.md commands the adapter issues. None of them sets a status.
BACKLOG_COMMANDS = {('task', 'create'), ('task', 'list'), ('task', 'view')}
BACKLOG_READS = {('task', 'list'), ('task', 'view')}
STATUS_FLAGS = ('-s', '--status')


class PlanningError(Exception):
    """A visible failure with a stable code."""

    def __init__(self, code, message, **details):
        super().__init__(f'{code}: {message}')
        self.code = code
        self.message = message
        self.details = details


class CannotRun(Exception):
    """A prerequisite or usage problem (exit 2)."""


@dataclass(frozen=True)
class Pointer:
    change: str
    artifact: str
    revision: str
    digest: str

    @property
    def repo_path(self):
        return f'{CHANGES_DIR}/{self.change}/{self.artifact}'

    @property
    def text(self):
        return f'openspec:changes/{self.change}/{self.artifact}@{self.revision}#sha256={self.digest}'

    @classmethod
    def parse(cls, text):
        match = POINTER_RE.fullmatch(text) if isinstance(text, str) else None
        if not match:
            raise PlanningError('POINTER_MALFORMED', f'not an OpenSpec source pointer: {text!r}',
                                pointer=text)
        return cls(match['change'], match['artifact'], match['revision'], match['digest'])


# ---------------------------------------------------------------------------
# Tools

def tool_argv(spec):
    """Turn a CMD argument into an argv prefix: a .js entry point runs with node."""
    path = Path(spec)
    if path.suffix.lower() in ('.js', '.cjs', '.mjs'):
        node = shutil.which('node')
        if not node:
            raise CannotRun('node is not on PATH; it is needed to run ' + spec)
        if not path.is_file():
            raise CannotRun(f'not a file: {spec}')
        return [node, str(path)]
    found = shutil.which(spec)
    if not found:
        raise CannotRun(f'command not found: {spec}')
    return [found]


def tool_env():
    env = dict(os.environ)
    # Never let an adapter run phone home or prompt.
    env.update({'OPENSPEC_TELEMETRY': '0', 'DO_NOT_TRACK': '1', 'GIT_TERMINAL_PROMPT': '0'})
    return env


# ---------------------------------------------------------------------------
# Process trees
#
# A command on PATH may be a launcher that runs the real program as its child: an npm shim
# (backlog.CMD runs node through cmd.exe), or Git for Windows' cmd\git.exe. Killing the launched
# process alone would leave that child running, still answering on the pipes it inherited. So
# every process the adapter starts (the upstream CLIs, Backlog.md and OpenSpec; it starts no git)
# is one process tree, killed and waited for as a whole: on Windows a job object (kill on close)
# that the process joins before it runs its first instruction; on POSIX a new session, whose
# process group is signalled.

if os.name == 'nt':
    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
            'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD)]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', _BasicLimits), ('IoInfo', _IoCounters),
                    ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

    class _ProcessIdList(ctypes.Structure):
        _fields_ = [('NumberOfAssignedProcesses', wintypes.DWORD),
                    ('NumberOfProcessIdsInList', wintypes.DWORD),
                    ('ProcessIdList', ctypes.c_size_t * 64)]

    class _ThreadEntry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ThreadID', wintypes.DWORD), ('th32OwnerProcessID', wintypes.DWORD),
                    ('tpBasePri', wintypes.LONG), ('tpDeltaPri', wintypes.LONG), ('dwFlags', wintypes.DWORD)]

    _KERNEL32 = None

    def _kernel32():
        """kernel32's job, process and thread functions, typed once (a private WinDLL instance,
        so no other module's prototypes are changed)."""
        global _KERNEL32
        if _KERNEL32 is None:
            k = ctypes.WinDLL('kernel32', use_last_error=True)
            H, B, D = wintypes.HANDLE, wintypes.BOOL, wintypes.DWORD
            for name, restype, argtypes in (
                    ('CreateJobObjectW', H, (wintypes.LPVOID, wintypes.LPCWSTR)),
                    ('SetInformationJobObject', B, (H, ctypes.c_int, wintypes.LPVOID, D)),
                    ('QueryInformationJobObject', B, (H, ctypes.c_int, wintypes.LPVOID, D, wintypes.LPDWORD)),
                    ('AssignProcessToJobObject', B, (H, H)),
                    ('TerminateJobObject', B, (H, wintypes.UINT)),
                    ('IsProcessInJob', B, (H, H, wintypes.PBOOL)),
                    ('OpenProcess', H, (D, B, D)),
                    ('TerminateProcess', B, (H, wintypes.UINT)),
                    ('WaitForSingleObject', D, (H, D)),
                    ('CloseHandle', B, (H,)),
                    ('CreateToolhelp32Snapshot', H, (D, D)),
                    ('Thread32First', B, (H, ctypes.POINTER(_ThreadEntry))),
                    ('Thread32Next', B, (H, ctypes.POINTER(_ThreadEntry))),
                    ('OpenThread', H, (D, B, D)),
                    ('ResumeThread', D, (H,))):
                function = getattr(k, name)
                function.restype, function.argtypes = restype, argtypes
            _KERNEL32 = k
        return _KERNEL32

    _CREATE_SUSPENDED = 0x4
    _KILL_ON_JOB_CLOSE = 0x2000
    _JOB_EXTENDED_LIMITS, _JOB_PROCESS_IDS = 9, 3
    _PROCESS_TERMINATE, _PROCESS_SET_QUOTA = 0x1, 0x100
    _PROCESS_QUERY_LIMITED, _SYNCHRONIZE = 0x1000, 0x100000
    _THREAD_SUSPEND_RESUME, _SNAP_THREADS = 0x2, 0x4
    _PROCESS_SUSPEND_RESUME = 0x800
    _INVALID_HANDLE = ctypes.c_void_p(-1).value
    _NT_RESUME = []

    def _nt_resume(k, pid):
        """True when ntdll's NtResumeProcess resumed process PID; False when it is not there or
        failed, and the caller resumes the threads itself."""
        if not _NT_RESUME:
            function = getattr(ctypes.WinDLL('ntdll'), 'NtResumeProcess', None)
            if function is not None:
                function.restype, function.argtypes = ctypes.c_long, (wintypes.HANDLE,)
            _NT_RESUME.append(function)
        function = _NT_RESUME[0]
        if function is None:
            return False
        handle = k.OpenProcess(_PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            return False
        try:
            return function(handle) >= 0  # an NTSTATUS: success is not negative
        finally:
            k.CloseHandle(handle)


def _remaining_ms(deadline):
    return max(0, int((deadline - time.monotonic()) * 1000))


class ProcessTree:
    """One process started with ``subprocess.Popen`` and every process it starts, which are
    killed and waited for together (``kill``). ``close`` kills whatever is left and releases the
    tree. ``running`` says whether the started process itself still runs."""

    def __init__(self, argv, **popen_args):
        self._job = None
        if os.name == 'nt':
            self._start_in_job(argv, popen_args)
        else:
            self.process = subprocess.Popen(argv, start_new_session=True, **popen_args)

    def _start_in_job(self, argv, popen_args):
        k = _kernel32()
        job = k.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
            if not k.SetInformationJobObject(job, _JOB_EXTENDED_LIMITS, ctypes.byref(limits),
                                             ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            flags = popen_args.pop('creationflags', 0) | _CREATE_SUSPENDED
            self.process = subprocess.Popen(argv, creationflags=flags, **popen_args)
        except BaseException:
            k.CloseHandle(job)
            raise
        self._job = job
        try:
            handle = k.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, self.process.pid)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not k.AssignProcessToJobObject(job, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                k.CloseHandle(handle)
            self._resume(k)
        except BaseException:
            # Never left suspended, and never running outside the job: closing the job kills it.
            self.process.kill()
            self.close(TOOL_TIMEOUT_S)
            raise

    def _resume(self, k):
        """Resume the suspended process (subprocess keeps no thread handle): ntdll's
        NtResumeProcess, as psutil resumes a process, or else the documented thread walk."""
        if not _nt_resume(k, self.process.pid):
            self._resume_threads(k)

    def _resume_threads(self, k):
        """Resume every thread of the process found by a Toolhelp walk of the system's threads
        (documented, but some 20 ms on a host with thousands of threads)."""
        snapshot = k.CreateToolhelp32Snapshot(_SNAP_THREADS, 0)
        if snapshot == _INVALID_HANDLE or not snapshot:
            raise ctypes.WinError(ctypes.get_last_error())
        resumed = 0
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            more = k.Thread32First(snapshot, ctypes.byref(entry))
            while more:
                if entry.th32OwnerProcessID == self.process.pid:
                    thread = k.OpenThread(_THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if k.ResumeThread(thread) == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                    finally:
                        k.CloseHandle(thread)
                    resumed += 1
                more = k.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            k.CloseHandle(snapshot)
        if not resumed:
            raise OSError(f'no thread of process {self.process.pid} to resume')

    def running(self):
        """Whether the started process still runs (on POSIX without reaping it, so that its
        process group cannot be reused before ``kill``)."""
        if self.process.returncode is not None:
            return False
        if os.name == 'nt' or not hasattr(os, 'waitid'):
            return self.process.poll() is None
        try:
            return os.waitid(os.P_PID, self.process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None
        except ChildProcessError:
            return self.process.poll() is None

    def kill(self, timeout):
        """Kill every process of the tree and wait (up to TIMEOUT) until each has ended."""
        deadline = time.monotonic() + timeout
        if os.name == 'nt':
            if self._job is not None:
                self._kill_job(deadline)
        else:
            self._kill_group(deadline)
        try:
            self.process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass

    def _kill_job(self, deadline):
        k = _kernel32()
        while True:
            pids = _ProcessIdList()
            if not k.QueryInformationJobObject(self._job, _JOB_PROCESS_IDS, ctypes.byref(pids),
                                               ctypes.sizeof(pids), None) \
                    and ctypes.get_last_error() != 234:  # ERROR_MORE_DATA: more than 64, a part listed
                raise ctypes.WinError(ctypes.get_last_error())
            if not pids.NumberOfAssignedProcesses:
                return
            handles = []
            for pid in pids.ProcessIdList[:pids.NumberOfProcessIdsInList]:
                handle = k.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED, False, pid)
                inside = wintypes.BOOL()
                if handle and k.IsProcessInJob(handle, self._job, ctypes.byref(inside)) and inside:
                    handles.append(handle)
                elif handle:
                    k.CloseHandle(handle)
            k.TerminateJobObject(self._job, 1)
            for handle in handles:
                k.WaitForSingleObject(handle, _remaining_ms(deadline))
                k.CloseHandle(handle)
            if time.monotonic() >= deadline:
                return

    def _kill_group(self, deadline):
        group = self.process.pid
        try:
            os.killpg(group, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return
        try:
            self.process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return
        while time.monotonic() < deadline:  # the rest of the group, reaped by their new parent
            try:
                os.killpg(group, 0)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(0.005)

    def close(self, timeout):
        """Kill whatever is left of the tree, wait for it, and release the tree."""
        self.kill(timeout)
        if self._job is not None:
            _kernel32().CloseHandle(self._job)  # kill on close: nothing in it survives this
            self._job = None


def run_tree(argv, timeout=None, env=None, cwd=None):
    """``subprocess.run(argv, cwd=..., capture_output=True, stdin=DEVNULL, timeout=...)`` as one
    process tree: when the ceiling expires every process of the tree is killed and waited for
    before ``subprocess.TimeoutExpired`` is raised, and none outlives the call. The default runner
    of the upstream CLIs (``Backlog.run``, ``openspec_apply_state``)."""
    timeout = TOOL_TIMEOUT_S if timeout is None else timeout
    tree = ProcessTree(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                       cwd=cwd)
    try:
        try:
            out, err = tree.process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            tree.kill(timeout)
            try:
                out, err = tree.process.communicate(timeout=timeout)  # at their end: no writer is left
            except subprocess.TimeoutExpired:
                out = err = None
            raise subprocess.TimeoutExpired(argv, timeout, out, err) from None
    finally:
        tree.close(timeout)
        for stream in (tree.process.stdout, tree.process.stderr):  # communicate closed them, unless it raised
            if not stream.closed:
                stream.close()
    return subprocess.CompletedProcess(argv, tree.process.returncode, out, err)


# ---------------------------------------------------------------------------
# Repository access (decision 0014, plan leaf F-10.3)
#
# Git is a facade over the shared repository-access module (integrations/repository/): every
# answer is read in this process from the repository's own files, over Dulwich; no git process
# is started. The facade keeps the calls and codes lineage, dispatch and readiness use:
# REVISION_INVALID and OBJECT_NAME_INVALID before any access, GIT_FAILED when the repository
# cannot be read, None for no such object, CannotRun when the project is not a work tree or
# Dulwich is not importable (REPOSITORY_NEEDS_DULWICH).

def _planning_error(exc):
    """The module's RepositoryError as the adapter's PlanningError: the same code, message and
    details (decision 0014 section 3)."""
    return PlanningError(exc.code, exc.message, **exc.details)


def _checked(check, text):
    failure = None
    try:
        return check(text)
    except repository_access.RepositoryError as exc:
        failure = _planning_error(exc)
    raise failure


def check_revision(revision):
    """REVISION, or REVISION_INVALID before any repository access: not text, empty, a leading
    '-', whitespace, a C0 control or DEL, or a documented gap form (decision 0014 section 2)."""
    return _checked(repository_access.check_revision, revision)


def check_object_name(name):
    """NAME, or OBJECT_NAME_INVALID before any repository access: not text, empty, a leading '-',
    a C0 control or DEL (a space is part of a name); REVISION_INVALID for a gap form in its
    revision."""
    return _checked(repository_access.check_object_name, name)


def open_project(project):
    """The project's repository, opened under the adapter's configuration policy; CannotRun when
    it is not a work tree, cannot be opened or Dulwich is not importable (the module's code
    leads the message)."""
    failure = None
    try:
        return repository_access.open_repository(project, config=CONFIG_POLICY)
    except repository_access.CannotRun as exc:
        failure = CannotRun(str(exc))
    except repository_access.RepositoryError as exc:
        failure = CannotRun(str(exc))
    raise failure


def check_work_tree(project):
    """The work-tree check (``git rev-parse --show-toplevel``'s acceptance): (root, configuration
    files read) of the work tree PROJECT is in; CannotRun otherwise. The repository is opened and
    closed again."""
    repository = open_project(project)
    try:
        return Path(repository.root), repository.config_sources
    finally:
        repository.close()


class _Session:
    """One read session of a Git: the repository, opened on the first read, and memos that last
    only as long as the session. Objects are memoized only by an immutable name (a full object
    id, or ``<full object id>:<path>``); revisions are resolved once per session, a snapshot;
    file lists by (full commit id, directory). After the session ends every read fails closed
    (GIT_FAILED)."""

    def __init__(self, git):
        self.git = git
        self.repository = None
        self.closed = False
        self.objects = {}
        self.revisions = {}
        self.trees = {}

    def call(self, method, *args):
        """The repository's METHOD(*ARGS), with the module's refusals and failures raised as
        PlanningErrors (raised after the module's frames are released)."""
        failure = None
        try:
            return getattr(self._open(), method)(*args)
        except repository_access.RepositoryError as exc:
            failure = _planning_error(exc)
        raise failure

    def _open(self):
        if self.closed:
            raise PlanningError('GIT_FAILED', f'the read session of {self.git.project} is closed')
        if self.repository is None:
            try:
                self.repository = open_project(self.git.project)
            except CannotRun as exc:  # it was a work tree when the Git was made
                raise PlanningError('GIT_FAILED', f'cannot open {self.git.project}: {exc}') from None
        return self.repository

    def read(self, name):
        check_object_name(name)  # a refused name opens nothing
        immutable = OBJECT_ID_RE.fullmatch(name.partition(':')[0]) is not None
        if immutable and name in self.objects:
            return self.objects[name]
        found = self.call('read', name)
        if immutable:
            self.objects[name] = found
        return found

    def close(self):
        self.closed = True
        repository, self.repository = self.repository, None
        if repository is not None:
            repository.close()


# One top-level adapter operation (plan leaf F-09.4, the Overseer's ruling R3): one lineage
# traversal, one readiness evaluation, or one resolution from the command line or a lineage
# resolver entry point. Within it, each project's repository access is one Git (one work-tree
# check) with one read session (one opened repository), and Backlog.md's reads are a snapshot:
# the same command is run once. Everything is dropped when the operation ends, normally or by an
# exception: no module-level cache, nothing kept for the next operation.
_OPERATION = contextvars.ContextVar('planning_operation', default=None)


class Operation:
    """What one operation shares (``operation()``)."""

    def __init__(self, stack):
        self.stack = stack
        self.projects = {}       # str(project) -> (Git with its session open, None) or (None, why)
        self.backlog_reads = {}  # (argv prefix, directory, args) -> (stdout, None) or (None, failure)


@contextlib.contextmanager
def operation():
    """Run the block as one operation; inside another operation it is that operation."""
    current = _OPERATION.get()
    if current is not None:
        yield current
        return
    with contextlib.ExitStack() as stack:
        op = Operation(stack)
        token = _OPERATION.set(op)
        try:
            yield op
        finally:
            _OPERATION.reset(token)


def current_operation():
    return _OPERATION.get()


def project_git(project):
    """(Git, None) for PROJECT, or (None, why) when its repository cannot be read. Within an
    operation the same Git, with its read session open, for every call; otherwise a new Git each
    call."""
    op = _OPERATION.get()
    if op is None:
        return _open_git(project)
    key = str(Path(project))
    if key not in op.projects:
        git, why = _open_git(project)
        if git is not None:
            op.stack.enter_context(git.session())
        op.projects[key] = (git, why)
    return op.projects[key]


def _open_git(project):
    try:
        return Git(project), None
    except (CannotRun, OSError) as exc:
        return None, str(exc)


class Git:
    """Read-only access to the project repository: a facade over the shared repository-access
    module (decision 0014), which reads it in this process; no process is started.

    Making a Git is the work-tree check (CannotRun when PROJECT is not inside a git work tree,
    or Dulwich is not importable: ``REPOSITORY_NEEDS_DULWICH``, naming ``task tools:install``).
    Reads (``commit``, ``object_type``, ``object_kind``, ``blob``, ``files``, ``export_tree``)
    go through one opened repository per read session (``session()``), and are memoized for
    that session only. Outside a session each call opens and closes its own.
    """

    def __init__(self, project):
        self.project = Path(project)
        self._session = None
        self.root, self.config_sources = check_work_tree(self.project)

    @contextlib.contextmanager
    def session(self):
        """A read session: one opened repository and the session's memos, closed when the block
        ends, normally or by an exception. Re-entrant: an inner session is the outer one."""
        if self._session is not None:
            yield self
            return
        session = self._session = _Session(self)
        try:
            yield self
        finally:
            self._session = None
            session.close()

    def _in_session(self, read, *args):
        if self._session is not None:
            return read(self._session, *args)
        with self.session():
            return read(self._session, *args)

    def commit(self, revision):
        """The full commit id of REVISION (``git rev-parse --verify <revision>^{commit}``), or None
        when the repository has no such commit. REVISION_INVALID, before any access, for text that
        is not a usable revision or a documented gap form (decision 0014 section 2)."""
        check_revision(revision)
        return self._in_session(self._commit, revision)

    @staticmethod
    def _commit(session, revision):
        if revision not in session.revisions:
            session.revisions[revision] = session.call('commit', revision)
        return session.revisions[revision]

    def object_kind(self, name):
        """The type of object NAME, or None when the repository has none."""
        check_object_name(name)
        found = self._in_session(_Session.read, name)
        return found[1] if found is not None else None

    def object_type(self, commit, path):
        return self.object_kind(f'{commit}:{path}')

    def blob(self, commit, path):
        name = check_object_name(f'{commit}:{path}')
        found = self._in_session(_Session.read, name)
        if found is None or found[1] != 'blob':
            raise PlanningError('GIT_FAILED', f'blob {name}: '
                                + ('no such object' if found is None else f'a {found[1]}, not a blob'))
        return found[2]

    def files(self, commit, directory):
        """The paths below DIRECTORY at COMMIT (``git ls-tree -r --name-only``), in git's order; []
        when it is absent; GIT_FAILED when COMMIT is no tree-ish."""
        return self._in_session(self._files, commit, directory)

    @staticmethod
    def _files(session, commit, directory):
        key = (commit, directory)
        if key in session.trees:
            return list(session.trees[key])
        files = session.call('files', commit, directory)
        if isinstance(commit, str) and OBJECT_ID_RE.fullmatch(commit):
            session.trees[key] = list(files)
        return files

    def export_tree(self, commit, subtree, destination):
        """Write the blob bytes of SUBTREE ('.' for the whole tree) at COMMIT into the empty
        directory DESTINATION, each at its repository-relative path (decision 0014 section 4: no
        end-of-line conversion, no attributes). EXPORT_REFUSED when it cannot be written safely."""
        return self._in_session(lambda session: session.call('export_tree', commit, subtree, destination))


# ---------------------------------------------------------------------------
# Pointers

def make_pointer(git, change, artifact, commit):
    if not CHANGE_ID_RE.fullmatch(change or ''):
        raise PlanningError('POINTER_MALFORMED', f'not an OpenSpec change id: {change!r}')
    if not isinstance(artifact, str) or not ARTIFACT_RE.fullmatch(artifact):
        raise PlanningError('POINTER_MALFORMED', f'not a relative artifact path: {artifact!r}')
    path = f'{CHANGES_DIR}/{change}/{artifact}'
    with git.session():
        kind = git.object_type(commit, path)
        if kind != 'blob':
            raise PlanningError('POINTER_ARTIFACT_MISSING', f'{path} is not a file at {commit}',
                                artifact=path, revision=commit)
        digest = hashlib.sha256(git.blob(commit, path)).hexdigest()
    return Pointer(change, artifact, commit, digest)


def resolve_pointer(git, text):
    """Re-resolve a pointer against the repository. Returns the Pointer or raises."""
    pointer = Pointer.parse(text)
    with git.session():
        commit = git.commit(pointer.revision)
        if commit != pointer.revision:
            raise PlanningError('POINTER_REVISION_MISSING',
                                f'the repository has no commit {pointer.revision}', pointer=text)
        kind = git.object_type(commit, pointer.repo_path)
        if kind != 'blob':
            raise PlanningError('POINTER_ARTIFACT_MISSING',
                                f'{pointer.repo_path} does not exist as a file at {commit}', pointer=text)
        actual = hashlib.sha256(git.blob(commit, pointer.repo_path)).hexdigest()
    if actual != pointer.digest:
        raise PlanningError('POINTER_DIGEST_MISMATCH',
                            f'{pointer.repo_path} at {commit} has sha256 {actual}, '
                            f'the pointer records {pointer.digest}', pointer=text, actual=actual)
    return pointer


# ---------------------------------------------------------------------------
# OpenSpec: no implementation checklist, no task tracking

def _scalar(text, key):
    """Value of a top-level 'key: value' line in a small YAML file, or None."""
    for line in text.splitlines():
        match = re.match(rf'^{re.escape(key)}\s*:\s*(.*?)\s*(?:#.*)?$', line)
        if match:
            return match.group(1).strip('\'"') or None
    return None


def schema_tracking(schema_text):
    """'untracked', 'tracked' or 'unknown' for an OpenSpec schema.yaml's apply.tracks."""
    lines = schema_text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith('apply'):
            continue
        head = re.match(r'^apply\s*:\s*(?:#.*)?$', line)
        if not head:
            return 'unknown'  # inline flow mapping or another form this scan does not read
        child_indent = None
        for child in lines[index + 1:]:
            if not child.strip() or child.lstrip().startswith('#'):
                continue
            indent = len(child) - len(child.lstrip(' '))
            if indent == 0:
                break
            if child_indent is None:
                child_indent = indent
            if indent != child_indent:
                continue  # nested content (a block scalar or a list)
            match = re.match(r'^\s+tracks\s*:\s*(.*?)\s*(?:#.*)?$', child)
            if match:
                return 'untracked' if match.group(1) in ('null', '~') else (
                    'unknown' if match.group(1) == '' else 'tracked')
        return 'untracked'
    return 'unknown'  # no apply section: what OpenSpec does then is not read here


def check_change(git, change, commit, openspec=None):
    """Refuse a change that is missing or carries or tracks its own implementation checklist."""
    with git.session():
        return _check_change(git, change, commit, openspec)


def _check_change(git, change, commit, openspec):
    directory = f'{CHANGES_DIR}/{change}'
    files = git.files(commit, directory)
    if not files:
        raise PlanningError('CHANGE_MISSING', f'{directory} does not exist at {commit}',
                            change=change, revision=commit)
    checklists = [name for name in files if name.rsplit('/', 1)[-1] == CHECKLIST_NAME]
    if checklists:
        raise PlanningError('OPENSPEC_CHECKLIST_PRESENT',
                            f'{", ".join(checklists)} duplicates the Backlog.md task list; Backlog.md '
                            'alone tracks implementation', files=checklists)
    schema = None
    meta = f'{directory}/.openspec.yaml'
    if git.object_type(commit, meta) == 'blob':
        schema = _scalar(git.blob(commit, meta).decode('utf-8', 'replace'), 'schema')
    if schema is None and git.object_type(commit, 'openspec/config.yaml') == 'blob':
        schema = _scalar(git.blob(commit, 'openspec/config.yaml').decode('utf-8', 'replace'), 'schema')
    result = {'schema': schema}
    schema_path = f'openspec/schemas/{schema}/schema.yaml' if schema and CHANGE_ID_RE.fullmatch(schema) else None
    in_repository = bool(schema_path) and git.object_type(commit, schema_path) == 'blob'
    static = schema_tracking(git.blob(commit, schema_path).decode('utf-8', 'replace')) \
        if in_repository else 'unknown'
    result['schema_in_repository'] = in_repository
    result['static_tracking'] = static
    if static == 'tracked':
        raise PlanningError('OPENSPEC_TRACKING_CONFIGURED',
                            f'schema {schema!r} at {commit} declares apply.tracks; Backlog.md alone '
                            'tracks implementation', schema=schema)
    if openspec is not None:
        result['openspec'] = openspec_apply_state(git, change, commit, openspec)
    elif static != 'untracked':
        raise PlanningError('OPENSPEC_TRACKING_UNKNOWN',
                            f'cannot establish from the repository that schema {schema!r} has no '
                            'apply.tracks; pass --openspec to ask OpenSpec itself', schema=schema)
    return result


def openspec_apply_state(git, change, commit, openspec_argv):
    """Ask OpenSpec, on an export of the exact revision (blob bytes, decision 0014 section 4),
    whether it tracks tasks for CHANGE. OpenSpec runs as one process tree (``run_tree``)."""
    with tempfile.TemporaryDirectory(prefix='aieh-planning-openspec-') as tmp:
        git.export_tree(commit, 'openspec', tmp)
        result = run_tree([*openspec_argv, 'instructions', 'apply', '--change', change, '--json'],
                          timeout=TOOL_TIMEOUT_S, env=tool_env(), cwd=tmp)
    if result.returncode != 0:
        raise PlanningError('OPENSPEC_FAILED', 'openspec instructions apply exited '
                            f'{result.returncode}: {result.stderr.decode("utf-8", "replace").strip()}')
    try:
        data = json.loads(result.stdout.decode('utf-8'))
    except ValueError as exc:
        raise PlanningError('OPENSPEC_FAILED', f'openspec printed no JSON: {exc}') from None
    if not isinstance(data, dict) or data.get('changeName') != change:
        raise PlanningError('OPENSPEC_FAILED', 'openspec answered for another change')
    if data.get('taskTrackingConfigured') is not False or data.get('tasks') != []:
        raise PlanningError('OPENSPEC_TRACKING_CONFIGURED',
                            f'OpenSpec tracks tasks for {change} at {commit} '
                            f'(taskTrackingConfigured={data.get("taskTrackingConfigured")!r})')
    return {key: data.get(key) for key in ('schemaName', 'state', 'taskTrackingConfigured', 'tasks',
                                           'progress')}


# ---------------------------------------------------------------------------
# Plan

def load_plan(data):
    if not isinstance(data, dict):
        raise PlanningError('PLAN_INVALID', 'the plan is not a JSON object')
    found_status = STATUS_KEYS & set(data)
    if found_status:
        raise PlanningError('STATUS_NOT_OWNED', f'the plan carries {sorted(found_status)}; '
                            'Backlog.md alone owns task status')
    unknown = set(data) - PLAN_KEYS
    if unknown or data.get('format') != PLAN_FORMAT:
        raise PlanningError('PLAN_INVALID', f'expected keys {sorted(PLAN_KEYS)} and format '
                            f'{PLAN_FORMAT!r}; unknown: {sorted(unknown)}')
    change = data.get('change')
    if not isinstance(change, str) or not CHANGE_ID_RE.fullmatch(change):
        raise PlanningError('PLAN_INVALID', f'not an OpenSpec change id: {change!r}')
    tasks = data.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        raise PlanningError('PLAN_INVALID', 'tasks must be a non-empty list')
    seen = []
    for number, task in enumerate(tasks, 1):
        where = f'task {number}'
        if not isinstance(task, dict):
            raise PlanningError('PLAN_INVALID', f'{where} is not an object')
        found_status = STATUS_KEYS & set(task)
        if found_status:
            raise PlanningError('STATUS_NOT_OWNED', f'{where} carries {sorted(found_status)}; '
                                'Backlog.md alone owns task status')
        unknown = set(task) - TASK_KEYS
        if unknown:
            raise PlanningError('PLAN_INVALID', f'{where} has unknown keys {sorted(unknown)}')
        key, title = task.get('key'), task.get('title')
        if not isinstance(key, str) or not CHANGE_ID_RE.fullmatch(key) or key in seen:
            raise PlanningError('PLAN_INVALID', f'{where}: key must be a new kebab-case id: {key!r}')
        if not isinstance(title, str) or not title.strip() or title != title.strip() or '\n' in title:
            raise PlanningError('PLAN_INVALID', f'{where}: title must be one non-empty trimmed line')
        description = task.get('description', '')
        if not isinstance(description, str):
            raise PlanningError('PLAN_INVALID', f'{where}: description must be a string')
        artifacts = task.get('artifacts')
        if not isinstance(artifacts, list) or not artifacts or \
                not all(isinstance(a, str) for a in artifacts) or len(set(artifacts)) != len(artifacts):
            raise PlanningError('POINTER_ABSENT', f'{where} ({key}) names no design artifact; every '
                                'task needs a source pointer')
        depends = task.get('depends_on', [])
        if not isinstance(depends, list) or not all(isinstance(d, str) for d in depends) \
                or len(set(depends)) != len(depends):
            raise PlanningError('PLAN_INVALID', f'{where}: depends_on must be a list of task keys')
        for dep in depends:
            if dep not in seen:
                raise PlanningError('PLAN_DEPENDENCY_UNKNOWN',
                                    f'{where} ({key}) depends on {dep!r}, which is not an earlier '
                                    'task of this plan')
        seen.append(key)
    return {'change': change, 'tasks': tasks}


# ---------------------------------------------------------------------------
# Backlog.md

class Backlog:
    # The process runner, a dependency-injection seam for tests: None (the default) runs
    # Backlog.md as one process tree (run_tree: an npm shim's node child ends with it). A runner
    # takes subprocess.run's arguments and returns its CompletedProcess; it is given to the
    # constructor, or set on the class.
    runner = None

    def __init__(self, argv_prefix, project, runner=None):
        self.argv_prefix = list(argv_prefix)
        self.project = Path(project)
        self.runner = type(self).runner if runner is None else runner

    def run(self, *args):
        if tuple(args[:2]) not in BACKLOG_COMMANDS:
            raise PlanningError('ADAPTER_REFUSED', f'the adapter does not issue backlog {" ".join(args[:2])}')
        options = args[:args.index('--')] if '--' in args else args  # after '--': the title only
        if any(arg in STATUS_FLAGS or arg.startswith(tuple(f + '=' for f in STATUS_FLAGS))
               for arg in options):
            raise PlanningError('ADAPTER_REFUSED', 'the adapter never sets a Backlog.md status')
        # Within one operation (operation()) each read is made once, a snapshot: the same
        # command in the same directory answers as it did; a create ends that snapshot.
        op = _OPERATION.get()
        read = tuple(args[:2]) in BACKLOG_READS
        key = (tuple(self.argv_prefix), str(self.project), tuple(args))
        if op is not None and not read:
            for stale in [k for k in op.backlog_reads if k[:2] == key[:2]]:
                del op.backlog_reads[stale]
        if op is not None and read and key in op.backlog_reads:
            out, failure = op.backlog_reads[key]
            if failure is not None:
                raise PlanningError('BACKLOG_FAILED', failure)
            return out
        if self.runner is None:
            result = run_tree([*self.argv_prefix, *args], timeout=TOOL_TIMEOUT_S, env=tool_env(), cwd=self.project)
        else:
            result = self.runner([*self.argv_prefix, *args], cwd=self.project, capture_output=True,
                                 stdin=subprocess.DEVNULL, timeout=TOOL_TIMEOUT_S, env=tool_env())
        if result.returncode != 0:
            failure = (f'backlog {" ".join(args[:2])} exited {result.returncode}: '
                       + (result.stderr or result.stdout).decode('utf-8', 'replace').strip())
            if op is not None and read:
                op.backlog_reads[key] = (None, failure)
            raise PlanningError('BACKLOG_FAILED', failure)
        out = result.stdout.decode('utf-8')
        if op is not None and read:
            op.backlog_reads[key] = (out, None)
        return out

    def _json(self, kind, *args):
        try:
            data = json.loads(self.run(*args))
        except ValueError as exc:
            raise PlanningError('BACKLOG_OUTPUT', f'backlog {" ".join(args[:2])} printed no JSON: {exc}') from None
        if not isinstance(data, dict) or data.get('schemaVersion') != 1 or data.get('kind') != kind:
            raise PlanningError('BACKLOG_OUTPUT', f'expected a schemaVersion 1 {kind!r} envelope')
        return data

    def list_tasks(self):
        tasks = self._json('task-list', 'task', 'list', '--json').get('tasks')
        if not isinstance(tasks, list) or not all(isinstance(t, dict) and isinstance(t.get('id'), str)
                                                   for t in tasks):
            raise PlanningError('BACKLOG_OUTPUT', 'task-list without a list of tasks with ids')
        return tasks

    def view(self, task_id):
        if not TASK_ID_RE.fullmatch(task_id or ''):
            raise PlanningError('TASK_ID_INVALID', f'not a Backlog.md task id: {task_id!r}')
        task = self._json('task-view', 'task', 'view', task_id, '--json').get('task')
        if not isinstance(task, dict) or not isinstance(task.get('id'), str) \
                or task['id'].upper() != task_id.upper():
            raise PlanningError('BACKLOG_OUTPUT', f'task-view did not return {task_id}')
        return task

    def create(self, title, description, references, dependencies):
        args = ['task', 'create']
        if description:
            args.append(f'--description={description}')
        args += [f'--ref={ref}' for ref in references]
        if dependencies:
            args.append('--dep=' + ','.join(dependencies))
        args += ['--plain', '--', title]
        before = {t['id'] for t in self.list_tasks()}
        self.run(*args)
        new = [t['id'] for t in self.list_tasks() if t['id'] not in before]
        if len(new) != 1:
            raise PlanningError('BACKLOG_OUTPUT', f'expected exactly one new task after create, found {new}')
        return new[0]


def create_tasks(git, backlog, plan, revision, openspec=None):
    """Create the plan's tasks in Backlog.md with source pointers and dependencies."""
    plan = load_plan(plan)
    change = plan['change']
    with git.session():
        commit = git.commit(revision)
        if commit is None:
            raise PlanningError('POINTER_REVISION_MISSING', f'the repository has no commit {revision!r}')
        openspec_state = check_change(git, change, commit, openspec)
        planned = []
        for task in plan['tasks']:
            pointers = [make_pointer(git, change, artifact, commit).text for artifact in task['artifacts']]
            planned.append((task, pointers))
    existing = backlog.list_tasks()
    for task, pointers in planned:
        for other in existing:
            if other.get('title') == task['title'] and other.get('references') == pointers:
                raise PlanningError('BACKLOG_DUPLICATE', f'{other["id"]} already maps {task["key"]} '
                                    f'from {change}@{commit}', task=other['id'])
    ids, created = {}, []
    try:
        for task, pointers in planned:
            deps = [ids[key] for key in task.get('depends_on', [])]
            new_id = backlog.create(task['title'], task.get('description', ''), pointers, deps)
            ids[task['key']] = new_id
            created.append({'key': task['key'], 'id': new_id})
            view = backlog.view(new_id)
            if view.get('title') != task['title'] or view.get('references') != pointers \
                    or [d.upper() for d in view.get('dependencies') or []] != [d.upper() for d in deps]:
                raise PlanningError('BACKLOG_MISMATCH', f'{new_id} does not carry the title, references '
                                    'and dependencies the adapter gave it')
            created[-1].update({'title': task['title'], 'references': pointers, 'dependencies': deps})
    except PlanningError as exc:
        exc.details['created'] = created
        raise
    return {'format': RESULT_FORMAT, 'change': change, 'revision': commit,
            'openspec': openspec_state, 'tasks': created}


def resolve_tasks(git, backlog, task_ids=None):
    """Re-resolve every OpenSpec pointer of the given (or all) Backlog.md tasks."""
    if not task_ids:
        task_ids = [t['id'] for t in backlog.list_tasks()]
    report = []
    with git.session():
        for task_id in task_ids:
            task = backlog.view(task_id)
            refs = task.get('references') or []
            pointers = [r for r in refs if isinstance(r, str) and r.startswith(POINTER_PREFIX)]
            entry = {'id': task['id'], 'pointers': []}
            if not pointers:
                entry['failure'] = {'code': 'POINTER_ABSENT',
                                    'message': f'{task["id"]} carries no OpenSpec source pointer'}
            for text in pointers:
                entry['pointers'].append(_resolve_entry(git, text))
            report.append(entry)
    return report


def _resolve_entry(git, text):
    try:
        resolve_pointer(git, text)
        return {'pointer': text, 'resolved': True}
    except PlanningError as exc:
        return {'pointer': text, 'resolved': False, 'code': exc.code, 'message': exc.message}


def _failures(report):
    for entry in report:
        if 'failure' in entry:
            yield entry['id'], None, entry['failure']['code'], entry['failure']['message']
        for item in entry['pointers']:
            if not item['resolved']:
                yield entry['id'], item['pointer'], item['code'], item['message']


# ---------------------------------------------------------------------------
# Command line

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create', help='create the plan\'s Backlog.md tasks with source pointers')
    create.add_argument('--project', required=True, type=Path)
    create.add_argument('--plan', required=True, type=Path)
    create.add_argument('--revision', required=True)
    create.add_argument('--backlog', required=True)
    create.add_argument('--openspec')
    resolve = sub.add_parser('resolve', help='re-resolve source pointers')
    resolve.add_argument('--project', required=True, type=Path)
    resolve.add_argument('--pointer', action='append', default=[])
    resolve.add_argument('--backlog')
    resolve.add_argument('--task', action='append', default=[])
    pointer = sub.add_parser('pointer', help='print the source pointer of one artifact')
    pointer.add_argument('--project', required=True, type=Path)
    pointer.add_argument('--change', required=True)
    pointer.add_argument('--artifact', required=True)
    pointer.add_argument('--revision', required=True)
    args = parser.parse_args(argv)
    try:
        git = Git(args.project)
        if args.command == 'create':
            try:
                plan = json.loads(args.plan.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                raise CannotRun(f'cannot read the plan: {exc}') from None
            backlog = Backlog(tool_argv(args.backlog), args.project)
            openspec = tool_argv(args.openspec) if args.openspec else None
            print(json.dumps(create_tasks(git, backlog, plan, args.revision, openspec), indent=2))
            return 0
        if args.command == 'pointer':
            with operation(), git.session():
                commit = git.commit(args.revision)
                if commit is None:
                    raise PlanningError('POINTER_REVISION_MISSING',
                                        f'the repository has no commit {args.revision!r}')
                text = make_pointer(git, args.change, args.artifact, commit).text
            print(text)
            return 0
        if bool(args.pointer) == bool(args.backlog) or (args.task and not args.backlog):
            raise CannotRun('resolve takes either --pointer ... or --backlog CMD [--task ID ...]')
        with operation():  # one resolution from the command line is one operation (F-09.4)
            if args.pointer:
                with git.session():
                    report = [{'id': None, 'pointers': [_resolve_entry(git, p) for p in args.pointer]}]
            else:
                report = resolve_tasks(git, Backlog(tool_argv(args.backlog), args.project), args.task)
        failures = list(_failures(report))
        print(json.dumps({'format': RESOLVE_FORMAT, 'tasks': report}, indent=2))
        for task_id, text, code, message in failures:
            print(f'FAIL {task_id or "-"} {text or "-"}: {code}: {message}', file=sys.stderr)
        return 1 if failures else 0
    except PlanningError as exc:
        print(f'FAIL {exc.code}: {exc.message}', file=sys.stderr)
        if exc.details.get('created'):
            print('Created before the failure (left in Backlog.md, not rolled back): '
                  + json.dumps(exc.details['created']), file=sys.stderr)
        return 1
    except (CannotRun, subprocess.TimeoutExpired, OSError) as exc:
        print(f'ERROR {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
