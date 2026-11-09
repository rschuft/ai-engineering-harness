"""The P-02.1 two-task fixture: a throwaway project repository and its Backlog.md capture.

``build_repo`` creates a git repository holding one OpenSpec change under the
``intent-driven`` schema, committed with a fixed identity and date so that its
commit id is reproducible:

- ``openspec/config.yaml`` and ``openspec/changes/qual-02-search-freshness/``
  (``.openspec.yaml``, ``proposal.md`` and the delta spec) are copied from the P-01.2
  recording in ``tools/tests/fixtures/intent_qualification/openspec/``;
- ``openspec/schemas/intent-driven/`` is copied from ``catalog/``;
- ``design.md`` comes from ``fixtures/two-task/`` (written for this leaf).

``build_repo`` builds the repository once per process for a given input digest (the
design files, the commit message and the fixed identity and date) and copies that golden
repository to each later caller with plain file copies (``golden``); a copy is the same
repository, with the same commit id, as a fresh build. ``build_repo(..., golden_copy=False)``
builds it with git every time.

``live_capture`` then initialises Backlog.md in that repository, runs the adapter on
``fixtures/two-task/plan.json`` and captures Backlog.md's own ``task list --json`` and
``task view <id> --json`` output, with the creation times replaced by a placeholder.
The capture names no machine path.

Record or refresh the committed capture (needs the pinned Backlog.md and OpenSpec,
installed as described in ``integrations/planning/README.md``):

    python -I -B integrations/planning/tests/two_task_fixture.py --backlog CMD --openspec CMD --record
"""
import argparse
import atexit
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PLANNING = HERE.parent
REPO = PLANNING.parents[1]
FIXTURE = HERE / 'fixtures' / 'two-task'
RECORDED = FIXTURE / 'recorded'
PLAN = FIXTURE / 'plan.json'
CHANGE = 'qual-02-search-freshness'
INTENT_OPENSPEC = REPO / 'tools' / 'tests' / 'fixtures' / 'intent_qualification' / 'openspec'
SCHEMA = REPO / 'catalog' / 'openspec' / 'schemas' / 'intent-driven'
BACKLOG_VERSION = '1.55.3'
OPENSPEC_VERSION = '1.16.0'
TIMESTAMP = '<timestamp>'
WAIT_CEILING_S = 120

GIT_ENV = {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_AUTHOR_NAME': 'Fixture',
           'GIT_AUTHOR_EMAIL': 'fixture@example.invalid', 'GIT_COMMITTER_NAME': 'Fixture',
           'GIT_COMMITTER_EMAIL': 'fixture@example.invalid', 'GIT_AUTHOR_DATE': '2026-11-07T00:00:00Z',
           'GIT_COMMITTER_DATE': '2026-11-07T00:00:00Z'}
MACHINE_PATH = re.compile(r'[A-Za-z]:[\\/]|/Users/|/home/|\\\\[A-Za-z]')

sys.path.insert(0, str(PLANNING))
import planning_adapter as adapter  # noqa: E402


def require_repository_access():
    """Fail, never skip, where the adapter's repository access cannot run (decision 0014 section
    9): without Dulwich this raises CannotRun ``REPOSITORY_NEEDS_DULWICH``, naming ``task
    tools:install``. A test whose resolver would turn that into ``PROJECT_UNAVAILABLE`` (as a
    product run must) calls it first, so that its failure says why."""
    adapter.repository_access.dulwich_modules()


def rmtree(path):
    """Remove a tree that holds git's read-only object files (Windows refuses them otherwise)."""
    def retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    shutil.rmtree(path, onexc=retry)


def git(repo, *args, env=None):
    # core.longpaths: a fixture path below a long TEMP can pass Windows' 260-character limit
    # (the archived qual-02 spec is 114 characters below the repository); git for Windows then
    # needs it to stat the file. Other platforms ignore the setting.
    result = subprocess.run(['git', '-c', 'core.longpaths=true', '-C', str(repo), *args],
                            capture_output=True, text=True,
                            encoding='utf-8', timeout=WAIT_CEILING_S, stdin=subprocess.DEVNULL,
                            env={**os.environ, **GIT_ENV, **(env or {})})
    if result.returncode != 0:
        raise AssertionError(f'git {args}: {result.stderr}')
    return result.stdout.strip()


def design_files():
    """Repository path -> bytes of the design revision."""
    change = INTENT_OPENSPEC / 'changes' / CHANGE
    files = {'README.md': b'Throwaway project repository of the P-02.1 two-task fixture.\n',
             'openspec/config.yaml': (INTENT_OPENSPEC / 'config.yaml').read_bytes(),
             f'openspec/changes/{CHANGE}/design.md': (FIXTURE / 'design.md').read_bytes()}
    for path in sorted(change.rglob('*')):
        if path.is_file():
            files[f'openspec/changes/{CHANGE}/{path.relative_to(change).as_posix()}'] = path.read_bytes()
    for path in sorted(SCHEMA.rglob('*')):
        if path.is_file():
            files[f'openspec/schemas/intent-driven/{path.relative_to(SCHEMA).as_posix()}'] = path.read_bytes()
    return files


