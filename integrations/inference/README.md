# Inference broker (`integrations/inference/`)

Plan leaf S-03.2 ("Implement and qualify the inference-access plane without a model"), **slice 1: the broker
core, built and tested offline**. Authority:
[decision 0015](../../decisions/0015-inference-broker-placement-provider-credential-custody-and-guest-inference-endpoint.md)
as amended by its amendment 1 (which governs where they disagree), decisions 0007 points 4 and 5,
[0009](../../decisions/0009-managed-data-root-and-configuration-contract.md) and 0013 point 6; the ACP
families of [`evidence/S-03-acp-coding-provider-recommendation.md`](../../evidence/S-03-acp-coding-provider-recommendation.md)
sections 1.1 to 1.5. Slice record: [`evidence/S-03.2-slice1-broker-core.md`](../../evidence/S-03.2-slice1-broker-core.md);
the qualification tools of slice 4: [`evidence/S-03.2-slice4-qualification-tools.md`](../../evidence/S-03.2-slice4-qualification-tools.md);
the provider-key containment search of slice 5:
[`evidence/S-03.2-slice5-key-containment-search.md`](../../evidence/S-03.2-slice5-key-containment-search.md).

Plan leaf S-03.5 ("Bind the broker's real-provider start to a recorded provider-envelope authorization"),
**slice 1**, adds the provider envelope and the start precondition ([below](#the-provider-envelope-plan-leaf-s-035-slice-1)):
built and tested offline only.

Plan leaf S-03.6 ("Retire the harness's spending enforcement from the broker, the provider envelope and the D1
grant") removes the spending limit, the cumulative cap and the attempt budgets, and keeps every security control
([Retired by S-03.6](#retired-by-s-036)): built and tested offline only.

Plan leaf S-03.3 ("Qualify the first ACP coding provider through the broker") adds two qualification tools, built
and tested offline only ([below](#route-and-model-discovery-s-033-slice-3-part-two) and
[below](#the-real-key-containment-search-s-033-slice-4)): the discovery mode of the qualification launcher with the
reader that turns a run's audit into a proposed family pin, and the real-key mode of the containment search.

Plan leaf E-05.10 ("Qualify native provider access through a host CONNECT-only tunnel, with no credential") adds
the native execution profile's provider tunnel beside the broker ([below](#the-provider-tunnel-e-0510)): built and
tested offline only; its live qualification waits on the Owner's act OA-31 (a).

The broker is the host-side process of the trusted management domain (inventory principal
`inference-broker`) that alone holds the model provider's key and alone issues inference access. Standard
library only, under the tools interpreter; it imports no litellm and no other HTTP client.

**Nothing here has run outside a test process.** Running the broker, its host listeners, the provider key,
the guest forward and hardening change, external egress and any model call are each their own explicit Owner
act (decision 0015, "Owner acts"; OA-12). No model identifier is assumed: the shipped allowlists are empty.

## Files

| Path | What |
|---|---|
| `inference_broker.py` | The broker (`Broker`: issue, revoke, status, admission, the pass-through), its two loopback listeners, the configuration loader, the usage extractors, the integration-store journal, the audit log, the credential set command and the command line; the provider envelope's start precondition (S-03.5: `live_envelope`, `authorize`, the held `Authorization`, the `envelope` command) |
| `inference_envelope.py` | The provider envelope (S-03.5 slice 1; `aieh-provider-envelope/2` since S-03.6): the `envelope` block's check (the retired spending keys refused), the canonical document, its digest and the canonical operation manifest. Standard library only; it opens nothing |
| `families.json` | The declared API families (`aieh-inference-families/1`) |
| `provider_tunnel.py` | The native profile's provider tunnel (E-05.10; decision 0023 section 4): a CONNECT-only tunnel on `127.0.0.1` at the profile's declared port that admits exactly `api.anthropic.com:443` with a TLS ClientHello naming that host, holds no credential, terminates no TLS, logs targets, decisions and byte counts only; `serve`, `stop` and `census` ([below](#the-provider-tunnel-e-0510)) |
| `tests/test_provider_tunnel.py` | E-05.10's tunnel offline: the loopback-only listener and its declared port; the admitted CONNECT spliced byte for byte to a fake origin through the outbound seam, called with the origin only; every refusal before the 200 (other hosts, ports, IP literals in each spelling, every request that is not a CONNECT, malformed heads, an offered credential) and after it (an absent, other or encrypted server name, a fragmented or malformed hello, a timeout) with its logged reason and no outbound connection; a real TLS stack's ClientHello; the log's fields and the absence of payload; no TLS, credential or broker module loaded; the stop; `serve`, the census and `stop` in a process of its own |
| `tests/tunnel_child.py` | The child process of the lifecycle test: `serve` over a test context (temporary run and log directories, an ephemeral port) |
| `inference_census.py` | The broker's live census (S-03.2, before the first provider call): what the running broker's process listens on and is connected to, read from the operating system's per-process TCP and UDP tables (Windows, through `ctypes`; elsewhere UNKNOWN), judged against the configuration and the broker's audit (`upstream-connect` lines) under `CENSUS_RULE`; its command (`--once`) |
| `inference_control.py` | The dispatcher's side (S-03.2 slice 3): the two listener ports read through the broker's own loader (`dispatcher_ports`), the forward target (`forward_target`: the inference listener only), the control client (`ControlClient`: status, a grant by fingerprint, revocation, and for the qualification one grant (`issue`, slice 4); `127.0.0.1` only), an attempt token's fingerprint (`token_fingerprint`) and the `issue` command (slice 4) |
| `inference_qualification.py` | The qualification-only commands (S-03.2 slice 4): the qualification launcher (`broker`: the broker's own `serve` with a synthetic key from standard input, loopback `http` upstreams only) and the fake upstream (`fake-upstream`); S-03.3 slice 3 part two: the launcher's discovery mode (`discover`) and the reader of a run's audit (`propose-pin`, `propose_pin`), which writes a proposed family pin and applies nothing |
| `inference_key_search.py` | The provider-key containment search (S-03.2 slice 5): the synthetic key held in memory, searched for raw and in its encodings over byte surfaces, with positive controls; its command line (`search`). Standard library only; it imports nothing of the broker. Since E-05.9 a `Search` takes the public `prefix` its body form strips (the synthetic one by default) and searches a surface of named in-memory byte strings (`objects`), which the native token's outbound search (`integrations/dispatch/native_token_search.py`) uses for a result bundle's inflated objects; the synthetic key's command line, forms, views and controls are unchanged |
| `inference_real_key_search.py` | The real-key containment search (S-03.3 slice 4): the key of the broker's credential entry, read through the broker's credential factory under a named Owner act, held in memory, and searched by `inference_key_search.run` (its forms, views, surfaces and controls); its command line (`search`) |
| `tests/broker_support.py` | Synthetic fixtures: an in-memory credential provider, a settable clock, a fake upstream per family (`FakeUpstream`, an in-process server on an ephemeral `127.0.0.1` port) and `Rig` (a broker over a fixture store and audit directory) |
| `tests/test_config.py` | The shipped declarations; every refusal of the declaration file and of `components.inference_broker`; the decision 0009 loader's refusal of secret-shaped keys under the component; the `config` command |
| `tests/test_usage.py` | The usage extractors over whole and byte-by-byte streams and bodies |
| `tests/test_grants.py` | Socket-free: issuance and its refusals (a budget refused, `BUDGET_RETIRED`), readiness, revocation and expiry with their receipts, journal failures, every admission refusal, no refusal for a request count, a usage count or unknown usage, refusal responses; a check that every stable code appears in a test |
| `tests/test_credential_set.py` | `credential-set` over an in-memory provider and a fixture store |
| `tests/test_credential_enter.py` | `credential-enter` (S-03.3, the Owner's act 2) over an injected console and an in-memory provider: refused unless the console is interactive and for an existing entry without `--replace`, both before any prompt; every rule of the key shape refused by name, never by value; stored through `credential-set`'s custody path; nothing derived from the key in the output; the real console check on a pipe, a file and the null device |
| `tests/test_egress.py` | The egress code path read from the module's syntax tree; `connect_upstream`; the census of the modules `serve` loads beside the broker (the envelope and its read side): no network module, no connector |
| `tests/envelope_support.py` | The provider envelope's fixtures (S-03.5): the real authorization recorder over the owner suite's fake Gitea (in memory) writing into a throwaway store, contexts whose provider, audit directory and wait raise if asked, a `Rig` holding a minted authorization, an injected connector; a correctly formed S-03.5 `/1` document and manifest of the same families (S-03.6) |
| `tests/test_spending_retired.py` | S-03.6's proof (it replaces S-03.5's `test_cap.py`): the cap and its ledger gone from the broker; a bound broker writes and reads no `inference/envelope/` receipt, and S-03.5's ledger receipts in a store are neither read nor changed; after each outcome S-03.5 counted as unknown (a 2xx answer without usage, a cut stream, a client leaving mid-stream, a request written and never answered, a connection cut while sending, a connection refused while sending, a refused connect, an answer outside 2xx, a broker error) the next request is admitted; a client gone mid-stream against a fake upstream; `BROKER_STOPPING` at the stop for a bound and a loopback family, in process and over a keep-alive connection; a hand-built authorization refused at admission (integration) |
| `tests/test_selection.py` | S-03.5 slice 2's proof rows C2 to C7: a delegated selection recorded by the real act starts the broker (no commit id in its receipt); a head another actor reserved, the product manager decided or written as an Owner record; a selection under an earlier envelope; a configured model not selected; a decision source that reads no selection or answers badly; a request and an issuance outside the held selection refused, a selected model passed through (integration) |
| `tests/test_envelope.py` | S-03.5 slice 1's proof rows: the block, the document, the golden digest and manifest, the `envelope` command; every start refusal of `serve` (no block, missing, unsettled, expired, replayed, another origin, expiry or selection, another target, a non-canonical manifest, a receipt over a `/1` document, hand-written receipts, a decision source that raises or answers badly, unbound families, the interim selection refusals); the retired spending keys refused; the start with its `authorization` member; the envelope kind recorded through the recorder; loopback upstreams as before; the held authorization at start and at admission, and the expiry while serving |
| `tests/test_broker_http.py` | Both listeners against the three fake upstreams: pass-through, key substitution, streaming, no budget (an answer without usage, a cut stream and an upstream error stop nothing), revocation and expiry on the wire, refusals, egress to the configured origin only, exclusive ports, the audit and the I7 scan; the refused-request audit (S-03.3 slice plan D-4): path, query parameter names and model in their bounded grammars, a credential in a path, a name, a query value, a header or the model never recorded |
| `tests/test_serve.py` | `serve` end to end in the test process |
| `tests/test_stop.py` | The stop (S-03.2 fix-forward, before act A2): the stop event, the interrupt handler and the forced exit of a second interrupt, `POST /v1/stop` and `inference_control.py stop`, `BROKER_STOPPING` from the stop's start, the bounded drain (a request cut by the stop audited `BROKER_STOPPED`; an upstream that never answers does not hold the stop); on Windows, `serve` in a process of its own stopped by a real `CTRL_BREAK_EVENT`, by `inference_control.py stop`, and forced by a second one; the security review's stop findings: a body read straddling the stop's start refused (M01), the cut wait (M25), a request cut while its upstream connection is made sends nothing (S3), a cut request claimed before it is interrupted (N1), a pass-through blocked on the upstream ends with the stop on Windows (N2), the handler that sets only a flag and no deadlock at a 0 s slice (S4), the ceilings within 3 s |
| `tests/test_reach.py` | Provider-side reach refused (S-03.3 fix-forward, before the first paid call): each rule of the `anthropic-messages` checker (`mcp_servers`, `container`, a tool type other than `custom`, a `tools` that is not a list or an entry that is not an object, a `url` or `file` source and a `container_upload` block anywhere, tool results included) refused `PROVIDER_REACH_REFUSED` with its audit `reach` member and nothing sent upstream; plain model calls and custom tools admitted; a family with no checker refused at start on an upstream that is not loopback (`FAMILY_REACH_UNCHECKED`); a body nested too deeply to parse refused `BODY_NOT_JSON` over the wire (a control body `CONTROL_BODY_INVALID`; an upstream answer unknown usage), never a handler error |
| `tests/test_account_scope.py` | Account-scope headers never forwarded (S-03.3 fix-forward): every header whose name starts with `anthropic-workspace` or `anthropic-organization` stripped, not refused, for each family, streamed and not, against the fake upstreams; the audit's `stripped_headers` (names only) |
| `tests/test_query.py` | Exact query-string equality (S-03.3 fix-forward; `pass` retired): `anthropic-messages` declares exactly `beta=true`, admitted and forwarded unchanged; every other form (case, repetition, addition, percent-encoding, `&`, `#`, an empty query) refused `QUERY_NOT_ALLOWED` before anything is sent; the description output; the qualification's fake upstream answering the declared query |
| `tests/test_census.py` | The live census: every verdict branch of its rule on synthetic tables, the four table layouts and a fake `iphlpapi`, the broker's pid in its status and start receipt, the `upstream-connect` line written at connect time, the command's record and exit codes; on Windows a real census of `serve` in a process of its own (PASS idle and with a request in flight, FAIL on an extra listener, connection or UDP socket in the broker's process) |
| `tests/test_body.py` | Strict bodies (S-03.3, the security review's B1, N4, N6): a key repeated at any depth refused `BODY_DUPLICATE_KEY` on the inference listener with nothing forwarded (the `model` allowlist and the reach rule bypasses) and `CONTROL_BODY_INVALID` on the control listener; a case-folded `mcp_servers` or `container`; a `Content-Length` of non-ASCII digits; a body that is not strict UTF-8 without a BOM (`BODY_ENCODING_INVALID`); a header value holding any control character but HTAB (`HEADER_VALUE_INVALID`) |
| `tests/test_headers.py` | The forwarded-header allowlist per family (S-03.3, the security review's S1): the shipped declarations and the refusal of one that names or covers a never-forwarded or account-scope header; only declared headers reach each fake upstream, every other one stripped and named; `HEADER_VALUE_INVALID` (a folded header), `CONTENT_ENCODING_REFUSED`, `CONTENT_TYPE_REFUSED`, nothing forwarded |
| `tests/test_reach_allowlist.py` | Provider-side reach by allowlist (S-03.3, the security review's S2): content block types and source types outside the allowlists refused `PROVIDER_REACH_REFUSED` wherever they are read (a replayed `server_tool_use`, server tool results, `mcp_tool_use`, a `web_page` source, unknown types), nothing forwarded; the allowed shapes forwarded; a tool schema or tool input holding a `source` (opaque to the provider) admitted |
| `tests/serve_child.py` | The child process of `test_stop.py` and `test_census.py`: the broker's `serve` with its real wait over a loopback-only test context (a fake upstream, an in-memory credential provider, a temporary directory; never the managed context) |
| `tests/test_control.py` | `inference_control.py`: the ports, the forward target's refusals, the token fingerprint, the client against a real broker on ephemeral ports (status, grant, revocation, issuance, the broker's refusal codes, an unreachable or foreign port), the `issue` command (the token to a pipe only; a terminal, a file or a device refused first) and its only connection, to `127.0.0.1` |
| `tests/test_qualification.py` | `inference_qualification.py`: the launcher's refusals (upstreams, provider id, key), its end-to-end run with the key substituted and only its fingerprint recorded, `serve` without a flag for it and the credential factory never returning its provider; the fake upstream's refusals, answers and records |
| `tests/test_key_search.py` | `inference_key_search.py`: its forms (the standard encodings at every alignment, the body, the fragments), a copy across a read boundary, every positive control for keys of 16 to 128 body characters and each control failing when the view it controls is broken, the gzip, SQLite, HTTP, tar, tree and environment views with their incomplete cases, the command line (a pipe only, every refusal without the key, a planted copy found, nothing printed, logged or written) |
| `tests/test_discovery.py` | S-03.3 slice 3 part two: the reader over audit records (exact routes and models with their answers and query parameter names; the flags; nothing outside the audit's grammars carried; grants, attempts and families), the key paths of an admitted body (names only, arrays collapsed, bounded) and their flags, `propose-pin` (a new file outside the checkout only, `families.json` unchanged, its refusals), and `discover` end to end against its own fake upstream (the proposal of the run; refusals before the key is read; the port freed; a secondary model planted in a nested field flagged by its path, never its value; the `fake-upstream` command's records unchanged) |
| `tests/test_real_key_search.py` | S-03.3 slice 4: the real-key search over a fake credential provider (a synthetic key, and a key of a provider key's shape made at run time): the entry read only after every argument is checked and under a named act, never standard input; not found, and planted copies found, on trees, files and an SQLite file; the provider's and the entry's refusals; a withheld report; no copy of the key printed or written |
| `tests/test_key_search_boundary.py` | The search end to end at the broker's exposure boundary: the broker under the qualification launcher with the fake upstreams, every byte that crossed its listeners, its outputs, store and audit directory searched (not found; found on the bytes it sends upstream); a planted leak (a reflecting upstream, a copy in the audit directory and in a database) found where it was planted |

## The declared families

`families.json` declares each API family the broker passes through, untranslated (amendment 1 point 3):

```json
{"id": "anthropic-messages", "status": "provisional",
 "consumer": "Claude Code's ACP adapter ...",
 "routes": [{"method": "POST", "path": "/v1/messages"}],
 "query": ["beta=true"],
 "auth": {"header": "x-api-key", "scheme": null},
 "headers": {"names": ["content-type", "accept", "anthropic-version", "anthropic-beta", "user-agent", "x-app"],
             "prefixes": ["x-stainless-"]},
 "usage": "anthropic-messages"}
```

| Family | Consumer | Routes (provisional) | Auth header | Usage from |
|---|---|---|---|---|
| `anthropic-messages` | Claude Code's ACP adapter (`ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`) | `POST /v1/messages`, with no query or exactly `beta=true` | `x-api-key: <credential>` | `message_start` and the last event carrying `usage` (`message_delta`); or the body's `usage` |
| `openai-responses` | Codex's ACP adapter in API-key mode | `POST /v1/responses` | `Authorization: Bearer <credential>` | the last event's `response.usage` (`response.completed`); or the body's `usage` |
| `openai-chat` | a native direct-LLM agent; a local model server as the degenerate upstream | `POST /v1/chat/completions` | `Authorization: Bearer <credential>` | the last chunk with a non-null `usage`; or the body's `usage` |

- `routes`: the exact method and path pairs admitted. A path is matched as a string: no normalization, no
  prefix, no trailing slash, no percent-decoding. Every set is **provisional**: it is pinned from observed
  traffic at the plan leaf that first runs the family, and the extractors with it.
- `query`: `refuse` (a request target with a query is refused), or an exact, finite list of whole query strings
  (name=value pairs of `[A-Za-z0-9._~-]` joined by `&`, at most 256 characters each; S-03.3 retired `pass`). The
  request target's raw query, the bytes after its first `?`, is admitted only when it is byte-equal to one of
  them: no parsing, no decoding, no reordering, no case folding. A target with no `?` is admitted as before; one
  ending in a bare `?` (an empty query) is refused, and so is every other form (`beta=TRUE`,
  `beta=true&beta=true`, `beta=true&x=1`, `beta=%74rue`, a trailing `&`, a `#`): `QUERY_NOT_ALLOWED`. An admitted
  query is forwarded unchanged. `anthropic-messages` ships exactly `["beta=true"]` (the OA-12 package, row P:
  only the form observed at S-03.3's discovery run is pinned); the two OpenAI families ship `refuse`.
- `headers` (S-03.3, the security review's S1): the request header names (lower case) and name prefixes (ending
  with `-`) the family forwards; every other request header is stripped and named in the audit. `anthropic-messages`
  declares `content-type`, `accept`, `anthropic-version`, `anthropic-beta`, `user-agent`, `x-app` and the prefix
  `x-stainless-`; the two OpenAI families `content-type`, `accept`, `user-agent`, `openai-beta` and the prefix
  `x-stainless-`. A declaration that names or covers a header the broker never forwards (a credential-bearing or
  hop-by-hop header, `Host`, `Content-Length`, `Accept-Encoding`, `Connection`) or an account-scope header is
  refused (`DECLARATION_INVALID`). The lists are written from the clients' public shapes: S-03.3's discovery run
  records the header names Claude Code actually sends (its audit's `stripped_headers`), and changing an allowlist
  after it is a reviewed change.
- `auth`: the header that carries the credential, read inbound (the attempt token) and written outbound (the
  provider key), with its scheme (`null` or `Bearer`).
- `usage`: the extractor (`anthropic-messages`, `openai-responses` or `openai-chat`). Counts are `input`
  (including reported cache tokens), `output` and `total`; `unknown` when absent, unreadable or cut off.

A declaration names no model, upstream or provider; `load_declarations` refuses anything malformed
(`DECLARATION_INVALID`).

## Configuration: `components.inference_broker` of `config.yml`

Read through the decision 0009 loader, which refuses any secret-shaped key (`password`, `token`, `secret`,
`key`, `credential`) anywhere; the broker applies the same rule again to its component.

```yaml
components:
  inference_broker:
    control_port: 18431            # 1024-65535, required to serve
    inference_port: 18432          # 1024-65535, different from control_port
    max_request_bytes: 33554432    # default 32 MiB (1 to 256 MiB)
    max_ttl_s: 86400               # the longest token lifetime, default one day (at most 7 days)
    upstream_timeout_s: 600        # default 600 (1 to 3600)
    families:
      anthropic-messages:
        provider: <provider id>    # the credential entry's user; omitted only for a loopback upstream
        upstream: https://<provider API host>   # an origin only
        models: []                 # exact, verified identifiers; empty: every issue is refused
```

The ports and values above are placeholders, not decided values. `upstream` is an origin only:
`https://host[:port]`, or `http://` with a loopback IP literal (a local model server); no path, query,
fragment or user information. A non-loopback upstream needs a `provider`. Model names are exact identifiers
(letters, digits, `.`, `_`, `:`, `@`, `/`, `-`): no wildcard, no duplicate. Unknown keys and undeclared
families are refused. `python -I -B integrations/inference/inference_broker.py config` prints the effective
configuration and touches no credential, store or listener. The `envelope` block (next section) is checked here
when present, never required here: `serve` requires it.

## The provider envelope (plan leaf S-03.5, slice 1)

`serve` refuses, before it reads the provider key or opens a listener, any family whose upstream is not loopback
(`Origin.loopback`: an IP literal the interpreter calls loopback; a host name, `localhost` included, never is)
unless the integration store holds the **governing, confirmed, unexpired** authorization recorder receipt
(decision 0012) of operation kind `provider-envelope` whose target is the canonical digest of the **live
envelope**, and whose merged manifest is the canonical manifest of that envelope. A configuration whose upstreams
are all loopback starts exactly as before: no store read, no envelope needed (a present block is only checked).
**Built and tested offline only**; no real authorization has been recorded.

**The live envelope** is a projection of the one snapshot `serve` reads (once) and serves: the provider id, the
one upstream origin and the selected models come from the families whose upstream is not loopback (the bound
families); only what has no home there is a block of its own:

```yaml
components:
  inference_broker:
    envelope:
      expires_at: "2026-12-31T00:00:00Z"   # quoted: YYYY-MM-DDTHH:MM:SSZ (UTC), a security validity window
      selection: envelope                  # envelope | delegation
```

The values are placeholders, not decided values. An unquoted timestamp (YAML reads it as a time) is refused
(`CONFIG_ENVELOPE_INVALID`), never normalized. The envelope carries **no spending limit**: a block that still
names `limit` or any of `amount`, `currency`, `enforced_by` or `cap` is refused (`CONFIG_ENVELOPE_INVALID`, the
keys named), never ignored ([Retired by S-03.6](#retired-by-s-036)). The bound families must share one provider and
one origin, and no loopback family may name that provider (`ENVELOPE_FAMILIES_UNBOUND`): under an envelope the
provider key goes to the envelope's origin only.

**The canonical document** (`aieh-provider-envelope/2`): exactly `format`, `provider`, `origin`
(`https://host:port`), `expires_at`, and `selection`:
`{"by": "envelope", "models": {<family>: [<ids, sorted>]}}`, or `{"by": "delegation", "record":
"decision:0018", "point": "3"}`. Its **digest**, the authorization's target, is `sha256:` and the sha256 of the
document as canonical JSON (the integration store's rule: sorted keys, no whitespace, UTF-8). **The canonical
manifest** `operations/<operation>.json`: `operation`, `kind` (`provider-envelope`), `target`, `expiresAt` and
`envelope` (the document, in clear, so the Owner reads it in the recorder's challenge summary), JSON with a
two-space indent and one final LF. `serve` regenerates it from the live envelope and the receipt's operation id
and requires its sha256 to be the receipt's manifest digest, so what the Owner was shown is exactly what is
enforced. A change of either form is a new format: `/2` dropped `/1`'s `limit`, so a receipt recorded over a
`/1` document names a digest no live envelope has and authorizes no start (`ENVELOPE_MISMATCH`, or
`ENVELOPE_REPLAYED` when a later `/1` receipt supersedes a `/2` one); none was recorded for a real provider.

**Authorizing it** (an Owner act; not run here): `inference_broker.py envelope --operation ID` prints the live
document, its digest and the canonical manifest's path, text and digest; the text travels inside the JSON report
as a string, so no console changes its line endings (write it to `operations/<ID>.json` as UTF-8 with LF line
endings, byte for byte). It is proposed and authorized as any operation, through `authorization_recorder.py
prepare` and `record` (`integrations/owner/README.md`), which do not change and know nothing of the kind.

**Which receipt governs** (the read side, `integrations/owner/envelope_decisions.py`, handed to `serve` as
`Context.authorization`): the recorder's receipts of operation kind `provider-envelope`, in reservation order;
the last confirmed one governs, so a later authorization ends an earlier one at the next start whatever its
expiry. In this order: a receipt under the recorder's prefix that cannot be read or is not the recorder's
(`ENVELOPE_RECORD_INVALID`); none confirmed and none unsettled (`ENVELOPE_NOT_AUTHORIZED`, also with no decision
source); a later one `reserved`, `dispatched` or `unknown` (`ENVELOPE_AUTHORIZATION_UNRESOLVED`: resolve it with
`authorization_recorder.py resolve`); the live digest an earlier, superseded authorization's
(`ENVELOPE_REPLAYED`); another digest, or a merged manifest that is not the canonical one (`ENVELOPE_MISMATCH`:
another origin, provider, expiry or selection, or a `/1` document); the expiry reached
(`ENVELOPE_EXPIRED`). Then the selection: with `selection: envelope`, the bound families' configured models are
inside the digest, and no bound family naming one is `MODEL_SELECTION_MISSING`. With `selection: delegation`
(slice 2) the governing selection is the last confirmed position of the one series `model-selection/v1/<n>`,
recorded by the engineering manager under decision 0018 point 3 (`integrations/owner/selection_recorder.py`):
none is `MODEL_SELECTION_MISSING`; a head that is not a well-formed `select-models` record of the selection
recorder (another actor, another decider, an Owner record) is `MODEL_SELECTION_NOT_AUTHORIZED`; a head resting
on another envelope receipt (a selection does not carry to a new envelope) is `MODEL_SELECTION_RECEIPT_MISMATCH`.
Under either authority a configured model of a bound family that the selection does not select is
`MODEL_NOT_SELECTED` (the configuration may not widen it), and none left is `MODEL_SELECTION_MISSING`. The held
selection is the configured models; `issue` and admission refuse any other model of a bound family
(`MODEL_NOT_SELECTED`, 403), after the existing checks. The per-request check reads the model where the
admission reads it: the request body's top-level `model`, which is where the three declared families name it;
a family that names its model elsewhere (a path segment, a header, a nested field) needs a check of its own
before it is declared. A delegated selection is read from the series' **last confirmed** position only: an
unsettled selection receipt (reserved or dispatched, a write that stopped) is never in force and has no file
effect to resolve (the act writes only the store and a copy of the record), so it is harmless and is not
waited for. A refused start exits 2, writes no receipt and no audit line (it may create an empty
integration store where none exists).

**What the broker holds.** `authorize` returns one frozen `Authorization` (the receipt key, the operation id,
the decision id, the digest, the expiry, the provider, the origin and the selected models);
`Broker.start()` refuses a bound family unless it holds an object `authorize` returned in this process
(`ENVELOPE_NOT_AUTHORIZED`; a copy or a hand-built one is not) whose provider and origin the family has
(`ENVELOPE_MISMATCH`). At admission a request of a bound family is refused
when the held authorization is not one `authorize` minted (`ENVELOPE_NOT_AUTHORIZED`, 503), when the family's
provider or upstream is not the held one (`ENVELOPE_MISMATCH`, 503), and from the expiry on
(`ENVELOPE_EXPIRED`, 403); an answer already streaming completes, loopback families and the control listener
keep working, and nothing is written at the moment of expiry. Supersession takes effect at the next start. The
start receipt and the status answer carry an `authorization` member (receipt, operation, decision, digest,
`expires_at`, the selection: `by`, `models` and, when delegated, its `record`, `point`, `receipt` and
`decision`) only when an envelope is bound. It never carries the selection record's revision.

**What it is not.** A control against accident, convenience and a stale or edited `config.yml` at the moment of
the act, not against a process of the Owner's account, which can write the store as the recorder does, read the
credential entry or forward from loopback (decision 0010 point 1); it does not authenticate the Owner (decision
0012 point 9). With only loopback upstreams `serve` still reads the real entry if one exists and sends it to the
loopback upstream that names its provider, as before (disclosed).

## Tokens: issue, revoke, status (the control listener)

The control listener answers only a direct loopback call (`Host` exactly `127.0.0.1:<port>`, no `Origin`
header, JSON bodies as `application/json`, at most 64 KiB, with no key repeated in any object); it is never
forwarded. Every process of the
Owner's account can call it (disclosed, decision 0013 point 6).

| Call | Body | Answer |
|---|---|---|
| `POST /v1/grants` | `conversation_id`, `attempt_id` (canonical lower-case UUIDs), `family`, `models` (a non-empty subset of the family's allowlist), `ttl_s` (1 to `max_ttl_s`); no `budget` (a body carrying one, of any value, is refused `BUDGET_RETIRED`) | 201: the token (returned once), its fingerprint, the grant and its receipt |
| `POST /v1/grants/revoke` | `token_fingerprint`, `trigger` (a decision 0007 point 5 trigger: `attempt end`, `suspected exposure`, `definition revocation`, `policy revision`, `expiry`, `owner direction`), `revoker` (1 to 200 printable characters, `valid_revoker`); or, in place of `token_fingerprint`, `conversation_id` and `attempt_id` (E-05.6: the attempt's one grant, for a dispatcher that lost the issue's answer) | 200: the grant, revoked, with its revocation receipt; by conversation and attempt with no grant, 200 `tombstoned` (`aieh-inference-attempt-tombstone/1`: the attempt is tombstoned and its issue is refused from then on, `GRANT_ATTEMPT_REVOKED`); `GRANT_UNKNOWN` when no grant has that fingerprint, or when the attempt's grant ended with an earlier run or is of another conversation; `GRANT_ALREADY_REVOKED` |
| `GET /v1/grants/<fingerprint>` | | the grant: state, lifetime, counts, usage, receipts |
| `GET /v1/status` | | the broker's `pid` (for the live census), listeners, the provider key's fingerprint and source, each family and whether it is ready, grant counts, the audit file |
| `POST /v1/stop` | an empty JSON object `{}` | 202: `aieh-inference-broker-stop/1` (`state` `stopping`, `began`: whether this call began the stop, `stopped_by`); the stop begins before the answer is sent and `serve` is woken after it ([The stop](#the-stop)) |

A token is `aieh-inf-` and 43 random URL-safe characters. The broker keeps only its sha256 digest and its
fingerprint (`sha256:` and 16 hex digits). One grant per attempt, durably: its receipt
`inference/attempt/<attempt id>/grant` (`aieh-inference-grant/2`, fingerprint only, no budget; `/1` carried the
retired one) is written and read back
before the token is returned, and a second grant for the same attempt is refused even after a restart.
Revocation takes effect at once (the next request answers 401) and then writes
`inference/attempt/<attempt id>/revocation` (`aieh-inference-revocation/1`: fingerprint, attempt,
conversation, trigger, revoker, and the per-attempt summary of requests, refusals, usage and bytes). An
expired token is revoked with trigger `expiry` at its next use or at the next control call. A receipt that
cannot be written leaves the revocation in force and is retried at each control call (`receipts_pending` in
the status). Receipts go to the integration store, never the effects store. Grants live in memory only: they
end with the broker process (its stop writes an audit line naming the live fingerprints).

Revocation by conversation and attempt (E-05.6) is the dispatcher's way to end a grant whose token it never
received (decision 0015 section 3.3: the dispatcher revokes at attempt end): the issue's answer was lost (a
timeout or an unreachable listener after the request was sent) or was not a valid grant of the attempt
(`ControlClient.issue` then names the answer's fingerprint on its `CONTROL_ANSWER_INVALID`, and the dispatcher
revokes by it as well, when that answer named the same conversation and attempt). The broker keeps one grant
per attempt, so the selector names at most one. When it finds none, the broker writes a tombstone receipt under
the attempt's grant receipt key (`inference/attempt/<attempt id>/grant`, format
`aieh-inference-attempt-tombstone/1`, durable): an issue for that attempt arriving later, in this run or after a
restart, is refused (`GRANT_ATTEMPT_REVOKED`). An issue's grant receipt and registration, and a revocation by
attempt's lookup and tombstone, run one at a time under the broker's attempt lock, and the store key is the same:
whichever comes first, no grant of the attempt is live after a revocation by attempt (an issue in flight
registers, then the waiting revocation revokes it). `ControlClient.revoke_attempt` makes the call. The dispatcher journals each issue before it is sent and each revocation in the
integration store (`integrations/dispatch/README.md`, "The D1 stage's create secrets").

## Inference: admission and pass-through

A request on the inference listener is admitted only when, in this order: exactly one token is presented in a
declared auth header shape; it is one this broker issued, unrevoked and unexpired; it arrives in its own
family's auth header; the method and path are in that family's route set (and the query rule holds); the
broker's own stop has not begun (`BROKER_STOPPING`) and, for a bound family, the envelope holds; the body has one
`Content-Length` of ASCII digits (no chunked body) within
`max_request_bytes`, is strict UTF-8 without a byte order mark (else `BODY_ENCODING_INVALID`: the JSON parser
alone would also read UTF-16, UTF-32 and a BOM), is a JSON object read strictly (a key repeated in any object, at
any depth and after escapes are decoded, is refused `BODY_DUPLICATE_KEY`: the broker must check the document the
provider reads) and names a `model` that is in both the token's list and the family's allowlist; no header value
holds a control character (0x00 to 0x1F except HTAB, and 0x7F: CR and LF of obsolete line folding included,
`HEADER_VALUE_INVALID`), the body is not declared encoded (`Content-Encoding` absent or `identity`, else
`CONTENT_ENCODING_REFUSED`) and its `Content-Type` is one `application/json` with at most a `charset=utf-8`
parameter, present whenever there is a body (else `CONTENT_TYPE_REFUSED`); the body asks the provider to reach or
run nothing outside the request ([Provider-side reach](#provider-side-reach)); and the token appears nowhere in
what would be forwarded (target, forwarded headers, body). The request is then counted, and passed through
unchanged to the family's one upstream origin: the same method, target and body; of the client's headers, **only
those the family declares** (`headers` in `families.json`, [above](#the-declared-families); an allowlist since
the security review's S1), and never a hop-by-hop one, `Host`, `Content-Length`, `Accept-Encoding` (the broker
asks for `identity`, so that usage can be read), a credential-bearing header (`Authorization`, `X-Api-Key`,
`Api-Key`, `Proxy-Authorization`, `Cookie`, `Forwarded`, `X-Forwarded-*`, `X-Real-Ip`) or a header that selects
the provider account's scope (a name starting with `anthropic-workspace` or `anthropic-organization`; no
declaration may name or cover one). Every other header is stripped, not refused, and its name recorded in the
audit line (`stripped_headers`); then the family's auth header with the provider key. The answer is streamed back as it arrives (status, headers,
body; chunked when the upstream gives no length), its usage read on the way. Accounting and the audit line
are written before the answer's last bytes, so a client's next request already meets them. An upstream error
status is passed through as it is.

**No budget.** A grant has no request or token budget (S-03.6): its request count, its usage and its answers
without usage are counted for the audit and the per-attempt summary as information only, and none of them
refuses, closes or narrows anything. After a 2xx answer without usage, a stream the upstream cut off
(`UPSTREAM_STREAM_BROKEN`) or a client gone mid-stream (`CLIENT_GONE`), the grant admits its next request. What
bounds a grant is its model list, its lifetime (`max_ttl_s`) and its revocation, then the provider account's own
limits.

**The stop.** The broker's own stop sets a stopping state under its lock first; from then on a request is
refused `BROKER_STOPPING` (503) at admission, before anything of it is written upstream, so a handler still alive
after the listeners stop (a keep-alive connection) forwards nothing more. After the stop the audit is closed, so
such a refusal is not answered: the connection is closed instead. How a stop is asked and how it ends:
[The stop](#the-stop).

**Provider-side reach.** The authorized D1 scope is plain model calls (OA-12 package, section 3 point 5): a
request must not ask the provider to reach or run anything outside the request. A family's reach checker reads
the parsed JSON body of every admitted request; `anthropic-messages` refuses, with `PROVIDER_REACH_REFUSED` (400):

- a top-level `mcp_servers` or `container` key, or one that case-folds to either, present at all, whatever its
  value (rule `top-level-key`); and a top-level key that case-folds to `messages`, `system` or `tools` without
  being exactly it (`Messages`, `System`, `Tools`: rule `top-level-key`, name the key);
- a `messages` that is present and is not a list of objects (rule `messages-shape`), and a `system` that is
  present and is neither a string nor a list of objects (rule `system-shape`);
- an entry of `tools` whose `type` is present and is not `custom` (rule `tool-type`): every server tool (web
  search, web fetch, code execution) and every provider-defined tool type, known or not, fail closed; Claude
  Code's own tools are custom tools;
- a `tools` that is present and is not a list, or a `tools` entry that is not an object (rule `tools-shape`, name
  `tools`): a shape the rule cannot read is refused, never passed on;
- a content block whose `type` is not one of `text`, `image`, `document`, `tool_use`, `tool_result`, `thinking`,
  `redacted_thinking`, `search_result` (rule `block-type`; an allowlist since the security review's S2): in
  `messages[].content`, in `system` when it is a list, and in the content of a `tool_result`, a `search_result`
  and a source of type `content`; so a replayed `server_tool_use`, any server tool's `*_tool_result`,
  `mcp_tool_use`, `container_upload` and every type not yet known are refused. A content that is neither a
  string nor a list of objects is refused too (rule `content-shape`);
- on an admitted content block, wherever a content block is read (the positions above, nested tool results
  included), a `source` that is an object whose `type` is not `base64`, `text` or `content` (rule `source-type`:
  `url`, `file`, `web_page`, a missing type, anything else), and an `image` or `document` whose `source` is not
  an object;
- anywhere else in the body (a whole-body walk, an unknown top-level key's subtree included), an object whose
  `source` is an object of a type outside `base64`, `text`, `content` (rule `source-type`). The walk skips exactly
  two subtrees, opaque to the provider: each `tools[i].input_schema` and each `tool_use` block's `input` (the
  engineering manager's rulings after the re-review and the reviewer's delta check). So a tool schema with a
  property named `source` and a tool input holding `{"source": {...}}` are admitted; a `source` beside them, in the
  same tool or block, is not. A `search_result`'s `source` is its citation string.

The allowlists are written from the provider's public request shapes. S-03.3's discovery run may show that the
pinned client (Claude Code) needs another block or source type; adding one is a reviewed change.

The refused request's audit line carries `reach`: `{"rule", "name"}`, the name being the key or the type in the
audit's bounded name grammar (`null` outside it), never a value. A family with no reach checker (the two OpenAI
families today) is refused at start when its upstream is not loopback (`FAMILY_REACH_UNCHECKED`); on a loopback
upstream it is unchanged. The walk is iterative, so a deeply nested body is checked whole.

**A body nested too deeply to parse.** The JSON parser raises `RecursionError`, not a JSON error, on a body nested
deeper than the interpreter's recursion limit. Admission refuses such a body `BODY_NOT_JSON` (400) like any body
that is not JSON, with nothing forwarded and no handler error; the control listener refuses one
`CONTROL_BODY_INVALID`, and an upstream answer nested so deeply is read as unknown usage.

**Egress.** `connect_upstream` is the one place that opens a connection, to the configured upstream origin of
the admitted token's family: `https` with the system's trust roots and hostname check, or `http` to a
loopback address only. It reads no proxy variable. The broker resolves the upstream name on the host; it
opens nothing else (no cost map, telemetry or update check). This is a code-path control plus disclosure
(decision 0015 section 5.1), shown by the syntax-tree census in `tests/test_egress.py`. At connect time (http.client
connects at a request's first byte) the connection writes an `upstream-connect` audit line with the peer it reached
(IP and port), its local address, the origin, the family and the attempt id: the broker's own record of its
egress, which the live census compares with the operating system's view.

**The live census (S-03.2; `inference_census.py --once`).** Before the first provider call, and around each live
step, the census observes at the operating system what the running broker's process (the `pid` of its status
answer; the start receipt carries it too) listens on and is connected to: on Windows the per-process TCP tables
(IPv4 and IPv6, `GetExtendedTcpTable` with `TCP_TABLE_OWNER_PID_ALL`) and UDP tables (`GetExtendedUdpTable`) through
`ctypes`, starting no process. Its rule (`CENSUS_RULE`, fixed in the code and copied into every record): the
broker's listeners are exactly `127.0.0.1:<control_port>` and `127.0.0.1:<inference_port>` of the configuration
(a wildcard address, another port, an IPv6 listener or a missing one: FAIL); it owns no UDP endpoint; every other
TCP connection it owns is inbound on one of those listeners from a loopback address, or outbound to a configured
origin's port with a remote IP the audit recorded for that origin (else FAIL). Tables that cannot be read (not
Windows, the API failing) are UNKNOWN, never PASS; so is an outbound connection while the audit cannot be read. The
record (`aieh-inference-census/1`) states that DNS resolution happens in the system resolver and is not observed,
and that a census is one moment (the audit is the continuous record). It prints the record and exits 0 PASS, 1
FAIL or UNKNOWN, 2 refused (`CENSUS_CONFIG_INVALID`, `CENSUS_BROKER_UNREACHABLE`, `CENSUS_STATUS_INVALID`). The
S-03.3 driver (`tools/guest.py acp-qualification`) runs it before any model call and again after the call.

**Listeners.** Both bind `127.0.0.1` only, without address reuse (on Windows with `SO_EXCLUSIVEADDRUSE`, so
no other socket can take the port), and do no name lookup. Neither writes a log of its own: the audit is the
broker's log.

## The stop

S-03.2 fix-forward, required before the Owner's act A2 (the OA-12 package, section 5 item 1): `serve` used to wait
indefinitely, which a Ctrl-C does not interrupt on Windows (measured by the architect on CPython 3.12.10), so the
only stop was a kill.

- **The stop event.** The broker owns one stop event. `serve` waits on it in slices of `STOP_POLL_S` (0.25 s), the
  interval at which the interpreter can run a signal handler: a functional bound, not a wait for work.
- **Asking for it.** SIGINT (Ctrl-C), SIGBREAK (Ctrl-Break, Windows) and SIGTERM, where the platform has them,
  ask for it: the handler records the signal's name in a plain flag and touches nothing else (no lock, no event:
  an `Event.set()` inside a handler can deadlock against the main thread's own wait on it, the security review's
  S4), and `serve`'s loop, at its next slice, begins the stop from the main thread. On Windows the C runtime
  delivers every console control event other than Ctrl-C, the console's close included, as SIGBREAK, so the same
  handler receives it (not tested: a close event cannot be generated by a test); Windows ends a closing console's
  processes about 5 s after the event, and documents that it ends them as soon as the handler returns, which the C
  runtime's handler does at once, so a stop on a console close is not assured (not verified). So does `POST /v1/stop` on the control listener, under the same rules as every control call (direct
  loopback caller, `application/json`), which is the stop that works from a session with no console:
  `inference_control.py stop`. The control stop begins the stop before it answers, and wakes `serve` only once
  its answer is sent.
- **The clean stop.** From its start every new request is refused `BROKER_STOPPING`; both listeners close;
  requests already admitted are given at most `STOP_DRAIN_CEILING_S` (2 s) to finish; each one still running is
  then cut: marked cut and its settlement claimed under the broker's lock first (so that its own pass-through,
  woken by the cut, cannot settle it as an upstream failure), then its client's connection shut (no further byte
  and no terminating chunk reaches it), then its upstream connection shut and closed (on Windows a shutdown alone
  does not wake a pass-through blocked on the upstream; the handle is closed), and audited with code
  `BROKER_STOPPED`, never as an upstream answer. A request whose upstream connection was still being made when it
  was cut is aborted as soon as the connection is made, before any byte is sent (the security review's S3); the pending
  revocation receipts and the `broker-stop` audit line (`stopped_by`: the signal's name, `control` or `stop`;
  `requests_cut`; `live_grants_ended`) are written; `serve` prints its status and exits 0. It never waits on a
  client or an upstream beyond those ceilings (a cut request's own thread gets at most `STOP_CUT_CEILING_S`, 1 s,
  to finish its audit line: 3 s in all, within the about 5 s Windows gives a closing console).
- **A second interrupt** during a stop that has not finished exits at once with exit code 3 (`FORCED_EXIT`),
  writing nothing further. One after the stop has finished is ignored.

The broker is not supervised (OA-12 package section 3, assumption 8): nothing restarts it.

## Audit

One append-only JSON line per request (`aieh-inference-audit/1`) in a new file per broker run,
`<managed root>/persistent/logs/inference/audit-<stamp>-<random>.jsonl`: `time`, `attempt_id`,
`conversation_id`, `token_fingerprint`, `family`, `method`, `path`, `query_names`, `model`, `unrecorded`,
`request_bytes`, `response_bytes`, `status`, `upstream_status`, `latency_ms`, `usage` and `code` (the refusal
code, or `CLIENT_GONE`, `UPSTREAM_STREAM_BROKEN`, `BROKER_ERROR`, `BROKER_STOPPED`: cut by the broker's
stop); plus `broker-start`, `upstream-connect` (`attempt_id`, `family`, `origin`, `peer` and `local`, each
`{address, port}`: written when an upstream connection is made), `broker-stop` (`stopped_by`, `requests_cut`,
`live_grants_ended`) and
`handler-error` lines. A request refused `PROVIDER_REACH_REFUSED` adds `reach` (`rule` and `name`); an admitted
request whose headers were stripped (any not declared by its family, except `Host`, `Content-Length`,
`Accept-Encoding`, `Connection` and its auth header, which the broker consumes) adds `stripped_headers` (`names`,
in the bounded name grammar below, and the count of the others, `unrecorded`), never a value. An admitted
request's line has its declared route and admitted model. A refused request's line (the S-03.3 slice plan's D-4, for route and model discovery without a model call against the
fake upstream) has its path, its query parameter **names** (sorted, at most 16) and, when it presented a
grant's token, the `model` of its JSON body (read, if the refusal came first, from the body the refusal
drains anyway); each only in a bounded grammar: a path segment or a name of at most 32 characters from
`[A-Za-z0-9._~-]`, a model in the broker's model grammar (128 characters), none holding the token prefix or
anything the I7 scan finds. What fails that is counted under `unrecorded` (`path`, `query_names`, `model`),
never written. Never a query value, a header, any other part of a body, the token or the provider key. A
secret the broker does not hold that a client places in a path segment, a name or the model within that
grammar is not recognized (disclosed). Every line,
receipt, refusal and control answer passes the I7 scan of F-06.3 (the broker's guard holds the provider key
and every issued token, and refuses anything 40-hex token-shaped) first; a line that fails it is withheld
(`EXPOSURE_FOUND`), an answer that fails it is replaced by an `EXPOSURE_FOUND` refusal. The provider key's
fingerprint is recorded once, in the broker's start receipt (`aieh-inference-broker-start/1`), with its `source`:
the name of the credential provider it was read from (`windows-credential-manager` on Windows,
`stdin-qualification` under the qualification launcher).

## The provider key

```
<key on standard input> | <tools python> -I -B integrations/inference/inference_broker.py credential-set --provider <id>
```

An Owner-run act. The key is read from standard input only (a terminal is refused: pipe it in; never argv,
the environment, a file or `config.yml`), must be printable ASCII without spaces (8 to 4096 characters,
optionally followed by one newline), and is stored through the credential provider of
[`integrations/credentials/`](../credentials/README.md) as the entry `AIEH model provider` with the provider
id as its user, then read back. Its receipt is an `aieh-credential-act/1` (`provision`, or `rotate` when an
entry existed; trigger `owner direction`) in the managed integration store, fingerprints only. The output
shows the fingerprint, never the key. **Not run** in this slice: the tests use an in-memory provider only.
There is one entry, so the broker holds one provider's key at a time; a family whose `provider` is another
id is not ready. Rotation is at the provider, then this command again and a broker restart.

### The Owner's key entry: `credential-enter` (S-03.3)

```
<tools python> -I -B integrations/inference/inference_broker.py credential-enter --provider <id> [--replace]
task inference:credential-enter -- --provider <id> [--replace]
```

The Owner's act 2 of OA-12 (the package's section 5 item 4, the architect's conditions): in his own console
window he pastes the dedicated provider key once, at a hidden prompt. `credential-set` stays as it is, for a key
piped on standard input.

- **A real console only.** Standard input must be an interactive console: on Windows its handle must have a
  console mode (`GetConsoleMode`), not merely pass `isatty`; elsewhere it must be a terminal. Otherwise it refuses
  before any prompt (`KEY_CONSOLE_REQUIRED`).
- **Echo off.** The key is read once through `getpass`, which reads the console itself on Windows. Its fallback,
  which would read standard input with echo, is refused (`KEY_CONSOLE_REQUIRED`), never taken.
- **Key-shaped only.** The value must begin `sk-ant-api`, hold only `[A-Za-z0-9_-]` and be 40 to 512 characters
  long (a broad bound: no exact length is verified for the provider's keys). An admin key (`sk-ant-admin`), an
  empty value and any whitespace are refused; nothing is stripped. A refusal (`KEY_NOT_KEY_SHAPED`) names the rule
  it failed (`empty`, `whitespace`, `admin-key`, `prefix`, `characters`, `length`) and asks for the key to be
  pasted again; it never shows the value or anything derived from it.
- **An existing entry** is refused unless `--replace` is given (`KEY_ENTRY_EXISTS`, before any prompt); with it the
  receipt's verb is `rotate`. A cancelled prompt (Ctrl-C or end of input) stores nothing (`KEY_ENTRY_CANCELLED`).
- **Custody.** The key is held in memory only (no file, environment variable, argument, log or receipt) and
  stored through `credential-set`'s path: the entry `AIEH model provider` with the provider id as its user, read
  back, under an `aieh-credential-act/1` receipt in the integration store that records fingerprints only (the
  harness records only the key's fingerprint, OA-12 A1).
- **Output.** Nothing derived from the key: no fingerprint, length or prefix. It prints that the key is stored in
  the entry, the receipt's operation key and state, and a reminder to clear the clipboard. Then restart the broker
  if it is running, so that it reads the stored key.

**Not run** outside a test process: the tests inject the console reader and use an in-memory credential provider;
a real console and the real Credential Manager are not touched.

## The dispatcher's side (`inference_control.py`)

`tools/guest.py` performs the dispatcher's role during bootstrap (decision 0013 point 1) and reaches the
broker only through this module. `dispatcher_ports` reads `control_port` and `inference_port` through
`load_config` (refusing what the broker refuses, and a missing port with `CONFIG_INCOMPLETE`);
`forward_target` gives the port a forward session may target and refuses the control listener's port
(`CONTROL_PORT_REFUSED`) and any other (`FORWARD_PORT_REFUSED`); `ControlClient` calls the control
listener on `127.0.0.1` as it admits callers (status, `GET /v1/grants/<fingerprint>`, revocation, the stop) and
passes the broker's refusal code on (`CONTROL_UNREACHABLE` and `CONTROL_ANSWER_INVALID` otherwise);
`token_fingerprint` checks a token's shape (`TOKEN_SHAPE_INVALID`) and returns only its fingerprint. The
dispatcher's own issuance and revocation for the D1 stage, the token reaching that stage's attempt through the
create's `secrets`, are E-05.6's (`integrations/dispatch/dispatch_inputs.py`, `dispatch` and `end_attempt`, through
`ControlClient`; see `integrations/dispatch/README.md`); the general case, every stage's create secrets from role
profiles, stays A-01.2's and E-03.1's. For the qualification, `ControlClient.issue` and the `issue` command (next
section) ask for one grant.
`guest.py inference-forward` (the forward session) and `job-access-probe --attempt-token-stdin` (the
token steps) use it; see `docs/development.md`, Execution guests.

## The qualification tools (slice 4)

Built for S-03.2's guest qualification (the plan in
[`evidence/S-03.2-slice3-forward-session.md`](../../evidence/S-03.2-slice3-forward-session.md) section 3).
**Not yet verified** outside a test process: running them is part of the Owner's act A2.

- **The qualification launcher**, `inference_qualification.py broker --provider ID`: a separately named command
  (the Overseer's ruling,
  [`evidence/S-03.2-plan-amendment-proposal-child-clause.md`](../../evidence/S-03.2-plan-amendment-proposal-child-clause.md)
  section 5). It runs the broker's own `serve` (`inference_broker.main(['serve'], context)`) with a synthetic
  provider key held in memory, so that the qualification can show the key substituted for the attempt token
  ("substitution shown with a synthetic key") and give the provider-key needle a fingerprint.
  1. It refuses unless every configured family's upstream is plain `http` to a loopback IP literal
     (`Origin.loopback`; `QUALIFICATION_UPSTREAM_REFUSED`) and one such family names `--provider`
     (`QUALIFICATION_NO_FAMILY`). It reads `components.inference_broker` once, and the broker serves that
     snapshot.
  2. The key is read from standard input only (a terminal is refused: `KEY_STDIN_TTY`). It must be
     `aieh-qualification-synthetic-` followed by 16 to 128 letters, digits, `_` or `-` (`KEY_NOT_SYNTHETIC`
     otherwise), a shape no provider's keys have. The prefix is sent upstream as part of the key, so a real
     provider key is refused as it is, and with the prefix added it is not valid at its provider.
  3. The start receipt (`aieh-inference-broker-start/1`) records the key's fingerprint with `source`
     `stdin-qualification`, the name of the launcher's credential provider, never the key; the launcher prints
     the same fingerprint on standard error.
  4. `serve` has no flag or variable for it. The launcher's provider (`SyntheticKeyProvider`) is constructed by
     the launcher only, `credentials.select_provider` never returns it, and it writes nothing (`set` and
     `delete` refuse: `KEY_NEVER_WRITTEN`).

  The broker's receipts and audit lines go where `serve` writes them; the key is written nowhere.
- **The token issue command**, `inference_control.py issue` (finding 3(c) of the slice 3 record): one grant from
  the control listener (`POST /v1/grants`) with `--conversation-id`, `--attempt-id` (default: a new random
  UUID), `--family`, `--model` (repeatable) and `--ttl-s` (the lifetime only: the budget options were retired by
  S-03.6), its answer checked for one
  token of the broker's shape, fingerprint and attempt. The token and one newline go to standard output and
  nowhere else, for a pipe into `guest.py job-access-probe --attempt-token-stdin`; standard error carries only
  `{"attempt_id", "token_fingerprint"}`. Standard output must be a pipe, checked before the configuration is
  read or anything is asked: a terminal is refused (`TOKEN_STDOUT_TERMINAL`), so the token is never shown, and
  so is a file or a device (`TOKEN_STDOUT_NOT_PIPE`), so it is never kept. Limit: a terminal window that is
  itself a pipe (mintty, Git Bash's default window) cannot be told from one; run it in a console (PowerShell).
- **The fake upstream**, `inference_qualification.py fake-upstream --family ID --port PORT [--address ADDR]`: one
  declared family's fake provider on a loopback IPv4 literal (`127.0.0.1` by default; any other address is
  refused, `FAKE_ADDRESS_REFUSED`, before anything binds), a port from 1024 to 65535 (`FAKE_PORT_INVALID`),
  bound exclusively. A request on a declared route of the family gets one fixed answer that is not a model's:
  the family's JSON shape with the text `aieh fake upstream: a fixed answer, not a model` and the usage counts
  1 and 1, which the broker's extractor reads (with no query, or one the family declares exactly, as the broker
  admits it). Another route answers 404, a body without a valid length 411.
  One JSON line (`aieh-inference-fake-upstream/1`) per request goes to standard output before its answer:
  `method`, `path` (a declared route only), `header_names` and `credential_fingerprints` (the fingerprint of
  each value of the family's auth header, its scheme word removed); never a header value or a body. `start`
  and `stop` lines frame them. The qualification shows the substitution by comparing that fingerprint with the
  start receipt's (and with the token's, which must differ).

## The provider-key containment search (slice 5)

S-03.2's proof as amended on 2026-11-11 (Owner decision OA-19) asks that agents cannot read the provider
credential be shown with the synthetic key "searched for at the secret's exposure boundaries ... in its raw form
and its common encodings by a checker that holds it in memory only and reports counts, with a positive control";
a fingerprint search alone is not proof that the raw credential is absent. `inference_key_search.py` is that
checker. **Not yet verified** against a live broker or guest: running it there is part of the Owner's acts A2,
A3 and A4.

- **What it searches for:** the whole key and its body (the key without the public prefix
  `aieh-qualification-synthetic-`), each raw (also what JSON escaping, URL and form encoding, HTML escaping and
  shell quoting give, all identities on this alphabet), as lower- and upper-case hex, as base64 and base64url at
  each of the three alignments, and as UTF-16LE and UTF-16BE; and raw windows of 16 body characters at a stride
  of 8, so a raw run of 23 body characters is found. Never by fingerprint.
- **Views:** the raw bytes in chunks that overlap by the longest needle less one byte (a copy across a read
  boundary is found); a gzip blob decompressed; an SQLite database row by row (a value split across overflow
  pages is whole there; read from an in-memory copy, the file is never opened by SQLite); a tar stream member by
  member with names and link targets; an HTTP/1.x capture message by message, de-chunked and decoded from gzip
  or deflate.
- **Surfaces:** `capture` and `http` (bytes held in memory, in a test or by `tools/guest.py`), `file`, `tree`
  (links and junctions not followed, counted), `tar` and `environ` (this process's). Each reports whether it was
  searched in full, the bytes per view, the items, what it could not read (by error type), what it did not
  follow, and the matches per form and view. A name is shown only if it holds no match.
- **Positive controls** (`Search.controls()`): copies of the key made by the standard library's encoders, planted
  in memory in every kind of surface and view (191 cases), including a copy across the read boundary, an SQLite
  row split across an overflow page and an HTTP body split across two chunks (where the raw view must find no
  whole copy). The verdict is `invalid` unless each is found. A surface may also be declared to hold the key
  (`expect='present'`): the offline test's bytes the broker sends upstream.
- **Verdicts:** `found`, `invalid`, `incomplete`, `not-found`. `not-found` is stated for the bytes searched only,
  with `not_covered` listing what lies outside them, process memory first.
- **Never kept:** the key comes from standard input only (a terminal is refused), must have the synthetic shape
  and the fingerprint given (`--expect-fingerprint`, the broker start receipt's); the report carries the
  fingerprint and counts, is searched for the key before it is printed and withheld if it holds one
  (`OUTPUT_WITHHELD`); the module prints nothing, keeps no log and writes no file.

```
<synthetic key> | <tools python> -I -B integrations/inference/inference_key_search.py search \
    --expect-fingerprint sha256:<16 hex> --surface LABEL=KIND:PATH [--surface ...]
```

KIND is `file`, `tree`, `tar` or `environ` (PATH `self`). Exit 0 `not-found`, 1 `found`, `invalid` or
`incomplete` (or a withheld report), 2 refused.

**Wired for the live qualification** (prepared, not run): `tools/guest.py inspect --provider-key-fingerprint FP
--provider-key-stdin` searches the P5 collection (the guest's files, process environments and records, as
collected as the agent user) and its host files (`seed.iso`, `launch.json`, `serial.log`) for the key itself, on
the host, in memory, beside the fingerprint needle; for a guest with the inference composition that P5 check is
UNKNOWN without it. `tools/guest.py job-access-probe --attempt-token-stdin --provider-key-stdin
--provider-key-fingerprint FP` (the token, then the key, on standard input) has the job's token script return
each answer it received whole (up to 64 KiB) and searches them, which is what crossed the forward; the answers
are never recorded. The key never travels to the guest. The search command then covers the instance directory,
the reports, the broker's store, audit directory and captured output. The prepared order is in the slice record.

## Route and model discovery (S-03.3, slice 3 part two)

The S-03.3 slice plan (`evidence/S-03.3-slice-plan.md`, slice 3 and step 6a) learns which routes and which model
names (Claude Code's secondary model included) the pinned client sends, before any key or paid call, from the
broker's audit of refused requests (the plan's D-4, above in [Audit](#audit)). **Not yet verified** outside a test
process: the discovery run is the slice plan's step 6a, under the Owner's acts A2, A3 and A4.

- **`discover`** (`inference_qualification.py discover --provider ID --out FILE`, the synthetic key on standard
  input): the qualification launcher in its discovery mode. It refuses exactly as `broker` does, through the same
  code path, and also: `--out` must be a new file in an existing directory outside the checkout
  (`PROPOSAL_OUT_REFUSED`; "outside" is the harness's one checkout comparison, `aieh_paths.inside_or_around`, which `load_manifest` also uses,
  made on the given path and on the resolved one: the lexical comparison covers a `\\?\` or `\\?\UNC\` prefix,
  an alternate data stream suffix, trailing spaces and dots of a component, case and `/`, and a link, junction,
  volume-GUID or GLOBALROOT form is caught on the resolved path), and each keyed family's upstream must be an IPv4 loopback literal
  (`FAKE_ADDRESS_REFUSED`) on which the command binds that family's fake upstream itself (`DISCOVERY_PORT_TAKEN`
  when it cannot), all before the key is read. The broker's upstream for a keyed family is then this process's fake
  upstream and nothing else. A configured family keyed to another provider id, whose loopback upstream the
  launcher admits, is **not** bound by `discover`: whatever listens there is not this command's fake upstream (its
  requests are still in the audit). When the broker stops (the Owner's interrupt), it reads that run's audit file (named in the
  broker's status) and writes the proposal (below) to `--out`, with a `discovery` member: the provider id, the
  keyed families, the provider key's fingerprint and what each fake upstream received (requests per route and
  answer, whether every credential it saw was the synthetic key's fingerprint, and per route the JSON **key paths**
  of the admitted request bodies). Key paths are names only, never a value: object keys joined by `.`, each array
  collapsed to `[]` (`messages[].content`); a key outside `[A-Za-z0-9_$@-][A-Za-z0-9_$@:-]{0,31}` (at most 32
  characters, the audit's own bound) or holding the token prefix is recorded as `<unrecorded>` and counted. **Key
  names can carry data** (an id, an e-mail address, a schema's field name): under the open maps `metadata`,
  `properties`, `input_schema`, `parameters`, `definitions`, `$defs` and any key ending in `_metadata`, and
  everywhere below them, a key name is recorded only when it contains `model` (any case), else as `<map>`, so
  `metadata.fallback_model` is still seen. At most 256 paths per request and per route, 32 levels, and a body of at
  most 32 MiB; beyond that the set is marked truncated. Only `discover` records them: the
  `fake-upstream` command's records are unchanged, and so are the broker and its audit. Standard output carries
  `serve`'s own report, standard error the proposal's summary. A key refused after the fake upstream was bound
  leaves no audit and no proposal, and the port is freed.
- **`propose-pin`** (`inference_qualification.py propose-pin --audit FILE --out FILE [--attempt-id UUID]`): the
  reader, for any one broker run's audit file. It writes the proposal to `--out` (a new file outside the checkout)
  and prints its summary. The audit file is read whole (at most 256 MiB; `AUDIT_UNREADABLE` otherwise).
- **The proposal** (`aieh-inference-family-pin-proposal/1`): `status` `proposed`, `applied` false and a statement
  that nothing is applied: neither `families.json` nor `config.yml` is written. Per family that a grant's request
  named: `proposed.routes` (the exact method and path pairs observed, in the declarations' route grammar) and
  `proposed.models` (the exact model names observed, the secondary model included); `declared` and `compared`
  (declared and not observed, observed and not declared); `observed.routes` (per route: requests, the answer codes,
  the query parameter names, the models, the requests without a top-level model) and `observed.models` (per model:
  requests, routes, codes). Requests without a grant of the broker are counted apart (`unattributed`); `attempts`
  lists the grants seen. The routes are for the Owner's approval (the slice plan's 6b); the model identifiers for
  the engineering manager's selection inside the Owner's provider envelope (decision 0018 point 3, `select-models`
  through `integrations/owner/selection_recorder.py`), verified against current provider information and
  presented to the Owner before the first paid call.
- **No wildcard, nothing outside the grammars.** Only strings inside the audit's own grammars are carried: a path
  of at most 16 segments of `[A-Za-z0-9][A-Za-z0-9._~-]{0,31}`, parameter names of that word, a model in the
  broker's model grammar without a wildcard character, none holding the token prefix. Anything else is counted
  (`READER_DROPPED`). A proposal that holds the synthetic key's prefix is not written (`PROPOSAL_EXPOSURE`).
- **Flags** (each with its family and route where it has one): `MODEL_NOT_TOP_LEVEL` (requests without a top-level
  `model`: the broker's per-request check reads that field only, S-03.5's F7, so the route is not declared without
  its own check), `MODEL_UNRECORDED`, `PATH_UNRECORDED`, `QUERY_NAMES_UNRECORDED`, `QUERY_OBSERVED` (a query string
  where the family's rule is `refuse`, on a route the family does not declare, or refused `QUERY_NOT_ALLOWED`: the
  audit holds the names only and the declarations exact whole query strings, so admitting it is a decision of its
  own), `ROUTE_NOT_DECLARABLE`, `UNATTRIBUTED_REQUESTS`, `AUDIT_LINES_WITHHELD`, `AUDIT_LINES_UNREADABLE`,
  `BROKER_UNRECORDED`, `READER_DROPPED` and `NO_GRANT_REQUESTS`; from a discovery run's key paths (S-03.5's F7,
  the engineering manager's option (b)): `MODEL_KEY_ELSEWHERE` (a key path other than the top-level `model` whose
  last segment contains `model`, any case; the flag lists the paths, never the values: a model named there is not
  checked by the broker, so the family is not declared without its own check), `KEY_PATHS_TRUNCATED` and
  `KEY_NAMES_UNRECORDED`. `complete` says whether everything the run sent is accounted for: it is false when any
  value went unrecorded, unread or withheld, the key paths were truncated or held an unrecorded name, a request
  presented no grant (`UNATTRIBUTED_REQUESTS`: its model is never recorded), or no grant's request was seen.
  `MODEL_KEY_ELSEWHERE` is a suitability flag about the pin and does not affect `complete`.
- **Not shown** (the proposal's `not_shown` list): a model named in a body field other than the top-level `model`
  of a refused request in a discovery run (only admitted requests reach the fake upstream that reads the key
  paths), and of any request when `propose-pin` reads an audit file alone (the audit records the top-level model
  only, D-4 as accepted); a secondary model under a key whose name does not contain `model` (`engine`,
  `deployment_id`): the flag reads key names, never values; key names that are data, as above; query values,
  headers and bodies; what a refused request would have done; requests the client never sent because an earlier one
  was refused.
- **A write that fails** after the run (or in `propose-pin`) is `PROPOSAL_WRITE_FAILED`, exit 1, with the error's
  type and no traceback; `propose-pin` over the run's audit file writes it again.

## The real-key containment search (S-03.3, slice 4)

S-03.3's proof searches for the **real** provider key at its exposure boundaries, raw and encoded, by a checker that
holds it in memory only, counts only, with a positive control; never printed or persisted. Under the engineering
manager's acceptance of the slice plan's D-5, the key is read from the same credential entry the broker reads
(same account, decision 0010 point 1, decision 0013 point 6). **Its live use is covered only by the Owner's act
A1** (OA-12: the provider key in its Credential Manager entry); it is built and tested with fakes only (a fake
credential provider holding a synthetic key) and has never read a real entry.

```
<tools python> -I -B integrations/inference/inference_real_key_search.py search --owner-act ACT \
    --expect-fingerprint sha256:<16 hex> --surface LABEL=KIND:PATH [--surface ...]
```

- Every argument is checked first: `--owner-act` is a **label** naming the Owner's act, recorded in the report; only
  its grammar is checked (`OWNER_ACT_REQUIRED` otherwise: a letter or digit, then up to 63 letters, digits, spaces
  or `._:()/-`), never a record: no recorded act is read or verified, and that the act exists is the operator's
  statement; `--expect-fingerprint` (the running broker's
  provider-key fingerprint, from its start receipt or status) and the surfaces, as `inference_key_search.py`
  takes them. Only then is the credential provider asked.
- The key is read once through the broker's own credential factory (`credentials.select_provider`, the provider
  the broker's managed context uses) from the entry `AIEH model provider`: never standard input, an argument or
  the environment. A provider that fails (`KEY_PROVIDER_FAILED`, its error type only), an absent or malformed
  entry (`KEY_ENTRY_ABSENT`) and another key (`FINGERPRINT_MISMATCH`, naming the key of the credential entry, never
  a piped one) are refused without repeating what was read.
- The search is `inference_key_search.run`: the same forms (for a key without the synthetic prefix, its body is
  the whole key), views, surfaces, positive controls (copies planted by the standard library's encoders) and
  verdicts. The report (`aieh-inference-real-key-search/1`, the search's own format as `search_format`) adds the
  entry, the credential provider's name and the Owner's act; it is searched for the key before it is printed and
  withheld if it holds one (`OUTPUT_WITHHELD`). Nothing is written, logged or kept.
- Its surfaces for S-03.3 are the instance directory (its records included), the reports, the broker's integration
  store and audit directory. The guest and the job's answers are searched by the prepared `tools/guest.py
  acp-qualification` driver's step 11 with the same key (`inspect`'s P5 collection and every Agent Server answer
  and container output of the run, in memory), read there by its own reader of the same entry.

## Commands

```
<tools python> -I -B -m unittest discover -s integrations/inference/tests -v      # task inference:test
<tools python> -I -B integrations/inference/inference_broker.py config            # validate and print the configuration
<tools python> -I -B integrations/inference/inference_broker.py envelope [--operation ID]   # the live envelope and its manifest
<tools python> -I -B integrations/inference/inference_broker.py credential-set --provider ID   # key on stdin
<tools python> -I -B integrations/inference/inference_broker.py credential-enter --provider ID [--replace]   # pasted at a hidden prompt
<tools python> -I -B integrations/inference/inference_broker.py serve             # both listeners until stopped
<tools python> -I -B integrations/inference/inference_control.py stop             # the stop from any session
<tools python> -I -B integrations/inference/inference_census.py --once            # the broker's live census
<tools python> -I -B integrations/inference/provider_tunnel.py serve --profile PROFILE_DIR   # the native tunnel
<tools python> -I -B integrations/inference/provider_tunnel.py stop               # its stop from any session
<tools python> -I -B integrations/inference/provider_tunnel.py census --once      # its live census
<synthetic key> | <tools python> -I -B integrations/inference/inference_qualification.py broker --provider ID
<tools python> -I -B integrations/inference/inference_qualification.py fake-upstream --family ID --port PORT
<tools python> -I -B integrations/inference/inference_control.py issue --conversation-id UUID --family ID \
    --model NAME --ttl-s SECONDS | <the command that reads the token>
<synthetic key> | <tools python> -I -B integrations/inference/inference_key_search.py search \
    --expect-fingerprint sha256:<16 hex> --surface LABEL=KIND:PATH [--surface ...]
<synthetic key> | <tools python> -I -B integrations/inference/inference_qualification.py discover --provider ID \
    --out FILE
<tools python> -I -B integrations/inference/inference_qualification.py propose-pin --audit FILE --out FILE \
    [--attempt-id UUID]
<tools python> -I -B integrations/inference/inference_real_key_search.py search --owner-act ACT \
    --expect-fingerprint sha256:<16 hex> --surface LABEL=KIND:PATH [--surface ...]
```

Exit 0 done, 1 failed, 2 refused (a stable code with its remedy); `serve` exits 3 on a second interrupt during
its stop. `serve` and `credential-set` act on the
managed root, its `config.yml` and the real credential provider: Owner acts, not run in this slice. The
qualification launcher acts on the managed root and its `config.yml` too (never on a credential provider); it,
the fake upstream and `issue` are part of the Owner's act A2 and have not run outside a test process.

## The provider tunnel (E-05.10)

The native execution profile ([decision 0023](../../decisions/0023-native-claude-code-execution-profile-native-authentication-and-provider-tunnel.md)
sections 4 to 6) runs the unmodified Claude Code with its own provider credential and no broker. Its one path out
of the conversation container is S-03.2's guest inference endpoint, unchanged on the guest side (one sshd
`PermitListen`, one container-guard ACCEPT, an empty egress-guard allowlist, DNS refused;
`tools/tests/test_tunnel_guest_side.py` pins the seed's and the declared rules' digests at S-03.2's composition),
whose forward ends here instead of at the broker. Claude Code's `HTTPS_PROXY` is the endpoint
(`http://172.17.0.1:8090`, E-05.9's admission).

**Adopt or own.** An established proxy would be adopted if one met every clause at a pin on this Windows host's
loopback: CONNECT only, an exact host:port allowlist, IP literals refused, the tunnelled ClientHello's server name
checked without terminating TLS, no credential, and target, decision and byte-count logging only. A documentation
survey found none: Squid can peek at the SNI and splice, but its `ssl_bump` port must be configured with a
certificate and key even when it never bumps, and it has no maintained native Windows release; mitmproxy's
passthrough reads the SNI but generates and holds a CA key; Envoy's `tls_inspector` and HAProxy's `req.ssl_sni`
read the SNI of direct TLS, not inside a CONNECT, and have no supported Windows build; nginx needs a third-party
CONNECT module and its `ssl_preread` has the same limit; Tinyproxy, Privoxy and Caddy's `forwardproxy` filter the
CONNECT target but never read the ClientHello. So the tunnel is owned, minimal and standard library only
(`provider_tunnel.py`, under 1,000 lines with its commands and census), the choice recorded here and in E-05.10's record.

**One declaration.** The execution profile's one `network.endpoints` entry of class `provider-tunnel` (profiles
P7) declares both sides: `guest_address` and `guest_port` (the inference endpoint's, the `HTTPS_PROXY` E-05.9's
admission compares) and `host_bind` `127.0.0.1` with `host_port` 18433, beside the broker's example ports 18431
and 18432 (the tunnel listens there; the forward holder targets it), and its `origin`, `api.anthropic.com:443`.

**Admission** (each refusal answered, before the 200 as an HTTP status with a JSON body `aieh_refusal.code` and
the header `X-AIEH-Tunnel-Refusal`, after it by closing the connection, and logged with its reason):

| Step | Refused | Code |
|---|---|---|
| request head (8 KiB, 10 s) | not a request, an HTTP version other than 1.0 or 1.1, too large or incomplete, a bare CR or LF anywhere | `TUNNEL_REQUEST_MALFORMED` (400) |
| method | every method but `CONNECT` (plain HTTP included) | `TUNNEL_NOT_CONNECT` (405) |
| headers | `Proxy-Authorization` (the tunnel takes no credential) | `TUNNEL_PROXY_CREDENTIAL` (403) |
| target | an IP literal in any spelling (dotted, numeric, hexadecimal, bracketed IPv6) | `TUNNEL_TARGET_IP_LITERAL` (403) |
| target | any host but exactly `api.anthropic.com` | `TUNNEL_TARGET_REFUSED` (403) |
| target | that host on any port but 443, the port's text exactly `443` (never `0443`) | `TUNNEL_PORT_REFUSED` (403) |
| capacity | more than 64 open connections | `TUNNEL_BUSY` (503) |
| ClientHello (one handshake record, 16 KiB, 10 s) | not one whole ClientHello in one handshake record, or bytes before the server's answer | `TUNNEL_HELLO_MALFORMED`, `TUNNEL_HELLO_FRAGMENTED` |
| ClientHello | an encrypted ClientHello (ECH, or the ESNI draft) | `TUNNEL_ECH_REFUSED` |
| ClientHello | no `server_name` | `TUNNEL_SNI_ABSENT` |
| ClientHello | a server name other than the CONNECT host | `TUNNEL_SNI_MISMATCH` |
| origin | the host's resolution of the origin gives an address that is not global, or an IPv6 form embedding or translating an IPv4 address (IPv4-compatible, IPv4-mapped, the NAT64 prefixes `64:ff9b::/96` and `64:ff9b:1::/48`, 6to4, Teredo) | `TUNNEL_UPSTREAM_REFUSED` |
| origin | no address resolved or reachable | `TUNNEL_UPSTREAM_FAILED` |
| stop | the connection was open at the tunnel's stop | `TUNNEL_STOPPED` |

Only after the CONNECT and its ClientHello are admitted does the tunnel open its own outbound connection, to the
origin's host name resolved on the host, connecting to exactly the addresses it checked (no second resolution), on
443; it sends the ClientHello's bytes as received and then splices
both ways, unread, until either side ends, 900 s pass with no byte, or it stops.

**The log** (`persistent/logs/provider-tunnel/tunnel-<UTC>-<hex>.jsonl`, `aieh-provider-tunnel-log/1`):
`tunnel-start` (listener, origin, pid), `upstream-connect` (connection number, target, origin, the peer address
it connected to), `connection` (number, target, decision, reason, end, `bytes_up`, `bytes_down`),
`refusals-suppressed` (reason, count, window), `accept-failed` (errors), `tunnel-stop` (by, connections cut, and
`log`: the suppressed counts per reason, the dropped lines and the bounds). Never payload, a header, the target of a
request that is not a CONNECT (a URL may carry a credential) or the server name a refused hello presented.

**The log's bound** (disclosed: a guest process can provoke refusals at will while a forward is held). Per refusal
reason, the first **20** refused connection lines of each **60 s** window are written verbatim; the rest of that
window are counted and written as one `refusals-suppressed` line per reason when the window closes (or at the stop).
Admitted connections and their `upstream-connect` lines are never aggregated. Past **64 MiB** per log file (one file
per `serve`) every further line is dropped and counted, `upstream-connect` lines included, so a census over a later
connection then fails closed (its peer is unrecorded); the `tunnel-stop` line is always written and carries the
totals. A flood of refusals therefore costs at most 20 lines per reason per minute plus one count line.

**Lifecycle.** `serve --profile PROFILE_DIR` runs in the foreground of the session that starts it (a process with
no console starts it with `CREATE_NO_WINDOW`), writes its run record
(`persistent/state/provider-tunnel/provider-tunnel.json`, `aieh-provider-tunnel-run/1`: pid, the process's
creation time, address, port, log file) once listening, and refuses a second start while a live one is recorded
(`TUNNEL_ALREADY_RUNNING`). A run record is trusted only for the process that wrote it: its pid running with the
recorded creation time; a pid reused by another process is an ended tunnel (its stale record replaced at `serve`,
removed at `stop`), and a process whose identity cannot be checked (access denied) is unknown, never ended
(`TUNNEL_RUN_RECORD_UNKNOWN`; the record is kept). It stops on SIGINT, SIGBREAK or SIGTERM (a flag the main thread
acts on in 0.25 s slices) or on `stop`, which writes the stop request beside the run record and waits on the
tunnel's process handle (15 s ceiling, `TUNNEL_STOP_TIMEOUT`). At the stop every open connection's sockets are cut
(shut down and closed through detach, so a worker blocked in a read, or in a send to a peer that does not read, ends
at once), each connection's line is written before the `tunnel-stop` line, the run record is removed and `serve`
exits 0. The accept loop backs off on an error (doubling from 50 ms to 1 s) and gives up after 20 consecutive ones
(`accept-failed`; `serve` then stops and exits 1). It starts no process. `census --once` observes the running tunnel at the operating system with
`inference_census.py`'s tables and decision rule: exactly its listener on `127.0.0.1:<port>`, no UDP endpoint, and
no connection but inbound ones from loopback and outbound ones to port 443 of a peer its log recorded.

**The forward holder** (`tools/guest.py inference-forward --action start --execution-profile native`) targets the
tunnel's declared port only for a profile that declares the provider-tunnel endpoint
(`NATIVE_PROFILE_UNDECLARED`; a deferred entry declares nothing), refuses every other port
(`FORWARD_PORT_REFUSED`), refuses when a broker port configured in `components.inference_broker` is the tunnel's
(`TUNNEL_PORT_CONFLICT`, also on the brokered start), and starts only once the tunnel's run record names its own,
live process on that port (`TUNNEL_NOT_READY`); the forward's record names the target (`ports.tunnel`), one forward
at a time (`FORWARD_TARGET_DIFFERS`). The brokered start is otherwise unchanged (`FORWARD_PORT_REFUSED`,
`CONTROL_PORT_REFUSED`, `BROKER_NOT_READY`).

**From a job** (the inference sweep's tunnel rows, with the forward held to the tunnel): the admitted CONNECT
completes a TLS handshake verified for `api.anthropic.com` and sends nothing after it; another host, another port,
an IP literal and plain HTTP are refused with the tunnel's status and code; a mismatched or absent server name is
`closed-without-answer` only when, after the 200 and the job's one ClientHello, not one byte arrives before the
end of the stream (a TLS alert from an origin the tunnel let through is a byte: `answered-after-hello`, a FAIL and a
stop condition).

**Not yet verified.** Everything live (the Owner's act OA-31 (a)): the tunnel as a host process against the real
network, the host's resolution of the origin, a TLS handshake with the provider through it, the forward to it from
a guest, its census over a real connection, Claude Code's own CONNECT and ClientHello (whether it sends ECH, or a
ClientHello split over records, is not observed), the stop from a real console window, and Linux and macOS.

## Stable codes

Configuration: `DECLARATION_INVALID`, `CONFIG_NOT_A_MAPPING`, `CONFIG_UNKNOWN_KEY`, `CONFIG_SECRET_SHAPED_KEY`,
`CONFIG_FAMILY_UNKNOWN`, `CONFIG_PORT_INVALID`, `CONFIG_LIMIT_INVALID`, `CONFIG_PROVIDER_INVALID`,
`CONFIG_PROVIDER_REQUIRED`, `CONFIG_ORIGIN_INVALID`, `CONFIG_MODEL_INVALID`, `CONFIG_INCOMPLETE`,
`CONFIG_ENVELOPE_INVALID`.
The provider envelope (S-03.5; at start `serve` exits 2): `ENVELOPE_NOT_CONFIGURED`, `ENVELOPE_FAMILIES_UNBOUND`,
`ENVELOPE_RECORD_INVALID`, `ENVELOPE_AUTHORIZATION_UNRESOLVED`, `ENVELOPE_REPLAYED`, `MODEL_SELECTION_MISSING`,
`MODEL_SELECTION_NOT_AUTHORIZED`, `MODEL_SELECTION_RECEIPT_MISMATCH`; at start, in `issue` and at admission:
`MODEL_NOT_SELECTED` (403);
at start and at admission: `ENVELOPE_NOT_AUTHORIZED`, `ENVELOPE_MISMATCH` (503), `ENVELOPE_EXPIRED` (403); at
admission once the broker's stop has begun: `BROKER_STOPPING` (503). At start (S-03.3): `FAMILY_REACH_UNCHECKED`.
Control: `CONTROL_ROUTE_UNKNOWN` (404), `CONTROL_CALLER_REFUSED` (403), `CONTROL_CONTENT_TYPE` (415),
`CONTROL_BODY_INVALID` (400), `CONVERSATION_ID_INVALID`, `ATTEMPT_ID_INVALID`, `FAMILY_UNKNOWN`, `MODELS_INVALID`,
`BUDGET_RETIRED`, `TTL_INVALID`, `TRIGGER_UNKNOWN`, `REVOKER_INVALID` (400), `MODEL_NOT_ALLOWLISTED` (403),
`FAMILY_NOT_READY`, `ATTEMPT_HAS_GRANT`, `GRANT_ALREADY_REVOKED` (409), `GRANT_UNKNOWN` (404), `JOURNAL_FAILED`,
`EXPOSURE_FOUND` (500).
Inference: `TOKEN_MISSING`, `TOKEN_AMBIGUOUS`, `TOKEN_UNKNOWN`, `TOKEN_REVOKED`, `TOKEN_EXPIRED`,
`TOKEN_WRONG_HEADER` (401), `ROUTE_NOT_ALLOWED` (404), `QUERY_NOT_ALLOWED`, `BODY_LENGTH_INVALID`,
`BODY_NOT_JSON`, `BODY_ENCODING_INVALID`, `BODY_DUPLICATE_KEY`, `HEADER_VALUE_INVALID`, `MODEL_MISSING`, `TOKEN_IN_REQUEST`,
`PROVIDER_REACH_REFUSED` (400), `CONTENT_ENCODING_REFUSED`, `CONTENT_TYPE_REFUSED` (415), `MODEL_NOT_ALLOWED` (403), `BODY_LENGTH_REQUIRED`
(411), `BODY_TOO_LARGE` (413), `UPSTREAM_UNREACHABLE` (502), `PROVIDER_KEY_ABSENT`, `UPSTREAM_NOT_CONFIGURED` (503).
Credential set: `PROVIDER_ID_INVALID`, `KEY_STDIN_TTY`, `KEY_INVALID`, `KEY_READ_BACK_FAILED`.
Credential enter: `PROVIDER_ID_INVALID`, `KEY_CONSOLE_REQUIRED`, `KEY_NOT_KEY_SHAPED`, `KEY_ENTRY_CANCELLED`
(exit 2), `KEY_ENTRY_EXISTS` (exit 2), `KEY_READ_BACK_FAILED` (exit 1).
Qualification (`inference_qualification.py`, beside the broker's configuration and key codes):
`QUALIFICATION_UPSTREAM_REFUSED`, `QUALIFICATION_NO_FAMILY`, `KEY_NOT_SYNTHETIC`, `KEY_NEVER_WRITTEN`,
`FAKE_FAMILY_UNKNOWN`, `FAKE_ADDRESS_REFUSED`, `FAKE_PORT_INVALID`. The `issue` command (beside the dispatcher's
side's codes and the broker's refusals): `TOKEN_STDOUT_TERMINAL`, `TOKEN_STDOUT_NOT_PIPE`. The key search (`inference_key_search.py`): `KEY_STDIN_TTY`,
`KEY_INVALID`, `KEY_NOT_SYNTHETIC`, `FINGERPRINT_INVALID`, `FINGERPRINT_MISMATCH`, `SURFACE_INVALID` (exit 2),
`OUTPUT_WITHHELD` (exit 1).
Discovery and the reader (`inference_qualification.py`, S-03.3): `DISCOVERY_PORT_TAKEN`, `PROPOSAL_OUT_REFUSED`,
`AUDIT_UNREADABLE`, `ATTEMPT_ID_INVALID` (exit 2), `PROPOSAL_EXPOSURE`, `PROPOSAL_WRITE_FAILED` (exit 1); after a discovery run, a proposal
that cannot be read or written exits 1. The real-key search (`inference_real_key_search.py`): `OWNER_ACT_REQUIRED`,
`KEY_PROVIDER_FAILED`, `KEY_ENTRY_ABSENT` and the key search's `FINGERPRINT_INVALID`, `FINGERPRINT_MISMATCH`,
`SURFACE_INVALID` (exit 2), `OUTPUT_WITHHELD` (exit 1).
A refusal answers `{"aieh_refusal": {"code", "detail", "remedy"}}` and closes the connection. Retired by S-03.6
(no longer answered by anything): `BUDGET_INVALID`, `BUDGET_REQUESTS_EXHAUSTED`, `BUDGET_TOKENS_EXHAUSTED`,
`BUDGET_USAGE_UNKNOWN`, `ENVELOPE_CAP_REACHED`, `ENVELOPE_USAGE_UNKNOWN`.

## Retired by S-03.6

On the Owner's direction of 2026-11-13 ("Owner direction: reconcile the D1 provider-access requirements before
live execution", verbatim in `evidence/bootstrap-log.md`, Decisions), applied by
[decision 0021 amendment 1](../../decisions/0021-provider-envelope-model-selection-and-broker-enforced-cap.md)
and [decision 0015 amendment 2](../../decisions/0015-inference-broker-placement-provider-credential-custody-and-guest-inference-endpoint.md),
plan leaf S-03.6 removed the harness's spending enforcement. Spending is bounded by the provider account's own
limits; the harness enforces none. Removed:

- **The envelope's spending limit**: the `limit` member (`amount`, `currency`, `enforced_by`, `cap`) of the
  `envelope` block and of the canonical document, and so of its digest. The canonical form is
  `aieh-provider-envelope/2`; a block that still names one of those keys is refused (`CONFIG_ENVELOPE_INVALID`).
- **The broker-enforced cumulative cap** and its per-run ledger in the integration store
  (`inference/envelope/<nonce>/run/<k>` and its `close`, `aieh-inference-envelope-run/1` and
  `aieh-inference-envelope-close/1`): nothing writes or reads them any more, and receipts an earlier build wrote
  are left as they are. The start order lost its ledger step; the held `Authorization`, the start receipt and the
  status lost the limit's enforcement, the carried usage and the run. Removed codes: `ENVELOPE_CAP_REACHED`,
  `ENVELOPE_USAGE_UNKNOWN`.
- **The attempt grant's request and token budget**: `budget` in the issue request (now refused,
  `BUDGET_RETIRED`), in the grant, its receipt (`aieh-inference-grant/2`) and its answers; the `--requests` and
  `--tokens` options of `inference_control.py issue` and `ControlClient.issue`'s two arguments; the D1 stage's
  grant declaration's `requests` and `tokens` (`integrations/dispatch/README.md`). Removed codes:
  `BUDGET_INVALID`, `BUDGET_REQUESTS_EXHAUSTED`, `BUDGET_TOKENS_EXHAUSTED` and `BUDGET_USAGE_UNKNOWN` (the rule
  that closed a token for good after one answer without usage).

Kept: the start precondition (the governing, confirmed, unexpired provider-envelope receipt over the canonical
digest, with the manifest binding) before the key and the listeners; the loopback rule; the two model-selection
authorities and the per-request model check; `expires_at` as a security validity window; the grant's binding to
its conversation, attempt, family, model list and lifetime, and its revocation; every other refusal; the
credential-header stripping; egress to the configured origin only; the audit, which still tells an answer passed
through from the upstream (its upstream status, or `UPSTREAM_STREAM_BROKEN`) from a broker refusal (its stable
code), with usage recorded as information; the I7 scan; and `BROKER_STOPPING`, now part of the clean stop for
every family.

## Not yet verified

- Everything outside a test process: the broker as a supervised host service (the lifecycle contract), its
  real listeners, the real credential entry, `credential-set` against the Credential Manager, TLS to a real
  provider, any model call (each an Owner act).
- The live census against the broker run by the Owner (act A2) and against a real provider connection over TLS:
  only an in-test broker on loopback ports with a loopback fake upstream has been censused; Linux and macOS
  (UNKNOWN by design).
- `credential-enter` in a real console window: the console-mode check on a real console handle, the hidden prompt
  (`getpass` on the console), a paste from the clipboard and the real Credential Manager (the Owner's act 2).
- Whether a pinned client (Claude Code) ever sends what the reach checker refuses, and the provider's own
  request shapes beyond its public documentation: the rules are written from the documented shapes, not from
  observed traffic.
- The route sets, query rules and usage extractors of all three families: provisional, written from the
  families' public shapes, not from observed traffic; they are pinned at the leaf that first runs each family.
- The provider-key search against a live broker, guest, job or instance directory (slice 5: offline only, in
  the test process); piping the token and the key as two lines into `job-access-probe` from PowerShell.
- S-03.3's tools: `discover` against a real client (the slice plan's 6a), the routes and models a pinned client
  actually sends, and `propose-pin` over a real audit file; the real-key search against a real credential entry
  (Windows Credential Manager) and real surfaces (only under the Owner's act A1).
- The guest side: the SSH remote forward (built offline in slice 3, never run against a real ssh or guest),
  the sshd and container-guard changes (slice 2, offline), the typed create's `secrets`/LLM fields (the D1
  stage's built offline by E-05.6, never sent to a real server; every other stage's A-01.2's and E-03.1's), the
  containment re-run; `inference_control.py` against the broker as a supervised host service.
- The qualification tools (slice 4): the launcher, the `issue` command and the fake upstream have run only in a
  test process (in-process listeners, an `os.pipe()` for the token); their first runs are part of act A2. The
  `issue` command's pipe check with PowerShell's and Git Bash's pipes is not observed.
- Linux and macOS (the listeners' exclusive binding is Windows-specific; elsewhere the default no-reuse
  binding applies).
- The stop from a real console: a Ctrl-C or Ctrl-Break typed in the Owner's own console window (the tests send
  `CTRL_BREAK_EVENT` to a child with a hidden console of its own, and raise SIGINT, SIGBREAK and SIGTERM in the
  test process); SIGTERM from another process; the stop on Linux and macOS.
- The provider envelope (S-03.5 slice 1) outside a test process: a real envelope manifest, its authorization by
  the Owner through the recorder against a real Gitea, `serve` started on it, and any request through `serve` to
  a non-loopback origin (S-03.3's live step). The authorization recorder admits only the S-01.2.2 fixture
  repository today. A real model selection recorded on the managed store. The provider account's own limits,
  which bound spending since S-03.6, and how the provider's refusal of a request beyond them surfaces.
