"""The containment observation of one conversation container (plan leaf S-03.3, slice 1), offline.

S-03.3's proof as amended on 2026-11-11 (the Owner's decision on OA-19): "The real ACP coding provider and every
process it starts, including any sub-agent or delegated session, run in the execution container as descendants of
the inner server under the same limits, shown by the process inventory and an independent docker inspect, and no
unexpected conversation appears on the outer server. The provider's actual delegation mechanism is identified ...
and the evidence distinguishes it from OpenHands' start_child_conversation tool". Slice plan:
``evidence/S-03.3-slice-plan.md`` section 4, slice 1.

This one standard-library file has two halves:

* **Collection** (``collect``, ``main``): sent to the guest as a file and run there by ``python3``. ``collect
  container`` runs inside the conversation container as its user (through the inner server's bash route, as
  ``tools/guest.py``'s job probe does) and lists every process of the container's PID namespace (its parent,
  executable, the first path among its first arguments, its identity, capabilities, ``NoNewPrivs``, ``Seccomp``
  and cgroup), the listening TCP sockets with their owner, and the container's own cgroup limits. ``collect host
  --pid N`` runs as the guest's root: every host process in the PID namespace of the container's init ``N``
  (``docker container inspect``'s ``State.Pid``), with its namespaced pid, cgroup and status, the limits of that
  cgroup, and any process outside the namespace whose parent is inside it. The output is one line,
  ``MARKER`` and canonical JSON. No command line argument value other than an absolute path is recorded, and no
  environment, file content or socket payload is read.
* **Judgement** (``container_verdict``, ``host_verdict``, ``sets_verdict``), on the host, over those snapshots,
  the inspected container and the before/after sets of containers and of outer and inner conversations.

The container view is taken from inside the boundary it judges; the host view is the independent one. The
verdicts fail closed: a process whose status, parent or cgroup cannot be read, an ambiguous inner server, an
adapter that is not found, or a provider process that the host cannot place is a failed check, never a pass.

Nothing here has run in a guest: **not yet verified** live. The provider process identities in
``PROVIDER_ADAPTERS`` come from the pinned image's files (``evidence/S-03.3-image-adapter-check.md``), not from
a running provider.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

SNAPSHOT_FORMAT = 'ai-engineering-harness/containment/snapshot/v1'
VERDICT_FORMAT = 'ai-engineering-harness/containment/verdict/v1'
MARKER = 'AIEH-CONTAINMENT-JSON '

# /proc/<pid>/status fields kept (identity, capabilities, the confinement flags, the namespaced pids).
STATUS_FIELDS = ('Uid', 'Gid', 'Groups', 'CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb', 'NoNewPrivs',
                 'Seccomp', 'NSpid')
CAP_FIELDS = ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')
# cgroup v2 interface files of the three caps decision 0001 s3 sets per conversation container.
LIMIT_FILES = ('memory.max', 'cpu.max', 'pids.max')
ARG_MAX = 256           # the longest recorded executable, argv0 or script path
SCRIPT_SCAN = 4         # the script is the first absolute path among argv[1:SCRIPT_SCAN]
# The inner server's port inside every conversation container: registry.py _build_container of the locked
# 1.60.1 wheel publishes container port 8000 (-p 127.0.0.1::8000; profile provisioning.agent_server.jobs.sources).
INNER_PORT = 8000
# An npm start: the bare npx/npm, or node running their scripts (decision 0015 amendment: no runtime npx fallback).
NPX_NAMES = frozenset({'npx', 'npm', 'npx-cli.js', 'npm-cli.js'})
# The adapter process each provider's pinned wrapper ends in: /usr/local/bin/<binary> is
# `PATH="/acp-node/bin:$PATH" exec "/acp-node/bin/<binary>" "$@"`, and /acp-node/bin/<binary> is the npm bin link
# to the adapter's dist/index.js, run by /acp-node/bin/node (the image adapter check, section 4.1). Provisional:
# the script's interpreter line was not read, and no provider has been seen running.
PROVIDER_ADAPTERS = {
    'claude-code': {'argv0': 'node', 'script': '/acp-node/bin/claude-agent-acp', 'exe': '/acp-node/bin/node'},
    'codex': {'argv0': 'node', 'script': '/acp-node/bin/codex-acp', 'exe': '/acp-node/bin/node'},
}
DOCKER_MEMORY_UNITS = {'b': 1, 'k': 1024, 'm': 1024 ** 2, 'g': 1024 ** 3}
CPU_PERIOD = 100000     # Moby's CFS period for --cpus (cgroup v2 cpu.max "<quota> <period>")


class ContainmentError(ValueError):
    """A snapshot, inspection or set that is not of its declared shape."""

    def __init__(self, code: str, detail: str):
        super().__init__(f'{code}: {detail}')
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------------------------------------------
# Collection (runs in the guest)
# ---------------------------------------------------------------------------------------------------------------

class OsFs:
    """The real file system, as the collector reads it."""

    def listdir(self, path: str) -> list:
        return os.listdir(path)

    def read_bytes(self, path: str) -> bytes:
        with open(path, 'rb') as handle:
            return handle.read()

    def readlink(self, path: str) -> str:
        return os.readlink(path)


def parse_stat(text: str) -> tuple:
    """(state, ppid) of a /proc/<pid>/stat line. The command name in parentheses may hold spaces and ')', so the
    fields are read after its last ')'."""
    _, sep, rest = text.rpartition(')')
    fields = rest.split()
    if not sep or len(fields) < 2 or not fields[1].isdigit():
        raise ValueError('not a /proc/<pid>/stat line')
    return fields[0], int(fields[1])


def parse_status(text: str) -> dict:
    """The STATUS_FIELDS of /proc/<pid>/status, each value with its whitespace normalized to single spaces."""
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition(':')
        if sep and key in STATUS_FIELDS:
            out[key] = ' '.join(value.split())
    return out


def parse_cgroup(text: str):
    """The cgroup v2 path of /proc/<pid>/cgroup (its ``0::`` line), or None when there is none."""
    for line in text.splitlines():
        if line.startswith('0::'):
            return line[3:]
    return None


def parse_cmdline(data: bytes) -> list:
    """The argument vector of /proc/<pid>/cmdline (NUL-separated, NUL-terminated)."""
    parts = data.split(b'\0')
    if parts[-1] == b'':
        parts.pop()
    return [p.decode('utf-8', 'replace') for p in parts]


def summarize_argv(argv: list) -> dict:
    """What is kept of an argument vector: argv0's last path segment, the first absolute path among the next
    arguments (a script an interpreter runs) and the count. No other argument value is recorded."""
    argv0 = argv[0].rsplit('/', 1)[-1][:ARG_MAX] if argv else ''
    script = next((a[:ARG_MAX] for a in argv[1:SCRIPT_SCAN] if a.startswith('/')), None)
    return {'argv0': argv0, 'script': script, 'argc': len(argv)}


def _address(hex_addr: str) -> str:
    """The textual address of a /proc/net/tcp{,6} local address (32-bit words in host byte order, little-endian
    on x86_64 and aarch64)."""
    raw = bytes.fromhex(hex_addr)
    words = b''.join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
    if len(words) == 4:
        return '.'.join(str(b) for b in words)
    groups = [words[i:i + 2].hex() for i in range(0, 16, 2)]
    return ':'.join(g.lstrip('0') or '0' for g in groups)


def parse_net_tcp(text: str) -> list:
    """The listening sockets of a /proc/net/tcp or tcp6 table: [{inode, address, port}]."""
    out = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 10 or fields[3] != '0A':
            continue
        host, _, port = fields[1].partition(':')
        out.append({'inode': fields[9], 'address': _address(host), 'port': int(port, 16)})
    return out


def _text(fs, path: str) -> str:
    return fs.read_bytes(path).decode('utf-8', 'replace')


def _error(exc: OSError) -> str:
    return type(exc).__name__


def _process(fs, proc: str, pid: int, *, with_ns: bool):
    """One process's record, or None when it ended while being read."""
    base = f'{proc}/{pid}'
    try:
        state, ppid = parse_stat(_text(fs, base + '/stat'))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        return {'pid': pid, 'ppid': None, 'error': f'stat: {type(exc).__name__}'}
    record = {'pid': pid, 'ppid': ppid, 'state': state}
    try:
        record['status'] = parse_status(_text(fs, base + '/status'))
    except FileNotFoundError:
        return None
    except OSError as exc:
        record['status'] = {'error': _error(exc)}
    try:
        record['cgroup'] = parse_cgroup(_text(fs, base + '/cgroup'))
    except FileNotFoundError:
        return None
    except OSError as exc:
        record['cgroup_error'] = _error(exc)
        record['cgroup'] = None
    try:
        record.update(summarize_argv(parse_cmdline(fs.read_bytes(base + '/cmdline'))))
    except FileNotFoundError:
        return None
    except OSError as exc:
        record.update({'argv0': None, 'script': None, 'argc': None, 'cmdline_error': _error(exc)})
    try:
        record['exe'] = fs.readlink(base + '/exe')[:ARG_MAX]
    except FileNotFoundError:
        record['exe'] = None       # a kernel thread, or a process that ended: kept, the verdict decides
    except OSError as exc:
        record['exe'] = None
        record['exe_error'] = _error(exc)
    if with_ns:
        try:
            record['pidns'] = fs.readlink(base + '/ns/pid')
        except OSError as exc:
            record['pidns'] = None
            record['pidns_error'] = _error(exc)
    return record


