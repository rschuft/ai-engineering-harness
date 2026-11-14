"""The broker's stop (plan leaf S-03.2, fix-forward before the Owner's act A2; the OA-12 package section 5 item 1).

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -p test_stop.py -v

The architect measured (2026-11-13, CPython 3.12.10 on Windows) that serve's indefinite wait ignored Ctrl-C, so the
only stop was a kill. Shown here: the broker's one stop event and the wait on it in slices; the interrupt handler
(SIGINT, SIGBREAK, SIGTERM) and the forced exit of a second interrupt during the stop; the control listener's
POST /v1/stop and inference_control.py stop; BROKER_STOPPING from the stop's start; the bounded drain of requests
already admitted, a request cut by the stop audited BROKER_STOPPED and never as an upstream answer, and a stop that
does not hang on an upstream that never answers. On Windows, serve in a process of its own (serve_child.py, started
CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW; loopback only, a temporary data root, a fake upstream) is stopped by a
real CTRL_BREAK_EVENT, by inference_control.py stop, and forced by a second CTRL_BREAK_EVENT. Every wait is on the
work's own signal with a ceiling; every process and thread started is ended. Everything is synthetic.
"""
from __future__ import annotations

import http.client
import io
import json
import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

import broker_support as S

CATEGORY = 'integration'
IB = S.IB
IC = S._load('aieh_inference_control', S.HERE.parent / 'inference_control.py')
CEILING_S = 60                                       # a bound against a hang, never an expected duration
CHILD = S.HERE / 'serve_child.py'
STOP_ASKED = 'serve-child: stop asked'


def lines_of(rig) -> list:
    return rig.audit_lines()


def request_lines(rig) -> list:
    return [line for line in lines_of(rig) if line.get('event') == 'request']


class Started(unittest.TestCase):
    """A started Rig per test (closed in cleanup), over FAMILY's fake upstream when one is given."""

    def rig(self, upstreams=None, **kw):
        rig = S.Rig(S.component(upstreams or {'openai-chat': 'http://127.0.0.1:9'}), **kw).start()
        self.addCleanup(rig.close)
        return rig

    def fake(self, family='anthropic-messages'):
        upstream = S.FakeUpstream(family)
        upstream.server.handle_error = lambda request, client_address: None   # a cut stream's reset: expected
        self.addCleanup(upstream.close)
        return upstream

    def thread(self, target):
        done = threading.Thread(target=target, daemon=True)
        done.start()
        self.addCleanup(done.join, CEILING_S)
        return done

    def stop_within_ceiling(self, rig):
        """rig.broker.stop() on a thread, joined with the ceiling: the stop itself must not hang."""
        stopper = threading.Thread(target=rig.broker.stop, daemon=True)
        stopper.start()
        stopper.join(CEILING_S)
        self.assertFalse(stopper.is_alive(), 'the stop hung')


# ---------------------------------------------------------------- the stop event


class StopEvent(Started):
    def test_the_first_request_begins_the_stop_and_names_it(self):
        rig = self.rig()
        broker = rig.broker
        self.assertFalse(broker.stop_event.is_set())
        self.assertTrue(broker.request_stop('SIGINT'))
        self.assertTrue(broker.stop_event.is_set())
        self.assertTrue(broker._stopping)
        self.assertFalse(broker.request_stop('control'))           # it had begun: not recorded again
        self.assertEqual(broker.stop_by, 'SIGINT')
        self.assertFalse(broker.stop_finished.is_set())
        broker.stop()
        self.assertTrue(broker.stop_finished.is_set())
        stop = [line for line in lines_of(rig) if line['event'] == 'broker-stop']
        self.assertEqual([(line['stopped_by'], line['requests_cut']) for line in stop], [('SIGINT', 0)])

    def test_without_wake_the_stop_begins_and_serve_is_not_yet_woken(self):
        rig = self.rig()
        self.assertTrue(rig.broker.request_stop('control', wake=False))
        self.assertTrue(rig.broker._stopping)
        self.assertFalse(rig.broker.stop_event.is_set())

    def test_a_stop_without_a_request_names_itself(self):
        rig = self.rig()
        rig.broker.stop()
        rig.broker.stop()                                            # twice is harmless
        stop = [line for line in lines_of(rig) if line['event'] == 'broker-stop']
        self.assertEqual([(line['stopped_by'], line['requests_cut']) for line in stop], [('stop', 0)])

    def test_the_wait_returns_on_the_stop_event(self):
        """The real wait (_wait_for_interrupt) returns once the control listener's stop sets the event; the
        thread that asks also asks the broker directly, so that a failed call cannot leave the wait running."""
        rig = self.rig()

        def ask():
            try:
                IC.ControlClient(rig.control).stop()
            finally:
                rig.broker.request_stop('test fallback')
        self.thread(ask)
        IB._wait_for_interrupt(rig.broker)
        self.assertEqual(rig.broker.stop_by, 'control')

    def test_the_wait_polls_in_slices_and_never_waits_unbounded(self):
        """serve's wait asks the event in slices of STOP_POLL_S: the interval at which an interrupt is delivered."""
        waits = []

        class Event:
            def wait(self, timeout=None):
                waits.append(timeout)
                return len(waits) == 3

        broker = object.__new__(IB.Broker)
        broker.stop_event, broker.stop_finished, broker._after_stop = Event(), threading.Event(), []
        broker._stopping = broker._stop_done = False
        broker.request_stop = lambda by, wake=True: True
        IB._wait_for_interrupt(broker)
        self.assertEqual(waits, [IB.STOP_POLL_S] * 3)
        self.assertLessEqual(IB.STOP_POLL_S, 0.5)
        for call in broker._after_stop:
            call()


