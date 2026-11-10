"""The repository-access module's contract suite, recorded half (plan leaf F-10.2, decision 0014).

Run from the repository root, under the tools interpreter (Dulwich is required: without it these
tests fail with REPOSITORY_NEEDS_DULWICH, never skip):

    <tools python> -I -B -m unittest discover -s integrations/repository/tests -v

Every answer of the module over the git-built golden corpus (``repository_corpus.py``) equals
git's recorded answer: the preserved revision grammar (``rev-parse --verify <form>^{commit}``
and ``cat-file`` for object names), file lists, exports (blob bytes), HEAD, status, the index,
listings and the work-tree check. The documented gap forms are refused before any repository
access; damaged objects fail visibly; the configuration policy is explicit and observable; no
process is launched. The git-oracle half (``test_repository_oracle.py``) asks git again.
"""
import gc
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

CATEGORY = 'contract'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import repository_corpus as rc  # noqa: E402  (puts integrations/repository on sys.path)
import repository_access as ra  # noqa: E402

REPO = HERE.parents[2]
TOOLS_LOCK = REPO / 'composition' / 'lock' / 'python' / 'tools-requirements.txt'

# Every form decision 0014 section 2 lists as a documented gap, as it may be written.
GAP_FORMS = [
    ':/x', ':/fix the bug', 'HEAD^{/x}', 'main^{/fix}~1', 'HEAD~1^{/a b}:README.md',
    'main@{yesterday}', '@{2026-11-01}', 'main@{1.day.ago}', 'HEAD@{now}', 'main@{100000000}', 'main@{}',
    'main@{1}@{yesterday}', '@{upstream}', '@{u}', 'main@{U}', 'main@{upstream}~1', '@{push}', 'main@{Push}',
    '@{-1}', '@{-2}~1', 'main@{-1}', 'A..B', 'HEAD~1..HEAD', 'HEAD...side', '..HEAD', 'HEAD..', '^HEAD',
    'HEAD^@', 'HEAD^!', 'HEAD^-', 'HEAD^-1', 'refs/heads/../heads/main', 'heads/../main']
INVALID_REVISIONS = ['', '-HEAD', '--all', 'HEAD main', 'HEAD\tx', 'HEAD\nx', 'main\x00', 'main\x7f', ' HEAD',
                     'HEAD ', 'a' + chr(0xa0) + 'b', 'a' + chr(0x2028) + 'b', 'x\ud800', None, 3, b'HEAD']
INVALID_NAMES = ['', '-HEAD', 'HEAD\x00', 'HEAD:a\nb', 'HEAD:\tx', 'x\x7f', 'x\ud800', None, b'HEAD']


def lock_pin(name):
    match = re.search(rf'^{re.escape(name)}==(\S+)', TOOLS_LOCK.read_text(encoding='utf-8'), re.M)
    return match.group(1)


def open_repo(name, policy='repository', work_tree=False):
    return ra.open_repository(rc.corpus() / name, config=policy, work_tree=work_tree)


class Spy:
    """Stands in for the Dulwich repository: records any access."""

    def __init__(self):
        self.accessed = []

    def __getattr__(self, name):
        self.accessed.append(name)
        raise AssertionError(f'repository accessed: {name}')


class DulwichPresent(unittest.TestCase):
    """Dulwich must be importable by the interpreter running the suite: the tools interpreter."""

    def test_dulwich_is_importable_at_the_locked_version(self):
        try:
            d = ra.dulwich_modules()
        except ra.CannotRun as exc:
            self.fail(f'{exc} (run this suite under the tools interpreter)')
        self.assertEqual(d.version, lock_pin('dulwich'), 'the pinned Dulwich of the tools lock')
        # From the installed metadata: importing urllib3 opens a socket (its IPv6 probe).
        from importlib import metadata
        self.assertEqual(metadata.version('urllib3'), lock_pin('urllib3'))


class MissingDulwich(unittest.TestCase):
    category = 'unit'

    def test_without_dulwich_opening_fails_with_the_stable_code_naming_tools_install(self):
        with mock.patch.dict(sys.modules, {'dulwich': None}), mock.patch.object(ra, '_D', None):
            with self.assertRaises(ra.CannotRun) as caught:
                ra.open_repository(rc.corpus() / 'repo one', config='repository')
            self.assertEqual(caught.exception.code, 'REPOSITORY_NEEDS_DULWICH')
            self.assertIn('task tools:install', caught.exception.message)
            self.assertIn('tools_install.py --python', caught.exception.message)
            # The grammar needs no Dulwich: refusals still come before anything is opened.
            with self.assertRaises(ra.RepositoryError):
                ra.check_revision(':/x')
            self.assertEqual(ra.check_revision('HEAD~1'), 'HEAD~1')


