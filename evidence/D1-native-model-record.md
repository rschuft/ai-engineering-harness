# D1 native profile: the engineering manager's model record (decision 0023 section 7)

Recorded by the engineering manager, 2026-11-14, from the investigation below (decision 0023 section 7; the Owner's
decisions on OA-05 and OA-12 of 2026-11-10 govern: verified against current provider information, never assumed from
memory, never a wildcard).

**Selection:**

- **Primary** `claude-sonnet-5`, pinned as the full id in the D1 create's `acp_model` (E-05.2).
- **Secondary** `claude-haiku-4-5-20251001`, disclosed, not pinned (a fifth secret name is outside decision 0023).
- **Sub-agent choices** `claude-opus-5`, `claude-haiku-4-5-20251001`, `claude-sonnet-5`, `claude-fable-5`, disclosed.
- **Refusal fallback** `claude-opus-5`, `claude-opus-4-8`, disclosed.
- Presented to the Owner with OA-31 (c) ([presentation](OA-31-consolidated-presentation-2026-11-14.md)).
- E-05.11 checks the identifiers on its first turn: main loop `claude-sonnet-5`, background
  `claude-haiku-4-5-20251001`; any id outside this record is a stop.

The investigation follows as prepared (its paths into the session's scratch directory are shown as
`<session scratch>/...`).

## The investigation (prepared 2026-11-14)

