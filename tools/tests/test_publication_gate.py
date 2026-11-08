"""Tests for tools/publication_gate.py and its .githooks hooks (stdlib unittest).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

Every gate test builds a throwaway git repository with an isolated git
configuration (no system or global config, a temporary HOME and tool cache),
copies the gate, its hooks and .gitleaks.toml into it, and drives real
`git commit` and `git push` against a local bare "origin". All secrets and
personal paths are synthetic and assembled at run time, so this file contains
none of them literally.

Tests that need the real scanner copy the pinned Gitleaks from the per-user
cache (installed by `task hooks:install`) into the temporary cache. They are
skipped when it is not installed, unless AIEH_GATE_REQUIRE_SCANNER=1, which
`task hooks:verify` sets. The fail-closed tests need no scanner: they use an
empty cache, a corrupted binary, or a stub scanner run by a throwaway copy of
the gate whose pinned scanner identity is replaced.
"""
from pathlib import Path
import atexit
import gzip
import hashlib
import importlib.util
import io
import os
import random
import shutil
import stat
import string
import subprocess
import sys
import tempfile
import unittest

CATEGORY = 'integration'

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / 'tools' / 'publication_gate.py'
HOOK_FILES = ('pre-commit', 'pre-push', 'gate-common.sh')
REQUIRE_SCANNER = os.environ.get('AIEH_GATE_REQUIRE_SCANNER') == '1'
NESTED = os.environ.get('AIEH_GATE_NESTED_SUITE') == '1'
TIMEOUT = 300


def load_gate():
    spec = importlib.util.spec_from_file_location('publication_gate_under_test', GATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = load_gate()

# Synthetic values: random-looking, generated per run from a fixed seed, never real.
_rng = random.Random(20261105)


def _synthetic(alphabet, length):
    return ''.join(_rng.choice(alphabet) for _ in range(length))


FAKE_AWS_KEY = 'AKIA' + _synthetic('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567', 16)
FAKE_GITHUB_TOKEN = 'ghp' + '_' + _synthetic(string.ascii_letters + string.digits, 36)
PERSON = 'mmuster' + 'mann'
BS = '\\'
SECRETS = (FAKE_AWS_KEY, FAKE_GITHUB_TOKEN)


def real_scanner():
    """The verified scanner in the real per-user cache, or None."""
    try:
        name, want = gate.expected_scanner()
        path = gate.tool_dir() / name
    except gate.GateError:
        return None
    if path.is_file() and gate.sha256_file(path) == want:
        return path
    return None


def remove_tree(path):
    def make_writable(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    shutil.rmtree(path, onexc=make_writable)


def clean_environ():
    """The caller's environment without git or Gitleaks state (tests may run inside a hook)."""
    return {k: v for k, v in os.environ.items()
            if not k.upper().startswith(('GIT_', 'GITLEAKS'))}


def shared_scanner_cache(testcase_class, scanner):
    """A tool cache holding a copy of SCANNER, shared by the tests of one class that only run
    the scanner (plan leaf F-09.3): the gate reads the cache and never writes it, so one copy
    serves every repository of the class. Removed when the class finishes."""
    cache = Path(tempfile.mkdtemp(prefix='aieh-gate-cache-'))
    testcase_class.addClassCleanup(remove_tree, cache)
    tool_dir = gate.tool_dir({'LOCALAPPDATA': str(cache), 'XDG_CACHE_HOME': str(cache)})
    tool_dir.mkdir(parents=True)
    shutil.copyfile(scanner, tool_dir / gate.expected_scanner()[0])
    return cache


# Golden gate repositories (plan leaf F-09.3): the initial repository pair (the work tree
# with its first commit, pushed to a bare 'origin') is built once per process for each set of
# inputs and copied per test with plain file copies.
_golden_root = None
_golden = {}


def _golden_repositories(files):
    """(directory holding 'work' and 'origin.git', initial commit) for FILES ({path: bytes})."""
    global _golden_root
    digest = hashlib.sha256()
    for path, data in sorted(files.items()):
        digest.update(path.encode('utf-8') + b'\x00' + hashlib.sha256(data).digest())
    key = digest.hexdigest()[:16]
    if key not in _golden:
        if _golden_root is None:
            _golden_root = Path(tempfile.mkdtemp(prefix='aieh-gate-golden-'))
            atexit.register(remove_tree, _golden_root)
        base = _golden_root / key
        root, remote, no_hooks, home = base / 'work', base / 'origin.git', base / 'no-hooks', base / 'home'
        no_hooks.mkdir(parents=True)
        home.mkdir()
        env = isolated_git_env(home)

        def git(*args):
            subprocess.run(['git', '-C', str(root), *args], env=env, check=True, capture_output=True,
                           timeout=TIMEOUT)
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(root)], env=env, check=True)
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(remote)], env=env, check=True)
        for rel, data in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        git('add', '-A')
        git('update-index', '--chmod=+x', '.githooks/pre-commit', '.githooks/pre-push')
        git('-c', f'core.hooksPath={no_hooks}', 'commit', '-q', '-m', 'add the gate')
        git('remote', 'add', 'origin', str(remote))
        git('-c', f'core.hooksPath={no_hooks}', 'push', '-q', 'origin', 'main')
        git('config', 'core.hooksPath', '.githooks')
        initial = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], env=env, check=True,
                                 capture_output=True).stdout.decode('ascii').strip()
        _golden[key] = (base, initial)
    return _golden[key]


