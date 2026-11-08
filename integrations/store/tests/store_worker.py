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
                                typed attempt, print the outcome (or the refusal's type)
"""
from pathlib import Path
import dataclasses
import hashlib
import importlib.util
import json
import os
import sys

MODULE = Path(__file__).resolve().parents[1] / 'integration_store.py'
_spec = importlib.util.spec_from_file_location('integration_store', MODULE)
store_mod = importlib.util.module_from_spec(_spec)
sys.modules['integration_store'] = store_mod
_spec.loader.exec_module(store_mod)


def emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + '\n')
    sys.stdout.flush()


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
        if command == 'reserve-attempt-and-exit':
            os._exit(0)
        store.close()
        return 0
    raise SystemExit(f'unknown command {command}')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
