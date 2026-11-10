"""Profile the repository's unittest suites: counted process launches, temporary directories,
tests and wall time, per test, class, category and suite (plan leaf F-09.1).

The profile runs exactly the suites ``task test`` runs, serially, each in its own child
process, as ``python -I -B -m unittest discover -s <suite> -v`` would: the child calls the
same ``unittest.main`` entry point with the same arguments, from the repository root. The
only addition is an audit hook (``sys.addaudithook``) and a recording test result. The hook
patches nothing and only counts, so profiling does not change which tests run or how they
end; ``compare`` proves that against a plain run.

Counters (exact, per test and per class fixture; never sampled):

- ``launches``: process launches made by the test process itself, counted from the audit
  events ``subprocess.Popen``, ``os.system``, ``os.spawn``, ``os.posix_spawn``, ``os.exec``,
  ``os.fork``, ``os.forkpty``, ``os.startfile`` and ``_winapi.CreateProcess`` (the last only
  when it does not come from ``subprocess``, which already raised ``subprocess.Popen``). A
  launch attempt that fails (for example a missing executable) still counts. Processes that
  a child starts (grandchildren) are not counted: the hook lives in the test process only.
- ``mkdtemp``: ``tempfile.mkdtemp`` calls, which include every ``TemporaryDirectory``.
- ``sockets``: ``socket.socket`` objects created (``socket.__new__``).
- ``chdir``: ``os.chdir`` calls.
- ``tests``: tests run, from the test result.

Events are attributed to the running test (its ``setUp``, ``tearDown`` and cleanups
included), else to the class or module fixture that unittest is running (``setUpClass``,
``tearDownClass``, ``setUpModule``, ``tearDownModule``), else to the module being imported
during discovery, else to ``other``. Wall time is a median over ``--runs`` runs.

Every test class declares its category, ``unit``, ``contract``, ``integration``, ``e2e`` or
``performance``: a class attribute ``category`` or a module-level ``CATEGORY`` (the class
attribute wins). Both are plain attributes, inert under unittest. ``categories`` checks
every class mechanically without running a test.

Usage (from the repository root):
    python -I -B tools/test_profile.py run [--runs N] [--suite NAME ...] [--out FILE]
                                           [--compact-out FILE]
    python -I -B tools/test_profile.py categories [--suite NAME ...]
    python -I -B tools/test_profile.py compare --profile FILE [--suite NAME ...]

``run`` writes the full profile (every test's id, outcome, counters and wall time) to
``--out``, or to a new temporary directory outside the checkout, and prints a summary.
``--compact-out`` also writes the compact form kept as evidence (per class and category, no
per-test rows, a digest of the ids and outcomes). ``compare`` runs the plain unittest
commands without the profiler and checks that they give the same test ids and outcomes as
the profile.

Exit status: 0 PASS (every test passed, every class categorized, counters equal across
runs; ``compare``: identical), 1 FAIL, 2 could not run.
"""
import argparse
import collections
import contextlib
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROFILE_SCHEMA = 'ai-engineering-harness/test-profile/v1'
COMPACT_SCHEMA = 'ai-engineering-harness/test-profile-compact/v1'
CHILD_SCHEMA = 'ai-engineering-harness/test-profile-suite/v1'
CATEGORIES = ('unit', 'contract', 'integration', 'e2e', 'performance')
COUNTERS = ('launches', 'mkdtemp', 'sockets', 'chdir')

_DISCOVER = re.compile(r"^      - '\{\{\.PYTHON\}\} -I -B -m unittest discover -s (\S+) -v'$")
_TASK_REF = re.compile(r'^      - task: (\S+)$')

LAUNCH_EVENTS = frozenset({
    'subprocess.Popen', 'os.system', 'os.spawn', 'os.posix_spawn', 'os.exec', 'os.fork',
    'os.forkpty', 'os.startfile', '_winapi.CreateProcess'})
EVENT_COUNTER = {event: 'launches' for event in LAUNCH_EVENTS}
EVENT_COUNTER.update({'tempfile.mkdtemp': 'mkdtemp', 'socket.__new__': 'sockets',
                      'os.chdir': 'chdir'})

OUTCOMES = ('ok', 'fail', 'error', 'skip', 'xfail', 'xpass')
_SEVERITY = {'ok': 0, 'skip': 0, 'xfail': 0, 'xpass': 1, 'fail': 2, 'error': 3}
_FIXTURE_FRAMES = {'_handleClassSetUp', '_tearDownPreviousClass', '_handleModuleFixture',
                   '_handleModuleTearDown'}
_PYTHON = re.compile(r'^(python|pythonw|py)(\d+(\.\d+)?)?(\.exe)?$')
_GIT_VALUE_OPTIONS = frozenset({'-c', '-C', '--git-dir', '--work-tree', '--namespace',
                                '--super-prefix', '--config-env', '--exec-path', '--list-cmds'})


class ProfileError(Exception):
    """The profile could not be produced (exit 2)."""


# --------------------------------------------------------------------------- categories

def class_category(cls):
    """(category, source) for a test class: its ``category`` attribute, else its module's
    ``CATEGORY``; (None, None) when neither is declared."""
    value = getattr(cls, 'category', None)
    if value is not None:
        return value, 'class'
    module = sys.modules.get(cls.__module__)
    value = getattr(module, 'CATEGORY', None) if module is not None else None
    if value is not None:
        return value, 'module'
    return None, None


