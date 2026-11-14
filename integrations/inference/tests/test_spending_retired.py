"""The proof of plan leaf S-03.6: the harness's spending enforcement is retired from the broker, and every control
that is not spending enforcement is kept.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -v

On the Owner's direction of 2026-11-13 (decision 0021 amendment 1; decision 0015 amendment 2): no cumulative cap,
no per-run envelope ledger (inference/envelope/...) written or read, no ENVELOPE_CAP_REACHED or
ENVELOPE_USAGE_UNKNOWN, and no request refused for a request count, a usage count or unknown usage; after an answer
without usage, a stream the upstream cut off and a client gone mid-stream the grant admits its next request; once
the broker's own stop begins a new request is refused BROKER_STOPPING (kept as part of the clean stop). The
envelope receipts are made by the REAL authorization recorder against the owner suite's fake Gitea
(envelope_support.py). An admitted request's outcome is played either by an in-memory upstream connection handed
to the broker's own pass-through (no socket), or by an in-process fake upstream on 127.0.0.1 (broker_support.py).
Everything here is synthetic. S-03.5's cap tests (test_cap.py) were removed with the cap; the ones that showed a
control that stays (the stop, a hand-built authorization) are carried over here.
"""
from __future__ import annotations

import dataclasses
import http.client
import io
import json
import unittest

import envelope_support as V

S, IB = V.S, V.IB
CATEGORY = 'integration'
USAGE = 18                                       # the synthetic answer's total (input 11, output 7)
RETIRED_RUN_FORMAT = 'aieh-inference-envelope-run/1'        # S-03.5's ledger receipts, as they may be stored
RETIRED_CLOSE_FORMAT = 'aieh-inference-envelope-close/1'


# ---------------------------------------------------------------- in-memory outcomes of one admitted request


class Response:
    def __init__(self, status=200, chunks=None, *, length=True, fail_after=None):
        self.status, self.reason = status, 'Synthetic'
        self.chunks = list(chunks if chunks is not None
                           else [json.dumps(S.json_answer('anthropic-messages')).encode()])
        self.length = sum(len(c) for c in self.chunks) if length else None
        self.fail_after, self.reads = fail_after, 0

    def getheader(self, name):
        return 'application/json' if name == 'content-type' else None

    def getheaders(self):
        return [('Content-Type', 'application/json')]

    def read1(self, size):
        if self.fail_after is not None and self.reads >= self.fail_after:
            raise http.client.IncompleteRead(b'')              # the upstream cut the stream
        self.reads += 1
        return self.chunks.pop(0) if self.chunks else b''


class Connection:
    """An in-memory upstream connection, as http.client's: ENDHEADERS and GETRESPONSE may raise instead of
    answering; SENT records what was written to it (nothing, for a request refused before the upstream)."""

    def __init__(self, response=None, *, endheaders=None, getresponse=None):
        self.response, self.raise_endheaders, self.raise_getresponse = response, endheaders, getresponse
        self.sent = []

    def putrequest(self, method, target, **kwargs):
        self.sent.append((method, target))

    def putheader(self, name, value):
        self.sent.append((name, value))

    def endheaders(self, body=None):
        if self.raise_endheaders is not None:
            raise self.raise_endheaders
        self.sent.append(body)

    def getresponse(self):
        if self.raise_getresponse is not None:
            raise self.raise_getresponse
        return self.response

    def close(self):
        pass


class Handler:
    """An in-memory request handler of the inference listener (what serve_inference uses of one); CLIENT_GONE: a
    client that leaves once the answer's headers are sent."""

    def __init__(self, broker, token, *, family='anthropic-messages', body=None, client_gone=False):
        body = json.dumps(body or {'model': S.MODEL_A}).encode()
        self.headers = S.headers(S.auth(family, token), ('Content-Length', str(len(body))))
        self.rfile, self.wfile, self.lines = io.BytesIO(body), io.BytesIO(), []
        if client_gone:
            class Gone(io.BytesIO):
                def write(inner, data):
                    raise ConnectionResetError('the synthetic client left')
            self.wfile = Gone()
        self.server = type('Server', (), {'broker': broker})
        self.command, self.path, self.close_connection, self.body_consumed = 'POST', S.ROUTE[family], False, False

    def send_response_only(self, status, message=None):
        self.lines.append(('status', status))

    def send_header(self, name, value):
        self.lines.append((name, value))

    def end_headers(self):
        pass

    def status(self):
        return next(value for name, value in self.lines if name == 'status')

    def refusal(self):
        return json.loads(self.wfile.getvalue())['aieh_refusal']['code']


