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


if __name__ == '__main__':
    unittest.main()
