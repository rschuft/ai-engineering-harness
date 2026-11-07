# Role-token matrix and revocation contract

Plan leaf **S-01.2.1**, "Define least-privilege principal/token permissions", as of
2026-11-07 (baseline commit `421719b`). It assigns distinct scopes to the planner,
builder, reviewer, CI, Owner and executor, and defines issuance and revocation, on top
of the S-01.1 [security inventory](../security/README.md).

- **Acceptance of this leaf:** no agent, reviewer or CI role has Owner or
  privileged-effect capability in the documented mapping.
- **Machine-readable form:** [`role-tokens.json`](role-tokens.json). The tables under
  [The matrix](#the-matrix) are rendered from it, and
  [`tools/check_role_tokens.py`](../tools/check_role_tokens.py) checks it (`task
  policy:check`; see [What the checker enforces](#what-the-checker-enforces)).
- **Decision:** [0007](../decisions/0007-role-token-matrix-and-revocation-contract.md)
  (Proposed).
- **This is a mapping, not a control.** It issues, installs, creates and configures
  nothing: no identity, account, bot, token, ACL, guest or endpoint (decision 0004,
  Owner clarification 7). S-01.2.2 tests the allowed and forbidden calls of each
  non-Owner principal against the pinned Gitea and records the result in each row (see
  [Realization](#realization)).
- **S-01.2.2 (2026-11-07):** the bot accounts and tokens exist; the planner, builder and
  verifier account-and-token rows, the builder's branch protection and the site
  administrator's blocked merge override are verified on a live fixture; the reviewer
  row failed in part (Gitea has no review-only scope, and a reader can open a PR); every
  Owner, administrator, protected-ref, protection and secret operation was refused for
  every bot token. Record:
  [`evidence/S-01.2.2-segregated-credentials.md`](../evidence/S-01.2.2-segregated-credentials.md).
- **S-01.3.1 (2026-11-07):** the dispatcher's admission half is verified: every key-gated
  Agent Server route refuses a missing or wrong key, the server does not start without a
  valid key, and no conversation container reaches the management listener, the guest
  itself or another container. Sole custody of the session key is not realized (no
  dispatcher; the operator login reads it during bootstrap). Record:
  [`evidence/S-01.3.1-management-api-admission.md`](../evidence/S-01.3.1-management-api-admission.md).
- **S-01.3.2 (2026-11-07):** the builder's and reviewer's job environment is verified:
  from inside two conversation containers no engine socket, engine API, Agent Server
  route, host service or management, Owner, admin or bot credential is reachable. The CI
  job's equivalent constraints are declared for the runner containment leaves and not
  verified (no CI runner exists). Record:
  [`evidence/S-01.3.2-job-daemon-and-management-access.md`](../evidence/S-01.3.2-job-daemon-and-management-access.md).

## Bootstrap reality

Gitea 28.3.0 runs on host loopback (F-06.1). The planner, builder, reviewer and
verifier bot accounts and their tokens exist since S-01.2.2, in the Owner account's
Credential Manager (`AIEH Gitea bot <role>`) pending the dispatcher, but no agent
workload has run or held one (decision 0003, C6), and the Owner's account performs
every operation that has been performed: the Owner directs the work and approves privileged host acts by UAC consent,
host tooling under the Owner's account runs the guest lifecycle and the Agent Server
management operations, and the host-side bootstrap agents share that account. They are
therefore not a role: they are granted nothing, they inherit the reach of the Owner's
account (`fd-bootstrap-shared-identity`), and the sunset map below names the leaf at
which each operation they perform today moves to its planned principal.

## How to read it

- **Roles are grants; principals are runtime identities.** Each role binds to exactly
  one principal of the inventory, and a principal may carry several roles (the planner
  and the builder are both roles on `engineering-agent`, each with its own Gitea bot
  identity and token). A grant names an inventory operation (`op-*`), a capability
  (`cap-*`, defined here) or an inventory credential (`cred-*`).
- **A role is agent-controlled** when its principal is (`planner`, `builder`,
  `reviewer`, `ci-job`). The checker derives this from the inventory.
- **Denials** are listed explicitly. Every agent-controlled role denies at least the
  baseline: `op-protected-merge`, `cap-code-merge-integration`,
  `cap-protected-ref-push`, `op-gitea-administration`, `op-effect-apply`,
  `op-effect-receipt-write`, `cred-executor-identity`,
  `cred-agent-server-session-key`, `op-as-conversation-create`,
  `cred-moby-docker-group`, `cred-gitea-owner-account` and `cred-gitea-admin`.
- **Statuses** follow the inventory's rules (`planned` with sources, `observed` with
  evidence, `unknown` with a finding). A role is `observed` only where its grants are
  shown by committed evidence today.
- **Realization** says how a role is to be enforced. A row is `verified: true` only
  with evidence; every other row says `verified: false`, names the leaf that is to
  verify it, and its note says why it is not verified (unknown, not applicable, or
  blocked).

## Issuance and revocation contract

- **Issuance.** `gitea-site-admin` issues Gitea identities, bot accounts and their
  tokens, protection rules and runner registration secrets. `management-dispatcher`,
  the launcher and credential broker, is custodian of the standing bot credentials and
  delivers each agent role token per attempt into the attempt environment only.
  Gitea 28.3.0 cannot bound a token to an attempt (it has no token lifetime, S-01.2.2),
  so the token is rotated at attempt end. Tokens never go into an image,
  seed, repository, log or record: records carry fingerprints only. Owner-class and
  executor-class credentials are issued only by Owner acts. The executor issues
  nothing. The inference broker alone issues inference access, and no provider
  credential is ever a role token.
- **Triggers:** attempt end, suspected exposure, definition revocation, policy revision,
  expiry and Owner direction. Every credential row includes suspected exposure and
  Owner direction; an agent role's credentials also end with the attempt.
- **Revoker:** the issuer's role. Where the issuer is outside the inventory (a provider,
  Gitea Actions, the Gitea installation), the row names the role that revokes.
- **On new dispatch:** immediate refusal.
- **In flight:** the dispatcher stops or contains the attempts holding the credential
  through `op-as-runtime-stop` and records them as exposed; Gitea fails closed at the
  credential's next authenticated call; CI jobs holding it are cancelled.
- **Evidence:** a Gitea audit record where audit logging is enabled (it is off by
  default), plus a revocation receipt in the integration store with the fingerprint,
  role, trigger, revoker and affected attempts. A receipt goes to the effects store only
  when the revocation was itself an executor effect (decision 0004, point 1): the
  executor's own credentials in the target.
- **Privileged rotation.** Rotating an Owner, admin, executor or management credential
  is a consequential external effect: an Owner-only manifest applied by the executor in
  the target, or an Owner act recorded in the bootstrap log during bootstrap.
- **Rotation owner.** Each row names one, and it equals the credential's
  `rotation_revocation_owner` in the inventory.

## The matrix

<!-- BEGIN GENERATED: python -I -B tools/check_role_tokens.py --render -->
### Roles and grants

| Role | Principal | Agent-controlled | Operations | Capabilities | Credentials | Status |
|---|---|---|---|---|---|---|
| `owner` The Owner | `owner` | no | `op-guest-boundary-change`, `op-host-privileged-change`, `op-git-push-public`, `op-policy-change`, `op-protected-merge`, `op-effect-store-custody` | `cap-code-merge-integration` | `cred-uac-consent`, `cred-gitea-owner-account`, `cred-owner-ui-access` | planned |
| `owner-os-account` The Owner's host account | `owner-os-account` | no | `op-guest-lifecycle`, `op-guest-exec`, `op-exchange`, `op-session-key-export`, `op-provision-fetch` | - | `cred-guest-ssh-key`, `cred-owner-github`, `cred-owner-provider-login` | observed |
| `gitea-site-admin` Gitea site administrator | `gitea-site-admin` | no | `op-gitea-administration` | - | `cred-gitea-admin` | planned |
| `planner` Planning agent | `engineering-agent` | yes | - | `cap-read-repositories`, `cap-push-proposal-branch`, `cap-open-pr` | `cred-gitea-bot-planner`, `cred-conversation-keys` | planned |
| `builder` Engineering agent (builder) | `engineering-agent` | yes | `op-open-proposal-pr` | `cap-read-repositories`, `cap-push-proposal-branch`, `cap-open-pr` | `cred-gitea-bot-builder`, `cred-conversation-keys` | planned |
| `reviewer` Reviewer agent | `reviewer-agent` | yes | `op-submit-review` | `cap-read-repositories`, `cap-submit-review` | `cred-gitea-bot-reviewer` | planned |
| `ci-job` CI job executing pull-request code | `ci-job` | yes | `op-ci-untrusted-job` | `cap-ci-statuses-artifacts` | `cred-ci-job-token` | planned |
| `ci-runner-service` CI runner service | `ci-runner-service` | no | `op-ci-runner-registration` | - | `cred-runner-registration` | planned |
| `management-dispatcher` Trusted dispatcher and credential broker | `management-dispatcher` | no | `op-as-conversation-create`, `op-as-runtime-stop`, `op-as-runtime-reprovision`, `op-as-conversation-delete`, `op-as-conversation-pause`, `op-as-management-read`, `op-as-unenumerated-routes`, `op-child-conversation` | - | `cred-agent-server-session-key` | planned |
| `integration-service` Integration Service | `integration-service` | no | `op-integration-store-write` | - | - | planned |
| `authorization-verifier` Authorization verifier | `authorization-verifier` | no | `op-authorization-verify` | `cap-read-repositories` | `cred-verifier-read` | planned |
| `privileged-executor` Privileged effect executor | `privileged-executor` | no | `op-effect-apply`, `op-effect-receipt-write` | - | `cred-executor-identity`, `cred-executor-target-secrets` | planned |
| `inference-broker` Inference broker | `inference-broker` | no | `op-inference-call` | - | `cred-llm-provider-key` | planned |
| `release-job-environment` Release-signing or deployment job environment | `release-job-environment` | no | `op-release-signing-deploy` | - | - | unknown |
| `guest-root` Guest root | `guest-root` | no | `op-moby-daemon-admin`, `op-guest-provision`, `op-guest-facts` | - | `cred-guest-host-keys` | observed |
| `guest-service-openhands` Guest service user (outer Agent Server) | `guest-service-openhands` | no | `op-moby-container-control` | - | `cred-oh-secret-key`, `cred-moby-docker-group` | observed |
| `guest-login-agent` Guest operator login | `guest-login-agent` | no | - | - | - | observed |

### Denials

| Role | Denied (operations, capabilities, credentials) |
|---|---|
| `owner-os-account` | `cred-executor-identity` |
| `gitea-site-admin` | `op-protected-merge`, `cap-code-merge-integration`, `cap-protected-ref-push` |
| `planner` | `op-protected-merge`, `cap-code-merge-integration`, `cap-protected-ref-push`, `op-gitea-administration`, `cap-work-status-mutation`, `op-effect-apply`, `op-effect-receipt-write`, `cred-executor-identity`, `cred-executor-target-secrets`, `cred-agent-server-session-key`, `op-as-conversation-create`, `op-child-conversation`, `cred-moby-docker-group`, `op-moby-container-control`, `cred-gitea-owner-account`, `cred-gitea-admin`, `cred-uac-consent`, `cred-owner-github`, `cred-llm-provider-key`, `cred-gitea-bot-builder`, `cred-gitea-bot-reviewer` |
| `builder` | `op-protected-merge`, `cap-code-merge-integration`, `cap-protected-ref-push`, `op-gitea-administration`, `cap-work-status-mutation`, `op-effect-apply`, `op-effect-receipt-write`, `cred-executor-identity`, `cred-executor-target-secrets`, `cred-agent-server-session-key`, `op-as-conversation-create`, `op-child-conversation`, `cred-moby-docker-group`, `op-moby-container-control`, `cred-gitea-owner-account`, `cred-gitea-admin`, `cred-uac-consent`, `cred-owner-github`, `cred-llm-provider-key`, `cred-gitea-bot-planner`, `cred-gitea-bot-reviewer` |
| `reviewer` | `op-protected-merge`, `cap-code-merge-integration`, `cap-protected-ref-push`, `op-gitea-administration`, `cap-work-status-mutation`, `op-effect-apply`, `op-effect-receipt-write`, `cred-executor-identity`, `cred-executor-target-secrets`, `cred-agent-server-session-key`, `op-as-conversation-create`, `op-child-conversation`, `cred-moby-docker-group`, `op-moby-container-control`, `cred-gitea-owner-account`, `cred-gitea-admin`, `cred-uac-consent`, `cred-owner-github`, `cred-llm-provider-key`, `cap-push-proposal-branch`, `cred-gitea-bot-planner`, `cred-gitea-bot-builder` |
| `ci-job` | `op-protected-merge`, `cap-code-merge-integration`, `cap-protected-ref-push`, `op-gitea-administration`, `cap-work-status-mutation`, `op-effect-apply`, `op-effect-receipt-write`, `cred-executor-identity`, `cred-executor-target-secrets`, `cred-agent-server-session-key`, `op-as-conversation-create`, `op-child-conversation`, `cred-moby-docker-group`, `op-moby-container-control`, `cred-gitea-owner-account`, `cred-gitea-admin`, `cred-uac-consent`, `cred-owner-github`, `cred-llm-provider-key`, `op-release-signing-deploy`, `cred-runner-registration`, `cap-push-proposal-branch` |
| `management-dispatcher` | `op-effect-apply`, `op-effect-receipt-write`, `cred-executor-identity` |
| `integration-service` | `cred-gitea-owner-account`, `cred-uac-consent`, `op-effect-receipt-write` |
| `authorization-verifier` | `cap-push-proposal-branch`, `cap-open-pr`, `op-protected-merge`, `op-effect-apply` |
| `privileged-executor` | `op-gitea-administration`, `cap-push-proposal-branch`, `cap-open-pr`, `cap-protected-ref-push`, `cap-code-merge-integration` |
| `release-job-environment` | `cred-executor-identity` |

### Capabilities

| Capability | Authority | Granted to | Delegation | Status |
|---|---|---|---|---|
| `cap-code-merge-integration` Merge a code PR into a protected integration branch: Merging a code pull request into a protected integration branch under the branch rules (required checks and independent review). Distinct from the Owner-only merge of an operation manifest on the authorization branch. | owner | `owner` | permitted automation only, by repository policy; never an agent or CI role (D-01.2) | planned |
| `cap-read-repositories` Read repositories: Read the repositories in scope, their pull requests and diffs. | scoped | `planner`, `builder`, `reviewer`, `authorization-verifier` | - | planned |
| `cap-push-proposal-branch` Push a proposal branch: Push `work/*` proposal branches; never a protected ref. | scoped | `planner`, `builder` | - | planned |
| `cap-open-pr` Open a pull request: Open a pull request from a proposal branch. | scoped | `planner`, `builder` | - | planned |
| `cap-submit-review` Submit a review: Submit a review as evidence; a review never merges. | scoped | `reviewer` | - | planned |
| `cap-ci-statuses-artifacts` Report CI statuses and artifacts: Report commit statuses and upload artifacts for the job's own run, within the job token's repository context. | scoped | `ci-job` | - | planned |
| `cap-protected-ref-push` Push to a protected ref: Push, force-push or API-merge directly to a protected ref, bypassing the merge rules. No role is granted it: protected refs change only through protected merges. | owner | no role | - | planned |
| `cap-work-status-mutation` Change Work status: Change a Work item's status. Backlog status belongs to the deterministic coordinator, which the inventory does not name yet; no role here is granted it. | management | no role | - | planned |

### Issuance and revocation

| Credential | Role | Issuer | Delivered by | Delivery | Revoker | Revocation | Triggers | Rotation owner |
|---|---|---|---|---|---|---|---|---|
| `cred-uac-consent` | `owner` | `owner` | - | Given interactively on the secure desktop for one specifically authorized elevated operation, which an agent may initiate (decision 0004, Owner clarification 4); never stored. | `owner` | It lapses after its one operation; the Owner withholds or withdraws consent. | suspected-exposure, owner-direction | `owner` |
| `cred-gitea-owner-account` | `owner` | `gitea-site-admin` | - | Created on the Gitea instance as an Owner act (Owner-class credentials are issued only by Owner acts); the Owner signs in independently. | `gitea-site-admin` | Disable the account or reset its password and sessions on the Gitea instance, as an Owner act. | suspected-exposure, expiry, owner-direction | `owner` |
| `cred-owner-ui-access` | `owner` | `external:undefined` | - | Not defined (fd-owner-ui-access); issued only by an Owner act. | `owner` | Not defined until the Owner UI's access is decided (S-01.3.1). | suspected-exposure, expiry, owner-direction | `owner` |
| `cred-guest-ssh-key` | `owner-os-account` | `owner-os-account` | - | Generated per instance at create by the system ssh-keygen into the per-instance directory; recreate issues a new one. | `owner-os-account` | Guest destroy removes it and recreate issues a new one. | suspected-exposure, owner-direction | `owner-os-account` |
| `cred-owner-github` | `owner-os-account` | `external:github` | - | The Owner's own account at the provider; custody not inspected. | `owner` | Revoked and reissued at the provider by the Owner. | suspected-exposure, expiry, owner-direction | `owner` |
| `cred-owner-provider-login` | `owner-os-account` | `external:model-provider` | - | The Owner's own coding-assistant login; never a role token. | `owner` | Signed out or revoked at the provider by the Owner. | suspected-exposure, expiry, owner-direction | `owner` |
| `cred-gitea-admin` | `gitea-site-admin` | `external:gitea-installation` | - | Created by F-06.1 with Gitea's CLI; its final password is generated and set by task gitea:finalize-credentials and held by the harness in the credential provider (Owner directive of 2026-11-07); read only by credential finalization and the fixture administration. | `owner` | Rotated by the Owner on the Gitea instance: a consequential external effect. | suspected-exposure, policy-revision, expiry, owner-direction | `owner` |
| `cred-gitea-bot-planner` | `planner` | `gitea-site-admin` | `management-dispatcher` | Delivered per attempt by the dispatcher into the attempt environment only. Gitea 28.3.0 cannot bound a token to an attempt (no token lifetime), so it is rotated at attempt end. Never in an image, seed, repository, log or record (fingerprints only). | `gitea-site-admin` | The site administrator revokes the bot's tokens (observed at S-01.2.2: it lists and deletes another account's token, which then answers 401) or disables the bot account; per attempt, the dispatcher rotates the token at attempt end, since Gitea 28.3.0 has no token lifetime; DELETE /api/v1/token also revokes the authenticating token (observed). | attempt-end, suspected-exposure, definition-revocation, policy-revision, expiry, owner-direction | `management-dispatcher` |
| `cred-conversation-keys` | `planner` | `guest-service-openhands` | - | Passed by the Agent Server's Docker runtime as environment values into the conversation container. | `guest-service-openhands` | They end with their container: stopping the runtime or deleting the conversation removes them. | attempt-end, suspected-exposure, definition-revocation, policy-revision, owner-direction | `guest-service-openhands` |
| `cred-gitea-bot-builder` | `builder` | `gitea-site-admin` | `management-dispatcher` | Delivered per attempt by the dispatcher into the attempt environment only. Gitea 28.3.0 cannot bound a token to an attempt (no token lifetime), so it is rotated at attempt end. Never in an image, seed, repository, log or record (fingerprints only). | `gitea-site-admin` | The site administrator revokes the bot's tokens (observed at S-01.2.2: it lists and deletes another account's token, which then answers 401) or disables the bot account; per attempt, the dispatcher rotates the token at attempt end, since Gitea 28.3.0 has no token lifetime; DELETE /api/v1/token also revokes the authenticating token (observed). | attempt-end, suspected-exposure, definition-revocation, policy-revision, expiry, owner-direction | `management-dispatcher` |
| `cred-conversation-keys` | `builder` | `guest-service-openhands` | - | Passed by the Agent Server's Docker runtime as environment values into the conversation container. | `guest-service-openhands` | They end with their container: stopping the runtime or deleting the conversation removes them. | attempt-end, suspected-exposure, definition-revocation, policy-revision, owner-direction | `guest-service-openhands` |
| `cred-gitea-bot-reviewer` | `reviewer` | `gitea-site-admin` | `management-dispatcher` | Delivered per attempt by the dispatcher into the attempt environment only. Gitea 28.3.0 cannot bound a token to an attempt (no token lifetime), so it is rotated at attempt end. Never in an image, seed, repository, log or record (fingerprints only). | `gitea-site-admin` | The site administrator revokes the bot's tokens (observed at S-01.2.2: it lists and deletes another account's token, which then answers 401) or disables the bot account; per attempt, the dispatcher rotates the token at attempt end, since Gitea 28.3.0 has no token lifetime; DELETE /api/v1/token also revokes the authenticating token (observed). | attempt-end, suspected-exposure, definition-revocation, policy-revision, expiry, owner-direction | `management-dispatcher` |
| `cred-ci-job-token` | `ci-job` | `external:gitea-actions` | - | Minted by Gitea Actions for one job into the job environment, within the configured token maxima. | `gitea-site-admin` | It expires with its job; on exposure the site administrator cancels the job and disables the runner. | attempt-end, suspected-exposure, policy-revision, expiry, owner-direction | `gitea-site-admin` |
| `cred-runner-registration` | `ci-runner-service` | `gitea-site-admin` | - | Issued by the site administrator to register the runner; stored on the runner host outside every job's filesystem. | `gitea-site-admin` | Unregister the runner and issue a new registration secret; the rotation is a consequential external effect. | suspected-exposure, policy-revision, expiry, owner-direction | `owner` |
| `cred-agent-server-session-key` | `management-dispatcher` | `guest-root` | - | Generated in the guest at provisioning; read by the operator login from its root:agent 0440 file during bootstrap (S-01.3.1); it is to reach only the dispatcher over a trusted channel (E-01.2.x). Records carry fingerprints only. | `guest-root` | Only guest recreate and provision revokes it, which ends every conversation. | suspected-exposure, policy-revision, owner-direction | `owner-os-account` |
| `cred-verifier-read` | `authorization-verifier` | `gitea-site-admin` | - | Issued by the site administrator to the verifier's own identity; unreachable from code runners. | `gitea-site-admin` | The site administrator revokes and reissues it. | suspected-exposure, policy-revision, expiry, owner-direction | `gitea-site-admin` |
| `cred-executor-identity` | `privileged-executor` | `owner` | - | Created by Owner act A4 at G-04.2.1: a service identity with no stored password, never in the Owner's credential store. | `owner` | An Owner elevated act during bootstrap; in the target, an Owner-only manifest that the executor applies. Receipt: effects-store. | suspected-exposure, policy-revision, expiry, owner-direction | `owner` |
| `cred-executor-target-secrets` | `privileged-executor` | `owner` | - | Provided by an Owner act into the executor's separate custody; not defined until G-04.2.x. | `owner` | An Owner elevated act during bootstrap; in the target, an Owner-only manifest that the executor applies. Receipt: effects-store. | suspected-exposure, policy-revision, expiry, owner-direction | `owner` |
| `cred-llm-provider-key` | `inference-broker` | `external:model-provider` | - | Loaded into the broker only, by the Owner. No provider credential is ever a role token. | `owner` | Rotated at the provider by the Owner, then reloaded into the broker only. | suspected-exposure, policy-revision, expiry, owner-direction | `owner` |
| `cred-guest-host-keys` | `guest-root` | `guest-root` | - | Regenerated at every create; the fingerprints reach the host through the serial log. | `guest-root` | Regenerated at every create. | suspected-exposure, owner-direction | `guest-root` |
| `cred-oh-secret-key` | `guest-service-openhands` | `guest-root` | - | Generated by the root provisioning step into a root-only environment file; it never leaves the guest. | `guest-root` | Only guest recreate and provision replaces it. | suspected-exposure, owner-direction | `guest-root` |
| `cred-moby-docker-group` | `guest-service-openhands` | `guest-root` | - | Group membership set by the root provisioning step. | `guest-root` | Only guest recreate and provision changes it. | suspected-exposure, policy-revision, owner-direction | `guest-root` |

