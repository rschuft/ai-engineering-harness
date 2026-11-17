# Owner host

The Owner's single React application (plan leaf **U-01.1**, parent U-01;
blueprint [`#conversation`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#conversation)).
It is a responsive shell with persistent navigation, one session identity, the
Owner chat built on assistant-ui, empty objective and Work surfaces, and Agent
Canvas embedded as a library for engineering sessions.

**One backend: sign-in and the stored chat.** Since U-01.3 the shell signs in to the
Integration process ([`integrations/ownerhost`](../../integrations/ownerhost/README.md))
on `http://127.0.0.1:13310`, its only backend. Since U-02.1, once signed in, the
chat's threads and messages are kept in the Owner conversation store through it
(below). There is still no chat model (every reply is a fixed acknowledgement),
objective source, Work system or Agent Server behind it, and every surface says
so instead of showing sample data.

Commands, prerequisites and verification status: [Owner host](../../docs/development.md#owner-host)
in the development reference.

## Routes

| Path | Area | Renders |
|---|---|---|
| `/` | (none) | Redirects to `/chat`. |
| `/chat` | Chat | assistant-ui's headless primitives. Signed out: `useLocalRuntime` with a model-free adapter, an empty in-memory thread and a disabled composer. Signed in (U-02.1): the stored chat, its thread list and the thread, with an Edit action that keeps the earlier version (branch picker). |
| `/work` | Work | The Objectives and Work items surfaces, each with an empty state that says no source is connected. |
| `/engineering` | Engineering | A "No Agent Server is connected" notice, then Agent Canvas's providers and scoped root, loaded lazily. |
| `/sign-in` | (none) | The login view (U-01.3): paste the Owner UI session credential; once signed in, the session and "Sign out". Not an area, so not in the navigation; the header links to it. |
| any other | (none) | "Page not found" inside the shell, with links to the three areas. |

The table is `ownerRoutes` in [`src/routes.tsx`](src/routes.tsx); the areas'
order, paths and labels are `AREAS` in [`src/areas.ts`](src/areas.ts). Every
area renders in `OwnerShell`'s outlet, so the navigation and the identity stay
mounted while the area changes.

## Components

| Component | File | Role |
|---|---|---|
| `OwnerApp` | `src/App.tsx` | The identity provider and the sign-in state above the router. |
| `OwnerShell` | `src/shell/OwnerShell.tsx` | Header (product name, identity, sign-in control), area navigation (`NavLink`, `aria-current`), outlet. |
| `useShellLayout` | `src/shell/layout.ts` | `wide` at or above 900 px, `narrow` below, from `matchMedia`. The shell sets `data-layout`; `shell.css` keys the grid on it. |
| `SessionIdentity` | `src/identity/SessionIdentity.tsx` | Shows "Owner", the local session's short id and "Not signed in" or "Signed in"; compact in the narrow layout. |
| `OwnerSessionProvider` | `src/identity/OwnerSessionContext.tsx` | The sign-in state: checks a stored credential once when the shell opens, `signIn` (verify, then keep), `signOut` (remove), and the Integration process client of the signed-in session. |
| `SignIn`, `SessionControl` | `src/identity/SignIn.tsx`, `src/identity/SessionControl.tsx` | The login view, and the header's "Sign in" link or "Sign out" button. |
| `ChatArea`, `StoredChat` | `src/areas/ChatArea.tsx` | assistant-ui `AssistantRuntimeProvider`, `ThreadPrimitive`, `MessagePrimitive`, `ComposerPrimitive`; signed in, `useRemoteThreadListRuntime` over `useLocalRuntime` with `ThreadListPrimitive`, `ActionBarPrimitive.Edit` and `BranchPickerPrimitive`. |
| `createThreadListAdapter`, `createHistoryAdapter` | `src/areas/conversation-adapters.ts` | The `RemoteThreadListAdapter` and the per-thread `ThreadHistoryAdapter` (through `unstable_useAdapters`) over the Integration process's thread and history routes (U-02.1). |
| `acknowledgingChatAdapter`, `modelFreeChatAdapter`, `createCapturingChatAdapter` | `src/areas/chat-adapter.ts` | The signed-in chat's fixed acknowledgement (never a model's text), and the signed-out adapter that refuses to run; since P-01.3 the signed-in chat's adapter, which asks the Integration process to capture a message in the request layout and replies with its card; since P-04.4 it also answers a `Review acceptance: O<n> of <change>` message with the acceptance card (the challenge, asked for the card the run writes) and an `Accept O<n> of <change>` message with the recorded card (on the nonce of the card it follows); any other message gets the acknowledgement. |
| `RequestForm`, `CaptureCard` | `src/areas/RequestForm.tsx`, `src/areas/capture-card.tsx` | The request form (P-01.3): the change's name, its objective, its acceptance criteria and suggestions as labelled one-line fields, sent as one message in the fixed layout shown in its preview; and the card that shows the capture's answer (the change and its commit) or its refusal with the stable code. |
| `AcceptanceCard`, `AcceptanceRecordCard` | `src/areas/acceptance-card.tsx` | The acceptance cards (P-04.4), assistant-ui tool UIs: the recorder's summary as the Integration process answered it, its expiry and an Accept form whose preview is exactly the message it sends, appended under its own card; and the recorded acceptance (the outcome id, minted or kept, the commit, the statement's reference) or the refusal with its stable code. The capture card offers the review of its change's objective. |
| `DecisionToolUI`, `UnknownToolUI`, `HUMAN_TOOL_NAMES` | `src/areas/decision-tool.tsx` | The tool UI for a pending Owner decision (U-02.2): the `owner_decision` human tool's question and one button per option while it is pending, the answer once given; any other tool call is named, never run. |
| `WorkArea` | `src/areas/WorkArea.tsx` | Objectives and Work items empty states. |
| `EngineeringArea` | `src/areas/EngineeringArea.tsx` | Not-connected notice, `CanvasBoundary`, lazy `CanvasMount`. |
| `CanvasMount` | `src/engineering/CanvasMount.tsx` | `AgentServerUIProviders` (analytics off, host i18n). Its `children` prop is the seam where U-01.2 places the selected session. |
| `CanvasBoundary` | `src/engineering/CanvasBoundary.tsx` | Replaces a failed Canvas mount with an explicit empty state naming the error. |
| `EmptyState` | `src/areas/EmptyState.tsx` | The shared plain "nothing connected" statement (`role="status"`). |

