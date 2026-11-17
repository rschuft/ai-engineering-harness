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
  opens (its custody decides who may);
- ``message`` and ``conversation``: the Owner conversation store (U-02.2; decision 0025
  point 6), opened read-only; a message's content is checked with
  ``lineage.check_message_content``, unchanged;
- ``attempt``: the dispatched attempt's conversation at the Agent Server (E-01.5), its record read
  from the integration store opened read-only and the server asked one ``GET`` through the
  route-checked client over the attempt's pinned route allowlist; its authority mode is the
  attempt's bound declaration and the answering transport's, which must agree. Configured only
  with a transport: the command line has none (against a live server: E-01.6's).

Every other kind answers through the ``Registry``: ``authority-unavailable`` with the
leaf that supplies it, or ``unsupported-kind`` when its identity is not settled.

Usage (from the repository root):
    python -I -B integrations/lineage/lineage_resolve.py schema
    python -I -B integrations/lineage/lineage_resolve.py parse REF [REF ...]
    python -I -B integrations/lineage/lineage_resolve.py resolve REF [REF ...] [--current]
        [--project DIR] [--backlog CMD] [--repo NAME=DIR ...] [--effects-root DIR [--effects-principal SID]]
        [--conversations DB]

Exit status: 0 PASS (every reference parsed or resolved), 1 FAIL (a malformed
reference, a schema problem, or any outcome other than resolved), 2 could not run.
Standard library only, plus the shared repository-access module (Dulwich; run it with the tools
interpreter) and the tools named.
"""
import argparse
import functools
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
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


def _integration_store_module():
    return _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')


def _dispatch_module():
    """The dispatcher's record readers and route-checked client (``dispatch_inputs``; loaded on first use, only by
    the attempt resolver)."""
    return _load('dispatch_inputs', REPO / 'integrations' / 'dispatch' / 'dispatch_inputs.py')


def _git(project):
    """The P-02.1 read-only repository access, or the reason it is unavailable: within an operation
    (``planning_adapter.operation``) the operation's own, one per project (plan leaf F-09.4)."""
    return planning.project_git(project)


def _operation(method):
    """A resolver entry point is one adapter operation (F-09.4): its repository reads share one
    work-tree check and one opened repository, and Backlog.md's reads are made once each; inside a
    traversal it is the traversal's operation."""
    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        with planning.operation():
            return method(*args, **kwargs)
    return wrapper


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

    @_operation
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

    @_operation
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

    @_operation
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

    @_operation
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
                # The commit's blob bytes (decision 0014 section 4), read by Backlog.md there.
                git.export_tree(commit, '.', tmp)
                return self._read(Path(tmp), reference, commit, 'reference')
        except planning.PlanningError as exc:
            return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, exc.code, exc.message)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return L.answer(reference, L.AUTHORITY_UNAVAILABLE, self.authority, 'PROJECT_UNAVAILABLE', str(exc))

    @_operation
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

    @_operation
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
# conversation and message: the Owner conversation store (plan leaf U-02.2; decision 0025, point 6)

def _conversation_module():
    """The Owner conversation store library (integrations/conversation; loaded on first use)."""
    return _load('aieh_conversation_store', REPO / 'integrations' / 'conversation' / 'conversation_store.py')


