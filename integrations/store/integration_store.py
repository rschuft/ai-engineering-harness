"""Trusted-host integration store: operational receipts and rebuildable projections.

Plan leaf F-05.1, blueprint section #infrastructure-state. Python standard library
only (sqlite3). The store is the Integration Service's local transactional state,
``integration.sqlite``: attempt reservations (durable attempt key, intent digest,
deterministic conversation ID, state and reconciliation status), an append-only
event history of their transitions, and projection tables that are rebuildable
from their sources and carry no authority.

Transaction policy
------------------
* Journal mode WAL, ``synchronous=FULL``, ``foreign_keys=ON`` and a busy timeout on
  every connection; ``open_store`` reads each back and refuses a connection that
  did not take them.
* One writer at a time: every write is a ``BEGIN IMMEDIATE`` transaction, so the
  write lock is taken before anything is read for the decision.
* Each reservation, each transition, each migration run and each projection
  rebuild is exactly one transaction. Nothing is committed half-way.
* Receipts are never deleted and events are never rewritten; there is no API for
  either and triggers refuse both.
* Local disk only: UNC paths and Windows network drives are refused. The file
  must never be inside this repository or in agent/guest storage.
* ``ATTACH`` is impossible on every connection (attached-database limit 0), and
  ``PRAGMA application_id`` (set by migration 0002) identifies the file as an
  integration store: the effects store refuses it and this store refuses an
  effects store file.

Backup and restore (plan leaf F-05.2, decision 0004)
----------------------------------------------------
``IntegrationStore.backup`` copies the live store with the SQLite online backup
API into ``<db dir>/backups/``, checks the copy's integrity and writes a sha256
manifest; ``restore_store`` verifies a backup against its manifest, takes
exclusive custody of the live file, refuses a rollback unless explicitly
accepted, preserves the superseded live content in ``backups/superseded/``,
drops the projections and appends a restore epoch. While an epoch is open new
attempt reservations are refused; ``reconcile`` and ``close_restore_epoch``
resolve it. The mechanics are shared with the effects store through
``integrations/storecore/storecore.py``; the two stores are never backed up or
restored together.

Typed attempt identity (plan leaf E-01.1.1, migration 0003)
-----------------------------------------------------------
``reserve_attempt(identity, intent, actor=...)`` reserves a Work attempt under a typed
``AttemptIdentity``: the Backlog.md task id, the design revision
(``openspec:changes/<change>@<commit>``), the stage, the ordinal, and the profile,
agent-manifest, planned-workspace and policy inputs. The operation key is the
canonical ``attempt/v1/<work_id>/<change>@<commit>/<stage>/<ordinal>``; the
conversation ID stays ``uuid5(CONVERSATION_NAMESPACE, key)`` and the receipt's own
``attempt_id`` is ``uuid5(ATTEMPT_NAMESPACE, key)``. SQLite enforces the key's match
with the typed columns, their immutability, and at most one live (reserved,
dispatched or unknown) attempt per (work, design revision, stage), whatever writes
the rows. ``reserve`` keeps working for opaque keys outside the ``attempt/``
namespace; such rows are untyped.

Migrations are the ordered files ``migrations/NNNN_<name>.sql``. Each runs in the
same transaction as its ``schema_migration`` row (with the sha256 of its
LF-normalised text) and ``PRAGMA user_version``. Opening refuses a database whose
recorded checksums differ from the files, whose version is newer than the files
this code knows, or whose recorded list is inconsistent.

Command line (run from the repository root)::

    python -I -B integrations/store/integration_store.py init --db PATH
    python -I -B integrations/store/integration_store.py default-path
    python -I -B integrations/store/integration_store.py backup --db PATH --actor NAME
    python -I -B integrations/store/integration_store.py restore --db PATH --manifest FILE --actor NAME [--accept-rollback]

``init`` creates or migrates the store at an explicit path and prints a JSON
summary. ``default-path`` only prints the default trusted-host location; it
creates nothing. ``backup`` and ``restore`` print a JSON manifest or report.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import dataclasses
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid
from typing import Callable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MIGRATIONS_DIR = HERE / 'migrations'


def _load_storecore():
    """The shared mechanics module, loaded by path (``python -I`` adds no script dir)."""
    name = 'aieh_storecore'
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, HERE.parent / 'storecore' / 'storecore.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


storecore = _load_storecore()


def _load_planning():
    """The planning adapter (P-02.1), loaded by path for its identifier grammars only."""
    name = 'aieh_store_planning_adapter'
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, HERE.parent / 'planning' / 'planning_adapter.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


planning = _load_planning()

MIN_SQLITE_VERSION = storecore.MIN_SQLITE_VERSION
DEFAULT_BUSY_TIMEOUT_MS = storecore.DEFAULT_BUSY_TIMEOUT_MS

# PRAGMA application_id of an integration store, set by migration 0002 ('AINT').
APPLICATION_ID = 0x41494E54
APPLICATION_ID_SINCE = 2

# Fixed namespace for deterministic conversation IDs. NEVER change it: every
# conversation ID already reserved, and every create already sent with one, is
# derived from it. A test pins a known (operation_key, conversation_id) pair.
CONVERSATION_NAMESPACE = uuid.UUID('7a215c37-e96b-473f-bc67-fa5786423cc1')

STATES = ('reserved', 'dispatched', 'confirmed', 'failed', 'unknown')
TRANSITIONS = frozenset({
    ('reserved', 'dispatched'),
    ('reserved', 'failed'),
    ('dispatched', 'confirmed'),
    ('dispatched', 'failed'),
    ('dispatched', 'unknown'),
    ('unknown', 'confirmed'),
    ('unknown', 'failed'),
})
RECONCILIATION_STATUSES = ('none', 'required', 'reconciled')
TERMINAL_STATES = frozenset({'confirmed', 'failed'})
LIVE_STATES = frozenset(STATES) - TERMINAL_STATES

# Fixed namespace for the attempt receipt's own identity, attempt_id (E-01.1.1).
# Distinct from CONVERSATION_NAMESPACE: the conversation ID is what is sent to the
# external system; attempt_id identifies our receipt. NEVER change it either; a test
# pins a known (operation_key, attempt_id) pair.
ATTEMPT_NAMESPACE = uuid.UUID('078cbf65-575e-463b-9e56-93efe59ba38c')

# Typed attempt identity (migration 0003). STAGES mirrors the attempt_stage table.
STAGES = ('implement', 'review')
KEY_PREFIX = 'attempt/v1/'
IDENTITY_FORMAT = 'attempt-identity/v1'
IDENTITY_INTENT_KEY = 'attemptIdentity'
WORK_REF_KEY = 'workRef'      # the key integrations/lineage reads (lineage_trace.WORK_KEY)
WORK_REF_PREFIX = 'backlog:'
DESIGN_REVISION_PREFIX = 'openspec:changes/'
MAX_WORK_ID = 64
MAX_CHANGE_ID = 128
MAX_WORKSPACE = 255
MAX_ORDINAL = 999999
# agent_manifest_digest is None while no approved agent/Skill catalog exists;
# E-01.2.1 makes it required.
NO_APPROVED_CATALOG = None

# Canonical tables: never dropped, rebuilt or deleted from.
CANONICAL_TABLES = ('schema_migration', 'attempt_state', 'attempt_transition',
                    'reconciliation_status', 'attempt', 'attempt_event',
                    'restore_epoch', 'restore_epoch_closure',
                    'attempt_stage', 'attempt_identity')
# Tables added after the dump format was fixed (F-05.2). An older store has no such
# table and its dump writes no line for it, so a manifest written before migration
# 0003 still verifies (storecore recomputes the canonical digest of a backup).
_CANONICAL_TABLES_SINCE_0003 = frozenset({'attempt_stage', 'attempt_identity'})
PROJECTION_PREFIX = 'proj_'
PROJECTION_CURSOR_TABLE = 'proj_cursor'

_MIGRATION_NAME = re.compile(r'^(\d{4})_([a-z0-9_]+)\.sql$')
_PROJECTION_NAME = re.compile(r'^[a-z][a-z0-9]{0,62}$')


StoreError = storecore.StoreError
UnsupportedSQLite = storecore.UnsupportedSQLite
UnsafeLocation = storecore.UnsafeLocation
MigrationError = storecore.MigrationError
PragmaError = storecore.PragmaError
ProjectionError = storecore.ProjectionError
WrongStoreKind = storecore.WrongStoreKind
BackupError = storecore.BackupError
RestoreRefused = storecore.RestoreRefused
RollbackRefused = storecore.RollbackRefused
RestoreEpochOpen = storecore.RestoreEpochOpen
Migration = storecore.Migration


class ConflictingReservation(StoreError):
    """The operation key is already reserved with a different intent digest."""


class UnknownAttempt(StoreError):
    pass


class IllegalTransition(StoreError):
    pass


class EpochNotReconciled(StoreError):
    """A restore epoch cannot close while an attempt's outcome is still uncertain."""


