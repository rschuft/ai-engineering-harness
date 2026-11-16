# I1 integration design (2026-11-16): the architect's work design and the engineering manager's rulings

This is the design record of unit I1's architecture consultation. It holds the **architect's work design** for the
two questions the [I1 commitment](bootstrap-log.md#commitment-i1-2026-11-16) handed to execution, AQ1 (the
Integration process, its Owner login and `cred-owner-ui-session`, and the thread store) and AQ2 (the fixture
transport's admission, and Agent Canvas against a loopback fixture): an architecture consultation at **gates C and G**,
answered to the engineering manager on 2026-11-16. The **engineering manager's rulings** on it follow, in the
[last section](#engineering-managers-rulings-on-the-i1-architect-answer-2026-11-16).

- The answer is the architect's advisory text as delivered; the rulings say what was accepted and what was amended
  (draft 0025 point 4: the shell's copy of the credential in `localStorage`, not `sessionStorage`).
- Decisions [0025](../decisions/0025-integration-process-owner-ui-session-credential-and-owner-conversation-store.md)
  and [0026](../decisions/0026-declared-transport-authority-fixture-profile-and-agent-server-fixture.md) are drawn
  from section 4, both Proposed.
- The only edits to the two texts: machine and session paths are named generically ("session scratch",
  "the engineering manager's checkout"), and every heading is one level lower so that both fit under this title.
  Repository-relative paths are kept.
- Nothing in it is built or verified by being recorded here. What the slices build is recorded at their verdicts.

## Architect answer: unit I1, gates C and G (AQ1 and AQ2)

To the engineering manager. Reading taken: a **work design** for AQ1 and AQ2, needed to unblock U-01.3, U-02.1,
E-01.7, E-01.8 and their successors. Advisory: every ruling below is a recommendation that you accept or not; each
decision draft is Proposed. Nothing in the repository was edited.

Contents: 0 basis; 1 rulings; 2 planning blockers and confirmations; 3 slice plan; 4 decision drafts; 5 planned-record
corrections; 6 STOP gates; 7 upstream facts, verified and not; 8 residuals.

### 0. Basis

- **Baseline, observed:** this repository (the engineering manager's checkout), branch `main`, HEAD `2475356` = `origin/main`; no tracked
  file modified (`git status --untracked-files=no`; untracked files were never listed, so the root `config.yml` was
  neither read nor enumerated).
- **Read in this invocation:** the commitment and the Owner direction (`evidence/bootstrap-log.md`, anchors
  `commitment-i1-2026-11-16`, `owner-direction-i1-2026-11-16`, the OA-32 and OA-33 rows); decisions 0008, 0009, 0011,
  0012, 0013, 0018, 0020, 0024 whole, and the cited lines of 0003, 0015, 0016; the 14 leaves and 17 context leaves from
  the plan JSON; `policy/network-matrix.json` (all `owner_act` rows and every host-loopback row), `policy/README.md`
  (network matrix section), `security/inventory.json` (the entries the brief names, and the operations),
  `policy/role-tokens.json` (the Owner role's session entries); `integrations/dispatch` (README; `dispatch_inputs.py`
  admission, client, `dispatch`; `attempt_run.py`; `result_path.py`; `attempt_end.py`; the fakes in the tests);
  `integrations/lineage`, `integrations/owner` (README, `acceptance_recorder.py`), `integrations/store/README.md`,
  `integrations/platform/README.md`, `integrations/paths` categories, `tools/guest.py` host census,
  `tools/check_profile.py` header, `profiles/README.md`, `apps/owner-host`, `evidence/D1-run-2026-11-16.md`,
  `evidence/F-04.2-conversation-lifecycle.md` (the OpenAPI finding).
- **Pinned upstream, read:** the installed packages under `apps/owner-host/node_modules` (`@openhands/agent-canvas`
  1.36.0, `@openhands/typescript-client` 1.60.1, `@assistant-ui/react` 0.15.32, `@assistant-ui/core` 0.3.32: the
  versions of `composition/lock/components.lock.json`); and files of `openhands-agent-server` fetched from GitHub at
  the lock's commit `e99e5c71ffe440a0b8d74b695f9307a7e34e4bbd` (v1.60.1) into session scratch
  (nine fetched, seven read). Section 7 lists each fact and its file.
- **Not read, by instruction or by boundary:** the root `config.yml`, any credential store, the managed data root, any
  other repository, D1's raw records (session scratch of another session). The Control Plane Knowledge surface was not
  used: the brief's authorized paths are this repository and session scratch.
- **Vocabulary.** "Verified" means read in this invocation at the path named. "Inferred" is marked. A defect is
  classified `introduced-by`, `exposed-by` or `unrelated-but-detected`.

---

### 1. Rulings

#### AQ1

**R1. The Integration process is a Python ASGI service: Starlette on uvicorn, in a new package
`integrations/ownerhost/`, run under the tools interpreter.**

- Versions: the ones the component lock already pins with hashes for the Agent Server's own closure
  (`composition/lock/python/windows-x86_64.txt`, verified: `starlette==1.10.0`, `uvicorn==0.54.0`, `h11==0.16.0`,
  `anyio==4.16.0`, `click==8.5.0`, `websockets==16.1.1`). They are added to the tools set
  (`composition/lock/python/tools-requirements.in` and `.txt`), wheels only, hash-locked. This is the keyring
  precedent of decision 0011 ("already pinned").
- Reasons. Everything the process must do is an in-process call of an existing Python module:
  `acceptance_recorder.prepare/record`, `repository_access.Repository.write_commit`, `lineage_trace.trace`, the
  planning adapter, the integration store. U-01.3's adoption line asks for "an established server framework rather
  than a bespoke one". The fixture of AQ2 needs a WebSocket server and the pinned Agent Server is itself
  Starlette/uvicorn, so one stack serves both and gives the fixture the real server's framework behaviour (CORS,
  WebSocket close codes).
- Rejected.
  - *(b) a Node service beside the app.* Every recorder, lineage and store call would cross a process and language
    boundary or be written twice. assistant-ui's backend patterns serve a model backend; I1 has none.
  - *The standard library's `http.server`, as the inference broker uses.* Routing, CORS, Origin and Host checks and
    the WebSocket would be owned code: what the adoption line rules out.
  - *(c) the thread store in the browser.* The lineage resolvers and P-01.3's byte comparison run on the host; a
    browser store cannot be read by them, and clearing site data would delete Owner statements.

**R2. Lifecycle under decision 0011, data under decision 0009.**

- Lifecycle: the service verbs `up`, `down`, `restart`, `status`, `inspect`, `verify`, realized through the existing
  `integrations/platform` contract and its Windows adapter (the kill-on-close Job Object, the run record
  `aieh-service-run/1`, the readiness record `aieh-readiness/1`). No `install`, `upgrade` or `uninstall`: it runs from
  the checkout; the run record names the harness commit and the tools lock digest. No credential verb: it is custodian
  of no credential. Linux and macOS stay `PLATFORM_UNSUPPORTED`, as the contract answers today.
- Data: the `state` category, `<state>/owner-host/` (the conversation store, R5); the `logs` category,
  `<logs>/owner-host/`. Nothing in the checkout. Configuration under `components.owner_host` (the project repository
  path and id, the Backlog command); no key name may contain `token`, `key`, `secret`, `password` or `credential`
  (the loader's secret-shaped rule).
- One fixed loopback port, declared in one constant that the host census imports (suggested `127.0.0.1:13310`; the
  engineer confirms it is free). A busy port is a refusal, never another port: the census finds harness listeners by
  port (`HOST_CENSUS_PORTS`), because the process name is only `python`.
- **No unauthenticated route.** U-01.3's proof says "every request needs the Owner UI session credential". There is
  no open health route: readiness reads the kernel's TCP table by PID, and liveness is the stable refusal itself (a
  request without the credential answers 401 `SESSION_CREDENTIAL_MISSING`). The one exception is the CORS preflight
  (`OPTIONS`), which a browser cannot authenticate; it carries no data and refuses an origin outside the allowlist.
- **No outbound connection, and no path to an Agent Server.** The package opens no client socket (an AST census test,
  the pattern of `integrations/inference/tests/test_egress.py`) and imports no credential, Gitea, authorization-recorder
  or dispatch-transport module (an import census, the pattern of the input recorder's test). This is what keeps
  decision 0013 point 1 true by construction: the process is never a network path to the management API.

**R3. `cred-owner-ui-session` is one credential: a random secret the Owner mints himself, of which the store keeps
only a verifier.**

- Issuance: `enroll`, a command the Owner runs in his own terminal. It generates 32 random bytes, shows the credential
  once on the console, and writes a session record: `{sessionId (a public UUID), verifier, issuedAt, expiresAt,
  supersedes}`. `verifier` is the sha256 of a fixed domain line and the credential. One session is current; a new
  enrollment supersedes the earlier one. The validity is chosen at enrollment (suggested default 12 hours, ceiling 7
  days).
- **The Owner-act guard is mechanical.** `enroll` refuses unless standard input and standard output are console
  handles: `GetConsoleMode` on both, the check `integrations/inference/inference_broker.py` already makes ("a pipe, a
  file, the null device or a redirection fails"), not `isatty` alone. A tool shell's pipes are refused
  (`ENROLL_NOT_INTERACTIVE`), so no agent session can obtain the secret by running it. Tests call the library
  function with a throwaway data root; the Owner's own enrollment is OA-32 (a).
- Shape: `aieh-oui-` followed by 52 characters of lower-case base32. It is not an Agent Server key (43 URL-safe
  characters, no prefix), not `aieh-inf-...`, not `sk-ant-...`, not 40 hexadecimal digits. The shape goes into
  `policy/role-tokens.json`; a test presents each of those other shapes and expects a refusal.
- Refusals, each stable and changing nothing: `SESSION_CREDENTIAL_MISSING`, `SESSION_CREDENTIAL_FOREIGN` (not this
  shape, or matching no issued verifier), `SESSION_CREDENTIAL_EXPIRED` (matches a verifier past its expiry: the record
  is kept so that expired and foreign stay distinguishable), `SESSION_CREDENTIAL_REVOKED` (superseded or revoked).
- "The process holds only a verifier": the record is all it reads. The credential passes through its memory on each
  request and is never stored, logged or echoed. The proof scans the process environment, its configuration snapshot
  and its log files for the throwaway credential and for every credential shape of the inventory.
- Rejected.
  - *OS credential manager delivery.* Any process of the Owner's account reads the entry without a prompt
    (`fd-bootstrap-shared-identity`), a browser cannot read it, and the Owner would still need it printed or on the
    clipboard. It would put the secret at rest where every host agent can read it.
  - *A login secret plus a session token the service issues.* Two credentials: the second is a new credential class
    (decision 0018 point 4.7), and the service would mint and momentarily hold it, against "never the credential
    itself".
  - *A code the service prints at start.* The session that starts the service would see it: not "issued only by an
    Owner act".
  - *Passkeys.* The right later form (the server would hold only a public key), but too large for I1: a WebAuthn
    relying-party id cannot be an IP literal, and it needs new dependencies. Not proposed here.

**R4. The login is one verified request; the credential travels in a header, never in a cookie.**

- A cookie is scoped by host, not by port. Every harness listener is on `127.0.0.1` (Gitea on 13300 renders
  bot-authored text), so a cookie would be sent to all of them, and any page on any loopback port is same-site with
  the service. A header is not ambient: another origin cannot send it without a preflight the service refuses.
- Flow: the shell's login view takes the credential; `POST /session` verifies it and answers the session id and the
  expiry; the shell keeps the credential in `sessionStorage` of its own origin (web storage is per origin, port
  included) and sends it on every request in `X-AIEH-Owner-Session`. The service keeps no session table, so a restart
  of the service loses nothing (U-06.1 item 7). After the browser is closed, the Owner enters the credential again.
- Request rules: `Host` must be the literal `127.0.0.1:<port>` (`HOST_NOT_ALLOWED`: DNS rebinding); `Origin`, when
  present, must be one of the shell's two origins, `http://127.0.0.1:4173` and `http://127.0.0.1:5173`
  (`ORIGIN_NOT_ALLOWED`); CORS answers only those origins and never allows credentials mode.
- Consequence for the UI (see R14): a script running in the shell's origin would hold the session's authority. So
  Agent Canvas, which renders agent-authored text, must not share that origin, and the shell gets a
  content-security policy (`connect-src` the service; `frame-src` the Canvas origin; no remote source).

**R5. The Owner conversation store is host-side SQLite of its own store kind, behind assistant-ui's own adapters.**

- A new store, `<state>/owner-host/conversation.sqlite`, built on `integrations/storecore` (WAL, `synchronous=FULL`,
  STRICT tables, a migration ledger, its own `application_id`). **Not** tables in `integration.sqlite`: that store
  "is not a record of authority" (`integrations/store/README.md`), while the Owner conversation store is the lineage
  authority for the `conversation` and `message` kinds (`integrations/lineage/README.md`). Package
  `integrations/conversation/`. Its only writers are the Integration process and `enroll` (the session table).
- The browser side is what blueprint UI-02 adopts: `useLocalRuntime` with a `ThreadHistoryAdapter`, under
  `useRemoteThreadListRuntime` with a `RemoteThreadListAdapter`, both thin HTTP adapters (verified exports and types,
  section 7).
- Canonical identity.
  - **Thread id:** minted by the store at `initialize`, a UUID, returned as `remoteId`; idempotent for the same
    session and local id.
  - **Message id:** assistant-ui's native id, as `append` sends it. Verified: it is seven characters from
    `nanoid/non-secure`, generated in the browser, and `append` returns nothing, so the store cannot assign another.
    The store accepts it in a strict grammar and makes it unique per thread: the same id with the same content digest
    is a repeat and succeeds; the same id with other content is `MESSAGE_ID_CONFLICT`. The lineage reference is
    `conversation:<thread>/<message>`.
  - **Order:** a per-thread `seq` the store assigns at the first append. `parent_id` is kept as sent. `load()`
    returns messages in `seq` order.
  - **Edits:** in assistant-ui an edit is a new message under the same parent. Both are kept. A user message is
    immutable: an `update` that would change its bytes is `MESSAGE_IMMUTABLE`. `update` is an upsert only for
    assistant messages (the pending tool state of U-02.2; the adapter's own contract: "treat it as an upsert keyed on
    the message id"). The message `delete` is not implemented (it is optional in the adapter); a thread `delete` is
    refused; `archive` works.
  - **Content, the durable source of D2:** an Owner statement is a user message with exactly one text part. The store
    keeps that text's UTF-8 bytes as a BLOB exactly as received (no normalization, no trimming) and their sha256. A
    text that cannot be encoded (a lone surrogate) or holds a NUL is refused. Every quote and span anchor is cut from
    this BLOB with `lineage.span_reference`; nothing is ever taken from text a client supplies later.
  - **Attribution:** each row carries its role, its author (`owner` for a user message appended under an authenticated
    session; `owner-host` for an assistant message) and the session id. Assistant rows are display state the browser
    wrote; no resolver or recorder treats one as a statement.
- Lineage: one read-only resolver for `message` and `conversation` (`storecore.open_read_only`, `query_only`,
  `check_current`, as `ReadOnlyIntegrationStore` does), applying `check_message_content` unchanged. Consequence you
  should expect: when a kind becomes `implemented` in `lineage_schema.json`, `Authorities` no longer admits a sample
  for it (its rule is schema status `authority-unavailable`), so the statement sample and the two committed example
  projections change at U-02.2, and the attempt sample at E-01.5. That is the planned end of the samples
  (`integrations/lineage/README.md`, "Not yet verified"), not a regression; P-03.2's proof text is untouched.

**R6. How P-01.3, P-04.4 and U-04.1 attach, without moving a boundary of 0013 or 0012.**

- **P-01.3 (capture).** The request names a thread and a message and carries the sha256 the browser computed; the
  service compares it with the stored bytes (`CAPTURE_MESSAGE_MISMATCH`, nothing changed). It then writes a
  write-ahead receipt in the integration store, `owner-ui/intent-capture/v1/<thread>/<message>`, and one commit
  through `repository_access.Repository.write_commit` (head compare-and-swap) that only adds
  `openspec/changes/<change>/`. A second request for the same message returns the first commit; an existing change id
  is `CAPTURE_CHANGE_EXISTS`; a lost outcome is settled by reading the repository, never by writing again.
  - Without a model, the structure must come from the Owner: the composer offers a labelled form (change name,
    objective, acceptance criteria, an optional method marked "suggestion") that is sent as **one** message in a fixed
    layout. The capture parses that layout only. Q1 is the whole message with its span anchor; each Owner-stated item
    is an exact byte span of the message, `attributed_to: owner`, `source: Q1`; a marked suggestion becomes a Proposed
    Method with `claim_type: hypothesis` and its Hypothesis item.
  - `normalized_by` cannot be `owner` (`tools/check_intent_record.py` refuses it) and the grammar has only
    `agent:<id>` and `person:<id>`. Use the capture component's id (`agent:owner-host-capture@<version>`) and attribute
    to it only the generated connective text (the Hypothesis sentence). The record then says truthfully who wrote the
    Markdown; "no model is called" is proved separately.
- **P-04.4 (acceptance).** `prepare` runs in process; the service keeps the challenge by nonce with the thread, the
  card message and the session id. The Owner's acceptance is a **user message** of the same session, after the card
  (the recorder refuses the request itself as the acceptance, and an assistant message cannot be a statement). The
  service builds the statement from its store, never from the request: `text` the stored bytes, `attributedTo: owner`,
  `channel: owner-ui`, `reference: conversation:<thread>/<message>#sha256:<digest>`, `recordedBy: owner`.
  - The recorder gains one rule: channel `owner-ui` is admitted only with a session-binding verifier passed in
    process, which checks that the message exists, is a user message authored under the session making the request,
    has that digest, and that the challenge was issued to that session. Without the verifier `owner-ui` is refused
    (`SESSION_BINDING_REQUIRED`), so the command line cannot declare it: that is "bound to the authenticated session
    rather than declared by a transcriber". Verified: no existing test uses `owner-ui`, and the acceptance recorder
    has no channel list today, so no P-04.1 or E-05.12 assertion changes.
  - Decision 0012's boundary stands: the authorization recorder and the dispatch-input commands keep
    `ADMITTED_CHANNELS = ('main-session',)`; the service imports neither; it reads no credential.
- **U-04.1 (projection).** Read-only: the lineage traversal over the project repository, Backlog.md's two read
  commands, the conversation store and the integration store opened read-only; the result receipt joined by
  reference. **The execution state comes from the dispatcher's receipts, not from the Agent Server**: the attempt's
  state, the turn journal, the launch receipt (R11), the delivery, pull and intake receipts, the result journal and
  receipt, the end and stop records. The service never asks an Agent Server, real or fixture: that call is the
  dispatcher's (decision 0013 point 1). The attempt authority is asked on the dispatcher side (E-01.5's resolver) and
  in U-06.1's run record.
- **No dispatch endpoint in I1.** The dispatch is run by the execution session's command, as at D1.

**R7. A new host-loopback listener of the Owner's account needs the matrix and inventory records before it first
listens, not a recorded Owner approval, while four conditions hold.**

Governing text:

1. Decision 0013 point 4: "Every such forward is a new host port. It is opened only after a recorded Owner approval
   (`op-guest-boundary-change`)". "Such forward" is point 3's "dispatcher-owned local forward ... pointing at the
   conversation's published guest-loopback port". Point 5, which defines the UI's credential to the Integration
   process, sets no approval. Point 6: host-internal edges "are separated by credential entry and code path, and are
   disclosed rather than prevented", and the enforced boundaries are host to guest, guest to containers, and Gitea's
   permission model.
2. `security/inventory.json`, `op-guest-boundary-change`: "Any guest network, guestfwd, host share, LLM credential,
   new host port or launch.argv change", named "Widen the guest boundary", over the guest assets. No operation
   reserves a host-internal loopback listener.
3. `policy/network-matrix.json`: `nm-owner-ui-integration` is recorded `owner_act: false` (accepted with decision
   0013). Verified over all rows: each of the thirteen `owner_act: true` rows crosses the guest boundary, leaves the
   host, or is `nm-owner-gitea` (the Owner's own placement decision, "Gitea on host loopback"); every other
   host-internal row is `false`, including `nm-owner-ui-shell` (observed since U-01.1 with no Owner act),
   `nm-gitea-internal`, `nm-gitea-webhooks` and `nm-management-internal`. The checker's only Owner-act rule is that an
   observed one cites its approval.
4. Decision 0018 point 4.7 reserves a change that "widens what an Owner-approved policy actually permits" and says
   "Recording a planned edge, a narrowing or a correction is not a widening". The Integration process realizes a
   planned edge and a planned credential. The fixture rows name paths between processes of one account, which the
   accepted records already disclose as reachable (`nm-owner-same-account`, `nm-owner-management-same-account`,
   `nm-management-internal`); they give no principal a reach to a protected asset it lacked.

Conditions. If any stops holding, it is an Owner act and a STOP: (a) the listener binds `127.0.0.1` only, on a fixed
declared port the census reads; (b) no forward, `hostfwd`, `guestfwd` or profile endpoint targets it; (c) its process
makes no outbound connection; (d) it holds no credential of a recorded class (the Integration process: a verifier
only).

Two precedents read the other way and do not govern here: the broker's two listeners (OA-12 item A2) and the CI
filtering proxy (decision 0016, A-4, "a host listener; the 0015 precedent"). Both are the host end of a path a guest
reaches, and the broker holds a provider key. `policy/README.md` says an Owner act marks "a new host port, a
guestfwd, a host listener"; its own generated table shows a host listener with "no", so the sentence describes the
marked rows and is not a rule. I recommend recording this reading in draft 0025 point 7 and reporting the three new
listeners to the Owner in the next report, as U-01.1's were reported, without asking.

#### AQ2

**R8. The authority mode is declared by the profile, bound by digest at reservation, enforced at the one client, and
required of every seam.**

1. Vocabulary: `live` and `fixture`.
2. Declaration: the profile's pinned route allowlist (`agent-server/routes.json`) gains an optional top-level
   `transport` object, `{"authority": "fixture", "kind": "loopback-fixture"}`. Absent means `live`. The profile
   repeats it at `provisioning.agent_server.transport`; `admit`, which reads both files, and `tools/check_profile.py`
   refuse a profile whose two declarations differ. The allowlist's sha256 is already in
   `policy_inputs.admission.routes`, so it is in the policy
   digest and in the reserved attempt identity. **No format changes**: `RESOLVED_FORMAT`, `POLICY_FORMAT`, the golden
   policy digest, the manifest schema, and the native profile's bytes and digest stay as they are (verified: neither
   `_check_route_allowlist` nor `AgentServerClient` closes the allowlist's top-level keys).
3. Seams declare their authority. `GuestTransport.authority = 'live'`; the fixture transport, `'fixture'`. A seam
   without the attribute is `live`, so every existing fake and suite is unchanged.
4. Enforcement: `AgentServerClient.__init__` compares the allowlist's declared authority with the transport's.
   Unequal is `TRANSPORT_AUTHORITY_MISMATCH` (context: declared, presented) with zero transport calls. Verified:
   every Agent Server call of the path builds that client from the attempt's pinned allowlist (`send_create`, and
   `attempt_end._client` for the attempt run, the end and the reads), so the two refusals E-01.8 asks for hold on
   every call, and one equality over declared values gives both directions.
5. The same equality at the other seams, with the attempt's bound authority (`attempt_authority(resolved,
   read_artifact)`, read from the pinned allowlist): the credential provider handed to `dispatch` and to
   `attempt_role_token` (`CREDENTIAL_AUTHORITY_MISMATCH`), the Gitea target of `publish_result`
   (`RESULT_TARGET_AUTHORITY_MISMATCH`), and the `inspect` and `pull` callables of `run_attempt`
   (`OBSERVER_AUTHORITY_MISMATCH`). So a fixture attempt cannot read the host credential provider or push to the
   managed Gitea, and a live attempt cannot take a fixture's token, inspect or result.
6. The fixture transport can reach only a fixture: its target is the literal `127.0.0.1` and the fixture's fixed
   port, and it refuses any answer without the fixture's label (`FIXTURE_LABEL_MISSING`). Pointed at a real server by
   mistake it stops at the first answer, `GET /server_info`, which is public and precedes the create.
7. This is not a "fixture-only branch": the dispatch modules compare declared values and never test for `fixture`.
   Falsifier: a census test that the string `fixture` appears in `dispatch_inputs.py`, `attempt_run.py`,
   `attempt_end.py` and `result_path.py` only in the authority vocabulary and those refusals' texts, and that none of
   them imports the fixture package.

On your options: (a) is right with two corrections. The kind is declared by the profile's pinned allowlist, not by the
manifest binding (the manifest schema is closed, and decision 0020 rejected a schema v2); and a registry keyed by
`transport.kind` belongs in the composition root that builds the seams, outside `dispatch`, with the client's equality
as the control. (b) is rejected: a URL is not bound to the attempt identity, and a forward changes it. Also rejected: a
driver flag (the admission design admits no caller-supplied value) and a new key in policy-inputs/v2 or
resolved-inputs/v2 (it moves the golden digest and the reader of stored reservations).

**R9. The fixture profile is a declared class of profile that is not an execution profile.**

- One checked-in profile, id beginning `fixture-` (suggested `fixture-d1-replay`); `tools/check_profile.py` requires
  that prefix exactly when the declared authority is `fixture`.
- It holds only what resolution and admission read: `schema`, `name`, `status`, `ceilings`,
  `provisioning.agent_server` (`version`, `config.content`, `fixture`, `stage_create_template`, `conversations`,
  `admission.routes`, `transport`), the one `network.endpoints` entry the native stage's admission reads, and `replays`
  (the profile and digest whose recorded observations it replays, with the evidence). Its admission-relevant values
  are those of the profile D1 ran (digest `b7c5d2fe...d9c7`), so the recorded inspect matches the admitted caps,
  image and mounts with the gate's logic unchanged. It has no provider, boot input, launch, state directory or
  lifecycle section, and the checker refuses one in it, so it cannot be launched.
- `status.operational: true` means, for a fixture profile only, that its conformance suite passed at the pinned
  answers (E-01.7's evidence). Contract C6, which binds the strong-security profile, is unchanged; the fixture profile
  claims none of the properties P1 to P12 and no tier.
- The contract (`profiles/README.md`, `profiles/properties.json`) gains a short section saying so. The checker's
  fixture path is a branch in the checker, which is outside E-01.7's "production dispatcher and Agent Canvas code
  paths".
- A binding of its own: OA-33's manifest names the profile by digest, and a catalog pin whose assignment names the
  profile's own create template (a byte copy of `d1-create.json`, since a template path must lie under its own
  profile's directory).

**R10. The fixture attempt is an attempt of the native execution kind, with a synthetic token from a fixture
credential provider. The unchanged result path leaves no other way.**

- Verified: `publish_result` runs `outbound_search(native, expected_fingerprint=AE.native_fingerprint(...))`, which
  refuses `OUTBOUND_SEARCH_REQUIRED` when no native token is held, and the fingerprint is the one the dispatch
  recorded. Decision 0024 point 8 states this gate, and your non-goals keep 0024 closed. An attempt with no token
  cannot be published by the result path as built.
- So the fixture profile declares `execution_profile: native` for its stage and replays D1's create, and the fixture
  binding supplies a credential provider whose one entry holds a token derived from a public seed (the pattern of
  `tests/native_support.token`, which E-05.4's and E-05.9's suites use today). The provider declares authority
  `fixture` (R8 point 5). The host credential provider is never constructed on the fixture path: the composition root
  imports no credential module (import census).
- This reading needs planning's confirmation: see PB-3.

**R11. Labels are copies of the bound declaration; readers trust the binding, not the label.**

- Writers add `authority` to a record only when the attempt's bound authority is not `live`: the `dispatched` and
  `confirmed` transition details (which already carry optional keys such as `nativeToken`), the launch receipt, the
  result journal's receipt (`result-receipt/v1`), the Owner report and the pull request body. A native record is byte
  for byte what it is today, so "the native admission's and E-05.4's suites are unchanged" can hold. This is E-01.8's
  "fixture record format": an optional key, no new format.
- Readers (the lineage attempt resolver, U-04.1's projection) compute the authority from the reservation's pinned
  allowlist and require every label to agree. A fixture-bound attempt whose record lacks the label, or a label on a
  live-bound attempt, is `unknown` with a stable code, shown as neither.
- Lineage: `authority_mode` gains `fixture`. A node a fixture answered carries a label beginning `FIXTURE` and adds a
  `fixture-authority` uncertainty (`FIXTURE_AUTHORITY`), exactly as a sample does, so a projection that used a fixture
  is never `complete`. The mode is taken per attempt from its bound declaration and the answering transport, never
  from a caller's flag; a mismatch answers `authority-unavailable` (`ATTEMPT_AUTHORITY_MISMATCH`). See PB-5 for what
  this means for U-06.1 item 8.
- E-01.5's gate writes a launch receipt, `dispatch/attempt/<attempt id>/launch`: the verdict (`launched` or
  `not-launched`), each compared field with the admitted or limit value and the observed one, the inspect document's
  digest and its source. It is implemented as the `inspect` callable `run_attempt` already takes, so `run_attempt`
  does not change: a mismatch or an inspect that cannot be obtained returns problems, and the existing path ends the
  attempt (`INSPECTION_FAILED`).

**R12. The fixture: one deterministic core, served on one loopback listener with two faces; it never executes
anything.**

- **It never executes what it receives.** The tests' fake runs SEED and RESULT in a real shell; a listener must not
  (any local process could post a command, and RESULT runs the repository's tests on the host). The served core
  recognizes a command only when its script text is byte for byte the pinned `SEED_SCRIPT` or `RESULT_SCRIPT`, decodes
  its hex parameters, and builds the answer.
- **RESULT is built, not replayed.** The intake recomputes the commit from this attempt's base, message and time
  (decision 0024 point 5.3), so D1's commit can never be the answer. The core takes the base bundle and the commit
  parameters from the command, applies D1's recorded file changes (three files, from the committed Owner report in
  `evidence/D1-run-2026-11-16.md`), writes the commit and its bundle in process with the repository-access module
  (the tests' `verified()` helper already does exactly this), and reports D1's recorded test output. A test with a
  real shell shows the built commit id equals the real RESULT script's on the same inputs.
- **Scenarios advance by call count**, never by a timer or a control route (a control route would not be an Agent
  Server route). The scenario is chosen when the process starts. "Running" lasts a fixed number of status reads (D1
  recorded seven over about a minute), which is the window U-06.1 item 7 needs.
- **Outside the catalog it refuses**: HTTP 501 with the fixture's label and `FIXTURE_NO_OBSERVATION`. It never invents
  an answer.
- **Label:** a response header on every HTTP answer and on the WebSocket handshake, and, where the schema has room,
  in the data the UI shows (the conversation's title and tags).
- **Two faces on one port** (suggested `127.0.0.1:13320`).
  - The dispatcher's face: the outer, Docker-mode routes the dispatcher's allowlist uses.
  - The UI's face, under a path prefix: a conversation's own server as a client holding the runtime credential sees
    it. It is read-only: a `POST`, and an inbound message on the socket, are refused (verified: Canvas can send a user
    message both ways, and the real socket would run it).
  - Access values are public labelled constants, one per face; the UI value is refused on the dispatcher's face and
    accepted on the UI's, as E-01.3.3 step (4) observed live.
- CORS as the pinned server does it (verified: an origin whose host is `localhost` or `127.0.0.1` is always allowed).
- A call log, appended to a file outside the checkout, is the evidence for "exactly one create and one initial
  message".

**R13. Promotion: one catalog of cited answers, one core, used in process by the offline leaves and served by
E-01.7.**

- New package `integrations/agentfixture/`:
  - `observations.json`: every answer, with its route, scenario state, status and body template, each field's
    provenance (recorded, echoed from the request, derived by a pinned rule, or the label) and its citation;
  - `core.py`: the state machine, callable as a transport (`core(method, path, body)`), with its call log. It is
    `FakeAgentServer`, `ConversationServer` and `RunServer` moved and merged, answering from the catalog;
  - `result.py`: R12's SEED and RESULT answers;
  - `backend.py`: the other seams, each promoted from a test: the exchange delivery (`deliver`), the pull over the
    retained verifier (`Puller`), E-05.4's fake Gitea (`DemoRemote`, `DemoGitea`, `FakeGitea`), the fixture credential
    provider, the recorded inspect source;
  - `server.py` (E-01.7): the Starlette application over the core; `transport.py`: the fixture transport.
- The existing test modules import these and keep test-only knobs (dropped answers, the real-shell oracle) as
  subclasses. The engineer shows that no test id and no assertion changed, only imports.
- E-01.4.1 needs no promotion (its proof asks for no citation). E-01.4.2 does the promotion, because its proof needs
  "each fake answer cites its F-04.2 observation"; E-01.5 adds the inspect documents; E-01.7 adds the listener and the
  UI face. One catalog, so no leaf has a second fake.
- **What a "recorded observation" can be.** Verified: the repository holds no raw payload of a live run. D1's raw
  records are "session scratch, not in the repository"; the committed observations are rows of evidence (statuses,
  counts, field values), the diff and the test output. An answer is therefore assembled field by field, and the
  provenance table is the proof. See PB-2.

**R14. Agent Canvas, as pinned, can run against a loopback fixture, but only as its standalone application on its own
origin, and not yet under E-01.7's proof as written.**

Verified at the pin (files in section 7):

1. The embedded library cannot be given a session: `useConversationId` reads Canvas's internal navigation context;
   the library's JavaScript exports only `useNavigation`, and the providers take no conversation or navigation
   property. U-01.1's finding stands.
2. The package ships the standalone application (`build/`, whose route manifest has
   `conversations/:conversationId`) and upstream's own server for it, `scripts/static-server.mjs`: static files plus a
   reverse proxy for `/api`, `/sockets` and `/server_info`, loopback by default, with the session key injected into
   the page, and `--disable-telemetry`.
3. Canvas authenticates a local backend with `X-Session-API-Key`, derives the conversation's URL from the backend
   host, and opens `/sockets/session/<conversation id>?after_seq=<n>` with first-frame authentication. The pinned
   server's session socket answers one `sync` frame and then `durable` frames for every event after the cursor.
4. **Canvas never calls the runtime-credential route**: the string `runtime/credentials` occurs nowhere in the
   Canvas `dist/` or in the pinned TypeScript client. The dispatcher's allowlist marks the route `not-used`.
5. The WebSocket routes are in no OpenAPI document (`routes.json`: `source: binary`), and the locked release
   `openapi.json` documents the local runtime only (F-04.2 finding 1; consistent with the pinned client's generated
   schema, which has no `runtime/credentials` and one operation on `.../runtime`).

Ruling for U-01.2: the UI-01 fallback is the standalone application served by upstream's `static-server.mjs` on its
own loopback port (suggested `127.0.0.1:13330`), proxying to the fixture's UI face, shown in the engineering area in
a frame whose address carries the selection (so a refresh keeps it). A separate origin is required, not a
convenience (R4): Canvas renders agent-authored text. Two things must be shown in a real browser before this is
built on: no request leaves loopback with telemetry disabled and Canvas's two remote font imports removed from a
derived copy of `build/` (the U-01.1 ruling, applied to the standalone build); and which requests the conversation
page needs in order to render (not established by reading; section 6, gate G5).

Why "not yet under the proof as written": PB-1 and PB-2.

**R15. Session access in I1.** Decision 0013 point 2 has the dispatcher issue a conversation's runtime credential
per Owner session; that mechanism and its forward are U-03.1's, which is outside I1, and the Integration process may
not call the route itself (R2). In I1 the engineering view receives, from the projection's "session detail" source
action, the Canvas address for the attempt's conversation; the access value is the fixture's public labelled
constant, held by the Canvas server's configuration, and the action is refused for an attempt whose bound authority
is not `fixture` (`SESSION_ACCESS_UNAVAILABLE`: the live path is U-03.1's). The fixture serves the runtime-credential
route (shape from the pinned source, cited to E-01.3.3 step (4)) so that U-03.1 can be built against it; no I1
component calls it. See PB-6.

---

### 2. Planning blockers and confirmations

Decision 0018 point 4.7 and the commitment: anything that changes a criterion, another leaf's contract or an
Owner-approved policy goes to planning. I designed around none of these. Each is recorded for the leaf named.

| Id | Leaf | What | Class | Needed from planning |
|---|---|---|---|---|
| **PB-1** | E-01.7 | The proof clause "Every route served is in the locked OpenAPI and each response validates against its schema" cannot be met as written. The locked release `openapi.json` documents the local runtime only (F-04.2 finding 1), while the dispatcher must call Docker-runtime routes it lacks (`DELETE .../runtime`, the conversation proxy); and WebSocket routes are in no OpenAPI document. | A mis-specified proof clause, `introduced-by` the plan amendment of 2026-11-16 (I1), `exposed-by` this consultation. **Blocker for E-01.7's verdict.** | An amendment that keeps the obligation: every route served is in the profile's pinned route inventory (`routes.json` at its digest); each response validates against the locked document where that document defines its schema; elsewhere the answer's shape is its cited observation's or the pinned source's, named as such. |
| **PB-2** | E-01.7, U-01.2 | "Every answer is taken from a recorded observation ... an answer without one is a failure." (a) No raw payload is committed, so answers can only be assembled field by field from evidence rows, request echoes and pinned rules. (b) I found no committed observation of the UI's vantage beyond one status pair (E-01.3.3 step (4): the inner server answered 200 with the runtime credential and 401 without): none of its `/server_info`, its conversation record, its events or an authenticated session-socket stream. D1 recorded the events' kinds and counts, not their bodies. Canvas's client reads `/server_info` from its backend for conversation-scoped requests and throws on any error but 404 (verified); whether the conversation view renders without it is gate G5. (c) No committed live observation of a failed turn exists (E-05.8's surfaces are source-read: "Unknown, all live"), so the "failed" scenario can cite only a refused create (S-01.3.1's 401), not an `error` turn. | Same classification as PB-1. **Blocker for the UI face and so for U-01.2**; (a) is a reading to confirm. | Either admit, for the UI face and the failed scenario, answers derived from the pinned source and the locked document, each marked "source-derived, not observed" in the provenance table (my recommendation: it keeps I1 offline, as the Owner directed, and says what it is); or record the missing observations in a guest (a live act with its Owner approvals, outside I1's conditions); or commit D1's raw event log as evidence if it still exists (an execution act through the publication gate). Without one of these the Canvas view can show a title, a status and the attempt's own message, and may not load at all. |
| **PB-3** | E-01.8; the commitment | "The fixture path reads no credential entry" and the commitment's "the native profile is not used". The unchanged result path publishes only an attempt whose create held a native token (R10). | A reading to confirm. **Blocker for E-01.8 if refused.** | Confirm: "no credential entry" means no entry of the host credential provider; the fixture profile replays the native execution kind with a token derived from a public seed, supplied by a fixture provider. If refused, E-01.8 needs a change to decision 0024 point 8's gate, which is yours and the product manager's to reopen, not mine to design around. |
| **PB-4** | E-01.7 | The action says the finished result's "commit" is taken from the D1 run record. It cannot be: the intake recomputes the commit over this attempt's base, message and time. | A wording correction of the action, not of the proof. | Record on the leaf: the commit is built by decision 0024 point 4.4's rule over D1's recorded file changes; D1's commit id is the citation only. |
| **PB-5** | U-06.1 item 8 | "Lineage from the message to the result resolves, each node's authority mode stated." With the sample pattern E-01.7 adopts, a projection a fixture answered is `incomplete` by design. | A reading to fix before the run (the decision rule precedes the observation). | Confirm: item 8 passes when every node's resolution is `resolved`, every mode is stated, and the only uncertainties are `fixture-authority` on the nodes the fixture answered. |
| **PB-6** | E-01.7, U-01.2 | The action lists the runtime-credential route among "the routes the dispatcher and the pinned Agent Canvas call". At the pins neither calls it. | A premise corrected by evidence; no criterion changes. | Note on the leaf: served for U-03.1; called by no I1 component; I1's session access is R15's. |
| **PB-7** | E-01.8, U-06.1; OA-33 | The unchanged result path admits one repository id, `aieh-d1-demo` (`ADMITTED_REPOSITORIES`; the suite patches it for its own id). | A constraint on OA-33's presentation. | I1's project repository must carry that id (the demo's local clone or a copy), or planning accepts a change to the result path's admitted set. |
| **PB-8** | OA-32 (b); U-06.1 | Two things the Owner should know before his request: it is entered through a labelled form (R6), and the delivered diff and test output are D1's recorded ones whatever he asks for, labelled fixture. | Information for the presentation. | Say so in OA-32's presentation; planning may suggest a request the recorded result fits. |
| **PB-9** | E-01.8 | The execution-profile contract gains a fixture profile class (R9). No Owner condition C1 to C7 and no property changes; no guest profile is relaxed. | My reading: yours to accept as the contract's owner (the precedent of decision 0015's P7 amendment), inside committed scope, since the plan already makes "the fixture profile" E-01.8's artifact. | None, unless you judge it a change to the contract between leaves; then it is the product manager's (decision 0018 point 1). |

Not a planning matter, for your report to the Owner: the three new loopback listeners (R7), and the ASGI stack added
to the tools set (R1).

---

### 3. Slice plan

One bounded slice per engineer dispatch, in an order that respects every dependency. The two chains interleave
freely; where you reorder, keep each chain's own order. "Records first" means the commit that writes them precedes any
process that listens. Listener tests are `integration` category (the budget tool fails a `unit` class that opens a
socket).

**Raise PB-1, PB-2 and PB-3 to planning now.** Slices 1 to 8 do not depend on the answers.

#### Slice 1: U-01.3 (a) records, decisions and the server stack
- Purpose: everything that must exist before the Integration process listens.
- Files: `decisions/0025-...md` and `decisions/0026-...md` (Proposed, section 4);
  `composition/lock/python/tools-requirements.in` and `.txt`; `policy/network-matrix.json` and `policy/README.md`
  (generated block); `security/inventory.json` and `security/README.md`; `policy/role-tokens.json`;
  `tools/guest.py` (`HOST_CENSUS_PORTS`); `docs/development.md`; `example_config.yml`.
- Records: section 5, rows C1 to C3 and N1 to N3.
- Proof: `task policy:network-check`, the security-inventory and role-token checkers PASS; the README's generated
  tables equal `--render`; `tools:install` resolves the new wheels with hashes.
- STOP: a wheel that is not available wheels-only for this host and interpreter (no sdist exception is proposed).

#### Slice 2: U-01.3 (b) the Integration process and the session credential. **Fresh review.**
- Purpose: the service, its login and `cred-owner-ui-session` (R1 to R4).
- Files: `integrations/ownerhost/` (`app.py`, `session.py`, `enroll.py`, `service.py` for the lifecycle verbs,
  `README.md`, `tests/`); `integrations/conversation/` (the store kind, migration 0001: store identity and the session
  table); `apps/owner-host/src/identity/` (the login view, the header, `sessionStorage`), the shell's
  content-security policy; `Taskfile.yml`; `AGENTS.md` and `docs/development.md` (the two new suites).
- Proof clauses of U-01.3, each with its falsifier:
  - binds `127.0.0.1` only: the host census by port, and the readiness record's listener table by PID;
  - every request needs the credential: a test walks the application's route table and requires
    `SESSION_CREDENTIAL_MISSING` on each without it; the preflight exception is asserted to carry no data;
  - not shaped like an Agent Server key: each other credential shape of the inventory is refused;
  - missing, foreign and expired each refused with its code "and changing nothing": the store's canonical dump and the
    project repository's head are equal before and after;
  - nothing in environment, configuration or logs: a scan for the throwaway credential and every credential shape;
  - plus the two structural tests of R2 (no client socket; the import census) and the console guard of R3.
- STOP: a route that must answer without the credential; any need for an outbound connection; any credential the
  service would have to read.

#### Slice 3: E-01.4.1 reconcile a lost create acknowledgement
- Files: `integrations/dispatch/reconcile.py` (or in `attempt_end.py`), tests beside the existing ones. It uses the
  existing fakes as they are.
- Design: the oracle for `IntegrationStore.reconcile` answers only for keys of the typed attempt namespace: it reads
  `GET /api/conversations/{reserved id}` through the checked client; 200 with the id is `performed`, 404 is
  `not_performed`, anything else or no answer is `indeterminate`. Every other key is `indeterminate` without a call.
- Proof: no create is sent while an attempt is `unknown`; with a recorder receipt (`owner-authorization/v1/...`,
  `dispatch-inputs/v1/...`) present after a restore epoch, that receipt is not settled and the transport saw no call
  for it.

#### Slice 4: U-02.1 threads and messages. **Review recommended (the store is an authority).**
- Files: `integrations/conversation/` (migration 0002: threads, messages, the append-only triggers);
  `integrations/ownerhost/` (the thread and history endpoints); `apps/owner-host/src/areas/` (the two adapters, the
  runtime composition).
- STOP gate first (G2): the pinned runtime's behaviour, in a jsdom test with no network.
- Proof: a reload returns the same messages, ids, parents and bytes in `seq` order; a repeated `append` adds nothing;
  a conflicting id, a changed user message and a thread delete are each refused with their code; a quote cut with
  `lineage.span_reference` verifies with `check_message_content`, and a source whose byte changed fails
  (`SPAN_DIGEST_MISMATCH`).

#### Slice 5: E-01.4.2 the cited core and the restart matrix
- Files: `integrations/agentfixture/` (`observations.json`, `core.py`, `README.md` with the provenance table);
  the three test modules that held the fakes now import them.
- Proof: across a lost create answer and a dispatcher restart before the create, after it, and after the message,
  the core's call log shows one create and one message; every answer the core gave has a provenance row citing its
  F-04.2 observation, and a catalog entry without one fails the suite; `git diff` shows no changed assertion and the
  test-id list is the same before and after.

#### Slice 6: U-02.2 pending state, reconnect, and the statement resolvers. **Fresh review (lineage semantics).**
- Files: `integrations/conversation/` (the assistant-message upsert); `apps/owner-host` (the tool UI for a pending
  decision); `integrations/lineage/` (`lineage_resolve.py`: the store resolver; `lineage_schema.json`: `message` and
  `conversation` become `implemented`; `lineage_trace.py`: content from the resolver; `lineage_samples.py` and
  `examples/`: the statement sample retired, the examples regenerated).
- STOP gate first (G11): how the pinned Backlog.md answers for an archived task.
- Proof: after the browser and the service restart, the thread and its pending tool call return once; `message` and
  `conversation` references resolve against the real store with mode `authoritative`; an archived task resolves
  through the work resolver, and an unresolved message, statement or archived-task reference fails the test.

#### Slice 7: E-01.5 the launch gate, non-overlap, and the attempt resolver. **Fresh review.**
- Files: `integrations/dispatch/launch_gate.py` (R11); `attempt_end.admit_new_attempt` (the non-overlap rule for
  every profile, with the existing codes `PRIOR_CONVERSATION_RUNNING` and `PRIOR_CONVERSATION_UNOBSERVED`);
  `integrations/agentfixture/` (the inspect documents, each field cited to F-04.2 or to D1 steps (3) and (5b));
  `integrations/lineage/` (the attempt resolver; mode `fixture`; the `fixture-authority` uncertainty; the attempt
  sample retired).
- Proof: the gate passes on the cited document and marks `not-launched` on an altered copy for each of the five
  compared fields and on an inspect that cannot be obtained; both non-overlap refusals; the resolver resolves the
  dispatched attempt against the core with mode `fixture` stated.

#### Slice 8: P-01.3 capture
- Files: `integrations/ownerhost/capture.py` and its endpoint; `apps/owner-host` (the composer's form, the
  acknowledgement card); the model-free chat adapter calls the endpoint.
- Proof: P-01.3's clauses as written. Add: the same message captured twice, and after a crash between the receipt
  and the commit, yields one change; `tools/check_intent_record.py` passes with the store's bytes as the source; the
  package still opens no client socket.
- STOP: a request the fixed layout cannot express without interpretation.

#### Slice 9: E-01.7 the served fixture. **After planning answers PB-1 and PB-2. Review recommended.**
- STOP gates first: G3 (the provenance table for every answer, before any route is built) and G4 (the locked
  document read route by route).
- Records first: section 5, N4 to N6.
- Files: `integrations/agentfixture/` (`server.py`, `transport.py`, `result.py`, the scenarios, the conformance
  tests).
- Proof: E-01.7's clauses as amended; the built RESULT equals the real script's on the same inputs (G7); the listener
  is on `127.0.0.1` only (census); the dispatcher's suites run against the served core unmodified; the UI value is
  refused on the dispatcher's face; a `POST` and an inbound socket message on the UI face are refused; an
  out-of-catalog request answers 501 and the label.

#### Slice 10: P-04.4 acceptance from the UI. **Fresh review.**
- Files: `integrations/owner/acceptance_recorder.py` (the `owner-ui` binding rule only);
  `integrations/ownerhost/acceptance.py`; `apps/owner-host` (the challenge card as a tool UI).
- Proof: P-04.4's clauses. Each refusal leaves the project repository's head and the store unchanged. `owner-ui` from
  the command line is `SESSION_BINDING_REQUIRED`. P-04.1's and E-05.12's suites: same test ids, same assertions.

#### Slice 11: E-01.8 the authority rule, the fixture profile and the composition. **After PB-3. Fresh review.**
- Files: `integrations/dispatch/dispatch_inputs.py` (the client's equality, `attempt_authority`, the provider seam),
  `attempt_run.py`, `attempt_tokens.py` and `result_path.py` (their seams and labels only);
  `profiles/fixture-.../` (`profile.json`, `agent-server/routes.json`, the create template);
  `catalog/assignments/` (the fixture pin's assignment); `tools/check_profile.py`; `profiles/README.md` and
  `properties.json`; `integrations/agentfixture/` (`backend.py`, `run.py`: the composition root and its command);
  a candidate manifest beside D1's in `integrations/dispatch/candidates/`.
- Proof: E-01.8's clauses, offline, with a throwaway store and a manifest promoted by the real recorder in a
  throwaway context. Each mismatch of R8 points 4 and 5 is refused with zero calls at its seam. The census of R8 point
  7. The native admission's and E-05.4's suites: same test ids and assertions. The host credential provider is never
  constructed (import census on the composition root).
- STOP: any change that would alter a native record's bytes, the golden policy digest, or a test of those two suites.

#### Slice 12: U-04.1 the projection
- Files: `integrations/ownerhost/projection.py` and its endpoints (the projection; the referenced artifact by digest).
- Proof: U-04.1's clauses. Each status names the receipt that shows it; `unknown` is shown as unknown; the result
  receipt's commit, diff and test output are references with digests; the label rule of R11 (a missing or wrong label
  is `unknown`).

#### Slice 13: U-01.2 the standalone Canvas route. **After PB-2. Review recommended.**
- STOP gate first: G5 and G6, with the decision rule written before the browser is opened.
- Records first: section 5, C4 and N7 to N8.
- Files: `apps/owner-host` (the engineering route carrying the selection, the frame, the source action); the build
  step that derives the Canvas `build/` copy without its remote imports; the command that starts
  `static-server.mjs`.
- Proof: U-01.2's clauses in a real browser; the selection survives a refresh; the network log shows loopback only.

#### Slice 14: U-04.2 the outcome card
- Files: `apps/owner-host` (the card as a tool UI over the projection).
- Proof: U-04.2's clauses; the fixture label is on the card; a missing source stays visible.

#### Slice 15: U-06.1 the run
- Before the run, written down: the run's rule and each item's decision rule, including PB-5's reading. Then OA-32,
  planning's design acceptance and OA-33, and the dispatch command of slice 11.
- No new code is expected. A defect found here is fixed forward in its own leaf's files.

---

### 4. Decision drafts (Proposed)

Two records, because they are accepted on different evidence and one may wait for planning. Both would be accepted by
the engineering manager under decision 0018 points 1 and 3.1 (architectural decisions inside committed scope),
except where section 2 says planning must answer first. Neither authorizes a reserved act.

#### Draft 0025: The Integration process, the Owner UI session credential and the Owner conversation store

```
# 0025 - The Integration process, the Owner UI session credential and the Owner conversation store

Status: Proposed - 2026-11-16, for plan leaves U-01.3, U-02.1, U-02.2, P-01.3, P-04.4 and U-04.1 (architect, gates C
and G). It authorizes no reserved act.

Authority: the I1 commitment (evidence/bootstrap-log.md, commitment-i1-2026-11-16); decision 0013 points 1, 5 and 6;
decision 0012 points 4 and 9; decision 0008 point 2; decision 0018 points 3.1, 4.1, 4.3 and 4.7; within decisions 0009
(the managed data root), 0010 point 1 (the same-account limit) and 0011 (the host-service lifecycle); blueprint
#conversation (UI-02) and #architecture.

Supersedes: none. It refines decision 0013 point 5 (the credential it names is defined here) and changes no accepted
record's text.

## Decision
1. Form. The Integration process is a Python ASGI service (Starlette on uvicorn, at the versions the component lock
   pins), integrations/ownerhost/, run under the tools interpreter, bound to host 127.0.0.1 on one fixed declared
   port. It has decision 0011's service verbs through the platform contract and no install, upgrade or credential
   verb. Its data are under the managed root's state and logs categories.
2. What it never does. It opens no outbound connection and has no path to an Agent Server; it is custodian of no
   credential; it imports no credential, Gitea, authorization-recorder or dispatch-transport module; it has no
   dispatch endpoint.
3. The credential. cred-owner-ui-session is one random secret, minted only by the Owner's enroll command, which
   refuses a session without a console and shows the secret once. The store keeps a verifier, the session's public
   id and its expiry; one session is current. Its shape is its own (prefix aieh-oui-).
4. Presentation. The credential is sent in a request header on every request and is never a cookie. No route answers
   without it, except the CORS preflight. Host and Origin are checked against literals.
5. Refusals: SESSION_CREDENTIAL_MISSING, _FOREIGN, _EXPIRED, _REVOKED; HOST_NOT_ALLOWED; ORIGIN_NOT_ALLOWED. Each
   changes nothing.
6. The Owner conversation store is a store kind of its own under the managed root, the lineage authority for the
   conversation and message kinds, written only by the Integration process (and, for sessions, by enroll). The thread
   id is the store's; the message id is assistant-ui's native id, unique per thread; order is the store's sequence; a
   user message is immutable and its bytes, kept as received, are the durable source of every quote; an edit is a new
   message; nothing is deleted.
7. Host-internal listeners. A listener of the Owner's account that binds 127.0.0.1 on a declared port, is the target
   of no forward or profile endpoint, makes no outbound connection and holds no credential is recorded in the network
   matrix and the security inventory before it first listens and is not an Owner act. A listener that fails any of
   the four is one (op-guest-boundary-change, or decision 0018 point 4.7).
8. Writes on the Owner's authenticated request. Exactly two: one intent change per message (P-01.3), and the
   acceptance recorder's commit (P-04.4). Each names server-held ids only, is idempotent by its key, and has a
   write-ahead receipt in the integration store.
9. The owner-ui channel. The acceptance recorder admits it only with a session binding verified in process: the
   statement is a user message of the session that makes the request, read from the store. The command line cannot
   declare it. The authorization recorder and the dispatch-input commands admit main-session only, as before.
10. The projection is read-only and takes execution state from the dispatcher's receipts.

## Consequences
- fd-owner-ui-session-plan-silence is answered by U-01.3; the matrix, inventory and role-token records are corrected
  there.
- fd-owner-authorization-record is narrowed for objective acceptance (an authenticated session), not closed: a
  process of the Owner's account can replace the verifier (decision 0010 point 1).

## Not decided here
Passkeys; a separate host identity for the service; backup and restore of the conversation store; the Owner chat's
model backend (deferred by the plan); live session access (U-03.1).

## Not verified
Anything live with the Owner's own credential (OA-32); Linux and macOS.
```

#### Draft 0026: Declared transport authority, the fixture profile and the Agent Server fixture

```
# 0026 - Declared transport authority, the fixture profile and the Agent Server fixture

Status: Proposed - 2026-11-16, for plan leaves E-01.4.2, E-01.5, E-01.7, E-01.8 and U-01.2 (architect, gates C and
G). It authorizes no reserved act. Points 5 and 8 wait for planning's answers on E-01.7's and E-01.8's wording.

Authority: the I1 commitment and the Owner's direction of 2026-11-16 ("use deterministic execution fixtures and the
verified D1 evidence where appropriate"); decisions 0001, 0013 (points 1 and 2), 0020 (point 6) and 0024, all
unchanged; blueprint #conversation (UI-01).

Supersedes: none.

## Decision
1. Authority. An attempt's authority is live or fixture. A profile declares fixture in its pinned route allowlist
   and in its declaration; absent means live. The allowlist's digest is in the policy inputs, so the authority is
   bound at reservation; no record format changes.
2. Seams. The Agent Server transport, the credential provider, the Gitea target and the inspect and pull observers
   each declare an authority (absent: live). The dispatch path requires each to equal the attempt's bound authority
   at its first use and refuses otherwise with a stable code and no call. The dispatch modules compare declared
   values and contain no fixture-specific path.
3. The fixture transport targets a literal loopback address and refuses an answer without the fixture's label.
4. Labels. A record of an attempt whose authority is not live carries it. A reader computes the authority from the
   reservation and treats a missing or contradicting label as unknown. In lineage, a node a fixture answered has
   authority mode fixture and a fixture-authority uncertainty; such a projection is never complete.
5. The fixture profile is not an execution profile: it has no tier, claims no property, cannot be launched, and is
   operational only as its conformance evidence shows. Contract conditions C1 to C7 are unchanged. It replays the
   native execution kind with a token derived from a public seed, from a fixture credential provider.
6. The fixture. One catalog of answers, each field cited, echoed, derived by a pinned rule, or the label; one
   deterministic core; scenarios advance by call count; a request outside the catalog is refused. It executes
   nothing it receives. Its result commit is built by decision 0024 point 4.4's rule over D1's recorded file changes.
7. Faces. One loopback listener: the dispatcher's face, and a read-only face for the Owner UI. The Owner UI never
   uses the dispatcher's face.
8. Agent Canvas at the pin is shown as its standalone application on its own loopback origin, served by upstream's
   static server, never in the origin that holds the Owner's session credential.
9. In I1 the engineering view's access is the fixture's public labelled value; the dispatcher-issued runtime
   credential of decision 0013 point 2 is built at U-03.1.

## Not decided here
The live session access and its forward (U-03.1, OA-07); a fixture for review or CI stages; raw recorded payloads as
committed evidence.

## Not verified
Agent Canvas in a real browser against the fixture; the standalone server's flags in use.
```

---

### 5. Planned-record corrections, mapped to slices

The commitment's four corrections (C), and the new records this design needs (N). "Recording a planned edge, a
narrowing or a correction is not a widening" (decision 0018 point 4.7).

| Id | Record | Change | Slice |
|---|---|---|---|
| C1 | `policy/network-matrix.json` `nm-owner-ui-integration` | `verify_at` and `inspection` U-01.2 to U-01.3; the protocol names the port; at the verdict, status `observed` with evidence | 1, then 2 |
| C2 | `security/inventory.json` `cred-owner-ui-session`, `fd-owner-ui-session-plan-silence` | `carried_to` U-03.1 to U-01.3; the credential's issuer (`owner`), storage, lifetime and notes as built; at the verdict the finding states its answer | 1, then 2 |
| C3 | `policy/role-tokens.json` Owner role | the issuance entry's `delivery` and `issuer`; the revocation entry's `method` | 1, then 2 |
| C4 | `policy/network-matrix.json` `nm-owner-ui-conversation` | `builds_at` U-01.2 to U-03.1 | 13 |
| N1 | inventory `api-integration-service`, `app-owner-host`, `integration-service` | the texts "Not built" and "connects to no backend yet" as built; the principal runs as the Owner's account in bootstrap | 1, then 2 |
| N2 | inventory: the Owner conversation store (asset); objective acceptance and intent capture (operations) | new records of committed leaves' artifacts | 1 (store), 8 and 10 (operations) |
| N3 | `tools/guest.py` `HOST_CENSUS_PORTS`; `docs/development.md` | the Integration process's port | 1 |
| N4 | network matrix: dispatcher to the fixture (`td-management` to `td-management`) | a new `allow` row, `owner_act: false`, prevention "binds 127.0.0.1 only" and "serves recorded answers only" | 9 |
| N5 | inventory: the fixture listener (asset) | new | 9 |
| N6 | census port for the fixture | new | 9 |
| N7 | network matrix: browser to the Canvas application (`td-owner` to `td-owner`), and the Canvas server to the fixture's UI face (`td-owner` to `td-management`) | two new `allow` rows, `owner_act: false` | 13 |
| N8 | inventory asset and census port for the Canvas server | new | 13 |
| N9 | network matrix: the result path to the Gitea double (a kernel-assigned loopback port inside the run's own process, for the push) | a new row, as `nm-gitea-internal` is recorded | 11 |
| N10 | `integrations/lineage/lineage_schema.json` | `message` and `conversation` (slice 6) and `attempt` (slice 7) become `implemented` | 6, 7 |
| N11 | `profiles/README.md`, `profiles/properties.json` | the fixture profile section | 11 |

Placement of the fixture in `td-management` and of the Canvas server in `td-owner` is my recommendation; the checker
must pass, and no row may touch a guest or untrusted domain.

---

### 6. STOP gates before building

Each is a check the engineer runs and reports before the slice builds on it.

| Gate | Slice | Check | STOP when |
|---|---|---|---|
| G1 | 1 | The ASGI stack resolves wheels-only with hashes for this host at the component lock's versions | a package needs an sdist |
| G2 | 4, 6 | With the pinned assistant-ui, in jsdom with no network: `append` receives the user message with its id before the adapter runs; what `load()` does without `headId`; when `update` is called for a tool paused by `unstable_humanToolNames`, and that a reload restores it; per-thread history through `unstable_useAdapters`; how `generateTitle` returns a stream without a model | a pending tool call cannot be restored through the history adapter (then U-02.2 needs `useExternalStoreRuntime`: back to you) |
| G3 | 9 | The provenance table for every answer of both faces, written before any route | any row has no committed observation and planning has not admitted its class (PB-2) |
| G4 | 9 | The locked release `openapi.json` (the asset), route by route against `routes.json`: defined or not, and the response schema | the result contradicts PB-1's premise either way (report it) |
| G5 | 13 | The pinned standalone Canvas in a real browser against the fixture's UI face: every request it makes, which fail, whether the conversation view renders, the network log. Rule, written first: PASS iff the view shows the fixture conversation's title and the dispatched message, every request the fixture answered 2xx has a provenance row, and no request went to a host other than 127.0.0.1 | a request leaves loopback (an egress origin: the Owner's, decision 0018 point 4.7); or rendering needs an answer with no provenance row |
| G6 | 13 | `static-server.mjs` at the pin with `--host 127.0.0.1`, `--route`, `--session-api-key`, `--disable-telemetry`; the census | it binds elsewhere, or a flag is not as its help text says |
| G7 | 9 | The built RESULT answer's commit id equals the real RESULT script's on the same base, edits, message and time (real shell, in a test) | they differ |
| G8 | 2 | The console guard: a pipe on either handle is refused; a console passes | a tool shell can run `enroll` |
| G9 | 11 | `tools/check_profile.py` accepts the fixture profile only on its own path, and `tools/guest.py` cannot create a guest from it | either tool treats it as an execution profile |
| G10 | 9 | The two server behaviours the fixture reproduces from source (the CORS rule; the session socket's `sync` then `durable` order), confirmed in the locked wheel, not only in the GitHub copy | the wheel differs |
| G11 | 6 | How the pinned Backlog.md 1.55.3 answers `task view <id> --json` for an archived task (the lineage README records that `task list --json` does not list one, and that it "was not examined") | an archived task cannot be read by the two commands the work resolver is limited to (then "archived tasks resolve" needs a resolver change: report it before building) |

---

### 7. Upstream facts

#### Verified at the pins

Installed packages (`apps/owner-host/node_modules`):

| # | Fact | Where |
|---|---|---|
| 1 | Canvas's embedded library cannot select a session | `@openhands/agent-canvas/dist/hooks/use-conversation-id.js`; `dist/context/navigation-context.js` (exports `useNavigation` only); `dist/components/providers/*.d.ts` |
| 2 | The standalone build routes `conversations/:conversationId` (and `.../panel`) | `build/assets/manifest-*.js` |
| 3 | Backends: `localStorage` key `openhands-backends`; the default local backend is the page's origin with `window.__AGENT_CANVAS_SESSION_API_KEY__`; a local backend authenticates with `X-Session-API-Key` | `dist/api/backend-registry/{storage,active-store,default-backend,auth}.js`, `dist/api/agent-server-config.js` |
| 4 | For a local backend the conversation URL is derived from the backend host and the key is the backend's | `dist/api/agent-server-adapter.js` |
| 5 | The socket is `/sockets/session/<id>` with `after_seq`, first-frame authentication, and the frame types `sync`, `durable`, `transient`, `delta`, `item_started`, `item_aborted`, `error`; Canvas can send a user message on the socket and by `sendEvent` | `dist/utils/websocket-url.js`, `dist/contexts/conversation-websocket-context.js` |
| 6 | `runtime/credentials` occurs nowhere in Canvas's `dist/` or the client's `dist/` | a search of both |
| 7 | Conversation-scoped requests use `/api/conversations/<id>/...` when `/server_info` advertises `conversation_runtime_routes_v1`; a `/server_info` error other than 404 is thrown | `@openhands/typescript-client/dist/client/runtime-transport.js` |
| 8 | The event stream authenticates by a first frame `{"type": "auth", "session_api_key": ...}` and refuses a key in the URL | `@openhands/typescript-client/dist/client/conversation-event-stream.js` |
| 9 | The client's generated schema has `.../runtime` (one operation) and `.../runtime/reprovision`, and no `.../runtime/credentials` | `@openhands/typescript-client/dist/generated/agent-server-schema.d.ts` |
| 10 | `static-server.mjs`: static files and a reverse proxy (`--route`, WebSockets), loopback by default, key injection, `--disable-telemetry`, `--base-path` | `@openhands/agent-canvas/scripts/static-server.mjs` (its help text; not run) |
| 11 | assistant-ui: `ThreadHistoryAdapter` (`load`, `append`, optional `update` and `delete`), `RemoteThreadListAdapter` (`initialize` returns `remoteId`; `delete`, `archive`, `generateTitle`, `fetch` required), `useLocalRuntime`, `useRemoteThreadListRuntime`, `makeAssistantToolUI`, `unstable_humanToolNames`; message ids from `nanoid/non-secure`, seven characters | `@assistant-ui/core/dist/adapters/thread-history.d.ts`, `dist/runtimes/remote-thread-list/types.d.ts`, `dist/runtimes/local/local-runtime-options.d.ts`, `dist/utils/id.js`; `@assistant-ui/react/dist/index.d.ts` |

`openhands-agent-server` source at the lock's commit `e99e5c71...` (fetched from GitHub; **not** compared with the
locked wheel, which is not in the repository: gate G10):

| # | Fact | File |
|---|---|---|
| 12 | CORS always allows an origin whose host is `localhost` or `127.0.0.1`, with credentials, every method and header | `middleware.py` |
| 13 | The session socket: authentication, close 4004 for an unknown conversation, one `sync` frame, then `durable` frames for every `seq` above `after_seq`; an inbound frame that is not the auth message is validated as a message and sent to the conversation with a run | `session_socket.py`, `session_protocol.py` |
| 14 | `POST /api/conversations/{id}/runtime/credentials` answers `{"session_api_key": ...}` and 404 for an unknown conversation | `docker_runtime/routers.py` |
| 15 | In Docker mode the outer server proxies `/api/conversations/{id}/{tail:path}` and both sockets to the conversation's container after authenticating with the outer key | `docker_runtime/routers.py` |

In the repository: the result path requires a held native token (`result_path.outbound_search`); it admits one
repository id (`ADMITTED_REPOSITORIES`); every later Agent Server call builds the client from the pinned allowlist
(`attempt_end._client`); the acceptance recorder has no channel list and no test uses `owner-ui`; D1's raw records are
not committed (`evidence/D1-run-2026-11-16.md`, "Raw records").

#### Not verified

1. Which requests the Canvas conversation page makes, and which must succeed for it to render (a browser is needed).
2. That telemetry disabled and the font imports removed leave no request beyond loopback.
3. The locked release `openapi.json` itself; I used the pinned client's generated schema as a stand-in.
4. Whether any committed evidence records the UI's vantage on a conversation beyond E-01.3.3 step (4). I searched the
   evidence for the socket routes and event kinds, not every evidence file.
5. The wheels for the ASGI stack under the tools lock process.
6. assistant-ui's runtime behaviour (types were read, nothing was run).
7. Whether Canvas tolerates an extra field in a socket frame (so the label goes in the handshake header).
8. The root `config.yml`, the credential stores and the managed data root: not read.

---

### 8. Residuals, stated

- **The same-account limit stands** (decision 0010 point 1; decision 0013 point 6). A process of the Owner's account
  can replace the session verifier or write the conversation store. The session credential authenticates the Owner to
  the service against other origins and other accounts; it does not separate him from host-side agents. Pinned
  digests in references make a later change to a stored message detectable.
- **The shell's origin holds the session's authority.** Hence the header, the content-security policy, and Canvas on
  another origin.
- **The fixture's access values are public.** Any local process can drive the fixture; the call log shows it.
- **The fixture's result is D1's**, whatever is requested (PB-8).
- **Three new loopback listeners** and **one new dependency family** on the trusted host.
- **The conversation store is an authority with no backup yet.** Not required by I1's criteria; it should become a
  leaf or a deferral through planning, not a clause of U-02.1.

---

## Engineering manager's rulings on the I1 architect answer (2026-11-16)

Source: the architect's answer above (gates C, G), held in session scratch.

- ACCEPTED: R1-R3 and R5-R15, the slice order (section 3), the STOP gates G1-G11 (section 6), the record corrections C1-C4 and N1-N11 (section 5).
- AMENDED R4 / draft 0025 point 4 (custody choice under delegated authority, decision 0018 point 3.1):
  - The browser copy of cred-owner-ui-session is kept in the shell origin's localStorage, not sessionStorage. The origin is scheme+host+port, so other loopback listeners cannot read it.
  - "Sign out" removes it, and the service-side expiry bounds it.
  - Reason: U-06.1 item (7) closes and reopens the browser during and after execution. sessionStorage would make the Owner re-enter his credential at each reopen, an avoidable Owner interaction; the Owner directed that his interactions be consolidated.
  - A same-account process reading the browser profile is inside decision 0010 point 1's disclosed same-account limit; disclose it in 0025's Consequences.
  - The header-not-cookie rule, the Host/Origin literal checks and the separate Canvas origin are unchanged.
- PB-9: ACCEPTED by me as the execution-profile contract's owner (precedent 0015 P7). The fixture profile class is inside committed scope.
- 0025 and 0026 are committed as Proposed in slice 1. I accept each at its leaves' verdicts; 0026 points 5 and 8 wait for planning.
- To planning (handoff after slice 1): PB-1, PB-2, PB-3 (blockers or readings), PB-4 and PB-6 (leaf notes), PB-5 (U-06.1 reading), PB-7 and PB-8 (OA-32/OA-33 presentation).
