# 0023 - The native Claude Code execution profile: native authentication, the provider tunnel, and the broker as an optional profile

Status: Accepted (product manager) - 2026-11-14, under decision 0018 points 1 and 3.1, with the Owner's direction of 2026-11-14 (below) as its basis: it changes scope, criteria and the contract between leaves on D1's path, each departure from Owner-accepted text reached by that direction, and it routes every reserved act to the Owner (section 8). Accepting it authorizes none of them. Drafted by the program manager for the product manager, on the Owner's direction of 2026-11-14 ("Owner direction: reconcile D1 for isolated, native Claude Code execution", verbatim in `evidence/bootstrap-log.md`, Decisions, anchor `owner-direction-native-d1-2026-11-14`), from the architect's consultation of the same day (gates A, C and G), whose findings this record states. It authorizes no reserved act: entering the token, its delivery to any attempt, the tunnel's egress, the forward's new target and every model call stay the Owner's, presented as Owner action OA-31 (section 8). Decision 0015 amendment 3 and decision 0021 amendment 2, which scope those records to the brokered profile, take effect with this record's acceptance and not before.

**Authority:** the Owner's direction of 2026-11-14 (above), which reads in part: "Run the unmodified Claude Code application.", "Use a provider-supported native authentication method.", "Permit the isolated Claude Code process to access its own authentication credential.", "Do not expose unrelated host credentials, host management interfaces or durable host state.", "Accept the limited risk associated with an isolated coding agent having its own provider credential.", "Do not intermediate subscription credentials through our inference broker.", "The inference broker remains an optional execution profile, not a mandatory dependency for native Claude Code execution.", "Keep existing correctness, containment and credential protections that are necessary for the chosen profile. Remove redundant requirements inherited from the brokered profile." and "Do not introduce another comprehensive security qualification program."; the Owner's clarification of 2026-11-14 (anchor `owner-clarification-native-auth-2026-11-14`); the engineering manager's answer (anchor `native-auth-path-2026-11-14`); decision 0018 points 1, 2, 3, 4.1, 4.7, 4.8, 5 and 7; within decisions 0003, 0006, 0009, 0010, 0011 (F-06.3) and 0013.

**Gate:** architecture consultation at gates A (the authentication method at the pins), C (a durable decision no record settles: a second execution profile and what it keeps) and G (a credential in a disposable guest; a new egress origin; custody).

**Supersedes:** none. It scopes decisions 0015 and 0021 to the brokered profile, by their own amendments (0015 amendment 3, 0021 amendment 2), and changes no other accepted record's text. Decisions 0003, 0007, 0013 and 0022 are unchanged; where this record names a consequence for their records, the plan leaf that changes them is named.

## Context

- The Owner paused the dedicated API key (OA-12 acts 1 and 2) and asked for the existing Claude Code authentication (anchor `owner-direction-pause-api-key-2026-11-14`), then directed native execution with the coding agent holding its own provider credential, the broker kept as an optional profile (the direction above).
- The provider's own rule, as the engineering manager recorded it on 2026-11-14 (anchor `subscription-auth-evaluation-2026-11-14`, `legal-and-compliance` read that day): subscription OAuth "is designed to support ordinary use of Claude Code and other native Anthropic applications"; "developers may not collect, store, or intermediate Claude.ai credentials or session tokens"; permitted: "an end user ... signing in to the unmodified Claude Code binary with their own Claude subscription". So the broker cannot hold a subscription credential; the credential belongs in the client.
- At the pins (the architect's reading, 2026-11-14): interactive login into a persistent store is provider-supported, but not reachable by configuration. The pinned OpenHands docker runtime gives only per-conversation mounts (`registry.py:620,668-673`); `ACPAgent`'s `acp_isolate_data_dir` overwrites `CLAUDE_CONFIG_DIR` (`acp_agent.py:2756-2762`); guests are disposable and have no host share (profiles P3, P4, P10). Seeding a copy of a refreshable login is worse on custody (a refresh token in every guest) and on concurrency (two attempts refreshing one login).
- The provider's long-lived token (`claude setup-token`, run through Anthropic's own flow) is documented for use as `CLAUDE_CODE_OAUTH_TOKEN` in a container. With it present, the pinned SDK strips `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` (anchor `native-auth-path-2026-11-14`), so the unmodified Claude Code talks to the provider itself.
- The SDK masks every secret value in agent output by substring (`acp_agent.py:3062`; `secret_registry.py:314-321,370-396`): a secret whose value is `1` or `true` would mask those strings everywhere in the agent's events.
- The guest side of S-03.2's composition (one sshd `PermitListen`, one container-guard ACCEPT, an empty egress allowlist, DNS refused) carries one forward to the host. Its holder accepts only the broker's inference port today (`FORWARD_PORT_REFUSED`, `BROKER_NOT_READY`; `evidence/S-03.2-slice3-forward-session.md` section 1). Two catalogue cases expect the broker: `ctl-inference-endpoint` (a 401 without a token) and `egr-inference-guest-login` (`TOKEN_MISSING`); the full catalogue FAILs on a guest without the inference composition (anchor `s-03-2-inference-cases-2026-11-14`).