class ReadOnlyConversationStore:
    """The Owner conversation store's reads on a read-only connection.

    The store's own ``open_store`` migrates (a write transaction) and creates an absent file,
    so it is not used. As ``lineage_trace.ReadOnlyIntegrationStore`` does for the integration
    store: the existing file is opened with SQLite's ``mode=ro`` (``storecore.open_read_only``),
    ``query_only`` is set, and ``storecore.check_current`` verifies the store kind and its
    migrations without migrating; then the store's own checks run, read only
    (``conversation_store.verify``: its schema objects are exactly the migrations', and every
    stored content has its recorded sha256). An absent file, a database of another kind, one
    that would need a migration, an altered schema and a content that does not match its digest
    are each refused (``StoreError``) and nothing is changed. Only ``thread``, ``message`` and
    ``messages`` are exposed. As with any SQLite reader of a WAL database, the read may create or
    update the ``-wal`` and ``-shm`` sidecar files; no database page changes.
    """

    def __init__(self, path):
        cs = self.store_mod = _conversation_module()
        storecore = cs.storecore
        storecore.check_sqlite_version()
        resolved = storecore.check_local_path(Path(path))
        if not resolved.is_file():
            raise cs.StoreError(f'no Owner conversation store file: {resolved.name}')
        self._conn = storecore.open_read_only(resolved)
        try:
            self._conn.execute('PRAGMA query_only = ON')
            if self._conn.execute('PRAGMA query_only').fetchone()[0] != 1:
                raise cs.StoreError('the connection did not take query_only')
            self.version = storecore.check_current(self._conn, cs.KIND)
            cs.verify(self._conn)
            self._store = cs.ConversationStore(self._conn, resolved)
        except BaseException:
            self._conn.close()
            raise

    def thread(self, thread_id):
        return self._store.thread(thread_id)

    def message(self, thread_id, message_id):
        return self._store.message(thread_id, message_id)

    def messages(self, thread_id):
        return self._store.messages(thread_id)

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


STATEMENT_ROLE = 'user'      # an Owner statement: a user message, author owner (decision 0025 point 6)


class _ConversationStoreResolver:
    """What the message and conversation resolvers share: the store at ``path``, opened read-only
    for each question and closed after it."""
    authority = 'Owner conversation store'

    def __init__(self, path):
        self.path = Path(path)

    def _ask(self, reference, query, read):
        """READ(store, say) inside one read-only opening; a refused or failed store answers
        authority-unavailable (CONVERSATION_STORE_UNAVAILABLE)."""
        def say(outcome, code=None, detail='', **extra):
            return L.answer(reference, outcome, self.authority, code, detail, query=query, **extra)

        cs = _conversation_module()
        try:
            with ReadOnlyConversationStore(self.path) as store:
                return read(store, say)
        except cs.ConversationRefused as exc:     # a read the store refused: answered by READ itself
            raise AssertionError(f'unhandled store refusal {exc.code}') from None
        except (cs.StoreError, sqlite3.Error, OSError) as exc:
            return say(L.AUTHORITY_UNAVAILABLE, 'CONVERSATION_STORE_UNAVAILABLE', f'{type(exc).__name__}: {exc}')

    @staticmethod
    def _thread(store, thread_id, say):
        """The thread, or the missing answer (None, answer)."""
        cs = _conversation_module()
        try:
            return store.thread(thread_id), None
        except cs.ConversationRefused:
            return None, say(L.MISSING, 'CONVERSATION_MISSING',
                             f'the Owner conversation store has no thread {thread_id!r}')


