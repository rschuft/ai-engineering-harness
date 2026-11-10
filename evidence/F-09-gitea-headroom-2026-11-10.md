# F-09 gitea headroom: the gitea suite under its wall

Builder evidence of 2026-11-10 for the Overseer's bounded test-runtime slice under the Owner's
scheduling priority of 2026-11-08 (a serial suite of at most 150 s, equivalent results across the
serial and parallel runners, every required security and contract test still enforced, no
reduction in meaningful coverage, measured before and after, no redesign of the testing
architecture). F-09 patterns only, no new leaf. The verdict is the Overseer's.

- **Goal of the dispatch:** the gitea suite (`integrations/gitea/tests`) back under its wall with
  margin: `test:budget` medians of 3.2-3.36 s against its budget of 2.5 s (limit 3.25 s) over five
  recent runs, with no gitea change since that budget was set. Walls only fall: the gitea wall is
  not raised. Test code and fixtures only.
- **Reached:** gitea **3.284 → 2.333 s** (interleaved medians, section 1); `test:budget` at the
  change: gitea median **2.358 s**, the wall lowered **2.5 → 2.4 s** (limit 3.12 s, 0.76 s above
  the median). Serial total 142.6 s.
- **Commits** (on `a3efe58`): `c9a2db4` (the gitea tests), `86ac0b6` (budgets and baseline
  re-proposed at `c9a2db4`), then this record. `integrations/gitea/tests/test_gitea_host.py`, the
  two budget files and this record only; no product file, no integrity-tracked file, nothing under
  `decisions/`.
- **Host:** Windows 11 x86_64, 32 logical processors, CPython 3.12.10 under the `python-tools`
  interpreter, Git for Windows 2.52.0. Every measurement ran from Git Bash with the default TEMP,
  `PYTHONDONTWRITEBYTECODE=1` and `AIEH_DATA_ROOT` set to a new, empty scratch directory (still
  empty after every run). Windows Disk Cleanup (`cleanmgr`) was absent before and after each timed
  set. `task` is not installed: each target ran as the command it wraps.
- **Raw material** (not committed): `<session scratch>/c53`: the profiles (`prof-before-1.json`,
  `prof-work-1.json`, `ab-{before,after}-{1,2,3}.json`, `budget-profile.json`), the run logs, the
  in-process probes (`probe/rootcost.py`, `probe/phases.py`, `probe/supcost.py`,
  `probe/killlatency.py` and their outputs), the mutation runners and their output
  (`probe/mutate.py`, `probe/mutate2.py`, `probe/mutate.out`, `probe/mutate2.out`) and the check
  logs (`chk-*.log`, `budget.log`).

## 1. Before and after

Before: `a3efe58`. After: `c9a2db4` (`86ac0b6` only re-proposes the budgets). Single-suite profiles
(`tools/test_profile.py run --suite gitea`), interleaved in the checkout (before, after, three
times; `git checkout --detach a3efe58` and back).

| Set | Revision | Runs (s) | Median (s) |
|---|---|---|---|
| Overseer, `test:budget` (five recent runs) | before | | 3.2-3.36 |
| First profile | `a3efe58` | 3.235 | |
| **Before, interleaved** | `a3efe58` | 3.314, 3.284, 3.257 | **3.284** |
| **After, interleaved** | `c9a2db4` | 2.328, 2.333, 2.343 | **2.333** |
| `test:budget` (PASS) | `c9a2db4` | 2.316, 2.358, 2.428 | **2.358** |

Per class (medians of the interleaved runs; every other class moved by less than 0.01 s):

| Class | Tests | Before (s) | After (s) | Change (s) | Launches | mkdtemp |
|---|---|---|---|---|---|---|
| `test_gitea_host.TestJobObject` | 4 | 1.557 | 1.196 | **−0.361** | 3 → 3 | 3 → 1 |
| `test_gitea_host.TestFinalizeCredentials` | 21 | 0.514 | 0.171 | **−0.343** | 0 | 21 → 0 |
| `test_gitea_host.TestIdentities` | 5 | 0.105 | 0.026 | −0.079 | 0 | 5 → 0 |
| `test_gitea_host.TestAcquire` | 3 | 0.078 | 0.016 | −0.062 | 0 | 3 → 0 |
| `test_gitea_host.TestLayout` | 5 | 0.067 | 0.021 | −0.046 | 0 | 5 → 0 |
| `test_gitea_host.TestAppIni` | 5 | 0.094 | 0.050 | −0.044 | 0 | 5 → 0 |
| `test_gitea_host.TestVerifyCheckoutScan` | 2 | 0.059 | 0.016 | −0.043 | 0 | 2 → 0 |
| `test_gitea_host.TestVerifiedBinary` | 4 | 0.067 | 0.033 | −0.034 | 0 | 4 → 0 |
| `test_gitea_host` (module fixture) | | 0.000 | 0.080 | +0.080 | 0 | 0 → 2 |
| `test_gitea_host.TestCheckoutFiles` | 4 | 0.216 | 0.217 | +0.001 | 1 | 2 |
| `test_lifecycle.TestOperations` | 8 | 0.117 | 0.111 | −0.006 | 0 | 0 |
| **suite** | **132** | **3.284** | **2.333** | **−0.951 (−29%)** | **4 → 4** | **62 → 17** |