class Spy:
    """The integration store, recording every key a broker or read side asks for or writes by name."""

    def __init__(self, store, asked: list):
        self._store, self._asked = store, asked

    def __getattr__(self, name):
        attribute = getattr(self._store, name)
        if not callable(attribute):
            return attribute

        def call(*args, **kwargs):
            if args and isinstance(args[0], str):
                self._asked.append(args[0])
            return attribute(*args, **kwargs)
        return call


def refused_connect(origin, timeout):
    """The broker's connector refused: no connection is made at all (connect_upstream raising)."""
    raise ConnectionRefusedError('the synthetic upstream refused the connection')


def _quietly(call, *args):
    try:
        call(*args)
    except Exception:  # noqa: BLE001 - the stopped broker's audit is closed under the request
        pass


class Case(V.EnvelopeCase):
    def rig(self, raw, **kw):
        """A broker (not started) under RAW's governing authorization, whose journal writes into the test's
        store."""
        rig = V.BoundRig(raw, V.minted(raw, self.db), connect=V.refuse, db=self.db, **kw)
        self.addCleanup(rig.close)
        return rig

    def started(self, raw, **kw):
        rig = self.rig(raw, **kw)
        rig.start()
        return rig, rig.issue(family='anthropic-messages', ttl=3600)['token']

    def send(self, rig, token, connection, *, connect=None, **kw):
        """One request through the broker's own pass-through, answered by CONNECTION (or by CONNECT, which stands
        in for the broker's connector itself)."""
        rig.broker._connect = connect or (lambda origin, timeout: connection)
        handler = Handler(rig.broker, token, **kw)
        rig.broker.serve_inference(handler)
        return handler

    def assertRefusedWith(self, handler, status, code):
        self.assertEqual((handler.status(), handler.refusal()), (status, code))

    def envelope_rows(self) -> dict:
        """{key: (state, intent, [events])} of every receipt under inference/envelope/ in the test's store."""
        store = S.STORE.open_store(self.db)
        try:
            return {a.operation_key: (a.state, a.intent_json, [(e.to_state, e.actor, e.detail_json)
                                                               for e in store.events(a.operation_key)])
                    for a in store.attempts() if a.operation_key.startswith('inference/envelope/')}
        finally:
            store.close()

    def governing(self, raw, operation=V.OPERATION):
        return self.confirmed(raw, operation)['receipt']['operation_key']

    def request_codes(self, rig) -> list:
        return [line['code'] for line in rig.audit_lines() if line.get('event') == 'request']


# ---------------------------------------------------------------- no ledger, no cap


