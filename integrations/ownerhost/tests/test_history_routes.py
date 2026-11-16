"""The thread and history routes of the Integration process, in process (plan leaf U-02.1; decision 0025, point 6).

The backend of the shell's two assistant-ui adapters (RemoteThreadListAdapter and ThreadHistoryAdapter), over the
conversation store, driven through ASGI on an event loop in this process (the live service is
test_history_listener.py's):

- **initialize** mints the thread id in the store, once per session and local id; list, fetch, rename, archive and
  unarchive answer assistant-ui's thread metadata; a **thread delete** is refused, ``THREAD_DELETE_REFUSED``, and
  changes nothing;
- **a reload returns the exact messages in order without duplicate ids**: the history load answers what was
  appended, ids, parents and the user message's text, in seq order, no headId;
- **a repeated append adds nothing**; a **conflicting id** (``MESSAGE_ID_CONFLICT``) and a **changed user message**
  (``MESSAGE_IMMUTABLE``) are refused with their codes and change nothing;
- a body is one JSON object of the JSON media type, bounded, with no duplicate key and no NaN (``REQUEST_INVALID``,
  ``REQUEST_TOO_LARGE``);
- every write is attributed to the authenticated session, and the log names the route template only: no thread id,
  message id or text reaches it.
"""
from __future__ import annotations

import json
import unittest

import ownerhost_support as T

CATEGORY = 'contract'
A, S, E = T.A, T.S, T.E
NOW = T.utc(2026, 11, 16, 12, 0, 0)
LOCAL = '__LOCALID_8spf4drozrs'
STATEMENT = 'Capture this — café, 中文 \U0001F600\r\n  exactly.  '
JSON = ('content-type', 'application/json')


def user_item(message_id, text, parent=None):
    return {'parentId': parent, 'runConfig': {},
            'message': {'id': message_id, 'createdAt': '2026-11-16T12:00:00.123Z', 'role': 'user',
                        'content': [{'type': 'text', 'text': text}], 'attachments': [], 'metadata': {'custom': {}}}}


def assistant_item(message_id, parent, text='Recorded.'):
    return {'parentId': parent, 'message': {'id': message_id, 'role': 'assistant', 'createdAt': '2026-11-16T12:00:01.000Z',
                                            'status': {'type': 'complete', 'reason': 'unknown'},
                                            'content': [{'type': 'text', 'text': text}], 'metadata': {'custom': {}}}}


class Base(unittest.TestCase):
    def setUp(self):
        self.scratch = T.Scratch()
        self.addCleanup(self.scratch.close)
        self.lines = []
        self.app = A.create_app(lambda: self.scratch.store, clock=lambda: T.stamp(NOW), log=self.lines.append)
        self.credential, self.record = self.scratch.enroll(at=NOW)

    def call(self, method, path, body=None, *headers, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode('utf-8') if body is not None else b'')
        extra = (JSON,) if body is not None and not headers else headers
        return T.call(self.app, method, path, (T.HOST, (S.HEADER, self.credential), *extra), body=data)

    def ok(self, method, path, body=None):
        status, _, answer = self.call(method, path, body)
        self.assertEqual(status, 200, answer)
        return json.loads(answer)

    def refused(self, status, code, method, path, body=None, *headers, raw=None):
        before = self.scratch.dump()
        got, _, answer = self.call(method, path, body, *headers, raw=raw)
        self.assertEqual((got, T.code_of(answer)), (status, code), answer)
        self.assertEqual(self.scratch.dump(), before, f'{code} changed the store')

    def new_thread(self, local=LOCAL):
        return self.ok('POST', '/threads', {'localId': local})['remoteId']


