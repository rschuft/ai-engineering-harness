"""The repository-access module's branch listing, ``Repository.branches()`` (decision 0014 section 8: reads
are added by the leaves that first need them; first needed by plan leaf P-01.3's capture, which settles a
receipt through every local branch).

Run from the repository root, under the tools interpreter (Dulwich is required: without it these tests
fail with REPOSITORY_NEEDS_DULWICH, never skip):

    <tools python> -I -B -m unittest discover -s integrations/repository/tests -v

git builds every fixture and is the oracle: ``git for-each-ref --format='%(refname) %(objectname)'
refs/heads/`` must equal the listing, for loose, packed, mixed and nested branches, a symbolic
reference, a linked worktree, a broken reference and a repository with no branch.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import repository_corpus as rc  # noqa: E402  (puts integrations/repository on sys.path)
import repository_access as ra  # noqa: E402


class Branches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ra.dulwich_modules()  # fail, never skip, without Dulwich
        cls.golden_root = Path(tempfile.mkdtemp(prefix='rb-'))
        repo = cls.golden_root / 'g'
        repo.mkdir()
        rc.git(repo, 'init', '--quiet', '-b', 'main')
        rc.write(repo, {'a.txt': 'one\n'})
        cls.one = rc.commit_all(repo, 'one', 1)
        rc.git(repo, 'branch', 'side')
        rc.git(repo, 'branch', 'feature/nested/deep')
        rc.write(repo, {'a.txt': 'two\n'})
        cls.two = rc.commit_all(repo, 'two', 2)

    @classmethod
    def tearDownClass(cls):
        rc.rmtree(cls.golden_root)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='rb-'))
        self.addCleanup(rc.rmtree, self.root)
        self.repo = self.root / 'r'
        shutil.copytree(self.golden_root / 'g', self.repo)

    def listing(self, path=None):
        with ra.open_repository(path or self.repo, config='repository', ceilings=[str(self.root)]) as repo:
            return repo.branches()

    def git_listing(self, path=None):
        text = rc.out(path or self.repo, 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/heads/')
        return dict(line.split(' ', 1) for line in text.splitlines() if line)

    def test_loose_branches_are_git_s(self):
        expected = {'refs/heads/main': self.two, 'refs/heads/side': self.one,
                    'refs/heads/feature/nested/deep': self.one}
        self.assertEqual(self.git_listing(), expected)
        self.assertEqual(self.listing(), expected)

    def test_packed_and_mixed_branches_are_git_s(self):
        rc.git(self.repo, 'pack-refs', '--all')
        self.assertFalse((self.repo / '.git' / 'refs' / 'heads' / 'side').exists())
        self.assertEqual(self.listing(), self.git_listing())
        rc.git(self.repo, 'update-ref', 'refs/heads/side', self.two)    # a loose value over the packed one
        rc.git(self.repo, 'branch', 'only-loose', self.one)
        expected = self.git_listing()
        self.assertEqual((expected['refs/heads/side'], expected['refs/heads/only-loose']), (self.two, self.one))
        self.assertEqual(self.listing(), expected)

    def test_a_symbolic_branch_answers_its_target_and_a_dangling_one_is_left_out(self):
        rc.git(self.repo, 'symbolic-ref', 'refs/heads/alias', 'refs/heads/side')
        rc.git(self.repo, 'symbolic-ref', 'refs/heads/dangling', 'refs/heads/absent')
        expected = self.git_listing()
        self.assertEqual(expected['refs/heads/alias'], self.one)
        self.assertTrue('refs/heads/dangling' not in expected)
        self.assertEqual(self.listing(), expected)

    def test_a_broken_reference_is_left_out_as_git_leaves_it(self):
        (self.repo / '.git' / 'refs' / 'heads' / 'broken').write_bytes(b'not an object id\n')
        expected = self.git_listing()
        self.assertTrue('refs/heads/broken' not in expected)
        self.assertEqual(self.listing(), expected)

    def test_a_linked_worktree_lists_the_common_directory_s_branches(self):
        tree = self.root / 'tree'
        rc.git(self.repo, 'worktree', 'add', '--quiet', '-b', 'in-tree', str(tree), self.one)
        expected = self.git_listing()
        self.assertEqual(expected['refs/heads/in-tree'], self.one)
        self.assertEqual(self.git_listing(tree), expected)
        self.assertEqual(self.listing(tree), expected)
        self.assertEqual(self.listing(), expected)

    def test_a_repository_without_a_branch_lists_none(self):
        empty = self.root / 'empty'
        empty.mkdir()
        rc.git(empty, 'init', '--quiet', '-b', 'main')
        self.assertEqual(self.git_listing(empty), {})
        self.assertEqual(self.listing(empty), {})


if __name__ == '__main__':
    unittest.main()
