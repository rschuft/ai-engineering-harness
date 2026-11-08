"""Check a test profile against the test budgets (plan leaf F-09.1).

``policy/test-budgets.json`` holds the enforceable budgets, per category, per suite and in
total, derived from the measured baseline in ``evidence/test-profile/``. A profile comes from
``tools/test_profile.py run`` (full or compact form). Counters are exact; wall time is the
median of the budget's number of runs, with its tolerance.

It fails when:

- the profile is not green: a test failed, a module did not import, a child crashed, a
  counter or outcome differed between runs, or a class has no valid category;
- a ``unit`` class launched a process, opened a socket or changed directory;
- a scope (a category, a suite, the total) has fewer tests than its budget, or more
  launches or temporary directories (``mkdtemp``) than its budget;
- a scope's median wall time exceeds its budget times (1 + tolerance) (and its budget plus
  ``min_slack_s``, which keeps sub-second scopes clear of timer noise), or the profile has
  fewer runs than the budget's medians need (unless ``--counters-only``, which says so);
- the profile has a suite or category the budgets do not name, or the budget file is
  malformed.

Counts below budget (fewer launches or temporary directories, more tests) pass and are
reported, so the budget can be tightened deliberately. ``propose`` prints the budget document
a profile implies; changing ``policy/test-budgets.json`` is a reviewed change, never automatic.

When it runs: at the acceptance of every plan leaf and at every release (``task
test:budget``). It is never run from a git hook.

Usage (from the repository root):
    python -I -B tools/check_test_budget.py check (--profile FILE | --run) [--budgets FILE]
                                                  [--counters-only]
    python -I -B tools/check_test_budget.py propose --profile FILE [--tolerance 0.3]

Exit status: 0 PASS, 1 FAIL, 2 could not run.
"""
import argparse
import importlib.util
import json
import math
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BUDGETS = REPO / 'policy' / 'test-budgets.json'
BASELINE = 'evidence/test-profile/baseline.json'
SCHEMA = 'ai-engineering-harness/policy/test-budgets/v1'
PROFILE_SCHEMAS = ('ai-engineering-harness/test-profile/v1',
                   'ai-engineering-harness/test-profile-compact/v1')
CATEGORIES = ('unit', 'contract', 'integration', 'e2e', 'performance')
SCOPE_KEYS = ('tests', 'launches', 'mkdtemp', 'wall_s')
UNIT_FORBIDDEN = ('launches', 'sockets', 'chdir')


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
    """Schema problems of a budget document (a list of strings)."""
    problems = []
    if not isinstance(budgets, dict) or budgets.get('schema') != SCHEMA:
        return [f'schema must be {SCHEMA}']
    wall = budgets.get('wall')
    if not (isinstance(wall, dict) and _number(wall.get('runs'), True) and wall['runs'] >= 1
            and _number(wall.get('tolerance'), False) and 0 <= wall['tolerance'] < 5
            and _number(wall.get('min_slack_s'), False) and wall['min_slack_s'] >= 0
            and wall.get('statistic') == 'median' and len(wall) == 4):
        problems.append('wall must be {"runs": int >= 1, "statistic": "median", '
                        '"tolerance": number, "min_slack_s": number}')
    for group in ('categories', 'suites'):
        if not isinstance(budgets.get(group), dict) or not budgets[group]:
            problems.append(f'{group} must be a non-empty object')
    if isinstance(budgets.get('categories'), dict):
        for name in budgets['categories']:
            if name not in CATEGORIES:
                problems.append(f'categories: unknown category {name!r}')
        for name in CATEGORIES:
            if name not in budgets['categories']:
                problems.append(f'categories: {name} has no budget')
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


