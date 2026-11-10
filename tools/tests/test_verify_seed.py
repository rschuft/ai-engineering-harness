"""Tests for tools/verify_seed.py (stdlib unittest).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

Every test runs the verifier on a temporary copy of the seeded files, or on a
temporary git repository built here. The only use of the checkout itself is
reading its files to copy them and one read-only baseline run against its own
git history. Each class copies the seeded files once; a test that writes gets a
private copy of that copy, and the tests that only read use the class's copy
itself and check that it is unchanged afterwards (``SeedCopy.READS_ONLY``).

The command-line contract (the exit status and the PASS, FAIL and ERROR lines of a
real run, git missing from PATH, a directory that is not a repository, and the
checkout's own baseline) is checked by running the verifier as a subprocess
(``run_verifier``). The logic cases (which edits fail, which pass) run the copy's
own verify_seed.py in this process (``verify``, plan leaf F-09.3): its ``main`` is
the command's, and its git reads in baseline mode are real git processes.
"""
from pathlib import Path
import atexit
import contextlib
import hashlib
import importlib.util
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

CATEGORY = 'contract'

REPO = Path(__file__).resolve().parents[2]
VERIFIER = 'tools/verify_seed.py'
PLAN = 'AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json'
PLAN_HTML = 'AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.html'
CSV = 'AI_Engineering_Implementation_Work_Packages_Small_Steps_2026-10-31.csv'
BLUEPRINT = 'AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html'
ORDINARY = ('README.md', 'CLAUDE.md', '.gitignore')

# Isolated git: no user/system config (autocrlf, signing, hooks), fixed identity.
GIT_ENV = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME='test', GIT_AUTHOR_EMAIL='test@example.invalid',
               GIT_COMMITTER_NAME='test', GIT_COMMITTER_EMAIL='test@example.invalid')


def seed_paths():
    manifest = json.loads((REPO / 'SEED_MANIFEST.json').read_text(encoding='utf-8'))
    return ['SEED_MANIFEST.json'] + [item['path'] for item in manifest['files']]


def run_verifier(root, *args, env=None):
    return subprocess.run([sys.executable, '-I', '-B', str(root / VERIFIER), *args],
                          capture_output=True, text=True, encoding='utf-8', env=env)


_loaded = itertools.count()


def verify(root, *args):
    """The verifier's logic in this process: ROOT's own verify_seed.py, loaded afresh (so its
    ROOT is the copy, as when it runs from there), its main() called with ARGS. Returns what
    run_verifier returns: the exit status and the text of stdout and stderr."""
    spec = importlib.util.spec_from_file_location(f'verify_seed_under_test_{next(_loaded)}',
                                                  root / VERIFIER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = module.main(list(args))
        except SystemExit as exc:  # argparse refusals, as the command would exit
            code = exc.code if isinstance(exc.code, int) else 1
    return subprocess.CompletedProcess([VERIFIER, *args], code, out.getvalue(), err.getvalue())


def rehash(root, rel):
    """The versioned update process: record REL's new sha256 in ROOT's manifest."""
    path = root / 'SEED_MANIFEST.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    data = (root / rel).read_bytes()
    for item in manifest['files']:
        if item['path'] == rel:
            item['sha256'] = hashlib.sha256(data).hexdigest()
            item['size_bytes'] = len(data)
    path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True,
                          env=GIT_ENV, check=True).stdout.strip()