def iter_tests(suite):
    for item in suite:
        if hasattr(item, '__iter__') and not hasattr(item, 'id'):
            yield from iter_tests(item)
        else:
            yield item


def class_id(cls):
    return f'{cls.__module__}.{cls.__qualname__}'


# --------------------------------------------------------------------------- launch keys

def _basename(value):
    text = os.fsdecode(value) if isinstance(value, (bytes, os.PathLike)) else str(value)
    return re.split(r'[\\/]', text.strip().strip('"'))[-1]


def program_key(argv):
    """A stable, path-free name for a launched program: ``git <subcommand>``,
    ``python <script>``, ``python -m <module>``, ``python -c`` or the executable's name."""
    if not argv:
        return '?'
    name = _basename(argv[0]).lower()
    if name.endswith('.exe'):
        name = name[:-4]
    if _PYTHON.match(name) or name == _basename(sys.executable).lower().removesuffix('.exe'):
        i = 1
        while i < len(argv):
            arg = str(argv[i])
            if arg == '-m' and i + 1 < len(argv):
                return f'python -m {argv[i + 1]}'
            if arg == '-c':
                return 'python -c'
            if arg in ('-W', '-X'):
                i += 2
                continue
            if arg.startswith('-'):
                i += 1
                continue
            return f'python {_basename(arg)}'
        return 'python'
    if name == 'git':
        i = 1
        while i < len(argv):
            arg = str(argv[i])
            if arg in _GIT_VALUE_OPTIONS:
                i += 2
                continue
            if arg.startswith('-'):
                i += 1
                continue
            return f'git {_word(arg)}'
        return 'git'
    return name


def _word(arg):
    """A subcommand as it was given, or '<path>' when it is not a plain word."""
    return arg if re.fullmatch(r'[\w.-]+', arg) else '<path>'


def _split_command_line(line):
    text = os.fsdecode(line) if isinstance(line, bytes) else str(line or '')
    text = text.strip()
    if text.startswith('"'):
        first, _, rest = text[1:].partition('"')
    else:
        first, _, rest = text.partition(' ')
    return [first, *rest.split()]


def launch_argv(event, args):
    """The argv of an audited launch, as far as the event shows it."""
    try:
        if event == 'subprocess.Popen':
            executable, cmd = args[0], args[1]
            if isinstance(cmd, (str, bytes)):
                argv = _split_command_line(cmd)
            elif isinstance(cmd, os.PathLike):
                argv = [cmd]
            else:
                argv = list(cmd)
            if executable is not None and argv:
                argv[0] = executable
            return argv
        if event == '_winapi.CreateProcess':
            return _split_command_line(args[1]) if args[1] else [args[0]]
        if event in ('os.spawn', 'os.exec'):
            return [args[-3], *list(args[-2] or ())[1:]]
        if event == 'os.posix_spawn':
            return [args[0], *list(args[1] or ())[1:]]
        if event == 'os.system':
            return ['os.system']
        if event == 'os.startfile':
            return ['os.startfile']
        return [event]
    except (IndexError, TypeError):
        return [event]


# --------------------------------------------------------------------------- the child

def _stdlib_dirs():
    import sysconfig
    paths = sysconfig.get_paths()
    dirs = {os.path.normcase(os.path.abspath(paths[key])) for key in ('stdlib', 'platstdlib')}
    return tuple(d + os.sep for d in dirs)


