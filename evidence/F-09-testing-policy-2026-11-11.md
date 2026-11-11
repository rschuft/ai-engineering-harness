# F-09 testing policy: test runtime is diagnostic, not a gate (2026-11-11)

Builder evidence of 2026-11-11 for the Overseer's dispatch applying the Owner's direction of
2026-11-11, "test runtime is diagnostic, not a gate" (quoted verbatim in
[`bootstrap-log.md`](bootstrap-log.md), Decisions). The direction retires the 150 s serial ceiling,
the per-suite wall-clock ceilings and the exact launch and `mkdtemp` budgets as blockers, keeps
runtime and process counts as diagnostics, prefers parallel tests by default, keeps genuine test
failures and the detection of removed or skipped tests blocking, and asks for the minimum policy
and tooling change. The verdict is the Overseer's and the Owner's.

- **Commits** (on `f8506b2`): `8b9442e` (the concurrent runner), `d2e3ff0` (the test check and the
  recorded test set), `20f51d6` (documentation), `e6af9c9` (the plan amendment), `9b2f62b` (fix
  forward of the runner's summary line), `58cf3b7` (this record); after the Overseer's review
  `6b9a6ec` (the historical `original_proof` fields restored), `34d36a2` (the no-window guard covers
  `tools/test_profile.py`), then this record's correction.
- **Host:** Windows 11 x86_64, 32 logical processors, CPython 3.12.10 under the `python-tools`
  interpreter. Every run from Git Bash with `PYTHONDONTWRITEBYTECODE=1` and `AIEH_DATA_ROOT` an
  empty scratch directory (the runner gives each suite its own); Windows Disk Cleanup (`cleanmgr`)
  absent before each run. `task` is not installed: each target ran as the command it wraps.

## 1. The test check (`tools/check_test_budget.py`, `d2e3ff0`)

| Blocks (exit 1) | Code |
|---|---|
| A failing or erroring test, a module that does not import, a crashed child | `PROFILE_NOT_GREEN` |
| A test count or an outcome that differs between runs | `NONDETERMINISTIC` |
| A class with no valid category (category separation) | `UNCATEGORIZED` |
| A `unit` class or module fixture that launches, opens a socket or changes directory (unit isolation, as enforced before) | `UNIT_NOT_ISOLATED` |
| A recorded test that was not skipped and did not run (removed, renamed, or its class now skips in `setUpClass`) | `TEST_REMOVED` |
| A recorded suite that did not run | `SUITE_MISSING` |
| A skip the recorded set does not record | `NEW_SKIP` |
| A compact profile (no ids): a suite with fewer tests, or more skips, than the recorded set | `TEST_COUNT_FELL`, `NEW_SKIP` |
| A malformed policy, recorded set or profile | `BUDGET_SCHEMA`, `RECORDED_SCHEMA`, `PROFILE_SCHEMA` |

| Notes only (never fail) | Code |
|---|---|
| Tests, launches, `mkdtemp` above or below the recorded measurements | `TESTS_ABOVE`/`_BELOW`, `LAUNCHES_ABOVE`/`_BELOW`, `MKDTEMP_ABOVE`/`_BELOW` |
| Launch, `mkdtemp`, socket or `chdir` counts that differ between runs | `COUNTERS_VARY` |
| New tests, new suites, scopes the measurements do not name | `TESTS_NEW`, `UNMEASURED`, `NOT_IN_PROFILE` |
| Fewer runs than the recorded medians (or `--counters-only`) | `WALL_NOT_COMPARED` |
| A median at least 50% above its recorded measurement (and at least `min_slack_s` = 0.5 s above it) | `WALL_SIGNAL` |
| A serial total above 300 s | `FULL_SUITE_SIGNAL` |

The two signals are the Owner's investigation heuristics, worded in each note as "an investigation
signal, not a gate". `policy/test-budgets.json` is schema v2: the same figures of the reference
profile (`a57b043`), no tolerance, `signals` {regression 0.5, full_suite_s 300} and the path of
the recorded test set. `propose` prints the measurements a profile implies; `record` prints the
recorded set of a full green profile.

**Removed-test detection: test ids, not count floors.** The recorded set,
[`test-profile/test-ids.json`](test-profile/test-ids.json), holds every suite's test ids (2,587
rows: 2,575 tests and 12 `setUpClass (…)` rows of classes that skip as a whole) and the 35 ids
skipped when it was recorded. A count floor needs no data file, but once later tests have raised
the count it no longer sees a removal unless it is raised with every change, which is the
per-change churn the Owner removed. With ids, a removal blocks however many tests were added since,
new tests need no commit, and the set is re-recorded only in a reviewed change that removes,
renames or skips tests deliberately. A recorded skip that now runs, or a skipped class's
`setUpClass` row that disappears because its tests now run, passes. The set was recorded with an
empty data root, the most restrictive environment, so tests that skip without installed tools are
recorded as skipped; where they run, that passes.