class MessageResolver(_ConversationStoreResolver):
    """Owner statements: user messages of the Owner conversation store, read-only.

    The content is the message's durable bytes as the store keeps them (the UTF-8 bytes of its
    text as received), and the kind's rule is applied to them by ``lineage.check_message_content``,
    unchanged: a content digest or a span anchor must match. A user message is immutable (its one
    revision), so ``current`` applies the same check, with the same anchors, as ``resolve``. An
    assistant message is display state the shell wrote, never a statement: it answers missing
    (MESSAGE_NOT_A_STATEMENT)."""
    kind = 'message'
    outcomes = frozenset({L.RESOLVED, L.MISSING, L.DIGEST_MISMATCH, L.AUTHORITY_UNAVAILABLE})

    def resolve(self, reference):
        return self._ask(reference, 'reference', lambda store, say: self._read(store, say, reference))

    def current(self, reference):
        return self._ask(reference, 'current', lambda store, say: self._read(store, say, reference))

    def _statement(self, store, reference, say):
        """(StoredMessage, None) for an Owner statement, else (None, the missing answer)."""
        cs = _conversation_module()
        thread, missing = self._thread(store, reference.thread, say)
        if thread is None:
            return None, missing
        try:
            stored = store.message(reference.thread, reference.message)
        except cs.ConversationRefused:
            return None, say(L.MISSING, 'MESSAGE_MISSING',
                             f'thread {reference.thread} has no message {reference.message!r}')
        if stored.role != STATEMENT_ROLE:
            return None, say(L.MISSING, 'MESSAGE_NOT_A_STATEMENT',
                             f'message {reference.message} is an {stored.role} message (display state the Owner '
                             'UI shell wrote), not an Owner statement')
        return stored, None

    def _read(self, store, say, reference):
        stored, missing = self._statement(store, reference, say)
        if stored is None:
            return missing
        result = L.check_message_content(reference, stored.content, self.authority)
        return say(result.outcome, result.code, result.detail or f'Owner statement {reference.message} of thread '
                   f'{reference.thread} (seq {stored.seq})', observed_digest=result.observed_digest)

    def content(self, reference):
        """The durable bytes of the Owner statement REFERENCE names, or None (absent, not a statement, or the
        store unavailable). Read-only."""
        def read(store, say):
            stored, _ = self._statement(store, reference, say)
            return stored.content if stored is not None else None
        result = self._ask(reference, 'reference', read)
        return result if isinstance(result, bytes) else None


class ConversationResolver(_ConversationStoreResolver):
    """Owner conversation threads, read-only. A ``conversation`` reference stands in the statement role, so
    it resolves only at an Owner statement (I1 work design, R5: an assistant row is display state the
    browser wrote, never a statement). Its **anchor** is the pinned ``@<message>``, which must be one of
    the thread's messages (else revision-mismatch, CONVERSATION_MESSAGE_MISSING), or, unpinned, the
    thread's last message (by the store's ``seq``). The anchor must be a user message, author ``owner``
    (else missing, CONVERSATION_NOT_A_STATEMENT), and a thread with no message is missing
    (CONVERSATION_EMPTY). The anchor's content is checked by ``lineage.check_message_content`` as the
    message resolver checks a statement's. The answer reports the anchor's id as ``observed_revision`` and
    the sha256 of its content as ``observed_digest``.

    ``current`` answers at the thread's last message. For an unpinned reference that message is the
    anchor, so it is held to the same rule; for a pinned one it is read for freshness only, so a thread
    that went on after the pin (with a reply or another statement) shows as superseded."""
    kind = 'conversation'
    outcomes = frozenset({L.RESOLVED, L.MISSING, L.REVISION_MISMATCH, L.AUTHORITY_UNAVAILABLE})

    def resolve(self, reference):
        return self._ask(reference, 'reference', lambda store, say: self._read(store, say, reference, True))

    def current(self, reference):
        return self._ask(reference, 'current', lambda store, say: self._read(store, say, reference, False))

    def _read(self, store, say, reference, pinned):
        thread, missing = self._thread(store, reference.thread, say)
        if thread is None:
            return missing
        messages = store.messages(reference.thread)
        if pinned and reference.through_message is not None:
            through = [m for m in messages if m.message_id == reference.through_message]
            if not through:
                return say(L.REVISION_MISMATCH, 'CONVERSATION_MESSAGE_MISSING',
                           f'thread {reference.thread} has no message {reference.through_message!r}')
            at = through[0]
        elif messages:
            at = messages[-1]
        else:
            return say(L.MISSING, 'CONVERSATION_EMPTY',
                       f'thread {reference.thread} has no message, so no Owner statement')
        where = (f'thread {reference.thread} through message {at.message_id} (seq {at.seq} of {len(messages)})')
        if not pinned and reference.through_message is not None:
            # current of a pinned reference: the thread's last message, for freshness only (not its anchor)
            return say(L.RESOLVED, detail=where, observed_revision=at.message_id, observed_digest=at.sha256)
        if (at.role, at.author) != (STATEMENT_ROLE, 'owner'):
            return say(L.MISSING, 'CONVERSATION_NOT_A_STATEMENT',
                       f'{where} is an {at.role} message (display state the Owner UI shell wrote), not an Owner '
                       'statement')
        result = L.check_message_content(L.MessageRef(reference.thread, at.message_id), at.content, self.authority)
        return say(result.outcome, result.code, result.detail or where, observed_revision=at.message_id,
                   observed_digest=result.observed_digest)


