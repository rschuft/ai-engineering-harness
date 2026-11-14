"""The native profile's provider tunnel (plan leaf E-05.10; decision 0023 section 4.2), offline: every connection is
made on 127.0.0.1 to a tunnel in this process (or, for the lifecycle, in a child process of its own), and its
outbound seam reaches a fake origin on 127.0.0.1, never the provider and never the network.

The ClientHellos are built here from the TLS 1.3 structure (RFC 8446 section 4.1.2; server_name RFC 6066 section 3);
they are structurally valid and carry no key material that matters: the tunnel never reads past the structure.
"""
from __future__ import annotations

import ast
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent / 'provider_tunnel.py'
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
import provider_tunnel as T  # noqa: E402

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
SENTINEL = b'aieh-payload-sentinel-7f3c'
PROFILE = json.loads((REPO / 'profiles' / 'strong-windows-qemu-whpx' / 'profile.json').read_text(encoding='utf-8'))
WAIT_S = 20          # a ceiling on a hang: every wait below is on its own completion signal


def len2(data: bytes) -> bytes:
    return len(data).to_bytes(2, 'big')


def client_hello(sni='api.anthropic.com', extensions=(), with_extensions=True, random=b'\x01' * 32,
                 session=b'\x02' * 32, names=None) -> bytes:
    """One TLS handshake record holding one ClientHello: server_name SNI (None: no server_name extension; NAMES: the
    raw list of host_name entries) then EXTENSIONS [(type, data)]."""
    exts = b''
    if sni is not None or names is not None:
        entries = names if names is not None else [sni.encode('ascii')]
        listed = b''.join(b'\x00' + len2(n) + n for n in entries)
        data = len2(listed) + listed
        exts += b'\x00\x00' + len2(data) + data
    for kind, data in extensions:
        exts += kind.to_bytes(2, 'big') + len2(data) + data
    suites = b'\x13\x01\x13\x02\x13\x03'
    body = b'\x03\x03' + random + bytes([len(session)]) + session + len2(suites) + suites + b'\x01\x00'
    if with_extensions:
        body += len2(exts) + exts
    handshake = b'\x01' + len(body).to_bytes(3, 'big') + body
    return b'\x16\x03\x01' + len2(handshake) + handshake


class FakeOrigin:
    """A loopback listener standing in for the provider's origin: it records every byte it receives on each
    connection and answers the first record it reads with REPLY."""
    REPLY = b'\x16\x03\x03\x00\x05fake!'

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.received: list[bytearray] = []
        self.done = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            got = bytearray()
            self.received.append(got)
            threading.Thread(target=self._one, args=(conn, got), daemon=True).start()

    def _one(self, conn, got):
        answered = False
        with conn:
            while True:
                try:
                    data = conn.recv(65536)
                except OSError:
                    break
                if not data:
                    break
                got += data
                if not answered:
                    conn.sendall(self.REPLY)
                    answered = True
        self.done.set()

    def close(self):
        self.sock.close()


class Rig:
    """A tunnel on an ephemeral 127.0.0.1 port in this process, its log in memory, its outbound seam recording each
    call and reaching the fake origin."""

    def __init__(self, test, **options):
        self.origin = FakeOrigin()
        self.resolved, self.connected = [], []
        self.log = T.MemoryLog()

        def resolve(host, port):
            self.resolved.append((host, port))
            return ['127.0.0.1']

        def connect(address, port, timeout):
            self.connected.append((address, port))
            return socket.create_connection((address, self.origin.port), timeout=timeout)
        self.tunnel = T.Tunnel(0, self.log, resolve=resolve, connect=connect, **options)
        self.address = self.tunnel.start()
        test.addCleanup(self.close)

    def close(self):
        if not self.tunnel.stopping.is_set():
            self.tunnel.stop('test')
        self.origin.close()

    def client(self) -> socket.socket:
        sock = socket.create_connection(self.address, timeout=WAIT_S)
        return sock

    def request(self, head: bytes) -> tuple[bytes, socket.socket]:
        sock = self.client()
        sock.sendall(head)
        return read_head(sock), sock

    def ended(self, number=None) -> list:
        """The connection lines, once every connection has logged its end."""
        deadline = threading.Event()
        for _ in range(int(WAIT_S / 0.05)):
            if self.tunnel.open_connections() == 0:
                break
            deadline.wait(0.05)
        return [line for line in self.log.lines if line['event'] == 'connection']


