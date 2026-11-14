"""The inference broker's live census (plan leaf S-03.2, before the first provider call; the OA-12 package section 3
assumption 3 and section 5 item 5).

The broker's egress is a control in its own code (decision 0015 section 5.1), not an operating-system boundary.
This command observes, at the operating system, what the running broker's process listens on and is connected to,
and judges that against the broker's configuration and its own audit. It starts no process: on Windows it reads
the per-process TCP tables (IPv4 and IPv6, GetExtendedTcpTable with TCP_TABLE_OWNER_PID_ALL) and UDP tables
(GetExtendedUdpTable with UDP_TABLE_OWNER_PID) of iphlpapi through ctypes. Elsewhere, or when the API fails, the
tables are unreadable and the verdict is UNKNOWN, never PASS.

What it compares:

- the broker's process id, from the broker itself (its control status answer's pid; the start receipt carries it
  too);
- the configuration (components.inference_broker of config.yml, through the broker's own loader): the two listener
  ports and each family's upstream origin;
- the broker's own record of its upstream connections: the audit's upstream-connect lines, which the broker's
  connector writes at connect time with the connection's peer address (IP and port, no secret), per origin.

The decision rule, fixed here before any run and copied into every record, is CENSUS_RULE. DNS resolution happens
in the system resolver and is not observed (DNS_NOTE): the census sees connections, not name lookups.

  <tools python> -I -B integrations/inference/inference_census.py --once

prints one JSON record (aieh-inference-census/1) on standard output. Exit 0 PASS, 1 FAIL or UNKNOWN, 2 refused (a
stable code: the configuration, the control listener's status or its answer). It reads the managed config.yml, the
broker's control listener on 127.0.0.1 and the broker's audit file in the managed logs directory; it writes
nothing. Standard library only.
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
import struct
import sys
import time
from pathlib import Path
from typing import Callable

HERE = Path(os.path.realpath(__file__)).parent


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


control = _load('aieh_inference_control', HERE / 'inference_control.py')
broker = control.broker

CENSUS_FORMAT = 'aieh-inference-census/1'
CONNECT_EVENT = 'upstream-connect'      # the broker's audit line at each upstream connection (its peer address)
AUDIT_NAME = re.compile(r'audit-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.jsonl')
AUDIT_LIMIT = 256 * 1024 * 1024
# Fixed before any run (the engineering manager's ruling, S-03.2); copied into every record.
CENSUS_RULE = (
    'PASS iff, in the operating system\'s TCP and UDP tables (IPv4 and IPv6, by owning process), the broker\'s '
    'process (the pid its own control status answer names): (1) listens on exactly 127.0.0.1:<control_port> and '
    '127.0.0.1:<inference_port> of the configuration (any other listener, a wildcard address, another port or an '
    'IPv6 listener, and a configured listener missing: FAIL); (2) owns no UDP endpoint (else FAIL); (3) owns no '
    'other TCP connection but an inbound one on one of those two listeners whose remote address is loopback, or an '
    'outbound one to the port of a configured upstream origin whose remote IP is among the peers the broker\'s audit '
    'recorded (upstream-connect lines) for that origin (else FAIL). The broker\'s status naming listeners other than '
    'the configured ones is FAIL. Tables that cannot be read (a platform other than Windows, or the API failing): '
    'UNKNOWN, never PASS; an outbound connection to an origin\'s port while the audit cannot be read: UNKNOWN unless '
    'another check fails. FAIL when any check fails; otherwise UNKNOWN when any is UNKNOWN; otherwise PASS.')
DNS_NOTE = ('DNS resolution happens in the system resolver (the broker\'s https connector resolves the origin\'s '
            'host name through it) and is not observed: the census sees the broker\'s connections, not its name '
            'lookups.')
LIMITS = ('The tables are read first and the audit after them, so a connection the census sees has its '
          'upstream-connect line unless the census ran in the instant between the connect and that line (it is then '
          'FAIL, never PASS). The census is one moment: a connection opened and closed between two censuses is not '
          'seen; the broker\'s audit is the continuous record.')

CODES = {
    'CENSUS_CONFIG_INVALID': 'fix components.inference_broker of config.yml (inference_broker.py config shows the '
                             'refusal), and give both listener ports',
    'CENSUS_BROKER_UNREACHABLE': 'start the broker (an Owner act) and check components.inference_broker.control_port',
    'CENSUS_STATUS_INVALID': 'the control listener\'s status does not name the broker\'s pid, its listeners or its '
                             'audit file: run the broker built with the census (S-03.2)',
}


class CensusRefused(Exception):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}. Remedy: {CODES[code]}.')


class TablesUnavailable(Exception):
    """The operating system's tables could not be read: the verdict is UNKNOWN."""


