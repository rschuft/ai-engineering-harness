# 0009 - Managed data root and configuration contract (external by default)

Status: Accepted (Overseer) - 2026-11-07, at the completion of F-07.1 (`8a81953`), implementing the Owner's directive and answers of 2026-11-07; the effects root's placement remains open pending the decision 0004 re-evaluation. Proposed (Architect draft, 2026-11-07), with the Owner's refinements of the same day: three lifecycle categories including `assets/`, the effects root's placement left to the re-evaluation of decision 0004, and the confirmations recorded below.

**Authority:** the Owner directive of 2026-11-07 on external-by-default installation, configuration and filesystem ownership (relayed in the plan amendment 945b563, leaves F-07.1, F-07.2, F-06.1), and the Owner's answers of the same day to the F-07 confirmations. This decision supersedes the repository-local placement (`<repo>/.local`) of the Owner's gap decision of the same day, as that directive does.

**Gate:** architecture consultation before F-07.1, gates C (several structures), G (custody, dogfooding boundary) and F (one contract across tools, integrations, profiles, hooks).

**Supersedes:** none. It refines decision 0004 point 3 without editing it, and leaves decision 0003 and the execution-profile contract (`profiles/README.md` section 11) unchanged.

## Context
The blueprint is silent on installation layout. Today three components invent their own locations:
- the integration store and the publication gate's tool cache sit under a per-user `ai-engineering-harness` tree;
- the guest-state root is Owner-named by act A3, and contract section 11 requires it to lie outside the Owner's profile and never be defaulted;
- the effects store has no default and refuses every user-profile root, the guest-state roots and the integration tree (decision 0004 point 3).

The Owner wants:
- one external managed root with a lifecycle split and an override;
- a tracked example configuration;
- one shared resolver;
- dogfooding without granting source-editing agents the installed harness's secrets or state.

The Owner's refinements add a third lifecycle category for downloaded, reusable artifacts that are neither authoritative operational state nor disposable scratch: pinned model weights, VM base images, installation packages, other verified third-party distributions, tool binaries such as Gitleaks and the Gitea binary, and the tools venv's wheels.

## Decision
1. **One managed root, computed, never from the working directory.**
   - Windows: `%LOCALAPPDATA%\AIEH`, from the environment variable.
   - POSIX: `$XDG_DATA_HOME/aieh`, defaulting to `~/.local/share/aieh`.
   - macOS: `~/Library/Application Support/aieh` (unverified).

   Beneath it are three lifecycle directories:
   - `persistent/`: durable workspaces, databases, credentials, authorization records, configuration and operational evidence. Never implicitly deleted; survives restarts and upgrades.
   - `ephemeral/`: disposable scratch, temporary execution artifacts, caches and regenerable intermediate files. Controlled cleanup only.
   - `assets/`: downloaded, reusable, verified artifacts. Deleted only deliberately: an asset is reclaimable only when no required consumer depends on it and verified reacquisition is possible.
2. **Categories** are a table in the resolver, each with lifecycle, directive class (A-E), creator and consumer:
   - persistent: state, gitea, installs, logs, workspaces;
   - ephemeral: cache, scratch, tmp;
   - assets: assets, laid out as `<kind>/<name>/<version>/`.

   Components consume resolved paths and invent none.

   **Assets and installs.** The earlier `installs` category splits by lifecycle. The downloaded, verified artifact is an asset in `assets/<kind>/<name>/<version>/`. An unpacked or installed copy that must persist is an install in `persistent/installs/<tool>/<version>/`. A tool with no install step runs from its asset directly, so nothing is copied twice. The reason for the split: the asset is the reacquirable source, identified by its provenance and integrity, while the install is derived state that is rebuilt from the asset. Keeping them apart lets an install be rebuilt without a download, and lets an asset be reclaimed deliberately without touching a running install. Base images are assets. Mutable VM disks and overlays are not: they belong in `persistent/` or `ephemeral/` by lifecycle.

   **Asset record.** Every asset keeps `aieh-asset.json` (`aieh-asset/1`) in its directory: `kind`, `name` and `version`; `provenance.source` (a source URL or registry); `integrity` (sha256 per file, the pin, or both); `reacquire` (how to reacquire it); `acquired_at`; and `consumers`. The record is written exclusively and never rewritten.