def read_head(sock) -> bytes:
    data = b''
    while b'\r\n\r\n' not in data:
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    return data


def read_all(sock) -> bytes:
    data = b''
    while True:
        try:
            chunk = sock.recv(65536)
        except (ConnectionResetError, ConnectionAbortedError):
            break
        if not chunk:
            break
        data += chunk
    return data


CONNECT = b'CONNECT api.anthropic.com:443 HTTP/1.1\r\nHost: api.anthropic.com:443\r\n\r\n'


class Listener(unittest.TestCase):
    """The tunnel listens on host 127.0.0.1 only."""

    def test_it_binds_loopback_only(self):
        rig = Rig(self)
        self.assertEqual(rig.address[0], '127.0.0.1')
        self.assertEqual(rig.log.lines[0]['event'], 'tunnel-start')
        self.assertEqual(rig.log.lines[0]['listener'], {'address': '127.0.0.1', 'port': rig.address[1]})
        others = sorted({info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
                        - {'127.0.0.1'})
        for address in others:              # the host's own non-loopback addresses, when it has any
            with self.assertRaises(OSError, msg=address):
                socket.create_connection((address, rig.address[1]), timeout=2).close()

    def test_the_bind_address_is_a_constant(self):
        tree = ast.parse(MODULE.read_text(encoding='utf-8'))
        binds = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and
                 isinstance(node.func, ast.Attribute) and node.func.attr == 'bind']
        self.assertEqual(len(binds), 1)
        self.assertEqual(ast.unparse(binds[0].args[0]), '(LOOPBACK, self.port)')
        self.assertEqual(T.LOOPBACK, '127.0.0.1')

    def test_the_port_is_the_profiles_declaration(self):
        declared = T.declared_endpoint(PROFILE)
        entry = [e for e in PROFILE['network']['endpoints'] if e['class'] == 'provider-tunnel'][0]
        self.assertEqual(declared['host_port'], entry['host_port'])
        self.assertEqual((declared['guest_address'], declared['guest_port']), ('172.17.0.1', 8090))
        for bad in ({}, {'network': {'endpoints': []}},
                    {'network': {'endpoints': [entry, entry]}},
                    {'network': {'endpoints': [dict(entry, host_bind='0.0.0.0')]}},
                    {'network': {'endpoints': [dict(entry, host_port='18433')]}},
                    {'network': {'endpoints': [dict(entry, host_port=80)]}},
                    {'network': {'endpoints': [dict(entry, origin='api.anthropic.com:80')]}}):
            with self.assertRaises(T.TunnelError) as ctx:
                T.declared_endpoint(bad)
            self.assertEqual(ctx.exception.code, 'TUNNEL_PROFILE_INVALID')


class Admitted(unittest.TestCase):
    """A CONNECT to exactly api.anthropic.com:443 with a ClientHello naming it is spliced, unread, to the origin."""

    def test_the_admitted_connect_is_spliced_byte_for_byte(self):
        rig = Rig(self)
        answer, sock = rig.request(CONNECT)
        self.assertEqual(answer, b'HTTP/1.1 200 Connection Established\r\n\r\n')
        hello = client_hello(random=SENTINEL[:26] + b'\x00' * 6)
        sock.sendall(hello)
        reply = b''
        while len(reply) < len(FakeOrigin.REPLY):
            reply += sock.recv(65536)
        self.assertEqual(reply, FakeOrigin.REPLY)
        later = b'\x17\x03\x03\x00\x20' + SENTINEL + b'\x00' * 6
        sock.sendall(later)
        sock.shutdown(socket.SHUT_WR)
        self.assertEqual(read_all(sock), b'')
        sock.close()
        self.assertTrue(rig.origin.done.wait(WAIT_S))
        self.assertEqual(bytes(rig.origin.received[0]), hello + later)     # as sent: nothing read, nothing changed
        self.assertEqual(rig.resolved, [('api.anthropic.com', 443)])
        self.assertEqual(rig.connected, [('127.0.0.1', 443)])
        lines = rig.ended()
        self.assertEqual(lines[0]['decision'], 'admitted')
        self.assertEqual((lines[0]['target'], lines[0]['reason'], lines[0]['end']),
                         ('api.anthropic.com:443', None, 'closed'))
        self.assertEqual((lines[0]['bytes_up'], lines[0]['bytes_down']), (len(hello + later), len(FakeOrigin.REPLY)))
        connects = [line for line in rig.log.lines if line['event'] == 'upstream-connect']
        self.assertEqual([(c['origin'], c['peer']['address']) for c in connects],
                         [('api.anthropic.com:443', '127.0.0.1')])

    def test_a_hello_sent_in_pieces_is_read_whole(self):
        rig = Rig(self)
        _, sock = rig.request(CONNECT)
        hello = client_hello()
        for i in range(0, len(hello), 7):
            sock.sendall(hello[i:i + 7])
        self.assertEqual(sock.recv(65536)[:5], FakeOrigin.REPLY[:5])
        sock.close()
        self.assertEqual(rig.ended()[0]['decision'], 'admitted')


