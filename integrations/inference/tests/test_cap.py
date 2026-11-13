"""The proof of plan leaf S-03.5, slice 3: the cumulative cap a broker-enforced envelope carries.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -v

The D rows of the work design's proof table (answer.md section 6.4): usage tokens (never money) counted for the
life of the governing provider-envelope receipt, as two confirmed receipts per run in the integration store (the
run receipt as the last step before the listeners serve, the close receipt at the broker's own stop), and the
envelope closed for good when the cap is reached or usage is unknown. The receipts are made by the REAL
authorization recorder against the owner suite's fake Gitea (envelope_support.py). An admitted request's outcome
is played by an in-memory upstream connection (no socket) handed to the broker's own pass-through, with an
in-memory request handler; a started broker's listeners are bound but not used. Row D2 (the cap's presence) is in
test_envelope.py (TheBlock: 'broker without a cap', 'provider with a cap'). Everything here is synthetic.
"""
from __future__ import annotations

import dataclasses
import http.client
import io
import json
import socket
import threading
import unittest

import envelope_support as V

S, IB = V.S, V.IB
CATEGORY = 'integration'
USAGE = 18                                       # the synthetic answer's total (input 11, output 7)


def capped(cap):
    return V.component(envelope=V.block(limit=V.limit(enforced_by='broker', cap=cap)))


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
    """An in-memory upstream connection. SOCK is None until the request is sent, as http.client's is until it
    connects (CONNECTED: it connects, then ENDHEADERS raises); ENDHEADERS and GETRESPONSE may raise instead;
    GATE holds the answer until the test releases it (ENTERED is set first)."""

    def __init__(self, response=None, *, endheaders=None, getresponse=None, connected=False, gate=None):
        self.response, self.raise_endheaders, self.raise_getresponse = response, endheaders, getresponse
        self.sock, self.connected, self.gate, self.entered, self.sent = None, connected, gate, threading.Event(), []

    def putrequest(self, method, target, **kwargs):
        self.sent.append((method, target))

    def putheader(self, name, value):
        self.sent.append((name, value))

    def endheaders(self, body=None):
        if self.connected:
            self.sock = object()
        if self.raise_endheaders is not None:
            raise self.raise_endheaders
        self.sock = object()
        self.sent.append(body)

    def getresponse(self):
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(30)                                 # a bound against a hang, released by the test
        if self.raise_getresponse is not None:
            self.sock = None                                   # as http.client: a failed answer closes the socket
            raise self.raise_getresponse
        return self.response

    def close(self):
        self.sock = None                                       # as http.client: the socket is gone after close


class Handler:
    """An in-memory request handler of the inference listener (what serve_inference uses of one)."""

    def __init__(self, broker, token, *, client_gone=False):
        body = json.dumps({'model': S.MODEL_A}).encode()
        self.headers = S.headers(('x-api-key', token), ('Content-Length', str(len(body))))
        self.rfile, self.wfile, self.lines = io.BytesIO(body), io.BytesIO(), []
        if client_gone:
            class Gone(io.BytesIO):
                def write(inner, data):
                    raise ConnectionResetError('the synthetic client left')
            self.wfile = Gone()
        self.server = type('Server', (), {'broker': broker})
        self.command, self.path, self.close_connection, self.body_consumed = 'POST', '/v1/messages', False, False

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


class Failing:
    """The integration store, refusing the reservation of a key that contains FRAGMENT (a lost write)."""

    def __init__(self, store, fragment):
        self._store, self._fragment = store, fragment

    def __getattr__(self, name):
        return getattr(self._store, name)

    def reserve(self, key, intent, *, actor):
        if self._fragment in key:
            raise S.STORE.StoreError('synthetic store failure')
        return self._store.reserve(key, intent, actor=actor)


