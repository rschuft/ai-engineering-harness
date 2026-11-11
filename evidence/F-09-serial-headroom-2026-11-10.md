# F-09 serial headroom: room under the 150 s ceiling for the inference suite

Builder evidence of 2026-11-10 for the Overseer's bounded test-runtime slice under the Owner's
scheduling priority of 2026-11-08 (a serial suite of at most 150 s, equivalent results across the
runners, every required security and contract test still enforced, no reduction in meaningful
coverage, measured before and after, no redesign of the testing architecture). F-09 patterns only,
no new leaf. The verdict is the Overseer's.

- **Why:** S-03.2 slice 1 stopped at the test budget: a serial median of 154.5 s at `b6b206f`, the
  new inference suite adding about 1.7 s and every unchanged suite measuring 3-7 % slower than the
  `6f10385` baseline (host drift). Overseer ruling: the 150 s ceiling is not raised; make room
  instead, at least 6 s at the median, then budget the inference suite.
- **Reached:** the store suite **19.03 → 11.09 s** (interleaved medians, section 1), from one test
  module; the serial median **152.2 → 141.2 s** in the same interleaved set (the other suites are
  the same code at both revisions and moved within noise). `check --run` at `e00fb06`:
  **PASS**, serial median **142.0 s** (8.0 s under the ceiling), store 11.6 s.
