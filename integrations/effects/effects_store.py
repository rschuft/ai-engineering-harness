"""Privileged effect store: effect receipts, a hash-chained journal, backup and restore.

Plan leaf F-05.2, blueprint section #infrastructure-state, decision 0004. Python
standard library only. ``effects.sqlite`` is the protected executor's own record
of external effects ("Protected executor keeps its own effect receipts"; "No
agent-write access"). It is a separate database in a separate directory tree with
its own migration line, ``PRAGMA application_id``, backup line and owner identity.
It is never attached to, co-located with, or backed up with the integration store,
and nothing here has a network endpoint, an MCP tool or any agent-callable
surface: this module is a library and a command line, nothing else.

Rules this module enforces
--------------------------
* **Location.** An explicit root is required; there is no default path. Refused:
  ``:memory:`` and URIs, UNC paths, network, removable and other non-fixed
  drives, the repository, the integration store's tree, every guest-state root a
  profile declares, every user-profile root (``%USERPROFILE%``, the Users root,
  ``%LOCALAPPDATA%``, ``%APPDATA%``, ``$HOME``, ``/home``, ...), and a missing
  root: ``init`` never creates the root (Owner act A4). A library-only fixture
  policy relaxes the user-profile rule, and only that rule, so tests can use
  ``%TEMP%``; the command line cannot select it, and summaries echo it.
* **Custody.** On every open the root directory's and the database files' owner
  and DACL are read back from the operating system and compared with the custody
  template (``effects_custody.py``); a mismatch is refused by name.
* **Receipts.** A reservation (the one-time effect key derived from its inputs,
  the inputs, the operation kind, the target identity, the Owner authority
  reference and the actor) is committed before any effect. States: reserved ->
  applying -> completed | failed | unknown; unknown -> completed | failed only by
  a recorded reconciliation or Owner attestation; ``observed`` receipts are
  created only by reconciliation. Receipts are never deleted, their identity
  never changes, and every change is an event in an append-only journal whose
  events form a sha256 hash chain (``verify_chain``).
* **Backup and restore.** The SQLite online backup API into ``<root>/backups/``
  with an integrity check and a sha256 manifest; restore under exclusive
  custody, rollback refused unless explicitly accepted, the superseded live
  content preserved aside in ``<root>/backups/superseded/``, and a restore epoch
  appended. While an epoch is open no reservation is accepted and no effect may
  start; reconciliation against the observed target and, for an indeterminate
  outcome, a recorded Owner attestation close it.

Command line (run from the repository root; there is deliberately no default path)::

    python -I -B integrations/effects/effects_store.py init --root ROOT [--principal SID]
    python -I -B integrations/effects/effects_store.py status --root ROOT [--principal SID]
    python -I -B integrations/effects/effects_store.py backup --root ROOT --actor NAME [--principal SID]
    python -I -B integrations/effects/effects_store.py restore --root ROOT --manifest FILE --actor NAME [--accept-rollback] [--principal SID]
    python -I -B integrations/effects/effects_store.py verify-chain --root ROOT [--principal SID]
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
import sqlite3
import sys
from typing import Callable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MIGRATIONS_DIR = HERE / 'migrations'


def _load(name: str, path: Path):
    """Load a sibling module by path (``python -I`` adds no script directory)."""
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


storecore = _load('aieh_storecore', HERE.parent / 'storecore' / 'storecore.py')
custody = _load('aieh_effects_custody', HERE / 'effects_custody.py')

DB_NAME = 'effects.sqlite'
BACKUPS_DIR = 'backups'
SUPERSEDED_DIR = 'superseded'
STAGING_DIR = 'staging'
# PRAGMA application_id of an effects store ('AEFX'), set by its migration 0001.
APPLICATION_ID = 0x41454658
APPLICATION_ID_SINCE = 1
KEY_PREFIX = 'fx1-'
KEY_INPUTS_VERSION = 1

STATES = ('reserved', 'applying', 'completed', 'failed', 'unknown', 'observed')
TERMINAL = frozenset({'completed', 'failed', 'observed'})
TRANSITIONS = frozenset({
    ('reserved', 'applying', 'executor'), ('reserved', 'failed', 'executor'),
    ('applying', 'completed', 'executor'), ('applying', 'failed', 'executor'),
    ('applying', 'unknown', 'executor'),
    ('reserved', 'completed', 'reconciliation'), ('reserved', 'unknown', 'reconciliation'),
    ('applying', 'completed', 'reconciliation'), ('applying', 'failed', 'reconciliation'),
    ('applying', 'unknown', 'reconciliation'),
    ('unknown', 'completed', 'reconciliation'), ('unknown', 'failed', 'reconciliation'),
    ('unknown', 'completed', 'owner_attestation'), ('unknown', 'failed', 'owner_attestation'),
})
VERDICTS = ('performed', 'not_performed', 'indeterminate')

StoreError = storecore.StoreError
UnsafeLocation = storecore.UnsafeLocation
MigrationError = storecore.MigrationError
WrongStoreKind = storecore.WrongStoreKind
BackupError = storecore.BackupError
RestoreRefused = storecore.RestoreRefused
RollbackRefused = storecore.RollbackRefused
RestoreEpochOpen = storecore.RestoreEpochOpen
CustodyRefused = custody.CustodyRefused
CustodyTemplate = custody.CustodyTemplate


class LocationRefused(UnsafeLocation):
    """A refused effects root; ``code`` names the rule."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f'{code}: {detail}')


class IllegalTransition(StoreError):
    pass


class UnknownEffect(StoreError):
    pass


class ChainError(StoreError):
    """The journal's hash chain or a receipt's derived key does not verify."""


class EpochNotReconciled(StoreError):
    """A restore epoch cannot close while an effect's outcome is unresolved."""


# ---------------------------------------------------------------------------
# Location policy

@dataclass(frozen=True)
class LocationPolicy:
    name: str
    relax_profile_rule: bool


LIVE_POLICY = LocationPolicy('live', relax_profile_rule=False)


