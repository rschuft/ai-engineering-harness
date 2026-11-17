"""The Owner conversation store's threads and messages, migration 0002 (plan leaf U-02.1; decision 0025, point 6).

U-02.1's proof at the store level:

- **a reload returns the exact messages in order without duplicate ids**: the store is closed and reopened, and
  ``load`` answers the same ids, parents and bytes, in ``seq`` order, each id once, edits (new messages under the same
  parent) included;
- **a repeated append adds nothing**; a **conflicting id** (``MESSAGE_ID_CONFLICT``), a **changed user message**
  (``MESSAGE_IMMUTABLE``) and a **thread delete** (``THREAD_DELETE_REFUSED``) are each refused with their code, and
  the store's canonical dump is equal before and after;
- **quotes are filled mechanically from the durable source** (Overseer decision D2): a quote cut with
  ``lineage.span_reference`` from a stored user message's bytes verifies with ``check_message_content``, and a source
  whose byte changed fails with ``SPAN_DIGEST_MISMATCH``.

Plus the store's own rules: the thread id is the store's (a UUID version 4, idempotent for one session and local
id); the message id is assistant-ui's native id, unique per thread; SQLite's triggers keep every table append-only
whatever writes the row; an assistant message's update appends a revision; a store migrated from 0001 keeps its
sessions; an altered schema is refused at open. Every database lives in a fresh temporary directory outside the
checkout.

U-02.2 (``PendingDecision``): the requests the Owner host shell sends for a run paused on a decision
(apps/owner-host/src/areas/fixtures/pending-decision.wire.json, checked against the shell on every run of its
tests) replayed into the store: the paused assistant message comes back once after a reopen, still pending; the
completion is an upsert of the same id that appends a revision (the paused one is kept); a user message stays
immutable under ``update``.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

CATEGORY = 'unit'
HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
REPO = PACKAGE.parents[1]


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


CS = _load('aieh_conversation_store', PACKAGE / 'conversation_store.py')
L = _load('aieh_lineage_for_conversation_tests', REPO / 'integrations' / 'lineage' / 'lineage.py')
storecore = CS.storecore
AT = '2026-11-16T12:00:00Z'
LOCAL = '__LOCALID_8spf4drozrs'
# An Owner statement with multi-byte characters and characters a normalizer would change: the bytes are kept as
# received (no NFC, no trimming, no line-ending change).
STATEMENT = '  Ship the capture form — café 中文 \U0001F600\r\nAcceptance: exact bytes.  '


def user_item(message_id, text, parent=None, created='2026-11-16T12:00:00.123Z'):
    return {'parentId': parent, 'runConfig': {},
            'message': {'id': message_id, 'createdAt': created, 'role': 'user',
                        'content': [{'type': 'text', 'text': text}], 'attachments': [], 'metadata': {'custom': {}}}}


def assistant_item(message_id, parent, text='Recorded.', status=None, content=None):
    return {'parentId': parent, 'runConfig': {},
            'message': {'id': message_id, 'role': 'assistant', 'createdAt': '2026-11-16T12:00:01.000Z',
                        'status': status or {'type': 'complete', 'reason': 'unknown'},
                        'content': content if content is not None else [{'type': 'text', 'text': text}],
                        'metadata': {'unstable_state': None, 'unstable_annotations': [], 'unstable_data': [],
                                     'steps': [], 'custom': {}}}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-conversation-threads-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = self.open()
        self.session = self.store.enroll_session(session_id=str(uuid.uuid4()), verifier='a' * 64,
                                                 issued_at='2026-11-16T00:00:00Z', expires_at='2026-11-16T23:00:00Z')

    def open(self, **kw):
        store = CS.open_store(self.tmp / CS.DB_NAME, **kw)
        self.addCleanup(store.close)
        return store

    def reopen(self):
        self.store.close()
        self.store = self.open(apply_migrations=False)
        return self.store

    def thread(self, local=LOCAL):
        return self.store.initialize_thread(session_id=self.session.session_id, local_id=local, at=AT)[0].thread_id

    def append(self, thread, item):
        return self.store.append_message(thread, item, session_id=self.session.session_id, at=AT)

    def update(self, thread, item):
        return self.store.update_message(thread, item, session_id=self.session.session_id, at=AT)

    def assert_refused(self, code, call, *args, **kw):
        before = self.store.canonical_dump()
        with self.assertRaises(CS.ConversationRefused) as caught:
            call(*args, **kw)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.store.canonical_dump(), before, f'{code} changed the store')

    def conversation(self, thread):
        """The browser's sequence for one exchange, an edit and a regeneration (gate G2)."""
        items = [user_item('U000001', STATEMENT), assistant_item('A000001', 'U000001'),
                 user_item('U000002', 'Edited: a second statement.'), assistant_item('A000002', 'U000002'),
                 assistant_item('A000003', 'U000002', 'Recorded again.'),
                 user_item('U000003', 'Third.', parent='A000003'), assistant_item('A000004', 'U000003')]
        for item in items:
            self.assertTrue(self.append(thread, item).changed)
        return items