## Session identity

`loadOrCreateSessionIdentity` ([`src/identity/session-identity.ts`](src/identity/session-identity.ts))
returns `{ role: "owner", sessionId, createdAt, persisted, authenticated: false }`.
`sessionId` is a random UUID made once with `crypto.randomUUID()` and kept in
`localStorage` under `aieh.owner-host.session-identity`, so it is the same in
every route, every tab and after a reload, until the browser's site data is
cleared. It is resolved once, above the router. If storage is unavailable, the
value lasts for the page and is marked `persisted: false`.

It is **not** authentication: it holds no credential, token or key. How the
Owner UI reaches the Agent Server is the open finding `fd-owner-ui-access` in
[`security/inventory.json`](../../security/inventory.json); nothing here decides
it.

## Sign-in to the Integration process (U-01.3)

[Decision 0025](../../decisions/0025-integration-process-owner-ui-session-credential-and-owner-conversation-store.md)
(accepted at U-01.3's verdict), point 4. The Owner mints the Owner UI session credential,
`cred-owner-ui-session` (`aieh-oui-` and 52 lower-case base32 characters), at his
own console with `task ownerhost:enroll`, and pastes it into `/sign-in`.
[`src/identity/owner-session.ts`](src/identity/owner-session.ts) holds the rules:

- The pasted value is checked for the shape first (nothing is sent otherwise),
  then verified with `POST /session`; only a verified credential is kept, as
  one record under `aieh.owner-host.owner-ui-session` in this origin's
  `localStorage`, with the session's public id and expiry. The field is
  emptied after each attempt.
- Every request to the Integration process goes through one client: to
  `http://127.0.0.1:13310` only, a path and never a URL, with the
  `X-AIEH-Owner-Session` header, `credentials: "omit"` (never a cookie),
  `redirect: "error"` and no referrer.
- A stored copy is checked once when the shell opens (the browser may have been
  closed and reopened). A refused credential (`SESSION_CREDENTIAL_FOREIGN`,
  `_EXPIRED`, `_REVOKED`) removes the copy; an unreachable process keeps it.
- The same holds on every authenticated route while signed in: a credential the
  thread or history routes refuse (for example after a later enrollment) removes
  the copy and returns the shell to sign-in, with the refusal shown, as "Sign
  out" does; a refusal of the request itself (`REQUEST_INVALID`, a store code)
  keeps it.
- "Sign out" removes the copy. The service's expiry bounds it either way.

Who can read the copy:

- A listener on another port cannot: the origin is scheme, host and port.
- A process that holds the shell's own port (`127.0.0.1:5173` or `4173`) while
  the shell is down **is** that origin, and a page it serves can read the copy.
  For a process of the Owner's account this is inside decision 0010 point 1's
  same-account limit; for another local account it is a disclosed residual.
  Vite's `strictPort` refuses to start on a squatted port, which is a visible
  signal: the shell does not come up.
- A process of the Owner's account that reads the browser profile can read the
  copy: inside the same limit.

### Precondition: nothing agent-authored in the shell's origin

The shell's origin holds the session's authority, so until U-01.2 moves Agent
Canvas to its own origin (decision 0026 point 8), **no agent-authored or
fixture-served content may be rendered in the shell's origin**. Today the
embedded Canvas has no backend: nothing configures one (no `openhands-backends`
entry, no session key), so it renders no conversation
(`src/engineering/canvas-no-backend.test.tsx`). Connecting a backend to the
embedded Canvas would break this precondition.

### Content-security policy

[`build/csp.ts`](build/csp.ts): the shell's origin holds the session's
authority, so the page may load code only from itself and connect only to
itself and to `http://127.0.0.1:13310`. `vite preview` sends it as a header (with
`frame-ancestors 'none'`), the build puts it into `index.html` as its first
element, and `vite dev` sends it with one allowance, inline scripts, for the
React refresh preamble Vite injects. Styles may be inline (Canvas and its
bundled libraries insert `<style>` elements) and images may be `data:` URLs
(Canvas shows browser screenshots so); frames are refused until the standalone
Canvas origin exists (U-01.2).

## Dependencies

`package.json` and `package-lock.json` are this app's own; the component lock in
`composition/lock/npm/` is unchanged. Every package the two locks share keeps the
component lock's version and integrity, except that the app's newer Vite toolchain
takes the top-level `vite` and `rolldown` paths, so Canvas's own pins (`vite`
8.0.16, `rolldown` 1.0.3) are nested under it. Install with `npm ci --ignore-scripts`. Nothing is
vendored (decision 0005): `node_modules/` and `dist/` are ignored.

