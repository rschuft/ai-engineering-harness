# Git use in the Python components, and a measured Dulwich probe

- **Purpose:** facts for the plan amendment that follows the Owner's architectural direction
  on Dulwich (2026-11-08, recorded verbatim in `evidence/bootstrap-log.md`, Decisions). This is
  an inventory and a feasibility probe, not a design. It proposes no leaves.
- **Revision inventoried:** `bc9a0f9` (`main`, equal to `origin/main`), clean tree.
- **Authority read:** blueprint decision card SHIP-02 ("ADOPT Dulwich within Python adapters";
  verification: "Validate supported clone/commit/ref/push/auth operations on target OS and Gitea
  for pinned Dulwich; delegate unsupported operations to upstream clients"), the Repository API
  policy ("use Dulwich in Python-owned adapters for Git objects, refs and transports; prefer each
  adopted product's supported API for its own managed state. Do not install Git CLI solely for
  our integration modules"), `#integration-contracts` ("Our Python adapters require no Git
  executable. Respect capabilities of pinned Dulwich version"), SHIP-03 (Dulwich is dual
  Apache-2.0/GPL; release-time licence gate). No record in `decisions/` covers Dulwich and
  `composition/` pins no Dulwich release (observed). F-09.4's evidence (section 6 and R.5)
  holds the earlier, unmeasured evaluation.
- **Host:** Windows 11 x86_64, 32 logical processors, CPython 3.12.10. Every measurement and
  probe ran from PowerShell, whose PATH holds only Git for Windows' launcher
  `C:\Program Files\Git\cmd\git.exe` (observed with `Get-Command git`).
- **Labels:** **observed** (a command or probe ran and showed it), **source** (read in the
  code named), **inference** (reasoned, not run). Unlabelled table cells are observed or read
  from source as the column says.
- **Raw material** (not in the repository): `…\scratchpad\c12\` holds `scripts\` (probe and
  measurement scripts), `logs\` (outputs: `parity.json`, `bench_rust.json`, `bench_pure.json`,
  `import_time.log`, `launch_attr.txt`, `profile_full.json`, `plan_hits2.txt`), `dl\` (the
  downloaded wheels), `venv\` (the throwaway environment) and `r\` (the throwaway repositories).

## 1. Inventory of git use

### 1.1 Method

- Every tracked `*.py` (81 files, `node_modules` excluded; `git ls-files`) was searched for
  process launches (`subprocess.*`, `Popen`, `os.system`, `os.exec*`, `os.spawn*`) and for
  `'git'`, `run_git`, `git_binary`, `run_tree`, `BatchReader`, `shutil.which`. Each launch site
  was read. `Taskfile.yml` and `.githooks/` were checked for the non-Python side.
- Launch counts come from a fresh `python -I -B tools/test_profile.py run --runs 1` at
  `bc9a0f9`, started from PowerShell with the child's TEMP under `…\scratchpad\c12\t`
  (1,558 tests, all passed; 1,778 launches, equal to the committed
  `evidence/test-profile/baseline.json` measured at `ff355e7`; serial wall 145.3 s). The
  profiler attributes each launch to `program @ calling file`. It counts launches by the test
  process only: git run by a child (a hook, a CLI under test) is not counted.
- Git launches in the profile: **1,450** of 1,778. Product-attributed: 853 (676 from
  `planning_adapter.py`, 161 `guest.py`, 15 `verify_seed.py` run from a temporary copy, 1
  `gitea_host.py`); the rest are test fixtures (section 1.6).

### 1.2 Class counts

| Class | Meaning | Product uses (rows) | Profile launches |
|---|---|---|---|
| R | repository operation in our own adapter | 11 (R1-R11) | 838 |
| H | hooks and the publication-safety gate | 1 Python module (H1, 9 functions) and the shell hooks | 0 counted (runs as a child process) |
| P | publication with real credentials | 0 in product Python today; future D-01.1 | 0 |
| U | upstream products' own git, or git in a guest | 4 | 0 |
| B | bootstrap / basic tier | 2 (B1, B2) | 15 (`verify_seed`, from a copy) |
| T | test fixtures | 13 files | 597 |
| O | other | 0 | 0 |

Nothing needed an Owner or product decision to classify. One row (R11) is a network read
and one (R10) is development tooling; both are noted where they sit.

### 1.3 Repository operations in our adapters (R)

Shared facts for R1-R4 (source, `integrations/planning/planning_adapter.py`): git is launched
as `['git', '-C', <project>, ...]` with `tool_env()` (the caller's environment plus
`GIT_TERMINAL_PROMPT=0`; system and global git configuration apply). Every launch is a
`ProcessTree` (a Windows job object with kill-on-close, the process joined while suspended; a
new session on POSIX), with a 120 s ceiling (`TOOL_TIMEOUT_S`) after which the whole tree is
killed and `subprocess.TimeoutExpired` raised. Within one operation (`operation()`), one
`Git` per project and one batch reader serve every read. Callers: the planning CLI
(`create`, `resolve`, `pointer`), `planning_readiness.read_readiness`,
`dispatch_inputs.PlanningWorkSource.read`, `lineage_resolve` (design, objective, work and
commit resolvers) and `lineage_trace` (project HEAD, archived locations).

| Row | file:function | git subcommand and arguments | Accomplishes | Inputs (paths, revisions) | Outputs consumed | Failure semantics | Tests | Launches |
|---|---|---|---|---|---|---|---|---|
| R1 | `planning_adapter.py:Git.__init__` | `which('git')`; `rev-parse --show-toplevel` | work-tree check | project path (spaces allowed; any subdirectory of a work tree passes; a bare repository or `.git` fails) | exit code only | `CannotRun('git is not on PATH')`, `CannotRun('not a git working tree: …')`; `_open_git` turns these, `OSError` and `TimeoutExpired` into `(None, why)` (`PROJECT_UNAVAILABLE` in lineage) | test_planning_adapter, test_git_batch, test_traversal_git, test_resolvers, test_trace, dispatch tests | 232 `rev-parse` |
| R2 | `planning_adapter.py:BatchReader.read` via `_Session.read`, `Git.commit`, `object_kind`, `object_type`, `blob` | `cat-file --batch` (one long-lived process per operation) | resolve revisions; read commits, trees and blobs | object names: `<revision>^{commit}` (revision = any text without whitespace, C0/DEL or a leading `-`: HEAD, branch, tag, full or short id, `~`/`^` forms all reach git), `<full id>:<path>` (paths with spaces and non-ASCII allowed), full ids | `(oid, type, bytes)` or `None` for `missing`/`ambiguous` | `OBJECT_NAME_INVALID`, `REVISION_INVALID` before any launch; `GIT_FAILED` on an unexpected answer, a process exit or after a timeout (reader fails closed); `TimeoutExpired` per request; `POINTER_REVISION_MISSING`, `POINTER_ARTIFACT_MISSING`, `POINTER_DIGEST_MISMATCH` above it | test_git_batch (protocol, timeouts, launcher trees), test_planning_adapter, lineage and dispatch suites | 263 `cat-file` |
| R3 | `planning_adapter.py:Git.files` | `ls-tree -r -z --name-only <commit> -- <dir>/` | list files under a directory at a commit | full commit id; `openspec/changes`, a change directory (spaces allowed) | NUL-separated names, decoded UTF-8 | `GIT_FAILED` with git's stderr on a non-zero exit; an absent directory gives an empty list | test_planning_adapter, test_traversal_git, lineage suites | 173 `ls-tree` |
| R4 | `planning_adapter.py:Git.archive` | `archive --format=tar <commit> -- <dir>` | export a tree: `openspec` for `openspec_apply_state` (OpenSpec CLI run on the export), `.` for `lineage_resolve` WorkResolver (Backlog.md run on the export) | full commit id; a directory | tar bytes, extracted with `tarfile` `filter='data'` | `GIT_FAILED`; `tarfile.TarError` is `PROJECT_UNAVAILABLE` in lineage | test_planning_adapter.OpenSpecChecklist, test_resolvers.WorkResolution | 7 `archive` |
| R5 | `tools/guest.py:exchange_push` (via `run_git`, `git_ok`) | `rev-parse --git-dir`; `rev-parse --verify --quiet --symbolic-full-name <ref>`; `rev-parse --verify <full>^{commit}`; `rev-list --count <full>`; `bundle create --quiet <file> <full>`; `bundle verify --quiet <file>` | one local branch as a complete bundle for the guest exchange | any repository path outside the state dir; one `refs/heads/` branch; output file under the instance staging dir (deep paths: `core.longpaths=true`) | resolved ref and commit, commit count; the bundle (header parsed and pack trailer recomputed in Python) | `Refused('EXCHANGE', …)` with git's stderr; `Refused('REFUSED'|'BOUNDS'|'BUNDLE', …)` from its own checks; `subprocess.run(timeout=600)` (see 1.7) | test_guest.Exchange | with R6, class Exchange: 54 `rev-parse`, 17 `bundle`, 14 `rev-list` |
| R6 | `tools/guest.py:verify_pulled_bundle` | `init --bare --quiet <vrepo>`; `fetch --quiet --no-tags <bundle> +refs/*:refs/outbound/<n>/*` (prerequisite sources); `bundle verify --quiet <file>`; `fetch --quiet --no-tags <file> +refs/*:refs/pulled/*`; `rev-parse --verify --end-of-options <ref>`; `fsck --strict --no-progress --no-dangling` | verify a bundle pulled from the guest in a fresh bare repository | staging paths (deep) | refs fetched, fsck exit code and output | `Refused('EXCHANGE'|'BUNDLE'|'REFUSED')`; result `verified: False` with the error | test_guest.Exchange | 3 `init`, 3 `fetch`, 2 `fsck` |
| R7 | `tools/guest.py:profile_revision` (local `git()`) | `rev-parse HEAD`; `status --porcelain --untracked-files=all -- profiles` | record the profile revision; refuse a dirty `profiles/` at create | the checkout | HEAD; whether status is empty | `Refused('REFUSED', …)` on a non-zero exit or a dirty tree; no ceiling (see 1.7) | test_guest.Refusals, Smoke, Inventory | with R8: 24 `rev-parse`, 24 `status` |
| R8 | `tools/guest.py:repo_inventory` (local `git()`, used by `smoke` and `inventory`) | `rev-parse HEAD`; `status --porcelain=v2 --untracked-files=no`; `ls-files -s` | evidence snapshot of the checkout | the checkout, `GIT_CONFIG_GLOBAL` set to the null device | HEAD; porcelain v2 lines (recorded verbatim); sha256 and line count of `ls-files -s` | return codes recorded, never raised; `timeout=300` | test_guest.Smoke, Inventory | 20 `ls-files` (and the R7 counts) |
| R9 | `integrations/gitea/gitea_host.py:checkout_files` | `ls-files -z --cached --others --exclude-standard` | list the checkout's tracked and untracked, not ignored files for the secret-leak scan | the checkout | NUL-separated names | `check=True`: `CalledProcessError`; stderr discarded; no ceiling | test_gitea_host.TestCheckoutFiles | 1 `ls-files` |
| R10 | `tools/test_profile.py:git_revision` (development tooling) | `rev-parse HEAD`; `status --porcelain --untracked-files=no` | stamp a profile with revision and dirtiness | the checkout (cwd) | HEAD; dirty flag | `(None, None)` on any failure; `timeout=60` each | test_test_profile (indirect, as a child) | 0 counted (child) |
| R11 | `composition/resolve.py:resolve_sources` (via `run`); `prerequisites` (via `tool_version`) | `-c credential.helper= ls-remote <https url>.git refs/tags/<tag> refs/tags/<tag>^{}`; `git --version` | resolve upstream tag commits over HTTPS, anonymously (component and inventory tiers, network) | public GitHub URLs | ref lines, peeled `^{}` line for annotated tags | checks recorded as failed; `run` has no ceiling; `tool_version` 60 s | none found | 0 (not in the test suites) |

### 1.4 Hooks and the publication-safety gate (H)

`tools/publication_gate.py` (source). Its `git()` helper runs `subprocess.run(['git', *args],
input=…, capture_output=True, timeout=300)` in the hook's working directory and environment
(git sets `GIT_DIR` and, for `git commit -a` or `git commit <paths>`, `GIT_INDEX_FILE`);
failures raise `GateError` (`git <cmd> failed (exit N)` or `could not run`), which blocks.
Tests: `tools/tests/test_publication_gate.py` (runs the gate as hooks of throwaway repositories
and as a CLI; the gate's own git launches are grandchildren and are not counted).

| Function | git subcommands | Purpose |
|---|---|---|
| `is_commit` | `cat-file -e <rev>^{commit}` | does HEAD (or a pushed remote tip) exist |
| `empty_tree` | `hash-object -t tree --stdin` | base for a first commit |
| `staged_items` | `diff-index --cached --raw -z --no-renames <base>` | staged blobs (honours `GIT_INDEX_FILE`) |
| `read_blobs` | `cat-file --batch` (stdin of full ids) | staged or pushed blob bytes |
| `read_config` | `cat-file blob :.gitleaks.toml` (pre-commit, index) / `HEAD:.gitleaks.toml` | the gate's own configuration |
| `commit_items` | `diff-tree -r -z --raw --no-renames --root -m --no-commit-id <c>`; `cat-file commit <c>` | blobs and messages of pushed commits |
| `rev_list`, `pushed_commits` | `rev-list <local> --not <remote>`; `rev-list <local> --not --remotes`; `rev-list --all` (history mode) | commits a push introduces |
| `toplevel` | `rev-parse --show-toplevel` | repository root |
| `mode_install`, `mode_verify` | `config --local core.hooksPath .githooks`; `config --local --get core.hooksPath` | install and verify the hooks |

- `.githooks/pre-commit` and `pre-push` (POSIX sh, run by git) source `gate-common.sh`, which
  runs `git rev-parse --show-toplevel` and then the gate with `python -I -B`.
- Gitleaks never runs git: the gate writes the items to a temporary tree and runs
  `gitleaks dir` on it (source, `run_scanner`).

### 1.5 Bootstrap and basic tier (B)

| Row | file:function | git | Purpose | Failure semantics | Tests | Launches |
|---|---|---|---|---|---|---|
| B1 | `tools/verify_seed.py:git_reader` (integrity-tracked; stdlib only; used by `--baseline REV` only, default mode needs no git) | `rev-parse --git-dir`; `rev-parse --verify --quiet <rev>^{commit}`; `cat-file --batch` with `<commit>:<path>` | read seed files as of a revision | `CannotRun` (exit 2): git unavailable, not a repository, revision unavailable, unexpected output; no ceiling anywhere | test_verify_seed.BaselineMode | 15 (`<outside>`: the tests run a copy) |
| B2 | `tools/check_prereqs.py:basic` (via `output`) | `which('git')`; `git --version`; `git -C <root> cat-file -t <seed commit>` | the basic tier: git present and the seed commit in a full clone | reported FAIL; `timeout=60` | none found | 0 |

### 1.6 Upstream and test use (U, T)

| Row | Where | Class | Note |
|---|---|---|---|
| U1 | Gitea server (`gitea.exe`, started by `gitea_host.py` with the inherited PATH) | U | Gitea runs git for its own repositories (inference from upstream's documented requirement; not probed). Git stays a host prerequisite of Gitea whatever our adapters do. |
| U2 | Backlog.md and OpenSpec CLIs, run by the planning adapter and lineage resolvers | U | Upstream Node tools; whether they run git was not inspected here. |
| U3 | OpenHands Agent Server and the agents' containers in the guest | U | Upstream; the decision 0013 git plane is "proposals leave by exchange". |
| U4 | git itself invoking `.githooks/` | U/H | The hook mechanism is git's; see gap G4. |
| T | `integrations/planning/tests/two_task_fixture.py` (146), `tools/tests/test_publication_gate.py` (232), `integrations/planning/tests/test_git_batch.py` (105, direct `git cat-file`/`rev-parse`/`mktree`/`commit-tree`/`hash-object`), `integrations/store/tests/test_backup_restore.py` (37), `tools/tests/test_verify_seed.py` (25), `integrations/lineage/tests/test_traversal_git.py` (20), `tools/tests/test_guest.py` (19), `integrations/planning/tests/test_planning_adapter.py` (13); without own launches in the profile: `readiness_fixture.py`, `test_resolvers.py`, `test_trace.py`, `test_live_lineage.py` (through `two_task_fixture.git`), `integrations/gitea/tests/test_authorization_live.py` (opt-in live suite: `clone`, `ls-remote`, `fetch`, `checkout`, `add`, `commit`, `commit-tree`, push as each bot through `http.extraHeader` in `GIT_CONFIG_*`, `credential.helper` empty) | T | 597 launches. The plan's F-09.3 action says "Dulwich is not used for fixtures". The live Gitea suite is the only place a push with real (bot) credentials happens today. |

### 1.7 The round-4 launcher finding, checked

Git for Windows' `cmd\git.exe` runs the real git as its child. `subprocess.run(…, timeout=N)`
kills only the launched process and then, on Windows, calls `communicate()` without a ceiling,
which waits for pipes the orphaned real git still holds (source: CPython 3.12
`subprocess.run`). Checked list (source):

| Site | Launch | Verdict |
|---|---|---|
| `tools/guest.py:run_git` | `subprocess.run(timeout=600)` | **confirmed** (timeout kills the launcher only) |
| `tools/guest.py:profile_revision` `git()` | `subprocess.run`, no timeout | **corrected:** no ceiling at all (an unbounded wait), not a timeout-kill |
| `tools/guest.py:repo_inventory` `git()` (smoke, inventory) | `subprocess.run(timeout=300)` | **confirmed** |
| `tools/publication_gate.py:git` | `subprocess.run(timeout=300)` | **confirmed** |
| `tools/test_profile.py:git_revision` | `subprocess.run(timeout=60)` twice | **confirmed** |
| `tools/check_prereqs.py:output` | `subprocess.run(timeout=60)` (git and task) | **confirmed** |
| `integrations/gitea/gitea_host.py:checkout_files` | `subprocess.run(check=True)`, no timeout | **corrected:** no ceiling |
| `tools/verify_seed.py:git_reader` | `subprocess.run` and `Popen(cat-file --batch)`, no timeout; `close()` waits without a ceiling | **corrected:** no ceiling, no kill |
| `composition/resolve.py:run` (`ls-remote`, network) and `tool_version` (`git --version`) | `subprocess.run` without / with `timeout=60` | **added:** `run` has no ceiling; `tool_version` has the timeout-kill pattern |
| `integrations/planning/planning_adapter.py:ProcessTree`, `run_tree`, `BatchReader` | job object / process group | the fixed reference (F-09.4 round 4) |

Inference: a Dulwich read runs in-process and removes these sites for whatever migrates; it
does not remove launches Dulwich itself makes (hooks and SSH, gap G4 and G13).

## 2. The Dulwich probe

### 2.1 Candidate release (PyPI JSON API, 2026-11-09)

- **dulwich 1.2.21**, uploaded 2026-11-05 (four days before this probe; 1.2.20 was uploaded
  2026-10-26), not yanked, "Development Status :: 5 - Production/Stable".
  `License-Expression: Apache-2.0 OR GPL-2.0-or-later` (wheel METADATA; licence file
  `COPYING`). `Requires-Python >=3.10`.
- **Runtime dependencies:** `urllib3>=2.2.2` (unconditional); `typing_extensions>=4.6.0` only
  for Python < 3.12 (none on 3.12). Everything else is an optional extra (`paramiko`, `gpg`,
  `pysequoia`, `fastimport`, `merge3`, `patiencediff`, `aiohttp`, `sha1dc`, …).
- **urllib3 2.8.0** (2026-09-15), `License-Expression: MIT`, one wheel
  `urllib3-2.8.0-py3-none-any.whl`, sha256
  `0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3`.
- **Compiled extensions:** the platform wheels hold three Rust (PyO3) extensions,
  `dulwich/_objects`, `_pack`, `_diff_tree` (observed in the cp312 win_amd64 wheel: `.pyd`
  files containing `pyo3` and `rustc` strings). A pure-Python wheel exists
  (`dulwich-1.2.21-py3-none-any.whl`, 762,744 bytes) and the platform wheels fall back to
  Python code when the extensions are absent (observed, 2.4).

cp312 wheel matrix (PyPI file list; sha256 from PyPI):

| Platform | File | sha256 |
|---|---|---|
| Windows x86_64 | `dulwich-1.2.21-cp312-cp312-win_amd64.whl` | `b3d30d40384cee2e8aa3722f87cef2f3d71717a0b45ac88eba457d62acf65dda` (downloaded and re-hashed: equal) |
| Windows arm64 | `…-cp312-cp312-win_arm64.whl` | `4747b1f94dbbf06e90d49247199db458bd9fefc588a4368669cb551ba4b6439f` |
| Windows x86 | `…-cp312-cp312-win32.whl` | `3206426faf4cb2474458f2dacf5c1b597a076831f2e7afa2a350df5fff2cce1a` |
| Linux x86_64 (glibc >= 2.28) | `…-cp312-cp312-manylinux_2_28_x86_64.whl` | `945278b0f74f83e0f0253aa5ede25f0228b7cca5ca31eb5f5fb76c445c5d5b02` |
| Linux aarch64 (glibc >= 2.28) | `…-cp312-cp312-manylinux_2_28_aarch64.whl` | `a3ac7c2e075b5130ce7055b9278eb1d820cc8196cb07d5480b0dc89499d0357d` |
| macOS arm64 (11.0+) | `…-cp312-cp312-macosx_11_0_arm64.whl` | `93adb787872f330cccf77b50ee41131d9932287725ca00625cd9c346c9ee70b9` |
| macOS x86_64 (10.13+) | `…-cp312-cp312-macosx_10_13_x86_64.whl` | `a7f106746f0596fa07974a5522dfd61d7516721a2ae6ecfdcce6e43f9deb6bd7` |
| any (pure Python) | `dulwich-1.2.21-py3-none-any.whl` | `31a522b9611e8032a43b8fb6941469c24e65ff4f14e0427986c58e90c22e154f` |
| source | `dulwich-1.2.21.tar.gz` | `5d3939f64883e6799614cab708ef4ee9ef415dd6dcad47527cdbb0eea43bf3a2` |

No musllinux wheel is published; there, and on glibc older than 2.28, pip selects the pure
wheel (inference from wheel tags). cp313, cp314 and cp315 (and free-threaded) wheels also exist.

Installation probe (observed): only the cp312 win_amd64 wheel and the urllib3 wheel were
downloaded (`pip download --only-binary :all:`), into their own directory, and installed with
`--no-index --require-hashes --only-binary :all:` into a throwaway venv made by the system
Python under `…\scratchpad\c12\venv`. Nothing was installed into the managed root or the
user site.

### 2.2 Throwaway repositories

Built with git under `…\scratchpad\c12\r\` (fixture git with `GIT_CONFIG_NOSYSTEM`, the
null global config and fixed dates, except the clone): a repository in `a b ü\repo one`
(spaces and non-ASCII in the root; files `openspec/changes/qual 02 spaced/…`,
`docs/ünïcode é.md`, binary data, an `eol=crlf` attribute, an `export-ignore` directory; an
annotated and a lightweight tag; a merge); a gc'd copy (packed refs, one pack, no loose
objects); a bare clone; a linked worktree (`.git` file into `worktrees/`); a
`--separate-git-dir` work tree; a SHA-256 repository; a repository with a 295-character file
path; and a `git clone --no-hardlinks` of this checkout made with the host configuration
(system `core.autocrlf=true`, CRLF work tree). The live checkout's `.git` was only read by
that clone.

### 2.3 Parity results (`…\scratchpad\c12\logs\parity.json`, 149 checks)

**Revision grammar** (git `cat-file --batch-check` against `dulwich.objectspec.parse_object`,
and `rev-parse --verify <rev>^{commit}` against `parse_commit`; loose and packed repositories
gave the same results):

| Form | git | Dulwich 1.2.21 |
|---|---|---|
| `HEAD`, full id, `main`, `refs/heads/main`, `heads/main`, tag names, `refs/tags/v1`, `side` | resolves | same |
| `v1^{}` | peels the tag | same |
| `HEAD~1`, `HEAD^`, `HEAD^2`, `HEAD^^`, `HEAD~1^2`, `main~0` | resolves | same in `parse_object`; **`parse_commit` raises `KeyError`** for `HEAD~1`, `HEAD^2` |
| `HEAD:README.md`, `<id>:<path with spaces>`, `<id>:<non-ASCII path>`, `<id>:<dir>` (tree), `HEAD:` (root tree), `v1:README.md` | resolves | same |
| `HEAD~1:README.md` | resolves | **`KeyError`** (`parse_tree` does not navigate `~`) |
| short id `f65adf3` | resolves | **`KeyError` in `parse_object`**; `parse_commit` resolves it |
| `HEAD^{commit}`, `<id>^{commit}`, `<short>^{commit}`, `HEAD^{tree}` | resolves | **`KeyError`**: `^{commit}` is read as "first parent" followed by the text `{commit}` (source: the `~`/`^` loop of `parse_object`) |
| `v1^{commit}`, `v1^{tag}` | resolves | **`ValueError: … does not have parent #1`** |
| `:README.md` (index), `HEAD@{0}` (reflog) | resolves | same |
| missing name, `deadbeef`, `0`×40, `nope`, `no/such/ref` | `<name> missing` | `KeyError` |

No form returned a wrong object; every divergence raised (observed). The forms our code
writes are `<revision>^{commit}` (R2, R5, B1, H1) and `<id>:<path>` (R2, B1, H1); R2 and the
lineage resolvers pass caller-supplied revision text through to git.

**Other operations:**

| Operation (use) | Result |
|---|---|
| `ls-tree -r --name-only <c> -- <dir>/` (R3): four directories incl. one with spaces, one non-ASCII, one absent | **same** (tree walk with `lookup_path` and `iter_tree_contents`) |
| `archive --format=tar` (R4) | **different.** File contents equal byte for byte except where git converts line endings: git applies `eol` attributes (always) and `core.autocrlf` (the host's system config has `true`, so with the product's environment every text file came out CRLF), Dulwich's `tar_stream` emits blob bytes. Git honours `export-ignore` (Dulwich included `secret/hidden.txt`). Git writes a pax global header with the commit id and directory entries; modes 0664 (git) against 0644 (Dulwich). No pathspec argument: pass a subtree. |
| work-tree check (R1) | `git rev-parse --show-toplevel` accepts any directory inside a work tree, refuses a bare repository and a `.git` directory. `Repo(path)` needs the root and opens bare repositories and `.git` directories (as bare); `Repo.discover(path)` walks up. Linked worktree and `--separate-git-dir` (`.git` file) open correctly. Non-repository: `NotGitRepository`. |
| `GIT_DIR`, `GIT_INDEX_FILE`, `GIT_WORK_TREE` in the environment (H1 runs inside hooks) | git obeys them; Dulwich never reads them (source: `Repo.__init__` takes `controldir=`, `worktree=`, `index_file=`, `object_directory=`). With `index_file=` passed, the staged diff matched git's exactly; reading the environment alone gave the wrong (default) index. |
| staged diff `diff-index --cached --raw -z --no-renames HEAD` (H1) | **same** (`index.changes_from_tree`: added, deleted, modified with ids) |
| `diff-tree -r --raw --no-renames --root -m` on a root and a merge commit (H1) | **same** (`diff_tree.tree_changes` per parent) |
| `rev-list main --not side`, `--count main` (H1, R5) | **same** |
| `rev-list --all` (H1) | same set, **different order** (all commits share one timestamp; tie order differs). Annotated tags must be peeled by the caller. |
| empty tree id (H1) | **same** (`Tree().id`) |
| `status --porcelain --untracked-files=no` on the host-config clone (R7, R8, R10) | **same** (clean: Dulwich applied `core.autocrlf` from the host's system config) |
| status after a modification, an untracked non-ASCII file and an ignored file | same files; git quotes the non-ASCII name (`"new file \303\244.txt"`, core.quotepath), Dulwich returns raw names; porcelain v1/v2 text must be rendered by the adapter |
| `ls-files -z --cached --others --exclude-standard` (R9) | **same** (537 paths; index plus `get_untracked_paths(exclude_ignored=True)`) |
| `ls-files -s` digest (R8) | **same** sha256 for this checkout (no path needed quoting); git quotes special paths, a rendering would have to match |
| bundles (R5, R6) | Dulwich reads a git bundle (v2, refs, prerequisites); a Dulwich-written bundle (`create_bundle_from_repo` + `write_bundle`) passed `git bundle verify`; storing a bundle's objects in a fresh bare repository and setting `refs/pulled/*` worked in process, and `git fsck --strict` of the result passed. No `bundle verify` equivalent: prerequisites and connectivity must be checked by the caller. |
| `porcelain.init`/`add`/`commit` on a path with spaces and non-ASCII | `git fsck --strict` passes. A CRLF file was stored as LF, because Dulwich read `core.autocrlf=true` from Git for Windows' system gitconfig, which it finds through PATH (source: `config.py`; observed `StackedConfig.default_backends()` = the user `.gitconfig` and `C:\Program Files\Git\etc\gitconfig`). |
| writing `core.hooksPath` with `ConfigFile` (H1 install) | **same** (read back by `git config --get`) |
| SHA-256 repository: open, `HEAD:<path>`, `parse_commit(HEAD)` | **same** |
| 295-character file path | listed and read (object reads) |
| repository root longer than MAX_PATH (295 characters) | git fails (`cannot change to …: Filename too long`, also for fixture creation: CreateProcess cannot use such a working directory). Dulwich `init` and `add` succeeded; **`commit` failed**: it launches the pre-commit hook with that directory as cwd and the `NotADirectoryError` is not caught. |
| local transports | `get_transport_and_path`: local path and `file://` give `LocalGitClient` (in process); `https://` `Urllib3HttpGitClient`; `ssh://` and `user@host:path` `SSHGitClient`. `porcelain.clone` of a local repository passed `git fsck --strict`. `ls_remote` of a local path returned refs and symrefs; its result type has no peeled-tag field (`object_format`, `refs`, `symrefs`). |

**Integrity and errors:**

| Case | git | Dulwich |
|---|---|---|
| loose object file whose content hashes to another id | `cat-file -p` printed the other content, exit 0 (no id check on read) | `ChecksumMismatch` on read (stricter) |
| corrupt zlib stream (loose) | exit 128, `inflate: data stream error` | `zlib.error` |
| one flipped byte in a pack | `archive` exit 128 (`incorrect data check`); `fsck` exit 14, pack checksum and CRC mismatch | reading every object: one `zlib.error`; `porcelain.fsck` crashed with `BufferError: cannot close exported pointers exist` |
| `fsck` of the id-mismatch repository | exit 3, `hash-path mismatch` | `porcelain.fsck` reported the same object (`ChecksumMismatch`) |
| missing object, bad revision | `<name> missing` | `KeyError` |
| non-repository | exit 128 | `NotGitRepository` |

Source facts: `porcelain.fsck` only calls `ShaFile.check()` on every object ("TODO: check
pack files / graph / refs" in the source), so it checks neither connectivity nor the pack
checksum, and has no `--strict` equivalent.

**Hooks (source and observed):** Dulwich runs `pre-commit`, `commit-msg` and `post-commit`
from `<controldir>/hooks/` only, with `subprocess.call` (`dulwich/hooks.py`); a missing hook
is a silent `FileNotFoundError`. It never reads `core.hooksPath` (no occurrence in the
package) and has no `pre-push` hook. Observed: each `porcelain.commit` made 3 launch attempts
(`.git\hooks\pre-commit`, `hooks\commit-msg`, `hooks\post-commit`), 1 with `no_verify=True`.

**Authentication (source only; no real remote was contacted):** HTTP(S) through urllib3 with
Basic credentials from the constructor or the URL, an auth callback on 401, proxy Basic
auth, and `http.extraHeader` values from configuration (including `GIT_CONFIG_COUNT`
environment configuration, which `config.py` reads). A `~/.git-credentials` reader exists
(`get_credentials_from_store`) but the client does not call it, and no git credential helper
(Git Credential Manager included) is ever executed (no `credential.helper` handling in the
package). SSH uses an external `ssh` (`SubprocessSSHVendor`), PuTTY `plink`, or the optional
`paramiko` extra; the first two launch a process.

### 2.4 Measurements

Method: one Python process per variant, interleaved repetitions, `time.perf_counter`,
medians (minimum and maximum in the raw JSON); PowerShell PATH (git = the `cmd\git.exe`
launcher); git launched exactly as the product launches it (`planning_adapter.run_tree`,
`BatchReader`). The traversal workload is the F-09.4 benchmark example
(`integrations/lineage/tests/lineage_example.py`, two-task fixture, sample authorities, the
fake Backlog.md in process): one traversal makes 1 work-tree check, 10 batch requests (3 of
the form `<rev>^{commit}`, 7 `<id>:<path>`) and 2 `ls-tree` runs (4 launches, observed; the
projection equals the committed example). The recorded requests were replayed through git
and through Dulwich; the 12 data answers were equal byte for byte.

| Measurement (median) | git | Dulwich, Rust extensions | Dulwich, pure Python |
|---|---|---|---|
| the traversal's git access (git: `Git()` + 1 `cat-file --batch` with 10 requests + 2 `ls-tree`; Dulwich: `Repo.discover` + the same reads + 2 tree walks), n=30 | **76.5 ms** | **10.6 ms** | 10.6 ms |
| whole traversal with git (context), n=30 | 83.8 ms | not measured | not measured |
| one-shot `rev-parse --verify --quiet HEAD^{commit}` via `run_tree` vs `Repo()` + `parse_commit('HEAD')`, n=60 | 17.7 ms | 0.64 ms | 0.64 ms |
| one-shot `ls-tree -r -z --name-only <c> -- openspec/changes/` via `run_tree` vs `Repo()` + subtree walk (equal output), n=60 | 18.0 ms | 1.55 ms | 1.54 ms |
| `Repo(path)` open + close, example repository / clone of this checkout, n=150 | n/a | 0.19 ms / 0.22 ms | 0.19 ms / 0.22 ms |
| every blob of HEAD in the clone of this checkout (536 blobs, 17,884,217 bytes, equal bytes), n=5 | 135.5 ms (one `cat-file --batch`) | 112.2 ms | 110.7 ms |
| import, fresh process, over `python -I -c pass` (21.6 ms), n=30 | n/a | `dulwich.repo` + `objectspec` +55.0 ms; `dulwich.porcelain` +103.7 ms | +53.9 ms |
| import in an already-running process (stdlib loaded) | n/a | 15.7 ms | 15.1 ms |

Inferences, not measured: replacing the traversal's git access would bring one traversal
from about 84 ms to about 18 ms (84 - 76.5 + 10.6). At 17.7 ms per one-shot launch, the 853
product-attributed launches in the suites cost at most about 15 s of the serial run; the 597
fixture launches are untouched (F-09.3: no Dulwich for fixtures). The fresh-process import
cost (55 to 104 ms) is paid by every CLI run and every test child process that imports
Dulwich. The Rust extensions made no measurable difference on these workloads.

## 3. Plan context

Plan JSON searched with Python over every work package's `action`, `artifact`, `proof`,
`adoption` and `notes` (`…\scratchpad\c12\logs\plan_hits2.txt`); verdicts from
`evidence/bootstrap-log.md` at `bc9a0f9`. The plan's own `status` fields are the original
baseline ("Not started" everywhere) and are not progress.

| Leaf | Git or Dulwich content in the plan | Verdict (bootstrap log) | Git use it owns or will add |
|---|---|---|---|
| F-01.1 | (resolver) | PASS 2026-11-06 | R11 `ls-remote` (built) |
| F-02 | adoption: "Dulwich for Python Git operations" | PASS 2026-11-06 | B1, B2 (built with git CLI) |
| F-03.2.2, F-03.3.1, F-03.4 | exchange mounts (F-03.3.1 action) | PASS 2026-11-06 | R5-R8 (built) |
| P-02.1, P-02.2 | (adapter) | PASS 2026-11-07 | R1-R4 (built) |
| P-03.1, P-03.2 | (lineage) | PASS 2026-11-07 | R1-R4 through `lineage_resolve`/`lineage_trace` (built) |
| E-01.2.1 | adoption: "OpenSpec/Git refs" | PASS 2026-11-08 | R1-R2 through `PlanningWorkSource` (built) |
| E-01.2.2 | adoption: "OpenSpec/Git refs" | IN PROGRESS (slice a observed; slice b not started) | reads through E-01.2.1 |
| F-06.1, S-01.2.2 | (Gitea) | PASS 2026-11-07 | R9; the live bot-push test (T) |
| F-09.1 | (profiler) | PASS 2026-11-08 | R10 |
| F-09.3 | action: "Dulwich is not used for fixtures" | PASS 2026-11-09 | constrains T |
| F-09.4 | action/proof: evaluate Dulwich; "outcome is recorded" | PASS 2026-11-09 (Dulwich not adopted within the leaf, R.5) | the batched reader R2 |
| publication-safety gate | Owner-directed, not a plan leaf | operational 2026-11-06 (`9d4c39f`) | H1 |
| P-04.1 | adoption: "OpenSpec change metadata … and Git, in the decision-0008 form" | not started | new: writes acceptance records into OpenSpec metadata in git (inference: a commit) |
| P-04.2 | Gitea API merge with `head_commit_id` | not started | Gitea REST (no local git named) |
| E-02.1 | "exact refs" | not started | reads at exact revisions (inference) |
| E-03.2.1, E-03.3.1, E-03.3.2 | "read-only exact code SHA"; "Gitea REST/Git" | not started | reviewer source snapshot and exact diffs |
| E-04.4 | "Git/Gitea evidence" | not started | exact-SHA evidence reads |
| D-01.1 | proof: "the dispatcher pushes as the stage's bot"; adoption: "Gitea Git hosting + Dulwich as appropriate" | not started | **new P use:** push to Gitea with a bot credential, branch naming, PR creation (REST) |
| D-01.2 | adoption: "Gitea Git hosting + Dulwich as appropriate" | not started | merge policy (Gitea) |
| G-01.1, G-01.2 | "Git policy catalog" | not started | catalog in git |
| G-03.1, G-06.2.1 | protected branch; direct push attempts | not started | push probes (denial tests) |
| G-04.3.1, G-04.3.2 | read the protected ref, merge revision and commit trailers | not started | new reads of commits and trailers |
| K-01.1, K-03.1, K-03.3.1, K-03.3.2 | "OpenSpec/Git revisions" | not started | source-span reads at revisions |
| R-02.1.1, R-02.1.2 | map git repositories; "verified backup bundle" | not started | repository backup (possibly bundles) |

No plan leaf names repository onboarding or clone-from-URL; the blueprint's onboarding
narrative assigns Dulwich "inspection, clone, refs and history operations" (blueprint text),
but no executable leaf carries it (observed by search).

## 4. Compatibility gaps found

Each gap names the operation, the evidence (section 2.3 unless stated) and whether it is a
**hard gap** (Dulwich 1.2.21 cannot do it as our use needs) or a **parity difference** (it can,
with adapter code, and a test can pin the behaviour).

| Gap | Operation and uses | Evidence | Kind |
|---|---|---|---|
| G1 | typed peel `<rev>^{commit}`, `^{tree}`, `^{tag}` (R2, R5, B1, H1) | `parse_object` misreads `^{…}` as parent navigation and raises | parity difference: map `<rev>^{commit}` to `parse_commit(<rev>)` and test it |
| G2 | revision grammar passed through from callers (R2, lineage `reference.revision`) | `parse_commit` lacks `~`/`^`; `parse_object` lacks short ids; `<rev>~N:<path>` fails | parity difference, but the accepted grammar must be fixed by a decision: git accepts every form today, Dulwich's functions each accept a different subset |
| G3 | `archive` export (R4) | no `export-ignore`/`export-subst`, no EOL conversion, no pax commit-id header, no directory entries, other modes; git's own output depends on the host's `core.autocrlf` | parity difference for content; which bytes are the contract (blob bytes or working-tree EOL) needs a decision, since git's current answer varies by host |
| G4 | hooks (H1, any commit made by Dulwich) | no `core.hooksPath`, no `pre-push`; hooks launched with `subprocess.call` (3 attempts per commit even when absent); a hook cwd beyond MAX_PATH raises uncaught `NotADirectoryError` | **hard gap** for the gate's enforcement on Dulwich-made commits and pushes; git's hook mechanism stays where the gate must run |
| G5 | `GIT_DIR`, `GIT_INDEX_FILE`, `GIT_WORK_TREE` (H1 in hooks) | never read from the environment | parity difference: pass `index_file=` etc.; pinned by the probe's equal result |
| G6 | `fsck --strict` (R6) | `porcelain.fsck` checks objects one by one only (no connectivity, pack checksum or strict checks) and crashed on a corrupt pack | **hard gap** for the exchange's strict verification; a replacement needs our own connectivity walk |
| G7 | `bundle verify` (R5, R6) | Dulwich reads and writes bundles git accepts; no verify command | parity difference: prerequisite and connectivity checks in the adapter (the guest code already recomputes the pack trailer) |
| G8 | work-tree check (R1) | `Repo(path)` needs the root and accepts bare repositories; `discover` walks up | parity difference: `discover` plus a non-bare check, pinned by tests |
| G9 | error and integrity semantics (all R) | Dulwich raises `KeyError`, `ChecksumMismatch`, `zlib.error`, `NotGitRepository`, `ValueError`; it verifies object ids on read where `git cat-file` does not | parity difference: map to the existing codes (`GIT_FAILED`, `POINTER_*`, `CannotRun`); stricter reads change one behaviour (a mismatched object now fails) |
| G10 | `rev-list --all` order (H1) | same set, different order on equal timestamps | parity difference: order defined by the caller |
| G11 | porcelain v1/v2 and `ls-files -s` text (R7, R8, R10) | Dulwich returns raw names; git quotes special paths | parity difference: render git's format if the recorded evidence format must stay |
| G12 | configuration discovery (any worktree read or write) | Dulwich reads Git for Windows' system gitconfig only by finding git on PATH; without git installed, system settings (here `core.autocrlf=true`) vanish | parity difference: behaviour changes with git's presence unless the adapter pins its configuration |
| G13 | authentication (P; R11 network) | no credential-helper execution (no Git Credential Manager); Basic, URL credentials, `http.extraHeader` (also via `GIT_CONFIG_*`), callbacks; SSH through an external process or paramiko | **hard gap** for credential-helper-based publication; the bot pattern of the live Gitea test (`http.extraHeader`) is supported in source, not probed live |
| G14 | peeled tags from `ls-remote` (R11) | the result has no peeled field on a local transport; HTTPS not probed (network not authorized) | not established |
| G15 | very long repository roots | git cannot `-C` into a root of MAX_PATH or more; Dulwich can open, init and add there (this host's Python handles long paths), but its commit fails (G4) | mixed; host-dependent |
| G16 | SHA-256 repositories (R2 accepts 64-hex ids) | open, resolve and read: same as git | none found |

## 5. Facts for the basic-tier question

- **What the basic tier uses git for (source):** `tools/check_prereqs.py --tier basic`
  requires git on PATH (`git --version`) and the seed commit in the clone
  (`git cat-file -t <seed>`, "use a full (non-shallow) git clone").
  `tools/verify_seed.py` needs git only for `--baseline REV` (`rev-parse` and
  `cat-file --batch`); its default mode reads the work tree and needs no git. It is
  integrity-tracked (changes only through the documented process) and stdlib-only by design.
  The publication gate needs git as the hook runner: git itself executes `.githooks/`
  (`core.hooksPath`, set by `publication_gate.py install` with `git config`), and the gate
  then reads the index and history with git (H1). Obtaining the repository (a full clone) and
  committing are git operations today (`AGENTS.md`, `docs/development.md`).
- **What a Dulwich dependency would mean (inference, from the facts above):**
  - The basic tier today is "CPython 3.12+ and git, in a full clone", with no package
    installation. Depending on Dulwich adds a hash-locked install step (dulwich and urllib3)
    before `task setup`, into an environment outside the checkout (the F-09.2 dev venv,
    installed by `integrations/paths/tools_install.py`, is the existing precedent).
  - The wheels-only policy can be met on every platform: cp312 wheels exist for Windows
    x86_64/arm64/x86, manylinux_2_28 x86_64/aarch64 and macOS arm64/x86_64, and a pure-Python
    `py3-none-any` wheel covers the rest (musllinux, glibc older than 2.28). urllib3 is a pure
    wheel. No sdist build is needed anywhere.
  - `verify_seed.py` would stop being stdlib-only, which is its stated design, and its change
    needs the Owner's integrity process.
  - Git does not leave the basic tier while the clone is made with git and the gate runs as
    git hooks (G4); Gitea also needs git on the host (U1).
  - Dulwich's behaviour depends on whether git is installed (G12).
- **Licensing (fact):** Apache-2.0 OR GPL-2.0-or-later (dulwich), MIT (urllib3); SHIP-03 keeps
  the release-time licence gate.

## 6. Not established by this probe

- Dulwich on Linux and macOS (only the Windows wheel was installed and run).
- HTTPS and SSH transports, authentication against Gitea, and push (no remote was contacted,
  by the dispatch's rules); peeled tags over HTTPS (G14).
- Whether Backlog.md or OpenSpec run git (U2).
- Behaviour on a host without git installed (G12 is read from source plus the observed
  configuration paths).
