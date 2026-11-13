# Authorization package: provider access for D1 (OA-12 with OA-22 (a), (b), (c), (e))

Prepared 2026-11-13 by the engineering manager, at `27b0f40`, under the Owner's [direction on provider access](bootstrap-log.md#owner-direction-provider-access-2026-11-13). Nothing below has been performed. This page is complete on its own. It replaces, for presentation, the [S-03.1 request](S-03.1-owner-authorization-request.md): where they differ, this page is current.

**One decision for the Owner:** approve or reject the package in section 1. Everything else here is the engineering manager's own decision, or a disclosure.

## 1. What the Owner is asked to approve

| # | Act | Exactly |
|---|---|---|
| P | **Provider and origin** | Anthropic's first-party Claude API. One origin, `https://api.anthropic.com:443` (TLS, the host's system roots). It is used only through the inference broker, with one route: `POST /v1/messages`, with no query string or with exactly `beta=true`. Only the form observed at S-03.3's discovery run is pinned. Every other path, query and destination stays refused. |
| A1 | **The provider key** | One dedicated Anthropic API key that you create for this harness. Create it in a dedicated Console workspace, for example `aieh-harness`, so it is single-workspace and revocable on its own. It is not your personal key and not your Claude Code login. You enter it once, in your own console window, by pasting it at a hidden prompt of one harness command. It is stored in Windows Credential Manager under `AIEH model provider`, and the harness records only its fingerprint. Never paste it into a conversation, a file or a chat. |
| A2 | **The broker's two listeners** | The broker runs as your Windows account, as a foreground process that the engineering manager starts for each live step and stops afterwards. It is not a service. It has two listeners: `127.0.0.1:18431` (control: issue and revoke attempt tokens; host-only, never forwarded) and `127.0.0.1:18432` (inference). It needs no administrator rights, no firewall change and no LAN exposure. |
| A3 = OA-22 (b), (c) | **One guest-to-host path** | For each disposable guest created for inference, the existing SSH management channel carries one remote forward: the guest's `172.17.0.1:8090` to the host's `127.0.0.1:18432`. It adds no new host listening port, no QEMU change and no `guestfwd`. It exists only while the harness holds the session. It serves two edges: `nm-job-inference` (containers) and `nm-guest-inference` (the guest's own processes: disclosed, with the token as the only control). |
| A4 = OA-22 (e) | **Guest hardening change** | It applies only to disposable guests created with `--inference`. The guest's sshd allows remote forwarding to `172.17.0.1:8090` only (`AllowTcpForwarding remote`, `GatewayPorts clientspecified`, `PermitListen 172.17.0.1:8090`; local forwarding stays refused). The container guard gets one ACCEPT, docker0 to `172.17.0.1:8090/tcp`. Moby is pinned to `bip 172.17.0.1/16` and `dns 172.17.0.1`, so a container's DNS lookup is refused by policy. The egress allowlist stays empty. The full containment catalogue is re-run, and every case must pass. |
| A5 | **Host egress** | The broker's outbound connections go to that one origin only, plus the host's DNS lookup of `api.anthropic.com`. The broker sends no telemetry and makes no price or update checks. |
| A6 + D1 | **Model calls** | The first call (S-03.3: one disposable guest, one conversation, a fixed one-word prompt, no repository content), then D1's own calls through the broker (E-05.5's contained coding conversation, which works only on the demo repository named under OA-25). The model-call wording of OA-22 (g) is to be reconciled by planning into this approval, so that D1 needs no further model-call decision. |

**Validity:** the authorization's `expires_at` is set to `2027-01-31T23:59:59Z`. This is a security validity window, set by the engineering manager, not a spending term. An earlier end is a stopped broker, a revoked key or a superseding authorization.

**Your acts after approval (three):**
1. Create the key at the provider.
2. Run the one key-entry command in your own console window.
3. Reply once to the authorization recorder's challenge, by naming its operation id, when the exact envelope manifest is shown to you.

Act 3 is the protected-merge record that the broker checks before it ever reads the key (decisions 0012 and 0021). It is shown together with the final manifest. It cannot be given today, because the manifest's form waits on the planning reconciliation in section 6.

**Not asked:** a budget, a spending limit, an expiry or an enforcement mechanism (per the direction). Whatever your provider account already imposes (credit balance, organization or workspace limits, rate limits) applies. When it interrupts execution, the harness stops cleanly (section 4).

**Stays unauthorized:**
- any other provider, origin, route, port, forward or guest relaxation;
- any provider-side tool, MCP connection, URL fetch or hosted execution (section 3);
- the review-role edge `nm-review-inference`;
- repository content anywhere except E-05.5's demo repository (under OA-22 (f), (h), (i) and (j), presented at their leaves);
- any other credential of your account;
- any change to Windows, WSL2, the host firewall or services.