- **Commits** (on `40150ce`): `e89a097` (the store crash tests), `a71707c` (the CI validation job
  runs the inference suite; `example_config.yml` shows the broker's settings; one new test),
  `e00fb06` (budgets and baseline re-proposed at `a71707c`), then this record. Test code, the
  configuration template, the CI workflow, the budgets, the baseline and this record only; no product
  file, no integrity-tracked file, nothing under `decisions/`, `evidence/bootstrap-log.md`
  untouched.
- **Host:** Windows 11 x86_64, 32 logical processors, CPython 3.12.10 under the `python-tools`
  interpreter. Every run from Git Bash with `PYTHONDONTWRITEBYTECODE=1` and `AIEH_DATA_ROOT`,
  `TEMP` and `TMP` set to new, empty directories under the session scratch (the data root empty
  after every run). Windows Disk Cleanup (`cleanmgr`) absent before and after every timed run
  (checked by each run's script, which refuses to start while it runs). `task` is not installed:
  each target ran as the command it wraps.
- **Raw material** (not committed): `<session scratch>/c61`: the profiles (`prof/before1.json`,
  `prof/store1.json`, `prof/ab-{before,after}-{1,2,3}.json`, `prof/budget3.json` and its compact
  form), the run scripts and logs (`scripts/`, `logs/`), the budget proposal and merge
  (`budget/`), the budget check's profile (`prof/budget-check1.json`), the mutation runners and their results (`scripts/mutate.py`, `scripts/mutate2.py`,
  `mut/run/mutation-results.json`, `logs/mutate*.log`).

## 1. Before and after

Before: `40150ce`. After: `e89a097` (`a71707c` adds one inference test and changes no timing;
`e00fb06` only re-proposes the budgets). Full serial profiles (`tools/test_profile.py run`),
interleaved in the checkout (after, before, three times; `git checkout --detach` and back to
`main`).

| Suite | Before runs (s) | Before median | After runs (s) | After median | Change |
|---|---|---|---|---|---|
| tools | 75.79, 75.85, 76.51 | 75.85 | 74.23, 75.06, 78.23 | 75.06 | −0.78 (same code) |
| **store** | 18.87, 19.03, 19.54 | **19.03** | 11.09, 11.03, 11.86 | **11.09** | **−7.94** |
| effects | 2.74, 2.87, 2.75 | 2.75 | 2.74, 2.85, 2.84 | 2.84 | +0.09 |
| planning | 12.62, 13.56, 13.15 | 13.15 | 12.29, 12.35, 12.83 | 12.35 | −0.79 (same code) |
| lineage | 15.52, 16.01, 15.71 | 15.71 | 14.80, 15.06, 16.06 | 15.06 | −0.65 (same code) |
| owner | 4.33, 4.32, 4.24 | 4.32 | 4.42, 4.31, 4.74 | 4.42 | +0.11 |
| paths | 1.61, 1.57, 1.58 | 1.58 | 1.55, 1.59, 1.68 | 1.59 | +0.01 |
| platform | 0.29, 0.27, 0.28 | 0.28 | 0.25, 0.26, 0.27 | 0.26 | −0.02 |
| credentials | 0.87, 0.88, 0.88 | 0.88 | 0.87, 0.88, 0.92 | 0.88 | +0.01 |
| gitea | 2.53, 2.50, 2.48 | 2.50 | 2.52, 2.49, 2.53 | 2.52 | +0.02 |
| dispatch | 6.26, 6.44, 6.20 | 6.26 | 6.21, 6.23, 6.51 | 6.23 | −0.03 |
| repository | 7.27, 7.44, 7.15 | 7.27 | 7.14, 7.31, 7.55 | 7.31 | +0.04 |
| inference | 1.66, 1.73, 1.69 | 1.69 | 1.59, 1.77, 1.78 | 1.77 | +0.09 |
| **serial** | 150.4, 152.4, 152.2 | **152.2** | 139.7, 141.2, 147.8 | **141.2** | **−10.9** |

The attributable saving is the store suite's 7.9 s; the rest of the serial difference is noise
between runs of identical code (the third after-run was slow across tools, lineage and
repository alike). A first single profile at `40150ce`, before any change, measured 147.8 s
(store 18.6 s). The host was slower than the `6f10385` baseline throughout (that baseline's
serial median was 144.6 s with 92 fewer tests).

The changed tests (medians of the interleaved runs):

| Test or class | Before (s) | After (s) | Launches | mkdtemp |
|---|---|---|---|---|
| `CrashMatrixTests.test_crash_matrix` | 8.003 | 1.326 | 57 → 57 | 20 → 20 |
| `RestartTests.test_restart_after_each_lifecycle_state` | 1.444 | 0.402 | 10 → 10 | 6 → 6 |
| `CrashMatrixTests` (class) | 8.153 | 1.470 | 58 → 58 | 21 → 21 |
| `RestartTests` (class) | 1.851 | 0.813 | 13 → 13 | 7 → 7 |
| `CrashMatrixTests.test_killed_writer_releases_the_lock` (unchanged) | 0.149 | 0.147 | 1 | 1 |
| `ConcurrencyTests` (unchanged) | 2.476 | 2.465 | 56 | 7 |

## 2. Where the time went (profile first)

The first profile at `40150ce` (147.8 s), its largest classes:

| Class | Wall (s) | Launches | Disposition |
|---|---|---|---|
| `test_publication_gate.WithRealScanner` | 16.1 | 96 | Real hooks and the pinned Gitleaks are the subject; one shared allowlist declined earlier (F-09 runtime headroom). Not changed. |
| `test_publication_gate.FailsClosed` | 8.7 | 71 | Real hook runs failing closed. Not changed. |
| **`test_reservation_crash_concurrency.CrashMatrixTests`** | **7.9** | **58** | **19 independent rows run one after another, three worker launches each (about 136 ms a launch): changed (section 3).** |
| `test_guest.NetprobeListener` | 6.8 | 3 | The pinned netprobe's 2.0 s wait and Windows' refusal delay. Not changed. |
| `test_check_network_matrix.Acceptance`, `test_check_containment_cases.Rules` | 4.8, 3.6 | 0 | The checkers' own evaluation (product cost). Not changed. |
| `test_git_batch.Launcher` | 3.4 | 7 | Its 1 s ceilings are the subject. Not changed. |
| `test_verify_seed` | 6.0 | 32 | The integrity-tracked verifier's cost. Not changed. |
| `test_resolvers.ObjectiveResolution` | 2.5 | 30 | Fixture repositories amended per test (git commits). Not changed. |
| `ConcurrencyTests` | 2.5 | 56 | Eight workers already race together per test. Not changed. |
| **`RestartTests`** | **1.8** | **13** | **Five independent lifecycle paths run one after another: changed (section 3).** |

In the lineage and planning suites no single test took more than 1.1 s; the largest are the
`Launcher` ceilings (the subject), the git oracle of `Equivalence` (the subject) and fixture
repositories amended by git commits per test (`ObjectiveResolution`, the `test_trace` classes).
The one serial run of independent launches found there, `RegistryAndCommandLine.test_resolve_command`
(six CLI runs against one shared fixture repository, 0.9 s), was left as it is: whether the
resolver's read path writes to that repository was not established, and the saving (about 0.7 s)
was not needed for the target. The store change alone met it.

## 3. The change, and why every assertion is preserved

`integrations/store/tests/test_reservation_crash_concurrency.py` only:

| # | Change | Saving (s) | Counters |
|---|---|---|---|
| 1 | **The crash matrix runs its rows' steps in waves.** Each of the 19 rows still gets a fresh store of its own (`new_store()`: the same `mkdtemp` prefix and the same in-process create and migrate as `setUp`). Step 0: every row's crash worker (`store_worker.py scripted`) is started, then each is read to its crash point and checked exactly as before (`crashed()`, the old `crash()` body: the crash label, the kill of a holding worker, the non-zero exit and `CRASH_EXIT`), and the WAL check. Step 1: every surviving row's fresh-process read (`get`) is started together (`run_workers`, the same command `run_worker` runs, each result read on the worker's own exit), then each row's checks run in the old order (the read, the in-process counts, `assert_store_verifies`). Step 2: every surviving row's re-request (`reserve-attempt`) likewise, then the claim rule and `assert_store_verifies`. | **6.7** (8.00 → 1.33) | launches 57, mkdtemp 20: unchanged |
| 2 | **The restart test's five lifecycle paths run in two waves** (every `scripted` run, then every `reserve-attempt`), each path on a fresh store of its own, with the old checks per path. | **1.0** (1.44 → 0.40) | launches 10, mkdtemp 6: unchanged |

