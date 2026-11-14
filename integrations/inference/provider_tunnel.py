"""The native execution profile's provider tunnel (plan leaf E-05.10; decision 0023 sections 4 and 6): a host
loopback CONNECT-only tunnel that admits exactly api.anthropic.com:443 and checks the TLS server name, holding no
credential and decrypting nothing.

The guest's inference forward (S-03.2's sshd remote forward on 172.17.0.1:8090, guest side unchanged) ends here
instead of at the broker when the forward holder starts it for the native profile (tools/guest.py inference-forward
--execution-profile native). Claude Code in the attempt's container reaches the provider through it as its
HTTPS_PROXY (E-05.9: http://172.17.0.1:8090); the TLS session is end to end between Claude Code and the provider.

Per connection, in this order, each refusal answered and logged with a stable reason (REFUSALS):

1. The request head is read, at most HEAD_LIMIT bytes within HEAD_TIMEOUT_S. Only `CONNECT <host>:<port> HTTP/1.x`
   is admitted: every other method (plain HTTP included) is TUNNEL_NOT_CONNECT (405); a head that is not a request
   (too large, incomplete in time, no version) TUNNEL_REQUEST_MALFORMED (400); a head carrying Proxy-Authorization
   TUNNEL_PROXY_CREDENTIAL (403: the tunnel takes no credential, not even one offered to it).
2. The target must be exactly ORIGIN (api.anthropic.com:443): an IP literal is TUNNEL_TARGET_IP_LITERAL, any other
   host TUNNEL_TARGET_REFUSED, the origin's host on another port TUNNEL_PORT_REFUSED (each 403).
3. The tunnel answers 200 and reads the client's first TLS record itself: one handshake record (content type 22)
   of at most 16 KiB holding exactly one whole ClientHello, within HELLO_TIMEOUT_S. A ClientHello split across
   records is TUNNEL_HELLO_FRAGMENTED; anything that does not parse TUNNEL_HELLO_MALFORMED; an encrypted ClientHello
   extension (ECH, or the ESNI draft) TUNNEL_ECH_REFUSED; no server_name TUNNEL_SNI_ABSENT; a server name other than
   the CONNECT host TUNNEL_SNI_MISMATCH. After the 200 a refusal cannot be an HTTP answer: the connection is closed.
4. Only then does the tunnel open its own outbound connection: the origin's host name resolved on the host (a
   resolved address that is not global is refused, TUNNEL_UPSTREAM_REFUSED) and a TCP connection to it on 443
   (TUNNEL_UPSTREAM_FAILED when none can be made). The ClientHello's bytes are sent as received, and from then on
   bytes are spliced both ways, unread, until either side ends or the tunnel stops.

The tunnel holds no key, certificate or credential and loads no TLS library: it never terminates TLS. It reads no
environment variable, no config.yml and no credential store. It listens on 127.0.0.1 only (LOOPBACK, a constant),
at the port the execution profile declares once (network.endpoints, class provider-tunnel, host_port; the same
entry gives the guest's HTTPS_PROXY, create_secrets.tunnel_endpoint). Its log (one JSON object per line,
LOG_FORMAT) carries only the target, the decision and its reason, byte counts, the upstream peer address it
connected to, and its own start and stop: never a byte of payload, never a header, never the target of a request
that is not a CONNECT (a URL may carry a credential), never the server name a refused ClientHello presented.

Lifecycle (the broker's pattern): `serve` runs in the foreground of the session that starts it and opens no window
of its own (a process that starts it from a session with no console passes CREATE_NO_WINDOW,
integrations/platform/no_window.py). It writes its run record (RUN_FORMAT: pid, address, port, log file) once
listening and removes it at its stop. The stop is asked by SIGINT, SIGBREAK or SIGTERM where the platform has them
(the handler sets a flag only; serve's main thread acts on it in slices of STOP_POLL_S), or, from any session, by
`stop`, which writes the stop request beside the run record and waits on the tunnel's process for at most
STOP_WAIT_S. At the stop the listener closes, every open connection is cut within one slice (logged
end: stopped), the tunnel-stop line is written and serve exits 0. It starts no process, so it leaves none behind.

  <tools python> -I -B integrations/inference/provider_tunnel.py serve --profile PROFILE_DIR
  <tools python> -I -B integrations/inference/provider_tunnel.py stop
  <tools python> -I -B integrations/inference/provider_tunnel.py census --once

`census --once` observes the running tunnel at the operating system (inference_census.py's tables and decision
rule, S-03.2): its process listens on exactly 127.0.0.1:<port>, owns no UDP endpoint, and owns no connection but
inbound ones from loopback and outbound ones to port 443 of an address its own log recorded as an upstream peer.

Exit 0 done, 1 failed (census: FAIL or UNKNOWN), 2 refused (a stable code, CODES). Standard library only.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import importlib.util
import ipaddress
import json
import os
import re
import secrets
import select
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Callable

HERE = Path(os.path.realpath(__file__)).parent
REPO = HERE.parents[1]

LOOPBACK = '127.0.0.1'
ORIGIN_HOST = 'api.anthropic.com'
ORIGIN_PORT = 443
ORIGIN = f'{ORIGIN_HOST}:{ORIGIN_PORT}'
ENDPOINT_CLASS = 'provider-tunnel'     # the profile's network.endpoints entry (E-05.9's field)
HEAD_LIMIT = 8192
HEAD_TIMEOUT_S = 10.0
RECORD_LIMIT = 16384                   # TLSPlaintext.length is at most 2^14
HELLO_TIMEOUT_S = 10.0
CONNECT_TIMEOUT_S = 10.0
IDLE_CEILING_S = 900.0                 # a spliced connection with no byte either way for this long is closed
SEND_TIMEOUT_S = 60.0
STOP_POLL_S = 0.25                     # the slice at which serve's main thread and each connection see the stop
STOP_CUT_CEILING_S = 5.0               # the stop's wait for the connections it cut to log their end
STOP_WAIT_S = 15.0                     # stop's wait on the tunnel's process
MAX_CONNECTIONS = 64
CHUNK = 65536
LOG_FORMAT = 'aieh-provider-tunnel-log/1'
RUN_FORMAT = 'aieh-provider-tunnel-run/1'
RUN_NAME = 'provider-tunnel.json'
STOP_NAME = 'provider-tunnel.stop'
LOG_NAME = re.compile(r'tunnel-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.jsonl')
STOP_SIGNALS = ('SIGINT', 'SIGBREAK', 'SIGTERM')
# TLS extension types the tunnel reads (IANA): server_name, and the two encrypted ClientHello forms it refuses.
EXT_SERVER_NAME = 0x0000
EXT_ECH = 0xfe0d
EXT_ESNI_DRAFT = 0xffce
AUTHORITY = re.compile(r'(?P<host>\[[0-9A-Fa-f:.]{2,45}\]|[A-Za-z0-9._~%!$&\'()*+,;=-]{1,253}):(?P<port>[0-9]{1,5})')
NUMERIC_HOST = re.compile(r'(0[xX][0-9A-Fa-f]+|[0-9]+)(\.(0[xX][0-9A-Fa-f]+|[0-9]+)){0,3}')

# Each refusal's reason (logged) and, before the 200, its HTTP status (answered).
REFUSALS = {
    'TUNNEL_NOT_CONNECT': (405, 'only CONNECT api.anthropic.com:443 is served: plain HTTP and every other method '
                                'are refused'),
    'TUNNEL_REQUEST_MALFORMED': (400, 'send one CONNECT request head (at most 8 KiB, within 10 s)'),
    'TUNNEL_PROXY_CREDENTIAL': (403, 'the tunnel takes no credential: send no Proxy-Authorization'),
    'TUNNEL_TARGET_IP_LITERAL': (403, 'connect by the origin\'s name, never an IP literal'),
    'TUNNEL_TARGET_REFUSED': (403, 'the only admitted target is api.anthropic.com:443'),
    'TUNNEL_PORT_REFUSED': (403, 'the only admitted target is api.anthropic.com:443'),
    'TUNNEL_BUSY': (503, 'too many open connections: try again'),
    'TUNNEL_HELLO_MALFORMED': (None, 'send one TLS ClientHello in one handshake record after the 200'),
    'TUNNEL_HELLO_FRAGMENTED': (None, 'send the ClientHello in one TLS record'),
    'TUNNEL_ECH_REFUSED': (None, 'the server name is checked: an encrypted ClientHello is refused'),
    'TUNNEL_SNI_ABSENT': (None, 'send the server_name extension naming the CONNECT host'),
    'TUNNEL_SNI_MISMATCH': (None, 'the ClientHello\'s server name must be the CONNECT host'),
    'TUNNEL_UPSTREAM_REFUSED': (None, 'the origin\'s name resolved to an address that is not global'),
    'TUNNEL_UPSTREAM_FAILED': (None, 'the origin could not be resolved or reached from the host'),
    'TUNNEL_STOPPED': (None, 'the tunnel is stopping'),
}
REASONS = {status: text for status, text in ((400, 'Bad Request'), (403, 'Forbidden'), (405, 'Method Not Allowed'),
                                             (503, 'Service Unavailable'))}
CODES = {
    'TUNNEL_PROFILE_INVALID': 'declare exactly one network.endpoints entry of class provider-tunnel with host_bind '
                              '127.0.0.1 and an integer host_port (1024-65535) in the execution profile',
    'TUNNEL_PORT_IN_USE': 'the declared port is taken: stop what holds it (or the tunnel already running)',
    'TUNNEL_ALREADY_RUNNING': 'a tunnel is already running (its run record names a live process): stop it first',
    'TUNNEL_NOT_RUNNING': 'no tunnel is running (no run record, or its process has ended)',
    'TUNNEL_STOP_TIMEOUT': 'the tunnel did not end within its stop ceiling: look at its process',
    'TUNNEL_RUN_RECORD_INVALID': 'the run record is not one this tunnel writes: remove it once no tunnel runs',
    'TUNNEL_PATHS_INVALID': 'fix the managed data root (aieh_paths.py check shows the refusal)',
}


class TunnelError(Exception):
    """A refusal of a command with a stable code (CODES)."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}. Remedy: {CODES[code]}.')


