"""The broker's live census (plan leaf S-03.2, before the first provider call; the OA-12 package section 3 assumption
3 and section 5 item 5): integrations/inference/inference_census.py, and what the broker gives it.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -p test_census.py -v

Shown, on synthetic tables (every verdict branch of the decision rule): PASS with the two configured listeners,
inbound connections from loopback and an outbound connection to the configured origin's port whose remote IP the
audit recorded; FAIL for a wildcard, another-port, IPv6 or extra listener, a missing listener, a UDP endpoint, an
inbound connection from a remote address that is not loopback, an outbound connection to another port or to an
address the audit did not record, and a status whose listeners are not the configured ones; UNKNOWN when the tables
cannot be read (not Windows, the API failing, a truncated table) and for an outbound connection while the audit
cannot be read; other processes' rows ignored. The table parser over synthetic bytes of each of the four tables and
a fake iphlpapi. The broker's side: its pid in the status answer and the start receipt, and the upstream-connect
audit line written at connect time with the peer reached. The command: its record and exit codes (0 PASS, 1 FAIL
or UNKNOWN, 2 refused). On Windows, one real census: the broker in a process of its own (serve_child.py) on
ephemeral loopback ports, a fake upstream in the test process (its origin the configured one): PASS while idle and
with a request in flight (the outbound connection to the upstream and the inbound one), then FAIL once the test opens
an extra listener, an extra connection or a UDP socket in the broker's process. Everything is synthetic.
"""
from __future__ import annotations

import ctypes
import http.client
import io
import json
import os
import queue
import shutil
import socket
import struct
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
CEN = S._load('aieh_inference_census', S.HERE.parent / 'inference_census.py')
CHILD = S.HERE / 'serve_child.py'
CEILING_S = 60                                  # a bound against a hang, never an expected duration
FAMILY = 'anthropic-messages'
PID, OTHER_PID = 4242, 777
CONTROL, INFERENCE = 18431, 18432
ORIGIN = 'https://api.example.test'
ORIGIN_TEXT = IB.parse_origin(ORIGIN).text()          # the origin as the broker writes it
LOOPBACK_ORIGIN, UPSTREAM_PORT = 'http://127.0.0.1:18500', 18500
AUDIT_FILE = 'audit-20261113T120000Z-0a1b2c3d.jsonl'
PEER = '203.0.113.7'


def tcp(local, remote=('0.0.0.0', 0), state='ESTABLISHED', pid=PID, version=4):
    return CEN.Endpoint('tcp', version, state, local[0], local[1], remote[0], remote[1], pid)


def listening(address, port, pid=PID, version=4):
    return tcp((address, port), ('0.0.0.0', 0) if version == 4 else ('::', 0), 'LISTEN', pid, version)


def udp(address, port, pid=PID, version=4):
    return CEN.Endpoint('udp', version, None, address, port, None, None, pid)


BASE = [listening('127.0.0.1', CONTROL), listening('127.0.0.1', INFERENCE)]


def config(origin=ORIGIN, control=CONTROL, inference=INFERENCE):
    raw = {'control_port': control, 'inference_port': inference,
           'families': {FAMILY: {'provider': S.PROVIDER, 'upstream': origin, 'models': [S.MODEL_A]}}}
    return IB.load_config(raw, allow_ephemeral=True)


def status(pid=PID, control=CONTROL, inference=INFERENCE, audit=AUDIT_FILE):
    return {'format': IB.STATUS_FORMAT, 'pid': pid,
            'listeners': {'control': {'address': '127.0.0.1', 'port': control},
                          'inference': {'address': '127.0.0.1', 'port': inference}},
            'audit': {'file': audit, 'lines': 3, 'withheld': 0}}


def connect_line(origin=ORIGIN_TEXT, address=PEER, port=443):
    return json.dumps({'format': IB.AUDIT_FORMAT, 'event': 'upstream-connect', 'origin': origin,
                       'peer': {'address': address, 'port': port}, 'local': {'address': '10.0.0.2', 'port': 50001},
                       'family': FAMILY, 'attempt_id': S.new_id()})


