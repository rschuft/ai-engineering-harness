"""Planning adapter: OpenSpec design references into Backlog.md tasks (plan leaf P-02.1).

Blueprint section ``#authority``: OpenSpec owns the accepted objective and the design;
Backlog.md owns tasks, dependencies and status. This adapter maps a small task plan
for one OpenSpec change into Backlog.md tasks through Backlog.md's own command line,
and gives every task source pointers that resolve the exact design revision:

    openspec:changes/<change-id>/<artifact-path>@<commit>#sha256=<digest>

``<commit>`` is the full git commit id of the design revision (40 or 64 hex digits),
``<artifact-path>`` is relative to ``openspec/changes/<change-id>/`` in that commit,
and ``<digest>`` is the sha256 of the artifact's blob bytes in that commit. The
pointer resolves in the project's own git repository, the one that holds both
``openspec/`` and Backlog.md's directory. Resolving it fails visibly when the commit
is missing, the artifact is missing at that commit, or its bytes differ from the
digest.

What the adapter never does:

- write Backlog.md's markdown files (only ``backlog task create``, ``task list
  --json`` and ``task view --json`` are run);
- pass, derive, mirror or report a task status: Backlog.md assigns its own default
  status and is the only owner of it;
- accept an OpenSpec change that carries its own implementation checklist
  (``tasks.md``) or whose schema tracks one (``apply.tracks``).

Usage (from the repository root):
    python -I -B integrations/planning/planning_adapter.py create --project DIR --plan FILE --revision REV --backlog CMD [--openspec CMD]
    python -I -B integrations/planning/planning_adapter.py resolve --project DIR (--pointer P ... | --backlog CMD [--task ID ...])
    python -I -B integrations/planning/planning_adapter.py pointer --project DIR --change ID --artifact PATH --revision REV

CMD is a Backlog.md (or OpenSpec) executable, or its ``.js`` entry point, which is
run with ``node``. Exit status: 0 PASS, 1 FAIL (a visible failure), 2 could not run.
Standard library only.
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

PLAN_FORMAT = 'planning-map/v1'
RESULT_FORMAT = 'planning-map-result/v1'
RESOLVE_FORMAT = 'planning-resolve/v1'
POINTER_PREFIX = 'openspec:'
CHANGES_DIR = 'openspec/changes'
TOOL_TIMEOUT_S = 120  # a ceiling that bounds a hung tool, not an expected duration
CHECKLIST_NAME = 'tasks.md'

CHANGE_ID = r'[a-z0-9]+(?:-[a-z0-9]+)*'
# A path part never starts with a dot, so '.', '..' and hidden files cannot be named.
PATH_PART = r'[A-Za-z0-9_][A-Za-z0-9._-]*'
ARTIFACT_PATH = rf'{PATH_PART}(?:/{PATH_PART})*'
COMMIT = r'[0-9a-f]{40}|[0-9a-f]{64}'
POINTER_RE = re.compile(
    rf'^openspec:changes/(?P<change>{CHANGE_ID})/(?P<artifact>{ARTIFACT_PATH})'
    rf'@(?P<revision>{COMMIT})#sha256=(?P<digest>[0-9a-f]{{64}})$')
CHANGE_ID_RE = re.compile(rf'^{CHANGE_ID}$')
ARTIFACT_RE = re.compile(rf'^{ARTIFACT_PATH}$')
TASK_ID_RE = re.compile(r'^[A-Za-z]+-[0-9]+(?:\.[0-9]+)*$')
# These grammars are checked with fullmatch: Python's $ also matches before a final newline,
# so .match would accept a task id or a pointer followed by a newline.

PLAN_KEYS = {'format', 'change', 'tasks'}
TASK_KEYS = {'key', 'title', 'description', 'artifacts', 'depends_on'}
# Status belongs to Backlog.md alone (blueprint #authority); a plan that tries to set
# or carry one is refused, never silently dropped.
STATUS_KEYS = {'status', 'state', 'done', 'completed', 'complete', 'checked', 'progress'}

# The only Backlog.md commands the adapter issues. None of them sets a status.
BACKLOG_COMMANDS = {('task', 'create'), ('task', 'list'), ('task', 'view')}
STATUS_FLAGS = ('-s', '--status')


class PlanningError(Exception):
    """A visible failure with a stable code."""

    def __init__(self, code, message, **details):
        super().__init__(f'{code}: {message}')
        self.code = code
        self.message = message
        self.details = details


class CannotRun(Exception):
    """A prerequisite or usage problem (exit 2)."""


@dataclass(frozen=True)
class Pointer:
    change: str
    artifact: str
    revision: str
    digest: str

    @property
    def repo_path(self):
        return f'{CHANGES_DIR}/{self.change}/{self.artifact}'

    @property
    def text(self):
        return f'openspec:changes/{self.change}/{self.artifact}@{self.revision}#sha256={self.digest}'

    @classmethod
    def parse(cls, text):
        match = POINTER_RE.fullmatch(text) if isinstance(text, str) else None
        if not match:
            raise PlanningError('POINTER_MALFORMED', f'not an OpenSpec source pointer: {text!r}',
                                pointer=text)
        return cls(match['change'], match['artifact'], match['revision'], match['digest'])


# ---------------------------------------------------------------------------
# Tools

def tool_argv(spec):
    """Turn a CMD argument into an argv prefix: a .js entry point runs with node."""
    path = Path(spec)
    if path.suffix.lower() in ('.js', '.cjs', '.mjs'):
        node = shutil.which('node')
        if not node:
            raise CannotRun('node is not on PATH; it is needed to run ' + spec)
        if not path.is_file():
            raise CannotRun(f'not a file: {spec}')
        return [node, str(path)]
    found = shutil.which(spec)
    if not found:
        raise CannotRun(f'command not found: {spec}')
    return [found]


def tool_env():
    env = dict(os.environ)
    # Never let an adapter run phone home or prompt.
    env.update({'OPENSPEC_TELEMETRY': '0', 'DO_NOT_TRACK': '1', 'GIT_TERMINAL_PROMPT': '0'})
    return env


class Git:
    """Read-only access to the project repository."""

    def __init__(self, project):
        self.project = Path(project)
        if not shutil.which('git'):
            raise CannotRun('git is not on PATH')
        top = self._run('rev-parse', '--show-toplevel', check=False)
        if top.returncode != 0:
            raise CannotRun(f'not a git working tree: {self.project}')

    def _run(self, *args, check=True):
        result = subprocess.run(['git', '-C', str(self.project), *args], capture_output=True,
                                stdin=subprocess.DEVNULL, timeout=TOOL_TIMEOUT_S, env=tool_env())
        if check and result.returncode != 0:
            raise PlanningError('GIT_FAILED', f'git {" ".join(args)}: '
                                f'{result.stderr.decode("utf-8", "replace").strip()}')
        return result

    def commit(self, revision):
        """The full commit id of REVISION, or None when the repository has no such commit."""
        if not isinstance(revision, str) or not revision or revision.startswith('-') \
                or any(ch.isspace() for ch in revision):
            raise PlanningError('REVISION_INVALID', f'not a usable revision: {revision!r}')
        result = self._run('rev-parse', '--verify', '--quiet', f'{revision}^{{commit}}', check=False)
        if result.returncode != 0:
            return None
        return result.stdout.decode('ascii').strip()

    def object_type(self, commit, path):
        result = self._run('cat-file', '-t', f'{commit}:{path}', check=False)
        return result.stdout.decode('ascii').strip() if result.returncode == 0 else None

    def blob(self, commit, path):
        return self._run('cat-file', 'blob', f'{commit}:{path}').stdout

    def files(self, commit, directory):
        out = self._run('ls-tree', '-r', '-z', '--name-only', commit, '--', directory + '/').stdout
        return [name.decode('utf-8') for name in out.split(b'\0') if name]

    def archive(self, commit, directory):
        return self._run('archive', '--format=tar', commit, '--', directory).stdout


# ---------------------------------------------------------------------------
# Pointers

def make_pointer(git, change, artifact, commit):
    if not CHANGE_ID_RE.fullmatch(change or ''):
        raise PlanningError('POINTER_MALFORMED', f'not an OpenSpec change id: {change!r}')
    if not isinstance(artifact, str) or not ARTIFACT_RE.fullmatch(artifact):
        raise PlanningError('POINTER_MALFORMED', f'not a relative artifact path: {artifact!r}')
    path = f'{CHANGES_DIR}/{change}/{artifact}'
    kind = git.object_type(commit, path)
    if kind != 'blob':
        raise PlanningError('POINTER_ARTIFACT_MISSING', f'{path} is not a file at {commit}',
                            artifact=path, revision=commit)
    digest = hashlib.sha256(git.blob(commit, path)).hexdigest()
    return Pointer(change, artifact, commit, digest)


def resolve_pointer(git, text):
    """Re-resolve a pointer against the repository. Returns the Pointer or raises."""
    pointer = Pointer.parse(text)
    commit = git.commit(pointer.revision)
    if commit != pointer.revision:
        raise PlanningError('POINTER_REVISION_MISSING',
                            f'the repository has no commit {pointer.revision}', pointer=text)
    kind = git.object_type(commit, pointer.repo_path)
    if kind != 'blob':
        raise PlanningError('POINTER_ARTIFACT_MISSING',
                            f'{pointer.repo_path} does not exist as a file at {commit}', pointer=text)
    actual = hashlib.sha256(git.blob(commit, pointer.repo_path)).hexdigest()
    if actual != pointer.digest:
        raise PlanningError('POINTER_DIGEST_MISMATCH',
                            f'{pointer.repo_path} at {commit} has sha256 {actual}, '
                            f'the pointer records {pointer.digest}', pointer=text, actual=actual)
    return pointer


# ---------------------------------------------------------------------------
# OpenSpec: no implementation checklist, no task tracking

def _scalar(text, key):
    """Value of a top-level 'key: value' line in a small YAML file, or None."""
    for line in text.splitlines():
        match = re.match(rf'^{re.escape(key)}\s*:\s*(.*?)\s*(?:#.*)?$', line)
        if match:
            return match.group(1).strip('\'"') or None
    return None


def schema_tracking(schema_text):
    """'untracked', 'tracked' or 'unknown' for an OpenSpec schema.yaml's apply.tracks."""
    lines = schema_text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith('apply'):
            continue
        head = re.match(r'^apply\s*:\s*(?:#.*)?$', line)
        if not head:
            return 'unknown'  # inline flow mapping or another form this scan does not read
        child_indent = None
        for child in lines[index + 1:]:
            if not child.strip() or child.lstrip().startswith('#'):
                continue
            indent = len(child) - len(child.lstrip(' '))
            if indent == 0:
                break
            if child_indent is None:
                child_indent = indent
            if indent != child_indent:
                continue  # nested content (a block scalar or a list)
            match = re.match(r'^\s+tracks\s*:\s*(.*?)\s*(?:#.*)?$', child)
            if match:
                return 'untracked' if match.group(1) in ('null', '~') else (
                    'unknown' if match.group(1) == '' else 'tracked')
        return 'untracked'
    return 'unknown'  # no apply section: what OpenSpec does then is not read here


