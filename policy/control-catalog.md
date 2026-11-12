# Control catalog (G-01.1)

Plan leaf **G-01.1**, "Define minimal versioned control catalog", as of 2026-11-11
(baseline commit `f9cbe0b`). It declares the isolation, credentials, CI, code review,
authorization, evidence and recovery controls, each with its risk applicability and its
enforcing owner, under blueprint `#control-evidence` (11B), `#governance-architecture` (11A)
and `#security`.

- **Acceptance of this leaf:** every required control has an objective subject, an
  enforcement boundary and applicability criteria.
- **Machine-readable form:** [`control-catalog.json`](control-catalog.json). The tables
  below are rendered from it, and
  [`tools/check_control_catalog.py`](../tools/check_control_catalog.py) checks it (`task
  policy:control-check`; see [What the checker enforces](#what-the-checker-enforces)).
- **This catalog defines controls; it is not evidence of enforcement.** A definition states
  an intent to enforce. No control here is assessed: plan leaf G-01.2 links each control to
  its independent evidence sources and to the satisfied, failed, unknown and stale
  interpretation. Until then every control's assessment is **unknown**, and unknown never
  satisfies a control.
- **Status: admitted (2026-11-12).** The Owner signed off revision `808b5bd76d09` of
  `policy/control-catalog.json` (see [Admission](#admission)). Admission is not proof of
  enforcement: that qualification remains G-01.2.

## How to read it

- **A control** has an id (the blueprint's ids where it names one), a category, an
  objective (`purpose`), a subject, its applicability, its enforcement points, its exception
  class, the effect of its failure and its sources. A control is referenced as
  `governance:<control id>@<full commit id of the admitted revision>`.
- **The subject** is typed by the lineage reference kinds of
  [`integrations/lineage/lineage_schema.json`](../integrations/lineage/lineage_schema.json)
  (P-03.1, projected end to end by P-03.2): an agent run is an `attempt`, a pull-request
  revision a `commit`, a consequential operation an `authorization`. A subject is objective
  only when the lineage schema settles its kind's native identity; the `release` kind is not
  settled, which is one reason `REL-01` is deferred.
- **Applicability** names the risk profiles a control applies in and the events that bring it
  into force on a subject. Profiles are additive: `baseline` always applies; `elevated` and
  `consequential` add their controls when their condition on a classification input holds. A
  control listed under `baseline` therefore applies to every subject. An unknown input counts
  as meeting every condition on it (the safer profile), and a transition whose operation type
  is unknown is not performed. No agent can remove a mandatory control.
- **An enforcement point** names the boundary (execution, Git and CI, effect, evidence:
  blueprint `#security` boundaries 3 to 6), the enforcing principal of the
  [security inventory](../security/README.md), the assets it guards and the plan leaves that
  build it. It is the enforcing owner. It is never an agent-controlled principal or a principal
  in an untrusted domain, and never the agent's prompt or instructions. A leaf listed under
  "Built at" may already be complete; whether its mechanism enforces the control is evidence,
  linked at G-01.2.
- **Exception classes:** `prohibited` (a non-waivable identity or containment invariant),
  `scoped` (a separately authorized, time-bounded exception under the exception contract; it
  never turns a failed or unknown assessment into passed) and `unsettled` (the accepted records
  do not settle whether an exception may be granted; until the named leaf settles it, none
  can be). Only the Owner grants an exception, bound to the control, target, reason, residual
  risk, compensating measures and expiry.

## Admission

The Owner is the rule authority: the catalog changes only by the inventory's Owner-only
policy change, `op-policy-change`. Of its two Owner acts, the first is performed:

1. **Sign off this catalog (performed 2026-11-12).** The Owner approves or amends an exact revision of
   `policy/control-catalog.json`. During bootstrap the Overseer transcribes the sign-off
   verbatim into `evidence/bootstrap-log.md`, then sets `admission.status` to `admitted` with
   that quote as `approval`; the checker then requires the quote verbatim in the log.
2. **Move the catalog into the protected Gitea policy repository** (`repo-gitea-policy`,
   planned, not created) once it exists, promoted by the protected catalog merge of blueprint
   `#sequence-maps` governance step 04. The M-5 reconciliation of 2026-11-11 left that step
   unchanged: decision 0012 covers the authorization of consequential operations, not catalog
   admission, and the authorization recorder gains no authority over it (the checker refuses
   an admission naming it). No mechanism for that merge is decided.

## What the checker enforces

`python -I -B tools/check_control_catalog.py` (`task policy:control-check`) exits 0 only when:

1. each of the leaf's seven categories (isolation, credentials, CI, code review,
   authorization, evidence, recovery) has a control, and the categories, boundaries,
   exception classes and classification inputs are exactly the closed sets;
2. every control states its objective, and its subject names lineage reference kinds whose
   native identity is settled, with a scope;
3. every control names the profiles it applies in (all declared) and the events that bring it
   into force; an isolation or credentials control applies in `baseline`;
4. every control names at least one enforcement point with a declared boundary, a mechanism,
   an inventory principal that is not agent-controlled and sits in a trusted,
   trusted-computing-base or contained domain, existing inventory assets and existing plan
   leaves;
5. an isolation or credentials control's exception is `prohibited`, and an `unsettled`
   exception names the plan leaf that settles it;
6. exactly one profile, `baseline`, applies always; every other profile's condition is on a
   declared classification input; and every profile has a control;
7. the rule authority, the exception authority and the admission performer are the principal
   of the inventory's Owner-only `op-policy-change`; the admission never names the planned
   performer of `op-protected-merge`; an `admitted` catalog cites the Owner's sign-off
   verbatim from `evidence/bootstrap-log.md`;
8. every id, link, blueprint anchor and plan leaf resolves; ids are well formed and unique; no
   key is unknown; the OSCAL block claims nothing; no machine path appears; and this page
   names every control id and its generated tables equal `--render`.

`--list` prints each control with its subject, profiles and enforcers; `--render` prints the
generated tables. The negative cases are in
[`tools/tests/test_check_control_catalog.py`](../tools/tests/test_check_control_catalog.py).
When the catalog changes, edit the JSON, replace the generated block with the output of
`--render`, and run the checker.

## Adoption

- **Structure:** a small local JSON contract checked by a standard-library checker, the
  repository's existing policy pattern (`tools/check_*.py`, `policy/*.json`), as blueprint
  `#control-evidence` asks ("Use a small schema and JSON Schema/Conftest validation
  initially"). It is shaped for a later OSCAL catalog export (the `oscal` block maps the
  fields) and deliberately not claimed to be an OSCAL document.
- **Conftest** is not used: it is not a pinned component of `composition/`, and pinning one
  is a separate change. **No mapping to an external standard** (NIST SSDF, OWASP SAMM) is
  asserted; the blueprint calls such mappings alignment hypotheses for review.
- **No policy service** is built, and nothing is enforced, installed or configured here.

<!-- BEGIN GENERATED: python -I -B tools/check_control_catalog.py --render -->
### Controls

| Control | Category | Objective | Subject | Applies in | Events | Exception |
|---|---|---|---|---|---|---|
| `EXEC-01` Workload isolation | isolation | An agent run executes only inside an approved workload profile: no protected mount, administrative socket or unauthorized network is reachable from it, whatever its prompt or instructions say. | `attempt`: Every agent run (one engineering conversation), bound to the execution profile it ran under. | `baseline` | every agent run; every change of an execution profile | prohibited |
| `SEC-EXEC-01` Owner credentials out of agent reach | credentials | Agent execution cannot access Owner credentials: an agent run holds only credentials issued for that single attempt and can read no Owner, administrator, executor, management or standing Gitea bot credential; its role's standing bot credential stays on the trusted host and only the dispatcher uses it, on the run's behalf. | `attempt`: Every agent run, with the credentials issued for it and the dispatcher's use of its stage's standing credential on its behalf. | `baseline` | every agent run; every borrowing of a stage's standing bot credential by the dispatcher for a confirmed attempt; every issuance of a credential for a single attempt | prohibited |
| `SDLC-01` Code hygiene and tests | ci | The required lint, format, test, coverage and acceptance-mapping checks run independently against the exact pull-request commit, and a protected merge waits for all of them; absent checks fail closed. | `commit`: Every revision of a pull request to a protected branch. | `baseline` | every pull-request revision | unsettled (settled at G-06.3.1) |
| `SEC-PR-01` Secrets and vulnerabilities | ci | The required secret, dependency and SBOM scans run against the exact commit, and their findings are triaged against a published risk policy before a protected merge or a release. | `commit`: Every revision of a pull request to a protected branch, every release candidate and every dependency change. | `baseline` | every pull-request revision; every release; every dependency change; a scheduled rescan, as applicable | scoped |
| `REVIEW-01` Independent challenge | code-review | A review independent of the author receives the immutable accepted goal and the exact diff; its approval counts only for the revision it reviewed. | `commit`: Every pull-request revision whose merge requires a review. | `baseline`, `elevated` | every review the protected code-merge policy requires (decided at D-01.2); every elevated-risk change: an independent security review | unsettled (settled at G-06.3.1) |
| `AUTH-01` Owner authority | authorization | A consequential effect happens only on the Owner's recorded authorization of the exact operation manifest, merged onto the protected authorization branch, and after the isolated executor has re-checked the exact target and digest. | `authorization`: Each consequential operation: one operation manifest on the protected authorization branch. | `consequential` | each consequential effect | unsettled (settled at G-06.3.1) |
| `ASSURE-01` Evidence integrity | evidence | A control verdict rests only on independently sourced evidence whose source identity, content integrity, subject, freshness and allowed signer or runner are verified; anything that cannot be verified is unknown or stale, never satisfied. | `commit`, `review`, `ci`, `authorization`, `effect-receipt`: Each evidence reference that a control verdict relies on. | `baseline` | each control verdict; each change of an evidence source a verdict relies on | unsettled (settled at G-06.3.1) |
| `RECOVER-01` Durable state recovery | recovery | A change or operation that can alter durable state (repositories, conversations, Work, Git history, credentials, operational records) proceeds only with a verified recovery option, and an unknown non-idempotent outcome stops for reconciliation and is never replayed. | `authorization`, `commit`: Each consequential operation, and each change whose change surface includes durable data. | `elevated`, `consequential` | each consequential operation (preconditions such as recovery-available, data-compatible and backup-verified); each change whose change surface is durable data (migration and data-health tests, a backup or recovery condition) | unsettled (settled at G-06.3.1) |

### Enforcement points

| Control | Boundary | Enforcing principal | Assets | Mechanism | Built at |
|---|---|---|---|---|---|
| `EXEC-01` | execution | `management-dispatcher` | `conversation-container`, `api-agent-server-management` | The restricted launcher starts only approved workload profiles and denies protected mounts, administrative sockets and unauthorized networks; the sandbox mount and permission manifest is the guard, not the agent prompt. | E-01.3.2, S-02.2 |
| `EXEC-01` | execution | `guest-root` | `guest-execution-vm`, `guest-container-guard` | The execution guest is the VM boundary against untrusted agents, and its container egress guard refuses every forwarded connection from a container bridge (S-01.4). | S-01.4, S-02.2 |
| `SEC-EXEC-01` | execution | `management-dispatcher` | `conversation-container` | No Owner secrets or host home mounts. The standing Gitea bot credentials stay on the trusted host in the OS credential provider; for a confirmed attempt the dispatcher borrows only the stage's mapped credential into its own in-memory attempt context, uses it there and releases it when the operation ends, which is not Gitea revocation; a standing credential never enters a guest, an agent environment, a container, a conversation, a conversation record or the UI, and records carry fingerprints only. Issuance, rotation and revocation of a standing credential are the Gitea site administrator's, on defined security and lifecycle triggers (suspected exposure, definition revocation, policy revision, expiry, Owner direction), never on routine attempt completion; the dispatcher issues, rotates and revokes none. The per-attempt inference token is issued by the inference broker and revoked at attempt end (decision 0015). Disclosed, not prevented: during bootstrap the Owner's account can read the standing credentials in the credential provider (decision 0013 point 6). Decision 0007 points 4 and 5, amendment 1; decision 0013 point 7. | E-01.3.3, E-01.3.2 |
| `SEC-EXEC-01` | git-ci | `gitea-site-admin` | `gitea-server` | Each agent role's Gitea identity is a non-administrator Bot account whose token carries the role's narrowest scope; no agent identity holds an Owner, administrator or executor credential (policy/role-tokens.json). | S-01.2.2 |
| `SDLC-01` | git-ci | `gitea-site-admin` | `gitea-server` | Protected branch rules require the mandatory status checks on the current head, from centrally required workflows that a consuming repository cannot opt out of. | Q-03.1, Q-03.2, D-01.2 |
| `SDLC-01` | git-ci | `ci-runner-service` | `ci-runner-host` | The required Gitea Actions jobs run in a disposable, contained job on the dedicated runner host, against the exact pull-request commit. | Q-02.2.2, Q-03.1 |
| `SEC-PR-01` | git-ci | `gitea-site-admin` | `gitea-server` | The scans are required status checks of the protected branch; a material finding without a permitted scoped exception keeps the merge blocked. | G-02.2, Q-03.2 |
| `SEC-PR-01` | git-ci | `ci-runner-service` | `ci-runner-host` | The pinned scanners run as required jobs in the contained CI job against the exact commit. | G-02.1 |
| `REVIEW-01` | git-ci | `gitea-site-admin` | `gitea-server` | Merge rules require the applicable approvals on the current head and dismiss stale approvals. | D-01.2, E-03.4 |
| `REVIEW-01` | execution | `management-dispatcher` | `conversation-container` | The reviewer runs in a session, runner or model and context separate from the builder's, under its own Bot identity, which can submit reviews and cannot merge. | E-03.2.1, E-03.2.2 |
| `AUTH-01` | effect | `gitea-site-admin` | `repo-gitea-authorization`, `gitea-server` | The protected authorization branch: no direct or force push, and only aieh-owner, the Owner's authority identity, is on its merge allowlist (decision 0012 point 3). | G-03.1, G-03.2 |
| `AUTH-01` | effect | `authorization-recorder` | `repo-gitea-authorization` | Merges only on a fresh Owner decision bound to the exact head and manifest digest, after the fail-closed protection check (decision 0012 points 4 to 6). | P-04.2 |
| `AUTH-01` | effect | `authorization-verifier` | `repo-gitea-authorization` | Reads the protected ref, merged_by, the trailers and the exact manifest blob; a protected-branch merge without a recorder trailer or receipt is an unrecorded merge (decision 0012 point 10). | G-04.3.1, G-04.3.2 |
| `AUTH-01` | effect | `privileged-executor` | `store-effects` | A separate OS identity re-checks the current authorized revision, target and digest before acting, and never trusts a webhook payload. | G-04.2.1, G-04.4.1 |
| `ASSURE-01` | evidence | `integration-service` | `api-integration-service`, `store-integration` | The independent evidence resolver, keyed by source revision and observed subject, retrieves the native record, verifies subject, revision, hash, source identity and freshness, and leaves missing evidence unknown; it keeps no second evidence or Work database. | G-01.2, G-06.3.1, G-06.4 |
| `RECOVER-01` | effect | `privileged-executor` | `store-effects` | Checks the manifest's recovery preconditions and the actual target state before acting, persists its receipt, queries the actual target state after a crash and stops on an unknown non-idempotent effect. | G-04.4.2, G-04.5, R-02.4.2 |
| `RECOVER-01` | git-ci | `gitea-site-admin` | `gitea-server` | A change whose surface is durable data carries migration and data-health checks among the required checks on its exact commit. | Q-03.1, R-02.2.2 |

### Profiles

| Profile | Applies when | Obligations | Controls |
|---|---|---|---|
| `baseline` Baseline engineering | always | Every attempt: isolated workspace, approved agent/skill digests, outcome/Work lineage. Every PR: protected CI checks, tested commit, review requirements by policy. | `EXEC-01`, `SEC-EXEC-01`, `SDLC-01`, `SEC-PR-01`, `REVIEW-01`, `ASSURE-01` |
| `elevated` Elevated-risk change | change-surface is any of auth, secrets, public-networking, durable-data, execution-boundary | Add scoped threat analysis, targeted adversarial tests, license/security assessment, enhanced isolation and independent security review when work touches auth, secrets, public networking, durable data or execution boundaries. | `REVIEW-01`, `RECOVER-01` |
| `consequential` Consequential operation | operation-type is any of consequential-effect | Add protected Owner authorization, exact effect digest, privilege-separated execution, data protection/rollback preconditions and independently observed outcome. Non-waivable identity and containment invariants still apply. | `AUTH-01`, `RECOVER-01` |

### Deferred controls

| Control | Why not here | Leaves |
|---|---|---|
| `AGENT-01` Approved agent/skill | Outside the categories this leaf declares. Its definitions are admitted through the agent and skill catalog (governance steps 01 to 05; step 04, the protected catalog merge, is unchanged by M-5 and outside decision 0012). | A-01.1, A-01.2 |
| `PLAN-01` Intent/acceptance trace | Outside the categories this leaf declares; the trace it checks is the lineage projection (P-03.2) and the acceptance verdicts. | G-05.1 |
| `REL-01` Artifact and delivery | Outside the categories this leaf declares, and its subject, a release artifact, has no settled native identity in the lineage schema. | R-01.1, R-02.2.1, R-05.4.2 |

<!-- END GENERATED -->

## Not yet verified

- That any enforcement point enforces its control: no control is assessed (G-01.2 and the
  leaves under "Built at").
- The Owner's sign-off of the catalog, and the protected policy repository it is to live in.
- Severity per control, verified external mappings, and the exception class of the five
  `unsettled` controls (G-06.3.1).

## Sources

- Blueprint: `#control-evidence`, `#governance-architecture`, `#security`, `#sequence-maps`,
  `#authorization-qualification`, `#quality-pipeline`, `#containment-architecture`,
  `#infrastructure-state`, `#updates`, `#workflow`.
- Plan: G-01.1 (and its parent G-01), with the dependencies S-01.4 (the
  [network matrix](network-matrix.json)) and P-03.2 (the lineage projection).
- Decisions: [0003](../decisions/0003-execution-guest-providers-and-isolation-contract.md),
  [0004](../decisions/0004-privileged-effect-store-custody-and-restore-semantics.md),
  [0007](../decisions/0007-role-token-matrix-and-revocation-contract.md),
  [0012](../decisions/0012-owner-authorization-channel-and-gitea-owner-identity.md),
  [0013](../decisions/0013-owner-ui-session-access-and-management-key-custody.md),
  [0016](../decisions/0016-hostile-ci-threat-model-validation-and-promotion-lanes-and-runner-reach.md).
- Inventory: [`security/inventory.json`](../security/inventory.json); the role tokens:
  [`role-tokens.json`](role-tokens.json).
