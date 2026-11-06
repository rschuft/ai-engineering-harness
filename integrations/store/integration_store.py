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

Migrations are the ordered files ``migrations/NNNN_<name>.sql``. Each runs in the
same transaction as its ``schema_migration`` row (with the sha256 of its
LF-normalised text) and ``PRAGMA user_version``. Opening refuses a database whose
recorded checksums differ from the files, whose version is newer than the files
this code knows, or whose recorded list is inconsistent.

Command line (run from the repository root)::

    python -I -B integrations/store/integration_store.py init --db PATH
    python -I -B integrations/store/integration_store.py default-path

``init`` creates or migrates the store at an explicit path and prints a JSON
summary. ``default-path`` only prints the default trusted-host location; it
creates nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid
from typing import Callable, Iterator, Mapping, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MIGRATIONS_DIR = HERE / 'migrations'

# STRICT tables need SQLite 3.37.0; JSON functions built in by default need 3.38.0.
MIN_SQLITE_VERSION = (3, 38, 0)
DEFAULT_BUSY_TIMEOUT_MS = 10_000

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

# Canonical tables: never dropped, rebuilt or deleted from.
CANONICAL_TABLES = ('schema_migration', 'attempt_state', 'attempt_transition',
                    'reconciliation_status', 'attempt', 'attempt_event')
PROJECTION_PREFIX = 'proj_'
PROJECTION_CURSOR_TABLE = 'proj_cursor'

_MIGRATION_NAME = re.compile(r'^(\d{4})_([a-z0-9_]+)\.sql$')
_PROJECTION_NAME = re.compile(r'^[a-z][a-z0-9]{0,62}$')


class StoreError(Exception):
    """Base class: the store refused an operation; nothing was changed."""


class UnsupportedSQLite(StoreError):
    pass


class UnsafeLocation(StoreError):
    pass


class MigrationError(StoreError):
    pass


class PragmaError(StoreError):
    pass


class ConflictingReservation(StoreError):
    """The operation key is already reserved with a different intent digest."""


class UnknownAttempt(StoreError):
    pass


class IllegalTransition(StoreError):
    pass


class ProjectionError(StoreError):
    pass


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
class Migration:
    version: int
    name: str
    path: Path
    sha256: str
    text: str


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
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def canonical_intent(intent: Mapping) -> str:
    """Canonical JSON for an intent object: sorted keys, no whitespace, UTF-8."""
    if not isinstance(intent, Mapping):
        raise StoreError('intent must be a JSON object')
    try:
        return json.dumps(intent, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise StoreError(f'intent is not canonical JSON: {exc}') from None


def intent_digest(intent: Mapping) -> str:
    return hashlib.sha256(canonical_intent(intent).encode('utf-8')).hexdigest()


def conversation_id_for(operation_key: str) -> str:
    """The deterministic conversation ID for an operation key (uuid5)."""
    return str(uuid.uuid5(CONVERSATION_NAMESPACE, operation_key))


def sqlite_version() -> str:
    return sqlite3.sqlite_version


def check_sqlite_version() -> None:
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        need = '.'.join(map(str, MIN_SQLITE_VERSION))
        raise UnsupportedSQLite(
            f'SQLite {sqlite3.sqlite_version} is too old: the store needs {need} or newer '
            '(STRICT tables and built-in JSON functions)')


def default_db_path(environ: Mapping[str, str] | None = None,
                    platform: str | None = None) -> Path:
    """The default trusted-host location. Computes a path; creates nothing."""
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    if plat == 'win32':
        base = env.get('LOCALAPPDATA')
        if not base:
            raise UnsafeLocation('LOCALAPPDATA is not set; pass an explicit --db path')
        return Path(base) / 'ai-engineering-harness' / 'state' / 'integration.sqlite'
    base = env.get('XDG_DATA_HOME') or str(Path(env.get('HOME') or Path.home()) / '.local' / 'share')
    return Path(base) / 'ai-engineering-harness' / 'state' / 'integration.sqlite'


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def check_location(path: Path) -> Path:
    """Resolve and vet a database path; refuse locations the blueprint forbids."""
    raw = str(path)
    if raw in ('', ':memory:') or raw.startswith('file:'):
        raise UnsafeLocation('the store must be a file path on local disk')
    if raw.startswith(('\\\\', '//')):
        raise UnsafeLocation(f'network (UNC) path refused: {raw}')
    resolved = Path(os.path.abspath(path))
    if _is_within(resolved, REPO.resolve()):
        raise UnsafeLocation(f'the store must not be inside the repository checkout: {resolved}')
    if sys.platform == 'win32':
        import ctypes
        drive = os.path.splitdrive(str(resolved))[0]
        if drive.startswith('\\\\'):
            raise UnsafeLocation(f'network (UNC) path refused: {resolved}')
        drive_remote = 4
        if ctypes.windll.kernel32.GetDriveTypeW(drive + '\\') == drive_remote:
            raise UnsafeLocation(f'network drive refused: {resolved}')
    return resolved


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found = []
    for entry in sorted(Path(directory).iterdir()):
        if entry.suffix != '.sql':
            continue
        match = _MIGRATION_NAME.match(entry.name)
        if not match:
            raise MigrationError(f'migration file name not NNNN_<name>.sql: {entry.name}')
        text = entry.read_bytes().decode('utf-8').replace('\r\n', '\n')
        found.append(Migration(int(match.group(1)), entry.name, entry,
                               hashlib.sha256(text.encode('utf-8')).hexdigest(), text))
    versions = [m.version for m in found]
    if versions != list(range(1, len(found) + 1)):
        raise MigrationError(f'migration versions must run 1..N without gaps: {versions}')
    return found


def split_statements(text: str) -> list[str]:
    """Split an SQL script into complete statements (trigger bodies stay whole).

    ``executescript`` is not used because it commits any open transaction first.
    """
    statements, pending = [], ''
    for piece in text.split(';'):
        pending += piece + ';'
        if sqlite3.complete_statement(pending):
            body = pending.strip()
            if _strip_comments(body).strip(' \n\t;'):
                statements.append(body)
            pending = ''
    if _strip_comments(pending).strip(' \n\t;'):
        raise MigrationError('migration ends with an incomplete statement')
    return statements


def _strip_comments(sql: str) -> str:
    return '\n'.join(line for line in sql.splitlines() if not line.strip().startswith('--'))


@contextlib.contextmanager
def write_transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """One ``BEGIN IMMEDIATE`` transaction: commit on success, roll back on any error."""
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise
    conn.execute('COMMIT')


# ---------------------------------------------------------------------------
# Opening and migrating

def _connect(path: Path, busy_timeout_ms: int) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=busy_timeout_ms / 1000)
    try:
        conn.execute(f'PRAGMA busy_timeout = {int(busy_timeout_ms)}')
        conn.execute('PRAGMA foreign_keys = ON')
        mode = conn.execute('PRAGMA journal_mode = WAL').fetchone()[0]
        conn.execute('PRAGMA synchronous = FULL')
        observed = pragmas(conn)
        expected = {'journal_mode': 'wal', 'synchronous': 2, 'foreign_keys': 1,
                    'busy_timeout': int(busy_timeout_ms)}
        if mode.lower() != 'wal' or observed != expected:
            raise PragmaError(f'connection did not take the required pragmas: {observed}')
    except BaseException:
        conn.close()
        raise
    return conn