def check_change(git, change, commit, openspec=None):
    """Refuse a change that is missing or carries or tracks its own implementation checklist."""
    directory = f'{CHANGES_DIR}/{change}'
    files = git.files(commit, directory)
    if not files:
        raise PlanningError('CHANGE_MISSING', f'{directory} does not exist at {commit}',
                            change=change, revision=commit)
    checklists = [name for name in files if name.rsplit('/', 1)[-1] == CHECKLIST_NAME]
    if checklists:
        raise PlanningError('OPENSPEC_CHECKLIST_PRESENT',
                            f'{", ".join(checklists)} duplicates the Backlog.md task list; Backlog.md '
                            'alone tracks implementation', files=checklists)
    schema = None
    meta = f'{directory}/.openspec.yaml'
    if git.object_type(commit, meta) == 'blob':
        schema = _scalar(git.blob(commit, meta).decode('utf-8', 'replace'), 'schema')
    if schema is None and git.object_type(commit, 'openspec/config.yaml') == 'blob':
        schema = _scalar(git.blob(commit, 'openspec/config.yaml').decode('utf-8', 'replace'), 'schema')
    result = {'schema': schema}
    schema_path = f'openspec/schemas/{schema}/schema.yaml' if schema and CHANGE_ID_RE.fullmatch(schema) else None
    in_repository = bool(schema_path) and git.object_type(commit, schema_path) == 'blob'
    static = schema_tracking(git.blob(commit, schema_path).decode('utf-8', 'replace')) \
        if in_repository else 'unknown'
    result['schema_in_repository'] = in_repository
    result['static_tracking'] = static
    if static == 'tracked':
        raise PlanningError('OPENSPEC_TRACKING_CONFIGURED',
                            f'schema {schema!r} at {commit} declares apply.tracks; Backlog.md alone '
                            'tracks implementation', schema=schema)
    if openspec is not None:
        result['openspec'] = openspec_apply_state(git, change, commit, openspec)
    elif static != 'untracked':
        raise PlanningError('OPENSPEC_TRACKING_UNKNOWN',
                            f'cannot establish from the repository that schema {schema!r} has no '
                            'apply.tracks; pass --openspec to ask OpenSpec itself', schema=schema)
    return result


