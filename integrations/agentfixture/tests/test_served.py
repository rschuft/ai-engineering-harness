"""The served fixture's conformance tests (plan leaf E-01.7): the two faces, the label, the refusals, the session
socket, the scenarios and their transport events, the source-derived refusal and create validation, over a real
loopback listener (in a thread of the test process; the process-level properties are test_process.py's).

Create validation needs the locked release openapi.json, which is never committed (decision 0005): the tests that
send a create through the listener run when ``AIEH_LOCKED_OPENAPI`` names it (its sha256 checked) and are skipped,
saying so, otherwise. Every other test creates the conversation in process, through the core the listener serves.
"""
import json
import unittest

import fixture_support as S

CATEGORY = 'integration'

AC, SERVER, TRANSPORT = S.AC, S.SERVER, S.TRANSPORT
OPENAPI = S.locked_openapi_path()
LOCKED = None if OPENAPI is None else SERVER.locked_document(OPENAPI)
NEEDS_DOCUMENT = unittest.skipIf(LOCKED is None, 'AIEH_LOCKED_OPENAPI is not given: create validation needs the '
                                                 'locked openapi.json, never committed (decision 0005)')
CONVERSATION = f'/api/conversations/{S.CID}'


def websockets_client():
    from websockets.sync.client import connect
    from websockets.exceptions import ConnectionClosed, InvalidStatus
    return connect, ConnectionClosed, InvalidStatus


class Listener(unittest.TestCase):
    category = 'integration'
    scenario = 'finished'
    document = None

    def setUp(self):
        self.fixture = SERVER.Fixture(self.scenario, openapi=self.document)
        self.addCleanup(self.fixture.core.close)
        self.served = S.InThread(self.fixture).start()
        self.addCleanup(self.served.stop)
        self.transport = self.served.transport(timeout=30)
        self.core = self.fixture.core

    def held(self):
        """The conversation created in process, through the core the listener serves (no document needed)."""
        self.assertEqual(self.core('POST', '/api/conversations', S.d1_create())['status'], 201)

    def ui(self, method, path, key=S.UI_ACCESS, **kwargs):
        return S.http(self.served.port, method, '/ui' + path, key=key, **kwargs)

    def message(self):
        return self.transport('POST', CONVERSATION + '/events', S.MESSAGE)

    def socket(self, path=f'/ui/sockets/session/{S.CID}', **kwargs):
        connect, _, _ = websockets_client()
        return connect(f'ws://127.0.0.1:{self.served.port}{path}', open_timeout=30, close_timeout=30, **kwargs)