| Package | Version | Licence | Why |
|---|---|---|---|
| `@openhands/agent-canvas` | 1.36.0 | MIT | Pinned component. |
| `@assistant-ui/react` | 0.15.32 | MIT | Pinned component. |
| `react`, `react-dom` | 19.3.1 | MIT | Pinned; Canvas's exact peer. |
| `react-router` | 8.5.0 | MIT | Pinned; Canvas's exact peer. |
| `i18next` | 26.5.11 | MIT | The version Canvas locks. Builds Canvas's i18n instance from its exported translations instead of Canvas's HTTP loader. |
| `vite` | 8.3.6 | MIT | Build and dev server (dev only). |
| `@vitejs/plugin-react` | 6.2.1 | MIT | JSX transform (dev only). |
| `vitest` | 5.1.0 | MIT | Test runner (dev only). |
| `jsdom` | 31.0.0 | MIT | Test DOM (dev only). |
| `@testing-library/react` | 16.3.3 | MIT | Component tests (dev only). |
| `@testing-library/dom` | 10.4.2 | MIT | Peer of the above (dev only). |
| `typescript` | 7.0.2 | Apache-2.0 | Type check (dev only). |
| `@types/react`, `@types/react-dom` | 19.3.0 | MIT | React types (dev only). |

The lock holds five packages that declare install scripts, and none of them is run:
`@openhands/agent-canvas` (a `postinstall` that only prints a banner on global
installs), `@heroui/shared-utils`, `@openrouter/sdk`, `core-js` and `fsevents`.

## Threads and messages (U-02.1)

[Decision 0025](../../decisions/0025-integration-process-owner-ui-session-credential-and-owner-conversation-store.md),
point 6. Signed in, the chat is assistant-ui's `LocalRuntime` under
`useRemoteThreadListRuntime` ([`src/areas/ChatArea.tsx`](src/areas/ChatArea.tsx)), with
two thin adapters ([`src/areas/conversation-adapters.ts`](src/areas/conversation-adapters.ts))
over the Integration process's thread and history routes:

- the `RemoteThreadListAdapter`: `initialize` sends the runtime's local thread id
  and gets back the id the Owner conversation store mints; `list`, `fetch`,
  `rename`, `archive` and `unarchive` read and write the store's thread events;
  `delete` is always refused (`THREAD_DELETE_REFUSED`: nothing is deleted);
  `generateTitle` returns a stream that closes at once (no model titles a thread);
- the `ThreadHistoryAdapter`, per thread through `unstable_useAdapters` (it
  resolves the thread at each call): `load` reads the thread's messages in the
  store's order, with no head, so the newest branch is shown; `append` and
  `update` send each message under assistant-ui's own id. One thread's writes are
  sent one after another in call order: the runtime does not order writes of
  different messages, and the store refuses a reply whose statement it does not
  hold yet (`MESSAGE_PARENT_NOT_FOUND`).

The store keeps an Owner message's text exactly as typed (its UTF-8 bytes) and
never changes it; Edit sends a new message under the same parent and the
branch picker shows both versions. The reply is
[`acknowledgingChatAdapter`](src/areas/chat-adapter.ts)'s fixed text, the same
every time: no model is called.