def pragmas(conn: sqlite3.Connection) -> dict:
    return {
        'journal_mode': conn.execute('PRAGMA journal_mode').fetchone()[0].lower(),
        'synchronous': conn.execute('PRAGMA synchronous').fetchone()[0],
        'foreign_keys': conn.execute('PRAGMA foreign_keys').fetchone()[0],
        'busy_timeout': conn.execute('PRAGMA busy_timeout').fetchone()[0],
    }


def _verify_applied(conn: sqlite3.Connection, known: Sequence[Migration]) -> int:
    """Check the recorded migrations against the files; return the database version."""
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    if version > len(known):
        raise MigrationError(
            f'database schema version {version} is newer than this code knows ({len(known)}); refusing to open')
    if version == 0:
        objects = conn.execute(
            "SELECT count(*) FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'").fetchone()[0]
        if objects:
            raise MigrationError('database has user_version 0 but already holds objects; '
                                 'it is not an integration store')
        return 0
    rows = conn.execute('SELECT version, name, sha256 FROM schema_migration ORDER BY version').fetchall()
    if [r[0] for r in rows] != list(range(1, version + 1)):
        raise MigrationError(
            f'recorded migrations {[r[0] for r in rows]} do not match user_version {version}')
    for (v, name, digest), migration in zip(rows, known):
        if name != migration.name or digest != migration.sha256:
            raise MigrationError(
                f'applied migration {v} ({name}) has changed: recorded sha256 {digest}, '
                f'file {migration.name} sha256 {migration.sha256}; refusing to open')
    return version


