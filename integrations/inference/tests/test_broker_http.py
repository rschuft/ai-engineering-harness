"""The broker on its two loopback listeners against a fake upstream per declared family (decision 0015 as
amended): the control listener, untranslated pass-through with the provider key substituted for the attempt
token, incremental streaming and usage, revocation and expiry over the wire, refusals with stable codes,
egress to the configured origin only, and the audit's content. One broker and three fake upstreams per module,
all on ephemeral 127.0.0.1 ports in this process; synthetic key, tokens and models.
"""
from __future__ import annotations

import http.client
import json
import socket
import unittest
from unittest import mock

import broker_support as S

CATEGORY = 'integration'
IB = S.IB
UPSTREAMS: dict = {}
RIG = None
ORIGINS: list = []      # every origin the broker's connector was asked for
TOKENS: list = []       # every token issued in this module


def spy(origin, timeout):
    ORIGINS.append(origin.text())
    return IB.connect_upstream(origin, timeout)


def setUpModule():
    global RIG
    for family in S.FAMILIES:
        UPSTREAMS[family] = S.FakeUpstream(family)
    RIG = S.Rig(S.component({family: up.origin for family, up in UPSTREAMS.items()}), connect=spy).start()


def tearDownModule():
    RIG.close()
    for upstream in UPSTREAMS.values():
        upstream.close()


def issue(family='openai-chat', models=(S.MODEL_A,), requests=20, tokens=10_000, ttl=600):
    body = {'conversation_id': S.new_id(), 'attempt_id': S.new_id(), 'family': family, 'models': list(models),
            'budget': {'requests': requests, 'tokens': tokens}, 'ttl_s': ttl}
    status, answer = S.control(RIG, 'POST', '/v1/grants', body)
    assert status == 201, answer
    TOKENS.append(answer['token'])
    return answer


def infer(grant, family, *, model=S.MODEL_A, stream=False, extra=(), target=None, host=None):
    body = {'model': model, 'stream': stream, 'input': S.PROMPT_MARKER}
    pairs = [S.auth(family, grant['token']), ('Content-Type', 'application/json')] + list(extra)
    return S.request(RIG.inference, 'POST', target or S.ROUTE[family], body, pairs, host=host)


def refusal(data: bytes) -> str:
    return json.loads(data)['aieh_refusal']['code']


