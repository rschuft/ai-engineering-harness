# 0015 - Inference broker placement, provider-credential custody and the guest `inference` endpoint

Status: Proposed, amended - 2026-11-10. The Owner approved amendment 1 (below) on 2026-11-10 (Owner decision (c) on OA-12, verbatim in `evidence/bootstrap-log.md`, Decisions). That approval, and the Owner's acceptance on the same day of the ACP coding-provider path, its brokered dedicated-key authentication in principle and Claude Code as the first provider to qualify, are **architectural acceptance, not execution authorization**: no key is created or stored, no capacity bought, no host listener, guest forward, guest hardening change, egress or model call happens until its own Owner act is recorded. Amendment 2 (2026-11-13, product manager, applying the Owner's direction of 2026-11-13) retires the harness's spending enforcement and grants nothing. Amendment 3 (2026-11-14, Proposed with decision 0023) scopes this record to the brokered execution profile and grants nothing. The original status follows unchanged as history.

Original status: Proposed - 2026-11-10, for plan leaf S-03.1 at `7b93fb3`: an Architect design (gates B and G), reviewed by the Overseer and put to the Owner as Owner action OA-12 ([the authorization request](../evidence/S-03.1-owner-authorization-request.md)). It authorizes nothing: every act it names waits for the Owner's answer to the S-03.1 authorization request, and no model run, credential entry, host listener, guest-to-host path or guest composition change happens before that answer is recorded in `evidence/bootstrap-log.md`. S-03.2 implements it exactly as authorized, or not at all.

**Authority:** the Owner's decision of 2026-11-07 ("Model access: design it now ... brought to the Owner for authorization before anything runs", bootstrap log, Decisions) and the plan leaf S-03.1; blueprint `#containment-architecture` ("Launcher and credential broker: checks accepted Work, policy revision, mounts, network, resource budget and provider entitlement before starting"; "bounded inference endpoint"; "Provider CLI requires authentication token: prefer trusted inference proxy or truly scoped short-lived token, not Owner credentials in agent-readable env/files"; acceptance: "negative-test ... provider-secret access") and `#security` ("Use scoped execution identities, protected secret storage, and isolated workspaces"). This record applies those within decisions 0003, 0006, 0007, 0009, 0010 and 0013; where it and they disagree, they govern and this record is the defect.

**Gate:** architecture consultation before S-03.2, gates B (a durable decision no record settles: where the broker runs, who holds the provider credential, what the `inference` endpoint is) and G (custody of the provider credential; the first guest-to-host path; egress; audit).

**Supersedes:** none. It relies on and does not change: decision 0003 (P5, P7, the Owner-authorization procedure), 0006 (the management channel and the provisioned guest), 0007 points 4 and 5 ("The inference broker alone issues inference access, and no provider credential is ever a role token"; "the provider key is rotated at the provider by the Owner and reloaded into the broker only"), 0009 (the managed root and `config.yml`), 0010 point 1 (the scoped threat model) and 0013 points 3, 4 and 6. It **refines, without rewriting**, three planning-level statements that assumed a QEMU `guestfwd` for the inference class: the execution-profile contract's P7 candidate mechanism ("QEMU SLIRP `restrict=on`, with `guestfwd` to a host-side allowlisting proxy") and the profile's deferred `inference` endpoint entry; the network matrix's planned rows `nm-job-inference` and `nm-review-inference` ("tcp to a guestfwd address"; "egress guard allowlist entry"); and S-01.4 ruling R5 ("the egress guard's first allowlist entry"). Each is named in Consequences; the Overseer owns the contract and the matrix and amends them at S-03.2.

## Context

