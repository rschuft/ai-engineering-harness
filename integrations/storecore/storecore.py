"""Shared SQLite mechanics for the harness's local stores.

Plan leaves F-05.1 and F-05.2, blueprint section #infrastructure-state, decision
0004. Python standard library only. Two stores use this module and nothing else
joins them:

* ``integrations/store/integration_store.py``: the Integration Service's
  ``integration.sqlite`` (coordination receipts and rebuildable projections);
* ``integrations/effects/effects_store.py``: the privileged executor's
  ``effects.sqlite`` (effect receipts and their hash-chained journal).

Each store keeps its own schema, migration line, ``PRAGMA application_id``, backup
line and location rules. This module holds only the mechanics they share:

* the connection policy (WAL, ``synchronous=FULL``, ``foreign_keys=ON``, a busy
  timeout, each read back; ``ATTACH`` impossible because the attached-database
  limit is 0 on every connection);
* the migration ledger (ordered ``NNNN_<name>.sql`` files, sha256 of the
  LF-normalised text, ``user_version``, the store kind's ``application_id``);
* ``BEGIN IMMEDIATE`` write transactions;
* the authorizer that confines a projection rebuild to its own tables;
* backup with the SQLite online backup API, an integrity check and a sha256
  manifest; verification of a backup against its manifest; restore under
  exclusive custody, with the superseded live content preserved aside, a
  rollback refusal and a single atomic replacement of the live file.

There is no command line here; each store has its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Callable, Iterator, Mapping, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

# STRICT tables need SQLite 3.37.0; JSON functions built in by default need 3.38.0.
MIN_SQLITE_VERSION = (3, 38, 0)
DEFAULT_BUSY_TIMEOUT_MS = 10_000
# Restore takes exclusive custody of the live file or refuses; this bounds the wait.
EXCLUSIVE_TIMEOUT_MS = 500

MANIFEST_FORMAT = 'aieh-store-backup/1'
SUPERSEDED_FORMAT = 'aieh-store-superseded/1'
BACKUP_METHOD = 'sqlite3.Connection.backup (SQLite online backup API)'
GENESIS_DIGEST = '0' * 64

_MIGRATION_NAME = re.compile(r'^(\d{4})_([a-z0-9_]+)\.sql$')
_BACKUP_NAME = re.compile(r'^[a-z]+-\d{8}T\d{6}\d{6}Z-hw\d{10}\.sqlite$')
_HEX64 = re.compile(r'^[0-9a-f]{64}$')


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


class ProjectionError(StoreError):
    pass


class WrongStoreKind(StoreError):
    """The file belongs to another store kind (or to no store at all)."""


class BackupError(StoreError):
    """A backup could not be made, or a backup does not match its manifest."""


class RestoreRefused(StoreError):
    """Restore refused before the live store was changed."""


class RollbackRefused(RestoreRefused):
    """The live store is ahead of, or diverges from, the backup."""


class RestoreEpochOpen(StoreError):
    """A restore epoch is open: new reservations are refused until it is reconciled."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sha256: str
    text: str


@dataclass(frozen=True)
class StoreKind:
    """What backup, restore and opening need to know about one store kind.

    ``application_id`` is written by the migration named in
    ``application_id_since`` (the integration store gained it in its migration
    0002; the effects store has it from 0001). ``high_water(conn)`` is the
    canonical high-water mark (a count that only grows); ``history_digest(conn,
    upto)`` digests the canonical history up to that mark, so a prefix of one
    history has the same digest in a longer one; ``chain_head(conn)`` is the
    hash-chain head, or None for a store without a chain. ``verify(conn)``
    raises when the store's own invariants fail. ``after_restore(conn, ctx)``
    runs on the staged copy before it replaces the live file (drop projections,
    append the restore epoch).
    """
    name: str
    label: str
    application_id: int
    application_id_since: int
    db_name: str
    migrations_dir: Path
    canonical_digest: Callable[[sqlite3.Connection], str]
    high_water: Callable[[sqlite3.Connection], int]
    history_digest: Callable[[sqlite3.Connection, int], str]
    chain_head: Callable[[sqlite3.Connection], str | None]
    verify: Callable[[sqlite3.Connection], None]
    after_restore: Callable[[sqlite3.Connection, 'RestoreContext'], None]


