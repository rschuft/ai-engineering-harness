"""Read-only end-to-end lineage traversal and its projection (plan leaf P-03.2).

Blueprint section ``#authority``, "Minimal relationship contract":

    Owner statement (thread/message ID)
     └─ originates → accepted objective (outcome ID)
        ├─ shaped_by → OpenSpec proposal / design revision
        ├─ fulfilled_by → Backlog task(s)
        │   └─ executed_by → OpenHands run(s)

"If a source relationship was never recorded, the UI must show missing provenance, not
invent a causal history." This module follows those links from one outcome id, read-only,
and returns a projection (``lineage-projection/v1``): every node with its authority, its
``authority_mode``, the resolution of its reference as written and at the authority's
current revision; every edge with the record that asserts it (its provenance); and an
explicit list of uncertainties. The verdict is ``complete`` only when that list is empty,
so a missing, changed, moved, unavailable or sample-backed node can never pass silently.

Where each edge's assertion comes from:

- statement → objective (``originates``) and objective → statement (``accepted_by``): the
  ``source`` and ``acceptance`` fields of the Objective item in the declaring change's
  intent record (decision 0008, point 6), read from git objects at the objective's
  observed revision. A local item id in ``source`` that names an Original Quote item is
  followed to that quote's ``source`` message, and the quote's bytes are located in the
  message content mechanically (Overseer decision D2), when the statement authority can
  return content.
- objective → design (``shaped_by``): the declaring change's files at that revision, as
  P-02.1 pointers (``.openspec.yaml`` is metadata, not an artifact).
- objective → work (``fulfilled_by``) and work → design (``cites``): the references of
  each Backlog.md task, from Backlog.md's own ``task list --json``. Backlog.md has no
  reverse index, so enumerating the tasks and reading their references is the supported
  way to find them; only the ``id`` and ``references`` fields are read, never a status.
- work → attempt (``executed_by``): an integration-store attempt reservation (F-05.1)
  whose intent cites the task (``workRef``) and, optionally, the outcome (``outcomeRef``),
  the key names of the blueprint's illustrative correlation receipt
  (``#integration-contracts``). The attempt's identity is the reservation's
  ``conversation_id``. The store is opened read-only (``mode=ro``, ``query_only``).

Every node is resolved through ``Authorities``: the lineage ``Registry`` (P-03.1), plus
optional, clearly labelled sample authorities that may stand in only for kinds whose real
authority does not exist yet (``lineage_samples.py``). Nothing here writes, runs
OpenSpec, or reads a Backlog.md status.

Usage (from the repository root):
    python -I -B integrations/lineage/lineage_trace.py trace OUTCOME --project DIR
        [--backlog CMD] [--store DB]

Exit status: 0 the projection is complete, 1 it carries uncertainty, 2 could not run.
The command line uses the real authorities only. Standard library only, plus git and the
tools named.
"""
import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
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


resolve_mod = _load('lineage_resolve', HERE / 'lineage_resolve.py')
L = resolve_mod.lineage
planning = resolve_mod.planning

PROJECTION_FORMAT = 'lineage-projection/v1'
AUTHORITATIVE, SAMPLE, UNAVAILABLE = 'authoritative', 'sample', 'unavailable'
AUTHORITY_MODES = (AUTHORITATIVE, SAMPLE, UNAVAILABLE)

# Relations: the blueprint's names where it has one (#authority, minimal relationship
# contract); accepted_by is decision 0008's acceptance field; cites is a task's reference.
ORIGINATES, ACCEPTED_BY, SHAPED_BY, FULFILLED_BY, CITES, EXECUTED_BY = (
    'originates', 'accepted_by', 'shaped_by', 'fulfilled_by', 'cites', 'executed_by')

# Freshness of a node: its reference as written, compared with the authority's current revision.
CURRENT, SUPERSEDED, MOVED, MOVED_CHANGED, GONE, UNKNOWN = (
    'current', 'superseded', 'moved', 'moved-changed', 'gone', 'unknown')

