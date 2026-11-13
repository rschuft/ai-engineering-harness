# 0018 - Planning and execution roles, delegated decisions and standing authorizations

Status: Proposed, revision 2 - 2026-11-12. Drafted by the Overseer on the Owner's direction of 2026-11-12 (verbatim
in `evidence/bootstrap-log.md`, Decisions, "Owner direction: the five-role operating model"); revised by the product
manager on the Owner's direction of the same day (Decisions, "Owner direction: decisions on the product manager's
first planning assessment", item 1; every change is listed under "Revision 2" below). **This record grants
nothing until the Owner accepts it.** Until then every existing restriction stays in force: per-act Owner
authorization, the integrity process's "only when your user explicitly asks", decision 0012's channel, and every
Owner-only operation in `security/inventory.json`.

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
   | Engineering manager (`engineering-manager`; execution lead, formerly the Overseer) | The order among ready committed leaves; dispatch; leaf verdicts (engineering completion); fix-forward; engineering and architectural decisions inside committed scope that change no criterion, no other leaf's contract and no Owner-approved policy; checkpoint pushes and publication within existing permissions |
   | Architect (`architect`; shared, gated) | Nothing: it advises whichever lead consulted it |
   | Engineer (`engineer`; formerly the Builder) | Local mechanics of one bounded task; a fresh engineer independently reviews each consequential change |

   Who accepts a decision follows what it changes: the engineering manager inside committed scope, the product
   manager for scope, criteria or contracts between leaves, the Owner at a reserved boundary. Architectural
   decisions follow the same rule (point 3.1). Every decision lives in `decisions/` or the log's Decisions; a
   skill or an agent's memory never holds one.

2. **Discovered work.** A discovered obligation becomes its own leaf or an explicit deferral with a reconsider
   condition. It joins a committed leaf's proof only when that leaf's artifact cannot honestly pass without it.
   A clause is re-homed, never dropped or weakened, and the record says where it went.

3. **Delegated, without a per-act approval, once this record is accepted.** Plan amendments that preserve every
   obligation, through the integrity process, with this record as the standing direction the process requires;
   deferrals with reconsider conditions; decisions inside committed scope; offline engineering; fast-forward
   checkpoint pushes of verified work to this repository. Technical model selection within an Owner-authorized
   provider and spending envelope: exact identifiers are verified against current provider information and
   presented, with intended uses and expected cost characteristics, before the first authorized paid operation;
   ordinary selection details need no approval. And:
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
      read-only against its issuer. Delegated use excludes issuing, rotating, revoking, widening, exporting or
      displaying one; every Owner or provider credential (point 4.1); and any new principal, credential class or
      token scope (point 4.7). For the five roles, this is the approval that `AGENTS.md`'s "ask before credential
      access" requires for these uses.

   Each milestone report lists every delegated decision made.

4. **Reserved to the Owner, per act.**
   1. Entering, rotating or exposing an Owner or provider credential.
   2. Creating or raising a spending cap or budget.
   3. Each recorder decision outside point 3's delegation: every authorization of a consequential effect, the
      protected merge (decision 0012) included; every acceptance the Owner reserves; every design acceptance and
      manifest promotion that point 3 does not delegate. Its challenge is single-use.
   4. A destructive or irreversible act on anything the harness did not create as disposable.
   5. Publication to a third party (decision 0017), a release, a tag or a package.
   6. Each elevation or other privileged host change (decision 0004).
   7. Each change that widens an Owner-approved policy record: a new edge between trust domains, an egress
      origin, a credential class or token scope, a principal with standing credentials, a relaxed guest profile
      or protection baseline.
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

8. **Nothing is superseded.** Decisions 0012 and 0016 and `AGENTS.md` are unchanged. Decision 0008 is applied,
   not amended: its point 2 already admits an acceptance delegated by an accepted decision record. Every
   consequential effect outside point 3 still needs the Owner's explicit authorization, per act or standing.

## Consequences

- On acceptance, `security/inventory.json`'s `op-policy-change` records the delegation of point 3, as
  `op-protected-merge` records its own.
- On acceptance, P-04.3's recorded decisions name their deciding authority: the Owner, through the recorder's
  challenge, or this record's point 3 delegation with the commitment or envelope it rests on. Until acceptance,
  only the first exists.
- On acceptance, `CLAUDE.md`'s "Owner statements" rule is reworded to point 7.
- At the D1 transition, acceptance contracts stay protected in the plan while the inventory and dependencies
  move to the Work system.

## Not decided here

The provider, its egress origin, the spending cap and the key; the D1 standing authorization and any manifest
envelope it carries (presented separately, item by item); the recorder decisions D1 needs that point 3 does not
delegate.

## Revision 2

Product manager, 2026-11-12, on the Owner's direction quoted above. Changed: point 1 (the product manager's and the
engineering manager's rows; architectural decisions follow the same rule); point 3 (sub-points 1 to 4: architectural
decisions, design acceptance inside committed scope, manifest promotion inside an explicit envelope, routine use of
harness-managed role credentials); point 4.3 (narrowed to recorder decisions outside point 3, with the protected merge
kept); point 5 (the session that records a standing authorization); point 7 (authorization recorded where given,
never relayed or impersonated); point 8 (decision 0008 applied; consequential effects outside point 3 stay
authorized); Consequences (the "after D1" candidate decided here; P-04.3's deciding authority; `CLAUDE.md`).
Unchanged: every other reserved act of point 4, the items that are never standing, and point 6.