# ---------------------------------------------------------------- the operating system's tables

TCP_STATES = {1: 'CLOSED', 2: 'LISTEN', 3: 'SYN_SENT', 4: 'SYN_RCVD', 5: 'ESTABLISHED', 6: 'FIN_WAIT1',
              7: 'FIN_WAIT2', 8: 'CLOSE_WAIT', 9: 'CLOSING', 10: 'LAST_ACK', 11: 'TIME_WAIT', 12: 'DELETE_TCB'}
AF_INET, AF_INET6 = 2, 23                 # the Windows address families
TCP_TABLE_OWNER_PID_ALL, UDP_TABLE_OWNER_PID = 5, 1
NO_ERROR, ERROR_INSUFFICIENT_BUFFER = 0, 122
# The row size of each table: MIB_TCPROW_OWNER_PID, MIB_TCP6ROW_OWNER_PID, MIB_UDPROW_OWNER_PID and
# MIB_UDP6ROW_OWNER_PID; every table is a DWORD count followed by its rows.
ROW_SIZES = {('tcp', 4): 24, ('tcp', 6): 56, ('udp', 4): 12, ('udp', 6): 28}


@dataclasses.dataclass(frozen=True)
class Endpoint:
    """One row of a table: protocol tcp or udp, IP version 4 or 6, the TCP state (None for UDP), the local and
    remote address and port (the remote ones None for UDP) and the owning process id. Addresses are canonical
    text (ipaddress), without a scope."""
    protocol: str
    version: int
    state: str | None
    local_address: str
    local_port: int
    remote_address: str | None
    remote_port: int | None
    pid: int

    def describe(self) -> dict:
        return {'protocol': self.protocol, 'version': self.version, 'state': self.state,
                'local': f'{_host(self.local_address)}:{self.local_port}',
                'remote': None if self.remote_address is None else f'{_host(self.remote_address)}:{self.remote_port}'}


def _host(address: str) -> str:
    return f'[{address}]' if ':' in address else address


def _port(raw: bytes) -> int:
    """A port held in network byte order in the low 16 bits of a DWORD."""
    return struct.unpack('>H', raw[:2])[0]


def _address(raw: bytes) -> str:
    return ipaddress.ip_address(raw).compressed


def canonical(address: str) -> str:
    """ADDRESS as canonical text (no scope; an IPv4-mapped IPv6 address as its IPv4 address)."""
    parsed = ipaddress.ip_address(str(address).split('%', 1)[0])
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return parsed.compressed


def parse_table(protocol: str, version: int, data: bytes) -> list:
    """The rows of one table's bytes (TablesUnavailable when they are not a whole table)."""
    size = ROW_SIZES[(protocol, version)]
    if len(data) < 4:
        raise TablesUnavailable(f'the {protocol}{version} table is shorter than its count')
    (count,) = struct.unpack_from('<I', data, 0)
    if len(data) < 4 + count * size:
        raise TablesUnavailable(f'the {protocol}{version} table holds fewer than its {count} rows')
    rows = []
    for index in range(count):
        row = data[4 + index * size:4 + (index + 1) * size]
        if (protocol, version) == ('tcp', 4):
            state, pid = struct.unpack_from('<I', row, 0)[0], struct.unpack_from('<I', row, 20)[0]
            rows.append(Endpoint('tcp', 4, TCP_STATES.get(state, f'state {state}'), _address(row[4:8]),
                                 _port(row[8:10]), _address(row[12:16]), _port(row[16:18]), pid))
        elif (protocol, version) == ('tcp', 6):
            state, pid = struct.unpack_from('<I', row, 48)[0], struct.unpack_from('<I', row, 52)[0]
            rows.append(Endpoint('tcp', 6, TCP_STATES.get(state, f'state {state}'), _address(row[0:16]),
                                 _port(row[20:22]), _address(row[24:40]), _port(row[44:46]), pid))
        elif (protocol, version) == ('udp', 4):
            rows.append(Endpoint('udp', 4, None, _address(row[0:4]), _port(row[4:6]), None, None,
                                 struct.unpack_from('<I', row, 8)[0]))
        else:
            rows.append(Endpoint('udp', 6, None, _address(row[0:16]), _port(row[20:22]), None, None,
                                 struct.unpack_from('<I', row, 24)[0]))
    return rows


