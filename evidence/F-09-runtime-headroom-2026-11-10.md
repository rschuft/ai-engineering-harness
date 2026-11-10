# F-09 runtime headroom: the serial suite after P-04.1

Builder evidence of 2026-11-10 for the Overseer's bounded test-runtime slice under the Owner's
scheduling priority of 2026-11-08 (test-suite wall-clock time: a serial suite of at most 150 s,
equivalent results across the serial and parallel runners, every required security and contract
test still enforced, no reduction in meaningful coverage, measured before and after, no redesign
of the testing architecture). The verdict is the Overseer's.

- **Goal of the dispatch:** a serial median of about 135 s or less, from the Overseer's 147.5 s
  at `6bbec70`, with F-09's own methods (fixtures built once, process boundaries injected where
  the launch is not the subject, repeated work batched or memoized). **Reached: 137.2 s**
  (section 1); the remaining cost is structural (section 6), with the options listed there.
- **Commits** (on `6bbec70`): `49e8010` (the gate tests' fixtures), `c5132f4` (guest.py compiled
  once per test process), `cb5a751` (checker fuzz copies, the verifier's golden repository),
  `98bb781` (one launch per commit in the verifier's baseline tests), `50e834a` (budgets and
  baseline re-proposed at `98bb781`), then this record. Test code, test fixtures and the budget
  files only; no product file, no integrity-tracked file, nothing under `decisions/`.
- **Host:** Windows 11 x86_64, 32 logical processors, CPython 3.12.10 under the `python-tools`
  interpreter (the dev venv for pytest), Git for Windows 2.52.0. Every measurement ran from Git
  Bash with the default TEMP; Windows Disk Cleanup (`cleanmgr`) was checked before and after
  each timed set (one set it slowed was discarded and rerun, section 1). `task` is not installed:
  each target ran as the command it wraps.
- **Raw material** (not committed): `<session scratch>/c34`: the profiles (`prof-before-1.json`,
  `budget2-profile.json`, `budget3-profile.json`, `ab-*.json`), the run logs, the in-process
  cost probes (`cprof*.py`, `compiles.py`, `launchcost.py`, `copycost.py`), the mutation runner
  (`mutate.py`, `mutate.out`) and the pytest outcome files (`conf/`).

## 1. Before and after

Before: `6bbec70`. After: `98bb781` (the changes; `50e834a` only re-proposes the budgets). All
runs serial, `tools/test_profile.py` (directly or through `check_test_budget.py check --run`).

| Set | Revision | Runs (s) | Median (s) |
|---|---|---|---|
| Overseer, quiet host | `6bbec70` | (three runs) | 147.5 |
| Before, interleaved with the after runs below | `6bbec70` | 148.8, 147.9, 147.9 | **147.9** |
| After the first three commits, interleaved | `cb5a751` | 137.4, 137.5 | 137.4 |
| `test:budget` | `cb5a751` | 137.3, 137.6, 137.5 | 137.5 |
| `test:budget` (discarded: `cleanmgr` started during run 3) | `cb5a751` | 137.7, 137.4, 151.8 | (137.7) |
| **`test:budget`, the after** | `98bb781` | 136.8, 137.3, 137.2 | **137.2** |

Per suite and category (medians; before = the three interleaved `6bbec70` runs, after = the
`98bb781` budget runs):

| Scope | Before (s) | After (s) | Change (s) |
|---|---|---|---|
| tools | 81.94 | 71.10 | **−10.84** |
| store | 18.26 | 18.33 | +0.07 |
| effects | 2.69 | 2.68 | −0.01 |
| planning | 11.93 | 11.90 | −0.03 |
| lineage | 13.89 | 13.91 | +0.02 |
| owner | 2.42 | 2.41 | −0.01 |
| paths | 1.43 | 1.43 | 0.00 |
| platform | 0.25 | 0.25 | 0.00 |
| credentials | 0.86 | 0.85 | −0.01 |
| gitea | 3.24 | 3.22 | −0.02 |
| dispatch | 4.57 | 4.57 | 0.00 |
| repository | 6.51 | 6.57 | +0.06 |
| **total** | **147.9** | **137.2** | **−10.7 (−7.2%)** |
| category unit | 24.40 | 22.29 | −2.11 |
| category contract | 21.17 | 20.82 | −0.35 (limit 21.97) |
| category integration | 96.28 | 89.51 | −6.77 |
| category performance | 0.75 | 0.75 | 0.00 |

## 2. Where the time went (profile first)

One profile at `6bbec70` (147.8 s), ranked by class wall, then explained with in-process probes:
a `cProfile` of the tools, store, lineage and planning suites, a timed `compile` census, and
launch and copy timings.

| Cost | Wall (s) | Cause |
|---|---|---|
| `test_publication_gate.WithRealScanner` | 15.6 | Real hooks running the pinned Gitleaks on each commit and push (the subject); three golden pairs for three allowlist configurations; a `git remote set-url` per repository. |
| `test_publication_gate.FailsClosed` | 13.8 | `test_6f` waited two 3 s scanner timeouts (7.2 s); each of five stub behaviours had its own pinned stub, so its own gate copy and golden pair (11 git launches each). |
| `test_reservation_crash_concurrency.CrashMatrixTests` | 7.6 | 57 real worker processes: crash, read by a fresh process, re-request in another process (the subject). |
| `test_guest.NetprobeListener` | 6.7 | The real listener process (compiling `guest.py` takes 0.5 s per launch), Windows' loopback refusal delay (about 1 s per refused connect) and the pinned netprobe's 2.0 s UDP no-reply wait. |
| `test_verify_seed` (two classes) | 8.4 | The integrity-tracked verifier opens every seeded file on each call; private copies per writing test; three git launches per test commit. |
| `test_check_network_matrix.Acceptance`, `test_check_containment_cases.Rules` | 9.5 | Type fuzzing: 432 and 609 deep copies of the committed documents, each evaluated by the checker. |
| tools discovery | 2.3 | `tools/guest.py` (0.7 MB) compiled five times in process (0.35 s each): the tests run with `-B` and the checkout has no `__pycache__`; `test_guest_drill` and `test_provision` also load copies of other test modules. |
| `test_guest.ApiProbe` | 3.2 | The HTTP server's shutdown waits for its 0.5 s poll; the refused-connection case waits Windows' refusal delay in the child. |
| `test_provision` | (0.5) | The seeded script's syntax tree parsed 69 times. |
| `test_guest.Smoke`, `.Inventory` | 2.3 | `repository_access` status of the live checkout, 18 times: it hashes every tracked file whose size matches (601 files). |

## 3. The changes, ranked by saving

Savings are class or discovery medians, the interleaved `6bbec70` runs against the interleaved
`cb5a751` runs (the `98bb781` row: against its budget runs).

| # | Change | Commit | Saving (s) | Launches |
|---|---|---|---|---|
| 1 | `FailsClosed.test_6f` waits the shortest timeout the gate accepts (`AIEH_GATE_TIMEOUT=1`, was 3): the stub never returns, so the outcome is the same; the test now also asserts `timed out after 1s`, so the value it sets is the one applied. The five stub behaviours share one pinned dispatcher stub that runs the behaviour written beside it in the tool cache: one stub gate copy, one golden pair instead of five. | `49e8010` | **5.48** (13.84 → 8.36) | 122 → 71 |
| 2 | `module_code.load` (new, `tools/tests/`): `spec_from_file_location` and `exec_module` with the compiled code shared per file content (path, size, modification time); every load is still a new module executed afresh. Used for the five in-process loads of `guest.py` (and the second load of `test_guest.py`). Tested by `test_module_code.py` (3 tests). | `c5132f4` | **1.40** (discovery 2.33 → 0.93) | 0 |
| 3 | `fresh()` in the containment-case and network-matrix tests parses the committed JSON text again instead of deep-copying the parsed document: an equal document sharing nothing, at about a quarter of the cost. | `cb5a751` | **1.64** (Rules 4.40 → 3.34; Acceptance 5.09 → 4.51) | 0 |
| 4 | `test_guest.ApiProbe`'s server polls for shutdown every 0.05 s (the repository transport tests' setting). | `c5132f4` | **0.90** (3.23 → 2.33) | 0 |
| 5 | The gate's golden pair: its origin is the relative URL `../origin.git` (every copy pushes to its own bare repository; the gate never reads the URL), so no `git remote set-url` per copy; initialized with an empty template (no sample hooks, `info/exclude` or `description`; `core.hooksPath` is `.githooks`). | `49e8010` | **0.47** (WithRealScanner 15.70 → 15.23; also in row 1) | 111 → 96 (and −7 in row 1) |
| 6 | `test_provision`: the seeded script's syntax tree is parsed once (`functools.cache`); its users only walk, unparse and compile nodes. | `c5132f4` | **0.47** (EgressRouteSeed 0.31 → 0.03, ConversationFactsSeed 0.20 → 0.01) | 0 |
| 7 | `test_verify_seed.BaselineMode`: the golden repository is initialized with an empty template, and `commit_all` makes one launch (`commit --all`, the new commit read from the loose ref git wrote) while no non-seeded file exists, `add --all` first otherwise. | `cb5a751`, `98bb781` | **0.28** (3.56 → 3.28) | 39 → 27 |