class TestControlListener(unittest.TestCase):
    def test_issue_status_and_revoke(self):
        grant = issue(family='openai-responses', models=(S.MODEL_A, S.MODEL_B))
        self.assertEqual(grant['family'], 'openai-responses')
        status, answer = S.control(RIG, 'GET', f'/v1/grants/{grant["token_fingerprint"]}')
        self.assertEqual((status, answer['state'], answer['models']), (200, 'live', [S.MODEL_A, S.MODEL_B]))
        self.assertNotIn('token', answer)
        status, broker = S.control(RIG, 'GET', '/v1/status')
        self.assertEqual(status, 200)
        self.assertEqual(broker['provider_key'], {'provider': S.PROVIDER, 'source': 'memory-fake',
                                                  'fingerprint': IB.contract.fingerprint(S.KEY)})
        self.assertEqual({f['id']: f['ready'] for f in broker['families']}, dict.fromkeys(S.FAMILIES, True))
        self.assertEqual(broker['listeners']['control'], {'address': '127.0.0.1', 'port': RIG.control})
        status, answer = S.control(RIG, 'POST', '/v1/grants/revoke', {
            'token_fingerprint': grant['token_fingerprint'], 'trigger': 'attempt end', 'revoker': 'dispatcher'})
        self.assertEqual((status, answer['state'], answer['receipt']['state']), (200, 'revoked', 'confirmed'))
        status, answer = S.control(RIG, 'POST', '/v1/grants/revoke', {
            'token_fingerprint': grant['token_fingerprint'], 'trigger': 'attempt end', 'revoker': 'dispatcher'})
        self.assertEqual((status, answer['aieh_refusal']['code']), (409, 'GRANT_ALREADY_REVOKED'))

    def test_each_control_refusal(self):
        good = {'conversation_id': S.new_id(), 'attempt_id': S.new_id(), 'family': 'openai-chat',
                'models': [S.MODEL_C], 'budget': {'requests': 1, 'tokens': 1}, 'ttl_s': 1}
        for (method, path, body, kwargs), expected in (
                (('GET', '/v1/grants', None, {}), (404, 'CONTROL_ROUTE_UNKNOWN')),
                (('DELETE', '/v1/status', None, {}), (404, 'CONTROL_ROUTE_UNKNOWN')),
                (('POST', '/v1/status', {}, {}), (404, 'CONTROL_ROUTE_UNKNOWN')),
                (('POST', '/v1/messages', {}, {}), (404, 'CONTROL_ROUTE_UNKNOWN')),
                (('GET', '/v1/status', None, {'extra': [('Origin', 'http://127.0.0.1')]}),
                 (403, 'CONTROL_CALLER_REFUSED')),
                (('POST', '/v1/grants', good, {'content_type': 'text/plain'}), (415, 'CONTROL_CONTENT_TYPE')),
                (('POST', '/v1/grants', good, {}), (403, 'MODEL_NOT_ALLOWLISTED')),
                (('POST', '/v1/grants', [1], {}), (400, 'CONTROL_BODY_INVALID')),
                (('POST', '/v1/grants', {'x': 'y' * 70000}, {}), (400, 'CONTROL_BODY_INVALID'))):
            with self.subTest(method=method, path=path, expected=expected):
                status, answer = S.control(RIG, method, path, body, **kwargs)
                self.assertEqual((status, answer['aieh_refusal']['code']), expected)
                self.assertTrue(answer['aieh_refusal']['remedy'])
        status, headers, data = S.request(RIG.control, 'GET', '/v1/status', host='localhost')
        self.assertEqual((status, refusal(data), headers.get('connection')), (403, 'CONTROL_CALLER_REFUSED', 'close'))
        status, _, data = S.request(RIG.control, 'POST', '/v1/grants', raw_body=b'{not json',
                                    header_pairs=[('Content-Type', 'application/json')])
        self.assertEqual((status, refusal(data)), (400, 'CONTROL_BODY_INVALID'))
        self.assertEqual(json.loads(data)['aieh_refusal']['detail'], 'the body is not JSON')

    def test_the_inference_listener_serves_no_control_route(self):
        status, _, data = S.request(RIG.inference, 'GET', '/v1/status')
        self.assertEqual((status, refusal(data)), (401, 'TOKEN_MISSING'))


