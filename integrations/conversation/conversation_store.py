"""The Owner conversation store, ``conversation.sqlite`` (plan leaves U-01.3 and U-02.1; decision 0025, points 3
and 6).

A store kind of its own on ``integrations/storecore`` (WAL, ``synchronous=FULL``, STRICT tables, a migration
ledger, its own ``PRAGMA application_id``), never tables in ``integration.sqlite``: the integration store "is not a
record of authority", while this store is the lineage authority for the ``conversation`` and ``message`` kinds. Its
location is ``<state>/owner-host/conversation.sqlite`` of the managed data root (decision 0009), outside the checkout
and on local disk.

Migration 0001 holds the store's identity and the Owner UI session table. A session row is what the Owner's
``enroll`` command writes (integrations/ownerhost/enroll.py): the session's public id, the **verifier** of the
credential (``cred-owner-ui-session``; never the credential), when it was issued and when it expires, and the
session it supersedes. The table is append-only; one session is current, the last one. The Integration process
reads it to verify a presented credential (integrations/ownerhost/session.py).

Migration 0002 holds the threads and messages (U-02.1; decision 0025 point 6), every table append-only:

- the **thread id** is the store's, a UUID minted at ``initialize_thread`` (idempotent for the same session and
  assistant-ui local thread id); a title and the archive state are events; a thread is never deleted
  (``THREAD_DELETE_REFUSED``);
- the **message id** is assistant-ui's native id (seven characters of ``[0-9A-Za-z]``), unique per thread; **order**
  is the store's per-thread ``seq``, assigned at the first append;
- a **user message** (an Owner statement: author ``owner``, exactly one text part) is immutable: its content is that
  text's UTF-8 bytes exactly as received, the durable source of every quote (``message_content``); a repeated append
  of the same id and bytes adds nothing, other bytes under the id are ``MESSAGE_ID_CONFLICT`` and an update that
  would change them is ``MESSAGE_IMMUTABLE``;
- an **assistant message** (author ``owner-host``: display state the shell wrote, never a statement) is kept as
  canonical JSON; ``update_message`` is an upsert that appends a revision;
- an **edit** in assistant-ui is a new message under the same parent: both are kept. Nothing is deleted.

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
import uuid
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
CANONICAL_TABLES = ('schema_migration', 'owner_session', 'thread', 'thread_event', 'message', 'message_revision')

SESSION_ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')
VERIFIER = re.compile(r'[0-9a-f]{64}')
TIMESTAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')
_SESSION_COLUMNS = 'seq, session_id, verifier, issued_at, expires_at, supersedes'

THREAD_ID = SESSION_ID                                        # a UUID version 4, minted here
LOCAL_THREAD_ID = re.compile(r'__LOCALID_[0-9A-Za-z]{1,64}')  # assistant-ui's local thread id (G2)
MESSAGE_ID = re.compile(r'[0-9A-Za-z]{7}')                    # assistant-ui's generateId: nanoid, 7 characters (G2)
CREATED_AT = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z')   # a JavaScript Date's toJSON
MAX_CONTENT_BYTES = 262_144                                   # a message's content, as the migration bounds it
MAX_TITLE_CHARS = 200
USER_ENVELOPE = {'attachments': [], 'metadata': {'custom': {}}}   # what a composer's user message carries besides
ITEM_KEYS = {'parentId', 'message', 'runConfig'}                  # its text (G2); anything else is refused
USER_KEYS = {'id', 'role', 'createdAt', 'content', 'attachments', 'metadata'}


class SchemaAltered(StoreError):
    """The file's schema objects (tables, triggers, indexes) differ from what its migrations create: a trigger was
    dropped or replaced by a writer outside this module. Refused at open with a stable code; nothing is changed."""
    code = 'CONVERSATION_STORE_ALTERED'

    def __init__(self, detail: str):
        super().__init__(f'{self.code}: {detail}')


class SessionConflict(StoreError):
    """An enrollment that cannot be recorded (a verifier or session id already used); nothing was changed."""


class ConversationRefused(StoreError):
    """A thread or message request the store refuses, with a stable code; nothing was changed."""
    CODES = ('THREAD_INVALID', 'THREAD_NOT_FOUND', 'THREAD_DELETE_REFUSED', 'MESSAGE_INVALID',
             'MESSAGE_PARENT_NOT_FOUND', 'MESSAGE_ID_CONFLICT', 'MESSAGE_IMMUTABLE', 'MESSAGE_NOT_FOUND')

    def __init__(self, code: str, detail: str):
        if code not in self.CODES:
            raise ValueError(f'not a conversation refusal code: {code!r}')
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}')


@dataclass(frozen=True)
class Thread:
    seq: int
    thread_id: str
    session_id: str
    local_id: str
    created_at: str
    title: str | None
    status: str                    # 'regular' or 'archived'

    def public(self) -> dict:
        """assistant-ui's RemoteThreadMetadata: the remote id, the status and the title when there is one."""
        found = {'remoteId': self.thread_id, 'status': self.status}
        if self.title is not None:
            found['title'] = self.title
        return found


