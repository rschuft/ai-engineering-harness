# Coding-provider path through ACP: architecture recommendation

> **Status: a recommendation, not a decision.** The Architect's answer to the Owner-requested review, recorded by the Overseer on 2026-11-10 after reading it in full. Every change it proposes (to proposed decision 0015, to the plan, to the create template and admission) is a proposal for the Owner and is **not applied**; OA-12's acts stay held. The Owner decisions it needs are listed in section 4 and in the Owner-action queue ([`bootstrap-log.md`](bootstrap-log.md), OA-12).
>
> **Overseer review:** concurs with the path (section 1), the separation of the model-access plane from coding-provider qualification (section 1.4), and amending 0015 rather than superseding it (section 3.1). Two points are emphasised for the Owner: (1) the pinned SDK and image run the providers in permission-suppressing modes and grant Claude Code broad tool permissions by managed settings (section 1.1, "Image" and "Permission handling"), so the container's process, filesystem, network and credential boundaries are the only boundaries, as the Owner directed; (2) R4, the locked image's adapter content, is unverified and is the first act of the proposed provider leaf, because a missing adapter would make the SDK fall back to `npx`, which the guest denies.

Architect consultation (gates A, B, F, G), 2026-11-10, for the Owner's correction "Preserve
coding-provider agnosticism through ACP" (verbatim in `evidence/bootstrap-log.md`, Decisions,
2026-11-10). This repository at `4386550` (`main` = `origin/main`), clean.
Read-only; no guest, credential, runtime, model call or network beyond unauthenticated raw reads of
the pinned upstream `OpenHands/software-agent-sdk` at commit `e99e5c71ffe440a0b8d74b695f9307a7e34e4bbd`
(the commit `composition/lock/components.lock.json` pins for the four `openhands-*==1.60.1`
packages). Upstream line references below are to that commit; harness references are to `4386550`.
Everything here is a proposal for the Owner; nothing was applied.

Labels used in section 2: **RECORD** = established by the blueprint or an accepted record;
**SOURCE** = read in the pinned upstream source this invocation, not run; **UNVERIFIED** =
implementation mechanism still to be shown live, with what shows it and at which leaf.

## 1. The actual coding-provider path

The default implementation and review path is an OpenHands conversation whose agent is the SDK's
`ACPAgent`, selected by the create request's `agent_settings.agent_kind: "acp"` with
`acp_server` one of the pinned registry's keys (`claude-code`, `codex`), created by the dispatcher
exactly as today's typed create is (one admitted, sha256-pinned body per stage), and running the
provider's ACP adapter as a child process of the inner Agent Server inside the conversation
container, where it is bounded by the container's qualified process, filesystem and network
posture, not by any ACP permission mode. The provider authenticates with an API key that is
not a provider key: the attempt token of proposed decision 0015, delivered through the request's
`secrets` channel under the provider's own key variable, with the provider's base-URL variable
pointed at the guest `inference` endpoint, so every provider call reaches the host-side broker,
which alone holds the dedicated provider key. OpenHands-native direct-LLM agents (`agent_kind:
"openhands"` with LLM settings) stay an optional second body shape through the same endpoint and
broker. Subscription logins (Claude Code OAuth token, Codex ChatGPT `auth.json`) are not a
coding path at this pin: the pinned SDK strips the base URL whenever the Claude OAuth token is
present and does not route Codex's ChatGPT backend through `openai_base_url`, so both would put a
long-lived Owner credential in the container with direct egress, against P5 and P7.

### 1.1 Mechanism at the pin (Determine A)