def _pids(fs, proc: str) -> list:
    return sorted(int(name) for name in fs.listdir(proc) if name.isdigit())


def _socket_owners(fs, proc: str, pids: list) -> tuple:
    """{socket inode: [pid]} from every readable /proc/<pid>/fd, and the pids whose fds could not be read."""
    owners, unreadable = {}, []
    for pid in pids:
        try:
            fds = fs.listdir(f'{proc}/{pid}/fd')
        except FileNotFoundError:
            continue
        except OSError:
            unreadable.append(pid)
            continue
        for fd in fds:
            try:
                target = fs.readlink(f'{proc}/{pid}/fd/{fd}')
            except OSError:
                continue
            if target.startswith('socket:[') and target.endswith(']'):
                owners.setdefault(target[8:-1], set()).add(pid)
    return {k: sorted(v) for k, v in owners.items()}, unreadable


def _limits(fs, directory: str) -> dict:
    out = {}
    for name in LIMIT_FILES:
        try:
            out[name] = _text(fs, f'{directory}/{name}').strip()
        except OSError:
            out[name] = None
    return out


def collect(mode: str, *, fs=None, proc: str = '/proc', cgroup_root: str = '/sys/fs/cgroup',
            target_pid=None, self_pid=None) -> dict:
    """The snapshot of one vantage. ``container``: every process visible (the container's PID namespace), the
    listening sockets of its network namespace with their owners, and the limits at its cgroup namespace's root.
    ``host``: every process in the PID namespace of ``target_pid``, the processes outside it whose parent is
    inside, and the limits of ``target_pid``'s cgroup."""
    fs = fs or OsFs()
    if mode not in ('container', 'host'):
        raise ContainmentError('MODE_INVALID', f'{mode!r}: container or host')
    out = {'format': SNAPSHOT_FORMAT, 'mode': mode, 'self': os.getpid() if self_pid is None else self_pid,
           'vanished': 0}
    pids = _pids(fs, proc)
    if mode == 'container':
        processes = []
        for pid in pids:
            record = _process(fs, proc, pid, with_ns=False)
            if record is None:
                out['vanished'] += 1
            else:
                processes.append(record)
        owners, unreadable = _socket_owners(fs, proc, [p['pid'] for p in processes])
        listeners = []
        for table in ('tcp', 'tcp6'):
            try:
                rows = parse_net_tcp(_text(fs, f'{proc}/net/{table}'))
            except OSError:
                continue
            for row in rows:
                listeners.append({'address': row['address'], 'port': row['port'],
                                  'pids': owners.get(row['inode'], [])})
        out.update(processes=processes, listeners=listeners, fd_unreadable=unreadable,
                   limits=_limits(fs, cgroup_root))
        return out
    if not isinstance(target_pid, int) or isinstance(target_pid, bool) or target_pid < 1:
        raise ContainmentError('TARGET_INVALID', 'host mode needs the container init pid (State.Pid)')
    try:
        target_ns = fs.readlink(f'{proc}/{target_pid}/ns/pid')
    except OSError as exc:
        raise ContainmentError('TARGET_INVALID', f'pid {target_pid}: {type(exc).__name__}') from None
    members, others = [], []
    for pid in pids:
        record = _process(fs, proc, pid, with_ns=True)
        if record is None:
            out['vanished'] += 1
        elif record.get('pidns') == target_ns:
            members.append(record)
        else:
            others.append(record)
    inside = {r['pid'] for r in members}
    target = next((r for r in members if r['pid'] == target_pid), None)
    path = target.get('cgroup') if target else None
    out.update(target_pid=target_pid, target_pidns=target_ns, processes=members,
               outside_children=[r for r in others if r.get('ppid') in inside],
               limits=_limits(fs, cgroup_root + path) if path is not None else None)
    return out