def run(rows, *, cfg=None, answer=None, audit=(), tables_error=None):
    def tables():
        if tables_error is not None:
            raise CEN.TablesUnavailable(tables_error)
        return list(rows)

    def read_audit(name):
        if isinstance(audit, BaseException):
            raise audit
        return list(audit)
    return CEN.census(cfg or config(), answer or status(), read_tables=tables, read_audit=read_audit)


class TheRule(unittest.TestCase):
    def assertVerdict(self, record, verdict, *needles):
        self.assertEqual(record['verdict'], verdict, record['violations'] + record['unknown'])
        text = json.dumps(record['violations'] + record['unknown'])
        for needle in needles:
            self.assertIn(needle, text)
        self.assertEqual(record['rule'], CEN.CENSUS_RULE)
        self.assertEqual(record['dns'], CEN.DNS_NOTE)
        self.assertIn('not observed', record['dns'])
        return record

    def test_pass_listeners_inbound_from_loopback_and_a_recorded_outbound(self):
        rows = BASE + [tcp(('127.0.0.1', INFERENCE), ('127.0.0.1', 50100)),
                       tcp(('127.0.0.1', CONTROL), ('127.0.0.1', 50101), 'CLOSE_WAIT'),
                       tcp(('10.0.0.2', 50001), (PEER, 443)),
                       tcp(('10.0.0.2', 50002), (PEER, 443), 'TIME_WAIT', pid=0),     # another pid: ignored
                       listening('0.0.0.0', 445, pid=OTHER_PID), udp('0.0.0.0', 53, pid=OTHER_PID)]
        record = self.assertVerdict(run(rows, audit=[connect_line(), 'not json', '{"event": "request"}']), 'PASS')
        self.assertEqual([e['kind'] for e in record['endpoints']], ['listener', 'listener', 'inbound', 'inbound',
                                                                    'outbound'])
        self.assertTrue(all(e['ok'] for e in record['endpoints']))
        self.assertEqual(record['audit'], {'readable': True, 'file': AUDIT_FILE, 'upstream_connect_lines': 1,
                                           'peers': {ORIGIN_TEXT: [PEER]}})
        self.assertEqual(record['expected'], {'listeners': [f'127.0.0.1:{CONTROL}', f'127.0.0.1:{INFERENCE}'],
                                              'origins': {ORIGIN_TEXT: 443}})
        self.assertEqual((record['format'], record['broker']['pid'], record['tables']),
                         ('aieh-inference-census/1', PID, {'readable': True, 'rows': len(rows)}))

    def test_pass_with_only_the_two_listeners(self):
        self.assertVerdict(run(BASE), 'PASS')

    def test_fail_for_each_listener_that_is_not_exactly_configured(self):
        cases = {
            'a wildcard address': listening('0.0.0.0', INFERENCE),
            'another port': listening('127.0.0.1', 18433),
            'another loopback address': listening('127.0.0.2', CONTROL),
            'an IPv6 loopback listener': listening('::1', INFERENCE, version=6),
            'an IPv6 wildcard listener': listening('::', CONTROL, version=6),
        }
        for name, extra in cases.items():
            with self.subTest(name):
                self.assertVerdict(run(BASE + [extra]), 'FAIL', 'a listener that is not configured')
        self.assertVerdict(run([listening('0.0.0.0', CONTROL), listening('127.0.0.1', INFERENCE)]), 'FAIL',
                           'a listener that is not configured', 'a configured listener is missing: 127.0.0.1:'
                           f'{CONTROL}')

    def test_fail_for_a_missing_listener(self):
        self.assertVerdict(run(BASE[:1]), 'FAIL', f'a configured listener is missing: 127.0.0.1:{INFERENCE}')
        self.assertVerdict(run([]), 'FAIL', 'a configured listener is missing')

    def test_fail_for_any_udp_endpoint(self):
        for row in (udp('127.0.0.1', 50200), udp('0.0.0.0', 5353), udp('::1', 50201, version=6)):
            with self.subTest(row.local_address):
                self.assertVerdict(run(BASE + [row]), 'FAIL', 'a UDP endpoint')

    def test_fail_for_an_inbound_connection_from_a_remote_address_that_is_not_loopback(self):
        self.assertVerdict(run(BASE + [tcp(('127.0.0.1', INFERENCE), ('192.168.1.20', 50100))]), 'FAIL',
                           'not loopback')

    def test_fail_for_an_outbound_connection_to_another_port_or_an_unrecorded_address(self):
        audit = [connect_line()]
        self.assertVerdict(run(BASE + [tcp(('10.0.0.2', 50001), (PEER, 80))], audit=audit), 'FAIL',
                           'no configured origin\'s port')
        self.assertVerdict(run(BASE + [tcp(('10.0.0.2', 50001), ('198.51.100.9', 443))], audit=audit), 'FAIL',
                           'did not record')
        self.assertVerdict(run(BASE + [tcp(('10.0.0.2', 50001), (PEER, 443))], audit=[]), 'FAIL', 'did not record')
        # a peer recorded for another origin does not count for this one
        other = [connect_line(origin='https://other.example.test')]
        self.assertVerdict(run(BASE + [tcp(('10.0.0.2', 50001), (PEER, 443))], audit=other), 'FAIL',
                           'did not record')
        # a loopback connection from a port other than the listeners' is outbound, not inbound
        self.assertVerdict(run(BASE + [tcp(('127.0.0.1', 50300), ('127.0.0.1', 50301))]), 'FAIL',
                           'no configured origin\'s port')

    def test_a_loopback_origin_s_connection_is_judged_by_its_recorded_peer(self):
        cfg = config(origin=LOOPBACK_ORIGIN)
        rows = BASE + [tcp(('127.0.0.1', 50400), ('127.0.0.1', UPSTREAM_PORT))]
        self.assertVerdict(run(rows, cfg=cfg, audit=[connect_line(LOOPBACK_ORIGIN, '127.0.0.1', UPSTREAM_PORT)]),
                           'PASS')
        self.assertVerdict(run(rows, cfg=cfg, audit=[]), 'FAIL', 'did not record')

    def test_ipv6_and_mapped_peers_are_compared_canonically(self):
        rows = BASE + [tcp(('2001:db8::2', 50001), ('2001:db8::7', 443), version=6)]
        self.assertVerdict(run(rows, audit=[connect_line(address='2001:0db8:0:0::7')]), 'PASS')
        self.assertVerdict(run(BASE + [tcp(('10.0.0.2', 50001), (PEER, 443))],
                               audit=[connect_line(address='::ffff:' + PEER)]), 'PASS')

    def test_fail_when_the_status_names_listeners_other_than_the_configured(self):
        self.assertVerdict(run(BASE, answer=status(control=18440)), 'FAIL', 'the broker\'s status names the control '
                                                                            'listener on port 18440')

    def test_unknown_when_the_tables_cannot_be_read(self):
        record = self.assertVerdict(run(BASE, tables_error='synthetic'), 'UNKNOWN', 'could not be read')
        self.assertEqual(record['tables'], {'readable': False, 'reason': 'synthetic'})
        self.assertIsNone(record['endpoints'])
        # and a FAIL already shown by the status is not hidden by it
        self.assertVerdict(run(BASE, answer=status(inference=18440), tables_error='synthetic'), 'FAIL')

    def test_unknown_for_an_outbound_connection_while_the_audit_cannot_be_read(self):
        rows = BASE + [tcp(('10.0.0.2', 50001), (PEER, 443))]
        record = self.assertVerdict(run(rows, audit=OSError('gone')), 'UNKNOWN', 'the audit cannot be read')
        self.assertEqual(record['audit'], {'readable': False, 'file': AUDIT_FILE, 'reason': 'OSError'})
        self.assertVerdict(run(BASE, audit=OSError('gone')), 'PASS')                 # nothing depends on it
        self.assertVerdict(run(rows + [udp('127.0.0.1', 1)], audit=OSError('gone')), 'FAIL', 'a UDP endpoint')

    def test_other_processes_rows_are_ignored(self):
        others = [listening('0.0.0.0', 80, pid=OTHER_PID), tcp(('10.0.0.2', 1), ('8.8.8.8', 53), pid=OTHER_PID),
                  udp('0.0.0.0', 53, pid=OTHER_PID)]
        self.assertVerdict(run(BASE + others), 'PASS')

    def test_a_status_without_pid_listeners_or_audit_is_refused(self):
        bad = {'no pid': dict(status(), pid=None), 'a boolean pid': dict(status(), pid=True),
               'no listeners': dict(status(), listeners={}),
               'a wildcard listener': dict(status(), listeners={'control': {'address': '0.0.0.0', 'port': CONTROL},
                                                                'inference': status()['listeners']['inference']}),
               'no audit': dict(status(), audit=None),
               'an audit path': dict(status(), audit={'file': '../' + AUDIT_FILE})}
        for name, answer in bad.items():
            with self.subTest(name):
                with self.assertRaises(CEN.CensusRefused) as caught:
                    run(BASE, answer=answer)
                self.assertEqual(caught.exception.code, 'CENSUS_STATUS_INVALID')