@dataclass(frozen=True)
class VerifiedBackup:
    manifest_path: Path
    manifest_sha256: str
    backup_path: Path
    manifest: dict


@dataclass(frozen=True)
class RestoreContext:
    """What a store kind records in its restore epoch."""
    backup: VerifiedBackup
    previous_live_high_water: int | None
    previous_live_history_digest: str | None
    superseded_copy: str | None
    rollback_accepted: bool
    actor: str
    restored_at: str


@dataclass
class RestoreReport:
    live_path: str
    backup_file: str
    manifest_sha256: str
    backup_high_water: int
    backup_history_digest: str
    previous_live: dict | None
    rollback: str | None
    rollback_accepted: bool
    superseded_copy: str | None
    migrated: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers

def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _stamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')


def canonical_json(value: object) -> str:
    """Canonical JSON: sorted keys, no whitespace, UTF-8, no NaN."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def check_sqlite_version() -> None:
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        need = '.'.join(map(str, MIN_SQLITE_VERSION))
        raise UnsupportedSQLite(
            f'SQLite {sqlite3.sqlite_version} is too old: the store needs {need} or newer '
            '(STRICT tables and built-in JSON functions)')


def is_within(path: Path, root: Path) -> bool:
    """Lexical containment (case-insensitive on Windows); touches no file."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def harness_state_root(environ: Mapping[str, str] | None = None, platform: str | None = None) -> Path:
    """The per-user application-data root that holds ``state/integration.sqlite``.

    Computes a path; creates and reads nothing.
    """
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    if plat == 'win32':
        base = env.get('LOCALAPPDATA')
        if not base:
            raise UnsafeLocation('LOCALAPPDATA is not set; pass an explicit --db path')
        return Path(base) / 'ai-engineering-harness'
    base = env.get('XDG_DATA_HOME') or str(Path(env.get('HOME') or Path.home()) / '.local' / 'share')
    return Path(base) / 'ai-engineering-harness'


def check_local_path(path: Path) -> Path:
    """Resolve and vet a database path: no memory or URI database, no UNC path,
    nothing inside the repository, no Windows network drive."""
    raw = str(path)
    if raw in ('', ':memory:') or raw.startswith('file:'):
        raise UnsafeLocation('the store must be a file path on local disk')
    if raw.startswith(('\\\\', '//')):
        raise UnsafeLocation(f'network (UNC) path refused: {raw}')
    resolved = Path(os.path.abspath(path))
    if is_within(resolved, REPO.resolve()):
        raise UnsafeLocation(f'the store must not be inside the repository checkout: {resolved}')
    if sys.platform == 'win32':
        drive = os.path.splitdrive(str(resolved))[0]
        if drive.startswith('\\\\'):
            raise UnsafeLocation(f'network (UNC) path refused: {resolved}')
        if drive_type(drive) == DRIVE_REMOTE:
            raise UnsafeLocation(f'network drive refused: {resolved}')
    return resolved


DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_CDROM, DRIVE_RAMDISK = 2, 3, 4, 5, 6


def drive_type(drive: str) -> int:
    """Windows GetDriveTypeW for a drive letter such as ``C:``."""
    import ctypes
    return ctypes.windll.kernel32.GetDriveTypeW(drive + '\\')


# ---------------------------------------------------------------------------
# Migrations

def load_migrations(directory: Path) -> list[Migration]:
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


