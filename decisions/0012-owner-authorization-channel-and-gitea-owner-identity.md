# 0012 - Owner authorization channel and the Gitea Owner identity

Status: Proposed (Architect) - 2026-11-07, following the Owner directive of 2026-11-07 ("Owner authorization must flow through the harness's governance mechanisms, not through a requirement that I manually approve merges in Gitea"). Owner confirmations 1 to 3 given 2026-11-07 (plan notes of P-04.2). Amended at P-04.2's offline build (2026-11-10, Builder proposal for the Overseer): the record's `format` field (Overseer ruling at P-04.1), the policy check's observable scope in Gitea 28.3.0, the manifest fields the recorder reads, and the recorder's state and receipt kind. Overseer rulings (2026-11-10): the proposed lost-answer settle rule is rejected (point 8); on the protection rules `aieh-owner` cannot read, the Overseer recommends detection rather than prevention (point 6), for the Owner's decision (Owner action OA-15 in `evidence/bootstrap-log.md`). The record is Proposed until P-04.2's live exercise and that decision.

**Gate:** architecture consultation at gates A, B and G.

**Scope.**
- It refines decision 0007 (point 4, Owner confirmation 1 and the `owner` row) and decision 0008 (point 2).
- It works within blueprint `#authorization-qualification`, `#decisions`, `#authority`, `#integration-contracts`, `#experience` and `#sequence-maps`, under decision 0010's threat model.
- It installs, issues, configures and merges nothing.

**Supersedes:** none. Within this repository, it supersedes two blueprint passages as they bear on the Owner's act: step 16 of the Owner's sequence ("Owner signs in independently to Gitea and merges the exact protected operation manifest; a chat click is not the authorization", in `#sequence-maps`, which the plan cites as `#experience` step 16) and the `#decisions` phrase "no automation merge". The blueprint is reconciled by a maintenance item, as M-1 did for decision 0001.

## Context
- Blueprint 10A makes a protected, Owner-only Gitea merge of an exact operation manifest the independent authorization record. `#authority` names the authenticated Gitea decision record as the system of record for consequential Owner authorization.
- The Owner has directed that he never operates Gitea.
- `aieh-owner` exists (F-06.1). It is the only identity on the merge allowlist of every protected rule in the S-01.2.2 fixture, and it holds no token. Its password is harness-held.
- The S-01.2.2 denials are verified.
- P-04.1 built the shared Owner decision record (`owner-decision/v1`) and the acceptance recorder. P-04.2 built the authorization recorder offline (against a fake Gitea); no authorization repository or verifier exists (`fd-owner-authorization-record`, narrowed).

## Decision
1. **The record stays.** A merge commit on the protected authorization branch, merged by `aieh-owner`, remains the authorization record that the verifier (G-04.3) and the executor (G-04.2) read. Nothing outside Gitea's protected ref authorizes an effect.
2. **The act moves.** The Owner's authorization is a recorded decision, never a Gitea operation. A deterministic, non-model authorization recorder captures it. This recorder is the same class of component as decision 0008's acceptance recorder: recording is clerical, and the Owner's statement reference, not the record, is the proof that the Owner decided.
3. **The Gitea Owner identity.** `aieh-owner` represents the Owner's authority in Gitea, not his person. It is a non-administrator account that:
   - is never signed in to and holds no token;
   - is on the merge allowlist of protected branches and on no push allowlist;
   - has its credential harness-held and read by the recorder alone.

   `merged_by: aieh-owner` is read and rendered as "merged under Owner authority by the recorder on decision <id>".
4. **The recorder.** One component, `authorization-recorder`, is custodian of `cred-gitea-owner-account` (the credential provider entry `AIEH Gitea owner`). It is a trusted, non-agent principal.
   - It authenticates by HTTP basic authentication with the password read from the credential provider by name, in memory, for each command, over host loopback.
   - It refuses an entry that names another account or holds anything token-shaped. It mints no token, sends no token, and never uses `sudo`, `force_merge` or auto-merge. It makes merge commits only.
   - No agent, reviewer, CI or model context can invoke it or read its credential. It has no MCP or agent-callable surface.
   - Its own state (`<state>/owner-authorization/` of the managed data root) holds the challenges it issued and the decision records it wrote.
