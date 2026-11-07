# Effects store (`effects.sqlite`)

Plan leaf F-05.2, blueprint section
[`#infrastructure-state`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#infrastructure-state),
[decision 0004](../../decisions/0004-privileged-effect-store-custody-and-restore-semantics.md)
(Proposed). This is the protected executor's own record of external effects
("Protected executor keeps its own effect receipts"; "No agent-write access"). It
uses the Python standard library only (`sqlite3`, `ctypes` for the read-only
custody check).

It is **separate from the integration store** (`integrations/store/`) in every
respect:

- a separate database in a separate directory tree;
- its own migration line and `PRAGMA application_id` (`0x41454658`);
- its own backup line and owner identity.

It is never attached to, co-located with, or backed up with `integration.sqlite`.
The two share only the mechanics in [`../storecore/storecore.py`](../storecore/storecore.py).

It is a **library and a command line, nothing else**: no network endpoint, no MCP
tool, no agent-callable surface. A test checks the imports and the command set.

**No live effects store exists.** F-05.2 proves the mechanisms on test fixtures
only. The live root is created by the Owner (act A4, at G-04.2.1), and G-04.2.2
provisions this store on it and proves denied access.

## Files

| Path | What |
|---|---|
| `effects_store.py` | The library and its command line (`init`, `status`, `backup`, `restore`, `verify-chain`) |
| `effects_custody.py` | Read-only custody check: the owner and DACL (or the POSIX mode and owner) read back from the OS |
| `migrations/NNNN_<name>.sql` | This store's own ordered, versioned migrations |
| `tests/test_effects_store.py` | Receipt, crash, backup and restore, reconciliation, manifest, location, custody, isolation and surface tests |
| `tests/effects_worker.py` | The subprocess the crash and custody tests run against one store |

## Commands

Run from the repository root. There is deliberately **no default path**: `--root`
is required and must already exist.

```
python -I -B integrations/effects/effects_store.py init --root <root> [--principal SID]       # task effects:init ROOT=<root>
python -I -B integrations/effects/effects_store.py status --root <root> [--principal SID]
python -I -B integrations/effects/effects_store.py backup --root <root> --actor <name>        # task effects:backup
python -I -B integrations/effects/effects_store.py restore --root <root> --manifest <file> --actor <name> [--accept-rollback]   # task effects:restore
python -I -B integrations/effects/effects_store.py verify-chain --root <root>                 # task effects:verify-chain
python -I -B -m unittest discover -s integrations/effects/tests -v                            # task effects:test
```

Each command prints JSON. When the store refuses, it exits 1 with
`REFUSED: <NAME>: ...`. `--principal` adds the executor principal's SID to the
custody template once G-04.2.1 has created it. Without it, the template is the
interim one: SYSTEM and Administrators only. Restore is the Owner's act, from an
elevated window, with the executor stopped.

## Location

`check_effects_root` runs every lexical rule before anything touches the
filesystem, so a refused location is never even stat-ed. It then checks the drive
type and existence, and checks the real path again. Refused, by name:

| Refusal | When |
|---|---|
| `LOCATION_MEMORY_OR_URI` | empty, `:memory:` or a `file:` URI |
| `LOCATION_UNC` | a UNC path (`\\server\share`, `//server/share`) |
| `LOCATION_REPOSITORY` | inside the repository checkout, or containing it |
| `LOCATION_INTEGRATION_TREE` | inside the integration store's tree (`%LOCALAPPDATA%\ai-engineering-harness`, or any tree the caller names), or containing it |
| `LOCATION_GUEST_STATE` | inside a guest-state root that a profile declares (`profiles/*/profile.json` `state_dir`, today `D:\aieh-guest-state`), or one the caller names |
| `LOCATION_PROFILE_ROOT` | inside a user-profile root: `%USERPROFILE%`, the Users root, `%LOCALAPPDATA%`, `%APPDATA%`, `$HOME`, `/home`, `/Users`, `/root` |
| `LOCATION_NETWORK_DRIVE`, `LOCATION_REMOVABLE`, `LOCATION_NOT_FIXED` | not a local fixed volume (Windows drive type) |
| `LOCATION_MISSING_ROOT`, `LOCATION_NOT_DIRECTORY` | the root does not exist (`init` **never creates it**), or is not a directory |
| `LOCATION_CO_LOCATED` | the root holds an `integration.sqlite` |

**Fixture policy.** `fixture_location_policy()` relaxes the user-profile rule and
nothing else, so tests can put a root under `%TEMP%`. Every other rule and the
custody check still apply. Only the library can select it: the command line
always uses `LIVE_POLICY` and has no option for it, and a test checks both. Every
summary echoes the policy in force (`location_policy`).

## Custody

On every open, `effects_custody.check_path` reads back what the operating system
actually holds: `GetNamedSecurityInfoW` for the owner, the DACL control bits and
every ACE. It reads the root directory, and also the database, its `-wal` and
`-shm`, and the `backups/` directories when they exist. It compares them with
the template and refuses by name.

| Refusal | When |
|---|---|
| `CUSTODY_WRONG_OWNER` | the owner is not SYSTEM, Administrators or the configured principal |
| `CUSTODY_EXTRA_ACE` | any ACE for another SID: Users, Authenticated Users, Everyone, the Owner's interactive account, OWNER RIGHTS, and so on |
| `CUSTODY_INHERITANCE_ENABLED` | the root's DACL is not protected |
| `CUSTODY_INHERITED_ACE` | the root holds an inherited ACE |
| `CUSTODY_NULL_DACL` | there is no DACL |
| `CUSTODY_UNSUPPORTED_ACE_TYPE` | an object or callback ACE |
| `CUSTODY_WRONG_MODE` (POSIX) | the directory is not 0700, or a file is not 0600 |

Files and directories inside the root inherit from the protected root. Inherited
ACEs are expected there, but their owner and every ACE SID must still be in the
template.

The module never changes a permission. The store creates its `backups/`
directories without an explicit mode on Windows, so they inherit the root. On
CPython 3.12.4 and later, `mkdir(mode=0o700)` writes its own protected DACL,
including OWNER RIGHTS, which the check would refuse.

The tests build their fixtures with the security API and `icacls`, on directories
they create. The template's principal is then the test process's own SID:

- a conforming directory opens;
- an extra ACE, inherited ACEs, a wrong owner, or an extra ACE on the database
  file is refused.

Denial to another principal is G-04.2.2's proof, not this one.

## Receipts

```python
store = effects_store.open_effects_store(root)       # live policy, interim template
request = effects_store.EffectRequest(operation_kind, target_identity, authority, inputs)
receipt = store.reserve(request, actor='executor').receipt      # before any effect
store.begin(receipt.effect_key, actor='executor')               # reserved -> applying
store.finish(receipt.effect_key, 'completed', actor='executor',
             result=effects_store.EffectResult('performed', observed_target_state))
```

Each receipt holds:

- the **one-time effect key**, `fx1-` plus the sha256 of the canonical key inputs.
  It is unique and immutable, and is re-derived and checked by `verify_chain` and
  by reconciliation.
- the **key inputs** themselves.
- the **operation kind** and the **target identity**.
- the **Owner authority reference**: the protected ref, the authorization
  revision, the manifest blob digest, the merged-by identity as the verifier
  reports it, and the policy revision.
- the **actor**.
- the **effect result**: the observed target state and the outcome. The outcome
  does not depend on the exit status, which is kept only as information.
- the times.

| From | To | Origin |
|---|---|---|
| (none) | `reserved` | executor (reservation; refused while a restore epoch is open) |
| `reserved` | `applying` | executor (refused while a restore epoch is open) |
| `reserved` | `failed` | executor (refused before any effect) |
| `applying` | `completed` / `failed` / `unknown` | executor |
| `reserved`, `applying` | `completed` / `unknown`; `applying` also `failed` | reconciliation |
| `unknown` | `completed` / `failed` | reconciliation, or a recorded Owner attestation |
| (none) | `observed` / `unknown` | reconciliation only (an effect the target shows, or an indeterminate one, without a receipt here) |

These rules are enforced in three places: in code; in SQL, by triggers and by a
foreign key from each event to `effect_transition`; and by the trigger gates.
Receipts are never deleted, and their identity columns and results never change.

`reconciliation_required()` lists `applying` and `unknown` receipts. After a
crash, an `applying` receipt is found that way on the next open, and it is never
reissued.

**Journal.** Every receipt creation, transition, reconciliation verdict and
restore-epoch event is a row in `effect_event`. Each row's
`hash = sha256(prev_hash || LF || content_json)`. A trigger enforces contiguous
sequence numbers and the link to the previous hash. `verify_chain` checks:

- every hash, recomputed;
- every indexed column against the hashed content;
- every receipt's key, re-derived from its inputs;
- every receipt's state against its last event.

The chain head is the hash of the last event. The high-water mark is its sequence
number.

## Backup, restore and restore epochs

The mechanics are the same as for the integration store
([`../store/README.md`](../store/README.md#backup-and-restore)), but on separate
lines and under separate custody:

- **Backup** goes to `<root>/backups/` and inherits the root's custody. It uses the
  SQLite online backup API, never a copy of the live files, followed by an
  integrity check and a sha256 manifest. The manifest records the high-water mark
  and the chain head; its example is in the F-05.2 evidence.
- **Restore** verifies the backup against its manifest. The backup must be of this
  store kind, with a schema no newer than this code, its sha256 must match, and it
  must be a rollback-journal copy. The restore then needs exclusive custody. A
  rollback is refused unless explicitly accepted. The superseded live content is
  preserved in `backups/superseded/` and never deleted. Finally the restore
  appends a restore epoch, which is a journal event and a `restore_epoch` row.
- **While an epoch is open**, `reserve` and `begin` are refused, in code and by
  triggers. Reads continue.

`reconcile(oracle, actor=..., candidates=[...])` resolves the uncertain receipts.
For each `applying` or `unknown` receipt, and each `reserved` receipt not yet
checked in this epoch, it re-derives the key and probes the target:

| Verdict | Result |
|---|---|
| performed | `completed`, with origin reconciliation. Never re-executed. |
| not performed | `failed` for an `applying` or `unknown` receipt. A `reserved` receipt is cleared and stays reserved. |
| indeterminate | `unknown`. Nothing more happens to it until an Owner attestation. |

`candidates` are effect requests that the caller still holds. A missing key
that the target shows performed gets an `observed` receipt. An indeterminate one
gets an `unknown` receipt.

`attest(key, outcome=..., attested_by=..., statement=...)` records the Owner's
attestation. `close_epoch(actor=...)` succeeds only once:

- no receipt is `applying` or `unknown`;
- every `reserved` receipt has been checked in the epoch.

Every verdict is an append-only `reconciliation_record` and a journal event.

`prune_backups(keep_last=N)` keeps the newest backup and every open epoch's
source. It never touches `backups/superseded/`. Receipts are never deleted.

## Recorded limits

- The **fixture oracle** in the tests stands in for real probes of the target;
  those come with G-04.4.2 and G-04.5.
- **OS-crash durability is UNKNOWN.** The crash tests kill processes; they do not
  cut power or crash the operating system.
- **Live identity separation cannot be proved** before G-04.2.1 and G-04.2.2. On
  this host, bootstrap agents run as the Owner's account. UAC consent gates
  elevation, but it is not a security boundary (decision 0004, point 9).
- The **command line's success path** needs an Owner-created root that conforms to
  the template. No such root exists, so the command line is exercised only for its
  refusals.
- **POSIX custody** (0700/0600 and the owner uid) is implemented and unit-tested on
  synthetic values only; it has not been run on a POSIX host.
- A key whose effect is recorded `failed` (not performed) stays spent. Retrying the
  same effect needs a new key, which means different inputs, for example an
  attempt number chosen by the executor (G-04.x).
