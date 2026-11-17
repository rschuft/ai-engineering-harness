"""Tests for integrations/lineage/lineage_trace.py: the read-only end-to-end traversal,
its projection, the example and the negative resolution fixtures (stdlib unittest,
plan leaf P-03.2).

Offline. Each case builds a throwaway project repository (the P-02.1 qual-02 change and an
x-outcomes declaration, never the P-01.2 fixture itself), the fake Backlog.md (replaying
Backlog.md's own recorded P-02.1 output, or its own small state), an integration store made
through the store's own API, and an Owner conversation store made through its own API that
holds the corpus statements the cases quote under store identities
(``lineage_example.build_conversations``; a case that needs a statement to resolve cites
them, ``cite_store``). Since U-02.2 no sample stands in for the Owner conversation store: its
statement sample is retired (I1 work design, R5), and statements are read from the real store.
Since E-01.5 no sample stands in for the Agent Server either: the attempt sample is retired, and
a case that needs an attempt to resolve dispatches it (``fixture_attempts``: the dispatcher's
records, made through the store's own API) and asks the attempt resolver over the Agent Server
fixture's cited core, whose answers state their mode ``fixture``.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lineage_example as E  # noqa: E402
import fixture_attempts as FA  # noqa: E402

T, S, R, L, fx = E.T, E.S, E.R, E.L, E.fx
RA = E.RA
planning = R.planning
OUTCOME, CHANGE, CHANGE_DIR = E.OUTCOME, E.CHANGE, E.CHANGE_DIR
ARCHIVED_DIR = f'openspec/changes/archive/2026-11-07-{CHANGE}'
OTHER_OUTCOME = '0d9e8f7a-6b5c-4d3e-8f1a-2b3c4d5e6f70'
FAKE_FILES = ('.fake-backlog.json', '.fake-backlog-argv.jsonl')
CLI = [sys.executable, '-I', '-B', str(E.LINEAGE_DIR / 'lineage_trace.py')]
QUAL08 = E.CORPUS / 'qual-08' / 'message-1.txt'
M1, M2 = E.store_reference('conversation:qual-02/message-1'), E.store_reference('conversation:qual-02/message-2')
Q8 = E.store_reference('conversation:qual-08/message-1')
THREAD02, THREAD08 = E.THREADS['qual-02'], E.THREADS['qual-08']
SPEC = 'specs/catalogue-search/new-product-visibility/spec.md'
NBSP = '\u00a0'.encode()  # U+00A0, written as an escape


def tree_state(repo):
    """What a read-only traversal must leave unchanged (the fake Backlog.md's own files aside)."""
    excluded = [f':(exclude){name}' for name in FAKE_FILES]
    return (fx.git(repo, 'status', '--porcelain', '--untracked-files=all', '--ignored', '--', '.', *excluded),
            fx.git(repo, 'for-each-ref'), fx.head(repo), fx.git(repo, 'count-objects', '-v'))


def store_state(path):
    """The database file's bytes and the store's canonical content."""
    store_mod = E.store_module()
    conn = store_mod.storecore.open_read_only(path)
    try:
        dump = store_mod._canonical_dump(conn)
    finally:
        conn.close()
    return hashlib.sha256(Path(path).read_bytes()).hexdigest(), hashlib.sha256(dump).hexdigest()


def fake_state(*tasks):
    """A fake Backlog.md state: (id, [references]) per task."""
    return json.dumps({'tasks': [{'id': task, 'title': f'Task {task}', 'status': 'To Do', 'description': None,
                                  'references': refs, 'dependencies': []} for task, refs in tasks]})


def by_reference(projection):
    return {node['reference']: node for node in projection['nodes']}


def reasons(projection):
    return {(u['reference'], u['reason'], u['code']) for u in projection['uncertainties']}


def edges(projection, relation=None):
    return {(e['from'], e['to'], e['relation']) for e in projection['edges']
            if relation is None or e['relation'] == relation}


class Case(unittest.TestCase):
    """A fresh throwaway project, store and work directory per test."""

    def setUp(self):
        fx.require_repository_access()  # without Dulwich: REPOSITORY_NEEDS_DULWICH, never a skip
        patch = E.in_process_backlog()
        patch.start()
        self.addCleanup(patch.stop)
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-trace-'))
        self.addCleanup(fx.rmtree, self.tmp)
        self.repo = self.tmp / 'p'
        self.design, self.declared = E.build_project(self.repo)
        self.store = self.tmp / 'st' / 'integration.sqlite'
        self.conversations = E.build_conversations(E.conversations_path(self.repo))

    def reserve(self, *intents):
        E.build_store(self.store, intents)

    def reserve_tasks(self, *tasks):
        self.reserve(*[(E.operation_key(t), E.task_intent(t)) for t in tasks])

    def commit(self, message):
        return fx.commit_all(self.repo, message, date='2026-11-07T00:02:00Z')

    def trace(self, outcome=None, samples=True, snapshot=E.RECORDED_TASKS, store=True, backlog=E.FAKE_BACKLOG):
        outcome = outcome or f'outcome:{OUTCOME}@{self.declared}'
        auth = E.authorities(self.repo, samples, backlog or E.FAKE_BACKLOG)
        return E.run_trace(outcome, auth, self.repo, self.store if store else None, backlog, snapshot)

    def fake_backlog(self, *tasks):
        (self.repo / '.fake-backlog.json').write_text(fake_state(*tasks), encoding='utf-8')

    def backlog_argv(self):
        log = self.repo / '.fake-backlog-argv.jsonl'
        return [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []

    def pointer(self, artifact, revision=None):
        return planning.make_pointer(planning.Git(self.repo), CHANGE, artifact, revision or self.design).text

    def assertUncertain(self, projection, reference, reason, code):
        self.assertIn((reference, reason, code), reasons(projection), json.dumps(projection['uncertainties'], indent=1))
        self.assertEqual(projection['verdict'], 'incomplete')


# ---------------------------------------------------------------------------
# The example

class Example(unittest.TestCase):
    category = 'contract'

    @classmethod
    def setUpClass(cls):
        fx.require_repository_access()
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-trace-example-'))
        # what build_dispatched made, recorded as it made it (work id, operation key, conversation id): the
        # expectation of the executed-by edges, independent of the projection (review of dispatch 19, N8)
        cls.dispatched, made = [], FA.FixtureAttempts.attempt

        def recording(attempts, integration_store, core, work_id, **kwargs):
            key, cid = made(attempts, integration_store, core, work_id, **kwargs)
            cls.dispatched.append((work_id, key, cid))
            return key, cid
        with E.in_process_backlog(), mock.patch.object(FA.FixtureAttempts, 'attempt', recording):
            cls.projections = E.example(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        fx.rmtree(cls.tmp)

    def test_regenerates_the_committed_example(self):
        self.assertEqual(self.projections, E.recorded())
        for name, projection in self.projections.items():
            with self.subTest(name=name):
                self.assertIsNone(fx.MACHINE_PATH.search(E.dumps(projection)))

    @staticmethod
    def recorded_proposal_pointer():
        """The proposal pointer the recorded P-02.1 tasks carry, pinned at the design commit."""
        view = json.loads((E.RECORDED_TASKS / 'task-view-TASK-1.json').read_text(encoding='utf-8'))
        (pointer,) = [r for r in view['task']['references'] if '/proposal.md@' in r]
        return pointer

    def test_sample_authorities_resolve_the_whole_chain_and_say_so(self):
        # (The name is recorded in evidence/test-profile/test-ids.json from before E-01.5, when the attempt sample
        # answered. Since E-01.5 the example's attempts are built with the dispatcher's own constructors, not by a
        # dispatch, and answered by the Agent Server fixture's cited core through the attempt resolver: they resolve
        # with their mode stated, fixture, and say so.)
        # The example's statements are the Owner conversation store's (lineage_example.example: build_conversations
        # and cite_store in a commit after the declaring one): they resolve authoritatively. The recorded tasks'
        # proposal pointer, pinned at the design commit, is superseded by that later commit, and says so.
        projection = self.projections['fixture']
        self.assertEqual(projection['format'], T.PROJECTION_FORMAT)
        roles = {node['role'] for node in projection['nodes']}
        self.assertEqual(roles, {'statement', 'objective', 'design', 'work', 'attempt'})
        superseded = self.recorded_proposal_pointer()
        for node in projection['nodes']:
            with self.subTest(node=node['reference']):
                freshness = T.SUPERSEDED if node['reference'] == superseded else T.CURRENT
                self.assertEqual((node['resolution']['outcome'], node['freshness']), (L.RESOLVED, freshness))
                expected = T.FIXTURE if node['role'] == 'attempt' else T.AUTHORITATIVE
                self.assertEqual(node['authority_mode'], expected)
                if expected == T.FIXTURE:
                    self.assertTrue(node['authority'].startswith('FIXTURE'))
                if node['role'] == 'statement':
                    self.assertEqual((node['kind'], node['authority']), ('message', 'Owner conversation store'))
        self.assertEqual(sorted(n['reference'] for n in projection['nodes'] if n['role'] == 'statement'), [M1, M2])
        self.assertEqual(projection['verdict'], 'incomplete')
        self.assertEqual({u['reason'] for u in projection['uncertainties']}, {'fixture-authority', 'superseded'})
        self.assertEqual({u['reference'] for u in projection['uncertainties'] if u['reason'] == 'fixture-authority'},
                         {n['reference'] for n in projection['nodes'] if n['authority_mode'] == T.FIXTURE})
        self.assertEqual(len([n for n in projection['nodes'] if n['authority_mode'] == T.FIXTURE]), 2)
        self.assertEqual({u['reference'] for u in projection['uncertainties'] if u['reason'] == 'superseded'},
                         {superseded})

    def test_the_chain_runs_from_the_original_message_to_the_attempts(self):
        projection = self.projections['fixture']
        root = projection['root']
        self.assertIn((M1, root, T.ORIGINATES), edges(projection))
        self.assertIn((root, M2, T.ACCEPTED_BY), edges(projection))
        self.assertEqual({t for _, t, _ in edges(projection, T.FULFILLED_BY)}, {'backlog:TASK-1', 'backlog:TASK-2'})
        store_mod = E.store_module()
        executed = [e for e in projection['edges'] if e['relation'] == T.EXECUTED_BY]
        # each attempt is the typed attempt build_dispatched made for its task (N8: the expectation is what it made,
        # recorded in setUpClass, never read back from the projection): its conversation the reserved one of its key
        self.assertEqual(sorted(work for work, _, _ in self.dispatched), ['TASK-1', 'TASK-2'])
        for work, key, cid in self.dispatched:
            self.assertEqual(cid, store_mod.conversation_id_for(key))
        self.assertEqual({(e['from'], e['to']) for e in executed},
                         {(f'backlog:{work}', f'openhands:conversation/{cid}') for work, _, cid in self.dispatched})
        self.assertEqual(sorted(e['provenance'][0]['operation_key'] for e in executed),
                         sorted(key for _, key, _ in self.dispatched))
        self.assertEqual({e['from'] for e in executed}, {'backlog:TASK-1', 'backlog:TASK-2'})
        self.assertEqual(len(edges(projection, T.SHAPED_BY)), 3)  # proposal, design, spec at the traced commit
        # D2: Q1's quote is located in the statement's durable bytes, read from the Owner conversation store, and
        # its span verifies.
        quote = by_reference(projection)[M1]['quotes'][0]
        self.assertEqual((quote['item'], quote['outcome']), ('Q1', L.RESOLVED))
        self.assertTrue(quote['span'].startswith(M1 + '#span:'))
        span = L.parse(quote['span'])
        content = QUAL02_MESSAGE1.read_bytes()
        self.assertEqual(L.span_bytes(span, content), content.rstrip(b'\n'))

    def test_every_edge_carries_its_provenance(self):
        for projection in self.projections.values():
            for edge in projection['edges']:
                with self.subTest(edge=(edge['from'], edge['relation'])):
                    self.assertTrue(edge['provenance'])
                    for provenance in edge['provenance']:
                        self.assertTrue(provenance['record'])
                        self.assertIn('authority', provenance)
            for edge in projection['edges']:
                provenance = edge['provenance'][0]
                if edge['relation'] in (T.ORIGINATES, T.ACCEPTED_BY, T.SHAPED_BY):
                    self.assertRegex(provenance['revision'], '^[0-9a-f]{40}$')
                if edge['relation'] == T.EXECUTED_BY:
                    self.assertEqual(provenance['record'], T.STORE_RECORD)
                    self.assertEqual(provenance['event_seq'], 0)
                    self.assertIsInstance(provenance['event_id'], int)
                    self.assertRegex(provenance['intent_digest'], '^[0-9a-f]{64}$')
                    self.assertTrue(provenance['operation_key'].startswith('attempt/v1/TASK-'))   # dispatched

    def test_the_real_registry_marks_statements_and_attempts_unavailable(self):
        # (The name is recorded in evidence/test-profile/test-ids.json from before U-02.2, when no authority held the
        # statements. Since U-02.2 the real registry resolves them from the Owner conversation store; only the
        # attempts are unavailable: since E-01.5 the kind is implemented, and this registry configures no Agent
        # Server transport for it.)
        projection = self.projections['real']
        for node in projection['nodes']:
            with self.subTest(node=node['reference']):
                if node['role'] == 'statement':  # asked of the real store since U-02.2: resolved there
                    self.assertEqual((node['authority_mode'], node['resolution']['outcome'],
                                      node['resolution']['code']),
                                     (T.AUTHORITATIVE, L.RESOLVED, None))
                elif node['role'] == 'attempt':
                    self.assertEqual((node['authority_mode'], node['resolution']['outcome'],
                                      node['resolution']['code']),
                                     (T.UNAVAILABLE, L.AUTHORITY_UNAVAILABLE, 'RESOLVER_NOT_CONFIGURED'))
                else:
                    self.assertEqual((node['authority_mode'], node['resolution']['outcome']),
                                     (T.AUTHORITATIVE, L.RESOLVED))
        self.assertEqual({u['reason'] for u in projection['uncertainties']}, {'unresolved', 'superseded'})
        self.assertEqual({u['reference'] for u in projection['uncertainties'] if u['reason'] == 'unresolved'},
                         {n['reference'] for n in projection['nodes'] if n['role'] == 'attempt'})
        self.assertEqual({u['reference'] for u in projection['uncertainties'] if u['reason'] == 'superseded'},
                         {self.recorded_proposal_pointer()})
        quote = by_reference(projection)[M1]['quotes'][0]
        self.assertEqual((quote['item'], quote['outcome']), ('Q1', L.RESOLVED))
        self.assertEqual(projection['authority_modes'], {'authoritative': 11, 'fixture': 0, 'sample': 0,
                                                         'unavailable': 2})
        # The same edges as with the fixture: the links are asserted by records, not by the authorities.
        self.assertEqual(edges(projection), edges(self.projections['fixture']))


QUAL02_MESSAGE1 = E.CORPUS / 'qual-02' / 'message-1.txt'


# ---------------------------------------------------------------------------
# Read-only

class Wording(unittest.TestCase):
    """Review of dispatch 19, N7: the example's attempts are built with the dispatcher's own constructors in a
    throwaway store, not dispatched; the development reference and the lineage README say so."""
    category = 'unit'

    def test_the_example_attempts_are_not_called_dispatched(self):
        repo = HERE.parents[2]
        for path in (repo / 'docs' / 'development.md', HERE.parent / 'README.md'):
            text = ' '.join(path.read_text(encoding='utf-8').split())
            with self.subTest(path=path.name):
                for claim in ("attempts dispatched in a throwaway", "attempts are dispatched in a throwaway",
                              "attempts dispatched in an integration store", "attempts are dispatched in an"):
                    self.assertFalse(claim in text, f'{path.name} says: {claim}')
                self.assertTrue("built with the dispatcher's own constructors" in text, path.name)


class ReadOnly(Case):
    def test_the_traversal_writes_nothing_and_asks_only_reads(self):
        self.reserve_tasks('TASK-1', 'TASK-2')
        before = tree_state(self.repo), store_state(self.store)
        calls = []
        real_popen = subprocess.Popen

        class Recording(real_popen):
            def __init__(self, args, *more, **kwargs):
                calls.append([str(arg) for arg in args])
                super().__init__(args, *more, **kwargs)

        # The real process interaction: the Backlog runner seam left at its default, so the
        # fake Backlog.md is launched as Backlog.md is (one process tree, run_tree), and every
        # process the traversal starts is recorded.
        with mock.patch.object(R.planning.Backlog, 'runner', None), \
                mock.patch.object(subprocess, 'Popen', Recording):
            projection = self.trace()
        self.assertEqual(projection['verdict'], 'incomplete')
        self.assertEqual((tree_state(self.repo), store_state(self.store)), before)
        backlog_prefix = E.FAKE_BACKLOG
        for argv in calls:
            with self.subTest(argv=argv[:4]):
                # No git process: the repository is read in this process (decision 0014).
                self.assertNotEqual(Path(argv[0]).name.lower().removesuffix('.exe'), 'git')
                self.assertEqual(argv[:len(backlog_prefix)], backlog_prefix)
                self.assertIn(tuple(argv[len(backlog_prefix):][:2]), {('task', 'list'), ('task', 'view')})
        self.assertFalse(any('openspec' in Path(str(a[0])).name.lower() for a in calls))
        # The default runner launched Backlog.md: its reads went through it.
        self.assertTrue([argv for argv in calls if argv[:len(backlog_prefix)] == backlog_prefix])
        logged = self.backlog_argv()
        self.assertTrue(logged)
        for argv in logged:
            self.assertIn(tuple(argv[:2]), {('task', 'list'), ('task', 'view')})
            self.assertNotIn('-s', argv)

    def test_never_reads_a_backlog_status(self):
        class Trapped(dict):
            def __getitem__(self, key):
                if key not in ('id', 'references'):
                    raise AssertionError(f'the traversal read {key!r}')
                return super().__getitem__(key)
            get = None

        recorded = json.loads((E.RECORDED_TASKS / 'task-list.json').read_text(encoding='utf-8'))['tasks']
        trapped = [Trapped(task) for task in recorded]
        self.reserve_tasks('TASK-1', 'TASK-2')
        with mock.patch.object(R.ReadOnlyBacklog, 'list_tasks', return_value=trapped), \
                mock.patch.object(R.ReadOnlyBacklog, 'view', side_effect=lambda task_id: Trapped(
                    {'id': task_id, 'status': 'Done'})):
            projection = self.trace()
        self.assertEqual({t for _, t, _ in edges(projection, T.FULFILLED_BY)}, {'backlog:TASK-1', 'backlog:TASK-2'})
        text = json.dumps(projection)
        for word in ('To Do', 'Done', 'isReady', 'status', 'readiness'):
            self.assertNotIn(word, text)

    def test_the_store_is_read_beside_an_open_writer_and_never_migrated(self):
        self.reserve_tasks('TASK-2')
        store_mod = E.store_module()
        with store_mod.open_store(self.store) as writer:
            writer.reserve(E.operation_key('TASK-1'), E.task_intent('TASK-1'), actor='writer')
            before = store_state(self.store)
            projection = self.trace()
            self.assertEqual(store_state(self.store), before)
            writer.transition(E.operation_key('TASK-1'), 'dispatched', actor='writer')  # the writer is unaffected
        self.assertEqual(len(edges(projection, T.EXECUTED_BY)), 2)  # the uncheckpointed reservation is seen

    def test_a_store_that_needs_a_migration_is_refused_not_migrated(self):
        store_mod = E.store_module()
        old = self.tmp / 'm'
        old.mkdir()
        shutil.copy(store_mod.MIGRATIONS_DIR / '0001_receipts_and_projections.sql', old)
        self.store.parent.mkdir()
        store_mod.open_store(self.store, migrations_dir=old).close()
        before = store_state(self.store)
        projection = self.trace()
        self.assertUncertain(projection, projection['root'], 'enumeration-unavailable', 'STORE_UNAVAILABLE')
        self.assertEqual(store_state(self.store), before)

    def test_an_absent_store_is_not_created(self):
        projection = self.trace()
        self.assertUncertain(projection, projection['root'], 'enumeration-unavailable', 'STORE_UNAVAILABLE')
        self.assertFalse(self.store.parent.exists())

    def test_a_database_of_another_kind_is_refused(self):
        self.store.parent.mkdir()
        conn = sqlite3.connect(self.store)
        conn.execute('CREATE TABLE attempt (x)')
        conn.commit()
        conn.close()
        before = hashlib.sha256(self.store.read_bytes()).hexdigest()
        projection = self.trace()
        self.assertUncertain(projection, projection['root'], 'enumeration-unavailable', 'STORE_UNAVAILABLE')
        self.assertEqual(hashlib.sha256(self.store.read_bytes()).hexdigest(), before)

    def test_the_read_only_view_cannot_write(self):
        self.reserve_tasks('TASK-1')
        with T.ReadOnlyIntegrationStore(self.store) as store:
            for name in ('reserve', 'transition', 'rebuild_projection', 'backup', 'reconcile', 'close_restore_epoch'):
                self.assertFalse(hasattr(store, name), name)
            with self.assertRaises(sqlite3.Error):
                store._conn.execute("UPDATE attempt SET state = 'failed'")


# ---------------------------------------------------------------------------
# Negative resolution fixtures

class ChangedRevision(Case):
    def test_a_design_amended_after_the_task_was_pinned_is_superseded(self):
        self.reserve_tasks('TASK-1', 'TASK-2')
        design_md = self.repo / CHANGE_DIR / 'design.md'
        design_md.write_bytes(design_md.read_bytes() + b'\nAmended after the tasks were created.\n')
        amended = self.commit('amend the design')
        pinned = self.pointer('design.md')
        projection = self.trace()
        node = by_reference(projection)[pinned]
        self.assertEqual((node['resolution']['outcome'], node['resolution']['observed_revision']),
                         (L.RESOLVED, self.design))
        self.assertEqual((node['current']['outcome'], node['current']['observed_revision']), (L.RESOLVED, amended))
        self.assertNotEqual(node['current']['observed_digest'], node['resolution']['observed_digest'])
        self.assertEqual(node['freshness'], T.SUPERSEDED)
        self.assertUncertain(projection, pinned, 'superseded', 'SUPERSEDED')
        unchanged = by_reference(projection)[self.pointer('proposal.md')]
        self.assertEqual(unchanged['freshness'], T.CURRENT)

    def test_an_amended_objective_is_superseded_but_its_pinned_reading_holds(self):
        self.reserve_tasks('TASK-1', 'TASK-2')
        E.edit(self.repo, f'{CHANGE_DIR}/proposal.md', b'within 5 minutes of being added, so customers',
               b'within 2 minutes of being added, so customers')
        self.commit('amend O1')
        projection = self.trace()
        node = by_reference(projection)[projection['root']]
        self.assertEqual((node['resolution']['outcome'], node['freshness']), (L.RESOLVED, T.SUPERSEDED))
        self.assertIn('within 5 minutes', node['facts']['statement'])  # what was known at the pin
        self.assertUncertain(projection, projection['root'], 'superseded', 'SUPERSEDED')

    def test_a_pinned_revision_the_project_does_not_hold(self):
        projection = self.trace(f'outcome:{OUTCOME}@{"0" * 40}')
        self.assertUncertain(projection, projection['root'], 'unresolved', 'OUTCOME_REVISION_MISSING')


class DigestMismatch(Case):
    def test_a_design_pointer_with_another_digest(self):
        good = self.pointer('design.md')
        bad = good[:-64] + hashlib.sha256(b'not the design').hexdigest()
        self.fake_backlog(('TASK-1', [bad]))
        self.reserve_tasks('TASK-1')
        projection = self.trace(snapshot=None)
        node = by_reference(projection)[bad]
        self.assertEqual((node['resolution']['outcome'], node['resolution']['code']),
                         (L.DIGEST_MISMATCH, 'POINTER_DIGEST_MISMATCH'))
        self.assertEqual(node['resolution']['observed_digest'], good[-64:])
        self.assertUncertain(projection, bad, 'unresolved', 'POINTER_DIGEST_MISMATCH')

    def test_d2_a_span_whose_no_break_space_became_a_space(self):
        content = QUAL08.read_bytes()
        start = content.index('1234,5'.encode())
        quote = content[start:content.index('€…'.encode()) + len('€'.encode())]
        self.assertIn(NBSP, quote)
        relayed = quote.replace(NBSP, b' ')
        digest = hashlib.sha256(relayed).hexdigest()
        # The anchor's digest taken over the relayed bytes, at the durable offsets; and the
        # relayed bytes' own length, which now ends inside a character of the durable text.
        bad = f'{Q8}#span:{start}+{len(quote)}:sha256:{digest}'
        short = f'{Q8}#span:{start}+{len(relayed)}:sha256:{digest}'
        good = L.span_reference(THREAD08, 'Q08msg1', content, start, len(quote)).text
        for reference, outcome, code in ((bad, L.DIGEST_MISMATCH, 'SPAN_DIGEST_MISMATCH'),
                                         (short, L.DIGEST_MISMATCH, 'SPAN_NOT_ON_CHARACTER_BOUNDARY'),
                                         (good, L.RESOLVED, None)):
            with self.subTest(code=code):
                self.setUp()
                E.edit(self.repo, f'{CHANGE_DIR}/proposal.md', b'- source: Q1, conversation:qual-02/message-2\n',
                       f'- source: Q1, conversation:qual-02/message-2, {reference}\n'.encode())
                self.commit('cite a span of qual-08')
                self.reserve_tasks('TASK-1', 'TASK-2')
                projection = self.trace(f'outcome:{OUTCOME}')
                node = by_reference(projection)[reference]
                self.assertEqual(node['resolution']['outcome'], outcome)
                if code:
                    self.assertEqual(node['resolution']['code'], code)
                    self.assertUncertain(projection, reference, 'unresolved', code)
                else:
                    self.assertEqual(node['resolution']['observed_digest'], hashlib.sha256(quote).hexdigest())

    def test_d2_a_quote_whose_no_break_space_became_a_space(self):
        content = QUAL08.read_bytes()
        first_line = content.split(b'\n')[0]
        for quote, expected in ((first_line.replace(NBSP, b' '), 'QUOTE_NOT_IN_SOURCE'),
                                (first_line, None)):
            with self.subTest(expected=expected):
                self.setUp()
                E.edit(self.repo, f'{CHANGE_DIR}/proposal.md', b'- source: conversation:qual-02/message-1\n',
                       f'- source: {Q8}\n'.encode())
                proposal = self.repo / CHANGE_DIR / 'proposal.md'
                data = proposal.read_bytes()
                old = data[data.index(b'```text\n', data.index(b'#### Q1')) + 8:]
                old = old[:old.index(b'\n```')]
                E.edit(self.repo, f'{CHANGE_DIR}/proposal.md', old, quote)
                self.commit('quote qual-08')
                projection = self.trace(f'outcome:{OUTCOME}')
                node = by_reference(projection)[Q8]
                if expected:
                    self.assertEqual(node['quotes'][0]['outcome'], L.DIGEST_MISMATCH)
                    self.assertUncertain(projection, Q8, 'quote-unverified', expected)
                else:
                    self.assertEqual(node['quotes'][0]['outcome'], L.RESOLVED)
                    span = L.parse(node['quotes'][0]['span'])
                    self.assertEqual(L.span_bytes(span, content), first_line)


class MissingNode(Case):
    def test_the_statement_is_missing(self):
        for path in (f'{CHANGE_DIR}/proposal.md', f'{CHANGE_DIR}/.openspec.yaml'):
            data = (self.repo / path).read_bytes()
            (self.repo / path).write_bytes(data.replace(b'conversation:qual-02/message-2',
                                                        f'conversation:{THREAD02}/Q02msg9'.encode()))
        declared = self.commit('cite a message the store does not hold')
        self.reserve_tasks('TASK-1', 'TASK-2')
        projection = self.trace(f'outcome:{OUTCOME}@{declared}')
        missing = f'conversation:{THREAD02}/Q02msg9'      # a thread of the store; no such message in it
        node = by_reference(projection)[missing]
        self.assertEqual((node['resolution']['outcome'], node['resolution']['code']), (L.MISSING, 'MESSAGE_MISSING'))
        self.assertUncertain(projection, missing, 'unresolved', 'MESSAGE_MISSING')
        self.assertIn((projection['root'], missing, T.ACCEPTED_BY), edges(projection))

    def test_a_task_id_whose_task_does_not_exist(self):
        self.reserve_tasks('TASK-1', 'TASK-2', 'TASK-9')
        projection = self.trace()
        node = by_reference(projection)['backlog:TASK-9']
        self.assertEqual((node['resolution']['outcome'], node['resolution']['code']), (L.MISSING, 'WORK_MISSING'))
        self.assertUncertain(projection, 'backlog:TASK-9', 'unresolved', 'WORK_MISSING')
        edge = [e for e in projection['edges'] if e['to'] == 'backlog:TASK-9' and e['relation'] == T.FULFILLED_BY]
        self.assertEqual(edge[0]['provenance'][0]['record'], T.STORE_RECORD)  # asserted by the reservation

    def test_a_reservation_whose_conversation_has_no_attempt_record(self):
        # (Until E-01.5 the attempt sample answered; since, the attempt resolver reads the dispatcher's record: a
        # reservation that was never dispatched and confirmed is no attempt of the Agent Server's.)
        self.reserve(('work-TASK-1/implement/revision-1', E.task_intent('TASK-1')),
                     ('work-TASK-2/implement/revision-2', E.task_intent('TASK-2')))
        core = FA.AC.AgentServerCore()
        self.addCleanup(core.close)
        attempts = FA.FixtureAttempts(self.tmp / 'fixture-root')
        auth = T.Authorities(R.build_registry(project=self.repo, backlog=E.FAKE_BACKLOG,
                                              conversations=E.conversations_path(self.repo),
                                              attempts=RA.AttemptResolver(self.store, core, attempts.read_artifact)))
        projection = E.run_trace(f'outcome:{OUTCOME}@{self.declared}', auth, self.repo, self.store)
        conversation = E.store_module().conversation_id_for('work-TASK-2/implement/revision-2')
        reference = f'openhands:conversation/{conversation}'
        node = by_reference(projection)[reference]
        self.assertEqual((node['resolution']['outcome'], node['resolution']['code'], node['authority_mode']),
                         (L.MISSING, 'ATTEMPT_NOT_CONFIRMED', T.AUTHORITATIVE))
        self.assertUncertain(projection, reference, 'unresolved', 'ATTEMPT_NOT_CONFIRMED')
        self.assertEqual(core.calls, [], 'no create was confirmed: the Agent Server is not asked')

    def test_an_outcome_declared_by_no_change(self):
        self.reserve_tasks('TASK-1', 'TASK-2')
        projection = self.trace(f'outcome:{OTHER_OUTCOME}')
        self.assertUncertain(projection, f'outcome:{OTHER_OUTCOME}', 'unresolved', 'OUTCOME_MISSING')
        self.assertUncertain(projection, f'outcome:{OTHER_OUTCOME}', 'missing-link', 'NO_TASK_FOR_OBJECTIVE')
        self.assertEqual([n['role'] for n in projection['nodes']], ['objective'])

    def test_a_task_without_an_attempt(self):
        self.reserve_tasks('TASK-2')
        projection = self.trace()
        self.assertUncertain(projection, 'backlog:TASK-1', 'missing-link', 'NO_ATTEMPT_FOR_TASK')

    def test_no_store_and_no_backlog_are_explicit(self):
        projection = self.trace(store=False)
        self.assertUncertain(projection, projection['root'], 'enumeration-unavailable', 'STORE_NOT_CONFIGURED')
        auth = E.authorities(self.repo)
        projection = T.trace(f'outcome:{OUTCOME}', auth, project=self.repo)
        self.assertUncertain(projection, f'outcome:{OUTCOME}', 'enumeration-unavailable', 'BACKLOG_NOT_CONFIGURED')
        self.assertUncertain(projection, f'outcome:{OUTCOME}', 'missing-link', 'NO_TASK_FOR_OBJECTIVE')

    def test_a_backlog_that_cannot_list(self):
        with mock.patch.dict(os.environ, {'FAKE_BACKLOG_MODE': 'bad-envelope'}):
            projection = self.trace(snapshot=None)
        self.assertUncertain(projection, projection['root'], 'enumeration-unavailable', 'BACKLOG_LIST_FAILED')
        projection = self.trace(backlog=[str(self.tmp / 'no-such-backlog.exe')])
        self.assertUncertain(projection, projection['root'], 'enumeration-unavailable', 'BACKLOG_UNAVAILABLE')

    def test_a_project_that_is_not_a_repository(self):
        plain = self.tmp / 'plain'
        plain.mkdir()
        auth = T.Authorities(R.build_registry(project=plain, backlog=E.FAKE_BACKLOG))
        with fx.ceiling(self.tmp):
            projection = T.trace(f'outcome:{OUTCOME}', auth, project=plain, backlog=E.FAKE_BACKLOG)
        self.assertUncertain(projection, f'outcome:{OUTCOME}', 'enumeration-unavailable', 'PROJECT_UNAVAILABLE')
        self.assertUncertain(projection, f'outcome:{OUTCOME}', 'unresolved', 'PROJECT_UNAVAILABLE')


class MovedOrGone(Case):
    def archive(self, change_file=None):
        (self.repo / 'openspec' / 'changes' / 'archive').mkdir()
        fx.git(self.repo, 'mv', CHANGE_DIR, ARCHIVED_DIR)
        if change_file:
            change_file(self.repo / ARCHIVED_DIR)
        return self.commit('openspec archive qual-02')

    def test_moved_by_archive_with_an_identical_blob(self):
        self.reserve_tasks('TASK-1', 'TASK-2')
        archived = self.archive()
        projection = self.trace(f'outcome:{OUTCOME}')  # current: the outcome resolves at the archive path
        nodes = by_reference(projection)
        pointer = self.pointer('design.md')
        node = nodes[pointer]
        self.assertEqual((node['resolution']['outcome'], node['current']['code']), (L.RESOLVED, 'POINTER_ARTIFACT_MISSING'))
        self.assertEqual(node['freshness'], T.MOVED)
        self.assertEqual(node['moved_to'], {'path': f'{ARCHIVED_DIR}/design.md', 'revision': archived,
                                            'digest': L.parse(pointer).digest})
        self.assertUncertain(projection, pointer, 'moved', 'DESIGN_ARTIFACT_MOVED')
        self.assertNotIn((pointer, 'gone', 'DESIGN_ARTIFACT_GONE'), reasons(projection))
        root = nodes[projection['root']]
        self.assertEqual(root['facts']['change'], ARCHIVED_DIR)
        self.assertUncertain(projection, projection['root'], 'missing-link', 'DESIGN_ARCHIVED_AT_REVISION')
        self.assertEqual({t for _, t, _ in edges(projection, T.FULFILLED_BY)}, {'backlog:TASK-1', 'backlog:TASK-2'})

    def test_moved_and_changed(self):
        self.reserve_tasks('TASK-1', 'TASK-2')
        self.archive(lambda d: (d / 'design.md').write_bytes((d / 'design.md').read_bytes() + b'\nChanged.\n'))
        projection = self.trace()
        pointer = self.pointer('design.md')
        self.assertEqual(by_reference(projection)[pointer]['freshness'], T.MOVED_CHANGED)
        self.assertUncertain(projection, pointer, 'moved-changed', 'DESIGN_ARTIFACT_MOVED_AND_CHANGED')
        self.assertEqual(by_reference(projection)[self.pointer('proposal.md')]['freshness'], T.MOVED)

    def test_gone(self):
        self.reserve_tasks('TASK-1', 'TASK-2')
        fx.git(self.repo, 'rm', '-r', '--quiet', CHANGE_DIR)
        self.commit('remove qual-02')
        projection = self.trace()  # pinned at the declaring commit: still readable there
        pointer = self.pointer('design.md')
        node = by_reference(projection)[pointer]
        self.assertEqual((node['resolution']['outcome'], node['freshness']), (L.RESOLVED, T.GONE))
        self.assertUncertain(projection, pointer, 'gone', 'DESIGN_ARTIFACT_GONE')
        self.assertNotIn('moved_to', node)
        self.assertUncertain(projection, projection['root'], 'current-unresolved', 'OUTCOME_MISSING')

    def test_an_archived_artifact_of_another_change_is_not_a_move(self):
        self.reserve_tasks('TASK-1', 'TASK-2')
        other = self.repo / 'openspec' / 'changes' / 'archive' / '2026-11-07-other-change'
        shutil.copytree(self.repo / CHANGE_DIR, other)
        (other / '.openspec.yaml').write_bytes(b'schema: intent-driven\n')  # declares nothing
        fx.git(self.repo, 'rm', '-r', '--quiet', CHANGE_DIR)
        self.commit('remove qual-02; an archived change holds the same file names and bytes')
        projection = self.trace()
        pointer = self.pointer('design.md')
        self.assertEqual(by_reference(projection)[pointer]['freshness'], T.GONE)
        self.assertUncertain(projection, pointer, 'gone', 'DESIGN_ARTIFACT_GONE')

    def test_a_current_reading_that_failed_is_not_gone(self):
        self.reserve_tasks('TASK-1', 'TASK-2')
        failed = lambda resolver, reference: L.answer(  # noqa: E731
            reference, L.AUTHORITY_UNAVAILABLE, resolver.authority, 'GIT_FAILED', 'boom', query='current')
        with mock.patch.object(R.DesignResolver, 'current', autospec=True, side_effect=failed):
            projection = self.trace()
        pointer = self.pointer('design.md')
        node = by_reference(projection)[pointer]
        self.assertEqual((node['resolution']['outcome'], node['freshness']), (L.RESOLVED, T.UNKNOWN))
        self.assertNotIn('moved_to', node)
        self.assertUncertain(projection, pointer, 'current-unresolved', 'GIT_FAILED')
        self.assertFalse({'gone', 'moved'} & {u['reason'] for u in projection['uncertainties']})

    def test_two_archived_copies_are_ambiguous(self):
        self.reserve_tasks('TASK-1', 'TASK-2')
        self.archive(lambda d: shutil.copytree(d, d.parent / f'2026-11-08-{CHANGE}'))
        projection = self.trace()
        pointer = self.pointer('design.md')
        self.assertUncertain(projection, pointer, 'current-unresolved', 'DESIGN_ARCHIVE_AMBIGUOUS')


class Ambiguous(Case):
    def test_two_changes_declare_the_same_outcome(self):
        shutil.copytree(self.repo / CHANGE_DIR, self.repo / 'openspec' / 'changes' / 'qual-02-copy')
        self.commit('a second change declares the outcome')
        self.reserve_tasks('TASK-1', 'TASK-2')
        projection = self.trace(f'outcome:{OUTCOME}')
        node = by_reference(projection)[f'outcome:{OUTCOME}']
        self.assertEqual((node['resolution']['outcome'], node['resolution']['code']), (L.AMBIGUOUS, 'OUTCOME_AMBIGUOUS'))
        self.assertUncertain(projection, f'outcome:{OUTCOME}', 'unresolved', 'OUTCOME_AMBIGUOUS')
        self.assertNotIn('statement', {n['role'] for n in projection['nodes']})
        # The reservations still cite the outcome; the tasks are reached through them only.
        provenance = [e['provenance'][0]['record'] for e in projection['edges'] if e['relation'] == T.FULFILLED_BY]
        self.assertEqual(len(provenance), 2)
        self.assertEqual(set(provenance), {T.STORE_RECORD})


# ---------------------------------------------------------------------------
# Statements, intents and the contract of the projection

class Statements(Case):
    def test_an_acceptance_of_a_scheme_no_kind_uses(self):
        for path in (f'{CHANGE_DIR}/proposal.md', f'{CHANGE_DIR}/.openspec.yaml'):
            data = (self.repo / path).read_bytes()
            (self.repo / path).write_bytes(data.replace(b'acceptance: conversation:qual-02/message-2',
                                                        b'acceptance: decision:0008'))
        self.commit('accept by a decision record')
        self.reserve_tasks('TASK-1', 'TASK-2')
        projection = self.trace(f'outcome:{OUTCOME}')
        node = by_reference(projection)['decision:0008']
        self.assertEqual((node['kind'], node['resolution']['outcome'], node['authority_mode']),
                         ('unknown', L.UNSUPPORTED_KIND, T.UNAVAILABLE))
        self.assertUncertain(projection, 'decision:0008', 'unresolved', 'REFERENCE_UNSUPPORTED_SCHEME')

    def test_sources_that_reach_no_statement(self):
        E.edit(self.repo, f'{CHANGE_DIR}/proposal.md', b'- source: Q1, conversation:qual-02/message-2\n',
               b'- source: CL1, Q7\n')
        self.commit('O1 cites no statement')
        self.reserve_tasks('TASK-1', 'TASK-2')
        projection = self.trace(f'outcome:{OUTCOME}')
        root = projection['root']
        self.assertUncertain(projection, root, 'missing-link', 'NO_SOURCE_STATEMENT')
        self.assertUncertain(projection, root, 'missing-link', 'SOURCE_ITEM_MISSING')
        self.assertEqual(edges(projection, T.ORIGINATES), set())
        # CL1 is not an original quote: it is not followed (its own source, Q1, is not read).
        self.assertNotIn('malformed-reference', {u['reason'] for u in projection['uncertainties']})
        self.assertNotIn('conversation:qual-02/message-1', by_reference(projection))

    def quote_block(self):
        """(start, end) of Q1's quote bytes in the throwaway proposal."""
        data = (self.repo / CHANGE_DIR / 'proposal.md').read_bytes()
        start = data.index(b'```text\n', data.index(b'#### Q1')) + len(b'```text\n')
        return data, start, data.index(b'\n```', start)

    def test_an_original_quote_without_its_quote(self):
        data, start, end = self.quote_block()
        (self.repo / CHANGE_DIR / 'proposal.md').write_bytes(data[:start] + data[end + 1:])
        E.cite_store(self.repo)        # Q1's source must resolve for its quote to be looked for
        self.commit('Q1 without its quote')
        projection = self.trace(f'outcome:{OUTCOME}')
        self.assertUncertain(projection, M1, 'quote-unverified', 'QUOTE_MISSING')

    def test_an_original_quote_of_a_thread(self):
        E.edit(self.repo, f'{CHANGE_DIR}/proposal.md', b'- source: conversation:qual-02/message-1\n',
               b'- source: conversation:qual-02\n')
        self.commit('Q1 quotes a thread')
        projection = self.trace(f'outcome:{OUTCOME}')
        self.assertUncertain(projection, 'conversation:qual-02', 'quote-unverified', 'QUOTE_SOURCE_NOT_A_MESSAGE')
        self.assertIn(('conversation:qual-02', projection['root'], T.ORIGINATES), edges(projection))

    def test_an_intent_record_that_changed_or_cannot_be_read(self):
        class Tampered(T.Authorities):
            """Answers the objective with another digest, or another declaring change."""
            change = None

            def ask(self, reference, method):
                result, mode = super().ask(reference, method)
                if reference.kind == 'objective' and result.resolved:
                    if self.change:
                        result = L.Resolution(**{**result.__dict__, 'facts': {**result.facts, 'change': self.change}})
                    else:
                        result = L.Resolution(**{**result.__dict__, 'observed_digest': '0' * 64})
                return result, mode

        self.reserve_tasks('TASK-1', 'TASK-2')
        for change, code in ((None, 'INTENT_RECORD_CHANGED'), ('openspec/changes/absent', 'INTENT_RECORD_UNREADABLE')):
            with self.subTest(code=code):
                auth = Tampered(E.registry(self.repo), S.sample_authorities())
                auth.change = change
                projection = E.run_trace(f'outcome:{OUTCOME}', auth, self.repo, self.store)
                self.assertUncertain(projection, f'outcome:{OUTCOME}', 'missing-link', code)
                # The resolver's own facts still give the direct source; Q1 is not followed.
                self.assertEqual({f for f, _, _ in edges(projection, T.ORIGINATES)}, {'conversation:qual-02/message-2'})

    def test_a_malformed_source_reference(self):
        E.edit(self.repo, f'{CHANGE_DIR}/proposal.md', b'- source: Q1, conversation:qual-02/message-2\n',
               b'- source: Q1, conversation:qual-02/message-2, backlog:task-1\n')
        self.commit('a malformed source')
        projection = self.trace(f'outcome:{OUTCOME}')
        self.assertUncertain(projection, 'backlog:task-1', 'malformed-reference', 'REFERENCE_MALFORMED')

    def test_a_quote_that_occurs_twice(self):
        E.edit(self.repo, f'{CHANGE_DIR}/proposal.md', b'- source: conversation:qual-02/message-1\n',
               f'- source: {Q8}\n'.encode())
        proposal = self.repo / CHANGE_DIR / 'proposal.md'
        data = proposal.read_bytes()
        old = data[data.index(b'```text\n', data.index(b'#### Q1')) + 8:]
        E.edit(self.repo, f'{CHANGE_DIR}/proposal.md', old[:old.index(b'\n```')], b'\xc2\xa0\xe2\x82\xac')
        self.commit('a quote that occurs twice')
        projection = self.trace(f'outcome:{OUTCOME}')
        self.assertUncertain(projection, Q8, 'quote-unverified', 'QUOTE_SPAN_AMBIGUOUS')

    def test_a_quote_cannot_be_checked_without_content(self):
        class NoContent(T.Authorities):
            """The statement resolves, but its authority returns no content."""
            def content(self, reference):
                return None
        E.cite_store(self.repo)
        self.commit('the intent record cites the Owner conversation store')
        auth = NoContent(E.registry(self.repo), S.sample_authorities())
        self.reserve_tasks('TASK-1', 'TASK-2')
        projection = E.run_trace(f'outcome:{OUTCOME}', auth, self.repo, self.store)
        self.assertEqual(by_reference(projection)[M1]['resolution']['outcome'], L.RESOLVED)
        self.assertUncertain(projection, M1, 'quote-unverified', 'QUOTE_SOURCE_UNREADABLE')


class StoreStatements(Case):
    """The statements of the chain read from the real Owner conversation store (plan leaf U-02.2)."""

    def test_the_whole_chain_resolves_against_the_store(self):
        E.cite_store(self.repo)
        cited = self.commit('the intent record cites the Owner conversation store')
        self.reserve_tasks('TASK-1', 'TASK-2')
        projection = self.trace(f'outcome:{OUTCOME}@{cited}')
        root = projection['root']
        self.assertIn((M1, root, T.ORIGINATES), edges(projection))
        self.assertIn((root, M2, T.ACCEPTED_BY), edges(projection))
        nodes = by_reference(projection)
        for reference in (M1, M2):
            with self.subTest(reference=reference):
                node = nodes[reference]
                self.assertEqual((node['kind'], node['role'], node['authority'], node['authority_mode'],
                                  node['resolution']['outcome'], node['freshness']),
                                 ('message', 'statement', 'Owner conversation store', T.AUTHORITATIVE, L.RESOLVED,
                                  T.CURRENT))
                self.assertFalse({u for u in projection['uncertainties'] if u['reference'] == reference})
        # D2: Q1's quote is located in the statement's durable bytes, read from the store, and its span verifies.
        quote = nodes[M1]['quotes'][0]
        self.assertEqual((quote['item'], quote['outcome']), ('Q1', L.RESOLVED))
        content = QUAL02_MESSAGE1.read_bytes()
        self.assertEqual(L.span_bytes(L.parse(quote['span']), content), content.rstrip(b'\n'))
        self.assertTrue(quote['span'].startswith(M1 + '#span:'))

    def test_an_unresolved_statement_is_a_failure(self):
        # A message the store does not hold, an assistant message (display state, never a statement) and a store
        # that cannot be read: each is an explicit unresolved uncertainty, and the projection is incomplete.
        cases = ((f'conversation:{THREAD02}/Q02msg9', L.MISSING, 'MESSAGE_MISSING'),
                 (f'conversation:{THREAD02}/A000001', L.MISSING, 'MESSAGE_NOT_A_STATEMENT'))
        for reference, outcome, code in cases:
            with self.subTest(code=code):
                self.setUp()
                with E.conversation_module().open_store(self.conversations) as store:
                    store.append_message(THREAD02, {'parentId': 'Q02msg2', 'message': {
                        'id': 'A000001', 'role': 'assistant', 'createdAt': '2026-11-07T00:00:01.000Z',
                        'status': {'type': 'complete', 'reason': 'unknown'},
                        'content': [{'type': 'text', 'text': 'Noted.'}], 'metadata': {'custom': {}}}},
                        session_id=E.SESSION, at=E.STORE_AT)
                E.cite_store(self.repo)
                E.edit(self.repo, f'{CHANGE_DIR}/proposal.md', f'- source: Q1, {M2}\n'.encode(),
                       f'- source: Q1, {M2}, {reference}\n'.encode())
                self.commit('cite a statement the store does not resolve')
                self.reserve_tasks('TASK-1', 'TASK-2')
                projection = self.trace(f'outcome:{OUTCOME}')
                node = by_reference(projection)[reference]
                self.assertEqual((node['authority_mode'], node['resolution']['outcome'], node['resolution']['code']),
                                 (T.AUTHORITATIVE, outcome, code))
                self.assertUncertain(projection, reference, 'unresolved', code)
        self.setUp()
        E.cite_store(self.repo)
        self.commit('the intent record cites the Owner conversation store')
        self.reserve_tasks('TASK-1', 'TASK-2')
        self.conversations.unlink()                     # the store is gone: unavailable, and not re-created
        projection = self.trace(f'outcome:{OUTCOME}')
        for reference in (M1, M2):
            with self.subTest(reference=reference):
                node = by_reference(projection)[reference]
                self.assertEqual((node['authority_mode'], node['resolution']['code']),
                                 (T.UNAVAILABLE, 'CONVERSATION_STORE_UNAVAILABLE'))
                self.assertUncertain(projection, reference, 'unresolved', 'CONVERSATION_STORE_UNAVAILABLE')
        self.assertFalse(self.conversations.exists())

    def test_a_thread_of_display_state_only_is_not_the_objectives_statement(self):
        # B1 (I1 work design, R5): the objective's only source and its acceptance name a thread whose anchor is an
        # assistant message (display state the shell wrote), or a thread with no message. Neither stands for an
        # Owner statement: the node is an explicit unresolved statement, never a resolved one.
        thread = '2b3c4d5e-6f70-4182-93a4-b5c6d7e8f901'
        cases = ((f'conversation:{thread}@A000001', 'CONVERSATION_NOT_A_STATEMENT', True),
                 (f'conversation:{thread}', 'CONVERSATION_NOT_A_STATEMENT', True),
                 (f'conversation:{thread}', 'CONVERSATION_EMPTY', False))
        for reference, code, reply in cases:
            with self.subTest(reference=reference, code=code):
                self.setUp()
                with E.conversation_module().open_store(self.conversations) as store:
                    store.initialize_thread(session_id=E.SESSION, local_id='__LOCALID_display', at=E.STORE_AT,
                                            mint=lambda: thread)
                    if reply:
                        store.append_message(thread, {'parentId': None, 'message': {
                            'id': 'A000001', 'role': 'assistant', 'createdAt': '2026-11-07T00:00:01.000Z',
                            'status': {'type': 'complete', 'reason': 'unknown'},
                            'content': [{'type': 'text', 'text': 'I, the shell, say so.'}],
                            'metadata': {'custom': {}}}}, session_id=E.SESSION, at=E.STORE_AT)
                for path in (f'{CHANGE_DIR}/proposal.md', f'{CHANGE_DIR}/.openspec.yaml'):
                    data = (self.repo / path).read_bytes()
                    data = data.replace(b'conversation:qual-02/message-2', reference.encode())
                    (self.repo / path).write_bytes(data.replace(b'- source: Q1, ', b'- source: '))
                self.commit('the objective sourced and accepted by a thread that holds no Owner statement')
                self.reserve_tasks('TASK-1', 'TASK-2')
                projection = self.trace(f'outcome:{OUTCOME}')
                node = by_reference(projection)[reference]
                self.assertEqual((node['kind'], node['role'], node['authority_mode'], node['resolution']['outcome'],
                                  node['resolution']['code']),
                                 ('conversation', 'statement', T.AUTHORITATIVE, L.MISSING, code))
                self.assertIn((reference, projection['root'], T.ORIGINATES), edges(projection))
                self.assertUncertain(projection, reference, 'unresolved', code)

    def test_the_traversal_only_reads_the_store(self):
        E.cite_store(self.repo)
        self.commit('the intent record cites the Owner conversation store')
        self.reserve_tasks('TASK-1', 'TASK-2')
        cs = E.conversation_module()

        def state():
            conn = cs.storecore.open_read_only(self.conversations)
            try:
                return self.conversations.read_bytes(), cs._canonical_dump(conn)
            finally:
                conn.close()
        before = state()
        projection = self.trace(f'outcome:{OUTCOME}')
        self.assertEqual(by_reference(projection)[M1]['resolution']['outcome'], L.RESOLVED)
        self.assertEqual(state(), before)


class Tasks(Case):
    def test_tasks_that_cite_the_outcome_or_the_change(self):
        other_change = self.pointer('design.md').replace(f'changes/{CHANGE}/', 'changes/other-change/')
        self.fake_backlog(('TASK-1', [f'outcome:{OUTCOME}']),
                          ('TASK-2', [f'outcome:{OUTCOME}@{self.declared}', 'https://example.invalid/x']),
                          ('TASK-3', [f'outcome:{OTHER_OUTCOME}', other_change]),
                          ('TASK-4', []),
                          ('TASK-5', [self.pointer('specs/catalogue-search/new-product-visibility/spec.md')]))
        self.reserve_tasks('TASK-1', 'TASK-2', 'TASK-5')
        projection = self.trace(snapshot=None)
        fulfilled = {t for _, t, _ in edges(projection, T.FULFILLED_BY)}
        self.assertEqual(fulfilled, {'backlog:TASK-1', 'backlog:TASK-2', 'backlog:TASK-5'})
        via = {e['to']: e['provenance'][0]['via'] for e in projection['edges'] if e['relation'] == T.FULFILLED_BY}
        self.assertEqual(via['backlog:TASK-2'], [f'outcome:{OUTCOME}@{self.declared}'])
        self.assertEqual({f for f, _, _ in edges(projection, T.CITES)}, {'backlog:TASK-5'})
        self.assertNotIn(other_change, by_reference(projection))

    def test_a_task_backlog_does_not_list_is_reached_only_through_a_reservation_citing_the_outcome(self):
        # What the lineage README states (Not yet verified) and the schema's work "open" text: a task task list --json
        # omits (archived, gate G11) is reached only through an attempt reservation whose intent cites the outcome; with
        # no such reservation it is omitted, and no uncertainty names it (a known gap of the traversal, not fixed here).
        snapshot = self.tmp / 'unlisted'
        shutil.copytree(E.RECORDED_TASKS, snapshot)
        listing = json.loads((snapshot / 'task-list.json').read_text(encoding='utf-8'))
        listing['tasks'] = [t for t in listing['tasks'] if t['id'] != 'TASK-1']
        (snapshot / 'task-list.json').write_text(json.dumps(listing), encoding='utf-8')
        intent = E.task_intent('TASK-1')
        del intent['outcomeRef']
        for name, intents in (('cites the outcome', [(E.operation_key('TASK-1'), E.task_intent('TASK-1'))]),
                              ('no reservation', []), ('no outcomeRef', [(E.operation_key('TASK-1'), intent)])):
            with self.subTest(reservation=name):
                self.store = self.tmp / name.replace(' ', '-') / 'integration.sqlite'
                self.reserve(*intents, (E.operation_key('TASK-2'), E.task_intent('TASK-2')))
                projection = self.trace(snapshot=snapshot)
                fulfilled = {t for _, t, _ in edges(projection, T.FULFILLED_BY)}
                if name == 'cites the outcome':
                    self.assertEqual(fulfilled, {'backlog:TASK-1', 'backlog:TASK-2'})
                    self.assertEqual(by_reference(projection)['backlog:TASK-1']['resolution']['outcome'], L.RESOLVED)
                else:
                    self.assertEqual(fulfilled, {'backlog:TASK-2'})
                    self.assertNotIn('backlog:TASK-1', by_reference(projection))
                    self.assertFalse([u for u in projection['uncertainties'] if 'TASK-1' in u['reference']])

    def test_task_references_that_are_not_a_list(self):
        self.fake_backlog(('TASK-1', 'not a list'), ('TASK-2', [f'outcome:{OUTCOME}']))
        self.reserve_tasks('TASK-2')
        projection = self.trace(snapshot=None)
        self.assertUncertain(projection, 'backlog:TASK-1', 'malformed-reference', 'TASK_REFERENCES_MALFORMED')
        self.assertEqual({t for _, t, _ in edges(projection, T.FULFILLED_BY)}, {'backlog:TASK-2'})


class Intents(Case):
    def test_malformed_intent_references(self):
        self.reserve_tasks('TASK-2')
        self.reserve(('k-lower', {'workRef': 'backlog:task-1', 'outcomeRef': f'outcome:{OUTCOME}'}),
                     ('k-kind', {'workRef': f'outcome:{OUTCOME}'}),
                     ('k-type', {'workRef': 5}))
        projection = self.trace()
        codes = {(u['reason'], u['code']) for u in projection['uncertainties']}
        self.assertIn(('malformed-reference', 'INTENT_REFERENCE_MALFORMED'), codes)
        self.assertEqual(sum(1 for u in projection['uncertainties'] if u['code'] == 'INTENT_REFERENCE_MALFORMED'), 3)

    def test_reservations_for_other_work_are_not_followed(self):
        self.reserve_tasks('TASK-1', 'TASK-2')
        self.reserve(('other', {'workRef': 'backlog:TASK-7', 'outcomeRef': f'outcome:{OTHER_OUTCOME}'}),
                     ('no-work', {'outcomeRef': f'outcome:{OUTCOME}'}),
                     ('unrelated', {'kind': 'something else'}))
        projection = self.trace()
        self.assertNotIn('backlog:TASK-7', by_reference(projection))
        self.assertEqual(len(edges(projection, T.EXECUTED_BY)), 2)

    def test_a_reservation_for_a_listed_task_needs_no_outcome(self):
        self.reserve(('work-TASK-1/implement/revision-1', E.task_intent('TASK-1', outcome=None)),
                     ('work-TASK-2/implement/revision-1', {'workRef': 'backlog:TASK-2',
                                                           'outcomeRef': f'outcome:{OTHER_OUTCOME}'}))
        projection = self.trace()
        self.assertEqual({f for f, _, _ in edges(projection, T.EXECUTED_BY)}, {'backlog:TASK-1', 'backlog:TASK-2'})


class Contract(Case):
    def dispatched(self, *tasks, live=False):
        """TASKS dispatched and confirmed on a fresh core (fixture_attempts), in this case's integration store; the
        attempt resolver over them (its transport the core)."""
        core = FA.AC.AgentServerCore()
        self.addCleanup(core.close)
        attempts = FA.FixtureAttempts(self.tmp / ('live-root' if live else 'fixture-root'), live=live)
        self.store.parent.mkdir(parents=True, exist_ok=True)
        store = E.store_module().open_store(self.store)
        try:
            for task in tasks:
                attempts.attempt(store, core, task, change=CHANGE, design_commit=self.design,
                                 outcome_ref=f'outcome:{OUTCOME}')
        finally:
            store.close()
        return core, RA.AttemptResolver(self.store, attempts.seam(core), attempts.read_artifact)

    def test_complete_only_when_every_node_is_authoritative_resolved_and_current(self):
        class Trusted(T.Authorities):
            """A test double that treats the fixture as a live authority (until E-01.5: the samples)."""
            def ask(self, reference, method):
                result, mode = super().ask(reference, method)
                return result, (T.AUTHORITATIVE if mode == T.FIXTURE else mode)

        # The statements resolve in the real Owner conversation store only where the intent record cites store
        # identities, so the case cites them at a commit and declares the tasks' design pointers at it, as the
        # recorded P-02.1 tasks are at the design commit (TASK-1: design and proposal; TASK-2: design and spec);
        # the outcome is traced at a later commit that changes nothing of the change, so all 13 nodes are current.
        E.cite_store(self.repo)
        cited = self.commit('the intent record cites the Owner conversation store')
        (self.repo / 'NOTES.md').write_bytes(b'An unrelated change.\n')
        later = self.commit('an unrelated change')
        self.fake_backlog(('TASK-1', [self.pointer('design.md', cited), self.pointer('proposal.md', cited)]),
                          ('TASK-2', [self.pointer('design.md', cited), self.pointer(SPEC, cited)]))
        _core, resolver = self.dispatched('TASK-1', 'TASK-2')
        registry = R.build_registry(project=self.repo, backlog=E.FAKE_BACKLOG,
                                    conversations=E.conversations_path(self.repo), attempts=resolver)
        projection = E.run_trace(f'outcome:{OUTCOME}@{later}', Trusted(registry), self.repo, self.store, snapshot=None)
        self.assertEqual((projection['verdict'], projection['uncertainties']), ('complete', []))
        self.assertEqual(projection['authority_modes'], {'authoritative': 13, 'fixture': 0, 'sample': 0,
                                                         'unavailable': 0})
        # untrusted, the same projection is incomplete: the attempts are the fixture's, and say so
        projection = E.run_trace(f'outcome:{OUTCOME}@{later}', T.Authorities(registry), self.repo, self.store,
                                 snapshot=None)
        self.assertEqual(projection['verdict'], 'incomplete')
        self.assertEqual({u['reason'] for u in projection['uncertainties']}, {'fixture-authority'})
        self.assertEqual(projection['authority_modes'], {'authoritative': 11, 'fixture': 2, 'sample': 0,
                                                         'unavailable': 0})

    def test_samples_stand_in_only_where_no_authority_exists(self):
        registry = E.registry(self.repo)
        sample = ReviewSample()
        # message and conversation are implemented since U-02.2, and attempt since E-01.5: no sample stands in for
        # them any more (R5, R11). A sample may still stand in for a kind whose authority is unavailable (review).
        for kind in ('message', 'conversation', 'attempt', 'design', 'objective', 'work', 'commit', 'effect-receipt',
                     'release', 'no-such-kind'):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                T.Authorities(registry, {kind: sample})
        self.assertEqual(set(T.Authorities(registry, {'review': sample}).samples), {'review'})

        class Unlabelled(ReviewSample):
            authority = 'Gitea'
        with self.assertRaises(ValueError):
            T.Authorities(registry, {'review': Unlabelled()})
        self.assertEqual(R.build_registry(project=self.repo).resolve('conversation:qual-02/message-1').outcome,
                         L.AUTHORITY_UNAVAILABLE)  # the default registry never answers from a sample

    def test_a_sample_answering_outside_its_contract_is_refused(self):
        class Wrong(ReviewSample):
            def resolve(self, reference):
                return L.answer(L.parse(f'gitea:o/r/pulls/8/reviews/1@{"c" * 40}'), L.RESOLVED, self.authority)
        auth = T.Authorities(E.registry(self.repo), {'review': Wrong()})
        with self.assertRaises(RuntimeError):
            auth.ask(L.parse(f'gitea:o/r/pulls/7/reviews/31@{"c" * 40}'), 'resolve')

    def test_the_root_is_an_outcome(self):
        auth = E.authorities(self.repo)
        for text in ('backlog:TASK-1', 'outcome:O-101'):
            with self.subTest(text=text), self.assertRaises(L.MalformedReference):
                T.trace(text, auth, project=self.repo)

    def test_the_sample_statement_store(self):
        # The statement sample is retired at U-02.2 (I1 work design, R5): lineage_samples has no statement
        # authority, and the cases it answered from the P-01.2 corpus are answered by the Owner conversation
        # store's own resolvers, read-only, for the same statements stored under store identities.
        self.assertFalse(hasattr(S, 'SampleStatementStore'))
        self.assertEqual(set(S.sample_authorities()), set())      # and the attempt sample since E-01.5
        registry = E.registry(self.repo)
        content = QUAL02_MESSAGE1.read_bytes()
        cases = {
            M1: (L.RESOLVED, None),
            f'{M1}#sha256:{hashlib.sha256(content).hexdigest()}': (L.RESOLVED, None),
            f'{M1}#sha256:{"0" * 64}': (L.DIGEST_MISMATCH, 'MESSAGE_DIGEST_MISMATCH'),
            f'conversation:{THREAD02}/Q02msg9': (L.MISSING, 'MESSAGE_MISSING'),
            'conversation:qual-99/message-1': (L.MISSING, 'CONVERSATION_MISSING'),
            'conversation:..%2Fqual-02/message-1': (L.MISSING, 'CONVERSATION_MISSING'),
            'conversation:..%2Fcorpus%2Fqual-02/message-1': (L.MISSING, 'CONVERSATION_MISSING'),  # no path escape
            f'conversation:{THREAD02}': (L.RESOLVED, None),
            f'conversation:{THREAD02}@Q02msg2': (L.RESOLVED, None),
            f'conversation:{THREAD02}@Q02msg7': (L.REVISION_MISMATCH, 'CONVERSATION_MESSAGE_MISSING'),
            'conversation:qual-99': (L.MISSING, 'CONVERSATION_MISSING'),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                pinned_thread = isinstance(L.parse(text), L.ConversationRef) and L.parse(text).pinned
                for method in (registry.resolve, registry.current):
                    result = method(L.parse(text))
                    if method == registry.current and pinned_thread:
                        expected = (L.RESOLVED, None)   # current answers at the thread's last message
                    self.assertEqual((result.outcome, result.code), expected)
                    self.assertEqual((result.reference, result.authority), (text, 'Owner conversation store'))
        auth = T.Authorities(registry)
        self.assertEqual(auth.content(L.parse(M1)), content)
        self.assertIsNone(auth.content(L.parse(f'conversation:{THREAD02}/Q02msg9')))
        broken = self.tmp / 'broken' / 'conversation.sqlite'
        broken.parent.mkdir()
        shutil.copy(self.conversations, broken)
        conn = sqlite3.connect(broken)
        conn.executescript('DROP TRIGGER message_no_delete;')
        conn.close()
        result = E.registry(self.repo, conversations=broken).resolve(L.parse(M1))
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'CONVERSATION_STORE_UNAVAILABLE'))

    def test_the_sample_attempt_records(self):
        # The attempt sample is retired at E-01.5 (I1 integration design, R11): no SampleAttemptRecords and no sample
        # file; the attempt kind is implemented and answered by the attempt resolver, here over the Agent Server
        # fixture's cited core, with its mode stated.
        self.assertFalse(hasattr(S, 'SampleAttemptRecords'))
        self.assertFalse((HERE / 'fixtures' / 'sample-attempts.json').exists())
        self.assertEqual(L.schema_kinds(L.load_schema())['attempt']['status'], 'implemented')
        core, resolver = self.dispatched('TASK-1')
        auth = T.Authorities(R.build_registry(attempts=resolver))
        (held,) = core.conversations
        result, mode = auth.ask(L.parse(f'openhands:conversation/{held}'), 'resolve')
        self.assertEqual((result.outcome, mode, result.authority), (L.RESOLVED, T.FIXTURE,
                                                                     L.fixture_authority('OpenHands Agent Server')))
        self.assertTrue(result.authority.startswith('FIXTURE'))
        result, mode = auth.ask(L.parse(f'openhands:conversation/{held}@event-1'), 'resolve')
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_EVENT_UNOBSERVED'))
        self.assertEqual(auth.ask(L.parse(f'openhands:conversation/{held}@event-1'), 'current')[0].outcome, L.RESOLVED)
        result, mode = auth.ask(L.parse(f'openhands:conversation/{OTHER_OUTCOME}'), 'resolve')
        self.assertEqual((result.outcome, result.code, mode), (L.MISSING, 'ATTEMPT_MISSING', T.AUTHORITATIVE))

    def test_a_fixture_answered_attempt_is_never_complete(self):
        """E-01.5: the attempts the fixture answered carry mode fixture, a label beginning FIXTURE and the
        fixture-authority uncertainty, so the projection is incomplete; a fixture answer for an attempt bound live is
        authority-unavailable, never a mode the caller chose."""
        _core, resolver = self.dispatched('TASK-1', 'TASK-2')
        registry = R.build_registry(project=self.repo, backlog=E.FAKE_BACKLOG,
                                    conversations=E.conversations_path(self.repo), attempts=resolver)
        projection = E.run_trace(f'outcome:{OUTCOME}@{self.declared}', T.Authorities(registry), self.repo, self.store)
        attempts = [n for n in projection['nodes'] if n['role'] == 'attempt']
        self.assertEqual(len(attempts), 2)
        for node in attempts:
            with self.subTest(node=node['reference']):
                self.assertEqual((node['authority_mode'], node['resolution']['outcome'], node['freshness']),
                                 (T.FIXTURE, L.RESOLVED, T.CURRENT))
                self.assertTrue(node['authority'].startswith('FIXTURE'))
                self.assertUncertain(projection, node['reference'], 'fixture-authority', 'FIXTURE_AUTHORITY')
        self.assertEqual(projection['authority_modes']['fixture'], 2)

    def test_a_fixture_answer_for_a_live_bound_attempt_is_unavailable(self):
        _core, resolver = self.dispatched('TASK-1', live=True)
        registry = R.build_registry(project=self.repo, backlog=E.FAKE_BACKLOG,
                                    conversations=E.conversations_path(self.repo), attempts=resolver)
        projection = E.run_trace(f'outcome:{OUTCOME}@{self.declared}', T.Authorities(registry), self.repo, self.store)
        (node,) = [n for n in projection['nodes'] if n['role'] == 'attempt']
        self.assertEqual((node['authority_mode'], node['resolution']['outcome'], node['resolution']['code']),
                         (T.UNAVAILABLE, L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_AUTHORITY_MISMATCH'))
        self.assertEqual(projection['authority_modes']['fixture'], 0)

    def test_change_name(self):
        self.assertEqual(T.change_name(CHANGE_DIR), (CHANGE, False))
        self.assertEqual(T.change_name(ARCHIVED_DIR), (CHANGE, True))
        self.assertEqual(T.change_name('openspec/changes/archive'), (None, False))
        self.assertEqual(T.change_name('elsewhere/x'), (None, False))


class ReviewSample:
    """A test-only SAMPLE stand-in for the review kind (still unavailable), for the samples' contract alone."""
    authority = 'SAMPLE reviews (test only)'

    def resolve(self, reference):
        return L.answer(reference, L.RESOLVED, self.authority)

    def current(self, reference):
        return L.answer(reference, L.RESOLVED, self.authority, query='current')


class CommandLine(Case):
    category = 'contract'

    def cli(self, *args, env=None):
        return subprocess.run([*CLI, *args], cwd=E.REPO, capture_output=True, text=True, encoding='utf-8',
                              stdin=subprocess.DEVNULL, timeout=fx.WAIT_CEILING_S,
                              env={**os.environ, **(env or {})})

    def test_trace_command(self):
        self.reserve_tasks('TASK-1', 'TASK-2')
        before = tree_state(self.repo), store_state(self.store)
        result = self.cli('trace', f'outcome:{OUTCOME}@{self.declared}', '--project', str(self.repo),
                          '--store', str(self.store))
        self.assertEqual(result.returncode, 1, result.stderr)
        projection = json.loads(result.stdout)
        self.assertEqual((projection['format'], projection['verdict']), (T.PROJECTION_FORMAT, 'incomplete'))
        self.assertEqual(projection['authority_modes']['sample'], 0)  # the command line never uses a sample
        self.assertIn((projection['root'], 'enumeration-unavailable', 'BACKLOG_NOT_CONFIGURED'), reasons(projection))
        self.assertIn(f'UNCERTAIN {projection["root"]}: enumeration-unavailable BACKLOG_NOT_CONFIGURED', result.stderr)
        self.assertEqual((tree_state(self.repo), store_state(self.store)), before)

    def test_trace_command_reads_the_owner_conversation_store(self):
        E.cite_store(self.repo)
        cited = self.commit('the intent record cites the Owner conversation store')
        self.reserve_tasks('TASK-1', 'TASK-2')
        result = self.cli('trace', f'outcome:{OUTCOME}@{cited}', '--project', str(self.repo), '--store', str(self.store),
                          '--conversations', str(self.conversations))
        self.assertEqual(result.returncode, 1, result.stderr)           # incomplete: no Backlog.md, no attempts
        projection = json.loads(result.stdout)
        nodes = by_reference(projection)
        self.assertEqual([(nodes[r]['authority_mode'], nodes[r]['resolution']['outcome']) for r in (M1, M2)],
                         [(T.AUTHORITATIVE, L.RESOLVED)] * 2)
        self.assertEqual(nodes[M1]['quotes'][0]['outcome'], L.RESOLVED)
        self.assertEqual(projection['authority_modes']['sample'], 0)
        # Without the store the statements are explicitly unavailable, never resolved.
        result = self.cli('trace', f'outcome:{OUTCOME}@{cited}', '--project', str(self.repo))
        projection = json.loads(result.stdout)
        self.assertEqual(by_reference(projection)[M1]['resolution']['code'], 'RESOLVER_NOT_CONFIGURED')
        self.assertIn(f'UNCERTAIN {M1}: unresolved RESOLVER_NOT_CONFIGURED', result.stderr)

    def test_could_not_run(self):
        self.assertEqual(self.cli('trace', 'outcome:O-101', '--project', str(self.repo)).returncode, 2)
        self.assertEqual(self.cli('trace', f'outcome:{OUTCOME}', '--project', str(self.repo),
                                  '--backlog', str(self.tmp / 'absent-tool')).returncode, 2)


if __name__ == '__main__':
    unittest.main()