| Step | Where | Source |
|---|---|---|
| Selection | `StartConversationRequest.agent_settings` (a dict) validated by the discriminated union `AgentSettingsConfig`: `agent_kind` `openhands` (default when absent) / `llm` (legacy) / `acp`. `agent_profile_id` is mutually exclusive with `agent_settings`. | `openhands-sdk/openhands/sdk/conversation/request.py` 437-531; `openhands-sdk/openhands/sdk/settings/model.py` 2207-2229 |
| ACP settings | `ACPAgentSettings`: `agent_kind: "acp"`, `acp_server: ACPServerKind` (`claude-code` default, `codex`, `gemini-cli`, `kimi-code`, `pi`, `opencode`, `custom`), `acp_command` (empty = registry default), `acp_args`, `acp_model`, `acp_session_mode`, `acp_startup_timeout`, `acp_isolate_data_dir`, `acp_file_secrets`, `agent_context`. "Provider credentials ride the conversation secrets channel (`request.secrets` ... -> `state.secret_registry`) keyed by the provider's env var name." | `settings/model.py` 1477-1478, 1786-2000 |
| Registry | `ACP_PROVIDERS["claude-code"]`: `api_key_env_var ANTHROPIC_API_KEY`, `base_url_env_var ANTHROPIC_BASE_URL`, `default_session_mode bypassPermissions`, `data_dir_env_var CLAUDE_CONFIG_DIR`, `env_conflicts`: when `CLAUDE_CODE_OAUTH_TOKEN` is present, `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` are stripped. `ACP_PROVIDERS["codex"]`: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `agent-full-access`, `data_dir_env_var CODEX_HOME`, file secret `CODEX_AUTH_JSON` -> `$CODEX_HOME/auth.json`. | `openhands-sdk/openhands/sdk/settings/acp_providers.py` 376-425 |
| Adapter pins | `@agentclientprotocol/claude-agent-acp@0.63.0` (binary `claude-agent-acp`), `@agentclientprotocol/codex-acp@2.2.2` (`codex-acp`), `@google/gemini-cli@0.46.0`; `DEFAULT_PREINSTALLED_ACP_PROVIDERS = (claude-code, codex, gemini-cli)`. SDK dependency `agent-client-protocol>=0.12.1,<0.13.0`. | `settings/acp_install_catalog.py` 105-132, 186-190; `openhands-sdk/pyproject.toml` 8 |
| Command | `resolve_acp_command()`: `acp_command` verbatim, else the registry's `npx -y --prefer-offline <pkg>@<ver>`, rewritten to the bare binary when `shutil.which(binary_name)` finds the image's PATH wrapper. `custom` with no command is a `ValueError`. | `settings/model.py` 2047-2141 |
| Image | Dockerfile `ARG INSTALL_ACP_PROVIDERS=claude-code,codex,gemini-cli`; stage `acp-providers` installs Node 24.22.1 under `/acp-node` and the pinned packages, writes wrappers to `/opt/acp-wrappers`; `base-image-minimal` copies them (`/acp-node`, wrappers into `/usr/local/bin/`), removes them if the Node runtime is incompatible with the base, writes `/etc/claude-code/managed-settings.json` = `{"permissions":{"allow":["Edit","Read","Bash"]}}` ("no human in the loop to approve"), sets `OH_ACP_SKILL_SOURCING=openhands_managed`. | `openhands-agent-server/openhands/agent_server/docker/Dockerfile` 22, 263-331, 408-452 |
| Outer create (Docker runtime) | `POST /api/conversations` pops `conversation_runtime`, forces `workspace` to `/workspace`, validates the body as `StartConversationRequest`, resolves the launch source (`agent_settings` or `agent_profile_id`), decrypts request secrets, then POSTs `forward_to_runtime(...)` to the container's own `/api/conversations` with the container's session key. The forwarded payload carries the resolved `agent_settings`, `secrets` materialized to values and re-encrypted with the container's cipher (`secrets_encrypted: true`). | `agent_server/docker_runtime/routers.py` 128-262; `agent_server/launch.py` 137-266 |
| Container environment | `_build_container` forwards a fixed list only (`HOME`, `OH_*`, the session key, `OH_RUNTIME_LAUNCHED_PROFILE`, `DEBUG`, observability vars); `OH_CONVERSATION_RUNTIME=local`. No provider variable crosses this way. | `agent_server/docker_runtime/registry.py` 607-700 |
| Inner create | The inner server's `_create_conversation`: `launch_source` -> `finalize(...)` -> `launched.agent` (`ACPAgentSettings.create_agent()` -> `ACPAgent`), `scoped_secrets` (a profile's `secret_refs` can narrow them), Codex credential binding when a stored ChatGPT login exists. | `agent_server/conversation_service.py` 1485-1660; `settings/model.py` 2142-2172 |
| Spawn | `ACPAgent._start_acp_server`: env = defaults, then `os.environ`, then **the whole `secret_registry` injected as env vars** ("an ACP CLI is a black box ... credentials must be delivered upfront"); `acp_isolate_data_dir` relocates the CLI's data dir to `<persistence_dir>/acp/<provider>`; file secrets materialized; `CLAUDECODE` stripped; provider `env_conflicts` applied; `OPENAI_BASE_URL` translated into `CODEX_CONFIG.openai_base_url` because Codex ignores the variable; `asyncio.create_subprocess_exec(command, *args, env=env)` (process cwd inherited from the server, session cwd `/workspace` via `session/new`); then `initialize`, auth-method selection, `session/new`, `set_session_mode`, model via `set_config_option`/`set_session_model`. | `openhands-sdk/openhands/sdk/agent/acp_agent.py` 3051-3260, 530-575, 2716-2763, 1071-1088 |
| Auth selection | File-backed subscription logins first (`chat-gpt` when `$CODEX_HOME/auth.json` is valid; Gemini Vertex/OAuth), then `api-key` for Codex (`CODEX_API_KEY`, `OPENAI_API_KEY`), then `_AUTH_METHOD_ENV_MAP` (Gemini only). `claude-login` is "intentionally NOT included"; `type: terminal` methods "need an interactive terminal, which the headless runtime cannot provide". Claude Code authenticates out of band from `ANTHROPIC_API_KEY` in its environment (`_preconfigured_credentials`). | `acp_agent.py` 308-437 |
| Permission handling | The SDK's `_OpenHandsACPBridge` is the ACP client: it answers `request_permission` itself; the registry's `default_session_mode` suppresses prompts. The blueprint's caveat and `fd-acp-provider-auth` stand: none of this is a boundary. | `acp_agent.py` 1296-1810; blueprint `#security` "ACP permission caveat" |
| Outer ACP routes | `POST /api/acp/models` answers 501 on a Docker-runtime server ("runs only where conversations run in-process"); `switch_acp_model`, `settings/*`, `secrets`, `llm/*` are all `dispatcher: not-used` in the pinned allowlist. | `agent_server/acp_router.py` 159-164; `profiles/strong-windows-qemu-whpx/agent-server/routes.json` |
| Harness today | The pinned template sends `agent_settings: {"agent_kind": "openhands", "mcp_config": {}, "tools": []}`; the body allowlist is the template's seven fields (`BODY_FIELDS`, `integrations/dispatch/dispatch_inputs.py` 817) and "each allowlisted field must equal the template's"; `secrets` and `agent_profile_id` are refused as unknown fields. | `profiles/strong-windows-qemu-whpx/agent-server/conversation-create.json`; `integrations/dispatch/README.md` |

