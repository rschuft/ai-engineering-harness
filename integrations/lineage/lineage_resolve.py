"""Read-only lineage resolvers and the command line (plan leaf P-03.1).

Resolvers exist only where a local authority and adapter already exist:

- ``design``: the P-02.1 OpenSpec source pointer, re-resolved from git objects by
  ``planning_adapter.resolve_pointer``;
- ``objective``: the outcome id declared under ``x-outcomes`` in a change's
  ``.openspec.yaml`` and cross-checked against that change's intent record, from git
  objects only (decision 0008);
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
import contextlib
import contextvars
import hashlib
import io
import json
import re
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


def _open_git(project):
    try:
        return planning.Git(project), None
    except (planning.CannotRun, OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)


# The git access of the running traversal (git_scope), or None.
_SCOPE = contextvars.ContextVar('lineage_git_scope', default=None)


@contextlib.contextmanager
def git_scope():
    """One traversal's git access (plan leaf F-09.4). Inside it, ``_git(project)`` gives every
    resolver the same ``planning_adapter.Git`` per project, with one read session open: one
    ``git cat-file --batch`` reader, and memos of immutable objects and of the revisions it
    resolved (a snapshot for this traversal). When the block ends, normally or by an
    exception, every session is closed and its reader process ended; nothing is kept for the
    next traversal. A scope inside a scope is the outer one."""
    if _SCOPE.get() is not None:
        yield
        return
    with contextlib.ExitStack() as stack:
        token = _SCOPE.set({'stack': stack, 'projects': {}})
        try:
            yield
        finally:
            _SCOPE.reset(token)


def _git(project):
    """The P-02.1 read-only git access, or the reason it is unavailable: within a traversal
    (git_scope), the traversal's own, opened once per project."""
    scope = _SCOPE.get()
    if scope is None:
        return _open_git(project)
    key = str(Path(project))
    if key not in scope['projects']:
        git, why = _open_git(project)
        if git is not None:
            scope['stack'].enter_context(git.session())
        scope['projects'][key] = (git, why)
    return scope['projects'][key]


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
            with git.session():
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
# objective (decision 0008)

def _intent_module():
    """The intent-record/v1 parser of P-01.1 (tools/check_intent_record.py)."""
    return _load('aieh_check_intent_record', REPO / 'tools' / 'check_intent_record.py')


X_OUTCOMES = 'x-outcomes'
OUTCOME_FIELDS = ('item', 'acceptance')
_ACTIVE_META = re.compile(r'^openspec/changes/(?P<change>[^/]+)/\.openspec\.yaml$')
_ARCHIVED_META = re.compile(r'^openspec/changes/archive/(?P<change>[^/]+)/\.openspec\.yaml$')
_OBJECTIVE_ITEM = re.compile(r'^O[1-9][0-9]*$')
_ENTRY_KEY = re.compile(rf'^(?P<id>{L.UUID}):$')
_FIELD = re.compile(r'^(?P<key>[a-z]+): (?P<value>\S+)$')


class OutcomeMetadataInvalid(ValueError):
    pass