The set was recorded from a full profile of the working tree whose content `d2e3ff0` committed
(the profile reports `f8506b2`, dirty: the commit came after the recording, so that the checker,
its tests and the set land together). A first profile was not green by construction: the new
`CommittedBudgetTests` needs the set it was about to record (a provisional set, written from that
profile without its one error row, let the tests load; the second, green profile replaced it).

## 2. The concurrent runner (`tools/run_tests.py`, `8b9442e`, `9b2f62b`)

`task test` now runs `<tools python> -I -B tools/run_tests.py`: every suite of `task test:serial`
(the former `test` list, unchanged) at once, at most one per processor (`--jobs N` caps it), each as
`<tools python> -I -B -m unittest discover -s <suite> -v` in a child of its own from the repository
root, with an empty `AIEH_DATA_ROOT` of its own under a temporary directory and
`PYTHONDONTWRITEBYTECODE=1`, started with `creationflags=_no_window().no_window_flags()`. Each
suite's output is printed when it ends, then a summary and the wall time as information; exit 1
when a suite failed. An interrupted run kills the suites already started and waits for them. No
test was restructured, and no suite is kept serial: each runs in its own process with its own data
root, and the full concurrent run below passed. `tools/test_profile.py` reads the suite list from
`test:serial` (`SUITES_TARGET`), so the profile and `check --run` still measure the same suites
serially.

`9b2f62b` fixes forward a defect introduced by `8b9442e` and exposed by the full run: the summary
took a suite's last output line for its result, and the tools suite's last line is a test's own
stdout (`}`), flushed after unittest's verdict when the process exits. The summary now takes
unittest's verdict line. Exit statuses were never affected.

## 3. The plan amendment (`e6af9c9`)

