# 0018 - Planning and execution roles, delegated decisions and standing authorizations

Status: Accepted (Owner) - 2026-11-12, revision 4, in the Owner's words "I accept decision 0018 revision 4 as
presented" (verbatim in `evidence/bootstrap-log.md`, Decisions, "Owner acceptance: decision 0018 revision 4, and
OA-28 item 5 with item 3"); revision 5 (2026-11-13) was applied by the product manager on the Owner's direction of
2026-11-13 (verbatim in the log's Decisions, "Owner direction: reconcile the D1 provider-access requirements before
live execution"; point 4.8), its changes listed under "Revisions". Its history: Proposed - 2026-11-12, revision 4. Drafted by the Overseer on the Owner's direction of 2026-11-12 (verbatim
in `evidence/bootstrap-log.md`, Decisions, "Owner direction: the five-role operating model"); revised by the product
manager on the Owner's direction of the same day (Decisions, "Owner direction: decisions on the product manager's
first planning assessment", item 1), and refined again on the Owner's direction "finalize decision 0018 revision 2"
(Decisions, same date), and corrected on the Owner's direction "decision 0018 revision 3 accepted in principle,
subject to the model-selection correction" (Decisions, same date). Every change is listed under "Revisions" below. **It grants what it states from
its acceptance; the Owner's statement grants no reserved live effect.** Before its acceptance, every existing restriction stayed in force: per-act Owner
authorization, the integrity process's "only when your user explicitly asks", decision 0012's channel, and every
Owner-only operation in `security/inventory.json`. From its acceptance they stay in force except where point 3 delegates the decision; no mechanism is relaxed (point 8).

## Context

- The Owner accepted D1, "the first contained AI-assisted coding task producing a verified result and draft pull
  request", as the next demonstration target, and directed an operating model of five roles: a product manager,
  a program manager, one shared architect, an engineering manager and an engineer. His role is "to provide
  intent, constraints, feedback, and authorization at genuinely reserved boundaries, not to manage routine
  engineering decisions".
- An independent architectural review, reconciled with the Overseer's proposal, found the cause of routine
  decisions becoming Owner approvals: the plan holds both acceptance contracts and the work inventory in one
  integrity-tracked file, and the inventory classes every plan change as Owner-only (`op-policy-change`). It also
  found that the reserved boundaries and class approvals already have machine-checked homes: the inventory's
  Owner-only operations, the network matrix's `owner_act` edges with their `owner_approval` quotes, and decision
  0003's repeatable guest authorization.
- The roles are realized by the Owner's own agent definitions, which are not part of this repository; `CLAUDE.md`
  describes the arrangement. This record decides only who decides what, and how a standing authorization is given.

## Owner direction

The Owner's decisions J1, J2 and J3 of 2026-11-12, verbatim (the whole direction is in `evidence/bootstrap-log.md`,
Decisions, "Owner direction: the five-role operating model"). One bracketed substitution replaces the name of an
unrelated project, which this repository does not name.

> J1: Accept Option A.
> Do not introduce CURRENT_STATE.json or another parallel
> planning state store. Reuse existing plans, evidence,
> OpenSpec, and Backlog. Minimize temporary state.

