# Bootstrap progress log

Minimal, traceable record of Overseer verdicts while the adopted Work system
(Backlog.md, per the blueprint) does not yet exist. It is not a second task
system: task definitions stay in the canonical plan JSON, and this log will be
migrated into the adopted Work system when that is established. Every entry
names the exact revision and the evidence the verdict rests on. Status values:
PASS, FAIL, UNKNOWN, BLOCKED. Parent (Medium/Large) contracts are evaluated
separately and never inferred from a child passing.

## Bootstrap

- **2026-11-05: seed bootstrap (not a plan task).** Commit `13197dd`. Archive
  inspected before extraction: 147 entries, no traversal or absolute paths, no
  symlinks, no `.git` metadata, no `LICENSE`. Content scan (secret, personal-path,
  email, and private-network patterns, with a positive control) found nothing.
  Inline HTML scripts are small bespoke page code, not vendored libraries.
  `tools/verify_seed.py` passes in place and in a fresh `core.autocrlf=true`
  clone. `.gitattributes` keeps the byte-verified seed files verbatim. All 136
  leaves remain Not started.

## Leaves

States follow the Owner's publication policy: implemented locally, then verified
locally, then pushed to `origin/main`. Parent acceptance is recorded separately.
Merging does not apply, because verified work is committed directly to `main`. A
push never implies parent acceptance.

| Task | Verdict | Revision | Evidence | Parent gates |
|---|---|---|---|---|
| F-03.2.1 Declare reference Linux guest profile | **Part a verified (2026-11-06); leaf not yet passed.** Part b, provider validation, needs the A2 install and the restart that completes A1 | `e90b02f` | `profiles/strong-windows-qemu-whpx/` (Debian 13 genericcloud image pinned by sha512 and sha256; Debian publishes no signature, so provenance is TLS only; SeaBIOS from the pinned QEMU; NoCloud seed on a read-only virtio disk, generator specified for F-03.2.2; ceilings 8 vCPU, 16 GiB, 40+120 GiB; SLIRP `restrict=on` with loopback-only forwards; `-accel whpx` with no fallback; vmx/svm masked), QEMU 11.1.3 MSYS2 ucrt64 lock (160 packages, signed-DB provenance, no admin), `strong-incus-vm` (4 pins UNKNOWN), `tools/check_profile.py` with 47 tests. The Overseer re-ran the profile check, the 66 tool tests and verify_seed. Contract fix (Overseer): Incus may use read-only, provider-generated seed and config media; the 9p `config` share stays forbidden. To be amended in part b. | F-03.2: evaluated at F-03.2.2. |
| F-03.1 Select managed-VM providers and isolation contract | PASS (2026-11-06), specification only; pushed | `39912fd` | `profiles/README.md` (contract: strong and trusted-workload tiers, properties P1-P12 with inspection methods, lifecycle, disclose-and-refuse with `TIER_UNAVAILABLE`, no nested virtualization assumed, remote-Linux minimum contract, Owner conditions C1-C7, version floors and pin rule), `profiles/matrix.md` (every non-unverified cell cited), `profiles/properties.json`. For each OS a non-nested strong path is specified: Windows QEMU+WHPX (reference, Owner W1) or remote Incus; Linux Incus VM; macOS Lima. The Builder validator passes; the Overseer re-ran it and checked coverage. Five sources did not fully confirm decision 0003; the corrections are recorded as current facts there. **Every runtime claim is UNKNOWN.** Host acts A1-A3 are pending separate Owner approval. | F-03 (Large): not evaluated until F-03.4. |
| F-02 Create the umbrella repository and repeatable tasks | PASS (2026-11-06); pushed | `358eaff`, `fcc0eba`, `54fa067` | Reconciled with the existing GitHub repository; no new repository was created. Seed verifier re-scoped (Owner direction) to classes contract / authority / ordinary, plus `--baseline seed`, which checks the original import strictly against `13197dd`. Contract checks are unchanged in strength, and the 19 tool tests fail against weakened verifiers. `Taskfile.yml` (Task 3.54.0, run from a checksum-verified binary and not installed), `tools/check_prereqs.py`, and `CONTRIBUTING.md` (prerequisites per OS, each marked verified or not yet verified). The repository layout is documented, with planned homes named but not created. **Proof:** from a fresh `core.autocrlf=true` clone, `task qualify` exits 0 (setup, then a full resolution with 348 checks, 0 failed, and digests equal to the F-01.2 record). Afterwards, `git status` of the clone is empty, so no tracked file or upstream project was edited. `task setup` also passes under WSL2 Ubuntu (basic tier only). The Overseer independently ran the four raw setup commands and reviewed the test-fixture repair: only ordinary files are re-hashed in the fixture. Defect: the F-02a test fixture assumed ordinary files were unchanged. It was introduced by `358eaff`, exposed by F-02b, and fixed forward in `54fa067`. | None scheduled at this leaf. |
| F-01.2 Generate and verify component lock | PASS (2026-11-06); pushed | `3e8f789`..`8ab01d0` | Lock and resolver are under `composition/` (`python -I composition/resolve.py --work <dir>`). The Builder ran two clean runs from a fresh clone of `a9136ce`. The Overseer ran a third, independent resolution from its own fresh clone of `8ab01d0`. All three exited 0 with 348 checks, 0 failed, `resolution_digest` `b23c42b2…94e1ce`, and `installed_digest` `2ee95857…329757`. Installed: 196 Python packages (including `func-timeout` 4.3.5 under decision 0002) and 669 npm packages, equal to the lock. `conversation_image` verified at its index digest. Negative controls each exit 1: a wheel-hash tamper, a sdist-hash tamper (refused before extraction), and a tamper of a reviewed build-file hash. Overseer reviewed the resolver's scrubbed build environment and credential-free git calls. Inventory labels: component metadata inventory; partial Syft SBOMs with their coverage stated; **license compliance NOT VERIFIED**. | **F-01: PASS on this Windows host.** A clean checkout resolves identical revisions and reports the installed versions. Install inside the Linux guest is UNKNOWN and is carried to F-03/F-04. OCI images were checked by manifest digest only; no signatures were verified. |
| F-01.1 Resolve compatible upstream version set | PASS (2026-11-06); pushed | `b38493c` | `composition/compatibility-matrix.md`, `composition/candidates.json`: 9 components, each with source, tag, and commit SHA, plus artifact digests where the channel provides them; 12 couplings; 11 explicit exclusions. Builder re-resolved 51 identifiers with 0 differences. Overseer independently re-resolved the SDK `v1.60.1`, Gitea `v28.3.0`, and Agent Canvas `v1.36.0` tag SHAs and the Canvas npm integrity: all match. Runtime compatibility is UNKNOWN, as declared (nothing installed). | F-01: no gate at this leaf; its proof is evaluated at F-01.2. |