5. **The Owner decision record.** The record shared with decision 0008's acceptance recorder, `owner-decision/v1`, has these fields in this order:
   - `format`: `owner-decision/v1`;
   - `decisionId`: a random UUID, version 4;
   - `kind`: `accept-objective` or `authorize-operation`;
   - `subject`: for `authorize-operation`, `repository`, `pull`, `base`, `head`, `manifest` (`operations/<operation>.json`), `digest` (`sha256:` of the manifest blob), `operation`, and what the manifest declares: `operationKind`, `target`, `expiresAt`;
   - `shown`: the summary presented, the nonce and the challenge's expiry;
   - `statement`: the text verbatim, `attributedTo: owner`, the channel and the reference;
   - `recordedBy`, `recordedAt`.

   A statement attributed to anyone but the Owner, or authored by a model, is refused.
6. **Checks before a merge.** Each failure is a stable refusal. The recorder requires:
   - a fresh, unexpired, unconsumed challenge that it issued itself (in its own state);
   - an Owner-attributed statement naming the operation id, given through an admitted channel;
   - the PR open from a branch of the repository against the protected branch, with the challenged head and manifest blob digest, exactly one added manifest file, a new operation id (not on the protected branch, no receipt that is not failed), and an author other than `aieh-owner`;
   - the manifest and the challenge unexpired, and the PR mergeable;
   - the protection and repository rules as expected, **as far as `aieh-owner` can observe them**: Gitea 28.3.0 serves branch protection rules to repository and site administrators only (`reqToken(), reqAdmin()`), so the recorder compares the repository's merge settings and `aieh-owner`'s permission (`GET /repos/{owner}/{repo}`) and the protected branch's view (`GET .../branches/{branch}`: protected, required approvals, status checks, whether `aieh-owner` can push and merge). The other accounts on the allowlists, force push, `block_admin_merge_override`, `block_on_outdated_branch` and the approvals allowlist are not compared before a merge; **pending the Owner's decision (OA-15)**, the Overseer recommends that this residual is **detected, not prevented**: only a repository or site administrator can change those fields, the agents hold no administrator credential, and the only administrator credentials are the Owner's; a principal that can read the rule (G-03.2's policy check, or the verifier) compares it with `gitea_roles.protection_rules()` and reports drift. Handing an administrator's read to the recorder before each merge would bring an administrator credential into the merge path, a wider custody than the residual it closes;
   - `aieh-owner` non-admin, with zero tokens;
   - single use.

   The merge names `head_commit_id`; Gitea refuses it with 409 if the head has changed.
7. **The manifest.** Until G-04.1.1 types it, the recorder reads four fields of `operations/<id>.json` (a UTF-8 JSON object of at most 64 KiB): `operation` (equal to the file's id), `kind`, `target` (one line) and `expiresAt` (`YYYY-MM-DDTHH:MM:SSZ`). G-04.1.1 keeps these fields or amends the recorder.
8. **Evidence.**
   - A write-ahead receipt in the integration store, never the effects store: its own append-only kind, operation key `owner-authorization/v1/<nonce>`, format `aieh-owner-authorization/1`, holding the decision, the approved head, the digest, the trailers and the merge call; reserved before the merge is sent, ending `confirmed`, `failed` (Gitea refused; nothing merged) or `unknown`.
   - Merge-commit trailers: `AIEH-Decision-Id`, `AIEH-Decision-Channel`, `AIEH-Approved-Head`, `AIEH-Manifest-Digest`, `AIEH-Statement-Ref`, `AIEH-Recorder`.
   - Gitea's PR record and audit log (`[audit] RECORD_OUTPUT = database`, `RETENTION_DAYS = 0`).
   - A post-merge read-back of the protected ref, the merge's parents (the approved head second), the trailers, the manifest digest at the merge and `merged_by`.

   A lost answer (or a 5xx, or a read-back that disagrees) is `unknown`. It is resolved by reading the pull request and its merge commit, never by merging again: `confirmed` when the merge reads back as recorded; `failed` when the pull request was merged otherwise or was closed without being merged; otherwise, including a pull request still open and unmerged however long after the merge was sent, it stays `unknown` (no time-based inference; Overseer ruling, 2026-11-10).
9. **Authentic channel.**
   - **Target:** an authenticated Owner host session (`cred-owner-ui-access`, decided at S-01.3.1) acting on the outcome card. The statement reference is the Owner's message id (U-02.1). Not admitted until it exists.
   - **Bootstrap (`main-session`, the one admitted channel today):** the Owner's decision in the main-session conversation, given after the recorder's challenge is presented. The Overseer transcribes it verbatim and records it in `evidence/bootstrap-log.md` with the decision id. The recorder is run only in the main session on an Owner decision, never by a dispatched Builder or Reviewer.

   Bootstrap proves a declared Owner decision bound to an exact revision, not an authenticated Owner. `fd-owner-authorization-record` is narrowed, not closed.
10. **Verifier.** `merged_by == aieh-owner` is necessary but not sufficient. The merge commit must carry a well-formed trailer whose approved head is a parent of the merge and whose digest equals the manifest blob at the protected ref. A protected-branch merge without a recorder trailer or receipt is reported as `unrecorded-merge`.
11. **Separation of duties.** These are three identities, with three credentials and three code paths:
    - the proposer: an agent bot;
    - the authorizer: the Owner, through the recorder, as `aieh-owner`;
    - the executor: the G-04.2.1 principal, with no Gitea write credential.
12. **Code merges.** D-01.2 decides the eligible merger for code PRs under blueprint `#workflow` ("permitted automation ... if the repository's policy permits it"). An interactive Owner merge is not assumed anywhere.
13. **Threat model.** Decision 0010 applies.
    - Prevented by Gitea's allowlists, its protection and credential custody: bot, CI and reviewer self-authorization; merging anything but the approved head; replay; the site admin's direct merge.
    - Detected, not prevented, and therefore disclosed: the administrator's `sudo` path, protection drift outside what `aieh-owner` can observe, token drift, and same-account processes (decision 0010: any process of the Owner's account can read the credential provider entry). Detection is by receipt reconciliation, trailers and the audit log.

