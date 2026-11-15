"""The D1 demonstration repository's content and its Work records (plan leaf E-05.1).

The demo repository is ``aieh-d1-demo`` (Owner decision OA-25, 2026-11-14), the repository of the change
``add-slugify`` that planning designed (``evidence/bootstrap-log.md``, ``commitment-d1-2026-11-15``). This module
writes, in a clone of it (a git work tree; never this checkout), the content E-05.1 brings up, each as one commit
made in process through the repository-access module (decision 0014 sections 6 and 8: no git, no hook):

- ``seed``: a NEW local bare repository (its name ends ``aieh-d1-demo.git``, the name the acceptance recorder and
  ``guest.py repository-tests`` read from a clone's origin) whose branch ``main`` is one root commit, **C0**: the
  initial content, ``template_files()``: the template tree ``demo/aieh-d1-demo/`` beside this module (a tiny
  standard-library package ``aieh_d1_demo``, its ``unittest`` tests, a README, the Backlog.md 1.55.3 configuration
  as ``backlog init`` writes it, OpenSpec's ``openspec/config.yaml``), with the catalog's ``intent-driven`` schema
  (``catalog/openspec/schemas/intent-driven/``, copied, never kept twice). No dependency, no ``.claude/`` and no
  ``.mcp.json`` (the adapter loads project settings from the workspace; carried to E-05.1 on 2026-11-14). The
  repository-access module writes no root commit, so this one is written with Dulwich's object API (no git, no
  configuration read). A repository already there is reported when it is exactly that (``already present``) and
  refused otherwise (``SEED_DIFFERS``). The work tree is a clone of it, ``git clone -c core.autocrlf=false``
  (decision of E-05.1 dispatch 2: the site administrator pushes C0 to C3 as prepared here, then protects ``main``);
- ``place``: the change ``openspec/changes/add-slugify/``, byte for byte as planning stored it
  (``evidence/D1-demo-design/``, read only). The commit is checked before the branch moves: its placement content
  (decision 0020 point 1, ``input_recorder.read_design``) must be planning's ``PLANNED_CONTENT``
  (``PLACEMENT_CONTENT_MISMATCH``, nothing visible changes). A change folder already present and equal is left
  as it is; one that differs is refused (``PLACEMENT_DIFFERS``), never overwritten;
- ``commit-task``: **C3**, the one Backlog.md task file the planning adapter just created
  (``backlog/tasks/*.md``, untracked), committed alone; anything else in the work tree is refused
  (``TASK_NOT_ALONE``).

and reads, writing nothing:

- ``sequence``: the clone's ``main`` against the sequence the provisioning act pushes, exactly C0 to C3: C0 the
  initial content (a root commit), C1 C0 and the placement, C2 the acceptance recorder's commit (``proposal.md`` and
  ``.openspec.yaml`` of the change changed, one decision record added, nothing else), C3 one task file added;

- ``verify-placement``: the change at one commit against the placement: its content digest and, per file, the
  files that differ, were added or are missing. At the placement commit it is ``identical``; at the acceptance
  recorder's commit it shows exactly what the recorder changed (O1's fields in ``proposal.md``, ``x-outcomes`` in
  ``.openspec.yaml``, its decision record), the diff planning checks before ``accept-design``;
- ``statement``: the Owner's statement the acceptance recorder's ``record-from-log`` takes (E-05.12): his words
  about the change, verbatim from the Decisions entry ``owner-direction-d1-planning-2026-11-15``, written only
  after checking, at the harness's committed ``HEAD``, that the recorder admits them (``STATEMENT_OUTSIDE_VERBATIM``
  otherwise);
- ``plan``: the planning map (``planning-map/v1``) of the change's one Backlog.md task, with its source pointers'
  artifacts and the outcome reference the recorder minted, for ``planning_adapter.py create``.

Usage (from the repository root, under the tools interpreter: Dulwich is required):

    <tools python> -I -B integrations/gitea/demo_repository.py files
    <tools python> -I -B integrations/gitea/demo_repository.py seed --repository DIR.git --identity "Name <email>"
    <tools python> -I -B integrations/gitea/demo_repository.py place --project DIR --identity "Name <email>"
    <tools python> -I -B integrations/gitea/demo_repository.py commit-task --project DIR --identity "Name <email>"
    <tools python> -I -B integrations/gitea/demo_repository.py sequence --project DIR
    <tools python> -I -B integrations/gitea/demo_repository.py verify-placement --project DIR --commit FULL
    <tools python> -I -B integrations/gitea/demo_repository.py statement --out FILE [--harness DIR]
    <tools python> -I -B integrations/gitea/demo_repository.py plan --outcome REF --out FILE

Exit status: 0 done (JSON on standard output), 1 a verification that did not hold, 2 refused (a stable code).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
REPO = HERE.parents[1]
TEMPLATE = HERE / 'demo' / 'aieh-d1-demo'
SCHEMA = REPO / 'catalog' / 'openspec' / 'schemas' / 'intent-driven'
SCHEMA_PATH = 'openspec/schemas/intent-driven'
REPOSITORY = 'aieh-d1-demo'
CHANGE = 'add-slugify'
CHANGE_PATH = f'openspec/changes/{CHANGE}'
DESIGN = REPO / 'evidence' / 'D1-demo-design' / 'openspec' / 'changes' / CHANGE
# The placement content of planning's design, by decision 0020 point 1's formula over its four files
# (evidence/bootstrap-log.md, commitment-d1-2026-11-15).
PLANNED_CONTENT = 'sha256:203a9c1e100cd0cad48eb6b442e0f8d2a5550c0802d41cb1f1d4b066b1a55745'
# Never part of the demo repository: a workspace's Claude Code settings or MCP configuration.
FORBIDDEN = frozenset(('.claude', '.mcp.json'))
SKIPPED_DIRECTORIES = frozenset(('__pycache__',))

STATEMENT_ANCHOR = 'owner-direction-d1-planning-2026-11-15'
STATEMENT_REFERENCE = f'harness:evidence/bootstrap-log.md#{STATEMENT_ANCHOR}'
# The Owner's words about E-05.1's change, as he wrote them in that entry's verbatim block (item 2, its first four
# paragraphs): they name the change's repository (aieh-d1-demo), as record-from-log requires.
STATEMENT_TEXT = ('Finalize and accept the OpenSpec change for\n'
                  'aieh-d1-demo:\n'
                  '\n'
                  'Implement slugify(text) as a small Python function,\n'
                  'with appropriate unittest coverage.\n'
                  '\n'
                  'Choose sensible, explicit behavior for normalization,\n'
                  'whitespace, punctuation, case, empty input, and\n'
                  'non-ASCII text.\n'
                  '\n'
                  'Keep the demonstration intentionally small.')
STATEMENT_CHANNEL = 'main-session'  # given in the product manager's main session (the entry says so)

# The change's one Backlog.md task (E-05.1): its pointers name the three design artifacts (a pointer cannot
# name .openspec.yaml, whose name starts with a dot; P-02.1's grammar).
TASK = {'key': 'implement-slugify', 'title': 'Implement slugify(text) in aieh_d1_demo (add-slugify)',
        'description': 'Implement aieh_d1_demo.slugify(text) and its unittest tests as the OpenSpec change '
                       'add-slugify specifies (acceptance criteria AC1 to AC7); standard library only.',
        'artifacts': ['proposal.md', 'specs/slugify/spec.md', 'design.md']}

SEED_MESSAGE = 'aieh-d1-demo: the initial content (plan leaf E-05.1)'
PLACE_MESSAGE = 'OpenSpec change add-slugify, placed byte for byte as planning designed it (plan leaf E-05.1)'
TASK_MESSAGE = 'Backlog.md: the task of add-slugify (plan leaf E-05.1)'
BRANCH = 'refs/heads/main'
TASK_FILE = re.compile(r'backlog/tasks/[^/]+\.md')
DECISION_FILE = re.compile(rf'{re.escape(CHANGE_PATH)}/owner-decisions/[0-9a-f-]{{36}}\.json')
RECORDER_CHANGES = (f'{CHANGE_PATH}/.openspec.yaml', f'{CHANGE_PATH}/proposal.md')


class DemoError(Exception):
    """A stable code; ``refusal`` (exit 2) when nothing was written, else a failed verification (exit 1)."""

    def __init__(self, code, message, refusal=True, **details):
        super().__init__(f'{code}: {message}')
        self.code, self.message, self.refusal, self.details = code, message, refusal, details


def _load(name, path):
    """A sibling module by path, once per process (``python -I`` adds no script directory)."""
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


def _ra():
    """The shared repository-access module, under the name the planning adapter and the recorders load it with."""
    return _load('repository_access', REPO / 'integrations' / 'repository' / 'repository_access.py')


def _planning():
    return _load('planning_adapter', REPO / 'integrations' / 'planning' / 'planning_adapter.py')


def _acceptance_recorder():
    return _load('acceptance_recorder', REPO / 'integrations' / 'owner' / 'acceptance_recorder.py')


def _input_recorder():
    return _load('input_recorder', REPO / 'integrations' / 'owner' / 'input_recorder.py')


# ---------------------------------------------------------------------------- the content


def _tree(root: Path, prefix: str) -> dict:
    """{prefix + relative POSIX path: bytes} of every file below ROOT; ``__pycache__`` directories are skipped,
    and a symbolic link or a forbidden name (FORBIDDEN) anywhere is refused."""
    if not root.is_dir():
        raise DemoError('CONTENT_MISSING', f'{root} is not a directory')
    files = {}
    for directory, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRECTORIES)
        for name in [*dirs, *names]:
            path = Path(directory, name)
            if name in FORBIDDEN:
                raise DemoError('CONTENT_FORBIDDEN', f'{path.relative_to(root).as_posix()}: the demo repository '
                                'carries no Claude Code settings or MCP configuration')
            if path.is_symlink():
                raise DemoError('CONTENT_FORBIDDEN', f'{path.relative_to(root).as_posix()} is a symbolic link')
        for name in sorted(names):
            path = Path(directory, name)
            files[prefix + path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def template_files() -> dict:
    """The demo repository's initial content: {repository path: bytes}, in path order."""
    files = _tree(TEMPLATE, '')
    schema = _tree(SCHEMA, SCHEMA_PATH + '/')
    overlap = sorted(set(files) & set(schema))
    if overlap or any(p.startswith(('openspec/changes/', 'backlog/tasks/')) for p in files):
        raise DemoError('CONTENT_FORBIDDEN', f'the template holds a schema file, a change or a task: '
                        f'{overlap or sorted(p for p in files if p.startswith(("openspec/changes/", "backlog/")))}')
    files.update(schema)
    return dict(sorted(files.items(), key=lambda item: item[0].encode('utf-8')))