# Uncertainty reasons (closed vocabulary).
REASONS = ('unresolved', 'current-unresolved', 'superseded', 'moved', 'moved-changed', 'gone',
           'sample-authority', 'quote-unverified', 'missing-link', 'malformed-reference',
           'enumeration-unavailable')

ROLE = {'message': 'statement', 'conversation': 'statement', 'objective': 'objective', 'design': 'design',
        'work': 'work', 'attempt': 'attempt'}
ROLE_ORDER = ('statement', 'objective', 'design', 'work', 'attempt', 'other')
STATEMENT_KINDS = ('message', 'conversation')
LOCAL_ITEM = re.compile(r'^[A-Z]+[1-9][0-9]*$')
ORIGINAL_QUOTE = 'Original Quote'

# The intent keys of an attempt reservation that the traversal reads: the blueprint's
# illustrative correlation receipt (#integration-contracts) names them workRef and outcomeRef.
WORK_KEY, OUTCOME_KEY = 'workRef', 'outcomeRef'
STORE_RECORD = 'integration store attempt reservation (F-05.1)'


def _intent_module():
    return resolve_mod._intent_module()


def _store_module():
    return _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')


# ---------------------------------------------------------------------------
# Authorities: the registry, and sample stand-ins for kinds without an authority

class Authorities:
    """Resolves a reference and says on whose authority.

    ``samples`` maps a kind to a sample resolver (``resolve``, ``current``, an
    ``authority`` label and optionally ``content(reference)``). A sample may stand in
    only for a kind whose schema status is ``authority-unavailable``; it can never
    replace an implemented authority. Every answer carries its ``authority_mode``:
    ``sample`` for a sample, ``unavailable`` when the authority could not be asked,
    ``authoritative`` otherwise.
    """

    def __init__(self, registry, samples=None):
        self.registry = registry
        self.samples = dict(samples or {})
        for kind, sample in self.samples.items():
            entry = registry.kinds.get(kind)
            if entry is None or entry['status'] != 'authority-unavailable':
                raise ValueError(f'a sample may stand in only for a kind whose authority is unavailable, not {kind!r}')
            if not str(getattr(sample, 'authority', '')).startswith('SAMPLE'):
                raise ValueError(f'the sample for {kind!r} must be labelled SAMPLE in its authority')

    def ask(self, reference, method):
        """(Resolution, authority_mode) for REFERENCE; METHOD is 'resolve' or 'current'."""
        query = 'reference' if method == 'resolve' else 'current'
        sample = self.samples.get(reference.kind)
        if sample is not None:
            result = getattr(sample, method)(reference)
            if not isinstance(result, L.Resolution) or result.reference != reference.text \
                    or result.kind != reference.kind or result.query != query or result.authority != sample.authority:
                raise RuntimeError(f'the {reference.kind} sample answered outside its contract: {result!r}')
            return result, SAMPLE
        result = getattr(self.registry, method)(reference)
        return result, (UNAVAILABLE if result.outcome == L.AUTHORITY_UNAVAILABLE else AUTHORITATIVE)

    def content(self, reference):
        """The durable bytes of a statement, when its (sample) authority can return them."""
        sample = self.samples.get(reference.kind)
        reader = getattr(sample, 'content', None)
        return reader(reference) if reader else None


# ---------------------------------------------------------------------------
# Read-only views of the sources the traversal enumerates

class ReadOnlyIntegrationStore:
    """The integration store's read methods on a read-only connection.

    The store's own ``open_store`` migrates (a write transaction) and creates an absent
    file, so it is not used. This opens the existing file with SQLite's ``mode=ro``
    (``storecore.open_read_only``), sets ``query_only``, verifies the store kind and its
    migrations without migrating (``storecore.check_current``) and exposes only
    ``attempts``, ``events`` and the verified ``version``. SQLite's WAL protocol still creates
    or updates the ``-wal`` and ``-shm`` sidecar files for any reader; the database file
    and its content are not changed (tested).
    """

    def __init__(self, path):
        self.store_mod = _store_module()
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

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _task_field(task, name):
    """One field of a Backlog.md task summary. Only ``id`` and ``references`` are read."""
    if name not in ('id', 'references'):
        raise AssertionError(f'the traversal never reads {name!r}')
    return task[name] if name in task else None