class TestPassThrough(unittest.TestCase):
    def test_each_family_is_passed_through_untranslated_with_the_provider_key(self):
        for family in S.FAMILIES:
            with self.subTest(family=family):
                upstream = UPSTREAMS[family]
                grant = issue(family=family)
                seen = len(upstream.requests)
                status, headers, data = infer(grant, family, extra=[('Anthropic-Version', 'synthetic-1'),
                                                                    ('X-Api-Key', grant['token'])])
                self.assertEqual(status, 200, data)
                self.assertEqual(json.loads(data), S.json_answer(family))
                self.assertEqual((headers['content-type'], headers['x-synthetic-upstream'], headers['content-length']),
                                 ('application/json', family, str(len(data))))
                (received,) = upstream.requests[seen:]
                self.assertEqual((received['method'], received['path']), ('POST', S.ROUTE[family]))
                self.assertEqual(json.loads(received['body']), {'model': S.MODEL_A, 'stream': False,
                                                                'input': S.PROMPT_MARKER})
                names = [name.lower() for name, _ in received['headers']]
                credential = [value for name, value in received['headers'] if name.lower() in
                              ('authorization', 'x-api-key')]
                self.assertEqual(credential, [S.KEY if family == 'anthropic-messages' else f'Bearer {S.KEY}'])
                self.assertEqual(dict((n.lower(), v) for n, v in received['headers'])['host'],
                                 f'127.0.0.1:{upstream.port}')
                self.assertIn(('Accept-Encoding', 'identity'), received['headers'])
                self.assertIn('anthropic-version', names)
                self.assertFalse(any(grant['token'] in value for _, value in received['headers']))
                self.assertNotIn(grant['token'].encode(), received['body'])
                answer = RIG.broker.grant_status(grant['token_fingerprint'])
                self.assertEqual((answer['requests'], answer['in_flight'], answer['usage']['total']), (1, 0, 18))

    def test_each_family_streams_and_its_usage_comes_from_the_final_event(self):
        for family in S.FAMILIES:
            with self.subTest(family=family):
                grant = issue(family=family)
                status, headers, data = infer(grant, family, stream=True)
                self.assertEqual((status, headers['content-type'], headers['transfer-encoding']),
                                 (200, 'text/event-stream', 'chunked'))
                self.assertIn(S.ANSWER_MARKER.encode(), data)
                self.assertEqual(RIG.broker.grant_status(grant['token_fingerprint'])['usage']['total'], 18)

    def test_a_stream_is_passed_on_as_it_arrives(self):
        upstream = UPSTREAMS['anthropic-messages']
        upstream.release.clear()
        upstream.first_sent.clear()
        grant = issue(family='anthropic-messages', models=('syn-gated',))
        connection = http.client.HTTPConnection('127.0.0.1', RIG.inference, timeout=30)
        try:
            body = json.dumps({'model': 'syn-gated', 'stream': True}).encode()
            connection.request('POST', '/v1/messages', body, {'x-api-key': grant['token'],
                                                              'Content-Type': 'application/json'})
            response = connection.getresponse()
            first = response.read1(65536)
            self.assertTrue(upstream.first_sent.is_set())
            self.assertFalse(upstream.release.is_set())   # the rest is still held at the upstream
            self.assertIn(b'message_start', first)
            self.assertNotIn(b'message_delta', first)
            upstream.release.set()
            rest = response.read()
        finally:
            upstream.release.set()
            connection.close()
        self.assertIn(b'message_stop', rest)
        self.assertEqual(RIG.broker.grant_status(grant['token_fingerprint'])['usage']['total'], 18)

    def test_an_answer_without_usage_stops_the_attempt_and_an_upstream_error_does_not(self):
        grant = issue(family='openai-chat', models=('syn-no-usage', 'syn-error', S.MODEL_A))
        status, _, data = infer(grant, 'openai-chat', model='syn-error')
        self.assertEqual((status, json.loads(data)['error']['message']), (500, 'synthetic upstream error'))
        status, _, _ = infer(grant, 'openai-chat', model='syn-no-usage', stream=True)
        self.assertEqual(status, 200)
        status, _, data = infer(grant, 'openai-chat')
        self.assertEqual((status, refusal(data)), (429, 'BUDGET_USAGE_UNKNOWN'))
        answer = RIG.broker.grant_status(grant['token_fingerprint'])
        self.assertEqual((answer['requests'], answer['refused'], answer['usage']['unknown_responses']), (2, 1, 1))

    def test_budgets_over_the_wire(self):
        grant = issue(family='openai-responses', requests=1)
        self.assertEqual(infer(grant, 'openai-responses')[0], 200)
        status, _, data = infer(grant, 'openai-responses')
        self.assertEqual((status, refusal(data)), (429, 'BUDGET_REQUESTS_EXHAUSTED'))
        grant = issue(family='openai-responses', tokens=18)
        self.assertEqual(infer(grant, 'openai-responses')[0], 200)
        status, _, data = infer(grant, 'openai-responses')
        self.assertEqual((status, refusal(data)), (429, 'BUDGET_TOKENS_EXHAUSTED'))