def design_files() -> dict:
    """The change's files as planning stored them: {repository path under CHANGE_PATH: bytes}."""
    return dict(sorted(_tree(DESIGN, CHANGE_PATH + '/').items(), key=lambda item: item[0].encode('utf-8')))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def files_report() -> dict:
    """What ``seed`` and ``place`` write, by path and sha256 (no content)."""
    return {'format': 'aieh-d1-demo-files/v1', 'repository': REPOSITORY,
            'template': {p: _sha256(d) for p, d in template_files().items()},
            'design': {'change': CHANGE, 'planned_content': PLANNED_CONTENT,
                       'files': {p: _sha256(d) for p, d in design_files().items()}}}


# ---------------------------------------------------------------------------- the commits


def _open(project, work_tree=True):
    ra = _ra()
    project = Path(project)
    try:
        return ra.open_repository(project, config='repository', work_tree=work_tree,
                                  ceilings=[str(project.resolve().parent)])
    except (ra.CannotRun, ra.RepositoryError) as exc:
        raise DemoError('PROJECT_UNAVAILABLE', f'{project}: {exc}') from None


def _head(repo):
    head = repo.head()
    if head.commit is None:
        raise DemoError('PROJECT_EMPTY', 'the project repository has no commit at HEAD: clone the seeded repository '
                        '(C0) first')
    return head.commit