def _fetch(function, family: int, table_class: int) -> bytes:
    """One table's bytes from FUNCTION (GetExtendedTcpTable or GetExtendedUdpTable), grown until it fits."""
    import ctypes
    from ctypes import wintypes
    size = wintypes.DWORD(0)
    result = function(None, ctypes.byref(size), False, family, table_class, 0)
    for _ in range(8):                           # a table that keeps growing between the calls is unreadable
        if result not in (NO_ERROR, ERROR_INSUFFICIENT_BUFFER):
            raise TablesUnavailable(f'the API answered error {result}')
        buffer = ctypes.create_string_buffer(max(int(size.value), 4))
        result = function(buffer, ctypes.byref(size), False, family, table_class, 0)
        if result == NO_ERROR:
            return buffer.raw
    raise TablesUnavailable('the table kept growing while it was read')


def read_tables(platform: str | None = None, library: Callable | None = None) -> list:
    """Every row of the four tables (TCP and UDP, IPv4 and IPv6), of every process: Windows only, through ctypes
    (no process is started). TablesUnavailable elsewhere or when the API fails. LIBRARY stands in for loading
    iphlpapi in tests."""
    platform = sys.platform if platform is None else platform
    if platform != 'win32':
        raise TablesUnavailable(f'the per-process tables are read on Windows only (this is {platform})')
    try:
        import ctypes
        from ctypes import wintypes
        iphlpapi = library() if library is not None else ctypes.WinDLL('iphlpapi', use_last_error=True)
        functions = {}
        for name in ('GetExtendedTcpTable', 'GetExtendedUdpTable'):
            function = getattr(iphlpapi, name)
            function.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL, wintypes.ULONG,
                                 ctypes.c_int, wintypes.ULONG)
            function.restype = wintypes.DWORD
            functions[name] = function
        rows = []
        for protocol, name, table_class in (('tcp', 'GetExtendedTcpTable', TCP_TABLE_OWNER_PID_ALL),
                                            ('udp', 'GetExtendedUdpTable', UDP_TABLE_OWNER_PID)):
            for version, family in ((4, AF_INET), (6, AF_INET6)):
                rows += parse_table(protocol, version, _fetch(functions[name], family, table_class))
        return rows
    except TablesUnavailable:
        raise
    except (OSError, AttributeError, ValueError, TypeError) as exc:
        raise TablesUnavailable(f'the tables could not be read ({type(exc).__name__})') from None


# ---------------------------------------------------------------- the broker's own record

def audit_peers(lines) -> tuple[dict, int]:
    """({origin: sorted peer addresses}, the number of upstream-connect lines) of an audit's lines (text). A line
    that is not one JSON object, or not of the event, is skipped."""
    peers: dict[str, set] = {}
    count = 0
    for line in lines:
        try:
            record = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(record, dict) or record.get('event') != CONNECT_EVENT:
            continue
        origin, peer = record.get('origin'), record.get('peer')
        if not isinstance(origin, str) or not isinstance(peer, dict) or not isinstance(peer.get('address'), str):
            continue
        try:
            address = canonical(peer['address'])
        except ValueError:
            continue
        peers.setdefault(origin, set()).add(address)
        count += 1
    return {origin: sorted(addresses) for origin, addresses in sorted(peers.items())}, count


# ---------------------------------------------------------------- the judgement

def _loopback(address: str | None) -> bool:
    try:
        return address is not None and ipaddress.ip_address(canonical(address)).is_loopback
    except ValueError:
        return False


