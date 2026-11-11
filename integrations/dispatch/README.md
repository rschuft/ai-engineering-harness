# Dispatch input resolution, create admission and the conversation create

Plan leaves E-01.2.1 (resolution), E-01.2.2 (admission, slice (a)) and E-01.3.1 (the native
conversation create, [below](#the-native-conversation-create-e-0131)), blueprint section
[`#execution-qualification`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#execution-qualification),
dispatch step 01: "Resolve the authoritative Work and profile. Check Backlog readiness,
accepted OpenSpec revision and executable requirements; choose ... a qualified profile."
[`dispatch_inputs.py`](dispatch_inputs.py) is that step's trusted-side resolver. It is
Python standard library only and pure: it reads through injected sources and writes
nothing. Its output feeds
[`reserve_attempt`](../store/README.md#typed-attempt-identity) (step 02). Its
[admission](#admission-before-the-openhands-create) (E-01.2.2) then builds the one OpenHands
create of the reserved attempt from trusted policy only, and validates it again immediately
before the injected transport (step 03): workspace, mounts, caps, runtime, route and body.

Nothing here has run against a live Backlog.md, a live store or a live manifest: **not yet
verified** outside the tests' throwaway directories. One admitted create, built from the
fixture's throwaway inputs and the real `strong-windows-qemu-whpx` declaration (only
`status.operational` set, in a throwaway copy), was sent by `send_create` to a live Agent
Server in a disposable drill guest, and the created container's mounts, caps and runtime
equalled the admitted ones (E-01.2.2 slice (b), `tests/live_admitted_create.py`,
[`evidence/E-01.2.2b-live-drills.md`](../../evidence/E-01.2.2b-live-drills.md)).

## Contract

```
request (identifiers only) + approved-input manifest + injected readers
        -> ResolvedInputs                     (ready for reserve_attempt)
        |  DispatchRefused(code, detail)      (before any reservation or external call)
```

### Request: `ai-engineering-harness/dispatch/request/v1`

```json
{"format": "ai-engineering-harness/dispatch/request/v1",
 "work_id": "TASK-2", "repository": "example-app", "stage": "implement",
 "profile": "strong-windows-qemu-whpx", "catalog_pin": "example-builder-pin"}
```

| Field | Grammar |
|---|---|
| `work_id` | A Backlog.md task id (the planning adapter's `TASK_ID_RE`, at most 64 characters); compared and stored upper case |
| `repository`, `profile`, `catalog_pin` | `[a-z0-9]+(-[a-z0-9]+)*`, at most 64 characters |
| `stage` | the same grammar; it must then be in the integration store's stage set (`implement`, `review`) |

Every field is required, and no other field is accepted. The request never carries a path,
a mount, a digest, a resource ceiling, a runtime, a revision or an ordinal. A field outside
the six is refused as `REQUEST_OVERRIDE_FORBIDDEN` when its name looks like one of those,
otherwise as `REQUEST_UNKNOWN_FIELD`. A value outside its grammar, such as a path in
`repository`, is `REQUEST_FIELD_INVALID`.

### Resolution

`resolve(request, manifest=..., work_sources=..., next_ordinal=..., read_profile=...)`.
The checks run in this order, and the first failing one refuses:

1. the request (shape, fields, grammars; a missing or empty `catalog_pin` is `CATALOG_PIN_REQUIRED`);
2. the repository is in the manifest;
3. the stage is in the store's stage set;
4. a binding approves the stage for the repository;
5. the profile is approved, and bound to that repository and stage;
6. the catalog pin: the manifest approves at least one pin, this pin is approved, and it is
   bound to that repository and stage;
7. the profile file: `profiles/<id>/profile.json`, its sha256 equal to the approved one, its
   `schema` the profile/v1 schema, its `name` the id, and `status.operational` exactly
   `true` (contract C6); then its admission policy (`admission_policy`, E-01.2.2: Docker
   runtime only, caps within the ceilings, the declared mounts; below);
8. the Work: the repository's Backlog.md lists it, and Backlog.md's own readiness
   (`planning_readiness.read_readiness`, P-02.2) reports it ready;
9. the design: every OpenSpec source pointer of the task resolves in git, all of them pin
   one change at one full commit (`design_revision_from_pointers`), and that is the
   accepted revision the manifest records for the change in this repository;
10. the outcome (E-01.3.1): exactly one `outcome:` reference among the task's own Backlog.md
    references, in the grammar the lineage reader parses (`outcome:<uuid>[@<full commit>]`,
    decision 0008). None is `OUTCOME_REF_ABSENT`, a malformed one `OUTCOME_REF_INVALID`, and two
    outcomes, or one at two revisions, `OUTCOME_REF_AMBIGUOUS`;
11. the ordinal: `next_ordinal(work_id, design_revision, stage)` (`store_next_ordinal`
    reads the store's typed claims; `reserve_attempt` remains the arbiter of live claims).

Steps 1 to 6 read the manifest only. No file, Backlog.md or git read happens for an
unapproved repository, stage, profile or pin.

| Injected | Live implementation | Tests |
|---|---|---|
| `work_sources(repository)` | `PlanningWorkSource(planning_adapter.Backlog(...), planning_adapter.Git(...))` for the approved repository | Backlog.md's recorded readiness JSON replayed in process, and a throwaway design repository |
| `next_ordinal` | `store_next_ordinal(store)` | the same, on a throwaway store |
| `read_profile` | `read_profile_file` (the checkout's `profiles/`, byte-exact by `profiles/.gitattributes`) | throwaway profile declarations |

### Resolved record: `ai-engineering-harness/dispatch/resolved-inputs/v2`

`ResolvedInputs` is frozen. `attempt_identity()` gives the store's `AttemptIdentity`;
`intent()` gives `{"dispatchInputs": <the record>, "workRef": "backlog:<work_id>", "outcomeRef":
<outcome_ref>}` for `reserve_attempt`, so the stored intent and its digest carry the approval
provenance, and every reservation carries the two correlation keys the lineage reader follows
(blueprint `#integration-contracts`). `ResolvedInputs.from_json` reads the record back from a
stored intent, strictly. v1 (E-01.2.1, E-01.2.2) had no `outcome_ref`.

| Field | Source |
|---|---|
| `work_id`, `repository`, `stage` | the request, canonical |
| `ordinal` | `next_ordinal` |
| `design_revision` | `openspec:changes/<change>@<commit>` from the task's pointers |
| `profile`, `profile_digest` | the sha256 of the `profile.json` bytes, equal to the approved one |
| `catalog_pin`, `agent_manifest_digest` | the pin's `manifest_sha256`; never null (E-01.1.1 left it nullable until this leaf) |
| `planned_workspace` | the fixed rule `<repository>/<work_id>/<attempt_id>`, relative to the managed root's `workspaces` category; `attempt_id` is the store's `uuid5(ATTEMPT_NAMESPACE, operation_key)`, so each attempt has its own |
| `policy_digest`, `policy_inputs` | below |
| `outcome_ref` | the task's one `outcome:` reference (resolution step 10) |
| `approval` | the manifest's schema, `version` and the sha256 of its bytes |

**`policy_digest`** is the sha256 of the canonical JSON (sorted keys, no whitespace, UTF-8)
of `policy_inputs`, which holds exactly the approved entries the attempt was admitted under
and, since v2 (E-01.2.2), the admission policy read from the approved profile:

```json
{"format": "ai-engineering-harness/dispatch/policy-inputs/v2",
 "repository": {"id": "..."}, "stage": "...",
 "design": {"repository": "...", "change": "...", "commit": "..."},
 "profile": {"id": "...", "sha256": "..."},
 "catalog_pin": {"id": "...", "repository": "...", "commit": "...", "manifest_sha256": "..."},
 "admission": {
   "runtime": {"conversation_runtime": "docker", "selectable": false},
   "route": {"method": "POST", "path": "/api/conversations"},
   "routes": {"path": "profiles/<id>/agent-server/routes.json", "sha256": "..."},
   "create_template": {"path": "profiles/<id>/agent-server/conversation-create.json", "sha256": "..."},
   "workspace": {"category": "workspaces", "working_dir": "/workspace"},
   "caps": {"memory": "4g", "cpus": 2.0, "pids_limit": 512, "max_concurrent_runs": 3},
   "ceilings": {"vcpu": 8, "memory_mib": 16384},
   "mounts": {"source_root": "/srv/scratch/openhands", "binds": [...], "forbidden_sources": [...]}}}
```

It does not cover the manifest's version or digest (they are provenance, beside it), the
binding lists, the Work or the ordinal (the attempt identity). A manifest revision that does
not change these entries leaves the policy digest unchanged; it still changes the intent
digest, so retrying a reserved key under another approval is a `ConflictingReservation`.
policy-inputs/v1 (E-01.2.1) had no `admission`; the pinned test digest changed with the format.

## Admission before the OpenHands create

Plan leaf E-01.2.2, slice (a): the host-side admission validator, fixture-proven. Dispatch
step 03 creates the Docker conversation; this is what stands between the reservation and that
create. The order is the dispatcher's (E-01.3.x):

```
resolve -> reserve_attempt -> admit(resolved, manifest, workspaces)      -> AdmittedCreate
                           -> send_create(admitted, resolved, workspaces, transport)
                              (validates everything again, then transport(method, path, body) once)
```

`admit` and `send_create` take no caller-supplied value: there is no parameter for a path, a
mount, a cap, a runtime, a working directory, a route or a body field. Every value comes from
trusted policy:

| What | Trusted source | Refused as |
|---|---|---|
| route | `POST /api/conversations` (the Docker runtime's `start_conversation`, F-04.2), and it must be the one entry of the profile's pinned route allowlist (`agent-server/routes.json`, S-01.3.1) with `dispatcher` `allowed` | `ROUTE_NOT_ALLOWLISTED` |
| body | the profile's sha256-pinned create template (`agent-server/conversation-create.json`, the F-04.2 fixture) with only `conversation_id` replaced by the reserved one (`conversation_id_for(operation_key)`) | below |
| runtime | `conversation_runtime` `docker` named explicitly in every body (decision 0001 s2), and the server configuration `conversation_runtime` `docker` with `conversation_runtime_selectable` `false`; any other value, an omitted selector or a selectable runtime is refused | `RUNTIME_NOT_DOCKER` |
| working directory | `workspace` exactly `{"kind": "LocalWorkspace", "working_dir": "/workspace"}`: the server-provisioned workspace, which passes no host path (decision 0001 s3); the policy also requires a declared bind whose destination is `/workspace` | `WORKING_DIR_NOT_ALLOWED` |
| caps | the server configuration's `conversation_container_memory`, `_cpus`, `_pids_limit` and `max_concurrent_runs`; `max_concurrent_runs` times each cap must stay within the profile's `ceilings` (`memory_mib`, `vcpu`). The body may carry `container.memory` or `container.cpus` only as exactly the declared value (the server applies a request's caps with no upper bound: F-04.2 deviation `request-caps-override`); any other cap field is refused | `CAPS_ABOVE_CEILING`, `CAPS_OVERRIDE_FORBIDDEN` |
| mounts | the profile's `conversations.mounts` with the conversation's hex id: the effective mount set the container must have is exactly that list (decision 0003). Every source lies strictly under `source_root` and clear of every forbidden source (the list must name the Docker and containerd sockets); destinations are distinct. A body field that would add a mount is refused | `MOUNT_POLICY_INVALID`, `MOUNTS_NOT_DECLARED` |
| host workspace | `planned_workspace` under the `workspaces` category of the `integrations/paths` resolution passed in; below | `WORKSPACE_*` |
| other fields | an allowlist (the template's fields: `conversation_id`, `conversation_runtime`, `workspace`, `agent_settings`, `autotitle`, `container`, `tags`; in `container`, `browser` and the two caps). Every other field is refused; its name only picks the code (a mount, cap, runtime or path name gets that class's code). Each allowlisted field must equal the template's | `BODY_FIELD_UNKNOWN`, `BODY_NOT_TEMPLATE`, `CONVERSATION_ID_MISMATCH`, `BODY_MALFORMED` |

**The host workspace.** The planned workspace must be exactly `<repository>/<WORK-ID>/<attempt
uuid>` in the fixed rule's grammar (a lower-case repository id, the canonical upper-case Work
id, a lower-case uuid; `/` only) and equal to the rule for this attempt. A part whose name
before any extension is a Windows device name (`CON`, `PRN`, `AUX`, `NUL`, `COM0` to `COM9`,
`LPT0` to `LPT9`, their superscript-digit forms, `CONIN$`, `CONOUT$`, `CLOCK$`; any case, with
or without an extension) is `WORKSPACE_RESERVED_NAME`. The identifier grammar admits `con` as a
repository id, so an approved repository named `con` resolves, and is refused here. Absolute,
drive, drive-relative, UNC and device paths, backslashes, `.` and `..`, `:` (streams), trailing
dots and spaces, case variants, non-ASCII look-alikes and empty or extra parts are
`WORKSPACE_PATH_INVALID`. Another attempt's workspace is `WORKSPACE_NOT_PLANNED`. The host path
is the `workspaces` category joined with the three parts. From the category itself down, any
existing part that is a symbolic link, a junction, another reparse point or not a directory is
`WORKSPACE_PATH_UNSAFE`; the walk runs again at the send, so one planted after admission is
refused too. The resolution must be this host's (`WORKSPACE_CATEGORY_UNAVAILABLE`). Admission
only reads (`lstat`) and creates nothing.

**Provenance.** `admit` refuses resolved inputs that another manifest approved, policy inputs
whose sha256 is not the policy digest or whose admission policy is not the approved profile's
(`ADMISSION_MISMATCH`), a profile whose bytes changed since resolution (`PROFILE_DRIFTED`), and
a pinned template or allowlist whose bytes changed (`PROFILE_ARTIFACT_DRIFTED`), is missing
(`PROFILE_ARTIFACT_MISSING`) or is not strict JSON of its shape (`PROFILE_ARTIFACT_INVALID`).
A profile without a complete admission declaration is refused at resolution
(`PROFILE_ADMISSION_INVALID`).

**Defence in depth.** `send_create` takes the `ResolvedInputs` the attempt was reserved under
(its policy digest is the reserved one), re-derives the admission policy from it, re-checks
that policy's rules, and runs every admission check on the `AdmittedCreate` again: identity,
workspace (with the on-disk walk), the template's and the route allowlist's sha256, route, body
and mounts. Only then, through the route-checked client and after decision 0001's
`/server_info` preconditions (E-01.3.1, [below](#the-native-conversation-create-e-0131)), does it
send the body it validated, exactly once. An admission refusal calls the transport zero times. A
transport failure is raised, never retried and never re-routed to another runtime.

**Not closed here.** Two recorded deviations are upstream registry behaviour that no create
field controls: `host.docker.internal:host-gateway` and no `--network none` on every
conversation container (F-04.2 section 7). Whether the running container matches the admitted
mount set and caps is observed guest-side (`conversation-smoke`, and E-01.2.2 slice (b)).

`AdmittedCreate.to_json()` is `ai-engineering-harness/dispatch/admitted-create/v1`: the
operation key, conversation id, route, body, mount set, planned and host workspace, policy
digest and the sha256 of the template and of the route allowlist (since E-01.3.1).

## The native conversation create (E-01.3.1)

Plan leaf E-01.3.1, blueprint `#execution-qualification` dispatch steps 02 and 03 and decision
0001: `dispatch(request, manifest=, work_sources=, integration_store=, workspaces=, transport=,
actor=)` runs one request through the dispatcher's order and creates one native Docker
conversation, or refuses.

```
resolve                         -> ResolvedInputs (a refusal reserves nothing)
reserve_attempt(intent())       -> reserved; the intent carries workRef and outcomeRef
reserved_inputs(store, key)     -> the record re-read from the store
admit(re-read record)           -> AdmittedCreate
create_workspace                -> the host workspace, only now, never through a link
transition dispatched           -> immediately before the send
send_create(re-read record)     -> GET /server_info, P1 to P5, then POST /api/conversations once
transition confirmed            -> with the returned identifiers as its detail; DispatchResult
```

**Every call is checked.** `AgentServerClient(routes_bytes, transport, routes_sha256=)` is the
only way to the transport. `call(method, route, params=, body=)` sends `transport(method, path,
body)` only when `(method, route)` is listed exactly once in the profile's pinned route allowlist
(`agent-server/routes.json`, S-01.3.1, sha256-pinned in the reserved policy) with `dispatcher`
`allowed`. The route is the allowlist's template (`/api/conversations/{conversation_id}`), and
its path parameters must be exactly its placeholders, `conversation_id` a lower-case UUID and
`event_id` one segment. Anything else (an unlisted, `not-used` or `validation` route, another
method, a concrete path, a query string, a case variant, a route listed twice) is
`ROUTE_NOT_ALLOWLISTED` or `ROUTE_PARAMETER_INVALID` before the transport is called. A bodyless
method with a body is `BODY_MALFORMED`. `send_create` builds its client from the allowlist bytes
the admission read (`AdmittedCreate.routes_bytes`, re-checked against the pinned sha256).

**The preconditions (decision 0001).** Before the create, `send_create` reads `GET /server_info`
through the client and `server_preconditions` requires all five; each failed one is named in
`SERVER_PRECONDITION_FAILED`'s context, and the create is not sent:

| | Condition | Source |
|---|---|---|
| P1 | a 2xx answer with a JSON object whose `version` is the pinned API version, the `version` of the pinned route allowlist (`1.60.1`) | decision 0001 s1 (the 1.60.1 line) |
| P2 | `conversation_runtime_routes_v1` in `capabilities` | s2 |
| P3 | `idempotent_conversation_create_v1` in `capabilities` | s2 (the retry rule) |
| P4 | `conversation_runtime` is `docker` | s2, required configuration |
| P5 | `available_conversation_runtimes` is `[]`: the runtime is not selectable | s2, `conversation_runtime_selectable=false` (hybrid only by recorded exception; none is recorded) |

Decision 0001 s2 accepts `"docker" in available_conversation_runtimes` as an alternative to P4.
With P5, which the plan's proof requires, that alternative is closed: a hybrid server is refused
until a recorded exception says otherwise. A transport that raises on the `GET` gives
`SERVER_PRECONDITION_FAILED` with every precondition failed. Decision 0001 does not number the
preconditions; P1 to P5 are this table's numbering of the plan's proof text.

**The request and the answer, as observed.** The request is the admitted body: the pinned
template (the F-04.2 fixture, valid against `#/components/schemas/StartConversationRequest` of the
locked release `openapi.json`, sha256 `3de49fac…e0d0`) with the reserved `conversation_id` and
`conversation_runtime` `docker`. The transport returns the HTTP answer as `{"status": <int>,
"body": <JSON>}` and raises when there is none, the shape tools/guest.py's API calls return. The
answer is the Agent Server's ConversationInfo, `201` for a new conversation and `200` for an
existing one with the same id (F-04.2 sections 4.2 and 4.5). `create_receipt` keeps only its
identifiers: `{format: create-receipt/v1, executionRef: "openhands:conversation/<id>",
conversationId, httpStatus, created}`. `executionRef` is the lineage reader's attempt reference.
Nothing else of the answer, and no event, is stored. The fixture
[`tests/fixtures/agent-server-1.60.1-exchange.json`](tests/fixtures/agent-server-1.60.1-exchange.json)
holds the two calls as the pinned server answered them (`/server_info` complete, the create's
answer as the selected fields the evidence records).

**The store.** The transitions follow the store's
[lifecycle contract](../store/README.md#lifecycle-contract):

| What happened | State | Detail |
|---|---|---|
| a refusal after the reservation and before the send (re-read, admission, workspace) | `reserved` -> `failed` | the refusal (refusal/v1) |
| about to send | `reserved` -> `dispatched` | `create-dispatched/v1`: the conversation id and route |
| a refusal in `send_create` (re-check, allowlist, preconditions): the create was not sent | `dispatched` -> `failed` | the refusal, `create_sent: false` |
| `200` or `201` with the reserved id | `dispatched` -> `confirmed` | the receipt |
| a `4xx`: `CREATE_REFUSED` | `dispatched` -> `failed` | the refusal, `create_sent: true` |
| no answer (the transport raised; re-raised), a `5xx`, another `2xx`, another id: `CreateOutcomeUnknown` | `dispatched` -> `unknown` | the status only |

Nothing is retried. An `unknown` attempt is a live claim, so no other attempt on the same Work,
design revision and stage is reserved until it is reconciled by its reserved conversation id
(E-01.4.x). Treating a `5xx` as `unknown`, not `failed`, is this leaf's conservative reading of
decision 0001's "any non-2xx is a refusal": the dispatch stops either way, and an outcome that
may have created a conversation is reconciled before another attempt.

**The re-read record.** `reserved_inputs(store, key)` reads the reservation back: the attempt
must still be `reserved` (`ATTEMPT_NOT_RESERVED`), the stored intent must have its digest, the
record must be `resolved-inputs/v2` exactly (`ResolvedInputs.from_json`), its identity must be
the typed identity row, and the stored intent must be exactly the record's own intent (its
`workRef`, `outcomeRef` and typed identity included). Anything else is `RESERVATION_INVALID`.
`admit` and `send_create` receive this record, not the resolution's object.

**The workspace.** `create_workspace` runs after admission. It creates the `workspaces` category
through `aieh_paths.ensure` when the category is missing. It then creates one directory per part
with a single `mkdir`, under a parent that `lstat` has just shown to be a plain directory, and
checks each created directory the same way. Then it walks the whole path again. A link, junction,
reparse point or file anywhere from the category down is `WORKSPACE_PATH_UNSAFE`. A junction
planted between the check and the `mkdir` remains a race the walk detects afterwards, not one it
prevents.

**Not this leaf.** The live transport and the per-attempt role tokens are E-01.3.3
([below](#the-live-transport-e-0133) and [the stage's role token](#the-stages-role-token-e-0133)),
built offline. The create body is still the F-04.2 disposable template
(finding F3, carried to A-01.x and E-03.1). Reconciliation and the idempotent retry are E-01.4.x.
The independent `docker inspect` of the created runtime is E-01.5. Nothing here has run against a
live Agent Server: **not yet verified** live.

## The live transport (E-01.3.3)

[`guest_transport.py`](guest_transport.py) is the dispatcher's one live transport.
`GuestTransport(api, profile, api_login=)` is the `transport(method, path, body)` that
`AgentServerClient` calls. Each call is one request through `tools/guest.py`'s `GuestApi`: SSH
over the instance's host-loopback forward with its per-instance key, and the API probe run in the
guest as the login the profile declares (`identity.guest_user`, `agent`). It returns
`{"status": <int>, "body": ...}` for every HTTP answer and raises `TransportError` when there is
none (`NO_ANSWER`). `for_instance(guest, ctx, name)` builds it for a running provisioned
instance.

This is the bootstrap reading of decision 0013 point 1 (the Overseer's ruling of 2026-11-11): the
dispatcher principal is the Owner's account acting through this module over `GuestApi` as
`agent`, the one login that reads the management key. The cut-over is the code path: op-as-* on
Work goes only through the dispatch module, and `tools/guest.py`'s probes keep their vantage. The
transport refuses a profile that does not declare that custody (`KEY_CUSTODY_UNDECLARED`: the
login is the key file's group, the file `root` `0440`, its directory `root` `0750`) and a channel
that runs as another login (`LOGIN_MISMATCH`).

The key is read in the guest only, from its file. The SSH command line and the guest python's
arguments carry its path, the listener and the request, never the key. It never enters the host
process: the probe sends it on the guest's loopback, redacts it from every answer and counts it,
and an answer that carried it is refused (`SECRET_IN_ANSWER`). The transport never opens the host
custody copy, which the provision and inspect steps fingerprint (disclosed under decision 0013
point 6). `calls` records each call's method, path, status, seconds and the sha256 of its
canonical body (`body_sha256`), never a body or an answer. `tools/guest.py drill --kind
admitted-create` and `tests/live_admitted_create.py` use this transport; neither has a bridge of
its own. **Not yet verified** live.

The custody probe (prepared, **not run**) runs from
[`tests/live_custody_probe.py`](tests/live_custody_probe.py), which drives `tools/guest.py`'s
`custody_probe` (its decision rule, `CUSTODY_PROBE_RULE`, is fixed before any run) and supplies its
step (5): one `implement` and one `review` attempt dispatched over this transport on the fixture
with the real declaration, each delivered its stage's token from the credential provider behind a
read-only wrapper (a write is a stop), both conversations then deleted
([`docs/development.md`](../../docs/development.md), the guest operations).

## The stage's role token (E-01.3.3)

Plan leaf E-01.3.3, decision 0007 point 4 and decision 0013 point 7:
[`attempt_tokens.py`](attempt_tokens.py) delivers the stage's Gitea bot token per attempt, into the
dispatcher's own attempt context and never into a conversation container. Untrusted code has no network
path to Gitea; proposals leave by exchange, and the dispatcher pushes as the bot it holds custody of.

| Stage | Role (`gitea_roles.ROLES`) | Bot | Credential (`policy/role-tokens.json`) | Entry |
|---|---|---|---|---|
| `implement` | `builder` | `aieh-bot-builder` | `cred-gitea-bot-builder` | `AIEH Gitea bot builder` |
| `review` | `reviewer` | `aieh-bot-reviewer` | `cred-gitea-bot-reviewer` | `AIEH Gitea bot reviewer` |

`STAGE_ROLES` covers exactly the store's stage set, one role each; the module refuses to load
otherwise.

```
with attempt_role_token(store, operation_key, provider=provider, port=gitea_port) as delivery:
    repository.push(url, refspec, credential=delivery.credential())   # the dispatcher's own push
    log(delivery.record())                                            # fingerprints only
```

It takes no stage, role, bot or entry from its caller. The checks run in this order, and the first
failing one refuses with `DispatchRefused` before anything later is read or sent:

1. the attempt's dispatch record, re-read from the store by `stored_inputs` (the same checks as
   `reserved_inputs`: its digest, its typed identity and its own intent), and the attempt
   `confirmed`. Otherwise `RESERVATION_INVALID` or `ATTEMPT_NOT_CONFIRMED`, and the credential
   provider is not read;
2. the stored stage's one entry, read through `gitea_roles.read_token`, and no other entry. No entry is
   `ROLE_TOKEN_MISSING`. An entry naming another account, or a value that is not a Gitea token (40
   lower-case hexadecimal digits), is `ROLE_TOKEN_MISMATCH`. A provider that fails is
   `ROLE_TOKEN_UNAVAILABLE`;
3. Gitea's own view of the token, `GET /api/v1/token`, which needs no scope. A `401` is
   `ROLE_TOKEN_REJECTED`. A lost answer, or anything but a `200` token view, is
   `ROLE_TOKEN_UNVERIFIED`. A token that authenticates as another account, or with scopes other than
   the role's, is `ROLE_TOKEN_MISMATCH`.

Inside the context the token is held in memory only. `credential()` gives the
[`integrations/repository`](../repository/README.md) `Credential` (`Authorization: token`, sent to the
remote's origin only). `record()` gives `ai-engineering-harness/dispatch/role-token-delivery/v1`: the
operation key, attempt id, stage, role, bot, entry, credential id, scopes and the token's fingerprint
(`sha256:` and 16 hex digits), never the token. `repr` shows the fingerprint, and the object refuses to be
copied or pickled. While the context is open, `AgentServerClient` refuses any call whose path or body
holds the token (a 40-hex run whose sha256 is held) or its fingerprint (`ROLE_TOKEN_EXPOSURE`), before
the transport: nothing the dispatcher sends into the guest can carry it. The holds are counted, because
two attempts of one stage hold the same standing token. When the context ends, the in-memory reference is
dropped and `credential()` refuses.

**Three lifecycles** (decision 0007 point 4; the Owner's correction of 2026-11-11):

1. **The standing bot credential**, in the host's credential provider, is issued, rotated and revoked only by
   the existing administrative authority ([`gitea_roles.py`](../gitea/README.md) `provision`, `rotate` and
   `retire`, the site administrator's acts) on defined security and lifecycle triggers, never on routine
   attempt completion. Gitea 28.3.0 gives the dispatcher no replacement mechanism: no token lifetime, and a
   new token only from the site administrator's CLI. The dispatcher is granted no issuance.
2. **Its per-attempt use** is this context: obtained only for a confirmed attempt, held in memory for the
   bounded operation, and released when the operation ends. **Releasing the in-memory reference is not Gitea
   revocation**: the standing token stays valid, and a concurrent or later attempt of the stage keeps using
   it. Nothing in this package revokes, mints or writes a credential entry. A token that Gitea refuses
   (revoked by the administrative lifecycle, or not this instance's) is `ROLE_TOKEN_REJECTED` until that
   lifecycle replaces the entry (`rotate` resumes over a token Gitea already refuses).
3. **The per-attempt inference token** (decision 0015) is a separate credential, issued by the inference
   broker, bounded to the attempt and revoked at attempt end; it is not handled here.

**Disclosed same-account limit:** during bootstrap the Owner's account can read the standing credentials in
its Credential Manager (decision 0013 point 6). Only fakes have been used: **not yet verified** live
([`evidence/E-01.3.3-dispatcher-custody.md`](../../evidence/E-01.3.3-dispatcher-custody.md)).

## The containment observation (S-03.3, slice 1)

Plan leaf S-03.3's proof as amended on 2026-11-11 (the Owner's decision on OA-19): the ACP coding provider "and
every process it starts, including any sub-agent or delegated session, run in the execution container as
descendants of the inner server under the same limits, shown by the process inventory and an independent docker
inspect, and no unexpected conversation appears on the outer server", and the evidence distinguishes the
provider's own delegation from OpenHands' `start_child_conversation` route. The slice plan is
[`evidence/S-03.3-slice-plan.md`](../../evidence/S-03.3-slice-plan.md).
[`conversation_containment.py`](conversation_containment.py) is one standard-library file, sent to the guest as a
file and run there by `python3`; its verdicts run on the host. Built and tested offline only: **not yet verified**
in a guest, and its wiring into `tools/guest.py` is a later slice.

| Vantage | Command | What it lists |
|---|---|---|
| Inside the conversation container, as its user (through the inner server's bash route, as the job probe runs) | `collect container` | Every process of the container's PID namespace: pid, parent, executable, `argv0`'s last segment, the first absolute path among the next three arguments (the script an interpreter runs) and the count; `Uid`, `Gid`, `Groups`, the five capability sets, `NoNewPrivs`, `Seccomp`; the cgroup v2 path. The listening TCP sockets with their owning pids (from `/proc/<pid>/fd`). The container's `memory.max`, `cpu.max` and `pids.max` |
| The guest root | `collect host --pid <State.Pid>` | Every host process in the PID namespace of the container's init (`docker container inspect`'s `State.Pid`), with the same fields and its namespaced pids (`NSpid`); any process outside that namespace whose parent is inside; the limits of the init's cgroup |

The output is one line, `AIEH-CONTAINMENT-JSON ` and the snapshot (`ai-engineering-harness/containment/snapshot/v1`).
No other argument value, no environment, file content or socket payload is read. A process that ends while it is
read is counted as `vanished`; a file that cannot be read is recorded as an error, never as a value.

| Verdict | Fails when |
|---|---|
| `container_verdict(snapshot, expected=)` | PID 1 is missing or has a parent; a process other than PID 1 has parent 0 (entered from outside the namespace); not exactly one process owns the inner server's listener (port 8000); a process lacks the expected user (all four `Uid` and `Gid` values), PID 1's `Groups`, empty capability sets, `NoNewPrivs` 1 or `Seccomp` 2, or its status is unreadable; a process is outside PID 1's cgroup; a process does not descend from the inner server, or its chain is lost (the inner server's own ancestors, and the collector's own chain, which is still judged for identity and cgroup, excepted); an `npx` or `npm` process exists; the container's limits are not the admitted caps; with a provider expected, its adapter is not a direct child of the inner server (`argv0` `node`, the script `/acp-node/bin/claude-agent-acp` or `codex-acp`) or its executable is not `/acp-node/bin/node` |
| `host_verdict(snapshot, inspect=, container=, expected=)` | the snapshot is not of the inspected init; `HostConfig` `Memory`, `NanoCpus` or `PidsLimit`, or the cgroup's files, are not the admitted caps; a member is outside the init's cgroup, lacks the identity or has no namespaced pid; a process outside the namespace has a parent inside; with a provider expected, an adapter is not seen from the guest root with the same executable (a transient provider process that ended between the two views is listed as `provider_vanished`, not failed) |
| `sets_verdict(before, after, conversation_id=)` | a container or an **outer**-server conversation appeared during the turn; an **inner**-server conversation appeared whose `parent_conversation_id` is not the observed conversation. A new inner conversation whose parent is the observed one is classified as started through the children route (`delegation.children_route`), the route `start_child_conversation` uses, so the record distinguishes it from the provider's own processes (`provider_tree`) |

`expected` holds the profile's job confinement (`uid`, `gid`, `capabilities`, `no_new_privs`, `seccomp`), the
admitted caps (`expected_limits(memory, cpus, pids_limit)`: Docker's `--memory`, `--cpus` and `--pids-limit` as
cgroup v2 values and as `HostConfig` values) and `provider` (`claude-code`, `codex`, or `None`). The adapter
identities come from the pinned image's files (the image adapter check), not from a running provider; a provider
whose real process shape differs is reported as not observed, with the inner server's children listed, never
passed. Every verdict fails closed, and a snapshot, inspection or set that is not of its shape raises
`ContainmentError` (`SNAPSHOT_INVALID`, `EXPECTED_INVALID`, `INSPECT_INVALID`, `SETS_INVALID`, `LIMITS_INVALID`,
`NO_SNAPSHOT`, `MODE_INVALID`, `TARGET_INVALID`) instead of being judged.

## Approved-input manifest: `ai-engineering-harness/dispatch/approved-inputs/v1`

```json
{"schema": "ai-engineering-harness/dispatch/approved-inputs/v1", "version": 1,
 "repositories": [{"id": "example-app"}],
 "designs": [{"repository": "example-app", "change": "add-search-freshness", "commit": "<full commit>"}],
 "profiles": [{"id": "strong-example-profile", "sha256": "<sha256 of profile.json>"}],
 "catalog_pins": [{"id": "example-builder-pin", "repository": "example-catalog",
                   "commit": "<full commit>", "manifest_sha256": "<sha256>"}],
 "bindings": [{"repository": "example-app", "stage": "implement",
               "profiles": ["strong-example-profile"], "catalog_pins": ["example-builder-pin"]}]}
```

[`examples/approved-inputs.example.json`](examples/approved-inputs.example.json) is a
complete synthetic example. Every key is required and no other key is accepted, at any
level. `check_manifest` reports:

| Code | When |
|---|---|
| `MANIFEST_SCHEMA` | not an object; wrong `schema`; a missing or unknown key; a section that is not a list or an entry that is not an object; a binding with no profile |
| `MANIFEST_VERSION` | `version` is not an integer of at least 1 |
| `MANIFEST_ID_INVALID` | an identifier, change id or identifier list outside its grammar |
| `MANIFEST_COMMIT_NOT_FULL` | a commit that is not 40 or 64 lower-case hex digits |
| `MANIFEST_DIGEST_INVALID` | a sha256 that is not 64 lower-case hex digits |
| `MANIFEST_STAGE_UNKNOWN` | a binding stage outside the store's stage set |
| `MANIFEST_DUPLICATE` | a repeated repository, profile or pin id, design (repository, change), binding (repository, stage), or id within a binding list |
| `MANIFEST_UNKNOWN_REFERENCE` | a design or binding naming an unapproved repository, or a binding naming an unapproved profile or pin |
| `MANIFEST_JSON` | not strict JSON: a duplicate object key, NaN or Infinity |

A catalog pin's `repository` names the catalog's repository; it need not be one whose Work
is dispatched.

**Accepted design revisions.** The blueprint records acceptance in OpenSpec ("Record
acceptance ... Accepted design revision") but no mechanism yet marks a change accepted. The
manifest's `designs` entries are therefore the approval source for "accepted OpenSpec
revision": one accepted commit per change and repository, replaced when a changed design is
accepted again.

### Custody (decision 0009, points 1, 2, 7 and 11; decision 0010)

- The live manifest is an authorization record under `persistent/`: the `state` category of
  the managed data root, `<state>/dispatch/approved-inputs.json`. `manifest_path()` computes
  it through `aieh_paths` and creates nothing.
- `load_manifest` refuses a relative path or one with `.` or `..` parts, and a path inside or
  containing the checkout (before reading it, and again after resolving links). The request
  never names a manifest.
- The repository holds only this schema, its checker, the synthetic example and the test
  fixtures. Writing the live manifest is not this leaf's: catalog pins come from A-01.1's
  protected promotion; repository, design, profile and binding entries from governance.
- Placement is not a security boundary (decision 0010). Agents are kept from the managed
  root by the execution guest, the mount policy, bundle exchange and the role-token matrix
  (decision 0009 point 11). During bootstrap, host-side processes of the Owner's account can
  read and change it (`fd-bootstrap-shared-identity`); the record's sha256 in every
  reservation makes a change visible afterwards, not impossible.

## Refusal codes

`DispatchRefused.code` is one of `REFUSALS`; `to_json()` gives
`ai-engineering-harness/dispatch/refusal/v1` with the code, its meaning, a detail and context.

| Code | Meaning |
|---|---|
| `REQUEST_MALFORMED` | not a request/v1 object with its fields |
| `REQUEST_UNKNOWN_FIELD` | a field outside the contract |
| `REQUEST_OVERRIDE_FORBIDDEN` | a field that tries to supply a path, mount, digest, resource, runtime, revision or ordinal |
| `REQUEST_FIELD_INVALID` | a value outside its identifier grammar |
| `MANIFEST_PATH_INVALID`, `MANIFEST_INSIDE_CHECKOUT`, `MANIFEST_MISSING`, `MANIFEST_UNREADABLE`, `MANIFEST_INVALID` | the manifest cannot be used |
| `REPOSITORY_NOT_APPROVED` | the repository is not approved |
| `STAGE_UNKNOWN`, `STAGE_NOT_BOUND` | the stage is unknown, or not approved for the repository |
| `PROFILE_NOT_APPROVED`, `PROFILE_NOT_BOUND` | the profile is not approved, or not bound to the repository and stage |
| `NO_APPROVED_CATALOG` | the manifest approves no catalog pin |
| `CATALOG_PIN_REQUIRED`, `CATALOG_PIN_UNKNOWN`, `CATALOG_PIN_NOT_BOUND` | no pin named, an unapproved pin, or one not bound |
| `PROFILE_MISSING`, `PROFILE_DRIFTED`, `PROFILE_INVALID`, `PROFILE_NOT_OPERATIONAL` | the profile file is absent, changed since approval, not this profile's declaration, or not operational |
| `WORK_SOURCE_UNAVAILABLE`, `WORK_NOT_FOUND`, `WORK_UNREADABLE`, `WORK_NOT_READY` | the Work cannot be read, does not exist, or Backlog.md does not report it ready |
| `DESIGN_POINTER_ABSENT`, `DESIGN_UNRESOLVED`, `DESIGN_AMBIGUOUS` | the task has no source pointer, one does not resolve, or they pin several revisions |
| `DESIGN_NOT_ACCEPTED`, `DESIGN_REVISION_MISMATCH` | no accepted revision of the change, or the task pins another one |
| `OUTCOME_REF_ABSENT`, `OUTCOME_REF_INVALID`, `OUTCOME_REF_AMBIGUOUS` | the task has no `outcome:` reference, a malformed one, or several outcomes (or one at several revisions) |
| `IDENTITY_INVALID` | the resolved inputs do not form a valid attempt identity |
| `PROFILE_ADMISSION_INVALID` | the profile declares no complete, well-formed admission policy |
| `PROFILE_ARTIFACT_MISSING`, `PROFILE_ARTIFACT_DRIFTED`, `PROFILE_ARTIFACT_INVALID` | a pinned create template or route allowlist is absent, changed, or not strict JSON of its shape |
| `ADMISSION_MISMATCH` | the resolved inputs or the admitted request do not match the approval they claim |
| `RUNTIME_NOT_DOCKER` | a local, process, selectable or omitted runtime, in the server configuration or the body |
| `CAPS_ABOVE_CEILING`, `CAPS_OVERRIDE_FORBIDDEN` | the declared caps times the concurrent runs exceed the guest ceilings; a body cap other than the declared one, or a cap field the policy does not establish |
| `MOUNT_POLICY_INVALID`, `MOUNTS_NOT_DECLARED` | declared binds outside the rules; an effective mount set other than the declared one, or a body field that would add a mount |
| `WORKING_DIR_NOT_ALLOWED` | the body's workspace is not the server-provisioned `/workspace` |
| `ROUTE_NOT_ALLOWLISTED` | a call (the create or any other) whose route the pinned allowlist does not list exactly once with `dispatcher` `allowed`; or a create that does not target `POST /api/conversations` |
| `ROUTE_PARAMETER_INVALID` | a route's path parameters are not exactly its placeholders, each in its grammar |
| `BODY_MALFORMED`, `BODY_FIELD_UNKNOWN`, `BODY_NOT_TEMPLATE`, `CONVERSATION_ID_MISMATCH` | the body is not an object (or a bodyless call carries one), carries a field outside the allowlist, differs from the pinned template, or lacks the reserved conversation id |
| `WORKSPACE_CATEGORY_UNAVAILABLE`, `WORKSPACE_PATH_INVALID`, `WORKSPACE_RESERVED_NAME`, `WORKSPACE_NOT_PLANNED`, `WORKSPACE_PATH_UNSAFE` | the host workspace: no usable category; outside the fixed rule's grammar; a Windows device name; not this attempt's; a link, junction, reparse point or non-directory on disk |
| `SERVER_PRECONDITION_FAILED` | `GET /server_info` does not show P1 to P5 (above), or was not answered; the create is not sent |
| `RESERVATION_INVALID`, `ATTEMPT_NOT_RESERVED` | the stored reservation is not the dispatch record of its typed identity; the attempt is no longer `reserved` |
| `CREATE_REFUSED` | the Agent Server answered the create with a `4xx` |
| `ATTEMPT_NOT_CONFIRMED` | a role token was asked for an attempt that is not `confirmed` |
| `ROLE_TOKEN_MISSING`, `ROLE_TOKEN_UNAVAILABLE` | no entry for the stage's bot; the credential provider failed |
| `ROLE_TOKEN_MISMATCH` | the entry names another account or holds no Gitea token; the token authenticates as another account or with other scopes |
| `ROLE_TOKEN_REJECTED`, `ROLE_TOKEN_UNVERIFIED` | Gitea answered `401` for the token; Gitea's answer was lost or not a token view |
| `ROLE_TOKEN_EXPOSURE` | an Agent Server call would carry a delivered role token or its fingerprint |

**No approved catalog means no dispatch.** `agent_manifest_digest` is required. Until
A-01.1 promotes approved catalog pins into the manifest, every request is refused
(`NO_APPROVED_CATALOG` or `CATALOG_PIN_REQUIRED`). That is intended. Today's checked-in
profiles also declare `operational: false`, so they are refused even when approved.

## Commands

Run from the repository root (`python3` outside Windows):

```
python -I -B -m unittest discover -s integrations/dispatch/tests -v                         # task dispatch:test
python -I -B integrations/dispatch/dispatch_inputs.py check-manifest --manifest FILE        # task dispatch:check-manifest
python -I -B integrations/dispatch/dispatch_inputs.py manifest-path                         # task dispatch:manifest-path
```

`check-manifest` schema-checks a file and prints a `manifest-check/v1` JSON report; exit 0
PASS, 1 FAIL (each problem as `FAIL <CODE>: ...` on stderr), 2 could not read. It admits
nothing and accepts any path. `manifest-path` prints the live manifest's expected location;
it creates and reads nothing there (exit 2 on a managed-root refusal).

## Tests

[`tests/test_dispatch_inputs.py`](tests/test_dispatch_inputs.py), offline, needs git:

| Class | What it shows |
|---|---|
| `AcceptanceRefusalTests` | **the proof.** Each refusal with its code, and with nothing reserved and no ordinal asked for: an unapproved repository; a design revision other than the accepted one, a change with none accepted, unresolvable pointers (digest, revision, artifact), no pointer, several revisions; an unapproved, unbound, drifted (content, line endings, one byte), missing, invalid or non-operational profile; an unknown, unbound or missing catalog pin, and a manifest with no pins; an unknown or unbound stage; blocked, missing-dependency and finished Work, unknown and unreadable Work; extra fields; caller-supplied path, digest, runtime, resource, revision and ordinal fields; paths in identifier fields; malformed requests |
| `SuccessTests` | the record's fields; it feeds `reserve_attempt`, which reserves (and is idempotent); the next resolution asks for ordinal 2 with its own workspace, which the store refuses as a live claim until the first attempt fails; the review binding; case-insensitive Work ids; the checked-in profiles are refused as not operational |
| `DeterminismTests` | the same inputs give an identical record and intent digest; the policy inputs (v2, with the admission policy) and a pinned golden policy digest; each policy input changes the digest; a manifest revision changes provenance and the intent digest but not the policy digest, so a retry under it conflicts; the record is immutable |
| `ManifestCheckerTests` | the example is valid; schema, version, identifiers, duplicates (also duplicate JSON keys), unknown references, non-full commits, digest format, unreadable bytes; type fuzzing never crashes |
| `ManifestCustodyTests` | the checkout (inside or containing) is refused before reading; path shapes; a manifest outside the checkout loads; `manifest_path` is `<state>/dispatch/approved-inputs.json` and creates nothing |
| `CliTests` | `check-manifest` exit codes and report; `manifest-path` with `AIEH_DATA_ROOT` in a throwaway directory creates nothing |

The design repository is built by the planning fixture (`two_task_fixture.build_repo`, a
reproducible commit), and Backlog.md is its own recorded readiness output
(`integrations/planning/tests/fixtures/readiness/`), so the Work and design checks run
against real Backlog.md JSON and real git objects.

[`tests/test_work_source_operation.py`](tests/test_work_source_operation.py) (F-09.4), on the
same fixture: one `PlanningWorkSource.read` is one adapter operation, so Backlog.md's `task
list` is run once (the read and the readiness evaluation both ask for it), every pointer is
resolved through one git batch reader, and the reader ends with the read, also when it raises.

[`tests/test_dispatch_admission.py`](tests/test_dispatch_admission.py) (E-01.2.2), on the same
fixture, with every create through a counting fake transport: each refusal asserts it was
called **zero** times, each positive control **exactly once** with the exact expected body. The
managed root is an `AIEH_DATA_ROOT` in the throwaway directory.

| Class | What it shows |
|---|---|
| `PositiveControlTests` | resolve, reserve, admit, send: one call with the pinned template and the reserved conversation id, the declared mount set with the conversation's hex id, the host workspace under the `workspaces` category (nothing created); the checked-in strong Windows profile's declaration (only `operational` flipped, in a throwaway copy) admits; the ceiling boundary admits; the declared cap values may be sent; plain existing directories admit; determinism; no parameter takes a caller choice; a failed create is not retried or re-routed |
| `WorkspaceDenialTests` | path shapes (`..`, absolute, drive, UNC, device, backslash, streams, trailing dot or space, case, look-alikes, empty or extra parts); Windows device names, from an approved repository named `con` (and `prn`, `aux`, `nul`, `com1`, `com0`, `lpt9`) through the real resolver and in any part and form; another attempt's workspace; an altered admitted host path; junctions at the category, repository, Work and attempt, and a file, at admission and planted after it; a symbolic link (skipped without the privilege); a missing or foreign-platform category |
| `ProfilePolicyDenialTests` | an approved profile declaring a local, process, absent, case-variant or selectable runtime (refused at resolution, nothing reserved); caps times runs above the ceilings; malformed caps or ceilings, no Agent Server declaration; binds on the Docker socket, Moby's data root, outside or at the source root, around a forbidden source, with `..` or an unknown placeholder, a relative or duplicate destination, no `/workspace` bind, the socket no longer forbidden; a route allowlist marking the create `not-used` or `validation`, listing it twice or not at all; a drifted, missing, malformed or misplaced pinned artifact; a template with a local or omitted runtime, a host or remote working directory, a cap override, a pids field, volumes, an initial message or an image |
| `TamperDenialTests` | an admitted request altered after construction and refused by `send_create`: 26 body alterations (runtime, working directory, caps, mounts, unknown fields, template fields, conversation id), non-object or non-strict JSON, the mount set (extra, missing, reordered, read-only, altered, none), the route, the template bytes, the identity and digest; resolved policy inputs altered with or without a matching digest, and forged consistent pairs breaking the ceilings, the runtime, the route, the working directory or the mount policy; provenance (another manifest, a drifted profile, a wrong profile digest, wrong types) |

[`tests/test_conversation_create.py`](tests/test_conversation_create.py) (E-01.3.1), on the same
fixture, with a fake Agent Server that replays the recorded answers of
[`tests/fixtures/agent-server-1.60.1-exchange.json`](tests/fixtures/agent-server-1.60.1-exchange.json).
Every refusal asserts that the create was never sent, and that the transport was called zero
times wherever nothing may be called. The positive control asserts exactly one `GET
/server_info` and one create with the exact body.

| Class | What it shows |
|---|---|
| `RouteAllowlistTests` (unit) | over every route of the pinned allowlist, a call is sent only for `dispatcher` `allowed`, with the rendered path; unknown paths, other methods, concrete paths, query strings, trailing slashes, case variants, `validation`, `not-used` and WebSocket routes, an allowed route listed twice or re-marked, wrong, extra, missing or out-of-grammar path parameters, a body on a `GET`, and a drifted or malformed allowlist are refused with zero calls |
| `ServerPreconditionTests` (unit) | the recorded `/server_info` meets P1 to P5; each precondition alone refuses (another version, a non-2xx or malformed answer, a missing capability, a local, process, case-variant or absent runtime, a selectable runtime list), and several failures are all named |
| `CreateReceiptTests` (unit) | 201 is created, 200 existing; another, missing or hex id, other statuses and non-objects give no receipt; the execution reference parses as the lineage reader's attempt reference |
| `DispatchTests` | the positive control (two calls, the store's three transitions and their details, `workRef` and `outcomeRef` in the reservation, nothing of the answer but its id stored, no event route called, the workspace created as plain directories); an existing conversation is confirmed as existing; the call order and the re-read record (spied: admit and `send_create` get the store's record, not the resolution's object; admission ran with no workspace, the send on a `dispatched` attempt with one); a stored intent altered in seven ways is `RESERVATION_INVALID` and failed; `reserved_inputs` on a missing, untyped or no longer reserved attempt; a resolution refusal reserves nothing; an admission refusal is failed and creates no workspace; junctions planted after admission at the category, the repository and the Work, and a file at the workspace, are refused and nothing is created through them; every precondition case refuses the create through `dispatch` (one `GET`, no `POST`, failed with `create_sent` false), as do an unanswered `/server_info` and an allowlist that no longer allows it; a 4xx is `CREATE_REFUSED` and failed; a 5xx, a 202 or another conversation's id is `unknown` (reconciliation required) and never retried; a lost answer is `unknown`, re-raised, and blocks the next attempt; the outcome reference absent, malformed, ambiguous or at two revisions is refused before any reservation |

[`tests/test_guest_transport.py`](tests/test_guest_transport.py) (E-01.3.3):

| Class | What it shows |
|---|---|
| `SeamTests` (unit) | one `GuestApi` request per call; every HTTP status is an answer; a refused, malformed or doubled probe result is `NO_ANSWER`; an answer that carried the key is `SECRET_IN_ANSWER`; a failing channel is re-raised and recorded; `calls` carries the body's canonical digest, never the body |
| `CustodyTests` (contract) | the checked-in profile declares the bootstrap custody; another group, mode, owner, directory, path or login, or none, is `KEY_CUSTODY_UNDECLARED`; a channel of another login is `LOGIN_MISMATCH`, and `tools/guest.py`'s channel login is `Ssh.run`'s default; `for_instance` builds the instance's `Ssh` and `GuestApi` and refuses an unprovisioned instance |
| `ProbePairTests` | a fake ssh runs the real API probe locally against a loopback fake Agent Server: the key is read from the fake guest's file and sent on the guest side only; it is never on an ssh command line, in the script, an answer, a record or a refusal; the host process never opens the host custody copy that holds the same synthetic key (negative controls: the open spy sees a read of it, and the text check finds a planted key); an answer echoing the key is redacted in the guest and refused |
| `DispatchOverTheProbePairTests` | `dispatch` end to end over the live transport and the probe pair: `GET /server_info` and the create, each with the key on the guest side only, the attempt `confirmed` |

[`tests/test_conversation_containment.py`](tests/test_conversation_containment.py) (S-03.3 slice 1, unit), over an
in-memory `/proc` and cgroup tree shaped as the pinned image's processes are expected to be (the inner server, the
Claude Code adapter, its CLI and a shell it started, the collector's chain through the bash route):

| Class | What it shows |
|---|---|
| `Parsers` | `stat` read after the last parenthesis, `status` fields normalized, the cgroup v2 line, the argument summary that keeps no value but a path, the IPv4 and IPv6 listener tables |
| `Collection` | both vantages' snapshots; processes that end while read are counted, unreadable files recorded as errors; a child outside the namespace with a parent inside is listed; the host target's errors |
| `ContainerVerdict` | the passing view; negative controls, one fact each: the adapter missing, elsewhere or with another executable, an orphan, an entered process, a lost parent or a loop, each identity field, a cgroup, an `npx` or `npm` start, a missing or ambiguous inner server, the limits, the init; the collector's chain named but still judged |
| `HostVerdict` | the passing view; another target, the inspected caps, the cgroup's files, a member's cgroup or identity, an escaped child, a missing namespaced pid, an adapter not seen or with another executable, two host processes for one inner pid; a transient process that ended between the views is listed, not failed |
| `SetsVerdict` | no new container, outer conversation or foreign inner conversation; a child through the children route classified, not failed |
| `Shapes`, `CommandLine` | malformed snapshots, expectations, limits, sets and outputs refused, not judged; `collect` prints one result line and refuses bad arguments; the file imports only the standard library |

[`tests/test_attempt_tokens.py`](tests/test_attempt_tokens.py) (E-01.3.3), on the same fixture: attempts
are dispatched through the fake Agent Server, then delivered from an in-memory credential provider
and a fake Gitea that answers `GET /api/v1/token` as Gitea 28.3.0 does (its login and scopes).

| Class | What it shows |
|---|---|
| `StageMappingTests` (contract) | the mapping covers exactly the store's stages; each mapped credential is in the dispatcher's `custodian_of` and is delivered by it, is granted to its role, and the other stage's credential is denied to it; the held-token guard counts holds and matches the token in a path or body and the fingerprint with or without its prefix |
| `DeliveryTests` | `implement` reads only the builder's entry and asks Gitea about that token only; `review` the reviewer's; the record carries the fingerprint and no token, and after the context `credential()` refuses; while the builder's token is held, another attempt's create carries neither it nor its fingerprint, and four calls that would carry it are refused before the transport (and pass once the context has ended); a missing entry, an entry naming another account, malformed values, another bot's token, other scopes, a `401`, lost or malformed answers and a failing provider refuse; an unknown, failed or merely reserved attempt reads nothing |
| `StandingCredentialTests` | the three lifecycles: two sequential attempts of a stage use the standing credential; two concurrent ones hold it at once, the first released out of order leaves the second's credential usable and the guard holding it, a third joins meanwhile, and Gitea is only ever asked `GET /api/v1/token` (nothing revokes); a token Gitea refuses is `ROLE_TOKEN_REJECTED` on every try until `gitea_roles.rotate` (the administrative act, resuming over the refused token) replaces the entry, then delivery works with the new one; while a token is held, another attempt dispatched over the live transport sends neither it nor its fingerprint, and calls that would carry it are refused before `GuestApi` is called; an attempt takes no stage from its caller, reads only its own stage's entry and refuses another attempt's stored record |
| `LiveCustodyDriverTests` | the prepared probe's step (5) composed offline: two attempts dispatched over the live transport on a fake `GuestApi`, each delivered its mapped bot through the read-only provider, both conversations deleted, no token in what was sent; the read-only wrapper refuses and counts writes; the optional administrative-lifecycle step's verdict |
| `ReachableNamesTests` (contract) | the package's syntax trees: no mint, CLI, entry write, administrative act or revocation is reachable, no `generate-access-token`, and Gitea is asked `GET /token` only; a negative control finds a planted mint |