class Threads(Base):
    def test_initialize_mints_the_thread_id_once_per_session_and_local_id(self):
        remote = self.new_thread()
        self.assertRegex(remote, T.CS.THREAD_ID)
        self.assertEqual(self.new_thread(), remote)
        other = self.new_thread('__LOCALID_k9EC8U4')
        self.assertNotEqual(other, remote)
        self.assertEqual(self.ok('GET', '/threads'), {'threads': [{'remoteId': remote, 'status': 'regular'},
                                                                  {'remoteId': other, 'status': 'regular'}]})
        self.assertEqual([t.session_id for t in self.scratch.store.threads()], [self.record.session_id] * 2)

    def test_fetch_rename_archive_and_unarchive(self):
        remote = self.new_thread()
        self.assertEqual(self.ok('GET', f'/threads/{remote}'), {'remoteId': remote, 'status': 'regular'})
        self.assertEqual(self.ok('POST', f'/threads/{remote}/title', {'title': 'Capture form'})['title'], 'Capture form')
        self.assertEqual(self.ok('POST', f'/threads/{remote}/archive')['status'], 'archived')
        self.assertEqual(self.ok('POST', f'/threads/{remote}/unarchive'),
                         {'remoteId': remote, 'status': 'regular', 'title': 'Capture form'})
        self.refused(404, 'THREAD_NOT_FOUND', 'GET', '/threads/3f2a9c1e-7b4d-4e8a-9c0b-1d2e3f405162')
        self.refused(404, 'THREAD_NOT_FOUND', 'GET', '/threads/not-a-thread/messages')
        self.refused(400, 'THREAD_INVALID', 'POST', '/threads', {'localId': 'not-local'})
        self.refused(400, 'THREAD_INVALID', 'POST', f'/threads/{remote}/title', {'title': ''})

    def test_a_thread_delete_is_refused_and_changes_nothing(self):
        remote = self.new_thread()
        self.ok('POST', f'/threads/{remote}/messages', user_item('U000001', STATEMENT))
        self.refused(409, 'THREAD_DELETE_REFUSED', 'POST', f'/threads/{remote}/delete')
        self.refused(405, 'METHOD_NOT_ALLOWED', 'DELETE', f'/threads/{remote}')
        self.assertEqual(len(self.ok('GET', f'/threads/{remote}/messages')['messages']), 1)


