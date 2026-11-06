#!/usr/bin/python3
"""AIEH netprobe: the TEST-ONLY guest-root network probe (plan leaf F-03.3.2).

Never part of ordinary operation. Only ``tools/guest.py netprobe`` uses this file: it
checks the file's sha256 against its pin, replaces the one PARAMS_JSON line, and puts
the result into a second user-data part of a disposable validation guest's seed.
cloud-init runs it once, as root, at first boot. The ordinary ``create`` never reads it.

Authority: decision 0003, "Owner authorization: network validation (2026-11-06)".
Guest root is used only inside a disposable test VM, and only to configure the
guest's own routes, resolvers, interfaces and a network namespace. Nothing is
installed; nothing outside the guest is changed.

In order:
1. records interfaces, routes, neighbours and NIC counters (``before``);
2. as root: a default route via the SLIRP gateway 10.0.2.2; resolvers 10.0.2.3 and
   public ones; an IPv6 address, a default IPv6 route and a static neighbour entry
   that sends IPv6 frames to the SLIRP gateway's MAC; a static neighbour for one unused
   on-link address (``after_setup``);
3. the positive control: the HELLO / NONCE / ECHO exchange with the host's test
   listener through the one guestfwd address;
4. every other probe (IPv4 direct, ICMP, DNS, host loopback through SLIRP, the host's
   LAN and IPv6 addresses, the decoys, the listener's host port), concurrently;
5. a container-like network namespace (a veth pair, guest NAT by iptables MASQUERADE,
   as Docker's default bridge does) from which the positive control and the IPv4 probes
   are repeated;
6. records the state again and writes /var/lib/aieh-netprobe/result.json (mode 0644,
   readable by the agent account).

It reports raw results only. The verdict is the host's (tools/guest.py, profiles P7).
"""
import errno
import ipaddress
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

PARAMS_JSON = '{}'  # @@AIEH-NETPROBE-PARAMS@@ (tools/guest.py replaces this line)

SCHEMA = 'ai-engineering-harness/profiles/netprobe-result/v1'
OUT_DIR = '/var/lib/aieh-netprobe'
MARKER = 'AIEH-NETPROBE'
SLIRP_NET = '10.0.2.0/24'
SLIRP_GW = '10.0.2.2'
SLIRP_DNS = '10.0.2.3'
UNUSED_ONLINK = '10.0.2.101'          # on-link, no guestfwd: SLIRP must not accept it
V6_ADDR, V6_GW, V6_DNS = 'fec0::15', 'fec0::2', 'fec0::3'   # SLIRP's IPv6 defaults
NETNS, VETH_HOST, VETH_NS = 'aieh-np', 'aieh-h', 'aieh-c'
NS_HOST_ADDR, NS_ADDR, NS_PREFIX = '192.168.77.1', '192.168.77.2', 30
NS_SUBNET = '192.168.77.0/30'
QUERY_NAME = 'deb.debian.org'
HOST_PORT_NAMES = ('ssh', 'qmp', 'decoy_tcp', 'listener')
CONNECT_S = 4.0
REPLY_S = 3.0
EXCHANGE_S = 10.0
LABEL = re.compile(r'^[a-z]{1,16}$')
NONCE = re.compile(r'^[0-9a-f]{32}$')


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def run(argv, timeout=60):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        return {'argv': argv, 'rc': r.returncode, 'out': r.stdout.strip(), 'err': r.stderr.strip()}
    except FileNotFoundError as exc:
        return {'argv': argv, 'rc': None, 'out': '', 'err': f'not found: {exc}'}
    except subprocess.TimeoutExpired:
        return {'argv': argv, 'rc': None, 'out': '', 'err': f'timeout after {timeout} s'}


def read_text(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as handle:
            return handle.read().strip()
    except OSError as exc:
        return f'unreadable: {exc}'


# ---------------------------------------------------------------- probes


def oserror_result(exc):
    """'refused', 'timeout', 'unreachable', or the errno name."""
    if isinstance(exc, ConnectionRefusedError):
        return 'refused'
    if isinstance(exc, (socket.timeout, TimeoutError)) or exc.errno == errno.ETIMEDOUT:
        return 'timeout'
    if exc.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH):
        return 'unreachable'
    return errno.errorcode.get(exc.errno, f'oserror-{exc.errno}')


def family(host):
    return socket.AF_INET6 if ':' in host else socket.AF_INET