def read_x_outcomes(data):
    """The ``x-outcomes`` declarations of one ``.openspec.yaml``: {id: {item, acceptance}}.

    A strict reader of exactly one shape: a top-level ``x-outcomes:`` block mapping whose
    keys are lower-case UUIDs, each mapping exactly ``item: O<n>`` and ``acceptance:
    <reference>`` as plain scalars. Blank and whole-line comment lines are allowed. Any
    other shape (a flow mapping, a duplicate id or key, an unknown key, a tab, a trailing
    comment, quoting, a third level) is refused. A file without the key declares nothing.
    """
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise OutcomeMetadataInvalid('not UTF-8') from None
    lines = [line.rstrip('\r') for line in text.split('\n')]
    mentions = [i for i, line in enumerate(lines) if X_OUTCOMES in line]
    if not mentions:
        return {}
    heads = [i for i in mentions if lines[i].rstrip(' ') == f'{X_OUTCOMES}:']
    if len(heads) != 1 or len(mentions) != 1:
        raise OutcomeMetadataInvalid(f'{X_OUTCOMES} must appear once, as a top-level "{X_OUTCOMES}:" block')
    intent = _intent_module()
    out, entry, entry_indent, field_indent = {}, None, None, None
    for number, line in enumerate(lines[heads[0] + 1:], heads[0] + 2):
        stripped = line.strip(' ')
        if stripped == '' or stripped.startswith('#'):
            continue
        indent = len(line) - len(line.lstrip(' '))
        if line[indent:indent + 1] == '\t':
            raise OutcomeMetadataInvalid(f'line {number}: tab indentation')
        if indent == 0:
            break  # the next top-level key ends the block
        # A tab, a trailing comment, quoting or any other value with white space fails the
        # patterns below.
        if entry_indent is None:
            entry_indent = indent
        if indent == entry_indent:
            match = _ENTRY_KEY.match(stripped)
            if not match:
                raise OutcomeMetadataInvalid(f'line {number}: expected "<lower-case uuid>:"')
            if match['id'] in out:
                raise OutcomeMetadataInvalid(f'line {number}: {match["id"]} is declared twice')
            entry = out[match['id']] = {}
            continue
        if entry is None or indent < entry_indent:
            raise OutcomeMetadataInvalid(f'line {number}: unexpected indentation')
        if field_indent is None:
            field_indent = indent
        if indent != field_indent:
            raise OutcomeMetadataInvalid(f'line {number}: unexpected indentation')
        match = _FIELD.match(stripped)
        if not match:  # an unknown key fails the exactly-item-and-acceptance check below
            raise OutcomeMetadataInvalid(f'line {number}: expected item: O<n> or acceptance: <reference>')
        if match['key'] in entry:
            raise OutcomeMetadataInvalid(f'line {number}: {match["key"]} is repeated')
        entry[match['key']] = match['value']
    if not out:
        raise OutcomeMetadataInvalid(f'{X_OUTCOMES} declares nothing')
    for outcome, entry in out.items():
        if set(entry) != set(OUTCOME_FIELDS):
            raise OutcomeMetadataInvalid(f'{outcome} must declare exactly item and acceptance')
        if not _OBJECTIVE_ITEM.match(entry['item']):
            raise OutcomeMetadataInvalid(f'{outcome}: item must be an Objective item id (O<n>)')
        if not intent.REFERENCE.match(entry['acceptance']) or entry['acceptance'].startswith('missing:'):
            raise OutcomeMetadataInvalid(f'{outcome}: acceptance must be an intent-record reference')
    return out


