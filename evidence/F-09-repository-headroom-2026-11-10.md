# F-09 repository headroom: the repository suite under its wall

Builder evidence of 2026-11-10 for the Overseer's bounded test-runtime slice under the Owner's
scheduling priority of 2026-11-08 (a serial suite of at most 150 s, every required security and
contract test still enforced, no reduction in meaningful coverage, measured before and after, no
redesign of the testing architecture). F-09 patterns only, no new leaf. The verdict is the
Overseer's.

- **Why:** the Overseer's `check --run` at `c4cf76a` failed one row: the repository suite, median
  7.86 s against its 5.9 s budget (limit 7.67 s), with no change to the suite (the previous
  builder measured 7.21 s; host drift). Overseer ruling: the wall is not raised; make the suite
  faster without weakening it, to a median of at most 5.5 s, as was done for the gitea and store
  suites.
- **Reached:** the repository suite **7.26 → 4.82 s** (interleaved medians, section 1); the
  serial median 140.4 → 137.7 s in the same set. `check --run` at `89196ae`: **PASS**, serial
  median **135.5 s**, repository **4.71 s** (section 6).
- **Commits** (on `9f01adc`): `3dddcd7` (the repository tests), `89196ae` (budgets and baseline
  re-proposed at `3dddcd7`), then this record. Test code under `integrations/repository/tests/`,
  the two budget files and this record only; no product file, no integrity-tracked file, nothing
  under `decisions/`, `evidence/bootstrap-log.md` untouched.
- **Host:** Windows 11 x86_64, 32 logical processors, CPython 3.12.10 under the `python-tools`
  interpreter, Git for Windows 2.52.0. Every run from Git Bash with `PYTHONDONTWRITEBYTECODE=1` and
  `AIEH_DATA_ROOT`, `TEMP` and `TMP` set to new, empty directories under the session scratch (the
  data root empty after every run). Windows Disk Cleanup (`cleanmgr`) absent before and after every
  timed run: each run's script waits on its exit (`Wait-Process`) before starting and discards a
  run it appeared in (none was). `task` is not installed: each target ran as the command it wraps.
- **Raw material** (not committed): `<session scratch>/c62`: the profiles (`prof/first1.json`,
  `prof/work1.json`, `prof/ab-{before,after}-{1,2,3}.json`, `prof/budget3.json` and its compact
  form), the run scripts and logs (`scripts/`, `logs/`), the in-process probes and their equivalence
  checks (`probe/`), the budget proposal and merge (`budget/`), the mutation runner and its results
  (`scripts/mutate.py`, `mut/results-*.json`).

## 1. Before and after

Before: `9f01adc`. After: `3dddcd7` (`89196ae` only re-proposes the budgets). Full serial profiles
(`tools/test_profile.py run`), interleaved in the checkout (after, before, three times; `git
checkout --detach 9f01adc` and back to `main`).

| Suite | Before runs (s) | Before median | After runs (s) | After median | Change |
|---|---|---|---|---|---|
| tools | 73.83, 74.75, 73.51 | 73.83 | 75.53, 74.72, 73.65 | 74.72 | +0.89 (same code) |
| store | 11.69, 11.18, 11.34 | 11.34 | 11.16, 11.31, 11.44 | 11.31 | −0.03 |
| effects | 2.73, 2.74, 2.76 | 2.74 | 2.75, 2.79, 2.87 | 2.79 | +0.05 |
| planning | 12.39, 12.34, 12.59 | 12.39 | 12.40, 12.21, 12.44 | 12.40 | +0.01 |
| lineage | 14.74, 15.00, 15.08 | 15.00 | 15.04, 14.72, 14.79 | 14.79 | −0.21 |
| owner | 4.30, 4.44, 4.37 | 4.37 | 4.47, 4.36, 4.43 | 4.43 | +0.06 |
| paths | 1.55, 1.57, 1.63 | 1.57 | 1.62, 1.52, 1.70 | 1.62 | +0.05 |
| platform | 0.26, 0.26, 0.26 | 0.26 | 0.27, 0.25, 0.29 | 0.27 | +0.01 |
| credentials | 0.91, 0.88, 0.96 | 0.91 | 0.92, 0.83, 0.88 | 0.88 | −0.03 |
| gitea | 2.47, 2.44, 2.47 | 2.47 | 2.46, 2.45, 2.46 | 2.46 | −0.01 |
| dispatch | 6.36, 6.27, 6.38 | 6.36 | 6.92, 6.18, 6.37 | 6.37 | +0.01 |
| **repository** | 6.99, 7.26, 7.31 | **7.26** | 4.87, 4.77, 4.82 | **4.82** | **−2.45 (−34 %)** |
| inference | 1.82, 1.78, 1.74 | 1.78 | 1.75, 1.61, 1.48 | 1.61 | −0.17 |
| **serial** | 140.0, 140.9, 140.4 | **140.4** | 140.2, 137.7, 137.6 | **137.7** | −2.7 |