def openspec_apply_state(git, change, commit, openspec_argv):
    """Ask OpenSpec, on an export of the exact revision, whether it tracks tasks for CHANGE."""
    with tempfile.TemporaryDirectory(prefix='aieh-planning-openspec-') as tmp:
        with tarfile.open(fileobj=io.BytesIO(git.archive(commit, 'openspec')), mode='r:') as tar:
            tar.extractall(tmp, filter='data')
        result = subprocess.run([*openspec_argv, 'instructions', 'apply', '--change', change, '--json'],
                                cwd=tmp, capture_output=True, stdin=subprocess.DEVNULL,
                                timeout=TOOL_TIMEOUT_S, env=tool_env())
    if result.returncode != 0:
        raise PlanningError('OPENSPEC_FAILED', 'openspec instructions apply exited '
                            f'{result.returncode}: {result.stderr.decode("utf-8", "replace").strip()}')
    try:
        data = json.loads(result.stdout.decode('utf-8'))
    except ValueError as exc:
        raise PlanningError('OPENSPEC_FAILED', f'openspec printed no JSON: {exc}') from None
    if not isinstance(data, dict) or data.get('changeName') != change:
        raise PlanningError('OPENSPEC_FAILED', 'openspec answered for another change')
    if data.get('taskTrackingConfigured') is not False or data.get('tasks') != []:
        raise PlanningError('OPENSPEC_TRACKING_CONFIGURED',
                            f'OpenSpec tracks tasks for {change} at {commit} '
                            f'(taskTrackingConfigured={data.get("taskTrackingConfigured")!r})')
    return {key: data.get(key) for key in ('schemaName', 'state', 'taskTrackingConfigured', 'tasks',
                                           'progress')}