def git_available():
    try:
        subprocess.run(['git', '--version'], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def tree_digest(root):
    """sha256 over every file's relative path and bytes under ROOT."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode('utf-8') + b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class SeedCopy(unittest.TestCase):
    """A temporary copy of the seeded files: copied once per class, then copied again for
    each test that writes. The tests named in READS_ONLY only read, so they use the class's
    copy itself, and each of them checks afterwards that it is unchanged."""
    READS_ONLY = frozenset()

    @classmethod
    def setUpClass(cls):
        shared = tempfile.TemporaryDirectory(prefix='verify_seed_')
        cls.addClassCleanup(shared.cleanup)
        cls.shared = Path(shared.name) / 'seed'
        for rel in seed_paths():
            dst = cls.shared / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, dst)
        # Ordinary files evolve after the seed; record the checkout's current
        # bytes in the copy's manifest so the copy starts out fully consistent.
        for rel in ORDINARY:
            rehash(cls.shared, rel)
        cls.shared_digest = tree_digest(cls.shared)

    def setUp(self):
        self._tmp = None
        if self._testMethodName in self.READS_ONLY:
            self.root = self.shared
            return
        self._tmp = tempfile.TemporaryDirectory(prefix='verify_seed_')
        self.root = Path(self._tmp.name) / 'seed'
        # Plain file copies: git's read-only object files become writable copies.
        shutil.copytree(self.source(), self.root, copy_function=shutil.copyfile)

    def source(self):
        """The tree a writing test's private copy is made from."""
        return self.shared

    def tearDown(self):
        if self._tmp is not None:
            self._tmp.cleanup()
        else:
            self.assertEqual(tree_digest(self.shared), self.shared_digest,
                             'a test that writes is listed in READS_ONLY: the shared copy changed')

    def append(self, rel, text='\nlocal edit\n'):
        with open(self.root / rel, 'ab') as fh:
            fh.write(text.encode('utf-8'))

    def manifest(self):
        return json.loads((self.root / 'SEED_MANIFEST.json').read_text(encoding='utf-8'))

    def write_manifest(self, manifest):
        (self.root / 'SEED_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n',
                                                      encoding='utf-8')

    def rehash(self, rel):
        """The versioned update process: record REL's new sha256 in the manifest."""
        rehash(self.root, rel)

    def assertPass(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r'(?m)^PASS')

    def assertFail(self, result, message):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f'FAIL: {message}', result.stderr)