- The plan's S-03 group exists because no leaf provided model access (decision 0007, Owner confirmation 3; bootstrap log 2026-11-07). The inventory already names the principal `inference-broker` (td-management, planned: "the host-side broker behind the guest's `inference` endpoint class: the only path to provider credentials, which never enter the guest"), the credential `cred-llm-provider-key` (planned; "never in the guest, the seed, a container or an agent-readable file") and the finding `fd-acp-provider-auth` ("how the provider inside a conversation container authenticates without holding an Owner or long-lived credential is not yet specified").
- The conversation's agent runs inside its container (the inner Agent Server), so model calls originate in a container, not in the guest's own processes (S-01.1 inventory; F-04.2).
- The qualified guest has no egress at any phase: SLIRP `restrict=on`, `ipv6=off`, one `hostfwd` (SSH), no `guestfwd`. A container reaches nothing outside the guest: the egress guard (`DOCKER-USER`, empty allowlist) refuses on-link targets and, with a route present, off-link ones; the container guard refuses every new connection from a container to the guest itself (S-01.3.1, S-01.4, S-02.2).
- **The guestfwd mechanism, as qualified, cannot carry an HTTP endpoint.** F-03.3.2 observed that one `guestfwd` chardev is one connection opened by QEMU at start, that every guest connection to the forwarded address is carried over that single stream (the netprobe listener was written line-based for that reason; both the guest's and the namespace's nonce exchanges arrived on the one chardev connection), and that after its listener stops the chardev stays `disconnected` for the life of the QEMU process (`query-chardev`; the QEMU process keeps a bound, non-listening client socket). The profile records the consequence: "An endpoint's broker must therefore run before the guest starts and for its whole life" (`network.enforcement_point.limits`). An HTTP client pool, several containers and streaming responses interleaved on one TCP stream do not work; a broker restart would need a guest restart; `start` refuses a launch record whose guestfwd listener is gone. The plan's S-03.1 proof names this ("the guestfwd lifetime (the broker runs before the guest)").
- **Containers name a public resolver they cannot reach.** Moby wrote `nameserver 8.8.8.8` and `8.8.4.4` into each container's `resolv.conf` because the guest's own resolver is the `127.0.0.53` stub ("Used default nameservers", F-04.2). Every lookup fails: off-link, no route (`ENETUNREACH`), and with a route present the egress guard refuses it (S-01.4 section 13; S-02.2 `egr-offlink-*`).
- **LiteLLM fetches its model cost map at import.** Established by E-01.4.3 from the litellm **1.105.1** bundled in the pinned agent-server 1.60.1 release binary (not the 1.105.7 of `composition/lock/python`, which the binary does not use; `provisioning.agent_server.start_race.bundled`): `litellm/__init__.py:563` calls `get_model_cost_map(url=...)` during `import litellm`; `litellm_core_utils/get_model_cost_map.py` (the function at `:618`) returns the bundled map at `:643` when `LITELLM_LOCAL_MODEL_COST_MAP` is `True` (its module docstring documents the switch), otherwise it fetches `raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`, on a retryable failure starts the daemon thread `litellm-model-cost-map-retry` (`:657-670`) and logs at `:672` (the thread at `:315`). The outer server's unit carries `Environment=LITELLM_LOCAL_MODEL_COST_MAP=True` (E-01.4.3, declared in `provisioning.agent_server.environment`); the control does not reach conversation containers, whose environment the 1.60.1 Docker runtime builds from a fixed list (`forwarded_env_names`), so each inner server still attempts the fetch at its start and is denied at name resolution (F-04.2; E-01.4.3 finding F-2). The upstream race fix is litellm 1.105.5 (BerriAI/litellm#48292, OA-01); it does not remove the fetch.
- **What `composition/` pins.** `litellm==1.105.7` in `composition/lock/python/*.txt` as a transitive of the four `openhands-*==1.60.1` packages (`requirements.in`); `composition/candidates.json` names no LiteLLM component. The LiteLLM **proxy** is not pinned: its extra set is only partly present in the lock (`fastapi`, `uvicorn`, `orjson`, `pyjwt`, `python-multipart`, `backoff`, `cryptography` are; `prisma`, `apscheduler`, `gunicorn`, `litellm-proxy-extras`, `litellm-enterprise` and `rq` are not).
- **The guest's sshd refuses forwarding today.** The seed's drop-in `/etc/ssh/sshd_config.d/10-aieh.conf` sets `AllowTcpForwarding no`, `AllowAgentForwarding no`, `PermitTunnel no`, `AllowUsers agent` (`profiles/seed/user-data.tmpl`). Decision 0013 point 3 already plans dispatcher-owned SSH local forwards, which will need the same directive relaxed (U-01.2, E-01.3.x).
- **The dispatcher's typed create** sends the profile's sha256-pinned template with only `conversation_id` replaced and refuses every other field (E-01.3.1; `integrations/dispatch/README.md`). The template (`agent-server/conversation-create.json`, the F-04.2 fixture) carries no LLM settings (`api_key` null, `base_url` null in F-04.2). No dispatcher exists; `tools/guest.py` under the Owner's account performs its role (inventory `observed_performer`; 0013 point 1).
- Credential custody on the host is the F-06.3 provider: Windows Credential Manager (`CredWriteW`/`CredReadW`, one named entry per credential), keyring on POSIX, fail closed, receipts with fingerprints only. Every entry of the Owner's account is readable by every process of that account, the bootstrap agent sessions included (`fd-bootstrap-shared-identity`; decision 0010 point 1 puts same-account processes outside the threat model).

## Considered options

**Placement and reach (the guest-to-broker path):**

