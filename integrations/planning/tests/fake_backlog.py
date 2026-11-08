"""A stand-in for the Backlog.md 1.55.3 command line, for the adapter's logic tests.

It implements only what the adapter issues (``task create``, ``task list --json``,
``task view <id> --json``) with the JSON envelope shapes recorded from the real
CLI (``fixtures/two-task/recorded/``). State lives in ``.fake-backlog.json`` in the
working directory, and every invocation's argv is appended to
``.fake-backlog-argv.jsonl`` there, so the tests can assert exactly what the
adapter asked for. ``FAKE_BACKLOG_MODE`` selects a misbehaviour:

- ``drop-refs``: create ignores ``--ref``;
- ``fail-create-2``: the second create exits 1;
- ``bad-envelope``: list answers with another schemaVersion;
- ``lost-create``: create reports success but keeps nothing.

``FAKE_BACKLOG_SNAPSHOT=<dir>`` instead replays Backlog.md's own recorded output:
``task list --json`` prints ``<dir>/task-list.json`` and ``task view <ID> --json``
prints ``<dir>/task-view-<ID>.json``, byte for byte; every other command fails.

Two ways to run it, with the same behaviour:

- as a command (``python -I -B fake_backlog.py ARGS``), launched by the adapter's
  ``Backlog`` exactly as Backlog.md is: the command-line contract tests do this;
- in the test process, through ``InProcessRunner(prefix)``, given to the adapter's
  ``Backlog`` as its runner (plan leaf F-09.3): it takes ``subprocess.run``'s arguments,
  runs ``main`` with the call's working directory and environment, and returns a
  ``CompletedProcess`` with the bytes the command would have printed. The logic tests
  do this, so they launch no process.

This is test scaffolding, not a Backlog.md implementation.
"""
import io
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

STATE = Path('.fake-backlog.json')
LOG = Path('.fake-backlog-argv.jsonl')
FILES = (STATE, LOG)
DEFAULT_STATUS = 'To Do'  # the fake's own default, as Backlog.md's config sets it


def load(cwd):
    state = cwd / STATE
    return json.loads(state.read_text(encoding='utf-8')) if state.exists() else {'tasks': []}


def save(cwd, state):
    (cwd / STATE).write_text(json.dumps(state), encoding='utf-8')


def summary(task):
    return {'id': task['id'], 'title': task['title'], 'status': task['status'],
            'references': task['references'], 'createdAt': '2026-11-07T00:00:00Z', 'updatedAt': None}


def replay(directory, argv, out, err):
    if argv == ['task', 'list', '--json']:
        name = 'task-list.json'
    elif argv[:2] == ['task', 'view'] and len(argv) == 4 and argv[3] == '--json':
        name = f'task-view-{argv[2].upper()}.json'
    else:
        print(f'fake: replay does not answer {argv}', file=err)
        return 1
    path = directory / name
    if not path.is_file():
        print(f'Task {argv[2] if len(argv) > 2 else ""} not found.', file=err)
        return 1
    out.flush()
    out.buffer.write(path.read_bytes())
    return 0


def main(argv, cwd=None, environ=None, out=None, err=None):
    cwd = Path('.') if cwd is None else Path(cwd)
    environ = os.environ if environ is None else environ
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    with (cwd / LOG).open('a', encoding='utf-8') as log:
        log.write(json.dumps(argv) + '\n')
    snapshot = environ.get('FAKE_BACKLOG_SNAPSHOT')
    if snapshot:
        return replay(Path(snapshot), argv, out, err)
    mode = environ.get('FAKE_BACKLOG_MODE', '')
    state = load(cwd)
    if argv[:2] == ['task', 'list'] and '--json' in argv:
        version = 2 if mode == 'bad-envelope' else 1
        print(json.dumps({'schemaVersion': version, 'kind': 'task-list',
                          'tasks': [summary(t) for t in state['tasks']]}), file=out)
        return 0
    if argv[:2] == ['task', 'view'] and len(argv) == 4 and argv[3] == '--json':
        for task in state['tasks']:
            if task['id'].upper() == argv[2].upper():
                print(json.dumps({'schemaVersion': 1, 'kind': 'task-view',
                                  'task': {**summary(task), 'dependencies': task['dependencies'],
                                           'description': task['description']}}), file=out)
                return 0
        print(f'Task {argv[2]} not found.', file=err)
        return 1
    if argv[:2] == ['task', 'create'] and '--' in argv:
        cut = argv.index('--')
        options, rest = argv[2:cut], argv[cut + 1:]
        if len(rest) != 1:
            print('expected one title', file=err)
            return 1
        if mode == 'fail-create-2' and len(state['tasks']) == 1:
            print('simulated failure', file=err)
            return 1
        task = {'id': f'TASK-{len(state["tasks"]) + 1}', 'title': rest[0], 'status': DEFAULT_STATUS,
                'description': None, 'references': [], 'dependencies': []}
        known = {t['id'] for t in state['tasks']}
        for option in options:
            name, _, value = option.partition('=')
            if name == '--description':
                task['description'] = value
            elif name == '--ref':
                if mode != 'drop-refs':
                    task['references'].append(value)
            elif name == '--dep':
                deps = [d.strip().upper() for d in value.split(',')]
                missing = [d for d in deps if d not in known]
                if missing:
                    print(f'The following dependencies do not exist: {missing}', file=err)
                    return 1
                task['dependencies'] = deps
            elif name == '--plain':
                pass
            else:
                print(f'fake: unsupported option {name}', file=err)
                return 1
        if mode != 'lost-create':
            state['tasks'].append(task)
            save(cwd, state)
        print(f'Task {task["id"]} - {task["title"]}', file=out)
        return 0
    print(f'fake: unsupported command {argv}', file=err)
    return 1


class InProcessRunner:
    """A runner for the adapter's ``Backlog``: this fake, run in the test process.

    It answers only argv that starts with PREFIX (the fake's command, as the tests name it);
    any other program (a missing command, for example) runs as a process through
    ``subprocess.run``, exactly as without this runner. ``calls`` holds every argv the fake
    answered, as a recording ``subprocess.run`` would."""

    def __init__(self, prefix):
        self.prefix = list(prefix)
        self.calls = []

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        if argv[:len(self.prefix)] != self.prefix:
            return subprocess.run(argv, **kwargs)
        if set(kwargs) - {'cwd', 'env', 'capture_output', 'stdin', 'timeout'} or not kwargs.get('capture_output'):
            raise AssertionError(f'the in-process fake Backlog.md is not run with {sorted(kwargs)}')
        cwd, env = kwargs.get('cwd'), kwargs.get('env')
        self.calls.append(argv)
        out = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
        err = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
        try:
            code = main(argv[len(self.prefix):], cwd=cwd, environ=os.environ if env is None else env,
                        out=out, err=err)
        except Exception:  # as the command would: a traceback on stderr, exit 1
            traceback.print_exc(file=err)
            code = 1
        out.flush()
        err.flush()
        return subprocess.CompletedProcess(argv, code, out.buffer.getvalue(), err.buffer.getvalue())


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