def fixture_location_policy() -> LocationPolicy:
    """Tests only: relaxes the user-profile rule (so %TEMP% can hold a fixture root).

    Every other location rule and the custody check still apply. The command line
    never uses this; every summary echoes the policy in force.
    """
    return LocationPolicy('fixture (tests only): user-profile rule relaxed; every other location rule '
                          'and the custody template apply', relax_profile_rule=True)


def declared_guest_state_roots() -> list[Path]:
    """Guest-state roots the execution profiles declare (``state_dir`` default/proposed)."""
    roots = []
    for profile in sorted((REPO / 'profiles').glob('*/profile.json')):
        try:
            state_dir = json.loads(profile.read_text(encoding='utf-8')).get('state_dir') or {}
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
        for key in ('default', 'proposed'):
            value = state_dir.get(key) if isinstance(state_dir, dict) else None
            if isinstance(value, str) and value:
                roots.append(Path(value))
    return roots


def user_profile_roots(environ: Mapping[str, str] | None = None, platform: str | None = None) -> list[Path]:
    """Every user-profile root the effects store must stay out of."""
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    roots = []
    if plat == 'win32':
        for var in ('USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'HOME'):
            if env.get(var):
                roots.append(Path(env[var]))
        if env.get('USERPROFILE'):
            roots.append(Path(env['USERPROFILE']).parent)  # the Users root
        roots.append(Path((env.get('SystemDrive') or 'C:') + '\\Users'))
    else:
        if env.get('HOME'):
            roots.append(Path(env['HOME']))
        roots.extend(Path(p) for p in ('/home', '/Users', '/root'))
    return roots


def integration_store_roots(environ: Mapping[str, str] | None = None, platform: str | None = None) -> list[Path]:
    """The integration store's default tree (``.../ai-engineering-harness``), when computable."""
    try:
        return [storecore.harness_state_root(environ, platform)]
    except UnsafeLocation:
        return []


def _forbidden(resolved: Path, policy: LocationPolicy, extra_guest_roots: Sequence[Path],
               integration_roots: Sequence[Path]) -> None:
    """Lexical location rules; touches no file."""
    rules = [('LOCATION_REPOSITORY', 'the repository checkout', [REPO.resolve()]),
             ('LOCATION_INTEGRATION_TREE', "the integration store's tree",
              [*integration_store_roots(), *map(Path, integration_roots)]),
             ('LOCATION_GUEST_STATE', 'a guest-state root', [*declared_guest_state_roots(),
                                                             *map(Path, extra_guest_roots)])]
    if not policy.relax_profile_rule:
        rules.append(('LOCATION_PROFILE_ROOT', 'a user-profile root', user_profile_roots()))
    for code, what, roots in rules:
        for root in roots:
            root = Path(os.path.abspath(root))
            if storecore.is_within(resolved, root):
                raise LocationRefused(code, f'{resolved} is inside {what} ({root})')
            if storecore.is_within(root, resolved):
                raise LocationRefused(code, f'{resolved} contains {what} ({root})')


def _filesystem_checks(resolved: Path) -> Path:
    """Checks that touch the filesystem; run only after every lexical rule passed."""
    if sys.platform == 'win32':
        drive = os.path.splitdrive(str(resolved))[0]
        kind = storecore.drive_type(drive)
        if kind == storecore.DRIVE_REMOTE:
            raise LocationRefused('LOCATION_NETWORK_DRIVE', f'network drive refused: {resolved}')
        if kind == storecore.DRIVE_REMOVABLE:
            raise LocationRefused('LOCATION_REMOVABLE', f'removable drive refused: {resolved}')
        if kind != storecore.DRIVE_FIXED:
            raise LocationRefused('LOCATION_NOT_FIXED', f'drive type {kind} is not a local fixed volume: {resolved}')
    if not resolved.exists():
        raise LocationRefused('LOCATION_MISSING_ROOT',
                              f'{resolved} does not exist; the effects root is created by the Owner (act A4), '
                              'never by this tool')
    if not resolved.is_dir():
        raise LocationRefused('LOCATION_NOT_DIRECTORY', f'{resolved} is not a directory')
    return Path(os.path.realpath(resolved))


def check_effects_root(root: os.PathLike | str, *, policy: LocationPolicy = LIVE_POLICY,
                       extra_guest_roots: Sequence[os.PathLike | str] = (),
                       integration_roots: Sequence[os.PathLike | str] = ()) -> Path:
    """Vet an effects root; refuse with a named LocationRefused. Creates nothing.

    Every lexical rule runs before anything touches the filesystem, so a refused
    location is never stat-ed. A root reached through a link is checked again at
    its real path.
    """
    raw = str(root)
    if raw in ('', ':memory:') or raw.startswith('file:'):
        raise LocationRefused('LOCATION_MEMORY_OR_URI', f'an effects root must be a local directory, not {raw!r}')
    if raw.startswith(('\\\\', '//')):
        raise LocationRefused('LOCATION_UNC', f'network (UNC) path refused: {raw}')
    resolved = Path(os.path.abspath(root))
    if str(resolved).startswith('\\\\'):
        raise LocationRefused('LOCATION_UNC', f'network (UNC) path refused: {resolved}')
    _forbidden(resolved, policy, extra_guest_roots, integration_roots)
    real = _filesystem_checks(resolved)
    if real != resolved:
        _forbidden(real, policy, extra_guest_roots, integration_roots)
    return real


# ---------------------------------------------------------------------------
# Receipts: inputs, keys and results

@dataclass(frozen=True)
class Authority:
    """The Owner authority an effect is executed under (as reported by the verifier)."""
    protected_ref: str
    authorization_revision: str
    manifest_blob_digest: str
    merged_by: str
    policy_revision: str


@dataclass(frozen=True)
class EffectRequest:
    """What an effect is: the inputs its one-time key is derived from."""
    operation_kind: str
    target_identity: str
    authority: Authority
    inputs: Mapping

    def key_inputs(self) -> dict:
        _check_text('operation_kind', self.operation_kind, 128)
        _check_text('target_identity', self.target_identity, 1024)
        if not isinstance(self.authority, Authority):
            raise StoreError('authority must be an Authority')
        for name, value in dataclasses.asdict(self.authority).items():
            _check_text(f'authority.{name}', value, 512 if name == 'protected_ref' else 256)
        if not isinstance(self.inputs, Mapping):
            raise StoreError('inputs must be a JSON object')
        return {'version': KEY_INPUTS_VERSION, 'operation_kind': self.operation_kind,
                'target_identity': self.target_identity, 'authority': dataclasses.asdict(self.authority),
                'inputs': dict(self.inputs)}

    def effect_key(self) -> str:
        return derive_effect_key(self.key_inputs())

    @classmethod
    def from_key_inputs(cls, key_inputs: Mapping) -> 'EffectRequest':
        return cls(key_inputs['operation_kind'], key_inputs['target_identity'],
                   Authority(**key_inputs['authority']), key_inputs['inputs'])


@dataclass(frozen=True)
class EffectResult:
    """The exact effect result: the observed target state and the outcome.

    The outcome is what the target shows, independent of any exit status, which is
    kept only as information.
    """
    outcome: str  # 'performed' | 'not_performed'
    observed_target_state: Mapping | None
    exit_status: int | None = None

    def to_json(self) -> str:
        if self.outcome not in ('performed', 'not_performed'):
            raise StoreError(f'outcome must be performed or not_performed: {self.outcome!r}')
        return _canonical({'outcome': self.outcome, 'observed_target_state': self.observed_target_state,
                           'exit_status': self.exit_status})


@dataclass(frozen=True)
class Probe:
    """What the observed target shows for one effect key (from an oracle)."""
    verdict: str  # 'performed' | 'not_performed' | 'indeterminate'
    observation: Mapping
    oracle: str


@dataclass(frozen=True)
class Receipt:
    effect_key: str
    key_inputs_json: str
    operation_kind: str
    target_identity: str
    authority_protected_ref: str
    authority_revision: str
    authority_manifest_digest: str
    authority_merged_by: str
    authority_policy_revision: str
    origin: str
    actor: str
    state: str
    reconciliation_status: str
    result_json: str | None
    state_seq: int
    created_seq: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ReserveResult:
    receipt: Receipt
    created: bool


def _canonical(value: object) -> str:
    try:
        return storecore.canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise StoreError(f'not canonical JSON: {exc}') from None


def _check_text(name: str, value: object, limit: int) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= limit:
        raise StoreError(f'{name} must be a string of 1 to {limit} characters')


def derive_effect_key(key_inputs: Mapping) -> str:
    """The one-time effect key: ``fx1-`` + sha256 of the canonical key inputs."""
    return KEY_PREFIX + hashlib.sha256(_canonical(key_inputs).encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------
# The journal (hash chain)

_EVENT_COLUMNS = ('seq', 'kind', 'effect_key', 'epoch_id', 'from_state', 'to_state', 'origin', 'actor',
                  'recorded_at')


def _append_event(conn: sqlite3.Connection, kind: str, actor: str, *, effect_key: str | None = None,
                  epoch_id: int | None = None, from_state: str | None = None, to_state: str | None = None,
                  origin: str | None = None, detail: object = None) -> int:
    """Append one journal event inside the caller's transaction; return its seq."""
    last = conn.execute('SELECT seq, hash FROM effect_event ORDER BY seq DESC LIMIT 1').fetchone()
    seq, prev = (last[0] + 1, last[1]) if last else (1, storecore.GENESIS_DIGEST)
    recorded_at = storecore.now()
    content = _canonical({'seq': seq, 'kind': kind, 'effect_key': effect_key, 'epoch_id': epoch_id,
                          'from_state': from_state, 'to_state': to_state, 'origin': origin, 'actor': actor,
                          'recorded_at': recorded_at, 'detail': detail})
    digest = storecore.sha256_text(prev + '\n' + content)
    conn.execute('INSERT INTO effect_event (seq, kind, effect_key, epoch_id, from_state, to_state, origin, actor, '
                 'content_json, prev_hash, hash, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                 (seq, kind, effect_key, epoch_id, from_state, to_state, origin, actor, content, prev, digest,
                  recorded_at))
    return seq


def verify_chain(conn: sqlite3.Connection) -> dict:
    """Verify the whole journal and every receipt against it; return the chain head.

    Checks contiguous sequence numbers, each previous-hash link, each event hash
    recomputed from its content, the indexed columns against the content, every
    receipt's key re-derived from its recorded inputs, and every receipt's state
    against its last journal event.
    """
    prev, expected_seq, last_state = storecore.GENESIS_DIGEST, 1, {}
    count = 0
    for row in conn.execute(f'SELECT {", ".join(_EVENT_COLUMNS)}, content_json, prev_hash, hash '
                            'FROM effect_event ORDER BY seq'):
        values = dict(zip(_EVENT_COLUMNS, row[:len(_EVENT_COLUMNS)]))
        content_json, prev_hash, digest = row[len(_EVENT_COLUMNS):]
        seq = values['seq']
        if seq != expected_seq:
            raise ChainError(f'CHAIN_GAP: expected event {expected_seq}, found {seq}')
        if prev_hash != prev:
            raise ChainError(f'CHAIN_LINK: event {seq} does not link to event {seq - 1}')
        if storecore.sha256_text(prev_hash + '\n' + content_json) != digest:
            raise ChainError(f'CHAIN_HASH: event {seq} content does not match its hash')
        content = json.loads(content_json)
        for column in _EVENT_COLUMNS:
            if content.get(column) != values[column]:
                raise ChainError(f'CHAIN_CONTENT: event {seq} column {column} differs from its hashed content')
        if values['kind'] in ('receipt_created', 'receipt_transition'):
            last_state[values['effect_key']] = values['to_state']
        prev, expected_seq, count = digest, expected_seq + 1, count + 1
    receipts = 0
    for key, inputs, state, created_seq in conn.execute(
            'SELECT effect_key, key_inputs_json, state, created_seq FROM effect_receipt ORDER BY effect_key'):
        receipts += 1
        if derive_effect_key(json.loads(inputs)) != key:
            raise ChainError(f'KEY_MISMATCH: {key} is not derived from its recorded inputs')
        created = conn.execute('SELECT kind, effect_key FROM effect_event WHERE seq = ?', (created_seq,)).fetchone()
        if created != ('receipt_created', key):
            raise ChainError(f'CHAIN_RECEIPT: {key} has no creation event at seq {created_seq}')
        if last_state.get(key) != state:
            raise ChainError(f'CHAIN_RECEIPT: {key} is {state} but its journal says {last_state.get(key)}')
    return {'events': count, 'high_water_mark': count, 'chain_head': prev, 'receipts': receipts}


def _high_water(conn: sqlite3.Connection) -> int:
    return conn.execute('SELECT coalesce(max(seq), 0) FROM effect_event').fetchone()[0]


def _history_digest(conn: sqlite3.Connection, upto: int) -> str:
    """The chain hash at ``upto``: equal for a history and any longer history it starts."""
    if upto == 0:
        return storecore.GENESIS_DIGEST
    row = conn.execute('SELECT hash FROM effect_event WHERE seq = ?', (upto,)).fetchone()
    return row[0] if row else ''


def _chain_head(conn: sqlite3.Connection) -> str:
    return _history_digest(conn, _high_water(conn))


def canonical_dump(conn: sqlite3.Connection) -> bytes:
    """A deterministic dump of every table (all are canonical): schema SQL and all rows."""
    lines = []
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for table in tables:
        sql = conn.execute("SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = ?", (table,)).fetchone()
        lines.append(f'-- {table}: {sql[0]}')
        columns = len(conn.execute(f'PRAGMA table_info("{table}")').fetchall())
        order = ', '.join(str(i) for i in range(1, columns + 1))
        for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY {order}'):
            lines.append(json.dumps([[type(v).__name__, v] for v in row], ensure_ascii=True))
    lines.append(json.dumps(conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name").fetchall(), ensure_ascii=True))
    return '\n'.join(lines).encode('utf-8')


def _open_epochs(conn: sqlite3.Connection) -> list[dict]:
    cursor = conn.execute('SELECT * FROM restore_epoch e WHERE NOT EXISTS '
                          '(SELECT 1 FROM restore_epoch_closure c WHERE c.epoch_id = e.epoch_id) ORDER BY epoch_id')
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _after_restore(conn: sqlite3.Connection, ctx: 'storecore.RestoreContext') -> None:
    """On the staged copy: append the restore epoch (journal event and row)."""
    manifest = ctx.backup.manifest
    with storecore.write_transaction(conn):
        epoch_id = conn.execute('SELECT coalesce(max(epoch_id), 0) + 1 FROM restore_epoch').fetchone()[0]
        detail = {'backup_file': manifest['backup_file'], 'backup_manifest_sha256': ctx.backup.manifest_sha256,
                  'backup_high_water': manifest['high_water_mark'], 'backup_chain_head': manifest['chain_head'],
                  'previous_live_high_water': ctx.previous_live_high_water,
                  'previous_live_chain_head': ctx.previous_live_history_digest,
                  'superseded_copy': ctx.superseded_copy, 'rollback_accepted': ctx.rollback_accepted,
                  'reconciliation_status': 'required'}
        seq = _append_event(conn, 'epoch_opened', ctx.actor, epoch_id=epoch_id, detail=detail)
        conn.execute(
            'INSERT INTO restore_epoch (epoch_id, opened_seq, backup_manifest_sha256, backup_file, backup_high_water, '
            'backup_chain_head, previous_live_high_water, previous_live_chain_head, superseded_copy, '
            'rollback_accepted, actor, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (epoch_id, seq, ctx.backup.manifest_sha256, manifest['backup_file'], manifest['high_water_mark'],
             manifest['chain_head'], ctx.previous_live_high_water, ctx.previous_live_history_digest,
             ctx.superseded_copy, int(ctx.rollback_accepted), ctx.actor, ctx.restored_at))


def _verify(conn: sqlite3.Connection) -> None:
    verify_chain(conn)


KIND = storecore.StoreKind(
    name='effects', label='an effects store', application_id=APPLICATION_ID,
    application_id_since=APPLICATION_ID_SINCE, db_name=DB_NAME, migrations_dir=MIGRATIONS_DIR,
    canonical_digest=lambda conn: hashlib.sha256(canonical_dump(conn)).hexdigest(),
    high_water=_high_water, history_digest=_history_digest, chain_head=_chain_head,
    verify=_verify, after_restore=_after_restore)


# ---------------------------------------------------------------------------
# Opening

def _check_custody(root: Path, template: CustodyTemplate) -> None:
    """Root and every store file and backup directory that exists, read back from the OS."""
    custody.check_path(root, template, is_root=True)
    for path in (root / DB_NAME, root / (DB_NAME + '-wal'), root / (DB_NAME + '-shm'),
                 root / BACKUPS_DIR, root / BACKUPS_DIR / SUPERSEDED_DIR, root / BACKUPS_DIR / STAGING_DIR):
        if path.exists():
            custody.check_path(path, template, is_root=False)


def _make_private_dir(directory: Path) -> None:
    """Create a directory under the root that keeps the root's custody.

    On Windows it must inherit the root's protected DACL: CPython 3.12.4+ gives
    ``mkdir(mode=0o700)`` its own protected DACL (SYSTEM, Administrators, OWNER
    RIGHTS), which is not the custody template, so the default mode is used. On
    POSIX the directory is 0700.
    """
    if sys.platform == 'win32':
        directory.mkdir(exist_ok=True)
    else:
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)


def _prepare(root: os.PathLike | str, principal: str | int | None, policy: LocationPolicy,
             extra_guest_roots: Sequence, integration_roots: Sequence) -> tuple[Path, CustodyTemplate]:
    storecore.check_sqlite_version()
    if not isinstance(policy, LocationPolicy):
        raise StoreError('policy must be a LocationPolicy')
    resolved = check_effects_root(root, policy=policy, extra_guest_roots=extra_guest_roots,
                                  integration_roots=integration_roots)
    template = CustodyTemplate(principal)
    _check_custody(resolved, template)
    if (resolved / 'integration.sqlite').exists():
        raise LocationRefused('LOCATION_CO_LOCATED', f'{resolved} holds an integration store; '
                                                     'the two stores are never co-located')
    return resolved, template


def open_effects_store(root: os.PathLike | str, *, principal: str | int | None = None,
                       policy: LocationPolicy = LIVE_POLICY, create: bool = False,
                       extra_guest_roots: Sequence[os.PathLike | str] = (),
                       integration_roots: Sequence[os.PathLike | str] = (),
                       busy_timeout_ms: int = storecore.DEFAULT_BUSY_TIMEOUT_MS) -> 'EffectsStore':
    """Open the effects store in an existing, Owner-created root.

    Vets the location, verifies the custody template from the effective ACEs of
    the root and the store files, refuses a file of another store kind, and
    applies pending migrations. With ``create`` (``init``) a missing database and
    ``backups/`` are created inside the root; the root itself is never created.
    """
    resolved, template = _prepare(root, principal, policy, extra_guest_roots, integration_roots)
    db = resolved / DB_NAME
    if not db.exists():
        if not create:
            raise StoreError(f'NO_STORE: {db} does not exist; run init first')
    backups = resolved / BACKUPS_DIR
    if create:
        for directory in (backups, backups / SUPERSEDED_DIR, backups / STAGING_DIR):
            _make_private_dir(directory)
    conn = storecore.connect(db, busy_timeout_ms)
    try:
        storecore.migrate(conn, KIND)
        _check_custody(resolved, template)
    except BaseException:
        conn.close()
        raise
    return EffectsStore(conn, resolved, template, policy)


def init_effects_store(root: os.PathLike | str, **kwargs) -> dict:
    """``init``: create or migrate the store inside an existing root; return its summary."""
    with open_effects_store(root, create=True, **kwargs) as store:
        return store.summary()


def restore_effects_store(root: os.PathLike | str, manifest: os.PathLike | str, *, actor: str,
                          accept_rollback: bool = False, principal: str | int | None = None,
                          policy: LocationPolicy = LIVE_POLICY,
                          extra_guest_roots: Sequence[os.PathLike | str] = (),
                          integration_roots: Sequence[os.PathLike | str] = ()) -> 'storecore.RestoreReport':
    """Restore a verified effects backup over the live store (the Owner's elevated act,
    with the executor stopped). See storecore.restore_store for the steps."""
    resolved, template = _prepare(root, principal, policy, extra_guest_roots, integration_roots)
    backups = resolved / BACKUPS_DIR
    for directory in (backups, backups / SUPERSEDED_DIR, backups / STAGING_DIR):
        if not directory.is_dir():
            raise RestoreRefused(f'{directory} does not exist; run init first')
    report = storecore.restore_store(resolved / DB_NAME, Path(manifest), KIND, actor=actor,
                                     accept_rollback=accept_rollback,
                                     superseded_dir=backups / SUPERSEDED_DIR, staging_dir=backups / STAGING_DIR)
    _check_custody(resolved, template)
    return report


# ---------------------------------------------------------------------------
# The store

_RECEIPT_COLUMNS = ', '.join(f.name for f in dataclasses.fields(Receipt))


class EffectsStore:
    def __init__(self, conn: sqlite3.Connection, root: Path, template: CustodyTemplate, policy: LocationPolicy):
        self.conn = conn
        self.root = root
        self.path = root / DB_NAME
        self.template = template
        self.policy = policy

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> 'EffectsStore':
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- reads ------------------------------------------------------------

    def schema_version(self) -> int:
        return self.conn.execute('PRAGMA user_version').fetchone()[0]

    def get(self, effect_key: str) -> Receipt | None:
        row = self.conn.execute(f'SELECT {_RECEIPT_COLUMNS} FROM effect_receipt WHERE effect_key = ?',
                                (effect_key,)).fetchone()
        return Receipt(*row) if row else None

    def receipts(self, states: Sequence[str] | None = None) -> list[Receipt]:
        sql, params = f'SELECT {_RECEIPT_COLUMNS} FROM effect_receipt', ()
        if states:
            sql += f' WHERE state IN ({",".join("?" * len(states))})'
            params = tuple(states)
        return [Receipt(*row) for row in self.conn.execute(sql + ' ORDER BY created_seq', params)]

    def events(self, effect_key: str | None = None) -> list[dict]:
        sql = f'SELECT {", ".join(_EVENT_COLUMNS)}, content_json, hash FROM effect_event'
        rows = self.conn.execute(sql + (' WHERE effect_key = ?' if effect_key else '') + ' ORDER BY seq',
                                 (effect_key,) if effect_key else ())
        names = [*_EVENT_COLUMNS, 'content_json', 'hash']
        return [dict(zip(names, row)) for row in rows]

    def reconciliation_records(self) -> list[dict]:
        cursor = self.conn.execute('SELECT * FROM reconciliation_record ORDER BY seq')
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def reconciliation_required(self) -> list[dict]:
        """Receipts flagged for reconciliation: an ``applying`` receipt found at open
        (its executor is gone, so its outcome is unknown) or an ``unknown`` one.
        Neither is ever reissued."""
        return [{'effect_key': r.effect_key, 'state': r.state,
                 'reason': ('effect started; outcome not recorded' if r.state == 'applying'
                            else 'outcome unknown')}
                for r in self.receipts(['applying', 'unknown'])]

    def open_epochs(self) -> list[dict]:
        return _open_epochs(self.conn)

    def high_water_mark(self) -> int:
        return _high_water(self.conn)

    def chain_head(self) -> str:
        return _chain_head(self.conn)

    def verify_chain(self) -> dict:
        return verify_chain(self.conn)

    # -- executor writes ---------------------------------------------------

    def reserve(self, request: EffectRequest, *, actor: str) -> ReserveResult:
        """Reserve an effect before it is started; one transaction.

        Commits the one-time effect key derived from the request, the inputs, the
        operation kind, the target identity, the Owner authority reference and the
        actor, with a journal event. Reserving the same request again returns the
        existing receipt unchanged. Refused (RestoreEpochOpen) while a restore
        epoch is open.
        """
        _check_text('actor', actor, 256)
        key_inputs = request.key_inputs()
        canonical = _canonical(key_inputs)
        key = derive_effect_key(key_inputs)
        with storecore.write_transaction(self.conn):
            existing = self.get(key)
            if existing is not None:
                if existing.key_inputs_json != canonical:
                    raise ChainError(f'KEY_MISMATCH: {key} is recorded with different inputs')
                return ReserveResult(existing, created=False)
            if self.open_epochs():
                raise RestoreEpochOpen('a restore epoch is open: new effect reservations are refused until '
                                       'reconciliation closes it')
            self._insert_receipt(key, key_inputs, canonical, 'executor', 'reserved', actor, None)
            return ReserveResult(self.get(key), created=True)

    def _insert_receipt(self, key: str, key_inputs: dict, canonical: str, origin: str, state: str, actor: str,
                        result_json: str | None, epoch_id: int | None = None) -> None:
        """Insert a receipt and its creation event. Caller owns the transaction."""
        seq = _append_event(self.conn, 'receipt_created', actor, effect_key=key, epoch_id=epoch_id,
                            to_state=state, origin=origin,
                            detail={'key_inputs': key_inputs,
                                    'result': None if result_json is None else json.loads(result_json)})
        now = storecore.now()
        authority = key_inputs['authority']
        self.conn.execute(
            f'INSERT INTO effect_receipt ({_RECEIPT_COLUMNS}) VALUES ({", ".join("?" * 18)})',
            (key, canonical, key_inputs['operation_kind'], key_inputs['target_identity'],
             authority['protected_ref'], authority['authorization_revision'], authority['manifest_blob_digest'],
             authority['merged_by'], authority['policy_revision'], origin, actor, state,
             'required' if state == 'unknown' else ('reconciled' if origin == 'reconciliation' else 'none'),
             result_json, 0, seq, now, now))

    def begin(self, effect_key: str, *, actor: str) -> Receipt:
        """reserved -> applying, immediately before the effect starts."""
        return self._transition(effect_key, 'applying', 'executor', actor, expected_from='reserved')

    def finish(self, effect_key: str, to_state: str, *, actor: str, result: EffectResult | None = None,
               detail: Mapping | None = None) -> Receipt:
        """applying -> completed | failed (with the observed result) | unknown."""
        if to_state not in ('completed', 'failed', 'unknown'):
            raise IllegalTransition(f'finish goes to completed, failed or unknown, not {to_state!r}')
        return self._transition(effect_key, to_state, 'executor', actor, result=result, detail=detail,
                                expected_from='applying')

    def fail_before_effect(self, effect_key: str, *, actor: str, reason: str) -> Receipt:
        """reserved -> failed: refused before any effect was started."""
        _check_text('reason', reason, 1024)
        return self._transition(effect_key, 'failed', 'executor', actor, expected_from='reserved',
                                result=EffectResult('not_performed', None), detail={'reason': reason})

    def _transition(self, effect_key: str, to_state: str, origin: str, actor: str, *,
                    result: EffectResult | None = None, detail: Mapping | None = None,
                    expected_from: str | None = None, epoch_id: int | None = None,
                    in_transaction: bool = False) -> Receipt:
        _check_text('actor', actor, 256)
        if to_state not in STATES:
            raise IllegalTransition(f'unknown state {to_state!r}')
        if to_state in ('completed', 'failed'):
            if not isinstance(result, EffectResult):
                raise StoreError(f'{to_state} needs the observed effect result')
            if (to_state == 'completed') != (result.outcome == 'performed'):
                raise StoreError(f'{to_state} does not match outcome {result.outcome!r}')
        result_json = result.to_json() if result is not None else None
        detail_value = None if detail is None else json.loads(_canonical(dict(detail)))

        def apply() -> Receipt:
            current = self.get(effect_key)
            if current is None:
                raise UnknownEffect(f'no receipt for {effect_key!r}')
            if expected_from is not None and current.state != expected_from:
                raise IllegalTransition(f'{effect_key} is {current.state}, not the expected {expected_from}')
            if (current.state, to_state, origin) not in TRANSITIONS:
                raise IllegalTransition(f'{current.state} -> {to_state} is not allowed for {origin}')
            if to_state == 'applying' and self.open_epochs():
                raise RestoreEpochOpen('a restore epoch is open: no effect may start until it is reconciled')
            if to_state == 'unknown':
                status = 'required'
            elif current.state == 'unknown' or origin != 'executor':
                status = 'reconciled'
            else:
                status = current.reconciliation_status
            _append_event(self.conn, 'receipt_transition', actor, effect_key=effect_key, epoch_id=epoch_id,
                          from_state=current.state, to_state=to_state, origin=origin,
                          detail={'result': None if result_json is None else json.loads(result_json),
                                  'detail': detail_value})
            self.conn.execute(
                'UPDATE effect_receipt SET state = ?, reconciliation_status = ?, state_seq = ?, '
                'result_json = coalesce(result_json, ?), updated_at = ? WHERE effect_key = ? AND state_seq = ?',
                (to_state, status, current.state_seq + 1, result_json, storecore.now(), effect_key,
                 current.state_seq))
            return self.get(effect_key)

        if in_transaction:
            return apply()
        with storecore.write_transaction(self.conn):
            return apply()

    # -- reconciliation and restore epochs ----------------------------------

    def _record(self, effect_key: str, verdict: str, action: str, probe: Mapping, actor: str,
                epoch_id: int | None) -> None:
        seq = _append_event(self.conn, 'reconciliation', actor, effect_key=effect_key, epoch_id=epoch_id,
                            detail={'verdict': verdict, 'action': action, 'probe': probe})
        self.conn.execute('INSERT INTO reconciliation_record (seq, epoch_id, effect_key, verdict, action, probe_json, '
                          'actor, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                          (seq, epoch_id, effect_key, verdict, action, _canonical(probe), actor, storecore.now()))

    def reconcile(self, oracle: Callable[[str, Mapping], Probe], *, actor: str,
                  candidates: Sequence[EffectRequest] = ()) -> dict:
        """Check effects whose outcome is uncertain against the observed target.

        For each ``applying`` or ``unknown`` receipt, and, while a restore epoch is
        open, each ``reserved`` receipt not yet checked in that epoch, the key is
        re-derived from its recorded inputs (a mismatch refuses everything) and
        ``oracle(key, key_inputs)`` probes the target:

        * performed -> ``completed`` (origin reconciliation; never re-executed);
        * not performed -> ``failed`` for applying/unknown; a reserved receipt is
          cleared for normal processing (no state change);
        * indeterminate -> ``unknown``; nothing further happens for it until a
          recorded Owner attestation (``attest``) resolves it.

        ``candidates`` are effect requests the caller still holds (for example the
        executor's pending work after a restore) whose receipts may have been lost
        with the restore: absent keys the target shows performed get an
        ``observed`` receipt; indeterminate ones an ``unknown`` receipt; not
        performed ones are recorded as cleared. Each item is one transaction.
        """
        _check_text('actor', actor, 256)
        epochs = self.open_epochs()
        epoch_id = epochs[-1]['epoch_id'] if epochs else None
        report = {'epoch_id': epoch_id, 'completed': [], 'failed': [], 'cleared': [], 'unknown': [],
                  'observed_created': [], 'unknown_created': [], 'already_recorded': []}

        def probe_for(key: str, key_inputs: Mapping) -> Probe:
            probe = oracle(key, key_inputs)
            if not isinstance(probe, Probe) or probe.verdict not in VERDICTS:
                raise StoreError(f'oracle must return a Probe with a verdict in {VERDICTS}: {probe!r}')
            return probe

        checked = {r['effect_key'] for r in self.reconciliation_records()
                   if epoch_id is not None and r['epoch_id'] == epoch_id}
        targets = [r for r in self.receipts(['applying', 'unknown', 'reserved'])
                   if r.state != 'reserved' or (epoch_id is not None and r.effect_key not in checked)]
        for receipt in targets:
            key_inputs = json.loads(receipt.key_inputs_json)
            if derive_effect_key(key_inputs) != receipt.effect_key:
                raise ChainError(f'KEY_MISMATCH: {receipt.effect_key} is not derived from its recorded inputs')
            probe = probe_for(receipt.effect_key, key_inputs)
            observation = {'oracle': probe.oracle, 'observation': dict(probe.observation)}
            with storecore.write_transaction(self.conn):
                if probe.verdict == 'performed':
                    self._record(receipt.effect_key, 'performed', 'transitioned', observation, actor, epoch_id)
                    self._transition(receipt.effect_key, 'completed', 'reconciliation', actor, epoch_id=epoch_id,
                                     result=EffectResult('performed', dict(probe.observation)),
                                     expected_from=receipt.state, in_transaction=True)
                    report['completed'].append(receipt.effect_key)
                elif probe.verdict == 'not_performed' and receipt.state == 'reserved':
                    self._record(receipt.effect_key, 'not_performed', 'cleared', observation, actor, epoch_id)
                    report['cleared'].append(receipt.effect_key)
                elif probe.verdict == 'not_performed':
                    self._record(receipt.effect_key, 'not_performed', 'transitioned', observation, actor, epoch_id)
                    self._transition(receipt.effect_key, 'failed', 'reconciliation', actor, epoch_id=epoch_id,
                                     result=EffectResult('not_performed', dict(probe.observation)),
                                     expected_from=receipt.state, in_transaction=True)
                    report['failed'].append(receipt.effect_key)
                elif receipt.state == 'unknown':
                    self._record(receipt.effect_key, 'indeterminate', 'left_unknown', observation, actor, epoch_id)
                    report['unknown'].append(receipt.effect_key)
                else:
                    self._record(receipt.effect_key, 'indeterminate', 'transitioned', observation, actor, epoch_id)
                    self._transition(receipt.effect_key, 'unknown', 'reconciliation', actor, epoch_id=epoch_id,
                                     detail={'probe': observation}, expected_from=receipt.state,
                                     in_transaction=True)
                    report['unknown'].append(receipt.effect_key)
        for request in candidates:
            key_inputs = request.key_inputs()
            key = derive_effect_key(key_inputs)
            if self.get(key) is not None:
                report['already_recorded'].append(key)
                continue
            probe = probe_for(key, key_inputs)
            observation = {'oracle': probe.oracle, 'observation': dict(probe.observation)}
            canonical = _canonical(key_inputs)
            with storecore.write_transaction(self.conn):
                if probe.verdict == 'performed':
                    self._record(key, 'performed', 'observed_receipt_created', observation, actor, epoch_id)
                    self._insert_receipt(key, key_inputs, canonical, 'reconciliation', 'observed', actor,
                                         EffectResult('performed', dict(probe.observation)).to_json(), epoch_id)
                    report['observed_created'].append(key)
                elif probe.verdict == 'not_performed':
                    self._record(key, 'not_performed', 'cleared', observation, actor, epoch_id)
                    report['cleared'].append(key)
                else:
                    self._record(key, 'indeterminate', 'unknown_receipt_created', observation, actor, epoch_id)
                    self._insert_receipt(key, key_inputs, canonical, 'reconciliation', 'unknown', actor, None,
                                         epoch_id)
                    report['unknown_created'].append(key)
        return report

    def attest(self, effect_key: str, *, outcome: str, attested_by: str, statement: str,
               observation: Mapping | None = None) -> Receipt:
        """Resolve a permanently unknown outcome by a recorded Owner attestation."""
        if outcome not in ('performed', 'not_performed'):
            raise StoreError('outcome must be performed or not_performed')
        _check_text('attested_by', attested_by, 256)
        _check_text('statement', statement, 4096)
        epochs = self.open_epochs()
        epoch_id = epochs[-1]['epoch_id'] if epochs else None
        attestation = {'attested_by': attested_by, 'statement': statement,
                       'observation': None if observation is None else dict(observation)}
        with storecore.write_transaction(self.conn):
            receipt = self.get(effect_key)
            if receipt is None or receipt.state != 'unknown':
                raise IllegalTransition(f'only an unknown receipt can be attested: {effect_key} is '
                                        f'{receipt.state if receipt else "absent"}')
            self._record(effect_key, f'attested_{outcome}', 'transitioned', attestation, attested_by, epoch_id)
            return self._transition(effect_key, 'completed' if outcome == 'performed' else 'failed',
                                    'owner_attestation', attested_by, epoch_id=epoch_id,
                                    result=EffectResult(outcome, attestation['observation']),
                                    detail={'attestation': attestation}, expected_from='unknown',
                                    in_transaction=True)

    def close_epoch(self, *, actor: str) -> list[int]:
        """Close every open restore epoch, or refuse (EpochNotReconciled).

        Refused while any receipt is ``applying`` or ``unknown``, or any
        ``reserved`` receipt has not been checked against the target in an open
        epoch.
        """
        _check_text('actor', actor, 256)
        with storecore.write_transaction(self.conn):
            epochs = self.open_epochs()
            if not epochs:
                raise StoreError('no restore epoch is open')
            unresolved = self.receipts(['applying', 'unknown'])
            if unresolved:
                raise EpochNotReconciled(
                    f'{len(unresolved)} receipt(s) applying or unknown: '
                    f'{[r.effect_key for r in unresolved][:10]}; reconcile them (or attest) first')
            open_ids = [e['epoch_id'] for e in epochs]
            checked = {r['effect_key'] for r in self.reconciliation_records() if r['epoch_id'] in open_ids}
            unchecked = [r.effect_key for r in self.receipts(['reserved']) if r.effect_key not in checked]
            if unchecked:
                raise EpochNotReconciled(f'{len(unchecked)} reserved receipt(s) not yet checked against the '
                                         f'target: {unchecked[:10]}')
            summary = {'receipt_states': dict(self.conn.execute(
                           'SELECT state, count(*) FROM effect_receipt GROUP BY state').fetchall()),
                       'reconciliation_records': len([r for r in self.reconciliation_records()
                                                      if r['epoch_id'] in open_ids])}
            for epoch in epochs:
                seq = _append_event(self.conn, 'epoch_closed', actor, epoch_id=epoch['epoch_id'], detail=summary)
                self.conn.execute('INSERT INTO restore_epoch_closure (epoch_id, closed_seq, actor, closed_at, '
                                  'summary_json) VALUES (?, ?, ?, ?, ?)',
                                  (epoch['epoch_id'], seq, actor, storecore.now(), _canonical(summary)))
            return open_ids

    # -- backup ---------------------------------------------------------------

    def backup(self, *, actor: str) -> dict:
        """Back up into ``<root>/backups/`` (same custody); return the manifest."""
        backups = self.root / BACKUPS_DIR
        custody.check_path(backups, self.template, is_root=False)
        manifest = storecore.backup_store(self.conn, KIND, backups, actor=actor)
        custody.check_path(backups / manifest['backup_file'], self.template, is_root=False)
        return manifest

    def prune_backups(self, *, keep_last: int, older_than_days: float | None = None) -> list[str]:
        """Retention: never the newest backup, never an open epoch's source, never receipts."""
        protected = [e['backup_file'] for e in self.open_epochs()]
        return storecore.prune_backups(self.root / BACKUPS_DIR, KIND, keep_last=keep_last,
                                       older_than_days=older_than_days, protected=protected)

    # -- evidence -------------------------------------------------------------

    def canonical_dump(self) -> bytes:
        return canonical_dump(self.conn)

    def summary(self) -> dict:
        return {
            'path': str(self.path),
            'store_kind': KIND.name,
            'application_id': self.conn.execute('PRAGMA application_id').fetchone()[0],
            'location_policy': self.policy.name,
            'custody_template': self.template.describe(),
            'sqlite_version': sqlite3.sqlite_version,
            'schema_version': self.schema_version(),
            'migrations': [{'version': v, 'name': n, 'sha256': s} for v, n, s in self.conn.execute(
                'SELECT version, name, sha256 FROM schema_migration ORDER BY version')],
            'pragmas': storecore.pragmas(self.conn),
            'receipts': dict(self.conn.execute('SELECT state, count(*) FROM effect_receipt GROUP BY state')),
            'high_water_mark': self.high_water_mark(),
            'chain_head': self.chain_head(),
            'open_restore_epochs': [e['epoch_id'] for e in self.open_epochs()],
            'reconciliation_required': self.reconciliation_required(),
        }


# ---------------------------------------------------------------------------
# Command line: the live location policy only; no default root; no network surface.

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='effects_store.py', description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)

    def command(name: str, text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=text)
        p.add_argument('--root', required=True, help='the Owner-created effects root (never created by this tool)')
        p.add_argument('--principal', default=None,
                       help='SID of the configured executor principal in the custody template (default: none, '
                            'the interim SYSTEM and Administrators template)')
        return p

    command('init', 'create or migrate effects.sqlite inside an existing root; print a JSON summary')
    command('status', 'print the store summary (read-only)')
    backup = command('backup', 'back up into <root>/backups/; print the manifest')
    backup.add_argument('--actor', required=True)
    restore = command('restore', 'restore a verified backup (Owner act, executor stopped); print the report')
    restore.add_argument('--manifest', required=True, help='the backup manifest (<backup>.manifest.json)')
    restore.add_argument('--actor', required=True)
    restore.add_argument('--accept-rollback', action='store_true',
                         help='explicitly accept losing live history that is ahead of or diverges from the backup '
                              '(the live content is still preserved aside)')
    command('verify-chain', 'verify the journal hash chain and every receipt; print the chain head')
    args = parser.parse_args(argv)

    options = {'principal': args.principal, 'policy': LIVE_POLICY}
    try:
        if args.command == 'init':
            output = init_effects_store(args.root, **options)
        elif args.command == 'restore':
            report = restore_effects_store(args.root, args.manifest, actor=args.actor,
                                           accept_rollback=args.accept_rollback, **options)
            with open_effects_store(args.root, **options) as store:
                output = {'restore': dataclasses.asdict(report), 'store': store.summary()}
        else:
            with open_effects_store(args.root, **options) as store:
                if args.command == 'status':
                    output = store.summary()
                elif args.command == 'backup':
                    output = store.backup(actor=args.actor)
                else:
                    output = store.verify_chain()
    except (StoreError, CustodyRefused) as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
