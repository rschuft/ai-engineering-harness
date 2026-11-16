# 0024 - The D1 attempt run and result path: two vantages, the conversation proxy's two tails, the result's custody chain, the journals and stops, and the draft pull request

Status: Proposed - 2026-11-16, drafted after D1's live run under the engineering manager's ruling R8 ("a decision record at E-05.5's completion"), for acceptance by the engineering manager under decision 0018 points 1 and 3.1: it is an architectural decision inside committed scope, and it changes no acceptance criterion, no other leaf's contract and no Owner-approved policy. The acceptance is a later commit. It authorizes no reserved act.

**Authority:** plan leaves E-01.3.2, E-05.4 and E-05.5 (their actions, artifacts and proofs unchanged); the
[D1 commitment](../evidence/bootstrap-log.md#commitment-d1-2026-11-15); decision 0018 points 1, 3.1, 3.3 and 4.8;
within decisions 0013 (point 7: candidate revisions leave as bundles), 0014 (section 7, row R6: the retained bundle
verifier, git the first parser), 0020 (point 6: the manifest loaded per dispatch with the decision verifier) and 0023
(the native profile, its token's custody and the outbound search, section 5); OA-22 (d), (f) and (j); OA-31 (b) and (f)
for D1 attempts.

**Gate:** architecture consultation at gates C (durable decisions no record settled: how the task is sent, how content
enters and the result leaves, who commits, what closes an attempt) and G (custody: what the trusted side accepts from
an attempt, and a credential in the attempt). The architect's work design (2026-11-15) was accepted by the engineering
manager with rulings R1 to R8 (listed in the [handoff](../evidence/bootstrap-log.md#handoff-d1-promotion-v2-2026-11-16)).
Then came slices A1 and A2, their independent review and the A3 fix round, A4 and its delta check, slices B and C,
their independent review and the C2 fix round, and a second delta check. This record states the design **as built**
at `6ddffef` and as run once, live, on 2026-11-16 ([evidence](../evidence/D1-run-2026-11-16.md)).

**Supersedes:** none. It applies decisions 0013, 0014, 0020 and 0023 and changes no accepted record's text. It adds
three end-record kinds to E-05.8's vocabulary (`model-stop`, `provider-stop`, `run-not-started`; point 7). It adds one
refusal to E-05.8's mechanism (`ATTEMPT_RESULT_HANDED_ON`) and one to its admission (`PRIOR_ATTEMPT_STOP_UNRESOLVED`).
Neither changes E-05.8's criteria.

## Context

- Before D1 the dispatcher could create a native conversation (E-01.3.1, E-05.2), and E-05.11 had qualified the
  native profile from `tools/guest.py`'s probe channel. Nothing in the dispatch module could send the task, seed the
  workspace, collect a result or take it to Gitea. E-05.4 ("from a reserved attempt's result in the exchange") and
  E-05.5 (one attempt end to end, a draft pull request and an Owner report) needed all four.
- The dispatcher's checked client admitted the conversation proxy `POST /api/conversations/{conversation_id}/{tail}`
  only as `validation`, the admission probe. The proxy reaches every POST of a conversation's inner server.
- The guest exchange is a bundles-only edge (`nm-dispatcher-exchange`); a workspace's bind source is unreadable to
  the `agent` login. The only path between the dispatcher and a conversation's files is the Agent Server API.
- `GuestTransport` sealed only a body with `secrets`; any other request rode the ssh command line, which Windows caps
  near 32767 characters. It recorded the sha256 of every body, the create's (with the token) included; E-05.11's
  review had ruled that digest out in its driver only.
- D1 has one attempt. E-05.8's admission refuses a new attempt after an earlier confirmed one that has no end record.
  A failure after a successful turn therefore has no retry.
- Observed on step 0's fixture conversation (2026-11-16) before the run, and recorded in `D1_STEP0_OBSERVED`:
  - the pinned image's container has git 2.47.3 and Python 3.13.15;
  - the bash route keeps CRLF and the spelling `tRuE` (no secret registered) and returns 1 MiB whole;
  - one `/bin/sh -c` argument is capped at 131072 bytes (a 139264-byte command: "Argument list too long");
  - the exchange delivery, the pathspec exclusion, the pull, the retained verifier and the commit-id equality all
    worked on a synthetic tree.

## Considered options

The work design's questions G1 to G7, each with what was rejected and why.

1. **Sending the task (G1).** (a) the proxy, narrowed to listed tails pinned in `routes.json`: **chosen**.
   - (b) `initial_message` in the create: rejected. The workspace exists only after the create, so `run: true` at
     create starts the turn before the seed and before the inspection the blueprint requires. It would also change
     the create E-05.11 qualified and E-05.2 bound: three digests, `BODY_FIELDS` and the shared native check.
   - (c) acting outside the checked client: rejected. It contradicts E-01.3.1's proof ("every dispatcher call ... is
     checked against the profile's routes.json") and E-01.3.3's cut-over, so it would weaken an acceptance criterion,
     which is the Owner's (decision 0018 point 4.8).
2. **Content in and the result out (G2).** (a) the tree in the SEED command's text; the result as a git bundle
   delivered into the guest exchange by the API probe and pulled to the unchanged R6 verifier: **chosen**.
   - (b) the host verifies bytes it reads directly: rejected; it departs from the proof text of E-05.4 and E-05.5.
   - (c) a root-side copier in the guest: rejected; a seed change, a new privileged component, an Owner act and a
     re-qualification.
3. **Who commits (G3).** (b) the dispatcher's fixed RESULT command, on a fresh git directory it brings, with
   host-side commit-id equality: **chosen**.
   - (a) the agent commits: rejected; not deterministic, and a missing, amended or multiple commit strands the single
     attempt.
   - (c) the host commits from a returned tree: rejected; it moves a tree through a bundles-only edge, bypasses R6
     and needs a repository-access write that cannot delete (`write_commit`).
4. **The message (G4).** A versioned frame in dispatcher code, its digest bound in a write-ahead turn journal:
   **chosen**. A frame in the agent assignment or the profile: rejected. `ASSIGNMENT_KEYS` is closed and read at the
   pin, so a new key moves the pin; and per-assignment instructions start A-01.2's role-profile materialization.
5. **The test output (G5).** (b) the accepted design's command run by RESULT on an export of the committed tree,
   bound to the commit: **chosen**.
   - (a) the agent's own run: not the report's evidence (blueprint step 04). The run record states whether the
     events show it, as a clause of its own.
   - (c) a fresh `repository-tests` run: rejected; OA-22 (i) authorizes only E-05.1's.
6. **Closing a successful attempt (G6).** Stop the runtime, then the result journal as the close, mutually exclusive
   with the end record: **chosen**. Deleting the conversation is teardown, not the close.
7. **Lineage (G7).** The result receipt in the lineage reader's grammars, mirrored by commit trailers and the pull
   request body: **chosen**. A new lineage kind or resolver edge: rejected; D-01.1 keeps its full proof.

## Decision

### 1. Two vantages, kept apart

1. **Dispatcher acts** decide what the agent receives and what the result is. They go only through
   `AgentServerClient` on the pinned allowlist: the create, the runtime and status reads, SEED, the message, RESULT,
   the runtime stop and the conversation's delete. The order is the dispatch module's (`attempt_run.run_attempt`,
   `result_path.publish_result`). `tools/guest.py` contributes the observer and the exchange pull as injected
   callables; the dispatch module imports nothing of it.
2. **Verifier observations** are E-05.11's steps, run from `tools/guest.py`'s probe channel on the attempt's
   conversation (`native_observer`, extracted unchanged). Their output is evidence and stop conditions only, never
   an input to the result. Routing them through the client would mean allowlisting arbitrary probe scripts.

### 2. The conversation proxy's two tails

1. `routes.json` pins the proxy entry as `dispatcher: allowed` with a closed `tails` list: `events` and
   `bash/execute_bash_command`. A further tail is a profile change and so a promotion (decision 0020).
2. The client admits a `{tail}` route only with a listed tail for which it has a grammar (`TAIL_GRAMMARS`), exactly.
   Any other tail, a case, encoding, slash or traversal variant, and any allowed `{tail}` route without a list, is
   `ROUTE_TAIL_NOT_ALLOWED`, with zero transport calls.
3. The grammars:
   - `events`: exactly `{"role": "user", "content": [{"type": "text", "text": <1 to 32768 characters>}], "run": true}`.
   - `bash/execute_bash_command`: exactly `{"command", "cwd": "/workspace", "timeout"}`. The timeout is 1 to 540
     seconds; the command is at most 4 MiB, with no NUL and no lone surrogate.
   - Anything else is `TAIL_BODY_INVALID`.
4. **Pinned builders.** A command is a `ContainerCommand` made only by a registered builder. `command_builder` admits
   only the names `d1-seed` and `d1-result`, and there is no free-form command function. A raw string, a mapping, a
   forged or altered command is `COMMAND_NOT_BUILT`. Tests register `test-` builders through `allow_test_builders`,
   which no production module calls.
5. What the dispatcher gains: it may send a user message to, and run a fixed command in, its own attempt's
   conversation container. The management key always admitted both, and the probe already did both. The edge
   `nm-dispatcher-agent-server` (OA-22 (d)) is unchanged. The inventory splits `op-as-conversation-message` and
   `op-as-conversation-command` out of `op-as-unenumerated-routes`.
6. The profile's diff is the one routes pin (the profile becomes `b7c5d2fe...d9c7`), promoted as manifest version 2 by the product manager
   ([record](../evidence/bootstrap-log.md#d1-promotion-v2-2026-11-16)).

### 3. Bodies on standard input; no digest of a `secrets` body

1. `GuestTransport` sends every call with a body sealed on ssh's standard input. The seal is the body's one secret
   word when it carries `secrets`, else a fresh nonce. A bodyless call keeps the probe's argument form. A seed or
   result command does not fit a Windows command line.
2. A call record holds method, path, status, seconds and the sha256 of the canonical body. A body that carries
   `secrets` gets no digest (`null`): with the body's known text, the digest would fingerprint the secret (R7; the
   live create's record shows `null`).

### 4. SEED and RESULT

1. **The base** is the approved repository's `refs/heads/main` in its project clone, read through the
   repository-access module. It must contain the accepted design commit (`BASE_LACKS_DESIGN`). Its tree must hold
   regular files only, with no `.claude`, `.mcp.json` or `.git` component (`SEED_TREE_REFUSED`). Names are compared
   per component, NFC-normalized, case-folded and with trailing dots and spaces stripped.
2. **SEED** (`d1-seed`): the base's tree as a hex gzipped tar on the command's text, checked against its sha256 and
   extracted with tarfile's `data` filter into `/workspace/<repository>`. No `.git` and no history enter the
   workspace.
3. **The message** (frame `aieh-d1-message/v2`) points the agent at the task file and the change folder already in
   the seeded tree. It asks the agent to implement the change as designed and run the design's test command offline;
   to change nothing under `backlog/` or `openspec/`; to create no `.claude` or `.mcp.json`; and not to commit or
   push. Every slot comes from the reserved record or the seeded tree.
4. **RESULT** (`d1-result`), one fixed command after a `finished` turn, every value hex-encoded:
   - a fresh git directory outside the workspace, with configuration isolated, built from the base bundle the
     command carries (nothing of a `.git` the agent left is read);
   - `read-tree` of the base, then `add -A` of the workspace, then R3's exclusion rule (below);
   - one commit, parent the base, author and committer `aieh-bot-builder <aieh-bot-builder@localhost.invalid>`
     (R5), at the attempt's `confirmed` time from the store, message `<task id>: <title>` with the trailers `Task:`,
     `Attempt:`, `Outcome:` and `Design:`;
   - a complete bundle of `refs/heads/work/<attempt id>`, read and hashed before any test runs;
   - the accepted design's test command on an export of the committed tree, with a minimal environment.

   It prints the base, tree, commit, the excluded paths, the bundle's digest and size, the tests' status and
   output. The bundle leaves in the exchange delivery's frame.
5. **R3's exclusion rule**, as revised: RESULT takes out of its commit any path with a component that folds to
   `.claude` or `.mcp.json`, and puts any change under `openspec/` or `backlog/` back as the base holds it. Each
   excluded path is reported in the record, the pull request body and the Owner report, never dropped silently.
6. **The argument limit.** Both commands must fit one `/bin/sh -c` argument (131072 bytes). Step (0) checks this for
   the real base before anything is dispatched.

### 5. The result's custody chain

1. **The exchange.** The API probe, as `agent`, finds the one frame of the bundle in RESULT's standard output and
   checks its size and sha256. It writes the bytes into the guest exchange exclusively (`<name>.partial`, then a
   link; an existing name is `EXISTS`). It answers the digest and size only and returns no payload byte. The
   delivery adds no isolation: the mover is the dispatcher's own login. It gives the result one ingestion path whose
   first parser is git.
2. **The pull.** `exchange-pull`, then `verify_pulled_bundle` unchanged (decision 0014 row R6).
3. **The host intake** (`intake_result`):
   - the attempt is confirmed, without an end record, its turn confirmed;
   - the pull is verified at the digest RESULT printed before the tests;
   - the bundle holds exactly `refs/heads/work/<attempt id>`, with no prerequisite;
   - **the commit's raw object is byte for byte `expected_commit(tree, base, message, time)`**, recomputed by the
     host (`RESULT_COMMIT_MISMATCH`). This one equality covers the parent, the identity, the time, the message and
     any extra header. The only untrusted input left is the tree.
4. **Tree policy on the host** (`RESULT_TREE_REFUSED` with reasons): an iterative walk, at most 64 deep and 5000
   entries; regular files only (no link, no gitlink); no component that folds to `.claude`, `.mcp.json` or `.git`
   (defence in depth behind R3); `openspec/` and `backlog/` exactly the base's; at most 64 MiB inflated. Any
   repository error is `RESULT_NOT_VERIFIED`.
5. Agent-controlled text (the test output, the excluded paths) stays in memory until the outbound search has passed
   over it. Records hold its digests and sizes.

### 6. The turn journal and the result journal

1. **The turn journal** `dispatch/attempt/<attempt id>/turn` (`attempt-turn/v1`) is reserved with its intent: the
   base, the seed's digest and count, the frame version and the message's sha256. It is `dispatched` immediately
   before the one POST, then `confirmed` with the status.
   - A 4xx other than 429 is `failed`. A 429 is `failed` (`TURN_RUN_NOT_STARTED`), and the attempt is ended as the
     interruption `run-not-started`.
   - No answer or a 5xx is `unknown`, settled only by reading the conversation's events.
   - A journal past `reserved` makes zero calls (`TURN_ALREADY_SENT`). The message is never sent twice.
2. **The close is the result journal** `dispatch/attempt/<attempt id>/result`, after the runtime is stopped and
   observed `missing` (E-05.8's primitive):
   - `reserved` at the intake, which binds the verified result to the attempt;
   - `dispatched` immediately before the first Gitea write;
   - `confirmed` with the receipt after the read-back;
   - `unknown` on a lost answer, settled only by reading Gitea.

   A different result for the same attempt is `RESULT_JOURNAL_CONFLICT`. A result whose tree equals the base's is
   `failed` with `RESULT_EMPTY_CHANGE`, and nothing is written.
3. **Mutual exclusion with the end record.** The result path refuses an attempt with an end record
   (`ATTEMPT_ENDED`), read at its start and again before the dispatch. `end_interrupted_attempt` refuses once the
   result journal is dispatched, confirmed or unknown (`ATTEMPT_RESULT_HANDED_ON`); a journal that is only reserved
   does not stop a security stop.
4. **Resumes.** The result step resumes from the receipts `.../delivery`, `.../pull` and `.../intake` (digests and
   host paths only). The same inputs make the same commit. A file already in the exchange is pulled and verified,
   never delivered again.

### 7. Stops, and the stop receipts

1. Any of E-05.11's stop conditions observed after the dispatch is recorded durably as it is observed
   (`attempt_end.record_stop`: `dispatch/attempt/<attempt id>/stop/<kind>/<code>`, no text). It then ends the
   attempt through E-05.8's mechanism (trigger `attempt-stopped`, the mapped record) on every path, a dispatcher
   refusal's included, before the result journal is dispatched. Nothing reaches Gitea.
2. The kinds:
   - `credential-stop`: a credential found;
   - `egress-stop`: a connection elsewhere, a direct attempt, a refused guest packet, an off-allowlist tunnel target,
     the tunnel's census after the turn, or a refused ClientHello;
   - `containment-stop`: anything else unnamed;
   - R2 adds `model-stop` (a model outside the attempt's model record) and `provider-stop` (the provider check after
     the turn).
3. A recorded stop refuses every later resume, recorded result and result path (`ATTEMPT_STOP_RECORDED`). While an
   earlier attempt of the work item has a recorded stop and an end that is not a security stop, a new attempt is
   refused (`PRIOR_ATTEMPT_STOP_UNRESOLVED`).
4. The result path's own `OUTBOUND_TOKEN_FOUND` is such a stop (`credential-stop`).
5. A turn that ends `error`, `stuck` or `paused`, and a run that did not start, are ended after the whole-run tunnel
   log and the guard window are read and before the delete: with a stop's record when one was observed, else as
   their interruption. An end that cannot be written deletes nothing.
6. An UNKNOWN inspection sends no message and ends nothing: the attempt is held for the engineering manager.

### 8. The outbound search gate before any write

1. E-05.9's search (`native_token_search`) runs with the dispatcher's held token. Its fingerprint must be the one the
   dispatch recorded (`OUTBOUND_TOKEN_MISMATCH`). It covers:
   - the result bundle: its bytes and every pack object, inflated, deltas applied;
   - every text: the test output, the excluded paths, the commit message, the pull request's title and body, the
     diff, the report's drafts, the journal's intent and the run record's texts.
2. `require_not_found` admits only `not-found` with valid controls whose subject names each digest; it runs before
   the result journal is dispatched.
3. The driver's step (11) searches the run record's draft and every answer of the run, also decoded as the result path
   decodes them.
4. The final report and receipt are searched again before they are written. Records hold the search's summary,
   never a searched byte.
5. The native token is read once per attempt, by the dispatcher, at the create (decision 0023 section 2.2). A
   resumed run reads it again only to search with it, and never sends it into the guest: its calls are sealed with
   nonces.

### 9. The work branch and the WIP draft pull request

1. The bot is the builder's standing token in the attempt context (`attempt_role_token`), through
   `attempt_tokens.ResultSession`. Its closed route list holds two branch reads, the open pull requests, the pull
   request by base and head, one pull request, and `POST /pulls`. Anything else is `BOT_ROUTE_REFUSED` with nothing
   sent: a merge, a review, a contents write and `/token` among them.
2. **Reconciliation before any write.**
   - The attempt's branch at the exact commit, and its pull request, are reused.
   - A branch at another commit is `RESULT_BRANCH_CONFLICT`; another pull request of the branch is
     `RESULT_PR_CONFLICT`.
   - `main` must still be at the base (`RESULT_BASE_MOVED`).
   - No other attempt of the task may have an open pull request (`RESULT_EARLIER_PR_OPEN`). The task's attempts are
     matched by their `work/<attempt id>` branches, never by text.
3. **The push** of `<commit>:refs/heads/work/<attempt id>` from the verified repository goes through
   `repository_access` (Dulwich, no process). It is never forced.
4. **The pull request.** Gitea 28.3.0's create has no draft field. A title with a work-in-progress prefix is a draft
   and not mergeable, so the title is `WIP: ` and the commit's subject, and the read-back requires `draft` true. The
   draft marker does not carry "not mergeable except by the Owner": the demo's protection does.
5. The body is built from the reserved record and the verified result only, with agent text shown as data. A failing
   test run still opens the pull request, marked FAILED, and E-05.5's verified result is then not met (R1).

### 10. The lineage receipt and the Owner report

1. **The receipt** (`result-receipt/v1`, in the confirmed result journal) holds, in the lineage reader's grammars:
   `workRef` (`backlog:`), `outcomeRef`, `executionRef` (`openhands:conversation/`), `baseRef` and `resultRef`
   (`git:<repository>@<commit>`). It also holds the design revision, the branch, the pull request (number, URL,
   title, author, body digest), the bundle's digest, the trailers, what the run wrote, the test status and output
   digest, the report's digests and both searches' summaries. The trailers and the body mirror it on Gitea. No
   lineage kind or resolver edge is added.
2. **The Owner report** (`owner-report/v1`, JSON and Markdown) is built by host code from the verified objects, with
   no process launched. It gives the identities, the pull request, the commit message, the diff base to result
   (bounded, with the whole diff's digest), the tests labelled "not independent CI", R3's exclusions, the search
   summary and the run's observations. It is written exclusively and is readable without a Gitea sign-in.

## Consequences

- An attempt's trusted side accepts two things: one git bundle, whose single commit must be the commit the dispatcher
  specified over whatever tree the container produced; and text, handled as data. Nothing the conversation wrote
  reaches a commit header, a pull request's title or body, or a store record, except through the shown-as-data
  report and body after the search.
- One live run used every part of this design and published a draft pull request
  ([evidence](../evidence/D1-run-2026-11-16.md)): `disposition` `published`, no stop, no interruption.
- Adding a third proxy tail, another builder, or a different result path is a change to this record. A new tail is
  also a profile change and a promotion.
- **Residuals**, each stated where it lives:
  1. **The builder registry is in-process module state.** Code inside the dispatcher's own process can still reach it
     (the A3 ruling S6). The pinned names and the seal bound only what other modules can do.
  2. **RESULT's standard output can be forged** by a process the agent left running. A forged marker is a repeated
     one and is refused, and a forged excluded list only misreports what was left out. The host's commit-id equality
     and its own tree policy bound what reaches the branch. The test output is the agent's code's output and can be
     influenced (the report's label says so).
  3. **The attribution residual** carried from E-05.11's
     [verdict](../evidence/bootstrap-log.md#e-05-11-verdict-2026-11-15). The container guard refuses packets addressed
     to the guest itself, and some refusals are not attributable to a logged line. The run's (7c) and (10b) read
     UNKNOWN on exactly that: 3 name lookups after the prompt and 5 refusals beyond the logged lines, with the egress
     guard 0 to 0 and the tunnel's targets `api.anthropic.com:443` only. Planning reconsiders it under that entry's
     conditions.
  4. **The 128 KiB argument limit.** SEED and RESULT ride one `/bin/sh -c` argument of at most 131072 bytes,
     observed live at step 0. The live run used 19165 and 66607 bytes. A larger repository needs another way in (an
     exchange push), which is a change to this record.
  5. **One dispatcher process.** The builder registry, the commands it made and the held role tokens are one
     process's state, and no second process runs an attempt of the same work item. It is assumed, not enforced
     across processes (review N6).
  6. Names with an ignorable code point (a zero-width space) are not folded away by R3's comparison (review A4 N-f).
     The workspace's own `.gitignore` and `.gitattributes` apply to `add -A`, and the agent controls both (review
     N1).

## Not decided here

1. **A finished attempt with no usable result** (an empty change, or a result the intake refuses). No record closes
   such an attempt, and none admits another, so the task is stranded. It changes E-05.5's criterion, so it is the
   product manager's. As built, the result journal is `failed` with its code and nothing reaches Gitea.
2. Independent CI on the work branch, and review: other leaves.
3. Live merge negatives: the bot's inability to merge stands on the absent merge route, the fake's refusal and the
   demo's protection. A live bot merge on the real pull request was deliberately not attempted.

## Evidence

- The live run: [`evidence/D1-run-2026-11-16.md`](../evidence/D1-run-2026-11-16.md).
- The design's history: the [handoff](../evidence/bootstrap-log.md#handoff-d1-promotion-v2-2026-11-16) and the
  [promotion](../evidence/bootstrap-log.md#d1-promotion-v2-2026-11-16).
- The code and its documentation: `integrations/dispatch/dispatch_inputs.py` (the client),
  `integrations/dispatch/guest_transport.py`, `integrations/dispatch/attempt_run.py`,
  `integrations/dispatch/result_path.py`, `integrations/dispatch/attempt_tokens.py`,
  `integrations/dispatch/attempt_end.py`, `tools/guest.py` (`d1_run`, `D1_RUN_RULE`, the API probe's exchange
  delivery), `integrations/dispatch/tests/live_d1_run.py`, `integrations/dispatch/tests/live_step0_rehearsal.py`, their
  tests, and `integrations/dispatch/README.md` (sections "The attempt run", "The result path", "The D1 run").

The commits:

| Slice | Commits |
|---|---|
| A1: the tails, the transport, the digest | `9684d9c`, `2ffc5a4`, `0c1f105`, `21a1f12`, `e8772a9` |
| A2: the attempt run | `e08852a` |
| A3: the fix round on the review of A1 and A2 | `6d9b779`, `c57494c` |
| A4: the delta check's fixes | `f3c3f1b`, `5edeffc` |
| B: the result path (E-05.4) | `0a0ba01`, `bc586fb` |
| C: the run driver and step 0 | `a9abdeb`, `6b7f32f`, `1ff9cf7`, `24d4ec9`, `536f427` |
| C2: the fix round on the review of B and C | `9030bfb`, `a0f6f9a`, `d5497f0`, `981e4c8`, `d487503` |
| The second delta check | `260ab8a`, `e21d7dd`, `6ddffef` |

## Not verified

- Linux and macOS hosts.
- Live: a resumed run, a stop and its end, a failing test run, a refused intake, an empty change, a lost answer at the
  push or the pull request, a second attempt of a work item, and step (10c). Each stands on its offline tests only.
- Gitea versions other than 28.3.0.
