# D1 plan amendment proposal (OA-28)

> **Applied 2026-11-12.** Decision 0018 was accepted by the Owner (revision 4); items 1 to 4 were decided by the product manager under its point 3, and item 5 was approved by the Owner together with item 3 (`bootstrap-log.md`, Decisions, "Owner acceptance: decision 0018 revision 4, and OA-28 item 5 with item 3"). An independent review added three corrections, applied in the same amendment: S-03.5 is in S-03's child list; S-03.5 and S-03.3 follow P-04.3 in the work order; and S-03.4 and K-02.2, which reach S-03.1 but not S-03.3, carry the model-use gate in their own proofs (the log's entry "Decision 0018 accepted and applied"). The text below is the proposal as it was presented.

> **Prepared by the product manager (2026-11-12). A proposal for the Owner's decision; nothing in the plan is
> changed.** It comes from the Owner's direction of 2026-11-12, item 4 ("Prepare the proposed plan amendments",
> verbatim in [the log](bootstrap-log.md#owner-direction-planning-review-decisions)), and from two
> program-manager analyses of the D1 commitment ([Commitment: D1](bootstrap-log.md#commitment-d1)). The plan is
> integrity-tracked, and decision 0018 is not accepted. Any change therefore goes through the integrity process
> (`docs/development.md`, "Changing integrity-tracked files") on the Owner's approval. Each item can be
> answered separately.

## 1. E-05.1 depends on P-04.3

**Finding.** E-05.1's proof requires "a design-acceptance record (decision 0008)" and live resolution by the
resolver. The design-acceptance decision kind is part of P-04.3's artifact ("the design-acceptance decision
kind"), and `integrations/owner/owner_decision.py` has none today. The resolver also refuses
`DESIGN_NOT_ACCEPTED` unless the live manifest has a `designs` entry (`integrations/dispatch/README.md`, the
refusal table), and only P-04.3's promotion writes the live manifest. E-05.1 cannot honestly pass before P-04.3.
Without the dependency, `plan_commitment.py` reports it ready too early.

**Amendment.** E-05.1 `deps`: `["P-02.2", "E-01.2.1"]` becomes `["P-02.2", "E-01.2.1", "P-04.3"]`. Its notes
gain: "P-04.3 added by the plan amendment of <date>: the design-acceptance decision kind and the live manifest's
design entry come from P-04.3." Nothing else in the leaf changes.

**Effect.** The D1 committed set is unchanged, because P-04.3 is already in it. E-05.1 stops showing as ready
until P-04.3 passes. Once P-04.3 passes, OA-23 and OA-24 are mechanically enforced for E-05.1.

## 2. The first-model-call authorization moves to the first-model-call boundary

**Finding.** S-03.1's proof ends: "...and is authorized or refused by the Owner before any model run." S-03.1
makes no model call, and neither does S-03.2 ("No model call is made"). The first model call through the
model-access plane is S-03.3's live step (6c, `evidence/S-03.3-slice-plan.md` section 5). Where the clause sits
now, it holds S-03.1 open, and through S-03.2's dependency on it, holds S-03.2's guest qualification, which is
D1's first live gate. S-03.1's notes already say A1, A5 and A6 are "re-presented under S-03.3".

**Amendment.**
- S-03.1 `proof`. The first sentence becomes: "The design names the sole holder of the provider credential, the
  endpoint class and its inspection." The second sentence is unchanged. Its words "is not ready for the Owner's
  authorization" still state that the Owner's authorization comes, and S-03.3 now holds it.
- S-03.3 `proof`, and its `agent_contract` completion evidence where that repeats the proof, gain one sentence:
  "Before the first model call through the model-access plane, by this leaf or any other, the Owner has
  authorized the broker design (decision 0015, S-03.1's artifact) for model use, together with the acts the first
  model call needs (the provider key A1, the broker's egress to the one provider origin A5, the first model call
  A6, and the spending cap); if the Owner refuses, no model call is made." The existing sentence "the exact model
  identifiers ... are approved by the Owner before the first paid call" stays (rewritten by item 5 if that item is applied).
- S-03.1 `notes` gain: "Plan amendment of <date>: the clause 'authorized or refused by the Owner before any model
  run' moved, unweakened, to S-03.3, the first-model-call boundary (OA-28)."

**Why this does not weaken the requirement.** The clause covered "any model run". The new sentence covers the
first model call through the model-access plane by any leaf, and the model-access plane is the only route the
harness has to a model. That route is also bound by edge `nm-ext-broker-provider` (`owner_act`), and, after
item 3, by a recorded authorization checked when the broker starts. The Owner's authorization still comes before
any model run. What changes is only which leaf's verdict waits for it.

**Effect.** S-03.1 can pass on its design. S-03.2's guest qualification then waits only on its own acts (OA-12
A2 to A4, the same acts as OA-22 (a), (b), (c) and (e)).

## 3. A new leaf: bind the broker's real-provider start to a recorded authorization

**Finding (program manager, verified by the product manager).** After the Owner enters the provider key (A1),
the provider key and all spend pass through one point: `inference_broker.py serve`. `serve` checks no
authorization (`integrations/inference/inference_broker.py`, the `serve` branch of `main`). The upstream origin
and model allowlist come from `config.yml`, which no Owner decision binds. The broker has no cumulative spending
cap. A wrong origin would send the provider key to that origin. So the D1 boundaries with the most at stake
(spend, external egress and a provider credential) are enforced only by instruction. This is discovered work. It
is not a clause of S-03.3: that leaf's artifact can pass on what the run observed, without the check. It
therefore becomes its own leaf, and S-03.3 depends on it, so the first real-key run cannot come before it.

**Amendment.** A new leaf **S-03.5**:
- **Title:** "Bind the broker's real-provider start to a recorded provider-envelope authorization".
- **Parent:** S-03. **Phase:** 1. **Size:** S.
- **Deps:** `["S-03.1", "P-04.2", "P-04.3"]` (P-04.3 provides the delegated decision kind used below). S-03.3's `deps` gain `"S-03.5"`.
- **Artifact:** "The broker's fail-closed start precondition, the provider-envelope operation kind recorded through
  the authorization recorder, its refusal codes, fixtures and negative suite."
- **Proof:** "Offline, against fixtures: started with any family whose upstream is not loopback, `serve` refuses
  before it opens a listener or reads the provider key, unless the integration store holds a confirmed, unexpired
  authorization recorder receipt (decision 0012) whose operation is the provider envelope and whose target is the
  canonical digest of the live envelope (the provider id, the one upstream origin, the spending limit and the
  expiry). A missing, expired, replayed or mismatched receipt (another origin, limit or digest) is refused with a
  stable code. The model selection is either part of the envelope digest the Owner authorizes, or, once decision 0018
  point 3 applies to S-03.3 (OA-28 item 5), a delegated recorder record (P-04.3's delegated decision kind) naming
  the envelope's receipt and decision 0018; a selection with neither authority, missing, or naming another receipt
  is refused at start with a stable code, and a request for a model outside the selection is refused. If the Owner-authorized spending cap
  is not enforced by the provider on the dedicated key, as stated in OA-12's presentation, the envelope carries a
  cumulative cap that the broker enforces and that fails closed when reached or when usage is unknown. Loopback
  fake upstreams (the S-03.2 qualification) start as today."
- **Notes:** "Added by the plan amendment of <date> (OA-28 item 3), from the program manager's analysis of
  instruction-only consequential boundaries in D1 (evidence/bootstrap-log.md, the classification entry of
  2026-11-12)."

**Effect.** It adds one offline leaf to D1's committed set. It runs alongside S-03.2's guest qualification, so
the critical path does not get longer. It enforces A5, the model pin, the cap where the provider has none, and
OA-22 (g)'s expiry, independently at the moment of the act.

## 4. Deferrals for findings 2 and 3

Add four entries to the plan's `deferred` list, each with a reconsider condition. None weakens a criterion.
1. "Owner-act gates in `plan_commitment.py`'s readiness (finding 2 of 2026-11-12)": reconsider when P-05.1 is
   committed (Backlog.md readiness replaces the tool, and Owner acts become dependencies there), or earlier if an
   execution session starts a gated act on the tool's word or a second commitment is recorded.
2. "Deterministic enforcement of the development agents' path boundary and protected paths (finding 3(a))":
   reconsider at the earlier of a separate operating-system identity for the dispatcher or the development agents,
   or a standing authorization exercised outside the Owner's session.
3. "A server-side guard against hook bypass, and an automatic `verify_seed` run (findings 3(b) and 3(c))":
   reconsider when the CI lane (Q-02.2.x) is committed, or at the first undetected drift of an integrity-tracked
   file.
4. "Authorship of Owner quotes in the log, beyond presence (finding 3(d))": reconsider when an Owner approval is
   consumed by a process the Owner's session does not oversee. Until then, an authorization that must be enforced
   independently goes through the recorder (decision 0018 revision 2, point 7; item 3 above).

5. "A mechanical projection-vs-plan agreement check (a generator or the verifier), with a round-trip test":
   reconsider at the first plan-projection drift found, at a plan amendment applied without the recorded check
   below, or when P-05.1 is committed. Today `tools/verify_seed.py` checks hashes, the graph and the manifest,
   but does not compare prompt, CSV or HTML text with the plan. No generator is tracked.

## 4a. Item 5: S-03.3's model selection, reconciled with decision 0018 point 3

**Applied only after the Owner's recorded acceptance of decision 0018 (revision 4) and the Owner's approval of
this item, and only together with item 3 (S-03.5), on which it depends. If any of these is missing, this item is
withdrawn and S-03.3 stays as written.** It removes an Owner approval from a criterion, so it stays the Owner's
under decision 0018 point 4.8 even after that decision is accepted. It comes from the Owner's
correction of 2026-11-12 ("Reconcile S-03.3 and related acceptance criteria through the established integrity
process so that they explicitly reflect this delegation"). A search of every field of the plan's leaves and its `deferred` list found no other criterion that requires
the Owner's approval of model identifiers. The requirement's source, the Owner's decisions on OA-05 and OA-12 of
2026-11-10, is reconciled by decision 0018's Consequences on acceptance; its verification and no-wildcard
requirements stand.

- S-03.3 `proof`, and the same sentence in its `agent_contract` completion evidence, its prompt, the CSV row and the
  HTML card: "...and the exact model identifiers, including any secondary model, are approved by the Owner before
  the first paid call." becomes "...and the exact model identifiers, including any secondary model, are selected
  inside the model-access envelope the Owner explicitly authorized (the provider, the spending limits and the
  permitted external effects; decision 0018 point 3), verified against current provider information, and
  recorded with their intended uses and expected cost characteristics; that record is presented to the Owner
  before the first paid call, the broker admits only the recorded identifiers (S-03.5), and no model, provider,
  origin or limit outside the envelope is used without the Owner's per-act decision."
- S-03.3 `notes`: "with the model identifiers presented for approval before A6" becomes "with the model
  identifiers selected inside the authorized envelope and presented before A6 (decision 0018 point 3; OA-28
  item 5)".

**Kept unchanged:** the Owner's authorization of the provider, the key (A1), the egress origin (A5), the first model
call (A6) and the spending cap before the first model call (item 2); the provider-key containment search; the
path and model allowlist pinned from observed traffic with no wildcard; "no unapproved destination"; and S-03.5's
independent check at broker start. What moves is only who picks the identifiers inside the authorized
envelope; the identifiers are still verified, recorded, presented and enforced.

On application, execution also updates its working documents, which are not criteria: the S-03.3 slice plan
(row Q8 and section 5, step 6b), slice 5's live driver (step 8) and the S-03.1 authorization request (A5's
"provider and model names"). There the model identifiers are recorded under decision 0018 point 3. **The Owner's
approval of the provider, the egress origin and the family's exact routes is unchanged.**

## 5. Applying it (for execution, on approval)

These rules come from tracked files, so no memory is needed. The program manager computed them, and the product
manager checked the first two at `cee138f`:
- **Plan JSON:** `json.dumps(plan, indent=2, ensure_ascii=False) + "\n"`, with LF line endings.
- **Task prompts:** `task_prompts/<id>.md` is `overseer_prompt + "\n"` (173 of 173).
- **CSV:** written with `csv.writer` defaults (CRLF line endings, minimal quoting, UTF-8 without a BOM) and the
  fixed 20-column header.
  - `ancestor_ids` and `deps` are joined with `;`.
  - Each `acceptance_gates` entry is written as `parent_id: original_proof`, and entries are joined with ` | `.
  - `agent_inputs` and `agent_guardrails` come from `agent_contract`, joined with ` | `.
- **HTML:**
  - `planData` is `json.dumps(plan, separators=(',',':'), ensure_ascii=False)`.
  - Cards follow `work_packages` order, and each card's textarea is `html.escape(overseer_prompt, quote=False)`.
  - A sibling card is the model for the rest of the card.
- **Precedents:**
  - `1f506f6`: a dependency only (item 1).
  - `1ccdf02`, `2f973b0`: a proof together with its prompt (items 2 and 5). The commit message of `1ccdf02` lists every
    part an amendment touches.
  - `13cb939`, `f3a6c92`: new leaves with the "Step n/N" and `Next:` ripple, the counts, and `deferred` entries
    (items 3 and 4). For S-03.5: `slice_count` 4 to 5 across S-03; `decomposition.leaf_count`,
    `added_leaf_count`, `phase_counts["1"]`, `task_prompt_count`, both `task_count` fields and the four "173"
    mentions in the HTML.
- **The check:** run the agreement check at the base, where it must pass, and again after the change. A fresh
  engineer reruns it, and the commit message records the result.

## 6. Not determined

- The exact canonical form of the provider envelope and the name of its operation kind are execution's design
  inside S-03.5.
- Whether the provider offers a hard cap on a dedicated key is to be verified against current provider
  information when OA-12 is prepared.