1. **Host-side broker reached over a QEMU `guestfwd`** (the planned shape). Rejected: single stream, no reconnection, broker-before-guest ordering (Context). Not a configuration matter: it is how the chardev forward works at this pin, observed in F-03.3.2. The per-connection `cmd:` form of `guestfwd` is not available on Windows QEMU (not verified here; irrelevant, because the chardev shape is the observed one).
2. **Host-side broker reached through an SSH remote port forward inside the qualified management channel** (`ssh -N -R <guest bind>:<port>:127.0.0.1:<broker port>`, held by the dispatcher with the per-instance key over the existing loopback `hostfwd`; the guest's sshd listens on the docker0 gateway address; one container-guard allow rule). **Chosen.** Per-connection TCP channels (HTTP, pools and streaming work as they do today); created after boot and re-established at will (no launch-record change, no guest restart); torn down with the session; the same channel, key and host-key trust 0013 already chose for host-to-guest connections; `launch.argv` unchanged, so the qualified profile's launch digest and P7 `netdev` checks stand.
3. **Broker inside the guest, outside the agent container** (a guest service on docker0). Rejected: the provider credential would be in the guest, against P5 ("Provider and LLM credentials never enter the guest") and the inventory's custody text; and the guest itself has no egress, so the broker would still need a guest-to-host path with the same problem as option 1 (a single chardev stream carrying one TLS connection to the provider: no pool, no reconnection).
4. **Broker in a separate guest.** Rejected: a second VM (decision 0006 set "an even higher bar" for one), the credential in a guest, and still two forwards of the option 1 kind between the guests and the host.
5. **Broker on SLIRP's host alias `10.0.2.2` with `restrict=off`.** Rejected: `restrict=on` is the qualified enforcement point (P7, F-03.3.2); without it every host loopback service (QMP, the SSH forward, Gitea) is reachable from the guest, and a Windows Firewall rule to compensate is an elevated host act for no in-scope threat (decision 0013 point 6).
6. **A second QEMU network backend** (`-netdev stream`/`socket` to a host user-space network such as gvisor-tap-vsock) or **virtio-vsock**. Rejected: vsock has no Windows host backend; a new network backend replaces the qualified enforcement point and reopens F-03.3.2 (decision 0006: "Do not reopen already-qualified VM isolation without evidence of an actual defect"). Recorded for R-03.x only.

**The adopted gateway mechanism:**

7. **LiteLLM proxy.** Not chosen for the reference. It is not pinned (Context); adopting it is a new component resolution under decisions 0001 s1 and 0005 with a licence gate for its enterprise parts. Its per-key issuance, budgets and spend logs (what 0007 point 4 needs: per-attempt inference access that the broker alone issues and revokes) depend, per its documentation, on a database server, which would be a further component; without one it is a static-key gateway, which fails 0007 point 5's revocation contract (not verified in this invocation: the proxy is not installed and no network was used). It is a large process (its own cost-map fetch, telemetry and plug-in surface) for a loopback service whose job is to hold one key. **Recorded alternative**: re-evaluate under a pin if multi-provider routing, fallbacks or cross-provider spend accounting become requirements.
8. **A generic reverse proxy with header injection** (Caddy, nginx). Not chosen: per-attempt token issuance and revocation at run time, a model allowlist read from the request body, and fingerprint-only receipts into our stores are outside their configuration; the custom part would be written anyway, beside a second host service.
9. **A minimal owned broker** in the blueprint's own component list ("Launcher and credential broker", `#containment-architecture`; "small ... authorization ... adapters", `#integration-contracts`): a loopback HTTP reverse proxy for exactly one provider API family that terminates per-attempt tokens, replaces them with the provider credential, allowlists paths and models, enforces budgets, streams responses unchanged and records fingerprint-only audit. Standard library plus the pinned `urllib3` 2.8.0, under the tools venv (decision 0009 point 8), supervised like the host Gitea under the lifecycle contract. **Chosen.** The upstream mechanisms adopted around it: the SDK's per-conversation LLM settings (`model`, `base_url`, `api_key`), the provider's own HTTP API (passed through, never translated), OpenSSH remote port forwarding with `PermitListen`, netfilter, and the F-06.3 credential provider.
10. **The Agent Server's own secrets and provider-connection routes** (`op-as-unenumerated-routes`). Rejected: they put the credential in the guest and in the conversation's reach (S-01.3.1: the agent can read its container's environment and records).

## Decision

### 1. Placement and principal
The inference broker is a **host-side process in the trusted management domain** (`td-management`, inventory principal `inference-broker`), the sole holder of the provider credential. It runs on the Owner host, bound to `127.0.0.1` only, under the host-service lifecycle contract that the host Gitea uses (supervised, loopback-and-identity inspected). During bootstrap it runs as the Owner's account, like Gitea and `tools/guest.py` (decision 0013 point 1 pattern); when the dispatcher principal is realized (E-01.3.3) the broker runs beside it and the token-issuance call moves to that principal. No separate OS identity is introduced for it (decision 0010 point 7).

### 2. The provider credential: custody, storage, rotation
1. **Holder:** the broker process, in memory, loaded at start. **Storage:** one entry of the OS credential provider (F-06.3), name `AIEH model provider`, user = the provider id, secret = the key; written only by an Owner-run harness command that reads the value from standard input (never argv, environment, file or config), with an `aieh-credential-act/1` receipt carrying the fingerprint. It is never in `config.yml` (decision 0009 point 7 refuses secret-shaped keys), the seed, the guest, a container, the create request, a record, a log or a report; records carry its fingerprint only.
2. **Who can read it:** every process of the Owner's account, including the bootstrap agent sessions (`fd-bootstrap-shared-identity`; decision 0010 point 1). Custody is against the guest and its agents, not against same-account processes; disclosed, not prevented. **Therefore the key is a dedicated harness key** (not the Owner's personal or coding-assistant login, `cred-owner-provider-login`), with a spend cap set at the provider, revocable there by the Owner at any time.
3. **Rotation and revocation** (decision 0007 point 5, row `cred-llm-provider-key`): rotated at the provider by the Owner; reloaded by re-running the set command and restarting the broker; a revocation at the provider fails every attempt closed at its next call. The broker never writes the key anywhere.
4. **A local model server** (if the Owner chooses one) is the degenerate case: the upstream is a loopback address, the credential entry may be absent, and the egress allowlist of section 5 is empty. Model weights are assets under decision 0009.

### 3. Per-attempt inference access
1. The broker **alone issues inference access** (decision 0007 point 4): one random **attempt token** per attempt (`cred-inference-attempt-token`, authority class `scoped`, issuer `inference-broker`, manager `management-dispatcher`, holder the attempt's agent), bound to the reserved conversation id (E-01.1.1), to a model allowlist, to a budget (requests and tokens) and to an expiry; stored hashed in the broker, journaled by fingerprint in the integration store.
2. The dispatcher obtains the token from the broker's **control listener** (section 4) at create time and places it in the create request's LLM settings as the provider API key, with `base_url` the guest endpoint of section 4 and `model` the allowlisted name. The SDK and litellm inside the container then send it where they would send a provider key; **the broker translates nothing**: it accepts the provider's own API shape.
3. The token is, by design, readable by the attempt's own agent (as its conversation keys are today, S-01.3.1 finding 3). Its exposure is bounded to that attempt's budget and model list until revocation. It is revoked at attempt end by the dispatcher, on suspected exposure, on definition revocation, on policy revision, at expiry and on Owner direction (0007 point 5 triggers); revocation is immediate at the broker (the next request answers 401) and leaves a receipt (fingerprint, attempt, trigger, revoker) in the integration store, never in the effects store.
4. No provider credential is ever a role token; no role token is ever sent to the broker.

### 4. The guest `inference` endpoint class and its inspection
1. **The endpoint** is a TCP listener on the guest at **the docker0 gateway address and a declared port** (`172.17.0.1:<inference_port>`; the address pinned by `bip` in Moby's `daemon.json`, declared in `provisioning.moby.daemon_json`), **owned by the guest's sshd as a remote port forward** requested by the dispatcher: `ssh -N -R 172.17.0.1:<inference_port>:127.0.0.1:<broker inference port>`, with `ExitOnForwardFailure=yes`, keepalives, the per-instance key and the profile's `ssh_client_options`, over the existing loopback `hostfwd`. Each container connection becomes one SSH channel and one connection from the host's ssh client to the broker's inference listener on `127.0.0.1`.
2. **Guest composition (seeded, declared, inspected):** the sshd drop-in gains `AllowTcpForwarding remote`, `GatewayPorts clientspecified` and `PermitListen 172.17.0.1:<inference_port>` (no other address or port may be bound; `-L` stays refused until the leaf realizing 0013 point 3 widens it with `PermitOpen`); the **container guard** gains exactly one rule before its refusals, accepting new TCP connections from `docker0` to `172.17.0.1:<inference_port>` (the allowlist slot the egress guard already reserves, applied to the INPUT chain because the endpoint is a guest listener); the **egress guard's allowlist stays empty** (no container opens any connection out of the guest).
3. **Host composition:** the broker's two loopback listeners: the **inference listener** (the only forward target; it serves inference requests under attempt tokens) and the **control listener** (issue, revoke, status; never forwarded; same-account only, disclosed under 0013 point 6). The dispatcher records the forward session (pid, ports, instance) beside the launch record while it holds it.
4. **Ordering and lifetime:** broker up, then the forward, then the token, then the create; the broker and the forward need exist only while attempts run. If the session drops, sshd closes the listener and a container's next connect is refused (fail closed, no hang); the dispatcher re-establishes it idempotently, also after a guest restart (the `hostfwd` port is kept in the launch record). The guest boots and runs without the broker.
5. **Inspection** (`inspect` in the guest, the host census on the host, the catalogue in S-02.x):
   - the sshd drop-in equals the declared text and `sshd -T` reports the three directives;
   - `ss -ltnp`: `172.17.0.1:<inference_port>` owned by sshd exactly when a forward session is recorded, and no other new listener; the guard chains equal the declared rules, the container guard with its one ACCEPT, the egress guard with none;
   - from a job: the endpoint connects and answers 401 without a token (reachability and admission); `172.17.0.1:22`, `:8000`, the published ports, `10.0.2.2:*`, `10.0.2.3:53`, the unconfigured guestfwd address and the off-link targets stay refused (the S-02 catalogue re-run, every compensating case PASS); a name lookup from a job fails closed;
   - the provider key's fingerprint appears nowhere in the guest, the jobs, the instance directory, the records or the reports (the P5 needles gain it);
   - on the host: the broker's two listeners on `127.0.0.1` only and the ssh session process (census); the broker's outbound TCP connections go only to the configured upstream origin.

### 5. Egress
1. **Broker egress allowlist:** exactly one upstream origin, the Owner's chosen provider API host on 443 over TLS with the host's system roots (or a loopback address for a local model server). The broker connects nowhere else: no cost map, no telemetry, no update check (it imports no litellm). On the host this is a code-path control plus disclosure, not an OS-enforced boundary (decision 0013 point 6; a per-process firewall rule would be elevation); its evidence is the broker's connection census and audit.
2. **Agent egress denial:** unchanged except for the one container-guard allow of section 4.2. Containers reach the guest's inference listener and nothing else: not the guest's other listeners, not the peer container, not SLIRP's aliases, not off-link addresses, not `raw.githubusercontent.com`, not a resolver.
3. **The provider's API family is allowlisted by path** (the completion and message routes litellm uses for that family; the exact set is pinned at S-03.2 from observed traffic) and **by model** (the `model` field of the request body against the Owner's list); anything else is refused with a stable code and logged.

### 6. Audit
1. **Recorded per request** (append-only JSON lines under `<managed root>/persistent/logs/inference/`): time, attempt and conversation id, token fingerprint, method and path, model, request and response byte counts, HTTP status and upstream status, latency, and the usage counts the provider reports (from the final event when streaming; `unknown` when absent). **Never recorded:** request or response bodies (they carry prompts, completions and, later, repository content), headers, the token, the provider key.
2. **Per attempt:** a summary receipt (requests, tokens, refusals, revocation) in the integration store at revocation, referenced from the attempt's dispatch record. The provider key's fingerprint is recorded once at broker start. The I7 exposure scan of F-06.3 runs over every line and receipt.
3. Cost accounting is the provider console's; the broker enforces counts and token budgets, not prices.

### 7. Positions on the three named items
1. **The container resolver (8.8.8.8).** The inference path needs no name resolution: `base_url` is the IP literal of section 4.1 (the `host.docker.internal` entry resolves to the same address through `/etc/hosts`, but the configuration does not rely on a recorded deviation). Public resolvers stay unreachable from containers (no route; with a route the egress guard refuses them), so every lookup fails closed. **S-03.2 replaces the public literal by policy:** Moby's `dns` option in `daemon.json` set to the guest's docker0 address, where nothing listens and the container guard refuses the query with an ICMP reject and a counter (a policy denial, in the S-01.4 sense, instead of a topology one), verified by the existing `egr-resolver-*` cases. If the Overseer declines the Moby change, the dead public resolver is recorded as a limit instead; the inference path is unaffected either way.
2. **LiteLLM's start-time cost-map fetch.** The broker opens nothing for it: `raw.githubusercontent.com` is not an upstream and no resolver is reachable, so the inner servers' fetch stays denied at name resolution and the bundled map is used, as today. The outer server keeps `LITELLM_LOCAL_MODEL_COST_MAP=True`. The control still cannot reach containers through the pinned runtime's fixed environment list (E-01.4.3 F-2): if the pinned create request admits a container environment, S-03.2 adds the variable there and verifies the fetch is no longer attempted; otherwise the race's container-side limit stands as recorded. The cost map is pricing metadata; the broker does not use it.
3. **The guestfwd lifetime.** No `guestfwd` is adopted, so "the broker runs before the guest and for its whole life" no longer applies. Its replacement is section 4.4: the broker runs before the first create; the forward exists before the create and is re-established after any loss; a conversation whose forward is gone is refused at connect, not hung; `launch.argv` is unchanged.

### 8. Threat model and disclosed residuals
In scope (decision 0010 point 1): an agent or job reading the provider credential (prevented: it is never in the guest; proved by fingerprint search), reaching the provider directly (prevented: guards and `restrict=on`), replaying another attempt's token (prevented: icc off, per-container records; tokens are per attempt), exceeding budgets (prevented at the broker), or reaching the control listener (prevented: it is not forwarded). Disclosed: same-account host processes can read the credential entry and call the control listener (0013 point 6); the attempt token is readable by its own attempt and persists in that conversation's record in the guest until revocation (a labelled `scoped` secret, P5); prompts and completions leave the host to the provider under the provider's terms; the broker's egress allowlist is enforced in its own code; the SSH session is a host process whose loss stops inference until re-established.

## Consequences
- **Plan leaf S-03.2** builds: `integrations/inference/` (the broker, its config under `components.inference_broker` in `config.yml`, the credential set command, tests with a fake provider), the dispatcher-side forward and token handling in `tools/guest.py` (bootstrap) and the typed create's LLM fields, the seed and profile amendments (sshd drop-in, container-guard allowlist, `bip`, optionally `dns`), `check_profile` (an active `inference` endpoint whose mechanism is a remote forward, not a guestfwd; the guestfwd rule count stays zero), `inspect` (section 4.5), the S-02 catalogue cases for the new allow, and the evidence. Its proof is restated in the authorization request.
- **The typed create** (E-01.3.1) gains the LLM settings fields (`model`, `base_url`, `api_key`) in its template and field allowlist, pinned by sha256 as today; the template remains the one body shape; the `api_key` value is the attempt token and never a provider key (a tamper test). *(Reconciled 2026-11-11: superseded for S-03.2 by amendment 1 item 2 and the plan amendments of 2026-11-10 and 2026-11-11 (Owner decisions (d) on OA-12 and OA-19): S-03.2 does not change the typed create and sends no create with LLM settings; the ACP `agent_settings` block and the two `secrets` names are A-01.2's and E-03.1's, and S-03.3's disposable fixture makes that change for its own qualification profile or waits for A-01.2. The text above is kept as decided.)*
- **Contract and policy amendments (Overseer, as contract owner, at S-03.2):** profiles P7 names the `inference` endpoint's mechanism as the dispatcher-held SSH remote forward on the docker0 gateway and the container guard as its enforcement point, keeping the egress guard's allowlist empty; the profile's `network.endpoints` `inference` entry loses `deferred` and gains the address, port, mechanism and the forward's owner; `network.enforcement_point.mechanism` says "guest-to-host only through the management channel's forwards"; the matrix rows `nm-job-inference` and `nm-review-inference` are reworded (planned until S-03.2 observes them), the broker-to-provider row gains the allowlist; the inventory's `endpoint-inference` location, `inference-broker` identity, `cred-llm-provider-key` storage and lifetime, the new `cred-inference-attempt-token`, the two host listeners and the forward session asset; `policy/role-tokens.json` gains the inference-access grant to the engineering and reviewer roles (issued by the broker, not a role token).
- **Decision 0013 point 3** (dispatcher-owned local forwards) later needs `AllowTcpForwarding yes` with `PermitOpen`; this record's `remote` plus `PermitListen` is compatible and is widened by that leaf, not here.
- **Sequencing:** S-03.2 depends on S-03.1, S-01.2.2 and F-06.3 (plan). Its live qualification needs the interim dispatcher (`tools/guest.py`) to hold the forward and send the create with LLM settings; the live dispatcher transport (E-01.3.2/E-01.3.3) inherits the same calls. E-03.2.2 and K-02.2 depend on S-03.2.
- **Owner acts** (the separate request): the provider choice and key; the credential entry; the broker's two host listeners; the guest-to-host forward and the guest composition changes; the broker's egress to one provider origin; the first model run, on a fixed prompt without repository content, in one disposable guest.

## Owner authorization
Pending: Owner action OA-12, [the S-03.1 authorization request](../evidence/S-03.1-owner-authorization-request.md). Nothing in this record is performed before the Owner's answer is recorded in the bootstrap log. A refusal leaves the strong tier as it is (no model access) and sends the design back to the Architect with the refused item named.


## Amendment 1 (2026-11-10): ACP coding providers through the broker

Approved by the Owner on 2026-11-10 (decision (c) on OA-12), from the Architect's recommendation
[`evidence/S-03-acp-coding-provider-recommendation.md`](../evidence/S-03-acp-coding-provider-recommendation.md) section 3.1, which holds the
source facts and the reasoning. The text above stays as written; where it and this amendment disagree, this
amendment governs. Sections 1, 2, 4, 6 and 7 (placement, credential custody, the endpoint and its inspection,
audit, the three named items) hold for ACP providers unchanged.

1. **Tokens are bound to an API family** (sections 3.1 and 3.2). Each per-attempt token is bound to one API
   family as well as to its conversation, model list, budget and expiry. Model, path, attempt, budget and
   expiry limits are kept.
2. **Two ways the token reaches an attempt** (section 3.2 and Consequences, "The typed create"). For an ACP
   agent (the default engineering coding path: OpenHands' `ACPAgent`, `agent_settings.agent_kind` `acp`), the
   token travels in the create's `secrets` under the pinned registry entry's `api_key_env_var`, with the broker
   endpoint under its `base_url_env_var`. For a native direct-LLM agent (optional), it travels in the LLM
   settings as written above. Each is one template shape per stage. The create's tamper test extends to: no
   secret name beyond the registry's two, and no provider key.
3. **Per-family, untranslated pass-through** (section 5.3). The broker's path and model allowlist becomes
   declared per-family entries, routed by path and passed through without translation. The path and model set
   of a family is pinned from observed traffic at the leaf that first runs that family. No wildcard model
   allowance; model names are verified, never assumed.
4. **Direct-model inference stays an optional capability.** Local inference remains the openai-chat family's
   degenerate upstream (section 2.4).
5. **Withdrawn:** the local-first request's section 3 refinement that narrowed the guest-facing contract to
   the OpenAI-compatible Chat Completions family alone. It would exclude both default ACP providers.
6. **Subscription authentication** (Claude OAuth tokens, a Codex ChatGPT login) is **not qualified for this
   sandboxed path at the pinned versions** (recommendation section 1.2). This is a finding at the pins, not a
   universal or permanent limit; a later pin is re-examined on its own evidence.
7. **Boundaries** (Owner, 2026-11-10). The provider's adapter and CLI run inside the qualified execution
   container, within its enforceable CPU, memory, filesystem, process and network limits. ACP
   permission-suppressing modes confer no authority and are not isolation controls. No unrestricted Owner
   credential, inherited MCP server, unexpected tool, arbitrary ACP command or unapproved network destination
   enters an attempt. The harness builds no orchestration layer of its own and does not replicate OpenHands'
   ACP implementation. Provider selection stays in the governed agent catalog.
8. **Closed "Not verified" item:** the create's credential and endpoint fields for the ACP kind are the
   `secrets` channel and the registry's two variable names (recommendation section 1.1, read at the pin). The
   LLM-settings field names of the native kind stay as listed.

Still open, each its own Owner act or presentation (bootstrap log, OA-12): the exact model identifiers
(including any secondary model Claude Code uses), the key, spend caps and budgets, the broker's host
listeners, the guest forward and hardening change, external egress, the first model call, and the image
adapter check (whether the pinned image contains the Claude Code and Codex ACP adapters; a derived image, if
needed, is presented before adoption; no runtime `npx` fallback).

## Amendment 2 (2026-11-13): no harness spending enforcement

By the product manager, applying the Owner's direction of 2026-11-13 ("Owner direction: reconcile the D1 provider-access requirements before live execution", verbatim in `evidence/bootstrap-log.md`, Decisions), which retires "Harness-enforced spending limits", "Per-attempt
inference budgets", "Budget exhaustion as an authorization failure" and "Requirements for the Owner to choose
spending caps or enforcement mechanisms", and keeps "Anthropic API access through the inference broker",
"Provider credential custody", "Approved network destinations", "Guest isolation and containment" and
"Security-relevant authorization and evidence". The text above, amendment 1 and the Current facts below stay as
written; where they and this amendment disagree, this amendment governs. The Current facts of 2026-11-13 (items 1
and 3: the spending limit in the digest, the token budgets and the cumulative cap) describe the code as built,
until S-03.6 passes; they are no longer requirements.

1. **The attempt token carries no budget** (sections 3.1 and 3.3; amendment 1 item 1). It stays bound to one
   API family, its reserved conversation and attempt, its model list and its expiry, and is revoked as section
   3.3 states. "Budget (requests and tokens)" is retired as a limit; the never-built per-day budget is retired.
   No request is refused for its count or its usage.
2. **An unknown usage closes nothing.** An answer without readable usage, or one cut off by the upstream or the
   client, is audited with its usage `unknown` (section 6.1) and changes no grant: the rule that closed an
   attempt's token for good after one such answer (`BUDGET_USAGE_UNKNOWN`) is retired.
3. **Spending is bounded by the provider account's own limits** (section 2.2; section 6.3). The key stays a
   dedicated harness key, revocable by the Owner at the provider; a spend cap set at the provider is the Owner's
   option, not a requirement of this record. The broker does no cost accounting and enforces no cumulative cap
   (decision 0021 amendment 1).
4. **A provider refusal is an interruption, not an authorization failure.** A provider answer refusing for
   authentication, credit or spending limits, rate or overload, and a lost upstream, are passed through
   unchanged and audited with the upstream status, distinguishable from the broker's own refusals, which carry
   the broker's stable codes. They are not containment or credential stops. What happens to the attempt (its
   end, the revocation of its token, its durable records, and a later new attempt with a new conversation and a
   new token) is the dispatcher's, under plan leaf E-05.8. After a provider authentication refusal, a new attempt
   waits until the engineering manager has recorded its cause, since a revoked key is an early end of the Owner's
   authorization; a containment, credential or unexpected-egress stop is never an interruption. No token is granted again to an existing conversation
   or attempt; native resumption is a deferral of the plan, reconsidered on its own evidence.
5. **What bounds a leaked attempt token** (section 3.3) is its model list, its lifetime (the broker's `max_ttl_s`)
   and its revocation, then the provider account's own limits, which the Owner accepted; no longer a budget.
6. **Kept:** the custody of section 2, the per-attempt identity and revocation of section 3, the endpoint and its
   inspection (section 4), the one egress origin (section 5), the audit (section 6: usage counts stay recorded as
   evidence, never as a limit), section 8's threat model except "exceeding budgets (prevented at the broker)",
   which is retired, and every boundary of amendment 1 item 7.

The code change is plan leaf S-03.6's (the plan amendment of 2026-11-13). Until it passes, the built budgets and
`BUDGET_USAGE_UNKNOWN` stay in the code, and no live act relies on them.

## Amendment 3 (2026-11-14, Proposed with decision 0023): the brokered execution profile

Drafted by the program manager for the product manager, applying the Owner's direction of 2026-11-14 ("Owner
direction: reconcile D1 for isolated, native Claude Code execution", verbatim in `evidence/bootstrap-log.md`,
Decisions), which reads in part "Reconcile ... Decisions 0015 and 0021.", "Do not intermediate subscription
credentials through our inference broker." and "The inference broker remains an optional execution profile, not a
mandatory dependency for native Claude Code execution.". It takes effect when [decision
0023](0023-native-claude-code-execution-profile-native-authentication-and-provider-tunnel.md) is accepted; until
then the text above governs unchanged. The text above, amendments 1 and 2 and the Current facts stay as written;
where they and this amendment disagree, this amendment governs.

1. **Scope.** This record governs the brokered execution profile. The native profile, on which D1 runs, is decision
   0023's: there, no broker holds a credential, no attempt token is issued or revoked, and the guest's forward ends
   at a host tunnel that holds no credential. Nothing built or qualified under this record is changed or
   withdrawn, and it is not a prerequisite of the native profile.
2. **Amendment 1 item 6** (subscription authentication not qualified for this sandboxed path at the pinned
   versions) stands for the brokered path. For the native profile, subscription authentication by the provider's
   long-lived token is qualified, or not, at the pins by plan leaf E-05.11 on its own evidence, as item 6 itself
   anticipated; until then it is not qualified.
3. **Amendment 1 item 7's boundaries apply to every profile.** The provider's adapter and CLI run inside the
   qualified execution container within its limits; ACP permission modes are no boundary; no inherited MCP server,
   unexpected tool, arbitrary ACP command or unapproved destination enters an attempt; no Owner credential enters an
   attempt except, on the native profile, the native token that decision 0023 admits on the Owner's direction ("Permit
   the isolated Claude Code process to access its own authentication credential.") and under the Owner's acts
   (OA-31). The harness still builds no orchestration layer of its own.
4. **Unchanged:** every section above for the brokered profile, the recorded Owner act 3 of OA-12 and its receipt,
   and the pause of acts 1 and 2.

## Evidence
- Plan leaves S-03, S-03.1, S-03.2; the Owner's decisions of 2026-11-07 and the guest-run authorization extension (bootstrap log).
- `profiles/strong-windows-qemu-whpx/profile.json` (`network`, `launch.argv`, `provisioning.agent_server.start_race`, `.environment`, `.admission.network.egress_guard`, `provisioning.moby.daemon_json`); `profiles/README.md` P5, P7; `profiles/seed/user-data.tmpl` (sshd drop-in, `aieh-container-guard`, the server unit).
- `evidence/F-03.3.2-guest-network.md` (the chardev's single connection and `disconnected` state), `evidence/F-04.2-conversation-lifecycle.md` (the containers' resolver, the inner servers' fetch), `evidence/E-01.4.3-start-race.md` and `evidence/E-01.2.2c-fix-requalification.md` F-15 (the cost-map source lines in the bundled 1.105.1), `evidence/S-01.4-network-matrix.md`, `evidence/S-02.2-isolation-evidence.md`, `evidence/F-06.3-credential-provider.md`, `evidence/E-01.3.1-conversation-create.md`; `integrations/dispatch/README.md`; `integrations/credentials/README.md`.
- `composition/lock/python/windows-x86_64.txt` (`litellm==1.105.7`; the proxy extras' absence), `composition/lock/python/requirements.in`, `composition/candidates.json`.
- `security/inventory.json`, `policy/network-matrix.json`, `security/containment-cases.json`; decisions 0003, 0006, 0007, 0009, 0010, 0013; blueprint `#security`, `#containment-architecture`.

## Not verified in this invocation
- LiteLLM proxy's database dependence for virtual keys and the exact `[proxy]` extra set (the proxy is not installed; no network was used).
- The field names of the 1.60.1 create request's LLM settings and whether the Agent Server persists the LLM `api_key` encrypted or in clear in the conversation record (`openapi.json` and the SDK source are not in the checkout); the exact request paths and headers litellm 1.105.1 uses per provider family; whether the pinned create request admits a container environment.
- OpenSSH `PermitListen`/`GatewayPorts clientspecified` and the Windows client's `-R` behaviour (documented; not exercised); a remote-forward listener bound to docker0's address across a dockerd restart; Moby's `bip` and `dns` daemon options in this guest (documented; not exercised).
- The 1.105.7 wheel's source lines (not installed in the checkout; the managed root was out of this invocation's scope).

## Current facts (2026-11-13)

Recorded by the engineering manager at S-03.5's completion ([decision 0021](0021-provider-envelope-model-selection-and-broker-enforced-cap.md), Accepted). The text above is unchanged.

1. The broker's real-provider start is bound to the Owner's authorization: `serve` refuses, before it reads the provider
   key or opens a listener, any family whose upstream is not a loopback IP literal unless the integration store holds
   the governing, confirmed, unexpired authorization recorder receipt of operation kind `provider-envelope` whose target
   is the canonical digest of the live envelope (the provider, the one origin, the spending limit and its enforcement,
   the expiry, the model selection). The one upstream origin of section 5.1 is thereby bound at start, not only
   configured.
2. Models: only the identifiers of the envelope, or of a delegated selection (decision 0018 point 3, decided by the
   engineering manager, naming the governing receipt), are admitted at start, at issuance and per request.
3. Section 6.3 stands: the broker enforces counts and token budgets, not prices. Where the envelope says the provider
   does not enforce the limit (`enforced_by: broker`), the broker enforces a cumulative cap in usage tokens and closes
   the envelope when it is reached or when usage is unknown.
4. Nothing here authorizes a key, an envelope, a cap, egress or a model call: those stay the Owner's (OA-12).
5. (Engineering manager, 2026-11-13) Plan leaf S-03.6 is PASS ([evidence](../evidence/S-03.6-spending-enforcement-retired.md);
   `ef82b76`, `1144776`, `9acfc66`), so amendment 2's "until S-03.6 passes" statements are satisfied: the attempt
   token carries no budget (an issue request carrying one is refused `BUDGET_RETIRED`), `BUDGET_USAGE_UNKNOWN` and the
   other budget refusals are gone, and no request is refused for its count or its usage; items 1 and 3 above no longer
   describe the code: the envelope's digest holds no spending limit (`aieh-provider-envelope/2`) and the broker
   enforces no cumulative cap.

## Current facts (2026-11-13, E-05.6)

Recorded by the engineering manager at E-05.6's completion ([evidence](../evidence/E-05.6-d1-stage-create-secrets.md)). The text above is unchanged.

1. The control listener revokes a grant by its token's fingerprint (section 3.3) or by its conversation and attempt
   (`conversation_id` and `attempt_id` in place of `token_fingerprint`; one grant per attempt), for a dispatcher that
   lost the issue's answer. A revocation by attempt that finds no grant writes a tombstone under the attempt's grant
   receipt key (`inference/attempt/<attempt id>/grant`, format `aieh-inference-attempt-tombstone/1`), after which that
   attempt's issue is refused (`GRANT_ATTEMPT_REVOKED`); per attempt, an issue's receipt and registration and such a
   revocation run one at a time, so no grant is live after a revocation by attempt. Same listener, same revoker,
   receipts in the integration store as before.
2. Section 3.2's issuance and section 3.3's revocation by the dispatcher are, for the D1 stage, E-05.6's
   (`integrations/dispatch/dispatch_inputs.py`): the token travels in the create's `secrets` (amendment 1 item 2), is
   requested only after the reservation and every other input are admitted, is revoked on any failure after the issue
   and at the attempt's end (`end_attempt`), and every record carries its fingerprint only. Every other stage's create
   secrets stay A-01.2's and E-03.1's.
3. Offline only: nothing here was run against a live broker, guest, Agent Server or provider, and nothing authorizes a
   key, an envelope, egress or a model call (OA-12).