**Tried and reverted before any commit:** an empty init template for the planning design
repository, the owner project and the guest exchange fixture. `test_acceptance_recorder`'s
client-hook case failed (it writes into `.git/hooks`), and `repository_access` reads the hooks
directory and `info/exclude` of those repositories, so their tests would have stopped exercising
a repository with git's sample hooks: kept only where git alone reads the fixture.

## 4. Equivalence

- **Test ids and outcomes (unittest):** the `6bbec70` and `cb5a751` profiles have the same
  outcome for every one of the 1,973 ids (ok 1,944, skip 29); after, 1,976 ids: the three new
  `test_module_code.Load` tests, ok. The `98bb781` budget runs: green, counters and outcomes equal
  in all three runs.
- **pytest, the whole collection with `--aieh-conformance`** against a stdlib profile under the
  dev interpreter (`cb5a751`): PASS serially (`-n 0`) and under xdist (8 workers, `loadscope`),
  1,976 ids, 1,970 tests run; again under xdist at `98bb781`: PASS. **`-m "not e2e"`:** 1,951
  passed, 2 skipped, serially and under xdist, with identical ids and outcomes (1,953 rows).
- **An empty `AIEH_DATA_ROOT`** (a new scratch directory): all twelve suites pass under the tools
  interpreter with `PYTHONDONTWRITEBYTECODE=1`, and the directory is still empty afterwards.