class Migration(Base):
    def test_the_store_is_at_migration_0002_with_its_four_tables(self):
        summary = self.store.summary()
        self.assertEqual(summary['schema_version'], 2)
        self.assertEqual([m['name'] for m in summary['migrations']],
                         ['0001_store_identity_and_sessions.sql', '0002_threads_and_messages.sql'])
        tables = {r[0] for r in self.store.conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
        self.assertEqual(tables, {'schema_migration', 'owner_session', 'thread', 'thread_event', 'message',
                                  'message_revision'})

    def test_a_store_made_at_0001_migrates_and_keeps_its_sessions(self):
        only_first = self.tmp / 'first'
        only_first.mkdir()
        shutil.copy(CS.MIGRATIONS_DIR / '0001_store_identity_and_sessions.sql', only_first)
        old_path = self.tmp / 'old'
        old_path.mkdir()
        old = CS.open_store(old_path / CS.DB_NAME, migrations_dir=only_first)
        enrolled = old.enroll_session(session_id=str(uuid.uuid4()), verifier='b' * 64,
                                      issued_at='2026-11-16T00:00:00Z', expires_at='2026-11-16T12:00:00Z')
        old.close()
        with self.assertRaises(CS.MigrationError):           # pending migration 0002: refused without migrating
            CS.open_store(old_path / CS.DB_NAME, apply_migrations=False)
        migrated = CS.open_store(old_path / CS.DB_NAME)
        self.addCleanup(migrated.close)
        self.assertEqual(migrated.schema_version(), 2)
        self.assertEqual([s.session_id for s in migrated.sessions()], [enrolled.session_id])
        CS.check_schema(migrated.conn)

    def test_an_altered_store_is_refused_at_open(self):
        thread = self.thread()
        self.append(thread, user_item('U000001', STATEMENT))
        self.store.close()
        for index, script in enumerate(('DROP TRIGGER message_revision_user_is_immutable;',
                       'DROP TRIGGER message_no_delete; DROP TRIGGER message_revision_no_delete; '
                       'DELETE FROM message_revision; DELETE FROM message;',
                       'DROP TRIGGER thread_no_delete; CREATE TRIGGER thread_no_delete BEFORE DELETE ON thread '
                       "WHEN 0 BEGIN SELECT RAISE(ABORT, 'x'); END;",
                       'CREATE INDEX extra ON message (role);')):
            with self.subTest(script=script):
                copy = self.tmp / f'altered-{index}'
                copy.mkdir()
                shutil.copy(self.tmp / CS.DB_NAME, copy / CS.DB_NAME)
                conn = sqlite3.connect(copy / CS.DB_NAME)
                conn.executescript(script)
                conn.commit()
                conn.close()
                for kw in ({}, {'apply_migrations': False}):
                    with self.assertRaises(CS.SchemaAltered) as caught:
                        CS.open_store(copy / CS.DB_NAME, **kw)
                    self.assertEqual(caught.exception.code, 'CONVERSATION_STORE_ALTERED')


class Threads(Base):
    def test_the_store_mints_the_thread_id_once_per_session_and_local_id(self):
        first, created = self.store.initialize_thread(session_id=self.session.session_id, local_id=LOCAL, at=AT)
        self.assertTrue(created)
        self.assertRegex(first.thread_id, CS.THREAD_ID)
        self.assertEqual(uuid.UUID(first.thread_id).version, 4)
        again, created = self.store.initialize_thread(session_id=self.session.session_id, local_id=LOCAL, at=AT)
        self.assertEqual((again, created), (first, False))
        other = self.thread('__LOCALID_k9EC8U4')
        self.assertNotEqual(other, first.thread_id)
        self.assertEqual([t.thread_id for t in self.store.threads()], [first.thread_id, other])
        self.assertEqual(first.public(), {'remoteId': first.thread_id, 'status': 'regular'})

    def test_a_malformed_local_id_or_unknown_thread_is_refused(self):
        for local in ('', 'abc', '__LOCALID_', '__LOCALID_a-b', '__localid_abc', '__LOCALID_' + 'a' * 65, None):
            with self.subTest(local=local):
                self.assert_refused('THREAD_INVALID', self.store.initialize_thread,
                                    session_id=self.session.session_id, local_id=local, at=AT)
        for thread in (str(uuid.uuid4()), 'thread-1', None):
            with self.subTest(thread=thread):
                self.assert_refused('THREAD_NOT_FOUND', self.store.thread, thread)
                self.assert_refused('THREAD_NOT_FOUND', self.store.load, thread)

    def test_title_and_archive_are_events(self):
        thread = self.thread()
        sid = self.session.session_id
        self.assertEqual(self.store.rename_thread(thread, 'Capture form', session_id=sid, at=AT).title, 'Capture form')
        self.assertEqual(self.store.archive_thread(thread, session_id=sid, at=AT).status, 'archived')
        self.assertEqual(self.store.archive_thread(thread, session_id=sid, at=AT).status, 'archived')
        self.assertEqual(self.store.unarchive_thread(thread, session_id=sid, at=AT).public(),
                         {'remoteId': thread, 'status': 'regular', 'title': 'Capture form'})
        events = self.store.conn.execute('SELECT kind, title FROM thread_event ORDER BY seq').fetchall()
        self.assertEqual(events, [('rename', 'Capture form'), ('archive', None), ('unarchive', None)])
        for title in ('', 'x' * 201, 'a\x00b', '\ud800'):
            with self.subTest(title=title):
                self.assert_refused('THREAD_INVALID', self.store.rename_thread, thread, title, session_id=sid, at=AT)

    def test_a_thread_delete_is_refused_and_changes_nothing(self):
        thread = self.thread()
        self.conversation(thread)
        self.assert_refused('THREAD_DELETE_REFUSED', self.store.delete_thread, thread)
        self.assert_refused('THREAD_DELETE_REFUSED', self.store.delete_thread, str(uuid.uuid4()))
        self.assertEqual(len(self.store.messages(thread)), 7)


class Reload(Base):
    def test_a_reload_returns_the_same_messages_ids_parents_and_bytes_in_seq_order(self):
        thread = self.thread()
        items = self.conversation(thread)
        before = self.store.load(thread)
        self.reopen()
        loaded = self.store.load(thread)
        self.assertEqual(loaded, before)
        self.assertEqual(list(loaded), ['messages'])                    # no headId: the last message is the head
        self.assertEqual([m['seq'] for m in loaded['messages']], list(range(1, len(items) + 1)))
        ids = [m['message']['id'] for m in loaded['messages']]
        self.assertEqual(len(ids), len(set(ids)))
        for sent, got in zip(items, loaded['messages']):
            with self.subTest(id=sent['message']['id']):
                self.assertEqual(got['parentId'], sent['parentId'])
                self.assertEqual(got['message'], sent['message'])          # the same message, field for field
        stored = self.store.messages(thread)
        self.assertEqual(stored[0].content, STATEMENT.encode('utf-8'))  # the bytes exactly as received
        self.assertEqual([(m.role, m.author) for m in stored[:2]], [('user', 'owner'), ('assistant', 'owner-host')])
        self.assertEqual({m.session_id for m in stored}, {self.session.session_id})
        # The edit is a new message under the original's parent: both are kept.
        self.assertEqual([(m.message_id, m.parent_id) for m in stored if m.role == 'user'],
                         [('U000001', None), ('U000002', None), ('U000003', 'A000003')])

    def test_a_message_id_is_unique_per_thread_not_across_threads(self):
        one, two = self.thread(), self.thread('__LOCALID_k9EC8U4')
        self.append(one, user_item('U000001', 'In thread one.'))
        self.append(two, user_item('U000001', 'In thread two.'))
        self.assertEqual(self.store.message_content(one, 'U000001'), b'In thread one.')
        self.assertEqual(self.store.message_content(two, 'U000001'), b'In thread two.')
        self.assertEqual(self.store.message(two, 'U000001').seq, 1)


class Refusals(Base):
    def test_a_repeated_append_adds_nothing(self):
        thread = self.thread()
        items = self.conversation(thread)
        before = self.store.canonical_dump()
        for item in items:
            with self.subTest(id=item['message']['id']):
                written = self.append(thread, json.loads(json.dumps(item)))
                self.assertFalse(written.changed)
        self.assertEqual(self.store.canonical_dump(), before)
        self.assertEqual(len(self.store.load(thread)['messages']), len(items))

    def test_a_conflicting_id_is_refused(self):
        thread = self.thread()
        self.conversation(thread)
        for item in (user_item('U000001', STATEMENT + '!'),                       # other bytes
                     user_item('U000001', STATEMENT, parent='A000004'),            # another parent
                     user_item('U000001', STATEMENT, created='2026-11-16T12:00:09.000Z'),
                     assistant_item('U000001', None),                              # another role
                     assistant_item('A000001', 'U000001', 'Another reply.')):      # an append is not an update
            with self.subTest(item=item['message']):
                self.assert_refused('MESSAGE_ID_CONFLICT', self.append, thread, item)

    def test_a_changed_user_message_is_refused(self):
        thread = self.thread()
        self.conversation(thread)
        self.assertFalse(self.update(thread, user_item('U000001', STATEMENT)).changed)   # the same bytes: no change
        for text in (STATEMENT + ' ', STATEMENT.replace('é', 'é'), 'Replaced.'):
            with self.subTest(text=text):
                self.assert_refused('MESSAGE_IMMUTABLE', self.update, thread, user_item('U000001', text))
        self.assert_refused('MESSAGE_IMMUTABLE', self.update, thread, assistant_item('U000001', None))
        self.assert_refused('MESSAGE_NOT_FOUND', self.update, thread, user_item('U000009', 'New via update.'))
        self.assertEqual(self.store.message_content(thread, 'U000001'), STATEMENT.encode('utf-8'))

    def test_a_parent_outside_the_thread_is_refused(self):
        one, two = self.thread(), self.thread('__LOCALID_k9EC8U4')
        self.append(one, user_item('U000001', 'One.'))
        self.assert_refused('MESSAGE_PARENT_NOT_FOUND', self.append, two, assistant_item('A000001', 'U000001'))
        self.assert_refused('MESSAGE_PARENT_NOT_FOUND', self.append, one, assistant_item('A000001', 'U000009'))

    def test_what_is_not_a_storable_message_is_refused(self):
        thread = self.thread()
        good = user_item('U000001', 'Fine.')

        def changed(path, value):
            item = json.loads(json.dumps(good))
            target = item
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            return item
        cases = {
            'lone surrogate': user_item('U000001', 'a\ud800b'),
            'NUL': user_item('U000001', 'a\x00b'),
            'empty text': user_item('U000001', ''),
            'too long': user_item('U000001', 'x' * (CS.MAX_CONTENT_BYTES + 1)),
            'two parts': changed(('message', 'content'), [{'type': 'text', 'text': 'a'}, {'type': 'text', 'text': 'b'}]),
            'an image part': changed(('message', 'content'), [{'type': 'image', 'image': 'data:'}]),
            'an attachment': changed(('message', 'attachments'), [{'id': 'x'}]),
            'custom metadata': changed(('message', 'metadata'), {'custom': {'k': 1}}),
            'an extra field': changed(('message', 'extra'), 1),
            'an id of another grammar': changed(('message', 'id'), 'user-1'),
            'a long id': changed(('message', 'id'), 'U0000001'),
            'a system role': changed(('message', 'role'), 'system'),
            'a createdAt without milliseconds': changed(('message', 'createdAt'), '2026-11-16T12:00:00Z'),
            'its own parent': changed(('parentId',), 'U000001'),
            'an unknown item key': changed(('headId',), None),
            'no parentId': {'message': good['message']},
            'not an object': ['U000001'],
            'an assistant message without status': {'parentId': None, 'message': {'id': 'A000001', 'role': 'assistant',
                                                                                  'content': []}},
            'an assistant message with NaN': assistant_item('A000001', None, content=[{'type': 'data', 'v': float('nan')}]),
        }
        for name, item in cases.items():
            with self.subTest(case=name):
                self.assert_refused('MESSAGE_INVALID', self.append, thread, item)
        self.assertEqual(self.store.messages(thread), [])

    def test_sqlite_keeps_every_table_append_only_whatever_writes_the_row(self):
        thread = self.thread()
        self.conversation(thread)
        self.store.rename_thread(thread, 'A title', session_id=self.session.session_id, at=AT)
        before = self.store.canonical_dump()
        sid, digest = self.session.session_id, 'c' * 64
        statements = [
            ("UPDATE message_revision SET content = x'00' WHERE message_id = 'U000001'", ()),
            ("DELETE FROM message_revision WHERE message_id = 'A000001'", ()),
            ("UPDATE message SET parent_id = NULL WHERE message_id = 'U000003'", ()),
            ("DELETE FROM message WHERE message_id = 'A000004'", ()),
            ("UPDATE thread SET local_id = '__LOCALID_x'", ()),
            ('DELETE FROM thread', ()),
            ("UPDATE thread_event SET title = 'B'", ()),
            ('DELETE FROM thread_event', ()),
            # a second revision of a user message
            ("INSERT INTO message_revision VALUES (?, 'U000001', 2, x'41', ?, ?, ?)", (thread, digest, sid, AT)),
            # a skipped sequence number, a skipped revision
            ("INSERT INTO message VALUES (?, 'Z000001', 9, NULL, 'user', 'owner', ?, '2026-11-16T12:00:00.000Z', ?)",
             (thread, sid, AT)),
            ("INSERT INTO message_revision VALUES (?, 'A000001', 3, x'41', ?, ?, ?)", (thread, digest, sid, AT)),
            # an author that does not match the role (at the right sequence number)
            ("INSERT INTO message VALUES (?, 'Z000002', 8, NULL, 'user', 'owner-host', ?, "
             "'2026-11-16T12:00:00.000Z', ?)", (thread, sid, AT)),
        ]
        for statement, args in statements:
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                self.store.conn.execute(statement, args)
        self.assertEqual(self.store.canonical_dump(), before)


class AssistantRevisions(Base):
    def test_an_update_of_an_assistant_message_appends_a_revision(self):
        thread = self.thread()
        self.append(thread, user_item('U000001', 'Start.'))
        tool = {'type': 'tool-call', 'toolCallId': 'call-1', 'toolName': 'ask_owner', 'args': {'q': 'Proceed?'},
                'argsText': '{"q":"Proceed?"}'}
        paused = assistant_item('A000001', 'U000001', status={'type': 'requires-action', 'reason': 'tool-calls'},
                                content=[tool])
        self.assertTrue(self.append(thread, paused).changed)
        self.assertFalse(self.update(thread, paused).changed)
        done = assistant_item('A000001', 'U000001', content=[{**tool, 'result': {'approved': True}},
                                                            {'type': 'text', 'text': 'Answer recorded.'}])
        written = self.update(thread, done)
        self.assertEqual((written.changed, written.message.revision, written.message.seq), (True, 2, 2))
        self.reopen()
        self.assertEqual(self.store.load(thread)['messages'][1]['message'], done['message'])
        revisions = self.store.conn.execute("SELECT revision, content FROM message_revision WHERE message_id = 'A000001' "
                                            'ORDER BY revision').fetchall()
        self.assertEqual([json.loads(c) for _, c in revisions], [paused['message'], done['message']])
        self.assert_refused('MESSAGE_ID_CONFLICT', self.update, thread, assistant_item('A000001', None))

    def test_an_update_of_an_unknown_assistant_message_is_an_append(self):
        thread = self.thread()
        self.append(thread, user_item('U000001', 'Start.'))
        written = self.update(thread, assistant_item('A000001', 'U000001'))
        self.assertEqual((written.changed, written.message.seq, written.message.revision), (True, 2, 1))


WIRE = REPO / 'apps' / 'owner-host' / 'src' / 'areas' / 'fixtures' / 'pending-decision.wire.json'


def wire_items():
    """The history items of the shell's recorded pending-decision requests, in order: (path tail, item)."""
    data = json.loads(WIRE.read_text(encoding='utf-8'))
    if data.get('format') != 'aieh-owner-host-wire/v1':
        raise AssertionError('not the shell\'s wire fixture')
    return [(request['path'].split('{thread}', 1)[1], request['body']) for request in data['requests']
            if request['path'].startswith('/threads/{thread}/')]


class PendingDecision(Base):
    """A run paused on the owner_decision human tool, as the shell writes it (plan leaf U-02.2)."""

    def replay(self, thread, items):
        written = []
        for tail, item in items:
            call = self.update if tail.startswith('/messages/') else self.append
            written.append(call(thread, item))
        return written

    def test_the_pending_call_comes_back_once_after_a_reopen_and_its_completion_is_a_revision(self):
        items = wire_items()
        self.assertEqual([tail for tail, _ in items], ['/messages', '/messages', '/messages/A000001'])
        (_, statement), (_, paused), (_, done) = items
        thread = self.thread()
        self.replay(thread, items[:2])
        self.reopen()                                       # the Integration process restarts: the store is reopened
        loaded = self.store.load(thread)['messages']
        self.assertEqual([(m['seq'], m['message']['id'], m['parentId']) for m in loaded],
                         [(1, 'U000001', None), (2, 'A000001', 'U000001')])
        self.assertEqual(loaded[1]['message'], paused['message'])
        self.assertEqual(loaded[1]['message']['status'], {'type': 'requires-action', 'reason': 'tool-calls'})
        (call,) = loaded[1]['message']['content']
        self.assertEqual((call['type'], call['toolName'], call['toolCallId']), ('tool-call', 'owner_decision', 'call-1'))
        self.assertNotIn('result', call)
        # A reconnect that sends the same requests again adds nothing: each id once, one revision each.
        dump = self.store.canonical_dump()
        self.assertEqual([w.changed for w in self.replay(thread, items[:2])], [False, False])
        self.assertEqual(self.store.canonical_dump(), dump)
        # The Owner answers: the completion is an upsert of the same id, a second revision; nothing else changes.
        (written,) = self.replay(thread, items[2:])
        self.assertEqual((written.changed, written.message.seq, written.message.revision), (True, 2, 2))
        self.reopen()
        loaded = self.store.load(thread)['messages']
        self.assertEqual([m['message']['id'] for m in loaded], ['U000001', 'A000001'])
        self.assertEqual(loaded[1]['message'], done['message'])
        self.assertEqual(loaded[0]['message']['content'], statement['message']['content'])
        revisions = self.store.conn.execute(
            "SELECT revision, content FROM message_revision WHERE message_id = 'A000001' ORDER BY revision").fetchall()
        self.assertEqual([(r, json.loads(c)) for r, c in revisions], [(1, paused['message']), (2, done['message'])])
        self.assertFalse(self.replay(thread, items[2:])[0].changed)  # the same completion again: nothing

    def test_an_update_never_changes_an_owner_statement(self):
        items = wire_items()
        thread = self.thread()
        self.replay(thread, items[:2])
        (_, statement) = items[0]
        content = self.store.message_content(thread, 'U000001')
        changed = json.loads(json.dumps(statement))
        changed['message']['content'][0]['text'] = 'Start the change, but differently.'
        self.assert_refused('MESSAGE_IMMUTABLE', self.update, thread, changed)
        as_reply = json.loads(json.dumps(items[2][1]))
        as_reply['message']['id'] = 'U000001'
        as_reply['parentId'] = None
        self.assert_refused('MESSAGE_IMMUTABLE', self.update, thread, as_reply)
        self.assertFalse(self.update(thread, statement).changed)       # the same bytes: no change
        unknown = json.loads(json.dumps(statement))
        unknown['message']['id'] = 'U000009'
        self.assert_refused('MESSAGE_NOT_FOUND', self.update, thread, unknown)
        reparented = json.loads(json.dumps(items[2][1]))
        reparented['parentId'] = None
        self.assert_refused('MESSAGE_ID_CONFLICT', self.update, thread, reparented)
        self.assertEqual(self.store.message_content(thread, 'U000001'), content)
        self.assertEqual(self.store.conn.execute(
            "SELECT count(*) FROM message_revision WHERE message_id = 'U000001'").fetchone()[0], 1)


class Quotes(Base):
    """Overseer decision D2: a quote is filled mechanically from the durable source, and a quote that differs from
    its source span is a failure."""

    def statement(self):
        thread = self.thread()
        self.conversation(thread)
        return thread, self.store.message_content(thread, 'U000001')

    def test_a_quote_cut_from_a_stored_message_verifies(self):
        thread, content = self.statement()
        quote = 'café 中文'.encode('utf-8')
        start = content.index(quote)
        reference = L.span_reference(thread, 'U000001', content, start, len(quote))
        self.assertTrue(reference.text.startswith(f'conversation:{thread}/U000001#span:{start}+{len(quote)}:sha256:'))
        self.reopen()
        source = self.store.message_content(thread, 'U000001')
        result = L.check_message_content(L.parse(reference.text), source)
        self.assertEqual((result.outcome, result.code), ('resolved', None))
        self.assertEqual(L.span_bytes(reference, source), quote)
        whole = L.message_reference(thread, 'U000001', source)
        self.assertTrue(L.check_message_content(whole, source).resolved)

    def test_a_source_whose_byte_changed_fails(self):
        thread, content = self.statement()
        start = content.index(b'Acceptance')
        reference = L.span_reference(thread, 'U000001', content, start, len(b'Acceptance'))
        self.store.close()
        # A same-account writer that keeps the schema (decision 0010 point 1): it lifts the trigger, changes one byte
        # of the statement inside the quoted span and its recorded digest, and puts the trigger back as it was.
        trigger = sqlite3.connect(self.tmp / CS.DB_NAME).execute(
            "SELECT sql FROM sqlite_schema WHERE name = 'message_revision_no_update'").fetchone()[0]
        changed = content.replace(b'Acceptance', b'Acceptancf')
        conn = sqlite3.connect(self.tmp / CS.DB_NAME)
        conn.executescript('DROP TRIGGER message_revision_no_update;')
        conn.execute("UPDATE message_revision SET content = ?, sha256 = ? WHERE message_id = 'U000001'",
                     (changed, L.message_bytes_digest(changed)))
        conn.executescript(trigger + ';')
        conn.commit()
        conn.close()
        self.store = self.open()                    # the schema is as migrated: the store opens
        source = self.store.message_content(thread, 'U000001')
        self.assertEqual(sum(a != b for a, b in zip(source, content)), 1)
        result = L.check_message_content(reference, source)
        self.assertEqual((result.outcome, result.code), ('digest-mismatch', 'SPAN_DIGEST_MISMATCH'))
        with self.assertRaises(L.MalformedReference):
            L.span_bytes(reference, source)

    def test_a_changed_byte_without_its_digest_is_refused_at_open(self):
        thread, content = self.statement()
        self.store.close()
        conn = sqlite3.connect(self.tmp / CS.DB_NAME)
        trigger = conn.execute("SELECT sql FROM sqlite_schema WHERE name = 'message_revision_no_update'").fetchone()[0]
        conn.executescript('DROP TRIGGER message_revision_no_update;')
        conn.execute("UPDATE message_revision SET content = ? WHERE message_id = 'U000001'",
                     (content.replace(b'Ship', b'Shop'),))
        conn.executescript(trigger + ';')
        conn.commit()
        conn.close()
        with self.assertRaisesRegex(CS.StoreError, 'does not match its digest'):
            CS.open_store(self.tmp / CS.DB_NAME)


if __name__ == '__main__':
    unittest.main()