def check_kind(conn: sqlite3.Connection, kind: StoreKind, version: int) -> None:
    """Refuse a database whose application_id names another store kind."""
    app = conn.execute('PRAGMA application_id').fetchone()[0]
    if app == kind.application_id:
        return
    if app != 0:
        raise WrongStoreKind(
            f'database application_id {app} is not {kind.label} ({kind.application_id}); refusing to open')
    if version >= kind.application_id_since:
        raise WrongStoreKind(
            f'database is at schema version {version} but has no application_id; '
            f'it is not {kind.label}; refusing to open')


def verify_applied(conn: sqlite3.Connection, known: Sequence[Migration], kind: StoreKind) -> int:
    """Check the store kind and the recorded migrations against the files; return the version."""
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    check_kind(conn, kind, version)
    if version > len(known):
        raise MigrationError(
            f'database schema version {version} is newer than this code knows ({len(known)}); refusing to open')
    if version == 0:
        objects = conn.execute(
            "SELECT count(*) FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'").fetchone()[0]
        if objects:
            raise MigrationError(f'database has user_version 0 but already holds objects; '
                                 f'it is not {kind.label}')
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


def migrate(conn: sqlite3.Connection, kind: StoreKind, migrations_dir: Path | None = None) -> list[str]:
    """Apply pending migrations in one transaction; return the names applied."""
    known = load_migrations(migrations_dir or kind.migrations_dir)
    applied = []
    with write_transaction(conn):
        version = verify_applied(conn, known, kind)
        for migration in known[version:]:
            for statement in split_statements(migration.text):
                conn.execute(statement)
            conn.execute('INSERT INTO schema_migration (version, name, sha256, applied_at) '
                         'VALUES (?, ?, ?, ?)',
                         (migration.version, migration.name, migration.sha256, now()))
            conn.execute(f'PRAGMA user_version = {migration.version}')
            applied.append(migration.name)
        if version < kind.application_id_since <= len(known):
            app = conn.execute('PRAGMA application_id').fetchone()[0]
            if app != kind.application_id:
                raise MigrationError(f'migrations did not set application_id {kind.application_id} ({app})')
        violations = conn.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            raise MigrationError(f'foreign key violations after migration: {violations}')
    return applied


def check_current(conn: sqlite3.Connection, kind: StoreKind, migrations_dir: Path | None = None) -> int:
    """Verify without migrating; refuse a database with pending migrations."""
    known = load_migrations(migrations_dir or kind.migrations_dir)
    conn.execute('BEGIN')
    try:
        version = verify_applied(conn, known, kind)
    finally:
        conn.execute('ROLLBACK')
    if version != len(known):
        raise MigrationError(f'database is at version {version}; {len(known)} expected')
    return version


# ---------------------------------------------------------------------------
# Connections

def connect(path: Path, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    """Open one connection with the store transaction policy, each pragma read back."""
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=busy_timeout_ms / 1000)
    try:
        deny_attach(conn)
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


def deny_attach(conn: sqlite3.Connection) -> None:
    """Make ATTACH impossible on this connection: at most 0 attached databases."""
    conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    if conn.getlimit(sqlite3.SQLITE_LIMIT_ATTACHED) != 0:
        raise PragmaError('could not set the attached-database limit to 0')


def pragmas(conn: sqlite3.Connection) -> dict:
    return {
        'journal_mode': conn.execute('PRAGMA journal_mode').fetchone()[0].lower(),
        'synchronous': conn.execute('PRAGMA synchronous').fetchone()[0],
        'foreign_keys': conn.execute('PRAGMA foreign_keys').fetchone()[0],
        'busy_timeout': conn.execute('PRAGMA busy_timeout').fetchone()[0],
    }


def open_read_only(path: Path) -> sqlite3.Connection:
    """A read-only connection to a backup copy (rollback-journal mode); never writes it."""
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, isolation_level=None)
    deny_attach(conn)
    return conn


# ---------------------------------------------------------------------------
# Projection authorizer