# ---------------------------------------------------------------------------
# The projection builder

def _resolution_json(result):
    return {'query': result.query, 'outcome': result.outcome, 'code': result.code, 'detail': result.detail,
            'observed_revision': result.observed_revision, 'observed_digest': result.observed_digest}


class _Projection:
    def __init__(self, authorities, root):
        self.authorities = authorities
        self.root = root
        self.nodes = {}
        self.edges = {}
        self.uncertainties = []

    def uncertain(self, reference, reason, code, detail='', outcome=None):
        assert reason in REASONS, reason
        entry = {'reference': reference, 'reason': reason, 'code': code, 'detail': detail}
        if outcome is not None:
            entry['outcome'] = outcome
        if entry not in self.uncertainties:
            self.uncertainties.append(entry)

    def edge(self, source, target, relation, provenance):
        key = (source, target, relation)
        provenances = self.edges.setdefault(key, [])
        if provenance not in provenances:
            provenances.append(provenance)

    def node(self, reference, freshness_hook=None):
        """The node of REFERENCE (a typed reference), resolved once as written and once at
        the authority's current revision."""
        text = reference.text
        if text in self.nodes:
            return self.nodes[text]
        pinned, mode = self.authorities.ask(reference, 'resolve')
        current, current_mode = self.authorities.ask(reference, 'current')
        node = {'reference': text, 'kind': reference.kind, 'role': ROLE.get(reference.kind, 'other'),
                'authority': pinned.authority, 'authority_mode': mode, 'pinned': reference.pinned,
                'resolution': _resolution_json(pinned), 'current': _resolution_json(current), 'freshness': UNKNOWN}
        if pinned.facts is not None:
            node['facts'] = pinned.facts
        self.nodes[text] = node
        if not pinned.resolved:
            self.uncertain(text, 'unresolved', pinned.code, pinned.detail, pinned.outcome)
            return node
        if mode == SAMPLE or current_mode == SAMPLE:
            self.uncertain(text, 'sample-authority', 'SAMPLE_AUTHORITY',
                           f'resolved only by a sample authority ({pinned.authority}); no live authority was asked')
        if current.resolved:
            if current.observed_digest != pinned.observed_digest:
                node['freshness'] = SUPERSEDED
                self.uncertain(text, 'superseded', 'SUPERSEDED',
                               f'the reading as written has digest {pinned.observed_digest}; the current revision '
                               f'{current.observed_revision} has {current.observed_digest}', current.outcome)
            else:
                node['freshness'] = CURRENT
            return node
        if freshness_hook is not None and freshness_hook(reference, node, current):
            return node
        self.uncertain(text, 'current-unresolved', current.code, current.detail, current.outcome)
        return node

    def to_json(self, sources):
        def node_key(n):
            return (ROLE_ORDER.index(n['role']) if n['role'] in ROLE_ORDER else len(ROLE_ORDER), n['reference'])
        edges = [{'from': s, 'to': t, 'relation': r, 'provenance': p} for (s, t, r), p in self.edges.items()]
        edges.sort(key=lambda e: (e['relation'], e['from'], e['to']))
        uncertainties = sorted(self.uncertainties, key=lambda u: (REASONS.index(u['reason']), u['reference'], u['code']))
        modes = {}
        for node in self.nodes.values():
            modes[node['authority_mode']] = modes.get(node['authority_mode'], 0) + 1
        return {
            'format': PROJECTION_FORMAT,
            'root': self.root,
            'verdict': 'complete' if not uncertainties else 'incomplete',
            'sources': sources,
            'authority_modes': {mode: modes.get(mode, 0) for mode in AUTHORITY_MODES},
            'nodes': sorted(self.nodes.values(), key=node_key),
            'edges': edges,
            'uncertainties': uncertainties,
        }


