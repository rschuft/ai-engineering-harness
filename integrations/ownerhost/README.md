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
repository ([below](#capture-p-013)). Acceptance (P-04.4) and the projection (U-04.1) attach later. It has no dispatch
endpoint.

## Files

| Path | What |
|---|---|
| `app.py` | The ASGI application (`create_app`), its three request checks, the session route, the thread and history routes and the capture route; `bind_listener` and `serve`, the server process |
| `capture.py` | P-01.3: the request layout's parser, the intent record it writes, the project configuration (`components.owner_host`), the commit identity, the write-ahead receipt and the commit |
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
`lineage.py` and `tools/check_intent_record.py`): no credential, Gitea, authorization-recorder, dispatch or inference
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
- Linux and macOS (the platform contract's adapters, F-06.4 and F-06.5).
- Ending with the Owner's session or a reboot (the job's declared behaviour, as for Gitea).