The attributable saving is the repository suite's 2.45 s; every other suite is the same code at
both revisions (the gitea suite, which also extracts a corpus subset through the changed
`extract_tree`, moved by 0.01 s) and moved within noise. A first single profile at `9f01adc`,
before any change, measured the repository suite at 7.95 s.

Per class (medians of the interleaved runs; every other class moved by less than 0.01 s or is
noise between runs of unchanged code):

| Class | Before (s) | After (s) | Change (s) | Launches | mkdtemp |
|---|---|---|---|---|---|
| `test_repository_oracle.OracleAgreement` | 2.891 | 0.906 | **−1.985** | 212 → 212 | 1 → 1 |
| `test_repository_oracle.OracleBundles` | 0.351 | 0.136 | −0.215 | 15 → 15 | 1 → 1 |
| `test_repository_access.AttributeFiles` (pays the corpus extraction) | 0.485 | 0.281 | −0.204 | 0 | 2 → 2 |
| `test_repository_oracle.OracleTransport` (unchanged) | 0.396 | 0.416 | +0.020 | 3 | 2 |
| `test_repository_transport.Push` (unchanged) | 0.166 | 0.240 | +0.074 | 0 | 1 |

Per test: `OracleAgreement.test_rev_parse_gives_the_batched_answers_for_the_proof_forms` 0.175 →
0.034 s (17 launches); `OracleBundles.test_bundles_verify` 0.349 → 0.135 s (15 launches).
`Push` is unchanged code (no test file it uses changed); its +0.07 s is noise of that class, which
ranged 0.12-0.34 s across this session's profiles of both revisions.

## 2. Where the time went (profile first)

The first profile at `9f01adc` (7.95 s), with each class split into its fixture and its tests, and
in-process timings of the oracle fixture by git command (`probe/oracle_cost.py`) and of the corpus
extraction (`probe/extract.py`):

| Cost | Wall (s) | Cause | Disposition |
|---|---|---|---|
| `OracleAgreement.setUpClass` | 2.24 | `repository_corpus.answers(batch=True)`: **191 git launches one after another** (63 `ls-files`, 45 `cat-file --batch-check`/`--batch`, 35 `status`, 13 `ls-tree`, 14 `rev-parse --show-toplevel`, 11 `rev-parse HEAD`, 9 `rev-parse --revs-only`, 1 `--version`; about 12 ms each), each an independent read of the corpus | changed (section 3, 1) |
| `OracleBundles.test_bundles_verify` | 0.33 | 5 cases, 3 git launches each (`bundle verify`, `bundle list-heads`, `bundle create`), one after another | changed (3, 2) |
| corpus extraction (`AttributeFiles.setUpClass`, the first to call `corpus()`) | 0.37-0.40 | 1,331 entries (643 directories, 688 files, 235 read-only) written one after another | changed (3, 3) |
| `OracleAgreement.test_rev_parse_...` | 0.19 | 17 `rev-parse --verify` launches, one after another | changed (3, 2) |
| `WriteCommit` | 0.66 | a git-built golden repository (4 launches) and git's view of each commit (`fsck`, `status`, `reflog`, a later `commit`, `ls-tree`, `show`: each depends on the previous or on the module's write) | not changed |
| `RecordedExpectations`, `RecordedCases`, `Export`, `Bundles`, `ConfigPolicy` | 1.5 | the module's own reads in process (Dulwich), no launch: product cost | not changed |
| `OracleTransport` | 0.46 | the local smart-HTTP server and git's `ls-remote` and two `fsck` over it, each depending on the module's clone or push | not changed |
| corpus removal at exit | 0.16 | `atexit` rmtree; a thread pool cannot be started once the interpreter is shutting down (tried, reverted; see F-3) | not changed |

## 3. The changes, and why every assertion is preserved

`integrations/repository/tests/repository_corpus.py` and `test_repository_oracle.py` only:

| # | Change | Saving (s) | Counters |
|---|---|---|---|
| 1 | **The oracle fixture asks its questions together.** `answers(root, facts, batch=True)` (the oracle tests' path) submits every question to a pool of 16 threads (`ORACLE_WORKERS`), each question the same `Oracle` method with the same arguments as before (so the same git process with the same argv and environment, `GIT_OPTIONAL_LOCKS=0`, over the read-only extracted corpus), then reads each answer into the place its sequential answer had. A question with an internal sequence (`names`, restarting `cat-file` after a name git dies on; `export_members`, `ls-tree` then `cat-file --batch`; `status_batched`) still runs its launches in order within one thread. The recording path (`batch=False`) asks the same questions at once, one after another, in the same order (`_Asked`). | **1.99** | launches 212, mkdtemp 1: unchanged |
| 2 | **The proof forms' 17 `rev-parse` launches and the bundle test's 15 git launches run together** (`repository_corpus.concurrently`: the calls' results in order, the first error raised again once every call ended). The bundle test first lets the module write all five bundles (each checked in its subTest as before), then asks git's three questions about all of them together, then checks each case in its own subTest in the old order; it now also asserts that every case was written and checked. | **0.36** (0.175 → 0.034, 0.349 → 0.135) | launches 17 and 15: unchanged |
| 3 | **The corpus extraction writes each top-level subtree in its own thread** (8 at a time, `EXTRACT_WORKERS`); every path is checked before anything is written (it was checked entry by entry while writing), the root's own entries are written first, and each subtree's entries are written in the archive's order with the same calls (directories, bytes, read-only bits). | **0.20** | mkdtemp unchanged |

Why nothing a test proves changed:

- **Every git launch of the oracle is still made, one per question as before**, with the same
  argv and environment: the git-oracle differential tests still compare the module with real
  `git` answers asked now. Only their start times overlap. No launch writes: the corpus is only
  read (`GIT_OPTIONAL_LOCKS=0` keeps `status` from refreshing the index; `bundle create` writes
  its own file in the test's temporary directory, as before), so no answer can depend on another
  launch. No test's subject is how long git takes; no timeout or ceiling changed.
- **Equivalence, measured** (`probe/equiv.py`, one extracted corpus, the `9f01adc` module loaded
  beside the new one): recording mode (693 launches): the **same launch sequence** (repository,
  argv, input; in order) and equal answers; batch mode (191 launches): the same launches as a
  multiset, equal answers, and equal to the committed recorded fixture. The extraction
  (`probe/extract_equiv.py`): the whole tree (1,331 entries) and a subset (174 entries) are equal
  in type, permission bits and bytes to the old extraction's.
- **No assertion was removed, weakened or reworded.** One was added: every bundle case written
  and checked (mutant H4 below is killed only by it). The subTest parameters are unchanged.
- The pools are local to the call and shut down before it returns (on an error, pending questions
  are cancelled and running ones waited for); no thread outlives the fixture or the test, so none
  runs while a `Ceilings` test observes `os.stat` or `os.lstat`, and nothing new is stat-ed above
  any test's temporary root (the extraction writes only below its own temporary directory, as
  before).

## 4. Equivalence

- **Test ids and outcomes:** the six interleaved profiles have the same 2,271 rows (2,264 tests
  and the class and module fixture rows) with the same outcome each, and the same outcomes digest
  (`91854691…`). `test_profile.py compare` of a plain repository run at the change against the
  first `9f01adc` profile: **PASS, identical ids and outcomes** (106 tests). The suite under
  unittest: 106 tests, OK.
- **Counters:** every class's tests, launches, mkdtemp, sockets and chdir are equal in all six
  profiles (serial totals 1,160 launches and 1,043 mkdtemp in every run); the profiler attributes
  the pool threads' launches to the same programs and sites (`git … @ repository_corpus.py`).

## 5. Mutation checks

In a throwaway copy (`git archive HEAD integrations` at `9f01adc` with the two changed test files
copied in; `TEMP`, `TMP` and the data root new and empty for each mutant, and empty afterwards),
each mutation applied alone, `test_repository_oracle.py` run under the tools interpreter. M0, the
unmutated copy: 15 tests OK.

| Id | Mutation | Result |
|---|---|---|
| P1 | product: `commit()` answers None for every `HEAD~` form | killed (`test_commit_forms`, 20 failures) |
| H1 | harness: every repository gets the first repository's object-name answers | killed (`setUpClass` error) |
| H2 | harness: every repository gets repo one's head answer | killed (16 failures: the recorded comparison and the module comparison) |
| H3 | harness: `concurrently` returns the answers in reverse order | killed (the proof forms and the bundle test, 15 failures, 5 errors) |
| H4 | harness: the last bundle case is silently dropped | killed (the added completion check) |
| H5 | harness: `extract_tree` leaves out the first subtree | killed (`setUpClass` error) |
| H6 | harness: every work tree gets the conflicted repository's index | killed (16 failures) |
| H5b | harness: `extract_tree` leaves out the last subtree (`xdg empty`, an empty directory) | survived, equivalent: the oracle's `XDG_CONFIG_HOME` names it, and git and the module read a missing directory as an empty one; the whole suite in the copy gives M0's result too (finding F-2) |

## 6. Budgets (`89196ae`) and the budget check

Re-proposed from a three-run profile of `3dddcd7` (clean tree, `cleanmgr` absent before and
after): serial runs 139.9, 138.5, 135.5 s, **median 138.5 s**; repository 4.78, 4.87, 4.61 s
(median 4.78 s). Counters follow the profile (all unchanged); walls only fall:

- **Fell:** repository 5.9 → **4.8 s** (limit 7.67 → 6.24 s), from the new measurement; store
  11.5 → 11.2 s (limit 14.95 → 14.56 s) and the integration category 90.9 → 87.5 s, the lower
  of committed and measured.
- **Kept** (each proposal at or above it): every other suite, the total (134.2 s) and the other
  categories. None rose.
- The baseline (`evidence/test-profile/baseline.json`) is that profile's compact form; its
  `measured` field (`2026-11-11`) is the profiler's own date stamp. `check --profile` of it against
  the new budgets: PASS; `test_check_test_budget` (17 tests, with `CommittedBudgetTests`): OK.

`check_test_budget.py check --run` at `89196ae` (clean tree, an empty data root, still empty
after): **PASS**, no failure and no note (every counter equal to its budget). Serial runs 135.5,
135.4, 135.8 s, **median 135.5 s** (at or under 150 s); repository 4.71, 4.81, 4.66 s, **median
4.71 s** (limit 6.24 s); store 10.92 s (limit 14.56 s); gitea 2.43 s (limit 3.12 s); every scope
under its limit. A first attempt of this check was discarded unread because `cleanmgr` was
running when it ended; the script then waited on `cleanmgr`'s exit and ran the check again
(`cleanmgr` absent before and after the counted run).

## 7. Checks

- `python -I tools/verify_seed.py`: PASS (167 tasks, 177 seeded files, 3 changed since seed).
- The repository suite under the tools interpreter: 106 tests, OK; `compare` against the before
  profile: identical ids and outcomes.
- `tools/test_profile.py categories` (tools interpreter): PASS (413 classes in 72 modules).
- The launch census (`tools/tests/test_launch_census.py`, at `3dddcd7`): OK (12 tests).
- `test_check_test_budget`: OK (17 tests); `check --profile` of the new baseline: PASS.
- `check_test_budget.py check --run`: section 6.
- Mutation checks: 8 of 9 killed, 1 equivalent (section 5).
- Publication gate: pre-commit PASS on each commit; `history origin/main..HEAD`: PASS (the three commits of this slice).
- A search of these commits' diffs and messages for personal paths and user names: none (the only matches are the commits' author headers and a substring of a test class name).

## 8. Findings

- **F-1, observation:** the eight-file suite of the pending OA-17 Linux run (revision 4) carries
  `repository_corpus.py` and `test_repository_oracle.py`, both changed here. That run binds commit
  `3cf45cd` and its archive `ac969359…6c8d`, so it is not affected; a later run of these files at
  a newer commit would carry the thread pools (plain `concurrent.futures` and `subprocess`; not run
  on POSIX here).
- **F-2, observation:** dropping the corpus's `xdg empty` directory changes no test's outcome
  (mutant H5b): a missing `XDG_CONFIG_HOME` reads as an empty one for git and for the module. Not
  changed (the corpus is a committed fixture; it is the same before and after).
- **F-3, observation:** the corpus's removal at process exit (about 0.16 s) stays serial: a
  thread pool cannot start during interpreter shutdown (`RuntimeError: cannot schedule new futures
  after interpreter shutdown`), seen once while trying it, which left that run's corpus directory
  in its own scratch `TEMP` (removed). Reverted before the commit.
- **Remaining costs** (unchanged): the module's in-process reads (about 1.5 s, product cost),
  `WriteCommit` (0.6 s, git's sequential view of each write), `OracleTransport` (0.4 s, the HTTP
  server and git's dependent checks), the corpus extraction's critical path (`repo one`'s 268
  entries, about 0.18 s).

## 9. Not verified

- pytest (`--aieh-conformance`, serial or xdist) was not run in this slice; the changed modules use
  only `concurrent.futures` and plain `subprocess` inside one fixture or test.
- POSIX hosts (ran only on Windows); PowerShell timings; the CI workflow.