Per test in `TestJobObject` (medians): `test_clean_exit_...` 0.181 → 0.011 s, `test_hard_kill_...`
0.169 → 0.001 s, `test_control_without_the_job_...` 1.164 → 1.008 s; the class fixture now holds
the three overlapping launches (about 0.18 s, the cost of one).

## 2. Where the time went (profile first)

The first profile at `a3efe58` (3.235 s), then an in-process split of each class into `setUp`,
test body and cleanups (`phases.py`), and timings of the fixture's pieces (`rootcost.py`) and of a
supervisor launch (`supcost.py`):

| Cost | Wall (s) | Cause |
|---|---|---|
| `TestJobObject.test_control_without_the_job_the_child_survives` | 1.17 | **`child.wait(1.0)`: a fixed 1.0 s wait whose expiry is the expected outcome** (finding F-1), plus its supervisor launch. |
| `TestJobObject`, the other two process tests | 0.35 | One supervisor launch each, in series: Python start (about 22 ms) and the in-child load of `gitea_host.py` with its imports (about 125 ms; 171 modules, the checkout modules compiled from source under `-B`). The real Job Object and real processes are the subject. |
| `Root` setUp, 45 tests in seven classes | 0.62 | A fresh managed root per test: `mkdtemp` 0.2 ms, `paths.resolve` 3.3 ms, `layout` 0.5 ms, `paths.init` 1.4 ms, `ensure_dirs` 5.0 ms, and its removal 1.5 ms (about 12 ms); TestIdentities, TestFinalizeCredentials and TestVerifyCheckoutScan also acquire the fake asset and write app.ini in every setUp (about 4 ms more). |
| The same classes' test bodies | (0.08) | Part of the bodies' cost was Windows' first read of the files each new root had just written (TestFinalizeCredentials' bodies fell from 142 to 61 ms with no body changed; F-2 of the contract headroom record). |
| `TestCheckoutFiles` | 0.22 | The listing of this checkout and git's own listing (the oracle, the subject), and the repository corpus' ignore-rule subset, extracted once per process (already shared). |
| `test_lifecycle.TestOperations` | 0.12 | The lifecycle operations themselves (SQLite backup and restore, staging), on the module's already shared root. |
| discovery and imports | 0.15 | Loading the product modules once per process. |

No test sleeps (the suite's one `time.sleep` is the supervised child's, which the tests end). Every
other wait or `timeout` in it is a ceiling on a fake, on git or on a process's end, never waited
out on a passing run.

## 3. The changes, and why every assertion is preserved

| # | Change | Saving (s) | Counters |
|---|---|---|---|
| 1 | **One shared managed root per starting state.** `setUpModule` builds two, each once, in a temporary directory of its own, with the same calls the per-test fixture made: `initialized` (`make_root`: `paths.resolve` through `AIEH_DATA_ROOT`, `paths.init`, `ensure_dirs`) and `configured` (also the fake asset acquired and app.ini written, as TestIdentities, TestFinalizeCredentials and TestVerifyCheckoutScan began each test). Each records `tree_state`: every directory and file below the temporary directory with its permission bits, and each file's bytes. `Root.setUp` (its class's `START`) **restores** that directory (`restore`: what a test added is removed, children first; every directory or file it changed or removed is written back, parents first, with its bytes and permission bits), then **asserts** `tree_state` equal to the recorded state and the shared resolution equal to a deep copy taken at build time, and computes the layout afresh. `TestLive` (the opt-in live Gitea) keeps a fresh root of its own. | **0.65** (the seven `Root` classes 0.984 → 0.333) | mkdtemp −45 (the per-test roots; +2 module roots) |
| 2 | **`TestJobObject`'s three supervisors start together** in `setUpClass` (one supervisor script, three `Popen`s, then each one's child pid read), so the launches overlap; each test acts on the supervisor of its own (`MODES` maps each test to its mode), `start()` now also asserts that mode, and class cleanups end whatever outlives its test (in the old per-test cleanup order). | **0.36** (1.557 → 1.196) | mkdtemp −2; launches unchanged (3) |

