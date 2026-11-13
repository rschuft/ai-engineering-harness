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

Plan leaf S-03.3 ("Qualify the first ACP coding provider through the broker") adds two qualification tools, built
and tested offline only ([below](#route-and-model-discovery-s-033-slice-3-part-two) and
[below](#the-real-key-containment-search-s-033-slice-4)): the discovery mode of the qualification launcher with the
reader that turns a run's audit into a proposed family pin, and the real-key mode of the containment search.

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
| `inference_envelope.py` | The provider envelope (S-03.5 slice 1): the `envelope` block's check, the canonical document, its digest and the canonical operation manifest. Standard library only; it opens nothing |
| `families.json` | The declared API families (`aieh-inference-families/1`) |
| `inference_control.py` | The dispatcher's side (S-03.2 slice 3): the two listener ports read through the broker's own loader (`dispatcher_ports`), the forward target (`forward_target`: the inference listener only), the control client (`ControlClient`: status, a grant by fingerprint, revocation, and for the qualification one grant (`issue`, slice 4); `127.0.0.1` only), an attempt token's fingerprint (`token_fingerprint`) and the `issue` command (slice 4) |
| `inference_qualification.py` | The qualification-only commands (S-03.2 slice 4): the qualification launcher (`broker`: the broker's own `serve` with a synthetic key from standard input, loopback `http` upstreams only) and the fake upstream (`fake-upstream`); S-03.3 slice 3 part two: the launcher's discovery mode (`discover`) and the reader of a run's audit (`propose-pin`, `propose_pin`), which writes a proposed family pin and applies nothing |
| `inference_key_search.py` | The provider-key containment search (S-03.2 slice 5): the synthetic key held in memory, searched for raw and in its encodings over byte surfaces, with positive controls; its command line (`search`). Standard library only; it imports nothing of the broker |
| `inference_real_key_search.py` | The real-key containment search (S-03.3 slice 4): the key of the broker's credential entry, read through the broker's credential factory under a named Owner act, held in memory, and searched by `inference_key_search.run` (its forms, views, surfaces and controls); its command line (`search`) |
| `tests/broker_support.py` | Synthetic fixtures: an in-memory credential provider, a settable clock, a fake upstream per family (`FakeUpstream`, an in-process server on an ephemeral `127.0.0.1` port) and `Rig` (a broker over a fixture store and audit directory) |
| `tests/test_config.py` | The shipped declarations; every refusal of the declaration file and of `components.inference_broker`; the decision 0009 loader's refusal of secret-shaped keys under the component; the `config` command |
| `tests/test_usage.py` | The usage extractors over whole and byte-by-byte streams and bodies |
| `tests/test_grants.py` | Socket-free: issuance and its refusals, readiness, revocation and expiry with their receipts, journal failures, every admission refusal, budgets, refusal responses; a check that every stable code appears in a test |
| `tests/test_credential_set.py` | `credential-set` over an in-memory provider and a fixture store |
| `tests/test_egress.py` | The egress code path read from the module's syntax tree; `connect_upstream`; the census of the modules `serve` loads beside the broker (the envelope and its read side): no network module, no connector |
| `tests/envelope_support.py` | The provider envelope's fixtures (S-03.5): the real authorization recorder over the owner suite's fake Gitea (in memory) writing into a throwaway store, contexts whose provider, audit directory and wait raise if asked, a `Rig` holding a minted authorization, an injected connector |
| `tests/test_cap.py` | S-03.5 slice 3's proof rows D1 and D3 to D8: no ledger when the provider enforces; the cap reached within a run and at the next start, a closed run's usage carried; each unknown outcome (a 2xx answer without usage, a cut stream, a client leaving mid-stream, a request written and never answered, a connection cut while sending, a broker error) closing the envelope for the run and at the next start; a refused connect and an answer outside 2xx adding nothing; a run without its close and a stop with a request in flight; a lost run or close write; a new authorization's ledger at zero (integration) |
| `tests/test_selection.py` | S-03.5 slice 2's proof rows C2 to C7: a delegated selection recorded by the real act starts the broker (no commit id in its receipt); a head another actor reserved, the product manager decided or written as an Owner record; a selection under an earlier envelope; a configured model not selected; a decision source that reads no selection or answers badly; a request and an issuance outside the held selection refused, a selected model passed through (integration) |
| `tests/test_envelope.py` | S-03.5 slice 1's proof rows: the block, the document, the golden digest and manifest, the `envelope` command; every start refusal of `serve` (no block, missing, unsettled, expired, replayed, another origin, limit, expiry or selection, another target, a non-canonical manifest, hand-written receipts, a decision source that raises or answers badly, unbound families, the interim selection and cap refusals); the start with its `authorization` member; the envelope kind recorded through the recorder; loopback upstreams as before; the held authorization at start and at admission, and the expiry while serving |
| `tests/test_broker_http.py` | Both listeners against the three fake upstreams: pass-through, key substitution, streaming, budgets, revocation and expiry on the wire, refusals, egress to the configured origin only, exclusive ports, the audit and the I7 scan; the refused-request audit (S-03.3 slice plan D-4): path, query parameter names and model in their bounded grammars, a credential in a path, a name, a query value, a header or the model never recorded |
| `tests/test_serve.py` | `serve` end to end in the test process |
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
 "query": "refuse",
 "auth": {"header": "x-api-key", "scheme": null},
 "usage": "anthropic-messages"}
```

| Family | Consumer | Routes (provisional) | Auth header | Usage from |
|---|---|---|---|---|
| `anthropic-messages` | Claude Code's ACP adapter (`ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`) | `POST /v1/messages` | `x-api-key: <credential>` | `message_start` and the last event carrying `usage` (`message_delta`); or the body's `usage` |
| `openai-responses` | Codex's ACP adapter in API-key mode | `POST /v1/responses` | `Authorization: Bearer <credential>` | the last event's `response.usage` (`response.completed`); or the body's `usage` |
| `openai-chat` | a native direct-LLM agent; a local model server as the degenerate upstream | `POST /v1/chat/completions` | `Authorization: Bearer <credential>` | the last chunk with a non-null `usage`; or the body's `usage` |

- `routes`: the exact method and path pairs admitted. A path is matched as a string: no normalization, no
  prefix, no trailing slash, no percent-decoding. Every set is **provisional**: it is pinned from observed
  traffic at the plan leaf that first runs the family, and the extractors with it.
- `query`: `refuse` (a request target with a query is refused) or `pass` (passed unchanged). All three ship
  `refuse`.
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
      expires_at: "2026-12-31T00:00:00Z"   # quoted: YYYY-MM-DDTHH:MM:SSZ (UTC)
      limit:
        amount: "25.00"                    # quoted decimal: the Owner-authorized spending limit
        currency: USD
        enforced_by: provider              # provider | broker
        #cap: 1000000                      # with broker only: a cumulative usage-token cap (integer)
      selection: envelope                  # envelope | delegation
```

The values are placeholders, not decided values. An unquoted timestamp or decimal (YAML reads them as a time and
a float) is refused (`CONFIG_ENVELOPE_INVALID`), never normalized. The bound families must share one provider and
one origin, and no loopback family may name that provider (`ENVELOPE_FAMILIES_UNBOUND`): under an envelope the
provider key goes to the envelope's origin only.

**The canonical document** (`aieh-provider-envelope/1`): `format`, `provider`, `origin` (`https://host:port`),
`limit` (`amount`, `currency`, `enforced_by`, `cap`: an integer or null), `expires_at`, and `selection`:
`{"by": "envelope", "models": {<family>: [<ids, sorted>]}}`, or `{"by": "delegation", "record":
"decision:0018", "point": "3"}`. Its **digest**, the authorization's target, is `sha256:` and the sha256 of the
document as canonical JSON (the integration store's rule: sorted keys, no whitespace, UTF-8). **The canonical
manifest** `operations/<operation>.json`: `operation`, `kind` (`provider-envelope`), `target`, `expiresAt` and
`envelope` (the document, in clear, so the Owner reads it in the recorder's challenge summary), JSON with a
two-space indent and one final LF. `serve` regenerates it from the live envelope and the receipt's operation id
and requires its sha256 to be the receipt's manifest digest, so what the Owner was shown is exactly what is
enforced. A change of either form is a new format (`/2`): receipts recorded under `/1` stop verifying.

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
another origin, provider, limit, enforcement, cap, expiry or selection); the expiry reached
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
waited for. With `enforced_by: broker`, the cap's ledger (below)
is read last. A refused start exits 2, writes no receipt and no audit line (it may create an empty
integration store where none exists).

**The cumulative cap** (slice 3; `limit.enforced_by: broker`, for a provider that does not enforce the
Owner-authorized limit on the dedicated key). The unit is **usage tokens, never money** (decision 0015 section
6.3): `limit.cap` is the cumulative usage the provider reports (input including cache, plus output: the
extractors' `total`) over every bound family, for the life of the **governing receipt**. How the cap follows from
the money limit and the models' prices is OA-12's presentation and the selection's cost text; the broker does no
price arithmetic. The ledger is the receipt's own and lives in the integration store as **two confirmed receipts
per run**: `inference/envelope/<nonce>/run/<k>` (`aieh-inference-envelope-run/1`), written and read back as the
last fallible step before the listeners serve, and `inference/envelope/<nonce>/run/<k>/close`
(`aieh-inference-envelope-close/1`), written at the broker's own stop with the run's `usage`, `requests`,
`unknown` answers and requests still `in_flight`. At start the runs are walked from 1 by direct lookups (a run
receipt that is not confirmed never served and counts zero) and the closed runs' usage is carried. One admitted
request of a bound family adds:

| Outcome | Counted |
|---|---|
| a complete answer with a readable usage report | its total |
| nothing of the request was written upstream (the connection was never made) | zero |
| a complete answer outside 2xx | zero: **an assumption about the provider's billing** (S-03.2's rule for the attempt budget), to verify from current provider information at OA-12's presentation |
| a 2xx answer without readable usage; any answer cut off by the upstream or by the client leaving mid-stream | unknown |
| a request written and never answered; a connection made and the request cut while sending; a broker error after admission | unknown |
| a run without its close receipt (a crash, a kill, a lost close write, a broker still serving); a close with unknown answers or requests in flight | unknown, at the next start |
| the run receipt cannot be written or read back | the start fails; nothing is served |

"Was anything written" is recorded when the request has been handed over, before its answer is read, and on a
failure before the connection is closed (http.client clears its socket on close, and when `getresponse`
fails); a connection that was made is counted as written. Observed on CPython 3.12 on Windows: a TLS handshake
that fails after the TCP connection leaves the socket set, so it counts as unknown (conservative, never an
undercount), while a refused TCP connect leaves none and counts zero. So **one transient TLS or certificate
failure closes a broker-enforced envelope until a new authorization.** **The stop:** the broker's own stop sets
a stopping state under its lock before it reads the close receipt's counts; from then on a request of a metered
family is refused `BROKER_STOPPING` (503) at admission, before anything of it is written upstream, and one
admitted before is counted in flight, so the next start refuses `ENVELOPE_USAGE_UNKNOWN`. The close's counts are
therefore the run's whole usage, and no window remains in which usage escapes the ledger. (After the stop the
audit is closed, so such a refusal is not answered: the connection is closed instead.) **Fail closed, and stay
closed:** the cap reached (carried plus this run at or above it) is
`ENVELOPE_CAP_REACHED`, and an unknown answer is `ENVELOPE_USAGE_UNKNOWN`, for every further request of a bound
family in that run (429, checked where the attempt budget is) and at every later start (exit 2). The only remedy is
a new provider-envelope authorization, whose receipt starts a new ledger at zero (decision 0018 point 4.2: raising
a cap is the Owner's per act); there is no reconciliation command. Disclosed limits: requests admitted together
can overshoot by their own usage; charges that are not tokens are not counted; a stop that is not the broker's own
closes the envelope although nothing may have been in flight; a restore of the store to a backup taken before usage
was recorded loses that usage (decision 0004). With `enforced_by: provider` nothing is metered and no ledger
receipt is written; loopback families are never metered.

**The alternative not taken** (R7): a write-ahead receipt per request (reserved and dispatched before the request
is forwarded; confirmed with its usage, failed for zero, unknown otherwise) survives a hard stop while idle and is
what the store's states were made for, at three transactions on every paid request and one receipt per request
for ever. Reconsider it when a hard stop closing the envelope proves operationally costly: at the first live use
of a broker-enforced cap, or when the broker becomes a supervised service whose stop is a kill (decision 0011
point 2, Windows).

**What the broker holds.** `authorize` returns one frozen `Authorization` (the receipt key, the operation id,
the decision id, the digest, the expiry, the provider, the origin, the selected models, the limit's enforcement
and, with a broker-enforced cap, the usage the closed runs carry and this run's position);
`Broker.start()` refuses a bound family unless it holds an object `authorize` returned in this process
(`ENVELOPE_NOT_AUTHORIZED`; a copy or a hand-built one is not) whose provider and origin the family has
(`ENVELOPE_MISMATCH`). At admission, where the attempt budget is checked, a request of a bound family is refused
when the held authorization is not one `authorize` minted (`ENVELOPE_NOT_AUTHORIZED`, 503), when the family's
provider or upstream is not the held one (`ENVELOPE_MISMATCH`, 503), and from the expiry on
(`ENVELOPE_EXPIRED`, 403); an answer already streaming completes, loopback families and the control listener
keep working, and nothing is written at the moment of expiry. Supersession takes effect at the next start. The
start receipt and the status answer carry an `authorization` member (receipt, operation, decision, digest,
`expires_at`, the selection: `by`, `models` and, when delegated, its `record`, `point`, `receipt` and `decision`;
the limit's enforcement) only when an envelope is bound. It never carries the selection record's revision.

**What it is not.** A control against accident, convenience and a stale or edited `config.yml` at the moment of
the act, not against a process of the Owner's account, which can write the store as the recorder does, read the
credential entry or forward from loopback (decision 0010 point 1); it does not authenticate the Owner (decision
0012 point 9). With only loopback upstreams `serve` still reads the real entry if one exists and sends it to the
loopback upstream that names its provider, as before (disclosed).

## Tokens: issue, revoke, status (the control listener)

The control listener answers only a direct loopback call (`Host` exactly `127.0.0.1:<port>`, no `Origin`
header, JSON bodies as `application/json`, at most 64 KiB); it is never forwarded. Every process of the
Owner's account can call it (disclosed, decision 0013 point 6).

| Call | Body | Answer |
|---|---|---|
| `POST /v1/grants` | `conversation_id`, `attempt_id` (canonical lower-case UUIDs), `family`, `models` (a non-empty subset of the family's allowlist), `budget` (`requests`, `tokens`: positive integers), `ttl_s` (1 to `max_ttl_s`) | 201: the token (returned once), its fingerprint, the grant and its receipt |
| `POST /v1/grants/revoke` | `token_fingerprint`, `trigger` (a decision 0007 point 5 trigger: `attempt end`, `suspected exposure`, `definition revocation`, `policy revision`, `expiry`, `owner direction`), `revoker` | 200: the grant, revoked, with its revocation receipt |
| `GET /v1/grants/<fingerprint>` | | the grant: state, budget, counts, usage, receipts |
| `GET /v1/status` | | listeners, the provider key's fingerprint and source, each family and whether it is ready, grant counts, the audit file |

A token is `aieh-inf-` and 43 random URL-safe characters. The broker keeps only its sha256 digest and its
fingerprint (`sha256:` and 16 hex digits). One grant per attempt, durably: its receipt
`inference/attempt/<attempt id>/grant` (`aieh-inference-grant/1`, fingerprint only) is written and read back
before the token is returned, and a second grant for the same attempt is refused even after a restart.
Revocation takes effect at once (the next request answers 401) and then writes
`inference/attempt/<attempt id>/revocation` (`aieh-inference-revocation/1`: fingerprint, attempt,
conversation, trigger, revoker, and the per-attempt summary of requests, refusals, usage and bytes). An
expired token is revoked with trigger `expiry` at its next use or at the next control call. A receipt that
cannot be written leaves the revocation in force and is retried at each control call (`receipts_pending` in
the status). Receipts go to the integration store, never the effects store. Grants live in memory only: they
end with the broker process (its stop writes an audit line naming the live fingerprints).

## Inference: admission and pass-through

A request on the inference listener is admitted only when, in this order: exactly one token is presented in a
declared auth header shape; it is one this broker issued, unrevoked and unexpired; it arrives in its own
family's auth header; the method and path are in that family's route set (and the query rule holds); the
request and usage budgets are not spent; the body has one `Content-Length` (no chunked body) within
`max_request_bytes`, is a JSON object and names a `model` that is in both the token's list and the family's
allowlist; and the token appears nowhere in what would be forwarded (target, headers, body). The request is
then counted, and passed through unchanged to the family's one upstream origin: the same method, target and
body; the client's headers except hop-by-hop ones, `Host`, `Content-Length`, `Accept-Encoding` (the broker
asks for `identity`, so that usage can be read) and every credential-bearing header (`Authorization`,
`X-Api-Key`, `Api-Key`, `Proxy-Authorization`, `Cookie`, `Forwarded`, `X-Forwarded-*`, `X-Real-Ip`); then the
family's auth header with the provider key. The answer is streamed back as it arrives (status, headers,
body; chunked when the upstream gives no length), its usage read on the way. Accounting and the audit line
are written before the answer's last bytes, so a client's next request already meets them. An upstream error
status is passed through as it is.

**Budgets.** A request is refused when the request budget is spent or the usage total reaches the token
budget. A successful answer that reports no usage (or is cut off) makes the token budget unenforceable, so
the attempt is refused further requests (`BUDGET_USAGE_UNKNOWN`, fail closed). Concurrent requests of one
attempt are admitted against the counts at admission, so in-flight requests can overshoot the token budget by
their own usage (disclosed).

**Egress.** `connect_upstream` is the one place that opens a connection, to the configured upstream origin of
the admitted token's family: `https` with the system's trust roots and hostname check, or `http` to a
loopback address only. It reads no proxy variable. The broker resolves the upstream name on the host; it
opens nothing else (no cost map, telemetry or update check). This is a code-path control plus disclosure
(decision 0015 section 5.1), shown by the syntax-tree census in `tests/test_egress.py`.

**Listeners.** Both bind `127.0.0.1` only, without address reuse (on Windows with `SO_EXCLUSIVEADDRUSE`, so
no other socket can take the port), and do no name lookup. Neither writes a log of its own: the audit is the
broker's log.

## Audit

One append-only JSON line per request (`aieh-inference-audit/1`) in a new file per broker run,
`<managed root>/persistent/logs/inference/audit-<stamp>-<random>.jsonl`: `time`, `attempt_id`,
`conversation_id`, `token_fingerprint`, `family`, `method`, `path`, `query_names`, `model`, `unrecorded`,
`request_bytes`, `response_bytes`, `status`, `upstream_status`, `latency_ms`, `usage` and `code` (the refusal
code, or `CLIENT_GONE`, `UPSTREAM_STREAM_BROKEN`, `BROKER_ERROR`); plus `broker-start`, `broker-stop` and
`handler-error` lines. An admitted request's line has its declared route and admitted model. A refused
request's line (the S-03.3 slice plan's D-4, for route and model discovery without a model call against the
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

## The dispatcher's side (`inference_control.py`)

`tools/guest.py` performs the dispatcher's role during bootstrap (decision 0013 point 1) and reaches the
broker only through this module. `dispatcher_ports` reads `control_port` and `inference_port` through
`load_config` (refusing what the broker refuses, and a missing port with `CONFIG_INCOMPLETE`);
`forward_target` gives the port a forward session may target and refuses the control listener's port
(`CONTROL_PORT_REFUSED`) and any other (`FORWARD_PORT_REFUSED`); `ControlClient` calls the control
listener on `127.0.0.1` as it admits callers (status, `GET /v1/grants/<fingerprint>`, revocation) and
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
  UUID), `--family`, `--model` (repeatable), `--requests`, `--tokens` and `--ttl-s`, its answer checked for one
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
  1 and 1, which the broker's extractor reads. Another route answers 404, a body without a valid length 411.
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
  where the family's rule is `refuse`: the declarations hold `refuse` or `pass` only, so admitting it is a decision
  of its own), `ROUTE_NOT_DECLARABLE`, `UNATTRIBUTED_REQUESTS`, `AUDIT_LINES_WITHHELD`, `AUDIT_LINES_UNREADABLE`,
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
<tools python> -I -B integrations/inference/inference_broker.py serve             # both listeners until Ctrl+C
<synthetic key> | <tools python> -I -B integrations/inference/inference_qualification.py broker --provider ID
<tools python> -I -B integrations/inference/inference_qualification.py fake-upstream --family ID --port PORT
<tools python> -I -B integrations/inference/inference_control.py issue --conversation-id UUID --family ID \
    --model NAME --requests N --tokens N --ttl-s SECONDS | <the command that reads the token>
<synthetic key> | <tools python> -I -B integrations/inference/inference_key_search.py search \
    --expect-fingerprint sha256:<16 hex> --surface LABEL=KIND:PATH [--surface ...]
<synthetic key> | <tools python> -I -B integrations/inference/inference_qualification.py discover --provider ID \
    --out FILE
<tools python> -I -B integrations/inference/inference_qualification.py propose-pin --audit FILE --out FILE \
    [--attempt-id UUID]
<tools python> -I -B integrations/inference/inference_real_key_search.py search --owner-act ACT \
    --expect-fingerprint sha256:<16 hex> --surface LABEL=KIND:PATH [--surface ...]
```

Exit 0 done, 1 failed, 2 refused (a stable code with its remedy). `serve` and `credential-set` act on the
managed root, its `config.yml` and the real credential provider: Owner acts, not run in this slice. The
qualification launcher acts on the managed root and its `config.yml` too (never on a credential provider); it,
the fake upstream and `issue` are part of the Owner's act A2 and have not run outside a test process.

## Stable codes

Configuration: `DECLARATION_INVALID`, `CONFIG_NOT_A_MAPPING`, `CONFIG_UNKNOWN_KEY`, `CONFIG_SECRET_SHAPED_KEY`,
`CONFIG_FAMILY_UNKNOWN`, `CONFIG_PORT_INVALID`, `CONFIG_LIMIT_INVALID`, `CONFIG_PROVIDER_INVALID`,
`CONFIG_PROVIDER_REQUIRED`, `CONFIG_ORIGIN_INVALID`, `CONFIG_MODEL_INVALID`, `CONFIG_INCOMPLETE`,
`CONFIG_ENVELOPE_INVALID`.
The provider envelope (S-03.5; at start `serve` exits 2): `ENVELOPE_NOT_CONFIGURED`, `ENVELOPE_FAMILIES_UNBOUND`,
`ENVELOPE_RECORD_INVALID`, `ENVELOPE_AUTHORIZATION_UNRESOLVED`, `ENVELOPE_REPLAYED`, `MODEL_SELECTION_MISSING`,
`MODEL_SELECTION_NOT_AUTHORIZED`, `MODEL_SELECTION_RECEIPT_MISMATCH`; at start, in `issue` and at admission:
`MODEL_NOT_SELECTED` (403);
at start and at admission: `ENVELOPE_NOT_AUTHORIZED`, `ENVELOPE_MISMATCH` (503), `ENVELOPE_EXPIRED` (403),
`ENVELOPE_CAP_REACHED`, `ENVELOPE_USAGE_UNKNOWN` (429); at admission after the broker's stop: `BROKER_STOPPING`
(503).
Control: `CONTROL_ROUTE_UNKNOWN` (404), `CONTROL_CALLER_REFUSED` (403), `CONTROL_CONTENT_TYPE` (415),
`CONTROL_BODY_INVALID` (400), `CONVERSATION_ID_INVALID`, `ATTEMPT_ID_INVALID`, `FAMILY_UNKNOWN`, `MODELS_INVALID`,
`BUDGET_INVALID`, `TTL_INVALID`, `TRIGGER_UNKNOWN`, `REVOKER_INVALID` (400), `MODEL_NOT_ALLOWLISTED` (403),
`FAMILY_NOT_READY`, `ATTEMPT_HAS_GRANT`, `GRANT_ALREADY_REVOKED` (409), `GRANT_UNKNOWN` (404), `JOURNAL_FAILED`,
`EXPOSURE_FOUND` (500).
Inference: `TOKEN_MISSING`, `TOKEN_AMBIGUOUS`, `TOKEN_UNKNOWN`, `TOKEN_REVOKED`, `TOKEN_EXPIRED`,
`TOKEN_WRONG_HEADER` (401), `ROUTE_NOT_ALLOWED` (404), `QUERY_NOT_ALLOWED`, `BODY_LENGTH_INVALID`,
`BODY_NOT_JSON`, `MODEL_MISSING`, `TOKEN_IN_REQUEST` (400), `MODEL_NOT_ALLOWED` (403), `BODY_LENGTH_REQUIRED`
(411), `BODY_TOO_LARGE` (413), `BUDGET_REQUESTS_EXHAUSTED`, `BUDGET_TOKENS_EXHAUSTED`, `BUDGET_USAGE_UNKNOWN`
(429), `UPSTREAM_UNREACHABLE` (502), `PROVIDER_KEY_ABSENT`, `UPSTREAM_NOT_CONFIGURED` (503).
Credential set: `PROVIDER_ID_INVALID`, `KEY_STDIN_TTY`, `KEY_INVALID`, `KEY_READ_BACK_FAILED`.
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
A refusal answers `{"aieh_refusal": {"code", "detail", "remedy"}}` and closes the connection.

## Not yet verified

- Everything outside a test process: the broker as a supervised host service (the lifecycle contract), its
  real listeners, the real credential entry, `credential-set` against the Credential Manager, TLS to a real
  provider, any model call (each an Owner act).
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
- The provider envelope (S-03.5 slice 1) outside a test process: a real envelope manifest, its authorization by
  the Owner through the recorder against a real Gitea, `serve` started on it, and any request through `serve` to
  a non-loopback origin (S-03.3's live step). The authorization recorder admits only the S-01.2.2 fixture
  repository today. A real model selection recorded on the managed store. The cumulative cap against a real
  provider: whether it bills an answer outside 2xx (the assumption above), whether it enforces a limit on a
  dedicated key, and http.client's socket state after a partial send (the failed TLS handshake is observed, above;
  Linux and macOS are not).