class Faces(Listener):
    def test_every_answer_carries_the_label_on_both_faces(self):
        self.held()
        answers = [S.http(self.served.port, 'GET', '/server_info'),
                   S.http(self.served.port, 'GET', '/api/conversations/count', key=S.DISPATCHER_ACCESS),
                   S.http(self.served.port, 'GET', '/alive'), S.http(self.served.port, 'GET', '/api/conversations/count'),
                   self.ui('GET', '/server_info'), self.ui('GET', CONVERSATION), self.ui('GET', '/alive'),
                   self.ui('GET', CONVERSATION, key=None), self.ui('POST', CONVERSATION, body={})]
        for answer in answers:
            with self.subTest(status=answer['status']):
                self.assertEqual((answer['label']['fixture'], answer['label']['authority']),
                                 ('ai-engineering-harness/agentfixture', 'fixture'))
        self.assertEqual([a['label']['answer'] for a in answers],
                         ['server-info', 'count', 'refusal', 'unauthorized', 'ui-server-info', 'ui-conversation',
                          'refusal', 'ui-unauthorized', 'refusal'])

    def test_each_faces_access_value_is_refused_on_the_other_face(self):
        self.held()
        wrong = S.http(self.served.port, 'GET', CONVERSATION, key=S.UI_ACCESS)
        self.assertEqual((wrong['status'], wrong['body'], wrong['label']['answer']),
                         (401, {'detail': 'Unauthorized'}, 'unauthorized'))
        wrong = self.ui('GET', CONVERSATION, key=S.DISPATCHER_ACCESS)
        self.assertEqual((wrong['status'], wrong['body'], wrong['label']['answer']),
                         (401, {'detail': 'Unauthorized'}, 'ui-unauthorized'))
        self.assertEqual(self.ui('GET', CONVERSATION)['status'], 200)
        self.assertEqual(self.transport('GET', CONVERSATION)['status'], 200)

    def test_the_ui_face_is_read_only_and_a_write_changes_nothing(self):
        self.held()
        before = (len(self.core.calls), json.dumps(self.core.conversations, sort_keys=True, default=str))
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            for path in (CONVERSATION + '/events', '/api/conversations', CONVERSATION,
                         CONVERSATION + '/bash/execute_bash_command'):
                with self.subTest(method=method, path=path):
                    answer = self.ui(method, path, body=S.MESSAGE)
                    self.assertEqual((answer['status'], answer['label']['answer']), (501, 'refusal'))
                    self.assertIn('read only', answer['label']['refused'])
        self.assertEqual((len(self.core.calls), json.dumps(self.core.conversations, sort_keys=True, default=str)),
                         before)

    def test_the_dispatcher_never_calls_the_ui_face(self):
        for path in ('/ui', '/ui/server_info', '/ui?x=1', f'/ui{CONVERSATION}'):
            with self.subTest(path=path):
                with self.assertRaises(TRANSPORT.FixtureTransportError) as caught:
                    self.transport('GET', path)
                self.assertEqual(caught.exception.code, 'FIXTURE_UI_FACE')
        self.assertEqual([c for c in self.fixture.log if c['face'] == 'ui'], [], 'nothing was sent')

    def test_outside_the_catalog_is_501_with_the_label_on_both_faces(self):
        self.held()
        for face, path in (('d', '/alive'), ('d', '/api/conversations/search'), ('d', CONVERSATION + '/events?x=1'),
                           ('d', f'{CONVERSATION}/agent_final_response'), ('u', '/api/settings'),
                           ('u', CONVERSATION + '/events/search?limit=5'), ('u', '/api/conversations/search'),
                           ('u', '/api/conversations/11111111-2222-4333-8444-555555555555')):
            with self.subTest(face=face, path=path):
                answer = S.http(self.served.port, 'GET', path, key=S.DISPATCHER_ACCESS) if face == 'd' \
                    else self.ui('GET', path)
                self.assertEqual((answer['status'], answer['label']['answer'], answer['body']), (501, 'refusal', None))
                self.assertTrue(answer['label']['refused'])