## Considered options

1. **Interactive login into an isolated persistent volume** (the Owner's stated preference). Supported by the provider; at the pins it needs the per-conversation configuration isolation overridden and a store writable by every attempt that persists settings and hooks across attempts, with refresh egress to a second origin. **Deferred** (section 2.3).
2. **A copy of the Owner's existing login seeded into each guest.** Rejected: a refresh-capable credential in every guest, refreshes racing between attempts, and the host Claude configuration as its source, which the direction excludes ("Do not expose unrelated host credentials ... or durable host state").
3. **The broker holding a subscription token.** Rejected: the provider rule above, and the direction ("Do not intermediate subscription credentials through our inference broker").
4. **The provider's long-lived token, entered once by the Owner and delivered natively to each attempt.** **Chosen**, with the guest side unchanged and the forward ending at a host tunnel that holds no credential.
5. **A TLS-intercepting proxy** (to keep the broker's request rules). Rejected: it would decrypt the Owner's subscription traffic on the host, an intermediation of the credential's use, and a new trust root in every guest.

## Decision

### 1. Two execution profiles

1. **Native** (D1's profile): the unmodified Claude Code authenticates with its own provider credential; no broker is involved. This record governs it.
2. **Brokered** (optional): decisions 0015, 0021 and 0022 as amended, the built broker and its qualifications (S-03.2, S-03.3, S-03.5, S-03.6, E-05.6, E-05.7), kept as built and not a prerequisite of the native profile. The recorded OA-12 act 3 stands for it; acts 1 and 2 stay paused.
3. A stage's profile is declared in its execution profile; a create mixing the two profiles' secret sets is refused (plan leaf E-05.9).

### 2. Authentication and custody

1. **Method:** `claude setup-token`, run by the Owner on the host through the provider's own flow, delivered to each attempt as `CLAUDE_CODE_OAUTH_TOKEN` in the D1 create's `secrets` (a `StaticSecret`).
2. **Custody (F-06.3's form):** one host credential-provider entry, written only by a harness command that reads the token at a hidden prompt (never argv, environment, file, `config.yml` or the host Claude configuration), with a receipt that carries its fingerprint only. The dispatcher reads that entry, and no other, only at a D1 create after every other input is admitted. No record, report or log carries the token; records carry its fingerprint. It is a new, separate credential: never `cred-owner-provider-login`, never the host `~/.claude`.
3. **Deferred:** interactive login into isolated persistent storage. Reconsider when the execution runtime can mount a per-profile persistent credential store, or when a run is made on a non-disposable profile (the plan's `deferred` list).

### 3. Run shape (unchanged)

OpenHands `ACPAgent`, `claude-agent-acp` 0.63.0, the Agent SDK, and the published `claude` 2.1.220 binary bundled in the pinned image, hash-identical to the release, with the same D1 create template (E-05.2's digest binding). The native secret set is exactly four names: `CLAUDE_CODE_OAUTH_TOKEN`; `HTTPS_PROXY`, equal to the profile's tunnel endpoint `http://172.17.0.1:<port>`; `CLAUDE_CODE_PROXY_RESOLVES_HOSTS`; and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`. The two switches take declared, collision-free spellings, never `1` or `true` (the masking trap above). No second authentication method (`ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`) is set: CLI 2.1.220 predates 2.1.225. The per-conversation, empty configuration directory is kept; the command is the pinned `claude-agent-acp`; no MCP configuration and no custom ACP server is admitted.

### 4. Egress

1. **The guest side stays byte-identical** to S-03.2's approved composition: one sshd `PermitListen`, one container-guard ACCEPT, an empty egress allowlist, DNS refused. The completed isolation evidence (decision 0003, P1-P10; S-02.2) is reused.
2. **The forward ends at a host loopback CONNECT-only tunnel.** It admits exactly `api.anthropic.com:443`; it refuses IP literals, plain HTTP and every other host and port; it checks that the TLS ClientHello's server name equals the CONNECT host; it holds no credential, decrypts nothing, and logs each target and decision, never payload. An established proxy is adopted where one meets every clause at a pin; otherwise a minimal owned tunnel, the choice recorded (plan leaf E-05.10).
3. **The forward holder** admits the tunnel's port for a profile that declares the native profile, and keeps refusing every other port; the forward is held only while an attempt needs it.
4. **Records:** the network matrix classifies the native path, profiles P7 and the profile declare the tunnel endpoint, the security inventory names its listener, and `ctl-inference-endpoint` and `egr-inference-guest-login` gain native expectations with a per-guest applicability rule (E-05.10). The credential class enters profiles P5, the security inventory and the role-token matrix (E-05.9); decision 0007 points 4 and 5 and `policy/role-tokens.json` describe the brokered profile's inference access, and the role-token checker's refusal of a provider credential to an agent role stays in force for every other credential.

### 5. What the native profile keeps, and what it does not inherit

| Kept (necessary for the native profile) | Where |
|---|---|
| Decision 0003 / P1-P10 isolation, S-02.2's evidence reused | E-05.10 (its catalogue re-run) |
| Guest egress denied but for the one endpoint; the forward held only while needed | E-05.10 |
| The tunnel's allowlist and server-name check | E-05.10 |
| No host `~/.claude`, `cred-owner-provider-login`, `cred-owner-github` or other host credential in a guest | E-05.11, E-05.5 |
| Host custody in F-06.3's form, fingerprint-only records | E-05.9 |
| An outbound search for the token on what leaves the guest (result bundle, records, reports), in memory, counts only, with a positive control | E-05.9 (the tool), E-05.11 and E-05.5 (its runs) |
| Create admission: the exact secret names, static secrets, the pinned command, no MCP, the per-conversation configuration directory | E-05.9 |
| Process containment (S-03.3's containment clauses) | E-05.11 (S-03.3 keeps them) |
| The assigned repository only; the result through the exchange; no bot merge | E-05.4, E-05.5 (unchanged) |
| Model identifiers verified, recorded, presented, never wildcard | E-05.11 (section 7) |

| Not inherited (redundant for the native profile) | Kept for the brokered profile in |
|---|---|
| Per-attempt inference-token issue and revocation | 0015 section 3, 0007 point 4, E-05.6, E-05.8's text before 2026-11-14 (a deferral) |
| The route and model allowlist bound to the envelope | 0015 section 5.3, 0021 section 5, S-03.3, S-03.5 |
| The real-key absence search inside the guest | S-03.3 (R1) |
| The provider-envelope start precondition | 0021, S-03.5 |
| The envelope authorization repository's use | 0022, E-05.7 |
| The broker's listeners, dedicated key and egress | OA-12 A1, A2, A5 |
| The broker's audit as the model-call evidence | 0015 section 6 |
| The broker plane's live qualification | S-03.2 |
| "The base URL is honoured" | S-03.3 (R6) |

### 6. Lost, and the residuals

1. **Lost, not redundant:** the broker's refusal of provider-side tools, MCP servers and URL sources cannot exist behind end-to-end TLS. OA-12 listed them as "stays unauthorized". This is disclosed to the Owner as a residual with OA-31 (a); a native control for it is a deferral of the plan.
2. **Residuals:** the token is readable by every process of the attempt and by guest root; it is valid up to a year and is not bound to an attempt; while a forward is held, every guest process, not only the attempt's container, can open a TLS connection to the provider's origin through the tunnel (the tunnel holds no credential, so this reaches the provider only with a credential the process holds); the tunnel's allowlist is enforced in its own code on the host, as the broker's egress was (decision 0013 point 6); same-account host processes can read the entry (decision 0010 point 1); prompts, completions and the demo repository's content go to the provider under the subscription's terms. A token suspected exposed is revoked by the Owner at the provider and replaced by a new entry (OA-31 (e)).

### 7. Model identifiers

Decision 0018 point 3 delegates model selection inside an envelope on the condition that "the broker admits only the recorded identifiers". The native profile has no broker, so that delegation does not apply to it as written, and the Owner's decisions on OA-05 and OA-12 of 2026-11-10 govern: the exact identifiers, including any secondary model Claude Code uses, are verified against current provider information, never assumed from memory and never a wildcard, recorded by the engineering manager with their intended uses and expected usage characteristics, and **presented to the Owner for approval** before the first model call (OA-31 (c)). The admitted create template pins the primary model by digest (E-05.2); a secondary model is pinned through the admitted create where the pinned CLI accepts it, otherwise disclosed. Extending point 3's delegation to a template-pinned selection would change decision 0018 and stays the Owner's (point 4.8).

### 8. Reserved acts (Owner action OA-31, each separately answerable)

(a) the standing authorization of the native path: the forward's new target, the tunnel's listener and its egress to `api.anthropic.com:443` (decision 0018 point 4.7), with the residuals of section 6 disclosed; (b) the new credential class in disposable guests (point 4.7; the Owner's standing guest authorization excludes model credentials); (c) D1's model calls billed to the Owner's subscription, with the model identifiers of section 7; (d) the Owner's reading of the provider's terms for an Agent-SDK-launched, unmodified binary on the Owner's own subscription; (e) the act itself: the Owner runs `claude setup-token` on the host and pastes the token at the hidden prompt (point 4.1); (f) the token's delivery to attempts. Delivering an Owner or provider credential into an attempt exposes it (point 4.1), and point 5 makes point-4.1 acts never standing: each delivery is therefore an Owner act per attempt, unless the Owner, under point 4.8, amends point 5 to admit this one class as a standing authorization with its conditions, stops and expiry. The prepared presentation is in the bootstrap log (OA-31).

**Mechanism.** None of these acts needs the authorization recorder: no harness component's start is bound to them as the broker's start was (decision 0021), and no new binding is introduced. (a) is consumed as the network matrix consumes an `owner_act` edge, by its `owner_approval` quote; (b) to (d) and (f) are verbatim log records; (e) is the Owner's own act, whose receipt carries the fingerprint. Decision 0018 point 7's limit applies and is disclosed: a log quote is checked for presence, not authorship.

## Consequences

- Plan (the amendment of 2026-11-14, through the integrity process): new leaves E-05.9 (the native token's custody and the D1 stage's native create secrets), E-05.10 (the tunnel, qualified with no credential) and E-05.11 (native Claude Code qualified in the execution container); E-05.2 depends on E-05.11 instead of S-03.3; E-05.5 on E-05.11 and E-05.9 instead of S-03.3 and E-05.6; E-05.8 re-scoped to the native profile; the E-05 gate names E-05.8 to E-05.11 in place of E-05.6 to E-05.8. S-03.2, S-03.3, S-03.5, S-03.6, E-05.6 and E-05.7 leave D1's path unchanged.
- Decision 0015 amendment 3 and decision 0021 amendment 2 scope them to the brokered profile; 0015 amendment 1 item 7's boundaries apply to every profile, the native token excepted.
- `profiles/README.md` P5 and P7, `profiles/properties.json`, the profile declaration, `policy/network-matrix.json`, `security/inventory.json`, `policy/role-tokens.json`, `security/containment-cases.json` and the forward holder change at E-05.9 and E-05.10, each with its checker.
- The blueprint's `#containment-architecture` threat row "Provider CLI requires authentication token" prefers "trusted inference proxy or truly scoped short-lived token, not Owner credentials in agent-readable env/files". The native profile departs from that preference on the Owner's direction; reconciling the blueprint's text is the plan's deferral, by the authority-class process on the Owner's direction, and is not on D1's path.

## Not decided here

The tunnel's port and implementation (E-05.10); the switches' exact spellings (E-05.9); the model identifiers (the engineering manager, presented under section 7); any answer of OA-31.

## Not verified

Everything live: the CLI's behaviour with only `CLAUDE_CODE_OAUTH_TOKEN` from an empty configuration directory, its traffic through `HTTPS_PROXY`, the hosts it contacts with the switches set, what it persists, and the masking of the switch values in events (E-05.11). The source lines in Context are the architect's reading at the pins, stated here and not re-read for this record. The provider's terms are quoted from the engineering manager's record of 2026-11-14; the Agent SDK overview's sentence on subscription sign-in is not in the repository's records and is quoted from the current page when OA-31 (d) is presented.