Why nothing a test proves changed:

- **What every `Root` test starts from** is the tree a fresh root built the same way gives: the
  same directories and files with the same bytes and permission bits, and the same resolution,
  asserted in `setUp` before every test, so a test that leaves anything behind makes the next
  test's `setUp` fail rather than pass silently. Paths a test names are below the shared
  directory instead of a new one; no assertion reads a directory's name, and every path an
  assertion compares is derived from `self.tmp`, `self.res` or `self.lay`, as before. Timestamps
  inside the recorded files (the root marker's, the asset record's) are those of the build, not of
  the test; no assertion reads them. The product modules keep no path-keyed cache (`_ADAPTER` is
  the platform adapter, `ACT_GUARD` is reset by `main`), so a test cannot read state an earlier
  test produced except through the tree, which is restored and checked.
- **The `configured` start** replaces two setUp calls (`acquire_fake`, `configure` with the fake
  CLI) by their recorded result; those calls were fixture steps, never asserted in those classes.
  `TestAppIni`, `TestAcquire` and `TestVerifiedBinary`, which assert acquire and configure, still
  call them in their tests on the `initialized` start.
- **`TestJobObject`:** every test still runs its own supervisor (with the job or without it) and
  its own child, both real processes and the real Job Object; the assertions are unchanged, and the
  control's survival window is still 1.0 s. The supervisors are started earlier, together; none
  of them is acted on before its test.
- No assertion was removed, weakened or reworded. Two were added: the restore check (and the
  resolution check) in `Root.setUp`, and the mode check in `TestJobObject.start`.

## 4. Equivalence

- **Test ids and outcomes:** the before and after profiles have the same 138 rows (132 tests and 6
  class-fixture rows) with the same outcome each: ok 130, skip 8, the same eight skips
  (the opt-in live suites' six fixtures, `TestExecutor`'s live test and `TestLive`); the same
  outcomes digest. The whole suite under unittest: 132 tests, OK (skipped=8), before and after.
- **Counters moved only as explained:** gitea mkdtemp 62 → 17 (unit 56 → 13: the 45 per-test roots
  of the seven `Root` classes less the two module roots; integration 5 → 3: `TestJobObject`'s two
  further script directories); launches 4, sockets 3 and chdir 0 unchanged.

## 5. Mutation checks

In a throwaway clone of `a3efe58` with `c9a2db4`'s test file copied in (never committed): each
mutation applied alone, the targeted tests run under the tools interpreter with an empty
`AIEH_DATA_ROOT`, the files restored after each. M0: `test_gitea_host` unmutated, 74 tests OK
(skipped=1).

| Id | Mutation | Targeted tests | Result |
|---|---|---|---|
| P1 | product: `ensure_dirs` reports every directory, not only the new ones | `TestLayout` | killed (`test_ensure_dirs_reports_only_new_directories`) |
| P2 | product: `acquire` reports a reused asset as acquired again | `TestAcquire` | killed (`test_download_verified_then_recorded`) |
| P3 | product: `finalize_credentials` reports nothing found in the managed root | `TestFinalizeCredentials` (configured start) | killed (1 failure) |
| P4 | product: the job is created without `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` | `TestJobObject` | killed (1 failure) |
| F1 | `restore` keeps what a test added | `test_gitea_host` | killed (43 failures) |
| F4 | `Root.setUp` neither restores nor checks the shared root | `test_gitea_host` | killed (5 failures, 22 errors) |
| F5 | F1, and `setUp` does not check | `test_gitea_host` | killed (5 failures, 22 errors) |
| J1 | the control's supervisor started with the job | `TestJobObject` | killed (`start()`'s mode check) |
| J2 | J1 without `start()`'s mode check | `TestJobObject` | killed (the control's own assertion) |
| F2 | `restore` writes nothing back | `test_gitea_host` | survived: no test of the module changes or removes an entry of a starting state; with a scratch class that does (X1, below), killed |
| F3 | `restore` writes a file's bytes but not its permission bits | `test_gitea_host` and X3 | survived, equivalent: neither starting state holds a read-only entry (modes 0o777 directories, 0o666 and 0o777 files), and a rewritten file is left writable, its recorded mode |

