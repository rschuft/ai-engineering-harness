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

`task setup` is the supported setup command. It checks the basic prerequisites,
verifies the seed in both modes and runs the tool tests, the integration store
tests and the effects store tests. It is offline and takes seconds. Before your first commit, also run
`task hooks:install` once per clone
(see [Publication-safety gate](#publication-safety-gate)). Without Task, run the six commands it wraps:

```
python -I -B tools/check_prereqs.py --tier basic
python -I tools/verify_seed.py
python -I tools/verify_seed.py --baseline seed
python -I -B -m unittest discover -s tools/tests -v
python -I -B -m unittest discover -s integrations/store/tests -v
python -I -B -m unittest discover -s integrations/effects/tests -v
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
| Component verification | CPython **3.12** with pip ≥ 23.1, Node.js ≥ 24 with npm ≥ 11, git, and HTTPS access to the registries listed in [`composition/lock/README.md`](../composition/lock/README.md). | `composition/resolve.py` (`task resolve`, `task qualify`). |
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
| `setup` | the six commands in [Quick start](#quick-start) | no | Supported setup command. |
| `qualify` | `setup`, then `prereqs:components`, then `resolve` with a new temporary `WORK` | yes | Full qualification smoke run. |
| `prereqs` | `python -I -B tools/check_prereqs.py --tier basic` | no | Exit 0 when met. |
| `prereqs:components` | `python -I -B tools/check_prereqs.py --tier components` | no | Reuses the resolver's own prerequisite check. |
| `prereqs:inventory` | `python -I -B tools/check_prereqs.py --tier inventory` | no | Checks the SBOM scan's host platform. |
| `verify` | `python -I tools/verify_seed.py` | no | Working tree against `SEED_MANIFEST.json`. Needs no git. |
| `verify:baseline` | `python -I tools/verify_seed.py --baseline seed` | no | The original import, strictly, from git history. |
| `test` | `python -I -B -m unittest discover -s tools/tests -v`, then `store:test`, then `effects:test` | no | Tool tests, integration store tests and effects store tests (stdlib `unittest`). |
| `store:test` | `python -I -B -m unittest discover -s integrations/store/tests -v` | no | [Integration store](#integration-store) tests: real processes against one SQLite file; about two seconds. |
| `store:init DB=<path>` | `python -I -B integrations/store/integration_store.py init --db <path>` | no | Creates or migrates the integration store at an explicit path and prints a JSON summary. Idempotent. |
| `store:path` | `python -I -B integrations/store/integration_store.py default-path` | no | Prints the default trusted-host store location. Creates nothing. |
| `store:backup DB=<path> ACTOR=<name>` | `python -I -B integrations/store/integration_store.py backup --db <path> --actor <name>` | no | Backs the integration store up with the SQLite backup API into `<db dir>/backups/`, checks the copy and prints its manifest. |
| `store:restore DB=<path> MANIFEST=<file> ACTOR=<name> [-- --accept-rollback]` | `python -I -B integrations/store/integration_store.py restore --db <path> --manifest <file> --actor <name> [--accept-rollback]` | no | Restores a verified backup and opens a restore epoch. Refuses a rollback unless accepted; keeps the superseded store in `backups/superseded/`. |
| `effects:test` | `python -I -B -m unittest discover -s integrations/effects/tests -v` | no | [Effects store](#effects-store) tests: crash, backup and restore, custody and location refusals on fixtures; a few seconds. |
| `effects:init ROOT=<dir> [-- --principal SID]` | `python -I -B integrations/effects/effects_store.py init --root <dir> [--principal SID]` | no | Creates or migrates `effects.sqlite` inside an existing, Owner-created root after the location and custody checks. Never creates the root. |
| `effects:backup ROOT=<dir> ACTOR=<name>` | `python -I -B integrations/effects/effects_store.py backup --root <dir> --actor <name>` | no | Backs the effects store up into `<root>/backups/` and prints the manifest. |
| `effects:restore ROOT=<dir> MANIFEST=<file> ACTOR=<name> [-- --accept-rollback]` | `python -I -B integrations/effects/effects_store.py restore --root <dir> --manifest <file> --actor <name> [--accept-rollback]` | no | The Owner's elevated act, with the executor stopped: restores a verified backup and opens a restore epoch. |
| `effects:verify-chain ROOT=<dir>` | `python -I -B integrations/effects/effects_store.py verify-chain --root <dir>` | no | Verifies the journal's hash chain and every receipt; prints the chain head. |
| `intent:check PROPOSAL=<file> -- --source REF=FILE` | `python -I -B tools/check_intent_record.py <file> --source REF=FILE [--source ...]` | no | Checks a proposal's [intent record](#intent-records): byte-identical quotes, Owner methods kept as hypotheses, acceptances, required fields. Exit 0 PASS, 1 FAIL, 2 could not run. |
| `intent:qualify -- <run\|check\|prompt\|system-prompt> [options]` | `python -I -B tools/qualify_intent_skill.py <subcommand> [options]` | `run`: the model command's own (a live model) | Runs the intent-normalization Skill's [behavioural qualification](#intent-records): one corpus item and turn through a JSON model-command template in an empty working directory, then the checker, then a ledger entry; refuses past `--max-invocations` (default 25). `check` scores a saved proposal against an item's messages. |
| `profile:check [-- --strict]` | `python -I -B tools/check_profile.py [--strict]` | no | Schema check of every `profiles/*/profile.json`: pinned boot inputs, labels, no host share, loopback-only forwards, ceilings, no TCG fallback. Runs no provider. `--strict` also fails on inputs declared with an unknown pin. |
| `guest:preflight PROFILE=<dir> STATE_DIR=<dir>` | `python -I -B tools/guest.py preflight --profile <dir> --state-dir <dir>` | no | Read-only capability report for a strong guest profile; each failure names its Owner act (A1, A2, A3). See [Execution guests](#execution-guests). |
| `guest:create PROFILE=… STATE_DIR=… NAME=<name>` | `python -I -B tools/guest.py create --profile <dir> --state-dir <dir> --name <name>` | no | Creates, boots and waits for a disposable guest. Refuses an existing instance. |
| `guest:start`, `guest:inspect`, `guest:stop`, `guest:destroy`, `guest:recreate` (same variables) | `python -I -B tools/guest.py <operation> --profile <dir> --state-dir <dir> --name <name>` | no | The rest of the lifecycle; `destroy` deletes only the instance directory. |
| `guest:exec PROFILE=… STATE_DIR=… NAME=… -- CMD` | `python -I -B tools/guest.py exec --profile <dir> --state-dir <dir> --name <name> -- CMD` | no | Operators only: a command in the guest over the loopback SSH forward. |
| `guest:push PROFILE=… STATE_DIR=… NAME=… REPO=<repo> REF=<branch>` | `python -I -B tools/guest.py exchange-push --profile <dir> --state-dir <dir> --name <name> --repo <repo> --ref <branch>` | no | Exchange push: one local branch as a bounded git bundle, by SFTP into `/home/agent/exchange`. Reads the repository only. |
| `guest:pull PROFILE=… STATE_DIR=… NAME=… FILE=<file>` | `python -I -B tools/guest.py exchange-pull --profile <dir> --state-dir <dir> --name <name> --file <file>` | no | Exchange pull: one file into the instance's staging directory; a bundle is verified in a fresh bare repository there. |
| `guest:canaries OUT=<dir>` | `python -I -B tools/guest.py canaries --out <dir>` | no | Writes a synthetic canary set and fake home into a new directory outside the checkout. |
| `guest:create-canaries PROFILE=… STATE_DIR=… NAME=… CANARIES=<dir>` | `python -I -B tools/guest.py create --profile <dir> --state-dir <dir> --name <name> --canaries <dir>` | no | `create` with the canary set planted in its own environment first (the P5 test). |
| `guest:check-surfaces PROFILE=… STATE_DIR=… NAME=… CANARIES=<dir>` | `python -I -B tools/guest.py check-surfaces --profile <dir> --state-dir <dir> --name <name> --canaries <dir>` | no | Startup inspection test for profiles P3 to P6 (F-03.3.1): exit 0 only when all four PASS. |
| `guest:smoke PROFILE=… STATE_DIR=… NAME=<name> CANARIES=<dir> DURABLE=<dir>` | `python -I -B tools/guest.py smoke --profile <dir> --state-dir <dir> --name <name> --canaries <dir> --durable <dir> [--durable <dir> …] [--out <file>]` | no | The F-03.4 provision/inspect/teardown smoke test (profiles P10) on a fresh instance name. Exit 0 only on PASS. See [Execution guests](#execution-guests). |
| `guest:provision-fetch PROFILE=… STATE_DIR=…` | `python -I -B tools/guest.py provision-fetch --profile <dir> --state-dir <dir>` | yes | Host side of guest provisioning (F-04.1a): downloads the profile's provision-lock artifacts from their upstreams (snapshot.debian.org, GitHub, ghcr.io through the pinned crane), verifies each against the lock and stages them under `<state>\provision\<lock sha256>\`. About 1.5 GB on the first run; a verified stage is reused. Runs nothing downloaded except crane. |
| `guest:netprobe PROFILE=… STATE_DIR=… NAME=<name>` | `python -I -B tools/guest.py netprobe --profile <dir> --state-dir <dir> --name <name>` | no | **Test only.** The F-03.3.2 network validation of profiles P7 in a disposable guest (guest root, one test `guestfwd` to a 127.0.0.1 listener, decoys). Exit 0 only on PASS. Destroy the instance afterwards. |
| `hooks:install` | `python -I -B tools/publication_gate.py install` | yes (once) | Installs the [publication-safety gate](#publication-safety-gate): pinned Gitleaks into the per-user cache, `core.hooksPath`. |
| `hooks:verify` | `python -I -B tools/publication_gate.py verify`, then the gate's tests with `AIEH_GATE_REQUIRE_SCANNER=1` | no | Scanner hash and version, hook wiring, configuration, synthetic tests. |
| `scan:history [-- REVS]` | `python -I -B tools/publication_gate.py history [REVS]` | no | Read-only, redacted scan of every commit (default `--all`); exit 1 on findings. |
| `resolve WORK=<dir>` | `python -I composition/resolve.py --work <dir>` | yes | Component lock resolution and host install; see [`composition/lock/README.md`](../composition/lock/README.md). `<dir>` must be empty or absent and outside the checkout. |
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
  checkout (HEAD, tracked status, `git ls-files -s` digest), the state directory's
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
  branch as a complete git bundle within the profile's `exchange.push` bounds, built
  with git under no system or global configuration and checked (header, pack checksum,
  `git bundle verify`) before it is copied under a new name. A pull copies one regular
  file of the guest's exchange directory into `<instance>\exchange\inbound\`; a bundle
  is verified in a fresh bare repository there, never in an Owner repository. Both
  directories are inside the instance directory, so `destroy` removes them.
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

Each operation prints one JSON object. The first real boot cycles are in
[`evidence/F-03.2.2b-guest-lifecycle.md`](../evidence/F-03.2.2b-guest-lifecycle.md);
the exchange and surface-test cycles (F-03.3.1) are in
[`evidence/F-03.3.1-guest-surfaces.md`](../evidence/F-03.3.1-guest-surfaces.md); the
network validation (F-03.3.2) is in
[`evidence/F-03.3.2-guest-network.md`](../evidence/F-03.3.2-guest-network.md); the
teardown test and the provider-profile qualification (F-03.4) are in
[`evidence/F-03.4-teardown-qualification.md`](../evidence/F-03.4-teardown-qualification.md)
and [`QUALIFICATION.md`](../profiles/strong-windows-qemu-whpx/QUALIFICATION.md).
The tier stays **not operational** until S-02.x also passes (C6).

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
| `tools/` | `verify_seed.py`, `check_prereqs.py`, `check_profile.py`, `msys2_lock.py`, `nocloud_seed.py`, `guest.py`, `publication_gate.py`, `check_intent_record.py` and their `tests/` | seed, F-02, F-03.2.1, F-03.2.2, F-03.3.1, F-04.1a, publication gate, P-01.1 |
| `catalog/` | Agent Skills and OpenSpec schemas shipped to managed projects: `openspec/schemas/intent-driven/`, `skills/intent-normalization/` (see its [README](../catalog/README.md)) | P-01.1 |
| `integrations/` | `store/`: the integration SQLite store, its migrations and its `tests/`; `effects/`: the privileged effect store, its migrations, custody check and `tests/`; `storecore/`: the SQLite mechanics both share | F-05.1, F-05.2 |
| `.githooks/` | The publication-safety gate's git hooks (`core.hooksPath`) | publication gate |
| `docs/` | This guide | contributor onboarding |
| repository root | Blueprint, plan and its projections, `task_manifest.json`, `SEED_MANIFEST.json`, `OVERSEER_START.md`, `Taskfile.yml`, `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `CLAUDE.md` | seed, F-02, contributor onboarding |

Planned homes are documented here and created by the leaf that first fills them.
That leaf may refine the name with a recorded reason. Upstream sources stay
external (pinned in `composition/`) unless adaptation is necessary.

| Concern | Planned home | Filled first by |
|---|---|---|
| Configuration (Agent Server and service configuration) | `config/` | F-04.1 |
| Integrations (Integration Service adapters and schemas) | `integrations/` (created by F-05.1: `integrations/store/`) | F-05.1, then P-02.1 and E-01.x |
| Policy (principals, permissions, controls) | `policy/` | S-01.1, S-01.2.1, G-01.1 |
| Agent and Skill catalog | `catalog/` (created by P-01.1: the `intent-driven` OpenSpec schema and the `intent-normalization` Skill) | P-01.1, then A-01.1 and E-03.1 |
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
- Output names the category, rule, file, line and commit only. Values are never
  printed (`--redact`, and the gate prints no match text).

### What it cannot detect

- Secrets in formats no rule knows, including novel or custom token formats and
  low-entropy passwords.
- Secrets split across lines, files or commits, or encoded in ways the scanner
  does not decode.
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