def judge(endpoints, *, pid: int, listeners: set, origins: dict, peers: dict | None) -> dict:
    """The decision rule (CENSUS_RULE) over ENDPOINTS (every process's rows): LISTENERS the configured
    {(address, port)}, ORIGINS {origin text: port} of the configured upstreams, PEERS the audit's {origin: [peer
    address]} (None: the audit could not be read). Returns {verdict, violations, unknown, endpoints}: the pid's
    endpoints, each with its class and whether it passes."""
    violations, unknown, classified, seen = [], [], [], set()
    for endpoint in endpoints:
        if endpoint.pid != pid:
            continue
        entry = endpoint.describe()
        local = (endpoint.local_address, endpoint.local_port)
        if endpoint.protocol == 'udp':
            entry.update(kind='udp endpoint', ok=False)
            violations.append(f'a UDP endpoint {entry["local"]}')
        elif endpoint.state == 'LISTEN':
            seen.add(local)
            ok = endpoint.version == 4 and local in listeners
            entry.update(kind='listener', ok=ok)
            if not ok:
                violations.append(f'a listener that is not configured: {entry["local"]}')
        elif local in listeners:
            ok = _loopback(endpoint.remote_address)
            entry.update(kind='inbound', ok=ok)
            if not ok:
                violations.append(f'an inbound connection from a remote address that is not loopback: '
                                  f'{entry["remote"]} to {entry["local"]}')
        else:
            matching = sorted(origin for origin, port in origins.items() if port == endpoint.remote_port)
            remote = canonical(endpoint.remote_address)
            if matching and peers is None:
                entry.update(kind='outbound', ok=None, origins=matching)
                unknown.append(f'an outbound connection to {entry["remote"]} while the audit cannot be read')
            else:
                recorded = [origin for origin in matching if remote in (peers or {}).get(origin, ())]
                entry.update(kind='outbound', ok=bool(recorded), origins=recorded or matching)
                if not recorded:
                    why = 'no configured origin\'s port' if not matching else \
                        'a remote address the broker\'s audit did not record for that origin'
                    violations.append(f'an outbound connection to {entry["remote"]}: {why}')
        classified.append(entry)
    for address, port in sorted(listeners - seen):
        violations.append(f'a configured listener is missing: {_host(address)}:{port}')
    verdict = 'FAIL' if violations else 'UNKNOWN' if unknown else 'PASS'
    return {'verdict': verdict, 'violations': violations, 'unknown': unknown, 'endpoints': classified}


def _status_view(status) -> tuple[int, dict, str]:
    """(pid, {name: port} of the status's listeners, the audit file's name), or CENSUS_STATUS_INVALID."""
    if not isinstance(status, dict):
        raise CensusRefused('CENSUS_STATUS_INVALID', 'the status answer is not an object')
    pid = status.get('pid')
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise CensusRefused('CENSUS_STATUS_INVALID', 'the status answer names no pid')
    listeners = status.get('listeners')
    ports = {}
    for name in ('control', 'inference'):
        entry = listeners.get(name) if isinstance(listeners, dict) else None
        port = entry.get('port') if isinstance(entry, dict) else None
        if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536 \
                or entry.get('address') != broker.LOOPBACK:
            raise CensusRefused('CENSUS_STATUS_INVALID', f'the status answer names no {name} listener on '
                                                         f'{broker.LOOPBACK}')
        ports[name] = port
    audit = status.get('audit')
    name = audit.get('file') if isinstance(audit, dict) else None
    if not isinstance(name, str) or not AUDIT_NAME.fullmatch(name):
        raise CensusRefused('CENSUS_STATUS_INVALID', 'the status answer names no audit file')
    return pid, ports, name


def census(config, status, *, read_tables: Callable, read_audit: Callable, clock: Callable = time.time) -> dict:
    """One census of the broker CONFIG configures, whose control status answer is STATUS: the tables first
    (READ_TABLES, TablesUnavailable: UNKNOWN), then the audit (READ_AUDIT(file name) -> its lines; OSError or
    ValueError: unreadable). Returns the record (aieh-inference-census/1)."""
    pid, ports, audit_file = _status_view(status)
    configured = {'control': config.control_port, 'inference': config.inference_port}
    violations = [f'the broker\'s status names the {name} listener on port {ports[name]}, the configuration '
                  f'{configured[name]}' for name in ('control', 'inference')
                  if configured[name] not in (0, ports[name])]     # 0: an ephemeral port (tests only)
    expected = {(broker.LOOPBACK, port if port else ports[name]) for name, port in configured.items()}
    origins = {family.upstream.text(): family.upstream.port for family in config.families.values()
               if family.upstream is not None}
    observed_at = datetime.datetime.fromtimestamp(clock(), datetime.timezone.utc).isoformat(timespec='milliseconds')
    try:
        endpoints, tables = read_tables(), {'readable': True}
    except TablesUnavailable as exc:
        endpoints, tables = None, {'readable': False, 'reason': str(exc)[:300]}
    try:
        peers, lines = audit_peers(read_audit(audit_file))
        audit = {'readable': True, 'file': audit_file, 'upstream_connect_lines': lines, 'peers': peers}
    except (OSError, ValueError) as exc:
        peers, audit = None, {'readable': False, 'file': audit_file, 'reason': type(exc).__name__}
    if endpoints is None:
        verdict = 'FAIL' if violations else 'UNKNOWN'
        judged = {'violations': violations, 'unknown': ['the operating system\'s tables could not be read'],
                  'endpoints': None}
    else:
        judged = judge(endpoints, pid=pid, listeners=expected, origins=origins, peers=peers)
        judged['violations'] = violations + judged['violations']
        verdict = 'FAIL' if judged['violations'] else 'UNKNOWN' if judged['unknown'] else 'PASS'
        tables['rows'] = len(endpoints)
    return {'format': CENSUS_FORMAT, 'verdict': verdict, 'rule': CENSUS_RULE, 'dns': DNS_NOTE, 'limits': LIMITS,
            'observed_at': observed_at,
            'broker': {'pid': pid, 'listeners': ports, 'audit_file': audit_file},
            'expected': {'listeners': sorted(f'{a}:{p}' for a, p in expected), 'origins': origins},
            'tables': tables, 'audit': audit, 'endpoints': judged['endpoints'],
            'violations': judged['violations'], 'unknown': judged['unknown']}


