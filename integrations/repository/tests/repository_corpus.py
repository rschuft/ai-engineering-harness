"""The repository-access contract corpus (plan leaf F-10.2): git-built golden repositories and
git's recorded answers over them.

The corpus is the Dulwich probe's (``evidence/dulwich-git-inventory.md`` section 2.2), built by
git with a fixed identity and fixed dates under one root whose name holds a space and a non-ASCII
character (``a b ü``):

- ``repo one``: loose objects; paths with spaces and non-ASCII; an ``eol=crlf`` file, a binary
  file, a CRLF blob, an executable, an ``export-ignore`` directory; annotated, lightweight,
  nested, tree and blob tags; a merge; remote-tracking and top-level references; reflogs;
  FETCH_HEAD and ORIG_HEAD; two blobs sharing a 4-digit prefix and a blob sharing one with a
  commit; plumbing-built commits with symbolic links, a gitlink and unsafe names; and a work
  tree with staged, unstaged, deleted, untracked, ignored and nested-repository changes;
- ``packed copy``: the same history after ``repack -a -d -k`` and ``pack-refs --all``;
- ``bare.git``, a mirror; ``linked tree``, a linked worktree (relative paths); ``separate work``
  with ``separate.git``; ``sha256 repo``; ``long.git``, whose tree holds a 295-character path;
- ``id mismatch``, ``corrupt zlib`` and ``corrupt pack``: one object each made unreadable;
- ``conflicted``: a failed merge (stages 1 to 3, MERGE_HEAD); ``not a repo``.

``fixtures/repository-corpus-tree.json.gz`` holds the built tree byte for byte: a gzipped JSON
list of every directory and file, a file's bytes as text where they are plain UTF-8 text and as
base64 otherwise (git's object files, packs and indexes), so that the publication-safety gate can
inspect all of it (it refuses an archive it cannot read as text). ``fixtures/repository-corpus.json``
holds git's answers over the tree (``record``). The tests extract the tree once per process
(``corpus``) and need no git; the git-oracle tests ask git again (``Oracle``) where git is on
PATH. Every git launch here belongs to the test fixtures.

Re-record (needs git; writes both fixture files):

    python -I -B integrations/repository/tests/repository_corpus.py --record
"""
import argparse
import atexit
import base64
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
MODULE_DIR = HERE.parent
FIXTURES = HERE / 'fixtures'
ARCHIVE = FIXTURES / 'repository-corpus-tree.json.gz'
EXPECTED = FIXTURES / 'repository-corpus.json'
ROOT_NAME = 'a b ü'
SCHEMA = 'aieh-repository-corpus/v1'
TREE_SCHEMA = 'aieh-repository-corpus-tree/v1'
WAIT_CEILING_S = 120
_NOT_TEXT = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

GIT_ENV = {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_AUTHOR_NAME': 'Fixture',
           'GIT_AUTHOR_EMAIL': 'fixture@example.invalid', 'GIT_COMMITTER_NAME': 'Fixture',
           'GIT_COMMITTER_EMAIL': 'fixture@example.invalid', 'GIT_TERMINAL_PROMPT': '0'}

UNI = 'docs/ünïcode é.md'
SPACED = 'openspec/changes/qual 02 spaced/design.md'
NON_ASCII_DIR = 'openspec/changes/ünï çhange'
LONG_DIRS = ('d' * 100, 'e' * 100)
LONG_NAME = 'g' * 72 + '.txt'
LONG_PATH = f'openspec/changes/{LONG_DIRS[0]}/{LONG_DIRS[1]}/{LONG_NAME}'

sys.path.insert(0, str(MODULE_DIR))


def rmtree(path):
    """Remove a tree holding git's read-only object files (Windows refuses them otherwise)."""
    def retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    shutil.rmtree(path, onexc=retry)


# ---------------------------------------------------------------------------- the extracted corpus

_ROOT = None
_EXPECTED = None


def corpus():
    """The corpus root (``<temp>/a b ü``), extracted from the committed tree once per process
    into a temporary directory removed at exit. Read it only: copy before changing anything."""
    global _ROOT
    if _ROOT is None:
        tmp = Path(tempfile.mkdtemp(prefix='aieh-repo-corpus-'))
        atexit.register(rmtree, tmp)
        extract_tree(ARCHIVE, tmp)
        _ROOT = tmp / ROOT_NAME
    return _ROOT


def ceilings():
    """The ceiling directories of every test that opens a repository of the corpus: its temporary
    root, so that no discovery examines that root or anything above it (git's
    GIT_CEILING_DIRECTORIES; the module's ``ceilings``)."""
    return [str(corpus().parent)]


def extract_tree(archive, destination):
    """Write the tree ARCHIVE holds below DESTINATION: directories, then files with their bytes,
    read-only where git wrote them read-only. Every path must be a plain relative path."""
    data = json.loads(gzip.decompress(Path(archive).read_bytes()).decode('utf-8'))
    if data.get('schema') != TREE_SCHEMA:
        raise ValueError(f'{archive}: not a {TREE_SCHEMA} tree')
    destination = Path(destination)
    for entry in data['entries']:
        parts = PurePosixPath(entry['path']).parts
        if not parts or entry['path'].startswith('/') or any(p in ('', '.', '..') for p in parts):
            raise ValueError(f'{archive}: unsafe path {entry["path"]!r}')
        target = destination.joinpath(*parts)
        if entry['type'] == 'dir':
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = entry['text'].encode('utf-8') if 'text' in entry else base64.b64decode(entry['base64'])
        target.write_bytes(content)
        if entry.get('read_only'):
            os.chmod(target, stat.S_IREAD)


def expected():
    """git's recorded answers (``fixtures/repository-corpus.json``)."""
    global _EXPECTED
    if _EXPECTED is None:
        _EXPECTED = json.loads(EXPECTED.read_text(encoding='utf-8'))
    return _EXPECTED


def archive_digest():
    return hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------- git

_BUILD_CEILING = None


def git(repo, *args, env=None, input=None, check=True, date=None):
    """Run git in REPO with the fixture environment; stdout bytes (CompletedProcess when not CHECK).
    While the corpus is built, its build directory is git's ceiling: no git discovery looks above it."""
    extra = dict(env or {})
    if _BUILD_CEILING is not None:
        extra.setdefault('GIT_CEILING_DIRECTORIES', _BUILD_CEILING)
    if date is not None:
        extra.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    result = subprocess.run(['git', '-c', 'core.longpaths=true', '-c', 'core.autocrlf=false', '-C', str(repo),
                             *args], input=input, capture_output=True, timeout=WAIT_CEILING_S,
                            stdin=None if input is not None else subprocess.DEVNULL,
                            env={**os.environ, **GIT_ENV, **extra})
    if not check:
        return result
    if result.returncode != 0:
        raise AssertionError(f'git {args} in {repo}: exit {result.returncode}: '
                             f'{result.stderr.decode("utf-8", "replace")}')
    return result.stdout


def out(repo, *args, **kwargs):
    return git(repo, *args, **kwargs).decode('utf-8').strip()


def date(n):
    return f'2026-11-01T{n:02d}:00:00Z'


def write(repo, files):
    for name, data in files.items():
        path = Path(repo, *name.split('/'))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))


def commit_all(repo, message, n):
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', message, date=date(n))
    return out(repo, 'rev-parse', 'HEAD')


def blob_id(data, algorithm=hashlib.sha1):
    return algorithm(b'blob %d\0' % len(data) + data).hexdigest()


def loose_path(repo_gitdir, oid):
    return Path(repo_gitdir, 'objects', oid[:2], oid[2:])


# ---------------------------------------------------------------------------- building

