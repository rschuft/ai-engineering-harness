# 0005 - Distribution model: upstream download, no redistribution

Status: Accepted (Owner decision) - 2026-11-06
Gate: none. This is the Owner's decision, given in answer to the publication licensing
audit, and the Overseer records it here.
Supersedes: none.

## Context
The [publication licensing audit](../composition/inventory/PUBLICATION-AUDIT.md)
(2026-11-06) found no violation in what the repository publishes: third-party
components are only referenced by name, version, hash, digest or URL, never
redistributed (C1, C2, C9). It kept the obligations of any future packaging or
distribution apart (F1–F6). It left three items to the Owner:
- **U1:** `lmnr-claude-code-proxy` 0.2.0, a proprietary, mandatory transitive dependency
  of `openhands-sdk` 1.60.1. Laminar's terms limit use to personal or internal business
  purposes and forbid redistribution without permission.
- **U2:** `@anthropic-ai/claude-agent-sdk` 0.3.220, inside the referenced agent-server
  image.
- **U3:** whether MIT also covers the repository's documentation.

The Owner answered U1 with a statement of the project's distribution model:

> For U1, accept local use of the pinned OpenHands dependency chain, subject to the
> applicable upstream terms.
>
> AI Engineering Harness is an open-source integration and composition project. We
> intend to publish our own source code, configuration, integration logic, installation
> mechanisms, dependency manifests, and version locks.
>
> Third-party dependencies should be downloaded directly from their original upstream
> distributors onto the user's machine, with pinned versions and verified hashes.
>
> We do not currently intend to vendor, bundle, mirror, repackage, or redistribute
> third-party binaries, libraries, or container images.
>
> Treat this as the default architectural distribution model, not merely a temporary
> workaround for lmnr-claude-code-proxy.

## Decision
1. The project publishes its own source, configuration, integration logic, installation
   mechanisms, dependency manifests and version locks.
2. Third-party dependencies are downloaded directly from their original upstream
   distributors onto the user's machine, pinned and hash-verified.
3. The project does not vendor, bundle, mirror, repackage or redistribute third-party
   binaries, libraries or container images.
4. This is the default architectural distribution model, not a temporary workaround for
   `lmnr-claude-code-proxy`.

## Consequences
The Owner's consequences:
- Do not replace working upstream dependencies solely because their licences prohibit
  redistribution that the project does not perform.
- Preserve attribution, licence identification and relevant usage restrictions.
- Verify that the intended local installation and execution are permitted.
- Keep licensing obligations enforced for repository content that is actually
  redistributed.
- Do not introduce distribution-compliance infrastructure for hypothetical bundled
  releases.
- Re-evaluate licensing when a concrete design proposes vendoring, mirroring, publishing
  modified third-party artifacts, or bundling them into distributable images or
  installers.
- Continue the adoption-first OpenHands implementation without a further architectural
  investigation, unless a licence actually restricts the intended use.

For the audit's items:
- **U1** (`lmnr-claude-code-proxy`) is accepted for local use under the upstream terms,
  with no replacement. Laminar's use restriction (personal or internal business
  purposes) stays recorded in the audit and the ledger, as a usage restriction.
- **F1–F6 and U2** apply as redistribution findings only if a concrete design proposes
  vendoring, mirroring, publishing modified artifacts, or bundling into images or
  installers. They are re-evaluated at that point, through R-04.x. U2 stays carried to
  R-04.1 for a review of its terms for the intended *use*.
- **U3** is a separate Owner decision on the same date: everything authored for this
  repository, code and documentation alike, is MIT as `LICENSE` states, and third-party
  material keeps its own licence.

## Current facts (2026-11-06)
- The repository already follows this model. The audit found no third-party content in
  the tree or its history (C1), and the locks record only names, versions, hashes,
  digests, URLs and declared licences (C9).
- Decision 0001 item 4 and F-04.1 pull the agent-server image from upstream by digest,
  with no re-publication. That is consistent with this model.
- `tools/msys2_lock.py` downloads each locked MSYS2 package from `repo.msys2.org` on the
  user's machine (audit F3). That is consistent with this model.

## Evidence
- The Owner's decisions of 2026-11-06 on U1 and U3, in answer to the Overseer's questions
  after the licensing audit.
- [`composition/inventory/PUBLICATION-AUDIT.md`](../composition/inventory/PUBLICATION-AUDIT.md):
  findings C1, C9, F1–F6 and U1–U3.
- [`composition/inventory/LEDGER.md`](../composition/inventory/LEDGER.md): open licence
  items 1, 2 and 5.
- [Decision 0001](0001-agent-server-dispatch-precondition-and-version-line.md), item 4.