def tcp(host, port):
    sock = socket.socket(family(host), socket.SOCK_STREAM)
    sock.settimeout(CONNECT_S)
    try:
        try:
            sock.connect((host, port))
        except OSError as exc:
            return {'result': oserror_result(exc), 'detail': str(exc)}
        out = {'result': 'connected'}
        try:
            sock.settimeout(1.0)
            out['banner'] = sock.recv(64).decode('ascii', 'replace')
        except OSError as exc:
            out['banner_error'] = type(exc).__name__
        return out
    finally:
        sock.close()


def dns_query(qid):
    query = struct.pack('>HHHHHH', qid, 0x0100, 1, 0, 0, 0)
    for label in QUERY_NAME.split('.'):
        query += bytes([len(label)]) + label.encode('ascii')
    return query + b'\x00' + struct.pack('>HH', 1, 1)


def udp_dns(server):
    sock = socket.socket(family(server), socket.SOCK_DGRAM)
    sock.settimeout(REPLY_S)
    try:
        sock.sendto(dns_query(0x5a5a), (server, 53))
        data, peer = sock.recvfrom(1500)
        return {'result': 'reply', 'detail': f'{len(data)} bytes from {peer[0]}'}
    except OSError as exc:
        result = oserror_result(exc)
        return {'result': 'no-reply' if result == 'timeout' else result, 'detail': str(exc)}
    finally:
        sock.close()


def tcp_dns(server):
    sock = socket.socket(family(server), socket.SOCK_STREAM)
    sock.settimeout(CONNECT_S)
    try:
        try:
            sock.connect((server, 53))
        except OSError as exc:
            return {'result': oserror_result(exc), 'detail': str(exc)}
        query = dns_query(0x5a5b)
        try:
            sock.sendall(struct.pack('>H', len(query)) + query)
            sock.settimeout(REPLY_S)
            return {'result': 'connected', 'detail': f'reply bytes {len(sock.recv(2))}'}
        except OSError as exc:
            return {'result': 'connected', 'detail': f'after connect: {type(exc).__name__}'}
    finally:
        sock.close()