def refused_before_200(test, rig, head, code, status):
    answer, sock = rig.request(head)
    sock.close()
    top, _, body = answer.partition(b'\r\n\r\n')
    test.assertTrue(top.startswith(f'HTTP/1.1 {status} '.encode()), (head, top))
    test.assertIn(f'X-AIEH-Tunnel-Refusal: {code}'.encode(), top)
    line = rig.ended()[-1]
    test.assertEqual((line['decision'], line['reason'], line['bytes_up'], line['bytes_down']),
                     ('refused', code, 0, 0))
    return line


class RefusedRequests(unittest.TestCase):
    """Every other request is refused, with a logged reason, before any outbound connection."""

    def test_other_hosts_ports_and_ip_literals(self):
        rig = Rig(self)
        cases = [
            (b'CONNECT example.com:443 HTTP/1.1\r\n\r\n', 'TUNNEL_TARGET_REFUSED', 'example.com:443'),
            (b'CONNECT api.anthropic.com.evil.test:443 HTTP/1.1\r\n\r\n', 'TUNNEL_TARGET_REFUSED', None),
            (b'CONNECT api.anthropic.com.:443 HTTP/1.1\r\n\r\n', 'TUNNEL_TARGET_REFUSED', None),
            (b'CONNECT API.anthropic.com:443 HTTP/1.1\r\n\r\n', 'TUNNEL_TARGET_REFUSED', None),
            (b'CONNECT statsig.anthropic.com:443 HTTP/1.1\r\n\r\n', 'TUNNEL_TARGET_REFUSED', None),
            (b'CONNECT api.anthropic.com:80 HTTP/1.1\r\n\r\n', 'TUNNEL_PORT_REFUSED', 'api.anthropic.com:80'),
            (b'CONNECT api.anthropic.com:8443 HTTP/1.1\r\n\r\n', 'TUNNEL_PORT_REFUSED', None),
            (b'CONNECT 160.79.104.10:443 HTTP/1.1\r\n\r\n', 'TUNNEL_TARGET_IP_LITERAL', '160.79.104.10:443'),
            (b'CONNECT [2607:6bc0::10]:443 HTTP/1.1\r\n\r\n', 'TUNNEL_TARGET_IP_LITERAL', None),
            (b'CONNECT 2690607114:443 HTTP/1.1\r\n\r\n', 'TUNNEL_TARGET_IP_LITERAL', None),
            (b'CONNECT 0xa0.0x4f.0x68.0xa:443 HTTP/1.1\r\n\r\n', 'TUNNEL_TARGET_IP_LITERAL', None),
            (b'CONNECT 127.1:443 HTTP/1.1\r\n\r\n', 'TUNNEL_TARGET_IP_LITERAL', None),
        ]
        for head, code, target in cases:
            line = refused_before_200(self, rig, head, code, 403)
            if target is not None:
                self.assertEqual(line['target'], target)
        self.assertEqual((rig.resolved, rig.connected), ([], []))

    def test_every_request_that_is_not_a_connect(self):
        rig = Rig(self)
        secret_url = b'/v1/messages?key=' + SENTINEL
        for head in (b'GET / HTTP/1.1\r\nHost: 172.17.0.1:8090\r\n\r\n',
                     b'GET http://api.anthropic.com' + secret_url + b' HTTP/1.1\r\nHost: api.anthropic.com\r\n\r\n',
                     b'POST /v1/messages HTTP/1.1\r\nContent-Length: 0\r\nUser-Agent: ' + SENTINEL + b'\r\n\r\n',
                     b'HEAD / HTTP/1.0\r\n\r\n', b'OPTIONS * HTTP/1.1\r\n\r\n',
                     b'connect api.anthropic.com:443 HTTP/1.1\r\n\r\n'):
            line = refused_before_200(self, rig, head, 'TUNNEL_NOT_CONNECT', 405)
            self.assertIsNone(line['target'])                    # a URL may carry a credential: never logged
        self.assertNotIn(SENTINEL.decode(), json.dumps(rig.log.lines))
        self.assertEqual((rig.resolved, rig.connected), ([], []))

    def test_malformed_heads_and_an_offered_credential(self):
        rig = Rig(self, head_timeout_s=0.5)
        for head in (b'CONNECT api.anthropic.com:443\r\n\r\n', b'CONNECT api.anthropic.com:443 HTTP/2\r\n\r\n',
                     b'CONNECT api.anthropic.com HTTP/1.1\r\n\r\n', b'\x16\x03\x01\x00\x05hello\r\n\r\n',
                     b'CONNECT api.anthropic.com:443 HTTP/1.1\r\nno colon\r\n\r\n',
                     b'CONNECT api.anthropic.com:443 HTTP/1.1\r\nX: ' + b'a' * 9000 + b'\r\n\r\n'):
            refused_before_200(self, rig, head, 'TUNNEL_REQUEST_MALFORMED', 400)
        sock = rig.client()                                    # an incomplete head, never finished
        sock.sendall(b'CONNECT api.anthropic.com:443 HTTP/1.1\r\n')
        self.assertTrue(read_head(sock).startswith(b'HTTP/1.1 400 '))
        sock.close()
        line = refused_before_200(self, rig, CONNECT[:-2] + b'Proxy-Authorization: Basic ' + SENTINEL + b'\r\n\r\n',
                                  'TUNNEL_PROXY_CREDENTIAL', 403)
        self.assertIsNone(line['target'])
        self.assertNotIn(SENTINEL.decode(), json.dumps(rig.log.lines))
        self.assertEqual((rig.resolved, rig.connected), ([], []))