def _present(repo, commit, files) -> tuple[dict, list]:
    """(the FILES not at COMMIT, the paths at COMMIT whose bytes differ)."""
    missing, differs = {}, []
    for path, data in files.items():
        found = repo.read(f'{commit}:{path}')
        if found is None:
            missing[path] = data
        elif found[1] != 'blob' or found[2] != data:
            differs.append(path)
    return missing, differs


def _commit(repo, files, message, identity, expected, check=None):
    ra = _ra()
    try:
        return repo.write_commit(files, message, identity=identity, expected_head=expected, check=check)
    except ra.RepositoryError as exc:
        raise DemoError(exc.code, exc.message, refusal=exc.code != 'GIT_FAILED', **exc.details) from None


def _check_identity(identity):
    if not isinstance(identity, str) or not _ra().IDENTITY.fullmatch(identity):
        raise DemoError('IDENTITY_INVALID', f'{identity!r} is not "Name <email>"')


def tree_files(repo, commit) -> dict:
    """{path: blob bytes} of every file of COMMIT, read through the repository module's export (no end-of-line
    conversion), in path order."""
    with tempfile.TemporaryDirectory(prefix='aieh-demo-tree-') as tmp:
        repo.export_tree(commit, '.', tmp)
        found = {}
        for directory, _dirs, names in os.walk(tmp):
            for name in names:
                path = Path(directory, name)
                found[path.relative_to(tmp).as_posix()] = path.read_bytes()
    return dict(sorted(found.items(), key=lambda item: item[0].encode('utf-8')))