## 2. Model selection (the engineering manager's, presented, not for approval)

Selected under decision 0018 point 3 (`selection: delegation`; recorded with `task owner:select-models` once the envelope receipt exists). Verified 2026-11-13 against the provider's live documentation (models overview, pricing, model deprecations).

| Use | Model id | Price per million tokens (input / output; cache write 5 min / cache read) | Status | Why |
|---|---|---|---|---|
| **Primary.** The coding agent's main loop and its sub-agents | `claude-sonnet-5` | $2 / $10; $2.50 / $0.20 | Active; retirement not sooner than 2027-06-30 | Strong coding model at the lowest Sonnet price. The pinned Claude Code (CLI 2.1.220, built 2026-07-24) predates Sonnet 5.5 (September 2026) and Haiku 5.5 (October 2026), so models the pinned client knows avoid request-shape failures. |
| **Secondary.** Claude Code's background tasks (with an API key it sends them to its default Haiku model) | `claude-haiku-4-5`, its exact form as observed at S-03.3's discovery run (`claude-haiku-4-5` or `claude-haiku-4-5-20251001`) | $1 / $5; $1.25 / $0.10 | Active; no deprecation notice (the provider gives at least 60 days) | The model the pinned client names. Refusing it would break background calls. |

**Expected cost (an estimate, not a budget):**
- S-03.3's first call: about $0.10 to $0.30.
- E-05.5's coding conversation: about $2 to $8, assuming 50 to 150 requests, mostly cache reads.
- D1 in total: tens of dollars at most, unless runs are repeated.

The account's own limits are the only spending stop (section 4).

**Verified availability:** the provider documentation lists both ids as active today. Availability to your account is shown by the first call, and a refusal there stops the run with nothing done. A later change of models inside this envelope is a new selection record of the engineering manager's, presented again before use, not a new Owner decision.

## 3. What is mechanically enforced, and what is assumed