class RefusedHellos(unittest.TestCase):
    """After the 200, a ClientHello whose server name is absent or differs from the CONNECT host (or one that
    cannot be checked) closes the connection before any outbound connection."""

    def refused(self, rig, data, code):
        answer, sock = rig.request(CONNECT)
        self.assertEqual(answer, b'HTTP/1.1 200 Connection Established\r\n\r\n')
        if data:
            sock.sendall(data)
        self.assertEqual(read_all(sock), b'')                  # closed: no ServerHello, nothing of the origin's
        sock.close()
        line = rig.ended()[-1]
        self.assertEqual((line['decision'], line['reason'], line['target'], line['bytes_up'], line['bytes_down']),
                         ('refused', code, 'api.anthropic.com:443', 0, 0))

    def test_each_refused_hello(self):
        rig = Rig(self, hello_timeout_s=0.5)
        hello = client_hello()
        cases = [
            (client_hello(sni=None), 'TUNNEL_SNI_ABSENT'),
            (client_hello(sni=None, with_extensions=False), 'TUNNEL_SNI_ABSENT'),
            (client_hello(names=[]), 'TUNNEL_SNI_ABSENT'),
            (client_hello(sni='example.com'), 'TUNNEL_SNI_MISMATCH'),
            (client_hello(sni=SENTINEL.decode()), 'TUNNEL_SNI_MISMATCH'),
            (client_hello(sni='API.ANTHROPIC.COM'), 'TUNNEL_SNI_MISMATCH'),
            (client_hello(sni='api.anthropic.com', extensions=[(0xfe0d, b'\x00' * 40)]), 'TUNNEL_ECH_REFUSED'),
            (client_hello(sni='api.anthropic.com', extensions=[(0xffce, b'\x00' * 40)]), 'TUNNEL_ECH_REFUSED'),
            (client_hello(names=[b'api.anthropic.com', b'example.com']), 'TUNNEL_HELLO_MALFORMED'),
            (client_hello(extensions=[(0x0000, b'\x00\x00')]), 'TUNNEL_HELLO_MALFORMED'),     # server_name twice
            (b'\x17' + hello[1:], 'TUNNEL_HELLO_MALFORMED'),                                 # not a handshake
            (hello[:5] + b'\x02' + hello[6:], 'TUNNEL_HELLO_MALFORMED'),                     # not a ClientHello
            (b'\x16\x03\x01\x40\x01' + b'\x00' * 10, 'TUNNEL_HELLO_MALFORMED'),              # longer than 16 KiB
            (b'GET / HTTP/1.1\r\n\r\n', 'TUNNEL_HELLO_MALFORMED'),                            # plain HTTP inside
            (hello[:20], 'TUNNEL_HELLO_MALFORMED'),                                           # never completed
            (b'', 'TUNNEL_HELLO_MALFORMED'),                                                  # nothing at all
        ]
        # A ClientHello split over two records: the first record carries only part of the handshake message.
        body = hello[5:]
        first, second = body[:60], body[60:]
        split = b'\x16\x03\x01' + len2(first) + first + b'\x16\x03\x01' + len2(second) + second
        cases.append((split, 'TUNNEL_HELLO_FRAGMENTED'))
        for data, code in cases:
            with self.subTest(code=code, data=data[:12]):
                self.refused(rig, data, code)
        self.assertEqual((rig.resolved, rig.connected), ([], []))
        self.assertNotIn(SENTINEL.decode(), json.dumps(rig.log.lines))

    def test_bytes_past_the_first_record_are_refused(self):
        """Read directly (both pieces already sent, so one read holds them): a second handshake record is a
        fragmented hello, any other byte before the server's answer is refused."""
        tunnel = T.Tunnel(0, T.MemoryLog(), hello_timeout_s=2)
        hello = client_hello()
        for extra, code in ((b'\x16\x03\x01\x00\x01x', 'TUNNEL_HELLO_FRAGMENTED'),
                            (b'\x17\x03\x03\x00\x01x', 'TUNNEL_HELLO_MALFORMED')):
            a, b = socket.socketpair()
            with a, b:
                a.settimeout(T.STOP_POLL_S)
                b.sendall(hello + extra)
                with self.assertRaises(T.Refused) as ctx:
                    tunnel._read_record(a, b'')
                self.assertEqual(ctx.exception.code, code)
        a, b = socket.socketpair()
        with a, b:
            a.settimeout(T.STOP_POLL_S)
            b.sendall(hello[7:])
            self.assertEqual(tunnel._read_record(a, hello[:7]), hello)

    def test_the_parser_alone(self):
        self.assertEqual(T.server_name(client_hello()), 'api.anthropic.com')
        with self.assertRaises(T.Refused) as ctx:
            T.server_name(client_hello()[:-1])
        self.assertEqual(ctx.exception.code, 'TUNNEL_HELLO_MALFORMED')


