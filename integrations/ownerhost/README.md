# The Integration process (`integrations/ownerhost/`)

Plan leaf **U-01.3**; [decision 0025](../../decisions/0025-integration-process-owner-ui-session-credential-and-owner-conversation-store.md)
(accepted at U-01.3's verdict); the I1 work design ([`evidence/I1-integration-design-2026-11-16.md`](../../evidence/I1-integration-design-2026-11-16.md),
rulings R1 to R4 and R7). The Owner UI's backend on the host: a Starlette application on uvicorn (the versions the
component lock pins, in the hash-locked tools set), run under the tools interpreter, bound to `127.0.0.1:13310`
only. The Owner UI shell ([`apps/owner-host`](../../apps/owner-host/README.md)) reaches it with the Owner UI session
credential, `cred-owner-ui-session`, which the Owner mints himself at a console.

Behind the credential: `POST /session` answers the authenticated session's public id and validity (the shell's
sign-in), and since U-02.1 the thread and history routes keep the Owner chat in the conversation store (below);
since U-02.2 a pending decision kept there survives a restart of the process and a reopened browser, once; since
P-01.3 an Owner message sent through the shell's request form is captured as an OpenSpec intent change in the project
repository ([below](#capture-p-013)); since P-04.4 the Owner accepts an objective of such a change on the acceptance
recorder's challenge, bound to his session ([below](#objective-acceptance-p-044)); since U-04.1 an outcome's
read-only projection joins its lineage with each attempt's observed state ([below](#outcome-projection-u-041)). It has
no dispatch endpoint.

## Files

| Path | What |
|---|---|
| `app.py` | The ASGI application (`create_app`), its three request checks, the session route, the thread and history routes, the capture route, the two acceptance routes (`acceptance-challenge`, `acceptance`) and the outcome projection's route; `bind_listener` and `serve`, the server process |
| `capture.py` | P-01.3: the request layout's parser, the intent record it writes, the project configuration (`components.owner_host`), the commit identity, the write-ahead receipt and the commit |
| `acceptance.py` | P-04.4: the review and acceptance layouts, the challenges held in memory, the session-binding verifier, the checks before the reservation (the preflight included), the write-ahead receipt, the recorder's commit and the settlement by reading |
| `projection.py` | U-04.1: the outcome projection (`outcome-projection/v1`): the lineage traversal joined with each attempt's typed status from the dispatcher's records (the state table below), its result's claims and its result receipt as evidence; `Projection`, the route's configuration and refusals |
| `bound_authority.py` | U-04.1: an attempt's bound authority read from its reservation's pinned route allowlist, transport-free, with codes of its own (R11; the dispatcher's own reader holds the Agent Server client) |
| `session.py` | The credential's shape and verifier, and `check`, which decides one request against the session table |
| `enroll.py` | The Owner's enroll command: the console guard, minting, the session row, the one showing |
| `service.py` | The lifecycle verbs through the platform contract (decision 0011): `up`, `down`, `restart`, `recover`, `status`, `inspect`, `verify`, and the supervisor |
| `tests/test_session.py` | The shape, the verifier, `check`'s four refusals (each changing nothing), every other inventory credential shape refused, enrollment (unit) |
| `tests/test_app.py` | The route-table walk, the preflight, Host and Origin, the refusals over ASGI, no cookie, the log (contract) |
| `tests/test_enroll.py` | The console guard on pipes, files and the null device, refusing before anything is resolved or written; gate G8 on a real (hidden) console in a child process (unit, integration) |
| `tests/test_service.py` | The server's environment allowlist, the configuration, readiness from the TCP table, `up`'s refusals, `down`, with a fake adapter; a record replaced while another handle reads it waits for the reader within the ceiling, any other refusal is raised at once, and a read that meets a replacement is made again (Windows) (unit) |
| `tests/test_structure.py` | R2's structural tests: no client socket (syntax trees), the import census (a fresh interpreter), one declared port (unit, integration) |
| `tests/test_listener.py` | The real start and stop on a throwaway layout: the listener table, the host census by port, every request over HTTP, the refusals, the environment and command line read from outside, the records and logs, the live import census, no window, no orphan (integration, Windows) |
| `tests/test_history_routes.py` | The thread and history routes over ASGI: initialize, list, fetch, rename, archive; append, update, load; the store's refusals, the body rules, the log (contract) |
| `tests/test_history_listener.py` | U-02.1's proof against the real service: a reload after a restart, repeats, the refusals, a quote cut from a received statement and a changed source byte (integration, Windows) |
| `tests/test_pending_decision.py` | U-02.2's proof against a real Integration process the test starts (`app.serve` through `serve_on_port.py`) on a free loopback port and a throwaway state directory, stopped by its stop request and started again twice: the shell's recorded pending-decision requests replayed, the thread and its pending call back once, a reconnect adding nothing, the answer an update of the same id; the lineage resolvers reading the store it wrote (integration) |
| `tests/test_outbound_guard.py` | The outbound guard in a real server process on a free port (`serve_outbound_probe.py`): connect, connect_ex and getaddrinfo refused before the call, the process still serving, the guard armed by the lifespan; never armed in the test process (integration) |
| `tests/test_capture.py` | P-01.3's proof in throwaway stores and a throwaway project repository: one change per message, idempotent across a retry, a restart and a reconnect; the quote's span, `check_intent_record.py`, the originates edge (after the acceptance recorder accepts O1 with a synthetic statement); the digest mismatch changing nothing; the layout refusals (bidirectional controls included); the crash windows, the commit id recorded before the branch moves, and settlement through every branch and parent (a branch switch, a merge without fast-forward, packed references, a rewritten history); a confirmed receipt under another configuration; the work-tree flag; the store's refusals; the commit identity, its placeholder classes and the session's principal; the harness checkout refused as the project; no socket, no process, no model (integration) |
| `tests/test_acceptance.py` | P-04.4's proof in throwaway stores and a throwaway project repository whose change the capture made: the outcome minted once and resolved, the statement resolved to the Owner's message, a re-acceptance keeping the id, author and committer; every refusal (challenge, session, statement, card, layout, repository state, configuration) changing neither the project repository nor either store; the verifier clause by clause; the race window and settlement; the shell's code list; no socket, no process (integration) |
| `tests/test_projection.py` | U-04.1's proof over attempts the dispatcher's own writers made on a throwaway store (the dispatch suite's `test_authority.Bound`): every status of the state table, the exit claims, the end mapping, R11's label rule, a fixture and a live attempt run to a published receipt, the outcome-level join, archived, deleted and reused task ids from Backlog.md's recorded output, read-only stores and reads, the route's guards and refusals (integration) |
| `tests/test_bound_authority.py` | The authority reader compared with `dispatch_inputs.attempt_authority` and `bound_label` on each case of its list, the known divergence (each admission code beside the pin's), the shared constants (integration, unit) |
| `tests/fixtures/backlog-archive/` | Backlog.md 1.55.3's own `task list --json` and `task view --json` output in a throwaway project (recorded 2026-11-17): `TASK-2` archived (`archived/`), then deleted (`deleted/`: its view fails), then its id taken by a new task (`reused/`) |
| `tests/serve_on_port.py` | The test-side child: `app.serve` on the port the test chose, never 13310 |
| `tests/ownerhost_support.py`, `tests/process_probe.py` | The fixtures (throwaway stores and credentials, the inventory's credential shapes built at run time) and the outside read of a process's environment block and command line |

## The credential

`cred-owner-ui-session` is `aieh-oui-` followed by 52 lower-case base32 characters (32 random bytes): not an Agent
Server key (43 URL-safe characters, no prefix), not an attempt token (`aieh-inf-`), not a provider key (`sk-ant-`),
not a Gitea token (40 hexadecimal digits). The Owner conversation store
([`integrations/conversation`](../conversation/README.md)) keeps only its **verifier** (sha256 of the domain line
`ai-engineering-harness/owner-ui-session/v1` and the credential), the session's public id, its issue time and its
expiry; the credential itself is stored nowhere. One session is current: a new enrollment supersedes it.

The shell sends it in the `X-AIEH-Owner-Session` header on every request, never as a cookie, and keeps its copy in
its own origin's `localStorage` until Sign out (decision 0025 point 4, as amended).

### enroll (the Owner's act)

```
<tools python> -I -B integrations/ownerhost/enroll.py [--hours N]       # task ownerhost:enroll
```

Run by the Owner, in his own console window. It refuses unless standard input and standard output are both console
handles (`ENROLL_NOT_INTERACTIVE`: the broker's GetConsoleMode check, reused), before it resolves the managed root,
opens the store or mints anything: plain pipes and redirected handles, an ordinary tool shell's accidental run,
obtain nothing. It then mints the credential, writes the session row (validity `--hours`, default 12, 1 to 168), and
shows the credential once on the console with the session id and expiry. Exit 0 enrolled, 2 refused. No test runs
it against the managed root; OA-32 (a) is the Owner's own enrollment.

What the guard does not do: it does not stop a process of the Owner's account that gives the command a console (one
of its own, hidden or not, or a pseudoconsole) and reads it, or that calls `enroll()` or writes the store. No console
check can tell the Owner from such a process; that is decision 0010 point 1's accepted same-account limit (decision
0025, Consequences). Any such enrollment supersedes the Owner's session, which then answers
`SESSION_CREDENTIAL_REVOKED` at his next request, unless a same-account writer of the store undoes it first
(decision 0010 point 1) (`tests/test_enroll.py` `GuardScope` shows a hidden console passing the guard).

## Every request

Outermost first; a refusal changes nothing, and the credential is never echoed or logged.

| Check | Refusal |
|---|---|
| `Host` is exactly `127.0.0.1:13310` | `HOST_NOT_ALLOWED` (400) |
| `Origin`, when present, is `http://127.0.0.1:4173` or `http://127.0.0.1:5173` | `ORIGIN_NOT_ALLOWED` (403) |
| CORS (Starlette's CORSMiddleware): those origins only, no credentials mode, only the session header and `Content-Type`; it answers the preflight, the one request without the credential, which carries no data | 400 for a preflight asking for another header |
| The session header: present, of the shape, matching a current, unexpired session | `SESSION_CREDENTIAL_MISSING`, `_FOREIGN`, `_REVOKED`, `_EXPIRED` (401) |

A superseded session is `_REVOKED` whether or not it has also expired; an expired current session is `_EXPIRED`; a
value that is not of the shape, or matches no enrolled verifier, or is sent twice, or whose session was issued more
than 5 minutes after now (no enrollment on this host writes one), is `_FOREIGN`. A path that is no route is refused
by the credential check first, then answers `NOT_FOUND` (404) or `METHOD_NOT_ALLOWED` (405), whose details do not
echo the path. A websocket is closed (1008): there is no websocket route, and uvicorn runs with `ws='none'`.

The service log (`<logs>/owner-host/service.log`) records each decided request as `accepted METHOD ROUTE STATUS
session=<public id>` or `refused CODE METHOD ROUTE`, where ROUTE is the path of the route the request matched or
`unmatched`, and METHOD a common method or `OTHER`: nothing the client wrote is logged verbatim, so no path can forge
a log line or carry a credential into the log. uvicorn's access log is off.

## Threads and messages (U-02.1)

[Decision 0025](../../decisions/0025-integration-process-owner-ui-session-credential-and-owner-conversation-store.md)
point 6; the store's rules are in [`integrations/conversation`](../conversation/README.md#migration-0002-threads-and-messages-u-021).
The backend of the shell's `RemoteThreadListAdapter` and `ThreadHistoryAdapter` (assistant-ui), every route behind the
credential and every write attributed to the authenticated session:

| Route | Adapter call | Answer |
|---|---|---|
| `GET /threads` | `list` | `{threads: [{remoteId, status, title?}]}` |
| `POST /threads` `{localId}` | `initialize` | `{remoteId}`: the store mints it, once per session and local id |
| `GET /threads/{thread_id}` | `fetch` | `{remoteId, status, title?}` |
| `POST /threads/{thread_id}/title` `{title}` | `rename` | the thread |
| `POST /threads/{thread_id}/archive`, `/unarchive` | `archive`, `unarchive` | the thread |
| `POST /threads/{thread_id}/delete` | `delete` | always `THREAD_DELETE_REFUSED` (409): nothing is deleted |
| `GET /threads/{thread_id}/messages` | history `load` | `{messages: [{seq, parentId, message}]}` in `seq` order, no head |
| `POST /threads/{thread_id}/messages` `{parentId, message}` | history `append` | `{id, seq, revision, changed}`; `changed` is false for a repeat |
| `POST /threads/{thread_id}/messages/{message_id}` `{parentId, message}` | history `update` | the same; an upsert for an assistant message, a user message is immutable |

A body is one JSON object, `Content-Type: application/json` (else 415), at most 1 MiB (`REQUEST_TOO_LARGE`, 413), with
no duplicate key and no NaN or Infinity (`REQUEST_INVALID`, 400). The store's refusals keep their codes:
`THREAD_INVALID` and `MESSAGE_INVALID` (400), `THREAD_NOT_FOUND` and `MESSAGE_NOT_FOUND` (404),
`MESSAGE_PARENT_NOT_FOUND`, `MESSAGE_ID_CONFLICT`, `MESSAGE_IMMUTABLE` and `THREAD_DELETE_REFUSED` (409), each changing
nothing. The methods stay `GET` and `POST` (the CORS allowlist is unchanged), so a thread delete is a `POST` to its own
route. The log names the route template (`accepted POST /threads/{thread_id}/messages 200 session=<public id>`): no
thread id, message id or text reaches it. Any current session reads and writes every thread, threads created under
superseded sessions included (decision 0025: one Owner, no per-session isolation); a row names the session that wrote
it.

## Capture (P-01.3)

Plan leaf **P-01.3**; decision 0025 point 8; the I1 work design, R6 and slice 8. `capture.py` holds the rules; this is
their summary.

| Route | Answer |
|---|---|
| `POST /threads/{thread_id}/messages/{message_id}/capture` `{sha256}` | `{change, commit, created, receipt, state, quote, files, project}`, and `workTree` when the branch holds the commit and the work tree or the index does not hold its files; `created` is false when the message was captured already |

**No model is called.** The structure of a requested change comes from the Owner: the shell's request form
(`apps/owner-host/src/areas/RequestForm.tsx`) sends **one** message in a fixed layout, and the capture parses that
layout only:

```
Change: <change name, kebab-case>
Objective: <one line>
Acceptance criteria:
- <one line>            (one or more)
Suggestion: <one line>  (zero or more)
```

LF between lines, no final line break, every value one non-empty line with no surrounding whitespace, no control or
separator character but a tab, and no bidirectional control character (U+202A to U+202E, U+2066 to U+2069: they make
the text shown differ from the bytes recorded). Zero-width characters (U+200B to U+200D, U+2060) are accepted and
recorded as they are. Anything else is `CAPTURE_LAYOUT_INVALID` (422) naming the line: nothing is guessed, trimmed or
reordered. The shell's model-free chat adapter asks for the capture of a message that begins `Change: `, once the
history adapter has stored it, and replies with a card built only from the answer or the refusal.

**In order, each refusal changing nothing:**

| Code | Status | When |
|---|---|---|
| `REQUEST_INVALID` | 400 | the body is not `{sha256}` with 64 lower-case hex digits |
| `CAPTURE_PROJECT_UNCONFIGURED`, `CAPTURE_CONFIG_INVALID` | 503 | `components.owner_host` is absent, or malformed |
| `THREAD_NOT_FOUND`, `MESSAGE_NOT_FOUND` | 404 | the store's own codes |
| `CAPTURE_NOT_A_STATEMENT` | 409 | the message is not an Owner statement |
| `CAPTURE_MESSAGE_MISMATCH` | 409 | the request's sha256 is not the **stored bytes'** |
| `CAPTURE_LAYOUT_INVALID` | 422 | the layout, naming the line; or a record the layout admits that does not pass `tools/check_intent_record.py` |
| `CAPTURE_SESSION_UNRECOGNIZED` | 403 | the authenticated session is not decision 0025's one-Owner session (`session_principal`) |
| `COMMIT_IDENTITY_UNAVAILABLE`, `COMMIT_IDENTITY_INVALID`, `COMMIT_IDENTITY_PLACEHOLDER` | 503 | the commit identity (below) |
| `CAPTURE_STORE_UNAVAILABLE` | 503 | no integration store is named, or the store refuses (it does not open, a restore epoch is open, a transition is refused) before anything is on the branch |
| `CAPTURE_PROJECT_UNAVAILABLE` | 503 | the configured path is not the root of a work tree with a commit on a branch (nothing above it is searched) |
| `CAPTURE_PROJECT_IS_HARNESS` | 503 | the configured path is the harness checkout the Integration process runs from, or shares its git common directory (a worktree of it), checked before any receipt |
| `CAPTURE_CHANGE_EXISTS` | 409 | the change name is taken |
| `CAPTURE_RECEIPT_CONFLICT` | 409 | the message's receipt holds another intent: another project (id or path), change or message digest |
| `CAPTURE_COMMIT_REFUSED` | 409 | the repository refuses the commit before anything is written (a client hook, local changes, a moved branch three times) |
| `CAPTURE_COMMIT_UNREACHABLE` | 409 | the receipt recorded a commit no local branch reaches (a rewritten history), and no branch holds one with its trailer |
| `CAPTURE_GIT_FAILED` | 500 | the repository cannot be read or written |
| `CAPTURE_OUTCOME_UNKNOWN` | 500 | the store refuses once a commit may be on the branch (the detail names it), or a receipt is `dispatched` with no recorded commit |

**The change.** One commit through `repository_access.Repository.write_commit` (a compare-and-swap of the branch) adds
exactly `openspec/changes/<change>/proposal.md` and `.openspec.yaml` (schema `intent-driven`, and `created:` the date of
the message's `createdAt`, which is the **client's** clock as the shell stated it when it appended the message, not
the server's). Its intent record (`intent-record/v1`, `normalized_by: agent:owner-host-capture@1.0.0`): Q1 is the whole
message under its span anchor (`conversation:<thread>/<message>#span:0+<n>:sha256:<digest>`, cut with
`lineage.span_reference` from the stored bytes); O1, each ACn and each Mn are exact byte spans of it, `attributed_to:
owner`, `source: Q1`; a suggestion is a Proposed Method with `claim_type: hypothesis` and its Hypothesis, never the
objective; the Hypotheses' one sentence is the only statement the capture wrote. The record passes
`tools/check_intent_record.py` against the stored bytes before anything is written. The commit message carries the
trailer `Intent-Capture: owner-ui/intent-capture/v1/<thread>/<message>`.

**One change per message.** The write-ahead receipt `owner-ui/intent-capture/v1/<thread>/<message>` (format
`aieh-owner-ui-intent-capture/1`) is reserved in the managed integration store before the commit (the message, its
sha256 and its session, the project's id and path, the change and the files' digests in the intent). When the commit's
objects are written and **before the branch moves**, it goes to `dispatched` with the commit id (`write_commit`'s
`check`); once the branch has moved, to `confirmed` (the capturing session in each detail).

- A confirmed receipt answers its commit, built from the receipt's own intent, never from the current configuration,
  and only for the request it was made for: another project (id or path), change or message digest is
  `CAPTURE_RECEIPT_CONFLICT`.
- A receipt left `reserved` or `dispatched` (a process that ended between the receipt and the confirmation) is
  settled **by reading the project repository first**, through every local branch (`refs/heads/*`, loose and
  packed) and every parent, not the first parent only: the recorded commit when a branch reaches it, else a commit
  carrying the trailer. When one is there the receipt is confirmed with it and nothing is written again, whichever
  branch is checked out (a branch switch, a merge without fast-forward and a deleted branch included). When the
  branch checked out holds the captured files and the work tree or the index does not (a process that ended between
  the branch's move and the work tree), the answer says so in `workTree`, and the shell's card tells the Owner.
- A recorded commit that no branch reaches (a rewritten history) is `CAPTURE_COMMIT_UNREACHABLE`, and nothing is
  written: putting the commit back on a branch has it answered; otherwise the request is sent again as a new message.
- A refused commit (`CAPTURE_COMMIT_REFUSED`, `CAPTURE_GIT_FAILED`) before its objects are recorded writes nothing and
  leaves the receipt `reserved`, so the same message is captured once the repository is repaired. A branch that moves
  under the capture is read again (at most three times); when it moves between the recording and the update, the
  receipt keeps the first commit id and the later attempt's commit is found by its trailer. A refusal after the
  recording leaves the receipt `dispatched`, and the next capture settles it as above.
- Captures are serialized: the route runs the capture on the server's one event loop, so **a capture blocks the
  process's other routes** (the thread and history routes included) while it runs; a capture reads and writes one
  local repository and the store, with no network.

The branches come from the repository-access module's `Repository.branches()` (loose and packed, through Dulwich's
refs container), and each commit is read through the same module.

**Who commits.** The commissioning user is the author and the committer of the commits the harness makes on that
user's behalf: the commit is made under the user's own git identity, and the harness is the user's mechanism. In I1
the user is the one enrolled Owner: `session_principal` maps decision 0025's one-Owner session (every Owner UI session
is his; the conversation store records his statements with author `owner`) to the principal `owner`, and is the only
place a session becomes a principal. Agents and components get no git identity: provenance lives in the intent record
(`normalized_by`), the lineage (the message's bytes, sha256 and session) and the evidence and receipts, and authorship
grants nothing. The identity is set explicitly, per principal, under `components.owner_host.git_identities` (below); it
is never read from git configuration or the environment and never inferred, and there is no shared default or
fallback. Refused, with nothing written and no receipt:

- `COMMIT_IDENTITY_UNAVAILABLE`: none for the principal; another principal's is never used.
- `COMMIT_IDENTITY_INVALID`: not `Name <email>` (a line break, `<` or `>` in the name); a name with no visible
  character, or with a control or format (Unicode Cf) character, such as a zero-width space or a bidirectional
  control; an email that is not ASCII (a full-width or ideographic dot is not a dot).
- `COMMIT_IDENTITY_PLACEHOLDER` (decision 0028 point 5, its list extended by the engineering manager on 2026-11-16):
  `localhost`, or under `.invalid`, `.localhost`, `.example` or `.test`; `example.com`, `example.net`,
  `example.org` (RFC 2606) or below them; under `.local`, `.internal`, `.home.arpa` or `.lan`; an IP literal,
  bracketed (`[192.0.2.1]`) or bare (`192.0.2.1`, `127.1`, `::1`); a single label (`user@host`, git's own fallback
  shape).

A GitHub no-reply address is accepted, and so is any other real address the user configured; `.onion` is accepted.
This is not decision 0025's undecided "separate host identity for the service", which is an operating-system account.

**Configuration.** service.py, never the server, reads `components.owner_host` of `config.yml` and passes it to the
server as JSON, with the managed integration store's path (`<state>/integration/integration.sqlite`):

```yaml
components:
  owner_host:
    project_repository: /absolute/path/to/the/project/work/tree   # its root; a copy of D1's demo repository in I1
    project_repository_id: aieh-d1-demo
    backlog_command: /absolute/path/to/backlog.md/cli.js           # for the projection (U-04.1); unused by the capture
    git_identities:
      owner: "<Your Name> <<id>+<login>@users.noreply.github.com>"   # a placeholder the capture refuses: replace it
```

The `git_identities` value shown is a placeholder that `COMMIT_IDENTITY_INVALID` refuses until the user replaces it with
his own identity. Absent, the capture answers `CAPTURE_PROJECT_UNCONFIGURED`; malformed, `CAPTURE_CONFIG_INVALID`; the service itself
starts either way. A change of the configuration takes effect at the next start.

The configured identity is not a secret and is not kept as one: `components.owner_host`, `git_identities` included,
is passed on the server process's command line (`--owner-host-config`), which any process of the same user can read,
and written to the run record (`<state>/owner-host/run.json`, its configuration snapshot).

## Objective acceptance (P-04.4)

Plan leaf **P-04.4**; decision 0025 points 8 and 9; the I1 work design, R6 and slice 10. `acceptance.py` holds the
rules; this is their summary. The Owner accepts an Objective item of an intent change on the acceptance recorder's own
challenge (P-04.1, `integrations/owner/acceptance_recorder.py`, run in process), and the statement is bound to his
authenticated session rather than declared by a transcriber. No model is called.

| Route | Answer |
|---|---|
| `POST /threads/{thread_id}/messages/{message_id}/acceptance-challenge` `{sha256, card}` | `{nonce, change, item, revision, proposal, summary, expiresAt, card, request}`: the recorder's challenge for the Owner's message `Review acceptance: O<n> of <change>` (exactly that line), shown in the card the shell is writing |
| `POST /threads/{thread_id}/messages/{message_id}/acceptance` `{nonce, sha256}` | `{change, item, outcome, minted, commit, decision, reference, statement, receipt, created, state, project}`, and `workTree` as the capture's: the Owner's message `Accept O<n> of <change>` (optionally followed by a line break and his own words) recorded on that challenge |

- **The challenge** is held in the process's memory by its nonce, with the thread, the review message, the card's id
  and the session it was issued to, and the thread's highest `seq` at that moment. A restart loses it: an acceptance on
  it is `ACCEPTANCE_CHALLENGE_UNKNOWN` (fail-closed), and the Owner reviews again. The card's id is the one id a request
  proposes (decision 0025 point 8 asks for server-held ids): at `prepare` the card is still being written, so it is
  checked against the store at `record`: stored after the challenge was issued, an assistant message, the reply to the
  review, in the same session, and an ancestor of the acceptance.
- **The statement** is built from the store, never from the request: `text` the stored bytes, `attributedTo: owner`,
  `channel: owner-ui`, `reference: conversation:<thread>/<message>#sha256:<digest>`, `recordedBy: owner`; the recorder
  admits `owner-ui` only with the session-binding verifier (`SessionBinding`) this module passes.
- **Before anything is written**, each refusal with a stable code and nothing changed: an assistant message
  (`ACCEPTANCE_MODEL_AUTHORED`), the digest (`ACCEPTANCE_MESSAGE_MISMATCH`), another session's message or challenge
  (`ACCEPTANCE_SESSION_MISMATCH`), the layout (`ACCEPTANCE_LAYOUT_INVALID`), the challenge (`ACCEPTANCE_CHALLENGE_UNKNOWN`,
  `ACCEPTANCE_CHALLENGE_MISMATCH`, `ACCEPTANCE_NOT_AFTER_CARD`, `CHALLENGE_CONSUMED`, `CHALLENGE_EXPIRED`,
  `CHALLENGE_STALE`), the capture's configuration, identity and project refusals (a detached HEAD is
  `CAPTURE_PROJECT_UNAVAILABLE`, refused when the project is opened), and the `preflight`: the repository-access
  module's `write_commit` asked to commit the change's files with their HEAD bytes, which it refuses before writing
  anything (`HOOKS_UNSUPPORTED`; `COMMIT_REFUSED` for `commit.gpgSign`, unmerged index entries or local changes to
  those files; `GIT_FAILED`); the decision-record directory `owner-decisions/` (`COMMIT_REFUSED` when a symbolic link
  or a junction leads to it, or a file, tracked or not, is in its way); and the content, through the recorder's own
  functions (`INTENT_RECORD_INVALID` for the proposal with the acceptance set, `RESOLUTION_FAILED` when the x-outcomes
  block would not read back as declared).
- **One commit per message**, the recorder's, behind the write-ahead receipt `owner-ui/objective-acceptance/v1/<thread>/
  <message>`; its author and committer are the session principal's configured identity (decision 0028). The outcome id
  is minted once and kept on a re-acceptance. A confirmed receipt answers the same commit, only for the same project,
  change, item, digest and nonce (`ACCEPTANCE_RECEIPT_CONFLICT`).
- **What can still reach the recorder's own checks after the reservation**, and nothing else: a race (another process
  changing the project repository between those checks and the commit; the refusal keeps its code); the lineage
  objective resolver's check of the new commit before the branch moves, which needs the commit's objects, and the
  recorder's own invariant on the decision record it builds (`RESOLUTION_FAILED`); an object store that cannot be
  written, or any other failure inside the commit (`ACCEPTANCE_OUTCOME_UNKNOWN`: a commit may exist). In each case the
  receipt stays `reserved`, and the same message, sent again once repaired, records exactly once: it is settled by
  reading every local branch and parent first. Once a commit may exist (an earlier receipt not confirmed, or a
  failure inside the commit), a failure of that reading is `ACCEPTANCE_OUTCOME_UNKNOWN`, never `GIT_FAILED`. If the
  cause outlives the challenge, the Owner reviews again and sends a new Accept message (a new receipt key); the old
  receipt stays `reserved`, as the store never deletes one.

## Pending decisions across a restart (U-02.2)

No route changes. A run paused on the shell's `owner_decision` human tool is appended as an assistant message with
status `requires-action` (`POST /threads/{thread_id}/messages`); the Owner's answer is its update
(`POST /threads/{thread_id}/messages/{message_id}`), which the store keeps as the next revision. The process keeps no
state of its own, so after it stops and starts again the history load answers the paused message, once, from the
store. `test_pending_decision.py` shows it with the shell's own requests (recorded and checked by the shell's test,
`apps/owner-host/src/areas/fixtures/pending-decision.wire.json`) against a real process: it starts `app.serve` itself
on a free loopback port, never `127.0.0.1:13310`, so a running Owner instance is neither needed nor touched, and it
stops only the processes it started. It stops the process gracefully, by its stop request: a killed process is not
exercised.

## Outcome projection (U-04.1)

`GET /outcomes/{outcome_id}` answers the read-only projection of `outcome:<outcome_id>` (`projection.py`), behind
the session, Host and Origin guards like every route. It runs on the event loop, as the capture does.

**The schema, `outcome-projection/v1`.** Two fields that are easy to confuse are kept apart and named so:
`lineageVerdict` is about the references (do the outcome's objective, statements and tasks resolve, and what is
uncertain), and each attempt's `executionStatus` is about what the dispatcher's records show it did.

| Key | What |
|---|---|
| `format`, `outcome` | `outcome-projection/v1`; the outcome reference |
| `lineageVerdict` | `failed` when an objective, statement (`message`, `conversation`) or task (`work`, archived ones included) reference does not resolve; else `incomplete` when `lineageUncertainties` holds anything; else `complete`. It is never `complete` while the outcome has an attempt: an attempt node's lineage resolution is never asked here (`RESOLVER_NOT_CONFIGURED`), and a fixture-bound attempt adds `FIXTURE_AUTHORITY` (R11). U-06.1's item 8 is judged from the dispatcher-side trace in its run record (R6; PB-5), never from this verdict |
| `lineageUncertainties` | The lineage's own uncertainties, unfiltered, and one `fixture-authority` (`FIXTURE_AUTHORITY`) per fixture-bound attempt node |
| `objective`, `statements`, `designs` | The lineage nodes of those roles, as `lineage-projection/v1` has them |
| `tasks` | Per task: its reference and resolution, how it was reached (`listing`: Backlog.md lists it citing the outcome or its design; `attempt`: only an attempt reservation citing it and the outcome), its attempts in reservation order, and `execution`: its latest attempt's execution status and code. The latest is the last reserved, by the typed attempt's reservation event (the store's `attempt_event.event_id`, an `INTEGER PRIMARY KEY` of an append-only table, so monotonic), never by ordinal: ordinals restart per work item, design revision and stage. `pending` `NO_ATTEMPT` when the store was read and holds none; `unknown` `STORE_UNAVAILABLE` when it could not be read |
| `attempts` | Per attempt: its ids and `reservedEventId`; `executionStatus`, `executionCode`, `detail` and `shownBy` (the record, its state and its last event that decided it), and where a row says so `cause`, `end`, `stops`, `disclosed` (records beside a published result) or `restoredRow` (the row a restore epoch made unproven); `authority` (`shown`: `live`, `fixture` or `unknown`; `bound`: the pinned allowlist's declaration, or none; its code); `result` and `evidence` (below); every record of the attempt it read |
| `failures` | Each unresolved objective, statement or task reference: role, kind, outcome, code |
| `coverage` | Always present: `{"archivedTasksEnumerable": false, "code": "ARCHIVED_TASKS_NOT_ENUMERABLE", "basis": "Backlog.md 1.55.3 task list --json", "detail": ...}` |
| `sources`, `lineage` | The traversal's sources, whether the integration store was read and whether a restore epoch is open; the whole `lineage-projection/v1`, its own verdict and uncertainties included |

Refusals, each changing nothing: `OUTCOME_INVALID` (400: not an outcome id, or a pinned one), and 503 for
`PROJECTION_PROJECT_UNCONFIGURED`, `PROJECTION_CONFIG_INVALID` (`components.owner_host`, read as the capture reads
it), `PROJECTION_STORE_UNCONFIGURED` and `PROJECTION_BACKLOG_UNAVAILABLE` (`backlog_command`).

**Read-only.** The integration store and the Owner conversation store are opened read-only (SQLite `mode=ro`,
`query_only`), the project repository is read through the repository-access module (no git process), Backlog.md runs
only `task list --json` and `task view <id> --json` (`ReadOnlyBacklog`), and OpenSpec never runs. No Agent Server is
asked, and the projection holds no transport.

### The state table

The status of one attempt comes only from the dispatcher's records in the integration store: never from an agent's
exit claim, and never from an Agent Server, real or fixture (decision 0013 point 1; the I1 design, R6). Anything those
records do not determine is `unknown`, never a guess. Each status names the record that shows it. The records are the
typed attempt `attempt/v1/<...>` (its state and its transitions' details) and, under `dispatch/attempt/<attempt id>/`:
the turn journal `turn`, the launch receipt `launch`, the result step's receipts `delivery`, `pull` and `intake`, the
result journal `result` (its confirmed detail is the result receipt, `result-receipt/v1`), the end journal `end` (its
confirmed detail is the end record, `attempt-end/v1`) and the stop receipts `stop/<kind>/<code>`. Every other record
of the attempt (`auth-cause`, `end-cause`, `escalation`, `inference-grant`, `inference-revocation/<n>`, ...) is kept
whole under its full key and label-checked; it decides no row.

The rows are read in order, and the first that matches decides. Changes from the table first written (`73d9e9f`):
the unreadable-record row is read right after the authority row; a published result (row 5) is read before the
launch's not-launched, the stops and the end, which are disclosed beside it (`disclosed`), because a published result
is an observed effect (the review's ruling 7: a stop recorded after it does not unpublish it; the writers refuse a
result after an end or a stop, and an end after a result handed on, so only a later stop can stand beside one);
among the failed rows the launch's not-launched is read before the stops and the end it causes; and a result-step
receipt left `unknown` or `failed` is `unknown` (row 16).

**Absence after a restore is not "not sent"** (decision 0004 point 7; the review's ruling 1). While a restore epoch
is open (`IntegrationStore.open_epochs`), every `pending` or `running` row rests on the absence of a later record that
the restored history cannot prove: it is `unknown`, with the row's own code and the suffix `_UNPROVEN`
(`ATTEMPT_RESERVED_UNPROVEN`, `CREATE_SENT_UNPROVEN`, `TURN_SENT_UNPROVEN`, `MESSAGE_RESERVED_UNPROVEN`,
`LAUNCHED_UNPROVEN`, `CREATED_UNPROVEN`, ...; `restoredRow` names the row). `recover` holds a reserved turn inside an
epoch as `TURN_RESERVED_UNPROVEN` in its report only (it records no hold), so the projection applies the same
condition, the open epoch, and shows `MESSAGE_RESERVED_UNPROVEN`. Outside an epoch the absence rows keep their status,
and their detail states only what is recorded ("no create is recorded"), never that something was not sent.

| # | Records | Status | Code |
|---|---|---|---|
| 0 | The bound authority (R11): the reservation's pinned route allowlist's declaration cannot be read (`bound_authority.py`'s code in `authority.reason`). A typed attempt that is `failed` stays `failed` (row 4), its authority shown as neither | `unknown` | `ATTEMPT_AUTHORITY_UNBOUND` |
| 0 | Fixture-bound, and a record the writers label lacks `authority: fixture` | `unknown` | `ATTEMPT_LABEL_MISSING` |
| 0 | Fixture-bound, and a record carries another label | `unknown` | `ATTEMPT_LABEL_MISMATCH` |
| 0 | Live-bound, and a record carries a label | `unknown` | `ATTEMPT_LABEL_ON_LIVE` |
| 0b | A record in a state the store does not name, not strict JSON, or of a kind the table reads in another format (a confirmed result or end journal without its receipt or record included) | `unknown` | `RECORD_UNREADABLE` |
| 1 | Typed attempt `reserved`: no create is recorded | `pending` | `ATTEMPT_RESERVED` |
| 2 | Typed attempt `dispatched`: the create is recorded sent, its answer is not | `running` | `CREATE_SENT` |
| 3 | Typed attempt `unknown`: the create's answer lost (E-01.4.1 settles it) | `unknown` | `CREATE_OUTCOME_UNKNOWN` |
| 4 | Typed attempt `failed`: a refused create, an admission or seam refusal, a reconciled 404 (the failed move's code in `cause`) | `failed` | `ATTEMPT_FAILED` |
| 5 | Confirmed, and the result journal is `confirmed` with its result receipt (any launch not-launched, stop or end disclosed beside it) | `succeeded` | `RESULT_PUBLISHED` |
| 6 | Confirmed, and the launch receipt's verdict is `not-launched` (the gate) | `failed` | `LAUNCH_NOT_LAUNCHED` |
| 7 | Confirmed, and a stop receipt is confirmed (decision 0024 point 7) | `failed` | `ATTEMPT_STOPPED` |
| 8 | Confirmed, and the end record is written (its trigger, classification, causes and the conversation's execution status the dispatcher surfaced: an `error`, `stuck` or `paused` turn ends here, decision 0024 point 7.5) | `failed` | `ATTEMPT_ENDED` |
| 9 | Confirmed, and the end journal is `unknown` | `unknown` | `ATTEMPT_END_UNSETTLED` |
| 10 | Confirmed, and the end journal is `reserved` or `dispatched` | `running` | `ATTEMPT_ENDING` |
| 11 | Confirmed, and the result journal is `failed` (its code, for example `RESULT_EMPTY_CHANGE`) | `failed` | `RESULT_FAILED` |
| 12 | Confirmed, and the result journal is `unknown`: a write refused or its answer lost | `unknown` | `RESULT_WRITE_UNSETTLED` |
| 13 | Confirmed, and the result journal is `dispatched` | `running` | `RESULT_PUBLISHING` |
| 14 | Confirmed, and the result journal is `reserved`: the host verified the result, no publication is recorded | `running` | `RESULT_VERIFIED` |
| 15 | Confirmed, and an intake, pull or delivery receipt is recorded (read in that order): verified (intake), or reported and not verified (pull, delivery) | `running` | `RESULT_VERIFIED`, `RESULT_DELIVERED` |
| 16 | Confirmed, and that receipt is `unknown` or `failed` (a restore sweep's, for example) | `unknown` | `RESULT_RECEIPT_UNSETTLED` |
| 17 | Confirmed, and the turn journal is `unknown`: the message's answer lost | `unknown` | `TURN_OUTCOME_UNKNOWN` |
| 18 | Confirmed, and the turn journal is `failed` (refused, or the run did not start) | `failed` | `TURN_FAILED` |
| 19 | Confirmed, and the turn journal is `confirmed` (recorded delivered) or `dispatched` (recorded being sent) | `running` | `TURN_SENT`, `MESSAGE_SENDING` |
| 20 | Confirmed, and the turn journal is `reserved`, or the launch receipt says `launched`, or no later record | `pending` | `MESSAGE_RESERVED`, `LAUNCHED`, `CREATED` |

**R11's labels (row 0).** The bound authority is read by `bound_authority.py` from the reservation's pinned route
allowlist. The dispatcher's own reader (`dispatch_inputs.attempt_authority`) lives beside the Agent Server client,
which the Integration process may not load (R2), so this one reads the same records in the same order.
`tests/test_bound_authority.py` compares the two, and `bound_label`, on each case of its list (the checked-in
profiles; the declarations; a drifted, missing, non-object and duplicate-key allowlist; each defect of the pin; the
policy's digest, format and profile; records that are not the dispatcher's, an approval of another schema and an
ordinal that is not an integer among them): what is pinned is that list, not every input. **The known divergence:**
the dispatcher validates the whole admission policy before it reads the pin, this reader only the pin. A record whose
other admission values are invalid while its digests hold is bound here and refused there, with each admission code
but the pin's (`PROFILE_ADMISSION_INVALID` for a missing cap, `RUNTIME_NOT_DOCKER`, `ROUTE_NOT_ALLOWLISTED`,
`WORKING_DIR_NOT_ALLOWED`, `CAPS_ABOVE_CEILING`, `MOUNT_POLICY_INVALID`: `Divergence` shows each); the dispatcher cannot
reserve such a record (admission runs before the reservation, and the record is bound by its digests). The pin's own
defects are refused by both (`PROFILE_ADMISSION_INVALID`, `BINDING_ADMISSION_INVALID`). The labels are read where
E-01.8's writers put them: the top-level `authority` of each `turn`, `launch`, `delivery`, `pull`, `intake`, `end`
and stop record's intent; the intake's `record.authority` too (the verified result's own record); `result.authority`
of the result journal's intent, and a top-level one if present; the result receipt and the end record; and every
transition of the typed attempt after its reservation. On a fixture-bound attempt each of those must carry
`fixture`; on a live-bound one no record may carry a label anywhere, a transition's detail included. Every other
record of the attempt is written without one by design (the engineering manager's `auth-cause`, `end-cause` and
`escalation`, a brokered grant's journals) and must only not carry another. A fixture-answered attempt that passes is
shown `fixture`, never `live`. Since this slice's review, a `not-launched` launch receipt whose admitted values could
not be read carries the bound authority as well (`launch_gate.py`, a writer gap of E-01.8; live receipts unchanged).

**Reported and verified are kept apart.** `succeeded` comes only from the result receipt: the host computed the
commit itself over the pulled bundle (the intake) and read the branch and the draft pull request back (the result
path). Every attempt's `result` shows the claims with their basis: `reported` for what the attempt itself said (the
commit and bundle digest RESULT printed, in the delivery receipt) and for the attempt's own tests (status, command,
output digest: not independent CI); `verified` for what the host established (the intake's commit, tree, base and
bundle). A report never sets a status.

**The result receipt as evidence** (`evidence`, E-05.4's `result-receipt/v1`), by reference and digest, never a copy:
`commit` (`git:<repository>@<commit>`, the commit and the branch: verified), `diff` (from the base reference to the
result reference, with the Owner report's JSON and Markdown sha256, which hold it: verified), `testOutput` (its sha256
and size, status and outcome: reported), `pullRequest` (number, URL, state, draft, the body's sha256: verified), the
bundle's digest, the lineage references, and the receipt's own record, event and sha256. No referenced artifact is
served: the commit and the diff are in the project repository's objects and the report is the result path's file,
each named by its digest, and the receipt holds nothing more.

**Archived tasks.** Every task the projection reaches is resolved through Backlog.md's `task view`, archived ones
included, and an unresolved one is a failure. Backlog.md 1.55.3's `task list --json` does not list an archived task,
and no read command enumerates one (observed 2026-11-17 in a throwaway project: no `task list` option, status, search
or label filter lists it), so a task archived with no attempt citing the outcome is not reached. That limit is the
`coverage` field, on every projection; it is not a lineage uncertainty and does not by itself change the lineage verdict (the
engineering manager's ruling on U-04.1). An attempt's task is always reached, archived or not, through the reservation
that cites the outcome. A known hazard of the pin, shown by a test and not fixed: `task delete` releases an archived
task's id and the next task takes it, so a reference to the deleted task resolves to the later one (a work reference
carries no digest).

## What it never does

Decision 0025 point 2, each with its test: it opens no outbound connection, and the server process holds itself to
that: once uvicorn's event loop runs, `serve`'s lifespan arms `OutboundGuard`, an audit hook that refuses every
`socket.connect` (`connect` and `connect_ex`) and `socket.getaddrinfo` in the process before the call, whatever the
address (a route that tries answers `OUTBOUND_REFUSED`, 500, and the process keeps serving). It is armed after the
loop exists because asyncio's Windows event loop makes its self-pipe with a socketpair that connects to a loopback
listener of its own when the loop is created; nothing connects after that. An audit hook cannot be removed, so only
the server process arms it: `tests/test_outbound_guard.py` runs `serve` in a child (`tests/serve_outbound_probe.py`).
Its one socket is `bind_listener`'s listener, bound with `SO_EXCLUSIVEADDRUSE`, so no other socket binds `127.0.0.1:13310` while it is held, even with
`SO_REUSEADDR`; a socket on another address of the port is not excluded, which `up` and `verify` cover by refusing or
failing on any other holder of the port; readiness reads the kernel's TCP table, never a request. The
server process loads only `app.py`, `session.py`, the conversation store and storecore, and since P-01.3 the
capture's modules (`capture.py`, the integration store, the planning adapter, the shared repository-access module,
`lineage.py` and `tools/check_intent_record.py`), since P-04.4 the acceptance's, and since U-04.1 the outcome
projection's (`projection.py`, `bound_authority.py` and `integrations/lineage/lineage_trace.py`, each by exact name): no credential, Gitea, authorization-recorder, dispatch or inference
module, and no network client (the repository-access module's remote transport, which imports one, is never reached:
a whole capture audited opens no socket and starts no process); it reads no credential and no `config.yml`
(service.py gives it its two directories, `components.owner_host` and the integration store's path); its environment, and its supervisor's, is the allowlist `ENVIRONMENT_NAMES` (Windows and
the interpreter's needs, nothing else); it has no dispatch endpoint.

## The lifecycle

```
<tools python> -I -B integrations/ownerhost/service.py up|down|restart|status|inspect|verify   # task ownerhost:<verb>
```

| Verb | What |
|---|---|
| `up` | Refuses `ALREADY_RUNNING` and `PORT_IN_USE` (never another port), then starts the managed environment through the platform adapter: a supervisor with no window that joins a new kill-on-close Job Object and starts the server process inside it (`app.py serve`), and waits until the server of its own launch listens (the TCP table), at most 30 s. Concurrent `up` commands are serialized by `launch.lock`; one instance is enforced by the supervisor's `instance.lock` (below) |
| `down` | Writes the stop request the server watches for (`<state>/owner-host/stop-request`), waits on both processes (at most 15 s), and terminates the supervisor only if they have not ended; the job then ends the server |
| `restart` | The contract's, under a write-ahead transition record (`<state>/owner-host/transitions/`). A restart whose stop or start raises or is refused (a held port, another `up`) closes its record as `failed` with the cause, so the next restart is not refused for it |
| `recover` | The contract's recovery, for a record left pending by a restart that was killed (the remedy `TRANSITION_PENDING` names): it reconciles the actual state, then finishes the restart. `restart` and `recover` hold `transition.lock`, so two never interleave |
| `status`, `inspect` | Report; change nothing |
| `verify` | The `aieh-readiness/1` record; exit 0 only when it passes: `supervisor_running`, `server_running`, `server_supervised`, `listener_on_declared_port`, `loopback_only`, `port_held_by_server` |

No `install`, `upgrade`, `uninstall` or credential verb: it runs from the checkout and is custodian of no credential.
Linux and macOS: `PLATFORM_UNSUPPORTED`.

One instance: the supervisor takes an exclusive OS lock on `<state>/owner-host/instance.lock` before it touches any
shared file and holds it for its whole life (the OS releases it when the supervisor ends, however it ends). A second
supervisor exits having started and written nothing, and its `up` is refused `ALREADY_RUNNING`. A server that exits
other than cleanly, killed included, is recorded as `failed` in `run.json`.

Data (decision 0009): `<state>/owner-host/` holds `conversation.sqlite`, `run.json` (`aieh-service-run/1`: the
supervisor and server processes, the job, the harness commit and tools lock digest, the configuration snapshot) and
`server.json` (the server's own record: process, address, port, whether its console has a window, and its live
import census at start and at stop); `<logs>/owner-host/` holds `supervisor.log`, `console.log` and `service.log`.
Each record is written whole (a `.partial` file, then `os.replace`). On Windows the replacement is refused while
another process has the record open, and a read is refused while a replacement runs: the writer and `service`'s
reader (`read_run_record`) retry for at most `SHARED_FILE_CEILING_S` (5 s), any other error at once (before, the
supervisor exited 1 when `up`'s poll held `run.json` open under load: dispatch 11's flake).

The supervisor is started by the platform adapter's `launch_supervisor` with the same environment allowlist as the
server, so neither holds what the starting environment holds beyond those names. It loads the Windows adapter, which
loads its credential-provider module only when a credential provider is asked for, never here: the supervisor's
import census (`supervisor_modules` in `run.json`, at start, running and stop) has nothing under
integrations/credentials, gitea, dispatch, inference or owner, and neither has the server's.

## Commands

```
<tools python> -I -B -m unittest discover -s integrations/ownerhost/tests -v   # task ownerhost:test
```

The listener tests start the real service on `127.0.0.1:13310` with a throwaway layout and stop it; they fail,
rather than skip, when the port is already held. `test_pending_decision.py` uses a free port of its own instead.

## Not yet verified

- The Owner's own enrollment and sign-in with his real credential (OA-32 (a)); a real browser against the service.
- U-02.1's and U-02.2's verdicts (built 2026-11-16; their tests PASS offline and against the real process with
  throwaway layouts).
- A pending decision asked by a real producer: no chat model is connected, so only the tests ask one.
- P-01.3's verdict (built 2026-11-16; its tests PASS offline with throwaway stores and repositories): no capture has
  been made in a real project repository, with the Owner's own configured identity, or from a real browser.
- U-04.1's verdict (built 2026-11-17; its tests PASS offline with throwaway stores, repositories and Backlog.md's
  recorded output): no projection of a real project repository, the live Backlog.md, a live attempt or a real
  browser; the coverage limit of archived tasks and the reuse of a deleted task's id are the pin's, not fixed.
- Linux and macOS (the platform contract's adapters, F-06.4 and F-06.5).
- Ending with the Owner's session or a reboot (the job's declared behaviour, as for Gitea).