def udp_send(host, port, scope):
    """One datagram to host:port; the host-side decoy log is the decisive record."""
    sock = socket.socket(family(host), socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    try:
        sock.sendto(f'{MARKER} UDP {scope}\n'.encode('ascii'), (host, port))
        data, peer = sock.recvfrom(512)
        return {'result': 'reply', 'detail': f'{len(data)} bytes from {peer[0]}'}
    except OSError as exc:
        result = oserror_result(exc)
        return {'result': 'no-reply' if result == 'timeout' else result, 'detail': str(exc)}
    finally:
        sock.close()


def ping(host):
    r = run(['ping', '-n', '-c', '2', '-W', '2', host], timeout=20)
    text = (r['out'] + '\n' + r['err']).strip()
    tail = [line for line in text.splitlines() if line.strip()][-2:]
    if r['rc'] == 0:
        result = 'reply'
    elif r['rc'] == 1:
        result = 'no-reply'
    elif 'unreachable' in text.lower():
        result = 'unreachable'
    else:
        result = 'error'
    return {'result': result, 'detail': ' | '.join(tail), 'rc': r['rc']}


def resolve(name):
    """The guest's own resolver path (NSS; systemd-resolved retries for a long time)."""
    r = run(['getent', 'ahosts', name], timeout=40)
    if r['rc'] == 0:
        return {'result': 'resolved', 'detail': ' | '.join(r['out'].splitlines()[:2])}
    if r['rc'] == 2:
        return {'result': 'not-found', 'detail': 'getent rc 2'}
    if r['rc'] is None and r['err'].startswith('timeout after'):
        return {'result': 'timeout', 'detail': f'getent: {r["err"]}'}
    return {'result': 'error', 'detail': f'getent rc {r["rc"]} {r["err"]}'}


def read_line(sock, deadline):
    buf = b''
    while b'\n' not in buf:
        if len(buf) > 512:
            raise ValueError('overlong line')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('no complete line before the deadline')
        sock.settimeout(remaining)
        chunk = sock.recv(512)
        if not chunk:
            raise ConnectionError('closed by the peer')
        buf += chunk
    return buf.split(b'\n', 1)[0].decode('ascii', 'replace')


def exchange(addr, port, label):
    """The positive control: HELLO, then echo the listener's nonce, then expect OK."""
    out = {'target': f'{addr}:{port}', 'label': label, 'lines': []}
    sock = socket.socket(family(addr), socket.SOCK_STREAM)
    sock.settimeout(CONNECT_S)
    try:
        try:
            sock.connect((addr, port))
        except OSError as exc:
            out.update(result=oserror_result(exc), detail=str(exc))
            return out
        try:
            deadline = time.monotonic() + EXCHANGE_S
            hello = f'{MARKER} HELLO {label}'
            sock.sendall((hello + '\n').encode('ascii'))
            out['lines'].append('> ' + hello)
            line = read_line(sock, deadline)
            out['lines'].append('< ' + line)
            parts = line.split()
            if len(parts) != 3 or parts[:2] != [MARKER, 'NONCE'] or not NONCE.match(parts[2]):
                out['result'] = 'connected-no-exchange'
                return out
            out['nonce'] = parts[2]
            echo = f'{MARKER} ECHO {parts[2]}'
            sock.sendall((echo + '\n').encode('ascii'))
            out['lines'].append('> ' + echo)
            line = read_line(sock, deadline)
            out['lines'].append('< ' + line)
            out['result'] = 'exchanged' if line == f'{MARKER} OK {label}' else 'connected-no-exchange'
        except (OSError, ValueError) as exc:
            out.update(result='connected-no-exchange', detail=f'{type(exc).__name__}: {exc}')
        return out
    finally:
        sock.close()


def probe_table(params, scope):
    """Every denied path, plus one informational row. 'scope' is 'guest' or 'netns'."""
    ports = params['host_ports']
    gf = params['guestfwd']
    rows = []

    def add(kind, host, port, cls, label=None, expect='denied'):
        shown = f'[{host}]' if ':' in host else host
        pid = f'{kind} {shown}' + (f':{port}' if port is not None else '') + \
            (f' ({label})' if label else '')
        rows.append({'id': pid, 'kind': kind, 'host': host, 'port': port, 'class': cls,
                     'expect': expect})

    for host, port in params['public_ipv4_tcp']:
        add('tcp', host, port, 'ipv4-direct')
    if params.get('debian_ipv4'):
        for port in (80, 443):
            add('tcp', params['debian_ipv4'], port, 'ipv4-direct', 'deb.debian.org')
    for host in params['public_ipv4_icmp']:
        add('icmp', host, None, 'ipv4-direct')
    for server in [SLIRP_DNS] + params['public_dns_ipv4']:
        add('udp-dns', server, 53, 'dns')
        add('tcp-dns', server, 53, 'dns')
    add('resolve', QUERY_NAME, None, 'dns')
    for name in HOST_PORT_NAMES:
        add('tcp', SLIRP_GW, ports[name], 'host-loopback', name)
    add('udp', SLIRP_GW, ports['decoy_udp'], 'host-loopback', 'decoy_udp')
    add('tcp', gf['addr'], gf['port'] + 1, 'allowlist-edge', 'guestfwd address, other port')
    add('tcp', UNUSED_ONLINK, gf['port'], 'allowlist-edge', 'other address, guestfwd port')
    for ip in params['host_ipv4']:
        for name in HOST_PORT_NAMES:
            add('tcp', ip, ports[name], 'host-lan', name)
        add('udp', ip, ports['decoy_udp'], 'host-lan', 'decoy_udp')
        add('icmp', ip, None, 'host-lan')
    # SLIRP itself answers an echo request to its virtual gateway; no host socket is used
    add('icmp', SLIRP_GW, None, 'slirp-internal', expect='info')
    if scope == 'guest':
        for host, port in params['public_ipv6_tcp']:
            add('tcp', host, port, 'ipv6')
        if params.get('debian_ipv6'):
            add('tcp', params['debian_ipv6'], 443, 'ipv6', 'deb.debian.org')
        for host in params['public_ipv6_icmp']:
            add('icmp', host, None, 'ipv6')
        for server in [V6_DNS] + params['public_dns_ipv6']:
            add('udp-dns', server, 53, 'ipv6')
        for name in HOST_PORT_NAMES:
            add('tcp', V6_GW, ports[name], 'ipv6', name)
        add('udp', V6_GW, ports['decoy_udp'], 'ipv6', 'decoy_udp')
        for ip in params['host_ipv6']:
            for name in HOST_PORT_NAMES:
                add('tcp', ip, ports[name], 'ipv6', name)
    return rows


def run_probe(row, scope):
    started = time.monotonic()
    kind = row['kind']
    try:
        if kind == 'tcp':
            result = tcp(row['host'], row['port'])
        elif kind == 'tcp-dns':
            result = tcp_dns(row['host'])
        elif kind == 'udp-dns':
            result = udp_dns(row['host'])
        elif kind == 'udp':
            result = udp_send(row['host'], row['port'], scope)
        elif kind == 'icmp':
            result = ping(row['host'])
        elif kind == 'resolve':
            result = resolve(row['host'])
        else:
            result = {'result': 'error', 'detail': f'unknown kind {kind}'}
    except Exception as exc:          # a probe bug is reported, never a pass
        result = {'result': 'error', 'detail': f'{type(exc).__name__}: {exc}'}
    return dict(row, **result, seconds=round(time.monotonic() - started, 2))


def scope_run(params, scope):
    gf = params['guestfwd']
    positive = exchange(gf['addr'], gf['port'], scope)
    rows = probe_table(params, scope)
    with ThreadPoolExecutor(max_workers=16) as pool:
        probes = list(pool.map(lambda row: run_probe(row, scope), rows))
    return {'scope': scope, 'positive': positive, 'probes': probes}


# ---------------------------------------------------------------- root configuration


def guest_interface():
    r = run(['ip', '-j', '-4', 'addr'])
    for link in json.loads(r['out'] or '[]'):
        for info in link.get('addr_info', []):
            if ipaddress.ip_address(info['local']) in ipaddress.ip_network(SLIRP_NET):
                return link['ifname'], info['local']
    raise RuntimeError(f'no interface in {SLIRP_NET}: {r}')


def snapshot(ifname):
    out = {key: run(argv) for key, argv in (
        ('ip_addr', ['ip', 'addr']),
        ('ip6_addr', ['ip', '-6', 'addr']),
        ('ip_route', ['ip', 'route']),
        ('ip6_route', ['ip', '-6', 'route']),
        ('ip_neigh', ['ip', 'neigh']),
        ('ip6_neigh', ['ip', '-6', 'neigh']),
        ('link_stats', ['ip', '-s', '-j', 'link', 'show', 'dev', ifname]))}
    out['resolv_conf'] = {'islink': os.path.islink('/etc/resolv.conf'),
                          'target': os.readlink('/etc/resolv.conf')
                          if os.path.islink('/etc/resolv.conf') else None,
                          'text': read_text('/etc/resolv.conf')}
    out['sysctl'] = {name: read_text(f'/proc/sys/net/{name}') for name in (
        'ipv4/ip_forward', 'ipv6/conf/all/disable_ipv6', f'ipv6/conf/{ifname}/disable_ipv6',
        f'ipv6/conf/{ifname}/addr_gen_mode', f'ipv6/conf/{ifname}/accept_ra')}
    return out


def gateway_mac(ifname):
    r = run(['ip', '-j', 'neigh', 'show', SLIRP_GW, 'dev', ifname])
    for entry in json.loads(r['out'] or '[]'):
        if entry.get('lladdr'):
            return entry['lladdr']
    return None


def resolv_text(params):
    servers = [SLIRP_DNS] + params['public_dns_ipv4'][:2]
    return ''.join(f'nameserver {s}\n' for s in servers) + 'options timeout:2 attempts:1\n'


def write_resolv(path, text):
    tmp = path + '.aieh-netprobe'
    with open(tmp, 'w', encoding='ascii') as handle:
        handle.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)                 # replaces a stub symlink by a regular file