def projection_authorizer(owned: Callable[[str | None], bool], owned_index: Callable[[str | None], bool],
                          cursor_table: str) -> Callable:
    """An SQLite authorizer that denies every write or schema change except to
    owned tables, owned indexes and the projection cursor table."""
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
            if owned(arg1) or arg1 in (cursor_table, 'sqlite_master', 'sqlite_sequence'):
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
    return authorize


@contextlib.contextmanager
def guarded_transaction(conn: sqlite3.Connection, authorizer: Callable, label: str) -> Iterator[None]:
    """One ``BEGIN IMMEDIATE`` transaction under ``authorizer``; any denial or
    failure rolls it back and raises ProjectionError."""
    conn.execute('BEGIN IMMEDIATE')
    try:
        conn.set_authorizer(authorizer)
        try:
            yield
        finally:
            conn.set_authorizer(None)
    except sqlite3.DatabaseError as exc:
        conn.execute('ROLLBACK')
        raise ProjectionError(f'{label} refused and rolled back: {exc}') from exc
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise
    conn.execute('COMMIT')


# ---------------------------------------------------------------------------
# Backup

def backup_store(conn: sqlite3.Connection, kind: StoreKind, backup_dir: Path, *, actor: str) -> dict:
    """Back up a live store with the SQLite online backup API; return the manifest.

    The copy is written as ``<kind>-<UTC>-hw<N>.sqlite.partial``, switched to the
    rollback journal, checked with ``PRAGMA integrity_check`` and the kind's own
    verification, renamed, and only then described by its sidecar manifest
    ``<copy>.manifest.json`` (sha256, kind, application_id, schema version,
    migrations, UTC time, canonical high-water mark, history digest, chain head,
    canonical digest). A backup without its manifest does not count. The live
    files are never copied directly.
    """
    _check_actor(actor)
    if conn.in_transaction:
        raise BackupError('backup needs a connection with no open transaction')
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        raise BackupError(f'backup directory does not exist: {backup_dir}')
    created_at = now()
    high_water = kind.high_water(conn)
    name = f'{kind.name}-{_stamp()}-hw{high_water:010d}.sqlite'
    final = backup_dir / name
    partial = backup_dir / (name + '.partial')
    manifest_path = backup_dir / (name + '.manifest.json')
    for existing in (final, partial, manifest_path):
        if existing.exists():
            raise BackupError(f'backup target already exists: {existing}')
    dest = sqlite3.connect(str(partial), isolation_level=None)
    try:
        deny_attach(dest)
        conn.backup(dest)
        mode = dest.execute('PRAGMA journal_mode = DELETE').fetchone()[0]
        if mode.lower() != 'delete':
            raise BackupError(f'backup copy did not leave WAL mode: {mode}')
        facts = _describe(dest, kind)
    except BaseException:
        dest.close()
        partial.unlink(missing_ok=True)
        raise
    dest.close()
    os.replace(partial, final)
    manifest = {
        'format': MANIFEST_FORMAT,
        'store_kind': kind.name,
        'application_id': facts['application_id'],
        'schema_version': facts['schema_version'],
        'migrations': facts['migrations'],
        'created_at': created_at,
        'actor': actor,
        'method': BACKUP_METHOD,
        'backup_file': name,
        'size': final.stat().st_size,
        'sha256': sha256_file(final),
        'integrity_check': 'ok',
        'high_water_mark': facts['high_water_mark'],
        'history_digest': facts['history_digest'],
        'chain_head': facts['chain_head'],
        'canonical_digest': facts['canonical_digest'],
        'sqlite_version': sqlite3.sqlite_version,
    }
    _write_json_exclusive(manifest_path, manifest)
    return manifest


