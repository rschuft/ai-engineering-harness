"""The Owner conversation store, ``conversation.sqlite`` (plan leaf U-01.3; Proposed decision 0025, points 3 and 6).

A store kind of its own on ``integrations/storecore`` (WAL, ``synchronous=FULL``, STRICT tables, a migration
ledger, its own ``PRAGMA application_id``), never tables in ``integration.sqlite``: the integration store "is not a
record of authority", while this store becomes the lineage authority for the ``conversation`` and ``message`` kinds
(U-02.1 adds threads and messages in its migration 0002). Its location is ``<state>/owner-host/conversation.sqlite``
of the managed data root (decision 0009), outside the checkout and on local disk.

Migration 0001 holds the store's identity and the Owner UI session table only. A session row is what the Owner's
``enroll`` command writes (integrations/ownerhost/enroll.py): the session's public id, the **verifier** of the
credential (``cred-owner-ui-session``; never the credential), when it was issued and when it expires, and the
session it supersedes. The table is append-only; one session is current, the last one. The Integration process
reads it to verify a presented credential (integrations/ownerhost/session.py).

Python standard library only. Writers: the Owner's ``enroll`` (sessions) and the Integration process (threads and
messages, from U-02.1). There is no command line here; the ownerhost commands open it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
MIGRATIONS_DIR = HERE / 'migrations'


def _load_storecore():
    """The shared mechanics module, loaded by path (``python -I`` adds no script directory)."""
    name = 'aieh_storecore'
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, HERE.parent / 'storecore' / 'storecore.py')
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


storecore = _load_storecore()
StoreError = storecore.StoreError
UnsafeLocation = storecore.UnsafeLocation
MigrationError = storecore.MigrationError
WrongStoreKind = storecore.WrongStoreKind

# PRAGMA application_id of an Owner conversation store, set by migration 0001 ('AICV').
APPLICATION_ID = 0x41494356
APPLICATION_ID_SINCE = 1
COMPONENT = 'owner-host'          # <state>/owner-host/ (decision 0009's <component>/ convention)
DB_NAME = 'conversation.sqlite'
CANONICAL_TABLES = ('schema_migration', 'owner_session')

SESSION_ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')
VERIFIER = re.compile(r'[0-9a-f]{64}')
TIMESTAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')
_SESSION_COLUMNS = 'seq, session_id, verifier, issued_at, expires_at, supersedes'


class SchemaAltered(StoreError):
    """The file's schema objects (tables, triggers, indexes) differ from what its migrations create: a trigger was
    dropped or replaced by a writer outside this module. Refused at open with a stable code; nothing is changed."""
    code = 'CONVERSATION_STORE_ALTERED'

    def __init__(self, detail: str):
        super().__init__(f'{self.code}: {detail}')


class SessionConflict(StoreError):
    """An enrollment that cannot be recorded (a verifier or session id already used); nothing was changed."""


@dataclass(frozen=True)
class Session:
    """One enrollment: its public id, the verifier of its credential, its validity, the session it supersedes,
    and the session that superseded it (None while it is current)."""
    seq: int
    session_id: str
    verifier: str
    issued_at: str
    expires_at: str
    supersedes: str | None
    superseded_by: str | None

    @property
    def current(self) -> bool:
        return self.superseded_by is None

    def public(self) -> dict:
        """What may be shown or logged: everything but the verifier."""
        return {'sessionId': self.session_id, 'issuedAt': self.issued_at, 'expiresAt': self.expires_at,
                'supersedes': self.supersedes, 'current': self.current}


def store_path(state_dir: os.PathLike | str) -> Path:
    """``<state>/owner-host/conversation.sqlite`` for the managed root's state directory STATE_DIR."""
    return Path(state_dir) / COMPONENT / DB_NAME


# ---------------------------------------------------------------------------
# Store kind: what opening (and storecore's backup mechanics) need to know. Backup and restore of this store are
# not decided (decision 0025, "Not decided here"): after_restore refuses.

def _high_water(conn: sqlite3.Connection) -> int:
    return conn.execute('SELECT coalesce(max(seq), 0) FROM owner_session').fetchone()[0]