class TestRefusalsOnTheWire(unittest.TestCase):
    def test_revocation_and_expiry_answer_401_at_the_next_request(self):
        grant = issue(family='anthropic-messages')
        self.assertEqual(infer(grant, 'anthropic-messages')[0], 200)
        S.control(RIG, 'POST', '/v1/grants/revoke', {'token_fingerprint': grant['token_fingerprint'],
                                                     'trigger': 'suspected exposure', 'revoker': 'owner (test)'})
        status, headers, data = infer(grant, 'anthropic-messages')
        self.assertEqual((status, refusal(data), headers['connection']), (401, 'TOKEN_REVOKED', 'close'))
        grant = issue(family='anthropic-messages', ttl=10)
        RIG.clock.now += 10
        try:
            status, _, data = infer(grant, 'anthropic-messages')
        finally:
            RIG.clock.now -= 10
        self.assertEqual((status, refusal(data)), (401, 'TOKEN_EXPIRED'))

    def test_refusals_carry_their_status_and_code(self):
        grant = issue(family='openai-chat', models=(S.MODEL_A,))
        for kwargs, expected in (
                ({'target': '/v1/messages'}, (404, 'ROUTE_NOT_ALLOWED')),
                ({'target': '/v1/chat/completions?x=1'}, (400, 'QUERY_NOT_ALLOWED')),
                ({'model': S.MODEL_B}, (403, 'MODEL_NOT_ALLOWED'))):
            with self.subTest(kwargs=kwargs):
                status, _, data = infer(grant, 'openai-chat', **kwargs)
                self.assertEqual((status, refusal(data)), expected)
        status, _, data = S.request(RIG.inference, 'POST', '/v1/chat/completions', header_pairs=[
            S.auth('openai-chat', grant['token']), ('Content-Length', str(64 * 1024 * 1024))])
        self.assertEqual((status, refusal(data)), (413, 'BODY_TOO_LARGE'))
        status, _, data = S.request(RIG.inference, 'POST', '/v1/chat/completions', {'model': S.MODEL_A})
        self.assertEqual((status, refusal(data)), (401, 'TOKEN_MISSING'))

    def test_the_broker_connects_only_to_the_family_upstream(self):
        grant = issue(family='openai-chat')
        before = len(ORIGINS)
        evil = [('X-Forwarded-Host', 'evil.example.test'), ('Forwarded', 'host=evil.example.test')]
        self.assertEqual(infer(grant, 'openai-chat', host='evil.example.test:443', extra=evil)[0], 200)
        status, _, data = infer(grant, 'openai-chat', target='http://evil.example.test/v1/chat/completions')
        self.assertEqual((status, refusal(data)), (404, 'ROUTE_NOT_ALLOWED'))
        self.assertEqual(ORIGINS[before:], [UPSTREAMS['openai-chat'].origin])
        received = UPSTREAMS['openai-chat'].requests[-1]
        self.assertFalse(any('evil' in value for _, value in received['headers']))
        self.assertEqual(set(ORIGINS), {up.origin for up in UPSTREAMS.values()})

    def test_an_unreachable_upstream_is_a_502_with_its_code(self):
        closed = []

        class Broken:
            """A connection whose upstream resets while the request is sent."""
            def putrequest(self, *args, **kwargs):
                pass

            def putheader(self, *args):
                pass

            def endheaders(self, body=None):
                raise ConnectionResetError(10054, 'synthetic reset')

            def close(self):
                closed.append(True)

        def refused(origin, timeout):
            if origin.port == 1:
                raise ConnectionRefusedError(10061, 'synthetic refusal')
            return Broken()
        raw = S.component({'openai-chat': 'http://127.0.0.1:1', 'openai-responses': 'http://127.0.0.1:2'})
        rig = S.Rig(raw, connect=refused).start()
        try:
            for family in ('openai-chat', 'openai-responses'):
                with self.subTest(family=family):
                    body = {'conversation_id': S.new_id(), 'attempt_id': S.new_id(), 'family': family,
                            'models': [S.MODEL_A], 'budget': {'requests': 5, 'tokens': 100}, 'ttl_s': 60}
                    status, grant = S.control(rig, 'POST', '/v1/grants', body)
                    status, _, data = S.request(rig.inference, 'POST', S.ROUTE[family], {'model': S.MODEL_A},
                                                [S.auth(family, grant['token'])])
                    self.assertEqual((status, refusal(data)), (502, 'UPSTREAM_UNREACHABLE'))
                    answer = rig.broker.grant_status(grant['token_fingerprint'])
                    self.assertEqual((answer['requests'], answer['in_flight'], answer['usage']['unknown_responses']),
                                     (1, 0, 0))
            self.assertEqual(closed, [True])
        finally:
            rig.close()
        rig.broker.stop()   # stopping twice is harmless

    def test_no_other_socket_can_take_a_listener_port(self):
        for port in (RIG.control, RIG.inference):
            with self.subTest(port=port):
                intruder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    intruder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    with self.assertRaises(OSError):
                        intruder.bind(('127.0.0.1', port))
                finally:
                    intruder.close()

    def test_an_answer_that_would_hold_a_secret_is_withheld(self):
        grant = issue()
        status, answer = S.control(RIG, 'POST', '/v1/grants/revoke', {
            'token_fingerprint': grant['token_fingerprint'], 'trigger': 'owner direction',
            'revoker': f'owner {S.KEY}'})
        self.assertEqual((status, answer['aieh_refusal']['code']), (500, 'EXPOSURE_FOUND'))
        status, answer = S.control(RIG, 'GET', f'/v1/grants/{grant["token_fingerprint"]}')
        self.assertEqual((status, answer['aieh_refusal']['code']), (500, 'EXPOSURE_FOUND'))
        self.assertEqual(infer(grant, 'openai-chat')[0], 401)
        self.assertNotIn(S.KEY, json.dumps(answer))

    def test_a_control_body_over_its_limit_is_refused_even_when_valid(self):
        body = {'conversation_id': S.new_id(), 'attempt_id': S.new_id(), 'family': 'openai-chat',
                'models': [S.MODEL_A], 'budget': {'requests': 1, 'tokens': 1}, 'ttl_s': 1}
        padded = json.dumps(body).encode() + b' ' * IB.CONTROL_BODY_LIMIT
        status, _, data = S.request(RIG.control, 'POST', '/v1/grants', raw_body=padded,
                                    header_pairs=[('Content-Type', 'application/json')])
        self.assertEqual((status, refusal(data)), (400, 'CONTROL_BODY_INVALID'))


