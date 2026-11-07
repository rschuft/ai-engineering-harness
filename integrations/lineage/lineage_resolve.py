"""Read-only lineage resolvers and the command line (plan leaf P-03.1).

Resolvers exist only where a local authority and adapter already exist:

- ``design``: the P-02.1 OpenSpec source pointer, re-resolved from git objects by
  ``planning_adapter.resolve_pointer``;
- ``work``: Backlog.md's own ``task view --json`` and ``task list --json`` through the
  P-02 wrapper, restricted to those two commands; a pinned reference is read by
  Backlog.md from an export of that commit;
- ``commit``: git, in a registered local clone;
- ``effect-receipt``: the F-05.2 effects store's read methods, on a store the caller
  opens (its custody decides who may).

Every other kind answers through the ``Registry``: ``authority-unavailable`` with the
leaf that supplies it, or ``unsupported-kind`` when its identity is not settled.

Usage (from the repository root):
    python -I -B integrations/lineage/lineage_resolve.py schema
    python -I -B integrations/lineage/lineage_resolve.py parse REF [REF ...]
    python -I -B integrations/lineage/lineage_resolve.py resolve REF [REF ...] [--current]
        [--project DIR] [--backlog CMD] [--repo NAME=DIR ...] [--effects-root DIR [--effects-principal SID]]

Exit status: 0 PASS (every reference parsed or resolved), 1 FAIL (a malformed
reference, a schema problem, or any outcome other than resolved), 2 could not run.
Standard library only, plus git and the tools named.
"""
import argparse
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load(name, path):
    import importlib.util
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


lineage = _load('lineage', HERE / 'lineage.py')
planning = lineage.planning
L = lineage


def _effects_module():
    """The F-05.2 effects store library (loaded on first use)."""
    return _load('effects_store', REPO / 'integrations' / 'effects' / 'effects_store.py')


def _git(project):
    """The P-02.1 read-only git access, or the reason it is unavailable."""
    try:
        return planning.Git(project), None
    except (planning.CannotRun, OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# design

class DesignResolver:
    """OpenSpec design artifacts in the project repository (P-02.1 pointers)."""
    kind = 'design'
    authority = 'OpenSpec'
    outcomes = frozenset({L.RESOLVED, L.MISSING, L.REVISION_MISMATCH, L.DIGEST_MISMATCH, L.AUTHORITY_UNAVAILABLE})
    _MAP = {'POINTER_REVISION_MISSING': L.REVISION_MISMATCH, 'POINTER_ARTIFACT_MISSING': L.MISSING,
            'POINTER_DIGEST_MISMATCH': L.DIGEST_MISMATCH}

    def __init__(self, project, current_revision='HEAD'):
        self.project = Path(project)
        self.current_revision = current_revision

    def resolve(self, reference):
        git, why = _git(self.project)
        if git is None:
            return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, 'PROJECT_UNAVAILABLE', why)
        try:
            planning.resolve_pointer(git, reference.text)
        except planning.PlanningError as exc:
            outcome = self._MAP.get(exc.code, L.AUTHORITY_UNAVAILABLE)
            return L.answer(reference, outcome, self.authority, exc.code, exc.message,
                            observed_digest=exc.details.get('actual'))
        except (subprocess.TimeoutExpired, OSError) as exc:
            return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, 'GIT_FAILED', str(exc))
        return L.answer(reference, L.RESOLVED, self.authority, observed_revision=reference.revision,
                        observed_digest=reference.digest)

    def current(self, reference):
        git, why = _git(self.project)
        if git is None:
            return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, 'PROJECT_UNAVAILABLE', why,
                            query='current')
        try:
            commit = git.commit(self.current_revision)
            if commit is None:
                return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, 'GIT_FAILED',
                                f'the project has no commit {self.current_revision!r}', query='current')
            pointer = planning.make_pointer(git, reference.change, reference.artifact, commit)
        except planning.PlanningError as exc:
            outcome = L.MISSING if exc.code == 'POINTER_ARTIFACT_MISSING' else L.AUTHORITY_UNAVAILABLE
            return L.answer(reference, outcome, self.authority, exc.code, exc.message, query='current')
        except (subprocess.TimeoutExpired, OSError) as exc:
            return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, 'GIT_FAILED', str(exc),
                            query='current')
        return L.answer(reference, L.RESOLVED, self.authority, detail=f'{self.current_revision} is {commit}',
                        observed_revision=pointer.revision, observed_digest=pointer.digest, query='current')


# ---------------------------------------------------------------------------
# work

