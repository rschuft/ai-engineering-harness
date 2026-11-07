# 0008 - Outcome identity: assignment, form and record

Status: Proposed (Architect, gate B consultation for P-03.1) - 2026-11-07. Refines blueprint
#authority (outcomeId rule, link table) and #integration-contracts ("OpenSpec goal and x-fields";
"We own stable IDs") within intent-record/v1 (P-01) and the P-02.1 design pointer. Creates no
OpenSpec schema change, no intent-record format change, no registry and no writer.
Supersedes: none.

## Context
The blueprint assigns an outcomeId when an objective is accepted, lets several changes and tasks
reference it, and carries it in OpenSpec's x-fields, which OpenSpec preserves without validating.
intent-record/v1 identifies an accepted objective only as a proposal-local item (O1) with an
acceptance reference. P-03.1 therefore left the objective kind unknown. OpenSpec 1.16.0
documents x- keys as the user's own ("never reads, writes or reports it") and archives a change
by moving its folder to openspec/changes/archive/YYYY-MM-DD-<name>/. No plan leaf owns the
acceptance-recording write (sequence step 11).

## Decision
1. Record. An accepted objective is an Objective item of an intent-driven proposal's intent
   record with authority: accepted and an acceptance reference (intent-record/v1 invariant 4),
   in one change of the project's OpenSpec tree: the outcome's declaring change. The project
   repository's git history is the revision authority. Nothing outside the OpenSpec tree is
   authoritative for an outcome.
2. Assignment. The outcome id is minted once, when that acceptance is recorded, by the party
   recording it: the integration's acceptance recorder on the Owner's Accept decision (target),
   or, during bootstrap, the agent recording an Owner acceptance given as a durable statement or
   delegated by an accepted decision record. It is never minted before an acceptance reference
   exists, never by the normalizing model, and never again for the same item: re-acceptance
   (amendment) keeps the id. Minting is clerical; the acceptance reference, not the record, is
   the proof that the Owner accepted.
3. Form. A random UUID (version 4) in canonical lower-case text (8-4-4-4-12 hex). It carries no
   meaning, order or derivation. Lineage reference: outcome:<uuid>[@<commit>].
4. Declaration. In the declaring change's .openspec.yaml, the top-level key x-outcomes maps the
   id to exactly {item: O<n>, acceptance: <reference>}, where acceptance equals the item's own
   acceptance field (a binding check, not a second authority). One id is declared by exactly one
   change at any commit of the repository. A change that serves an existing outcome references
   it (an item source, a Backlog --ref) and never re-declares it.
5. Revision. @<commit> is the full commit id of the project repository at which the outcome is
   read; the pinned reading is immutable. A resolution's observed_digest is the sha256 of the
   declaring change's proposal.md blob at that commit. An amendment of an accepted objective is
   written in the declaring change's proposal with a new acceptance reference: same id, new
   revision ("preserve subsequent revisions rather than overwriting history"). A different goal
   is a new outcome with a new id. Supersession links are not defined here (K-03.3.2).
6. Resolution rule. From git objects only, at the pinned commit or at HEAD for current:
   enumerate openspec/changes/<change>/.openspec.yaml and
   openspec/changes/archive/<dated-change>/.openspec.yaml; exactly one declares the id, else
   missing or ambiguous; the declared item exists in that change's proposal Objective section with
   authority: accepted and the same acceptance, else the outcome does not resolve. A resolved
   answer reports the declaring change path, the item, its acceptance reference, its source (the
   trace to the source statement), the accepted Acceptance Criteria that cite it (acceptance
   conditions), observed_revision and observed_digest. resolved means OpenSpec holds a
   well-formed accepted-objective record; whether the Owner accepted is established by resolving
   the acceptance reference through its own kind.

## Consequences
- P-03.1: the objective kind is settled and implemented on fixtures; the illustrative
  outcome:O-101 no longer parses.
- The acceptance recorder (sets the item's authority and acceptance, mints the id, writes the
  declaration, commits) has no owning plan leaf: a plan gap routed to the Overseer and Owner.
  Until it exists, Owner acceptances are recorded by hand in this form, each citing the Owner's
  durable statement or the delegating accepted record.
- acceptance references of scheme decision: have no lineage kind; added when a traversal needs it.
- Not yet verified: openspec validate --strict with x-outcomes present, and byte-identity of
  .openspec.yaml across openspec archive, both to be shown by the lineage live test.

## Owner confirmation
Not required before P-03.1 completes. Offered for information: (1) opaque UUIDs rather than
readable sequence numbers (irreversible once referenced); (2) bootstrap practice: an agent records
an Owner acceptance and mints the id on the Owner's durable statement; (3) the recorder plan gap.

## Evidence
Blueprint #authority, #integration-contracts, #experience (sequence steps 10-11), #decisions;
catalog/skills/intent-normalization/references/intent-record.md; evidence/P-01.2 (acceptance
demonstration, fixture standing in for the Owner); OpenSpec docs/cli.md at v1.16.0 (x- keys,
archive path); integrations/planning/README.md (pointer, Git reader); this consultation.