# ---------------------------------------------------------------------------
# The traversal

_ARCHIVED = re.compile(r'^openspec/changes/archive/(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})-(?P<change>[^/]+)/(?P<artifact>.+)$')
_ACTIVE_CHANGE = re.compile(r'^openspec/changes/(?P<change>[^/]+)$')
_ARCHIVED_CHANGE = re.compile(r'^openspec/changes/archive/[0-9]{4}-[0-9]{2}-[0-9]{2}-(?P<change>[^/]+)$')


def change_name(change_path):
    """The OpenSpec change id of a declaring change path, active or archived."""
    for pattern in (_ARCHIVED_CHANGE, _ACTIVE_CHANGE):
        match = pattern.match(change_path or '')
        if match and match['change'] != 'archive':
            return match['change'], pattern is _ARCHIVED_CHANGE
    return None, False


def archived_location(git, revision, pointer):
    """Where ``openspec archive`` put a design artifact: every
    ``openspec/changes/archive/<date>-<change>/<artifact>`` blob at REVISION, with its sha256."""
    found = []
    for path in git.files(revision, 'openspec/changes/archive'):
        match = _ARCHIVED.match(path)
        if match and match['change'] == pointer.change and match['artifact'] == pointer.artifact:
            found.append((path, hashlib.sha256(git.blob(revision, path)).hexdigest()))
    return found