def build(root):
    """Build the corpus under ROOT / ROOT_NAME with git; the facts the expectations need."""
    global _BUILD_CEILING
    base = Path(root) / ROOT_NAME
    base.mkdir(parents=True)
    _BUILD_CEILING = str(Path(root).resolve())
    facts = {}
    main = base / 'repo one'
    main.mkdir()
    git(main, 'init', '-q', '-b', 'main')
    write(main, {
        'README.md': 'readme\n',
        UNI: 'unicode ü\n',
        'openspec/config.yaml': 'schema: spec-driven\n',
        SPACED: '# design\n',
        'openspec/changes/plain/x.md': 'plain\n',
        f'{NON_ASCII_DIR}/design.md': '# désign\n',
        f'{NON_ASCII_DIR}/spécs/s péc.md': 'spec\n',
        'data/binary.bin': b'\x00\x01\r\n\x02\x03\xff\r\n',
        '.gitattributes': 'eol/*.txt text eol=crlf\nignored-export export-ignore\n*.bin binary\n',
        '.gitignore': 'build/\n*.log\n',
        'eol/crlf.txt': 'line one\nline two\n',
        'ignored-export/hidden.txt': 'hidden from git archive\n',
        'text/crlf-in-blob.txt': b'a\r\nb\r\n',
        'exec.sh': '#!/bin/sh\necho hi\n',
    })
    git(main, 'add', '-A')
    git(main, 'update-index', '--chmod=+x', 'exec.sh')
    git(main, 'commit', '-q', '-m', 'A', date=date(0))
    facts['A'] = out(main, 'rev-parse', 'HEAD')
    git(main, 'tag', 'lw')
    git(main, 'checkout', '-q', '-b', 'side')
    write(main, {'docs/side.md': 'side\n'})
    facts['B'] = commit_all(main, 'B', 1)
    git(main, 'checkout', '-q', 'main')
    write(main, {'README.md': 'readme\nsecond line\n'})
    facts['C'] = commit_all(main, 'C', 2)
    git(main, 'tag', '-a', 'v1', '-m', 'v1', date=date(2))
    git(main, 'merge', '-q', '--no-ff', '-m', 'merge', 'side', date=date(3))
    facts['D'] = out(main, 'rev-parse', 'HEAD')
    write(main, {'openspec/changes/plain/x.md': 'plain, changed\n'})
    facts['E'] = commit_all(main, 'E', 4)
    git(main, 'tag', '-a', 'v2', '-m', 'v2', 'v1', date=date(4))
    facts['tree'] = out(main, 'rev-parse', 'HEAD^{tree}')
    facts['readme_blob'] = out(main, 'rev-parse', 'HEAD:README.md')
    facts['v1_tag'] = out(main, 'rev-parse', 'v1')
    git(main, 'tag', '-a', 'treetag', '-m', 'treetag', facts['tree'], date=date(4))
    git(main, 'tag', '-a', 'blobtag', '-m', 'blobtag', facts['readme_blob'], date=date(4))
    git(main, 'branch', 'dup', facts['A'])
    git(main, 'tag', 'dup', facts['B'])
    git(main, 'update-ref', 'refs/top', facts['C'])
    git(main, 'update-ref', '-m', 'remote', 'refs/remotes/origin/main', facts['B'])
    git(main, 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
    git(main, 'branch', 'ünï', facts['A'])
    git(main, 'branch', 'cafe', facts['A'])
    git(main, 'fetch', '-q', '.', 'side')
    # Two blobs sharing a 4-digit prefix, and a blob sharing commit E's 4-digit prefix.
    facts['amb4'] = _write_colliding(main, lambda oid, seen: oid[:4] in seen, 'ambiguous')
    facts['cb4'] = _write_colliding(main, lambda oid, seen: oid[:4] == facts['E'][:4], 'collide')
    # The packed copy and the bare mirror, before anything else changes the repository.
    packed = base / 'packed copy'
    shutil.copytree(main, packed)
    git(packed, 'repack', '-a', '-d', '-k', '-q')
    git(packed, 'prune-packed')
    git(packed, 'pack-refs', '--all')
    loose = [p for p in (packed / '.git' / 'objects').iterdir() if len(p.name) == 2 and any(p.iterdir())]
    assert not loose, f'loose objects left in the packed copy: {loose}'
    bare = base / 'bare.git'
    git(base, 'init', '-q', '--bare', '-b', 'main', str(bare))
    git(main, 'push', '-q', '--mirror', str(bare))
    _plumbing_commits(main, facts)
    linked = base / 'linked tree'
    git(main, 'worktree', 'add', '-q', '--relative-paths', '-b', 'wtb', '../linked tree', facts['C'], date=date(5))
    write(linked, {'linked.txt': 'linked\n'})
    facts['F'] = commit_all(linked, 'F', 6)
    _work_tree_changes(main)
    _separate(base, facts)
    _sha256(base, facts)
    _long(base, facts)
    _damaged(base, facts)
    _conflicted(base, facts)
    _replaced(base, facts)
    _ignore_cases(base)
    _attribute_cases(base)
    _line_endings(base)
    write(base / 'not a repo', {'file.txt': 'not a repository\n'})
    (base / 'xdg empty').mkdir()
    return facts


def _write_colliding(repo, wanted, label):
    """Write blobs until one's id satisfies WANTED(oid, ids so far); return its 4-digit prefix."""
    seen = {}
    for number in range(1_000_000):
        data = f'{label} {number}\n'.encode()
        oid = blob_id(data)
        if wanted(oid, seen):
            if label == 'ambiguous':
                git(repo, 'hash-object', '-w', '--stdin', input=seen[oid[:4]])
            git(repo, 'hash-object', '-w', '--stdin', input=data)
            return oid[:4]
        seen[oid[:4]] = data
    raise AssertionError(f'no {label} blob found')


def _mktree(repo, entries):
    listing = ''.join(f'{mode} {kind} {oid}\t{name}\n' for mode, kind, oid, name in entries)
    return out(repo, 'mktree', input=listing.encode('utf-8'))


def _hash(repo, data):
    return out(repo, 'hash-object', '-w', '--stdin', input=data)


def _plumbing_commits(main, facts):
    """Commits only plumbing can make here: symbolic links, a gitlink, unsafe names."""
    readme = facts['readme_blob']
    docs = out(main, 'rev-parse', f'{facts["E"]}:docs')
    file_blob = _hash(main, b'a file\n')

    def links_tree(extra):
        entries = [('120000', 'blob', _hash(main, b'../README.md'), 'inside'),
                   ('120000', 'blob', _hash(main, b'../docs'), 'dir'),
                   ('160000', 'commit', facts['A'], 'sub'),
                   ('100644', 'blob', file_blob, 'file.txt')] + extra
        links = _mktree(main, sorted(entries, key=lambda e: e[3] + ('/' if e[1] == 'tree' else '')))
        return _mktree(main, [('100644', 'blob', readme, 'README.md'), ('040000', 'tree', docs, 'docs'),
                              ('040000', 'tree', links, 'links')])

    def commit_tree(tree, name, n):
        oid = out(main, 'commit-tree', tree, '-m', name, date=date(n))
        git(main, 'update-ref', f'refs/heads/{name}', oid)
        return oid

    facts['links_ok'] = commit_tree(links_tree([]), 'links-ok', 7)
    facts['links_escape'] = commit_tree(
        links_tree([('120000', 'blob', _hash(main, b'../../escape'), 'outside')]), 'links-escape', 8)
    # p/q/x -> ../.. stays inside (the root); p/up -> q/x/../.. climbs out of the link p/q/x.
    q = _mktree(main, [('120000', 'blob', _hash(main, b'../..'), 'x')])
    p = _mktree(main, [('040000', 'tree', q, 'q'), ('120000', 'blob', _hash(main, b'q/x/../..'), 'up')])
    facts['links_climb'] = commit_tree(_mktree(main, [('040000', 'tree', p, 'p')]), 'links-climb', 9)
    unsafe = _mktree(main, [('100644', 'blob', file_blob, '.GIT')])
    facts['unsafe'] = commit_tree(_mktree(main, [('040000', 'tree', unsafe, 'dir')]), 'unsafe-name', 10)


def _work_tree_changes(main):
    write(main, {'README.md': 'readme\nsecond line\nworktree edit\n', 'staged new.txt': 'staged\n'})
    git(main, 'add', 'staged new.txt')
    write(main, {UNI: 'staged ü\n'})
    git(main, 'add', UNI)
    write(main, {UNI: 'unstaged ü\n'})
    (main / 'openspec' / 'config.yaml').unlink()
    git(main, 'rm', '-q', '--cached', 'data/binary.bin')
    (main / 'eol' / 'crlf.txt').unlink()
    git(main, 'checkout', '--', 'eol/crlf.txt')
    write(main, {'untracked file.txt': 'u\n', 'newdir/a.txt': 'a\n', 'newdir/sub/b.txt': 'b\n',
                 'only-ignored/x.log': 'log\n', 'build/out.o': 'o\n', 'notes.tmp': 't\n',
                 'docs/new ü.md': 'new\n'})
    (main / 'emptydir' / 'inner').mkdir(parents=True)
    with open(main / '.git' / 'info' / 'exclude', 'a', encoding='utf-8') as handle:
        handle.write('*.tmp\n')
    nested = main / 'nested repo'
    nested.mkdir()
    git(nested, 'init', '-q', '-b', 'main')
    write(nested, {'n.txt': 'nested\n'})
    commit_all(nested, 'nested', 11)


def _separate(base, facts):
    work, gitdir = base / 'separate work', base / 'separate.git'
    git(base, 'init', '-q', '-b', 'main', '--separate-git-dir', str(gitdir), str(work))
    with open(work / '.git', 'r+b') as handle:  # git marks it hidden: a create-mode open is refused
        handle.truncate(0)
        handle.write(b'gitdir: ../separate.git\n')
    config = (gitdir / 'config').read_text(encoding='utf-8')
    assert 'worktree' not in config, config
    write(work, {'sep.txt': 'separate\n', 'dir/inner.txt': 'inner\n'})
    facts['S'] = commit_all(work, 'separate', 12)


def _sha256(base, facts):
    repo = base / 'sha256 repo'
    git(base, 'init', '-q', '-b', 'main', '--object-format=sha256', str(repo))
    write(repo, {'README.md': 'sha256\n', UNI: 'unicode ü\n'})
    facts['H1'] = commit_all(repo, 'H1', 13)
    git(repo, 'checkout', '-q', '-b', 'side')
    write(repo, {'side.txt': 'side\n'})
    facts['H2'] = commit_all(repo, 'H2', 14)
    git(repo, 'checkout', '-q', 'main')
    write(repo, {'README.md': 'sha256\nsecond\n'})
    facts['H3'] = commit_all(repo, 'H3', 15)
    git(repo, 'tag', '-a', 's1', '-m', 's1', date=date(15))
    git(repo, 'merge', '-q', '--no-ff', '-m', 'merge', 'side', date=date(16))
    facts['H4'] = out(repo, 'rev-parse', 'HEAD')


def _long(base, facts):
    repo = base / 'long.git'
    git(base, 'init', '-q', '--bare', '-b', 'main', str(repo))
    leaf = _mktree(repo, [('100644', 'blob', _hash(repo, b'long path\n'), LONG_NAME)])
    inner = _mktree(repo, [('040000', 'tree', leaf, LONG_DIRS[1])])
    outer = _mktree(repo, [('040000', 'tree', inner, LONG_DIRS[0])])
    changes = _mktree(repo, [('040000', 'tree', outer, 'changes')])
    root = _mktree(repo, [('100644', 'blob', _hash(repo, b'long\n'), 'README.md'),
                          ('040000', 'tree', changes, 'openspec')])
    facts['L'] = out(repo, 'commit-tree', root, '-m', 'long', date=date(17))
    git(repo, 'update-ref', 'refs/heads/main', facts['L'])
    assert len(LONG_PATH) == 295, len(LONG_PATH)


def _small(path, n):
    path.mkdir()
    git(path, 'init', '-q', '-b', 'main')
    write(path, {'README.md': 'hello\n', 'other.txt': 'other\n', 'dir/more.txt': 'more\n'})
    commit_all(path, 'small', n)
    return out(path, 'rev-parse', 'HEAD:README.md'), out(path, 'rev-parse', 'HEAD:other.txt')


def _damaged(base, facts):
    # id mismatch: README's loose object file holds other.txt's object.
    repo = base / 'id mismatch'
    readme, other = _small(repo, 18)
    target = loose_path(repo / '.git', readme)
    os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
    target.write_bytes(loose_path(repo / '.git', other).read_bytes())
    os.chmod(target, stat.S_IREAD)
    facts['mismatch'] = readme
    # corrupt zlib: README's loose object file with its deflate stream damaged.
    repo = base / 'corrupt zlib'
    readme, _ = _small(repo, 19)
    target = loose_path(repo / '.git', readme)
    data = bytearray(target.read_bytes())
    for i in range(2, 6):
        data[i] ^= 0xff
    os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
    target.write_bytes(bytes(data))
    os.chmod(target, stat.S_IREAD)
    assert git(repo, 'cat-file', 'blob', readme, check=False).returncode != 0, 'the zlib damage is readable'
    facts['zlib'] = readme
    # corrupt pack: one byte inside README's deflate data in the only pack.
    repo = base / 'corrupt pack'
    readme, _ = _small(repo, 20)
    git(repo, 'repack', '-a', '-d', '-q')
    git(repo, 'prune-packed')
    pack_dir = repo / '.git' / 'objects' / 'pack'
    idx = next(pack_dir.glob('*.idx'))
    pack = idx.with_suffix('.pack')
    offsets = {}
    for line in out(repo, 'show-index', input=idx.read_bytes()).splitlines():
        offset, oid = line.split()[:2]
        offsets[oid] = int(offset)
    data = bytearray(pack.read_bytes())
    data[offsets[readme] + 4] ^= 0xff
    os.chmod(pack, stat.S_IWRITE | stat.S_IREAD)
    pack.write_bytes(bytes(data))
    os.chmod(pack, stat.S_IREAD)
    assert git(repo, 'cat-file', 'blob', readme, check=False).returncode != 0, 'the pack damage is readable'
    facts['pack'] = readme


def _replaced(base, facts):
    """``replace loose``: R3 replaced by R1 with ``git replace`` (git then reads R1's content
    for R3); ``replace packed``: the same after ``pack-refs --all``; ``replace disabled``: the
    same with ``core.useReplaceRefs=false`` (git reads R3 unreplaced)."""
    repo = base / 'replace loose'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    write(repo, {'f.txt': 'one\n'})
    facts['R1'] = commit_all(repo, 'R1', 25)
    write(repo, {'f.txt': 'two\n'})
    facts['R2'] = commit_all(repo, 'R2', 26)
    write(repo, {'f.txt': 'three\n'})
    facts['R3'] = commit_all(repo, 'R3', 27)
    git(repo, 'replace', facts['R3'], facts['R1'])
    packed = base / 'replace packed'
    shutil.copytree(repo, packed)
    git(packed, 'pack-refs', '--all')
    assert not (packed / '.git' / 'refs' / 'replace' / facts['R3']).exists()
    disabled = base / 'replace disabled'
    shutil.copytree(repo, disabled)
    git(disabled, 'config', 'core.useReplaceRefs', 'false')


def _conflicted(base, facts):
    repo = base / 'conflicted'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    write(repo, {'conflict.txt': 'base\n', 'gone.txt': 'gone\n'})
    commit_all(repo, 'base', 21)
    git(repo, 'checkout', '-q', '-b', 'other')
    write(repo, {'conflict.txt': 'theirs\n', 'both.txt': 'theirs both\n'})
    (repo / 'gone.txt').unlink()
    commit_all(repo, 'other', 22)
    git(repo, 'checkout', '-q', 'main')
    write(repo, {'conflict.txt': 'ours\n', 'gone.txt': 'gone, changed\n', 'both.txt': 'ours both\n'})
    commit_all(repo, 'ours', 23)
    result = git(repo, 'merge', '-q', 'other', check=False, date=date(24))
    assert result.returncode != 0, 'the merge did not conflict'


# ---------------------------------------------------------------------------- F-10.4 cases
# Each case is its own repository, answered as `cases` (listings and status) apart from the
# F-10.2 `repos`, so that the F-10.2 answers and test ids stay as they were.

CRLF = b'one\r\ntwo\r\n'

# name: (.gitignore text or None, untracked files, {other file: text appended}, tracked files)
IGNORE_CASES = {
    'ignore dir star': ('logs/*\n!logs/keep/\n', ['logs/x', 'logs/keep/y'], {}, []),
    'ignore dir star no slash': ('logs/*\n!logs/keep\n', ['logs/x', 'logs/keep/y'], {}, []),
    # gitignore(5), EXAMPLES: exclude everything except the directory foo/bar.
    'ignore doc example': ('/*\n!/foo\n/foo/*\n!/foo/bar\n', ['a', 'foo/x', 'foo/bar/y'], {}, []),
    'ignore dir then file': ('logs/\n!logs/y\n', ['logs/y', 'z'], {}, []),
    'ignore double star': ('**/gen/*\n!**/gen/keep/\n', ['a/gen/x', 'a/gen/keep/y', 'gen/keep/z'], {}, []),
    'ignore nested': ('out/*\n', ['out/x', 'out/keep/y'], {'out/.gitignore': '!keep/\n'}, []),
    'ignore info exclude': (None, ['v/x', 'v/k/y'], {'.git/info/exclude': 'v/*\n!v/k/\n'}, []),
    # gitignore(5): the info/exclude and Documentation/.gitignore example, and the pattern-format
    # examples (doc/frotz/, frotz/, /*.c, abc/**, a/**/b, hello.*, \!, \#).
    'ignore gitignore examples': (
        'doc/frotz/\nfrotz/\n/*.c\nabc/**\na/**/b\nhello.*\n\\!important!.txt\n\\#hash\n',
        ['Documentation/foo.html', 'Documentation/gitignore.html', 'file.o', 'lib.a', 'src/internal.o',
         'doc/frotz/x', 'a/doc/frotz/y', 'x/frotz/z', 'frotz', 'cat-file.c', 'mozilla-sha1/sha1.c', 'abc/x',
         'abc/d/e', 'a/b', 'a/x/b', 'a/x/y/b', 'a/bb', 'hello.txt', 'sub/hello.c', 'hello', '!important!.txt',
         '#hash', 'plain.txt'],
        {'.git/info/exclude': '*.[oa]\n', 'Documentation/.gitignore': '*.html\n!foo.html\n'}, []),
    # The levels: core.excludesFile (a path relative to the work tree), info/exclude above it,
    # each .gitignore above that.
    'ignore levels': ('!lvl2\n', ['a.ex', 'lvl', 'lvl2', 'only-info', 'plain.txt', 'd/lvl'],
                      {'.git/extra excludes': '*.ex\nlvl\nlvl2\n', '.git/info/exclude': '!lvl\nonly-info\n'}, []),
    # The probe corpus: negation, directory patterns, **, nested .gitignore, info/exclude,
    # a nested repository and tracked files under ignore rules.
    'ignore corpus': (
        '*.log\n!keep.log\nbuild/\n**/tmp/**\n/rootonly.txt\ndoc/**/*.pdf\ncache\n!cache/\n\\#hash\n*.o\n'
        '!important.o\nlogs/*\n!logs/keep/\n',
        ['x.log', 'keep.log', 'build/out.bin', 'src/build/x', 'one/tmp/two/f', 'tmp/f', 'rootonly.txt',
         'sub/rootonly.txt', 'doc/a/b/c.pdf', 'doc/c.pdf', 'doc/c.txt', 'cache', 'dir/cache', 'cache2/cache/f',
         '#hash', 'a.o', 'important.o', 'logs/x', 'logs/keep/y', 'a/t.txt', 'a/a-keep.txt', 'a/nested/f',
         'a/b/t.txt', 'a/b/nested/f', 'secret-x', 'secret-public', 'd e/f g.txt', 'ü/ä.txt',
         'empty-dir-sibling/.keep'],
        {'a/.gitignore': '*.txt\n!a-keep.txt\nnested/\n', 'a/b/.gitignore': '!*.txt\n',
         '.git/info/exclude': 'secret-*\n!secret-public\n'},
        ['tracked.log', 'build/tracked.txt']),
}
CASE_LISTINGS = [(False, True, True), (True, True, True), (False, True, False)]
CASE_STATUS = [('no', None), ('normal', None), ('all', None)]

ATTRIBUTES = (
    '[attr]mybin -text -diff\n'
    '[attr]chain mybin\n'
    '* text eol=lf\n'
    '*.gz binary\n'            # composition/.gitattributes: a later binary unsets text
    '*.dat mybin\n'
    '*.late binary\n'
    '*.late text\n'            # a later text wins over an earlier binary
    '*.inl1 text binary\n'     # on one line, the macro after text wins
    '*.inl2 binary text\n'     # and text after the macro wins
    '*.chain chain\n'          # a macro naming a macro
    '*.neg binary\n'
    '*.neg -binary\n'          # a macro set false expands nothing
    '*.unspec !text\n'
    '*.UPPER binary\n'         # core.ignorecase: matched case-insensitively
    'dironly/ -text\n'         # a directory-only pattern never matches a file
    '!*.negpat -text\n'        # a negative pattern is ignored
    '"quoted name.q" -text\n'
    '*.info text\n'
    '*.bad -text bad!name\n'   # an invalid attribute name drops the line
)
ATTRIBUTE_FILES = ['x.gz', 'x.dat', 'x.late', 'x.inl1', 'x.inl2', 'x.chain', 'x.neg', 'x.unspec', 'x.upper',
                   'dironly/f.txt', 'x.negpat', 'quoted name.q', 'sub/y.sub', 'x.info', 'amybin', 'x.bad',
                   'plain.txt']
LINE_ENDINGS = {'lf.txt': b'one\ntwo\n', 'crlf.txt': CRLF, 'sub/a b.txt': b'space\r\n', 'same.txt': b'ab\n',
                'unchanged.txt': b'unchanged\r\n'}


def _ignore_cases(base):
    for number, (name, (gitignore, files, extra, tracked)) in enumerate(IGNORE_CASES.items()):
        repo = base / name
        repo.mkdir()
        git(repo, 'init', '-q', '-b', 'main')
        if gitignore is not None:
            write(repo, {'.gitignore': gitignore})
        write(repo, {path: 'data\n' for path in files + tracked})
        for path, text in extra.items():
            with open(Path(repo, *path.split('/')), 'a', encoding='utf-8', newline='\n') as handle:
                handle.write(text)
        if name == 'ignore levels':
            git(repo, 'config', 'core.excludesFile', '.git/extra excludes')
        if tracked or name == 'ignore corpus':
            git(repo, 'add', '-f', *tracked, *(p for p in ('.gitignore', *extra) if not p.startswith('.git/')))
            git(repo, 'commit', '-q', '-m', name, date=date(28 + number))
        if name == 'ignore corpus':
            (repo / 'empty').mkdir()
            inner = repo / 'inner'
            inner.mkdir()
            git(inner, 'init', '-q', '-b', 'main')


def _attribute_cases(base):
    """``attributes``: git's attribute order and macros (each file committed with CRLF content,
    so that git's status of the unchanged work tree is clean only under git's own evaluation)."""
    repo = base / 'attributes'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    write(repo, {'.gitattributes': ATTRIBUTES, 'sub/.gitattributes': '[attr]mybin text\n*.sub mybin\n'})
    write(repo, {path: CRLF for path in ATTRIBUTE_FILES})
    with open(repo / '.git' / 'info' / 'attributes', 'w', encoding='utf-8', newline='\n') as handle:
        handle.write('*.info binary\n')
    commit_all(repo, 'attributes', 40)
    write(repo, {'x.dat': b'ONE\r\ntwo\r\n'})   # same size, other content: compared


def _line_endings(base):
    """``line endings``: core.autocrlf=true in the repository; after the commit the work tree's
    line endings are swapped, so git reports each such file modified by its size alone."""
    repo = base / 'line endings'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    git(repo, 'config', 'core.autocrlf', 'true')
    write(repo, LINE_ENDINGS)
    git(repo, '-c', 'core.autocrlf=true', 'add', '-A')
    write(repo, {'keep-crlf.txt': b'x\r\n'})
    git(repo, 'add', 'keep-crlf.txt')            # autocrlf=false: a blob holding CRLF
    git(repo, '-c', 'core.autocrlf=true', 'commit', '-q', '-m', 'line endings', date=date(41))
    write(repo, {'lf.txt': CRLF, 'crlf.txt': b'one\ntwo\n', 'sub/a b.txt': b'space\n', 'keep-crlf.txt': b'x\n',
                 'same.txt': b'cd\n'})


CASES = {**{name: {'listing': CASE_LISTINGS, 'status': CASE_STATUS} for name in IGNORE_CASES},
         'attributes': {'listing': CASE_LISTINGS, 'status': CASE_STATUS},
         'line endings': {'listing': CASE_LISTINGS, 'status': CASE_STATUS}}


def full_name_forms(facts):
    """Per repository: the names asked of ``git rev-parse --verify --quiet --symbolic-full-name``."""
    E = facts['E']
    return {
        'repo one': ['HEAD', '@', 'main', 'heads/main', 'refs/heads/main', 'side', 'v1', 'tags/v1', 'refs/tags/v1',
                     'lw', 'treetag', 'blobtag', 'dup', 'heads/dup', 'tags/dup', 'refs/heads/dup', 'origin',
                     'origin/main', 'remotes/origin/main', 'refs/remotes/origin/HEAD', 'top', 'refs/top', 'ünï',
                     'cafe', 'ORIG_HEAD', 'FETCH_HEAD', 'nosuch', 'links-ok', 'main-worktree/HEAD', 'wtb',
                     'refs/heads/wtb', E, E[:7], 'HEAD~1', 'HEAD^2', 'HEAD^{tree}', 'v1^{}', 'main@{0}',
                     'HEAD:README.md', ':README.md', f'v1-1-g{E[:7]}'],
        'packed copy': ['HEAD', 'main', 'side', 'v1', 'dup', 'origin', 'top', 'refs/remotes/origin/HEAD', 'nosuch'],
        'linked tree': ['HEAD', '@', 'wtb', 'main', 'main-worktree/HEAD', 'HEAD~1'],
        'bare.git': ['HEAD', 'main', 'side', 'origin', 'v1', 'dup'],
        'sha256 repo': ['HEAD', 'main', 's1', 'side'],
        'separate work': ['HEAD', 'main'],
        'conflicted': ['HEAD', 'MERGE_HEAD', 'ORIG_HEAD', 'other'],
    }


# ---------------------------------------------------------------------------- the forms

def forms(facts):
    """Per repository: the revisions asked for a commit and the object names asked of cat-file."""
    A, B, C, D, E = (facts[k] for k in 'ABCDE')
    amb, cb = facts['amb4'], facts['cb4']
    refs = ['HEAD', '@', 'main', 'heads/main', 'refs/heads/main', 'side', 'refs/heads/side', 'v1', 'tags/v1',
            'refs/tags/v1', 'lw', 'v2', 'treetag', 'blobtag', 'dup', 'heads/dup', 'tags/dup', 'refs/heads/dup',
            'origin', 'origin/main', 'remotes/origin/main', 'refs/remotes/origin/HEAD', 'top', 'refs/top',
            'ünï', 'cafe', 'ORIG_HEAD', 'FETCH_HEAD', 'MERGE_HEAD', 'nosuch', 'no/such/ref', 'config',
            'HEAD/', 'main/', '/main', 'main.lock', 'refs', 'refs/heads', 'links-ok', 'HEAD@',
            'main-worktree/HEAD', 'info/exclude', 'logs/HEAD', 'logs/refs/heads/main', 'packed-refs',
            'refs/heads//main', '.git']
    ids = [E, E.upper(), E[:4], E[:5], E[:7], E[:12], E[:39], E[:3], E[:7].upper(), A[:7], amb, cb, facts['tree'],
           facts['readme_blob'], facts['v1_tag'], '0' * 40, 'f' * 64, 'f' * 41, 'f' * 39, 'zzzz', 'cafe']
    navigation = ['HEAD~', 'HEAD~0', 'HEAD~1', 'HEAD~2', 'HEAD~3', 'HEAD~4', 'HEAD~99', 'HEAD^', 'HEAD^0',
                  'HEAD^1', 'HEAD^2', 'HEAD^^', 'HEAD^^^', 'HEAD~1^1', 'HEAD~1^2', 'HEAD~1^3', 'HEAD~1^2~1',
                  'HEAD~1^2^', 'main~0', '@~1', '@^', 'v1~1', 'v1^', 'v1^0', 'v2~1', 'lw~0', 'lw^',
                  'HEAD~2147483647', 'HEAD~2147483648', 'HEAD^01', 'HEAD~01', E[:7] + '~1', cb + '~1', 'origin~1',
                  'treetag~1', 'blobtag^0', 'HEAD~1~1', 'HEAD^^2']
    peel = ['HEAD^{commit}', 'HEAD^{tree}', 'HEAD^{blob}', 'HEAD^{tag}', 'HEAD^{}', 'HEAD^{object}', 'v1^{}',
            'v1^{tag}', 'v1^{commit}', 'v1^{tree}', 'v1^{object}', 'v2^{}', 'v2^{tag}', 'v2^{commit}',
            'treetag^{tree}', 'treetag^{}', 'treetag^{commit}', 'blobtag^{blob}', 'blobtag^{}',
            'HEAD^{tree}^{tree}', 'HEAD^{commit}garbage}', 'HEAD^{commitx}', 'HEAD^{COMMIT}', 'HEAD^{}^{}',
            E[:7] + '^{tree}', cb + '^{tree}', cb + '^{}', amb + '^{}', 'HEAD~1^{commit}', 'HEAD^{commit}~1',
            'HEAD~1^{commit}^2', facts['tree'] + '^{tree}', facts['readme_blob'] + '^{blob}', 'HEAD^{']
    paths = ['HEAD:README.md', 'HEAD:', 'HEAD:openspec', 'HEAD:openspec/', 'HEAD~1:README.md', 'HEAD^2:README.md',
             'HEAD^2:docs/side.md', 'v1:README.md', 'HEAD:./README.md', 'HEAD:./', 'HEAD:../x', 'HEAD:no-such',
             'HEAD:README.md/', ':README.md', ':0:README.md', ':1:README.md',
             cb + ':README.md', amb + ':README.md', 'HEAD:links', 'links-ok:links/sub', 'links-ok:links/inside',
             'HEAD:/README.md', 'HEAD:openspec//config.yaml', ':./README.md', ':0:', ':4:README.md',
             'HEAD:a@{1}', 'HEAD:x@{upstream}']
    reflog = ['main@{0}', 'main@{1}', 'main@{2}', 'main@{3}', 'main@{4}', 'main@{5}', 'main@{99}', 'main@{00001}',
              'HEAD@{0}', 'HEAD@{1}', 'HEAD@{2}', 'HEAD@{8}', '@{0}', '@{1}', '@@{0}', 'side@{0}', 'side@{1}',
              'side@{2}', 'v1@{0}', 'refs/heads/main@{1}', 'main@{1}~1', 'main@{1}^{commit}', 'main@{1}^2',
              'nosuch@{0}', 'origin@{0}', 'origin/main@{0}', 'origin/main@{1}', 'dup@{0}', 'wtb@{0}',
              'main@{99999999}', '@{2}~1', 'main-worktree/HEAD@{0}']
    describe = [f'v1-1-g{E[:7]}', f'x-g{E[:7]}', f'g{E[:7]}', f'v1-g{A[:7]}', 'v1-gzz', 'v1-g', f'a-g{E[:3]}',
                f'a-g{cb}', f'a-1-g{cb}', f'a-g{B[:7]}~1', f'a-9-g{B[:7]}~1', f'v1-2-g{E[:7]}^{{tree}}',
                f'1-g{E[:7]}', f'a-01-g{E[:7]}', f'a-1x-g{E[:7]}', f'a-b-1-g{E[:7]}', f'v1-1-g{E[:7]}-dirty',
                f'a--1-g{E[:7]}', f'v1-1-g{E[:7].upper()}', f'a-1-G{E[:7]}', f'a-1-g{amb}', f'x-1-g{facts["tree"][:7]}']
    # git rereads the text after the last @{ as a reflog date when such a name does not resolve
    # otherwise (rev-parse <form>^{commit}); its answer then depends on the clock: refused.
    fallback = ['main@{0}:README.md', 'main@{1}^{tree}', 'main@{1}x', 'main@{3}~1', '@{1}^{blob}',
                'HEAD@{0}:', 'side@{0}~5']
    fallback_names = ['@{1}^{blob}', 'main@{1}^{tag}', 'HEAD@{0}^{blob}']
    main_commits = refs + ids + navigation + peel + paths + reflog + describe
    spaced = [f'HEAD:{UNI}', f'HEAD:{SPACED}', f'HEAD:{NON_ASCII_DIR}', f'HEAD:{NON_ASCII_DIR}/spécs/s péc.md',
              f':{NON_ASCII_DIR}/design.md', 'HEAD:openspec/changes/qual 02 spaced', f'{E}:{UNI}',
              f'HEAD:docs//{UNI[5:]}', 'HEAD: README.md', 'HEAD:README.md ', ':staged new.txt', f':{UNI}',
              ':data/binary.bin', 'HEAD:data/binary.bin', 'HEAD:eol/crlf.txt', 'no such name', f'HEAD~1:{UNI}',
              'HEAD:openspec/changes/qual 02 spaced/', 'links-ok:links/file.txt', 'HEAD:ignored-export/hidden.txt']
    main_names = main_commits + spaced + [f for f in fallback if f not in fallback_names]
    shared = ['HEAD', '@', 'main', 'refs/heads/main', 'side', 'v1', 'v1^{}', 'lw', 'dup', 'origin', 'top',
              E, E[:7], amb, cb, 'HEAD~1', 'HEAD^2', 'HEAD~1^2', 'HEAD^{tree}', 'HEAD:README.md', 'HEAD:',
              'main@{0}', 'main@{1}', 'HEAD@{1}', '@{0}', f'v1-1-g{E[:7]}', 'nosuch', 'ORIG_HEAD', ':README.md']
    sha = [facts[k] for k in ('H1', 'H2', 'H3', 'H4')]
    sha256 = ['HEAD', '@', 'main', 'side', 's1', 's1^{}', 's1^{tag}', 'HEAD~1', 'HEAD^2', 'HEAD~1^2', 'HEAD^{tree}',
              'HEAD:README.md', f'HEAD:{UNI}', 'HEAD:', sha[3], sha[3].upper(), sha[3][:4], sha[3][:7], sha[3][:40],
              sha[3][:63], sha[0][:12], 'f' * 64, 'f' * 40, 'main@{0}', 'main@{1}', 'HEAD@{2}', '@{1}',
              f'x-g{sha[2][:8]}', 'HEAD~3', 'HEAD^{}', ':README.md', 'nosuch']
    linked = ['HEAD', '@', 'wtb', 'main', 'HEAD~1', 'HEAD@{0}', 'HEAD@{1}', 'HEAD@{2}', '@{0}', '@{1}', 'wtb@{0}',
              'wtb@{1}', 'wtb@{2}', 'main@{0}', ':linked.txt', ':README.md', 'HEAD:linked.txt', 'ORIG_HEAD', 'v1',
              'FETCH_HEAD']
    separate = ['HEAD', '@', 'main', 'HEAD@{0}', '@{0}', ':sep.txt', 'HEAD:dir/inner.txt', 'HEAD:dir',
                facts['S'][:7], 'nosuch']
    bare = ['HEAD', '@', 'main', 'side', 'v1', 'v1^{}', 'origin', 'refs/remotes/origin/HEAD', 'HEAD~1', 'HEAD^2',
            E[:7], amb, cb, 'main@{0}', '@{0}', 'HEAD@{0}', ':README.md', 'HEAD:./README.md', 'HEAD:README.md',
            'links-ok', 'top']
    long = ['HEAD', 'HEAD:README.md', f'HEAD:{LONG_PATH}', f'HEAD:openspec/changes/{LONG_DIRS[0]}', 'main@{0}']
    replaced = ['HEAD', 'HEAD~1', 'HEAD~2', 'HEAD^{tree}', 'HEAD:f.txt', 'main@{0}', facts['R3'], facts['R1'],
                facts['R3'][:7]]
    conflicted = ['HEAD', 'MERGE_HEAD', 'other', ':conflict.txt', ':0:conflict.txt', ':1:conflict.txt',
                  ':2:conflict.txt', ':3:conflict.txt', ':both.txt', ':1:both.txt', ':2:both.txt', ':3:both.txt',
                  ':gone.txt', ':1:gone.txt', ':2:gone.txt', ':3:gone.txt', 'ORIG_HEAD', 'HEAD:gone.txt']

    def commits_only(names):
        return [n for n in names if not any(ch.isspace() for ch in n)]

    out = {
        'repo one': {'commits': main_commits, 'names': main_names, 'fallback_commits': fallback,
                     'fallback_names': fallback_names},
        'packed copy': {'commits': shared, 'names': shared + [f'HEAD:{UNI}', 'HEAD:openspec']},
        'bare.git': {'commits': bare, 'names': bare},
        'linked tree': {'commits': linked, 'names': linked},
        'separate work': {'commits': separate, 'names': separate},
        'sha256 repo': {'commits': sha256, 'names': sha256},
        'long.git': {'commits': long, 'names': long},
        'conflicted': {'commits': conflicted, 'names': conflicted},
        'replace disabled': {'commits': replaced, 'names': replaced},
        'replace loose': {'commits': [], 'names': [], 'replaced_commits': replaced, 'replaced_names': replaced},
        'replace packed': {'commits': [], 'names': [], 'replaced_commits': replaced, 'replaced_names': replaced},
    }
    for asked in out.values():
        asked['commits'] = commits_only(asked['commits'])
    return out


WORK_TREE_SUBJECTS = ['repo one', 'repo one/docs', 'repo one/openspec/changes/qual 02 spaced', 'linked tree',
                      'separate work', 'separate work/dir', 'sha256 repo', 'conflicted', 'bare.git',
                      'repo one/.git', 'repo one/.git/refs', 'separate.git', 'long.git', 'not a repo']
FILES = {'repo one': [('HEAD', 'openspec/changes'), ('HEAD', 'openspec/changes/qual 02 spaced'), ('HEAD', 'docs'),
                      ('HEAD', NON_ASCII_DIR), ('HEAD', f'{NON_ASCII_DIR}/spécs'),
                      ('HEAD', 'no/such'), ('HEAD', 'README.md'), ('HEAD', 'openspec'), ('HEAD~2', 'docs'),
                      ('links-ok', 'links'), ('HEAD', 'ignored-export')],
         'packed copy': [('HEAD', 'openspec/changes'), ('HEAD', 'docs')],
         'sha256 repo': [('HEAD', 'docs')],
         'long.git': [('HEAD', 'openspec/changes'), ('HEAD', f'openspec/changes/{LONG_DIRS[0]}')]}
EXPORTS = {'repo one': [('HEAD', '.'), ('HEAD', 'openspec'), ('HEAD', 'eol'), ('links-ok', '.')],
           'sha256 repo': [('HEAD', '.')], 'long.git': [('HEAD', '.')], 'packed copy': [('HEAD', 'openspec')]}
STATUS = {'repo one': [('no', None), ('normal', None), ('all', None), ('all', ['docs']), ('normal', ['newdir']),
                       ('no', ['openspec/changes', 'README.md'])],
          'conflicted': [('no', None), ('all', None)], 'linked tree': [('all', None)],
          'separate work': [('all', None)], 'sha256 repo': [('all', None)], 'packed copy': [('all', None)],
          'replace disabled': [('all', None)]}
LISTINGS = [(True, False, False), (False, True, False), (False, True, True), (True, True, True)]
WORK_TREES = ['repo one', 'linked tree', 'separate work', 'sha256 repo', 'conflicted', 'packed copy',
              'replace loose', 'replace packed', 'replace disabled']
HEADS = ['repo one', 'packed copy', 'bare.git', 'linked tree', 'separate work', 'sha256 repo', 'long.git',
         'conflicted', 'replace loose', 'replace packed', 'replace disabled']


# ---------------------------------------------------------------------------- git's answers

class Oracle:
    """git's answers over the extracted corpus at ROOT, under the environment that matches the
    module's ``repository`` configuration policy (no system, global or XDG configuration, no
    system attributes, no optional index writes)."""

    def __init__(self, root):
        self.root = Path(root)
        # GIT_CEILING_DIRECTORIES: git's discovery never looks above the corpus's temporary root.
        self.env = {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_ATTR_NOSYSTEM': '1',
                    'XDG_CONFIG_HOME': str(self.root / 'xdg empty'), 'GIT_OPTIONAL_LOCKS': '0',
                    'GIT_TERMINAL_PROMPT': '0', 'LC_ALL': 'C',
                    'GIT_CEILING_DIRECTORIES': str(self.root.resolve().parent)}

    def run(self, repo, *args, input=None):
        return subprocess.run(['git', '-c', 'core.longpaths=true', '-C', str(self.root / repo), *args],
                              input=input, capture_output=True, timeout=WAIT_CEILING_S,
                              stdin=None if input is not None else subprocess.DEVNULL,
                              env={**os.environ, **self.env})

    def version(self):
        return self.run('.', '--version').stdout.decode().strip()

    def commit(self, repo, form):
        """``git rev-parse --verify --quiet <form>^{commit}`` (one process per form)."""
        result = self.run(repo, 'rev-parse', '--verify', '--quiet', f'{form}^{{commit}}')
        return result.stdout.decode('ascii').strip() if result.returncode == 0 else None

    def commits(self, repo, forms):
        """{form: oid or None} for ``<form>^{commit}`` asked of one ``cat-file --batch-check``
        (git resolves the name as rev-parse does for every non-gap form; the tests check that
        these answers equal the recorded rev-parse ones)."""
        found = self.names(repo, [f'{form}^{{commit}}' for form in forms])
        return {form: (found[f'{form}^{{commit}}'] or [None])[0] for form in forms}

    def names(self, repo, names):
        """{name: [oid, type] or None} by ``cat-file --batch-check``, restarted after a name git
        dies on (that name answers None)."""
        answers, pending = {}, list(names)
        while pending:
            data = ''.join(n + '\n' for n in pending).encode('utf-8')
            result = self.run(repo, 'cat-file', '--batch-check', input=data)
            lines = result.stdout.decode('utf-8').splitlines()
            for name, line in zip(pending, lines):
                if line in (f'{name} missing', f'{name} ambiguous'):
                    answers[name] = None
                else:
                    oid, kind, _size = line.split(' ')
                    answers[name] = [oid, kind]
            if len(lines) >= len(pending):
                break
            answers[pending[len(lines)]] = None
            pending = pending[len(lines) + 1:]
        return answers

    def files(self, repo, commit, directory):
        result = self.run(repo, 'ls-tree', '-r', '-z', '--name-only', commit, '--', directory + '/')
        assert result.returncode == 0, result.stderr
        return [n.decode('utf-8') for n in result.stdout.split(b'\0') if n]

    def export_members(self, repo, commit, subtree):
        """[[path, mode, sha256 of the blob or None, size]] of ``ls-tree -r`` below SUBTREE."""
        args = ['ls-tree', '-r', '-z', commit] + ([] if subtree == '.' else ['--', subtree])
        result = self.run(repo, *args)
        assert result.returncode == 0, result.stderr
        rows = []
        for record in result.stdout.split(b'\0'):
            if not record:
                continue
            meta, path = record.split(b'\t', 1)
            mode, kind, oid = meta.decode().split()
            rows.append([path.decode('utf-8'), mode, kind, oid])
        blobs = [row[3] for row in rows if row[2] == 'blob']
        contents = self.blobs(repo, blobs)
        return [[path, mode, hashlib.sha256(contents[oid]).hexdigest() if kind == 'blob' else None,
                 len(contents[oid]) if kind == 'blob' else None] for path, mode, kind, oid in rows]

    def blobs(self, repo, oids):
        result = self.run(repo, 'cat-file', '--batch', input=''.join(o + '\n' for o in oids).encode())
        data, contents, pos = result.stdout, {}, 0
        for oid in oids:
            end = data.index(b'\n', pos)
            _oid, _kind, size = data[pos:end].decode().split()
            contents[oid] = data[end + 1:end + 1 + int(size)]
            pos = end + 1 + int(size) + 1
        return contents

    def head(self, repo):
        commit = self.run(repo, 'rev-parse', '--verify', '--quiet', 'HEAD')
        ref = self.run(repo, 'symbolic-ref', '--quiet', 'HEAD')
        return [commit.stdout.decode().strip() if commit.returncode == 0 else None,
                ref.stdout.decode().strip() if ref.returncode == 0 else None]

    def status(self, repo, untracked, paths):
        args = ['status', '--porcelain=v1', '-z', '--no-renames', f'--untracked-files={untracked}']
        if paths:
            args += ['--'] + [f':(literal){p}' for p in paths]
        result = self.run(repo, *args)
        assert result.returncode == 0, result.stderr
        return [[record[:2].decode(), record[3:].decode('utf-8')] for record in result.stdout.split(b'\0') if record]

    def index(self, repo):
        result = self.run(repo, 'ls-files', '-s', '-z')
        assert result.returncode == 0, result.stderr
        rows = []
        for record in result.stdout.split(b'\0'):
            if record:
                meta, path = record.split(b'\t', 1)
                mode, oid, stage = meta.decode().split()
                rows.append([int(mode, 8), oid, int(stage), path.decode('utf-8')])
        return rows

    def listing(self, repo, cached, others, exclude_standard):
        args = ['ls-files', '-z'] + (['--cached'] if cached else []) + (['--others'] if others else []) + \
            (['--exclude-standard'] if exclude_standard else [])
        result = self.run(repo, *args)
        assert result.returncode == 0, result.stderr
        return [n.decode('utf-8') for n in result.stdout.split(b'\0') if n]

    def toplevel(self, subject):
        result = self.run(subject, 'rev-parse', '--show-toplevel')
        if result.returncode != 0:
            return None
        top = os.path.realpath(result.stdout.decode('utf-8').strip())
        return Path(os.path.relpath(top, os.path.realpath(self.root))).as_posix()

    def bundle_heads(self, repo, path):
        result = self.run(repo, 'bundle', 'list-heads', str(path))
        return result.returncode, result.stdout.decode().splitlines()

    def files_batched(self, repo, cases):
        """{(commit, directory): paths} for CASES, one ``ls-tree -r -z --name-only <commit> --
        <dir>/ ...`` per commit: each directory's paths are the union's paths below it, in git's
        order (what one ``ls-tree`` per directory gives)."""
        out = {}
        for commit in dict.fromkeys(c for c, _d in cases):
            dirs = [d for c, d in cases if c == commit]
            result = self.run(repo, 'ls-tree', '-r', '-z', '--name-only', commit, '--', *(d + '/' for d in dirs))
            assert result.returncode == 0, result.stderr
            union = [n.decode('utf-8') for n in result.stdout.split(b'\0') if n]
            for d in dirs:
                out[(commit, d)] = [n for n in union if n.startswith(d + '/')]
        return out

    def head_batched(self, repo):
        """``rev-parse HEAD --symbolic-full-name HEAD`` in one launch: [commit, ref], the ref None
        when HEAD is detached (git then prints HEAD), as ``head`` answers."""
        result = self.run(repo, 'rev-parse', 'HEAD', '--symbolic-full-name', 'HEAD')
        if result.returncode != 0:
            return self.head(repo)
        commit, ref = result.stdout.decode().split()
        return [commit, None if ref == 'HEAD' else ref]

    def listings_batched(self, repo, asked):
        """{(cached, others, exclude): paths} for ASKED: the cached and the excluding listings from
        one ``ls-files -z -t --cached --others --exclude-standard`` (its '?' entries are the
        others, the rest the index entries, each in git's order), the others without excludes
        from their own ``ls-files``."""
        result = self.run(repo, 'ls-files', '-z', '-t', '--cached', '--others', '--exclude-standard')
        assert result.returncode == 0, result.stderr
        tagged = [(r[:1].decode(), r[2:].decode('utf-8')) for r in result.stdout.split(b'\0') if r]
        out = {}
        for cached, others, exclude in asked:
            if exclude or not others:
                out[(cached, others, exclude)] = [path for tag, path in tagged
                                                  if (tag == '?' and others) or (tag != '?' and cached)]
            else:
                out[(cached, others, exclude)] = self.listing(repo, cached, others, exclude)
        return out

    def status_batched(self, repo, asked):
        """{(untracked, paths): entries} for ASKED, with ``--untracked-files=no`` read from the
        same paths' ``all`` answer (its entries without the untracked ``??`` ones) when both are
        asked, and every other question asked of ``status`` itself."""
        out = {}
        for untracked, paths in asked:
            key = (untracked, tuple(paths or ()))
            if key in out:
                continue
            if untracked == 'no' and ('all', paths) in asked:
                every = out.get(('all', tuple(paths or ()))) or self.status(repo, 'all', paths)
                out[('all', tuple(paths or ()))] = every
                out[key] = [entry for entry in every if entry[0] != '??']
            else:
                out[key] = self.status(repo, untracked, paths)
        return out

    def full_names_batched(self, repo, names):
        """{name: full name or None} from one ``rev-parse --revs-only --symbolic-full-name <n1>
        --absolute-git-dir <n2> --absolute-git-dir ...``: each name's answer is what rev-parse
        prints before the next git-directory line (an absolute path, which no reference name is).
        A name rev-parse cannot read as a revision makes it read every later argument as a path:
        that name answers None and the launch restarts after it."""
        answers, pending = {}, list(names)
        while pending:
            args = ['rev-parse', '--revs-only', '--symbolic-full-name']
            for name in pending:
                args += [name, '--absolute-git-dir']
            lines = self.run(repo, *args).stdout.decode('utf-8').splitlines()
            done, group = 0, []
            for line in lines:
                if os.path.isabs(line):
                    assert len(group) <= 1, (pending[done], group)
                    answers[pending[done]] = group[0] if group else None
                    done, group = done + 1, []
                else:
                    group.append(line)
            if done == len(pending):
                break
            answers[pending[done]] = None
            pending = pending[done + 1:]
        return answers

    def full_name(self, repo, name):
        """``git rev-parse --verify --quiet --symbolic-full-name <name>`` (one process per name):
        the name printed, or None when git prints nothing or fails."""
        result = self.run(repo, 'rev-parse', '--verify', '--quiet', '--symbolic-full-name', name)
        text = result.stdout.decode('utf-8').strip()
        return text if result.returncode == 0 and text else None

    def bundle_verify(self, repo, path):
        result = self.run(repo, 'bundle', 'verify', '--quiet', str(path))
        return result.returncode, result.stderr.decode('utf-8', 'replace')


def answers(root, facts, batch=False):
    """Every answer the expectations record, asked of git over the corpus at ROOT: the commit
    forms with one ``rev-parse --verify`` each (recording), or through ``cat-file --batch-check``
    (BATCH, the oracle tests)."""
    oracle = Oracle(root)
    repos = {}
    for repo, asked in forms(facts).items():
        names = oracle.names(repo, asked['names'])
        if batch:
            batched = oracle.commits(repo, asked['commits'])
            commits = [[f, batched[f]] for f in asked['commits']]
        else:
            commits = [[f, oracle.commit(repo, f)] for f in asked['commits']]
        repos[repo] = {'commits': commits, 'names': [[n, names[n]] for n in asked['names']]}
        for kind in ('fallback', 'replaced'):
            # Recorded for the record, never compared with the module, which refuses these: the
            # fallback answers depend on the clock, the replaced ones on refs/replace/.
            if f'{kind}_commits' in asked and not batch:
                found = oracle.names(repo, asked[f'{kind}_names'])
                repos[repo][f'{kind}_commits'] = [[f, oracle.commit(repo, f)] for f in asked[f'{kind}_commits']]
                repos[repo][f'{kind}_names'] = [[n, found[n]] for n in asked[f'{kind}_names']]
    # Recording asks one question per launch; the oracle tests (BATCH) ask git many questions per
    # launch where git answers them in one (F-10.4), and check those answers against the recorded.
    for repo, cases in FILES.items():
        found = oracle.files_batched(repo, cases) if batch else {(c, d): oracle.files(repo, c, d) for c, d in cases}
        repos[repo]['files'] = [[c, d, found[(c, d)]] for c, d in cases]
    for repo, cases in EXPORTS.items():
        repos[repo]['export'] = [[c, s, oracle.export_members(repo, c, s)] for c, s in cases]

    def statuses(repo, cases):
        found = oracle.status_batched(repo, cases) if batch else \
            {(u, tuple(p or ())): oracle.status(repo, u, p) for u, p in cases}
        return [[u, p, found[(u, tuple(p or ()))]] for u, p in cases]

    def listings(repo, cases):
        found = oracle.listings_batched(repo, cases) if batch else \
            {(c, o, x): oracle.listing(repo, c, o, x) for c, o, x in cases}
        return [[c, o, x, found[(c, o, x)]] for c, o, x in cases]

    for repo, cases in STATUS.items():
        repos[repo]['status'] = statuses(repo, cases)
    for repo in WORK_TREES:
        repos[repo]['index'] = oracle.index(repo)
        repos[repo]['listing'] = listings(repo, LISTINGS)
    for repo in HEADS:
        repos[repo]['head'] = oracle.head_batched(repo) if batch else oracle.head(repo)
    work_trees = [[s, oracle.toplevel(s)] for s in WORK_TREE_SUBJECTS]
    cases = {}
    for repo, asked in CASES.items():
        cases[repo] = {'index': oracle.index(repo), 'listing': listings(repo, asked['listing']),
                       'status': statuses(repo, asked['status'])}
    full_names = {}
    for repo, names in full_name_forms(facts).items():
        found = oracle.full_names_batched(repo, names) if batch else {n: oracle.full_name(repo, n) for n in names}
        full_names[repo] = [[name, found[name]] for name in names]
    return {'git': oracle.version(), 'repos': repos, 'work_trees': work_trees, 'cases': cases,
            'full_names': full_names}


# ---------------------------------------------------------------------------- recording

def write_tree(root, path):
    """ROOT / ROOT_NAME as a deterministic gzipped JSON tree: sorted entries, each directory and
    file, a file's bytes as text when they are plain UTF-8 text, else base64."""
    base = Path(root)
    # git init's inert sample hooks are left out (no hook runs in any test).
    members = [base / ROOT_NAME] + sorted((p for p in (base / ROOT_NAME).rglob('*') if not p.name.endswith('.sample')),
                                         key=lambda p: p.relative_to(base).as_posix())
    entries = []
    for member in members:
        entry = {'path': member.relative_to(base).as_posix()}
        if member.is_dir():
            entry['type'] = 'dir'
        else:
            entry['type'] = 'file'
            data = member.read_bytes()
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                text = None
            if text is not None and not _NOT_TEXT.search(text):
                entry['text'] = text
            else:
                entry['base64'] = base64.b64encode(data).decode('ascii')
            if not os.access(member, os.W_OK):
                entry['read_only'] = True
        entries.append(entry)
    document = json.dumps({'schema': TREE_SCHEMA, 'root': ROOT_NAME, 'entries': entries}, indent=0,
                          ensure_ascii=False) + '\n'
    with open(path, 'wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as gz:
            gz.write(document.encode('utf-8'))


def record():
    work = Path(tempfile.mkdtemp(prefix='aieh-repo-corpus-record-'))
    try:
        facts = build(work / 'build')
        FIXTURES.mkdir(exist_ok=True)
        write_tree(work / 'build', ARCHIVE)
        extracted = work / 'extracted'
        extract_tree(ARCHIVE, extracted)
        data = {'schema': SCHEMA, 'archive_sha256': archive_digest(), 'root': ROOT_NAME, 'facts': facts,
                'long_path': LONG_PATH, **answers(extracted / ROOT_NAME, facts)}
        EXPECTED.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + '\n',
                            encoding='utf-8', newline='\n')
        print(f'recorded {ARCHIVE.name} ({ARCHIVE.stat().st_size} bytes, sha256 {data["archive_sha256"]}) and '
              f'{EXPECTED.name} with {data["git"]}')
    finally:
        rmtree(work)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--record', action='store_true', help='rebuild the corpus and rewrite both fixture files')
    args = parser.parse_args(argv)
    if not args.record:
        parser.error('nothing to do: pass --record')
    sys.stdout.reconfigure(encoding='utf-8')
    record()
    return 0


if __name__ == '__main__':
    sys.exit(main())
