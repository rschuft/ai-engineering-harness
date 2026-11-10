"""The repository-access module's contract suite, git-oracle half (plan leaf F-10.2).

Where git is on PATH, git is asked again, over the same extracted golden corpus, every question
the recorded expectations answer (``repository_corpus.answers``: ``rev-parse --verify
<form>^{commit}``, ``cat-file --batch-check``, ``ls-tree``, ``status``, ``ls-files``,
``symbolic-ref``, ``rev-parse --show-toplevel``), and the module must give git's answer. git's
answer must also still equal the recorded one, so the recorded half stays git's answer on this
host. Bundles the module writes must pass ``git bundle verify`` and list their references. Where
git is absent the whole module skips with that reason; the recorded half
(``test_repository_access.py``) still runs. Every git launch here belongs to the test fixtures.
"""
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import repository_corpus as rc  # noqa: E402
import repository_access as ra  # noqa: E402

GIT_ABSENT = 'git is not on PATH: the git-oracle comparison needs it (the recorded half still runs)'


def setUpModule():
    # Launch git by name and skip on FileNotFoundError, so that the launch counts the same with
    # and without git (docs/development.md, Budgets).
    try:
        subprocess.run(['git', '--version'], capture_output=True, stdin=subprocess.DEVNULL,
                       timeout=rc.WAIT_CEILING_S, check=False)
    except FileNotFoundError:
        raise unittest.SkipTest(GIT_ABSENT) from None


def open_repo(name, work_tree=False):
    return ra.open_repository(rc.corpus() / name, config='repository', work_tree=work_tree, ceilings=rc.ceilings())


