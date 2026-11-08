"""Tests for tools/check_test_budget.py and policy/test-budgets.json (plan leaf F-09.1).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The committed baseline profile (evidence/test-profile/baseline.json) must pass the committed
budgets, and an injected regression of each kind must fail. Every other case builds a small
synthetic profile in memory and mutates a copy. Nothing is written in the checkout.
"""
from pathlib import Path
import contextlib
import copy
import importlib.util
import io
import json
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / 'tools' / 'check_test_budget.py'
BUDGETS_PATH = REPO / 'policy' / 'test-budgets.json'
BASELINE_PATH = REPO / 'evidence' / 'test-profile' / 'baseline.json'

_spec = importlib.util.spec_from_file_location('check_test_budget', CHECKER)
ctb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ctb)

CATEGORY = 'unit'


def scope(tests, launches=0, mkdtemp=0, wall=10.0, runs=3, **extra):
    return dict({'tests': tests, 'launches': launches, 'mkdtemp': mkdtemp, 'sockets': 0,
                 'chdir': 0, 'wall': {'runs': [wall] * runs, 'median': wall}}, **extra)


def synthetic(runs=3):
    suites = [dict(scope(10, 5, 2, 20.0, runs), name='tools', start_dir='tools/tests',
                   successful=True, outcomes={'ok': 10}),
              dict(scope(4, 0, 1, 4.0, runs), name='store', start_dir='integrations/store/tests',
                   successful=True, outcomes={'ok': 4})]
    return {
        'schema': 'ai-engineering-harness/test-profile-compact/v1',
        'revision': 'abc', 'dirty': False, 'measured': '2026-11-08', 'runs': runs,
        'host': {'system': 'Windows'},
        'totals': scope(14, 5, 3, 24.0, runs),
        'suites': suites,
        'categories': {'unit': dict(scope(8, 0, 1, 2.0, runs), classes=2),
                       'integration': dict(scope(6, 5, 2, 20.0, runs), classes=1)},
        'uncategorized': [], 'invalid_categories': [], 'determinism': [], 'problems': [],
        'classes': [{'id': 'm.U', 'suite': 'tools', 'category': 'unit', 'tests': 8,
                     'launches': 0, 'mkdtemp': 1, 'sockets': 0, 'chdir': 0, 'wall': 2.0},
                    {'id': 'm.I', 'suite': 'tools', 'category': 'integration', 'tests': 6,
                     'launches': 5, 'mkdtemp': 2, 'sockets': 0, 'chdir': 0, 'wall': 20.0}],
    }


def codes(profile, budgets, counters_only=False):
    failures, notes = ctb.check(profile, budgets, counters_only)
    return [f.code for f in failures], [n.code for n in notes]


