# Authorization package: provider access for D1 (OA-12 with OA-22 (a), (b), (c), (e))

Updated 2026-11-13 by the engineering manager after S-03.6 (PASS) and the pre-live broker fixes, at `008b7d6`
([verdict](bootstrap-log.md#s-03-6-verdict-2026-11-13)). The acts of section 1 and its one decision are unchanged
in substance.

Prepared 2026-11-13 by the engineering manager, at `27b0f40`, under the Owner's [direction on provider access](bootstrap-log.md#owner-direction-provider-access-2026-11-13). Nothing below has been performed. This page is complete on its own. It replaces, for presentation, the [S-03.1 request](S-03.1-owner-authorization-request.md): where they differ, this page is current.

**One decision for the Owner:** approve or reject the package in section 1. Everything else here is the engineering manager's own decision, or a disclosure.

## 1. What the Owner is asked to approve

| # | Act | Exactly |
|---|---|---|
| P | **Provider and origin** | Anthropic's first-party Claude API. One origin, `https://api.anthropic.com:443` (TLS, the host's system roots). It is used only through the inference broker, with one route: `POST /v1/messages`, with no query string or with exactly `beta=true`. Only the form observed at S-03.3's discovery run is pinned. Every other path, query and destination stays refused. |
| A1 | **The provider key** | One dedicated Anthropic API key that you create for this harness. Create it in a dedicated Console workspace, for example `aieh-harness`, so it is single-workspace and revocable on its own. It is not your personal key and not your Claude Code login. You enter it once, in your own console window (a real console, not a pipe or an editor), by pasting it at a hidden prompt of one harness command: `task inference:credential-enter -- --provider anthropic` (that is, `inference_broker.py credential-enter --provider anthropic`). It is stored in Windows Credential Manager under `AIEH model provider`, and the harness records only its fingerprint. Never paste it into a conversation, a file or a chat. |
| A2 | **The broker's two listeners** | The broker runs as your Windows account, as a foreground process that the engineering manager starts for each live step and stops afterwards. It is not a service. It has two listeners: `127.0.0.1:18431` (control: issue and revoke attempt tokens; host-only, never forwarded) and `127.0.0.1:18432` (inference). It needs no administrator rights, no firewall change and no LAN exposure. |
| A3 = OA-22 (b), (c) | **One guest-to-host path** | For each disposable guest created for inference, the existing SSH management channel carries one remote forward: the guest's `172.17.0.1:8090` to the host's `127.0.0.1:18432`. It adds no new host listening port, no QEMU change and no `guestfwd`. It exists only while the harness holds the session. It serves two edges: `nm-job-inference` (containers) and `nm-guest-inference` (the guest's own processes: disclosed, with the token as the only control). |
| A4 = OA-22 (e) | **Guest hardening change** | It applies only to disposable guests created with `--inference`. The guest's sshd allows remote forwarding to `172.17.0.1:8090` only (`AllowTcpForwarding remote`, `GatewayPorts clientspecified`, `PermitListen 172.17.0.1:8090`; local forwarding stays refused). The container guard gets one ACCEPT, docker0 to `172.17.0.1:8090/tcp`. Moby is pinned to `bip 172.17.0.1/16` and `dns 172.17.0.1`, so a container's DNS lookup is refused by policy. The egress allowlist stays empty. The full containment catalogue is re-run, and every case must pass. |
| A5 | **Host egress** | The broker's outbound connections go to that one origin only, plus the host's DNS lookup of `api.anthropic.com`. The broker sends no telemetry and makes no price or update checks. |
| A6 + D1 | **Model calls** | The first call (S-03.3: one disposable guest, one conversation, a fixed one-word prompt, no repository content), then D1's own calls through the broker (E-05.5's contained coding conversation, which works only on the demo repository named under OA-25). OA-22 (g) is folded into this approval (planning, 2026-11-13, [planning pass](bootstrap-log.md#planning-pass-2026-11-13b)), so D1 needs no further model-call decision. |

**Validity:** the authorization's `expires_at` is set to `2027-01-31T23:59:59Z`. This is a security validity window, set by the engineering manager, not a spending term. An earlier end is a stopped broker, a revoked key or a superseding authorization.

**Your acts after approval (three):**
1. Create the key at the provider.
2. Run the one key-entry command, `task inference:credential-enter -- --provider anthropic`, in your own console window, and paste the key at its hidden prompt (nothing is shown; it refuses a value that is not key-shaped, and reminds you to clear the clipboard).
3. Reply once to the authorization recorder's challenge, by naming its operation id, when the exact envelope manifest is shown to you.

Act 3 is the protected-merge record that the broker checks before it ever reads the key (decisions 0012 and 0021). It is answered on the canonical manifest of the envelope format `aieh-provider-envelope/2` (provider, origin, `expires_at` and the model selection; no spending limit), which S-03.6 built; section 7 previews it. Before act 3 the engineering manager prints that manifest (`inference_broker.py envelope --operation <id>`), proposes it as `operations/<id>.json` on the authorization repository (`aieh-authorization/authorizations`, decision 0022) and prepares the recorder's challenge (`authorization_recorder.py prepare`); the challenge then shows you the exact manifest.

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
5. **What a request may ask of the provider** (built 2026-11-13, offline; [evidence](S-03.2-S-03.3-pre-live-security-fixes.md)):
   - nothing outside the request: `mcp_servers`, `container`, server or provider tools (any `tools` entry whose type is not `custom`), and content blocks and sources outside an allowlist (URL and file sources included) are refused, `PROVIDER_REACH_REFUSED`;
   - headers by allowlist only: `content-type`, `accept`, `anthropic-version`, `anthropic-beta`, `user-agent`, `x-app` and `x-stainless-*`; every other header, the account-scope ones (`anthropic-workspace-id`) included, is stripped and named in the audit; a header value with a control character, a compressed body or another content type is refused;
   - strict bodies: a repeated key, a body that is not strict UTF-8 and a body nested too deeply are refused;
   - the query is exactly absent or `beta=true`, byte for byte.
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
3. **Egress is a control in the broker's code, not an operating-system boundary.** Its evidence is a static census, the broker's audit (each upstream connection's peer recorded), and a live census of the broker's sockets at the operating system (`inference_census.py --once`: exactly its two loopback listeners, no UDP, outbound only to the origin's port and recorded peers), which runs before the first call and after it; anything but PASS stops the run.
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
- Of the two built rules that worked against your direction:
  - the first, one broken or usage-less stream closing the attempt's token for good, is retired (S-03.6): such an answer is recorded and the token admits its next request;
  - the second, OpenHands' rewrite of a running conversation to `error` at server start (the OA-03 finding), stays: planning placed its handling in plan leaf E-05.8 (the interrupted attempt is ended cleanly, its token revoked and its records kept; a new attempt gets a new conversation and token).
- **The broker stops cleanly** on Ctrl-C or Ctrl-Break in its console, or on `inference_control.py stop` from another session: new requests are refused, requests in flight get at most 3 s, and the stop is recorded. Closing its console window is not a clean stop.

Native resumption is a deferral of the plan, determined first in E-05.8; it is not part of this approval, and execution stops cleanly until it exists.

## 5. Engineering work before each live act (the engineering manager's; offline; no Owner decision)

Each item's state on 2026-11-13 (built offline, reviewed; [evidence](S-03.2-S-03.3-pre-live-security-fixes.md), [S-03.6](S-03.6-spending-enforcement-retired.md)):

1. **Interruptible stop** (before A2): **done offline**, `5499356`, `d7682b6`, `61e1906` (section 4).
2. **Refusals in the broker** (provider-side tools, MCP servers, URL sources, hosted execution; account-scope headers): **done offline**, `e676d9e`, `7f45b1d`, `4f5dd75`, `6163b53`, `87f4b9c`, `5469f19`, `73c5831`, `008b7d6` (section 3, item 5).
3. **Route grammar** (exact whole-query equality): **done offline**, `c377875`.
4. **The key-entry command**: **done offline**, `a895d2b`, `8bf46e3`: a real console with echo off, a value that is not key-shaped refused, the key in memory only, nothing derived from it printed, the clipboard reminder; its receipt keeps only the key's fingerprint.
5. **A live census**: **done offline**, `3dc5f27`, `6e79cdd` (section 3, assumption 3).
6. **The D1 grant's model list** (primary plus secondary): **done offline**, `144fa54`: it is the broker's held selection for the ACP family, so both selected models are admitted.
7. **Declared ports** 18431 and 18432: **done** (`example_config.yml` and the inference README, S-03.6's `1144776`).
8. **Record corrections**: **done**: the key is pasted, not typed (section 1; a correction note on the [S-03.1 request](S-03.1-owner-authorization-request.md)); the Moby DNS change is required (a correction note on the S-03.1 requests and in the OA-12 row of the log); decision 0021 is no longer "Proposed" in the inventory (`1144776`); the proposal step is named before act 3 (section 1).

What remains is live: each act, then S-03.3's discovery run and first call.

Each change gets an independent review before it is published.

## 6. For planning

Reconciled by planning on 2026-11-13: [planning pass `planning-pass-2026-11-13b`](bootstrap-log.md#planning-pass-2026-11-13b).

## 7. Preview of the act-3 manifest

What the recorder's challenge will show you at act 3, built offline on 2026-11-13 at `008b7d6` by the broker's own
`envelope` command (`inference_broker.py envelope --operation d1-provider-envelope`) over a scratch configuration
(never the managed root or its `config.yml`) holding the intended envelope: provider `anthropic`, the
`anthropic-messages` family with upstream `https://api.anthropic.com` and the selected models, `expires_at:
"2027-01-31T23:59:59Z"`, `selection: delegation`, listeners 18431 and 18432.

```json
{
  "operation": "d1-provider-envelope",
  "kind": "provider-envelope",
  "target": "sha256:6ed0882190c5c505aabb868d37eb2b5b6bf93b12618e63ebd7be7c0a2a5d4d54",
  "expiresAt": "2027-01-31T23:59:59Z",
  "envelope": {
    "format": "aieh-provider-envelope/2",
    "provider": "anthropic",
    "origin": "https://api.anthropic.com:443",
    "expires_at": "2027-01-31T23:59:59Z",
    "selection": {
      "by": "delegation",
      "record": "decision:0018",
      "point": "3"
    }
  }
}
```

- **Envelope digest** (the authorization's target): `sha256:6ed0882190c5c505aabb868d37eb2b5b6bf93b12618e63ebd7be7c0a2a5d4d54`.
  Manifest digest of this preview: `sha256:eb4f612a4dbda2d592a827102d9aa3d2d56755dda5efaf68a899669dba4bcac2`.
- **The model identifiers are not in the digest:** under `selection: delegation` the document names decision 0018
  point 3, not the models (`inference_envelope.document`). The preview's digest was the same with the secondary
  configured as `claude-haiku-4-5` and as `claude-haiku-4-5-20251001`, so the secondary's exact form, observed at
  S-03.3's discovery run, does not change it. The models are recorded afterwards by the engineering manager's
  selection record, which rests on your authorization's receipt.
- **The operation id** `d1-provider-envelope` is the preview's: the real one is chosen when the manifest is proposed,
  and it changes the manifest's own digest, not the envelope digest.
- The recorder's challenge is issued on the real configuration, after acts 1 and 2. Its envelope digest equals the
  preview's only if that configuration's provider, origin, expiry and selection are exactly these.

## Sources

- **Provider documentation**, read 2026-11-13 at platform.claude.com/docs: about-claude/models/overview, about-claude/pricing, about-claude/model-deprecations, api/rate-limits, api/errors, manage-claude/workspaces.
- **Claude Code documentation** at code.claude.com/docs: llm-gateway-protocol, costs, model-config.
- **The repository's facts:** the engineering manager's fact sheet and recovery investigation, and the architect's answer (gates G and C; advisory B and G), 2026-11-13. These are session working files, not in the repository; their sourced conclusions are carried here.