class Grammar(unittest.TestCase):
    """Refusals come before any repository access (an access spy records none)."""

    category = 'unit'

    @classmethod
    def setUpClass(cls):
        cls.repo = open_repo('repo one', work_tree=True)

    @classmethod
    def tearDownClass(cls):
        cls.repo.close()

    def refused(self, code, call, *args):
        real, spy = self.repo._dul, Spy()
        self.repo._dul = spy
        try:
            with self.assertRaises(ra.RepositoryError) as caught:
                call(*args)
        finally:
            self.repo._dul = real
        self.assertEqual(caught.exception.code, code, caught.exception)
        self.assertEqual(spy.accessed, [])
        return caught.exception

    def test_every_gap_form_is_refused_before_any_access(self):
        for form in GAP_FORMS:
            with self.subTest(form=form):
                self.assertIsNotNone(ra.gap_form(form))
                error = self.refused('REVISION_INVALID', self.repo.commit, form)
                if not any(ch.isspace() for ch in form):  # whitespace alone already refuses a revision
                    self.assertIn('decision 0014', error.message)
                for call in (self.repo.object_kind, self.repo.object_id, self.repo.read):
                    self.assertIn('decision 0014', self.refused('REVISION_INVALID', call, form).message)
        self.refused('REVISION_INVALID', self.repo.blob, 'HEAD^{/x}', 'README.md')
        self.refused('REVISION_INVALID', self.repo.files, 'main@{yesterday}', 'docs')

    def test_the_proof_forms_are_gaps(self):
        for form, gap in ((':/x', 'history search'), ('HEAD^{/x}', 'history search'),
                          ('main@{yesterday}', 'reflog date'), ('@{upstream}', 'configured branch'),
                          ('@{-1}', 'previous checkout'), ('A..B', 'range')):
            with self.subTest(form=form):
                self.assertIn(gap, ra.gap_form(form))

    def test_invalid_revisions_and_names_are_refused_before_any_access(self):
        for revision in INVALID_REVISIONS:
            with self.subTest(revision=revision):
                self.refused('REVISION_INVALID', self.repo.commit, revision)
        for name in INVALID_NAMES:
            with self.subTest(name=name):
                for call in (self.repo.object_kind, self.repo.object_id, self.repo.read):
                    self.refused('OBJECT_NAME_INVALID', call, name)
        for directory in ('', '.', '/docs', 'docs/', 'a//b', 'a/../b', './docs', 'd\x00'):
            with self.subTest(directory=directory):
                self.refused('OBJECT_NAME_INVALID', self.repo.files, 'HEAD', directory)

    def test_preserved_forms_are_not_gaps(self):
        facts = rc.expected()['facts']
        for form in ('HEAD', '@', 'HEAD~1', 'HEAD^2', 'HEAD~1^2', 'main@{0}', '@{1}', 'HEAD^{tree}', 'v1^{}',
                     'HEAD~1:README.md', ':README.md', ':2:x', 'HEAD:a..b.txt', 'HEAD:x@{yesterday}',
                     'HEAD:x^{/y}', 'HEAD:x@{u}', ':/', facts['E'][:4], f'v1-1-g{facts["E"][:7]}', 'main@{99999999}'):
            with self.subTest(form=form):
                self.assertIsNone(ra.gap_form(form))

    def test_names_keep_spaces_and_revisions_refuse_them(self):
        self.assertEqual(ra.check_object_name('HEAD:a b.md'), 'HEAD:a b.md')
        self.refused('REVISION_INVALID', self.repo.commit, 'HEAD:a b.md')

    def test_refnames(self):
        for name in ('refs/heads/main', 'refs/top', 'refs/heads/ünï', 'main-worktree/HEAD'):
            self.assertTrue(ra.refname_valid(name), name)
        for name in ('refs/heads/a..b', 'refs/heads/.x', 'refs/heads/x.lock', 'refs/heads/x/', 'refs//x', '@',
                     'refs/heads/a b', 'refs/heads/a:b', 'refs/heads/a\\b', 'refs/heads/a@{b', 'refs/x.', 'main'):
            self.assertFalse(ra.refname_valid(name), name)
        self.assertTrue(ra.refname_valid('main', onelevel=True))


