# D1 native profile: the consolidated Owner decision (OA-31, with OA-22 (d) (f) (h) (i) (j) and OA-25)

Presented by the engineering manager, 2026-11-14, after the offline work passed: E-05.9 PASS (offline), E-05.10
offline complete (its live step waits (a)), E-05.8 PASS (offline). The model record is
`evidence/D1-native-model-record.md`; the provider pages re-read are in `evidence/D1-native-provider-terms-2026-11-14.md`. Basis: decision 0023 (Accepted), the
prepared OA-31 (bootstrap log, anchor `oa-31-prepared-2026-11-14`), OA-22's row, OA-25's row, and the Owner's
direction to the engineering manager of 2026-11-14 (anchor `owner-direction-native-execution-2026-11-14`), which asked
for one consolidated decision recommending standing authorization for D1 coding attempts and routine model selection
within the native profile, and no per-attempt approval. Each item is separately answerable. Nothing is granted until
the Owner answers; the answer is recorded verbatim by the session in which it is given.

**Not asked here:** the brokered profile (OA-12 acts 1 and 2 stay paused); any other repository; host shares; any
other egress; any other Owner credential in a guest; merging (the result is an unreviewed draft pull request; merging
stays the Owner's); release or publication.

## 1. The provider's terms (OA-31 (d)) - the Owner's own reading

Re-read by the engineering manager 2026-11-14 (verbatim; the full excerpt is in the evidence file):
- legal-and-compliance: OAuth "is designed to support ordinary use of Claude Code and other native Anthropic
  applications"; "Developers building products or services that interact with Claude's capabilities, including those
  using the Agent SDK, should use API key authentication ... Anthropic does not permit third-party developers to offer
  Claude.ai login into their own applications, or to route requests through Free, Pro, Max, or Ultra plan credentials on
  behalf of their users. Moreover, developers may not collect, store, or intermediate Claude.ai credentials or session
  tokens — sign-in to a Claude account must complete through Anthropic's own flow." ... "Nor does it prevent an end user
  from signing in to the unmodified Claude Code binary with their own Claude subscription, including where a platform
  hosts Claude Code ..."; "Advertised usage limits for Pro, Max, and Ultra plans assume ordinary, individual usage of
  Claude Code and the Agent SDK."
- agent-sdk/overview: "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai
  login or rate limits for their products, including agents built on the Claude Agent SDK. Use the API key
  authentication methods described in the Quickstart instead."
- authentication: `claude setup-token` generates "a one-year OAuth token" "For CI pipelines, scripts, or other
  environments where interactive browser login isn't available"; "It does not save the token anywhere; copy it and set
  it as the `CLAUDE_CODE_OAUTH_TOKEN` environment variable wherever you want to authenticate".

**Engineering manager's reading (not a substitute for yours):** the documented method is used as documented (sign-in
through Anthropic's own flow on your host; the token set in the environment where Claude Code runs; the binary
unmodified). The restrictions address third parties offering claude.ai login *to their users* and handling *others'*
tokens. Here you are the developer, operator and only user; the harness is not offered to anyone; the token is yours,
for your own use. The tension to weigh: the harness launches the binary through the Agent SDK (via the ACP adapter) and
holds your token in your OS credential store for delivery. If the harness were ever offered to others, API-key
authentication (the brokered profile) applies. **Recommendation:** read the three pages yourself; if your reading
matches, say so; if not, no token is created and D1's profile returns to planning.

## 2. The native path, standing (OA-31 (a))
The guest forward's target becomes the host tunnel (127.0.0.1:18433; guests see `http://172.17.0.1:8090`); the tunnel
admits only `api.anthropic.com:443`, checks the TLS server name, holds no credential, decrypts nothing. Guest side
byte-identical to what you approved under OA-22 (b), (c), (e). *Unblocks:* E-05.10's live no-credential run, then
E-05.11 and D1. *Residuals:* provider-side tools/MCP/URL sources can no longer be refused (end-to-end TLS); while a
forward is held every guest process can reach the provider origin (useless without a credential it holds); the
allowlist is enforced in the tunnel's own code. *Stops:* the tunnel admitting another target; any failed containment
case; unexpected egress; any credential finding. *Expiry:* D1's acceptance. **Recommendation: approve.**

## 3. The credential class in disposable guests (OA-31 (b))
Your native token, delivered as `CLAUDE_CODE_OAUTH_TOKEN` (one of exactly four admitted secret names) into a D1
qualification or attempt container; readable there by the attempt and by guest root; never another Owner credential,
never your host `~/.claude`. Held in one host credential-store entry (`AIEH Claude Code native token`), fingerprint-only
records; an outbound search of everything leaving the guest after each run. *Residuals:* valid up to a year; not bound
to an attempt; same-account host processes can read the entry (decision 0010). *Stops:* the token persisted in the
configuration directory or found in anything leaving the guest; any other credential in an attempt; a containment
failure. *Expiry:* D1's acceptance (the token stays yours to revoke at the provider). **Recommendation: approve.**