# The brief's name for a reservation whose key exists with another intent digest.
IntentConflict = ConflictingReservation


class InvalidIdentity(StoreError):
    """A typed attempt identity field, or its intent, does not meet the contract."""


class LiveClaim(StoreError):
    """An attempt on the same work, design revision and stage is still reserved,
    dispatched or unknown; it must reach confirmed or failed (an unknown outcome is
    reconciled first) before another ordinal is reserved."""


class OrdinalOutOfSequence(StoreError):
    """The ordinal is not the next one on its (work, design revision, stage): a gap."""


def _is_sha256_hex(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def valid_work_id(value) -> bool:
    """A canonical (upper-case) Backlog.md task id, by the planning adapter's grammar."""
    return (isinstance(value, str) and 3 <= len(value) <= MAX_WORK_ID and value == value.upper()
            and planning.TASK_ID_RE.fullmatch(value) is not None)


def valid_design_revision(value) -> bool:
    """``openspec:changes/<change>@<commit>``: planning's CHANGE_ID and a full COMMIT."""
    if not isinstance(value, str) or not value.startswith(DESIGN_REVISION_PREFIX):
        return False
    change, sep, commit = value[len(DESIGN_REVISION_PREFIX):].partition('@')
    return (bool(sep) and 1 <= len(change) <= MAX_CHANGE_ID
            and re.fullmatch(planning.CHANGE_ID, change) is not None
            and re.fullmatch(planning.COMMIT, commit) is not None)


def valid_planned_workspace(value) -> bool:
    """A relative identifier by the planning adapter's ARTIFACT_PATH grammar; never a host path."""
    return (isinstance(value, str) and 1 <= len(value) <= MAX_WORKSPACE
            and re.fullmatch(planning.ARTIFACT_PATH, value) is not None)


def design_revision(change: str, commit: str) -> str:
    """The design revision of an OpenSpec change at a full commit."""
    text = f'{DESIGN_REVISION_PREFIX}{change}@{commit}'
    if not valid_design_revision(text):
        raise InvalidIdentity(f'not an OpenSpec change at a full commit: change {change!r}, commit {commit!r}')
    return text


def design_revision_from_pointers(pointers: Sequence[str]) -> str:
    """The design revision a Backlog.md task's OpenSpec source pointers pin.

    Each pointer is parsed by the planning adapter (``Pointer.parse``) and must be in
    its canonical text form; all of them must name the same change at the same commit.
    """
    if isinstance(pointers, str) or not pointers:
        raise InvalidIdentity('a design revision needs at least one OpenSpec source pointer')
    pinned = set()
    for text in pointers:
        try:
            pointer = planning.Pointer.parse(text)
        except planning.PlanningError as exc:
            raise InvalidIdentity(f'{exc.code}: {exc.message}') from None
        if pointer.text != text:
            raise InvalidIdentity(f'not a canonical OpenSpec source pointer: {text!r}')
        pinned.add((pointer.change, pointer.revision))
    if len(pinned) != 1:
        raise InvalidIdentity(f'the pointers pin more than one change or commit: {sorted(pinned)}')
    (change, commit), = pinned
    return design_revision(change, commit)


def attempt_id_for(operation_key: str) -> str:
    """The deterministic attempt ID of a typed attempt's operation key (uuid5)."""
    return str(uuid.uuid5(ATTEMPT_NAMESPACE, operation_key))


@dataclass(frozen=True)
class AttemptIdentity:
    """The typed identity of a Work attempt (blueprint #execution-qualification, step 02).

    The key fields are ``work_id``, ``design_revision``, ``stage`` and ``ordinal``; the
    other fields belong to the intent, so the same key with another profile, manifest,
    workspace or policy is a ConflictingReservation, never a second attempt. A
    ``work_id`` is stored upper case: Backlog.md ids compare without case.
    """
    work_id: str
    design_revision: str
    stage: str
    ordinal: int
    profile_digest: str
    planned_workspace: str
    policy_digest: str
    agent_manifest_digest: str | None = NO_APPROVED_CATALOG

    def __post_init__(self):
        work_id = self.work_id.upper() if isinstance(self.work_id, str) else self.work_id
        if not valid_work_id(work_id):
            raise InvalidIdentity(f'work_id is not a Backlog.md task id (at most {MAX_WORK_ID} characters): '
                                  f'{self.work_id!r}')
        object.__setattr__(self, 'work_id', work_id)
        if not valid_design_revision(self.design_revision):
            raise InvalidIdentity('design_revision must be openspec:changes/<change>@<full commit>: '
                                  f'{self.design_revision!r}')
        if self.stage not in STAGES:
            raise InvalidIdentity(f'stage must be one of {STAGES}: {self.stage!r}')
        if type(self.ordinal) is not int or not 1 <= self.ordinal <= MAX_ORDINAL:
            raise InvalidIdentity(f'ordinal must be an integer from 1 to {MAX_ORDINAL}: {self.ordinal!r}')
        for name in ('profile_digest', 'policy_digest'):
            if not _is_sha256_hex(getattr(self, name)):
                raise InvalidIdentity(f'{name} must be 64 lower-case hex digits (sha256): '
                                      f'{getattr(self, name)!r}')
        if self.agent_manifest_digest is not None and not _is_sha256_hex(self.agent_manifest_digest):
            raise InvalidIdentity('agent_manifest_digest must be 64 lower-case hex digits, or None while no '
                                  f'approved catalog exists: {self.agent_manifest_digest!r}')
        if not valid_planned_workspace(self.planned_workspace):
            raise InvalidIdentity('planned_workspace must be a relative identifier under persistent/workspaces '
                                  f'(path parts [A-Za-z0-9_][A-Za-z0-9._-]*), never a host path: '
                                  f'{self.planned_workspace!r}')

    @property
    def operation_key(self) -> str:
        """``attempt/v1/<work_id>/<change>@<commit>/<stage>/<ordinal>``."""
        return (f'{KEY_PREFIX}{self.work_id}/{self.design_revision[len(DESIGN_REVISION_PREFIX):]}'
                f'/{self.stage}/{self.ordinal}')

    @property
    def work_ref(self) -> str:
        return f'{WORK_REF_PREFIX}{self.work_id}'

    def as_intent(self) -> dict:
        """The identity as it is carried in the reservation's intent."""
        return {'format': IDENTITY_FORMAT, 'work_id': self.work_id, 'design_revision': self.design_revision,
                'stage': self.stage, 'ordinal': self.ordinal, 'profile_digest': self.profile_digest,
                'agent_manifest_digest': self.agent_manifest_digest,
                'planned_workspace': self.planned_workspace, 'policy_digest': self.policy_digest}


@dataclass(frozen=True)
class AttemptRecord:
    """A typed attempt's identity row: the identity, its attempt ID and whether it is live."""
    operation_key: str
    attempt_id: str
    identity: AttemptIdentity
    live: bool


@dataclass(frozen=True)
class Reservation:
    operation_key: str
    intent_digest: str
    intent_json: str
    conversation_id: str
    state: str
    reconciliation_status: str
    state_seq: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ReserveResult:
    reservation: Reservation
    created: bool  # False: an identical reservation already existed (idempotent)


@dataclass(frozen=True)
class AttemptReservation:
    reservation: Reservation
    attempt: AttemptRecord
    created: bool  # False: an identical reservation already existed (idempotent)


@dataclass(frozen=True)
class Event:
    event_id: int
    operation_key: str
    seq: int
    from_state: str | None
    to_state: str
    reconciliation_status: str
    actor: str
    reason: str | None
    detail_json: str | None
    recorded_at: str


@dataclass(frozen=True)
class Projection:
    """A rebuildable projection.

    ``tables`` are the tables it owns, each ``proj_<name>`` or ``proj_<name>_<x>``;
    ``ddl`` creates them; ``populate(conn)`` fills them from the source and returns
    ``(cursor, coverage)``: the source cursor reached and a JSON-serialisable
    coverage description. During a rebuild an SQLite authorizer denies every write
    or schema change outside this projection's own tables and its proj_cursor row.
    """
    name: str
    source: str
    tables: tuple[str, ...]
    ddl: tuple[str, ...]
    populate: Callable[[sqlite3.Connection], tuple[str | None, object]]


# ---------------------------------------------------------------------------
# Helpers

def _now() -> str:
    return storecore.now()


def canonical_intent(intent: Mapping) -> str:
    """Canonical JSON for an intent object: sorted keys, no whitespace, UTF-8."""
    if not isinstance(intent, Mapping):
        raise StoreError('intent must be a JSON object')
    try:
        return storecore.canonical_json(intent)
    except (TypeError, ValueError) as exc:
        raise StoreError(f'intent is not canonical JSON: {exc}') from None


def intent_digest(intent: Mapping) -> str:
    return hashlib.sha256(canonical_intent(intent).encode('utf-8')).hexdigest()


def conversation_id_for(operation_key: str) -> str:
    """The deterministic conversation ID for an operation key (uuid5)."""
    return str(uuid.uuid5(CONVERSATION_NAMESPACE, operation_key))


def sqlite_version() -> str:
    return sqlite3.sqlite_version


check_sqlite_version = storecore.check_sqlite_version
split_statements = storecore.split_statements
write_transaction = storecore.write_transaction
pragmas = storecore.pragmas


def default_db_path(environ: Mapping[str, str] | None = None,
                    platform: str | None = None) -> Path:
    """The default trusted-host location. Computes a path; creates nothing."""
    return storecore.harness_state_root(environ, platform) / 'state' / 'integration.sqlite'


def check_location(path: Path) -> Path:
    """Resolve and vet a database path; refuse locations the blueprint forbids."""
    return storecore.check_local_path(path)


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    return storecore.load_migrations(directory)


# ---------------------------------------------------------------------------
# Store kind: what backup, restore and opening need to know

def _high_water(conn: sqlite3.Connection) -> int:
    """Canonical high-water mark: the last attempt event (events are append-only)."""
    return conn.execute('SELECT coalesce(max(event_id), 0) FROM attempt_event').fetchone()[0]


def _history_digest(conn: sqlite3.Connection, upto: int) -> str:
    """sha256 over the attempt events up to ``upto``, chained row by row."""
    digest = storecore.GENESIS_DIGEST
    for row in conn.execute(f'SELECT {_EVENT_COLUMNS} FROM attempt_event WHERE event_id <= ? '
                            'ORDER BY event_id', (upto,)):
        digest = storecore.sha256_text(digest + '\n' + json.dumps(row, ensure_ascii=True))
    return digest


def _verify_kind_invariants(conn: sqlite3.Connection) -> None:
    bad = conn.execute(
        'SELECT a.operation_key FROM attempt a WHERE a.state_seq <> '
        '(SELECT max(seq) FROM attempt_event e WHERE e.operation_key = a.operation_key) '
        'OR NOT EXISTS (SELECT 1 FROM attempt_event e WHERE e.operation_key = a.operation_key AND e.seq = 0)'
    ).fetchall()
    if bad:
        raise StoreError(f'attempts whose event history does not match their state: {bad[:5]}')
    if conn.execute("SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'attempt_identity'"
                    ).fetchone() is None:
        return
    # The uuid5 derivations are computed here, not in SQL: check every typed row.
    for key, attempt_id, conversation_id, live, state in conn.execute(
            'SELECT i.operation_key, i.attempt_id, a.conversation_id, i.live, a.state '
            'FROM attempt_identity i LEFT JOIN attempt a ON a.operation_key = i.operation_key'):
        if (state is None or attempt_id != attempt_id_for(key) or conversation_id != conversation_id_for(key)
                or live != int(state in LIVE_STATES)):
            raise StoreError(f'typed attempt {key!r} does not match its derived identity or state')
    untyped = conn.execute("SELECT count(*) FROM attempt a WHERE a.operation_key GLOB 'attempt/*' AND NOT EXISTS "
                           '(SELECT 1 FROM attempt_identity i WHERE i.operation_key = a.operation_key)').fetchone()[0]
    if untyped:
        raise StoreError(f'{untyped} attempt(s) in the attempt/ namespace have no typed identity')


def _drop_projections(conn: sqlite3.Connection) -> list[str]:
    """Drop every projection table and clear the cursor; one guarded transaction."""
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name GLOB 'proj_*' "
        f"AND name <> '{PROJECTION_CURSOR_TABLE}' ORDER BY name")]

    def owned(name):
        return bool(name) and name.startswith(PROJECTION_PREFIX) and name != PROJECTION_CURSOR_TABLE

    def owned_index(name):
        return owned(name) or bool(name) and name.startswith('sqlite_autoindex_' + PROJECTION_PREFIX)

    authorizer = storecore.projection_authorizer(owned, owned_index, PROJECTION_CURSOR_TABLE)
    with storecore.guarded_transaction(conn, authorizer, 'projection drop'):
        for table in sorted(tables, reverse=True):
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(f'DELETE FROM {PROJECTION_CURSOR_TABLE}')
    return tables


