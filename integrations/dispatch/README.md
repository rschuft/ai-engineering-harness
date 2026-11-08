# Dispatch input resolution

Plan leaf E-01.2.1, blueprint section
[`#execution-qualification`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#execution-qualification),
dispatch step 01: "Resolve the authoritative Work and profile. Check Backlog readiness,
accepted OpenSpec revision and executable requirements; choose ... a qualified profile."
[`dispatch_inputs.py`](dispatch_inputs.py) is that step's trusted-side resolver. It is
Python standard library only and pure: it reads through injected sources and writes
nothing. Its output feeds
[`reserve_attempt`](../store/README.md#typed-attempt-identity) (step 02). E-01.2.2 adds the
workspace, mount, resource and runtime ceilings to this resolver; it does not add a second
one.

Nothing here has run against a live Backlog.md, a live store or a live manifest: **not yet
verified** outside the tests' throwaway directories.

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
   `true` (contract C6);
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
of `policy_inputs`, which holds exactly the approved entries the attempt was admitted under:

```json
{"format": "ai-engineering-harness/dispatch/policy-inputs/v1",
 "repository": {"id": "..."}, "stage": "...",
 "design": {"repository": "...", "change": "...", "commit": "..."},
 "profile": {"id": "...", "sha256": "..."},
 "catalog_pin": {"id": "...", "repository": "...", "commit": "...", "manifest_sha256": "..."}}
```

It does not cover the manifest's version or digest (they are provenance, beside it), the
binding lists, the Work or the ordinal (the attempt identity). A manifest revision that does
not change these entries leaves the policy digest unchanged; it still changes the intent
digest, so retrying a reserved key under another approval is a `ConflictingReservation`.
E-01.2.2 adds its ceilings to `policy_inputs` under a new format tag.

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
| `DeterminismTests` | the same inputs give an identical record and intent digest; the policy inputs and a pinned golden policy digest; each policy input changes the digest; a manifest revision changes provenance and the intent digest but not the policy digest, so a retry under it conflicts; the record is immutable |
| `ManifestCheckerTests` | the example is valid; schema, version, identifiers, duplicates (also duplicate JSON keys), unknown references, non-full commits, digest format, unreadable bytes; type fuzzing never crashes |
| `ManifestCustodyTests` | the checkout (inside or containing) is refused before reading; path shapes; a manifest outside the checkout loads; `manifest_path` is `<state>/dispatch/approved-inputs.json` and creates nothing |
| `CliTests` | `check-manifest` exit codes and report; `manifest-path` with `AIEH_DATA_ROOT` in a throwaway directory creates nothing |

The design repository is built by the planning fixture (`two_task_fixture.build_repo`, a
reproducible commit), and Backlog.md is its own recorded readiness output
(`integrations/planning/tests/fixtures/readiness/`), so the Work and design checks run
against real Backlog.md JSON and real git objects.
