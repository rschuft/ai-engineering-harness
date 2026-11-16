# 0025 - The Integration process, the Owner UI session credential and the Owner conversation store

Status: Accepted - 2026-11-16, by the engineering manager (decision 0018 points 1 and 3.1), at leaf U-01.3's verdict;
points 3 and 4 corrected at acceptance after the independent review (evidence: the log entry
[`u-01-3-verdict-2026-11-16`](../evidence/bootstrap-log.md#u-01-3-verdict-2026-11-16)). It authorizes no reserved act.
Previously: Proposed - 2026-11-16, for plan leaves U-01.3, U-02.1, U-02.2, P-01.3, P-04.4 and U-04.1 (architect,
gates C and G), with point 4 as amended by the engineering manager's rulings of 2026-11-16 (decision 0018 point 3.1).

**Authority:** the I1 commitment ([`evidence/bootstrap-log.md`](../evidence/bootstrap-log.md#commitment-i1-2026-11-16));
decision 0013 points 1, 5 and 6; decision 0012 points 4 and 9; decision 0008 point 2; decision 0018 points 3.1, 4.1,
4.3 and 4.7; within decisions 0009 (the managed data root), 0010 point 1 (the same-account limit) and 0011 (the
host-service lifecycle); blueprint `#conversation` (UI-02) and `#architecture`.

**Gate:** the architect's work design for I1 (gates C and G), with the engineering manager's rulings
([`evidence/I1-integration-design-2026-11-16.md`](../evidence/I1-integration-design-2026-11-16.md)).

**Supersedes:** none. It refines [decision 0013](0013-owner-ui-session-access-and-management-key-custody.md) point 5
(the credential it names is defined here) and changes no accepted record's text.

## Decision
1. **Form.** The Integration process is a Python ASGI service (Starlette on uvicorn, at the versions the component
   lock pins), `integrations/ownerhost/`, run under the tools interpreter, bound to host `127.0.0.1` on one fixed
   declared port (13310, declared in the network matrix and the host census). It has decision 0011's service verbs
   through the platform contract and no install, upgrade or credential verb. Its data are under the managed root's
   state and logs categories.
2. **What it never does.** It opens no outbound connection and has no path to an Agent Server; it is custodian of no
   credential; it imports no credential, Gitea, authorization-recorder or dispatch-transport module; it has no
   dispatch endpoint.
3. **The credential.** `cred-owner-ui-session` is one random secret, minted by the `enroll` command for the Owner
   to run at his own console, which shows it once; the command refuses plain pipes and redirected handles, but
   cannot tell the Owner from a process of his account that drives a console or pseudoconsole, calls the library or
   writes the store (decision 0010 point 1), and each such enrollment supersedes the Owner's session, which then
   answers `SESSION_CREDENTIAL_REVOKED` at his next request unless a same-account writer of the store undoes it
   first. The store keeps a verifier, the session's public id and its expiry; one session is current. Its shape is
   its own (prefix `aieh-oui-`).
4. **Presentation.** The credential is sent in a request header on every request and is never a cookie. No route
   answers without it, except the CORS preflight. Host and Origin are checked against literals. The Owner UI shell
   keeps its copy in its own origin's `localStorage`, not `sessionStorage`: the origin is scheme, host and port, so
   a listener on another port cannot read it, while a process that holds the shell's own port while the shell is
   down is that origin and can (inside decision 0010 point 1 for the Owner's account, a disclosed residual for
   another local account; Vite's strictPort then refuses to start, a visible signal). "Sign out" removes it, and the
   service-side expiry bounds it.
   (Amended by the engineering manager: U-06.1 item (7) closes and reopens the browser during and after execution,
   and `sessionStorage` would make the Owner re-enter his credential at each reopen, an avoidable Owner interaction;
   the Owner directed that his interactions be consolidated.)
5. **Refusals:** `SESSION_CREDENTIAL_MISSING`, `_FOREIGN`, `_EXPIRED`, `_REVOKED`; `HOST_NOT_ALLOWED`;
   `ORIGIN_NOT_ALLOWED`. Each changes nothing.
6. **The Owner conversation store** is a store kind of its own under the managed root, the lineage authority for the
   `conversation` and `message` kinds, written only by the Integration process (and, for sessions, by `enroll`). The
   thread id is the store's; the message id is assistant-ui's native id, unique per thread; order is the store's
   sequence; a user message is immutable and its bytes, kept as received, are the durable source of every quote; an
   edit is a new message; nothing is deleted.
7. **Host-internal listeners.** A listener of the Owner's account that binds `127.0.0.1` on a declared port, is the
   target of no forward or profile endpoint, makes no outbound connection and holds no credential is recorded in the
   network matrix and the security inventory before it first listens and is not an Owner act. A listener that fails
   any of the four is one (`op-guest-boundary-change`, or decision 0018 point 4.7).
8. **Writes on the Owner's authenticated request.** Exactly two: one intent change per message (P-01.3), and the
   acceptance recorder's commit (P-04.4). Each names server-held ids only, is idempotent by its key, and has a
   write-ahead receipt in the integration store.
9. **The `owner-ui` channel.** The acceptance recorder admits it only with a session binding verified in process: the
   statement is a user message of the session that makes the request, read from the store. The command line cannot
   declare it. The authorization recorder and the dispatch-input commands admit `main-session` only, as before.
10. **The projection** is read-only and takes execution state from the dispatcher's receipts.

## Consequences
- `fd-owner-ui-session-plan-silence` is answered by U-01.3; the matrix, inventory and role-token records are
  corrected there.
- `fd-owner-authorization-record` is narrowed for objective acceptance (an authenticated session), not closed: a
  process of the Owner's account can replace the verifier (decision 0010 point 1).
- The shell's copy of the credential is in the browser profile's `localStorage`. A process of the Owner's account
  that reads the browser profile can read it: this is inside decision 0010 point 1's disclosed same-account limit, as
  the verifier's replacement is.

## Not decided here
Passkeys; a separate host identity for the service; backup and restore of the conversation store; the Owner chat's
model backend (deferred by the plan); live session access (U-03.1).

## Not verified
Anything live with the Owner's own credential (OA-32); Linux and macOS.