def table_bytes(protocol, version, rows) -> bytes:
    """Synthetic table bytes of the Windows layouts (a DWORD count, then the rows)."""
    out = struct.pack('<I', len(rows))
    for row in rows:
        ip = socket.inet_aton if version == 4 else (lambda a: socket.inet_pton(socket.AF_INET6, a))
        port = struct.pack('>H', row['local_port']) + b'\0\0'
        if (protocol, version) == ('tcp', 4):
            out += (struct.pack('<I', row['state']) + ip(row['local']) + port + ip(row['remote'])
                    + struct.pack('>H', row['remote_port']) + b'\0\0' + struct.pack('<I', row['pid']))
        elif (protocol, version) == ('tcp', 6):
            out += (ip(row['local']) + b'\0' * 4 + port + ip(row['remote']) + b'\0' * 4
                    + struct.pack('>H', row['remote_port']) + b'\0\0' + struct.pack('<II', row['state'], row['pid']))
        elif (protocol, version) == ('udp', 4):
            out += ip(row['local']) + port + struct.pack('<I', row['pid'])
        else:
            out += ip(row['local']) + b'\0' * 4 + port + struct.pack('<I', row['pid'])
    return out


TABLES = {
    ('tcp', 4): [{'state': 2, 'local': '127.0.0.1', 'local_port': CONTROL, 'remote': '0.0.0.0', 'remote_port': 0,
                  'pid': PID},
                 {'state': 5, 'local': '10.0.0.2', 'local_port': 50001, 'remote': PEER, 'remote_port': 443,
                  'pid': PID}],
    ('tcp', 6): [{'state': 2, 'local': '::1', 'local_port': 8080, 'remote': '::', 'remote_port': 0, 'pid': 9}],
    ('udp', 4): [{'local': '0.0.0.0', 'local_port': 5353, 'pid': 10}],
    ('udp', 6): [{'local': 'fe80::1', 'local_port': 546, 'pid': 11}],
}


