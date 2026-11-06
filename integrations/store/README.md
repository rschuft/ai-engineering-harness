# Integration store (`integration.sqlite`)

Plan leaf F-05.1, blueprint section
[`#infrastructure-state`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#infrastructure-state).
This is the trusted host's local transactional state for the Integration Service:
**operational coordination receipts** (attempt reservations and their transitions)
and **rebuildable projections**. It is Python standard library only (`sqlite3`).

It is not a record of authority. OpenSpec, Backlog.md, OpenHands, Gitea and the
Owner keep their own data. The privileged executor's effect receipts belong in a
separate store (F-05.2), never here.

## Files

| Path | What |
|---|---|
| `integration_store.py` | The library and its command line (`init`, `default-path`) |
| `migrations/NNNN_<name>.sql` | Ordered, versioned schema migrations |
| `tests/test_integration_store.py` | Transaction, restart, crash, contention, migration and projection tests |
| `tests/store_worker.py` | The subprocess the tests run against one database file |

## Commands

Run from the repository root (`python3` outside Windows):

```
python -I -B integrations/store/integration_store.py init --db <path>     # task store:init DB=<path>
python -I -B integrations/store/integration_store.py default-path        # task store:path
python -I -B -m unittest discover -s integrations/store/tests -v         # task store:test
```

`init` creates the parent directory if needed, creates or migrates the store, and
prints a JSON summary: the path, SQLite version, schema version, applied
migrations with their sha256, the connection pragmas and the table lists. It is
idempotent; running it again only re-checks the migrations. It exits 1 with
`REFUSED: ...` when the store refuses to open.

`default-path` prints the default location and creates nothing.

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

## Attempt receipts

A caller reserves an attempt **before** any external call:

```python
store = integration_store.open_store(path)
result = store.reserve(operation_key, intent, actor='dispatcher')
result.reservation.conversation_id   # send this conversation_id on the create
```

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

## Schema

| Table | Kind | Holds |
|---|---|---|
| `schema_migration` | canonical | applied migrations: version, file name, sha256 of the LF-normalised text, time |
| `attempt_state`, `attempt_transition`, `reconciliation_status` | canonical | the closed vocabularies; changed only by a migration |
| `attempt` | canonical | one row per attempt key; identity columns immutable |
| `attempt_event` | canonical | append-only history |
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
- it is not empty but has no version (not an integration store).

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

F-05.1 has only a test fake source. The real OpenSpec and Backlog projections
come later, and backup and restore are F-05.2.