class Cors(Listener):
    """Review ruling 2: no CORS on the dispatcher's face; on the UI face GET only, from configured origins only, never
    with credentials; every preflight labelled, an out-of-catalog one the labelled 501."""
    ORIGIN = 'http://127.0.0.1:13330'

    def setUp(self):
        self.fixture = SERVER.Fixture(self.scenario, ui_origins=(self.ORIGIN,))
        self.addCleanup(self.fixture.core.close)
        self.served = S.InThread(self.fixture).start()
        self.addCleanup(self.served.stop)
        self.transport = self.served.transport(timeout=30)
        self.core = self.fixture.core

    def preflight(self, path, origin=ORIGIN, method='GET', asked='x-session-api-key'):
        headers = {'Origin': origin, 'Access-Control-Request-Method': method}
        if asked:
            headers['Access-Control-Request-Headers'] = asked
        return S.http(self.served.port, 'OPTIONS', path, headers=headers)

    def cors_headers(self, answer):
        return {k: v for k, v in answer['headers'].items() if k.startswith('access-control-')}

    def test_the_dispatchers_face_has_no_cors_and_its_preflight_is_the_labelled_501(self):
        for path in ('/api/conversations', '/server_info', '/alive', CONVERSATION):
            for origin in (self.ORIGIN, 'http://localhost:5173'):
                with self.subTest(path=path, origin=origin):
                    answer = self.preflight(path, origin=origin, method='POST')
                    self.assertEqual((answer['status'], answer['label']['answer']), (501, 'refusal'))
                    self.assertEqual(self.cors_headers(answer), {})
        # review round 2 (M21): a GET preflight from a configured origin, on paths that share a UI template
        for path in ('/server_info', CONVERSATION, CONVERSATION + '/events/search'):
            with self.subTest(get_preflight=path):
                answer = self.preflight(path)
                self.assertEqual((answer['status'], answer['label']['answer'], self.cors_headers(answer)),
                                 (501, 'refusal', {}))
                self.assertIn('dispatcher', answer['label']['refused'])
        plain = S.http(self.served.port, 'OPTIONS', '/api/conversations')
        self.assertEqual((plain['status'], plain['label']['answer']), (501, 'refusal'))
        get = S.http(self.served.port, 'GET', '/api/conversations/count', key=S.DISPATCHER_ACCESS,
                     headers={'Origin': self.ORIGIN})
        self.assertEqual((get['status'], self.cors_headers(get)), (200, {}))

    def test_the_ui_face_allows_get_from_a_configured_origin_only_and_never_credentials(self):
        self.held()
        answer = self.preflight('/ui' + CONVERSATION)
        self.assertEqual((answer['status'], answer['label']['answer'], answer['label']['sourceDerived']),
                         (200, 'ui-preflight', ['status']))
        self.assertEqual(self.cors_headers(answer), {'access-control-allow-origin': self.ORIGIN,
                                                     'access-control-allow-methods': 'GET',
                                                     'access-control-allow-headers': 'x-session-api-key'})
        refused = [self.preflight('/ui' + CONVERSATION, origin='http://localhost:4173'),
                   self.preflight('/ui' + CONVERSATION, method='POST'),
                   self.preflight('/ui/api/settings'),
                   self.preflight('/ui' + CONVERSATION, asked='x-session-api-key,authorization')]
        for answer in refused:
            with self.subTest(refused=answer['label'].get('refused')):
                self.assertEqual((answer['status'], answer['label']['answer'], self.cors_headers(answer)),
                                 (501, 'refusal', {}))
        get = self.ui('GET', CONVERSATION, headers={'Origin': self.ORIGIN})
        self.assertEqual(self.cors_headers(get), {'access-control-allow-origin': self.ORIGIN})
        other = self.ui('GET', CONVERSATION, headers={'Origin': 'http://localhost:5173'})
        self.assertEqual(self.cors_headers(other), {})

    def test_only_a_loopback_http_origin_can_be_configured(self):
        """Review round 2: localhost, 127.0.0.1 or [::1], http, any port; anything else is refused at start, with a
        stable code, by the fixture and by the command line."""
        for origin in ('http://localhost', 'http://127.0.0.1:4173', 'http://[::1]:13330'):
            SERVER.Fixture('finished', ui_origins=(origin,)).core.close()
        for origin in ('https://127.0.0.1:4173', 'http://evil.example', 'http://127.0.0.2', 'http://localhost.evil',
                       'http://127.0.0.1:4173/', 'null', 'http://0.0.0.0:80'):
            with self.subTest(origin=origin):
                with self.assertRaises(SERVER.OriginRefused) as caught:
                    SERVER.Fixture('finished', ui_origins=(origin,))
                self.assertIn('UI_ORIGIN_NOT_LOOPBACK', str(caught.exception))
                self.assertEqual(SERVER.main(['serve', '--log', str(S.PACKAGE / 'never-written.jsonl'),
                                              '--port', str(S.free_port()), '--ui-origin', origin]), 2)

    def test_with_no_configured_origin_every_preflight_is_refused(self):
        fixture = SERVER.Fixture('finished')
        self.addCleanup(fixture.core.close)
        served = S.InThread(fixture).start()
        self.addCleanup(served.stop)
        fixture.core('POST', '/api/conversations', S.d1_create())
        answer = S.http(served.port, 'OPTIONS', '/ui' + CONVERSATION,
                        headers={'Origin': self.ORIGIN, 'Access-Control-Request-Method': 'GET'})
        self.assertEqual((answer['status'], answer['label']['answer']), (501, 'refusal'))


