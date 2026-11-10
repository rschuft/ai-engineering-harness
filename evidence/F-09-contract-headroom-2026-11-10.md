# F-09 contract headroom: the contract category after Q-02.1

Builder evidence of 2026-11-10 for the Overseer's bounded test-runtime slice under the Owner's
scheduling priority of 2026-11-08 (a serial suite of at most 150 s, equivalent results across the
serial and parallel runners, every required security and contract test still enforced, no
reduction in meaningful coverage, no redesign of the testing architecture). The verdict is the
Overseer's.

- **Goal of the dispatch:** the `contract` category's median at or below about 19.5 s on a quiet
  host (at least 2.5 s under its 22.1 s limit, budget 17.0 s), from the Overseer's 22.0 s and
  22.4 s at `867381b`; also a serial median at or below about 138 s. Then the carried defect:
  `task test:categories` must pass.
- **Reached:** contract **21.58 → 18.59 s** (interleaved medians, section 1), 3.5 s under its
  limit. Serial total **142.2 → 139.2 s**: the 138 s aim is not reached; the remaining costs and
  their options are in section 8. `test:categories`: **PASS** (section 6).
- **Commits** (on `867381b`): `16dbb89` (the verifier tests' work copy), `8386ebf`
  (`test:categories` under the tools interpreter), `5f1b60d` (budgets and baseline re-proposed at
  `8386ebf`), then this record. Test code, `Taskfile.yml`'s `test:categories` target, that
  target's row in `docs/development.md`, the budget files and this record only; no product file,
  no integrity-tracked file, nothing under `decisions/`.
- **Host:** Windows 11 x86_64, 32 logical processors, CPython 3.12.10 under the `python-tools`
  interpreter (the dev venv for pytest), Git for Windows 2.52.0. Every measurement ran from Git
  Bash with the default TEMP and `AIEH_DATA_ROOT` set to a new, empty scratch directory. Windows
  Disk Cleanup (`cleanmgr`) was checked before and after each timed run; one run it overlapped was
  discarded (finding F-3). `task` is not installed: each target ran as the command it wraps.
- **Raw material** (not committed): `<session scratch>/c39`: the profiles (`prof-before-1.json`,
  `ab-before-{1,2,3}.json`, `ab-after-{1,2,3}.json`, `budget-profile.json`), the run logs, the
  cost probes (`copycost.py`, `verifycost.py`), the mutation runner and its output (`mutate.py`,
  `mutate.out`), the pytest outcome files (`conf/`) and the check logs (`checks.log`, `chk-*.log`).

## 1. Before and after

Before: `867381b`. After: `8386ebf` (the changes; `5f1b60d` only re-proposes the budgets). All
runs serial, `tools/test_profile.py` (directly or through `check_test_budget.py check --run`).
The before and after runs were interleaved in the checkout (after, before, three times;
`git checkout --detach 867381b` and back), `cleanmgr` absent before and after each.

| Set | Revision | Runs (s) | Median (s) | Contract median (s) |
|---|---|---|---|---|
| Overseer, quiet host | `867381b` | 145.2, 147.3 | | 22.0, 22.4 |
| First profile (per-test rows) | `867381b` | 143.5 | | 22.0 |
| **Before, interleaved** | `867381b` | 142.28, 142.19, 142.22 | **142.2** | **21.58** |
| **After, interleaved** | `8386ebf` | 139.19, 139.10, 139.37 | **139.2** | **18.59** |
| Three-run profile for the re-proposal | `8386ebf` | 139.09, 139.76, 143.88 | 139.8 | 18.76 |
| `test:budget` (PASS) | `5f1b60d` | 147.16, 144.01, 142.10 | 144.0 | 19.57 |
| `test:budget` again (PASS) | `5f1b60d` | 139.32, 142.91, 140.21 | 140.2 | 18.80 |
| (discarded: `cleanmgr` ran throughout) | `8386ebf` | 174.9 | | (24.5) |

The first `test:budget` set ran on a host drifting by about 3% in every suite (tools 74.8 s
against the interleaved 71.7 s, its runs falling from 147.2 to 142.1 s); the interleaved sets are
the fair before and after. The second `test:budget` set, later and quieter, gave 140.2 s and a
contract median of 18.80 s (its runs 18.57, 19.10, 18.80).

Per suite and category (medians of the interleaved sets):

| Scope | Before (s) | After (s) | Change (s) |
|---|---|---|---|
| tools | 74.67 | 71.71 | **−2.96** |
| store | 18.31 | 18.35 | +0.04 |
| effects | 2.66 | 2.68 | +0.02 |
| planning | 11.86 | 11.80 | −0.06 |
| lineage | 14.16 | 14.04 | −0.12 |
| owner | 2.34 | 2.32 | −0.02 |
| paths | 1.44 | 1.40 | −0.04 |
| platform | 0.25 | 0.24 | −0.01 |
| credentials | 0.85 | 0.85 | 0.00 |
| gitea | 3.23 | 3.22 | −0.01 |
| dispatch | 5.93 | 6.00 | +0.07 |
| repository | 6.56 | 6.55 | −0.01 |
| **total** | **142.22** | **139.19** | **−3.03 (−2.1%)** |
| category unit | 24.97 | 24.90 | −0.07 |
| **category contract** | **21.58** | **18.59** | **−2.99 (limit 22.10)** |
| category integration | 91.13 | 91.14 | +0.01 |
| category performance | 0.77 | 0.74 | −0.03 |

The two changed classes account for the change (class medians, interleaved): `DefaultMode`
5.14 → 2.66 s, `BaselineMode` 3.38 → 3.03 s; no other class moved by more than 0.08 s.

## 2. Where the contract time went (profile first)

The first profile at `867381b` (contract 22.0 s, 61 classes), ranked by class wall:

| Class | Wall (s) | Launches | What it is |
|---|---|---|---|
| `test_verify_seed.DefaultMode` | 5.25 | 5 | 13 tests; 11 write, each into a private copy of the seeded files |
| `test_verify_seed.BaselineMode` | 3.44 | 27 | 5 tests, each in a private copy of a golden git repository of the seeded files |
| `test_resolvers.RegistryAndCommandLine` | 1.58 | 12 | the lineage command line, launched (the subject) |
| `test_planning_adapter.CommandLine` | 1.24 | 19 | the planning command line, launched (the subject) |
| `test_launch_census.TreeCensus` | 1.11 | 0 | the AST census of every tracked source (parsed once, already memoized) |
| `test_backup_restore.ManifestCheckTests` | 0.87 | 5 | the store command line's backup and restore round trip |
| `test_trace.CommandLine` | 0.70 | 9 | the trace command line |
| `test_readiness.Stages` | 0.66 | 10 | the readiness command line's exit codes |
| `test_dispatch_inputs.CliTests` | 0.64 | 4 | the dispatch-inputs command line |
| the other 52 classes | 6.5 | | each under 0.45 s |

Each writing `DefaultMode` test cost about 0.33 s with a single verifier call, and each further
call about 0.05 s. Timed in scratch (`verifycost.py`, `copycost.py`): copying the seeded files
(176 files, 5.8 MB) takes 0.07 s and removing the copy 0.02 s, but the verifier's **first** read
of a freshly written copy takes 0.23-0.25 s against 0.03 s for the second read of the same copy:
Windows scans each newly written file when it is first opened. A per-test private copy paid that
first read in every writing test; it was the larger part of the class.

The command-line classes launch the real command (the contract under test), and the census is
already parsed once per process: their costs are their subjects.

## 3. The change, ranked by saving

| # | Change | Commit | Saving (s) | Counters |
|---|---|---|---|---|
| 1 | `test_verify_seed`: each class makes one **work copy** of its source (the seeded copy, or `BaselineMode`'s golden repository) and **restores** it before each writing test: what the previous test added is removed (files and directories; git's read-only objects made writable first), every file it changed or removed is copied back from the source with plain file copies, removed directories are recreated, and the whole work copy is then **checked equal to the source** (every file's sha256 and every directory, `tree_state`) before the test runs. Only the differences are written, so later tests read files already scanned. The read-only tests, their shared copy and its unchanged-copy check are as before. | `16dbb89` | **2.84** (DefaultMode 5.14 → 2.66, BaselineMode 3.38 → 3.03); contract −2.99, total −3.03 | mkdtemp −16 (the 11 + 5 private copies); launches unchanged |
| 2 | `test:categories` under the tools interpreter (section 6) | `8386ebf` | 0 | none |

Per test (interleaved medians): nine `DefaultMode` writing tests fell from 0.32-0.39 s to
0.07-0.15 s and the tenth, with 16 verifier calls, from 1.03 to 0.79 s; the first writing test of
each class pays the work copy and its first read once (`DefaultMode.test_authority_edit_...`
0.37 → 0.39 s, `BaselineMode.test_baseline_checks_task_manifest_consistency` 0.49 → 0.69 s). `BaselineMode` saves less because each of its tests commits through git and
launches the verifier, which the change leaves as they were.

What every writing test now starts from is the same tree a fresh copy gave: the same files with
the same bytes and the same directories, asserted in `setUp`. Its path is the class's work copy
instead of a new temporary directory; no test reads its own path's name, and the one test that
uses the copy's parent (`GIT_CEILING_DIRECTORIES`) gets the work copy's own parent.

## 4. Equivalence

- **Test ids and outcomes (unittest):** the first `867381b` profile and every `8386ebf` profile
  have the same outcome for each of the 2,075 ids (ok 2,046, skip 29) and the same outcomes digest;
  tests 2,069, launches 1,160, sockets 103 and chdir 3 in every run, before and after.
- **pytest, the whole collection with `--aieh-conformance`** against a stdlib profile written
  under the dev interpreter at `8386ebf`: **CONFORMANCE PASS** serially (`-n 0`) and under xdist
  (`-n auto --maxprocesses 8 --dist loadscope`, 8 workers): 2,075 ids, 2,069 tests run, 2,050
  passed, 38 skipped, 7,057 subtests passed, in 181.6 s and 39.9 s. **`-m "not e2e"`:** 2,050 passed,
  2 skipped, serially and under xdist, with identical ids and outcomes (2,052 rows; the outcome
  files' `tests` and `suites` equal).
- **An empty `AIEH_DATA_ROOT`** (new scratch directories): every profile run, the pytest runs and
  all twelve suites ran with it; each directory was still empty afterwards (section 7).
- **Counters moved only as explained:** mkdtemp 1,068 → 1,052 (the 16 private copies, contract
  97 → 81, tools 552 → 536). Nothing else.

## 5. Mutation checks

In a throwaway clone of `8386ebf` (never committed): each mutation applied alone, the targeted
tests run, the file restored; the unmutated targets pass (M0). Every mutation is killed.

| Id | Mutation | Targeted tests | Result |
|---|---|---|---|
| M0 | none | `test_verify_seed` | OK (19 tests) |
| M1 | `restore` keeps the files a test added | `test_verify_seed` | killed (10 failures) |
| M2 | `restore` copies no file back | `test_verify_seed` | killed (14 failures) |
| M3 | `restore` keeps the directories a test added | `BaselineMode` | killed (4 failures) |
| M4 | `restore` recreates no removed directory | `BaselineMode` | killed (2 errors) |
| M5 | `restore` copies back only removed files, not changed ones | `test_verify_seed` | killed (14 failures) |
| M6 | a writing test gets the source itself, not the work copy | `test_verify_seed` | killed (23 failures, 2 errors) |
| M7 | no restore and no equality check between writing tests | `test_verify_seed` | killed (8 failures, 2 errors) |
| M8 | `tree_state` ignores directories | `BaselineMode` | killed (2 errors) |
| T1 | `test:categories` without the tools interpreter variables | `test_pytest_conftest.RequiredTargets` | killed (1 error) |

## 6. `test:categories` (carried finding F-1 of the previous slice)

`task test:categories` ran `python -I -B tools/test_profile.py categories` under the plain
interpreter, which imports every test module; `integrations/credentials/tests/test_credential_provider.py`
imports `keyring`, which only the Python tools set has: **FAIL** (`ModuleNotFoundError: No module
named 'keyring'`, observed again at `8386ebf` under the plain interpreter). The target now
resolves `<tools python>` with the same `vars` as `test:profile` and `test:budget`; its
description and its row in `docs/development.md` name that interpreter and `tools:install`.
`RequiredTargets.test_the_profile_and_budget_targets_run_under_the_tools_interpreter` now checks
it too (a subtest; mutation T1). Result under the tools interpreter: **PASS** (352 classes in 60
modules: unit 187, contract 61, integration 88, e2e 15, performance 1). The credential code is
unchanged.

## 7. Budgets (`5f1b60d`) and checks

Budgets from the `8386ebf` three-run profile. Counters follow it (mkdtemp 1,052; tools 536;
contract 81; tests 2,069 and launches 1,160 unchanged). Walls only fall, each the lower of the
committed and the proposed value: **fell:** tools 73.0 → 72.0. Kept: every other wall, the
contract's 17.0 (limit 22.1) and the total's 134.2 among them. `check --profile` of that profile
against the new budgets: PASS; the committed baseline passes them (`CommittedBudgetTests` OK).
Headroom on the interleaved after: contract 18.59 of 22.10 s (3.5 s), gitea 3.22 of 3.25 s
(unchanged, the tightest scope), tools 71.7 of 93.6 s.

Checks at `5f1b60d`:

- `python -I tools/verify_seed.py`: PASS (165 tasks, 175 seeded files, 3 ordinary changed since
  seed); `--baseline seed`: PASS (136 tasks, 146 intact seeded files, all strict).
- The twelve suites under the tools interpreter with `PYTHONDONTWRITEBYTECODE=1` and an empty
  `AIEH_DATA_ROOT`: all OK (tools 1,188 tests, 6 skipped; store 84; effects 34; planning 104, 7
  skipped; lineage 146, 6 skipped; owner 38, 1 skipped; paths 38; platform 38; credentials 51, 1
  skipped; gitea 132, 8 skipped; dispatch 113; repository 103). The data root was still empty
  afterwards, and after every profile, pytest and mutation run.
- pytest: section 4 (at `8386ebf`; `5f1b60d` changes no test code).
- `hooks:verify` as its commands: `publication_gate.py verify`: PASS; the gate's 27 tests with
  `AIEH_GATE_REQUIRE_SCANNER=1` (the nested whole tool-suite rerun included): OK, 95.5 s.
- `test:categories` under the tools interpreter: PASS.
- `test:budget` (`check_test_budget.py check --run`), `cleanmgr` absent before and after: PASS
  twice (section 1). Its temporary directories, and those of this slice's profile runs, were
  removed afterwards, each matched to its own run log.

## 8. What remains

The serial median is 139.2 s, about 1.2 s above the 138 s aim. The remaining large costs, with
what each would need:

| Cost | Wall (s) | Why it stays, and the option |
|---|---|---|
| `test_publication_gate.WithRealScanner` | 15.2 | Real hooks and the pinned Gitleaks (the subject). One allowlist golden pair for all three configurations: about 1 s, changes the inputs of security tests (option of the previous slice, not taken). |
| `FailsClosed` | 8.4 | Real hook runs failing closed. |
| `CrashMatrixTests` | 7.9 | Real worker processes are the subject. |
| `test_guest.NetprobeListener` | 6.8 | The real listener, Windows' refusal delay, the pinned netprobe's 2.0 s wait. |
| Network matrix and containment type fuzz | 8.4 | The checkers' own evaluation. |
| `test_check_profile.Negative` | 2.5 | About 1 s (under `cProfile`) is the per-test check that the shared copy is unchanged: it hashes every file of the copy after each of 100 tests, and opening a file costs about 0.17 ms here. A cheaper check (stat data first, or once per class) would weaken or move that assertion: not taken. |
| `test_check_ci_policy` type fuzz | 1.1 | The checker's evaluation (its security-inventory path checks), not parsing. |
| `test_guest.Smoke`, `.Inventory` | 2.6 | The live checkout's status; `guest.Context(..., repo_root=)` could point them at a fixture repository (about 2 s), but they would stop inventorying the real checkout (option of the previous slice, not taken). |
| `test_verify_seed` | 5.8 | The verifier's reads and BaselineMode's git commits. Sharing one seeded copy between the two classes (once per process, as the golden repository already is) would save about 0.3 s: within F-09's patterns, not taken because it does not close the gap alone. |

The options that reach 138 s change what a test reads (Smoke and Inventory, about 2 s) or the
inputs of security tests (one allowlist golden, about 1 s): the Overseer's call.

## 9. Findings

- **F-1, unrelated but detected (carried from the previous slice), repaired:** `task
  test:categories` failed under the plain interpreter (section 6). Repaired forward in `8386ebf`.
- **F-2, observation:** on this host the first read of freshly written files costs about 35 ms
  per MB (0.2 s for the 5.8 MB seed copy), many times the copy itself. Per-test copies that are
  read whole pay it every time; restoring a work copy pays it once.
- **F-3, observation (process):** the first after-profile ran while `cleanmgr` was already running
  (the pre-check printed it, and the run was not gated on it): 174.9 s, discarded. Every later timed
  run was gated on `cleanmgr` being absent and rechecked afterwards; the wait used a background
  loop on the process list.
- **F-4, observation:** with `AIEH_DATA_ROOT` pointing at an empty directory,
  `integrations/paths/tools_install.py --python` reports the tools set as not installed (it looks
  under that root), so a Taskfile target that resolves `<tools python>` cannot run with that
  override. The interpreter was resolved once without it, and the suites ran with it.

## 10. Not verified

- PowerShell timings (its `cmd\git.exe` launcher adds a process per git command); only Git Bash
  ran here.
- POSIX hosts; the first-read cost (F-2) is a Windows measurement.
- `docs/development.md`'s wall-time history was not updated (outside this slice's paths).