def _parents(repo, commit) -> list:
    out, number = [], 1
    while (parent := repo.commit(f'{commit}^{number}')) is not None:
        out.append(parent)
        number += 1
    return out


def _seeded(path, files) -> dict:
    """An existing REPOSITORY that is exactly what seed makes, reported; anything else refused."""
    try:
        with _open(path, work_tree=False) as repo:
            head = repo.head()
            commit = repo.commit(BRANCH)
            if head.ref != BRANCH or commit is None or _parents(repo, commit) or tree_files(repo, commit) != files:
                raise DemoError('SEED_DIFFERS', f'{path} exists and is not one root commit of the initial content on '
                                'main; nothing is overwritten')
    except DemoError as exc:
        if exc.code == 'PROJECT_UNAVAILABLE':
            raise DemoError('SEED_DIFFERS', f'{path} exists and is not a git repository; nothing is written') from None
        raise
    return {'operation': 'seed', 'result': 'already present', 'repository': str(path), 'commit': commit}


def _identity_bytes(identity) -> bytes:
    _check_identity(identity)
    return identity.encode('utf-8')


def _write_tree(objects, store, files) -> bytes:
    """The nested trees of FILES ({path: bytes}, regular non-executable files) in STORE; the root tree's id."""
    root = {}
    for path, data in files.items():
        node = root
        *dirs, name = path.split('/')
        for part in dirs:
            node = node.setdefault(part, {})
        node[name] = data

    def write(node):
        tree = objects.Tree()
        for name, value in node.items():
            if isinstance(value, dict):
                tree.add(name.encode('utf-8'), 0o040000, write(value))
            else:
                blob = objects.Blob.from_string(value)
                store.add_object(blob)
                tree.add(name.encode('utf-8'), 0o100644, blob.id)
        store.add_object(tree)
        return tree.id
    return write(root)


