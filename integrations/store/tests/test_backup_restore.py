"""Backup, restore, restore epochs and projection rebuilds for the integration store (F-05.2).

Run from the repository root:

    python -I -B -m unittest discover -s integrations/store/tests -v

Every database and the synthetic canonical-source repository live in a fresh
temporary directory outside the checkout. The synthetic repository is a real git
repository holding OpenSpec-shaped and Backlog.md-shaped files; it stands in for
OpenSpec and Backlog.md until they are adopted (decision 0004, point 8).
"""
from pathlib import Path
import dataclasses
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
STORE_DIR = HERE.parent
MODULE = STORE_DIR / 'integration_store.py'
WORKER = HERE / 'store_worker.py'

_spec = importlib.util.spec_from_file_location('integration_store', MODULE)
store_mod = importlib.util.module_from_spec(_spec)
sys.modules['integration_store'] = store_mod
_spec.loader.exec_module(store_mod)
storecore = store_mod.storecore

WAIT_CEILING_S = 60
INTENT = {'scoped_resources': {'repository': 'example/repo'}, 'request': {'agent': 'builder'}}


def manifest_path_for(db, manifest):
    return Path(db).parent / 'backups' / (manifest['backup_file'] + '.manifest.json')


class OracleFixture:
    """Stands in for the external system (OpenHands, E-01.4.x): verdict per operation key."""

    def __init__(self, verdicts):
        self.verdicts = verdicts

    def __call__(self, reservation):
        return self.verdicts[reservation.operation_key]