class OracleAgreement(unittest.TestCase):
    """The module answers as git does, and git still answers as recorded."""

    @classmethod
    def setUpClass(cls):
        cls.root = rc.corpus()
        cls.expected = rc.expected()
        cls.live = rc.answers(cls.root, cls.expected['facts'], batch=True)

    def test_rev_parse_gives_the_batched_answers_for_the_proof_forms(self):
        """The commit forms are asked of one cat-file --batch-check per repository; rev-parse
        --verify, which recorded them, gives the same answers (here for the forms the plan's
        proof names, and for every form through the recorded answers)."""
        facts = self.expected['facts']
        oracle = rc.Oracle(self.root)
        sample = {'repo one': ['HEAD~1', 'HEAD^2', '@', 'main@{0}', 'HEAD^{tree}', 'v1^{}', 'HEAD~1:README.md',
                               facts['amb4'], facts['cb4'], 'main@{99}', f'v1-1-g{facts["E"][:7]}', ':README.md'],
                  'sha256 repo': ['HEAD~1', 'HEAD^2', facts['H4'][:7]], 'linked tree': ['HEAD@{1}', 'wtb@{0}']}
        for repo, forms in sample.items():
            batched = dict(self.live['repos'][repo]['commits'])
            for form in forms:
                with self.subTest(repo=repo, form=form):
                    self.assertEqual(oracle.commit(repo, form), batched[form])

    def test_git_still_gives_the_recorded_answers(self):
        for repo, recorded in self.expected['repos'].items():
            live = self.live['repos'].get(repo, {})
            for section in ('commits', 'names', 'files', 'export', 'status', 'index', 'listing', 'head'):
                if section in recorded:
                    with self.subTest(repo=repo, section=section):
                        self.assertEqual(live[section], recorded[section])
        self.assertEqual(self.live['work_trees'], self.expected['work_trees'])

    def test_commit_forms(self):
        for repo, data in self.live['repos'].items():
            with open_repo(repo) as r:
                for form, git in data['commits']:
                    with self.subTest(repo=repo, form=form):
                        self.assertEqual(r.commit(form), git)

    def test_object_names(self):
        for repo, data in self.live['repos'].items():
            with open_repo(repo) as r:
                for name, git in data['names']:
                    with self.subTest(repo=repo, name=name):
                        found = r.read(name)
                        self.assertEqual([found[0], found[1]] if found else None, git)

    def test_file_lists_heads_index_status_and_listings(self):
        for repo, data in self.live['repos'].items():
            with open_repo(repo) as r:
                for commit, directory, git in data.get('files', []):
                    with self.subTest(repo=repo, files=directory):
                        self.assertEqual(r.files(commit, directory), git)
                if 'head' in data:
                    with self.subTest(repo=repo, head=True):
                        self.assertEqual([r.head().commit, r.head().ref], data['head'])
                if 'index' in data:
                    with self.subTest(repo=repo, index=True):
                        self.assertEqual([[e.mode, e.oid, e.stage, e.path] for e in r.index_entries()], data['index'])
                for untracked, paths, git in data.get('status', []):
                    with self.subTest(repo=repo, status=untracked, paths=paths):
                        self.assertEqual([[e.xy, e.path] for e in r.status(paths, untracked)], git)
                for cached, others, exclude, git in data.get('listing', []):
                    with self.subTest(repo=repo, listing=(cached, others, exclude)):
                        self.assertEqual(r.listing(cached, others, exclude), git)

    def test_git_still_gives_the_recorded_case_answers(self):
        """The F-10.4 cases: ignore rules, attributes, the size rule, full reference names."""
        for repo, recorded in self.expected['cases'].items():
            with self.subTest(repo=repo):
                self.assertEqual(self.live['cases'][repo], recorded)
        self.assertEqual(self.live['full_names'], self.expected['full_names'])

    def test_case_listings_status_and_index(self):
        for repo, data in self.live['cases'].items():
            with open_repo(repo, work_tree=True) as r:
                with self.subTest(repo=repo, index=True):
                    self.assertEqual([[e.mode, e.oid, e.stage, e.path] for e in r.index_entries()], data['index'])
                for cached, others, exclude, git in data['listing']:
                    with self.subTest(repo=repo, listing=(cached, others, exclude)):
                        mine = r.listing(cached, others, exclude)
                        self.assertEqual(set(git) - set(mine), set(), 'never a strict subset of git')
                        self.assertEqual(mine, git)
                for untracked, paths, git in data['status']:
                    with self.subTest(repo=repo, status=untracked, paths=paths):
                        self.assertEqual([[e.xy, e.path] for e in r.status(paths, untracked)], git)

    def test_full_names_are_gits_symbolic_full_names(self):
        for repo, rows in self.live['full_names'].items():
            with open_repo(repo) as r:
                for name, git in rows:
                    with self.subTest(repo=repo, name=name):
                        self.assertEqual(r.full_name(name), git)

    def test_ceilings_are_gits(self):
        """GIT_CEILING_DIRECTORIES: a ceiling between a directory and its repository hides the
        repository from git and from the module; the start directory itself is still examined."""
        oracle = rc.Oracle(self.root)
        cases = [('repo one/docs', 'repo one'), ('repo one', 'repo one'), ('repo one/docs', 'repo one/docs'),
                 ('linked tree', 'repo one')]
        for subject, ceiling in cases:
            with self.subTest(subject=subject, ceiling=ceiling):
                env = {**os.environ, **oracle.env, 'GIT_CEILING_DIRECTORIES': str((self.root / ceiling).resolve())}
                result = subprocess.run(['git', '-C', str(self.root / subject), 'rev-parse', '--show-toplevel'],
                                        capture_output=True, stdin=subprocess.DEVNULL, timeout=rc.WAIT_CEILING_S, env=env)
                git = os.path.realpath(result.stdout.decode('utf-8').strip()) if result.returncode == 0 else None
                try:
                    with ra.open_repository(self.root / subject, config='repository',
                                            ceilings=[str(self.root / ceiling)]) as r:
                        mine = os.path.realpath(r.root)
                except ra.CannotRun:
                    mine = None
                self.assertEqual(mine and os.path.normcase(mine), git and os.path.normcase(git))

    def test_exports_are_git_blob_bytes(self):
        tmp = Path(tempfile.mkdtemp(prefix='aieh-repo-oracle-export-'))
        self.addCleanup(rc.rmtree, tmp)
        number = 0
        for repo, data in self.live['repos'].items():
            for commit, subtree, members in data.get('export', []):
                number += 1
                dest = tmp / str(number)
                dest.mkdir()
                with self.subTest(repo=repo, commit=commit, subtree=subtree), open_repo(repo) as r:
                    r.export_tree(commit, subtree, dest)
                    for path, mode, sha, size in members:
                        target = dest.joinpath(*path.split('/'))
                        if mode in ('100644', '100755'):
                            data_ = target.read_bytes()
                            self.assertEqual(len(data_), size, path)
                            self.assertEqual(hashlib.sha256(data_).hexdigest(), sha, path)

    def test_the_work_tree_check(self):
        for subject, git in self.live['work_trees']:
            with self.subTest(subject=subject):
                try:
                    with ra.open_repository(self.root / subject, config='repository', ceilings=rc.ceilings()) as r:
                        got = Path(os.path.relpath(os.path.realpath(r.root), os.path.realpath(self.root))).as_posix()
                except ra.CannotRun:
                    got = None
                self.assertEqual(got, git)


