"""U-02.1's proof against the real Integration process (plan leaf U-02.1; decision 0025, point 6).

One scenario, observed first and judged by the tests: the service is started through ``service.up`` on a throwaway
managed layout (a temporary directory, never the managed data root) with a throwaway Owner UI session; the shell's
requests are made over HTTP to 127.0.0.1:13310; the service is stopped with ``service.down`` and started again, and
the thread is read back; ``down`` stops it. Then:

- **a reload returns the exact messages in order without duplicate ids**: the history load after the restart equals
  the one before it and what was appended (ids, parents, the user messages' text), in seq order, each id once;
- **a repeated append adds nothing**, and a **conflicting id**, a **changed user message** and a **thread delete** are
  each refused with their stable code (``MESSAGE_ID_CONFLICT``, ``MESSAGE_IMMUTABLE``, ``THREAD_DELETE_REFUSED``),
  the store's canonical dump equal before and after;
- **quotes are filled mechanically from the durable source** (Overseer decision D2): a quote cut with
  ``lineage.span_reference`` from the stored bytes of a statement the service received verifies with
  ``check_message_content``, and a copy of the store whose statement byte changed (digest and schema kept: the
  same-account limit) fails with ``SPAN_DIGEST_MISMATCH``;
- the service log names route templates only: no thread id, message id, text or credential.

Windows only (the platform contract's only adapter). It fails, rather than skips, when 127.0.0.1:13310 is already
held: stop the service (service.py down) before running it.
"""
from __future__ import annotations

import http.client
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import ownerhost_support as T

CATEGORY = 'integration'
SV = T._load('aieh_ownerhost_service', T.PACKAGE / 'service.py')
L = T._load('aieh_lineage_for_ownerhost_tests', T.REPO / 'integrations' / 'lineage' / 'lineage.py')
A, S, E, CS = T.A, T.S, T.E, T.CS
LOCAL = '__LOCALID_8spf4drozrs'
STATEMENT = '  Capture the form — café, 中文 \U0001F600\r\nAcceptance: exact bytes.  '
QUOTE = 'café, 中文'


def user_item(message_id, text, parent=None):
    return {'parentId': parent, 'runConfig': {},
            'message': {'id': message_id, 'createdAt': '2026-11-16T12:00:00.123Z', 'role': 'user',
                        'content': [{'type': 'text', 'text': text}], 'attachments': [], 'metadata': {'custom': {}}}}


def assistant_item(message_id, parent, text='Recorded.'):
    return {'parentId': parent, 'message': {'id': message_id, 'role': 'assistant', 'createdAt': '2026-11-16T12:00:01.000Z',
                                            'status': {'type': 'complete', 'reason': 'unknown'},
                                            'content': [{'type': 'text', 'text': text}], 'metadata': {'custom': {}}}}


ITEMS = [user_item('U000001', STATEMENT), assistant_item('A000001', 'U000001'),
         user_item('U000002', 'An edit of the first statement.'), assistant_item('A000002', 'U000002'),
         assistant_item('A000003', 'U000002', 'Recorded again.')]