@dataclass(frozen=True)
class StoredMessage:
    """One message at its latest revision: its place, attribution and content bytes."""
    thread_id: str
    message_id: str
    seq: int
    parent_id: str | None
    role: str
    author: str
    session_id: str
    created_at: str | None
    revision: int
    content: bytes
    sha256: str

    def item(self) -> dict:
        """The message as assistant-ui's history item (ExportedMessageRepositoryItem), with the store's seq beside it.
        A user message is rebuilt from its stored text; an assistant message is its stored JSON."""
        if self.role == 'user':
            message = {'id': self.message_id, 'role': 'user', 'createdAt': self.created_at,
                       'content': [{'type': 'text', 'text': self.content.decode('utf-8')}],
                       **json.loads(json.dumps(USER_ENVELOPE))}
        else:
            message = json.loads(self.content.decode('utf-8'))
        return {'seq': self.seq, 'parentId': self.parent_id, 'message': message}


@dataclass(frozen=True)
class Written:
    """What an append or update did: ``changed`` is False for a repeat that added nothing."""
    message: StoredMessage
    changed: bool


@dataclass(frozen=True)
class _Parsed:
    message_id: str
    parent_id: str | None
    role: str
    created_at: str | None
    content: bytes
    sha256: str


def _refuse(code: str, detail: str):
    raise ConversationRefused(code, detail)


def _check_time(at) -> None:
    if not isinstance(at, str) or not TIMESTAMP.fullmatch(at):
        raise ValueError('a time is YYYY-MM-DDTHH:MM:SSZ')


def _canonical_json_bytes(value) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                          allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeEncodeError, RecursionError) as exc:
        _refuse('MESSAGE_INVALID', f'the message is not storable JSON ({type(exc).__name__})')