def _remove_tree(path):
    """rmtree that also removes read-only files (git writes its objects read-only)."""
    def make_writable(function, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        function(target)
    if path.exists():
        shutil.rmtree(path, onexc=make_writable)


class IntegrationBackupTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-store-backup-test-'))
        self.addCleanup(_remove_tree, self.tmp)
        self.db = self.tmp / 'state' / 'integration.sqlite'
        self.db.parent.mkdir()

    def open(self, **kwargs):
        store = store_mod.open_store(self.db, **kwargs)
        self.addCleanup(store.close)
        return store


class BackupRestoreTests(IntegrationBackupTestCase):
    def test_backup_more_attempts_restore_epoch_reconcile_and_close(self):
        store = self.open()
        store.reserve('op-confirmed', INTENT, actor='t')
        store.transition('op-confirmed', 'dispatched', actor='t')
        store.transition('op-confirmed', 'confirmed', actor='t')
        store.reserve('op-dispatched', {**INTENT, 'n': 2}, actor='t')
        store.transition('op-dispatched', 'dispatched', actor='t')
        store.reserve('op-reserved', {**INTENT, 'n': 3}, actor='t')
        manifest = store.backup(actor='owner')
        self.assertEqual((manifest['store_kind'], manifest['application_id'], manifest['chain_head']),
                         ('integration', store_mod.APPLICATION_ID, None))
        self.assertEqual(manifest['high_water_mark'], store.high_water_mark())
        at_backup = {t: store.conn.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall()
                     for t in ('attempt', 'attempt_event')}
        hw_b = store.high_water_mark()

        store.reserve('op-lost', {**INTENT, 'n': 4}, actor='t')  # the lost tail
        store.transition('op-lost', 'dispatched', actor='t')
        live_hw, live_digest = store.high_water_mark(), store.history_digest()
        live_dump = store.canonical_dump()
        store.close()

        path = manifest_path_for(self.db, manifest)
        with self.assertRaisesRegex(store_mod.RollbackRefused, 'ROLLBACK_REFUSED: the live store is ahead'):
            store_mod.restore_store(self.db, path, actor='owner')
        with self.open() as unchanged:
            self.assertEqual(unchanged.canonical_dump(), live_dump)
        self.assertEqual(os.listdir(self.db.parent / 'backups' / 'superseded'), [])

        report = store_mod.restore_store(self.db, path, actor='owner', accept_rollback=True)
        self.assertEqual(report.previous_live['high_water_mark'], live_hw)
        aside = self.db.parent / 'backups' / 'superseded' / report.superseded_copy
        ro = storecore.open_read_only(aside)
        self.assertEqual(store_mod._history_digest(ro, live_hw), live_digest)
        self.assertIsNotNone(ro.execute("SELECT 1 FROM attempt WHERE operation_key = 'op-lost'").fetchone())
        ro.close()

        restored = self.open()
        for table, rows in at_backup.items():
            self.assertEqual(restored.conn.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall(), rows, table)
        self.assertEqual(restored.high_water_mark(), hw_b)
        [epoch] = restored.open_epochs()
        self.assertEqual((epoch['backup_file'], epoch['backup_high_water'], epoch['previous_live_high_water'],
                          epoch['previous_live_history_digest'], epoch['rollback_accepted'],
                          epoch['reconciliation_status']),
                         (manifest['backup_file'], hw_b, live_hw, live_digest, 1, 'required'))

        with self.assertRaises(store_mod.RestoreEpochOpen):
            restored.reserve('op-new', {**INTENT, 'n': 5}, actor='t')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'restore epoch is open'):
            restored._insert_reservation('op-new', '{}', '0' * 64, 't')
        self.assertEqual(restored.reserve('op-reserved', {**INTENT, 'n': 3}, actor='t').created, False)
        with self.assertRaises(store_mod.EpochNotReconciled):
            restored.close_restore_epoch(actor='owner')

        result = restored.reconcile(OracleFixture({'op-dispatched': 'performed'}), actor='reconciler')
        self.assertEqual(result, {'confirmed': ['op-dispatched'], 'failed': [], 'still_unknown': []})
        self.assertEqual([e.to_state for e in restored.events('op-dispatched')],
                         ['reserved', 'dispatched', 'unknown', 'confirmed'])
        self.assertEqual(restored.close_restore_epoch(actor='owner', summary={'oracle': 'fixture'}),
                         [epoch['epoch_id']])
        self.assertTrue(restored.reserve('op-new', {**INTENT, 'n': 5}, actor='t').created)
        self.assertIsNone(restored.get('op-lost'))  # knowledge lost; its dispatch was not

    def test_indeterminate_outcome_keeps_the_epoch_open(self):
        store = self.open()
        store.reserve('op-x', INTENT, actor='t')
        store.transition('op-x', 'dispatched', actor='t')
        manifest = store.backup(actor='owner')
        store.close()
        store_mod.restore_store(self.db, manifest_path_for(self.db, manifest), actor='owner')
        restored = self.open()
        self.assertEqual(restored.reconcile(OracleFixture({'op-x': 'indeterminate'}), actor='r')['still_unknown'],
                         ['op-x'])
        with self.assertRaises(store_mod.EpochNotReconciled):
            restored.close_restore_epoch(actor='owner')
        restored.reconcile(OracleFixture({'op-x': 'not_performed'}), actor='r')
        self.assertEqual(restored.get('op-x').state, 'failed')
        restored.close_restore_epoch(actor='owner')

    def test_restore_needs_exclusive_custody(self):
        store = self.open()
        store.reserve('op-1', INTENT, actor='t')
        manifest = store.backup(actor='owner')
        store.close()
        proc = subprocess.Popen([sys.executable, '-I', '-B', str(WORKER), 'contend', str(self.db), 'op-held',
                                 json.dumps(INTENT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding='utf-8')
        try:
            self.assertEqual(json.loads(proc.stdout.readline()), {'ready': True})  # it holds the store open
            with self.assertRaisesRegex(store_mod.RestoreRefused, 'EXCLUSIVE_CUSTODY'):
                store_mod.restore_store(self.db, manifest_path_for(self.db, manifest), actor='owner')
        finally:
            proc.kill()
            proc.wait(timeout=WAIT_CEILING_S)
            proc.stdout.close(), proc.stderr.close(), proc.stdin.close()
        with self.open() as unchanged:
            self.assertEqual(unchanged.open_epochs(), [])

    def test_older_backup_is_migrated_after_restore(self):
        v1 = self.tmp / 'migrations-v1'
        v1.mkdir()
        shutil.copy2(store_mod.MIGRATIONS_DIR / '0001_receipts_and_projections.sql', v1)
        with self.open(migrations_dir=v1) as old:
            self.assertEqual((old.schema_version(), old.conn.execute('PRAGMA application_id').fetchone()[0]), (1, 0))
            old.reserve('op-old', INTENT, actor='t')
            manifest = storecore.backup_store(old.conn, store_mod.KIND, self._backups(), actor='owner')
        self.assertEqual((manifest['schema_version'], manifest['application_id']), (1, 0))
        report = store_mod.restore_store(self.db, manifest_path_for(self.db, manifest), actor='owner')
        self.assertEqual(report.migrated, [m.name for m in store_mod.load_migrations()[1:]])
        self.assertEqual(report.migrated[0], '0002_store_identity_and_restore_epochs.sql')
        with self.open() as restored:
            self.assertEqual(restored.schema_version(), len(store_mod.load_migrations()))
            self.assertEqual(restored.conn.execute('PRAGMA application_id').fetchone()[0], store_mod.APPLICATION_ID)
            self.assertEqual(len(restored.open_epochs()), 1)
            self.assertEqual(restored.get('op-old').state, 'reserved')

    def _backups(self):
        backups = self.db.parent / 'backups'
        backups.mkdir(exist_ok=True)
        return backups

    def test_retention_keeps_the_newest_and_an_open_epochs_source(self):
        store = self.open()
        store.reserve('op-1', INTENT, actor='t')
        first = store.backup(actor='owner')
        second = store.backup(actor='owner')
        third = store.backup(actor='owner')
        store.close()
        store_mod.restore_store(self.db, manifest_path_for(self.db, first), actor='owner')
        with self.open() as restored:
            self.assertEqual(restored.prune_backups(keep_last=1), [second['backup_file']])
            self.assertEqual(sorted(p.name for p in (self.db.parent / 'backups').glob('*.sqlite')),
                             sorted([first['backup_file'], third['backup_file']]))
            self.assertEqual(restored.prune_backups(keep_last=1, older_than_days=1), [])


class ManifestCheckTests(IntegrationBackupTestCase):
    def setUp(self):
        super().setUp()
        with self.open() as store:
            store.reserve('op-1', INTENT, actor='t')
            self.manifest = store.backup(actor='owner')
        self.path = manifest_path_for(self.db, self.manifest)

    def assert_live_unchanged(self, before):
        with self.open() as live:
            self.assertEqual(live.canonical_dump(), before)
            self.assertEqual(live.open_epochs(), [])

    def test_tampered_backup_is_refused(self):
        with self.open() as live:
            before = live.canonical_dump()
        backup = self.path.with_name(self.manifest['backup_file'])
        data = bytearray(backup.read_bytes())
        data[-200] ^= 0x01
        backup.write_bytes(bytes(data))
        with self.assertRaisesRegex(store_mod.BackupError, 'BACKUP_TAMPERED'):
            store_mod.restore_store(self.db, self.path, actor='owner', accept_rollback=True)
        self.assert_live_unchanged(before)

    def test_newer_schema_backup_is_refused(self):
        migrations = self.tmp / 'migrations-newer'
        shutil.copytree(store_mod.MIGRATIONS_DIR, migrations)
        current = len(store_mod.load_migrations())
        (migrations / f'{current + 1:04d}_future.sql').write_text(
            'CREATE TABLE future_thing (id INTEGER PRIMARY KEY) STRICT;\n', encoding='utf-8')
        newer_db = self.tmp / 'newer' / 'integration.sqlite'
        newer_db.parent.mkdir()
        with store_mod.open_store(newer_db, migrations_dir=migrations) as newer:
            manifest = newer.backup(actor='owner')
        self.assertEqual(manifest['schema_version'], current + 1)
        with self.open() as live:
            before = live.canonical_dump()
        with self.assertRaisesRegex(store_mod.MigrationError, 'BACKUP_SCHEMA_NEWER'):
            store_mod.restore_store(self.db, manifest_path_for(newer_db, manifest), actor='owner',
                                    accept_rollback=True)
        self.assert_live_unchanged(before)

    def test_cli_backup_and_restore_round_trip(self):
        cmd = [sys.executable, '-I', '-B', str(MODULE)]
        backup = subprocess.run(cmd + ['backup', '--db', str(self.db), '--actor', 'owner'], capture_output=True,
                                text=True, encoding='utf-8', timeout=WAIT_CEILING_S)
        self.assertEqual(backup.returncode, 0, backup.stderr)
        manifest = json.loads(backup.stdout)
        self.assertEqual(manifest['integrity_check'], 'ok')
        restore = subprocess.run(cmd + ['restore', '--db', str(self.db), '--manifest',
                                        str(manifest_path_for(self.db, manifest)), '--actor', 'owner'],
                                 capture_output=True, text=True, encoding='utf-8', timeout=WAIT_CEILING_S)
        self.assertEqual(restore.returncode, 0, restore.stderr)
        output = json.loads(restore.stdout)
        self.assertEqual(output['store']['open_restore_epochs'], [1])
        self.assertIsNone(output['restore']['rollback'])
        with self.open() as store:  # make the live store ahead of the backup
            store.reconcile(lambda r: 'performed', actor='r')
            store.close_restore_epoch(actor='owner')
            store.reserve('op-2', {**INTENT, 'n': 2}, actor='t')
        args = cmd + ['restore', '--db', str(self.db), '--manifest', str(manifest_path_for(self.db, manifest)),
                      '--actor', 'owner']
        again = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=WAIT_CEILING_S)
        self.assertEqual(again.returncode, 1)
        self.assertIn('REFUSED: ROLLBACK_REFUSED: the live store is ahead', again.stderr)
        accepted = subprocess.run(args + ['--accept-rollback'], capture_output=True, text=True, encoding='utf-8',
                                  timeout=WAIT_CEILING_S)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertTrue(json.loads(accepted.stdout)['restore']['rollback_accepted'])
        self.assertEqual(len(list((self.db.parent / 'backups' / 'superseded').glob('*.sqlite'))), 2)
        missing = subprocess.run(cmd + ['backup', '--db', str(self.tmp / 'none.sqlite'), '--actor', 'o'],
                                 capture_output=True, text=True, encoding='utf-8', timeout=WAIT_CEILING_S)
        self.assertEqual(missing.returncode, 1)
        self.assertFalse((self.tmp / 'none.sqlite').exists())


# ---------------------------------------------------------------------------
# Projection rebuild from a synthetic canonical-source repository

GIT_ENV = {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_AUTHOR_NAME': 'Fixture',
           'GIT_AUTHOR_EMAIL': 'fixture@example.invalid', 'GIT_COMMITTER_NAME': 'Fixture',
           'GIT_COMMITTER_EMAIL': 'fixture@example.invalid', 'GIT_AUTHOR_DATE': '2026-11-06T00:00:00Z',
           'GIT_COMMITTER_DATE': '2026-11-06T00:00:00Z'}

SYNTHETIC_FILES = {
    'openspec/project.md': '# Project\n\nSynthetic OpenSpec project for the F-05.2 projection fixture.\n',
    'openspec/specs/effects-journal/spec.md': (
        '# effects-journal Specification\n\n## Requirements\n\n### Requirement: Receipts survive restore\n'
        'The store SHALL keep every receipt present at backup time.\n'),
    'openspec/changes/add-restore-epoch/proposal.md': (
        '# Change: Add restore epochs\n\n## Why\nA restore loses knowledge, never effects.\n'),
    'openspec/changes/add-restore-epoch/tasks.md': '## 1. Implementation\n- [x] 1.1 Epoch table\n- [ ] 1.2 Gate\n',
    'backlog/config.yml': 'project_name: "fixture"\n',
    'backlog/tasks/task-1 - Back-up-the-store.md': (
        '---\nid: task-1\ntitle: Back up the store\nstatus: Done\nlabels: [store]\n---\n\n## Description\nBackup.\n'),
    'backlog/tasks/task-2 - Reconcile-after-restore.md': (
        '---\nid: task-2\ntitle: Reconcile after restore\nstatus: In Progress\n---\n\n## Description\nEpoch.\n'),
    'README.md': 'Synthetic canonical-source repository (test fixture).\n',
}


def git(repo, *args, binary=False):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, timeout=WAIT_CEILING_S,
                            env={**os.environ, **GIT_ENV})
    if result.returncode != 0:
        raise AssertionError(f'git {args} failed: {result.stderr.decode("utf-8", "replace")}')
    return result.stdout if binary else result.stdout.decode('utf-8')


