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
  as `aieh-owner` (below);
- the authorization recorder's **dispatch-input commands** (plan leaf P-04.3,
  [`input_recorder.py`](input_recorder.py)): they record design acceptances and manifest promotions,
  decided by the Owner or delegated by
  [decision 0018](../../decisions/0018-planning-and-execution-roles-delegated-decisions-and-standing-authorizations.md)
  point 3.2 or 3.3, and are the only writer of the live approved-input manifest (below), with the
  **delegated decision record** (`delegated-decision/v1`, [`delegated_decision.py`](delegated_decision.py))
  and the series readers and verifier ([`input_decisions.py`](input_decisions.py)).

Standard library only, plus the shared repository-access module (Dulwich, from the Python tools set;
[decision 0014](../../decisions/0014-dulwich-adoption-scope-and-repository-access-contracts.md)) and
the lineage objective resolver. The acceptance recorder launches no process, uses no network, reads
no credential and does not touch the managed data root. The authorization recorder launches no
process either; it talks to the managed Gitea on host loopback, reads the two credentials it is
custodian of (`aieh-owner`'s password, and its protection check's read-only token), and keeps its state
and receipts under the managed data root (below). The dispatch-input commands launch no process, use no
network, read no credential and import no Gitea or credential module; they keep their state and receipts
under the managed data root and write the live manifest there.

## Files