class Robustness(Listener):
    def test_a_body_nested_past_the_parsers_depth_or_not_json_is_a_labelled_400(self):
        """Review N-d: never an unlabelled 500."""
        import http.client
        for raw in (b'[' * 200000, b'{not json', b'\xff\xfe'):
            with self.subTest(size=len(raw)):
                connection = http.client.HTTPConnection('127.0.0.1', self.served.port, timeout=30)
                try:
                    connection.request('POST', '/api/conversations', body=raw,
                                       headers={'Content-Type': 'application/json',
                                                'X-Session-API-Key': S.DISPATCHER_ACCESS})
                    response = connection.getresponse()
                    response.read()
                    label = json.loads(response.getheader('X-AIEH-Fixture'))
                finally:
                    connection.close()
                self.assertEqual((response.status, label['answer']), (400, 'malformed'))
        self.assertEqual(self.core.calls, [])

    def test_a_body_that_parses_but_is_nested_deep_is_a_labelled_400_and_changes_nothing(self):
        """Review round 2: bodies of depth 600 and 900 parse, and the core's copy of them would not: both routes the
        dispatcher's key reaches with a body, refused before the core, its state unchanged."""
        self.held()
        before = (len(self.core.calls), json.dumps(self.core.conversations, sort_keys=True, default=str))
        for route in (CONVERSATION + '/events', CONVERSATION + '/bash/execute_bash_command', '/api/conversations'):
            for deep in (65, 600, 900):
                with self.subTest(route=route, depth=deep):
                    raw = ('[' * deep + ']' * deep).encode('ascii')
                    json.loads(raw)                                   # it parses
                    answer = S.http(self.served.port, 'POST', route, key=S.DISPATCHER_ACCESS, raw=raw)
                    self.assertEqual((answer['status'], answer['label']['answer']), (400, 'malformed'))
        self.assertEqual((len(self.core.calls), json.dumps(self.core.conversations, sort_keys=True, default=str)),
                         before)
        shallow = [[[{'role': 'user'}]]]
        self.assertEqual(SERVER.depth(shallow), 4)

    def test_a_long_core_call_runs_off_the_event_loop(self):
        """Review N-e: while a SEED holds the core (here, a call made to wait on the test's own event), the listener
        still answers a request that needs no core state; nothing waits on a clock."""
        import threading
        entered, release = threading.Event(), threading.Event()
        original = self.fixture.call

        def held_call(method, path, body):
            if path.endswith('/bash/execute_bash_command'):
                entered.set()
                release.wait(60)
            return original(method, path, body)
        self.fixture.call = held_call
        self.held()
        done = {}
        worker = threading.Thread(target=lambda: done.setdefault(
            'answer', self.transport('POST', CONVERSATION + '/bash/execute_bash_command',
                                     {'command': 'x', 'cwd': '/workspace', 'timeout': 5})))
        worker.start()
        self.addCleanup(worker.join, 60)
        self.addCleanup(release.set)
        self.assertTrue(entered.wait(60))
        answer = S.http(self.served.port, 'GET', '/alive', key=S.DISPATCHER_ACCESS)
        self.assertEqual((answer['status'], answer['label']['answer']), (501, 'refusal'))
        self.assertNotIn('answer', done, 'the held call is still held')
        release.set()
        worker.join(60)
        self.assertEqual(done['answer']['fixture']['answer'], 'refusal')


