# F-09 serial test runtime headroom: 148.8 to 135.9 s

Builder evidence of 2026-11-11 for the Overseer's bounded test-runtime slice: the serial run that
`tools/check_test_budget.py check --run` measures was 145.7 s at `0927e3b` against the Owner's
150 s ceiling, and the owner suite's wall was marginal. The aim: at least 15 s under 150 s without
weakening any test; walls lowered to the new measurement in a separate budget commit (walls only
fall). Test code and shared test helpers only; no product file, no integrity-tracked file, nothing
under `decisions/`. The verdict is the Overseer's.

- **Reached:** serial median **148.8 s → 135.9 s** (−12.9 s, −8.7%) on this host today: 14.1 s
  under 150 s. `check --run` at the budget commit: median 136.8 s (13.2 s under 150 s), every
  counter and test passing, one wall over: the owner suite's (5.22 s, limit 5.20 s; section 6).
  After the Overseer's rulings (section 7: the owner wall raised by its new tests' measured cost,
  the record writer's change): **`check --run` PASS** at `a01c960`, median 136.2 s (13.8 s under
  150 s).
- **Tests:** 2466 before and after; every run of both trees gave the same outcomes digest
  (`ce38af9f9c78`: the same test ids with the same outcomes). No test was removed, skipped or
  marked slow. Launches 1173 → 1148; `mkdtemp` 1077 → 1056.
- **Commits** (on `730649f`): `79b75be`, `b2f0827`, `7efcad8`, `73c40a8`, `40a72d3`, `ed142a2`,
  `808d96c`, `7241e3f`, `1ed7903` (the changes, section 2), `abffaa5` (budgets and baseline
  re-proposed at `1ed7903`), `682f4b3` (this record); after the rulings `644ec49` (the record
  writer), `85c2ac7` (the owner wall), `a01c960` (budgets re-proposed at `644ec49`), then this
  record's update.
- **Host:** Windows 11 x86_64, 32 logical processors, CPython 3.12.10 under the `python-tools`
  interpreter, Git for Windows 2.52.0. Every measurement ran from Git Bash with `TEMP` in a session
  scratch directory, `PYTHONDONTWRITEBYTECODE=1`, `AIEH_DATA_ROOT` an empty scratch directory, the
  run in a kill-on-close job object started with `CREATE_NO_WINDOW`, and Windows Disk Cleanup
  (`cleanmgr`) absent before and after each run. `task` is not installed: each target ran as the
  command it wraps.

## 1. Before and after (per suite)

Before: `730649f`. Three single `tools/test_profile.py run` profiles of each tree, interleaved in
the checkout (after, before, three times; `git checkout --detach` and back), then a three-run
profile of the final tree (`--runs 3`, the budget baseline).

| Suite | `730649f` (3 interleaved) | `808d96c` (3 interleaved) | `1ed7903` (3-run profile) | runs at `1ed7903` | change |
|---|---|---|---|---|---|
| tools | 81.20 | 74.51 | 73.60 | 73.51, 73.60, 73.71 | −7.61 |
| store | 11.47 | 10.69 | 10.76 | 10.76, 11.10, 10.69 | −0.71 |
| effects | 2.81 | 2.20 | 2.18 | 2.14, 2.18, 2.21 | −0.63 |
| planning | 12.64 | 10.52 | 10.48 | 10.61, 10.48, 10.30 | −2.16 |
| lineage | 15.25 | 14.29 | 13.96 | 13.55, 13.96, 13.98 | −1.29 |
| owner | 5.20 | 5.12 | 5.02 | 5.01, 5.02, 5.07 | −0.18 |
| paths | 1.60 | 1.56 | 1.56 | 1.60, 1.54, 1.56 | −0.04 |
| platform | 0.25 | 0.26 | 0.26 | 0.27, 0.25, 0.26 | +0.02 |
| credentials | 0.86 | 0.86 | 0.88 | 0.94, 0.83, 0.88 | +0.01 |
| gitea | 2.73 | 2.72 | 2.69 | 2.73, 2.69, 2.69 | −0.04 |
| dispatch | 6.20 | 5.51 | 5.55 | 5.55, 5.55, 5.62 | −0.65 |
| repository | 4.92 | 5.20 | 5.12 | 4.74, 5.12, 7.36 | +0.19 |
| inference | 3.52 | 3.54 | 3.55 | 3.49, 3.60, 3.55 | +0.03 |
| **total** | **148.77** (148.45, 148.77, 150.22) | **137.24** (134.67, 137.24, 138.01) | **135.92** (134.89, 135.92, 137.90) | | **−12.85** |