**Enforced in code** (offline tests now; live evidence comes at S-03.2 and S-03.3):
1. The provider key is read only by the broker, and only after the start precondition passes. It never enters a guest, a record or a log (searched raw and encoded, with a positive control).
2. The broker refuses to start toward the provider unless the integration store holds your confirmed, unexpired authorization receipt for exactly this provider, origin and manifest.
3. Every request needs a live per-attempt token, bound to one conversation and attempt, with a model list and an expiry. The dispatcher revokes it at the attempt's end and on any failure. Unknown or revoked tokens are refused.
4. Only the selected models and the pinned route are accepted. Every query except the pinned one is refused, and credential headers are stripped.
5. **To be added before the first paid call** (engineering, no Owner decision; the architect's review of 2026-11-13; section 5):
   - the broker refuses any request asking the provider to reach or run something outside the request (server tools, `mcp_servers`, URL-sourced content, `container`);
   - the broker never forwards a header that selects the provider account scope (`anthropic-workspace-id`).
6. Both listeners are on `127.0.0.1` only. The control listener is never forwarded.
7. In the guest:
   - sshd allows exactly the one remote forward;
   - the container guard allows exactly the one address and port;
   - DNS is refused;
   - the egress allowlist is empty.

   These are verified by `inspect`, the job sweep and the containment catalogue.
8. Create admission: exactly the two secret names, no provider-key-shaped value, and the token bound to its attempt.

**Assumptions and limits (disclosed):**
1. **Same account.** Every process of your Windows account, including the AI sessions that build the harness, can read the key entry, call the control listener and write the store (decision 0010 point 1). The controls protect against accident and convenience, not against your own account.
2. **The authorization does not bind which key is stored.** Use only the dedicated key.
3. **Egress is a control in the broker's code, not an operating-system boundary.** Today's evidence is a static census plus the broker's audit. A live connection census is to be added (section 5).
4. **What you send to the provider** (prompts and the demo repository's content during E-05.5) goes to Anthropic under its terms. The broker cannot inspect content. Only the "no repository content" conditions limit it.
5. **The agent sees what it is given.** It can read its own token (by design), and the provider's response headers reach it (your organization and workspace ids: identifiers, not credentials).
6. **No harness spending control.** Money is limited only by your provider account's own limits. A leaked key spends until you revoke it at the provider.
7. **Billing of failed answers.** No provider statement was found on whether a complete error answer is billed. Under this package nothing depends on it.
8. **The broker is unsupervised.** It runs in the foreground and is not restarted automatically.

## 4. When execution stops, and what happens then

**Automatic stops:**
- **Containment:** a failed containment case or job-sweep edge, or a connection to any destination but the inference endpoint.
- **Credentials:** a credential found in a recorded surface (the run stops, and rotation or revocation is your decision).
- **Refusals:** a refused route, query or model; an expired or revoked token.
- **Authorization:** the broker refuses to start on a missing, mismatched, superseded or expired authorization.

**Procedural stops** (the engineering manager stops the leaf): any unexpected host-side connection seen in the broker's audit or census; any provider refusal (spend limit, exhausted credit, authentication, rate limit, overload).

**On a provider interruption, today** (investigation of 2026-11-13):
- The broker passes the provider's error through and records it.
- Durable records (the integration store, receipts, audit) survive.
- The conversation and its workspace survive on the guest's disk until the guest is destroyed.
- **No resume exists yet at any layer.** Recovery is a new attempt that starts a new conversation.
- Two built rules work against your direction:
  - one broken or usage-less stream closes the attempt's token for good;
  - the harness deliberately rewrites a running conversation to `error` at server start (the OA-03 finding).

Making "preserve Work state and resume safely when access returns" true is the recovery contract planning must place (section 6). It is not part of this approval, and execution stops cleanly until it exists.

## 5. Engineering work before each live act (the engineering manager's; offline; no Owner decision)

1. **The broker cannot be stopped by an interrupt on this host.** The architect measured on CPython 3.12.10 (Windows) that the broker's indefinite wait ignores Ctrl-C, so the only stop is a kill. The fix is an interruptible wait plus a stop that works from a session with no console. It is required before A2 goes live.
2. **Refusals in the broker:** provider-side tools, MCP servers, URL sources and hosted execution; never forward account-scope headers. Each gets a negative test.
3. **Route grammar:** exact equality of the whole query string, to admit `beta=true` only as observed.
4. **The key-entry command** (the architect's conditions):
   - it runs in a real console with echo off;
   - it refuses a value that is not key-shaped;
   - the key exists in memory only;
   - it prints nothing derived from the key;
   - it reminds you to clear the clipboard.
5. **A live census** of the broker's listeners and outbound connections.
6. **The D1 grant's model list:** primary plus secondary.
7. **Declared ports:** 18431 and 18432.
8. **Record corrections:**
   - the key is pasted, not "typed from the keyboard";
   - the Moby DNS change is not optional;
   - stale "Proposed" for decision 0021 in the inventory;
   - the proposal act missing from the envelope steps.

Each change gets an independent review before it is published.

## 6. For planning (the product manager reconciles, per the direction)

1. **S-03.5 and decision 0021:**
   - The envelope's `limit` (amount, currency, enforced_by, cap) has no value that is both non-binding and true. The architect recommends dropping it in a new canonical format. The fallback is a declared placeholder.
   - Keep the start precondition, the manifest binding, the selection and `expires_at` (a security validity: decision 0012 point 7 requires it).
2. **Per-attempt budgets** (decision 0015 section 6.3; E-05.6's `inference_grant`):
   - the request and token budgets: retire them, or set them non-binding (the broker's maxima);
   - `BUDGET_USAGE_UNKNOWN`: needs a decision and a code change;
   - the per-day budget was never built: retire it;
   - keep `ttl_s`, attempt identity and the model list.
3. **The recovery contract:** what "resume safely" means across the broker (re-grant), the dispatcher (execution-state record, a new attempt versus the same conversation), OpenHands (the deliberate `running` to `error` rewrite) and the ACP/Claude Code session (resume or fork, unverified in the pinned adapter). Today it is in no D1 leaf (gaps G1 to G11 of the investigation).
4. **Wording to change:** E-05.5's proof ("the authorized cap"), S-03.3's and S-03.5's proofs, OA-22 (g) and its stop "the cap reached".
5. **Accepted texts to amend:**
   - decision 0018 points 3 and 8 (Owner-accepted: presented unless the direction is recorded as that acceptance);
   - decision 0015 sections 2.2, 3.1, 3.3, 6.3 and 8, amendment 1 item 1, and Current facts item 3;
   - decision 0021, its title and sections 1, 3, 4, 6, 7 and 9.4.

## Sources

- **Provider documentation**, read 2026-11-13 at platform.claude.com/docs: about-claude/models/overview, about-claude/pricing, about-claude/model-deprecations, api/rate-limits, api/errors, manage-claude/workspaces.
- **Claude Code documentation** at code.claude.com/docs: llm-gateway-protocol, costs, model-config.
- **The repository's facts:** the engineering manager's fact sheet and recovery investigation, and the architect's answer (gates G and C; advisory B and G), 2026-11-13. These are session working files, not in the repository; their sourced conclusions are carried here.