def _describe(conn: sqlite3.Connection, kind: StoreKind) -> dict:
    """Facts about a copy, read from the copy itself after an integrity check."""
    result = [r[0] for r in conn.execute('PRAGMA integrity_check').fetchall()]
    if result != ['ok']:
        raise BackupError(f'integrity_check failed on the copy: {result[:5]}')
    if conn.execute('PRAGMA foreign_key_check').fetchall():
        raise BackupError('foreign_key_check failed on the copy')
    kind.verify(conn)
    high_water = kind.high_water(conn)
    return {
        'application_id': conn.execute('PRAGMA application_id').fetchone()[0],
        'schema_version': conn.execute('PRAGMA user_version').fetchone()[0],
        'migrations': [{'version': v, 'name': n, 'sha256': s} for v, n, s in conn.execute(
            'SELECT version, name, sha256 FROM schema_migration ORDER BY version')],
        'high_water_mark': high_water,
        'history_digest': kind.history_digest(conn, high_water),
        'chain_head': kind.chain_head(conn),
        'canonical_digest': kind.canonical_digest(conn),
    }


def _write_json_exclusive(path: Path, value: dict) -> None:
    partial = path.with_name(path.name + '.partial')
    with open(partial, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)


def verify_backup(manifest_path: Path, kind: StoreKind) -> VerifiedBackup:
    """Verify a backup against its manifest before it is used for anything.

    Refuses a manifest of another format or store kind, a copy whose sha256 or
    size differs, a schema version newer than this code knows, recorded
    migrations that differ from the files, a failed integrity check, or facts
    (high-water mark, history digest, chain head, canonical digest) that differ
    from the manifest.
    """
    manifest_path = Path(manifest_path)
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw.decode('utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError(f'BACKUP_MANIFEST_UNREADABLE: {manifest_path}: {exc}') from None
    if not isinstance(manifest, dict) or manifest.get('format') != MANIFEST_FORMAT:
        raise BackupError(f'BACKUP_MANIFEST_FORMAT: {manifest_path} is not a {MANIFEST_FORMAT} manifest')
    if manifest.get('store_kind') != kind.name:
        raise WrongStoreKind(f'BACKUP_WRONG_KIND: the backup is of store kind {manifest.get("store_kind")!r}, '
                             f'not {kind.name!r}')
    name = manifest.get('backup_file')
    if not isinstance(name, str) or not _BACKUP_NAME.match(name) or not name.startswith(kind.name + '-'):
        raise BackupError(f'BACKUP_MANIFEST_FORMAT: bad backup_file {name!r}')
    if not manifest_path.name == name + '.manifest.json':
        raise BackupError(f'BACKUP_MANIFEST_FORMAT: manifest {manifest_path.name} does not name {name}')
    known = load_migrations(kind.migrations_dir)
    version = manifest.get('schema_version')
    if not isinstance(version, int) or version < 1:
        raise BackupError(f'BACKUP_MANIFEST_FORMAT: bad schema_version {version!r}')
    if version > len(known):
        raise MigrationError(f'BACKUP_SCHEMA_NEWER: backup schema version {version} is newer than '
                             f'this code knows ({len(known)}); refusing to restore')
    expected_app = kind.application_id if version >= kind.application_id_since else 0
    if manifest.get('application_id') != expected_app:
        raise WrongStoreKind(f'BACKUP_WRONG_KIND: manifest application_id {manifest.get("application_id")} '
                             f'is not {expected_app}')
    backup_path = manifest_path.with_name(name)
    if not backup_path.is_file():
        raise BackupError(f'BACKUP_MISSING: {backup_path}')
    digest = sha256_file(backup_path)
    if digest != manifest.get('sha256') or backup_path.stat().st_size != manifest.get('size'):
        raise BackupError(f'BACKUP_TAMPERED: {backup_path.name} sha256 {digest} does not match the '
                          f'manifest ({manifest.get("sha256")})')
    with open(backup_path, 'rb') as handle:
        header = handle.read(100)
    # A backup copy is switched to the rollback journal (header bytes 18-19 = 1, 1);
    # a copy of a live WAL-mode file (2, 2) is not a backup and is never used.
    if len(header) < 100 or header[:16] != b'SQLite format 3\x00' or header[18:20] != b'\x01\x01':
        raise BackupError(f'BACKUP_NOT_A_BACKUP_COPY: {backup_path.name} is not a rollback-journal copy made '
                          'by the backup mechanism (a copy of live WAL files is never restored)')
    conn = open_read_only(backup_path)
    try:
        conn.execute('BEGIN')
        try:
            observed_version = verify_applied(conn, known, kind)
            if observed_version != version:
                raise BackupError(f'BACKUP_TAMPERED: copy is at version {observed_version}, manifest says {version}')
            facts = _describe(conn, kind)
        finally:
            conn.execute('ROLLBACK')
    except sqlite3.DatabaseError as exc:
        raise BackupError(f'BACKUP_UNREADABLE: {backup_path.name}: {exc}') from None
    finally:
        conn.close()
    for key in ('application_id', 'schema_version', 'migrations', 'high_water_mark',
                'history_digest', 'chain_head', 'canonical_digest'):
        if facts[key] != manifest.get(key):
            raise BackupError(f'BACKUP_TAMPERED: {key} of the copy ({facts[key]!r}) differs from the '
                              f'manifest ({manifest.get(key)!r})')
    if sha256_file(backup_path) != digest:
        raise BackupError(f'BACKUP_TAMPERED: {backup_path.name} changed while it was verified')
    return VerifiedBackup(manifest_path, hashlib.sha256(raw).hexdigest(), backup_path, manifest)


# ---------------------------------------------------------------------------
# Restore

def acquire_exclusive(path: Path, timeout_ms: int = EXCLUSIVE_TIMEOUT_MS) -> sqlite3.Connection:
    """Take exclusive custody of a live store file or refuse.

    ``locking_mode=EXCLUSIVE`` and a ``BEGIN EXCLUSIVE`` take the exclusive lock
    on the database file and keep it until the connection closes. Every other
    open WAL connection holds a shared lock for its whole life, so another open
    connection (an executor, a service, a reader) makes this fail.
    """
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=timeout_ms / 1000)
    try:
        deny_attach(conn)
        conn.execute(f'PRAGMA busy_timeout = {int(timeout_ms)}')
        conn.execute('PRAGMA locking_mode = EXCLUSIVE')
        conn.execute('BEGIN EXCLUSIVE')
        conn.execute('COMMIT')
    except sqlite3.DatabaseError as exc:
        conn.close()
        if getattr(exc, 'sqlite_errorname', '') in ('SQLITE_BUSY', 'SQLITE_LOCKED'):
            raise RestoreRefused(f'EXCLUSIVE_CUSTODY: another connection holds {path}: {exc}; stop every '
                                 'user of the store (for the effects store: the executor) first') from None
        raise RestoreRefused(f'LIVE_UNREADABLE: {path}: {exc}; the restore will not replace content it '
                             'cannot preserve aside') from None
    except BaseException:
        conn.close()
        raise
    return conn