# ---------------------------------------------------------------- the command

@dataclasses.dataclass
class Context:
    """What the command acts on. managed_context() is the Owner's: config.yml, the control listener on 127.0.0.1,
    the managed logs directory, the operating system's tables. A test passes its own, whole."""
    component: Callable          # -> the raw components.inference_broker (or None)
    status: Callable             # control port -> the control listener's status answer (ControlError: refused)
    logs: Callable               # -> the broker's audit directory
    tables: Callable             # -> every row of the tables (TablesUnavailable: UNKNOWN)
    out: object
    err: object
    allow_ephemeral: bool = False
    clock: Callable = time.time


def managed_context() -> Context:
    res = broker.paths.resolve()
    return Context(component=lambda: res.components.get(broker.COMPONENT),
                   status=lambda port: control.ControlClient(port).status(),
                   logs=lambda: broker.paths.ensure('logs', res, 'inference'), tables=read_tables, out=sys.stdout,
                   err=sys.stderr)


def _read_audit(directory: Path, name: str) -> list:
    path = Path(directory) / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > AUDIT_LIMIT:
        raise OSError('not a regular audit file within its size limit')
    return path.read_text(encoding='utf-8').splitlines()


def once(ctx: Context) -> dict:
    """One census of the configured broker (CensusRefused before anything is observed)."""
    try:
        config = broker.load_config(ctx.component(), allow_ephemeral=ctx.allow_ephemeral)
    except broker.InferenceError as exc:
        raise CensusRefused('CENSUS_CONFIG_INVALID', f'{exc.code}: {exc.detail}') from None
    if config.control_port is None or config.inference_port is None:
        raise CensusRefused('CENSUS_CONFIG_INVALID', 'a listener port is not configured')
    try:
        status = ctx.status(config.control_port)
    except control.ControlError as exc:
        raise CensusRefused('CENSUS_BROKER_UNREACHABLE', f'the control listener\'s status: {exc.code}') from None
    return census(config, status, read_tables=ctx.tables, read_audit=lambda name: _read_audit(ctx.logs(), name),
                  clock=ctx.clock)


EXIT = {'PASS': 0, 'FAIL': 1, 'UNKNOWN': 1}


def main(argv=None, context: Context | None = None) -> int:
    parser = argparse.ArgumentParser(prog='inference_census.py', description='The inference broker\'s live census '
                                     '(S-03.2). Exit 0 PASS, 1 FAIL or UNKNOWN, 2 refused.')
    parser.add_argument('--once', action='store_true', required=True,
                        help='observe the configured broker once and print the record')
    parser.parse_args(argv)
    try:
        ctx = context or managed_context()
        record = once(ctx)
    except CensusRefused as exc:
        (context.err if context else sys.stderr).write(f'inference-census: {exc}\n')
        return 2
    except broker.paths.PathsError as exc:
        (context.err if context else sys.stderr).write(f'inference-census: {exc}\n')
        return 2
    ctx.out.write(json.dumps(record, indent=2, sort_keys=True) + '\n')
    ctx.err.write(f'inference-census: {record["verdict"]}\n')
    return EXIT[record['verdict']]


if __name__ == '__main__':
    sys.exit(main())
