# Owner decisions

Plan group P-04, "Record Owner decisions": Owner decisions are recorded by deterministic, non-model
recorders in one shared Owner decision-record shape. This directory holds that shape and the two
recorders:

- the **Owner decision record** (`owner-decision/v1`, [`owner_decision.py`](owner_decision.py));
- the **acceptance recorder** (plan leaf P-04.1,
  [`acceptance_recorder.py`](acceptance_recorder.py)): it records the Owner's acceptance of an
  Objective item of an intent-driven OpenSpec change and mints the outcome id, in the form of
  [decision 0008](../../decisions/0008-outcome-identity-assignment-form-and-record.md);
- the **Owner authorization recorder** (plan leaf P-04.2,
  [`authorization_recorder.py`](authorization_recorder.py); decision 0012): it records
  the Owner's authorization of one exact operation manifest and merges it into the protected branch
  as `aieh-owner` (below).

Standard library only, plus the shared repository-access module (Dulwich, from the Python tools set;
[decision 0014](../../decisions/0014-dulwich-adoption-scope-and-repository-access-contracts.md)) and
the lineage objective resolver. The acceptance recorder launches no process, uses no network, reads
no credential and does not touch the managed data root. The authorization recorder launches no
process either; it talks to the managed Gitea on host loopback, reads the two credentials it is
custodian of (`aieh-owner`'s password, and its protection check's read-only token), and keeps its state
and receipts under the managed data root (below).

## Files