class SourceDerived(Listener):
    def test_the_listener_refuses_the_request_that_would_need_the_source_derived_entry(self):
        self.held()
        self.assertEqual(self.transport('GET', CONVERSATION + '/events/search')['body']['items'], [])
        self.assertEqual(self.message()['status'], 200)
        refused = self.transport('GET', CONVERSATION + '/events/search')
        self.assertEqual((refused['status'], refused['fixture']['answer']), (501, 'refusal'))
        self.assertIn('message-event', refused['fixture']['refused'])
        self.assertNotIn('body', refused)
        # in process the core still answers it, naming its source-derived fields (E-01.4.2's restart matrix)
        inside = self.core('GET', CONVERSATION + '/events/search')
        self.assertEqual(inside['fixture']['sourceDerived'], [f'message-event.{p}' for p in AC.SOURCE_DERIVED])

    def test_the_ui_face_names_its_source_derived_fields_in_the_label(self):
        self.held()
        answer = self.ui('GET', CONVERSATION)
        self.assertEqual(answer['label']['sourceDerived'], ['status', 'body.workspace', 'body.agent',
                                                            'body.execution_status'])
        self.assertEqual(answer['label']['face'], 'ui')
        self.assertEqual(answer['body'], {
            'id': S.CID, 'workspace': {'kind': 'LocalWorkspace', 'working_dir': '/workspace'},
            'agent': {'kind': 'ACPAgent', 'acp_command': ['claude-agent-acp']}, 'execution_status': 'idle',
            'title': S.SERVED['answers']['ui-conversation']['title'],
            'tags': S.SERVED['answers']['ui-conversation']['tags']})
        self.message()
        events = self.ui('GET', CONVERSATION + '/events/search')
        self.assertEqual(events['body'], {'items': [{'kind': 'MessageEvent', 'source': 'user', 'llm_message': {
            'role': 'user', 'content': [{'type': 'text', 'text': 'Implement the change as designed.'}]}}],
            'next_page_id': None})
        self.assertEqual(self.ui('GET', CONVERSATION)['body']['execution_status'], 'finished')

    def test_a_conversation_whose_agent_the_source_does_not_determine_is_refused_on_the_ui_face(self):
        body = S.d1_create()
        body['agent_settings'] = dict(body['agent_settings'], acp_command=['npx', '-y', 'x'])
        self.core('POST', '/api/conversations', body)
        answer = self.ui('GET', CONVERSATION)
        self.assertEqual((answer['status'], answer['label']['answer']), (501, 'refusal'))


class Socket(Listener):
    def test_one_sync_frame_then_the_replay_and_the_label_on_the_handshake(self):
        self.held()
        self.message()
        with self.socket(f'/ui/sockets/session/{S.CID}?after_seq=-1') as ws:
            label = json.loads(ws.response.headers['X-AIEH-Fixture'])
            ws.send(json.dumps({'type': 'auth', 'session_api_key': S.UI_ACCESS}))
            frames = [json.loads(ws.recv(timeout=30)), json.loads(ws.recv(timeout=30))]
        self.assertEqual((label['answer'], label['face']), ('ui-socket', 'ui'))
        self.assertEqual(frames[0], {'type': 'sync', 'from_seq': -1, 'through_seq': 0})
        self.assertEqual((frames[1]['type'], frames[1]['seq'], frames[1]['event']['kind']), ('durable', 0,
                                                                                         'MessageEvent'))

    def test_without_after_seq_only_the_sync_frame(self):
        self.held()
        with self.socket() as ws:
            ws.send(json.dumps({'type': 'auth', 'session_api_key': S.UI_ACCESS}))
            self.assertEqual(json.loads(ws.recv(timeout=30)), {'type': 'sync', 'from_seq': None, 'through_seq': None})

    def test_an_inbound_message_is_refused_and_changes_nothing(self):
        _, closed, _ = websockets_client()
        self.held()
        before = json.dumps(self.core.conversations, sort_keys=True, default=str)
        with self.socket() as ws:
            ws.send(json.dumps({'type': 'auth', 'session_api_key': S.UI_ACCESS}))
            ws.recv(timeout=30)
            ws.send(json.dumps({'role': 'user', 'content': [{'type': 'text', 'text': 'run this'}]}))
            with self.assertRaises(closed) as caught:
                ws.recv(timeout=30)
        self.assertEqual(caught.exception.rcvd.code, SERVER.REFUSED_CLOSE)
        self.assertIn('FIXTURE_NO_OBSERVATION', caught.exception.rcvd.reason)
        self.assertEqual(json.dumps(self.core.conversations, sort_keys=True, default=str), before)

    def test_authentication_as_the_pinned_server_refuses_it(self):
        _, closed, invalid = websockets_client()
        self.held()
        with self.socket() as ws:
            ws.send(json.dumps({'type': 'auth', 'session_api_key': S.DISPATCHER_ACCESS}))
            with self.assertRaises(closed) as caught:
                ws.recv(timeout=30)
        self.assertEqual((caught.exception.rcvd.code, caught.exception.rcvd.reason), (4001, 'Authentication failed'))
        with self.assertRaises(invalid) as denied:
            with self.socket(additional_headers={'X-Session-API-Key': 'wrong'}):
                pass
        self.assertEqual(denied.exception.response.status_code, 403)
        self.assertEqual(json.loads(denied.exception.response.headers['X-AIEH-Fixture'])['answer'], 'ui-socket-denied')

    def test_a_socket_outside_the_catalog_is_refused_with_the_label(self):
        _, closed, _ = websockets_client()
        for path in (f'/sockets/session/{S.CID}', f'/ui/sockets/events/{S.CID}',
                     '/ui/sockets/session/11111111-2222-4333-8444-555555555555'):
            with self.subTest(path=path):
                with self.socket(path) as ws:
                    if path.startswith('/ui/sockets/session/'):
                        ws.send(json.dumps({'type': 'auth', 'session_api_key': S.UI_ACCESS}))
                    with self.assertRaises(closed) as caught:
                        ws.recv(timeout=30)
                self.assertEqual(caught.exception.rcvd.code, SERVER.REFUSED_CLOSE)