class Recorder:
    """Counts audited events into the scope that is running (a test, a fixture, an import)."""

    def __init__(self, repo, suite_dir):
        self.repo = os.path.normcase(str(Path(repo).resolve())) + os.sep
        self.suite_dir = os.path.normcase(str(Path(suite_dir).resolve())) + os.sep
        self.stdlib = _stdlib_dirs()
        self.self_file = os.path.normcase(os.path.abspath(__file__))
        self.lock = threading.Lock()
        self.current = None          # the running test's record
        self.fixture = None          # the running fixture's record
        self.tests = []
        self.fixtures = {}
        self.imports = {}
        self.other = self._new_record()

    @staticmethod
    def _new_record(**extra):
        record = dict(extra)
        record.update({counter: 0 for counter in COUNTERS})
        record['programs'] = collections.Counter()
        return record

    def _relative(self, filename):
        path = os.path.normcase(os.path.abspath(filename))
        if path.startswith(self.repo):
            return path[len(self.repo):].replace(os.sep, '/')
        return '<outside>'

    def _origin(self, frame):
        while frame is not None:
            name = frame.f_code.co_filename
            path = os.path.normcase(os.path.abspath(name)) if not name.startswith('<') else name
            if not (name.startswith('<') or path.startswith(self.stdlib) or path == self.self_file):
                return self._relative(name)
            frame = frame.f_back
        return '<stdlib>'

    def _import_scope(self, frame):
        while frame is not None:
            code = frame.f_code
            if code.co_name == '<module>':
                path = os.path.normcase(os.path.abspath(code.co_filename))
                if path.startswith(self.suite_dir) and path.endswith('.py'):
                    module = frame.f_globals.get('__name__', '?')
                    return self.imports.setdefault(module, self._new_record(module=module))
            frame = frame.f_back
        return None

    def scope(self, frame):
        if self.current is not None:
            return self.current
        if self.fixture is not None:
            return self.fixture
        record = self._import_scope(frame)
        return record if record is not None else self.other

    def on_event(self, event, args, frame):
        counter = EVENT_COUNTER.get(event)
        if counter is None:
            return
        if event == '_winapi.CreateProcess':
            caller = frame.f_code.co_filename if frame is not None else ''
            if os.path.basename(caller) == 'subprocess.py':
                return
        with self.lock:
            record = self.scope(frame)
            record[counter] += 1
            if counter == 'launches':
                via = '' if event == 'subprocess.Popen' else f' [{event}]'
                key = f'{program_key(launch_argv(event, args))}{via} @ {self._origin(frame)}'
                record['programs'][key] += 1

    # fixtures -----------------------------------------------------------------------
    def fixture_owner(self, frame):
        while frame is not None:
            code = frame.f_code
            if code.co_name in _FIXTURE_FRAMES and os.path.basename(code.co_filename) == 'suite.py':
                local = frame.f_locals
                if code.co_name == '_handleClassSetUp':
                    return 'class', class_id(type(local['test']))
                if code.co_name == '_tearDownPreviousClass':
                    return 'class', class_id(local['previousClass'])
                if code.co_name == '_handleModuleFixture':
                    return 'module', local['currentModule']
                return 'module', local['previousModule']
            frame = frame.f_back
        return None

    def begin_fixture(self, frame):
        owner = self.fixture_owner(frame)
        if owner is None:
            return
        key = f'{owner[0]}:{owner[1]}'
        with self.lock:
            record = self.fixtures.setdefault(
                key, self._new_record(kind=owner[0], owner=owner[1], wall=0.0))
            record['_start'] = time.perf_counter()
            self.fixture = record

    def end_fixture(self):
        with self.lock:
            record, self.fixture = self.fixture, None
        if record is not None:
            record['wall'] += time.perf_counter() - record.pop('_start')


RECORDER = None


def _audit(event, args):
    recorder = RECORDER
    if recorder is not None and event in EVENT_COUNTER:
        recorder.on_event(event, args, sys._getframe(1))


def _make_result_class(base):
    class ProfilingResult(base):
        def startTest(self, test):
            recorder = RECORDER
            recorder.current = recorder._new_record(
                id=test.id(), cls=class_id(type(test)), outcome=None)
            recorder.current['_start'] = time.perf_counter()
            super().startTest(test)

        def stopTest(self, test):
            super().stopTest(test)
            recorder = RECORDER
            record, recorder.current = recorder.current, None
            if record is not None:
                record['wall'] = time.perf_counter() - record.pop('_start')
                record['outcome'] = record['outcome'] or 'ok'
                recorder.tests.append(record)

        def _setupStdout(self):
            if RECORDER.current is None:
                RECORDER.begin_fixture(sys._getframe(1))
            super()._setupStdout()

        def _restoreStdout(self):
            super()._restoreStdout()
            if RECORDER.current is None:
                RECORDER.end_fixture()

        def _mark(self, test, outcome):
            recorder = RECORDER
            record = recorder.current
            if record is not None and record['id'] == test.id():
                if record['outcome'] is None or _SEVERITY[outcome] > _SEVERITY[record['outcome']]:
                    record['outcome'] = outcome
            else:  # a class or module fixture failure (unittest's _ErrorHolder)
                holder = recorder._new_record(id=test.id(), cls=None, outcome=outcome, wall=0.0)
                recorder.tests.append(holder)

        def addSuccess(self, test):
            super().addSuccess(test)
            self._mark(test, 'ok')

        def addFailure(self, test, err):
            super().addFailure(test, err)
            self._mark(test, 'fail')

        def addError(self, test, err):
            super().addError(test, err)
            self._mark(test, 'error')

        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            self._mark(test, 'skip')

        def addExpectedFailure(self, test, err):
            super().addExpectedFailure(test, err)
            self._mark(test, 'xfail')

        def addUnexpectedSuccess(self, test):
            super().addUnexpectedSuccess(test)
            self._mark(test, 'xpass')

        def addSubTest(self, test, subtest, err):
            super().addSubTest(test, subtest, err)
            if err is not None:
                failure = issubclass(err[0], test.failureException)
                self._mark(test, 'fail' if failure else 'error')

    return ProfilingResult


def _class_rows(suite):
    """({class id: row}, {module: its CATEGORY or None}, [failed imports])."""
    rows, modules = {}, {}
    failed_imports = []
    for test in iter_tests(suite):
        cls = type(test)
        if cls.__module__ == 'unittest.loader' and cls.__name__ == '_FailedTest':
            failed_imports.append(test.id())
            continue
        key = class_id(cls)
        row = rows.get(key)
        if row is None:
            category, source = class_category(cls)
            row = rows[key] = {'id': key, 'module': cls.__module__, 'category': category,
                               'source': source, 'tests': 0}
            module = sys.modules.get(cls.__module__)
            modules[cls.__module__] = getattr(module, 'CATEGORY', None)
        row['tests'] += 1
    return rows, modules, failed_imports