def parse_item(item) -> _Parsed:
    """Check one history item as assistant-ui's history adapter sends it (``{parentId, message, runConfig?}``) and
    return what the store keeps. MESSAGE_INVALID for anything else. A user message must be exactly what the composer
    sends: one text part (encodable as UTF-8, no NUL, at most MAX_CONTENT_BYTES bytes), its createdAt, no
    attachments and empty custom metadata; its content is the text's UTF-8 bytes as received. An assistant message
    is kept as canonical JSON."""
    if not isinstance(item, dict) or not set(item) <= ITEM_KEYS or 'message' not in item or 'parentId' not in item:
        _refuse('MESSAGE_INVALID', 'a history item is {parentId, message} (and runConfig)')
    parent, message = item['parentId'], item['message']
    if parent is not None and not (isinstance(parent, str) and MESSAGE_ID.fullmatch(parent)):
        _refuse('MESSAGE_INVALID', 'parentId is null or a message id')
    if not isinstance(message, dict):
        _refuse('MESSAGE_INVALID', 'message is an object')
    message_id, role = message.get('id'), message.get('role')
    if not (isinstance(message_id, str) and MESSAGE_ID.fullmatch(message_id)):
        _refuse('MESSAGE_INVALID', 'a message id is seven characters of [0-9A-Za-z] (assistant-ui\'s native id)')
    if parent == message_id:
        _refuse('MESSAGE_INVALID', 'a message is not its own parent')
    if role == 'user':
        content = message.get('content')
        if set(message) != USER_KEYS or any(message[key] != value for key, value in USER_ENVELOPE.items()):
            _refuse('MESSAGE_INVALID', 'a user message is {id, role, createdAt, content, attachments: [], '
                                       'metadata: {custom: {}}}')
        if not (isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict)
                and set(content[0]) == {'type', 'text'} and content[0]['type'] == 'text'
                and isinstance(content[0]['text'], str)):
            _refuse('MESSAGE_INVALID', 'a user message has exactly one text part')
        created_at = message['createdAt']
        if not (isinstance(created_at, str) and CREATED_AT.fullmatch(created_at)):
            _refuse('MESSAGE_INVALID', 'createdAt is YYYY-MM-DDTHH:MM:SS.sssZ')
        text = content[0]['text']
        if not text or '\x00' in text:
            _refuse('MESSAGE_INVALID', 'the text is not empty and holds no NUL')
        try:
            data = text.encode('utf-8')        # strict: a lone surrogate is refused, nothing is normalized
        except UnicodeEncodeError:
            _refuse('MESSAGE_INVALID', 'the text cannot be encoded as UTF-8 (a lone surrogate)')
    elif role == 'assistant':
        created_at = None
        if not isinstance(message.get('content'), list) or not isinstance(message.get('status'), dict):
            _refuse('MESSAGE_INVALID', 'an assistant message has content and a status')
        data = _canonical_json_bytes(message)
    else:
        _refuse('MESSAGE_INVALID', 'a message is a user or an assistant message')
    if len(data) > MAX_CONTENT_BYTES:
        _refuse('MESSAGE_INVALID', f'the content exceeds {MAX_CONTENT_BYTES} bytes')
    return _Parsed(message_id, parent, role, created_at, data, hashlib.sha256(data).hexdigest())


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
    if conn.execute("SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'message_revision'").fetchone():
        # Each stored content matches its recorded digest, and a user message's bytes are UTF-8 text.
        for thread, message, revision, content, digest, role in conn.execute(
                'SELECT r.thread_id, r.message_id, r.revision, r.content, r.sha256, m.role FROM message_revision r '
                'JOIN message m USING (thread_id, message_id)'):
            if not isinstance(content, bytes) or hashlib.sha256(content).hexdigest() != digest:
                raise StoreError(f'message {thread}/{message} revision {revision} does not match its digest')
            if role == 'user':
                try:
                    content.decode('utf-8')
                except UnicodeDecodeError:
                    raise StoreError(f'user message {thread}/{message} is not UTF-8 text') from None


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
        rows = [json.dumps([[type(v).__name__, v.hex() if isinstance(v, bytes) else v] for v in row],
                           ensure_ascii=True) for row in conn.execute(f'SELECT * FROM "{table}"')]
        lines.extend(sorted(rows))
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

    # -- threads (U-02.1) -------------------------------------------------

    _THREAD_SELECT = (
        'SELECT t.seq, t.thread_id, t.session_id, t.local_id, t.created_at, '
        "(SELECT title FROM thread_event e WHERE e.thread_id = t.thread_id AND e.kind = 'rename' "
        ' ORDER BY e.seq DESC LIMIT 1), '
        "coalesce((SELECT CASE e.kind WHEN 'archive' THEN 'archived' ELSE 'regular' END FROM thread_event e "
        "  WHERE e.thread_id = t.thread_id AND e.kind IN ('archive', 'unarchive') ORDER BY e.seq DESC LIMIT 1), "
        "  'regular') FROM thread t ")

    def threads(self) -> list[Thread]:
        """Every thread, oldest first. Reads only."""
        return [Thread(*row) for row in self.conn.execute(self._THREAD_SELECT + 'ORDER BY t.seq')]

    def thread(self, thread_id) -> Thread:
        """The thread THREAD_ID, else THREAD_NOT_FOUND. Reads only."""
        if not isinstance(thread_id, str) or not THREAD_ID.fullmatch(thread_id):
            _refuse('THREAD_NOT_FOUND', 'not a thread id')
        row = self.conn.execute(self._THREAD_SELECT + 'WHERE t.thread_id = ?', (thread_id,)).fetchone()
        if row is None:
            _refuse('THREAD_NOT_FOUND', 'no thread has this id')
        return Thread(*row)

    def initialize_thread(self, *, session_id: str, local_id: str, at: str, mint=None) -> tuple[Thread, bool]:
        """The thread for assistant-ui's local thread id LOCAL_ID under SESSION_ID: the one already recorded for
        them, or a new one whose id the store mints (a UUID version 4). Returns (thread, created)."""
        if not isinstance(local_id, str) or not LOCAL_THREAD_ID.fullmatch(local_id):
            _refuse('THREAD_INVALID', 'a local thread id is __LOCALID_ and 1 to 64 characters of [0-9A-Za-z]')
        _check_time(at)
        with storecore.write_transaction(self.conn):
            found = self.conn.execute('SELECT thread_id FROM thread WHERE session_id = ? AND local_id = ?',
                                      (session_id, local_id)).fetchone()
            if found:
                created, thread_id = False, found[0]
            else:
                created, thread_id = True, (mint or (lambda: str(uuid.uuid4())))()
                self._insert('INSERT INTO thread (seq, thread_id, session_id, local_id, created_at) '
                             'VALUES ((SELECT coalesce(max(seq), 0) + 1 FROM thread), ?, ?, ?, ?)',
                             (thread_id, session_id, local_id, at))
        return self.thread(thread_id), created

    def _thread_event(self, thread_id: str, kind: str, title: str | None, session_id: str, at: str) -> Thread:
        _check_time(at)
        with storecore.write_transaction(self.conn):
            self.thread(thread_id)
            self._insert('INSERT INTO thread_event (seq, thread_id, kind, title, session_id, recorded_at) '
                         'VALUES ((SELECT coalesce(max(seq), 0) + 1 FROM thread_event), ?, ?, ?, ?, ?)',
                         (thread_id, kind, title, session_id, at))
        return self.thread(thread_id)

    def rename_thread(self, thread_id: str, title, *, session_id: str, at: str) -> Thread:
        if not isinstance(title, str) or not 1 <= len(title) <= MAX_TITLE_CHARS or '\x00' in title:
            _refuse('THREAD_INVALID', f'a title is 1 to {MAX_TITLE_CHARS} characters')
        try:
            title.encode('utf-8')
        except UnicodeEncodeError:
            _refuse('THREAD_INVALID', 'the title cannot be encoded as UTF-8')
        if self.thread(thread_id).title == title:
            return self.thread(thread_id)
        return self._thread_event(thread_id, 'rename', title, session_id, at)

    def archive_thread(self, thread_id: str, *, session_id: str, at: str) -> Thread:
        if self.thread(thread_id).status == 'archived':
            return self.thread(thread_id)
        return self._thread_event(thread_id, 'archive', None, session_id, at)

    def unarchive_thread(self, thread_id: str, *, session_id: str, at: str) -> Thread:
        if self.thread(thread_id).status == 'regular':
            return self.thread(thread_id)
        return self._thread_event(thread_id, 'unarchive', None, session_id, at)

    def delete_thread(self, thread_id) -> None:
        """Always refused: nothing is deleted (decision 0025 point 6). Archive a thread instead."""
        _refuse('THREAD_DELETE_REFUSED', 'threads are never deleted; archive the thread instead')

    # -- messages (U-02.1) ------------------------------------------------

    _MESSAGE_SELECT = (
        'SELECT m.thread_id, m.message_id, m.seq, m.parent_id, m.role, m.author, m.session_id, m.created_at, '
        'r.revision, r.content, r.sha256 FROM message m JOIN message_revision r USING (thread_id, message_id) '
        'WHERE r.revision = (SELECT max(revision) FROM message_revision x '
        '                    WHERE x.thread_id = m.thread_id AND x.message_id = m.message_id) ')

    def messages(self, thread_id: str) -> list[StoredMessage]:
        """THREAD_ID's messages in the store's order (seq), each at its latest revision. Reads only."""
        self.thread(thread_id)
        return [StoredMessage(*row) for row in self.conn.execute(
            self._MESSAGE_SELECT + 'AND m.thread_id = ? ORDER BY m.seq', (thread_id,))]

    def message(self, thread_id: str, message_id: str) -> StoredMessage:
        """One message at its latest revision, else MESSAGE_NOT_FOUND. Reads only."""
        self.thread(thread_id)
        row = None
        if isinstance(message_id, str) and MESSAGE_ID.fullmatch(message_id):
            row = self.conn.execute(self._MESSAGE_SELECT + 'AND m.thread_id = ? AND m.message_id = ?',
                                    (thread_id, message_id)).fetchone()
        if row is None:
            _refuse('MESSAGE_NOT_FOUND', 'no message of the thread has this id')
        return StoredMessage(*row)

    def message_content(self, thread_id: str, message_id: str) -> bytes:
        """The durable bytes of a message: for a user message (an Owner statement) the UTF-8 bytes of its text as
        received, the source every quote and span anchor is cut from (lineage.span_reference)."""
        return self.message(thread_id, message_id).content

    def load(self, thread_id: str) -> dict:
        """The thread as assistant-ui's history load answers it: every message in seq order, no headId (the head
        is then the last message, gate G2)."""
        return {'messages': [stored.item() for stored in self.messages(thread_id)]}

    def append_message(self, thread_id: str, item, *, session_id: str, at: str) -> Written:
        """assistant-ui's history ``append``: record a new message under the next seq. A repeat of the same id with
        the same parent, role and content adds nothing (changed False); the same id with anything else is
        MESSAGE_ID_CONFLICT. The parent must be a message of the thread (MESSAGE_PARENT_NOT_FOUND)."""
        parsed = parse_item(item)
        _check_time(at)
        with storecore.write_transaction(self.conn):
            self.thread(thread_id)
            existing = self._existing(thread_id, parsed.message_id)
            if existing is not None:
                if self._same(existing, parsed):
                    return Written(existing, False)
                _refuse('MESSAGE_ID_CONFLICT', 'the thread already has a different message with this id')
            self._insert_message(thread_id, parsed, session_id, at)
        return Written(self.message(thread_id, parsed.message_id), True)

    def update_message(self, thread_id: str, item, *, session_id: str, at: str) -> Written:
        """assistant-ui's history ``update``, an upsert keyed on the message id, for assistant messages only (a run
        paused for a tool, then completed): a changed assistant message appends a revision; an unknown one is
        appended. A user message is immutable: the same bytes change nothing, other bytes are MESSAGE_IMMUTABLE, and
        an unknown user message is MESSAGE_NOT_FOUND (update never creates a statement)."""
        parsed = parse_item(item)
        _check_time(at)
        with storecore.write_transaction(self.conn):
            self.thread(thread_id)
            existing = self._existing(thread_id, parsed.message_id)
            if existing is None:
                if parsed.role == 'user':
                    _refuse('MESSAGE_NOT_FOUND', 'an update does not create a user message')
                self._insert_message(thread_id, parsed, session_id, at)
                return Written(self.message(thread_id, parsed.message_id), True)
            if existing.role == 'user':
                if self._same(existing, parsed):
                    return Written(existing, False)
                _refuse('MESSAGE_IMMUTABLE', 'a user message is immutable')
            if parsed.role != 'assistant' or parsed.parent_id != existing.parent_id:
                _refuse('MESSAGE_ID_CONFLICT', 'an update keeps the message\'s role and parent')
            if parsed.sha256 == existing.sha256:
                return Written(existing, False)
            self._insert('INSERT INTO message_revision (thread_id, message_id, revision, content, sha256, session_id, '
                         'recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                         (thread_id, parsed.message_id, existing.revision + 1, parsed.content, parsed.sha256,
                          session_id, at))
        return Written(self.message(thread_id, parsed.message_id), True)

    def _existing(self, thread_id: str, message_id: str) -> StoredMessage | None:
        row = self.conn.execute(self._MESSAGE_SELECT + 'AND m.thread_id = ? AND m.message_id = ?',
                                (thread_id, message_id)).fetchone()
        return StoredMessage(*row) if row else None

    @staticmethod
    def _same(existing: StoredMessage, parsed: _Parsed) -> bool:
        return (existing.role, existing.parent_id, existing.created_at, existing.sha256) == (
            parsed.role, parsed.parent_id, parsed.created_at, parsed.sha256)

    def _insert_message(self, thread_id: str, parsed: _Parsed, session_id: str, at: str) -> None:
        if parsed.parent_id is not None and self._existing(thread_id, parsed.parent_id) is None:
            _refuse('MESSAGE_PARENT_NOT_FOUND', 'the parent is not a message of this thread')
        author = 'owner' if parsed.role == 'user' else 'owner-host'
        self._insert('INSERT INTO message (thread_id, message_id, seq, parent_id, role, author, session_id, created_at, '
                     'appended_at) VALUES (?, ?, (SELECT coalesce(max(seq), 0) + 1 FROM message WHERE thread_id = ?), '
                     '?, ?, ?, ?, ?, ?)',
                     (thread_id, parsed.message_id, thread_id, parsed.parent_id, parsed.role, author, session_id,
                      parsed.created_at, at))
        self._insert('INSERT INTO message_revision (thread_id, message_id, revision, content, sha256, session_id, '
                     'recorded_at) VALUES (?, ?, 1, ?, ?, ?, ?)',
                     (thread_id, parsed.message_id, parsed.content, parsed.sha256, session_id, at))

    def _insert(self, sql: str, params: tuple) -> None:
        try:
            self.conn.execute(sql, params)
        except sqlite3.IntegrityError as exc:
            raise StoreError(f'the store refused the write: {exc}') from None

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
                'sessions': len(self.sessions()),
                'threads': self.conn.execute('SELECT count(*) FROM thread').fetchone()[0],
                'messages': self.conn.execute('SELECT count(*) FROM message').fetchone()[0]}
