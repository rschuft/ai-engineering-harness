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
| other fields | an allowlist (the template's fields: `conversation_id`, `conversation_runtime`, `workspace`, `agent_settings`, `autotitle`, `container`, `tags`; in `container`, `browser` and the two caps; for the D1 stage only, `secrets` and `secrets_encrypted`, [E-05.6](#the-d1-stages-create-secrets-e-056)). Every other field is refused; its name only picks the code (a mount, cap, runtime or path name gets that class's code). Each allowlisted field must equal the template's | `BODY_FIELD_UNKNOWN`, `BODY_NOT_TEMPLATE`, `CONVERSATION_ID_MISMATCH`, `BODY_MALFORMED` |

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
workspace (with the on-disk walk), the template's and the route allowlist's sha256, the
approved profile's bytes against the profile digest (since E-05.2), route, body and mounts. Only then, through the route-checked client and after decision 0001's
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

### The D1 stage's create template (E-05.2)

Plan leaf E-05.2 extends this admission for the D1 stage only (carved from A-01.2, which still
owns the general materialization from role profiles). An approved profile may declare one stage
create template, `provisioning.agent_server.stage_create_template` `{stage, path, sha256}` (other
keys descriptive). For that stage, the D1 stage, the pin replaces the F-04.2 fixture as the
policy's `create_template`: the policy-inputs/v2 shape is unchanged, so the policy digest, and
with it the reserved attempt identity, binds the template's sha256, and the template is reachable
only through a profile that a promoted manifest approved by sha256 (decision 0020). Every other
stage, and every profile without the declaration, keeps the admission above unchanged.