Why nothing a test proves changed:

- **Every row still runs its own real processes in its own order** on its own database: the crash
  worker stops at the same statement (by `os._exit` or by a kill while holding the write lock),
  a new process reads what persisted before anything else opens that database (so the WAL is
  still unconsumed), the parent then counts and verifies, a further process re-requests, and the
  parent applies the claim rule. Across rows nothing is shared: each database is in a temporary
  directory of its own, so starting the rows' workers together changes no row's inputs or order,
  only the wall time. No test's subject is how long a worker takes.
- **A failing row stops where it failed and the others continue**, as before: each step's checks
  run inside the row's `subTest`, and a row whose check failed is not given a later step.
- **No assertion was removed, weakened or reworded.** One was added to each test: every row (or
  path) ran every step (`completed` equals the full list), so a harness that silently dropped a
  row cannot pass (mutations T3 and T4 below are killed only by it).
- `run_workers` kills only workers this test started, and only if one is still running when the
  wave is left by an exception; each result is read with `communicate` under the same 60 s
  ceiling as `run_worker` (a ceiling on a hang, never waited out on a passing run). No sleep.

## 4. Equivalence

- **Test ids and outcomes:** each of the three interleaved before/after pairs has the same 2,270
  profile rows (2,263 tests and the class and module fixture rows) with the same outcome each (ok
  2,240, skip 30), and all six profiles carry the same outcomes digest (`b0f86e3b…`). The store
  suite under unittest: 84 tests, OK, before and after.
- **Counters:** every class's launches, mkdtemp, sockets and chdir equal before and after (the
  serial totals 1,160 launches and 1,043 mkdtemp in every run).
- The inference suite gained one test in `a71707c` (section 6): 92 → 93 tests, outcome ok.

## 5. Mutation checks