def seed(repository, identity, now=None) -> dict:
    """Create the NEW bare repository REPOSITORY whose main is one root commit of the initial content (C0); see the
    module's text. NOW ((seconds, offset east of UTC in seconds)) stands in for the clock in tests."""
    author = _identity_bytes(identity)
    files = template_files()
    path = Path(repository)
    if not path.name.endswith(f'{REPOSITORY}.git'):
        raise DemoError('SEED_NAME', f'{path.name!r}: the repository\'s name ends {REPOSITORY}.git, which names its '
                        'clones\' origin')
    if os.path.lexists(path):
        return _seeded(path, files)
    if not path.parent.is_dir():
        raise DemoError('SEED_NAME', f'{path.parent} is not a directory')
    d = _ra().dulwich_modules()
    seconds, offset = now or (int(time.time()), time.localtime().tm_gmtoff)
    repo = d.repo.Repo.init_bare(str(path), mkdir=True, config=d.config.StackedConfig([]), default_branch=b'main')
    try:
        commit = d.objects.Commit()
        commit.tree = _write_tree(d.objects, repo.object_store, files)
        commit.parents = []
        commit.author = commit.committer = author
        commit.author_time = commit.commit_time = seconds
        commit.author_timezone = commit.commit_timezone = offset
        commit.encoding = b'UTF-8'
        commit.message = SEED_MESSAGE.encode('utf-8') + b'\n'
        repo.object_store.add_object(commit)
        repo.refs[BRANCH.encode('ascii')] = commit.id
        repo.refs.set_symbolic_ref(b'HEAD', BRANCH.encode('ascii'))
    finally:
        repo.close()
    report = _seeded(path, files)  # read back through the repository module
    return {**report, 'result': 'created', 'written': sorted(files)}


def placement_report(project, commit) -> dict:
    """The change at COMMIT against the placement (read only)."""
    content, files = _input_recorder().read_design(project, REPOSITORY, CHANGE, commit)
    held = dict(files)
    planned = {p[len(CHANGE_PATH) + 1:]: _sha256(d) for p, d in design_files().items()}
    return {'operation': 'verify-placement', 'repository': REPOSITORY, 'change': CHANGE, 'commit': commit,
            'content': content, 'planned_content': PLANNED_CONTENT,
            'identical': content == PLANNED_CONTENT and held == planned,
            'differs': sorted(p for p in planned if p in held and held[p] != planned[p]),
            'added': sorted(p for p in held if p not in planned),
            'missing': sorted(p for p in planned if p not in held)}


def place(project, identity) -> dict:
    """Commit the change's files byte for byte (design_files); see the module's text."""
    _check_identity(identity)
    files = design_files()
    with _open(project) as repo:
        head = _head(repo)
        held = set(repo.files(head, CHANGE_PATH) or ())
        missing, differs = _present(repo, head, files)
        extra = sorted(held - set(files))
        relative = len(CHANGE_PATH) + 1
        if not missing and not differs and not extra:
            report = placement_report(project, head)
            return {'operation': 'place', 'result': 'already present', 'commit': head,
                    'content': report['content'], 'identical': report['identical']}
        if held:
            differs, extra, missing = ([p[relative:] for p in sorted(paths)] for paths in (differs, extra, missing))
            raise DemoError('PLACEMENT_DIFFERS', f'{CHANGE_PATH}/ is at {head} and is not the placement (differs: '
                            f'{differs}, added: {extra}, missing: {missing}); nothing is overwritten',
                            differs=differs, added=extra, missing=missing)

        def check(commit):
            # Before the branch moves (write_commit's CHECK): the placement content must be planning's.
            content, _ = _input_recorder().read_design(project, REPOSITORY, CHANGE, commit)
            if content != PLANNED_CONTENT:
                raise DemoError('PLACEMENT_CONTENT_MISMATCH', f'the placement\'s content is {content}, planning\'s '
                                f'is {PLANNED_CONTENT}; nothing was committed', content=content)
        commit = _commit(repo, files, PLACE_MESSAGE, identity, head, check=check)
    report = placement_report(project, commit)
    return {'operation': 'place', 'result': 'committed', 'commit': commit, 'parent': head,
            'written': sorted(files), 'content': report['content'], 'identical': report['identical']}