def make_synthetic_repo(path):
    path.mkdir()
    git(path, 'init', '-q', '-b', 'main')
    for name, text in SYNTHETIC_FILES.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode('utf-8'))
    git(path, 'add', '-A')
    git(path, 'commit', '-q', '-m', 'Synthetic OpenSpec and Backlog content')
    return path


def repository_state(repo):
    """Everything the rebuild must leave unchanged: HEAD, tree, refs, status and every file's bytes."""
    files = {}
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d != '.git']
        for filename in filenames:
            full = Path(dirpath) / filename
            files[full.relative_to(repo).as_posix()] = hashlib.sha256(full.read_bytes()).hexdigest()
    return {'head': git(repo, 'rev-parse', 'HEAD').strip(), 'tree': git(repo, 'rev-parse', 'HEAD^{tree}').strip(),
            'refs': git(repo, 'for-each-ref', '--format=%(refname) %(objectname)'),
            'status': git(repo, 'status', '--porcelain=v1', '--untracked-files=all'), 'files': files}


_FRONTMATTER = re.compile(r'^---\n(.*?)\n---\n', re.S)


def repository_projection(repo):
    """A projection of OpenSpec- and Backlog-shaped files, read from git objects only
    (``ls-tree`` and ``cat-file``: nothing in the repository is written)."""
    def populate(conn):
        head = git(repo, 'rev-parse', 'HEAD').strip()
        entries = git(repo, 'ls-tree', '-r', '-z', '--full-tree', head).split('\0')
        files = items = 0
        for entry in filter(None, entries):
            meta, path = entry.split('\t', 1)
            _mode, kind, oid = meta.split()
            if kind != 'blob':
                continue
            files += 1
            text = git(repo, 'cat-file', 'blob', oid, binary=True).decode('utf-8')
            parts = path.split('/')
            row = None
            if parts[:2] == ['openspec', 'changes'] and len(parts) == 4 and parts[3] == 'proposal.md':
                title = text.splitlines()[0].lstrip('# ').strip()
                done = len(re.findall(r'^- \[x\]', git(repo, 'cat-file', 'blob', f'{head}:openspec/changes/'
                                                       f'{parts[2]}/tasks.md'), re.M))
                row = ('openspec-change', parts[2], title, f'tasks done: {done}')
            elif parts[:2] == ['openspec', 'specs'] and len(parts) == 4 and parts[3] == 'spec.md':
                row = ('openspec-spec', parts[2], text.splitlines()[0].lstrip('# ').strip(), None)
            elif parts[:2] == ['backlog', 'tasks'] and path.endswith('.md'):
                fields = dict(line.split(': ', 1) for line in _FRONTMATTER.match(text).group(1).splitlines())
                row = ('backlog-task', fields['id'], fields['title'], fields['status'])
            if row:
                conn.execute('INSERT INTO proj_workitems (path, kind, item_id, title, status, blob) '
                             'VALUES (?, ?, ?, ?, ?, ?)', (path, *row, oid))
                items += 1
        return head, {'files': files, 'items': items, 'complete': True}
    return store_mod.Projection(
        name='workitems', source='synthetic-git-repository',
        tables=('proj_workitems',),
        ddl=('CREATE TABLE proj_workitems (path TEXT PRIMARY KEY, kind TEXT NOT NULL, item_id TEXT NOT NULL, '
             'title TEXT NOT NULL, status TEXT, blob TEXT NOT NULL) STRICT',
             'CREATE INDEX proj_workitems_by_kind ON proj_workitems (kind, item_id)'),
        populate=populate)