class ReadOnlyBacklog(planning.Backlog):
    """The P-02 Backlog.md wrapper, limited to the two read commands."""
    READ_COMMANDS = {('task', 'list'), ('task', 'view')}

    def run(self, *args):
        if tuple(args[:2]) not in self.READ_COMMANDS:
            raise planning.PlanningError('ADAPTER_REFUSED', f'the lineage resolver only reads: backlog {" ".join(args[:2])}')
        return super().run(*args)


class WorkResolver:
    """Backlog.md tasks, read by Backlog.md itself; never a status."""
    kind = 'work'
    authority = 'Backlog.md'
    outcomes = frozenset({L.RESOLVED, L.MISSING, L.REVISION_MISMATCH, L.AMBIGUOUS, L.AUTHORITY_UNAVAILABLE})

    def __init__(self, project, backlog_argv):
        self.project = Path(project)
        self.backlog_argv = list(backlog_argv)

    def resolve(self, reference):
        if reference.revision is None:
            return self._read(self.project, reference, None, 'reference')
        git, why = _git(self.project)
        if git is None:
            return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, 'PROJECT_UNAVAILABLE', why)
        try:
            commit = git.commit(reference.revision)
            if commit != reference.revision:
                return L.answer(reference, L.REVISION_MISMATCH, self.authority, 'WORK_REVISION_MISSING',
                                f'the project repository has no commit {reference.revision}')
            with tempfile.TemporaryDirectory(prefix='aieh-lineage-work-') as tmp:
                with tarfile.open(fileobj=io.BytesIO(git.archive(commit, '.')), mode='r:') as tar:
                    tar.extractall(tmp, filter='data')
                return self._read(Path(tmp), reference, commit, 'reference')
        except planning.PlanningError as exc:
            return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, exc.code, exc.message)
        except (subprocess.TimeoutExpired, OSError, tarfile.TarError) as exc:
            return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, 'PROJECT_UNAVAILABLE', str(exc))

    def current(self, reference):
        return self._read(self.project, reference, None, 'current')

    def _read(self, directory, reference, commit, query):
        def unavailable(code, detail):
            return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, code, detail, query=query)

        if not directory.is_dir():
            return unavailable('PROJECT_UNAVAILABLE', f'not a directory: {directory}')
        backlog = ReadOnlyBacklog(self.backlog_argv, directory)
        task, view_error = None, None
        try:
            task = backlog.view(reference.task)
        except planning.PlanningError as exc:
            view_error = exc
        except (subprocess.TimeoutExpired, OSError) as exc:
            return unavailable('BACKLOG_UNAVAILABLE', str(exc))
        try:
            listed = backlog.list_tasks()
        except planning.PlanningError as exc:
            return unavailable('BACKLOG_LIST_FAILED', f'Backlog.md did not list its tasks, so the task id cannot '
                               f'be shown unique: {exc.message}')
        except (subprocess.TimeoutExpired, OSError) as exc:
            return unavailable('BACKLOG_UNAVAILABLE', str(exc))
        matches = [t for t in listed if t['id'].upper() == reference.task.upper()]
        where = f' at {commit}' if commit else ''
        if len(matches) > 1:
            return L.answer(reference, L.AMBIGUOUS, self.authority, 'WORK_AMBIGUOUS',
                            f'Backlog.md lists {len(matches)} tasks with the id {reference.task}{where}', query=query)
        if task is None:
            if matches or view_error.code != 'BACKLOG_FAILED':
                return unavailable('BACKLOG_VIEW_FAILED', f'{view_error.code}: {view_error.message}')
            return L.answer(reference, L.MISSING, self.authority, 'WORK_MISSING',
                            f'Backlog.md has no task {reference.task}{where}: {view_error.message}', query=query)
        return L.answer(reference, L.RESOLVED, self.authority,
                        detail=f'Backlog.md task {task["id"]}{where}', observed_revision=commit, query=query)


# ---------------------------------------------------------------------------
# commit

def _object_type(repository, oid):
    result = subprocess.run(['git', '-C', str(repository), 'cat-file', '-t', oid], capture_output=True,
                            stdin=subprocess.DEVNULL, timeout=planning.TOOL_TIMEOUT_S, env=planning.tool_env())
    return result.stdout.decode('ascii', 'replace').strip() if result.returncode == 0 else None