def main(argv=None, out=None) -> int:
    """``collect container`` or ``collect host --pid N``: print MARKER and the snapshot as one JSON line."""
    parser = argparse.ArgumentParser(prog='conversation_containment.py')
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('collect')
    c.add_argument('mode', choices=('container', 'host'))
    c.add_argument('--pid', type=int)
    args = parser.parse_args(argv)
    if args.mode == 'host' and args.pid is None:
        parser.error('collect host needs --pid')
    if args.mode == 'container' and args.pid is not None:
        parser.error('--pid is for collect host only')
    try:
        snapshot = collect(args.mode, target_pid=args.pid)
    except ContainmentError as exc:
        sys.stderr.write(f'conversation_containment: {exc}\n')
        return 2
    (out or sys.stdout).write(MARKER + json.dumps(snapshot, sort_keys=True, separators=(',', ':')) + '\n')
    return 0


# ---------------------------------------------------------------------------------------------------------------
# Judgement (runs on the host)
# ---------------------------------------------------------------------------------------------------------------

def parse_output(stdout: str) -> dict:
    """The snapshot of a collector's output: its last MARKER line."""
    lines = [line for line in (stdout or '').splitlines() if line.startswith(MARKER)]
    if not lines:
        raise ContainmentError('NO_SNAPSHOT', 'the collector printed no result line')
    try:
        return json.loads(lines[-1][len(MARKER):])
    except ValueError as exc:
        raise ContainmentError('NO_SNAPSHOT', f'the result line is not JSON: {exc}') from None