class NoLedger(Case):
    def test_the_cap_and_its_ledger_are_gone_from_the_broker(self):
        for name in ('ledger_keys', 'read_ledger', 'envelope_usage', 'Meter', 'UNKNOWN_USAGE', 'ENVELOPE_RUN_FORMAT',
                     'ENVELOPE_CLOSE_FORMAT', 'BUDGET_LIMITS'):
            with self.subTest(name):
                self.assertFalse(hasattr(IB, name))
        for code in ('ENVELOPE_CAP_REACHED', 'ENVELOPE_USAGE_UNKNOWN', 'BUDGET_INVALID', 'BUDGET_REQUESTS_EXHAUSTED',
                     'BUDGET_TOKENS_EXHAUSTED', 'BUDGET_USAGE_UNKNOWN'):
            with self.subTest(code):
                self.assertNotIn(code, IB.CODES)
        self.assertEqual({f.name for f in dataclasses.fields(IB.Authorization)} & {'enforced_by', 'cap', 'carried',
                                                                                   'run'}, set())

    def test_a_bound_broker_writes_and_reads_no_ledger_receipt(self):
        """serve under a confirmed /2 authorization: the store is asked for no inference/envelope/ key, at start,
        while serving or at the stop; the start receipt and the status carry no limit or meter."""
        raw = V.component()
        receipt = self.governing(raw)
        asked, seen = [], {}
        provider = S.MemoryProvider({IB.ENTRY: (S.PROVIDER, S.KEY)})
        ctx = self.context(raw, provider=lambda: provider, logs=lambda: self.tmp / 'logs',
                           wait=lambda broker: seen.update(broker.status()))
        ctx.store = lambda: Spy(S.STORE.open_store(self.db), asked)
        self.assertEqual(IB.main(['serve'], ctx), 0, ctx.err.getvalue())
        self.assertTrue(asked)                                            # the spy saw the start receipt at least
        self.assertEqual([key for key in asked if key.startswith('inference/envelope/')], [])
        self.assertEqual(self.envelope_rows(), {})
        (start,) = self.start_receipts()
        for member in (start['authorization'], seen['authorization']):
            self.assertEqual(set(member), {'receipt', 'operation', 'decision', 'digest', 'expires_at', 'selection'})
            self.assertEqual(member['receipt'], receipt)

    def test_s_03_5s_ledger_receipts_are_neither_read_nor_changed(self):
        """A store that holds S-03.5's ledger under the governing receipt (a run without its close, which S-03.5
        refused ENVELOPE_USAGE_UNKNOWN, and a closed run with unknown answers): the broker starts and serves, and
        those receipts are left exactly as they were (no store data is deleted or rewritten)."""
        raw = V.component()
        receipt = self.governing(raw)
        nonce = receipt.rsplit('/', 1)[-1]
        journal = IB.Journal(lambda: S.STORE.open_store(self.db), IB.BrokerGuard())
        try:
            for run, close in ((1, None), (2, {'usage': 0, 'requests': 1, 'unknown': 1, 'in_flight': 1})):
                key = f'inference/envelope/{nonce}/run/{run}'
                journal.record(key, {'format': RETIRED_RUN_FORMAT, 'service': IB.SERVICE, 'receipt': receipt,
                                     'run': run}, {'state': 'open'}, conflict='JOURNAL_FAILED')
                if close is not None:
                    journal.record(f'{key}/close', {'format': RETIRED_CLOSE_FORMAT, 'service': IB.SERVICE,
                                                    'receipt': receipt, 'run': run, **close},
                                   {'state': 'closed'}, conflict='JOURNAL_FAILED')
        finally:
            journal.close()
        before = self.envelope_rows()
        self.assertEqual(len(before), 3)
        asked, seen = [], {}
        upstream = S.FakeUpstream('anthropic-messages')
        self.addCleanup(upstream.close)
        provider = S.MemoryProvider({IB.ENTRY: (S.PROVIDER, S.KEY)})

        def wait(broker):
            broker._connect = V.Connector({V.ORIGIN + ':443': upstream})
            token = broker.issue({'conversation_id': S.new_id(), 'attempt_id': S.new_id(),
                                  'family': 'anthropic-messages', 'models': [S.MODEL_A], 'ttl_s': 60})['token']
            seen['answer'] = S.request(broker.listeners['inference']['port'], 'POST', '/v1/messages',
                                       {'model': S.MODEL_A}, [S.auth('anthropic-messages', token)])
        ctx = self.context(raw, provider=lambda: provider, logs=lambda: self.tmp / 'logs', wait=wait)
        ctx.store = lambda: Spy(S.STORE.open_store(self.db), asked)
        self.assertEqual(IB.main(['serve'], ctx), 0, ctx.err.getvalue())
        self.assertEqual(seen['answer'][0], 200)
        self.assertEqual([key for key in asked if key.startswith('inference/envelope/')], [])
        self.assertEqual(self.envelope_rows(), before)


# ---------------------------------------------------------------- nothing is refused for usage