> J2: Accept Option B.
> Create new, project-neutral Product Manager and Program
> Manager agent definitions. Do not modify the existing
> [unrelated project's] planning agents.
>
> Retain one shared Architect supporting both planning and
> execution. Preserve its existing engineering consultation
> capabilities while incorporating planning consultation
> and selective skill discovery.
>
> Skills should be discovered and loaded when relevant,
> preferably from existing open-source sources. External
> skills require appropriate source verification and must
> never override accepted architectural constraints.
>
> The Architect may retain nonauthoritative technical
> navigation knowledge, but architectural decisions,
> constraints, and commitments must remain in durable
> repository records.

The Owner's direction for revision 2, item 1, verbatim:

> 1. Decision 0018
>
> I support amendments 1 through 4 in principle.
>
> Prepare the exact revised decision record for review,
> including:
>
> - Delegated design acceptance within committed scope.
> - Delegated manifest promotion within an explicit
>   authorization envelope.
> - Architectural decisions accepted by the accountable
>   lead for their scope.
> - Routine use of harness-managed role credentials under
>   existing custody and permission constraints.
> - Human authorization recorded in the session where it
>   was actually given, without impersonation or relay.
>
> Preserve explicit authorization for consequential effects
> outside delegated permissions, including protected merges.
>
> Do not activate expanded authority until the revised
> decision is accepted.

> J3: Delegate technical model selection within an
> authorized provider and spending envelope.
>
> Verify exact model identifiers against current provider
> information. Present the selected models, intended uses,
> and expected cost characteristics before the first
> authorized paid operation. Do not require my approval
> for ordinary model-selection details.

## Decision

1. **Who decides what.**

   | Role | Decides |
   |---|---|
   | Owner | Intent, constraints, and every reserved act (point 4) |
   | Product manager (`product-manager`; planning lead) | Outcomes, priorities and milestone selection; each milestone's acceptance criteria; milestone acceptance against its product outcome; decisions that change scope, criteria or the contract between leaves, architectural ones included; plan amendments that preserve every obligation; design acceptance inside committed scope and manifest promotion inside an Owner-granted envelope (point 3) |
   | Program manager (`program-manager`; invoked by the product manager only) | The committed set; which dependencies are real; which leaf owns an acceptance clause; deferrals, each with a reconsider condition; the disposal of a blocker execution raised |
   | Engineering manager (`engineering-manager`; execution lead, formerly the Overseer) | The order among ready committed leaves; dispatch; leaf verdicts (engineering completion); fix-forward; engineering and architectural decisions inside committed scope that change no criterion, no other leaf's contract and no Owner-approved policy; technical model selection inside an authorized model-access envelope (point 3); checkpoint pushes and publication within existing permissions |
   | Architect (`architect`; shared, gated) | Nothing: it advises whichever lead consulted it |
   | Engineer (`engineer`; formerly the Builder) | Local mechanics of one bounded task; a fresh engineer independently reviews each consequential change |

   Who accepts a decision follows what it changes: the engineering manager inside committed scope, the product
   manager for scope, criteria or contracts between leaves, the Owner at a reserved boundary. Architectural
   decisions follow the same rule (point 3.1). Every decision lives in `decisions/` or the log's Decisions; a
   skill or an agent's memory never holds one.

2. **Discovered work.** A discovered obligation becomes its own leaf or an explicit deferral with a reconsider
   condition. It joins a committed leaf's proof only when that leaf's artifact cannot honestly pass without it.
   A clause is re-homed, never dropped or weakened, and the record says where it went.

3. **Delegated, without a per-act approval, once this record is accepted.** Milestone selection, priorities and
   commitments; decisions inside committed scope; offline engineering; deferrals with reconsider conditions. Plan
   amendments that preserve every obligation, through the integrity process, with this record as the standing
   direction the process requires: adding a leaf, a dependency or a criterion; refining, splitting or re-homing a
   criterion without lowering what it proves; correcting one that cannot be met as written the same way; each
   with the reasoning recorded and the program manager's challenge. Routine publication within existing
   permissions: fast-forward checkpoint pushes of verified work to this repository's existing origin and branch,
   never a force push, a new remote, a tag or a release. Technical model selection inside a model-access
   envelope the Owner has explicitly authorized: the provider and the permitted external effects (the egress origin
   and what may be sent to it). The envelope carries no spending limit: spending is bounded by the provider
   account's own limits (revision 5). Inside it, the engineering manager, for the leaf that
   makes the paid call, selects the exact model identifiers, any secondary model included, verifies them against
   current provider information, and records them with their intended uses and expected cost characteristics;
   each such record is presented to the Owner before the first paid operation under it, and the broker admits only
   the recorded identifiers. Where a leaf's acceptance criteria require the Owner's approval of model identifiers,
   this applies to that leaf only once those criteria are amended through the integrity process to state it (for
   S-03.3, OA-28 item 5); until then that approval is required, and a presentation never stands in for it. A
   provider, origin or model outside the envelope is an Owner decision per act. And:
   1. **Architectural decisions.** A decision record is accepted by the lead accountable for its scope under
      point 1, after the architect's consultation where a gate earned one. Accepting it authorizes none of the
      reserved acts (point 4) it names: each is presented separately, and the design does not wait for them. A
      decision that contradicts or weakens an Owner-accepted decision or constraint stays reserved (point 4.8).
   2. **Design acceptance inside committed scope.** The product manager accepts the design of an OpenSpec change
      whose intent the Owner gave and which lies inside a recorded commitment's scope (for D1, the change the
      Owner names under E-05.5). It is recorded through the authorization recorder as an acceptance delegated by
      this record (decision 0008 point 2: "delegated by an accepted decision record"), naming this record, the
      commitment and the exact revision (decision 0008 point 5); it is never recorded as an Owner decision. A
      change to the harness's own governance, a policy record or an accepted decision is not inside committed
      scope for this purpose.
   3. **Manifest promotion inside an explicit envelope.** The product manager promotes a dispatch-input manifest
      (P-04.3) when every entry lies inside an envelope the Owner granted as a standing authorization (point 5):
      the repositories, designs, profiles, bindings and agent assignments it admits, the leaf or milestone it
      serves, its conditions, its stop conditions and its expiry. The promotion is recorded through P-04.3's
      mechanism as a decision delegated by this record, bound to the manifest digest and naming the envelope.
      The engineering manager, which dispatches with the manifest, never promotes one. An entry outside the
      envelope is an Owner decision per act.
   4. **Routine use of harness-managed role credentials.** A component uses a credential the harness issued and
      holds (a bot or service credential under decisions 0007, 0011 and 0013, such as the Gitea bot role tokens)
      for its decided purpose, through its decided custody path, inside committed scope and existing
      permissions: it reads the credential from its credential-provider entry for that use and verifies it
      read-only against its issuer. Revoking one the harness suspects exposed is also delegated, because it only
      narrows access. Delegated use excludes issuing, rotating, widening, exporting or displaying one; every Owner or provider credential (point 4.1); and any new principal, credential class or
      token scope (point 4.7). For the five roles, this is the approval that `AGENTS.md`'s "ask before credential
      access" requires for these uses.

   Each milestone report lists every delegated decision made.