def memory_bytes(value: str) -> int:
    """Docker's --memory value ('4g', '512m', ...) in bytes."""
    text = str(value).strip().lower()
    unit = text[-1:] if text[-1:] in DOCKER_MEMORY_UNITS else 'b'
    number = text[:-1] if text[-1:] in DOCKER_MEMORY_UNITS else text
    if not number.isdigit() or int(number) < 1:
        raise ContainmentError('LIMITS_INVALID', f'memory {value!r}')
    return int(number) * DOCKER_MEMORY_UNITS[unit]


def expected_limits(memory, cpus, pids_limit) -> dict:
    """The cgroup v2 interface values and the inspected HostConfig values of Docker's --memory, --cpus and
    --pids-limit (the admitted caps)."""
    if isinstance(cpus, bool) or not isinstance(cpus, (int, float)) or not 0 < cpus <= 1024:
        raise ContainmentError('LIMITS_INVALID', f'cpus {cpus!r}')
    if isinstance(pids_limit, bool) or not isinstance(pids_limit, int) or pids_limit < 1:
        raise ContainmentError('LIMITS_INVALID', f'pids_limit {pids_limit!r}')
    mem = memory_bytes(memory)
    quota = round(cpus * CPU_PERIOD)
    return {'cgroup': {'memory.max': str(mem), 'cpu.max': f'{quota} {CPU_PERIOD}', 'pids.max': str(pids_limit)},
            'inspect': {'Memory': mem, 'NanoCpus': round(cpus * 1e9), 'PidsLimit': pids_limit}}


def _require(cond: bool, code: str, detail: str) -> None:
    if not cond:
        raise ContainmentError(code, detail)


