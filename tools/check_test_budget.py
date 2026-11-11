"""Check a test profile against the recorded test set and report its runtime as diagnostics
(plan leaf F-09.1, as amended by the Owner's direction of 2026-11-11: test runtime is
diagnostic, not a gate).

A profile comes from ``tools/test_profile.py run`` (full or compact form). It is checked
against two committed files:

- ``evidence/test-profile/test-ids.json``, the recorded test set: every suite's test ids and
  the ids that were skipped when it was recorded (``record`` writes it from a full profile);
- ``policy/test-budgets.json``, the recorded measurements of the reference profile in
  ``evidence/test-profile/`` (tests, launches, ``mkdtemp`` and median wall time per category,
  per suite and in total) and the Owner's investigation signals.

It fails (blocks) only on what is not a performance measurement:

- the profile is not green: a test failed or errored, a module did not import, a child
  crashed, or a test or an outcome differed between runs;
- a class has no valid category, or a ``unit`` class (or module fixture) launched a process,
  opened a socket or changed directory (category separation and unit isolation);
- a recorded test that was not skipped is missing (a removed or renamed test, or a class that
  now skips in ``setUpClass``), a recorded suite is missing, or a test is skipped that the
  recorded set does not record as skipped (a new skip). A compact profile has no test ids:
  then a suite with fewer tests, or more skips, than the recorded set fails instead;
- the policy or the recorded set is malformed.

Everything else is a note and never fails: wall times, launch and ``mkdtemp`` counts that
differ from the recorded measurements, launch, ``mkdtemp``, socket or ``chdir`` counts that
differ between runs, new tests, and scopes the measurements do not name. Two notes are the
Owner's investigation signals, never thresholds that block work: a median at least 50% above
its recorded measurement (``WALL_SIGNAL``), and a full serial set above five minutes
(``FULL_SUITE_SIGNAL``).

New tests need no commit. The recorded set changes only when tests are deliberately removed,
renamed or skipped: re-record it from a full profile (``record``) in the same reviewed change.
``propose`` prints the measurements a profile implies; they need no update when tests are
added.

When it runs: at the acceptance of every plan leaf and at every release (``task
test:budget``). It is never run from a git hook.

Usage (from the repository root):
    python -I -B tools/check_test_budget.py check (--profile FILE | --run) [--budgets FILE]
                                                  [--recorded FILE] [--counters-only]
    python -I -B tools/check_test_budget.py record --profile FULL_PROFILE
    python -I -B tools/check_test_budget.py propose --profile FILE

Exit status: 0 PASS, 1 FAIL, 2 could not run.
"""
import argparse
import importlib.util
import json
import math
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BUDGETS = REPO / 'policy' / 'test-budgets.json'
BASELINE = 'evidence/test-profile/baseline.json'
RECORDED = 'evidence/test-profile/test-ids.json'
SCHEMA = 'ai-engineering-harness/policy/test-budgets/v2'
RECORDED_SCHEMA = 'ai-engineering-harness/test-ids/v1'
PROFILE_SCHEMAS = ('ai-engineering-harness/test-profile/v1',
                   'ai-engineering-harness/test-profile-compact/v1')
CATEGORIES = ('unit', 'contract', 'integration', 'e2e', 'performance')
SCOPE_KEYS = ('tests', 'launches', 'mkdtemp', 'wall_s')
COUNTERS = ('launches', 'mkdtemp', 'sockets', 'chdir')
UNIT_FORBIDDEN = ('launches', 'sockets', 'chdir')
# The Owner's investigation signals (2026-11-11): roughly 50% above a comparable measurement, or
# a full suite above five minutes. Notes for a reviewer, never blocking thresholds.
SIGNALS = {'regression': 0.5, 'full_suite_s': 300}
# unittest reports a class or module fixture that skips or fails as one row such as
# 'setUpClass (module.Class)' (its _ErrorHolder), not as the tests it holds.
FIXTURE_ROW = re.compile(r'^(setUpClass|tearDownClass|setUpModule|tearDownModule) \(.+\)$')