| Path | What |
|---|---|
| `owner_decision.py` | The shared record: its fields, the kinds, the `accept-objective` and `authorize-operation` subjects, `statement_verdict` and `check_record` |
| `acceptance_recorder.py` | `prepare` and `record`, the refusal codes and remedies, the edits of `proposal.md` and `.openspec.yaml`, and the command line |
| `authorization_recorder.py` | The authorization recorder: `prepare`, `record` and `resolve`, the refusal codes and remedies, the expected policy, the protection verifier's seam and the command line's verifier (`protection_verifier`: the Gitea integration's protection check), the session as `aieh-owner`, the receipt, the merge and its read-back, and the command line |
| `tests/test_owner_decision.py` | The record's shape and every statement verdict (unit) |
| `tests/test_recorder_edits.py` | The recorder's edits, byte for byte, line endings included; every code has a remedy (unit) |
| `tests/test_acceptance_recorder.py` | `prepare` and `record` on throwaway fixture repositories: the resolver round trip, the id kept on re-recording, the shared shape, every refusal; the command line (integration) |
| `tests/test_live_openspec.py` | Live, skipped unless `AIEH_OPENSPEC` names the pinned OpenSpec 1.16.0: `validate --strict` accepts a change holding `owner-decisions/` and `x-outcomes`, `archive --yes` moves the decision record with the change byte for byte, and the outcome resolves at its archived path (e2e) |
| `tests/owner_fixture.py` | The fixture project repository (two changes from the P-01.2 recording) and the example record; `--record` rewrites it |
| `tests/fixtures/accept-objective.decision.json` | The example decision record (synthetic statement, fixed clock, nonce and ids) |
| `tests/fake_gitea.py` | A fake Gitea 28.3.0 (the slice the authorization recorder uses, as read in the pinned source, and a bot's proposal routes and the precondition's reads (`GET /token`, the open pull requests) for the live exercise's phase plumbing; the protection auditor's requests go to `integrations/gitea/tests/protection_fake.py`), callable in memory or served by an in-process HTTP server on 127.0.0.1 that can drop an answer; and a fixture credential provider |
| `tests/authz_support.py` | The authorization recorder's per-test fixture: a fake Gitea, a fixture provider, the recorder's state and an integration store of its own, a fixed clock, and a fake protection verifier (`verified` unless a test scripts it) |
| `tests/test_authorization_units.py` | The `authorize-operation` subject, the trailers and the merge message, the policy comparison, the protection verifier's seam (only a well-formed verdict counts), the session's fixed calls, the credential checks, the codes and remedies, a fixture context never reaching the managed root, the command line (unit) |
| `tests/test_authorization_recorder.py` | The plan's proof over HTTP on loopback: one merge per recorded decision, bound to the head and the digest, with the receipt and the trailers; every refusal with its code and no merge; fail closed on every protection answer but `verified` (no verifier included), the verifier the last read before the receipt and the merge, the bracket after it; the command line's protection check against the fake auditor (verified, drift, every unverifiable state, a rule changed across the merge, no credential read for a refused statement); every bot token refused; no token minted; a lost answer resolved by reading (integration) |
| `tests/test_live_authorization.py` | The live exercise on the S-01.2.2 fixture in two phases with the Owner's own decision between them (and `rechallenge`, regenerating expired challenges for the operations already presented), each skipped unless `AIEH_AUTHZ_RECORDER_LIVE` names it (`prepare`, then `record`; e2e) |
| `tests/test_live_phases.py` | The live exercise's phase plumbing against the fake Gitea: phase rechallenge (fresh challenges for the same operations with reads only, the record phase on them, every refusal leaving the run directory unchanged); prepare's precondition (the baseline variable, the protection check's digest, every role's identity and scopes, open pull requests and existing branches, each refused with zero writes), the auditor's control on a nonexistent pull request, the stopping rule after every control attempt, the presentation, the statement-file refusals, the expected outcome without a verifier and with one that does not verify, the stale-head control and each refusal it can observe (finding F14), the SECURITY FAILURE stops, the protection check end to end (unit) |

## The Owner decision record (`owner-decision/v1`)

One JSON object per decision, with exactly these fields in this order:

| Field | Value |
|---|---|
| `format` | `owner-decision/v1` |
| `decisionId` | a random UUID, version 4, canonical lower-case text |
| `kind` | `accept-objective` (P-04.1) or `authorize-operation` (P-04.2) |
| `subject` | what was decided on; for `accept-objective`: `change`, `item` (`O<n>`), `outcome` (the outcome id), `revision` (the commit the summary was shown at) and `proposal` (the sha256 of the change's `proposal.md` there); for `authorize-operation`: `repository` (`owner/name`), `pull`, `base` (the protected branch), `head` (the exact head), `manifest` (`operations/<operation>.json`), `digest` (`sha256:` of its blob), `operation`, and what the manifest declares: `operationKind`, `target` and `expiresAt` |
| `shown` | what the recorder presented before the decision: `summary` (the text shown), `nonce` (32 lower-case hex digits) and `expiresAt` (the challenge's expiry) |
| `statement` | the decision as stated: `text` (verbatim), `attributedTo` (`owner`), `channel` (a lower-case token, such as `main-session`) and `reference` (where the statement is kept) |
| `recordedBy` | who ran the recorder: `owner`, `agent:<id>` or `person:<id>` |
| `recordedAt` | `YYYY-MM-DDTHH:MM:SSZ` (UTC) |

Attributions and references use the intent-record/v1 grammar. The file is JSON with a two-space
indent, the fields in this order, UTF-8 kept, LF. The example is
[`tests/fixtures/accept-objective.decision.json`](tests/fixtures/accept-objective.decision.json).

The record is **clerical**. It says what was shown, what was said, who recorded it and when. It
does not authenticate the Owner: `attributedTo` and `channel` are declared by whoever transcribed
the statement, and the acceptance reference, not the record, is the proof that the Owner accepted
(decision 0008, point 2).

**How a statement is judged** (`statement_verdict`, from the statement alone, in this order):

| Verdict | When |
|---|---|
| missing | no statement, an empty `text`, or no `reference` (absent, empty or `missing:<what>`) |
| authored by a model | `attributedTo` is `agent:<id>` (an agent is a model), or the `reference` is an engineering conversation of the Agent Server (`openhands:`, the lineage `attempt` kind: a model's own transcript) |
| not attributed to the Owner | `attributedTo` is anything but `owner` (`person:<id>`, any other text, or absent) |
| malformed | a field outside the four, a `channel` that is not a lower-case token, or a `reference` outside the intent-record/v1 grammar |

`recordedBy` may be an agent: during bootstrap the Overseer transcribes the Owner's reply (the
P-04.2 bootstrap channel). Recording is clerical; accepting is the Owner's.

## The acceptance recorder (plan leaf P-04.1)

Two steps, as the Owner sees them:

1. **`prepare`** reads the change at the project repository's `HEAD` and prints a challenge
   (`owner-decision-challenge/v1`): the summary to show the Owner (the Objective item, its
   attribution and source, its current authority and outcome, the acceptance criteria that cite
   it, the proposal's sha256), a random nonce and an expiry (60 minutes by default, at most a
   week), bound to that commit and to the proposal's digest. It writes nothing.
2. **`record`** takes the challenge and the Owner's statement and, unless a refusal below
   applies, makes **one commit** on the checked-out branch, in process, through
   `repository_access.Repository.write_commit` (no hook, no process; decision 0014 sections 6
   and 8):
   - the decision record at `openspec/changes/<change>/owner-decisions/<decisionId>.json`;
   - the item set to `authority: accepted` and `acceptance: <the statement's reference>` in
     `proposal.md` (only those lines change; line endings are kept);
   - the outcome id, minted as a random UUID version 4, declared in `.openspec.yaml` as
     `x-outcomes: {<id>: {item: O<n>, acceptance: <reference>}}` (decision 0008, point 4);
   - before the branch moves, `outcome:<id>@<new commit>` must resolve through the lineage
     objective resolver with the declared change, item and acceptance; otherwise nothing visible
     changes (`RESOLUTION_FAILED`).

   OpenSpec 1.16.0 accepts such a change (`validate --strict`), and `archive` moves the decision
   records with it byte for byte; the outcome then resolves at its archived path
   (`test_live_openspec.py`, opt-in).

   The commit message ends with the trailers `AIEH-Decision-Id`, `AIEH-Outcome-Id` and
   `AIEH-Recorder: acceptance-recorder/1`.

**Minting once.** The id is minted only by `record`, only with an acceptance reference, and never
again for the same item (decision 0008, point 2). An item that already has an id is refused
(`OUTCOME_ALREADY_MINTED`); `--amend` records a new Owner acceptance of it (decision 0008, point 5),
keeping the id and rewriting the acceptance in both the item and the declaration, with a new
decision record. An objective accepted by hand without an id is minted once on its first
recording.

**The acceptance reference** must be a message of the Owner's conversation
(`conversation:<thread>/<message>`, the lineage `message` kind) or an accepted decision record
(`decision:<id>`), and never the request itself (an Original Quote's `source`; intent-record/v1
invariant 4).

### Refusals

Each refusal has a stable code and its remedy (`acceptance-recorder: CODE: detail. Remedy: ...`,
exit 2), and changes nothing: the branch, the work tree and the index are as they were.

| Code | Refused when |
|---|---|
| `ACCEPTANCE_MISSING` | the statement is missing, has no text, or names no reference |
| `ACCEPTANCE_MODEL_AUTHORED` | the statement is authored by a model (above) |
| `STATEMENT_NOT_OWNER` | the statement is attributed to anyone but the Owner |
| `STATEMENT_INVALID` | the statement is malformed (above), or its file is not JSON |
| `ACCEPTANCE_REFERENCE_INVALID` | the reference is neither an Owner message nor `decision:<id>`, or is the request itself |
| `ACCEPTANCE_ALREADY_RECORDED` | an amendment names the acceptance the item already has |
| `OUTCOME_ALREADY_MINTED` | the item already has its outcome id (re-minting); use `--amend` |
| `OUTCOME_NOT_MINTED` | `--amend` for an item without an id |
| `RECORDED_BY_INVALID`, `IDENTITY_INVALID` | `--recorded-by` is not an attribution; `--identity` is not `Name <email>` |
| `CHALLENGE_MISSING` | no challenge |
| `CHALLENGE_INVALID` | not `prepare`'s challenge for this project: another shape, an unknown revision, or a summary or digest that is not what `prepare` shows at that revision |
| `CHALLENGE_EXPIRED` | the challenge's expiry has passed |
| `CHALLENGE_CONSUMED` | a decision on the challenge's nonce is already recorded |
| `CHALLENGE_STALE` | the proposal changed after the summary was shown |
| `CHANGE_MISSING`, `ITEM_NOT_OBJECTIVE`, `OBJECT_NAME_INVALID` | no such active change; not an Objective item; an unusable change name (`archive`, a path) |
| `INTENT_RECORD_INVALID` | the proposal is not a valid intent-record/v1 record (every check but the quotes' sources), before or after the edit |
| `OUTCOME_METADATA_INVALID` | `.openspec.yaml`'s `x-outcomes` is not decision 0008's form, declares the item twice, or a committed decision record is malformed |
| `HOOKS_UNSUPPORTED` | the repository has client hooks (decision 0014 section 6) |
| `COMMIT_REFUSED` | the repository module refused the commit: the change's files have local changes, HEAD is not a branch or moved, signing is configured, or the index cannot be rewritten (`details['reason']`) |
| `RESOLUTION_FAILED` | the new commit's outcome does not resolve as declared; nothing was committed |
| `PROJECT_UNAVAILABLE`, `GIT_FAILED` | not a work tree with a commit, or Dulwich is not importable; the repository could not be read |

## The Owner authorization recorder (plan leaf P-04.2)

The record of an Owner authorization is a merge commit on the protected branch of the authorization
repository, merged by the Gitea account `aieh-owner`; the Owner's act is a recorded decision, never a
Gitea operation (decision 0012). The recorder is the sole custodian of
`cred-gitea-owner-account`: it reads the credential provider entry `AIEH Gitea owner` by name, into
memory, for each command (`integrations/credentials`, plan leaf F-06.3), and authenticates by HTTP
basic authentication over one keep-alive connection to the managed Gitea on 127.0.0.1. It refuses an
entry that names another account or holds anything token-shaped, never sends a token, never mints
one, never uses `sudo`, `force_merge` or auto-merge, and makes merge commits only: its session can
make only its fixed reads and one merge call, whose body is exactly `Do: merge`, the title, the
message, `head_commit_id` and no branch deletion. It has no agent-callable or MCP surface: it is run
only in the main session on an Owner decision.

1. **`prepare OWNER/NAME PULL`** reads the pull request as `aieh-owner` and writes a challenge
   (`owner-authorization-challenge/v1`) to the recorder's own state,
   `<state>/owner-authorization/challenges/<nonce>.json`: the operation, the pull request, its
   exact head, the manifest's digest and what it declares, the summary to show the Owner (the
   manifest itself included), a random nonce and its expiry (30 minutes by default, at most a day).
   It also asks the protection verifier and reports its answer under `protection` (not in the
   challenge); it refuses nothing on it, since it sends nothing.
2. **`record --challenge NONCE --statement FILE --recorded-by ATTRIBUTION`** refuses (below) unless
   every check holds, the protection verifier's answer last (below), then writes the Owner decision
   record (kind `authorize-operation`) to
   `<state>/owner-authorization/decisions/<decisionId>.json` and, before anything is sent, a
   write-ahead receipt of its own append-only kind in the integration store
   (`owner-authorization/v1/<nonce>`, format `aieh-owner-authorization/1`, holding the decision, the
   approved head, the digest, the trailers and the merge call; never the effects store). It merges
   with `Do: merge` and `head_commit_id` and the trailers `AIEH-Decision-Id`,
   `AIEH-Decision-Channel`, `AIEH-Approved-Head`, `AIEH-Manifest-Digest`, `AIEH-Statement-Ref` and
   `AIEH-Recorder: authorization-recorder/1` in the message, then reads back the protected ref (the
   merge commit), its parents (the approved head second), the trailers, the manifest digest at the
   merge and `merged_by`, and asks the protection verifier once more. The receipt ends `confirmed`,
   `failed` (Gitea refused; nothing merged) or `unknown` (the answer was lost, or a 5xx, or the
   read-back disagreed).
3. **`resolve --challenge NONCE`** resolves an `unknown` receipt **by reading**, never by merging:
   `confirmed` when the pull request was merged by `aieh-owner` with this decision's trailers,
   approved head and digest; `failed` only on a definitive read: merged otherwise (not by
   `aieh-owner`, or without this decision's trailers, approved head or digest) or closed without
   being merged. An open, unmerged pull request leaves the receipt `unknown` however long ago the
   merge was sent, since the request may still be completing on the server: the outcome stays
   unknown until a read finds the pull request merged or closed, and closing it is an Owner or
   operator act outside the recorder. A receipt left `reserved` (nothing was sent) becomes `failed`.

`merged_by: aieh-owner` is shown as "merged under Owner authority by the recorder on decision
<id>", never as merged by the Owner. The admitted channel is `main-session` (the bootstrap channel):
the Owner's verbatim reply in the main-session conversation after the challenge is shown,
transcribed by the Overseer and logged with the decision id. It proves a declared decision bound to
an exact revision, not an authenticated Owner.

**The manifest.** The recorder reads four fields of `operations/<id>.json`, a UTF-8 JSON object of
at most 64 KiB: `operation` (equal to the file's id), `kind` (a lower-case token), `target` (one
line) and `expiresAt` (`YYYY-MM-DDTHH:MM:SSZ`). Other fields are allowed: the typed manifest is
plan leaf G-04.1.1's.

**What the policy check can see.** Gitea 28.3.0 serves branch protection rules
(`GET /repos/{owner}/{repo}/branch_protections`) to repository and site administrators only
(`reqToken(), reqAdmin()` in `routers/api/v1/api.go`), and `aieh-owner` is neither. The recorder
therefore compares what a write collaborator can read with the expected policy of the repository
(`Policy`; the S-01.2.2 fixture `aieh-authz-fixture/authz` is the one admitted repository, its
expectation derived from `gitea_roles.protection_rules()`): the repository is private, not archived,
with its default branch, allowing merge commits, and `aieh-owner` holds write but not admin; the
protected branch is protected, `aieh-owner` cannot push to it but can merge, with the rule's required
approvals and no status checks. It cannot see who else is on the merge or push allowlists, force
push, `block_admin_merge_override`, `block_on_outdated_branch`, the approvals allowlist,
`block_on_rejected_reviews`, the bypass allowlist (`enable_bypass_allowlist` and its users and teams,
who may force-merge past every gate), `block_on_codeowner_reviews` or the rule's name
(`Policy.unobservable`): the protection verifier compares them. These checks stay, as a layer beside it.

**The protection verifier (fail closed).** Decision 0012 point 6 (Owner decision OA-15a): the
recorder does not merge unless every security-relevant protection rule is verified by a narrowly
scoped, trusted, read-only check immediately before the merge, and a merge is refused when a
required setting cannot be verified. The recorder calls it through a mechanism-neutral seam:

- `Context.verifier` is a callable `verifier(repository, base, phase)` returning
  `ProtectionVerdict(status, detail, digest=None)`: `status` one of `verified`, `drift`, `unverified`;
  `digest` (`sha256:<64 hex>` or none) identifies what it observed. It is given no credential,
  session or state of the recorder.
- `record` asks it (phase `before-merge`) as the last read before the receipt is reserved and the
  merge is sent, after every other check. `verified` goes on; `drift` refuses `PROTECTION_DRIFT`;
  `unverified`, an exception (its type is recorded, never its text), a malformed answer or **no
  verifier configured** refuses `PROTECTION_UNVERIFIED`. Each refusal sends nothing, writes no
  receipt and no decision record, and leaves the challenge usable until it expires.
- After the read-back it asks once more (phase `after-merge`). Both answers go into the receipt,
  additively in format `aieh-owner-authorization/1`: `protection.before` in the intent, and
  `protection` `{before, after, equal}` in the confirmed detail. An answer that differs from the
  first (verdict or digest) adds `code: PROTECTION_CHANGED_AFTER_MERGE` and its disclosure: the merge
  stands, the receipt stays `confirmed`, the command exits 0 and says so on standard error. It is a
  disclosure (`DISCLOSURES`), not a refusal.
- `prepare` asks it (phase `prepare`) and reports the answer.
- The command line's context (`managed_context`) configures the mechanism the Owner approved on
  2026-11-11 (OA-16): `protection_verifier(provider, port)`, the Gitea integration's protection check
  ([`integrations/gitea/protection_check.py`](../gitea/README.md#the-protection-check-oa-16)), asked in
  process. It reads, as the protection auditor `aieh-bot-protection-audit` (a restricted Bot with
  repository-administrator collaboration on the admitted repository only and a token of scope exactly
  `read:repository`), every rule's 34 fields, the exact rule set and Gitea's precedence for the
  protected branch, the repository's merge settings, the collaborators and their permissions, the
  teams and the deploy keys, and compares them with the harness's total declaration. Its answer's
  detail starts with its code (`VERIFIED`, `DRIFT`, `CREDENTIAL_MISSING`, `CREDENTIAL_REFUSED`,
  `CREDENTIAL_REJECTED`, `AUDITOR_INVALID`, `READ_FAILED`, `VIEW_INVALID`, `PRECEDENCE_UNVERIFIED`,
  `NOT_DECLARED`); everything but `verified` and `drift` is `unverified`. The recorder is custodian of
  the auditor's entry `AIEH Gitea bot protection-audit` too; only the check reads it, by name, into
  memory, for each answer, never in the code path that reads `aieh-owner`'s password, and only once the
  recorder's own checks have passed (a refused statement reads neither credential). Without the
  auditor's entry the check answers `unverified` (`CREDENTIAL_MISSING`) and `record` refuses the merge
  with `PROTECTION_UNVERIFIED`. The auditor was provisioned and the check qualified live on 2026-11-12
  (OA-16 Acts A to D; [record](../../evidence/P-04.2-protection-verifier.md)).
- Gitea evaluates the rule again at the merge itself, and nothing spans the check and the merge: a
  rule changed between them is disclosed by the answer after the merge, not prevented (time of check
  to time of use; the Gitea README describes what Gitea enforces at merge time).

### Refusals

`authorization-recorder: CODE: detail. Remedy: ...`; exit 2 when nothing was sent to Gitea's merge,
1 for a failed or unknown outcome.

| Code | Refused when |
|---|---|
| `CHALLENGE_MISSING`, `CHALLENGE_INVALID`, `CHALLENGE_UNKNOWN` | no challenge; not a nonce, or a malformed state file; a nonce this recorder did not issue (not in its state) |
| `CHALLENGE_EXPIRED`, `CHALLENGE_CONSUMED` | the challenge's expiry has passed; a receipt already exists for the nonce (a replay) |
| `STATEMENT_MISSING`, `STATEMENT_MODEL_AUTHORED`, `STATEMENT_NOT_OWNER`, `STATEMENT_INVALID` | the statement verdicts of the shared record |
| `STATEMENT_OPERATION_MISSING`, `CHANNEL_NOT_ADMITTED` | the statement does not name the operation id; its channel is not admitted |
| `RECORDED_BY_INVALID`, `REPOSITORY_NOT_ADMITTED` | `--recorded-by` is not an attribution; no expected policy for the repository |
| `CREDENTIAL_MISSING`, `CREDENTIAL_REFUSED`, `CREDENTIAL_REJECTED` | no entry; an entry naming another account (a bot) or holding a token-shaped or empty secret, refused before anything is sent; Gitea refuses the password |
| `IDENTITY_NOT_OWNER`, `OWNER_IS_ADMIN`, `OWNER_HAS_TOKEN` | the credential signs in as another account; `aieh-owner` is an administrator; it holds a token |
| `POLICY_DRIFT` | the repository or the protected branch differs from the expected policy |
| `PROTECTION_UNVERIFIED`, `PROTECTION_DRIFT` | the protection verifier did not answer `verified` before the merge: no verifier configured, `unverified` (the command line's check: its detail names why, `CREDENTIAL_MISSING` when the auditor's entry is missing), an exception or a malformed answer; or it found drift |
| `PULL_NOT_FOUND`, `PULL_NOT_OPEN`, `PULL_BASE_WRONG`, `PULL_AUTHOR_OWNER` | no such pull request; not open; not from a branch of the repository into the protected branch; opened by `aieh-owner` |
| `MANIFEST_NOT_SINGLE`, `MANIFEST_INVALID`, `MANIFEST_EXPIRED` | not exactly one added `operations/<id>.json`; the four fields above; the manifest's expiry has passed |
| `HEAD_STALE`, `DIGEST_CHANGED` | the head is not the challenged one (the recorder's check, or Gitea's 409 to `head_commit_id`); the digest is not the challenged one |
| `OPERATION_NOT_NEW`, `PULL_NOT_MERGEABLE` | the manifest is on the protected branch already or the operation has a receipt that is not failed; Gitea does not report the pull request mergeable |
| `MERGE_REFUSED`, `OUTCOME_UNKNOWN` | Gitea refused the merge (405 and others; receipt failed); the answer was lost or did not read back (receipt unknown; run `resolve`) |
| `GITEA_UNAVAILABLE`, `RECEIPT_MISSING` | Gitea did not answer a read; `resolve` for a nonce without a receipt |

One code is a disclosure, not a refusal: `PROTECTION_CHANGED_AFTER_MERGE` in a confirmed receipt's
detail, when the verifier's answer after the merge differs from its answer before it.

## Commands

From the repository root, under the tools interpreter (`<tools python>` is what
`python -I -B integrations/paths/tools_install.py --python` prints):

```
<tools python> -I -B integrations/owner/acceptance_recorder.py prepare --project DIR --change NAME --item O1 --out challenge.json
<tools python> -I -B integrations/owner/acceptance_recorder.py record --project DIR --challenge challenge.json \
    --statement statement.json --recorded-by agent:<id> --identity "Name <email>" [--amend]
<tools python> -I -B -m unittest discover -s integrations/owner/tests -v      # task owner:test
<tools python> -I -B integrations/owner/tests/owner_fixture.py [--record]     # the example record
```

`task owner:accept -- prepare ...` and `task owner:accept -- record ...` run the first two.

The authorization recorder, only in the main session on an Owner decision:

```
<tools python> -I -B integrations/owner/authorization_recorder.py prepare OWNER/NAME PULL [--expires-in-minutes N]
<tools python> -I -B integrations/owner/authorization_recorder.py record --challenge NONCE --statement statement.json \
    --recorded-by agent:<id>
<tools python> -I -B integrations/owner/authorization_recorder.py resolve --challenge NONCE
```

`task owner:authorize -- prepare ...` (and `record`, `resolve`) run them. `--port` names the Gitea
port; by default the managed Gitea's host record gives it.

The live exercise on the S-01.2.2 fixture runs in two phases, each an Owner-approved act and never
run by default (`test_live_authorization.py` lists what each reads, writes and leaves). It never
constructs an Owner statement (Owner decision OA-14):

```
AIEH_AUTHZ_RECORDER_LIVE=prepare AIEH_AUTHZ_RECORDER_RUN_DIR=<an existing, empty directory> \
    AIEH_AUTHZ_RECORDER_PROTECTION_BASELINE=<the expected protection digest, sha256:<64 hex>> \
    <tools python> -I -B -m unittest discover -s integrations/owner/tests -p test_live_authorization.py -v
AIEH_AUTHZ_RECORDER_LIVE=record AIEH_AUTHZ_RECORDER_RUN_DIR=<the same directory> \
    AIEH_AUTHZ_RECORDER_STATEMENT=<the Owner's statement file> \
    <tools python> -I -B -m unittest discover -s integrations/owner/tests -p test_live_authorization.py -v
AIEH_AUTHZ_RECORDER_LIVE=rechallenge AIEH_AUTHZ_RECORDER_RUN_DIR=<the same directory> \
    AIEH_AUTHZ_RECORDER_PROTECTION_BASELINE=<the expected protection digest, sha256:<64 hex>> \
    <tools python> -I -B -m unittest discover -s integrations/owner/tests -p test_live_authorization.py -v
```

1. **prepare**: first a precondition, before any write, each failure refusing the phase with nothing
   written: `AIEH_AUTHZ_RECORDER_PROTECTION_BASELINE` present and `sha256:<64 lower-case hex>` (checked
   before anything is read), and the protection check answering `verified` with exactly that digest;
   `GET /token` of every role's token (the four bots and the protection auditor) naming exactly that
   role's account and declared scopes; no open pull request on the fixture (`GET
   .../pulls?state=open`, as the verifier bot) and neither branch the run would create present; main's
   head recorded. No site administrator's credential is read. Then the builder bot proposes two
   manifests (`operations/<id>.json`) and the reviewer bot approves both; each of the four bots' merge
   of each pull request must be refused (403 or 405); the protection auditor never addresses either:
   its control is the merge of a nonexistent pull request, confirmed absent first (404 to the verifier
   bot), which passes only with 403 and Gitea's scope refusal. After every single attempt main's head
   and both proposals' merged state are read: any 2xx, a proposal merged or main moving is a
   **SECURITY FAILURE** at once (no later control, no challenge, no presentation); a control refused
   otherwise than expected stops the phase too. The recorder's real `prepare` then issues each
   one-time challenge into the run directory's own recorder state (`<run dir>/recorder`); then
   `presentation.json` and `presentation.txt` list, per challenge, the repository, the pull request,
   the base, the approved head, the manifest and its digest, the operation id, kind, target and
   expiry, the nonce and its expiry, the protection check's answer at prepare, the effects the merge
   will have, the expected outcome and the recorder's own summary, and name the stale-head control
   (pull request B: refused, nothing merged, main unmoved; A is the one to authorize), with the
   precondition's results, the bot controls' statuses and the auditor's control ("nonexistent pull
   request #n, refused by scope"). Nothing is merged.
2. **The Owner, between the phases.** The Overseer presents the presentation. Only if the Owner then
   authorizes in his own words, naming the operation id(s), does the Overseer write that reply
   verbatim into the statement file (`{"text", "attributedTo": "owner", "channel": "main-session",
   "reference"}`) and run phase record.
3. **record**: the statement is read exactly as written and checked by the recorder's own statement
   checks; a missing, empty or non-JSON file, a model-authored or non-Owner statement, or one naming
   none of the challenged operations is refused before Gitea or the credential provider is touched.
   `record` runs for each challenge the statement names, with the command line's protection check (the
   stale-head control first: its head is moved after the recorder's checks and before its merge call;
   the property checked is that nothing merges and `main` does not move, and the refusal Gitea gives is
   recorded as observed, not assumed: 409 `HEAD_STALE` with the receipt failed is expected, a 405
   `MERGE_REFUSED` or a 500 `OUTCOME_UNKNOWN` is possible while Gitea re-checks the pull request after
   the push, finding F14; B merging is a SECURITY FAILURE); then the read-backs, zero tokens on
   `aieh-owner`, closing every pull request left open, and the custody inspection. **A challenge whose
   protection check does not answer `verified` immediately before its merge (the auditor not
   provisioned, or the fixture not as declared) is expected to refuse `PROTECTION_UNVERIFIED` or
   `PROTECTION_DRIFT` with nothing sent**; the presentation says which, from the answer at prepare.
4. **rechallenge** (only when the presented challenges expired unused, and only on the Owner's
   authorization of fresh challenges; it authorizes no merge): fresh one-time challenges for the
   operations already presented, on their existing pull requests, approved heads and manifests. It
   sends no write to Gitea. Before generating anything it refuses (each with its code) unless every
   presented challenge has expired and no other challenge for these operations in the run's recorder
   state is still usable (a regeneration never leaves two live challenges for one operation); the
   protection check answers `verified` with the baseline; every role's identity and scopes are as
   declared; main is at the presented head; each pull request is open, not merged, into main, at the
   presented head on the presented branch, with the presented manifest digest; and the recorder would
   not refuse the operation (`OPERATION_NOT_NEW`, `MANIFEST_EXPIRED`). The recorder's real `prepare` then
   issues each challenge, whose subject must equal the presented one exactly (`SUBJECT_DIFFERS`). The
   previous presentation moves to `presentation-<k>.json` and `.txt` (nothing is overwritten); the new one
   has the same format and keys (phase record reads it unchanged), marks the original prepare's
   precondition and controls as not re-run, and adds `regeneration`. Then the custody inspection.
`statement.json` is `{"text": ..., "attributedTo": "owner", "channel": ..., "reference": ...}`.

## Not yet verified

- Any real acceptance: the recorder has run on throwaway fixture repositories only, with synthetic
  statements. No Owner acceptance has been recorded with it.
- The statement's attribution against its source: the Owner conversation store (U-02.x) does not
  exist, so whether the referenced message is the Owner's is declared, not checked.
- Under `core.autocrlf=true` the files are written as their blob bytes (LF), where git's checkout
  would write CRLF; git's and the module's `status` report them clean (tested on a fixture).
  Filter drivers and `working-tree-encoding` on these paths: not tested.
- Task itself (the targets' commands were run directly), Linux and macOS.
- The authorization recorder against a real Gitea: its live exercise (`test_live_authorization.py`)
  ran once on the S-01.2.2 fixture on 2026-11-12, on the Owner's own authorization (OA-14;
  [record](../../evidence/P-04.2-authorization-recorder.md), section 17). Observed on Gitea 28.3.0:
  one merge by basic authentication as `aieh-owner`, with the six trailers kept as written, the
  approved head as the second parent and the read-back confirmed, and `aieh-owner` holding no token
  after it; and the 409 to a stale `head_commit_id` (the stale-head control: `HEAD_STALE`, receipt
  failed, nothing merged). The other refusals (an altered digest, a replayed or expired decision, a
  missing or non-Owner statement, a missing challenge, a token on `aieh-owner`) have run against the
  fake Gitea of `tests/fake_gitea.py` only; the Gitea reads they compare against ran live. Not
  observed: the audit log's events for the merge.
- The Owner credential's absence from job environments: the exercise's custody inspection found
  `aieh-owner`'s password in no file of the managed root, the checkout or the run directory and not in
  the main session's process environment, but no job environment existed to inspect; carried to S-03.3
  (agent attempts) and Q-02.2.2 (CI jobs). The custody of the Owner's own credentials (the push
  credential and the provider login, `fd-owner-credential-custody`) is not inspected: P-04.2 is blocked on
  it.
- The statement's attribution against its source (as above), for the recorded Owner authorization of
  OA-14 too.
- The protection rule itself: `aieh-owner` cannot read it in Gitea 28.3.0, so the allowlists of other
  accounts and the override flags are not compared by its own checks (`Policy.unobservable`). The
  recorder fails closed on them through the protection check of OA-16, whose auditor was provisioned
  and whose live negative tests and qualification ran on 2026-11-12 (OA-16 Acts C and D); it answered
  `verified` before and after the live exercise's merge.
