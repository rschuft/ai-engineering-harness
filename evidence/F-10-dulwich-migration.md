# F-10: the Dulwich migration of the Python components' repository operations (F-10.5 record)

Plan leaf F-10.5 ("Cross-platform contract run, launch census guard, documentation and evidence")
and the F-10 group record, under
[decision 0014](../decisions/0014-dulwich-adoption-scope-and-repository-access-contracts.md)
(Accepted, amended at F-10.2, F-10.4 and F-10.6). Builder evidence of 2026-11-10; the verdict is
the Overseer's.

**Where this leaf stands.** The census guard, the documentation, the `check_prereqs` line and
this record are done and pass on Windows. **The Linux guest contract run has not been made**: it
carries repository test content into a guest, so decision 0014 section 8 requires the Owner's
approval for that run (Owner action OA-05), and it is not approved. Linux is therefore recorded as
**not verified, pending the Owner-approved guest run (OA-05)**; the exact one-run operation is
prepared for the Overseer to present ([The Linux guest run](#the-linux-guest-run-oa-05)). Without
it the leaf does not pass and the F-10 group gate stays open ([F-10 group proof](#the-f-10-group-proof)).

- **Commits** (local `main`; not pushed):
  - `f219724`: the launch census guard (`tools/tests/test_launch_census.py`), the `check_prereqs`
    INFO line on the tools venv and its tests, `docs/development.md`, the README's component
    status, and the LEDGER's resolver command line;
  - `6ab2cbc`: the census guard's cost reduced (fix forward of `test:budget`'s contract wall,
    [Budgets](#budgets));
  - `b09bd62`: budgets and baseline re-proposed at `6ab2cbc`, counters only;
  - this record.
- **Host:** Windows 11 x86_64 (build 26300), 32 logical CPUs, CPython 3.12.10, Git for Windows
  2.52.0.windows.1, Dulwich 1.2.21 (`cp312-cp312-win_amd64`, with its three Rust extensions) and
  urllib3 2.8.0 in the `python-tools` venv. Task is not installed: each target's command was run
  as `Taskfile.yml` renders it, with `PYTHONDONTWRITEBYTECODE=1`. No guest was started.
- **Raw material** (not committed): the Builder's session scratch directory `c27\`: the census
  helpers (`census_dump.py`, `gitlists.py`, `gitconsts.py`), the budget runs (`bt_gb\` the failing
  run at `f219724`, `bt_gb2\` and `prof_gb2\` the passing run and the baseline's profile at
  `6ab2cbc`, `bt_ps\` and `prof_ps\` PowerShell, `make_budgets.py`), the nine suites (`full\`,
  `final\`), the guest-run preparation (`oa05-plan.md`, `guestrun\`, `wheels\`, `pypi\`,
  `rehearsal\`, `preflight.json`), conformance (`conf\`), `test:all` (`testall\`), the gate
  (`gate\`) and the basic-tier audit (`basic_audit.py`).

## Per-row disposition (decision 0014 section 1)

| Row | Operation | Disposition | Where it runs now | Leaf, commits | Evidence |
|---|---|---|---|---|---|
| R1 | work-tree check | migrated | `open_repository(..., work_tree=True)` behind `planning_adapter.Git` | F-10.3 `bd175bd`, `41f0555` | [F-10.3](F-10.3-planning-migration.md) |
| R2 | revisions and object reads | migrated: the preserved grammar (356 commit forms and 385 object names equal to git 2.52; 34 gap forms refused before any access); every read verified against its id (G9) | `Repository.commit`, `object_kind`, `read`, `blob` | F-10.2 `622bd75`..`3aa5ef3`, `f585e87`; F-10.3 | [F-10.2](F-10.2-repository-module.md), [F-10.3](F-10.3-planning-migration.md) |
| R3 | file lists | migrated | `Repository.files` | F-10.3 | [F-10.3](F-10.3-planning-migration.md) |
| R4 | archive export | migrated: blob bytes (section 4), replacing `git archive` | `Repository.export_tree` | F-10.3 | [F-10.3](F-10.3-planning-migration.md) |
| R5 | exchange push (bundle creation) | migrated: 0 git launches | `write_bundle`, `full_name` in `tools/guest.py:exchange_push` | F-10.4 `46c8d89` | [F-10.4](F-10.4-exchange-snapshots-listing.md) |
| R6 | exchange pull verification | **retained** (gaps G6, G7; git the integrity authority, section 7) | `tools/guest.py:run_git`: `init --bare`, `fetch`, `bundle verify`, `rev-parse`, `fsck --strict` (the verb set asserted by `test_guest`) | F-10.4 | [F-10.4](F-10.4-exchange-snapshots-listing.md) |
| R7 | profile revision | migrated (`host` policy, `config_sources` recorded) | `tools/guest.py:profile_revision` | F-10.4 | [F-10.4](F-10.4-exchange-snapshots-listing.md) |
| R8 | checkout inventory | migrated (`repo-inventory/2`) | `tools/guest.py:repo_inventory` | F-10.4 | [F-10.4](F-10.4-exchange-snapshots-listing.md) |
| R9 | checkout listing for the secret-leak scan | migrated: equal to git's listing on this checkout and 10 ignore-rule repositories | `integrations/gitea/gitea_host.py:checkout_files` | F-10.4 `fb9b25c`, `46c8d89` | [F-10.4](F-10.4-exchange-snapshots-listing.md) |
| R10 | profile revision stamp (development tooling) | migrated (`null` with its reason when unavailable) | `tools/test_profile.py:git_revision` | F-10.4 | [F-10.4](F-10.4-exchange-snapshots-listing.md) |
| R11 | `ls-remote` tag resolution over HTTPS | migrated once G14 was established: the eight locked tags equal the lock, 0 launches | `ls_remote` in `composition/resolve.py` | F-10.6 `53584ef` | [F-10.6](F-10.6-transports.md) |
| H1 | publication-safety gate | **retained** (gap G4; G5, G10) | `tools/publication_gate.py:git` | (unchanged) | decision 0014 section 6 |
| B1 | `verify_seed.py --baseline` | **retained** (bootstrap ordering) | `tools/verify_seed.py:git_reader`, `git_reader.git` | (unchanged) | decision 0014 section 1 |
| B2 | `check_prereqs.py --tier basic` | **retained** (bootstrap ordering) | `tools/check_prereqs.py:basic` | (unchanged; F-10.5 adds an INFO line, no launch) | decision 0014 section 1 |
| T | test fixtures and the git oracle | **retained, by design** (the independent oracle) | 30 sites in 13 test files ([The census guard](#the-launch-census-guard)) | | decision 0014 sections 1 and 8 |
| U1-U4 | upstream git use (Gitea, Backlog.md and OpenSpec, the guest's upstream products, git running the hooks) | untouched | not launch sites in our Python sources (U4 is git itself) | | inventory 1.6 |

**Future uses** (decision 0014 section 1), none built yet: the D-01.1 bot push will use the
module's `Repository.push` (qualified against the host Gitea at F-10.6); the P-04.1
acceptance-recorder commit will use the module's commit, which refuses a repository with client
hooks (section 6; `HOOKS_UNSUPPORTED` for pushes already); the R-02.1.2 backup bundle will use
`write_bundle`, and its verification at restore is of the R6 class (git retained). When they are
built, the census guard holds them: a git launch there fails it until a decision retains it.

## The launch census guard

`tools/tests/test_launch_census.py` (`f219724`, cost reduced in `6ab2cbc`).

**Method.** The tracked `*.py` files are the index's, read in process through the repository
module (no git launched; 93 files at `b09bd62`), each read from the working tree and parsed with
`ast` (never executed, never searched as text). A launch is a call of a standard-library launcher
(`subprocess.run`, `Popen`, `call`, `check_call`, `check_output`, `getoutput`, `getstatusoutput`;
`os.system`, `popen`, `exec*`, `spawn*`, `posix_spawn*`, `startfile`; `asyncio.create_subprocess_*`;
`pty.spawn`), reached through any import form, a name bound to it, or a parameter defaulting to it
(`run=subprocess.run`). A function that launches a program taken from one of its own parameters
is a wrapper (`planning_adapter.run_tree` and `ProcessTree`, `check_prereqs.output`,
`resolve.run`, `gitea_host.run_quiet` ...), and a call of a wrapper is a launch, followed to a
fixed point (a worklist over a callee-name index). The program is git when the argv's first
element, a shell string's first word or `executable=` is a git program: `git`, a path ending in
`git` or `git.exe`, `shutil.which('git')`, a path join or `Path`/`str` of one, or a name,
`self`/`cls` attribute, class attribute or module function return value that is one. A site is
the innermost function holding a git launch.

**What it cannot see** (its docstring): a launcher reached dynamically (`getattr`, a container, a
launcher passed in from another module, `functools.partial`, `eval`/`exec`); a program computed
at run time (read from a file, a record or the environment, as the guest's QEMU argv is, or
assembled from pieces); a wrapper reached by another name (an alias, an inherited method through
a subclass); a git launched by a child process (a hook, an upstream CLI, Dulwich itself) or inside
the guest (Python source held in strings and run over `ssh`); code outside tracked `*.py` files
(the shell hooks, the Taskfile, untracked files). Two blind spots err toward failing: a git argv
passed to any function named like a tree wrapper counts as a launch, and every assignment of a
name counts, whatever the control flow. A site is a function, so a second git launch added inside
an allowlisted function is not a new site (R6's verb set is asserted separately by `test_guest`).

**The allowlist** (`ALLOWLIST`, 35 sites; the guard passes only when the census equals it):

| Site | Row or gap |
|---|---|
| `tools/guest.py:run_git` | R6: `init --bare`, `fetch`, `bundle verify`, `rev-parse`, `fsck --strict` for `verify_pulled_bundle` (gaps G6, G7) |
| `tools/publication_gate.py:git` | H1: the gate's reads of the index, refs, blobs and commits (gap G4) |
| `tools/verify_seed.py:git_reader` | B1: `cat-file --batch` for `verify_seed.py --baseline` |
| `tools/verify_seed.py:git_reader.git` | B1: `rev-parse` for `verify_seed.py --baseline` |
| `tools/check_prereqs.py:basic` | B2: `git --version` and `cat-file -t <seed revision>`, the basic tier |
| `integrations/gitea/tests/test_authorization_live.py:git` | T: the live authorization suite, git as each bot (opt-in) |
| `integrations/gitea/tests/test_gitea_host.py:TestCheckoutFiles.test_the_listing_of_this_checkout_is_gits` | T: oracle of the R9 listing |
| `integrations/gitea/tests/test_transport_live.py:TestClone.test_a_module_clone_passes_git_fsck_strict` | T: oracle of a module clone (opt-in) |
| `integrations/lineage/tests/test_traversal_git.py:OneTraversal.check_against_the_git_oracle`, `git_oracle` | T: oracle of the traversal (through `planning.run_tree` and `ProcessTree`) |
| `integrations/planning/tests/test_git_batch.py:Equivalence._write_ambiguous_blobs`, `Equivalence.one_shot`, `Equivalence.plumbing`, `RealLauncher.start` | T: fixtures, the one-shot oracle, and the `run_tree` launcher test through `cmd\git.exe` |
| `integrations/planning/tests/test_planning_adapter.py:GoldenRepository.ask` | T: oracle |
| `integrations/planning/tests/two_task_fixture.py:git` | T: the planning and lineage fixture builder |
| `integrations/repository/tests/repository_corpus.py:Oracle.run`, `git` | T: the differential suite's git oracle and the corpus builder |
| `integrations/repository/tests/test_repository_oracle.py:OracleAgreement.test_ceilings_are_gits`, `OracleHostFiles.git`, `OracleTransport.git`, `setUpModule` | T: the git oracle and its presence probe |
| `integrations/store/tests/test_backup_restore.py:git` | T: fixture |
| `tools/tests/test_guest.py:Exchange.test_a_dulwich_written_bundle_passes_git_bundle_verify`, `Exchange.test_incremental_bundle_verifies_against_the_pushed_history`, `Exchange.test_the_incremental_pull_launches_only_the_verifiers_verbs`, `Refusals.test_dirty_profiles_refused.git`, `_build_fixture_repo` | T: fixtures and the bundle oracle |
| `tools/tests/test_publication_gate.py:GateRepo.remote_ref`, `GateRepo.run`, `_golden_repositories`, `_golden_repositories.git` | T: the gate's throwaway and golden repositories (git runs the hooks) |
| `tools/tests/test_verify_seed.py:checkout_has_full_history`, `git`, `git_available` | T: fixtures and probes for the B1 tests |

Product sites: 5 (R6 1, H1 1, B1 2, B2 1). Test sites: 30 in 13 files. No site outside decision
0014's retained rows was found, so nothing stopped the leaf here.

**Tests** (12): `TreeCensus` (contract) `test_every_git_launch_site_is_retained_and_every_retained_site_exists`,
`test_the_census_reads_the_tracked_sources`, `test_each_allowlisted_site_names_a_retained_row_of_decision_0014`
(each label's row is one decision 0014 section 1 marks "retain git", read from the decision; T only
under `tests/`), `test_the_guard_fails_on_an_injected_launch_and_on_a_removed_site`; `Detection`
(unit, synthetic sources) for the import forms, the program forms, aliases and injectable
runners, wrappers and their callers, class attributes and path joins, a fixed helper, the
comparison and unparseable sources.

**The injected-failure proof.** On an in-memory copy of the tracked sources (no product file
edited): `integrations/planning/planning_adapter.py` (not allowlisted) gets an appended
`def injected_status(path): return subprocess.run(['git', '-C', str(path), 'status'], ...)`, a new
module `integrations/newcomer/newcomer.py` gets the same, and the gate's `['git', *args]` becomes
`['true', *args]`. The census then differs from the allowlist exactly by the two injected sites
(unexpected; the adapter's at its line, via `subprocess.run`) and the gate's site (missing), and
the guard's verdict function, the one the tree test asserts on, fails naming all three. At
`f219724` the proof ran the tree test itself on those sources; `6ab2cbc` applies the verdict
function to the census made once in `setUpClass`, for cost.

**Cross-checks.**
- Every list or tuple literal starting with a git program, and every `shutil.which('git')`,
  outside a census site was read (`gitlists.py`): data in `test_test_profile` and
  `test_traversal_git`, an expected argv in a mocked `test_guest` test, and `guest.git_binary`
  (used by the R6 site). The broader scan of every git-named string constant (`gitconsts.py`)
  found one missed site, `test_git_batch.RealLauncher.start` (its launcher comes from a classmethod's
  `cls.launcher`, a `Path / 'cmd' / 'git.exe'`); the census was extended to `cls` attributes and
  path joins before the commit, and finds it.
- The dynamic profile agrees: every origin the profiler attributes a git launch to at `6ab2cbc`
  is a census site's file, or a product site reached from a test: `tools/guest.py` 23 (R6's verbs
  only: `init`, `fetch`, `bundle`, `rev-parse`, `fsck`), `<outside>` 15 (`verify_seed.py` run from
  a temporary copy: B1), `planning_adapter.py` 27 (made by `test_traversal_git` and
  `test_git_batch.RealLauncher` through `run_tree`/`ProcessTree`: T sites).

## Measurements

**Launches** (the profile counts launches by the test process; git run by a hook or a child is
not counted):

| | Inventory at `bc9a0f9` (before F-10) | `6ab2cbc` (after) |
|---|---|---|
| All launches per serial run | 1,778 | 1,211 |
| git launches | 1,450 | 885 |
| git launches from product code of the migrated rows (R1-R5, R7-R11) | 838 (R rows; 676 attributed to `planning_adapter.py`, 161 to `guest.py`) | **0** |
| git launches from retained product sites | (B1 15) | R6 23, B1 15 (H1 and B2: not in the counted process) |
| git launches by tests (T) | 597 | 847 (including the 27 made by tests through `run_tree`) |

T grew because the differential suite's git oracle (F-10.2, `repository_corpus.py` 225 at
`6ab2cbc`) and the transport and ignore-rule oracles were added; they are the independent check
the migration is judged by.

**Serial totals** (`task test`'s suites, three-run medians unless noted):

| Shell, revision | Median (runs) | Note |
|---|---|---|
| PowerShell, `bc9a0f9` (inventory) | 145.3 s (one run) | before F-10 |
| Git Bash, `53584ef` (F-10.6 baseline) | 141.95 s | |
| Git Bash, `f219724` (`test:budget`) | 147.6 s (147.6, 147.5, 147.7) | contract wall FAIL (below) |
| Git Bash, `6ab2cbc` (`test:budget`, the new baseline) | **145.0 s** (145.4, 144.9, 145.0) | PASS; the F-09 criterion (at most 150 s, Git Bash) holds |
| PowerShell, `b09bd62` (`test:budget --counters-only`) | 152.8 s (one run) | recorded, not gated (section 10's measurement shell) |
| PowerShell, `b09bd62` (three-run profile) | 152.5 s (152.5, 152.7, 152.4) | recorded, not gated; PowerShell's `git` is the `cmd\git.exe` launcher, about +7 ms per launch (F-10.3) |

**Ratios and wall times carried from the leaves** (Git Bash unless noted):
- Traversal repository access, module against the git oracle interleaved: **11.0 to 11.8x**
  (criterion at least 4x); one-shot resolve **11.0 to 11.6x** (criterion at least 8x); PowerShell
  17.7 to 18.6x and 17.4 to 18.4x ([F-10.3](F-10.3-planning-migration.md)).
- Exchange push of this checkout: module 2,688 ms against git 1,106 ms (a 28.5 MB bundle against
  9.3 MB: no deltas, section 10); of a 2-commit fixture 8.0 against 89.2 ms. Inventory snapshot
  96.0 against 40.8 ms ([F-10.4](F-10.4-exchange-snapshots-listing.md)).
- Import: `planning_adapter` +73.6 ms over `python -c pass` with the module's standard-library
  imports, +105 ms with Dulwich loaded at the first open ([F-10.3](F-10.3-planning-migration.md)).
- Transports: 0 launches in every transport test; G14's eight tags about 0.35 s each
  ([F-10.6](F-10.6-transports.md)).
- The census guard itself: 1.01 s (`TreeCensus`, contract) in the profile at `6ab2cbc`.

## Budgets

**The first `test:budget`** (Git Bash, three runs, at `f219724`, Disk Cleanup not running) **failed
one wall**: `WALL_ABOVE category contract: median 22.21 s, budget 16.9 s, limit 21.97 s`. Every
other contract class was within 0.12 s of the baseline; the guard's two classes cost 2.05 s
(`InjectedLaunch` 1.51 s, `TreeCensus` 0.54 s): the parse of 93 files (about 0.7 s), and the
cyclic collector scanning the growing syntax trees during and after it. Classification:
**introduced-by `f219724`**. Repaired forward in `6ab2cbc` (no wall changed): one contract class
makes both censuses once with the collector off and releases the trees with their cycles broken;
the wrapper search became a worklist; leaf nodes are not descended into. The guard costs 1.01 s
in the profile.

**At `6ab2cbc`** (Git Bash, three runs, Disk Cleanup not running): **PASS**; total 145.0 s;
contract **21.35 s against its 21.97 s limit** (97 % of it); tools 82.5 s, repository 6.1 s.
`b09bd62` re-proposes **counters only** from that profile: tests tools 1,099 to 1,116, unit 1,052
to 1,065, contract 293 to 297, total 1,776 to 1,793; launches (1,211) and mkdtemp (1,006)
unchanged; **no `wall_s` changed**. PowerShell, `--counters-only`, at `b09bd62`: **PASS** with the
same counters.

The contract category now runs at 97 % of its limit on a quiet host. A run on a busy host (Disk
Cleanup has inflated every suite by 10 to 25 % before) is likely to fail it; the leaf did not
change the wall.

## Platforms

| Platform | Dulwich contract suite and components | Basis |
|---|---|---|
| Windows 11 x86_64 | **verified**: the nine suites, the contract suite with its git oracle, under the tools venv (`cp312-cp312-win_amd64`) | this record and the F-10 leaves |
| Linux | **not verified: pending the Owner-approved guest run (OA-05)** | [The Linux guest run](#the-linux-guest-run-oa-05) |
| macOS | **not yet verified** (no Mac available) | decision 0014 section 8 |

Observed on Windows while preparing the guest run, not a Linux result: the contract suite under
the system CPython 3.12.10 with `-I -S` and Dulwich's **pure** wheel imported by zipimport (no
Rust extensions) passes too: with git on `PATH` 96 tests, all `ok`; with git not on `PATH` 81
tests run and the git-oracle module skipped (82 rows; outcomes digest `3673f879…5a57`).

## The Linux guest run (OA-05)

Not run. Prepared for the Overseer to present to the Owner: `c27\oa05-plan.md` (the exact
operation, content, destination, isolation, resource effects, teardown and failure handling) and
the unrun script `c27\guestrun\oa05_run.py`. In brief: one new disposable guest `f105-linux` of
profile `strong-windows-qemu-whpx` (preflight `available` on 2026-11-10, read-only); 8 repository
files (446,127 bytes; manifest sha256 `77a2c901…cd49`) and the two pure wheels (Dulwich
`31a522b9…154f`, urllib3 `0cf3cae5…6e3`, both in the lock) by SFTP into `/srv/scratch/agent/f105`;
the suite under the guest's `python3 -I -S` with the wheels by zipimport; only the report (at most
1 MiB JSON) back through `exchange-pull`; destroy in every outcome, verified. The expected result
is the Windows reference above without git (the image has no git, observed in F-04.1a): 82 rows,
the git-oracle module the one platform-marked skip. Items that would need their own approval (git
in the guest, the manylinux platform wheel as a second pass, any network) are listed in the plan.

## The F-10 group proof

| Clause | Evaluation | Verdict |
|---|---|---|
| Every repository operation of the Python components runs in process through the shared module, except the retained list of decision 0014 | R1-R5 and R7-R11 run on the module (the leaves' evidence); the census finds git launched only at R6, H1, B1, B2 and T sites; the dynamic profile agrees (0 launches from migrated rows) | **met (Windows)** |
| Parity, integrity, revision-grammar, failure-code and performance criteria met | Parity: the differential suite equal to git (1,109 answers over 23 repositories) and the listing equal on 10 ignore-rule repositories; integrity: every read verified, damaged objects `GIT_FAILED`, the R6 verifier unchanged; grammar: 356 commit forms and 385 names equal to git, 34 gap forms refused before access; failure codes: sections 3 and 10; performance: 11.0x and 11.0x against 4x and 8x, budgets kept, the serial median 145.0 s against 150 s | **met (Windows)** |
| The contract suite passes on Windows and on the Linux verification guest with equal ids and outcomes | Windows: passes (96 tests, git oracle included). Linux: the guest run needs the Owner's per-run approval (OA-05), which is not given; not run | **open: Linux not verified** |
| git is launched only at the documented gaps (the launch census guard) | the guard passes on the tree (35 sites, each named with its row) and fails on an injected `subprocess.run(['git', ...])` in a non-allowlisted module | **met** |
| No required test target skips a Dulwich-dependent test | the required targets run under the tools interpreter; the nine suites at `b09bd62` skip 27 tests, none Dulwich-dependent: the env-gated live Backlog.md and OpenSpec tests (13), the opt-in live Gitea tests (7: authorization 4, transport 2, the binary's lifecycle 1), the pytest-runner tests that need the dev venv (4), the gate's nested rerun (1; it runs under `hooks:verify`), one not-applicable executor test and one POSIX-only test; without Dulwich the dependent suites fail with `REPOSITORY_NEEDS_DULWICH` (F-10.2, F-10.3, F-10.6) | **met (Windows)** |
| macOS | not yet verified | recorded |

**The F-10 group does not pass**: its Linux clause is open until the Owner-approved guest run is
made and gives the same ids and outcomes as Windows. F-10.5 does not pass for the same reason.

## Other validation

At `b09bd62` (the code of `6ab2cbc` and its budgets) unless noted; the final revision changes only
this record and one sentence of `docs/development.md`, after which the seed checks and the nine
suites were run again (last rows).

| Check | Command | Result |
|---|---|---|
| Basic prerequisites | `python -I -B tools/check_prereqs.py --tier basic` | PASS; the new INFO line names the tools venv's interpreter |
| Basic tier, standard library and offline | the same under `python -I -S -B` with an audit hook refusing the network (`c27\basic_audit.py`) | exit 0; 0 network attempts; Dulwich not loaded; the only modules loaded outside the standard library are the repository's own `aieh_paths` and `aieh_storecore` (themselves standard-library only) |
| Categories | `<tools python> -I -B tools/test_profile.py categories` | PASS: 298 classes in 46 modules (unit 147, contract 57, integration 80, e2e 13, performance 1) |
| The nine `task test` suites | `<tools python> -I -B -m unittest discover -s <suite> -v`, Git Bash, serially | all OK: tools 1,116 (6 skipped), store 84, effects 34, planning 104 (7 skipped), lineage 146 (6 skipped), paths 38, gitea 93 (8 skipped), dispatch 82, repository 96; 141 s in this plain run |
| `test:budget`, Git Bash | `<tools python> -I -B tools/check_test_budget.py check --run` | `f219724`: FAIL (the contract wall, 22.21 s against 21.97 s); `6ab2cbc`: **PASS**, total median 145.0 s; Disk Cleanup not running in either |
| `test:budget`, PowerShell | `... check --run --counters-only` | **PASS**: 1,793 tests, 1,211 launches, 1,006 mkdtemp (equal to Git Bash); 152.8 s, one run |
| PowerShell serial median | `<tools python> -I -B tools/test_profile.py run --runs 3`, then `check --profile` (recorded, not gated) | median **152.5 s** (152.5, 152.7, 152.4); contract 21.7 s; the repository suite's 8.0 s is above its 7.67 s limit, as PowerShell's launcher made it before (decision 0014 section 10: walls are judged on Git Bash) |
| pytest conformance | dev interpreter: `test_profile.py run --out P`, then `pytest -n auto --maxprocesses 8 --dist loadscope -p no:cacheprovider --aieh-conformance=P` | `CONFORMANCE PASS: 1799 ids, 1793 tests run`; 1,776 passed, 36 skipped |
| `test:all` | `<dev python> -I -B -m pytest -n auto --maxprocesses 8 --dist loadscope -m "not e2e"`, then the Owner host's `npm test -- --no-cache --no-fsModuleCache` (Node 24.19.0) | 1,776 passed, 2 skipped; Vitest 7 files, 43 tests passed |
| `hooks:verify` | `python -I -B tools/publication_gate.py verify`, then `AIEH_GATE_REQUIRE_SCANNER=1 <tools python> -I -B -m unittest discover -s tools/tests -p test_publication_gate.py -v` | PASS; 27 tests OK (test 7's nested whole-suite rerun included), 111 s |
| The guest run's Windows reference | `c27\guestrun\rehearse_windows.py` at `d470ae0` and at `b09bd62` (archive built by `oa05_payload.py` from the commit's blobs) | the archive's sha256 equal at both (`6ba67720…ee00`); without git 81 tests run, digest `3673f879…5a57` at both; with git 96 `ok`, the same 96 ids as the tools-venv run |
| Guest preflight (read-only) | `python -I -B tools/guest.py preflight --profile profiles/strong-windows-qemu-whpx --state-dir D:\aieh-guest-state` | `available`; the image's sha256 equals the pin |
| Seed integrity, final revision | `python -I tools/verify_seed.py` | PASS (165 tasks; 3 ordinary files changed since seed) |
| Seed baseline, final revision | `python -I tools/verify_seed.py --baseline seed` | PASS (136 tasks) |
| The nine suites, final revision | as above | all OK, the same counts and skips as above; 142 s |

## Findings

- **The contract wall exceeded by the census guard** (`test:budget` at `f219724`): introduced-by
  `f219724`; repaired forward in `6ab2cbc`; `test:budget` PASS at `6ab2cbc`. The category keeps
  3 % of headroom on a quiet host.
- **A site the first census missed** (`test_git_batch.RealLauncher.start`, a launcher held in a
  `cls` attribute and joined as a path): introduced-by the first draft of the guard and caught by
  the constant cross-check before any commit; the guard follows `cls` attributes and path joins.
- **The lock's informational `resolver` string** (`composition/lock/components.lock.json`, `python
  -I composition/resolve.py`) is still stale: unrelated-but-detected at F-10.6; it changes with the
  next lock change (the lock is not edited by this leaf). The LEDGER's line is corrected.
- **Stale statements in the development reference** ("no component uses that module yet", the
  module as read-only, the lineage `commit` resolver as "the P-02.1 repository access"):
  exposed-by this leaf's documentation pass; corrected in `f219724` and in this record's commit.
- **`6ab2cbc`'s message** says the tests' assertions are unchanged; the injected-failure test now
  asserts on the guard's verdict function instead of re-running the tree test (above). The
  assertions on the sites and the messages are the same.
- **No arbitrary-file SFTP target** for the guest run: the plan uses guest.py's own `Sftp` helper
  over the same channel (a deviation the plan states, section 10).

## Not verified

- Linux (the guest run, OA-05) and macOS.
- Any target under Task (rendered and run without it).
- The census guard's blind spots (above); git launched inside upstream products (U).
- `test:budget` on a busy host; the contract category's 3 % headroom.
- The pure wheel and the manylinux wheel on Linux (the plan runs the pure wheel; the platform wheel
  is listed for its own approval).