class OracleHostFiles(unittest.TestCase):
    """The host policy reads the files git reads on this host (``git var``, git 2.42 or later),
    under the environment without git's configuration-location variables."""

    @classmethod
    def setUpClass(cls):
        cls.env = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_CONFIG', 'GIT_ATTR'))}

    def git(self, *args):
        result = subprocess.run(['git', *args], capture_output=True, stdin=subprocess.DEVNULL,
                                timeout=rc.WAIT_CEILING_S, env=self.env, cwd=rc.corpus() / 'repo one')
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line for line in result.stdout.decode('utf-8').splitlines() if line]

    def same(self, a, b):
        return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))

    def test_the_system_and_global_files_are_gits(self):
        with mock.patch.dict(os.environ, self.env, clear=True), \
                ra.open_repository(rc.corpus() / 'repo one', config='host', ceilings=rc.ceilings()) as r:
            paths = ra.host_config_paths()
            attributes = r.attribute_files()
            r.status(None, 'no')
            sources = r.config_sources
        system = self.git('var', 'GIT_CONFIG_SYSTEM')[0]
        self.assertTrue(self.same(system, paths[-1]), (system, paths))
        self.assertEqual(len(paths), 3)
        globals_ = self.git('var', 'GIT_CONFIG_GLOBAL')
        self.assertEqual(sorted(os.path.normcase(os.path.normpath(p)) for p in globals_),
                         sorted(os.path.normcase(os.path.normpath(p)) for p in paths[:2]))
        self.assertTrue(self.same(self.git('var', 'GIT_ATTR_SYSTEM')[0], attributes[0]), attributes)
        self.assertTrue(self.same(self.git('var', 'GIT_ATTR_GLOBAL')[0], attributes[-1]), attributes)
        # Every system file git reads, host reads too.
        origins = {line.split('\t', 1)[0].removeprefix('file:') for line in
                   self.git('config', '--system', '--list', '--show-origin')}
        for origin in origins:
            self.assertTrue(any(self.same(origin, source) for source in sources), (origin, sources))


class OracleReplaced(unittest.TestCase):
    """git applies the replace references the module refuses (live, as recorded)."""

    def test_git_replaces(self):
        oracle = rc.Oracle(rc.corpus())
        for repo in ('replace loose', 'replace packed'):
            recorded = rc.expected()['repos'][repo]['replaced_names']
            live = oracle.names(repo, [name for name, _ in recorded])
            with self.subTest(repo=repo):
                self.assertEqual([[name, live[name]] for name, _ in recorded], recorded)


