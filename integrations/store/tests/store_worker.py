"""Subprocess worker for the integration store tests (not a test module itself).

Usage:  python -I -B store_worker.py <command> <db> [args...]

Each command prints JSON lines on stdout and flushes after each, so the parent
waits on the worker's own output (and its exit), never on a fixed sleep.

  reserve-and-exit KEY INTENT   reserve, print the result, then os._exit(0) with
                                the connection still open (no close, no checkpoint)
  get KEY                       print the reservation (or null) and its events
  hold-uncommitted KEY INTENT   BEGIN IMMEDIATE, insert the reservation rows, print
                                {"ready": true} and block on stdin until killed
  contend KEY INTENT            open, print {"ready": true}, wait for a "go" line
                                on stdin, reserve, print the outcome
  conversation-id KEY           print the deterministic conversation ID
  reserve-attempt IDENTITY INTENT
                                reserve a typed attempt (IDENTITY is the JSON of an
                                AttemptIdentity's fields), print the outcome, close
  reserve-attempt-and-exit IDENTITY INTENT
                                the same, then os._exit(0) with the connection open
  contend-attempt IDENTITY INTENT
                                open, print {"ready": true}, wait for "go", reserve the
                                typed attempt, print the outcome (or the refusal's type;
                                an sqlite3 error is reported as raw:<type>)
  attempts                      print every attempt with its typed identity and events
  scripted IDENTITY INTENT STEPS CRASH
                                run STEPS (comma list: reserve, then target states)
                                through the library; CRASH is none or
                                STEP|before-or-after|STATEMENT PREFIX|exit-or-hold:
                                stop at that statement of that step (prefix CALL with
                                before: before the library call), then os._exit(9)
                                or block until killed; without a crash, os._exit(0)
  contend-transition KEY STATE FROM
                                open, print {"ready": true}, wait for "go", transition
                                KEY to STATE expecting FROM, print the outcome
"""
from pathlib import Path
import dataclasses
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys

MODULE = Path(__file__).resolve().parents[1] / 'integration_store.py'
_spec = importlib.util.spec_from_file_location('integration_store', MODULE)
store_mod = importlib.util.module_from_spec(_spec)
sys.modules['integration_store'] = store_mod
_spec.loader.exec_module(store_mod)


def emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + '\n')
    sys.stdout.flush()


class CrashingConnection:
    """A test-side wrapper around the store's sqlite3 connection (no library seam needed).

    It delegates everything, and stops the process once, ``before`` or ``after`` the
    first statement that starts with ``prefix``: ``exit`` hard-exits (os._exit(9), no
    rollback, no close), ``hold`` prints a holding line and blocks on stdin until the
    parent kills the process. The library code that runs is the real one.
    """

    def __init__(self, conn, *, when, prefix, action, label):
        self._conn, self._when, self._prefix, self._action, self._label = conn, when, prefix, action, label

    def fire(self):
        emit({'crashed_at': self._label, 'in_transaction': self._conn.in_transaction})
        if self._action == 'hold':
            sys.stdin.readline()  # blocks until the parent kills this process
            os._exit(3)
        os._exit(9)

    def execute(self, sql, *args):
        hit = sql.lstrip().startswith(self._prefix)
        if hit and self._when == 'before':
            self.fire()
        result = self._conn.execute(sql, *args)
        if hit and self._when == 'after':
            self.fire()
        return result

    def __getattr__(self, name):
        return getattr(self._conn, name)