def _history_digest(conn: sqlite3.Connection, upto: int) -> str:
    digest = storecore.GENESIS_DIGEST
    for row in conn.execute(f'SELECT {_SESSION_COLUMNS} FROM owner_session WHERE seq <= ? ORDER BY seq', (upto,)):
        digest = storecore.sha256_text(digest + '\n' + json.dumps(row, ensure_ascii=True))
    return digest


def _verify_kind_invariants(conn: sqlite3.Connection) -> None:
    rows = conn.execute(f'SELECT {_SESSION_COLUMNS} FROM owner_session ORDER BY seq').fetchall()
    previous = None
    for index, row in enumerate(rows, start=1):
        if row[0] != index or row[5] != previous:
            raise StoreError(f'owner session {row[1]!r} breaks the supersession chain')
        previous = row[1]


def _after_restore(conn: sqlite3.Connection, ctx) -> None:
    raise storecore.RestoreRefused('backup and restore of the Owner conversation store are not decided '
                                   '(decision 0025, "Not decided here")')


def _canonical_dump(conn: sqlite3.Connection) -> bytes:
    """A deterministic dump of every canonical table: schema SQL and all rows, then every schema object."""
    lines = []
    for table in CANONICAL_TABLES:
        sql = conn.execute("SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = ?", (table,)).fetchone()
        lines.append(f'-- {table}: {sql[0] if sql else None}')
        if sql is None:
            continue
        for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY 1'):
            lines.append(json.dumps([[type(v).__name__, v] for v in row], ensure_ascii=True))
    objects = conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_schema WHERE name <> 'sqlite_sequence' "
                           'ORDER BY type, name').fetchall()
    lines.append(json.dumps(objects, ensure_ascii=True))
    lines.append(json.dumps({'application_id': conn.execute('PRAGMA application_id').fetchone()[0],
                             'user_version': conn.execute('PRAGMA user_version').fetchone()[0]}))
    return '\n'.join(lines).encode('utf-8')


def _canonical_digest(conn: sqlite3.Connection) -> str:
    return hashlib.sha256(_canonical_dump(conn)).hexdigest()


KIND = storecore.StoreKind(
    name='conversation', label='an Owner conversation store', application_id=APPLICATION_ID,
    application_id_since=APPLICATION_ID_SINCE, db_name=DB_NAME, migrations_dir=MIGRATIONS_DIR,
    canonical_digest=_canonical_digest, high_water=_high_water, history_digest=_history_digest,
    chain_head=lambda conn: None, verify=_verify_kind_invariants, after_restore=_after_restore)


# ---------------------------------------------------------------------------
# Opening

_SCHEMA_OBJECTS = "SELECT type, name, tbl_name, sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"


def expected_schema(migrations_dir: Path = MIGRATIONS_DIR) -> list[tuple]:
    """The schema objects the migrations create, from a private in-memory database."""
    conn = sqlite3.connect(':memory:', isolation_level=None)
    try:
        for migration in storecore.load_migrations(migrations_dir):
            for statement in storecore.split_statements(migration.text):
                conn.execute(statement)
        return conn.execute(_SCHEMA_OBJECTS).fetchall()
    finally:
        conn.close()