class OracleBundles(unittest.TestCase):
    """git accepts the bundles the module writes."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-repo-oracle-bundle-'))
        cls.oracle = rc.Oracle(rc.corpus())

    @classmethod
    def tearDownClass(cls):
        rc.rmtree(cls.tmp)

    def test_bundles_verify(self):
        cases = [('repo one', ['refs/heads/main']), ('repo one', ['refs/heads/side', 'refs/tags/v1']),
                 ('packed copy', ['refs/heads/main']), ('sha256 repo', ['refs/heads/main', 'refs/tags/s1']),
                 ('long.git', ['refs/heads/main'])]
        for number, (repo, refs) in enumerate(cases):
            with self.subTest(repo=repo, refs=refs):
                path = self.tmp / f'{number} ü.bundle'
                with open_repo(repo) as r:
                    header = r.write_bundle(refs, path)
                self.assertTrue(header['pack_trailer']['ok'])
                code, err = self.oracle.bundle_verify(repo, path)
                self.assertEqual(code, 0, err)
                code, heads = self.oracle.bundle_heads(repo, path)
                self.assertEqual(code, 0)
                self.assertEqual([line.split(' ', 1) for line in heads], header['refs'])
                # git's own bundle of the same references carries the same header.
                own = self.tmp / f'{number}-git.bundle'
                created = self.oracle.run(repo, 'bundle', 'create', '--quiet', str(own), *refs)
                self.assertEqual(created.returncode, 0, created.stderr)
                theirs = ra.parse_bundle_header(own)
                self.assertEqual((theirs['version'], theirs['capabilities'], theirs['prerequisites']),
                                 (header['version'], header['capabilities'], header['prerequisites']))
                self.assertEqual(sorted(theirs['refs']), sorted(header['refs']))
                self.assertTrue(ra.pack_trailer(own, theirs)['ok'])


class OracleTransport(unittest.TestCase):
    """git agrees with the transports (F-10.6) over the local smart-HTTP server of
    ``test_repository_transport``: ``git ls-remote`` lists what ``ls_remote`` lists, and
    ``git fsck --strict`` accepts the module's clone and the served repository after a module
    push. git gets the test credential as an ``http.extraHeader`` in its own environment."""

    def setUp(self):
        import test_repository_transport as tt
        self.tt = tt
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-repo-oracle-transport-'))
        self.addCleanup(rc.rmtree, self.tmp)
        self.remote, self.ids = tt.served(self.tmp / 'remote.git')
        self.local_path = tt.local_copy(self.tmp / 'local.git')
        self.addCleanup(tt.stop_golden)
        self.addCleanup(tt.stop_server)
        self.addCleanup(self.remote.close)

    def git(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
        env.update(rc.GIT_ENV, GIT_TERMINAL_PROMPT='0', GIT_CEILING_DIRECTORIES=str(self.tmp), GIT_CONFIG_COUNT='2',
                   GIT_CONFIG_KEY_0='http.extraHeader',
                   GIT_CONFIG_VALUE_0='Authorization: ' + self.tt.TOKEN.authorization(),
                   GIT_CONFIG_KEY_1='credential.helper', GIT_CONFIG_VALUE_1='')
        result = subprocess.run(['git', *args], capture_output=True, stdin=subprocess.DEVNULL, env=env,
                                timeout=rc.WAIT_CEILING_S)
        return result.returncode, result.stdout.decode('utf-8'), result.stderr.decode('utf-8', 'replace')

    def test_ls_remote_clone_and_push_are_gits(self):
        code, out, err = self.git('ls-remote', self.remote.url)
        self.assertEqual(code, 0, err)
        listed = dict(reversed(line.split('\t')) for line in out.splitlines())
        self.assertEqual(ra.ls_remote(self.remote.url, self.tt.TOKEN), listed)
        clone = self.tmp / 'clone.git'
        written = ra.clone(self.remote.url, clone, self.tt.TOKEN)
        self.assertEqual(written, {k: v for k, v in listed.items() if k.startswith(('refs/heads/', 'refs/tags/'))
                                   and not k.endswith('^{}')})
        code, out, err = self.git('--git-dir', str(clone), 'fsck', '--strict', '--no-progress')
        self.assertEqual((code, out, err), (0, '', ''))
        with ra.open_repository(self.local_path, config='repository', work_tree=False, ceilings=[self.tmp]) as r:
            r.push(self.remote.url, 'HEAD:refs/heads/main', self.tt.TOKEN)
            r.push(self.remote.url, f'+{self.ids["orphan"].decode()}:refs/heads/side', self.tt.BASIC)
        code, out, err = self.git('--git-dir', str(self.remote.path), 'fsck', '--strict', '--no-progress')
        self.assertEqual((code, out, err), (0, '', ''))
        refs = self.remote.refs()
        self.assertEqual((refs[b'refs/heads/main'], refs[b'refs/heads/side']), (self.ids['c3'], self.ids['orphan']))


if __name__ == '__main__':
    unittest.main()