def _check_snapshot(snapshot, mode: str) -> list:
    _require(isinstance(snapshot, dict) and snapshot.get('format') == SNAPSHOT_FORMAT
             and snapshot.get('mode') == mode, 'SNAPSHOT_INVALID', f'not a {mode} snapshot')
    processes = snapshot.get('processes')
    _require(isinstance(processes, list) and processes, 'SNAPSHOT_INVALID', 'no process list')
    seen = set()
    for p in processes:
        _require(isinstance(p, dict) and isinstance(p.get('pid'), int) and not isinstance(p.get('pid'), bool)
                 and p['pid'] > 0, 'SNAPSHOT_INVALID', f'a process without a pid: {p!r:.120}')
        _require(p['pid'] not in seen, 'SNAPSHOT_INVALID', f'pid {p["pid"]} listed twice')
        seen.add(p['pid'])
        _require(p.get('ppid') is None or (isinstance(p['ppid'], int) and not isinstance(p['ppid'], bool)),
                 'SNAPSHOT_INVALID', f'pid {p["pid"]}: ppid')
        _require(isinstance(p.get('status', {}), dict), 'SNAPSHOT_INVALID', f'pid {p["pid"]}: status')
    return processes


def _summary(p: dict) -> dict:
    return {k: p.get(k) for k in ('pid', 'ppid', 'exe', 'argv0', 'script')}


def _identity_problems(p: dict, expected: dict, reference: dict) -> list:
    """Why process P does not hold the container's identity and confinement (empty when it does)."""
    st = p.get('status') or {}
    if 'error' in st or not st:
        return ['status unreadable']
    problems = []
    if st.get('Uid', '').split() != [str(expected['uid'])] * 4:
        problems.append(f"Uid {st.get('Uid')!r}")
    if st.get('Gid', '').split() != [str(expected['gid'])] * 4:
        problems.append(f"Gid {st.get('Gid')!r}")
    if st.get('Groups') != (reference.get('status') or {}).get('Groups'):
        problems.append(f"Groups {st.get('Groups')!r}")
    for cap in CAP_FIELDS:
        if st.get(cap) != expected['capabilities']:
            problems.append(f'{cap} {st.get(cap)!r}')
    if st.get('NoNewPrivs') != expected['no_new_privs']:
        problems.append(f"NoNewPrivs {st.get('NoNewPrivs')!r}")
    if st.get('Seccomp') != expected['seccomp']:
        problems.append(f"Seccomp {st.get('Seccomp')!r}")
    return problems


def _check(checks: list, name: str, ok: bool, observed=None) -> None:
    checks.append({'check': name, 'ok': bool(ok), 'observed': observed})


def _ancestors(pid: int, parent: dict, limit: int) -> tuple:
    """(chain from PID's parent upwards, resolved): resolved is False when a parent is not in the snapshot or the
    chain loops."""
    chain, here = [], pid
    while len(chain) <= limit:
        up = parent.get(here)
        if up is None:
            return chain, False
        if up == 0:
            return chain, True
        if up in chain or up == pid:
            return chain, False
        chain.append(up)
        here = up
    return chain, False


def _descendants(root: int, children: dict) -> list:
    out, stack = [], [root]
    while stack:
        here = stack.pop()
        out.append(here)
        stack.extend(sorted(children.get(here, ()), reverse=True))
    return out


def _is_npx(p: dict) -> bool:
    script = p.get('script') or ''
    return p.get('argv0') in NPX_NAMES or script.rsplit('/', 1)[-1] in NPX_NAMES


def _expected(expected: dict) -> dict:
    _require(isinstance(expected, dict), 'EXPECTED_INVALID', 'expected values')
    for key in ('uid', 'gid', 'capabilities', 'no_new_privs', 'seccomp', 'limits'):
        _require(key in expected, 'EXPECTED_INVALID', f'{key} missing')
    limits = expected['limits']
    _require(isinstance(limits, dict) and isinstance(limits.get('cgroup'), dict)
             and isinstance(limits.get('inspect'), dict), 'EXPECTED_INVALID', 'limits: expected_limits()')
    provider = expected.get('provider')
    _require(provider is None or provider in PROVIDER_ADAPTERS, 'EXPECTED_INVALID', f'provider {provider!r}')
    return expected


