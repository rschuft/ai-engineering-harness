# 0007 - Role-token matrix and revocation contract

Status: Accepted (Overseer) - 2026-11-07, at the completion of S-01.2.1 (`05ad4ff`). It refines decision 0004 within the blueprint and issues, installs or creates nothing. The items under "Owner confirmation" remain pending and are not needed before a Gitea instance exists. Proposed 2026-11-07.
Gate: architecture consultation before S-01.2.1, gate G (the least-privilege boundary
between the Owner, privileged effects and the agent, reviewer and CI roles).
Supersedes: none. It refines [decision 0004](0004-privileged-effect-store-custody-and-restore-semantics.md)
within blueprint `#security`, `#authorization-qualification`, `#governance-architecture`,
`#quality-pipeline` and `#agent-skills`.

## Context
Plan leaf S-01.2.1 must assign distinct scopes to the planner, builder, reviewer, CI,
Owner and executor, and define issuance and revocation. Its acceptance: no agent,
reviewer or CI role has Owner or privileged-effect capability in the documented
mapping. The S-01.1 inventory ([`security/inventory.json`](../security/inventory.json))
names the principals, credentials and privileged operations, and left the rotation and
revocation owners of the planned role credentials undecided.

The blueprint fixes the boundaries this record applies:
- agent credentials may propose PRs but may neither push the protected target, merge
  into it nor change protection settings (`#integration-contracts`,
  `#authorization-qualification`);
- dedicated, least-privileged Gitea bot accounts, restricted job-token maxima, and no
  Owner token or site-administrator secret inside agent workspaces or CI runners
  (`#authorization-qualification`);
- untrusted CI holds no Owner, release or signing secret and no host Docker socket
  (`#quality-pipeline`);
- the launcher and credential broker checks accepted Work, policy, mounts, network and
  provider entitlement before starting an attempt (`#containment-architecture`);
- emergency revocation disables future dispatch and handles active exposures
  explicitly (`#agent-skills`, `#security`);
- rotating privileged credentials is a consequential external effect (`#decisions`).

Today no agent role token exists, Gitea is not installed, no agent workload has run
(decision 0003, C6), and the Owner's account performs every operation that has been
performed.

## Decision
1. **Roles are grants; principals are runtime identities.** A role binds to exactly one
   inventory principal, and a principal may carry several roles. A grant designates an
   inventory operation (`op-*`), a named capability (`cap-*`) or a credential
   (`cred-*`) to a role. No grant is made to a principal that is not independently
   isolated. The host-side bootstrap agents are a non-role row with no grants: they
   inherit the reach of the Owner's account (`fd-bootstrap-shared-identity`), and a
   sunset map names the leaf at which each operation they perform today moves to its
   planned principal: conversation create and runtime control at S-01.3.1 (the
   dispatcher); privileged effects and effect-store custody at G-04.2.1; Gitea
   administration at no installing leaf (a plan gap, routed to the Owner). No
   exclusion flag may remove a row from the acceptance.
2. **Planner.** A role on the existing `engineering-agent` principal, with its own Gitea
   bot identity and token (`cred-gitea-bot-planner`, planned). Its path-level
   realization is pending the planning-artefact layout: a repository-level permission if
   planning artefacts get their own repository, or a required scoped-workflow check on
   PR paths if they are co-located. Gitea token scopes are categorical (to verify at
   S-01.2.2). Its named denials: no merge, protected-ref push, administration or
   protection settings, executor, session key, Docker or Work-status mutation (Backlog
   status belongs to the coordinator).
3. **Release-signing and deployment principal.** It stays `unknown`, with these
   invariants: trusted side only, never `ci-job` or any agent role; its credential is of
   a privileged class; activation goes through `op-effect-apply`; the signing identity
   is distinct from the executor's effect identity unless Q-02.4 decides otherwise.
   Q-02.4 and G-04.2.1 decide it.
4. **Issuance.** The Gitea site administrator issues Gitea identities, bot accounts,
   protection rules and runner registration secrets. The dispatcher (the launcher and
   credential broker) is custodian of the standing bot credentials and delivers each
   agent role token per attempt into the attempt environment only; the token is bounded
   to the attempt where the pinned Gitea supports it (to verify) and is otherwise
   rotated at attempt end. Tokens never go into an image, seed, repository, log or
   record (fingerprints only). Owner-class and executor-class credentials are issued only
   by Owner acts. The executor issues nothing. The inference broker alone issues
   inference access, and no provider credential is ever a role token.