Prepared 2026-11-14 for the engineering manager (decision 0023 section 7; E-05.11's proof). Read-only. Nothing was
installed or executed; no provider API call, no credential. Repository `rschuft/ai-engineering-harness` at
`17e1801` (main = origin/main), clean. Everything below is either a citation into a hash-checked source or a provider
documentation quote; inferences are marked **(inference)**. This draft selects nothing: the selection and its
presentation to the Owner (OA-31 (c)) remain the engineering manager's.

### Identifier table

The "native profile environment" means exactly what decision 0023 section 3 admits: `CLAUDE_CODE_OAUTH_TOKEN`,
`HTTPS_PROXY`, `CLAUDE_CODE_PROXY_RESOLVES_HOSTS`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` (non-empty), no
`ANTHROPIC_BASE_URL`, an empty per-conversation `CLAUDE_CONFIG_DIR`, `acp_args []`.

| Role | Exact id (as sent on the wire by CLI 2.1.220) | Alias in 2.1.220 | How pinned or disclosed | Intended use | Expected usage characteristics | Current at provider (read 2026-11-14) |
|---|---|---|---|---|---|---|
| **Primary** (main loop) | `claude-sonnet-5` | `sonnet` (also what `default` resolves to in this environment, see 2) | Pinned by the template's `acp_model` (E-05.2 digest); recommended value `claude-sonnet-5` (section 7) | The coding agent's main loop and every sub-agent that inherits | 1M context native (catalog `window:1e6,native_1m:!0`); 64K default / 128K max output; API list price $2 / $10 per MTok, cache write 5m $2.50, cache read $0.20 (the subscription is not billed per token; the API price is used here only as the relative weight, **(inference)**) | "Active (legacy)"; "Released June 30, 2026"; retirement "Not sooner than June 30, 2027"; successor Sonnet 5.5 exists, unknown to the pinned CLI |
| **Secondary** (small/fast, background) | `claude-haiku-4-5-20251001` | `haiku` (provider alias `claude-haiku-4-5`) | **Disclosed, not pinned**: only env vars or settings pin it, and a fifth secret name is outside decision 0023's four (section 3) | Session title generation, tool-use summary labels, WebFetch content processing, token counting, the background-agent classifier; the built-in `claude-code-guide` sub-agent | 200K context; 32K default / 64K max output; API list price $1 / $5 per MTok, cache write 5m $1.25, cache read $0.10; short requests | "Active (legacy)"; "Released October 15, 2025"; retirement "Not sooner than October 15, 2026" (that date has passed; no deprecation notice is listed, and the provider gives "at least 60 days' notice") |
| **Sub-agent** (by the Agent tool's `model` parameter) | `claude-opus-5` (`opus`), `claude-haiku-4-5-20251001` (`haiku`), `claude-sonnet-5` (`sonnet`); `claude-fable-5` (`fable`) named, reachability not established | `sonnet`, `opus`, `haiku`, `fable` | **Disclosed, not pinned**: the main agent may choose per call; `CLAUDE_CODE_SUBAGENT_MODEL` would pin it but is a fifth name | Delegated work; default is `inherit` (= primary) | Opus 5: 1M context, $5 / $25 per MTok (2.5x Sonnet 5's weight); Haiku and Sonnet as above | Opus 5: "Active (legacy)", "Released July 24, 2026", retirement "Not sooner than July 24, 2027"; Fable 5: deprecations table "Active", "Not sooner than June 9, 2027" |
| **Refusal fallback** (named by the CLI) | `claude-opus-5` (refusal category `bio`), `claude-opus-4-8` (category `cyber`) | none | **Disclosed**: consent-gated in the adapter; OpenHands 1.60.1 declares no elicitation, so expected to end the turn instead (section 4) | Only if the provider refuses a request | as above; Opus 4.8 $5 / $25, 1M | Opus 4.8: "Active (legacy)", "Released May 28, 2026", retirement "Not sooner than May 28, 2027" |

Every id above is in CLI 2.1.220's bundled catalog and was released on or before the CLI's build day (published to
npm 2026-07-24T23:11:21.821Z; the image's SDK manifest says "built 2026-07-24", repo record `evidence/S-03.3-D-1-image-source-read.md` line 132). No wildcard.

### Sources and integrity

| Source | Path (`<session scratch>/e059/...`) | Check | Result |
|---|---|---|---|
| `@agentclientprotocol/claude-agent-acp` 0.63.0 | `work/dl/claude-agent-acp-0.63.0.tgz`, extracted `work/x/acp/package` | registry `dist.integrity` read live 2026-11-14 vs tarball sha512; extracted files vs tarball members; repo image record | sha512 `/Ylytz6K...u12XwlA==` equal; `dist/index.js` sha256 `260aac90...dacd` equals the image record (`evidence/S-03.3-image-adapter-check.md` line 112); `dist/acp-agent.js` sha256 `f086c295...1600` equals its tarball member |
| `@anthropic-ai/claude-code` 2.1.220 (wrapper) | `work/dl/claude-code-2.1.220.tgz` | registry sha512 | `ogBrvwkq...R2Auyw==` equal |
| `@anthropic-ai/claude-code-linux-x64` 2.1.220 | `work/dl/claude-code-linux-x64-2.1.220.tgz`, binary `work/x/cclinux/package/claude` (275,012,592 B) | registry sha512; binary vs tarball member | sha512 `3CGFCnI0...4DZKWvzQ7Q==` equal; binary sha256 `674f61f20ff306f3100cf9200e4c36c4b70278b5bef2884549819b942a89c863` equal to its member |
| OpenHands SDK 1.60.1 wheel | `review/wheel/openhands_sdk-1.60.1-py3-none-any.whl`, extracted `review/sdk` | sha256 vs lock (`f6efa8f8...eb6b`) | equal |

**CLI digest in the repo:** no repository record pins a digest of the `claude` binary (E-05.9 record, "No repository
record pins a CLI digest; the binary's identity with the image's is E-05.11's to show"). The image runs the
Agent SDK's platform binary `@anthropic-ai/claude-agent-sdk-linux-x64/claude` (adapter `claudeCliPath`,
`acp-agent.js` lines 221-246), not this package; decision 0023 section 3 asserts they are hash-identical, which
nothing in this investigation verified (the image was not read).

**Not among the sources:** `@anthropic-ai/claude-agent-sdk` 0.3.220's `sdk.mjs` (the SDK between adapter and CLI).
Statements about how an SDK option becomes a CLI argument are therefore **(inference)**.

CLI citations are byte offsets into the binary above (the minified JavaScript region, about 246.9 M to 260.7 M).

### Determinations

#### 1. How the adapter applies `acp_model`

Two paths, both taken on every new session:

1. **Session `_meta`.** OpenHands sends `{"claudeCode": {"options": {"model": <acp_model>}}}` with `session/new`
   (`openhands/sdk/settings/acp_providers.py` `build_session_model_meta`, line 614-629; `session_meta_key="claudeCode"`,
   line 396; call at `agent/acp_agent.py` line 3400). The adapter spreads `_meta.claudeCode.options` into the Agent
   SDK's `query()` options (`acp-agent.js` line 4092 `const userProvidedOptions = sessionMeta?.claudeCode?.options`;
   line 4147 `...userProvidedOptions,`), so the SDK receives `model: <acp_model>`. That the SDK turns it into the
   CLI's `--model` is **(inference)** (SDK not read); the CLI keeps a start-up model as `Ot.initialMainLoopModel`
   (`SK()`, @246913697) and a later switch as `Ot.mainLoopModelOverride` (`Aw()`, @246913651); the main-loop model
   is `mj()` = override, else initial, else `ANTHROPIC_MODEL`, else settings `model` (@249334277), resolved by `vi()`
   (@249353682) or, if unset, the default `KA()`.
2. **Protocol call.** After `session/new` OpenHands calls `session/set_config_option(configId="model", value=<acp_model>)`
   (`_maybe_set_session_model`, `acp_agent.py` lines 831-888; `supports_set_session_model=True`,
   `acp_providers.py` line 394). The adapter (`acp-agent.js` lines 3190-3262) accepts the value only if it matches a
   row of the session's model picker: exact value; else `resolveModelPreference` (line 4970): exact value or display
   name, then a row whose `resolvedModel` equals the value (a non-`default` row first, line 4993), then substring and
   token matching restricted by a family-version check (`modelVersionsCompatible`, line 4927). The canonical row
   value is passed on: `query.setModel(resolvedValue)` (line 3257). Comment at line 3219: "This lets callers use
   human-friendly aliases like "opus" or "sonnet" instead of full model IDs".

**Aliases are accepted, and so is a full id.** The picker rows come from the CLI (`nqe`, @249538979: each row carries
`value` and `resolvedModel`, `default` resolving to `KA()`). In the native profile environment the rows are
`default` (resolves `claude-sonnet-5`), `sonnet` (`claude-sonnet-5`), `opus` (`claude-opus-5`), `haiku`
(`claude-haiku-4-5-20251001`) (section 2). So:
- `acp_model: "claude-sonnet-5"` matches the `sonnet` row through `resolvedModel` and becomes `setModel("sonnet")`;
  the CLI then resolves `sonnet` from its bundled catalog to `claude-sonnet-5`.
- `acp_model: "sonnet"` matches the `sonnet` row exactly; same result at this pin.
- `opusplan`, `best`, `default` are handled by the tokenizer (`opusplan` -> `opus`; `best`/`default` -> no token,
  `acp-agent.js` lines 4945-4951); `best` and `opusplan` are not picker rows here.

**An unknown id is not refused at create.** If no row matches, the adapter throws "Invalid value for config option
model" (line 3241); OpenHands logs "Could not set model %r on ACP server %s (%s); the session will use the server
default" and continues (`acp_agent.py` lines 878-886; docstring lines 842-856: "a model the live session won't
accept degrades to the server default rather than failing"). Separately, an id that reached the CLI through path 1
is added to the picker as a "Custom model" row (`jug`, @249536344: when `mj()`/`SK()` names a model no row matches,
`t.push(TJn(i)??{value:i,label:i,description:"Custom model"})`), which would then let path 2 select it and send it
to the API, where an unknown id would fail at the first turn **(inference: API behaviour not observed)**. Either way
the create's `acp_model` is not proof of the model used; the first turn's evidence must show it (section 7).

The adapter never adds `ANTHROPIC_MODEL` or a settings `model` (none admitted), so its own initial pick is the
`default` row and it skips its own `setModel` (`getAvailableModels`, lines 5178-5236, `skipSetModel` when no input).

#### 2. CLI 2.1.220: default primary, alias table, known ids

**Built-in catalog, static** ("Hand-maintained baked-in model catalog", `Skl` @247195473; parsed once,
`PFr=Vr(()=>{let e=G8m().safeParse(Skl);...})`, `yQ=PFr`, @247211678; no remote refresh path in that code).

**Aliases** (`m1e=["sonnet","opus","haiku","fable","best","sonnet[1m]","opus[1m]","fable[1m]","opusplan"]`,
@248838049) resolve through `vi()` (@249353682) and the catalog's alias table (@247207803):

| Alias | First party (Anthropic API, OAuth) in 2.1.220 | Source |
|---|---|---|
| `sonnet` | `claude-sonnet-5` | `aliases:{... sonnet:{default:"claude-sonnet-5", per_provider:{bedrock:"claude-sonnet-4-5", ...}}` @247207803; `CT()` @249337540 -> `h7n()` @249337633 |
| `opus` | `claude-opus-5` | `opus:{default:"claude-opus-5",...}`; `EE()` @249337365 -> `N6e()` @249337456 |
| `haiku` | `claude-haiku-4-5-20251001` | `haiku:{default:"claude-haiku-4-5"}`; `B6e()` @249337689 -> `Vji()` @249337782; catalog `claude-haiku-4-5` first-party id `claude-haiku-4-5-20251001` (@247196883) |
| `fable` | `claude-fable-5` | `fable:{default:"claude-fable-5"}`; availability gated by `Qkt()` @249334911 (needs server-provided model options or `ANTHROPIC_DEFAULT_FABLE_MODEL`) |
| `best` | `fable` when available, else `opus` | `best:"fable"` @247207803; `iRc()`/`sRc()` @249334553 |
| `opusplan` | `opus` in plan mode, else `sonnet` | `vi()` @249353682; `LP()` @249338189 |
| `sonnet[1m]`, `opus[1m]`, `fable[1m]` | the same id with the 1M hint | `vi()`; Sonnet 5 and Opus 5 are natively 1M in the catalog |

Each env var `ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU,FABLE}_MODEL` overrides its alias (`CT`, `EE`, `B6e`, `w5r`);
none is admitted in the native profile.

**Known full ids** (catalog `id` -> first-party wire id; `$Zh` @249099364, wire mapping `$oe` @249354982):
`claude-3-5-haiku` -> `claude-3-5-haiku-20241022`; `claude-haiku-4-5` -> `claude-haiku-4-5-20251001`;
`claude-3-5-sonnet` -> `claude-3-5-sonnet-20241022`; `claude-3-7-sonnet` -> `claude-3-7-sonnet-20250219`;
`claude-sonnet-4-0` -> `claude-sonnet-4-20250514`; `claude-sonnet-4-5` -> `claude-sonnet-4-5-20250929`;
`claude-sonnet-4-6`; `claude-sonnet-5`; `claude-opus-4-0` -> `claude-opus-4-20250514`; `claude-opus-4-1` ->
`claude-opus-4-1-20250805`; `claude-opus-4-5` -> `claude-opus-4-5-20251101`; `claude-opus-4-6`; `claude-opus-4-7`;
`claude-opus-4-8`; `claude-opus-5`; `claude-fable-5`; `claude-mythos-5`. Not known: anything released after
2026-07-24, including `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-haiku-5-5`, `claude-fable-5-1`, `claude-fable-5-2`.

**Default primary by plan** (`iQt()` @249340613 -> `cRc()` @249341338):

```
function cRc(){if(ii()){if(F1e()||jot()||G6e())return{setting:KO()?Y8(EE()):EE(),envFamily:"opus"}}
else if(rm())return{setting:KO()?Y8(EE()):EE(),envFamily:"opus"};let e=Hn();...return{setting:CT(),envFamily:"sonnet"}}
```

`ii()` = a claude.ai OAuth subscriber (@250375669); `F1e()` = `Ca()==="max"`, `jot()` = Team with
`default_claude_max_5x`, `G6e()` = Enterprise usage-based (@250376724-250376905). So, when the plan is known:
Max, Team Premium, Enterprise usage-based -> `claude-opus-5` (with the `[1m]` hint when `KO()`); Pro, Team Standard,
other Enterprise -> `claude-sonnet-5`; non-subscriber Anthropic API -> `claude-opus-5`. This agrees with the current
documentation: "Before v2.1.280, `default` resolved to Sonnet 5 on Pro and Team Standard, and to Opus 5 on Max,
Ultra, Team Premium, Enterprise, the Anthropic API, ... from v2.1.219." (model-config).

**But in the native profile the plan is not known to the CLI, so the default is `claude-sonnet-5` on every plan.**
With `CLAUDE_CODE_OAUTH_TOKEN` the CLI builds its auth record without asking the server:
`ms=Vr(()=>{if(rf())return null;if(Z.CLAUDE_CODE_OAUTH_TOKEN)return{accessToken:Z.CLAUDE_CODE_OAUTH_TOKEN,...,
scopes:Beu(),subscriptionType:Z.CLAUDE_CODE_SUBSCRIPTION_TYPE||null,rateLimitTier:Z.CLAUDE_CODE_RATE_LIMIT_TIER||null}`
(@250391341). `Ca()` returns that `subscriptionType` (@250376606; its override `u4i()` is constant false in this
build, @249109417), so `Ca()` is `null`; `F1e/jot/G6e` are false and `cRc` falls through to `CT()` =
`claude-sonnet-5`. `ii()` is still true (default scopes `["user:inference"]`, `Beu` @250366661; `$5="user:inference"`
@247432548). The other inputs of `iQt` are empty: the organization default and model-access entitlements come only
from the bootstrap fetch, which is skipped under the nonessential-traffic switch (`Nl_` @257496877:
`if(ca())return w("[Bootstrap] Skipped: Nonessential traffic disabled"),null`), and the configuration directory
starts empty. `KO()` is false when `ii()&&Ca()===null` (@249352850), so no `[1m]` hint.
`CLAUDE_CODE_SUBSCRIPTION_TYPE` would change this, but it is not one of the four admitted names.

**Picker rows in this environment** (`Fug` @249532077, subscriber branch without a known plan): `Default`
(value `null` -> `default`), `opus` (`DWi`), `haiku` (`qBc` @249541934), and `sonnet` inserted after Default by
`xWi`/`Oug`/`$ug` (@249531188-249531489) because the default's family is `sonnet`. The 1M rows are absent
(`Doe()` false for a subscriber without cached extra-usage state, @249330294 / `rRc` @249329723).

#### 3. Secondary (small/fast) model

`RP()` (@249333609): `ANTHROPIC_SMALL_FAST_MODEL` if set; otherwise, because `eQt()` (@249333441) is true on the
first-party host (`Hn()==="firstParty"&&(Yd()||...)`; `Yd()` true without `ANTHROPIC_BASE_URL`, @249103452), it
returns `B6e()` = `ANTHROPIC_DEFAULT_HAIKU_MODEL` or `claude-haiku-4-5-20251001`.

Uses found in 2.1.220 (call sites of `RP()` and of the small-query helper `g6`, which sends `model:RP()`,
@259010505):
- `generate_session_title` (@258590117), `tool_use_summary_generation` (@254334778), `web_fetch_apply`
  (WebFetch page processing, @255012186), `rename_generate_name`, `teleport_generate_title`;
- `count_tokens` (`cBs` @257214113);
- the background-agent classifier (`Icd` @254487533, flag `tengu_bg_classifier_config` default
  `useSmallFastModel:!0`);
- prompt and agent hooks without a model (@259156474, @259163392; none configured in the native profile);
- the quota check (`DZg` @251992097), which `ELu` skips under the switch (`if(ca())return`, @251992374);
- API-key verification (`Wtp`), not used with OAuth.

Provider documentation: `ANTHROPIC_DEFAULT_HAIKU_MODEL` - "Model ID that the `haiku` alias resolves to, also used for
background functionality"; `ANTHROPIC_SMALL_FAST_MODEL` - "[DEPRECATED] Name of Haiku-class model for background
tasks" (env-vars).

**Pinning it would need a fifth secret name.** The only pins are those env vars (or `CLAUDE_CODE_SUBAGENT_MODEL`
for sub-agents), a settings `env`, or settings `modelOverrides` (`Sbc` @249104871). The create admits exactly four
secrets (decision 0023 section 3); OpenHands 1.60.1 has no `acp_env` (`evidence/S-03.3-slice2-qualification-create.md`
line 96); the user settings directory is the per-conversation empty `CLAUDE_CONFIG_DIR`. So: **disclosed, not
pinned**.

**`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`** does not switch the secondary model off. It removes the quota-check
call and the bootstrap fetch (above); the title, summary, WebFetch and token-count calls read show no such gate in
the excerpts read (a gate elsewhere is not excluded). Its effect on model choice is indirect and favourable: with the
bootstrap skipped, no server-supplied organization default, entitlement list or extra model option (such as Fable)
can change the default or the picker.

#### 4. Sub-agents and other model switches

- Resolution (`tte` @254073377): `CLAUDE_CODE_SUBAGENT_MODEL` first (in 2.1.220 it overrides even the tool
  parameter; the current documentation says "Before v2.1.251, this variable overrode both the per-..."), then the
  Agent tool's `model`, then the agent definition's `model`, else `inherit` (the main-loop model).
- The Agent tool's parameter: `model:v.enum(["sonnet","opus","haiku","fable"]).optional()` (@256081018), "Optional
  model override for this agent... If omitted, uses the agent definition's model, or inherits from the parent." So
  the main agent can choose Opus or Haiku for a sub-agent on its own.
- Built-in agents: `claude-code-guide` `model:"haiku"` (@252889722); `statusline-setup` `model:"sonnet"`
  (@252909151); `Explore`, `Plan` and `fork` `model:"inherit"` (@252894938, @252899939, @252144711).
- `fable`: named, but `Qkt()` reports it unavailable without server-provided options; whether an Agent call with
  `fable` is refused or substituted was not traced.
- **Refusal fallback:** routes `Vug={bio:"claude-opus-5",cyber:"claude-opus-4-8"}` (and for an Opus 5 primary
  `{cyber:"claude-opus-4-8"}`), @249543748, used by `UWi` (@249542226). The adapter: "Declaring the kind is the
  opt-in: the CLI never emits an undeclared dialog, and the flow instead degrades to the classic refusal error ending
  the turn" (lines 4177-4180), and declares it only when the client advertises form elicitation. OpenHands initializes
  with `conn.initialize(protocol_version=1)` (line 3229) and declines every elicitation (lines 1722-1734). Expected,
  **(inference)**: no fallback model runs; a refusal ends the turn. The adapter also handles a completed fallback
  (`syncModelAfterRefusalFallback`, line 2031), so whether any undeclared automatic path exists in the CLI is not
  settled.
- **Availability fallback** (`x5r` @249350157) uses only `--fallback-model`/`fallbackModel`, which the adapter does
  not set.

#### 5. Provider status of each id (read 2026-11-14, about 22:18 UTC)

Pages (fetched as markdown with `curl`, saved under `<session scratch>/models/docs/`):
`https://platform.claude.com/docs/en/about-claude/models/overview.md`,
`https://platform.claude.com/docs/en/about-claude/model-deprecations.md`,
`https://platform.claude.com/docs/en/models/{sonnet-5,haiku-4-5,opus-5,opus-4-8}/overview.md`,
`https://code.claude.com/docs/en/model-config.md`, `https://code.claude.com/docs/en/env-vars.md`,
`https://code.claude.com/docs/en/costs.md`, `https://code.claude.com/docs/en/sub-agents.md`.

| Id | Deprecations table (verbatim row) | Model page | Released vs CLI build (2026-07-24) |
|---|---|---|---|
| `claude-sonnet-5` | "claude-sonnet-5 \| Active \| N/A \| Not sooner than June 30, 2027" | "**Legacy.** Released June 30, 2026." "Model ID: `claude-sonnet-5`" "Context window: 1M tokens · Max output: 128K tokens · Input pricing: $2 / MTok · Output pricing: $10 / MTok"; Status "Active (legacy)" | before |
| `claude-haiku-4-5-20251001` | "claude-haiku-4-5-20251001 \| Active \| N/A \| Not sooner than October 15, 2026" | "**Legacy.** Released October 15, 2025." "Model ID: `claude-haiku-4-5-20251001`"; "Claude API alias \| `claude-haiku-4-5`"; "Context window: 200K tokens · Max output: 64K tokens · Input pricing: $1 / MTok · Output pricing: $5 / MTok" | before |
| `claude-opus-5` | "claude-opus-5 \| Active \| N/A \| Not sooner than July 24, 2027" | "**Legacy.** Released July 24, 2026." "Context window: 1M tokens · Max output: 128K tokens · Input pricing: $5 / MTok · Output pricing: $25 / MTok" | same day; present in the catalog |
| `claude-opus-4-8` | "claude-opus-4-8 \| Active \| N/A \| Not sooner than May 28, 2027" | "**Legacy.** Released May 28, 2026." $5 / $25, 1M | before |
| `claude-fable-5` | "claude-fable-5 \| Active \| N/A \| Not sooner than June 9, 2027" | not fetched | in the catalog |

Definitions (deprecations page): "**Active:** The model is fully supported and recommended for use." "**Legacy:** The
model will no longer receive updates and might be deprecated in the future." "Anthropic notifies customers with
active deployments for models with upcoming retirements, providing at least 60 days' notice before model retirement
for publicly released models."

Current models (overview): `claude-fable-5-2`, `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`; none is
known to the pinned CLI. The model-config page's alias table ("Anthropic API | Opus 5.5 | Sonnet 5.5 | Haiku 5.5")
describes current CLI versions, not 2.1.220.

**Usage characteristics on a subscription.** The pages read give API prices, not subscription weights; that usage
limits scale with these prices is **(inference)**. Relative weight per token by API price: Haiku 4.5 0.5x,
Sonnet 5 1x, Opus 5 / Opus 4.8 2.5x. The CLI's own catalog marks Sonnet 5 as pricing tier `tier_3_15` and shows a
"$2/$10 per Mtok · promo through ..." label with list price "$3/$15" (`wug`, about @249524084), so the Sonnet 5 price
could rise to $3 / $15 after a promotion ends; the provider pages read today state $2 / $10.

**Risk to disclose for the secondary.** Haiku 4.5's "Not sooner than October 15, 2026" has passed with no
deprecation notice listed. A notice would give at least 60 days. If it is retired, the pinned CLI's background calls
fail and only an env var (a fifth name) or a CLI upgrade fixes it.

#### 6. `--bare`

`claude-agent-acp` 0.63.0 never passes `--bare`: no occurrence of `--bare` or `CLAUDE_CODE_SIMPLE` in any
`dist/*.js`; its only extra CLI argument is `"replay-user-messages"` (`acp-agent.js` lines 4190-4193), and it starts
the CLI through the SDK's `query()` with `pathToClaudeCodeExecutable` (line 4189). The adapter refuses subscriptions
only under its own `--hide-claude-auth` argument (line 264-266, line 4296), which `acp_args: []` does not pass. In
the CLI, bare mode is `function rf(){return Yt(process.env.CLAUDE_CODE_SIMPLE)||NTi("--bare")}` (@247212993), and
under it the OAuth record is `null` (`ms=Vr(()=>{if(rf())return null;...` @250391341). Documentation (env-vars,
`CLAUDE_CODE_SIMPLE`): "OAuth tokens and keychain credentials are not read ... Equivalent to passing `--bare`". The
SDK's own argument list was not read, so "the SDK adds no `--bare`" is **(inference)** (no adapter option asks for
it).

### 7. Recommendation for the template's `acp_model`

**`claude-sonnet-5` (full id).**

- It is exactly the model the pinned CLI already chooses in the native profile on every plan (section 2). So the
  failure modes of section 1 (a rejected `set_config_option` silently keeping the server default) cannot change the
  model: the pin and the fallback coincide. Pinning `claude-opus-5` instead would run Sonnet 5 silently if the pin
  were ever rejected.
- A full id is self-describing in the record, equals the id the API reports back in each response's `model`, fits the
  admission grammar (`MODEL_NAME`, `integrations/dispatch/create_secrets.py` line 322), and is the id the provider's
  deprecations table tracks. The adapter maps it onto the `sonnet` row by `resolvedModel` (line 4993), so it works
  today.
- An alias (`sonnet`) works identically at this pin but is a moving pointer: its meaning is the CLI catalog's, and a
  CLI upgrade changes it without the template changing (current CLIs resolve `sonnet` to Sonnet 5.5). That is close
  to a wildcard by decision 0023 section 7's standard. `default` is worse: it depends on plan, environment and server
  state.
- Trade-off of the full id: after a CLI upgrade whose `sonnet` no longer resolves to `claude-sonnet-5`, the adapter may
  not find a matching row, and OpenHands then degrades to the default **silently** (a log warning only). The full id
  turns that into a detectable mismatch rather than a silent drift, but only if something checks.
- Either way, E-05.11 should verify the effective model from the first turn rather than trust the create: the
  model in the session's `configOptions`/current model reported over ACP, and the `model` field of the turn's
  assistant messages (the adapter reads `message.message.model`, line 2611). Expected: `claude-sonnet-5` for the main
  loop, `claude-haiku-4-5-20251001` for background calls. Any other id is a stop.

**What the record should disclose rather than pin:** the secondary `claude-haiku-4-5-20251001`; sub-agent models the
agent may choose (`claude-opus-5`, `claude-haiku-4-5-20251001`, and `claude-fable-5` unestablished); the refusal
fallback ids `claude-opus-5` and `claude-opus-4-8` (expected not to run under OpenHands).

### Findings beyond the questions (for the engineering manager)

1. **The assigned repository's settings can change the model.** The adapter starts the SDK with
   `settingSources: ["user", "project", "local"]` (line 4145); `project` and `local` settings are read from the
   working directory (`/workspace`, the assigned repository) **(inference: CLI-side loading not traced)**. A
   committed `.claude/settings.json` could set `model`, `availableModels`, `modelOverrides` (`Sbc` @249104871) or an
   `env` block, changing the primary, the secondary or the picker. The docs say `CLAUDE_CODE_OAUTH_TOKEN` is
   "Ignored in project and local settings", which implies other env vars are not. For E-05.5's demo repository this
   is controllable; for D1 generally it is a residual.
2. **`CLAUDE_CODE_SUBSCRIPTION_TYPE` decides the default.** Without it, the plan-based default (Opus 5 on Max) does
   not apply; with it, the default would change. The template pin makes this moot for the main loop, as long as the
   pin is accepted.
3. **OA-12's earlier selection** (`evidence/OA-12-OA-22-provider-access-package.md` line 56: primary
   `claude-sonnet-5`, secondary "`claude-haiku-4-5` or `claude-haiku-4-5-20251001`") is consistent with this; the
   pinned CLI sends the dated form `claude-haiku-4-5-20251001`.
4. **No digest of the CLI binary is pinned in the repository**; the binary read here is the npm release, not the
   image's copy (decision 0023's "hash-identical" is E-05.11's to show).

### Not done

No install; the CLI, adapter and SDK were not executed; no provider API call; no credential or host Claude
configuration read; the image was not read. The Agent SDK 0.3.220's `sdk.mjs` was not read. The GrowthBook flag
values at run time, the `fable` sub-agent path and any automatic refusal fallback were not traced.