So: an implementation run selects the coding provider by the materialized `agent_settings` block of
the admitted create body (A-01.2 / E-03.1's "agent block"), never by server configuration; the
provider process runs inside the conversation container as a child of the inner server, under the
container's `--cap-drop ALL`, `no-new-privileges`, `openhands` user, pids/memory/CPU caps, the
three declared binds and the guest's container and egress guards (F-04.2, S-01.3.x, S-02.x).

### 1.2 Authentication without Owner credentials (Determine B)

| Provider | CLI needs | Scoped / short-lived options | Where the secret sits | Broker fronts | Broker cannot front |
|---|---|---|---|---|---|
| Claude Code (`claude-agent-acp` 0.63.0) | `ANTHROPIC_API_KEY` (Console API key), or `CLAUDE_CODE_OAUTH_TOKEN` (subscription token from the CLI's `setup-token`), or interactive `claude login` (impossible headless) | Brokered: `ANTHROPIC_API_KEY` = the per-attempt token (0015 s3), `ANTHROPIC_BASE_URL` = `http://172.17.0.1:<inference_port>`; the real key is a dedicated, spend-capped Console key held only by the broker (0015 s2). Key scoping at Anthropic (workspace keys, spend limits) is the Owner's console act; the harness adds the per-attempt bound. | Real key: broker memory + one credential-provider entry (0015 s2). Token: the create's `secrets` (re-encrypted into the container), the conversation's persisted state (cipher), the CLI's process environment; per-conversation `CLAUDE_CONFIG_DIR` when `acp_isolate_data_dir` is true. | The Anthropic Messages API family (`x-api-key` header), streamed, untranslated; path and `model` allowlists; budgets; revocation. | The OAuth token path: the SDK strips `ANTHROPIC_BASE_URL` when `CLAUDE_CODE_OAUTH_TOKEN` is present (SOURCE), so it cannot be brokered; interactive login; the CLI's non-inference traffic (telemetry, update checks, OAuth profile) which the guest denies. |
| Codex (`codex-acp` 2.2.2) | `OPENAI_API_KEY` / `CODEX_API_KEY` (Platform API key), or ChatGPT subscription `auth.json` (refresh token) | Brokered: `OPENAI_API_KEY` = attempt token, `OPENAI_BASE_URL` = the endpoint (the SDK writes it into `CODEX_CONFIG.openai_base_url`); a dedicated, spend-capped Platform key held by the broker. | As above; `CODEX_HOME` per conversation. | The OpenAI API family Codex uses in API-key mode (Responses API expected; pinned from observed traffic), untranslated. | The ChatGPT subscription path: `auth.json` is materialized into the container (a long-lived Owner credential, readable by the attempt) and its backend is not `openai_base_url` (SOURCE, `acp_agent.py` 530-575; `acp_file_credentials.py` 135-190); device/browser login flows. |

Both brokered paths keep 0015's shape (token in, provider key only at the broker, untranslated
pass-through, fingerprint-only audit). The exposure is 0015 s3.3's: the token is readable by its
own attempt and bounded by budget, model list, expiry and revocation.

### 1.3 Networking, and whether the 0015 broker serves ACP providers (Determine C)

- Required egress per provider: exactly one upstream origin on 443 (Anthropic's API host for Claude
  Code; OpenAI's API host for Codex in API-key mode), from the broker on the host only. No name
  resolution in the guest: the base URL is the IP-literal guest endpoint (0015 s7.1); the broker
  resolves on the host. Both CLIs can be pointed at a base URL at this pin (Claude Code by
  `ANTHROPIC_BASE_URL`; Codex through `CODEX_CONFIG.openai_base_url`, which the SDK synthesizes).
- The CLIs also attempt non-inference connections (telemetry, update checks, OAuth metadata).
  Under the egress guard these fail closed; whether each CLI degrades gracefully, and which
  documented switches silence that traffic, is a qualification item (section 5).
- **The 0015 broker serves ACP coding providers only if its API-family clause is generalized.**
  0015 s5.3 allowlists "the provider's API family" (one), and the local-first request (section 3)
  narrowed it to the OpenAI-compatible Chat Completions request. Neither ACP provider speaks Chat
  Completions: Claude Code speaks the Anthropic Messages API and Codex the OpenAI API in its own
  wire shape. The broker must therefore be a per-upstream-family pass-through: a declared set of
  `{family, upstream origin, auth header style, path allowlist, model allowlist}` entries
  (anthropic-messages; openai (Codex); openai-chat for the native agent, LiteLLM, or a local
  server), routed by request path, with each attempt token bound to one family at issuance.
  Nothing is translated, so the semantic and inference-access contracts name no provider: the
  dispatcher carries opaque `secrets` under names it reads from the pinned registry, and the
  broker's families are configuration.
- The guest endpoint, the SSH remote forward, the container-guard allow and the empty egress
  allowlist of 0015 s4-s5 are consumer-agnostic and unchanged; one listener serves both consumer
  kinds.
- The local-model alternative stays the degenerate upstream (0015 s2.4) for the openai-chat family
  (native agents, Knowledge, Conversation). It is not a Claude Code or Codex upstream at this pin:
  whether the installed Ollama offers an Anthropic-compatible endpoint was not examined and is at
  most an "optional local coding experiment" in the Owner's words.

### 1.4 Model access versus coding-provider qualification (Determine D)

Separate them. The model-access plane (broker, token issuance, endpoint, forward, guest
composition, egress, audit) is provider- and consumer-agnostic, and its proof needs no model: a
probe inside a disposable conversation container can show the endpoint answers 401 without a
token and forwards with one to a fake upstream on the host, that revocation is immediate, that
forward loss fails closed, and that every other target stays refused, with no provider key, no
Owner egress and no model anywhere. The coding-provider qualification (the pinned adapter and
CLI start under the container's actual permissions, the four boundaries each shown independently,
the provider's observed endpoint and model-name set, graceful failure of denied traffic, token
replay refused) is a different proof with its own Owner acts (a provider key and one egress
origin). Today no leaf owns the second: E-03.2.2 launches a review with an ACP adapter on the
strength of S-03.2 alone, and S-03.2's first live call was specified as a native conversation
with LLM settings. Section 3 proposes the split.

### 1.5 Minimal adapter and contract changes (Determine E)

1. **Create template and allowlist, per stage** (E-01.3.1's finding F3, owned by A-01.2 / E-03.1):
   the `agent_settings` block becomes an `ACPAgentSettings` payload (`agent_kind: acp`,
   `acp_server` from the pinned registry, `acp_command: []` and `acp_args: []` so only the image's
   pinned binary runs, `acp_model` from the broker's allowlist, `acp_isolate_data_dir: true`,
   `acp_session_mode` pinned to the registry value or null); a `secrets` field is added to
   `BODY_FIELDS` carrying exactly two names, the registry's `api_key_env_var` (value: this
   attempt's token) and `base_url_env_var` (value: the declared endpoint URL). Admission refuses
   `acp_server: custom`, any non-empty `acp_command`/`acp_args`, any other secret name,
   `agent_profile_id` (already unknown), and a token the dispatcher did not issue for this
   attempt. The names come from the pinned SDK's `ACP_PROVIDERS`, not from a harness enumeration
   (blueprint: "Do not maintain a parallel provider enumeration"). The openhands-kind body (LLM
   settings `model`/`base_url`/`api_key`) is the optional alternative block, admitted the same way.
2. **Dispatch record**: the create receipt gains the answer's `agent.acp_server` and the model
   identifier (identifiers, no secret); provider name and version reach the evidence through the
   conversation's persisted events at reconciliation (E-01.4.x), since the ACP server identifies
   itself only at session start. ACP tool calls are persisted as events (`sdk/event/acp_tool_call.py`),
   so execution evidence keeps the same reader.
3. **Token binding**: 0015 s3.1's attempt token gains a family (section 1.3); issuance stays the
   dispatcher's call to the broker's control listener, before the create.
4. **Profile and P5/S-01.3.2 allowances** (Overseer, contract owner): the attempt token in the
   CLI's process environment is a labelled scoped secret; `jobs.environment.secret_names` and the
   `credential_name_pattern` rule gain exactly the provider's key variable, the P5 needles gain the
   provider key's fingerprint (absent), the job probe's control finds the token's fingerprint, and
   the inventory's `endpoint-inference`, `nm-job-inference`, `nm-review-inference` lose the
   guestfwd wording as 0015 already schedules.
5. **Independence of review**: the review stage's materialized block pins its own `acp_server`
   and/or model and its own token; the independence itself is enforced by exchange, mounts, role
   tokens and the separate attempt (decisions 0003, 0007, 0013), not by the provider choice.
6. **No new layer**: the dispatcher still sends one admitted create; OpenHands spawns and drives
   the provider; the broker is the one process 0015 already adds.

## 2. Credential and security requirements

| # | Requirement | Label | Verified by, at |
|---|---|---|---|
| R1 | Provider and LLM credentials never enter the guest; only behind the brokered `inference` class | RECORD: profiles P5, P7; 0007 points 4-5; 0015 s2; blueprint `#containment-final-decision` threat row "Provider CLI requires authentication token" | fingerprint search in guest, jobs, records, reports (0015 s4.5), S-03.2 |
| R2 | ACP permission modes are not an isolation boundary; process, filesystem, network and credential boundaries are qualified independently | RECORD: blueprint `#security` caveat; `fd-acp-provider-auth`; Owner constraint. SOURCE: the image's `managed-settings.json` allows all tools; the SDK's bridge answers permissions itself | the four boundaries shown from inside a container with the provider process running, provider leaf (section 3) |
| R3 | The ACP adapter runs inside the conversation container under the qualified container posture | SOURCE (routers.py / registry.py / acp_agent.py). UNVERIFIED live | `docker inspect` of the running container plus process inventory showing the adapter and CLI as children of the inner server under the same caps and user, provider leaf; E-01.5's independent inspect later |
| R4 | The locked image (ID `e8959dfc...42cb`, tag at lock time `1.60.1-python`) contains `/usr/local/bin/claude-agent-acp`, `/usr/local/bin/codex-acp` and `/acp-node/bin/node` | UNVERIFIED (inferred from Dockerfile defaults; `provision.lock.json` records only architecture, os, created, user, entrypoint) | offline read of the staged image config's `Env` (`ACP_NODE_DIR`, `OH_ACP_SKILL_SOURCING`) and of the layer listing, no guest; else one `ls` inside a disposable container; first act of the provider leaf. If absent, the SDK falls back to `npx`, which the guest denies: a derived image is then a decision-0006/composition change for the Owner |
| R5 | The provider authenticates with the attempt token only; no subscription login reaches the container | SOURCE: registry env rules, auth selection, file-secret materialization. UNVERIFIED: that the CLI persists nothing of the key to its data dir | admission test that `secrets` holds exactly the two names and the token; scan of the per-conversation data dir after a run; provider leaf |
| R6 | Both CLIs honour the base URL so every inference call reaches the broker and nothing reaches the provider directly | SOURCE for the mechanism (`ANTHROPIC_BASE_URL`; `CODEX_CONFIG.openai_base_url`). UNVERIFIED for the adapters' behaviour | broker audit shows every request; egress guard counters show the refused direct attempts; S-02 catalogue re-run; provider leaf |
| R7 | Non-inference CLI traffic fails closed without breaking the run, or is disabled by documented switches | UNVERIFIED | observed denied connections and a completed fixed-prompt turn; provider leaf; a CLI that cannot run without it is a STOP for the Owner |
| R8 | The broker passes each provider's own API family untranslated with per-family path and model allowlists; the token is bound to one family | Proposed amendment of 0015 s3.1, s5.3 (section 3) | fixture tests with a fake upstream per family, S-03.2; live paths pinned from observed traffic, provider leaf |
| R9 | The guest-to-host path is the dispatcher-held SSH remote forward; `launch.argv` unchanged; the egress guard's allowlist stays empty | RECORD-level design in 0015 s4 (Proposed); Owner acts A3, A4 pending | `inspect`, the S-02 catalogue, host census, S-03.2 |
| R10 | Same-account disclosure: the provider key entry and the broker's control listener are reachable by every process of the Owner's account | RECORD: 0010 point 1, 0013 point 6, `fd-bootstrap-shared-identity`; 0015 s2.2 | disclosure, every request |
| R11 | Agent definitions, skills and the provider's tool scope cannot widen at launch; stored server settings inject no MCP servers | RECORD: blueprint `#agent-skills` ("an external ACP server owns its subprocess tools"), A-01.2 proof. SOURCE: `server_launch_stores` merges the server's stored `mcp_config` | admission denies MCP and tool fields in the ACP block; the inner server's settings store is shown default; A-01.2, with a first check at the provider leaf |
| R12 | `custom` ACP servers and caller-supplied commands are refused | Proposed admission rule (section 1.5) | admission tests, A-01.2 / E-03.1 |

## 3. Proposed changes to decision 0015 and to the plan

### 3.1 Decision 0015: keep, with three amendments and one withdrawal (not supersede)

The placement (s1), credential custody (s2), per-attempt tokens (s3), endpoint and inspection
(s4), egress (s5), audit (s6) and the positions on the three named items (s7) hold for ACP
providers as they are. Amend:

- **s3.1-s3.2** (token binding and the create's LLM fields): bind each token to one API family
  as well as a conversation, model list, budget and expiry; the token reaches an ACP agent
  through the create's `secrets` under the registry's `api_key_env_var`, with the endpoint under
  `base_url_env_var`, and reaches a native agent through the LLM settings as written. Both are
  one template shape per stage.
- **s5.3** (path and model allowlist): from "the provider's API family" to declared per-family
  entries routed by path, pass-through only, with the set per family pinned from observed traffic
  at the leaf that first runs that family.
- **Consequences, "The typed create"**: name both body shapes and the `secrets` field; the
  tamper test extends to "no secret name beyond the registry's two, no provider key".
- **Withdraw** the local-first request's section 3 refinement ("this one family": Chat
  Completions). It excludes both default providers. Local inference remains the openai-chat
  family's degenerate upstream (s2.4).
- **Context**: record the SOURCE facts of section 1.1 (the ACP settings, the secrets channel,
  the image's adapter payload and managed settings, the OAuth-token strip, the Codex config
  translation) and close 0015's "Not verified" item on the create's LLM field names for the ACP
  kind.

### 3.2 Plan (integrity process; Owner-directed amendment)

| Leaf | Change | Dependencies |
|---|---|---|
| S-03.1 | Reopen for the 0015 amendments above; proof unchanged | unchanged |
| S-03.2 | Re-scope the live qualification to the **plane proof without a model**: broker with a fake upstream per family on fixtures; in one disposable guest, a probe from inside a conversation container shows 401 without a token, forwarding with one, immediate revocation, fail-closed forward loss, every other target refused, the S-02 catalogue re-run. Owner acts needed: A2, A3, A4 only. Drop A6 and the LLM-settings create from its proof; keep the child-conversation clause | unchanged (S-03.1, S-01.2.2, F-06.3) |
| **S-03.3 (new)** "Qualify the default ACP coding provider through the broker" | One ACP provider (Owner's choice of claude-code or codex, API-key mode) in one disposable guest, one fixed prompt, no repository content, a disposable pinned create fixture (as F-04.2's was; refused for a real stage by A-01.2 later). Proves R2-R7 and R11-R12 of section 2; pins the family's path and model allowlists from observed traffic; records the adapter and CLI versions. First act: R4's offline image check. Owner acts: the provider key (A1), one egress origin (A5), the first model call (A6) | S-03.2, F-04.2 |
| A-01.2 | Materialization produces an ACP or openhands `agent_settings` block plus the two `secrets` names per stage; admission rules of section 1.5 item 1 | unchanged |
| E-03.1 | "model/provider mapping" = `acp_server` + `acp_model` (+ family) from the pinned registry per role; the provider compatibility fixture is S-03.3's observed record; openhands-native stays the optional alternative | add S-03.3 |
| E-03.2.2 | Depends on the qualified provider, not only the plane | S-03.2 -> S-03.3 |
| K-02.2 | Native-LLM consumer; keeps S-03.2; the local upstream acts (L1, L2) belong to it or to a sibling "optional local inference experiment" leaf, never to the coding path | unchanged |
| E-01.3.3 / E-01.3.2 | Unchanged; the token issuance call joins the dispatcher principal as 0015 s1 says | unchanged |

Order of the next moves: 0015 amendment and the plan amendment (Owner) -> S-03.2 plane proof
(A2, A3, A4) -> S-03.3 provider qualification (A1, A5, A6) -> A-01.x / E-03.1 materialization ->
E-03.2.x. OA-12's held acts L1, L2 stay held and are re-homed; A2, A3, A4 are re-presented under
the plane proof; A1, A5, A6 under S-03.3.

## 4. Decisions and authorizations for the Owner before work proceeds

1. **Authentication mode**: API keys dedicated to the harness (Console / Platform, spend-capped,
   revocable), brokered; subscription logins (Claude OAuth token, Codex `auth.json`) are not a
   coding path at this pin for the reasons in section 1.2. This also decides which account and
   terms apply (blueprint `#components`: "USER-SUPPLIED; pin adapters and honor third-party terms").
2. **First provider and models**: claude-code or codex for S-03.3; the model names the broker
   allowlists (Claude Code also uses a small/fast model for background calls; both names must be
   allowlisted or pinned by its documented variable, to be confirmed from observed traffic).
3. **Broker families**: accept the per-family pass-through amendment of 0015 and the withdrawal of
   the Chat-Completions-only refinement.
4. **Plan amendment**: S-03.2 re-scope, S-03.3 added, E-03.1 and E-03.2.2 edges, L1/L2 re-homed.
5. **Image**: if R4 fails, whether to adopt a derived image (a decision-0006 item 3 and composition
   change) or another delivery of the pinned adapters.
6. **Posture disclosures** (Overseer as contract owner, disclosed to the Owner under gate G): the
   attempt token in the CLI's process environment as a labelled scoped secret; `acp_isolate_data_dir`
   true; the registry's permission-suppressing session modes kept, documented as not a boundary;
   denied non-inference traffic as a fail-closed condition.

## 5. Not verified in this invocation

- The locked image's content (R4); the staged archive is under the managed root, out of scope here.
- The npm adapters themselves (`claude-agent-acp` 0.63.0, `codex-acp` 2.2.2) and the CLIs they
  bundle were not fetched: their exact HTTP endpoints, header styles, acceptance of a plain-HTTP
  base URL, any WebSocket transport, what they persist to their data dirs, and their behaviour
  when telemetry and update checks are refused. The SDK's statements about them (Claude honours
  `ANTHROPIC_BASE_URL`; Codex ignores `OPENAI_BASE_URL`) are upstream claims at the pin, not
  observations.
- `validate_agent_settings` acceptance of the proposed block; the openhands-kind LLM settings
  fields (not read in full); the inner server's settings store being default in our guest.
- Provider-side key scoping features (workspace keys, projects, admin APIs) and the Ollama
  installation's API surface: not examined.
- No live act: no guest, container, broker, forward, credential, model or network beyond the
  pinned-source reads named above.