### Realization

| Role | Mechanism | Verified | Verify at | Evidence |
|---|---|---|---|---|
| `owner` | A separate Gitea Owner account, the only identity on the authorization branch's merge allowlist; interactive sign-in only, never a personal access token in any agent or CI context. Note: Partly shown at S-01.2.2: aieh-owner is the only merge-allowlist identity of every protected-branch rule of the fixture, and it holds no access token (finalize-credentials). The authorization branch does not exist yet (fd-owner-authorization-record). Under the Owner directive of 2026-11-07 the Owner never signs in: the credential is harness-held and how the Owner identity is used internally is to be decided, so "interactive sign-in only" is superseded pending that decision. | no | S-01.2.2 | `evidence/S-01.2.2-segregated-credentials.md`, `evidence/F-06.1-gitea-loopback.md` |
| `owner` | Code merges into protected integration branches under the D-01.2 branch rules. Note: Not exercised at S-01.2.2: no Owner merge was performed (the Owner credential is not used by tests); the D-01.2 branch rules are not applied yet. | no | D-01.2 | `evidence/S-01.2.2-segregated-credentials.md` |
| `gitea-site-admin` | The Gitea site-administrator account; branch protection with the admin force-merge override disabled, so the administrator obeys the branch rules. Note: Verified at S-01.2.2: the fixture's default-branch rule carries block_admin_merge_override; the site administrator's merge and force-merge of a proposal PR both answered 405 "User not allowed to merge PR", and the default branch did not change. | yes | S-01.2.2 | `evidence/S-01.2.2-segregated-credentials.md` |
| `gitea-site-admin` | Issues Gitea identities, bot accounts and their tokens, protection rules and runner registration secrets; never exposed to agents or CI. Note: Partly shown at S-01.2.2: the protection rules, organization, repository and collaborators were issued by the site administrator through the API (basic authentication, password in memory, no token); the bot accounts and tokens through Gitea's CLI by the Owner's host account; the administrator can list and revoke another account's token (200, 204, then 401). No runner registration secret exists (fd-ci-runner-unpinned). The credential is read only by credential finalization and the fixture administration. | no | S-01.2.2 | `evidence/S-01.2.2-segregated-credentials.md` |
| `planner` | A dedicated, non-administrator Gitea bot account and token. Note: Verified at S-01.2.2: aieh-bot-planner, a restricted, non-administrator Gitea Bot account without a password; token scope write:repository only; every Owner, administrator, user and token operation probed was refused, and it pushed work/authz-planner and opened a PR. | yes | S-01.2.2 | `evidence/S-01.2.2-segregated-credentials.md` |
| `planner` | Planning-artefact-only writes, pending the layout: a repository-level permission if planning artefacts get their own repository, or a required scoped-workflow check on PR paths if they are co-located. Note: Unknown at S-01.2.2: Gitea 28.3.0 token scopes are categorical and no path-level scope exists; pending the planning-artefact layout (decision 0007, point 2). | no | S-01.2.2 | `evidence/S-01.2.2-segregated-credentials.md` |
| `builder` | A dedicated, non-administrator Gitea bot account and token with repository write and PR scope. Note: Verified at S-01.2.2: aieh-bot-builder, a restricted, non-administrator Bot account; token scope write:repository; write collaborator of the fixture; it pushed work/authz-builder and opened a PR. | yes | S-01.2.2 | `evidence/S-01.2.2-segregated-credentials.md` |
| `builder` | Branch protection denies the bot direct push, force push, API merge and protection changes; it can still open a proposal PR. Note: Verified at S-01.2.2: direct push, force-push and push-deletion of main and a push to a non-work/* branch were declined by the pre-receive hook; merge, force-merge and squash answered 405; protection, settings, collaborator, hook, deploy-token, transfer and deletion calls answered 403; it still opened a proposal PR. | yes | S-01.2.2 | `evidence/S-01.2.2-segregated-credentials.md` |
| `builder` | The job environment: a per-conversation container of the guest Agent Server with no engine socket and no engine API (Docker, containerd and the others absent; 2375 and 2376 refused at every address), no route of the outer Agent Server at any address, no host service through SLIRP, and no management, Owner, admin or bot credential in its files or process environments; not privileged, every capability set empty, no_new_privs, seccomp and AppArmor (provisioning.agent_server.jobs). Note: Verified live on a disposable provisioned guest (guest.py job-access-probe, before and after a guest restart) from inside two disposable conversation containers, as their default user (root is not obtainable): every declared engine socket, the engine ports and host aliases over TCP, all 193 routes at every address, and the outer key and Gitea bot token fingerprints. No agent workload, LLM or repository content ran. | yes | S-01.3.2 | `evidence/S-01.3.2-job-daemon-and-management-access.md` |
| `reviewer` | A dedicated Gitea bot account and token with read and review permission only, on no merge allowlist. Note: Failed in part at S-01.2.2. Shown: read permission on the fixture, on no merge allowlist; it submitted an approving review; its pushes were declined, its merges answered 405, its settings calls 403. Not realizable: Gitea 28.3.0 has no review-only scope (a review with read:repository answered 403, required=[write:repository]), and a read-permission collaborator can open a pull request from an existing branch (201; fd-gitea-reader-opens-pr). Neither reaches an Owner operation. | no | S-01.2.2 | `evidence/S-01.2.2-segregated-credentials.md` |
| `reviewer` | The job environment: a per-conversation container of the guest Agent Server with no engine socket and no engine API (Docker, containerd and the others absent; 2375 and 2376 refused at every address), no route of the outer Agent Server at any address, no host service through SLIRP, and no management, Owner, admin or bot credential in its files or process environments; not privileged, every capability set empty, no_new_privs, seccomp and AppArmor (provisioning.agent_server.jobs). Note: Verified live on a disposable provisioned guest (guest.py job-access-probe, before and after a guest restart) from inside two disposable conversation containers, as their default user (root is not obtainable): every declared engine socket, the engine ports and host aliases over TCP, all 193 routes at every address, and the outer key and Gitea bot token fingerprints. No agent workload, LLM or repository content ran. | yes | S-01.3.2 | `evidence/S-01.3.2-job-daemon-and-management-access.md` |
| `ci-job` | The Gitea Actions job token with restricted repository and workflow token maxima. Note: Unknown at S-01.2.2: no CI runner is selected or pinned and Gitea Actions is off (fd-ci-runner-unpinned). | no | S-01.2.2 | - |
| `ci-job` | A disposable container or VM on a dedicated runner host: no host-mode execution, host Docker socket, user home, Owner credential or release, signing or deployment secret. Note: Unknown at S-01.2.2: no CI runner is selected or pinned and Gitea Actions is off (fd-ci-runner-unpinned). | no | S-01.2.2 | - |
| `ci-job` | The runner containment profile carries the job constraints of S-01.3.2: no engine socket or engine TCP endpoint reachable from a job; no management key, Owner, admin or bot token in its environment or readable filesystem; no privileged mode, added capability, device or host namespace; no host-path mount beyond the scoped workspace. Note: Declared at S-01.3.2 (provisioning.agent_server.jobs.ci), not verified: no CI runner exists. The profile is Q-02.2.1; Q-02.2.2 proves it and Q-02.3.2 attempts the engine socket from a hostile job. | no | Q-02.2.2 | - |
| `ci-runner-service` | The runner's registration secret on the dedicated runner host, unreachable from the job filesystem. Note: Unknown at S-01.2.2: no CI runner is selected or pinned (fd-ci-runner-unpinned). | no | S-01.2.2 | - |
| `management-dispatcher` | The sole holder of the Agent Server session key, on the trusted side; admission to the create and admin routes is limited to its identity and network (S-01.3.1). Note: Not realized at S-01.3.1: no dispatcher exists, and during bootstrap the Owner's account holds the key through the operator login. The admission half is verified (next row); sole custody of the key is decided with the dispatcher (E-01.2.x). | no | E-01.2.2 | - |
| `management-dispatcher` | Admission to the Agent Server's management API by key and by network: every key-gated route refuses a missing or wrong key (HTTP 401, WebSocket close 4001 or handshake 403); the server does not start without a valid key; the listener is on the guest loopback only and no conversation container reaches it, the guest itself or another container (container guard, icc off). The per-route allowlist of the dispatcher (routes.json) is policy for the dispatcher, not a server control. Note: Verified live on a disposable provisioned guest (guest.py admission-probe, before and after a guest restart): all 193 routes of the inventory, and connections from two conversation containers to every guest address. | yes | S-01.3.1 | `evidence/S-01.3.1-management-api-admission.md` |
| `management-dispatcher` | Custodian of the standing bot credentials; delivers each agent role token per attempt into the attempt environment only, with fingerprints only in records. Note: Not verified at S-01.2.2: no dispatcher exists. Bootstrap custody observed instead: the Credential Manager entries "AIEH Gitea bot <role>" of the Owner's account, written by owner-os-account; records carry fingerprints only. | no | S-01.2.2 | `evidence/S-01.2.2-segregated-credentials.md` |
| `integration-service` | Its own process identity with custody of the integration store and no access to the effects store. Note: Unknown at S-01.2.2: not a Gitea principal and not built. | no | S-01.2.2 | - |
| `authorization-verifier` | A read-only Gitea credential for the verifier's own identity; it never executes. Note: Verified at S-01.2.2: aieh-bot-verifier, a restricted, non-administrator Bot account; token scope read:repository only; it read the protected default branch, a PR with merged_by and a blob; every write probed (push, PR, review, merge, settings) was refused by scope. | yes | S-01.2.2 | `evidence/S-01.2.2-segregated-credentials.md` |
| `privileged-executor` | A separate Windows service identity created by Owner act A4 at G-04.2.1, with Modify on the effects root only. Note: Not applicable at S-01.2.2: no executor exists (G-04.x); executor-action denial is carried to G-04.2.1. | no | G-04.2.1 | - |
| `privileged-executor` | It issues nothing and holds no Gitea write credential. Note: Not applicable at S-01.2.2: no executor exists (G-04.x); executor-action denial is carried to G-04.2.1. | no | G-04.2.1 | - |
| `inference-broker` | The host-side broker behind the guest's inference endpoint class; it alone issues per-attempt inference access. Note: Realization unknown: no plan leaf builds the broker (a plan gap routed to the Owner). Unknown at S-01.2.2. | no | S-01.2.2 | - |
| `release-job-environment` | Not decided: Q-02.4 and G-04.2.1 decide the principal and its credential. Note: Unknown at S-01.2.2: undecided. | no | S-01.2.2 | - |

### Target and bootstrap

| Role | Target | Bootstrap: observed performer | Bootstrap: note |
|---|---|---|---|
| `owner` | Owner-only operations, the Gitea Owner account on the authorization branch's merge allowlist only, UAC consent for specifically authorized elevated acts, public-repository push, and code merges into protected integration branches. Never a personal access token in any agent or CI context. | `owner` | The Owner directs the work and approves privileged host acts by UAC consent. The Gitea Owner account aieh-owner exists (F-06.1); its credential is harness-held (Owner directive of 2026-11-07: the Owner never signs in to Gitea), and how the Owner identity is used internally is to be decided; it is the only merge-allowlist identity of the S-01.2.2 fixture; public pushes run from the Owner's account. |
| `owner-os-account` | The Owner's interactive host account: guest lifecycle, exec, exchange, session-key export and provisioning fetch. It holds no executor or service identity, and no executor credential is stored in its credential store. | `owner-os-account` | Host tooling under this account performs every operation of this row, and the host-side bootstrap agents share the account (fd-bootstrap-shared-identity). |
| `gitea-site-admin` | Site administration of Gitea under the branch rules; issues Gitea identities, bot accounts, protection rules and runner registration secrets. Never exposed to agents or CI. | `owner-os-account` | Gitea 28.3.0 runs on host loopback (F-06.1). aieh-site-admin holds a harness-held password set by task gitea:finalize-credentials (Owner directive of 2026-11-07: no Owner sign-in), which also revoked its leftover tokens. Gitea administration during bootstrap is performed by the Owner's host account: identities, bots and tokens through Gitea's CLI, the fixture as the site administrator through the API. |
| `planner` | Its own Gitea bot identity and token: read the repositories in scope, push `work/*` proposal branches and open PRs whose writes are planning artefacts only. | none | Its Gitea bot account and token exist (S-01.2.2), in the Owner account's Credential Manager pending the dispatcher; no agent workload has run or held the token (decision 0003, C6). |
| `builder` | Its own Gitea bot identity and token: read the repositories in scope, push `work/*` proposal branches and open PRs. | none | Its Gitea bot account and token exist (S-01.2.2), in the Owner account's Credential Manager pending the dispatcher; no agent workload has run or held the token (decision 0003, C6). |
| `reviewer` | Its own Gitea bot identity and token: read the PR and diff and submit reviews as evidence. | none | Its Gitea bot account and token exist (S-01.2.2), in the Owner account's Credential Manager pending the dispatcher; no agent workload has run or held the token (decision 0003, C6). |
| `ci-job` | The job token's repository context for its own run only. | none | No CI runner is selected or pinned, and no CI job has run. |
| `ci-runner-service` | The registration secret, unreachable from jobs. | none | No CI runner is selected or pinned. |
| `management-dispatcher` | Sole holder of the Agent Server session key; the Agent Server management operations; custodian and per-attempt deliverer of the standing bot credentials. It writes no effect receipt. Custodian of `cred-gitea-bot-planner`, `cred-gitea-bot-builder`, `cred-gitea-bot-reviewer`. | `owner-os-account` | No dispatcher exists. The Owner's account performs conversation create and runtime control through the operator login (see the sunset map). |
| `integration-service` | Integration-store writes. Never the Owner approval credential or an effect receipt. | `owner-os-account` | The integration store stays in Owner-session custody during bootstrap (decision 0004, point 9). |
| `authorization-verifier` | A read-only Gitea credential: reads the protected ref, the PR, merged_by, the exact blob and the policy. | none | Not built. Its read-only Gitea identity aieh-bot-verifier and token exist (S-01.2.2); no verifier has used them. |
| `privileged-executor` | The executor identity and target secrets, effect application and effect receipts. It issues nothing and writes nothing in Gitea. | none | Nothing live exists: no effects root, executor principal, service or scheduled task (decision 0004, Current facts). |
| `inference-broker` | The provider credential and per-attempt inference access. | none | The inference endpoint class is deferred, and no plan leaf builds the broker. |
| `release-job-environment` | Narrowly authorized release or deployment jobs in a separately credentialed environment, after verifying the protected revision. Invariant: Trusted side only: never ci-job or any agent role. Invariant: Its credential is of a privileged class. Invariant: Activation goes through op-effect-apply. Invariant: The signing identity is distinct from the executor's effect identity unless Q-02.4 decides otherwise. | none | Undecided (fd-release-job-principal); no release has been signed or deployed. |
| `guest-root` | Root inside the execution guest, reached only through cloud-init at create and declared systemd units. | `guest-root` | Root acts only in the single-use provision step and the facts reporters. |
| `guest-service-openhands` | The guest's own service principal for the Agent Server and the guest's Docker API. It validates the session key but is not a role that uses it. | `guest-service-openhands` | Runs the outer Agent Server and starts conversation containers through the guest's Docker. |
| `guest-login-agent` | An operator and provisioning login, never an agent role token: exec is never offered to agents. Whether it keeps read access to the session key is S-01.3.1's decision. | `owner-os-account` | Host tooling uses this login for exec, exchange, the provisioning upload and the facts requests; it can read the Agent Server session key today. |

### Non-roles and the sunset map

`bootstrap-host-agents` (principal `bootstrap-host-agents`, independently isolated: no): no grants; inherits the reach of `owner-os-account`; findings `fd-bootstrap-shared-identity`.

| Operations | Move at | To (inventory principal) | Scope |
|---|---|---|---|
| `op-as-conversation-create`, `op-as-runtime-stop`, `op-as-runtime-reprovision`, `op-as-conversation-delete`, `op-as-management-read` | S-01.3.1 | `management-dispatcher` | Conversation create and runtime control on the Agent Server management API |
| `op-effect-apply`, `op-effect-receipt-write`, `op-effect-store-custody` | G-04.2.1 | `owner`, `privileged-executor` | Privileged effects and effect-store custody |
| `op-gitea-administration` | none (Gitea runs since F-06.1, but no plan leaf moves its administration from the Owner's account (Gitea's CLI) to an independently isolated site-administrator principal: a plan gap routed to the Owner.) | `gitea-site-admin` | Gitea administration |
<!-- END GENERATED -->

## What the checker enforces

`python -I -B tools/check_role_tokens.py` (`task policy:check`) exits 0 only when:

1. every role binds to exactly one existing principal, its `agent_controlled` equals
   the principal's, and every granted or denied id exists;
2. no agent-controlled role is granted an Owner-only operation, an executor operation,
   `op-gitea-administration`, an `op-as-*` operation, `cap-code-merge-integration` or
   another capability of privileged authority, a credential of Owner, admin, executor or
   management authority, or custody of a credential; and no provider credential is ever
   a role token;
3. no grant is made to a principal that is not independently isolated, and the non-role
   rows carry no grants;
4. every granted operation's inventory principal is the role's principal;
5. every agent-controlled role denies the baseline, and no role grants what it denies;
6. every granted credential has exactly one issuance row and one revocation row; the
   issuer matches the inventory, the revoker is the issuer's role, the executor issues
   and delivers nothing, the triggers come from the closed set, the rotation owner is
   never null without a finding and matches the inventory, and only an executor
   credential's row sends its receipt to the effects store;
7. a realization marked verified carries evidence, and every `verify_at` is a plan
   leaf;
8. the sunset map names every planned operation that the Owner's account performs
   today, and each entry names its leaf or, where none exists, the gap;
9. every inventory operation and credential is granted to some role; no row carries an
   exclusion flag or an unknown key;
10. every status, link, blueprint anchor and plan id follows the inventory's rules;
11. no machine path (drive letter, UNC path, user-profile variable) appears, and this
    README names every role and capability id and its generated tables equal
    `--render`.

`--list` prints each role with its principal and grant counts; `--render` prints the
generated tables. The negative cases are in
[`tools/tests/test_check_role_tokens.py`](../tools/tests/test_check_role_tokens.py).
When the matrix changes, edit the JSON, replace the generated block with the output of
`--render`, and run the checker.

## Sources

- Blueprint: `#security`, `#authorization-qualification`, `#governance-architecture`,
  `#quality-pipeline`, `#agent-skills`, `#containment-architecture`,
  `#integration-contracts`, `#decisions`.
- Plan: S-01.2.1, S-01.2.2, S-01.3.1, S-01.3.2, Q-02.2.1, Q-02.2.2, Q-02.3.2, Q-02.4, D-01.2, G-04.2.1.
- Decisions: [0003](../decisions/0003-execution-guest-providers-and-isolation-contract.md),
  [0004](../decisions/0004-privileged-effect-store-custody-and-restore-semantics.md)
  (Owner clarifications 5 and 7),
  [0006](../decisions/0006-guest-provisioning-channel-and-image-conformance.md),
  [0007](../decisions/0007-role-token-matrix-and-revocation-contract.md).
- Inventory: [`security/inventory.json`](../security/inventory.json) and its
  [README](../security/README.md).