def check_schema(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> None:
    """SchemaAltered unless the store's schema objects are exactly the migrations' (the triggers included)."""
    actual, expected = conn.execute(_SCHEMA_OBJECTS).fetchall(), expected_schema(migrations_dir)
    if actual != expected:
        missing = sorted({row[1] for row in expected} - {row[1] for row in actual})
        changed = sorted(row[1] for row in actual if row not in expected)
        raise SchemaAltered(f'schema objects missing {missing} or not as migrated {changed}')


def open_store(path: os.PathLike | str, *, migrations_dir: Path = MIGRATIONS_DIR,
               busy_timeout_ms: int = storecore.DEFAULT_BUSY_TIMEOUT_MS,
               apply_migrations: bool = True) -> 'ConversationStore':
    """Open (creating if absent) the store at an explicit PATH, whose parent directory must exist. With
    ``apply_migrations=False`` a database with pending migrations is refused instead of migrated. A file of
    another store kind (by ``PRAGMA application_id``) is refused, as is a location inside the checkout, on a
    network path or in memory, and a store whose schema objects (its triggers included) are not exactly what its
    migrations create (SchemaAltered, CONVERSATION_STORE_ALTERED)."""
    storecore.check_sqlite_version()
    resolved = storecore.check_local_path(Path(path))
    if not resolved.parent.is_dir():
        raise UnsafeLocation(f'parent directory does not exist: {resolved.parent}')
    conn = storecore.connect(resolved, busy_timeout_ms)
    try:
        if apply_migrations:
            storecore.migrate(conn, KIND, migrations_dir)
        else:
            storecore.check_current(conn, KIND, migrations_dir)
        check_schema(conn, migrations_dir)
        _verify_kind_invariants(conn)
    except BaseException:
        conn.close()
        raise
    return ConversationStore(conn, resolved)


# ---------------------------------------------------------------------------
# The store


class ConversationStore:
    def __init__(self, conn: sqlite3.Connection, path: Path):
        self.conn = conn
        self.path = path

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> 'ConversationStore':
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- reads ------------------------------------------------------------

    def schema_version(self) -> int:
        return self.conn.execute('PRAGMA user_version').fetchone()[0]

    def _sessions(self, where: str = '', params: tuple = ()) -> list[Session]:
        rows = self.conn.execute(
            f'SELECT {", ".join("s." + c.strip() for c in _SESSION_COLUMNS.split(","))}, n.session_id '
            f'FROM owner_session s LEFT JOIN owner_session n ON n.supersedes = s.session_id {where} ORDER BY s.seq',
            params).fetchall()
        return [Session(*row) for row in rows]

    def sessions(self) -> list[Session]:
        return self._sessions()

    def session_by_verifier(self, verifier: str) -> Session | None:
        """The session whose credential has VERIFIER, current or not, else None. Reads only."""
        if not isinstance(verifier, str) or not VERIFIER.fullmatch(verifier):
            return None
        found = self._sessions('WHERE s.verifier = ?', (verifier,))
        return found[0] if found else None

    def current_session(self) -> Session | None:
        found = self._sessions('WHERE n.session_id IS NULL')
        return found[-1] if found else None

    # -- writes -----------------------------------------------------------

    def enroll_session(self, *, session_id: str, verifier: str, issued_at: str, expires_at: str) -> Session:
        """Record a new session, superseding the current one, in one ``BEGIN IMMEDIATE`` transaction. Only the
        Owner's enroll command calls this. Refuses a malformed value (ValueError) and a verifier or session id
        already used (SessionConflict); nothing is changed by a refusal."""
        if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
            raise ValueError('session_id must be a lower-case UUID version 4')
        if not isinstance(verifier, str) or not VERIFIER.fullmatch(verifier):
            raise ValueError('verifier must be 64 lower-case hexadecimal digits')
        for name, value in (('issued_at', issued_at), ('expires_at', expires_at)):
            if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
                raise ValueError(f'{name} must be YYYY-MM-DDTHH:MM:SSZ')
        with storecore.write_transaction(self.conn):
            seq, current = self.conn.execute(
                'SELECT coalesce(max(seq), 0) + 1, (SELECT session_id FROM owner_session ORDER BY seq DESC LIMIT 1) '
                'FROM owner_session').fetchone()
            if self.conn.execute('SELECT 1 FROM owner_session WHERE verifier = ? OR session_id = ?',
                                 (verifier, session_id)).fetchone():
                raise SessionConflict('the verifier or the session id is already recorded')
            try:
                self.conn.execute(f'INSERT INTO owner_session ({_SESSION_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)',
                                  (seq, session_id, verifier, issued_at, expires_at, current))
            except sqlite3.IntegrityError as exc:
                raise ValueError(f'the session was refused by the store: {exc}') from None
        return self._sessions('WHERE s.session_id = ?', (session_id,))[0]

    # -- evidence ---------------------------------------------------------

    def canonical_dump(self) -> bytes:
        """A deterministic dump of every canonical table: schema SQL and all rows."""
        return _canonical_dump(self.conn)

    def summary(self) -> dict:
        """The store's identity and shape; no verifier."""
        return {'path': str(self.path), 'store_kind': KIND.name,
                'application_id': self.conn.execute('PRAGMA application_id').fetchone()[0],
                'sqlite_version': sqlite3.sqlite_version, 'schema_version': self.schema_version(),
                'migrations': [{'version': v, 'name': n, 'sha256': s} for v, n, s in self.conn.execute(
                    'SELECT version, name, sha256 FROM schema_migration ORDER BY version')],
                'pragmas': storecore.pragmas(self.conn),
                'sessions': len(self.sessions())}