class History(Base):
    def exchange(self, remote):
        items = [user_item('U000001', STATEMENT), assistant_item('A000001', 'U000001'),
                 user_item('U000002', 'Edited statement.'), assistant_item('A000002', 'U000002')]
        for seq, item in enumerate(items, start=1):
            answer = self.ok('POST', f'/threads/{remote}/messages', item)
            self.assertEqual(answer, {'id': item['message']['id'], 'seq': seq, 'revision': 1, 'changed': True})
        return items

    def test_a_reload_returns_the_exact_messages_in_order_without_duplicate_ids(self):
        remote = self.new_thread()
        items = self.exchange(remote)
        loaded = self.ok('GET', f'/threads/{remote}/messages')
        self.assertEqual(list(loaded), ['messages'])
        self.assertEqual([m['seq'] for m in loaded['messages']], [1, 2, 3, 4])
        ids = [m['message']['id'] for m in loaded['messages']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([{k: m[k] for k in ('parentId', 'message')} for m in loaded['messages']],
                         [{k: i[k] for k in ('parentId', 'message')} for i in items])
        self.assertEqual(self.scratch.store.message_content(remote, 'U000001'), STATEMENT.encode('utf-8'))
        self.assertEqual({m.session_id for m in self.scratch.store.messages(remote)}, {self.record.session_id})

    def test_a_repeated_append_adds_nothing(self):
        remote = self.new_thread()
        items = self.exchange(remote)
        before = self.scratch.dump()
        for seq, item in enumerate(items, start=1):
            self.assertEqual(self.ok('POST', f'/threads/{remote}/messages', item),
                             {'id': item['message']['id'], 'seq': seq, 'revision': 1, 'changed': False})
        self.assertEqual(self.scratch.dump(), before)

    def test_a_conflicting_id_and_a_changed_user_message_are_refused(self):
        remote = self.new_thread()
        self.exchange(remote)
        self.refused(409, 'MESSAGE_ID_CONFLICT', 'POST', f'/threads/{remote}/messages', user_item('U000001', 'Other.'))
        self.refused(409, 'MESSAGE_IMMUTABLE', 'POST', f'/threads/{remote}/messages/U000001',
                     user_item('U000001', STATEMENT + ' '))
        self.refused(409, 'MESSAGE_PARENT_NOT_FOUND', 'POST', f'/threads/{remote}/messages',
                     assistant_item('A000009', 'U000009'))
        self.refused(404, 'MESSAGE_NOT_FOUND', 'POST', f'/threads/{remote}/messages/U000009',
                     user_item('U000009', 'Created by update?'))
        self.refused(400, 'MESSAGE_INVALID', 'POST', f'/threads/{remote}/messages/A000002',
                     assistant_item('A000001', 'U000001', 'The path names another message.'))

    def test_an_assistant_update_appends_a_revision(self):
        remote = self.new_thread()
        self.exchange(remote)
        answer = self.ok('POST', f'/threads/{remote}/messages/A000002', assistant_item('A000002', 'U000002', 'Done.'))
        self.assertEqual(answer, {'id': 'A000002', 'seq': 4, 'revision': 2, 'changed': True})
        last = self.ok('GET', f'/threads/{remote}/messages')['messages'][-1]
        self.assertEqual(last['message']['content'], [{'type': 'text', 'text': 'Done.'}])

    def test_a_body_is_one_bounded_json_object(self):
        remote = self.new_thread()
        path = f'/threads/{remote}/messages'
        good = json.dumps(user_item('U000001', 'Fine.')).encode()
        self.refused(415, 'REQUEST_INVALID', 'POST', path, None, ('content-type', 'text/plain'), raw=good)
        self.refused(415, 'REQUEST_INVALID', 'POST', path, None, raw=good)
        for raw in (b'[1]', b'{"parentId": null, "parentId": null, "message": {}}', b'{"x": NaN}', b'{"x": Infinity}',
                    b'\xff\xfe', b'{' * 100_000, b''):
            with self.subTest(raw=raw[:40]):
                self.refused(400, 'REQUEST_INVALID', 'POST', path, None, JSON, raw=raw)
        self.refused(413, 'REQUEST_TOO_LARGE', 'POST', path, None, JSON, raw=b' ' * (A.MAX_BODY_BYTES + 1))
        lone = good.replace(b'Fine.', b'\\ud800')
        self.refused(400, 'MESSAGE_INVALID', 'POST', path, None, JSON, raw=lone)
        self.refused(400, 'REQUEST_INVALID', 'POST', '/threads', {'localId': LOCAL, 'extra': 1})

    def test_the_log_names_the_route_template_only(self):
        remote = self.new_thread()
        self.exchange(remote)
        self.call('POST', f'/threads/{remote}/messages', user_item('U000001', 'Other.'))
        self.call('GET', f'/threads/{remote}/messages')
        text = '\n'.join(self.lines)
        for secret in (remote, 'U000001', 'A000001', 'Edited statement', 'Other.', LOCAL, self.credential):
            self.assertNotIn(secret, text)
        self.assertIn(f'accepted POST /threads/{{thread_id}}/messages 409 session={self.record.session_id}', text)
        self.assertIn(f'accepted GET /threads/{{thread_id}}/messages 200 session={self.record.session_id}', text)

    def test_the_shell_s_preflight_admits_the_history_routes(self):
        remote = self.new_thread()
        status, headers, body = T.call(self.app, 'OPTIONS', f'/threads/{remote}/messages/U000001', (
            T.HOST, ('origin', T.SHELL_ORIGIN), ('access-control-request-method', 'POST'),
            ('access-control-request-headers', 'x-aieh-owner-session,content-type')))
        self.assertEqual((status, dict(headers)['access-control-allow-origin']), (200, T.SHELL_ORIGIN))
        self.assertNotIn(remote.encode(), body)


if __name__ == '__main__':
    unittest.main()