def container_verdict(snapshot, *, expected: dict) -> dict:
    """The inside view of one conversation container. ``expected``: ``uid``, ``gid``, ``capabilities``,
    ``no_new_privs``, ``seccomp`` (the profile's jobs.process values), ``limits`` (``expected_limits``),
    ``provider`` (a PROVIDER_ADAPTERS key, or None when no provider is expected) and optionally
    ``inner_port``."""
    expected = _expected(expected)
    processes = _check_snapshot(snapshot, 'container')
    by_pid = {p['pid']: p for p in processes}
    parent = {p['pid']: p.get('ppid') for p in processes}
    children = {}
    for p in processes:
        if p.get('ppid') in by_pid:
            children.setdefault(p['ppid'], []).append(p['pid'])
    checks = []
    out = {'format': VERDICT_FORMAT, 'vantage': 'container', 'checks': checks, 'process_count': len(processes),
           'vanished': snapshot.get('vanished')}

    init = by_pid.get(1)
    _check(checks, 'init: PID 1 present, started by no process of the namespace',
           init is not None and init.get('ppid') == 0, _summary(init) if init else None)
    entered = [_summary(p) for p in processes if p['pid'] != 1 and p.get('ppid') == 0]
    _check(checks, 'entered: no process entered the namespace from outside (parent 0)', not entered, entered)

    port = expected.get('inner_port', INNER_PORT)
    listeners = snapshot.get('listeners') if isinstance(snapshot.get('listeners'), list) else []
    owners = sorted({pid for row in listeners if isinstance(row, dict) and row.get('port') == port
                     for pid in (row.get('pids') or [])})
    inner = owners[0] if len(owners) == 1 and owners[0] in by_pid else None
    out['inner_server'] = _summary(by_pid[inner]) if inner is not None else None
    _check(checks, f'inner server: exactly one process owns the listener on port {port}', inner is not None,
           {'owners': owners, 'fd_unreadable': snapshot.get('fd_unreadable')})

    reference = init or {}
    identity = {p['pid']: probs for p in processes if (probs := _identity_problems(p, expected, reference))}
    _check(checks, 'identity: every process has the container user, no capability, no_new_privs and seccomp',
           not identity, {str(k): v for k, v in sorted(identity.items())})
    base_cgroup = reference.get('cgroup')
    off_cgroup = {str(p['pid']): p.get('cgroup') for p in processes if p.get('cgroup') != base_cgroup}
    _check(checks, "cgroup: every process in PID 1's cgroup", base_cgroup is not None and not off_cgroup,
           {'pid1': base_cgroup, 'other': off_cgroup})

    unresolved, outside = [], []
    inner_chain = _ancestors(inner, parent, len(processes))[0] if inner is not None else []
    # The collector's own chain (started through the bash route for this observation) is judged for identity and
    # cgroup above, and named here, but not as a process of the attempt.
    me = snapshot.get('self')
    mine = [me] + _ancestors(me, parent, len(processes))[0]
    collector = [pid for pid in mine if pid in by_pid and pid not in (1, inner) and pid not in inner_chain]
    out['collector'] = [_summary(by_pid[pid]) for pid in collector]
    for p in processes:
        if p['pid'] in (1, inner) or p['pid'] in inner_chain or p['pid'] in collector:
            continue
        chain, resolved = _ancestors(p['pid'], parent, len(processes))
        if not resolved:
            unresolved.append(_summary(p))
        elif inner is None or inner not in chain:
            outside.append(_summary(p))
    out['outside_inner_server'] = outside
    _check(checks, 'ancestry: every process descends from the inner server (none reparented outside it)',
           inner is not None and not unresolved and not outside, {'unresolved': unresolved, 'outside': outside})

    npx = [_summary(p) for p in processes if _is_npx(p)]
    _check(checks, 'npx: no npm or npx process (no runtime install)', not npx, npx)

    limits = snapshot.get('limits')
    _check(checks, 'limits: the container cgroup holds the admitted caps',
           isinstance(limits, dict) and limits == expected['limits']['cgroup'], limits)

    provider = expected.get('provider')
    out['provider_tree'] = []
    if provider is not None:
        want = PROVIDER_ADAPTERS[provider]
        adapters = [pid for pid in children.get(inner, []) if inner is not None
                    and by_pid[pid].get('argv0') == want['argv0'] and by_pid[pid].get('script') == want['script']]
        tree = sorted({pid for a in adapters for pid in _descendants(a, children)})
        out['adapters'] = adapters
        out['provider_tree'] = [_summary(by_pid[pid]) for pid in tree]
        _check(checks, f'adapter: the {provider} adapter is a direct child of the inner server', bool(adapters),
               {'inner_server_children': [_summary(by_pid[c]) for c in children.get(inner, [])]})
        wrong_exe = [_summary(by_pid[a]) for a in adapters if by_pid[a].get('exe') != want['exe']]
        _check(checks, f"adapter executable: {want['exe']}", bool(adapters) and not wrong_exe, wrong_exe)
    out['listeners'] = [{'address': row.get('address'), 'port': row.get('port'), 'pids': row.get('pids'),
                         'provider': any(pid in {s['pid'] for s in out['provider_tree']}
                                         for pid in (row.get('pids') or []))}
                        for row in listeners if isinstance(row, dict)]
    out['ok'] = all(c['ok'] for c in checks)
    return out