| Path | What |
|---|---|
| `owner_decision.py` | The shared record: its fields, the kinds, the `accept-objective`, `authorize-operation`, `accept-design` and `promote-manifest` subjects (`subject_problems`), `statement_verdict` and `check_record` |
| `delegated_decision.py` | The delegated decision record (`delegated-decision/v1`): its fields, the delegation table (`DELEGATIONS`) and the basis types (`BASIS_TYPES`), the act's checks (`check_delegation`, and `read_authority`, which reads the delegating record and the log at the harness repository's `HEAD`), the generic `decide` and `check_record` |
| `input_decisions.py` | The dispatch-input series (their store keys, positions and heads), the design binding of a manifest entry, and the verifier (`verify_manifest`, `verifier`) with its refusal codes; importable without the write side |
| `envelope_decisions.py` | The provider-envelope authorizations' read side (plan leaf S-03.5, slice 1): the authorization recorder's receipts of operation kind `provider-envelope`, the governing one (the last confirmed), and the verifier the inference broker's `serve` asks (`verify_envelope`, `verifier`) with its refusal codes; importable without the recorder (no Gitea, credential or store module) |
| `selection_recorder.py` | The model-selection recorder (plan leaf S-03.5, slice 2): `delegate` (the engineering manager's `select-models` decision under decision 0018 point 3, resting on the governing provider-envelope receipt) and `status`; the codes and remedies, the context and the command line. It imports no Gitea or credential module |
| `input_recorder.py` | The dispatch-input commands: `design prepare`, `record` and `delegate`; `manifest prepare`, `record`, `delegate` and `resolve`; `status`; the codes and remedies, the context and the command line |
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
| `tests/input_fixture.py` | The dispatch-input commands' fixtures: a throwaway project repository (an OpenSpec change at two commits), fixture harness repositories (a decision 0018 `Accepted (Owner)`, the same `Proposed`, and one whose log quotes are only in the work tree), a per-test context over a throwaway store and state root, synthetic statements, bases and candidate manifests |
| `tests/test_input_decisions.py` | The two new kinds and the unchanged shape of `owner-decision/v1`; `delegated-decision/v1`, its table (the engineering manager never decides either kind) and a later kind added as a row; the status parser; the codes, the admitted channels and the repeated grammars against their sources (unit) |
| `tests/test_input_recorder.py` | Both authorities end to end with the verifier's answer; every code of the recorder table with what it leaves (a refusal reserves nothing and leaves the live manifest as it was; `PROMOTION_FAILED` and `OUTCOME_UNKNOWN` leave a receipt `manifest resolve` settles); each delegated refusal on the fixture harness repositories; the real decision 0018 at `HEAD`; the verifier's refusals; a fixture context never reaching the managed root; importing the commands loads no Gitea or credential module; the command line (integration) |
| `tests/test_live_phases.py` | The live exercise's phase plumbing against the fake Gitea: phase rechallenge (fresh challenges for the same operations with reads only, the record phase on them, every refusal leaving the run directory unchanged); prepare's precondition (the baseline variable, the protection check's digest, every role's identity and scopes, open pull requests and existing branches, each refused with zero writes), the auditor's control on a nonexistent pull request, the stopping rule after every control attempt, the presentation, the statement-file refusals, the expected outcome without a verifier and with one that does not verify, the stale-head control and each refusal it can observe (finding F14), the SECURITY FAILURE stops, the protection check end to end (unit) |
| `tests/test_selection_recorder.py` | The model-selection act (S-03.5 slice 2) on the fixture harness repositories, over provider-envelope receipts the real recorder writes against the fake Gitea: a selection and the one that supersedes it, each refusal leaving nothing reserved (the product manager, a basis of another shape, an unknown, unconfirmed, other-kind, superseded, expired or forged receipt, an unsettled later envelope, decision 0018 `Proposed`, no store, a malformed selection), a position taken meanwhile, a failed write, the real decision 0018 at `HEAD`, the command line, the managed context, and the act loading no Gitea or credential module (integration) |
| `tests/test_envelope_decisions.py` | The provider-envelope read side (S-03.5) over receipts the real recorder writes against the fake Gitea: the governing authorization and its view, the expiry at its second, supersession and replay, a non-canonical manifest, other kinds ignored, a failed, unknown or reserved receipt alone or after the confirmed one, every hand-written receipt it refuses, its constants equal to the recorder's and its imports (unit) |

## The Owner decision record (`owner-decision/v1`)

One JSON object per decision, with exactly these fields in this order:

| Field | Value |
|---|---|
| `format` | `owner-decision/v1` |
| `decisionId` | a random UUID, version 4, canonical lower-case text |
| `kind` | `accept-objective` (P-04.1), `authorize-operation` (P-04.2), or `accept-design` or `promote-manifest` (P-04.3; their subjects are under "The dispatch-input commands" below) |
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

### Provider-envelope authorizations (plan leaf S-03.5, slice 1)

The Owner authorizes the inference broker's provider envelope through this recorder as any operation: the
manifest `operations/<id>.json` that `inference_broker.py envelope --operation <id>` prints, of kind
`provider-envelope`, whose target is the envelope's canonical digest
([`integrations/inference/README.md`](../inference/README.md), "The provider envelope"). The recorder does not
change and learns nothing of the kind. Its read side is `envelope_decisions.py`, which the broker's `serve` is
handed: it lists the recorder's receipts (they are keyed by a random nonce, so there is no direct lookup), keeps
those of kind `provider-envelope` reserved by `authorization-recorder/1` with a well-formed `owner-decision/v1`
that binds the receipt's key, operation and manifest digest, orders them by reservation, and lets the **last
confirmed** one govern. Its answers, in order: `ENVELOPE_RECORD_INVALID` (a receipt under the prefix whose kind
cannot be read, or a provider-envelope receipt that is not the recorder's: another actor or receipt format, a
decision that fails `check_record`, a repeated `decisionId`), `ENVELOPE_NOT_AUTHORIZED` (none confirmed and none
unsettled), `ENVELOPE_AUTHORIZATION_UNRESOLVED` (a later one `reserved`, `dispatched` or `unknown`: run
`resolve`), `ENVELOPE_REPLAYED` (the live digest is a superseded authorization's), `ENVELOPE_MISMATCH` (another
digest, or the merged manifest is not the canonical manifest of the live envelope), `ENVELOPE_EXPIRED` (the
governing `expiresAt` reached); otherwise the governing receipt's view (`receipt`, `operation`, `decisionId`,
`target`, `digest`, `expiresAt`). It reads the integration store only. A later provider-envelope authorization
ends an earlier one at the broker's next start; no revocation record exists.

### Model selections (plan leaf S-03.5, slice 2)