3. **Precedence**, highest first:
   1. a `config.yml` per-directory override, absolute or relative to the effective root;
   2. `AIEH_DATA_ROOT`, absolute or relative to the repository root of the tree the resolver is loaded from;
   3. the OS default.

   `config.yml` carries no root key. The resolver reads exactly one override variable, and never `.env`.
4. **Refusals.** Each is checked before any filesystem access where it can be decided lexically, and has a stable code and a remedy. Refused:
   - a root that is a volume root, a profile root itself, inside or containing the checkout, or on a network or non-fixed volume;
   - a category path inside or containing the checkout, at a volume root, overlapping another category, or on a network volume for a store;
   - an unknown key, a wrong type, an unsupported version, or a secret-shaped key;
   - a root marker of another format, and an asset record that does not match `aieh-asset/1`.
5. **Creation.**
   - `resolve` creates nothing.
   - A consumer's `ensure(category)` creates below an existing root. It creates the root only when the root's parent exists and is not a volume root.
   - `init` alone may create an Owner-named root that is a direct child of a volume root. It creates `persistent/`, `ephemeral/` and `assets/`, and marks the root `aieh-root/1`.
   - No directory is otherwise ever created directly under a volume root.
   - F-07.x contains no deletion code.
6. **Registered external locations.** The resolver reports these from configuration and neither defaults, creates nor validates them.
   - `effects_root` (decision 0004 point 3): no default; validated and custody-checked only by the effects store. Its placement awaits the decision 0004 re-evaluation; directory placement is not a security control. The resolver provides the check that an effects root lies neither inside nor around the managed data (`LOCATION_MANAGED_ROOT`), for the effects store to adopt.
   - `guest_state` (decision 0003 act A3; contract section 11): Owner-named, never defaulted, outside the profile. Posture P-A: the guest-state root is not relocated; relocation is a separate Owner act.
7. **Configuration.**
   - `example_config.yml` is tracked at the repository root. `config.yml` is optional and gitignored; its absence is the supported default.
   - Schema v1: `version`, `paths`, and `components.<name>` (each validated by its component).
   - Secrets never appear in either file. The loader refuses secret-shaped keys and names the credential custody that owns them (decision 0007).
8. **Libraries.**
   - Platform conventions are hand-written. platformdirs is not adopted: it splits data, cache, state and logs across OS bases and nests an author segment on Windows.
   - PyYAML 6.0.3, already hash-locked, is used only when `config.yml` exists. `task tools:install` downloads it wheels-only, with required hashes, into `assets/python-wheels/python-tools/<version>/` with its asset record, and installs it from there into the venv `persistent/installs/python-tools/<version>/`. It reads no `config.yml`, because it installs the loader that `config.yml` needs. The offline basic tier is unchanged.
   - dotenv was evaluated and not adopted.
9. **Adapters.** The resolver's JSON (`aieh-paths/v1`) is the cross-language contract. `--format sh` and `--format ps1` are thin emitters. No adapter re-implements precedence.
10. **Relocation and upgrade.**
    - Nothing under the root records the checkout path as identity.
    - The checkout records the root only in the gitignored `config.yml`.
    - `installs/<tool>/<version>/` and `assets/<kind>/<name>/<version>/` sit side by side.
    - `persistent/` changes only through each component's own migration.
    - A marker format mismatch is refused.