class DefaultMode(SeedCopy):
    READS_ONLY = frozenset({'test_unchanged_tree_passes', 'test_works_without_git'})

    def test_unchanged_tree_passes(self):
        result = run_verifier(self.root)
        self.assertPass(result)
        # The contract count follows the plan's size (one prompt per leaf), so
        # derive it from the manifest rather than fixing a number.
        authority = (BLUEPRINT, 'OVERSEER_START.md')
        contract = sum(1 for item in self.manifest()['files']
                       if item['path'] not in ORDINARY + authority)
        self.assertIn(f'{contract} contract intact, 2 authority intact, 3 ordinary, '
                      '0 changed since seed', result.stdout)
        self.assertNotIn('INFO:', result.stdout)

    def test_ordinary_edits_pass_with_info(self):
        for rel in ('README.md', 'CLAUDE.md', '.gitignore'):
            with self.subTest(rel=rel):
                self.append(rel)
                result = verify(self.root)
                self.assertPass(result)
                self.assertIn(f'INFO: ordinary file changed since seed: {rel}', result.stdout)
        self.assertIn('3 changed since seed', result.stdout)

    def test_missing_ordinary_file_is_info(self):
        (self.root / 'README.md').unlink()
        result = verify(self.root)
        self.assertPass(result)
        self.assertIn('INFO: ordinary file missing: README.md', result.stdout)

    def test_contract_and_authority_edits_fail_without_manifest_update(self):
        cases = [(PLAN, 'contract'), ('task_prompts/F-02.md', 'contract'),
                 ('task_manifest.json', 'contract'), (CSV, 'contract'),
                 (PLAN_HTML, 'contract'), (VERIFIER, 'contract'),
                 (BLUEPRINT, 'authority'), ('OVERSEER_START.md', 'authority')]
        for rel, cls in cases:
            with self.subTest(rel=rel):
                original = (self.root / rel).read_bytes()
                # Whitespace keeps JSON and Python parseable, so only the hash check trips.
                self.append(rel, '\n')
                self.assertFail(verify(self.root), f'changed {cls} file: {rel}')
                (self.root / rel).write_bytes(original)
                self.assertPass(verify(self.root))

    def test_edited_prompt_also_fails_task_manifest_hash(self):
        self.append('task_prompts/F-02.md')
        self.assertFail(verify(self.root), 'prompt content mismatch: task_prompts/F-02.md')

    def test_missing_contract_file_fails(self):
        (self.root / CSV).unlink()
        self.assertFail(run_verifier(self.root), f'missing contract file: {CSV}')

    def test_authority_edit_with_manifest_update_passes(self):
        for rel in (BLUEPRINT, 'OVERSEER_START.md'):
            with self.subTest(rel=rel):
                self.append(rel)
                self.rehash(rel)
                result = verify(self.root)
                self.assertPass(result)
                self.assertIn('2 authority intact', result.stdout)

    def test_unclassified_manifest_path_fails(self):
        (self.root / 'NEW_FILE.md').write_text('new\n', encoding='utf-8')
        manifest = self.manifest()
        manifest['files'].append({'path': 'NEW_FILE.md', 'sha256': '0' * 64, 'size_bytes': 4})
        self.write_manifest(manifest)
        self.rehash('NEW_FILE.md')
        self.assertFail(verify(self.root), 'unclassified manifest path: NEW_FILE.md')

    def test_license_in_manifest_fails(self):
        (self.root / 'LICENSE').write_text('licence\n', encoding='utf-8')
        manifest = self.manifest()
        manifest['files'].append({'path': 'LICENSE', 'sha256': '0' * 64, 'size_bytes': 8})
        self.write_manifest(manifest)
        self.assertFail(verify(self.root), 'seed would overwrite repository LICENSE')

    def edit_plan(self, change):
        plan = json.loads((self.root / PLAN).read_text(encoding='utf-8'))
        change({t['id']: t for t in plan['work_packages']})
        (self.root / PLAN).write_text(json.dumps(plan, indent=2), encoding='utf-8')
        self.rehash(PLAN)  # isolate the graph check from the hash check

    def test_dependency_cycle_fails(self):
        def make_cycle(tasks):
            child = next(t for t in tasks.values() if t['deps'])
            tasks[child['deps'][0]]['deps'].append(child['id'])
        self.edit_plan(make_cycle)
        self.assertFail(verify(self.root),
                        'dependency graph contains a cycle or unresolved reference')

    def test_unknown_dependency_fails(self):
        self.edit_plan(lambda tasks: tasks['F-02']['deps'].append('Z-99.9'))
        self.assertFail(verify(self.root), "unknown dependency IDs: [('F-02', 'Z-99.9')]")

    def test_non_small_task_fails(self):
        self.edit_plan(lambda tasks: tasks['F-02'].update(size='M'))
        self.assertFail(verify(self.root), 'a non-Small executable task is present')

    def test_works_without_git(self):
        # The copy is not a repository, and PATH holds only an empty directory
        # (Python's own directory may also hold git, e.g. /usr/bin on Linux).
        empty = self.root.parent / 'empty-path'
        empty.mkdir()
        no_git = {k: v for k, v in os.environ.items() if k.upper() != 'PATH'}
        no_git['PATH'] = str(empty)
        no_git['GIT_CEILING_DIRECTORIES'] = str(self.root.parent)
        probe = subprocess.run([sys.executable, '-I', '-c',
                                'import shutil; print(shutil.which("git"))'],
                               capture_output=True, text=True, env=no_git)
        self.assertEqual(probe.stdout.strip(), 'None')
        self.assertPass(run_verifier(self.root, env=no_git))
        result = run_verifier(self.root, '--baseline', 'seed', env=no_git)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('ERROR: git is unavailable', result.stderr)


