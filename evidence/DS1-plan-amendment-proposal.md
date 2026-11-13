# DS1 plan amendment proposal: a fresh clone reproduces the development agent environment (OA-29)

> **Prepared by the product manager (2026-11-12). A proposal for the Owner's decision; nothing in the plan is
> changed.** It comes from the Owner's directions of 2026-11-12 on distribution and on knowledge promotion
> (verbatim in [the log](bootstrap-log.md#owner-direction-distribution-requirements) and
> [here](bootstrap-log.md#owner-direction-knowledge-promotion)), from Proposed
> [decision 0019](../decisions/0019-development-agent-environment-distribution-and-knowledge-promotion.md), and from
> the program manager's milestone placement. Any change goes through the integrity process on the Owner's
> approval.

## 1. Classification and placement

- The Owner's requirements are **product acceptance requirements of a milestone of their own: DS1**. They are
  **not D1 prerequisites.**
  - No D1 proof reads project-scope agents, the onboarding text or the agent catalog.
  - D1 runs the roles from the Owner's existing environment.
  - No content of local agent memory is needed by any D1 proof.
- F-11 is independent of D1. No D1 leaf depends on it, and it depends on no open D1 leaf. It is also independent
  of P-05.1.
- **Sequencing:** behind D1's authorized work. F-11's offline leaves fill gaps while D1's leaves wait on Owner
  gates, and they never displace a ready D1 leaf.

## 2. Milestone DS1

**Outcome.** A new user on a clean profile clones the repository and gives the README's one setup instruction to
Claude Code. The AI installs and verifies the five role agents and their skills from the canonical catalog at a
pin, without changing anything else of the user's.

**Acceptance criteria.** These are the proof of the terminal leaf F-11.4.
1. **Fresh-clone setup.** On a clean profile with no harness agents or skills, a fresh clone at a named commit is
   set up by the README's single setup instruction. The AI performs and verifies the installation, and a new
   session's own init event lists exactly the locked agents and skills.
2. **Canonical source.** The repository tracks no copy of a role definition or skill. The installed bytes equal
   the manifest's sha256 values at the locked catalog commit. An upgrade is a reviewed change to the lock only.
3. **Your setup is left untouched.** The user-scope agents, skills, settings and memory are byte-identical before
   and after install, upgrade and uninstall. The installer refuses an occupied path it did not place, and never
   writes user scope or settings.
4. **Bootstrap.** The setup instruction works with no specialized agent or skill present, and `task setup` passes
   with the catalog unreachable.
5. **Codex.** Given the same instruction, Codex completes the repository steps through `AGENTS.md`. Codex role
   installation is either provided and verified, or stated as not provided.
6. **Runtime separation.** The role set appears in neither `catalog/` nor `catalog_pins`, shown by a mechanical
   check.
7. **Honest status.** The README calls the setup reproducible only on the strength of the E2 to E5 evidence of
   decision 0019 point 9.

## 3. Leaves

The new Medium group is **F-11, "Reproduce the development agent environment from a fresh clone"** (phase 1).

| Leaf | Deps | Proof sketch | Gate |
|---|---|---|---|
| F-11.1 Install the pinned role environment into project scope: the lock schema under `composition/lock/`, the stdlib installer, and the ignore and gate entries for `.claude/agents` and `.claude/skills` | F-02, F-07.1 | E1, against a fixture catalog and a fixture user profile: <ul><li>a closed write set, with byte-exact placement;</li><li>refusals for a hash or commit mismatch and for an occupied or modified path;</li><li>upgrade and uninstall touch only recorded, unmodified paths;</li><li>the user tree's hashes are unchanged;</li><li>`task setup` is unaffected.</li></ul> | Offline; decision 0019 accepted |
| F-11.2 Pin the published catalog projection | F-11.1 | A real lock entry (repository, full commit, manifest sha256). A fetch at the pin verifies every file. The closure check passes. | Owner: catalog URL, licence and publication; closure; egress for the fetch |
| F-11.3 Onboarding: the `AGENTS.md` Setup section and the README instruction | F-11.1 | The instruction runs the setup steps before any role is installed, and the text matches what was verified. | The Owner's approval of the `AGENTS.md` text; Codex parity; install or offer |
| F-11.4 Verify a fresh installation (terminal) | F-11.2, F-11.3 | Criteria 1 to 7 above. | Owner: egress, a clean-profile login, model calls |
| F-11.5 First promotion of lessons into repository knowledge | F-02 | <ul><li>Documented conventions: blueprint edits, decision acceptance, the commit message across gate rejections, the Windows shell traps.</li><li>A guard that test fixtures refuse the ambient managed root.</li><li>A staleness check for the security inventory's README.</li><li>A size guard for `AGENTS.md`.</li><li>Each guard shown to fail on the old code.</li></ul> | Offline. Off DS1's critical path: the terminal leaf does not depend on it. |

Design notes from the program manager, adopted:
- F-11.1 does not depend on F-10.2. A stdlib fetch that checks each file against the manifest needs neither
  Dulwich nor byte-stable archives.
- The ignore entries belong in F-11.1, not in a commit now.

**Critical path:** the catalog's publication of the projection (an Owner act in another repository) → F-11.2 →
F-11.4. F-11.1 and F-11.3 run beside it.

## 4. Prepared execution commitment

Recorded only once this amendment and decision 0019 are accepted:

> **Commitment: F-11.1 (an offline increment of DS1).** Terminal leaf F-11.1; acceptance is its proof. Offline
> only: E1 fixtures, a fixture catalog and a fixture user profile. No network, no real catalog, no user profile
> touched. Readiness is stated as three facts: technically ready, authorized, independently enforced. Sequenced
> behind D1's authorized work.

## 5. Knowledge-promotion first batch, by home

- **Repository guards and docs:** F-11.5.
- **`AGENTS.md` rules:** two candidates (no shell heredocs for text with escapes; fixtures refuse the ambient
  managed root). They are folded into F-11.3's `AGENTS.md` change, so the Owner approves `AGENTS.md` once.
- **Catalog skills and definitions** are the Owner's, in the catalog repository; they reach users through F-11.2's
  lock:
  - a mutation method that proves a test can fail;
  - rehearsing a live act offline before its authorization;
  - the engineer stopping and returning a validated patch when a needed path is outside its dispatch;
  - ending background work it started;
  - a memory rule;
  - `fix-forward`'s carve-out for the blueprint's visible reconciliation notes.
- **Local only, never published:** component-behaviour notes already held in evidence and decisions; timings,
  commit identifiers, scratch-script pointers, leaf status; machine paths; another project's knowledge.