class ObjectiveResolver:
    """Accepted objectives by outcome id, read from the project's OpenSpec tree in git
    objects only (decision 0008, point 6). It never runs openspec or reads the working tree."""
    kind = 'objective'
    authority = 'OpenSpec'
    outcomes = frozenset({L.RESOLVED, L.MISSING, L.REVISION_MISMATCH, L.AMBIGUOUS, L.AUTHORITY_UNAVAILABLE})

    def __init__(self, project, current_revision='HEAD'):
        self.project = Path(project)
        self.current_revision = current_revision

    def resolve(self, reference):
        return self._ask(reference, 'reference')

    def current(self, reference):
        return self._ask(reference, 'current')

    def _ask(self, reference, query):
        def say(outcome, code=None, detail='', **extra):
            return L.answer(reference, outcome, self.authority, code, detail, query=query, **extra)

        git, why = _git(self.project)
        if git is None:
            return say(L.AUTHORITY_UNAVAILABLE, 'PROJECT_UNAVAILABLE', why)
        try:
            with git.session():
                if query == 'reference' and reference.revision is not None:
                    commit = git.commit(reference.revision)
                    if commit != reference.revision:
                        return say(L.REVISION_MISMATCH, 'OUTCOME_REVISION_MISSING',
                                   f'the project repository has no commit {reference.revision}')
                else:
                    commit = git.commit(self.current_revision)
                    if commit is None:
                        return say(L.AUTHORITY_UNAVAILABLE, 'GIT_FAILED',
                                   f'the project has no commit {self.current_revision!r}')
                return self._read(git, commit, reference, say)
        except OutcomeMetadataInvalid as exc:
            return say(L.AUTHORITY_UNAVAILABLE, 'OUTCOME_METADATA_INVALID', str(exc))
        except planning.PlanningError as exc:
            return say(L.AUTHORITY_UNAVAILABLE, 'GIT_FAILED', exc.message)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return say(L.AUTHORITY_UNAVAILABLE, 'GIT_FAILED', str(exc))

    def _read(self, git, commit, reference, say):
        metas = [path for path in git.files(commit, 'openspec/changes')
                 if (_ACTIVE_META.match(path) and _ACTIVE_META.match(path)['change'] != 'archive')
                 or _ARCHIVED_META.match(path)]
        declared = []
        for path in sorted(metas):
            try:
                outcomes = read_x_outcomes(git.blob(commit, path))
            except OutcomeMetadataInvalid as exc:
                raise OutcomeMetadataInvalid(f'{path} at {commit}: {exc}') from None
            if reference.outcome in outcomes:
                declared.append((path, outcomes[reference.outcome]))
        if not declared:
            return say(L.MISSING, 'OUTCOME_MISSING', f'no change declares {reference.outcome} at {commit}')
        if len(declared) > 1:
            return say(L.AMBIGUOUS, 'OUTCOME_AMBIGUOUS',
                       f'{len(declared)} changes declare {reference.outcome} at {commit}: '
                       + ', '.join(path for path, _ in declared))
        path, declaration = declared[0]
        change = path.rsplit('/', 1)[0]
        proposal = f'{change}/proposal.md'
        if git.object_type(commit, proposal) != 'blob':
            raise OutcomeMetadataInvalid(f'{proposal} does not exist at {commit}')
        data = git.blob(commit, proposal)
        intent = _intent_module()
        try:
            record, problems = intent._Parser(data).parse()
        except UnicodeDecodeError:
            raise OutcomeMetadataInvalid(f'{proposal} at {commit} is not UTF-8') from None
        if problems:
            raise OutcomeMetadataInvalid(f'{proposal} at {commit} is not a readable intent record: '
                                         + '; '.join(str(p) for p in problems[:3]))
        item = record.items.get(declaration['item'])
        why = None
        if item is None or item.section != 'Objective':
            why = f'{proposal} has no Objective item {declaration["item"]}'
        elif item.fields.get('authority') != 'accepted':
            why = f'{declaration["item"]} is {item.fields.get("authority")!r}, not accepted'
        elif item.fields.get('acceptance') != declaration['acceptance']:
            why = (f'{declaration["item"]} has acceptance {item.fields.get("acceptance")!r}; the declaration '
                   f'says {declaration["acceptance"]!r}')
        if why:
            return say(L.MISSING, 'OUTCOME_NOT_ACCEPTED', why, observed_revision=commit)
        criteria = [ac.id for ac in record.sections.get('Acceptance Criteria', [])
                    if ac.fields.get('authority') == 'accepted'
                    and item.id in intent._split_list(ac.fields.get('source', ''))]
        facts = {'change': change, 'item': item.id, 'statement': item.fields.get('statement'),
                 'acceptance': item.fields['acceptance'], 'source': intent._split_list(item.fields.get('source', '')),
                 'acceptance_criteria': criteria}
        return say(L.RESOLVED, detail=f'{item.id} of {change}', observed_revision=commit,
                   observed_digest=hashlib.sha256(data).hexdigest(), facts=facts)


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
            with git.session():
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
            with git.session():
                commit = git.commit(reference.commit)
                kind = git.object_kind(reference.commit) if commit is None else 'commit'
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
        resolvers.append(ObjectiveResolver(project))
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