What the pinned runtime does, which the adapters rely on, is gate G2's test
([`src/areas/g2-runtime-gate.test.tsx`](src/areas/g2-runtime-gate.test.tsx), jsdom,
no network): the history append of a message, with its id, before the model
adapter runs; `load()` without a head; a run paused on a human tool (the model
adapter returns status `requires-action`) appended at the pause, restored by a
reload and completed by an update; per-thread history; a title stream with no
model.
[`src/areas/stored-chat.test.tsx`](src/areas/stored-chat.test.tsx) runs the
stored chat against a fake Integration process. A real browser and the Owner's
own session are **not yet verified**.

## Pending decisions and reconnect (U-02.2)

A decision the Owner is asked is a human tool, `owner_decision`
([`src/areas/decision-tool.tsx`](src/areas/decision-tool.tsx)). A run pauses on
it because the run's model adapter returns the `owner_decision` call with status
`requires-action`: in the pinned assistant-ui 0.15.32, `unstable_humanToolNames`
(which the stored chat still passes) does not pause a run, and a settled run is
marked complete unless its adapter says otherwise (gate G2's test). A future
producer of decisions (a chat model adapter) must therefore return
`requires-action` itself. The paused assistant message (status
`requires-action`, the tool call without a result) is appended to the Owner
conversation store like any message. The assistant message renders
its tool calls through `MessagePrimitive.Parts`' tool components: the decision
card shows the question and one button per option while the call is pending,
and the answer once given.

After the browser is closed and reopened, or the Integration process restarts,
the history adapter's `load` brings the paused message back, once, and the card
shows it still pending (gate G2: a pending tool call is restored through the
history adapter, so `useExternalStoreRuntime` is not needed). The Owner's answer
(`addResult`) resumes the run with the chat's model adapter, and the completed
message is an `update` of the same id, which the store keeps as a new revision.
Reopening again shows the answered card, once; reopening writes nothing.

No chat model is connected, so the shell asks no decision itself yet:
`StoredChat` takes the run's model adapter as `chatModel` (the fixed
acknowledgement by default), and the test supplies one that asks a decision.
[`src/areas/pending-decision.test.tsx`](src/areas/pending-decision.test.tsx)
closes and reopens the browser in jsdom against a fake Integration process with
the store's rules, and compares the requests the shell sent with
[`src/areas/fixtures/pending-decision.wire.json`](src/areas/fixtures/pending-decision.wire.json),
which the Integration process's test replays against a real process it stops
and starts (`integrations/ownerhost/tests/test_pending_decision.py`). A real
browser and a decision asked by a real producer are **not yet verified**.

## Requested changes (P-01.3)

Under the composer, the request form ([`src/areas/RequestForm.tsx`](src/areas/RequestForm.tsx))
takes a requested change as labelled fields: the change's name (kebab-case), its objective, one or
more acceptance criteria and optional suggestions, each one line. "Send the request" appends one
message in the fixed layout the Integration process parses (`formatRequest`; the preview shows the
exact text, which is what the store keeps and the record quotes):

```
Change: <name>
Objective: <objective>
Acceptance criteria:
- <criterion>
Suggestion: <suggestion>
```

