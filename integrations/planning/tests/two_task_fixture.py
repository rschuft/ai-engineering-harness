"""The P-02.1 two-task fixture: a throwaway project repository and its Backlog.md capture.

``build_repo`` creates a git repository holding one OpenSpec change under the
``intent-driven`` schema, committed with a fixed identity and date so that its
commit id is reproducible:

- ``openspec/config.yaml`` and ``openspec/changes/qual-02-search-freshness/``
  (``.openspec.yaml``, ``proposal.md`` and the delta spec) are copied from the P-01.2
  recording in ``tools/tests/fixtures/intent_qualification/openspec/``;
- ``openspec/schemas/intent-driven/`` is copied from ``catalog/``;
- ``design.md`` comes from ``fixtures/two-task/`` (written for this leaf).

``live_capture`` then initialises Backlog.md in that repository, runs the adapter on
``fixtures/two-task/plan.json`` and captures Backlog.md's own ``task list --json`` and
``task view <id> --json`` output, with the creation times replaced by a placeholder.
The capture names no machine path.

Record or refresh the committed capture (needs the pinned Backlog.md and OpenSpec,
installed as described in ``integrations/planning/README.md``):

    python -I -B integrations/planning/tests/two_task_fixture.py --backlog CMD --openspec CMD --record
"""
import argparse
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


def rmtree(path):
    """Remove a tree that holds git's read-only object files (Windows refuses them otherwise)."""
    def retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    shutil.rmtree(path, onexc=retry)


def git(repo, *args, env=None):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True,
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


def commit_all(repo, message, date=None):
    env = {'GIT_AUTHOR_DATE': date, 'GIT_COMMITTER_DATE': date} if date else None
    git(repo, 'add', '--all', env=env)
    git(repo, 'commit', '--quiet', '-m', message, env=env)
    return git(repo, 'rev-parse', 'HEAD')


def build_repo(repo):
    """Create the design repository; return its commit id."""
    Path(repo).mkdir(parents=True)
    git(repo, 'init', '--quiet', '-b', 'main')
    write(repo, design_files())
    return commit_all(repo, 'OpenSpec change qual-02-search-freshness: proposal, spec and design')


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