# ---------------------------------------------------------------------------
# Plan

def load_plan(data):
    if not isinstance(data, dict):
        raise PlanningError('PLAN_INVALID', 'the plan is not a JSON object')
    found_status = STATUS_KEYS & set(data)
    if found_status:
        raise PlanningError('STATUS_NOT_OWNED', f'the plan carries {sorted(found_status)}; '
                            'Backlog.md alone owns task status')
    unknown = set(data) - PLAN_KEYS
    if unknown or data.get('format') != PLAN_FORMAT:
        raise PlanningError('PLAN_INVALID', f'expected keys {sorted(PLAN_KEYS)} and format '
                            f'{PLAN_FORMAT!r}; unknown: {sorted(unknown)}')
    change = data.get('change')
    if not isinstance(change, str) or not CHANGE_ID_RE.fullmatch(change):
        raise PlanningError('PLAN_INVALID', f'not an OpenSpec change id: {change!r}')
    tasks = data.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        raise PlanningError('PLAN_INVALID', 'tasks must be a non-empty list')
    seen = []
    for number, task in enumerate(tasks, 1):
        where = f'task {number}'
        if not isinstance(task, dict):
            raise PlanningError('PLAN_INVALID', f'{where} is not an object')
        found_status = STATUS_KEYS & set(task)
        if found_status:
            raise PlanningError('STATUS_NOT_OWNED', f'{where} carries {sorted(found_status)}; '
                                'Backlog.md alone owns task status')
        unknown = set(task) - TASK_KEYS
        if unknown:
            raise PlanningError('PLAN_INVALID', f'{where} has unknown keys {sorted(unknown)}')
        key, title = task.get('key'), task.get('title')
        if not isinstance(key, str) or not CHANGE_ID_RE.fullmatch(key) or key in seen:
            raise PlanningError('PLAN_INVALID', f'{where}: key must be a new kebab-case id: {key!r}')
        if not isinstance(title, str) or not title.strip() or title != title.strip() or '\n' in title:
            raise PlanningError('PLAN_INVALID', f'{where}: title must be one non-empty trimmed line')
        description = task.get('description', '')
        if not isinstance(description, str):
            raise PlanningError('PLAN_INVALID', f'{where}: description must be a string')
        artifacts = task.get('artifacts')
        if not isinstance(artifacts, list) or not artifacts or \
                not all(isinstance(a, str) for a in artifacts) or len(set(artifacts)) != len(artifacts):
            raise PlanningError('POINTER_ABSENT', f'{where} ({key}) names no design artifact; every '
                                'task needs a source pointer')
        depends = task.get('depends_on', [])
        if not isinstance(depends, list) or not all(isinstance(d, str) for d in depends) \
                or len(set(depends)) != len(depends):
            raise PlanningError('PLAN_INVALID', f'{where}: depends_on must be a list of task keys')
        for dep in depends:
            if dep not in seen:
                raise PlanningError('PLAN_DEPENDENCY_UNKNOWN',
                                    f'{where} ({key}) depends on {dep!r}, which is not an earlier '
                                    'task of this plan')
        seen.append(key)
    return {'change': change, 'tasks': tasks}