# ---------------------------------------------------------------- the interrupt handler


class Interrupts(Started):
    def bounded_wait(self, rig, pending):
        """IB.wait_for_stop on a thread joined with a ceiling, so that a loop that never begins the stop fails the
        test instead of hanging the suite (the re-review's R16)."""
        waiter = threading.Thread(target=IB.wait_for_stop, args=(rig.broker, pending), daemon=True)
        waiter.start()
        waiter.join(CEILING_S)
        if waiter.is_alive():
            rig.broker.request_stop('test: the wait loop never began the stop')     # ends the stray loop
            self.fail('wait_for_stop did not begin the stop within the ceiling')

    def handler(self, rig, exits):
        pending = IB.StopRequest()
        return pending, IB.stop_signal_handler(pending, lambda: rig.broker._stopping, lambda: rig.broker._stop_done,
                                               exit=exits.append)

    def test_each_stop_signal_of_the_platform_stops_the_wait(self):
        """A real signal, raised in this process's main thread, runs the installed handler, which records its name;
        the wait's loop then begins the stop, named by the signal; the handlers stay until the stop has finished,
        then the previous ones are restored."""
        names = [name for name in IB.STOP_SIGNALS if hasattr(signal, name)]
        self.assertIn('SIGINT', names)
        self.assertIn('SIGTERM', names)
        if sys.platform == 'win32':
            self.assertIn('SIGBREAK', names)
        for name in names:
            with self.subTest(name):
                number = getattr(signal, name)
                before = signal.getsignal(number)
                rig = self.rig()
                pending = IB.StopRequest()
                restore = IB.install_stop_signals(pending, lambda: rig.broker._stopping,
                                                  lambda: rig.broker._stop_done)
                rig.broker.after_stop(restore)
                self.addCleanup(restore)                     # once more, should a check below fail first
                self.assertIsNot(signal.getsignal(number), before)        # installed: raising it is safe
                signal.raise_signal(number)                  # its handler runs before raise_signal returns
                self.assertEqual(pending.asked, name)
                self.assertFalse(rig.broker.stop_event.is_set())          # the handler set nothing else
                self.bounded_wait(rig, pending)              # the wait's loop begins the stop
                self.assertEqual(rig.broker.stop_by, name)
                self.assertTrue(rig.broker.stop_event.is_set())
                self.assertIsNot(signal.getsignal(number), before)        # kept during the stop
                rig.broker.stop()
                self.assertEqual(signal.getsignal(number), before)        # restored once it has finished

    def test_the_handler_touches_only_its_flag(self):
        """The security review's S4: no lock and no event in the handler. A broker whose lock and event would fail if
        touched: the handler records the name and returns."""
        class Untouchable:
            def __getattr__(self, name):
                raise AssertionError(f'the handler touched {name}')
        exits = []
        pending = IB.StopRequest()
        handler = IB.stop_signal_handler(pending, lambda: False, lambda: False, exit=exits.append)
        broker = Untouchable()
        handler(signal.SIGINT, None)
        self.assertEqual((pending.asked, exits), ('SIGINT', []))
        self.assertIsInstance(broker, Untouchable)

    def test_a_second_interrupt_during_the_stop_exits_at_once_writing_nothing(self):
        rig = self.rig()
        exits = []
        pending, handler = self.handler(rig, exits)
        handler(signal.SIGINT, None)
        self.assertEqual((pending.asked, exits), ('SIGINT', []))
        written = rig.audit.lines
        handler(signal.SIGINT, None)                                     # before the loop saw the first
        self.assertEqual(exits, [IB.FORCED_EXIT])
        self.bounded_wait(rig, pending)
        self.assertEqual(rig.broker.stop_by, 'SIGINT')
        handler(signal.SIGINT, None)                                     # during the stop
        self.assertEqual(exits, [IB.FORCED_EXIT] * 2)
        self.assertNotEqual(IB.FORCED_EXIT, 0)
        self.assertEqual(rig.audit.lines, written)                       # nothing further written
        rig.broker.stop()
        handler(signal.SIGINT, None)                                     # after the stop: ignored
        self.assertEqual(exits, [IB.FORCED_EXIT] * 2)

    def test_an_interrupt_after_a_control_stop_is_the_second(self):
        rig = self.rig()
        exits = []
        _, handler = self.handler(rig, exits)
        IC.ControlClient(rig.control).stop()
        handler(signal.SIGBREAK if hasattr(signal, 'SIGBREAK') else signal.SIGINT, None)
        self.assertEqual(exits, [IB.FORCED_EXIT])
        self.assertEqual(rig.broker.stop_by, 'control')

    def test_off_the_main_thread_nothing_is_installed(self):
        before = signal.getsignal(signal.SIGINT)
        seen = []
        worker = threading.Thread(target=lambda: seen.append(IB.install_stop_signals(IB.StopRequest())))
        worker.start()
        worker.join(CEILING_S)
        self.assertEqual(len(seen), 1)
        seen[0]()
        self.assertEqual(signal.getsignal(signal.SIGINT), before)

    def test_no_deadlock_at_a_zero_slice(self):
        """The security review's S4, its probe's pattern (probe_signal_event.py): the wait at a 0 s slice, so that the
        main thread is almost always inside the stop event's wait, and SIGINT raised from another thread, many
        rounds, in a process of its own with a watchdog. Event.set() in the handler deadlocked there within a few
        rounds; the handler that sets a plain flag does not."""
        proc = subprocess.run([sys.executable, '-I', '-B', '-c', NO_DEADLOCK, str(S.HERE), '400'],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=CEILING_S * 2,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('no deadlock in 400 rounds', proc.stdout)


NO_DEADLOCK = """
import os, signal, sys, threading, time
sys.path.insert(0, sys.argv[1])
import broker_support as S
IB = S.IB
rounds, progress = int(sys.argv[2]), [0, time.monotonic()]

def watchdog():
    while True:
        time.sleep(1.0)
        if time.monotonic() - progress[1] > 10:
            print(f'DEADLOCK after {progress[0]} rounds', flush=True)
            os._exit(7)
threading.Thread(target=watchdog, daemon=True).start()
for i in range(rounds):
    broker = object.__new__(IB.Broker)
    broker._lock, broker.stop_event, broker.stop_finished = threading.RLock(), threading.Event(), threading.Event()
    broker._stopping = broker._stop_done = False
    broker.stop_by, broker._after_stop = None, []
    threading.Thread(target=lambda: (time.sleep(0.0005), signal.raise_signal(signal.SIGINT)), daemon=True).start()
    IB._wait_for_interrupt(broker, poll_s=0)
    assert broker.stop_by == 'SIGINT', broker.stop_by
    for call in broker._after_stop:
        call()
    progress[0], progress[1] = i + 1, time.monotonic()
print(f'no deadlock in {rounds} rounds', flush=True)
"""


# ---------------------------------------------------------------- the control listener's stop


class ControlStop(Started):
    def test_post_stop_answers_then_wakes_and_refuses_every_new_request(self):
        upstream = self.fake('openai-chat')
        rig = self.rig({'openai-chat': upstream.origin})
        grant = rig.issue()
        status, answer = S.control(rig, 'POST', '/v1/stop', {})
        self.assertEqual((status, answer), (202, {'format': IB.STOP_FORMAT, 'state': 'stopping', 'began': True,
                                                  'stopped_by': 'control'}))
        self.assertTrue(rig.broker.stop_event.is_set())
        status, _, data = S.request(rig.inference, 'POST', '/v1/chat/completions', {'model': S.MODEL_A},
                                    [S.auth('openai-chat', grant['token'])])
        self.assertEqual((status, json.loads(data)['aieh_refusal']['code']), (503, 'BROKER_STOPPING'))
        self.assertEqual(upstream.requests, [])
        status, answer = S.control(rig, 'POST', '/v1/stop', {})
        self.assertEqual((status, answer['began'], answer['stopped_by']), (202, False, 'control'))

    def test_the_stop_route_is_a_control_route_under_the_same_rules(self):
        rig = self.rig()
        for name, call, expected in (
                ('a body with a field', lambda: S.control(rig, 'POST', '/v1/stop', {'now': True}),
                 (400, 'CONTROL_BODY_INVALID')),
                ('not JSON', lambda: S.control(rig, 'POST', '/v1/stop', {}, content_type='text/plain'),
                 (415, 'CONTROL_CONTENT_TYPE')),
                ('no body', lambda: S.control(rig, 'POST', '/v1/stop'), (415, 'CONTROL_CONTENT_TYPE')),
                ('GET', lambda: S.control(rig, 'GET', '/v1/stop'), (404, 'CONTROL_ROUTE_UNKNOWN')),
                ('an Origin', lambda: S.control(rig, 'POST', '/v1/stop', {}, extra=[('Origin', 'http://x.test')]),
                 (403, 'CONTROL_CALLER_REFUSED'))):
            with self.subTest(name):
                status, answer = call()
                self.assertEqual((status, answer['aieh_refusal']['code']), expected)
        status, _, data = S.request(rig.control, 'POST', '/v1/stop', {}, [('Content-Type', 'application/json')],
                                    host=f'localhost:{rig.control}')
        self.assertEqual((status, json.loads(data)['aieh_refusal']['code']), (403, 'CONTROL_CALLER_REFUSED'))
        self.assertFalse(rig.broker.stop_event.is_set())
        self.assertFalse(rig.broker._stopping)
        self.assertIn('POST /v1/stop', IB.REMEDIES['CONTROL_ROUTE_UNKNOWN'])

    def test_inference_control_stop(self):
        rig = self.rig()
        out, err = io.StringIO(), io.StringIO()
        ports = {'control_port': rig.control, 'inference_port': rig.inference}
        self.assertEqual(IC.main(['stop'], IC.Context(component=lambda: ports, out=out, err=err)), 0,
                         err.getvalue())
        self.assertEqual(json.loads(out.getvalue()), {'format': IB.STOP_FORMAT, 'state': 'stopping', 'began': True,
                                                      'stopped_by': 'control'})
        self.assertEqual(err.getvalue(), '')
        self.assertTrue(rig.broker.stop_event.is_set())

    def test_inference_control_stop_refusals(self):
        holder = socket.socket()
        holder.bind(('127.0.0.1', 0))
        free = holder.getsockname()[1]
        holder.close()                                   # a port with no listener
        for name, component, code in (('no ports', {}, 'CONFIG_INCOMPLETE'),
                                      ('nobody listening', {'control_port': free, 'inference_port': free + 1
                                                            if free < 65535 else free - 1}, 'CONTROL_UNREACHABLE')):
            with self.subTest(name):
                out, err = io.StringIO(), io.StringIO()
                self.assertEqual(IC.main(['stop'], IC.Context(component=lambda c=component: c, out=out, err=err)),
                                 2)
                self.assertIn(code, err.getvalue())
                self.assertEqual(out.getvalue(), '')


# ---------------------------------------------------------------- the drain of requests already admitted


class Drain(Started):
    def gated(self, rig, upstream, grant, seen):
        """A streamed request of the gated model on its own client: SEEN gets the first bytes' arrival, then how
        the answer ended (the whole body, or the exception that ended it)."""
        def run():
            client = http.client.HTTPConnection('127.0.0.1', rig.inference, timeout=CEILING_S)
            try:
                client.request('POST', '/v1/messages', body=json.dumps({'model': 'syn-gated', 'stream': True}),
                               headers={'x-api-key': grant['token'], 'Content-Type': 'application/json'})
                answer = client.getresponse()
                seen['status'] = answer.status
                seen['first'] = answer.read1(65536)
                seen['first_read'].set()
                seen['rest'] = answer.read()
                seen['ended'] = 'complete'
            except (OSError, http.client.HTTPException) as exc:
                seen['ended'] = type(exc).__name__
            finally:
                seen['first_read'].set()
                client.close()
        return self.thread(run)

    def test_a_request_still_running_at_the_ceiling_is_cut_and_audited_as_cut(self):
        upstream = self.fake()
        rig = self.rig({'anthropic-messages': upstream.origin})
        grant = rig.issue(family='anthropic-messages', models=('syn-gated',))
        seen = {'first_read': threading.Event()}
        client = self.gated(rig, upstream, grant, seen)
        self.assertTrue(seen['first_read'].wait(CEILING_S))
        self.assertEqual(seen['status'], 200)
        rig.broker.drain_ceiling_s = 0.2                 # the gated upstream never finishes on its own
        self.stop_within_ceiling(rig)
        client.join(CEILING_S)
        self.assertFalse(client.is_alive())
        self.assertNotEqual(seen['ended'], 'complete')   # no terminating chunk: the client sees it cut
        (line,) = request_lines(rig)
        self.assertEqual((line['code'], line['status'], line['upstream_status'], line['usage']),
                         ('BROKER_STOPPED', 200, 200, 'unknown'))
        self.assertGreater(line['response_bytes'], 0)                     # the first event, sent before
        (stop,) = [line for line in lines_of(rig) if line['event'] == 'broker-stop']
        self.assertEqual((stop['requests_cut'], stop['stopped_by']), (1, 'stop'))
        summary = rig.broker._by_fingerprint[grant['token_fingerprint']].summary()
        self.assertEqual((summary['requests'], summary['in_flight']), (1, 0))

    def test_a_request_that_finishes_within_the_ceiling_is_not_cut(self):
        upstream = self.fake()
        rig = self.rig({'anthropic-messages': upstream.origin})
        grant = rig.issue(family='anthropic-messages', models=('syn-gated',))
        seen = {'first_read': threading.Event()}
        client = self.gated(rig, upstream, grant, seen)
        self.assertTrue(seen['first_read'].wait(CEILING_S))
        stopper = threading.Thread(target=rig.broker.stop, daemon=True)
        stopper.start()
        self.assertTrue(rig.broker.stop_event.wait(CEILING_S))    # the stop has begun and is draining
        upstream.release.set()                                     # the upstream finishes its answer
        stopper.join(CEILING_S)
        self.assertFalse(stopper.is_alive())
        client.join(CEILING_S)
        self.assertEqual(seen['ended'], 'complete')
        (line,) = request_lines(rig)
        self.assertEqual((line['code'], line['status'], line['upstream_status']), (None, 200, 200))
        self.assertIsInstance(line['usage'], dict)
        (stop,) = [line for line in lines_of(rig) if line['event'] == 'broker-stop']
        self.assertEqual(stop['requests_cut'], 0)

    def test_an_upstream_that_never_answers_does_not_hold_the_stop(self):
        """An upstream that accepts the connection and never answers: the stop cuts the request at its ceiling,
        and the request is audited BROKER_STOPPED with no upstream status (never as an upstream answer)."""
        silent = socket.socket()
        silent.bind(('127.0.0.1', 0))
        silent.listen(4)
        self.addCleanup(silent.close)
        accepted = []

        def accept():
            try:
                connection, _ = silent.accept()
                accepted.append(connection)               # held open, never read or answered
            except OSError:
                pass
        acceptor = self.thread(accept)
        rig = self.rig({'openai-chat': f'http://127.0.0.1:{silent.getsockname()[1]}'})
        grant = rig.issue()
        seen = {}

        def send():
            try:
                seen['answer'] = S.request(rig.inference, 'POST', '/v1/chat/completions', {'model': S.MODEL_A},
                                           [S.auth('openai-chat', grant['token'])])
            except (OSError, http.client.HTTPException) as exc:
                seen['answer'] = type(exc).__name__
        client = self.thread(send)
        acceptor.join(CEILING_S)
        self.assertEqual(len(accepted), 1)
        self.addCleanup(accepted[0].close)
        rig.broker.drain_ceiling_s = 0.2
        self.stop_within_ceiling(rig)
        client.join(CEILING_S)
        self.assertFalse(client.is_alive())
        self.assertNotIsInstance(seen['answer'], tuple)            # no answer at all: the connection was cut
        (line,) = request_lines(rig)
        self.assertEqual((line['code'], line['status'], line['upstream_status'], line['usage']),
                         ('BROKER_STOPPED', None, None, 'unknown'))

    def test_a_flight_the_stop_cut_is_not_sent_upstream(self):
        """A pass-through whose connection is made after the stop cut its flight sends nothing upstream."""
        rig = self.rig()
        grant = rig.issue()
        sent = []

        class Connection:
            def putrequest(self, *args, **kwargs):
                sent.append(args)

            def close(self):
                sent.append('closed')
        flight = IB.Flight({'event': 'request'}, 0.0)
        handler = type('H', (), {'command': 'POST', 'path': '/v1/chat/completions'})()
        body = json.dumps({'model': S.MODEL_A}).encode()
        admission = rig.broker.admit('POST', '/v1/chat/completions', S.headers(
            S.auth('openai-chat', grant['token']), ('Content-Type', 'application/json'),
            ('Content-Length', str(len(body)))), lambda n: body, flight)
        self.assertIn(id(flight), rig.broker._flights)

        def connect(origin, timeout):
            with rig.broker._lock:
                flight.cut = True                             # the stop cut it while it connected
            return Connection()
        rig.broker._connect = connect
        rig.broker._relay(handler, admission, flight)
        self.assertEqual(sent, ['closed'])
        rig.broker._settle(flight, 'unknown', 0, None, None, 'BROKER_STOPPED')     # as the stop would
        self.assertEqual(rig.broker._flights, {})


# ---------------------------------------------------------------- the independent security review's stop findings


class Silent:
    """An upstream that accepts connections and never reads or answers (held open until the test's cleanup)."""

    def __init__(self, case):
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(4)
        self.origin = f'http://127.0.0.1:{self.sock.getsockname()[1]}'
        self.accepted, self.held = threading.Event(), []
        case.addCleanup(self.close)
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        try:
            connection, _ = self.sock.accept()
        except OSError:
            return
        self.held.append(connection)
        self.accepted.set()

    def close(self):
        for connection in self.held:
            connection.close()
        self.sock.close()


class ReviewFindings(Started):
    def returning(self, rig) -> threading.Event:
        """Set once an inference handler's serve_inference has returned (its pass-through thread is done)."""
        returned, original = threading.Event(), rig.broker.serve_inference

        def serve_inference(handler):
            try:
                original(handler)
            finally:
                returned.set()
        rig.broker.serve_inference = serve_inference
        return returned

    def send(self, rig, grant, family='anthropic-messages'):
        """One request on its own thread (any answer, or the error that ended it, ignored)."""
        def run():
            try:
                S.request(rig.inference, 'POST', S.ROUTE[family], {'model': S.MODEL_A}, [S.auth(family, grant['token'])])
            except (OSError, http.client.HTTPException):
                pass
        return self.thread(run)

    def stopped_lines(self, rig) -> list:
        return [(line['code'], line['status'], line['upstream_status']) for line in request_lines(rig)]

    def test_m01_a_body_read_that_straddles_the_start_of_the_stop_is_refused(self):
        """The registration-time BROKER_STOPPING check (the review's M01): the stop begins while the body is read,
        after the first check; the request is refused and never registered or counted, so nothing is forwarded."""
        rig = self.rig()
        grant = rig.issue()
        body = json.dumps({'model': S.MODEL_A}).encode()

        def read(length):
            rig.broker.request_stop('test: during the body read')
            return body
        headers = S.headers(S.auth('openai-chat', grant['token']), ('Content-Type', 'application/json'),
                            ('Content-Length', str(len(body))))
        with self.assertRaises(IB.InferenceError) as caught:
            rig.broker.admit('POST', '/v1/chat/completions', headers, read, IB.Flight({'event': 'request'}, 0.0))
        self.assertEqual(caught.exception.code, 'BROKER_STOPPING')
        held = rig.broker._by_fingerprint[grant['token_fingerprint']]
        self.assertEqual((held.requests, held.in_flight, held.refused), (0, 0, 1))
        self.assertEqual(rig.broker._flights, {})

    def test_m25_the_stop_waits_for_a_settle_its_own_thread_claimed(self):
        """The cut wait (the review's M25): a request whose own pass-through has claimed its settlement but not yet
        written its audit line when the drain ends is not cut; the stop waits for its line (within
        STOP_CUT_CEILING_S) before it writes the broker-stop line and closes the audit."""
        upstream = self.fake('openai-chat')
        rig = self.rig({'openai-chat': upstream.origin})
        grant = rig.issue()
        rig.broker.drain_ceiling_s = 0                       # the drain's own wait ends at once
        writing, release = threading.Event(), threading.Event()
        original = rig.audit.write

        def write(record):
            if record.get('event') == 'request':
                writing.set()
                release.wait(CEILING_S)                     # the line is held until the stop waits for it
            original(record)
        rig.audit.write = write
        waiting = threading.Event()

        class Watched:
            """The broker's settle condition, telling the test when the stop waits on it."""
            def __init__(self, condition):
                self.condition = condition

            def wait(self, timeout=None):
                waiting.set()
                return self.condition.wait(timeout)

            def notify_all(self):
                self.condition.notify_all()
        rig.broker._settled = Watched(rig.broker._settled)
        client = self.send(rig, grant, 'openai-chat')
        self.assertTrue(writing.wait(CEILING_S))             # claimed by its own thread, its line held
        stopper = threading.Thread(target=rig.broker.stop, daemon=True)
        stopper.start()
        waiting.wait(IB.STOP_CUT_CEILING_S * 3)              # the stop waits for it (never, without the cut wait)
        release.set()
        stopper.join(CEILING_S)
        client.join(CEILING_S)
        self.assertFalse(stopper.is_alive())
        events = [(line['event'], line.get('code')) for line in lines_of(rig) if line['event'] != 'upstream-connect']
        self.assertEqual(events, [('broker-start', None), ('request', None), ('broker-stop', None)])
        self.assertEqual([line['requests_cut'] for line in lines_of(rig) if line['event'] == 'broker-stop'], [0])

    def test_s3_a_request_cut_while_its_connection_is_made_sends_nothing(self):
        """The review's S3 (probe_cut_connect.py): the upstream connect is held at a gate; the stop's drain ends and
        cuts the request; then the gate opens and the connection is made. Nothing is sent: the upstream receives
        no request, even after the gate opened and the pass-through ended."""
        upstream = self.fake()
        entered, gate = threading.Event(), threading.Event()
        self.addCleanup(gate.set)

        class SlowConnect(IB._UpstreamHTTPConnection):
            def connect(self):
                entered.set()
                gate.wait(CEILING_S)
                super().connect()
        rig = self.rig({'anthropic-messages': upstream.origin},
                       connect=lambda origin, timeout: SlowConnect(origin.host, origin.port, timeout=timeout))
        returned = self.returning(rig)
        grant = rig.issue(family='anthropic-messages')
        rig.broker.drain_ceiling_s = 0.2
        client = self.send(rig, grant)
        self.assertTrue(entered.wait(CEILING_S))
        self.stop_within_ceiling(rig)
        gate.set()
        self.assertTrue(returned.wait(CEILING_S))            # the pass-through has finished
        client.join(CEILING_S)
        self.assertEqual(upstream.requests, [])
        self.assertEqual(self.stopped_lines(rig), [('BROKER_STOPPED', None, None)])

    def test_n1_a_cut_request_is_claimed_before_it_is_interrupted(self):
        """The review's N1 (probe_cut_settle.py): the drain's interrupt wakes the pass-through, which tries to settle
        the request as its own failure before the drain settles it; the drain claimed it first, so it is audited
        BROKER_STOPPED and counted once."""
        silent = Silent(self)
        rig = self.rig({'anthropic-messages': silent.origin})
        grant = rig.issue(family='anthropic-messages')
        rig.broker.drain_ceiling_s = 0.2
        attempted, original_settle, stopping = threading.Event(), rig.broker._settle, threading.current_thread()

        def settle(*args):
            if threading.current_thread() is not stopping:
                attempted.set()                              # the woken pass-through's own settle
            original_settle(*args)
        rig.broker._settle = settle
        original_interrupt = IB.Flight.interrupt

        def interrupt(flight):
            original_interrupt(flight)
            attempted.wait(CEILING_S)                        # the pass-through tries first
        client = self.send(rig, grant)
        self.assertTrue(silent.accepted.wait(CEILING_S))
        with unittest.mock.patch.object(IB.Flight, 'interrupt', interrupt):
            rig.broker.stop()
        client.join(CEILING_S)
        self.assertTrue(attempted.is_set())
        self.assertEqual(self.stopped_lines(rig), [('BROKER_STOPPED', None, None)])
        held = rig.broker._by_fingerprint[grant['token_fingerprint']]
        self.assertEqual((held.requests, held.in_flight), (1, 0))

    def test_n2_a_pass_through_blocked_on_the_upstream_ends_with_the_stop(self):
        """The review's N2 (probe_cut_leak.py): on Windows a shutdown alone left the pass-through blocked until the
        upstream closed its end (its timeout is upstream_timeout_s, 600 s by default). Closing the handle ends it:
        the thread returns within the ceiling while the upstream still holds its end open."""
        silent = Silent(self)
        rig = self.rig({'anthropic-messages': silent.origin})
        returned = self.returning(rig)
        grant = rig.issue(family='anthropic-messages')
        rig.broker.drain_ceiling_s = 0.2
        client = self.send(rig, grant)
        self.assertTrue(silent.accepted.wait(CEILING_S))
        self.stop_within_ceiling(rig)
        self.assertTrue(returned.wait(10), 'the pass-through still blocked on the upstream')
        self.assertEqual(len(silent.held), 1)                 # the upstream never closed its end
        client.join(CEILING_S)
        self.assertEqual(self.stopped_lines(rig), [('BROKER_STOPPED', None, None)])

    def test_the_ceilings_fit_a_closing_console(self):
        self.assertLessEqual(IB.STOP_DRAIN_CEILING_S + IB.STOP_CUT_CEILING_S, 3.0)
        self.assertEqual(self.rig().broker.drain_ceiling_s, IB.STOP_DRAIN_CEILING_S)


# ---------------------------------------------------------------- serve in a process of its own (Windows)


BREAKER = '''
import ctypes, sys
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
pid = int(sys.argv[1])
kernel32.FreeConsole()
if not kernel32.AttachConsole(pid):
    sys.exit(10)
kernel32.SetConsoleCtrlHandler(None, True)
sys.exit(0 if kernel32.GenerateConsoleCtrlEvent(1, pid) else 11)
'''


@unittest.skipUnless(sys.platform == 'win32', 'console control events are Windows only')
class InAProcessOfItsOwn(unittest.TestCase):
    """serve_child.py: the broker's serve with its real wait, started CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
    loopback only, over a temporary directory (never the managed root). A CTRL_BREAK_EVENT reaches only the
    processes attached to the console of the process group it names; the child has a hidden console of its own, so a
    helper process (also without a window) attaches to it and generates the event (BREAKER)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-inference-stop-'))
        (self.tmp / 'logs').mkdir()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def start(self, drain_ceiling_s=0.5):
        spec = self.tmp / 'spec.json'
        spec.write_text(json.dumps({'dir': str(self.tmp), 'drain_ceiling_s': drain_ceiling_s}), encoding='utf-8')
        out = open(self.tmp / 'out.json', 'wb')
        self.addCleanup(out.close)
        env = dict(os.environ)
        env['AIEH_DATA_ROOT'] = str(self.tmp / 'data-root')     # never the managed root, even by accident
        proc = subprocess.Popen([sys.executable, '-I', '-B', str(CHILD), str(spec)], stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.PIPE, env=env,
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
        self.addCleanup(self.end, proc)
        self.err_lines: queue.Queue = queue.Queue()
        self.err_text = []

        def pump():
            for raw in iter(proc.stderr.readline, b''):
                text = raw.decode('utf-8', 'replace').rstrip('\r\n')
                self.err_text.append(text)
                self.err_lines.put(text)
            self.err_lines.put(None)
        self.pumper = threading.Thread(target=pump, daemon=True)
        self.pumper.start()
        self.addCleanup(self.pumper.join, CEILING_S)
        serving = self.until(lambda text: text.startswith('inference-broker: serving: '))
        listeners = json.loads(serving.split('serving: ', 1)[1])
        return proc, listeners['control']['port'], listeners['inference']['port']

    def end(self, proc):
        if proc.poll() is None:
            proc.kill()
        proc.wait(CEILING_S)
        proc.stderr.close()

    def until(self, match) -> str:
        """The first standard-error line of the child that MATCH accepts, within the ceiling."""
        while True:
            text = self.err_lines.get(timeout=CEILING_S)
            if text is None:
                self.fail(f'the child ended first: {self.err_text}')
            if match(text):
                return text

    def ctrl_break(self, proc):
        helper = subprocess.run([sys.executable, '-I', '-c', BREAKER, str(proc.pid)], stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=CEILING_S, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(helper.returncode, 0, helper.stderr)

    def audit(self) -> list:
        (path,) = (self.tmp / 'logs').glob('audit-*.jsonl')
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]

    def grant(self, control):
        rig = type('Ports', (), {'control': control})
        status, grant = S.control(rig, 'POST', '/v1/grants', {
            'conversation_id': S.new_id(), 'attempt_id': S.new_id(), 'family': 'anthropic-messages',
            'models': [S.MODEL_A, 'syn-gated'], 'ttl_s': 600})
        self.assertEqual(status, 201)
        return grant

    def in_flight(self, inference, grant):
        """A gated streamed request left in flight: (its thread, what it saw), once its first bytes arrived."""
        seen = {'first_read': threading.Event()}

        def run():
            client = http.client.HTTPConnection('127.0.0.1', inference, timeout=CEILING_S)
            try:
                client.request('POST', '/v1/messages', body=json.dumps({'model': 'syn-gated', 'stream': True}),
                               headers={'x-api-key': grant['token'], 'Content-Type': 'application/json'})
                answer = client.getresponse()
                answer.read1(65536)
                seen['first_read'].set()
                answer.read()
                seen['ended'] = 'complete'
            except (OSError, http.client.HTTPException) as exc:
                seen['ended'] = type(exc).__name__
            finally:
                seen['first_read'].set()
                client.close()
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        self.addCleanup(worker.join, CEILING_S)
        self.assertTrue(seen['first_read'].wait(CEILING_S))
        return worker, seen

    def test_ctrl_break_stops_serve_cleanly(self):
        proc, control, inference = self.start()
        grant = self.grant(control)
        status, _, _ = S.request(inference, 'POST', '/v1/messages', {'model': S.MODEL_A},
                                 [S.auth('anthropic-messages', grant['token'])])
        self.assertEqual(status, 200)
        worker, seen = self.in_flight(inference, grant)
        self.ctrl_break(proc)
        self.assertEqual(proc.wait(CEILING_S), 0, self.err_text)
        self.pumper.join(CEILING_S)
        worker.join(CEILING_S)
        self.assertNotEqual(seen.get('ended'), 'complete')
        lines = self.audit()
        self.assertEqual([line['event'] for line in lines], ['broker-start', 'upstream-connect', 'request',
                                                             'upstream-connect', 'request', 'broker-stop'])
        self.assertEqual([line['code'] for line in lines if line['event'] == 'request'], [None, 'BROKER_STOPPED'])
        stop = lines[-1]
        self.assertEqual((stop['stopped_by'], stop['requests_cut'], stop['live_grants_ended']),
                         ('SIGBREAK', 1, [grant['token_fingerprint']]))
        self.assertIn(STOP_ASKED, self.err_text)
        self.assertFalse(any('Traceback' in text for text in self.err_text), self.err_text)
        self.assertIn('I7 no-exposure scan: clean', self.err_text[-1])
        report = json.loads((self.tmp / 'out.json').read_text(encoding='utf-8'))
        self.assertEqual(report['format'], IB.STATUS_FORMAT)
        self.assertFalse((self.tmp / 'data-root').exists())

    def test_inference_control_stop_stops_serve(self):
        proc, control, inference = self.start()
        out, err = io.StringIO(), io.StringIO()
        ports = {'control_port': control, 'inference_port': inference}
        self.assertEqual(IC.main(['stop'], IC.Context(component=lambda: ports, out=out, err=err)), 0,
                         err.getvalue())
        self.assertEqual(json.loads(out.getvalue())['state'], 'stopping')
        self.assertEqual(proc.wait(CEILING_S), 0, self.err_text)
        lines = self.audit()
        self.assertEqual([line['event'] for line in lines], ['broker-start', 'broker-stop'])
        self.assertEqual((lines[-1]['stopped_by'], lines[-1]['requests_cut']), ('control', 0))

    def test_a_second_ctrl_break_during_the_stop_exits_at_once(self):
        proc, control, inference = self.start(drain_ceiling_s=CEILING_S * 10)   # the drain would outlast the test
        worker, _ = self.in_flight(inference, self.grant(control))
        self.ctrl_break(proc)
        self.until(lambda text: text == STOP_ASKED)              # the first began the stop; it is draining
        self.ctrl_break(proc)
        self.assertEqual(proc.wait(CEILING_S), IB.FORCED_EXIT, self.err_text)
        self.pumper.join(CEILING_S)
        # the in-flight request's connect line, then nothing further written
        self.assertEqual([line['event'] for line in self.audit()], ['broker-start', 'upstream-connect'])
        self.assertFalse(any('Traceback' in text for text in self.err_text), self.err_text)


if __name__ == '__main__':
    unittest.main()