class RealClientHello(unittest.TestCase):
    """The tunnel reads the ClientHello a real TLS stack sends (this interpreter's ssl module): the origin's
    name admitted and spliced byte for byte to the origin, another name and none refused before any outbound
    connection."""

    def handshake(self, rig, server_hostname, context):
        _, sock = rig.request(CONNECT)
        try:
            context.wrap_socket(sock, server_hostname=server_hostname)
        except (ssl.SSLError, OSError):
            pass                                          # the fake origin answers no ServerHello
        finally:
            sock.close()

    def test_a_real_client_hello(self):
        context = ssl.create_default_context()
        rig = Rig(self)
        self.handshake(rig, 'api.anthropic.com', context)
        self.assertTrue(rig.origin.done.wait(WAIT_S))
        received = bytes(rig.origin.received[0])
        record = received[:5 + int.from_bytes(received[3:5], 'big')]
        self.assertEqual(T.server_name(record), 'api.anthropic.com')
        self.assertEqual(rig.ended()[0]['decision'], 'admitted')
        self.handshake(rig, 'example.com', context)
        bare = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        bare.check_hostname, bare.verify_mode = False, ssl.CERT_NONE
        self.handshake(rig, None, bare)
        reasons = [line['reason'] for line in rig.ended()]
        self.assertEqual(reasons, [None, 'TUNNEL_SNI_MISMATCH', 'TUNNEL_SNI_ABSENT'])
        self.assertEqual(len(rig.connected), 1)