# ---------------------------------------------------------------------------
# Backlog.md

class Backlog:
    # The process runner, a dependency-injection seam for tests: None (the default) runs
    # Backlog.md with subprocess.run. A runner takes subprocess.run's arguments and returns
    # its CompletedProcess; it is given to the constructor, or set on the class.
    runner = None

    def __init__(self, argv_prefix, project, runner=None):
        self.argv_prefix = list(argv_prefix)
        self.project = Path(project)
        self.runner = type(self).runner if runner is None else runner

    def run(self, *args):
        if tuple(args[:2]) not in BACKLOG_COMMANDS:
            raise PlanningError('ADAPTER_REFUSED', f'the adapter does not issue backlog {" ".join(args[:2])}')
        options = args[:args.index('--')] if '--' in args else args  # after '--': the title only
        if any(arg in STATUS_FLAGS or arg.startswith(tuple(f + '=' for f in STATUS_FLAGS))
               for arg in options):
            raise PlanningError('ADAPTER_REFUSED', 'the adapter never sets a Backlog.md status')
        run = subprocess.run if self.runner is None else self.runner
        result = run([*self.argv_prefix, *args], cwd=self.project, capture_output=True,
                     stdin=subprocess.DEVNULL, timeout=TOOL_TIMEOUT_S, env=tool_env())
        if result.returncode != 0:
            raise PlanningError('BACKLOG_FAILED', f'backlog {" ".join(args[:2])} exited {result.returncode}: '
                                + (result.stderr or result.stdout).decode('utf-8', 'replace').strip())
        return result.stdout.decode('utf-8')

    def _json(self, kind, *args):
        try:
            data = json.loads(self.run(*args))
        except ValueError as exc:
            raise PlanningError('BACKLOG_OUTPUT', f'backlog {" ".join(args[:2])} printed no JSON: {exc}') from None
        if not isinstance(data, dict) or data.get('schemaVersion') != 1 or data.get('kind') != kind:
            raise PlanningError('BACKLOG_OUTPUT', f'expected a schemaVersion 1 {kind!r} envelope')
        return data

    def list_tasks(self):
        tasks = self._json('task-list', 'task', 'list', '--json').get('tasks')
        if not isinstance(tasks, list) or not all(isinstance(t, dict) and isinstance(t.get('id'), str)
                                                   for t in tasks):
            raise PlanningError('BACKLOG_OUTPUT', 'task-list without a list of tasks with ids')
        return tasks

    def view(self, task_id):
        if not TASK_ID_RE.fullmatch(task_id or ''):
            raise PlanningError('TASK_ID_INVALID', f'not a Backlog.md task id: {task_id!r}')
        task = self._json('task-view', 'task', 'view', task_id, '--json').get('task')
        if not isinstance(task, dict) or not isinstance(task.get('id'), str) \
                or task['id'].upper() != task_id.upper():
            raise PlanningError('BACKLOG_OUTPUT', f'task-view did not return {task_id}')
        return task

    def create(self, title, description, references, dependencies):
        args = ['task', 'create']
        if description:
            args.append(f'--description={description}')
        args += [f'--ref={ref}' for ref in references]
        if dependencies:
            args.append('--dep=' + ','.join(dependencies))
        args += ['--plain', '--', title]
        before = {t['id'] for t in self.list_tasks()}
        self.run(*args)
        new = [t['id'] for t in self.list_tasks() if t['id'] not in before]
        if len(new) != 1:
            raise PlanningError('BACKLOG_OUTPUT', f'expected exactly one new task after create, found {new}')
        return new[0]


