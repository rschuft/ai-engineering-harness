# Development reference

This guide covers the commands this repository has today, what each one needs,
and where it has actually been run. Anything not run is marked **not yet
verified**. It is the technical reference for coding agents and for developers
who want the detail; the contributor workflow is in
[`CONTRIBUTING.md`](../CONTRIBUTING.md) and the instructions shared by coding
agents are in [`AGENTS.md`](../AGENTS.md).

[`Taskfile.yml`](../Taskfile.yml) is the executable source of truth for the
supported repository commands. This guide explains them and gives each one's
direct equivalent; when the two differ, the Taskfile is right and this guide
needs fixing.

Work is planned in the canonical plan
(`AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json`).
The Owner currently carries it out through the Overseer process described in
[`OVERSEER_START.md`](../OVERSEER_START.md); that arrangement is not a
prerequisite for contributing (see
[How work is done here](../README.md#how-work-is-done-here)).

## Quick start

```
git clone https://github.com/rschuft/ai-engineering-harness
cd ai-engineering-harness
task setup
```

`task setup` is the supported setup command. It checks the basic prerequisites and
verifies the seed in both modes, with the standard library only and offline. It then installs
the hash-locked Python tools set (`task tools:install`: PyYAML, Dulwich, urllib3 and keyring, wheels only,
under the [managed data root](#managed-data-root); it downloads from PyPI once per lock and
reuses the verified wheels afterwards), and runs, under that set's interpreter, the tool tests, the integration store
tests, the effects store tests, the planning adapter tests, the lineage tests, the Owner decision recorder tests, the managed data root tests, the lifecycle contract and platform adapter tests, the credential provider tests, the host Gitea tests, the dispatch tests (input resolution, create admission and the native conversation create) and the repository-access contract tests. The tests run serially; the whole of `setup` took 156 s from PowerShell on the verification host at F-10.1, with the tools set already downloaded ([Testing](#testing) has the measurements). Before your first commit, also run
`task hooks:install` once per clone
(see [Publication-safety gate](#publication-safety-gate)). Without Task, run the sixteen commands it wraps:

```
python -I -B tools/check_prereqs.py --tier basic
python -I tools/verify_seed.py
python -I tools/verify_seed.py --baseline seed
python -I -B integrations/paths/tools_install.py
<tools python> -I -B -m unittest discover -s tools/tests -v
<tools python> -I -B -m unittest discover -s integrations/store/tests -v
<tools python> -I -B -m unittest discover -s integrations/effects/tests -v
<tools python> -I -B -m unittest discover -s integrations/planning/tests -v
<tools python> -I -B -m unittest discover -s integrations/lineage/tests -v
<tools python> -I -B -m unittest discover -s integrations/owner/tests -v
<tools python> -I -B -m unittest discover -s integrations/paths/tests -v
<tools python> -I -B -m unittest discover -s integrations/platform/tests -v
<tools python> -I -B -m unittest discover -s integrations/credentials/tests -v
<tools python> -I -B -m unittest discover -s integrations/gitea/tests -v
<tools python> -I -B -m unittest discover -s integrations/dispatch/tests -v
<tools python> -I -B -m unittest discover -s integrations/repository/tests -v
<tools python> -I -B -m unittest discover -s integrations/inference/tests -v
```

`<tools python>` is the interpreter that `python -I -B integrations/paths/tools_install.py
--python` prints: the `python-tools` venv for the current lock. That command creates nothing
and exits 1 when the set is not installed. Use `python3` instead of `python` outside Windows.

`task qualify` is the full qualification smoke run. It runs `setup`, then the
component prerequisites, then a full component resolution into a new temporary
directory outside the checkout, then the release run of the tests (`dev:install`,
`test:all` and `hooks:verify`; see [Testing](#testing)). It needs the component tier,
network access and the installed publication-safety gate; its resolution took about four
minutes on the verification host. It modifies no tracked
file and no upstream project: upstream components are only downloaded,
hash-checked and installed into that directory.

## Tool tiers

| Tier | Needs | For |
|---|---|---|
| Basic development | CPython ≥ 3.12 and git, in a full (non-shallow) clone. [Task](#task) 3.54.0 is an optional convenience. | Seed verification (`check_prereqs.py --tier basic`, `verify_seed.py` in both modes) and the [publication-safety gate](#publication-safety-gate): standard library only, offline. Editing docs and tools. |
| Python tools set | The basic tier, plus HTTPS access to PyPI (pypi.org, files.pythonhosted.org) once per lock for `task tools:install`, which `task setup` runs. | `task test` and `task setup`'s tests, which run under the set's interpreter; `config.yml` (PyYAML); the Python components' repository operations (Dulwich 1.2.21 and urllib3 2.8.0, plan group F-10). |
| Product runtime: the tools venv | The Python tools set installed for the current lock (`task tools:install`). `check_prereqs.py --tier basic` reports its interpreter, or that it is not installed, as information only. | The Python components read and write git repositories in process over Dulwich, through the shared [repository-access module](#repository-access): planning, lineage and dispatch, the guest exchange push and checkout snapshots, the Gitea checkout listing, the test profiler's revision stamp and the resolver's source tags. Their targets run under `<tools python>`; under an interpreter without Dulwich they stop with `REPOSITORY_NEEDS_DULWICH`, with no git fallback. git is launched only at the sites [decision 0014](../decisions/0014-dulwich-adoption-scope-and-repository-access-contracts.md) section 1 retains (the exchange verifier, the publication-safety gate, the basic-tier checks and the test fixtures), held by the [launch census guard](#repository-access). |
| Component verification | The Python tools set (its interpreter, CPython **3.12** with pip ≥ 23.1, runs the resolver; its Dulwich reads the source tags, F-10.6), Node.js ≥ 24 with npm ≥ 11, and HTTPS access to the registries listed in [`composition/lock/README.md`](../composition/lock/README.md). git is not needed by the resolver. | `composition/resolve.py` (`task resolve`, `task qualify`). |
| Optional inventory | A resolver work directory from `task resolve` or `task qualify`, plus network access to PyPI (metadata) and GitHub and the image registries (SBOM). The SBOM scan downloads its pinned Syft 1.57.0 and Grant 0.7.0 archives itself and checks their sha256 before running them; only Windows x86_64 archives are pinned. Syft and Grant are **not** host prerequisites. | `task inventory`, `task sbom`. |

Later milestones need more tools and environments than these tiers cover, such
as managed execution guests and the services that run in them, Gitea, scanner
tooling such as Grype. Dulwich, for the Python components' Git operations, is pinned in the
Python tools set (plan leaf F-10.1); the shared [repository-access module](#repository-access) is
built over it (F-10.2), and the components of the product-runtime row use it (F-10.3, F-10.4,
F-10.6). The
Windows reference guest profile has its own provider prerequisites in
[`profiles/strong-windows-qemu-whpx/PREREQUISITES.md`](../profiles/strong-windows-qemu-whpx/PREREQUISITES.md).
This guide does not record whether any of them is verified. That is recorded in
the evidence: the [bootstrap log](../evidence/bootstrap-log.md),
[`evidence/`](../evidence/) and each profile's `QUALIFICATION.md`.

The basic-tier checks stay standard-library only and offline: `check_prereqs.py --tier basic`,
`verify_seed.py` in both modes and the publication-safety gate import nothing outside the
standard library and use no network (shown with `python -I -S` and no network in
[`evidence/F-10.1-dulwich-pins.md`](../evidence/F-10.1-dulwich-pins.md)), and the Taskfile runs
them with the plain `PYTHON`. Everything that needs a package uses the Python tools set:
`task tools:install` installs PyYAML (for the optional `config.yml`, [Managed data
root](#managed-data-root)), Dulwich and urllib3, and keyring with its dependencies (the credential
provider on Linux and macOS, plan leaf F-06.3; never instantiated on Windows) from PyPI, hash-locked and wheels only
([`composition/lock/python/tools-requirements.txt`](../composition/lock/python/tools-requirements.txt)),
into a venv under the managed data root, and `task setup` and `task test` run the test suites
under that venv's interpreter ([decision 0014](../decisions/0014-dulwich-adoption-scope-and-repository-access-contracts.md)
section 9).

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
| `task setup` | PASS. Since F-10.1 (`tools:install`, then the tests under the tools interpreter) its commands PASS, rendered from the Taskfile and run from PowerShell and Git Bash; not yet run under Task | PASS before F-10.1 (under Python 3.14.4); not yet verified since | not yet verified | not yet verified |
| `task tools:install`, `task dev:install` (Dulwich 1.2.21, urllib3 2.8.0, keyring 25.7.0 and its closure) | PASS: hash-locked, wheels only; Dulwich from its `cp312-cp312-win_amd64` wheel; keyring and its Windows closure from `py3-none-any` wheels, the Linux-only packages skipped by their markers ([F-06.3](../evidence/F-06.3-credential-provider.md)) | not yet verified | not yet verified | not yet verified |
| Dulwich repository access: the differential contract suite (`repository:test`) | PASS: every test, the git-oracle half included (git 2.52.0.windows.1), under the tools venv | not yet verified | pending: one run in the disposable Debian 13 verification guest (profile `strong-windows-qemu-whpx`), which needs the Owner's approval for that run ([decision 0014](../decisions/0014-dulwich-adoption-scope-and-repository-access-contracts.md) section 8) | not yet verified |
| Dulwich in the components (planning, lineage, dispatch, the guest exchange push and snapshots, the Gitea listing, the resolver's source tags) and the launch census guard | PASS (`task test` under the tools venv; git launched only at the retained sites) | not yet verified | not yet verified | not yet verified |
| The four raw setup commands | PASS | PASS (under Python 3.14.4) | not yet verified | not yet verified |
| Node.js / npm | 24.19.0 / 11.17.0 | 22.22.1 / 9.2.0: below the component tier | not yet verified | not yet verified |
| `task qualify` (resolver) | PASS: 348 checks, 0 failed, digests equal to the F-01.2 record; about 4 minutes | not met: no CPython 3.12 and no pip; Node 22, npm 9 | not yet verified | not yet verified |
| `task inventory` | PASS: 924 items | not yet verified | not yet verified | not yet verified |
| `task sbom` | PASS with `-- --skip-oci` (host Python and npm, about 6 minutes); the OCI scans are not yet verified through Task | not supported | not yet verified | not yet verified |
| Host service `install` (Gitea) | PASS: the live instance (F-06.1); a fixture instance in the live lifecycle test ([F-06.2](../evidence/F-06.2-platform-windows.md)) | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Host service `up`, `down` | PASS: a fixture instance, including a hard kill of the supervisor ending Gitea through the Job Object ([F-06.2](../evidence/F-06.2-platform-windows.md)); the live instance runs since F-06.1 | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Host service `restart` | PASS: a fixture instance ([F-06.2](../evidence/F-06.2-platform-windows.md)) | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Host service `status` | PASS: the live instance, output byte-identical before and after F-06.2 ([F-06.2](../evidence/F-06.2-platform-windows.md)) | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Host service `inspect` | PASS: the live instance (read-only) and a fixture instance ([F-06.2](../evidence/F-06.2-platform-windows.md)) | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Host service `verify` and its `aieh-readiness/1` record | PASS: the live instance, output byte-identical before and after F-06.2; the readiness record carries the platform ([F-06.2](../evidence/F-06.2-platform-windows.md)) | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Credential `provision` | PASS on the live instance in F-06.1 and S-01.2.2 (`identities`, `gitea:roles -- provision`); since F-06.2 fakes only | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Credential `rotate` | PASS on the live instance in F-06.1 section 8 and S-01.2.2 (`finalize-credentials`, `gitea:roles -- rotate`); since F-06.2 fakes only; its integration-store receipt, written and read back, with fakes and a fixture store only ([F-06.3](../evidence/F-06.3-credential-provider.md)) | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Credential `retire` | fakes only: not yet verified against Gitea; its integration-store receipt, written and read back, with fakes and a fixture store only ([F-06.3](../evidence/F-06.3-credential-provider.md)) | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Host service `upgrade` | fixture assets and fakes only (one version is pinned): not yet verified; rehearsal in F-06.6 | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Host service `recover` | PASS: a fixture instance (an interrupted restart resumed) ([F-06.2](../evidence/F-06.2-platform-windows.md)); upgrade recovery with fakes only | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Host service `uninstall` | PASS: a fixture instance (refused while running; persistent state and the asset kept) ([F-06.2](../evidence/F-06.2-platform-windows.md)) | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Credential provider: Windows Credential Manager (ctypes) | PASS: the live entries (S-01.2.2), read by `gitea:authz` ([F-06.2](../evidence/F-06.2-platform-windows.md)), and again after its move to `integrations/credentials/` behind the factory ([F-06.3](../evidence/F-06.3-credential-provider.md)); the provider contract suite over an in-memory advapi32; `CREDENTIAL_PROVIDER_LOCKED` with fakes only; the real-store cross-read is opt-in and not yet run | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Credential provider: keyring (Secret Service, macOS Keychain) | kept off the Windows provider (never instantiated there). Installed in the tools set and exercised in process ([F-06.3](../evidence/F-06.3-credential-provider.md)): the provider contract suite with an in-process backend, the cross-read across processes with a test-only backend, and `SecretService.Keyring()` and `macOS.Keyring()` instantiated explicitly and refused as not viable on Windows | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| Credential provider factory, its refusals and `credentials:doctor` | PASS: Credential Manager chosen without importing keyring; `NO_CREDENTIAL_PROVIDER` for every unqualified case; keyring's own selection and configuration shown ignored; `doctor` reports the provider and its viability and touches no entry ([F-06.3](../evidence/F-06.3-credential-provider.md)) | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| `credentials:test` | PASS under the tools venv ([F-06.3](../evidence/F-06.3-credential-provider.md)) | not yet verified (F-06.4) | not yet verified (F-06.4) | not yet verified (F-06.5) |
| The inference broker and `inference:test` | PASS offline under the tools venv: synthetic keys, an in-memory credential provider, a fixture integration store and fake upstreams on ephemeral 127.0.0.1 ports inside the test process ([S-03.2 slice 1](../evidence/S-03.2-slice1-broker-core.md)). Not yet verified: the broker run as a host service, its real listeners, the real credential entry, TLS to a provider and any model call (each its own Owner act); the qualification tools of slice 4 (the launcher, the fake upstream, `inference_control.py issue`) outside the test process; the provider-key containment search of slice 5 ([record](../evidence/S-03.2-slice5-key-containment-search.md)) against a live broker, guest or instance directory | not yet verified | not yet verified | not yet verified |
| The acceptance recorder (`owner:accept`) and `owner:test` | PASS on throwaway fixture repositories with synthetic statements, under the tools venv ([P-04.1](../evidence/P-04.1-acceptance-recorder.md)); no real Owner acceptance recorded; not run under Task | not yet verified | not yet verified | not yet verified |
| The authorization recorder (`owner:authorize`) | PASS against a fake Gitea only, in memory and over an in-process loopback HTTP server, with a fixture credential provider and synthetic statements ([P-04.2](../evidence/P-04.2-authorization-recorder.md)); it fails closed: `record` refuses `PROTECTION_UNVERIFIED` unless the protection check of decision 0012 point 6 (OA-16; [record](../evidence/P-04.2-protection-verifier.md)) answers `verified`, and its auditor is not provisioned, so it merges nothing yet; the two-phase live exercise on the S-01.2.2 fixture is opt-in and not yet run; no real Owner authorization recorded; not run under Task | not yet verified | not yet verified | not yet verified |

The host-service rows follow the lifecycle contract of plan leaf F-06.2 (draft decision 0011): one row
per verb and per credential provider. A platform counts as supported only with its own evidence
record; every result names its OS.

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
  root [`.gitattributes`](../.gitattributes) stores the seeded files verbatim
  (`-text`), [`profiles/.gitattributes`](../profiles/.gitattributes) stores the profile
  directories and seed templates verbatim (`-text`: everything pinned by sha256 under
  `profiles/`, including the netprobe probe), and
  [`composition/.gitattributes`](../composition/.gitattributes) keeps LF everywhere
  under `composition/`, so the byte-level checks pass in a fresh
  `core.autocrlf=true` clone. That has been verified (for `profiles/`, again in F-03.4). Other files, including
  `Taskfile.yml` and the tool tests, may be checked out with CRLF; they work
  either way.
- **`python` and `py -3`.** The Taskfile calls `python` on Windows and `python3`
  elsewhere. Override it per run: `task setup PYTHON="py -3"`.
- **Console encoding.** `python -I` ignores `PYTHONUTF8` and `PYTHONIOENCODING`.
  The setup commands print ASCII only. If a command's non-ASCII output fails on
  a legacy code page, add `-X utf8` after `-I`.
- **WSL2 is not VM-grade isolation.** The blueprint
  ([`#infrastructure-state`](../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#infrastructure-state))
  treats native WSL2 as an explicitly weaker, trusted-workload option. A
  separately governed Linux VM or host is the strong-security profile. Using WSL
  for these developer commands says nothing about isolating agent workloads.

## Repository commands

| Task target | Command without Task | Network | Result |
|---|---|---|---|
| `setup` | the sixteen commands in [Quick start](#quick-start) | yes (PyPI, once per lock: `tools:install`) | Supported setup command: the basic-tier checks (offline), then `tools:install` and `test` under the tools interpreter. |
| `qualify` | `setup`, then `prereqs:components`, then `resolve` with a new temporary `WORK`, then `dev:install`, `test:all` and `hooks:verify` | yes | Full qualification smoke run, and the release run of the tests: the parallel runner, the Owner host's Vitest tests when Node.js 24 or later is present, and the gate's nested whole-tool-suite rerun. Needs the [publication-safety gate](#publication-safety-gate) installed. |
| `prereqs` | `python -I -B tools/check_prereqs.py --tier basic` | no | Exit 0 when met. |
| `prereqs:components` | `python -I -B tools/check_prereqs.py --tier components` | no | Reuses the resolver's own prerequisite check. |
| `prereqs:inventory` | `python -I -B tools/check_prereqs.py --tier inventory` | no | Checks the SBOM scan's host platform. |
| `verify` | `python -I tools/verify_seed.py` | no | Working tree against `SEED_MANIFEST.json`. Needs no git. |
| `verify:baseline` | `python -I tools/verify_seed.py --baseline seed` | no | The original import, strictly, from git history. |
| `test` | `<tools python> -I -B -m unittest discover -s tools/tests -v`, then `store:test`, `effects:test`, `planning:test`, `lineage:test`, `owner:test`, `paths:test`, `platform:test`, `credentials:test`, `gitea:test`, `dispatch:test`, `repository:test` and `inference:test`, each of which runs under `<tools python>` too (`<tools python>`: what `python -I -B integrations/paths/tools_install.py --python` prints) | no | Tool tests, integration store tests, effects store tests, planning adapter tests, lineage tests, Owner decision recorder tests, managed data root tests, lifecycle contract and platform adapter tests, host Gitea tests, dispatch resolution and admission tests, repository-access contract tests and inference broker tests (stdlib `unittest`), all under the Python tools set's interpreter, so that PyYAML and Dulwich are present. Needs `tools:install` (which `setup` runs); fails, naming it, otherwise. |
| `test:profile [-- --runs N --out FILE --compact-out FILE --suite NAME]` | `<tools python> -I -B tools/test_profile.py run [options]` | no | [Testing](#testing): profiles the `test` suites serially, under the tools interpreter, and counts each test's and class's process launches, temporary directories, sockets and `chdir` calls, by category and suite; writes the profile to a new temporary directory. Exit 0 PASS, 1 FAIL, 2 could not run. |
| `test:categories [-- --list]` | `<tools python> -I -B tools/test_profile.py categories [--list]` | no | Checks that every test class declares a valid category, under the tools interpreter: the test modules it imports need the Python tools set (the credential provider tests import keyring). Imports the test modules; runs no test. Needs `tools:install`. |
| `dev:install` | `python -I -B integrations/paths/tools_install.py --set python-dev-tools` | yes (PyPI) | Installs the hash-locked dev tools venv (pytest, pytest-xdist and their dependencies, and the Python tools set: PyYAML, Dulwich, urllib3 and keyring with its closure, with the tools lock's hashes, [`composition/lock/python/dev-requirements.txt`](../composition/lock/python/dev-requirements.txt)), wheels only, under the managed data root; prints its interpreter. `--set python-dev-tools --python` prints that interpreter for the current lock, creating nothing, and exits 1 when it is not installed. Not part of `setup`. |
| `test:unit [-- ARGS]` | `PYTHONDONTWRITEBYTECODE=1 <dev python> -I -B -m pytest -n auto --maxprocesses 8 --dist loadscope -m unit [ARGS]` | no | [Testing](#testing): the inner loop, the `unit` tests in parallel under the unit guard. Needs `dev:install`. |
| `test:fast [-- ARGS]` | the same with `-m "unit or contract"` | no | The inner loop: `unit` and `contract` tests in parallel. |
| `test:component [-- ARGS]` | the same with `-m "contract or integration"` | no | The boundary: `contract` and `integration` tests in parallel. |
| `test:all [-- ARGS]` | the same with `-m "not e2e"`, then `owner-host:test:if-node` | no | Every suite of `test` but the live `e2e` classes, in parallel on at most 8 processes, then the Owner host's Vitest tests when Node.js 24 or later is present. Needs `dev:install` (and `owner-host:install` with Node.js 24). |
| `test:budget [-- --counters-only]` | `<tools python> -I -B tools/check_test_budget.py check --run [--counters-only]` | no | **Acceptance obligation** at every leaf acceptance and release, never in a hook: profiles three serial runs under the tools interpreter and checks them against [`policy/test-budgets.json`](../policy/test-budgets.json). Exit 0 PASS, 1 FAIL, 2 could not run. |
| `store:test` | `<tools python> -I -B -m unittest discover -s integrations/store/tests -v` | no | [Integration store](#integration-store) tests: real processes against one SQLite file, including crash, restart and concurrent-admission races; about fifteen seconds. |
| `store:init DB=<path>` | `python -I -B integrations/store/integration_store.py init --db <path>` | no | Creates or migrates the integration store at an explicit path and prints a JSON summary. Idempotent. |
| `store:path` | `python -I -B integrations/store/integration_store.py default-path` | no | Prints the default trusted-host store location. Creates nothing. |
| `store:backup DB=<path> ACTOR=<name>` | `python -I -B integrations/store/integration_store.py backup --db <path> --actor <name>` | no | Backs the integration store up with the SQLite backup API into `<db dir>/backups/`, checks the copy and prints its manifest. |
| `store:restore DB=<path> MANIFEST=<file> ACTOR=<name> [-- --accept-rollback]` | `python -I -B integrations/store/integration_store.py restore --db <path> --manifest <file> --actor <name> [--accept-rollback]` | no | Restores a verified backup and opens a restore epoch. Refuses a rollback unless accepted; keeps the superseded store in `backups/superseded/`. |
| `effects:test` | `<tools python> -I -B -m unittest discover -s integrations/effects/tests -v` | no | [Effects store](#effects-store) tests: crash, backup and restore, custody and location refusals on fixtures; a few seconds. |
| `effects:init ROOT=<dir> [-- --principal SID]` | `python -I -B integrations/effects/effects_store.py init --root <dir> [--principal SID]` | no | Creates or migrates `effects.sqlite` inside an existing, Owner-created root after the location and custody checks. Never creates the root. |
| `effects:backup ROOT=<dir> ACTOR=<name>` | `python -I -B integrations/effects/effects_store.py backup --root <dir> --actor <name>` | no | Backs the effects store up into `<root>/backups/` and prints the manifest. |
| `effects:restore ROOT=<dir> MANIFEST=<file> ACTOR=<name> [-- --accept-rollback]` | `python -I -B integrations/effects/effects_store.py restore --root <dir> --manifest <file> --actor <name> [--accept-rollback]` | no | The Owner's elevated act, with the executor stopped: restores a verified backup and opens a restore epoch. |
| `effects:verify-chain ROOT=<dir>` | `python -I -B integrations/effects/effects_store.py verify-chain --root <dir>` | no | Verifies the journal's hash chain and every receipt; prints the chain head. |
| `planning:test` | `<tools python> -I -B -m unittest discover -s integrations/planning/tests -v` | no | [Planning adapter](#planning-adapter) tests: offline with a fake Backlog.md and git. The live tests against the pinned Backlog.md and OpenSpec run only when `AIEH_BACKLOG` and `AIEH_OPENSPEC` name their entry points, and are skipped otherwise. |
| `planning:create PROJECT=<repo> PLAN=<file> REVISION=<rev> BACKLOG=<cmd> [-- --openspec <cmd>]` | `<tools python> -I -B integrations/planning/planning_adapter.py create --project <repo> --plan <file> --revision <rev> --backlog <cmd> [--openspec <cmd>]` | no | Creates a plan's Backlog.md tasks and their dependencies through `backlog task create`; each task carries OpenSpec source pointers at the exact design revision. Refuses a change with a `tasks.md` or a tracked schema, and any status. Exit 0 PASS, 1 FAIL, 2 could not run. Since F-10.3 it reads the repository through the shared repository-access module (Dulwich), so the target runs it under the tools interpreter, as the test targets do; under an interpreter without Dulwich it fails with `REPOSITORY_NEEDS_DULWICH`. |
| `planning:readiness PROJECT=<repo> BACKLOG=<cmd> [-- --task ID --no-pointers]` | `<tools python> -I -B integrations/planning/planning_readiness.py --project <repo> --backlog <cmd> [--task ID ...] [--no-pointers]` | no | Reports Backlog.md's own readiness per task (P-02.2): eligible only when Backlog.md says ready and every source pointer resolves; blocking and missing dependency ids from Backlog.md's `readiness`. Exit 1 on a missing dependency, a failing pointer or unknown readiness; blocked tasks alone exit 0. Since F-10.3 it reads the repository through the shared repository-access module (Dulwich), so the target runs it under the tools interpreter, as the test targets do; under an interpreter without Dulwich it fails with `REPOSITORY_NEEDS_DULWICH`. |
| `planning:resolve PROJECT=<repo> -- --backlog <cmd> [--task ID]` (or `-- --pointer <p>`) | `<tools python> -I -B integrations/planning/planning_adapter.py resolve --project <repo> (--backlog <cmd> [--task ID ...] \| --pointer <p> ...)` | no | Re-resolves source pointers; exit 1 on a missing revision, a missing artifact, a digest mismatch or a task without a pointer. Since F-10.3 it reads the repository through the shared repository-access module (Dulwich), so the target runs it under the tools interpreter, as the test targets do; under an interpreter without Dulwich it fails with `REPOSITORY_NEEDS_DULWICH`. |
| `lineage:test` | `<tools python> -I -B -m unittest discover -s integrations/lineage/tests -v` | no | [Lineage references](#lineage-references) tests: parsing and formatting of every kind, the schema, the span anchor, every outcome of each implemented resolver against throwaway git repositories, the fake Backlog.md and its recorded fixtures, and effects-store fixtures, and the P-03.2 traversal with its example and negative resolution fixtures. The live tests run only when `AIEH_BACKLOG` and `AIEH_OPENSPEC` name the pinned tools. |
| `lineage:schema` | `python -I -B integrations/lineage/lineage_resolve.py schema` | no | Checks `integrations/lineage/lineage_schema.json` against the typed references and lists each kind's authority and status. Exit 0 PASS, 1 FAIL. |
| `lineage:resolve -- REF ... [--current] [--project <repo>] [--backlog <cmd>] [--repo NAME=<dir>] [--effects-root <dir>]` | `<tools python> -I -B integrations/lineage/lineage_resolve.py resolve REF ... [options]` | no | Resolves references read-only and prints one JSON resolution each. Exit 0 when all resolved, 1 on any other outcome or a malformed reference, 2 could not run. Since F-10.3 it reads the repository through the shared repository-access module (Dulwich), so the target runs it under the tools interpreter, as the test targets do; under an interpreter without Dulwich it fails with `REPOSITORY_NEEDS_DULWICH`. |
| `lineage:trace -- OUTCOME --project <repo> [--backlog <cmd>] [--store <db>]` | `<tools python> -I -B integrations/lineage/lineage_trace.py trace OUTCOME --project <repo> [--backlog <cmd>] [--store <db>]` | no | Projects the lineage of one outcome id read-only (statement, objective, design, task, attempt), with the real authorities only, and prints the `lineage-projection/v1` JSON. Exit 0 complete, 1 the projection carries uncertainty, 2 could not run. Since F-10.3 it reads the repository through the shared repository-access module (Dulwich), so the target runs it under the tools interpreter, as the test targets do; under an interpreter without Dulwich it fails with `REPOSITORY_NEEDS_DULWICH`. |
| `lineage:example [-- --record]` | `<tools python> -I -B integrations/lineage/tests/lineage_example.py [--record]` | no | Rebuilds the lineage projection example offline (sample authorities and real registry) and prints each verdict; `--record` rewrites `integrations/lineage/examples/`. Since F-10.3 it reads the repository through the shared repository-access module (Dulwich), so the target runs it under the tools interpreter, as the test targets do; under an interpreter without Dulwich it fails with `REPOSITORY_NEEDS_DULWICH`. |
| `owner:test` | `<tools python> -I -B -m unittest discover -s integrations/owner/tests -v` | no | [Owner decisions](#owner-decisions) tests (P-04.1, P-04.2): the shared `owner-decision/v1` record and statement verdicts, the recorder's edits of `proposal.md` and `.openspec.yaml`, and `prepare` and `record` on throwaway fixture repositories (the lineage objective resolver round trip, the id kept on re-recording, every refusal with its code and remedy); the authorization recorder against a fake Gitea, in memory and over an in-process loopback HTTP server (one merge per recorded decision with its receipt and trailers, every refusal with its code, a lost answer resolved by reading); synthetic statements and a fixture credential provider only. The live exercise on the S-01.2.2 fixture (`test_live_authorization.py`, two phases with the Owner's own decision between them) skips unless `AIEH_AUTHZ_RECORDER_LIVE` names a phase (`prepare`, then `record`); its phase plumbing is tested against the fake Gitea. |
| `owner:accept -- prepare --project <repo> --change <name> --item O<n> [--expires-in-minutes N] [--out <file>]` (or `-- record --project <repo> --challenge <file> --statement <file> --recorded-by <attribution> --identity '<Name <email>>' [--amend]`) | `<tools python> -I -B integrations/owner/acceptance_recorder.py prepare\|record ...` | no | The [acceptance recorder](#owner-decisions): `prepare` prints the challenge to show the Owner and writes nothing; `record` records the Owner's statement, mints or keeps the outcome id and commits in the project repository, in process. Exit 0 done, 2 refused (a stable code and its remedy). **Not yet verified** on a real project or with a real Owner acceptance. |
| `owner:authorize -- prepare <owner>/<name> <pull> [--expires-in-minutes N]` (or `-- record --challenge <nonce> --statement <file> --recorded-by <attribution>`, or `-- resolve --challenge <nonce>`) | `<tools python> -I -B integrations/owner/authorization_recorder.py prepare\|record\|resolve ...` | no | The [authorization recorder](#owner-decisions), run only in the main session on an Owner decision: `prepare` writes the challenge to show the Owner to the recorder's state; `record` records the Owner's statement and merges the challenged head as `aieh-owner` (basic authentication from the credential provider, in memory; a write-ahead receipt in the integration store); `resolve` resolves an unknown outcome by reading, never merging. Fail closed: `record` refuses `PROTECTION_UNVERIFIED` or `PROTECTION_DRIFT` (nothing sent) unless the protection check (OA-16, `gitea:protection-check`) answers `verified` immediately before the merge; until its auditor is provisioned (an Owner act) it answers `unverified`. Exit 0 done, 2 refused, 1 failed or unknown. **Not yet verified** against a real Gitea or with a real Owner authorization. |
| `paths:test` | `<tools python> -I -B -m unittest discover -s integrations/paths/tests -v` | no | [Managed data root](#managed-data-root) tests: every refusal code, the platform defaults by injection, both adapters, the legacy table, `example_config.yml`, asset records. The `config.yml` tests skip, counted, when PyYAML is not importable. |
| `paths:show [-- --format sh\|ps1]` | `python -I -B integrations/paths/aieh_paths.py show [--format json\|sh\|ps1]` | no | Prints the managed data root and its categories (`aieh-paths/v1` JSON, or shell assignments). Creates nothing. Exit 2 on a refusal, with its code and remedy. |
| `paths:init` | `python -I -B integrations/paths/aieh_paths.py init` | no | Creates the managed data root, its `persistent/`, `ephemeral/` and `assets/` directories and its `aieh-root.json` marker. Idempotent. |
| `paths:doctor` | `python -I -B integrations/paths/aieh_paths.py doctor` | no | Reports the root, what exists, the marker and the legacy locations with their migration recipes. Moves and changes nothing. |
| `tools:install` | `python -I -B integrations/paths/tools_install.py` | yes (PyPI, once per lock) | Installs the hash-locked Python tools venv (PyYAML, for `config.yml`; Dulwich 1.2.21 and urllib3 2.8.0, for the Python components' repository operations; keyring 25.7.0 and its closure, the credential provider on Linux and macOS (F-06.3); [`composition/lock/python/tools-requirements.txt`](../composition/lock/python/tools-requirements.txt)), wheels only, under the managed data root; prints its interpreter. Part of `setup`; `test` runs under its interpreter. `python -I -B integrations/paths/tools_install.py --python` prints that interpreter for the current lock, creating nothing, and exits 1 when it is not installed. |
| `platform:test` | `<tools python> -I -B -m unittest discover -s integrations/platform/tests -v` | no | [Host-service lifecycle contract](../integrations/platform/README.md) tests (F-06.2): the verbs, records, refusal codes and remedies, adapter selection, the write-ahead transitions and their orchestration over a fake service, the I7 exposure guard; the Windows adapter's declarations and refusals with fakes (never the real Credential Manager), and its listener, token and identity reads of the test process (Windows). |
| `credentials:test` | `<tools python> -I -B -m unittest discover -s integrations/credentials/tests -v` | no | [Credential provider](../integrations/credentials/README.md) tests (F-06.3): the provider contract suite over a fake, the Windows provider (an in-memory advapi32 stand-in; Windows) and keyring with an in-process backend; the fail-closed factory and its `NO_CREDENTIAL_PROVIDER` refusals; keyring's own selection and configuration shown ignored; `doctor`; the credential acts' integration-store receipts on a fixture store; the throwaway-name cross-read across processes with a test-only backend. Never the real Credential Manager: its real-store cross-read runs only with `AIEH_CREDENTIALS_REAL_STORE=1`. |
| `credentials:doctor` | `<tools python> -I -B integrations/credentials/credential_provider.py doctor` | no | Reports the credential provider the harness chooses on this system and its viability, with the refusal and its remedy when there is none. Reads, writes and lists no entry; prints no secret. Exit 0 viable, 2 refused. |
| `gitea:test` | `<tools python> -I -B -m unittest discover -s integrations/gitea/tests -v` | no | [Host Gitea](#host-gitea) tests: pin, layout, `app.ini`, acquisition, the binary lock, identities and first login, role bots, fixture and rotation with fakes (never the real Credential Manager); the Job Object, socket-table and token code against child processes (Windows); the guest profile declares no path to a token store. The live lifecycle test runs only when `AIEH_GITEA_BINARY` names a copy of the pinned binary; the live authorization tests only with `AIEH_GITEA_AUTHZ=1` (`gitea:authz`), the live transport tests only with `AIEH_GITEA_TRANSPORT=1` (`gitea:transport`), and the live protection-auditor tests only with `AIEH_PROTECTION_AUDIT_LIVE=negative` or `=qualify` (each phase an Owner act; not yet run). |
| `dispatch:test` | `<tools python> -I -B -m unittest discover -s integrations/dispatch/tests -v` | no | [Dispatch input resolution and admission](#dispatch-input-resolution-and-admission) tests: every refusal before any reservation, a resolved record reserving in a throwaway store, determinism and the pinned policy digest, the approved-input manifest's schema check and custody; the create admission (workspace, mounts, caps, runtime, route and body bypasses never reach a fake transport; one admitted create reaches it once); the native conversation create (E-01.3.1: every Agent Server call checked against the pinned route allowlist, decision 0001's `/server_info` preconditions, the dispatcher's order on the record re-read from the store, refused attempts marked failed, the workspace created after admission without following links, `workRef` and `outcomeRef` in every reservation, the returned conversation id recorded), against a fake Agent Server replaying the pinned server's recorded answers; the stage's role token (E-01.3.3: each stage reads exactly its mapped bot's entry, a missing or mismatched credential refuses, only a confirmed attempt gets one, no Agent Server call carries it, records carry its fingerprint only), against an in-memory credential provider and a fake Gitea; the live transport (E-01.3.3: `GuestTransport` over `tools/guest.py`'s `GuestApi` as the login that holds the management key, the key never on a command line or in the host process, the host custody copy never opened), with a fake ssh running the real API probe against a loopback fake Agent Server. Uses Backlog.md's recorded readiness output and a throwaway design repository; needs git. |
| `dispatch:check-manifest MANIFEST=<file>` | `python -I -B integrations/dispatch/dispatch_inputs.py check-manifest --manifest <file>` | no | Schema-checks an approved-input manifest and prints a JSON report. Admits nothing. Exit 0 PASS, 1 FAIL, 2 could not read. |
| `dispatch:manifest-path` | `python -I -B integrations/dispatch/dispatch_inputs.py manifest-path` | no | Prints where the live approved-input manifest is expected (`<state>/dispatch/approved-inputs.json` under the managed data root). Creates and reads nothing there. |
| `repository:test` | `<tools python> -I -B -m unittest discover -s integrations/repository/tests -v` | no | [Repository access](#repository-access) contract tests: the module's answers over a git-built golden corpus equal git's recorded answers (revision grammar, object names, file lists, exports, HEAD, status, index, listings, the work-tree check), the gap forms are refused before any access, damaged objects fail visibly, the configuration policies, bundles, no process launched; then the git-oracle comparison, which skips, naming why, where git is not on `PATH`. Fails with `REPOSITORY_NEEDS_DULWICH` without Dulwich, never skips. |
| `inference:test` | `<tools python> -I -B -m unittest discover -s integrations/inference/tests -v` | no | [Inference broker](#inference-broker) tests (S-03.2 slice 1): the family declarations and `components.inference_broker` with every refusal (secret-shaped keys included); token issuance, family binding, revocation, expiry and budgets with their integration-store receipts; every admission refusal code; untranslated pass-through and incremental streaming to a fake upstream per declared family, with the synthetic provider key in place of the attempt token; usage extraction; the audit lines and the I7 scan; egress to the configured origin only; the credential set command over an in-memory provider; `serve` in process; the qualification launcher, the fake upstream and the `issue` command (slice 4) in process; the provider-key containment search (slice 5): its forms, views and positive controls, its command line, and the broker's exposure boundary searched end to end under the launcher (not found; a planted leak found). Never the real credential store, the managed root or the network beyond loopback. |
| `gitea:install [-- --port N \| --from-file EXE]` | `python -I -B integrations/gitea/gitea_host.py install [--port N] [--from-file EXE]` | yes (GitHub, once) | Creates the managed data root (`init`), downloads the pinned Gitea Windows binary into `assets/`, verifies it against the lock and records it, and writes `app.ini` once with Gitea-generated secrets. Windows only. |
| `gitea:up` | `python -I -B integrations/gitea/gitea_host.py up` | no | Starts the managed environment (a supervisor holding a kill-on-close Job Object) with Gitea inside it on `127.0.0.1:13300`; waits for `/api/healthz`. |
| `gitea:down` | `python -I -B integrations/gitea/gitea_host.py down` | no | Stops Gitea with its own `manager shutdown`, then the supervisor. |
| `gitea:status` | `python -I -B integrations/gitea/gitea_host.py status` | no | Processes, listeners, token elevation and job; changes nothing. |
| `gitea:verify [-- --readiness]` | `<tools python> -I -B integrations/gitea/gitea_host.py verify [--readiness]` | no | The F-06.1 proof set against the running instance. Exit 0 PASS, 1 any check failed, 2 refused. `--readiness` prints the same verdicts as an `aieh-readiness/1` record: platform-neutral check names and the platform record (F-06.2). Since F-10.4 it reads the checkout or the repository through the shared repository-access module (Dulwich), so the target runs it under the tools interpreter; under an interpreter without Dulwich it fails with `REPOSITORY_NEEDS_DULWICH`. |
| `gitea:restart` | `python -I -B integrations/gitea/gitea_host.py restart` | no | `down` (when running) and `up` under a write-ahead `aieh-service-transition/1` record (F-06.2); `gitea:recover` resumes an interrupted one. |
| `gitea:inspect` | `python -I -B integrations/gitea/gitea_host.py inspect` | no | Read-only (F-06.2): the `aieh-platform/1` record, the desired, staged and running versions, the supervisor and Gitea with their listeners (TCP table) and user identity (process token), the supervision record and the transitions. |
| `gitea:upgrade -- --to VERSION [--from-file EXE]` | `python -I -B integrations/gitea/gitea_host.py upgrade --to VERSION [--from-file EXE]` | yes (GitHub, once per version) unless `--from-file` | A pinned version only (F-06.2): stages and verifies its asset beside the current one, stops, backs up `gitea.db` (SQLite backup API) and `app.ini`, makes it desired, starts it and checks readiness; a failure before readiness rolls back automatically from the backup. Refuses `VERSION_MISMATCH`, `DOWNGRADE_REFUSED`, `TRANSITION_PENDING`. One version is pinned today, so only fixture assets have exercised it. |
| `gitea:recover` | `python -I -B integrations/gitea/gitea_host.py recover` | no | Reconciles the actual state with a pending transition record first, then resumes it or rolls it back; with nothing pending, reports the state (F-06.2). |
| `gitea:uninstall` | `python -I -B integrations/gitea/gitea_host.py uninstall` | no | Refused while Gitea runs (`UNINSTALL_RUNNING`); empties `ephemeral/tmp/gitea/` only and deletes nothing under `persistent/` and no asset (F-06.2). |
| `gitea:identities` | `python -I -B integrations/gitea/gitea_host.py identities` | no | Creates the site administrator and the non-administrator Owner account; each temporary password goes only into the credential provider (Windows Credential Manager). |
| `gitea:finalize-credentials` | `<tools python> -I -B integrations/gitea/gitea_host.py finalize-credentials` | no | Replaces both temporary passwords with harness-held final ones, with no Owner sign-in (Owner directive of 2026-11-07). Each is generated, stored in the credential provider first and set through Gitea's own forced change. Then every token of both accounts is revoked, the result is verified, the temporary entries are deleted, and the run fails if any password is found in the managed root, the checkout or the output. Each account's act writes an integration-store receipt, fingerprints only, and reads it back (F-06.3; fakes only since). Live-verified on 2026-11-07. Since F-10.4 it reads the checkout or the repository through the shared repository-access module (Dulwich), so the target runs it under the tools interpreter; under an interpreter without Dulwich it fails with `REPOSITORY_NEEDS_DULWICH`. |
| `gitea:roles -- provision\|fixture [--admin-merge-probe]\|escape-probe\|rotate ROLE\|retire ROLE\|status` | `python -I -B integrations/gitea/gitea_roles.py <command>` | no | [Role credentials](#host-gitea) (S-01.2.2): creates the restricted, non-administrator Bot accounts and mints each role's narrowest token into the credential provider (`AIEH Gitea bot <role>`); `fixture` applies the authorization fixture as the site administrator, with its harness-held password in memory and no token (only after `gitea:finalize-credentials`); `escape-probe`, a separate Owner act and never part of `provision` or `fixture`, creates the same way the private, empty repository `aieh-authz-fixture/escape-probe` with no collaborators, whose rules the protection auditor's live negative test must be refused (it never addresses the fixture repository, leaves an existing one in that state unchanged and refuses one in any other state; **not yet verified** against a real Gitea); `rotate` revokes a token, proves it fails closed and re-issues it; `retire` revokes it, proves it fails closed and deletes its entry (F-06.2); each `rotate` and `retire` writes an integration-store receipt, fingerprints only, and reads it back, or fails (F-06.3); `status` changes nothing. Prints fingerprints, never a token. |
| `gitea:protection-check -- verify <owner>/<name>` | `python -I -B integrations/gitea/protection_check.py verify <owner>/<name> [--base <branch>] [--port N]` | no | The [protection check](../integrations/gitea/README.md#the-protection-check-oa-16) of decision 0012 point 6 (OA-16) as the authorization recorder asks it: reads the admitted repository's protection rules, precedence, settings, collaborators, teams and deploy keys as the read-only protection auditor (its Credential Manager entry, in memory) and prints the verdict (`verified`, `drift`, `unverified`) with its digest, never a token. Exit 0 verified, 1 drift, 2 unverified or refused. Its auditor is not provisioned: **not yet verified** against a real Gitea. |
| `gitea:authz` | `AIEH_GITEA_AUTHZ=1`, then `python -I -B -m unittest discover -s integrations/gitea/tests -p test_authorization_live.py -v` | no | Live allowed and forbidden calls of each bot token against the running Gitea. Opt-in; skips with its reason when Gitea is down, an entry is missing, or (per class) the fixture is absent. `AIEH_GITEA_AUTHZ_REPORT=<file>` records every probe. |
| `gitea:transport` | `AIEH_GITEA_TRANSPORT=1`, then `<tools python> -I -B -m unittest discover -s integrations/gitea/tests -p test_transport_live.py -v` | no | Live qualification of the [repository-access](#repository-access) module's smart-HTTP transports (F-10.6): the push matrix of `gitea:authz` replayed through the module as each bot (`PUSH_REFUSED` for HTTP 401 or 403, `PUSH_REJECTED` for a rejected update; no module call launches a process), and a module clone checked by `git fsck --strict`. Reads the bot tokens from Credential Manager into memory, as `gitea:authz` does. Adds one commit to builder's and planner's proposal branches (`work/authz-<role>`), as `gitea:authz` does; everything else it tries is refused. Opt-in; skips with its reason when Gitea is down, an entry is missing, the fixture is absent or Dulwich is not importable. `AIEH_GITEA_TRANSPORT_REPORT=<file>` records every probe. |
| `security:check [-- --list]` | `python -I -B tools/check_security_inventory.py [--list]` | no | Checks the [security inventory](#security-inventory): every privileged operation names exactly one existing principal, no agent principal holds, manages or may read an Owner, admin, executor or management credential, every reference resolves, and every entry is planned, observed (with evidence) or unknown (with a finding). Exit 0 PASS, 1 FAIL, 2 could not run. |
| `security:containment-check [-- --list\|--render]` | `python -I -B tools/check_containment_cases.py [--list] [--render]` | no | Checks the [containment cases](#containment-cases) (S-02.1): every category covered by a denial case; every probe names an enforcement location whose references resolve (profiles P-ids, network-matrix edges, inventory assets, credentials or findings) and a positive control that is an existing permitted case; every attempt is non-destructive (a closed operation set, writes only in the probe's scratch, no deny-listed command, no off-host target outside the S-01.4 sweeps); every category has a live mutation; no machine path; the README block equals `--render`. Exit 0 PASS, 1 FAIL, 2 could not run. |
| `policy:check [-- --list\|--render]` | `python -I -B tools/check_role_tokens.py [--list] [--render]` | no | Checks the [role-token matrix](#role-token-matrix): no agent, reviewer or CI role is granted an Owner, executor, administration or management operation, a privileged capability or credential; every grant names an existing id of the role's own principal; every credential has its issuance and revocation rows; the sunset map is complete; the README's tables equal `--render`. Exit 0 PASS, 1 FAIL, 2 could not run. |
| `policy:network-check [-- --list\|--render]` | `python -I -B tools/check_network_matrix.py [--list] [--render]` | no | Checks the [network matrix](#network-matrix) (S-01.4): every ordered pair of trust domains has a classified row; no allow from an untrusted or contained domain into a trusted one names anything but a profiles P7 endpoint class or reaches a management or credential asset; every allow names a prevention mechanism and every disclosed path a finding; every id, plan leaf and profile endpoint resolves; every active profile endpoint and forward is an allow row; an observed Owner act cites its approval; the README's tables equal `--render`. Exit 0 PASS, 1 FAIL, 2 could not run. |
| `policy:ci-check [-- --list\|--render]` | `python -I -B tools/check_ci_policy.py [--list] [--render]` | no | Checks the hostile-CI policy (Q-02.1; [`policy/README.md`](../policy/README.md#hostile-ci-policy-q-021)): no validation lane holds an Owner, admin, executor or management credential and the job holds only its two inert task tokens; the job reaches nothing; the runner configuration, the governance workflow (`policy/ci/workflows/`), the Gitea-side configuration, the token ceilings, the empty secret sets, the proxy allowlist and the registration reset are as decided; every forward is an Owner act; every fact verified at source names its lines in the pinned archive; every id resolves; the README's block equals `--render`. Standard library, offline, reads only committed files. Exit 0 PASS, 1 FAIL, 2 could not run. |
| `intent:check PROPOSAL=<file> -- --source REF=FILE` | `python -I -B tools/check_intent_record.py <file> --source REF=FILE [--source ...]` | no | Checks a proposal's [intent record](#intent-records): byte-identical quotes, Owner methods kept as hypotheses, acceptances, required fields. Exit 0 PASS, 1 FAIL, 2 could not run. |
| `intent:qualify -- <run\|check\|prompt\|system-prompt> [options]` | `python -I -B tools/qualify_intent_skill.py <subcommand> [options]` | `run`: the model command's own (a live model) | Runs the intent-normalization Skill's [behavioural qualification](#intent-records): one corpus item and turn through a JSON model-command template in an empty working directory, then the checker, then a ledger entry; refuses past `--max-invocations` (default 25). `check` scores a saved proposal against an item's messages. |
| `profile:check [-- --strict]` | `python -I -B tools/check_profile.py [--strict] [--openapi <file>]` | no | Schema check of every `profiles/*/profile.json`: pinned boot inputs, labels, no host share, loopback-only forwards, ceilings, no TCG fallback. Runs no provider. `--strict` also fails on inputs declared with an unknown pin. `--openapi` validates the Agent Server conversation fixture against the locked `openapi.json` (F-04.1). |
| `guest:preflight PROFILE=<dir> STATE_DIR=<dir>` | `python -I -B tools/guest.py preflight --profile <dir> --state-dir <dir>` | no | Read-only capability report for a strong guest profile; each failure names its Owner act (A1, A2, A3). See [Execution guests](#execution-guests). |
| `guest:create PROFILE=… STATE_DIR=… NAME=<name>` | `<tools python> -I -B tools/guest.py create --profile <dir> --state-dir <dir> --name <name>` | no | Creates, boots and waits for a disposable guest. Refuses an existing instance and a dirty `profiles/`. Since F-10.4 it reads the checkout or the repository through the shared repository-access module (Dulwich), so the target runs it under the tools interpreter; under an interpreter without Dulwich it fails with `REPOSITORY_NEEDS_DULWICH`. |
| `guest:start`, `guest:inspect`, `guest:stop`, `guest:destroy`, `guest:recreate` (same variables) | `python -I -B tools/guest.py <operation> --profile <dir> --state-dir <dir> --name <name>` (`recreate`: `<tools python>`) | no | The rest of the lifecycle; `destroy` deletes only the instance directory. `recreate` creates, so it runs under the tools interpreter, as `create` does. |
| `guest:exec PROFILE=… STATE_DIR=… NAME=… -- CMD` | `python -I -B tools/guest.py exec --profile <dir> --state-dir <dir> --name <name> -- CMD` | no | Operators only: a command in the guest over the loopback SSH forward. |
| `guest:push PROFILE=… STATE_DIR=… NAME=… REPO=<repo> REF=<branch>` | `<tools python> -I -B tools/guest.py exchange-push --profile <dir> --state-dir <dir> --name <name> --repo <repo> --ref <branch>` | no | Exchange push: one local branch as a bounded git bundle, by SFTP into `/home/agent/exchange`. Reads the repository only. Since F-10.4 the bundle is written in process by the shared repository-access module (Dulwich; no git is launched), so the target runs under the tools interpreter; `guest:pull` keeps git as the verifier. |
| `guest:pull PROFILE=… STATE_DIR=… NAME=… FILE=<file>` | `python -I -B tools/guest.py exchange-pull --profile <dir> --state-dir <dir> --name <name> --file <file>` | no | Exchange pull: one file into the instance's staging directory; a bundle is verified in a fresh bare repository there. |
| `guest:canaries OUT=<dir>` | `python -I -B tools/guest.py canaries --out <dir>` | no | Writes a synthetic canary set and fake home into a new directory outside the checkout. |
| `guest:create-canaries PROFILE=… STATE_DIR=… NAME=… CANARIES=<dir>` | `<tools python> -I -B tools/guest.py create --profile <dir> --state-dir <dir> --name <name> --canaries <dir>` | no | `create` with the canary set planted in its own environment first (the P5 test). |
| `guest:check-surfaces PROFILE=… STATE_DIR=… NAME=… CANARIES=<dir>` | `python -I -B tools/guest.py check-surfaces --profile <dir> --state-dir <dir> --name <name> --canaries <dir>` | no | Startup inspection test for profiles P3 to P6 (F-03.3.1): exit 0 only when all four PASS. |
| `guest:smoke PROFILE=… STATE_DIR=… NAME=<name> CANARIES=<dir> DURABLE=<dir>` | `<tools python> -I -B tools/guest.py smoke --profile <dir> --state-dir <dir> --name <name> --canaries <dir> --durable <dir> [--durable <dir> …] [--out <file>]` | no | The F-03.4 provision/inspect/teardown smoke test (profiles P10) on a fresh instance name. Exit 0 only on PASS. See [Execution guests](#execution-guests). Runs under the tools interpreter (the profile revision and the `repo-inventory/2` snapshots read the checkout through the repository-access module). |
| `guest:provision-fetch PROFILE=… STATE_DIR=…` | `python -I -B tools/guest.py provision-fetch --profile <dir> --state-dir <dir>` | yes | Host side of guest provisioning (F-04.1a): downloads the profile's provision-lock artifacts from their upstreams (snapshot.debian.org, GitHub, ghcr.io through the pinned crane), verifies each against the lock and stages them under `<state>\provision\<lock sha256>\`. About 1.5 GB on the first run; a verified stage is reused. Runs nothing downloaded except crane. |
| `guest:image-inspect PROFILE=… STATE_DIR=… -- --path <path>[#key#key] [--path …]` | `python -I -B tools/guest.py image-inspect --profile <dir> --state-dir <dir> --path <path>[#key#key] [--path …]` | no | Read only (S-03.3): re-verifies the `provision-fetch` stage against the lock, then reads the staged agent-server image archive as data. The gzip layers are streamed, re-hashed against the lock and applied in order as a union view (whiteouts and opaque directories honoured); for each path it reports presence, type, mode, owner, size, the layer that last wrote it, symlink and hard-link targets (resolved inside the image root), the sha256 of the file it resolves to, a directory's children and, with `#key#key`, a JSON file's field; also the config's user, entrypoint, matching `Env` entries and the history lines naming acp, claude, codex or node. Extracts, runs and writes nothing. |
| `guest:create-provisioned PROFILE=… STATE_DIR=… NAME=<name>` | `<tools python> -I -B tools/guest.py create --profile <dir> --state-dir <dir> --name <name> --provision` | no | `create` whose seed carries the provisioning manifest of the verified `provision-fetch` stage (F-04.1b). `recreate` and `smoke` take `--provision` too. |
| `guest:provision PROFILE=… STATE_DIR=… NAME=<name>` | `python -I -B tools/guest.py provision --profile <dir> --state-dir <dir> --name <name>` | no | Guest side of provisioning (F-04.1b): transfers the stage over SFTP, triggers the seeded single-use root step and checks its `RESULT.json`. See [Execution guests](#execution-guests). |
| `guest:conversation-smoke PROFILE=… STATE_DIR=… NAME=<name> [-- --restart --openapi <file> --canaries <dir> --out <file>]` | `python -I -B tools/guest.py conversation-smoke --profile <dir> --state-dir <dir> --name <name> [--restart] [--openapi <file>] [--canaries <dir>] [--out <file>]` | no | The contained conversation lifecycle (F-04.2) on a running provisioned guest: create the disposable Docker conversation of the pinned fixture, inspect it and its container, create it again (idempotent), read its events, stop its runtime, reopen it, optionally restart the guest and reopen again, delete it. Exit 0 only on PASS. See [Execution guests](#execution-guests). |
| `guest:admission-probe PROFILE=… STATE_DIR=… NAME=<name> [-- --out <file>]` | `python -I -B tools/guest.py admission-probe --profile <dir> --state-dir <dir> --name <name> [--out <file>]` | no | The management API admission (S-01.3.1) on a running provisioned guest: the pinned route inventory against the running server, every route without the key and with a wrong one, the agent network's reach from inside two disposable conversation containers, the key check and the logged refusals. Exit 0 only on PASS. See [Execution guests](#execution-guests). |
| `guest:job-access-probe PROFILE=… STATE_DIR=… NAME=<name> [-- --token-fingerprint LABEL=sha256:<hex16> --attempt-token-stdin --out <file>]` | `python -I -B tools/guest.py job-access-probe --profile <dir> --state-dir <dir> --name <name> [--token-fingerprint LABEL=sha256:<hex16>] [--attempt-token-stdin] [--out <file>]` | no | The job environment (S-01.3.2) on a running provisioned guest: from inside two disposable conversation containers, their effective hardening, every engine socket, the engine API and the host aliases over TCP, every privileged Agent Server route at every address, the management, Owner, admin and bot credentials by name and fingerprint, and the S-01.4 egress sweep (public literals, SLIRP's aliases, an unconfigured guestfwd-class address) against the egress guard's counters. On a guest with the inference composition it adds the inference sweep, and `--attempt-token-stdin` (one attempt token on standard input, never an argument) the token steps of S-03.2. Exit 0 only on PASS. See [Execution guests](#execution-guests). |
| `guest:inference-forward PROFILE=… STATE_DIR=… NAME=<name> ACTION=start\|status\|stop [-- --broker-port <port>]` | `python -I -B tools/guest.py inference-forward --profile <dir> --state-dir <dir> --name <name> --action start\|status\|stop [--broker-port <port>]` | no | The inference forward session (S-03.2, decision 0015 sections 4.1, 4.3 and 4.4) of a guest created with `create --provision --inference` (refused for any other): `start` holds `ssh -N -R 172.17.0.1:8090:127.0.0.1:<broker inference port>` over the instance's hostfwd, with `ExitOnForwardFailure=yes`, keepalives and the per-instance key; a detached holder writes `<instance>\inference-forward.json` once ssh reports the forward and removes it when the session ends. `start` is idempotent (a held session is returned, a stale record replaced); `status` and `stop` read and end it. The port is `components.inference_broker.inference_port` (the control port and any other are refused) and the broker's control listener must report it. **Not yet verified** against a real ssh or guest: it needs the Owner's acts A2, A3 and A4. See [Execution guests](#execution-guests). |
| `guest:containment-probe PROFILE=… STATE_DIR=… NAME=<name> [-- --sensitivity --token-fingerprint LABEL=sha256:<hex16> --out <file>]` | `python -I -B tools/guest.py containment-probe --profile <dir> --state-dir <dir> --name <name> [--sensitivity] [--token-fingerprint LABEL=sha256:<hex16>] [--out <file>]` | no | The containment probes (S-02.1) on a running provisioned guest: the versioned catalogue in one pass, reusing `admission-probe` and `job-access-probe` unchanged and running the remaining cases inside two further disposable conversation containers with generated canary workspaces; per case the attempt, principal, observations, positive control and verdict (PASS, FAIL or UNKNOWN) with the runtime-configuration snapshot. `--sensitivity` adds the live mutations. The route-present egress case needs a guest created with `--egress-falsification`. Exit 0 only on PASS. See [Execution guests](#execution-guests). |
| `guest:host-census [-- --exclude-pid <pid> --out <file>]` | `python -I -B tools/guest.py host-census [--exclude-pid <pid>] [--out <file>]` | no | S-01.4, read only and unelevated: the harness's host listeners by PID (QEMU, the host Gitea and its proxy, the Owner host's Vite servers), each of which must be on 127.0.0.1, and the Windows Firewall profiles and rule count, recorded as disclosure (UNKNOWN when a cmdlet is refused). No profile or state directory; it changes no rule. Exit 0 only on PASS. |
| `guest:netprobe PROFILE=… STATE_DIR=… NAME=<name>` | `<tools python> -I -B tools/guest.py netprobe --profile <dir> --state-dir <dir> --name <name>` | no | **Test only.** The F-03.3.2 network validation of profiles P7 in a disposable guest (guest root, one test `guestfwd` to a 127.0.0.1 listener, decoys). Exit 0 only on PASS. Destroy the instance afterwards. |
| `hooks:install` | `python -I -B tools/publication_gate.py install` | yes (once) | Installs the [publication-safety gate](#publication-safety-gate): pinned Gitleaks into the per-user cache, `core.hooksPath`. |
| `hooks:verify` | `python -I -B tools/publication_gate.py verify`, then the gate's tests under `<tools python>` with `AIEH_GATE_REQUIRE_SCANNER=1` (`<tools python> -I -B -m unittest discover -s tools/tests -p test_publication_gate.py -v`) | no | Scanner hash and version, hook wiring, configuration, synthetic tests, and test 7's nested rerun of the whole tool suite (which runs nowhere else but `qualify`). |
| `scan:history [-- REVS]` | `python -I -B tools/publication_gate.py history [REVS]` | no | Read-only, redacted scan of every commit (default `--all`); exit 1 on findings. |
| `resolve WORK=<dir>` | `<tools python> -I -B composition/resolve.py --work <dir>` | yes | Component lock resolution and host install; see [`composition/lock/README.md`](../composition/lock/README.md). `<dir>` must be empty or absent and outside the checkout. Since F-10.6 it reads the source tags through the shared repository-access module (Dulwich, no git), so the target runs it under the tools interpreter; under an interpreter without Dulwich it stops with `REPOSITORY_NEEDS_DULWICH` (exit 2). |
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
[`composition/inventory/LEDGER.md`](../composition/inventory/LEDGER.md) for the open
items.

**Formatting and linting.** No formatter or linter is configured yet.

## Testing

The tests are standard-library `unittest` suites. Each lives beside the code it tests:
`tools/tests/` for the tools and `integrations/<component>/tests/` for each integration.
`task test` runs them serially, one `<tools python> -I -B -m unittest discover -s <suite> -v`
per suite, in the order of the `test` target in `Taskfile.yml`, under the Python tools set's
interpreter (`tools_install.py --python`; [Tool tiers](#tool-tiers)). Live suites against installed
tools or services are opt-in through their environment variables and are skipped, counted,
otherwise.

**Categories.** Every test class declares one category, `unit`, `contract`, `integration`,
`e2e` or `performance`: a class attribute `category = '...'`, or a module-level
`CATEGORY = '...'` that covers every class of the module without its own. Both are plain
attributes that unittest ignores. The categories mean:

| Category | A class is in it when | Process launches, sockets, `os.chdir` |
|---|---|---|
| `unit` | it exercises code in the test process only: logic, parsing, refusals, with in-memory or temporary-file fixtures | none, in its tests and class fixtures (the profile and `test:budget` check this) |
| `contract` | it checks a boundary against its specification: a committed artifact (policy, inventory, profile, lock, README block) against its checker or schema, a pinned upstream interface, or a command's exit-code and output contract | allowed |
| `integration` | it drives real components together: git repositories, several processes on one store, child processes and their Windows job, file-system custody | allowed |
| `e2e` | it needs a live installed tool or running service and runs only when its environment variables name them | allowed; skipped without them |
| `performance` | it measures a time or a launch count as its result | allowed |

A class is classified from what the profile measured, not from its name: anything that
launches a process, opens a socket or changes directory, in a test or a class fixture, is not
`unit`. `task test:categories` checks mechanically that every class has a valid category; it
imports the test modules and runs no test.

**Profile.** `task test:profile` (`<tools python> -I -B tools/test_profile.py run`) runs exactly the
suites of `task test`, serially, under the interpreter that runs it (the tools interpreter, as
`task test` runs them), each in a child process that calls `unittest.main` with the
same arguments as `python -I -B -m unittest discover -s <suite> -v`, from the repository
root. An audit hook (`sys.addaudithook`), which patches nothing, counts per test and per
class fixture:

- `launches`: process launches by the test process itself (the `subprocess.Popen`,
  `os.system`, `os.spawn`, `os.posix_spawn`, `os.exec`, `os.fork`, `os.startfile` and direct
  `_winapi.CreateProcess` audit events), failed attempts included; processes those children
  start are not counted;
- `mkdtemp`: `tempfile.mkdtemp` calls, `TemporaryDirectory` included;
- `sockets` and `chdir`: sockets created and `os.chdir` calls;
- tests run, and each test's outcome and wall time.

Events are attributed to the running test (with its `setUp`, `tearDown` and cleanups), else
to the class or module fixture unittest is running, else to the module being imported. Each
launch is also named by its program (`git <subcommand>`, `python <script>`, an executable's
name) and by the repository file that made it, which ranks the costs to remove. The full
profile, every test's id, outcome, counters and wall time, goes to a new temporary directory
outside the checkout (`--out` to choose); `--runs N` repeats the whole set and reports wall
medians, and fails when a counter or an outcome differs between runs. `python -I -B
tools/test_profile.py compare --profile <full profile>` runs the plain unittest commands
without the profiler and fails unless they give the same test ids and outcomes.

**Budgets.** [`policy/test-budgets.json`](../policy/test-budgets.json) holds the enforceable
budgets, per category, per suite and in total, from the measured baseline in
[`evidence/test-profile/`](../evidence/test-profile/): exact counters (at least the
baseline's tests; at most its launches and `mkdtemp` calls) and the median wall time of
three serial runs with a 30% tolerance (never less than half a second of slack, for
sub-second scopes). `task test:budget` (`<tools python> -I -B tools/check_test_budget.py check
--run`) profiles three runs under the tools interpreter and checks them; it fails on a failing or uncategorized test, a
`unit` class that launches, opens a socket or changes directory, a counter above its budget,
fewer tests, a median above its tolerance, or a suite or category the budgets do not name.
Counts below budget pass and are reported. `python -I -B tools/check_test_budget.py propose
--profile <file>` prints the budgets a profile implies; changing the budget file is a
reviewed change with the profile that justifies it, never automatic. The counters do not
depend on the shell or on which optional programs are on PATH: a test that needs one (`sh` or
`pwsh` for the path adapters' round trips) attempts its launch in every environment and skips
when the program is missing, and a failed attempt still counts as a launch, so PowerShell, Git
Bash and a POSIX shell count the same launches and one profile's proposal holds in all of
them. A test that decided to skip before launching would count one launch fewer where its
program is missing, and budgets proposed there would fail elsewhere. The wall budgets
belong to the baseline host (recorded in the file); on another host, check the counters
with `-- --counters-only`, which needs one run and says that the wall time was not checked.

**When the budget check runs.** `task test:budget` is an acceptance obligation: it runs at
the acceptance of every plan leaf and at every release, and its result is recorded with the
leaf's evidence. It never runs from a git hook: it takes three full serial runs.

**Wall time.** At `07c7cd5` the serial `task test` set took a median of 355 s on the
verification host (Windows 11, 32 logical processors, CPython 3.12.10); the per-suite
medians and the measurement are in [`evidence/F-09.1-test-baseline.md`](../evidence/F-09.1-test-baseline.md).
At `0c0412f`, with test 7's nested rerun moved to the gate tier (F-09.2), it took a median of
243 s, and `test:all` took 50 to 53 s on 8 workers;
[`evidence/F-09.2-parallel-runner.md`](../evidence/F-09.2-parallel-runner.md) has the
measurements. At `a18e8cf`, with the shared fixtures below (F-09.3), three serial runs took a
median of 219 s (195 to 215 s in a later set whose interleaved runs of the earlier tree took
260 s), and `test:all` 41 to 42 s;
[`evidence/F-09.3-shared-fixtures.md`](../evidence/F-09.3-shared-fixtures.md) has the
measurements. At `7bb7254`, with the batched git reads below (F-09.4), three serial runs
interleaved with runs of the F-09.3 tree took a median of 154 s against 203 s, and `test:all`
34 to 36 s. At `34f9d8e`, with one git access per operation and the checkers' load/evaluate
seam (F-09.4 round 2), three interleaved serial runs took a median of 147 s (135 to 155 s)
against 201 s for the F-09.3 tree and 175 s for the round-1 tree, and `test:all` 31 s. At
`3366af4` (round 3: one read session per dispatch test, the profile checker compiled once per
content), three interleaved serial runs took a median of 127 s (126 to 138 s) against 206 s
for the F-09.3 tree and 143 s for the round-2 tree, and `test:all` 31 to 32 s. Those runs
were made from Git Bash, whose `PATH` resolves the real git. From PowerShell, whose default
`PATH` resolves Git for Windows' launcher `cmd\git.exe` (one more process per git command),
three interleaved serial runs at `e73f941` (round 4: every adapter git process one process
tree) took a median of 147 s (147 to 149 s) against 249 s for the F-09.3 tree and 147 s for
the round-3 tree, and `test:all` 33 s; one run from Git Bash took 147 s in the same period;
[`evidence/F-09.4-batched-git.md`](../evidence/F-09.4-batched-git.md) has the measurements.
At `3aa5ef3` (F-10.2: the repository-access suite added, and every suite under the tools
interpreter), three serial runs took a median of 145 s (144 to 146 s) from Git Bash, the
baseline of the budgets, and 159 s from PowerShell, and `test:all` 36 s;
[`evidence/F-10.2-repository-module.md`](../evidence/F-10.2-repository-module.md) has the
measurements.

**Shared fixtures and process boundaries.** Expensive fixtures are built once and copied, and
logic cases run in the test process; the tests that check a real process interaction still
launch it (plan leaf F-09.3):

- **Golden repositories.** A fixture repository is built with git once per test process for
  each digest of its inputs (its files, commit messages, identity and dates) and copied per
  test with plain file copies: the planning design repository
  (`two_task_fixture.build_repo`), the lineage example project, the dispatch tests' revised
  design, the gate tests' repository pair (with its bare `origin`) and the guest exchange
  fixture. A copy is the same repository, with the same commits, as a fresh build (a test
  checks it). The fixture's own git commands run with `core.longpaths`, and it commits edits
  and deletions of tracked files in one `git commit --all`.
- **The repository-access corpus** (plan leaf F-10.2) is built by git once, when it is
  recorded, and committed as an archive with git's answers beside it, so that its recorded half
  runs without git; the suite extracts it once per test process and only reads it
  ([Repository access](#repository-access)).
- **The Backlog runner.** `planning_adapter.Backlog` takes a runner (by default `None`:
  `run_tree`, one process tree, since F-10.3; `subprocess.run` before). The logic tests answer
  the fake Backlog.md in the test process
  (`fake_backlog.InProcessRunner`); the command-line contracts and the traversal's recorded-
  process test launch it, and a contract test checks that both answer alike.
- **In-process logic cases.** The verifier's logic cases call the copy's own
  `verify_seed.py` `main()` in the test process; its command-line contract (exit status and
  output, git missing from `PATH`, a directory that is not a repository, this checkout's own
  baseline) is still a real run. The network-matrix and containment-case checkers have a
  load/evaluate seam (`load_inputs`, `evaluate`; `check` is the two together): their mutation
  tests load the inputs once per class and evaluate each mutated copy against them, checking
  that the shared inputs stay unchanged, while the committed files still go through `check`
  and the command line.
- **Shared read-only copies.** The gate tests that run the real scanner share one copy of it
  per class (the gate only reads its tool cache), and the profile checker's negative cases
  share one copy of `profiles/`; a case that writes takes a private copy, and every case
  checks that the shared copy is unchanged. The verifier's tests copy the seeded files once
  per class: the cases that only read use that copy, each writing case takes a private copy
  of it; the baseline-mode cases copy one repository per class with the seed staged and packed.
- **Repository reads in process (plan leaves F-09.4 and F-10.3).** The planning adapter's
  `Git` is a facade over the shared [repository-access](#repository-access) module: it reads
  the repository in the test process over Dulwich and launches no git (F-09.4's
  `git cat-file --batch` reader is gone). One top-level operation (a lineage traversal, a
  readiness evaluation or dispatch read, a resolution from the command line or a resolver
  entry point) shares one work-tree check and one opened repository per project, and runs
  each Backlog.md read once; nothing outlives the operation. One traversal of the lineage
  example launches 3 processes with the fake Backlog.md launched (none with it in the test
  process), against 7 and 4 with the batch reader and 79 and 70 before it. The benchmark is
  the `performance` class `OneTraversal` in
  `integrations/lineage/tests/test_traversal_git.py`: its result is that launch count, at most
  10, and it measures the traversal's repository access against the git oracle, interleaved
  in the same run. The upstream CLIs (Backlog.md, OpenSpec) are each one process tree (a
  Windows job object, a POSIX process group), so a kill, a timeout or a close also ends the
  child a launcher such as an npm shim or `cmd\git.exe` starts; `test_git_batch` checks it
  through a stand-in launcher and, where it is installed, through Git for Windows' own
  (POSIX not yet verified).
- **Long temporary paths.** The test processes create paths up to 176 characters below
  TEMP (measured; the provision tests), which Python on Windows opens past 260 characters only
  where long paths are enabled. Git for Windows needs `core.longpaths` past 260 characters:
  the fixtures' own git commands set it, and so does the guest exchange verifier's host git
  (`tools/guest.py` `run_git`), whose pull verification creates a bare repository about 138
  characters below the state directory, and the publication-gate tests' fixture repositories
  (their bare `origin`'s receive quarantine is about 133 characters below TEMP). Every suite
  passes under a TEMP of 131 characters (F-09.4).

**Parallel runner.** pytest and pytest-xdist run the same unittest suites as a second runner;
`task test` and `task setup` stay the serial unittest run, under the Python tools set's
interpreter. `task dev:install` installs them, hash-locked and wheels only
([`composition/lock/python/dev-requirements.txt`](../composition/lock/python/dev-requirements.txt):
pytest, pytest-xdist 3.8.0, execnet, pluggy, iniconfig, Pygments, packaging, and colorama on
Windows, all pure-Python wheels under MIT, BSD or Apache licences; and the Python tools set,
PyYAML 6.0.3 (MIT), Dulwich 1.2.21 (Apache-2.0 elected) and urllib3 2.8.0 (MIT), with exactly the
hashes of the tools lock, so that every suite runs with the same packages under both runners), into the `python-dev-tools`
venv under the managed data root through the same mechanism as `task tools:install`.
[`pyproject.toml`](../pyproject.toml) holds the pytest configuration only (the repository is
not a Python package): the suites of `task test`, unittest's collection rules (only
`unittest.TestCase` classes in `test*.py` files, no subdirectory of a suite), one marker per
category under `--strict-markers`, no cache directory and no assertion rewriting. The root
[`conftest.py`](../conftest.py) gives each test its class's category as a marker, refuses a
class without a valid category, and holds the unit guard.

| Target | Runs | For |
|---|---|---|
| `test:unit` | `-m unit` | the inner loop |
| `test:fast` | `-m "unit or contract"` | the inner loop |
| `test:component` | `-m "contract or integration"` | the boundary |
| `test:all` | `-m "not e2e"`, then the Owner host's Vitest tests when Node.js 24 or later is present | everything but the live classes |

Each runs `<dev python> -I -B -m pytest -n auto --maxprocesses 8 --dist loadscope -m <tier>`
with `PYTHONDONTWRITEBYTECODE=1`: at most 8 worker processes, and each test class stays in one
worker, so its `setUpClass` runs once. Pass pytest options after `--`, for example
`task test:unit -- -k paths` or `-- -n 0` for one process.

- **The unit guard.** While a `unit` test runs (its setup with `setUpClass` and `setUpModule`,
  its body and its teardown), an audit hook refuses a process launch, a socket and an
  `os.chdir`, the same audit events the profile counts, and the test fails, naming each event.
  The refused launch never starts. Tests in the other categories may do all three.
- **Nothing is written inside the checkout.** No `.pytest_cache` (`-p no:cacheprovider`), no
  `__pycache__` (`-B` and `PYTHONDONTWRITEBYTECODE=1`, because xdist workers do not inherit
  `-B`; `conftest.py` refuses to run otherwise), and pytest's base temporary directory stays
  under the system temporary directory. The Owner host's tests run with Vitest's result and
  module caches off.
- **The same results.** `--aieh-outcomes=FILE` writes every test id and outcome as the stdlib
  runner reports them (a class that skips or fails in `setUpClass` is one `setUpClass
  (module.Class)` row, as unittest reports it), and `--aieh-conformance=PROFILE` fails unless
  they equal those of a full stdlib profile (`tools/test_profile.py run --out PROFILE`) under
  the same interpreter (write both with `=`: pytest finds its root directory before it knows
  these options, and would take an existing file outside the checkout for a test path). Run the
  stdlib side with the dev venv's interpreter too, so that both sides import the same packages:
  the tests that run pytest itself skip where pytest is not importable, and the `config.yml`
  tests where PyYAML is not.
- **Live suites** (`e2e`) stay opt-in through their environment variables and never run in
  parallel: `test:all` deselects them, and their own targets (`gitea:authz`, `gitea:transport` and the live
  planning and lineage tests) run them serially.
- **Test 7's nested rerun.** The publication gate's test 7 checks the existing commands in
  every run (`verify_seed.py` in both modes and `check_profile.py`). Its nested rerun of the
  whole tool suite, about two minutes, runs only under `AIEH_GATE_REQUIRE_SCANNER=1`:
  `task hooks:verify` (whose test run uses the tools interpreter, as `task test` does; the gate
  itself keeps the plain one), and `task qualify` at a release. Elsewhere it is reported skipped, with
  that reason.
- **Required tiers.** `task test` (every suite, serially) and `task test:all` run every
  fail-closed security proof that runs by default; only the `e2e` classes are outside
  `test:all`.

## Managed data root

[`integrations/paths/`](../integrations/paths/README.md) holds the shared path resolver of
plan leaf F-07.1 ([decision 0009](../decisions/0009-managed-data-root-and-configuration-contract.md),
Proposed). The harness keeps its installations, state, caches and downloads outside the
checkout, under one managed data root:

- Windows: `%LOCALAPPDATA%\AIEH`
- Linux: `$XDG_DATA_HOME/aieh`, or `~/.local/share/aieh`
- macOS: `~/Library/Application Support/aieh` (**not yet verified**)

`AIEH_DATA_ROOT` overrides it: absolute, or relative to the repository root, never to the
working directory. A root inside or containing the checkout is refused. The root holds
`persistent/` (never deleted implicitly), `ephemeral/` (controlled cleanup only) and `assets/`
(downloaded, verified artifacts, each with an `aieh-asset.json` record of its version,
provenance, integrity and reacquisition). `task paths:show` prints every category and creates
nothing; `task paths:init` creates the root; `task paths:doctor` reports what exists and the
legacy locations, and moves nothing.

`example_config.yml` is the tracked template; copy it to the gitignored `config.yml` to
override a category's directory (relative to the effective root, or absolute). Its absence is
the supported default, it never holds secrets, and `.env` is never read. Reading it needs
PyYAML (`task tools:install`).

F-07.1 defines the contract only. The integration store, the publication gate's Gitleaks cache
and the guest tooling keep their current locations until F-07.2 adopts it, and nothing is moved
or deleted. Details, the error codes and the OS-managed locations that stay outside the root
are in the component's [README](../integrations/paths/README.md).

## Host Gitea

[`integrations/gitea/`](../integrations/gitea/README.md) runs the local Git service of plan leaf
F-06.1 on the Owner's Windows host: Gitea 28.3.0's official Windows binary
(`gitea-28.3.0-windows-amd64.exe`, pinned by sha256 in `composition/lock/components.lock.json`
after three upstream sources agreed), bound to `127.0.0.1:13300` only, as the current user without
elevation. There is no WSL, VM, Windows service, scheduled task, PATH, registry or firewall change.
The qualification record is [`evidence/F-06.1-gitea-loopback.md`](../evidence/F-06.1-gitea-loopback.md).

Everything Gitea uses comes from the [managed data root](#managed-data-root): the verified binary is
an asset (`assets/release-binaries/gitea/28.3.0/`), its configuration and state are in
`persistent/gitea/`, its logs in `persistent/logs/gitea/` and its temporary files in
`ephemeral/tmp/gitea/`. `app.ini` holds Gitea's secrets (class E). During bootstrap any process of
the Owner's account, host agents included, can read it and the SQLite database
(`fd-bootstrap-shared-identity`).

Lifecycle, in order:

1. `task gitea:install` (network once): the root, the verified asset, `app.ini`.
2. `task gitea:up`: a supervising managed environment starts Gitea inside a Job Object with
   `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, so Gitea cannot outlive the supervisor; `task gitea:down`
   stops it with Gitea's own `manager shutdown`. Killing the supervisor ends Gitea too.
3. `task gitea:identities`: the site administrator `aieh-site-admin` and the separate
   non-administrator Owner account `aieh-owner` (decision 0007), each with a temporary password that
   Gitea generates and that is written only into the credential provider
   (`AIEH Gitea site-admin (temporary)`, `AIEH Gitea owner (temporary)`).
4. `task gitea:finalize-credentials`: the harness replaces both temporary passwords with final ones
   that it holds in the provider (`AIEH Gitea site-admin`, `AIEH Gitea owner`), revokes every token of
   both accounts, verifies, and deletes the temporary entries. The Owner never signs in to Gitea or
   opens Credential Manager (Owner directive of 2026-11-07, superseding F-06.1's manual first
   sign-in). How it works and why it never exposes a password:
   [integrations/gitea/README.md](../integrations/gitea/README.md#identities-and-credential-finalization).
   Live-verified on 2026-11-07 ([F-06.1 section 8](../evidence/F-06.1-gitea-loopback.md)).

`task gitea:status` and `task gitea:verify` report the state and the proof set at any time.

**The host-service lifecycle contract (F-06.2).** `gitea_host.py` composes the contract and the Windows adapter of [`integrations/platform/`](../integrations/platform/README.md) (draft decision 0011): the verbs install, up, down, restart, status, inspect and verify; credential provision, rotate and retire; upgrade, recover and uninstall; the records `aieh-platform/1`, `aieh-service-run/1` (it generalises `aieh-gitea-run/1`, still read), `aieh-readiness/1` and `aieh-service-transition/1`; and the refusal codes `PLATFORM_UNSUPPORTED`, `PLATFORM_MISMATCH`, `SUPERVISION_UNAVAILABLE`, `NO_CREDENTIAL_PROVIDER`, `CREDENTIAL_PROVIDER_LOCKED`, `VERSION_MISMATCH`, `DOWNGRADE_REFUSED`, `TRANSITION_PENDING` and `UNINSTALL_RUNNING`, each with its remedy. Every act ends with the I7 no-exposure scan of what it shows. Credentials are reached through the harness's credential provider ([`integrations/credentials/`](../integrations/credentials/README.md), F-06.3), which the adapter supplies through a fail-closed factory: Credential Manager on Windows, keyring with an explicitly instantiated backend on Linux and macOS; every rotate or retire act (`finalize-credentials` per account, `gitea:roles -- rotate` and `retire`) writes an integration-store receipt, fingerprints only, into `persistent/state/integration/integration.sqlite` of the managed root and reads it back. How each verb maps onto Gitea: [integrations/gitea/README.md](../integrations/gitea/README.md#the-lifecycle-contracts-verbs). Windows record: [`evidence/F-06.2-platform-windows.md`](../evidence/F-06.2-platform-windows.md). Linux and macOS are **not yet verified** (F-06.4, F-06.5).

**Role credentials (S-01.2.2).** `task gitea:roles -- provision` creates one restricted,
non-administrator Gitea Bot account per role that holds a Gitea credential (`aieh-bot-planner`,
`aieh-bot-builder`, `aieh-bot-reviewer`, `aieh-bot-verifier`; no password, so no interactive sign-in)
and mints each token with Gitea's CLI using the narrowest categorical scope (`write:repository`, the
verifier `read:repository`). Owner decision OA-16 adds the protection auditor `aieh-bot-protection-audit`
(`read:repository`, repository administrator of the fixture only; planned, not provisioned), whose
token the authorization recorder's protection check (`task gitea:protection-check`) alone reads. The token goes from the CLI's captured output into one Credential
Manager entry, `AIEH Gitea bot <role>`: the bootstrap custody until the dispatcher exists. Gitea
28.3.0 has no token lifetime, so tokens rotate (`-- rotate ROLE`, through `DELETE /api/v1/token`).
`-- fixture` creates the authorization fixture (organization `aieh-authz-fixture`, repository
`authz` with merge commits as its only merge style, protected `main` with `aieh-owner` as the only
merger, three rules each total over Gitea 28.3.0's 34 rule fields) as the site administrator, by basic
authentication with its harness-held password in memory and no token. Gitea refuses that account's
API calls until its temporary password is replaced, so it runs only after step 4. `task gitea:authz` then runs the live allowed and forbidden calls. Record:
[`evidence/S-01.2.2-segregated-credentials.md`](../evidence/S-01.2.2-segregated-credentials.md).

## Integration store

[`integrations/store/`](../integrations/store/README.md) holds the Integration
Service's trusted-host SQLite store (`integration.sqlite`, plan leaf F-05.1):
attempt reservations, their append-only transition history, versioned migrations
and rebuildable `proj_` projection tables. It uses the standard library `sqlite3`
and needs SQLite 3.38.0 or newer, which it checks when it opens a store. The
transaction policy, schema and states are in its README.

Always pass an explicit database path. The default trusted-host location, which
`store:path` prints, is per-user application data:

- Windows: `%LOCALAPPDATA%\ai-engineering-harness\state\integration.sqlite`
- elsewhere: `${XDG_DATA_HOME:-~/.local/share}/ai-engineering-harness/state/integration.sqlite`

Neither setup nor the tests create it: a consumer initialises it when it first
needs it. Keep the file on local disk, outside the repository (the store refuses
a path inside the checkout), out of agent workspaces and out of guest storage.

Backup and restore (F-05.2, [decision 0004](../decisions/0004-privileged-effect-store-custody-and-restore-semantics.md))
use the SQLite online backup API, never a copy of the live files. `store:backup`
writes the copy and a sha256 manifest to `<db dir>/backups/`. `store:restore`
verifies the backup, needs exclusive use of the store, refuses a rollback unless
explicitly accepted, keeps the superseded store in `backups/superseded/`, drops
the projections and opens a restore epoch. New attempts are refused until
reconciliation closes the epoch. Details are in the store's
[README](../integrations/store/README.md#backup-and-restore).

Typed attempt identity (E-01.1.1, migration 0003): `reserve_attempt` reserves a
Work attempt under its Backlog.md task id, design revision
(`openspec:changes/<change>@<commit>`), stage (`implement` or `review`), ordinal
and its profile, agent-manifest, planned-workspace and policy digests. SQLite
enforces the canonical key, the immutable identity and at most one live attempt
per work, design revision and stage. Stores created before 0003 migrate when
opened; their attempts stay valid and untyped. The contract is in the store's
[README](../integrations/store/README.md#typed-attempt-identity). No live store
has been migrated: **not yet verified** outside the tests' throwaway directories.

## Dispatch input resolution and admission

[`integrations/dispatch/`](../integrations/dispatch/README.md) is the trusted-side resolver of
dispatch step 01 (plan leaf E-01.2.1, blueprint `#execution-qualification`). A dispatch
request names identifiers only: the Work (a Backlog.md task id), the repository, the stage,
the execution profile and the agent catalog pin. The resolver checks them against the
approved-input manifest, Backlog.md's own readiness, the task's OpenSpec source pointers and
the profile file's sha256. It returns an immutable record for `reserve_attempt` (design
revision, profile, agent manifest and policy digests, planned workspace, and the manifest
version and digest that approved them), or a typed refusal with a stable code, before any
reservation or external call. A field that tries to supply a path, digest, mount, resource,
runtime, revision or ordinal is refused, as is any unknown field.

The live manifest is an authorization record under the managed data root,
`<state>/dispatch/approved-inputs.json` (`dispatch:manifest-path`); a manifest inside the
checkout is refused. The repository holds only its schema check (`dispatch:check-manifest`),
a synthetic example and test fixtures. Writing the live manifest belongs to governance and,
for catalog pins, to A-01.1. Until A-01.1 promotes an approved catalog pin, every dispatch is
refused: that is intended. No live manifest, Backlog.md or store has been used: **not yet
verified** outside the tests' throwaway directories.

The same package holds the create admission of dispatch step 03 (plan leaf E-01.2.2, slice
(a)). After the reservation, `admit` builds the one OpenHands create of the attempt from
trusted policy only. The route is `POST /api/conversations`, and the profile's pinned route
allowlist must admit it. The body is the profile's sha256-pinned create template with the
reserved conversation id: Docker runtime named explicitly, the server-provisioned `/workspace`,
no cap but the declared one, no field outside the allowlist. The policy it enforces is read
from the approved profile into the policy digest (policy-inputs/v2): Docker only and not
selectable, the conversation caps times the concurrent runs within the guest ceilings, the
declared mount set. The planned workspace is resolved under the `workspaces` category of the
managed data root: device names, path tricks, another attempt's path and links or junctions on
disk are refused. `send_create` runs every check again immediately before the injected
transport and sends the create exactly once; an admission refusal never reaches it.

`dispatch` (plan leaf E-01.3.1) is the dispatcher's order on one request: resolve,
`reserve_attempt`, admit and `send_create`, where admit and `send_create` receive the record
re-read from the store (checked against its digest and its typed identity). The host workspace
is created only after admission, one directory at a time and never through a link or junction.
Every Agent Server call goes through `AgentServerClient`, which refuses any route that the
profile's pinned allowlist (`agent-server/routes.json`) does not list exactly once as
`dispatcher` `allowed`, before the transport is called. Before the create, `GET /server_info`
must show decision 0001's preconditions P1 to P5: the pinned version, the capabilities
`conversation_runtime_routes_v1` and `idempotent_conversation_create_v1`, runtime `docker` and
no selectable runtime. A refusal marks the attempt `failed`. A 200 or 201 carrying the reserved
conversation id marks it `confirmed`, with the returned identifiers (and nothing else of the
answer) as the transition's detail. A 4xx is `failed`, and no answer, a 5xx or another id is
`unknown` until it is reconciled; nothing is retried. Every reservation carries `workRef` and
`outcomeRef`, the Work's one `outcome:` reference (decision 0008), the keys the lineage reader
reads. Its live transport is `GuestTransport` (plan leaf E-01.3.3,
[`integrations/dispatch/guest_transport.py`](../integrations/dispatch/guest_transport.py)): each
call is one request through `tools/guest.py`'s `GuestApi`, over the instance's host-loopback SSH
forward with its per-instance key, as the guest login the profile declares (`agent`), the login
that reads the management key from its `root:agent 0440` file. The key is read in the guest only,
never on a command line and never in the host process, and an answer that carried it is refused;
the transport records each call's status and the body's sha256, never a body. During bootstrap
that is the dispatcher principal (decision 0013 point 1): the Owner's account through the dispatch
module. Only fakes have driven `dispatch`, including a fake ssh running the real API probe against
a loopback fake server: no management key or Agent Server, **not yet verified** live.

`attempt_role_token` (plan leaf E-01.3.3) delivers a confirmed attempt's stage bot token into the
dispatcher's own attempt context: `implement` the builder's, `review` the reviewer's, each read by
name from the credential provider and checked against Gitea's own `GET /api/v1/token` (the bot's
login, exactly its scopes). It refuses a missing or mismatched credential, and while it is open the
Agent Server client refuses any call that would carry the token or its fingerprint into the guest.
Records carry the fingerprint only. Per-attempt rotation, the management key's custody and the
op-as-* cut-over are not built ([`evidence/E-01.3.3-dispatcher-custody.md`](../evidence/E-01.3.3-dispatcher-custody.md));
only fakes have been used, **not yet verified** live.

Slice (b) sent one admitted create live:
[`integrations/dispatch/tests/live_admitted_create.py`](../integrations/dispatch/tests/live_admitted_create.py)
(not a test module; `discover` never runs it) builds the request exactly as slice (a)'s positive
control does, from the real `strong-windows-qemu-whpx` declaration with only
`status.operational` set in a throwaway copy, and `send_create` handed it to `tools/guest.py`'s
own one-POST bridge to a running drill guest's Agent Server over the management SSH channel.
Since E-01.3.3 the drill has no bridge of its own: `GET /server_info` and the create go through
the dispatch module's `GuestTransport` on the drill's `GuestApi` (not run live since). The
created container's mounts, caps and runtime are then compared with the admitted ones, and the
drill checks that exactly one create was sent
([`evidence/E-01.2.2b-live-drills.md`](../evidence/E-01.2.2b-live-drills.md)).
No live manifest, store or managed root was used: every dispatcher input stayed in the
fixture's throwaway directories.

## Inference broker

The host-side inference broker of [decision 0015](../decisions/0015-inference-broker-placement-provider-credential-custody-and-guest-inference-endpoint.md) as amended (plan leaf S-03.2) is in [`integrations/inference/`](../integrations/inference/README.md): two `127.0.0.1` listeners (control: issue, revoke, status; inference: per-family, untranslated pass-through under per-attempt tokens), the declared API families in `families.json` (route sets provisional until pinned from observed traffic), the Owner's settings in `components.inference_broker` of `config.yml` (ports, and per family the provider id, the upstream origin and the model allowlist, which ships empty), the provider key in the credential provider entry `AIEH model provider`, receipts in the integration store and audit lines in `persistent/logs/inference/`. Slice 1 is built and tested offline only (`task inference:test`). Running the broker, its host listeners, the provider key, the guest forward, egress and any model call are each their own Owner act and are **not yet verified**.

Three host-side tools for S-03.2's guest qualification (slice 4, [record](../evidence/S-03.2-slice4-qualification-tools.md)) are built and tested in process only and are **not yet verified** live; running them is part of the Owner's act A2:

- `<synthetic key> | <tools python> -I -B integrations/inference/inference_qualification.py broker --provider ID`: the qualification launcher, a separately named command (never a flag of `serve`). It runs the broker's own `serve` with a synthetic key held in memory, refuses unless every configured family's upstream is plain `http` to a loopback IP literal, reads the key from standard input only (never a terminal) and requires the synthetic prefix `aieh-qualification-synthetic-`; the start receipt records the key's fingerprint with the source `stdin-qualification`, and the key is written nowhere.
- `<tools python> -I -B integrations/inference/inference_qualification.py fake-upstream --family ID --port PORT`: one declared family's fake upstream on `127.0.0.1` (any non-loopback address refused), a fixed answer that is not a model's with usage the broker reads, and one JSON line per request on standard output: method, path, header names and the fingerprint of the received credential, never a header value or a body.
- `<tools python> -I -B integrations/inference/inference_control.py issue --conversation-id UUID --family ID --model NAME --requests N --tokens N --ttl-s SECONDS | python -I -B tools/guest.py job-access-probe ... --attempt-token-stdin`: one grant from the control listener; the token goes to standard output only, which must be a pipe (a terminal, a file or a device is refused), and standard error carries only the attempt id and the token's fingerprint.

The provider-key containment search of S-03.2's proof as amended (slice 5, [record](../evidence/S-03.2-slice5-key-containment-search.md)) is built and tested in process only and is **not yet verified** against a live broker or guest:

- `<synthetic key> | <tools python> -I -B integrations/inference/inference_key_search.py search --expect-fingerprint sha256:<16 hex> --surface LABEL=KIND:PATH [...]`: the synthetic key from standard input only, held in memory and checked against the start receipt's fingerprint, searched for raw and in its encodings (hex, base64 and base64url at three alignments, UTF-16, the body without the prefix, raw fragments), never by fingerprint, over files, directory trees, tar streams and this process's environment, with gzip, SQLite-row and read-boundary views and in-memory positive controls. It reports counts per surface and a verdict that covers the bytes searched only; it prints, logs and writes no copy of the key. Exit 0 not found, 1 found, invalid or incomplete, 2 refused.

## Effects store

[`integrations/effects/`](../integrations/effects/README.md) holds the privileged
executor's effect store (`effects.sqlite`, plan leaf F-05.2, decision 0004):
one-time effect receipts, an append-only, hash-chained journal, reconciliation
records and restore epochs. It is separate from the integration store in every
respect: database, directory, migrations, `application_id`, backup line and owner.
It is a library and a command line only.

There is **no default path**. `ROOT` must be an existing directory on a local
fixed volume, outside the repository, every user profile (including
`%LOCALAPPDATA%`), every guest-state root and the integration store's tree. On
every open the store reads back the root's owner and DACL and refuses anything
but the custody template: inheritance removed, and access for SYSTEM,
Administrators and the configured principal only. The Owner creates that root
from an elevated window (act A4 at G-04.2.1). Until then the store is proven
only on test fixtures, and **no live effects store exists**. The tests use a
library-only fixture policy that allows `%TEMP%`; the command line cannot select
it.

## Execution guests

[`tools/guest.py`](../tools/guest.py) implements the lifecycle bindings of the Windows
strong profile, [`profiles/strong-windows-qemu-whpx`](../profiles/strong-windows-qemu-whpx/README.md)
(plan leaf F-03.2.2), under the contract in [`profiles/README.md`](../profiles/README.md).
It needs the Owner acts A1 to A3 in that profile's
[`PREREQUISITES.md`](../profiles/strong-windows-qemu-whpx/PREREQUISITES.md), and runs on
Windows only. The profile and the state directory are named on every call; nothing
defaults them.

- `create` refuses an existing instance, checks every pinned digest, generates a fresh
  ed25519 key with Windows' built-in `ssh-keygen` into the instance's `ssh\` directory,
  creates the disks and the seed, writes `launch.json` (every boot input with its
  digest, the argv, the profile revision; it refuses uncommitted changes under
  `profiles/`), and launches QEMU detached. It then waits on observable signals under
  one ceiling (`--ready-timeout`, default 600 s): QMP answering with the profile's
  accelerator, cloud-init's host-key block on the serial log (written to the
  instance's `known_hosts`), the SSH banner, and `cloud-init status --wait`.
- `inspect` prints, and writes under `<state>\instances\<name>\records\`, a record of
  profiles P1 to P12: declared value, observed value, method and PASS, FAIL or UNKNOWN
  per check. It includes the guest egress probes, which are evidence toward F-03.3.2,
  not its formal suite.
  The record also carries `compatibility`: the XSAVE detector reads the guest kernel's
  messages from the instance's `serial.log` on the host (no guest privilege) and from
  `dmesg` when `agent` may read it. `XSAVE consistency problem` or `XSAVE disabled` is
  a FAIL (the operation exits 1); `x86/fpu: misordered xstate` is a recorded
  limitation (profile README, open item 3). P11 checks that `launch.json`,
  `process.json`, every record and every `stderr.log` header carry the profile's
  labels; each launch writes one `AIEH-LOG-HEADER` line to `stderr.log` first.
- `preflight` also asks the Windows Hypervisor Platform whether it offers XSAVES
  (`WHvGetCapability`, read-only; nothing is installed). Without XSAVES the profile's
  `-cpu max` is expected to panic the guest kernel, so preflight reports `unavailable`;
  when the query itself fails the check is `unknown`, disclosed and not refused.
- `stop` is QMP `system_powerdown`, then QMP `quit` after the profile's
  `stop_timeout_s`, then terminating that process id only (`--force` skips
  `system_powerdown`). `destroy` stops with force if needed and deletes the instance
  directory only; an absent instance reports `absent`. `recreate` takes `--canaries`
  like `create`.
- `smoke` (F-03.4) is the provision/inspect/teardown test of profiles P10, on a fresh
  instance name: preflight; create; inspect (P3 to P6 must PASS, every property PASS
  except P10, no XSAVE FAIL); graceful stop; start from `launch.json`; inspect; forced
  stop; recreate; inspect; destroy; destroy again (`absent`). The inspect records are
  compared across the start (every field equal) and across the recreate: each check
  is classified in `CHECK_CLASSES` as stable (equal after a named normalisation that
  drops ports and optional mounts), per-instance (machine-id, host keys, instance id,
  seed: equal across start, different across recreate) or volatile (recorded only).
  Before and after each destroy and recreate it inventories the durable sources: the
  checkout (`repo-inventory/2`: HEAD, the tracked changes, the index digest), the state directory's
  pinned image and provider prefix, every other `instances\` entry (a running sibling's
  disks and logs are volatile; its other files are hashed and its QMP status is
  recorded), and the `--durable` roots the operator names, which stand for Owner data.
  Any difference fails. It never lists the state directory itself. One verdict, PASS
  or FAIL, is printed and, with `--out`, written to a new file outside the checkout.
- SSH always uses the profile's client options plus `BatchMode=yes`,
  `IdentityAgent=none`, `GlobalKnownHostsFile=none` and the per-instance key. The tool
  refuses to run `ssh` when that key is missing, because `ssh -i` with a missing file
  silently falls back to the identities in `~/.ssh`.
- `exchange-push` and `exchange-pull` (F-03.3.1) use Windows' built-in `sftp.exe` with
  the same options and key (`-S` names the built-in `ssh.exe`). A push is one local
  branch as a complete git bundle within the profile's `exchange.push` bounds. Since
  F-10.4 it is written in process by the shared repository-access module (`write_bundle`,
  under the `repository` configuration policy; no git is launched), and checked in Python
  (exactly one `refs/heads/` reference at its commit, no prerequisites, the bounds, the
  recomputed pack checksum) before it is copied under a new name. A pull copies one regular
  file of the guest's exchange directory into `<instance>\exchange\inbound\`; a bundle
  is verified in a fresh bare repository there, never in an Owner repository, by git:
  `init --bare`, the prerequisite fetches, `bundle verify`, the fetch, the per-reference
  `rev-parse --verify` and `fsck --strict` (decision 0014 section 7: git stays the
  integrity authority; a Dulwich walk may only be added). Both directories are inside the
  instance directory, so `destroy` removes them.
- `create` records the profile revision (HEAD, and a refusal when `profiles/` has
  uncommitted changes) and `smoke` takes `repo-inventory/2` snapshots of the checkout (HEAD,
  the tracked changes, and the sha256 of the index's canonical rendering: one
  `<mode> <id> <stage><TAB><path>` line per entry, raw UTF-8, sorted, each ending in LF),
  both read in process by the repository-access module under the `host` policy, each
  recording its `config_sources`. `gitea_host.py`'s checkout listing for the secret-leak
  scan is the module's `listing` (cached, others, exclude-standard) under `host` too.
- `check-surfaces` is the startup inspection test for profiles P3 to P6. It runs
  `inspect` and passes only when all four properties PASS: the guest's mounts, disks,
  block nodes and directories equal the profile's `guest_storage` table exactly; the
  Owner-class scan with its positive control finds nothing, and no value of the canary
  set appears in the guest, its seed, its launch record or its serial log; no
  host-management socket, channel, display or environment variable is present, and QMP
  is not reachable from the guest. The canary set comes from `canaries` and is planted
  by `create --canaries`; canary values never travel to the guest (the guest's files
  come to the host and are searched there), and records carry only their sha256.
- `netprobe` (F-03.3.2) is a **test-only validation mode**, authorized by decision
  0003, "Owner authorization: network validation". It starts one listener process
  with three sockets on 127.0.0.1 at OS-chosen ports: the test listener, which only
  answers a nonce exchange, and a TCP and a UDP decoy that are never forwarded. It
  then creates a disposable guest whose seed carries a second user-data part, the
  pinned probe script
  [`validation/netprobe/netprobe.py`](../profiles/strong-windows-qemu-whpx/validation/netprobe/netprobe.py),
  which cloud-init runs once as root. The guest's `-netdev` also gets one
  `guestfwd=tcp:10.0.2.100:7000-tcp:127.0.0.1:<listener port>`. As root, the probe
  adds a default route, resolvers and an IPv6 address and route, exchanges the nonce
  through the forward, tries every denied path (public IPv4 and IPv6 literals, ICMP,
  DNS, the host's addresses, the host's loopback through `10.0.2.2`, the decoys), and
  repeats this from a network namespace behind guest NAT. `netprobe` collects the
  result and the listener log, stops the listener, checks that its sockets were on
  127.0.0.1 only and are gone, and gives the machine verdict for P7. `launch.json`
  records the instance as a validation instance with the full effective argv. The
  ordinary `create` takes none of these inputs, `launch` refuses a `guestfwd` that no
  validation record declares, and `start` refuses a validation instance. `inspect` of
  a validation instance adds the netprobe checks to P7; for an ordinary instance, P7
  cites the enforcement point's qualification. Destroy the instance after the cycle.
- `provision-fetch` (F-04.1a) is the host side of guest provisioning
  ([decision 0006](../decisions/0006-guest-provisioning-channel-and-image-conformance.md),
  Proposed). It reads the profile's
  [`provision.lock.json`](../profiles/strong-windows-qemu-whpx/provision.lock.json)
  after its bytes match the profile's pin (`provider.provision_lock`), downloads the
  Debian indexes and packages from snapshot.debian.org and the Agent Server release
  binary from GitHub (https only, size and sha256 checked while streaming), and installs
  the pinned crane into `<state>\tools\crane\<version>\` after checking the archive and
  `crane.exe` against the lock. Crane runs with a scrubbed environment and an empty
  `DOCKER_CONFIG`; `crane manifest` bytes must hash to the locked index and platform
  digests, and the archive from `crane pull` must hold exactly the locked config (the
  image ID) and layers. Work happens in `<state>\provision\<lock sha256>.partial\`
  (resumable) and is renamed to `<lock sha256>\` with a `staged.json` manifest only
  when everything verified; a later run re-verifies and reuses it. A mismatching
  download is kept as `*.rejected` and nothing is staged. No `.deb` is unpacked and no
  image is run on the host. The run is in
  [`evidence/F-04.1a-provision-pins-fetch.md`](../evidence/F-04.1a-provision-pins-fetch.md).
- `create --provision` and `provision` (F-04.1b) are the guest side. `create --provision`
  re-verifies the stage and writes its manifest (each `.deb`, the image archive and the
  release binary with size and sha256; the locked image ID; the local tag
  `aieh/agent-server:1.60.1-b43ee580`; the declared `daemon.json`) into the seed, which
  always carries the single-use root step ([seed README](../profiles/seed/README.md));
  the launch record keeps the manifest digest. `provision` then checks that the stage
  still gives that manifest, that the trigger is armed and that nothing was uploaded
  before; copies the files by SFTP into `/srv/scratch/agent/provision/` within the
  profile's `provisioning.upload` bounds; checks each in the guest; creates `READY`; and
  waits, in one SSH session, on an inotify event for
  `/var/lib/aieh/provision/RESULT.json` under the `root_step.timeout_s` ceiling (waking
  every 10 s only to notice a failed unit). The root step copies to a root-only staging
  directory, verifies, writes `daemon.json` and a sysctl drop-in (no IPv6 on Moby's
  interfaces), installs with `apt-get install --no-install-recommends ./…` (never
  `apt-get update`), turns containerd's CRI plugin off, loads the image, checks its ID,
  keeps only the local tag, runs it once with `--entrypoint true`, enables the boot-time
  facts report, deletes the upload and the staging directory, disables its trigger and
  writes `RESULT.json` last. `provision` fetches and checks it into
  `<instance>\provision\` and writes a record with the timings. It is single use:
  recovery is `recreate --provision`, then `provision`. `inspect` of a provisioned
  instance adds the Moby checks (P6 sockets and the `agent` refusal, P7 TCP listeners,
  P8 group, and a `provisioning (F-04.1)` entry: version, daemon, image, containers,
  modules, leftovers, units), reading root's boot-time report
  `/run/aieh/docker-facts.json` as `agent`.
- The guest inference endpoint's composition (S-03.2 slice 2, decision 0015 section 4) is
  **opt-in per guest and planned**: `create --provision --inference` (never with
  `--drill`, and never a netprobe instance) applies it, and applying it to a guest is the
  Owner's guest hardening act, not yet authorized. **Not yet verified in a guest.**
  The profile declares it in `network.inference_composition`: the seed overlay
  [`profiles/seed/inference-overlay.json`](../profiles/seed/inference-overlay.json),
  pinned by sha256, whose exact text edits `tools/nocloud_seed.py --inference` applies to
  the user-data template (each anchor exactly once): the sshd drop-in's
  `AllowTcpForwarding no` becomes `AllowTcpForwarding remote`,
  `GatewayPorts clientspecified` and `PermitListen 172.17.0.1:8090`; the container guard
  gains one ACCEPT after its RETURN, IPv4 only
  (`-d 172.17.0.1/32 -i docker0 -p tcp -m tcp --dport 8090 -j ACCEPT`); and the boot
  facts report `sshd -T`'s forwarding directives. The manifest's `daemon.json` gains
  `bip` (`172.17.0.1/16`) and `dns` (`["172.17.0.1"]`), and the launch record an
  `inference` block. **Without the option the seed, the manifest and every guest-visible
  file are byte-identical to before** (`tools/tests/test_nocloud_seed.py` pins the
  digests computed at `0b8af57`). The egress guard's allowlist stays empty. `inspect`
  verifies the state the launch record names: off, the ordinary drop-in, the four guard
  rules, the profile's `daemon.json` and nothing on the endpoint's port; on, the composed
  drop-in, `sshd -T`, the guard's ACCEPT in iptables only, `bip` and `dns`, and the
  endpoint listened on by sshd exactly when a forward session is held (a record
  `<instance>\inference-forward.json` whose ssh process still runs).
  `inspect --provider-key-fingerprint sha256:<16 hex>` makes the provider key a P5
  needle (every secret-shaped run of the collection and the host files is fingerprinted);
  for an opted-in guest that check is UNKNOWN without it. With `--provider-key-stdin` as
  well (S-03.2 slice 5: the synthetic qualification key, the key of that fingerprint, on
  standard input), the collection and the host files are also searched for the key
  itself, raw and encoded, on the host (`integrations/inference/inference_key_search.py`);
  for an opted-in guest that check is UNKNOWN without it, since a fingerprint alone is not
  proof that the raw key is absent. `job-access-probe --attempt-token-stdin
  --provider-key-stdin --provider-key-fingerprint FP` (the token, then the key, on standard
  input) searches every answer the job and the guest login received from the endpoint,
  returned whole up to 64 KiB and never recorded. The key never travels to the guest. `job-access-probe` on an
  opted-in guest adds the inference sweep from both jobs: the endpoint must answer 401
  without a token, the allow's edges (`172.17.0.1:8091`, UDP to the endpoint,
  `10.0.2.15:8090`) and the resolver (`172.17.0.1:53`) must be refused with the
  container guard's IPv4 REJECT counters rising, and a name lookup must fail; an edge
  that answers or a name that resolves is a stop condition; once from the guest's own
  login (outside every container) the endpoint must refuse a request without a token
  (401 `TOKEN_MISSING`: while a forward is held the token is the only admission control
  for the guest's own processes, `nm-guest-inference`). The containment catalogue
  declares the matching cases as `planned`.
  **The forward session (S-03.2 slice 3, offline only):** `inference-forward --action
  start|status|stop` holds `ssh -N -R 172.17.0.1:8090:127.0.0.1:<broker inference port>`
  for an opted-in instance with `ssh_client_options`, the per-instance key, the hostfwd
  port and the forward's own options (`network.inference_composition.forward_session`:
  `-N -v`, `ExitOnForwardFailure=yes`, keepalives). A detached holder starts ssh, writes
  the record (pid, binary, creation time, holder pid, ports, argv) once ssh reports
  `remote forward success`, waits on ssh and removes the record when the session ends;
  `start` returns a held session, replaces a stale record and never retries on its own;
  `destroy` stops a held session first and `recreate` carries the composition from the
  launch record (it then needs `--provision`). `job-access-probe --attempt-token-stdin`
  reads one attempt token from standard input and, from inside the token's own job, shows
  it forwarded to the family's upstream, refused (401 `TOKEN_REVOKED`) after the probe
  revokes it through the broker's control listener, refused (`ECONNREFUSED`) while the
  forward is stopped and refused again after it is re-established; the token travels only
  in a script's text on standard input and records carry its fingerprint. Both are
  **not yet verified** against a real ssh, broker listener or guest (Owner acts A2-A4).
- The same root step installs the OpenHands Agent Server (F-04.1 slice (c)): the release
  binary as `aieh-agent-server.service` under the no-login system user `openhands`
  (group `docker`), bound to the guest's `127.0.0.1:8000` only, configured by the
  profile's `provisioning.agent_server` (Docker runtime, the local immutable image,
  explicit caps, every data path under `/srv/scratch/openhands`), with `OH_SECRET_KEY`
  and the session API key generated in the guest into a root-only environment file.
  `provision` fetches the session key alone into `<instance>\agent-server\session.key`
  (destroyed with the instance; records hold fingerprints only). `inspect` adds the
  `/server_info` runtime conditions of decision 0001 s2 (queried as `agent` on the guest
  loopback), the binary, service, config, engine endpoint, data paths, session-key
  enforcement, the declared listener (P7) and the secret custody and search (P5).
  `python -I -B tools/check_profile.py --openapi <openapi.json>` also validates the
  disposable conversation fixture against the release's `openapi.json` (downloaded,
  pinned by sha256, never committed).
- `conversation-smoke` (F-04.2) runs the disposable conversation of that fixture on a
  running provisioned guest. Every API call runs as `agent` on the guest loopback, with
  the session key read inside the guest from its file. Root-only facts of the
  conversation container come from the on-demand reporter: `agent` creates
  `/var/lib/aieh/facts-request/conversation-facts` (no content is read; at most 20
  requests a minute), `aieh-conversation-facts.service` removes it and writes
  `/run/aieh/conversation-facts.json` from `docker ps` and `docker container inspect` of
  the containers carrying the Agent Server's owner label (environment by name only,
  secret values redacted), root's TCP listeners and the stored conversations. The run
  checks the image ID, the exact mount list, the user, caps and the 127.0.0.1 port
  against `provisioning.agent_server.conversations`, and the amended profiles P7: one
  `docker-proxy` listener on `127.0.0.1` per running conversation container. `inspect`
  uses the same report for its P7 listener checks and its `conversation containers`
  entry. The upstream deviations it records (`host-gateway`, no `--network none`,
  request caps override) are evidence for S-01.3.x and E-01.2.2, not failures.
- `admission-probe` (S-01.3.1) checks the management API admission declared in
  `provisioning.agent_server.admission`. It compares the running server's own
  `/openapi.json` with the pinned route inventory
  ([`agent-server/routes.json`](../profiles/strong-windows-qemu-whpx/agent-server/routes.json):
  every route, its credential, its class and whether the trusted dispatcher uses it),
  then sends every route a request without the key and with a wrong one (WebSockets:
  four refusals each). A key-gated route that answers 2xx without the key is a stop
  condition. It creates two disposable conversations and, through the outer server's
  proxied bash route (the agent's own terminal), connects from inside each container to
  the management listener, the guest's `sshd` and LLMNR, the published ports and the
  peer container at every address the container can see; checks that no readable
  process environment holds the outer key and where `start_child_conversation` sends
  its request; runs the seeded key check under synthetic environments; reads what the
  guard and the server logged; and deletes both conversations. The guest side of the
  admission is seeded: `aieh-container-guard.service` (which `docker.service` requires)
  rejects and logs any new connection from a container bridge to the guest itself,
  `icc` is off on Moby's default bridge, and the Agent Server's `ExecStartPre` refuses
  to start without a valid session key. `inspect` checks all three from the boot-time
  facts.
- The server's start is ordered and fail-closed (E-01.2.2 slice (c)):
  `aieh-agent-server.service` `Requires=` and starts `After=` both `docker.service` and
  `aieh-agent-server-quiesce.service` (never `Wants=`), so a failing guard, Moby or
  quiesce step fails the server's start job with result `dependency`. The quiesce step is
  a seeded root oneshot without `RemainAfterExit`, so every server start (boot, restart,
  `Restart=on-failure`) runs it again first. It removes every container (`docker rm -f`,
  then none may remain), then, for each record of the conversations path, through
  directory-relative opens that never follow a link, acts only on regular, singly linked
  `meta.json` and `base_state.json` files owned by the service user: `execution_status`
  `running` becomes `error` in place, unparseable JSON is left alone, and a record that
  fails a check or whose `meta.json` id is not its directory name is moved aside into the
  root-only `/srv/scratch/aieh-quarantine`, never deleted. Its journal line carries counts
  and hex ids only. This compensates the pinned 1.60.1 server's start-up resume of a
  stored `running` record in its own process (`fd-outer-server-local-recovery` in
  [`security/inventory.json`](../security/inventory.json)). The profile declares it in
  `provisioning.agent_server.quiesce` and `service.dependencies`; `check_profile` checks
  the declaration against the seed template and `inspect` against the boot facts.
- The server's start-up and its readiness wait (E-01.4.3). The unit sets
  `LITELLM_LOCAL_MODEL_COST_MAP=True`, litellm's own switch, so that the bundled cost map
  is used and the start-up fetch, its retry thread and the import race they caused
  (E-01.2.2c finding F-15) do not happen; it reaches the outer server only, not
  conversation containers. The readiness wait (`ExecStartPost`,
  `/usr/local/sbin/aieh-agent-server-ready 127.0.0.1 8000 280 30 ${MAINPID}`) polls
  `GET /ready`, stops at once when the main process has exited (instead of waiting out
  its 280 s ceiling), and prints one outcome line per start: `ready start=<class>` with
  `<class>` `clean` only when the server was ready within 30 s and the unit's `NRestarts`
  is 0, otherwise `retried`, `slow` or `unverified` (comma-joined); or `not ready
  start=main-exited|timeout`. `Restart=on-failure` then starts a failed server again
  after 5 s. The profile declares it in `provisioning.agent_server.start_race` and
  `service.readiness`; `inspect`'s check "Agent Server start (E-01.4.3)" requires the
  control in the unit's and the server processes' environment, `NRestarts` 0 and this
  boot's last outcome line `start=clean`, from the boot facts. Observed on the qualified
  host only ([`evidence/E-01.4.3-start-race.md`](../evidence/E-01.4.3-start-race.md));
  the `slow`, `unverified` and `timeout` outcomes are covered by unit tests only.
- `job-access-probe` (S-01.3.2) proves the job environment declared in
  `provisioning.agent_server.jobs`: each conversation container, where builder and
  reviewer runs execute. It creates two disposable conversations; compares each
  container's `docker container inspect` (from the on-demand facts) with the declared
  values (not privileged, `CapDrop` ALL, no added capability, device or host namespace,
  `SecurityOpt` exactly `no-new-privileges`, AppArmor `docker-default`, no engine or
  credential variable name); and, from inside each container as its default user, reads
  its identity, capabilities, `NoNewPrivs`, seccomp and AppArmor state, the
  credential-like variable names of every readable process, every socket and whether
  `sudo` or `su` gives root. It then tries every declared engine socket and every socket
  it found; the engine ports, the management listener and the published ports at
  `host.docker.internal` and every guest address, and the instance's SSH, QMP and the host
  Gitea port at SLIRP's `10.0.2.2`; every route of the admission inventory at every
  address, without a key and with the conversation's own key; and searches the
  container's readable files and process environments for the outer session key and any
  Gitea token by fingerprint (`--token-fingerprint LABEL=sha256:<16 hex>`, repeatable),
  never by value. An engine socket or API, a management route or a host service that
  answers is a stop condition. `inspect`'s `conversation containers` entry applies the
  same declared values to every container. The CI side of the job constraints is
  recorded as planned (no CI runner exists yet). Since S-01.4 it also runs the
  predeclared egress sweep from inside each job (`1.1.1.1:443`, `8.8.8.8:53` over TCP and
  UDP, SLIRP's `10.0.2.2` host ports and `10.0.2.3:53`, and the unconfigured
  guestfwd-class address `10.0.2.100:7000`), reading the egress guard's per-rule counters
  before and after. Its decision rule is fixed: every target refused with the guard's
  reset or ICMP reject and the guard's counters incremented is a PASS; a timeout or an
  unreachable error alone is topology, not policy (FAIL); a connection is a stop
  condition. After the Overseer's S-01.4 ruling, the no-route sweep records off-link
  targets as topology and leaves them out of its verdict, and a route-present step decides
  instead: on a guest created with `create --provision --egress-falsification` (a
  validation-only manifest flag), a seeded root unit adds a temporary IPv4 default route via
  SLIRP's `10.0.2.2` on agent's request file and always deletes it again; with the route
  present, `1.1.1.1:443` and `8.8.8.8:53` (TCP and UDP) are swept from both jobs and once
  from the guest's own namespace (a control). PASS: every job target refused by the guard,
  its IPv4 REJECT counters up by exactly the attempts and its log lines showing `OUT=` the
  uplink; a timeout or ENETUNREACH is a FAIL; a connection is a stop condition. The step
  removes the route in a `finally` and verifies it is gone. On an ordinary provisioned guest
  the step fails as not available.
- The container egress guard (S-01.4) is seeded with the container guard: the same script
  and unit (which `docker.service` requires) create Moby's `DOCKER-USER` chain when it is
  absent and send every new forwarded connection from `docker0` or a `br-*` bridge to
  another interface to `AIEH-EGRESS-GUARD`, which logs (prefix `aieh-egress-guard: `) and
  refuses it, IPv4 and IPv6, with an empty allowlist
  (`provisioning.agent_server.admission.network.egress_guard`). The root step's admission
  step, the boot facts (with the rules the guard printed before Moby started) and
  `inspect`'s `container egress guard (S-01.4)` check verify it.
- `containment-probe` (S-02.1) runs the versioned containment catalogue
  ([`security/containment-cases.json`](../security/containment-cases.json), refused unless
  its checker passes) in one pass. It runs `admission-probe` and `job-access-probe`
  unchanged and reads their cases from their records; the remaining cases run inside two
  further disposable conversation containers, as the job's default user, after each job
  has written a generated canary file into its own `/workspace/.aieh-probe` (no repository
  content). The attempts are a closed, non-destructive set: reads, listings, `access(2)`
  checks, connects to the container's own loopback, sockets created and closed, namespace
  calls in a forked child that exits at once, an empty module image, and writes only in the
  probe's scratch directories, which it removes. Each case is classified: a denial PASSes
  only when its paired positive control succeeded in the same run (otherwise UNKNOWN); an
  attempt that succeeds is a FAIL and a stop condition (later primitives do not start); a
  missing hardening control or observation is a FAIL, never skipped; a recorded deviation
  (no `--network none`, `host.docker.internal`) PASSes only while its compensating cases
  pass. The record carries a runtime-configuration snapshot before and after (normalized
  `docker inspect` digests, both guards' counters, `daemon.json` and `SecurityOptions`, and
  the profile, seed, manifest, image, route-inventory, fixture and catalogue pins).
  `--sensitivity` also runs the catalogue's mutations: each points a denial case at an
  operation the job may perform and must be classified a success (FAIL).
- `host-census` (S-01.4) is a read-only, unelevated census of the harness's host
  listeners by PID, each of which must be on `127.0.0.1`, with the Windows Firewall
  profiles and rule count recorded as disclosure. It reads no file and changes no rule;
  `--exclude-pid` keeps a process out of every lookup.
- `drill` (E-01.2.2 slices (b) and (c); E-01.4.3) is a **test-only mode** for the
  fail-closed drills and the restart series, under the Owner's extended guest-run
  authorization of 2026-11-07. `create --provision --drill --drill-leaf <leaf>` (with
  `--egress-falsification` and `--canaries` if wanted) seeds
  [`tools/guest_drill.py`](../tools/guest_drill.py) as a second user-data part, which
  cloud-init runs once as root: it installs a root helper behind a `root:agent` `0730`
  request directory (`/var/lib/aieh-drill`), so that `agent` can ask it to break or restore
  a control, alter or roll back a stored conversation, restart the Agent Server, observe
  units, listeners and the server's journal, or scan the guest as root. The profile's
  templates, `launch.argv` and every ordinary `create` are unchanged; the launch record
  marks the instance as a drill instance (`validation.mode` `drill`, the helper's sha256)
  and names the plan leaf it was created for (`validation.plan_leaf`: `--drill-leaf`
  `E-01.2.2` or `E-01.4.3`, required with `--drill`); it has no `guestfwd`, share or new
  host port, and `start` may boot it again. `drill --kind` and `containment-probe
  --drill-defective-control` refuse any other instance, and `drill --kind` refuses a kind
  of another leaf (`restart-series` is E-01.4.3's, every other kind E-01.2.2's); each
  drill record names its kind's leaf (`plan_leaf`). Launch records written before
  `--drill-leaf` name `E-01.2.2 slice (b)` and are read as E-01.2.2.
  - `--kind fail-closed`: the key check (the environment file rewritten without the
    session key, then with a second one) and the guard (a drop-in that makes
    `aieh-container-guard.service` fail before it installs a rule, then one that only
    verifies, so a boot finds no rule), each followed by its restore and a positive
    control; for the guard the guest is rebooted with the failing unit. Slice (c) adds the
    quiesce step: a drop-in makes it fail, then a server restart and a guest boot must
    leave the server not started (result `dependency`, no listener, no process).
  - `--kind stored-state`: one disposable conversation is created and stopped; every field
    of its job-writable stored files (`meta.json`, `base_state.json`, and a planted
    `owner_lease.json`) is altered alone, then the Agent Server restarts (its start-up
    path) and the conversation is reopened; the container's image, mounts, caps, user,
    working directory and keys, the server's runtime and processes, its resume lines in
    the journal of that start and the altered path on disk are compared with a baseline
    cycle, and the directory is rolled back to its snapshot (twice, around a server
    restart). A failed server start is retried once and both attempts are recorded. A
    sensitivity cycle (a create with request caps) shows the comparison catching a cap
    change, and the job itself then writes the start-up pair (`execution_status` and the
    working directory) from inside its container, once with its runtime stopped normally
    and once after killing its own inner server. `--limit N` runs only the first N
    alterations. With the quiesce step, an alteration whose record the step moves aside
    (a `meta.json` id that is not the directory's) is recorded as `quarantined`, is not
    reopened, and is moved back before the rollback.
  - `--kind f2-closed` (slice (c)): the "F-2 closed" drill, its decision rule fixed before
    observation. On fresh disposable conversations: the start-up pair written by the
    helper (A); written by the job from inside its container, then the runtime stopped
    normally (B1) or the container force-killed by root (B2); rewritten by the job in a
    loop while the server is killed and restarted by systemd with the container alive
    (C); an idle record's files kept across a restart, a reopen and a guest restart (D); a
    record claiming another conversation's id (F); `base_state.json` replaced by a symbolic
    link and by a hard link to a sentinel outside the record, whose times show it was
    neither read nor written (G). Each start is judged by the rule: no resume line, no
    `owner_lease.json` from the outer server, no new path under the server's home or the
    record, no `running` left, no container event between the step's end and the server's
    `ExecStart` (Moby's events), and the step's result `success` while the server is
    active.
  - `--kind root-scan --canaries <set> [--raw]`: the guest-root P5 scan. As root, every
    regular file of every disk-backed and tmpfs mount and every process environment and
    command line is searched for the canary set's cores (by sha256, the values never
    enter the guest), the guest's own secrets (by value, in the guest), private-key blocks
    and Owner-class patterns, with a planted positive control; `--raw` also counts the
    secrets and canaries on the raw block devices. A secret is allowed only in its declared
    store.
  - `--kind restart-series [--limit N]` (E-01.4.3; on a guest created with `--drill-leaf
    E-01.4.3`): N consecutive restarts of the Agent Server (default 500) through the
    helper (`systemctl restart`, which also re-runs the quiesce step and the key check).
    Each is recorded with its rc, its in-guest time, the unit and the readiness wait's
    outcome line; the journal of that start is kept in full only when it was not clean. A
    failed start is followed until systemd's `Restart=on-failure` start is active, with
    its own outcome line and time. The record gives the main-process exits during start,
    the failed starts and their retries to readiness, the outcome classes and the
    distributions (min, p50, p90, p99, max, 1-second buckets) of the ready wait and the
    restart. Then the server is SIGKILLed: its `Restart=on-failure` start must report
    `start=retried`, and one manual restart is recorded. PASS only when all N ran with no
    main-process exit during start and no failed start (the leaf's decision rule).
  - `containment-probe --drill-defective-control <id>` replaces a positive control with an
    attempt that cannot succeed: its cases must become UNKNOWN and the run must not PASS.

  The live check of slice (a)'s admitted create runs from
  [`integrations/dispatch/tests/live_admitted_create.py`](../integrations/dispatch/tests/live_admitted_create.py)
  (see [Dispatch input resolution and admission](#dispatch-input-resolution-and-admission)).
  There is no Task target. Destroy every drill instance afterwards. The observed runs are in
  [`evidence/E-01.2.2b-live-drills.md`](../evidence/E-01.2.2b-live-drills.md) and, for the
  restart series (on the qualified host only),
  [`evidence/E-01.4.3-start-race.md`](../evidence/E-01.4.3-start-race.md).

Each operation prints one JSON object. The first real boot cycles are in
[`evidence/F-03.2.2b-guest-lifecycle.md`](../evidence/F-03.2.2b-guest-lifecycle.md);
the exchange and surface-test cycles (F-03.3.1) are in
[`evidence/F-03.3.1-guest-surfaces.md`](../evidence/F-03.3.1-guest-surfaces.md); the
network validation (F-03.3.2) is in
[`evidence/F-03.3.2-guest-network.md`](../evidence/F-03.3.2-guest-network.md); the
conversation lifecycle (F-04.2) is in
[`evidence/F-04.2-conversation-lifecycle.md`](../evidence/F-04.2-conversation-lifecycle.md); the
teardown test and the provider-profile qualification (F-03.4) are in
[`evidence/F-03.4-teardown-qualification.md`](../evidence/F-03.4-teardown-qualification.md)
and [`QUALIFICATION.md`](../profiles/strong-windows-qemu-whpx/QUALIFICATION.md).
The profile is **operational on the qualified host only**, since 2026-11-09, by the
Overseer's C6 decision; a new host, a changed pin or a guest-changing leaf requalifies it.
Dispatch still needs an approved catalog pin, and the dispatcher (E-01.3.1) has run only against an injected transport.
Other providers, Linux and macOS are **not yet verified**.

## Intent records

Plan leaf P-01.1 adds two product artifacts under [`catalog/`](../catalog/README.md),
for the projects the harness manages (this repository does not plan itself with
OpenSpec):

- the OpenSpec schema `intent-driven` (artifacts proposal, specs and design;
  `apply.requires` lists all three and there is no `apply.tracks`, because Backlog.md
  tracks implementation), whose proposal carries an intent record;
- the Agent Skill `intent-normalization`, which writes that record: the requester's
  words byte for byte, the objective, binding constraints (only with an acceptance
  recorded separately from the request), proposed methods (the Owner's stay
  hypotheses), hypotheses, acceptance criteria and open clarifications, each with a
  claim type and an attribution. The grammar is in the Skill's
  [`references/intent-record.md`](../catalog/skills/intent-normalization/references/intent-record.md).

[`tools/check_intent_record.py`](../tools/check_intent_record.py) checks a proposal
against the quoted source text, with the standard library only and no model. The
verifier lives in `tools/`, outside the Skill, so that the Skill being qualified does
not carry its own judge. Its tests (`tools/tests/test_check_intent_record.py`, part of
`task test`) pass the builder-produced fixture in `tools/tests/fixtures/intent_record/`
and fail its mutations. That fixture shows the format can express a confusing
request; it is not a qualification of the Skill on model runs.

Plan leaf P-01.2 qualified the Skill on live model runs.
[`tools/qualify_intent_skill.py`](../tools/qualify_intent_skill.py) (`task
intent:qualify`) gives the Skill to a model as its system prompt and one corpus
request (and, for a later turn, the earlier proposal and the follow-up message) as its
prompt. It runs a JSON command template in an empty working directory, checks the
returned proposal and appends a run ledger entry, and never runs past an invocation
cap. The corpus, the pre-written expected outcomes, the ledger, the outputs and the
OpenSpec changes recorded from them are in `tools/tests/fixtures/intent_qualification/`
([README](../tools/tests/fixtures/intent_qualification/README.md)). Their tests
re-score every committed output without a model. Results and limits:
[`evidence/P-01.2-intent-skill-qualification.md`](../evidence/P-01.2-intent-skill-qualification.md).

OpenSpec 1.16.0 checks the schema (`openspec schema validate intent-driven`) and the
readiness of a change's artifacts (`openspec status`), and `openspec validate` checks
delta specs. It does not check the content of a proposal; that is this checker's job.

## Repository access

Plan leaf F-10.2 adds [`integrations/repository/`](../integrations/repository/README.md), the
shared repository-access module of
[decision 0014](../decisions/0014-dulwich-adoption-scope-and-repository-access-contracts.md)
(Accepted): access to git repositories over Dulwich 1.2.21, from the Python tools set,
in the calling process. It launches no process. It holds the work-tree check, the preserved
revision grammar (every form git resolves, refusing only 0014's gap forms with
`REVISION_INVALID` before any access), object reads, file lists, `export_tree` (blob bytes),
HEAD, status, the index, listings, bundles, and an explicit configuration policy per call
(`host`, `repository` or `none`, with `config_sources`). Since F-10.3 the planning adapter's
`Git` is a facade over it (rows R1-R4 of the inventory: the work-tree check, revisions and
object reads, file lists, and exports as blob bytes, replacing `git archive`), under the
`repository` policy, so the planning, lineage and dispatch components launch no git. Since
F-10.4 the guest exchange push (R5, `write_bundle` and `full_name`), the profile revision and
the inventory snapshots (R7, R8, under `host`), the Gitea checkout listing (R9) and the test
profiler's revision stamp (R10, `null` with its reason when unavailable) use it too; the
exchange verifier (R6) keeps git (decision 0014 section 7). F-10.4 also repaired the module
forward: ignore rules and attributes are decided as git decides them, not by Dulwich, and
status applies git's size rule (the module's README). Since F-10.6 it also has smart-HTTP
transports (`ls_remote`, a bare `clone` and `Repository.push`, with an in-memory credential and
no credential helper), qualified against the host Gitea, and the resolver reads the source
tags through them (R11). Since P-04.1 it has its one write to history, `Repository.write_commit`,
for the [acceptance recorder](#owner-decisions): objects plus a compare-and-set update of the
branch, no hook (a repository with client hooks is refused, decision 0014 section 6), no process,
with the work tree and the index brought to the commit.

**Launch census guard.** `tools/tests/test_launch_census.py` (F-10.5) parses every tracked
`*.py` file (the index, read through the module, so no git is launched) and passes only when the
git launch sites it finds equal the retained list of decision 0014 section 1, each named with
its row: R6 (the exchange verifier's `run_git`), H1 (the publication-safety gate's `git`), B1
(`verify_seed.py --baseline`), B2 (`check_prereqs.py --tier basic`) and T (the test fixtures and
the git oracle). A new launch site fails it, and so does a retained site that disappears; a test
proves both on an in-memory copy of the tracked sources with an injected
`subprocess.run(['git', ...])`. It follows the standard library's launchers through imports,
aliases and injectable parameters, and the tree's own launcher wrappers (`run_tree`,
`ProcessTree`, `check_prereqs.output`) to their callers. Its docstring lists what static
analysis cannot see: a launcher or a program computed at run time, git launched by a child
process or inside a guest, and code outside tracked `*.py` files.

`task repository:test` runs its differential contract suite under the tools interpreter: the
recorded half compares the module with git's answers recorded over a committed, git-built
golden corpus and needs no git; the git-oracle half asks git again where git is on `PATH` and
skips, naming why, elsewhere. Without Dulwich the suite fails with `REPOSITORY_NEEDS_DULWICH`;
it never skips. The module's README lists the grammar, the local mechanics, the error codes, the
policies, the export contract and what is not yet verified.

## Planning adapter

Plan leaf P-02.1 adds [`integrations/planning/`](../integrations/planning/README.md),
the small resolver between OpenSpec and Backlog.md that blueprint section
[`#authority`](../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#authority)
calls for. OpenSpec owns the design; Backlog.md owns tasks, dependencies and status.
The adapter reads a task plan for one OpenSpec change and creates the tasks with
Backlog.md's own command line (`backlog task create --ref ... --dep ...`, then
`task view --json` to check each one). It never writes Backlog.md's files and never
sets, derives or reports a status. It refuses a change that carries its own
implementation checklist (`tasks.md`) or whose schema tracks one (`apply.tracks`).
This repository does not adopt Backlog.md or OpenSpec for its own Work: both run in
a managed project's repository, and in the tests in a throwaway one.

Every task carries one source pointer per design artifact it implements:

```
openspec:changes/<change-id>/<artifact-path>@<full commit id>#sha256=<blob sha256>
```

`planning:resolve` re-resolves the pointers from git objects alone. It fails visibly
on a missing revision, a missing artifact, a digest mismatch, or a task with no
pointer. The format, the plan input and every failure code are in the adapter's
[README](../integrations/planning/README.md).

The pinned Backlog.md 1.55.3 and OpenSpec 1.16.0 come from the component lock
(`composition/lock/npm/`), installed with `npm ci --ignore-scripts` into a directory
outside the checkout. Backlog.md runs without install scripts: npm installs its
platform package from `optionalDependencies`. The offline tests use a fake Backlog.md
and run under the tools interpreter (Dulwich; git builds their fixture repositories and is
their oracle). The adapter reads the repository in process (F-10.3) and starts Backlog.md and
OpenSpec as process trees; OpenSpec reads an export of the revision's blob bytes. It launches
no git, and needs the [product runtime](#tool-tiers): the `planning:` targets run under the
tools interpreter, and without Dulwich the adapter stops with `REPOSITORY_NEEDS_DULWICH`. The live
tests (`AIEH_BACKLOG`, `AIEH_OPENSPEC`) regenerate the
committed two-task capture in `integrations/planning/tests/fixtures/two-task/` and
compare it with the recorded one. They ran on Windows 11 x86_64 only; other hosts,
Backlog.md's MCP surface and concurrent writers are **not yet verified**.

Plan leaf P-02.2 adds the readiness read,
[`planning_readiness.py`](../integrations/planning/planning_readiness.py) (`task
planning:readiness`). It reports Backlog.md 1.55.3's own readiness per task (`isReady`,
and `readiness.blockingDependencies` and `readiness.missingDependencies` from `task view
--json`) and never computes readiness itself. A task is eligible only when Backlog.md
reports it ready, its readiness fields are present and agree, and every source pointer
it carries resolves. A missing dependency, a failing pointer or unknown readiness is a
visible failure (exit 1); a blocked task is an ordinary, ineligible state. Backlog.md
refuses `task create --dep` on an id that does not exist. A missing reference arises
when branches meet: one adds a dependency, another deletes the task, and git merges
both. The recorded fixtures in `integrations/planning/tests/fixtures/readiness/`
(blocked, unblocked after Backlog.md's own status change, missing) are replayed offline
and regenerated by the live tests. The ambiguous (duplicate-id) case was observed live
but has no fixture, and readiness under concurrent edits is **not yet verified**.

## Lineage references

Plan leaf P-03.1 adds [`integrations/lineage/`](../integrations/lineage/README.md): the
typed source references that blueprint section
[`#authority`](../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#authority)
asks the integration to carry between products, and a read-only resolver interface.
`lineage_schema.json` (`lineage-reference-schema/v1`) gives every reference kind its
authority, its stable identity (always the product's native ID), its revision anchor
(and whether pinning is required) and its validation rule. `lineage.py` parses and formats
each kind's canonical text, and the two round-trip. The `design` kind is the P-02.1
pointer, parsed and formatted by `planning_adapter.Pointer` unchanged.

A resolution is `resolved` or names why not: `missing`, `revision-mismatch`,
`digest-mismatch`, `authority-unavailable`, `unsupported-kind` or `ambiguous`. It has no
truth value, so it is never a silent success. Resolvers exist only where a local authority
and adapter exist:

| Kind | Authority | Resolver | Status |
|---|---|---|---|
| `design` | OpenSpec (git) | P-02.1 pointer resolution | implemented; offline tests |
| `work` | Backlog.md | `task view --json`, `task list --json` (P-02) | implemented; offline, and live with `AIEH_BACKLOG` |
| `commit` | Git | the shared repository-access module (in process over Dulwich, as `git rev-parse` and `cat-file` answer) in a registered clone | implemented; offline tests |
| `effect-receipt` | effects store | F-05.2 read methods | implemented on fixtures only |
| `objective` | OpenSpec | the outcome id declared under `x-outcomes` in the declaring change's `.openspec.yaml`, cross-checked against its intent record ([decision 0008](../decisions/0008-outcome-identity-assignment-form-and-record.md), Proposed) | implemented; offline, and live with `AIEH_OPENSPEC` (`validate --strict`, `archive`) |
| `conversation`, `message` | Owner conversation store | none | authority unavailable (U-02.1); **not yet verified** |
| `attempt` | OpenHands Agent Server | none | authority unavailable (E-01.3.1, E-01.4.1); **not yet verified** |
| `review`, `ci`, `authorization` | Gitea | none | authority unavailable (E-03.3.x, Q-03.x, G-03.1/G-04.3.1); **not yet verified** |
| `release`, `catalog` | Git/Gitea, Gitea catalog | none | identity not settled (`unsupported-kind`) |

A `message` reference may carry a span anchor (byte offset, length and the sha256 of those
bytes) so that a quote can be re-extracted from the durable source and verified byte for
byte. No message store exists yet, so only the anchor and its check are implemented. Live
resolution of effect receipts, which needs the store's custody identity (G-04.2.x), every
host but Windows 11 x86_64, and every kind marked unavailable or unsettled are **not yet
verified**.

The resolvers and the traversal read every repository through the shared
[repository-access module](#repository-access), in process (F-10.3), and launch no git. They
need the [product runtime](#tool-tiers): the `lineage:` targets run under the tools
interpreter. Without Dulwich a resolution that needs a repository is `authority-unavailable`
(`PROJECT_UNAVAILABLE`, decision 0014 section 3), and the lineage tests fail, naming
`REPOSITORY_NEEDS_DULWICH`; none skips.

Plan leaf P-03.2 adds `lineage_trace.py`: a read-only traversal from one outcome id
through the Owner's statements, the declaring change's design, the Backlog.md tasks that
reference it (found with Backlog.md's own `task list --json`, since it keeps no reverse
index) and the attempts that integration-store reservations record for those tasks. It
returns a `lineage-projection/v1` projection. Every node carries its authority, its
`authority_mode` (`authoritative`, `sample` or `unavailable`), and its resolution as
written and at the current revision. Every edge carries the record that asserts it, and an
explicit uncertainty list covers anything missing, changed, moved, gone, unavailable or
sample-backed. The verdict is `complete` only when that list is empty. The statement and
attempt authorities do not exist yet, so a full chain is shown only with the clearly
labelled sample authorities in `lineage_samples.py`, which the command line never uses.
The example projections are in `integrations/lineage/examples/`. Live statement and attempt
authorities, and the shape of a real dispatcher's reservation intent, are **not yet
verified** (see the [lineage README](../integrations/lineage/README.md#lineage-traversal-p-032)).

## Owner decisions

Plan group P-04 records the Owner's decisions through deterministic, non-model recorders in one
shared record shape, `owner-decision/v1` (`integrations/owner/owner_decision.py`): `decisionId`,
`kind`, `subject`, `shown` (the summary presented, its nonce and expiry), `statement` (the text
verbatim, `attributedTo: owner`, the channel and the reference), `recordedBy` and `recordedAt`.
Plan leaf P-04.1 adds the first recorder, the acceptance recorder
([`integrations/owner/`](../integrations/owner/README.md); `task owner:accept`). `prepare` shows
the Owner what is being accepted; `record` refuses, each with a stable code and its remedy, a
missing acceptance, one authored by a model, a statement attributed to anyone but the Owner,
re-minting and a stale, expired or replayed challenge; otherwise it writes the decision record
into the change's `owner-decisions/`, sets the Objective item's authority and acceptance, mints
the outcome id once and declares it under `x-outcomes`
([decision 0008](../decisions/0008-outcome-identity-assignment-form-and-record.md)), checks that
the new outcome resolves through the lineage objective resolver, and commits in process through
the [repository-access module](#repository-access)'s commit write, which runs no hook and so
refuses a repository with client hooks (decision 0014 section 6). The attribution is declared by
whoever transcribed the statement, not authenticated. It has run on throwaway fixture repositories
with synthetic statements only. OpenSpec 1.16.0 accepts a change holding the records
(`validate --strict`) and `archive` moves them with it byte for byte (live, `AIEH_OPENSPEC`). A real
acceptance and every host but Windows 11 are **not yet verified**.

Plan leaf P-04.2 adds the Owner authorization recorder (`task owner:authorize`; decision 0012 as
proposed): the sole custodian of `cred-gitea-owner-account`, it merges one exact operation manifest
`operations/<id>.json` as `aieh-owner` on a recorded Owner decision (kind `authorize-operation`),
with `Do: merge` and `head_commit_id`, the six `AIEH-*` trailers and a write-ahead receipt of its own
kind in the integration store, and refuses, each with a stable code, a stale head (Gitea's 409), an
altered digest, a replayed or expired decision, a missing or non-Owner statement, a missing
challenge, protection drift and a token on `aieh-owner`. In Gitea 28.3.0 only repository and site
administrators can read branch protection rules, so its own policy check compares what `aieh-owner`
can observe (the [README](../integrations/owner/README.md) lists what it cannot), and it fails closed
on the rest (decision 0012 point 6, Owner decision OA-15a): it merges only when a protection
verifier answers `verified` as the last read before the merge, and refuses `PROTECTION_UNVERIFIED`
or `PROTECTION_DRIFT` otherwise. The command line's verifier is the protection check of Owner
decision OA-16 ([`integrations/gitea/protection_check.py`](../integrations/gitea/README.md#the-protection-check-oa-16)):
it reads every rule, the rule set and its precedence, the merge settings, the collaborators, the teams
and the deploy keys as a read-only protection auditor and compares them with the harness's total
declaration; the auditor is not provisioned, so the command line merges nothing yet. Both have run
against a fake Gitea only; the two-phase live exercise on the
S-01.2.2 fixture (the Owner's own authorization between `prepare` and `record`) and a real Owner
authorization are **not yet verified**.

## Owner host

Plan leaf U-01.1 adds [`apps/owner-host/`](../apps/owner-host/README.md): the Owner's
single React application (blueprint
[`#conversation`](../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#conversation)).
It has routes for chat, Work and engineering, persistent navigation, one local session
identity, and a narrow and a wide layout. The chat is assistant-ui's headless primitives
over a model-free `LocalRuntime`. Agent Canvas 1.36.0 is embedded as a library with no
backend. Nothing is connected (no model, store, Work system or Agent Server), and every
surface says so. The session identity is a random, non-secret value kept in the browser's
local storage. It is not authentication: the Owner UI's access to the Agent Server is the
open finding `fd-owner-ui-access` in the [security inventory](#security-inventory). The
app's README records the routes, the identity design and the evidence for the
compatibility-matrix row "agent-canvas 1.36.0 / assistant-ui 0.15.32".

These targets need the **component tier** (Node.js ≥ 24, npm ≥ 11), and `owner-host:install`
needs access to the npm registry. They are not part of `setup` or `test`, which need only
Python, git and the Python tools set. The app has its own `package.json` and `package-lock.json` with
the component lock's versions for every package they share. Install it with
`npm ci --ignore-scripts`, which runs no package's install scripts. `node_modules/` and
`dist/` are not committed (decision 0005).

| Task target | Command without Task (in `apps/owner-host`) | Network | Result |
|---|---|---|---|
| `owner-host:install` | `npm ci --ignore-scripts --no-audit --no-fund` | yes | Installs the locked dependencies; npm checks each tarball's integrity. |
| `owner-host:typecheck` | `npm run typecheck` (`tsc --noEmit -p tsconfig.json`) | no | TypeScript 7.0.2 check of the app, its tests and the build plugin. |
| `owner-host:test` | `npm test` (`vitest run`) | no | Component, routing, identity, responsive-logic, no-network and Canvas compatibility tests in jsdom. |
| `owner-host:test:if-node` | when `node` is 24 or later, `npm test -- --no-cache --no-fsModuleCache`; otherwise a skip message | no | The same tests, without Vitest's result and module caches (nothing written under `node_modules/`); part of `test:all`. Fails when `node_modules/` is missing (`owner-host:install` first). |
| `owner-host:build` | `npm run build` (`vite build`) | no | Production build into `apps/owner-host/dist/`. Canvas is a lazy chunk. |

`npm run dev` and `npm run preview` serve the app on 127.0.0.1 only. Neither has a
Task target.

Verified on Windows 11 x86_64 with Node.js 24.19.0 and npm 11.17.0, with an isolated npm
cache and empty npm configuration: install, type check, tests (7 files, 43 tests) and build
PASS. `vite preview` on 127.0.0.1 served every route and the built assets. Rendering in a
real browser (including the responsive layout), every other host and the Task targets
themselves are **not yet verified**.

## Security inventory

Plan leaf S-01.1 records the harness's trust domains, principals, protected assets,
credential requirements and privileged operations in
[`security/inventory.json`](../security/inventory.json), with the human-readable
record in [`security/README.md`](../security/README.md). Every entry is `planned`
(defined by accepted authority, with source links), `observed` (shown by committed
evidence, with evidence links), `unknown` or `conflict` (with a finding). It is an
inventory, not a control: it changes no identity, key or permission, and S-01.2 and
S-01.3.x implement against it.

[`tools/check_security_inventory.py`](../tools/check_security_inventory.py) (`task
security:check`) enforces the leaf's acceptance with the standard library only:
every privileged operation names exactly one existing principal; no agent principal
holds, manages or may read a credential of Owner, admin, executor or management
authority, and no Owner-only operation uses one an agent can hold or read; an agent
that shares the Owner's OS identity (the host-side bootstrap agents) is never described
as an isolated principal, and every privileged credential it can reach is disclosed by a
finding. It also resolves every reference, link, blueprint anchor and plan id, rejects
machine paths, and requires the README to name every operation and finding. Its tests
(`tools/tests/test_check_security_inventory.py`, part of `task test`) pass the
committed inventory and fail its mutations. When an entry changes, update the JSON,
keep the README's tables and summary consistent with it, and run the checker.

## Containment cases

Plan leaf S-02.1 records the job environment's expected-denial matrix as versioned data in
[`security/containment-cases.json`](../security/containment-cases.json), rendered in
[`security/README.md`](../security/README.md#containment-cases-s-021). Each case names its
category (file, sibling-workspace, secret, socket, egress, privilege-expansion,
management-api), its principal, the exact non-destructive attempt, the expected outcome
classes, the enforcement location with its references, and the permitted case that is its
positive control. [`tools/check_containment_cases.py`](../tools/check_containment_cases.py)
(`task security:containment-check`) enforces the leaf's acceptance with the standard
library only; its tests (`tools/tests/test_check_containment_cases.py`, part of `task
test`) pass the committed catalogue and fail its mutations. `tools/guest.py
containment-probe` runs it (see [Execution guests](#execution-guests)). When the catalogue
changes, edit the JSON, replace the README's generated block with the output of
`--render`, and run the checker.

## Role-token matrix

Plan leaf S-01.2.1 binds each role to exactly one principal of the security inventory
and grants it inventory operations, named capabilities (`cap-*`) and credentials, in
[`policy/role-tokens.json`](../policy/role-tokens.json), with the human-readable record
in [`policy/README.md`](../policy/README.md) and the decision in
[0007](../decisions/0007-role-token-matrix-and-revocation-contract.md) (Proposed). It
also records each credential's issuance and revocation (triggers, revoker, rotation
owner) and, for the host-side bootstrap agents, which are a non-role row with no grants,
the leaf at which each operation they perform today moves to its planned principal.
Every realization is `verified: false` until S-01.2.2 tests it: the matrix issues,
installs and configures nothing.

[`tools/check_role_tokens.py`](../tools/check_role_tokens.py) (`task policy:check`)
enforces the leaf's acceptance with the standard library only, reusing the inventory
checker's link, status and machine-path rules: no agent, reviewer or CI role is granted
an Owner-only, executor, Gitea administration or Agent Server management operation,
`cap-code-merge-integration` or another privileged capability, a credential of Owner,
admin, executor or management authority, or a provider credential; no grant goes to a
principal that is not independently isolated; every granted operation belongs to the
role's own principal; issuers and rotation owners agree with the inventory; and the
README's generated tables equal `--render`. Its tests
(`tools/tests/test_check_role_tokens.py`, part of `task test`) pass the committed
matrix and fail its mutations. When the matrix changes, edit the JSON, replace the
README's generated block with the output of `--render`, and run both checkers.

## Network matrix

Plan leaf S-01.4 classifies every communication between the inventory's trust domains in
[`policy/network-matrix.json`](../policy/network-matrix.json), rendered in
[`policy/README.md`](../policy/README.md#network-matrix-s-014), under decision
[0013](../decisions/0013-owner-ui-session-access-and-management-key-custody.md)
(Proposed). Each row of an ordered domain pair has a verdict (allow, deny, disclosed), a
protocol, an endpoint (an inventory asset or a profiles P7 endpoint class), its
credentials, its enforcement points (prevention, detection or disclosure, at the host, the
guest, the container or Gitea), a status (observed, planned, decided) with its evidence or
plan leaf, whether it needs an Owner act, and its inspection command. It opens nothing: no
forward, firewall rule or Gitea change.

[`tools/check_network_matrix.py`](../tools/check_network_matrix.py) (`task
policy:network-check`) enforces the leaf's acceptance with the standard library only,
reusing the inventory checker's link and machine-path rules (see the policy README for the
full list). Its tests (`tools/tests/test_check_network_matrix.py`, part of `task test`)
pass the committed matrix and fail its mutations. When the matrix changes, edit the JSON,
replace the README's generated block with the output of `--render`, and run the checker;
when the inventory gains an asset, classify it in `asset_classes`.

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
| `profiles/` | Execution-profile contract, platform-provider matrix and property list, the profile declarations, and per-OS packaging when added | F-03.1 |
| `task_prompts/` | One Overseer prompt per plan leaf | seed |
| `tools/` | `verify_seed.py`, `check_prereqs.py`, `check_profile.py`, `msys2_lock.py`, `nocloud_seed.py`, `guest.py`, `publication_gate.py`, `check_intent_record.py`, `check_security_inventory.py`, `check_role_tokens.py`, `check_network_matrix.py`, `check_containment_cases.py`, `test_profile.py`, `check_test_budget.py` and their `tests/` | seed, F-02, F-03.2.1, F-03.2.2, F-03.3.1, F-04.1a, publication gate, P-01.1, S-01.1, S-01.2.1, S-01.4, S-02.1, F-09.1 |
| `catalog/` | Agent Skills and OpenSpec schemas shipped to managed projects: `openspec/schemas/intent-driven/`, `skills/intent-normalization/` (see its [README](../catalog/README.md)) | P-01.1 |
| `security/` | The [security inventory](#security-inventory): trust domains, principals, protected assets, credential requirements and privileged operations (`inventory.json`, `README.md`); the [containment cases](#containment-cases) (`containment-cases.json`) | S-01.1, S-02.1 |
| `policy/` | Permissions and controls: the [role-token matrix](#role-token-matrix) and revocation contract (`role-tokens.json`, `README.md`); the [test budgets](#testing) (`test-budgets.json`) | S-01.2.1, G-01.1, F-09.1 |
| `integrations/` | `paths/`: the [managed data root](#managed-data-root) resolver, its configuration loader, the tools venv installer and their `tests/`; `gitea/`: the [host Gitea](#host-gitea) lifecycle tool and its `tests/`; `store/`: the integration SQLite store, its migrations and its `tests/`; `effects/`: the privileged effect store, its migrations, custody check and `tests/`; `storecore/`: the SQLite mechanics both share; `planning/`: the OpenSpec-to-Backlog.md planning adapter, the readiness read and their `tests/`; `lineage/`: the typed lineage reference schema, the read-only resolvers, the lineage traversal, its `examples/` and their `tests/`; `dispatch/`: the trusted dispatch input resolver, the approved-input manifest's schema check, the create admission before the OpenHands create, the native conversation create (the dispatcher's order, the route-checked Agent Server client, the `/server_info` preconditions), its synthetic `examples/` and `tests/` (with the recorded Agent Server request/response fixture); `repository/`: the shared [repository-access](#repository-access) module over Dulwich and its differential contract suite with its golden corpus in `tests/fixtures/`; `owner/`: the shared Owner decision record, the [acceptance recorder](#owner-decisions) and their `tests/`; `inference/`: the [inference broker](#inference-broker), its declared API families (`families.json`) and its `tests/` | F-05.1, F-05.2, P-02.1, P-02.2, P-03.1, P-03.2, F-07.1, F-06.1, E-01.2.1, E-01.2.2, E-01.3.1, F-10.2, P-04.1, S-03.2 |
| `apps/` | `owner-host/`: the [Owner host](#owner-host) React application, its tests, its build plugin and its own npm lock | U-01.1 |
| `.githooks/` | The publication-safety gate's git hooks (`core.hooksPath`) | publication gate |
| `docs/` | This guide | contributor onboarding |
| repository root | Blueprint, plan and its projections, `task_manifest.json`, `SEED_MANIFEST.json`, `OVERSEER_START.md`, `Taskfile.yml`, `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `CLAUDE.md`, `example_config.yml` (the configuration template; `config.yml` is gitignored) | seed, F-02, contributor onboarding, F-07.1 |

Planned homes are documented here and created by the leaf that first fills them.
That leaf may refine the name with a recorded reason. S-01.1 recorded its inventory of
principals, assets and credential requirements in `security/` rather than `policy/`,
because it describes the current and planned security state rather than enforceable
policy; role permissions and controls (S-01.2.1, G-01.1) keep `policy/`. Upstream
sources stay external (pinned in `composition/`) unless adaptation is necessary.

| Concern | Planned home | Filled first by |
|---|---|---|
| Configuration (Agent Server and service configuration) | `config/` | F-04.1 |
| Integrations (Integration Service adapters and schemas) | `integrations/` (created by F-05.1: `integrations/store/`) | F-05.1, then P-02.1 and E-01.x |
| Policy (permissions, controls) | `policy/` (created by S-01.2.1: the role-token matrix) | S-01.2.1, G-01.1 |
| Agent and Skill catalog | `catalog/` (created by P-01.1: the `intent-driven` OpenSpec schema and the `intent-normalization` Skill) | P-01.1, then A-01.1 and E-03.1 |
| Tests, contract tests included | Beside the code they test: `tools/tests/` and `integrations/<component>/tests/`. A contract test is a declared [category](#testing), not a directory; there is no top-level `tests/` | each leaf with code; categories F-09.1 |
| Owner-facing applications | `apps/` (created by U-01.1: `apps/owner-host/`). A separate home because it is a Node application with its own npm toolchain and lock, unlike the Python tools and integrations | U-01.1, then U-01.2 and U-02.x |

## Changing integrity-tracked files

`tools/verify_seed.py` assigns every path in `SEED_MANIFEST.json` to a class:

| Class | Files | How to change them |
|---|---|---|
| contract | the plan JSON, its HTML and CSV projections, `task_manifest.json`, `task_prompts/`, `tools/verify_seed.py` | Only through a regenerated, reviewed plan (or, for the verifier, a reviewed change), with the manifest hashes updated in the same commit. Any mismatch fails. |
| authority | the blueprint HTML, `OVERSEER_START.md` | Change the file and its `sha256` (and `size_bytes`) in `SEED_MANIFEST.json` in the same commit. Any mismatch fails. |
| ordinary | `README.md`, `CLAUDE.md`, `.gitignore` | Edit freely. The verifier reports them as `INFO: ordinary file changed since seed`. |

A new manifest entry without a class fails, so classify it in the verifier.

An Owner-directed plan amendment changes the plan JSON, regenerates its HTML and
CSV projections and the affected task prompts in the generator's exact format,
and updates `task_manifest.json` and `SEED_MANIFEST.json` (hashes, sizes, new
prompt entries and `task_count`) in the same commit. The plan records each
amendment, dated and with its provenance, in its `amendments` list; its original
statuses and `as_of` stay the seed baseline.
`python -I tools/verify_seed.py --baseline seed` checks the original import
strictly at any time, whatever has changed since.

## Security expectations

This is a **public** repository. Repository-authored code and documentation are
MIT-licensed ([`LICENSE`](../LICENSE)). Third-party components keep their own
licences, and are downloaded from their upstream distributors rather than
redistributed
([decision 0005](../decisions/0005-distribution-model-upstream-download-no-redistribution.md)). The
SBOM and Grant outputs under `composition/inventory/generated/` are metadata about
third-party packages, not copies of them
([publication audit](../composition/inventory/PUBLICATION-AUDIT.md)).

- Dependencies are hash-locked. Python installs are wheels only, with one
  reviewed sdist exception ([decision 0002](../decisions/0002-reviewed-sdist-exception-for-resolution.md)).
  npm runs with `--ignore-scripts`.
- Use throwaway work directories outside the checkout, and run Python tools with
  `python -I` (add `-B` where a module is imported from the checkout).
- Put no credentials in commands, files, or logs. Registry access is anonymous.
- Install the [publication-safety gate](#publication-safety-gate) in every
  clone you commit from. It does not replace review: before each commit and
  push, still review the diff for secrets, personal machine paths and private
  data.
- Third-party code and artifacts keep their own licences; preserve their
  notices.

## Publication-safety gate

This repository is public, and anything pushed to it should be assumed copied
at once. The gate is a pair of repository-local git hooks that stop secrets and
private machine information before they are committed or pushed. Its logic is
in [`tools/publication_gate.py`](../tools/publication_gate.py) (stdlib Python); the
hooks in [`.githooks/`](../.githooks/) only locate CPython 3.12+ and call it. The
detector is [Gitleaks](https://github.com/gitleaks/gitleaks) (MIT), run locally:
nothing is sent to an external scanning service.

### Install and verify

```
task hooks:install     # python -I -B tools/publication_gate.py install
task hooks:verify      # python -I -B tools/publication_gate.py verify, then the gate's tests
```

`hooks:install` downloads the pinned Gitleaks **8.30.1** release asset for the
host, checks it against the sha256 pinned in the gate (which was checked against
the release's `gitleaks_8.30.1_checksums.txt` and GitHub's asset digest when
pinned) and against that checksums file (itself pinned by sha256), extracts the
executable, checks its pinned sha256, and caches it per user, outside the
checkout:

- Windows: `%LOCALAPPDATA%\ai-engineering-harness\tools\gitleaks\8.30.1\`
- elsewhere: `${XDG_CACHE_HOME:-~/.cache}/ai-engineering-harness/tools/gitleaks/8.30.1/`

It then sets `git config --local core.hooksPath .githooks` (this clone only).
Gitleaks publishes no release signature, so none is checked. Builds are pinned
for Windows, Linux and macOS on x86_64 and arm64; only the Windows x86_64 build
has been run here. Every hook run re-checks the cached binary's sha256 before
using it.

`hooks:verify` checks the cached binary's hash and version, the hook wiring and
the configuration, then runs the synthetic test suite
(`tools/tests/test_publication_gate.py`) with `AIEH_GATE_REQUIRE_SCANNER=1`, so
the tests that need the real scanner fail instead of skipping. In `task test`
those tests skip when the scanner is not installed.

`task scan:history` (`python -I -B tools/publication_gate.py history [REVS]`)
scans every commit reachable from `REVS` (default `--all`), read-only, and
prints findings without values. It exits 1 when it finds anything.

### What it checks

- **pre-commit** scans the exact staged content: every added or modified blob in
  the index, read from git, not from the working tree.
- **pre-push** scans every commit being introduced, read from the ref lines git
  passes on stdin: for an existing remote ref, the commits not reachable from
  its current tip; for a new remote ref, the commits not reachable from any
  remote-tracking ref. Each commit's changed blobs and its message are scanned,
  so a secret added in one commit and removed in a later one is still caught.
- Only what git actually stages or commits is inspected. `.gitignore` is not
  relied on: `git add -f .env` is caught.
- Rules: the Gitleaks default rules (tokens, API keys, private keys and many
  more), extended in the committed [`.gitleaks.toml`](../.gitleaks.toml) with
  narrow rules for absolute paths into personal Windows profiles
  (`<drive>:\Users\<name>`, with forward slashes, or JSON-escaped), personal
  Linux, WSL, MSYS and macOS homes (`/home/<name>`, `/Users/<name>`,
  `/mnt/<drive>/Users/<name>`, `/c/Users/<name>`, `\\wsl$\...\home\<name>`), and
  local credential and token stores matched **by file path** (for example
  `.claude/.credentials.json`, `.codex/auth.json`, `.mcp.json`,
  `.git-credentials`, `.netrc`, `.npmrc` with an auth token, `.aws/credentials`,
  `.kube/config`, SSH keys, `*.pem`/`*.key`, `.env` and `.env.*` but not
  `.env.example`, keyrings and `.gnupg/`). Documentation and `.gitignore` lines
  that merely mention those names pass. Generic placeholders pass and are listed
  in the configuration with a reason each: names beginning with `<`, `%`, `$`
  or `{` (`C:\Users\<user>`, `%USERPROFILE%`, `$HOME`), `~`, `C:\Users\you`,
  `C:\Users\Public`, `/home/user`, `/home/agent` (the guest user in
  `profiles/`). Repository-relative paths never match.
- **Archives and binaries.** gzip data is decompressed and its content scanned.
  Any other binary or archive (zip, tar, 7z, disk images, executables, PDFs,
  images and the like) is refused unless its exact path is listed in
  `binary_allowlist` in `.gitleaks.toml` with a reason; a listed binary is still
  subject to the path rules. The list is empty: the only tracked binaries are the
  gzip files under `composition/inventory/generated/`, which are scanned.
- **Fails closed.** A missing scanner, a wrong hash, a scanner error or timeout,
  a missing or invalid configuration, or a scan that cannot complete blocks the
  commit or push (exit 2). Each scanned file carries a per-run marker the
  scanner must report, so a scanner that silently skips a file or "succeeds"
  without output is caught. A file that Gitleaks would skip by a default path
  allowlist (lock files, `node_modules/`) is rescanned under a neutral name.
  Inline `gitleaks:allow` comments and `.gitleaksignore` files are ignored.
- **Large content.** Gitleaks reads a file in pieces and scans each piece
  separately, so a match across a piece boundary would be missed. Content over
  96 KiB is therefore scanned as overlapping windows, each of which, with its
  marker, fits in one scanner read. Consecutive windows overlap by at least
  32 KiB, so any match up to that length lies whole in one window. Every
  window's marker is required, so a window the scanner does not inspect still
  fails closed. Findings are reported at the file's real line, once.
- Output names the category, rule, file, line and commit only. Values are never
  printed (`--redact`, and the gate prints no match text).

### What it cannot detect

- Secrets in formats no rule knows, including novel or custom token formats and
  low-entropy passwords.
- Secrets split across lines, files or commits, or encoded in ways the scanner
  does not decode.
- In content over 96 KiB, a single match longer than 32 KiB, which may cross a
  window boundary.
- Private information that is not a recognisable path or credential: names,
  hostnames, internal URLs, customer data, screenshots.
- Content of allowlisted binaries.
- Anything that does not pass through these hooks: content outside git, other
  clones without the gate, edits made on GitHub, issue and PR text, and tags'
  annotation messages.
- A bypass. `git commit --no-verify`, `git push --no-verify`, or unsetting
  `core.hooksPath` turns the gate off. Never do that; agents must not either.

### False positives

Change the committed `.gitleaks.toml` with the narrowest possible allowlist
entry: an exact value or name, scoped to an exact path where possible, with a
`description` stating why it is safe. Prefer value- or line-based entries:
global path allowlists are not honoured (the file is rescanned under a neutral
name). The change is reviewed like code. Never use `--no-verify` to get past a
finding.

Known false positives: `generic-api-key` matches English prose in the seed plan
(`AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json`
and its `.html` projection). They are already published, so they block nothing
unless those files change; the history scan reports them.

### If the gate finds a credential

1. Do not push. Unstage or amend the unpushed commit to remove it; for an
   earlier unpushed commit, rewrite only the unpushed commits.
2. If the credential ever left this machine (pushed anywhere, pasted, logged,
   shared), treat it as compromised: **revoke and rotate it** at its issuer.
   Removing it from git does not undo the exposure.
3. Never rewrite published history or force-push without the Owner's
   authorization.

### GitHub push protection

Keep GitHub's server-side secret scanning and push protection enabled for this
repository. It is an independent backstop: it applies to pushes from any clone,
including ones without these hooks or where they were bypassed, and to edits
made on GitHub, and it uses GitHub's own provider-verified patterns. The local
gate adds what GitHub does not check (personal paths, local credential files,
refused binaries) and stops content before it leaves the machine.

## How progress is recorded

[`evidence/bootstrap-log.md`](../evidence/bootstrap-log.md) holds the Overseer's
verdicts per plan leaf, and [`decisions/`](../decisions/) holds accepted decisions.
Both are written by the Overseer; contributors do not edit them as part of
ordinary changes. Task status is not tracked anywhere else.
