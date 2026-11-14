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
        broker.request_stop = lambda by, wake=True: True
        IB._wait_for_interrupt(broker)
        self.assertEqual(waits, [IB.STOP_POLL_S] * 3)
        self.assertLessEqual(IB.STOP_POLL_S, 0.5)
        for call in broker._after_stop:
            call()


# ---------------------------------------------------------------- the interrupt handler


class Interrupts(Started):
    def test_each_stop_signal_of_the_platform_stops_the_wait(self):
        """A real signal, raised in this process's main thread, runs the installed handler: the stop begins, named
        by the signal; the handlers stay until the stop has finished, then the previous ones are restored."""
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
                restore = IB.install_stop_signals(rig.broker.request_stop, rig.broker.stop_finished)
                rig.broker.after_stop(restore)
                self.addCleanup(restore)                     # once more, should a check below fail first
                self.assertIsNot(signal.getsignal(number), before)        # installed: raising it is safe
                signal.raise_signal(number)                  # its handler runs before raise_signal returns
                self.assertEqual(rig.broker.stop_by, name)
                self.assertTrue(rig.broker.stop_event.is_set())
                self.assertIsNot(signal.getsignal(number), before)        # kept during the stop
                rig.broker.stop()
                self.assertEqual(signal.getsignal(number), before)        # restored once it has finished

    def test_a_second_interrupt_during_the_stop_exits_at_once_writing_nothing(self):
        rig = self.rig()
        exits = []
        handler = IB.stop_signal_handler(rig.broker.request_stop, rig.broker.stop_finished, exit=exits.append)
        handler(signal.SIGINT, None)
        self.assertEqual((rig.broker.stop_by, exits), ('SIGINT', []))
        written = rig.audit.lines
        handler(signal.SIGINT, None)
        self.assertEqual(exits, [IB.FORCED_EXIT])
        self.assertNotEqual(IB.FORCED_EXIT, 0)
        self.assertEqual(rig.audit.lines, written)                       # nothing further written
        rig.broker.stop()
        handler(signal.SIGINT, None)                                     # after the stop: ignored
        self.assertEqual(exits, [IB.FORCED_EXIT])

    def test_an_interrupt_after_a_control_stop_is_the_second(self):
        rig = self.rig()
        exits = []
        handler = IB.stop_signal_handler(rig.broker.request_stop, rig.broker.stop_finished, exit=exits.append)
        IC.ControlClient(rig.control).stop()
        handler(signal.SIGBREAK if hasattr(signal, 'SIGBREAK') else signal.SIGINT, None)
        self.assertEqual(exits, [IB.FORCED_EXIT])
        self.assertEqual(rig.broker.stop_by, 'control')

    def test_off_the_main_thread_nothing_is_installed(self):
        before = signal.getsignal(signal.SIGINT)
        seen = []
        worker = threading.Thread(target=lambda: seen.append(IB.install_stop_signals(lambda by: True)))
        worker.start()
        worker.join(CEILING_S)
        self.assertEqual(len(seen), 1)
        seen[0]()
        self.assertEqual(signal.getsignal(signal.SIGINT), before)


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
