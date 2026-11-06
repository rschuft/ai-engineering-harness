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

## Owner-directed maintenance items (no plan leaf covers these)

| Item | Scope | Sequencing |
|---|---|---|
| M-1 | Reconcile the blueprint with decision 0001 and verified upstream behavior, preserving the decision's provenance. Update the blueprint's integrity metadata through the versioned process F-02 introduces. | After F-02's verifier re-scope |

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
