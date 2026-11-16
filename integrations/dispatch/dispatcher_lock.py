"""The dispatcher lock (plan leaf E-01.4.2, slice 5a; the architect's ruling R17; draft decision 0027 points 2 and 3).

One exclusive, non-blocking operating-system lock per integration store: the file ``<store file name>.dispatcher.lock``
beside the store, in the store's own directory and custody (``lock_path``). It holds no data (0 bytes) and is never
deleted. The operating system releases it when the holder's handle closes or its process ends, however it ends.

Who holds it, and for how long (R17 point 2):

- ``dispatch_inputs.dispatch``: from before anything is resolved or reserved until the create's outcome transition
  has committed, or the call is left by an exception;
- ``attempt_run.run_attempt``: from before its first call until the message's outcome is recorded (never while the
  turn is waited for); ``attempt_run.send_message`` takes it itself, re-entrantly;
- ``restart_recovery.recover``: throughout.

``end_attempt``, ``end_interrupted_attempt`` and the cause commands never take it: the engineering manager must be
able to end an attempt whose dispatcher hangs (R17 point 5).

**The invariant** (R17 point 3). I-1: a typed attempt or a turn journal is moved into ``dispatched`` only by a thread
that holds the lock, and that thread holds it until it has recorded that row's outcome, or its act has ended without
one. I-2: a typed attempt is reserved, and leaves ``reserved``, inside one held region. **What it proves** (point 4): a
holder that finds a typed attempt ``reserved`` or ``dispatched``, or a turn journal ``dispatched``, has established
that the act which wrote that row has ended without recording its outcome. It proves nothing about the Agent Server.

**Busy and unavailable.** The lock is re-entrant in the holding thread; another thread of the same process is refused
like another process (``Busy``: the registry below refuses it, the operating system refuses another handle and
another process). A lock file that cannot be opened or created is ``Unavailable``: never a pass, never reported as
busy. The dispatch modules raise them as ``DISPATCHER_BUSY`` and ``DISPATCHER_LOCK_UNAVAILABLE``
(``dispatch_inputs.dispatcher_lock``), before anything is reserved or sent.

**The technique** is ``integrations/ownerhost/service.py``'s ``InstanceLock`` (accepted at U-01.3): ``msvcrt.locking``
of one byte on Windows, ``fcntl.flock`` elsewhere. It is written again here, not imported, because a move would add a
module to the Integration process's supervisor, whose module set ``integrations/ownerhost/tests/test_structure.py``
pins (two copies are a recorded residual of the design). Measured on Windows (the tests' G12 facts): a second handle
in the same process is refused; a killed holder's lock is free once its exit is observed; a child the holder started,
alive after the holder died, does not keep it, even with the handle inheritable. **Not verified:** Linux and macOS,
where ``flock`` belongs to the open file description and a child that inherited the descriptor keeps it.

**What it is not** (point 7): a coordination control between cooperating dispatcher code, not a security boundary.
A process of the Owner's account that does not take it is not stopped (decision 0010 point 1).

Standard library only.
"""
from __future__ import annotations

import errno
import os
import threading
from contextlib import contextmanager
from pathlib import Path

SUFFIX = '.dispatcher.lock'
# The errors of a lock another handle holds: msvcrt.locking (LK_NBLCK) fails with EACCES (measured on Windows 11,
# CPython 3.12.10); fcntl.flock (LOCK_NB) with EWOULDBLOCK (EAGAIN). Any other error is not "busy".
BUSY_ERRNOS = frozenset(n for n in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, getattr(errno, 'EDEADLOCK', None),
                                    getattr(errno, 'EDEADLK', None)) if n is not None)


class LockError(Exception):
    """The lock was not taken: ``code`` is the dispatch refusal it stands for."""
    code = ''

    def __init__(self, path, detail: str):
        self.path, self.detail = path, detail
        super().__init__(f'{self.code}: {detail}')


class Busy(LockError):
    code = 'DISPATCHER_BUSY'