def main(argv):
    command, db, *rest = argv
    if command == 'conversation-id':
        emit({'conversation_id': store_mod.conversation_id_for(rest[0])})
        return 0
    store = store_mod.open_store(db)
    if command == 'reserve-and-exit':
        result = store.reserve(rest[0], json.loads(rest[1]), actor='worker')
        emit({'created': result.created, 'reservation': dataclasses.asdict(result.reservation)})
        os._exit(0)
    if command == 'get':
        reservation = store.get(rest[0])
        attempt = store.attempt_identity(rest[0])
        emit({'reservation': reservation and dataclasses.asdict(reservation),
              'attempt': attempt and dataclasses.asdict(attempt),
              'events': [dataclasses.asdict(e) for e in store.events(rest[0])]})
        store.close()
        return 0
    if command == 'hold-uncommitted':
        canonical = store_mod.canonical_intent(json.loads(rest[1]))
        store.conn.execute('BEGIN IMMEDIATE')
        store._insert_reservation(rest[0], canonical,
                                  hashlib.sha256(canonical.encode('utf-8')).hexdigest(), 'worker')
        emit({'ready': True, 'in_transaction': store.conn.in_transaction})
        sys.stdin.readline()  # blocks until the parent kills this process
        os._exit(3)
    if command == 'contend':
        emit({'ready': True})
        if sys.stdin.readline().strip() != 'go':
            return 2
        try:
            result = store.reserve(rest[0], json.loads(rest[1]), actor=f'worker-{os.getpid()}')
            emit({'outcome': 'created' if result.created else 'existing',
                  'conversation_id': result.reservation.conversation_id})
        except store_mod.ConflictingReservation:
            emit({'outcome': 'conflict'})
        store.close()
        return 0
    if command in ('reserve-attempt', 'reserve-attempt-and-exit', 'contend-attempt'):
        identity = store_mod.AttemptIdentity(**json.loads(rest[0]))
        intent = json.loads(rest[1])
        if command == 'contend-attempt':
            emit({'ready': True})
            if sys.stdin.readline().strip() != 'go':
                return 2
        try:
            result = store.reserve_attempt(identity, intent, actor=f'worker-{os.getpid()}')
            emit({'outcome': 'created' if result.created else 'existing',
                  'reservation': dataclasses.asdict(result.reservation),
                  'attempt': dataclasses.asdict(result.attempt)})
        except store_mod.StoreError as exc:
            emit({'outcome': type(exc).__name__})
        except sqlite3.Error as exc:  # never expected: reported, so a test can refuse it
            emit({'outcome': f'raw:{type(exc).__name__}', 'detail': str(exc)})
        if command == 'reserve-attempt-and-exit':
            os._exit(0)
        store.close()
        return 0
    if command == 'attempts':
        emit({'attempts': [{'reservation': dataclasses.asdict(r),
                            'attempt': (lambda a: a and dataclasses.asdict(a))(store.attempt_identity(r.operation_key)),
                            'events': [dataclasses.asdict(e) for e in store.events(r.operation_key)]}
                           for r in store.attempts()]})
        store.close()
        return 0
    if command == 'scripted':
        # scripted IDENTITY INTENT STEPS CRASH: run the real library calls in order and,
        # when CRASH names a step, stop the process at one statement of that step.
        identity = store_mod.AttemptIdentity(**json.loads(rest[0]))
        intent = json.loads(rest[1])
        steps = rest[2].split(',')
        crash = None if rest[3] == 'none' else rest[3].split('|')
        raw_conn = store.conn
        for index, step in enumerate(steps):
            if crash is not None and int(crash[0]) == index:
                store.conn = CrashingConnection(raw_conn, when=crash[1], prefix=crash[2], action=crash[3],
                                                label=rest[3])
                if crash[1] == 'before' and crash[2] == 'CALL':
                    store.conn.fire()  # before the library call: no statement of it runs
            if step == 'reserve':
                result = store.reserve_attempt(identity, intent, actor='scripted-worker')
                emit({'step': index, 'done': step, 'created': result.created,
                      'state': result.reservation.state})
            else:
                after = store.transition(identity.operation_key, step, actor='scripted-worker')
                emit({'step': index, 'done': step, 'state': after.state})
            store.conn = raw_conn
        if crash is not None:
            emit({'error': f'crash point {rest[3]} was never reached'})
            return 4
        os._exit(0)  # no close, no checkpoint: the commits live in the WAL
    if command == 'contend-transition':
        emit({'ready': True})
        if sys.stdin.readline().strip() != 'go':
            return 2
        try:
            after = store.transition(rest[0], rest[1], actor=f'worker-{os.getpid()}', expected_from=rest[2])
            emit({'outcome': 'transitioned', 'state': after.state})
        except store_mod.StoreError as exc:
            emit({'outcome': type(exc).__name__})
        except sqlite3.Error as exc:
            emit({'outcome': f'raw:{type(exc).__name__}', 'detail': str(exc)})
        store.close()
        return 0
    raise SystemExit(f'unknown command {command}')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