The write-back path, with a scratch class (`TestZzRestoreProbe`, `configured` start: its first
test overwrites app.ini, makes the host record read-only, removes the logs directory and the
acquire source; its second asserts them back): **X0** unmutated, OK; **X1** `restore` writes
nothing back, killed (the `setUp` check); **X2** `restore` recreates no directory, killed; **X4**
`restore` skips a file whose bytes are equal but whose mode differs, killed (the `setUp` check,
mode 0o444 against 0o666).

## 6. Budgets (`86ac0b6`) and checks

`test:budget` (`check_test_budget.py check --run`) at `c9a2db4`, once, `cleanmgr` absent before
and after: **PASS**, serial runs 142.6, 143.6, 141.0 s, **median 142.6 s** (at or under 150 s);
gitea 2.316, 2.358, 2.428 s, **median 2.358 s**. Its temporary directory was removed afterwards
(matched to its own log).

Budgets re-proposed from that profile: counters follow it, and each wall is the lower of the
committed and the proposed value. **Fell:** gitea 2.5 → 2.4 s (limit 3.25 → 3.12 s). Every other
wall kept (each proposal at or above it); none rose. Counters: mkdtemp gitea 62 → 17 (total
1054 → 1009, unit 540 → 497, integration 432 → 430), from this change; tests total 2117 → 2142
(tools 1188 → 1210, repository 103 → 106, unit 1285 → 1307, contract 328 → 331), from the tests
added since the previous baseline `538847a` (`7970bf7`, `3e12723`, `3cf45cd`; finding F-3);
launches unchanged (1,160). `check --profile` of the new compact baseline against the new
budgets: PASS; `test_check_test_budget.CommittedBudgetTests`: OK (4 tests).

Checks:

- `python -I tools/verify_seed.py`: PASS (167 tasks, 177 seeded files, 3 changed since seed), at
  the test change (no integrity-tracked file changed afterwards).
- The gitea suite under the tools interpreter with `PYTHONDONTWRITEBYTECODE=1` and an empty
  `AIEH_DATA_ROOT`: 132 tests, OK (skipped=8), the same tests and skips as before.
- `test:categories` under the tools interpreter: PASS (381 classes in 64 modules).
- The launch census (`tools/tests/test_launch_census.py`): OK (12 tests); `test_gitea_host`'s one
  git site is unchanged.
- Publication gate: pre-commit PASS on each commit; `history origin/main..HEAD` PASS (section 8).

## 7. Findings

- **F-1, `exposed-by-F-09-gitea-headroom` (its profiling), carried, not repaired:**
  `TestJobObject.test_control_without_the_job_the_child_survives` waits a fixed 1.0 s
  (`child.wait(1.0)`) and passes when the wait expires: a guessed duration, not a completion
  signal, and now 1.0 of the suite's 2.33 s. Measured (`killlatency.py`, five runs): with the job,
  the child is seen ended 0.8-2.1 ms after `TerminateProcess` of its supervisor (the supervisor
  itself ended after 0.7-1.7 ms); without it, the child was still alive after 3.0 s in both
  control runs. Any repair changes the window that test proves (the dispatch's stop rule), so the
  choice is the Overseer's: (a) a shorter fixed window (weakens the control); (b) an
  event-anchored control: kill a with-job and a without-job supervisor together and assert the
  control child alive once the with-job child is seen ended (and, if wanted, after a margin
  derived from that latency) (one more launch, a different window); (c) keep it. Saving about
  0.9-1.0 s.
- **F-2, observation:** the shared roots' files are scanned once at build time instead of once per
  test (Windows' first read of newly written files, F-2 of the contract headroom record): part of
  the bodies' saving in section 1 comes from that, not from `setUp`.
- **F-3, observation:** the committed budget's test counters lagged the tree by 25 tests added in
  three commits since `538847a`; `check --run` reported them as `TESTS_ABOVE` notes (passing), and
  the re-proposal brings them to the tree.

## 8. Not verified

- pytest (`--aieh-conformance`, serial or xdist) was not run in this slice; the module fixture
  follows `test_lifecycle`'s, which runs under it, and `addClassCleanup` is already used in this
  suite.
- `TestLive` (opt-in, a copy of the pinned Gitea): not run; it keeps its own fresh root.
- POSIX hosts (the restore records and restores POSIX permission bits, the product's 0o700
  directories there among them, but ran only on Windows); PowerShell timings.
