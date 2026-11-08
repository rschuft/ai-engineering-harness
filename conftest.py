"""pytest over the repository's unittest suites (plan leaf F-09.2; docs/development.md#testing).

pytest and pytest-xdist run the unchanged standard-library suites as a second, parallel runner;
`task test` stays the stdlib serial run. This file:

- maps each test class's declared category (F-09.1: a class attribute ``category`` or the
  module's ``CATEGORY``, read by ``tools/test_profile.py``'s own ``class_category``) to the
  pytest marker of that name, and refuses a class without a valid category (with
  ``--strict-markers``, a marker that pyproject.toml does not declare is refused too);
- holds the **unit guard**: while a ``unit`` test runs (its setup, with ``setUpClass`` and
  ``setUpModule``, its call and its teardown), an audit hook refuses a process launch, a socket
  or an ``os.chdir`` (the profile's own audit events) and the test fails, naming each event;
- records each test's outcome as the stdlib runner reports it (``--aieh-outcomes FILE``), and
  compares them with a stdlib profile (``--aieh-conformance PROFILE``, from
  ``tools/test_profile.py run``): the dual-runner conformance check;
- collects only what ``python -m unittest discover -s <suite>`` collects: no subdirectory of a
  suite directory (unittest descends only into packages, and no suite has one).

It refuses to run with bytecode writing enabled: run it with ``python -I -B`` and
``PYTHONDONTWRITEBYTECODE=1`` (the xdist workers do not inherit ``-B``), as the test:* targets
of Taskfile.yml do.
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent


def _load_profile():
    name = 'aieh_test_profile_for_conftest'
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, REPO / 'tools' / 'test_profile.py')
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


profile = _load_profile()
CATEGORIES = profile.CATEGORIES
OUTCOMES_SCHEMA = 'ai-engineering-harness/pytest-outcomes/v1'
# The audit events the profile counts as launches, sockets and os.chdir.
GUARDED_EVENTS = frozenset(event for event, counter in profile.EVENT_COUNTER.items()
                           if counter in ('launches', 'sockets', 'chdir'))
_SEVERITY = profile._SEVERITY


class UnitGuardViolation(RuntimeError):
    """A unit test launched a process, opened a socket or changed directory."""


# --------------------------------------------------------------------------- the unit guard

_GUARD = {'nodeid': None, 'events': []}


def _audit(event, args):
    if event in GUARDED_EVENTS and _GUARD['nodeid'] is not None:
        _GUARD['events'].append(event)
        raise UnitGuardViolation(f'unit guard: {event} in the unit test {_GUARD["nodeid"]}')


sys.addaudithook(_audit)


def _guarded(item):
    """Run one phase of `item` (a hook wrapper's body) under the guard when it is a unit test."""
    if item.get_closest_marker('unit') is None:
        return (yield)
    _GUARD['nodeid'], _GUARD['events'] = item.nodeid, []
    try:
        return (yield)
    finally:
        events, _GUARD['nodeid'] = _GUARD['events'], None
        if events:
            pytest.fail(f'unit guard: the unit test {item.nodeid} made {", ".join(events)}; a unit test '
                        'launches no process, opens no socket and calls no os.chdir, in its tests or '
                        'its class and module fixtures (docs/development.md#testing)', pytrace=False)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    return (yield from _guarded(item))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    return (yield from _guarded(item))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    return (yield from _guarded(item))


# --------------------------------------------------------------------------- configuration

def pytest_addoption(parser):
    group = parser.getgroup('aieh', 'AI Engineering Harness (conftest.py)')
    group.addoption('--aieh-outcomes', metavar='FILE',
                    help='write each test id and outcome, as the stdlib runner reports them, to FILE')
    group.addoption('--aieh-conformance', metavar='PROFILE',
                    help='fail unless the ids and outcomes equal those of a full stdlib profile '
                         '(tools/test_profile.py run --out PROFILE); needs the whole collection')


def suites(repo=REPO):
    """[(name, start directory)] of `task test`, read from Taskfile.yml as the profile reads it."""
    return profile.select_suites([], repo)


def pytest_configure(config):
    if not sys.dont_write_bytecode:
        raise pytest.UsageError('conftest.py: run pytest with python -I -B and PYTHONDONTWRITEBYTECODE=1 '
                                '(the test:* targets of Taskfile.yml do), so that nothing is written '
                                'inside the checkout')
    declared = {line.split(':', 1)[0].strip() for line in config.getini('markers')}
    if not set(CATEGORIES) <= declared:
        raise pytest.UsageError(f'conftest.py: pyproject.toml must declare a marker for every category: '
                                f'{", ".join(sorted(set(CATEGORIES) - declared))} missing')
    config._aieh_suites = [(name, (Path(config.rootpath) / start).resolve()) for name, start in
                           suites(Path(config.rootpath))]


def pytest_ignore_collect(collection_path, config):
    """unittest discovery does not descend into a suite directory's subdirectories (none is a
    package); neither does this collection."""
    if collection_path.is_dir():
        for _, start in getattr(config, '_aieh_suites', ()):
            if collection_path != start and collection_path.is_relative_to(start):
                return True
    return None


def test_id(item):
    """The stdlib runner's id of a collected unittest method: TestCase.id()."""
    return f'{item.cls.__module__}.{item.cls.__qualname__}.{item.name}'


def pytest_collection_modifyitems(session, config, items):
    problems = []
    for item in items:
        cls = getattr(item, 'cls', None)
        if cls is None or not issubclass(cls, unittest.TestCase):
            problems.append(f'{item.nodeid}: not a unittest.TestCase method')
            continue
        category, _ = profile.class_category(cls)
        if category not in CATEGORIES:
            problems.append(f'{item.nodeid}: class {profile.class_id(cls)} has category {category!r}; '
                            f'declare one of {", ".join(CATEGORIES)}')
            continue
        item.add_marker(category)
    if problems:
        raise pytest.UsageError('conftest.py: ' + '; '.join(problems))


# --------------------------------------------------------------------------- outcomes

def _suite_of(item):
    path = Path(item.path).resolve()
    for name, start in item.config._aieh_suites:
        if path.parent == start:
            return name
    return None


def _fixture_row(item, excinfo, phase):
    """The stdlib runner's row for an error or skip raised by a class or module fixture: unittest
    reports it once, as `setUpClass (module.Class)`, and does not run that class's tests."""
    names, error, seen = set(), excinfo.value, set()
    while error is not None and id(error) not in seen:  # the guard's failure has the fixture's error as context
        seen.add(id(error))
        frame = error.__traceback__
        while frame is not None:
            names.add(frame.tb_frame.f_code.co_name)
            frame = frame.tb_next
        error = error.__cause__ or error.__context__
    cls = f'{item.cls.__module__}.{item.cls.__qualname__}'
    module = item.cls.__module__
    for frame, row in (('setUpModule', f'setUpModule ({module})'),
                       ('setUpClass', f'setUpClass ({cls})'),
                       ('tearDownModule', f'tearDownModule ({module})'),
                       ('tearDownClass', f'tearDownClass ({cls})')):
        if frame in names and (phase == 'setup') == frame.startswith('setUp'):
            return row
    return None


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    fixture_row = None
    if call.when in ('setup', 'teardown') and call.excinfo is not None and getattr(item, 'cls', None):
        fixture_row = _fixture_row(item, call.excinfo, call.when)
    report = yield
    if getattr(item, 'cls', None) is None:
        return report
    row = {'suite': _suite_of(item), 'id': test_id(item), 'outcome': None, 'counted': False}
    if report.when == 'call':
        row['counted'] = True
        if report.passed:
            row['outcome'] = 'ok'
        elif report.skipped:
            row['outcome'] = 'xfail' if hasattr(report, 'wasxfail') else 'skip'
        elif 'Unexpected success' in str(report.longrepr):
            row['outcome'] = 'xpass'
        else:
            failure = call.excinfo is not None and call.excinfo.errisinstance(item.cls.failureException)
            row['outcome'] = 'fail' if failure else 'error'
    elif report.failed or report.skipped:
        outcome = 'skip' if report.skipped else 'error'
        if fixture_row is not None:
            row.update(id=fixture_row, outcome=outcome)
        else:
            row.update(outcome=outcome, counted=report.when == 'setup')
    report.aieh_row = row
    return report


class Outcomes:
    """The controller's record of every report (xdist workers send theirs to it)."""

    def __init__(self):
        self.rows = {}       # (suite, id) -> outcome
        self.counted = {}    # nodeid -> suite, for tests the stdlib runner counts as run
        self.deselected = 0

    def add(self, report):
        row = getattr(report, 'aieh_row', None)
        if not row or row['outcome'] is None:
            return
        key = (row['suite'], row['id'])
        old = self.rows.get(key)
        if old is None or _SEVERITY[row['outcome']] > _SEVERITY[old]:
            self.rows[key] = row['outcome']
        if row['counted']:
            self.counted[report.nodeid] = row['suite']

    def document(self, workers):
        ran = {}
        for suite in self.counted.values():
            ran[suite] = ran.get(suite, 0) + 1
        return {'schema': OUTCOMES_SCHEMA, 'workers': workers,
                'suites': [{'name': name, 'tests': ran[name]} for name in sorted(ran, key=str)],
                'tests': [{'suite': s, 'id': i, 'outcome': o} for (s, i), o in sorted(self.rows.items(), key=str)]}


def differences(document, stdlib_profile):
    """Differences between the pytest outcomes and a stdlib profile's ids, outcomes and counts."""
    found = []
    want = {(t['suite'], t['id']): t['outcome'] for t in stdlib_profile['tests']}
    got = {(t['suite'], t['id']): t['outcome'] for t in document['tests']}
    for key in sorted(set(want) | set(got), key=str):
        if want.get(key) != got.get(key):
            found.append(f'{key[0]}: {key[1]}: stdlib {want.get(key)}, pytest {got.get(key)}')
    want_ran = {s['name']: s['tests'] for s in stdlib_profile['suites']}
    got_ran = {s['name']: s['tests'] for s in document['suites']}
    for name in sorted(set(want_ran) | set(got_ran), key=str):
        if want_ran.get(name) != got_ran.get(name):
            found.append(f'{name}: stdlib ran {want_ran.get(name)} tests, pytest {got_ran.get(name)}')
    return found


def _is_worker(config):
    return hasattr(config, 'workerinput')


_OUTCOMES = {'record': None}  # the controller's Outcomes; None in an xdist worker


def pytest_sessionstart(session):
    _OUTCOMES['record'] = None if _is_worker(session.config) else Outcomes()


def pytest_deselected(items):
    if _OUTCOMES['record'] is not None:
        _OUTCOMES['record'].deselected += len(items)


def pytest_runtest_logreport(report):
    if _OUTCOMES['record'] is not None:
        _OUTCOMES['record'].add(report)


def pytest_sessionfinish(session, exitstatus):
    config, record = session.config, _OUTCOMES['record']
    if record is None:
        return
    out, conformance = config.getoption('aieh_outcomes'), config.getoption('aieh_conformance')
    if not out and not conformance:
        return
    workers = getattr(config.option, 'numprocesses', None) or 0
    document = record.document(workers)
    if out:
        Path(out).write_text(json.dumps(document, indent=1) + '\n', encoding='utf-8')
    if conformance:
        terminal = config.pluginmanager.get_plugin('terminalreporter')
        if record.deselected:
            found = [f'{record.deselected} tests deselected; conformance needs the whole collection']
        else:
            stdlib = json.loads(Path(conformance).read_text(encoding='utf-8'))
            if stdlib.get('schema') != profile.PROFILE_SCHEMA:
                raise pytest.UsageError('--aieh-conformance needs a full profile (tools/test_profile.py run --out)')
            found = differences(document, stdlib)
        for line in found:
            terminal.write_line(f'CONFORMANCE DIFF: {line}')
        terminal.write_line(f'CONFORMANCE {"PASS" if not found else "FAIL"}: {len(document["tests"])} ids, '
                            f'{sum(s["tests"] for s in document["suites"])} tests run, workers {workers}')
        if found and session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
