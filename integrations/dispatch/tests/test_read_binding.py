"""The read-binding test (plan leaf E-01.4.2, slice 5c; E-01.7's proof carries the same rule): the fields the dispatch
path reads of the fixture core's answers are exactly the provenance table's rows marked read, and none of them is
clock-valued or not served.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_read_binding.py -v

**How it records.** At the answer boundary: every answer the core makes is returned as mappings that note each key
read of them, by catalog answer and field path, present or not, with its reader (the innermost dispatch function
under the read), through exactly the operations ``agentfixture/core.py``'s docstring names (``m[k]``, ``get``, ``in``
and the whole-key reads). Every other read of a whole answer, or change of it, is noted as an **opaque read** and
raises; the judgement rejects each one by name (``OPAQUE_READ``), whatever the answer. ``read_binding_runner.py``
installs the recorder before any test module is loaded and runs dispatch test modules under it, in processes of their
own (no visible window), four at a time.

**What it covers: the dispatch suite, whole.** Every ``test_*.py`` module of ``integrations/dispatch/tests`` but two:
this module, and ``test_agentfixture_core.py``, whose tests read the core's answers themselves to test the core (their
reads are the test's, not the dispatch path's). The restart matrix (``test_restart_matrix.py``) is one of the modules.
Each module's own tests must all pass under the recorder, or the binding is refused. The report names the modules in
which the core answered at all; a module whose tests never reach the core contributes nothing and costs only its run.

**Enough, and not.** The binding is a recorded fact over the suites it runs: it sees every read those tests make of a
core answer, by any code, the test knobs' own reads of a core answer included (a knob that reads a field the dispatch
path does not read would show here as a read; none does). It does not see a dispatch path no test runs, nor a read of
an answer a test knob made instead of the core (those answers are not catalog answers), nor an unbound ``dict``
method on a key an answer does not hold (the recorder's one documented blind spot). Reads of the core's refusals
(answers that are only its label) are allowed and listed: that is how the dispatch path finds it has no answer.

**Where.** Each row marked read names the functions of ``integrations/dispatch/`` that read it (``readBy``); they are
exactly the recorded readers of its paths that are dispatch functions (a test knob's own read is ``outside:`` and
does not count).
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RUNNER = HERE / 'read_binding_runner.py'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
EXCLUDED = ('test_read_binding.py', 'test_agentfixture_core.py')
WORKERS = 4
CEILING_S = 1800        # a ceiling on one module's run, not an expected duration


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


AC = _load('agentfixture_core', REPO / 'integrations' / 'agentfixture' / 'core.py')
CATALOG = AC.load_catalog()


def modules():
    return sorted(p.name for p in HERE.glob('test_*.py') if p.name not in EXCLUDED)


def rows_by_path():
    rows = {}
    for row in CATALOG['provenance']:
        for path in AC.field_paths(row['field']):
            rows[(row['answer'], path)] = row
    return rows


def judge(reads, rows):
    """The recorded reads against the table: (violations, the read rows observed, the refusal reads). An opaque read
    (a whole answer read, or changed, outside the recorded reads) is a violation named ``OPAQUE_READ`` on any answer,
    a refusal included."""
    marked = {key for key, row in rows.items() if row['read']}
    violations, observed, refusals = [], set(), []
    for read in reads:
        key = (read['answer'], read['path'])
        if any(how.startswith(AC.OPAQUE) for how in read['how']):
            violations.append({**read, 'violation': 'OPAQUE_READ', 'row': None})
            continue
        if read['answer'] == 'refusal':
            refusals.append(key)
            continue
        row = rows.get(key)
        if row is not None:
            if not (row['read'] and row['served'] and read['present']) or 'clock-valued' in row['marks']:
                violations.append({**read, 'row': {k: row[k] for k in ('class', 'read', 'served', 'marks')}})
            else:
                observed.add(key)
            continue
        container = any(a == read['answer'] and (p.startswith(read['path'] + '.') or p.startswith(read['path'] + '[]'))
                        for a, p in marked)
        if not (container and read['present']):
            violations.append({**read, 'row': None})
    return violations, observed, refusals


class ReadBinding(unittest.TestCase):
    category = 'integration'

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix='aieh-read-binding-'))
        names = modules()

        def run(name):
            done = subprocess.run([sys.executable, '-I', '-B', str(RUNNER), str(cls.out / f'{name}.json'), name],
                                  cwd=REPO, capture_output=True, timeout=CEILING_S, creationflags=NO_WINDOW,
                                  env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
            return name, done.returncode, done.stderr.decode('utf-8', 'replace')[-2000:]
        with ThreadPoolExecutor(WORKERS) as pool:
            cls.runs = list(pool.map(run, names))
        cls.results = {name: json.loads((cls.out / f'{name}.json').read_text(encoding='utf-8'))
                       for name, _, _ in cls.runs if (cls.out / f'{name}.json').is_file()}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def reads(self):
        merged = {}
        for result in self.results.values():
            for read in result['reads']:
                held = merged.setdefault((read['answer'], read['path']), dict(read, how=[]))
                held['present'] = held['present'] or read['present']
                held['how'] += [how for how in read['how'] if how not in held['how']]
        return list(merged.values())

    def readers(self):
        merged = {}
        for result in self.results.values():
            for read in result['readers']:
                merged.setdefault((read['answer'], read['path']), set()).update(read['by'])
        return merged

    def test_every_module_ran_and_passed_under_the_recorder(self):
        for name, code, err in self.runs:
            with self.subTest(module=name):
                self.assertIn(name, self.results, err)
                self.assertEqual((code, self.results[name]['failures']), (0, []), err)
                self.assertGreater(self.results[name]['tests'], 0)
        self.assertEqual(sorted(self.results), modules())

    def test_the_reads_are_exactly_the_rows_marked_read(self):
        rows = rows_by_path()
        violations, observed, _ = judge(self.reads(), rows)
        self.assertEqual(violations, [], 'a read of a field not marked read, clock-valued, not served or not listed')
        self.assertEqual(observed, {key for key, row in rows.items() if row['read']},
                         'a row marked read that no suite reads')

    def test_each_row_read_names_exactly_the_dispatch_functions_that_read_it(self):
        """Dispatch 14, N4: the Read column's "where" is the recorded readers that are dispatch functions."""
        readers = self.readers()
        for row in CATALOG['provenance']:
            if row['read']:
                with self.subTest(answer=row['answer'], field=row['field']):
                    found = set().union(*(readers.get((row['answer'], path), set())
                                          for path in AC.field_paths(row['field'])))
                    self.assertEqual(set(row['readBy']), {by for by in found if not by.startswith('outside:')})

    def test_no_row_marked_read_is_clock_valued_or_not_served(self):
        for row in CATALOG['provenance']:
            if row['read']:
                with self.subTest(answer=row['answer'], field=row['field']):
                    self.assertTrue(row['served'])
                    self.assertNotIn('clock-valued', row['marks'])

    def test_the_core_answered_in_the_matrix_and_the_three_fakes_modules(self):
        answering = {name for name, result in self.results.items() if result['answers']}
        self.assertLessEqual({'test_restart_matrix.py', 'test_conversation_create.py', 'test_attempt_end.py',
                              'test_attempt_run.py'}, answering)
        made = {}
        for result in self.results.values():
            for answer, count in result['answers'].items():
                made[answer] = made.get(answer, 0) + count
        self.assertEqual(set(made), set(CATALOG['answers']) - {'message-event'}, made)