def commit_task(project, identity) -> dict:
    """C3: commit the one Backlog.md task file the planning adapter created (untracked), and nothing else."""
    _check_identity(identity)
    with _open(project) as repo:
        head = _head(repo)
        entries = repo.status(untracked='all')
        tracked = [f'{e.xy} {e.path}' for e in entries if e.xy != '??']
        new = [e.path for e in entries if e.xy == '??']
        if tracked or len(new) != 1 or not TASK_FILE.fullmatch(new[0]):
            raise DemoError('TASK_NOT_ALONE', f'the work tree must hold exactly one new task file under backlog/tasks/ '
                            f'and nothing else; it holds {tracked + [f"?? {p}" for p in new]}; nothing was written')
        path = new[0]
        target = Path(project, *path.split('/'))
        data = target.read_bytes()
        target.unlink()  # write_commit writes the file itself (an untracked file is in its way)
        try:
            commit = _commit(repo, {path: data}, TASK_MESSAGE, identity, head)
        except BaseException:
            if not target.exists():
                target.write_bytes(data)
            raise
    return {'operation': 'commit-task', 'result': 'committed', 'commit': commit, 'parent': head, 'written': [path]}


def _changes(before, after) -> tuple[list, list, list]:
    return (sorted(p for p in after if p in before and after[p] != before[p]),
            sorted(p for p in after if p not in before), sorted(p for p in before if p not in after))


def sequence_report(project) -> dict:
    """The clone's main against the sequence C0 to C3 (see the module's text); read only."""
    problems, names = [], ('C0', 'C1', 'C2', 'C3')
    with _open(project, work_tree=False) as repo:
        tip = repo.commit(BRANCH)
        if tip is None:
            raise DemoError('SEQUENCE_ABSENT', f'{project} has no branch main')
        chain = [tip]
        while len(chain) <= len(names):
            parents = _parents(repo, chain[-1])
            if len(parents) > 1:
                problems.append(f'{chain[-1]} is a merge')
            if not parents:
                break
            chain.append(parents[0])
        if len(chain) != len(names):
            problems.append(f'main holds {len(chain) if len(chain) <= len(names) else "more than 4"} commits, not '
                            'exactly C0 to C3')
            return {'operation': 'sequence', 'complete': False, 'main': tip, 'problems': problems}
        commits = dict(zip(names, reversed(chain)))
        trees = {name: tree_files(repo, commit) for name, commit in commits.items()}
    template, design = template_files(), design_files()
    if trees['C0'] != template:
        problems.append('C0 is not the initial content: ' + json.dumps(_changes(template, trees['C0'])))
    if trees['C1'] != {**trees['C0'], **design} or set(design) & set(trees['C0']):
        problems.append('C1 is not C0 with the placement: ' + json.dumps(_changes(trees['C0'], trees['C1'])))
    changed, added, removed = _changes(trees['C1'], trees['C2'])
    if changed != sorted(RECORDER_CHANGES) or removed or len(added) != 1 or not DECISION_FILE.fullmatch(added[0]):
        problems.append(f'C2 is not the acceptance recorder\'s commit: changed {changed}, added {added}, removed '
                        f'{removed}')
    changed, added, removed = _changes(trees['C2'], trees['C3'])
    if changed or removed or len(added) != 1 or not TASK_FILE.fullmatch(added[0]):
        problems.append(f'C3 is not one task file: changed {changed}, added {added}, removed {removed}')
    return {'operation': 'sequence', 'complete': not problems, 'main': tip, 'commits': commits,
            'task_file': added[0] if len(added) == 1 else None, 'problems': problems}


# ---------------------------------------------------------------------------- the inputs of the other commands


def statement(harness=REPO) -> dict:
    """The statement record-from-log takes, checked against the harness's committed log first."""
    A = _acceptance_recorder()
    try:
        found = A.read_log_entry(harness, STATEMENT_ANCHOR)
    except A.RecorderError as exc:
        raise DemoError(exc.code, str(exc)) from None
    if not A.verbatim_admits(found.entry, STATEMENT_TEXT):
        raise DemoError('STATEMENT_OUTSIDE_VERBATIM', f'the statement is not wholly inside the Owner\'s block of '
                        f'{STATEMENT_ANCHOR} at {found.revision}')
    return {'text': STATEMENT_TEXT, 'attributedTo': 'owner', 'channel': STATEMENT_CHANNEL,
            'reference': STATEMENT_REFERENCE}