class TestAudit(unittest.TestCase):
    KEYS = {'format', 'time', 'event', 'attempt_id', 'conversation_id', 'token_fingerprint', 'family', 'method',
            'path', 'query_names', 'model', 'unrecorded', 'request_bytes', 'response_bytes', 'status',
            'upstream_status', 'latency_ms', 'usage', 'code'}

    def test_one_line_per_request_without_body_header_token_or_key(self):
        grant = issue(family='openai-responses')
        status, _, answer = infer(grant, 'openai-responses', extra=[('X-Synthetic-Header', 'header-value-5e1f')])
        self.assertEqual(status, 200)
        self.assertEqual(infer(grant, 'openai-responses', model=S.MODEL_B)[0], 403)
        lines = RIG.audit_lines()
        mine = [line for line in lines if line.get('token_fingerprint') == grant['token_fingerprint']]
        self.assertEqual(len(mine), 2)
        for line in mine:
            self.assertEqual(set(line), self.KEYS)
        ok, refused = mine
        request = json.dumps({'model': S.MODEL_A, 'stream': False, 'input': S.PROMPT_MARKER}).encode()
        self.assertEqual({k: ok[k] for k in ('format', 'event', 'attempt_id', 'conversation_id', 'family', 'method',
                                             'path', 'model', 'request_bytes', 'response_bytes', 'status',
                                             'upstream_status', 'usage', 'code')},
                         {'format': 'aieh-inference-audit/1', 'event': 'request', 'attempt_id': grant['attempt_id'],
                          'conversation_id': grant['conversation_id'], 'family': 'openai-responses',
                          'method': 'POST', 'path': '/v1/responses', 'model': S.MODEL_A,
                          'request_bytes': len(request), 'response_bytes': len(answer), 'status': 200,
                          'upstream_status': 200, 'usage': {'input': 11, 'output': 7, 'total': 18}, 'code': None})
        self.assertIsInstance(ok['latency_ms'], float)
        self.assertEqual((ok['query_names'], ok['unrecorded']), (None, None))
        self.assertEqual((refused['status'], refused['code'], refused['path'], refused['query_names'], refused['model'],
                          refused['unrecorded'], refused['upstream_status']),
                         (403, 'MODEL_NOT_ALLOWED', '/v1/responses', None, S.MODEL_B, None, None))
        self.assertEqual(lines[0]['event'], 'broker-start')
        text = RIG.audit.path.read_text(encoding='utf-8')
        for needle in [S.KEY, S.PROMPT_MARKER, S.ANSWER_MARKER, 'header-value-5e1f', 'x-api-key', 'Bearer',
                       'authorization'] + TOKENS:
            self.assertNotIn(needle, text)

    def test_the_i7_scan_finds_no_token_or_key_in_the_audit_or_the_store(self):
        issue()
        guard = IB.contract.ExposureGuard()
        for secret in [S.KEY] + TOKENS:
            guard.hold(secret)
        files = [RIG.audit.path] + sorted(RIG.tmp.glob('integration.sqlite*'))
        guard.scan_files(files)
        report = guard.report()
        self.assertEqual((report['found_in'], report['unreadable'], report['clean']), ([], [], True))
        self.assertGreaterEqual(report['scanned'], 2)

    def test_a_line_that_would_hold_a_secret_is_withheld(self):
        before = RIG.audit.withheld
        RIG.audit.write({'event': 'test', 'detail': S.KEY})
        RIG.audit.write({'event': 'test', 'detail': 'f' * 40})
        lines = RIG.audit_lines()[-2:]
        self.assertEqual([line.get('withheld') for line in lines], ['EXPOSURE_FOUND', 'EXPOSURE_FOUND'])
        self.assertEqual(RIG.audit.withheld, before + 2)
        self.assertNotIn(S.KEY, RIG.audit.path.read_text(encoding='utf-8'))