5. **Revocation contract.** Each credential row carries its trigger classes (attempt
   end, suspected exposure, definition revocation, policy revision, expiry, Owner
   direction), its revoker (the issuer's role), its rotation owner, and the common
   effects: new dispatch is refused at once; in flight, the dispatcher stops or contains
   the attempts holding the credential through `op-as-runtime-stop` and records them as
   exposed, Gitea fails closed at the next authenticated call, and CI jobs are
   cancelled. The evidence is a Gitea audit record where enabled, plus a revocation
   receipt in the integration store (fingerprint, role, trigger, revoker, affected
   attempts), never in the effects store unless the revocation was itself an executor
   effect (decision 0004, point 1). Rotating a privileged credential (Owner, admin,
   executor or management class) is a consequential external effect: an Owner-only
   manifest applied by the executor, or during bootstrap an Owner act recorded in the
   bootstrap log. Decided rows: the Agent Server session key is revoked only by guest
   recreate and provision, which ends every conversation; inner conversation keys end
   with their container; the executor identity and target secrets by an Owner elevated
   act (bootstrap) or an Owner-only manifest applied by the executor (target); the Gitea
   administrator credential's rotation owner is the Owner; the provider key is rotated at
   the provider by the Owner and reloaded into the broker only.
6. **Target and bootstrap.** Every role row carries its target scope and its bootstrap
   reality (the observed performer, with evidence). Every realization is unverified and
   is to be verified at S-01.2.2.

The matrix is [`policy/role-tokens.json`](../policy/role-tokens.json), its record is
[`policy/README.md`](../policy/README.md), and
[`tools/check_role_tokens.py`](../tools/check_role_tokens.py) enforces it.

## Consequences
- `policy/` is created.
- The inventory is edited: `cred-gitea-bot-planner` is added; every rotation owner is
  set and `fd-rotation-undecided` is removed; `fd-release-job-principal` records the
  narrowing of point 3 and is carried to Q-02.4; `fd-acp-provider-auth` records that no
  provider credential is a role token and that no plan leaf owns the broker.
- Nothing is issued, installed, created or configured (decision 0004, Owner
  clarification 7).
- S-01.2.2's Gitea-dependent tests need a pinned, disposable Gitea instance that no
  plan leaf provides.
- Agent-held Gitea tokens presuppose a `git-hosting` guest endpoint class or a
  trusted-side push of exchanged bundles. S-01.4 decides the plane, and any guest
  forward is an Owner-only boundary change.
- Carried:
  - Gitea 28.3.0 bot, token-scope, impersonation and job-token behaviour (S-01.2.2);
  - management-API scoping and the operator login's key access (S-01.3.1);
  - the release lane (Q-02.4, G-04.2.1);
  - inference access (no owning leaf).

## Owner confirmation
**Status: resolved** (Overseer reconciliation, 2026-11-09; see "Resolution" below). The text as accepted on 2026-11-07 follows unchanged.

Pending. It is not needed before a Gitea instance exists.
1. During bootstrap, the Owner personally holds the Gitea site-administrator credential
   and a separate, non-administrator Gitea Owner account for protected merges.
2. Where the pinned Gitea instance for S-01.2.2's denial tests runs: host loopback from
   a pinned binary, or a workload in the qualified guest. Each option is a separate
   Owner authorization.
3. Plan gaps to route: no leaf installs Gitea, and no leaf builds the inference broker or
   provides model access.

**Resolution** (Overseer reconciliation, 2026-11-09, Owner-action queue item OA-R2 in
`evidence/bootstrap-log.md`). It records Owner decisions already on record, and adds none:
1. Resolved by the Owner's identity decision, which F-06.1 applied ("Identities, per the
   Owner's decision (resolving 0007 Owner confirmation 1)", the F-06.1 row of the bootstrap
   log; `evidence/F-06.1-gitea-loopback.md` section 7). There are two Gitea accounts:
   `aieh-site-admin` (administrator) and `aieh-owner` (not an administrator). Their final
   passwords are set by S-01.2.2's automated finalization (`63e2628`;
   `evidence/F-06.1-gitea-loopback.md` section 8), so no sign-in by the Owner is needed.
2. Resolved by "2026-11-07: Owner decisions on three plan gaps", item (1) (bootstrap log,
   Decisions): Gitea runs on host loopback from the pinned binary, under the managed data
   root, as the current Windows user, not elevated. That instance is F-06.1.
3. Resolved by the same entry, items (2) to (4): the inference-broker design leaf, the plan
   amendment, and the acceptance-recorder leaf.

## Evidence
- The Architect's gate G consultation for S-01.2.1 (2026-11-07), as accepted by the
  Overseer with amendments: the dispatcher's custody of the standing bot credentials is
  settled by the blueprint's launcher and credential-broker clauses
  (`#containment-architecture`, `#authorization-qualification`,
  `#integration-contracts`) and is not an Owner confirmation item.
- [`policy/role-tokens.json`](../policy/role-tokens.json) and
  `python -I -B tools/check_role_tokens.py` (`task policy:check`), with its tests in
  [`tools/tests/test_check_role_tokens.py`](../tools/tests/test_check_role_tokens.py).
- [`security/inventory.json`](../security/inventory.json) (S-01.1) and
  `python -I -B tools/check_security_inventory.py`.