def plan(outcome) -> dict:
    """The planning map of the change's one task, carrying OUTCOME, checked by the planning adapter."""
    P = _planning()
    data = {'format': P.PLAN_FORMAT, 'change': CHANGE, 'tasks': [dict(TASK, outcome=outcome)]}
    try:
        P.load_plan(data)
    except P.PlanningError as exc:
        raise DemoError(exc.code, exc.message) from None
    return data


def _write_new(path, data) -> str:
    path = Path(path)
    try:
        with open(path, 'x', encoding='utf-8', newline='\n') as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    except OSError as exc:
        raise DemoError('OUT_UNWRITABLE', f'{path}: {type(exc).__name__}: a new file in an existing directory')
    return str(path)


def main(argv=None, out=None, err=None) -> int:
    parser = argparse.ArgumentParser(prog='demo_repository.py', description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('files', help='what seed and place write, by path and sha256; reads only')
    p = sub.add_parser('seed', help='a new bare repository whose main is C0, the initial content')
    p.add_argument('--repository', required=True, help='the new bare repository (its name ends aieh-d1-demo.git)')
    p.add_argument('--identity', required=True, help='the commit identity, "Name <email>"')
    for name in ('place', 'commit-task'):
        p = sub.add_parser(name, help=f'{name}: one commit in the clone PROJECT, in process')
        p.add_argument('--project', required=True, help='the demo repository clone\'s work tree root')
        p.add_argument('--identity', required=True, help='the commit identity, "Name <email>"')
    p = sub.add_parser('sequence', help='the clone\'s main against C0 to C3; reads only')
    p.add_argument('--project', required=True)
    p = sub.add_parser('verify-placement', help='the change at COMMIT against the placement; reads only')
    p.add_argument('--project', required=True)
    p.add_argument('--commit', required=True, help='a full commit id')
    p = sub.add_parser('statement', help='write the statement record-from-log takes (checked first)')
    p.add_argument('--out', required=True, help='a new file')
    p.add_argument('--harness', default=str(REPO), help='the harness repository whose committed log is read')
    p = sub.add_parser('plan', help='write the planning map of the change\'s one task')
    p.add_argument('--outcome', required=True, help='outcome:<uuid>@<commit>, as record-from-log printed it')
    p.add_argument('--out', required=True, help='a new file')
    args = parser.parse_args(argv)
    out, err = out or sys.stdout, err or sys.stderr
    if out is sys.stdout and hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')
    code = 0
    try:
        if args.command == 'files':
            result = files_report()
        elif args.command == 'seed':
            result = seed(args.repository, args.identity)
        elif args.command == 'place':
            result = place(args.project, args.identity)
        elif args.command == 'commit-task':
            result = commit_task(args.project, args.identity)
        elif args.command == 'sequence':
            result = sequence_report(args.project)
            code = 0 if result['complete'] else 1
        elif args.command == 'verify-placement':
            result = placement_report(args.project, args.commit)
            code = 0 if result['identical'] else 1
        elif args.command == 'statement':
            result = {'operation': 'statement', 'written': _write_new(args.out, statement(args.harness))}
        else:
            result = {'operation': 'plan', 'written': _write_new(args.out, plan(args.outcome))}
    except DemoError as exc:
        err.write(f'demo-repository: {exc}\n')
        return 2 if exc.refusal else 1
    except ValueError as exc:  # an argument the repository module refuses (an identity, a path)
        err.write(f'demo-repository: REFUSED: {exc}\n')
        return 2
    except Exception as exc:  # a recorder's own refusal (input_recorder.RecorderError and the like), by its text
        if type(exc).__name__ != 'RecorderError':
            raise
        err.write(f'demo-repository: {exc}\n')
        return 2
    out.write(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    return code


if __name__ == '__main__':
    sys.exit(main())