def child_main(start_dir, out, discover_only):
    """Run one suite as `python -I -B -m unittest discover -s <start_dir> -v` would."""
    global RECORDER
    import unittest
    t0 = time.perf_counter()
    RECORDER = Recorder(REPO, start_dir)
    sys.addaudithook(_audit)
    state = {}

    if discover_only:
        loader = unittest.TestLoader()
        suite = loader.discover(start_dir)
        classes, modules, failed = _class_rows(suite)
        payload = {'schema': CHILD_SCHEMA, 'start_dir': start_dir, 'classes': list(classes.values()),
                   'modules': modules, 'failed_imports': failed + [str(e) for e in loader.errors]}
        Path(out).write_text(json.dumps(payload), encoding='utf-8')
        return 0

    class ProfilingRunner(unittest.TextTestRunner):
        resultclass = _make_result_class(unittest.TextTestResult)

        def run(self, test):
            state['run_start'] = time.perf_counter()
            state['classes'], state['modules'], state['failed_imports'] = _class_rows(test)
            result = super().run(test)
            state['run_end'] = time.perf_counter()
            state['result'] = result
            return result

    sys.argv = ['python -m unittest', 'discover', '-s', start_dir, '-v']
    unittest.main(module=None, argv=list(sys.argv), testRunner=ProfilingRunner, exit=False)
    result = state['result']
    recorder, RECORDER = RECORDER, None

    def plain(record):
        clean = {k: v for k, v in record.items() if not k.startswith('_')}
        clean['programs'] = dict(clean['programs'])
        return clean

    payload = {
        'schema': CHILD_SCHEMA,
        'start_dir': start_dir,
        'discovery_wall': state['run_start'] - t0,
        'run_wall': state['run_end'] - state['run_start'],
        'tests_run': result.testsRun,
        'successful': result.wasSuccessful(),
        'classes': list(state['classes'].values()),
        'modules': state['modules'],
        'failed_imports': state['failed_imports'],
        'tests': [plain(r) for r in recorder.tests],
        'fixtures': [plain(r) for r in recorder.fixtures.values()],
        'imports': [plain(r) for r in recorder.imports.values()],
        'other': plain(recorder.other),
    }
    Path(out).write_text(json.dumps(payload), encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


# --------------------------------------------------------------------------- the parent

def taskfile_suites(text):
    """The suites `task test` runs, in its order, read from Taskfile.yml: each command of
    the `test` target that is a unittest discovery, directly or through one `task:` call.
    A suite is named after its directory: `tools/tests` is `tools`, `integrations/X/tests`
    is `X`."""
    blocks, name = {}, None
    for line in text.splitlines():
        header = re.match(r'^  ([\w:-]+):\s*$', line)
        if header:
            name = header.group(1)
            blocks[name] = []
        elif name is not None and (line.startswith('    ') or not line.strip()):
            blocks[name].append(line)
        else:
            name = None
    if 'test' not in blocks:
        raise ProfileError('Taskfile.yml has no test target')

    def discovers(lines):
        return [m.group(1) for m in map(_DISCOVER.match, lines) if m]

    suites = []
    for line in blocks['test']:
        direct = _DISCOVER.match(line)
        ref = _TASK_REF.match(line)
        if direct:
            dirs = [direct.group(1)]
        elif ref:
            dirs = discovers(blocks.get(ref.group(1), []))
            if len(dirs) != 1:
                raise ProfileError(f'Taskfile.yml target {ref.group(1)} is not one unittest discovery')
        else:
            continue
        for start_dir in dirs:
            parts = start_dir.split('/')
            suite = parts[-2] if len(parts) >= 2 and parts[-1] == 'tests' else start_dir
            if parts[0] == 'tools':
                suite = 'tools'
            suites.append((suite, start_dir))
    if not suites:
        raise ProfileError('the Taskfile.yml test target runs no unittest discovery')
    return suites


def select_suites(names, repo=None):
    all_suites = taskfile_suites((Path(repo or REPO) / 'Taskfile.yml').read_text(encoding='utf-8'))
    if not names:
        return all_suites
    known = dict(all_suites)
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ProfileError(f'unknown suite(s): {", ".join(unknown)}; known: {", ".join(known)}')
    return [(n, known[n]) for n in names]


def run_child(name, start_dir, workdir, tag, discover_only=False):
    out = Path(workdir) / f'{tag}-{name}.json'
    log = Path(workdir) / f'{tag}-{name}.log'
    argv = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '_suite',
            '--start-dir', start_dir, '--out', str(out)]
    if discover_only:
        argv.append('--discover-only')
    t0 = time.perf_counter()
    with open(log, 'wb') as stream:
        proc = subprocess.run(argv, cwd=REPO, stdout=stream, stderr=subprocess.STDOUT)
    wall = time.perf_counter() - t0
    if not out.is_file():
        raise ProfileError(f'suite {name}: the profiling child wrote no result '
                           f'(exit {proc.returncode}); see {log}')
    data = json.loads(out.read_text(encoding='utf-8'))
    data['wall'] = wall
    data['returncode'] = proc.returncode
    return data


def _zero():
    return {counter: 0 for counter in COUNTERS}


def _add(total, record):
    for counter in COUNTERS:
        total[counter] += record.get(counter, 0)