def restore_store(live_path: Path, manifest_path: Path, kind: StoreKind, *, actor: str,
                  superseded_dir: Path, staging_dir: Path, accept_rollback: bool = False) -> RestoreReport:
    """Restore a verified backup over the live store; refuse rather than lose content.

    1. Verify the backup against its manifest (``verify_backup``).
    2. Take exclusive custody of the live file (``acquire_exclusive``).
    3. Compare the live history with the backup: a live store that is ahead of the
       backup, diverges from it, or cannot be read is a rollback, refused unless
       ``accept_rollback``. A live file of another store kind, or one that cannot
       be read (so cannot be preserved), is always refused.
    4. Preserve the live content aside in ``superseded_dir`` with the backup
       mechanism (never deleted by this code).
    5. Stage the backup with the backup mechanism, migrate it if older, and let
       the kind drop projections and append its restore epoch there.
    6. Replace the live content with the staged copy in one backup step (one
       destination transaction), so a crash leaves the old or the new store.
    """
    _check_actor(actor)
    verified = verify_backup(manifest_path, kind)
    manifest = verified.manifest
    live_path = Path(live_path)
    for directory in (superseded_dir, staging_dir):
        if not Path(directory).is_dir():
            raise RestoreRefused(f'directory does not exist: {directory}')
    live_existed = live_path.exists()
    live = acquire_exclusive(live_path)
    stage = None
    stage_path = None
    try:
        previous, rollback = None, None
        if live_existed:
            previous, rollback = _compare_live(live, verified, kind)
            if rollback and not accept_rollback:
                raise RollbackRefused(f'ROLLBACK_REFUSED: {rollback}; nothing was changed. Restore again with '
                                      'explicit rollback acceptance only if losing that knowledge is intended '
                                      '(the live content is then preserved aside)')
        superseded = None
        if live_existed:
            superseded = _preserve_aside(live, kind, Path(superseded_dir), previous, actor)
        stage_path = Path(staging_dir) / f'{kind.name}-staging-{_stamp()}.sqlite'
        if stage_path.exists():
            raise RestoreRefused(f'staging file already exists: {stage_path}')
        source = open_read_only(verified.backup_path)
        try:
            stage = sqlite3.connect(str(stage_path), isolation_level=None)
            deny_attach(stage)
            source.backup(stage)
        finally:
            source.close()
        stage.execute('PRAGMA foreign_keys = ON')
        migrated = migrate(stage, kind)
        context = RestoreContext(
            backup=verified,
            previous_live_high_water=previous and previous['high_water_mark'],
            previous_live_history_digest=previous and previous['history_digest'],
            superseded_copy=superseded,
            rollback_accepted=bool(rollback and accept_rollback),
            actor=actor, restored_at=now())
        kind.after_restore(stage, context)
        result = [r[0] for r in stage.execute('PRAGMA integrity_check').fetchall()]
        if result != ['ok']:
            raise RestoreRefused(f'integrity_check failed on the staged copy: {result[:5]}')
        kind.verify(stage)
        stage.backup(live)  # one step, one destination transaction
        live.execute('PRAGMA journal_mode = WAL')
    finally:
        if stage is not None:
            stage.close()
        live.close()
        if stage_path is not None:
            stage_path.unlink(missing_ok=True)  # a working copy; never live content or a backup
    return RestoreReport(
        live_path=str(live_path), backup_file=verified.backup_path.name,
        manifest_sha256=verified.manifest_sha256,
        backup_high_water=manifest['high_water_mark'], backup_history_digest=manifest['history_digest'],
        previous_live=previous, rollback=rollback, rollback_accepted=bool(rollback and accept_rollback),
        superseded_copy=superseded, migrated=migrated)