class TestRefusedRequestAudit(unittest.TestCase):
    """The audit of a refused request (the S-03.3 slice plan's D-4): the method, the path, the query parameter names
    and, for a request presenting a grant's token, the requested model, each only in its bounded grammar, for route
    and model discovery without a model call. Never a query value, a header, any other part of the body or a
    credential."""

    def line_of(self, grant):
        return [line for line in RIG.audit_lines() if line.get('token_fingerprint') == grant['token_fingerprint']][-1]

    def fields(self, line):
        self.assertEqual((line['request_bytes'], line['response_bytes'], line['upstream_status'], line['usage']),
                         (0, 0, None, None))
        return {key: line[key] for key in ('method', 'path', 'query_names', 'model', 'unrecorded', 'code')}

    def test_a_refused_route_records_its_path_query_names_and_model(self):
        grant = issue(family='anthropic-messages')
        status, _, data = infer(grant, 'anthropic-messages', model=S.MODEL_B,
                                target='/v1/messages/count_tokens?beta=true&beta=1&api-version=2023-06-01')
        self.assertEqual((status, refusal(data)), (404, 'ROUTE_NOT_ALLOWED'))
        self.assertEqual(self.fields(self.line_of(grant)),
                         {'method': 'POST', 'path': '/v1/messages/count_tokens', 'query_names': ['api-version', 'beta'],
                          'model': S.MODEL_B, 'unrecorded': None, 'code': 'ROUTE_NOT_ALLOWED'})
        status, _, data = S.request(RIG.inference, 'GET', '/v1/models?limit=20',
                                    header_pairs=[S.auth('anthropic-messages', grant['token'])])
        self.assertEqual((status, refusal(data)), (404, 'ROUTE_NOT_ALLOWED'))
        self.assertEqual(self.fields(self.line_of(grant)),
                         {'method': 'GET', 'path': '/v1/models', 'query_names': ['limit'], 'model': None,
                          'unrecorded': None, 'code': 'ROUTE_NOT_ALLOWED'})

    def test_a_refused_query_on_a_declared_route_records_names_never_values(self):
        grant = issue(family='anthropic-messages')
        target = f'/v1/messages?beta=true&key={S.KEY}&token={grant["token"]}&q=query-value-91ac'
        status, _, data = infer(grant, 'anthropic-messages', target=target,
                                extra=[('X-Debug', S.KEY), ('X-Synthetic-Header', 'header-value-77b1')])
        self.assertEqual((status, refusal(data)), (400, 'QUERY_NOT_ALLOWED'))
        line = self.line_of(grant)
        self.assertEqual(self.fields(line), {'method': 'POST', 'path': '/v1/messages',
                                             'query_names': ['beta', 'key', 'q', 'token'], 'model': S.MODEL_A,
                                             'unrecorded': None, 'code': 'QUERY_NOT_ALLOWED'})
        self.assertNotIn('withheld', line)
        text = RIG.audit.path.read_text(encoding='utf-8')
        for needle in (S.KEY, grant['token'], grant['token'][len(IB.TOKEN_PREFIX):], 'query-value-91ac',
                       'header-value-77b1', 'x-debug', 'X-Debug', 'x-synthetic-header', S.PROMPT_MARKER):
            with self.subTest(needle=needle[:12]):
                self.assertNotIn(needle, text)

    def test_a_credential_in_the_path_a_name_or_the_model_is_counted_not_recorded(self):
        grant = issue(family='anthropic-messages')
        for target, body, expected in (
                (f'/v1/{grant["token"]}/messages', {'model': S.MODEL_A}, ('ROUTE_NOT_ALLOWED', None, S.MODEL_A, {'path': 1})),
                (f'/v1/messages?{S.KEY}=1&{grant["token"]}&beta', {'model': S.MODEL_A},
                 ('QUERY_NOT_ALLOWED', ['beta'], S.MODEL_A, {'query_names': 2})),
                ('/v1/messages', {'model': grant['token']}, ('MODEL_NOT_ALLOWED', None, None, {'model': 1})),
                ('/v1/messages', {'model': S.KEY + ' x'}, ('MODEL_NOT_ALLOWED', None, None, {'model': 1}))):
            with self.subTest(target=target[:20], expected=expected):
                pairs = [S.auth('anthropic-messages', grant['token']), ('Content-Type', 'application/json')]
                status, _, data = S.request(RIG.inference, 'POST', target, body, pairs)
                self.assertEqual(refusal(data), expected[0])
                line = self.line_of(grant)
                self.assertEqual((line['code'], line['query_names'], line['model'], line['unrecorded']), expected)
        text = RIG.audit.path.read_text(encoding='utf-8')
        for needle in (S.KEY, grant['token'], grant['token'][len(IB.TOKEN_PREFIX):]):
            self.assertNotIn(needle, text)

    def test_without_a_grant_the_body_is_not_read_for_its_model(self):
        status, _, data = S.request(RIG.inference, 'POST', '/v1/discovery-probe-5c2e?stream=1',
                                    {'model': 'discovery-model-6b1f'}, [('Content-Type', 'application/json')])
        self.assertEqual((status, refusal(data)), (401, 'TOKEN_MISSING'))
        line = [line for line in RIG.audit_lines() if line.get('path') == '/v1/discovery-probe-5c2e'][-1]
        self.assertEqual(self.fields(line), {'method': 'POST', 'path': '/v1/discovery-probe-5c2e',
                                             'query_names': ['stream'], 'model': None, 'unrecorded': None,
                                             'code': 'TOKEN_MISSING'})
        self.assertIsNone(line['token_fingerprint'])
        self.assertNotIn('discovery-model-6b1f', RIG.audit.path.read_text(encoding='utf-8'))

    def test_the_recorded_shapes(self):
        observe = RIG.broker.observed_request
        word, many = 'a' * 32, '&'.join(f'n{i:02d}=v' for i in range(20))
        none = {'path': None, 'query_names': None, 'model': None, 'unrecorded': None}
        for (target, body), expected in (
                (('/v1/messages', None), dict(none, path='/v1/messages')),
                (('/', None), dict(none, path='/')),
                (('', None), dict(none, unrecorded={'path': 1})),
                (('/v1/' + word, None), dict(none, path='/v1/' + word)),
                (('/v1/' + word + 'a', None), dict(none, unrecorded={'path': 1})),
                (('/' + '/'.join(['s'] * 16), None), dict(none, path='/' + '/'.join(['s'] * 16))),
                (('/' + '/'.join(['s'] * 17), None), dict(none, unrecorded={'path': 1})),
                (('/v1/messages/', None), dict(none, unrecorded={'path': 1})),
                (('/v1//messages', None), dict(none, unrecorded={'path': 1})),
                (('v1/messages', None), dict(none, unrecorded={'path': 1})),
                (('http://evil.example.test/v1/messages', None), dict(none, unrecorded={'path': 1})),
                (('/v1/%41', None), dict(none, unrecorded={'path': 1})),
                (('/v1/-dash', None), dict(none, unrecorded={'path': 1})),
                (('/v1/aieh-inf-x', None), dict(none, unrecorded={'path': 1})),
                (('/v1/m?', None), dict(none, path='/v1/m')),
                (('/v1/m?a=1&&b&a', None), dict(none, path='/v1/m', query_names=['a', 'b'])),
                (('/v1/m?=x&%41=1', None), dict(none, path='/v1/m', query_names=[], unrecorded={'query_names': 2})),
                (('/v1/m?' + many, None), dict(none, path='/v1/m', query_names=[f'n{i:02d}' for i in range(16)],
                                                unrecorded={'query_names': 4})),
                (('/v1/m', b'{"model": "m-1"}'), dict(none, path='/v1/m', model='m-1')),
                (('/v1/m', b'{"model": "us.vendor.m-2:0"}'), dict(none, path='/v1/m', model='us.vendor.m-2:0')),
                (('/v1/m', json.dumps({'model': 'x' * 128}).encode()), dict(none, path='/v1/m', model='x' * 128)),
                (('/v1/m', json.dumps({'model': 'x' * 129}).encode()),
                 dict(none, path='/v1/m', unrecorded={'model': 1})),
                (('/v1/m', b'{"model": 7}'), dict(none, path='/v1/m', unrecorded={'model': 1})),
                (('/v1/m', b'{"model": null}'), dict(none, path='/v1/m', unrecorded={'model': 1})),
                (('/v1/m', b'{"model": "has space"}'), dict(none, path='/v1/m', unrecorded={'model': 1})),
                (('/v1/m', b'{"model": "aieh-inf-m"}'), dict(none, path='/v1/m', unrecorded={'model': 1})),
                (('/v1/m', b'{"other": "m-1"}'), dict(none, path='/v1/m')),
                (('/v1/m', b'["m-1"]'), dict(none, path='/v1/m')),
                (('/v1/m', b'not json'), dict(none, path='/v1/m')),
                (('/v1/m', bytes([255])), dict(none, path='/v1/m')),
                (('/v1/m', b''), dict(none, path='/v1/m'))):
            with self.subTest(target=target[:40], body=body[:40] if body else body):
                self.assertEqual(observe(target, body), expected)

    def test_anything_the_i7_scan_holds_is_counted_not_recorded(self):
        guard = IB.BrokerGuard()
        guard.hold('held-short-secret-2a7d')
        with mock.patch.object(RIG.broker, 'guard', guard):
            observed = RIG.broker.observed_request('/v1/held-short-secret-2a7d?held-short-secret-2a7d=1&beta',
                                                   b'{"model": "held-short-secret-2a7d"}')
            self.assertEqual(observed, {'path': None, 'query_names': ['beta'], 'model': None,
                                        'unrecorded': {'path': 1, 'query_names': 1, 'model': 1}})
            hex_run = 'f' * 40
            self.assertEqual(RIG.broker.observed_request('/v1/m', json.dumps({'model': hex_run}).encode())['unrecorded'],
                             {'model': 1})
        self.assertEqual(RIG.broker.observed_request('/v1/held-short-secret-2a7d', None)['path'],
                         '/v1/held-short-secret-2a7d')


if __name__ == '__main__':
    unittest.main()