def check(profile, budgets, counters_only=False):
    """(failures, notes): lists of Finding."""
    failures, notes = [], []
    problems = check_budget_document(budgets)
    if problems:
        return [Finding('BUDGET_SCHEMA', 'policy', p) for p in problems], notes
    if profile.get('schema') not in PROFILE_SCHEMAS:
        return [Finding('PROFILE_SCHEMA', 'profile', f'schema must be one of {PROFILE_SCHEMAS}')], notes

    for problem in profile.get('problems', []):
        failures.append(Finding('PROFILE_NOT_GREEN', 'profile', problem))
    for suite in profile['suites']:
        if not suite['successful']:
            failures.append(Finding('PROFILE_NOT_GREEN', f'suite {suite["name"]}',
                                    f'outcomes {suite["outcomes"]}'))
    for item in profile.get('determinism', []):
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

    wall = budgets['wall']
    runs = profile.get('runs', 0)
    check_wall = not counters_only
    if check_wall and runs < wall['runs']:
        failures.append(Finding('WALL_UNMEASURED', 'profile',
                                f'{runs} run(s); the budget medians need {wall["runs"]}'))
        check_wall = False
    if counters_only:
        notes.append(Finding('WALL_NOT_CHECKED', 'profile', '--counters-only'))

    have = _profile_scopes(profile)
    want = _budget_scopes(budgets)
    for label in sorted(set(have) - set(want)):
        entry = have[label][0]
        if label.startswith('category ') and not entry.get('tests'):
            continue
        failures.append(Finding('UNBUDGETED', label, 'the budgets do not name this scope'))
    for label, budget in sorted(want.items()):
        observed, median = have.get(label, (None, None))
        if observed is None:
            if label.startswith('category ') and budget['tests'] == 0:
                continue
            failures.append(Finding('SCOPE_MISSING', label, 'the profile has no such scope'))
            continue
        if observed['tests'] < budget['tests']:
            failures.append(Finding('TESTS_BELOW', label,
                                    f'{observed["tests"]} tests, budget at least {budget["tests"]}'))
        elif observed['tests'] > budget['tests']:
            notes.append(Finding('TESTS_ABOVE', label,
                                 f'{observed["tests"]} tests, budget {budget["tests"]}'))
        for counter in ('launches', 'mkdtemp'):
            if observed[counter] > budget[counter]:
                failures.append(Finding(f'{counter.upper()}_ABOVE', label,
                                        f'{observed[counter]}, budget at most {budget[counter]}'))
            elif observed[counter] < budget[counter]:
                notes.append(Finding(f'{counter.upper()}_BELOW', label,
                                     f'{observed[counter]}, budget {budget[counter]}'))
        if check_wall:
            limit = wall_limit(budget['wall_s'], wall)
            if median > limit:
                failures.append(Finding('WALL_ABOVE', label,
                                        f'median {median:.2f} s, budget {budget["wall_s"]:.1f} s, '
                                        f'limit {limit:.2f} s'))
    return failures, notes


def wall_limit(budget_s, wall):
    """The largest passing median: the budget plus its tolerance, and never less than the
    budget plus min_slack_s, so that sub-second scopes do not fail on timer noise."""
    return max(budget_s * (1 + wall['tolerance']), budget_s + wall['min_slack_s'])


def _ceil_tenth(seconds):
    return math.ceil(round(seconds * 10, 6)) / 10


def propose(profile, tolerance=0.3, runs=3, baseline_path=BASELINE, min_slack_s=0.5):
    """The budget document a profile implies: its exact counters and its wall medians
    (rounded up to a tenth of a second)."""
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
        'description': ('Enforceable test budgets (plan leaf F-09.1). Counters are exact: tests '
                        'at least, launches and mkdtemp at most. wall_s is a median over '
                        'wall.runs serial runs on the baseline host; a median passes up to '
                        'wall_s x (1 + wall.tolerance), and never below wall_s + '
                        'wall.min_slack_s. Checked by tools/check_test_budget.py (task '
                        'test:budget) at every leaf acceptance and release, never in a hook.'),
        'baseline': {'revision': profile.get('revision'), 'measured': profile.get('measured'),
                     'runs': profile.get('runs'), 'host': profile.get('host'),
                     'profile': baseline_path},
        'wall': {'runs': runs, 'statistic': 'median', 'tolerance': tolerance,
                 'min_slack_s': min_slack_s},
        'total': scope(profile['totals'], profile['totals']['wall']['median']),
        'suites': {s['name']: scope(s, s['wall']['median']) for s in profile['suites']},
        'categories': categories,
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
    p_check = sub.add_parser('check', help='check a profile against the budgets')
    source = p_check.add_mutually_exclusive_group(required=True)
    source.add_argument('--profile', help='a profile from tools/test_profile.py run')
    source.add_argument('--run', action='store_true',
                        help='profile the suites now (the budget\'s number of runs)')
    p_check.add_argument('--budgets', default=str(DEFAULT_BUDGETS))
    p_check.add_argument('--counters-only', action='store_true',
                         help='check counters and outcomes only (one run is enough)')
    p_prop = sub.add_parser('propose', help='print the budgets a profile implies')
    p_prop.add_argument('--profile', required=True)
    p_prop.add_argument('--tolerance', type=float, default=0.3)
    p_prop.add_argument('--runs', type=int, default=3)
    p_prop.add_argument('--baseline-path', default=BASELINE)
    args = parser.parse_args(argv)

    if args.command == 'propose':
        profile = _load_json(args.profile, 'profile')
        print(json.dumps(propose(profile, args.tolerance, args.runs, args.baseline_path),
                         indent=1))
        return 0

    budgets = _load_json(args.budgets, 'budgets')
    if args.run:
        problems = check_budget_document(budgets)
        if problems:
            return _could_not(f'malformed budgets: {problems[0]}')
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
        failures, notes = check(profile, budgets, args.counters_only)
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