class Running(Listener):
    scenario = 'running'

    def test_the_ui_face_runs_for_its_own_reads_while_the_dispatchers_face_is_finished(self):
        self.held()
        self.assertEqual(self.ui('GET', CONVERSATION)['body']['execution_status'], 'idle')
        self.message()
        self.assertEqual(self.transport('GET', CONVERSATION)['body']['execution_status'], 'finished')
        seen = [self.ui('GET', CONVERSATION)['body']['execution_status'] for _ in range(SERVER.RUNNING_READS + 2)]
        self.assertEqual(seen, ['running'] * SERVER.RUNNING_READS + ['finished'] * 2)
        self.assertEqual(self.transport('GET', CONVERSATION)['body']['execution_status'], 'finished')


class Failed(Listener):
    scenario = 'failed'

    def test_the_create_is_refused_as_s_01_3_1_observed(self):
        self.assertEqual(self.transport('GET', '/server_info')['status'], 200)
        answer = self.transport('POST', '/api/conversations', S.d1_create())
        self.assertEqual((answer['status'], answer['body'], answer['fixture']['answer']),
                         (401, {'detail': 'Unauthorized'}, 'unauthorized'))
        self.assertEqual((self.core.creates, self.core.conversations), ([], {}))


class Pending(Listener):
    scenario = 'pending'

    def test_the_message_never_reaches_the_core_and_the_conversation_stays_idle(self):
        self.held()
        short = self.served.transport(timeout=2)       # a ceiling: the response is withheld until the client leaves
        with self.assertRaises(TRANSPORT.FixtureTransportError) as caught:
            short('POST', CONVERSATION + '/events', S.MESSAGE)
        self.assertEqual(caught.exception.code, 'NO_ANSWER')
        self.assertEqual(self.core.messages(), [])
        self.assertEqual(self.transport('GET', CONVERSATION)['body']['execution_status'], 'idle')
        self.assertEqual(self.ui('GET', CONVERSATION)['body']['execution_status'], 'idle')
        self.assertIn('request never reaches the core (the message)', [c['event'] for c in self.fixture.log])


