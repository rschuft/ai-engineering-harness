# Integration store (`integration.sqlite`)

Plan leaves F-05.1, F-05.2 and E-01.1.1, blueprint section
[`#infrastructure-state`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#infrastructure-state).
This is the trusted host's local transactional state for the Integration Service:
**operational coordination receipts** (attempt reservations and their transitions)
and **rebuildable projections**. It is Python standard library only (`sqlite3`).

It is not a record of authority. OpenSpec, Backlog.md, OpenHands, Gitea and the
Owner keep their own data. The privileged executor's effect receipts belong in a
separate store (F-05.2), never here. The store also carries the Owner recorders' decision
receipts (the authorization recorder's, and its dispatch-input commands' design acceptances and
manifest promotions, P-04.3), which `load_manifest` reads as evidence that a decision was recorded;
the authority stays with the decider.

## Files

| Path | What |
|---|---|
| `integration_store.py` | The library and its command line (`init`, `default-path`, `backup`, `restore`) |
| `migrations/NNNN_<name>.sql` | Ordered, versioned schema migrations |
| `tests/test_integration_store.py` | Transaction, restart, crash, contention, migration and projection tests |
| `tests/test_attempt_identity.py` | Typed attempt identity, key, claim rule, lifecycle flag, SQL/Python grammar agreement and migration 0003 (E-01.1.1) |
| `tests/test_reservation_crash_concurrency.py` | Typed reservations under real process crashes at each statement boundary of a reservation and a transition, restart in a new process, and concurrent admission races (E-01.1.2) |
| `tests/test_backup_restore.py` | Backup, restore, restore epochs, manifest checks and the projection rebuild from a synthetic repository (F-05.2) |
| `tests/store_worker.py` | The subprocess the tests run against one database file; its `scripted` command runs real library calls and stops at a chosen SQL statement (`os._exit`, or blocks until the test kills it) |
| `../planning/planning_adapter.py` | Read only: the identifier grammars (task id, change id, commit, path) and `Pointer.parse` that typed identities reuse |
| `../storecore/storecore.py` | The SQLite mechanics shared with the effects store: connection policy, migration ledger, write transactions, the projection authorizer, backup and restore |

## Commands

Run from the repository root (`python3` outside Windows):

```
python -I -B integrations/store/integration_store.py init --db <path>     # task store:init DB=<path>
python -I -B integrations/store/integration_store.py default-path        # task store:path
python -I -B integrations/store/integration_store.py backup --db <path> --actor <name>      # task store:backup
python -I -B integrations/store/integration_store.py restore --db <path> --manifest <file> --actor <name> [--accept-rollback]   # task store:restore
python -I -B -m unittest discover -s integrations/store/tests -v         # task store:test
```

`init` creates the parent directory if needed, creates or migrates the store, and
prints a JSON summary: the path, SQLite version, schema version, applied
migrations with their sha256, the connection pragmas and the table lists. It is
idempotent; running it again only re-checks the migrations. It exits 1 with
`REFUSED: ...` when the store refuses to open.

`default-path` prints the default location and creates nothing. `backup` and
`restore` are described in [Backup and restore](#backup-and-restore).

## Location

Always pass an explicit path. The default trusted-host location is per-user
application data:

- Windows: `%LOCALAPPDATA%\ai-engineering-harness\state\integration.sqlite`
- elsewhere: `${XDG_DATA_HOME:-~/.local/share}/ai-engineering-harness/state/integration.sqlite`

The default store is initialised when a consumer first needs it, not by setup.
The file must stay on local disk, out of every agent workspace and out of guest
storage, and must never be inside the repository. The store refuses paths inside
this checkout, UNC paths and (on Windows) network drives. On other systems it does
not detect network mounts: placing the file on local disk is the operator's
responsibility. `init` creates the directory with mode 0700 on POSIX; on Windows
the directory inherits the per-user profile's ACL. Neither is otherwise verified.

## Transaction policy

- Every connection sets and reads back `journal_mode=WAL`, `synchronous=FULL`,
  `foreign_keys=ON` and a busy timeout (10 s by default). A connection that did
  not take them is refused.
- One writer at a time: every write is a `BEGIN IMMEDIATE` transaction, so the
  write lock is held before anything is read to decide the write.
- One transaction each for a reservation, a transition, a migration run and a
  projection rebuild. A crash before `COMMIT` leaves nothing behind.
- Receipts are never deleted and their history is never rewritten. There is no
  API for it, and triggers refuse it.
- SQLite 3.38.0 or newer is required (STRICT tables, built-in JSON functions);
  `open_store` checks the runtime version and refuses an older library.
- `ATTACH` is impossible on every connection (the attached-database limit is 0).
- `PRAGMA application_id` is `0x41494E54` (set by migration 0002). Opening refuses
  a file of another store kind, such as an effects store.

## Attempt receipts

A caller reserves an attempt **before** any external call:

```python
store = integration_store.open_store(path)
result = store.reserve(operation_key, intent, actor='dispatcher')
result.reservation.conversation_id   # send this conversation_id on the create
```

A Work attempt is reserved with `reserve_attempt` under a typed identity instead
(see [Typed attempt identity](#typed-attempt-identity)). `reserve` keeps working
for opaque keys outside the `attempt/` namespace; those attempts are untyped.

- `operation_key` is the durable attempt key (text, 1 to 512 characters,
  unique).
- `intent` is a JSON object holding the intended scoped resources and the rest of
  the request. The store keeps its canonical JSON (sorted keys, no whitespace)
  and its sha256 `intent_digest`.
- `conversation_id` is `uuid5(CONVERSATION_NAMESPACE, operation_key)`. The
  namespace is fixed in `integration_store.py` and must never change. It is
  unique in the schema.
- Reserving an existing key with the same digest returns the existing
  reservation (`created=False`). Reserving it with a different digest raises
  `ConflictingReservation` and changes nothing.

States and allowed transitions (enforced in code, by a trigger on `attempt`, and
by a foreign key from each event to `attempt_transition`):

| From | To | Meaning |
|---|---|---|
| (none) | `reserved` | intent, key and conversation ID committed; no external call yet |
| `reserved` | `dispatched` | the external create is about to be or has been sent |
| `reserved` | `failed` | refused before any external call |
| `dispatched` | `confirmed` / `failed` | outcome observed |
| `dispatched` | `unknown` | outcome uncertain (for example a lost acknowledgement) |
| `unknown` | `confirmed` / `failed` | resolved by reconciliation against the external system |

`confirmed` and `failed` are terminal. `reconciliation_status` is `required`
exactly while the state is `unknown`, becomes `reconciled` when an unknown
attempt is resolved, and is otherwise `none`. `transition(..., expected_from=)`
refuses the change when the current state differs.

Every reservation and transition appends a row to `attempt_event`: the sequence
number, from and to states, reconciliation status, actor, reason, optional JSON
detail and time.

## Typed attempt identity

Plan leaf E-01.1.1, migration 0003, blueprint
[`#execution-qualification`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#execution-qualification),
dispatch step 02: "Persist Work ID, immutable design revision, attempt UUID,
preselected conversation UUID, planned workspace and policy digest. Prevent
concurrent claims of the same Work revision/stage."

A Work attempt is reserved under a typed identity, before any external call:

```python
identity = integration_store.AttemptIdentity(
    work_id='TASK-12', design_revision=integration_store.design_revision_from_pointers(task_pointers),
    stage='implement', ordinal=1, profile_digest=..., planned_workspace='work/TASK-12/attempt-1',
    policy_digest=..., agent_manifest_digest=None)
result = store.reserve_attempt(identity, intent, actor='dispatcher')
result.reservation.conversation_id   # send this conversation_id on the create
result.attempt.attempt_id            # this receipt's own identity
```

### Identity

| Field | Contract | Source |
|---|---|---|
| `work_id` | the Backlog.md task id, `planning_adapter.TASK_ID_RE`, stored upper case (Backlog.md and the planning adapter compare ids without case), at most 64 characters | Backlog.md (P-02.2) |
| `design_revision` | `openspec:changes/<change>@<commit>`: the blueprint's change-level design notation, built from the planning adapter's `CHANGE_ID` (at most 128 characters) and a full `COMMIT` (40 or 64 hex digits). `design_revision_from_pointers` derives it from a task's OpenSpec source pointers with `Pointer.parse`; they must all pin one change at one commit | OpenSpec in git (P-02.1) |
| `stage` | a row of `attempt_stage`: `implement` or `review` | blueprint, "One Work item" steps 2 and 3 |
| `ordinal` | 1, 2, 3 ... per (`work_id`, `design_revision`, `stage`), no gaps, at most 999999 | this store |
| `profile_digest` | sha256 (64 lower-case hex digits) of the execution profile's `profile.json` bytes, as `tools/guest.py` records `profile.sha256` | `profiles/` |
| `agent_manifest_digest` | sha256 of the approved agent and Skill manifest; `None` (JSON `null`) while no approved catalog exists. E-01.2.1 makes it required | the catalog (not yet built) |
| `planned_workspace` | a relative identifier under the managed root's `persistent/workspaces` category (decision 0009), the planning adapter's `ARTIFACT_PATH` grammar, at most 255 characters. Never a host path: `/`, a drive, `..`, a hidden part or a backslash is refused. E-01.2.2 resolves it through `integrations/paths` | decision 0009 |
| `policy_digest` | sha256 of the applicable policy | the dispatcher's policy input |

Every digest is CHECK-constrained to 64 lower-case hex digits. The SQLite CHECKs
and the Python validators accept exactly the same values; a differential test
compares them.

### Key, attempt ID and conversation ID

- `operation_key` is `attempt/v1/<work_id>/<change>@<commit>/<stage>/<ordinal>`,
  for example `attempt/v1/TASK-1/qual-02-search-freshness@8eacfa8...4fb7/implement/1`.
  No part's grammar contains `/`, so the encoding is unambiguous without escaping;
  the longest identity is under 300 characters, within the 512-character limit.
  A trigger refuses an identity whose key is not this encoding of its columns.
- The `attempt/` key namespace belongs to typed attempts. `reserve` refuses it, and
  a trigger refuses an `attempt` row in it that has no identity.
- `conversation_id` stays `uuid5(CONVERSATION_NAMESPACE, operation_key)`: the
  identity sent to the external system.
- `attempt_id` is `uuid5(ATTEMPT_NAMESPACE, operation_key)`, under its own fixed
  namespace: this receipt's identity. It is unique and immutable, and a restart
  re-derives it. Neither namespace may ever change; tests pin a known pair for each.
- The other fields (profile, manifest, workspace, policy) are not in the key. They
  are in the intent, so the same key with another profile or policy is a
  `ConflictingReservation` (also named `IntentConflict`), never a second attempt.

### Intent

The stored intent is the caller's intent plus two keys:

- `workRef`: `backlog:<work_id>`. `integrations/lineage` follows it from the
  reservation to the task. A caller may supply it only with that value.
- `attemptIdentity`: the identity's fields with `format: attempt-identity/v1`.
  Reserved; a caller may not supply it.

A trigger checks both against the typed columns when the attempt row is written.
`intent_digest` covers the whole of it.

### reserve_attempt

One `BEGIN IMMEDIATE` transaction. In order, with nothing changed on a refusal:

1. the key exists with the same digest: the existing reservation, `created=False`;
2. the key exists with another digest: `ConflictingReservation`;
3. a restore epoch is open: `RestoreEpochOpen`;
4. an attempt on the same (`work_id`, `design_revision`, `stage`) is `reserved`,
   `dispatched` or `unknown`: `LiveClaim`;
5. the ordinal is not the next one on that triple: `OrdinalOutOfSequence` (a gap;
   reusing an ordinal is its existing key, so 1 or 2 applies).

An invalid field raises `InvalidIdentity` when the `AttemptIdentity` is built.
Otherwise the identity row, the attempt row and its seq-0 event are written.
`attempt_identity(key)` reads an identity (`None` for an untyped attempt),
`identity_form(key)` says `typed` or `legacy-untyped`, and
`claims(work_id, design_revision, stage)` lists a triple's attempts by ordinal.

### Crashes, restarts and races

Plan leaf E-01.1.2 tests these with real processes (`tests/test_reservation_crash_concurrency.py`).

- **Crashes.** A process that dies anywhere inside a reservation or a transition leaves
  the store as it was before that call: the identity, attempt and event rows of one call
  commit together or not at all. Once `COMMIT` has run, the result survives even if the
  process dies before it returns and nothing checkpointed the WAL. A process killed while
  it holds the write lock releases it.
- **Restarts.** After any crash or restart, an identical request returns the same
  `operation_key`, `attempt_id`, `conversation_id` and `design_revision`, with
  `created=False` once the row exists.
- **Races.** Concurrent requests get typed outcomes only, never a raw `sqlite3` error such
  as `SQLITE_BUSY`:
  - identical requests: one `created`, the rest `existing`;
  - competing ordinals on one triple: one live claim, the rest `LiveClaim` or
    `OrdinalOutOfSequence`;
  - one key with different intents: one `created`, the rest `ConflictingReservation`;
  - different triples: all `created`;
  - competing transitions: one wins, the rest `IllegalTransition`.

### Claim rule

At most one live attempt per (`work_id`, `design_revision`, `stage`). A new
ordinal is reserved only when every earlier ordinal on the triple is terminal
(`confirmed` or `failed`) and the ordinals have no gap. Never while one is
`reserved`, `dispatched` or `unknown`: an unknown outcome is reconciled first. A
rework after review is another `implement` ordinal, and a fresh review another
`review` ordinal. Whether one is warranted, and how many, is policy and the stage
reconciler's decision; the schema encodes no cap.

Mechanism, all in SQLite so any writer is held to it:

- `attempt_identity.live` is 1 while the attempt is reserved, dispatched or
  unknown, and 0 once it is confirmed or failed. It is written only by triggers:
  an identity is inserted live, an `AFTER UPDATE OF state` trigger on `attempt` sets
  it from `attempt_state.terminal`, and a `BEFORE UPDATE OF live` trigger refuses any
  value that disagrees with the attempt's state. So it cannot drift.
- A partial unique index on (`work_id`, `design_revision`, `stage`) `WHERE live = 1`
  is the structural rule: two live rows on a triple cannot exist.
- A `BEFORE INSERT` trigger on `attempt_identity` (`attempt_identity_admission`)
  refuses a non-canonical key, a row not inserted live, a row attached to an
  existing attempt, a live claim and an ordinal that is not the next one, with a
  clear message.
- The identity is written before its attempt; its reference to `attempt` is
  deferred to `COMMIT`, so an identity without its attempt never commits. A
  trigger on `attempt` (`attempt_typed_admission`) requires a typed attempt to start
  `reserved` and its intent to carry the same identity.

Why: the blueprint asks to prevent concurrent claims, and the index holds the rule
even if the trigger were bypassed. The trigger gives the ordinal rule and a named
refusal; the flag lets a partial index express "live". The tests show a raw SQL
insert refused under each rule, the index refusing a second live row with the
trigger dropped, and every direct write of `live` that disagrees refused.

### Lifecycle contract

The states and transitions are those of migration 0001, unchanged. The store
records the actor of each change; it does not authenticate it. Callers keep to
this contract:

| State | Entered by (who, when) | What it permits |
|---|---|---|
| `reserved` | the dispatcher, through `reserve_attempt`, before any external call | dispatching with the reserved `conversation_id`; after a restart, dispatching it again (the ID is deterministic, decision 0001); no other ordinal on the triple |
| `dispatched` | the dispatcher, immediately before it sends the create (E-01.3.x) | waiting for and recording the outcome; a create retry only with the same `conversation_id` and only when the pinned server advertises `idempotent_conversation_create_v1` (decision 0001); no other ordinal |
| `unknown` | the dispatcher on a lost acknowledgement or an interrupted create, or `reconcile` while a restore epoch is open | reconciliation only: query the reserved `conversation_id` (E-01.4.x); "a lost HTTP reply is not permission to start a new conversation"; no other ordinal |
| `confirmed` | the dispatcher on an observed successful create, or the reconciler when the conversation is found | terminal; the next ordinal on the triple (rework, a fresh review) if policy calls for one |
| `failed` | the dispatcher on a refusal before any external call or an observed failed create, or the reconciler when the conversation is not found | terminal; the next ordinal (a retry) if policy calls for one |

`confirmed` is about the conversation create, not about the Work: whether the
Work is done stays with Backlog.md and the evidence.

`confirmed` is not execution completion either: the conversation it records may
still be running. The store's claim rule covers reservation and creation only;
it permits the next ordinal once the earlier one is terminal, and nothing in the
store knows whether that conversation has finished. Execution-level
non-overlap is the coordinator's duty: it must not reserve the next ordinal of a
(`work_id`, `design_revision`, `stage`) triple while the earlier attempt's
conversation is still executing, as the Agent Server reports it. That rule is
required, with acceptance tests, at E-01.5 and E-04.2.x; until then no component
enforces it. The reservation schema stays as it is.

## Migration 0003

`0003_typed_attempt_identity.sql` adds `attempt_stage`, `attempt_identity`, the
partial unique index, the triggers above and the `attempt_typing` view. It
changes no existing table, state or transition.

- Attempts reserved before it (opaque keys) stay valid, unchanged and untyped:
  `identity_form` is `legacy-untyped`, they have no identity, they keep their
  lifecycle, and they are outside the claim rule. Receipts are never rewritten or
  deleted. `reserve` keeps working for opaque keys outside `attempt/`; those rows
  are untyped as well.
- If an untyped attempt already uses a key in the `attempt/` namespace, the
  migration refuses (`MigrationError: migration 0003 refused ...`) and the store
  stays at version 2, unchanged.
- The canonical dump of an older store is unchanged: a table that 0003 adds and
  the store does not have writes no line. So a backup manifest written before 0003
  still verifies.
- The backup verification also checks every typed row: its `attempt_id` and
  `conversation_id` are the uuid5 of its key, its `live` flag matches the state,
  and no `attempt/` key lacks an identity.

## Schema

| Table | Kind | Holds |
|---|---|---|
| `schema_migration` | canonical | applied migrations: version, file name, sha256 of the LF-normalised text, time |
| `attempt_state`, `attempt_transition`, `reconciliation_status` | canonical | the closed vocabularies; changed only by a migration |
| `attempt` | canonical | one row per attempt key; identity columns immutable |
| `attempt_event` | canonical | append-only history |
| `attempt_stage` | canonical | the closed stage vocabulary; changed only by a migration (0003) |
| `attempt_identity` | canonical | one row per typed attempt: its typed identity, `attempt_id` and `live` flag; identity immutable (0003) |
| `attempt_typing` (view) | derived | each attempt's `identity_form`: `typed` or `legacy-untyped` (0003) |
| `restore_epoch`, `restore_epoch_closure` | canonical | one row per restore and its closure; append-only (migration 0002) |
| `proj_cursor` | projection | per projection: source, source cursor, coverage, rebuild time |
| `proj_<name>`, `proj_<name>_*` | projection | rebuildable views; no authority |

All tables are `STRICT`. `PRAGMA user_version` equals the highest applied
migration.

## Migrations

Migrations are `migrations/NNNN_<name>.sql`, numbered 1..N without gaps. Each
pending migration runs inside one `BEGIN IMMEDIATE` transaction, together with
its `schema_migration` row and `PRAGMA user_version`. A failing migration leaves
the database exactly as it was.

Opening refuses a database when:

- a recorded migration's name or checksum differs from the file (an applied
  migration was edited);
- its version is newer than the migrations this code knows;
- the recorded list does not match `user_version`;
- it is not empty but has no version (not an integration store);
- its `application_id` names another store kind.

The checksum is taken over the file's text with CRLF normalised to LF, so it is
the same in any checkout. `integrations/.gitattributes` also keeps these files LF.
Never edit an applied migration; add a new one.

## Projections

A `Projection` names its source and the tables it owns (`proj_<name>` or
`proj_<name>_*`). It supplies their DDL and a `populate(conn)` callable that
returns the source cursor reached and a coverage description.
`rebuild_projection` drops and recreates exactly those tables, fills them and
records the cursor, all in one transaction. While it runs, an SQLite authorizer
denies every other write and schema change: canonical tables, other
projections, triggers, views, `ATTACH`, pragmas and transaction control. A
denied or failed rebuild rolls back completely. The tests show that a rebuild
leaves every canonical table byte-for-byte unchanged.

The real OpenSpec and Backlog projections come later. Until then the tests use a
fake source and, for F-05.2, a synthetic git repository holding OpenSpec-shaped
and Backlog.md-shaped files. The projection reads it with `git ls-tree` and
`git cat-file` only. The tests show that the repository's HEAD, tree, references,
`git status` and file bytes are unchanged after a rebuild, and so are the
canonical tables.

## Backup and restore

Plan leaf F-05.2,
[decision 0004](../../decisions/0004-privileged-effect-store-custody-and-restore-semantics.md).
The mechanics are in `../storecore/storecore.py` and are shared with the effects
store. The two stores are never backed up or restored together.

**Backup** (`store.backup(actor=...)`, `task store:backup`). The SQLite online
backup API copies the store into `<db dir>/backups/<kind>-<UTC>-hw<N>.sqlite`. The
live `.sqlite`, `-wal` and `-shm` files are never copied. The copy is switched to
the rollback journal and must pass `PRAGMA integrity_check` and
`foreign_key_check`. Only then is its sidecar manifest written,
`<copy>.manifest.json`, recording:

- the store kind and `application_id`;
- the schema version and the migrations with their sha256;
- the UTC time and the actor;
- the size and sha256 of the copy;
- the canonical high-water mark and the history digest;
- the digest of the canonical dump.

A backup without a manifest does not count. Here the high-water mark is the last
`attempt_event` ID. The history digest chains the attempt events up to it.
Restore-epoch rows are bookkeeping and are not counted. The manifest's
`chain_head` is null: only the effects store has a hash chain.

**Restore** (`restore_store(db, manifest, actor=...)`, `task store:restore`). In
order:

1. Verify the backup against its manifest. Refused: a manifest of another format
   or store kind; a copy whose sha256 or size differs; a file that is not a
   rollback-journal backup copy; a schema version newer than this code knows;
   recorded migrations that differ from the files; a failed integrity check; or
   facts that differ from the manifest. An older schema is migrated after the
   restore.
2. Take exclusive custody of the live file: `locking_mode=EXCLUSIVE` and
   `BEGIN EXCLUSIVE`. Any other open connection makes the restore refuse
   (`EXCLUSIVE_CUSTODY`).
3. Compare histories. If the live store is ahead of the backup, or diverges from
   it, that is a rollback, refused (`ROLLBACK_REFUSED`) unless `--accept-rollback`
   is given. A live file that cannot be read, or that is of another store kind, is
   always refused.
4. Preserve the live content aside with the backup mechanism, in
   `backups/superseded/`, with a JSON note. The tools never delete it.
5. Stage the backup in `backups/staging/`. Migrate it, drop every projection and
   clear `proj_cursor` (under the projection authorizer), and append a
   `restore_epoch` row. The row records the backup's identity, high-water mark and
   history digest, the superseded store's mark and digest, the superseded copy,
   whether a rollback was accepted, the projections dropped, the actor and the time.
6. Replace the live content with the staged copy in one backup step, which is one
   destination transaction. A crash leaves the old store or the new one.

**Restore epochs.** A restore loses knowledge, never effects. While an epoch has
no closure, `reserve` refuses new attempts (`RestoreEpochOpen`), and so does a
trigger (`attempt_reservation_gate`). Reads continue. Then:

- `reconcile(oracle, actor=...)` moves every `dispatched` attempt to `unknown`.
- It then resolves each `unknown` attempt with the oracle's verdict:
  - `performed` becomes `confirmed`;
  - `not_performed` becomes `failed`;
  - `indeterminate` stays `unknown`.

  These are the F-05.1 transitions, unchanged.
- `close_restore_epoch(actor=...)` closes the epoch once no attempt is
  `dispatched` or `unknown`.
- A `reserved` attempt may stay: its conversation ID is deterministic, so a second
  dispatch cannot create a second conversation (decision 0001).

The real oracle, a lookup in OpenHands, is E-01.4.x. The tests use a fixture.

**Retention.** `store.prune_backups(keep_last=N, older_than_days=None)` deletes
old backup copies and their manifests. It never deletes the newest copy, the
source of an open epoch, or anything in `backups/superseded/`. Canonical rows are
never deleted.

Backups are local-disk only. They inherit the custody of the store's directory,
which is the Owner's session (decision 0004, point 9).