def _after_restore(conn: sqlite3.Connection, ctx: 'storecore.RestoreContext') -> None:
    """On the staged copy: drop the projections, then append the restore epoch."""
    dropped = _drop_projections(conn)
    manifest = ctx.backup.manifest
    with write_transaction(conn):
        conn.execute(
            'INSERT INTO restore_epoch (backup_manifest_sha256, backup_file, backup_high_water, '
            'backup_history_digest, previous_live_high_water, previous_live_history_digest, '
            'superseded_copy, rollback_accepted, projections_dropped_json, actor, opened_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (ctx.backup.manifest_sha256, manifest['backup_file'], manifest['high_water_mark'],
             manifest['history_digest'], ctx.previous_live_high_water, ctx.previous_live_history_digest,
             ctx.superseded_copy, int(ctx.rollback_accepted), json.dumps(dropped), ctx.actor, ctx.restored_at))


def _canonical_digest(conn: sqlite3.Connection) -> str:
    return hashlib.sha256(_canonical_dump(conn)).hexdigest()


KIND = storecore.StoreKind(
    name='integration', label='an integration store', application_id=APPLICATION_ID,
    application_id_since=APPLICATION_ID_SINCE, db_name='integration.sqlite', migrations_dir=MIGRATIONS_DIR,
    canonical_digest=_canonical_digest, high_water=_high_water, history_digest=_history_digest,
    chain_head=lambda conn: None, verify=_verify_kind_invariants, after_restore=_after_restore)


