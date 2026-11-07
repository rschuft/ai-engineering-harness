"""Tests for integrations/lineage/lineage_trace.py: the read-only end-to-end traversal,
its projection, the example and the negative resolution fixtures (stdlib unittest,
plan leaf P-03.2).

Offline. Each case builds a throwaway project repository (the P-02.1 qual-02 change and an
x-outcomes declaration, never the P-01.2 fixture itself), the fake Backlog.md (replaying
Backlog.md's own recorded P-02.1 output, or its own small state), and an integration
store made through the store's own API. Sample authorities (lineage_samples.py) stand in
for the Owner conversation store and the Agent Server where a case needs them.
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lineage_example as E  # noqa: E402

T, S, R, L, fx = E.T, E.S, E.R, E.L, E.fx
planning = R.planning
OUTCOME, CHANGE, CHANGE_DIR = E.OUTCOME, E.CHANGE, E.CHANGE_DIR
ARCHIVED_DIR = f'openspec/changes/archive/2026-11-07-{CHANGE}'
OTHER_OUTCOME = '0d9e8f7a-6b5c-4d3e-8f1a-2b3c4d5e6f70'
FAKE_FILES = ('.fake-backlog.json', '.fake-backlog-argv.jsonl')
CLI = [sys.executable, '-I', '-B', str(E.LINEAGE_DIR / 'lineage_trace.py')]
QUAL08 = S.CORPUS / 'qual-08' / 'message-1.txt'
NBSP = '\u00a0'.encode()  # U+00A0, written as an escape


def tree_state(repo):
    """What a read-only traversal must leave unchanged (the fake Backlog.md's own files aside)."""
    excluded = [f':(exclude){name}' for name in FAKE_FILES]
    return (fx.git(repo, 'status', '--porcelain', '--untracked-files=all', '--ignored', '--', '.', *excluded),
            fx.git(repo, 'for-each-ref'), fx.git(repo, 'rev-parse', 'HEAD'), fx.git(repo, 'count-objects', '-v'))


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
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-trace-'))
        self.addCleanup(fx.rmtree, self.tmp)
        self.repo = self.tmp / 'p'
        self.design, self.declared = E.build_project(self.repo)
        self.store = self.tmp / 'st' / 'integration.sqlite'

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
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-trace-example-'))
        cls.projections = E.example(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        fx.rmtree(cls.tmp)

    def test_regenerates_the_committed_example(self):
        self.assertEqual(self.projections, E.recorded())
        for name, projection in self.projections.items():
            with self.subTest(name=name):
                self.assertIsNone(fx.MACHINE_PATH.search(E.dumps(projection)))

    def test_sample_authorities_resolve_the_whole_chain_and_say_so(self):
        projection = self.projections['sample']
        self.assertEqual(projection['format'], T.PROJECTION_FORMAT)
        roles = {node['role'] for node in projection['nodes']}
        self.assertEqual(roles, {'statement', 'objective', 'design', 'work', 'attempt'})
        for node in projection['nodes']:
            with self.subTest(node=node['reference']):
                self.assertEqual((node['resolution']['outcome'], node['freshness']), (L.RESOLVED, T.CURRENT))
                expected = T.SAMPLE if node['role'] in ('statement', 'attempt') else T.AUTHORITATIVE
                self.assertEqual(node['authority_mode'], expected)
                if expected == T.SAMPLE:
                    self.assertTrue(node['authority'].startswith('SAMPLE'))
        self.assertEqual(projection['verdict'], 'incomplete')
        self.assertEqual({u['reason'] for u in projection['uncertainties']}, {'sample-authority'})
        self.assertEqual({u['reference'] for u in projection['uncertainties']},
                         {n['reference'] for n in projection['nodes'] if n['authority_mode'] == T.SAMPLE})

    def test_the_chain_runs_from_the_original_message_to_the_attempts(self):
        projection = self.projections['sample']
        root = projection['root']
        message1, message2 = 'conversation:qual-02/message-1', 'conversation:qual-02/message-2'
        self.assertIn((message1, root, T.ORIGINATES), edges(projection))
        self.assertIn((root, message2, T.ACCEPTED_BY), edges(projection))
        self.assertEqual({t for _, t, _ in edges(projection, T.FULFILLED_BY)}, {'backlog:TASK-1', 'backlog:TASK-2'})
        attempts = {(f, t) for f, t, _ in edges(projection, T.EXECUTED_BY)}
        store_mod = E.store_module()
        self.assertEqual(attempts, {
            (f'backlog:{task}', f'openhands:conversation/{store_mod.conversation_id_for(E.operation_key(task))}')
            for task in ('TASK-1', 'TASK-2')})
        self.assertEqual(len(edges(projection, T.SHAPED_BY)), 3)  # proposal, design, spec at the declaring commit
        quote = by_reference(projection)[message1]['quotes'][0]
        self.assertEqual((quote['item'], quote['outcome']), ('Q1', L.RESOLVED))
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
                    self.assertTrue(provenance['operation_key'].startswith('work-TASK-'))

    def test_the_real_registry_marks_statements_and_attempts_unavailable(self):
        projection = self.projections['real']
        for node in projection['nodes']:
            with self.subTest(node=node['reference']):
                if node['role'] in ('statement', 'attempt'):
                    self.assertEqual((node['authority_mode'], node['resolution']['outcome'],
                                      node['resolution']['code']),
                                     (T.UNAVAILABLE, L.AUTHORITY_UNAVAILABLE, 'AUTHORITY_NOT_YET_AVAILABLE'))
                    self.assertTrue(node['resolution']['detail'].endswith(
                        'U-02.1, U-02.2' if node['role'] == 'statement' else 'E-01.3.1, E-01.4.1'))
                else:
                    self.assertEqual((node['authority_mode'], node['resolution']['outcome']),
                                     (T.AUTHORITATIVE, L.RESOLVED))
        self.assertEqual({u['reason'] for u in projection['uncertainties']}, {'unresolved'})
        self.assertEqual(projection['authority_modes'], {'authoritative': 9, 'sample': 0, 'unavailable': 4})
        # The same edges as with the samples: the links are asserted by records, not by the authorities.
        self.assertEqual(edges(projection), edges(self.projections['sample']))


QUAL02_MESSAGE1 = S.CORPUS / 'qual-02' / 'message-1.txt'


# ---------------------------------------------------------------------------
# Read-only

class ReadOnly(Case):
    def test_the_traversal_writes_nothing_and_asks_only_reads(self):
        self.reserve_tasks('TASK-1', 'TASK-2')
        before = tree_state(self.repo), store_state(self.store)
        calls = []
        real_run = subprocess.run

        def recording(argv, *args, **kwargs):
            calls.append(list(argv))
            return real_run(argv, *args, **kwargs)

        with mock.patch.object(subprocess, 'run', side_effect=recording):
            projection = self.trace()
        self.assertEqual(projection['verdict'], 'incomplete')
        self.assertEqual((tree_state(self.repo), store_state(self.store)), before)
        backlog_prefix = E.FAKE_BACKLOG
        for argv in calls:
            with self.subTest(argv=argv[:4]):
                if argv[0] == 'git':
                    self.assertEqual(argv[1], '-C')
                    self.assertIn(argv[3], ('rev-parse', 'cat-file', 'ls-tree', 'archive'))
                else:
                    self.assertEqual(argv[:len(backlog_prefix)], backlog_prefix)
                    self.assertIn(tuple(argv[len(backlog_prefix):][:2]), {('task', 'list'), ('task', 'view')})
        self.assertFalse(any('openspec' in Path(str(a[0])).name.lower() for a in calls))
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
        bad = f'conversation:qual-08/message-1#span:{start}+{len(quote)}:sha256:{digest}'
        short = f'conversation:qual-08/message-1#span:{start}+{len(relayed)}:sha256:{digest}'
        good = L.span_reference('qual-08', 'message-1', content, start, len(quote)).text
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
                       b'- source: conversation:qual-08/message-1\n')
                proposal = self.repo / CHANGE_DIR / 'proposal.md'
                data = proposal.read_bytes()
                old = data[data.index(b'```text\n', data.index(b'#### Q1')) + 8:]
                old = old[:old.index(b'\n```')]
                E.edit(self.repo, f'{CHANGE_DIR}/proposal.md', old, quote)
                self.commit('quote qual-08')
                projection = self.trace(f'outcome:{OUTCOME}')
                node = by_reference(projection)['conversation:qual-08/message-1']
                if expected:
                    self.assertEqual(node['quotes'][0]['outcome'], L.DIGEST_MISMATCH)
                    self.assertUncertain(projection, 'conversation:qual-08/message-1', 'quote-unverified', expected)
                else:
                    self.assertEqual(node['quotes'][0]['outcome'], L.RESOLVED)
                    span = L.parse(node['quotes'][0]['span'])
                    self.assertEqual(L.span_bytes(span, content), first_line)


class MissingNode(Case):
    def test_the_statement_is_missing(self):
        for path in (f'{CHANGE_DIR}/proposal.md', f'{CHANGE_DIR}/.openspec.yaml'):
            data = (self.repo / path).read_bytes()
            (self.repo / path).write_bytes(data.replace(b'conversation:qual-02/message-2', b'conversation:qual-02/message-9'))
        declared = self.commit('cite a message the store does not hold')
        self.reserve_tasks('TASK-1', 'TASK-2')
        projection = self.trace(f'outcome:{OUTCOME}@{declared}')
        node = by_reference(projection)['conversation:qual-02/message-9']
        self.assertEqual((node['resolution']['outcome'], node['resolution']['code']), (L.MISSING, 'MESSAGE_MISSING'))
        self.assertUncertain(projection, 'conversation:qual-02/message-9', 'unresolved', 'MESSAGE_MISSING')
        self.assertIn((projection['root'], 'conversation:qual-02/message-9', T.ACCEPTED_BY), edges(projection))

    def test_a_task_id_whose_task_does_not_exist(self):
        self.reserve_tasks('TASK-1', 'TASK-2', 'TASK-9')
        projection = self.trace()
        node = by_reference(projection)['backlog:TASK-9']
        self.assertEqual((node['resolution']['outcome'], node['resolution']['code']), (L.MISSING, 'WORK_MISSING'))
        self.assertUncertain(projection, 'backlog:TASK-9', 'unresolved', 'WORK_MISSING')
        edge = [e for e in projection['edges'] if e['to'] == 'backlog:TASK-9' and e['relation'] == T.FULFILLED_BY]
        self.assertEqual(edge[0]['provenance'][0]['record'], T.STORE_RECORD)  # asserted by the reservation

    def test_a_reservation_whose_conversation_has_no_attempt_record(self):
        self.reserve(('work-TASK-1/implement/revision-1', E.task_intent('TASK-1')),
                     ('work-TASK-2/implement/revision-2', E.task_intent('TASK-2')))
        projection = self.trace()
        conversation = E.store_module().conversation_id_for('work-TASK-2/implement/revision-2')
        reference = f'openhands:conversation/{conversation}'
        node = by_reference(projection)[reference]
        self.assertEqual((node['resolution']['outcome'], node['resolution']['code'], node['authority_mode']),
                         (L.MISSING, 'ATTEMPT_MISSING', T.SAMPLE))
        self.assertUncertain(projection, reference, 'unresolved', 'ATTEMPT_MISSING')

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
        self.commit('Q1 without its quote')
        projection = self.trace(f'outcome:{OUTCOME}')
        self.assertUncertain(projection, 'conversation:qual-02/message-1', 'quote-unverified', 'QUOTE_MISSING')

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
               b'- source: conversation:qual-08/message-1\n')
        proposal = self.repo / CHANGE_DIR / 'proposal.md'
        data = proposal.read_bytes()
        old = data[data.index(b'```text\n', data.index(b'#### Q1')) + 8:]
        E.edit(self.repo, f'{CHANGE_DIR}/proposal.md', old[:old.index(b'\n```')], b'\xc2\xa0\xe2\x82\xac')
        self.commit('a quote that occurs twice')
        projection = self.trace(f'outcome:{OUTCOME}')
        self.assertUncertain(projection, 'conversation:qual-08/message-1', 'quote-unverified', 'QUOTE_SPAN_AMBIGUOUS')

    def test_a_quote_cannot_be_checked_without_content(self):
        class NoContent(S.SampleStatementStore):
            content = None
        samples = S.sample_authorities()
        samples['message'] = NoContent()
        auth = T.Authorities(E.registry(self.repo), samples)
        self.reserve_tasks('TASK-1', 'TASK-2')
        projection = E.run_trace(f'outcome:{OUTCOME}', auth, self.repo, self.store)
        self.assertUncertain(projection, 'conversation:qual-02/message-1', 'quote-unverified', 'QUOTE_SOURCE_UNREADABLE')


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
    def test_complete_only_when_every_node_is_authoritative_resolved_and_current(self):
        class Trusted(T.Authorities):
            """A test double that treats the samples as live authorities."""
            def ask(self, reference, method):
                result, mode = super().ask(reference, method)
                return result, (T.AUTHORITATIVE if mode == T.SAMPLE else mode)

        self.reserve_tasks('TASK-1', 'TASK-2')
        auth = Trusted(E.registry(self.repo), S.sample_authorities())
        projection = E.run_trace(f'outcome:{OUTCOME}@{self.declared}', auth, self.repo, self.store)
        self.assertEqual((projection['verdict'], projection['uncertainties']), ('complete', []))
        self.assertEqual(projection['authority_modes'], {'authoritative': 13, 'sample': 0, 'unavailable': 0})

    def test_samples_stand_in_only_where_no_authority_exists(self):
        registry = E.registry(self.repo)
        statements = S.SampleStatementStore()
        for kind in ('design', 'objective', 'work', 'commit', 'effect-receipt', 'release', 'no-such-kind'):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                T.Authorities(registry, {kind: statements})

        class Unlabelled(S.SampleStatementStore):
            authority = 'Owner conversation store'
        with self.assertRaises(ValueError):
            T.Authorities(registry, {'message': Unlabelled()})
        self.assertEqual(R.build_registry(project=self.repo).resolve('conversation:qual-02/message-1').outcome,
                         L.AUTHORITY_UNAVAILABLE)  # the default registry never answers from a sample

    def test_a_sample_answering_outside_its_contract_is_refused(self):
        class Wrong(S.SampleStatementStore):
            def resolve(self, reference):
                return L.answer(L.parse('conversation:other/m'), L.RESOLVED, self.authority)
        auth = T.Authorities(E.registry(self.repo), {'message': Wrong()})
        with self.assertRaises(RuntimeError):
            auth.ask(L.parse('conversation:qual-02/message-1'), 'resolve')

    def test_the_root_is_an_outcome(self):
        auth = E.authorities(self.repo)
        for text in ('backlog:TASK-1', 'outcome:O-101'):
            with self.subTest(text=text), self.assertRaises(L.MalformedReference):
                T.trace(text, auth, project=self.repo)

    def test_the_sample_statement_store(self):
        store = S.SampleStatementStore()
        content = QUAL02_MESSAGE1.read_bytes()
        cases = {
            'conversation:qual-02/message-1': (L.RESOLVED, None),
            f'conversation:qual-02/message-1#sha256:{hashlib.sha256(content).hexdigest()}': (L.RESOLVED, None),
            f'conversation:qual-02/message-1#sha256:{"0" * 64}': (L.DIGEST_MISMATCH, 'MESSAGE_DIGEST_MISMATCH'),
            'conversation:qual-02/message-9': (L.MISSING, 'MESSAGE_MISSING'),
            'conversation:qual-99/message-1': (L.MISSING, 'CONVERSATION_MISSING'),
            'conversation:..%2Fqual-02/message-1': (L.MISSING, 'CONVERSATION_MISSING'),
            'conversation:..%2Fcorpus%2Fqual-02/message-1': (L.MISSING, 'CONVERSATION_MISSING'),  # no path escape
            'conversation:qual-02': (L.RESOLVED, None),
            'conversation:qual-02@message-2': (L.RESOLVED, None),
            'conversation:qual-02@message-7': (L.REVISION_MISMATCH, 'CONVERSATION_MESSAGE_MISSING'),
            'conversation:qual-99': (L.MISSING, 'CONVERSATION_MISSING'),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                for method in (store.resolve, store.current):
                    result = method(L.parse(text))
                    self.assertEqual((result.outcome, result.code), expected)
                    self.assertEqual(result.reference, text)
        self.assertEqual(store.content(L.parse('conversation:qual-02/message-1')), content)
        self.assertIsNone(store.content(L.parse('conversation:qual-02/message-9')))
        broken = self.tmp / 'corpus'
        (broken / 'qual-02').mkdir(parents=True)
        shutil.copy(S.CORPUS / 'qual-02' / 'item.json', broken / 'qual-02')
        result = S.SampleStatementStore(broken).resolve(L.parse('conversation:qual-02/message-1'))
        self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'SAMPLE_CORPUS_INVALID'))

    def test_the_sample_attempt_records(self):
        records = S.SampleAttemptRecords()
        known = json.loads(S.ATTEMPTS.read_text(encoding='utf-8'))['records'][0]['id']
        result = records.resolve(L.parse(f'openhands:conversation/{known}'))
        self.assertEqual(result.outcome, L.RESOLVED)
        result = records.resolve(L.parse(f'openhands:conversation/{known}@event-1'))
        self.assertEqual((result.outcome, result.code), (L.REVISION_MISMATCH, 'ATTEMPT_EVENT_MISSING'))
        self.assertEqual(records.current(L.parse(f'openhands:conversation/{known}@event-1')).outcome, L.RESOLVED)
        result = records.resolve(L.parse(f'openhands:conversation/{OTHER_OUTCOME}'))
        self.assertEqual((result.outcome, result.code), (L.MISSING, 'ATTEMPT_MISSING'))
        data = json.loads(S.ATTEMPTS.read_text(encoding='utf-8'))
        for name, change in {'a field F-04.2 did not record': lambda d: d['records'][0].update(execution_status='idle'),
                             'not marked sample': lambda d: d.update(sample=False),
                             'another format': lambda d: d.update(format='x')}.items():
            with self.subTest(case=name):
                bad = json.loads(json.dumps(data))
                change(bad)
                path = self.tmp / 'bad.json'
                path.write_text(json.dumps(bad), encoding='utf-8')
                result = S.SampleAttemptRecords(path).resolve(L.parse(f'openhands:conversation/{known}'))
                self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'SAMPLE_RECORDS_INVALID'))

    def test_change_name(self):
        self.assertEqual(T.change_name(CHANGE_DIR), (CHANGE, False))
        self.assertEqual(T.change_name(ARCHIVED_DIR), (CHANGE, True))
        self.assertEqual(T.change_name('openspec/changes/archive'), (None, False))
        self.assertEqual(T.change_name('elsewhere/x'), (None, False))


class CommandLine(Case):
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

    def test_could_not_run(self):
        self.assertEqual(self.cli('trace', 'outcome:O-101', '--project', str(self.repo)).returncode, 2)
        self.assertEqual(self.cli('trace', f'outcome:{OUTCOME}', '--project', str(self.repo),
                                  '--backlog', str(self.tmp / 'absent-tool')).returncode, 2)


if __name__ == '__main__':
    unittest.main()
