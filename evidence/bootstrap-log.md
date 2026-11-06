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

| Task | Verdict | Revision | Evidence | Parent gates |
|---|---|---|---|---|
| F-01.1 Resolve compatible upstream version set | PASS (2026-11-06) | `b38493c` | `composition/compatibility-matrix.md`, `composition/candidates.json`: 9 components, each with source, tag, and commit SHA, plus artifact digests where the channel provides them; 12 couplings; 11 explicit exclusions. Builder re-resolved 51 identifiers with 0 differences. Overseer independently re-resolved the SDK `v1.60.1`, Gitea `v28.3.0`, and Agent Canvas `v1.36.0` tag SHAs and the Canvas npm integrity: all match. Runtime compatibility is UNKNOWN, as declared (nothing installed). | F-01: no gate at this leaf; its proof is evaluated at F-01.2. |

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

## Obligations carried to later leaves (from decision 0001)

| Leaf | Obligation |
|---|---|
| F-01.2 | Lock the 1.60.1 line by hash, integrity, and index digest. Lock `conversation_image` to the digest in decision 0001; `latest-python` is non-conforming. Automation is a coupled pin and is not installed. |
| F-04.1 | Docker-only server configuration (`conversation_runtime=docker`, selectable=false). Explicit memory, CPU, and pids caps. Locked `conversation_image`. `OH_SECRET_KEY` set. |
| F-04.2, E-01.5 | Observe the effective mounts and image digest; independent `docker inspect` of the runtime. |
| E-01.2.2 | Allowlist for `working_dir`; reject caller mount and resource overrides. |
| E-01.3.1, E-01.5 | Preconditions P1-P5. Validate the per-conversation runtime discriminator against the pinned OpenAPI. |
| S-01.3.1, S-01.3.2, S-01.4, F-03.3.2, F-03.2.1, S-02.1, S-02.2 | Admission control, host-gateway and egress denial, guest quota ceilings, and host-path and sibling-worktree probes. |