class Origin(unittest.TestCase):
    """Its own outbound connections go only to the admitted origin, resolved on the host."""

    def test_the_seam_is_called_with_the_origin_only(self):
        tree = ast.parse(MODULE.read_text(encoding='utf-8'))
        calls = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and
                 ast.unparse(n.func) in ('self.resolve', 'self.connect')]
        self.assertEqual(sorted(calls), ['self.connect(address, ORIGIN_PORT, CONNECT_TIMEOUT_S)',
                                         'self.resolve(ORIGIN_HOST, ORIGIN_PORT)'])
        self.assertEqual((T.ORIGIN_HOST, T.ORIGIN_PORT), ('api.anthropic.com', 443))
        tree_calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
        self.assertEqual(sorted(c for c in tree_calls if c in ('socket.create_connection', 'socket.getaddrinfo')),
                         ['socket.create_connection', 'socket.getaddrinfo'])

    def test_the_hosts_resolution_refuses_an_address_that_is_not_global(self):
        def answer(*addresses):
            return [(socket.AF_INET6 if ':' in a else socket.AF_INET, socket.SOCK_STREAM, 6, '', (a, 443))
                    for a in addresses]
        with mock.patch.object(T.socket, 'getaddrinfo', return_value=answer('160.79.104.10', '160.79.104.10')) as gai:
            self.assertEqual(T.resolve_origin('api.anthropic.com', 443), ['160.79.104.10'])
        self.assertEqual(gai.call_args[0][:2], ('api.anthropic.com', 443))
        for bad in ('127.0.0.1', '10.0.2.2', '172.17.0.1', '169.254.1.1', '::1', 'fd00::1'):
            with mock.patch.object(T.socket, 'getaddrinfo', return_value=answer('160.79.104.10', bad)), \
                    self.assertRaises(T.Refused) as ctx:
                T.resolve_origin('api.anthropic.com', 443)
            self.assertEqual(ctx.exception.code, 'TUNNEL_UPSTREAM_REFUSED')

    def test_an_unreachable_or_refused_origin_closes_the_admitted_connection(self):
        for failure, code in ((OSError('no route'), 'TUNNEL_UPSTREAM_FAILED'),
                              (T.Refused('TUNNEL_UPSTREAM_REFUSED'), 'TUNNEL_UPSTREAM_REFUSED')):
            rig = Rig(self)
            rig.tunnel.resolve = mock.Mock(side_effect=failure)
            _, sock = rig.request(CONNECT)
            sock.sendall(client_hello())
            self.assertEqual(read_all(sock), b'')
            sock.close()
            line = rig.ended()[-1]
            self.assertEqual((line['decision'], line['reason']), ('refused', code))


class NoCredentialNoTls(unittest.TestCase):
    """It holds no credential and terminates no TLS: it imports no TLS or credential module, reads no environment
    variable, configuration or credential store, and logs only targets, decisions and byte counts."""

    def test_its_imports_and_reads(self):
        tree = ast.parse(MODULE.read_text(encoding='utf-8'))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split('.')[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or '').split('.')[0])
        self.assertEqual(imported, {'__future__', 'argparse', 'dataclasses', 'datetime', 'importlib', 'ipaddress',
                                    'json', 'os', 're', 'secrets', 'select', 'signal', 'socket', 'sys', 'threading',
                                    'time', 'pathlib', 'typing', 'ctypes'})
        text = MODULE.read_text(encoding='utf-8')
        for word in ('environ', 'getenv', 'ssl', 'keyring', 'credential_provider', 'config.yml', 'getpass'):
            self.assertNotIn(word, [n.attr if isinstance(n, ast.Attribute) else getattr(n, 'id', None)
                                    for n in ast.walk(tree)], word)
        loaded = [ast.unparse(n.args[1]) for n in ast.walk(tree) if isinstance(n, ast.Call) and
                  ast.unparse(n.func) == '_load']
        self.assertEqual(sorted(loaded), ["HERE / 'inference_census.py'",
                                          "REPO / 'integrations' / 'paths' / 'aieh_paths.py'"])
        self.assertNotIn('BEGIN CERTIFICATE', text)
        self.assertNotIn('PRIVATE KEY', text)

    def test_serve_loads_no_broker_or_credential_module(self):
        """In a fresh interpreter: the module, a tunnel started and stopped, and not one broker, credential or TLS
        module loaded (the census alone loads the broker's census)."""
        script = (
            'import sys, socket; sys.path.insert(0, sys.argv[1]); import provider_tunnel as T\n'
            'before = set(sys.modules)\n'
            't = T.Tunnel(0, T.MemoryLog()); t.start(); t.stop()\n'
            'bad = sorted(m for m in sys.modules if m.startswith(("aieh_", "ssl", "_ssl", "keyring", "http")))\n'
            'print(bad)\n')
        out = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(HERE.parent)], capture_output=True,
                             text=True, timeout=60, creationflags=NO_WINDOW)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), '[]')

    def test_the_log_carries_no_payload_and_only_its_fields(self):
        rig = Rig(self, hello_timeout_s=0.5)
        _, sock = rig.request(CONNECT)
        sock.sendall(client_hello(random=SENTINEL[:26] + b'\x00' * 6, session=SENTINEL[:32]))
        sock.recv(65536)
        sock.sendall(SENTINEL * 10)
        sock.close()
        rig.request(b'GET /' + SENTINEL + b' HTTP/1.1\r\nCookie: ' + SENTINEL + b'\r\n\r\n')[1].close()
        _, refused = rig.request(CONNECT)
        refused.sendall(client_hello(sni=SENTINEL.decode()))
        read_all(refused)
        refused.close()
        lines = rig.ended()
        rig.tunnel.stop('test')
        text = json.dumps(rig.log.lines)
        self.assertNotIn(SENTINEL.decode(), text)
        allowed = {'tunnel-start': {'listener', 'origin', 'pid'},
                   'upstream-connect': {'conn', 'target', 'origin', 'peer'},
                   'connection': {'conn', 'target', 'decision', 'reason', 'end', 'bytes_up', 'bytes_down'},
                   'tunnel-stop': {'stopped_by', 'connections_cut', 'connections_left'}}
        for line in rig.log.lines:
            self.assertEqual(set(line) - {'format', 'event', 'at'}, allowed[line['event']], line)
        self.assertEqual(len(lines), 3)