class CommitResolver:
    """Exact commits in registered local clones (repository name -> directory)."""
    kind = 'commit'
    authority = 'Git'
    outcomes = frozenset({L.RESOLVED, L.MISSING, L.AUTHORITY_UNAVAILABLE})

    def __init__(self, repositories):
        self.repositories = {name: Path(path) for name, path in dict(repositories).items()}

    def resolve(self, reference, query='reference'):
        path = self.repositories.get(reference.repository)
        if path is None:
            return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, 'REPOSITORY_NOT_REGISTERED',
                            f'no local clone is registered for {reference.repository}', query=query)
        git, why = _git(path)
        if git is None:
            return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, 'REPOSITORY_UNAVAILABLE', why,
                            query=query)
        try:
            commit = git.commit(reference.commit)
            kind = _object_type(path, reference.commit) if commit is None else 'commit'
        except (planning.PlanningError, subprocess.TimeoutExpired, OSError) as exc:
            return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, 'GIT_FAILED', str(exc), query=query)
        if commit is None:
            if kind:
                return L.answer(reference, L.MISSING, self.authority, 'COMMIT_NOT_A_COMMIT',
                                f'{reference.commit} is a {kind}, not a commit', query=query)
            return L.answer(reference, L.MISSING, self.authority, 'COMMIT_MISSING',
                            f'{reference.repository} has no commit {reference.commit}', query=query)
        if commit != reference.commit:
            return L.answer(reference, L.MISSING, self.authority, 'COMMIT_ID_MISMATCH',
                            f'{reference.commit} is not a full object id there (it abbreviates {commit})',
                            query=query)
        return L.answer(reference, L.RESOLVED, self.authority, observed_revision=commit, query=query)

    def current(self, reference):
        return self.resolve(reference, 'current')  # a commit is immutable: its current revision is itself


# ---------------------------------------------------------------------------
# effect-receipt

class _ReadOnlyEffects:
    """The only effects-store methods a resolver may call."""

    def __init__(self, store):
        self._store = store

    def verify_chain(self):
        return self._store.verify_chain()

    def get(self, effect_key):
        return self._store.get(effect_key)

    def events(self, effect_key):
        return self._store.events(effect_key)

    def open_epochs(self):
        return self._store.open_epochs()

    def high_water_mark(self):
        return self._store.high_water_mark()


class EffectReceiptResolver:
    """Receipts in the privileged effects store, read through its own library.

    ``open_store`` opens the store and returns an ``EffectsStore`` (a context manager).
    Its location and custody checks run there: a process the store's custody does not
    admit is refused, and the answer is authority-unavailable.
    """
    kind = 'effect-receipt'
    authority = 'effects store'
    outcomes = frozenset({L.RESOLVED, L.MISSING, L.REVISION_MISMATCH, L.DIGEST_MISMATCH, L.AUTHORITY_UNAVAILABLE})

    def __init__(self, open_store, effects=None):
        self.open_store = open_store
        self.effects = effects or _effects_module()

    @classmethod
    def for_root(cls, root, principal=None):
        """The live location policy and custody template, as the effects command line uses."""
        effects = _effects_module()
        return cls(lambda: effects.open_effects_store(root, principal=principal), effects)

    def resolve(self, reference):
        return self._resolve(reference, 'reference')

    def current(self, reference):
        return self._resolve(L.EffectReceiptRef(reference.effect_key), 'current', reference)

    def _resolve(self, reference, query, asked=None):
        asked = asked or reference

        def say(outcome, code=None, detail='', **extra):
            return L.answer(asked, outcome, self.authority, code, detail, query=query, **extra)

        try:
            with self.open_store() as opened:
                store = _ReadOnlyEffects(opened)
                store.verify_chain()
                receipt = store.get(reference.effect_key)
                if receipt is None:
                    epochs = [e['epoch_id'] for e in store.open_epochs()]
                    return say(L.MISSING, 'EFFECT_RECEIPT_MISSING',
                               'the effects store holds no receipt with this key; that is not evidence that the '
                               'effect did not happen (decision 0004, point 7)'
                               + (f'; restore epochs {epochs} are open' if epochs else ''))
                events = {e['seq']: e for e in store.events(reference.effect_key)}
                if not events:
                    return say(L.AUTHORITY_UNAVAILABLE, 'EFFECTS_CHAIN_INVALID',
                               'the receipt has no journal event')
                if reference.seq is None:
                    # The receipt's position is its last journal event; verify_chain has
                    # checked that the receipt's state is that event's.
                    head = events[max(events)]
                    return say(L.RESOLVED, detail=f'state {receipt.state}',
                               observed_revision=str(head['seq']), observed_digest=head['hash'])
                event = events.get(reference.seq)
                if event is None:
                    return say(L.REVISION_MISMATCH, 'EFFECT_EVENT_MISSING',
                               f'the journal holds no event {reference.seq} of this receipt (its events: '
                               f'{sorted(events)}; high-water mark {store.high_water_mark()})')
                if event['hash'] != reference.event_hash:
                    return say(L.DIGEST_MISMATCH, 'EFFECT_EVENT_DIGEST_MISMATCH',
                               f'event {reference.seq} has hash {event["hash"]}',
                               observed_revision=str(reference.seq), observed_digest=event['hash'])
                return say(L.RESOLVED, detail=f'state {event["to_state"]} as of event {reference.seq}',
                           observed_revision=str(reference.seq), observed_digest=event['hash'])
        except self.effects.ChainError as exc:
            return say(L.AUTHORITY_UNAVAILABLE, 'EFFECTS_CHAIN_INVALID', f'the journal does not verify: {exc}')
        except (self.effects.StoreError, self.effects.CustodyRefused, sqlite3.Error, OSError) as exc:
            return say(L.AUTHORITY_UNAVAILABLE, 'EFFECTS_STORE_UNAVAILABLE', f'{type(exc).__name__}: {exc}')