class NothingRefusedForUsage(Case):
    """A bound family (an upstream that is not loopback), each outcome S-03.5 counted as unknown usage or against
    the cap, then the next request of the same grant: admitted and passed through."""

    CASES = {
        'a 2xx answer without usage': dict(connection=lambda: Connection(Response(chunks=[json.dumps(
            S.json_answer('anthropic-messages', with_usage=False)).encode()])), code=None, status=200),
        'a stream the upstream cuts': dict(connection=lambda: Connection(Response(
            chunks=[b'{"id": "msg_syn", ', b'"usage": {}}'], length=False, fail_after=1)),
            code='UPSTREAM_STREAM_BROKEN', status=200),
        'a client that leaves mid-stream': dict(connection=lambda: Connection(Response(
            chunks=[b'{"id": "msg_syn", ', b'"usage": {"input_tokens": 11, "output_tokens": 7}}'], length=False)),
            client_gone=True, code='CLIENT_GONE', status=200),
        'a request written and never answered': dict(connection=lambda: Connection(
            getresponse=http.client.RemoteDisconnected('no answer')), code='UPSTREAM_UNREACHABLE', status=502),
        'a connection made and the request cut': dict(connection=lambda: Connection(
            endheaders=ConnectionResetError('reset while sending')), code='UPSTREAM_UNREACHABLE', status=502),
        'a connection made, then refused while sending': dict(connection=lambda: Connection(
            endheaders=ConnectionRefusedError('refused')), code='UPSTREAM_UNREACHABLE', status=502),
        'a refused connect': dict(connection=lambda: None, connect=refused_connect, code='UPSTREAM_UNREACHABLE',
                                  status=502),
        'an answer outside 2xx': dict(connection=lambda: Connection(Response(
            500, chunks=[b'{"error": {"message": "synthetic"}}'])), code=None, status=500),
    }

    def test_after_each_outcome_the_next_request_is_admitted(self):
        raw = V.component()
        self.governing(raw)
        for name, case in self.CASES.items():
            with self.subTest(name):
                rig, token = self.started(raw)
                first = self.send(rig, token, case['connection'](), connect=case.get('connect'),
                                  client_gone=case.get('client_gone', False))
                self.assertEqual(first.status(), case['status'])
                after = Connection(Response())
                self.assertEqual(self.send(rig, token, after).status(), 200)     # admitted, passed through
                self.assertTrue(after.sent)
                self.assertEqual(self.request_codes(rig), [case['code'], None])
                held = rig.broker._by_fingerprint[IB.contract.fingerprint(token)]
                self.assertEqual((held.requests, held.refused, held.in_flight), (2, 0, 0))
                rig.close()
        self.assertEqual(self.envelope_rows(), {})

    def test_a_broker_error_after_admission_closes_nothing(self):
        raw = V.component()
        self.governing(raw)
        rig, token = self.started(raw)
        with self.assertRaises(RuntimeError):
            self.send(rig, token, Connection(getresponse=RuntimeError('a synthetic broker defect')))
        self.assertEqual(self.send(rig, token, Connection(Response())).status(), 200)
        self.assertEqual(self.request_codes(rig), ['BROKER_ERROR', None])

    def test_any_number_of_requests_and_usage_tokens(self):
        """S-03.5's cap counted usage tokens over the bound families; nothing counts toward a cap now."""
        raw = V.component()
        self.governing(raw)
        rig, token = self.started(raw)
        for _ in range(30):
            self.assertEqual(self.send(rig, token, Connection(Response())).status(), 200)
        summary = rig.broker.grant_status(IB.contract.fingerprint(token))
        self.assertEqual((summary['requests'], summary['refused'], summary['usage']['total']), (30, 0, 30 * USAGE))
        self.assertNotIn('meter', rig.broker.status()['authorization'])


class AgainstTheFakeUpstream(unittest.TestCase):
    """The grant after a client gone mid-stream, against an in-process fake upstream (the real connector to a
    loopback origin): the answer is cut on the client's side, its usage is unknown, and the grant admits its next
    request over the wire. (An upstream-cut stream and an answer without usage over the wire are in
    test_broker_http.)"""

    def test_a_client_gone_mid_stream_then_the_next_request(self):
        upstream = S.FakeUpstream('anthropic-messages')
        self.addCleanup(upstream.close)
        # The broker closes its upstream connection when its client leaves, so the fake upstream's later writes
        # are reset: expected, and not printed.
        upstream.server.handle_error = lambda request, client_address: None
        rig = S.Rig(S.component({'anthropic-messages': upstream.origin})).start()
        self.addCleanup(rig.close)
        grant = rig.issue(family='anthropic-messages')
        handler = Handler(rig.broker, grant['token'], body={'model': S.MODEL_A, 'stream': True}, client_gone=True)
        rig.broker.serve_inference(handler)
        self.assertEqual(handler.status(), 200)
        self.assertEqual(len(upstream.requests), 1)
        status, _, data = S.request(rig.inference, 'POST', '/v1/messages', {'model': S.MODEL_A},
                                    [S.auth('anthropic-messages', grant['token'])])
        self.assertEqual((status, json.loads(data)['usage']), (200, {'input_tokens': 11, 'output_tokens': 7}))
        self.assertEqual(len(upstream.requests), 2)
        lines = [(line['status'], line['upstream_status'], line['code'], line['usage'])
                 for line in rig.audit_lines() if line.get('event') == 'request']
        self.assertEqual(lines, [(200, 200, 'CLIENT_GONE', 'unknown'),
                                 (200, 200, None, {'input': 11, 'output': 7, 'total': USAGE})])
        summary = rig.broker.grant_status(grant['token_fingerprint'])
        self.assertEqual((summary['state'], summary['requests'], summary['refused'],
                          summary['usage']['unknown_responses']), ('live', 2, 0, 1))


# ---------------------------------------------------------------- the clean stop (kept)