def _compare_live(live: sqlite3.Connection, verified: VerifiedBackup, kind: StoreKind):
    """Return (facts about the live store, rollback reason or None); refuse an unreadable live store."""
    try:
        version = live.execute('PRAGMA user_version').fetchone()[0]
        check_kind(live, kind, version)
    except WrongStoreKind as exc:
        raise RestoreRefused(f'LIVE_WRONG_KIND: {exc}') from None
    except sqlite3.DatabaseError as exc:
        raise RestoreRefused(f'LIVE_UNREADABLE: {exc}; the restore will not replace content it cannot '
                             'preserve aside') from None
    try:
        if version == 0:
            return {'high_water_mark': 0, 'history_digest': GENESIS_DIGEST, 'schema_version': 0}, None
        live_hw = kind.high_water(live)
        live_digest = kind.history_digest(live, live_hw)
        facts = {'high_water_mark': live_hw, 'history_digest': live_digest, 'schema_version': version}
    except sqlite3.DatabaseError as exc:
        raise RestoreRefused(f'LIVE_UNREADABLE: {exc}; the restore will not replace content it cannot '
                             'preserve aside') from None
    backup_hw = verified.manifest['high_water_mark']
    if live_hw > backup_hw:
        return facts, (f'the live store is ahead of the backup (live high-water mark {live_hw}, '
                       f'backup {backup_hw})')
    source = open_read_only(verified.backup_path)
    try:
        backup_digest_at_live = kind.history_digest(source, live_hw)
    finally:
        source.close()
    if backup_digest_at_live != live_digest:
        return facts, (f'the live history diverges from the backup at high-water mark {live_hw} '
                       f'(live {live_digest}, backup {backup_digest_at_live})')
    return facts, None