def migrate(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations in one transaction; return the names applied."""
    known = load_migrations(migrations_dir)
    applied = []
    with write_transaction(conn):
        version = _verify_applied(conn, known)
        for migration in known[version:]:
            for statement in split_statements(migration.text):
                conn.execute(statement)
            conn.execute('INSERT INTO schema_migration (version, name, sha256, applied_at) '
                         'VALUES (?, ?, ?, ?)',
                         (migration.version, migration.name, migration.sha256, _now()))
            conn.execute(f'PRAGMA user_version = {migration.version}')
            applied.append(migration.name)
        violations = conn.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            raise MigrationError(f'foreign key violations after migration: {violations}')
    return applied


def open_store(path: os.PathLike | str, *, migrations_dir: Path = MIGRATIONS_DIR,
               busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
               apply_migrations: bool = True) -> 'IntegrationStore':
    """Open (creating if absent) the store at an explicit path.

    The parent directory must already exist. With ``apply_migrations=False`` a
    database with pending migrations is refused instead of migrated.
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
            known = load_migrations(migrations_dir)
            conn.execute('BEGIN')
            try:
                version = _verify_applied(conn, known)
            finally:
                conn.execute('ROLLBACK')
            if version != len(known):
                raise MigrationError(f'database is at version {version}; {len(known)} expected')
    except BaseException:
        conn.close()
        raise
    return IntegrationStore(conn, resolved)


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
        """
        if not isinstance(operation_key, str) or not 1 <= len(operation_key) <= 512:
            raise StoreError('operation_key must be a string of 1 to 512 characters')
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
            self._insert_reservation(operation_key, canonical, digest, actor)
            return ReserveResult(self.get(operation_key), created=True)

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

        def authorize(action, arg1, arg2, db, _trigger):
            allowed = sqlite3.SQLITE_OK
            if action in (sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT,
                          sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE):
                return allowed
            if action == sqlite3.SQLITE_PRAGMA:  # FTS5 reads it internally
                return allowed if (arg1, arg2) == ('data_version', None) else sqlite3.SQLITE_DENY
            if db != 'main':
                return sqlite3.SQLITE_DENY
            if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                # sqlite_master writes happen only as part of DDL, which is checked
                # by name below; writable_schema would need a (denied) PRAGMA.
                if owned(arg1) or arg1 in (PROJECTION_CURSOR_TABLE, 'sqlite_master', 'sqlite_sequence'):
                    return allowed
                return sqlite3.SQLITE_DENY
            if action in (sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE,
                          sqlite3.SQLITE_CREATE_VTABLE, sqlite3.SQLITE_DROP_VTABLE):
                return allowed if owned(arg1) else sqlite3.SQLITE_DENY
            if action in (sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_DROP_INDEX):
                return allowed if owned(arg2) and owned_index(arg1) else sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_REINDEX:  # issued internally by CREATE INDEX
                return allowed if owned_index(arg1) else sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_ALTER_TABLE:
                return allowed if owned(arg2) else sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_DENY  # triggers, views, temp objects, attach, transactions...

        conn = self.conn
        conn.execute('BEGIN IMMEDIATE')
        try:
            conn.set_authorizer(authorize)
            try:
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
            finally:
                conn.set_authorizer(None)
        except sqlite3.DatabaseError as exc:
            conn.execute('ROLLBACK')
            raise ProjectionError(f'rebuild of {projection.name!r} refused and rolled back: {exc}') from exc
        except BaseException:
            if conn.in_transaction:
                conn.execute('ROLLBACK')
            raise
        conn.execute('COMMIT')

    def projection_cursor(self, name: str) -> tuple | None:
        return self.conn.execute(
            f'SELECT projection, source, cursor, coverage_json, rebuilt_at FROM {PROJECTION_CURSOR_TABLE} '
            'WHERE projection = ?', (name,)).fetchone()

    # -- evidence ---------------------------------------------------------

    def canonical_dump(self) -> bytes:
        """A deterministic dump of every canonical table: schema SQL and all rows."""
        lines = []
        for table in CANONICAL_TABLES:
            sql = self.conn.execute("SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = ?",
                                    (table,)).fetchone()
            lines.append(f'-- {table}: {sql[0] if sql else None}')
            for row in self.conn.execute(f'SELECT * FROM "{table}" ORDER BY 1, 2'):
                lines.append(json.dumps([[type(v).__name__, v] for v in row], ensure_ascii=True))
        objects = self.conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema "
            f"WHERE name NOT GLOB '{PROJECTION_PREFIX}*' AND tbl_name NOT GLOB '{PROJECTION_PREFIX}*' "
            "AND name <> 'sqlite_sequence' ORDER BY type, name").fetchall()
        lines.append(json.dumps(objects, ensure_ascii=True))
        return '\n'.join(lines).encode('utf-8')

    def summary(self) -> dict:
        tables = [r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' ORDER BY name")]
        return {
            'path': str(self.path),
            'sqlite_version': sqlite3.sqlite_version,
            'schema_version': self.schema_version(),
            'migrations': [{'version': v, 'name': n, 'sha256': s} for v, n, s, _ in self.applied_migrations()],
            'pragmas': pragmas(self.conn),
            'canonical_tables': [t for t in tables if t in CANONICAL_TABLES],
            'projection_tables': [t for t in tables if t.startswith(PROJECTION_PREFIX)],
            'attempts': self.conn.execute('SELECT count(*) FROM attempt').fetchone()[0],
        }


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
    args = parser.parse_args(argv)

    if args.command == 'default-path':
        try:
            print(default_db_path())
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
