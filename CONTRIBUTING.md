# Contributing

This guide covers the commands this repository has today, what each one needs,
and where it has actually been run. Anything not run is marked **not yet
verified**. Work is planned in the canonical plan
(`AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json`)
and carried out through the Overseer process described in
[`OVERSEER_START.md`](OVERSEER_START.md).

## Quick start

```
git clone https://github.com/rschuft/ai-engineering-harness
cd ai-engineering-harness
task setup
```

`task setup` is the supported setup command. It checks the basic prerequisites,
verifies the seed in both modes and runs the tool tests. It is offline and takes
seconds. Without Task, run the four commands it wraps:

```
python -I -B tools/check_prereqs.py --tier basic
python -I tools/verify_seed.py
python -I tools/verify_seed.py --baseline seed
python -I -B -m unittest discover -s tools/tests -v
```

Use `python3` instead of `python` outside Windows.

`task qualify` is the full qualification smoke run. It runs `setup`, then the
component prerequisites, then a full component resolution into a new temporary
directory outside the checkout. It needs the component tier and network access,
and took about four minutes on the verification host. It modifies no tracked
file and no upstream project: upstream components are only downloaded,
hash-checked and installed into that directory.

## Tool tiers

| Tier | Needs | For |
|---|---|---|
| Basic development | CPython ≥ 3.12 and git, in a full (non-shallow) clone. [Task](#task) 3.54.0 is an optional convenience. | Seed verification, tool tests, editing docs and tools. |
| Component verification | CPython **3.12** with pip ≥ 23.1, Node.js ≥ 24 with npm ≥ 11, git, and HTTPS access to the registries listed in [`composition/lock/README.md`](composition/lock/README.md). | `composition/resolve.py` (`task resolve`, `task qualify`). |
| Optional inventory | A resolver work directory from `task resolve` or `task qualify`, plus network access to PyPI (metadata) and GitHub and the image registries (SBOM). The SBOM scan downloads its pinned Syft 1.57.0 and Grant 0.7.0 archives itself and checks their sha256 before running them; only Windows x86_64 archives are pinned. Syft and Grant are **not** host prerequisites. | `task inventory`, `task sbom`. |

Later milestones will need more. These are named by plan leaf and are **not
claimed** here: a managed Linux guest VM and its provider (F-03.1, F-03.2.x),
Moby/Docker Engine inside that guest (F-04.1), Gitea (D-01.1, Q-02.x), scanner
tooling such as Grype (G-02.1), and Dulwich for Python Git operations in
adapters (first needed by an adapter that performs Git operations).

Check a tier with `task prereqs`, `task prereqs:components` or
`task prereqs:inventory`, or run `python -I -B tools/check_prereqs.py --tier <basic|components|inventory>`.
The check exits 0 when the tier is met and 1 otherwise. It does not probe the
network.

## Where this has been verified

| Tool or command | Windows 11 x86_64 | Linux via WSL2 (Ubuntu 26.04) | Native Linux | macOS |
|---|---|---|---|---|
| CPython | 3.12.10, as `python` and `py -3` | 3.14.4 (`python3`); no 3.12 present | not yet verified | not yet verified |
| git | 2.52.0.windows.1 | 2.53.0 | not yet verified | not yet verified |
| Task 3.54.0 | release zip, sha256 verified, run from a directory outside the checkout | release tarball, sha256 verified, run from `/tmp` | not yet verified | not yet verified |
| `task setup` | PASS | PASS (under Python 3.14.4) | not yet verified | not yet verified |
| The four raw setup commands | PASS | PASS (under Python 3.14.4) | not yet verified | not yet verified |
| Node.js / npm | 24.19.0 / 11.17.0 | 22.22.1 / 9.2.0: below the component tier | not yet verified | not yet verified |
| `task qualify` (resolver) | PASS: 348 checks, 0 failed, digests equal to the F-01.2 record; about 4 minutes | not met: no CPython 3.12 and no pip; Node 22, npm 9 | not yet verified | not yet verified |
| `task inventory` | PASS: 924 items | not yet verified | not yet verified | not yet verified |
| `task sbom` | PASS with `-- --skip-oci` (host Python and npm, about 6 minutes); the OCI scans are not yet verified through Task | not supported | not yet verified | not yet verified |

The Linux install path for the component sets (inside the F-03/F-04 guest) is
**unknown** until the resolver runs there.

## Supported installation methods

Only what is listed as verified has been exercised.

- **Windows.** CPython 3.12, reachable as `python` (and as `py -3` where the
  Python launcher is installed). Git for Windows. Node.js 24 with npm 11. Task: download
  `task_windows_amd64.zip` from the pinned release, check its sha256 against the
  table under [Task](#task), and run `task.exe` from any directory; it needs no
  installation. Package managers (winget, Scoop, Chocolatey, npm, `go install`)
  are **not yet verified**.
- **Linux via WSL2.** The distribution's own `python3` and `git` were enough for
  the basic tier. The Ubuntu 26.04 packages do not meet the component tier (no
  CPython 3.12; Node 22, npm 9); installing CPython 3.12 and Node 24 there is
  **not yet verified**. Task: `task_linux_amd64.tar.gz`, checked the same way.
- **Native Linux and macOS.** Not yet verified.

### Windows specifics

- **Line endings.** Git for Windows sets `core.autocrlf=true` by default. The
  root [`.gitattributes`](.gitattributes) stores the seeded files verbatim
  (`-text`), and [`composition/.gitattributes`](composition/.gitattributes) keeps
  LF everywhere under `composition/`, so the byte-level checks pass in a fresh
  `core.autocrlf=true` clone. That has been verified. Other files, including
  `Taskfile.yml` and the tool tests, may be checked out with CRLF; they work
  either way.
- **`python` and `py -3`.** The Taskfile calls `python` on Windows and `python3`
  elsewhere. Override it per run: `task setup PYTHON="py -3"`.
- **Console encoding.** `python -I` ignores `PYTHONUTF8` and `PYTHONIOENCODING`.
  The setup commands print ASCII only. If a command's non-ASCII output fails on
  a legacy code page, add `-X utf8` after `-I`.
- **WSL2 is not VM-grade isolation.** The blueprint
  ([`#infrastructure-state`](AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#infrastructure-state))
  treats native WSL2 as an explicitly weaker, trusted-workload option. A
  separately governed Linux VM or host is the strong-security profile. Using WSL
  for these developer commands says nothing about isolating agent workloads.

## Repository commands

| Task target | Command without Task | Network | Result |
|---|---|---|---|
| `setup` | the four commands in [Quick start](#quick-start) | no | Supported setup command. |
| `qualify` | `setup`, then `prereqs:components`, then `resolve` with a new temporary `WORK` | yes | Full qualification smoke run. |
| `prereqs` | `python -I -B tools/check_prereqs.py --tier basic` | no | Exit 0 when met. |
| `prereqs:components` | `python -I -B tools/check_prereqs.py --tier components` | no | Reuses the resolver's own prerequisite check. |
| `prereqs:inventory` | `python -I -B tools/check_prereqs.py --tier inventory` | no | Checks the SBOM scan's host platform. |
| `verify` | `python -I tools/verify_seed.py` | no | Working tree against `SEED_MANIFEST.json`. Needs no git. |
| `verify:baseline` | `python -I tools/verify_seed.py --baseline seed` | no | The original import, strictly, from git history. |
| `test` | `python -I -B -m unittest discover -s tools/tests -v` | no | Tool tests (stdlib `unittest`). |
| `resolve WORK=<dir>` | `python -I composition/resolve.py --work <dir>` | yes | Component lock resolution and host install; see [`composition/lock/README.md`](composition/lock/README.md). `<dir>` must be empty or absent and outside the checkout. |
| `inventory RESOLVED=<work> OUT=<file>` | `python -I composition/inventory/metadata_inventory.py --resolved <work> --out <file>` | yes | Component metadata inventory (declared licences). |
| `sbom RESOLVED=<work> TOOLS=<dir> OUT=<dir> [-- --skip-oci]` | `python -I composition/inventory/scan.py --resolved <work> --tools <dir> --out <dir> [--skip-oci]` | yes | Syft SBOMs and Grant licence findings. Windows x86_64 only. Without `--skip-oci` it downloads the image layers of four OCI images. |

Exit codes: `verify_seed.py` returns 0 PASS, 1 FAIL, 2 could not run;
`resolve.py` returns 0, 1, 2 or 3 as documented in the lock README.

Point `OUT` outside the checkout. For `inventory`, the directory that will
contain `OUT` must already exist. The defaults of `metadata_inventory.py` and
`scan.py` overwrite the tracked evidence under `composition/inventory/`, which
is a reviewed change, not a routine run. `scan.py` exits 0 even when Grant
reports findings; read `scan-manifest.json` and the `grant-*.json` files.

**Licence checks.** `task sbom` runs Grant against Grant's own default
configuration. That is a tool default, not a project policy. **Licence
compliance is not verified**; see
[`composition/inventory/LEDGER.md`](composition/inventory/LEDGER.md) for the open
items.

**Formatting and linting.** No formatter or linter is configured yet.

## Task

The Taskfile targets Task **3.54.0** (release `v3.54.0`, published 2026-10-01,
<https://github.com/go-task/task/releases/tag/v3.54.0>). Checksums come from the
release's `task_checksums.txt` (sha256
`1c81a44f7f5e7c06dd3b696be47c7d10cad26c1a12d0cde780a4114649c5e259`):

| Asset | sha256 | Checked here |
|---|---|---|
| `task_windows_amd64.zip` | `837f42f71899ea41d07a47acc81d4d6ea80cb41c68292345f915c656473efcb7` | downloaded; matches the checksum file and the GitHub asset digest |
| `task_linux_amd64.tar.gz` | `680859dbb4d881a9c72d4d9a8f510825450849af8567deacd7302c01124416fb` | downloaded; matches the checksum file and the GitHub asset digest |
| `task_linux_arm64.tar.gz` | `d7189d439d4a6058e39e1b2acd7c8b27acd4856691b408f23b242e4294e1df5b` | copied from the checksum file; not downloaded |
| `task_darwin_amd64.tar.gz` | `0543b0844a725814c0412d3f4bed12873ce9ed0da207b15775f63a97d734aac0` | copied from the checksum file; not downloaded |
| `task_darwin_arm64.tar.gz` | `12a69fcf37bb8d5bc9150c44f9a936775b73e59ff044c2c245232f198c135637` | copied from the checksum file; not downloaded |

No release signature was verified. Task is optional: every target's command
also runs on its own.

## Repository layout

Directories exist only when they hold real content.

| Path | Holds | Origin |
|---|---|---|
| `composition/` | Component lock, compatibility matrix, resolver, licence/inventory ledger and generated inventory | F-01.1, F-01.2 |
| `decisions/` | Accepted decision records | Overseer |
| `evidence/` | `bootstrap-log.md`: Overseer verdicts until the adopted Work system exists | Overseer |
| `profiles/` | Execution-profile contract, platform-provider matrix and property list; later the profile declarations (F-03.2.1, F-03.3.x) and per-OS packaging (R-03.x) | F-03.1 |
| `task_prompts/` | One Overseer prompt per plan leaf | seed |
| `tools/` | `verify_seed.py`, `check_prereqs.py` and their `tests/` | seed, F-02 |
| repository root | Blueprint, plan and its projections, `task_manifest.json`, `SEED_MANIFEST.json`, `OVERSEER_START.md`, `Taskfile.yml`, this guide | seed, F-02 |

Planned homes are documented here and created by the leaf that first fills them.
That leaf may refine the name with a recorded reason. Upstream sources stay
external (pinned in `composition/`) unless adaptation is necessary.

| Concern | Planned home | Filled first by |
|---|---|---|
| Configuration (Agent Server and service configuration) | `config/` | F-04.1 |
| Integrations (Integration Service adapters and schemas) | `integrations/` | F-05.1, then P-02.1 and E-01.x |
| Policy (principals, permissions, controls) | `policy/` | S-01.1, S-01.2.1, G-01.1 |
| Agent and Skill catalog | `catalog/` | A-01.1, E-03.1 |
| Contract tests | `tests/` | F-03.3.1, S-02.1, E-01.3.2 |

## Changing integrity-tracked files

`tools/verify_seed.py` assigns every path in `SEED_MANIFEST.json` to a class:

| Class | Files | How to change them |
|---|---|---|
| contract | the plan JSON, its HTML and CSV projections, `task_manifest.json`, `task_prompts/`, `tools/verify_seed.py` | Only through a regenerated, reviewed plan (or, for the verifier, a reviewed change), with the manifest hashes updated in the same commit. Any mismatch fails. |
| authority | the blueprint HTML, `OVERSEER_START.md` | Change the file and its `sha256` (and `size_bytes`) in `SEED_MANIFEST.json` in the same commit. Any mismatch fails. |
| ordinary | `README.md`, `CLAUDE.md`, `.gitignore` | Edit freely. The verifier reports them as `INFO: ordinary file changed since seed`. |

A new manifest entry without a class fails, so classify it in the verifier.
`python -I tools/verify_seed.py --baseline seed` checks the original import
strictly at any time, whatever has changed since.

## Security expectations

This is a **public, MIT-licensed** repository.

- Dependencies are hash-locked. Python installs are wheels only, with one
  reviewed sdist exception ([decision 0002](decisions/0002-reviewed-sdist-exception-for-resolution.md)).
  npm runs with `--ignore-scripts`.
- Use throwaway work directories outside the checkout, and run Python tools with
  `python -I` (add `-B` where a module is imported from the checkout).
- Put no credentials in commands, files, or logs. Registry access is anonymous.
- Before each commit and push, review the diff for secrets, personal machine
  paths and private data.
- Third-party code and artifacts keep their own licences; preserve their
  notices.

## How progress is recorded

[`evidence/bootstrap-log.md`](evidence/bootstrap-log.md) holds the Overseer's
verdicts per plan leaf, and [`decisions/`](decisions/) holds accepted decisions.
Both are written by the Overseer; contributors do not edit them as part of
ordinary changes. Task status is not tracked anywhere else.
