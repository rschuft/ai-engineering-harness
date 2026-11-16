"""A dispatcher-lock holder in another process, for test_dispatcher_lock.py (not a test module itself; the pattern of
integrations/store/tests/store_worker.py).

Usage:  python -I -B lock_holder.py <command> <store> [args...]

Each command prints one JSON line on stdout and flushes it, so the parent waits on the holder's own output (and its
exit), never on a fixed sleep; then it blocks reading standard input until it is killed or its input closes.

  hold                  take the store's dispatcher lock
  dispatched IDENTITY   take the lock, open the store, reserve the typed attempt IDENTITY (the JSON of an
                        AttemptIdentity's fields) and move it to dispatched, as dispatch does before its create
  orphan                take the lock, mark its handle inheritable and start a child (close_fds=False) that
                        inherits it and blocks on the same standard input; print the child's pid
"""
from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys

DISPATCH = Path(__file__).resolve().parents[1]
REPO = DISPATCH.parents[1]
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + '\n')
    sys.stdout.flush()


def main(argv) -> int:
    command, store_path = argv[0], argv[1]
    lock = _load('dispatcher_lock', DISPATCH / 'dispatcher_lock.py')
    lock.acquire(store_path)
    if command == 'hold':
        emit({'held': True, 'pid': os.getpid()})
    elif command == 'dispatched':
        store_mod = _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')
        store = store_mod.open_store(store_path)
        identity = store_mod.AttemptIdentity(**json.loads(argv[2]))
        store.reserve_attempt(identity, {'kind': 'lock-holder'}, actor='lock-holder')
        store.transition(identity.operation_key, 'dispatched', actor='lock-holder', reason='create',
                         expected_from='reserved')
        emit({'held': True, 'dispatched': identity.operation_key, 'pid': os.getpid()})
    elif command == 'orphan':
        fd = lock._HOLDS[lock._key(lock.lock_path(store_path))].fd
        os.set_inheritable(fd, True)
        child = subprocess.Popen([sys.executable, '-I', '-c', 'import sys; sys.stdin.read()'], close_fds=False,
                                 creationflags=NO_WINDOW)
        emit({'held': True, 'child': child.pid, 'pid': os.getpid(), 'inheritable': os.get_inheritable(fd)})
    else:
        raise SystemExit(f'unknown command {command!r}')
    sys.stdin.read()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