def create_tasks(git, backlog, plan, revision, openspec=None):
    """Create the plan's tasks in Backlog.md with source pointers and dependencies."""
    plan = load_plan(plan)
    change = plan['change']
    commit = git.commit(revision)
    if commit is None:
        raise PlanningError('POINTER_REVISION_MISSING', f'the repository has no commit {revision!r}')
    openspec_state = check_change(git, change, commit, openspec)
    planned = []
    for task in plan['tasks']:
        pointers = [make_pointer(git, change, artifact, commit).text for artifact in task['artifacts']]
        planned.append((task, pointers))
    existing = backlog.list_tasks()
    for task, pointers in planned:
        for other in existing:
            if other.get('title') == task['title'] and other.get('references') == pointers:
                raise PlanningError('BACKLOG_DUPLICATE', f'{other["id"]} already maps {task["key"]} '
                                    f'from {change}@{commit}', task=other['id'])
    ids, created = {}, []
    try:
        for task, pointers in planned:
            deps = [ids[key] for key in task.get('depends_on', [])]
            new_id = backlog.create(task['title'], task.get('description', ''), pointers, deps)
            ids[task['key']] = new_id
            created.append({'key': task['key'], 'id': new_id})
            view = backlog.view(new_id)
            if view.get('title') != task['title'] or view.get('references') != pointers \
                    or [d.upper() for d in view.get('dependencies') or []] != [d.upper() for d in deps]:
                raise PlanningError('BACKLOG_MISMATCH', f'{new_id} does not carry the title, references '
                                    'and dependencies the adapter gave it')
            created[-1].update({'title': task['title'], 'references': pointers, 'dependencies': deps})
    except PlanningError as exc:
        exc.details['created'] = created
        raise
    return {'format': RESULT_FORMAT, 'change': change, 'revision': commit,
            'openspec': openspec_state, 'tasks': created}