def write(repo, files):
    for name, data in files.items():
        target = Path(repo, *name.split('/'))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def loose_head(repo):
    """HEAD's commit id read from the files git wrote (gitrepository-layout): HEAD and, when it
    names a branch, that branch's loose ref; None when either is absent or not a commit id."""
    gitdir = Path(repo) / '.git'
    try:
        value = (gitdir / 'HEAD').read_text(encoding='ascii').strip()
        if value.startswith('ref: refs/heads/'):
            value = (gitdir / value[len('ref: '):]).read_text(encoding='ascii').strip()
    except (OSError, ValueError):
        return None
    return value if re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value) else None


def loose_object(repo, oid):
    """The file git wrote for the loose object OID of REPO (it must exist)."""
    path = Path(repo) / '.git' / 'objects' / oid[:2] / oid[2:]
    if not path.is_file():
        raise AssertionError(f'{oid} is not a loose object of {repo}')
    return path


def damage_object(repo, oid, how):
    """Damage the loose object OID of REPO, as a disk or another writer could (plan leaf F-10.3):
    'zlib', its bytes no zlib stream; 'another', the file of another object of REPO (HOW is then
    ('another', other oid)); 'directory', a directory in the file's place."""
    path = loose_object(repo, oid)
    os.chmod(path, stat.S_IWRITE)  # git writes object files read-only
    if how == 'zlib':
        path.write_bytes(b'not a zlib stream')
    elif how == 'directory':
        path.unlink()
        path.mkdir()
    else:
        kind, other = how
        assert kind == 'another', how
        path.write_bytes(loose_object(repo, other).read_bytes())


def loose_objects(repo):
    """Every loose object id of REPO."""
    root = Path(repo) / '.git' / 'objects'
    return sorted(p.parent.name + p.name for p in root.glob('[0-9a-f][0-9a-f]/*') if p.is_file())


def head(repo):
    """HEAD's commit id: read from the loose ref git just wrote, or, when HEAD is not a loose
    ref (packed, for example), asked of git."""
    return loose_head(repo) or git(repo, 'rev-parse', 'HEAD')


# The working-tree files of each repository at its last commit_all (or golden copy). When a
# later commit_all finds no file outside that set, every change is to a tracked path (an edit
# or a deletion), so `git commit --all` commits exactly what `git add --all` then `git commit`
# would, in one launch. Anything else (a new, moved or unknown file, a repository commit_all
# has not seen) takes the two steps.
_committed_files = {}


def _key(repo):
    return os.path.normcase(os.path.abspath(repo))


def worktree_files(repo):
    """Every file under REPO outside .git, as a relative POSIX path."""
    out = set()
    for directory, dirs, files in os.walk(repo):
        if '.git' in dirs:
            dirs.remove('.git')
        rel = Path(directory).relative_to(repo)
        out.update((rel / name).as_posix() for name in files)
    return frozenset(out)


def commit_all(repo, message, date=None):
    env = {'GIT_AUTHOR_DATE': date, 'GIT_COMMITTER_DATE': date} if date else None
    files = worktree_files(repo)
    known = _committed_files.get(_key(repo))
    # The set is used only while HEAD is still the commit it was recorded at.
    if known is not None and known[0] == loose_head(repo) and files <= known[1]:
        git(repo, 'commit', '--all', '--quiet', '-m', message, env=env)
    else:
        git(repo, 'add', '--all', env=env)
        git(repo, 'commit', '--quiet', '-m', message, env=env)
    commit = head(repo)
    _committed_files[_key(repo)] = (commit, files)
    return commit


DESIGN_MESSAGE = 'OpenSpec change qual-02-search-freshness: proposal, spec and design'

# Golden repositories: built once per process per input digest, then copied. The digest
# covers every input of the build (the files, the message, the identity and date); a change
# to any of them builds a new golden repository.
_golden_root = None
_golden = {}


def input_digest(*parts):
    """A sha256 over PARTS: bytes, strings, and {name: bytes} dicts (sorted by name)."""
    digest = hashlib.sha256()
    for part in parts:
        items = sorted(part.items()) if isinstance(part, dict) else [(None, part)]
        for name, value in items:
            for piece in (name, value):
                if piece is None:
                    continue
                data = piece if isinstance(piece, bytes) else str(piece).encode('utf-8')
                digest.update(len(data).to_bytes(8, 'big') + data)
        digest.update(b'\x00part')
    return digest.hexdigest()


def golden(repo, key, build):
    """Copy into REPO (which must not exist) the repository BUILD(directory) makes, and return
    BUILD's result. BUILD runs once per process for each KEY, in a temporary directory removed at
    exit; every call copies its result with plain file copies (git's object files stay
    read-only, as git wrote them)."""
    global _golden_root
    if key not in _golden:
        if _golden_root is None:
            _golden_root = Path(tempfile.mkdtemp(prefix='aieh-golden-'))
            atexit.register(rmtree, _golden_root)
        source = _golden_root / key[:16]
        _golden[key] = (source, build(source))
    source, result = _golden[key]
    shutil.copytree(source, repo, symlinks=True)
    if _key(source) in _committed_files:
        _committed_files[_key(repo)] = _committed_files[_key(source)]
    return result