def suite_result(name, data):
    """Aggregate one child's raw data into class rows (tests and class fixtures), module rows
    (module fixtures and import-time events) and what could be attributed to neither."""
    classes = {row['id']: dict(row, discovered=row['tests'], tests=0, wall=0.0,
                               programs=collections.Counter(), **_zero())
               for row in data['classes']}
    for test in data['tests']:
        if test.get('cls') in classes:
            classes[test['cls']]['tests'] += 1
    modules = {}
    for row in classes.values():
        if row['module'] not in modules:
            declared = data.get('modules', {}).get(row['module'])
            modules[row['module']] = dict(
                _zero(), id=row['module'], module=row['module'],
                category=declared if declared is not None else row['category'],
                source='module' if declared is not None else 'first class',
                tests=0, wall=0.0, programs=collections.Counter())

    unattributed = dict(_zero(), programs=collections.Counter())

    def take(row, record, timed=True):
        target = row if row is not None else unattributed
        _add(target, record)
        target['programs'].update(record['programs'])
        if row is not None and timed:
            row['wall'] += record.get('wall', 0.0)

    for test in data['tests']:
        take(classes.get(test.get('cls')), test)
    for fixture in data['fixtures']:
        take(classes.get(fixture['owner']) if fixture['kind'] == 'class'
             else modules.get(fixture['owner']), fixture)
    for imported in data['imports']:
        take(modules.get(imported['module']), imported, timed=False)
    take(None, data['other'])
    return classes, modules, unattributed


def _median(values):
    return round(statistics.median(values), 3) if values else 0.0


def outcomes_digest(pairs):
    text = ''.join(f'{test_id}\t{outcome}\n' for test_id, outcome in sorted(pairs))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _repository_access():
    """The shared repository-access module (integrations/repository, decision 0014), loaded by
    path once per process (the standard library at import, Dulwich when a repository opens)."""
    module = sys.modules.get('repository_access')
    if module is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'repository_access', REPO / 'integrations' / 'repository' / 'repository_access.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules['repository_access'] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules['repository_access']
            raise
    return module


def git_revision(repo=REPO):
    """(revision, dirty, reason) of the checkout: HEAD and whether a tracked file differs, as
    ``git rev-parse HEAD`` and ``git status --porcelain --untracked-files=no`` answer, read in
    process by the shared repository-access module under the ``host`` configuration policy
    (decision 0014 row R10). When the module cannot answer (no Dulwich in this interpreter, not a
    work tree, a status it cannot give as git does) revision and dirty are None and reason says
    why; otherwise reason is None."""
    try:
        ra = _repository_access()
    except (OSError, ImportError) as exc:
        return None, None, f'the repository-access module cannot be loaded: {exc}'
    try:
        with ra.open_repository(repo, config='host') as opened:
            head = opened.head().commit
            if head is None:
                return None, None, 'HEAD names no commit'
            return head, bool(opened.status(None, 'no')), None
    except (ra.RepositoryError, ra.CannotRun) as exc:
        return None, None, f'{exc.code}: {exc.message}'