class RecordedExpectations(unittest.TestCase):
    """The module's answers equal git's recorded answers over the golden corpus."""

    @classmethod
    def setUpClass(cls):
        cls.root = rc.corpus()
        cls.expected = rc.expected()
        cls.repos = cls.expected['repos']

    def test_the_corpus_is_the_recorded_one(self):
        self.assertEqual(self.expected['schema'], rc.SCHEMA)
        self.assertEqual(rc.archive_digest(), self.expected['archive_sha256'])
        self.assertEqual(len(self.expected['long_path']), 295)
        for name in ('repo one', 'packed copy', 'bare.git', 'linked tree', 'separate work', 'sha256 repo',
                     'long.git', 'id mismatch', 'corrupt zlib', 'corrupt pack', 'conflicted', 'not a repo'):
            self.assertTrue((self.root / name).is_dir(), name)
        packed = self.root / 'packed copy' / '.git' / 'objects'
        self.assertEqual([p for p in packed.iterdir() if len(p.name) == 2 and any(p.iterdir())], [])
        self.assertTrue(any((self.root / 'repo one' / '.git' / 'objects').glob('??/*')))

    def test_commit_forms(self):
        for repo, data in self.repos.items():
            with open_repo(repo) as r:
                for form, want in data['commits']:
                    with self.subTest(repo=repo, form=form):
                        self.assertEqual(r.commit(form), want)

    def test_object_names(self):
        for repo, data in self.repos.items():
            with open_repo(repo) as r:
                for name, want in data['names']:
                    with self.subTest(repo=repo, name=name):
                        found = r.read(name)
                        self.assertEqual([found[0], found[1]] if found else None, want)
                        self.assertEqual(r.object_kind(name), want[1] if want else None)
                        self.assertEqual(r.object_id(name), want[0] if want else None)

    def test_the_date_fallback_is_refused(self):
        data = self.repos['repo one']
        with open_repo('repo one') as r:
            for kind, rows in (('commit', data['fallback_commits']), ('name', data['fallback_names'])):
                for form, _clock_dependent in rows:
                    with self.subTest(kind=kind, form=form):
                        self.assertIsNone(ra.gap_form(form))
                        with self.assertRaises(ra.RepositoryError) as caught:
                            r.commit(form) if kind == 'commit' else r.read(form)
                        self.assertEqual(caught.exception.code, 'REVISION_INVALID')
                        self.assertIn('@{<date>}', caught.exception.message)

    def test_blobs(self):
        facts = self.expected['facts']
        with open_repo('repo one') as r:
            self.assertEqual(r.blob('HEAD', 'README.md'), b'readme\nsecond line\n')
            self.assertEqual(r.blob(facts['E'], rc.UNI), 'unicode ü\n'.encode())
            self.assertEqual(r.blob('HEAD', 'data/binary.bin'), b'\x00\x01\r\n\x02\x03\xff\r\n')
            self.assertEqual(r.blob('HEAD', 'eol/crlf.txt'), b'line one\nline two\n')
            for name, path, why in (('HEAD', 'docs', 'a tree, not a blob'), ('HEAD', 'no such', 'no such object'),
                                    ('0' * 40, 'README.md', 'no such object')):
                with self.subTest(path=path):
                    with self.assertRaises(ra.RepositoryError) as caught:
                        r.blob(name, path)
                    self.assertEqual(caught.exception.code, 'GIT_FAILED')
                    self.assertIn(why, caught.exception.message)
        with open_repo('long.git') as r:
            self.assertEqual(r.blob('HEAD', self.expected['long_path']), b'long path\n')

    def test_file_lists(self):
        for repo, data in self.repos.items():
            if 'files' not in data:
                continue
            with open_repo(repo) as r:
                for commit, directory, want in data['files']:
                    with self.subTest(repo=repo, commit=commit, directory=directory):
                        self.assertEqual(r.files(commit, directory), want)
        with open_repo('repo one') as r, self.assertRaises(ra.RepositoryError) as caught:
            r.files('0' * 40, 'docs')
        self.assertEqual(caught.exception.code, 'GIT_FAILED')

    def test_heads(self):
        for repo, data in self.repos.items():
            if 'head' in data:
                with self.subTest(repo=repo), open_repo(repo) as r:
                    head = r.head()
                    self.assertEqual([head.commit, head.ref], data['head'])

    def test_index_entries(self):
        for repo, data in self.repos.items():
            if 'index' in data:
                with self.subTest(repo=repo), open_repo(repo, work_tree=True) as r:
                    self.assertEqual([[e.mode, e.oid, e.stage, e.path] for e in r.index_entries()], data['index'])

    def test_status(self):
        for repo, data in self.repos.items():
            if 'status' not in data:
                continue
            with open_repo(repo, work_tree=True) as r:
                for untracked, paths, want in data['status']:
                    with self.subTest(repo=repo, untracked=untracked, paths=paths):
                        self.assertEqual([[e.xy, e.path] for e in r.status(paths, untracked)], want)

    def test_listings(self):
        for repo, data in self.repos.items():
            if 'listing' not in data:
                continue
            with open_repo(repo, work_tree=True) as r:
                for cached, others, exclude, want in data['listing']:
                    with self.subTest(repo=repo, cached=cached, others=others, exclude=exclude):
                        self.assertEqual(r.listing(cached, others, exclude), want)

    def test_the_work_tree_check(self):
        """Accepted: a work tree's root and subdirectories, a linked worktree, a separate git
        directory's work tree. Refused: bare, .git and anything in it, and a non-repository."""
        for subject, want in self.expected['work_trees']:
            with self.subTest(subject=subject):
                if want is None:
                    with self.assertRaises(ra.CannotRun) as caught:
                        ra.open_repository(self.root / subject, config='repository')
                    self.assertEqual(caught.exception.code, 'NOT_A_WORK_TREE')
                else:
                    with ra.open_repository(self.root / subject, config='repository') as r:
                        self.assertEqual(Path(r.root).resolve(), (self.root / want).resolve())
        with ra.open_repository(self.root / 'bare.git', config='repository', work_tree=False) as r:
            self.assertTrue(r.bare)
        with self.assertRaises(ra.CannotRun) as caught:
            ra.open_repository(self.root / 'not a repo', config='repository', work_tree=False)
        self.assertEqual(caught.exception.code, 'NOT_A_REPOSITORY')
        with self.assertRaises(ra.CannotRun):
            ra.open_repository(self.root / 'no such directory', config='repository')
        with self.assertRaises(ValueError):
            ra.open_repository(self.root / 'repo one', config='system')


class RecordedCases(unittest.TestCase):
    """The F-10.4 cases (``repository_corpus.CASES``, each its own repository): the ignore rules
    (directories re-included by a negation, gitignore(5)'s examples, nested files, info/exclude,
    a relative core.excludesFile), git's attribute order and macros, git's size rule; and the
    full reference name of a name (``full_name_forms``)."""

    @classmethod
    def setUpClass(cls):
        cls.expected = rc.expected()
        cls.cases = cls.expected['cases']

    def test_every_case_is_recorded(self):
        self.assertEqual(sorted(self.cases), sorted(rc.CASES))
        self.assertEqual(sorted(self.expected['full_names']), sorted(rc.full_name_forms(self.expected['facts'])))

    def cases_with(self, prefix):
        return [(name, data) for name, data in sorted(self.cases.items()) if name.startswith(prefix)]

    def check_listings(self, prefix):
        for repo, data in self.cases_with(prefix):
            with open_repo(repo, work_tree=True) as r:
                for cached, others, exclude, want in data['listing']:
                    with self.subTest(repo=repo, cached=cached, others=others, exclude=exclude):
                        self.assertEqual(r.listing(cached, others, exclude), want)

    def check_status(self, prefix):
        for repo, data in self.cases_with(prefix):
            with open_repo(repo, work_tree=True) as r:
                self.assertEqual([[e.mode, e.oid, e.stage, e.path] for e in r.index_entries()], data['index'])
                for untracked, paths, want in data['status']:
                    with self.subTest(repo=repo, untracked=untracked, paths=paths):
                        self.assertEqual([[e.xy, e.path] for e in r.status(paths, untracked)], want)

    def test_ignore_rule_listings(self):
        self.check_listings('ignore ')

    def test_ignore_rule_status(self):
        self.check_status('ignore ')

    def test_a_listing_is_never_a_strict_subset_of_gits(self):
        """The secret-leak scan reads the listing: a path git lists and the module does not
        would go unscanned."""
        rows = [(repo, row) for repo, data in self.cases.items() for row in data['listing']]
        rows += [(repo, row) for repo, data in self.expected['repos'].items() for row in data.get('listing', [])]
        for repo, (cached, others, exclude, want) in rows:
            with self.subTest(repo=repo, cached=cached, others=others, exclude=exclude), \
                    open_repo(repo, work_tree=True) as r:
                self.assertEqual(set(want) - set(r.listing(cached, others, exclude)), set())

    def test_attribute_order_and_macros(self):
        self.check_status('attributes')
        self.assertEqual(self.cases['attributes']['status'][0][2], [[' M', 'x.dat']])

    def test_a_changed_size_is_a_change_without_a_comparison(self):
        self.check_status('line endings')
        self.assertEqual([path for _xy, path in self.cases['line endings']['status'][0][2]],
                         ['crlf.txt', 'keep-crlf.txt', 'lf.txt', 'same.txt', 'sub/a b.txt'])

    def test_full_names(self):
        for repo, rows in self.expected['full_names'].items():
            with open_repo(repo) as r:
                for name, want in rows:
                    with self.subTest(repo=repo, name=name):
                        self.assertEqual(r.full_name(name), want)

    def test_full_name_refuses_what_a_revision_refuses(self):
        with open_repo('repo one') as r:
            for form in (':/x', 'main@{yesterday}', '-HEAD', 'HEAD main', ''):
                with self.subTest(form=form), self.assertRaises(ra.RepositoryError) as caught:
                    r.full_name(form)
                self.assertEqual(caught.exception.code, 'REVISION_INVALID')

    def test_an_ambiguous_name_resolves_without_the_warning(self):
        tmp = Path(tempfile.mkdtemp(prefix='aieh-repo-ambiguous-'))
        self.addCleanup(rc.rmtree, tmp)
        shutil.copytree(rc.corpus() / 'bare.git', tmp / 'bare.git')
        with open(tmp / 'bare.git' / 'config', 'a', encoding='utf-8') as handle:
            handle.write('[core]\n\twarnAmbiguousRefs = false\n')
        with ra.open_repository(tmp / 'bare.git', config='repository', work_tree=False) as r:
            self.assertEqual(r.full_name('dup'), 'refs/tags/dup')   # git's first rule that resolves
        with ra.open_repository(tmp / 'bare.git', config='none', work_tree=False) as r:
            self.assertIsNone(r.full_name('dup'))