@unittest.skipUnless(sys.platform == 'win32', 'the platform contract has a Windows adapter only')
class HistoryOverTheService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-ownerhost-history-'))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.lay = SV.Layout(cls.tmp / 'state' / 'owner-host', cls.tmp / 'logs' / 'owner-host')
        cls.lay.state.mkdir(parents=True)
        cls.lay.logs.mkdir(parents=True)
        cls.adapter = SV.contract.select_adapter()
        if cls.adapter.port_in_use(A.PORT, A.LOOPBACK):
            raise AssertionError(f'{A.LOOPBACK}:{A.PORT} is already held: stop the Integration process '
                                 '(service.py down) before running the listener tests')
        cls.store = CS.open_store(cls.lay.store)
        cls.addClassCleanup(cls.store.close)
        cls.credential, cls.record = E.enroll(cls.store, hours=1)
        cls.obs = {}
        try:
            cls.obs['up'] = SV.up(cls.lay, cls.adapter)
            cls.before_restart()
            cls.obs['down'] = SV.down(cls.lay, cls.adapter)
            cls.obs['up_again'] = SV.up(cls.lay, cls.adapter)
            cls.obs['after'] = cls.request('GET', f'/threads/{cls.remote}/messages')
            cls.obs['threads_after'] = cls.request('GET', '/threads')
        finally:
            cls.stop()

    @classmethod
    def request(cls, method, path, body=None):
        connection = http.client.HTTPConnection(A.LOOPBACK, A.PORT, timeout=10)
        headers = {S.HEADER: cls.credential, 'Origin': T.SHELL_ORIGIN}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        try:
            connection.request(method, path, body=json.dumps(body).encode('utf-8') if body is not None else None,
                               headers=headers)
            response = connection.getresponse()
            data = response.read()
            return response.status, json.loads(data) if data else None
        finally:
            connection.close()

    @classmethod
    def refused(cls, method, path, body=None):
        before = cls.store.canonical_dump()
        status, answer = cls.request(method, path, body)
        return status, (answer or {}).get('code'), before == cls.store.canonical_dump()

    @classmethod
    def before_restart(cls):
        obs = cls.obs
        obs['initialize'] = cls.request('POST', '/threads', {'localId': LOCAL})
        cls.remote = obs['initialize'][1]['remoteId']
        obs['initialize_again'] = cls.request('POST', '/threads', {'localId': LOCAL})
        obs['appends'] = [cls.request('POST', f'/threads/{cls.remote}/messages', item) for item in ITEMS]
        obs['before'] = cls.request('GET', f'/threads/{cls.remote}/messages')
        dump = cls.store.canonical_dump()
        obs['repeats'] = [cls.request('POST', f'/threads/{cls.remote}/messages', item) for item in ITEMS]
        obs['repeats_unchanged'] = dump == cls.store.canonical_dump()
        obs['conflict'] = cls.refused('POST', f'/threads/{cls.remote}/messages', user_item('U000001', 'Another text.'))
        obs['immutable'] = cls.refused('POST', f'/threads/{cls.remote}/messages/U000001',
                                       user_item('U000001', STATEMENT.strip()))
        obs['delete'] = cls.refused('POST', f'/threads/{cls.remote}/delete')

    @classmethod
    def stop(cls):
        try:
            SV.down(cls.lay, cls.adapter)
        finally:
            run = SV.read_run_record(cls.lay.run_record) or {}
            supervisor = SV.live(cls.adapter, run, 'supervisor')
            if supervisor is not None:           # started by this test: never left behind
                supervisor.terminate()
                supervisor.wait(SV.STOP_CEILING_S)
        cls.obs['port_open_after'] = cls.adapter.port_in_use(A.PORT, A.LOOPBACK)
        cls.obs['service_log'] = (cls.lay.logs / 'service.log').read_text(encoding='utf-8', errors='replace')

    def test_the_service_ran_and_stopped(self):
        self.assertTrue(self.obs['up']['ready'])
        self.assertTrue(self.obs['up_again']['ready'])
        self.assertFalse(self.obs['port_open_after'])

    def test_initialize_mints_one_thread_for_the_local_id(self):
        self.assertEqual(self.obs['initialize'][0], 200)
        self.assertRegex(self.remote, CS.THREAD_ID)
        self.assertEqual(self.obs['initialize_again'], self.obs['initialize'])
        self.assertEqual(self.obs['threads_after'], (200, {'threads': [{'remoteId': self.remote, 'status': 'regular'}]}))

    def test_a_reload_after_a_restart_returns_the_exact_messages_in_order_without_duplicate_ids(self):
        self.assertEqual([a[1]['seq'] for a in self.obs['appends']], [1, 2, 3, 4, 5])
        status, before = self.obs['before']
        self.assertEqual((status, self.obs['after']), (200, self.obs['before']))
        messages = before['messages']
        self.assertEqual([m['seq'] for m in messages], [1, 2, 3, 4, 5])
        ids = [m['message']['id'] for m in messages]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([{k: m[k] for k in ('parentId', 'message')} for m in messages],
                         [{k: i[k] for k in ('parentId', 'message')} for i in ITEMS])
        self.assertEqual(self.store.message_content(self.remote, 'U000001'), STATEMENT.encode('utf-8'))

    def test_a_repeated_append_adds_nothing(self):
        self.assertTrue(self.obs['repeats_unchanged'])
        self.assertEqual([(s, a['changed']) for s, a in self.obs['repeats']], [(200, False)] * len(ITEMS))

    def test_a_conflicting_id_a_changed_user_message_and_a_thread_delete_are_refused(self):
        self.assertEqual(self.obs['conflict'], (409, 'MESSAGE_ID_CONFLICT', True))
        self.assertEqual(self.obs['immutable'], (409, 'MESSAGE_IMMUTABLE', True))
        self.assertEqual(self.obs['delete'], (409, 'THREAD_DELETE_REFUSED', True))

    def test_a_quote_cut_from_the_stored_statement_verifies_and_a_changed_byte_fails(self):
        content = self.store.message_content(self.remote, 'U000001')
        quote = QUOTE.encode('utf-8')
        start = content.index(quote)
        reference = L.span_reference(self.remote, 'U000001', content, start, len(quote))
        result = L.check_message_content(L.parse(reference.text), content)
        self.assertEqual((result.outcome, result.code), ('resolved', None))
        self.assertEqual(L.span_bytes(reference, content), quote)
        # A copy of the store whose statement changed by one byte inside the span, its digest updated and the schema
        # kept (a same-account writer, decision 0010 point 1): the store opens, and the quote fails.
        copy_dir = Path(tempfile.mkdtemp(prefix='aieh-ownerhost-history-copy-'))
        self.addCleanup(shutil.rmtree, copy_dir, True)
        target = sqlite3.connect(copy_dir / CS.DB_NAME)
        self.store.conn.backup(target)
        trigger = target.execute("SELECT sql FROM sqlite_schema WHERE name = 'message_revision_no_update'").fetchone()[0]
        changed = content.replace('中'.encode('utf-8'), '为'.encode('utf-8'))
        target.executescript('DROP TRIGGER message_revision_no_update;')
        target.execute("UPDATE message_revision SET content = ?, sha256 = ? WHERE message_id = 'U000001'",
                       (changed, L.message_bytes_digest(changed)))
        target.executescript(trigger + ';')
        target.commit()
        target.close()
        copy = CS.open_store(copy_dir / CS.DB_NAME, apply_migrations=False)
        self.addCleanup(copy.close)
        changed_source = copy.message_content(self.remote, 'U000001')
        self.assertEqual(sum(a != b for a, b in zip(changed_source, content)), 1)
        result = L.check_message_content(reference, changed_source)
        self.assertEqual((result.outcome, result.code), ('digest-mismatch', 'SPAN_DIGEST_MISMATCH'))

    def test_the_service_log_names_route_templates_only(self):
        log = self.obs['service_log']
        self.assertIn(f'accepted POST /threads/{{thread_id}}/messages 200 session={self.record.session_id}', log)
        self.assertIn(f'accepted POST /threads/{{thread_id}}/delete 409 session={self.record.session_id}', log)
        for text in (self.remote, LOCAL, 'U000001', 'A000001', 'Capture the form', 'Another text', self.credential):
            self.assertNotIn(text, log)
        self.assertEqual(T.exposures(log, [self.credential]), [])


if __name__ == '__main__':
    unittest.main()