def setup_root(params, ifname):
    steps = [run(['ip', 'route', 'replace', 'default', 'via', SLIRP_GW, 'dev', ifname]),
             run(['ping', '-n', '-c', '1', '-W', '2', SLIRP_GW])]   # learns the gateway MAC
    mac = gateway_mac(ifname)
    write_resolv('/etc/resolv.conf', resolv_text(params))
    steps.append({'argv': ['write', '/etc/resolv.conf'], 'rc': 0, 'out': resolv_text(params),
                  'err': ''})
    if shutil.which('resolvectl'):
        steps.append(run(['resolvectl', 'dns', ifname, SLIRP_DNS] + params['public_dns_ipv4'][:2]))
    if mac:
        steps.append(run(['ip', 'neigh', 'replace', UNUSED_ONLINK, 'lladdr', mac, 'dev', ifname,
                          'nud', 'permanent']))
    steps += [run(['sysctl', '-w', f'net.ipv6.conf.{ifname}.disable_ipv6=0']),
              run(['ip', '-6', 'addr', 'add', f'{V6_ADDR}/64', 'dev', ifname, 'nodad']),
              run(['ip', '-6', 'route', 'replace', 'default', 'via', V6_GW, 'dev', ifname])]
    if mac:
        for addr in (V6_GW, V6_DNS):
            steps.append(run(['ip', '-6', 'neigh', 'replace', addr, 'lladdr', mac, 'dev', ifname,
                              'nud', 'permanent']))
    return steps, mac