class AttributeLines(unittest.TestCase):
    """``parse_attribute_lines``: gitattributes lines as git's parse_attr_line reads them."""

    category = 'unit'

    def test_lines(self):
        U = ra._UNSPECIFIED
        text = (b'\xef\xbb\xbf# comment\n\n  *.c text -diff !merge eol=lf\r\n[attr]m -text\n[attr]\n'
                b'!neg -text\n"a b.q" -text\n"bad\\x" text\n*.x -text=x bad!name\n' + b'*.y text\n' +
                b'*.long ' + b'a' * 2048 + b'\n')
        lines = ra.parse_attribute_lines(text, macros_allowed=True)
        self.assertEqual(lines, [
            (3, 'pattern', b'*.c', [(b'text', True), (b'diff', False), (b'merge', U), (b'eol', b'lf')]),
            (4, 'macro', b'm', [(b'text', False)]),
            (7, 'pattern', b'a b.q', [(b'text', False)]),
            (8, 'pattern', b'"bad\\x"', [(b'text', True)]),
            (10, 'pattern', b'*.y', [(b'text', True)])])
        nested = ra.parse_attribute_lines(b'[attr]m -text\n*.z m\n', macros_allowed=False)
        self.assertEqual(nested, [(2, 'pattern', b'*.z', [(b'm', True)])])   # never a glob pattern