def _preserve_aside(live: sqlite3.Connection, kind: StoreKind, superseded_dir: Path,
                    previous: dict, actor: str) -> str:
    name = f'{kind.name}-superseded-{_stamp()}.sqlite'
    target = superseded_dir / name
    if target.exists():
        raise RestoreRefused(f'superseded copy already exists: {target}')
    dest = sqlite3.connect(str(target), isolation_level=None)
    try:
        deny_attach(dest)
        live.backup(dest)
        dest.execute('PRAGMA journal_mode = DELETE')
        result = [r[0] for r in dest.execute('PRAGMA integrity_check').fetchall()]
        if result != ['ok']:
            raise RestoreRefused(f'the superseded live content failed its integrity check: {result[:5]}')
    finally:
        dest.close()
    _write_json_exclusive(superseded_dir / (name + '.json'), {
        'format': SUPERSEDED_FORMAT, 'store_kind': kind.name, 'file': name,
        'sha256': sha256_file(target), 'preserved_at': now(), 'actor': actor,
        'high_water_mark': previous['high_water_mark'], 'history_digest': previous['history_digest'],
        'schema_version': previous['schema_version'], 'method': BACKUP_METHOD,
        'note': 'Live content superseded by a restore. Never deleted by the store tools.',
    })
    return name


# ---------------------------------------------------------------------------
# Retention

def list_backups(backup_dir: Path, kind: StoreKind) -> list[tuple[Path, dict]]:
    """Backups of this kind in ``backup_dir`` that have a manifest, oldest first."""
    found = []
    for manifest_path in sorted(Path(backup_dir).glob(f'{kind.name}-*.sqlite.manifest.json')):
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get('format') == MANIFEST_FORMAT and manifest.get('store_kind') == kind.name:
            found.append((manifest_path, manifest))
    return sorted(found, key=lambda item: (item[1].get('created_at', ''), item[0].name))


def prune_backups(backup_dir: Path, kind: StoreKind, *, keep_last: int, older_than_days: float | None = None,
                  protected: Sequence[str] = ()) -> list[str]:
    """Delete old backup copies (file and manifest); return the names deleted.

    Keeps the newest ``keep_last`` (at least 1) and every backup newer than
    ``older_than_days`` when given. Never deletes a name in ``protected`` (the
    source of an open restore epoch), anything outside ``backup_dir`` itself, or a
    superseded live copy (those live in a subdirectory and are never deleted).
    """
    if keep_last < 1:
        raise BackupError('retention must keep at least the newest backup')
    backups = list_backups(backup_dir, kind)
    candidates = backups[:-keep_last] if len(backups) > keep_last else []
    cutoff = None
    if older_than_days is not None:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=older_than_days)
    deleted = []
    for manifest_path, manifest in candidates:
        name = manifest['backup_file']
        if name in protected:
            continue
        if cutoff is not None:
            created = datetime.datetime.strptime(manifest['created_at'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(
                tzinfo=datetime.timezone.utc)
            if created > cutoff:
                continue
        (Path(backup_dir) / name).unlink(missing_ok=True)
        manifest_path.unlink()
        deleted.append(name)
    return deleted


def _check_actor(actor: str) -> None:
    if not isinstance(actor, str) or not 1 <= len(actor) <= 256:
        raise StoreError('actor must be a string of 1 to 256 characters')