## 4. Model calls on your subscription, and the model selection rule (OA-31 (c))
The record (verified 2026-11-14 from the pinned CLI 2.1.220 and the provider's model pages; never from memory):

| Role | Identifier | How fixed | Use |
|---|---|---|---|
| Primary | `claude-sonnet-5` | pinned in the admitted D1 create (`acp_model`) | the coding agent's main loop; sub-agents by default |
| Secondary | `claude-haiku-4-5-20251001` | chosen by the CLI; disclosed, not pinnable within the four secret names | titles, summaries, web-fetch processing, background classifier |
| Sub-agent choice | `claude-opus-5`, `claude-haiku-4-5-20251001`, `claude-sonnet-5`, `claude-fable-5` | the agent may choose per sub-agent call; disclosed | delegated steps |
| Refusal fallback | `claude-opus-5`, `claude-opus-4-8` | consent-gated in the adapter, expected never offered | only after a provider refusal |

All are current at the provider and known to the pinned CLI. Calls count against your subscription's own limits; no
harness cap (decision 0018 revision 5). *Stops:* an identifier outside this record observed in the events.

**Asked:** (c1) approve D1's model calls with this record. **(c2) Routine model selection, standing (an amendment of
decision 0018 point 3, under point 4.8):** "Within the native execution profile, the engineering manager may change
the primary model pinned in the D1 create, and the record above, to another model that is current at the provider and
known to the pinned Claude Code, verified from current provider information and recorded before its first use, and
reported in the next report; a change of the pinned Claude Code itself remains a planned change." *Expiry:* D1's
acceptance. **Recommendation: approve (c1) and (c2).**

## 5. The token's delivery to attempts (OA-31 (f))
(i) per attempt, or **(ii) standing, by your amendment of decision 0018 point 5 (point 4.8) admitting this one class**:
"The dispatcher may deliver the native Claude Code token to E-05.11's qualification runs and to D1 attempts, including a
new attempt after an interruption, under OA-31 (b)'s conditions and stops, until D1's acceptance." It excludes any
other credential. After an authentication refusal no new attempt runs until the engineering manager records the cause
and, where the provider refused the token, you enter a new one. **Recommendation: (ii).**

## 6. D1's remaining standing items (OA-22 (d), (f), (h), (i), (j)), as prepared 2026-11-12 and reconciled 2026-11-14
- (d) edge `nm-dispatcher-agent-server`: the dispatcher reaches the guest's agent server through the existing forward
  (E-01.3.3's custody probe; every D1 dispatch). **Approve.**
- (f) agent attempts through the dispatcher on the D1 demo repository's content only (the native token's delivery is
  item 5, not this). **Approve.**
- (h) provisioning the demo repository and its protections on the host Gitea inside declared policy. **Approve.**
- (i) the demo repository's content in a disposable guest for E-05.1's offline test run in the pinned image. **Approve.**
- (j) the D1 manifest envelope (decision 0018 point 3.3): the demo repository and the change named in 7, the qualified
  native profile and binding, the D1 agent assignment with no Skills, E-01.3.2's disposable work-attempt entries on the
  demo repository; the product manager promotes D1's manifests inside it. **Approve.**
All: excludes host shares, other egress, other Owner credentials, other repositories; stops on any failed containment
case, unexpected egress or credential finding; expire at D1's acceptance.

## 7. Name the D1 change (OA-25) - your intent
One small change in a demo repository on the host Gitea, testable offline in the pinned image. A default you may
accept, change or replace: **repository `aieh-d1-demo`, a tiny standard-library Python package with `unittest` tests;
the change: "add a `slugify(text)` function (lower-case, trim, collapse runs of non-alphanumerics to one hyphen, no
leading or trailing hyphen) with tests."** The demo repository will carry no `.claude/` settings or MCP configuration
(the adapter loads project settings from the workspace).

## 8. The one act (OA-31 (e)), after 1-5
On the host, in your own terminal: run `claude setup-token` (Anthropic's browser flow), then
`task credentials:native-token-enter` and paste the token at its hidden prompt. Never in a conversation, a command
line, a log or a file. The receipt shows the fingerprint only.

## What follows without asking you again (if approved)
E-05.10's live no-credential run; E-05.11's qualification (first authenticated turn, containment, persistence and
leakage searches); E-05.1 (the demo repository and the change's OpenSpec/Backlog records); E-01.3.3's probe; E-05.2 to
E-05.4; then D1 itself: your change implemented and tested by the contained Claude Code agent and delivered as an
unreviewed draft pull request. You would hear from the engineering manager again at a stop, an authentication refusal,
or D1's result.