class CapCase(V.EnvelopeCase):
    def rig(self, raw, *, store_factory=None):
        """A broker (not started) under RAW's governing authorization, its meter read from the ledger, whose
        journal writes into the test's store."""
        rig = V.BoundRig(raw, V.minted(raw, self.db), connect=V.refuse, db=self.db, store_factory=store_factory)
        self.addCleanup(rig.close)
        return rig

    def started(self, raw, **kw):
        rig = self.rig(raw, **kw)
        rig.start()
        token = rig.issue(family='anthropic-messages', requests=100, tokens=10 ** 6, ttl=3600)['token']
        return rig, token

    def send(self, rig, token, connection, **kw):
        """One request through the broker's own pass-through, answered by CONNECTION."""
        rig.broker._connect = lambda origin, timeout: connection
        handler = Handler(rig.broker, token, **kw)
        rig.broker.serve_inference(handler)
        return handler

    def assertRefusedWith(self, handler, status, code):
        self.assertEqual((handler.status(), handler.refusal()), (status, code))

    def ledger(self) -> dict:
        """{key: (state, intent)} of the envelope ledger's receipts in the test's store."""
        store = S.STORE.open_store(self.db)
        try:
            return {a.operation_key: (a.state, json.loads(a.intent_json)) for a in store.attempts()
                    if a.operation_key.startswith('inference/envelope/')}
        finally:
            store.close()

    def closed(self, receipt, run=1) -> dict:
        state, intent = self.ledger()[IB.ledger_keys(receipt, run)[1]]
        self.assertEqual(state, 'confirmed')
        return {k: intent[k] for k in ('usage', 'requests', 'unknown', 'in_flight')}

    def governing(self, raw, operation=V.OPERATION):
        return self.confirmed(raw, operation)['receipt']['operation_key']


class Provider(CapCase):
    def test_d1_the_provider_enforces_no_ledger_and_nothing_metered(self):
        raw = V.component()
        self.governing(raw)
        seen = {}
        code, ctx = self.serve(raw, lambda broker: seen.update(broker.status()))
        self.assertEqual(code, 0, ctx.err.getvalue())
        self.assertEqual(seen['authorization']['limit'], {'enforced_by': 'provider', 'cap': None})
        self.assertNotIn('meter', seen['authorization'])
        self.assertEqual(self.ledger(), {})


class Reached(CapCase):
    def test_d3_reached_within_a_run_then_at_the_next_start(self):
        raw = capped(USAGE)
        receipt = self.governing(raw)
        rig, token = self.started(raw)
        run_key, _ = IB.ledger_keys(receipt, 1)
        self.assertEqual(self.ledger()[run_key][0], 'confirmed')            # the run receipt, before serving
        self.assertEqual(self.send(rig, token, Connection(Response())).status(), 200)
        self.assertRefusedWith(self.send(rig, token, Connection(Response())), 429, 'ENVELOPE_CAP_REACHED')
        meter = rig.broker.status()['authorization']['meter']
        self.assertEqual((meter['usage'], meter['requests'], meter['unknown'], meter['in_flight']), (USAGE, 1, 0, 0))
        rig.close()
        self.assertEqual(self.closed(receipt), {'usage': USAGE, 'requests': 1, 'unknown': 0, 'in_flight': 0})
        self.assertStartRefused(raw, 'ENVELOPE_CAP_REACHED')

    def test_d3_a_closed_runs_usage_and_the_current_runs_reach_it(self):
        raw = capped(30)
        self.governing(raw)
        rig, token = self.started(raw)
        self.assertEqual(self.send(rig, token, Connection(Response())).status(), 200)       # 18 of 30
        rig.close()
        rig, token = self.started(raw)                                                      # carried 18, run 2
        self.assertEqual(rig.broker.status()['authorization']['limit'],
                         {'enforced_by': 'broker', 'cap': 30, 'carried': USAGE, 'run': 2})
        self.assertEqual(self.send(rig, token, Connection(Response())).status(), 200)       # 36 of 30
        self.assertRefusedWith(self.send(rig, token, Connection(Response())), 429, 'ENVELOPE_CAP_REACHED')

    def test_d8_a_new_authorization_starts_a_ledger_at_zero(self):
        raw = capped(USAGE)
        first = self.governing(raw, 'op-envelope-0001')
        rig, token = self.started(raw)
        self.send(rig, token, Connection(Response()))
        rig.close()
        self.assertStartRefused(raw, 'ENVELOPE_CAP_REACHED')
        second = self.governing(raw, 'op-envelope-0002')                                    # the same content
        held = V.minted(raw, self.db)
        self.assertEqual((held.receipt, held.carried, held.run), (second, 0, 1))
        self.assertNotEqual(IB.ledger_keys(first, 1), IB.ledger_keys(second, 1))


