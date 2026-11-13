# Managed data root and configuration (`aieh_paths.py`)

Plan leaf F-07.1, blueprint section
[`#infrastructure-state`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#infrastructure-state),
[decision 0009](../../decisions/0009-managed-data-root-and-configuration-contract.md) (Proposed).

The harness keeps its installations, service state, caches and downloads outside the
source checkout, under one **managed data root**. This module is the one resolver every
component uses to find those directories. Components consume the resolved paths and
invent none. It is Python standard library only; PyYAML is needed only when the optional
`config.yml` exists.

F-07.1 defines the contract. No component uses it yet: the integration store, the
publication gate and the guest tooling keep their current locations until F-07.2.

## Files

| Path | What |
|---|---|
| `aieh_paths.py` | The resolver, the configuration loader and the command line (`show`, `init`, `doctor`), the category table, the legacy table and the asset record format |
| `tools_install.py` | `task tools:install`: the hash-locked Python tools venv, the first consumer of the contract. `--set python-dev-tools` (`task dev:install`) installs the dev tools set (pytest, pytest-xdist, PyYAML, Dulwich, urllib3 and keyring) the same way, from its own lock, as `python-dev-tools` beside it; `--python` prints a set's venv interpreter for the current lock, creating nothing, and exits 1 when it is not installed |
| `tests/test_aieh_paths.py` | The section 9 criteria 1 to 10 of the Owner directive, the adapters, the legacy table, `example_config.yml`, the asset records, `tools:install` and its `--set` and `--python` options |
| `../../example_config.yml` | The tracked, commented configuration template |
| `../../composition/lock/python/tools-requirements.txt` | The tools venv lock: `pyyaml==6.0.3` with the hashes of the F-01.2 lock, `dulwich==1.2.21` and `urllib3==2.8.0` (F-10.1), and `keyring==25.7.0` with its closure copied from the F-01.2 locks, with `sys_platform` markers (F-06.3) |
| `../../composition/lock/python/dev-requirements.txt` | The dev tools venv lock (F-09.2): pytest, pytest-xdist and their dependencies, and `pyyaml==6.0.3`, `dulwich==1.2.21`, `urllib3==2.8.0` and the keyring closure with the same hashes as the tools lock |

## Commands

Run from the repository root (`python3` outside Windows):

```
python -I -B integrations/paths/aieh_paths.py show [--format json|sh|ps1]   # task paths:show
python -I -B integrations/paths/aieh_paths.py init                          # task paths:init
python -I -B integrations/paths/aieh_paths.py doctor                        # task paths:doctor
python -I -B integrations/paths/tools_install.py                            # task tools:install (network: PyPI)
python -I -B integrations/paths/tools_install.py --set python-dev-tools     # task dev:install (network: PyPI)
python -I -B integrations/paths/tools_install.py --set python-dev-tools --python   # its interpreter, or exit 1
python -I -B -m unittest discover -s integrations/paths/tests -v           # task paths:test
```

`show` and `doctor` create nothing. `init` creates the root, its three lifecycle
directories and the marker. Every command exits 2 on a refusal and prints its code and remedy.

## The root

| Platform | Default root |
|---|---|
| Windows | `%LOCALAPPDATA%\AIEH`, from the environment variable |
| Linux and other POSIX | `$XDG_DATA_HOME/aieh`, or `~/.local/share/aieh` when `XDG_DATA_HOME` is unset or relative |
| macOS | `~/Library/Application Support/aieh` (**not yet verified**) |

Precedence, highest first:

1. a per-category override in `config.yml` (`paths.<category>`): absolute, or relative to the
   effective root. One that leaves the root is reported with `outside_root: true` and a warning;
2. `AIEH_DATA_ROOT`: absolute, or relative to the repository root of the tree the resolver is
   loaded from, never to the working directory;
3. the OS default.

`config.yml` has no root key. The resolver's only override variable is `AIEH_DATA_ROOT`; it
also reads `LOCALAPPDATA`, `XDG_DATA_HOME` and `HOME` for the default and the profile variables
for a refusal. It never reads `.env`: dotenv was evaluated and not adopted.

## Categories

Below the root sit three lifecycle directories: `persistent/` (never deleted implicitly;
survives restarts and upgrades), `ephemeral/` (open to controlled cleanup only) and
`assets/` (downloaded, verified, reacquirable artifacts, reclaimed only deliberately when no
required consumer depends on them and verified reacquisition is possible). Nothing in F-07.1
deletes anything.

| Category | Default below the root | Lifecycle | Class | Layout | Creator | Consumer |
|---|---|---|---|---|---|---|
| `state` | `persistent/state` | persistent | B | `<component>/` | the component (`ensure`) | integration, planning and lineage stores (F-07.2) |
| `gitea` | `persistent/gitea` | persistent | E | | the Gitea installer (F-06.1) | Gitea (F-06.1) |
| `installs` | `persistent/installs` | persistent | B | `<tool>/<version>/` | `tools:install`; installers | the tools venv; unpacked tools |
| `logs` | `persistent/logs` | persistent | B | `<component>/` | the component | operators |
| `workspaces` | `persistent/workspaces` | persistent | C | | reserved | reserved |
| `assets` | `assets` | assets | B | `<kind>/<name>/<version>/` with `aieh-asset.json` | downloaders (`tools:install`; F-07.2) | installers, guest provisioning (F-07.2) |
| `cache` | `ephemeral/cache` | ephemeral | D | `<component>/` | the component | pip (`tools:install`); components |
| `scratch` | `ephemeral/scratch` | ephemeral | D | | the component | `task qualify` (F-07.2) |
| `tmp` | `ephemeral/tmp` | ephemeral | D | | the component | components |

The class is the Owner directive's: B the installed harness and its managed data, C durable
user work, D disposable execution data, E protected configuration, credentials and evidence.
Class A, the source checkout, is never under the root.

**Assets and installs.** A downloaded, verified artifact (a VM base image, model weights, an
installation package, a tool archive, wheels) is an asset in `assets/<kind>/<name>/<version>/`.
An unpacked or installed copy that must persist is an install in
`persistent/installs/<tool>/<version>/`. A tool that needs no install step runs from its asset
directly. Mutable VM disks and overlays are not assets: they belong in `persistent/` or
`ephemeral/` by lifecycle. `tools:install` shows the split: its wheels are an asset, the venv
built from them an install.

**Asset record** (`aieh-asset/1`, `aieh-asset.json` in the asset's directory, written by
`asset_record()` and `write_asset_record()`, checked by `check_asset_record()`):

```json
{
  "format": "aieh-asset/1",
  "kind": "python-wheels",
  "name": "python-tools",
  "version": "cp312-442f4405a6dc",
  "provenance": {"source": "https://pypi.org/simple/"},
  "integrity": {
    "sha256": {
      "dulwich-1.2.21-cp312-cp312-win_amd64.whl": "b3d30d40384cee2e8aa3722f87cef2f3d71717a0b45ac88eba457d62acf65dda",
      "pyyaml-6.0.3-cp312-cp312-win_amd64.whl": "5fcd34e47f6e0b794d17de1b4ff496c00986e1c83f7ab2fb8fcfe9616ff7477b",
      "urllib3-2.8.0-py3-none-any.whl": "0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3"
    },
    "pin": "composition/lock/python/tools-requirements.txt sha256:442f4405a6dc3d583beb8fffd81762a796b20ed4e465bcabd5f57ec4bb6de8bd"
  },
  "reacquire": "task tools:install (pip download --require-hashes --only-binary=:all: -r composition/lock/python/tools-requirements.txt)",
  "acquired_at": "2026-11-07T16:29:10Z",
  "consumers": ["installs/python-tools"]
}
```

`kind`, `name` and `version` are single path segments; `integrity` holds sha256 digests per
file, the pin, or both. The record is written exclusively and never rewritten.

**Registered external locations** have no default and are never created or checked by the
resolver. They are absolute paths in `config.yml` (`paths.effects_root`, `paths.guest_state`),
reported under `external`:

- `effects_root`: the privileged effects store root (decision 0004, Owner act A4), checked
  only by the effects store. Its placement awaits the re-evaluation of decision 0004;
  directory placement is not a security control. `check_effects_root()` refuses an effects
  root inside or containing the managed data (`LOCATION_MANAGED_ROOT`) for the effects store
  to adopt in F-07.2.
- `guest_state`: the execution-guest state root (decision 0003, act A3), not relocated.

## Refusals

Each refusal has a stable code and names its remedy (`REMEDIES` in the module). The lexical
checks run before any filesystem access; then, read-only, the link-resolved root and categories
are checked against the checkout and, on Windows, the volume type through storecore's
`GetDriveTypeW` check.

"Inside or containing the checkout" (`ROOT_INSIDE_CHECKOUT`, `PATH_INSIDE_CHECKOUT`, lexically
and after resolving links) is one public comparison, `inside_or_around(candidate, root,
platform)`, which the dispatch manifest's guard (`dispatch_inputs.load_manifest`) and the S-03.3
proposal's `--out` also use. On Windows it compares the path as the file system resolves it: a
leading `\\?\` or `\\.\` removed (and `\\?\UNC\` made `\\`), the trailing spaces and dots of each
component removed, `/` made `\`, then normalized and case-folded, with `commonpath`; elsewhere
the normalized path. The order of the refusals is unchanged: a root or a store category given
in the `\\?\` form is still refused first as a network path (`ROOT_UNC_OR_NETWORK`,
`PATH_NETWORK_FOR_STORE`).

| Group | Codes |
|---|---|
| Root | `DEFAULT_ROOT_UNAVAILABLE`, `ROOT_NOT_ABSOLUTE_AFTER_ANCHOR`, `ROOT_IS_DRIVE_ROOT`, `ROOT_IS_PROFILE_ROOT`, `ROOT_INSIDE_CHECKOUT` (also a root containing the checkout), `ROOT_UNC_OR_NETWORK` (also a non-fixed volume) |
| Configuration | `CONFIG_UNREADABLE`, `CONFIG_NEEDS_YAML`, `CONFIG_NOT_A_MAPPING`, `CONFIG_VERSION_UNSUPPORTED`, `CONFIG_UNKNOWN_KEY`, `CONFIG_PATH_TYPE`, `CONFIG_SECRET_SHAPED_KEY` |
| Paths | `PATH_INSIDE_CHECKOUT` (also containing it), `PATH_IS_DRIVE_ROOT`, `PATH_OVERLAP`, `PATH_NETWORK_FOR_STORE` (`state` and `gitea`) |
| Creation | `DRIVE_ROOT_CREATE`, `ROOT_PARENT_MISSING`, `ROOT_MARKER_MISMATCH` |
| Other | `LOCATION_MANAGED_ROOT`, `ASSET_RECORD_INVALID` |

A secret-shaped key is any key, at any depth, containing `password`, `token`, `secret`, `key`
or `credential`. Messages never show configuration values or YAML text.

## Creation

- `resolve()` creates nothing.
- `ensure(category, res, *parts)` creates a category directory below an existing root. It
  creates the root itself only when the root's parent exists and is not a volume root. It never
  creates a registered external location or a direct child of a volume root
  (`DRIVE_ROOT_CREATE`), and never creates anything above the root (`ROOT_PARENT_MISSING`).
- `init()` (`task paths:init`) creates the root, `persistent/`, `ephemeral/` and `assets/`, and
  writes `aieh-root.json` (`aieh-root/1`, `created_at`, `resolver_version`). It alone may create
  an Owner-named root directly below a volume root. A marker of another format is refused.
- Nothing under the root records the checkout path, so the checkout can move. `installs` and
  `assets` keep versions side by side.

## Adapters

The JSON is the cross-language contract (`aieh-paths/v1`; a sample from injected POSIX paths):

```json
{
  "format": "aieh-paths/v1",
  "root": "/home/user/.local/share/aieh",
  "root_source": "default",
  "repo_root": "/home/user/src/ai-engineering-harness",
  "platform": "linux",
  "paths": {
    "state": {"path": "/home/user/.local/share/aieh/persistent/state", "lifecycle": "persistent",
              "class": "B", "source": "root", "outside_root": false},
    "cache": {"path": "/home/user/.local/share/aieh-cache", "lifecycle": "ephemeral",
              "class": "D", "source": "config", "outside_root": true}
  },
  "external": {"effects_root": "/srv/aieh-effects", "guest_state": null},
  "warnings": ["paths.cache lies outside the managed root: /home/user/.local/share/aieh-cache"]
}
```

(`paths` holds all nine categories; two are shown.) `root_source` is `default`, `env` or
`env-relative`. `--format sh` prints `export AIEH_PATH_<NAME>='...'` and `--format ps1` prints
`$env:AIEH_PATH_<NAME> = '...'` for the root, every category and each external location that is
set. Neither re-implements precedence. Output is UTF-8. In PowerShell:

```powershell
function Get-AiehPaths {
    # The resolver's JSON as an object; run from the repository root.
    $json = & python -I -B integrations/paths/aieh_paths.py show
    if ($LASTEXITCODE -ne 0) { throw "aieh_paths.py show exited $LASTEXITCODE" }
    $json | Out-String | ConvertFrom-Json
}
```

## Configuration and the tools venv

`example_config.yml` at the repository root shows every key, with the defaults commented out.
Copy it to `config.yml` (gitignored) to change a setting. Schema version 1 has three top-level
keys: `version`, `paths` and `components.<name>` (each validated by its own component).

Reading `config.yml` needs PyYAML, which the basic tier does not include. Without it the
resolver refuses with `CONFIG_NEEDS_YAML`. `task tools:install` downloads the locked wheels into
`assets/python-wheels/python-tools/<version>/`, writes their asset record, and installs them
from there (`--no-index`) into a venv at `persistent/installs/python-tools/<version>/`, with
pip's cache in `ephemeral/cache/pip`. `<version>` is the interpreter tag and the start of the
lock's sha256. It prints the venv's interpreter; rerun with it, for example
`task paths:show PYTHON=<that interpreter>`. `tools:install` reads no `config.yml`, because it
installs the loader `config.yml` needs: it follows `AIEH_DATA_ROOT` or the OS default only.

## Legacy locations

`doctor` reports the defaults that predate this contract, with their existence,
classification and migration recipe. It moves nothing:

| Name | Windows | Elsewhere | Classification |
|---|---|---|---|
| `integration-store` | `%LOCALAPPDATA%\ai-engineering-harness\state` | `${XDG_DATA_HOME:-~/.local/share}/ai-engineering-harness/state` | service database |
| `gitleaks-cache` | `%LOCALAPPDATA%\ai-engineering-harness\tools\gitleaks` | `${XDG_CACHE_HOME:-~/.cache}/ai-engineering-harness/tools/gitleaks` | installed binary (regenerable) |

## Unavoidable OS-managed locations

These stay where the platform puts them:

- `%TEMP%` or `$TMPDIR`, used by Python's `tempfile` (the tests use it);
- `.git/config`, which holds `core.hooksPath` for the publication gate;
- pip's cache, unless `PIP_CACHE_DIR` is set (`tools:install` sets it to `ephemeral/cache/pip`);
- npm's cache for the Owner host (`apps/owner-host`);
- `__pycache__`, suppressed by `-B`.

## Not yet verified

- macOS and native Linux: the POSIX defaults are tested by injection only, on Windows.
- On POSIX, a root or store on a network or removable volume is refused only when it is a
  `//` path; the volume type is checked on Windows only.