A new dated `amendments` entry quotes the direction, cites the log and quotes each superseded
clause; the notes of F-09, F-09.1, F-09.3, F-09.4 and F-10.3 record it. Changed, in the plan JSON
(proof, `completion_evidence`, notes, `overseer_prompt`), the HTML (cards, prompts, lower-cased
search text, `planData`), the CSV, the prompts of F-09.1 to F-09.4 and F-10.3, `task_manifest.json`
and `SEED_MANIFEST.json`. `e6af9c9` also rewrote the F-09 group's `original_proof` and the F-09
gate on F-09.4 that copies it; those are historical fields, and `6b9a6ec` restored both to their
`f8506b2` values with what renders the gate (F-09.4's prompt line under "PARENT ACCEPTANCE CHECKS
AT THIS STEP", its HTML card and the CSV gate cell), and corrected the amendment entry's summary
and F-09.4's note. Against `f8506b2` the plan JSON now differs only in `amendments`, the F-09
group's `proof`, `completion_evidence` and notes, and the proof, `completion_evidence`, notes and
`overseer_prompt` of F-09.1, F-09.3 and F-10.3, F-09.2's `overseer_prompt`, and F-09.4's notes and
`overseer_prompt` (its "Required outcome" line only). Consequence for the Overseer: F-09.4's gate
line and card still show the original F-09 proof, with its 150 s clause, as the historical
original; the amended proof is the group's `proof`.

| Field | Before | After |
|---|---|---|
| F-09 proof (and F-09.1 to F-09.4's "Required outcome"; not `original_proof` or the F-09.4 gate) | … the budget check passes on the baseline and fails on an injected regression; serial task test takes at most 150 s; every fail-closed security proof stays in a required tier. | … the budget check passes on the baseline and fails on an injected removed or newly skipped test, while wall times and launch and mkdtemp counts are reported as diagnostics, never as gates; every fail-closed security proof stays in a required tier. |
| F-09.1 proof | … the budget check passes on the baseline and fails on an injected regression. | … the budget check passes on the baseline and fails on an injected removed or newly skipped test; wall times and launch and mkdtemp counts are reported as diagnostics, never as gates. |
| F-09.3 proof | … with the CLI contracts kept; serial task test takes at most 150 s; the test count is at least the baseline; … | … with the CLI contracts kept; the test count is at least the baseline; … |
| F-10.3 proof | … task test:budget PASS on re-proposed budgets and serial task test at most 150 s; … | … task test:budget PASS, its wall times and counts recorded as diagnostics; … |

Unchanged by design, as the entry says: actions and artifacts (they describe the work as planned and
done), the leaf-specific measured results that are those leaves' own deliverables (F-09.3's launch
reductions, F-09.4's traversal launches, F-10.3's speed ratios, the wall times F-09.2 and F-10.4
record), and the `task test:budget` passes of F-10.5 and R-05.4.1, which now name the check as it
is. No field tied runtime gating to a security or acceptance property that could not be separated:
in the F-09 proof the fail-closed security clause is its own clause.

## 4. Documentation (`20f51d6`)

`docs/development.md`: the quick start (five commands), the `test`, `test:serial` and `test:budget`
rows, and the Testing section (the concurrent run; the direction and its signals; the recorded test
set and when it is re-recorded; the measurements file; the wall-time history kept as history with
the ceiling retired). The per-change rebaselining requirement is removed. `policy/README.md`'s
test-budget section says the same. The root README states no ceiling and is unchanged.

## 5. Checks

| Check | Result |
|---|---|
| `test_check_test_budget.py` (26 tests) | OK. Negative controls among them: a removed test, a removed test hidden by a new one (a rename), a new skip (of a recorded test and of a new test), a class that newly skips in `setUpClass`, a missing suite, an uncategorized class, a unit class that launches, opens a socket or changes directory each fail; more launches or `mkdtemp`, slower walls (to 100x), a total above 300 s, counters that vary between runs and more tests each only note, with the committed files unchanged |
| Controls on the real profile (scratch script, the checker's command line) | Unchanged: PASS. One recorded test removed: exit 1 `TEST_REMOVED`. One test newly skipped: exit 1 `NEW_SKIP`. A unit class with a launch: exit 1 `UNIT_NOT_ISOLATED`. An uncategorized class: exit 1 `UNCATEGORIZED`. Every wall x2 with launches and `mkdtemp` +50: exit 0 with `WALL_SIGNAL` and `FULL_SUITE_SIGNAL` notes. 25 new test ids: exit 0 with a `TESTS_NEW` note |
| `test_run_tests.py` (7 tests), `test_test_profile.py` (26), `test_pytest_conftest.py` (20, 4 skipped without pytest as before), `test_launch_census.py` (21) | OK |
| No-window guard on `tools/run_tests.py` | Passes; with the flag removed the guard reports `no creationflags (via subprocess.Popen)` (negative control, census helper on a mutated copy) |
| Serial profile, one run (`test_profile.py run`), then `check --profile` | 2,575 tests, PASS; notes only (counts above or below the reference, `WALL_NOT_COMPARED`). Serial totals 171.2 s and 214.0 s in two runs on a host slower than at the reference (138.7 s): information |
| **Full suite through `task test`'s command** (`tools/run_tests.py`) at `e6af9c9` | **13 suites, 0 failed**, every suite OK (tools 1,344 tests, skipped 6); **wall 113.1 s** (information). No process of the run was left afterwards (process lists before and after), and its temporary directory was removed |
| `tools/run_tests.py --suite platform --suite paths --suite credentials` at `9b2f62b` | OK; the summary shows each verdict |
| `verify_seed.py` and `verify_seed.py --baseline seed` | PASS (167 tasks, 172 contract files intact) and PASS (seed baseline) |
| Publication gate | pre-commit PASS on every commit; `publication_gate.py history` at `9b2f62b`: PASS (495 commits) |

## 6. Deviations and findings

- **Files outside the dispatch's edit list, needed for the concurrent `task test`:** the new
  `tools/run_tests.py` and its tests; `tools/test_profile.py` (one constant: the profile reads the
  suite list from `test:serial`, since `test` now runs the runner); the Taskfile contract tests in
  `tools/tests/test_pytest_conftest.py` and the reader tests in `tools/tests/test_test_profile.py`
  follow the new layout with the same assertions. Renamed test ids:
  `test_pytest_conftest.RequiredTargets.test_test_runs_every_suite_under_the_tools_interpreter`
  became `…test_test_serial_runs_every_suite_under_the_tools_interpreter` (same assertions) beside
  the new `…test_test_runs_the_suites_concurrently_under_the_tools_interpreter`; the checker's tests
  for the old blocking rules became tests of the new ones.
- **Unrelated but detected, then fixed (`34d36a2`):** `tools/test_profile.py`'s own launches
  (`run_child`, `run_plain`) passed no creation flags, and the no-window guard did not scan it
  because its name starts with `test_`. They now use the helper, and the guard excludes only
  modules inside a `tests/` directory; no other non-test module was hidden by the old rule. The
  guard reports both launches of the previous file (negative control).
- **Unrelated but detected:** `build_profile` keys test rows by id across suites; two suites with
  the same module and test name would lose a row. None collide today (2,587 rows, equal to the
  suites' tests and fixture rows).
- `test:budget` stays an acceptance obligation at every leaf acceptance and release (unchanged); it
  no longer gates runtime.

## 7. Not verified

The runner on Linux or macOS; an interactive Ctrl-C of `task test`; a run from a parent with no
console; `task` itself (not installed).