class Unknown(CapCase):
    CASES = {
        'a 2xx answer without usage': dict(connection=lambda: Connection(Response(chunks=[json.dumps(
            S.json_answer('anthropic-messages', with_usage=False)).encode()]))),
        'a stream the upstream cuts': dict(connection=lambda: Connection(Response(
            chunks=[b'{"id": "msg_syn", ', b'"usage": {}}'], length=False, fail_after=1))),
        # (an answer with a length is settled from the whole answer before its last bytes are written, so a client
        # that leaves then leaves a known usage: mid-stream is a streamed answer still being read)
        'a client that leaves mid-stream': dict(connection=lambda: Connection(Response(
            chunks=[b'{"id": "msg_syn", ', b'"usage": {"input_tokens": 11, "output_tokens": 7}}'], length=False)),
            client_gone=True),
        'a request written and never answered': dict(connection=lambda: Connection(
            getresponse=http.client.RemoteDisconnected('no answer'))),
        'a connection made and the request cut': dict(connection=lambda: Connection(
            endheaders=ConnectionResetError('reset while sending'), connected=True)),
    }

    def test_d4_each_unknown_outcome_closes_the_envelope(self):
        for number, (name, case) in enumerate(self.CASES.items(), 1):
            with self.subTest(name):
                raw = capped(10 ** 6)
                receipt = self.governing(raw, f'op-envelope-{number:04d}')   # a new authorization: a new ledger
                rig, token = self.started(raw)
                self.send(rig, token, case['connection'](), client_gone=case.get('client_gone', False))
                self.assertRefusedWith(self.send(rig, token, Connection(Response())), 429, 'ENVELOPE_USAGE_UNKNOWN')
                rig.close()
                self.assertEqual(self.closed(receipt), {'usage': 0, 'requests': 1, 'unknown': 1, 'in_flight': 0})
                self.assertStartRefused(raw, 'ENVELOPE_USAGE_UNKNOWN')

    def test_d4_a_broker_error_after_admission(self):
        raw = capped(10 ** 6)
        receipt = self.governing(raw)
        rig, token = self.started(raw)
        with self.assertRaises(RuntimeError):
            self.send(rig, token, Connection(getresponse=RuntimeError('a synthetic broker defect')))
        self.assertRefusedWith(self.send(rig, token, Connection(Response())), 429, 'ENVELOPE_USAGE_UNKNOWN')
        codes = [line['code'] for line in rig.audit_lines() if line.get('event') == 'request']
        self.assertEqual(codes, ['BROKER_ERROR', 'ENVELOPE_USAGE_UNKNOWN'])
        rig.close()
        self.assertEqual(self.closed(receipt)['unknown'], 1)
        self.assertStartRefused(raw, 'ENVELOPE_USAGE_UNKNOWN')


class NotUnknown(CapCase):
    def test_d5_a_refused_connect_and_a_non_2xx_answer_add_nothing(self):
        raw = capped(10 ** 6)
        receipt = self.governing(raw)
        rig, token = self.started(raw)
        refused = self.send(rig, token, Connection(endheaders=ConnectionRefusedError('refused')))
        self.assertRefusedWith(refused, 502, 'UPSTREAM_UNREACHABLE')
        error = Response(500, chunks=[b'{"error": {"message": "synthetic"}}'])
        self.assertEqual(self.send(rig, token, Connection(error)).status(), 500)
        self.assertEqual(self.send(rig, token, Connection(Response())).status(), 200)   # the next is admitted
        meter = rig.broker.status()['authorization']['meter']
        self.assertEqual((meter['usage'], meter['unknown'], meter['requests']), (USAGE, 0, 3))
        rig.close()
        self.assertEqual(self.closed(receipt), {'usage': USAGE, 'requests': 3, 'unknown': 0, 'in_flight': 0})
        self.assertEqual(V.minted(raw, self.db).carried, USAGE)              # still open

    def test_the_rule_for_each_outcome(self):
        """envelope_usage: a usage report's total; zero for nothing written or a complete answer outside 2xx (R6,
        an assumption about provider billing); unknown otherwise."""
        usage = {'input': 11, 'output': 7, 'total': USAGE}
        for args, expected in (((usage, 200, None, True), USAGE), ((usage, 500, None, True), USAGE),
                               (('unknown', None, 'UPSTREAM_UNREACHABLE', False), 0),
                               (('unknown', 500, None, True), 0),
                               (('unknown', 200, None, True), None), (('unknown', 200, 'CLIENT_GONE', True), None),
                               (('unknown', 500, 'UPSTREAM_STREAM_BROKEN', True), None),
                               (('unknown', None, 'UPSTREAM_UNREACHABLE', True), None),
                               (('unknown', None, 'BROKER_ERROR', False), None)):
            with self.subTest(args=args):
                self.assertEqual(IB.envelope_usage(*args), expected)