class Refused(Exception):
    """One connection's refusal (a REFUSALS code)."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def now_iso(epoch: float | None = None) -> str:
    stamp = datetime.datetime.fromtimestamp(time.time() if epoch is None else epoch, datetime.timezone.utc)
    return stamp.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


# ---------------------------------------------------------------- the declaration (one source of truth)

def declared_endpoint(profile) -> dict:
    """The execution profile's one tunnel endpoint (network.endpoints, class provider-tunnel): {'host_bind',
    'host_port', 'guest_address', 'guest_port'}; TUNNEL_PROFILE_INVALID otherwise. The host side is the tunnel's
    listener (and the forward holder's target), the guest side the HTTPS_PROXY E-05.9's admission compares."""
    endpoints = (profile.get('network') or {}).get('endpoints') if isinstance(profile, dict) else None
    entries = [e for e in endpoints or [] if isinstance(e, dict) and e.get('class') == ENDPOINT_CLASS]
    if len(entries) != 1:
        raise TunnelError('TUNNEL_PROFILE_INVALID', f'{len(entries)} {ENDPOINT_CLASS} endpoints declared')
    entry = entries[0]
    port = entry.get('host_port')
    if entry.get('host_bind') != LOOPBACK or type(port) is not int or not 1024 <= port <= 65535:
        raise TunnelError('TUNNEL_PROFILE_INVALID', f'the {ENDPOINT_CLASS} endpoint needs host_bind {LOOPBACK} and '
                                                    'an integer host_port of 1024-65535')
    if entry.get('origin') != ORIGIN:
        raise TunnelError('TUNNEL_PROFILE_INVALID', f'the {ENDPOINT_CLASS} endpoint\'s origin is not {ORIGIN}')
    return {'host_bind': LOOPBACK, 'host_port': port, 'guest_address': entry.get('guest_address'),
            'guest_port': entry.get('guest_port')}


def load_profile(directory) -> dict:
    path = Path(directory) / 'profile.json'
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise TunnelError('TUNNEL_PROFILE_INVALID', f'{path.name}: {type(exc).__name__}') from None


# ---------------------------------------------------------------- the request head and the target

def is_ip_literal(host: str) -> bool:
    """An IP literal in any spelling a resolver might accept: bracketed IPv6, dotted or numeric IPv4 (decimal, octal
    or hexadecimal parts), or anything ipaddress parses."""
    if host.startswith('['):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return NUMERIC_HOST.fullmatch(host) is not None


def parse_head(head: bytes) -> str:
    """The admitted CONNECT target of one request head (without its blank line), or Refused."""
    try:
        text = head.decode('ascii')
    except UnicodeDecodeError:
        raise Refused('TUNNEL_REQUEST_MALFORMED') from None
    lines = text.split('\r\n')
    words = lines[0].split(' ')
    if len(words) != 3 or not words[0] or not re.fullmatch(r'HTTP/1\.[01]', words[2]):
        raise Refused('TUNNEL_REQUEST_MALFORMED')
    if words[0] != 'CONNECT':
        raise Refused('TUNNEL_NOT_CONNECT')
    for line in lines[1:]:
        name, colon, _ = line.partition(':')
        if not colon or not name or name != name.strip():
            raise Refused('TUNNEL_REQUEST_MALFORMED')
        if name.lower() == 'proxy-authorization':
            raise Refused('TUNNEL_PROXY_CREDENTIAL')
    return words[1]


def check_target(target: str) -> None:
    """Admit exactly ORIGIN, or Refused with the reason."""
    match = AUTHORITY.fullmatch(target)
    if match is None:
        raise Refused('TUNNEL_REQUEST_MALFORMED')
    host, port = match.group('host'), int(match.group('port'))
    if is_ip_literal(host):
        raise Refused('TUNNEL_TARGET_IP_LITERAL')
    if host != ORIGIN_HOST:
        raise Refused('TUNNEL_TARGET_REFUSED')
    if port != ORIGIN_PORT:
        raise Refused('TUNNEL_PORT_REFUSED')


def logged_target(target: str | None) -> str | None:
    """The target as the log may carry it: a CONNECT authority of the grammar, else None."""
    return target if isinstance(target, str) and AUTHORITY.fullmatch(target) else None


# ---------------------------------------------------------------- the ClientHello

class _Reader:
    def __init__(self, data: bytes):
        self.data, self.at = data, 0

    def take(self, n: int) -> bytes:
        if n < 0 or self.at + n > len(self.data):
            raise Refused('TUNNEL_HELLO_MALFORMED')
        out = self.data[self.at:self.at + n]
        self.at += n
        return out

    def int(self, n: int) -> int:
        return int.from_bytes(self.take(n), 'big')

    def vector(self, length_bytes: int) -> bytes:
        return self.take(self.int(length_bytes))

    def done(self) -> bool:
        return self.at == len(self.data)


def record_length(header: bytes) -> int:
    """The length of the first TLS record from its 5-byte header, or Refused: a handshake record (22) of a TLS 1.x
    record version, 1 to RECORD_LIMIT bytes."""
    if len(header) != 5 or header[0] != 22 or header[1] != 3 or header[2] > 4:
        raise Refused('TUNNEL_HELLO_MALFORMED')
    length = int.from_bytes(header[3:5], 'big')
    if not 4 <= length <= RECORD_LIMIT:
        raise Refused('TUNNEL_HELLO_MALFORMED')
    return length


def server_name(record: bytes) -> str:
    """The one host_name of the ClientHello in one whole TLS handshake record (header included), or Refused:
    fragmented, malformed, encrypted (ECH), without a server name. Nothing but the structure is read."""
    length = record_length(record[:5])
    if len(record) != 5 + length:
        raise Refused('TUNNEL_HELLO_MALFORMED')
    body = _Reader(record[5:])
    if body.int(1) != 1:                                    # msg_type client_hello
        raise Refused('TUNNEL_HELLO_MALFORMED')
    hello_length = body.int(3)
    if 4 + hello_length > length:
        raise Refused('TUNNEL_HELLO_FRAGMENTED')            # the rest is in a later record
    if 4 + hello_length != length:
        raise Refused('TUNNEL_HELLO_MALFORMED')             # another message in the same record
    hello = _Reader(body.take(hello_length))
    if hello.int(1) != 3:                                   # legacy_version 3.x
        raise Refused('TUNNEL_HELLO_MALFORMED')
    hello.take(1 + 32)
    if len(hello.vector(1)) > 32:                           # legacy_session_id
        raise Refused('TUNNEL_HELLO_MALFORMED')
    suites = hello.vector(2)
    if not suites or len(suites) % 2:
        raise Refused('TUNNEL_HELLO_MALFORMED')
    if not hello.vector(1):                                 # legacy_compression_methods
        raise Refused('TUNNEL_HELLO_MALFORMED')
    if hello.done():
        raise Refused('TUNNEL_SNI_ABSENT')                  # no extensions at all
    extensions = _Reader(hello.vector(2))
    if not hello.done():
        raise Refused('TUNNEL_HELLO_MALFORMED')
    seen, names = set(), None
    while not extensions.done():
        kind, data = extensions.int(2), extensions.vector(2)
        if kind in seen:
            raise Refused('TUNNEL_HELLO_MALFORMED')
        seen.add(kind)
        if kind in (EXT_ECH, EXT_ESNI_DRAFT):
            raise Refused('TUNNEL_ECH_REFUSED')
        if kind == EXT_SERVER_NAME:
            names = _host_names(data)
    if names is None:
        raise Refused('TUNNEL_SNI_ABSENT')
    return names


def _host_names(data: bytes) -> str:
    outer = _Reader(data)
    entries = _Reader(outer.vector(2))
    if not outer.done():
        raise Refused('TUNNEL_HELLO_MALFORMED')
    found = []
    while not entries.done():
        kind, name = entries.int(1), entries.vector(2)
        if kind != 0:
            raise Refused('TUNNEL_HELLO_MALFORMED')
        found.append(name)
    if not found:
        raise Refused('TUNNEL_SNI_ABSENT')
    if len(found) != 1:
        raise Refused('TUNNEL_HELLO_MALFORMED')
    try:
        return found[0].decode('ascii')
    except UnicodeDecodeError:
        raise Refused('TUNNEL_SNI_MISMATCH') from None


# ---------------------------------------------------------------- the origin

def resolve_origin(host: str, port: int) -> list:
    """The host's own resolution of the origin (the system resolver): its global addresses, in order. An address
    that is not global (loopback, private, link-local, ...) is refused, so a resolver answer cannot turn the tunnel
    toward the host or its network."""
    found = []
    for family, _, _, _, address in socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM,
                                                       socket.IPPROTO_TCP):
        if family in (socket.AF_INET, socket.AF_INET6) and address[0] not in found:
            found.append(address[0])
    if any(not ipaddress.ip_address(a.split('%')[0]).is_global for a in found):
        raise Refused('TUNNEL_UPSTREAM_REFUSED')
    return found


def connect_origin(address: str, port: int, timeout: float) -> socket.socket:
    return socket.create_connection((address, port), timeout=timeout)


# ---------------------------------------------------------------- the log

class Log:
    """The tunnel's log: one JSON object per line, flushed at once. Only the fields its writers pass, which are
    never payload."""

    def __init__(self, directory: Path):
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.name = f'tunnel-{stamp}-{secrets.token_hex(4)}.jsonl'
        self.path = Path(directory) / self.name
        self._file = open(self.path, 'x', encoding='utf-8', newline='\n')
        self._lock = threading.Lock()

    def write(self, event: str, **fields) -> None:
        line = json.dumps(dict(fields, format=LOG_FORMAT, event=event, at=now_iso()), sort_keys=True)
        with self._lock:
            if not self._file.closed:
                self._file.write(line + '\n')
                self._file.flush()

    def close(self) -> None:
        with self._lock:
            self._file.close()


class MemoryLog:
    """A log kept in memory (tests): the same lines, as objects."""

    def __init__(self):
        self.lines, self.name = [], 'memory'
        self._lock = threading.Lock()

    def write(self, event: str, **fields) -> None:
        with self._lock:
            self.lines.append(json.loads(json.dumps(dict(fields, format=LOG_FORMAT, event=event, at=now_iso()))))

    def close(self) -> None:
        pass


# ---------------------------------------------------------------- the tunnel

class Tunnel:
    """The listener and its connections. RESOLVE(host, port) -> [address] and CONNECT(address, port, timeout) ->
    socket are the outbound seam (tests give a fake origin); they are only ever called with ORIGIN_HOST and
    ORIGIN_PORT, after a CONNECT and its ClientHello are admitted."""

    def __init__(self, port: int, log, *, resolve: Callable = resolve_origin, connect: Callable = connect_origin,
                 head_timeout_s: float = HEAD_TIMEOUT_S, hello_timeout_s: float = HELLO_TIMEOUT_S,
                 idle_ceiling_s: float = IDLE_CEILING_S, max_connections: int = MAX_CONNECTIONS):
        self.port, self.log = port, log
        self.resolve, self.connect = resolve, connect
        self.head_timeout_s, self.hello_timeout_s = head_timeout_s, hello_timeout_s
        self.idle_ceiling_s, self.max_connections = idle_ceiling_s, max_connections
        self.stopping = threading.Event()
        self._lock = threading.Lock()
        self._live: dict[int, threading.Thread] = {}
        self._count = 0
        self._listener: socket.socket | None = None
        self._acceptor: threading.Thread | None = None
        self.address: tuple | None = None

    def start(self) -> tuple:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind((LOOPBACK, self.port))
            sock.listen(16)
            sock.settimeout(STOP_POLL_S)
        except OSError:
            sock.close()
            raise TunnelError('TUNNEL_PORT_IN_USE', f'{LOOPBACK}:{self.port} cannot be bound') from None
        self._listener = sock
        self.address = sock.getsockname()[:2]
        self.log.write('tunnel-start', listener={'address': self.address[0], 'port': self.address[1]},
                       origin=ORIGIN, pid=os.getpid())
        self._acceptor = threading.Thread(target=self._accept, name='provider-tunnel-accept', daemon=True)
        self._acceptor.start()
        return self.address

    def _accept(self) -> None:
        while not self.stopping.is_set():
            try:
                conn, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.stopping.is_set():
                    return
                continue
            with self._lock:
                if self.stopping.is_set():
                    conn.close()
                    return
                self._count += 1
                number, busy = self._count, len(self._live) >= self.max_connections
                if not busy:
                    worker = threading.Thread(target=self._serve, args=(conn, number),
                                              name=f'provider-tunnel-{number}', daemon=True)
                    self._live[number] = worker
            if busy:
                self._answer(conn, 'TUNNEL_BUSY')
                self.log.write('connection', conn=number, target=None, decision='refused', reason='TUNNEL_BUSY',
                               end=None, bytes_up=0, bytes_down=0)
                conn.close()
            else:
                worker.start()

    def open_connections(self) -> int:
        with self._lock:
            return len(self._live)

    def stop(self, by: str = 'stop') -> dict:
        """Close the listener, cut every open connection within one slice and wait for each to log its end (at most
        STOP_CUT_CEILING_S); write the tunnel-stop line."""
        with self._lock:
            self.stopping.set()                  # under the lock: no connection is added after the snapshot
            live = list(self._live.values())
        if self._acceptor is not None:
            self._acceptor.join(STOP_CUT_CEILING_S)
        if self._listener is not None:
            self._listener.close()
        deadline = time.monotonic() + STOP_CUT_CEILING_S
        for worker in live:
            worker.join(max(0.0, deadline - time.monotonic()))
        left = self.open_connections()
        self.log.write('tunnel-stop', stopped_by=by, connections_cut=len(live), connections_left=left)
        return {'stopped_by': by, 'connections_cut': len(live), 'connections_left': left}

    # one connection

    def _serve(self, conn: socket.socket, number: int) -> None:
        state = {'target': None, 'decision': 'refused', 'reason': None, 'end': None, 'up': 0, 'down': 0}
        upstream = None
        try:
            conn.settimeout(STOP_POLL_S)
            head, rest = self._read_head(conn)
            target = parse_head(head)
            state['target'] = logged_target(target)
            check_target(target)
            conn.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            record = self._read_record(conn, rest)
            name = server_name(record)
            if name != ORIGIN_HOST:
                raise Refused('TUNNEL_SNI_MISMATCH')
            upstream, peer = self._open_origin()
            state['decision'] = 'admitted'
            self.log.write('upstream-connect', conn=number, target=ORIGIN, origin=ORIGIN,
                           peer={'address': peer[0], 'port': peer[1]})
            upstream.settimeout(SEND_TIMEOUT_S)
            upstream.sendall(record)
            state['up'] += len(record)
            state['end'] = self._splice(conn, upstream, state)
        except Refused as exc:
            state['reason'] = exc.code
            if exc.code != 'TUNNEL_STOPPED':
                self._answer(conn, exc.code)
            else:
                state['end'] = 'stopped'
        except OSError:
            state['end'] = 'error'
        finally:
            for sock in (upstream, conn):
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            self.log.write('connection', conn=number, target=state['target'], decision=state['decision'],
                           reason=state['reason'], end=state['end'], bytes_up=state['up'], bytes_down=state['down'])
            with self._lock:
                self._live.pop(number, None)

    def _answer(self, conn: socket.socket, code: str) -> None:
        """The HTTP refusal of a refusal before the 200 (a JSON body naming the code); nothing after it."""
        status = REFUSALS[code][0]
        if status is None:
            return
        body = json.dumps({'aieh_refusal': {'code': code, 'remedy': REFUSALS[code][1]}}).encode('ascii')
        head = (f'HTTP/1.1 {status} {REASONS[status]}\r\nContent-Type: application/json\r\n'
                f'Content-Length: {len(body)}\r\nX-AIEH-Tunnel-Refusal: {code}\r\nConnection: close\r\n\r\n')
        try:
            conn.settimeout(SEND_TIMEOUT_S)
            conn.sendall(head.encode('ascii') + body)
        except OSError:
            pass

    def _recv(self, conn: socket.socket, deadline: float, code: str) -> bytes:
        """One read of CONN in slices of STOP_POLL_S: TUNNEL_STOPPED at the stop, CODE past DEADLINE."""
        while True:
            if self.stopping.is_set():
                raise Refused('TUNNEL_STOPPED')
            if time.monotonic() >= deadline:
                raise Refused(code)
            try:
                return conn.recv(CHUNK)
            except socket.timeout:
                continue

    def _read_head(self, conn: socket.socket) -> tuple[bytes, bytes]:
        data, deadline = b'', time.monotonic() + self.head_timeout_s
        while b'\r\n\r\n' not in data:
            if len(data) > HEAD_LIMIT:
                raise Refused('TUNNEL_REQUEST_MALFORMED')
            chunk = self._recv(conn, deadline, 'TUNNEL_REQUEST_MALFORMED')
            if not chunk:
                raise Refused('TUNNEL_REQUEST_MALFORMED')
            data += chunk
        head, _, rest = data.partition(b'\r\n\r\n')
        if len(head) + 4 > HEAD_LIMIT:
            raise Refused('TUNNEL_REQUEST_MALFORMED')
        return head, rest

    def _read_record(self, conn: socket.socket, data: bytes) -> bytes:
        """The first TLS record, whole (header and body), read within the hello timeout; bytes past it are refused
        (a client sends nothing after its ClientHello before the server answers)."""
        deadline = time.monotonic() + self.hello_timeout_s
        while len(data) < 5:
            chunk = self._recv(conn, deadline, 'TUNNEL_HELLO_MALFORMED')
            if not chunk:
                raise Refused('TUNNEL_HELLO_MALFORMED')
            data += chunk
        total = 5 + record_length(data[:5])
        while len(data) < total:
            chunk = self._recv(conn, deadline, 'TUNNEL_HELLO_MALFORMED')
            if not chunk:
                raise Refused('TUNNEL_HELLO_MALFORMED')
            data += chunk
        if len(data) > total:
            more = data[total:]
            if more[:1] == b'\x16':
                raise Refused('TUNNEL_HELLO_FRAGMENTED')
            raise Refused('TUNNEL_HELLO_MALFORMED')
        return data

    def _open_origin(self) -> tuple[socket.socket, tuple]:
        try:
            addresses = self.resolve(ORIGIN_HOST, ORIGIN_PORT)
        except Refused:
            raise
        except OSError:
            raise Refused('TUNNEL_UPSTREAM_FAILED') from None
        for address in addresses or []:
            if self.stopping.is_set():
                raise Refused('TUNNEL_STOPPED')
            try:
                sock = self.connect(address, ORIGIN_PORT, CONNECT_TIMEOUT_S)
            except OSError:
                continue
            return sock, sock.getpeername()[:2]
        raise Refused('TUNNEL_UPSTREAM_FAILED')

    def _splice(self, conn: socket.socket, upstream: socket.socket, state: dict) -> str:
        """Bytes both ways, unread, until both sides end, an error, the idle ceiling or the stop."""
        conn.settimeout(SEND_TIMEOUT_S)
        open_from = {conn: upstream, upstream: conn}
        idle_since = time.monotonic()
        while open_from:
            if self.stopping.is_set():
                return 'stopped'
            readable, _, _ = select.select(list(open_from), [], [], STOP_POLL_S)
            if not readable:
                if time.monotonic() - idle_since >= self.idle_ceiling_s:
                    return 'idle'
                continue
            idle_since = time.monotonic()
            for source in readable:
                data = source.recv(CHUNK)
                sink = open_from[source]
                if not data:
                    del open_from[source]
                    try:
                        sink.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    continue
                sink.sendall(data)
                state['up' if source is conn else 'down'] += len(data)
        return 'closed'


# ---------------------------------------------------------------- the run record and the stop request

def read_run(run_dir: Path) -> dict | None:
    """The run record, or None when there is none; TUNNEL_RUN_RECORD_INVALID when it is not one of ours."""
    path = Path(run_dir) / RUN_NAME
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise TunnelError('TUNNEL_RUN_RECORD_INVALID', 'unreadable') from None
    if not isinstance(record, dict) or record.get('format') != RUN_FORMAT or \
            type(record.get('pid')) is not int or type(record.get('port')) is not int or \
            record.get('address') != LOOPBACK:
        raise TunnelError('TUNNEL_RUN_RECORD_INVALID', 'not an aieh-provider-tunnel-run/1 record')
    return record


def pid_alive(pid: int) -> bool:
    """Whether a process with this id runs (Windows: an open handle whose exit code is STILL_ACTIVE)."""
    if os.name == 'nt':
        handle = _open_process(pid)
        if not handle:
            return False
        try:
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32')
            kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            _close(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _open_process(pid: int):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    return kernel.OpenProcess(0x00100000 | 0x1000, False, pid)      # SYNCHRONIZE | QUERY_LIMITED_INFORMATION


def _close(handle) -> None:
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32')
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle(handle)


def wait_exit(pid: int, ceiling: float) -> bool:
    """Wait on the process's own end (its handle), at most CEILING seconds. True when it has ended."""
    if os.name != 'nt':
        deadline = time.monotonic() + ceiling
        while pid_alive(pid) and time.monotonic() < deadline:
            threading.Event().wait(STOP_POLL_S)
        return not pid_alive(pid)
    handle = _open_process(pid)
    if not handle:
        return True
    try:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32')
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        return kernel.WaitForSingleObject(handle, int(ceiling * 1000)) == 0
    finally:
        _close(handle)


def write_new(path: Path, data: dict) -> None:
    with open(path, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(data, sort_keys=True) + '\n')


# ---------------------------------------------------------------- the commands

@dataclasses.dataclass
class Context:
    """What the commands act on. managed_context() is the Owner's: the managed state and logs directories
    (decision 0009). A test passes its own, whole: never the managed one."""
    run_dir: Callable            # -> the directory of the run record and the stop request
    logs: Callable               # -> the log directory
    out: object
    err: object
    wait: Callable | None = None         # serve's wait (tunnel, run_dir) -> the stop's cause; default wait_for_stop
    resolve: Callable = resolve_origin
    connect: Callable = connect_origin
    allow_ephemeral: bool = False        # tests only: --port 0
    tables: Callable | None = None       # census: -> every row of the operating system's tables


def managed_context() -> Context:
    paths = _load('aieh_paths', REPO / 'integrations' / 'paths' / 'aieh_paths.py')
    try:
        res = paths.resolve()
    except paths.PathsError as exc:
        raise TunnelError('TUNNEL_PATHS_INVALID', str(exc)) from None
    return Context(run_dir=lambda: paths.ensure('state', res, 'provider-tunnel'),
                   logs=lambda: paths.ensure('logs', res, 'provider-tunnel'), out=sys.stdout, err=sys.stderr)


def _load(name: str, path: Path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


class StopFlag:
    """What a signal handler may touch: a plain attribute (never an Event: the main thread acts on it)."""

    def __init__(self):
        self.asked: str | None = None


def install_stop_signals(flag: StopFlag) -> Callable:
    """Handlers for each of STOP_SIGNALS the platform has that only record the signal's name; returns the call that
    restores the previous handlers. Only the main thread can install them (elsewhere a no-op)."""
    if threading.current_thread() is not threading.main_thread():
        return lambda: None
    previous = {}

    def handler(signum, frame):
        if flag.asked is None:
            try:
                flag.asked = signal.Signals(signum).name
            except ValueError:
                flag.asked = f'signal {signum}'
    for name in STOP_SIGNALS:
        number = getattr(signal, name, None)
        if number is not None:
            previous[number] = signal.signal(number, handler)

    def restore():
        if threading.current_thread() is threading.main_thread():
            for number, old in previous.items():
                signal.signal(number, old)
    return restore


def wait_for_stop(tunnel: Tunnel, run_dir: Path, poll_s: float = STOP_POLL_S) -> str:
    """serve's wait, in slices of POLL_S: until a stop signal is recorded or the stop request appears beside the
    run record. Returns what asked."""
    flag = StopFlag()
    restore = install_stop_signals(flag)
    request = Path(run_dir) / STOP_NAME
    idle = threading.Event()             # never set: the slice at which a signal handler runs
    try:
        while True:
            if flag.asked is not None:
                return flag.asked
            if request.exists():
                return 'stop-request'
            idle.wait(poll_s)
    finally:
        restore()


def serve(ctx: Context, port: int) -> dict:
    run_dir = Path(ctx.run_dir())
    current = read_run(run_dir)
    if current is not None:
        if pid_alive(current['pid']):
            raise TunnelError('TUNNEL_ALREADY_RUNNING', f'pid {current["pid"]} on port {current["port"]}')
        (run_dir / RUN_NAME).unlink(missing_ok=True)              # a stale record of an ended tunnel
    (run_dir / STOP_NAME).unlink(missing_ok=True)                 # a request no tunnel took
    log = Log(Path(ctx.logs()))
    try:
        tunnel = Tunnel(port, log, resolve=ctx.resolve, connect=ctx.connect)
        address = tunnel.start()
        record = {'format': RUN_FORMAT, 'pid': os.getpid(), 'address': address[0], 'port': address[1],
                  'origin': ORIGIN, 'log': log.name, 'started_at': now_iso()}
        try:
            write_new(run_dir / RUN_NAME, record)
        except FileExistsError:
            tunnel.stop('start-refused')
            raise TunnelError('TUNNEL_ALREADY_RUNNING', 'a run record appeared while starting') from None
        by = 'error'
        try:
            ctx.err.write(f'provider-tunnel: serving: {json.dumps(record, sort_keys=True)}\n')
            ctx.err.flush()
            by = (ctx.wait or wait_for_stop)(tunnel, run_dir)
        finally:
            result = tunnel.stop(by)
            try:
                if (read_run(run_dir) or {}).get('pid') == os.getpid():
                    (run_dir / RUN_NAME).unlink()
            except (OSError, TunnelError):
                pass
            (run_dir / STOP_NAME).unlink(missing_ok=True)
        return dict(result, port=address[1])
    finally:
        log.close()


def stop(ctx: Context) -> dict:
    run_dir = Path(ctx.run_dir())
    record = read_run(run_dir)
    if record is None or not pid_alive(record['pid']):
        raise TunnelError('TUNNEL_NOT_RUNNING', 'no running tunnel')
    try:
        write_new(run_dir / STOP_NAME, {'asked_at': now_iso(), 'pid': record['pid']})
    except FileExistsError:
        pass                                                      # already asked
    if not wait_exit(record['pid'], STOP_WAIT_S):
        raise TunnelError('TUNNEL_STOP_TIMEOUT', f'pid {record["pid"]} still runs after {STOP_WAIT_S} s')
    return {'result': 'stopped', 'pid': record['pid'], 'port': record['port']}


def log_peers(lines) -> dict:
    """{ORIGIN: sorted upstream peer addresses} from the log's upstream-connect lines."""
    peers = set()
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get('event') == 'upstream-connect' and \
                isinstance(entry.get('peer'), dict) and isinstance(entry['peer'].get('address'), str):
            peers.add(entry['peer']['address'])
    return {ORIGIN: sorted(peers)}


CENSUS_FORMAT = 'aieh-provider-tunnel-census/1'
CENSUS_RULE = (
    'PASS iff, in the operating system\'s TCP and UDP tables (IPv4 and IPv6, by owning process), the tunnel\'s '
    'process (the pid its run record names): (1) listens on exactly 127.0.0.1:<the declared port> (any other '
    'listener, a wildcard or IPv6 listener, or the declared one missing: FAIL); (2) owns no UDP endpoint; (3) owns '
    'no other TCP connection but an inbound one on its listener from a loopback address, or an outbound one to port '
    '443 of an address its log recorded as an upstream peer (upstream-connect lines). Tables that cannot be read: '
    'UNKNOWN, never PASS (inference_census.py\'s judgement, S-03.2).')


def census(ctx: Context) -> dict:
    census_module = _load('aieh_inference_census', HERE / 'inference_census.py')
    run_dir = Path(ctx.run_dir())
    record = read_run(run_dir)
    if record is None or not pid_alive(record['pid']):
        raise TunnelError('TUNNEL_NOT_RUNNING', 'no running tunnel')
    observed_at = now_iso()
    try:
        endpoints, tables = (ctx.tables or census_module.read_tables)(), {'readable': True}
    except census_module.TablesUnavailable as exc:
        endpoints, tables = None, {'readable': False, 'reason': str(exc)[:300]}
    name = record.get('log')
    try:
        if not isinstance(name, str) or not LOG_NAME.fullmatch(name):
            raise ValueError('no log file named')
        peers = log_peers((Path(ctx.logs()) / name).read_text(encoding='utf-8').splitlines())
        log = {'readable': True, 'file': name, 'peers': peers}
    except (OSError, ValueError) as exc:
        peers, log = None, {'readable': False, 'file': name, 'reason': type(exc).__name__}
    if endpoints is None:
        judged = {'verdict': 'UNKNOWN', 'violations': [], 'endpoints': None,
                  'unknown': ['the operating system\'s tables could not be read']}
    else:
        judged = census_module.judge(endpoints, pid=record['pid'], listeners={(LOOPBACK, record['port'])},
                                     origins={ORIGIN: ORIGIN_PORT}, peers=peers)
        tables['rows'] = len(endpoints)
    return {'format': CENSUS_FORMAT, 'verdict': judged['verdict'], 'rule': CENSUS_RULE, 'observed_at': observed_at,
            'tunnel': {'pid': record['pid'], 'port': record['port'], 'log': name}, 'tables': tables, 'log': log,
            'endpoints': judged['endpoints'], 'violations': judged['violations'], 'unknown': judged['unknown']}


def main(argv=None, context: Context | None = None) -> int:
    parser = argparse.ArgumentParser(prog='provider_tunnel.py', description='The native profile\'s provider tunnel '
                                     '(E-05.10). Exit 0 done, 1 failed, 2 refused.')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('serve', help='listen on 127.0.0.1 at the profile\'s declared port until stopped')
    p.add_argument('--profile', required=True, help='the execution profile directory (its profile.json declares '
                                                    'the provider-tunnel endpoint)')
    p.add_argument('--port', type=int, help=argparse.SUPPRESS)        # tests only (Context.allow_ephemeral)
    sub.add_parser('stop', help='ask the running tunnel to stop and wait for it')
    c = sub.add_parser('census', help='observe the running tunnel at the operating system once')
    c.add_argument('--once', action='store_true', required=True)
    args = parser.parse_args(argv)
    err = context.err if context else sys.stderr
    try:
        ctx = context or managed_context()
        if args.command == 'serve':
            port = declared_endpoint(load_profile(args.profile))['host_port']
            if args.port is not None:
                if not ctx.allow_ephemeral:
                    raise TunnelError('TUNNEL_PROFILE_INVALID', 'the port is the profile\'s declaration only')
                port = args.port
            result = serve(ctx, port)
        elif args.command == 'stop':
            result = stop(ctx)
        else:
            result = census(ctx)
    except TunnelError as exc:
        err.write(f'provider-tunnel: {exc}\n')
        return 2
    ctx.out.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
    if args.command == 'census':
        ctx.err.write(f'provider-tunnel: census {result["verdict"]}\n')
        return 0 if result['verdict'] == 'PASS' else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