def setup_netns(params, ifname):
    commands = [
        ['ip', 'netns', 'add', NETNS],
        ['ip', 'link', 'add', VETH_HOST, 'type', 'veth', 'peer', 'name', VETH_NS, 'netns', NETNS],
        ['ip', 'addr', 'add', f'{NS_HOST_ADDR}/{NS_PREFIX}', 'dev', VETH_HOST],
        ['ip', 'link', 'set', VETH_HOST, 'up'],
        ['ip', 'netns', 'exec', NETNS, 'ip', 'link', 'set', 'lo', 'up'],
        ['ip', 'netns', 'exec', NETNS, 'ip', 'addr', 'add', f'{NS_ADDR}/{NS_PREFIX}', 'dev', VETH_NS],
        ['ip', 'netns', 'exec', NETNS, 'ip', 'link', 'set', VETH_NS, 'up'],
        ['ip', 'netns', 'exec', NETNS, 'ip', 'route', 'add', 'default', 'via', NS_HOST_ADDR],
        ['sysctl', '-w', 'net.ipv4.ip_forward=1'],
        ['iptables', '-t', 'nat', '-A', 'POSTROUTING', '-s', NS_SUBNET, '-o', ifname,
         '-j', 'MASQUERADE'],
    ]
    steps = []
    for argv in commands:
        steps.append(run(argv))
        if steps[-1]['rc'] != 0:
            return steps, False
    os.makedirs(f'/etc/netns/{NETNS}', exist_ok=True)
    write_resolv(f'/etc/netns/{NETNS}/resolv.conf', resolv_text(params))
    return steps, True


def write_result(result):
    os.makedirs(OUT_DIR, exist_ok=True)
    os.chmod(OUT_DIR, 0o755)
    partial = os.path.join(OUT_DIR, 'result.json.partial')
    with open(partial, 'w', encoding='utf-8') as handle:
        json.dump(result, handle, indent=1, sort_keys=True)
    os.chmod(partial, 0o644)
    os.replace(partial, os.path.join(OUT_DIR, 'result.json'))


def main(argv):
    params = json.loads(PARAMS_JSON)
    if argv[1:3] == ['--scope', 'netns']:
        print(json.dumps(scope_run(params, 'netns'), sort_keys=True))
        return 0
    result = {'schema': SCHEMA, 'started_at': now(), 'uid': os.getuid(), 'params': params,
              'script': os.path.abspath(__file__)}
    try:
        result['tools'] = {t: shutil.which(t) for t in (
            'ip', 'iptables', 'ping', 'getent', 'resolvectl', 'sysctl', 'unshare', 'nft')}
        result['iptables_version'] = run(['iptables', '-V'])
        result['nsswitch_hosts'] = [line for line in read_text('/etc/nsswitch.conf').splitlines()
                                    if line.startswith('hosts:')]
        ifname, addr = guest_interface()
        result['interface'] = {'name': ifname, 'ipv4': addr}
        result['before'] = snapshot(ifname)
        result['setup'], result['slirp_gateway_mac'] = setup_root(params, ifname)
        result['after_setup'] = snapshot(ifname)
        result['guest'] = scope_run(params, 'guest')
        result['after_probes'] = snapshot(ifname)
        steps, configured = setup_netns(params, ifname)
        result['netns'] = {'setup': steps, 'configured': configured}
        if configured:
            child = run(['ip', 'netns', 'exec', NETNS, sys.executable, os.path.abspath(__file__),
                         '--scope', 'netns'], timeout=600)
            result['netns']['child'] = {'rc': child['rc'], 'err': child['err'][-2000:]}
            try:
                result['netns'].update(json.loads(child['out']))
            except ValueError as exc:
                result['netns']['parse_error'] = f'{exc}: {child["out"][:2000]}'
            result['netns']['nat_counters'] = run(['iptables', '-t', 'nat', '-L', 'POSTROUTING',
                                                   '-n', '-v', '-x'])
            result['netns']['forward_chain'] = run(['iptables', '-S', 'FORWARD'])
            result['netns']['ns_addr'] = run(['ip', 'netns', 'exec', NETNS, 'ip', 'addr'])
            result['netns']['ns_route'] = run(['ip', 'netns', 'exec', NETNS, 'ip', 'route'])
        result['after'] = snapshot(ifname)
    except Exception:                    # reported to the host, which then cannot PASS
        result['error'] = traceback.format_exc()
    result['ended_at'] = now()
    write_result(result)
    return 0                             # cloud-init stays 'done'; the host judges result.json


if __name__ == '__main__':
    sys.exit(main(sys.argv))