Decision 0018 point 3 delegates technical model selection inside an authorized model-access envelope to the
engineering manager. The delegation table has a third row: kind `select-models`, `decision:0018` point `3`,
decider `agent:engineering-manager` only (the product manager is refused `DECIDER_NOT_DELEGATED`), basis type
`envelope-receipt`. Its subject: `leaf`, `models` (`{<family>: [{id, use, cost}]}`: exact identifiers in the
broker's grammar, no wildcard, no duplicate, no family empty), `verified` (`{source, at}`) and `supersedes`
(set by the recorder). The basis is `{"type": "envelope-receipt", "receipt": "owner-authorization/v1/<nonce>"}`;
it is an authority when the integration store holds that receipt, reserved by the authorization recorder, of
operation kind `provider-envelope`, confirmed. This basis type needs the store: `read_authority` takes it as a
keyword and, without one, refuses `AUTHORITY_UNAVAILABLE`; the record's fields and the two P-04.3 rows are
unchanged.

`selection_recorder.py delegate --selection FILE --decided-by agent:engineering-manager --basis FILE` also
requires the basis receipt to be the governing, unexpired provider-envelope authorization
(`DELEGATION_BASIS_NOT_AUTHORITY` for a superseded or expired one, or while a later one is unsettled), then
writes a write-ahead receipt at the next position of the one series `model-selection/v1/<sequence>`
(`aieh-model-selection/1`, actor `selection-recorder/1`) and a copy under
`<state>/delegated-decisions/model-selections/`. Its own codes: `SELECTION_INVALID`, `SELECTION_POSITION_TAKEN`
(nothing written), `SELECTION_WRITE_FAILED` (the receipt failed, its position spent; exit 1). `status` reads the
series' head. **Checked at the act:** the row, the decider, the basis's shape, decision 0018 at `HEAD`, the basis
receipt and that it governs, the subject's shape. **Not checked:** who ran the command; that the identifiers
were verified against current provider information; that the costs are right; that the record was presented to
the Owner before the first paid operation (S-03.3). The broker's start reads the series through
`envelope_decisions.verify_selection` (the decision source's `selection(receipt)`): the last confirmed position
governs; `MODEL_SELECTION_MISSING`, `MODEL_SELECTION_NOT_AUTHORIZED` (not the selection recorder's, or not a
well-formed `select-models` record binding its position and basis) or `MODEL_SELECTION_RECEIPT_MISMATCH`
(another envelope receipt); otherwise the identifiers per family, never the record's revision.

## The dispatch-input commands (plan leaf P-04.3)

Two decisions approve dispatch inputs:

- a **design acceptance** (`accept-design`): the design of one OpenSpec change of one manifest
  repository at an exact revision (decision 0008 point 5);
- a **manifest promotion** (`promote-manifest`): one approved-input manifest
  (`ai-engineering-harness/dispatch/approved-inputs/v1`, unchanged; integrations/dispatch).

Each is decided by one of two authorities, recorded in one of two formats:

- **the Owner**: an `owner-decision/v1` record, through a challenge, as the other recorders take one:
  `prepare` writes the challenge (the subject, the summary to show the Owner, a nonce and an expiry, 30
  minutes by default, at most a day) to the recorder's own state, and `record` takes the Owner's
  statement, refusing it unless it is the Owner's, came through an admitted channel (`main-session`), and
  names the change (a design) or the token `approved-inputs-v<version>` (a manifest). Run only in the
  main session, on the Owner's decision, with the statement transcribed verbatim (decision 0012 point 9);
- **a delegation**: a `delegated-decision/v1` record, in one step (`delegate`): there is no challenge,
  because there is no Owner to show it to. Decision 0018 point 3.2 delegates a design acceptance inside a
  recorded commitment's scope, and point 3.3 a manifest promotion inside an envelope the Owner granted, to
  the **product manager** (`agent:product-manager`) only; the engineering manager never decides either
  (`DECIDER_NOT_DELEGATED`). A delegated decision is never an `owner-decision/v1` record, is never kept
  among the Owner's records, and is never shown as the Owner's.

### The subjects

`accept-design`: `repository` (the manifest's repository id: a label, which nothing ties to a project
repository; `commit` and `content` bind what was accepted), `change` (the OpenSpec change id),
`commit` (the exact revision, 40 or 64 hex digits), `content` (`sha256:` over the change's folder at that
commit: for each blob under `openspec/changes/<change>/`, in ascending path order, the line
`<sha256 of the blob>  <path relative to the folder>\n`; the digest of those lines) and `supersedes` (the
`decisionId` of the acceptance of that change it replaces, or `null` for the first).

`promote-manifest`: `schema` (`ai-engineering-harness/dispatch/approved-inputs/v1`), `version` (the
manifest's `version`: its position in the promotion series), `digest` (`sha256:` of the manifest file's
bytes), `previous` (`{version, digest}` of the promotion it replaces, or `null`) and `designs` (for each
`designs` entry, in manifest order, `{repository, change, commit, acceptance, sequence}`: the decision id
of its design acceptance and its position in that series).

### The delegated decision record (`delegated-decision/v1`)

Fields, in this order: `format`, `decisionId`, `kind`, `subject` (the subject of the same kind above,
validated by the same function), `delegation` (`record`: `decision:0018`; `point`: `3.2` or `3.3`;
`revision`: the full commit of the harness repository at which the record and the basis were read;
`digest`: `sha256:` of the record file's blob there; `basis`), `decidedBy` (the role the delegation names),
`recordedBy` (equal to `decidedBy`: a delegated decision is recorded by the lead that made it; none is
relayed) and `recordedAt`. The basis is `{type, link, quote}`, the shape of the network matrix's
`owner_approval`, anchored: `type` `commitment` (point 3.2) or `envelope` (point 3.3), `link`
`evidence/bootstrap-log.md#<anchor>` (the anchor of the log's Decisions entry it rests on), and the quote,
verbatim, at least 12 characters (a commitment's contains `Commitment: `).

**How a basis is an authority** (fail closed). The anchor must open a Decisions entry of the log at the
harness repository's `HEAD` (`- <a id="<anchor>"></a>**<date>: <title>** ...`; the entry runs to the next
top-level list item or heading). A `commitment`'s entry is titled `<date>: Commitment: ...` and contains the
quote. An `envelope`'s entry is titled `<date>: Owner standing authorization: ...`, and the quote lies inside
its verbatim block (its `>` lines, the prefixes stripped, compared with runs of whitespace collapsed on both
sides). Each title begins, after its `<date>: `, with its kind's words: a title that merely contains
`Commitment:` is no commitment, and an undated title is no authority of either type. An entry with another
title (`Owner direction:`, `Owner authorization:`, ...), a quote outside the entry or its block, or a row of
the Owner-actions queue prepared and not granted is `DELEGATION_BASIS_NOT_AUTHORITY`; an absent anchor or quote is `DELEGATION_BASIS_NOT_RECORDED`.

**The convention this needs** (decision 0018 points 5 and 7): the session in which the Owner grants a
standing authorization records it in the log's Decisions as an entry titled `<date>: Owner standing
authorization: <what it covers>`, with an anchor, and the Owner's words verbatim as a `>` block. No agent
writes, paraphrases or relays one. The recorder checks the entry's presence and shape, never its
authorship. Until such an entry exists (none does at the time of writing), every delegated promotion is
refused and a promotion is the Owner's.

**The delegation table** (`delegated_decision.DELEGATIONS`) is data: one row per kind, naming the
delegating record and its point, the decider and the basis type. A kind without a row is never delegated
(`DELEGATION_KIND_UNKNOWN`). A later leaf (S-03.5's model selection) adds its kind as a row, with its subject
check and, where it needs one, a basis type of its own (`BASIS_TYPES`), and records through the same
`read_authority` and `decide`; the record's fields do not change.

**What `delegate` checks**: the row, the decider and the basis's shape; the delegating record
(`decisions/0018-*.md`), read from the harness repository's `HEAD` commit through the repository-access
module (the committed blob, never the work tree), has its first `Status:` line beginning exactly `Status:
Accepted (Owner) -` (a qualified variant such as `Accepted (Owner), superseded ...` is not accepted); the
basis is an authority of its type at that commit (above); then everything the Owner path checks about the
subject; and a delegated acceptance never supersedes an Owner acceptance of the same change
(`OWNER_ACCEPTANCE_HEAD`: weakening an Owner-accepted decision is reserved, decision 0018 point 4.8; the
next acceptance of that change is the Owner's). Promotions are not gated so: a new manifest version does
not weaken an earlier one. **Not checked, disclosed** (decision 0018 point 7; decision 0010 point 1): who
actually ran the command (any process of the account can declare the product manager); that the change
lies inside the commitment's scope, that the Owner gave its intent and that it is not a change to the
harness's own governance; that every entry lies inside the envelope and that the envelope has not expired
or stopped; and who wrote a log quote ("a log quote is checked for presence, not authorship").

### The series, the receipts and the live manifest

Every decision is a write-ahead receipt in the integration store (intent format
`aieh-dispatch-input-decision/1`, actor `dispatch-input-recorder/1`) at its position of its series:

| Series | Store key | The receipt holds |
|---|---|---|
| promotions | `dispatch-inputs/v1/promotion/<version>` | the decision record, the manifest's schema, version, digest, `previous` and its exact text |
| acceptances of one change | `dispatch-inputs/v1/design/<repository>/<change>/<sequence>` | the decision record, the repository, the change and the sequence |

Positions start at 1 and are contiguous. A decision's link (`supersedes`, `previous`) names the last
**confirmed** decision of its series, and it takes the next free position: a failed or unconfirmed
position is spent and never reused. The store's unique key makes a position single-use: a second `record`
on a consumed challenge is `CHALLENGE_CONSUMED`; a challenge whose position another decision took is
`CHALLENGE_STALE`. A candidate naming a design revision whose acceptance a later acceptance of that change
superseded is `DECISION_REPLAYED`. A design acceptance writes no manifest; its receipt is confirmed when it
is recorded. An act that stops after its reservation (a decision copy that cannot be written) marks its
receipt failed when the store lets it (`IO_FAILED` for a design, `PROMOTION_FAILED` for a promotion; exit
1): the position is spent and the challenge used (`CHALLENGE_CONSUMED`, whose detail gives the receipt's
state). `status` shows, for each series, its head, its next position, its failed positions and its
unsettled ones.

The Owner's challenges and decision copies are kept in the recorder's own state,
`<state>/owner-authorization/dispatch-inputs/{challenges,decisions}/`; delegated decision copies in
`<state>/delegated-decisions/dispatch-inputs/`, never under `owner-authorization/`. The copies are for
people and backups: nothing reads them to decide. No receipt holds a filesystem path.

**The live manifest** (`<state>/dispatch/approved-inputs.json`, decision 0009) has one writer: `manifest
record` and `manifest delegate` reserve the receipt, mark it dispatched, write the candidate's exact bytes
to a temporary file in the live file's own directory, replace the live file with it atomically, read its
digest back and confirm. A write that did not land leaves the receipt failed and the live file as it was
(`PROMOTION_FAILED`); an outcome that does not read back as decided leaves it unknown (`OUTCOME_UNKNOWN`).
`manifest resolve --version N` settles a receipt **by reading** the live file, never by writing it:
confirmed when its digest is the decided one, failed otherwise (a receipt left reserved, nothing written,
becomes failed). No promotion is prepared, recorded or delegated while an earlier promotion receipt is
reserved, dispatched or unknown (`PROMOTION_UNRESOLVED`): once a later promotion replaced the live file,
resolving the earlier one by reading would record a decision that landed as failed. A design acceptance
writes no file, so an unsettled design receipt has no such hazard; it is a spent position the verifier
ignores, and blocks nothing.

**The verifier** (`input_decisions.verify_manifest`, or `verifier(store)` as the callable
`load_manifest(path, decisions=...)` takes; integrations/dispatch) reads the store's receipts only, by direct
lookups: the promotion at the manifest's version must exist (`MANIFEST_NOT_PROMOTED`), be a well-formed
record of its format binding the receipt's version and digest (`DECISION_RECORD_INVALID`), be confirmed
(`MANIFEST_PROMOTION_UNCONFIRMED`), have the file's digest (`MANIFEST_DIGEST_MISMATCH`), be the last confirmed
promotion (`DECISION_REPLAYED`), and each design entry must have the confirmed acceptance the promotion
bound for it, reserved by the recorder (`DESIGN_ACCEPTANCE_MISSING`, `DECISION_RECORD_INVALID`). It also
walks the promotion series from position 1 to the manifest's version by direct lookups
(`DECISION_RECORD_INVALID`, the detail naming the position): every position present, each reserved by the
recorder's actor (`dispatch-input-recorder/1`), no `decisionId` or Owner challenge repeated, and each
confirmed promotion's `previous` the confirmed promotion before it. A gap **above** the manifest's version
cannot be seen without listing the store, which the verifier does not do. Otherwise it answers the approval view
(`ai-engineering-harness/dispatch/manifest-approval/v1`): the promotion decision and each design entry's
acceptance decision, each with its receipt and its authority (the Owner, or the delegating record, its
point, the revision, the decider and the basis). Design acceptances are not re-checked for currency at
load: a later acceptance takes effect when it is promoted.

**What stops a same-account process writing a "decision" beside the manifest?** Nothing at the operating
system's level (decision 0010 point 1; `fd-bootstrap-shared-identity`): a file beside the manifest has no
effect, because no decision file is read; a manifest is approved only by a confirmed receipt of this store
at its version with its digest, and producing one means running the recorder, which leaves an
append-only receipt naming the authority it claimed. Unapproved content is detected and refused at load
(`load_manifest`), not prevented from being written, unless the store itself is also written by hand: a
same-account write of the store that imitates the recorder (its actor, fresh ids, the right `previous`) is
outside the threat model (decision 0010 point 1), and the series checks above catch only a careless one.

### Refusals

`input-recorder: CODE: detail. Remedy: ...`; exit 2 when nothing was recorded or written, 1 for a failed or
unknown promotion (its receipt says which).

| Code | Refused when |
|---|---|
| `CHALLENGE_MISSING`, `CHALLENGE_INVALID`, `CHALLENGE_UNKNOWN` | no challenge; not a nonce, a malformed state file, or a challenge of the other kind; a nonce this recorder did not issue |
| `CHALLENGE_EXPIRED`, `CHALLENGE_CONSUMED`, `CHALLENGE_STALE` | the challenge's expiry has passed; this challenge was already used (its position holds its receipt, confirmed or not: the detail says which); another decision holds its position, or the series or a design acceptance changed after the summary was shown |
| `STATEMENT_MISSING`, `STATEMENT_MODEL_AUTHORED`, `STATEMENT_NOT_OWNER`, `STATEMENT_INVALID` | the statement verdicts of the shared record (or a statement file that is not JSON) |
| `STATEMENT_SUBJECT_MISSING`, `CHANNEL_NOT_ADMITTED`, `RECORDED_BY_INVALID` | the statement does not name the change or `approved-inputs-v<version>`; its channel is not admitted; `--recorded-by` is not an attribution |
| `PROJECT_UNAVAILABLE`, `GIT_FAILED` | `--project` is not a work tree root (or Dulwich is missing); the repository could not be read |
| `CHANGE_MISSING`, `REVISION_INVALID` | no file under `openspec/changes/<change>/` at the commit, or not a change id; not a full commit id of the repository |
| `CANDIDATE_UNREADABLE`, `CANDIDATE_INVALID`, `CANDIDATE_INSIDE_CHECKOUT` | the candidate cannot be read (or is above 1 MiB); it is not UTF-8 strict JSON of the v1 schema; it lies inside or around the checkout |
| `MANIFEST_LOCATION_INVALID` | the live manifest's path is refused by `load_manifest`'s own path rules |
| `VERSION_NOT_NEXT` | the candidate's version is not the next position of the promotion series (or, for a delegated decision, another decision took the position meanwhile) |
| `DESIGN_ACCEPTANCE_MISSING`, `DECISION_REPLAYED` | a design entry has no confirmed acceptance at its commit; it names a revision whose acceptance a later one superseded |
| `PROMOTION_FAILED`, `OUTCOME_UNKNOWN` | the write did not land (receipt failed, the live file as it was); it did not read back as decided (receipt unknown: run `manifest resolve`) |
| `PROMOTION_UNRESOLVED` | an earlier promotion receipt is reserved, dispatched or unknown: run `manifest resolve --version N` first |
| `RECEIPT_MISSING` | `manifest resolve` for a version without a receipt |
| `DELEGATION_KIND_UNKNOWN`, `DECIDER_NOT_DELEGATED` | no row of the delegation table for the kind; the decider is not the row's |
| `DELEGATION_BASIS_INVALID`, `DELEGATION_BASIS_NOT_RECORDED` | the basis is not `{type, link, quote}` of the row's type with an anchored link (or its file is not JSON); the quote or the anchored entry is not in the log at the harness repository's `HEAD` |
| `DELEGATION_BASIS_NOT_AUTHORITY` | the anchored entry is not an authority of the basis type, or the quote lies outside it (a commitment) or its verbatim block (a standing authorization) |
| `DELEGATION_NOT_ACCEPTED`, `AUTHORITY_UNAVAILABLE` | the delegating record's status is not `Accepted (Owner) -` at `HEAD` (or it is not there once); the harness repository cannot be read |
| `OWNER_ACCEPTANCE_HEAD` | a delegated acceptance of a change whose current acceptance is the Owner's |
| `IO_FAILED` | a file could not be written or read: a challenge (nothing recorded, exit 2), or a decision copy after the reservation (the receipt failed, exit 1); on the command line also any other file error, as a code, never a traceback |

A repository id outside the manifest's grammar, or an expiry outside 1 to 1440 minutes, is a usage error
(exit 2, no code).

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

The dispatch-input commands (`record` only in the main session on an Owner decision; `delegate` only by the
role the delegation names, in its own session):

```
<tools python> -I -B integrations/owner/input_recorder.py design prepare --project DIR --repository ID --change NAME \
    --commit FULL [--expires-in-minutes N]
<tools python> -I -B integrations/owner/input_recorder.py design record --challenge NONCE --statement statement.json \
    --recorded-by agent:<id>
<tools python> -I -B integrations/owner/input_recorder.py design delegate --project DIR --repository ID --change NAME \
    --commit FULL --decided-by agent:product-manager --basis basis.json
<tools python> -I -B integrations/owner/input_recorder.py manifest prepare --candidate FILE [--expires-in-minutes N]
<tools python> -I -B integrations/owner/input_recorder.py manifest record --challenge NONCE --statement statement.json \
    --recorded-by agent:<id>
<tools python> -I -B integrations/owner/input_recorder.py manifest delegate --candidate FILE \
    --decided-by agent:product-manager --basis basis.json
<tools python> -I -B integrations/owner/input_recorder.py manifest resolve --version N
<tools python> -I -B integrations/owner/input_recorder.py status
```

`task owner:design -- prepare ...` (and `record`, `delegate`) and `task owner:promote -- prepare ...` (and
`record`, `delegate`, `resolve`) run the first seven. `basis.json` is `{"type": "commitment" or "envelope",
"link": "evidence/bootstrap-log.md#<anchor>", "quote": ...}`.

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
- The dispatch-input commands against the managed data root, its integration store or a real Owner
  decision: they have run on throwaway repositories, a throwaway store and state root, and synthetic
  statements and bases only. `load_manifest`'s enforcement has likewise run only over a throwaway store
  (integrations/dispatch, `tests/test_manifest_promotion.py`); no live driver calls it yet (E-01.3.2).
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
  credential and the provider login, `fd-owner-credential-custody`) is not inspected. On 2026-11-12 the
  finding was re-homed from P-04.2, whose artifact does not hold them (S-03.3 for agent attempts, a plan
  deferral for CI jobs, Owner action OA-21 for their stores), and P-04.2 passed.
- The statement's attribution against its source (as above), for the recorded Owner authorization of
  OA-14 too.
- The protection rule itself: `aieh-owner` cannot read it in Gitea 28.3.0, so the allowlists of other
  accounts and the override flags are not compared by its own checks (`Policy.unobservable`). The
  recorder fails closed on them through the protection check of OA-16, whose auditor was provisioned
  and whose live negative tests and qualification ran on 2026-11-12 (OA-16 Acts C and D); it answered
  `verified` before and after the live exercise's merge.