class Stop(unittest.TestCase):
    """The stop closes the listener and cuts every open connection; the cut connection logs its end."""

    def test_the_stop_cuts_a_spliced_and_a_waiting_connection(self):
        rig = Rig(self)
        _, spliced = rig.request(CONNECT)
        spliced.sendall(client_hello())
        spliced.recv(65536)
        waiting = rig.client()                       # sends nothing: the tunnel waits for its head
        waiting.sendall(b'CONN')
        for _ in range(int(WAIT_S / 0.05)):
            if rig.tunnel.open_connections() == 2:
                break
            threading.Event().wait(0.05)
        result = rig.tunnel.stop('test')
        self.assertEqual((result['connections_cut'], result['connections_left']), (2, 0))
        ends = sorted((line['decision'], line['end']) for line in rig.log.lines if line['event'] == 'connection')
        self.assertEqual(ends, [('admitted', 'stopped'), ('refused', 'stopped')])
        self.assertEqual(rig.log.lines[-1]['event'], 'tunnel-stop')
        with self.assertRaises(OSError):
            socket.create_connection(rig.address, timeout=2).close()
        spliced.close()
        waiting.close()

    def test_the_signal_handler_sets_a_flag_only(self):
        flag = T.StopFlag()
        restore = T.install_stop_signals(flag)
        try:
            handler = __import__('signal').getsignal(__import__('signal').SIGINT)
            handler(__import__('signal').SIGINT, None)
            self.assertEqual(flag.asked, 'SIGINT')
            handler(__import__('signal').SIGINT, None)
            self.assertEqual(flag.asked, 'SIGINT')
        finally:
            restore()

    def test_the_wait_returns_on_the_stop_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / T.STOP_NAME).write_text('{}', encoding='utf-8')
            self.assertEqual(T.wait_for_stop(None, Path(tmp), poll_s=0.01), 'stop-request')