class TheTables(unittest.TestCase):
    def test_each_table_layout_is_parsed(self):
        rows = {key: CEN.parse_table(*key, table_bytes(*key, value)) for key, value in TABLES.items()}
        self.assertEqual(rows[('tcp', 4)], [
            CEN.Endpoint('tcp', 4, 'LISTEN', '127.0.0.1', CONTROL, '0.0.0.0', 0, PID),
            CEN.Endpoint('tcp', 4, 'ESTABLISHED', '10.0.0.2', 50001, PEER, 443, PID)])
        self.assertEqual(rows[('tcp', 6)], [CEN.Endpoint('tcp', 6, 'LISTEN', '::1', 8080, '::', 0, 9)])
        self.assertEqual(rows[('udp', 4)], [CEN.Endpoint('udp', 4, None, '0.0.0.0', 5353, None, None, 10)])
        self.assertEqual(rows[('udp', 6)], [CEN.Endpoint('udp', 6, None, 'fe80::1', 546, None, None, 11)])
        self.assertEqual({k: v for k, v in CEN.ROW_SIZES.items()},
                         {k: (len(table_bytes(*k, v)) - 4) // len(v) for k, v in TABLES.items()})

    def test_a_truncated_table_is_unreadable(self):
        data = table_bytes('tcp', 4, TABLES[('tcp', 4)])
        for cut in (data[:2], data[:-1], struct.pack('<I', 3) + data[4:]):
            with self.subTest(len(cut)):
                with self.assertRaises(CEN.TablesUnavailable):
                    CEN.parse_table('tcp', 4, cut)

    def test_another_platform_is_unreadable(self):
        for platform in ('linux', 'darwin'):
            with self.subTest(platform):
                with self.assertRaises(CEN.TablesUnavailable) as caught:
                    CEN.read_tables(platform)
                self.assertIn('Windows only', str(caught.exception))

    @unittest.skipUnless(sys.platform == 'win32', 'the per-process tables are read on Windows only')
    def test_the_api_read_through_a_fake_iphlpapi(self):
        tables = {('tcp', CEN.AF_INET): table_bytes('tcp', 4, TABLES[('tcp', 4)]),
                  ('tcp', CEN.AF_INET6): table_bytes('tcp', 6, TABLES[('tcp', 6)]),
                  ('udp', CEN.AF_INET): table_bytes('udp', 4, TABLES[('udp', 4)]),
                  ('udp', CEN.AF_INET6): table_bytes('udp', 6, TABLES[('udp', 6)])}
        calls = []

        def function(protocol, error=None):
            def call(buffer, size_ref, order, family, table_class, reserved):
                calls.append((protocol, family, table_class, buffer is None))
                if error is not None:
                    return error
                data, size = tables[(protocol, family)], size_ref._obj
                if buffer is None or size.value < len(data):
                    size.value = len(data)
                    return CEN.ERROR_INSUFFICIENT_BUFFER
                ctypes.memmove(buffer, data, len(data))
                return CEN.NO_ERROR
            return call

        def library(error=None):
            return lambda: _Lib(function('tcp', error), function('udp', error))
        rows = CEN.read_tables('win32', library())
        self.assertEqual(len(rows), 5)
        self.assertEqual({(p, f, c) for p, f, c, _ in calls},
                         {('tcp', 2, 5), ('tcp', 23, 5), ('udp', 2, 1), ('udp', 23, 1)})
        with self.assertRaises(CEN.TablesUnavailable) as caught:
            CEN.read_tables('win32', library(error=87))
        self.assertIn('error 87', str(caught.exception))
        record = CEN.census(config(), status(), read_tables=lambda: CEN.read_tables('win32', library(error=87)),
                            read_audit=lambda name: [])
        self.assertEqual(record['verdict'], 'UNKNOWN')

    @unittest.skipUnless(sys.platform == 'win32', 'the per-process tables are read on Windows only')
    def test_the_real_tables_hold_this_process_s_listener(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(('127.0.0.1', 0))
        server.listen(1)
        mine = [e for e in CEN.read_tables() if e.pid == os.getpid() and e.state == 'LISTEN']
        self.assertIn(('127.0.0.1', server.getsockname()[1]), [(e.local_address, e.local_port) for e in mine])


class _Lib:
    def __init__(self, tcp_function, udp_function):
        self.GetExtendedTcpTable, self.GetExtendedUdpTable = tcp_function, udp_function


class TheBrokerSide(unittest.TestCase):
    def test_the_status_and_the_start_receipt_name_the_pid(self):
        rig = S.Rig(S.component({FAMILY: 'http://127.0.0.1:9'})).start()
        self.addCleanup(rig.close)
        self.assertEqual(rig.broker.status()['pid'], os.getpid())
        record, _ = rig.store_records(rig.broker.start_receipt['operation_key'])
        self.assertEqual(json.loads(record.intent_json)['pid'], os.getpid())

    def test_each_upstream_connection_is_recorded_at_connect_time_with_its_peer(self):
        upstream = S.FakeUpstream(FAMILY)
        self.addCleanup(upstream.close)
        seen = []
        rig = S.Rig(S.component({FAMILY: upstream.origin}),
                    connect=lambda origin, timeout: hooked(IB.connect_upstream(origin, timeout), seen, rig,
                                                           upstream))
        rig.start()
        self.addCleanup(rig.close)
        grant = rig.issue(family=FAMILY)
        for _ in range(2):
            status, _, _ = S.request(rig.inference, 'POST', '/v1/messages', {'model': S.MODEL_A},
                                     [S.auth(FAMILY, grant['token'])])
            self.assertEqual(status, 200)
        lines = rig.audit_lines()
        connects = [line for line in lines if line.get('event') == 'upstream-connect']
        self.assertEqual(len(connects), 2)
        for line in connects:
            self.assertEqual({k: line[k] for k in ('origin', 'family', 'attempt_id', 'peer')},
                             {'origin': upstream.origin, 'family': FAMILY, 'attempt_id': grant['attempt_id'],
                              'peer': {'address': '127.0.0.1', 'port': upstream.port}})
            self.assertEqual(line['local']['address'], '127.0.0.1')
            self.assertNotIn('token_fingerprint', line)
        # written at connect time: once each connection is made, before a byte of its request reached the upstream
        self.assertEqual(seen, [(1, 0), (2, 1)])
        events = [line['event'] for line in lines if line.get('event') in ('upstream-connect', 'request')]
        self.assertEqual(events, ['upstream-connect', 'request'] * 2)
        self.assertEqual(CEN.audit_peers([json.dumps(line) for line in lines]),
                         ({upstream.origin: ['127.0.0.1']}, 2))
        text = rig.audit.path.read_text(encoding='utf-8')
        for secret in (S.KEY, grant['token']):
            self.assertNotIn(secret, text)

    def test_a_refused_request_opens_no_connection_and_writes_no_connect_line(self):
        rig = S.Rig(S.component({FAMILY: 'http://127.0.0.1:9'})).start()
        self.addCleanup(rig.close)
        grant = rig.issue(family=FAMILY)
        status, _, _ = S.request(rig.inference, 'POST', '/v1/messages', {'model': S.MODEL_C},
                                 [S.auth(FAMILY, grant['token'])])
        self.assertEqual(status, 403)
        self.assertEqual([line for line in rig.audit_lines() if line.get('event') == 'upstream-connect'], [])


def hooked(connection, seen, rig, upstream):
    """CONNECTION, its connect observed: just after it (http.client connects at the first request), SEEN gets (the
    upstream-connect lines written, the requests the upstream has received)."""
    real = connection.connect

    def connect():
        real()
        seen.append((len([line for line in rig.audit_lines() if line.get('event') == 'upstream-connect']),
                     len(upstream.requests)))
    connection.connect = connect
    return connection


class TheCommand(unittest.TestCase):
    def context(self, *, component=None, answer=None, rows=BASE, audit=(), status_error=None):
        tmp = Path(tempfile.mkdtemp(prefix='aieh-inference-census-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / AUDIT_FILE).write_text('\n'.join(audit) + '\n', encoding='utf-8')
        asked = []

        def ask(port):
            asked.append(port)
            if status_error is not None:
                raise status_error
            return answer or status()
        raw = component if component is not None else {
            'control_port': CONTROL, 'inference_port': INFERENCE,
            'families': {FAMILY: {'provider': S.PROVIDER, 'upstream': ORIGIN, 'models': [S.MODEL_A]}}}
        ctx = CEN.Context(component=lambda: raw, status=ask, logs=lambda: tmp, tables=lambda: list(rows),
                          out=io.StringIO(), err=io.StringIO())
        ctx.asked = asked
        return ctx

    def test_pass_exits_0_and_prints_the_record(self):
        ctx = self.context(rows=BASE + [tcp(('10.0.0.2', 50001), (PEER, 443))], audit=[connect_line()])
        self.assertEqual(CEN.main(['--once'], ctx), 0, ctx.err.getvalue())
        record = json.loads(ctx.out.getvalue())
        self.assertEqual((record['verdict'], record['rule'], ctx.asked), ('PASS', CEN.CENSUS_RULE, [CONTROL]))
        self.assertEqual(record['audit']['peers'], {ORIGIN_TEXT: [PEER]})
        self.assertIn('inference-census: PASS', ctx.err.getvalue())

    def test_fail_and_unknown_exit_1(self):
        ctx = self.context(rows=BASE + [udp('127.0.0.1', 1)])
        self.assertEqual(CEN.main(['--once'], ctx), 1)
        self.assertEqual(json.loads(ctx.out.getvalue())['verdict'], 'FAIL')

        ctx = self.context()
        ctx.tables = lambda: CEN.read_tables('linux')
        self.assertEqual(CEN.main(['--once'], ctx), 1)
        self.assertEqual(json.loads(ctx.out.getvalue())['verdict'], 'UNKNOWN')

    def test_refusals_exit_2_before_anything_is_observed(self):
        def never():
            raise AssertionError('the tables were read')
        cases = {
            'CENSUS_CONFIG_INVALID': dict(component={'control_port': 'x'}),
            'CENSUS_BROKER_UNREACHABLE': dict(status_error=IC.ControlError('CONTROL_UNREACHABLE', 'synthetic')),
            'CENSUS_STATUS_INVALID': dict(answer=dict(status(), pid=0)),
        }
        for code, case in cases.items():
            with self.subTest(code):
                ctx = self.context(**case)
                ctx.tables = never
                self.assertEqual(CEN.main(['--once'], ctx), 2)
                self.assertIn(code, ctx.err.getvalue())
                self.assertEqual(ctx.out.getvalue(), '')
        ctx = self.context(component={})                 # no port configured
        self.assertEqual(CEN.main(['--once'], ctx), 2)
        self.assertIn('CENSUS_CONFIG_INVALID', ctx.err.getvalue())

    def test_once_is_required(self):
        with self.assertRaises(SystemExit):
            with unittest.mock.patch('sys.stderr', io.StringIO()):
                CEN.main([], self.context())

    def test_an_audit_name_outside_its_shape_is_never_read(self):
        ctx = self.context(answer=dict(status(), audit={'file': 'audit-x.jsonl'}))
        self.assertEqual(CEN.main(['--once'], ctx), 2)
        self.assertIn('CENSUS_STATUS_INVALID', ctx.err.getvalue())



@unittest.skipUnless(sys.platform == 'win32', 'the per-process tables are read on Windows only')
class TheRealCensus(unittest.TestCase):
    """The broker's serve in a process of its own (serve_child.py, CREATE_NO_WINDOW, loopback only, a temporary
    directory, never the managed root), its upstream a fake upstream in this test process: its origin is the
    configured origin. The census reads the real tables."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-inference-census-'))
        (self.tmp / 'logs').mkdir()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.upstream = S.FakeUpstream(FAMILY)
        self.addCleanup(self.upstream.close)
        spec = self.tmp / 'spec.json'
        spec.write_text(json.dumps({'dir': str(self.tmp), 'drain_ceiling_s': 0.5, 'upstream': self.upstream.origin,
                                    'sockets': True}), encoding='utf-8')
        out = open(self.tmp / 'out.json', 'wb')
        self.addCleanup(out.close)
        env = dict(os.environ)
        env['AIEH_DATA_ROOT'] = str(self.tmp / 'data-root')     # never the managed root, even by accident
        self.proc = subprocess.Popen([sys.executable, '-I', '-B', str(CHILD), str(spec)], stdin=subprocess.PIPE,
                                     stdout=out, stderr=subprocess.PIPE, env=env,
                                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
        self.addCleanup(self.end)
        self.lines: queue.Queue = queue.Queue()
        self.err_text = []

        def pump():
            for raw in iter(self.proc.stderr.readline, b''):
                text = raw.decode('utf-8', 'replace').rstrip('\r\n')
                self.err_text.append(text)
                self.lines.put(text)
            self.lines.put(None)
        self.pumper = threading.Thread(target=pump, daemon=True)
        self.pumper.start()
        serving = self.until(lambda text: text.startswith('inference-broker: serving: '))
        ports = json.loads(serving.split('serving: ', 1)[1])
        self.control, self.inference = ports['control']['port'], ports['inference']['port']

    def end(self):
        if self.proc.poll() is None:
            try:
                IC.ControlClient(self.control).stop()
                self.proc.wait(CEILING_S)
            except (IC.ControlError, subprocess.TimeoutExpired, AttributeError):
                self.proc.kill()
                self.proc.wait(CEILING_S)
        self.proc.stdin.close()
        self.pumper.join(CEILING_S)
        self.proc.stderr.close()

    def until(self, match) -> str:
        while True:
            text = self.lines.get(timeout=CEILING_S)
            if text is None:
                self.fail(f'the child ended first: {self.err_text}')
            if match(text):
                return text

    def command(self, text) -> int:
        self.proc.stdin.write(text.encode('ascii') + b'\n')
        self.proc.stdin.flush()
        word = text.split()[0]
        return int(self.until(lambda line: line.startswith(f'serve-child: {word} ')).rsplit(' ', 1)[1])

    def census(self) -> tuple[int, dict]:
        ctx = CEN.Context(component=lambda: S.component({FAMILY: self.upstream.origin}),
                          status=lambda port: IC.ControlClient(self.control).status(), logs=lambda: self.tmp / 'logs',
                          tables=CEN.read_tables, out=io.StringIO(), err=io.StringIO(), allow_ephemeral=True)
        code = CEN.main(['--once'], ctx)
        self.assertNotEqual(code, 2, ctx.err.getvalue())
        return code, json.loads(ctx.out.getvalue())

    def in_flight(self):
        """A gated streamed request held in flight: the broker holds the inbound connection and the outbound one to
        the upstream until the test releases it."""
        status, grant = S.control(type('Ports', (), {'control': self.control}), 'POST', '/v1/grants', {
            'conversation_id': S.new_id(), 'attempt_id': S.new_id(), 'family': FAMILY,
            'models': [S.MODEL_A, 'syn-gated'], 'ttl_s': 600})
        self.assertEqual(status, 201)
        seen = {'first_read': threading.Event()}

        def run():
            client = http.client.HTTPConnection('127.0.0.1', self.inference, timeout=CEILING_S)
            try:
                client.request('POST', '/v1/messages', body=json.dumps({'model': 'syn-gated', 'stream': True}),
                               headers={'x-api-key': grant['token']})
                answer = client.getresponse()
                answer.read1(65536)
                seen['first_read'].set()
                answer.read()
            except (OSError, http.client.HTTPException):
                pass
            finally:
                seen['first_read'].set()
                client.close()
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        self.addCleanup(worker.join, CEILING_S)
        self.addCleanup(self.upstream.release.set)
        self.assertTrue(seen['first_read'].wait(CEILING_S))
        return worker

    def test_pass_then_fail_on_an_extra_listener_connection_or_udp_socket(self):
        code, record = self.census()
        self.assertEqual((code, record['verdict']), (0, 'PASS'), record['violations'] + record['unknown'])
        self.assertNotEqual(record['broker']['pid'], os.getpid())   # the child's (a venv launcher's own child)
        self.assertEqual(sorted(e['local'] for e in record['endpoints'] if e['kind'] == 'listener'),
                         sorted([f'127.0.0.1:{self.control}', f'127.0.0.1:{self.inference}']))

        worker = self.in_flight()
        code, record = self.census()
        self.assertEqual((code, record['verdict']), (0, 'PASS'), record['violations'] + record['unknown'])
        outbound = [e for e in record['endpoints'] if e['kind'] == 'outbound']
        self.assertIn(f'127.0.0.1:{self.upstream.port}', [e['remote'] for e in outbound])
        self.assertTrue(all(e['ok'] for e in outbound))
        self.assertIn(f'127.0.0.1:{self.inference}', [e['local'] for e in record['endpoints']
                                                      if e['kind'] == 'inbound'])
        self.assertEqual(record['audit']['peers'], {self.upstream.origin: ['127.0.0.1']})
        self.upstream.release.set()
        worker.join(CEILING_S)

        port = self.command('listen')
        code, record = self.census()
        self.assertEqual((code, record['verdict']), (1, 'FAIL'))
        self.assertIn(f'a listener that is not configured: 127.0.0.1:{port}', record['violations'])

        target = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(target.close)
        target.bind(('127.0.0.1', 0))
        target.listen(1)
        self.command(f'connect {target.getsockname()[1]}')
        code, record = self.census()
        self.assertEqual((code, record['verdict']), (1, 'FAIL'))
        self.assertIn(f'an outbound connection to 127.0.0.1:{target.getsockname()[1]}: no configured origin\'s port',
                      record['violations'])

        port = self.command('udp')
        code, record = self.census()
        self.assertEqual((code, record['verdict']), (1, 'FAIL'))
        self.assertIn(f'a UDP endpoint 127.0.0.1:{port}', record['violations'])
        self.assertFalse((self.tmp / 'data-root').exists())


if __name__ == '__main__':
    unittest.main()