class Export(unittest.TestCase):
    """export_tree writes blob bytes (decision 0014 section 4)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-repo-export-'))
        cls.count = 0

    @classmethod
    def tearDownClass(cls):
        rc.rmtree(cls.tmp)

    def destination(self):
        type(self).count += 1
        path = self.tmp / f'export {self.count} ü'
        path.mkdir()
        return path

    def test_exports_equal_git_blob_bytes(self):
        for repo, data in rc.expected()['repos'].items():
            for commit, subtree, members in data.get('export', []):
                with self.subTest(repo=repo, commit=commit, subtree=subtree), open_repo(repo) as r:
                    dest = self.destination()
                    counts = r.export_tree(commit, subtree, dest)
                    self.check(dest, members)
                    self.assertEqual(counts['files'], sum(1 for m in members if m[1] in ('100644', '100755')))

    def check(self, dest, members):
        written = []
        for top, dirs, files in os.walk(dest):  # links are not followed
            for name in files + [d for d in dirs if os.path.islink(os.path.join(top, d))]:
                written.append(Path(top, name).relative_to(dest).as_posix())
        written.sort()
        expected_paths = sorted(path for path, mode, _sha, _size in members if mode != '160000')
        self.assertEqual(written, expected_paths)
        for path, mode, sha, size in members:
            target = dest.joinpath(*path.split('/'))
            if mode == '160000':
                self.assertTrue(target.is_dir() and not any(target.iterdir()), path)
            elif mode == '120000':
                self.assertTrue(target.is_symlink(), path)
                link = os.readlink(target).replace('\\', '/')
                self.assertEqual(hashlib.sha256(link.encode()).hexdigest(), sha, path)
            else:
                data = target.read_bytes()
                self.assertEqual((hashlib.sha256(data).hexdigest(), len(data)), (sha, size), path)
                if os.name != 'nt':
                    self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755 if mode == '100755' else 0o644)

    def test_export_ignore_eol_and_binary_are_blob_bytes(self):
        with open_repo('repo one') as r:
            dest = self.destination()
            r.export_tree('HEAD', '.', dest)
        self.assertEqual((dest / 'ignored-export' / 'hidden.txt').read_bytes(), b'hidden from git archive\n')
        self.assertEqual((dest / 'eol' / 'crlf.txt').read_bytes(), b'line one\nline two\n')
        self.assertEqual((dest / 'text' / 'crlf-in-blob.txt').read_bytes(), b'a\r\nb\r\n')
        self.assertEqual((dest / 'data' / 'binary.bin').read_bytes(), b'\x00\x01\r\n\x02\x03\xff\r\n')

    def test_links_inside_are_links_and_a_gitlink_is_an_empty_directory(self):
        with open_repo('repo one') as r:
            dest = self.destination()
            counts = r.export_tree('links-ok', '.', dest)
        self.assertEqual((counts['files'], counts['links'], counts['directories']), (4, 2, 1))
        self.assertEqual(os.readlink(dest / 'links' / 'inside').replace('\\', '/'), '../README.md')
        self.assertEqual((dest / 'links' / 'inside').read_bytes(), b'readme\nsecond line\n')
        self.assertTrue((dest / 'links' / 'dir').is_dir())
        self.assertEqual(list((dest / 'links' / 'sub').iterdir()), [])

    def test_refusals_write_nothing(self):
        with open_repo('repo one') as r:
            for commit, why in (('links-escape', 'leaves the export'), ('links-climb', 'climbs out of another link'),
                                ('unsafe-name', 'git metadata')):
                with self.subTest(commit=commit):
                    dest = self.destination()
                    with self.assertRaises(ra.RepositoryError) as caught:
                        r.export_tree(commit, '.', dest)
                    self.assertEqual(caught.exception.code, 'EXPORT_REFUSED')
                    self.assertIn(why, caught.exception.message)
                    self.assertEqual(list(dest.iterdir()), [])
            dest = self.destination()
            (dest / 'x').write_text('x')
            with self.assertRaises(ra.RepositoryError) as caught:
                r.export_tree('HEAD', '.', dest)
            self.assertEqual(caught.exception.code, 'EXPORT_REFUSED')
            with self.assertRaises(ra.RepositoryError) as caught:
                r.export_tree('HEAD', 'no/such', self.destination())
            self.assertEqual(caught.exception.code, 'GIT_FAILED')

    def test_a_platform_refusing_links_refuses_the_export(self):
        with open_repo('repo one') as r, mock.patch.object(ra.os, 'symlink', side_effect=OSError('privilege')):
            with self.assertRaises(ra.RepositoryError) as caught:
                r.export_tree('links-ok', '.', self.destination())
        self.assertEqual(caught.exception.code, 'EXPORT_REFUSED')
        self.assertIn('privilege', caught.exception.message)

    def test_unsafe_names(self):
        for name in ('.git', '.GIT', '..', '.', ''):
            self.assertIsNotNone(ra._unsafe_component(name), name)
        self.assertIsNone(ra._unsafe_component('a b ü.md'))
        with mock.patch.object(ra, '_WINDOWS', True):
            for name in ('aux.txt', 'CON', 'nul ', 'a:b', 'a\\b', 'x.', 'x ', 'git~1', '.git.', 'COM1.log'):
                self.assertIsNotNone(ra._unsafe_component(name), name)
            self.assertIsNone(ra._unsafe_component('auxiliary.txt'))


class Integrity(unittest.TestCase):
    """A damaged object fails visibly with GIT_FAILED naming it (decision 0014 section 3); no
    crash, and the other objects still read. The verified-object cache (F-10.3) holds only
    objects whose content hashed to their id, within its bound, and is emptied by close()."""

    def test_damaged_objects(self):
        facts = rc.expected()['facts']
        for repo, oid in (('id mismatch', facts['mismatch']), ('corrupt zlib', facts['zlib']),
                          ('corrupt pack', facts['pack'])):
            with self.subTest(repo=repo):
                r = open_repo(repo, work_tree=True)
                try:
                    for call, args in ((r.blob, ('HEAD', 'README.md')), (r.object_kind, (oid,)),
                                       (r.read, ('HEAD:README.md',))):
                        with self.assertRaises(ra.RepositoryError) as caught:
                            call(*args)
                        self.assertEqual(caught.exception.code, 'GIT_FAILED')
                        self.assertEqual(caught.exception.details.get('object'), oid)
                        self.assertIn(oid, caught.exception.message)
                    self.assertNotIn(oid, r._objects)  # a damaged object is never cached
                    self.assertEqual(r.blob('HEAD', 'other.txt'), b'other\n')
                    self.assertEqual(r.blob('HEAD', 'dir/more.txt'), b'more\n')
                    self.assertIsNotNone(r.commit('HEAD'))
                    # A verified object is read from the repository once.
                    store = type(r._dul.object_store)
                    with mock.patch.object(store, 'get_raw', autospec=True, side_effect=store.get_raw) as reads:
                        self.assertEqual(r.blob('HEAD', 'other.txt'), b'other\n')
                    self.assertEqual(reads.call_count, 0)
                    self.assertLessEqual(r._object_bytes, ra.OBJECT_CACHE_BYTES)
                    with mock.patch.object(ra, 'OBJECT_CACHE_BYTES', 64):
                        r._objects.clear()
                        r._object_bytes = 0
                        r.blob('HEAD', 'other.txt')
                        r.blob('HEAD', 'dir/more.txt')
                        self.assertLessEqual(r._object_bytes, 64)
                        self.assertTrue(all(len(entry[1]) <= 64 // 8 for entry in r._objects.values()))
                    with self.assertRaises(ra.RepositoryError) as caught:
                        r.export_tree('HEAD', '.', _empty_dir())
                    self.assertEqual(caught.exception.code, 'GIT_FAILED')
                    self.assertIsNone(caught.exception.__context__)
                finally:
                    with warnings.catch_warnings(record=True) as seen:
                        warnings.simplefilter('always')
                        r.close()
                        gc.collect()
                self.assertEqual((len(r._objects), r._object_bytes), (0, 0))
                # Closing released every file of the damaged repository.
                self.assertEqual([str(w.message) for w in seen if issubclass(w.category, ResourceWarning)], [])


_EMPTY = []


def _empty_dir():
    if not _EMPTY:
        _EMPTY.append(Path(tempfile.mkdtemp(prefix='aieh-repo-damaged-')))
        import atexit
        atexit.register(rc.rmtree, _EMPTY[0])
    path = _EMPTY[0] / str(len(list(_EMPTY[0].iterdir())))
    path.mkdir()
    return path


class ConfigPolicy(unittest.TestCase):
    """Every call names its configuration policy, and config_sources lists the files read
    (decision 0014 section 5)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-repo-config-'))
        cls.repo = cls.tmp / 'work'
        shutil.copytree(rc.corpus() / 'separate work', cls.repo, symlinks=True)
        shutil.copytree(rc.corpus() / 'separate.git', cls.tmp / 'separate.git', symlinks=True)
        cls.excludes = cls.tmp / 'excludes'
        cls.excludes.write_text('*.secret\n', encoding='utf-8')
        cls.global_config = cls.tmp / 'global config'
        cls.global_config.write_text(f'[core]\n\texcludesFile = {cls.excludes.as_posix()}\n', encoding='utf-8')
        (cls.repo / 'note.secret').write_text('s\n', encoding='utf-8')
        (cls.repo / 'note.txt').write_text('t\n', encoding='utf-8')
        cls.config = os.path.join(str(cls.tmp / 'separate.git'), 'config')

    @classmethod
    def tearDownClass(cls):
        rc.rmtree(cls.tmp)

    def test_repository_and_none_read_only_the_repository_config(self):
        for policy in ('repository', 'none'):
            with self.subTest(policy=policy), ra.open_repository(self.repo, config=policy) as r:
                r.status(None, 'all')
                self.assertEqual([os.path.normcase(p) for p in r.config_sources], [os.path.normcase(self.config)])
        with ra.open_repository(self.repo, config='repository') as r:
            self.assertTrue(r._config_bool(b'core', b'bare', True) is False)
        with ra.open_repository(self.repo, config='none') as r:
            self.assertTrue(r._config_bool(b'core', b'bare', True), 'none applies no configuration')

    def test_host_reads_the_global_file_and_the_excludes_it_names(self):
        env = {'GIT_CONFIG_GLOBAL': str(self.global_config), 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_ATTR_NOSYSTEM': '1'}
        with mock.patch.dict(os.environ, env):
            with ra.open_repository(self.repo, config='host') as r:
                untracked = [e.path for e in r.status(None, 'all') if e.xy == '??']
                sources = list(r.config_sources)
            self.assertEqual(ra.host_config_paths(), [str(self.global_config)])
        self.assertIn('note.txt', untracked)
        self.assertNotIn('note.secret', untracked)
        self.assertEqual([os.path.normcase(p) for p in sources],
                         [os.path.normcase(p) for p in (self.config, str(self.global_config), str(self.excludes))])
        with mock.patch.dict(os.environ, env), ra.open_repository(self.repo, config='repository') as r:
            self.assertIn('note.secret', [e.path for e in r.status(None, 'all')])

    def test_host_is_the_same_under_every_path(self):
        """The system file is located without PATH (decision 0014 section 5): Git Bash's PATH
        order, PowerShell's and an empty PATH give the same files and the same answers."""
        install = ra._registry_install_path() if os.name == 'nt' else '/usr'
        self.assertTrue(install, 'Git for Windows is not in the registry on this host')
        orders = {'git bash': [os.path.join(install, 'mingw64', 'bin'), os.path.join(install, 'usr', 'bin'),
                               os.path.join(install, 'cmd')],
                  'powershell': [os.path.join(install, 'cmd')], 'empty': []}
        seen = {}
        for name, entries in orders.items():
            env = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_CONFIG', 'GIT_ATTR'))}
            env['PATH'] = os.pathsep.join(entries)
            with mock.patch.dict(os.environ, env, clear=True), ra.open_repository(rc.corpus() / 'repo one',
                                                                                  config='host') as r:
                status = r.status(None, 'all')
                seen[name] = (ra.host_config_paths(), ra.system_file('gitconfig'), r.config_sources,
                              r.attribute_files(), status, r.listing(True, True, True))
        self.assertEqual(seen['git bash'], seen['powershell'])
        self.assertEqual(seen['git bash'], seen['empty'])
        system = seen['empty'][1]
        if os.name == 'nt':
            self.assertEqual(system, os.path.join(install, 'etc', 'gitconfig'))
        if os.path.isfile(system):
            self.assertIn(os.path.normpath(system), seen['empty'][2])

    def test_the_system_file_rules(self):
        clean = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_CONFIG', 'GIT_ATTR'))}
        with mock.patch.dict(os.environ, clean, clear=True), \
                mock.patch.object(ra, '_registry_install_path', return_value='X:\\Git'), \
                mock.patch.object(ra, '_WINDOWS', True):
            system = os.path.join('X:\\Git', 'etc', 'gitconfig')
            self.assertEqual(ra.host_config_paths()[-1], system)
            self.assertEqual(ra.system_file('gitattributes'), os.path.join('X:\\Git', 'etc', 'gitattributes'))
            for value, present in (('1', False), ('true', False), ('0', True), ('false', True), ('', True)):
                with self.subTest(GIT_CONFIG_NOSYSTEM=value), mock.patch.dict(os.environ, {'GIT_CONFIG_NOSYSTEM': value}):
                    self.assertEqual(system in ra.host_config_paths(), present)
            with mock.patch.dict(os.environ, {'GIT_CONFIG_SYSTEM': 'chosen', 'GIT_CONFIG_NOSYSTEM': '1'}):
                self.assertEqual(ra.host_config_paths()[-1], 'chosen')
            with mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': 'g'}):
                self.assertEqual(ra.host_config_paths(), ['g', system])
        with mock.patch.dict(os.environ, clean, clear=True), mock.patch.object(ra, '_WINDOWS', True), \
                mock.patch.object(ra, '_registry_install_path', return_value=None):
            self.assertIsNone(ra.system_file('gitconfig'))
            self.assertEqual(len(ra.host_config_paths()), 2, 'no system file without an installation')
        with mock.patch.object(ra, '_WINDOWS', False):
            self.assertEqual((ra.system_file('gitconfig'), ra.system_file('gitattributes')),
                             ('/etc/gitconfig', '/etc/gitattributes'))

    def test_repository_policy_is_the_same_with_and_without_git_on_path(self):
        def snapshot():
            with ra.open_repository(self.repo, config='repository') as r:
                return (r.config_sources, r.status(None, 'all'), r.listing(True, True, True), r.index_entries(),
                        r.commit('HEAD'), r.read('HEAD:sep.txt'), r.head())

        with_git = snapshot()
        with mock.patch.dict(os.environ, {'PATH': ''}):
            without_git = snapshot()
        self.assertEqual(with_git, without_git)


class AttributeFiles(unittest.TestCase):
    """The user and system attribute files git reads: read, and status refused
    (ATTRIBUTES_UNSUPPORTED) when one sets an attribute status consults."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-repo-attributes-'))
        for name in ('work', 'separate.git'):
            shutil.copytree(rc.corpus() / ('separate work' if name == 'work' else name), cls.tmp / name, symlinks=True)
        cls.repo = cls.tmp / 'work'
        cls.neutral = cls.tmp / 'neutral attributes'
        cls.neutral.write_text('# only diff drivers\n*.doc\tdiff=astextplain\n"a b.x" -diff !merge\n', encoding='utf-8')
        cls.text = cls.tmp / 'text attributes'
        cls.text.write_text('*.txt text eol=crlf\n', encoding='utf-8')
        (cls.tmp / 'xdg' / 'git').mkdir(parents=True)
        (cls.tmp / 'xdg' / 'git' / 'attributes').write_text('*.txt eol=crlf\n', encoding='utf-8')
        (cls.tmp / 'no xdg').mkdir()

    @classmethod
    def tearDownClass(cls):
        rc.rmtree(cls.tmp)

    def env(self, attributes=None, xdg='no xdg'):
        config = self.tmp / f'global {len(os.listdir(self.tmp))}'
        config.write_text(f'[core]\n\tattributesFile = {Path(attributes).as_posix()}\n' if attributes else '',
                          encoding='utf-8')
        return {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_ATTR_NOSYSTEM': '1',
                'XDG_CONFIG_HOME': str(self.tmp / xdg)}

    def status(self, policy, env):
        with mock.patch.dict(os.environ, env), ra.open_repository(self.repo, config=policy) as r:
            return r.status(None, 'all'), r.config_sources

    def refused(self, policy, env):
        with self.assertRaises(ra.RepositoryError) as caught:
            self.status(policy, env)
        self.assertEqual(caught.exception.code, 'ATTRIBUTES_UNSUPPORTED')
        return caught.exception

    def test_status_attributes(self):
        for text, found in (('*.doc diff=astextplain\n', None), ('# c\n\n*.x -diff !merge whitespace=x\n', None),
                            ('*.txt text\n', 'text'), ('*.bin binary\n', 'binary'), ('[attr]m text\n', '[attr]m'),
                            ('"a b" eol=lf\n', 'eol=lf'), ('"a b" diff\n', None), ('*.x filter=lfs\n', 'filter=lfs'),
                            ('*.x -text\n', '-text'), ('*.x ident\n', 'ident'), ('*.x mymacro\n', 'mymacro')):
            with self.subTest(text=text):
                self.assertEqual(ra.status_attribute(text), found)

    def test_a_global_file_is_read_and_refused_only_when_status_depends_on_it(self):
        _status, sources = self.status('host', self.env(self.neutral))
        self.assertIn(os.path.normpath(str(self.neutral)), sources)
        error = self.refused('host', self.env(self.text))
        self.assertEqual(error.details['attribute'], 'text')
        self.assertEqual(os.path.normcase(error.details['path']), os.path.normcase(str(self.text)))

    def test_a_macro_in_a_user_file_is_refused_naming_its_line(self):
        macro = self.tmp / 'macro attributes'
        macro.write_text('# a macro\n*.doc diff=astextplain\n[attr]mine -text\n', encoding='utf-8')
        error = self.refused('host', self.env(macro))
        self.assertEqual((error.details['line'], error.details['attribute']), (3, '[attr]mine'))
        self.assertIn(':3 defines the macro [attr]mine', error.message)

    def test_the_xdg_file_applies_to_host_only(self):
        self.refused('host', self.env(xdg='xdg'))
        self.status('repository', self.env(xdg='xdg'))
        self.status('host', self.env(xdg='no xdg'))

    def test_the_system_file_and_git_attr_nosystem(self):
        with mock.patch.object(ra, 'system_file', lambda name: str(self.text) if name == 'gitattributes' else None):
            env = self.env()
            env['GIT_ATTR_NOSYSTEM'] = '0'
            self.refused('host', env)
            env['GIT_ATTR_NOSYSTEM'] = '1'
            self.status('host', env)
            env['GIT_ATTR_NOSYSTEM'] = '0'
            self.status('repository', env)

    def test_a_repository_configured_file_applies_under_repository_too(self):
        config = self.tmp / 'separate.git' / 'config'
        original = config.read_bytes()
        self.addCleanup(config.write_bytes, original)
        config.write_bytes(original + f'[core]\n\tattributesFile = {self.text.as_posix()}\n'.encode())
        self.refused('repository', self.env())
        self.refused('host', self.env())
        self.status('none', self.env())


class ReplaceRefs(unittest.TestCase):
    """git applies refs/replace/ to object reads by default: such a repository's object reads
    are refused (REPLACE_REFS_UNSUPPORTED); core.useReplaceRefs=false reads as git does."""

    def test_reads_are_refused_where_git_would_replace(self):
        facts, repos = rc.expected()['facts'], rc.expected()['repos']
        for repo in ('replace loose', 'replace packed'):
            with self.subTest(repo=repo), open_repo(repo, work_tree=True) as r:
                self.assertEqual(r.replace_refs(), [f'refs/replace/{facts["R3"]}'])
                for form, _git in repos[repo]['replaced_commits']:
                    with self.subTest(form=form):
                        self.assertRefused(r.commit, form)
                        self.assertRefused(r.read, form)
                self.assertRefused(r.blob, 'HEAD', 'f.txt')
                self.assertRefused(r.files, 'HEAD', 'x')
                self.assertRefused(r.status, None, 'all')
                self.assertRefused(r.export_tree, 'HEAD', '.', _empty_dir())
                self.assertRefused(r.write_bundle, ['refs/heads/main'], _empty_dir() / 'b.bundle')
                # References, the index and the listing are not replaced: they answer as git.
                self.assertEqual([r.head().commit, r.head().ref], repos[repo]['head'])
                self.assertEqual([[e.mode, e.oid, e.stage, e.path] for e in r.index_entries()], repos[repo]['index'])

    def test_git_replaces_and_the_disabled_copy_reads_unreplaced(self):
        repos = rc.expected()['repos']
        replaced = dict(repos['replace loose']['replaced_names'])
        disabled = dict(repos['replace disabled']['names'])
        for name in ('HEAD~1', 'HEAD^{tree}', 'HEAD:f.txt'):
            self.assertNotEqual(replaced[name], disabled[name], name)
        with open_repo('replace disabled') as r:
            self.assertEqual(r.blob('HEAD', 'f.txt'), b'three\n')
        with open_repo('replace disabled', 'none') as r:  # no configuration: git's default applies
            self.assertRefused(r.read, 'HEAD')

    def assertRefused(self, call, *args):
        with self.assertRaises(ra.RepositoryError) as caught:
            call(*args)
        self.assertEqual(caught.exception.code, 'REPLACE_REFS_UNSUPPORTED', caught.exception)


class Bundles(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-repo-bundle-'))

    @classmethod
    def tearDownClass(cls):
        rc.rmtree(cls.tmp)

    def test_a_branch_bundle(self):
        facts = rc.expected()['facts']
        with open_repo('repo one') as r:
            header = r.write_bundle(['refs/heads/main'], self.tmp / 'main.bundle')
        self.assertEqual(header['version'], 2)
        self.assertEqual(header['refs'], [[facts['E'], 'refs/heads/main']])
        self.assertEqual(header['prerequisites'], [])
        self.assertTrue(header['pack_trailer']['ok'])
        self.assertEqual(ra.parse_bundle_header(self.tmp / 'main.bundle')['refs'], header['refs'])

    def test_a_sha256_bundle_and_a_tag(self):
        facts = rc.expected()['facts']
        with open_repo('sha256 repo') as r:
            header = r.write_bundle(['refs/heads/main', 'refs/tags/s1'], self.tmp / 'sha256.bundle')
            tag = r._ref_value('refs/tags/s1')[1]
        self.assertEqual((header['version'], header['capabilities']), (3, ['object-format=sha256']))
        self.assertEqual(header['refs'], [[facts['H4'], 'refs/heads/main'], [tag, 'refs/tags/s1']])
        self.assertEqual(header['pack_trailer']['algorithm'], 'sha256')
        self.assertTrue(header['pack_trailer']['ok'])

    def test_refusals(self):
        with open_repo('repo one') as r:
            (self.tmp / 'exists.bundle').write_bytes(b'x')
            for refs, dest in ((['refs/heads/main'], 'exists.bundle'), (['refs/heads/nosuch'], 'a.bundle'),
                               (['main'], 'b.bundle'), ('refs/heads/main', 'c.bundle'), ([], 'd.bundle')):
                with self.subTest(refs=refs), self.assertRaises(ra.RepositoryError) as caught:
                    r.write_bundle(refs, self.tmp / dest)
                self.assertEqual(caught.exception.code, 'BUNDLE_INVALID')
        self.assertEqual((self.tmp / 'exists.bundle').read_bytes(), b'x')
        for name in ('a.bundle', 'b.bundle', 'c.bundle', 'd.bundle'):
            self.assertFalse((self.tmp / name).exists())

    def test_header_and_trailer_checks(self):
        path = self.tmp / 'garbage.bundle'
        for data in (b'not a bundle\n', b'# v2 git bundle\n' + b'x' * 10, b'# v2 git bundle\nbad line\n\n'):
            path.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(ra.RepositoryError) as caught:
                ra.parse_bundle_header(path)
            self.assertEqual(caught.exception.code, 'BUNDLE_INVALID')
        with open_repo('repo one') as r:
            r.write_bundle(['refs/heads/side'], self.tmp / 'side.bundle')
        data = bytearray((self.tmp / 'side.bundle').read_bytes())
        header = ra.parse_bundle_header(self.tmp / 'side.bundle')
        data[header['pack_offset'] + 20] ^= 0xff
        (self.tmp / 'flipped.bundle').write_bytes(bytes(data))
        self.assertFalse(ra.pack_trailer(self.tmp / 'flipped.bundle', header)['ok'])


class NoProcess(unittest.TestCase):
    """The module launches no process: every operation runs with process creation refused."""

    category = 'unit'

    def test_every_operation_without_a_process(self):
        refuse = AssertionError('a process was launched')
        patches = [mock.patch.object(subprocess, 'Popen', side_effect=refuse),
                   mock.patch.object(os, 'system', side_effect=refuse)]
        if os.name == 'nt':
            import _winapi
            patches.append(mock.patch.object(_winapi, 'CreateProcess', side_effect=refuse))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        dest = _empty_dir()
        for policy in ra.POLICIES:
            with self.subTest(policy=policy), open_repo('repo one', policy, work_tree=True) as r:
                r.commit('HEAD~1^2')
                r.read('HEAD:README.md')
                r.files('HEAD', 'docs')
                r.head()
                r.status(None, 'all')
                r.index_entries()
                r.listing(True, True, True)
                r.config_sources
        with open_repo('repo one') as r:
            r.export_tree('HEAD', 'openspec', dest)
            r.write_bundle(['refs/heads/side'], dest / 'x.bundle')


if __name__ == '__main__':
    unittest.main()