11. **Boundary.** Directory placement is never a security boundary. A source-editing agent is kept from the managed root by:
    - the execution guest (0003 P3-P7);
    - the exact conversation mount policy;
    - git-bundle exchange, so untracked configuration never enters the guest;
    - the role-token matrix (0007).

    During bootstrap, host-side agent sessions reach the whole managed root as the Owner's account (`fd-bootstrap-shared-identity`). This is the accepted limit, and no new sandboxing is introduced.

## Consequences
- **F-07.1** delivers the resolver, configuration, tests and this record. It changes no component's location.
- **F-07.2** adopts the contract and moves and deletes nothing. It:
  - moves the integration store's default to `persistent/state/integration/`;
  - moves the Gitleaks download to `assets/` with its asset record, and its unpacked binary to `persistent/installs/gitleaks/<version>/`, or runs it from the asset where no install step is needed;
  - adds `LOCATION_MANAGED_ROOT` and legacy-tree refusals to the effects store;
  - moves `task qualify` scratch;
  - runs the hooks through the `sh` adapter;
  - adds the inventory assets and findings;
  - publishes `doctor`-based migration output;
  - plans the guest-state migration by classification rather than as one tree: base images to `assets/`, mutable disks and overlays to `persistent/` or `ephemeral/` by lifecycle, by a copy, an integrity verification, a reference switch and a separately authorized cleanup, without interrupting active guest workflows;
  - proves the bundle-exclusion and mount-policy falsifiers.
- **F-06.1** consumes `gitea`, `installs` and `assets`. Its binary and state are kept separate, so an upgrade never touches state.
- **The decision 0004 re-evaluation** decides the effects root's placement against the actual Windows ACLs, process identities and the directory-replacement threat model, distinguishing detection from OS-enforced prevention. It keeps the effects store's custody checks and authorization requirements.
- **G-04.2.2** measures, on the live effects root, that a non-elevated Owner-account process cannot read, write, rename or replace it.
- **Recorded limits:**
  - Gitea's class-E data sits in Owner-session custody, by Owner decision;
  - the Linux root deviates from the XDG cache/state split by design;
  - macOS is unverified.

## Owner confirmation
The Owner answered the F-07 confirmations on 2026-11-07:
1. **Effects root.** The Owner challenged the premise that a drive-root directory gives custody protection against processes of the same account. Directory placement is not treated as a security control. The effects store's custody checks and authorization requirements are kept, and decision 0004 is re-evaluated, not silently superseded. Until then, no default and no placement preference is encoded here.
2. **Guest state.** The guest-state root stays intact (posture P-A). F-07.2 plans its migration into the managed root by the classification above, after an inventory, and performs none of it now.
3. **A root inside or containing the checkout is refused** (the gap decision's `.local` is superseded). Relative overrides are for sibling or other directories.
4. **Three lifecycle categories:** `persistent/`, `ephemeral/` and `assets/`, as in Decision points 1 and 2.

## Evidence
- The Owner directive of 2026-11-07, and the Owner's answers to the F-07 confirmations of the same day.
- Plan leaves F-07.1, F-07.2 and F-06.1 (945b563, 7b41701).
- Decisions 0003, 0004, 0005 and 0007.
- Blueprint `#infrastructure-state` and `#containment-architecture`.
- `integrations/storecore/storecore.py`, `integrations/effects/effects_store.py`, `tools/guest.py`, `tools/publication_gate.py`, `composition/resolve.py`, `profiles/README.md` section 11, `profiles/*/profile.json`, `security/inventory.json`, `policy/role-tokens.json`.
- `composition/lock/python/windows-x86_64.txt` (pyyaml 6.0.3, platformdirs 4.14.5, python-dotenv 1.2.4).
- The Architect's consultation of 2026-11-07 (the `python -I` venv measurement; the platformdirs documentation).
- The F-07.1 implementation: `integrations/paths/aieh_paths.py`, `integrations/paths/tools_install.py`, `integrations/paths/tests/test_aieh_paths.py`, `example_config.yml`, `composition/lock/python/tools-requirements.txt`.