def build_profile(runs_data, suites, revision=None, dirty=None, revision_reason=None):
    """Combine the children's data from every run into one profile (pure: launches nothing)."""
    nruns = len(runs_data)
    problems = []
    suite_rows = []
    class_rows = {}
    module_rows = {}
    tests = {}
    determinism = []
    category_wall_runs = collections.defaultdict(lambda: [0.0] * nruns)
    total_wall_runs = [0.0] * nruns
    for name, start_dir in suites:
        per_run = []
        for r, run in enumerate(runs_data):
            data = run[name]
            classes, modules, unattributed = suite_result(name, data)
            classes.update({f'module {k}': v for k, v in modules.items()})
            per_run.append((data, classes, unattributed))
            total_wall_runs[r] += data['wall']
            for row in classes.values():
                category_wall_runs[row['category'] or 'uncategorized'][r] += row['wall']
        data0, classes0, unattributed0 = per_run[0]
        # Determinism: counters and outcomes must be equal in every run.
        for r, (data, classes, unattributed) in enumerate(per_run[1:], start=2):
            for key, row in classes0.items():
                other = classes.get(key)
                for counter in COUNTERS + ('tests',):
                    if other is None or other[counter] != row[counter]:
                        determinism.append({'suite': name, 'class': key, 'counter': counter,
                                            'run1': row[counter],
                                            f'run{r}': None if other is None else other[counter]})
            for counter in COUNTERS:
                if unattributed[counter] != unattributed0[counter]:
                    determinism.append({'suite': name, 'class': None, 'counter': counter,
                                        'run1': unattributed0[counter],
                                        f'run{r}': unattributed[counter]})
            first = {t['id']: t['outcome'] for t in data0['tests']}
            again = {t['id']: t['outcome'] for t in data['tests']}
            if first != again:
                determinism.append({'suite': name, 'outcomes_differ_in_run': r})
        for data, _, _ in per_run:
            if data['returncode'] not in (0, 1):
                problems.append(f'suite {name}: the child exited {data["returncode"]}')
        if data0['failed_imports']:
            problems.append(f'suite {name}: modules failed to import: {data0["failed_imports"]}')
        outcome_counts = collections.Counter(t['outcome'] for t in data0['tests'])
        walls = collections.defaultdict(list)
        for data, _, _ in per_run:
            for t in data['tests']:
                walls[t['id']].append(t.get('wall', 0.0))
        for t in data0['tests']:
            tests[t['id']] = {'id': t['id'], 'suite': name, 'outcome': t['outcome'],
                              'wall': _median(walls[t['id']]), **{c: t[c] for c in COUNTERS}}
        totals = _zero()
        for row in classes0.values():
            _add(totals, row)
        _add(totals, unattributed0)
        for key, row in classes0.items():
            walls = [classes[key]['wall'] for _, classes, _ in per_run if key in classes]
            item = {
                'id': row['id'], 'suite': name, 'category': row['category'],
                'source': row['source'], 'tests': row['tests'],
                'discovered': row.get('discovered', 0), **{c: row[c] for c in COUNTERS},
                'wall': _median(walls),
                'programs': dict(sorted(row['programs'].items(), key=lambda kv: (-kv[1], kv[0]))),
            }
            if key.startswith('module '):
                if any(item[c] for c in COUNTERS) or item['wall'] >= 0.001:
                    module_rows[(name, row['id'])] = item
            else:
                class_rows[key] = item
        suite_rows.append({
            'name': name, 'start_dir': start_dir, 'tests': data0['tests_run'],
            'outcomes': dict(sorted(outcome_counts.items())),
            'successful': all(d['successful'] for d, _, _ in per_run),
            **totals,
            'unattributed': {c: unattributed0[c] for c in COUNTERS},
            'wall': {'runs': [round(d['wall'], 3) for d, _, _ in per_run],
                     'median': _median([d['wall'] for d, _, _ in per_run]),
                     'discovery_median': _median([d['discovery_wall'] for d, _, _ in per_run])},
        })
    categories = {}
    for row in class_rows.values():
        cat = row['category'] or 'uncategorized'
        entry = categories.setdefault(cat, {'classes': 0, 'tests': 0, **_zero()})
        entry['classes'] += 1
        entry['tests'] += row['tests']
        _add(entry, row)
    for row in module_rows.values():
        cat = row['category'] or 'uncategorized'
        entry = categories.setdefault(cat, {'classes': 0, 'tests': 0, **_zero()})
        _add(entry, row)
    for cat, entry in categories.items():
        entry['wall'] = {'runs': [round(w, 3) for w in category_wall_runs[cat]],
                         'median': _median(category_wall_runs[cat])}
    totals = {'tests': sum(s['tests'] for s in suite_rows), **_zero()}
    for s in suite_rows:
        _add(totals, s)
    totals['wall'] = {'runs': [round(w, 3) for w in total_wall_runs],
                      'median': _median(total_wall_runs)}
    uncategorized = sorted(k for k, row in class_rows.items() if row['category'] is None)
    invalid = sorted(k for k, row in class_rows.items()
                     if row['category'] is not None and row['category'] not in CATEGORIES)
    profile = {
        'schema': PROFILE_SCHEMA,
        'revision': revision,
        'dirty': dirty,
        'revision_reason': revision_reason,
        'measured': time.strftime('%Y-%m-%d', time.gmtime()),
        'host': {'system': platform.system(), 'release': platform.release(),
                 'machine': platform.machine(), 'cpus': os.cpu_count(),
                 'python': platform.python_version()},
        'runs': nruns,
        'totals': totals,
        'suites': suite_rows,
        'categories': dict(sorted(categories.items())),
        'uncategorized': uncategorized,
        'invalid_categories': invalid,
        'determinism': determinism,
        'problems': problems,
        'outcomes_digest': outcomes_digest((t['id'], t['outcome']) for t in tests.values()),
        'classes': sorted(class_rows.values(), key=lambda r: (r['suite'], r['id'])),
        'modules': sorted(module_rows.values(), key=lambda r: (r['suite'], r['id'])),
        'tests': sorted(tests.values(), key=lambda r: (r['suite'], r['id'])),
    }
    return profile


