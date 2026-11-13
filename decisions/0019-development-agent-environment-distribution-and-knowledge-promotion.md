# 0019 - Distributing the development agent environment, and promoting lessons into project knowledge

Status: Proposed - 2026-11-12. Prepared by the product manager on the Owner's directions of 2026-11-12, verbatim in
`evidence/bootstrap-log.md`, Decisions: "Owner direction: distribution and onboarding requirements" and "Owner
direction: knowledge-promotion assessment of local agent memories". It rests on a consultation with the shared
architect (gates B, C and F; advisory) and a milestone-placement analysis by the program manager, both weighed
by the product manager. **This record grants nothing until the Owner accepts it.** Until then, `CLAUDE.md`'s
statement that the role agents "are not part of this repository" stands, and nothing is installed from a clone.

## Context

- The five development roles and their skills are the Owner's own definitions. They live in a separate agent
  catalog repository (published at `ce6ffa2`) and today load from the Owner's user-level configuration. A fresh
  clone cannot reproduce them. The Owner requires that it can, without relying on prior machine setup, without
  duplicate maintained definitions, and without disturbing a user's unrelated settings, agents or skills.
- The catalog already has a projection step. For each harness it produces each definition's exact text and
  relative path, with definition, profile and projected digests (observed through a read-only projection query
  in the Owner's environment; one adapter, `claude-code`).
- This repository already has three install patterns to reuse: `composition/` pins by version and hash
  (decision 0005: download from upstream, no redistribution); `tools_install.py` installs hash-locked wheels
  under the managed data root; `publication_gate.py install` downloads a pinned, hash-checked tool and changes the
  clone's own configuration only.
- `catalog/` holds the harness's *runtime* content (Skills and OpenSpec schemas shipped to managed projects),
  which reaches agents only through `catalog_pins` promoted by P-04.3. The word "catalog" therefore names two
  different things. This record calls the roles' content the **development agent environment**.

## Decision

1. **Two classes.**
   - **Development tooling:** the five role agents and the skills they reference. Canonical source: the
     Owner's agent catalog. They run on the host, as `bootstrap-host-agents` (`security/inventory.json`).
   - **Harness runtime:** `catalog/` and, later, the agent-assignment manifests and role profiles. Canonical
     source: this repository, then the protected Gitea catalog. They reach agents only through `catalog_pins`
     (P-04.3), and this record leaves that path unchanged.
   - The development tooling never enters `catalog/` or `catalog_pins`, and being installed as development
     tooling qualifies nothing for runtime use.
2. **Canonical source, pinned.** This repository tracks no copy of a role definition or skill. It tracks one lock
   under `composition/lock/`, holding the catalog repository, a full commit and the sha256 of the catalog's
   published projection manifest. The manifest lists path and sha256 for the closed set: the five agents and
   every skill they reference. The lock is the admission `AGENTS.md` requires before a retrieved Skill is more
   than data. Branches and tags are never used.
3. **Install into project scope only.** A small installer using only the standard library fetches the projection
   at the pin over plain HTTPS or Git, with no provider API, CLI or credential (decision 0017). It verifies the
   manifest against the lock and every file against the manifest, then places the files byte-exact in the
   clone's own project scope (`.claude/agents/`, `.claude/skills/`). Those paths are ignored by git and refused by
   the publication gate. The write set is closed: the manifest's files and one install record in the clone.
   The installer never writes user scope, never edits a settings, hooks, MCP or TOML file, and never
   re-serializes a definition. A target path it did not place refuses the install. The install is separate from
   `task setup`, so an unreachable catalog cannot fail F-02's setup proof.
4. **Upgrade and removal.** An upgrade is a reviewed change to the lock, followed by a re-run. Upgrade and
   uninstall act only on recorded paths whose bytes still match. A modified file is reported and left in place.
   Memory is never installed, carried across a role rename, or removed.
5. **Precedence is disclosed, not engineered.** Where a user has their own agent or skill with a role's name,
   the setup reports it and records which one the harness loads. Installer tests and the first real install
   run in a throwaway clone.
6. **Profiles and memory.** The catalog's harness profile sets model, effort and memory scope. The installer
   rewrites nothing. Recommended for distribution: memory scope `local` (inside the clone, already ignored and
   refused by the gate).
7. **Codex.** The setup instruction and the repository steps work under Codex through `AGENTS.md`. The role set
   is installed for Codex only when the catalog publishes a Codex projection and a fresh-clone run shows it
   loaded; the same pin, placement and removal rules then apply.
8. **Onboarding.** The README carries the clone-to-setup flow and one default setup instruction. `AGENTS.md`
   carries a Setup section that the instruction follows. Both work before any role or skill is installed.
   Neither calls the role environment reproducible until a fresh installation is verified (point 9).
9. **What makes "reproducible" true.** For each operating system:
   - **E1, offline fixtures:** a populated fake user profile is byte-identical after install, upgrade and
     uninstall; installs are idempotent; a digest mismatch and an occupied path are refused.
   - **E2, fresh clone:** a clean profile and the README instruction given verbatim, with the lock, manifest and
     placed hashes recorded.
   - **E3, load:** a new session's own init event lists exactly the locked agents and skills.
   - **E4, controls:** an altered manifest is refused; a planted user namesake is reported.
   - **E5, Codex:** given the same instruction, Codex completes the repository steps.
   - E2 to E5 are live and need the Owner's authorization (egress, a clean-profile login, model calls).
10. **Promoting lessons into project knowledge.** No new store. Memory is a dated observation, never authority.
    1. *Propose:* the role that learned a lesson names it in its unit report, in one line with the evidence that
       shows it and the proposed home. It never quotes memory text.
    2. *Classify:* at the next planning pass, the program manager reconciles each candidate against its home:
       agent definitions or skills (the catalog); `AGENTS.md`/`CLAUDE.md` rules; decisions and docs; planning
       records; evidence; local only. It records "already held by X", or makes the lesson discovered work (a
       leaf or a deferral).
    3. *Decide by home:* `AGENTS.md` rules on the Owner's ask; docs, conventions and guards inside a committed
       leaf; decisions by the lead accountable for their scope (decision 0018 point 3, accepted 2026-11-12, revision 4); catalog
       definitions and skills by the Owner, in the catalog's own repository.
    4. *Land and verify:* re-check the lesson against the current tree; prefer a deterministic check with a test
       shown to fail on the old code; commit through the publication gate.
    5. *Reach users:* repository homes arrive with the next clone; catalog homes arrive by a lock bump verified as
       in point 9.
    6. *Prune:* once the record exists, the memory's owner replaces its own entry with a pointer to it. No role
       edits another's memory.
    7. *Recurrence:* a lesson seen twice is promoted or explicitly declined.
    - Never published: raw memory, personal or machine paths, other projects' names or knowledge, credentials.

## Consequences

- On acceptance, `CLAUDE.md`'s "not part of this repository" sentence is reworded. Its proposed text: "Their
  definitions are maintained in the Owner's agent catalog, not here. This repository pins one revision and
  installs it into a clone's project scope only through the documented setup. They are not needed to
  contribute. Do not write, edit, copy or impersonate them; when a role is not installed, say so."
- The work is the plan amendment adding group F-11 (`evidence/DS1-plan-amendment-proposal.md`).
- Decisions 0005, 0009, 0014 and 0017 are applied, not amended. Decision 0018 is unaffected.

## Not decided here

- The catalog's fetchability, licence and URL.
- Its publication of the projection and manifest, and where.
- The role set's closure at a named commit.
- Codex parity.
- Whether the default instruction installs the roles or offers them.
- The authorizations for E2 to E5.

Each of these is an Owner act in OA-29.