def isolated_git_env(home, cache=None, shims=None):
    """The gate repositories' environment: no system or global git config, a fixed identity,
    HOME and the tool cache in temporary directories."""
    env = clean_environ()
    cache = home.parent / 'cache' if cache is None else cache
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0',
               GIT_AUTHOR_NAME='test', GIT_AUTHOR_EMAIL='test@example.invalid',
               GIT_COMMITTER_NAME='test', GIT_COMMITTER_EMAIL='test@example.invalid',
               HOME=str(home), USERPROFILE=str(home),
               XDG_CACHE_HOME=str(cache), LOCALAPPDATA=str(cache),
               GNUPGHOME=str(home.parent / 'gnupg'))
    if shims is not None:
        env['PATH'] = str(shims) + os.pathsep + os.environ.get('PATH', '')
    return env


class GateRepo:
    """A throwaway repository wired to the gate, with a bare 'origin'.

    The initial pair (the gate, its hooks and configuration committed and pushed) is a copy of
    a golden pair built once per set of inputs; the copy's 'origin' is then pointed at its own
    bare repository. With CACHE (a shared_scanner_cache), the tool cache is shared; otherwise
    each repository has its own, holding a copy of SCANNER if given."""

    def __init__(self, testcase, scanner=None, gate_source=None, config=None, cache=None):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-gate-test-'))
        testcase.addCleanup(remove_tree, self.tmp)
        self.root = self.tmp / 'work'
        self.remote = self.tmp / 'origin.git'
        self.no_hooks = self.tmp / 'no-hooks'
        self.no_hooks.mkdir()
        (self.tmp / 'home').mkdir()
        # The hooks look for python3 first: point it at this interpreter, so the
        # temporary LOCALAPPDATA cannot confuse a platform launcher.
        shims = self.tmp / 'bin'
        shims.mkdir()
        (shims / 'python3').write_text(f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n',
                                       encoding='utf-8', newline='\n')
        os.chmod(shims / 'python3', 0o755)
        self.env = isolated_git_env(self.tmp / 'home', None if cache is None else Path(cache), shims)
        self.tool_dir = gate.tool_dir(self.env)
        if cache is None:
            self.tool_dir.mkdir(parents=True)
            if scanner is not None:
                shutil.copyfile(scanner, self.tool_dir / gate.expected_scanner()[0])
        files = {f'.githooks/{name}': (REPO / '.githooks' / name).read_bytes() for name in HOOK_FILES}
        files['tools/publication_gate.py'] = gate_source if gate_source is not None else GATE.read_bytes()
        files['.gitleaks.toml'] = config if config is not None else (REPO / '.gitleaks.toml').read_bytes()
        golden, self.initial = _golden_repositories(files)
        shutil.copytree(golden / 'work', self.root, symlinks=True)
        shutil.copytree(golden / 'origin.git', self.remote, symlinks=True)
        self.git('remote', 'set-url', 'origin', str(self.remote))

    def write(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode('utf-8') if isinstance(content, str) else content)

    def run(self, *args, data=None, extra_env=None):
        env = dict(self.env, **(extra_env or {}))
        proc = subprocess.run(['git', '-C', str(self.root), *args], input=data, capture_output=True,
                              env=env, timeout=TIMEOUT)
        proc.out = (proc.stdout + proc.stderr).decode('utf-8', 'replace')
        return proc

    def git(self, *args):
        proc = self.run(*args)
        if proc.returncode != 0:
            raise AssertionError(f'git {" ".join(args)} failed: {proc.out}')
        return proc.stdout.decode('utf-8').strip()

    def head(self):
        return self.git('rev-parse', 'HEAD')

    def commit(self, message='change', extra_env=None):
        return self.run('commit', '-q', '-m', message, extra_env=extra_env)

    def commit_without_gate(self, message):
        """A commit made where the gate is not installed (e.g. another clone)."""
        self.git('-c', f'core.hooksPath={self.no_hooks}', 'commit', '-q', '-m', message)
        return self.head()

    def push(self, *refspecs, extra_env=None):
        return self.run('push', 'origin', *refspecs, extra_env=extra_env)

    def remote_ref(self, ref='refs/heads/main'):
        proc = subprocess.run(['git', '--git-dir', str(self.remote), 'rev-parse', '-q', '--verify', ref],
                              capture_output=True, env=self.env)
        return proc.stdout.decode().strip() or None

    def gate(self, *args):
        proc = subprocess.run([sys.executable, '-I', '-B', 'tools/publication_gate.py', *args],
                              cwd=self.root, capture_output=True, env=self.env, timeout=TIMEOUT)
        proc.out = (proc.stdout + proc.stderr).decode('utf-8', 'replace')
        return proc