4. **Reserved to the Owner, per act.**
   1. Entering, rotating or exposing an Owner or provider credential.
   2. Creating or raising a spending cap or budget. None is required (revision 5): the harness enforces no
      spending limit.
   3. Each recorder decision outside point 3's delegation: every authorization of a consequential effect, the
      protected merge (decision 0012) included; the acceptance of an objective as the Owner's intent (decision
      0008), for which the Owner's own recorded statement suffices and no separate approval is asked; every design
      acceptance and manifest promotion that point 3 does not delegate. Its challenge is single-use.
   4. A destructive or irreversible act on anything the harness did not create as disposable.
   5. Publication to a third party (decision 0017), a release, a tag or a package.
   6. Each elevation or other privileged host change (decision 0004).
   7. Each change that widens what an Owner-approved policy actually permits: a new allowed edge between trust
      domains, an egress origin, a credential class or token scope, a principal with standing credentials, a
      relaxed guest profile or protection baseline. Recording a planned edge, a narrowing or a correction is not
      a widening.
   8. Contradicting or weakening an Owner constraint, an Owner-accepted decision or an acceptance criterion, and
      changing this delegation.

5. **Standing authorizations.** The Owner may approve a class of acts once instead of each instance. A standing
   authorization names the acts (operations or matrix edges), the leaf or milestone they serve, their
   conditions, their stop conditions and their expiry, each item separately answerable (decision 0016, "Owner
   authorization"). It is given by the Owner in whichever session the Owner is speaking in, and recorded
   verbatim in the log's Decisions by that session (point 7); the existing mechanisms consume it as they do today (the network matrix's
   `owner_approval` quote for an `owner_act` edge; a decision-0003-style repeatable authorization; the
   inventory's operations). No agent writes, broadens or extends one, and none is ever relayed between sessions.
   Items 1 to 3 and 8 of point 4 are never standing.

6. **Durable state, no new store.** A commitment is a dated entry in the log's Decisions naming a milestone's
   terminal leaf, whose proof is the milestone's acceptance criteria. The committed set is computed from the
   plan's dependencies and the log's Leaves table by `tools/plan_commitment.py`
   (`task plan:commitment -- <leaf>`), never kept as a second copy. Leaf status stays in the Leaves
   table, blockers on the blocked leaf's row, reserved requests in the Owner-actions queue. At the D1 transition
   the repository's own Work moves to the adopted Work system (Backlog.md and OpenSpec), by its own leaf,
   P-05.1.

7. **Sessions and Owner authorization.** Planning and execution sessions alternate; one lead writes to the
   checkout at a time; the handoff either way is a commit. An Owner authorization is recorded, verbatim and
   dated, by the session in which the Owner actually gave it. No agent writes, paraphrases, synthesizes or
   impersonates one, and none is relayed: another session acts on it only by reading that durable record, never
   on a session's report that it was given. Where an act's mechanism binds the authorization itself (the
   recorder's single-use challenge, decision 0012), the act consumes only that binding. A log quote is checked
   for presence, not authorship; that limit is disclosed, and an authorization that must be independently
   enforced goes through the recorder.

8. **Nothing else is superseded, and no enforcement is relaxed.** Decisions 0012 and 0016 are unchanged. The one
   earlier Owner requirement this record changes on acceptance is named under Consequences. Decision
   0008 is applied, not amended: its point 2 already admits an acceptance delegated by an accepted decision
   record. `AGENTS.md` is unchanged for every contributor; for the five roles, a delegation of point 3 is the
   user's approval that `AGENTS.md` requires for that act (a push, a credential use, a change to an
   integrity-tracked file), and nothing more. Delegation changes who decides, never a mechanism: the recorder's
   challenge, the guest boundary, the network matrix's `owner_act` edges, the provider account's own limits,
   Gitea's protection and the publication gate stay in force, and an act a mechanism refuses is not
   authorized by this record. Every consequential effect outside point 3 still needs the Owner's explicit
   authorization, per act or standing.

## Consequences

- On acceptance, `security/inventory.json`'s `op-policy-change` and `op-git-push-public` record the delegations
  of point 3, as `op-protected-merge` records its own.
- On acceptance, P-04.3's recorded decisions name their deciding authority: the Owner, through the recorder's
  challenge, or this record's point 3 delegation with the commitment or envelope it rests on. Until acceptance,
  only the first exists.
- On acceptance, `CLAUDE.md`'s "Owner statements" rule is reworded to point 7.
- On acceptance, and not before, S-03.3's acceptance criteria are reconciled with point 3's model selection
  through the integrity process (OA-28 item 5), on the Owner's approval of that item, which stays the Owner's under
  point 4.8. If this record is not accepted, item 5 is withdrawn and S-03.3 stays as written.
- On acceptance, for identifiers selected inside an authorized envelope, the approval in the Owner's decisions on
  OA-05 and OA-12 of 2026-11-10 ("Exact model identifiers, including any secondary model used by Claude Code,
  remain to be verified and presented for approval before the first paid inference call") is replaced by point
  3's record and presentation, once OA-28 item 5 applies. That decision's verification requirement and its "Do not
  use wildcard model allowances or assume a model name from memory" stand.
- At the D1 transition, acceptance contracts stay protected in the plan while the inventory and dependencies
  move to the Work system.

## Not decided here

The provider, its egress origin and the key; the D1 standing authorization and any manifest
envelope it carries (presented separately, item by item); the recorder decisions D1 needs that point 3 does not
delegate.

## Revisions

Revision 2:

Product manager, 2026-11-12, on the Owner's direction quoted above. Changed: point 1 (the product manager's and the
engineering manager's rows; architectural decisions follow the same rule); point 3 (sub-points 1 to 4: architectural
decisions, design acceptance inside committed scope, manifest promotion inside an explicit envelope, routine use of
harness-managed role credentials); point 4.3 (narrowed to recorder decisions outside point 3, with the protected merge
kept); point 5 (the session that records a standing authorization); point 7 (authorization recorded where given,
never relayed or impersonated); point 8 (decision 0008 applied; consequential effects outside point 3 stay
authorized); Consequences (the "after D1" candidate decided here; P-04.3's deciding authority; `CLAUDE.md`).
Unchanged: every other reserved act of point 4, the items that are never standing, and point 6.

Revision 3 (product manager, 2026-11-12, on the Owner's direction to finalize revision 2, evaluated against the
Owner's operating model): point 3 names milestone selection, priorities and commitments, ordinary criterion
refinement, and routine publication explicitly, and stated that J3's presentation satisfies S-03.3's model
approval inside the envelope (withdrawn by revision 4); point 3.4 delegates revoking a suspected-exposed harness credential; point 4.3
replaces "every acceptance the Owner reserves" with the acceptance of an objective as the Owner's intent, which
the Owner's own statement satisfies; point 4.7 reserves widening what a policy permits, not record-keeping;
point 8 makes a point-3 delegation the approval `AGENTS.md` requires for the five roles and states that no
enforcement mechanism is relaxed; Consequences add `op-git-push-public`. Unchanged: every other reserved act, the
items that are never standing, and points 2, 5, 6 and 7.

Revision 4 (product manager, 2026-11-12, on the Owner's correction quoted in the log): point 3's model-selection
sentence no longer treats a presentation as satisfying an approval a criterion requires. Model selection is
delegated inside an envelope the Owner explicitly authorizes (provider, spending limits, permitted external
effects), with verified identifiers, intended uses and expected costs recorded and presented before the first paid
operation and the broker admitting only the recorded identifiers; it applies to S-03.3 only once its criteria are
amended through the integrity process (OA-28 item 5). Consequences add that reconciliation and name the earlier Owner requirement it replaces (point 8's heading
says so). The engineering manager is named as the one who selects (point 1's row). Nothing else changed beyond the
Status line and the annotation of revision 3.

Revision 5 (product manager, 2026-11-13, applying the Owner's direction of 2026-11-13, "Owner direction: reconcile
the D1 provider-access requirements before live execution", verbatim in the log's Decisions, which retires
"Harness-enforced spending limits", "Per-attempt inference budgets", "Budget exhaustion as an authorization
failure" and "Requirements for the Owner to choose spending caps or enforcement mechanisms", and reads
"Reconcile decisions 0015, 0018 and 0021" and "avoid redundant confirmations of decisions already covered by
accepted intent"). This revision is the product manager's application of those words; it was not presented for a
separate acceptance.
Changed: point 3, where the model-access envelope is the provider and the permitted external effects, with no
spending limit, and "limit" is dropped from what lies outside it; point 4.2 notes that no cap or budget is
required; point 8 names the provider account's own limits in place of "the provider-side and broker spending
limits"; "Not decided here" drops the spending cap. Unchanged: every other delegation and reserved act, the items
that are never standing, credential custody (point 4.1), the recorder decisions (point 4.3), the widening of policy
(point 4.7), and points 1, 2, 5, 6 and 7. The Status line keeps its form `Status: Accepted (Owner) -`, which the
recorders check.

## Current facts

- 2026-11-12: Accepted by the Owner (revision 4). Consequences applied the same day: `security/inventory.json`
  `op-policy-change` and `op-git-push-public` record the point-3 delegations; `CLAUDE.md`'s Owner-statements rule
  points to point 7; the plan amendment of 2026-11-12 (OA-28 items 1 to 5) reconciles S-03.3 with point 3, adds
  S-03.5 and makes E-05.1 depend on P-04.3. The Owner's acceptance authorizes no provider credential, spending,
  external egress, first model call or other reserved live effect.
- 2026-11-13: Revision 5 applied (above). Decisions 0015 (amendment 2) and 0021 (amendment 1) and the plan are
  reconciled with it the same day; it authorizes no provider credential, egress or model call (OA-12 stays
  unanswered).
