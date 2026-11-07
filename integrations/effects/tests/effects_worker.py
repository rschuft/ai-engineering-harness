"""Subprocess worker for the effects store tests (not a test module itself).

Usage:  python -I -B effects_worker.py <command> <root> <principal> [args...]

The worker opens the store with the library-only fixture location policy (the
tests' roots live in a temporary directory) and the given custody principal. Each
command prints JSON lines on stdout and flushes after each, so the parent waits
on the worker's own output (and its exit), never on a fixed sleep.

  reserve-and-exit REQUEST       reserve, print the receipt, then os._exit(0) with
                                 the connection still open (no close, no checkpoint)
  applying-and-exit REQUEST      reserve and begin (-> applying), print, os._exit(0)
  hold-uncommitted REQUEST       BEGIN IMMEDIATE, insert the receipt and its journal
                                 event, print {"ready": true} and block until killed
  hold-open                      open the store, print {"ready": true}, block on stdin
"""
from pathlib import Path
import dataclasses
import importlib.util
import json
import os
import sys

MODULE = Path(__file__).resolve().parents[1] / 'effects_store.py'
_spec = importlib.util.spec_from_file_location('effects_store', MODULE)
store_mod = importlib.util.module_from_spec(_spec)
sys.modules['effects_store'] = store_mod
_spec.loader.exec_module(store_mod)


def emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + '\n')
    sys.stdout.flush()


def request_from(text: str):
    data = json.loads(text)
    return store_mod.EffectRequest(data['operation_kind'], data['target_identity'],
                                   store_mod.Authority(**data['authority']), data['inputs'])


def main(argv):
    command, root, principal, *rest = argv
    store = store_mod.open_effects_store(root, principal=principal, policy=store_mod.fixture_location_policy())
    if command == 'reserve-and-exit':
        result = store.reserve(request_from(rest[0]), actor='executor-worker')
        emit({'created': result.created, 'receipt': dataclasses.asdict(result.receipt)})
        os._exit(0)
    if command == 'applying-and-exit':
        result = store.reserve(request_from(rest[0]), actor='executor-worker')
        receipt = store.begin(result.receipt.effect_key, actor='executor-worker')
        emit({'receipt': dataclasses.asdict(receipt)})
        os._exit(0)
    if command == 'hold-uncommitted':
        request = request_from(rest[0])
        key_inputs = request.key_inputs()
        store.conn.execute('BEGIN IMMEDIATE')
        store._insert_receipt(store_mod.derive_effect_key(key_inputs), key_inputs,
                              store_mod._canonical(key_inputs), 'executor', 'reserved', 'executor-worker', None)
        emit({'ready': True, 'in_transaction': store.conn.in_transaction})
        sys.stdin.readline()  # blocks until the parent kills this process
        os._exit(3)
    if command == 'hold-open':
        emit({'ready': True})
        sys.stdin.readline()
        store.close()
        return 0
    raise SystemExit(f'unknown command {command}')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