class RepositoryProjectionTests(IntegrationBackupTestCase):
    def test_rebuild_from_the_synthetic_repository_changes_neither_repository_nor_canonical_tables(self):
        repo = make_synthetic_repo(self.tmp / 'canonical-source')
        store = self.open()
        store.reserve('op-1', INTENT, actor='t')
        store.transition('op-1', 'dispatched', actor='t')
        repo_before = repository_state(repo)
        canonical_before = store.canonical_dump()
        projection = repository_projection(repo)

        store.rebuild_projection(projection)
        rows = store.conn.execute('SELECT kind, item_id, title, status FROM proj_workitems ORDER BY 1, 2').fetchall()
        self.assertEqual(rows, [
            ('backlog-task', 'task-1', 'Back up the store', 'Done'),
            ('backlog-task', 'task-2', 'Reconcile after restore', 'In Progress'),
            ('openspec-change', 'add-restore-epoch', 'Change: Add restore epochs', 'tasks done: 1'),
            ('openspec-spec', 'effects-journal', 'effects-journal Specification', None)])
        name, source, cursor, coverage, _ = store.projection_cursor('workitems')
        self.assertEqual((source, cursor), ('synthetic-git-repository', repo_before['head']))
        self.assertEqual(json.loads(coverage), {'complete': True, 'files': len(SYNTHETIC_FILES), 'items': 4})
        self.assertEqual(repository_state(repo), repo_before)
        self.assertEqual(store.canonical_dump(), canonical_before)

        # Restore drops the projections and marks them stale; the rebuild restores them.
        manifest = store.backup(actor='owner')
        store.close()
        report = store_mod.restore_store(self.db, manifest_path_for(self.db, manifest), actor='owner')
        restored = self.open()
        self.assertIsNone(restored.projection_cursor('workitems'))
        self.assertIsNone(restored.conn.execute(
            "SELECT name FROM sqlite_schema WHERE name = 'proj_workitems'").fetchone())
        self.assertEqual(json.loads(restored.open_epochs()[0]['projections_dropped_json']), ['proj_workitems'])
        self.assertIsNone(report.rollback)
        canonical_restored = restored.canonical_dump()
        restored.rebuild_projection(repository_projection(repo))
        self.assertEqual(restored.conn.execute(
            'SELECT kind, item_id, title, status FROM proj_workitems ORDER BY 1, 2').fetchall(), rows)
        self.assertEqual(restored.canonical_dump(), canonical_restored)
        self.assertEqual(repository_state(repo), repo_before)


if __name__ == '__main__':
    unittest.main()