def _nspid(p: dict):
    """The innermost pid of a host process (the last field of NSpid), or None."""
    fields = ((p.get('status') or {}).get('NSpid') or '').split()
    if len(fields) < 2 or not all(f.isdigit() for f in fields):
        return None
    return int(fields[-1])


def host_verdict(snapshot, *, inspect: dict, container: dict, expected: dict) -> dict:
    """The guest root's view of the same container: ``snapshot`` from ``collect host --pid <State.Pid>``,
    ``inspect`` the container's ``docker container inspect`` object, ``container`` the inside snapshot (from
    ``collect container``) and ``expected`` as for ``container_verdict``."""
    expected = _expected(expected)
    processes = _check_snapshot(snapshot, 'host')
    _require(isinstance(inspect, dict) and isinstance(inspect.get('State'), dict)
             and isinstance(inspect.get('HostConfig'), dict), 'INSPECT_INVALID', 'State and HostConfig')
    inside = _check_snapshot(container, 'container')
    checks = []
    out = {'format': VERDICT_FORMAT, 'vantage': 'host', 'checks': checks, 'member_count': len(processes)}
    state_pid = inspect['State'].get('Pid')
    _check(checks, 'target: the snapshot is of the inspected container init (State.Pid)',
           isinstance(state_pid, int) and state_pid > 0 and snapshot.get('target_pid') == state_pid
           and any(p['pid'] == state_pid for p in processes),
           {'State.Pid': state_pid, 'target_pid': snapshot.get('target_pid')})

    host = inspect['HostConfig']
    got = {k: host.get(k) for k in expected['limits']['inspect']}
    _check(checks, 'inspect: HostConfig Memory, NanoCpus and PidsLimit are the admitted caps',
           got == expected['limits']['inspect'], got)
    _check(checks, "host cgroup: the container cgroup's interface files hold the admitted caps",
           snapshot.get('limits') == expected['limits']['cgroup'], snapshot.get('limits'))

    target = next((p for p in processes if p['pid'] == state_pid), None)
    base_cgroup = target.get('cgroup') if target else None
    off_cgroup = {str(p['pid']): p.get('cgroup') for p in processes if p.get('cgroup') != base_cgroup}
    _check(checks, "members: every process of the container's PID namespace is in its cgroup",
           base_cgroup is not None and not off_cgroup, {'container': base_cgroup, 'other': off_cgroup})
    identity = {p['pid']: probs for p in processes if (probs := _identity_problems(p, expected, target or {}))}
    _check(checks, 'members: the container user, no capability, no_new_privs and seccomp (host view)',
           not identity, {str(k): v for k, v in sorted(identity.items())})
    escaped = [_summary(p) for p in snapshot.get('outside_children') or []]
    _check(checks, 'no escape: no process outside the namespace has a parent inside it', not escaped, escaped)

    by_inner = {}
    no_nspid = []
    for p in processes:
        n = _nspid(p)
        if n is None:
            no_nspid.append(_summary(p))
        else:
            by_inner.setdefault(n, []).append(p)
    _check(checks, 'members: each has a namespaced pid', not no_nspid, no_nspid)

    view = container_verdict(container, expected=expected)
    tree = view.get('provider_tree') or []
    adapters = set(view.get('adapters') or [])
    seen, vanished, mismatched = [], [], []
    for item in tree:
        found = by_inner.get(item['pid']) or []
        if len(found) != 1:
            (mismatched if found else vanished).append(item)
            continue
        if found[0].get('exe') != item.get('exe'):
            mismatched.append({'inside': item, 'host': _summary(found[0])})
        else:
            seen.append(item['pid'])
    out['provider_seen'] = seen
    out['provider_vanished'] = vanished
    if expected.get('provider') is not None:
        _check(checks, 'cross-view: every adapter seen from the guest root, with the same executable',
               bool(adapters) and adapters <= set(seen) and not mismatched,
               {'adapters': sorted(adapters), 'seen': seen, 'mismatched': mismatched})
    inside_pids = {p['pid'] for p in inside}
    out['appeared'] = sorted(n for n in by_inner if n not in inside_pids)
    out['ok'] = all(c['ok'] for c in checks)
    return out


