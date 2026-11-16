# Owner host

The Owner's single React application (plan leaf **U-01.1**, parent U-01;
blueprint [`#conversation`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#conversation)).
It is a responsive shell with persistent navigation, one session identity, the
Owner chat built on assistant-ui, empty objective and Work surfaces, and Agent
Canvas embedded as a library for engineering sessions.

**One backend, for sign-in only.** Since U-01.3 the shell signs in to the
Integration process ([`integrations/ownerhost`](../../integrations/ownerhost/README.md))
on `http://127.0.0.1:13310`; that is the only request it makes, and only when
the Owner signs in or a stored sign-in is checked. There is still no chat model,
conversation thread, objective source, Work system or Agent Server behind it,
and every surface says so instead of showing sample data.

Commands, prerequisites and verification status: [Owner host](../../docs/development.md#owner-host)
in the development reference.

## Routes

| Path | Area | Renders |
|---|---|---|
| `/` | (none) | Redirects to `/chat`. |
| `/chat` | Chat | assistant-ui's headless primitives over `useLocalRuntime` with a model-free adapter: an empty in-memory thread and a disabled composer. |
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
| `ChatArea` | `src/areas/ChatArea.tsx` | assistant-ui `AssistantRuntimeProvider`, `ThreadPrimitive`, `MessagePrimitive`, `ComposerPrimitive`. |
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
(Proposed), point 4 as amended. The Owner mints the Owner UI session credential,
`cred-owner-ui-session` (`aieh-oui-` and 52 lower-case base32 characters), at his
own console with `task ownerhost:enroll`, and pastes it into `/sign-in`.
[`src/identity/owner-session.ts`](src/identity/owner-session.ts) holds the rules:

- The pasted value is checked for the shape first (nothing is sent otherwise),
  then verified with `POST /session`; only a verified credential is kept, as
  one record under `aieh.owner-host.owner-ui-session` in this origin's
  `localStorage` (the origin is scheme, host and port, so another loopback
  listener cannot read it), with the session's public id and expiry. The field
  is emptied after each attempt.
- Every request to the Integration process goes through one client: to
  `http://127.0.0.1:13310` only, a path and never a URL, with the
  `X-AIEH-Owner-Session` header, `credentials: "omit"` (never a cookie),
  `redirect: "error"` and no referrer.
- A stored copy is checked once when the shell opens (the browser may have been
  closed and reopened). A refused credential (`SESSION_CREDENTIAL_FOREIGN`,
  `_EXPIRED`, `_REVOKED`) removes the copy; an unreachable process keeps it.
- "Sign out" removes the copy. The service's expiry bounds it either way.

A process of the Owner's account that reads the browser profile can read the
copy: inside decision 0010 point 1's disclosed same-account limit.

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