- Decisions [0003](0003-execution-guest-providers-and-isolation-contract.md),
  [0004](0004-privileged-effect-store-custody-and-restore-semantics.md) (Owner
  clarifications 5 and 7) and
  [0006](0006-guest-provisioning-channel-and-image-conformance.md).

## Current facts (2026-11-08)
Added with the Owner's approval of 2026-11-08 ("add a current-facts note reflecting my
previously supplied confirmations; preserve the original decision history, provenance,
and attribution"). The sections above are unchanged and remain the record of 2026-11-07.
The three "Owner confirmation" items were answered by later Owner decisions, all recorded
in [`evidence/bootstrap-log.md`](../evidence/bootstrap-log.md):
1. **Credential holding.** Superseded by the Owner's directive of 2026-11-07, "no manual
   Gitea credential enrollment". The harness creates and finalizes both identities, the
   site administrator and the non-administrator Owner account `aieh-owner`, and holds their
   credentials in the OS credential provider. The Owner does not sign in to Gitea. The
   Owner also decided on 2026-11-07 to keep `aieh-owner` as the Owner-authority identity,
   used only by the Owner authorization recorder on a recorded Owner decision (P-04.2;
   draft decision 0012).
2. **Where Gitea runs.** Host loopback (127.0.0.1) from the pinned Gitea 28.3.0 Windows
   binary, under the managed data root, without administrator rights and with no second
   VM: the Owner's plan-gap decision and his "external-by-default" directive, both
   2026-11-07. Built and verified by F-06.1.
3. **Plan gaps.** Routed by the Owner on 2026-11-07 and added through the plan amendment
   of that day: F-06.1 installs Gitea; S-03.1 and S-03.2 design and build the inference
   broker (model access); P-04.1 builds the acceptance recorder.

## Amendment 1 (OA-20): credential classes, borrowing and revocation triggers

Added with the Owner's approval of 2026-11-11 (Owner decision OA-20), following the Owner's directions of 2026-11-11
on the E-01.3.3 token lifecycle and on this decision (both verbatim in `evidence/bootstrap-log.md`). Points 4 and
5 above are kept as decided on 2026-11-07, for history and provenance. Where they differ from this amendment, this
amendment governs. The superseded clauses are named exactly below; no other part of the decision changes.

1. **Point 4, superseded:** "delivers each agent role token per attempt into the attempt environment only".
   Decision 0013 point 7 had already relocated the attempt environment to the dispatcher's attempt context.
   **Current requirement:**
   - The standing Gitea bot credentials stay on the trusted host, in the OS credential provider.
   - For a confirmed operation, the dispatcher borrows the stage's mapped credential into its own in-memory
     attempt context. It borrows only that stage's credential and releases the access when the operation ends.
   - A standing Gitea token never enters a guest, an agent environment, a container, a conversation, a
     conversation record or the UI. Records carry fingerprints only.
2. **Point 4, superseded:** "the token is bounded to the attempt where the pinned Gitea supports it (to verify)
   and is otherwise rotated at attempt end".
   - **What was established.** S-01.2.2 verified that Gitea 28.3.0 gives a token no lifetime and that the bots
     have no password. A replacement token can therefore be issued only by the site administrator, never by the
     dispatcher. The Owner's direction of 2026-11-11 rejects routine revocation without an authorized, automatic
     replacement mechanism.
   - **Current requirement:**
     - Releasing the dispatcher's in-memory access at the end of an operation is not Gitea revocation. It is
       recorded as a release.
     - Issuance (point 4), rotation and revocation (point 5, "the issuer's role") of a standing Gitea bot
       credential are the Gitea site administrator's. During bootstrap the administration command performs them
       as the Owner's account.
     - Rotation and revocation happen on the triggers of point 5 as amended in 3 below, never on routine attempt
       completion.
     - The dispatcher holds no administrator credential and issues nothing.
3. **Point 5, narrowed by credential class:** "attempt end" in the list of trigger classes.
   - **Credentials with attempt end as a trigger:** attempt end remains a trigger for credentials issued for a
     single attempt, task or session. Among them:
     - the broker-issued inference attempt token (decision 0015);
     - the inner conversation keys, which end with their container;
     - the CI job and runtime tokens Gitea Actions mints per task;
     - the conversation runtime credential.
   - **Standing Gitea bot credentials:** attempt end is not a trigger for them. They are revoked or rotated only on
     suspected exposure, definition revocation, policy revision, expiry or Owner direction.
   - **Effects of a security-triggered revocation.** Revoking a standing credential keeps all of point 5's common
     effects:
     - new dispatch is refused at once;
     - Gitea fails closed at the next authenticated call, so delivery is refused until the administrator-managed
       lifecycle restores the credential;
     - attempts in flight that hold the credential are stopped or contained and recorded as exposed;
     - CI jobs holding it are cancelled;
     - the evidence is the Gitea audit record where enabled, plus the revocation receipt in the integration store.

Disclosed, not prevented: during bootstrap the Owner's account can read the standing credentials in the
credential provider (decision 0013 point 6).