In a throwaway copy of `git archive HEAD integrations` with the changed test file copied in (TEMP
and data root outside the copy, empty before, empty after each mutant), each mutation applied
alone and the targeted tests run under the tools interpreter. M0, the unmutated copy:
`CrashMatrixTests` and `RestartTests`, 4 tests OK.

| Id | Mutation | Targeted tests | Result |
|---|---|---|---|
| P1 | product: a live claim is never refused | `test_crash_matrix` | killed (1 failure, 17 errors) |
| P2 | product: an identical re-request reports `created` | crash matrix, restart | killed (20 failures) |
| P3 | product: a transition skips a `state_seq` | crash matrix, restart | killed (9 failures) |
| P4 | product: the reservation commits its identity row on its own, before the attempt row | `test_crash_matrix` | killed (20 failures) |
| T1 | harness: `run_workers` returns the results in reverse order | crash matrix, restart | killed (18 failures, 6 errors) |
| T2 | harness: every fresh-process read goes to the first row's store | `test_crash_matrix` | killed (1 failure, 13 errors) |
| T3 | harness: the rows are silently dropped before the re-request step | `test_crash_matrix` | killed (the added completion check) |
| T4 | harness: the restart paths are silently dropped | restart | killed (the added completion check) |
| T5 | harness: the WAL check reads the first row's store | `test_crash_matrix` | killed (13 failures) |

The example-configuration test (`a71707c`), the same way on a copy holding `example_config.yml`:
E0 unmutated OK; **killed** each of E1 (the component line uncommented, so the template sets it),
E2 (a commented value differs from the default), E3 (the component block renamed), E4 (product:
the shipped `max_ttl_s` default changes) and E5 (a commented port is given a value).

## 6. Wiring follow-ups from slice 1 (`a71707c`)

- `policy/ci/workflows/validation.yml`: the quality step's suite loop runs
  `integrations/inference/tests` after the repository suite. `tools/check_ci_policy.py`: PASS;
  `test_check_ci_policy`: OK (68 tests).
- `example_config.yml`: the statement that no component settings are defined is replaced by
  `components.inference_broker`, commented out as the template's other defaults are, with the
  shipped values: no `control_port` or `inference_port` (no default; the broker does not serve
  without them), `max_request_bytes` 33554432, `max_ttl_s` 86400, `upstream_timeout_s` 600,
  `families: {}` (no provider, no upstream, no model); no secret, no host name. A new test
  (`test_config.TestDecision0009Loader.test_the_example_configuration_shows_the_shipped_defaults`)
  checks that the template sets nothing and that its commented lines, uncommented as the template
  says, pass the decision 0009 loader and load to exactly `load_config(None)`. The paths suite's
  template tests (the commented-default lines, no secret-shaped key, no drive path, the copy
  resolving to the defaults): OK.

## 7. Budgets (`e00fb06`)

Re-proposed from a three-run profile of `a71707c` (clean tree, `cleanmgr` absent before and
after): serial runs 146.5, 144.0, 143.1 s, **median 144.0 s**; store 11.39, 11.73, 11.48 s;
inference 1.99, 1.74, 1.73 s. Counters follow the profile; walls only fall:

- **New:** `suites.inference`: 93 tests, 0 launches, 33 mkdtemp, wall 1.8 s (limit 2.34 s). The
  slice 1 builder's prepared row (92 tests, 1.8 s) re-derived: one more test (`a71707c`).
- **Fell:** store 15.1 → **11.5 s** (limit 19.63 → 14.95 s), set from the new measurement.
- **Kept** (each proposal at or above it): every other suite, the total (134.2 s) and every
  category. None rose.
- **Counters:** tests 2,171 → 2,264 (unit 1,328 → 1,399, integration 492 → 514) and mkdtemp
  1,010 → 1,043 (unit 498 → 525, integration 430 → 436): all from the inference suite and its new
  test. Launches unchanged (1,160).