@NEEDS_DOCUMENT
class Validated(Listener):
    document = LOCKED

    def test_a_valid_create_is_answered_201_and_an_invalid_one_never(self):
        bad = dict(S.d1_create(), workspace={'kind': 'LocalWorkspace'})
        answer = self.transport('POST', '/api/conversations', bad)
        self.assertEqual((answer['status'], answer['fixture']['answer']), (501, 'refusal'))
        self.assertIn('does not validate against StartConversationRequest', answer['fixture']['refused'])
        self.assertEqual((self.core.calls, self.core.conversations), ([], {}), 'the core never saw it')
        self.assertEqual(self.transport('POST', '/api/conversations', S.d1_create())['status'], 201)


class Unvalidated(Listener):
    def test_without_the_locked_document_every_create_is_refused(self):
        answer = self.transport('POST', '/api/conversations', S.d1_create())
        self.assertEqual((answer['status'], answer['fixture']['answer']), (501, 'refusal'))
        self.assertIn('the locked openapi.json is not given', answer['fixture']['refused'])
        self.assertEqual(self.core.calls, [])


@NEEDS_DOCUMENT
class LostAcknowledgement(Listener):
    scenario = 'lost-create-acknowledgement'
    document = LOCKED

    def test_the_create_reaches_the_core_its_answer_is_withheld_and_the_lookup_answered(self):
        with self.assertRaises(TRANSPORT.FixtureTransportError) as caught:
            self.served.transport(timeout=2)('POST', '/api/conversations', S.d1_create())
        self.assertEqual(caught.exception.code, 'NO_ANSWER')
        self.assertEqual(len(self.core.creates), 1)
        self.assertEqual(self.transport('GET', CONVERSATION)['status'], 200)


@NEEDS_DOCUMENT
class Unknown(Listener):
    scenario = 'unknown'
    document = LOCKED

    def test_the_create_and_every_lookup_reach_the_core_and_are_withheld(self):
        short = self.served.transport(timeout=2)
        for method, path, body in (('POST', '/api/conversations', S.d1_create()), ('GET', CONVERSATION, None),
                                   ('GET', CONVERSATION, None)):
            with self.subTest(method=method):
                with self.assertRaises(TRANSPORT.FixtureTransportError):
                    short(method, path, body)
        self.assertEqual([c[:2] for c in self.core.calls], [('POST', '/api/conversations'), ('GET', CONVERSATION),
                                                           ('GET', CONVERSATION)])


class CallLog(Listener):
    scenario = 'failed'

    def test_the_call_log_names_face_method_path_and_answer_never_a_body(self):
        body = dict(S.d1_create(), secrets={'CLAUDE_CODE_OAUTH_TOKEN': 'throwaway-secret-value-xyz'})
        self.transport('POST', '/api/conversations', body)
        self.ui('GET', '/server_info')
        self.assertEqual([(c['face'], c['method'], c['path'], c['answer']) for c in self.fixture.log],
                         [('dispatcher', 'POST', '/api/conversations', 'unauthorized'),
                          ('ui', 'GET', '/server_info', 'ui-server-info')])
        self.assertNotIn('throwaway-secret-value-xyz', json.dumps(self.fixture.log))


class Authority(Listener):
    def test_no_answer_of_the_fixture_can_be_taken_as_live(self):
        lineage = S.load('aieh_lineage_resolve_for_fixture', S.REPO / 'integrations' / 'lineage' / 'lineage_resolve.py')
        self.held()
        self.message()
        answers = [self.transport('GET', '/server_info'), self.transport('GET', CONVERSATION),
                   self.transport('GET', '/alive'), self.transport('GET', CONVERSATION + '/runtime'),
                   self.served.transport(access=S.UI_ACCESS)('GET', '/api/conversations/count')]
        for answer in answers:
            with self.subTest(answer=answer['fixture']['answer']):
                self.assertEqual(lineage.answering_authority(answer), lineage.FIXTURE)
        self.assertEqual(TRANSPORT.FixtureTransport.authority, 'fixture')


if __name__ == '__main__':
    unittest.main()
