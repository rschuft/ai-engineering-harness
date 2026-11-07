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

This is test scaffolding, not a Backlog.md implementation.
"""
import json
import os
import sys
from pathlib import Path

STATE = Path('.fake-backlog.json')
LOG = Path('.fake-backlog-argv.jsonl')
DEFAULT_STATUS = 'To Do'  # the fake's own default, as Backlog.md's config sets it


def load():
    return json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'tasks': []}


def save(state):
    STATE.write_text(json.dumps(state), encoding='utf-8')


def summary(task):
    return {'id': task['id'], 'title': task['title'], 'status': task['status'],
            'references': task['references'], 'createdAt': '2026-11-07T00:00:00Z', 'updatedAt': None}


def main(argv):
    with LOG.open('a', encoding='utf-8') as log:
        log.write(json.dumps(argv) + '\n')
    mode = os.environ.get('FAKE_BACKLOG_MODE', '')
    state = load()
    if argv[:2] == ['task', 'list'] and '--json' in argv:
        version = 2 if mode == 'bad-envelope' else 1
        print(json.dumps({'schemaVersion': version, 'kind': 'task-list',
                          'tasks': [summary(t) for t in state['tasks']]}))
        return 0
    if argv[:2] == ['task', 'view'] and len(argv) == 4 and argv[3] == '--json':
        for task in state['tasks']:
            if task['id'].upper() == argv[2].upper():
                print(json.dumps({'schemaVersion': 1, 'kind': 'task-view',
                                  'task': {**summary(task), 'dependencies': task['dependencies'],
                                           'description': task['description']}}))
                return 0
        print(f'Task {argv[2]} not found.', file=sys.stderr)
        return 1
    if argv[:2] == ['task', 'create'] and '--' in argv:
        cut = argv.index('--')
        options, rest = argv[2:cut], argv[cut + 1:]
        if len(rest) != 1:
            print('expected one title', file=sys.stderr)
            return 1
        if mode == 'fail-create-2' and len(state['tasks']) == 1:
            print('simulated failure', file=sys.stderr)
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
                    print(f'The following dependencies do not exist: {missing}', file=sys.stderr)
                    return 1
                task['dependencies'] = deps
            elif name == '--plain':
                pass
            else:
                print(f'fake: unsupported option {name}', file=sys.stderr)
                return 1
        if mode != 'lost-create':
            state['tasks'].append(task)
            save(state)
        print(f'Task {task["id"]} - {task["title"]}')
        return 0
    print(f'fake: unsupported command {argv}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