# ---------------------------------------------------------------------------
# Registry and command line

def build_registry(*, project=None, backlog=None, repositories=None, open_effects=None, schema=None):
    """A Registry with the resolvers the given configuration allows.

    ``project`` enables design (and, with ``backlog``, an argv prefix, work);
    ``repositories`` maps repository names to local clones for commit;
    ``open_effects`` opens the effects store for effect-receipt.
    """
    resolvers = []
    if project is not None:
        resolvers.append(DesignResolver(project))
        if backlog is not None:
            resolvers.append(WorkResolver(project, backlog))
    if repositories:
        resolvers.append(CommitResolver(repositories))
    if open_effects is not None:
        resolvers.append(open_effects if isinstance(open_effects, EffectReceiptResolver)
                         else EffectReceiptResolver(open_effects))
    return L.Registry(resolvers, schema)


class CannotRun(Exception):
    pass


def _repositories(values):
    out = {}
    for value in values:
        name, sep, path = value.partition('=')
        if not sep or not name or not path:
            raise CannotRun(f'--repo takes NAME=DIR: {value!r}')
        out[name] = Path(path)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('schema', help='check the schema against the typed references and list the kinds')
    p_parse = sub.add_parser('parse', help='parse references and print their typed fields')
    p_parse.add_argument('references', nargs='+')
    p_resolve = sub.add_parser('resolve', help='resolve references (read-only)')
    p_resolve.add_argument('references', nargs='+')
    p_resolve.add_argument('--current', action='store_true', help='the identity at the current revision')
    p_resolve.add_argument('--project', type=Path)
    p_resolve.add_argument('--backlog')
    p_resolve.add_argument('--repo', action='append', default=[])
    p_resolve.add_argument('--effects-root', type=Path)
    p_resolve.add_argument('--effects-principal')
    args = parser.parse_args(argv)
    try:
        if args.command == 'schema':
            schema = L.load_schema()
            problems = L.check_schema(schema)
            for entry in schema['kinds']:
                print(f'{entry["kind"]:15} {entry["status"]:22} {entry["authority"]["name"]}')
            for problem in problems:
                print(f'FAIL {problem}', file=sys.stderr)
            return 1 if problems else 0
        if args.command == 'parse':
            failed = False
            for text in args.references:
                try:
                    ref = L.parse(text)
                except L.MalformedReference as exc:
                    print(f'FAIL {exc.code}: {exc.message}', file=sys.stderr)
                    failed = True
                    continue
                fields = {k: v for k, v in vars(ref).items()}
                print(json.dumps({'reference': ref.text, 'kind': ref.kind, 'pinned': ref.pinned,
                                  'identity': list(ref.identity()), 'fields': fields}))
            return 1 if failed else 0
        if args.backlog and args.project is None:
            raise CannotRun('--backlog needs --project')
        if args.effects_principal and args.effects_root is None:
            raise CannotRun('--effects-principal needs --effects-root')
        backlog = planning.tool_argv(args.backlog) if args.backlog else None
        effects = (EffectReceiptResolver.for_root(args.effects_root, args.effects_principal)
                   if args.effects_root else None)
        registry = build_registry(project=args.project, backlog=backlog, repositories=_repositories(args.repo),
                                  open_effects=effects)
        failed = False
        for text in args.references:
            try:
                result = registry.current(text) if args.current else registry.resolve(text)
            except L.MalformedReference as exc:
                print(f'FAIL {exc.code}: {exc.message}', file=sys.stderr)
                failed = True
                continue
            print(json.dumps(result.to_json()))
            if not result.resolved:
                failed = True
                print(f'FAIL {result.reference}: {result.outcome} {result.code}: {result.detail}', file=sys.stderr)
        return 1 if failed else 0
    except (CannotRun, planning.CannotRun) as exc:
        print(f'ERROR {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