def _id_set(value, what: str) -> set:
    _require(isinstance(value, list) and all(isinstance(v, str) and v for v in value), 'SETS_INVALID',
             f'{what}: a list of identifiers')
    return set(value)


def sets_verdict(before: dict, after: dict, *, conversation_id: str) -> dict:
    """The before/after sets around the observed turn. Each of ``before`` and ``after`` holds ``containers``
    (container ids), ``outer`` (conversation ids on the outer server) and ``inner`` (the inner server's
    conversations: ``[{id, parent_conversation_id}]``). A new container or a new outer conversation fails; a new
    inner conversation is classified: one whose parent is the observed conversation was started through the
    inner server's children route (the route OpenHands' start_child_conversation tool uses), any other fails."""
    _require(isinstance(conversation_id, str) and conversation_id, 'SETS_INVALID', 'conversation_id')
    for side in (before, after):
        _require(isinstance(side, dict) and set(side) == {'containers', 'outer', 'inner'}, 'SETS_INVALID',
                 'containers, outer and inner')
    containers = sorted(_id_set(after['containers'], 'containers') - _id_set(before['containers'], 'containers'))
    outer = sorted(_id_set(after['outer'], 'outer') - _id_set(before['outer'], 'outer'))

    def inner_rows(rows, what):
        _require(isinstance(rows, list), 'SETS_INVALID', f'{what}: a list')
        out = {}
        for row in rows:
            _require(isinstance(row, dict) and isinstance(row.get('id'), str) and row['id']
                     and (row.get('parent_conversation_id') is None
                          or isinstance(row.get('parent_conversation_id'), str)), 'SETS_INVALID',
                     f'{what}: {{id, parent_conversation_id}}')
            out[row['id']] = row.get('parent_conversation_id')
        return out
    old, new = inner_rows(before['inner'], 'inner before'), inner_rows(after['inner'], 'inner after')
    added = {k: v for k, v in new.items() if k not in old}
    children = sorted(k for k, v in added.items() if v == conversation_id)
    unexpected = sorted(k for k, v in added.items() if v != conversation_id)
    checks = []
    _check(checks, 'containers: no new container during the turn', not containers, containers)
    _check(checks, 'outer server: no new conversation during the turn', not outer, outer)
    _check(checks, "inner server: every new conversation is a child of the observed one (children route)",
           not unexpected, {k: added[k] for k in unexpected})
    return {'format': VERDICT_FORMAT, 'vantage': 'sets', 'checks': checks,
            'delegation': {'children_route': children, 'outer_new': outer, 'containers_new': containers},
            'ok': all(c['ok'] for c in checks)}


if __name__ == '__main__':
    sys.exit(main())