## Decisions

- **2026-11-06: [0001](../decisions/0001-agent-server-dispatch-precondition-and-version-line.md) Accepted.**
  Architect consulted at gates A and G before F-01.2. The blueprint's
  `selectable_conversation_runtime_v1` precondition names a token that no upstream
  release advertises (a documentation defect exposed by F-01.1), and the qualified
  pin v1.58.2 is below Agent Canvas 1.36.0's floor of 1.59.0. The decision locks
  the 1.60.1 line, restates the precondition as observed `/server_info` conditions
  plus required configuration, and carries the containment findings forward as
  re-examination obligations on existing leaves. Before accepting, the Overseer
  verified that all named leaves exist and checked the Canvas `defaults.json` pins.

- **2026-11-06: [0001](../decisions/0001-agent-server-dispatch-precondition-and-version-line.md) clarified** at the Owner's direction. Docker-only is the current safety
  setting, not an exclusion of Podman, dedicated-VM execution, or other approved providers.
  The blueprint is reconciled at M-1.
- **2026-11-06: [0002](../decisions/0002-reviewed-sdist-exception-for-resolution.md) Accepted (Overseer, no gate earned).**
  A reviewed, hash-pinned sdist exception for `func-timeout` 4.3.5, which has no wheel
  on PyPI. Every other package stays wheels-only.

- **2026-11-06: [0003](../decisions/0003-execution-guest-providers-and-isolation-contract.md) Accepted.**
  Architect consulted at gates C and G before F-03.1. The decision sets the execution-guest providers and
  the isolation contract (P1-P12, strong vs trusted-workload tiers, disclose-and-refuse). **Owner selected
  W1** (QEMU + WHPX as the Windows strong-tier reference) with seven conditions. Selecting the provider
  authorizes no host change: A1 (enable `HypervisorPlatform` and restart), A2 (QEMU install) and A3 (the
  guest-state directory) each still need their own Owner approval when required. Until then F-03.2.1+
  cannot be realized on this host. Disclosure: the consultation briefly started the Owner's WSL Ubuntu distro
  for read-only inspection and stopped it again. Later dispatches treat that distro as untouchable.