class Unavailable(LockError):
    code = 'DISPATCHER_LOCK_UNAVAILABLE'


def lock_path(store_path) -> Path:
    """The lock file of the integration store at STORE_PATH: ``<store file name>.dispatcher.lock`` beside it."""
    path = Path(store_path)
    if not path.name:
        raise ValueError(f'{store_path!r} names no store file')
    return path.with_name(path.name + SUFFIX)


def open_handle(path) -> int:
    """A read-write handle on the lock file at PATH, created (empty, mode 0600) when absent. Not inheritable (PEP
    446). Raises OSError when it cannot be opened or created."""
    return os.open(path, os.O_RDWR | os.O_CREAT, 0o600)


def lock_handle(fd: int) -> None:
    """Lock FD exclusively without blocking (one byte at offset 0, past the end of the empty file, on Windows).
    Raises OSError when it is not locked (its errno in BUSY_ERRNOS when another handle holds it)."""
    if os.name == 'nt':
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock_handle(fd: int) -> None:
    """Unlock and close FD (closing alone releases it; the explicit unlock keeps Windows' order)."""
    try:
        if os.name == 'nt':
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


class _Hold:
    __slots__ = ('fd', 'owner', 'depth')

    def __init__(self, fd: int, owner: int):
        self.fd, self.owner, self.depth = fd, owner, 1


# The process's holds, by lock file: the holding thread and its depth (re-entrance). Guarded by _GUARD.
_HOLDS: dict[str, _Hold] = {}
_GUARD = threading.Lock()


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _resolve(store_path) -> Path:
    if not isinstance(store_path, (str, os.PathLike)):
        raise Unavailable(store_path, f'the integration store names no file ({type(store_path).__name__})')
    try:
        return lock_path(store_path)
    except (ValueError, TypeError) as exc:
        raise Unavailable(store_path, str(exc)) from None


def acquire(store_path) -> None:
    """Take the lock of the store at STORE_PATH, or raise Busy (held by another thread, handle or process) or
    Unavailable (the file cannot be opened or created, or the lock fails otherwise). Re-entrant in the holding
    thread: each acquire needs its release."""
    path = _resolve(store_path)
    key, me = _key(path), threading.get_ident()
    with _GUARD:
        hold = _HOLDS.get(key)
        if hold is not None:
            if hold.owner != me:
                raise Busy(path, 'another thread of this process holds the dispatcher lock')
            hold.depth += 1
            return
        try:
            fd = open_handle(path)
        except OSError as exc:
            raise Unavailable(path, f'the lock file cannot be opened or created ({type(exc).__name__}, '
                                    f'errno {exc.errno})') from None
        try:
            lock_handle(fd)
        except OSError as exc:
            os.close(fd)
            if exc.errno in BUSY_ERRNOS:
                raise Busy(path, 'another handle or process holds the dispatcher lock') from None
            raise Unavailable(path, f'the lock file cannot be locked ({type(exc).__name__}, errno {exc.errno})') \
                from None
        _HOLDS[key] = _Hold(fd, me)


def release(store_path) -> None:
    """Release one acquire of the calling thread; the last one unlocks and closes the handle."""
    path = _resolve(store_path)
    key = _key(path)
    with _GUARD:
        hold = _HOLDS.get(key)
        if hold is None or hold.owner != threading.get_ident():
            raise RuntimeError('the dispatcher lock is not held by this thread')
        hold.depth -= 1
        if hold.depth:
            return
        del _HOLDS[key]
        unlock_handle(hold.fd)


def held_by_this_thread(store_path) -> bool:
    """Whether the calling thread holds the lock of the store at STORE_PATH."""
    try:
        key = _key(_resolve(store_path))
    except Unavailable:
        return False
    with _GUARD:
        hold = _HOLDS.get(key)
        return hold is not None and hold.owner == threading.get_ident()


@contextmanager
def held(store_path):
    """The lock held for the block (acquire, then release however the block is left)."""
    acquire(store_path)
    try:
        yield
    finally:
        release(store_path)
