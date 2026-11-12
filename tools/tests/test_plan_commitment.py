"""Tests for tools/plan_commitment.py: closure, status parsing, readiness and refusals."""

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

CATEGORY = 'unit'

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location('plan_commitment', ROOT / 'tools' / 'plan_commitment.py')
pc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pc)


def leaf(ident, deps=(), title=None):
    return {'id': ident, 'title': title or f'Leaf {ident}', 'deps': list(deps)}


PLAN = {
    'work_packages': [
        leaf('A-01.1'),
        leaf('A-01.2', ['A-01.1']),
        leaf('B-01.1', ['A-01.1']),
        leaf('B-01.2', ['A-01.2', 'B-01.1']),
        leaf('C-01.1', ['B-01.2']),
        leaf('D-01.1'),
    ],
    'decomposition': {'medium_parent_aliases': {'B-01': 'B-01.2'}, 'legacy_parent_aliases': {}},
}

LOG = """# Log

## Owner actions

| Id | Status |
|---|---|
| OA-1 | **PASS** |

## Leaves

Intro text.

| Task | Verdict | Revision | Evidence | Parent gates |
|---|---|---|---|---|
| A-01.1 First | **PASS (2026-11-06)** for the profile | `abc` | e | g |
| A-01.2 Second | PASS (2026-11-06); pushed | `def` | e | g |
| B-01.1 Third | **IN PROGRESS (2026-11-11)**: slice 1 | x | e | g |
| B-01 headroom (a group row, not a leaf) | **PASS (2026-11-10)** | x | e | g |
| D-01.1 Other | **BLOCKED on one clause (review)** | x | e | g |

## Decisions

| B-01.2 Not a leaves row | **PASS** | x | e | g |
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.plan = self.write('plan.json', json.dumps(PLAN))
        self.log = self.write('log.md', LOG)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding='utf-8')
        return str(path)

    def run_main(self, *argv, plan=None, log=None):
        out, err = io.StringIO(), io.StringIO()
        args = list(argv) + ['--plan', plan or self.plan, '--log', log or self.log]
        code = pc.main(args, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()


class StatusParsingTests(unittest.TestCase):
    def test_first_bold_token_reduced_to_leading_upper_case_words(self):
        cases = {
            '**PASS (2026-11-12)**: accepted': 'PASS',
            '**IN PROGRESS (2026-11-11)**: slice 2': 'IN PROGRESS',
            '**BLOCKED on one clause (acceptance review 2026-11-12; OA-21)**': 'BLOCKED',
            '**STOPPED (2026-11-11)** at the boundary': 'STOPPED',
            '**PASS:** done, then **FAIL** later': 'PASS',
            'PASS (2026-11-06), specification only; pushed': 'PASS',
            'Not started': 'not started',
        }
        for cell, expected in cases.items():
            with self.subTest(cell=cell):
                self.assertEqual(pc.status_of(cell), expected)

    def test_leaves_table_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'log.md'
            path.write_text(LOG, encoding='utf-8')
            statuses = pc.load_statuses(path)
        self.assertEqual(statuses['A-01.1'], 'PASS')
        self.assertEqual(statuses['A-01.2'], 'PASS')
        self.assertEqual(statuses['B-01.1'], 'IN PROGRESS')
        self.assertEqual(statuses['D-01.1'], 'BLOCKED')
        self.assertNotIn('B-01.2', statuses)  # a row under Decisions is not a Leaves row
        self.assertNotIn('OA-1', statuses)


class ClosureAndReadinessTests(Fixture):
    def test_closure_is_the_transitive_dependencies_in_dependency_order(self):
        result = pc.report('B-01.2', self.plan, self.log)
        ids = [r['id'] for r in result['leaves']]
        self.assertEqual(ids, ['A-01.1', 'A-01.2', 'B-01.1', 'B-01.2'])
        self.assertNotIn('C-01.1', ids)  # a dependant is not in the closure
        self.assertNotIn('D-01.1', ids)  # an unrelated leaf is not either

    def test_readiness_and_summary(self):
        result = pc.report('C-01.1', self.plan, self.log)
        rows = {r['id']: r for r in result['leaves']}
        self.assertTrue(rows['A-01.1']['passed'])
        self.assertFalse(rows['A-01.1']['ready'])  # passed is never ready
        self.assertTrue(rows['B-01.1']['ready'])  # in progress, its dependency passed
        self.assertEqual(rows['B-01.2']['status'], 'not started')  # no row
        self.assertFalse(rows['B-01.2']['ready'])  # B-01.1 has not passed
        self.assertFalse(rows['C-01.1']['ready'])
        self.assertEqual(rows['B-01.2']['deps'], ['A-01.2', 'B-01.1'])
        self.assertEqual(result['summary'], {'total': 5, 'passed': 2, 'open': 3, 'ready': 1, 'blocked': 2})
        self.assertEqual(result['ready'], ['B-01.1'])

    def test_own_status_does_not_change_readiness(self):
        result = pc.report('D-01.1', self.plan, self.log)
        (row,) = result['leaves']
        self.assertEqual((row['status'], row['ready']), ('BLOCKED', True))

    def test_text_and_json_output(self):
        code, out, err = self.run_main('C-01.1')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('Summary: total 5, passed 2, open 3, ready 1, blocked 2', out)
        self.assertIn('Ready: B-01.1', out)
        code, out, _ = self.run_main('C-01.1', '--json')
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data['schema'], 'ai-engineering-harness/plan-commitment/v1')
        self.assertEqual(data['terminal'], 'C-01.1')
        self.assertEqual(data['summary']['total'], 5)


class RefusalTests(Fixture):
    def assert_refused(self, code_name, *argv, **paths):
        code, out, err = self.run_main(*argv, '--json', **paths)
        self.assertEqual(code, 2)
        self.assertIn(f'REFUSED {code_name}:', err)
        self.assertEqual(json.loads(out)['error']['code'], code_name)
        return err

    def test_unknown_leaf(self):
        self.assert_refused('UNKNOWN_LEAF', 'Z-09.9')

    def test_group_id_names_its_terminal_leaf(self):
        err = self.assert_refused('UNKNOWN_LEAF', 'B-01')
        self.assertIn('its terminal leaf is B-01.2', err)

    def test_cycle(self):
        plan = {'work_packages': [leaf('X-01.1', ['X-01.2']), leaf('X-01.2', ['X-01.1']),
                                  leaf('X-01.3', ['X-01.2'])]}
        err = self.assert_refused('DEPENDENCY_CYCLE', 'X-01.3', plan=self.write('cycle.json', json.dumps(plan)))
        self.assertIn('X-01.1, X-01.2', err)

    def test_unreadable_files(self):
        missing = str(self.dir / 'absent.json')
        self.assert_refused('UNREADABLE_FILE', 'A-01.1', plan=missing)
        self.assert_refused('UNREADABLE_FILE', 'A-01.1', plan=self.write('bad.json', '{not json'))
        self.assert_refused('UNREADABLE_FILE', 'A-01.1', plan=self.write('nowp.json', '{}'))
        self.assert_refused('UNREADABLE_FILE', 'A-01.1', log=self.write('noleaves.md', '# Log\n\n## Decisions\n'))
        self.assert_refused('UNREADABLE_FILE', 'A-01.1', log=str(self.dir / 'absent.md'))


class CommittedPlanTests(unittest.TestCase):
    """The committed plan and log: every leaf's closure computes, the D1 terminal leaf's included."""

    category = 'contract'

    def test_d1_closure(self):
        result = pc.report('E-05.5')
        ids = [r['id'] for r in result['leaves']]
        self.assertEqual(ids[-1], 'E-05.5')
        for ident in ('E-05.1', 'E-05.2', 'E-05.3', 'E-05.4', 'E-01.3.2', 'S-03.3', 'P-04.3'):
            self.assertIn(ident, ids)
        self.assertEqual(len(ids), len(set(ids)))
        position = {ident: n for n, ident in enumerate(ids)}
        for row in result['leaves']:
            for dep in row['deps']:
                self.assertLess(position[dep], position[row['id']])
        s = result['summary']
        self.assertEqual(s['total'], s['passed'] + s['ready'] + s['blocked'])

    def test_every_leaf_resolves(self):
        leaves, _ = pc.load_plan(pc.ROOT / pc.PLAN)
        for ident in leaves:
            pc.closure(leaves, ident)