- **Counters moved only as explained:** launches 1,236 → 1,158 (−78): FailsClosed −51 (four golden
  builds of 11 launches, seven `set-url`), WithRealScanner −15 (`set-url`), BaselineMode −12 (two
  of the three launches of each of six commits). mkdtemp 1,046 → 1,047: `test_module_code`'s class
  directory. Tests 1,967 → 1,970. Sockets and chdir unchanged.
- **One parse, unchanged:** after all 63 `test_provision` tests in one process the cached tree
  equals a fresh `ast.parse` of the script (`ast.dump` with attributes); 69 requests, one parse.
- **One launch per commit, same commit:** with each `commit_all` result compared to `git
  rev-parse HEAD` and the status checked clean, all 13 commits of `BaselineMode` (and of a
  scratch case adding a new file, which takes the `add --all` path) agree.

## 5. Mutation checks

In a throwaway clone of `6bbec70` with the changed files copied in (never committed): each
mutation applied alone, the targeted tests run, the file restored; each unmutated target passes.

| Id | Mutation | Targeted tests | Result |
|---|---|---|---|
| M1a | The gate treats a scanner timeout as an empty report | `test_6f` | killed |
| M1b | The gate applies `AIEH_GATE_TIMEOUT + 1` | `test_6f` | killed (`timed out after 2s`) |
| M2a | The gate ignores the scanner's exit status | `test_6c` | killed |
| M2b | The gate's "success without a report" branch never taken | `test_6d` | killed |
| M2c | Every stub repository given the same behaviour | `FailsClosed` | killed (3 failures) |
| M3 | The golden origin URL absolute again (copies push into the golden's origin) | `WithRealScanner` | killed (3 failures) |
| M4a | `module_code` cache keyed on the path alone | `test_module_code` | killed |
| M4b | `module_code.load` returns a shared module | `test_module_code` | killed |
| M5a | `fresh()` returns the shared catalogue | `test_check_containment_cases` | killed (4 failures, 11 errors) |
| M5b | `fresh()` returns the shared matrix | `test_check_network_matrix` | killed (3 failures, 9 errors) |
| M6a | `commit_all` without `--all` | `BaselineMode` | killed |
| M6b | `commit_all` returns a wrong commit | `BaselineMode` | killed |

## 6. What was not changed, and why

The after profile's largest classes, and the options the Overseer can weigh:

| Class | Wall (s) | Why it stays |
|---|---|---|
| `WithRealScanner` | 15.1 | Each case is a real commit or push through the hooks and the pinned Gitleaks: the gate's subject. Its three allowlist golden pairs (about 0.5 s each) could become one if a single configuration allowlisted all three paths, but that changes the inputs of security tests: **option, not taken (about 1 s).** |
| `FailsClosed` | 8.4 | Real hook runs, each failing closed. |
| `CrashMatrixTests` | 7.9 | Real processes are the subject. Launching the workers through the base interpreter instead of the venv's redirector would save about 7 ms a launch (1.4 s in the store suite), but changes the children's interpreter: not recommended. |
| `NetprobeListener` | 6.7 | The real listener (its main script is compiled on every launch), Windows' refusal delay and the pinned netprobe's 2.0 s wait (F-09.3 reached the same conclusion; the netprobe is pinned by sha256). |
| `test_verify_seed` | 8.1 | The verifier is integrity-tracked; its file reads per call are its cost. |
| Network matrix, containment fuzz | 7.8 | The checkers' own evaluation (about 11.7 ms per matrix mutation); a faster checker is a product change. |
| `test_git_batch.Launcher` | 3.4 | Its 1 s ceilings and sleeps are the subject (a tree ended at its ceiling); shorter ones risk a vacuous pass under load. |
| `test_guest.ApiProbe` | 2.3 | The remaining 2 s is the refusal delay of the connection-refused case. |
| `test_guest.Smoke`, `.Inventory` | 2.3 | About 2.1 s is the status of the live checkout. `guest.Context(..., repo_root=)` already exists and could point them at a small fixture repository, but they would stop inventorying the real checkout: **option, not taken (about 2 s).** A status that skips hashing on matching stat data would be a `repository_access` change (decision 0014). |

Options (1) the Smoke and Inventory repository through `repo_root` and (2) one allowlist golden
pair together are about 3 s, which would reach about 134 s; both change what a test reads, so
they are the Overseer's call. The F-09.3 and F-09.4 measures (golden fixtures, the Backlog
runner seam, in-process repository reads) are unchanged.