def config_with_allowlist(entries):
    text = (REPO / '.gitleaks.toml').read_text(encoding='utf-8')
    body = ', '.join(f'{{ path = "{path}", reason = "{reason}" }}' for path, reason in entries)
    marker = 'binary_allowlist = []'
    assert text.count(marker) == 1
    return text.replace(marker, f'binary_allowlist = [{body}]').encode('utf-8')


class GateTestCase(unittest.TestCase):
    def assertNoSecretValue(self, output):
        for value in SECRETS:
            self.assertNotIn(value, output)
        self.assertNotIn(BS + PERSON, output)
        self.assertNotIn('/' + PERSON, output)

    def assertRejected(self, proc, *expected):
        self.assertNotEqual(proc.returncode, 0, proc.out)
        self.assertIn('REJECTED', proc.out)
        for text in expected:
            self.assertIn(text, proc.out)
        self.assertNoSecretValue(proc.out)

    def assertBlockedClosed(self, proc, *expected):
        self.assertNotEqual(proc.returncode, 0, proc.out)
        self.assertIn('CANNOT RUN (fail closed)', proc.out)
        for text in expected:
            self.assertIn(text, proc.out)


class WithRealScanner(GateTestCase):
    """Detection behaviour, using the pinned Gitleaks."""

    @classmethod
    def setUpClass(cls):
        cls.scanner = real_scanner()
        if cls.scanner is None:
            message = (f'pinned Gitleaks {gate.GITLEAKS_VERSION} is not installed in the per-user cache '
                       '(run `task hooks:install`)')
            if REQUIRE_SCANNER:
                raise AssertionError(message)
            raise unittest.SkipTest(message)
        cls.cache = shared_scanner_cache(cls, cls.scanner)

    def repo(self, **kwargs):
        return GateRepo(self, self.scanner, cache=self.cache, **kwargs)

    # Required case 1
    def test_1_staged_fake_credential_is_rejected(self):
        r = self.repo()
        r.write('app/settings.py', f'AWS_ACCESS_KEY_ID = "{FAKE_AWS_KEY}"\nTOKEN = "{FAKE_GITHUB_TOKEN}"\n')
        r.git('add', 'app/settings.py')
        proc = r.commit('add settings')
        self.assertRejected(proc, 'aws-access-token', 'github-pat', 'app/settings.py:1', 'app/settings.py:2')
        self.assertEqual(r.head(), r.initial)

    # Required case 2
    def test_2_staged_personal_paths_are_rejected(self):
        r = self.repo()
        variants = {
            'win-backslash.md': 'C:' + BS + 'Users' + BS + PERSON + BS + 'src' + BS + 'x',
            'win-slash.md': 'see C:/Users/' + PERSON + '/AppData/Local',
            'win-json.json': '{"path": "D:' + BS * 2 + 'Users' + BS * 2 + PERSON + BS * 2 + 'repo"}',
            'linux-home.sh': 'cd /home/' + PERSON + '/work',
            'mac-home.md': 'open /Users/' + PERSON + '/Documents',
            'wsl-mount.md': 'ls /mnt/c/Users/' + PERSON + '/Downloads',
            'msys-path.md': 'cd /c/Users/' + PERSON + '/src',
            'wsl-unc.md': BS * 2 + 'wsl$' + BS + 'Ubuntu' + BS + 'home' + BS + PERSON + BS + 'x',
        }
        for name, text in variants.items():
            r.write(f'docs/{name}', text + '\n')
        r.git('add', 'docs')
        proc = r.commit('add docs')
        self.assertRejected(proc, 'personal-windows-profile-path', 'personal-posix-home-path',
                            'personal-wsl-unc-home-path', *(f'docs/{name}:1' for name in variants))
        self.assertEqual(r.head(), r.initial)

    # Required case 3
    def test_3_ignored_credential_stays_out_and_force_added_one_is_rejected(self):
        r = self.repo()
        r.write('.gitignore', '.env\n')
        r.write('.env', f'AWS_ACCESS_KEY_ID={FAKE_AWS_KEY}\n')
        r.write('notes.md', 'Configuration lives in a local .env file.\n')
        r.git('add', '-A')
        staged = r.git('diff', '--cached', '--name-only').split()
        self.assertEqual(sorted(staged), ['.gitignore', 'notes.md'])
        proc = r.commit('add notes')
        self.assertEqual(proc.returncode, 0, proc.out)
        self.assertNotIn('.env', r.git('ls-tree', '-r', '--name-only', 'HEAD').split())
        r.git('add', '-f', '.env')
        before = r.head()
        proc = r.commit('add env')
        self.assertRejected(proc, 'credential-store-dotenv', 'aws-access-token', '.env')
        self.assertEqual(r.head(), before)

    # Required case 4
    def test_4_push_rejects_a_secret_from_an_earlier_unpushed_commit(self):
        r = self.repo()
        r.write('app/config.py', f'KEY = "{FAKE_AWS_KEY}"\n')
        r.git('add', 'app/config.py')
        leaking = r.commit_without_gate('add config')
        r.write('app/config.py', 'KEY = None\n')
        r.git('add', 'app/config.py')
        proc = r.commit('remove key')
        self.assertEqual(proc.returncode, 0, proc.out)  # the later commit itself is clean
        proc = r.push('main')
        self.assertRejected(proc, 'pre-push', 'aws-access-token', 'app/config.py:1', leaking[:12])
        self.assertEqual(r.remote_ref(), r.initial)
        # A new remote ref: every commit not reachable from a remote-tracking ref.
        proc = r.push('main:refs/heads/feature')
        self.assertRejected(proc, 'aws-access-token', leaking[:12])
        self.assertIsNone(r.remote_ref('refs/heads/feature'))

    # Required case 5
    def test_5_safe_documentation_with_generic_paths_passes(self):
        r = self.repo()
        lines = [
            'Cache: %LOCALAPPDATA%' + BS + 'ai-engineering-harness' + BS + 'tools' + BS + 'gitleaks',
            'Profile: %USERPROFILE%' + BS + '.claude, $HOME/.cache, ${HOME}/x, ~/.cache',
            'Examples: C:' + BS + 'Users' + BS + '<user>' + BS + 'AppData, C:' + BS + 'Users' + BS + 'you' + BS + 'src',
            'Shared: C:' + BS + 'Users' + BS + 'Public' + BS + 'Documents and C:/Users/<user>/x',
            'JSON: "C:' + BS * 2 + 'Users' + BS * 2 + 'you' + BS * 2 + 'repo"',
            'Linux: /home/user/project, /home/<user>/project, /home/agent/work, /Users/Shared/x',
            'Repository paths: tools/publication_gate.py, composition/lock/README.md, ./profiles/README.md',
            'Never commit .env, .claude/.credentials.json, .codex/auth.json, .mcp.json, .git-credentials,',
            '.netrc, ~/.aws/credentials, ~/.kube/config, id_ed25519 or anything under .gnupg/.',
        ]
        r.write('docs/GUIDE.md', '\n'.join(lines) + '\n')
        r.write('.gitignore', '.env\n.env.*\n!.env.example\n.mcp.json\n.claude/.credentials.json\n.codex/auth.json\n')
        r.write('.env.example', '# Copy to .env and fill in locally.\nAPI_TOKEN=\n')
        r.write('.npmrc', 'registry=https://registry.npmjs.org/\n')
        r.git('add', '-A')
        proc = r.commit('add docs')
        self.assertEqual(proc.returncode, 0, proc.out)
        self.assertIn('PASS', proc.out)
        proc = r.push('main')
        self.assertEqual(proc.returncode, 0, proc.out)
        self.assertEqual(r.remote_ref(), r.head())

    def test_credential_stores_are_rejected_by_file_path(self):
        r = self.repo()
        files = {
            '.claude/.credentials.json': ('{}', 'credential-store-claude'),
            'cfg/.codex/auth.json': ('{}', 'credential-store-codex'),
            '.mcp.json': ('{}', 'credential-store-mcp'),
            '.git-credentials': ('x', 'credential-store-git'),
            '_netrc': ('x', 'credential-store-netrc'),
            '.npmrc': ('//registry.npmjs.org/:_authToken=${NPM_TOKEN}', 'credential-store-npmrc-auth'),
            '.pypirc': ('[pypi]', 'credential-store-pypirc'),
            'backup/.aws/credentials': ('[default]', 'credential-store-cloud-cli'),
            '.kube/config': ('apiVersion: v1', 'credential-store-cloud-cli'),
            'keys/id_ed25519': ('x', 'credential-store-ssh'),
            'certs/server.pem': ('x', 'credential-store-key-file'),
            '.env.local': ('X=1', 'credential-store-dotenv'),
            '.gnupg/gpg.conf': ('x', 'credential-store-keyring'),
        }
        for path, (content, _rule) in files.items():
            r.write(path, content + '\n')
        r.git('add', '-A')
        proc = r.commit('add stores')
        self.assertRejected(proc, *{rule for _c, rule in files.values()}, *files)
        self.assertEqual(r.head(), r.initial)

    def test_unallowlisted_binary_is_refused_and_an_allowlisted_one_passes(self):
        payload = b'PK\x03\x04' + bytes(range(256)) * 4
        r = self.repo()
        r.write('assets/bundle.zip', payload)
        r.write('assets/blob.dat', b'\x00\x01\x02 opaque')
        r.git('add', 'assets')
        proc = r.commit('add binaries')
        self.assertRejected(proc, 'binary-not-allowlisted', 'assets/bundle.zip', 'assets/blob.dat')
        self.assertEqual(r.head(), r.initial)
        allowed = self.repo(config=config_with_allowlist([('assets/bundle.zip', 'Synthetic test fixture.')]))
        allowed.write('assets/bundle.zip', payload)
        allowed.git('add', 'assets')
        proc = allowed.commit('add allowlisted binary')
        self.assertEqual(proc.returncode, 0, proc.out)
        self.assertIn('allowlisted binary, content not inspected: assets/bundle.zip', proc.out)
        # An allowlisted binary is still subject to the path rules.
        keyed = self.repo(config=config_with_allowlist([('certs/client.p12', 'Synthetic test fixture.')]))
        keyed.write('certs/client.p12', b'\x30\x82\x00\x10' + bytes(32))
        keyed.git('add', 'certs')
        proc = keyed.commit('add key container')
        self.assertRejected(proc, 'credential-store-key-file', 'certs/client.p12')
        self.assertEqual(keyed.head(), keyed.initial)

    def test_allowlisted_gzip_holding_a_fake_secret_is_rejected(self):
        r = self.repo(config=config_with_allowlist([('data/report.json.gz', 'Synthetic test fixture.')]))
        buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0) as handle:
            handle.write(f'{{"note": "ok",\n "token": "{FAKE_GITHUB_TOKEN}"}}\n'.encode())
        r.write('data/report.json.gz', buffer.getvalue())
        r.git('add', 'data')
        proc = r.commit('add report')
        self.assertRejected(proc, 'github-pat', 'data/report.json.gz (decompressed):2')
        self.assertEqual(r.head(), r.initial)

    def test_push_rejects_a_personal_path_in_a_commit_message(self):
        r = self.repo()
        r.write('README.md', 'hello\n')
        r.git('add', 'README.md')
        r.commit_without_gate('copied from C:' + BS + 'Users' + BS + PERSON + BS + 'notes')
        proc = r.push('main')
        self.assertRejected(proc, 'personal-windows-profile-path', 'commit message')
        self.assertEqual(r.remote_ref(), r.initial)

    def test_history_mode_reports_findings_without_values(self):
        r = self.repo()
        r.write('old.py', f'TOKEN = "{FAKE_GITHUB_TOKEN}"\n')
        r.git('add', 'old.py')
        leaking = r.commit_without_gate('old')
        r.git('rm', '-q', 'old.py')
        r.commit_without_gate('remove')
        proc = r.gate('history')
        self.assertEqual(proc.returncode, 1, proc.out)
        self.assertRejected(proc, 'github-pat', 'old.py:1', leaking[:12])

    def test_commit_without_its_configuration_is_blocked(self):
        r = self.repo()
        r.git('rm', '-q', '--cached', '.gitleaks.toml')
        proc = r.commit('drop config')
        self.assertBlockedClosed(proc, 'not in the index')
        self.assertEqual(r.head(), r.initial)

    # Gitleaks 8.30.1 reads a file through a 100,000-byte buffer and extends each
    # read to the next blank line, by at most 25,000 bytes; its bufio reader then
    # refills 4,096 bytes at a time. In text with no blank line, fragments are cut
    # at byte 125,000 and every 28,672 bytes after (bytes 125,000 + 4,096 * N in
    # general), and a match across a cut is never reported.

    def test_8_trailing_marker_in_the_former_cut_window_passes(self):
        # The 2,119,697-byte length at which a plan HTML once failed closed. One
        # blank line at byte 114,000 puts the cuts at 125,000 + 4,096 * N, and
        # N = 487 (byte 2,119,752) falls inside the marker line that the gate
        # appends at byte 2,119,698. The unwindowed gate reported "did not
        # inspect"; windowed, every marker is read and the clean file passes.
        r = self.repo()
        line = b'filler text without blank lines\n'

        def filler(n):
            return (line * (n // len(line) + 1))[:n]

        body = filler(114_000) + b'\n\n' + filler(2_119_697 - 114_002)
        body = body[:-1] + b'x'
        self.assertEqual(len(body), 2_119_697)
        self.assertEqual(body.count(b'\n\n'), 1)
        r.write('docs/long.txt', body)
        r.git('add', 'docs/long.txt')
        proc = r.commit('add a long file')
        self.assertEqual(proc.returncode, 0, proc.out)
        self.assertIn('PASS', proc.out)
        proc = r.push('main')
        self.assertEqual(proc.returncode, 0, proc.out)

    def test_9_secret_across_a_scanner_fragment_cut_is_rejected(self):
        # With no blank line, Gitleaks cuts the first fragment at byte 125,000.
        # The fake token straddles that cut (unwindowed, the gate passed it); a
        # second one lies far beyond it. Both are reported at their real lines.
        r = self.repo()
        line = b'filler text without blank lines\n'
        token = FAKE_GITHUB_TOKEN.encode()
        first = 125_000 - 20
        head = (line * (first // len(line) + 1))[:first - 1] + b'\n'
        middle = line * 4000
        body = head + token + b'\n' + middle + token + b'\n' + line * 100
        self.assertEqual(body.index(token), first)
        self.assertNotIn(b'\n\n', body)
        lines = (head.count(b'\n') + 1, head.count(b'\n') + 2 + middle.count(b'\n'))
        r.write('data/big.txt', body)
        r.git('add', 'data/big.txt')
        proc = r.commit('add data')
        self.assertRejected(proc, 'github-pat', *(f'data/big.txt:{n}' for n in lines))
        self.assertIn('2 finding(s)', proc.out)
        self.assertEqual(r.head(), r.initial)


class ScanWindows(unittest.TestCase):
    """The window split itself; no scanner needed."""
    category = 'unit'

    def check(self, content):
        windows = gate.scan_windows(content)
        self.assertEqual(windows[0][0], 0)
        self.assertEqual(windows[-1][0] + len(windows[-1][1]), len(content))
        for (start, part), (nxt, _) in zip(windows, windows[1:]):
            self.assertEqual(part, content[start:start + len(part)])
            self.assertLessEqual(len(part), gate.SCAN_WINDOW)
            # consecutive windows overlap by at least SCAN_OVERLAP and always advance
            self.assertGreaterEqual(start + len(part) - nxt, gate.SCAN_OVERLAP)
            self.assertGreaterEqual(nxt - start, gate.SCAN_WINDOW - 2 * gate.SCAN_OVERLAP)
        self.assertLessEqual(len(windows[-1][1]), gate.SCAN_WINDOW)
        return windows

    def test_small_content_is_one_window(self):
        for content in (b'', b'x', b'a\n' * (gate.SCAN_WINDOW // 2)):
            self.assertEqual(gate.scan_windows(content), [(0, content)])

    def test_window_and_marker_fit_one_scanner_read(self):
        marker = len(gate.CANARY_PREFIX) + 32
        self.assertLessEqual(gate.SCAN_WINDOW + 1 + marker + 1, gate.SCANNER_READ_BYTES)

    def test_large_content_is_covered_with_overlap(self):
        rng = random.Random(7)
        cases = [
            b'y' * 2_119_697,                                    # one long line
            b''.join(b'x' * rng.randrange(1, 300) + b'\n' for _ in range(20_000)),
            b'z' * (gate.SCAN_WINDOW + 1),
        ]
        for content in cases:
            with self.subTest(size=len(content)):
                windows = self.check(content)
                self.assertGreater(len(windows), 1)

    def test_windows_start_at_a_line_when_one_is_near(self):
        content = (b'0123456789abcde\n' * 40_000)
        for start, _ in self.check(content)[1:]:
            self.assertEqual(content[start - 1:start], b'\n')

    def test_every_short_match_lies_whole_in_one_window(self):
        content = b'q' * 1_000_003
        windows = self.check(content)
        span = gate.SCAN_OVERLAP
        for pos in range(0, len(content) - span, 997):
            self.assertTrue(any(s <= pos and pos + span <= s + len(p) for s, p in windows), pos)


STUBS = {
    'fails': 'import sys\nsys.stderr.write("stub scanner failure\\n")\nsys.exit(3)\n',
    'silent-success': 'import sys\nsys.exit(0)\n',
    'no-marker': ('import sys\nargs = sys.argv[1:]\n'
                  'open(args[args.index("--report-path") + 1], "w").write("[]")\nsys.exit(42)\n'),
    'empty-success': ('import sys\nargs = sys.argv[1:]\n'
                      'open(args[args.index("--report-path") + 1], "w").write("[]")\nsys.exit(0)\n'),
    'hangs': 'import time\ntime.sleep(120)\n',
}


def stub_gate_source(stub_name, stub_sha256):
    """A copy of the gate whose pinned scanner is a Python stub."""
    source = GATE.read_text(encoding='utf-8')
    marker = "\nif __name__ == '__main__':"
    assert source.count(marker) == 1
    override = ('\n# Test override: the pinned scanner is a stub run by this interpreter.\n'
                f'SCANNER_PREFIX = ({sys.executable!r}, "-I")\n\n\n'
                f'def expected_scanner():\n    return {stub_name!r}, {stub_sha256!r}\n\n')
    return source.replace(marker, override + marker).encode('utf-8')


class FailsClosed(GateTestCase):
    """Required case 6: no usable scanner blocks both commit and push. No real scanner needed."""

    def check_blocks_commit_and_push(self, r, *expected, extra_env=None):
        r.write('file.txt', 'harmless\n')
        r.git('add', 'file.txt')
        proc = r.commit('blocked', extra_env=extra_env)
        self.assertBlockedClosed(proc, *expected)
        self.assertEqual(r.head(), r.initial)
        r.commit_without_gate('made elsewhere')
        proc = r.push('main', extra_env=extra_env)
        self.assertBlockedClosed(proc, *expected)
        self.assertEqual(r.remote_ref(), r.initial)

    def stub_repo(self, behaviour):
        name = 'gitleaks-stub.py'
        source = STUBS[behaviour].encode()
        r = GateRepo(self, gate_source=stub_gate_source(name, gate.sha256_bytes(source)))
        (r.tool_dir / name).write_bytes(source)
        return r

    def test_6a_scanner_not_installed(self):
        self.check_blocks_commit_and_push(GateRepo(self), 'is not installed')

    def test_6b_scanner_with_wrong_hash(self):
        r = GateRepo(self)
        (r.tool_dir / gate.expected_scanner()[0]).write_bytes(b'not the pinned scanner')
        self.check_blocks_commit_and_push(r, 'does not match the pinned')

    def test_6c_scanner_exits_nonzero(self):
        self.check_blocks_commit_and_push(self.stub_repo('fails'), 'scanner failed (exit 3)')

    def test_6d_scanner_succeeds_without_output(self):
        self.check_blocks_commit_and_push(self.stub_repo('silent-success'), 'success without writing its report')

    def test_6g_scanner_succeeds_with_an_empty_report(self):
        self.check_blocks_commit_and_push(self.stub_repo('empty-success'), 'did not inspect')

    def test_6e_scanner_report_lacks_the_per_run_marker(self):
        self.check_blocks_commit_and_push(self.stub_repo('no-marker'), 'did not inspect')

    def test_6f_scanner_times_out(self):
        self.check_blocks_commit_and_push(self.stub_repo('hangs'), 'timed out',
                                          extra_env={'AIEH_GATE_TIMEOUT': '3'})


class ExistingCommands(unittest.TestCase):
    """Required case 7: the repository's existing commands still work in this checkout."""

    def run_here(self, *args, env=None):
        proc = subprocess.run([sys.executable, *args], cwd=REPO, capture_output=True,
                              env=env or clean_environ(), timeout=TIMEOUT)
        out = (proc.stdout + proc.stderr).decode('utf-8', 'replace')
        self.assertEqual(proc.returncode, 0, out)
        return out

    def test_7_verify_seed_and_check_profile(self):
        if NESTED:
            self.skipTest('already running inside the whole-suite run')
        self.assertIn('PASS', self.run_here('-I', 'tools/verify_seed.py'))
        self.assertIn('PASS', self.run_here('-I', 'tools/verify_seed.py', '--baseline', 'seed'))
        self.run_here('-I', '-B', 'tools/check_profile.py')

    def test_7_the_whole_tool_suite(self):
        # The nested whole-suite rerun (about two minutes) runs in the gate tier only: task
        # hooks:verify sets AIEH_GATE_REQUIRE_SCANNER=1, and task qualify runs hooks:verify at a
        # release (plan leaf F-09.2). Every other run reports it skipped, with this reason.
        if NESTED:
            self.skipTest('already running inside the whole-suite run')
        if not REQUIRE_SCANNER:
            self.skipTest('the nested whole-suite rerun runs under AIEH_GATE_REQUIRE_SCANNER=1 '
                          '(task hooks:verify, and task qualify at a release)')
        env = dict(clean_environ(), AIEH_GATE_NESTED_SUITE='1')
        out = self.run_here('-I', '-B', '-m', 'unittest', 'discover', '-s', 'tools/tests', env=env)
        self.assertIn('OK', out)


if __name__ == '__main__':
    unittest.main()
