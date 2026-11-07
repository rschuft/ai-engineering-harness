"""The P-02.2 readiness fixtures: Backlog.md's own readiness JSON in three recorded stages.

Starting from the two-task fixture (``two_task_fixture.live_capture``: TASK-2 depends on
TASK-1, both created by the planning adapter), the stages are made only with Backlog.md's
command line and plain git, never by editing Backlog.md's files:

- ``blocked``: as created. TASK-1 is not done, so Backlog.md reports TASK-2 blocked by it.
- ``unblocked``: ``backlog task edit TASK-1 -s Done``, run by the test acting as the
  Backlog.md owner (the adapter writes no status). TASK-2 becomes ready; TASK-1, finished,
  is reported not ready and not blocked.
- ``missing``: everything committed; on a branch, ``backlog task create --dep=TASK-2``
  adds TASK-3 (with TASK-2's design pointer); on ``main``, ``backlog task archive TASK-2``
  and ``backlog task delete TASK-2``; then ``git merge``. Backlog.md refuses ``--dep`` on
  an id that does not exist and ``task delete`` strips the dependencies other tasks hold
  on the same branch, so a missing reference arises when work from two branches meets.
  Backlog.md then reports TASK-2 in TASK-3's ``missingDependencies``.

Each stage directory holds Backlog.md's ``task list --json``, ``task list --ready --json``
and ``task view <id> --json`` output (creation and update times replaced by
``<timestamp>``) and ``readiness.json``, the readiness report. Record or refresh them (needs the pinned Backlog.md and OpenSpec):

    python -I -B integrations/planning/tests/readiness_fixture.py --backlog CMD --openspec CMD --record
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import two_task_fixture as fx  # noqa: E402

PLANNING = fx.PLANNING
sys.path.insert(0, str(PLANNING))
import planning_readiness as readiness  # noqa: E402

adapter = fx.adapter
RECORDED = HERE / 'fixtures' / 'readiness'
STAGES = ('blocked', 'unblocked', 'missing')
TASK_3_TITLE = 'Verify that new products appear in search within 5 minutes'


def snapshot(backlog_argv, repo):
    listed = json.loads(fx.run_tool([*backlog_argv, 'task', 'list', '--json'], repo))
    out = {'task-list.json': listed,
           'task-list-ready.json': json.loads(fx.run_tool([*backlog_argv, 'task', 'list', '--ready', '--json'],
                                                          repo))}
    for task in listed['tasks']:
        out[f'task-view-{task["id"]}.json'] = json.loads(
            fx.run_tool([*backlog_argv, 'task', 'view', task['id'], '--json'], repo))
    report = readiness.read_readiness(adapter.Backlog(backlog_argv, repo), adapter.Git(repo))
    out['readiness.json'] = report
    return {name: fx.normalise(data) for name, data in out.items()}


def live_stages(backlog_argv, openspec_argv, work):
    """Run the three stages under WORK; return {stage: {file: data}} and the project path."""
    repo, _commit, created = fx.live_capture(backlog_argv, openspec_argv, work)
    stages = {}
    with mock.patch.dict(os.environ, fx.isolated_env(Path(work) / 'home')):
        stages['blocked'] = snapshot(backlog_argv, repo)
        fx.run_tool([*backlog_argv, 'task', 'edit', 'TASK-1', '-s', 'Done', '--plain'], repo)
        stages['unblocked'] = snapshot(backlog_argv, repo)
        pointer = created['create-result.json']['tasks'][1]['references'][0]
        fx.commit_all(repo, 'Backlog.md state after TASK-1 is done')
        fx.git(repo, 'checkout', '--quiet', '-b', 'side')
        fx.run_tool([*backlog_argv, 'task', 'create', '--dep=TASK-2', f'--ref={pointer}', '--plain', '--',
                     TASK_3_TITLE], repo)
        fx.commit_all(repo, 'TASK-3 depends on TASK-2')
        fx.git(repo, 'checkout', '--quiet', 'main')
        fx.run_tool([*backlog_argv, 'task', 'archive', 'TASK-2'], repo)
        fx.run_tool([*backlog_argv, 'task', 'delete', 'TASK-2'], repo)
        fx.commit_all(repo, 'TASK-2 archived and deleted')
        fx.git(repo, 'merge', '--quiet', '--no-edit', 'side')
        stages['missing'] = snapshot(backlog_argv, repo)
    return repo, stages


def recorded(stage):
    directory = RECORDED / stage
    return {p.name: json.loads(p.read_text(encoding='utf-8')) for p in sorted(directory.glob('*.json'))}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Record the P-02.2 readiness fixtures.')
    parser.add_argument('--backlog', required=True)
    parser.add_argument('--openspec', required=True)
    parser.add_argument('--record', action='store_true', help='write the stages into fixtures/readiness/')
    args = parser.parse_args(argv)
    backlog_argv, openspec_argv = adapter.tool_argv(args.backlog), adapter.tool_argv(args.openspec)
    work = Path(tempfile.mkdtemp(prefix='aieh-planning-readiness-'))
    try:
        _repo, stages = live_stages(backlog_argv, openspec_argv, work)
        for stage, files in stages.items():
            for name, value in files.items():
                text = fx.dumps(value)
                if fx.MACHINE_PATH.search(text):
                    print(f'ERROR {stage}/{name} names a machine path', file=sys.stderr)
                    return 1
                if args.record:
                    (RECORDED / stage).mkdir(parents=True, exist_ok=True)
                    (RECORDED / stage / name).write_text(text, encoding='utf-8', newline='\n')
            print(f'{stage}: eligible {files["readiness.json"]["eligible"]}; '
                  + '; '.join(f'{t["id"]} {t["reasons"]}' for t in files['readiness.json']['tasks']))
        return 0
    finally:
        fx.rmtree(work)


if __name__ == '__main__':
    sys.exit(main())