class Judge(unittest.TestCase):
    """The judgement itself, on recorded reads made up for it (the falsifiers)."""
    category = 'unit'

    def judged(self, *reads):
        return judge([{'answer': a, 'path': p, 'present': present, 'how': ['get']} for a, p, present in reads],
                     rows_by_path())

    def test_a_read_of_a_field_not_marked_read_is_a_violation(self):
        self.assertEqual(len(self.judged(('server-info', 'body.python_version', True))[0]), 1)

    def test_a_read_of_a_clock_valued_or_not_served_field_is_a_violation(self):
        for read in (('server-info', 'body.uptime', True), ('create-new', 'body.created_at', True),
                     ('conversation', 'body.title', False), ('message', 'body', False),
                     ('conversation-absent', 'body.detail', False), ('message-event', 'id', False)):
            with self.subTest(read=read):
                self.assertEqual(len(self.judged(read)[0]), 1)

    def test_an_unlisted_or_absent_read_is_a_violation_and_a_container_is_not(self):
        self.assertEqual(len(self.judged(('runtime', 'body.nothing', False))[0]), 1)
        self.assertEqual(len(self.judged(('conversation-absent', 'body', False))[0]), 1)
        self.assertEqual(len(self.judged(('conversation', 'body.id', False))[0]), 1, 'a read row the core did not serve')
        self.assertEqual(self.judged(('server-info', 'body', True), ('message-event', 'llm_message.content', True))[0],
                         [])

    def test_refusal_reads_are_listed_not_judged(self):
        violations, observed, refusals = self.judged(('refusal', 'body', False))
        self.assertEqual((violations, observed, refusals), ([], set(), [('refusal', 'body')]))

    def test_an_opaque_read_is_a_named_violation_for_each_operation_class(self):
        """Dispatch 14, S2: each operation class's opaque read, as the recorder records it, is rejected by name, on
        a read row's answer and on a refusal alike."""
        operations = {'equality': lambda b: b == {}, 'text': repr, 'union': lambda b: b | {},
                      'change': lambda b: b.pop('status'), 'copy': lambda b: b.copy(),
                      'unbound': lambda b: dict.get(b, 'status')}
        for kind, act in operations.items():
            for request in (('GET', '/server_info'), ('GET', '/alive')):
                with self.subTest(kind=kind, request=request):
                    core, reads = AC.AgentServerCore(), AC.Reads()
                    with AC.recording(reads):
                        answer = core(*request)
                    with self.assertRaises(AC.OpaqueRead):
                        act(answer)
                    violations, _, _ = judge(reads.to_json(), rows_by_path())
                    self.assertEqual([v.get('violation') for v in violations], ['OPAQUE_READ'])


