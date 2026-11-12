# 0018 - Planning and execution roles, delegated decisions and standing authorizations

Status: Proposed - 2026-11-12. Drafted by the Overseer on the Owner's direction of 2026-11-12 (verbatim in
`evidence/bootstrap-log.md`, Decisions, "Owner direction: the five-role operating model"). **This record grants
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
   | Product manager (planning lead) | Outcomes, priorities and milestone selection; each milestone's acceptance criteria; milestone acceptance against its product outcome; decisions that change scope, criteria or the contract between leaves; plan amendments that preserve every obligation |
   | Program manager (invoked by the product manager only) | The committed set; which dependencies are real; which leaf owns an acceptance clause; deferrals, each with a reconsider condition; the disposal of a blocker execution raised |
   | Engineering manager (execution lead; the existing Overseer) | The order among ready committed leaves; dispatch; leaf verdicts (engineering completion); fix-forward; engineering decisions inside committed scope that change no criterion, no other leaf's contract and no Owner-approved policy; checkpoint pushes and publication within existing permissions |
   | Architect (shared, gated) | Nothing: it advises whichever lead consulted it |
   | Engineer (the existing Builder) | Local mechanics of one bounded task; a fresh engineer independently reviews each consequential change |

   Who accepts a decision follows what it changes: the engineering manager inside committed scope, the product
   manager for scope, criteria or contracts between leaves, the Owner at a reserved boundary. Every decision
   lives in `decisions/` or the log's Decisions; a skill or an agent's memory never holds one.

2. **Discovered work.** A discovered obligation becomes its own leaf or an explicit deferral with a reconsider
   condition. It joins a committed leaf's proof only when that leaf's artifact cannot honestly pass without it.
   A clause is re-homed, never dropped or weakened, and the record says where it went.

3. **Delegated, without a per-act approval, once this record is accepted.** Plan amendments that preserve every
   obligation, through the integrity process, with this record as the standing direction the process requires;
   deferrals with reconsider conditions; decisions inside committed scope; offline engineering; fast-forward
   checkpoint pushes of verified work to this repository. Technical model selection within an Owner-authorized
   provider and spending envelope: exact identifiers are verified against current provider information and
   presented, with intended uses and expected cost characteristics, before the first authorized paid operation;
   ordinary selection details need no approval. Each milestone report lists every delegated decision made.

4. **Reserved to the Owner, per act.**
   1. Entering, rotating or exposing an Owner or provider credential.
   2. Creating or raising a spending cap or budget.
   3. Each recorder decision (acceptance, authorization, input-manifest promotion); its challenge is single-use.
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
   authorization"). It is given by the Owner in the main session and recorded verbatim in the log's Decisions by
   the session that received it; the existing mechanisms consume it as they do today (the network matrix's
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

7. **Sessions.** Planning and execution sessions alternate; one lead writes to the checkout at a time; the
   handoff either way is a commit. An Owner statement an act requires is given in the session that performs it.

8. **Nothing is superseded.** Decisions 0012 and 0016 and `AGENTS.md` are unchanged.

## Consequences

- On acceptance, `security/inventory.json`'s `op-policy-change` records the delegation of point 3, as
  `op-protected-merge` records its own.
- Candidate, after D1: whether P-04.3's rule of a recorded Owner decision per manifest digest and design entry
  should admit acceptance delegated by an accepted decision record (decision 0008 point 2).
- At the D1 transition, acceptance contracts stay protected in the plan while the inventory and dependencies
  move to the Work system.

## Not decided here

The provider, its egress origin, the spending cap and the key; the D1 standing authorization (presented
separately, item by item); the recorder decisions D1 needs.