# ---------------------------------------------------------------------------
# attempt (plan leaf E-01.5)

class ReadOnlyIntegrationStore:
    """The integration store's read methods on a read-only connection.

    The store's own ``open_store`` migrates (a write transaction) and creates an absent
    file, so it is not used. This opens the existing file with SQLite's ``mode=ro``
    (``storecore.open_read_only``), sets ``query_only``, verifies the store kind and its
    migrations without migrating (``storecore.check_current``) and exposes only
    ``attempts``, ``events``, ``get``, ``attempt_identity`` and the verified ``version``.
    SQLite's WAL protocol still creates or updates the ``-wal`` and ``-shm`` sidecar files for
    any reader; the database file and its content are not changed (tested).
    """

    def __init__(self, path):
        self.store_mod = _integration_store_module()
        storecore = self.store_mod.storecore
        resolved = self.store_mod.check_location(Path(path))
        if not resolved.is_file():
            raise self.store_mod.StoreError(f'no integration store file: {resolved.name}')
        self._conn = storecore.open_read_only(resolved)
        try:
            self._conn.execute('PRAGMA query_only = ON')
            if self._conn.execute('PRAGMA query_only').fetchone()[0] != 1:
                raise self.store_mod.StoreError('the connection did not take query_only')
            self.version = storecore.check_current(self._conn, self.store_mod.KIND)
            self._store = self.store_mod.IntegrationStore(self._conn, resolved)
        except BaseException:
            self._conn.close()
            raise

    def attempts(self):
        return self._store.attempts()

    def events(self, operation_key):
        return self._store.events(operation_key)

    def get(self, operation_key):
        return self._store.get(operation_key)

    def attempt_identity(self, operation_key):
        return self._store.attempt_identity(operation_key)

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


ATTEMPT_AUTHORITY = 'OpenHands Agent Server'
LIVE, FIXTURE = 'live', 'fixture'          # the I1 integration design's R8 vocabulary
AUTHORITIES = (LIVE, FIXTURE)
CONVERSATION_ROUTE = '/api/conversations/{conversation_id}'