## 7. Budgets (`50e834a`)

From the `98bb781` three-run profile. Counters follow it (launches 1,158; mkdtemp 1,047; tests
1,970). Walls only fall, each the lower of the committed and the proposed value. **Fell:** tools
77.5 → 71.1, lineage 18.1 → 14.0, dispatch 5.0 → 4.6, planning 12.1 → 12.0, unit 23.8 → 22.3.
Kept: the total's 134.2 and every other wall. `check --profile` of that profile against the new
budgets: PASS; the committed baseline passes them (`CommittedBudgetTests` OK). Headroom now:
contract 20.8 of 21.97 s (was 21.2), gitea 3.22 of 3.25 s (unchanged, the tightest scope).

## 8. Checks run

- `python -I tools/verify_seed.py` and `--baseline seed`: PASS (165 tasks; seed baseline 136), at
  `cb5a751` and at `98bb781`.
- Every suite under the tools interpreter with `PYTHONDONTWRITEBYTECODE=1`: all pass (also with an
  empty `AIEH_DATA_ROOT`, section 4).
- pytest: section 4. `task hooks:verify` (`publication_gate.py verify`, then the gate's 27 tests
  with `AIEH_GATE_REQUIRE_SCANNER=1`, the nested whole tool-suite rerun included): PASS, OK.
- `test:budget` from Git Bash, three runs, `cleanmgr` absent before and after: section 1.
- `test_profile.py categories` under the tools interpreter: PASS (338 classes).

## 9. Findings

- **F-1, unrelated but detected:** `task test:categories` runs under the plain interpreter
  (`{{.PYTHON}}`), and there it FAILs: `integrations/credentials/tests/test_credential_provider.py`
  imports `keyring`, which only the tools interpreter has. Under the tools interpreter: PASS.
  Not changed (outside this slice).
- **F-2, introduced by this work and repaired before any commit:** the empty init template in the
  owner fixture failed `test_a_repository_with_client_hooks_is_refused`; reverted there and for
  the other `repository_access` fixtures (section 3).
- **F-3, observation:** `test_guest`'s Smoke and Inventory read the live checkout, so they depend
  on its state; `repository_access` status hashes every tracked file of matching size (601 files,
  about 117 ms per call).
- **F-4, observation:** the message of `50e834a` says its before was interleaved with "the changed
  tree"; those interleaved runs were at `cb5a751`, the `98bb781` tree less its last commit.

## 10. Not verified

- PowerShell timings (its `cmd\git.exe` launcher adds a process per git command); only Git Bash
  ran here.
- POSIX hosts.
- `docs/development.md`'s wall-time history still ends at `3aa5ef3`; this slice changed test code
  and budgets only.