# ---------------------------------------------------------------------------
# Opening and migrating

def _connect(path: Path, busy_timeout_ms: int) -> sqlite3.Connection:
    return storecore.connect(path, busy_timeout_ms)


def migrate(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations in one transaction; return the names applied."""
    try:
        return storecore.migrate(conn, KIND, migrations_dir)
    except sqlite3.IntegrityError as exc:
        if 'legacy_attempt_keys_in_reserved_attempt_namespace' in str(exc):
            raise MigrationError(
                'migration 0003 refused: untyped attempts already use operation keys in the reserved attempt/ '
                'namespace, so they could not be given a typed identity; nothing was changed. Inspect them with '
                "SELECT operation_key FROM attempt WHERE operation_key GLOB 'attempt/*'") from None
        raise


def open_store(path: os.PathLike | str, *, migrations_dir: Path = MIGRATIONS_DIR,
               busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
               apply_migrations: bool = True) -> 'IntegrationStore':
    """Open (creating if absent) the store at an explicit path.

    The parent directory must already exist. With ``apply_migrations=False`` a
    database with pending migrations is refused instead of migrated. A file of
    another store kind (by ``PRAGMA application_id``) is refused.
    """
    check_sqlite_version()
    resolved = check_location(Path(path))
    if not resolved.parent.is_dir():
        raise UnsafeLocation(f'parent directory does not exist: {resolved.parent}')
    conn = _connect(resolved, busy_timeout_ms)
    try:
        if apply_migrations:
            migrate(conn, migrations_dir)
        else:
            storecore.check_current(conn, KIND, migrations_dir)
    except BaseException:
        conn.close()
        raise
    return IntegrationStore(conn, resolved)


def restore_store(path: os.PathLike | str, manifest: os.PathLike | str, *, actor: str,
                  accept_rollback: bool = False) -> 'storecore.RestoreReport':
    """Restore a verified backup over the store at ``path`` (see storecore.restore_store).

    The superseded live content goes to ``<db dir>/backups/superseded/`` and is
    never deleted; the restored store has an open restore epoch.
    """
    check_sqlite_version()
    resolved = check_location(Path(path))
    if not resolved.parent.is_dir():
        raise UnsafeLocation(f'parent directory does not exist: {resolved.parent}')
    backups = resolved.parent / 'backups'
    superseded, staging = backups / 'superseded', backups / 'staging'
    for directory in (backups, superseded, staging):
        directory.mkdir(mode=0o700, exist_ok=True)
    return storecore.restore_store(resolved, Path(manifest), KIND, actor=actor, accept_rollback=accept_rollback,
                                   superseded_dir=superseded, staging_dir=staging)


# ---------------------------------------------------------------------------
# The store

_ATTEMPT_COLUMNS = ('operation_key, intent_digest, intent_json, conversation_id, state, '
                    'reconciliation_status, state_seq, created_at, updated_at')
_EVENT_COLUMNS = ('event_id, operation_key, seq, from_state, to_state, reconciliation_status, '
                  'actor, reason, detail_json, recorded_at')


class IntegrationStore:
    def __init__(self, conn: sqlite3.Connection, path: Path):
        self.conn = conn
        self.path = path

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> 'IntegrationStore':
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- reads ------------------------------------------------------------

    def schema_version(self) -> int:
        return self.conn.execute('PRAGMA user_version').fetchone()[0]

    def applied_migrations(self) -> list[tuple]:
        return self.conn.execute(
            'SELECT version, name, sha256, applied_at FROM schema_migration ORDER BY version').fetchall()

    def get(self, operation_key: str) -> Reservation | None:
        row = self.conn.execute(f'SELECT {_ATTEMPT_COLUMNS} FROM attempt WHERE operation_key = ?',
                                (operation_key,)).fetchone()
        return Reservation(*row) if row else None

    def events(self, operation_key: str) -> list[Event]:
        rows = self.conn.execute(f'SELECT {_EVENT_COLUMNS} FROM attempt_event '
                                 'WHERE operation_key = ? ORDER BY seq', (operation_key,)).fetchall()
        return [Event(*row) for row in rows]

    def attempts(self, states: Sequence[str] | None = None) -> list[Reservation]:
        sql = f'SELECT {_ATTEMPT_COLUMNS} FROM attempt'
        params: tuple = ()
        if states:
            sql += f' WHERE state IN ({",".join("?" * len(states))})'
            params = tuple(states)
        return [Reservation(*row) for row in self.conn.execute(sql + ' ORDER BY created_at, operation_key', params)]

    # -- writes -----------------------------------------------------------

    def reserve(self, operation_key: str, intent: Mapping, *, actor: str) -> ReserveResult:
        """Reserve an attempt before any external call; one transaction.

        Commits the operation key, the canonical intent and its sha256 digest, and
        the deterministic conversation ID, with a seq-0 event. Reserving an existing
        key with the same digest returns the existing reservation unchanged; with a
        different digest it raises ConflictingReservation and changes nothing.
        While a restore epoch is open a new reservation raises RestoreEpochOpen
        (and a trigger refuses the insert).
        """
        if not isinstance(operation_key, str) or not 1 <= len(operation_key) <= 512:
            raise StoreError('operation_key must be a string of 1 to 512 characters')
        if operation_key.startswith('attempt/'):
            raise InvalidIdentity('the attempt/ key namespace is reserved for typed attempts: use reserve_attempt')
        canonical = canonical_intent(intent)
        digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        with write_transaction(self.conn):
            existing = self.get(operation_key)
            if existing is not None:
                if existing.intent_digest != digest:
                    raise ConflictingReservation(
                        f'operation key {operation_key!r} is already reserved with intent digest '
                        f'{existing.intent_digest}, not {digest}')
                return ReserveResult(existing, created=False)
            open_epochs = self.open_epochs()
            if open_epochs:
                raise RestoreEpochOpen(
                    f'restore epoch {open_epochs[0]["epoch_id"]} is open: new attempt reservations are '
                    'refused until reconciliation closes it')
            self._insert_reservation(operation_key, canonical, digest, actor)
            return ReserveResult(self.get(operation_key), created=True)

    def reserve_attempt(self, identity: AttemptIdentity, intent: Mapping, *, actor: str) -> AttemptReservation:
        """Reserve a typed Work attempt before any external call; one transaction.

        The stored intent is ``intent`` plus ``workRef`` (``backlog:<work_id>``, the key
        the lineage reader follows) and ``attemptIdentity`` (the identity's fields); its
        digest therefore covers the profile, manifest, workspace and policy as well as
        the request. In order, with nothing changed on any refusal:

        * the key exists with the same digest: the existing reservation, ``created=False``;
        * the key exists with another digest: ConflictingReservation (IntentConflict);
        * a restore epoch is open: RestoreEpochOpen;
        * an attempt on the same (work, design revision, stage) is reserved, dispatched
          or unknown: LiveClaim;
        * the ordinal is not the next one on that triple: OrdinalOutOfSequence.

        Every earlier ordinal is then confirmed or failed. Whether a further attempt
        (rework, a fresh review) is warranted, and how many, is the caller's policy.
        SQLite enforces the same rules (migration 0003) for any writer.
        """
        if not isinstance(identity, AttemptIdentity):
            raise InvalidIdentity('identity must be an AttemptIdentity')
        if not isinstance(intent, Mapping):
            raise StoreError('intent must be a JSON object')
        if IDENTITY_INTENT_KEY in intent:
            raise InvalidIdentity(f'the intent key {IDENTITY_INTENT_KEY!r} is reserved for the typed identity')
        if WORK_REF_KEY in intent and intent[WORK_REF_KEY] != identity.work_ref:
            raise InvalidIdentity(f'intent {WORK_REF_KEY} {intent[WORK_REF_KEY]!r} does not name the attempt\'s '
                                  f'work {identity.work_ref!r}')
        storecore._check_actor(actor)
        key = identity.operation_key
        canonical = canonical_intent({**intent, WORK_REF_KEY: identity.work_ref,
                                      IDENTITY_INTENT_KEY: identity.as_intent()})
        digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        with write_transaction(self.conn):
            existing = self.get(key)
            if existing is not None:
                if existing.intent_digest != digest:
                    raise ConflictingReservation(
                        f'operation key {key!r} is already reserved with intent digest '
                        f'{existing.intent_digest}, not {digest}')
                return AttemptReservation(existing, self.attempt_identity(key), created=False)
            open_epochs = self.open_epochs()
            if open_epochs:
                raise RestoreEpochOpen(
                    f'restore epoch {open_epochs[0]["epoch_id"]} is open: new attempt reservations are '
                    'refused until reconciliation closes it')
            triple = (identity.work_id, identity.design_revision, identity.stage)
            live = self.conn.execute(
                'SELECT i.operation_key, a.state FROM attempt_identity i JOIN attempt a USING (operation_key) '
                'WHERE i.work_id = ? AND i.design_revision = ? AND i.stage = ? AND i.live = 1', triple).fetchone()
            if live is not None:
                raise LiveClaim(f'{live[0]!r} is {live[1]}: no other attempt on this work, design revision and '
                                'stage is reserved until it is confirmed or failed (reconcile an unknown outcome '
                                'first)')
            highest = self.conn.execute(
                'SELECT coalesce(max(ordinal), 0) FROM attempt_identity '
                'WHERE work_id = ? AND design_revision = ? AND stage = ?', triple).fetchone()[0]
            if identity.ordinal != highest + 1:
                raise OrdinalOutOfSequence(f'ordinal {identity.ordinal} on this work, design revision and stage: '
                                           f'the next ordinal is {highest + 1}')
            self.conn.execute(
                'INSERT INTO attempt_identity (operation_key, attempt_id, work_id, design_revision, stage, '
                'ordinal, profile_digest, agent_manifest_digest, planned_workspace, policy_digest, live) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)',
                (key, attempt_id_for(key), identity.work_id, identity.design_revision, identity.stage,
                 identity.ordinal, identity.profile_digest, identity.agent_manifest_digest,
                 identity.planned_workspace, identity.policy_digest))
            self._insert_reservation(key, canonical, digest, actor)
            return AttemptReservation(self.get(key), self.attempt_identity(key), created=True)

    def attempt_identity(self, operation_key: str) -> AttemptRecord | None:
        """The typed identity of an attempt, or None for an untyped (legacy) one."""
        row = self.conn.execute(
            'SELECT operation_key, attempt_id, work_id, design_revision, stage, ordinal, profile_digest, '
            'planned_workspace, policy_digest, agent_manifest_digest, live FROM attempt_identity '
            'WHERE operation_key = ?', (operation_key,)).fetchone()
        if row is None:
            return None
        return AttemptRecord(row[0], row[1], AttemptIdentity(*row[2:10]), bool(row[10]))

    def identity_form(self, operation_key: str) -> str | None:
        """'typed' or 'legacy-untyped' (the attempt_typing view); None when no such attempt."""
        row = self.conn.execute('SELECT identity_form FROM attempt_typing WHERE operation_key = ?',
                                (operation_key,)).fetchone()
        return row and row[0]

    def claims(self, work_id: str, design_revision_text: str, stage: str) -> list[AttemptRecord]:
        """Every typed attempt on one (work, design revision, stage), by ordinal."""
        keys = self.conn.execute(
            'SELECT operation_key FROM attempt_identity WHERE work_id = ? AND design_revision = ? AND stage = ? '
            'ORDER BY ordinal', (work_id.upper() if isinstance(work_id, str) else work_id,
                                 design_revision_text, stage)).fetchall()
        return [self.attempt_identity(k) for (k,) in keys]

    def _insert_reservation(self, operation_key: str, canonical: str, digest: str, actor: str) -> None:
        """Insert the reservation row and its seq-0 event. Caller owns the transaction."""
        now = _now()
        self.conn.execute(
            'INSERT INTO attempt (operation_key, intent_digest, intent_json, conversation_id, '
            'state, reconciliation_status, state_seq, created_at, updated_at) '
            "VALUES (?, ?, ?, ?, 'reserved', 'none', 0, ?, ?)",
            (operation_key, digest, canonical, conversation_id_for(operation_key), now, now))
        self.conn.execute(
            'INSERT INTO attempt_event (operation_key, seq, from_state, to_state, '
            'reconciliation_status, actor, reason, detail_json, recorded_at) '
            "VALUES (?, 0, NULL, 'reserved', 'none', ?, 'reserved', NULL, ?)",
            (operation_key, actor, now))

    def transition(self, operation_key: str, to_state: str, *, actor: str,
                   reason: str | None = None, detail: Mapping | None = None,
                   expected_from: str | None = None) -> Reservation:
        """Move an attempt to ``to_state`` and append the event; one transaction.

        Refuses (IllegalTransition, nothing changed) a pair outside TRANSITIONS, or
        a current state other than ``expected_from`` when that is given. Entering
        ``unknown`` sets reconciliation_status 'required'; leaving it sets
        'reconciled'.
        """
        if to_state not in STATES:
            raise IllegalTransition(f'unknown state {to_state!r}')
        detail_json = None if detail is None else canonical_intent(detail)
        with write_transaction(self.conn):
            current = self.get(operation_key)
            if current is None:
                raise UnknownAttempt(f'no attempt reserved under {operation_key!r}')
            if expected_from is not None and current.state != expected_from:
                raise IllegalTransition(
                    f'{operation_key!r} is {current.state}, not the expected {expected_from}')
            if (current.state, to_state) not in TRANSITIONS:
                raise IllegalTransition(f'{current.state} -> {to_state} is not allowed')
            if to_state == 'unknown':
                status = 'required'
            elif current.state == 'unknown':
                status = 'reconciled'
            else:
                status = current.reconciliation_status
            seq = current.state_seq + 1
            now = _now()
            self.conn.execute(
                'UPDATE attempt SET state = ?, reconciliation_status = ?, state_seq = ?, updated_at = ? '
                'WHERE operation_key = ? AND state_seq = ?',
                (to_state, status, seq, now, operation_key, current.state_seq))
            self.conn.execute(
                'INSERT INTO attempt_event (operation_key, seq, from_state, to_state, '
                'reconciliation_status, actor, reason, detail_json, recorded_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (operation_key, seq, current.state, to_state, status, actor, reason, detail_json, now))
            return self.get(operation_key)

    # -- projections ------------------------------------------------------

    def rebuild_projection(self, projection: Projection) -> None:
        """Drop and recreate one projection's tables from its source; one transaction.

        Only that projection's own ``proj_`` tables and its ``proj_cursor`` row can
        change: an SQLite authorizer denies every other write and schema change for
        the duration, and any failure rolls the whole rebuild back.
        """
        _validate_projection(projection)
        own = f'{PROJECTION_PREFIX}{projection.name}'

        def owned(table: str | None) -> bool:
            return bool(table) and (table == own or table.startswith(own + '_'))

        def owned_index(index: str | None) -> bool:
            return owned(index) or bool(index) and index.startswith('sqlite_autoindex_' + own)

        authorizer = storecore.projection_authorizer(owned, owned_index, PROJECTION_CURSOR_TABLE)
        conn = self.conn
        with storecore.guarded_transaction(conn, authorizer, f'rebuild of {projection.name!r}'):
            for table in reversed(projection.tables):
                conn.execute(f'DROP TABLE IF EXISTS "{table}"')
            conn.execute(f'DELETE FROM {PROJECTION_CURSOR_TABLE} WHERE projection = ?',
                         (projection.name,))
            for statement in projection.ddl:
                conn.execute(statement)
            cursor, coverage = projection.populate(conn)
            conn.execute(f'INSERT INTO {PROJECTION_CURSOR_TABLE} '
                         '(projection, source, cursor, coverage_json, rebuilt_at) VALUES (?, ?, ?, ?, ?)',
                         (projection.name, projection.source, cursor,
                          json.dumps(coverage, sort_keys=True, separators=(',', ':')), _now()))

    def projection_cursor(self, name: str) -> tuple | None:
        return self.conn.execute(
            f'SELECT projection, source, cursor, coverage_json, rebuilt_at FROM {PROJECTION_CURSOR_TABLE} '
            'WHERE projection = ?', (name,)).fetchone()

    # -- backup, restore epochs and reconciliation (F-05.2) ---------------

    def backup(self, *, actor: str, backup_dir: Path | None = None) -> dict:
        """Back up this store into ``<db dir>/backups/`` (or ``backup_dir``); return the manifest.

        The SQLite online backup API, an integrity check on the copy and a sha256
        manifest (storecore.backup_store). Never a copy of the live files.
        """
        target = Path(backup_dir) if backup_dir is not None else self.path.parent / 'backups'
        if backup_dir is None:
            target.mkdir(mode=0o700, exist_ok=True)
        return storecore.backup_store(self.conn, KIND, target, actor=actor)

    def high_water_mark(self) -> int:
        return _high_water(self.conn)

    def history_digest(self) -> str:
        return _history_digest(self.conn, _high_water(self.conn))

    def open_epochs(self) -> list[dict]:
        """Restore epochs without a closure, oldest first (none before migration 0002)."""
        if self.conn.execute("SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'restore_epoch'"
                             ).fetchone() is None:
            return []
        cursor = self.conn.execute(
            'SELECT * FROM restore_epoch e WHERE NOT EXISTS '
            '(SELECT 1 FROM restore_epoch_closure c WHERE c.epoch_id = e.epoch_id) ORDER BY epoch_id')
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def reconcile(self, oracle: Callable[[Reservation], str], *, actor: str) -> dict:
        """Resolve attempts whose outcome a restore (or a lost acknowledgement) made uncertain.

        While a restore epoch is open, every ``dispatched`` attempt first moves to
        ``unknown`` (the restore may have lost its outcome). Then, for every
        ``unknown`` attempt, ``oracle(reservation)`` reports what the external
        system shows: ``'performed'`` -> ``confirmed``, ``'not_performed'`` ->
        ``failed``, ``'indeterminate'`` -> stays ``unknown`` and nothing else is
        done for it. Uses only the F-05.1 transitions. The real oracle (the
        OpenHands conversation lookup) is E-01.4.x; tests use a fixture.
        """
        report = {'confirmed': [], 'failed': [], 'still_unknown': []}
        if self.open_epochs():
            for attempt in self.attempts(['dispatched']):
                self.transition(attempt.operation_key, 'unknown', actor=actor, expected_from='dispatched',
                                reason='restore epoch: outcome uncertain after restore')
        for attempt in self.attempts(['unknown']):
            verdict = oracle(attempt)
            if verdict == 'performed':
                self.transition(attempt.operation_key, 'confirmed', actor=actor, expected_from='unknown',
                                reason='reconciled: observed in the external system')
                report['confirmed'].append(attempt.operation_key)
            elif verdict == 'not_performed':
                self.transition(attempt.operation_key, 'failed', actor=actor, expected_from='unknown',
                                reason='reconciled: not present in the external system')
                report['failed'].append(attempt.operation_key)
            elif verdict == 'indeterminate':
                report['still_unknown'].append(attempt.operation_key)
            else:
                raise StoreError(f'oracle verdict must be performed, not_performed or indeterminate: {verdict!r}')
        return report

    def close_restore_epoch(self, *, actor: str, summary: Mapping | None = None) -> list[int]:
        """Close every open restore epoch once no attempt is ``dispatched`` or ``unknown``.

        ``reserved`` attempts may stay: their conversation ID is deterministic, so
        dispatching them again cannot create a second conversation (decision 0001).
        Returns the epoch IDs closed; raises EpochNotReconciled otherwise.
        """
        storecore._check_actor(actor)
        detail = canonical_intent(summary or {})
        with write_transaction(self.conn):
            epochs = self.open_epochs()
            if not epochs:
                raise StoreError('no restore epoch is open')
            uncertain = self.attempts(['dispatched', 'unknown'])
            if uncertain:
                raise EpochNotReconciled(
                    f'{len(uncertain)} attempt(s) still dispatched or unknown: '
                    f'{[a.operation_key for a in uncertain][:10]}; reconcile them first')
            closed_at = _now()
            body = json.dumps({'reconciliation': json.loads(detail),
                               'attempt_states': dict(self.conn.execute(
                                   'SELECT state, count(*) FROM attempt GROUP BY state').fetchall())},
                              sort_keys=True, separators=(',', ':'))
            for epoch in epochs:
                self.conn.execute('INSERT INTO restore_epoch_closure (epoch_id, actor, closed_at, summary_json) '
                                  'VALUES (?, ?, ?, ?)', (epoch['epoch_id'], actor, closed_at, body))
            return [e['epoch_id'] for e in epochs]

    def prune_backups(self, *, keep_last: int, older_than_days: float | None = None,
                      backup_dir: Path | None = None) -> list[str]:
        """Retention: delete old backups, never the newest, never an open epoch's source."""
        target = Path(backup_dir) if backup_dir is not None else self.path.parent / 'backups'
        protected = [e['backup_file'] for e in self.open_epochs()]
        return storecore.prune_backups(target, KIND, keep_last=keep_last, older_than_days=older_than_days,
                                       protected=protected)

    # -- evidence ---------------------------------------------------------

    def canonical_dump(self) -> bytes:
        """A deterministic dump of every canonical table: schema SQL and all rows."""
        return _canonical_dump(self.conn)

    def summary(self) -> dict:
        tables = [r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' ORDER BY name")]
        return {
            'path': str(self.path),
            'store_kind': KIND.name,
            'application_id': self.conn.execute('PRAGMA application_id').fetchone()[0],
            'sqlite_version': sqlite3.sqlite_version,
            'schema_version': self.schema_version(),
            'migrations': [{'version': v, 'name': n, 'sha256': s} for v, n, s, _ in self.applied_migrations()],
            'pragmas': pragmas(self.conn),
            'canonical_tables': [t for t in tables if t in CANONICAL_TABLES],
            'projection_tables': [t for t in tables if t.startswith(PROJECTION_PREFIX)],
            'attempts': self.conn.execute('SELECT count(*) FROM attempt').fetchone()[0],
            'typed_attempts': (self.conn.execute('SELECT count(*) FROM attempt_identity').fetchone()[0]
                               if 'attempt_identity' in tables else 0),
            'high_water_mark': self.high_water_mark(),
            'open_restore_epochs': [e['epoch_id'] for e in self.open_epochs()],
        }


def _canonical_dump(conn: sqlite3.Connection) -> bytes:
    """A deterministic dump of every canonical table: schema SQL and all rows."""
    lines = []
    for table in CANONICAL_TABLES:
        sql = conn.execute("SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = ?",
                           (table,)).fetchone()
        if sql is None and table in _CANONICAL_TABLES_SINCE_0003:
            continue  # keeps the dump, and so the digest, of an older store unchanged
        lines.append(f'-- {table}: {sql[0] if sql else None}')
        if sql is None:
            continue
        for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY 1, 2'):
            lines.append(json.dumps([[type(v).__name__, v] for v in row], ensure_ascii=True))
    objects = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema "
        f"WHERE name NOT GLOB '{PROJECTION_PREFIX}*' AND tbl_name NOT GLOB '{PROJECTION_PREFIX}*' "
        "AND name <> 'sqlite_sequence' ORDER BY type, name").fetchall()
    lines.append(json.dumps(objects, ensure_ascii=True))
    return '\n'.join(lines).encode('utf-8')


def _validate_projection(projection: Projection) -> None:
    if not _PROJECTION_NAME.match(projection.name) or projection.name == 'cursor':
        raise ProjectionError(f'projection name must match {_PROJECTION_NAME.pattern} '
                              f'and not be "cursor": {projection.name!r}')
    own = f'{PROJECTION_PREFIX}{projection.name}'
    if not projection.tables:
        raise ProjectionError('a projection owns at least one table')
    for table in projection.tables:
        if not (table == own or (table.startswith(own + '_') and re.fullmatch(r'[a-z0-9_]+', table))):
            raise ProjectionError(f'projection {projection.name!r} may only own {own} or {own}_*: {table!r}')


# ---------------------------------------------------------------------------
# Command line

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='integration_store.py', description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init', help='create or migrate the store at an explicit path; print a JSON summary')
    init.add_argument('--db', required=True, help='database file path (its parent directory is created)')
    sub.add_parser('default-path', help='print the default trusted-host location; creates nothing')
    backup = sub.add_parser('backup', help='back up the store at an explicit path into <db dir>/backups/; '
                                           'print the manifest')
    backup.add_argument('--db', required=True, help='existing database file path')
    backup.add_argument('--actor', required=True, help='who takes the backup (recorded in the manifest)')
    restore = sub.add_parser('restore', help='restore a verified backup over the store; print the report')
    restore.add_argument('--db', required=True, help='database file path (its directory must exist)')
    restore.add_argument('--manifest', required=True, help='the backup manifest (<backup>.manifest.json)')
    restore.add_argument('--actor', required=True, help='who restores (recorded in the restore epoch)')
    restore.add_argument('--accept-rollback', action='store_true',
                         help='explicitly accept losing live history that is ahead of or diverges from the backup '
                              '(the live content is still preserved aside)')
    args = parser.parse_args(argv)

    if args.command == 'default-path':
        try:
            print(default_db_path())
        except StoreError as exc:
            print(f'REFUSED: {exc}', file=sys.stderr)
            return 1
        return 0

    if args.command == 'backup':
        try:
            target = check_location(Path(args.db))
            if not target.is_file():
                raise UnsafeLocation(f'no store at {target}')
            with open_store(target, apply_migrations=False) as store:
                print(json.dumps(store.backup(actor=args.actor), indent=2, sort_keys=True))
        except StoreError as exc:
            print(f'REFUSED: {exc}', file=sys.stderr)
            return 1
        return 0

    if args.command == 'restore':
        try:
            report = restore_store(args.db, args.manifest, actor=args.actor, accept_rollback=args.accept_rollback)
            with open_store(args.db) as store:
                print(json.dumps({'restore': dataclasses.asdict(report), 'store': store.summary()},
                                 indent=2, sort_keys=True))
        except StoreError as exc:
            print(f'REFUSED: {exc}', file=sys.stderr)
            return 1
        return 0

    try:
        check_sqlite_version()
        target = check_location(Path(args.db))
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open_store(target) as store:
            print(json.dumps(store.summary(), indent=2))
    except StoreError as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
