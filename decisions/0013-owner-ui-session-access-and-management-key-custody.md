# 0013 - Owner UI access to engineering sessions and the sole custody of the Agent Server management key

Status: Accepted (Overseer) - 2026-11-07, at the completion of S-01.4 (`d084b8d`, `8cea7fb`, fix-forward `bb72b8b`, `ecd3bf5`). It names no host-to-guest path as open; each one still needs a recorded Owner approval at the leaf that first needs it. Point 6 applies the blueprint's `#security` and `#containment-architecture` text read with decision 0010 s1, and does not amend 0010. Proposed (Architect draft, 2026-11-07).

It refines [decision 0007](0007-role-token-matrix-and-revocation-contract.md), points 4 and 5, within blueprint `#architecture` ("Selected boundary"), `#integration-contracts` ("API admission is mandatory") and `#execution-qualification` ("Must be reachable only from the dispatcher and trusted Owner UI, never arbitrary code or tools"). 0007 stays Accepted, and its text is unchanged.

It changes no guest boundary. Every host-to-guest path it names stays deferred until the Owner approves it.

Supersedes: none.

## Context
- The Agent Server's one session key admits every key-gated route (S-01.3.1; `fd-session-key-not-fine-grained`).
- The blueprint lists the trusted Owner UI beside the dispatcher as a legitimate caller of the management API. It requires Agent Canvas to access only the backend an Owner-authorized session needs, and it forbids assuming the session key is fine-grained.
- No record said which credential the UI holds (`fd-owner-ui-access`).
- At the pins:
  - the outer server mints per-conversation runtime credentials (`POST /api/conversations/{id}/runtime/credentials`, key-gated);
  - Canvas 1.36.0 connects per conversation (`conversationUrl`, `sessionApiKey` per call; `dist/api/agent-server-client-options.js`).

  The response shape and Canvas's registration API are verified at U-01.2, not here.

## Decision
1. **The management key is held by the trusted dispatcher alone.** No browser, UI process, Integration process or agent ever holds it. During bootstrap the Owner's account performs the dispatcher's role through `tools/guest.py` (unchanged).
2. **The Owner UI reaches an engineering session only with that conversation's runtime credential.** The credential:
   - is issued per session by the dispatcher, from the outer server's runtime-credentials route;
   - is bounded to that conversation and to the Owner's session;
   - is never stored in a record, log or repository.
3. **Transport.**
   - The dispatcher's management calls and the UI's conversation connections both use the qualified management channel: the loopback-bound SSH forward, with a per-instance key.
   - A UI connection is a dispatcher-owned local forward bound to host `127.0.0.1`, pointing at the conversation's published guest-loopback port, and it lives no longer than the Owner's session.
   - A QEMU `hostfwd` of the management listener is not adopted.
4. **Every such forward is a new host port.** It is opened only after a recorded Owner approval (`op-guest-boundary-change`), requested by the leaf that first needs it (U-01.2 or E-01.3.x), never by S-01.4.
5. **The UI's credential to the Owner-host/Integration process is a separate Owner session credential**, not shaped like an Agent Server key. Which leaf builds it is unsettled (plan silence, carried).
6. **Same-account scope on the host network plane.**
   - Same-account host processes are outside the threat model on the host network plane too. This applies blueprint `#security` ("If both processes run with the Owner's unrestricted shell permissions, two API tokens or localhost ports do not create an isolation boundary") and `#containment-architecture`, read with [decision 0010](0010-effects-store-placement-and-governance-threat-model.md), point 1. It does not amend 0010.
   - Host-internal edges are separated by credential entry and code path, and are disclosed rather than prevented.
   - The enforced boundaries are:
     - host to guest: SLIRP `restrict=on`, `ipv6=off`, the loopback-bound forward and the per-instance key;
     - guest to containers: the container guard, the egress guard, `icc` off, loopback-only listeners and keys;
     - Gitea's permission model.
7. **Git plane.** Untrusted code has no network path to Gitea. Proposals leave by exchange (profiles P4), and the dispatcher pushes as the bot identity it holds custody of. 0007 point 4's "delivered into the attempt environment only" means the dispatcher's attempt context, never the conversation container. This is consistent with S-01.3.2's verified token rule.

## Consequences
- `cred-owner-ui-access` splits into two planned credentials:
  - a UI-to-Integration session credential (`cred-owner-ui-session`);
  - a per-conversation runtime credential issued by `management-dispatcher` (`cred-conversation-runtime-access`).
- `fd-owner-ui-access` moves from unknown to planned, carried to U-01.2 and E-01.3.1.
- The dispatcher's realization gains "sole network path to the management API", verified at E-01.3.2.
- **Residual, disclosed:** the UI and the conversation's agent share a conversation-bounded credential, which the agent can already read in its own container. A UI compromise is bounded to that attempt.
- **Not decided here:**
  - the exact forward mechanism (E-01.3.x);
  - Canvas's host-side registration (U-01.2);
  - the CI runner's reachability to a loopback-only Gitea (Q-02.1, Q-02.2.1). The guestfwd chardev is one stream, and an Owner act is needed.

## Evidence
- The Architect's S-01.4 consultation (gates C and G), as accepted by the Overseer on 2026-11-07 with rulings R1 to R9.
- [`policy/network-matrix.json`](../policy/network-matrix.json) and `python -I -B tools/check_network_matrix.py` (`task policy:network-check`).
- [`evidence/S-01.3.1-management-api-admission.md`](../evidence/S-01.3.1-management-api-admission.md), [`evidence/S-01.3.2-job-daemon-and-management-access.md`](../evidence/S-01.3.2-job-daemon-and-management-access.md) and [`evidence/S-01.4-network-matrix.md`](../evidence/S-01.4-network-matrix.md) (S-01.4).
- Decisions [0003](0003-execution-guest-providers-and-isolation-contract.md), [0006](0006-guest-provisioning-channel-and-image-conformance.md), [0007](0007-role-token-matrix-and-revocation-contract.md) and [0010](0010-effects-store-placement-and-governance-threat-model.md).

## Current facts (2026-11-11, OA-20 and E-01.3.3)

Recorded by the Overseer after the Owner's approval of OA-20 (2026-11-11, verbatim in
[`evidence/bootstrap-log.md`](../evidence/bootstrap-log.md)). No text of the decision above changes.

1. **Point 1, the bootstrap reading as written.** During bootstrap the dispatcher principal is the Owner's
   account acting through the dispatch module, which reaches the guest through `tools/guest.py`'s `GuestApi`
   as the `agent` login. A host identity distinct from the Owner's account is not built. The Owner deferred it
   on 2026-11-11: "Do not introduce a separate dispatcher OS account or another guest login under this
   approval. That architectural decision remains deferred."
2. **Point 6 still governs the disclosure.** Same-account access to the host-held credentials remains
   disclosed, and is not represented as independent isolation.
3. **Point 7 and decision 0007 Amendment 1.** The standing Gitea bot credentials stay on the trusted host. The
   dispatcher borrows a stage's credential into its own in-memory attempt context for a confirmed attempt and
   releases it at the end; release is not revocation. A standing bot credential never enters a guest, an agent
   environment, a conversation or the UI (the UI clause of point 1 read as covering every credential of that
   class, not only the management key).