| Rule | Where | Refused as |
|---|---|---|
| the declaration names a known stage and pins a file under `profiles/<id>/` by sha256 | resolution (any stage) | `PROFILE_ADMISSION_INVALID` |
| it does not pin the profile's F-04.2 fixture (same path or same sha256) | resolution | `STAGE_TEMPLATE_DISPOSABLE` |
| the pinned template is not tagged disposable (a tag value ending `-disposable`: the F-04.2 fixture's and the S-03.3 qualification create's) | admission and `send_create` | `STAGE_TEMPLATE_DISPOSABLE` |
| the pinned template carries an ACP agent block (`agent_settings` with `agent_kind` `acp`) | admission and `send_create` | `AGENT_BLOCK_NOT_ACP` |
| the reserved policy's create template is the stage's pin | admission and `send_create` | `ADMISSION_MISMATCH` |
| the body's agent block is exactly the template's (canonical JSON), as every allowlisted field | admission and `send_create` | `BODY_NOT_TEMPLATE` (field `agent_settings`) |
| the template's bytes have the pinned sha256 | admission and `send_create` | `PROFILE_ARTIFACT_DRIFTED` |
| the approved profile the admitted create carries (`AdmittedCreate.profile_bytes`) has the reserved profile digest | `send_create` (and admission's own re-check) | `PROFILE_DRIFTED`, `PROFILE_MISSING` |

`send_create` takes no profile reader, so the admitted create carries the approved profile's
bytes beside the template and the route allowlist; the send re-checks them against the reserved
profile digest and, when they declare this attempt's stage as the D1 stage, re-runs the content
checks. An admitted create built without admission's content check is therefore refused at the
send, and nothing is sent (the independent review's R1; `ADMITTED_FORMAT` is unchanged).

**What is recognized as a disposable fixture, and what is not.** The F-04.2 fixture is
recognized by its path or its sha256 (the profile's `fixture` pin) and by its tag; the S-03.3
qualification create by its path (outside `profiles/<id>/`, so it cannot be pinned) and by its
tag, and, when filled, by its `secrets` on every stage but the D1 stage (`BODY_FIELD_UNKNOWN`);
on the D1 stage (since E-05.6, below) by the shared secrets check and its tag. A copy of either with the tag
removed, and without `secrets`, is simply another template: nothing here can tell it apart, and
whether it may be admitted is decided by the profile's approval by sha256 in a promoted manifest
(decision 0020), like any other template.

**Scope.** E-05.2 applies to the D1 stage only. Every other real stage keeps E-01.2.2's
admission, the F-04.2 fixture included, until A-01.2 (whose proof refuses that fixture for every
real stage). The checked-in `strong-windows-qemu-whpx` profile does not pin the candidate below:
it gains the pin only when S-03.3 qualifies the real template.

**The candidate.** [`profiles/strong-windows-qemu-whpx/agent-server/d1-create.json`](../../profiles/strong-windows-qemu-whpx/agent-server/d1-create.json)
is a CANDIDATE, pinned by no checked-in profile: E-01.2.2's body allowlist (no `secrets`), with
S-03.3 slice 2's ACP block (`claude-code`, exactly `["claude-agent-acp"]`, no arguments, no MCP
server, an isolated data directory), its `acp_model` the sentinel `candidate-unselected` (no
model is selected before S-03.3; never a name from memory) and the tag `e-05.2-d1-candidate`.
When S-03.3 qualifies the block, its bytes change (the model, the tag) and a profile pins its
sha256. **Not yet verified:** any live create from it. The D1 create's inference credentials
(the S-03.3 create's `secrets`), which E-01.2.2's allowlist refuses and E-05.2 does not add, are
E-05.6's (next section).

### The D1 stage's create secrets (E-05.6)

Plan leaf E-05.6 extends the admission and the create for the D1 stage only (carved from A-01.2,
which still owns every other stage's secrets from role profiles): the D1 create carries a
`secrets` block of exactly the pinned ACP registry entry's two names, each a `StaticSecret` of
exactly `kind` and `value`, with `secrets_encrypted` false: under `ANTHROPIC_API_KEY` the
attempt's inference token, bound to the reserved conversation and attempt, and under
`ANTHROPIC_BASE_URL` the profile's guest inference endpoint (decision 0015 amendment 1 item 2).

**One check, shared.** The secrets block is checked by `create_secrets.check_secrets`, the one
function S-03.3's qualification admission (`acp_qualification.check_create`) also calls: one
module, loaded under one name (`aieh_dispatch_create_secrets`), each caller passing its own
refusal type. The codes and their meanings are the same on both sides (`create_secrets.MEANINGS`);
the dispatcher adds a binding to the grant it holds. No refusal detail of the shared check, for
either caller, repeats the token, a part of it of 8 or more characters or a word shaped like a
provider key: a reported location has each such word as `<redacted>` (`create_secrets.redact`):

| Rule | Refused as |
|---|---|
| the names are exactly the registry entry's two (an `OH_` name, another provider's, a missing or renamed one is refused) | `SECRET_NAMES` |
| each is a `StaticSecret` of exactly `kind` and `value` (a `LookupSecret` makes the outer server fetch a URL the body names) | `SECRET_KIND_FORBIDDEN` |
| `secrets_encrypted` is `false` | `SECRETS_ENCRYPTED` |
| no key or value anywhere in the body has a provider key's shape | `SECRET_PROVIDER_KEY_SHAPED` |
| the token has the broker's attempt-token shape | `SECRET_NOT_ATTEMPT_TOKEN` |
| the token is the grant's (by fingerprint), and the grant is of the reserved conversation and attempt; no grant held is refused too (dispatcher only) | `SECRET_TOKEN_NOT_BOUND` |
| the token, or any part of it, appears nowhere but in its own secret: the token, its body after the prefix, any token-shaped text, or any run of 8 or more characters of its body (`create_secrets.FRAGMENT`: 48 bits of the URL-safe alphabet, so a chance match with the template's text is negligible) | `TOKEN_OUTSIDE_SECRET` |
| the endpoint is the profile's guest inference endpoint, and no other destination appears | `DESTINATION_NOT_ENDPOINT` |

**Where the values come from.** The names from the pinned registry extract
(`acp_qualification.registry_secret_names`, its sha256 checked on every load); the endpoint from
the approved profile's one `network.endpoints` entry of class `inference`
(`acp_qualification.inference_endpoint`); the token only from the broker's issue answer. The
grant's family is the registry entry's (`acp_qualification.ACP_FAMILY`, `anthropic-messages`),
its one model the pinned template's `acp_model` (in the broker's model grammar), and its lifetime
is declared beside the stage template's pin: `stage_create_template.inference_grant` exactly
`{ttl_s}`, a positive integer, bound by the profile digest and required at resolution
(`PROFILE_ADMISSION_INVALID`); the broker bounds it at issuance (`max_ttl_s`). The grant carries
no request or token budget (retired by S-03.6, decision 0015 amendment 2): a declaration that still
names `requests` or `tokens` is refused at resolution, `PROFILE_ADMISSION_INVALID` with the retired
keys named, never ignored. Anything else that cannot be admitted (the registry extract drifted, no
single inference endpoint, another ACP server, a model outside the grammar) is
`INFERENCE_INPUTS_INVALID` at admission, before any token exists.

**The grant's model list: the authorization-bound selection (S-03.3).** With an API key, Claude Code sends its
background calls to its own default small model, which the pinned OpenHands ACP settings cannot name (a third
secret name would change E-05.6's proof). So the grant's list is not the template's model alone whenever the broker
serves the ACP family under the Owner's provider envelope: immediately before the issue (and before its journal),
the dispatcher reads the broker's control status, and when it holds a provider-envelope authorization whose
selection names the ACP family (`authorization.selection.models["anthropic-messages"]`, the member the broker's
`Authorization.describe` writes), the grant is issued with exactly that selection's models, in its order: the
primary and the secondary the engineering manager selected. The template's `acp_model` must be among them, else
`INFERENCE_MODEL_NOT_SELECTED` and nothing is issued. When the broker holds no such authorization (a loopback
family, or an authorization that binds other families only), the list stays the template's one model. A status
that is not answered, or whose authorization member cannot be read (no selection, a list that is empty, has a
duplicate or a name outside the broker's grammar), is `INFERENCE_GRANT_UNAVAILABLE`. The list comes from the
authorization-bound selection, not from the profile digest: the selection is the engineering manager's
model-selection record on the governing envelope receipt (decision 0018 point 3), which changes within the envelope
without a new profile, and which the broker already holds and enforces; the profile and the stage template carry
no model list, and the grant declaration (`inference_grant`, `{ttl_s}`) gains no field. The broker's own issue
check (each model allowlisted and selected) is unchanged and remains the enforcement.

**The pinned template carries no secrets** (a template that does is `BODY_FIELD_UNKNOWN`):
`admit` admits every input but the secrets, and `admit_secrets(admitted, resolved=, workspaces=,
grant=)` adds the block, the token's value as the slot `{attempt_token}`. The grant
(`InferenceGrant`) holds the token in memory; the checks before the transport, in `admit_secrets`
and again in `send_create`, put it in the slot's place in a body built in memory, run the shared
check with the binding on that exact body, and `send_create` sends it. A D1 create without its
block or its grant is refused at the send. Every other stage still refuses `secrets` and
`secrets_encrypted` (`BODY_FIELD_UNKNOWN`), and a grant on its create (`ADMISSION_MISMATCH`).

**Order and revocation.** In `dispatch(..., inference=InferenceAccess)`: resolve, reserve,
`admit` (every other input), then, and only then, the token is requested from the broker's
control listener (`InferenceAccess.from_component(raw, revoker=)`: `inference_control.
ControlClient` on the port of `dispatcher_ports`; the revoker is checked with the broker's own
grammar at construction, `INFERENCE_REVOKER_INVALID`) for the reserved conversation and attempt;
then `admit_secrets`, the workspace, `dispatched` (its detail carries the grant by fingerprint)
and `send_create`. No control listener, or a broker that refuses the issue, is
`INFERENCE_GRANT_UNAVAILABLE` (the broker's code in its context).

**The grant journal.** The issue is journaled in the integration store before it is sent:
`dispatch/attempt/<attempt id>/inference-grant` (`inference-grant-journal/v1`: the operation key,
attempt, conversation, family and revoker, never the token) is reserved and dispatched before the
call, then confirmed with the grant's record (by fingerprint), or failed (`issued` false) when the
broker refused the issue. When the answer is lost (a timeout, an unreachable listener after the
request was sent) or is not a valid grant of this attempt, the outcome is unknown: the grant is
revoked by the attempt's conversation and attempt (the broker's selector beside the fingerprint, one
grant per attempt). An invalid answer's fingerprint is revoked too, and journaled, only when that
answer named this conversation and attempt: another attempt's grant is never revoked on a wrong
answer, and the attempt's selector decides the outcome. When the broker holds no grant of the
attempt it tombstones the attempt, so that a late issue (one still in flight when the client gave
up) is refused, never registered: the outcome is recorded as `no grant; attempt tombstoned`, and
`end_attempt` need not call again. The journal is then settled (confirmed when a grant was found,
failed when none was, unsettled while the revocation itself fails).

**Revocation, always.** Once issued (or once its outcome is unknown), the grant is revoked (trigger
`attempt end`: a refused attempt ends) on any refusal or failure, whatever is raised:
`DispatchRefused` (the secrets admission, the workspace, a `send_create` refusal, a 4xx), a
transport failure, an uncertain outcome, a failing `dispatched` transition, and any other
`BaseException` (KeyboardInterrupt and SystemExit included: best effort, then re-raised). It is
revoked before the attempt's outcome is recorded, and its outcome is in that record and on the raised
exception (its context, or a note). Every revocation is journaled as the receipt
`dispatch/attempt/<attempt id>/inference-revocation/<n>` (reserved and dispatched before the call,
then confirmed or failed with the record); the call is made even when the store cannot be written.
A failed revocation is recorded and surfaced, never swallowed, and never stops the attempt's
outcome from being recorded.

**The attempt's end.** A confirmed attempt keeps its grant until its end. `end_attempt(store,
operation_key, inference=, actor=)` revokes the attempt's issued, not yet revoked grant, whatever the
attempt's state (confirmed, failed, unknown, or reserved or dispatched as an interrupted dispatcher
left it): **ending an attempt still in flight revokes its grant** (fail closed), and that dispatch then
sends no create: `send_create`, given the store, refuses `GRANT_REVOKED` before each transport call
when the attempt has a revocation receipt (the revocation stands). It revokes by the
fingerprint the journal holds, else by the attempt; it resumes and settles any unsettled
revocation receipt of the attempt whatever its revoker, and settles an unsettled journal. A failed
revocation is `INFERENCE_REVOCATION_FAILED` with the record; a later call tries again under the
next receipt. When the grant is already revoked and journaled, its record is returned without a
call; an attempt with no journal (every other stage, a D1 attempt refused before the issue) or
whose issue the broker refused has nothing to end: None (`ATTEMPT_NOT_ENDABLE` is gone). The
broker writes its own revocation receipt; the grant's state shows it.

**The receipts change no attempt's outcome.** Restore-epoch reconciliation and its closure see the
same attempts with or without the journal and the revocation receipts, and none carries a `workRef`
or `outcomeRef`. A receipt or journal left `dispatched` by an interrupted dispatcher is reconciled as
itself (the oracle is asked about it, never the attempt) and holds the restore epoch open until
then, as the broker's own receipts do: a grant or a revocation whose outcome is unknown must be
settled; `end_attempt` still revokes such a grant by its attempt.

**Fingerprints, never the token.** The admitted body's token secret must be the slot: a token
value there, even the held grant's own, is `SECRET_NOT_FROM_GRANT` at the send.
`AdmittedCreate.to_json()` carries the slot and `inference_grant` (`inference-grant/v2`: the
token's fingerprint, conversation, attempt, family, models, expiry; `v1` also carried the retired
budget), and redacts anything
token- or provider-key-shaped in the body besides; the `dispatched`, `failed` and `unknown`
details, `DispatchResult`, the journal, the revocation records and every refusal carry the
fingerprint only. While the token is held, a refusal's detail and context are rebuilt, with no
`__context__` or `__cause__` to the original: a string that, without its characters outside the
token's alphabet, still holds a part of the token of 8 or more characters is withheld whole; in any
other, every word holding a token, such a part, or a provider key's shape is redacted
(`create_secrets.redact`). The live transport sends a body that carries `secrets` sealed
(`guest_transport.GuestTransport`: on ssh's standard input, never in an argument, so neither a
command line nor a `TimeoutExpired` shows it). The dispatcher holds no provider credential and
reads none: importing it loads no inference or credential module, and the D1 stage's own modules
(`acp_qualification`, `inference_control`) are loaded on first use.

**Not yet verified:** any live create with secrets, any live broker, guest or model call; the
checked-in profile pins no stage template yet, so no grant lifetime is declared there.

### The native profile's token (E-05.9)

Plan leaf E-05.9 adds the D1 stage on the **native execution profile** (decision 0023): the
unmodified Claude Code authenticates with the Owner's own long-lived token (`claude setup-token`),
and no broker is involved. E-05.6's brokered profile stays as built.

**The declaration.** The stage template's pin declares `execution_profile`: `brokered` when absent
(E-05.6, with its `inference_grant`), or `native`, which takes no `inference_grant` (declaring
both, or another value, is `PROFILE_ADMISSION_INVALID` at resolution). The profile declares its
tunnel endpoint as one `network.endpoints` entry of class `provider-tunnel` with `guest_address`
`172.17.0.1` and a `guest_port` (`create_secrets.tunnel_endpoint`; otherwise
`NATIVE_TUNNEL_UNDECLARED`). E-05.10 fills it: `strong-windows-qemu-whpx` declares the entry
(class `provider-tunnel` in `profiles/properties.json` and P7), `172.17.0.1:8090` on the guest
side (the inference endpoint's listener, so `HTTPS_PROXY` is `http://172.17.0.1:8090`) and the
tunnel's `host_port` on the host side
([provider tunnel](../inference/README.md#the-provider-tunnel-e-0510)); the other profiles defer it.

**The token's custody.** One credential-provider entry (F-06.3), `AIEH Claude Code native token`,
user `claude-code` ([`native_token.py`](native_token.py)), written only by the Owner's entry
command ([`../credentials/native_token_entry.py`](../credentials/native_token_entry.py), `task
credentials:native-token-enter`, the Owner's act OA-31 (e)): an interactive console only, the token
read once at a hidden prompt (never argv, the environment, a file, `config.yml` or the host Claude
configuration), a value without the token's shape refused by rule name, the one entry written and
read back, a fingerprint-only `aieh-credential-act/1` receipt. This package only reads a provider.
The shape (`native_token.token_rule`): `sk-ant-`, a lower-case label, `-`, then only
`[A-Za-z0-9_-]`, 40 to 512 characters; the labels of the provider's other credentials (an API key
`api...`, `admin...`, a session key `sid...`, session tokens `cc` and `si`) are refused. Neither the
provider's documentation nor the pinned CLI states the setup-token value's exact shape; this is the
grammar both state for the provider's credentials (the sources are in `native_token.py`).

**The read.** `dispatch(..., native_credentials=<provider>)`: after `admit` has admitted every other
input (the tunnel endpoint and the template's agent block included), and only then,
`native_token.read` asks the provider for that one entry, once (`NATIVE_TOKEN_MISSING`,
`NATIVE_TOKEN_UNAVAILABLE`, `NATIVE_TOKEN_NOT_SHAPED`, and `NATIVE_ENTRY_USER_MISMATCH` when the
entry's user is not the entry command's `claude-code`; no provider given is
`NATIVE_TOKEN_UNAVAILABLE`); no other entry, no environment variable and no host Claude
configuration is read. The token is held in memory (`NativeToken`: its `repr` and `record()` carry
the fingerprint only, it does not pickle) until the transport call; the admitted body holds
`{native_token}` in its place (a token value there is `NATIVE_SECRET_NOT_FROM_ENTRY` at the send).
The dispatched transition, a refusal's context, an unknown outcome's detail, the admitted-create
record and the result carry `tokenFingerprint` only.

**One check, shared.** `create_secrets.check_native_secrets` is the one check of the native create,
the dispatcher's at `admit_secrets` and again in `send_create` before the transport, and E-05.11's
qualification admission's (which calls the same function with its own refusal type, as S-03.3's
calls `check_secrets`). Its codes and meanings are `create_secrets.NATIVE_MEANINGS`:

| Rule | Refused as |
|---|---|
| the names are not a mix of the native set and the brokered one (`ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`) | `NATIVE_SECRETS_MIXED` |
| the names are exactly `CLAUDE_CODE_OAUTH_TOKEN`, `HTTPS_PROXY`, `CLAUDE_CODE_PROXY_RESOLVES_HOSTS` and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` (`ANTHROPIC_AUTH_TOKEN`, an `OH_` name, `CLAUDE_CONFIG_DIR` or a missing one is refused) | `NATIVE_SECRET_NAMES` |
| each is a `StaticSecret` of exactly `kind` and `value` (a `LookupSecret` included) | `SECRET_KIND_FORBIDDEN` |
| `secrets_encrypted` is `false` | `SECRETS_ENCRYPTED` |
| the token has the native shape | `NATIVE_TOKEN_NOT_SHAPED` |
| the token is the one read from the entry (by fingerprint; dispatcher only) | `NATIVE_TOKEN_NOT_HELD` |
| the token, its body after `sk-ant-<label>-`, any run of 8 or more of its body's characters, or an encoded copy (the outbound search's own needles, `inference_key_search.needles`: hexadecimal, base64 and base64url at three alignments, UTF-16, of the token and of its body) appears nowhere else | `NATIVE_TOKEN_OUTSIDE_SECRET` |
| no second authentication method anywhere else: an `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` or `ANTHROPIC_AUTH_TOKEN` name, or another provider credential's value | `NATIVE_SECOND_AUTH_METHOD` |
| `HTTPS_PROXY` is the profile's tunnel endpoint, and no other destination appears | `NATIVE_PROXY_NOT_TUNNEL` |
| each switch is its declared spelling, `tRuE` (never `1` or `true`) | `NATIVE_SWITCH_NOT_DECLARED` |
| no MCP configuration (`mcp_config` empty, no other `mcp` key) | `NATIVE_MCP_FORBIDDEN` |
| the agent block is `acp`, `claude-code`, exactly `["claude-agent-acp"]`, no `acp_args` | `NATIVE_ACP_COMMAND_NOT_PINNED` |
| the per-conversation configuration directory is kept: `acp_isolate_data_dir` true, nothing naming `CLAUDE_CONFIG_DIR` | `NATIVE_CONFIG_DIR_RELOCATED` |
| `agent_settings.agent_context` is absent or null (its `secrets` are seeded into the conversation's secret registry and injected into the ACP process's environment; its `skills` are written under the persistence directory) | `NATIVE_AGENT_CONTEXT_FORBIDDEN` |
| `agent_settings.acp_file_secrets` is absent or empty (a spec writes a secret's value to a file under `<persistence>/acp/<subdir>` and points an environment variable at it) | `NATIVE_FILE_SECRETS_FORBIDDEN` |
| every other `agent_settings` member is one of the run shape's at its admitted value: `agent_kind` `acp`, `acp_server` `claude-code`, `acp_command`, `acp_args` `[]`, `acp_model` one model name (required), `acp_session_mode` null, `acp_isolate_data_dir` true, `mcp_config` `{}` (the timeouts, `verification`, `schema_version` and any unknown member refused) | `NATIVE_AGENT_SETTING_FORBIDDEN` |
| the create's top-level fields are the run shape's: the template's fields, `secrets` and `secrets_encrypted` (for E-05.11's callers; the D1 stage's own allowlist refuses first) | `NATIVE_BODY_FIELD_FORBIDDEN` |

The switches' spelling: at the pinned CLI (`claude` 2.1.220, read from the release package
`@anthropic-ai/claude-code-linux-x64` 2.1.220), `CLAUDE_CODE_PROXY_RESOLVES_HOSTS` is read through
the CLI's environment parser's bool (`1`, `true`, `yes` or `on`, lower-cased and trimmed) and
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` as any non-empty value (its declared accessor is the same
bool); `tRuE` is accepted by every reader of both, is neither `1` nor `true` (the SDK masks every
secret value in agent output by exact, case-sensitive substring: `str.replace` and an unflagged
`re` pattern at the pin, `conversation/secret_registry.py` lines 321 and 339-341, so `tRuE` masks only `tRuE`), and does not occur in the CLI's own code and text. The
closed-world rows follow the pinned SDK 1.60.1 (`settings/model.py` `ACPAgentSettings.create_agent`;
`agent/acp_agent.py` `_start_acp_server`, `_materialize_skills`, `_materialise_file_secrets`): the SDK's
default `acp_file_secrets` (when absent) name reserved secrets the four admitted names never are, so
none materialises. The native path loads no broker module: its redaction (`redact_native`,
`native_location`), its fragments and its encoded forms are broker-free. The
agent-block half (`check_native_agent`) also runs on the pinned template at `admit`, before any
token is read. A native template that is the S-03.3 qualification fixture is still
`STAGE_TEMPLATE_DISPOSABLE`; every other stage still refuses `secrets` (`BODY_FIELD_UNKNOWN`) and
never reads the token; a broker grant on the native stage, or the native token on the brokered one,
is `ADMISSION_MISMATCH`.

**The outbound search** ([`native_token_search.py`](native_token_search.py)): S-03.2's key search
(`inference_key_search.Search`, its forms, views, surfaces and positive controls; reused with the
token's public prefix), plus the result bundle: a git bundle's pack objects inflated and their
deltas applied (standard library), with its own positive control (the token planted whole, split
across a delta's base and its inserted data, and behind a ref-delta, none in the raw bytes). It holds
the token in memory, reports counts and the fingerprint (a report that would hold the token is
withheld), and `not-found` covers the bytes searched only. Its command line reads the token from the
one entry and names the Owner's act (`--owner-act`); its runs are E-05.11's and E-05.5's.

**Not yet verified:** any real token, entry, console or Credential Manager; any create carrying the
token, the CLI's reading of the switches, the SDK's masking and every other live behaviour
(E-05.11); the tunnel and its endpoint (E-05.10).

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
in a guest. `tools/guest.py acp-qualification` (S-03.3 slice 5, prepared, not run) sends it to the qualification
conversation's container and judges its output. The guest-root vantage (the slice 5 record's finding F-6) comes
from the guest's root facts reporter (S-03.3 slice 6): on request it writes the snapshot `collect host` prints
for each running conversation container, from verbatim copies of this file's readers in the seed, and the
driver reads it as `agent` (`tools/guest.py` `host_snapshot_from_report`); a guest seeded before slice 6, a
truncated list or a missing field is UNKNOWN, never PASS
([`evidence/S-03.3-slice6-root-vantage.md`](../../evidence/S-03.3-slice6-root-vantage.md)).

| Vantage | Command | What it lists |
|---|---|---|
| Inside the conversation container, as its user (through the inner server's bash route, as the job probe runs) | `collect container` | Every process of the container's PID namespace: pid, parent, executable, `argv0`'s last segment, the first absolute path among the next three arguments (the script an interpreter runs) and the count; `Uid`, `Gid`, `Groups`, the five capability sets, `NoNewPrivs`, `Seccomp`; the cgroup v2 path. The listening TCP sockets with their owning pids (from `/proc/<pid>/fd`); the other TCP sockets (slice 5: local and remote address and port, the state's kernel name, the owning pids; no inode, no payload) and any table that could not be read. The container's `memory.max`, `cpu.max` and `pids.max` |
| The guest root | `collect host --pid <State.Pid>`, or the same snapshot in the root facts reporter's `containment` section (slice 6) | Every host process in the PID namespace of the container's init (`docker container inspect`'s `State.Pid`), with the same fields and its namespaced pids (`NSpid`); any process outside that namespace whose parent is inside; the limits of the init's cgroup |

The output is one line, `AIEH-CONTAINMENT-JSON ` and the snapshot (`ai-engineering-harness/containment/snapshot/v1`).
No other argument value, no environment, file content or socket payload is read. A process that ends while it is
read is counted as `vanished`; a file that cannot be read is recorded as an error, never as a value.

| Verdict | Fails when |
|---|---|
| `container_verdict(snapshot, expected=)` | PID 1 is missing or has a parent; a process other than PID 1 has parent 0 (entered from outside the namespace); not exactly one process owns the inner server's listener (port 8000); a process lacks the expected user (all four `Uid` and `Gid` values), PID 1's `Groups`, empty capability sets, `NoNewPrivs` 1 or `Seccomp` 2, or its status is unreadable; a process is outside PID 1's cgroup; a process does not descend from the inner server, or its chain is lost (the inner server's own ancestors, and the collector's own chain, which is still judged for identity and cgroup, excepted); an `npx` or `npm` process exists; the container's limits are not the admitted caps; with a provider expected, its adapter is not a direct child of the inner server (`argv0` `node`, the script `/acp-node/bin/claude-agent-acp` or `codex-acp`) or its executable is not `/acp-node/bin/node` |
| `host_verdict(snapshot, inspect=, container=, expected=)` | the snapshot is not of the inspected init; `HostConfig` `Memory`, `NanoCpus` or `PidsLimit`, or the cgroup's files, are not the admitted caps; a member is outside the init's cgroup, lacks the identity or has no namespaced pid; a process outside the namespace has a parent inside; with a provider expected, an adapter is not seen from the guest root with the same executable (a transient provider process that ended between the two views is listed as `provider_vanished`, not failed) |
| `network_verdict(snapshot, endpoint=)` (slice 5) | a connection whose peer answered (every state but `SYN_SENT` and `CLOSE`) goes anywhere but the guest inference endpoint, the container's loopback or inbound to the inner server's port (`other_reached`: the qualification run's stop condition); a `CLOSE` or unknown state, or a TCP table that could not be read (`tcp6` absent excepted), fails without a stop. A connect still in `SYN_SENT` is listed as `attempted` (refused or unanswered; the guards' counters judge it) |
| `sets_verdict(before, after, conversation_id=)` | a container or an **outer**-server conversation appeared during the turn; an **inner**-server conversation appeared whose `parent_conversation_id` is not the observed conversation. A new inner conversation whose parent is the observed one is classified as started through the children route (`delegation.children_route`), the route `start_child_conversation` uses, so the record distinguishes it from the provider's own processes (`provider_tree`) |

`expected` holds the profile's job confinement (`uid`, `gid`, `capabilities`, `no_new_privs`, `seccomp`), the
admitted caps (`expected_limits(memory, cpus, pids_limit)`: Docker's `--memory`, `--cpus` and `--pids-limit` as
cgroup v2 values and as `HostConfig` values) and `provider` (`claude-code`, `codex`, or `None`). The adapter
identities come from the pinned image's files (the image adapter check), not from a running provider; a provider
whose real process shape differs is reported as not observed, with the inner server's children listed, never
passed. Every verdict fails closed, and a snapshot, inspection or set that is not of its shape raises
`ContainmentError` (`SNAPSHOT_INVALID`, `EXPECTED_INVALID`, `INSPECT_INVALID`, `SETS_INVALID`, `LIMITS_INVALID`,
`NO_SNAPSHOT`, `MODE_INVALID`, `TARGET_INVALID`) instead of being judged.

## The ACP qualification create (S-03.3, slice 2)

Plan leaf S-03.3 runs the first ACP coding provider (Claude Code) through the inference broker with "a disposable
pinned create fixture" (its proof). That create carries the ACP `agent_settings` block and the create's `secrets`,
which no dispatch stage admits: a stage's body must be its profile's pinned template (`check_create_body`, whose
allowlist has no `secrets`), and a stage reads pinned artifacts only under `profiles/<id>/`
(`read_profile_artifact`). So the fixture lives here, beside its own admission, and the two never meet (the
Overseer's ruling on the [slice plan](../../evidence/S-03.3-slice-plan.md)'s D-3).
[`acp_qualification.py`](acp_qualification.py) builds and checks it; nothing sends it yet (the live driver is slice
5), and nothing here has run in a guest: **not yet verified** against a live Agent Server.

| File | What it is |
|---|---|
| [`qualification/acp-claude-code-create.json`](qualification/acp-claude-code-create.json) | The fixture (`ai-engineering-harness/dispatch/acp-qualification-create/v1`), pinned by `FIXTURE_SHA256`: the Docker runtime, `/workspace`, `agent_settings` `{agent_kind: acp, acp_server: claude-code, acp_command: ["claude-agent-acp"], acp_args: [], acp_model, acp_session_mode: null, acp_isolate_data_dir: true, mcp_config: {}}` (no `tools`, `agent_context` or `acp_file_secrets`), `secrets` `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` as `StaticSecret`s, `secrets_encrypted` false, no browser, the tag `s-03.3-disposable`; four placeholders: the reserved conversation id, the approved model, the attempt token and the guest inference endpoint |
| [`qualification/acp-registry-claude-code-1.60.1.json`](qualification/acp-registry-claude-code-1.60.1.json) | The facts of the pinned OpenHands registry the fixture relies on (the key and base-URL variable names, the binary name, the session mode, the data-dir variable, `env_conflicts`, the secret kinds, and the environment facts behind finding F-3), each with its source line in the locked wheels, whose sha256 it names; pinned by `REGISTRY_SHA256`. The fixture's command and secret names are checked against it on every load |

`build_create(conversation_id=, attempt_token=, acp_model=, approved_models=, profile=)` fills the fixture and
checks it; `check_create(body, conversation_id=, approved_models=, profile=)` admits exactly the fixture with its
four values and refuses everything else with a `QualificationRefused` code
(`ai-engineering-harness/dispatch/acp-qualification-refusal/v1`):

| Code | Refused |
|---|---|
| `FIXTURE_DRIFTED`, `FIXTURE_INVALID` | the fixture or the extract is not its pinned bytes, not its strict JSON shape, or they disagree (a command or secret name that is not the registry's) |
| `ENDPOINT_UNDECLARED` | the profile declares no single `network.endpoints` entry of class `inference` with an IPv4 literal and a port |
| `MODEL_NOT_APPROVED` | `acp_model` is not one name of the family's configured allowlist (the broker's model grammar, no wildcard, no duplicate; an empty list approves nothing) |
| `CONVERSATION_ID_MISMATCH` | not the reserved conversation id |
| `BODY_MALFORMED`, `BODY_FIELD_UNKNOWN`, `BODY_NOT_FIXTURE` | not an object; a field outside the fixture; any other field (runtime, workspace, container, tags, session mode, data-dir isolation, ...) not the fixture's |
| `AGENT_PROFILE_FORBIDDEN` | `agent_profile_id` or another profile reference: a profile resolution brings the server's stored settings and MCP servers |
| `TOOLS_FORBIDDEN` | tools, skills, plugins, hooks, client tools, agent definitions, launch additions or an `agent_context` |
| `MCP_FORBIDDEN` | any MCP server: `mcp_config` other than `{}`, or an MCP field |
| `ACP_SERVER_NOT_PINNED` | `agent_kind` other than `acp`, or `acp_server` other than `claude-code` (`custom` included) |
| `ACP_COMMAND_NOT_PINNED` | `acp_command` other than exactly `["claude-agent-acp"]`: empty or absent (the registry's `npx` form, which the SDK keeps when `shutil.which` misses the wrapper), the `npx` command, a path, a shell or `env` prefix, another adapter; any `acp_args` |
| `SECRET_NAMES`, `SECRET_KIND_FORBIDDEN`, `SECRETS_ENCRYPTED` | secrets other than exactly the registry's two names (no `OH_*` name, no OAuth token); a secret that is not `{kind: StaticSecret, value: <string>}` (a `LookupSecret` makes the outer server fetch a URL the body names, finding F-2); `secrets_encrypted` not `false` |
| `SECRET_PROVIDER_KEY_SHAPED` | a provider-key-shaped value anywhere (`sk-ant-`, `sk-proj-`, a long `sk-` run) |
| `SECRET_NOT_ATTEMPT_TOKEN`, `TOKEN_OUTSIDE_SECRET` | `ANTHROPIC_API_KEY` is not one broker-issued attempt token (`aieh-inf-` and 43 URL-safe characters); that token, its body or any other token anywhere else in the create |
| `DESTINATION_NOT_ENDPOINT` | `ANTHROPIC_BASE_URL` other than the profile's guest inference endpoint (`http://172.17.0.1:8090` for `strong-windows-qemu-whpx`), or any other URL anywhere in the create |

The attempt token in `ANTHROPIC_API_KEY` is the broker-issued per-attempt token, never a provider key
(`cred-inference-attempt-token`). **Finding F-3, disclosed, not changed:** at the pinned OpenHands the adapter's
environment is the inner server's own (`OH_SECRET_KEY`, `OH_SESSION_API_KEYS_0` included) plus the secret registry,
and no field of the create can remove or blank a variable of it: the registry has no environment field
(`env_conflicts` is per provider and, for Claude Code, strips only the Anthropic variables when an OAuth token is
present), `ACPAgentSettings` has no `acp_env`, and a blank `StaticSecret` validates to none and is not exported. The
exposure class is the one S-01.3.1 recorded through `/proc/1/environ`
([slice 2 record](../../evidence/S-03.3-slice2-qualification-create.md)).

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

**Accepted design revisions.** The manifest's `designs` entries are the approval source for
"accepted OpenSpec revision": one accepted commit per change and repository, replaced when a
changed design is accepted again. Since P-04.3 each entry rests on a recorded design acceptance
of that change at that commit (`accept-design`, by the Owner or delegated by decision 0018 point
3.2), which the promotion decision binds; nothing is added to the change folder. A later
acceptance takes effect when a manifest naming it is promoted.

### Custody (decision 0009, points 1, 2, 7 and 11; decision 0010)

- The live manifest is an authorization record under `persistent/`: the `state` category of
  the managed data root, `<state>/dispatch/approved-inputs.json`. `manifest_path()` computes
  it through `aieh_paths` and creates nothing.
- `load_manifest` refuses a relative path or one with `.` or `..` parts, and a path inside or
  containing the checkout (before reading it, and again after resolving links). These path
  refusals stay its first (the dispatch-input commands rely on them). The request never names a
  manifest. "Inside or containing" is one comparison, `aieh_paths.inside_or_around` (shared with
  the managed root's guard and the S-03.3 proposal's `--out`), made twice: on the path as given
  and on its realpath (`MANIFEST_INSIDE_CHECKOUT`; the input recorder's `CANDIDATE_INSIDE_CHECKOUT`
  runs the same rules). The lexical comparison covers these Windows forms: a leading `\\?\` or
  `\\.\` (and `\\?\UNC\` as `\\`), an alternate data stream suffix (`:stream`), the trailing
  spaces and dots Windows ignores in a component, `/` and case. A link or junction, a volume-GUID
  path and a GLOBALROOT path are caught by the realpath comparison, not by the lexical one.
- **Promotion through a recorded decision (plan leaf P-04.3).** The live manifest has one
  writer, the dispatch-input commands of the authorization recorder
  ([`integrations/owner/input_recorder.py`](../owner/README.md#the-dispatch-input-commands-plan-leaf-p-043)):
  a promotion decided by the Owner, or by the product manager under decision 0018 point 3.3, is a
  write-ahead receipt in the integration store at the manifest's `version`, bound to the sha256 of
  its bytes and to the design acceptance of each `designs` entry. `load_manifest(path,
  decisions=...)` asks a decision verifier (`input_decisions.verifier(store)` over the managed
  store, `<state>/integration/integration.sqlite`) after the path, read and schema checks, and
  refuses (`MANIFEST_NOT_PROMOTED` without one; the verifier's codes below otherwise) unless the
  store holds a confirmed promotion at this version with this digest, no later promotion is
  confirmed, and each design entry has the confirmed acceptance the promotion bound. The loaded
  manifest carries the approval view (`approval`); `approving_record(section, key)` names, for
  each entry, the record that approved it: a design entry its design acceptance, every other
  entry the promotion. `parse_manifest` stays for checking only: `resolve`, `admit` and
  `dispatch` accept only an `ApprovedInputs` object that `load_manifest` returned in this process
  (held by identity: a `dataclasses.replace`, a copy or a hand-built one is refused) and check
  its approval view again, refusing anything else (`MANIFEST_NOT_PROMOTED`) before anything is
  read or reserved. That guard is against convenience and accident (a driver that parses the
  file itself); code of the same account in the same process can forge anything, and is outside
  the threat model (decision 0010 point 1). Nor does `load_manifest` know which verifier it was
  given: **the live driver (E-01.3.2) must pass `input_decisions.verifier(<the managed integration
  store>)`** (`<state>/integration/integration.sqlite`), load the manifest for each dispatch, and
  never cache an `ApprovedInputs` across dispatches. Catalog pins still come from A-01.1's
  protected promotion, through such a decision.
- Placement is not a security boundary (decision 0010). Agents are kept from the managed
  root by the execution guest, the mount policy, bundle exchange and the role-token matrix
  (decision 0009 point 11). During bootstrap, host-side processes of the Owner's account can
  read and change both the file and the store (`fd-bootstrap-shared-identity`; decision 0010
  point 1): a manifest changed without a recorded decision is **detected and refused at load**,
  not prevented from being written, unless the store itself is also written by hand to imitate
  the recorder, which decision 0010 point 1 places outside the threat model (the verifier's
  series checks catch only a careless imitation, and a gap above the manifest's version is not
  seen without listing the store). No decision file beside the manifest is read.

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
| `MANIFEST_NOT_PROMOTED` | no decision source was given, the store holds no promotion receipt at this version, or (`resolve`, `admit`, `approving_record`) the manifest was not approved by `load_manifest` |
| `DECISION_RECORD_INVALID` | the receipt's decision is not a well-formed record of its format and kind or does not bind what the receipt says; or the verifier raised or answered anything but a well-formed view of this manifest |
| `MANIFEST_PROMOTION_UNCONFIRMED`, `MANIFEST_DIGEST_MISMATCH` | the promotion receipt exists but is not confirmed (`manifest resolve`); the file's sha256 is not the decided one |
| `DECISION_REPLAYED`, `DESIGN_ACCEPTANCE_MISSING` | a later promotion is confirmed; a design entry has no binding, or no confirmed design-acceptance receipt equal to it |
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
| `STAGE_TEMPLATE_DISPOSABLE`, `AGENT_BLOCK_NOT_ACP` | the D1 stage's create template (E-05.2) is the profile's F-04.2 fixture or tagged disposable; it carries no ACP agent block |

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
| `ManifestCustodyTests` | the checkout (inside or containing) is refused before reading, in every Windows form of its path (`\\?\`, `\\.\`, trailing spaces and dots, case, `/`), and `inside_or_around` itself; path shapes; a manifest outside the checkout is refused without a decision source and loads with one; `manifest_path` is `<state>/dispatch/approved-inputs.json` and creates nothing |
| `CliTests` | `check-manifest` exit codes and report; `manifest-path` with `AIEH_DATA_ROOT` in a throwaway directory creates nothing |

The resolution and admission tests load their fixture manifests through `load_manifest` with a
**test-only** decision verifier (`fixture_verifier`, which approves any manifest with synthetic
records); nothing of P-04.3's proof rests on it.

The design repository is built by the planning fixture (`two_task_fixture.build_repo`, a
reproducible commit), and Backlog.md is its own recorded readiness output
(`integrations/planning/tests/fixtures/readiness/`), so the Work and design checks run
against real Backlog.md JSON and real git objects.

[`tests/test_work_source_operation.py`](tests/test_work_source_operation.py) (F-09.4), on the
same fixture: one `PlanningWorkSource.read` is one adapter operation, so Backlog.md's `task
list` is run once (the read and the readiness evaluation both ask for it), every pointer is
resolved through one git batch reader, and the reader ends with the read, also when it raises.

[`tests/test_manifest_promotion.py`](tests/test_manifest_promotion.py) (P-04.3): **the proof**
that a manifest loads only through a recorded decision. Every row goes through `load_manifest`
with the real decision verifier over a throwaway integration store, the manifests promoted by the
real dispatch-input commands (the Owner's challenge and a synthetic statement, or the product
manager's delegation on a fixture harness repository holding a decision 0018 and a log; fixtures
from `integrations/owner/tests/input_fixture.py`):

| Class | What it shows |
|---|---|
| `EntryWithoutARecordedDecision` | a manifest written by hand with an empty store, an entry added and the version raised by hand, and no decision source: `MANIFEST_NOT_PROMOTED` |
| `DigestOtherThanTheDecidedOne` | one byte of whitespace, a profile's `sha256`, a pin's `manifest_sha256`: `MANIFEST_DIGEST_MISMATCH` |
| `DesignEntryWithoutAnAcceptance` | the recorder refuses a candidate whose design has no acceptance (no receipt, no live file); a promotion receipt written by hand for such a design: `DESIGN_ACCEPTANCE_MISSING` |
| `ReplayedDecision` | version 1 put back after version 2: `DECISION_REPLAYED`; `record` twice on one challenge: `CHALLENGE_CONSUMED`, one receipt; a candidate naming a superseded design revision: the recorder's `DECISION_REPLAYED` |
| `PromotedManifestLoads` | Owner and delegated promotions load with their version and sha256; every entry's `approving_record` resolves to a confirmed receipt that covers it (a design its acceptance, every other entry the promotion), with its authority |
| `NeverAnOwnerDecision` | an agent-attributed statement of either kind is `STATEMENT_MODEL_AUTHORED`; a delegated record fails the Owner record's check |
| `EnforcementCannotBeSkipped` | `resolve`, `admit` and `dispatch` given `parse_manifest`'s output, a view of another digest, a well-formed view on a parsed manifest, or a replace, copy or hand-built equal of a loaded one, refuse `MANIFEST_NOT_PROMOTED` with nothing read and nothing reserved |
| `LoadOrder` | the path refusals come first and ask no verifier; a verifier that raises or answers anything but a view of this manifest approves nothing (`DECISION_RECORD_INVALID`); the verifier's own refusals pass through |

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

[`tests/test_d1_stage_admission.py`](tests/test_d1_stage_admission.py) (E-05.2), on the E-01.2.2
fixture with one more synthetic profile that pins the candidate for `implement`; **the proof**,
clause by clause, every refusal with the counting transport called zero times:

| Class | What it shows |
|---|---|
| `TheCandidate` (unit) | the candidate's block is S-03.3 slice 2's but the model (a sentinel); it is an allowlisted body without `secrets`, tagged candidate, otherwise the F-04.2 fixture's runtime, workspace, title and container |
| `AcceptsTheApprovedBlock` | the D1 stage admits exactly the pinned template (its pin in the policy, the body sent once, the template's sha256 in the record); another ACP block re-pinned is admitted as itself under another policy digest, and bytes changed without a new pin are `PROFILE_ARTIFACT_DRIFTED`; the boundary: the same profile's review stage and a profile without the declaration keep E-01.2.2's template |
| `RefusesAnyOtherBlock` | eighteen other agent blocks in the body (the F-04.2 bare agent, another kind or server, the `npx` form, an `npx` or wrapper command, arguments, another model or session mode, a shared data dir, an MCP server, tools, an agent profile or context, a missing key, wrong types) are `BODY_NOT_TEMPLATE` at the send and in `check_create_body`; another agent source beside it is `BODY_FIELD_UNKNOWN`; an approved template without an ACP block is `AGENT_BLOCK_NOT_ACP` |
| `RefusesTheF042Fixture` | the fixture pinned by path, by digest or both is `STAGE_TEMPLATE_DISPOSABLE` at resolution, nothing reserved; a re-serialized copy or its tag is refused at admission; a create built from it is `PROFILE_ARTIFACT_DRIFTED` (its bytes) or `BODY_NOT_TEMPLATE` (its block) |
| `RefusesTheQualificationFixture` | its file cannot be pinned (`PROFILE_ADMISSION_INVALID`; the reader refuses its path); its body pinned is `STAGE_TEMPLATE_DISPOSABLE`, untagged `BODY_FIELD_UNKNOWN` (`secrets`); its filled create is `BODY_FIELD_UNKNOWN`, and without `secrets` `BODY_NOT_TEMPLATE` (`tags`) |
| `SendCreateRechecks` | the review's R1: an admitted create built with admission's content check skipped (a non-ACP or a disposable template) is refused by `send_create` with the content check's code, and admission itself refuses it; the carried profile must be the approved one (`PROFILE_DRIFTED`: another profile, one byte more, empty; `PROFILE_MISSING`: none) |
| `DeclarationRefusals` | eleven malformed declarations are `PROFILE_ADMISSION_INVALID` for either stage; a missing pinned file is `PROFILE_ARTIFACT_MISSING` |

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
| `NetworkVerdict` (slice 5) | the connection table and its owners (no inode kept); the endpoint, loopback (IPv4, IPv6, IPv4-mapped) and inbound connections pass; another destination fails in each answered state, also another port of the endpoint's address; a `SYN_SENT` attempt is recorded, not failed; `CLOSE` and unknown states and unread tables fail without a stop; malformed endpoints and snapshots refused |
| `Shapes`, `CommandLine` | malformed snapshots, expectations, limits, sets and outputs refused, not judged; `collect` prints one result line and refuses bad arguments; the file imports only the standard library |

[`tests/test_acp_qualification.py`](tests/test_acp_qualification.py) (S-03.3 slice 2, unit), with a synthetic
conversation id, models and attempt tokens and the checked-in profile:

| Class | What it shows |
|---|---|
| `PositiveControl` | the filled fixture, exactly, admitted (also after a JSON round trip and with another approved model); the endpoint is the profile's; a token whose body holds an `sk-` run is still a token; the pins hold and the extract's wheels are the lock's; the module imports nothing that launches or connects |
| `RealStageRefusal` | the dispatcher's own body check against the profile's template and admission policy refuses the create (`BODY_FIELD_UNKNOWN` on `secrets`, then `BODY_NOT_TEMPLATE` on `agent_settings`) and admits the template itself; its artifact reader cannot read either qualification file (`PROFILE_ARTIFACT_MISSING`); the qualification check refuses the stage template |
| `FieldRefusals`, `SecretRefusals`, `DestinationRefusals`, `FixtureRefusals` | each refusal code above on its own fact: profile, tool, skill, plugin, hook and MCP fields; another agent kind or server; the empty, absent, `npx`, path, shell, `env` and other-adapter commands and any arguments; models outside or malformed allowlists; missing, extra (`OH_*`, OAuth) or renamed secrets; `LookupSecret` and malformed sources; encrypted secrets; provider-key-shaped values in four places; values that are not one token; the token, its body or another token elsewhere; eleven other base URLs and URLs elsewhere; malformed endpoint declarations; the conversation id; every other fixture field |
| `PinRefusals` | drifted bytes (a newline, CRLF, truncation, empty) and re-pinned but invalid files (not JSON, duplicate keys, another format, a missing or doubled placeholder, a command or secret names that disagree with the extract) are refused by the loader, the builder and the check; a re-pinned equivalent file is admitted |

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

[`tests/test_native_d1_stage.py`](tests/test_native_d1_stage.py) (E-05.9), on the E-05.2 fixture with
the synthetic profile declaring the native profile and a tunnel endpoint, the fake Agent Server and an
in-memory credential provider; **the proof**, clause by clause, every refusal with the counting
transport called zero times:

| Class | What it shows |
|---|---|
| `Accepts` | a full native dispatch sends exactly the four static secrets (the token, the tunnel endpoint, the two switches), `secrets_encrypted` false, the rest the template; no `ANTHROPIC_*` name; the result and the dispatched transition carry the fingerprint; the provider was asked for the one entry |
| `Refusals` | every rule of `NATIVE_MEANINGS` on its own fact (the review's inputs among them: a fifth secret through `agent_context.secrets`, `acp_file_secrets` seeding the configuration directory or writing the token, encoded copies of the token), at admission and again at `send_create`, no refusal text holding the token; a token not the held one; a token value in the admitted body; refusals of the profile (no, two or another tunnel endpoint) and the template (MCP, another command, a shared data dir) before any read; malformed declarations at resolution |
| `Mixing` | a broker grant on the native stage and the native token on the brokered one are `ADMISSION_MISMATCH`; the brokered stage refuses the native name (`SECRET_NAMES`) |
| `OtherStages` | the review stage refuses `secrets` (`BODY_FIELD_UNKNOWN`) and never reads the token; the S-03.3 qualification fixture is `STAGE_TEMPLATE_DISPOSABLE` on the native stage |
| `SharedCheck` | the dispatcher calls `create_secrets.check_native_secrets` (patched, it refuses with it); a qualification caller gets the same function and codes; the closed world (every forwarding request field, every `agent_settings` member outside the run shape); the native path with the broker module unreachable; no other module of the package declares the set |
| `ReadOrder` | the order `admit`, `stage_inference`, read, `admit_secrets`, workspace, `send_create`, the attempt reserved and no workspace at the read; a missing, malformed or unreadable entry, or no provider, is a refused attempt |
| `NoOtherCredential` | negative control: sentinels in other entries, the credential environment names and a host Claude configuration (an audit hook on file opens); only the one entry is read; positive controls see each kind of read |
| `Custody` | the store, the result, the admitted-create record and captured output and logs carry the fingerprint only, also on a refused, unknown and unanswered create |

[`tests/test_native_token.py`](tests/test_native_token.py) (unit): the shape and each rule by name; the
read of exactly one entry and its refusals; the held token's fingerprint-only views.
[`tests/test_native_token_search.py`](tests/test_native_token_search.py) (unit, Dulwich): a committed
copy in a real bundle found only in the inflated objects; the bundle's positive control (and its
negative control without delta application); a clean bundle, store and report directory
`not-found`; a planted copy found in each common encoding; a missed control is `invalid`; a report
holding the token is withheld; the command line's one-entry read and refusals. The entry command's
tests are [`../credentials/tests/test_native_token_entry.py`](../credentials/tests/test_native_token_entry.py).