# ---------------------------------------------------------------------------
# E-01.7's extension: the same binding over the served fixture's listener

SERVED_EXPECTED_FAILURES = {
    # each needs the dispatcher face's source-derived entry (message-event), which the listener refuses to serve:
    # answered in process only, for E-01.4.2's restart matrix (E-01.7's proof)
    'test_restart_matrix.Rows.test_j_dies_with_the_turn_dispatched_its_message_received',
    'test_restart_matrix.Rows.test_j_prime_as_j_then_a_restore',
    'test_restart_matrix.Rows.test_k_the_messages_answer_is_lost_then_a_death',
}
TRANSPORT_KEY = 'transport key'                # a row's mark: a key the transport adds (E-01.8's seam), not served


def transport_keys():
    """The (answer, path) of every served row marked a transport key (review ruling 7: read from the rows)."""
    return {(row['answer'], path) for row in CATALOG['served']['provenance'] if TRANSPORT_KEY in row['marks']
            for path in AC.field_paths(row['field'])}


def locked_openapi():
    """The locked release openapi.json AIEH_LOCKED_OPENAPI names (never committed: decision 0005), or None."""
    named = os.environ.get('AIEH_LOCKED_OPENAPI')
    if not named:
        return None
    import hashlib
    if hashlib.sha256(Path(named).read_bytes()).hexdigest() != CATALOG['served']['lockedOpenapi']['sha256']:
        raise ValueError(f'{named} is not the locked openapi.json')
    return named


def served_rows_by_path():
    """The core's rows and the served fixture's (``served.provenance``), by (answer, field path)."""
    rows = rows_by_path()
    for row in CATALOG['served']['provenance']:
        for path in AC.field_paths(row['field']):
            rows[(row['answer'], path)] = row
    return rows