class Traversal:
    """One read-only traversal from an outcome id; ``run()`` returns the projection."""

    def __init__(self, authorities, *, project, backlog=None, store=None):
        self.authorities = authorities
        self.project = Path(project)
        self.backlog = list(backlog) if backlog is not None else None
        self.store = Path(store) if store is not None else None

    def run(self, outcome):
        root = L.parse(outcome) if isinstance(outcome, str) else outcome
        if not isinstance(root, L.ObjectiveRef):
            raise L.MalformedReference('REFERENCE_MALFORMED', f'the traversal starts from an outcome: {root!r}')
        self.p = _Projection(self.authorities, root.text)
        self.git, why = resolve_mod._git(self.project)
        sources = {'project_head': None, 'backlog': None, 'store_schema_version': None}
        if self.git is None:
            self.p.uncertain(root.text, 'enumeration-unavailable', 'PROJECT_UNAVAILABLE', why)
        else:
            try:
                sources['project_head'] = self.git.commit('HEAD')
            except (planning.PlanningError, subprocess.TimeoutExpired, OSError):
                pass
        objective = self.p.node(root)
        facts = objective.get('facts') if objective['resolution']['outcome'] == L.RESOLVED else None
        revision = objective['resolution']['observed_revision'] if facts else None
        change, archived = change_name(facts['change']) if facts else (None, False)
        if facts and self.git is not None:
            self.statements(root, facts, revision, objective['resolution']['observed_digest'])
            self.design(root, facts, revision, change, archived)
        tasks = self.work(root, change, sources)
        self.attempts(root, tasks, sources)
        return self.p.to_json(sources)

    # -- statements ------------------------------------------------------

    def _parse(self, text, where):
        """A typed reference, or a node for a scheme no kind uses; None when malformed."""
        try:
            return L.parse(text)
        except L.MalformedReference as exc:
            if exc.code == 'REFERENCE_UNSUPPORTED_SCHEME':
                answer = self.authorities.registry.resolve(text)
                node = {'reference': text, 'kind': 'unknown', 'role': 'other', 'authority': answer.authority,
                        'authority_mode': UNAVAILABLE, 'pinned': False, 'resolution': _resolution_json(answer),
                        'current': _resolution_json(answer), 'freshness': UNKNOWN}
                self.p.nodes.setdefault(text, node)
                self.p.uncertain(text, 'unresolved', answer.code, answer.detail, answer.outcome)
                return text
            self.p.uncertain(text, 'malformed-reference', exc.code, f'{where}: {exc.message}')
            return None

    def statements(self, root, facts, revision, digest):
        proposal = f'{facts["change"]}/proposal.md'
        record_provenance = {'record': f'{proposal} (intent record, declaring change)', 'authority': 'OpenSpec',
                             'revision': revision, 'digest': digest, 'item': facts['item']}
        record = None
        try:
            data = self.git.blob(revision, proposal)
            if hashlib.sha256(data).hexdigest() != digest:
                self.p.uncertain(root.text, 'missing-link', 'INTENT_RECORD_CHANGED',
                                 f'{proposal} at {revision} no longer has the digest the objective resolved')
            else:
                record, _problems = _intent_module()._Parser(data).parse()
        except (planning.PlanningError, subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as exc:
            self.p.uncertain(root.text, 'missing-link', 'INTENT_RECORD_UNREADABLE', str(exc))
        reached = []
        for entry in facts['source']:
            provenance = {**record_provenance, 'field': 'source'}
            if LOCAL_ITEM.match(entry):
                item = record.items.get(entry) if record is not None else None
                if item is None:
                    if record is not None:
                        self.p.uncertain(root.text, 'missing-link', 'SOURCE_ITEM_MISSING',
                                         f'{facts["item"]} cites {entry}, which {proposal} does not hold')
                    continue
                if item.section != ORIGINAL_QUOTE:
                    continue  # only an original quote leads to a statement
                reference = self._parse(item.fields.get('source', ''), f'{entry}.source')
                if reference is None:
                    continue
                provenance = {**provenance, 'via': entry}
                if not isinstance(reference, str):
                    self._quote(reference, item, entry)
            else:
                reference = self._parse(entry, f'{facts["item"]}.source')
                if reference is None:
                    continue
            text = reference if isinstance(reference, str) else self.p.node(reference)['reference']
            reached.append(text)
            self.p.edge(text, root.text, ORIGINATES, provenance)
        acceptance = self._parse(facts['acceptance'], f'{facts["item"]}.acceptance')
        if acceptance is not None:
            text = acceptance if isinstance(acceptance, str) else self.p.node(acceptance)['reference']
            self.p.edge(root.text, text, ACCEPTED_BY, {
                **record_provenance, 'field': 'acceptance',
                'declaration': f'{facts["change"]}/.openspec.yaml x-outcomes (decision 0008)'})
        statement_nodes = [t for t in reached if self.p.nodes[t]['kind'] in STATEMENT_KINDS]
        if not statement_nodes:
            self.p.uncertain(root.text, 'missing-link', 'NO_SOURCE_STATEMENT',
                             f'{facts["item"]} names no Owner statement among its sources {facts["source"]}')

    def _quote(self, reference, item, item_id):
        """Locate an original quote's bytes in its source message and verify the span
        (Overseer decision D2: quotes are filled mechanically from the durable source)."""
        node = self.p.node(reference)
        if reference.kind != 'message':
            self.p.uncertain(reference.text, 'quote-unverified', 'QUOTE_SOURCE_NOT_A_MESSAGE',
                             f'{item_id} quotes a {reference.kind}, not a message')
            return
        quote = {'item': item_id}
        node.setdefault('quotes', []).append(quote)
        if node['resolution']['outcome'] != L.RESOLVED:
            quote['outcome'] = 'not-checked'
            quote['detail'] = 'the statement did not resolve, so the quote cannot be checked'
            return
        content = self.authorities.content(reference)
        if content is None:
            quote['outcome'] = 'not-checked'
            self.p.uncertain(reference.text, 'quote-unverified', 'QUOTE_SOURCE_UNREADABLE',
                             f'the authority of {reference.text} returns no content to check {item_id} against')
            return
        if not item.quote:
            quote['outcome'] = 'not-checked'
            self.p.uncertain(reference.text, 'quote-unverified', 'QUOTE_MISSING', f'{item_id} has no quote')
            return
        start = content.find(item.quote)
        if start < 0:
            quote['outcome'] = L.DIGEST_MISMATCH
            self.p.uncertain(reference.text, 'quote-unverified', 'QUOTE_NOT_IN_SOURCE',
                             f'the quote of {item_id} is not a byte-identical span of the message')
            return
        if content.find(item.quote, start + 1) >= 0:
            quote['outcome'] = L.AMBIGUOUS
            self.p.uncertain(reference.text, 'quote-unverified', 'QUOTE_SPAN_AMBIGUOUS',
                             f'the quote of {item_id} occurs more than once in the message')
            return
        span = L.span_reference(reference.thread, reference.message, content, start, len(item.quote))
        check = L.check_message_content(span, content)
        quote.update({'span': span.text, 'outcome': check.outcome})
        if not check.resolved:
            self.p.uncertain(reference.text, 'quote-unverified', check.code, check.detail)

    # -- design ----------------------------------------------------------

    def _design_freshness(self, reference, node, current):
        """A design pointer whose current() is missing: moved by openspec archive, or gone."""
        if current.code != 'POINTER_ARTIFACT_MISSING' or self.git is None:
            return False
        try:
            head = self.git.commit('HEAD')
            found = archived_location(self.git, head, reference) if head else []
        except (planning.PlanningError, subprocess.TimeoutExpired, OSError) as exc:
            self.p.uncertain(reference.text, 'current-unresolved', 'GIT_FAILED', str(exc))
            return True
        if not found:
            node['freshness'] = GONE
            self.p.uncertain(reference.text, 'gone', 'DESIGN_ARTIFACT_GONE',
                             f'{current.detail}; and no openspec/changes/archive/<date>-{reference.change}/'
                             f'{reference.artifact} exists at {head}', current.outcome)
            return True
        if len(found) > 1:
            self.p.uncertain(reference.text, 'current-unresolved', 'DESIGN_ARCHIVE_AMBIGUOUS',
                             f'{len(found)} archived copies at {head}: ' + ', '.join(p for p, _ in found),
                             L.AMBIGUOUS)
            return True
        path, digest = found[0]
        node['moved_to'] = {'path': path, 'revision': head, 'digest': digest}
        if digest == reference.digest:
            node['freshness'] = MOVED
            self.p.uncertain(reference.text, 'moved', 'DESIGN_ARTIFACT_MOVED',
                             f'openspec archive moved it to {path} at {head}, byte for byte unchanged; the pointer '
                             f'still resolves at its pinned revision', current.outcome)
        else:
            node['freshness'] = MOVED_CHANGED
            self.p.uncertain(reference.text, 'moved-changed', 'DESIGN_ARTIFACT_MOVED_AND_CHANGED',
                             f'moved to {path} at {head}, where it has sha256 {digest}', current.outcome)
        return True

    def design_node(self, pointer):
        return self.p.node(pointer, freshness_hook=self._design_freshness)

    def design(self, root, facts, revision, change, archived):
        if archived:
            self.p.uncertain(root.text, 'missing-link', 'DESIGN_ARCHIVED_AT_REVISION',
                             f'at {revision} the declaring change is {facts["change"]}; a P-02.1 pointer cannot '
                             'address an archived artifact, so the design is reached only through task references')
            return
        if change is None:
            return
        try:
            paths = self.git.files(revision, facts['change'])
        except (planning.PlanningError, subprocess.TimeoutExpired, OSError) as exc:
            self.p.uncertain(root.text, 'enumeration-unavailable', 'GIT_FAILED', str(exc))
            return
        prefix = facts['change'] + '/'
        for path in sorted(paths):
            artifact = path[len(prefix):]
            if artifact == '.openspec.yaml':
                continue  # change metadata, not an artifact
            try:
                pointer = L.parse(planning.make_pointer(self.git, change, artifact, revision).text)
            except (planning.PlanningError, L.MalformedReference) as exc:
                self.p.uncertain(root.text, 'malformed-reference', getattr(exc, 'code', 'POINTER_MALFORMED'),
                                 f'{path}: {exc}')
                continue
            node = self.design_node(pointer)
            self.p.edge(root.text, node['reference'], SHAPED_BY, {
                'record': f'{facts["change"]} (declaring change, its files)', 'authority': 'OpenSpec',
                'revision': revision})

    # -- work ------------------------------------------------------------

    def work(self, root, change, sources):
        """{task id: node reference} of the tasks that fulfil the objective."""
        tasks = {}
        if self.backlog is None:
            self.p.uncertain(root.text, 'enumeration-unavailable', 'BACKLOG_NOT_CONFIGURED',
                             'no Backlog.md command was given, so the tasks cannot be enumerated')
            return tasks
        backlog = resolve_mod.ReadOnlyBacklog(self.backlog, self.project)
        try:
            listed = backlog.list_tasks()
        except planning.PlanningError as exc:
            self.p.uncertain(root.text, 'enumeration-unavailable', 'BACKLOG_LIST_FAILED', f'{exc.code}: {exc.message}')
            return tasks
        except (subprocess.TimeoutExpired, OSError) as exc:
            self.p.uncertain(root.text, 'enumeration-unavailable', 'BACKLOG_UNAVAILABLE', str(exc))
            return tasks
        sources['backlog'] = 'task list --json (working tree)'
        for task in listed:
            task_id = _task_field(task, 'id')
            references = _task_field(task, 'references') or []
            if not isinstance(references, list):
                self.p.uncertain(f'backlog:{task_id}', 'malformed-reference', 'TASK_REFERENCES_MALFORMED',
                                 'Backlog.md listed references that are not a list')
                continue
            matched = []
            for text in references:
                try:
                    reference = L.parse(text)
                except L.MalformedReference:
                    continue  # a reference of another kind or none: not a lineage link
                if isinstance(reference, L.ObjectiveRef) and reference.outcome == root.outcome:
                    matched.append(reference)
                elif isinstance(reference, L.DesignRef) and change is not None and reference.change == change:
                    matched.append(reference)
            if not matched:
                continue
            work = self._work_node(task_id)
            if work is None:
                continue
            tasks[work.task] = work.text
            provenance = {'record': f'Backlog.md task {work.task} references', 'authority': 'Backlog.md',
                          'revision': None, 'via': [r.text for r in matched]}
            self.p.edge(root.text, work.text, FULFILLED_BY, provenance)
            for reference in matched:
                if isinstance(reference, L.DesignRef):
                    node = self.design_node(reference)
                    self.p.edge(work.text, node['reference'], CITES, {**provenance, 'via': [reference.text]})
        return tasks

    def _work_node(self, task_id):
        try:
            work = L.WorkRef(task_id)
        except L.MalformedReference as exc:
            self.p.uncertain(f'backlog:{task_id}', 'malformed-reference', exc.code, exc.message)
            return None
        self.p.node(work)
        return work

    # -- attempts --------------------------------------------------------

    def attempts(self, root, tasks, sources):
        if self.store is None:
            self.p.uncertain(root.text, 'enumeration-unavailable', 'STORE_NOT_CONFIGURED',
                             'no integration store was given, so attempt reservations cannot be read')
            reservations = []
        else:
            store_mod = _store_module()
            try:
                with ReadOnlyIntegrationStore(self.store) as store:
                    sources['store_schema_version'] = store.version
                    reservations = [(r, store.events(r.operation_key)) for r in store.attempts()]
            except (store_mod.StoreError, sqlite3.Error, OSError) as exc:
                self.p.uncertain(root.text, 'enumeration-unavailable', 'STORE_UNAVAILABLE',
                                 f'{type(exc).__name__}: {exc}')
                reservations = []
        executed = set()
        for reservation, events in reservations:
            where = f'reservation {reservation.operation_key!r}'
            try:
                intent = json.loads(reservation.intent_json)
            except ValueError:
                self.p.uncertain(root.text, 'malformed-reference', 'INTENT_NOT_JSON', where)
                continue
            if not isinstance(intent, dict):
                continue
            cited = {}
            for key, cls in ((WORK_KEY, L.WorkRef), (OUTCOME_KEY, L.ObjectiveRef)):
                if key not in intent:
                    continue
                value = intent[key]
                try:
                    reference = L.parse(value) if isinstance(value, str) else None
                except L.MalformedReference:
                    reference = None
                if not isinstance(reference, cls):
                    self.p.uncertain(f'{where} {key}', 'malformed-reference', 'INTENT_REFERENCE_MALFORMED',
                                     f'{where}: {key} is not a {cls.KIND} reference: {value!r}')
                    continue
                cited[key] = reference
            work, outcome = cited.get(WORK_KEY), cited.get(OUTCOME_KEY)
            for_root = outcome is not None and outcome.outcome == root.outcome
            if work is None or (work.task not in tasks and not for_root):
                continue
            reserved = [e for e in events if e.seq == 0 and e.to_state == 'reserved']
            provenance = {'record': STORE_RECORD, 'authority': 'integration store (operational receipt, '
                          'not the attempt\'s authority)', 'operation_key': reservation.operation_key,
                          'intent_digest': reservation.intent_digest,
                          'event_seq': reserved[0].seq if reserved else None,
                          'event_id': reserved[0].event_id if reserved else None}
            if work.task not in tasks:
                node = self._work_node(work.task)
                if node is None:
                    continue
                tasks[work.task] = node.text
                self.p.edge(root.text, node.text, FULFILLED_BY, {**provenance, 'via': [outcome.text, work.text]})
            try:
                attempt = L.AttemptRef(reservation.conversation_id)
            except L.MalformedReference as exc:
                self.p.uncertain(where, 'malformed-reference', exc.code, exc.message)
                continue
            self.p.node(attempt)
            self.p.edge(tasks[work.task], attempt.text, EXECUTED_BY, provenance)
            executed.add(work.task)
        if not tasks:
            self.p.uncertain(root.text, 'missing-link', 'NO_TASK_FOR_OBJECTIVE',
                             'no Backlog.md task references the outcome or its declaring change\'s design, and no '
                             'attempt reservation cites it')
        for task in sorted(set(tasks) - executed):
            self.p.uncertain(tasks[task], 'missing-link', 'NO_ATTEMPT_FOR_TASK',
                             'no attempt reservation in the integration store cites this task')


def trace(outcome, authorities, *, project, backlog=None, store=None):
    """The ``lineage-projection/v1`` projection of OUTCOME (text or ObjectiveRef)."""
    return Traversal(authorities, project=project, backlog=backlog, store=store).run(outcome)


# ---------------------------------------------------------------------------
# Command line

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    p_trace = sub.add_parser('trace', help='project the lineage of one outcome (read-only, real authorities only)')
    p_trace.add_argument('outcome')
    p_trace.add_argument('--project', type=Path, required=True)
    p_trace.add_argument('--backlog')
    p_trace.add_argument('--store', type=Path)
    args = parser.parse_args(argv)
    try:
        backlog = planning.tool_argv(args.backlog) if args.backlog else None
        registry = resolve_mod.build_registry(project=args.project, backlog=backlog)
        projection = trace(args.outcome, Authorities(registry), project=args.project, backlog=backlog,
                           store=args.store)
    except L.MalformedReference as exc:
        print(f'ERROR {exc.code}: {exc.message}', file=sys.stderr)
        return 2
    except (planning.CannotRun, resolve_mod.CannotRun) as exc:
        print(f'ERROR {exc}', file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(projection, indent=2, ensure_ascii=False))
    for entry in projection['uncertainties']:
        print(f'UNCERTAIN {entry["reference"]}: {entry["reason"]} {entry["code"]}', file=sys.stderr)
    return 0 if projection['verdict'] == 'complete' else 1


if __name__ == '__main__':
    sys.exit(main())
