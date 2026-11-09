"""Readiness read: Backlog.md's own readiness and dependency states, surfaced (plan leaf P-02.2).

Blueprint section ``#authority``: Backlog.md owns tasks, dependencies, readiness and
status. This module reads Backlog.md 1.55.3's JSON (``task list --json`` and
``task view <id> --json``, envelope ``schemaVersion`` 1) and reports, per task,
whether it is eligible and why not. It never computes readiness: every verdict comes
from Backlog.md's own fields,

- ``isReady`` (in ``task list`` and ``task view``),
- ``readiness``: ``isReady``, ``isBlocked``, ``blockingDependencies``,
  ``missingDependencies`` (``task view``),
- ``dependencyGraph.nodes[].state`` (``task view``; ``resolved``, ``missing``,
  ``ambiguous``),

and a task is eligible only when Backlog.md reports it ready, its readiness fields are
present and agree, and (unless ``--no-pointers``) every OpenSpec source pointer it
carries resolves (``planning_adapter.resolve_pointer``). A field that is absent or of
the wrong type makes the task's readiness unknown, which is never eligible. Statuses
are neither read for a verdict nor reported.

Usage (from the repository root):
    python -I -B integrations/planning/planning_readiness.py --project DIR --backlog CMD [--task ID ...] [--no-pointers]

Exit status: 0 when every reported task's readiness is known and consistent and no
task has a missing dependency or a failing source pointer (blocked tasks are normal);
1 when any task does (each one is printed as ``FAIL <id>: <CODE> ...``); 2 could not run.
"""
import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location('planning_adapter', Path(__file__).resolve().parent / 'planning_adapter.py')
adapter = sys.modules.get('planning_adapter')
if adapter is None:
    adapter = importlib.util.module_from_spec(_spec)
    sys.modules['planning_adapter'] = adapter
    _spec.loader.exec_module(adapter)

READINESS_FORMAT = 'planning-readiness/v1'
READINESS_FIELDS = {'isReady': bool, 'isBlocked': bool, 'blockingDependencies': list,
                    'missingDependencies': list}

# Reason codes. Each names the Backlog.md field it reports; none is computed here.
MISSING = 'MISSING_DEPENDENCIES'          # readiness.missingDependencies is not empty
BLOCKED = 'BLOCKED_BY_DEPENDENCIES'       # readiness.blockingDependencies is not empty
NOT_READY = 'NOT_READY'                   # isReady false with neither list set (Backlog gives no more)
UNKNOWN = 'READINESS_UNKNOWN'             # a readiness field is absent or malformed
INCONSISTENT = 'READINESS_INCONSISTENT'   # Backlog.md's own readiness fields disagree
# A reason that is a visible failure (exit 1); BLOCKED and NOT_READY are ordinary states.
FAILURES = {MISSING, UNKNOWN, INCONSISTENT}


def _ids(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def classify(task, listed_is_ready):
    """One task's readiness entry from Backlog.md's task-view task and its task-list isReady."""
    readiness = task.get('readiness')
    entry = {'id': task.get('id'), 'eligible': False, 'reasons': [], 'blocking_dependencies': None,
             'missing_dependencies': None, 'graph_unresolved': None, 'backlog_readiness': readiness}
    well_formed = isinstance(readiness, dict) and all(
        isinstance(readiness.get(key), kind) for key, kind in READINESS_FIELDS.items()) and \
        _ids(readiness['blockingDependencies']) and _ids(readiness['missingDependencies']) and \
        isinstance(task.get('isReady'), bool) and isinstance(listed_is_ready, bool)
    graph = task.get('dependencyGraph')
    nodes = graph.get('nodes') if isinstance(graph, dict) else None
    if not isinstance(nodes, list) or not all(isinstance(n, dict) and isinstance(n.get('id'), str)
                                              and isinstance(n.get('state'), str) for n in nodes):
        well_formed = False
    if not well_formed:
        entry['reasons'].append(UNKNOWN)
        return entry
    entry['graph_unresolved'] = [{'id': n['id'], 'state': n['state']} for n in nodes
                                 if n['state'] != 'resolved']
    blocking, missing = readiness['blockingDependencies'], readiness['missingDependencies']
    entry['blocking_dependencies'], entry['missing_dependencies'] = blocking, missing
    ready = readiness['isReady']
    if missing:
        entry['reasons'].append(MISSING)
    if blocking:
        entry['reasons'].append(BLOCKED)
    if not ready and not missing and not blocking:
        entry['reasons'].append(NOT_READY)
    # Backlog.md's own fields must agree with one another; the adapter only compares them.
    if ready != task['isReady'] or ready != listed_is_ready or \
            (ready and (readiness['isBlocked'] or blocking or missing)) or \
            (readiness['isBlocked'] != bool(blocking or missing)):
        entry['reasons'].append(INCONSISTENT)
    entry['eligible'] = ready and not entry['reasons']
    return entry


def read_readiness(backlog, git=None, task_ids=None):
    """Readiness report for the listed (or given) tasks; pointers are resolved when GIT is given."""
    if git is None:
        return _read_readiness(backlog, None, task_ids)
    with git.session():  # one read session: one git batch reader for every pointer of the report
        return _read_readiness(backlog, git, task_ids)


def _read_readiness(backlog, git, task_ids):
    listed = {t['id']: t.get('isReady') for t in backlog.list_tasks()}
    report = []
    for task_id in task_ids or list(listed):
        task = backlog.view(task_id)
        entry = classify(task, listed.get(task['id']))
        if git is not None:
            refs = task.get('references')
            pointers = [r for r in refs if isinstance(r, str) and r.startswith(adapter.POINTER_PREFIX)] \
                if isinstance(refs, list) else []
            entry['pointers'] = [adapter._resolve_entry(git, text) for text in pointers]
            codes = [p['code'] for p in entry['pointers'] if not p['resolved']]
            if not pointers:
                codes = ['POINTER_ABSENT']
            for code in codes:
                if code not in entry['reasons']:
                    entry['reasons'].append(code)
            entry['eligible'] = entry['eligible'] and not codes
        report.append(entry)
    return {'format': READINESS_FORMAT, 'eligible': [e['id'] for e in report if e['eligible']],
            'tasks': report}


def failures(report):
    for entry in report['tasks']:
        for reason in entry['reasons']:
            if reason in FAILURES or reason.startswith('POINTER_'):
                detail = ''
                if reason == MISSING:
                    detail = ' ' + ', '.join(entry['missing_dependencies'])
                yield entry['id'], reason + detail


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--backlog', required=True)
    parser.add_argument('--task', action='append', default=[])
    parser.add_argument('--no-pointers', action='store_true',
                        help='report Backlog.md readiness only, without resolving source pointers')
    args = parser.parse_args(argv)
    try:
        git = adapter.Git(args.project)
        backlog = adapter.Backlog(adapter.tool_argv(args.backlog), args.project)
        report = read_readiness(backlog, None if args.no_pointers else git, args.task)
    except adapter.PlanningError as exc:
        print(f'FAIL {exc.code}: {exc.message}', file=sys.stderr)
        return 1
    except (adapter.CannotRun, subprocess.TimeoutExpired, OSError) as exc:
        print(f'ERROR {exc}', file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    found = list(failures(report))
    for task_id, text in found:
        print(f'FAIL {task_id}: {text}', file=sys.stderr)
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