def top_programs(profile, limit=25):
    counts = collections.Counter()
    for row in profile['classes'] + profile['modules']:
        counts.update(row['programs'])
    return [{'program': key, 'launches': n}
            for key, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def top_classes(profile, counter, limit=15):
    rows = sorted(profile['classes'], key=lambda r: (-r[counter], r['id']))
    return [{'class': r['id'], 'category': r['category'], counter: r[counter], 'tests': r['tests']}
            for r in rows[:limit] if r[counter]]


def compact(profile):
    """The evidence form: no per-test rows and no per-class programs."""
    keep = {k: v for k, v in profile.items()
            if k not in ('tests', 'classes', 'modules', 'schema')}
    return {
        'schema': COMPACT_SCHEMA,
        **keep,
        'top_launch_programs': top_programs(profile),
        'top_launch_classes': top_classes(profile, 'launches'),
        'top_mkdtemp_classes': top_classes(profile, 'mkdtemp'),
        'classes': [{k: v for k, v in row.items() if k != 'programs'}
                    for row in profile['classes']],
        'modules': [{k: v for k, v in row.items() if k != 'programs'}
                    for row in profile['modules']],
    }


def profile_ok(profile):
    reasons = list(profile['problems'])
    if profile['uncategorized']:
        reasons.append(f'{len(profile["uncategorized"])} classes have no category')
    if profile['invalid_categories']:
        reasons.append(f'{len(profile["invalid_categories"])} classes have an unknown category')
    if profile['determinism']:
        reasons.append(f'{len(profile["determinism"])} counters or outcomes differ between runs')
    if not all(s['successful'] for s in profile['suites']):
        reasons.append('a suite has failing tests')
    return reasons


def print_summary(profile, stream=sys.stdout):
    w = stream.write
    w(f'profile of {profile["revision"] or "?"}{" (dirty)" if profile["dirty"] else ""}, '
      f'{profile["runs"]} run(s)\n')
    w(f'{"suite":<12}{"tests":>7}{"launches":>10}{"mkdtemp":>9}{"sockets":>9}{"chdir":>7}'
      f'{"wall s":>9}\n')
    for s in profile['suites']:
        w(f'{s["name"]:<12}{s["tests"]:>7}{s["launches"]:>10}{s["mkdtemp"]:>9}{s["sockets"]:>9}'
          f'{s["chdir"]:>7}{s["wall"]["median"]:>9.1f}\n')
    t = profile['totals']
    w(f'{"total":<12}{t["tests"]:>7}{t["launches"]:>10}{t["mkdtemp"]:>9}{t["sockets"]:>9}'
      f'{t["chdir"]:>7}{t["wall"]["median"]:>9.1f}\n')
    w(f'{"category":<14}{"classes":>8}{"tests":>7}{"launches":>10}{"mkdtemp":>9}{"wall s":>9}\n')
    for name, c in profile['categories'].items():
        w(f'{name:<14}{c["classes"]:>8}{c["tests"]:>7}{c["launches"]:>10}{c["mkdtemp"]:>9}'
          f'{c["wall"]["median"]:>9.1f}\n')


def run_profile(runs, suites, workdir):
    runs_data = []
    for r in range(1, runs + 1):
        run = {}
        for name, start_dir in suites:
            run[name] = run_child(name, start_dir, workdir, f'run{r}')
            print(f'run {r}/{runs} {name}: {run[name]["tests_run"]} tests, '
                  f'{run[name]["wall"]:.1f} s', file=sys.stderr, flush=True)
        runs_data.append(run)
    revision, dirty, reason = git_revision()
    return build_profile(runs_data, suites, revision, dirty, reason)


def check_categories(suites, workdir):
    rows, failed = [], []
    for name, start_dir in suites:
        data = run_child(name, start_dir, workdir, 'discover', discover_only=True)
        if data['returncode'] != 0:
            raise ProfileError(f'suite {name}: discovery exited {data["returncode"]}')
        for row in data['classes']:
            rows.append(dict(row, suite=name))
        failed.extend(data['failed_imports'])
    return rows, failed


# --------------------------------------------------------------------------- plain runs

_DESCRIPTION = re.compile(r'^ {0,2}(\w+) \(([\w.]+)\)(.*)$')


def _status(text):
    text = text.strip()
    if text == 'ok':
        return 'ok'
    for prefix, outcome in (('FAIL', 'fail'), ('ERROR', 'error'), ('skipped', 'skip'),
                            ('expected failure', 'xfail'), ('unexpected success', 'xpass')):
        if text.startswith(prefix):
            return outcome
    return None


def parse_verbose(text):
    """Test ids and outcomes from the stderr of `python -m unittest ... -v` (verbosity 2).

    Returns ({id: outcome}, ran) where ran is the 'Ran N tests' count or None."""
    results = {}
    pending = None
    for line in text.splitlines():
        if line.startswith(('=' * 20, '-' * 20)):
            pending = None
            if line.startswith('=' * 20):
                break  # the failure details follow; every outcome is already listed
            continue
        match = _DESCRIPTION.match(line)
        if match:
            name, ident, rest = match.groups()
            key = ident if ident.endswith('.' + name) else f'{name} ({ident})'
            if ' ... ' in rest:
                status = _status(rest.rsplit(' ... ', 1)[1])
                if status is not None:
                    _merge(results, key, status)
                    pending = None
                    continue
            pending = key
            continue
        if pending is not None:
            status = _status(line.rsplit(' ... ', 1)[1]) if ' ... ' in line else _status(line)
            if status is not None:
                _merge(results, pending, status)
                pending = None
    ran = re.search(r'^Ran (\d+) tests? in ', text, re.M)
    return results, int(ran.group(1)) if ran else None


def _merge(results, key, status):
    old = results.get(key)
    if old is None or _SEVERITY[status] > _SEVERITY[old]:
        results[key] = status


def run_plain(name, start_dir, workdir):
    log = Path(workdir) / f'plain-{name}.log'
    proc = subprocess.run([sys.executable, '-I', '-B', '-m', 'unittest', 'discover', '-s',
                           start_dir, '-v'], cwd=REPO, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE)
    log.write_bytes(proc.stderr)
    return parse_verbose(proc.stderr.decode('utf-8', 'replace')), proc.returncode


def compare(profile, suites, workdir):
    """Differences between a plain run's ids and outcomes and the profile's."""
    differences = []
    expected = collections.defaultdict(dict)
    for test in profile['tests']:
        expected[test['suite']][test['id']] = test['outcome']
    for name, start_dir in suites:
        (got, ran), _ = run_plain(name, start_dir, workdir)
        want = expected.get(name, {})
        suite_row = next((s for s in profile['suites'] if s['name'] == name), None)
        if suite_row is None:
            differences.append(f'{name}: not in the profile')
            continue
        if ran != suite_row['tests']:
            differences.append(f'{name}: plain run ran {ran} tests, the profile {suite_row["tests"]}')
        for key in sorted(set(want) | set(got)):
            if want.get(key) != got.get(key):
                differences.append(f'{name}: {key}: profile {want.get(key)}, plain {got.get(key)}')
        print(f'{name}: plain {len(got)} ids (ran {ran}), profile {len(want)}',
              file=sys.stderr, flush=True)
    return differences


# --------------------------------------------------------------------------- CLI

def _workdir(path=None):
    if path:
        Path(path).mkdir(parents=True, exist_ok=True)
        return Path(path)
    return Path(tempfile.mkdtemp(prefix='aieh-test-profile-'))


@contextlib.contextmanager
def scratch(path=None):
    """A working directory for children's files: `path` (kept), or a new temporary directory
    removed on exit, so that `categories` and `compare` leave nothing behind."""
    if path:
        yield _workdir(path)
        return
    with tempfile.TemporaryDirectory(prefix='aieh-test-profile-', ignore_cleanup_errors=True) as tmp:
        yield Path(tmp)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    p_run = sub.add_parser('run', help='profile the suites')
    p_run.add_argument('--runs', type=int, default=1)
    p_run.add_argument('--suite', action='append', default=[])
    p_run.add_argument('--out', help='the full profile (default: a new temporary directory)')
    p_run.add_argument('--compact-out', help='also write the compact evidence form here')
    p_run.add_argument('--workdir', help='where the children write (default: temporary)')
    p_cat = sub.add_parser('categories', help='check that every test class has a category')
    p_cat.add_argument('--suite', action='append', default=[])
    p_cat.add_argument('--list', action='store_true', help='print every class and its category')
    p_cat.add_argument('--workdir')
    p_cmp = sub.add_parser('compare', help='compare a plain run with a profile')
    p_cmp.add_argument('--profile', required=True)
    p_cmp.add_argument('--suite', action='append', default=[])
    p_cmp.add_argument('--workdir')
    p_child = sub.add_parser('_suite', help=argparse.SUPPRESS)
    p_child.add_argument('--start-dir', required=True)
    p_child.add_argument('--out', required=True)
    p_child.add_argument('--discover-only', action='store_true')
    args = parser.parse_args(argv)

    if args.command == '_suite':
        return child_main(args.start_dir, args.out, args.discover_only)
    try:
        suites = select_suites(args.suite)
        if args.command == 'run':
            if args.runs < 1:
                raise ProfileError('--runs must be at least 1')
            workdir = _workdir(args.workdir)
            profile = run_profile(args.runs, suites, workdir)
            out = Path(args.out) if args.out else workdir / 'profile.json'
            out.write_text(json.dumps(profile, indent=1) + '\n', encoding='utf-8')
            if args.compact_out:
                Path(args.compact_out).write_text(json.dumps(compact(profile), indent=1) + '\n',
                                                  encoding='utf-8')
            print_summary(profile)
            print(f'profile: {out}')
            reasons = profile_ok(profile)
            for reason in reasons:
                print(f'FAIL: {reason}')
            print('PASS' if not reasons else 'FAIL')
            return 0 if not reasons else 1
        if args.command == 'categories':
            with scratch(args.workdir) as workdir:
                rows, failed = check_categories(suites, workdir)
            bad = [r for r in rows if r['category'] not in CATEGORIES]
            counts = collections.Counter(r['category'] for r in rows if r['category'] in CATEGORIES)
            if args.list:
                for r in sorted(rows, key=lambda r: (r['suite'], r['id'])):
                    print(f'{r["suite"]}\t{r["id"]}\t{r["category"]}\t{r["source"]}\t{r["tests"]}')
            modules = {r['module'] for r in rows}
            print(f'{len(rows)} classes in {len(modules)} modules: '
                  + ', '.join(f'{c} {counts[c]}' for c in CATEGORIES))
            for r in bad:
                print(f'FAIL: {r["suite"]} {r["id"]}: category {r["category"]!r}')
            for f in failed:
                print(f'FAIL: failed to import: {f}')
            print('PASS' if not bad and not failed else 'FAIL')
            return 0 if not bad and not failed else 1
        if args.command == 'compare':
            profile = json.loads(Path(args.profile).read_text(encoding='utf-8'))
            if profile.get('schema') != PROFILE_SCHEMA:
                raise ProfileError('compare needs a full profile (run --out), not a compact one')
            with scratch(args.workdir) as workdir:
                differences = compare(profile, suites, workdir)
            for d in differences:
                print(f'DIFF: {d}')
            print('PASS: identical ids and outcomes' if not differences else 'FAIL')
            return 0 if not differences else 1
    except (ProfileError, OSError, ValueError, KeyError) as exc:
        print(f'could not run: {exc}', file=sys.stderr)
        return 2
    return 2


if __name__ == '__main__':
    sys.exit(main())
