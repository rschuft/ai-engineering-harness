"""U-02.2's proof against a real Integration process that is stopped and started (plan leaf U-02.2; decision 0025,
point 6; I1 work design, slice 6).

The "browser" is the HTTP client: the requests are exactly the ones the Owner host shell sends for a run paused on a
decision, recorded and checked against the shell by its own test (apps/owner-host/src/areas/pending-decision.test.tsx,
fixtures/pending-decision.wire.json). Closing the browser is dropping every connection and every id it held;
reopening it is a new client that reads the thread list and the thread's history back, as the shell's adapters do.

The "service" is a real Integration process: ``app.serve`` in a child process (serve_on_port.py) that this test
starts on a free loopback port it picked and a throwaway state directory (never the managed data root, never the
Owner's 127.0.0.1:13310 instance), and stops the way ``service.py down`` does (the stop-request file, then the
process's exit). The test stops only the processes it started.

One scenario, observed first and judged by the tests: up, the Owner's statement and the paused decision written;
browser closed and service restarted; browser reopened (the thread and its pending call come back once, a reconnect
that re-sends the same requests adds nothing); the decision answered (an update of the same message id, a second
revision); service restarted and browser reopened again (the answered decision, once). Then the lineage message and
conversation resolvers read the store this process wrote, read-only, with authority mode ``authoritative``.
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import ownerhost_support as T

CATEGORY = 'integration'
A, S, E, CS = T.A, T.S, T.E, T.CS
SV = T._load('aieh_ownerhost_service', T.PACKAGE / 'service.py')
TR = T._load('lineage_trace', T.REPO / 'integrations' / 'lineage' / 'lineage_trace.py')
R, L = TR.resolve_mod, TR.L
CHILD = Path(__file__).resolve().parent / 'serve_on_port.py'
WIRE = T.REPO / 'apps' / 'owner-host' / 'src' / 'areas' / 'fixtures' / 'pending-decision.wire.json'
READY_CEILING_S = 60          # bounds a server that never comes up; it normally listens within a second or two
STOP_CEILING_S = 60           # bounds a server that never exits; it normally stops within the poll and the shutdown
POLL_S = 0.05                 # the readiness poll's interval: the wait is on the server record and the port, not a guess
LOCAL = '__LOCALID_u022restart'


def free_port() -> int:
    """A loopback port no listener holds now, never the Integration process's declared one."""
    while True:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind((A.LOOPBACK, 0))
            port = probe.getsockname()[1]
        finally:
            probe.close()
        if port != A.PORT:
            return port


def wire():
    data = json.loads(WIRE.read_text(encoding='utf-8'))
    assert data['format'] == 'aieh-owner-host-wire/v1', 'not the shell\'s wire fixture'
    return data['requests']


class Server:
    """One Integration process this test started: app.serve on PORT, with the state and logs directories given."""

    def __init__(self, state: Path, logs: Path, port: int):
        self.state, self.logs, self.port = state, logs, port
        self.proc = None
        self.pids = []

    def start(self):
        for name in ('stop-request', 'server.json'):
            (self.state / name).unlink(missing_ok=True)
        out = open(self.logs / f'child-{len(self.pids)}.out', 'wb')
        try:
            self.proc = subprocess.Popen([sys.executable, '-I', '-B', str(CHILD), str(self.state), str(self.logs),
                                          str(self.port)], cwd=str(self.state), env=SV.child_environment(os.environ),
                                         stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                         creationflags=SV.no_window.no_window_flags())
        finally:
            out.close()
        deadline = time.monotonic() + READY_CEILING_S
        while time.monotonic() < deadline:
            record = self.record()
            if record and record.get('state') == 'listening' and record.get('port') == self.port:
                self.pids.append(record['pid'])
                return record
            if self.proc.poll() is not None:
                raise AssertionError(f'the server exited {self.proc.returncode} before it listened')
            time.sleep(POLL_S)
        raise AssertionError(f'the server did not listen within {READY_CEILING_S} s')

    def record(self):
        try:
            return json.loads((self.state / 'server.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def stop(self):
        """Stop it as service.py down does; force the process tree only when it does not exit within the ceiling."""
        if self.proc is None or self.proc.poll() is not None:
            return None
        (self.state / 'stop-request').write_text('stop\n', encoding='utf-8')
        try:
            return self.proc.wait(STOP_CEILING_S)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(self.proc.pid)], capture_output=True,
                               creationflags=SV.no_window.no_window_flags(), timeout=STOP_CEILING_S)
            else:
                self.proc.kill()
            self.proc.wait(STOP_CEILING_S)
            raise AssertionError('the server did not stop on its stop request')

    def listening(self) -> bool:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(2)
        try:
            return probe.connect_ex((A.LOOPBACK, self.port)) == 0
        finally:
            probe.close()