- The baseline (`evidence/test-profile/baseline.json`) is that profile's compact form; its
  `measured` field (`2026-11-11`) is the profiler's own date stamp. `check --profile` of the
  profile against the new budgets: PASS; `test_check_test_budget` (17 tests, among them
  `CommittedBudgetTests`): OK.

`check_test_budget.py check --run` at `e00fb06` (clean tree, `cleanmgr` absent before and after,
an empty data root, still empty after): **PASS**, no failure and no note (every counter equal to
its budget). Serial runs 141.1, 142.0, 147.7 s, **median 142.0 s** (at or under 150 s); store
11.61 s (limit 14.95 s), inference 1.74 s (limit 2.34 s); every scope under its limit (the
closest: finding F-1).

## 8. Checks

At `e00fb06` unless noted, with `AIEH_DATA_ROOT`, `TEMP` and `TMP` set to new, empty scratch
directories (the data root still empty after each):

- `python -I tools/verify_seed.py`: PASS (167 tasks, 177 seeded files, 3 changed since seed).
- The store suite: 84 tests, OK; `test_profile.py compare` against the before profile
  (`ab-before-1`, `40150ce`): **identical ids and outcomes**.
- The inference suite: 93 tests, OK; `compare`: the only difference is the added
  `test_the_example_configuration_shows_the_shipped_defaults` (absent before, ok now).
- The paths suite: 38 tests, OK; the tools suite: 1,210 tests, OK (skipped=6); `compare` of both
  against the before profile: **identical ids and outcomes**.
- `tools/test_profile.py categories` (tools interpreter): PASS.
- `tools/check_ci_policy.py`: PASS; `test_check_ci_policy`: OK (68 tests).
- `test_check_test_budget` (with `CommittedBudgetTests`): OK (17 tests); `check --profile` of the
  new baseline against the new budgets: PASS.
- `check_test_budget.py check --run`: PASS (section 7).
- Mutation checks: 9 of 9 and 5 of 5 killed (section 5).
- Publication gate: pre-commit PASS on each commit; `history origin/main..HEAD` PASS (the slice 1
  commits and these).
- A search of these commits' diffs and messages for personal paths and user names (the user and
  machine names, drive and home paths, the temporary and scratch directories): none.

## 9. Findings

- **F-1, observation: two scopes stand close to their limits on today's host.** Under the rule
  that walls only fall, the repository suite (wall 5.9 s, limit 7.67 s) measured 7.21 s in the
  budget check and the contract category (wall 17.0 s, limit 22.1 s) 20.1 s; neither changed in
  this slice. The total's wall (134.2 s, limit 174.5 s) is not the binding constraint: the
  Owner's 150 s ceiling is, with 8.0 s of room at the budget check's median.
- **F-2, unrelated but detected, not changed:** an ignored `integrations/store/tests/__pycache__/`
  (one `test_reservation_crash_concurrency.cpython-312.pyc`, dated 2026-11-07) sits in the
  checkout; every run of this slice used `-B` and `PYTHONDONTWRITEBYTECODE=1` and wrote none.
- **F-3, observation:** `evidence/S-03.2-slice1-broker-core.md` notes that `example_config.yml`
  still said no component settings were defined; `a71707c` resolves that statement. That record
  was not edited.
- **Remaining structural costs** (unchanged, each previously ruled on or product cost): the
  real-scanner and fail-closed gate tests (about 25 s), the netprobe listener (6.8 s), the network
  matrix and containment fuzz (8.3 s), the verifier (6.0 s), the batch launcher's ceilings
  (3.4 s), the store's racing workers (`ConcurrencyTests`, 2.5 s: the race itself).

## 10. Not verified

- pytest (`--aieh-conformance`, serial or xdist) was not run in this slice; the changed module
  uses only `subTest`, `addCleanup` and plain `subprocess`, as before.
- POSIX hosts (the workers and the waves are plain `subprocess`; ran only on Windows); PowerShell
  timings; the CI workflow itself (the validation job is not run here).