def without_line(stdout: str, line: str) -> str:
    """STDOUT with the marker line LINE removed (``frame``: the exchange frame's lines, from its first to its end)."""
    lines, kept, framing = stdout.split('\n'), [], False
    for text in lines:
        if line == 'frame':
            framing = framing or text.startswith('AIEH-EXCHANGE-PART ')
            if framing:
                framing = not text.startswith('AIEH-EXCHANGE-END ')
                continue
        elif text.startswith(f'AIEH-RESULT {line} ') or text == f'AIEH-RESULT {line}':
            continue
        kept.append(text)
    return '\n'.join(kept)


@unittest.skipIf(locked_openapi() is None, 'AIEH_LOCKED_OPENAPI is not given: the listener validates every create '
                                           'against the locked openapi.json, never committed (decision 0005)')
class ServedReadBinding(unittest.TestCase):
    """The dispatch suite, unmodified, against the served core (``read_binding_runner.py --served``: every request a
    test sends to a core goes over HTTP to the listener serving that core), with the read record at the fixture
    transport's answer boundary; the failed scenario's refused create over the listener (the restart matrix, its
    rows failing by design); and RESULT's answer read by the production parser (the resumed result step's own call,
    ``parse_result(answer, delivered_expected=False)``) in process. The served table's rows marked read are exactly
    what these read, with their readers."""
    category = 'integration'

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix='aieh-served-binding-'))
        names = modules()

        def run(args):
            name, extra = args
            target = cls.out / f'{"-".join(extra) or "finished"}-{name}.json'
            done = subprocess.run([sys.executable, '-I', '-B', str(RUNNER), '--served', *extra, str(target), name],
                                  cwd=REPO, capture_output=True, timeout=CEILING_S, creationflags=NO_WINDOW,
                                  env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
            result = json.loads(target.read_text(encoding='utf-8')) if target.is_file() else None
            return name, extra, done.returncode, result
        jobs = [(name, []) for name in names] + [('test_restart_matrix.py', ['--scenario', 'failed'])]
        with ThreadPoolExecutor(WORKERS) as pool:
            cls.runs = list(pool.map(run, jobs))
        cls.result_reads = cls.read_a_result()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    @staticmethod
    def read_a_result():
        """RESULT answered by the core over a D1-shaped base (agentfixture's G7 fixture), read by the production
        parser under a read record."""
        tests = REPO / 'integrations' / 'agentfixture' / 'tests'
        sys.path.insert(0, str(tests))
        try:
            fixture = _load('agentfixture_test_result', tests / 'test_result.py')
        finally:
            sys.path.remove(str(tests))
        case = fixture.D1Shaped('setUp')
        case.setUp()
        try:
            case.seeded()
            reads = AC.Reads()
            with AC.recording(reads):
                answer = case.core('POST', case.path, fixture.result_command(case.base))
                fixture.AR.parse_result(answer, delivered_expected=False)
            stdout = answer['body']['stdout']
            # review N-b: which marker lines the parser reads, shown by taking each away (never by the table)
            needed = {}
            for line in ('base', 'tree', 'commit', 'excluded', 'bundle', 'tests', 'test-output', 'done', 'frame'):
                try:
                    fixture.AR.parse_result({'status': 200, 'body': {'stdout': without_line(stdout, line),
                                                                     'exit_code': 0}}, delivered_expected=False)
                    needed[line] = False
                except fixture.AR.DispatchRefused:
                    needed[line] = True             # any refusal: the parser needs the line (review round 2)
            return {'reads': reads.to_json(), 'readers': reads.readers_json(), 'needed': needed}
        finally:
            case.doCleanups()

    def finished(self):
        return [result for name, extra, _, result in self.runs if not extra]

    def all_reads(self):
        results = [result for _, _, _, result in self.runs if result] + [self.result_reads]
        merged, readers = {}, {}
        for result in results:
            for read in result['reads']:
                held = merged.setdefault((read['answer'], read['path']), dict(read, how=[]))
                held['present'] = held['present'] or read['present']
                held['how'] += [how for how in read['how'] if how not in held['how']]
            for read in result['readers']:
                readers.setdefault((read['answer'], read['path']), set()).update(read['by'])
        return list(merged.values()), readers

    def test_the_failed_scenarios_run_fails_on_its_refused_creates(self):
        """Review N-c: the restart matrix in the failed scenario fails by design (every create is answered 401):
        its own return code and failures, and that the dispatch path was given the 401 to read."""
        (run,) = [(code, result) for name, extra, code, result in self.runs if extra]
        code, result = run
        self.assertEqual(code, 1)
        self.assertGreater(len(result['failures']), 0)
        self.assertGreater(result['answers'].get('unauthorized', 0), 0)
        self.assertNotIn('create-new', result['answers'], 'no create was answered 201')
        self.assertTrue(any('CREATE_REFUSED' in text and '401' in text for text in result['failed'].values()))

    def test_the_dispatch_suite_runs_against_the_served_core_failing_only_where_the_listener_refuses(self):
        results = self.finished()
        self.assertEqual(len(results), len(modules()))
        self.assertTrue(all(result is not None and result['tests'] > 0 for result in results))
        failures = {test for result in results for test in result['failures']}
        self.assertEqual(failures, SERVED_EXPECTED_FAILURES)
        refused = [r for result in results for r in result['refused']]
        self.assertTrue(any(r['path'].endswith('/events/search') for r in refused))
        for result in results:
            for name, text in result['failed'].items():
                with self.subTest(test=name):
                    self.assertIn('reconciled-from-events', text, 'a failure only where the event is refused')

    def test_over_the_wire_the_reads_are_rows_marked_read_none_clock_valued_or_not_served(self):
        rows = served_rows_by_path()
        reads, _ = self.all_reads()
        keys = transport_keys()
        self.assertEqual(keys, {('result', 'delivered')})
        transport = [r for r in reads if (r['answer'], r['path']) in keys]
        self.assertEqual([(r['answer'], r['path'], r['present']) for r in transport], [('result', 'delivered', False)])
        text = [r for r in reads if (r['answer'], r['path']) == ('result', 'body.stdout')]
        self.assertEqual([r['present'] for r in text], [True], 'the parser reads RESULT\'s text')
        judged = [r for r in reads if (r['answer'], r['path']) not in keys | {('result', 'body.stdout')}]
        violations, observed, _ = judge(judged, rows)
        self.assertEqual(violations, [], 'a read of a field not marked read, clock-valued, not served or not listed')
        observed_rows = {id(rows[key]) for key in observed}
        needed = self.result_reads['needed']
        for row in CATALOG['served']['provenance']:
            paths = AC.field_paths(row['field'])
            lines = [p[len('body.stdout#'):] for p in paths if p.startswith('body.stdout#')]
            with self.subTest(answer=row['answer'], field=row['field']):
                if lines:                 # a line is read when the parser refuses the text without it
                    self.assertEqual({needed[line] for line in lines}, {row['read']})
                elif row['read'] and TRANSPORT_KEY not in row['marks']:
                    self.assertIn(id(row), observed_rows, 'a served row marked read that nothing reads')

    def test_each_served_row_read_names_exactly_the_dispatch_functions_that_read_it(self):
        _, readers = self.all_reads()
        for row in CATALOG['served']['provenance']:
            if row['read']:
                with self.subTest(answer=row['answer'], field=row['field']):
                    found = set()
                    for path in AC.field_paths(row['field']):
                        key = (row['answer'], 'body.stdout' if path.startswith('body.stdout#') else path)
                        found |= readers.get(key, set())
                    self.assertEqual(set(row['readBy']), {by for by in found if not by.startswith('outside:')})
                    self.assertEqual(row['served'], TRANSPORT_KEY not in row['marks'])
                    self.assertNotIn('clock-valued', row['marks'])


if __name__ == '__main__':
    unittest.main()