def declared_authority(allowlist: bytes):
    """The authority an attempt's pinned route allowlist declares (the I1 integration design, R8 point 2): its
    top-level ``transport`` object's ``authority``, ``live`` when there is no ``transport``; None when the declaration
    is not one of AUTHORITIES (or not readable)."""
    try:
        data = json.loads(allowlist.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if 'transport' not in data:
        return LIVE
    transport = data['transport']
    authority = transport.get('authority') if isinstance(transport, dict) else None
    return authority if authority in AUTHORITIES else None


def answering_authority(answer):
    """The authority the Agent Server answer ANSWER names: a fixture labels every answer (``fixture.authority``,
    the agentfixture catalog's label); an answer with no label is ``live``. None for a label of no known authority."""
    label = answer.get('fixture') if isinstance(answer, dict) else None
    if label is None:
        return LIVE
    authority = label.get('authority') if isinstance(label, dict) else None
    return authority if authority in AUTHORITIES else None


class AttemptResolver:
    """Execution attempts: the conversation of an attempt the dispatcher dispatched, at the Agent Server, read-only
    (plan leaf E-01.5; the I1 integration design, R11).

    A reference ``openhands:conversation/<id>[@<event>]`` is resolved in this order, each answer named by its code:

    1. the integration store (STORE, opened read-only) holds a reservation whose reserved conversation id is ``<id>``
       (else missing, ATTEMPT_MISSING), in state ``confirmed`` (its create was answered with the reserved id; else
       missing, ATTEMPT_NOT_CONFIRMED), and that reservation is the dispatcher's record of a typed attempt
       (``dispatch_inputs.stored_inputs``; else authority-unavailable, ATTEMPT_RECORD_INVALID);
    2. the attempt's **bound authority** is its pinned route allowlist's declaration (``declared_authority``: the
       allowlist read by its pinned sha256 through READ_ARTIFACT; else authority-unavailable,
       ATTEMPT_ALLOWLIST_UNREADABLE);
    3. the Agent Server, through TRANSPORT and the route-checked client over that allowlist, is asked ``GET
       /api/conversations/{id}`` once (no answer: authority-unavailable, ATTEMPT_UNANSWERED);
    4. the **answering authority** (``answering_authority``: the answer's fixture label, or ``live``) must equal the
       bound one (else authority-unavailable, ATTEMPT_AUTHORITY_MISMATCH: a fixture-bound attempt answered without
       the label, or a label on a live-bound one, is neither);
    5. a 404 is missing (ATTEMPT_CONVERSATION_MISSING); a 200 whose body names ``<id>`` is resolved, its observed
       digest the sha256 of ``{"id": <id>}`` as the server answered it (identity, not the conversation's state); any
       other answer is authority-unavailable (ATTEMPT_UNOBSERVED);
    6. a pinned ``@<event>`` is not resolved (authority-unavailable, ATTEMPT_EVENT_UNOBSERVED): the native event
       id's form is not observed (the kind's open item), so the resolver cannot tell an event from its absence;
       ``current`` ignores the anchor.

    A resolution the fixture answered carries ``lineage.fixture_authority`` of the kind's authority as its label,
    so that a traversal states its mode ``fixture``; the mode is the resolver's own finding per reference, never a
    caller's flag. Read-only: the store is opened ``mode=ro`` and the server is asked one ``GET``."""
    kind = 'attempt'
    authority = ATTEMPT_AUTHORITY
    outcomes = frozenset({L.RESOLVED, L.MISSING, L.AUTHORITY_UNAVAILABLE})

    def __init__(self, store, transport, read_artifact=None):
        self.store, self.transport, self._read_artifact = Path(store), transport, read_artifact

    def resolve(self, reference):
        return self._ask(reference, 'reference')

    def current(self, reference):
        return self._ask(reference, 'current')

    def _ask(self, reference, query):
        def say(outcome, code=None, detail='', authority=ATTEMPT_AUTHORITY, **extra):
            return L.answer(reference, outcome, authority, code, detail, query=query, **extra)

        store_mod = _integration_store_module()
        try:
            with ReadOnlyIntegrationStore(self.store) as store:
                record = self._record(store, reference, say)
        except (store_mod.StoreError, sqlite3.Error, OSError) as exc:
            return say(L.AUTHORITY_UNAVAILABLE, 'INTEGRATION_STORE_UNAVAILABLE', f'{type(exc).__name__}: {exc}')
        if isinstance(record, L.Resolution):
            return record
        return self._at_server(reference, query, record, say)

    def _record(self, store, reference, say):
        """The attempt's (resolved inputs, its pinned allowlist's bytes and pin) from the store, or a Resolution."""
        di = _dispatch_module()
        held = [r for r in store.attempts() if r.conversation_id == reference.conversation]
        if not held:
            return say(L.MISSING, 'ATTEMPT_MISSING',
                       f'the integration store holds no attempt whose reserved conversation is {reference.conversation}')
        (reservation,) = held          # a conversation id is the uuid5 of one operation key
        if reservation.state != 'confirmed':
            return say(L.MISSING, 'ATTEMPT_NOT_CONFIRMED', f'the attempt {reservation.operation_key!r} is '
                       f'{reservation.state}: no create of it was answered with its conversation')
        try:
            resolved = di.stored_inputs(store, reservation.operation_key, state='confirmed')
        except di.DispatchRefused as refusal:
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_RECORD_INVALID',
                       f'{reservation.operation_key!r} is not the dispatcher\'s record of a typed attempt '
                       f'({refusal.code})')
        try:
            pin = di._resolved_admission(resolved)['routes']
            allowlist = di._read_pinned(self._read_artifact or di.read_profile_artifact, pin, 'route allowlist')
        except di.DispatchRefused as refusal:
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_ALLOWLIST_UNREADABLE',
                       f'the attempt\'s pinned route allowlist cannot be read ({refusal.code})')
        return resolved, allowlist, pin

    def _at_server(self, reference, query, record, say):
        di = _dispatch_module()
        _resolved, allowlist, pin = record
        bound = declared_authority(allowlist)
        if bound is None:
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_ALLOWLIST_UNREADABLE',
                       'the attempt\'s pinned route allowlist declares no authority of ' + ', '.join(AUTHORITIES))
        conversation = reference.conversation
        try:
            client = di.AgentServerClient(allowlist, self.transport, routes_sha256=pin['sha256'])
            answer = client.call('GET', CONVERSATION_ROUTE, params={'conversation_id': conversation})
        except Exception as exc:  # noqa: BLE001 - no answer: nothing is inferred from it
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_UNANSWERED',
                       f'the Agent Server did not answer for conversation {conversation} ({type(exc).__name__})')
        answered = answering_authority(answer)
        if answered != bound:
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_AUTHORITY_MISMATCH',
                       f'the attempt is bound to authority {bound!r} and was answered by {answered!r}')
        authority = L.fixture_authority(ATTEMPT_AUTHORITY) if answered == FIXTURE else ATTEMPT_AUTHORITY
        status = answer.get('status') if isinstance(answer, dict) else None
        if status == 404:
            return say(L.MISSING, 'ATTEMPT_CONVERSATION_MISSING',
                       f'the Agent Server does not hold conversation {conversation}', authority=authority)
        body = answer.get('body') if isinstance(answer, dict) else None
        if status != 200 or not isinstance(body, dict) or body.get('id') != conversation:
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_UNOBSERVED',
                       f'the Agent Server answered {status!r} without the conversation', authority=authority)
        if query == 'reference' and reference.event is not None:
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_EVENT_UNOBSERVED',
                       f'event {reference.event!r}: the native event id\'s form is not observed, so a pinned event '
                       'is not resolved', authority=authority)
        digest = hashlib.sha256(json.dumps({'id': body['id']}, sort_keys=True, separators=(',', ':'))
                                .encode('utf-8')).hexdigest()
        return say(L.RESOLVED, detail=f'conversation {conversation} of the dispatched attempt (bound and answered '
                   f'{answered})', authority=authority, observed_digest=digest)


# ---------------------------------------------------------------------------
# Registry and command line

def build_registry(*, project=None, backlog=None, repositories=None, open_effects=None, conversations=None,
                   attempts=None, schema=None):
    """A Registry with the resolvers the given configuration allows.

    ``project`` enables design (and, with ``backlog``, an argv prefix, work);
    ``repositories`` maps repository names to local clones for commit;
    ``open_effects`` opens the effects store for effect-receipt;
    ``conversations`` (the path of an Owner conversation store) enables message and conversation;
    ``attempts`` (an ``AttemptResolver``: the integration store and an Agent Server transport) enables attempt.
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
    if conversations is not None:
        resolvers.append(MessageResolver(conversations))
        resolvers.append(ConversationResolver(conversations))
    if attempts is not None:
        if not isinstance(attempts, AttemptResolver):
            raise TypeError('attempts must be an AttemptResolver')
        resolvers.append(attempts)
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
    p_resolve.add_argument('--conversations', type=Path,
                           help='an Owner conversation store (conversation.sqlite), read-only: message and conversation')
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
                                  open_effects=effects, conversations=args.conversations)
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