No model is connected. The run's model adapter (`createCapturingChatAdapter`) waits until the
history adapter has stored the message, then sends
`POST /threads/{thread}/messages/{message}/capture` with the sha256 of the message's text
(WebCrypto), and replies with an `intent_capture` tool call whose result is the service's answer
or refusal, shown by the capture card; a message not in the layout gets the fixed acknowledgement
and no capture. A suggestion is recorded as a hypothesis, never as the objective
([the Integration process's capture](../../integrations/ownerhost/README.md#capture-p-013)).
[`src/areas/capture-request.test.tsx`](src/areas/capture-request.test.tsx) shows it against a fake
Integration process: the layout and its digest (equal to Python's), the order (the capture after
the statement is stored), the card, a refusal's code and detail, and no capture for an ordinary
message. A real browser is **not yet verified**.

**Objective acceptance (P-04.4).** The capture card's review button, or the Owner typing it, sends
`Review acceptance: O<n> of <change>`; the run's adapter, once that message is stored, asks
`POST /threads/{thread}/messages/{message}/acceptance-challenge` with its sha256 and the id of the
assistant message the run is writing (`unstable_getMessage().id`), and replies with the acceptance
card (`objective_acceptance`): the acceptance recorder's summary as answered, its expiry and an
Accept form. The form sends, as the Owner's own message and exactly as its preview shows,
`Accept O<n> of <change>` and, when he writes any, a line break and his own words; it is appended
directly under its own card, so that an older card's form accepts on that card's challenge, never a
later card's. The run's adapter then asks `POST .../messages/{message}/acceptance` with the nonce of
the card the message follows and the message's sha256, and replies with the recorded card
(`objective_acceptance_recorded`). An acceptance with no card of its item before it asks nothing
(`ACCEPTANCE_NO_CARD`). Nothing on either card is a model's text; the service decides and records
([the Integration process's acceptance](../../integrations/ownerhost/README.md#objective-acceptance-p-044)).
[`src/areas/acceptance-flow.test.tsx`](src/areas/acceptance-flow.test.tsx) shows it against a fake
Integration process. A real browser is **not yet verified**.

## The standalone Agent Canvas (U-01.2): gates G6 and G5

Plan leaf U-01.2 shows an attempt's engineering session as blueprint UI-01's fallback: Agent Canvas 1.36.0's
standalone application, served by upstream's own `scripts/static-server.mjs` on its own loopback origin,
`http://127.0.0.1:13330`, proxying to the served fixture's read-only UI face (`http://127.0.0.1:13320/ui`,
[`integrations/agentfixture`](../../integrations/agentfixture/README.md)), framed in the engineering area
(the I1 design, R14 and R15; decision 0026 points 8 and 9, Proposed). Its edges and asset were recorded first
(`nm-owner-ui-canvas`, `nm-canvas-agentfixture-ui`, `app-agent-canvas`; census port 13330).

**The start command** is `npm run canvas:serve` ([`scripts/canvas-standalone.mjs`](scripts/canvas-standalone.mjs),
its tests beside it): it checks the installed package against `package-lock.json`, derives the copy of `build/`
(the two font imports removed, checked byte for byte; `--csp` adds the content-security policy, off by default),
and runs upstream's server with G6's command line below; `npm run canvas:derive` only derives. The font rule both
it and the library build plugin apply is one module, [`scripts/remote-imports.mjs`](scripts/remote-imports.mjs).

The two gates' decision rules below were written and committed **before** the Canvas server first listened and
before any browser was opened (the I1 design, section 6). They are not changed after the observation.

### G6: the static server at the pin

**Run.** `node <agent-canvas>/scripts/static-server.mjs --host 127.0.0.1 --port 13330 --dir <derived build>
--route /api=http://127.0.0.1:13320/ui --route /sockets=http://127.0.0.1:13320/ui
--route /server_info=http://127.0.0.1:13320/ui --session-api-key agentfixture-ui-face-public-value
--disable-telemetry`, from the installed pinned package (`@openhands/agent-canvas` 1.36.0, integrity as
`package-lock.json` records it), unpatched, with no window, its environment holding no `MARS_*`,
`SESSION_API_KEY` or `AGENT_CANVAS_*` variable but `MARS_WEB=0`. `<derived build>` is a copy of the package's
`build/` outside the checkout.

**PASS iff every one of these is observed:**

1. *Binding.* The host census by port 13330 (`tools/guest.py`'s query, `Get-NetTCPConnection -State Listen`)
   finds exactly one listener on that port, its address `127.0.0.1`, owned by the started process (or its
   child), and no other listener of that process tree on any address.
2. *`--host`, `--port`.* The server's own ready line names `http://127.0.0.1:13330/`.
3. *`--route`* ("Proxy <prefix> (and subpaths) to <url>; may be repeated. WebSockets supported"): a `GET
   /server_info` and a `GET /api/conversations/<id>` sent to 13330 are answered by the fixture (its
   `X-AIEH-Fixture` label header present, and the fixture's call log names the request on its UI face under
   `/ui`); a WebSocket upgrade of `/sockets/session/<id>` sent to 13330 reaches the fixture's UI face (a labelled
   handshake, and its call log's `connect`).
4. *`--session-api-key`* ("Inject session API key into index.html"): the served `index.html` holds
   `window.__AGENT_CANVAS_SESSION_API_KEY__="agentfixture-ui-face-public-value"`.
5. *`--disable-telemetry`* ("Injects window.__AGENT_CANVAS_DO_NOT_TRACK__ = true"): the served `index.html` holds
   `window.__AGENT_CANVAS_DO_NOT_TRACK__=true`.
6. *The derived build* differs from the package's `build/` only by the two remote Google Fonts `@import` rules
   removed: a byte comparison of every file finds exactly one changed file (the root stylesheet), whose bytes equal
   the original's with exactly those two rules taken out, and no JavaScript file changed, added or removed.

**STOP** (and report, building nothing on it) if the server binds anything but `127.0.0.1`, or any flag above does
not do what its help text says.

**Observed (2026-11-17): PASS.** Windows 11, Node 24.19.0, the installed package's version and integrity equal to
`package-lock.json`'s (npm's install record compared for the package, `sirv`, `httpxy` and `sirv`'s closure). The
server was started exactly as the rule's command line, its environment `SystemRoot`, `windir`, `TEMP`, `TMP` and
`MARS_WEB=0` only, the fixture serving on 13320 (scenario `finished`, a conversation created and its message sent on
the dispatcher's face).

1. One TCP listener on port 13330, `127.0.0.1`, owned by the server's node process; that process held no other TCP
   listener and no UDP endpoint. `tools/guest.py host-census`: PASS, listing 13330 (`node`, found by port) and 13320
   (`python`) on `127.0.0.1`.
2. Upstream's ready line: `Static-server + proxy listening on http://127.0.0.1:13330/`, with the three routes
   `/server_info`, `/sockets` and `/api` to `http://127.0.0.1:13320/ui`.
3. Through 13330: `GET /server_info` 200 with the label (`ui-server-info`); `GET /api/conversations/<id>` 200 with
   the label (`ui-conversation`, title `FIXTURE: ai-engineering-harness/agentfixture (not a live conversation)`);
   the session socket's handshake labelled (`ui-socket`), then `sync` and `durable` after the first-frame
   authentication; the fixture's call log names each on its UI face.
4. and 5. The served `index.html` holds `window.__AGENT_CANVAS_SESSION_API_KEY__="agentfixture-ui-face-public-value";`
   and `window.__AGENT_CANVAS_DO_NOT_TRACK__=true;` (in upstream's one injected script, before `</head>`).
6. 400 files in each tree, the same set; one differs, `assets/root-DpxuifD3.css` (sha256 `32148826…2341` in the
   package, `608907fc…3dc6` in the copy), equal to the original with exactly the two Google Fonts `@import` rules
   (285 bytes) removed; no JavaScript or HTML file differs.

### G5: the conversation view in a real browser

**Run.** The fixture serves on `127.0.0.1:13320` (scenario `finished`, the locked release document given). Before
the page opens, the conversation is created and its one message sent on the fixture's **dispatcher's** face, as
the dispatcher sends them (the D1 stage's create template with a conversation id; one user message): the fixture's
session socket sends the `sync` frame and the replay at connect and no live frame after (E-01.7's verdict), so
the message can only reach the view by the replay or the event search, never by a live frame. The Canvas server
runs as in G6. A real browser (the host's installed Chrome or Edge, headless, a throwaway profile under the
session's scratch directory, background networking, component updates, sync and default apps off) opens
`http://127.0.0.1:13330/conversations/<id>`, driven over the DevTools protocol; the page's own network log
(the protocol's Network domain, WebSocket included) is the egress evidence. The browser process's own background
traffic is constrained by those flags, not packet-captured.

**Recorded:** every request the page made (URL, method, status, and for each one the fixture answered, its catalog
answer from the label header and the call log, and that answer's provenance rows in
`integrations/agentfixture/README.md`); which requests failed; whether the view renders; screenshots.

**PASS iff all of:**

1. the view shows the fixture conversation's title (`FIXTURE: ai-engineering-harness/agentfixture (not a live
   conversation)`, the UI face's labelled title) and the dispatched message's text, read from the rendered page
   (its visible text) and seen in a screenshot;
2. every request the fixture answered with a 2xx status names a catalog answer that has provenance rows (the
   label header's `answer`, found in the served provenance table);
3. no request in the page's network log went to a host other than `127.0.0.1`.

**STOP** (and report) if a request leaves loopback (an egress origin is the Owner's: decision 0018 point 4.7), or
rendering needs an answer with no provenance row. A request the fixture refuses (its labelled 501) is recorded as
failed; it does not stop the gate unless the view cannot render without it.

**Observed (2026-11-17): STOP, on both conditions.** Headless Chrome (the host's installed
`C:\Program Files\Google\Chrome\Application\chrome.exe`) with a throwaway profile, the rule's flags, driven over the
DevTools protocol from the tools set's `websockets`; the fixture and the Canvas server as in G6; the page
`http://127.0.0.1:13330/conversations/<id>`, observed until the browser's own `networkIdle` lifecycle event.

- **A request left loopback.** The page made 14 `GET` requests to `https://cdn.simpleicons.org/...` (`github`,
  `linear`, `gitlab`, `bitbucket`, `atlassian`, `jira`, `notion`, each twice), all answered 200: icons of the MCP
  integration catalog that Canvas's bundled `@openhands/extensions` lists as `logoUrl` and renders as images on its
  onboarding and home view's "Suggested" templates, from a Cloudflare address (`[2606:4700:3036::ac43:d892]:443`). Neither upstream's `--disable-telemetry` nor the font rule
  touches them. No request went to `fonts.googleapis.com`, `fonts.gstatic.com` or a telemetry host. The request
  headers were not recorded.
- **The view did not render the conversation.** A fresh profile shows Canvas's onboarding ("Check your backend",
  "Disconnected", with the default backend `http://127.0.0.1:13330` and the injected key filled in), and no request
  for the conversation, its events or its socket was made. Canvas 1.36.0's local-backend check
  (`dist/api/agent-server-compatibility.js` `validateLocalBackend`) calls `GET /api/settings` before
  `/server_info`; the fixture answers it with its labelled 501, as it does `/api/llm/models/verified`,
  `/api/profiles`, `/api/agent-profiles`, `/api/meta-profiles`, `/api/settings/agent-schema`,
  `/api/automation/sdk-version` and `/api/automation/health` (28 refused requests in all), none of which has a
  catalog answer or a provenance row. Onboarding is shown until Canvas's origin holds `openhands-onboarded` in its
  `localStorage` (`dist/components/features/onboarding/use-onboarding-completion.js`).
- Every other request (281 of 295) was to `127.0.0.1:13330`: the page, its assets, `/locales/en/openhands.json`, `/favicon.svg`
  and `/mars/health` (answered by the static server's own fallback, `MARS_WEB=0`). No fixture answer was 2xx.

Nothing is built on this gate: the engineering route, the frame and the source action wait for the decision on
both conditions.

**Re-run (2026-11-17), the engineering manager's direction after the STOP: STOP again, on rule 4 of that direction
(completing Canvas's onboarding needs a write to the backend).** The rule above is unchanged. What changed:

- *No request can leave loopback.* The browser now blocks, before any page loads, every request whose host is not
  `127.0.0.1` (the DevTools protocol's `Fetch` interception, each blocked attempt logged with its URL, type and
  initiator; a probe to `http://192.0.2.1/` shown blocked first), and sends anything else it tries to a closed
  loopback proxy (`--proxy-server=http://127.0.0.1:9`, bypassing `127.0.0.1` alone). The driver is
  `integrations/agentfixture/tests/browser_cdp.py`; the gate itself is the environment-gated
  `integrations/agentfixture/tests/test_canvas_browser.py`.
- *The fixture's UI face answers Canvas's local-backend check* (a fix-forward of E-01.7's catalog, its rows first):
  `GET /api/settings` (a server that persists no settings, source-derived) and the observed `version` in
  `/server_info` ([the fixture's README](../../integrations/agentfixture/README.md)).
- *The onboarding is passed in the browser, as a user passes it*, nothing written into Canvas's storage from outside.

Observed, the same with the content-security policy option off and on (below):

- Canvas now connects to the backend (its check reads `/api/settings` 200 `ui-settings` and `/server_info` 200
  `ui-server-info`; every fixture 2xx answer is one of those two, both with provenance rows) and shows its onboarding
  with a modal dialog over it, "Help improve OpenHands": "This preference is saved for the local backend", a box
  "Send anonymous usage data" ticked by default, and "Confirm preferences", its only control. It is shown while the
  backend's settings carry no `misc_settings.app_preferences.user_consents_to_analytics` (a server that persists
  none answers none), even with telemetry disabled by upstream's flag.
- Declined as a user would (the box unticked, then Confirm), Canvas sends `PATCH /api/settings` (three times); the
  read-only UI face refuses it (its labelled 501), and the dialog stays. "Skip for now" lies under the dialog;
  clicking it changes nothing. No request for the conversation, its events or its socket was made, so the
  conversation's title and the dispatched message were not shown, and the socket's sync-and-replay behaviour was not
  reached.
- The other start-up reads stay the fixture's labelled 501 (`/api/llm/models/verified`, `/api/profiles`,
  `/api/agent-profiles`, `/api/meta-profiles`, `/api/settings/agent-schema`, `/api/automation/sdk-version`,
  `/api/automation/health`: 20 in all); none is shown to be needed, since the view is never reached.
- *Off loopback, now blocked:* only the probe and Canvas's MCP-catalog logos, images from
  `https://cdn.simpleicons.org/` (`github`, `linear`, `gitlab`, `bitbucket`, `atlassian`, `jira`, `notion`; 31
  attempts with the policy off), every one blocked before it was sent; none got a response. They come from the
  onboarding and home view; whether the conversation view itself attempts any is not known, since it was not
  reached. No WebSocket was opened.
- *The content-security policy option* (`--csp`, off by default; evidence for planning, not adopted): `default-src
  'self'; script-src 'self'` and the sha256 of each of the page's six inline scripts (five of the pinned
  `index.html` and the one upstream's server injects); `style-src 'self' 'unsafe-inline'; img-src 'self' data:;
  font-src 'self'; connect-src 'self' ws://127.0.0.1:13330; worker-src 'self'; object-src 'none'; base-uri 'self';
  form-action 'self'`. With it on, the page made the same 281 loopback requests with the same answers and showed the
  same views; the policy blocked the logo images itself (298 attempts, the browser's own `img-src` violation for
  each; the block saw only its probe), and nothing else: no script, style, connection or worker violation.

## Agent Canvas and assistant-ui in one React app

This is the evidence for the compatibility-matrix row "agent-canvas 1.36.0 /
assistant-ui 0.15.32: Both hosted in one React app", observed with Node 24.19.0
and npm 11.17.0 on Windows 11 x86_64, in jsdom and in the production build.
`src/engineering/canvas-compat.test.tsx`, `canvas-styles.test.ts` and
`canvas-default-i18n.test.ts` record it as tests.

- **Shared React packages.** `npm ls` resolves exactly one copy each of `react`
  19.3.1, `react-dom` 19.3.1, `react-router` 8.5.0, `zustand` 5.0.16 and
  `framer-motion` 12.38.0. Canvas's `dist/` imports only `react`, `react-dom`,
  `react/jsx-runtime`, `react-router` and `framer-motion` as bare modules. It
  ships everything else pre-bundled in `dist/node_modules/`: zustand, TanStack
  Query, i18next, react-i18next, posthog-js, axios and others. So Canvas runs
  its own bundled zustand next to the npm zustand that assistant-ui uses.
  These are two separate store instances, and they do not collide. Both trees
  mount side by side under one router with no invalid-hook-call error.
- **Bundle.** `vite build` succeeds. Canvas is in its own lazy chunk
  (`CanvasMount-*.js`, about 3.2 MB, 1.0 MB gzip, plus `CanvasMount-*.css`, about
  446 kB). It loads only when the engineering area opens. The entry chunk
  (React, react-router, assistant-ui) is about 849 kB (255 kB gzip). The bundler
  reported no collision or resolution error, only its warning about chunks over
  500 kB.
- **CSS isolation.** All 3,459 style rules in Canvas's `styles.css` are scoped
  under `[data-agent-server-ui]`. Its global at-rules are 17 `@keyframes` and 75
  `@property --tw-*` registrations, and it has no `@font-face`. The host stylesheet
  styles only `html`, `body`, `#root`, `:root` and `.owner-*` classes, uses
  `--owner-*` variables, and declares no keyframes or properties, so no global
  name collides. Host content placed inside Canvas's root does receive Canvas's
  scoped preflight.
- **Google Fonts.** Canvas's stylesheet starts with two remote `@import` rules
  from `fonts.googleapis.com` (Outfit, IBM Plex Mono). The host build drops
  remote `@import` rules from that one stylesheet
  (`build/canvas-offline-fonts.ts`), as blueprint UI-01 allows ("bundle or
  override its CSS Google Fonts imports when offline operation is required").
  Canvas then falls back to the other fonts in its font stacks. The built CSS
  contains no `fonts.googleapis.com` reference and no `@import`. The installed
  package is not modified.
- **i18n.** Without a host instance, Canvas builds an i18next instance that
  fetches `/locales/{lng}/openhands.json` from the host's origin. The host
  serves no such file: `vite preview` answers that path with `index.html`. The
  host therefore registers an instance built from Canvas's exported
  `translationResources` (`setI18n`) before Canvas mounts.
- **No backend.** With no backend registered, Canvas stays at its own
  "no backend" state and disables its queries. Its providers, its root and its
  analytics-off telemetry make no request: no fetch, XHR, WebSocket,
  EventSource or beacon was observed.
- **No native not-connected view.** None of Canvas's exported components shows
  a not-connected state. `ConversationPanel` keeps its loading skeleton
  indefinitely, because the conversation query never runs. `Sidebar` needs a
  `SidebarMobileNavProvider` that is not exported. The host therefore states the
  not-connected condition itself and mounts only the providers and root.
- **Session selection (for U-01.2).** `ConversationView` and `ChatPanel` read
  the conversation id from Canvas's internal navigation context, not from
  react-router parameters. Even under a host route
  `/conversations/:conversationId` they throw "useConversationId must be used
  within a route that has a conversationId parameter". The `.d.ts` declares a
  `NavigationProvider`, but the 1.36.0 JavaScript does not export it, and
  `dist/context/` is not in the package's export map. At this version an
  embedded Canvas cannot be given an existing session through its public
  exports. The blueprint's UI-01 fallback is "a standalone Canvas route if a
  version-pinned embed cannot select an existing session". That choice belongs
  to U-01.2 and is not made here. Canvas also navigates to absolute
  `/conversations/...` paths, which a host route table must leave free or map.

## Not yet verified

- **A real browser.** No browser rendered the app. That includes the narrow and
  wide layouts, the CSS grid, the fallback fonts, Canvas's dark theme next to
  the host's colours, focus order and touch targets. The jsdom tests check the
  breakpoint logic (`matchMedia`, `data-layout`, navigation orientation, compact
  identity) but not CSS. `vite preview` on 127.0.0.1 served `/`, `/chat`,
  `/work`, `/engineering` and the built assets with HTTP 200, but no page was
  rendered.
- Any host but Windows 11 x86_64 with Node 24.19.0 and npm 11.17.0.
- Canvas against a real Agent Server, existing-session selection,
  reconnection and history (U-01.2, E-01.x).
- The Owner UI's access to the Agent Server (`fd-owner-ui-access`).
- The sign-in against the running Integration process in a real browser, the
  content-security policy as a browser enforces it, and the Owner's own
  credential (OA-32 (a)). The tests use a fake Integration process.
