"""The repository-access module's commit write (decision 0014 sections 6 and 8; first needed by plan
leaf P-04.1, the acceptance recorder).

Run from the repository root, under the tools interpreter (Dulwich is required: without it these
tests fail with REPOSITORY_NEEDS_DULWICH, never skip):

    <tools python> -I -B -m unittest discover -s integrations/repository/tests -v

``Repository.write_commit`` builds the commit as objects plus a compare-and-set update of the
branch, runs no hook (a repository with client hooks is refused), launches no process, and brings
the work tree and the index to the commit. git (which builds the fixture) is the oracle: ``fsck
--strict`` accepts the result, ``status`` is clean, the reflogs carry the commit, and a later
``git commit`` keeps the change (no stale cache-tree survives in the index).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import repository_corpus as rc  # noqa: E402  (puts integrations/repository on sys.path)
import repository_access as ra  # noqa: E402

IDENTITY = 'Fixture Recorder <recorder@example.invalid>'
WHEN = (1794312000, 3600)  # 2026-11-10T12:00:00Z, +01:00


def _base(directory):
    """A small git-built repository: main with two commits, a nested file and an index that git
    wrote (with its cache-tree extension)."""
    repo = Path(directory)
    repo.mkdir()
    rc.git(repo, 'init', '--quiet', '-b', 'main')
    rc.write(repo, {'a/x.txt': b'x\n', 'top.txt': b't\n', 'a/b/keep.md': b'keep\n'})
    rc.git(repo, 'add', '--all')
    rc.git(repo, 'commit', '--quiet', '-m', 'one', date=rc.date(1))
    return rc.out(repo, 'rev-parse', 'HEAD')


class WriteCommit(unittest.TestCase):
    """The commit, its refusals, and git's view of the result."""

    @classmethod
    def setUpClass(cls):
        ra.dulwich_modules()  # fail, never skip, without Dulwich
        cls.golden_root = Path(tempfile.mkdtemp(prefix='rc-'))
        cls.head = _base(cls.golden_root / 'g')

    @classmethod
    def tearDownClass(cls):
        rc.rmtree(cls.golden_root)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='rc-'))
        self.addCleanup(rc.rmtree, self.root)
        self.repo = self.root / 'r'
        shutil.copytree(self.golden_root / 'g', self.repo)

    def open(self):
        return ra.open_repository(self.repo, config='repository', ceilings=[str(self.root)])

    def commit(self, files, **kwargs):
        kwargs.setdefault('identity', IDENTITY)
        kwargs.setdefault('expected_head', self.head)
        kwargs.setdefault('when', WHEN)
        with self.open() as repo:
            return repo.write_commit(files, 'recorded\n\nbody', **kwargs)

    def loose_head(self):
        return (self.repo / '.git' / 'refs' / 'heads' / 'main').read_text(encoding='ascii').strip()

    def refused(self, code, files, reason=None, **kwargs):
        before = self.loose_head()
        with self.assertRaises(ra.RepositoryError) as caught:
            self.commit(files, **kwargs)
        self.assertEqual(caught.exception.code, code, caught.exception)
        if reason is not None:
            self.assertEqual(caught.exception.details.get('reason'), reason, caught.exception)
        self.assertEqual(self.loose_head(), before)
        return caught.exception

    def test_a_commit_is_written_in_process_and_the_checkout_follows_it(self):
        files = {'a/x.txt': b'x2\n', 'a/n/new.json': b'{}\n'}
        with mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('a process was launched')):
            oid = self.commit(files)
        self.assertEqual(self.loose_head(), oid)
        with self.open() as repo:
            self.assertEqual(repo.head(), ra.Head(oid, 'refs/heads/main'))
            self.assertEqual(repo.commit(f'{oid}~1'), self.head)
            self.assertEqual(repo.blob(oid, 'a/x.txt'), b'x2\n')
            self.assertEqual(repo.blob(oid, 'a/n/new.json'), b'{}\n')
            self.assertEqual(repo.blob(oid, 'a/b/keep.md'), b'keep\n')
            self.assertEqual(repo.status(untracked='all'), [])
            commit = repo._object(oid)
            self.assertEqual((commit.author, commit.committer), (IDENTITY.encode(),) * 2)
            self.assertEqual((commit.author_time, commit.author_timezone), WHEN)
            self.assertEqual(commit.message, b'recorded\n\nbody\n')
        self.assertEqual((self.repo / 'a' / 'n' / 'new.json').read_bytes(), b'{}\n')
        logs = (self.repo / '.git' / 'logs')
        for log in (logs / 'HEAD', logs / 'refs' / 'heads' / 'main'):
            last = log.read_bytes().splitlines()[-1]
            self.assertTrue(last.startswith(f'{self.head} {oid} {IDENTITY} 1794312000 +0100\t'.encode()), last)
            self.assertTrue(last.endswith(b'\tcommit: recorded'), last)
        rc.git(self.repo, 'fsck', '--strict', '--no-progress')
        self.assertEqual(rc.out(self.repo, 'status', '--porcelain', '--untracked-files=all'), '')
        self.assertEqual(rc.out(self.repo, 'reflog', '-n', '1', '--format=%H %gs'), f'{oid} commit: recorded')
        # A later git commit keeps the change: no stale cache-tree survived in the index.
        rc.write(self.repo, {'top.txt': b't2\n'})
        rc.git(self.repo, 'commit', '--quiet', '-am', 'two', date=rc.date(2))
        self.assertEqual(rc.out(self.repo, 'ls-tree', '-r', '--name-only', 'HEAD').splitlines(),
                         ['a/b/keep.md', 'a/n/new.json', 'a/x.txt', 'top.txt'])
        self.assertEqual(rc.out(self.repo, 'show', 'HEAD:a/x.txt'), 'x2')

    def test_check_runs_after_the_objects_and_before_the_branch_moves(self):
        seen = []

        def check(oid):
            with self.open() as repo:  # the commit is readable by its id, unreferenced
                seen.append(repo.blob(oid, 'top.txt'))
            raise RuntimeError('refused by the caller')

        with self.assertRaises(RuntimeError):
            self.commit({'top.txt': b'changed\n'}, check=check)
        self.assertEqual(seen, [b'changed\n'])
        self.assertEqual(self.loose_head(), self.head)
        self.assertEqual((self.repo / 'top.txt').read_bytes(), b't\n')
        with self.open() as repo:
            self.assertEqual(repo.status(untracked='all'), [])

    def test_a_branch_that_moves_before_the_update_is_not_overwritten(self):
        def move(oid):
            (self.repo / '.git' / 'refs' / 'heads' / 'main').write_text(f'{self.head[:-1]}0\n', encoding='ascii')

        with self.assertRaises(ra.RepositoryError) as caught:
            self.commit({'top.txt': b'changed\n'}, check=move)
        self.assertEqual((caught.exception.code, caught.exception.details['reason']), ('COMMIT_REFUSED', 'head-moved'))
        self.assertEqual(self.loose_head(), f'{self.head[:-1]}0')
        self.assertEqual((self.repo / 'top.txt').read_bytes(), b't\n')

    def test_client_hooks_are_refused_before_anything_is_written(self):
        hooks = self.repo / '.git' / 'hooks'
        hooks.mkdir(exist_ok=True)
        (hooks / 'pre-commit.sample').write_text('#!/bin/sh\n', encoding='ascii')
        (hooks / 'pre-commit').write_text('#!/bin/sh\nexit 1\n', encoding='ascii')
        objects = sorted(p.name for p in (self.repo / '.git' / 'objects').rglob('*'))
        error = self.refused('HOOKS_UNSUPPORTED', {'top.txt': b'changed\n'})
        self.assertEqual(error.details['hook'], 'hooks/pre-commit')
        self.assertEqual(sorted(p.name for p in (self.repo / '.git' / 'objects').rglob('*')), objects)
        (hooks / 'pre-commit').unlink()
        with open(self.repo / '.git' / 'config', 'a', encoding='utf-8') as handle:
            handle.write('[core]\n\thooksPath = elsewhere\n')
        error = self.refused('HOOKS_UNSUPPORTED', {'top.txt': b'changed\n'})
        self.assertEqual(error.details['hook'], 'core.hooksPath=elsewhere')

    def test_refusals_leave_the_branch_and_the_work_tree_as_they_were(self):
        self.refused('COMMIT_REFUSED', {'top.txt': b'changed\n'}, 'head-moved', expected_head='0' * 40)
        self.refused('COMMIT_REFUSED', {'top.txt': b't\n'}, 'nothing-to-commit')
        self.refused('COMMIT_REFUSED', {'a/x.txt/below': b'x\n'}, 'path-conflict')
        self.refused('COMMIT_REFUSED', {'a/b': b'x\n'}, 'path-conflict')
        (self.repo / 'untracked.txt').write_bytes(b'mine\n')
        self.refused('COMMIT_REFUSED', {'untracked.txt': b'x\n'}, 'local-changes')
        (self.repo / 'top.txt').write_bytes(b'edited\n')
        self.refused('COMMIT_REFUSED', {'top.txt': b'changed\n'}, 'local-changes')
        self.assertEqual((self.repo / 'top.txt').read_bytes(), b'edited\n')
        self.assertEqual((self.repo / 'untracked.txt').read_bytes(), b'mine\n')
        for path in ('', 'a//b', '../x', '.git/config', 'a/.git/x', '/abs'):
            with self.subTest(path=path):
                self.refused('OBJECT_NAME_INVALID', {path: b'x\n'})

    def test_signing_detached_head_and_unsupported_indexes_are_refused(self):
        config = self.repo / '.git' / 'config'
        original = config.read_bytes()
        config.write_bytes(original + b'[commit]\n\tgpgSign = true\n')
        self.refused('COMMIT_REFUSED', {'top.txt': b'changed\n'}, 'signing')
        config.write_bytes(original)
        (self.repo / '.git' / 'HEAD').write_text(f'{self.head}\n', encoding='ascii')
        self.refused('COMMIT_REFUSED', {'top.txt': b'changed\n'}, 'head')
        (self.repo / '.git' / 'HEAD').write_text('ref: refs/heads/main\n', encoding='ascii')
        # An index this module must not rewrite: unmerged entries, or an extension git requires to
        # be understood (lower-case signature).
        d = ra.dulwich_modules()
        real = ra.Repository._index
        for conflicts, signature in ((True, b'REUC'), (False, b'sdir'), (False, b'link')):
            def index(repository, conflicts=conflicts, signature=signature):
                found = real(repository)
                found.has_conflicts = lambda: conflicts
                found._extensions = [d.index.IndexExtension(signature, b'')]
                return found
            with self.subTest(signature=signature), mock.patch.object(ra.Repository, '_index', index):
                self.refused('COMMIT_REFUSED', {'top.txt': b'changed\n'}, 'index')
        # git's own split index: Dulwich 1.2.21 cannot read it, so nothing is written.
        rc.git(self.repo, 'update-index', '--split-index')
        error = self.refused('GIT_FAILED', {'top.txt': b'changed\n'})
        self.assertIn('cannot read the index', error.message)
        self.assertEqual((self.repo / 'top.txt').read_bytes(), b't\n')

    def test_arguments_are_checked_first(self):
        for files, kwargs in (({}, {}), ({'top.txt': 'text'}, {}), ({'top.txt': b'x'}, {'identity': 'no email'}),
                              ({'top.txt': b'x'}, {'identity': 'A <b>\n'}),
                              ({'top.txt': b'x'}, {'expected_head': 'HEAD'})):
            with self.subTest(files=files, kwargs=kwargs), self.assertRaises(ValueError):
                self.commit(files, **kwargs)
        self.assertEqual(self.loose_head(), self.head)


if __name__ == '__main__':
    unittest.main()