@unittest.skipUnless(os.name == 'nt', 'the process lifecycle is verified on Windows')
class Lifecycle(unittest.TestCase):
    """serve in a process of its own, started with no window: its run record, its listener on 127.0.0.1 only in the
    operating system's tables, a second serve refused, the stop command, a clean exit and no record or port left."""

    def test_serve_census_stop(self):
        tmp = Path(tempfile.mkdtemp(prefix='aieh-tunnel-'))
        self.addCleanup(__import__('shutil').rmtree, tmp, True)
        (tmp / 'run').mkdir()
        (tmp / 'logs').mkdir()
        (tmp / 'profile').mkdir()
        entry = [e for e in PROFILE['network']['endpoints'] if e['class'] == 'provider-tunnel'][0]
        (tmp / 'profile' / 'profile.json').write_text(json.dumps({'network': {'endpoints': [entry]}}),
                                                       encoding='utf-8')
        spec = tmp / 'spec.json'
        spec.write_text(json.dumps({'run_dir': str(tmp / 'run'), 'logs': str(tmp / 'logs'),
                                    'profile': str(tmp / 'profile')}), encoding='utf-8')
        child = subprocess.Popen([sys.executable, '-I', '-B', str(HERE / 'tunnel_child.py'), str(spec)],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=NO_WINDOW)
        self.addCleanup(child.stderr.close)
        self.addCleanup(child.stdout.close)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        line = child.stderr.readline().decode('utf-8')           # the serving line: its own completion signal
        self.assertIn('provider-tunnel: serving: ', line)
        record = json.loads(line.split('serving: ', 1)[1])
        self.assertEqual(T.read_run(tmp / 'run'), record)
        ctx = T.Context(run_dir=lambda: tmp / 'run', logs=lambda: tmp / 'logs', out=mock.Mock(), err=mock.Mock())
        census = T.census(ctx)
        self.assertEqual(census['verdict'], 'PASS', census)
        listeners = [e for e in census['endpoints'] if e['kind'] == 'listener']
        self.assertEqual(listeners, [{'protocol': 'tcp', 'version': 4, 'state': 'LISTEN',
                                      'local': f'127.0.0.1:{record["port"]}', 'remote': '0.0.0.0:0',
                                      'kind': 'listener', 'ok': True}])
        with self.assertRaises(T.TunnelError) as again:
            T.serve(ctx, 0)
        self.assertEqual(again.exception.code, 'TUNNEL_ALREADY_RUNNING')
        self.assertEqual(T.stop(ctx), {'result': 'stopped', 'pid': record['pid'], 'port': record['port']})
        self.assertEqual(child.wait(WAIT_S), 0)
        out = json.loads(child.stdout.read().decode('utf-8'))
        self.assertEqual(out['stopped_by'], 'stop-request')
        self.assertIsNone(T.read_run(tmp / 'run'))
        self.assertFalse((tmp / 'run' / T.STOP_NAME).exists())
        logs = list((tmp / 'logs').iterdir())
        self.assertEqual(len(logs), 1)
        events = [json.loads(x)['event'] for x in logs[0].read_text(encoding='utf-8').splitlines()]
        self.assertEqual(events, ['tunnel-start', 'tunnel-stop'])
        with self.assertRaises(OSError):
            socket.create_connection(('127.0.0.1', record['port']), timeout=2).close()
        with self.assertRaises(T.TunnelError) as gone:
            T.stop(ctx)
        self.assertEqual(gone.exception.code, 'TUNNEL_NOT_RUNNING')


class Census(unittest.TestCase):
    """The census judges the tunnel's sockets by inference_census.py's rule, with its log's upstream peers."""

    def test_outbound_only_to_a_recorded_peer_of_the_origin(self):
        census_module = T._load('aieh_inference_census', T.HERE / 'inference_census.py')
        E = census_module.Endpoint
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pid = os.getpid()
            log = tmp / 'tunnel-20261114T000000Z-0123abcd.jsonl'
            log.write_text(json.dumps({'event': 'upstream-connect', 'peer': {'address': '160.79.104.10',
                                                                               'port': 443}}) + '\n',
                           encoding='utf-8')
            T.write_new(tmp / T.RUN_NAME, {'format': T.RUN_FORMAT, 'pid': pid, 'address': '127.0.0.1',
                                            'port': 18433, 'log': log.name})
            base = [E('tcp', 4, 'LISTEN', '127.0.0.1', 18433, '0.0.0.0', 0, pid),
                    E('tcp', 4, 'ESTABLISHED', '127.0.0.1', 18433, '127.0.0.1', 50000, pid),
                    E('tcp', 4, 'ESTABLISHED', '10.0.0.5', 50001, '160.79.104.10', 443, pid),
                    E('tcp', 4, 'ESTABLISHED', '10.0.0.5', 50002, '1.2.3.4', 443, pid + 1)]

            def run(rows):
                ctx = T.Context(run_dir=lambda: tmp, logs=lambda: tmp, out=None, err=None, tables=lambda: rows)
                return T.census(ctx)
            self.assertEqual(run(base)['verdict'], 'PASS')
            for extra in (E('tcp', 4, 'ESTABLISHED', '10.0.0.5', 50003, '1.2.3.4', 443, pid),
                          E('tcp', 4, 'LISTEN', '0.0.0.0', 18433, '0.0.0.0', 0, pid),
                          E('udp', 4, None, '127.0.0.1', 5353, None, None, pid),
                          E('tcp', 4, 'ESTABLISHED', '10.0.0.5', 50004, '160.79.104.10', 80, pid)):
                self.assertEqual(run(base + [extra])['verdict'], 'FAIL', extra)
            self.assertEqual(run(base[1:])['verdict'], 'FAIL')     # the listener missing


if __name__ == '__main__':
    unittest.main()