def resolve_tasks(git, backlog, task_ids=None):
    """Re-resolve every OpenSpec pointer of the given (or all) Backlog.md tasks."""
    if not task_ids:
        task_ids = [t['id'] for t in backlog.list_tasks()]
    report = []
    for task_id in task_ids:
        task = backlog.view(task_id)
        refs = task.get('references') or []
        pointers = [r for r in refs if isinstance(r, str) and r.startswith(POINTER_PREFIX)]
        entry = {'id': task['id'], 'pointers': []}
        if not pointers:
            entry['failure'] = {'code': 'POINTER_ABSENT',
                                'message': f'{task["id"]} carries no OpenSpec source pointer'}
        for text in pointers:
            entry['pointers'].append(_resolve_entry(git, text))
        report.append(entry)
    return report


def _resolve_entry(git, text):
    try:
        resolve_pointer(git, text)
        return {'pointer': text, 'resolved': True}
    except PlanningError as exc:
        return {'pointer': text, 'resolved': False, 'code': exc.code, 'message': exc.message}


def _failures(report):
    for entry in report:
        if 'failure' in entry:
            yield entry['id'], None, entry['failure']['code'], entry['failure']['message']
        for item in entry['pointers']:
            if not item['resolved']:
                yield entry['id'], item['pointer'], item['code'], item['message']


# ---------------------------------------------------------------------------
# Command line

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create', help='create the plan\'s Backlog.md tasks with source pointers')
    create.add_argument('--project', required=True, type=Path)
    create.add_argument('--plan', required=True, type=Path)
    create.add_argument('--revision', required=True)
    create.add_argument('--backlog', required=True)
    create.add_argument('--openspec')
    resolve = sub.add_parser('resolve', help='re-resolve source pointers')
    resolve.add_argument('--project', required=True, type=Path)
    resolve.add_argument('--pointer', action='append', default=[])
    resolve.add_argument('--backlog')
    resolve.add_argument('--task', action='append', default=[])
    pointer = sub.add_parser('pointer', help='print the source pointer of one artifact')
    pointer.add_argument('--project', required=True, type=Path)
    pointer.add_argument('--change', required=True)
    pointer.add_argument('--artifact', required=True)
    pointer.add_argument('--revision', required=True)
    args = parser.parse_args(argv)
    try:
        git = Git(args.project)
        if args.command == 'create':
            try:
                plan = json.loads(args.plan.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                raise CannotRun(f'cannot read the plan: {exc}') from None
            backlog = Backlog(tool_argv(args.backlog), args.project)
            openspec = tool_argv(args.openspec) if args.openspec else None
            print(json.dumps(create_tasks(git, backlog, plan, args.revision, openspec), indent=2))
            return 0
        if args.command == 'pointer':
            commit = git.commit(args.revision)
            if commit is None:
                raise PlanningError('POINTER_REVISION_MISSING', f'the repository has no commit {args.revision!r}')
            print(make_pointer(git, args.change, args.artifact, commit).text)
            return 0
        if bool(args.pointer) == bool(args.backlog) or (args.task and not args.backlog):
            raise CannotRun('resolve takes either --pointer ... or --backlog CMD [--task ID ...]')
        if args.pointer:
            report = [{'id': None, 'pointers': [_resolve_entry(git, p) for p in args.pointer]}]
        else:
            report = resolve_tasks(git, Backlog(tool_argv(args.backlog), args.project), args.task)
        failures = list(_failures(report))
        print(json.dumps({'format': RESOLVE_FORMAT, 'tasks': report}, indent=2))
        for task_id, text, code, message in failures:
            print(f'FAIL {task_id or "-"} {text or "-"}: {code}: {message}', file=sys.stderr)
        return 1 if failures else 0
    except PlanningError as exc:
        print(f'FAIL {exc.code}: {exc.message}', file=sys.stderr)
        if exc.details.get('created'):
            print('Created before the failure (left in Backlog.md, not rolled back): '
                  + json.dumps(exc.details['created']), file=sys.stderr)
        return 1
    except (CannotRun, subprocess.TimeoutExpired, OSError) as exc:
        print(f'ERROR {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
