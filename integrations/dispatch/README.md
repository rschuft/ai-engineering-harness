# Dispatch input resolution and create admission

Plan leaves E-01.2.1 (resolution) and E-01.2.2 (admission, slice (a)), blueprint section
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

Nothing here has run against a live Backlog.md, a live store, a live manifest or a live Agent
Server: **not yet verified** outside the tests' throwaway directories.

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
10. the ordinal: `next_ordinal(work_id, design_revision, stage)` (`store_next_ordinal`
    reads the store's typed claims; `reserve_attempt` remains the arbiter of live claims).

Steps 1 to 6 read the manifest only. No file, Backlog.md or git read happens for an
unapproved repository, stage, profile or pin.

| Injected | Live implementation | Tests |
|---|---|---|
| `work_sources(repository)` | `PlanningWorkSource(planning_adapter.Backlog(...), planning_adapter.Git(...))` for the approved repository | Backlog.md's recorded readiness JSON replayed in process, and a throwaway design repository |
| `next_ordinal` | `store_next_ordinal(store)` | the same, on a throwaway store |
| `read_profile` | `read_profile_file` (the checkout's `profiles/`, byte-exact by `profiles/.gitattributes`) | throwaway profile declarations |

### Resolved record: `ai-engineering-harness/dispatch/resolved-inputs/v1`

`ResolvedInputs` is frozen. `attempt_identity()` gives the store's `AttemptIdentity`;
`intent()` gives `{"dispatchInputs": <the record>}` for `reserve_attempt`, so the stored
intent and its digest carry the approval provenance.

| Field | Source |
|---|---|
| `work_id`, `repository`, `stage` | the request, canonical |
| `ordinal` | `next_ordinal` |
| `design_revision` | `openspec:changes/<change>@<commit>` from the task's pointers |
| `profile`, `profile_digest` | the sha256 of the `profile.json` bytes, equal to the approved one |
| `catalog_pin`, `agent_manifest_digest` | the pin's `manifest_sha256`; never null (E-01.1.1 left it nullable until this leaf) |
| `planned_workspace` | the fixed rule `<repository>/<work_id>/<attempt_id>`, relative to the managed root's `workspaces` category; `attempt_id` is the store's `uuid5(ATTEMPT_NAMESPACE, operation_key)`, so each attempt has its own |
| `policy_digest`, `policy_inputs` | below |
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
workspace (with the on-disk walk), the template's sha256, route, body and mounts. Only then
does it call `transport(method, path, body)` with the body it validated, exactly once. A
refusal calls the transport zero times. A transport failure is raised, never retried and never
re-routed to another runtime.

**Not closed here.** Two recorded deviations are upstream registry behaviour that no create
field controls: `host.docker.internal:host-gateway` and no `--network none` on every
conversation container (F-04.2 section 7). Whether the running container matches the admitted
mount set and caps is observed guest-side (`conversation-smoke`, and E-01.2.2 slice (b)).

`AdmittedCreate.to_json()` is `ai-engineering-harness/dispatch/admitted-create/v1`: the
operation key, conversation id, route, body, mount set, planned and host workspace, policy
digest and the template's sha256.

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
| `IDENTITY_INVALID` | the resolved inputs do not form a valid attempt identity |
| `PROFILE_ADMISSION_INVALID` | the profile declares no complete, well-formed admission policy |
| `PROFILE_ARTIFACT_MISSING`, `PROFILE_ARTIFACT_DRIFTED`, `PROFILE_ARTIFACT_INVALID` | a pinned create template or route allowlist is absent, changed, or not strict JSON of its shape |
| `ADMISSION_MISMATCH` | the resolved inputs or the admitted request do not match the approval they claim |
| `RUNTIME_NOT_DOCKER` | a local, process, selectable or omitted runtime, in the server configuration or the body |
| `CAPS_ABOVE_CEILING`, `CAPS_OVERRIDE_FORBIDDEN` | the declared caps times the concurrent runs exceed the guest ceilings; a body cap other than the declared one, or a cap field the policy does not establish |
| `MOUNT_POLICY_INVALID`, `MOUNTS_NOT_DECLARED` | declared binds outside the rules; an effective mount set other than the declared one, or a body field that would add a mount |
| `WORKING_DIR_NOT_ALLOWED` | the body's workspace is not the server-provisioned `/workspace` |
| `ROUTE_NOT_ALLOWLISTED` | the create does not target `POST /api/conversations`, or the allowlist does not admit it |
| `BODY_MALFORMED`, `BODY_FIELD_UNKNOWN`, `BODY_NOT_TEMPLATE`, `CONVERSATION_ID_MISMATCH` | the body is not an object, carries a field outside the allowlist, differs from the pinned template, or lacks the reserved conversation id |
| `WORKSPACE_CATEGORY_UNAVAILABLE`, `WORKSPACE_PATH_INVALID`, `WORKSPACE_RESERVED_NAME`, `WORKSPACE_NOT_PLANNED`, `WORKSPACE_PATH_UNSAFE` | the host workspace: no usable category; outside the fixed rule's grammar; a Windows device name; not this attempt's; a link, junction, reparse point or non-directory on disk |

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