class Browser:
    """The shell's side of the wire: every request carries the session header and the shell's origin. A new
    Browser holds nothing of an earlier one (no connection, no id)."""

    def __init__(self, port: int, credential: str):
        self.port, self.credential = port, credential

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection(A.LOOPBACK, self.port, timeout=30)
        headers = {S.HEADER: self.credential, 'Origin': T.SHELL_ORIGIN, 'Host': f'{A.LOOPBACK}:{self.port}'}
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

    def replay(self, requests, thread):
        """The shell's recorded requests, with the thread id the store minted in place of {thread}."""
        answers = []
        for request in requests:
            body = request['body']
            if request['path'] == '/threads':
                body = {'localId': LOCAL}
            answers.append(self.request(request['method'], request['path'].replace('{thread}', thread or ''), body))
        return answers


class PendingDecisionAcrossRestarts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-ownerhost-pending-'))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.state, cls.logs = cls.tmp / 'state' / 'owner-host', cls.tmp / 'logs' / 'owner-host'
        cls.state.mkdir(parents=True)
        cls.logs.mkdir(parents=True)
        cls.store_path = cls.state / CS.DB_NAME
        cls.store = CS.open_store(cls.store_path)
        cls.addClassCleanup(cls.store.close)
        cls.credential, cls.record = E.enroll(cls.store, hours=1)
        cls.port = free_port()
        cls.server = Server(cls.state, cls.logs, cls.port)
        cls.obs = {'port': cls.port}
        requests = wire()
        initialize, statement, paused, answer = requests
        try:
            cls.obs['up'] = cls.server.start()
            first = Browser(cls.port, cls.credential)
            cls.obs['initialize'] = first.replay([initialize], None)[0]
            cls.thread = cls.obs['initialize'][1]['remoteId']
            cls.obs['writes'] = first.replay([statement, paused], cls.thread)
            cls.obs['before'] = first.request('GET', f'/threads/{cls.thread}/messages')
            del first                                                       # the browser is closed
            cls.obs['stopped'] = cls.server.stop()
            cls.obs['port_open_while_down'] = cls.server.listening()
            cls.obs['up_again'] = cls.server.start()
            reopened = Browser(cls.port, cls.credential)                     # a new browser: it holds no id
            cls.obs['threads'] = reopened.request('GET', '/threads')
            cls.obs['after'] = reopened.request('GET', f'/threads/{cls.thread}/messages')
            dump = cls.store.canonical_dump()
            cls.obs['reconnect'] = reopened.replay([initialize, statement, paused], cls.thread)
            cls.obs['reconnect_unchanged'] = dump == cls.store.canonical_dump()
            cls.obs['answer'] = reopened.replay([answer], cls.thread)[0]
            cls.obs['answered'] = reopened.request('GET', f'/threads/{cls.thread}/messages')
            cls.obs['stopped_again'] = cls.server.stop()
            cls.obs['up_third'] = cls.server.start()
            cls.obs['final'] = Browser(cls.port, cls.credential).request('GET', f'/threads/{cls.thread}/messages')
            cls.obs['final_threads'] = Browser(cls.port, cls.credential).request('GET', '/threads')
        finally:
            cls.obs['stopped_last'] = cls.server.stop()
            cls.obs['port_open_after'] = cls.server.listening()
            cls.obs['service_log'] = (cls.logs / 'service.log').read_text(encoding='utf-8', errors='replace')
        cls.requests = requests

    def test_a_real_process_was_started_three_times_on_a_free_port_and_stopped(self):
        self.assertNotEqual(self.port, A.PORT)
        for key in ('up', 'up_again', 'up_third'):
            self.assertEqual((self.obs[key]['address'], self.obs[key]['port']), (A.LOOPBACK, self.port))
        self.assertEqual(len(set(self.server.pids)), 3)           # three processes: each restart is a new one
        self.assertEqual((self.obs['stopped'], self.obs['stopped_again'], self.obs['stopped_last']), (0, 0, 0))
        self.assertFalse(self.obs['port_open_while_down'])
        self.assertFalse(self.obs['port_open_after'])
        self.assertEqual(self.server.record()['state'], 'stopped')

    def test_the_thread_and_its_pending_call_come_back_once_after_both_restarts(self):
        self.assertEqual([(s, a['seq'], a['revision'], a['changed']) for s, a in self.obs['writes']],
                         [(200, 1, 1, True), (200, 2, 1, True)])
        status, before = self.obs['before']
        self.assertEqual((status, self.obs['after']), (200, self.obs['before']))      # the same, byte for byte
        self.assertEqual(self.obs['threads'], (200, {'threads': [{'remoteId': self.thread, 'status': 'regular'}]}))
        messages = before['messages']
        self.assertEqual([(m['seq'], m['message']['id'], m['parentId']) for m in messages],
                         [(1, 'U000001', None), (2, 'A000001', 'U000001')])
        self.assertEqual([m['message'] for m in messages],
                         [self.requests[1]['body']['message'], self.requests[2]['body']['message']])
        paused = messages[1]['message']
        self.assertEqual(paused['status'], {'type': 'requires-action', 'reason': 'tool-calls'})
        (call,) = paused['content']
        self.assertEqual((call['toolName'], call['toolCallId']), ('owner_decision', 'call-1'))
        self.assertNotIn('result', call)                                              # still pending

    def test_a_reconnect_that_sends_the_same_requests_again_adds_nothing(self):
        initialize, *appends = self.obs['reconnect']
        self.assertEqual(initialize, (200, {'remoteId': self.thread}))              # the same thread, not a second
        self.assertEqual([(s, a['changed']) for s, a in appends], [(200, False), (200, False)])
        self.assertTrue(self.obs['reconnect_unchanged'])

    def test_the_answer_is_an_update_of_the_same_message_and_survives_a_restart_once(self):
        self.assertEqual(self.obs['answer'], (200, {'id': 'A000001', 'seq': 2, 'revision': 2, 'changed': True}))
        self.assertEqual(self.obs['final'], self.obs['answered'])
        messages = self.obs['final'][1]['messages']
        self.assertEqual([(m['seq'], m['message']['id']) for m in messages], [(1, 'U000001'), (2, 'A000001')])
        self.assertEqual(messages[1]['message'], self.requests[3]['body']['message'])
        self.assertEqual(messages[1]['message']['content'][0]['result'], {'choice': 'Approve'})
        self.assertEqual(self.obs['final_threads'], self.obs['threads'])
        revisions = self.store.conn.execute(
            "SELECT revision, sha256 FROM message_revision WHERE thread_id = ? AND message_id = 'A000001' "
            'ORDER BY revision', (self.thread,)).fetchall()
        self.assertEqual([r for r, _ in revisions], [1, 2])                         # the pending state is kept
        self.assertEqual(self.store.conn.execute(
            "SELECT count(*) FROM message_revision WHERE message_id = 'U000001'").fetchone()[0], 1)

    def test_the_statement_and_the_thread_resolve_authoritatively_in_the_store_the_process_wrote(self):
        registry = R.build_registry(conversations=self.store_path)
        authorities = TR.Authorities(registry)
        before = self.store.canonical_dump()
        statement = f'conversation:{self.thread}/U000001'
        content = self.store.message_content(self.thread, 'U000001')
        cases = {
            statement: (L.RESOLVED, None, TR.AUTHORITATIVE),
            L.message_reference(self.thread, 'U000001', content).text: (L.RESOLVED, None, TR.AUTHORITATIVE),
            L.span_reference(self.thread, 'U000001', content, 0, len(b'Start')).text:
                (L.RESOLVED, None, TR.AUTHORITATIVE),
            # The thread's last message is the decision's reply, never a statement (I1 work design, R5): unpinned, the
            # thread does not stand for an Owner statement; pinned at the Owner's statement, it does.
            f'conversation:{self.thread}': (L.MISSING, 'CONVERSATION_NOT_A_STATEMENT', TR.AUTHORITATIVE),
            f'conversation:{self.thread}@U000001': (L.RESOLVED, None, TR.AUTHORITATIVE),
            f'conversation:{self.thread}/A000001': (L.MISSING, 'MESSAGE_NOT_A_STATEMENT', TR.AUTHORITATIVE),
            f'conversation:{self.thread}/U000009': (L.MISSING, 'MESSAGE_MISSING', TR.AUTHORITATIVE),
            f'conversation:{self.thread}/U000001#sha256:{"0" * 64}':
                (L.DIGEST_MISMATCH, 'MESSAGE_DIGEST_MISMATCH', TR.AUTHORITATIVE),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                result, mode = authorities.ask(L.parse(text), 'resolve')
                self.assertEqual((result.outcome, result.code, mode), expected)
                self.assertEqual(result.authority, 'Owner conversation store')
        self.assertEqual(authorities.content(L.parse(statement)), 'Start the change.'.encode('utf-8'))
        head, _ = authorities.ask(L.parse(f'conversation:{self.thread}@U000001'), 'current')   # freshness: the head
        self.assertEqual(head.observed_revision, 'A000001')
        self.assertEqual(self.store.canonical_dump(), before)

    def test_the_service_log_names_route_templates_only(self):
        log = self.obs['service_log']
        self.assertIn(f'listening on {A.LOOPBACK}:{self.port}', log)
        self.assertIn(f'accepted POST /threads/{{thread_id}}/messages/{{message_id}} 200 '
                      f'session={self.record.session_id}', log)
        for text in (self.thread, LOCAL, 'U000001', 'A000001', 'Start the change', 'Approve', self.credential):
            self.assertNotIn(text, log)
        self.assertEqual(T.exposures(log, [self.credential]), [])


if __name__ == '__main__':
    unittest.main()