def load_profiler():
    spec = importlib.util.spec_from_file_location(
        'test_profile', Path(__file__).resolve().parent / 'test_profile.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Finding:
    def __init__(self, code, scope, detail):
        self.code, self.scope, self.detail = code, scope, detail

    def __str__(self):
        return f'{self.code} {self.scope}: {self.detail}'


def _number(value, integer):
    if isinstance(value, bool):
        return False
    return isinstance(value, int) if integer else isinstance(value, (int, float))


def check_budget_document(budgets):
    """Schema problems of the measurements document (a list of strings)."""
    problems = []
    if not isinstance(budgets, dict) or budgets.get('schema') != SCHEMA:
        return [f'schema must be {SCHEMA}']
    wall = budgets.get('wall')
    if not (isinstance(wall, dict) and _number(wall.get('runs'), True) and wall['runs'] >= 1
            and _number(wall.get('min_slack_s'), False) and wall['min_slack_s'] >= 0
            and wall.get('statistic') == 'median' and len(wall) == 3):
        problems.append('wall must be {"runs": int >= 1, "statistic": "median", "min_slack_s": number}')
    signals = budgets.get('signals')
    if not (isinstance(signals, dict) and set(signals) == set(SIGNALS)
            and all(_number(v, False) and v > 0 for v in signals.values())):
        problems.append('signals must be {"regression": number > 0, "full_suite_s": number > 0}')
    if budgets.get('recorded_tests') != RECORDED:
        problems.append(f'recorded_tests must be {RECORDED}')
    for group in ('categories', 'suites'):
        if not isinstance(budgets.get(group), dict) or not budgets[group]:
            problems.append(f'{group} must be a non-empty object')
    if isinstance(budgets.get('categories'), dict):
        for name in budgets['categories']:
            if name not in CATEGORIES:
                problems.append(f'categories: unknown category {name!r}')
        for name in CATEGORIES:
            if name not in budgets['categories']:
                problems.append(f'categories: {name} has no measurement')
    scopes = [('total', budgets.get('total'))]
    for group in ('categories', 'suites'):
        if isinstance(budgets.get(group), dict):
            scopes += [(f'{group[:-1] if group == "suites" else "category"} {k}', v)
                       for k, v in budgets[group].items()]
    for label, scope in scopes:
        if not isinstance(scope, dict) or set(scope) != set(SCOPE_KEYS):
            problems.append(f'{label}: needs exactly {", ".join(SCOPE_KEYS)}')
            continue
        for key in SCOPE_KEYS:
            if not _number(scope[key], key != 'wall_s') or scope[key] < 0:
                problems.append(f'{label}: {key} must be a non-negative '
                                f'{"number" if key == "wall_s" else "integer"}')
    return problems


def _id_list(value):
    return (isinstance(value, list) and all(isinstance(i, str) and i for i in value)
            and value == sorted(set(value)))


def check_recorded_document(recorded):
    """Schema problems of the recorded test set (a list of strings)."""
    if not isinstance(recorded, dict) or recorded.get('schema') != RECORDED_SCHEMA:
        return [f'schema must be {RECORDED_SCHEMA}']
    problems = []
    suites = recorded.get('suites')
    if not isinstance(suites, dict) or not suites:
        return ['suites must be a non-empty object']
    for name, entry in suites.items():
        if not (isinstance(entry, dict) and set(entry) == {'tests', 'skipped'}
                and _id_list(entry['tests']) and _id_list(entry['skipped'])):
            problems.append(f'suite {name}: needs exactly "tests" and "skipped", sorted lists of '
                            f'distinct ids')
        elif not set(entry['skipped']) <= set(entry['tests']):
            problems.append(f'suite {name}: a skipped id is not among its tests')
    return problems


def _profile_scopes(profile):
    scopes = {'total': (profile['totals'], profile['totals']['wall']['median'])}
    for suite in profile['suites']:
        scopes[f'suite {suite["name"]}'] = (suite, suite['wall']['median'])
    for name, entry in profile['categories'].items():
        scopes[f'category {name}'] = (entry, entry['wall']['median'])
    return scopes


def _budget_scopes(budgets):
    scopes = {'total': budgets['total']}
    scopes.update({f'suite {k}': v for k, v in budgets['suites'].items()})
    scopes.update({f'category {k}': v for k, v in budgets['categories'].items()})
    return scopes


def _short(ids, limit=5):
    ids = sorted(ids)
    more = f' and {len(ids) - limit} more' if len(ids) > limit else ''
    return ', '.join(ids[:limit]) + more


def _check_recorded(profile, recorded, failures, notes):
    """The recorded test set against the profile: removed tests, missing suites and new skips
    fail; new tests are a note."""
    have = {s['name']: s for s in profile['suites']}
    rows = profile.get('tests')
    for name, entry in sorted(recorded['suites'].items()):
        label = f'suite {name}'
        recorded_ids, recorded_skips = set(entry['tests']), set(entry['skipped'])
        if name not in have:
            failures.append(Finding('SUITE_MISSING', label,
                                    f'the recorded set has {len(recorded_ids)} tests in this suite; '
                                    f'the profile does not run it'))
            continue
        if rows is None:
            # A compact profile has counts, not ids: the suite's tests run and its skips.
            running = sum(1 for i in recorded_ids if not FIXTURE_ROW.match(i))
            if have[name]['tests'] < running:
                failures.append(Finding('TEST_COUNT_FELL', label,
                                        f'{have[name]["tests"]} tests, the recorded set has {running}'))
            skips = have[name]['outcomes'].get('skip', 0)
            if skips > len(recorded_skips):
                failures.append(Finding('NEW_SKIP', label,
                                        f'{skips} skipped, the recorded set has {len(recorded_skips)}'))
            continue
        outcomes = {r['id']: r['outcome'] for r in rows if r['suite'] == name}
        removed = recorded_ids - recorded_skips - set(outcomes)
        if removed:
            failures.append(Finding('TEST_REMOVED', label,
                                    f'{len(removed)} recorded test(s) did not run: {_short(removed)}'))
        skipped = {i for i, outcome in outcomes.items() if outcome == 'skip'} - recorded_skips
        if skipped:
            failures.append(Finding('NEW_SKIP', label,
                                    f'{len(skipped)} test(s) skipped that the recorded set does not '
                                    f'record as skipped: {_short(skipped)}'))
        added = set(outcomes) - recorded_ids
        if added:
            notes.append(Finding('TESTS_NEW', label, f'{len(added)} test(s) not in the recorded set'))
    for name in sorted(set(have) - set(recorded['suites'])):
        notes.append(Finding('TESTS_NEW', f'suite {name}', 'a suite the recorded set does not name'))
    if rows is None:
        notes.append(Finding('TEST_IDS_NOT_CHECKED', 'profile',
                             'a compact profile: suite test and skip counts checked instead'))


def signal_limit(wall_s, budgets):
    """The median above which a scope's wall time is an investigation signal: its recorded
    median plus the regression share, and never less than that plus min_slack_s, so that
    sub-second scopes do not signal on timer noise."""
    share = budgets['signals']['regression']
    return max(wall_s * (1 + share), wall_s + budgets['wall']['min_slack_s'])


def check(profile, budgets, recorded, counters_only=False):
    """(failures, notes): lists of Finding. ``recorded`` is the recorded test set, or None to
    leave it out (the committed reference profile predates the set)."""
    failures, notes = [], []
    problems = check_budget_document(budgets)
    if problems:
        return [Finding('BUDGET_SCHEMA', 'policy', p) for p in problems], notes
    if recorded is not None:
        problems = check_recorded_document(recorded)
        if problems:
            return [Finding('RECORDED_SCHEMA', 'recorded', p) for p in problems], notes
    if profile.get('schema') not in PROFILE_SCHEMAS:
        return [Finding('PROFILE_SCHEMA', 'profile', f'schema must be one of {PROFILE_SCHEMAS}')], notes

    for problem in profile.get('problems', []):
        failures.append(Finding('PROFILE_NOT_GREEN', 'profile', problem))
    for suite in profile['suites']:
        if not suite['successful']:
            failures.append(Finding('PROFILE_NOT_GREEN', f'suite {suite["name"]}',
                                    f'outcomes {suite["outcomes"]}'))
    for item in profile.get('determinism', []):
        if item.get('counter') in COUNTERS:
            notes.append(Finding('COUNTERS_VARY', 'profile', json.dumps(item, sort_keys=True)))
        else:
            failures.append(Finding('NONDETERMINISTIC', 'profile', json.dumps(item, sort_keys=True)))
    for class_id in profile.get('uncategorized', []):
        failures.append(Finding('UNCATEGORIZED', class_id, 'declares no category'))
    for class_id in profile.get('invalid_categories', []):
        failures.append(Finding('UNCATEGORIZED', class_id, 'declares an unknown category'))
    for row in profile.get('classes', []) + profile.get('modules', []):
        if row.get('category') == 'unit':
            used = {k: row[k] for k in UNIT_FORBIDDEN if row.get(k)}
            if used:
                failures.append(Finding('UNIT_NOT_ISOLATED', row['id'], json.dumps(used)))
    if recorded is not None:
        _check_recorded(profile, recorded, failures, notes)

    # Diagnostics: the recorded measurements, and the Owner's investigation signals.
    runs = profile.get('runs', 0)
    compare_wall = not counters_only and runs >= budgets['wall']['runs']
    if not compare_wall:
        notes.append(Finding('WALL_NOT_COMPARED', 'profile',
                             f'{runs} run(s); the recorded medians are of {budgets["wall"]["runs"]}'))
    total = profile['totals']['wall']['median']
    if total > budgets['signals']['full_suite_s']:
        notes.append(Finding('FULL_SUITE_SIGNAL', 'total',
                             f'serial median {total:.1f} s, above {budgets["signals"]["full_suite_s"]} s: '
                             f'an investigation signal, not a gate'))
    have = _profile_scopes(profile)
    want = _budget_scopes(budgets)
    for label in sorted(set(have) - set(want)):
        if label.startswith('category ') and not have[label][0].get('tests'):
            continue
        notes.append(Finding('UNMEASURED', label, 'the recorded measurements do not name this scope'))
    for label, budget in sorted(want.items()):
        observed, median = have.get(label, (None, None))
        if observed is None:
            if not (label.startswith('category ') and budget['tests'] == 0):
                notes.append(Finding('NOT_IN_PROFILE', label, 'a measured scope the profile does not have'))
            continue
        for counter in ('tests', 'launches', 'mkdtemp'):
            if observed[counter] != budget[counter]:
                direction = 'ABOVE' if observed[counter] > budget[counter] else 'BELOW'
                notes.append(Finding(f'{counter.upper()}_{direction}', label,
                                     f'{observed[counter]}, recorded {budget[counter]}'))
        if compare_wall and median > signal_limit(budget['wall_s'], budgets):
            notes.append(Finding('WALL_SIGNAL', label,
                                 f'median {median:.2f} s, recorded {budget["wall_s"]:.1f} s: '
                                 f'an investigation signal, not a gate'))
    return failures, notes


def _ceil_tenth(seconds):
    return math.ceil(round(seconds * 10, 6)) / 10


def propose(profile, runs=3, baseline_path=BASELINE, min_slack_s=0.5):
    """The measurements document a profile implies: its counters and its wall medians (rounded
    up to a tenth of a second), with the Owner's signals."""
    def scope(entry, median):
        return {'tests': entry['tests'], 'launches': entry['launches'],
                'mkdtemp': entry['mkdtemp'], 'wall_s': _ceil_tenth(median)}

    categories = {}
    for name in CATEGORIES:
        entry = profile['categories'].get(name)
        categories[name] = (scope(entry, entry['wall']['median']) if entry else
                            {'tests': 0, 'launches': 0, 'mkdtemp': 0, 'wall_s': 0.0})
    return {
        'schema': SCHEMA,
        'description': ('Recorded test measurements (plan leaf F-09.1, as amended on 2026-11-11: '
                        'test runtime is diagnostic, not a gate). Counts and wall medians of the '
                        'reference profile, per category, per suite and in total; wall_s is a median '
                        'over wall.runs serial runs on the reference host. They are compared as '
                        'notes only, never as gates, and need no update when tests are added. A '
                        'median above wall_s x (1 + signals.regression), and never below wall_s + '
                        'wall.min_slack_s, or a serial total above signals.full_suite_s, is an '
                        'investigation signal. What blocks is the recorded test set (recorded_tests): '
                        'removed or newly skipped tests. Checked by tools/check_test_budget.py (task '
                        'test:budget), never in a hook.'),
        'baseline': {'revision': profile.get('revision'), 'measured': profile.get('measured'),
                     'runs': profile.get('runs'), 'host': profile.get('host'),
                     'profile': baseline_path},
        'recorded_tests': RECORDED,
        'wall': {'runs': runs, 'statistic': 'median', 'min_slack_s': min_slack_s},
        'signals': dict(SIGNALS),
        'total': scope(profile['totals'], profile['totals']['wall']['median']),
        'suites': {s['name']: scope(s, s['wall']['median']) for s in profile['suites']},
        'categories': categories,
    }


def record(profile):
    """The recorded test set a full profile implies: per suite, every test id it ran (a class
    or module fixture that skipped as one row included) and the ids that were skipped."""
    if 'tests' not in profile:
        raise ValueError('a full profile is needed (tools/test_profile.py run --out FILE): '
                         'a compact profile has no test ids')
    if profile.get('problems') or not all(s['successful'] for s in profile['suites']):
        raise ValueError('the profile is not green')
    suites = {s['name']: {'tests': set(), 'skipped': set()} for s in profile['suites']}
    for row in profile['tests']:
        suites[row['suite']]['tests'].add(row['id'])
        if row['outcome'] == 'skip':
            suites[row['suite']]['skipped'].add(row['id'])
    return {
        'schema': RECORDED_SCHEMA,
        'description': ('The recorded test set (the Owner\'s direction of 2026-11-11: detect '
                        'accidentally removed or skipped tests). A recorded test that was not '
                        'skipped and does not run, or a skip not recorded here, fails '
                        'tools/check_test_budget.py check; new tests need no change here. Re-record '
                        'it (check_test_budget.py record --profile <full profile>) only in a reviewed '
                        'change that removes, renames or skips tests deliberately.'),
        'recorded_from': {'revision': profile.get('revision'), 'dirty': profile.get('dirty'),
                          'measured': profile.get('measured'), 'host': profile.get('host')},
        'suites': {name: {'tests': sorted(e['tests']), 'skipped': sorted(e['skipped'])}
                   for name, e in suites.items()},
    }


def _load_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise SystemExit(_could_not(f'cannot read the {what} {path}: {exc}'))


def _could_not(message):
    print(f'could not run: {message}', file=sys.stderr)
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    p_check = sub.add_parser('check', help='check a profile against the recorded test set')
    source = p_check.add_mutually_exclusive_group(required=True)
    source.add_argument('--profile', help='a profile from tools/test_profile.py run')
    source.add_argument('--run', action='store_true',
                        help='profile the suites now (the recorded medians\' number of runs)')
    p_check.add_argument('--budgets', default=str(DEFAULT_BUDGETS))
    p_check.add_argument('--recorded', help=f'the recorded test set (default: {RECORDED})')
    p_check.add_argument('--counters-only', action='store_true',
                         help='one run: no wall comparison and no comparison between runs')
    p_record = sub.add_parser('record', help='print the recorded test set a full profile implies')
    p_record.add_argument('--profile', required=True)
    p_prop = sub.add_parser('propose', help='print the measurements a profile implies')
    p_prop.add_argument('--profile', required=True)
    p_prop.add_argument('--runs', type=int, default=3)
    p_prop.add_argument('--baseline-path', default=BASELINE)
    args = parser.parse_args(argv)

    if args.command == 'propose':
        profile = _load_json(args.profile, 'profile')
        print(json.dumps(propose(profile, args.runs, args.baseline_path), indent=1))
        return 0
    if args.command == 'record':
        profile = _load_json(args.profile, 'profile')
        try:
            print(json.dumps(record(profile), indent=1))
        except (ValueError, KeyError, TypeError) as exc:
            return _could_not(f'cannot record from {args.profile}: {exc}')
        return 0

    budgets = _load_json(args.budgets, 'measurements')
    recorded = _load_json(args.recorded or REPO / RECORDED, 'recorded test set')
    if args.run:
        problems = check_budget_document(budgets) + check_recorded_document(recorded)
        if problems:
            return _could_not(f'malformed policy: {problems[0]}')
        profiler = load_profiler()
        workdir = Path(tempfile.mkdtemp(prefix='aieh-test-budget-'))
        runs = 1 if args.counters_only else budgets['wall']['runs']
        profile = profiler.run_profile(runs, profiler.select_suites([]), workdir)
        (workdir / 'profile.json').write_text(json.dumps(profile, indent=1) + '\n',
                                              encoding='utf-8')
        print(f'profile: {workdir / "profile.json"}')
        profiler.print_summary(profile)
    else:
        profile = _load_json(args.profile, 'profile')
    try:
        failures, notes = check(profile, budgets, recorded, args.counters_only)
    except (KeyError, TypeError) as exc:
        return _could_not(f'malformed profile: {exc!r}')
    for note in notes:
        print(f'note: {note}')
    for failure in failures:
        print(f'FAIL: {failure}')
    print('PASS' if not failures else f'FAIL ({len(failures)})')
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(main())