class BudgetCheckTests(unittest.TestCase):
    def setUp(self):
        self.profile = synthetic()
        self.budgets = ctb.propose(self.profile)

    def test_a_profile_passes_the_budgets_it_implies(self):
        self.assertEqual(ctb.check_budget_document(self.budgets), [])
        self.assertEqual(codes(self.profile, self.budgets), ([], []))
        self.assertEqual(self.budgets['categories']['e2e'],
                         {'tests': 0, 'launches': 0, 'mkdtemp': 0, 'wall_s': 0.0})

    def bump(self, counter, delta, category='integration', suite='tools'):
        p = self.profile
        for entry in (p['totals'], p['categories'][category],
                      next(s for s in p['suites'] if s['name'] == suite)):
            entry[counter] += delta
        return p

    def test_one_more_launch_fails(self):
        failed, _ = codes(self.bump('launches', 1), self.budgets)
        self.assertEqual(sorted(failed), ['LAUNCHES_ABOVE'] * 3)

    def test_one_more_temporary_directory_fails(self):
        failed, _ = codes(self.bump('mkdtemp', 1, category='unit'), self.budgets)
        self.assertEqual(sorted(failed), ['MKDTEMP_ABOVE'] * 3)

    def test_one_test_fewer_fails_and_one_more_is_a_note(self):
        failed, _ = codes(self.bump('tests', -1), self.budgets)
        self.assertEqual(sorted(failed), ['TESTS_BELOW'] * 3)
        self.setUp()
        failed, notes = codes(self.bump('tests', 1), self.budgets)
        self.assertEqual((failed, sorted(notes)), ([], ['TESTS_ABOVE'] * 3))

    def test_fewer_launches_pass_with_a_note(self):
        failed, notes = codes(self.bump('launches', -1), self.budgets)
        self.assertEqual((failed, sorted(notes)), ([], ['LAUNCHES_BELOW'] * 3))

    def test_wall_tolerance_is_thirty_percent_of_the_median(self):
        self.profile['suites'][1]['wall']['median'] = 4.0 * 1.29
        self.assertEqual(codes(self.profile, self.budgets), ([], []))
        self.profile['suites'][1]['wall']['median'] = 4.0 * 1.31
        self.assertEqual(codes(self.profile, self.budgets)[0], ['WALL_ABOVE'])

    def test_sub_second_scopes_get_the_minimum_slack(self):
        wall = self.budgets['wall']
        self.assertEqual(ctb.wall_limit(0.1, wall), 0.6)
        self.assertAlmostEqual(ctb.wall_limit(100.0, wall), 130.0)

    def test_too_few_runs_leave_the_wall_unmeasured_unless_counters_only(self):
        profile = synthetic(runs=1)
        profile['totals']['wall']['median'] = 1000.0
        self.assertEqual(codes(profile, self.budgets)[0], ['WALL_UNMEASURED'])
        self.assertEqual(codes(profile, self.budgets, counters_only=True),
                         ([], ['WALL_NOT_CHECKED']))

    def test_a_profile_that_is_not_green_fails(self):
        self.profile['suites'][0]['successful'] = False
        self.profile['problems'] = ['suite tools: modules failed to import']
        self.profile['determinism'] = [{'suite': 'tools', 'class': 'm.I', 'counter': 'launches'}]
        self.profile['uncategorized'] = ['m.X']
        failed, _ = codes(self.profile, self.budgets)
        self.assertEqual(sorted(failed), ['NONDETERMINISTIC', 'PROFILE_NOT_GREEN',
                                          'PROFILE_NOT_GREEN', 'UNCATEGORIZED'])

    def test_a_unit_class_that_launches_or_opens_a_socket_fails(self):
        self.profile['classes'][0]['sockets'] = 1
        self.assertEqual(codes(self.profile, self.budgets)[0], ['UNIT_NOT_ISOLATED'])
        self.profile['classes'][0]['sockets'] = 0
        self.profile['classes'][0]['chdir'] = 2
        self.assertEqual(codes(self.profile, self.budgets)[0], ['UNIT_NOT_ISOLATED'])

    def test_unbudgeted_and_missing_scopes_fail(self):
        extra = copy.deepcopy(self.profile['suites'][1])
        extra['name'] = 'new'
        self.profile['suites'].append(extra)
        self.assertIn('UNBUDGETED', codes(self.profile, self.budgets)[0])
        self.setUp()
        del self.profile['suites'][1]
        self.assertIn('SCOPE_MISSING', codes(self.profile, self.budgets)[0])

    def test_malformed_budgets_and_profiles_are_refused(self):
        bad = copy.deepcopy(self.budgets)
        bad['categories']['unit']['launches'] = -1
        del bad['categories']['performance']
        bad['wall']['tolerance'] = 'x'
        problems = ctb.check_budget_document(bad)
        self.assertEqual(len(problems), 3, problems)
        self.assertEqual(codes(self.profile, bad)[0], ['BUDGET_SCHEMA'] * 3)
        self.assertEqual(codes({'schema': 'x'}, self.budgets)[0], ['PROFILE_SCHEMA'])
        bad = copy.deepcopy(self.budgets)
        bad['suites']['tools']['extra'] = 1
        self.assertTrue(ctb.check_budget_document(bad))

    def test_command_line_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix='ctb-') as tmp:
            profile_file = Path(tmp) / 'p.json'
            budget_file = Path(tmp) / 'b.json'
            profile_file.write_text(json.dumps(self.profile), encoding='utf-8')
            budget_file.write_text(json.dumps(self.budgets), encoding='utf-8')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(ctb.main(['check', '--profile', str(profile_file),
                                           '--budgets', str(budget_file)]), 0)
                self.assertEqual(ctb.main(['propose', '--profile', str(profile_file)]), 0)
            self.assertIn('PASS', out.getvalue())
            self.assertEqual(json.loads(out.getvalue().split('PASS\n', 1)[1]), self.budgets)
            self.bump('launches', 1)
            profile_file.write_text(json.dumps(self.profile), encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(ctb.main(['check', '--profile', str(profile_file),
                                           '--budgets', str(budget_file)]), 1)
            self.assertIn('LAUNCHES_ABOVE', out.getvalue())
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_:
                ctb.main(['check', '--profile', str(Path(tmp) / 'absent.json'),
                          '--budgets', str(budget_file)])
            self.assertEqual(exit_.exception.code, 2)


class CommittedBudgetTests(unittest.TestCase):
    """The committed budgets against the committed baseline profile."""
    category = 'contract'

    @classmethod
    def setUpClass(cls):
        cls.budgets = json.loads(BUDGETS_PATH.read_text(encoding='utf-8'))
        cls.baseline = json.loads(BASELINE_PATH.read_text(encoding='utf-8'))

    def test_the_budget_file_is_well_formed_and_names_its_baseline(self):
        self.assertEqual(ctb.check_budget_document(self.budgets), [])
        self.assertEqual(self.budgets['baseline']['profile'], 'evidence/test-profile/baseline.json')
        self.assertEqual(self.budgets['baseline']['revision'], self.baseline['revision'])
        self.assertEqual(self.budgets['wall'], {'runs': 3, 'statistic': 'median', 'tolerance': 0.3,
                                                'min_slack_s': 0.5})

    def test_the_baseline_passes_and_its_counters_are_the_budgets(self):
        failures, _ = ctb.check(self.baseline, self.budgets)
        self.assertEqual([str(f) for f in failures], [])
        proposed = ctb.propose(self.baseline)
        for group in ('categories', 'suites'):
            for name, entry in proposed[group].items():
                for counter in ('tests', 'launches', 'mkdtemp'):
                    self.assertEqual(self.budgets[group][name][counter], entry[counter],
                                     f'{group} {name} {counter}')

    def test_every_baseline_class_has_a_category(self):
        self.assertEqual(self.baseline['uncategorized'], [])
        self.assertEqual(self.baseline['invalid_categories'], [])
        self.assertTrue(all(row['category'] in ctb.CATEGORIES for row in self.baseline['classes']))

    def test_an_injected_regression_fails(self):
        for counter, delta, code in (('launches', 1, 'LAUNCHES_ABOVE'),
                                     ('mkdtemp', 1, 'MKDTEMP_ABOVE'),
                                     ('tests', -1, 'TESTS_BELOW')):
            profile = copy.deepcopy(self.baseline)
            profile['categories']['integration'][counter] += delta
            failures, _ = ctb.check(profile, self.budgets)
            self.assertEqual([f.code for f in failures], [code], counter)
        profile = copy.deepcopy(self.baseline)
        profile['totals']['wall']['median'] = self.budgets['total']['wall_s'] * 1.31
        self.assertEqual([f.code for f in ctb.check(profile, self.budgets)[0]], ['WALL_ABOVE'])


if __name__ == '__main__':
    unittest.main()