- **2026-11-06: Owner host acts.** A1: the Owner authorized the Overseer to enable the Windows Hypervisor Platform feature through an interactive UAC prompt. The feature went from Disabled to Enabled; no other feature was touched and no restart was performed; a restart is pending and will be coordinated with the Owner. A3: the guest-state directory was created outside the repository and the Owner profile, with its ACL restricted to the Owner account, SYSTEM and Administrators. A2 (pinned QEMU install) is approved under eight conditions and has not been performed yet. A stray `.gnupg/common.conf`, which a Builder accidentally created in the Owner profile, was verified as unreferenced and removed under explicit Owner authorization.
- **2026-11-06: publication-safety gate operational** (Owner-directed), commit `9d4c39f`. Gitleaks 8.30.1, pinned and checksum-verified, in a per-user cache, with the binary re-hashed on every run. Repository-local pre-commit and pre-push hooks (`core.hooksPath=.githooks`) fail closed. Narrow rules cover personal paths and credential-store file paths. `.gz` files are decompressed and scanned; other binaries are refused unless allowlisted. The Builder added 19 gate tests (85 tool tests in total). The Overseer ran independent controls: a synthetic credential was rejected with its value redacted; Windows and POSIX personal paths were rejected; a placeholder documentation example passed; a missing scanner was refused (fail closed). History scan (read-only, all commits): 3 `generic-api-key` findings, all English prose in the seed plan files (entropy 3.51); **no real credential, nothing to rotate**.

## Owner-directed maintenance items (no plan leaf covers these)

| Item | Scope | Sequencing |
|---|---|---|
| M-1 | Reconcile the blueprint with decision 0001 and verified upstream behavior, preserving the decision's provenance. Update the blueprint's integrity metadata through the versioned process F-02 introduces. | **Done (2026-11-06), `e1ed236`; pushed.** 8 passages reconciled, each with a visible note linking decision 0001, plus a Reconciliation notes entry. The 31 October observations made at v1.58.2 are kept as history; forward-looking requirements are restated. The blueprint's sha256 and size are updated in `SEED_MANIFEST.json` in the same commit. Both verify modes pass; the 105 element ids are unchanged; style and script blocks are byte-identical. Overseer reviewed the word diff and independently ran both modes. Recorded but not changed: v1.57.0 release-note statements, and the claim that runtime never falls back to local, which is checkable only with docker inspect (owned by E-01.3.1 and E-01.5). |
| M-2 | Reconcile blueprint `#platforms` and SHIP-01 wording, which reads WSL2 as a peer of a VM, with SEC-01 and decision 0003's tiers. Use the authority-class process. | After F-03.1 |

## Open license and distribution items (owned by G-02.1, R-04.1, R-04.2)

The full list is in `composition/inventory/LEDGER.md`. The most material items are
`lmnr-claude-code-proxy` 0.2.0, declared `LicenseRef-Proprietary` and pulled in by
`openhands-sdk` through `lmnr` (it is also in the Canvas image), and `func-timeout`,
which is LGPLv2. The lock references these packages and does not redistribute them.

## Obligations carried to later leaves (from decision 0001)

| Leaf | Obligation |
|---|---|
| F-01.2 | Lock the 1.60.1 line by hash, integrity, and index digest. Lock `conversation_image` to the digest in decision 0001; `latest-python` is non-conforming. Automation is a coupled pin and is not installed. |
| F-04.1 | Docker-only server configuration (`conversation_runtime=docker`, selectable=false). Explicit memory, CPU, and pids caps. Locked `conversation_image`. `OH_SECRET_KEY` set. |
| F-03.x, F-04.x | Run `composition/resolve.py` inside the Linux guest (glibc ≥ 2.28, CPython 3.12); its Linux build-environment branch has never run. |
| F-04.2, E-01.5 | Observe the effective mounts and image digest; independent `docker inspect` of the runtime. |
| E-01.2.2 | Allowlist for `working_dir`; reject caller mount and resource overrides. |
| E-01.3.1, E-01.5 | Preconditions P1-P5. Validate the per-conversation runtime discriminator against the pinned OpenAPI. |
| S-01.3.1, S-01.3.2, S-01.4, F-03.3.2, F-03.2.1, S-02.1, S-02.2 | Admission control, host-gateway and egress denial, guest quota ceilings, and host-path and sibling-worktree probes. |
