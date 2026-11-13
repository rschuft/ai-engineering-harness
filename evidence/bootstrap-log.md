# Bootstrap progress log

Minimal, traceable record of Overseer verdicts while the adopted Work system
(Backlog.md, per the blueprint) does not yet exist. It is not a second task
system: task definitions stay in the canonical plan JSON, and this log will be
migrated into the adopted Work system when that is established. Every entry
names the exact revision and the evidence the verdict rests on. Status values:
PASS, FAIL, UNKNOWN, BLOCKED. Parent (Medium/Large) contracts are evaluated
separately and never inferred from a child passing.

## Owner actions

The durable queue of everything that needs the Owner's own authority: a decision, an approval
or an external act. Owner directions of 2026-11-09 (verbatim under Decisions). It is part of
this log, not a separate task system, and moves into the adopted Work system with the log.

Rules:
- The Overseer adds an item when an obligation arises, and reconciles the queue at every
  checkpoint and handoff.
- Every Overseer report carries a "Needs Owner" section, in the four categories below.
- Silence is never approval.
- At a gate that needs an item, only that operation stops, and the exact decision is presented
  with its implications. Unrelated ready work continues.
- An item closes only with its resolution and linked evidence.
- A completion receipt (a URL, a confirmation) is the resolution of its item, never a
  separate item.

Categories:
1. **Needs Owner now**: an act the Owner can complete now, with its prepared material.
2. **Awaiting preparation**: the draft or prerequisite is not ready; not yet an Owner act.
3. **Future authorization**: needed at a named gate, with what will be presented there.
4. **Optional housekeeping**: non-blocking.

Each row gives its identity, provenance, the act, why it needs Owner authority, the evidence,
what it blocks, and its status.

### 1. Needs Owner now

| Id | Origin | Act needed | Why Owner authority | Evidence and prepared material | Blocks | Status |
|---|---|---|---|---|---|---|
| OA-29 | The Owner's directions of 2026-11-12 on distribution and knowledge promotion | **DS1, each item separately answerable:** (a) accept, amend or decline Proposed [decision 0019](../decisions/0019-development-agent-environment-distribution-and-knowledge-promotion.md); (b) the plan amendment adding group F-11 ([proposal](DS1-plan-amendment-proposal.md)): since decision 0018's acceptance, the product manager's once (a) is accepted; (c) the catalog's URL, visibility and a licence that permits fetching it at clone time; (d) the catalog publishes the projection and its manifest, and where (an act in the catalog's own repository); (e) the role set's closure at a named catalog commit; (f) memory scope `local` for distribution (recommended); (g) Codex: bootstrap only (recommended) or role parity; (h) whether the default instruction installs the roles or offers them; (i) the `AGENTS.md` Setup section, with two promoted rules, at F-11.3; (j) at F-11.2 and F-11.4: egress to fetch the catalog, a clean-profile harness login, and model calls for the verification. | Governance, another repository of the Owner's, a licence, a credential, egress and spend | The decision; the proposal; the architect's design and memory audit, and the program manager's placement (Decisions, the planning entry of 2026-11-12) | Nothing on D1's path. (a) and (b) unblock F-11.1, which is offline; (c) to (e) unblock F-11.2; (g) to (i) unblock F-11.3; (j) unblocks F-11.4. | Pending; nothing installed from a clone |
| OA-19 | S-03.2 slice 3 finding 3(b); Architect consultation (gates A, G) | **Approve, amend or decline the plan amendment** in [the proposal](S-03.2-plan-amendment-proposal-child-clause.md) section 3: S-03.2's proof can no longer meet "A child conversation launched by an agent driven by the fake upstream ... No model call is made" (the 2026-11-10 re-scope removed the only create shape that lets an upstream drive an agent, and the template has no tools); the proposal shows the child's containment by a probe-created child through the same route and key, and moves the agent's own launch to S-03.3 (the ACP provider) and to the first leaf that runs an openhands-kind agent (made concrete in S-03.4); S-03.3 gains the real-key fingerprint search and a note on its create fixture | A change to the integrity-tracked plan and to acceptance criteria (Owner-reserved; never weakened silently) | The proposal (exact wording, reasoning, what was not determined); slice 3 evidence section 3.2 | S-03.2's guest qualification cannot pass as written; the offline slices continue | **Done 2026-11-11** (plan `2f973b0`, inventory `cebd3ab`, decision 0015 note with this entry): the corrected wording applied exactly; see Decisions, "OA-19 and M-5 applied" |
| OA-18 | M-4 finding | **Approve or decline M-5**: the same blueprint reconciliation as M-4, for the passages M-4's named sections did not cover (listed in the M-5 row below), including "What the Owner sees ... Recommended: merge to activate", which asks the Owner to merge in Gitea. | A change to the integrity-tracked blueprint (Owner-reserved, as M-1 to M-4 were). | The M-5 row; the M-4 commit `31a7f8b` as the pattern. | Nothing blocks on it; the blueprint is inconsistent with decision 0012 until then. | **Done 2026-11-11** (`fee915e`): M-5 applied through the integrity process; see the M-5 row |
| OA-17 | F-10.5; the OA-05 run's Linux finding | **Approve or decline one run** of [revision 4](F-10.5-oa05-guest-run-plan-rev4.md): the same eight-file suite at `3cf45cd953642e90c4bbf6be63cf3d5483e9a0bc` (the ceiling fix: the test file and one docstring changed), archive `ac9693599f8ed97272e23dd9c1f4f7b94d6bf23849a872bbbead7ddd740e6c8d`, manifest `49fcb35f...7400`, script `2d67a7cb...87ba` (revision 3 with five binding constants changed; `REPO` stays the clone), runner and wheels unchanged; one disposable `f105-linux` guest with revision 2 and 3's isolation, limits, transfer and teardown. PASS = digest `d5aa24a7...6d937` (85 rows). One run, no retry. | Repository content in a guest (the standing guest authorization excludes it). | [Revision 4](F-10.5-oa05-guest-run-plan-rev4.md), sections 0-9; [the revision 3 run](F-10.5-oa05-linux-run.md). | F-10.5 and the F-10 group. Unrelated work continues. | **Done 2026-11-11, once** ([run evidence](F-10.5-oa17-linux-run-rev4.md), [report](F-10.5-linux-report-rev4.json)). Inputs verified before execution (script, clone head and clean tree by the Overseer; payload, runner and wheels by the script). **PASS for its scope:** 84 ok, 1 module skipped as expected (no git), digest `d5aa24a7...6d937` equal to the Windows reference; the two `Ceilings` rows that failed in revision 3 pass. Teardown verified by the script and independently by the Overseer (no launch record, 0 QEMU processes, 0 QEMU listeners). A partial Linux result, not cross-platform qualification: Linux git-oracle parity, the native Linux wheel, `write_commit` on Linux, macOS and repeatability stay unverified |

### 2. Awaiting preparation

| Id | Origin | Act needed | Why Owner authority | Evidence and prepared material | Blocks | Status |
|---|---|---|---|---|---|---|
| OA-12 | S-03.1 (plan leaf; the Owner's 2026-11-07 decision "Model access: design it now") | **Authorize or refuse, per act**, the model-access design of Proposed decision 0015: the provider and model names, a dedicated provider-capped key and budgets (choices; since 2026-11-12, with decision 0018 accepted and OA-28 item 5 applied, the engineering manager selects the model names inside the authorized envelope, verified, recorded with intended uses and expected costs, and presented before the first paid call, while the provider, key, budgets and egress stay the Owner's; the provider-envelope authorization that S-03.5 checks at broker start is recorded through the recorder as part of A5 and A6); A1 the provider key in one Credential Manager entry, typed by the Owner into a harness command; A2 a host broker as the Owner's account with two `127.0.0.1` listeners; A3 one guest-to-host path, an SSH remote port forward in the existing management channel to `172.17.0.1:<port>` in the guest; A4 the guest composition relaxed to exactly that address and port (sshd forwarding, one container-guard allow; optionally Moby `dns`); A5 the broker's egress to exactly one provider origin; A6 one first model call, fixed prompt, no repository content, one disposable guest. | A credential, a host service and ports, the first guest-to-host path, host egress and model usage billed to the Owner: product, security and spending authority; beyond the standing guest authorization (no LLM or model credential, no guestfwd). | [Authorization request](S-03.1-owner-authorization-request.md) (complete on its own); [decision 0015](../decisions/0015-inference-broker-placement-provider-credential-custody-and-guest-inference-endpoint.md) (Proposed; Architect design reviewed by the Overseer). Nothing performed. | **Now:** S-03.2's guest qualification waits on A2 to A4 (OA-22 (a), (b), (c), (e)); S-03.3's proof holds the Owner's authorization before the first model call (moved from S-03.1 by OA-28 item 2), as do S-03.4's and K-02.2's for their own model calls. On D1's path: S-03.3 directly (its key, egress origin and first model call); E-05.2 and E-05.3 through S-03.3; E-05.5 directly (its model calls under the cap) and through S-03.3. E-05.1 and E-05.4 do not depend on it. Unrelated work continues. | **Package prepared 2026-11-13, awaiting the Owner:** [package](OA-12-OA-22-provider-access-package.md), under the [Owner direction](#owner-direction-provider-access-2026-11-13); [record](#oa-12-package-2026-11-13). **Architecture accepted 2026-11-10; execution items pending preparation** (Owner, verbatim under Decisions). **Accepted (not to be re-presented unless new evidence contradicts it):** the ACP coding path through OpenHands `ACPAgent` as the default (OpenHands-native optional); brokered, dedicated, spend-capped API keys in principle; Claude Code first to qualify, Codex kept as a supported alternative; decision 0015 amendment 1 (applied); the plan reconciliation (to apply by the integrity process); S-03.2 offline work with synthetic credentials and fake upstreams. **Pending, each presented separately when prepared:** the exact model identifiers, including Claude Code's secondary model (verified, never from memory; no wildcards; since 2026-11-12 selected by the engineering manager inside the authorized envelope and presented, not approved, under decision 0018 point 3); the key, its storage and spend caps and budgets; the broker's host listeners; the guest forward and hardening change; external egress; the first model call; the image adapter result is in: both adapters and the Node runtime are present in the exact pinned image at their registry pins ([S-03.3 check](S-03.3-image-adapter-check.md), 2026-11-10; no derived image needed; the bundled CLIs not yet opened). L1 and L2 stay held, re-homed to an optional native-inference capability 2026-11-12, the Owner's J3 (Decisions, "Owner direction: the five-role operating model") directs delegating technical model selection within an authorized provider and spending envelope; it took effect on 2026-11-12 with decision 0018's acceptance and OA-28 item 5 ([Owner acceptance](#owner-acceptance-0018-rev4)). Still the Owner's: the provider and its single egress origin, the spending cap, and creating and entering the key. **Presentation requirements (planning, 2026-11-13; [planning pass](#planning-pass-2026-11-13)):** the envelope's spending limit with an `expires_at` date (OA-22 (g)'s "expires at D1's acceptance" is not a date); who enforces the cap (the provider, or the Owner choosing `enforced_by: broker`, which closes on any unclean stop); whether a complete non-2xx answer bills zero (decision 0021 R6); that "what may be sent to it" stays the Owner's unenforced condition; that the envelope does not bind which key; the engineering manager's model record (presented, not approved); that the real-key search reads the key in memory under A1 only (D-5); and that the envelope authorization is recorded on the authorization repository of decision 0022 (OA-30 first), never on the fixture. |

### 3. Future authorization

| Id | Origin | Act needed at the gate | Why Owner authority | What will be presented | Gate | Status |
|---|---|---|---|---|---|---|
| OA-06 | Decisions [0004](../decisions/0004-privileged-effect-store-custody-and-restore-semantics.md) and [0010](../decisions/0010-effects-store-placement-and-governance-threat-model.md) (act A4); the F-05.1 limits | The privileged host act A4: create the executor principal and the effects-store custody root. | A privileged host act: account, elevation and custody. | The precise privileged operation and its effects. **Not authorized** (Owner, 2026-11-09). | G-04.2.1 (and the effects CLI success path). | Pending (future); reserved for its gate (Owner, 2026-11-09 and 2026-11-10) |
| OA-07 | [Decision 0013](../decisions/0013-owner-ui-session-access-and-management-key-custody.md); the S-01.4 and F-04.2 rows | An approval for each distinct host-to-guest connection (the Owner UI, the dispatch path). | Decision 0013: no host-to-guest path opens without a recorded Owner approval. | Each connection, separately, at the leaf that first needs it. **Not authorized** (Owner, 2026-11-09). | U-01.2 and E-01.3.x, as each is reached. For D1, the dispatch-path connection (edge `nm-dispatcher-agent-server`) is presented as OA-22 item (d); see the D1 commitment. | Pending (future); reserved for its gate (Owner, 2026-11-09 and 2026-11-10) |
| OA-13 | [Decision 0016](../decisions/0016-hostile-ci-threat-model-validation-and-promotion-lanes-and-runner-reach.md), section 10 | The CI lane's acts and confirmations, each separately: A-1 the `ci-control` forward; A-2 repository content in a CI guest; A-3 an untrusted workload there; A-4 the filtering proxy's host listener; C-1 enabling Gitea Actions for the governance repository only, with the token ceilings; C-2 the governance repository, `aieh-bot-ci`, the registration-token procedure and the live check; C-3 the CI guest variant, its ceilings and lifetime | Guest network, repository content and untrusted workloads beyond the standing guest authorization; a host listener; a configuration change of Gitea, the trusted computing base | Each act with what stays unauthorized, in the 0003 procedure. **Owner direction (2026-11-10):** no live CI runner is qualified while its registration token remains reusable and an effective reset or revocation is unverified; if the automated reset is unavailable, that is a blocking condition at the live provisioning gate, presented with the required alternative or Owner act. Accepting decision 0016 authorizes none of its acts | Q-02.2.1 (C-3, A-4), Q-02.2.2 (A-1, A-2, A-3, C-2's registration), Q-02.3.1 (C-1, C-2) | Pending (future); **not authorized** (Owner, 2026-11-10) |
| OA-22 | D1 commitment (2026-11-12); decision 0018 point 5 | **The D1 standing authorization, each item separately answerable:** (a) the inference broker's loopback listeners; (b) edge `nm-guest-inference`; (c) edge `nm-job-inference`; (d) edge `nm-dispatcher-agent-server` (if granted, OA-07's dispatch-path approval under decision 0013); (e) S-03.2's guest hardening change; (f) agent attempts through the dispatcher on the D1 demo repository's content only; (g) model calls under the cap set in OA-12; (h) provisioning the demo repository and its protections on the host Gitea inside declared policy; (i) the demo repository's content in a disposable guest for E-05.1's offline test run in the pinned image (the standing guest authorization excludes repository content; item (f) covers only agent attempts) (added 2026-11-12, planning). (j) the D1 manifest envelope (decision 0018 point 3.3): the demo repository and the design of the change named under OA-25, the qualified execution profile and binding, and the D1 agent assignment with no Skills, and E-01.3.2's entries for its disposable work attempt where they use the demo repository, inside which the product manager promotes D1's manifests; an entry outside it is an Owner decision per act (added 2026-11-12, planning). Items (a), (b), (c) and (e) are the same acts as OA-12's A2, A3 and A4: they are presented once, together. Excludes host shares, any other egress, any Owner credential in a guest, and every other repository. Stops on any failed containment case, unexpected egress, credential finding, or the cap reached. Expires at D1's acceptance. | Each widens an Owner-approved policy record or spends; (j) is decision 0018's point-3.3 envelope, which the Owner grants | `policy/network-matrix.json` (the three edges' `owner_act`); decision 0003 (the guest authorization this extends); decision 0015 | S-03.2's guest qualification, S-03.3, E-01.3.3's probe (item (d): it is the first live traversal of edge `nm-dispatcher-agent-server`, through the existing forward, with no new host port), E-01.3.2, E-05.1 (items (h) and (i)), E-05.4 (items (f) and, for the demo repository, (h)) and D1 (E-05.5) (corrected 2026-11-12, planning). | Items (a), (b), (c), (e) presented with OA-12 on 2026-11-13 ([package](OA-12-OA-22-provider-access-package.md)). Prepared 2026-11-12. Items (a), (b), (c) and (e) with OA-12's A2 to A4 are the first gate on D1's critical path and are presented when OA-12 is prepared, not after the other offline leaves; the rest at their leaves (planning, 2026-11-12). Nothing is granted until the Owner answers. Items (f) and (g), when presented, state that they include the dispatcher's issuance and revocation of each attempt's inference token through the broker (E-05.6; planning, 2026-11-13). |
| OA-25 | D1 commitment; E-05.5's proof ("The Owner names one small change in a demo repository on the host Gitea") | **Name the D1 change and its demo repository.** Intent, not an authorization: one small change, testable offline in the pinned image. | The proof makes the naming the Owner's. | Nothing to prepare; it can be given at any time before E-05.1 starts. Planning refines it into the OpenSpec change. | E-05.1, then E-05.5 | Pending (future); added 2026-11-12, planning |

### 4. Optional housekeeping

None pending.

### Resolved

| Id | Origin | Act | Resolution and evidence |
|---|---|---|---|
| OA-30 | [Decision 0022](../decisions/0022-authorization-repository-the-one-ledger-provisioned-for-d1.md); E-05.7 ([planning pass](#planning-pass-2026-11-13)) | **The authorization repository, each part separately answerable:** (a) one run as the site administrator (the harness-held password read into memory, no token minted): create the private organization and repository (auto-initialized, `main`), apply its settings, create its protection rules, set its collaborators, read back; (b) the widening this grants, stated in words: the protection auditor `aieh-bot-protection-audit` becomes repository administrator of this repository as well (token and scope unchanged), the four bots gain the fixture's permissions there, and `aieh-owner` gains merge on its protected branches; (c) the read-only `protection_check.py verify` as the auditor, its baseline recorded (delegated under decision 0018 point 3.4, presented with the act so the record is whole); optionally (d) the Owner confirms, or has enabled, Gitea's `[audit]` setting, on which D1 does not rely (decision 0022, Consequences). Stays unauthorized: any merge or Owner statement there; any negative control or drift injection there; any change to the fixture, an account, a token, a scope or `app.ini` (except (d) if granted). Stops: a non-2xx call; a read-back difference; `verify` not `verified`; the administrator holding a token afterwards; the fixture no longer verifying. | Done 2026-11-13 on the Owner's authorization (verbatim in Decisions, [OA-30](#owner-authorization-oa-30-2026-11-13)): parts (a)-(c) performed once; ledger verified, baseline `sha256:041510d5…837f`; fixture unchanged; (d) not authorized. Row moved to Resolved, 2026-11-13 ([E-05.7 verdict](#e-05-7-verdict-2026-11-13)). |
| OA-14 | P-04.2 (its live proof) | **Preparation approved, merge not authorized** (Owner, 2026-11-10). The exercise is reworked so it never manufactures Owner authority: (1) prepare the fixture proposals and manifest; (2) issue the recorder's actual one-time challenge; (3) present the exact operation, head, manifest digest, effects and challenge to the Owner; (4) the Owner's subsequent explicit authorization; (5) only then the protected merge. Negative controls (bot merges, a stale head) within the fixture scope; any unexpected successful bot merge is a security failure. Custody and teardown checks kept. Only the five named Credential Manager entries. | **Done 2026-11-12** on the Owner's explicit authorization of both operations (verbatim in Decisions, "Owner authorization: OA-14 operations A and B"): record phase run once; B `live-20261112t060110z-b` refused 409 `HEAD_STALE` (receipt failed, nothing merged, main unmoved); A `live-20261112t060110z-a` merged once as `75e89b28143464949c24bd46433a5d9f2197b0d0` (parents main `f18da179` and the approved head `111d20c3`), receipt confirmed, protection `verified` with the baseline before and after. The P-04.2 verdict and decision 0012 are judged separately by the Overseer. Earlier: regenerated challenges and Act E prepare 2026-11-12; held 2026-11-10 until OA-16 Acts A to D Row moved to Resolved by planning, 2026-11-13. |
| OA-16 | P-04.2; OA-15a | **Decide the mechanism** of the fail-closed protection check before each recorder merge ([recommendation](P-04.2-protection-check-recommendation.md), gate G, SOURCE-verified at Gitea 28.3.0). Recommended (option 2): a dedicated restricted Gitea Bot `aieh-bot-protection-audit` with **repository-administrator** collaboration on the admitted repository only and one token of scope exactly `read:repository` (Gitea refuses every write by scope, in either presentation; no password; no sudo), held by a small adapter the recorder calls in-process as the last read before the merge and again after it; it compares all 34 settings of every rule (including the bypass allowlist, finding F-A), the exact rule set and the repository roster and merge styles, and refuses on any drift or anything it cannot verify. **The question for the Owner:** whether a read-only-scoped token of a repository-administrator Bot, held by the recorder's adapter, is acceptable under "no administrator credentials in the recorder". Alternative without any Gitea credential: option 1, a read-only read of the rule from Gitea's own database by the same account that runs Gitea (rejected by the Architect: unenforced reach to every table, schema coupling). | **Done 2026-11-12**: Acts A to E performed, each PASS (Decisions, 2026-11-12: Act A step (iv); Act B `verified` with its baseline; Act C; Act D; Act E, the prepare phase of OA-14); the protection check is qualified on the S-01.2.2 fixture only; decision 0012 Accepted (Overseer). The row's earlier status ("next: the storage fix, then step (iv)") was stale; moved to Resolved by planning, 2026-11-13. |
| OA-27 | Decision 0018 | Accept, amend or decline the revised decision 0018 | **Accepted by the Owner 2026-11-12, revision 4** ([Owner acceptance](#owner-acceptance-0018-rev4), verbatim). Consequences applied: the inventory's `op-policy-change` and `op-git-push-public` record the point-3 delegations; `CLAUDE.md`'s Owner-statements rule; the plan amendment (OA-28). No reserved live effect is authorized by it. |
| OA-28 | D1 plan amendment proposal | Approve or decline the D1 plan amendment, items 1 to 5 | **Applied 2026-11-12** through the integrity process ([proposal](D1-plan-amendment-proposal.md)): items 1 to 4 decided by the product manager under decision 0018 point 3; item 5 approved by the Owner together with item 3 ([Owner acceptance](#owner-acceptance-0018-rev4)). The projection agreement check passed before and after; `verify_seed` PASS at 174 leaves. |
| OA-23 | D1 commitment; decision 0008 | The D1 demo change's design acceptance | **Delegated 2026-11-12** (decision 0018 point 3.2): the product manager accepts the D1 demo design once the Owner names the change (OA-25), recorded through the recorder as an acceptance delegated by decision 0018 (P-04.3's kind), never as an Owner decision. No Owner act remains. |
| OA-24 | D1 commitment; P-04.3 | Every D1 live manifest promotion | **Delegated 2026-11-12** (decision 0018 point 3.3): the product manager promotes D1's manifests inside the envelope the Owner grants, which is OA-22 item (j); an entry outside it is an Owner decision per act. |
| OA-26 | E-01.3.3; E-05.4; E-05.5 | Credential access to the harness's own bot entries | **Delegated 2026-11-12** (decision 0018 point 3.4, routine use of harness-managed role credentials under their decided custody). E-01.3.3's probe still needs OA-22 item (d) for the dispatch edge. |
| OA-21 | P-04.2 acceptance review (2026-11-12); reconciliation row O-033 (`fd-owner-credential-custody`) | Accept, as a decision-0010 same-account limit, that the Owner's push credential (`cred-owner-github`) and coding-assistant login (`cred-owner-provider-login`) stay in the Owner's own host stores, uninspected; or authorize a read-only, metadata-first inspection. | **Closed 2026-11-12, nonblocking, no inspection** (Owner direction, Decisions, "Owner direction: decisions on the product manager's first planning assessment", item 2: "Accept the existing decision-0010 same-account threat-model limit as sufficient for this finding. Close OA-21 as nonblocking, retaining the disclosed limitation and reconsideration condition."). `fd-owner-credential-custody` is now a disclosed limit under [decision 0010](../decisions/0010-effects-store-placement-and-governance-threat-model.md) point 1 (same-account processes out of scope), with its reconsider condition unchanged: a separate operating-system identity for the dispatcher or the development agents. Where the Owner's stores keep the two credentials, and whether a file copy exists, stays not inspected and unknown; nothing is claimed. Their absence from agent attempts stays S-03.3's proof, and from CI jobs the plan's deferral. |
| OA-05 | F-10.5; decision 0014 section 8 | **Approve or decline one run**, exactly as presented: the repository-access contract suite (8 repository files, 446,127 bytes, archive sha256 `6ba67720…ee00`, plus the pure Dulwich 1.2.21 and urllib3 2.8.0 wheels from the lock) in one new disposable guest `f105-linux` (profile `strong-windows-qemu-whpx`), no guest network, no host share, no guestfwd, no new host port, no credential; only the test report (at most 1 MiB) comes back; the guest is destroyed in every outcome, and destruction verified. | **Done 2026-11-10, once** (revision 3; [run evidence](F-10.5-oa05-linux-run.md), [report](F-10.5-linux-report.json)). Inputs verified before execution; the run completed: 79 ok, 1 module skipped as expected (no git), **2 FAIL** (`Ceilings`: ancestors of the guest temporary directory recorded as touched on Linux, not on Windows); digest `302f93ce...c32f` differs from the Windows reference. Teardown verified by the script and independently by the Overseer (no instance record, 0 QEMU processes, 0 QEMU listeners). Linux git-oracle parity, the native Linux Dulwich wheel and `write_commit` on Linux stay unverified. The failures are under diagnosis; any further guest run needs a new Owner approval. |
| OA-15 | P-04.2 finding F1; decision 0012 | Two decisions on [decision 0012](../decisions/0012-owner-authorization-channel-and-gitea-owner-identity.md): **(1)** the protection rules `aieh-owner` cannot read at Gitea 28.3.0 (the other accounts on the merge and push allowlists, force push, `block_admin_merge_override`, `block_on_outdated_branch`, the approvals allowlist, `block_on_rejected_reviews`, the rule name): the Overseer recommends **detected, not prevented** (only administrators, whose credentials are the Owner's, can change them; a principal that can read the rule compares it, at G-03.2 or in the verifier), rather than handing an administrator's read to the recorder before each merge. This narrows P-04.2's proof clause "protection drift is refused" to the drift `aieh-owner` can observe. **(2)** Approve maintenance item M-4, the blueprint wording for the recorder (step 16 in `#sequence-maps`, the `#decisions` "Owner merges" step, consistency wording), by the authority-class process. | **Decided by the Owner 2026-11-10** (verbatim under Decisions). (a) **Declined:** the requirement is not narrowed to what `aieh-owner` can see; a consequential authorization fails closed if its required protection settings cannot be verified; the Overseer investigates a narrowly scoped, trusted, read-only check of every security-relevant protection rule immediately before the merge (no administrator privilege for `aieh-owner`, no administrator credential in the recorder); [decision 0012](../decisions/0012-owner-authorization-channel-and-gitea-owner-identity.md) stays Proposed until that control is established and qualified (point 6 amended). (b) **Approved:** M-4 by the integrity-controlled blueprint process; the Owner decides, the deterministic recorder merges as `aieh-owner`, and no model or agent may manufacture an Owner decision. |
| OA-02 | E-01.4.3 findings F-1, F-2 | Filing the OpenHands companion note to OpenHands/software-agent-sdk is **authorized** (2026-11-09). This session has no authenticated GitHub tool. Either file the prepared text yourself and send the URL, or make an authenticated GitHub tool available to the session (for example, the GitHub CLI installed and logged in by you), and the Overseer files it. | **Publication authority withdrawn, unexercised** (Owner, 2026-11-10; [decision 0017](../decisions/0017-git-host-agnosticism-and-owner-scoped-external-publication.md)). Nothing was filed. Kept as internal knowledge, deferred optional external reporting, not an Owner action: Ready to file, revised for accuracy: [E-01.4.3 evidence, section 13](E-01.4.3-start-race.md). The section 9 companion draft is superseded. Duplicate check done: none found. Any external report needs a new, explicit, scoped Owner decision naming the destination and the exact content. History: Pending: authorized (Owner, 2026-11-09; the authorization stands, Owner, 2026-11-10); no authenticated filing tool in this session; nonblocking |
| OA-09 | F-10.6 finding (ruling R5) | Authorize, or decline, filing the upstream report to jelmer/dulwich: `Urllib3HttpGitClient(extra_headers=...)` stores the headers but never sends them (1.2.21). If authorized, it is filed as OA-02 is (by you, or by the Overseer once an authenticated GitHub tool is available). | **Publication authority withdrawn, unexercised** (Owner, 2026-11-10; [decision 0017](../decisions/0017-git-host-agnosticism-and-owner-scoped-external-publication.md)). Nothing was filed. Kept as internal knowledge, deferred optional external reporting, not an Owner action: Ready to file: [F-10.6 evidence, "Upstream report: Dulwich `extra_headers`"](F-10.6-transports.md). Duplicate check done: none found (closest: #1769, #882, #2201, all about other paths). Any external report needs a new, explicit, scoped Owner decision naming the destination and the exact content. History: Pending: authorized (Owner, 2026-11-10). Rechecked 2026-11-10: no matching upstream report (issue and pull-request searches `Urllib3HttpGitClient`, `extra headers`, `extraHeader`); the reproduction re-run on dulwich 1.2.21 (the latest release): the server received no header; still present on upstream `main` at `5b6e39c` (the argument stored, never read). Filing waits only for an authenticated GitHub tool |
| OA-03 | E-01.2.2c finding F-2; limit `fd-outer-server-local-recovery` | **Authorize or decline filing** the ready report to OpenHands/software-agent-sdk, and **choose the route**: GitHub's private vulnerability report (recommended by the preparer: the repository's security policy page offers "Report a vulnerability"; whether private reporting is enabled was not confirmed), or a public issue (the text is written to be safe in public). If authorized, it is filed as OA-02 is (by you, or by the Overseer once an authenticated GitHub tool is available). | **Publication authority withdrawn, unexercised** (Owner, 2026-11-10; [decision 0017](../decisions/0017-git-host-agnosticism-and-owner-scoped-external-publication.md)). Nothing was filed. Kept as internal knowledge, deferred optional external reporting, not an Owner action: Ready: [OA-03 report](OA-03-openhands-resume-report.md) (`787f41b`): evidence review (observed, read from upstream source at `v1.60.1`, and our own deployment choices kept apart), the code path, unchanged at v1.60.2, v1.61.0 and `main`, and a duplicate check of 19 queries (none equivalent; closest #4893, #5128, #5626). Overseer spot-check of the cited upstream lines: confirmed. Framing: resume itself is intended crash recovery; the question is that Docker-backed records are hydrated in the outer process (stored module imports, host `working_dir` creation, the lease), with no switch. Any external report needs a new, explicit, scoped Owner decision naming the destination and the exact content. History: Pending: authorized for GitHub private vulnerability reporting only (Owner, 2026-11-10). Private reporting is enabled on OpenHands/software-agent-sdk (GitHub API, 2026-11-10). Blocker: no authenticated GitHub tool in this session; the Owner may file the prepared text himself from the repository's Security tab ("Report a vulnerability"). Never posted publicly without a separate Owner decision |
| OA-11 | F-06.3 finding 1 | Remove the stray `<managed root>\persistent\state\integration\integration.sqlite` (and sidecars; the directory if empty), after a read-only check. Approved conditionally by the Owner, 2026-11-10. | **Done 2026-11-10.** No sidecars existed. The read-only check (immutable SQLite open) found exactly the five synthetic receipts (`MemoryProvider`; four confirmed, one failed), their 15 events and the schema's reference rows; nothing else. The file (sha256 `4fcc5516...6737`, re-checked) was removed, then the empty `integration` directory. [Evidence](OA-10-OA-11-owner-acts-2026-11-10.md). |
| OA-10 | F-06.3 proof (the throwaway-name cross-read test) | One run of the real-store cross-read test against the Owner's Windows Credential Manager. Approved by the Owner, 2026-11-10. | **Done 2026-11-10, once, PASS** at `867381b`: one throwaway entry written, read back by name from a separate process (fingerprint only), deleted, absent from a separate process and from the test; I7 clean; no other entry read, written, deleted or enumerated. [Evidence](OA-10-OA-11-owner-acts-2026-11-10.md). F-06.3 passes and decision 0011 is accepted. |
| OA-01 (with OA-04, merged) | E-01.4.3; E-01.2.2c finding F-15 | File the litellm import-race report and record its reference. Authorized by the Owner, 2026-11-09. | **Closed 2026-11-09, no filing needed:** an equivalent upstream record exists. [BerriAI/litellm#48292](https://github.com/BerriAI/litellm/pull/48292) (merged 2026-10-25) describes the same offline start-up `ImportError` and fixes it in litellm 1.105.5 (on PyPI); [#46711](https://github.com/BerriAI/litellm/pull/46711) is the fix on main; [#46142](https://github.com/BerriAI/litellm/issues/46142) is a related symptom. Per the authorization ("record its URL and add relevant new evidence only when appropriate"), the URL is recorded and nothing is added: the fix needs nothing from our evidence. Duplicate check and review: [E-01.4.3 evidence, section 13](E-01.4.3-start-race.md). The receipt closes E-01.4.3 (its row). |
| OA-08 | F-10.2 finding F-2 | Delete the two synthetic corpus directories `aieh-repo-corpus-9o7tj36r` and `aieh-repo-corpus-_ifrtu9s` from the user temp directory. Authorized by the Owner, 2026-11-09. | **Done 2026-11-09 by the Overseer**, after checking that: both lay directly in the user temp directory, which is not a reparse point; neither was a link or reparse point, with 0 reparse points inside (590 entries and 43,615 bytes each); the layout matched the F-10.2 corpus generator (`ROOT_NAME = 'a b ü'`; the bare, damaged, SHA-256 and work-tree test repositories); and no process command line referenced them. Exactly these two paths were removed; both now report absent. |
| OA-R1 | F-03.2 host acts A1-A3 | A1: enable the Windows Hypervisor Platform and restart. A2: install the pinned QEMU. A3: create the guest-state directory. | Done 2026-11-06, under Decisions: "Owner host acts", "A1 complete", "A2 done". The F-03.1 row's "pending" text predates them. |
| OA-R2 | Decision 0007, "Owner confirmation" 1-3 | (1) The Owner holds the Gitea site-administrator credential and a separate Owner account. (2) Where Gitea runs. (3) Routing the plan gaps. | (1) The Owner's identity decision applied in F-06.1. (2) and (3): "2026-11-07: Owner decisions on three plan gaps". The decision text is reconciled with a dated resolution note; the accepted text is kept unchanged. |
| OA-R3 | F-06.1 | The Owner's first Gitea sign-in and the credential finish step. | Superseded by automated finalization, S-01.2.2 `63e2628` ([F-06.1 evidence, section 8](F-06.1-gitea-loopback.md)). No Owner sign-in is needed. |
| OA-R4 | M-3; the Agent Server start-up race | Approve the M-3 wording reconciliation, and give the race an owner. | Owner decision of 2026-11-09 (Decisions). M-3 done `01842b5`; the race was given leaf E-01.4.3 (`ab0def1`). |

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
| F-03.2.1 Declare reference Linux guest profile | **PASS (2026-11-06)** for the reference profile `strong-windows-qemu-whpx` (W1, this host). `strong-incus-vm` is declared but not validated: it has no Incus host here and 4 pins remain UNRESOLVED, carried to its Linux leaves | `e90b02f` (part a); `dcef745`, `d1aa45f`, `f42b2c7` (part b) | Part a: `profiles/strong-windows-qemu-whpx/` (Debian 13 genericcloud image pinned by sha512 and sha256, TLS-only provenance; SeaBIOS from the pinned QEMU; NoCloud seed on a read-only virtio disk; 8 vCPU, 16 GiB, 40+120 GiB; SLIRP `restrict=on` with loopback-only forwards; `-accel whpx` with no fallback; vmx/svm masked), the QEMU MSYS2 lock, `tools/check_profile.py`. Part b: contract amendment allowing read-only configuration media (QEMU NoCloud seed; Incus `cloud-init:config`/`agent:config`), 9p `config` share still forbidden; [provider validation evidence](F-03.2.1b-provider-validation.md): strict profile check PASS; `QEMU emulator version 11.1.3`, accelerators `tcg whpx`; image sha256 and sha512 match; paused boot (`-S`, full 65-argument argv from `profile.json`, guest code never run) answered QMP with `query-accelerators` `enabled: whpx`, `prelaunch`, 8 CPUs, base memory 17179869184, QOM `vmx`/`svm` false on all vCPUs, `quit` then exit 0. Defects fixed forward in PREREQUISITES: the QMP one-liner returned the SHUTDOWN event instead of the `quit` reply, and it had a launch race. Open for F-03.2.2: `-mon` is deprecated in 11.1.3 (Overseer: replace it in F-03.2.2 and re-run the paused boot then; no argv change now); a prelaunch warning, `Ignoring request for interrupt vector 0`; guest-visible CPUID masking. The Overseer independently re-ran the strict check and re-hashed the image, read `query-accelerators` in the raw QMP transcript, confirmed no QEMU process remained and the instance directory was gone, and reviewed the contract diff. | F-03.2: not yet; it is evaluated at F-03.2.2 (real boot and the observable isolation tests, C6). |
| F-03.2.2 Provision and inspect disposable Linux guest | **PASS (2026-11-06)** | `0a061e9`, `e86cf13` (part a); `ec1ae0b`, `c6f1286`, `2dbcbda` (part b) | Part a ([evidence](F-03.2.2a-seed-and-monitor.md)): `tools/nocloud_seed.py`, a deterministic ISO 9660/Joliet NoCloud seed with 27 tests. The QMP monitor moved off the deprecated `-mon` to `-object monitor-qmp`, the form QEMU's own help documents. The paused boot re-run showed no deprecation warning and `enabled: whpx`. Part b ([evidence](F-03.2.2b-guest-lifecycle.md)): `tools/guest.py` covers preflight, create, start, stop, destroy, recreate, inspect and exec per `lifecycle.bindings`, with 8 `guest:*` Task targets and 39 tests. Two real disposable Debian 13 guests were booted one after the other under WHPX, inspected and destroyed. Declared versus observed matched in every row: 8 vCPU, 16 GiB, 40+120 GiB, read-only seed and base, whpx, vmx/svm absent in the guest, devices, loopback-only forwards, firmware and image digests. cloud-init accepted the `cidata` seed. The two guests had distinct machine-ids and host keys, and user `agent` has no sudo and no root SSH. Owner conditions 1-9 are evidenced condition by condition. SSH and QMP `Listen` only on 127.0.0.1; connecting to them on the LAN address and on `[::1]` was refused. Egress was blocked from the unprivileged account: no route to external addresses, and `restrict=on` refused 10.0.2.2/10.0.2.3. **Not shown:** a guest root with a default route (owned by F-03.3.2). Teardown: no process left, instance directories removed, image and QEMU hashes unchanged. Fix-forward: the P6 contract wording now requires no socket under `/tmp/.X11-unix` (Overseer decision; the new check has not yet run on a real guest). Recorded WHPX limitation: `misordered xstate at 1408` WARN under `-cpu max` on this AMD host. It is not attributed to the upstream CPUID[0xD] no-XSAVES panic defect (Owner-supplied finding, compared against the serial log). On hosts without XSAVES a panic is expected, and preflight does not detect it. The CPU model is qualified in F-03.4/R-03.x; `-cpu` is unchanged. The Overseer re-ran 181 tool tests, the strict check and verify_seed, and confirmed 0 instances and no QEMU process. Architect not consulted: no gate was reached, and the CPU-model choice is deferred as a qualification obligation. | **F-03.2 PASS (2026-11-06):** a disposable guest was created from the declared profile and its reported settings match the pinned configuration. The strong tier is **not** operational until F-03.3.x, F-03.4 and S-02.x pass (C6, Owner condition 9). |
| F-03.3.1 Constrain guest filesystem and credential surfaces | **PASS (2026-11-06)** for `strong-windows-qemu-whpx`; `strong-incus-vm` declares no storage table (no host) | `0a0b5cc`, `a255499` | [Evidence](F-03.3.1-guest-surfaces.md). `profile.json` gains a machine-checked `guest_storage` allowlist (block devices, 25 mounts derived from a reconnaissance guest, exchange and scratch directories, forbidden types and paths) and `exchange` bounds. `check_profile` validates the table against `launch.argv` exactly. `tools/guest.py` gains `exchange-push`/`exchange-pull` (git bundle over the loopback SFTP forward, using a synthetic fixture repository only), canaries, and per-property P3-P6 checks. Two fresh guests passed P3 (7/7), P4 (8/8), P5 (6/6) and P6 (11/11). 13 synthetic canaries were planted in the host environment and a fake home: 0 found in the guest, seed, `launch.json` or serial log, and the host-side positive control found all 13. The per-instance private key was not found in any encoding. The exchange bundle digest was identical on the host, in the guest and after the pull, and `git fsck --strict` passed. 35 negative-control tests (46 mutation sites) turn each property to FAIL. Owner conditions 1-9 are evidenced. Limits: the P5 scan reads what `agent` can read (root-only files not read; the seed is scanned on the host). P6 uses a deny-list plus absence of channels; the vsock local CID is 1. Defect introduced and fixed forward: `destroy` failed on read-only git pack files (`remove_tree`). The Overseer re-ran 286 tool tests, the strict check and verify_seed, scanned the range for canary- or key-shaped strings (none found), and confirmed 0 instances and no QEMU process. Open: where exported exchange evidence lives for `fresh`-mode guests. | F-03.3: not yet. P7 ("unrestricted host bridge") is F-03.3.2. |
| F-03.3.2 Restrict guest networking | **PASS (2026-11-06)** for `strong-windows-qemu-whpx` | `3b6305c`, `948ed37` (fix-forward), `731d8fc` | [Evidence](F-03.3.2-guest-network.md). A test-only `netprobe` validation mode, refused by ordinary `create`/`start`, adds a pinned root probe (cloud-init multipart) and one guestfwd to a 127.0.0.1 echo listener. The ordinary `launch` block and seed templates are byte-identical before and after (the Overseer compared `launch` against origin). With guest root installing IPv4 and IPv6 default routes, every probed denied path stayed unreachable: 58 from the guest and 30 from a network namespace behind guest NAT. That covers public IPv4 TCP and ICMP, DNS over UDP and TCP to SLIRP and public resolvers, the host LAN address, 10.0.2.2 to the SSH-forward, QMP, listener-host and decoy ports, a UDP decoy, other guestfwd-looking addresses, and IPv6 literals and host IPv6 addresses. The guestfwd nonce exchange succeeded from both (positive control), and the decoy logs show no guest contact. The NIC tx counter rose, so the frames left the guest. An ordinary guest still passed P3-P6 and exchange afterwards. Owner conditions 9 + 8 are mapped to evidence. `profile.json` `network`: enforcement point `qualified` (SLIRP `restrict=on` with guestfwd), a reachability table and an IPv6 statement. `inference` and `provision` stay deferred and need Owner authorization; the broker must be up before QEMU starts. Defects introduced and fixed forward after cycle 1, which reached no denied path: TimeWait counting, resolver-timeout classification, and probe-namespace artefacts in `inspect`. Recorded at the time: pinned templates and the probe are hashed as LF, and `.gitattributes` was believed not to pin them. **Corrected by F-03.4:** the nested `profiles/.gitattributes` (`e90b02f`) already marks them `-text`; a fresh `autocrlf=true` clone reproduced every digest, and no change was needed. The Builder's `ls` of the guest-state root printed the protected `downloads` name only. The Overseer re-ran 433 tool tests and the strict check, scanned the range for host addresses (only guest veth link-local addresses), and confirmed no QEMU or listener process and 0 instances. | **F-03.3 PASS (2026-11-06)** for this profile on this host: no implicit Owner-folder mounts or privileged sockets (F-03.3.1), and no unrestricted host bridge (F-03.3.2). Limit: "inside a container" was approximated by a guest network namespace; a real container is S-02/E-01 after F-04.1. The strong tier is still not operational (F-03.4, S-02.x; C6). |
| F-03.4 Demonstrate reproducible teardown and inspectability | **PASS (2026-11-06)** for `strong-windows-qemu-whpx` | `8803d24`, `b5ff695` (fix-forward), `5775877` | [Evidence](F-03.4-teardown-qualification.md); [qualification record](../profiles/strong-windows-qemu-whpx/QUALIFICATION.md) (P1-P12 per leaf, host class without a machine name, limitations, adaptation points). `guest.py smoke` / `guest:smoke` runs preflight, create, inspect, graceful stop, start, inspect, forced stop, recreate, inspect-compare, destroy, and inventory-compare. It passed twice end to end on fresh names (93 s each). The first run failed on a self-introduced classification defect: guest MemTotal varies per boot. It was fixed forward, and QMP base-memory stays the exact stable ceiling. P10: the inventory covers the checkout (HEAD, status, `ls-files` digest), the shared state-directory content (image and provider binary hashes, provider tree digest), every other entry under `instances/`, and planted sentinel durable roots. Owner folders are never traversed. All 12 before/after diffs were empty, and a sibling instance, running and stopped, stayed byte-identical. Recreate kept 78 stable fields equal and renewed all per-instance identity (machine-id, host key, instance id, seed, SSH key). `start` from `launch.json` was exercised for real for the first time. XSAVE: preflight reads host XSAVE features with a read-only `WHvGetCapability` (this host includes XSAVES); a host without XSAVES is refused with `TIER_UNAVAILABLE`. The serial-log detector reported only the recorded `misordered xstate` limitation in all 10 inspects. P11 labels are now on every record and on a `stderr.log` header. `-cpu` and `launch` are unchanged (the Overseer compared them against origin). The Overseer re-ran 473 tool tests, the strict check and verify_seed, and confirmed 0 instances and no QEMU process. The one 127.0.0.1 python listener seen was an unrelated local application of the Owner, not harness work. | **F-03 PASS (2026-11-06)** for the Windows reference profile on this host: guest provision and teardown mount no Owner secrets or uncontrolled host folders (F-03.3.1 P3-P6, F-03.3.2 P7, F-03.4 P10). Limits: P5 scanned as `agent`; container-in-guest approximated by a network namespace; the WHPX XSAVE limitation. Linux (Incus) and macOS (Lima) profiles are not qualified. The strong tier is **not operational** until S-02.x passes (C6). |
| P-01.1 Define intent distinction schema and normalization Skill | **PASS (2026-11-06)** | `db82899` | `catalog/openspec/schemas/intent-driven/`: an OpenSpec 1.16.0 custom schema with proposal, specs and design. `apply.requires` lists all three and `apply.tracks` is omitted (blueprint #authority). The proposal template carries an intent record: verbatim attributed quote, objective, binding constraints, proposed methods, hypotheses, acceptance criteria, open clarifications, with attribution and claim type per item. `catalog/skills/intent-normalization/` is an Agent Skills SKILL.md, version 1.0.0, with a reference grammar and CHANGELOG. `tools/check_intent_record.py` is a stdlib invariant checker with 43 tests: the quote is a byte-identical span of the source; an Owner method stays a hypothesis unless an acceptance separate from the quote's source is recorded; required fields are present. Proof: a confusing sample request ("bump the gateway timeout ... put a Redis cache") keeps its original text byte for byte, both prescribed methods are classified `hypothesis` with refutation tests, and the ambiguities become clarifications. The fixture is builder-produced, not a model qualification (that is P-01.2). Mutations fail with exact codes. With the pinned OpenSpec, `openspec schema validate intent-driven` is valid and `status` shows the proposal done. The Overseer re-ran the checker and its 43 tests and verify_seed. Architect not consulted: the blueprint settles the schema shape. The Overseer accepted the Builder's interpretations: an acceptance must be separate from the quote's source, and the claim types follow the minimal semantic record. | P-01: not yet; evaluated at P-01.2 (live model runs, OpenSpec acceptance recording). |
| P-01.2 Qualify clarification and adoption behavior | **PASS (2026-11-06)** for one model and channel | `5fc74e8` (corpus and expected outcomes, committed before any run), `2970b48`, `ffdec17` | [Evidence](P-01.2-intent-skill-qualification.md). The Owner authorized it: 23 of 25 allowed `claude -p` invocations on `claude-opus-5-5`, USD 1.71 at list price. Runs were tool-less and isolated: `--tools ""`, `--safe-mode`, an empty MCP config, `--setting-sources project`, no session persistence, the Skill as system prompt, and an empty scratch working directory outside any repository. The session metadata of all 23 shows no tools, MCP servers, skills or slash commands, and no credential was set or read. Account context could not be excluded; it appears in no output. The corpus has 13 requests: ambiguous goals, misleading methods, insistence, an embedded injection, a genuine separate acceptance, no method, and Unicode/whitespace. There are 4 clarification follow-ups. Checker: 16/17 PASS. The exception is qual-08, where U+00A0 is lost in the headless channel (D2). Fidelity: 17/17 against the pre-written expected outcomes. Misleading Owner methods stay hypotheses; the injection is quoted, not obeyed (Overseer spot-checked qual-05 and qual-06); a genuine acceptance promotes only what it covers; resolved clarifications cite `conversation:qual-NN/message-2`; the original quote stays byte-identical. OpenSpec 1.16.0: a fixture acceptance standing in for the Owner accepts O1 and AC1 only, the delta spec is written from those alone, and validate passes. The checker refuses promotion without a separate acceptance. Skill 1.0.0 → 1.1.0: a general rule that an agent-proposed method cites the item it serves, never a quote (D1, exposed by P-01.2). **Overseer decision on D2:** quotes are to be filled mechanically from the durable source by the integration, with the model referencing message spans, carried to P-03.x and U-02.x. The model-written quote stays checkable by `check_intent_record.py`. Limits: one model, one channel and one run per item (no variance); a synthetic corpus written by the Builder; the fidelity review is the Builder's own, guarded by commit order plus the Overseer's spot-checks; the acceptance is a fixture, not an Owner decision. The Overseer re-scanned the range for account data (none found). | **P-01 PASS (2026-11-06)**, with the limits above: a misleading Owner method suggestion remains a hypothesis; the accepted objective reflects the original desired behaviour; clarifications are traceable to messages. |
| F-05.1 Create integration SQLite receipt and projection schemas | **PASS (2026-11-06)** | `2a663ae`, `aac903f` (AGENTS.md fix-forward) | `integrations/store/`: stdlib `sqlite3`, STRICT tables, migration 0001 with an sha256-checked migration ledger, and `user_version`. Transaction policy: WAL, `synchronous=FULL`, `foreign_keys=ON`, `BEGIN IMMEDIATE` (single writer); SQLite 3.38 or later is required, and 3.49.1 was observed. Identity: a caller `operation_key` and the sha256 of canonical intent JSON; the conversation ID is `uuid5` of a fixed namespace and the key, persisted at reservation (decision 0001). States: reserved, dispatched, confirmed, failed, unknown, with transitions enforced in code and SQL and an append-only event table; deletes and identity edits are refused by triggers. Projections (`proj_*`) rebuild under an SQLite authorizer that denies writes outside the projection. The store refuses paths inside the repository, network paths and `:memory:`. The default trusted-host location (per-user app data, never the guest state directory) is not yet initialized. Proof: 33 tests. A subprocess `os._exit` after commit leaves the reservation present and `reserved` on reopen; a kill inside an open transaction leaves nothing. 8 real processes racing on one key give one row with a shared ID (same digest) or 1 winner and 7 conflicts (different digests). A rebuild leaves the receipt and event tables byte-identical. The Builder ran mutation checks, and the Overseer re-ran the 33 tests and verify_seed. Architect not consulted: blueprint #infrastructure-state settles the store's semantics, and the remaining choices are local schema mechanics that migrations can change. Carried to E-01: whether `unknown` can be re-dispatched (currently not; changing that needs a decision consistent with "never reissue unknown external effects"), the restart sweep of `dispatched` attempts, and operation-key minting. Carried to F-05.2: backup and restore versus effects already performed, the effects store's separate OS identity on a single-user Windows host, OS-crash durability, and retention. | F-05: not yet; evaluated at F-05.2. |
| F-05.2 Separate privileged effect records and validate backup recovery | **PASS (2026-11-06)** on fixtures | `81580db`, `5609ac3`, `224f6cc` | [Evidence](F-05.2-effects-store-backup-restore.md). The design is [decision 0004](../decisions/0004-privileged-effect-store-custody-and-restore-semantics.md): Architect gate G, Overseer option O4, and Owner **Accepted** with seven clarifications (`5017094`). `integrations/storecore/` holds the shared F-05.1 mechanics; ATTACH is impossible (attached-database limit 0) and each store has its own `application_id`. `integrations/effects/` is a separate effects store: STRICT tables; receipts with key inputs and the authority reference; states reserved, applying, completed, failed, unknown and observed, with origin-scoped transitions; an append-only hash-chained journal; an epoch gate that blocks reservation and apply. Custody is read back from the effective DACL and owner with `GetNamedSecurityInfoW` on every open, and refused by name. The location rule refuses a default path, the repository, profile roots, UNC, the guest-state root and the integration tree; the fixture policy is library-only. Integration store migration 0002 adds an `application_id`, restore epochs and a reservation gate; 0001 is unchanged. Proof: 34 + 9 new tests. A reservation survives `os._exit`; a killed transaction leaves nothing; an `applying` receipt is flagged after a crash. Backup uses the SQLite backup API with integrity check and sha256 manifest; restore leaves receipts at backup time byte-identical (chain head equal), opens an epoch that refuses reservations, and closes it only after fixture-oracle reconciliation, with Owner attestation for unknown. A rollback is refused unless accepted, superseded live content is preserved aside, and tampered, wrong-kind or newer backups are refused. A rebuild from a synthetic OpenSpec/Backlog git repository leaves its tree and status and the canonical tables unchanged. 10 mutations were caught. Nothing live was created: no effects root, account, task, service or elevation (the Overseer confirmed `D:/aieh-effects-state` and the default integration store location are absent). The Overseer re-ran the 42 + 34 store tests and verify_seed, and accepted the Builder's interpretations: reconciliation-only transitions; applying or unknown found not performed becomes `failed` with the key spent; `begin` is refused during an epoch. Limits: a fixture oracle instead of real target probes (G-04.4.2, G-04.5, E-01.4.x); a fixture repository instead of OpenSpec/Backlog; OS-crash durability UNKNOWN; live identity separation not provable before G-04.2.1/G-04.2.2; the effects CLI success path needs the Owner-created root (A4). | **F-05 PASS (2026-11-06) on fixtures:** crash and reopen preserve unfinished receipts in both stores, and rebuilding projections never rewrites the canonical sources. The limits are as listed. |
| F-04.1 Configure pinned Agent Server Docker runtime | **PASS (2026-11-07)** for `strong-windows-qemu-whpx` | slice a `ab950fb`, `f605aaf`, `9a29f54`; slice b `31ecaf4`, `e34d495`, `a53a73d`; slice c `90816fa`, `faa0532`, `bba9fb5` | Design: Owner direction (host download, then SFTP, then native install in the guest) and an Architect gate C/G consultation; [decision 0006](../decisions/0006-guest-provisioning-channel-and-image-conformance.md), Accepted by the Overseer at completion. Owner authorization A and B. Evidence: [a](F-04.1a-provision-pins-fetch.md), [b](F-04.1b-provision-moby.md), [c](F-04.1c-agent-server.md). Declared versus observed, all match. **Version:** binary sha256 equals the lock, and `/server_info` reports 1.60.1. **Engine endpoint:** the Docker CLI over the unix socket `/run/docker.sock`, Moby 26.1.5+dfsg1. **Image:** the local immutable tag `aieh/agent-server:1.60.1-b43ee580` resolves offline, with image ID equal to the locked config digest (decision 0006 item 3). **Data paths:** 8 directories under `/srv/scratch/openhands`, owned by `openhands`. **Runtime selection:** `conversation_runtime` docker, not selectable, with capabilities `conversation_runtime_routes_v1` and `idempotent_conversation_create_v1` present (decision 0001 s2 met). Listener: `127.0.0.1:8000` inside the guest only, with no host forward. The session key is enforced (401 without it or with a wrong one). `OH_SECRET_KEY` sits in a root-only env file, not readable by `agent`; neither secret is in any record (fingerprint search). Per-conversation caps are 4g/2 CPU/512 pids with 3 concurrent runs, inside the 16 GiB / 8 vCPU guest. `smoke --provision` PASS with stable start and recreate comparisons. Contract amendments by the Overseer as contract owner: P2, P5 (session key and secret custody), P6 (the guest's own Moby sockets; the `openhands` service user) and P7 (the guest-internal Agent Server listener). `launch` is byte-identical throughout. A disposable conversation-create fixture is validated against the locked `openapi.json` and not executed (F-04.2). Recorded: LiteLLM tries a model-cost-map fetch at start, fails on DNS and falls back (no egress). Upstream `build_git_sha` is unknown. Containment findings are confirmed in source and carried to S-01.3.x/E-01.2.2: request-level `container.memory/cpus` override the server caps, `--add-host host-gateway` is always added, and there is no `--network none`. Process disclosures: two Builder path-boundary slips (a recursive grep from the repository root in slice c, and `ls` of named state-directory children in slice a). Neither read protected content. The Overseer re-ran the strict check, 455 profile/guest/provision/seed tests and verify_seed, compared `launch` against origin, scanned for secret values, and confirmed 0 instances and no QEMU process. | F-04: not yet; F-04.2 creates, stops and reopens the fixture conversation. Open for F-04.2: conversation containers publish `-p 127.0.0.1::8000`, a Moby-owned loopback listener that P7 currently rejects; the contract owner must declare a bounded allowance. |
| F-04.2 Exercise contained conversation lifecycle | **PASS (2026-11-07)** for `strong-windows-qemu-whpx` | `fec83d9`, `66ab854` | [Evidence](F-04.2-conversation-lifecycle.md). `guest.py conversation-smoke --restart --openapi --canaries` (Task `guest:conversation-smoke`) on a fresh `create --provision` guest PASS in 13 steps, driven as `agent` over the session-keyed guest-internal API with no LLM and no network. The fixture is valid against the locked `openapi.json`, and every route used is present in the live server's own document. **Create** returned 201 with the fixed id (no LLM key or base URL, empty secret registry). **Inspect**, from root facts: `.Image` is the locked ID `sha256:e8959dfc…`; user `999:989`; `CapDrop` ALL; `no-new-privileges`; 4 GiB/2 CPU/512 pids; exactly the three declared mounts; one `docker-proxy` listener on guest `127.0.0.1` to container port 8000. **Idempotent create** returned 200 with the same id and container. **Stop** (`DELETE …/runtime`) returned 204 and removed the container and its listener, leaving the state unchanged. **Reopen** (`…/runtime/reprovision`) gave a new container with the same mounts, id and stored-state hashes. The same held across a graceful guest restart. **Delete** returned 200, then 404. `smoke --provision` still PASS (stable start and recreate comparisons). Contract amendment by the Overseer as contract owner: a bounded P7 allowance, exactly one Moby (`docker-proxy`/`dockerd`) listener on guest `127.0.0.1` at an ephemeral port per owner-labelled conversation container, mapped to its port 8000, never forwarded to the host (decision 0003 Current facts). `launch` is byte-identical. New root reporter: an on-demand, parameterless conversation-facts unit (`agent` creates a request file in a `root:agent 0730` directory; `PathExists` starts a root oneshot that unlinks the file without opening it and runs only `docker ps`/`docker container inspect` on owner-labelled containers; secrets are redacted; at most 20 runs per 60 s, failing closed; `IPAddressDeny=any`). The Overseer reviewed its source: a directory planted at the request path only exhausts the rate limit and so denies `agent` its own reporter, which is acceptable. Overseer ruling on the Builder's finding 2: a conversation with no message persists no events (upstream behaviour), so retention is proven by the stored-state hashes and the listing after restart. A non-empty event log is not required by the F-04 or F-04.2 proof and is outside the authorized fixture. Non-empty event retention is carried to the first leaf that runs a real conversation turn. Recorded, carried to S-01.3.x/E-01.2.2: `--add-host host.docker.internal:host-gateway` (resolves to the guest's `docker0`); `NetworkMode` bridge (no `--network none`); request caps override server caps (by source, not exercised); the inner server ignores the outer VSCode/preload settings and starts VSCode on unpublished port 8001; container resolver `8.8.8.8`; LiteLLM cost-map fetch at start by server and each container fails at DNS; residue after delete (a `runtime-control/*.json.lock` and an empty `.trash/`). The release `openapi.json` documents only the local runtime; the Docker routes come from the locked wheel. Process disclosure: Git Bash path conversion broke the Builder's sparse-checkout pattern in its scratch clone, which briefly held `evidence/`; one `ls …` piped to `head -2` printed two names (not the protected file) and nothing was read; the clone was corrected and the repository's own `evidence/` was untouched. The Overseer re-ran verify_seed (both baselines), `check_profile --strict` (whpx) and `check_profile` (incus), the 637 tool, 42 store and 34 effects tests (all OK), compared `launch` against origin (sha `cd21566c…`, equal), scanned the range for personal data and secret-like values (none), and confirmed 0 instances and no QEMU process. | **F-04 PASS (Overseer, 2026-11-07)** for `strong-windows-qemu-whpx`: F-04.1 and F-04.2 together show one native conversation created, inspected, stopped and recovered, with the reported Docker runtime and the effective mounts matching policy. Qualifications: state retention is proven on an empty event log; the containment deviations above are carried forward, not resolved; the strong tier stays not operational (C6) until S-02.x passes. |
| S-01.1 Inventory principals and protected assets | **PASS (2026-11-07)** | `de4088e` | [`security/README.md`](../security/README.md) (trust-domain table, asset inventory, credential requirements) and the machine-readable [`security/inventory.json`](../security/inventory.json): 9 trust domains, 17 principals, 20 credentials, 35 assets, 34 privileged operations (6 Owner-only), 16 findings. `tools/check_security_inventory.py` (Task `security:check`, 50 tests) enforces the acceptance mechanically: every privileged operation names exactly one existing principal; no agent-controlled principal holds, manages or can read a credential of owner, admin, executor or management authority; no Owner-only operation uses an agent-reachable credential; only the Owner and the Owner's account carry Owner authority; every reference, file link, blueprint anchor and plan id resolves; status is a closed set (observed needs evidence, planned needs sources, unknown needs a finding). The Builder disabled each of 15 rules in scratch copies and each broke at least one test. Planned and observed are kept apart: each principal carries `identity.planned` and `identity.observed`, and each operation its accountable `principal` and, separately, its `observed_performer` (for example, conversation creation belongs to the planned management dispatcher; today the Owner's account performs it in `conversation-smoke`). Decision 0004 clarification 5 is applied: the host-side bootstrap agents are an agent principal with `owner_authority: false` and `independently_isolated: false`, and every Owner-only operation they perform discloses the shared OS identity (`fd-bootstrap-shared-identity`, a recorded limit, not a prevention). No conflict between accepted records was found, and no credential value was found in tracked content. Carried, with the leaf that owns each: the release-signing and deployment principal is unnamed by accepted authority (`fd-release-job-principal`, unknown, placeholder `release-job-environment`) to S-01.2.1; the guest login `agent` can read the Agent Server session key, so it must never be given to an untrusted workload (`fd-guest-login-name-and-key`), the unenumerated Agent Server capability routes (`fd-agent-server-route-inventory`) and the child-conversation tool path (`fd-child-conversation-tool`) to S-01.3.1; the container network deviations, including the untested inference that containers can reach the guest's sshd and each other's inner servers over `docker0`, and the shared container/service uid (`fd-container-network-deviations`, `fd-container-shares-service-uid`) to S-01.3.x/E-01.2.2; rotation owners to S-01.2.1; the remaining unknowns (CI runner pin, Gitea 28.3.0 bot/token-scope behaviour, Owner UI access, provider authentication, Owner credential custody) to their consuming leaves. Overseer ruling on placement: the inventory lives in `security/` (descriptive security model); `policy/` stays the home of enforced permissions and controls (S-01.2.1, G-01.1), as `docs/development.md` now records. The Overseer re-ran verify_seed (both baselines), the checker (PASS), the 687 tool, 42 store and 34 effects tests (all OK), and reviewed every operation's principal and every credential's holder and readers. The README's navigation table gains a `security/` row. | S-01: not yet; S-01.2 and S-01.3 implement and test against this inventory. |
| S-01.2.1 Define least-privilege principal/token permissions | **PASS (2026-11-07)** | `05ad4ff` | Design: an Architect gate G consultation (durable authorization and credential custody), accepted by the Overseer with one amendment: the dispatcher's custody of standing bot credentials is settled by the blueprint's launcher/credential-broker clauses (`#containment-architecture`, `#authorization-qualification`, `#integration-contracts`), not an Owner item. [Decision 0007](../decisions/0007-role-token-matrix-and-revocation-contract.md), Accepted by the Overseer at completion; its Owner confirmations are pending and not needed before a Gitea instance exists. Output: [`policy/role-tokens.json`](../policy/role-tokens.json) and [`policy/README.md`](../policy/README.md), rendered from it. The matrix has 17 roles (4 agent-controlled: planner, builder, reviewer, ci-job), 8 capabilities and 1 non-role row. Every role carries an issuance and revocation contract (22 revocation rows), and target and bootstrap are kept apart. Principles: roles are grants on inventory principals, and no grant may name a principal that is not independently isolated. The host-side bootstrap agents hold `grants: []`, inherit the Owner account's reach (disclosed) and carry a sunset map: the `op-as-*` operations move to the dispatcher at S-01.3.1, effects and custody move at G-04.2.1, and Gitea administration has no installing leaf. The planner is a role on `engineering-agent` with its own bot token (`cred-gitea-bot-planner`); its path-level realization is pending the planning-artefact layout. The release principal stays unknown but is fenced: trusted side only, never CI or an agent, activation through the executor; it is carried to Q-02.4 and G-04.2.1. Revocation refuses new dispatch at once, and the dispatcher stops or contains in-flight holders and records them as exposed. Revocation receipts go to the integration store. Rotating a privileged credential is a consequential effect. `tools/check_role_tokens.py` (Task `policy:check`, 73 tests) enforces the acceptance: an agent-controlled role granted an Owner-only, executor, Gitea-administration or management operation, the merge capability, or an owner, admin, executor or management credential fails, and so does a relabelled role. It also checks coverage of every inventory operation and credential, the required denials, issuer and revoker consistency, closed statuses, and that the README equals the render. Exclusion flags are rejected. The Builder disabled each of the 35 failure codes in scratch copies; all but one unreachable code broke a test. A fuzzing pass of about 3,000 malformed values does not crash it. All 20 realization rows are `verified: false` with `verify_at` S-01.2.2: no Gitea behaviour is asserted. Inventory edits: `cred-gitea-bot-planner` added; every rotation owner set, so `fd-rotation-undecided` is removed; `fd-release-job-principal` narrowed and carried to Q-02.4 as well (fix-forward of a routing omission introduced by `de4088e`); `fd-acp-provider-auth` records that no provider credential is ever a role token. Overseer rulings: accepted the Builder's added `owner-os-account` role. It is the Owner's own account, not an agent, and keeps every inventory operation and credential covered; the agents' inherited reach is disclosed on the non-role row. Bot-token per-attempt rotation depends on unverified Gitea 28.3.0 behaviour; it is marked for S-01.2.2, and the site-admin credential must never reach the dispatcher. Plan gaps confirmed by the Overseer and routed to the Owner: no plan leaf installs or runs a Gitea instance, which S-01.2.2's Gitea denial tests and many later leaves presuppose; and no plan leaf provides the inference broker or model access. The Overseer re-ran verify_seed (both baselines), `policy:check` (including the render), `security:check` and the 760 tool tests (OK), and reviewed every agent role's grants: only `scoped` credentials. | S-01.2: not yet; S-01.2.2 issues segregated credentials and tests denial. |
| P-02.1 Map OpenSpec design references into Backlog tasks | **PASS (2026-11-07)** | `3e1aa8d` | [`integrations/planning/`](../integrations/planning/README.md): a stdlib-plus-git adapter (Task `planning:create`, `planning:resolve`, `planning:test`). It turns an `intent-driven` OpenSpec change into Backlog.md tasks only through Backlog.md's CLI (`task create --ref --dep`, then `task list/view --json` read-back), and never writes Backlog's files. Source pointer: `openspec:changes/<change>/<artifact>@<full commit>#sha256=<content digest>`, which extends the blueprint's `openspec:changes/<name>@sha` notation. `resolve` re-resolves pointers and fails visibly: `POINTER_REVISION_MISSING` (including after a real history rewrite and prune), `POINTER_DIGEST_MISMATCH` and `POINTER_ARTIFACT_MISSING`. Status ownership: the adapter issues no status option or `task edit`, and refuses status-like plan keys (`STATUS_NOT_OWNED`) and a change carrying `tasks.md` (`OPENSPEC_CHECKLIST_PRESENT`). OpenSpec 1.16.0 reports `taskTrackingConfigured: false` for the change. A live test changes a Backlog status and commits a new design revision; the pointers still resolve to the original revision, and the statuses are unchanged. Two-task fixture (`refresh-on-add` depends on `measure-delay`) on a reproducible throwaway repository (commit `8eacfa8…`), with Backlog.md's own JSON recorded, timestamps normalised and no machine paths. Tools: Backlog.md 1.55.3 (wrapper and `windows-x64` platform package) and OpenSpec 1.16.0 installed by `npm ci --ignore-scripts` from `composition/lock/npm/` in a throwaway directory; integrity equals the component lock; no lock was added and nothing is vendored (decision 0005). This repository does not adopt Backlog.md here. No durable decision is needed: blueprint `#authority` settles the ownership split. The pointer format is documented in the adapter README; if a later leaf (E-01.x, UI) binds to it, that leaf records it. Tests: 41 (36 offline with fakes, plus 5 live that skip with a reason unless `AIEH_BACKLOG`/`AIEH_OPENSPEC` are set); the Builder disabled 17 adapter rules one at a time and each was caught. Not yet verified: other hosts, Backlog's MCP surface, concurrent writers, cross-repository designs, and rollback of a partial `create` (created tasks are reported, not removed). Process disclosure: a Builder demo script redirected `LOCALAPPDATA` for a whole process tree and called the bare `python` alias, so the Windows Python install manager treated it as a fresh profile and downloaded CPython 3.12.10 from python.org into scratch. That was a network fetch outside the leaf's npm-only allowance. The Builder deleted it and fixed the demo to use the absolute interpreter. The Overseer confirmed no host change: the installed Python manager package (26.4) has been unchanged since 2026-10-10, and `python` is still 3.12.10. The tests use `sys.executable` and cannot trigger this. The Overseer re-ran verify_seed (both baselines) and the planning suite with and without the live tools (41 OK; 5 skipped offline), scanned the range, and added the planning suite to the setup commands in `AGENTS.md`. | P-02: not yet; P-02.2 reads readiness and the dependency graph. |
| P-02.2 Consume native readiness and failure states | **PASS (2026-11-07)** | `a27cb72` | `integrations/planning/planning_readiness.py` (Task `planning:readiness`; output `planning-readiness/v1`) reads Backlog.md 1.55.3's own readiness with `task list --json` and `task view --json` only. That covers `isReady`, `readiness.{isReady,isBlocked,blockingDependencies,missingDependencies}` and the `dependencyGraph` node `state` (`resolved`/`missing`/`ambiguous`), all observed live. It recomputes nothing and reads no status. Each task is reported eligible or ineligible with Backlog's own reasons: `BLOCKED_BY_DEPENDENCIES` and `NOT_READY` exit 0; `MISSING_DEPENDENCIES`, `READINESS_UNKNOWN` (absent or malformed fields), `READINESS_INCONSISTENT` (Backlog's fields disagree) and `POINTER_*` exit 1 with a `FAIL <id>` line. A duplicate-id board fails the read. Fixtures recorded from Backlog's own JSON, built only with the Backlog CLI and git: `blocked` (TASK-2 waits on TASK-1), `unblocked` (the test, as Backlog owner, marks TASK-1 Done; the adapter writes no status) and `missing`. In each stage the adapter's eligible set equals Backlog's own `task list --ready`. Observed upstream behaviour: Backlog refuses `--dep` on a nonexistent id, and archive/delete/demote remove the reference. A missing reference arises from a branch merge after the dependency was deleted on `main`, which is reproduced in the `missing` fixture (TASK-3 ineligible, node `state: missing`, exit 1). Tests: 56 planning tests (13 new offline, with a trap that fails on any `status`/`completed` read, plus 2 new live). The Builder disabled each of 11 readiness rules one at a time and each was caught. Overseer ruling: accepted that a task without a resolvable OpenSpec pointer is never eligible (`POINTER_ABSENT`; `--no-pointers` opts out). This fails closed, and whether provenance-free tasks may be dispatched is carried to the dispatch-policy leaves. Not yet verified: other hosts, concurrent edits (the read is a list plus per-task views, not atomic), `check_active_branches` on, the ambiguous, archived and demoted cases as fixtures (live probes only), and Backlog's MCP surface. The Overseer re-ran verify_seed (both baselines), the planning suite live (56 OK) and offline (OK, 7 skipped), and the 760 tool tests (OK), checked that the module reads no `status`/`completed` field and inspected the `missing` fixture verdict. | **P-02 PASS (Overseer, 2026-11-07)**: blocked dependencies stay blocked until Backlog's own status change; missing references fail visibly (`MISSING_DEPENDENCIES`, `POINTER_*`, Backlog's own refusal of unknown `--dep`, and the read failing on duplicate ids); and OpenSpec carries no implementation checklist (`tasks.md` refused, `taskTrackingConfigured: false`, from P-02.1). Qualification: Backlog.md is exercised on fixtures in throwaway repositories; this repository does not yet adopt it for its own Work. |
| P-03.1 Specify typed lineage IDs and source resolution | **PASS (2026-11-07)** | `5cf8ddd`, `922cfbc` (objective kind, after a gate B consultation) | [`integrations/lineage/`](../integrations/lineage/README.md) (Task `lineage:test`, `lineage:schema`, `lineage:resolve`). `lineage_schema.json` (`lineage-reference-schema/v1`) gives each kind an explicit authority (per blueprint `#authority`), a stable native identity and a revision anchor. Required pinning: design, commit, review, CI and authorization. Optional pinning: conversation, message, objective, work, attempt and effect-receipt. It also lists non-authoritative records so they are never treated as authorities. The canonical text forms (`conversation:`, `outcome:`, `openspec:` (the P-02.1 pointer, unchanged and reused by import), `backlog:`, `openhands:conversation/`, `git:`, `gitea:`, `effect:`) round-trip exactly. Native ids are percent-encoded, commits are full ids only, and every kind except `design` also fits the intent-record/v1 reference grammar. Message span anchor `#span:<start>+<length>:sha256:<hex>` over the stored UTF-8 bytes, carrying Overseer decision D2 from P-01.2: a quote whose U+00A0 became U+0020 gives `digest-mismatch`. The extraction itself is left to U-02.x/P-03.2. Resolver interface: every answer is `resolved` (with the observed revision and digest) or an explicit `missing`, `revision-mismatch`, `digest-mismatch`, `authority-unavailable`, `unsupported-kind` or `ambiguous` with a stable code; `bool()` on a resolution raises. `resolve` answers the pin, and `current` answers the authority's current revision. Implemented resolvers: design (P-02.1), work (Backlog's own JSON, including at a pinned commit via `git archive`), commit (git), effect-receipt (effects-store chain and events, on fixtures; `missing` is not evidence of non-occurrence, per 0004) and objective. Declared `authority-unavailable`, each naming the leaf that supplies its authority: conversation, message, attempt, review, CI and authorization. Release and catalog are `unsupported-kind` (not settled; owned by the R-, A- and K- leaves). **Objective:** the Builder stopped and marked it unknown, because no record assigned an outcomeId. An Architect gate B consultation settled it. [Decision 0008](../decisions/0008-outcome-identity-assignment-form-and-record.md), Accepted by the Overseer: a lower-case UUID v4 minted once when an Objective item's acceptance is recorded, declared in the declaring change's `.openspec.yaml` under `x-outcomes` as `{item, acceptance}`, and resolved from git objects across `changes/` and `changes/archive/` with a cross-check against the accepted intent-record item. An amendment keeps the id. Shown live with OpenSpec 1.16.0: `validate --strict` passes with `x-outcomes`, and `archive` leaves `.openspec.yaml` byte-identical; the outcome resolves at both the archive path (current) and the original path (pinned). Tests: lineage 78 (5 live). The Builder's rule-disabling runs caught 125 of 128 mutations for the base rules (3 equivalent) and 39 of 41 for the objective rules (2 equivalent). Recorded, unrelated to this leaf: two `test_guest` exchange tests and publication-gate test 7 fail with git `Filename too long` when TEMP is a very deep directory, because `guest.run_git` builds a clean git environment without `core.longpaths`. They pass under the default TEMP. Carried: after `openspec archive` a design pointer's `current()` answers `POINTER_ARTIFACT_MISSING` because the path moved, which the P-03.2 traversal must distinguish from gone; supersession (K-03.3.2); a lineage kind for `decision:` acceptance references; live effects-store resolution (custody; G-04.2.x); Dulwich instead of the git executable (`#integration-contracts`, not acted on). Plan gap routed to the Owner: no leaf builds the acceptance recorder (mint, declare and commit an outcome on acceptance). Until one exists, acceptances are recorded by hand in the 0008 form. The Overseer re-ran verify_seed (both baselines), the lineage suite live and offline, the planning suite live, the schema check and the 760 tool tests under the default TEMP (all OK), and scanned the range. | P-03: not yet; P-03.2 builds the traversal and its changed-SHA and missing-node tests. |
| P-03.2 Project end-to-end lineage with broken-link semantics | **PASS (2026-11-07)**; statement and attempt nodes on labelled sample authorities | `60c7a2c` | `integrations/lineage/lineage_trace.py` (Task `lineage:trace`, `lineage:example`) projects `lineage-projection/v1`. Each node records its reference, kind, authority, `authority_mode` (`authoritative`, `sample` or `unavailable`), pinned and current resolutions, and freshness (`current`, `superseded`, `moved`, `moved-changed`, `gone` or `unknown`). Each edge records `provenance`, the records that assert it with their revision. The verdict is `complete` only when there is no uncertainty, from a closed list of reasons. Starting from an outcome id, the traversal follows: the statement (through the objective's `source`/`acceptance`, with a span anchor built from the quote and verified, carrying D2); the objective (decision 0008); the design (the declaring change's P-02.1 pointers); Backlog tasks (their own `references` from `task list --json`, reading only `id` and `references`, because Backlog has no reverse index); and the attempt (an integration-store reservation's `workRef`/`outcomeRef`, operation key and event, giving `openhands:conversation/<id>`). Examples: [`projection-sample-authorities.json`](../integrations/lineage/examples/projection-sample-authorities.json) has 13 nodes and 14 edges, with 9 authoritative and 4 sample nodes; its verdict is incomplete with 4 `sample-authority` uncertainties. [`projection-real-registry.json`](../integrations/lineage/examples/projection-real-registry.json) has the same graph, with the 2 statement and 2 attempt nodes `authority-unavailable`. Negative fixtures each give explicit uncertainty, tested: design or objective amended after pinning (`superseded`); a missing pinned commit; a digest mismatch; D2 span and quote mismatches (`SPAN_DIGEST_MISMATCH`, `QUOTE_NOT_IN_SOURCE`); missing statement, task, attempt and outcome; ambiguous outcome; a task without an attempt (`missing-link`). Moved and gone are distinguished after `openspec archive` (`moved` when the same bytes are under `changes/archive/<date>-<change>/`, otherwise `moved-changed` or `gone`; shown live). Read-only: the integration store is opened `mode=ro` with `query_only` and no migration (database bytes and dump unchanged; SQLite's own `-wal`/`-shm` sidecars may appear, which the Overseer accepts as not modifying the store). Git runs only `rev-parse`, `cat-file`, `ls-tree` and `archive`; Backlog runs only `task list`/`view`; OpenSpec never runs. A trap test fails if any Backlog field other than `id`/`references` is read. Overseer rulings: (1) the reservation intent keys `workRef`/`outcomeRef` follow the blueprint's illustrative correlation receipt (`#integration-contracts`) and are an interface the dispatcher (E-01.x) must honour; (2) `moved` with identical bytes counts as uncertainty (the conservative reading), and its severity is carried to the consumers E-02.1 and U-04.1. Tests: lineage 134 (live `LiveTrace` included). The Builder's mutation check caught 78 of 82, the other 4 being equivalent. Not yet verified: live statement and attempt authorities (U-02.x, E-01.x), a real dispatcher's reservation, a live integration store at its trusted location, tasks absent from `task list` (archived), the acceptance recorder, other hosts. The Overseer re-ran verify_seed (both baselines), lineage live (134 OK) and offline, planning live, store, effects and the 760 tool tests under the default TEMP (all OK), checked that the example rebuild leaves the tree unchanged, and inspected both projections' authority modes and verdicts. | **P-03 PASS (Overseer, 2026-11-07), qualified:** an objective is traversed from the original message through design and task to the attempt with provenance on every edge, and a changed SHA, missing, moved or ambiguous source yields explicit uncertainty. Objective, design and task resolve against real authorities (git, OpenSpec records, Backlog.md). The statement and attempt nodes rest on labelled sample authorities and are `authority-unavailable` under the real registry until U-02.x and E-01.x supply them. |
| U-01.1 Establish Owner host navigation and identity shell | **PASS (2026-11-07)**, jsdom and build; real-browser rendering not yet verified | `31fc6de` | [`apps/owner-host/`](../apps/owner-host/README.md), a new planned home recorded in `docs/development.md` (Task `owner-host:install`, `typecheck`, `test`, `build`; component tier, Node 24 and npm 11, kept out of the basic `setup`/`test`). It is a React 19.3.1 app on react-router 8.5.0 with routes `/chat`, `/work`, `/engineering`, `/` (redirects to chat) and a not-found page inside the shell; every route renders in `OwnerShell`, so navigation and identity stay mounted. Wide and narrow layouts switch at 900 px through `matchMedia`. Chat uses assistant-ui 0.15.32's own primitives over a model-free local runtime (empty thread, composer disabled, no invented replies). Work shows empty Objectives and Work surfaces that say nothing is connected. Identity: a random session UUID in `localStorage`, the same on every route and after a reload, holding no credential. The Owner UI's authentication stays open (`fd-owner-ui-access`). Agent Canvas 1.36.0 mounts lazily in the engineering area with no Agent Server and no network, which answers the compatibility matrix's open row "Canvas and assistant-ui in one React app" as compatible for mounting. Evidence: a single copy each of react, react-dom, react-router, zustand and framer-motion; no bundle collisions; all 3,459 Canvas style rules scoped under `[data-agent-server-ui]`. Dependencies: the component lock's exact versions for every shared package, plus the minimal toolchain (Vite 8.3.6, plugin-react 6.2.1, Vitest 5.1.0, jsdom 31.0.0, Testing Library, TypeScript 7.0.2; all MIT or Apache-2.0), exact pins with integrity, installed with `--ignore-scripts`; no install script was needed. Overseer rulings: (1) accepted `i18next` 26.5.11 (Canvas's own locked version) as a direct dependency, so the host registers Canvas's exported translations instead of letting Canvas fetch them over HTTP; (2) accepted the build plugin that drops Canvas's two remote Google Fonts `@import` rules (no package patch). It is consistent with the default-deny network posture and the blueprint's offline allowance, and is reversible; reported to the Owner. Finding carried to U-01.2: Canvas 1.36.0's public exports cannot select an existing session (`useConversationId` needs an internal, unexported navigation context), and Canvas navigates to absolute `/conversations/...` paths. U-01.2 must apply the blueprint's UI-01 fallback (a standalone Canvas route) or show otherwise; a test records the failure, so an upgrade that fixes it will be noticed. Tests: 43 Vitest tests (navigation, identity across routes and reload, empty states, disabled composer, a network guard on fetch/XHR/WebSocket/EventSource/beacon after every test, layout logic, Canvas CSS scoping and mount), `tsc --noEmit` and `vite build` (Canvas is a lazy chunk). The preview was served on 127.0.0.1 only and stopped afterwards; no firewall prompt. Not yet verified: real-browser rendering at both breakpoints, Canvas against a live Agent Server, other hosts. The Overseer re-ran the type check (exit 0), the 43 tests, the build, verify_seed and the 760 tool tests, confirmed the tree clean after the build, and scanned the range. | U-01: not yet; U-01.2 connects outcome selection to the engineering-session panel. |
| F-07.1 Define and implement the managed data root and configuration contract | **PASS (2026-11-07)**; Windows host, POSIX by injection | `8a81953` (and `adb8a33`, the gate documentation) | Design: an Architect gate C/G/F consultation, accepted by the Overseer with the Owner's refinements (`assets/` as a third lifecycle category; the effects root left to the 0004 re-evaluation; in-checkout roots refused; the guest-state root stays external). [Decision 0009](../decisions/0009-managed-data-root-and-configuration-contract.md), Accepted by the Overseer at completion. [`integrations/paths/`](../integrations/paths/README.md) (`aieh_paths.py`; Task `paths:show`, `paths:init`, `paths:doctor`, `tools:install`, `paths:test`), plus `example_config.yml` (tracked) and `config.yml` (gitignored). Root: `%LOCALAPPDATA%\AIEH` (from the environment variable) or `$XDG_DATA_HOME/aieh`, or `AIEH_DATA_ROOT` (a relative value resolves against the repository root of the loaded tree, never the cwd), with `persistent/`, `ephemeral/` and `assets/`. Categories: state, gitea, installs, logs and workspaces (persistent); assets (`<kind>/<name>/<version>/` with an `aieh-asset/1` record of version, provenance, integrity and reacquisition data); cache, scratch and tmp (ephemeral). `effects_root` and `guest_state` are registered external locations, never defaulted, created or validated by the resolver. Precedence: a `config.yml` per-directory override (relative values resolve against the effective root) > `AIEH_DATA_ROOT` > the OS default; `config.yml` has no root key; `.env` is never read (dotenv evaluated, not adopted). Platform paths are hand-written (platformdirs not adopted). PyYAML 6.0.3 (hash-locked, `tools-requirements.txt`) is imported only when `config.yml` exists, so the basic tier stays stdlib-only. There are 22 stable refusal codes, each naming its remedy (drive root, profile root, root inside or containing the checkout, network volume, overlap, a secret-shaped key, an unknown key, a marker mismatch, an invalid asset record, and others), plus a read-only `realpath` check against junctions into the checkout. `resolve` creates nothing; `ensure` never creates a direct child of a volume root; `init` alone creates an Owner-named root. There is no deletion code. Adapters: the JSON contract `aieh-paths/v1`, with `sh` and `ps1` emitters (round-tripped through Git `sh` and `pwsh`). `doctor` reports the legacy defaults (the integration store and gate cache trees) and moves nothing. Tests: 36, mapped to the Owner's section 9 criteria 1-10, every test with an injected environment and anchor; run stdlib-only (`-S`, 4 yaml tests skipped and counted), with the system Python, and in a scratch tools venv (all OK); 15 of 15 mutations killed. `aieh_paths.py` is 570 lines (491 of code); the Overseer accepts this against the roughly-500 target. `tools_install.py` is separate as the contract's first consumer. Process disclosure: one `ls -d` on a non-existent sibling path, outside the Builder's allowed roots, during a smoke test; nothing exists there and nothing was created. Not yet verified: macOS and native Linux (POSIX is covered by injection only), POSIX volume-type checks, `task` itself. No component adopts the contract yet (F-07.2). The Overseer re-ran verify_seed (both baselines), the paths suite stdlib-only and with the system Python, the 767 tool tests, a CLI `show` against a temporary `AIEH_DATA_ROOT` (it created nothing), and the scan. | F-07: not yet; F-07.2 adopts the contract and plans the migration. |
| F-06.1 Run pinned Gitea on host loopback under the managed data root | **PASS (2026-11-07)**; the Owner's first sign-in and the credential finish step are pending | `acbea9a`, `f116a49` | [Evidence](F-06.1-gitea-loopback.md); [`integrations/gitea/`](../integrations/gitea/README.md) (Task `gitea:install`, `gitea:up`, `gitea:down`, `gitea:status`, `gitea:verify`, `gitea:identities`, `gitea:finish-first-login`). Pin: Gitea 28.3.0's Windows binary, published as `gitea-28.3.0-windows-amd64.exe` (sha256 `4003c068…ee06`). The GitHub release asset digest (release immutable), the upstream `.sha256` on GitHub and the `.sha256` on dl.gitea.com agree, and the `.sha256` files are byte-identical. It is recorded in `composition/lock/components.lock.json`, `candidates.json` and compatibility matrix 2.7. First real creation of the managed root: `%LOCALAPPDATA%\AIEH` by the resolver's `init`. The binary is an asset (`assets/release-binaries/gitea/28.3.0/` with an `aieh-asset/1` record); state is in `persistent/gitea/` (configuration, SQLite, repositories), with logs in `persistent/logs/gitea/` and temporary files in `ephemeral/tmp/gitea/`. Gitea always runs with explicit work, custom and config paths. Nothing is in the checkout. `app.ini`: `HTTP_ADDR=127.0.0.1`, port 13300; SSH off; registration disabled; sign-in required to view; offline mode; install lock; mailer, update checker, federation, OpenID, OAuth2 provider, Actions and LFS off; secrets from `gitea generate secret`. Lifecycle: a detached supervisor (the Owner's account) creates a Job Object with KILL_ON_JOB_CLOSE (flags `0x2000`, no breakaway) and starts Gitea inside it. A clean `down` (`gitea manager shutdown`) and a hard kill of the supervisor both end Gitea (0.031 s), leaving no listener. No firewall or UAC prompt. Identities, per the Owner's decision (resolving 0007 Owner confirmation 1): `aieh-site-admin` (administrator) and `aieh-owner` (not an administrator), created by Gitea's CLI with `--random-password` and `--must-change-password=true`. The CLI output is captured in memory and written through `CredWriteW` into two temporary Windows Credential Manager entries. No password was printed, logged, committed or put on a command line, and neither password is in the managed root or the checkout. The first-login procedure and the finish step (it verifies the forced change, deletes both entries and checks no copy remains) were qualified end to end on a disposable instance with an in-memory credential store. Proofs (`gitea:verify`, all true): the binary hash equals the pin (hashed through a write-, rename- and delete-blocking handle); every Gitea listener is on `127.0.0.1` (13300, plus Gitea 28's own egress-policy proxy on a kernel-assigned loopback port, which answers 407); the token is not elevated (limited, medium integrity); resolver paths lie outside the checkout; sign-up is refused (POST 403; the page reads "Registration is disabled"); all 7 anonymous API routes probed return 403; no Gitea secret is in the checkout. Inventory: `gitea-server`, `cred-gitea-admin` and `cred-gitea-owner-account` are observed. `fd-bootstrap-shared-identity` now states that same-account processes, including host agents, can read `app.ini` and the database and so forge or take over Gitea sessions, while the final passwords exist only as Gitea's hashes. Tests: gitea 41 (plus 1 live lifecycle test, run). Process slips disclosed: one listing of the repository root, and one probe in `/tmp` (deleted). Carried: `policy/role-tokens.json` and the `gitea-site-admin` principal still say Gitea is not installed (to update at S-01.2.2); the supervisor runs from the source checkout until an installed distribution exists. The Overseer re-ran verify_seed (both baselines), the gitea suite, `security:check` and `policy:check`, and `gitea:verify` against the live instance (passed). It confirmed the processes and their listeners (`127.0.0.1:13300` and `127.0.0.1:56567`, both owned by the Gitea process inside the supervisor's job), the sign-up page text, the 403 on anonymous API access, and the scan. | F-06: met for the Gitea host and filesystem contract. The pending Owner sign-in completes the identity setup; S-01.2.2 is now unblocked. |
| S-01.2.2 Issue segregated credentials and test denial | **PASS (2026-11-07)**; executor denial is not applicable until G-04.2.1 | `6c75a90`, `a899fe6`, `63e2628` (F-06.1 fix-forward: automated finalization), `ffb6516`, `c1a4e8a` (sign-in fix), `559023d` | [Evidence](S-01.2.2-segregated-credentials.md). Bots `aieh-bot-planner`, `aieh-bot-builder`, `aieh-bot-reviewer` and `aieh-bot-verifier`: Gitea Bot type, `--restricted`, non-admin, no password; tokens `write:repository` (planner, builder, reviewer) and `read:repository` (verifier), minted by the CLI with `--raw`. Custody: Windows Credential Manager entries `AIEH Gitea bot <role>`, behind a new `CredentialProvider` interface (a Windows implementation now, ready for a cross-platform provider); `owner-os-account` is the bootstrap performer. The bot-role reader refuses the site-admin and Owner entries. **F-06.1 finalization, live:** both human accounts received a random final password through Gitea's own forced change (login, `/`, the change form, change). The final password was stored before the change; the temporary password is rejected and the final one valid; `is_admin` is true for the site admin and false for the Owner; the temporary entries are deleted; and a scan of the managed root (including logs), the checkout and the report found no password. Every site-admin token was deleted right after the change: a fixture token left by the Builder's first attempt (inert while must-change was set) and two remediation probes. A probe answered 403 before and 401 after, so the exposure is remediated. **Fixture** (applied as the site admin with the password in memory only, no admin token): private `aieh-authz-fixture/authz`; `main` has no push or force-push, merges by `aieh-owner` only, the admin override blocked and one reviewer approval required; `work/*` is pushable by the builder and planner only; `**` by nobody. **Live authorization suite** (`task gitea:authz`, 18 tests, 284 probes, every bot on every row; Overseer rerun: 18 OK, the executor test skipped). Allowed: reading and cloning, `work/*` push and PRs (builder, planner), an approving review (reviewer), verifier reads. Refused: interactive sign-in, `/admin`, other users' tokens (including minting via basic auth), other users' data, `sudo`, `X-WEBAUTH-USER`, creating repositories or organisations, secrets and variables, merge, force-merge and squash into `main`, push, force-push and delete of `main` or non-`work/*` branches, protection, settings, collaborators, hooks, deploy tokens, transfer and delete; and the site admin's own merge (405). Open questions answered: review needs `write:repository` (the read scope is refused); `--restricted` hides non-collaborated repositories; the site admin can revoke another account's token. Recorded limit `fd-gitea-reader-opens-pr` (no review-only scope; a read collaborator can open a PR), carried to D-01.2. Neither gap reaches an Owner operation. Realizations verified: 5 of 20; the others are partial, carried or unknown with reasons. Bootstrap limit (decision 0010): processes running as the Owner's account can read the Credential Manager entries and can use Gitea's CLI to mint tokens for any account. The Overseer re-ran verify_seed (both baselines), the 767 tool tests, the gitea suite (72), the live authorization suite (18), `security:check` and `policy:check`, and scanned the range. | **S-01.2 PASS (Overseer, 2026-11-07)**, qualified: agent, reviewer and verifier tokens cannot perform an Owner or administrator operation, instance-wide or on a protected repository, and no token store or managed-root path reaches agent workspaces in the guest. Executor operations cannot be invoked by anyone because no executor exists; G-04.2.1's proof ("agent and CI principals cannot invoke or impersonate the executor") carries that obligation. |
| S-01.3.1 Restrict management API admission | **PASS (2026-11-07)**; on a disposable guest, no dispatcher yet | `da58a33`, `d208de1` | [Evidence](S-01.3.1-management-api-admission.md). Route inventory `profiles/strong-windows-qemu-whpx/agent-server/routes.json` (pinned in the profile): 193 routes, 170 operations from the live `/openapi.json` plus 4 documentation routes and 19 found only in the locked release binary (sha256 rehashed; read as data, never run; the locked wheel and `openapi.json` named in the dispatch are not on the host and nothing was downloaded); classified 10 public-read, 12 management-read, 171 privileged; the `dispatcher` field is the dispatcher's own allowlist, not a server control. Admission: the Agent Server session key on every `/api` router and first-message WebSocket auth; a seeded `ExecStartPre` key check makes the server fail closed (upstream treats an empty key list as unsecured); the `AIEH-CONTAINER-GUARD` chain (IPv4 and IPv6, `docker0` and `br-+`) refuses new connections from containers to the guest, `docker.service` requires it, and `icc` is off; all installed by seeded provisioning and verified by the root step and `inspect`. **Live proofs** (fresh guest `s0131-a`, then again after a guest restart): every key-gated route 401 or 403 or closed 4001 without a key or with a wrong key, and no 2xx; the app-backend proxy inert (503); the trusted side with the key 200/201; from inside two conversation containers the management listener, `sshd`, LLMNR and the peer container are refused or unreachable at every address (before the controls `sshd`, LLMNR and the peer were reachable); `start_child_conversation` reaches only the conversation's own inner server with its own key, and the inner key reaches nothing outside. Session-key custody stated: only the Owner's account, through `guest.py` as the operator login, reads the key; no workload has that login. The profile `launch`, `network` and `host_shares` blocks are unchanged (sorted-JSON digests compared by the Overseer). **Overseer rulings:** the binary-plus-live route source accepted (both locked or observed, and they agree exactly); the Incus seed-template pin change accepted (shared template, as at F-04.2); P6/P7 contract text not amended now, since the guard changes no listener; the proposed dedicated key-file group deferred to E-01.2.2, where the dispatcher's sole custody is due, since it changes the P5 contract and no dispatcher exists yet. Carried: `fd-child-conversation-tool` (E-01.2.2), `fd-guest-login-name-and-key` (S-01.3.2, E-01.2.2), container NAT path and request caps (S-01.3.2, S-01.4, E-01.2.2, S-02.1), `fd-owner-ui-access` (S-01.4). Unrelated, detected: a 137-character fixture path under `tools/tests/fixtures/intent_qualification/` exceeds the Windows path limit in a deep clone (carried to F-09). Overseer verification at `d208de1`: verify_seed (156) and `--baseline seed` (136) PASS; `check_profile --strict` PASS for the Windows profile (the Incus profile's 4 unresolved pins are unchanged from `091a7d6`); `security:check` and `policy:check` PASS; tools 794, store 42, effects 34, planning 56, lineage 134, paths 36 and gitea 72 tests OK with the default TEMP; the gate history scan of the range PASS; 0 guest instances and no QEMU process. | S-01.3 is evaluated at S-01.3.2 (the last slice). |
| S-01.3.2 Remove container daemon and management access from jobs | **PASS (2026-11-07)**; on a disposable guest; CI not applicable yet | `881e728`, `d2652d0` | [Evidence](S-01.3.2-job-daemon-and-management-access.md). Job environment (the per-conversation containers) inspected read-only and from inside: the locked wheel's container creation (hash matches the lock) sets `--user 999:989`, `--cap-drop ALL`, `no-new-privileges`, exactly three bind mounts under the guest scratch path and resource caps; Moby defaults give no privileged mode, devices or host namespaces, builtin seccomp and AppArmor `docker-default`; inside, every capability set is 0, `NoNewPrivs 1`, `Seccomp 2`, no socket file, and root is not obtainable (`sudo` refused by no-new-privileges, `su` fails). Hardening: the server's only fitting option `enable_browser: false`; the job profile declared as data (`provisioning.agent_server.jobs`: container settings, 10 engine socket paths, engine ports, the SLIRP host addresses, a credential-file pattern, the CI constraints), validated by `check_profile` and enforced on every container by `inspect`, hence by `conversation-smoke` and `admission-probe`; Moby `required_security_options` names the four daemon defaults the jobs rely on. Profile `launch`, `network` and `host_shares` unchanged (digests compared by the Overseer). **Live** (`job-access-probe`, guest `s0132-a`, before and after a guest restart, from two containers): all 10 engine socket paths `ENOENT`; engine ports 2375/2376, the management port and the published ports refused at every guest address; at the SLIRP host alias `10.0.2.2` the engine ports, the instance SSH and QMP ports and the host Gitea port refused; the peer container times out; all 193 routes refused at every address, without a key and with the conversation's inner key; control: the container's own inner server 200. Token search (about 39,300 readable files and every readable process environment, by name and fingerprint, never by value): no outer session key or `OH_SECRET_KEY` fingerprint, none of the eight S-01.2.2 bot token fingerprints (sourced from the committed evidence; no credential store read), no credential file name; control: the conversation's own key found. `admission-probe`, `conversation-smoke --restart` and `inspect` PASS on the same guest. Fail closed: without the container guard Moby does not start, and without a valid key the server does not start (observed at S-01.3.1); the absence of the socket follows from the hash-verified binary's fixed mounts and is enforced by `inspect` on every container. New limit `fd-job-image-engine-clients` (the image ships engine clients and setuid `sudo`/`su`, inert today; carried to S-02.1 and E-01.2.2). CI: no runner exists; its four constraints (no engine socket or endpoint, no management, Owner, admin or bot token, not privileged, no host path beyond the scoped workspace) are recorded as planned and unverified, carried to Q-02.2.1, Q-02.2.2 and Q-02.3.2. **Overseer rulings:** no contract text amendment now (the P6/P7 wording on the job environment goes with the S-01.4 network matrix); the `planner` role shares the builder's job environment, and its verified row waits for the planner's own dispatch; the key-file group stays deferred to E-01.2.2. Overseer verification at `d2652d0`: verify_seed (156) and `--baseline seed` (136) PASS; `check_profile --strict` PASS; `security:check` (16 findings) and `policy:check` (24 rows, 8 verified) PASS; tools 818, store 42, effects 34, planning 56, lineage 134, paths 36 and gitea 72 tests OK with the default TEMP; gate history scan of the range PASS; no personal path in the range; 0 guest instances and no QEMU process. | **S-01.3 PASS (Overseer, 2026-11-07)**, qualified: agent-side requests to privileged Agent Server routes and to container-management sockets fail closed for the job environments that exist (the conversation containers), observed in one evidence run covering both halves; admission is enforced by the session key and the fail-closed key check (S-01.3.1) and by the container guard. The CI side is not applicable until a runner exists; Q-02.2.1, Q-02.2.2 and Q-02.3.2 carry the obligation (Q-02.3.2's proof includes the engine-socket attempt). S-01 is preserved, not closed (S-01.4). |
| S-01.4 Apply deny-by-default inter-domain communications | **PASS (2026-11-07)**; on a disposable guest and the Windows host; the planned edges are recorded, not built | `d084b8d`, `8cea7fb`, `bb72b8b` (fix-forward), `ecd3bf5` | [Evidence](S-01.4-network-matrix.md). Design: an Architect gate C/G consultation, accepted by the Overseer with rulings (no Windows Firewall rule; a container egress guard; the git plane by exchange; P6/P7 amended); [decision 0013](../decisions/0013-owner-ui-session-access-and-management-key-custody.md) (the Owner UI never holds the management key; it uses a per-conversation runtime credential issued by the dispatcher; every host-to-guest forward is an Owner act at the leaf that needs it; the same-account scope applies on the host network plane; untrusted code has no path to Gitea, and the dispatcher pushes as the bot), Accepted by the Overseer at completion. `policy/network-matrix.json` with `tools/check_network_matrix.py` (Task `policy:network-check`): all 81 ordered pairs of the 9 trust domains plus 10 external edges, each classified (allow 28, deny 74, disclosed 6; observed 55, planned 46, decided 7; 9 Owner acts, the 3 observed ones citing their approvals). Deny by default is checked mechanically: every pair has a row, every allow from untrusted code names a P7 class and never a management or credential asset, and every allow names a prevention mechanism. Seeded container egress guard (`AIEH-EGRESS-GUARD` from `DOCKER-USER`, IPv4 and IPv6, empty allowlist; installed before Moby, which requires it) and a read-only, unelevated host census (`guest.py host-census`): every harness listener on 127.0.0.1, 643 firewall rules unchanged before, during and after, no prompt. **Egress proof:** the first sweep FAILED the rule fixed before it ran (off-link targets got ENETUNREACH from the routing table, so the guard never saw them; no connection was made). The Overseer ruled that the FAIL stands, and ordered a better experiment: a route-present falsification (a validation-only, flag-gated root unit adds a temporary default route via the SLIRP gateway in the disposable guest; SLIRP `restrict=on` unchanged). With the route present, every off-link TCP and UDP attempt from both jobs was refused by the guard, its counters rose exactly (+4 tcp-reset, +2 reject), each log line showed the uplink, and the route was removed and verified gone; identical before and after a guest restart. On-link targets (the SLIRP host alias with the SSH, QMP and Gitea ports, DNS, an unconfigured guestfwd address) were refused by the guard in every run. Also in the same runs: `admission-probe`, `job-access-probe`, `conversation-smoke --restart` and `inspect` PASS. Findings: `fd-container-network-deviations`, `fd-host-loopback-exposure` and `fd-owner-ui-access` become limits; new `fd-owner-ui-session-plan-silence` (U-01.2, P-04.2); the CI runner and CI job paths to Gitea are recorded as denied, carried to Q-02.1 and Q-02.2.1. The profile's `launch`, `network` and `host_shares` blocks are unchanged (digests compared by the Overseer). Overseer verification at `ecd3bf5`: verify_seed (156) and `--baseline seed` (136) PASS; `check_profile --strict` PASS; `security:check`, `policy:check` and `policy:network-check` PASS; tools 867, store 42, effects 34, planning 56, lineage 134, paths 36 and gitea 72 tests OK with the default TEMP; gate history scan of the range PASS; no personal path; 0 guest instances and no QEMU process. | **S-01 PASS (Overseer, 2026-11-07)**, qualified: an agent controlling its own workspace cannot invoke privileged conversation creation (every privileged route is refused from the job side at every address, with or without its own key; S-01.3.1, S-01.3.2, re-observed here) and cannot reach Owner, admin, bot or management credentials (no engine socket or endpoint, no host or Gitea path, no credential found by name or fingerprint; egress denied by the guard). The sole custody of the management key by a dispatcher is decided (0013) but not realized, since no dispatcher exists: E-01.2.2 and E-01.3.2 verify it. The CI side is carried to Q-02.2.x and Q-02.3.2; the executor to G-04.2.x. |
| S-02.1 Implement repeatable sandbox denial probes | **PASS (2026-11-07)**; probes validated on one disposable guest (probe validation, not the S-02.2 acceptance run) | `dc5018a`, `34f552c` | [Evidence](S-02.1-containment-probes.md). A versioned case catalogue, `security/containment-cases.json` (v1, rendered in `security/README.md`): 111 cases in 7 categories (file, sibling-workspace, secret, socket, egress, privilege-expansion, management-api): 76 denial, 14 hardening, 2 deviation (no `--network none`; `host.docker.internal`, each passing only while its compensating cases pass) and 19 permitted controls. Every non-permitted case names an enforcement location from a closed set of 18, with references that resolve to P-ids, `nm-*` matrix edges or inventory ids, and a permitted control that must pass in the same run. `tools/check_containment_cases.py` (Task `security:containment-check`) enforces coverage, resolution, controls, a closed set of provably non-destructive operations, profile-derived paths, a mutation per category, no machine paths and the README render. Runner `guest.py containment-probe` (refuses a catalogue that fails its checker; reuses `admission-probe` and `job-access-probe` unchanged; per-case records with attempt, principal, observations, classification, control verdict and runtime snapshot: guard counters, `daemon.json`, SecurityOptions, docker-inspect digests and pins). A failed control makes its cases UNKNOWN, a missing hardening control or an unexpected observation is FAIL, an unexpected success is FAIL and stops the run. **Validation** (guest from a clean checkout at `dc5018a`, `--egress-falsification --canaries`): 111/111 PASS before and after a guest restart, every verdict, classification, docker-inspect digest and pin identical; all jobs 999:989. A pre-commit shakedown showed the no-downgrade rule working: two defective controls of the Builder's own made their probes UNKNOWN, not PASS; fixed before commit. **Sensitivity:** offline, a would-be success is classified FAIL in every category (26 runner tests on the real primitives against a fake guest, plus UNKNOWN on a failed control, FAIL on a missing hardening control, a missing egress-falsification flag or an unsearched fingerprint); live, 7 of 7 mutations (one per category, each pointing a denial at an operation the job is allowed) were classified FAIL in both runs, with no guest control weakened. Findings: `fd-container-shares-service-uid` narrowed (uid 999 can write only its own three binds; no sibling path or foreign process reachable) but kept open-risk: the job can rewrite its own conversation's stored state that the outer server reads, untested because the test changes state; `fd-job-image-engine-clients` and `fd-container-network-deviations` re-tested; all three carried to S-02.2. Overseer verification at `34f552c`: verify_seed (156) and `--baseline seed` (136) PASS; `check_profile --strict` PASS; `security:check`, `security:containment-check`, `policy:check` and `policy:network-check` PASS; tools 926, store 42, effects 34, planning 56, lineage 134, paths 36 and gitea 72 tests OK with the default TEMP; profile `launch`, `network` and `host_shares` digests unchanged; gate history scan of the range PASS; no personal path; raw records re-tallied (111 PASS per run, no verdict difference); 0 guest instances and no QEMU process. | S-02 is evaluated at S-02.2 (the last slice). |
| S-02.2 Execute probes and record actual isolation evidence | **PASS (2026-11-07)**; the agent side, on a disposable guest; CI out of scope | `cbee89a`, and this commit (finding records) | [Evidence](S-02.2-isolation-evidence.md). The acceptance run of the S-02.1 suite (catalogue v1, 111 cases) on one fresh guest from the clean commit `111e6ec` (`--egress-falsification --canaries`; create, provision, inspect, containment-probe, conversation-smoke with restart, containment-probe, inspect, destroy): **111/111 PASS in both runs**, every verdict, observed outcome, control verdict and compensating verdict identical across the restart and identical to S-02.1; the configuration (commit, profile and its three block digests, boot inputs, image, binary, `daemon.json`, SecurityOptions, docker-inspect digest) identical in all four snapshots; every job 999:989; the egress guard's refusal counters rose in each run, IPv6 counters 0; `inspect` PASS before and after (P10 UNKNOWN outside the smoke, the known XSAVE limitation). The first, wider S-02.2 dispatch (the acceptance run plus fail-closed drills that remove one guest control at a time, and a test of the job's own stored state) was stopped by the API's safety screening while the Builder was still orienting; its stray disposable guest was destroyed by the Overseer. **Owner ruling (2026-11-07):** accept S-02 qualified: the re-run is accepted as observed, and the drills and the stored-state question are carried to E-01.2.2 with `fd-container-shares-service-uid` kept open-risk. The three S-02.2-carried findings were updated accordingly (S-02.2 cited, carried to E-01.2.2). Overseer verification at `cbee89a`: verify_seed (156) PASS; `security:check`, `security:containment-check`, `policy:check` and `policy:network-check` PASS; checker tests (352) OK; raw records re-tallied (111 PASS per run, no difference; record digests match the report); gate history scan PASS; no personal path; 0 guest instances and no QEMU process. | **S-02 PASS (Overseer, 2026-11-07, by Owner ruling), qualified:** from inside the actual agent context every prohibited read, sibling-workspace access, secret search, engine-socket or engine-endpoint access, egress attempt (with and without a route), privilege-expansion attempt and management-route call is denied (76 denial cases, each with a passing control), and every hardening control is present (14 cases); failures are observable (explicit per-case outcomes and reasons, logged refusals, exact guard counters) and the profile did not change across the run. Declared, not observed here: that a missing guard or key blocks activation (the key check's refusals and the guard's `Requires=` are observed, a removal drill is not; S-01.3.1 observed the missing-guard case once), and that a failed control yields UNKNOWN rather than PASS (shown live only in the S-02.1 shakedown and in offline tests); carried to E-01.2.2 with the stored-state question. The CI side is carried to Q-02.2.x and Q-02.3.2. |
| E-01.1.1 Model reserved attempt identities and lifecycle | **PASS (2026-11-07)** on fixtures | `f176077` | [Evidence](E-01.1.1-attempt-identity.md). Migration `0003_typed_attempt_identity.sql` on the F-05.1 integration store: a STRICT `attempt_identity` table, 1:1 with `attempt`, with typed immutable columns (`work_id`, `design_revision` as `openspec:changes/<change>@<commit>`, `stage` from a lookup table `implement`/`review`, `ordinal`, profile, policy and nullable agent-manifest digests, a relative `planned_workspace` under decision 0009's workspaces category, `attempt_id`, `live`). The canonical key `attempt/v1/<work>/<change>@<commit>/<stage>/<ordinal>` is enforced against the columns by a trigger; the conversation ID stays `uuid5(CONVERSATION_NAMESPACE, key)` and `attempt_id` is `uuid5` under a new pinned namespace. **Claim rule** (Overseer ruling after the Builder correctly stopped on a brief that contradicted the blueprint's rework loop, `#execution-qualification` "Rework or pass" and "Prevent concurrent claims"): at most one live attempt per Work, design revision and stage, enforced in SQLite by an admission trigger and a partial unique index on a `live` flag that triggers keep equal to the attempt's state; a new ordinal needs every earlier one terminal (`failed` or `confirmed`) with no gap; no retry cap in the schema (policy). Pre-0003 attempts stay valid as legacy-untyped and are never rewritten; the pre-0003 canonical dump is byte-identical, so earlier backup manifests still verify. **Acceptance:** identical reservations in one process, two processes (the first hard-exiting) and 8 concurrent processes resolve to one row, one event and one conversation UUID. 31 new tests; 29 of 30 mutations caught (the miss is equivalent). Fix-forward in the same commit: the two lineage example projections regenerated by lineage's own `--record` (only `store_schema_version` 2 to 3; Overseer-authorized). Gaps recorded, not repaired: lineage cannot resolve the change-level design form and reads only `workRef` from the intent (kept); planning's `Pointer.parse` and `TASK_ID_RE.match` accept a trailing newline (unrelated-but-detected; the store guards with `fullmatch`). Overseer verification at `f176077`: verify_seed (156) and `--baseline seed` (136) PASS; tools 926, store 73, effects 34, planning 56, lineage 134, paths 36 and gitea 72 tests OK with the default TEMP; migrations 0001 and 0002 unchanged, `CONVERSATION_NAMESPACE` unchanged; gate history scan PASS; no personal path; an independent probe on a scratch store confirmed idempotent duplicates, refusal of a live second ordinal, an ordinal gap, a conflicting intent, a raw `UPDATE` of `live` and a raw second live insert, and acceptance of rework after `confirmed`. | E-01.1 is evaluated at E-01.1.2 (the last slice). |
| E-01.1.2 Test reservation crash and concurrent admission | **PASS (2026-11-07)** on fixtures, with real processes | `840cac4` | [Evidence](E-01.1.2-reservation-crash-concurrency.md). Tests only; no defect found, so the library, `storecore` and migrations 0001 to 0003 are unchanged. **Crash matrix** (19 rows, real worker processes running the real `reserve_attempt` and `transition`, crashed by `os._exit` or a kill at statement boundaries through a worker-only connection wrapper; no fault-injection seam added to the library): a crash anywhere before `COMMIT` leaves nothing (including after the identity row and before the attempt row, under the deferred foreign key, and while holding the write lock, which is released); after `COMMIT` exactly one row and its events, with the WAL left un-checkpointed. In every row the identical re-request in a new process returns the same `operation_key`, `attempt_id`, `conversation_id` and `design_revision` (`created=False` once a row exists), and the integrity, foreign-key and store invariant checks pass with no triple holding two live rows. **Concurrency** (8 processes, 20 repetitions per race): identical requests give one `created` and seven `existing`; competing ordinals give exactly one live claim, with typed refusals only (`LiveClaim`, `OrdinalOutOfSequence`); one key with 8 intents gives one `created` and seven `ConflictingReservation`; 8 triples all succeed; reserve against a freeing transition exercises both branches; no raw `sqlite3` error or `SQLITE_BUSY` escaped. Stability: 25 + 25 fresh-process iterations, no flake; 6 of 6 single-edit mutations caught. Overseer verification at `840cac4`: verify_seed (156) and `--baseline seed` (136) PASS; tools 926, store 84, effects 34, planning 56, lineage 134, paths 36 and gitea 72 tests OK with the default TEMP; the new module passed 3 further runs; gate history scan PASS; no personal path. | **E-01.1 PASS (Overseer, 2026-11-07):** concurrent identical dispatch requests resolve to one reserved key (8 processes, E-01.1.1 and here); no second concurrent claim of a Work, design revision and stage; a restart finds the same conversation UUID, attempt UUID and design revision, after a crash at every point and with an un-checkpointed WAL; a lost reply is answered by the identical request as `existing`. Qualified: proven at the store level; the Agent Server side of a lost create is E-01.4.x; power loss (`synchronous=FULL`) is not exercised by process crashes. |
| E-01.2.1 Resolve authorized source and runtime inputs | **PASS (2026-11-08)** on fixtures | `e6d348b` | [Evidence](E-01.2.1-dispatch-input-resolution.md). `integrations/dispatch/` (Task `dispatch:test`, `dispatch:check-manifest`, `dispatch:manifest-path`): a pure, trusted-side resolver. A request (`dispatch/request/v1`) names only `work_id`, `repository`, `stage`, `profile` and `catalog_pin`; any other field is refused, a path, digest, runtime or resource field as `REQUEST_OVERRIDE_FORBIDDEN`. It is checked against a schema-checked approved-input manifest (`dispatch/approved-inputs/v1`: repositories, accepted designs, profiles with their sha256, catalog pins at full commits with a manifest sha256, and bindings by repository and stage), whose live copy is resolved under the managed root's state category by `aieh_paths` and refused inside or containing the checkout (decision 0009); no live manifest written. The profile's current digest must equal the approved one and the profile must be operational; the Work must be ready by Backlog.md's own readiness; the design pointers must pin one change at the manifest's accepted commit; an approved, bound catalog pin is **required**, so every dispatch is refused until A-01.1 produces pins (intended). The resolved record carries `design_revision`, the digests, `planned_workspace` (`<repository>/<work_id>/<attempt_id>`, never a host path), a `policy_digest` over exactly the approved entries, and the manifest version and digest as provenance in the intent. 47 tests (every refusal before any reservation; determinism with a pinned policy digest; manifest checker; custody; CLI); mutation check 43 of 43 after two Builder-introduced test gaps were fixed before commit. Overseer rulings on the Builder's findings: (F1) the manifest's `designs` entry is the dispatch-time record of the accepted design revision; who writes it is carried to governance with the other manifest entries; (F2) the operational-profile requirement is accepted (both checked-in profiles are not operational, so they are refused); (F3) a class-E category for authorization records is carried to F-07.2; (F4) the attempt key has no repository component, so two repositories sharing a Work id, change and commit collide, which fails closed as `ConflictingReservation`, carried to E-01.3.x; (F5) `AGENTS.md` omits `gitea:test` and `dispatch:test`, fixed with the next change. Overseer verification at `e6d348b`: verify_seed (156) and `--baseline seed` (136) PASS; tools 926, store 84, effects 34, planning 56, lineage 134, paths 36, gitea 72 and dispatch 47 tests OK with the default TEMP; gate history scan PASS; no personal path; an independent probe confirmed override, path-shaped identifier and short-commit refusals. | E-01.2 is evaluated at E-01.2.2 (the last slice). |
| E-01.2.2 Enforce workspace and resource ceilings before create | **PASS (2026-11-09)** for `strong-windows-qemu-whpx`. Slice (a) was observed on fixtures. Slice (b), observed live, FAILED proof items (1) and (2). Slice (c), the fix forward, PASSES (1) to (3) on fresh guests. (4) was decided by the Overseer: the profile is operational. | slice a `0e051d6`; slice b `3e5d303` to `5d13615`; budgets `64542f1`; slice c `752ff74` to `eb6b6ba`; the operational flag `21c7ad1` (with the current-state documentation; three real-profile dispatch tests: Incus refused, QEMU/WHPX resolves with an approved catalog pin, and `NO_APPROVED_CATALOG` without one); budgets `cbbe693` (counters re-proposed; wall budgets kept rather than loosened, because both profiles at `21c7ad1` ran 19 to 39% slower from host drift, accepted by the Overseer) | [Slice (a) evidence](E-01.2.2a-dispatch-admission.md). **Slice (a)**, the host-side admission in `integrations/dispatch/`: `resolve → reserve_attempt → admit → send_create(transport)`. The route is fixed (`POST /api/conversations`), and the profile's pinned `routes.json` must allowlist it for the dispatcher (`fd-session-key-not-fine-grained`, dispatch side). The body is the profile's pinned create template, with only the reserved `conversation_id` substituted. It is checked against a field allowlist: `conversation_runtime` exactly `docker` and never omitted; `working_dir` exactly `/workspace`; caps only as declared, with caps × `max_concurrent_runs` within the profile ceilings, which closes the "request caps override" deviation on the dispatch side; the effective mounts exactly the declared binds, never a container-engine socket. The host workspace is resolved under the `workspaces` category; path shapes, Windows device names, other attempts' paths and links or junctions are refused, and admission writes nothing. `send_create` re-runs every check from the reserved record immediately before the transport, so a body, mount set or junction changed after admission is refused. POLICY_FORMAT v2 puts the admission policy into the reserved policy digest. 21 new refusal codes. The proof is 31 new tests: every refusal calls the transport 0 times, and each positive control calls it exactly once with the exact body (including the real `strong-windows-qemu-whpx` declaration in a throwaway copy with only `operational` flipped). Mutation check: 46 of 46 caught, after two test gaps found in round 1 were fixed before commit. **Overseer rulings:** (F3) the template is the F-04.2 disposable fixture, so a real attempt's agent, message and tags need a per-stage or catalog-derived block that admission validates; carried to A-01.x and E-01.3.x, and today every dispatch is refused anyway (no operational profile and no approved catalog pin); (F4) the golden policy digest moved with v2, as designed; (F5) device-name repository ids are now refused at admission, and the manifest schema is unchanged; (F6) `host-gateway` and the missing `--network none` are set unconditionally by the upstream registry, so they stay recorded limits (S-01.4 compensating controls); (F7) the `integrations/` layout row and the Quick start in `docs/development.md` and `AGENTS.md` still describe dispatch as input resolution only, to be fixed with the next documentation change; `fd-guest-login-name-and-key` (management key custody) is carried to E-01.3.x, which builds the dispatcher (decision 0013, R9); `fd-child-conversation-tool` is a recorded limit (a child runs inside the admitted container and its caps). **Slice (b)**, waiting behind the F-09 priority: the S-02 fail-closed drills, the stored-state question (`fd-container-shares-service-uid`), and a live check that a created container's mounts, caps and runtime equal the admitted ones. Overseer verification at `0e051d6`: verify_seed PASS; dispatch 78 tests OK; `admit` and `send_create` read.<br>**Slice (b)** ([evidence](E-01.2.2b-live-drills.md), 2026-11-09, four disposable drill guests under the extended guest authorization, all destroyed): **(1) FAIL**: the key check fails closed (two variants) and an injected defective control makes its 22 dependent cases UNKNOWN and the run FAIL, but a failing guard stops Moby and not the Agent Server, which serves its key-gated API with no Moby behind it (F-1: the server unit has `Wants=docker.service`, not `Requires=`). **(2) FAIL**: 134 of 136 single-field alterations of the job-writable stored state are inert, but `execution_status` `running` makes the outer Agent Server, the `docker`-group management principal, resume the conversation in its own process at its next start, and with a stored `workspace.working_dir` it creates and `git init`s that host path; the job can persist `running` itself (F-2: this answers the residual of `fd-container-shares-service-uid`). The created container never changed. **(3) PASS** with one stated waiver (the host account name is not sent into the guest; the agent-scope P5 scan, which searches for it, passed). **Live admitted create: PASS** (mounts, caps and runtime equal the admitted ones). **(4) not prepared.** Fixed forward within slice (b): F-3, F-4 and F-5 (each introduced-by `3e5d303`). Recorded as upstream behaviour: F-6 (a refused create leaves an empty record) and F-7 (the outer server's lease makes the inner server answer 404).<br>**Gate G consultation** (gate A secondary; the Architect, 2026-11-09), **accepted by the Overseer**: in 1.60.1 the start-up resume is unconditional, and no configuration gates it. The stored `tool_module_qualnames` are imported in the management process before any lease check; loading job-supplied code is not established, because no job-writable path is on the import path. Store separation would need an upstream change. Remedy, as fix-forward inside this leaf (exposed-by; no integrity-tracked file, plan or decision record changes): F-1 becomes `Requires=`/`After=docker.service`. A new required root oneshot, `aieh-agent-server-quiesce.service`, runs before every server start: it removes every container, then rewrites stored `running` records to `error` (upstream's own recovery outcome). The profile declares it, `check_profile` validates it and `inspect` compares it. The limit `fd-outer-server-local-recovery` is carried to decision 0001's version line, with an upstream report. **Overseer rulings:** (R1) because the step writes as root into a job-writable tree, it reads and writes only through directory-relative opens that never follow a link, and only a regular, singly linked file owned by the conversation uid. It moves aside, never deletes, any record that fails these checks or whose `meta.json` id differs from its directory name: the move goes to a root-only quarantine on the same filesystem. This adopts the Architect's optional id-quarantine action. (R2) E-01.5 must take its executing signal from the container's existence (root facts), never from the job-written stored status; carried to E-01.5. (R3) Requalification per the consultation: three guests (R1 provisioned smoke and lifecycle; R2 fail-closed and defective-control drills with the new quiesce-break variant; R3 the full stored-state run with the new F-2 variants), reopening F-04.1, F-04.2, S-01.3.1, F-03.4 and E-01.2.2(b). (R4) the slice-(b) commits left the test budget's counters failing (mkdtemp 968, budget 952: the new drill tests; introduced-by `3e5d303`, a re-proposal omitted), fixed in the next commit. Overseer verification at `5d13615`: evidence read; tools suite 1,023 OK (5 skipped); dispatch 80 OK; verify_seed PASS (164; seed baseline 136); no QEMU or SSH process left.<br>**Slice (c)** ([evidence](E-01.2.2c-fix-requalification.md), 2026-11-09, seven disposable guests under the extended guest authorization, all destroyed). **F-1 fixed:** `Requires=docker.service` (`752ff74`). **F-2 fixed:** the required root quiesce step (`dbe2096`), built to ruling R1; `profiles/strong-incus-vm` moved only its pin of the shared template. **(1) PASS:**<br>- the key check (two variants);<br>- the guard (two variants): Moby and the Agent Server are both stopped (the start job's result is `dependency`; no process, no listener);<br>- a broken quiesce step: the server does not start;<br>- defective controls: 22 UNKNOWN, run FAIL as required.<br>**(2) PASS:**<br>- 136 of 136 alterations, 0 steering; #120 and #135 are rewritten to `error` before the server starts; #10 is quarantined;<br>- the "F-2 closed" drill, with its decision rule fixed before observation: variants A (the #135 replica), B1 (the job writes and the runtime stops normally), B2 (a forced kill; the kill race is now established: the `working_dir` text survives, but there is no resume and no host path), C (the job keeps writing while the server restarts), D (idle-record retention), E (on R2b) and F (id quarantine), and G (a symbolic link and a hard link, both quarantined, the sentinel neither read nor written): all PASS.<br>**(3) PASS** on three guests, with slice (b)'s waiver. **Live admitted create PASS** on two guests. **Reopened verdicts re-observed PASS:** F-04.1 (`smoke --provision`), F-04.2 (`conversation-smoke --restart` and variant D), S-01.3.1 (`admission-probe` and the drills), F-03.4 (P9 and P10); `job-access-probe` PASS with the route-present falsification. **Findings:**<br>- F-10 (introduced-by `dbe2096`; fixed in `6d3307f`): variant E's restore did not reboot.<br>- F-14 (exposed-by; origin `d084b8d`; fixed in `8f8b335`): `inspect`'s stable egress-guard view kept per-boot times, so a provisioned smoke's start comparison would always fail.<br>- F-15 (unrelated-but-detected; upstream 1.60.1): an intermittent import race makes the server exit 1 at start (2 of 272 restarts); the retry starts cleanly. It is slice (b)'s F-5, now with a cause. Carried to the upstream report.<br>- F-12: quarantined records wait for an operator act.<br>- `security/inventory.json`: `fd-container-shares-service-uid`'s residual is answered with the compensating control; `fd-outer-server-local-recovery` is added (an upstream limit, carried to decision 0001's version line); a note for E-01.5 (ruling R2).<br>- 0006 gains a Current facts entry from the Overseer as contract owner.<br>**Overseer verification at `eb6b6ba`:** the quiesce script read (all containers removed and verified before any record is touched; every open is directory-relative with `O_NOFOLLOW`; owner, link count and inode are re-checked after open; a moved-aside record is renamed, never deleted, into a root-only `0700` quarantine on the same file system; any other failure exits 1); the guest-side declarations are unchanged between R3's commit `dbe2096` and `eb6b6ba` (only `QUALIFICATION.md` text); tools suite 1,043 OK (6 skipped; the POSIX-only directory-relative test skips on Windows and is proved live); dispatch 80 OK; verify_seed PASS (164; seed baseline 136); counters-only budget check PASS; `check_profile` and `check_security_inventory` PASS; no QEMU, SSH or SFTP process left. **Not verified:** the frozen binary's `sys.path`; a `meta.json` that pydantic accepts but the standard library rejects (an untested inference, recorded in `fd-outer-server-local-recovery`); the S-02.2 acceptance run was not repeated (container settings and the job's reach are unchanged; its standing probes passed); upstream reports not yet filed.<br>**(4) Overseer decision, 2026-11-09 (C6):** `strong-windows-qemu-whpx` `status.operational` is set to **true**, on the qualified host only. The grounds:<br>- proof items (1) to (3) and the live admitted create pass after the fix forward, and no stored field steers;<br>- C6's leaves F-03.3.1, F-03.3.2, F-03.4 and S-02.x passed, and are cited by property id in `status.operational_evidence` (P1, P2, P8 to P12: F-03.4, re-observed in slice (c); P3 to P6: F-03.3.1, S-02.1, S-02.2; P7: F-03.3.2, S-01.4, S-02.2; the Agent Server path: F-04.1, F-04.2, S-01.3.1, S-01.3.2; P5's root scan: E-01.2.2 (b) and (c));<br>- `check_profile --strict` PASS on a copy with the change applied.<br>Carried with the decision, not gating it:<br>- the XSAVE `misordered-xstate` limitation;<br>- P5's root-scan waiver;<br>- `fd-outer-server-local-recovery`, `fd-container-shares-service-uid`, `fd-session-key-not-fine-grained` and `fd-guest-login-name-and-key`;<br>- CI out of scope.<br>A new host, a changed pin or a guest-changing leaf requalifies before the flag holds again. Setting the flag admits nothing on its own: dispatch still needs an approved catalog pin (E-01.2.1, A-01.1), and no dispatcher exists yet (E-01.3.x). | **E-01.2 PASS (2026-11-09), qualified.** Proof: "Malformed or unapproved workspace paths, profiles and local-runtime fallback are rejected before any OpenHands create request." E-01.2.1 and E-01.2.2(a) refuse every malformed or unapproved input with 0 transport calls (fixtures; no dispatcher yet, E-01.3.x). Slice (b) found a local-runtime fallback inside the guest: the outer server resumed stored conversations in its own process. Slice (c) closed it, and that is observed live. Qualified: admission is proven on fixtures plus one live admitted create, on one Windows host. *(2026-11-10: external reporting is deferred by decision 0017 and its addendum; the upstream reference and any prepared report are internal knowledge, not pending work.)* |
| E-01.3.1 Implement typed native conversation-create request | **PASS (2026-11-10)**, injected transport only, Windows; no live create (no transport for live use exists until E-01.3.3) | code, tests, fixture, README and `docs/development.md` (E-01.2.2 finding F7) `6c8630a`; budgets `c885bf4` (counters; the dispatch and integration walls raised within the new tests' measured cost, by the Overseer's advance ruling); evidence `08bc4b4` | [Evidence](E-01.3.1-conversation-create.md). `integrations/dispatch/dispatch_inputs.py`: `AgentServerClient`, the dispatcher's only way to the Agent Server, sends a call only when its method and route are listed once with `dispatcher: allowed` in the profile's pinned `routes.json` (digest checked) and its path parameters fit their grammar; anything else is refused with the transport not called. `dispatch` runs resolve, reserve, admit, workspace creation, send_create in that order; `send_create` takes the record re-read from the store (`reserved_inputs`: digest, typed identity, still `reserved`), sends `GET /server_info` through the client, checks the preconditions, then the create with the reserved `conversation_id` and runtime `docker`; the receipt keeps the returned ids only, no event history. The workspace directory is created after admission without following links (junctions planted after admission and at creation time refused, their targets left empty). Every reservation carries `workRef` and `outcomeRef` (`resolved-inputs/v2`). 8 new refusal codes; `ROUTE_NOT_ALLOWLISTED` now covers every call. **Proof:** `test_conversation_create.py`, 31 tests (dispatch suite 82 to 113); every refusal asserts zero transport calls, each positive control exactly the expected calls; mutation check 40 of 40 killed after round 1's 6 survivors were closed by four tests before the commit. Upstream shapes from recorded evidence: `/server_info` from F-04.1c section 3, the create template as validated against the locked OpenAPI `StartConversationRequest` at F-04.2 section 4.1 (the obligation to validate the runtime discriminator against the pinned OpenAPI), the create answer from F-04.2 sections 4.2 and 4.5; fixture `integrations/dispatch/tests/fixtures/agent-server-1.60.1-exchange.json`.<br>**Overseer rulings:** (F3) decision 0001 does not number its preconditions; the Overseer accepts the leaf's numbering as the reading of decision 0001 and the plan's proof, without amending the decision: P1 `version` equals the pinned allowlist's version (1.60.1, s1), P2 `conversation_runtime_routes_v1`, P3 `idempotent_conversation_create_v1`, P4 `conversation_runtime` `docker`, P5 `available_conversation_runtimes` empty (the proof's requirement; it closes s2's hybrid alternative, consistent with s2's required configuration, and no hybrid exception is recorded); the recorded server answer meets all five. (F4) `outcomeRef` is the Work item's own lineage reference in decision 0008's form, exactly one `outcome:<uuid>[@<commit>]`; it is never derived from a design pointer (that would be inference, not a reference), so Work without an explicit outcome reference is not dispatchable, which the proof's "every reservation carries outcomeRef" already implies. Carried: the leaves that create dispatchable Work (P-04.3, A-01.x) must write that reference. (F5) decision 0001's "any non-2xx is a refusal" holds: no non-2xx answer ever counts as a created conversation. A 4xx marks the attempt failed (`CREATE_REFUSED`); no answer, a 5xx, another 2xx or a different id leaves it unknown and blocks the next attempt until reconciled, because a refusal does not prove no effect (reconcile before retry). (F6) a precondition refusal calls the transport once, for `GET /server_info` itself, never for the create.<br>**Fix forward (introduced-by `6c8630a`, repaired in it, not run):** `send_create` now makes two calls, so the opt-in live helper `live_admitted_create.py` sends `/server_info` over the drill's API channel; parsed only. **Overseer verification:** `verify_seed` PASS both modes (165/136); read of the client, the precondition check and the recorded server answer; the dispatch, store, planning and lineage suites OK with `AIEH_DATA_ROOT` redirected to an empty directory, still empty after; budget diff read (walls raised: dispatch 4.6 to 5.7 s, measured cost 1.19 s; integration 88.9 to 89.9 s, measured cost 1.09 s; planning fell; others kept); `test:budget` from Git Bash on a quiet host (Disk Cleanup waited out) **PASS**, serial 138.7 s, contract 20.8 s. Builder: all 12 suites OK; mutation 40/40; gate tests 27 OK; `test:categories` PASS under the tools interpreter.<br>**Unrelated but detected (carried):** the `test` and `dispatch:test` descriptions in `Taskfile.yml` are stale. **Not verified:** any live create or the live helper; the full create answer (only recorded fields); a junction raced between a parent check and `mkdir` (handle-relative creation would be needed); platforms other than Windows (the junction tests skip there). |
| E-01.3.3 Realize dispatcher credential custody and per-attempt role tokens | **IN PROGRESS (2026-11-11)**: the role-token half built and tested offline (Windows, fakes only); slice 2 built offline under the Overseer's rulings and the Owner's correction of the token lifecycle (the live transport, the standing-credential use with no revocation at attempt end, the records, the custody probe prepared and unrun); the plan amendment OA-20 applied 2026-11-11 (below); remaining: the disposable-guest custody probe, which needs the Credential Manager reads of the two bot entries (OA-26) and, as the first live traversal of edge `nm-dispatcher-agent-server`, OA-22 item (d) (corrected 2026-11-12, planning) | role token in the attempt context `da4ec03`; tests from the mutation check `d387901`; budgets `b4b2108`; evidence `c32ad25`; slice 2: live transport `e5da60c`, the three lifecycles `2a4f460`, records `f1efb72`, custody probe `85c63f6`, OA-20 proposal draft `32552f4`, tests from the mutation check `196a6bb`, budgets `1e9de10`, evidence `3594caf`; OA-20 package: `14f91fa`, `a57b043`; `security/README.md` row `d45a036` | [Evidence](E-01.3.3-dispatcher-custody.md). `integrations/dispatch/attempt_tokens.py`: stages map to bots (`implement` to `aieh-bot-builder`, `review` to `aieh-bot-reviewer`, tied to `policy/role-tokens.json` by a contract test); `attempt_role_token` takes no stage, role or entry from its caller, re-reads the stored attempt and delivers only for a confirmed one, reads only the mapped entry and requires Gitea's `GET /api/v1/token` to show exactly the bot and its scopes, failing closed otherwise (missing, another account's or malformed entry, another bot's token, other scopes, 401, a lost answer, a failing provider); records carry the fingerprint only and the delivery refuses copy and pickle; while a token is held the Agent Server client refuses any call whose path or body carries it or its fingerprint (`ROLE_TOKEN_EXPOSURE`). Mutation 115/116 killed (one equivalent), 4 workers, no window, 0 leftover processes; three test gaps in checks moved unchanged from E-01.3.1 fixed forward (unrelated-but-detected). **Overseer verification:** the module and the client guard read; budget `check --run` PASS at `c32ad25` on the idle host (serial 134.0 s, dispatch 5.7 s; cleanmgr absent before and after); verify_seed PASS; publication gate and private-path grep clean. **Stopped (evidence section 3):** F-1, Gitea 28.3.0 gives the dispatcher no way to issue a token (CLI or basic authentication only; a Bot has no password), so per-attempt rotation needs an issuer; F-2, no guest dispatcher principal exists or is decided (decision 0013 point 1 keeps `tools/guest.py`'s bootstrap role unchanged; ruling R9 keeps the key file), the realization changes the profile and seed (and so the pinned profile digest), and every management call of `tools/guest.py` reads the key as `agent`, including the `job-access-probe` that S-03.2's pending acts depend on; F-3, "a read by the UI is refused" needs a reading under decision 0013 point 6. Not verified: anything live. **Slice 2 (2026-11-11):** [evidence section 8](E-01.3.3-dispatcher-custody.md). `integrations/dispatch/guest_transport.py`: the dispatch module's one live transport, through `tools/guest.py`'s `GuestApi` as `agent` (the key read in the guest only; an answer carrying it refused; another declaration or channel login refused; records statuses and body digests only); the drill and `live_admitted_create.py` use it. The Owner's correction applied before any revocation code existed: no revocation at attempt end; the five tests of the correction (sequential attempts on the standing credential, concurrent attempts not invalidating one another, a revoked credential failing closed until the administrative lifecycle restores it, no stage credential reaching the guest, no other stage's credential); `rotate` resumes over a token already refused; the dispatch package reaches no mint, CLI, entry write or revocation (reachable names, with a negative control). Records `planned`. Custody probe prepared (`guest.custody_probe`, its rule stated before any run; the runtime-credential answer read under a named assumed shape for U-01.2 to verify). Mutation 605/611 then 32/33 killed. **Overseer verification:** budget `check --run` PASS at `3594caf` on the idle host (serial 141.9 s, tools 78.8 s, dispatch 7.8 s; cleanmgr absent before and after); verify_seed PASS; publication gate and private-path grep clean. Detected, carried to the next slice: `Ssh.run` starts `ssh.exe` without `CREATE_NO_WINDOW` (the Owner's no-window rule; unrelated-but-detected), and one other spawn uses `DETACHED_PROCESS`; `check_role_tokens` requires the `attempt-end` trigger on agent rows, the planner row and `policy/README.md` still state rotation at attempt end, `security/README.md`'s row for `fd-guest-login-name-and-key` drifts, and the leaf's title and artifact say "per-attempt delivery and rotation" (all for OA-20). **OA-20 package (2026-11-11):** [proposal](E-01.3.3-plan-amendment-proposal.md), presented to the Owner: the leaf's title, action, artifact, proof and notes exactly (the proof separating the live probe's clauses from the offline tests' five token checks); the decision 0007 amendment 1 (the Overseer's draft, revised after the Builder found four defects in it: an overstated reference, two of point 5's effects omitted, a citation, and a list read as closed); a records patch (not applied; `policy/role-tokens.json`, `security/inventory.json`, `policy/ci-token-secret-policy.json`, `tools/check_role_tokens.py` and its tests, the two READMEs), whose patched scratch tree passes every checker and verify_seed. **OA-20 applied (2026-11-11):** decision 0007 Amendment 1 and the 0013 note `2cdf664`; plan `1ccdf02`; patch `ea4ff69`; sweep fix `911c433`; `6ae54a8`; test ids `1b65161` (Decisions). |
| S-03.1 Design the inference broker and model-access plane | **PASS (2026-11-12)**, the engineering manager's verdict (decision 0018 point 1). History: IN PROGRESS from 2026-11-10: the Owner accepted the ACP architecture and decision 0015 amendment 1 (applied); the leaf is reconciled by the plan amendment; since the plan amendment of 2026-11-12 (OA-28 item 2) its proof needs no Owner act, and the Owner's authorization before any model run is S-03.3's (and S-03.4's and K-02.2's for theirs) | decision 0015 (Proposed) and the request, this commit | [Decision 0015](../decisions/0015-inference-broker-placement-provider-credential-custody-and-guest-inference-endpoint.md); [authorization request](S-03.1-owner-authorization-request.md). Architect consultation, gates B and G; read-only, no runtime. **Design:** a host-side broker in `td-management`, loopback only, the sole holder of the provider credential (one F-06.3 credential entry, loaded into memory, fingerprints only elsewhere); per-attempt tokens the broker alone issues and revokes (decision 0007 points 4 and 5), carried as the conversation's API key with `base_url` the guest endpoint; the guest `inference` endpoint is a listener on the docker0 gateway owned by the guest's sshd as a remote port forward the dispatcher holds over the existing management channel, with one container-guard allow and the egress guard's allowlist still empty; the broker's egress is one provider origin; audit lines without bodies, headers or secrets. **The three named items:** the 8.8.8.8 resolver stays unreachable and the inference path needs no DNS (S-03.2 to point Moby `dns` at a refused guest address, else a recorded limit); LiteLLM's cost-map fetch stays denied and the broker opens nothing for it (source lines in the bundled 1.105.1 from E-01.4.3); no guestfwd is adopted, because F-03.3.2 observed a single stream that does not reconnect, so the broker need not run before the guest.<br>**Options weighed:** guestfwd, a broker inside the guest or in a second guest, SLIRP `restrict=off`, a second network backend; the LiteLLM proxy (not pinned; per-key revocation needs its database, unverified) recorded as the alternative for multi-provider routing; a generic reverse proxy. **Correction to the planning premise:** `composition/` pins the litellm library (1.105.7, a transitive of the OpenHands packages), not the LiteLLM proxy; the guest's agent-server binary bundles 1.105.1.<br>**Overseer review:** the quoted Owner decision checked against this log; the seed's `AllowTcpForwarding no` confirmed; the design is consistent with decisions 0003 (P5), 0007, 0010 and 0013 and refines, without rewriting, planning-level text that assumed a guestfwd (profiles P7's candidate mechanism, the matrix rows `nm-job-inference`/`nm-review-inference`, S-01.4 ruling R5), which the Overseer amends at S-03.2 only as authorized. **Not verified:** the 1.60.1 create request's LLM field names and whether the Agent Server stores the API key in clear; OpenSSH `PermitListen`/`GatewayPorts clientspecified` and the Windows client's `-R`; Moby `bip`/`dns` in this guest; the LiteLLM proxy's database dependence. <br>**Verdict (engineering manager, 2026-11-12):** each proof clause traced to decision 0015 as amended: the sole holder of the provider credential (the placement section: the host-side broker in `td-management`); the endpoint class and its inspection (section 4, its item 5); the 8.8.8.8 resolver, LiteLLM's cost-map fetch and the guestfwd lifetime (the three named items). The artifact is the Proposed decision and the authorization request (`evidence/S-03.1-owner-authorization-request.md`); since OA-28 item 2 the proof needs no Owner act. Decision 0015 stays Proposed, as the artifact states; its acceptance is not part of this proof and authorizes no act (decision 0018 point 3.1). Its "Not verified" items are S-03.2's and S-03.3's qualification, unchanged. No parent gate (S-03 has open children). |
| S-03.2 Implement and qualify the inference-access plane without a model | **IN PROGRESS (2026-11-10)**: slices 1 (the broker core), 2 (the guest composition, opt-in), 3 (the forward session and the probe's token steps) 4 (the qualification tools) and 5 (the provider-key containment search) built and tested offline, Windows; the OA-19 plan amendment applied; open: the guest qualification (Owner acts A2, A3, A4), then the guest qualification (Owner acts A2, A3, A4) | broker `b1ded92`; wiring `b76c361`; test speedups `b6b206f`; evidence `40150ce`; CI and example config `a71707c`; budgets `e00fb06`; slice 2: composition `0303ce3`, tests from the mutation check `2aed3ff`, budgets `9f07c19` and `1b8ef44`, evidence `5b4f80a`; slice 3: forward session and token steps `573d71e`, no-window fix `60a68cd`, tests from the mutation check `b0393b1`, slice 1 reconciliation note `9b4c5b0`, budgets `4bfdd8f`, evidence `afc6022`; slice 4: tools `60b8a5c`, streaming-fixture race fix `3498199`, tests from the mutation check `2c54b4b`, budgets `38e08b5`, evidence `447efe0`; slice 5: search `f7bc98d`, wiring `ea27585`, fix-forward `9e85f67`, tests from the mutation check `af9b3f0`, `edcaa41`, budgets `6f75943`, evidence `0927e3b` | [Slice 1 evidence](S-03.2-slice1-broker-core.md); [decision 0015](../decisions/0015-inference-broker-placement-provider-credential-custody-and-guest-inference-endpoint.md) as amended. **Dispatch ruling (Overseer):** S-03.1 is still IN PROGRESS, but its design is accepted (decision 0015 amendment 1, Owner) and the Owner's decision (d) on OA-12 authorizes S-03.2's offline development, so the offline slices proceed; the guest qualification waits for S-03.1 and the Owner acts. **Slice 1:** `integrations/inference/`: a host broker on `127.0.0.1` only with a control listener (issue, revoke, status; direct loopback calls only) and an inference listener; per-attempt tokens stored hashed and bound to conversation, API family, model list, request and token budgets and expiry; one grant per attempt; revocation immediate with an integration-store receipt; untranslated pass-through to the family's one upstream origin with the provider key substituted (the attempt token never leaves toward the upstream; credential and forwarding headers stripped; a request carrying its own token anywhere refused); SSE streamed; usage from the final event, and an attempt with unknown usage refused further requests (fail closed); audit lines without bodies, headers, token or key, through the I7 scan; three declared families (`anthropic-messages`, `openai-responses`, `openai-chat`; routes **provisional**, pinned from observed traffic at the leaf that first runs each); **no upstream and no model shipped** (every issue refused `MODEL_NOT_ALLOWLISTED` until the Owner approves exact model ids); `credential-set` reads the key from piped standard input only (never run against the real store). 92 tests (93 with the config test); mutation 241/245 killed, 4 equivalent or not exercisable in process. **Overseer verification:** the outbound connector and the admission path read (one connector, the admitted family's origin only; plain http only to loopback); inference suite 92 OK with the data root left empty; verify_seed PASS; Overseer budget `check --run` at `c4cf76a` (Disk Cleanup absent before and after): serial median 144.6 s, inference 1.7 s and store 11.6 s within their walls, one failure in an untouched suite, the repository suite (median 7.86 s against its 7.67 s limit; the Builder measured 7.21 s): unrelated-but-detected host drift on a suite chronically near its limit; no wall raised; a repository headroom slice follows (the gitea precedent); publication gate and private-path grep clean. **Not verified:** anything outside a test process (real listeners, the real credential entry, TLS to a provider, any model call); the provisional routes and usage extractors; Linux and macOS. Detected, not changed: the slice evidence's line saying `example_config.yml` defines no component settings is out of date since `a71707c` **Slice 2 (2026-11-10):** [evidence](S-03.2-slice2-guest-composition.md). The guest side of decision 0015 section 4, declared `planned` and **opt-in per guest** (Overseer ruling: `create --provision --inference`, refused without `--provision`, with `--drill` or for a netprobe instance; applying it to a guest is the Owner's act A4, not authorized): a pinned seed overlay (`profiles/seed/inference-overlay.json`, seven exact edits, each anchor once) gives the sshd drop-in `AllowTcpForwarding remote`, `GatewayPorts clientspecified` and `PermitListen 172.17.0.1:8090` (local forwarding stays refused), the container guard one IPv4 ACCEPT (`-d 172.17.0.1/32 -i docker0 -p tcp --dport 8090`) between its RETURN and its LOG, and the boot facts `sshd -T`; the manifest's `daemon.json` gains `bip` 172.17.0.1/16 and `dns` [172.17.0.1]; the egress allowlist stays empty and `check_profile` refuses an inference entry in it; `inspect` checks whichever state the launch record names and takes the provider key's fingerprint as a P5 needle; `job-access-probe` adds the endpoint (401 without a token), four refused edges and a failing name lookup on an opted-in guest; six `planned` S-02 cases; contract amendments (P7, the endpoint entry, the matrix rows, the inventory assets). Cost-map control (0015 section 7.2) not built: the pinned create admits no container environment (E-01.4.3 F-2 stands). Mutation 430/445 killed, the 15 survivors live-only or equivalent. **Overseer verification:** with the option off, the pre-slice generator (`0b8af57`, from `git archive`) and the current one, run on identical inputs (no manifest, a manifest, a manifest with the profile's `daemon.json`), wrote byte-identical files, seed.iso included (their result differs only in the instance path); the overlay and the profile's composition read against decision 0015 as amended; tools suite 1246 OK (6 skipped); `check_profile`, `check_network_matrix`, `check_containment_cases`, `check_security_inventory`, `check_role_tokens`, `check_ci_policy` and verify_seed PASS; budget `check --run` PASS at `5b4f80a` (serial 140.8 s, tools 77.0 s; a first run failed six walls at 198.8 s while another process outside the harness held the host's CPU, every suite slower, and passed on the idle host; cleanmgr absent before and after); publication gate and private-path grep clean. **Not verified:** everything in a guest (OpenSSH `PermitListen` with `GatewayPorts clientspecified`, the listener's process name, the Windows client's `-R`, the rule order printed, Moby's `bip` and `dns`, the 401 through the forward, every job-side outcome); Linux and macOS. **Rulings:** (1) the per-attempt token credential `cred-inference-attempt-token` was not added (it needs `policy/role-tokens.json`, granting the engineering and reviewer roles as 0015 directs, and `policy/ci-token-secret-policy.json`, outside that dispatch's paths): carried to slice 3 as `planned` entries implementing accepted decision 0015, not a policy change; (2) found by the Builder: while a forward session is held, the guest's own processes (not only containers) reach the endpoint and the attempt token is the only control; decision 0015 already makes the token the admission control and a guest process outside a container is inside the guest's trust domain, so this is a coverage gap in the matrix (no row for guest process to endpoint), carried to slice 3 as a `planned` row and case, not a design change; (3) `recreate` not carrying `--inference` (like `--egress-falsification`) and the template's guard comment naming an inference allowlist entry are carried to slice 3 (the comment only in the overlay, so the default bytes stay). The profile's `enforcement_point.mechanism` (qualified by F-03.3.2) is reworded to name the remote forward instead of guestfwd; launch.argv carries no guestfwd either way, so what F-03.3.2 qualified (SLIRP `restrict=on`, hostfwd on 127.0.0.1) is unchanged. Process note: a surviving mutant let a new test with a relative path run `create` in the checkout root during the mutation re-run; it wrote an untracked `no-such-instance-dir/ssh/` with a throwaway key pair, removed by the Builder, never committed; the test now uses an absolute temporary path and the harness runs each mutant in its private copy (the tree was clean at the Overseer's check). **Correction (2026-11-11, Overseer):** the slice 2 entry's "next: slice 3 (... the typed create's secrets)" was wrong: the plan's 2026-11-10 re-scope dropped the LLM-settings create from S-03.2's proof, and the ACP `agent_settings` block and the two `secrets` names belong to A-01.2 and E-03.1; slice 3 did not change the typed create. **Slice 3 (2026-11-11):** [evidence](S-03.2-slice3-forward-session.md). `tools/guest.py inference-forward --action start|status|stop` (refused for an instance without the composition): a holder process runs `ssh -N -v -o ExitOnForwardFailure=yes` with keepalives, the per-instance key and the profile's client options, `-R 172.17.0.1:8090:127.0.0.1:<broker inference port>`; the port comes from `components.inference_broker` through `integrations/inference/inference_control.py` (the control port and any other refused; `start` refuses unless the broker's status shows its inference listener there); the record `inference-forward.json` is written only after ssh reports the forward established and removed when ssh ends; a record is trusted only while its ssh process runs (pid, binary, creation time); `start` is idempotent and replaces a stale record; no automatic retry; `destroy` stops a held session. `job-access-probe --attempt-token-stdin` (opted-in guest only) shows, from inside the token's container: forwarded with the token, 401 `TOKEN_REVOKED` after revocation, `ECONNREFUSED` without the forward, 401 again after re-establishment, and always revokes at the end; the token is read from standard input, reaches the guest in the script's own text on ssh's standard input and the container as bash-session input through the `printf` builtin (no process argument carries it), answers are redacted and records carry its fingerprint only; it persists in the conversation's `bash_events`, as decision 0015 section 8 discloses. Contract items, all `planned`: `cred-inference-attempt-token`; the inference-access grant to `planner`, `builder` and `reviewer` (Overseer ruling: accepted; 0015's "engineering roles" read as the roles of principal `engineering-agent`), issued by the broker, CI lane none; the guest-login path slice 2 found (`nm-guest-inference` disclosed, finding `fd-guest-inference-reach`, case `egr-inference-guest-login`, a new enforcement location `broker-token-admission`; catalogue version 3, 118 cases); `recreate` carries the composition from the launch record (`--egress-falsification` stays dropped, a test aid); the template's guard comment fixed in the overlay only (re-pinned; default bytes unchanged). Mutation 327/329 killed, 2 survivors not exercisable (a module loader's re-raise). **Overseer verification:** the holder and ssh launch flags and the token transport read; tools suite 1278 OK (6 skipped); inference suite 102 OK; the six contract checkers, the containment render check and verify_seed PASS; no forward or test process left after the runs; budget `check --run` PASS at `afc6022` (serial 142.4 s, tools 79.0 s; host idle, cleanmgr absent before and after); publication gate and private-path grep clean. **Incident (Owner-reported, 2026-11-11):** console windows opened on the Owner's screen during the slice: the new holder was started with `DETACHED_PROCESS`, so each ssh (in tests a fake ssh) it started got a visible console of its own, multiplied by a 10-worker mutation run. Classified introduced-by; the Overseer ended the run's process tree and stopped the Builder; fixed forward in `60a68cd` (holder `CREATE_NO_WINDOW` with `CREATE_NEW_PROCESS_GROUP`, ssh `CREATE_NO_WINDOW`, QEMU's launch unchanged; a test asserts both launches' flags without starting a process; real-spawn tests end and check every process they start; the mutation harness at 4 workers with each mutant in a job object). It would also have shown the Owner a window for every real forward session. **Findings for the qualification:** (a) on this host the broker reads its key only from Credential Manager; a keyless loopback upstream (already supported) proves forwarding, revocation and forward loss but not the key substitution, and the P5 provider-key needle stays UNKNOWN; a qualification-only launcher taking a synthetic key on standard input is not built; (b) the proof's clause "A child conversation launched by an agent driven by the fake upstream runs inside the parent container and under its caps" cannot be met as the plan stands: the re-scope dropped the LLM-settings create and the pinned template has `tools: []`, so no agent can be driven by the fake upstream or start a child (an inconsistency in the 2026-11-10 re-scope, which kept the clause; under Architect consultation, gate A, before any plan amendment is presented to the Owner); (c) no harness command issues the probe's token. **Not verified:** everything against real ssh and a guest (the Windows client holding `-N -R` without a console, the `-v` success line, `ExitOnForwardFailure` with `PermitListen`, keepalives, every job-side outcome, the sealed transport). Detected, not changed: `policy/README.md` prose still gives the egress allowlist's first entry to inference; the `inference-broker` role's bootstrap note in `role-tokens.json` still calls the endpoint deferred. **Slice 4 (2026-11-11):** [evidence](S-03.2-slice4-qualification-tools.md). Three host-side commands for the qualification, none run outside a test process: (1) the synthetic-key launcher `integrations/inference/inference_qualification.py broker --provider ID` (a separate module; the Overseer's four constraints: every configured upstream plain http to a loopback IP literal or `QUALIFICATION_UPSTREAM_REFUSED`; the key from standard input only, a terminal refused, the prefix `aieh-qualification-synthetic-` required or `KEY_NOT_SYNTHETIC`; the start receipt's `provider_key` gains `source` (`stdin-qualification` here, the credential store's name under `serve`); never a flag on `serve`, and the credential factory never returns its provider, each by a test); it runs the broker's own `serve` with the configuration read once and the key held in memory; (2) `inference_control.py issue` writes one checked token to standard output only when that is a pipe (a terminal or a file refused) and its attempt id and fingerprint to standard error; (3) `inference_qualification.py fake-upstream` on 127.0.0.1 only, a fixed non-model answer per family, records with header names and the received credential's fingerprint, never values or bodies. Two stale records fixed (`policy/README.md` prose; the `inference-broker` role note). Fixed forward: a slice 1 test fixture's race (unrelated-but-detected under mutation load). Mutation 171/181 killed, 10 equivalent or outside a test process. The inference wall 1.8 to 2.1 s (the new tests' measured cost). **Overseer verification:** the launcher's checks and its call into `serve` read; inference suite 121 OK; the six contract checkers and verify_seed PASS; budget `check --run` PASS at `447efe0` (serial 137.1 s, tools 75.7 s; cleanmgr absent); publication gate and private-path grep clean. **Rulings:** the launcher "writes nothing" means it persists no key (the broker's ordinary start receipt and audit lines with the fingerprint are expected); a keyless launcher run stays refused (a keyless loopback family runs under plain `serve` and shows no substitution). Per the Owner's OA-19 decision the launcher is an offline qualification mechanism only and authorizes neither A2 nor any listener. Not verified: any run outside a test process; `issue` through a real shell pipe; Linux and macOS. Detected, not changed: the fake upstream is IPv4 only while the launcher accepts `http://[::1]`. **Slice 5 (2026-11-11):** [evidence](S-03.2-slice5-key-containment-search.md). `integrations/inference/inference_key_search.py` holds the synthetic key in memory and searches for the key itself, never by fingerprint: raw (which also covers JSON, URL, form, HTML and shell escaping of its alphabet), hex in both cases, base64 and base64url at three alignments, UTF-16LE/BE, each of the whole key and its body, and raw 16-character body fragments at stride 8; over raw bytes with overlapping chunks, gzip, SQLite row by row, tar members and de-chunked HTTP messages. A verdict counts only when every positive control (planted through the real encoders, per encoding and surface) is found; the report is checked for the key before it is printed and withheld if it holds it. The exposure boundary is the launcher/broker process: offline, in a test process, every byte across both listeners, its stdout and stderr, the fake upstream's records, the store and audit tree and the environment: not found over about 184 KB on 9 surfaces, 191 controls valid; the bytes sent upstream found as they must be; planted leaks (base64 on the forward, hex in the audit directory, an SQLite row) found. Wired for the live run, prepared and unrun: `guest.py inspect --provider-key-stdin` (for an instance with the inference composition its P5 key check is UNKNOWN without the search, the Owner's "fingerprint-only is not proof") and `job-access-probe --provider-key-stdin` (the answers searched in memory, never recorded). **Overseer verification:** the wiring read (key from standard input only, never a terminal, checked against the start receipt's fingerprint; the inspect record refused if it would hold the key); verify_seed and the contract checkers PASS; budget `check --run` PASS at `0927e3b` on the idle host (serial 145.7 s, tools 80.1 s, inference 3.5 s, owner 5.1 s; cleanmgr absent before and after). **Rulings:** the budget commit's rewrite of `evidence/test-profile/baseline.json` is the budget mechanism's own (as slice 4's); the Builder's final run failing only the owner wall (5.24 s against 5.20; no owner change in this slice) is host variance, passed on the idle host, and the owner wall is not raised here; watch: the serial total is 4.3 s under its 150 s ceiling, which is never raised. Disclosed, by design (decision 0015 3.2): the broker returns the upstream's answer unexamined, so an upstream that echoed the key would carry it across the forward (this search finds it; real providers are S-03.3's). Not covered: process memory, stacked or other encodings, container writable layers. Not verified: the live run; Linux and macOS. |
| S-03.3 Qualify the first ACP coding provider through the broker | **IN PROGRESS (2026-11-11; offline work complete 2026-11-13, only live steps remain)**: offline preparation while S-03.2's guest qualification waits on OA-12; the slice plan, slice 1 (the containment observation), slice 2 (the qualification create and its admission) slice 3 part one (the refused-request audit), slice 5 (the live qualification driver, prepared and unrun) and D-6 (the attempt token's environment name) built and tested offline, Windows | plan `98a15d8` (it also carried an early copy of slice 1's two files, a staging slip fixed forward in the next commit); slice 1 `c9fa6d1`; evidence `8ceb101`; slice 2 `a6713f8`; slice 3 part one `84d1d9d`; evidence `1c6aa56`; D-6 `94883b8`; slice 5 `e3d3fe8`, `27eeae5`; evidence `b34eb76` | [Slice plan](S-03.3-slice-plan.md), [slice 1](S-03.3-slice1-containment-observation.md). Read at the pinned OpenHands 1.60.1 sources (the locked wheels, hashes equal to the lock, read as data): the ACP adapter is a direct child of the inner server in the conversation container, so it and every process it starts are under the container's limits by construction; four delegation mechanisms distinguished (the provider's own processes, an ACP session fork, the inner server's children route, the native `start_child_conversation` tool, which an ACP agent never receives). Slice 1 (`integrations/dispatch/conversation_containment.py`): collects every process of the container and the guest's view of its PID namespace and cgroup, and judges, failing closed, single inner server, the adapter its direct child, every process its descendant, the same user, capabilities, no_new_privs, seccomp and cgroup, the admitted caps, no npx or npm process, the two views agreeing, and no new container or outer-server conversation (a new inner child conversation labelled as the children route). Findings: F-2, a `LookupSecret` in the create's `secrets` would make the outer server fetch a URL the body names; F-3, the adapter inherits the inner server's environment including the conversation's session and cipher keys (the exposure class S-01.3.1 already recorded, through `/proc/1/environ`; a new path); F-5, the broker's audit of a refused request records neither path nor model. **Overseer verification:** the plan's source reading of the create and the spawn read; dispatch suite 225 OK; the Builder's full parallel suite 13/13 and checkers PASS; verify_seed PASS; publication gate and private-path grep clean. **Overseer rulings (no gate earned: each follows from an accepted record or an Owner constraint):** admission accepts `StaticSecret` only (F-2, fail closed); the qualification sends exactly `acp_command: ["claude-agent-acp"]`, never an empty command that can fall back to npx (the Owner's "Do not silently fall back to runtime npx installation"); F-3 is disclosed as the existing class and the adapter's environment is sanitized of `OH_SESSION_API_KEYS_*` and `OH_SECRET_KEY` where the image's wrapper allows it without changing OpenHands' code, else disclosed; the qualification create fixture lives under `integrations/`, pinned and refused by real stages, with no profile edit; the broker's audit of a refused request may record method, path, parameter names and the requested model (no values) for a no-cost route and model discovery; the secret names in the job contract are amended for the attempt token's name. Owner decisions carried: the adapter and CLI pins (D-1), the real-key search's key access (with A1), the model identifiers, A1 to A6. Not verified: anything in a guest. **Slices 2 and 3 part one (2026-11-11):** [evidence](S-03.3-slice2-qualification-create.md). `integrations/dispatch/acp_qualification.py` with a digest-pinned create fixture and a registry extract (source lines, the locked wheels' sha256 checked against the lock): `check_create` admits exactly the fixture with its four values and refuses, each by its own code, any secret kind but `StaticSecret`, any command but exactly `["claude-agent-acp"]` (the empty npx fallback included), `agent_profile_id`, MCP configuration, tools, skills, plugins, hooks and `agent_context`, any destination but the profile's inference endpoint, other secret names, provider-key-shaped values and a model outside the family's allowlist; the unchanged real dispatch path refuses the fixture. The broker's audit of a refused request records its path, sorted query parameter names and, for a request presenting a grant's token, its `model`, each only within a bounded grammar and the I7 guard, else counted as unrecorded; never a value, a header, another body part or a credential. F-3 answered from source: the create cannot remove or blank the inherited `OH_SESSION_API_KEYS_*` or `OH_SECRET_KEY` without changing OpenHands' code, so F-3 stays disclosed (the existing class). **Overseer verification:** the audit change read; dispatch 256 OK, inference 148 OK; the Builder's full parallel suite 13/13, checkers PASS; verify_seed PASS; publication gate and private-path grep clean. Carried: D-6, the job contract's secret names for the attempt token, lives in the profile, `check_profile` and `tools/guest.py`, so it is amended with the live-preparation slice, admitting the name only for a conversation that carries an attempt token whose value has the broker's token shape. **Slice 5 and D-6 (2026-11-11):** [evidence](S-03.3-slice5-live-driver.md). `tools/guest.py acp-qualification` takes the attempt token on stdin from `inference_control.py issue`, admits and sends the slice-2 create, sends a fixed prompt, observes containment (slice 1 plus a TCP connection view), the job contract, the container and conversation sets, the broker's counters and the key search, revokes the token at attempt end and deletes the conversation; its decision rule is fixed in the code and copied into every record, each step PASS, FAIL or UNKNOWN; a STOP skips the rest but never the key search, revocation or teardown; the real-key search is refused without a named Owner act. D-6: the profile admits `ANTHROPIC_API_KEY` under the opt-in inference composition only, where the job probe reports, by shape, the broker's token shape and no provider-key shape; with no such names the verdict is the old one (profile sha256 `c7e9a58d...` to `0eb5fc0a...`; no checked-in file pins either; a live approved-input manifest listing the old digest refuses it until re-approved). Findings: F-6, the guest-root vantage slice 1 needs has no channel on an inference guest, so steps 5 and 8 are UNKNOWN until one is decided; F-7, the prompt uses the proxy route the pinned route inventory names for the admission probe only (disclosed); F-8, some response shapes are assumed, recorded as `ACP_ASSUMED`; F-9, the connection view is TCP at two snapshots. **Overseer verification:** the D-6 contract diff and the real-key guard read; dispatch 263 OK, driver 49 OK, D-6 6 OK, `test_check_profile` 140 OK; seven checkers PASS; verify_seed PASS both modes; the Builder's full parallel suite 13/13. **Overseer rulings (no gate earned):** F-6 is closed by extending the existing fixed, argument-free root facts reporter with slice 1's host collection (the same class as its listener facts under decision 0015 section 4.5; no new root channel, no drill helper on inference guests, slice 1's independence kept); F-8 is checked read-only in the staged image archive under the Owner's D-1 inspection. Not verified: anything in a guest. <br>**Offline completion (2026-11-13, engineering manager):** slice 3 part two (the discovery mode and the proposed-pin reader, with body key names only for F7) and slice 4 (the real-key containment search, built and tested with fakes only) `d845834`, `28a054c`; review fix-forward `b0c4500`, `4e3df3c`, `d01cbf1`, `ee51b8e`, `eb6d751`, `881cb73`, `01ff496`; evidence `676dbad` ([slices 3b and 4](S-03.3-slice3b-slice4-discovery-and-real-key-search.md)). The live driver needed no change for S-03.5 (its 6c start is `inference_broker.py serve`, through the start precondition). Independently reviewed and re-reviewed; the review also exposed a weak checkout comparison in P-04.3's `load_manifest` and F-07.1's managed-root guard (decision 0009), both fixed forward by one shared comparison in `aieh_paths`. **Remaining, all live, each its own Owner act:** S-03.2's guest qualification (A2, A3, A4); 6a discovery with the synthetic key; 6b the Owner's approval of the exact routes, the provider envelope (S-03.5) and the engineering manager's model selection presented before the first paid call; A1 the key; A5 the egress; 6c (A6) the qualification run; the real-key search (covered by A1, ruling D-5); teardown and 6d the record. |
| S-03.5 Bind the broker's real-provider start to a recorded provider-envelope authorization | **PASS (2026-11-13)**, the engineering manager's verdict (decision 0018 point 1): every proof clause shown offline against fixtures (evidence section on the proof); independently reviewed and re-reviewed | envelope and start precondition `6d0b9b2`; selection act `fb1e656`; selection at start and per request `b5928cf`; cap `5fdc43f`; review fix-forward `01c970d`; decision 0021 and evidence `0d4e42f`; inventory and policy `0707ad6` | [Evidence](S-03.5-provider-envelope-authorization.md); [decision 0021](../decisions/0021-provider-envelope-model-selection-and-broker-enforced-cap.md) (Accepted, engineering manager); Current facts (2026-11-13) on decisions 0012, 0015 and 0020. Added by the plan amendment of 2026-11-12 (OA-28 item 3). Architect consultation, gates C and G. **Built:** the operation kind `provider-envelope` (`integrations/inference/inference_envelope.py`, the `envelope` command); `serve` refuses before the key and the listeners unless the governing, confirmed, unexpired receipt binds the live envelope's digest and canonical manifest; the model selection (in the envelope, or a delegated `select-models` record by the engineering manager, `integrations/owner/selection_recorder.py`) checked at start, issuance and per request; the broker-enforced cumulative cap in usage tokens with a per-run ledger, closing the envelope when reached or unknown. Loopback fake upstreams and provider-enforced envelopes behave as before. Offline only: no real key, provider, envelope, egress or model call. | - |
| Q-02.1 Define hostile-CI threat model and permission ceiling | **PASS (2026-11-10)**, specification; nothing installed, registered, forwarded, enabled or run | artifacts, checker and record edits `c4e18dd`; budgets `9986dba` (counters; the tools, unit and contract walls raised within the new tests' measured cost, by the Overseer's advance ruling); evidence `48714b1`; decision 0016 accepted, policy files linked to it, two checker tests set up their own unlinked state `8a9b70d` | [Evidence](Q-02.1-hostile-ci-policy.md); [decision 0016](../decisions/0016-hostile-ci-threat-model-validation-and-promotion-lanes-and-runner-reach.md). Architect consultation (gates B, C and G). `policy/ci-runner-profile.json`, `policy/ci-token-secret-policy.json`, `policy/ci/workflows/validation.yml`, `tools/check_ci_policy.py` (`task policy:ci-check`), records in `security/inventory.json` and `policy/role-tokens.json`. **Design:** validation runs in a dedicated, disposable CI guest of the strong tier (act_runner, to be pinned at Q-02.2.1), jobs in its own Moby with no network path at all; the proposal arrives as a verified git bundle in the read-only exchange; only the runner process reaches Gitea, over a dispatcher-held SSH remote forward bound to the CI guest's own loopback (new P7 class `ci-control`, an Owner act), through a host filtering proxy admitting only the runner RPC; Actions stays off on every repository that receives proposals, and the only workflow is a governance repository's, dispatched by the trusted lane from its protected default branch; the job token is inert by topology and permissionless by configuration (restricted mode, all-none ceilings, `permissions: {}`, no cross-repository grants); no Actions secret or variable exists anywhere; a new `aieh-bot-ci` posts `aieh/validation` only after reading the run it dispatched; merges stay Owner acts, and no Actions context ever holds a promotion credential.<br>**Premise check (gate A):** before any artifact was written, the builder read the pinned Gitea source (`gitea-src-28.3.0.tar.gz`, one GET, sha256 equal to the lock, read without building) and found the first draft's G4 contradicted (a configurable job-token ceiling exists; every public repository is readable by any job token) and parts of G2, G6, G7, G8 and G9 wrong (the registration token is not one-shot; only an owner or site administrator can list secrets; a runtime JWT and a v4 artifact route exist). The Architect's revision 2 corrected every dependent mechanism; the lanes and the Owner acts did not change. G1 to G10 are verified at source with path:line, none live; the act_runner facts are unverified.<br>**Overseer rulings:** R1 the filtering proxy (option B4) is adopted, its listener Owner act A-4; R2 the registration token is reset, read, delivered once and reset again by the host Gitea-administration command (the dispatcher and the CI guest never hold the site-administrator credential), the fallback disclosed; R3 the network-matrix edits and the P7 class are the Overseer's, at Q-02.2.1; the G-facts carry `verified: source`; the live check is the administration command's and was never run. Decision 0016 accepted by the Overseer at completion, as 0013 was at S-01.4; every act stays Owner-gated (A-1 to A-4; confirmations C-1 to C-3 at Q-02.2.1, Q-02.2.2 and Q-02.3.1).<br>**Overseer verification:** read of revision 2 in full and of the workflow; `verify_seed` PASS both modes (165/136); `policy:ci-check`, `policy:check`, `policy:network-check`, the containment-case and inventory checkers PASS; the tools suite (1,188) OK with `AIEH_DATA_ROOT` redirected to an empty directory, still empty after; budget diff read; `test:budget` from Git Bash with no Disk Cleanup: first run FAIL on the contract wall (22.36 s against 22.10 s) with every suite 5 to 6% slower, the untouched ones included (host drift; CPU idle when sampled after), rerun **PASS**, serial 145.2 s, contract 22.0 s. Builder: mutation 209 of 210 killed (the survivor equivalent); `hooks:verify` PASS.<br>**Fix forward (introduced-by the Overseer's link commit):** two checker tests read the committed decision link as empty; they now set up the unlinked state themselves (446 checker tests OK). **Unrelated but detected:** the component lock's `gitea-src-28.3.0.tar.gz` entry has no `url`; `security/README.md`'s finding count was stale (restated). **Carried:** the contract wall has about 0.1 s of headroom on a quiet host and the serial total about 5 s under the 150 s gate, so the next leaf adding tests needs runtime work first (Overseer decision). **Not verified:** every G-fact live (Q-02.3.1); every act_runner fact (Q-02.2.1); OpenSSH `PermitListen` and Windows `-R`; that Gitea and act_runner parse the workflow as the checker does; nothing is operational. |
| Q-02.2.1 Define disposable CI runner containment profile | **STOPPED (2026-11-11)** at the boundary: the proof cannot be met offline and needs Owner choices; one part valid whatever the outcome built | registration narrowing `5a07b6f`; evidence `43c9183` | [Evidence](Q-02.2.1-runner-containment-profile.md). The proof is the checker's verdict over the declared CI variant and its seed, which must carry one runner label pinned by image digest and pass `check_profile --strict`; act_runner and the job image are not pinned in `composition/lock/components.lock.json`, so the leaf needs a component resolution (network, decisions 0001 and 0005) and the Owner's C-3 (decision 0016 section 10: the CI guest's composition including the job image, its ceilings, and its lifetime, shared with a persistent runner or one guest per validation with an ephemeral runner). Built: the registration fallback is never in force for a live runner and a declared `live_gate` blocks until the live reset proof (Q-02.2.2, act C-2), with the two alternatives the Owner named (decision 0016's dated note, point 1); `check_ci_policy` reports `REGISTRATION_RESET` otherwise; mutation 13/13 killed. **Overseer verification:** the policy diff read; budget `check --run` PASS at `43c9183` (serial 144.4 s on a rerun after a run discarded because Disk Cleanup started during it; cleanmgr absent before and after); verify_seed and the contract checkers PASS; publication gate and private-path grep clean. Accepted deviation: `policy/README.md` item 7 (hand-written) reworded so it no longer describes the refused fallback. Not built, waiting on C-3 and the pins: the CI variant and seed, the filtering proxy (R1; its listener is act A-4), the P7 class and matrix edits, the lifecycle targets. |
| G-01.1 Define minimal versioned control catalog | **PASS (2026-11-12)**: the catalog and its checker built offline; the definitions-only proof met offline; admitted on the Owner's sign-off of `808b5bd76d09` (`op-policy-change`); enforcement is not claimed (G-01.2) | catalog and checker `20b9e24`; evidence `3606357`; reconciled `808b5bd`; admitted `fb602b2` | [Evidence](G-01.1-control-catalog.md). `policy/control-catalog.json` (page `policy/control-catalog.md`, checker `tools/check_control_catalog.py`, task `policy:control-check`): 8 controls covering the leaf's 7 categories (EXEC-01, SEC-EXEC-01, SDLC-01, SEC-PR-01, REVIEW-01, AUTH-01, ASSURE-01, RECOVER-01), each with an objective, a subject typed by a P-03.2 lineage kind, applicability by cumulative profile (baseline, elevated, consequential) and events, enforcement points (a blueprint boundary, an enforcing inventory principal that is neither agent-controlled nor untrusted, the assets, the leaves that build it), an exception class and a failure effect; AGENT-01, PLAN-01 and REL-01 deferred with reasons and leaves. Exceptions: `prohibited` for isolation and credentials, `scoped` for SEC-PR-01 (the blueprint's words), `unsettled` (fails closed, no exception grantable) for the five the records leave silent, to G-06.3.1. Admission is the Owner's `op-policy-change`: the checker refuses the authorization recorder as admission performer or authority (decision 0012 does not cover catalog admission; M-5 left governance step 04 unchanged). Mutation 191/196 killed (5 equivalent), in process. **Overseer verification:** the catalog's admission block and a control read; the checker PASS; budget `check --run` PASS at `3606357` (serial 144.8 s; cleanmgr absent before and after); verify_seed and the contract checkers PASS; publication gate and private-path grep clean. **Rulings:** the minimal set without the three deferred controls accepted (REL-01's subject has no settled lineage identity yet); `policy/` as the home until the protected policy repository exists; Conftest not used (not pinned). Carried to OA-20's application: SEC-EXEC-01's mechanism text says "delivers each role token per attempt into its own attempt context", to be worded as borrowing once the 0007 amendment is accepted. Not verified: that any enforcement point enforces its control (G-01.2). |
| E-01.4.3 Eliminate or bound the Agent Server start-up import race | **PASS (2026-11-09)** for `strong-windows-qemu-whpx` (qualified host only). Decision rule met; upstream reference recorded: BerriAI/litellm#48292, an equivalent upstream record whose fix ships in litellm 1.105.5 (Owner-action OA-01, with OA-04 merged into it). OpenHands still locks litellm 1.105.1 through v1.61.0; the companion note is OA-02, informational. The reconsider condition (R-01.2) is met once a pinned agent-server bundles litellm 1.105.5 or later. | `574d8db` (fixed commit), evidence `31e2ba0`, budgets `6f252ca`; fix forward `5b3a2fa`, budgets `be88397` | [Evidence](E-01.4.3-start-race.md). Root cause (E-01.2.2c F-15): the pinned 1.60.1 binary bundles litellm **1.105.1** on CPython 3.13.18 (not the 1.105.7 of `composition/lock/python`); offline, `import litellm` starts the cost-map retry thread, both threads log through a filter that imports `litellm.rust_bridge.catalog` lazily, and CPython's module-lock deadlock avoidance hands the main thread a partially initialised module (source lines cited; the thread-side lock edge **not established**, no reproduction outside the binary). Control: upstream `LITELLM_LOCAL_MODEL_COST_MAP=True` in the server unit, declared in `provisioning.agent_server.start_race` with its reconsider condition (R-01.2). Readiness wait (`service.readiness`): fails fast on the main process's exit (`${MAINPID}`) and reports `clean`/`retried`/`slow`/`unverified` or `main-exited`/`timeout`; a new inspect check fails on any start that is not clean. Series (decision rule fixed before observation): `e0143-c` at `574d8db`, **0 main-process exits in 500 consecutive restarts** (readiness max 6.5 s); negative control `e0143-b` without the variable, 1 in 500, failed fast at 2.0 s and reported `main-exited` then `retried`. Requalification at `574d8db`: smoke PASS (on a re-run alone; the first run was disturbed by a concurrent sibling guest), conversation-smoke, admission-probe and job-access-probe PASS. All guests destroyed. Under the extended guest authorization of 2026-11-07.<br>**Statistical note:** pooled uncontrolled starts show 3 in 772, so 0 in 500 would occur about 14% of the time without a fix (the plan assumed 2.5%); the acceptance rests on the rule and on the source (the path is not taken with the control).<br>**Findings and dispositions:** F-1 (unrelated-but-detected) the bundled litellm 1.105.1 is recorded nowhere in `composition/` and the image SBOM does not see inside the binary: routed to R-01.2 (staged composition against the running inventory) and R-04.1 (per-artifact SBOM). F-2 (exposed-by) the control cannot reach conversation containers (1.60.1 forwards a fixed environment list): a documented limit in `start_race.scope` with the R-01.2 reconsider condition; not observed; the E-01.5 and E-01.4.2 dispatches must require that an inner server's start failure surfaces as a failure, never a hang. F-3 (exposed-by) the 280 s wait after the main process died: fixed. F-4 (introduced-by `574d8db`, docs) and F-5 (exposed-by, drill guests named the wrong leaf): fixed in `5b3a2fa` (`--drill-leaf`, now required with `--drill`). F-6 (introduced-by the procedure) concurrent guests disturbed smoke: re-run alone. F-7 the lock edge: unknown.<br>**Overseer verification at `be88397`:** verify_seed PASS (165); tools suite under the tools interpreter 1,078 OK (6 skipped); counters-only budget PASS; check_profile PASS; the unit diff read (Environment line; ExecStartPost `280 30 ${MAINPID}`); the upstream drafts read. **Not verified:** the inner-container race, the `slow`/`unverified`/`timeout` outcomes live, other hosts and profiles. | E-01.4 is evaluated at its last slice. *(2026-11-10: external reporting is deferred by decision 0017 and its addendum; the upstream reference and any prepared report are internal knowledge, not pending work.)* |
| F-09.1 Measure, classify and baseline the test suites | **PASS (2026-11-08)**, qualified on the launch count | `20c7da6`, fix-forward `4c6f44a` (docs `eef7e10`) | [Evidence](F-09.1-test-baseline.md). `tools/test_profile.py` (each suite runs in a child process under `unittest.main` with the `task test` arguments; a stdlib audit hook counts launch attempts by the test process itself and every `mkdtemp`, and charges each to its test, class or module fixture, or import) and `tools/check_test_budget.py` (exact counters per category and suite; wall medians of three runs with 30% tolerance and a 0.5 s floor), with the targets `test:profile`, `test:categories` and `test:budget` (the acceptance obligation at each leaf acceptance and at release, never in a hook); `task test` and `task setup` are unchanged. **Categories:** 224 classes in 34 modules, 0 uncategorized (unit 113, contract 39, integration 61, e2e 11 opt-in live, performance 0). The rule is behavioural: any class that launched a process, opened a socket or changed directory is not `unit`, so the F-09.2 guard already holds on the baseline, and every default fail-closed proof sits in a required tier. **Reproduction** at `330a4e2` (two runs in a throwaway clone): 1,141 tests and 762 mkdtemp exact, 5,821 launches against 5,820. The difference of one is stable, so it is a counting-definition difference; the prototype's definition is not in the repository and was not tuned to. **Overseer ruling:** the proof's structural reproduction is accepted, and the launch definition is now pinned in the code. **Before** (Owner request), serial `task test` at `07c7cd5`, medians of three: **355.4 s** total (tools 216.2 s, of which test 7's nested rerun is about 115 s; lineage 84.8 s). Baseline at the final tree: 1,477 tests, 6,877 launches (72% from `planning_adapter.py`: `git cat-file` 2,460, `rev-parse` 1,786), 1,003 mkdtemp, 382.3 s profiled. The profiler changes no id or outcome in any of the 8 suites. Budget: PASS on the baseline; FAIL on an injected launch in a unit test (`UNIT_NOT_ISOLATED` and three `LAUNCHES_ABOVE`). Overseer verification at `4c6f44a`: verify_seed PASS; `categories` 0 uncategorized; new tool tests 17 + 23 OK; an independent `check --run --counters-only` **PASS** (6,877 launches and 1,003 mkdtemp exact; 1,478 tests, one above budget from the fix-forward's own test, reported as a note); `.claude/` is the Builder's gitignored note directory. Not verified: POSIX launch events, wall budgets on other hosts, the targets through Task (not on PATH). | F-09 is evaluated at F-09.4. |
| F-09.2 Adopt pytest and pytest-xdist as the parallel runner over the unittest suites | **PASS (2026-11-08)**, qualified: the dev venv lacks PyYAML (fixed forward at F-09.3) and no target ran under Task | `9d8367f`, `d2e6009`, fix-forwards `c72e5aa`, `0c0412f`, evidence `8d81975` | [Evidence](F-09.2-parallel-runner.md). A hash-locked dev lock (`composition/lock/python/dev-requirements.txt`: pytest 9.2.0, pytest-xdist 3.8.0 and six dependencies, all pure-Python, MIT, BSD or Apache; compiled with the pinned uv; all 16 hashes checked by the Builder against a local download and PyPI), installed by `task dev:install` through `tools_install` as `python-dev-tools` under the managed root. `pyproject.toml` and a root `conftest.py` add the category markers with `--strict-markers` and the unit guard (a `unit` test that launches a process, opens a socket or changes directory fails). Targets `test:unit`, `test:fast`, `test:component` and `test:all` (`-n auto --maxprocesses 8 --dist loadscope -m "not e2e"`, then Vitest when Node.js 24 or later is present); `task test` and `task setup` unchanged. Test 7's nested whole-suite rerun now runs under `AIEH_GATE_REQUIRE_SCANNER=1` (`hooks:verify`, and `qualify` at release), where it passed with the fail-closed cases 6a to 6g. **Conformance:** the stdlib serial run, `pytest -n 0` and `pytest -n auto` (8 workers) give the same 1,497 ids and outcomes under the dev interpreter (one digest for all three). Five consecutive `test:all` runs pass (49.9 to 53.3 s). **Serial `task test` after, medians of three: 243.3 s** against 355.4 s before (the tools suite's −107 s is test 7's rerun). The guard trips on an injected launch (1 failed, 925 passed) and on none of the real `unit` classes. No checkout writes across 18 runs. Budgets re-proposed (1,493 tests, 6,876 launches, 1,005 mkdtemp), each delta explained. **Overseer rulings:** (1) the `tools_install.py` change (`--set`, `--python`; default unchanged; two tests), outside the dispatch's paths, is accepted: the dispatch had made read-only the file its outcome required, a dispatch defect, and the change is minimal and in its own commit; (2) PyYAML: the parallel tier skips the 4 `config.yml` tests the serial tier runs, an introduced-by gap between runners; fixed forward at F-09.3 by pinning `pyyaml==6.0.3` in the dev lock with the hashes already admitted in `tools-requirements.txt` (wheels-only, hash-locked; the pure-Python rule was the dispatch's precaution, not repository policy); (3) the stale `integrations/paths/README.md` line and the lock README's missing `tools-requirements.txt` row go with that fix-forward. Overseer verification at `8d81975`: verify_seed (158) and `--baseline seed` (136) PASS; `tools_install.py` diff read; an independent `check_test_budget.py check --run --counters-only` **PASS** (1,493 tests and 1,005 mkdtemp exact; 6,875 launches, one below budget in the paths suite, where this shell has no `sh` on PATH and the `sh` adapter test skips; inferred, a note); an independent `test:all` command under the dev interpreter: 1,472 passed, 6 skipped (the 4 PyYAML tests, the `sh` adapter test and test 7), in 59.0 s; `git status --porcelain --ignored` unchanged by both. Not verified: Linux and macOS, the targets through Task, `task qualify` end to end. | F-09 is evaluated at F-09.4. |
| F-09.3 Build expensive fixtures once and inject process boundaries | **PASS (2026-11-09)**, judged jointly with F-09.4 (ruling 1). First held on two criteria: serial `task test` at most 150 s (measured 218.6 s), and the long-TEMP run (two guest exchange tests failed). Both are met: `run_git` runs with `core.longpaths` (`39a8526`) and every suite passed under a 131-character TEMP (F-09.4 round 4); serial `task test` is 144.9 s at `159bde9` (Overseer, `task test:budget`, three runs from PowerShell). | `f120111` (F-09.2 fix-forwards), `a2667d3` to `f26c235`; completion `39a8526`, `9eaa1e7` | [Evidence](F-09.3-shared-fixtures.md). **Delivered:**<br>- golden design repositories built once by input digest and copied per test;<br>- a Backlog runner seam (`Backlog(..., runner=None)`, default `subprocess.run` unchanged) with an in-process fake shown equal to the launched one;<br>- the gate tests on golden repository pairs with one scanner per class;<br>- `verify_seed` logic cases in-process;<br>- one shared `profiles/` copy for the read-only `check_profile` cases;<br>- `core.longpaths` for the fixture's git;<br>- a fix for a leak of guest-test temp trees.<br>**Met:**<br>- fixture git launches 855 → 138 (−83.9%);<br>- `fake_backlog` launches 523 → 40 (−92.4%), with five CLI contract tests still launching it;<br>- tests 1,493 → 1,500, none removed or weakened;<br>- the three runners give the same 1,504 ids and outcomes;<br>- the 4 `config.yml` tests now run under `test:all` (PyYAML 6.0.3 in the dev lock with the 73 admitted hashes, kept equal by a contract test);<br>- `hooks:verify` passes with 6a to 6g and test 7;<br>- the budgets pass with walls.<br>**Serial:** median 218.6 s. In an interleaved A/B on the same host, after 209.6 s against before 259.9 and 261.4 s. The host's tools suite varies by about 15% between periods.<br>**Overseer rulings:**<br>1. **Sequencing.** The remaining time is dominated by F-09.4's scope: the planning adapter's own git launches cost 52.0 s for 4,460 launches. F-09.3 therefore takes no verdict now. F-09.4 is dispatched before F-09.3's verdict, and both are judged on one measurement.<br>   - The F-09.3 → F-09.4 edge is the Overseer's terminal-reach encoding (2026-11-07), not a dependency on F-09.3's wall figure.<br>   - F-09.3's other criteria are verified.<br>   - No criterion is weakened: F-09.3 is not PASS until serial `task test` is measured at most 150 s and the long-TEMP run passes.<br>2. **Long TEMP.** `tools/guest.py` `run_git` lacks `core.longpaths`, a production limit the leaf exposed (exposed-by). It is fixed forward in the next dispatch, with the suites rerun under a TEMP of at least 100 characters. `guest.py` is not hash-pinned; `netprobe.py` is.<br>3. **Scope item 5 (injectable guest probe timeouts) is deferred.** The only real timeout is the 2.0 s UDP wait in `netprobe.py`. That file is pinned by sha256 in `profile.json` and `guest.py`, and changing a pin requalifies the containment catalogue (R-01.2), all for about 2 s. Reconsider when `netprobe.py` next changes for another reason, or if that wait blocks the target.<br>4. **Path boundary.** The Builder listed the gate's scanner cache under the per-user application data folder once. That path was outside the dispatch's named roots, though not protected; the tests read the scanner from there. Classified a minor process defect. The next dispatch names the path.<br>**Overseer verification at `f26c235`:**<br>- verify_seed (158) and `--baseline seed` (136) PASS;<br>- the `planning_adapter.py` seam diff read;<br>- an independent `check --run --counters-only` **PASS**: 1,500 tests and 933 mkdtemp exact; launches 5,474, one below budget in the paths suite (no `sh` on this shell's PATH, as at F-09.2);<br>- `git status --porcelain --ignored` unchanged. | F-09 is evaluated at F-09.4 (PASS, below). |
| F-09.4 Batch and memoize adapter git access | **PASS (2026-11-09)** | `cc5bca7` to `b7f5317` (rounds 1 to 3), `e73f941` to `ebfa026` (round 4, launcher fix), `6dd8128` to `6958ea5` (round 5); unrelated-but-detected fix `ff355e7`, budgets `159bde9` | [Evidence](F-09.4-batched-git.md). One `git cat-file --batch` reader per operation (a traversal, a readiness evaluation, or a CLI or resolver resolution), memoized by object id, with a ref snapshot and a Backlog.md read snapshot per operation and nothing kept between operations. Object names may contain spaces; C0 controls and DEL are refused; revisions refuse any whitespace. Every git process the planning adapter starts is one process tree (a Windows job object the process joins before it runs, or a POSIX session), so no git outlives its reader, including the real git behind Git for Windows' `cmd\git.exe` launcher; the reader fails closed by its own process state.<br>**Criteria:** (1) the two-task traversal launches 7 processes with Backlog.md launched (at most 10), projections equal to `integrations/lineage/examples/`; (2) product-attributed `cat-file` and `rev-parse` launches 4,251 → 399 (−90.6%) like-for-like by the method of record (the old attribution rule on both sides, tests existing at `352920a`); 478 (−88.8%) with the new tests counted. **Dulwich evaluation:** not adopted within F-09.4 (round 2, R6); superseded by the Owner direction of 2026-11-08 (Decisions); the migration is owned by separate plan leaves.<br>**Overseer rulings:** round 1's whitespace refusal was over-specified by the Overseer's dispatch (R1); round 2's mixed-method −90.4% rejected, like-for-like required; the launcher defect (introduced-by) was found by the Overseer's own PowerShell run: the reader killed only the launcher, the real git kept answering and was orphaned, and one lifecycle test failed 4 of 4 runs under PowerShell while passing 13 of 13 under Git Bash; fixed in round 4. Round 5 made the budget counters shell-independent (exposed-by: a paths test launched only where `sh` is on PATH, so the budget check failed from Git Bash); its ~1% looser wall budgets are accepted because the committed budgets equal `propose`'s output; the rewritten `evidence/test-profile/baseline.json` in `159bde9` is accepted (the Overseer's dispatch contradicted itself on that path). `ff355e7` (unrelated-but-detected, pre-existing since `ec1ae0b`): two guest records of one operation written within one clock tick (about 1 ms on Windows CPython 3.12) collided under exclusive create and the second was lost after the work was done; the stamp now advances by one microsecond until the create succeeds, with a deterministic test.<br>**Overseer verification at `159bde9`:** the round-4 adapter diff read; the planning suite OK from PowerShell (the `cmd\git.exe` launcher) and Git Bash with no `git.exe` left; serial suite 142.3 s (one PowerShell run at `ebfa026`); `task test:budget` (three runs, PowerShell) **PASS**, median 144.9 s, 1,558 tests, 1,778 launches, 952 mkdtemp; at `6958ea5` the Git Bash counters-only check failed once on the guest record collision (fixed by `ff355e7`); stdlib profile `run` and `compare` PASS; `pytest -n 0` and `pytest -n auto --maxprocesses 8 --dist loadscope` with `--aieh-conformance` both PASS (1,562 ids, 1,558 run); verify_seed PASS (158; seed baseline 136); no test class relabelled `e2e` since `8d81975`; `git status --porcelain --ignored` unchanged after the Overseer removed two `.pyc` files that its own first pytest run wrote (it omitted `PYTHONDONTWRITEBYTECODE=1`). **Not verified:** POSIX process groups (WSL is protected), `NtResumeProcess` on other Windows builds, launchers other than Git for Windows', the budget check on Linux or macOS. **Carried to the Dulwich inventory:** the same timeout-kill pattern in `tools/guest.py` (`run_git`, the `git()` inside `smoke`, `profile_revision`), `tools/publication_gate.py`, `tools/test_profile.py`, `tools/check_prereqs.py`, `integrations/gitea/gitea_host.py` and `tools/verify_seed.py`. | **F-09 PASS (2026-11-09).** Every test class declares a category and the unit guard holds (the profile `run` and the budget check pass; 1,558 tests in contract, e2e, integration, performance and unit); the stdlib serial run, `pytest -n 0` and `pytest -n auto` give the same ids and outcomes (conformance PASS at `159bde9`); the budget check passes on the baseline (three runs, PowerShell) and fails on an injected regression (F-09.1 evidence; `test_check_test_budget`); serial `task test` 144.9 s, at most 150 s (355.4 s at the F-09.1 baseline; 249.2 s at `352920a` from PowerShell); every fail-closed security proof stays in a required tier (the F-09.2 verdict; the `e2e` set is unchanged since). Limits: one Windows 11 host, PowerShell and Git Bash; no target ran under Task. |
| F-09.5 Retire the remaining timing assertion and the timing-only runs of the test check | Not started | - | Added by the plan amendment `bbbad04` (fix-forward `3a4af34`) (2026-11-13; [planning pass](#planning-pass-2026-11-13)): the Owner's testing-governance direction; not in D1's set; ready offline, ordered below D1's work | - |
| F-10.1 Pin Dulwich and urllib3 in the tools and dev sets | **PASS (2026-11-09)**, qualified: no target ran under Task (not installed on this host; the Taskfile targets were rendered and run), and the Linux and macOS wheels are hash-verified only | `e146063`, evidence `6b233f1` | [Evidence](F-10.1-dulwich-pins.md). `dulwich==1.2.21` (Apache-2.0 elected, of Apache-2.0 OR GPL-2.0-or-later) and `urllib3==2.8.0` are added to the tools lock (new `tools-requirements.in`: dulwich, pyyaml, urllib3) and the dev lock, by the pinned uv 0.13.7 (`--universal --generate-hashes --no-build`, reproduced byte for byte). Every one of the 64 Dulwich files and 2 urllib3 files is downloaded and re-hashed: each equals PyPI's JSON and the lock. No new transitive dependency. The licence rows are in the lock README, `candidates.json` and the LEDGER. The lock-equality contract test pins exactly the locked set with equal hashes (11 of 11 mutations caught), plus a `RequiredTargets` test. `task setup` now installs the tools set, and `task setup` and `task test` run every suite under the tools interpreter (1,625 tests OK; with no tools set installed `test` stops at once, exit 1, creating nothing). The basic-tier checks (`check_prereqs`, `verify_seed` in both modes, the publication gate) run under `-I -S -B` with an audit hook that refuses the network: 0 network attempts, standard-library imports only, with positive controls. Installed under the managed root only through `tools_install` (Overseer ruling at dispatch: the 0009 mechanism, non-elevated, hash-locked, wheels only).<br>**Findings:** (F-1, introduced-by `e146063`) the `tools_install.py` docstring and `integrations/paths/README.md` still describe the tools set as PyYAML only; carried to the next builder dispatch (wording). (F-2, exposed-by; a forward obligation for F-10.2) `test:profile`, `test:budget`, `hooks:verify` (its test 7 reruns the tool suite) and the standalone per-suite targets still use the plain interpreter, and must use the tools interpreter once a test needs Dulwich. (F-3, unrelated-but-detected) the "about four minutes" setup time in `docs/development.md` is replaced by the observed 156 s. Pytest conformance PASS (`-n 0` and `-n auto`, 1,629 ids, 1,625 run); no budget counter moved but tests (+4, contract).<br>**Overseer verification at `6b233f1`:** the tools interpreter imports dulwich 1.2.21, urllib3 2.8.0 and PyYAML 6.0.3 under CPython 3.12.10; the tools suite under the tools interpreter, 1,047 OK (6 skipped); the counters-only budget check PASS; verify_seed PASS (164); both `.in` diffs read; the `test` target read (`TOOLS_PYTHON` from `tools_install.py --python`, passed as `PYTHON` to every suite target). **Not verified:** Task's evaluation of the task-level `PYTHON` override, Linux and macOS installs, PEP 740 attestations. | F-10 is evaluated at F-10.5. |
| F-10.2 Build the shared repository-access module and its differential contract suite | **PASS (2026-11-09)**, qualified: Windows only (Linux at F-10.5, macOS not available); no target ran under Task (rendered); the F-09 150 s serial criterion is carried to the F-10 group gate (decision 0014 section 10) | `622bd75`..`3aa5ef3`, repair `f585e87`, budgets `84f2e73` and `b634651`, evidence `b60fda7` and `9bab278` | [Evidence](F-10.2-repository-module.md). `integrations/repository/repository_access.py` (standard library plus Dulwich, no process) implements decision 0014's interface; no caller migrated. The differential suite (53 tests: a recorded half over a committed git-built corpus, and a git-oracle half that skips with a named reason when git is not on `PATH`) proves the preserved grammar (356 commit forms and 385 object names over 8 repositories, SHA-1 and SHA-256, equal to git 2.52), 34 gap forms refused before any access, file lists, the blob-bytes export, the work-tree check, damaged repositories as `GIT_FAILED`, and the `repository` policy unchanged with `PATH` emptied. Without Dulwich the suite fails (none skipped), naming `REPOSITORY_NEEDS_DULWICH`. `repository:test` is in `test`/`setup`; every per-suite target, `test:profile`, `test:budget` and the gate's tests in `hooks:verify` run under the tools interpreter (the F-10.1 F-2 obligation, closed); the basic tier is unchanged.<br>**Overseer repair dispatch** (introduced-by `622bd75` against 0014 section 5 and the no-silent-difference rule): `host` located the system file through `PATH` (a different file under Git Bash than PowerShell), and user/system attribute files and replace references differed from git silently. Fixed in `f585e87`: the system file comes from `GIT_CONFIG_SYSTEM`/`NOSYSTEM`, Git for Windows' registry `InstallPath`, or `/etc/gitconfig`, identical under three `PATH` orders and equal to `git var GIT_CONFIG_SYSTEM`; outside attribute files are read and a status-relevant attribute refuses with `ATTRIBUTES_UNSUPPORTED`; replace references refuse object reads with `REPLACE_REFS_UNSUPPORTED`.<br>**Findings:** F-1 and F-2 (introduced-by, fixed in `3aa5ef3`: no non-ASCII directory in the corpus; a damaged pack left open); F-3/F-4 (exposed-by: PowerShell walls exceed the Git Bash budgets, serial 159 s; ruled: judged on the baseline shell, PowerShell recorded; hypothesis, not measured: PowerShell's `cmd\git.exe` launcher; F-10.3 reports both shells); F-5 (unrelated: `test_profile.py` labels a `-C` path with a space as "git b"); F-6 (upstream Dulwich 1.2.21: `get_raw` does not verify loose ids, `read_reflog` fails on a message-less line, the reference container refuses `refs/top`/`ORIG_HEAD`/`FETCH_HEAD`, `create_bundle_from_repo` records the peeled commit of an annotated tag; worked around in the module). Two synthetic corpus directories from runs before F-2's fix remain in the user temp directory (the builder's delete was refused by the permission classifier; left for the Owner).<br>**Overseer verification at `9bab278`:** verify_seed PASS (165; seed 136); the nine suites under the tools interpreter OK (1,681 total; repository 53); the repository suite fails without Dulwich; counters-only budget PASS; no `subprocess` in the module; the registry read is read-only (`winreg.KEY_READ`). Decision 0014 **accepted** (Overseer) with these amendments. **Not verified:** Linux, macOS, POSIX modes, reftable/split/sparse indexes, submodule status, Task itself. | F-10 is evaluated at F-10.5. |
| F-10.3 Migrate the planning adapter's repository access (R1-R4) | **PASS (2026-11-09)**, qualified: Windows only (Linux at F-10.5); no target ran under Task (rendered) | `bd175bd`, read-path repair `41f0555`, `193edab`, budgets `f069c46`, evidence `72d2a84` and `1ca8975` | [Evidence](F-10.3-planning-migration.md). `planning_adapter.Git` is a facade over `integrations/repository/` (policy `repository` at every call site); `BatchReader`, the `cat-file` protocol, `Git._run`, `batch_argv` and the git one-shots are deleted; `archive` is replaced by `export_tree` (blob bytes); Backlog.md and OpenSpec launch through `run_tree` (a fake-launcher test leaves no process after a timeout; mutation to plain `subprocess.run` caught). Planning, lineage and dispatch keep their test ids and outcomes (104/146/82); `Equivalence.test_revisions` passes unchanged (20 forms); both lineage example projections byte-equal; **0 product git launches** (was 676; 27 remain attributed to the adapter file by the profile's origin rule, all made by tests: the oracle and `RealLauncher`). Live `test_live_backlog` 7/7 and `test_live_lineage` 6/6 on blob-bytes exports on this `core.autocrlf=true` host (`git archive` gave CRLF, the export 0 CR). Without Dulwich every dependent test fails naming `REPOSITORY_NEEDS_DULWICH`; none skips.<br>**STOP and resolution:** the first run missed the 4x traversal ratio (2.3x from Git Bash): the F-10.2 module read each object twice, kept no cache and missed into the pack listing (F-1, **introduced-by `622bd75`**). Overseer ruling: criterion kept; root-cause repair of the read path, no tuning. `41f0555`: a bounded (32 MiB, LRU) cache of objects verified against their id, parsed from the verified bytes; damaged objects never cached; 180 to 17 object reads per traversal. Measured interleaved, Git Bash: traversal **11.0-11.8x**, one-shot **11.0-11.6x** (PowerShell 17.7-18.6x and 17.4-18.4x); oracle rounds 3 and 6, chosen from the measured spread. Fresh-process import +73.6 ms (was +61.4), +106 ms with Dulwich loaded at first open. Performance wall budget 0.6 to 0.8 s by Overseer ruling (the plan-required oracle rounds are new measurement work: 0.27 s of 0.74 s); no other wall changed. Serial `task test` median: Git Bash **137.3 s** at the baseline (140.2 s at `f069c46`), PowerShell 144.8 s: the F-09 150 s criterion met in both shells. Launches 1,982 to 1,309.<br>**Launcher hypothesis measured (confirmed):** PowerShell's PATH `git` is `cmd\git.exe`, a launcher costing +6.7 to +7.0 ms and one extra process per launch, which predicts 7.1-7.3 s of the 7.9 s shell gap. **Findings:** F-3 (exposed-by) six `planning:`/`lineage:` command targets used the plain interpreter: fixed `193edab` with a `RequiredTargets` test; F-4, F-5 (introduced and fixed: `--record` without Dulwich, `run_tree` pipes); F-6, F-7 (stale "Proposed" wording; `AGENTS.md` command list: fixed). Residual: Dulwich lists `objects/pack` on each loose miss (about 0.55 ms per traversal; not patched).<br>**Overseer verification at `1ca8975`:** verify_seed PASS (165); all nine suites under the tools interpreter OK (planning 104, lineage 146, dispatch 82, repository 53, tools 1,079, others unchanged); counters-only budget PASS; only the performance `wall_s` changed in `policy/test-budgets.json`; no git verb left in `planning_adapter.py`; the cache code read (verify before insert, bound, close). **Not verified:** Linux, macOS, a packed repository's read cost after the repair, Task itself. | F-10 is evaluated at F-10.5. |
| F-10.4 Migrate the exchange push, the checkout snapshots and the checkout listing; retain the exchange verifier | **PASS (2026-11-09)**, qualified: Windows only (Linux at F-10.5); no target ran under Task (rendered); no real guest | module fix forward `fb9b25c`, rows `46c8d89`, `b49baed`, rulings `7986f49`, `6c905f2`, `08efd0a`, budgets `8ece2ca`, evidence `69a852c` and `2636d5e`; decision 0014 amended at acceptance | [Evidence](F-10.4-exchange-snapshots-listing.md). R5 `exchange_push` writes the bundle with the module and launches **0 git**; R6 keeps git (`init --bare`, `fetch`, `bundle verify`, `rev-parse`, `fsck --strict`; the set asserted by test); R7/R8 `profile_revision` and `repo-inventory/2` and R9 `checkout_files` and R10 `git_revision` on the module, records carrying `config_sources`. A Dulwich-written bundle passes `git bundle verify` and round-trips `verified: true`; the tampered bundle gives `verified: false`; the incremental bundle verifies. `checkout_files` equals git's listing on this checkout and on all 10 ignore-rule repositories. Contract corpus 962 to 1,109 answers (11 to 23 repositories), every earlier answer unchanged.<br>**STOP 1 (module defects, introduced-by `622bd75`, exposed-by F-10.4):** A, the listing dropped files under a directory a later rule re-includes (a scan would miss them); B, attribute macros and git's built-in `binary`; C, git's size rule for status. Ruling: fix the module first, by the git oracle; repaired in `fb9b25c`. Lesson: a differential corpus is judged by its rule-class coverage, not its size.<br>**STOP 2 (budget):** the repository wall 6.38 s over its 6.24 s limit and the serial median 149.6 s. Rulings: batch the git oracle (repository suite launches 359 to 235; no wall raised); one measured `deltify=True` experiment (did not finish in 600 s; the undeltified writer stays: bundle 3.1x git's, push 2.7 s against 1.1 s, `max_bytes` reached about 3x sooner, bound unchanged; decision 0014 section 10); git's ceiling directories in the module (`open_repository(..., ceilings=)`, `GIT_CEILING_DIRECTORIES`) with a stat-spy test; the stale profile description corrected (description only; QUALIFICATION.md needs no requalification).<br>**Budgets:** `8ece2ca` re-proposes counters only (tests 1,710 to 1,742, launches 1,309 to 1,208); **no wall changed**. **Overseer verification:** `verify_seed` PASS in both modes (165/136); the ceiling tests OK; `test:budget` from Git Bash FAIL once (contract 22.34 s, serial 159.4 s) while Windows Disk Cleanup ran, as in the builder's one failing run; rerun after it exited: **PASS**, serial 140.9 s (builder: 139.8 s; PowerShell 146.9 s, recorded only). Builder: all nine suites OK; pytest conformance PASS (`-n 0`, `-n auto`); `hooks:verify` rendered PASS.<br>**Plan-clause omission ruled:** the proof clause lists the pull's launches as init, fetch, bundle verify and fsck; the action's "per-ref check" is `rev-parse`, inside the R6 retention (decision 0014 sections 1 and 10 now name it).<br>**Open, carried:** discovery above the temporary root remains in 4 planning and 5 lineage tests (unrelated-but-detected path-boundary defect; test-only fix, next dispatch). The builder disclosed one deliberate spy run without a ceiling (21 stats above the corpus root) to prove the spy detects a walk. Not verified: Linux, macOS, any target under Task, any real guest. |
| F-10.6 Qualify Dulwich transports against the host Gitea: push, auth, ls-remote | **PASS (2026-11-09)**, qualified: Windows only (Linux at F-10.5); no target ran under Task (rendered); the full `task resolve` not run (its source-tag stage only) | slice 1 `0921d30`; transports `a934980`, `93781f9`; rulings `ab07a9f`, `53584ef`; budgets `836368c`; evidence `0ab555c`, `10d4402`, `b5627b6`; decision 0014 amended at acceptance | [Evidence](F-10.6-transports.md). The module gains `ls_remote`, a bare `clone` and `Repository.push` over smart HTTP with an in-memory `Credential` (no helper, no ssh, **0 launches** in every transport test). **Matrix:** all 24 rows of the `test_authorization_live` matrix equal, git against the module, for builder, planner, reviewer and verifier (pre-receive refusals give `PUSH_REJECTED`, 403 gives `PUSH_REFUSED`); the module allowed nothing git refused; anonymous push 401 gives `PUSH_REFUSED`. Fixture residue: commits on `work/authz-builder` and `work/authz-planner` only, as the git suite leaves. A module clone over HTTP passes `git fsck --strict`. **G14 established:** the eight locked tags (tag id and peeled commit) equal the lock; **R11 migrated** (`53584ef`): the resolver's source tags run on the module, 8 of 8 verified, 0 launches, the lock unchanged byte for byte; without Dulwich it fails with `REPOSITORY_NEEDS_DULWICH`, no git fallback. Token scan by fingerprint (never by value): 0 matches over 109 files; the gate found no secret.<br>**Slice 1** (`0921d30`, test-only, unrelated-but-detected from F-10.4): 4 planning and 5 lineage tests bound discovery at their temporary root; a stat guard shows 0 examinations outside a temporary root in both suites (1,231 and 2,039 examinations).<br>**STOP (budget) and rulings:** the repository wall 6.46 s over its 6.24 s limit (Overseer measurement; serial 147.3 s). R1: the transport and oracle tests are required work, so by explicit Overseer ruling only the repository wall rises, 4.8 to 5.9 s (the `propose` value from a quiet three-run Git Bash profile); R2: migrate R11 (decision 0014 section 1 settled it; the dispatch had under-scoped the paths); R3: codes `REMOTE_REFUSED`, `REMOTE_FAILED`, `HOOKS_UNSUPPORTED` accepted (decision 0014 section 10); R4: a redirect to another origin (scheme, host or port) must carry no credential: 16 subtests and an end-to-end loopback test, a mutation fails 17; urllib3 2.8.0 already strips it, no module change; R5: Dulwich 1.2.21 never sends `extra_headers` (reproduced; worked around in the module, pin-sensitive): duplicate check found none, ready-to-file draft in the evidence (Owner action OA-09).<br>**Overseer verification:** `verify_seed` PASS (165/136); basic prerequisites PASS; counters-only budget PASS; `test:budget` from Git Bash on a quiet host (Disk Cleanup had run and exited) **PASS**, serial 142.1 s, repository 5.8 s, contract 19.9 s. Builder: nine suites OK; conformance PASS (1,782 ids, 1,776 run); `hooks:verify` rendered PASS; `prereqs:components` PASS; `gitea:authz` 18 OK; `gitea:transport` 2 OK.<br>**Carried:** the lock's informational `resolver` string and the command line in `composition/inventory/LEDGER.md` still read `python -I composition/resolve.py` (next lock change; F-10.5's documentation). Not verified: Linux, macOS, proxies, authenticated HTTPS remotes, SHA-256 remotes, v0/v1 servers, pushes above 1 MiB, real cross-scheme or cross-host redirects. *(2026-11-10: external reporting is deferred by decision 0017 and its addendum; the upstream reference and any prepared report are internal knowledge, not pending work.)* |
| F-10.5 Cross-platform contract run, launch census guard, documentation and evidence | **IN PROGRESS (2026-11-11)**: the Linux finding is fixed (`3cf45cd`) and the OA-17 run in one Debian 13 guest matched the Windows reference (85 outcomes, digest `d5aa24a7...6d937`); not promoted to cross-platform qualification (Owner, OA-17): Linux git-oracle parity, the native Linux wheel, `write_commit` on Linux and macOS stay unverified | `f219724`, cost repair `6ab2cbc`, budgets `b09bd62` (counters only), evidence `5088899`; ceiling fix `3cf45cd`, evidence `2314681` | [Evidence](F-10-dulwich-migration.md); [OA-05 plan](F-10.5-oa05-guest-run-plan.md). **Census guard** `tools/tests/test_launch_census.py` (12 tests, AST over the tracked sources read through the module): 35 allowlisted sites, each on a retained row of decision 0014 (R6 `guest.py:run_git`; H1 the gate; B1 `verify_seed`; B2 `check_prereqs`; T 30 test sites in 13 files); it fails on an injected launch, a new launching module and a removed site (in memory, no product file edited); no site outside 0014's list. Docs: the tools-venv tier row, Dulwich verification rows (Windows PASS, Linux pending, macOS not yet verified); README component status only (no leaf status); `check_prereqs` INFO line (stdlib, offline, no Dulwich import); the LEDGER resolver line. **F-10 group, evaluated:** in-process operations, parity, integrity, grammar, codes, performance (11.0x), census and no-skip clauses met on Windows; Linux open (OA-05); macOS not yet verified.<br>**Fix forward:** the census cost made the contract wall fail (22.21 s against 21.97 s, introduced-by `f219724`); `6ab2cbc` cut it to 1.0 s, no wall changed. **Overseer verification:** `verify_seed` PASS (165); the census and `check_prereqs` tests OK; `test:budget` from Git Bash on a quiet host **PASS**, serial 142.6 s, contract 21.1 s (96% of its limit: a busy host can fail it). Builder: nine suites OK; conformance PASS (1,799 ids, 1,793 run); `test:all` PASS; `hooks:verify` rendered PASS; PowerShell 152.5 s (recorded only).<br>**Process note:** against the dispatch, the builder tried to run the OA-05 script without `--approved` to check its refusal; the session's permission guard blocked it and nothing ran. Corrected in the next dispatch. [OA-05 run](F-10.5-oa05-linux-run.md) (2026-11-10): 79 ok, 2 FAIL, 1 skipped; teardown verified. **2026-11-11 (OA-17):** [revision 4 run](F-10.5-oa17-linux-run-rev4.md), performed by the Overseer once: 84 ok, 1 skipped as expected, digest equal to Windows; teardown verified independently. |
| F-06.2 Host-service lifecycle contract and the Windows adapter | **PASS (2026-11-10)**, Windows only (Linux F-06.4, macOS F-06.5); decision 0011 stays drafted until F-06.3 completes, as the plan sets | inventory fix `5e8b031`; contract and adapter `8a87d7d`; fixture repair `05130af`; budgets `593409a` (counters and the new `platform` suite only); evidence `204561b`; README fix `c015e6a` | [Evidence](F-06.2-platform-windows.md). `integrations/platform/` holds `platform_contract.py` and `platform_windows.py`, and `gitea_host.py` reaches every Windows call through the adapter (of 426 lines removed from `gitea_host.py`, 297 moved verbatim, 20 stayed elsewhere and 65 are the intended changes). Verbs: install, up, down, restart, status, inspect, verify; provision, rotate, retire; upgrade, recover, uninstall. Records: `aieh-platform/1`, `aieh-asset/1`, `aieh-gitea-host/1` with the optional `platform.asset_key`, `aieh-service-run/1` (still reads `aieh-gitea-run/1`), `aieh-readiness/1` (carries its platform), `aieh-service-transition/1`. The nine new refusal codes each carry a remedy, and existing messages are unchanged (each covered by a named test). **Proof:** live `gitea:verify` (19/19) and `gitea:status` byte-identical at `13f2329`, `8a87d7d` and `593409a`; the live instance is the same Gitea process throughout. An I7 no-exposure scan follows every live act (status, inspect, verify, `verify --readiness`, `gitea:authz` 18 OK with 284 probes); the live lifecycle test ran on a fixture instance in a temporary root (install through recover, a supervisor kill included; 14.6 s). Never run live: down, restart, upgrade, recover, uninstall and every credential act.<br>**Fix forward:** the new tests put the gitea suite over its wall limit (3.46 s against 3.25 s, introduced-by `8a87d7d`); `05130af` repaired it, and no wall changed. The `fd-outer-server-local-recovery` wording, in the inventory (`5e8b031`) and the security README, is corrected to match OA-03: imports and registrations come before the lease claim, and the directory creation and `git init` after it (introduced-by `e17ac2b`).<br>**Overseer verification:** `verify_seed` PASS (165/136); `cmp` of the captured before and after outputs shows them identical; live status running, with the same process; `test:budget` from Git Bash on a quiet host **PASS**, serial 142.4 s, contract 20.9 s (95% of its limit), gitea 3.1 s against 3.25 s. Builder: ten suites OK (platform 40, gitea 121 with 8 opt-in skips); pytest 1,844 passed; `hooks:verify` rendered PASS; PowerShell 150.8 s, recorded only (repository 7.78 s over its limit there, as at F-10.5).<br>**Overseer ruling (sequencing):** the plan's F-06.2 action lists the whole verb set, so the upgrade, recover and uninstall verbs and the transition record are F-06.2's code. F-06.6 keeps its full proof: the disposable-instance rehearsal (a real cross-version upgrade needs a second pinned version), reboot or sign-out behaviour, and the inspection of the egress proxy. Semantics chosen within the accepted design and recorded in the evidence: uninstall empties `ephemeral/tmp/gitea/` only; upgrade backups go in `persistent/gitea/backups/<transition id>/`; retire covers role bots only. **Not verified:** Linux, macOS, keyring; a real upgrade; retire against a running Gitea; `CREDENTIAL_PROVIDER_LOCKED` and `SUPERVISION_UNAVAILABLE` from real OS failures. **Carried:** the gitea suite has little wall headroom, so its next test is likely to need a wall re-proposal by ruling. |
| F-06.3 Credential provider adoption (keyring for POSIX; Windows provider kept; fail closed) | **PASS (2026-11-10)**, Windows; the real-store cross-read ran once under Owner action OA-10 ([evidence](OA-10-OA-11-owner-acts-2026-11-10.md)); decision 0011 accepted | provider, factory, receipts, pins `437a578`; budgets `c3e9c0f` (counters and the new `credentials` suite only); evidence `28b7d0b` | [Evidence](F-06.3-credential-provider.md). `integrations/credentials/credential_provider.py`: the ctypes Credential Manager provider moved (methods AST-identical to `f6e82bc`), `KeyringProvider` instantiating `SecretService.Keyring()` or `macOS.Keyring()` by name with a viable `.priority`, and a fail-closed factory: Windows never imports keyring, anything else refuses `NO_CREDENTIAL_PROVIDER`, and `get_keyring()`, a keyringrc, `PYTHON_KEYRING_BACKEND`, the CLI and keyrings.alt are shown ignored by test; `doctor` reports the provider (Windows: `windows-credential-manager`, viable). **Overseer ruling:** keyring is installed in the tools set on every platform and is never the Windows provider (decision 0011 draft: "keyring kept off the Windows provider"); keyring 25.7.0 and its dependencies copied byte for byte from the F-01.2 locks into the tools and dev locks, with their `sys_platform` markers; `tools:install` installed them wheels-only. Every rotate and retire act (`gitea_roles`, and `finalize-credentials` as rotate) writes an integration-store receipt, fingerprints only, and reads it back (`CREDENTIAL_RECEIPT_UNREAD` otherwise); fixtures only. Live acts: `gitea:status`/`verify` byte-identical before and after (stdout and stderr), `gitea:authz` 18 OK, `gitea:roles -- status` (read-only, by code read first) four entries present; I7 clean after each; no live entry written, deleted or enumerated.<br>**Fix forward (introduced-by an uncommitted draft):** one test run wrote 5 synthetic receipts into the real managed root's integration store; fixed before the commit (a fixture context must bring its own store). The file remains: Owner action OA-11. **Process note:** the builder also ran `dev:install` (the product's installer; the dev lock mirrors the tools set), which the dispatch did not list.<br>**Overseer verification:** `verify_seed` PASS (165/136); `cmp` of the before and after captures identical; the credentials, gitea and platform suites run with `AIEH_DATA_ROOT` redirected to an empty directory wrote nothing there; read of the prepared real-store test; `test:budget` from Git Bash on a quiet host **PASS**, serial 143.8 s, contract 21.0 s, gitea 3.2 s against 3.25 s. Builder: eleven suites OK (credentials 51 with the opt-in skip); pytest 1,904 passed; `hooks:verify` PASS.<br>**Carried:** keyring 25.7.0's `macOS.Keyring` cannot look an entry up by name alone, so the factory refuses it: F-06.5 needs a decision on entry lookup. The gitea suite's wall has almost no headroom. **Real-store cross-read (OA-10, 2026-11-10, one run at `867381b`):** PASS: write, separate-process read by name (fingerprint only), delete, absence from a separate process and from the test, I7 clean; no other entry touched. **Not verified:** Secret Service and Keychain on real hosts (F-06.4, F-06.5); receipts against the live Gitea; `CREDENTIAL_PROVIDER_LOCKED` from a real session. |
| P-04.1 Record Owner acceptance and mint outcome identity | **PASS (2026-11-10)**, on fixtures, Windows; no real acceptance recorded anywhere | recorder, shared record and `write_commit` `5e205f3`; budgets `43d3724` (counters and the new `owner` suite only); evidence `c0bb1df`; OpenSpec check `d415eb3`; decision 0014 amended at acceptance | [Evidence](P-04.1-acceptance-recorder.md). `integrations/owner/`: `owner_decision.py` (the shared Owner decision record `owner-decision/v1`: `decisionId` uuid4, `kind`, `subject`, `shown` {summary, nonce, expiresAt}, `statement` {text, attributedTo, channel, reference}, `recordedBy`, `recordedAt`; `authorize-operation` named and refused until P-04.2) and `acceptance_recorder.py` (`task owner:accept`: sets the item's authority and acceptance, mints the outcome UUID into `x-outcomes`, writes the record and commits in process). Refusals with stable codes and remedies, each tested with the branch, work tree and index unchanged: a missing acceptance, one authored by a model (`agent:` attribution or an `openhands:` reference), a statement not attributed to the Owner, re-minting (the uuid generator never called), and the challenge, name and reference refusals. **Proof:** a recorded acceptance resolves through the lineage objective resolver (unresolved at the previous commit); the recorder runs that check before the branch moves; `--amend` keeps the id and the earlier pinned reading still resolves. OpenSpec 1.16.0 (locked npm install in a throwaway directory): `validate --strict` accepts a change holding the record, `archive` moves `owner-decisions/` and `.openspec.yaml` byte-identical, and the resolver resolves the archived change (opt-in test `test_live_openspec.py`).<br>**Repository module:** P-04.1 is the first write, `Repository.write_commit` (decision 0014 sections 6 and 8): hooks refused before any write, a compare-and-set branch update, no launch; the census guard green with no new site. Exposed-by P-04.1 and repaired: Dulwich writes stale index extensions back, so the next `git commit` would revert the change; the write drops them (pin-sensitive, decision 0014 section 10).<br>**Overseer rulings** (the shared shape and the Owner-attribution rule are what the accepted Owner-authority design binds for P-04.1; the rest is the recorder's own form): the record lives at `openspec/changes/<change>/owner-decisions/<decisionId>.json` in the recording commit, so it moves with the change; a leading `format` field is kept, and decision 0012 lists it when committed at P-04.2; the challenge is stateless (`prepare`/`record`, single use detected from the committed records, 60-minute default expiry, 7 days at most), and the Owner's statement need not repeat the nonce. P-04.2's stricter authenticity rules (its own challenge state, a statement naming the operation id) are for merges and stay its own; the item's `acceptance` is the statement's reference; `--amend` is required to re-record; commit trailers `AIEH-Decision-Id`, `AIEH-Outcome-Id`, `AIEH-Recorder`. The recorder checks what the transcriber declares; it does not authenticate the Owner (the accepted bootstrap channel).<br>**Overseer verification:** `verify_seed` PASS (165/136); the owner and repository suites with `AIEH_DATA_ROOT` redirected to an empty directory OK and the directory still empty; census OK; `test:budget` from Git Bash on a quiet host **PASS**, serial 147.5 s, contract 21.0 s. Builder: every suite OK; pytest 1,948 passed; `hooks:verify` PASS.<br>**Carried:** the serial total is close to the 150 s gate; the next leaf adding tests needs test-runtime work first (Overseer decision). **Not verified:** a real acceptance or project repository; the statement against a conversation store (U-02.x); three recorder codes without a trigger test; Linux and macOS. |
| P-04.2 Record Owner authorization and merge it as aieh-owner | **PASS (2026-11-12)**: accepted after the Owner's direction to correct OA-21's obligation mapping (Decisions, 2026-11-12). Every clause met, live or on the recorder's real code (section 17). The custody sentence covers the credential the leaf's artifact holds, `cred-gitea-owner-account`, inspected live three times. The Owner's own credentials were not inspected and are not claimed; finding `fd-owner-credential-custody` is re-homed (see Decisions). Earlier, **IN PROGRESS (2026-11-10)**: the recorder fails closed (decision 0012 point 6, OA-15a): no merge without a `verified` answer from the protection verifier; the command line's verifier is now OA-16's protection check (built offline 2026-11-11), which answers `unverified` (`CREDENTIAL_MISSING`) until the auditor is provisioned, so the recorder still merges nothing; the live exercise is reworked into two phases with the Owner between (OA-14); the fixture's protection declaration is total (F-C). Open: the OA-16 live acts (provisioning, the fixture declaration, the negative tests, the qualification), then the live exercise (OA-14) | recorder, subject and suites `db212d2`; records `d67bd62`; live exercise written `024d84f`; tests from the mutation check `bcf94ce`, `32a9591`; test fixtures `538847a`; budgets `992c855`; evidence `5402a7e`; fix-forward `7970bf7`, `03bb85f`; fail-closed seam `0c57f0a`; two-phase exercise `d720fb8`; F-C `6e3a481`; tests from the mutation check `6f10385`; budgets `68a3bc2`; evidence `f14c50b`; OA-16 protection check, auditor role and wiring `20377ea`; tests from the mutation check `a63636e`; documentation `7fc6ef6`; evidence `394bfa1`; OA-16 preparation: escape-probe `e318249`, documentation `5f54be2`, records `68fae80`, tests from the mutation check `4e30564`, evidence `6384d29` | [Evidence](P-04.2-authorization-recorder.md); [decision 0012](../decisions/0012-owner-authorization-channel-and-gitea-owner-identity.md) (Proposed). 35 stable refusal codes; one merge per decision bound to the approved head and manifest digest with six trailers and a write-ahead receipt; a lost answer resolved by reading, never by merging again; no token minted or used; mutation check 157/171 killed (14 equivalent or unreachable), `resolve` 11/11 after the fix-forward. **Overseer verification:** the STOP finding read at the pinned Gitea 28.3.0 source (`branch_protections` behind `reqToken(), reqAdmin()`); publication gate and private-path grep clean; verify_seed PASS; owner suite 86 OK; inventory and role-token checkers PASS; budget check PASS at `5402a7e` (serial 141.5 s; cleanmgr absent before and after); the code read for the credential, merge and read-back paths. **Rulings:** F4 the 15-minute settle rule rejected (an open, unmerged pull request stays `unknown`; removed `7970bf7`); F2 `planned_performer` reference-checked; F10 (approvals checked by Gitea at merge time, not before) accepted as disclosed. **Not verified:** anything against a real Gitea; the custody inspection; the protection rule's unobservable fields; any real Owner authorization **2026-11-10 (seam, phases, F-C):** `Context.verifier(repository, base, phase)` returns `ProtectionVerdict` (`verified`/`drift`/`unverified`, detail, digest); no verifier, an exception or a malformed answer is `unverified`; `record` asks it as the last read before the receipt is reserved and the merge sent and refuses `PROTECTION_DRIFT` or `PROTECTION_UNVERIFIED` (nothing sent, no receipt, no decision record); after the read-back it asks again and records a differing answer as the disclosure `PROTECTION_CHANGED_AFTER_MERGE` (the merge stands); 37 refusal codes. Phase `prepare` opens the fixture proposals, runs the bot-merge negative controls (a success is a SECURITY FAILURE) and writes the recorder's real challenges and a presentation, merging nothing; phase `record` reads the Owner's statement from a file exactly as written and checks it with the recorder's own checks before any Gitea call or credential read; the exercise never writes a statement. `protection_rules()` declares all 34 Gitea 28.3.0 BranchProtection fields (bypass allowlist disabled and empty on every rule, F-A); one value changes: `main` `block_on_outdated_branch` true (Overseer ruling: accepted; it keeps the merged tree the approved head's; not applied to the live fixture). Mutation check: recorder lines 14/14 killed; live-phase functions 39/39 after the added tests. **Overseer verification:** the diff read: the one merge call (`session.merge`) is reached only after `require_verified`; the live test constructs no statement; verify_seed PASS; owner suite 113 OK, gitea suite 134 OK (scratch data root left empty); inventory checker PASS; budget `check --run` PASS at `f14c50b` (serial 145.3 s; Disk Cleanup absent before and after); publication gate and private-path grep clean. **Rulings:** F13 (exposed-by F-C: with an outdated base B would get 405 before 409) repaired by recording the stale-head control first; F14 (inferred from source, not observed: after the hook's push Gitea re-checks the pull request and may answer 405 "try again later", or 500, before the 409 head check) carried to the verifier slice: the control's property is that nothing merges and `main` does not move; which Gitea refusal is observed is recorded, not assumed; no record can reach the merge before then. Detected, not changed: `integrations/gitea/README.md` summarizes the rules without `block_on_outdated_branch` (carried to the same slice). **OA-16 verifier (2026-11-11):** [evidence](P-04.2-protection-verifier.md). `integrations/gitea/protection_check.py` reads, as `aieh-bot-protection-audit` with a `read:repository` token, a fixed set of GETs only (any other method or path raises before sending): the token's identity and exact scope, the repository view and the auditor's `permissions.admin`, every rule (34 fields, bypass allowlists included), the exact rule set, precedence for `main` against Gitea's own `effective_branch_protection_name` (Gitea 28.3.0's order read at the pinned source: priority, then a plain name before a glob, then the earlier created), 11 repository merge settings, collaborators with Gitea's computed permission, teams and deploy keys; `drift` on any difference, `unverified` on a missing, unexpected or wrongly typed field, a list not read whole, a failed or lost read, a precedence the model cannot confirm, a rejected or wrong credential, or a missing entry (zero requests sent). The recorder's `managed_context` configures it through `protection_verifier`; no refusal code added (37). Gitea's merge-time evaluation and the remaining check-to-merge window are documented (gitea README, `fd-protection-check-toctou`). Records `planned`: `cred-gitea-protection-audit`, `op-protection-verify`, the recorder role's grants. A live negative and qualification module is prepared, environment-gated, never run. F14 carried (the stale-head control's property is that nothing merges and `main` does not move; the refusal observed is recorded); the gitea README's rule summary and the `security/README.md` row for `fd-child-conversation-tool` fixed. Mutation 108/115 killed (7 equivalent or unreachable), 4 workers, no window, 0 leftover processes. **Overseer verification:** the check's `observe`, `judge` and `verify` and the recorder wiring read (the recorder's `check_protection` turns any verifier exception into `unverified`); verify_seed and the five contract checkers PASS; owner 126 OK, gitea 188 OK; budget `check --run` PASS at `394bfa1` (serial 138.3 s; cleanmgr absent before and after). **Rulings:** P1, one lane row for the new credential in `policy/ci-token-secret-policy.json` (outside the brief's paths, required by `check_ci_policy`), accepted: the lane map must name every inventory credential, and `trusted-lane` matches `cred-gitea-owner-account`'s; P7, `provision` (identity with token) and `fixture` (collaboration with protection) bundling acts, accepted as matching the Owner's own grouping (provisioning of the identity or credential; changing collaborators or protection; live merge tests), no command split. Carried: P2, the recorder role's realization row (needs `test_check_role_tokens`'s map) to the provisioning slice; `nm-owner-gitea` does not list the new credential; the escape probe needs a repository the auditor is not a collaborator of. Process deviations disclosed by the Builder: one stat of the tools interpreter's executable under the managed data root (only executing it is allowed) and one fixed one-second sleep, both corrected in the next dispatch. Not verified: anything against the live Gitea. **OA-16 preparation (2026-11-11):** [section 13](P-04.2-protection-verifier.md). `gitea_roles.py escape-probe` (`task gitea:roles -- escape-probe`), a separate Owner act never called by `provision` or `fixture`: as the site administrator the way `fixture` acts (basic authentication, no token left), it creates the private, empty repository `aieh-authz-fixture/escape-probe` with no collaborators; one existing exactly so is reported and left unchanged, any other state refused (`ESCAPE_PROBE_STATE`); it never addresses `authz`; the live negative test uses it by default. `nm-owner-gitea` lists `cred-gitea-protection-audit`; the recorder role's realization row (planned, P-04.2) added with `test_check_role_tokens`'s map. Mutation 49/49 killed, 4 workers, no window, 0 leftover processes. **Overseer verification:** the command's code read (one write, the creation, only after a 404; read-back required); verify_seed and the four contract checkers PASS; gitea suite OK (13 live classes skipped); role-token tests 73 OK; budget `check --run` PASS at `6384d29` (serial 138.9 s; cleanmgr absent before and after). **Rulings:** the accepted existing state is exactly what the command creates (private, empty, not archived, no collaborators); finding P8 (Gitea answers 404 both for a repository the token cannot see and one that does not exist): the repository's existence is evidenced by the `escape-probe` report taken immediately before the negative phase within the same Owner act, and no site-administrator read is added to the negative phase, which keeps its credentials to the auditor's and the verifier bot's. Not verified: the command against a real Gitea (no collaborator added at creation, `empty` reported). |
| P-04.3 Promote approved dispatch inputs through recorded decisions | **PASS (2026-11-13)**, the engineering manager's verdict (decision 0018 point 1): every proof clause shown offline, through `load_manifest` with the real verifier over a throwaway store and the real recorder (evidence section 2); independently reviewed and re-reviewed (decision 0018 point 1) | records and commands `dca60ac`, `3b752c9`; enforcement `491aa8d`; unsettled-promotion fix-forward `518a026`; review fix-forward `6878d1b`, `e13607f`, `535183b`; decision 0020 and evidence `2f9041c`; inventory `83ad72b` | [Evidence](P-04.3-dispatch-input-decisions.md); [decision 0020](../decisions/0020-dispatch-input-decisions-design-acceptance-manifest-promotion-and-load-enforcement.md) (Accepted, engineering manager); decision 0012 Current facts (2026-11-13). Architect consultation, gates B and G. **Built:** two kinds in `owner-decision/v1` (`accept-design`, `promote-manifest`); the sibling `delegated-decision/v1` (decision 0018 points 3.2 and 3.3, decided by `agent:product-manager` only); the dispatch-input commands (`integrations/owner/input_recorder.py`, `task owner:design`, `task owner:promote`), the only writer of the live manifest; the store series and the verifier (`integrations/owner/input_decisions.py`); `load_manifest`'s refusals `MANIFEST_NOT_PROMOTED`, `DECISION_RECORD_INVALID`, `MANIFEST_PROMOTION_UNCONFIRMED`, `MANIFEST_DIGEST_MISMATCH`, `DECISION_REPLAYED`, `DESIGN_ACCEPTANCE_MISSING`; the approval view naming each entry's approving record; `resolve`, `admit` and `dispatch` accept only a manifest `load_manifest` returned. Manifest schema v1 unchanged. Offline only: no live manifest, live store, live Owner record, Gitea, credential, guest or network. **Readiness of delegated promotion:** it fails closed until the log holds an `Owner standing authorization:` entry (decision 0020 point 7); none exists. | - |
| E-05.1 Bring up the D1 demo Work: one OpenSpec change and one Backlog.md task in the demo repository | Not started | - | Added by the plan amendment `f3a6c92` (2026-11-12) | - |
| E-05.2 Admit the D1 stage's ACP agent block, bound to its template digest | **IN PROGRESS (2026-11-13)**: built and tested offline against a CANDIDATE template; the verdict waits for S-03.3's qualified template and the checked-in profile's pin (the engineering manager's ruling below) | build `a5eadd2`; review fix-forward `d9e9ebe`; evidence `087c138` | [Evidence](E-05.2-d1-stage-admission.md). Added by the plan amendment `f3a6c92` (2026-11-12). **Built:** a profile declares `provisioning.agent_server.stage_create_template {stage, path, sha256}` for the D1 stage (`implement`); admission then uses that pin as the create template, refuses any other agent block (`BODY_NOT_TEMPLATE`), a template without an ACP block (`AGENT_BLOCK_NOT_ACP`) and the F-04.2 or a disposable-tagged fixture (`STAGE_TEMPLATE_DISPOSABLE`), at admit and again at `send_create`; the policy digest binds the template's sha256 into the attempt. The candidate `profiles/strong-windows-qemu-whpx/agent-server/d1-create.json` carries `acp_model` `candidate-unselected` and is pinned by no checked-in profile. Independently reviewed (12 of the review's 13 mutants killed in its log; E6, the pin's profile-prefix check, is reported run by line number but not logged); F2 fixed so `send_create` re-runs the content checks. **Ruling (engineering manager):** the proof's "refuses the F-04.2 disposable fixture template for a real stage" must hold on the approved profile, so the checked-in profile's pin (and with it the change to `test_the_checked_in_profile_declaration_admits_when_operational`) lands with S-03.3's qualified template, sequenced with E-01.3.2's disposable attempt; in E-05.2 "a real stage" is the D1 stage, other stages being A-01.2's. |
| E-05.3 Pin a digest-bound agent assignment with no Skills for D1 | Not started | - | Added by the plan amendment `f3a6c92` (2026-11-12) | - |
| E-05.4 Return an attempt's result to a bot work/ branch and an unreviewed draft pull request | Not started | - | Added by the plan amendment `f3a6c92` (2026-11-12) | - |
| E-05.7 Provision the authorization repository and admit it, alone, in the managed recorder (carved from G-03.1 for D1) | **PASS (2026-11-13)**, the engineering manager's [verdict](#e-05-7-verdict-2026-11-13); offline build [record](#e-05-7-offline-2026-11-13); live half: Owner act OA-30, performed once and verified | build `1903d6c`, `9c53029`, `d25d9ae`, `5657358`; fix-forwards `fa02e3d`, `05520d9`, `02fc9c4`, `73639f4`, `2dd731e`; records `ddb257d`, `48fae7c` | [Evidence](E-05.7-authorization-repository-offline.md). Added by the plan amendment `bbbad04` (fix-forward `3a4af34`); carved from G-03.1 for D1 ([decision 0022](../decisions/0022-authorization-repository-the-one-ledger-provisioned-for-d1.md)) | - |
| E-05.6 Admit the D1 stage's create secrets: the attempt's inference token and endpoint | **PASS (2026-11-13)**, the engineering manager's [verdict](#e-05-6-verdict-2026-11-13); offline by construction; independently reviewed in three passes | build `aa32a87`; fix-forwards `c6b90c8`, `d5fcbd7`, `4966416`, `8d47cac`, `b977105`, `44a83ab` | [Evidence](E-05.6-d1-stage-create-secrets.md). Added by the plan amendment `bbbad04` (fix-forward `3a4af34`); carved from A-01.2 for the D1 stage | - |
| E-05.5 Demonstrate D1: one contained AI-assisted coding task to a verified result and a draft pull request | Not started | - | Added by the plan amendment `f3a6c92` (2026-11-12) | - |
| P-05.1 Move the repository's own Work into Backlog.md and OpenSpec | Not started | - | Added by the plan amendment `f3a6c92` (2026-11-12) | - |
| F-09 runtime headroom (Overseer slice under the Owner's 2026-11-08 test wall-clock directive; F-09 patterns, no new leaf) | **PASS (2026-11-10)**: serial median 147.9 to 137.2 s (builder), 137.5 s (Overseer); test code, fixtures and budgets only | gate fixtures `49e8010`; `guest.py` compiled once `c5132f4`; checker fuzz copies and verifier golden repository `cb5a751`; verifier baseline launches `98bb781`; budgets and baseline at `98bb781` `50e834a` (counters, and walls that fell only); evidence `6a70893` | [Evidence](F-09-runtime-headroom-2026-11-10.md). Opened because the serial total stood 2.5 s under the 150 s gate after P-04.1. Savings: the gate's fail-closed tests 5.5 s (the timeout test waits the gate's shortest accepted timeout, 1 s, and now asserts `timed out after 1s`; one pinned stub scanner runs each behaviour, so one golden repository pair serves all five), checker fuzz copies 1.6 s (re-parse instead of deep copy), `guest.py` compiled once per process 1.4 s (`tools/tests/module_code.py`, a new module per load, its own 3 tests), the API probe server's shutdown poll 0.9 s, the gate golden pair 0.5 s (relative origin URL, empty init template), the seeded script's syntax tree parsed once 0.5 s, the verifier's baseline tests 0.3 s. Launches 1,236 to 1,158; tests +3. No assertion removed, no test skipped, no product, integrity-tracked or record file touched.<br>**Equivalence:** the 1,973 unittest ids common to before and after have identical outcomes; pytest conformance serial and xdist PASS (1,976 ids); `-m "not e2e"` identical serially and under xdist; 12 of 12 mutations killed in a throwaway clone. Walls that fell: tools 77.5 to 71.1, lineage 18.1 to 14.0, dispatch 5.0 to 4.6, planning 12.1 to 12.0, unit 23.8 to 22.3; none rose. **Fix forward (introduced-by an uncommitted draft):** an empty init template in the owner fixture broke a hooks-refusal test, because the repository module reads hooks and `info/exclude`; reverted there and kept only for repositories git alone reads.<br>**Overseer rulings:** the ~135 s target was the Overseer's, not the Owner's gate; 12.5 s of headroom suffices for the next leaves. Both remaining options are declined: pointing `test_guest`'s Smoke and Inventory tests at a fixture repository changes what they inventory (the real checkout), and sharing one allowlist across the `WithRealScanner` pairs changes security tests' inputs. **Overseer verification:** `verify_seed` PASS both modes (165/136); all 12 suites OK with `AIEH_DATA_ROOT` redirected to an empty directory, still empty after; read of the budget and test diffs; `test:budget` from Git Bash on a quiet host (no `cleanmgr` before or after) **PASS**, serial 137.5 s, contract 21.0 s. Builder: `hooks:verify` PASS.<br>**Unrelated but detected (carried):** `task test:categories` fails under the plain interpreter it uses, because `test_credential_provider` imports keyring, which only the tools interpreter has; it passes under the tools interpreter. **Remaining structural costs:** the real-scanner gate tests 15.1 s, crash-matrix workers 7.9 s, the netprobe listener 6.7 s, the verifier 8.1 s, checker fuzz 7.8 s, the batch launcher's ceilings 3.4 s. **Not verified:** PowerShell timings; POSIX hosts. |
| F-09 contract headroom (Overseer slice under the Owner's 2026-11-08 test wall-clock directive; F-09 patterns, no new leaf) | **PASS (2026-11-10)**: contract median 21.58 to 18.59 s (limit 22.10 s), serial 142.2 to 139.2 s (builder, interleaved); test code, one Taskfile target and budgets only | verify_seed work copy `16dbb89`; `test:categories` under the tools interpreter `8386ebf`; budgets and baseline `5f1b60d` (counters; the tools wall fell 73.0 to 72.0, none rose); evidence `5200157` | [Evidence](F-09-contract-headroom-2026-11-10.md). Opened because the contract category stood about 0.1 s under its limit after Q-02.1. **Cause, measured first:** on this host the first read of freshly written files costs about 35 ms per MB, so each writing verify_seed test paid it on a private seeded copy. **Fix:** one work copy per class, restored before each writing test and asserted equal to its source (every file's sha256 and every directory) in `setUp`; inputs, assertions and launches unchanged. **Equivalence:** the same 2,075 unittest ids and outcomes before and after; pytest conformance serial and xdist PASS; `-m "not e2e"` identical serially and under xdist; 9 of 9 mutations killed in a throwaway clone. mkdtemp 1,068 to 1,052 (the 16 private copies no longer made).<br>**Carried defect repaired forward (unrelated-but-detected at F-09 runtime headroom):** `task test:categories` imported keyring under the plain interpreter; it now finds `<tools python>` as `test:profile` and `test:budget` do, checked by `RequiredTargets`; PASS.<br>**Overseer verification:** `verify_seed` PASS both modes (165/136); the changed test files OK with `AIEH_DATA_ROOT` redirected to an empty directory, still empty after; `test:categories` PASS; read of the Taskfile and budget diffs; `test:budget` from Git Bash: a first run with Disk Cleanup starting mid-run discarded (157.8 s), the rerun on a quiet host (no Disk Cleanup before or after) **PASS**, serial 139.4 s, contract 18.7 s. Builder: all 12 suites OK; `hooks:verify` PASS.<br>**Process note:** the builder's first after-profile ran while Disk Cleanup was running and was discarded (its pre-check printed but did not stop the run). **Remaining:** the ~138 s aim is missed by about 1 s; the two remaining options change what a test reads (`test_guest` Smoke/Inventory on a fixture repository; one shared allowlist for the real-scanner gate tests) and stay declined. The gitea suite is the tightest wall (3.22 of 3.25 s). **Not verified:** PowerShell timings; POSIX hosts. |
| F-09 gitea headroom (Overseer slice under the Owner's 2026-11-08 test wall-clock directive; F-09 patterns, no new leaf) | **PASS (2026-11-10)**: gitea suite median 3.28 to 2.33 s; wall 2.5 to 2.4 s; no wall rose; test code and budgets only | tests `c9a2db4`; budgets `86ac0b6`; evidence `057dc06`; F-2 fix-forward `1654271`, evidence `5d3bda5` | [Evidence](F-09-gitea-headroom-2026-11-10.md). Shared managed roots per starting state, restored and checked byte- and mode-exact before each test; the three job supervisors started together; same 132 ids, outcomes and digest; mutation checks killed every product and fixture break. F-1: the 1.0 s window of the job control test is a negative control's observation window, kept (Overseer ruling). F-2 (introduced-by `c9a2db4`): a failed `setUpModule` leaked its roots; repaired. **Overseer verification:** budget `check --run` PASS at `5d3bda5` (gitea 2.4 s, serial 146.9 s; Disk Cleanup was running during this run, so the pass is an upper bound under load) |
| F-09 serial headroom (Overseer slice under the Owner's 2026-11-08 test wall-clock directive; F-09 patterns, no new leaf) | **PASS (2026-11-10)**: store suite median 19.0 to 11.1 s; serial A/B median 152.2 to 141.2 s on the same host; the inference suite budgeted under 150 s; no wall rose | tests `e89a097`; budgets `e00fb06`; evidence `c4cf76a` | [Evidence](F-09-serial-headroom-2026-11-10.md). Trigger: S-03.2 slice 1 stopped at its budget step (serial median 154.5 s; the new suite adds about 1.7 s; unchanged suites measured 3-7 % slower than the `6f10385` baseline on the day). **Overseer ruling:** the Owner's 150 s ceiling is not raised; headroom first. The store's crash-matrix and restart tests start each step's workers together across independent rows (fresh store per row, the same order within a row, the same 57 and 10 launches and temporary directories), with one added assertion that every row ran every step; same test ids and outcomes (one new config test); mutation 14/14 killed. **Overseer verification:** Overseer budget `check --run` at `c4cf76a` (Disk Cleanup absent before and after): serial median 144.6 s, inference 1.7 s and store 11.6 s within their walls, one failure in an untouched suite, the repository suite (median 7.86 s against its 7.67 s limit; the Builder measured 7.21 s): unrelated-but-detected host drift on a suite chronically near its limit; no wall raised; a repository headroom slice follows (the gitea precedent). Detected, not changed: the repository suite (7.21 of 7.67 s) and the contract category (20.1 of 22.1 s) sit near their limits on the day |
| F-09 repository headroom (Overseer slice under the Owner's 2026-11-08 test wall-clock directive; F-09 patterns, no new leaf) | **PASS (2026-11-10)**: repository suite median 7.26 to 4.82 s; wall 5.9 to 4.8 s; no wall rose | tests `3dddcd7`; budgets `89196ae`; evidence `dc45e35` | [Evidence](F-09-repository-headroom-2026-11-10.md). Trigger: the Overseer's budget run at `c4cf76a` failed the untouched repository suite (7.86 s against its 7.67 s limit); the wall was not raised. The git oracle fixture's 191 independent read-only launches, two tests' launches and the corpus extraction run concurrently; the same launches, arguments, environment and answers (recording mode keeps its exact 693-launch order; equivalence checked against the previous module over the same corpus); one added assertion; nothing new stat-ed above a test's temporary root; mutation 8/9 killed (1 equivalent). The pending OA-17 run binds `3cf45cd` and is unaffected; the thread pools are not yet run on POSIX. **Overseer verification:** repository suite 106 OK (data root left empty); budget `check --run` PASS at `dc45e35`, Disk Cleanup absent before and after |
| F-03.1 Select managed-VM providers and isolation contract | PASS (2026-11-06), specification only; pushed | `39912fd` | `profiles/README.md` (contract: strong and trusted-workload tiers, properties P1-P12 with inspection methods, lifecycle, disclose-and-refuse with `TIER_UNAVAILABLE`, no nested virtualization assumed, remote-Linux minimum contract, Owner conditions C1-C7, version floors and pin rule), `profiles/matrix.md` (every non-unverified cell cited), `profiles/properties.json`. For each OS a non-nested strong path is specified: Windows QEMU+WHPX (reference, Owner W1) or remote Incus; Linux Incus VM; macOS Lima. The Builder validator passes; the Overseer re-ran it and checked coverage. Five sources did not fully confirm decision 0003; the corrections are recorded as current facts there. **Every runtime claim is UNKNOWN.** Host acts A1-A3 are pending separate Owner approval. | F-03 (Large): not evaluated until F-03.4. |
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

- **2026-11-06: [0003](../decisions/0003-execution-guest-providers-and-isolation-contract.md) Accepted.**
  Architect consulted at gates C and G before F-03.1. The decision sets the execution-guest providers and
  the isolation contract (P1-P12, strong vs trusted-workload tiers, disclose-and-refuse). **Owner selected
  W1** (QEMU + WHPX as the Windows strong-tier reference) with seven conditions. Selecting the provider
  authorizes no host change: A1 (enable `HypervisorPlatform` and restart), A2 (QEMU install) and A3 (the
  guest-state directory) each still need their own Owner approval when required. Until then F-03.2.1+
  cannot be realized on this host. Disclosure: the consultation briefly started the Owner's WSL Ubuntu distro
  for read-only inspection and stopped it again. Later dispatches treat that distro as untouchable.

- **2026-11-06: Owner host acts.** A1: the Owner authorized the Overseer to enable the Windows Hypervisor Platform feature through an interactive UAC prompt. The feature went from Disabled to Enabled; no other feature was touched and no restart was performed; a restart is pending and will be coordinated with the Owner. A3: the guest-state directory was created outside the repository and the Owner profile, with its ACL restricted to the Owner account, SYSTEM and Administrators. A2 (pinned QEMU install) is approved under eight conditions and has not been performed yet. A stray `.gnupg/common.conf`, which a Builder accidentally created in the Owner profile, was verified as unreferenced and removed under explicit Owner authorization.
- **2026-11-06: A1 complete.** The Owner restarted Windows. Afterwards, read non-elevated: `HypervisorPlatform` InstallState 1 (enabled), a hypervisor present, and a boot time after the A1 change. A2 was installed earlier (QEMU 11.1.3, verified, not run). Its first execution was the F-03.2.1b paused-boot validation, which is the separately authorized validation stage; no guest has been booted.
- **2026-11-06: Owner authorized F-03.2.2 guest validation**: creating, booting, inspecting, stopping and destroying disposable Debian 13 guests with the pinned QEMU/WHPX profile, repeatable without approval for each boot, under nine conditions recorded in [decision 0003](../decisions/0003-execution-guest-providers-and-isolation-contract.md). Expanding host access, network permissions or VM privileges, or running untrusted workloads, needs separate authorization.
- **2026-11-06: Owner authorized F-03.3.2 network validation**: root inside disposable test guests may configure guest routes and interfaces to prove outbound denial (IPv4, IPv6, DNS, direct IP). A temporary QEMU guestfwd may reach only a purpose-built 127.0.0.1 echo test listener on an ephemeral port. Repeatable, under eight further constraints recorded in [decision 0003](../decisions/0003-execution-guest-providers-and-isolation-contract.md). Broader guest-to-host access, production connectivity or a change to the approved profile needs separate authorization.
- **2026-11-06: publication-safety gate operational** (Owner-directed), commit `9d4c39f`. Gitleaks 8.30.1, pinned and checksum-verified, in a per-user cache, with the binary re-hashed on every run. Repository-local pre-commit and pre-push hooks (`core.hooksPath=.githooks`) fail closed. Narrow rules cover personal paths and credential-store file paths. `.gz` files are decompressed and scanned; other binaries are refused unless allowlisted. The Builder added 19 gate tests (85 tool tests in total). The Overseer ran independent controls: a synthetic credential was rejected with its value redacted; Windows and POSIX personal paths were rejected; a placeholder documentation example passed; a missing scanner was refused (fail closed). History scan (read-only, all commits): 3 `generic-api-key` findings, all English prose in the seed plan files (entropy 3.51); **no real credential, nothing to rotate**.
- **2026-11-06: AI-first contributor onboarding** (Owner-directed), commit `7cb5464`. CONTRIBUTING.md is now a short human guide: clone, a coding agent, describe the change, review. The new portable AGENTS.md says that opening the repository authorizes only the user's task. CLAUDE.md imports AGENTS.md and keeps the Overseer rules verbatim, with no routing change. The technical reference moved intact to docs/development.md: 282 of 300 lines are verbatim, 12 differ only in link prefixes, and 6 are deliberate rewordings. README section "How work is done here" separates ordinary contribution from the Owner's temporary Overseer arrangement. The Overseer re-ran the link check (102 relative and anchor links, 8 external, PASS), verify_seed (including `--baseline seed`) and the 108 tool tests. Not verified: a live fresh-clone session in Codex or Claude Code; checks 2 and 3 rest on the official documentation. Remaining: the comments in `.githooks/` still point to CONTRIBUTING.md, which still links to the gate section. Disclosure: the Builder listed the repository root once, which printed the seed archive's name; it was not read, stat-ed or hashed.
- **2026-11-06: publication licensing audit** (Owner-directed), commits `18c386d` and `a7a419c`; report in [`composition/inventory/PUBLICATION-AUDIT.md`](../composition/inventory/PUBLICATION-AUDIT.md). The whole tree and history were checked: 53 commits, 392 blobs, no path ever deleted, no binary or archive ever added, and all 14 gzip blobs decompressed. **Current-publication verdict: no violation and nothing to escalate.** Third-party components are only referenced (names, versions, hashes) and never redistributed. The SBOM and Grant outputs hold metadata only. Third-party-derived fragments are functional or attributed (generated Grant config, OpenSpec schema keys and headings, short quotes). Fixed: the MIT statements now say MIT covers repository-owned content only (C7); func-timeout is LGPL-3.0 per its shipped text, not LGPLv2/2.1, corrected in LEDGER, the lock, the lock README and a decision 0002 current-facts entry (C8); courtesy OpenSpec attribution in `catalog/README.md`. **Future distribution: not ready.** F1-F6 (LGPL/GPL/AGPL/MPL notices and source offers, image re-publication, Backlog.md binaries, provider terms) are carried to G-02.1, R-04.1, R-04.2, R-03.1.1, R-03.3.1 and F-04.1. **Unresolved, Owner:** U1, `lmnr-claude-code-proxy` 0.2.0 (transitive via openhands-sdk → lmnr), whose terms are "all rights reserved" and limit use to personal or internal business use with no redistribution. Its use needs an Owner decision, and redistribution would need permission or an Architect-reviewed dependency change. U3: whether repository-owned documentation is MIT. U2 (Anthropic claude-agent-sdk terms inside the agent-server image) is carried to R-04.1. The Overseer verified the commits, that nothing pins the lock's digest, verify_seed and the 473 tool tests.
- **2026-11-06: Owner decisions after the audit.** (1) U1 and the distribution model: local use of the pinned OpenHands chain is accepted under upstream terms. The default distribution model is to publish our own source, configuration, manifests and locks, and to have users download third-party dependencies from upstream, pinned and hash-verified, with no vendoring, bundling, mirroring or redistribution. Recorded as [decision 0005](../decisions/0005-distribution-model-upstream-download-no-redistribution.md), Accepted. (2) U3: repository-authored code **and documentation** are MIT, as `LICENSE` states (wording updated in `b87a147`). (3) P-01.2 live qualification is authorized through bounded, tool-less Claude Code headless (`claude -p`) runs under the Owner's existing login: about 15-25 short runs, outputs kept as evidence, no new credentials stored. Also recorded: [decision 0004](../decisions/0004-privileged-effect-store-custody-and-restore-semantics.md), **Proposed**, privileged-effect store custody and restore semantics. It follows an Architect gate-G consultation, and the Overseer accepted option O4: elevation-gated custody now, the executor principal at G-04.2.1 through Owner act A4, which is requested then and not now. F-05.2 proceeds on fixtures. Acceptance awaits the Owner's acknowledgement. The README status was refreshed from evidence (`7360a74`).
- **2026-11-06: Owner accepted decision 0004** with seven clarifications, incorporated in `5017094`. Effects receipts are separate and protected by OS access controls against integration processes and untrusted agents. Nothing live is created during F-05.2. At G-04.2.1, prefer a Windows service identity, such as a virtual service account, if it is sufficient. An agent may initiate a specifically authorized elevated operation for the Owner's interactive UAC approval, but never auto-elevates, bypasses UAC, or holds persistent privileged credentials. UAC consent is not an OS boundary, and the Owner-account agents are not isolated principals. Backup, restore, reconciliation and replay protection are as specified. No additional accounts, services, VMs or authorization machinery until needed. Each actual privileged host change is requested as a scoped authorization.
- **2026-11-06: Owner authorized F-04.1 provisioning** (A and B), after the Owner set the design (host download, then SFTP over the management channel, then native install in the guest; no proxy or provisioning VM without proof) and an Architect gate C/G consultation. **A, host:** pinned, hash-checked downloads from the original upstreams into `D:/aieh-guest-state/provision/` (Debian docker.io/docker-cli closure and signed index from snapshot.debian.org; the agent-server image by locked digest from ghcr.io; the release binary); one pinned, checksum-verified `crane` run from the state directory only to fetch the image; a non-root, no-network resolution guest. **B, guest:** a single-use, cloud-init-seeded root step that copies, sha256-verifies and installs Moby with apt and the image with `docker load`, installs the Agent Server as a service under a no-login user, generates guest-local secrets, deletes the upload and disables itself. Moby and the Agent Server run only for F-04.1/F-04.2 inspection (no LLM, repository content or untrusted workload). Unchanged: no guest network at any phase, no guestfwd, no host shares, the QEMU command line, and the tier not operational. It is repeatable under the guest-validation conditions as amended. Any guest network, guestfwd, host share, LLM credential or new host port needs separate approval. The automatic auto-mode safety check paused the first dispatch, and it proceeded after this explicit authorization. Recorded in [decision 0006](../decisions/0006-guest-provisioning-channel-and-image-conformance.md) (Proposed). **Slice F-04.1a done** (`ab950fb`, `f605aaf`, `9a29f54`; [evidence](F-04.1a-provision-pins-fetch.md)): `resolve.py` still resolves (no upstream pin change). The resolution guest verified Debian's InRelease signature (sqv) and resolved runc, containerd, tini, docker.io 26.1.5 and docker-cli at snapshot 20261106T143859Z. `provision.lock.json` is pinned by the profile and checked by `check_profile`. The image index → manifest → config digest `sha256:e8959dfc…` is the image ID. `provision-fetch` staged 1.49 GB in 44 s, with the image layers verified against the lock, and a re-run re-verifies without downloading. The Overseer re-ran the strict check, the 21 fetch tests and verify_seed, and checked the stage size and that the commits contain no pre-signed URL. Overseer decision: the bootstrap-log obligation to run resolve.py inside the Linux guest is re-scoped to the first leaf that runs SDK Python in the guest.
- **2026-11-07: slice F-04.1b done** (`31ecaf4`, `e34d495` fix-forward, `a53a73d`; [evidence](F-04.1b-provision-moby.md)). A seeded, hash-gated single-use root step (`/usr/local/sbin/aieh-provision`, triggered by a `READY` marker after the SFTP upload) does the following: it copies to a root-only staging directory, verifies the sha256 values against the seed manifest, writes `daemon.json` (data root on scratch, unix socket only, `no-new-privileges`) and installs the 5 pinned debs from local files (no `apt-get update`). It then turns off containerd's CRI TCP listener (which Debian's package enables; exposed by this slice), loads the image, checks image ID `sha256:e8959dfc…` equals the lock and keeps only the tag `aieh/agent-server:1.60.1-b43ee580`. Finally it deletes the upload and staging and removes its trigger. `RESULT.json` is written last. Upload: 1.48 GB in about 11 s; root step about 78 s (`docker load` 61 s). `agent` is refused at every Moby socket (`EACCES`) and has no TCP listener. P1-P9, P11 and P12 PASS. Stop/start keeps the image, and `smoke --provision` passed in 286 s, including recreate. Contract amendments by the Overseer as contract owner: P2 (Moby inside the ceilings) and P6 (the guest's own Moby sockets allowed, with `agent` unable to connect). Moby's mounts are declared in `guest_storage`. `launch` is byte-identical. P5 is unchanged (no secret yet). Overseer rulings: (1) accepted a persistent boot-time root unit, `aieh-docker-facts.service`. It is a read-only Docker facts reporter that takes no agent-controlled input, needed because `agent` cannot query the daemon. Disclosed to the Owner as a reporter beside the single-use install step. (2) Accepted replacing containerd's packaged config only while it is unmodified. The Overseer re-ran the strict check and the provision and seed tests, compared the launch block against origin, and confirmed 0 instances and no QEMU process.
- **2026-11-07: self-contained repository** (Owner-directed hygiene), commits `ce38bc0` and `679cd50`. References to an unrelated project were removed from `README.md`, `AGENTS.md`, `CLAUDE.md`, `OVERSEER_START.md` and the plan JSON and HTML. By the Owner's principle, which also covers unnamed references, the per-task guardrail now reads "…or modifying unrelated repositories" in all 136 task prompts and their plan copies, and the plan scope reads "Adoption-first open-source implementation". Generic architectural uses of "control plane" are kept. Integrity: `SEED_MANIFEST.json` and `task_manifest.json` were updated in the same commits by the documented rehash; `verify_seed` and `--baseline seed` PASS, and history is untouched. The publication gate flagged the known seed-plan prose false positive (`generic-api-key` on "issuance/revocation", one of the 3 from the history scan). The Overseer, as reviewer, approved one exact-value allowlist entry for that rule only. It was proven narrow: near misses and a synthetic key are still rejected, and the 19 gate tests are OK.
- **2026-11-07: Owner decisions on three plan gaps** found by the Overseer and Architects: no plan leaf installs Gitea (which S-01.2.2 and most later leaves presuppose), none provides model access through the inference broker, and none builds the acceptance recorder (decision 0008). (1) **Gitea on host loopback**, with the Owner's modification, verbatim: "Do not hardcode installation or state directories on D:. All Gitea installation and data paths must follow the repository-owned filesystem convention. Default to: <repo>/.local/persistent/gitea/ Support AIEH_DATA_ROOT as an optional override of .local, with ephemeral/ and persistent/ beneath that root. Gitea remains bound exclusively to 127.0.0.1, runs under the current Windows user without administrator privileges, and stops when the managed environment shuts down. Use the existing pinned and hash-verified Gitea binary. Do not introduce a second VM. The optional config.yml design can be implemented separately; do not block this work on the full configuration system." Overseer note: the composition pins Gitea 28.3.0's Linux binaries, images and source, but no Windows binary. On this Windows host, the faithful reading is the Windows asset of the same pinned release, pinned by the same three-source hash check (GitHub asset digest, upstream `.sha256` on GitHub and on dl.gitea.com); this was disclosed to the Owner. (2) **Model access: design it now.** A supplementary leaf for an Architect-reviewed inference-broker design, brought to the Owner for authorization before anything runs. (3) **Amend the plan** through the documented integrity process (plan JSON and its projections, new task prompts, both manifests), so the plan stays the single backlog. (4) **Add an acceptance-recorder leaf now**, sequenced after P-03.
- **2026-11-07: Owner directive "external-by-default installation, centralized configuration and filesystem ownership"** (dogfooding: the installed harness and its managed state live outside the source checkout, and source-editing agents gain no installed secrets or operational state). It supersedes the repository-local `.local` placement of the gap decision; nothing was ever created there. Key points: an OS-appropriate managed root (Windows `%LOCALAPPDATA%\AIEH\`, Linux XDG); an `AIEH_DATA_ROOT` override (a relative value resolves against the repository root); a tracked `example_config.yml` and an optional, gitignored `config.yml`; precedence per-directory override > `AIEH_DATA_ROOT` > OS default; one shared resolver; no secrets in source-accessible configuration; no new sandboxing for the development Overseer (an accepted bootstrap limit); the Windows-native Gitea 28.3.0 binary, pinned to the three-source standard, approved; no WSL or VM for Gitea. Owner follow-up answers the same day: (1) the Owner **challenged decision 0004's premise** that a drive-root directory gives custody against same-account processes, asked that 0004 be re-evaluated against the actual ACLs, process identities and replacement threat model (detection kept distinct from OS-enforced prevention), and said not to supersede it silently; an Architect re-evaluation is queued. (2) A **third lifecycle category, `assets/`**, for downloaded, verified, reusable artifacts (versioned, with provenance and reacquisition data, deleted only deliberately), beside `persistent/` and `ephemeral/`; the existing guest-state root stays intact, and F-07.2 plans its migration by classification (copy, verify, switch references, cleanup only when separately authorized). (3) A data root inside or containing the checkout is refused. An Architect gate C/G/F consultation designed F-07.1; the Overseer accepted it with the Owner's refinements. Verbatim records are kept by the Overseer.
- **2026-11-07: plan amendment** (Owner-directed; integrity process) `945b563`, `a917e5a`, `7b41701`. The plan now has 142 leaves and 142 prompts (from 136). New groups and leaves: F-06/F-06.1 (pinned Gitea on host loopback under the managed data root, consuming the resolver; binary as an asset, state persistent), F-07/F-07.1 (managed data root and configuration contract), F-07/F-07.2 (component adoption and migration plan), S-03/S-03.1 (inference broker design, for Owner authorization), S-03/S-03.2 (broker implementation, not dispatchable before that authorization), P-04/P-04.1 (acceptance recorder). New edges: S-01.2.2 gains F-06.1; E-03.2.2 and K-02.2 gain S-03.2, so 69 leaves now wait on the broker. Group dependencies follow the existing convention (a group's deps equal its leaves' external deps through the aliases). The Owner's "Gitea follows the shared filesystem contract" criterion sits in F-06's gate, to avoid a group cycle. The plan records both dated `amendments`. Count-bearing prose in `CLAUDE.md`, `OVERSEER_START.md` (authority; hash updated) and the plan's operating prompt is now count-free. `verify_seed` PASS on both baselines (142 tasks; seed 136). Overseer rulings: P-01.2 (already PASS, run on the Owner's separately authorized headless channel) and E-01.4.2 (`run: false` needs no model) are not wired to S-03.2.
- **2026-11-07: publication-gate coverage defect found and repaired** (`0499dc3`, Owner-authorized). The amendment's follow-up commit was refused because of the plan HTML's byte length, not its content. Root cause, read from Gitleaks v8.30.1's source and reproduced: it scans files in 100,000-byte fragments, extended to a blank line by at most 25,000 bytes, with no overlap, so a match crossing a cut is never seen. That split the gate's end-of-file coverage marker (a false refusal, failing closed). It also let a synthetic `ghp_` token straddling a cut **pass the old gate (a false negative)**. The auto-mode safety check blocked the Overseer's first dispatch of a repair as security weakening; the Owner then explicitly authorized a strict repair. The fix: content over 96 KiB is scanned as overlapping windows (32 KiB overlap), each sized to fit one scanner read, each window's marker required, and findings mapped back to their real lines; fail-closed kept; rules, `.gitleaks.toml`, hooks and `core.hooksPath` unchanged. Tests reproduce the old failure length (now PASS) and catch a boundary-straddling synthetic secret; both fail against the old gate. The Overseer confirmed no fail-closed path was removed, ran the 26 gate tests with the real scanner, `verify`, the 767 tool tests, and **rescanned the entire history with the repaired gate: PASS (108 commits, 1,049 blobs and messages), so no secret escaped through the gap**. The description in `docs/development.md` is updated in a follow-up.
- **2026-11-07: decision 0004 re-evaluated; Owner decision 0010.** The Owner challenged 0004's premise that a drive-root location protects the effects store from same-account processes. An Architect (gates A and G) measured, without elevation, the ACL metadata of `D:\`, `%LOCALAPPDATA%`, `C:\ProgramData` and also `C:\` (disclosed, beyond the brief), and ran scratch-only experiments. Findings: parent `FILE_DELETE_CHILD` alone decides whether a same-account process can rename or delete a protected directory through the native API. `D:\` and `C:\ProgramData` deny it to the Owner's non-elevated token, and every profile directory grants it. Win32 rename and delete fail everywhere (they also request SYNCHRONIZE), so they are not evidence. 0004's rationale is partly supported: the parent chain, not "drive root", is the property. The Owner then decided a **governance-scoped threat model**: prevent accidental or convenient circumvention of the established workflows and keep execution accountable; a malicious process with the Owner's full account privileges is out of scope. The Owner also decided: the effects store at `<managed-data-root>/persistent/effects/` through the resolver; relocation exposure reported, not refused; the executor's code and configuration under `persistent/installs/` with defaults, validating its identity, configuration, authorization and integrity and failing closed; no separate identity or elevation solely for same-account filesystem attacks. Recorded as [decision 0010](../decisions/0010-effects-store-placement-and-governance-threat-model.md) (Accepted, Owner), which refines 0004 and 0009 without editing them. Its consequences go to F-07.2 (the effects category and store location policy, the relocation report, the inventory) and to a plan rewording of G-04.2.1 and G-04.2.2. Their proofs stand.
- **2026-11-07: Owner directive: no manual Gitea credential enrollment** (zero routine Gitea administration). The harness provisions, verifies, rotates and cleans up the administrator and Owner credentials through the OS credential provider; separate administrator, Owner and bot identities are kept; Owner authorization flows through harness governance, not manual Gitea merges; how the Owner identity is used internally is to be established (an Architect consultation is queued); the lifecycle is to be the same on Windows, Linux and macOS. The Owner approved the automated finalization directly, including repeat rotation of the two accounts under the same rules. The auto-mode permission check refused it twice in a Builder's session even with that approval relayed; the Owner then instructed the Overseer (main session) to run it. The Overseer read the wrapper in full and ran it. The first run stopped safely at sign-in (Gitea 28.3.0 answers a correct sign-in of a must-change account with 303 to `/`, not to the change form), with nothing changed. After the fix (`c1a4e8a`) the second run succeeded.
- **2026-11-07: Owner directives on cross-platform operation, documentation and MADR, and fast testing; four Architect consultations; Owner decisions.** Directives: (a) cross-platform installation and operation are architectural requirements, with a common lifecycle contract and platform adapters (Windows first; Linux and macOS designed, never claimed verified prematurely); (b) modernize the documentation into Markdown under `docs/`, adopt MADR, keep the JSON plan authoritative, and evaluate the monolithic HTML projection; (c) fast, parallel, deterministic testing, measured first. Consultations, each accepted by the Overseer: the cross-platform lifecycle (gates C, F, G: one contract, OS-held supervision per platform, keyring for POSIX only with explicit backends, Windows keeps its stdlib provider; decision 0011 drafted); the Owner authority in Gitea (gates A, B, G: "keep the record, move the act", a deterministic authorization recorder is the sole holder of the `aieh-owner` credential and merges only on a recorded Owner decision bound to the exact head and manifest digest, single-use, with trailers; decision 0012 drafted); documentation and MADR (gates B, C, D: MADR 4.0.0 minimal plus front matter, ADRs never grant authority, a docs tree, a plan-view generator, a stronger verifier); testing (gate C, measured: 1,141 tests in 305 s serial and 6,990 process launches per run; pytest plus xdist in a hash-locked dev venv over the unchanged unittest suites, declared categories with a unit guard, test 7's whole-suite rerun moved to the gate tier, golden fixtures, counted budgets). **Owner decisions:** the bootstrap approval channel accepted (a declared decision bound to an exact revision, transcribed verbatim; not cryptographic proof); the recorder may perform `aieh-owner` merges on recorded decisions; `aieh-owner` kept as the Owner-authority identity; the committed plan HTML and CSV to be retired in favour of on-demand generation with a stronger verifier; `decisions/` stays at the root; headless Linux custody to qualify `systemd-creds`; the Linux verification host is the existing disposable Debian test guest; macOS deferred until a Mac is available. Overseer decisions within the directives: keyring off Windows; the POSIX lifecycle under the tools venv; the dev-tools venv under the managed root; the testing tiers, homes and pins as the consultation recommends. All new work enters the plan in one combined amendment.
- **2026-11-07: combined plan amendment** (the integrity process; `52f3a81`, fix-forward `42963e5`). The plan grows to 156 leaves and prompts (from 142). New leaves: F-06.2 to F-06.6 (host-service lifecycle contract and Windows adapter; credential provider with keyring for POSIX; Linux on the existing disposable Debian test guest, qualifying `systemd-creds`; macOS, not dispatchable until the Owner provides a Mac; upgrade, recovery and uninstall); P-04.2 (Owner authorization recorder); group F-08 (F-08.1 to F-08.4: MADR adoption and checker, `docs/` restructure and link checker, plan-view generator, retirement of the committed HTML and CSV with a stronger verifier); group F-09 (F-09.1 to F-09.4: measure and baseline, pytest-xdist over the unittest suites, golden fixtures, batched adapter git access). Changed: the F-06 parent (each platform counts as supported only with its own evidence record; terminal F-06.6); P-04 retitled "Record Owner decisions", covering both recorders (terminal P-04.2); G-03.1, G-03.2 (+P-04.2), G-04.3.1, G-04.3.2, D-01.2 (+P-04.2) for the recorder; the G-04.2 group, G-04.2.1 and G-04.2.2 reworded per decision 0010 with their proofs unchanged; P-04.1 now uses the shared decision-record shape; dependency edits R-02.3.1 (+F-06.2, F-06.6), R-03.4.1 (+F-06.4, F-06.5) and S-03.2 (+F-06.3). Group dependencies follow the convention, asserted. Overseer rulings on the Builder's findings: terminal reach encoded (F-06.6 +F-06.3; F-09.3 +F-09.2; F-09.4 +F-09.3); stale group texts fixed; the {F-06, S-01} membership interleaving accepted (the acceptance graph is acyclic and nothing deadlocks); F-09.4 accepted in phase 1 inside a phase-0 group. Unchanged leaves were reproduced byte for byte (except F-02, as before), every prompt equals its JSON text, and `planData` equals the JSON. The Overseer re-ran verify_seed (156; seed baseline 136, strict), the 767 tool tests, the dependency spot-checks and the scan.
- **2026-11-07: Owner extended the guest run authorization** (F-04.1 authorization B previously read "Moby and the Agent Server run only for F-04.1/F-04.2 inspection"). Verbatim option chosen: "Moby and the Agent Server may run in disposable guests for any plan leaf's containment, admission and lifecycle testing, under the existing isolation conditions: no LLM or model credential, no repository content, no untrusted workload, no guest network, guestfwd, host share or new host port. Anything beyond that still needs separate approval." The F-03.2.2 and F-03.3.2 guest-validation conditions and decision 0003 still apply.
- **2026-11-07: decision 0013 Accepted (Overseer)** at the completion of S-01.4. It refines 0007 points 4 and 5. The Owner UI never holds the Agent Server management key: the dispatcher alone holds it, and the UI uses a per-conversation runtime credential the dispatcher issues. Every host-to-guest forward stays closed until a recorded Owner approval at the leaf that first needs it (U-01.2 or E-01.3.x for the UI and the dispatcher, S-03.x for model access, Q-02.x for the CI runner). Point 6 applies the same-account scope to the host network plane, as the blueprint's `#security` text states ("two API tokens or localhost ports do not create an isolation boundary") read with decision 0010 s1; it adds no mechanism and does not amend 0010; reported to the Owner. Point 7: untrusted code has no network path to Gitea; proposals leave by exchange and the dispatcher pushes as the bot identity it holds custody of.
- **2026-11-07: Owner ruling on S-02.2.** After the API's safety screening stopped the S-02.2 dispatch that also asked for fail-closed drills and a stored-state test, the Owner chose: accept S-02 qualified, the re-run accepted as observed, the drills and the stored-state question carried to E-01.2.2, `fd-container-shares-service-uid` kept open-risk.
- **2026-11-08: independent review findings (Owner directive).** Three candidate findings were checked against `253f8d5`. (1) Attempt reservation versus execution concurrency: a responsibility gap, intentional. `confirmed` in the integration store means the conversation create succeeded, not that the attempt finished, and the store admits the next ordinal once the earlier one is terminal (the E-01.1.1 ruling, after the blueprint's rework loop). No component yet prevents a new attempt on the same Work, design revision and stage while an earlier conversation still executes, because the coordinator is not built. The reservation schema is unchanged by the Owner's direction. **Carried acceptance requirement:** E-01.5 and E-04.2.1/E-04.2.2 must enforce, and prove by acceptance tests, that no ordinal is reserved or dispatched for a triple while an earlier attempt's conversation is executing, as the Agent Server reports it. (2) Gitea token revocation: confirmed; finalization does not require the post-revocation inventory to be empty. (3) Unreadable files in the credential-leak scan: confirmed for the checkout scan; the managed-root scan also skips unreadable directories. **Fixed in `9102733`** ([disposition record](review-findings-2026-11-07.md)): `revoke_all_tokens()` now raises `TOKEN_REVOCATION_UNVERIFIED` when the listing after the deletions is not a token list, and `TOKENS_REMAIN` when any token is still listed (including one whose delete answered 204), on both `finalize_account` paths, with resume on rerun; `files_containing()` reports unreadable files (and tracked files absent from the working tree, which are not a failure) and `contains_secret()` reports directories it cannot list; `finalize_credentials` refuses an incomplete scan as `SECRET_SCAN_INCOMPLETE` (an unreadable managed-root file, formerly counted as a password hit, now lands here, still fail-closed) and `verify()`'s checkout check fails with the paths shown. The integration store README states that `confirmed` is not execution completion and names the carried requirement. 18 new or changed tests (mocks and fakes only) fail or error on the old code; `AGENTS.md` lists the gitea and dispatch suites (`9342f5a`). Overseer verification at `9342f5a`: both scan functions' callers updated (no other caller); verify_seed (156) and `--baseline seed` (136) PASS; tools 926, store 84, effects 34, planning 56, lineage 134, paths 36, gitea 90 and dispatch 47 tests OK with the default TEMP; gate history scan PASS; no personal path. Not run against the live Gitea.
- **2026-11-08: Owner scheduling priority: test-suite wall-clock time.** The Owner's directive, verbatim in part: "Reduce test-suite wall-clock time now. ... Prioritize this sequence ahead of other ready implementation work, subject to existing dependencies and safety gates. Finish any currently active Builder task rather than interrupting or abandoning its work. At the next dispatch opportunity, begin F-09.1 and continue through F-09.4 as dependencies become satisfied." Acceptance kept: equivalent results across serial and parallel runners; every required security and contract test still enforced; no reduction in meaningful coverage; a serial suite wall-clock of at most 150 s; measured before and after wall-clock results. Use the existing leaves and prompts; no duplicate work packages and no redesign of the testing architecture. Overseer sequencing: E-01.2.2 slice (a), already running, finished (`0e051d6`); next are F-09.1, F-09.2, F-09.3 and F-09.4, whose dependencies (F-02, F-07.1, P-03.2) are PASS. E-01.2.2 slice (b) and other ready work follow.
- **2026-11-08: Owner directive: a closed, executable plan; planning-integrity reconciliation.**
  - **Directive**, verbatim in part: "Ensure every discovered implementation obligation is represented in executable work, not merely recorded as a carry-forward note. ... If deliberately deferred, record the explicit authority, reason, and reconsideration condition. Do not silently treat documentation or a reference to an accepted task as evidence of resolution."
  - **Method:** a read-only Builder inventory at `4c6f44a` covered this log, every evidence record's carried and not-verified sections, `security/inventory.json`, `decisions/`, the review findings and the plan. It found 98 obligations: 32 orphaned (including the upstream conversation-network behaviour found after its S-01 owners passed), 16 not covered, 23 partial, 13 covered and 14 resolved. The Overseer decided every row. A Builder amended the plan through the integrity process (`2967d2d`, with fix-forwards `ef62f12` and `1f506f6` after Overseer rulings on its findings).
  - **Plan changes:** 158 leaves. Two new leaves:
    - **P-04.3** promotes the approved dispatch inputs through recorded decisions. It is P-04's terminal leaf; E-01.3.2 and A-01.1 depend on it.
    - **E-01.3.3** realizes dispatcher credential custody and per-attempt role tokens. E-01.3.2 depends on it, and it depends on F-06.3.

    Enforceable proof text is appended to 38 open leaves. U-03.1 gains dependencies on E-01.3.3 and F-06.3. The P-04 ↔ E-01 group-level cycle is accepted with an acyclic leaf graph, as with F-06 ↔ S-01.
  - **The upstream network behaviour:** `host-gateway` and the default bridge (no `--network none`) are now owned by R-01.2 and E-01.5. R-01.2 re-proves the containment catalogue on every pin change and adopts any upstream control. E-01.5 checks every attempt's `NetworkMode` and `ExtraHosts` against the recorded limit values. Closing them is deferred (Overseer as contract owner): upstream sets both unconditionally, and the outer server reaches the container through its published port. Reconsider when upstream offers a control or a compensating case fails.
  - **Repository fix-forwards:**
    - every planned network edge names its verifying leaf, enforced by `check_network_matrix` (`1064737`);
    - stale `verify_at` and `carried_to` pointers to accepted leaves are re-pointed (`1b25112`);
    - `policy/README.md` covers `test-budgets.json` (`85a4e4e`);
    - grammar checks in planning (`70e0226`) and lineage (`258d4b1`) use `fullmatch`.
  - **Record:** [plan-reconciliation-2026-11-08.md](plan-reconciliation-2026-11-08.md) (`5729c65`, `9240a23`, `e36188a`) has one row per obligation: covered 13, amended 51, new leaf 5, deferred 9 (each with its authority, reason and reconsideration condition), resolved 14, fix-forward 3, Owner-reserved 3.
  - **Overseer verification at `e36188a`:**
    - verify_seed PASS (158; seed baseline 136);
    - the leaf graph is acyclic;
    - all 98 ids appear exactly once in the record;
    - the amended proofs of E-01.2.2, E-01.5, R-01.2, P-04.3 and E-01.3.3 were read;
    - the Builder's checks: 115 unchanged leaves byte-identical; old text a prefix of new text on all 41 changed leaves; prompts equal the JSON; group-deps convention holds; tools 967, planning 58 and lineage 135 tests OK; security, role-token, network-matrix and containment checks PASS; counters-only budget PASS.
- **2026-11-08: Owner decisions on the three Owner-reserved reconciliation items.**
  1. **Decision 0013, point 6, accepted by the Owner**, verbatim: "I accept extending the previously established same-account threat-model boundary to the host network plane. This does not authorize weakening guest isolation, network enforcement against untrusted agents, credential separation, or the independently verified security controls."
  2. **M-2 approved** to proceed after F-09.4.
  3. **Decision 0007:** the Owner approved a current-facts note reflecting his earlier confirmations, preserving the original history, provenance and attribution, with no historical decision rewritten. The note was appended; the sections of 2026-11-07 are unchanged.

- **2026-11-08: Owner architectural direction on Dulwich**, verbatim: "Owner architectural direction: Adopt Dulwich as the preferred Git implementation for Python components. The previous decision to defer Dulwich is superseded. Rationale: - Eliminate the external Git executable dependency where possible. - Use a consistent Python implementation across Windows, Linux and macOS. - Avoid unnecessary subprocess creation and management. - Simplify installation, testing, and maintenance. Do not interrupt the currently running F-09.4 Builder or discard its work. After the current task completes: 1. Reconcile this decision with the blueprint and existing architectural decisions. 2. Inventory Git CLI usage in Python components and distinguish repository operations from Git hooks, publication workflows, and other operations that genuinely require Git CLI. 3. Create or amend executable Small leaves to migrate supported repository operations to Dulwich, with explicit dependencies and acceptance criteria. 4. Preserve Git behavior, including paths containing spaces, repository integrity, revision resolution, and failure semantics. 5. Require cross-platform contract tests, measured performance, and parity with existing behavior. 6. Retain Git CLI only where a documented compatibility gap justifies it. Use the existing plan-integrity process. Do not silently defer the adoption again or expand the active F-09.4 scope. Complete the current test-performance sequence and continue autonomous execution according to the updated dependencies."
  - **Overseer reconciliation (initial, 2026-11-09):** the blueprint already adopts Dulwich for AI Engineering's own Python adapters (decision SHIP-02, "no external Git executable for our Python adapters"; the Repository API policy; unsupported operations delegated to upstream clients). The deferral this supersedes was F-09.4's recorded evaluation (round 2, R6), not an accepted decision. No record in `decisions/` covers Dulwich, and `composition/` pins no Dulwich release. F-09.4 completed without its scope being expanded. Next: an inventory of Git CLI usage in the Python components, then a plan amendment through the integrity process with executable Small migration leaves.
- **2026-11-09: Owner decisions on M-3 and the Agent Server start-up race**, verbatim: "Owner decision: M-3 is approved. Reconcile the Linux isolation wording in the blueprint with decision 0003 and SEC-01. Preserve the distinction between the strong Linux VM boundary and trusted-workload containers. This is a documentation correction, not authorization to change the implemented isolation architecture. Also ensure the intermittent OpenHands startup import race (2 failures in 272 restarts) has an explicit executable owner or documented disposition under our planning-integrity rules. Reporting upstream does not replace local work tracking. Do not interrupt F-10.1 or change its scope. Continue the existing autonomous execution sequence."
  - **Overseer disposition (2026-11-09).** No existing Small leaf's proof tests the race (E-01.2.2(c) finding F-15; slice (b)'s F-5). Three leaves come close, and each falls short:
    - E-01.4.2 restarts the pinned server, but only to prove recovery without duplicate effects.
    - R-01.2 re-observes the cost-map fetch, but only when a lock changes.
    - F-04.1 and F-04.2 have passed, and their proofs do not measure start failures.

    It gets a **new executable Small leaf, E-01.4.3**, added by the integrity process in the same builder dispatch as M-3, after F-10.1. Its work:
    - establish the root cause from the locked source and the slice-(c) journals (inference so far: litellm's cost-map retry thread imports a partly initialised module while the guest has no network);
    - adopt an upstream configuration control that removes the trigger, through the profile declaration and requalification, or record why none exists;
    - declare the start path's failure handling (systemd restart and the readiness ceiling), so that a slow or retried start is reported as such;
    - record the upstream report's reference. The report does not discharge the leaf.

    Its proof uses a rule fixed before observation:
    - with a control: 0 main-process exits during start in at least 500 consecutive server restarts on a fresh disposable guest. At the observed rate (2 of 272) an unchanged server would pass this with a probability of about 2.5%.
    - without a control: every failed start is retried and becomes ready within a declared ceiling over 500 restarts, the maximum start time is recorded, and the limit is recorded with its reconsider condition (an upstream fix in a pinned release, re-observed by R-01.2).

    It depends on F-04.2 and E-01.2.2, so it is eligible at once. It is placed in E-01.4, which owns interruption and recovery of the Agent Server path. The F-04 parent verdict stands for its own contract.
  - **Done: plan amendment `ab0def1`** (165 leaves; the eighth `amendments` entry).
    - E-01.4.3 is slice 1 of 3 in E-01.4, so that no existing handoff text changes. E-01.4.1 and E-01.4.2 become slices 2 and 3; E-01.4.2 stays the terminal child and keeps the gate.
    - E-01.4's group deps gain F-04 and E-01.2, by the group-deps convention.
    - The plan HTML's Large-outcome count for E-01 is corrected to 11 small steps. It was stale since `2967d2d` (E-01.3.3), a defect introduced there.
    - The Builder's script shows no existing leaf's text, deps, prompt or gate changed.
    - Overseer verification: verify_seed PASS (165; seed baseline 136); the per-commit file lists read.
  - **Done: wording fix forward `f8d81e8`** (F-10.1 finding F-1): the `tools_install.py` docstring and `integrations/paths/README.md` now name PyYAML, Dulwich and urllib3.

- **2026-11-06: A2 done (QEMU 11.1.3 installed, not run).** The first pass stopped before extraction, as the Owner's conditions require, and found two problems. (1) The F-03.2.1a lock pinned both `sqlite` and `sqlite3`, which conflict: 66 of their shared files differ. This was a defect introduced by F-03.2.1a, whose dependency resolution ignored provides, conflicts and replaces. (2) Four packages contain hardlinks inside the same package. Fix-forward `bccf9e6`: `tools/msys2_lock.py` re-resolves the closure from the signed `ucrt64.db` using libalpm rules (23 tests). The result is 159 packages, with `sqlite3` replaced by `sqlite`, no remaining conflict and 0 overlapping paths; the lock's sha256 is `69e08336...df879`. Overseer decision: hardlinks are written as plain copies after checking each target stays inside the same package. Installed result: 158 packages extracted (`iso-codes` symlinks refused), and all 45,742 files verified against their archive hashes, with 0 mismatched, 0 missing and 0 extra. No links or reparse points on disk. Nothing executed or elevated. The Overseer independently re-hashed the three pinned binaries, re-counted the files and links, and re-ran the strict profile check. The restart that completes A1 is still pending.

- **2026-11-09: Owner direction on Owner-action tracking**, verbatim: "Owner direction: Ensure obligations requiring my attention cannot disappear into the autonomous execution transcript. Use the existing bootstrap progress records, and eventually the adopted Work system, to maintain a durable Owner-action queue. Do not create a competing task system or database. Each outstanding action must record: Stable identifier and originating task or finding; Exact decision, approval, or external action requested; Why Owner authority is required; Supporting evidence and any prepared artifact; Whether it blocks a task now or only at a future gate; Pending/resolved status and resolution evidence. Reconcile the existing outstanding obligations, including: The three upstream issue reports; E-01.4.3's missing upstream report references; F-10.5's per-act Linux guest authorization; Any other unresolved Owner actions already in the record. At every Overseer checkpoint or handoff, explicitly surface a concise "Needs Owner" section showing outstanding actions, even when work continues autonomously. Distinguish actionable-now items from future-gated items. Do not block unrelated ready work for outstanding actions. Never interpret silence as approval. When a gate requiring Owner authorization is reached, stop that specific operation and present the exact decision needed, with its implications. Once an action is completed, record its resolution and link the evidence before closing it. Treat this as a correction to the existing oversight and reporting process, not a new implementation workstream. Continue the current Builder and autonomous execution."
  - **Overseer disposition:** the queue is the [Owner actions](#owner-actions) section of this log. It holds 8 pending items (OA-01 to OA-08) and 4 reconciled as resolved (OA-R1 to OA-R4), found by reading the Leaves rows, the Decisions entries and every decision record's status and Owner-confirmation section. No plan, task or other file was created.

- **2026-11-09: Owner direction accepting and refining the Owner-action queue, with explicit authorizations**, verbatim: "Owner direction: Accept and refine the Owner-action queue, and execute the following explicitly authorized actions. The durable queue and checkpoint reporting are accepted. Keep them. Do not interrupt the current Builder or suspend unrelated autonomous engineering work. EXPLICIT OWNER AUTHORIZATIONS OA-01 — APPROVED: File the LiteLLM upstream issue. I authorize you to submit the prepared LiteLLM import-race report to BerriAI/litellm on my behalf. Before publication: - Verify the report accurately reflects our evidence. - Exclude credentials, private paths, and sensitive data. - Check whether an equivalent issue already exists. - Do not overstate the established root cause. - Preserve the pinned versions and reproduction evidence. If an equivalent issue exists, record its URL and add relevant new evidence only when appropriate. Otherwise, submit the prepared issue using authorized GitHub tooling. This authorization covers this specific report, not other external publications. Record the issue URL and submission evidence. OA-02 — APPROVED: File the OpenHands companion issue. I authorize submission of the prepared OpenHands companion report covering: - The Agent Server binary bundling LiteLLM 1.105.1. - The scope limitation of the startup-race mitigation. - The environment-variable forwarding limitation affecting conversation containers. Apply the same accuracy, confidentiality, duplicate-check, and evidence requirements as OA-01. This report is informational and must not block unrelated engineering work. OA-04 — MERGE INTO OA-01. Recording the LiteLLM issue reference is the completion receipt for OA-01, not another independent Owner action. Once the issue URL is recorded and verified, close OA-01 and OA-04 together and complete E-01.4.3 if its other acceptance conditions remain satisfied. OA-08 — APPROVED: Clean up exact synthetic test folders. I authorize deletion of these two folders from the current host's temporary directory: - aieh-repo-corpus-9o7tj36r - aieh-repo-corpus-_ifrtu9s First independently verify: - Both paths are under the expected temporary directory. - They contain only the previously identified synthetic test corpus. - No active process or test requires them. - Neither path redirects through a link or reparse point outside the expected temporary directory. Delete only these exact directories. If verification fails, leave them unchanged and report why. Record cleanup evidence and close OA-08. ACTIONS NOT YET AUTHORIZED OA-03 — Prepare the OpenHands conversation-resume report. Complete the draft and evidence review, then surface the ready-to-file report for my authorization. Do not publish this third report yet. OA-05 — F-10.5 Linux guest qualification. Approval is reserved until you present the exact one-run operation, source content, destination, isolation, resource effects, and teardown plan. Do not treat this message as authorization to run it. OA-06 — G-04.2.1 privileged host act A4. Not yet authorized. Surface the precise privileged operation and its effects at the required gate. OA-07 — Host-to-guest connections. Not yet authorized. Continue requesting authorization for each distinct connection as required by the existing governance contract. OWNER-ACTION PRESENTATION Refine the queue and its "Needs Owner" projection into four categories: 1. Needs Owner now: The exact actionable decision or external act, with prepared material and evidence. 2. Awaiting preparation: Items whose draft or prerequisite isn't ready. Do not present these as actions I can complete now. 3. Future authorization: Actions requiring my approval at a named execution gate. Include the gate and what must be presented. 4. Optional housekeeping: Nonblocking maintenance, kept out of the primary Owner attention area. Do not duplicate obligations for submission receipts, confirmation links, or other completion evidence. For every obligation, preserve its identity, provenance, blocking scope, status, and resolution evidence. RECONCILIATION Decision 0007 still contains stale "Pending" wording. Reconcile it with the previously recorded Owner acceptance, preserving historical evidence and following the existing decision-document governance rules. Do not manufacture a new approval or rewrite decision history. EXECUTION These are bounded improvements to the existing Owner oversight process, not a new task system or workstream. Use authorized mechanisms for the approved external submissions. If authentication or tool permissions prevent filing, preserve the prepared report and surface only the specific missing action; do not bypass credential controls. After carrying out each authorized action, update the durable queue and record its evidence. Continue autonomous execution. Never interpret silence as authorization. Stop only operations that reach an unapproved Owner gate."
  - **Overseer disposition:**
    - OA-01: an equivalent upstream record exists (BerriAI/litellm#48292, fixed in litellm 1.105.5), so the URL is recorded and nothing is filed. OA-01 and OA-04 are closed together, and E-01.4.3 is complete.
    - OA-02: revised for accuracy (OpenHands v1.61.0 still locks litellm 1.105.1), and the duplicate check found none. Filing is blocked only by the missing authenticated GitHub tool: the GitHub CLI is not installed and no connector is attached. Stored credentials were not read.
    - OA-08: verified and deleted.
    - Decision 0007: reconciled with a dated resolution note; the accepted text is kept unchanged.
    - OA-03: the draft goes into the next builder dispatch.
    - The queue is restructured into the four categories.

- **2026-11-10: [0015](../decisions/0015-inference-broker-placement-provider-credential-custody-and-guest-inference-endpoint.md) Proposed** at S-03.1 (Architect, gates B and G; reviewed by the Overseer). Inference broker placement, provider-credential custody and the guest `inference` endpoint. It authorizes nothing; Owner action OA-12 carries the acts it needs.

- **2026-11-10: [0016](../decisions/0016-hostile-ci-threat-model-validation-and-promotion-lanes-and-runner-reach.md) Accepted (Overseer)** at the completion of Q-02.1 (Architect, gates B, C and G; revision 2 at gate A after the source-level check contradicted the first draft). The hostile-CI threat model, the validation and promotion lanes, and the CI runner's reach to Gitea; it decides the item decision 0013 left open. Rulings R1 (filtering proxy adopted) and R2 (registration-token reset procedure). It authorizes nothing; each act is requested by the leaf that first needs it.

- **2026-11-10: Owner decisions on the Owner-action queue and feedback on the Q-02.1 CI design**, after an independent review of `origin/main` at `93d49f6`, verbatim:

  ```text
  Owner decisions following independent review of origin/main
  at 93d49f6 and the current Owner-action queue.

  Continue autonomous execution and do not interrupt the
  running Q-02.1 Builder.

  AUTHORIZED NOW

  OA-10 — APPROVED.

  Authorize exactly one execution of the prepared
  F-06.3 Windows Credential Manager cross-process test.

  Use the described random, synthetic credential only.
  Verify cross-process retrieval, deletion and absence.
  Do not enumerate or modify any other credential.
  Record the outcome and cleanup evidence.
  If the operation differs from the prepared plan, stop.

  OA-11 — APPROVED CONDITIONALLY.

  Authorize removal of the exact stray integration.sqlite
  file and its associated SQLite sidecars only after the
  specified read-only verification establishes that the
  database contains only the five synthetic receipts.

  If anything unexpected is present, leave it unchanged.
  Delete the integration directory only if empty.
  Record the result.

  OA-05 — APPROVED CONDITIONALLY FOR ONE RUN.

  Authorize one F-10.5 Linux guest qualification using
  the eight exact repository files, archive hash, two
  locked wheels, runner hash, disposable guest, resource
  limits, isolation and teardown conditions in
  evidence/F-10.5-oa05-guest-run-plan.md.

  The checkout has advanced beyond the plan's pinned HEAD.
  You may update the script's checkout precondition to the
  current clean revision ONLY IF every approved source-file
  hash and the resulting archive digest remain identical.

  Never reset or switch the active Builder's checkout.
  If the payload changes, stop and present a revised plan.

  One run only. No retries, guest network, new host port,
  credential access or additional repository content.
  Verify teardown independently.

  Report explicitly that Linux git-oracle parity and the
  native Linux Dulwich wheel remain unverified. Do not
  represent this limited run as proving those properties.

  OA-09 — APPROVED.

  Authorize the prepared public Dulwich issue about
  Urllib3HttpGitClient ignoring extra_headers.

  Recheck for a matching upstream report and verify the
  reproduction and affected version before publication.
  Exclude private paths, credentials and unrelated data.
  If no authenticated filing capability is available,
  retain the authorization and prepared issue in the queue.

  OA-03 — APPROVED FOR PRIVATE REPORTING ONLY.

  Authorize filing the prepared OpenHands Docker-runtime
  start-up recovery finding through GitHub's private
  vulnerability-reporting mechanism, if available.

  Preserve the distinction between observed behavior,
  source-derived inference and unproven exploitability.
  Do not claim demonstrated arbitrary code execution.

  If private reporting is unavailable, do not post the
  security-relevant details publicly without a separate
  Owner decision. Keep the action pending and report
  the exact blocker.

  OA-02 — PREVIOUS AUTHORIZATION STANDS.

  The OpenHands LiteLLM companion note remains authorized.
  File when an appropriate authenticated tool is available,
  or retain it as a pending nonblocking Owner obligation.
  Do not access unrelated stored credentials to accomplish
  filing.

  NOT YET AUTHORIZED

  OA-12 — DEFER EXECUTION AUTHORIZATION.

  The host-side inference broker architecture is a
  reasonable candidate, but this message does not authorize
  A1 through A6, new network paths, provider credentials,
  or model calls.

  First perform read-only discovery of whether my existing
  local Ollama installation can satisfy the initial
  fixed-prompt qualification. Identify the exact available
  model tags, the local endpoint, and which proposed acts
  would become unnecessary when no provider key or external
  egress is needed.

  Present a concise local-first option and retain the
  cloud-provider alternative. Do not silently select a
  model, start a service, or weaken isolation.

  OA-06 and OA-07 remain reserved for their specific gates.
  The future Q-02 CI host and guest acts also remain
  unauthorized.

  Q-02.1 CI DESIGN FEEDBACK

  The detection and correction of the incorrect pinned
  Gitea assumptions is appropriate. Retain source-verified
  security semantics rather than assumptions.

  In particular, do not qualify a live CI runner while
  its registration token remains reusable and an effective
  reset/revocation mechanism is unverified.

  If automated token reset is unavailable, preserve it as
  an explicit blocking condition at the live provisioning
  gate and present the required alternative or Owner act.

  Verify that job-token restrictions, absence of secrets,
  network isolation and the separation between the runner
  and untrusted jobs are independently enforced.

  Do not treat accepting decision 0016 as authorization
  to execute its privileged or network-changing acts.

  OWNER-ACTION RECORDS

  Record each decision against the existing OA identifier.
  Close only after verified execution and linked evidence.
  Keep authorized-but-unperformed external filings visible.
  Do not turn completion receipts into new Owner actions.

  Continue unrelated eligible engineering work autonomously.
  Never interpret silence as approval.
  ```

  - **Overseer disposition** (2026-11-10):
    - The builder the message names had already finished: Q-02.1 passed and was pushed at `867381b` before the message arrived. The builder then running (test-runtime headroom) was not interrupted; the OA-05 run and the record commits waited for it, so that its timings and its checkout were not disturbed.
    - OA-10: run once, PASS; closed ([evidence](OA-10-OA-11-owner-acts-2026-11-10.md)). F-06.3 passes; decision 0011 accepted.
    - OA-11: the read-only check found only the five synthetic receipts; file and empty directory removed; closed ([evidence](OA-10-OA-11-owner-acts-2026-11-10.md)).
    - OA-05: stopped at the payload check before any act (2 of the 8 files changed after the plan's commit); a revised plan will be presented. Nothing ran. When it runs, Linux git-oracle parity and the native Linux Dulwich wheel stay unverified, as the Owner directs.
    - OA-09, OA-03, OA-02: no authenticated GitHub tool exists in this session (the GitHub CLI is not installed); no stored credential was accessed. OA-09 rechecked (no duplicate; reproduced on 1.2.21; present on `main`); OA-03's private route confirmed enabled. All three stay visible as authorized and pending.
    - OA-12: execution deferred; the read-only Ollama discovery is done ([evidence](S-03.1-local-model-discovery.md)). Nothing was started or selected; the `ollama` command was not run, because on Windows it starts the app when no server runs.
    - Q-02.1 feedback: recorded on decision 0016 as a dated Owner direction; the registration-token fallback of its section 6.3 is no longer a path to a live runner, and the policy file's fallback allowance is narrowed at Q-02.2.1. OA-13 lists the CI acts, none authorized.

- **2026-11-10: Owner direction reconciling the execution results** (a second message the same day), verbatim:

  ```text
  Owner direction: Reconcile the latest execution results
  and continue autonomous engineering.

  Do not interrupt the active test-runtime Builder.

  COMPLETED ACTIONS

  OA-10 and OA-11 are accepted as completed based on the
  reported verification and cleanup evidence.

  Do not repeat either operation.

  Ensure F-06.3, decision 0011, the cleanup evidence and
  the Owner-action queue are committed and published
  through the normal verification process.

  OA-05 — REVISED APPROVAL REQUIRED

  The original authorization was bound to exact content.
  The two changed files invalidate that payload.

  The previous approval does not authorize running a
  different archive.

  Prepare the revised plan with:
  - Exact source revision and file hashes
  - New archive and runner digests
  - Updated Windows reference results
  - Confirmation that guest isolation, resource limits,
    transfer and teardown are unchanged
  - Explicit limits on what the Linux run establishes

  Present the revised plan for my approval before running.
  Do not interrupt another Builder or reset its checkout.

  UPSTREAM REPORTS

  OA-02, OA-03 and OA-09 remain authorized as previously
  recorded, with OA-03 restricted to private vulnerability
  reporting.

  Their absence of an authenticated filing mechanism is
  not permission to access unrelated credentials.

  Keep them visible as authorized-but-unperformed.
  Continue unrelated engineering work.

  OA-12 — LOCAL-FIRST MODEL ACCESS

  I select local-first as the preferred architecture for
  the initial inference qualification. This does not
  authorize execution yet.

  The existing Ollama discovery is sufficient; do not
  repeat it.

  Do not automatically adopt gemma4-uncensored:latest
  because it is the only installed model.

  Evaluate its exact digest, provenance, license and
  configuration. A digest establishes identity, not trust.
  Determine whether a verified upstream model would be
  preferable for the initial qualification.

  For local inference:
  - A1, the cloud-provider key, is unnecessary.
  - A5, cloud-provider egress, is unnecessary.
  - A2, A3, A4 and A6 still require explicit approval.
  - Starting the Ollama service is a separate host act.

  Prepare one concrete, bounded authorization request for
  the remaining acts, including the exact model, endpoint,
  service startup effects, isolation changes and teardown.

  No service startup, inference calls, new guest forwarding
  or guest hardening relaxation is authorized by this message.

  Preserve the cloud-provider design as an alternative.
  Do not build a provider-specific dependency into the
  semantic or inference-access contracts.

  CI — Q-02 AND OA-13

  Q-02.1 is complete. Do not reopen its accepted design
  merely to repeat feedback.

  Retain OA-13 and its future authorization gates.

  The first live CI runner must not be qualified unless
  registration-token reset or revocation is verified and
  the other independently enforced security controls pass.

  Do not accept an indefinitely reusable registration
  token as a routine residual risk.

  Decision 0016's acceptance does not authorize its
  future host, guest, network or CI execution acts.

  OWNER-ACTION QUEUE

  Preserve the existing four-category presentation.
  Reconcile every status with the actual committed evidence.

  Close completed actions only once.
  Do not manufacture additional approvals or duplicate
  completion receipts.

  Continue autonomous execution on other eligible work.
  Silence never constitutes Owner authorization.
  ```

  - **Overseer disposition** (2026-11-10):
    - OA-10 and OA-11: closed once each in the queue's Resolved table with [their evidence](OA-10-OA-11-owner-acts-2026-11-10.md); not repeated. F-06.3, decision 0011 and the queue committed and pushed after the publication gate and the path scan.
    - OA-05: the conditional approval no longer covers the payload; status "revised approval required". The revised plan is prepared by a builder in a separate clone, never in another builder's checkout, and presented before any run.
    - OA-02, OA-03 (private reporting only), OA-09: authorized and unperformed, visible in the queue; no credential accessed.
    - OA-12: local-first recorded as the preferred architecture, unauthorized. The installed model was evaluated ([request](S-03.1-local-first-authorization-request.md), section 1) and is not proposed; the request presents the pinned official `gemma4:e2b-it-q4_K_M` and the acts L1, L2, A2, A3, A4, A6; the guest-facing contract is the provider-neutral OpenAI-compatible Chat Completions request; the cloud request stays the alternative.
    - CI: Q-02.1 not reopened; OA-13 retained with the registration-token condition (decision 0016's dated Owner note).

- **2026-11-10: Owner architectural correction: coding-provider agnosticism through ACP** (a third message the same day), verbatim:

  ```text
  Owner architectural correction: Preserve coding-provider
  agnosticism through ACP.

  Do not interrupt the current Builder.

  I am concerned that S-03 and OA-12 are evolving toward
  using local models directly through the OpenHands-native
  agent as our default engineering execution capability.

  That is not the intended coding architecture.

  Our blueprint specifies Claude Code and Codex as preferred,
  replaceable coding providers through ACP where supported.
  OpenHands remains our selected session and execution
  infrastructure, not necessarily the coding agent itself.

  The pinned OpenHands SDK v1.60.1 already includes ACPAgent
  and provider definitions for Claude Code and Codex.

  DIRECTION

  1. The default engineering implementation/review path
     should use an ACP coding provider, with Claude Code
     and Codex as the initial candidates.

  2. OpenHands-native direct-LLM agents remain an optional
     capability, not the implicit default coding provider.

  3. Local Ollama inference remains a candidate for
     Knowledge, Conversation, auxiliary processing, and
     optional local coding experiments. It must not become
     the coding-system foundation by implementation inertia.

  4. Hold OA-12 execution authorizations (L1, L2, A2,
     A3, A4, A6). Do not download or launch models,
     start services, change guest networking, or make
     model calls under this direction.

  ARCHITECTURAL RECONCILIATION

  Consult the Architect for one bounded review of:

  - The blueprint's ACP coding-provider design.
  - Pinned OpenHands SDK ACPAgent and provider registry.
  - Current create template and E-01.3.1 dispatch contract.
  - A-01.1, A-01.2 and E-03.1 provider materialization.
  - S-03.1/S-03.2 and proposed decision 0015.
  - Existing guest containment and credential rules.

  Determine:

  A. How OpenHands selects an ACP coding provider rather
     than agent_kind=openhands for an implementation run.

  B. How Claude Code and Codex authentication can work
     without exposing unrestricted Owner credentials or
     weakening guest isolation.

  C. What provider networking is actually required, and
     whether the proposed inference broker serves ACP
     coding providers or only native direct-LLM consumers.

  D. Whether S-03's model-access requirements should be
     distinguished from coding-provider qualification,
     with their existing task dependencies reconciled.

  E. What minimal adapter and contract changes preserve
     provider replaceability, authoritative Work, independent
     review and execution evidence.

  Do not create another orchestration layer or duplicate
  the OpenHands SDK's existing ACP integration.

  Do not assume ACP permission modes enforce isolation.
  The process, filesystem, network and credential boundaries
  must be independently qualified.

  DELIVERABLE

  Record a concise recommendation identifying the actual
  coding-provider path, its credential and security
  requirements, and necessary changes to proposed decision
  0015 and the existing task plan.

  Distinguish decisions already established by the blueprint
  from implementation mechanisms that remain unverified.

  Bring any consequential architectural change or new
  Owner authorization back to me before proceeding.

  Continue unrelated ready engineering work autonomously.
  ```

  - **Overseer disposition** (2026-11-10):
    - OA-12's execution acts held; the local-first request is kept as presented and marked held; nothing started, pulled or called.
    - The Architect review (A to E) is dispatched as one bounded consultation once the running test-runtime builder has returned (one subordinate at a time); its recommendation, and any change to decision 0015 or the plan, comes back to the Owner before anything proceeds on S-03.

- **2026-11-10: [0011](../decisions/0011-host-service-lifecycle-contract-platform-adapters-and-credential-provider.md) Accepted (Overseer)** at the completion of F-06.2 (`f6e82bc`) and F-06.3 (the OA-10 run), as its draft set. Linux and macOS are accepted only at F-06.4 and F-06.5.

- **2026-11-10: Architect review of the coding-provider path (gates A, B, F and G), as the Owner directed.** [Recommendation](S-03-acp-coding-provider-recommendation.md), recorded with the Overseer's review; proposals only, nothing applied. The path: an OpenHands conversation whose agent is the SDK's `ACPAgent` (`agent_settings.agent_kind: "acp"`, `acp_server` from the pinned registry), the provider's adapter a child of the inner server inside the conversation container, authenticated by the per-attempt token through the create's `secrets` with its base URL at the guest `inference` endpoint, so only the broker holds a provider key; OpenHands-native direct-LLM agents stay an optional second body shape. Subscription logins are not a coding path at the pin (the SDK strips the base URL when a Claude OAuth token is present; a Codex ChatGPT login is a long-lived credential materialized into the container). The model-access plane and coding-provider qualification are separated (S-03.2 without a model; a proposed S-03.3 for the provider). The Owner's decisions are listed under OA-12.

- **2026-11-10: Owner decisions on OA-05 and OA-12** (a fourth message the same day), verbatim:

  ```text
  Owner decisions on OA-05 and OA-12.

  Continue autonomous execution. Do not interrupt any active
  Builder or discard its work.

  OA-05 — APPROVED, REVISION 2, OPTION (a)

  I authorize exactly one execution of
  evidence/F-10.5-oa05-guest-run-plan-rev2.md,
  option (a): the eight-file F-10.2 suite.

  Use the dedicated clean clone at:
  9751bdfedf41cf8dade0a8f7d8bf914ba1c18ddb

  Approved archive SHA-256:
  12090fc3881cfea74a7b0b526cebca41bc494847c32dd10f288dd32ba6a94b6e

  Use the documented manifest, wheels, runner, run script,
  guest profile, isolation conditions and teardown procedure
  without modification.

  No ninth test file, Git installation in the guest, new
  network connectivity, changed payload or automatic retry.

  Verify the exact inputs before execution and independently
  verify teardown afterward.

  Record the actual outcome and preserve the explicit limits:
  Linux Git-oracle parity, the native Linux Dulwich wheel and
  write_commit on Linux remain unverified.

  OA-12 — ARCHITECTURAL DECISIONS

  I accept the Architect's recommendation to preserve
  Claude Code and Codex as replaceable coding providers
  through OpenHands ACPAgent.

  The default engineering coding path must use ACP, not
  the OpenHands-native direct-LLM agent.

  Decision (a): AUTHENTICATION APPROACH ACCEPTED IN PRINCIPLE.

  Dedicated, spend-capped provider API keys through the
  inference broker are the preferred qualification mechanism
  under the existing credential and isolation constraints.

  This is not authorization to create or store a key,
  purchase API capacity, incur charges or make calls.

  Record that subscription authentication is not qualified
  for this sandboxed path at the pinned versions. Do not
  silently treat that limitation as universal or permanent.

  Decision (b): FIRST PROVIDER — CLAUDE CODE.

  Select Claude Code through ACP as the first provider to
  qualify. Preserve Codex as a supported, replaceable
  alternative, not a later custom integration.

  Claude Code is the initial qualification target, not a
  permanent exclusive provider choice.

  Exact model identifiers, including any secondary model
  used by Claude Code, remain to be verified and presented
  for approval before the first paid inference call.

  Do not use wildcard model allowances or assume a model
  name from memory.

  Decision (c): APPROVE THE DECISION 0015 AMENDMENTS.

  Amend proposed decision 0015 as recommended in
  evidence/S-03-acp-coding-provider-recommendation.md:

  - Bind per-attempt tokens to an API family.
  - Support the pinned registry's ACP provider credentials
    and base-URL settings through the create secrets channel.
  - Implement per-family, untranslated API pass-through.
  - Preserve model, path, attempt, budget and expiry limits.
  - Retain direct-model inference as an optional capability.
  - Withdraw the Chat-Completions-only narrowing.

  Preserve prior decision history and clearly distinguish
  architectural acceptance from execution authorization.

  Decision (d): APPROVE THE PLAN RECONCILIATION.

  Use the existing plan-integrity process to:

  - Reconcile S-03.1 and decision 0015.
  - Scope S-03.2 to the model-free inference-access plane,
    with independent denial and containment evidence.
  - Add S-03.3 to qualify the first real ACP coding provider.
  - Update the E-03.1 and E-03.2.2 dependencies.
  - Keep provider selection in the governed agent catalog.
  - Move the local Ollama acts to an optional native-inference
    capability, not the default coding-provider path.

  S-03.2 may develop and test offline implementations using
  synthetic credentials and fake upstreams.

  Actual host listeners, guest forwarding, guest hardening
  changes, provider credentials, external egress and model
  calls still require their respective explicit Owner acts.

  Decision (e): IMAGE ADAPTERS.

  First verify whether the exact pinned OpenHands image
  already contains the required Claude Code and Codex ACP
  adapters.

  Do not assume the Dockerfile's defaults prove the image
  actually contains those binaries.

  If missing, prefer a reproducible, pinned derived image
  using the existing composition and provisioning process.
  Present the exact change and qualification before adopting
  it. Do not silently fall back to runtime npx installation.

  SECURITY AND CONTRACT REQUIREMENTS

  The provider subprocess must remain inside the qualified
  execution container and its enforceable CPU, memory,
  filesystem, process and network boundaries.

  ACP permission-suppressing modes do not confer authority
  and are not isolation controls.

  Prevent unrestricted Owner credentials, inherited MCP
  servers, unexpected tools, arbitrary ACP commands or
  unapproved network destinations from entering the attempt.

  Preserve source authority, exact revisions, independent
  review and execution evidence.

  Do not build another orchestration layer or replicate
  OpenHands' existing ACP implementation.

  OWNER ACTION TRACKING

  Record these decisions against OA-05 and OA-12.

  OA-05 closes only after the authorized run and its evidence.

  For OA-12, separate accepted architectural choices from
  still-pending provider model names, credentials, budgets,
  external egress, host services and first model usage.

  Do not present the accepted architectural choices again
  unless new evidence materially contradicts them.

  Continue unrelated eligible work autonomously.
  Silence never constitutes approval.
  ```

  - **Overseer disposition** (2026-11-10):
    - OA-05: the inputs were checked before execution and the run was **not** started: the approved script binds the main checkout, not the clone the approval names (an Overseer error in revision 2's note). A one-line revision 3 is presented; nothing else changes. Recorded in the OA-05 row.
    - OA-12: decision 0015 amendment 1 written as approved, with its status separating architectural acceptance from execution authorization; the local-first request's section 3 refinement marked withdrawn; OA-12 moved to "Awaiting preparation" with the accepted choices and the pending items separated.
    - Next, serially: the P-04.2 fix-forward; the plan amendment by the integrity process (decision (d)); the image adapter check (decision (e)), read-only; then S-03.2 offline (synthetic credentials, fake upstreams).

- **2026-11-10: [0012](../decisions/0012-owner-authorization-channel-and-gitea-owner-identity.md) recorded, Proposed,** at P-04.2's offline build. The Architect's 2026-11-07 design (gates A, B and G; Owner confirmations 1 to 3 given 2026-11-07) with the build's amendments: the record's field order (with `format`), the policy check limited to what `aieh-owner` can observe at Gitea 28.3.0, the four manifest fields read until G-04.1.1, the recorder's state and receipt kind. Overseer rulings: the lost-answer settle rule rejected (no time-based inference; an open, unmerged pull request stays `unknown`); the unreadable protection fields recommended as detected, not prevented, for the Owner's decision (OA-15). It is accepted after the live exercise (OA-14) and that decision.

- **2026-11-10: plan amendment, S-03 reconciliation** (Owner decision (d) of 2026-11-10; the integrity process) `13cb939`, fix-forward `4aa01ad`; policy and security references `9f2e9a9`. The plan has 167 leaves and prompts (from 165). S-03.2 is re-scoped to the inference-access plane without a model (offline with synthetic credentials and a fake upstream per family; then the guest plane proof; Owner acts A2, A3, A4). New S-03.3 qualifies the first ACP coding provider (Claude Code first, Codex by the same registry path; the image adapter check first; recommendation R1-R7 and R11-R12; Owner acts A1, A5, A6; S-03's gate). New optional S-03.4 holds the local acts L1 and L2 (still held), never the coding path. E-03.1 gains S-03.3; E-03.2.2 and the E-03 and E-03.2 groups move from S-03.2 to S-03.3; K-02.2 notes it may consume S-03.4. The network matrix's broker-to-provider row and the ACP-authentication finding are carried to S-03.3. **Overseer verification:** verify_seed PASS (167; seed baseline 136); the three new proofs read against the Owner's decisions; the dependency graph acyclic; the checkers PASS. The plan has no optional marker: S-03.4 says so in its title, proof and notes, and S-03's notes say its gate does not wait for it. Detected, not changed: the `fd-acp-provider-auth` detail and the `inference-broker` realization note still say no plan leaf owns the broker (stale since S-03 was added); to reconcile at S-03.2.

- **2026-11-10: Owner decisions on OA-05, OA-14 and OA-15, and an architectural correction on external collaboration** (a fifth message the same day), verbatim:

  ```text
  Owner decisions on OA-05, OA-14 and OA-15, plus an
  architectural correction on external collaboration.

  Do not interrupt the active Builder.

  EXTERNAL HOSTING AND PUBLICATION — OWNER DIRECTION

  The AI Engineering Harness must be Git-host-agnostic.

  Git is the repository foundation. Local Gitea is our
  selected governance service, not a requirement that user
  repositories be hosted on GitHub.

  GitHub, GitLab, Bitbucket, Azure DevOps and other hosting
  services are optional integrations. Do not make GitHub
  authentication, APIs, CLI or issue tracking a prerequisite
  for operating the engineering system.

  More importantly, autonomous engineering must not
  automatically publish to third-party projects.

  Finding an upstream defect does not authorize creating
  an issue, comment, pull request, discussion or private
  vulnerability report in the upstream project.

  Revoke the outstanding, unexercised publication authority
  for OA-02, OA-03 and OA-09.

  Preserve their prepared findings, reproduction evidence,
  affected versions and upstream references as internal
  knowledge.

  Classify them as deferred or optional external reporting,
  not as "Needs Owner now" obligations.

  They must not block engineering or repeatedly surface
  as outstanding actions requiring my attention.

  External publication requires a new, explicit, scoped
  Owner decision naming the destination and exact proposed
  content. Never infer authorization from an engineering
  task or an earlier general approval.

  Do not install GitHub CLI, access GitHub credentials,
  use an external connector or create a provider-specific
  publishing workflow to resolve these findings.

  This does not prohibit ordinary authorized Git operations
  against repositories owned or configured by the user.

  Keep external contribution capabilities optional,
  provider-neutral at the semantic boundary, and separate
  from the core engineering lifecycle.

  OA-05 — APPROVED, REVISION 3

  Authorize exactly one run of the revised eight-file
  Linux qualification.

  The only permitted script change from revision 2 is:

  REPO = HERE.parent / 'clone'

  Expected revised script SHA-256:
  81d470ec8a123546985a1bb25dd53dc212fdbfd11b62dee9e79a1528829e8662

  Approved source revision:
  9751bdfedf41cf8dade0a8f7d8bf914ba1c18ddb

  Approved archive SHA-256:
  12090fc3881cfea74a7b0b526cebca41bc494847c32dd10f288dd32ba6a94b6e

  Verify the exact script diff and digest.
  Use the dedicated clean clone, never the main checkout.

  All other approved inputs, isolation, resource limits,
  transfer and teardown requirements remain unchanged.

  One run only. No automatic retries.

  Record the actual result and preserve the explicit
  limitations of the Linux qualification.

  OA-14 — PREPARATION APPROVED; MERGE NOT AUTHORIZED

  Authorize preparation of the bounded recorder exercise
  against aieh-authz-fixture/authz, including only the five
  named harness Credential Manager entries and the specified
  fixture proposals.

  However, test_live_authorization.py currently constructs
  an Owner-attributed authorization statement itself.

  A general test approval is not authorization for a
  dynamically generated operation that I haven't seen.

  Correct the workflow:

  1. Prepare the fixture and manifest.
  2. Issue the recorder's actual one-time challenge.
  3. Present the exact operation, head revision, manifest
     digest, effects and challenge to me.
  4. Require my subsequent explicit authorization.
  5. Only then perform the protected merge.

  The test must never manufacture Owner authority.

  Negative controls may be prepared and exercised within
  the authorized fixture scope, with any unexpected
  successful bot merge treated as a security failure.

  Preserve credential custody and teardown checks.

  OA-15a — DETECTION-ONLY PROPOSAL DECLINED

  Do not narrow the protected-merge acceptance requirement
  to only the branch-protection fields visible to aieh-owner.

  A consequential authorization must fail closed if its
  required protection settings cannot be verified.

  Investigate a narrowly scoped, trusted read-only check
  of all security-relevant protection rules immediately
  before the merge.

  Do not give aieh-owner administrator privileges or place
  administrator credentials in the recorder.

  Prefer an existing trusted mechanism or a small bounded
  verification adapter, not another policy service.

  Keep decision 0012 Proposed until the required control
  is established and qualified.

  OA-15b — BLUEPRINT RECONCILIATION APPROVED

  Authorize M-4 through the existing integrity-controlled
  blueprint maintenance process.

  The Owner makes the authorization decision.
  The deterministic recorder performs the protected merge
  using the aieh-owner authority identity.

  Preserve the distinction between the Owner, the recorder
  and the Gitea identity.

  No model or agent may manufacture an Owner decision.

  RECONCILIATION

  Update the existing Owner-action queue and decision
  evidence. Preserve prior authorization history while
  recording the subsequent withdrawal of unexercised
  external-publication authority.

  Do not create a separate workflow or task system.

  Continue unrelated ready engineering work autonomously.
  Silence never constitutes authorization.
  ```

  - **Overseer disposition** (2026-11-10):
    - External collaboration: recorded as [decision 0017](../decisions/0017-git-host-agnosticism-and-owner-scoped-external-publication.md) (Accepted, Owner). OA-02, OA-03 and OA-09 moved to Resolved as "publication authority withdrawn, unexercised", their findings kept as internal knowledge; they are no longer reported as Owner actions. A bounded read-only audit for hosting-provider prerequisites is scheduled.
    - OA-05: revision 3 verified (one-line diff, sha256, clean clone, unchanged inputs); the one run follows the active builder.
    - OA-14: moved to Awaiting preparation; the exercise is reworked to issue the real challenge and stop for the Owner's explicit authorization before any merge.
    - OA-15: resolved by the decisions. (a) Decision 0012 point 6 amended to fail closed; the Overseer consults the Architect (gate G) on the trusted read-only protection check before the recorder is changed. (b) M-4 to be performed by the integrity process.

- **2026-11-10: Owner direction: external defect reporting deferred from the first release** (a sixth message the same day), verbatim:

  ```text
  Additional Owner architectural direction:
  Defer external defect reporting from the first release.

  External defect reporting is not merely creating an
  issue through GitHub, GitLab, Gitea or another service.

  Before publication, the system would need to assemble
  a complete defect kit containing:

  - Minimal, independently reproducible steps
  - Relevant platform, machine and environment details
  - Expected and observed behavior
  - Problem description and impact
  - Known or plausible workarounds
  - Plausible solutions, clearly identified as hypotheses
    when not verified

  A complete capability would also require review for
  secrets and sensitive information, explicit Owner
  publication authorization, host-specific submission
  adapters, tracking of posted reports, upstream responses,
  fixes and their eventual adoption.

  I do not authorize building that capability in the
  first release.

  Retain existing OA-02, OA-03 and OA-09 technical
  findings as internal evidence. Do not invest further
  effort in preparing publication kits for them.

  Do not file external reports, install publishing tools,
  build provider-specific issue integrations, or introduce
  a new reporting or tracking subsystem.

  Do not keep these findings in "Needs Owner now".
  They are internal findings with no publication obligation.

  Continue consuming relevant upstream fixes and tracking
  known upstream issues when doing so directly supports
  our own engineering and dependency management.

  Record external defect reporting as a deferred optional
  capability, without adding executable first-release Work
  or changing the core implementation plan.

  Continue autonomous work on eligible first-release tasks.
  ```

  - **Overseer disposition** (2026-11-10): recorded as an addendum to [decision 0017](../decisions/0017-git-host-agnosticism-and-owner-scoped-external-publication.md); no plan change and no Work added. OA-02, OA-03 and OA-09 are already in Resolved as internal findings with no publication obligation (the earlier disposition of this day); no further effort on their publication kits. Upstream fixes and known upstream issues keep being consumed and tracked where they serve the harness's own engineering and dependency management.

- **2026-11-10: Architect consultation (gate G) on the fail-closed protection check (OA-15a).** [Recommendation](P-04.2-protection-check-recommendation.md), recorded with the Overseer's review; nothing applied. Recommended: a read-only audit identity through Gitea's own API (a restricted Bot with repository-administrator collaboration on the admitted repository only, one `read:repository` token) and a small in-process adapter bracketing the merge; put to the Owner as OA-16. Findings: F-A, the bypass allowlist at 28.3.0 lets listed accounts merge past every gate and no harness record names it (exposed-by P-04.2); F-B, branch-protection changes made through the API leave no audit event at 28.3.0 (internal knowledge, decision 0017); F-C, the fixture's protection rules are not total.
- **2026-11-10: S-03.3 image adapter check (Owner decision (e)).** `tools/guest.py image-inspect` (`3e12723`) read the staged, lock-verified image as data: `/usr/local/bin/claude-agent-acp` (claude-agent-acp 0.63.0), `/usr/local/bin/codex-acp` (codex-acp 2.2.2) and `/acp-node/bin/node` are present; recommendation R4 holds for both providers ([evidence](S-03.3-image-adapter-check.md), `19509a7`). The bundled CLIs were not opened; nothing was executed. Overseer verification: the code reads only; the output file's per-path rows checked against the evidence; budget PASS at `ebbce7f` (145.6 s).

- **2026-11-10: F-10.5 Linux ceiling finding: diagnosis, Overseer ruling and fix.** The two `Ceilings` failures of the OA-05 run come from the product's path canonicalization: on POSIX `os.path.realpath` calls `os.lstat` once per ancestor, and the test's spy watches `os.lstat`; discovery's own probes never go above the ceiling on either platform (reproduced offline by forcing POSIX canonicalization). **Ruling (Overseer):** "examined" in the ceiling contract means the upward search's probes, as decision 0014 section 8 frames it and as git's ceiling semantics are (git resolves ceilings to real paths); metadata lookups by canonicalization are not examinations by the search. No accepted decision or plan proof is narrowed: the broader wording was in the README and the F-10.4 evidence, corrected with a dated note. Fix `3cf45cd`: the observation is suspended only during canonicalization; forced-POSIX variants and a positive control make Windows cover Linux's behaviour offline, boundary-safe (nothing above the test's temporary root is stat-ed); mutation evidence in [F-10 evidence](F-10-dulwich-migration.md). Revision 4 of the run plan is presented as OA-17. **Process defect (disclosed):** the diagnosis's one-off reproduction made single metadata lookups (`lstat`) on the real ancestors of its scratch directory, including the user's profile directory and its parent; no listing, search or read; the managed data root was not touched. Classified a path-boundary defect of the dispatch; the fix dispatch forbade it and the committed variants answer above-root lookups synthetically. **Budget:** the gitea suite's wall sits at its limit (3.2 to 3.36 s over five runs against 3.25 s) with no gitea change; unrelated-but-detected; every row the fix touches passes (serial 146.8 s); a headroom slice for the gitea suite follows instead of a raised wall.

- **2026-11-10: Hosting-provider prerequisite audit (decision 0017, Consequences).** [Evidence](0017-hosting-provider-audit.md): a Builder's read-only audit of every tracked file at `d95542e`. **No hosting provider is a prerequisite of operating the system**: no plan leaf's proof needs a provider's CI, API, CLI or issue tracker; no tool or task target uses a provider credential or CLI; no document requires a provider account to operate; no `.github/` tree is tracked; the CI runner profile fixes `default_actions_url: self` and the CI policy checker refuses any `uses:`. Observed, anonymous pinned fetches whose only origin is a provider host: `composition/resolve.py` (GitHub releases API and GHCR, `task resolve` / `task qualify` only), `guest:provision-fetch` (the Agent Server binary and crane from GitHub, the image from ghcr.io; no local-source argument seen) and the publication gate's Gitleaks download (contributing, not operating); Gitea has a `--from-file` alternative. **Overseer rulings:** (1) an anonymous fetch of a hash-pinned artifact is not a prerequisite in decision 0017's sense (its subjects are a provider's authentication, API, CLI and issue tracker); recorded as an observation, and an offline local-source option for `guest:provision-fetch` stays a possible future slice, not Work now; (2) leftovers from the withdrawn publication path (class E) are reconciled as records, not as plan changes, since the Owner's 2026-11-10 addendum adds no Work and leaves the plan unchanged: the E-01.2.2, E-01.4.3 and F-10.6 rows carry a dated note; decision 0006 carries a dated reconciliation note (its text kept); E-01.4.3's plan wording ("File the upstream report") is left as the original baseline, governed by decision 0017 where it disagrees (0017's own precedence clause); the OA-03, E-01.4.3 and F-10.6 evidence drafts stay unchanged, as 0017 directs; `security/inventory.json` (a live record, "Upstream report to be filed") is reworded by a Builder and its README re-rendered. Not determined: whether `guest:provision-fetch` runs offline from an already staged state; whether the pre-commit hook fails closed without Gitleaks.

- **2026-11-10: decision 0017 audit follow-ups.** `security/inventory.json` `fd-outer-server-local-recovery` reworded from "Upstream report to be filed" to "Upstream report deferred (decision 0017) ... kept as internal knowledge" (`be23a79`; kind, status and every other field unchanged; the README bullet edited to match, since no renderer covers it; inventory checker counts unchanged). The audit's open question on the publication gate is answered from source: the hook and `tools/publication_gate.py` fail closed (exit 2) when Gitleaks is missing, its hash is wrong or the scan does not complete. Process note: that Builder ran one unrequested `git stash` round trip to measure the before state (no loss).

- **2026-11-11: S-03.2's child-conversation clause and the synthetic-key launcher (Architect consultation, gates A and G; advisory).** [Proposal](S-03.2-plan-amendment-proposal-child-clause.md). Gate A: slice 3 found the clause unmeetable as the plan stands; the Architect confirmed it (introduced by its own recommendation's S-03.2 row, carried into the plan at `13cb939`; exposed by slice 3) and recommended showing the child's containment by a probe-created child through the inner children route with the conversation's key, and moving the agent's own launch to the leaves that run agents live. **Overseer:** accepted, with one adjustment: S-03.4 is optional and nothing depends on it, so the native agent's launch is assigned to the first leaf that runs an openhands-kind agent, made concrete in S-03.4; presented to the Owner as OA-19 (a plan and acceptance-criteria change is the Owner's). Gate G: a qualification-only launcher taking a synthetic key on standard input does not conflict with decision 0015's custody (sections 2, 6; I6 binds `select_provider` on the production path) under four constraints (loopback-http upstreams only; standard input only, no terminal, a mandatory synthetic prefix; a start receipt with the fingerprint and source `stdin-qualification`; a separately named command, never a `serve` flag or variable). **Overseer ruling:** accepted; built offline under decision (d); running it is part of act A2, whose presentation will name it; it gives the provider-key fingerprint search a positive control. Further inconsistencies the Architect found, carried as records after OA-19: decision 0015's Consequences still say S-03.2 builds the create's LLM fields (superseded by amendment 1 item 2; a dated note to come); the S-03.1 authorization request's list "What S-03.2 will prove" includes items needing A1 and A5, now S-03.3's (re-presented leaf by leaf with A2 to A4); `fd-child-conversation-tool`'s `carried_to` (S-03.2) and S-01.3.1's evidence (E-01.2.2) disagree.

- **2026-11-11: Owner decisions on OA-16, OA-17, OA-18 and OA-19**, verbatim:

  ```text
  Owner decisions: OA-16, OA-17, OA-18 and OA-19.

  Continue autonomous execution. Do not interrupt the
  active S-03.2 Builder.

  OA-16 — APPROVED: READ-ONLY PROTECTION AUDITOR

  Approve option 2 of
  evidence/P-04.2-protection-check-recommendation.md.

  Use a dedicated restricted Gitea Bot,
  aieh-bot-protection-audit, with repository-admin
  collaboration only on the admitted authorization
  repository and a token scoped exactly read:repository.

  This accepts the distinction between repository-admin
  visibility and an API token that cannot perform writes.
  It does not permit a site-admin identity or token,
  an administrator credential for aieh-owner, or broader
  permissions.

  Build the bounded protection verifier through the
  existing Gitea integration. Check the full declared
  protection policy, including bypass lists, rule
  precedence, collaborators, teams, deploy keys and
  merge settings.

  Fail closed on missing fields, unexpected fields,
  policy drift, invalid credentials or failed reads.

  Preserve the pre-merge verification and post-merge
  evidence. Gitea's merge-time enforcement and the
  remaining time-of-check/time-of-use limitation must
  be explicitly documented.

  Live provisioning of the new identity or credential,
  changing Gitea collaborators or protection settings,
  and executing live merge tests remain separate Owner
  acts. Present them when prepared.

  Require live negative tests demonstrating that the
  read-only token cannot modify protection, change
  permissions, push, merge or escape its scope.

  OA-17 — APPROVED: ONE REVISION-4 LINUX RUN

  Authorize exactly one execution of
  evidence/F-10.5-oa05-guest-run-plan-rev4.md.

  Approved source commit:
  3cf45cd953642e90c4bbf6be63cf3d5483e9a0bc

  Approved archive SHA-256:
  ac9693599f8ed97272e23dd9c1f4f7b94d6bf23849a872bbbead7ddd740e6c8d

  Approved run script SHA-256:
  2d67a7cb80a83a96436e1b34628adb2da18e8b31daed411744c86707a06087ba

  Use the dedicated clean clone, the exact eight-file
  payload and the previously approved isolation,
  resource, transfer and teardown conditions.

  Verify the binding hashes before execution.
  No changes to the main checkout, no additional files,
  no automatic retries.

  Record actual outcomes, independent teardown and
  the Linux capabilities that remain unverified.
  Do not promote a partial Linux result to full
  cross-platform qualification.

  OA-18 — APPROVED: M-5 BLUEPRINT RECONCILIATION

  Approve the exact wording-only reconciliation
  described in the M-5 maintenance row.

  The Owner makes the decision on the presented exact
  operation and challenge; the deterministic recorder
  executes the authorized merge as aieh-owner.

  Remove remaining instructions requiring the Owner
  to log into Gitea and merge personally.

  Check the catalog passage separately against
  decision 0012's actual scope; do not extend recorder
  authority to unrelated operations by changing wording.

  Use the existing integrity-controlled blueprint
  change process. Preserve historical evidence and
  all accepted authority and security requirements.

  OA-19 — APPROVED WITH QUALIFICATION AMENDMENT

  Approve the separation proposed in
  evidence/S-03.2-plan-amendment-proposal-child-clause.md,
  section 3, subject to the following correction.

  S-03.2 must demonstrate the model-free broker and
  network containment properties. Probe the inner
  children route with the conversation's own key.

  If it creates a child, verify that the child remains
  in the parent's container, under the same limits,
  without an outer-server conversation or new
  container/listener.

  If it refuses creation without model settings, record
  the refusal as a demonstrated fail-closed outcome,
  NOT as proof of successful child containment.

  The latter behavior remains unverified and must
  retain a traceable qualification obligation. S-03.2
  may satisfy its model-free acceptance requirements
  without falsely claiming that a child ran.

  S-03.3 must independently prove that the real ACP
  coding provider and any delegated processes remain
  under the execution container's limits, and that
  no unexpected outer-server conversation appears.

  Do not assume ACP provider delegation uses the
  OpenHands start_child_conversation tool. Verify the
  actual supported mechanism and distinguish the two
  behaviors in evidence.

  If native OpenHands agent execution is enabled, its
  start_child_conversation capability must be qualified
  at the first leaf actually enabling that capability.
  S-03.4 alone must not become a mandatory dependency
  of the default ACP coding path.

  Preserve the provider-key containment requirement.
  A fingerprint-only search must not be described as
  proof of absence of the underlying raw credential.
  Use evidence appropriate to the actual secret
  exposure boundary, with a positive control, without
  printing or persisting credential material.

  Keep actual paid inference, model IDs, provider-key
  storage and use, external egress, host listeners,
  guest hardening and forwards behind their explicit
  Owner authorization acts.

  Apply the plan amendment through the established
  integrity-controlled process. Reconcile related
  inventory and decision references, preserving
  provenance and verified-versus-unverified distinctions.

  The synthetic-key launcher ruling is accepted as
  an offline qualification mechanism only. It does
  not authorize act A2 or any live listener.

  Record these four Owner decisions without reopening
  settled choices. Continue other eligible work.
  Silence never constitutes authorization.
  ```

  Overseer reading (no settled choice reopened): OA-16 accepts the read-only auditor and directs the verifier through the existing Gitea integration, failing closed on missing or unexpected fields, drift, invalid credentials or failed reads; every live act is presented separately. OA-17 is one run only, performed as the revision 3 run was, after the active Builder returns. OA-18 is wording only, through the integrity process. OA-19 corrects the proposal: a refused child is a fail-closed outcome, never proof of containment, and successful child containment stays a traceable obligation; ACP delegation is not assumed to be `start_child_conversation`; the native tool is qualified at the first leaf that enables it; a fingerprint search is not described as proof of absence. The synthetic-key launcher is an offline qualification mechanism only and authorizes neither A2 nor any listener.

- **2026-11-11: Overseer process deviation: a push before the history gate.** A chained command (`a && b ...; push`) whose first step, a log-recording script, stopped on its own assertion skipped the chained publication-gate step, and the unconditional push after it sent the Builder's verified slice 4 commits (`9838ed6..447efe0`) without the Overseer's history gate. The private-path grep did run and was clean, and every commit had passed the pre-commit gate. The history gate was run on exactly that range at once: PASS (5 commits, 23 blobs and messages). Cause: the assertion was right, since an earlier log row of the Overseer's carried a literal `|` inside a table cell (S-03.2, "`CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`"), which split the row; repaired in `3b14d55`. A table scan then found one more such cell (the F-04.2 row's "`ls … | head -2`"), repaired with this entry; rows with one cell fewer than the header are the table's long-standing form and render an empty last cell. Correction: the gates and the push now run as separate fail-fast steps (`set -e`).

- **2026-11-11: OA-19 and M-5 applied (integrity process).** Plan `2f973b0`: the corrected OA-19 wording applied to S-03.2 (the key-containment clause and the child-conversation sentences), S-03.3 (proof and notes), S-03.4 (proof) and A-01.2 (notes), with the leaves' `completion_evidence`, `overseer_prompt`, the HTML and CSV projections, three task prompts, `task_manifest.json` and `SEED_MANIFEST.json`; a new amendments entry. **Overseer verification:** a structural diff of the plan against `7b05f78` shows only those fields of those four leaves and the amendments list changed (245 leaves both sides; no status, dependency, title or gate); the S-03.2 proof states the fail-closed refusal is not proof that a child ran and that a fingerprint search alone is not proof of absence; verify_seed PASS in both modes; the Builder's tools suite 1278 OK. Ruling: S-03.3's appended paragraph follows the whole sentence that ends "... documented as not a boundary." (inserting mid-sentence would split it). Inventory `cebd3ab`: `fd-child-conversation-tool` carried to S-03.2, S-03.3 and A-01.2, history kept. Decision 0015 carries a dated reconciliation note at its Consequences sentence on the create's LLM fields (this commit; text kept). Detected, not changed: `security/README.md`'s hand-kept row for that finding still says "Carried to: S-03.2." (carried to the next Builder slice).

- **2026-11-11: OA-16 verifier built offline and verified; live acts presented.** The Builder's four commits (`20377ea`..`394bfa1`) were checked by the Overseer as the P-04.2 row states and pushed after the publication gate and the private-path grep. Decision 0012 stays Proposed. The live acts were presented to the Owner, each a separate Owner act, none performed: (A) `gitea_roles.py provision` creates the restricted Bot and mints its `read:repository` token into the sixth Credential Manager entry `AIEH Gitea bot protection-audit`; (B) `gitea_roles.py fixture` gives it repository-admin collaboration on `aieh-authz-fixture/authz` only and applies the total protection declaration and merge settings (live changes: `block_on_outdated_branch` true on `main`, rebase, squash and fast-forward-only merges off), then the check's baseline; (C) the negative tests, which need a repository the auditor is not a collaborator of; (D) the qualification by injected drift; (E) OA-14's live exercise, which now also reads the sixth entry, beyond the five OA-14 named.

- **2026-11-11: serial test runtime reduced, no test weakened** ([record](test-runtime-2026-11-11.md)). The serial median had reached 145.7 s against the 150 s ceiling, which is never raised; the Overseer dispatched a reduction before further slices. Builder commits `79b75be`..`6cfc80f`: fixture git without auto-maintenance, one exact duplicate evaluation removed from a fuzz loop (every distinct input still evaluated), small fixture repositories for the guest smoke and inventory tests through the existing `repo_root` seam, concurrent refused connects and oracle commands, a copied migrated empty store, the custody refusal tests at their own short time-out, snapshot fixture copies, a per-class profile work copy checked before every test, and one byte-identical product change (`guest.write_json_exclusive` writes one `json.dumps`, with a byte-equality test; saving about 0.07 s, kept as allowed). Test count unchanged apart from that test (2466 to 2467); the outcomes digest equal before and after. Walls lowered (store, effects, planning, lineage, dispatch, the integration category). **Owner wall 4.0 to 4.6 s (Overseer ruling):** raised by exactly the measured cost of the 13 owner tests OA-16 added (per-test medians summing 0.585 s, rounded up to 0.6 s), the rule that walls rise only by the measured cost of new tests; its old budget predated those tests. A fix-forward (`808d96c`) of a test the Builder weakened in `73c40a8`; that commit message's last sentence is wrong and the record corrects it (history not rewritten). **Overseer verification:** the product change read; budget `check --run` PASS at `6cfc80f` on the idle host (serial 133.8 s, tools 72.8 s, owner 5.1 s; cleanmgr absent before and after); verify_seed PASS; publication gate and private-path grep clean before the push.

- **2026-11-11: E-01.3.3 architecture consultation (gates A and G) and the Overseer's rulings.** The Architect (read-only) found that "dispatcher principal" has three senses the leaf's proof conflates: the code path (the dispatch module as the only path for op-as-* on Work), the guest login that reads the key (today `agent`), and a host identity distinct from the Owner's account (no leaf builds it; decision 0013 point 1 makes bootstrap the Owner's account). With one host account, a second guest login would be a second door on the same key ring, so a probe passing on it would be custody theatre. **Rulings (Overseer):** (F-2) the bootstrap reading of decision 0013 point 1, as written: the dispatcher principal is the Owner's account through the dispatch module over `tools/guest.py`'s `GuestApi` as `agent`; the guest key file stays `root:agent 0440` (R9); the host copy stays the leak-scan needle, disclosed under point 6; E-01.3.3's cut-over is the code path one; the separation of an operator login is deferred to the first leaf that changes the seed for the Owner UI forward (OA-07, U-03.1), and the dispatcher's own host identity is a plan silence routed to the Owner. (F-1) rotation realized literally under decision 0007 point 4: the dispatcher revokes a stage's token at the last release (`DELETE /api/v1/token`, a receipt), re-issuance stays the site administrator's act through the administration command, the dispatch package reaches no mint, and the residual is recorded as a limit; the dispatcher is not granted issuance. (F-3) the UI clause read as the UI's credential class: a dispatcher-minted conversation runtime credential is refused on every key-gated management route and admitted only by its conversation's inner server; the host copy is the disclosed limit; the UI's forward channel stays U-03.1's. Because the proof text is Owner-approved plan text (the 2026-11-08 amendment), the corrected wording goes to the Owner as a plan amendment (OA-20); the offline outcomes proceed meanwhile, and the guest probe and the PASS wait for it. No decision text changes; a dated current-facts note on decision 0013 follows the Owner's answer. Disclosed by the Architect: one scratch file written to the checkout root for about two minutes and removed (no tracked change; tree clean, checked by the Overseer).

- **2026-11-11: Owner architectural correction, E-01.3.3 token lifecycle (verbatim).** It supersedes the Overseer's ruling F-1 of the same day (revocation at the last release), which the Owner did not accept; the Builder received it before any revocation code was written. Verbatim:

  > Owner architectural correction — E-01.3.3 token lifecycle.
  >
  > Do not interrupt the active Builder except to prevent
  > implementation of the following defect.
  >
  > I do not accept routine revocation of a standing Gitea
  > builder or reviewer bot token when the last attempt
  > using it ends, unless an authorized, automatic
  > replacement mechanism already exists.
  >
  > Gitea 28.3.0 requires administrator authority to
  > issue a replacement for these passwordless bots.
  > Revoking the standing credential after every attempt
  > would make normal engineering execution dependent on
  > repeated administrator operations.
  >
  > Distinguish three lifecycles:
  >
  > 1. Standing Gitea bot credential
  >
  >    Held in the trusted host's credential provider.
  >    Its issuance, rotation and actual Gitea revocation
  >    remain under the existing administrative authority.
  >
  >    Rotate or revoke for defined security and lifecycle
  >    triggers, not routine attempt completion.
  >
  > 2. Per-attempt use of that credential
  >
  >    The dispatcher obtains the stage's mapped credential
  >    only for a confirmed attempt, retains it in memory
  >    within the bounded operation, and releases access
  >    when the operation ends.
  >
  >    Do not expose it to agents, guest containers,
  >    conversation records or the UI.
  >
  >    Releasing the in-memory reference is not Gitea token
  >    revocation. Record that distinction accurately.
  >
  > 3. Per-attempt inference token
  >
  >    This remains an independently issued, bounded
  >    credential and must be revoked at attempt end,
  >    as specified by decision 0015.
  >
  > Do not grant administrator authority to the dispatcher
  > or introduce a new credential-issuing service.
  >
  > Require tests demonstrating:
  > - Two sequential attempts of the same stage succeed
  >   using the authorized standing credential.
  > - Concurrent attempts cannot invalidate one another.
  > - An actually revoked Gitea credential fails closed
  >   until the administrator-managed lifecycle restores it.
  > - No stage credential or its raw value reaches the guest.
  > - A confirmed attempt cannot acquire another stage's
  >   credential.
  >
  > Reconcile this with the existing wording "rotate role
  > tokens per attempt where Gitea allows it." Gitea does
  > not provide the required replacement mechanism to the
  > dispatcher, so do not interpret that clause as requiring
  > destructive revocation after every attempt.
  >
  > Have the Architect review this correction if necessary.
  > Incorporate it into the proposed OA-20 amendment, with
  > the precise distinction between implemented security
  > controls and disclosed same-account limitations.
  >
  > Do not silently modify Owner-approved acceptance
  > criteria. Present the exact amended text for approval.
  >
  > Keep the management-key and UI rulings otherwise
  > unchanged. No live operations are authorized by this
  > instruction.
  >
  > Continue eligible offline work.

- **2026-11-11: Owner reconciliation for OA-20, decision 0007 (verbatim).** OA-20 will carry an explicit amendment of decision 0007 points 4 and 5 (the historical text kept), together with the E-01.3.3 plan wording and the records that restate the superseded clauses. Verbatim:

  > One additional reconciliation for OA-20.
  >
  > I checked accepted decision 0007. Its point 4 contains
  > two requirements that conflict with the corrected
  > E-01.3.3 implementation:
  >
  > 1. It says the dispatcher delivers Gitea role tokens
  >    into the attempt environment.
  > 2. It says tokens are otherwise rotated at attempt end.
  >
  > Point 5 also lists attempt end among revocation
  > triggers without sufficiently distinguishing
  > credential classes.
  >
  > OA-20 must reconcile all three statements, not just
  > add a historical note about rotation.
  >
  > The intended behavior is:
  >
  > - Standing Gitea bot credentials remain on the
  >   trusted host under administrative issuance,
  >   rotation and revocation.
  > - The dispatcher borrows the mapped credential for
  >   a confirmed operation, then releases its in-memory
  >   access without revoking the Gitea token.
  > - Standing Gitea tokens never enter the guest,
  >   agent environment or conversation.
  > - Broker-issued inference tokens remain scoped per
  >   attempt and are revoked at attempt end.
  > - Security-triggered revocation of standing Gitea
  >   credentials remains effective and fail-closed.
  >
  > Preserve decision 0007's historical text and
  > provenance, but make its superseded clauses explicit
  > through a properly authorized amendment. Do not leave
  > contradictory current requirements.
  >
  > Include this reconciliation in OA-20's exact proposed
  > wording for my approval.
  >
  > Do not interrupt the Builder or broaden its scope.
  > Continue the existing offline implementation.

- **2026-11-11: no-window audit and helper (the Owner's rule after the window incident).** The Builder's audit found 29 launches in `tools/` and `integrations/` without `CREATE_NO_WINDOW`, among them `Ssh.run`, and two `DETACHED_PROCESS` starts (QEMU, and the Gitea supervisor, which starts a console child) (`410132b`). An unconditional flag cost about 7 ms per launch and took the serial median to 147.0 s (one run 154.9 s) against the 150 s ceiling, which is never raised. **Overseer ruling:** the purpose is that no harness process opens a visible window, so one helper, `integrations/platform/no_window.py`, gives the flag when this process is attached to no console and inheritance otherwise (a child sharing a console opens no window); QEMU, the Gitea supervisor, Gitea and the forward holder keep it unconditionally (`f8ba6ec`). The Builder verified the premise in kill-on-close jobs for three parent states (a pseudo console, a parent started with `CREATE_NO_WINDOW`, a detached parent): no case opened a window. Accepted deviation: the test is `GetConsoleProcessList` (attached to any console), not `GetConsoleWindow`, which is NULL for a windowless console and would have re-imposed the cost in agent sessions. A repository-wide guard (`tools/tests/test_launch_census.py`, `composition/` included) fails on any launch without the helper or the unconditional flag and on `DETACHED_PROCESS` or `CREATE_NEW_CONSOLE`, with a negative control; allowlisted: `guest.py exec` (an interactive passthrough whose console handles the flag breaks), `guest_drill` (runs in the Linux guest) and `verify_seed.py` (integrity-tracked). Accepted: the flag added to `tools/publication_gate.py`'s launches (the gate rule protects the hooks path, `.githooks/` and `.gitleaks.toml`). **Overseer verification:** the helper read; budget `check --run` PASS at `2fd333c` on the idle host (serial 139.1 s; cleanmgr absent before and after); verify_seed and the contract checkers PASS; publication gate and private-path grep clean. Not verified: console behaviour outside Windows 11; a live guest or Gitea start since the change.

- **2026-11-11: Owner direction, test runtime is diagnostic, not a gate (verbatim).** It supersedes the 150 s serial ceiling, the per-suite wall-clock ceilings and the exact launch and mkdtemp budgets as blockers of ordinary work. Verbatim:

  > Owner direction: stop optimizing tests against the
  > fixed 150-second serial runtime ceiling.
  >
  > The current test infrastructure is sufficiently fast
  > and mature for development to continue.
  >
  > I do not want repeated Builder assignments that
  > recover 5-15 seconds whenever legitimate new tests
  > consume the available headroom.
  >
  > Stop the active "Serial test runtime reduction 2"
  > Builder cleanly. Preserve any useful completed
  > findings, but do not require it to achieve another
  > runtime target or initiate further optimization rounds.
  >
  > Change the testing policy as follows:
  >
  > 1. Retire the hard 150-second serial-suite
  >    acceptance requirement.
  >
  > 2. Retire per-suite wall-clock ceilings and exact
  >    launch/mkdtemp budgets as routine blockers for
  >    accepting ordinary engineering work.
  >
  > 3. Keep test runtime measurements and process counts
  >    as diagnostic information, not continuously
  >    rebaselined performance gates.
  >
  > 4. Prefer parallel tests by default wherever they
  >    are deterministic and independent.
  >
  > 5. Continue preferring in-memory fixtures, mocks
  >    and stubs for unit tests. Use real filesystems,
  >    processes, services and repositories only where
  >    their behavior is actually being qualified.
  >
  > 6. Preserve:
  >    - All existing behavioral and security assertions
  >    - Fail-closed security and authorization tests
  >    - Test category separation
  >    - Unit-test isolation rules
  >    - Independent integration and contract tests
  >    - Detection of accidentally removed or skipped tests
  >    - Process cleanup and no-visible-window requirements
  >    - Deterministic, reproducible outcomes
  >
  > 7. Do not weaken or delete tests to improve speed.
  >    Do not reduce coverage or hide failures.
  >
  > 8. During development, run focused affected suites.
  >    Run the applicable broader suite at acceptance
  >    and release gates. Do not repeatedly validate
  >    unchanged artifacts without a reason.
  >
  > 9. Investigate significant, sustained performance
  >    regressions, not small increases caused by
  >    legitimate new tests. As a review heuristic,
  >    consider roughly 50% regression from comparable
  >    measurements or a full suite exceeding five
  >    minutes. These are investigation signals, not
  >    automatic work-blocking thresholds.
  >
  > 10. Never launch an optimization workstream merely
  >     because a passing suite approaches an old budget.
  >
  > This supersedes my earlier 150-second requirement.
  >
  > Reconcile the canonical F-09 acceptance criteria,
  > test-budget policy, checker behavior, developer
  > documentation and generated task prompts through
  > the existing integrity-controlled process.
  >
  > Preserve their historical provenance. Keep genuine
  > test failures blocking, but remove artificial
  > performance gating and per-change budget churn.
  >
  > Make the minimum required policy/tooling changes.
  > Do not build a replacement performance management
  > system or spend another extended period benchmarking.
  >
  > Then return engineering capacity to the critical
  > path: authorization, dispatch, inference qualification,
  > coding providers, independent review and delivery.
  >
  > OA-20, the G-01.1 policy admission and C-3 remain
  > separate Owner decisions. Do not infer approval
  > of those actions from this testing direction.
  >
  > Continue autonomous eligible engineering work.

- **2026-11-11: the second runtime-reduction slice stopped cleanly under that direction.** Kept, each verified by the Overseer (the six contract checkers PASS; tools suite 1327 OK, 6 skipped, its data root empty afterwards; verify_seed PASS): `7d02e72` (the custody-probe test class launches each distinct sweep once per class, 18 launches to 2; test only), `dedc6ae` (a byte-identical memo of the checkers' machine-path and link answers, proven by running all 2,096 checker-test calls on the old and new checkers with equal problem lists), `b9a8faf` (a test digest helper reading whole files; equal digests), and `04ecee6` (findings, marked diagnostic). Diagnostic finding: of the rise from `f3da010` to `a3cf0ab`, about 5 s was the cost of the new test classes and about 12 s was host drift (the same revision measured 133.8 s and 145.7 s on the same day). No budget commit; no further optimization. Process note: a background-command stop did not end its child processes; the Builder ended them and its final check found none of its processes left.

- **2026-11-11: the testing policy reconciled with the Owner's direction (integrity process).** ([record](F-09-testing-policy-2026-11-11.md)). Builder commits `8b9442e`..`cbee59c`. `tools/check_test_budget.py` (policy v2): wall times, launch, mkdtemp, socket and chdir counts are notes, never failures; the Owner's two investigation signals are notes (`WALL_SIGNAL`: about 50% above a recorded figure; `FULL_SUITE_SIGNAL`: serial total above 300 s); still blocking: failing or erroring tests, outcomes differing between runs, uncategorized classes, unit classes that launch, open a socket or change directory, and removed or newly skipped tests against a recorded set of test ids (`evidence/test-profile/test-ids.json`), so new tests need no commit and the set is re-recorded only when tests are deliberately removed or skipped. `task test` runs the 13 suites in parallel (`tools/run_tests.py`, each in its own process and empty data root, through the no-window helper); `task test:serial` keeps the serial run. The plan (amendment entry quoting the direction): the 150 s clause and the budget-regression clause removed from the F-09 group's proof and the F-09.1, F-09.3 and F-10.3 proofs and the inherited required outcomes; actions and artifacts describing completed work unchanged. **Overseer review:** a structural diff of the plan found the group's `original_proof` (and F-09.4's gate copy of it) rewritten; restored to their earlier text as historical fields (`6b9a6ec`), with the amendment entry and F-09.4's note saying so. **Overseer ruling:** F-09.4's inherited gate displays the historical original proof as provenance; it is evaluated against the group's amended proof, the Owner's direction having superseded the 150 s requirement. Fixed forward: `tools/test_profile.py` (a tool whose name starts with `test_`, hidden from the no-window guard) now uses the helper, and the guard skips only `tests/` directories (`34d36a2`). **Overseer verification:** the plan's field diff against `f8506b2` checked; verify_seed PASS in both modes; the full suite once through the new parallel command at `cbee59c`: 13 suites, 0 failed (wall 122.6 s, information); publication gate and private-path grep clean.

- **2026-11-11: Owner decision OA-20, approved (verbatim).** It approves the E-01.3.3 package of [the proposal](E-01.3.3-plan-amendment-proposal.md), sections 3 to 6. Verbatim:

  > Owner decision — OA-20 APPROVED.
  >
  > Approve the exact E-01.3.3 package in:
  >
  > evidence/E-01.3.3-plan-amendment-proposal.md
  >
  > This approval covers:
  >
  > 1. The revised E-01.3.3 plan wording and proof
  >    in section 3, including the fields and
  >    generated artifacts identified in section 4.
  >
  > 2. Amendment 1 to decision 0007 in section 5,
  >    preserving the original decision text and
  >    explicitly identifying superseded requirements.
  >
  > 3. The seven-file reconciliation patch in
  >    section 6, including the corrected credential
  >    classes, rotation owners and revocation triggers.
  >
  > Verify the exact proposed changes, patch integrity
  > and source preconditions before applying them.
  >
  > Apply through the existing integrity-controlled
  > process. Preserve the historical record and verify
  > that no contradictory current credential-lifecycle
  > requirements remain.
  >
  > The approved behavior is:
  >
  > - Standing Gitea bot credentials stay on the
  >   trusted host.
  > - The dispatcher borrows the stage's credential
  >   only for a confirmed attempt.
  > - Releasing that credential does not revoke it.
  > - Issuance, rotation and revocation remain
  >   administrator-managed.
  > - Attempt-scoped inference credentials are revoked
  >   when their attempt ends.
  > - No standing bot credential enters the guest,
  >   agent environment, conversation or UI.
  > - During bootstrap, same-account access to
  >   host credentials remains disclosed, not
  >   represented as independently isolated.
  >
  > Do not introduce a separate dispatcher OS account
  > or another guest login under this approval.
  > That architectural decision remains deferred.
  >
  > Do not run the disposable-guest custody probe,
  > change live credentials, create new connections
  > or execute privileged effects under this approval.
  >
  > Continue the existing offline S-03.3 work without
  > interrupting its active Builder.
  >
  > Report the exact revisions, validation outcomes,
  > and the remaining live qualification obligations.
  >
  > Continue other eligible engineering work.

- **2026-11-11: OA-20 applied (integrity process).** Decision 0007 Amendment 1 (the section 5 text exactly, dated 2026-11-11) and a dated current-facts note on decision 0013 (the bootstrap reading of point 1; the dispatcher OS account deferred by the Owner): `2cdf664`, by the Overseer. Builder commits, each verified by the Overseer: plan `1ccdf02` (section 3's texts exactly; only the E-01.3.3 leaf and one appended amendments entry changed); the approved patch `ea4ff69` (sha256 `ae098ae8...`, byte-equal to Appendix A, 7 files); the sweep fix `911c433` (the dispatcher's realization row in `policy/role-tokens.json` still restated the superseded clause word for word); `6ae54a8` (`attempt_tokens.py`'s docstring cites the amended point 4; no code change); `1b65161` (the recorded test ids: the approved rename and addition, and the tests committed since the last recording). **Overseer ruling (no gate earned):** section 4's whole-file digests of `task_manifest.json` and the CSV were computed at `f8ba6ec`; the Owner-approved F-09 amendments `e6af9c9` and `6b9a6ec` changed other rows of both files since. The Overseer checked that the OA-20 line delta of both files is byte-identical at `f8ba6ec` and at the application revision, and ruled the package applied there with the re-based digests (prompt `991de667...` as stated; manifest `8b072387...`; CSV `bc59f0ea...`); the plan's amendments entry states this. Sweep: no current text contradicts the approved behavior; the superseded clauses remain only as history (decision 0007 points 4 and 5, `evidence/`, the plan's amendments entries). Validation: verify_seed PASS both modes; role-token, security-inventory, CI-policy and control-catalog checkers PASS; role-token tests 74 OK; dispatch 263 OK; full parallel suite 13/13, 2749 tests. Detected by the budget check, exposed by this work and introduced by S-03.3 slice 5 (`e3d3fe8`): `UNIT_NOT_ISOLATED` for `test_acp_qualification_driver.InnerConversationsScript` (a loopback server in a unit-category class); fixed forward in the next dispatch. Remaining live obligations of E-01.3.3: the disposable-guest custody probe (not authorized) and the dispatcher's live use of a standing credential.

- **2026-11-11: Owner decisions on OA-16 Act A, S-03.3 D-1, C-3 and G-01.1 (verbatim).**

  > Owner decisions — OA-16 Act A, S-03.3 D-1, C-3,
  > and G-01.1.
  >
  > 1. OA-16 ACT A — APPROVED
  >
  > Authorize exactly one execution of:
  >
  > task gitea:roles -- provision
  >
  > Create the restricted, non-site-administrator
  > aieh-bot-protection-audit identity and its token
  > scoped exactly read:repository.
  >
  > Store the token in the sixth Credential Manager
  > entry, AIEH Gitea bot protection-audit.
  >
  > Verify identity, scope, custody and fingerprint-only
  > reporting. Do not expose the token.
  >
  > Preserve all existing identities and credentials.
  > Stop on unexpected behavior; do not retry
  > automatically.
  >
  > Acts B, C, D and E remain unauthorized.
  > Present Act A's evidence before requesting Act B.
  >
  > 2. S-03.3 D-1 — OPTION A APPROVED
  >
  > Authorize one additional read-only inspection of
  > the existing staged, hash-verified OpenHands image
  > archive under the managed guest-state root.
  >
  > Inspect the bundled Claude Code adapter, SDK and
  > CLI as data to resolve the identified source-level
  > questions.
  >
  > Do not execute the CLI, install npm packages,
  > download dependencies, alter the image or
  > create a guest.
  >
  > Record the exact image identity, inspected files
  > and findings.
  >
  > 3. C-3 — OPTION 1 APPROVED
  >
  > Accept these ceilings for the dedicated CI guest:
  >
  > - 4 vCPU
  > - 6 GiB memory
  > - 20 GiB system disk
  > - 40 GiB working disk
  >
  > Choose one guest reused within a validation session,
  > with the disposable per-job containers, networks,
  > storage isolation, disabled caches and mandatory
  > guest-recreation conditions of decision 0016.
  >
  > Destroy the guest at the session's end.
  > Never reuse a compromised or unverified guest.
  >
  > Proceed with the offline runner and image pinning,
  > profile definition and validation.
  >
  > This decision does not authorize live runner
  > registration, Gitea Actions activation, guest
  > network changes, untrusted workloads or any other
  > OA-13 act.
  >
  > The registration-token reset must still be proven
  > effective before live registration.
  >
  > 4. G-01.1 — RECONCILE BEFORE ADMISSION
  >
  > I accept the catalog's overall structure, but
  > defer formal admission of revision 20b9e24.
  >
  > OA-20 changes the authoritative semantics of
  > standing Gitea bot credentials.
  >
  > After OA-20 is applied, reconcile SEC-EXEC-01
  > and any other affected control text. Ensure the
  > catalog describes host-held credentials used by
  > the dispatcher, not credentials handed to agents.
  >
  > Keep the other controls and the fail-closed
  > unsettled exception classes unchanged.
  >
  > Run the catalog checker, then present the exact
  > final revision and SHA-256 for sign-off.
  >
  > Do not admit an altered catalog under the old
  > approval digest.
  >
  > 5. EXECUTION ORDER
  >
  > Do not interrupt the active S-03.3 Builder or
  > introduce competing edits to its working tree.
  >
  > Carry out the approved independent operations
  > when safe, without delaying unrelated eligible
  > engineering work.
  >
  > Do not interpret these decisions as authorization
  > for additional live acts.
  >
  > Report completed operations, exact evidence and
  > the next Owner decision required.

- **2026-11-11: OA-16 Act A run once, FAILED at the credential write; stopped, not retried.** From a clean clone at `1c629ee`, Gitea healthy at 127.0.0.1:13300: `gitea_roles.py provision` exited 1 with `CREDENTIAL_WRITE_FAILED: CredWriteW('AIEH Gitea bot protection-audit') failed (1734)`; its exposure scan was clean and the Overseer's own scan found no token-shaped text. Cause (code reading): the entry's comment for the protection-audit role is 271 characters, over Windows' 256-character limit for a credential comment; the other roles' comments are 232. The offline fake provider enforces no Windows limit, so no test caught it (a test gap). Code-based inference: the account created, one token minted and lost, no entry written, the other four entries only read and checked.

- **2026-11-11: Owner approval of Act A recovery step (ii), one read-only inspection (verbatim).**

  > Owner decision — OA-16 Act A recovery, step (ii).
  >
  > APPROVED: One read-only inspection of the failed
  > provisioning operation's actual state.
  >
  > Use the harness's existing trusted Gitea
  > administration path and stored site-administrator
  > credential.
  >
  > Scope the inspection exclusively to:
  >
  > aieh-bot-protection-audit
  >
  > Establish and report:
  >
  > 1. Whether the account exists.
  > 2. Whether its actual account type is Bot and it is
  >    not a site administrator.
  > 3. Whether its restricted status can be verified
  >    through an authoritative read-only source.
  >    If not observable, report UNKNOWN.
  > 4. The names, identifiers and scopes of its existing
  >    access tokens, without reading or exposing values.
  > 5. Whether the sixth Credential Manager entry exists,
  >    without disclosing any secret content.
  >
  > Record the observed results and distinguish them
  > from the earlier code-based inferences.
  >
  > If the required inspection cannot be completed
  > without modifying state, stop and report why.
  >
  > Do not create accounts, mint tokens, rotate or
  > revoke credentials, change permissions, or modify
  > repository protection settings.
  >
  > No retry of provision is authorized.
  > No orphan-token deletion is authorized.
  > Acts B through E remain unauthorized.
  >
  > In parallel, prepare the offline fix already
  > identified:
  >
  > - Enforce Windows credential field limits before
  >   token issuance.
  > - Extend fake-provider tests to cover those limits.
  > - Include post-mint storage failure and bounded
  >   cleanup tests.
  > - Avoid introducing temporary credential entries
  >   or other persistent side effects merely to
  >   perform a preflight.
  > - Never treat prevalidation as a guarantee that
  >   credential storage cannot fail.
  >
  > Do not interrupt the active S-03.3 Builder or
  > introduce competing working-tree edits.
  >
  > Once the read-only inspection completes, present
  > the exact orphan token identifiers proposed for
  > deletion as recovery step (iii).
  >
  > Do not perform steps (iii) or (iv) without their
  > subsequent Owner approvals.
  >
  > Continue unrelated eligible engineering work.

- **2026-11-12: Act A recovery step (ii) performed once (00:10:28 UTC), read-only.** Through the product's own modules from the clean clone: `gitea admin user list` and, as the site administrator by its harness-held password in memory, `GET /api/v1/user`, `GET /api/v1/users/aieh-bot-protection-audit` and its token list. **Observed** (each inference confirmed): the account exists, ID 8, type Bot (the user list's Type column), not an administrator, `restricted: true` (the admin API), active, never signed in; exactly one token, ID 14, `aieh-protection-audit-20261111T222233Z`, scope exactly `read:repository`; no entry `AIEH Gitea bot protection-audit` (read by its exact name; nothing enumerated). The list's last-eight field was dropped in memory, never printed or recorded; no token-shaped text in the output. Script sha256 `7f4de14d...`, output `00e12659...` (session scratch).

- **2026-11-12: Owner authorization of Act A recovery step (iii), deletion of token 14 (verbatim).**

  > Owner authorization — OA-16 Act A recovery, step (iii).
  >
  > APPROVED: Delete exactly one orphaned Gitea access
  > token created by the failed Act A provisioning.
  >
  > Target:
  > - Account: aieh-bot-protection-audit
  > - Gitea user ID: 8
  > - Token ID: 14
  > - Token name: aieh-protection-audit-20261111T222233Z
  > - Token scope: exactly read:repository
  >
  > Use the existing trusted Gitea administration path
  > and the site administrator's harness-held credential.
  >
  > Before deletion, independently confirm that:
  > 1. The account still has user ID 8 and is a
  >    restricted, non-site-administrator Bot.
  > 2. Token ID 14 belongs to that account.
  > 3. Its name and scope exactly match those above.
  > 4. No unexpected additional token exists on that
  >    account.
  >
  > If any prerequisite differs, stop without deleting.
  >
  > Delete only token ID 14. Do not delete or modify the
  > account, another token, another credential entry,
  > repository permissions, or protection settings.
  >
  > After deletion:
  > - Read back the account's token list.
  > - Verify that it contains zero tokens.
  > - Verify that the account remains unchanged.
  > - Report the observed result without token values
  >   or token suffixes.
  > - Record the recovery operation and its evidence.
  >
  > If the deletion succeeds but verification fails,
  > record the outcome as UNKNOWN and stop. Do not
  > automatically retry the deletion.
  >
  > Step (iv), reprovisioning, is NOT authorized yet.
  > Acts B through E remain unauthorized.
  >
  > Complete the offline credential-storage correction
  > and its regression tests before presenting step (iv).
  >
  > Preserve the existing sequencing with the active
  > Builders. Continue unrelated eligible work.

- **2026-11-12: Act A recovery step (iii) performed once (00:16:15 UTC): PASS.** Prechecks from two sources, all true: the user list's row (ID 8, Bot, not an administrator) and the admin API (ID 8, type Bot, restricted, not an administrator); token 14 on that account with the exact name and scope; exactly one token. One `DELETE /api/v1/users/aieh-bot-protection-audit/tokens/14` as the site administrator answered 204. Read-back: zero tokens; the account's twelve recorded fields identical before and after. No other account, token, entry, permission or protection setting touched; no token value or suffix recorded. Script sha256 `44cd7507...`, output `ed4d486e...` (session scratch). Step (iv) waits on the storage fix and the Owner.

- **2026-11-12: G-01.1 reconciled with OA-20, for sign-off.** `808b5bd`: SEC-EXEC-01 alone changed (its purpose, subject scope, events, the execution point's mechanism, and decision 0015 added to its sources); it now describes host-held standing credentials used by the dispatcher, administrator-managed lifecycle on defined triggers, the attempt-scoped inference token revoked at attempt end and the disclosed same-account limitation. Every other control, the deferred controls, the exception classes (the five unsettled ones failing closed) and the admission block are equal to `20b9e24` (JSON-level comparison, checked by the Overseer). Checker PASS; its tests 13 OK. `policy/control-catalog.json` blob `648fa27d6b44fc40648053ce4376cd792f9c12e0`, sha256 `67aef72a1fd2486199abb00e0b965bbbc2371a5abbcc726289505108907ee042`; admission stays proposed.

- **2026-11-12: Owner decision, G-01.1 catalog admission approved, with a test-execution clarification (verbatim).** The approved source revision is `808b5bd76d09` with `policy/control-catalog.json` at sha256 `67aef72a1fd2486199abb00e0b965bbbc2371a5abbcc726289505108907ee042`; the admission metadata is applied in a later commit, recorded separately below. Verbatim:

  > Owner decision — G-01.1 catalog admission.
  >
  > APPROVED: Admit the governance control catalog
  > at commit 808b5bd76d09.
  >
  > File:
  > policy/control-catalog.json
  >
  > Approved SHA-256:
  > 67aef72a1fd2486199abb00e0b965bbbc2371a5abbcc726289505108907ee042
  >
  > I approve the eight control definitions, including
  > SEC-EXEC-01 as reconciled with OA-20.
  >
  > The existing five unsettled exception classes
  > remain fail-closed until G-06.3.1.
  >
  > Record this Owner approval verbatim in the bootstrap
  > log and apply the catalog admission through the
  > established policy process.
  >
  > Do not change control definitions, expand authority,
  > or treat catalog admission as proof of enforcement.
  > That qualification remains G-01.2.
  >
  > After updating admission metadata, record the new
  > committed revision and digest separately from the
  > approved source revision.
  >
  > TEST EXECUTION CLARIFICATION
  >
  > Keep the behavioral and test-isolation checks in
  > tools/check_test_budget.py.
  >
  > The current socket-using unit test is a legitimate
  > category violation. Correct its classification or
  > test design without weakening the assertions.
  >
  > However, check_test_budget.py check --run executes
  > a complete serial test profile.
  >
  > Do not repeatedly run that serial profile simply
  > because an ordinary change added tests or because
  > the parallel test suite's runtime changed.
  >
  > During development, use focused affected tests and
  > the relevant category/isolation checks. Run the
  > complete test profile at appropriate acceptance
  > boundaries when its evidence is actually needed.
  >
  > Maintain independent test categories, unit isolation,
  > removed-test detection and meaningful failure gates.
  >
  > Do not reintroduce time budgets, repeat benchmarking
  > on unchanged revisions, or create a new performance
  > optimization workstream.
  >
  > Continue the active credential-storage Builder
  > without interruption.
  >
  > OA-16 step (iv), the guest custody probe, and all
  > other live acts remain separately authorized gates.
  >
  > Continue eligible engineering work.

- **2026-11-12: OA-16 Act A storage fix built offline and verified (fix forward).** `fa37c02`: the Windows credential field limits (wincred.h: Comment 256 characters, `CRED_MAX_STRING_LENGTH`; UserName 513; TargetName 32767; blob 2560 bytes) are checked by `CredentialStore.write` before `CredWriteW` (`CREDENTIAL_FIELD_LIMIT`, nothing written) and by a pure check `gitea_roles.py` calls for every requested role before any Gitea change (`provision`: before account creation and minting; `rotate`: before revoking); every role's comment is now at most 240 characters (protection-audit 223); the fake providers enforce the same limits; a store that fails after a mint makes the new token revoke itself once (`DELETE /api/v1/token`, then 401), no retry, failing as `TOKEN_STORE_FAILED`, or as `TOKEN_ORPHANED` naming the token for an administrator when the revocation is not confirmed; no temporary entry; passing the check is not treated as a guarantee. `61b8575`: `InnerConversationsScript` declared `integration` (introduced by `e3d3fe8`; test unchanged). **Overseer verification:** the diff read; credentials 60 OK (1 skipped), gitea 210 OK (13 skipped), the driver tests OK; verify_seed PASS; the Builder's full parallel suite 13/13 and one serial profile check at this acceptance boundary PASS (no `UNIT_NOT_ISOLATED`, no removed test, no new skip). Not verified: the 256/257 boundary on the real Credential Manager; whether a `read:repository` token may revoke itself live (if not, the outcome is `TOKEN_ORPHANED`, reported, fail-safe); an interrupt (`BaseException`) between mint and store is not cleaned up. In `rotate`, a store failure leaves both tokens revoked and the role without a working credential until a rerun (fails closed).

- **2026-11-12: G-01.1 catalog admitted (admission metadata applied).** Approved source revision: `808b5bd76d09` (`policy/control-catalog.json` sha256 `67aef72a1fd2486199abb00e0b965bbbc2371a5abbcc726289505108907ee042`, blob `648fa27d`). Admitted committed revision: `fb602b24fca76ec49e5a9022e032e0093cc1abaf`, where `policy/control-catalog.json` has blob `7af4a61b1e9ef860325bf3405b4e50f0018cce85` and sha256 `0aff0990cf2b05a950a3e8010ae160607f383ecb7462c8d0d6de66f65a4001f8`. The JSON differs from the approved revision only in `admission` (`status` proposed to admitted; `approval` citing the Owner's line "APPROVED: Admit the governance control catalog" in this log), checked at JSON level by the Overseer; no control definition, deferred control, exception class or authority changed; the five unsettled exception classes stay fail-closed until G-06.3.1. The page's status prose follows; the catalog tests now build the admission state each case tests (the committed-catalog test asserts the admitted state and that its quote is in this log; no assertion removed). Checker PASS ("admission admitted"); its tests OK; full parallel suite 13/13; verify_seed PASS. Admission is not proof of enforcement: that qualification remains G-01.2. The second admission act, the move into the protected policy repository, has no decided mechanism.

- **2026-11-12: Owner authorization of Act A recovery step (iv), one provisioning re-run (verbatim).**

  > Owner authorization — OA-16 Act A recovery,
  > step (iv).
  >
  > APPROVED: Execute exactly one provisioning re-run.
  >
  > Command:
  > task gitea:roles -- provision
  >
  > Use a clean checkout at commit:
  > 63f836e311bba088e3177ccda0dbddca7ffe244c
  >
  > This authorization is limited to completing the
  > previously failed creation of the protection
  > auditor's credential.
  >
  > Required preconditions:
  >
  > 1. Confirm aieh-bot-protection-audit remains an
  >    existing restricted, non-site-administrator Bot.
  >
  > 2. Confirm its access-token list is empty following
  >    the approved orphan-token deletion.
  >
  > 3. Confirm the sixth Credential Manager entry,
  >    AIEH Gitea bot protection-audit, is absent.
  >
  > 4. Confirm the other four Bot credentials remain
  >    present and valid.
  >
  > 5. Confirm the corrected credential-field preflight
  >    and post-mint cleanup code is present at the
  >    approved revision.
  >
  > If any precondition differs, stop without minting.
  >
  > Authorized effects:
  >
  > - Mint exactly one token for
  >   aieh-bot-protection-audit.
  > - Scope it exactly read:repository.
  > - Store it in the sixth Credential Manager entry.
  > - Read back and verify its identity and scopes.
  > - Read and verify the four existing credentials
  >   without modifying them.
  >
  > No account creation, credential rotation, or changes
  > to existing roles or permissions are authorized.
  >
  > If credential storage fails:
  >
  > - Permit the implementation's single bounded
  >   self-revocation attempt for the newly minted token.
  > - Do not retry the mint or storage operation.
  > - If revocation is unconfirmed, record the orphan
  >   identity and stop for separate recovery approval.
  >
  > After execution:
  >
  > - Report the account identity and token scope.
  > - Confirm the sixth entry exists and is readable
  >   through the credential provider.
  > - Report fingerprints only, never token values.
  > - Verify the four existing entries were unchanged.
  > - Run the credential-exposure scan.
  > - Record the observed result and exact evidence.
  >
  > This approval covers one execution only.
  >
  > OA-16 Acts B through E remain unauthorized.
  > The E-01.3.3 guest custody probe remains unauthorized.
  > No additional live operation is implied.
  >
  > Do not interrupt the active D-1 Builder or create
  > competing changes to its working tree.
  >
  > Once Act A is verified successful, present the
  > prepared exact scope of Act B for my decision.
  >
  > Continue unrelated eligible engineering work.

- **2026-11-12: Act A step (iv) performed once: PASS; OA-16 Act A complete.** From a clean clone at `63f836e311bba088e3177ccda0dbddca7ffe244c` (the fix present). Preconditions (read-only, 01:00:55 UTC), all met: the account ID 8, Bot, restricted, not an administrator (user list and admin API); its token list empty; no entry `AIEH Gitea bot protection-audit`; the four other bot entries present and accepted by Gitea with their scopes; `check_entry` before any Gitea call and `store_minted` after the mint in `provision`, every role's entry within the limits. The run (`gitea_roles.py provision`, the command `task gitea:roles -- provision` wraps; 01:01:08 UTC; exit 0): `created_accounts` empty; one token minted, ID 15, `aieh-protection-audit-20261112T010109Z`, scope exactly `read:repository`, fingerprint `sha256:a4109cc864373ed5`, stored in the sixth entry; the other four `minted: false`; its I7 scan clean. Read-back (01:01:19 UTC): the account unchanged; exactly one token; the entry present, readable through the credential provider and accepted by Gitea as `read:repository` with the same name; the four other entries' fingerprints and checks identical before and after (planner `4d6ca761...`, builder `2edcc707...`, reviewer `89283518...`, verifier `2ccc9194...`). No token-shaped text in any output (the Overseer's scan). Evidence (session scratch): `check.py` `55fe172d...`, `pre.json` `40d3db4d...`, `provision.out` `52626129...`, `post.json` `4b11a2dd...`. Act B was presented the same day; Acts B to E unauthorized.

- **2026-11-12: S-03.3 D-1 and F-8, the one Owner-approved source read of the staged image.** [Record](S-03.3-D-1-image-source-read.md). `2cfa23a`: `image-inspect` gains a bounded read-only text mode (listing, excerpts, searches, string constants, every count capped) and, because the agent server is a PyInstaller executable without `.py` source, a reader of its PYZ modules as data (its own table-of-contents and marshal walker; `marshal.loads` never called, nothing loaded as code); the earlier behaviour and its tests unchanged. `c05b946`: the record, its argument list written before the run. One run, 2026-11-12 01:06:54 to 01:07:15 UTC, `inspected`, every layer re-hashed against the lock; the same image identity as the first read. Findings: an ACP session fork starts a new CLI process under the adapter (the slice plan's 2.4 (b) differs); sub-agent output arrives on the parent CLI's stream, the sub-agent model `CLAUDE_CODE_SUBAGENT_MODEL` else the tool's, the agent's or the main model; an experimental agent-teams switch exists; the CLI reads `ANTHROPIC_BASE_URL`; the secondary model is read from `ANTHROPIC_SMALL_FAST_MODEL` or `ANTHROPIC_DEFAULT_HAIKU_MODEL` (the code names `claude-haiku-4-5`; not a model approval; how the default is derived unanswered); non-inference traffic has documented switches, but event logging and the WebFetch domain check go to a fixed Anthropic host that does not follow the base URL (refused in the guest, not switched off). F-8: six of seven assumptions confirmed; the turn-end status set differs (the SDK's terminal set is finished, error, stuck; the driver's adds paused and waiting_for_confirmation). **Overseer verification:** the new code's loading path read (no code loading); image-inspect tests 46 and the existing ones OK; the Builder's tools suite 1428 OK; verify_seed PASS; no machine path in the record. **Overseer ruling (no gate earned):** reading the agent server's PYZ modules as data is within the approved read ("Inspect ... as data"; nothing executed). Carried to the next S-03.3 slice: `ACP_ASSUMED['status']` and the driver's turn-end set, and the 429 note. Unanswered items (section 8) need a further Owner-approved read; none requested now.

- **2026-11-12: Owner authorization of OA-16 Act B (verbatim).**

  > Owner authorization — OA-16 Act B.
  >
  > APPROVED: Apply and verify the declared protection
  > fixture for exactly one repository:
  >
  > aieh-authz-fixture/authz
  >
  > This authorization covers one execution of:
  >
  > task gitea:roles -- fixture
  >
  > followed by one read-only verification:
  >
  > task gitea:protection-check -- verify
  > aieh-authz-fixture/authz
  >
  > PRECONDITIONS
  >
  > Before making changes:
  >
  > 1. Confirm the organization and repository already
  >    exist. Creating either is NOT authorized.
  >
  > 2. Read and record the current repository settings,
  >    complete collaborator roster, and complete branch
  >    protection rule set.
  >
  > 3. Compare the actual state against the committed
  >    declaration and the specific changes described
  >    in the Act B proposal.
  >
  > 4. If unexpected collaborators, protection rules,
  >    repository state, or security-relevant drift
  >    exists, stop and present the difference before
  >    making any changes.
  >
  > 5. Confirm the protection auditor still has exactly
  >    one valid read:repository token, held in its
  >    designated Credential Manager entry.
  >
  > AUTHORIZED CHANGES
  >
  > Apply the committed declaration using the existing
  > trusted Gitea administration path.
  >
  > Repository settings:
  > - Private, not archived, default branch main.
  > - Merge commits only.
  > - Rebase, squash, fast-forward-only and manual
  >   merging disabled.
  >
  > Collaborators:
  > - protection-audit: repository admin
  > - planner: write
  > - builder: write
  > - reviewer: read
  > - verifier: read
  > - aieh-owner: write
  >
  > Branch protection:
  > - main: no push or force-push; only aieh-owner
  >   merges; one approved reviewer required;
  >   rejected reviews and outdated branches block;
  >   administrator merge override blocked.
  > - work/*: push restricted to planner and builder.
  > - **: all other branch pushes prohibited.
  >
  > Apply all 34 fields per rule exactly as declared,
  > including disabled and empty bypass allowlists.
  >
  > No additional repository, identity, credential,
  > permission or protection changes are authorized.
  >
  > POSTCONDITIONS
  >
  > 1. Read back every repository setting, collaborator
  >    permission and protection rule.
  >
  > 2. Compare the observed state against the complete
  >    declaration, not merely the fields that changed.
  >
  > 3. Confirm the site administrator holds no token.
  >
  > 4. Run the auditor's read-only protection verifier
  >    once against the named repository.
  >
  > 5. Require a verified verdict and record its
  >    baseline digest.
  >
  > 6. Record the before/after differences, operations,
  >    exact revision, verification results and
  >    credential-exposure scan.
  >
  > If any operation fails or the resulting state is
  > unexpected, stop without retrying. Preserve the
  > observed partial state and report it for
  > reconciliation; do not perform unapproved repairs.
  >
  > AUTHORIZATION BOUNDARIES
  >
  > - No account or token creation or rotation.
  > - No change to any other repository.
  > - No escape-probe creation or negative testing.
  > - No deliberate protection drift.
  > - No protected merge.
  > - No authorization of Acts C, D or E.
  >
  > This is one execution of Act B only.
  >
  > Do not interrupt the active D-1 Builder. Preserve
  > working-tree isolation and record the outcome in
  > the bootstrap log when safe.
  >
  > Once Act B passes, present Act C's exact scope for
  > the next Owner decision.
  >
  > Continue unrelated eligible engineering work.

- **2026-11-12: OA-16 Act B performed once: PASS (`verified`).** From a clean clone at `399b68c16ab3010acc4a7ed3bcd6da3173c441b4`. Preconditions (read-only as the site administrator, 01:21:40 UTC): the organization and `aieh-authz-fixture/authz` exist; private, not archived, default branch `main`, no deploy key, the Owners team only; the complete roster planner and builder write, reviewer and verifier read, `aieh-owner` write and no one else; the rules `main`, `work/*` and `**`; the differences from the declaration exactly those the Act B proposal named (rebase, rebase-explicit, squash and fast-forward-only merges on; the auditor without access; `main` `block_on_outdated_branch` false); the auditor's one token, ID 15, `read:repository`, in its entry (`sha256:a4109cc864373ed5`) and accepted; the administrator without token. **Process deviation (Overseer):** the Overseer's precondition script first stopped on the `work/*` push list read as `[builder, planner]` against the declared `[planner, builder]`; Gitea holds that list as a set and the product's verifier compares it sorted, so the script's comparison was corrected to the verifier's and the recorded state re-evaluated offline, with no further read, before any change. The run (`gitea_roles.py fixture`, the command `task gitea:roles -- fixture` wraps; 01:22:10 UTC; exit 0): one settings PATCH, six collaborator PUTs, three rule PATCHes, each 2xx, on `authz` only; no rule created; the administrator held no token afterwards; its I7 scan clean. Read-back (01:22:19 UTC) against the whole declaration: 11 settings, the six collaborators and their permissions (the auditor admin), the Owners team, no deploy key, 3 rules x 34 fields: no difference; the auditor's token unchanged. Verification (`protection_check.py verify aieh-authz-fixture/authz`, 01:22:20 UTC, exit 0): `verified`, baseline digest `sha256:5dd7ace780ca0878146915ed74e8761b432e4489f20cdfe9a243804ad5aa6e42`; its I7 scan clean; no token-shaped text in any output (the Overseer's scan; the one 40-hex hit was inside that 64-hex digest). Gitea 28.3.0 records no audit event for these API changes. Evidence (session scratch): `state.py` `f75b25dd...`, `pre.json` `b6c22b18...`, `fixture.out` `ea4f1769...`, `post.json` `1c006cbf...`, `verify.out` `205f5380...`. Act C presented the same day; Acts C to E unauthorized.

- **2026-11-12: S-03.3 slice 6, the guest-root vantage (F-6) and the turn's end (F-8), offline.** [Record](S-03.3-slice6-root-vantage.md). `aa6a3a7`: the root facts reporter (`profiles/seed/user-data.tmpl`, `aieh-provision conversation-facts`) gains one key, `containment`: per owner-labelled running container exactly slice 1's `collect host --pid` snapshot, by verbatim copies of slice 1's readers (a test holds them equal), one `/proc` scan, capped (16 containers, 1024 members, 64 outside children), no command, no environment, of the arguments only the program name and one path; its only input still the request file's existence; the driver's default vantage reads it as `agent` into slice 1's unchanged `host_verdict`; every gap UNKNOWN, never PASS (an existing guest's reporter has no section). Digests: the seed template `92deb03f...` to `f8e3b163...` (pinned by both profiles), the QEMU profile `0eb5fc0a...` to `f0ef1ca4...`, the Incus profile `ab65af02...` to `fbcbf11a...`; four seed digests in `test_nocloud_seed.py` re-pinned; a live approved-input manifest listing the old profile digest would refuse it until re-approved (not read: protected). `5a4e270`: the turn ends on the image's status enum: `finished` PASS; `error`, `stuck`, `paused`, `deleting` and any value outside the enum FAIL; `waiting_for_confirmation` FAIL and a stop; the wait continues only on `idle`, `running` or no value; `ACP_ASSUMED` cites the D-1 record; a 429 stays FAIL (no retry; disclosed). `8bd4e62`: the record. **Overseer verification:** the reporter diff read (no environment, no command; the argument summary as slice 1's); `test_provision`, the driver tests, `test_nocloud_seed`, `test_check_profile` and the dispatch suite OK; `check_profile` PASS; verify_seed PASS; the Builder's full parallel suite 13/13. Not verified: anything on a guest kernel (the reporter's root reads of uid 999 processes, the status fields, the report's size). The live run needs a guest created at or after `aa6a3a7`.

- **2026-11-12: Q-02.2.1 under C-3, the runner pinned and the job image chosen.** [Record](Q-02.2.1-c3-pins.md). `3e128cf`: the CI runner (act_runner, renamed upstream `gitea.com/gitea/runner`, binary `gitea-runner`) pinned at v6.0.0, commit `b5305c67...`, Linux amd64 binary sha256 `62ecab22...` (three records agree; the checksum file's OpenPGP signature not verified), MIT, compatible with Gitea 28.3.0 by its floor (1.26.2) and the six `/api/actions` methods; decision 0016's A1 facts answered from its source with citations. Endpoints: gitea.com, its storage redirect, dl.gitea.com, and three registries, all unauthenticated and read-only. **Overseer verification:** the lock diff read; the resolver's checks on the new entries, verify_seed both modes, `check_ci_policy`, `check_profile` and `test_resolve_sources` PASS. **Overseer rulings (no gate earned; each within C-3's "Proceed with the offline runner and image pinning"):** (1) the job image is `docker.io/library/python:3.12-trixie` (index `sha256:cad37dd2...`, linux/amd64 manifest `sha256:97dc788c...`, image id `sha256:37662cc6...`): an official, maintained upstream image with git and the CPython minor the tools lock targets, the CI guest's own Debian 13, without the Docker CLI or sudo; it runs under a numeric non-root `--user` with the decision 0016 container options; (2) v6.0.0 was released one day before the pin: it stands for the offline definition, and the pin is re-evaluated before any live registration (C-2); (3) the builder's six findings go to the profile-definition slice: the exchange mount, declared in `container.options` and silently dropped at v6.0.0 while `valid_volumes` is empty, moves to the runner's `container.volumes` read-only if its source confirms that path keeps `:ro` and leaves workflows unable to add mounts (the intent of decision 0016 kept), otherwise it returns to the Overseer; the IPv6 key follows its new name; the unpinned keys and runner environment are declared; the runner's own job-summary post stays denied and is disclosed; the registration token enters by file only; the job's Python tools set without network is designed there.

- **2026-11-12: Owner authorization of OA-16 Act C, conditional (verbatim).**

  > Owner authorization — OA-16 Act C.
  >
  > CONDITIONALLY APPROVED.
  >
  > Authorize the escape-probe repository and live
  > negative qualification of the protection auditor,
  > subject to the safety corrections below.
  >
  > TARGETS
  >
  > Authorization fixture:
  > aieh-authz-fixture/authz
  >
  > Escape-test repository:
  > aieh-authz-fixture/escape-probe
  >
  > Required protection baseline:
  > sha256:5dd7ace780ca0878146915ed74e8761b432e4489f20cdfe9a243804ad5aa6e42
  >
  > PRECONDITIONS
  >
  > Before executing live negative tests:
  >
  > 1. Confirm the Act B protection verifier still
  >    returns verified with the approved digest.
  >
  > 2. Confirm the auditor's token remains scoped
  >    exactly read:repository and its credential
  >    remains unchanged.
  >
  > 3. Review the live negative tests for write probes
  >    that could mutate state if unexpectedly accepted.
  >
  > 4. Correct any claim that all proposed write probes
  >    are inherently harmless.
  >
  > 5. Make security failures terminate further
  >    write probes immediately. Do not rely on
  >    unittest subTest or ordinary failure reporting
  >    to stop a potentially dangerous sequence.
  >
  > 6. Ensure repository-creation and other negative
  >    probes cannot create unintended durable objects.
  >    If a probe cannot be made safely non-mutating on
  >    unexpected acceptance, leave that probe
  >    unexercised and report the qualification gap.
  >    Do not silently count it as passing.
  >
  > These test-harness corrections are authorized.
  > Keep them focused, tested, and separate from the
  > active D-1 Builder's working tree.
  >
  > AUTHORIZED LIVE EXECUTION
  >
  > A. Execute once:
  >
  > task gitea:roles -- escape-probe
  >
  > Create only aieh-authz-fixture/escape-probe if absent.
  >
  > Require it to be private, empty and without
  > collaborators. If it exists in another state,
  > stop without changing it.
  >
  > B. Execute the corrected live negative suite once.
  >
  > Confirm:
  > - Auditor identity and exact read:repository scope.
  > - Authorized reads succeed.
  > - All exercised unauthorized writes are refused
  >   specifically by scope.
  > - No unauthorized repository access.
  > - No administrator or sudo capability.
  > - No unintended changes to protected state.
  >
  > C. Execute once each:
  >
  > task gitea:authz
  > task gitea:transport
  >
  > Their existing authorized planner/builder test
  > commits on the fixture's proposal branches are
  > permitted. No protected merge is authorized.
  >
  > D. Verify the protection baseline again.
  >
  > Require:
  > - verified
  > - exactly the same baseline digest
  > - no unexpected credentials or permissions
  > - clean credential-exposure scan
  >
  > FAILURE HANDLING
  >
  > Any unexpected successful auditor write is a
  > SECURITY FAILURE.
  >
  > Stop immediately, preserve the observed state and
  > report the exact operation and effects.
  >
  > Do not automatically revoke credentials, retry
  > tests, clean up unexpected state, or repair
  > protection rules.
  >
  > Present any required recovery act separately.
  >
  > BOUNDARIES
  >
  > This approval does not authorize:
  > - OA-16 Act D or E.
  > - Deliberate protection drift.
  > - Protected merges.
  > - Changes to other repositories.
  > - Credential issuance, rotation or revocation.
  > - Broader Gitea administration.
  >
  > Record Act C's exact outcomes, including any
  > unexercised probes, and present Act D's scope
  > only after Act C's applicable proof is satisfied.
  >
  > Continue unrelated eligible engineering work.

- **2026-11-12: Act C precondition review (Overseer, read-only) of `test_protection_audit_live.py`, phase `negative`.** Harmless if wrongly accepted: the declared-value PATCHes and PUTs, deletions of absent objects, the empty priorities POST, the invalid-body deploy key, deploy token and webhook, the merge of an absent pull request. Would create a durable object if wrongly accepted: the API file write on `main` (if the branch rule also failed), both repository creations, both git pushes, and the token creation with the token as a password (today revoked after the fact). The Overseer's Act C presentation had said every body was chosen so that a wrong acceptance changes nothing: corrected here. A `SecurityFailure` raised inside `subTest` is recorded and the loop continues to the next write; the before/after snapshot does not see new repositories, branches, keys, hooks or tokens. The harness correction is dispatched next; no live step has run.

- **2026-11-12: OA-16 Act C test-harness corrections (the Owner's preconditions 3 to 6), verified.** `fe7d9e3` and `7995a75` (`test_protection_audit_live.py`, negative phase): a module-level breaker, checked before every write and independent of `subTest`, that the first security failure trips (no later write of any class is sent; `tearDownModule` fails the run and the report names the probe and every write not sent); every write probe harmless or made non-mutating on wrong acceptance (the file write to an absent, invalid branch; repository and token creation with bodies that fail validation; the pushes are a non-fast-forward without `+` and the deletion of an absent ref, which the repository module withholds after the receive-pack advertisement); a served advertisement is a security failure (the Overseer's ruling); a wider snapshot; the docstring corrected; none unexercised. `501dce1` (`gitea:authz`, `gitea:transport`): the same for the auditor's rows (fixture writes addressed to an absent repository, invalid bodies, `--dry-run` pushes the client withholds), a breaker over every role (`live_breaker.py`), the other roles' 219 and 48 requests byte-equal to `7995a75`'s; two auditor probes UNEXERCISED and reported as failing subtests by the convention (`POST /admin/actions/runners/registration-token`: no body, an acceptance would create the instance's registration token; the web sign-in form: an acceptance would open a session), both covered by the negative phase's scope and password probes. **Overseer verification:** the breaker wiring read; gitea suite 257 OK (13 skipped); verify_seed PASS. Process note: one Builder's recursive search read `decisions/` and this log (read only, public, nothing changed); the Overseer's brief had overstated them as untouchable and now names them read-only.

- **2026-11-12: OA-16 Act C performed: PASS.** From a clean clone at `7995a75` (steps A, B) and `501dce1` (step C). Preconditions (02:18 to 02:19 UTC): `verify` `verified` with the Act B baseline `sha256:5dd7ace780ca0878146915ed74e8761b432e4489f20cdfe9a243804ad5aa6e42`; the auditor's token ID 15, `read:repository`, fingerprint `sha256:a4109cc864373ed5`, accepted; the site administrator's read-only snapshot of every user, every user's token list (names and ids), the organization's repositories and the fixture's branches, tags, webhooks, deploy keys, collaborators and open pull requests. **A** (`escape-probe`, 02:19:14 UTC, once): `created` by one POST (201), private, empty, no collaborators; the administrator without token. **B** (negative phase, 02:19:28 UTC, once): 8 tests OK; `GET /token` shows the login and exactly `read:repository`; random and empty passwords 401; the token as a password refused by scope; rules and repository read as an administrator, the verifier bot 403 on the rules (control); all 15 HTTP write probes 403 with Gitea's scope message; both git pushes `PUSH_REFUSED` (HTTP 403 at the advertisement); `/repos/search` the fixture only; user, organization and admin routes 403 by scope; `sudo` refused; the escape-probe's rules 404; breaker not tripped; none unexercised. **C** (`gitea:authz` once, 02:2x UTC, the command its target wraps, system Python as the target uses; `gitea:transport` once, tools interpreter): authz 16 OK, 1 skipped (executor, carried to G-04.2.1), and exactly the two by-design UNEXERCISED auditor subtests failing; every auditor write 403 by scope or refused at the advertisement; transport 2 OK, the auditor's five pushes 403; breakers not tripped; builder's and planner's proposal branches advanced by their permitted commits, their PRs closed again. **D** (02:5x UTC): `verified` with exactly the baseline digest; the final snapshot differs from the one after A only in `work/authz-builder` and `work/authz-planner` (permitted), with `main`, every token list, the collaborators, hooks, keys and repositories unchanged and no open pull request. Exposure: each tool's own scan clean, and the Overseer's exact-value scan of every output against the five role tokens held in memory found 0. Evidence (session scratch, sha256): `snap.py` `bf7ec616...`, `snap0.json` `247a66d4...`, `snap1.json` `5feb9a35...`, `snap2.json` `87059ee3...`, `a.out` `a40bdc0e...`, `b-report.json` `ef72d1a0...`, `c1-report.json` `af69721b...`, `c2-report.json` `e1c9296d...`, `d-verify.out` `205f5380...`. Gitea 28.3.0 records no audit event for these API calls. Acts D and E unauthorized.

- **2026-11-12: Q-02.2.1 CI profile slice, stopped at three boundaries; the Overseer's rulings.** [Record](Q-02.2.1-ci-profile.md). `5517399`: the job image pinned in the component lock (index, linux/amd64 manifest, image id). `32277b9`, `fa2c0f4`: `policy/ci-runner-profile.json` records C-3 (ceilings decided; lifetime shared, runner persistent, no `--ephemeral`, deleted at destroy) and the runner's 6.0.0 keys: the IPv6 rule on `container.network_create_options.enable_ipv6`, `bind_workdir`, `sweep`, `tool_cache_mode`, hooks, `post_task_script`, `extra_headers`, metrics and health check pinned off or empty, no `$` in a variant's config, the runner service's environment refused for the label, token, proxy, Docker host, hook and telemetry names, the registration token by `--token-file` under `/run/` only with `--config` and no `--labels`; the job-summary post disclosed; `check_ci_policy` checks each (81 tests, 33 of 33 mutants killed). `25a074d`: the record. **Overseer verification:** the policy diff read; `check_ci_policy`, `check_profile`, `check_role_tokens`, `check_network_matrix`, `check_security_inventory` and verify_seed PASS; the Builder's full parallel suite 13/13. **Overseer rulings (no gate earned; each keeps decision 0016's stated rules):** (A) the exchange is declared in the runner's `container.volumes`, read-only, exactly, with `valid_volumes: []` kept: at 6.0.0 a source in `container.volumes` is also admitted, read-only, as a workflow volume source, so a workflow could re-mount the same read-only exchange at another target; no other host path and no write become reachable, which keeps T7 and T9; disclosed, and the checker holds `container.volumes` to exactly the declared read-only sources; (B) one anonymous, read-only registry read of the pinned linux/amd64 manifest is authorized for the layer list the provision lock needs; (C) the label names the image by its id, `aieh-validation:docker://sha256:<config digest>`, as decision 0006 item 3 loads images (the id equals the locked config digest), because a `docker load`ed image may carry no repository digest in Moby's classic store and a digest reference would then be pulled, which decision 0016 T9 forbids; the LABEL rule follows; observed at Q-02.2.2; (D) the job's Python tools set is the staged, hash-locked Linux cp312 wheels mounted read-only and installed per job with `--no-index --require-hashes --only-binary=:all:` into a job-local venv (design A): the pinned image stays unchanged and nothing persists across jobs.

- **2026-11-12: Q-02.2.1, the CI profile variant declared offline under rulings A to D.** [Record](Q-02.2.1-ci-variant.md). `e6f3987`: `runner_config.volumes` exactly the read-only exchange and wheel binds, `valid_volumes` empty, mount options refused, the label by image id equal to the lock's config digest. `0f60655`: the token policy's A1 facts verified at the runner source (checked against the lock), disclosures ci-d10 (the job-summary post) and ci-d11 (the read-only re-mount), `fd-ci-runner-unpinned` narrowed to pinned and declared but not observed running. `12fa0e5`: the sibling profile `strong-windows-qemu-whpx-ci` (C-3's ceilings, launch argv, the runner as `aieh-ci-runner` in `docker` only, the seeded config, loopback-only unit left disabled, registration by `--token-file` under `/run` with no `--ephemeral`, the `ci-control` sshd lines), its seed `profiles/seed/ci/user-data.tmpl` (no Agent Server, no token), its provision lock (the job image with the 7 layers read by the one authorized registry read, the runner binary, the wheel set by the tools lock, the Debian Moby closure) and `check_profile`'s `ci_runner` branch; **its commit message is wrong** (it repeats `0f60655`'s: a retry after a refused pre-commit took the previous message); the intended subject is "CI profile variant strong-windows-qemu-whpx-ci: seed, provision lock, check_profile's ci_runner branch (Q-02.2.1)"; history is not rewritten, this entry and the record's section 8 are the correction. `cd0bec1`: the record. **Overseer verification:** `check_profile --strict` PASS on the variant and the execution profile (`strong-incus-vm` fails on its 4 declared unknown pins, unchanged); `check_ci_policy`, `check_role_tokens`, `check_network_matrix`, `check_security_inventory`, `check_containment_cases` and verify_seed PASS; `test_check_ci_policy` and `test_check_profile` OK; the seed holds no token. Remaining for the leaf: the `tools/guest.py` CI bindings and lifecycle targets, the filtering proxy (R1), the P7 class and matrix edits (R3, the Overseer's); nothing about a running CI guest is verified.

- **2026-11-12: Owner authorization of OA-16 Act D, conditional (verbatim).**

  > Owner authorization — OA-16 Act D.
  >
  > CONDITIONALLY APPROVED: Qualify live protection
  > drift detection against the existing fixture.
  >
  > Repository:
  > aieh-authz-fixture/authz
  >
  > Expected baseline:
  > sha256:5dd7ace780ca0878146915ed74e8761b432e4489f20cdfe9a243804ad5aa6e42
  >
  > PRECONDITION — FIX THE RESTORATION CONTROL
  >
  > The current drift test uses unittest.subTest around
  > injections and restoration assertions.
  >
  > This must not allow a later injection to execute
  > after any unsuccessful restoration.
  >
  > Before the live run:
  >
  > 1. Modify the test so failed or unverified
  >    restoration stops the entire injection sequence.
  >
  > 2. Require independent read-back and a verified
  >    protection verdict with the original baseline
  >    digest after each restoration.
  >
  > 3. If an injection fails, still attempt bounded
  >    restoration of that injection's effects.
  >
  > 4. If restoration fails or cannot be verified,
  >    stop immediately. Do not send another injection.
  >
  > 5. Do not automatically retry failed mutations or
  >    restoration operations.
  >
  > 6. Add focused offline tests proving that no later
  >    injection executes after failed restoration,
  >    unexpected verification or an uncertain outcome.
  >
  > Keep the correction narrowly scoped and do not
  > interrupt the active CI Builder.
  >
  > LIVE EXECUTION
  >
  > After the correction is independently verified,
  > authorize one controlled qualification run.
  >
  > Before the first mutation:
  >
  > - Verify the auditor's identity and read-only token.
  > - Verify the repository's exact protection baseline.
  > - Confirm the fixture has no unexpected drift.
  >
  > Execute these five scenarios, sequentially:
  >
  > 1. Set main.block_admin_merge_override to false.
  > 2. Lower main's precedence below the ** rule.
  > 3. Add the unexpected aieh-qualify/* rule.
  > 4. Raise the verifier bot's repository permission
  >    to admin.
  > 5. Enable allow_squash_merge.
  >
  > For each scenario:
  >
  > - Apply only the named mutation.
  > - Verify the auditor reports drift identifying it.
  > - Restore the exact original configuration.
  > - Independently verify that protection is restored
  >   and its digest equals the original baseline.
  > - Proceed only after all checks pass.
  >
  > After the fifth scenario:
  >
  > - Verify the complete repository declaration.
  > - Verify the original baseline digest.
  > - Confirm no temporary rule or changed permission
  >   remains.
  > - Confirm the five role credentials are unchanged.
  > - Run the credential-exposure scan.
  > - Record the exact operations and their results.
  >
  > FAILURE HANDLING
  >
  > On unexpected mutation, missing drift detection,
  > failed restoration, or an uncertain outcome:
  >
  > - Attempt the bounded restoration needed to
  >   return the affected fixture to its baseline.
  > - Stop further injections.
  > - Report the observed state and any differences.
  > - Do not silently repair, retry, or claim PASS.
  > - Present any additional recovery act for separate
  >   Owner authorization.
  >
  > BOUNDARIES
  >
  > This approval covers OA-16 Act D only.
  >
  > It does not authorize:
  > - Act E or OA-14's protected merge.
  > - Credential issuance, rotation or revocation.
  > - Changes outside aieh-authz-fixture/authz.
  > - Any new Gitea identity or repository.
  > - CI live execution or runner registration.
  > - Any inference-provider or guest-network act.
  >
  > Record the evidence and present Act E's exact scope
  > only after Act D has passed.
  >
  > Continue unrelated eligible engineering work.

- **2026-11-12: OA-16 Act D restoration control (the Owner's precondition), verified.** `4bc611e`: the qualify phase's `subTest` loop replaced by `Qualification`, a stop-latched sequence independent of unittest: a baseline precondition (the auditor's `GET /token` login and exactly `read:repository`; `verified` with the expected digest from `AIEH_PROTECTION_AUDIT_BASELINE`; the site administrator's read-back equal to the complete declaration) before any mutation; per scenario the latch, the one injection sent once, drift naming it, one bounded restoration (the probe rule deleted if present, then one `apply_fixture`), then both the read-back equal to the declaration (all 34 fields per rule, the settings, every collaborator and permission) and `verified` with the baseline digest; any failed check, non-2xx answer or exception stops it, makes one restoration attempt if none was made for that injection, reads the final state once and reports; nothing retried, no later injection sent. **Overseer verification:** the driver read; its 25 offline tests (each stop case, the precondition, a full pass) and the gitea suite 282 OK (13 skipped); verify_seed PASS.

- **2026-11-12: OA-16 Act D performed once: PASS.** From a clean clone at `4bc611e2d3bd2297f3fdb9fa6a0ba8feac1bbb21`, 04:08 UTC, with `AIEH_PROTECTION_AUDIT_BASELINE` the Act B baseline. Precondition passed (the auditor's identity and scope, `verified` with `sha256:5dd7ace780ca0878146915ed74e8761b432e4489f20cdfe9a243804ad5aa6e42`, the read-back equal to the declaration). The five scenarios in order, each injection accepted (200, 200, 201, 204, 200), each detected as drift naming it (`main.block_admin_merge_override is False`; `main.priority is 5` with the rules matching main in Gitea's order `['**', 'main']`; `rule 'aieh-qualify/*' (priority 9) is not declared`; `collaborator aieh-bot-verifier: admin, declared read`; `allow_squash_merge is True`), each restored by one bounded restoration (the extra rule's DELETE 204, then the full declaration, every call 2xx), each followed by a read-back with no difference and `verified` with the baseline digest. After the fifth: the complete declaration, no `aieh-qualify/*` rule, the verifier bot `read`, `verified` with the baseline digest. A separate final `verify`: `verified`, the same digest. The site administrator's snapshots before and after are byte-identical (sha256 `87059ee3...`, also equal to Act C's final): every user's token list, the auditor's fingerprint `sha256:a4109cc864373ed5`, collaborators, branches, hooks and keys unchanged. The Overseer's exact-value exposure scan against the five role tokens: 0 in every output. Evidence (session scratch): `run-report.json` `4170e033...`, `run.out` `616bebd1...`, `final-verify.out` `205f5380...`. Gitea 28.3.0 records no audit event for these API calls. Act E unauthorized.

- **2026-11-12: Owner decision: OA-16 Act E, the PREPARE PHASE ONLY of OA-14's live exercise, approved; the record phase, any Owner statement and any protected merge not authorized.** Verbatim (the Owner's resume message, its Act E part):

  > OA-16 ACT E — OWNER DECISION
  >
  > APPROVED: The PREPARE PHASE ONLY of OA-14's live
  > authorization-recorder qualification.
  >
  > This approval authorizes preparation of the
  > fixture proposals, negative bot merge controls,
  > one-time challenges and Owner presentation.
  >
  > It does NOT authorize the RECORD PHASE, an Owner
  > statement, or a protected merge.
  >
  > TARGET REPOSITORY
  >
  > aieh-authz-fixture/authz
  >
  > REQUIRED PROTECTION BASELINE
  >
  > sha256:5dd7ace780ca0878146915ed74e8761b432e4489f20cdfe9a243804ad5aa6e42
  >
  > PREPARATION REQUIREMENTS
  >
  > 1. Verify the exact protection baseline, the
  >    expected repository state and the required
  >    identities and credential scopes.
  >
  > 2. Correct the auditor's negative merge control
  >    before live execution.
  >
  >    It must target a nonexistent pull request
  >    rather than either real proposal.
  >
  >    Require refusal by scope, not merely the
  >    absence of the pull request.
  >
  >    Act C already independently established the
  >    auditor's read-only scope.
  >
  > 3. Preserve the four other bots' real merge
  >    refusal controls.
  >
  >    Any successful unauthorized merge or movement
  >    of protected main is a SECURITY FAILURE.
  >
  >    Stop immediately on such a result, without
  >    attempting remaining controls.
  >
  > 4. Add or update focused offline tests for the
  >    auditor-control correction and stopping rules.
  >    Verify them before running live.
  >
  > 5. Use one fresh, empty, isolated run directory.
  >
  > 6. Execute the PREPARE phase once using the
  >    existing P-04.2 live exercise.
  >
  > AUTHORIZED PREPARE EFFECTS
  >
  > - Builder proposes two fixture-no-op manifests
  >   on separate work/authz-recorder branches.
  > - Builder creates the two corresponding pull
  >   requests.
  > - Reviewer approves each exact proposal head.
  > - The four other bots attempt their specified
  >   negative merge controls.
  > - The recorder creates the two one-time challenges.
  > - The preparation produces presentation.json and
  >   presentation.txt.
  > - The custody inspection runs.
  >
  > The recorder may read the harness-held Owner
  > credential in its trusted host context only
  > as required by the existing preparation contract.
  > No Owner credential may enter an agent context.
  >
  > REQUIRED PRESENTATION
  >
  > Report each proposed operation's:
  >
  > - Exact operation ID
  > - Repository and pull request
  > - Approved head SHA
  > - Manifest digest
  > - Challenge and expiration
  > - Intended effects
  > - Expected result
  > - Protection verification result
  >
  > Identify which operation is A, the intended
  > successful fixture merge, and which is B,
  > the stale-head negative control.
  >
  > Confirm that no protected merge occurred during
  > preparation and that main remains unchanged.
  >
  > STOP AFTER PREPARE
  >
  > Do not write or synthesize any Owner authorization
  > statement.
  >
  > Do not begin the record phase.
  >
  > Do not infer that this approval authorizes either
  > operation.
  >
  > Present the exact prepared challenge information
  > to me for a fresh, explicit Owner decision.
  >
  > If the challenges expire before I respond, report
  > the expiration; do not regenerate them or rerun
  > the preparation without further authorization.
  >
  > OTHER WORK
  >
  > Continue independently eligible offline work
  > without interrupting active Builders.
  >
  > The guest custody probe, inference live acts,
  > CI live acts and privileged-host operations
  > remain separately gated.
  >
  > Preserve the existing Owner-action queue and
  > report unresolved decisions at handoff.
  >
  > Do not create new architectural work or perform
  > unnecessary test-runtime optimization.
  >
  > Proceed with the authorized Act E preparation,
  > then present the result and stop at the
  > Owner-authorization boundary.

- **2026-11-12: Act E preparation, offline correction verified.** `33f54cc`..`e6e452e` (the Builder; [P-04.2 section 15](P-04.2-authorization-recorder.md)): prepare now checks, before any write, the protection baseline (`AIEH_AUTHZ_RECORDER_PROTECTION_BASELINE`, `verified` with exactly that digest), every role's `GET /token` login and scopes, no open pull request and neither run branch present; the protection auditor's control is the merge of a nonexistent pull request (absence read first as aieh-bot-verifier; PASS only 403 with Gitea's scope refusal), never of A or B; the four bots keep their real controls; main and both proposals are read after every attempt and any 2xx, merge or movement of main is a SECURITY FAILURE with no further control. Mutation of the changed lines: 92 of 92 killed. **Overseer verification:** the diff read; verify_seed PASS; owner suite 146 OK (2 skipped), gitea suite 282 OK (13 skipped), `AIEH_DATA_ROOT` an empty directory, still empty after. **Unrelated but detected:** `check_test_budget.py check --run` fails `TEST_REMOVED` for `test_acp_qualification_driver.DriverRun.test_without_a_root_channel_and_with_the_search_off_the_run_is_unknown`, removed by `5a4e270` (S-03.3) without re-recording `evidence/test-profile/test-ids.json`; carried as a fix-forward. Choice recorded: a drift answer at the recorder's own prepare after a verified precondition still yields a presentation stating the expected refusal (no merge is possible without `verified` at record).

- **2026-11-12: OA-16 Act E, the prepare phase of OA-14, performed once: PASS; stopped at the Owner's boundary.** From a clean clone at `95b5d1eedb1d1f5d6fed0d44c2f308cb155d288e`, the managed Gitea brought up first (`gitea_host.py up`: the record was stale from the previous session; non-elevated, loopback, kill-on-close job), one fresh empty run directory in session scratch, `AIEH_AUTHZ_RECORDER_LIVE=prepare`, `AIEH_AUTHZ_RECORDER_PROTECTION_BASELINE` the required baseline; 06:01:10Z to 06:01:42Z, exit 0, run once. **Precondition before any write:** the protection check `verified` with `sha256:5dd7ace780ca0878146915ed74e8761b432e4489f20cdfe9a243804ad5aa6e42`; `GET /token` of each role: aieh-bot-planner, aieh-bot-builder and aieh-bot-reviewer `write:repository`, aieh-bot-verifier and aieh-bot-protection-audit `read:repository`; main at `f18da179731cf906fbae4bfa62b23449363bb8aa`; no open pull request; neither run branch present. **Proposals:** the builder bot opened #31 (A, `live-20261112t060110z-a`, head `111d20c342b1a4ec5bcb5c409df8c59b55ab1fd2`) and #32 (B, the stale-head control, `live-20261112t060110z-b`, head `b2cbb2f5b900ea2931456bf509bddcccd07d9cb2`), each approved by the reviewer bot. **Negative controls:** planner, builder and reviewer 405 and verifier 403 on each of #31 and #32; the protection auditor's merge of the nonexistent #1000032 (confirmed absent first: 404) 403 "token does not have at least one of required scope(s), required=[write:repository], token scope=read:repository"; after each of the nine attempts main read `f18da179` and neither proposal merged. **Challenges** (the recorder's real prepare, 180 minutes): A `b7c663c54727651f3d8f80cf10ea4673` to 2026-11-12T09:01:14Z, manifest `sha256:847dbe5638239377efab6fe60b7ef80132b0c4ef8c7039642e77a5b7112b962d`; B `fb517570ab6464d08474b10980d597ba` to 2026-11-12T09:01:15Z, manifest `sha256:61591a548aa47f6fd0db8f46f74b0ce99f7ba97480d9e31bdb7b0e652a5b1c34`; the protection check `verified` for each at prepare. Custody inspection: the Owner account's password found nowhere (managed root, the clone's listed files, the run directory, the process environment), nothing unreadable. **Overseer verification:** the report and the presentation read; after the run `protection_check.py verify aieh-authz-fixture/authz` answered `verified` with the same baseline digest. No protected merge occurred; main unchanged. Evidence (session scratch): `presentation.json` `75d5dd37...`, `presentation.txt` `33be0a7d...`, `report.json` `e9228eb4...`, `run.out` `d93a2c65...`. No Owner statement written; the record phase not begun; presented to the Owner for a fresh, explicit decision.

- **2026-11-12: Owner decision: fresh one-time challenges for OA-14's two existing operations authorized; no merge, no record phase.** The challenges of the Act E prepare expired unused (09:01:14Z and 09:01:15Z). Verbatim:

  > I have reviewed Act E's prepare results for operations
  > live-20261112t060110z-a and live-20261112t060110z-b.
  >
  > The original one-time challenges have expired.
  >
  > I authorize regeneration of fresh one-time challenges
  > for both existing operations, limited to their already
  > prepared pull requests, approved heads, manifest digests,
  > and intended effects.
  >
  > This does not authorize either merge, modification of
  > either approved head or manifest, creation of replacement
  > proposals, or execution of the record phase.
  >
  > Before presenting the fresh challenges, verify that both
  > proposals remain unchanged, neither has merged, main has
  > not moved, and repository protection is still verified
  > against the approved baseline.
  >
  > If fresh challenges cannot be generated safely against
  > the existing prepared operations, stop and report the
  > specific blocker without recreating the proposals or
  > performing additional live operations.
  >
  > Present both fresh challenges and their complete
  > authorization details for my explicit decision.

- **2026-11-12: Phase rechallenge built offline and verified.** `858bac7`..`c4dc0fe` (the Builder; [P-04.2 section 16](P-04.2-authorization-recorder.md)): `AIEH_AUTHZ_RECORDER_LIVE=rechallenge` on the same run directory sends Gitea only GET requests; before any challenge it requires every earlier challenge for the two operations to be expired (`CHALLENGE_STILL_LIVE` otherwise), the protection check `verified` with the baseline, each role's identity and scopes, main at the presented head (`MAIN_MOVED`), each pull request open, unmerged, on its presented base, branch and approved head with the presented manifest digest, and the recorder's own operation and expiry checks; then the recorder's real `prepare` for each, the subject compared field by field (`SUBJECT_DIFFERS`); the earlier presentation kept as `presentation-<k>.*`, the new one marked as a regeneration whose controls were not re-run. Mutation of the changed lines: 124 of 124 killed. **Overseer verification:** the phase read (no write method); verify_seed PASS; owner suite 170 OK (2 skipped), gitea suite 282 OK (13 skipped), `AIEH_DATA_ROOT` empty and still empty after. Overseer rulings: the Builder's two stricter choices accepted (any still-usable challenge file for these operations blocks; the recorder's operation and expiry checks run for both before any challenge is written).

- **2026-11-12: Fresh OA-14 challenges regenerated once: PASS; stopped at the Owner's boundary.** From a clean clone at `fa472733b5c9c9fc2cb59ed782a4b6459e990628`, on Act E's run directory (its presentation verified byte-identical to the one prepare wrote, `75d5dd37...` and `33be0a7d...`, before the run), `AIEH_AUTHZ_RECORDER_LIVE=rechallenge`, 15:06:50Z to 15:07:23Z, exit 0, run once; Gitea received GET requests only. Verified before any challenge: both earlier challenges expired (09:01:14Z, 09:01:15Z); the protection check `verified` with `sha256:5dd7ace780ca0878146915ed74e8761b432e4489f20cdfe9a243804ad5aa6e42`; each role's identity and scopes as at prepare; main at `f18da179731cf906fbae4bfa62b23449363bb8aa`, unmoved; #31 and #32 open, not merged, base main, at their approved heads `111d20c3...` and `b2cbb2f5...` on their branches, with the presented manifest digests; no receipt names either operation and neither manifest has expired. The recorder's real prepare then issued A `c765b1ce9e133725dedb24863149ff09` (to 18:06:51Z) and B `8e0c514a5810ae362edd82b6f9af8a74` (to 18:06:52Z), each subject equal field by field to the presented operation; the protection check `verified` for each. The earlier presentation is kept as `presentation-1.*` (hashes unchanged); the new one states that the merge controls were not re-run. Custody inspection: nothing found, nothing unreadable. **Overseer verification:** after the run `protection_check.py verify` answered `verified` with the baseline digest. No protected merge; main unchanged; no statement written; the record phase not begun. Evidence (session scratch): `presentation.json` `14725c87...`, `presentation.txt` `c5302d50...`, `report-rechallenge.json` `6b75f0ef...`, `run-rechallenge.out` `041f555f...`.

- <a id="owner-authorization-oa-14-2026-11-12"></a>**2026-11-12: Owner authorization: OA-14 operations A and B**, given in the main session after the fresh challenges were presented; transcribed verbatim by the Overseer as the recorder's statement (`attributedTo` owner, channel `main-session`, reference `evidence:bootstrap-log.md#owner-authorization-oa-14-2026-11-12`; statement file sha256 `1b08feae...`, its text checked by `owner_decision.statement_verdict` before the run). Verbatim:

  > I authorize both operations:
  >
  > A: live-20261112t060110z-a
  > B: live-20261112t060110z-b
  >
  > For operation A, I authorize the recorder to merge pull
  > request #31 into main using only the approved head
  > 111d20c342b1a4ec5bcb5c409df8c59b55ab1fd2
  > and manifest digest
  > sha256:847dbe5638239377efab6fe60b7ef80132b0c4ef8c7039642e77a5b7112b962d.
  >
  > For operation B, I authorize the stale-head negative
  > control against pull request #32, approved head
  > b2cbb2f5b900ea2931456bf509bddcccd07d9cb2
  > and manifest digest
  > sha256:61591a548aa47f6fd0db8f46f74b0ce99f7ba97480d9e31bdb7b0e652a5b1c34.
  >
  > I authorize the deliberate branch mutation required to
  > make B stale, but not a successful merge of B.
  >
  > Use only the fresh challenges:
  > A: c765b1ce9e133725dedb24863149ff09
  > B: 8e0c514a5810ae362edd82b6f9af8a74
  >
  > Execute B before A, preserving all existing protection
  > checks, custody controls, evidence requirements, and
  > immediate-stop conditions.
  >
  > This authorization is limited to these two operations
  > and their documented effects. It does not authorize
  > other privileged operations or additional live exercises.
  >
  > If either challenge has expired, stop without executing
  > that operation or regenerating its challenge.

- **2026-11-12: OA-14 record phase performed once: B refused, A merged; PASS for the live exercise.** From the clean clone at `fa47273`, on Act E's run directory and its regenerated presentation, at 15:34:02Z to 15:34:11Z, exit 0, both challenges unexpired (to 18:06:51Z and 18:06:52Z). **B first** (`8e0c514a5810ae362edd82b6f9af8a74`): the builder bot's push to `work/authz-recorder-20261112t060110z-b` after the recorder's checks (201), then Gitea answered the recorder's merge 409 "head out of date": `HEAD_STALE`, receipt `owner-authorization/v1/8e0c514a...` failed, #32 not merged, main unmoved. **Then A** (`c765b1ce9e133725dedb24863149ff09`): the protection check `verified` with `sha256:5dd7ace780ca0878146915ed74e8761b432e4489f20cdfe9a243804ad5aa6e42` immediately before the merge and again after (equal); one merge commit `75e89b28143464949c24bd46433a5d9f2197b0d0` on main, parents `f18da179731cf906fbae4bfa62b23449363bb8aa` and the approved head `111d20c342b1a4ec5bcb5c409df8c59b55ab1fd2`, manifest digest `sha256:847dbe56...b962d` at the merge, merged by aieh-owner, the six trailers (decision `d18a66d3-3072-4beb-a8dc-ac37047c1a33`, channel `main-session`, the approved head, the digest, the statement reference, `authorization-recorder/1`); receipt `owner-authorization/v1/c765b1ce...` confirmed (reserved, dispatched, confirmed). Read-backs: main at the merge commit; aieh-owner holds zero tokens (the recorder's identity check). Cleanup as documented: #32, still open, closed by the builder bot (PATCH 201); the work/ branches and the merge commit stay. Custody inspection: nothing found, nothing unreadable. **Overseer verification:** the report read; after the run `protection_check.py verify` answered `verified` with the baseline digest. Evidence (session scratch): `report-record.json` `cb2890fe...`, `run-record.out` `87d04a35...`, the run directory's recorder state (challenges, decisions, store). Nothing else was run live. Not decided here: the P-04.2 leaf verdict and decision 0012's acceptance (Overseer, next).

- **2026-11-12: Test inventory repaired (unrelated but detected).** `f92601c`: `check_test_budget.py check --run` failed `TEST_REMOVED` for a driver test attributed to `5a4e270`; the test was renamed one commit earlier, in `aa6a3a7` (S-03.3 slice 6, F-6, recorded in its evidence section 5), to `test_with_an_older_reporter_and_the_search_off_the_run_is_unknown`. Only that id changed in `evidence/test-profile/test-ids.json` (no regeneration; `recorded_from` kept); the full profile shows exactly one id gone and no skip changed across 13 suites. **Overseer verification:** the one-line diff read; the new name exists, the old does not; the Builder's `check --run` PASS (serial 145.8 s; walls as notes); publication gate clean.

- **2026-11-12: P-04.2 acceptance review: blocked on one clause; decision 0012 accepted.** `1d76344`..`67b9c5b` (records, decision 0012, [section 17](P-04.2-authorization-recorder.md)). **Met:** one merge bound to head and digest with receipt and trailers (live, A); the stale head's 409 (live, B); no token minted (live: aieh-owner holds none); every bot token refused for the merge (live, Act E) and as the recorder's input (offline, before any request); protection drift (the verifier's live drift detection, Act D, with the fail-closed seam and the live `verified` answers around A's merge); the altered digest, replayed or expired decision, missing or non-Owner statement, missing challenge and a token on aieh-owner (refusals on the recorder's real code against the fake transport, each before any merge call, over Gitea reads exercised live; not individually live: an aieh-owner token would itself mint one, and no further live exercise is authorized); decision 0012 committed; the same-account limit recorded. **Not met:** the custody clause. Plan amendment `2967d2d` added it to discharge reconciliation row O-033 (`fd-owner-credential-custody`: the Owner's push credential and provider login); the live inspection covered aieh-owner's password only (absent from the managed root, the checkout, the run directory and the main session's environment, three times; no job environment existed). Reading it as the recorder's credential alone would narrow the criterion, so P-04.2 is not accepted; OA-21 presents the minimum closing act. Job-environment custody of the aieh-owner credential is owned by S-03.3 (agent attempts) and Q-02.2.2 (CI jobs) by their plan text; not E-01.3.3 or S-03.2. **Decision 0012: Accepted (Overseer)** on its own stated conditions (point 6's check established and qualified, OA-16 Acts A to D; the live exercise run with the Owner's own authorization); a dated Current facts section; no numbered point changed. Also: two role-token realization rows verified (the owner's Gitea account, the recorder's protection auditor); S-01.3.2's job rows narrowed to what their search covered; stale Proposed/not-provisioned text corrected in the inventory, the security, policy, owner and gitea READMEs, docs and a Taskfile description. **Overseer verification:** the diffs read; verify_seed PASS; the four checkers PASS; the checker tests 514 OK; no record claims P-04.2 accepted. Left as recorded wording of intent, not verified claims: the conversation-container asset, the execution profile and decision 0016 point 4 state that jobs hold no Owner credential.

- <a id="owner-direction-five-role-operating-model"></a>**2026-11-12: Owner direction: the five-role operating model.** Three Owner messages of 2026-11-12 in the main session, verbatim below (labelled msg6, msg7 and msg9 in the order given; the paste wrappers are removed, and in msg9 one bracketed substitution replaces the name of an unrelated project, which this repository does not name). Between msg7 and msg9, a further Owner message of 2026-11-12 (msg8) directed an independent architectural review of the proposal by the shared architect, as a design consultation; its findings were reconciled with the Overseer's proposal before msg9. Decision 0018 (Proposed) records the resulting responsibilities.

  msg6, 2026-11-12 (D1 accepted; the five roles; design only):

  > I have reviewed your strategic reassessment.
  >
  > I agree with the central finding: we have prioritized
  > local engineering completeness over integrated capability
  > delivery.
  >
  > I accept D1, the first contained AI-assisted coding
  > task producing a verified result and draft pull request,
  > as the proposed next demonstration target.
  >
  > However, I do not want the existing Overseer to absorb
  > permanent responsibility for product strategy, milestone
  > selection, critical-path management, and global priority.
  >
  > We are adopting a different target organizational model:
  >
  > PLANNING
  > - Product Manager: accountable lead for intent refinement,
  >   product outcomes, priorities, and milestone selection.
  > - Program Manager: specialist responsible for work
  >   inventory, dependencies, sequencing, readiness,
  >   critical-path analysis, and blockers.
  > - Architect: shared specialist for architecture,
  >   integration strategy, technical feasibility,
  >   and architectural coherence.
  >
  > EXECUTION
  > - Engineering Manager: the current Overseer role,
  >   accountable for executing authorized work packages,
  >   delivery, delegation, verification, and reporting.
  > - Engineer: the current Builder role.
  > - Architect: the SAME shared Architect role used
  >   by Planning, selectively invoked when needed.
  >
  > This is five distinct agent roles, not six.
  >
  > Both accountable leads selectively invoke specialists.
  > There is no requirement to consult every specialist on
  > every decision.
  >
  > Planning owns what, why, priorities, and sequencing.
  > Execution owns delivery within accepted commitments.
  > The Architect informs both without independently changing
  > product priorities or Owner authority.
  >
  > Strategic intent, capabilities, dependencies, constraints,
  > decisions, and evidence must be durable repository state,
  > not conversational memory held by individual agents.
  >
  > Your next assignment is DESIGN ONLY:
  >
  > 1. Reconcile this organizational model with the existing
  >    agent definitions, project architecture, Work model,
  >    Workflow model, governance mechanisms, and plans.
  >
  > 2. Recommend the minimum changes required to introduce
  >    a Product Manager and Program Manager while preserving
  >    the existing execution capabilities.
  >
  > 3. Define the planning-to-execution contract, including
  >    work-package dispatch, delegated authority, delivery
  >    commitments, evidence reporting, blockers, and
  >    replanning.
  >
  > 4. Identify existing mechanisms that can implement this
  >    without introducing new infrastructure, services,
  >    governance layers, or unnecessary artifacts.
  >
  > 5. Define how planning maintains strategic direction
  >    while avoiding continuous coordination overhead.
  >    Specialists are invoked based on need.
  >
  > 6. Show how the proposed structure would manage the D1
  >    critical path, including the deferrals identified
  >    in your assessment.
  >
  > 7. Distinguish changes requiring Owner authority from
  >    changes that can be delegated after the architecture
  >    is accepted.
  >
  > 8. Reassess OA-21. Determine whether GitHub credential
  >    inspection is genuinely necessary for P-04.2 or
  >    represents an incorrectly attached proof obligation.
  >
  > 9. Identify which recommendations from your previous
  >    section F belong in the new planning roles and which
  >    remain legitimate Engineering Manager responsibilities.
  >
  > 10. Propose an incremental migration that avoids
  >     interrupting functioning implementation mechanisms
  >     or losing existing evidence and accepted decisions.
  >
  > Do not implement anything yet.
  > Do not modify agent definitions, plans, decisions,
  > or acceptance criteria.
  > Do not resume Q-02.2.1.
  > Do not initiate live operations.
  >
  > Return a concise architectural proposal with:
  >
  > A. Final role definitions and decision authority.
  > B. Planning-to-execution operating workflow.
  > C. Durable work and dependency model.
  > D. Minimum repository and agent-definition changes.
  > E. D1 critical-path ownership and sequencing.
  > F. Migration plan.
  > G. Genuine Owner decisions needed to proceed.
  >
  > The goal is a reusable AI engineering operating model
  > that maintains strategic objectives while allowing
  > execution to proceed autonomously and efficiently.
  >
  > Avoid reproducing human organizational bureaucracy.
  > Optimize for clear authority, durable state, selective
  > agent invocation, and integrated capability delivery.
  >
  > Stop after presenting the proposal for review.

  msg7, 2026-11-12 (the Owner's role; the corrected responsibility model; design only):

  > Revise your proposed five-role AI Engineering operating model
  > based on the following direction.
  >
  > My role is to supply intent, constraints, feedback, and
  > authorization for genuinely consequential external effects.
  > I am not the project's operational authority or project manager.
  >
  > The AI system owns translating my intent into plans,
  > architecture, implementation, integration, verification,
  > and delivery.
  >
  > Adopt these five roles:
  >
  > - Product Manager: planning lead, intent refinement,
  >   capabilities, priorities, milestones, acceptance criteria.
  > - Program Manager: work inventory, dependencies, critical
  >   path, sequencing, readiness, blockers, and deferrals.
  > - Architect: shared specialist serving planning and
  >   execution, consulted selectively.
  > - Engineering Manager: execution lead, delivery commitments,
  >   delegation, implementation coordination, and verification.
  > - Engineer: implementation, integration, and testing.
  >
  > The Architect should discover and selectively apply relevant
  > skills for planning and execution consultations. Prefer
  > existing open-source skills over building new ones. Skills
  > provide expertise, not additional authority.
  >
  > Both leads invoke specialists only when needed.
  >
  > Separate strategic planning from engineering execution through
  > durable state and explicit work commitments. Do not require
  > planning involvement in routine implementation decisions.
  >
  > Correct the proposed responsibility model:
  >
  > 1. The Product Manager derives and maintains acceptance
  >    criteria from my intent, seeking clarification only when
  >    necessary.
  >
  > 2. The Product Manager selects milestones and priorities
  >    without requiring my approval at every transition.
  >
  > 3. The Program Manager challenges dependencies and prevents
  >    discovered engineering work from automatically expanding
  >    the critical path.
  >
  > 4. The Engineering Manager owns ordinary engineering decisions
  >    and publication within established permissions.
  >
  > 5. My explicit authorization remains necessary for actions
  >    that cross reserved security, credential, financial,
  >    destructive, or external-effect boundaries.
  >
  > 6. Preserve accepted constraints and requirements. Agents
  >    may refine implementation and planning autonomously but
  >    may not silently contradict or weaken my expressed intent.
  >
  > 7. Do not use the historical bootstrap log as the permanent
  >    authoritative representation of current strategic state.
  >    Recommend a minimal, declarative current-state representation
  >    linked to the existing plans, decisions, and evidence.
  >
  > 8. Reconcile the proposed responsibility model with existing
  >    authorization mechanisms so routine engineering decisions
  >    do not unnecessarily become Owner approval requests.
  >
  > 9. Preserve the D1 integrated coding-agent demonstration as
  >    the immediate delivery objective.
  >
  > 10. Retain your finding that OA-21 was incorrectly attached
  >     to P-04.2. Include the proposed correction in the
  >     revised design.
  >
  > This remains DESIGN ONLY.
  >
  > Do not modify agent definitions, repository plans,
  > architecture records, or implementation artifacts yet.
  > Do not resume Q-02.2.1 or initiate live operations.
  >
  > Return the revised operating model, minimum migration steps,
  > and only the genuinely consequential decisions that still
  > require my explicit authorization.
  >
  > Be concise and opinionated. Optimize for delivering integrated
  > capabilities, not reproducing human organizational bureaucracy.
  >
  > Stop for review after presenting the revision.

  msg9, 2026-11-12 (J1 to J3; the offline migration authorized, items 1 to 9):

  > I have reviewed the reconciled five-role proposal and
  > Fable's independent architectural assessment.
  >
  > My decisions:
  >
  > J1: Accept Option A.
  > Do not introduce CURRENT_STATE.json or another parallel
  > planning state store. Reuse existing plans, evidence,
  > OpenSpec, and Backlog. Minimize temporary state.
  >
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
  >
  > J3: Delegate technical model selection within an
  > authorized provider and spending envelope.
  >
  > Verify exact model identifiers against current provider
  > information. Present the selected models, intended uses,
  > and expected cost characteristics before the first
  > authorized paid operation. Do not require my approval
  > for ordinary model-selection details.
  >
  > Operating model:
  >
  > - Product Manager owns intent refinement, product
  >   outcomes, priorities, and milestone selection.
  > - Program Manager owns dependencies, sequencing,
  >   critical paths, readiness, blockers, and deferrals.
  > - Engineering Manager owns execution and delivery.
  > - Engineer implements and verifies bounded tasks.
  > - Architect provides shared technical expertise,
  >   invoked selectively.
  >
  > Planning determines what outcomes matter and which
  > work is worth undertaking. Engineering determines
  > how to deliver committed work.
  >
  > The Product Manager accepts milestones against their
  > product outcomes. The Engineering Manager verifies
  > engineering completion. Use independent review for
  > consequential changes.
  >
  > My role is to provide intent, constraints, feedback,
  > and authorization at genuinely reserved boundaries,
  > not to manage routine engineering decisions.
  >
  > Proceed with the OFFLINE migration:
  >
  > 1. Create the two new planning agent definitions.
  > 2. Consolidate the Architect's planning and execution
  >    consultation capabilities without weakening either.
  > 3. Narrow the existing Overseer into an Engineering
  >    Manager operating against planning commitments.
  > 4. Preserve the existing Engineer role.
  > 5. Implement the minimum planning-to-execution handoff
  >    using existing repository mechanisms.
  > 6. Prepare decision 0018 as Proposed, documenting
  >    responsibilities, delegated operations, reserved
  >    boundaries, and standing authorization semantics.
  > 7. Prepare the D1 plan changes and supporting leaves
  >    identified through the independent review.
  > 8. Correct OA-21's obligation mapping without claiming
  >    that unperformed credential inspections passed.
  > 9. Preserve existing acceptance criteria, security
  >    boundaries, and evidence.
  >
  > Important:
  >
  > This authorizes routine offline engineering and
  > publication within existing permissions.
  >
  > It does NOT authorize new live operations, changes to
  > existing security or credential permissions, spending,
  > external network access, or execution of proposed
  > standing authorization classes.
  >
  > Do not treat proposed decision 0018 as an accepted grant
  > of additional authority. Existing restrictions remain
  > effective until explicitly changed.
  >
  > Do not resume unrelated Q-02.2.1 work.
  >
  > Use the existing publication and integrity mechanisms.
  > Keep tests proportional to the changes.
  >
  > At completion, report:
  >
  > - Agent definitions created or modified.
  > - Planning-to-execution handoff implemented.
  > - Decision 0018 status.
  > - D1 plan readiness and remaining critical blockers.
  > - OA-21 and P-04.2 status.
  > - Published commits and verification.
  > - Genuine reserved decisions requiring my attention.
  >
  > Once the planning roles are operational, stop and
  > present the handoff. Do not independently start the
  > next execution milestone.

- <a id="owner-direction-definitions-skills-instructions-state-enforcement"></a>**2026-11-12: Owner direction: definitions, skills, repository instructions, state and enforcement.** Given in the main session during the migration, verbatim (msg10; the paste wrapper is removed):

  > The Engineering Manager definition exceeding the 18 KiB
  > agent-definition limit suggests that we may be putting
  > too much procedural knowledge into agent definitions.
  >
  > Do not solve this solely by compressing or deleting prose.
  >
  > During the current five-role migration, review the agent
  > definitions and distinguish five concerns:
  >
  > 1. Agent identity, responsibilities, delegation, and
  >    authority boundaries: agent definitions.
  >
  > 2. Specialized repeatable procedures and reasoning
  >    methods: selectively loaded agent skills.
  >
  > 3. Repository-wide engineering rules and conventions:
  >    AGENTS.md and related canonical instructions.
  >
  > 4. Current objectives, milestones, dependencies,
  >    decisions, commitments, and evidence:
  >    durable repository state.
  >
  > 5. Inviolable security, authorization, integrity,
  >    and publication constraints:
  >    deterministic enforcement wherever possible.
  >
  > Identify procedural material currently embedded in agent
  > definitions that belongs in reusable skills.
  >
  > Prefer existing skill mechanisms and established
  > open-source skills. Do not invent a new skill framework.
  >
  > Maintain progressive disclosure: agents should load
  > specialized procedures only when the current task
  > requires them.
  >
  > Avoid automatically loading every skill into every
  > agent's context.
  >
  > Preserve all existing requirements, authority boundaries,
  > and operational safeguards. Moving instructions must
  > not silently weaken behavior or create conflicting
  > authoritative copies.
  >
  > Keep agent definitions concise and focused on their
  > stable responsibilities and routing to relevant skills.
  >
  > Use shared skills where planning and execution require
  > the same procedure, without blurring their decision
  > rights.
  >
  > Assess whether any instructions should instead become
  > deterministic checks rather than relying on model
  > compliance.
  >
  > Incorporate this separation into the current migration.
  > Do not expand into a standalone skill-platform project.
  >
  > Report briefly:
  > - What remained in agent definitions.
  > - What moved into skills.
  > - What belongs in shared repository instructions.
  > - Any newly identified enforcement gaps.
  > - Final definition sizes and verification results.
  >
  > Continue respecting the current authorization boundaries
  > and existing migration scope.

- **2026-11-12: The offline five-role migration (msg9 items 1 to 9, msg10).** Outside this repository, the Owner's own agent definitions now realize the five roles: a product manager and a program manager were created, the architect consolidates planning and execution consultations, the Overseer is narrowed into the engineering manager, and the Builder is kept as the engineer (not inspected from this repository). Repeatable procedures moved from those definitions into selectively loaded skills. This repository gained the plan amendment `f3a6c92` (groups E-05 and P-05, S-03.3's re-homing sentence, the CI deferral), the handoff tool `tools/plan_commitment.py` with `task plan:commitment` (`a3064e3`), decision 0018 as Proposed and the `CLAUDE.md` section "Planning and execution" (`9ed4ad7`), and these records. Nothing live was performed and no permission changed.

- **2026-11-12: P-04.2 accepted (PASS); OA-21's obligation mapping corrected.** On the Owner's direction "Correct OA-21's obligation mapping without claiming that unperformed credential inspections passed" (verbatim above). **Cause (introduced-by plan amendment `2967d2d`, re-pointed `1b25112`):** reconciliation row O-033, the finding `fd-owner-credential-custody` about the Owner's push credential (`cred-owner-github`) and coding-assistant login (`cred-owner-provider-login`), was carried to P-04.2, whose artifact holds a different credential. P-04.2's sentence "An inspection shows that the Owner credential exists only in its OS credential-provider entry: no file copy, and absent from every agent and job environment" reads, in its leaf, as the recorder's credential `cred-gitea-owner-account`. That credential was inspected live three times: absent from the managed root, the checkout, the run directory and the main session's environment. Its absence from job environments, none of which existed, stays owned by S-03.3 (agent attempts) and Q-02.2.2 (CI jobs), as ruled at the acceptance review. **Re-homed, not dropped:** (1) the Owner's two credentials absent from every agent-attempt environment: S-03.3, whose proof gains, by the plan amendment `f3a6c92`, the sentence "The Owner's own credentials (cred-owner-github, cred-owner-provider-login) are absent from the attempt's container, environment and files, by name and by an in-memory value search with a positive control; an unrestricted Owner credential never enters the attempt."; (2) their absence from CI job environments: an explicit plan deferral until the CI lane is committed (amendment `f3a6c92`); (3) where the Owner's own host stores keep them, and whether any file copy exists: **not inspected, unknown**, presented as OA-21 for the Owner to accept as a decision-0010 same-account limit (reconsider condition: a separate operating-system identity for the dispatcher or the development agents) or to authorize a read-only, metadata-first inspection. The inventory's `carried_to` and the reconciliation record are corrected to match. No inspection is claimed that was not performed. **P-04.2: PASS** (Overseer, as engineering manager). P-04.3 is unblocked.

- <a id="commitment-d1"></a>**2026-11-12: Commitment: D1.** Terminal leaf **E-05.5**, "Demonstrate D1: one contained AI-assisted coding task to a verified result and a draft pull request"; acceptance is its proof. Committed set, from `task plan:commitment -- E-05.5` at `5f930d2`: 57 leaves, 46 passed, 11 open, 4 ready, 7 blocked. Open: S-03.1 (IN PROGRESS, ready), S-03.2 (IN PROGRESS, blocked), S-03.3 (IN PROGRESS, blocked), P-04.3 (not started, ready), E-05.1 (not started, ready), E-05.2 (not started, blocked), E-01.3.3 (IN PROGRESS, ready), E-05.3 (not started, blocked), E-01.3.2 (not started, blocked), E-05.4 (not started, blocked), E-05.5 (not started, blocked); ready: S-03.1, P-04.3, E-05.1, E-01.3.3. (Figures corrected in a planning pass of 2026-11-12: they were first taken at the amendment commit `f3a6c92`, with P-04.2 then open (BLOCKED) and ready: 45 passed, 12 open, 4 ready, 8 blocked; P-04.2's verdict above makes them the figures given here.) Reserved acts it depends on: OA-12 (the provider, the spending cap, the key); OA-22 (prepared, not granted); OA-07 (decision 0013: each host-to-guest connection needs a recorded Owner approval), whose dispatch-path connection on D1's path is edge `nm-dispatcher-agent-server` (the dispatcher to the outer Agent Server over the management SSH channel to guest 127.0.0.1:8000), so OA-22 item (d), when and only if the Owner grants it, is that approval; OA-07 stays pending, and its Owner UI connection (U-01.2) is untouched; and at D1 time the two recorder decisions, the design acceptance (decision 0008; OA-23) and the manifest promotion (P-04.3; OA-24). Recorded on the Owner's selection of D1 (msg6) during the migration session; the product manager confirms or revises it at its first planning session.

- <a id="owner-direction-catalog-publication-findings"></a>**2026-11-12: Owner direction: agent-catalog publication and three findings for the program manager.** Given in the main session after the migration report, verbatim (the paste wrapper is removed):

  > I authorize a one-time, push-only HTTPS protocol
  > exception for publication of the two already verified
  > agent catalog commits:
  >
  > b27b893
  > ce6ffa2
  >
  > Scope:
  > - The existing agent catalog repository only.
  > - The existing origin/main destination only.
  > - No additional commits or modifications.
  > - No fetch, pull, force-push, credential changes,
  >   or persistent Git configuration changes.
  >
  > Before pushing, verify that:
  > - The local branch contains exactly the approved commits.
  > - The working tree is clean.
  > - The target remote and branch are the expected ones.
  > - Publication will be a fast-forward.
  >
  > If the remote state cannot be verified without
  > exceeding this authorization, stop and report.
  >
  > Use the existing one-command push-only exception.
  > Do not make the exception persistent.
  >
  > After publication, verify the resulting remote state
  > and report the published commit.
  >
  > Record the following findings for Program Manager
  > classification, without automatically placing them
  > on the D1 critical path:
  >
  > 1. Catalog suite failures and environmental limitations.
  > 2. Handoff readiness ignoring Owner-act gates.
  > 3. Instruction-only enforcement of development-agent
  >    boundaries and repository integrity checks.
  >
  > Do not initiate additional implementation, live D1
  > operations, or other reserved acts.
  >
  > Once the catalog publication is verified, stop and
  > report the result.
  >
  > The next planning session should use product-manager,
  > not the legacy engineering-overseer.

- **2026-11-12: Agent catalog published (outside this repository).** Before the push, checked locally: the branch was `main` tracking `origin/main`; the push URL was the expected repository; exactly the two approved commits were ahead (`b27b893`, then `ce6ffa2`, on the tracking head `0983026`), none behind; the tracked working tree was clean; the HTTPS refusal was set in the clone's own configuration only. The remote's live head was not read, because reading it would have needed a fetch. The fast-forward guarantee came from the push itself: an unforced push either fast-forwards or is refused. One command, with the exception for that command only and lazy fetch disabled: the server reported `refs/heads/main` `0983026..ce6ffa2` as a fast-forward update, exit 0. Afterwards: the tracking ref is `ce6ffa2`, 0 ahead and 0 behind; the clone's HTTPS refusal is unchanged, and no global value exists. Published commit: `ce6ffa2`.

- <a id="findings-for-program-manager-2026-11-12"></a>**2026-11-12: Findings recorded for program-manager classification.** On the Owner's direction above. Unclassified: none is a leaf, a deferral or a proof clause, and none is on the D1 critical path until the program manager classifies it.
  1. **Agent-catalog suite failures and environmental limits (observed during the migration; the catalog is outside this repository).** Its full application suite: 3136 passed, 300 failed, 100 errors. 399 of those 400 fail the same way at the pre-change commit: Windows path-length failures under the long session temporary directory, and timeouts under load. The one failure the change caused was fixed. Its installation suite: 24 passed, 87 skipped, because no wheelhouse is configured. Open question: whether a green suite on this host is a precondition for anything committed here.
  2. **Handoff readiness ignores Owner-act gates (observed; raised by the engineering manager's read of the D1 handoff).** `tools/plan_commitment.py` derives "ready" from recorded dependencies and status only, not from the Owner-actions queue. Of the four ready D1 leaves at `550b4fa`, only P-04.3 needs no Owner act.
  3. **Development-agent boundaries and repository integrity checks are enforced by instruction only (observed).** (a) The path boundary and protected paths rely on the agent complying. The coding assistant's deny rules or a pre-tool hook in the Owner's own settings could enforce them. (b) Bypassing git hooks (`--no-verify`, or a changed hooks path) is prevented only by instruction. (c) Nothing runs `tools/verify_seed.py` automatically: no hook and no CI. (d) Related, also instruction-only: one writer per checkout; execution touching only committed leaves; Owner quotes in this log are checked for presence, not for who wrote them. Only the authorization recorder's challenge is bound to the Owner.

- <a id="owner-direction-first-planning-review"></a>**2026-11-12: Owner direction: the product manager's first planning review.** Given in the main session that opened the first product-manager planning session, verbatim (the paste wrapper is removed):

  > You are taking over strategic planning for the
  > AI Engineering Harness.
  >
  > The five-role migration is complete for its initial
  > scope. The agent catalog is published at ce6ffa2,
  > and the harness repository is published through
  > 1021c77.
  >
  > Establish your planning context from the repository's
  > authoritative plans, decisions, evidence, and progress
  > records. Do not rely on this prompt as a substitute
  > for those records.
  >
  > Our immediate product objective is D1: demonstrate
  > a contained AI-assisted coding task that modifies
  > a demo repository, runs tests, and returns a result
  > branch, draft pull request, and verification evidence.
  >
  > Before directing further execution:
  >
  > 1. Review proposed decision 0018 and evaluate whether
  >    its delegation model reflects my intent:
  >
  >    I provide vision, constraints, feedback, and
  >    authorization for genuinely consequential effects.
  >
  >    AI owns product refinement, planning, architecture,
  >    implementation, integration, verification, and
  >    delivery within those boundaries.
  >
  >    Identify any provisions that unnecessarily make
  >    me the operational decision-maker.
  >
  > 2. Review OA-21 and determine whether its remaining
  >    decision is actually consequential or can be
  >    resolved through an accepted existing constraint.
  >    Do not inspect personal credentials.
  >
  > 3. Ask the Program Manager to classify the three
  >    outstanding findings:
  >
  >    - Catalog test failures and environmental issues.
  >    - Handoff readiness ignoring pending Owner actions.
  >    - Development-agent safeguards relying on
  >      instructions rather than deterministic enforcement.
  >
  >    Distinguish genuine D1 blockers from deferred
  >    hardening. In particular, establish whether the
  >    readiness defect could allow unauthorized execution.
  >
  > 4. Reconcile the current D1 critical path with actual
  >    implementation readiness and authorization gates.
  >
  > 5. Identify the smallest next execution commitment
  >    that can proceed under existing permissions.
  >
  > Do not modify accepted decisions, expand delegated
  > authority, initiate live operations, or resume
  > implementation during this review.
  >
  > Return a concise planning assessment containing:
  >
  > - Decision 0018: accept as written or recommended amendments.
  > - OA-21: recommended disposition.
  > - Findings: classification and D1 impact.
  > - D1: current critical path and immediate next commitment.
  > - Human decisions genuinely necessary now.
  >
  > Use the shared Architect selectively if an architectural
  > question requires its expertise.
  >
  > Do not introduce additional planning artifacts or
  > approval processes.
  >
  > Stop for my review before commissioning execution.

- <a id="owner-direction-planning-review-decisions"></a>**2026-11-12: Owner direction: decisions on the product manager's first planning assessment.** Given in the main session in answer to the assessment, verbatim (the paste wrapper is removed):

  > I accept the strategic direction of your assessment.
  >
  > Proceed with the following decisions:
  >
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
  >
  > 2. OA-21
  >
  > Accept the existing decision-0010 same-account threat-model
  > limit as sufficient for this finding.
  >
  > Close OA-21 as nonblocking, retaining the disclosed
  > limitation and reconsideration condition.
  >
  > Do not inspect my personal credentials.
  >
  > 3. Planning and execution
  >
  > Commit P-04.3 as the next offline engineering work package.
  >
  > You own selecting and sequencing this commitment.
  > My approval is not required for routine planning decisions.
  >
  > Hand the commitment to the Engineering Manager using the
  > established planning-to-execution mechanism.
  >
  > The Engineering Manager may perform and publish the
  > authorized offline work under existing permissions.
  >
  > 4. D1 critical path
  >
  > Correct the inaccurate dependency and Owner-action
  > records identified in your assessment.
  >
  > Prepare the proposed plan amendments:
  >
  > - E-05.1 depends on P-04.3.
  > - Move the first-model-call authorization requirement
  >   to the actual first-model-call boundary, without
  >   weakening the requirement.
  >
  > Do not apply amendments requiring authority that has
  > not yet been delegated.
  >
  > 5. Authorization enforcement
  >
  > Preserve the distinction between:
  >
  > - Work that is technically ready.
  > - Work that has received necessary authorization.
  > - Work whose authorization is independently enforced.
  >
  > Ask the Program Manager to identify whether any planned
  > D1 operation relies solely on agent instructions for a
  > consequential-effect boundary.
  >
  > Do not automatically initiate a broad security-hardening
  > workstream. Identify only the minimum enforcement needed
  > before the relevant live operation.
  >
  > 6. Reporting
  >
  > Return a concise summary of:
  >
  > - P-04.3 handoff and execution status.
  > - Exact decision 0018 amendments ready for review.
  > - OA-21 disposition.
  > - D1 critical-path corrections.
  > - Remaining authorization-enforcement gaps that
  >   materially affect D1.
  >
  > Do not authorize or initiate new live operations,
  > credential access, external egress, or spending.
  >
  > Do not resume unrelated CI work.

- <a id="owner-direction-distribution-requirements"></a>**2026-11-12: Owner direction: distribution and onboarding requirements.** Given in the main session during the product manager's planning pass, verbatim (the paste wrapper is removed):

  > Additional product requirements for the five-role
  > AI Engineering Harness migration:
  >
  > The agent definitions and skills currently appear to
  > depend on my user-level Claude Code configuration.
  >
  > A fresh clone of the public harness repository must
  > be able to reproduce the required agent environment
  > without relying on my machine's prior setup.
  >
  > The README must also provide an AI-first onboarding
  > experience, including a default setup prompt that a
  > new user can give Claude Code or Codex immediately
  > after cloning the repository.
  >
  > The bootstrap process must work before specialized
  > harness agents and skills are installed.
  >
  > Please incorporate these requirements into your
  > current planning work.
  >
  > Specifically:
  >
  > 1. Determine which agents and skills are development
  >    tooling versus installed harness runtime components.
  >
  > 2. Inspect existing distribution, dependency pinning,
  >    installation, and projection mechanisms.
  >
  > 3. Recommend the simplest reproducible installation
  >    approach, preserving canonical upstream sources
  >    and avoiding duplicate maintained definitions.
  >
  > 4. Ensure installation and upgrades preserve unrelated
  >    user settings, agents, skills, and customizations.
  >
  > 5. Define the README onboarding workflow:
  >    clone, install Claude Code or Codex, open the repo,
  >    provide one setup instruction, and let the AI
  >    perform and verify installation.
  >
  > 6. Consult the shared Architect for distribution design
  >    and the Program Manager for milestone placement.
  >
  > 7. Classify these as explicit product acceptance
  >    requirements. Determine whether they block D1
  >    or belong to the next distribution milestone.
  >
  > Do not interrupt or redo work already underway.
  >
  > You may make straightforward README improvements
  > within existing permissions. For substantive changes
  > to installation architecture, prepare a proposal
  > and execution commitment.
  >
  > Do not initiate new live operations, credential access,
  > external egress, spending, or unrelated CI work.
  >
  > Include the distribution assessment and proposed
  > next steps in your existing final report.
  >
  > Do not describe the five-role migration as fully
  > reproducible until a fresh installation is verified.

- <a id="owner-direction-knowledge-promotion"></a>**2026-11-12: Owner direction: knowledge-promotion assessment of local agent memories.** Given in the main session during the product manager's planning pass, verbatim (the paste wrapper is removed):

  > One additional requirement for the agent distribution and
  > onboarding assessment already underway:
  >
  > Our local Claude Code agent memories contain substantial
  > engineering experience accumulated while building the
  > AI Engineering Harness.
  >
  > Some of this knowledge should benefit other users installing
  > the system. Other information is historical, obsolete,
  > project-specific, machine-specific, or private.
  >
  > Perform a read-only knowledge-promotion assessment.
  >
  > 1. Inventory the relevant local agent memories.
  >
  > 2. Classify reusable knowledge by its appropriate home:
  >    - Agent definitions: stable responsibilities and boundaries.
  >    - Skills: reusable procedures, methods, and expertise.
  >    - AGENTS.md and Claude/Codex instructions: shared rules.
  >    - Architecture and decisions: durable technical knowledge.
  >    - Planning records: current objectives and dependencies.
  >    - Evidence: historical observations and verification.
  >    - Local configuration or memory: machine-specific state.
  >
  > 3. Identify valuable engineering methodologies that are
  >    missing from the distributable system.
  >
  > 4. Reconcile proposed promotions against existing definitions,
  >    skills, instructions, decisions, and evidence. Avoid
  >    duplication and conflicting sources of authority.
  >
  > 5. Verify conclusions against current repository evidence.
  >    Treat memories as potentially stale observations, not
  >    authoritative requirements.
  >
  > 6. Identify obsolete information and sensitive local data.
  >    Do not publish personal information, credentials, local
  >    paths, or raw memory files.
  >
  > 7. Recommend a lightweight, repeatable process for promoting
  >    useful lessons into version-controlled project knowledge.
  >
  > Do not modify or delete local memories.
  > Do not publish or change agent definitions or skills yet.
  > Do not interrupt implementation already authorized.
  >
  > Integrate the findings into your existing distribution
  > assessment rather than creating a separate project.
  >
  > Report the significant reusable knowledge, its proposed
  > destination, any gaps in the distributed agent environment,
  > and the minimum work needed to make it available to new
  > users.
  >
  > Keep the first integrated D1 demonstration as the delivery
  > priority unless a genuine prerequisite is identified.

- <a id="findings-classified-2026-11-12"></a>**2026-11-12: The three findings classified, and D1's consequential boundaries reconciled with their enforcement (planning).** By the program manager (dispatches 1 and 2 of the product manager's planning pass, read-only), weighed by the product manager, who spot-checked the cited code. This answers the Owner's direction (items 3 and 5).
  - **Finding 1, agent-catalog suite failures.** No action in this repository. No proof here depends on the Owner's agent-catalog repository. In the plan, "agent catalog" means the harness's own `catalog_pins`, which is a different thing. The failures belong in that repository's own records. D1 impact: none.
  - **Finding 2, readiness ignores Owner gates.** A misleading planning signal, not an authorization bypass. Nothing reads `plan_commitment.py`'s "ready" except its own tests, the Taskfile target and the documentation. The tool only prints. It becomes a deferral (OA-28 item 4.1). Until then, each commitment entry states its leaves' readiness as three facts: technically ready, authorized, independently enforced. D1 impact: none.
  - **Finding 3, instruction-only safeguards.** No D1 proof depends on (a) to (d). They become deferrals with reconsider conditions (OA-28 items 4.2 to 4.4). D1 impact: none on any proof.
  - **D1's consequential boundaries, by enforcement at the moment of the act.**
    - *Mechanical:*
      - the recorder decisions (OA-23, OA-24), through the recorder's single-use challenge and, once P-04.3 passes, `load_manifest`'s refusals;
      - the content dispatched (the resolver, then P-04.3);
      - the provider key's existence (A1: only the Owner has it).
    - *Bounded independently* (instruction-only authorization accepted as a disclosed limit under decision 0010 point 1 and decision 0013 point 6):
      - the broker's loopback listeners, the forward and the guest hardening change (OA-12 A2 to A4 = OA-22 (a), (b), (c), (e));
      - the bot-credential reads (OA-26), whose tokens have scoped rights and cannot merge;
      - demo-repository content in a disposable guest with egress denied (OA-22 (i));
      - demo-repository provisioning, and the bot push and pull request on the offline, loopback Gitea (OA-22 (f), (h));
      - the dispatch edge (OA-22 (d)).
    - *Instruction only, consequential:* the broker's real-provider start (S-03.3 step 6c, and E-05.5's model calls). Spend, external egress and the provider key all depend on `inference_broker.py serve`, which checks no authorization. The origin and models come from an unbound `config.yml`, and there is no cumulative cap. **Minimum enforcement before the first real-key run:**
      - a fail-closed start precondition bound to a recorder receipt for the provider envelope: proposed leaf S-03.5, OA-28 item 3;
      - the presentation of OA-12 states how the provider enforces the spending cap on the dedicated key; where it does not, S-03.5's broker-side cap applies.
      - Nothing else is required before a live D1 act. No broader hardening workstream is started.
  - **Also recorded.**
    - `tools/guest.py`'s `--real-key-act` is a label, not a check. This is a disclosed limit, which S-03.5's receipt can later back.
    - A1 is best presented together with A6, in the session that performs step 6c, so that the key exists only from the authorized run onward.
    - E-01.3.3's custody probe is the first live traversal of edge `nm-dispatcher-agent-server`, so it needs OA-22 item (d). OA-22's Blocks column and the E-01.3.3 row say so.

- <a id="commitment-p-04-3"></a>**2026-11-12: Commitment: P-04.3 (an offline increment of D1).** Terminal leaf **P-04.3**, "Promote approved dispatch inputs through recorded decisions"; acceptance is its proof, unchanged. Selected by the product manager under the Owner's direction of 2026-11-12, item 3 (verbatim above: "Commit P-04.3 as the next offline engineering work package. You own selecting and sequencing this commitment."). Committed set, from `task plan:commitment -- P-04.3` at the commit that records this entry: 42 leaves, 41 passed, 1 open (P-04.3, not started, ready). It lies inside [Commitment: D1](#commitment-d1), which stands with E-05.5 as its terminal leaf.
  - **Why this leaf.** It is the only open D1 leaf that is ready and needs no Owner act. Its artifact supplies the design-acceptance decision kind and the manifest promotion that E-05.1, E-01.3.2 and E-05.3 need.
  - **Scope: offline only.** The proof is met with fixtures in a throwaway store. No live manifest is written and no live Owner record is made. No guest, live Gitea, credential access, network, egress or spending. The first live promotion is OA-24's.
  - **Contract with later leaves (planning).** Each recorded decision names its deciding authority. Until decision 0018 revision 2 (OA-27) is accepted, the only authority built is the Owner's, through the recorder's challenge (decision 0012). The record shape must not foreclose a decision delegated by an accepted decision record (decision 0008 point 2). No delegated path is enabled before that acceptance.
  - **Readiness of D1's open leaves, kept as three separate facts (the Owner's direction, item 5).**
    - *Technically ready* (`plan_commitment.py`): S-03.1, P-04.3, E-05.1, E-01.3.3.
    - *Authorized* (no Owner act outstanding): P-04.3 only. S-03.1 waits on OA-12, or on OA-28 if that amendment is approved. E-05.1 waits on OA-22 (h) and (i), OA-23, OA-24 and OA-25. E-01.3.3's probe waits on OA-26 and OA-22 (d).
    - *Independently enforced* (the authorization checked by a mechanism at the moment of the act): see the classification entry below. P-04.3 crosses no gated boundary.
  - **Handoff.** Execution takes P-04.3 next. The engineering manager may perform and publish this authorized offline work under existing permissions (the Owner's direction, item 3). The planning records of this pass are committed locally for the handoff and are published with execution's first checkpoint push. Nothing else on the D1 path is handed over.

- <a id="distribution-assessment-2026-11-12"></a>**2026-11-12: Distribution and knowledge-promotion assessment (planning).** On the Owner's two directions above. The shared architect was consulted twice (gates B, C and F; advisory): once for the distribution design, once for a read-only audit of the in-checkout agent memory. The program manager placed the work. The product manager weighed both and spot-checked the key facts.
  - **Classification.** The requirements are product acceptance requirements of a separate milestone, **DS1**. They are **not D1 prerequisites**: no D1 proof reads project-scope agents, the onboarding text, the agent catalog or memory content. D1 stays the delivery priority. Development tooling (the five roles and their skills, canonical in the Owner's catalog) is kept apart from harness runtime content (`catalog/`, which reaches agents only through `catalog_pins`). This is [decision 0019](../decisions/0019-development-agent-environment-distribution-and-knowledge-promotion.md) (Proposed).
  - **Recommended approach.** The repository pins the catalog's published projection in a lock. A stdlib installer verifies it and places it byte-exact in the clone's ignored project scope. It never writes user scope or settings files, refuses paths it did not place, and upgrades by a reviewed lock bump.
  - **Rejected alternatives.** A plugin marketplace: namespaced names, and state in the user-level store. A submodule. Vendored copies. Re-projecting here, which would create a second adapter.
  - **Plan and work.** The work is group F-11 ([proposal](DS1-plan-amendment-proposal.md)), and the Owner acts are OA-29. **The five-role environment is not reproducible from a fresh clone today, and is not described as reproducible until E2 to E5 are verified.**
  - **Onboarding.** README "Getting started" now carries a default setup instruction that uses only the existing Quick start and needs nothing installed first (`cee138f`, within existing permissions). The `AGENTS.md` Setup section waits for OA-29 (i).
  - **Memory audit** (counts and categories only; no memory file read into a record, changed or removed):
    - The in-checkout store holds 75 lessons, all under the retired agent name `engineering-builder`. The current `engineer` store is empty, so the role rename cut the working engineer off from them.
    - Half restate upstream behaviour already held in evidence and decisions.
    - Thirteen lessons are worth promoting. They give six methods the distributable system lacks: proving a test can fail; rehearsing a live act offline; amending integrity-tracked plan files reproducibly; Windows shell and edit hygiene; ending background work; memory discipline.
    - The store also holds perishable data (commit identifiers, timings, scratch pointers) and sensitive local data (personal and machine paths, another project's name). It stays local, and the gate already refuses its directory.
    - The promotion process is decision 0019 point 10. The first batch is F-11.5, OA-29 (i) and the Owner's catalog.
  - **One D1-path exposure, resolved.** Applying OA-28 needs the plan's exact serialization. The rules are derived from tracked files and history, and are recorded in the D1 proposal ("Applying it"), so no memory read is needed. A mechanical agreement check is a deferral (OA-28 item 4.5).
  - **Disclosed.** In the first consultation the architect wrote one lesson file to its own memory, a store outside this repository. It wrote nothing in the second. The user-level memory stores were not read, because no path was authorized.

- <a id="owner-direction-finalize-0018"></a>**2026-11-12: Owner direction: finalize decision 0018 revision 2.** Given in the main session in answer to the planning report, verbatim (the paste wrapper is removed):

  > I have reviewed your planning report.
  >
  > The strategic direction is accepted:
  >
  > - D1 remains the immediate integration objective.
  > - DS1 is a separate distribution milestone.
  > - P-04.3 is the next offline execution commitment.
  > - S-03.5 addresses a genuine consequential-effect
  >   enforcement gap and should remain on the path
  >   before live provider access.
  > - Reusable local-memory knowledge should be promoted
  >   selectively, not copied wholesale.
  > - No additional Owner decisions should be requested
  >   merely for ordinary planning or engineering work.
  >
  > Before execution resumes, I want to finalize
  > decision 0018 revision 2.
  >
  > Present its exact proposed delegation and reserved-
  > boundary language, including the changes from revision 1.
  >
  > Evaluate it against my intended operating model:
  >
  > I provide intent, constraints, and feedback.
  > The AI owns refinement, planning, architecture,
  > implementation, verification, and delivery.
  >
  > Human authorization is reserved for genuinely
  > consequential effects that exceed existing permissions.
  >
  > Avoid requiring my approval for:
  > - Ordinary plan and acceptance-criteria refinement.
  > - Architectural decisions within accepted constraints.
  > - Milestone selection and prioritization.
  > - Routine use of harness-managed credentials.
  > - Design acceptance within committed scope.
  > - Manifest promotion within an authorized envelope.
  > - Routine publication within existing permissions.
  >
  > Preserve independently enforced boundaries for
  > credentials, spending, external effects, protected
  > merges, destructive operations, and privileged changes.
  >
  > Identify any remaining language in decision 0018
  > that unnecessarily transfers operational decisions
  > back to me.
  >
  > Also distinguish decisions that require my authorization
  > under CURRENT accepted policy from decisions that can
  > be delegated once 0018 is accepted.
  >
  > Do not implement or activate decision 0018 yet.
  > Do not begin execution or initiate live operations.
  >
  > Return a concise recommendation and the exact decision
  > wording needing my acceptance.
  >
  > Stop for review.

- <a id="owner-direction-0018-model-selection-correction"></a>**2026-11-12: Owner direction: decision 0018 revision 3 accepted in principle, subject to the model-selection correction.** Given in the main session in answer to the presentation of revision 3, verbatim (the paste wrapper is removed):

  > I accept the five-role operating model and the delegation
  > principles in decision 0018 revision 3, subject to one
  > required correction before activation.
  >
  > The clause stating that presentation of exact model
  > identifiers satisfies an existing requirement for Owner
  > approval is not acceptable as written.
  >
  > My intent is to delegate technical model selection within
  > an explicitly authorized provider, spending envelope,
  > and permitted external effects.
  >
  > Reconcile S-03.3 and related acceptance criteria through
  > the established integrity process so that they explicitly
  > reflect this delegation.
  >
  > Do not reinterpret an unsatisfied approval requirement
  > as satisfied merely by presenting information.
  >
  > Preserve:
  > - Verified model identifiers and intended uses.
  > - Presentation of expected cost characteristics.
  > - Provider authorization and spending limits.
  > - Credential custody and external egress controls.
  > - Independent enforcement of consequential boundaries.
  >
  > Make the smallest necessary correction to decision 0018
  > and its associated acceptance requirements.
  >
  > Verify that the resulting records are consistent and
  > that no unrelated criterion or security requirement
  > has been weakened.
  >
  > Present the corrected exact wording and identify any
  > remaining inconsistencies.
  >
  > Do not activate expanded delegation, begin execution,
  > or initiate live operations until this correction is
  > verified and I have explicitly accepted the final record.
  >
  > Keep P-04.3 committed and ready for execution.
  >
  > Stop after reporting the correction for final acceptance.

- <a id="owner-acceptance-0018-rev4"></a>**2026-11-12: Owner acceptance: decision 0018 revision 4, and OA-28 item 5 with item 3.** Given in the main session in answer to the presentation of revision 4, verbatim (the paste wrapper is removed):

  > I accept decision 0018 revision 4 as presented.
  >
  > This is my explicit authorization to adopt its
  > five-role operating model, delegated responsibilities,
  > reserved boundaries, and standing-authorization
  > semantics.
  >
  > My intent is for the AI system to own ordinary product
  > planning, architecture, engineering decisions,
  > implementation, verification, and delivery.
  >
  > I retain authority over the consequential effects
  > reserved by decision 0018.
  >
  > I also approve OA-28 item 5, together with its
  > required dependency on item 3.
  >
  > Specifically:
  >
  > - Technical model selection is delegated to the
  >   Engineering Manager within an explicitly authorized
  >   provider, spending, egress, and data-exposure envelope.
  >
  > - Exact model identifiers, including secondary models,
  >   must be verified against current provider information,
  >   recorded with their intended uses and expected costs,
  >   and presented before the first paid call.
  >
  > - The S-03.3 acceptance criteria may be amended exactly
  >   as proposed in OA-28 item 5, through the existing
  >   integrity process.
  >
  > - S-03.5 must independently enforce the provider
  >   envelope and admitted model selection before the
  >   inference broker starts.
  >
  > - No provider credential, spending, external egress,
  >   first model call, or other reserved live effect is
  >   authorized by this statement.
  >
  > Apply decision 0018 and its documented consequences.
  > Reconcile the affected acceptance criteria and working
  > documents without weakening other requirements.
  >
  > Under the newly accepted delegation, resolve the
  > remaining OA-28 planning items autonomously.
  >
  > Preserve all existing security and authorization
  > enforcement.
  >
  > Publish the verified planning changes through the
  > established publication process.
  >
  > Then complete the P-04.3 execution handoff and report
  > the next genuine D1 blockers and required human acts.
  >
  > Do not initiate new live operations, credential access,
  > external egress, or spending.
  >
  > Stop at the planning-to-execution boundary.

- <a id="decision-0018-applied-2026-11-12"></a>**2026-11-12: Decision 0018 accepted and applied; OA-28 applied; D1 readiness (planning).** On the [Owner's acceptance](#owner-acceptance-0018-rev4) above.
  - **Applied.**
    - Decision 0018 is Accepted (Owner), revision 4, with a "Current facts" section.
    - `security/inventory.json`: `op-policy-change` and `op-git-push-public` record the point-3 delegations. Both stay Owner-only for everything outside them.
    - `CLAUDE.md`'s "Owner statements" and "Who decides what" rules point to decision 0018.
    - Working documents (the S-03.3 slice plan, slice 5's live driver, the S-03.1 request) carry a dated reconciliation note. Their historical text is marked, not rewritten, and the Owner's approval of the exact routes is kept.
  - **The plan amendment (OA-28), through the integrity process.**
    1. E-05.1 depends on P-04.3.
    2. The Owner's authorization before the first model call moves, unweakened, from S-03.1 to S-03.3.
    3. New leaf **S-03.5**; S-03.3 depends on it.
    4. Five deferrals.
    5. S-03.3's model identifiers are reconciled with decision 0018 point 3.
    - **Method:** the projections were regenerated by rules shown first to reproduce the tracked files byte for byte: the JSON, all 173 prompts, the CSV, planData, card order and search text, and the cards of every touched leaf. The amendment was run first in a throwaway clone and then in the checkout, with identical bytes. `verify_seed` PASS: 174 leaves, 184 seeded files.
  - **Delegated decisions made in this pass** (decision 0018 point 3; listed for the D1 milestone report). All are the product manager's.
    - OA-28 items 1 to 4.
    - S-03.5 placed in phase 0 (I0) with its S-03 siblings (the proposal had said phase 1), priority P0, deps S-03.1, P-04.2 and P-04.3.
    - From the independent review (program manager), before publication: S-03.5 added to S-03's child list; S-03.5 and S-03.3 moved after P-04.3 in the work order and the projections, so no leaf precedes a dependency; the Owner's authorization of the broker design for model use added to the proofs of S-03.4 and K-02.2, which reach S-03.1 but not S-03.3, so moving S-03.1's clause drops the gate for no leaf. S-03.5's phase sits before its phase-1 dependencies; this is disclosed in the amendment entry.
    - OA-23, OA-24 and OA-26 closed as delegated.
    - OA-22 gains item (j), the D1 manifest envelope.
    - The S-03.5 notes state that its envelope receipt is the Owner's authorization of A5 and A6 under OA-12, not a new Owner act.
  - **Contract for P-04.3 (planning), updated.** With decision 0018 accepted, a recorded decision names its deciding authority: the Owner, through the recorder's challenge, or decision 0018's point-3 delegation, naming the commitment or envelope it rests on. P-04.3 builds both kinds for design acceptance and manifest promotion. S-03.5 uses the delegated kind for the model selection. P-04.3's proof is unchanged.
  - **D1 readiness at this commit, kept as three facts.** Committed set 58 (46 passed, 12 open).
    - *Technically ready:* S-03.1, P-04.3, E-01.3.3.
    - *Authorized (no Owner act outstanding):* P-04.3. S-03.1's proof now needs no Owner act: its design passes or fails on its own, and the engineering manager decides the verdict. E-01.3.3's probe needs OA-22 (d).
    - *Independently enforced:* P-04.3 crosses no gated boundary. S-03.5, once built, enforces the provider envelope and model selection at broker start.

- <a id="p-04-3-verdict-2026-11-13"></a>**2026-11-13: P-04.3 PASS; decision 0020 Accepted (engineering manager); findings for planning (execution).** The engineering manager's verdict on the [commitment](#commitment-p-04-3), under decision 0018 point 1.
  - **Proof, clause by clause** (evidence `evidence/P-04.3-dispatch-input-decisions.md`, section 2; my independent re-runs of the owner and dispatch suites after each slice, with `AIEH_DATA_ROOT` pointed at an absent directory that stayed absent): an entry written without a recorded decision and a digest other than the decided one are refused by `load_manifest` (`MANIFEST_NOT_PROMOTED`, `MANIFEST_DIGEST_MISMATCH`); a design entry without a design-acceptance record is refused (`DESIGN_ACCEPTANCE_MISSING`, at the act and at load); a replayed decision is refused (`DECISION_REPLAYED`, `CHALLENGE_CONSUMED`, `CHALLENGE_STALE`); a manifest promoted through a recorded decision bound to its digest loads, and each of its entries names its approving record. The P-04 gate's clause "never minted, approved or merged by a model" holds for Owner records: a delegated decision is a separate format, refused by the Owner record's check.
  - **Independent review** (a fresh engineer, decision 0018 point 1): findings F1 to F11, then a re-review (N-A to N-D). Fixed forward: F1 (a delegated basis must be an anchored, dated entry of its type: `Commitment:`, or `Owner standing authorization:` with the quote inside the Owner's verbatim block), F2 and F3 (the series walk at load; the gap above the manifest's version documented), F4 (the provenance guard), F5 (every surviving mutant named by the review killed, except M29, trivial), F6 (documentation), F7 (crash paths), F8 (`OWNER_ACCEPTANCE_HEAD`, decision 0018 point 4.8), F11 (the exact status prefix), N-A, N-B, N-D. **N-C**, my disposition: no change; the paired checks (M10 with N7, N24 with the digest comparison) each fail closed alone.
  - **Delegated decisions made under decision 0018 (engineering manager's, listed for the D1 milestone report):** the S-03.1 verdict (row above); the architect's P-04.3 work design accepted with rulings R1 to R8 (R1: "each of its entries names its approving record" is read on the loaded manifest, schema v1 kept; R2: the guard in `resolve` and `admit`; R3: the commands as a module of the authorization recorder; R5: S-03.5 adds a delegation row without a format change; R6: the engineering manager never promotes; R7: `PROMOTION_UNRESOLVED`; R8: path refusals first); the review rulings F1 to F8, F11 and N-A to N-D above; decision 0020 accepted (point 3.1); the inventory operations `op-design-acceptance` and `op-manifest-promotion` and the asset `store-approved-inputs` recorded, with their policy entries mirroring `op-protected-merge` (`policy/role-tokens.json`: granted to the `owner` role only, denied to every role that denies `op-protected-merge`; `policy/network-matrix.json`: asset class `management`, as `store-integration`) - record-keeping and a narrowing, no edge, principal, credential class or token scope added, so not a widening (point 4.7); the 0012 Current-facts note.
  - **For planning (none blocks P-04.3; each the product manager's unless stated):**
    1. *F9, exposed-by-decision-0018-acceptance:* P-04.3's action still says "only through a recorded Owner decision ... in the shared Owner decision-record shape"; since decision 0018 a delegated decision also promotes, in `delegated-decision/v1`. The proof is neutral. A wording correction through the integrity process.
    2. *OA-22 item (j):* a delegated promotion now needs the Owner's grant recorded as an entry titled `<date>: Owner standing authorization: ...`, anchored, with the Owner's words verbatim as a `>` block (decision 0020 point 7); the session in which the Owner grants it records it so. Presenting (j) as a typed list would make containment mechanical; granting it through the recorder would make the grant itself enforced.
    3. *E-05.1's clause "The OpenSpec change has a design-acceptance record (decision 0008)":* the record is held by the recorder and names the change at its exact revision; no file goes into the change folder (decision 0020 point 9.1).
    4. *F10, exposed-by-P-04.3:* `integration_store.reconcile(oracle)` runs over every unknown attempt and a restore epoch moves every dispatched attempt to unknown, so the recorders' receipts (P-04.2's and P-04.3's) could be settled by E-01.4.x's OpenHands oracle. The leaf that builds that reconcile driver must make the oracle answer indeterminate outside its own key namespace, or reconcile filter by prefix. To be placed.
    5. *Unrelated-but-detected (architect):* `integration_store.default_db_path`, `task store:path`, the store README's "Location" and `docs/development.md` name the former default store location, while the managed contexts open `<state>/integration/integration.sqlite`. The live driver (E-01.3.2) must use the latter (decision 0020 point 6).
    6. *Test-runtime signals (diagnostic only):* owner suite median about 10.3 s against 4.6 s recorded (P-04.3's integration tests); unit category about 46 s against 24.5 s; gitea about 5.1 s against 2.4 s (untouched). No gate.
  - **Disclosed.** The engineer wrote two memory files of its own under the checkout's ignored `.claude/` directory (its standing memory instruction), unstaged; nothing else there was read or listed. The architect read three of its own memory files before applying the brief's protection line, and wrote none. A first full test run had one load-sensitive lineage timing failure while a mutation job ran; the quiet rerun passed all 13 suites.

- <a id="s-03-5-verdict-2026-11-13"></a>**2026-11-13: S-03.5 PASS; decision 0021 Accepted (engineering manager); findings for planning (execution).** The engineering manager's verdict, under decision 0018 point 1.
  - **Proof, clause by clause** (evidence `evidence/S-03.5-provider-envelope-authorization.md`; my independent re-runs of the inference and owner suites after each slice, `AIEH_DATA_ROOT` pointed at an absent directory that stayed absent): `serve` refuses, before it opens a listener or reads the provider key, a non-loopback family without the confirmed, unexpired receipt whose operation is the provider envelope and whose target is the live envelope's canonical digest; missing, expired, replayed and mismatched receipts (origin, limit, digest) are refused with stable codes; the model selection is either in the envelope's digest or a delegated record under decision 0018 point 3 naming the envelope's receipt, and one with neither authority, missing or naming another receipt is refused at start, and a request for an unselected model is refused; a broker-enforced envelope carries a cumulative cap that fails closed when reached or when usage is unknown; loopback fake upstreams start as today.
  - **Independent review** (a fresh engineer, decision 0018 point 1): one blocking finding, F1 (a request on a keep-alive connection after the close receipt was relayed and never counted: the cap failed open), fixed in `01c970d` (`BROKER_STOPPING` for metered brokers, set under the lock before the close counts are read; a race of eight threads against the stop accounted every upstream write); F2, F3 (untested branches; E11's wrong refusal code fixed), F5 to F7 (documentation) fixed; F4 no change. The re-review closed all of them with no new finding.
  - **Delegated decisions (engineering manager's, listed for the D1 milestone report):** the architect's S-03.5 work design accepted with rulings R1 to R11 (R1 replay is supersession by a later authorization; R2 the envelope is a projection of the served configuration; R3 the canonical manifest bound at start; R4 no loopback family names the envelope's provider; R5 both selection authorities, kind `select-models`, the engineering manager only; R6 a complete non-2xx answer counts zero toward the cap, an assumption about provider billing to verify at OA-12's presentation; R7 a per-run ledger, the per-request ledger rejected with a reconsider condition; R8 a closed envelope reopens only by a new authorization; R9 expiry at admission, supersession at the next start; R10 the minted-object guard; R11 the `envelope` command); the review rulings; the existing-assertion changes allowed (the egress census and one module list gain `delegated_decision`; the interim cap test asserts the real unknown case; the delegated-kinds list gains `select-models`); decision 0021 accepted (point 3.1); the inventory and policy records (`op-model-selection` mirroring `op-protected-merge`; the broker's start precondition on `op-inference-call` and edge `nm-ext-broker-provider`; record-keeping and a narrowing, point 4.7); the Current-facts notes on 0012, 0015 and 0020.
  - **For planning and for OA-12's presentation (none blocks S-03.5):**
    1. *OA-22 (g)* says the cap's authorization "expires at D1's acceptance"; the envelope needs a date (`expires_at`), so OA-12 must present one.
    2. *The first real envelope manifest's repository:* the recorder admits only the S-01.2.2 fixture repository today, and G-03.1 is not a dependency of S-03.3; which repository carries the first real provider-envelope manifest is open.
    3. *Decision 0018 point 3's "what may be sent to it"* is not a member of the envelope, and the broker cannot check it; it stays the Owner's stated condition.
    4. *Decision 0015 section 2.2* asks for a provider-side cap. If OA-12's presentation says the provider does not enforce the limit on the dedicated key, an `enforced_by: broker` envelope is the Owner choosing the fallback; one transient TLS or certificate failure, or any stop that is not the broker's clean stop, then closes the envelope until a new authorization.
    5. *The envelope does not bind which key* (the credential entry); the key's custody stays decision 0015's.
    6. *Decision 0015's Status* still reads "Proposed, amended"; S-03.3's proof requires the Owner's authorization of the broker design for model use (OA-12), unchanged.
    7. *Carried to S-03.3 (engineering, mine):* the per-request model check reads the body's top-level `model` for the three declared families; a family that names a model elsewhere needs its own check before it is declared.
  - **Disclosed.** The S-03.5 engineer ran one `grep -r` from the repository root during slice 1, which traversed the ignored `.claude/` directory (no match, nothing printed); later dispatches required `git grep` or named paths. A refused start in the managed context may create an empty integration store.

- <a id="owner-direction-testing-governance"></a>**2026-11-13: Owner direction: simplify testing governance.** Given in the main session during the engineering manager's execution session, verbatim (the paste wrapper is removed):

  > Owner direction: simplify testing governance.
  >
  > I no longer want test execution-time budgets,
  > timing ratios, or performance baselines enforced
  > as mandatory engineering gates.
  >
  > Our testing policy should prioritize:
  > - Correctness and deterministic assertions.
  > - Fast unit tests using isolated fixtures.
  > - Focused integration and contract tests.
  > - Parallel execution where safe.
  > - Functional timeouts that catch hangs.
  > - Security and resource-boundary verification.
  >
  > Performance is a diagnostic concern. If tests become
  > unacceptably slow, we can profile and optimize them
  > as a separate engineering improvement.
  >
  > For the current S-03.3 work:
  >
  > 1. Do not repeat successful budget checks or
  >    unchanged test suites unnecessarily.
  >
  > 2. Complete the current correctness review and
  >    required acceptance evidence.
  >
  > 3. Do not bypass any currently binding integrity
  >    or publication gate. If a time-budget gate is
  >    mandatory, satisfy it for this checkpoint.
  >
  > 4. Record my direction for the Product Manager to
  >    update the testing policy and remove mandatory
  >    performance-budget enforcement through the
  >    established process.
  >
  > 5. Do not start that cleanup during S-03.3.
  >    Keep D1 integration as the priority.
  >
  > Finish the current committed work and publish
  > the verified checkpoint.
  >
  > No additional Owner approval is required for
  > ordinary testing-policy implementation decisions
  > within decision 0018's delegation.

  - **For the product manager (item 4; not started by execution, item 5):** update the testing policy (`docs/development.md`'s testing sections, `policy/test-budgets.json`, `tools/check_test_budget.py`'s role as the "acceptance obligation" at leaf acceptance, and any test that asserts a timing ratio or wall-time bound as a pass/fail condition, such as the lineage suite's `test_traversal_git.OneTraversal.test_one_traversal_of_the_two_task_example`) through the established process, so that no execution-time budget, timing ratio or performance baseline is a mandatory gate, keeping the deterministic checks (the recorded test set: no failing, removed or newly skipped test; categories; unit isolation) and functional timeouts. The Owner states that ordinary testing-policy implementation decisions within decision 0018's delegation need no further Owner approval.
  - **Execution's application now (items 1 to 3):** no repeated budget checks or unchanged suites; the publication gate and the integrity checks stay binding; the budget check's wall-time results were already notes only, and its binding part (the recorded test set) last passed at `01ff496`.

- <a id="s-03-3-offline-2026-11-13"></a>**2026-11-13: S-03.3 offline work complete; rulings D-1 to D-5 and F7 (execution).** By the engineering manager under decision 0018 point 1 (the slice plan's decisions D-1 to D-5, "decisions to present", are engineering decisions inside committed scope since decision 0018). S-03.3 stays IN PROGRESS: only its live steps remain.
  - **Rulings.** D-1: the provider's code is read from the pinned image only (option (a), already done); option (b), an npm pin in `composition/`, is not taken. D-2: `acp_command: ["claude-agent-acp"]`, as built in slice 2. D-4: the broker's refused-request audit as built (method, path, query parameter names, the requested `model`; no values, no bodies). D-5: the real-key search reads the key from the broker's own credential entry, in memory only; its live use is covered only by the Owner's act A1, and A1's presentation must say so. F7 (carried from S-03.5): option (b), the discovery fake upstream records request-body key names only (open maps collapsed unless a name contains "model"), and the proposed-pin reader flags `MODEL_KEY_ELSEWHERE`; the broker and its audit are unchanged.
  - **Fix-forwards outside S-03.3's own code (classified exposed-by-review):** `load_manifest`'s checkout guard (P-04.3, E-01.2.1) and the managed root's in-checkout guard (F-07.1, decision 0009) compared Windows path forms lexically, so the `\\?\` and trailing-space forms of a path inside the checkout passed; one shared comparison (`aieh_paths.inside_or_around`) now serves both and the proposal's `--out`. No refusal code or order changed; two forms are newly refused, correctly. A test made flaky (one run in 64) by the new real-key search tests was fixed forward.
  - **Known duplication, kept (my disposition):** `tools/guest.py`'s `read_real_provider_key` and `inference_real_key_search.read_entry_key` read the same entry; unifying them would change the driver's recorded refusal codes; reconsider when the driver is next changed.
  - **For planning:** the lineage suite's `test_traversal_git.OneTraversal.test_one_traversal_of_the_two_task_example` timing-ratio test fails under parallel load (it failed twice in this session's full runs while other work loaded the host, and passed on each quiet rerun); unrelated-but-detected, not in the committed set; a candidate for its own leaf or a deferral.

- <a id="e-05-2-offline-2026-11-13"></a>**2026-11-13: E-05.2 built offline; a D1 blocker for planning (execution).** By the engineering manager. E-05.2 stays IN PROGRESS (row above): its verdict waits for S-03.3's qualified template and the checked-in profile's pin.
  - **For planning (a genuine D1 blocker, discovered work with no owner):** the real D1 create needs the inference attempt token and the endpoint as `secrets` (`StaticSecret`s; decision 0015 amendment 1, item 2; S-03.3's qualification create carries them), but E-01.2.2's body allowlist refuses `secrets` (`BODY_FIELD_UNKNOWN`), and no leaf from E-05.1 to E-05.5 adds them; the general case is A-01.2's, which is outside D1's committed set. E-05.5 cannot pass without them. Planning to place it: a new D1 leaf carved from A-01.2 for the D1 stage (as E-05.2 was), or a re-homed clause.
  - **Engineering sequencing recorded:** when the real template is pinned, the live drills (`live_admitted_create.py`) and E-01.3.2's disposable bare-agent attempt on `implement` move to the ACP template; E-01.3.2's dispatch must account for that, and a re-promotion of any live manifest follows the profile's new sha256 (decision 0020).

- <a id="planning-pass-2026-11-13"></a>**2026-11-13: Planning pass: the D1 create's secrets, D1's authorization ledger, the testing policy, and execution's findings (planning).** By the product manager, on the engineering manager's PLANNING REQUIRED at `cfda343` ([blocker](#e-05-2-offline-2026-11-13)) and the Owner's [testing-governance direction](#owner-direction-testing-governance). Program manager dispatch 1 (read-only validation and placement) and dispatch 2 (the plan amendment, `bbbad04` (fix-forward `3a4af34`)). One architect consultation, gates G and F (the authorization ledger). The product manager spot-checked the cited code: `dispatch_inputs.BODY_FIELDS`, `AdmittedCreate.to_json`, `admitted_policies`, `managed_context`, and the input and selection recorders' imports. [Commitment: D1](#commitment-d1) stands, with E-05.5 as its terminal leaf.
  - **The blocker, validated and wider than raised (observed):**
    - The create's `secrets` are required by decision 0015 amendment 1 item 2, refused by E-01.2.2's allowlist, and owned by no D1 leaf.
    - A-01.2's proof never named `secrets`. The general obligation lived only in S-03.3's notes and decision 0015's note.
    - No D1 leaf issued or revoked the attempt token for a real attempt (decision 0015 section 3.3). Only S-03.3's qualification driver uses the broker's `issue` and `revoke`.
    - `AdmittedCreate.to_json()` emits the full body, so a filled token would reach any record built from it.
  - **Placed (decision 0018 point 3, the program manager's challenge):** new leaf **E-05.6** "Admit the D1 stage's create secrets: the attempt's inference token and endpoint", carved from A-01.2 for the D1 stage only, as E-05.2 was.
    - Deps: E-01.2.2 and E-01.3.1 (both PASS). E-05.5 gains it.
    - Its proof holds every custody boundary:
      - exactly the registry's two names, StaticSecret only, `secrets_encrypted` false;
      - a token bound to the reserved attempt, and the profile's endpoint;
      - refusal at admit and again at `send_create`;
      - one check shared with S-03.3's admission, not a copy;
      - issuance only after reservation, and revocation on failure and at attempt end;
      - no record carries the token, only its fingerprint;
      - the dispatcher reads no provider credential.
    - A-01.2's proof is unchanged; its notes now name the per-stage `secrets` block.
    - Rejected:
      - a re-homed clause in E-05.2, E-01.3.2, E-01.3.3 or E-05.5: each artifact passes honestly without it, and E-05.2's or E-05.5's would lengthen the critical path;
      - pulling in A-01.2 (and with it A-01.1): too large, against the carve precedent;
      - reusing the qualification admission as-is: it is disposable-only and bypasses E-01.2.2.
    - Dependency challenge, my ruling: E-05.6 does not depend on E-05.2. The two meet at E-05.5. E-05.6's proof is shown on E-05.2's committed `stage_create_template` mechanism with the candidate template.
  - **Discovered and placed: D1's authorization ledger.** The architect's consultation corrected the premise:
    - only the Owner's provider-envelope authorization needs a Gitea merge;
    - design acceptance, manifest promotion and model selection are integration-store receipts (decision 0020);
    - the managed recorder admits only the S-01.2.2 fixture.
    [Decision 0022](../decisions/0022-authorization-repository-the-one-ledger-provisioned-for-d1.md) (Accepted, product manager) puts real authorizations in one dedicated authorization repository, G-03.1's own repository provisioned early, and never in the fixture. Its new leaf is **E-05.7**, carved from G-03.1:
    - deps P-04.2 and S-01.2.2 (both PASS);
    - S-03.3 gains it, for step 6b only, as does G-03.1;
    - the offline build is ready now; the live half is the new Owner act **OA-30**.
    Rejected: the fixture (decision 0022, option 1).
  - **Testing policy (the Owner's direction of 2026-11-13; implementation decisions delegated in its last line).**
    - Inventory, by the program manager:
      - The wall times and counters of the test check have been notes, never failures, since 2026-11-11.
      - Still timing-based:
        - F-10.3's proof (the 4x and 8x ratios);
        - the F-10 group gate's "performance criteria";
        - decision 0014's ratio and its 150 s F-09 criterion;
        - one lineage test asserting a timing ratio, which is load-flaky;
        - three serial runs of the test check at leaf acceptance, needed only to compare wall medians.
    - Disposition:
      - **(a)** The amendment `bbbad04` (fix-forward `3a4af34`) records those timings as diagnostics in F-10.3's proof and the F-10 gate, by the Owner's direction ("timing ratios", "performance baselines").
      - **(b)** New leaf **F-09.5**, P1 (the plan defines only P0 and P1), deps F-09.1 and F-10.3, ready offline. It turns the lineage ratios into recorded diagnostics (the equality assertions kept). It makes one profiled run the test check's default at leaf acceptance, its blocking findings exactly the deterministic set. It keeps the three-run determinism comparison for release, and states in `docs/development.md` and the Taskfile that no execution-time budget, ratio or baseline is a gate. No new budget gate.
      - **(c)** A Current-facts note on decision 0014.
    - Kept:
      - the recorded test set (no failing, removed or newly skipped test), categories and unit isolation;
      - R-05.4.1's release check, which is deterministic;
      - functional hang timeouts (the lineage `<60` s and planning `<30` s checks);
      - resource ceilings, security and authorization tests;
      - the integrity and publication gates;
      - independent review.
    - **Not a D1 prerequisite** (computed: no D1-set proof names the test check or a timing bound). F-09.5 is outside D1's set and adds no dependency to any D1 leaf. It is placed after S-03.3 in the work orders (Owner item 5), and execution orders it below D1's ready work.
    - Until F-09.5 lands, a load-induced failure of the lineage ratio test is a known diagnostic flake, not a regression.
  - **Execution's findings, classified:**
    1. *P-04.3's action wording (F9):* corrected in the amendment (an Owner decision, or a decision delegated by an accepted record in `delegated-decision/v1`). Proof unchanged.
    2. *E-05.1's design-acceptance record:* no proof change. A note added: the record is held by the recorder at the change's exact revision, and no file goes in the change folder (decision 0020 point 9.1).
    3. *F10, reconcile settling recorder receipts:* a criterion added to E-01.4.1, which builds the reconcile driver: its oracle answers indeterminate outside its own key namespace. It is outside D1's set, and `reconcile` has no caller outside tests (observed).
    4. *The stale default store path:* unrelated-but-detected, an engineering fix-forward of ordinary files (the engineering manager's). Carried as a dispatch constraint: E-01.3.2's live driver uses `<state>/integration/integration.sqlite` (decision 0020 point 6).
    5. *OA-12's presentation and outstanding authorizations:* the queue rows are updated (below). OA-14 and OA-16 move to Resolved; their rows were stale (an architect observation).
  - **Engineering notes carried to dispatches (not criteria):**
    - When E-01.3.2's attempt moves to the ACP template, if an ACP create without credentials cannot start, raise it as a blocker. E-01.3.2's proof passes with a credential-free create, so no dependency is added.
    - The ownership sentences in `inference_control.py` and `inference/README.md` ("A-01.2, E-03.1") are updated with E-05.6.
  - **D1 after the amendment** (`task plan:commitment -- E-05.5` at `bbbad04` (fix-forward `3a4af34`)): 60 leaves, 49 passed, 11 open, 5 ready, 6 blocked (was 58, 49, 9, 3, 6). The critical path is unchanged:
    - OA-12 and OA-22 (a)(b)(c)(e) → S-03.2 live → S-03.3 live (with E-05.7 and OA-30 before step 6b; E-05.7 runs in parallel with S-03.2 and adds no leaf to the path, only OA-30) → E-05.2 → E-05.3 → E-05.5;
    - in parallel, E-01.3.3 (OA-22 (d)) → E-01.3.2 → E-05.4 → E-05.5, and E-05.1 (OA-25, OA-22 (h)(i)) → E-05.5;
    - E-05.6 is off the critical path.
  - **Readiness, three facts:**
    - *Technically ready:* S-03.2, E-05.7, E-05.1, E-01.3.3, E-05.6.
    - *Authorized (no Owner act outstanding):*
      - offline: E-05.6 and E-05.7's offline build;
      - live: none. S-03.2's guest qualification waits on OA-12/OA-22 (a)-(c)(e); E-01.3.3's probe on OA-22 (d); E-05.1 on OA-25 and OA-22 (h)(i); E-05.7's live half on OA-30.
    - *Independently enforced:* E-05.6's custody checks are mechanical at admit and send, and its broker revocation shows in the grant's state. E-05.7's admission is mechanical (`REPOSITORY_NOT_ADMITTED`), and the ledger's protection is checked by the OA-16 verifier.
  - **Minimum Owner acts for live D1** (each separately answerable; none is asked in this pass, and none is granted until the Owner answers in the session that performs it):
    1. **OA-25**: name the D1 change and the demo repository (intent).
    2. **OA-12**, with OA-22 (a), (b), (c) and (e): the authorization of decision 0015's broker design for model use; the provider envelope (provider and egress origin, the spending limit with an `expires_at` date, and who enforces the cap: the provider, or the Owner choosing `enforced_by: broker` with its close-on-unclean-stop consequence), recorded through the recorder on the E-05.7 ledger; A1, the key, with A6, the first model call. The presentation also states:
       - whether a non-2xx answer bills zero (R6);
       - that "what may be sent" stays the Owner's unenforced condition;
       - that the envelope does not bind which key;
       - the engineering manager's model record (presented, not approved);
       - that the real-key search reads the key in memory under A1 only.
    3. **OA-30**: the authorization repository's creation, its collaborations (a stated widening under decision 0018 point 4.7), and its first read-only verification. Optionally, the Owner may confirm or have enabled Gitea's `[audit]` setting; D1 does not rely on it (decision 0022).
    4. **OA-22**, as a standing authorization recorded in an anchored `<date>: Owner standing authorization:` entry with a verbatim `>` block (decision 0020 point 7):
       - (d), which is OA-07's dispatch-path approval;
       - (f) and (g), stating that they include the dispatcher's issuance and revocation of each attempt's inference token (E-05.6);
       - (h) and (i);
       - (j), the manifest envelope for the product manager's promotions.
    5. Not needed: OA-23, OA-24 and OA-26 (delegated 2026-11-12); OA-07's Owner UI connection (D1 does not use it).
  - **Delegated decisions made in this pass (for the D1 milestone report):** E-05.6 and its dependency ruling; E-05.7 and S-03.3's and G-03.1's dependency on it; decision 0022 accepted (point 3.1); the testing-policy amendment, F-09.5 and the decision 0014 note (under the Owner's direction); the P-04.3, E-05.1, A-01.2 and E-01.4.1 changes; the queue reconciliation.
  - **Handoff.** Execution takes, among ready committed work, E-05.6 and E-05.7's offline build. Neither needs an Owner act, and neither is on the critical path, so they can proceed while the Owner considers OA-12, OA-22, OA-25 and OA-30. F-09.5 is ready outside D1, below D1's work. These planning records are committed locally for the handoff and are published with execution's next checkpoint push.

- <a id="e-05-6-verdict-2026-11-13"></a>**2026-11-13: E-05.6 PASS (engineering manager).** The engineering manager's verdict, under decision 0018 point 1. Evidence: [E-05.6](E-05.6-d1-stage-create-secrets.md); commits `aa32a87`, `c6b90c8`, `d5fcbd7`, `4966416`, `8d47cac`, `b977105`, `44a83ab`, and this record.
  - **Verdict basis.** Every clause of the proof is shown offline, by construction: on E-05.2's committed `stage_create_template` mechanism, with a test template (the candidate's sentinel model is never a model) and the real inference broker in process (control listener on loopback, no upstream contacted), as planning's [placement](#planning-pass-2026-11-13) says. Each clause is traced to its tests in the evidence; the dispatch and inference suites passed after the last code change, the whole run twice during the leaf. Independently reviewed in three passes: the first pass's findings 1 to 8 and the second pass's A, B and C fixed, D no change; the third pass found no blocking or should-fix finding, N1 and N5 fixed, N2 to N4 accepted residuals (the evidence states them).
  - **Delegated engineering decisions (decision 0018 point 3; for the D1 milestone report):**
    1. One shared check, `integrations/dispatch/create_secrets.py`, for S-03.3's qualification admission and the D1 stage; the token-fragment threshold is 8 characters (48 bits of the URL-safe alphabet).
    2. The pinned stage template carries no secrets; admission adds them, the token's value a slot filled only in memory at the send.
    3. The per-attempt grant budgets are declared as `provisioning.agent_server.stage_create_template.inference_grant {requests, tokens, ttl_s}`, with no default in code.
    4. One family constant, `acp_qualification.ACP_FAMILY = anthropic-messages` (`tools/guest.py` reads it).
    5. The broker's control listener revokes by conversation and attempt as well as by fingerprint, and tombstones an attempt revoked before its grant registers (`GRANT_ATTEMPT_REVOKED`). No architect consultation: the same listener and the same revoker principal; it only narrows authority and adds no trust edge.
    6. `GuestTransport` seals any body carrying secrets (standard input, never a command line).
    7. A grant journal; revocation on any `BaseException` after the issue; `end_attempt` for an attempt in any state; `GRANT_REVOKED` before each transport call.
  - **Carried notes for planning (not criteria):**
    1. S-03.3 must decide whether Claude Code's secondary model joins the grant's model list (today exactly `[acp_model]`).
    2. E-01.4.1's reconciliation must settle the dispatcher's grant-journal and revocation receipts by `end_attempt`, not by the OpenHands oracle: they are outside the conversation key namespace and, left unsettled, hold a restore epoch open.
    3. OA-12's presentation includes the per-attempt `inference_grant` values.
  - **Records:** decision 0015 gains a "Current facts (2026-11-13, E-05.6)" note (no change to decided text); `security/inventory.json` and `security/README.md` update `cred-inference-attempt-token` and `api-inference-control` for E-05.6 (status `planned`: offline only).

- <a id="e-05-7-offline-2026-11-13"></a>**2026-11-13: E-05.7 offline build complete; verdict waits OA-30 (engineering manager).** Evidence: [E-05.7 offline](E-05.7-authorization-repository-offline.md); commits `1903d6c`, `9c53029`, `d25d9ae`, `5657358`, `fa02e3d`, `05520d9`, `02fc9c4`, `73639f4`, `2dd731e`, and this record. Every offline clause of the proof is shown on the Gitea fakes and throwaway stores and traced to its tests in the evidence. The live clauses are NOT RUN: they are Owner act OA-30. Independently reviewed in two passes. In the first, findings 1 to 7 were fixed and 8 accepted. In the second, findings 1 to 4 were fixed and 5 is a residual. The fixture's baseline is unchanged (`sha256:5dd7ace780ca0878146915ed74e8761b432e4489f20cdfe9a243804ad5aa6e42`, recomputed by the reviewer on the trees before and after the change); the one changed fixture assertion is the auditor's reach.
  - **Delegated engineering decisions (decision 0018 point 3; for the D1 milestone report):**
    1. The authorization repository's name is `aieh-authorization/authorizations`, a private organization of its own (decision 0022 point 1: chosen by the engineering manager before OA-30's presentation).
    2. Admission by explicit admitted sets per context: `managed_policies` (the ledger alone) for the command line; `exercise_policies` (the fixture alone) for exercise contexts; `admitted_policies` removed.
    3. One protection declaration per repository (`gitea_roles.DECLARATIONS`). The ledger's equals the fixture's but for the name.
    4. The proposal act, with bot tokens only: the builder bot proposes and the reviewer bot approves, the approval read back. It never merges. A differing read-back is `DIGEST_CHANGED`. It runs as `task owner:propose`.
    5. OA-30's module, `gitea_roles.py authorization-repository --owner-act OA-30`. It runs every check that does not depend on the new repository before the first write, records its writes in order, and prints a stop report on every stop.
  - **Residuals:**
    - The proposal act's scans are bounded: 50 open pull requests, 100 pages of files each, refused beyond.
    - The two declarations share the rule functions until G-03.1 changes the ledger's.
    - In D1 one session drives both the proposing and the reviewing bot (decision 0022).
  - **Next act:** OA-30 is now prepared; see its row in the Owner-actions queue. The verdict follows the act and its read-only check.
- <a id="owner-authorization-oa-30-2026-11-13"></a>**2026-11-13: Owner authorization: OA-30**, given in the main (engineering manager) session after the D1 execution report presented OA-30 as prepared; transcribed verbatim by the engineering manager (decision 0018 point 7). It authorizes OA-30 parts (a), (b) and (c) as worded below; part (d), Gitea's `[audit]` setting, is not named and stays unauthorized. Verbatim:

  > Owner decision: OA-30 APPROVED.
  >
  > I authorize the narrowly scoped creation and
  > configuration of the dedicated authorization repository:
  >
  > aieh-authorization/authorizations
  >
  > The authorization covers:
  >
  > 1. Creating this repository in the existing local Gitea
  >    instance.
  >
  > 2. Granting the protection auditor the administrative
  >    permissions specified by decision 0022.
  >
  > 3. Granting the four existing bot identities only their
  >    declared permissions for this repository.
  >
  > 4. Granting aieh-owner the protected-branch merge
  >    authority required by the authorization recorder.
  >
  > 5. Applying the existing branch-protection requirements.
  >
  > 6. Performing the read-only verification and recording
  >    the observed protection baseline.
  >
  > This authorization does not permit:
  > - Creating additional repositories.
  > - Widening permissions beyond the approved declaration.
  > - Changing existing repositories' permissions.
  > - Making model calls or incurring provider spending.
  > - Creating or modifying provider credentials.
  > - Expanding network access.
  > - Merging an authorization proposal without a separate
  >   valid Owner decision.
  >
  > Execute OA-30 using the implemented E-05.7 procedure.
  >
  > Use the established recorder and evidence requirements.
  > Verify the actual Gitea state rather than relying on
  > the administrative command's success response.
  >
  > If the observed configuration differs from the approved
  > declaration, stop and report the discrepancy rather
  > than broadening permissions.
  >
  > Complete E-05.7's remaining live acceptance criteria,
  > record the verdict, and publish the verified checkpoint
  > through the established publication gate.
  >
  > Do not initiate OA-12, OA-22, or any other reserved
  > Owner operation.
  >
  > Report the outcome and the next D1 authorization
  > boundary.

- <a id="e-05-7-verdict-2026-11-13"></a>**2026-11-13: E-05.7 PASS (engineering manager).** The engineering manager's verdict, under decision 0018 point 1. Evidence: [E-05.7](E-05.7-authorization-repository-offline.md); commits `1903d6c`, `9c53029`, `d25d9ae`, `5657358`, `fa02e3d`, `05520d9`, `02fc9c4`, `73639f4`, `2dd731e`, the records `ddb257d` and `48fae7c`, and this record.
  - **Verdict basis.**
    - Every offline clause of the proof is shown on the Gitea fakes and throwaway stores ([offline build](#e-05-7-offline-2026-11-13)), independently reviewed in two passes.
    - The live half is Owner act OA-30, on the Owner's authorization ([verbatim](#owner-authorization-oa-30-2026-11-13); parts (a) to (c); (d) not authorized). `<tools python> -I -B integrations/gitea/gitea_roles.py authorization-repository --owner-act OA-30` ran once from the main session, 2026-11-13T21:18:53Z to 21:18:55Z, exit 0, I7 clean:
      - twelve writes, each 2xx; basic authentication only; the administrator's tokens `[]` before and after; no token minted;
      - recorder receipts `[]`;
      - read-back differences `[]`;
      - `pulls` 0 and `head_parents` 0, from the act's own GETs of the actual state;
      - the protection check `verified` as the auditor;
      - the fixture `verified` with `sha256:5dd7ace780ca0878146915ed74e8761b432e4489f20cdfe9a243804ad5aa6e42` before and after.
    - The reviewer then confirmed, read-only, as the auditor: the authorization repository `verified` with the same digest and the fixture `verified` with its recorded baseline (both exit 0, problems `[]`); an offline field-by-field comparison of the read-back with the declaration: 131 comparisons, 0 differences.
    - Nothing else was done on the repository: no merge, proposal, negative control or drift injection, and no change to the fixture, an account, a token, a scope or `app.ini`.
  - **Recorded baseline** of the authorization repository `aieh-authorization/authorizations`: `sha256:041510d5330eb44a5a063afa9abfe9a6f0e340b6d357a9c46bfcd3e81341837f`.
  - **What it unblocks.** S-03.3 step 6b's recording carrier now exists: the managed recorder admits this repository alone, and the proposal act (`task owner:propose`) opens its pull requests. The provider-envelope authorization itself remains OA-12's.
  - **Records:** OA-30 moved to Resolved in the queue; `security/inventory.json`, `security/README.md`, `policy/role-tokens.json` and its generated tables in `policy/README.md` updated (`repo-gitea-authorization` and `op-protection-verify` `observed`; `op-gitea-administration` gains the act; the auditor's reach and `fd-owner-authorization-record`); the Gitea and owner READMEs and `docs/development.md` state the act as performed.
- <a id="owner-direction-provider-access-2026-11-13"></a>**2026-11-13: Owner direction: provider access for D1 without harness spending enforcement.** Given in the main (engineering manager) session while the engineering manager prepared the OA-12 with OA-22 (a), (b), (c) and (e) package; transcribed verbatim by the engineering manager (decision 0018 point 7; the paste wrapper is removed). It is direction, not an authorization: no act of OA-12 or OA-22 is granted by it. Its reconciliation with S-03.5, decision 0021 and the leaves that rely on them is the product manager's, as the Owner directs. Verbatim:

  > Owner clarification for OA-12 and D1:
  >
  > Do not implement or require harness-enforced spending
  > limits, cumulative usage accounting, or budget-based
  > model-call rejection.
  >
  > I accept that provider limits, exhausted credits,
  > rate limits, and authentication failures may interrupt
  > execution. Continuous availability is not a requirement.
  >
  > The desired behavior is to preserve durable Work state
  > and resume safely when provider access becomes available.
  >
  > Claude Code already provides session resumption.
  > Reuse that capability wherever applicable, and verify
  > the equivalent recovery contract for contained
  > OpenHands execution.
  >
  > Keep the broker responsible for:
  > - Provider credential custody.
  > - Approved provider destinations.
  > - Isolation and network restrictions.
  > - Attempt identity and authorization.
  > - Security-relevant audit evidence.
  >
  > Do not remove those security boundaries.
  >
  > The existing S-03.5 spending machinery should not
  > be expanded. Have the Product Manager reconcile its
  > requirements and acceptance criteria with this Owner
  > direction, including any necessary change to previously
  > accepted decisions.
  >
  > For OA-12, recommend the smallest provider-access
  > authorization needed for D1. Pricing research may
  > inform model selection, but do not ask me to choose
  > a budget, expiry date, or spending-enforcement mechanism.
  >
  > Do not interrupt or restart completed engineering work.
  > Continue preparing the D1 authorization proposal under
  > these revised requirements.
- <a id="oa-12-package-2026-11-13"></a>**2026-11-13: OA-12 with OA-22 (a), (b), (c), (e) prepared as one package; findings for planning (execution).** By the engineering manager, on the Owner's request for one decision-ready package and under the Owner's [direction on provider access](#owner-direction-provider-access-2026-11-13). Package: [OA-12-OA-22-provider-access-package.md](OA-12-OA-22-provider-access-package.md). Nothing performed; no Owner act granted.
  - **Work done:** provider facts verified 2026-11-13 against the provider's live documentation (models, prices, deprecations, workspace limits, error shapes; Claude Code's gateway protocol); a read-only fact sheet of the mechanics as built; an architecture consultation, gates G and C (and B and G, advisory, for planning); a read-only investigation of recovery after a provider interruption.
  - **Engineering decisions under decision 0018 point 3 (delegated, presented, not approved):** provider Anthropic (first-party), origin `https://api.anthropic.com:443`; route bound `POST /v1/messages`, with no query or exactly `beta=true`, pinning only the form observed at S-03.3 6a (`count_tokens` and `/v1/models` stay refused); models `claude-sonnet-5` (primary) and `claude-haiku-4-5` in its observed form (Claude Code's background model), with `selection: delegation`; broker ports 18431 (control) and 18432 (inference); `expires_at` `2027-01-31T23:59:59Z` as a security validity window, not a spending term; the D1 grant's model list becomes primary plus secondary.
  - **Architect's findings accepted (fix-forward, mine, offline, before the live acts they gate):**
    1. **Defect, exposed by this preparation:** `serve`, the qualification launcher, `discover` and `fake-upstream` wait with `threading.Event().wait()`, which SIGINT did not interrupt on CPython 3.12.10 (Windows), so only a kill stops them and `discover` never writes its proposal. Repair: an interruptible wait and a stop from a session with no console; required before A2 goes live.
    2. The broker refuses provider-side reach (server-tool `tools[]` types, `mcp_servers`, URL-sourced content, `container`). This is already decided by decision 0015 amendment 1 item 7 and S-03.3's clause.
    3. The broker never forwards an account-scope header (`anthropic-workspace-id`).
    4. The route grammar gains exact whole-query equality.
    5. The key-entry command gets a hidden prompt, under the architect's seven conditions.
    6. A live census of the broker's listeners and outbound connections, which 0015 section 4.5 and S-03.2 assume and `host-census` lacks.
    7. Record corrections: A1 is pasted, not typed; Moby `dns` is not optional; the inventory's stale "Proposed" for 0021; the proposal act missing from the envelope steps.
  - **PLANNING REQUIRED (the product manager, per the direction):**
    - (1) **S-03.5 and decision 0021:** the envelope's `limit` (drop it in a new canonical format, or a declared placeholder); keep the start precondition, the manifest binding, the selection and `expires_at`.
    - (2) **Per-attempt budgets** (0015 section 6.3, E-05.6 `inference_grant`): `requests` and `tokens` retired or non-binding; `BUDGET_USAGE_UNKNOWN`, which closes an attempt's token for good after one usage-less or cut-off 2xx, needs a decision and a code change; the never-built per-day budget retired.
    - (3) **The recovery contract.** Investigation gaps, none in a D1 leaf unless stated:
      - G1: that close-for-good rule.
      - G2: no re-grant to an existing conversation; a broker restart drops grants.
      - G3: provider and broker refusals share statuses.
      - G4: no execution-state record after `confirmed`.
      - G5: no `/run` or resume act (sending E-05.5's message is in E-05.5).
      - G6: a new attempt is a new conversation.
      - G7: the OA-03 `running` to `error` quiesce; event retention is in E-01.4.2, outside D1.
      - G8: no record of Claude Code or ACP retry, or of `session/load` and resume, in the pinned adapter 0.63.0.
      - G9: provider-failure status unobserved.
      - G10: interrupted work lost at `destroy` (E-05.4 returns on success only).
    - (4) **Wording to change:** E-05.5's "authorized cap", S-03.3's and S-03.5's proofs, OA-22 (g) and its stop "the cap reached"; fold D1's model calls into the OA-12 approval.
    - (5) **Accepted texts to amend:** 0018 points 3 and 8 (Owner-accepted), 0015 (sections 2.2, 3.1, 3.3, 6.3, 8, amendment 1 item 1, Current facts item 3), 0021 (title and sections 1, 3, 4, 6, 7, 9.4).
  - **Not verified:** anything live; the provider-side feature list is from the provider's API reference of 2026-11-03, not re-read today; the interrupt measurement used SIGINT through the C runtime, not a console Ctrl-C.

## Owner-directed maintenance items (no plan leaf covers these)

| Item | Scope | Sequencing |
|---|---|---|
| M-1 | Reconcile the blueprint with decision 0001 and verified upstream behavior, preserving the decision's provenance. Update the blueprint's integrity metadata through the versioned process F-02 introduces. | **Done (2026-11-06), `e1ed236`; pushed.** 8 passages reconciled, each with a visible note linking decision 0001, plus a Reconciliation notes entry. The 31 October observations made at v1.58.2 are kept as history; forward-looking requirements are restated. The blueprint's sha256 and size are updated in `SEED_MANIFEST.json` in the same commit. Both verify modes pass; the 105 element ids are unchanged; style and script blocks are byte-identical. Overseer reviewed the word diff and independently ran both modes. Recorded but not changed: v1.57.0 release-note statements, and the claim that runtime never falls back to local, which is checkable only with docker inspect (owned by E-01.3.1 and E-01.5). |
| M-2 | Reconcile blueprint `#platforms` and SHIP-01 wording, which reads WSL2 as a peer of a VM, with SEC-01 and decision 0003's tiers. Use the authority-class process. | **Done (2026-11-09), `d7fbd86`.** Two passages reconciled, each with a visible note linking decision 0003 and SEC-01 (`#proof-SEC-01`): the `#platforms` "Engineering isolation" Windows cell (formerly "Linux container via WSL2 or container VM") and `#proof-SHIP-01` (formerly "behind Windows WSL2/VM"), plus a Reconciliation notes entry after M-1's. Native WSL2 is stated as an explicitly weaker option for trusted workloads only, never a strong-tier provider; decision 0003's nested candidate (KVM inside a dedicated WSL2 distro, rank 5) is not contradicted. The upstream OpenHands WSL2 observation is kept. No selection or isolation requirement changed. The blueprint's sha256 and size are updated in `SEED_MANIFEST.json` in the same commit. Overseer verification: verify_seed PASS (164; seed baseline 136); the diff touches 2 passages and 1 note (5 lines); the Builder parsed the HTML (105 ids unchanged and in order, every in-page link resolves, 12 elements added, none removed) and ran the tools suite OK. |
| M-3 | Reconcile the `#platforms` "Engineering isolation" Linux cell ("Native Linux container sandbox") and SHIP-01's "or Linux Engine as needed", which present a host container as the Linux isolation boundary, with SEC-01's Linux row (a QEMU/KVM VM) and decision 0003 (Incus VMs are the Linux strong tier; Incus containers count as trusted-workload). Wording only; the authority-class process. Found during M-2 (detected, not changed). | **Done (2026-11-09), `01842b5`.** Approved by the Owner (2026-11-09; Decisions). The `#platforms` Linux cell now reads: "Linux container inside a managed Linux VM: QEMU/KVM, as Incus virtual-machine instances (strong tier); a container that shares the host kernel, whether hardened host Docker or an Incus container, is an explicitly weaker option for trusted workloads only and never a strong-tier provider". `#proof-SHIP-01` names a managed Linux VM on Linux, with the same trusted-workload-only sentence. Each passage has a visible note linking decision 0003 and `#proof-SEC-01`, and a Reconciliation notes entry follows M-2's. No selection, requirement or implemented isolation architecture changed. The blueprint's sha256 and size are updated in `SEED_MANIFEST.json` in the same commit. **Overseer verification:** verify_seed PASS (165 after the amendment; seed baseline 136); the word diff read; the Builder parsed the HTML (105 ids unchanged and in order, 123 in-page links resolve, the style and script blocks are byte-identical, 13 elements added and none removed). |
| M-4 | Reconcile the blueprint with decision 0012: step 16 of the Owner's sequence (`#sequence-maps`, the diagram label and the table row; the plan cites it as `#experience` step 16) becomes "Owner -> authorization recorder -> Gitea": the Owner decides on the exact manifest the recorder presents, as a challenge bound to the head and digest, and the recorder records the decision and merges exactly that head as `aieh-owner` (the Owner's authority, not his person); a chat click is still not the authorization. The `#decisions` "Owner merges" step becomes "only `aieh-owner` can merge to the protected authorization branch, and only the recorder, on a recorded Owner decision, merges as it; no agent, reviewer, CI or other automation merges". Consistency wording in `#authority` and `#authorization-qualification` where they name the Owner's own Gitea act. Wording only; the authority-class process. Proposed at P-04.2. | **Done (2026-11-10), `31a7f8b`.** Approved by the Owner (OA-15b). Five passages reconciled, each with a visible note linking decision 0012: step 16 in `#sequence-maps` (the diagram's title and the table row; actor "Owner -> authorization recorder -> Gitea"; the Owner decides on the exact manifest presented as a one-time challenge bound to the head and digest, his own authorization is recorded, the deterministic recorder merges exactly that head as `aieh-owner` after a fail-closed verification of the required protection settings, and no model or agent may manufacture an Owner decision; the AUTHORITY tag kept), the `#decisions` lane ("Owner authorizes; recorder merges"), and two `#authorization-qualification` passages; plus a Reconciliation notes entry after M-3's. No mechanism, identity or credential for the protection check is named (OA-16 open). No selection or requirement changed. The blueprint's sha256 and size updated in `SEED_MANIFEST.json`. **Overseer verification:** verify_seed PASS (167; seed baseline 136); the per-passage diffs read; the Builder parsed the HTML (105 ids unchanged and in order, 126 in-page links resolve, style and script blocks byte-identical, 19 elements added, none removed) and ran the tools suite OK. Detected, not changed: further passages outside M-4's named sections (M-5). |
| M-5 | Reconcile the remaining blueprint passages that still present the Owner's own Gitea merge as the authorization act, found during M-4 (detected, not changed): `#decisions` "What the Owner sees" ("Recommended: merge to activate", a link opening the Gitea PR); `#sequence-maps` governance step 14 ("Owner / Curator -> Gitea Catalog: ... separately authenticated merge", AUTHORITY tag "Owner merge of operation SHA"); `#practical-workflows` ("Review approval without Owner merge is not authority"; "Owner merges an exact operation manifest to the protected authorization branch"); `#architecture` ("Protected merge is the Owner authorization event"); `#integration-contracts` ("after Owner-only merge"; "Authorization: Owner-only merge rather than a detached approval"); `#control-evidence` ("authenticated Owner merge"); `#rollout` step 04 ("Owner merges only through a protected branch under separate credentials"). Same substance as M-4 (decision 0012; the Owner decides, the recorder merges as `aieh-owner`); wording only; the authority-class process. Step 14 (the catalog) is checked against decision 0012's scope before it is changed. | **Done (2026-11-11), `fee915e`.** Approved by the Owner (OA-18). Ten passages reconciled, each with a visible dated note linking decision 0012: `#decisions` "What the Owner sees" ("Recommended: authorize to activate"; the Owner decides on the recorder's one-time challenge and never signs in to Gitea to merge); `#sequence-maps` governance step 14 (description, the diagram title, and the AUTHORITY tag "Owner-authorized merge of operation SHA"; the lane labels kept); `#practical-workflows` (the authorization journey's Gitea step and failure mode, and the product-update journey); `#architecture`; `#integration-contracts` (table row, panel heading and text); `#control-evidence`; `#rollout` step 04; plus a Reconciliation notes entry. **Step 14 checked against decision 0012's scope:** 0012 covers it (its subject is the authorization of a consequential operation by merging its manifest on the protected authorization branch, 0012 points 1 and 5, and its scope names `#sequence-maps`); 0012 does not cover catalog admission, so governance step 04 ("Protected catalog merge") and code merges (D-01.2) are unchanged and the recorder gains no authority over them. No protection-check mechanism, identity or credential is named. **Overseer verification:** the remaining "Owner merges" and "merge to activate" occurrences are all inside "formerly" notes; ids (105) identical and in order, style and script blocks identical (the Overseer's own parse); verify_seed PASS in both modes. **Overseer rulings:** two passages beyond the row's quoted list (the authorization journey's "Owner reviews and merges the exact operation manifest", the integration-contracts panel's "Owner reviews and merges the exact manifest") are within OA-18 ("Remove remaining instructions requiring the Owner to log into Gitea and merge personally"), accepted and disclosed here; the shared lane labels "Owner / Curator" are kept, since dropping a role by wording could read as an authority change. Detected, not changed: phrases describing the protection rule ("Owner-only merge" in `#architecture`, `#authorization-qualification` and SEC-02) stay true under 0012, `aieh-owner` being the Owner identity |

## Open license and distribution items (owned by G-02.1, R-04.1, R-04.2)

The full list is in `composition/inventory/LEDGER.md`. The most material items are
`lmnr-claude-code-proxy` 0.2.0, declared `LicenseRef-Proprietary` and pulled in by
`openhands-sdk` through `lmnr` (it is also in the Canvas image), and `func-timeout`,
which is LGPL-3.0 (the shipped licence text; package metadata says LGPLv2/2.1; corrected by the 2026-11-06 licensing audit, C8). The lock references these packages and does not redistribute them.

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