class Crashes(CapCase):
    def test_d6_a_run_receipt_without_its_close(self):
        """A broker that ends without its own stop (a crash): its listeners close; its stop never runs."""
        raw = capped(10 ** 6)
        receipt = self.governing(raw)
        rig = self.rig(raw)
        rig.start()
        for server in rig.broker._servers:
            server.shutdown()
        rig.broker._close_servers()
        rig.journal.close()
        rig.audit.close()
        rig.started = False
        rig.journal.close = rig.audit.close = lambda: None              # the crash closed them already
        self.assertEqual(sorted(self.ledger()), [IB.ledger_keys(receipt, 1)[0]])
        self.assertIn('no close receipt', self.assertStartRefused(raw, 'ENVELOPE_USAGE_UNKNOWN').err.getvalue())

    def test_d6_a_clean_stop_with_a_request_in_flight(self):
        raw = capped(10 ** 6)
        receipt = self.governing(raw)
        rig, token = self.started(raw)
        gate = threading.Event()
        self.addCleanup(gate.set)
        connection = Connection(Response(), gate=gate)
        rig.broker._connect = lambda origin, timeout: connection
        flight = threading.Thread(target=_quietly, args=(rig.broker.serve_inference, Handler(rig.broker, token)),
                                  daemon=True)
        flight.start()
        self.assertTrue(connection.entered.wait(30))                      # admitted, sent, awaiting its answer
        self.assertEqual(rig.broker.status()['authorization']['meter']['in_flight'], 1)
        rig.close()
        gate.set()
        flight.join(30)
        self.assertEqual(self.closed(receipt), {'usage': 0, 'requests': 1, 'unknown': 0, 'in_flight': 1})
        self.assertIn('in flight', self.assertStartRefused(raw, 'ENVELOPE_USAGE_UNKNOWN').err.getvalue())


def _quietly(call, *args):
    try:
        call(*args)
    except Exception:  # noqa: BLE001 - the stopped broker's audit is closed under the request still in flight
        pass


class OverASocket(CapCase):
    """F2 of the review: "a request written and never answered" over a real loopback socket (http.client's own
    connection, whose socket is gone once getresponse fails): the request is counted unknown, never zero."""

    def test_a_request_written_and_never_answered_over_a_real_socket(self):
        raw = capped(10 ** 6)
        receipt = self.governing(raw)
        rig, token = self.started(raw)
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        port, received = listener.getsockname()[1], []

        def take_and_drop():
            peer, _ = listener.accept()
            received.append(peer.recv(65536))                  # the request arrives; no answer is ever sent
            peer.close()
        taker = threading.Thread(target=take_and_drop, daemon=True)
        taker.start()
        made = []

        def connect(origin, timeout):
            made.append(http.client.HTTPConnection('127.0.0.1', port, timeout=10))
            return made[-1]
        rig.broker._connect = connect
        handler = Handler(rig.broker, token)
        rig.broker.serve_inference(handler)
        taker.join(30)
        self.assertTrue(received and received[0].startswith(b'POST /v1/messages'))
        self.assertIsNone(made[0].sock)                        # what the broker cannot read after the failure
        self.assertRefusedWith(handler, 502, 'UPSTREAM_UNREACHABLE')
        self.assertEqual(rig.broker.status()['authorization']['meter']['unknown'], 1)
        rig.close()
        self.assertEqual(self.closed(receipt)['unknown'], 1)


class Stopping(CapCase):
    """F1 of the review: from the broker's own stop, no request of a metered family is admitted (BROKER_STOPPING)
    before anything of it is written upstream; the close receipt's counts are the run's whole usage."""

    def test_r1_a_request_after_the_stop_is_refused_before_anything_is_sent(self):
        raw = capped(10 ** 6)
        receipt = self.governing(raw)
        rig, token = self.started(raw)
        self.assertEqual(self.send(rig, token, Connection(Response())).status(), 200)        # 18 tokens
        rig.broker.stop()
        closed = self.closed(receipt)
        self.assertEqual(closed, {'usage': USAGE, 'requests': 1, 'unknown': 0, 'in_flight': 0})
        after = Connection(Response())
        handler = Handler(rig.broker, token)
        rig.broker._connect = lambda origin, timeout: after
        _quietly(rig.broker.serve_inference, handler)         # its audit is closed: the refusal is not answered
        self.assertEqual(after.sent, [])                                  # nothing written upstream
        meter = rig.broker.meter.describe()
        self.assertEqual((meter['usage'], meter['requests'], meter['in_flight']), (USAGE, 1, 0))
        self.assertEqual(V.minted(raw, self.db).carried, USAGE)          # the next start carries the true usage

    def test_r1_the_refusal_code(self):
        raw = capped(10 ** 6)
        self.governing(raw)
        rig, token = self.started(raw)
        rig.broker.meter.stopping = True                       # the state stop() sets first, under the lock
        self.assertRefusedWith(self.send(rig, token, Connection(Response())), 503, 'BROKER_STOPPING')

    def test_r1b_a_keep_alive_request_after_the_stop_on_a_real_listener(self):
        raw = capped(10 ** 6)
        receipt = self.governing(raw)
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
        self.assertEqual(self.closed(receipt), {'usage': USAGE, 'requests': 1, 'unknown': 0, 'in_flight': 0})
        meter = rig.broker.meter.describe()
        self.assertEqual((meter['usage'], meter['requests']), (USAGE, 1))
        self.assertEqual(V.minted(raw, self.db).carried, USAGE)

    def test_the_provider_enforced_and_loopback_brokers_have_no_stopping_state(self):
        raw = V.component()
        self.governing(raw)
        rig = V.BoundRig(raw, V.minted(raw, self.db), connect=V.refuse, db=self.db)
        self.addCleanup(rig.close)
        self.assertIsNone(rig.broker.meter)