class Stopping(Case):
    """BROKER_STOPPING, kept as part of the clean stop (S-03.6, the engineering manager's ruling): once the broker's
    own stop begins, a new request is refused before anything of it is written upstream."""

    def test_a_request_after_the_stop_is_refused_before_anything_is_sent(self):
        raw = V.component()
        self.governing(raw)
        rig, token = self.started(raw)
        self.assertEqual(self.send(rig, token, Connection(Response())).status(), 200)
        rig.broker.stop()
        after = Connection(Response())
        handler = Handler(rig.broker, token)
        rig.broker._connect = lambda origin, timeout: after
        _quietly(rig.broker.serve_inference, handler)         # its audit is closed: the refusal is not answered
        self.assertEqual(after.sent, [])                                  # nothing written upstream
        held = rig.broker._by_fingerprint[IB.contract.fingerprint(token)]
        self.assertEqual((held.requests, held.refused), (1, 1))

    def test_the_refusal_code_for_a_bound_and_a_loopback_family(self):
        local = S.FakeUpstream('openai-chat')
        self.addCleanup(local.close)
        raw = V.component(others={'openai-chat': {'provider': None, 'upstream': local.origin,
                                                  'models': [S.MODEL_A]}})
        self.governing(raw)
        rig, token = self.started(raw)
        local_token = rig.issue(family='openai-chat')['token']
        with rig.broker._lock:
            rig.broker._stopping = True                     # the state stop() sets first, under the lock
        bound = Connection(Response())
        self.assertRefusedWith(self.send(rig, token, bound), 503, 'BROKER_STOPPING')
        handler = Handler(rig.broker, local_token, family='openai-chat')
        rig.broker._connect = IB.connect_upstream
        rig.broker.serve_inference(handler)
        self.assertRefusedWith(handler, 503, 'BROKER_STOPPING')
        self.assertEqual((bound.sent, local.requests), ([], []))
        self.assertIn('stop', IB.CODES['BROKER_STOPPING'][1])
        for word in ('envelope', 'usage', 'run'):
            self.assertNotIn(word, IB.CODES['BROKER_STOPPING'][1])

    def test_a_keep_alive_request_after_the_stop_on_a_real_listener(self):
        raw = V.component()
        self.governing(raw)
        rig, token = self.started(raw)
        upstream = []

        def connect(origin, timeout):
            upstream.append(Connection(Response()))
            return upstream[-1]
        rig.broker._connect = connect
        client = http.client.HTTPConnection('127.0.0.1', rig.inference, timeout=30)
        self.addCleanup(client.close)
        body = json.dumps({'model': S.MODEL_A})

        def post():
            client.request('POST', '/v1/messages', body=body, headers={'x-api-key': token})
            answer = client.getresponse()
            answer.read()
            return answer.status
        self.assertEqual(post(), 200)
        rig.broker.stop()
        try:
            second = post()                                    # the same connection, its handler thread still alive
        except (OSError, http.client.HTTPException) as exc:
            second = type(exc).__name__
        self.assertNotEqual(second, 200)
        self.assertEqual(len(upstream), 1)                                # the second request was never forwarded

    def test_a_broker_that_is_not_stopping_admits(self):
        """The control of the tests above: before its stop the same broker admits the request and forwards it."""
        raw = V.component()
        self.governing(raw)
        rig, token = self.started(raw)
        self.assertFalse(rig.broker._stopping)
        upstream = Connection(Response())
        self.assertEqual(self.send(rig, token, upstream).status(), 200)
        self.assertEqual(upstream.sent[0], ('POST', '/v1/messages'))       # forwarded
        self.assertEqual(self.request_codes(rig), [None])


# ---------------------------------------------------------------- the held authorization (carried over)


class Forged(Case):
    def test_a_hand_built_authorization_swapped_into_a_started_broker(self):
        """Carried over from S-03.5 (test_cap.Forged.test_b3_...): a copy of the held authorization (not one
        authorize() minted), here with an expiry already past, is refused ENVELOPE_NOT_AUTHORIZED at admission,
        before its expiry is read, and nothing is written upstream."""
        raw = V.component()
        self.governing(raw)
        rig, token = self.started(raw)
        rig.broker.authorization = dataclasses.replace(rig.broker.authorization, expires=0.0)
        connection = Connection(Response())
        self.assertRefusedWith(self.send(rig, token, connection), 503, 'ENVELOPE_NOT_AUTHORIZED')
        self.assertEqual(connection.sent, [])


if __name__ == '__main__':
    unittest.main()
