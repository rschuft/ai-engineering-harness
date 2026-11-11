"""Tests for tools/check_test_budget.py, policy/test-budgets.json and
evidence/test-profile/test-ids.json (plan leaf F-09.1, as amended by the Owner's direction of
2026-11-11: test runtime is diagnostic, not a gate).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

What blocks: a profile that is not green, a missing or invalid category, a unit class that is
not isolated, a removed recorded test and a new skip. What only notes: wall times, launch and
mkdtemp counts, new tests. The unit cases build a small synthetic profile in memory and mutate a
copy; the contract cases check the committed files. Nothing is written in the checkout.
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
PROFILER = REPO / 'tools' / 'test_profile.py'
BUDGETS_PATH = REPO / 'policy' / 'test-budgets.json'
BASELINE_PATH = REPO / 'evidence' / 'test-profile' / 'baseline.json'
RECORDED_PATH = REPO / 'evidence' / 'test-profile' / 'test-ids.json'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ctb = _load('check_test_budget', CHECKER)

CATEGORY = 'unit'


def scope(tests, launches=0, mkdtemp=0, wall=10.0, runs=3, **extra):
    return dict({'tests': tests, 'launches': launches, 'mkdtemp': mkdtemp, 'sockets': 0,
                 'chdir': 0, 'wall': {'runs': [wall] * runs, 'median': wall}}, **extra)


def rows(suite, cls, count, outcome='ok'):
    return [{'id': f'{cls}.test_{i}', 'suite': suite, 'outcome': outcome} for i in range(count)]


def synthetic(runs=3):
    """A full profile: suite tools (unit class m.U with 8 tests, integration class m.I with 2,
    one of them skipped) and suite store (integration class s.I with 4 tests)."""
    suites = [dict(scope(10, 5, 2, 20.0, runs), name='tools', start_dir='tools/tests',
                   successful=True, outcomes={'ok': 9, 'skip': 1}),
              dict(scope(4, 0, 1, 4.0, runs), name='store', start_dir='integrations/store/tests',
                   successful=True, outcomes={'ok': 4})]
    tests = rows('tools', 'm.U', 8) + rows('tools', 'm.I', 1) + \
        [{'id': 'm.I.test_skipped', 'suite': 'tools', 'outcome': 'skip'}] + rows('store', 's.I', 4)
    return {
        'schema': 'ai-engineering-harness/test-profile/v1',
        'revision': 'abc', 'dirty': False, 'measured': '2026-11-08', 'runs': runs,
        'host': {'system': 'Windows'},
        'totals': scope(14, 5, 3, 24.0, runs),
        'suites': suites,
        'categories': {'unit': dict(scope(8, 0, 1, 2.0, runs), classes=1),
                       'integration': dict(scope(6, 5, 2, 20.0, runs), classes=2)},
        'uncategorized': [], 'invalid_categories': [], 'determinism': [], 'problems': [],
        'classes': [{'id': 'm.U', 'suite': 'tools', 'category': 'unit', 'tests': 8,
                     'launches': 0, 'mkdtemp': 1, 'sockets': 0, 'chdir': 0, 'wall': 2.0},
                    {'id': 'm.I', 'suite': 'tools', 'category': 'integration', 'tests': 2,
                     'launches': 5, 'mkdtemp': 1, 'sockets': 0, 'chdir': 0, 'wall': 16.0},
                    {'id': 's.I', 'suite': 'store', 'category': 'integration', 'tests': 4,
                     'launches': 0, 'mkdtemp': 1, 'sockets': 0, 'chdir': 0, 'wall': 4.0}],
        'modules': [],
        'tests': tests,
    }


def codes(profile, budgets, recorded, counters_only=False):
    failures, notes = ctb.check(profile, budgets, recorded, counters_only)
    return sorted(f.code for f in failures), sorted(n.code for n in notes)


class BudgetCheckTests(unittest.TestCase):
    def setUp(self):
        self.profile = synthetic()
        self.budgets = ctb.propose(self.profile)
        self.recorded = ctb.record(self.profile)

    def check(self, counters_only=False):
        return codes(self.profile, self.budgets, self.recorded, counters_only)

    def bump(self, counter, delta, category='integration', suite='tools'):
        p = self.profile
        for entry in (p['totals'], p['categories'][category],
                      next(s for s in p['suites'] if s['name'] == suite)):
            entry[counter] += delta
        return p

    def drop(self, test_id):
        self.profile['tests'] = [r for r in self.profile['tests'] if r['id'] != test_id]

    def test_a_profile_passes_what_it_implies(self):
        self.assertEqual(ctb.check_budget_document(self.budgets), [])
        self.assertEqual(ctb.check_recorded_document(self.recorded), [])
        self.assertEqual(self.check(), ([], []))
        self.assertEqual(self.budgets['categories']['e2e'],
                         {'tests': 0, 'launches': 0, 'mkdtemp': 0, 'wall_s': 0.0})
        self.assertEqual(self.recorded['suites']['tools']['skipped'], ['m.I.test_skipped'])
        self.assertEqual(len(self.recorded['suites']['tools']['tests']), 10)

    def test_more_launches_or_temporary_directories_are_notes_not_failures(self):
        self.bump('launches', 1)
        self.assertEqual(self.check(), ([], ['LAUNCHES_ABOVE'] * 3))
        self.setUp()
        self.bump('mkdtemp', 1, category='unit')
        self.assertEqual(self.check(), ([], ['MKDTEMP_ABOVE'] * 3))
        self.setUp()
        self.bump('launches', -1)
        self.assertEqual(self.check(), ([], ['LAUNCHES_BELOW'] * 3))

    def test_a_slower_wall_is_never_a_failure_and_fifty_percent_is_the_signal(self):
        store = self.profile['suites'][1]['wall']
        store['median'] = 4.0 * 1.49
        self.assertEqual(self.check(), ([], []))
        store['median'] = 4.0 * 1.51
        self.assertEqual(self.check(), ([], ['WALL_SIGNAL']))
        store['median'] = 4.0 * 100
        self.assertEqual(self.check()[0], [])

    def test_sub_second_scopes_get_the_minimum_slack(self):
        self.assertAlmostEqual(ctb.signal_limit(0.1, self.budgets), 0.6)
        self.assertAlmostEqual(ctb.signal_limit(100.0, self.budgets), 150.0)

    def test_a_full_suite_above_five_minutes_is_a_signal_only(self):
        self.profile['totals']['wall']['median'] = 299.0
        self.assertEqual(self.check(), ([], ['WALL_SIGNAL']))
        self.profile['totals']['wall']['median'] = 301.0
        self.assertEqual(self.check(), ([], ['FULL_SUITE_SIGNAL', 'WALL_SIGNAL']))

    def test_more_tests_need_no_change_to_the_committed_files(self):
        self.profile['tests'] += rows('tools', 'm.New', 3) + rows('store', 's.New', 1)
        self.bump('tests', 3)
        self.bump('tests', 1, suite='store')
        self.bump('launches', 4)
        self.profile['totals']['wall']['median'] *= 1.2
        failed, notes = self.check()
        self.assertEqual(failed, [])
        self.assertIn('TESTS_NEW', notes)
        self.assertIn('TESTS_ABOVE', notes)
        self.assertIn('LAUNCHES_ABOVE', notes)

    def test_a_removed_test_fails(self):
        self.drop('m.U.test_3')
        failed, _ = self.check()
        self.assertEqual(failed, ['TEST_REMOVED'])
        failures, _ = ctb.check(self.profile, self.budgets, self.recorded)
        self.assertIn('m.U.test_3', failures[0].detail)

    def test_a_removed_test_fails_even_when_new_tests_keep_the_count(self):
        self.drop('m.U.test_3')
        self.profile['tests'] += rows('tools', 'm.New', 1)
        failed, notes = self.check()
        self.assertEqual(failed, ['TEST_REMOVED'])
        self.assertIn('TESTS_NEW', notes)

    def test_a_new_skip_fails(self):
        self.profile['tests'][0]['outcome'] = 'skip'
        self.assertEqual(self.check()[0], ['NEW_SKIP'])
        self.setUp()
        self.profile['tests'].append({'id': 'm.New.test_0', 'suite': 'tools', 'outcome': 'skip'})
        self.assertEqual(self.check()[0], ['NEW_SKIP'])

    def test_a_class_that_now_skips_in_set_up_class_fails(self):
        self.profile['tests'] = [r for r in self.profile['tests'] if not r['id'].startswith('m.U.')]
        self.profile['tests'].append({'id': 'setUpClass (m.U)', 'suite': 'tools', 'outcome': 'skip'})
        self.assertEqual(self.check()[0], ['NEW_SKIP', 'TEST_REMOVED'])

    def test_a_recorded_skip_may_run_or_disappear(self):
        self.profile['tests'] = [dict(r, outcome='ok') for r in self.profile['tests']]
        self.assertEqual(self.check()[0], [])
        self.drop('m.I.test_skipped')
        self.assertEqual(self.check()[0], [])

    def test_a_missing_suite_fails_and_a_new_suite_is_a_note(self):
        del self.profile['suites'][1]
        self.profile['tests'] = [r for r in self.profile['tests'] if r['suite'] != 'store']
        failed, notes = self.check()
        self.assertEqual(failed, ['SUITE_MISSING'])
        self.assertIn('NOT_IN_PROFILE', notes)
        self.setUp()
        extra = dict(copy.deepcopy(self.profile['suites'][1]), name='new')
        self.profile['suites'].append(extra)
        self.profile['tests'] += rows('new', 'n.I', 4)
        failed, notes = self.check()
        self.assertEqual(failed, [])
        self.assertEqual(notes, ['TESTS_NEW', 'UNMEASURED'])

    def test_a_compact_profile_checks_counts_instead_of_ids(self):
        del self.profile['tests']
        self.assertEqual(self.check(), ([], ['TEST_IDS_NOT_CHECKED']))
        self.profile['suites'][0]['tests'] -= 1
        self.assertEqual(self.check()[0], ['TEST_COUNT_FELL'])
        self.profile['suites'][0]['tests'] += 1
        self.profile['suites'][0]['outcomes']['skip'] += 1
        self.assertEqual(self.check()[0], ['NEW_SKIP'])

    def test_a_profile_that_is_not_green_fails(self):
        self.profile['suites'][0]['successful'] = False
        self.profile['problems'] = ['suite tools: modules failed to import']
        self.profile['determinism'] = [{'suite': 'tools', 'class': 'm.I', 'counter': 'tests'},
                                       {'suite': 'tools', 'outcomes_differ_in_run': 2}]
        failed, _ = self.check()
        self.assertEqual(failed, ['NONDETERMINISTIC', 'NONDETERMINISTIC', 'PROFILE_NOT_GREEN',
                                  'PROFILE_NOT_GREEN'])

    def test_counters_that_vary_between_runs_are_a_note(self):
        self.profile['determinism'] = [{'suite': 'tools', 'class': 'm.I', 'counter': counter}
                                       for counter in ctb.COUNTERS]
        self.assertEqual(self.check(), ([], ['COUNTERS_VARY'] * 4))

    def test_a_class_without_a_valid_category_fails(self):
        self.profile['uncategorized'] = ['m.X']
        self.profile['invalid_categories'] = ['m.Y']
        self.assertEqual(self.check()[0], ['UNCATEGORIZED', 'UNCATEGORIZED'])

    def test_a_unit_class_that_launches_or_opens_a_socket_fails(self):
        for counter in ('launches', 'sockets', 'chdir'):
            with self.subTest(counter=counter):
                self.setUp()
                self.profile['classes'][0][counter] = 1
                self.assertEqual(self.check()[0], ['UNIT_NOT_ISOLATED'])
        self.setUp()
        self.profile['modules'] = [{'id': 'm', 'suite': 'tools', 'category': 'unit', 'launches': 3}]
        self.assertEqual(self.check()[0], ['UNIT_NOT_ISOLATED'])
        self.setUp()
        self.profile['classes'][0]['mkdtemp'] = 9
        self.assertEqual(self.check()[0], [])

    def test_too_few_runs_leave_the_wall_uncompared(self):
        self.profile = synthetic(runs=1)
        self.profile['totals']['wall']['median'] = 1000.0
        self.assertEqual(self.check(), ([], ['FULL_SUITE_SIGNAL', 'WALL_NOT_COMPARED']))
        self.profile = synthetic()
        self.profile['totals']['wall']['median'] = 100.0
        self.assertEqual(self.check(counters_only=True), ([], ['WALL_NOT_COMPARED']))

    def test_malformed_documents_are_refused(self):
        bad = copy.deepcopy(self.budgets)
        bad['categories']['unit']['launches'] = -1
        del bad['categories']['performance']
        bad['signals']['regression'] = 'x'
        problems = ctb.check_budget_document(bad)
        self.assertEqual(len(problems), 3, problems)
        self.assertEqual(codes(self.profile, bad, self.recorded)[0], ['BUDGET_SCHEMA'] * 3)
        for key, value in (('recorded_tests', 'elsewhere.json'), ('wall', {'runs': 3, 'statistic': 'median',
                                                                           'tolerance': 0.3, 'min_slack_s': 0.5})):
            bad = dict(copy.deepcopy(self.budgets), **{key: value})
            self.assertEqual(len(ctb.check_budget_document(bad)), 1, key)
        for mutate in (lambda r: r['suites']['tools']['tests'].reverse(),
                       lambda r: r['suites']['tools']['skipped'].append('zz.not.a.test'),
                       lambda r: r['suites']['store'].update(extra=[]),
                       lambda r: r.update(schema='x'),
                       lambda r: r.update(suites={})):
            recorded = copy.deepcopy(self.recorded)
            mutate(recorded)
            self.assertEqual(codes(self.profile, self.budgets, recorded)[0], ['RECORDED_SCHEMA'])
        self.assertEqual(codes({'schema': 'x'}, self.budgets, self.recorded)[0], ['PROFILE_SCHEMA'])

    def test_record_needs_a_full_green_profile(self):
        compact = {k: v for k, v in self.profile.items() if k != 'tests'}
        with self.assertRaises(ValueError):
            ctb.record(compact)
        self.profile['suites'][1]['successful'] = False
        with self.assertRaises(ValueError):
            ctb.record(self.profile)

    def test_command_line_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix='ctb-') as tmp:
            profile_file, budget_file, recorded_file = (Path(tmp) / n for n in ('p.json', 'b.json', 'r.json'))
            profile_file.write_text(json.dumps(self.profile), encoding='utf-8')
            budget_file.write_text(json.dumps(self.budgets), encoding='utf-8')
            recorded_file.write_text(json.dumps(self.recorded), encoding='utf-8')
            files = ['--budgets', str(budget_file), '--recorded', str(recorded_file)]

            def run(*argv):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    status = ctb.main(list(argv))
                return status, out.getvalue()

            self.assertEqual(run('check', '--profile', str(profile_file), *files), (0, 'PASS\n'))
            status, out = run('propose', '--profile', str(profile_file))
            self.assertEqual((status, json.loads(out)), (0, self.budgets))
            status, out = run('record', '--profile', str(profile_file))
            self.assertEqual((status, json.loads(out)), (0, self.recorded))
            self.bump('launches', 1)
            self.profile['totals']['wall']['median'] = 400.0
            profile_file.write_text(json.dumps(self.profile), encoding='utf-8')
            status, out = run('check', '--profile', str(profile_file), *files)
            self.assertEqual(status, 0, out)
            self.assertIn('note: LAUNCHES_ABOVE', out)
            self.assertIn('note: FULL_SUITE_SIGNAL', out)
            self.drop('m.U.test_0')
            profile_file.write_text(json.dumps(self.profile), encoding='utf-8')
            status, out = run('check', '--profile', str(profile_file), *files)
            self.assertEqual(status, 1, out)
            self.assertIn('FAIL: TEST_REMOVED suite tools', out)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run('record', '--profile', str(budget_file))[0], 2)
                with self.assertRaises(SystemExit) as exit_:
                    run('check', '--profile', str(Path(tmp) / 'absent.json'), *files)
            self.assertEqual(exit_.exception.code, 2)


class CommittedBudgetTests(unittest.TestCase):
    """The committed measurements, the reference profile and the recorded test set."""
    category = 'contract'

    @classmethod
    def setUpClass(cls):
        cls.budgets = json.loads(BUDGETS_PATH.read_text(encoding='utf-8'))
        cls.baseline = json.loads(BASELINE_PATH.read_text(encoding='utf-8'))
        cls.recorded = json.loads(RECORDED_PATH.read_text(encoding='utf-8'))

    def test_the_measurements_are_well_formed_and_carry_the_owners_signals(self):
        self.assertEqual(ctb.check_budget_document(self.budgets), [])
        self.assertEqual(self.budgets['baseline']['profile'], 'evidence/test-profile/baseline.json')
        self.assertEqual(self.budgets['baseline']['revision'], self.baseline['revision'])
        self.assertEqual(self.budgets['recorded_tests'], 'evidence/test-profile/test-ids.json')
        self.assertEqual(self.budgets['wall'], {'runs': 3, 'statistic': 'median', 'min_slack_s': 0.5})
        self.assertEqual(self.budgets['signals'], {'regression': 0.5, 'full_suite_s': 300})

    def test_the_recorded_set_is_well_formed_and_names_the_suites_of_task_test(self):
        self.assertEqual(ctb.check_recorded_document(self.recorded), [])
        suites = [name for name, _ in _load('test_profile', PROFILER).select_suites([])]
        self.assertEqual(sorted(self.recorded['suites']), sorted(suites))
        self.assertEqual(sorted(self.budgets['suites']), sorted(suites))

    def test_the_reference_profile_passes_and_its_counters_are_the_measurements(self):
        failures, _ = ctb.check(self.baseline, self.budgets, None)
        self.assertEqual([str(f) for f in failures], [])
        proposed = ctb.propose(self.baseline)
        for group in ('categories', 'suites'):
            for name, entry in proposed[group].items():
                for counter in ('tests', 'launches', 'mkdtemp'):
                    self.assertEqual(self.budgets[group][name][counter], entry[counter],
                                     f'{group} {name} {counter}')

    def test_every_reference_class_has_a_category(self):
        self.assertEqual(self.baseline['uncategorized'], [])
        self.assertEqual(self.baseline['invalid_categories'], [])
        self.assertTrue(all(row['category'] in ctb.CATEGORIES for row in self.baseline['classes']))

    def profile_of_the_recorded_set(self):
        """The reference profile with the recorded set as its test rows (a full profile)."""
        profile = copy.deepcopy(self.baseline)
        profile['schema'] = 'ai-engineering-harness/test-profile/v1'
        profile['tests'] = [{'id': test_id, 'suite': suite,
                             'outcome': 'skip' if test_id in entry['skipped'] else 'ok'}
                            for suite, entry in self.recorded['suites'].items() for test_id in entry['tests']]
        return profile

    def test_a_removed_or_newly_skipped_test_fails_and_runtime_only_notes(self):
        profile = self.profile_of_the_recorded_set()
        self.assertEqual([str(f) for f in ctb.check(profile, self.budgets, self.recorded)[0]], [])
        running = next(r for r in profile['tests'] if r['outcome'] == 'ok')
        removed = copy.deepcopy(profile)
        removed['tests'].remove(running)
        self.assertEqual([f.code for f in ctb.check(removed, self.budgets, self.recorded)[0]], ['TEST_REMOVED'])
        skipped = copy.deepcopy(profile)
        next(r for r in skipped['tests'] if r['id'] == running['id'])['outcome'] = 'skip'
        self.assertEqual([f.code for f in ctb.check(skipped, self.budgets, self.recorded)[0]], ['NEW_SKIP'])
        slower = copy.deepcopy(profile)
        slower['tests'].append({'id': 'test_new.New.test_new', 'suite': 'tools', 'outcome': 'ok'})
        slower['categories']['integration']['launches'] += 100
        slower['totals']['wall']['median'] = 10 * self.budgets['total']['wall_s']
        failures, notes = ctb.check(slower, self.budgets, self.recorded)
        self.assertEqual(failures, [])
        self.assertTrue({'TESTS_NEW', 'LAUNCHES_ABOVE', 'WALL_SIGNAL', 'FULL_SUITE_SIGNAL'}
                        <= {n.code for n in notes})


if __name__ == '__main__':
    unittest.main()