## Consequences
- **Plan** (integrity process; already amended 2026-11-07 for the new leaf and wording):
  - P-04.2 (the recorder; deps P-04.1, S-01.2.2);
  - G-03.2 gains P-04.2; wording of G-03.1, G-03.2, G-04.3.1, G-04.3.2, D-01.2 and P-04.1;
  - the P-04 parent proof covers both recorders.
- **`security/inventory.json`** (done at P-04.2): a principal `authorization-recorder`, custodian (manager) of `cred-gitea-owner-account`; `op-protected-merge` keeps principal `owner`, with `planned_performer: authorization-recorder`; `fd-owner-authorization-record` narrowed and carried to G-03.1 and G-04.x.
- **`policy/role-tokens.json`** (done at P-04.2): the `owner` row's realization and issuance text, and a custodian row `authorization-recorder` (`custodian_of`, no grants).
- **Blueprint maintenance item** for `#sequence-maps` step 16 (cited as `#experience` step 16) and the `#decisions` phrase "no automation merge".
- **Verified at P-04.2 against a fake Gitea only** (in memory and over a loopback HTTP server): the refusals, the single merge, the receipt, the trailers, the read-back and the lost-answer resolution.
- **Not verified until the live exercise on the S-01.2.2 fixture (an Owner-approved act):**
  - that `head_commit_id` causes a 409 on a changed head;
  - trailer preservation in the merge commit body;
  - a basic-auth merge as `aieh-owner`;
  - the read-back fields as Gitea 28.3.0 returns them;
  - that the Owner credential exists only in its provider entry (the exercise's inspection);
  - audit event coverage.

## Owner confirmation
1. The bootstrap channel of point 9, with its disclosed limit. (Given 2026-11-07.)
2. That the harness may perform `aieh-owner` merges on recorded Owner decisions (point 4). (Given 2026-11-07.)
3. That `aieh-owner` stays the Owner-authority identity (point 3), rather than a new recorder-named Bot. (Given 2026-11-07.)
4. For information: audit logging is on with unlimited retention, and D-01.2 decides code merges.

## Evidence
- The Owner directive of 2026-11-07 and the Owner decisions of 2026-11-07 (plan notes of P-04.2).
- Decisions 0007, 0008 and 0010.
- `evidence/F-06.1`, `evidence/S-01.2.2`, `evidence/P-04.1` and `evidence/P-04.2`.
- `policy/role-tokens.json` and `security/inventory.json`.
- The blueprint sections cited above.
- Gitea 28.3.0 source at the tag: `services/forms/repo_form.go` (`MergePullRequestForm.HeadCommitID`), `routers/api/v1/repo/pull.go` (`MergePullRequest`: `ErrSHADoesNotMatch` -> 409 "head out of date"; the message is the title, a blank line, then the message), `services/pull/merge.go` and `merge_prepare.go` (`createTemporaryRepoForMerge` compares the head), `services/pull/merge_merge.go` (`merge --no-ff`), `routers/api/v1/api.go` (`branch_protections` behind `reqToken(), reqAdmin()`; `/users/{username}/tokens` behind `reqSelfOrAdmin(), reqBasicOrRevProxyAuth()`), `services/convert/convert.go` (`ToBranch`), `services/convert/repository.go`, `routers/api/v1/repo/collaborators.go`; read, not exercised.
- This consultation.
