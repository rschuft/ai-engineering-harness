"""The dispatcher lock's dynamic census (E-01.4.2 slice 5a, completion condition 4; not a test module itself).

Usage:  <tools python> -I -B lock_census_runner.py OUT_JSON PATTERN[:CLASS,...] [PATTERN[:CLASS,...] ...]

Wraps ``IntegrationStore.reserve_attempt`` and ``IntegrationStore.transition`` at the class level with recorders,
then runs the dispatch suite's test modules matching each PATTERN (``unittest`` discovery in this directory; with
CLASS names, only those classes), less ``test_dispatcher_lock`` (the test that launches this runner). Every ``reserve_attempt``, and every transition of a
typed attempt (``attempt/v1/``) or a turn journal (``dispatch/attempt/<id>/turn``) into ``dispatched``, is recorded
with the site that made it (the first frame outside the store and the dispatch modules' pass-through helpers
``_mark``, ``_mark_end`` and ``_settle``), whether that site is production code (``integrations/dispatch/*.py``) or a
test's, and whether the calling thread held the store's dispatcher lock. The record, the tests run and their failures
are written to OUT_JSON as JSON.
"""
from pathlib import Path
import functools
import importlib.util
import io
import json
import re
import sys
import unittest

HERE = Path(__file__).resolve().parent
DISPATCH = HERE.parent
PASS_THROUGH = frozenset({'_mark', '_mark_end', '_settle'})
TURN_RE = re.compile(r'dispatch/attempt/[0-9a-f-]{36}/turn')
SELF_MODULE = 'test_dispatcher_lock'


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


di = _load('dispatch_inputs', DISPATCH / 'dispatch_inputs.py')
store_mod = di.store
lock = di._dispatcher_lock_module()
STORE_FILE = Path(store_mod.__file__).resolve()
CALLS = []


def site_of(frame):
    """(module file name, function, production?) of the first frame that is neither the store nor a pass-through."""
    while frame is not None:
        path = Path(frame.f_code.co_filename).resolve()
        if path == STORE_FILE or (path.parent == DISPATCH and frame.f_code.co_name in PASS_THROUGH):
            frame = frame.f_back
            continue
        return path.name, frame.f_code.co_name, path.parent == DISPATCH
    return None, None, False


def record(kind, store, key):
    name, function, production = site_of(sys._getframe(2))
    CALLS.append({'kind': kind, 'key': key, 'module': name, 'function': function, 'production': production,
                  'held': lock.held_by_this_thread(getattr(store, 'path', None))})


def install():
    reserve_attempt, transition = store_mod.IntegrationStore.reserve_attempt, store_mod.IntegrationStore.transition

    @functools.wraps(reserve_attempt)
    def recording_reserve_attempt(self, identity, intent, *, actor):
        record('reserve_attempt', self, getattr(identity, 'operation_key', None))
        return reserve_attempt(self, identity, intent, actor=actor)

    @functools.wraps(transition)
    def recording_transition(self, operation_key, to_state, **kwargs):
        if to_state == 'dispatched' and isinstance(operation_key, str) and (
                operation_key.startswith(store_mod.KEY_PREFIX) or TURN_RE.fullmatch(operation_key)):
            record('typed-dispatched' if operation_key.startswith(store_mod.KEY_PREFIX) else 'turn-dispatched',
                   self, operation_key)
        return transition(self, operation_key, to_state, **kwargs)
    store_mod.IntegrationStore.reserve_attempt = recording_reserve_attempt
    store_mod.IntegrationStore.transition = recording_transition


def selected(suite, classes=()):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from selected(item, classes)
        elif not item.id().startswith(SELF_MODULE + '.') and (not classes or type(item).__name__ in classes):
            yield item


def main(argv):
    out, patterns = Path(argv[0]), argv[1:]
    install()
    loader, tests = unittest.TestLoader(), unittest.TestSuite()
    for spec in patterns:
        pattern, _, classes = spec.partition(':')
        tests.addTests(selected(loader.discover(str(HERE), pattern=pattern, top_level_dir=str(HERE)),
                                tuple(filter(None, classes.split(',')))))
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(tests)
    out.write_text(json.dumps({'calls': CALLS, 'run': result.testsRun,
                               'failures': [t.id() for t, _ in result.failures + result.errors]}), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