def _build_design_repo(repo, files):
    Path(repo).mkdir(parents=True)
    git(repo, 'init', '--quiet', '-b', 'main')
    write(repo, files)
    return commit_all(repo, DESIGN_MESSAGE)


def build_repo(repo, golden_copy=True):
    """Create the design repository; return its commit id."""
    files = design_files()
    if not golden_copy:
        return _build_design_repo(repo, files)
    key = input_digest('build_repo/1', files, DESIGN_MESSAGE, GIT_ENV)
    return golden(repo, key, lambda directory: _build_design_repo(directory, files))


def isolated_env(home):
    """Environment overrides that keep the tools' per-user state inside HOME."""
    home = str(home)
    return {'HOME': home, 'USERPROFILE': home, 'APPDATA': home, 'LOCALAPPDATA': home,
            'XDG_CONFIG_HOME': home, 'XDG_DATA_HOME': home, 'XDG_CACHE_HOME': home,
            'OPENSPEC_TELEMETRY': '0', 'DO_NOT_TRACK': '1', 'CI': '1', **GIT_ENV}


def run_tool(argv, cwd):
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                            timeout=WAIT_CEILING_S, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise AssertionError(f'{argv[-3:]} exited {result.returncode}: {result.stderr or result.stdout}')
    return result.stdout


def tool_version(argv, cwd):
    return run_tool([*argv, '--version'], cwd).strip()


def backlog_init(backlog_argv, repo):
    run_tool([*backlog_argv, 'init', 'fixture', '--defaults', '--integration-mode', 'none',
              '--check-branches', 'false', '--include-remote', 'false'], repo)


def normalise(value):
    if isinstance(value, dict):
        return {k: (TIMESTAMP if k in ('createdAt', 'updatedAt') and v is not None else normalise(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [normalise(v) for v in value]
    return value


def capture(backlog_argv, repo, result):
    out = {'task-list.json': json.loads(run_tool([*backlog_argv, 'task', 'list', '--json'], repo))}
    for task in result['tasks']:
        out[f'task-view-{task["id"]}.json'] = json.loads(
            run_tool([*backlog_argv, 'task', 'view', task['id'], '--json'], repo))
    out['create-result.json'] = result
    return {name: normalise(data) for name, data in out.items()}


def live_capture(backlog_argv, openspec_argv, work):
    """Build the repository under WORK, create the two tasks, return (repo, commit, capture)."""
    repo = Path(work) / 'project'
    (Path(work) / 'home').mkdir(parents=True, exist_ok=True)
    with mock.patch.dict(os.environ, isolated_env(Path(work) / 'home')):
        commit = build_repo(repo)
        backlog_init(backlog_argv, repo)
        plan = json.loads(PLAN.read_text(encoding='utf-8'))
        result = adapter.create_tasks(adapter.Git(repo), adapter.Backlog(backlog_argv, repo), plan,
                                      commit, openspec_argv)
        return repo, commit, capture(backlog_argv, repo, result)


def dumps(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def recorded():
    return {path.name: json.loads(path.read_text(encoding='utf-8')) for path in sorted(RECORDED.glob('*.json'))}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Record the two-task fixture capture.')
    parser.add_argument('--backlog', required=True)
    parser.add_argument('--openspec', required=True)
    parser.add_argument('--record', action='store_true', help='write the capture into fixtures/')
    args = parser.parse_args(argv)
    backlog_argv, openspec_argv = adapter.tool_argv(args.backlog), adapter.tool_argv(args.openspec)
    work = Path(tempfile.mkdtemp(prefix='aieh-planning-record-'))
    try:
        (work / 'home').mkdir()
        with mock.patch.dict(os.environ, isolated_env(work / 'home')):
            versions = [(tool_version(backlog_argv, work), BACKLOG_VERSION),
                        (tool_version(openspec_argv, work), OPENSPEC_VERSION)]
        for version, want in versions:
            if version != want:
                print(f'ERROR expected version {want}, found {version}', file=sys.stderr)
                return 2
        _repo, commit, data = live_capture(backlog_argv, openspec_argv, work)
        for name, value in data.items():
            text = dumps(value)
            if MACHINE_PATH.search(text):
                print(f'ERROR {name} names a machine path', file=sys.stderr)
                return 1
            if args.record:
                RECORDED.mkdir(exist_ok=True)
                (RECORDED / name).write_text(text, encoding='utf-8', newline='\n')
        print(f'commit {commit}; {len(data)} files ' + ('recorded' if args.record else 'captured'))
        return 0
    finally:
        rmtree(work)


if __name__ == '__main__':
    sys.exit(main())