The suites the slice does not touch (paths to inference) moved within the host's noise (the
repository suite's 7.36 s run is one slow run). This host ran about 3 s slower today than the
dispatch's 145.7 s at `0927e3b`.

## 2. Where the time went, and each change

Found with a first profile of `730649f`, in-process `cProfile` of every suite, a per-class split of
`setUp`, body and cleanups, `GIT_TRACE2_PERF` traces of the fixture and hook git processes, and
timings of single costs (a refused loopback connect, a fixture copy, a store creation). Savings are
per-class medians of the interleaved runs (`730649f` → `808d96c`) unless stated.

| Commit | Change | Cause removed | Measured saving |
|---|---|---|---|
| `79b75be` | Fixture git commits set `maintenance.auto=false` (the two-task fixture's `git`, `test_verify_seed`'s `git`, and the publication gate's golden pair, whose own configuration is now written into the config files `git init` wrote instead of five `git` launches per golden pair) | every `git commit` and receive started `git maintenance run --auto` (about 30 ms; 86 counted outside the gate tests), whose thresholds a fixture never reaches | gate `WithRealScanner` 16.66 → 15.93 s, `FailsClosed` 9.05 → 8.82 s; part of lineage's −1.0 s and planning's other savings; 25 launches fewer |
| `b2f0827` | `Acceptance.test_schema_and_types_never_crash` evaluates the key-independent `enforcement = [value]` input once per value | the same input was evaluated inside the loop over 18 keys: 153 of 369 evaluations (about 11 ms each) were exact repeats | 4.96 → 3.18 s |
| `7efcad8` | The smoke sequence and Inventory's two destroy/diff tests run on a context whose checkout is a copy of `fixture_repo`'s repository (`guest.Context`'s existing `repo_root` parameter) | 18 inventories a run hashed every tracked file of this checkout (about 0.15 s each) | `Smoke` 1.69 → 0.49 s, `Inventory` 0.99 → 0.40 s |
| `7efcad8` | `NetprobeListener.test_client_results` makes its two refused connects at once | a refused loopback connect takes 2.0 s on Windows (SYN retries after the reset; measured 2.02-2.05 s) | 6.80 → 4.76 s |
| `73c40a8` | `Equivalence` runs its one-shot git oracle commands first, four at a time, then compares | 107 one-shot launches one after another | 1.78 → 0.93 s |
| `73c40a8`, `808d96c` | `test_a_normal_close_ends_the_launcher_and_its_child`: the child waits for a line on its inherited standard input instead of sleeping 1 s | a fixed 1 s sleep that kept the child alive to be watched | `Launcher` 3.42 → 2.46 s |
| `40a72d3` | dispatch's integration store per test, and the lineage example's per store directory, start as a copy of one migrated empty store | creating and migrating a store took about 12 ms, a copy and open about 3 ms (84 + about 40 a run) | dispatch −0.65 s, part of lineage's |
| `ed142a2` | `test_restore_needs_exclusive_custody` (store, effects) passes `timeout_ms=50` to the real `storecore.acquire_exclusive` | the refusal waited out the 500 ms default busy timeout, though the worker holds its lock until it is stopped | 1.12 → 0.59 s and 1.06 → 0.51 s |
| `7241e3f` | `two_task_fixture.golden` writes each copy from a snapshot of the golden tree read once | `shutil.copytree` per copy (about 170 a run) | 37 → 29 ms a copy in process (about 1.5 s a run) |
| `1ed7903` | The profile checker's four block classes restore one work copy per class (`SeedCopy`'s pattern) | a full copy of `profiles/`, the lock and the evidence per test, its removal, and Windows' first-read scan of each new file (about 50 ms a test, 25 tests) | the four classes 2.74 → 1.88 s in process; 21 `mkdtemp` fewer |

Not changed, with the reason:

- **The publication gate's real hooks** (`WithRealScanner`, `FailsClosed`: 24.8 s): each gated commit
  or push runs the hook, two Python starts through the `python3` shim, the gate's git reads and the
  pinned Gitleaks (about 0.25 s a scan); `6f` waits out the gate's shortest timeout (1 s) twice.
  These are the tests' subject.
- **Real waits that are the property:** `NetprobeListener.test_exchange_decoys_and_stop` (the decoy's
  UDP no-reply window, 2.0 s, a constant in the guest program), `ApiProbe.test_connection_refused_is_recorded`
  (one refused connect in the probe child, 2.0 s), the git_batch launcher ceilings (`timeout=1`,
  twice) and `RealLauncher`'s 0.5 s observation, `TestJobObject`'s 1.0 s control window (ruled kept
  on 2026-11-10).
- **Product evaluation cost** in the checkers' fuzz and mutation tests (`check_containment_cases`,
  `check_network_matrix`, `check_ci_policy`, `check_profile`), `verify_seed`'s hashing, and the owner
  suite (in process, 3.63 s of its 4.88 s is the recorders' own work).
- **Shareable only with a product change (finding, for the Overseer):** `guest.write_json_exclusive`
  writes each record with `json.dump(..., indent=2)` into the file, which runs the pure-Python
  encoder chunk by chunk; 264 records a run, 3.4 s under `cProfile` in the tools suite
  (`ContainmentProbe` alone about 1.2 s of body). Writing `json.dumps(...)` in one call gives the
  same bytes, much faster; it is a product change, so it is not made here. **Corrected in section
  7:** that estimate was `cProfile`'s per-call overhead; measured without a profiler the writer
  takes about 0.5 s a run and one `json.dumps` saves about 0.07 s of it.

## 3. No assertion weakened

- **Exact repeats only removed.** `b2f0827` removes repeated evaluations of one input, not a test
  or a distinct input. Before, inside `for key in keys:` (18 keys):
  `m = fresh(); edge(m, 'nm-owner-guest-ssh')['enforcement'] = [v]; self.codes(m)`; after, the same
  three lines once per value after that loop. `fresh()` is a new parse of the committed text, the
  class's `tearDown` still asserts no evaluation changed the shared inputs, and every distinct input
  is still evaluated.
- **Same processes, same sockets.** The concurrent oracle and refused connects run every launch and
  connect they ran before, with the same assertions; only their order in time changed.
- **Same fixture content.** Equivalence probes: the gate's golden pairs (default, allowlist, stub)
  built the old and the new way with fixed dates have the same commit, refs, objects, index and files;
  their config values differ only by the added `maintenance.auto=false`. Each golden repository kind
  copied by `copytree` and by `copy_snapshot` (design repository, lineage project, dispatch revised
  design, owner project) has the same entries, bytes, modes, file attributes and modification times.
  A store copy holds the schema and rows of a fresh store (the migrations' `applied_at` times
  differ), and each test still opens it with `open_store`, which verifies every applied migration.
- **The checkout inventory.** The smoke and destroy tests assert that the inventories around a
  destroy or recreate are unchanged; they now inventory a fixture repository instead of this
  checkout. What the repository inventory records is tested on `fixture_repo` (`test_repository_inventory`
  and its sibling), and `Smoke.test_refusals` keeps this checkout (the record must not go into it).
- **Timeout through a parameter.** `ed142a2` sets `acquire_exclusive`'s own `timeout_ms` for the two
  refusal tests; the worker holds its lock until stopped, so the refusal, its code and the checks
  after it are the same at 50 ms as at 500 ms.

Mutation spot-check of the refactored fixtures (`HEAD` archived to scratch, each mutant run in a
kill-on-close job object; baselines green):

| Mutant | Result |
|---|---|
| Equivalence oracle answers rotated / all `None` | killed (32 and 31 failures) |
| Dispatch tests share the class's store / the class store holds a planted reservation | killed (35 and 130 failures and errors) |
| Lineage golden store holds a planted reservation | killed (11) |
| Gate golden without `core.hooksPath` / with the origin remote pointing elsewhere | killed (12 and 13) |
| Netprobe client reads a refusal as a timeout (`tcp`) / `exchange` reads it as no exchange | killed (1 each) |
| Profile work copy: restore copies nothing back | killed by the setUp check (7) |
| Profile work copy: restore keeps added files | survived: equivalent, no test adds a file |
| Profile work copy: no restore and no check | survived: without the check, the writes of this order's tests do not change a later outcome; the check is what keeps each test on a fresh tree |
| Normal-close child does not wait for its line | survived: the child is still starting when it is watched, as it was with the old 1 s sleep removed |

The last row corrects `808d96c`'s message, whose final sentence says this mutant then fails; the
rerun showed it survives. The `alive()` check it added holds the precondition (the child runs when
watched) but cannot catch a child that ends a few milliseconds later.

## 4. Budgets (`abffaa5`)

Re-proposed from the three-run profile of `1ed7903` (`evidence/test-profile/baseline.json`). Walls
only fall, each the lower of the committed and the measured wall: store 11.2 → 10.8, effects
2.6 → 2.2, planning 11.8 → 10.5, dispatch 5.7 → 5.6 and the integration category 87.5 → 82.7 s;
every other wall kept. Counters to the new baseline: launches 1173 → 1148 (tools 318 → 293,
integration 1011 → 986), `mkdtemp` 1077 → 1056 (tools 563 → 542, unit 549 → 528); tests 2466.

## 5. Checks

- **`tools/check_test_budget.py check --run` at `abffaa5`** (three serial runs, tools interpreter,
  `cleanmgr` absent before and after): serial median **136.8 s** (136.39, 136.84, 136.80): **13.2 s
  under 150 s**. Every counter passes and every test passes (2466; outcomes digest `ce38af9f9c78`,
  the same as every run of `730649f`): tools 1284 (1278 ok, 6 skipped), store 84, effects 34,
  planning 104 (7 skipped), lineage 146 (6 skipped), owner 126, paths 38, platform 38, credentials
  51, gitea 200, dispatch 113, repository 106, inference 142. **FAIL on one wall only:**
  `WALL_ABOVE suite owner: median 5.22 s, budget 4.0 s, limit 5.20 s` (runs 5.22, 5.24, 5.16).
- An earlier `check --run` at `abffaa5` is discarded: Windows Disk Cleanup started during it
  (`cleanmgr` present after the run; runs of 136.0, 145.2 and 162.6 s). The rerun above started
  after it exited.
- `python -I tools/verify_seed.py` PASS; `python -I tools/verify_seed.py --baseline seed` PASS.
- `python -I -B tools/publication_gate.py history origin/main..HEAD` PASS (run again after this
  record's commit).
- Every commit passed the pre-commit gate. No hook was bypassed.

## 6. Open for the Overseer (as first reported; ruled in section 7)

- **The owner wall fails `check --run` by 0.02 s** (median 5.22 s, limit 5.20 s; the dispatch
  measured 5.1 s at `0927e3b`). Its budget, 4.0 s, was set at `68a3bc2` for 113 tests; the suite has
  had 126 since `6f75943`, whose re-proposal kept the wall. Today's medians: 5.20 s before this slice
  (runs 5.17, 5.20, 5.32), 5.0-5.2 s after. In process, 3.63 s of the suite's 4.88 s are the test bodies, the recorders' own work
  (prepare, record, the fake Gitea over loopback); its fixtures are about 1 s and already shared
  where nothing writes (the golden project now copied from a snapshot, one migrated store per
  module). No change allowed here removes 0.3 s or more from it without weakening a test; the wall
  is not raised here. A decision for the Overseer: re-measure the owner wall for its 126 tests, or
  a product-side speedup.
- **15 s aim:** 14.1 s under 150 s by the three-run profile and 13.2 s by `check --run` on today's
  host, which ran about 3 s slower than at `0927e3b` (148.8 s before against the dispatch's 145.7 s).
  The product finding in section 2 (`write_json_exclusive`, about 1 s or more in the tools suite)
  is the largest saving left that this slice may not take.

## 7. The Overseer's rulings and their results

**1. The owner wall** may rise only by the measured cost of the tests added since its budget was
set (`68a3bc2`, 113 tests). The tests added since then, by id: test discovery of
`integrations/owner/tests` at `68a3bc2` (114 ids) and at `644ec49` (127 ids), compared; 13 ids
added, none removed. They came with the OA-16 slice (`20377ea`, `a63636e`). Their per-test medians
come from `tools/test_profile.py run --runs 3` at `644ec49` (clean tree, `cleanmgr` absent before
and after); a test's wall includes its `setUp` and cleanups:

| Test (added since `68a3bc2`) | Median (s) |
|---|---|
| `test_authorization_recorder.ProtectionCheck.test_a_refused_statement_reads_neither_credential` | 0.013 |
| `test_authorization_recorder.ProtectionCheck.test_a_rule_changed_across_the_merge_is_disclosed` | 0.030 |
| `test_authorization_recorder.ProtectionCheck.test_drift_refuses_before_anything_is_sent_and_the_challenge_stays_usable` | 0.049 |
| `test_authorization_recorder.ProtectionCheck.test_every_unverifiable_state_refuses_and_sends_nothing` | 0.176 |
| `test_authorization_recorder.ProtectionCheck.test_verified_one_merge_by_aieh_owner_and_only_reads_by_the_auditor` | 0.036 |
| `test_live_phases.Prepare.test_a_verifier_that_does_not_verify_at_prepare_sets_the_expected_outcome` | 0.018 |
| `test_live_phases.Prepare.test_the_available_verifier_is_the_command_line_s_protection_check` | 0.003 |
| `test_live_phases.ProtectionCheckEndToEnd.test_drift_refuses_the_record_and_nothing_is_merged` | 0.041 |
| `test_live_phases.ProtectionCheckEndToEnd.test_verified_one_merge_and_the_stale_head_control` | 0.045 |
| `test_live_phases.Record.test_a_refusal_other_than_the_protection_check_s_stops_the_phase` | 0.039 |
| `test_live_phases.Record.test_a_stale_head_control_refused_by_the_protection_check_is_not_reached` | 0.033 |
| `test_live_phases.Record.test_a_stale_head_control_that_merges_is_a_security_failure` | 0.025 |
| `test_live_phases.Record.test_the_stale_head_control_records_the_refusal_it_observes` | 0.077 |
| **Sum** | **0.585** |

Arithmetic: 0.585 s rounded up to a tenth of a second is 0.6 s; the wall becomes 4.0 + 0.6 =
**4.6 s** (`85c2ac7`), and its limit 4.6 × 1.3 = 5.98 s. The new class `ProtectionCheck` also has
a class-level cost outside its tests (class median 0.343 s against 0.304 s in its tests); per the
ruling it is not counted. The owner suite's median in that profile is 5.07 s and 5.10 s in the
`check --run` below, so the raised wall covers the gap; it was not raised further.

**2. The record writer** (`644ec49`, `tools/guest.py`): `write_json_exclusive` writes
`json.dumps(data, indent=2, sort_keys=True) + '\n'` in one call inside the same exclusive create
(mode `'x'`, UTF-8, LF); an existing name is still refused with `FileExistsError`. (One difference
in a failure only: a value json cannot encode now leaves an empty file where the streamed form left
the part written before the error; the exception is the same.) A new test,
`StampedRecords.test_a_record_is_the_bytes_the_streaming_writer_wrote`, writes ten representative
records both ways (empty and nested containers, unsorted keys, non-ASCII text from Latin-1 to an
emoji with a no-break space and U+2028, quotes, backslashes and control characters, large and
negative numbers, a bare string, `null`, the whole Windows profile) and compares the bytes, and
checks that an existing record is refused and left as it was. Writer mutants run against it
(`ensure_ascii=False`, `sort_keys=False`, `indent=1`, no final newline, overwriting, platform
newlines) all fail it. **Measured saving:** across the guest test modules, without a profiler,
238 records took 0.54 and 0.55 s in the writer before and 0.47 and 0.49 s after: about 0.07 s a
run. A 105 KB record: 1.1-1.3 ms streamed, 1.0 ms in one call. Most of the writer's time is the
pure-Python indented encoder, which `json.dumps` with `indent` also runs; the second or more
estimated in section 2 was `cProfile`'s overhead. The tools suite's wall does not show the change
(73.8 s in the three-run profile at `644ec49` against 73.6 s at `1ed7903`).

**3.** `808d96c`'s wrong sentence is recorded in section 3; history is not rewritten.

**Budgets** (`a01c960`, re-proposed from the three-run profile at `644ec49`, serial median 135.7 s):
counters to the new baseline (tests 2466 → 2467, `mkdtemp` 1056 → 1057: the writer's test, in
tools and unit); walls only fall: planning 10.5 → 10.3, lineage 14.0 → 13.9, the integration
category 82.7 → 82.4 s; every other wall kept, the owner wall at 4.6 s.

**Checks at the final code and budgets (`a01c960`):**

- `tools/check_test_budget.py check --run` (three serial runs, `cleanmgr` absent before and after):
  **PASS**. Serial median **136.2 s** (136.92, 136.17, 136.19): 13.8 s under 150 s. Tests 2467, all
  passing or skipped as before (tools 1279 ok and 6 skipped; owner 125 ok and 2 skipped, median
  5.10 s against a limit of 5.98 s); outcomes digest `c3bfbf3595b4` (it changes with the added
  test). Every counter at its budget.
- `python -I tools/verify_seed.py` and `--baseline seed`: PASS.
- `python -I -B tools/publication_gate.py history origin/main..HEAD`: PASS, run after this
  section's commit, which changes this file only.