@unittest.skipUnless(git_available(), 'git is not available')
class BaselineMode(SeedCopy):
    """Each test starts from a copy of one repository built per class (``golden``): the seeded
    files with ``git init`` run, every file staged and the staged objects packed, nothing
    committed. A test's first ``commit_all`` then commits the same tree as from a fresh
    ``git init``, without writing the objects again; every commit is the test's own."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.golden = golden_repository(cls.shared, cls.shared_digest)

    def source(self):
        return self.golden

    def commit_all(self, message):
        git(self.root, 'add', '--all')
        git(self.root, 'commit', '--quiet', '--no-verify', '-m', message)
        return git(self.root, 'rev-parse', 'HEAD')

    def test_baseline_reads_object_database_not_working_tree(self):
        clean = self.commit_all('seed')
        self.append(CSV)
        (self.root / 'README.md').unlink()
        self.assertFail(verify(self.root), f'changed contract file: {CSV}')
        result = verify(self.root, '--baseline', clean)
        self.assertPass(result)
        self.assertIn(f'PASS (baseline {clean})', result.stdout)
        self.assertIn('all strict', result.stdout)

    def test_tampered_baseline_commit_fails(self):
        cases = [('README.md', 'ordinary'), ('task_prompts/F-02.md', 'contract'),
                 (BLUEPRINT, 'authority')]
        for rel, cls in cases:
            with self.subTest(rel=rel):
                original = (self.root / rel).read_bytes()
                self.append(rel)
                tampered = self.commit_all(f'tamper {rel}')
                (self.root / rel).write_bytes(original)  # working tree is clean again
                self.assertPass(verify(self.root))
                self.assertFail(verify(self.root, '--baseline', tampered),
                                f'changed {cls} file: {rel}')

    def test_baseline_checks_task_manifest_consistency(self):
        manifest = json.loads((self.root / 'task_manifest.json').read_text(encoding='utf-8'))
        manifest['tasks'][0]['deps'] = ['Z-99.9']
        (self.root / 'task_manifest.json').write_text(json.dumps(manifest, indent=2),
                                                      encoding='utf-8')
        self.rehash('task_manifest.json')
        rev = self.commit_all('inconsistent task manifest')
        self.assertFail(verify(self.root, '--baseline', rev),
                        f'prompt dependency mismatch: {manifest["tasks"][0]["id"]}')

    def test_unknown_revision_cannot_run(self):
        self.commit_all('seed')
        result = run_verifier(self.root, '--baseline', 'no-such-revision')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('ERROR: baseline revision not available: no-such-revision', result.stderr)

    def test_not_a_repository_cannot_run(self):
        shutil.rmtree(self.root / '.git')
        env = dict(GIT_ENV, GIT_CEILING_DIRECTORIES=str(self.root.parent))
        result = run_verifier(self.root, '--baseline', 'seed', env=env)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('ERROR: not a git repository', result.stderr)


_golden = {}


def golden_repository(seed, digest):
    """A repository made once per process for each digest of the seeded files SEED: a copy of
    them with ``git init`` run, every file staged and the staged objects in one pack (nothing
    committed). Removed at exit."""
    if digest not in _golden:
        tmp = tempfile.TemporaryDirectory(prefix='verify_seed_golden_')
        atexit.register(tmp.cleanup)
        root = Path(tmp.name) / 'seed'
        shutil.copytree(seed, root, copy_function=shutil.copyfile)
        # --template= (empty): no sample hooks, info/exclude or description, which nothing here reads;
        # 16 fewer files in every copy (plan leaf F-09). The repository and its commits are the same.
        git(root, 'init', '--quiet', '--template=')
        git(root, 'add', '--all')
        git(root, 'repack', '-a', '-d', '-q')
        git(root, 'prune-packed')
        _golden[digest] = root
    return _golden[digest]


def checkout_has_full_history():
    if not git_available():
        return False
    probe = subprocess.run(['git', '-C', str(REPO), 'rev-parse', '--is-shallow-repository'],
                           capture_output=True, text=True)
    return probe.returncode == 0 and probe.stdout.strip() == 'false'


@unittest.skipUnless(checkout_has_full_history(), 'checkout is not a full git clone')
class RealBootstrapBaseline(unittest.TestCase):

    def test_seed_baseline_of_this_repository_passes(self):
        # Read-only: baseline mode reads only git objects of this checkout.
        result = run_verifier(REPO, '--baseline', 'seed')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS (baseline 13197ddf1b4b49924add5dda21c39ac619cbdf3b)', result.stdout)
        self.assertIn('146 intact seeded files, all strict '
                      '(141 contract, 2 authority, 3 ordinary)', result.stdout)


if __name__ == '__main__':
    unittest.main()