class Forged(CapCase):
    """F3 of the review: hand-written records the checks refuse on their own."""

    def test_b14_a_confirmed_run_receipt_another_actor_reserved(self):
        """A run receipt reserved by another actor beside a close the broker wrote: refused for the run's actor
        alone (the close alone would pass)."""
        raw = capped(10 ** 6)
        receipt = self.governing(raw)
        run_key, close_key = IB.ledger_keys(receipt, 1)
        store = S.STORE.open_store(self.db)
        try:
            store.reserve(run_key, {'format': IB.ENVELOPE_RUN_FORMAT, 'run': 1}, actor='someone-else')
            store.transition(run_key, 'dispatched', actor='someone-else', expected_from='reserved')
            store.transition(run_key, 'confirmed', actor='someone-else', expected_from='dispatched')
        finally:
            store.close()
        journal = IB.Journal(lambda: S.STORE.open_store(self.db), IB.BrokerGuard())
        try:
            journal.record(close_key, {'format': IB.ENVELOPE_CLOSE_FORMAT, 'service': IB.SERVICE, 'receipt': receipt,
                                       'run': 1, 'usage': 0, 'requests': 0, 'unknown': 0, 'in_flight': 0},
                           {'state': 'closed'}, conflict='JOURNAL_FAILED')
        finally:
            journal.close()
        detail = self.assertStartRefused(raw, 'ENVELOPE_USAGE_UNKNOWN').err.getvalue()
        self.assertIn('was not reserved by the broker', detail)

    def test_b3_a_hand_built_authorization_swapped_into_a_started_broker(self):
        """A copy of the held authorization (not one authorize() minted), here with an expiry already past: refused
        ENVELOPE_NOT_AUTHORIZED at admission, before its expiry is read."""
        raw = capped(10 ** 6)
        self.governing(raw)
        rig, token = self.started(raw)
        rig.broker.authorization = dataclasses.replace(rig.broker.authorization, expires=0.0)
        connection = Connection(Response())
        self.assertRefusedWith(self.send(rig, token, connection), 503, 'ENVELOPE_NOT_AUTHORIZED')
        self.assertEqual(connection.sent, [])


class LostWrites(CapCase):
    def test_d7_the_store_fails_at_the_run_receipt_and_nothing_is_served(self):
        raw = capped(10 ** 6)
        self.governing(raw)
        provider = S.MemoryProvider({IB.ENTRY: (S.PROVIDER, S.KEY)})
        ctx = self.context(raw, provider=lambda: provider, logs=lambda: self.tmp / 'logs', wait=V.refuse)
        ctx.store = lambda: Failing(S.STORE.open_store(self.db), '/run/')
        self.assertEqual(IB.main(['serve'], ctx), 1)                     # wait (serving) was never reached
        self.assertIn('JOURNAL_FAILED', ctx.err.getvalue())
        self.assertEqual(len(self.start_receipts()), 1)                   # written before the run receipt
        self.assertEqual(self.ledger(), {})

    def test_d7_the_store_fails_at_the_close_receipt(self):
        raw = capped(10 ** 6)
        receipt = self.governing(raw)
        rig, _token = self.started(raw, store_factory=lambda: Failing(S.STORE.open_store(self.db), '/close'))
        rig.broker.stop()
        self.assertIn('envelope-close-failed', [line.get('event') for line in rig.audit_lines()])
        self.assertEqual(sorted(self.ledger()), [IB.ledger_keys(receipt, 1)[0]])
        self.assertStartRefused(raw, 'ENVELOPE_USAGE_UNKNOWN')


if __name__ == '__main__':
    unittest.main()
