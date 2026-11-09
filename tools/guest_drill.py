#!/usr/bin/python3
# aieh-drill: the TEST-ONLY root helper of a drill guest (plan leaf E-01.2.2 slice (b)).
#
# tools/guest.py create --provision --drill seeds this file as a second user-data part
# (cloud-init runs it once, as root, at first boot) of a disposable drill guest; the
# profile's templates, its launch.argv and an ordinary create are unchanged, and no
# ordinary guest ever carries it. At first boot it installs itself as
# /usr/local/sbin/aieh-drill with a path unit: when agent writes the request file into
# the root:agent 0730 request directory, the oneshot service reads and removes it, runs
# one action as root and writes an agent-readable result named by the request id.
#
# Actions (the drills of the leaf's proof):
#   observe        units, drop-ins, listeners, Moby processes, the Agent Server's cgroup,
#                  journal tails, lstat of named paths, the owned containers' key
#                  fingerprints (only while docker.service is active: no socket activation)
#   guard-break    a drop-in that makes aieh-container-guard.service fail at its next
#                  start (variant fail-pre: an ExecStartPre that exits 1; check-only: the
#                  guard verifies without installing, so it finds no rules at boot)
#   guard-restore  remove that drop-in
#   key-break      rewrite the Agent Server's environment file to a bad variant (the
#                  original kept root-only), then restart the unit
#   key-restore    put the original bytes back (sha256 checked), delete the copy, restart
#   server-restart restart aieh-agent-server.service
#   state-read     the stored conversation files of one conversation (JSON, redacted)
#   state-snapshot keep the whole conversation directory (root-only)
#   state-alter    set or delete one field of one stored file, or plant an absent one
#   state-rollback make the directory equal to the snapshot again (what a server added
#                  while acting on an alteration included), and compare
#   state-discard  delete the snapshot
#   quiesce-break  a drop-in that makes aieh-agent-server-quiesce.service fail (slice (c))
#   quiesce-restore remove that drop-in
#   server-kill    SIGKILL every process of the server's unit, then wait for systemd's
#                  Restart=on-failure start (a server restart with its containers alive)
#   start-window   the quiesce step's runs of this boot and the last start's order: Moby's
#                  container events between the step's start, its exit, the server's ExecStart
#                  and the server's active state (only while docker.service is active)
#   container-kill SIGKILL one conversation's container (no shutdown of its inner server)
#   quarantine-list the quarantine's entries by name and kind
#   quarantine-return move a quarantined conversation directory back (drill rollback)
#   sentinel-plant replace a conversation's base_state.json by a symbolic or hard link to a
#                  sentinel file outside the record, its access time set before its mtime
#   sentinel-check whether the sentinel was read or written since (times, size, sha256), then
#                  the access-time method's own control (a read moves it)
#   root-scan      the guest-root P5 scan: every regular file of every disk-backed and
#                  tmpfs mount and every process environment and command line, for the
#                  host canary cores (by sha256 only), the guest's secrets (by value, in
#                  the guest), private-key blocks and Owner-class patterns; optionally the
#                  raw block devices, counted
#
# Every secret value it handles is redacted from its results and counted; results carry
# fingerprints (aieh-secret-fingerprint/v1) and paths, never a value. Standard library only.
import hashlib
import json
import os
import pwd
import re
import secrets
import stat
import subprocess
import sys
import time

SCHEMA = 'ai-engineering-harness/profiles/drill-result/v1'
SELF = '/usr/local/sbin/aieh-drill'
ROOT = '/var/lib/aieh-drill'
REQUEST_DIR = ROOT + '/request'
REQUEST = REQUEST_DIR + '/request.json'
RESULTS = ROOT + '/results'
BACKUP = ROOT + '/backup'
CONTROL = ROOT + '/control'
PATH_UNIT = 'aieh-drill.path'
SERVICE = 'aieh-drill.service'
AGENT = 'agent'
REQUEST_MAX = 1 << 16
REQUEST_ID = re.compile(r'^[a-z0-9][a-z0-9-]{7,63}$')
HEX32 = re.compile(r'^[0-9a-f]{32}$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/root',
       'SYSTEMD_PAGER': '', 'SYSTEMD_COLORS': '0'}
GUARD_UNIT = 'aieh-container-guard.service'
GUARD_DROPIN = '/etc/systemd/system/aieh-container-guard.service.d/90-aieh-drill.conf'
GUARD_VARIANTS = {
    'fail-pre': ('# aieh-drill (TEST ONLY): the guard unit fails before it installs any rule\n'
                 '[Service]\n'
                 "ExecStartPre=/bin/sh -c 'echo aieh-drill: guard made to fail; exit 1'\n"),
    'check-only': ('# aieh-drill (TEST ONLY): the guard verifies without installing, so a boot\n'
                   '# finds no rule and the unit fails\n'
                   '[Service]\n'
                   'ExecStart=\n'
                   'ExecStart=/usr/bin/python3 -I /usr/local/sbin/aieh-container-guard check\n'),
}
AS_UNIT = 'aieh-agent-server.service'
QUIESCE_UNIT = 'aieh-agent-server-quiesce.service'
QUIESCE_PREFIX = 'aieh-agent-server-quiesce: '
QUIESCE_DROPIN = '/etc/systemd/system/aieh-agent-server-quiesce.service.d/90-aieh-drill.conf'
QUIESCE_VARIANTS = {
    'fail-pre': ('# aieh-drill (TEST ONLY): the quiesce step fails before it acts\n'
                 '[Service]\n'
                 "ExecStartPre=/bin/sh -c 'echo aieh-drill: quiesce made to fail; exit 1'\n"),
}
QUARANTINE = '/srv/scratch/aieh-quarantine'
SENTINEL_DIR = '/srv/scratch/aieh-drill-sentinel'
SENTINEL_KINDS = ('symlink', 'hardlink')
AS_SECRETS = '/etc/aieh/agent-server/secrets.env'
AS_SESSION_KEY = '/var/lib/aieh/agent-server/session.key'
AS_VARS = ('OH_SECRET_KEY', 'OH_SESSION_API_KEYS_0')
KEY_VARIANTS = ('missing-session-key', 'empty-session-key', 'second-session-key')
UNITS = (GUARD_UNIT, 'docker.service', 'docker.socket', 'containerd.service', QUIESCE_UNIT,
         AS_UNIT, 'aieh-conversation-facts.path', PATH_UNIT)
PROPS = ('LoadState', 'ActiveState', 'SubState', 'Result', 'NRestarts', 'MainPID',
         'ExecMainPID', 'ExecMainCode', 'ExecMainStatus', 'ActiveEnterTimestampMonotonic',
         'InactiveEnterTimestampMonotonic', 'ConditionResult', 'DropInPaths',
         'ExecMainStartTimestampMonotonic', 'ExecMainExitTimestampMonotonic')
JOURNAL_UNITS = (GUARD_UNIT, 'docker.service', QUIESCE_UNIT, AS_UNIT)
MOBY = ('dockerd', 'containerd', 'docker-proxy', 'containerd-shim', 'containerd-shim-runc-v2')
OWNER_LABEL = 'ai.openhands.runtime-owner'
CONVERSATIONS = '/srv/scratch/openhands/conversations'
OBSERVE_ROOTS = ('/srv/scratch/openhands/', '/tmp/', '/var/tmp/', '/workspace')
STATE_FILES = ('base_state.json', 'meta.json', 'owner_lease.json')
SNAPSHOT_FMT = BACKUP + '/state-{hex}'
FINGERPRINT_PREFIX = b'aieh-secret-fingerprint/v1\n'
# the positive control's key armor, assembled so that this file (which travels in the seed, and
# which the profiles P5 scan searches) holds no private-key header
ARMOR = '-' * 5 + '{} OPENSSH PRIVATE KEY' + '-' * 5
SECRET_VALUE = re.compile(r'^[A-Za-z0-9_-]{43}$')
CORE = re.compile(rb'(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])')
KEY_BLOCK = re.compile(rb'-----BEGIN ([A-Z0-9 ]*)PRIVATE KEY-----(.{0,20000}?)-----END \1PRIVATE KEY-----',
                       re.S)
OWNER_PATTERNS = {
    'private-key-header': [rb'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----',
                           rb'PuTTY-User-Key-File-\d'],
    'git-host-token': [rb'gh[pousr]_[A-Za-z0-9]{36}', rb'github_pat_[A-Za-z0-9_]{50,}',
                       rb'glpat-[A-Za-z0-9_-]{20}'],
    'cloud-token': [rb'(?:AKIA|ASIA)[0-9A-Z]{16}', rb'AIza[0-9A-Za-z_-]{35}'],
    'llm-provider-key': [rb'sk-ant-[A-Za-z0-9_-]{20,}', rb'sk-proj-[A-Za-z0-9_-]{20,}',
                         rb'sk-[A-Za-z0-9]{48}'],
    'windows-profile-path': [rb'[A-Za-z]:[\\/]{1,2}[Uu][Ss][Ee][Rr][Ss][\\/]{1,2}[A-Za-z0-9._ -]{1,64}',
                             rb'/mnt/[a-z]/[Uu][Ss][Ee][Rr][Ss]/[A-Za-z0-9._ -]{1,64}'],
}
# cheap literal tests before each class's regexes (a class whose literals are all absent from
# a window cannot match there)
OWNER_PREFILTER = {
    'private-key-header': (b'PRIVATE KEY-----', b'PuTTY-User-Key-File-'),
    'git-host-token': (b'ghp_', b'gho_', b'ghu_', b'ghs_', b'ghr_', b'github_pat_', b'glpat-'),
    'cloud-token': (b'AKIA', b'ASIA', b'AIza'),
    'llm-provider-key': (b'sk-',),
    'windows-profile-path': (b'sers', b'SERS', b'sERS', b'Sers'),
}
SCAN_FSTYPES = ('ext4', 'ext3', 'ext2', 'xfs', 'btrfs', 'vfat', 'tmpfs')
CHUNK = 8 << 20
OVERLAP = 4096


class Failed(Exception):
    pass


def run(argv, timeout=120):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=ENV,
                           check=False)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout after ' + str(timeout) + ' s'


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(value):
    return 'sha256:' + hashlib.sha256(FINGERPRINT_PREFIX + value.encode()).hexdigest()[:16]


def read_env_file(path):
    out = {}
    try:
        with open(path, encoding='ascii') as handle:
            for line in handle:
                name, sep, value = line.rstrip('\n').partition('=')
                if sep:
                    out[name] = value
    except OSError:
        pass
    return out


def known_secrets():
    """{label: value} of every secret this helper may meet: the server's two (from the
    environment file and its kept copy) and each owned container's own two (only while
    docker.service is active)."""
    out = {}
    for label, path in (('server', AS_SECRETS), ('server-copy', BACKUP + '/secrets.env')):
        for name, value in read_env_file(path).items():
            if value:
                out[label + ':' + name] = value
    try:
        with open(AS_SESSION_KEY, encoding='ascii') as handle:
            value = handle.read().strip()
        if value:
            out['server:session.key'] = value
    except OSError:
        pass
    for cid, env in container_envs().items():
        for name in AS_VARS:
            if env.get(name):
                out['container:' + cid[:12] + ':' + name] = env[name]
    return out


def unit_show(unit):
    rc, out, err = run(['systemctl', 'show', unit, '--no-pager', '-p', ','.join(PROPS)])
    props = {}
    for line in out.splitlines():
        k, _, v = line.partition('=')
        props[k] = v
    return props


def is_active(unit):
    return unit_show(unit).get('ActiveState') == 'active'


def container_envs():
    """{container id: environment} of the containers carrying the owner label; empty
    unless docker.service is active (a docker CLI call would socket-activate it)."""
    if not is_active('docker.service'):
        return {}
    rc, out, _ = run(['docker', 'ps', '-q', '--no-trunc', '--filter', 'label=' + OWNER_LABEL])
    ids = [i for i in out.split() if HEX64.match(i)] if rc == 0 else []
    envs = {}
    if ids:
        rc, out, _ = run(['docker', 'container', 'inspect'] + ids)
        try:
            for c in json.loads(out) if rc == 0 else []:
                env = {}
                for item in (c.get('Config') or {}).get('Env') or []:
                    name, _, value = item.partition('=')
                    env[name] = value
                envs[c.get('Id')] = env
        except ValueError:
            pass
    return envs


def invocation_journal(unit, lines=300):
    """The journal lines of the unit's current invocation only (this start, not an earlier one)."""
    invocation = run(['systemctl', 'show', unit, '-p', 'InvocationID', '--value'])[1].strip()
    if not re.match(r'^[0-9a-f]{32}$', invocation):
        return {'id': None, 'lines': []}
    rc, out, _ = run(['journalctl', '-b', '_SYSTEMD_INVOCATION_ID=' + invocation, '-o',
                      'short-monotonic', '--no-pager', '-n', str(lines)], timeout=60)
    return {'id': invocation, 'lines': out.splitlines()[-lines:]}


def journal(unit, lines=40):
    rc, out, _ = run(['journalctl', '-b', '-u', unit, '-o', 'short-monotonic', '--no-pager',
                      '-n', str(lines)], timeout=60)
    return out.splitlines()[-lines:]


def proc_entries(pids):
    out = []
    for pid in pids:
        try:
            with open('/proc/' + pid + '/comm', encoding='utf-8', errors='replace') as h:
                comm = h.read().strip()
            with open('/proc/' + pid + '/cmdline', 'rb') as h:
                argv = [a.decode('utf-8', 'replace') for a in h.read().split(b'\0') if a][:6]
            uid = os.stat('/proc/' + pid).st_uid
        except OSError:
            continue
        out.append({'pid': int(pid), 'comm': comm, 'argv': argv, 'uid': uid})
    return out


def cgroup_processes(unit):
    cg = run(['systemctl', 'show', unit, '-p', 'ControlGroup', '--value'])[1].strip()
    if not cg:
        return {'control_group': None, 'processes': []}
    try:
        with open('/sys/fs/cgroup' + cg + '/cgroup.procs', encoding='ascii') as h:
            pids = h.read().split()
    except OSError:
        pids = []
    return {'control_group': cg, 'processes': proc_entries(pids)}


def moby_processes():
    found = []
    for pid in os.listdir('/proc'):
        if pid.isdigit():
            try:
                with open('/proc/' + pid + '/comm', encoding='utf-8', errors='replace') as h:
                    comm = h.read().strip()
            except OSError:
                continue
            if comm in MOBY:
                found.append({'pid': int(pid), 'comm': comm})
    return sorted(found, key=lambda e: e['pid'])


def lstat_path(path):
    if not isinstance(path, str) or not path.startswith('/') or '\0' in path or \
            not path.startswith(OBSERVE_ROOTS):
        return {'error': 'not an allowed absolute path'}
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return {'state': 'absent'}
    except OSError as exc:
        return {'state': 'error', 'errno': exc.errno}
    kind = 'dir' if stat.S_ISDIR(st.st_mode) else 'file' if stat.S_ISREG(st.st_mode) else \
        'link' if stat.S_ISLNK(st.st_mode) else 'other'
    entry = {'state': kind, 'uid': st.st_uid, 'gid': st.st_gid,
             'mode': format(stat.S_IMODE(st.st_mode), 'o'), 'mtime': int(st.st_mtime)}
    if kind == 'dir':
        try:
            entry['entries'] = sorted(os.listdir(path))[:50]
        except OSError:
            pass
    return entry


def observe(params):
    units = {u: unit_show(u) for u in UNITS}
    rc, out, _ = run(['ss', '-Hltnp'])
    with open('/proc/sys/kernel/random/boot_id', encoding='ascii') as h:
        boot_id = h.read().strip()
    containers = {}
    for cid, env in container_envs().items():
        containers[cid[:12]] = {'keys': {n: fingerprint(env[n]) for n in AS_VARS if env.get(n)},
                                'variables': sorted(env)}
    dropin = quiesce_dropin = None
    if os.path.lexists(GUARD_DROPIN):
        with open(GUARD_DROPIN, 'rb') as h:
            dropin = sha256_bytes(h.read())
    if os.path.lexists(QUIESCE_DROPIN):
        with open(QUIESCE_DROPIN, 'rb') as h:
            quiesce_dropin = sha256_bytes(h.read())
    with open('/proc/uptime', encoding='ascii') as h:
        uptime = float(h.read().split()[0])
    return {'boot_id': boot_id, 'uptime_s': uptime,
            'units': units, 'guard_dropin_sha256': dropin,
            'quiesce_dropin_sha256': quiesce_dropin,
            'listeners': [line.split()[3] + ' ' + (line.split()[5] if len(line.split()) > 5 else '')
                          for line in out.splitlines() if len(line.split()) > 3],
            'moby_processes': moby_processes(),
            'agent_server': cgroup_processes(AS_UNIT),
            'journal': {u: journal(u, int(params.get('journal_lines', 40))) for u in JOURNAL_UNITS},
            'server_invocation': invocation_journal(AS_UNIT),
            'paths': {p: lstat_path(p) for p in (params.get('paths') or [])[:50]},
            'containers': containers,
            'docker_socket_present': os.path.exists('/run/docker.sock')}


def daemon_reload():
    rc, out, err = run(['systemctl', 'daemon-reload'], 120)
    if rc != 0:
        raise Failed('daemon-reload exited ' + str(rc) + ': ' + err[-300:])


def guard_break(params):
    variant = params.get('variant')
    if variant not in GUARD_VARIANTS:
        raise Failed('unknown guard variant ' + repr(variant))
    os.makedirs(os.path.dirname(GUARD_DROPIN), mode=0o755, exist_ok=True)
    data = GUARD_VARIANTS[variant].encode('ascii')
    with open(GUARD_DROPIN, 'wb') as h:
        h.write(data)
        h.flush()
        os.fsync(h.fileno())
    os.chmod(GUARD_DROPIN, 0o644)
    daemon_reload()
    return {'variant': variant, 'dropin': GUARD_DROPIN, 'sha256': sha256_bytes(data),
            'content': GUARD_VARIANTS[variant], 'unit': unit_show(GUARD_UNIT)}


def guard_restore(params):
    present = os.path.lexists(GUARD_DROPIN)
    if present:
        os.unlink(GUARD_DROPIN)
    daemon_reload()
    return {'removed': present, 'present_after': os.path.lexists(GUARD_DROPIN),
            'unit': unit_show(GUARD_UNIT)}


def write_in_place(path, data, mode=None, uid=None, gid=None):
    """Overwrite (or create) a regular file, never through a link; ownership and mode as
    given or as they were."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode or 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Failed(path + ' is not a regular file')
        os.write(fd, data)
        os.fsync(fd)
        if uid is not None:
            os.fchown(fd, uid, gid)
        if mode is not None:
            os.fchmod(fd, mode)
    finally:
        os.close(fd)


def read_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Failed(path + ' is not a regular file')
        chunks = []
        while True:
            b = os.read(fd, 1 << 20)
            if not b:
                break
            chunks.append(b)
        return b''.join(chunks), st
    finally:
        os.close(fd)


def restart_server(timeout=420):
    t0 = time.monotonic()
    rc, out, err = run(['systemctl', 'restart', AS_UNIT], timeout)
    return {'rc': rc, 'stderr': err.strip()[-600:], 'seconds': round(time.monotonic() - t0, 1),
            'unit': unit_show(AS_UNIT), 'invocation': invocation_journal(AS_UNIT, 120)}


def key_break(params):
    variant = params.get('variant')
    if variant not in KEY_VARIANTS:
        raise Failed('unknown key variant ' + repr(variant))
    original, st = read_regular(AS_SECRETS)
    copy = BACKUP + '/secrets.env'
    if not os.path.lexists(copy):
        write_in_place(copy, original, 0o600, 0, 0)
    good = read_env_file(copy)
    lines = []
    if variant == 'missing-session-key':
        lines = ['OH_SECRET_KEY=' + good['OH_SECRET_KEY']]
    elif variant == 'empty-session-key':
        lines = ['OH_SECRET_KEY=' + good['OH_SECRET_KEY'], 'OH_SESSION_API_KEYS_0=']
    elif variant == 'second-session-key':
        lines = [n + '=' + good[n] for n in AS_VARS] + \
            ['OH_SESSION_API_KEYS_1=' + secrets.token_urlsafe(32)]
    write_in_place(AS_SECRETS, ('\n'.join(lines) + '\n').encode('ascii'),
                   stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid)
    return {'variant': variant, 'variables_written': [line.partition('=')[0] for line in lines],
            'original_sha256': sha256_bytes(original), 'restart': restart_server(120)}


def key_restore(params):
    copy = BACKUP + '/secrets.env'
    original, _ = read_regular(copy)
    _, st = read_regular(AS_SECRETS)
    write_in_place(AS_SECRETS, original, stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid)
    now, _ = read_regular(AS_SECRETS)
    if now != original:
        raise Failed('the environment file differs from its kept copy after the restore')
    os.unlink(copy)
    return {'restored_sha256': sha256_bytes(now), 'copy_removed': not os.path.lexists(copy),
            'restart': restart_server()}


def server_restart(params):
    return restart_server()


def conversation_dir(params):
    hex_id = params.get('hex')
    if not isinstance(hex_id, str) or not HEX32.match(hex_id):
        raise Failed('hex must be a 32-hex conversation id')
    path = CONVERSATIONS + '/' + hex_id
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode):
        raise Failed(path + ' is not a directory')
    return hex_id, path, st


def state_file(params):
    hex_id, cdir, st = conversation_dir(params)
    name = params.get('file')
    if name not in STATE_FILES:
        raise Failed('file must be one of ' + ', '.join(STATE_FILES))
    return hex_id, cdir, st, name, cdir + '/' + name


def state_read(params):
    hex_id, cdir, _ = conversation_dir(params)
    entries = []
    for root, dirs, files in os.walk(cdir):
        for n in sorted(dirs + files):
            p = os.path.join(root, n)
            st = os.lstat(p)
            e = {'path': os.path.relpath(p, cdir), 'uid': st.st_uid, 'gid': st.st_gid,
                 'mode': format(stat.S_IMODE(st.st_mode), 'o'), 'size': st.st_size,
                 'kind': 'dir' if stat.S_ISDIR(st.st_mode) else 'file' if stat.S_ISREG(st.st_mode)
                 else 'other'}
            if e['kind'] == 'file':
                with open(p, 'rb') as h:
                    e['sha256'] = sha256_bytes(h.read())
            entries.append(e)
    content = {}
    for name in STATE_FILES:
        p = cdir + '/' + name
        if os.path.isfile(p) and not os.path.islink(p):
            try:
                content[name] = json.loads(read_regular(p)[0].decode('utf-8'))
            except (ValueError, UnicodeDecodeError) as exc:
                content[name] = {'aieh-drill-unparsed': str(exc)[:200]}
    return {'hex': hex_id, 'entries': entries, 'content': content}


def walk_pointer(doc, pointer):
    """(parent, key) of a JSON pointer given as a list of keys and indices."""
    if not isinstance(pointer, list) or not pointer:
        raise Failed('pointer must be a non-empty list')
    node = doc
    for part in pointer[:-1]:
        if isinstance(node, dict) and isinstance(part, str) and part in node:
            node = node[part]
        elif isinstance(node, list) and isinstance(part, int) and 0 <= part < len(node):
            node = node[part]
        else:
            raise Failed('pointer ' + json.dumps(pointer) + ' does not resolve')
    last = pointer[-1]
    if isinstance(node, dict) and isinstance(last, str):
        return node, last
    if isinstance(node, list) and isinstance(last, int) and 0 <= last < len(node):
        return node, last
    raise Failed('pointer ' + json.dumps(pointer) + ' does not name a field')


def state_alter(params):
    """Set or delete one field of one stored file, or plant an absent one (ownership and mode
    as the stored files have them). state-snapshot keeps the original, state-rollback puts it
    back."""
    hex_id, cdir, dst, name, path = state_file(params)
    op = params.get('op')
    if op not in ('set', 'delete', 'plant'):
        raise Failed('op must be set, delete or plant')
    if not os.path.lexists(SNAPSHOT_FMT.format(hex=hex_id) + '.json'):
        raise Failed('no snapshot of ' + hex_id + ' (state-snapshot first)')
    if os.path.lexists(path):
        original, st = read_regular(path)
        doc = json.loads(original.decode('utf-8'))
    else:
        if op != 'plant':
            raise Failed(name + ' is absent; only plant creates it')
        original, st, doc = None, None, None
    old = None
    if op == 'plant':
        if original is not None:
            raise Failed(name + ' exists; plant only creates')
        doc = params.get('value')
    else:
        parent, key = walk_pointer(doc, params.get('pointer'))
        present = (key in parent) if isinstance(parent, dict) else True
        old = parent[key] if present else '<absent>'
        if op == 'delete':
            if not present:
                raise Failed('pointer names no present field')
            del parent[key]
        else:
            parent[key] = params.get('value')
    data = json.dumps(doc, separators=(',', ':')).encode('utf-8')
    ref = os.lstat(cdir + '/meta.json') if os.path.lexists(cdir + '/meta.json') else dst
    write_in_place(path, data, stat.S_IMODE(st.st_mode) if st else 0o600,
                   st.st_uid if st else ref.st_uid, st.st_gid if st else ref.st_gid)
    return {'hex': hex_id, 'file': name, 'op': op, 'pointer': params.get('pointer'),
            'old': old, 'new': params.get('value') if op != 'delete' else '<deleted>',
            'sha256_before': sha256_bytes(original) if original is not None else None,
            'sha256_after': sha256_bytes(read_regular(path)[0])}


def tree_entries(cdir):
    """{relative path: entry} of a conversation directory, never following a link."""
    out = {}
    for root, dirs, files in os.walk(cdir):
        for n in dirs + files:
            path = os.path.join(root, n)
            st = os.lstat(path)
            rel = os.path.relpath(path, cdir)
            kind = 'dir' if stat.S_ISDIR(st.st_mode) else 'file' if stat.S_ISREG(st.st_mode) \
                else 'other'
            entry = {'kind': kind, 'uid': st.st_uid, 'gid': st.st_gid,
                     'mode': stat.S_IMODE(st.st_mode)}
            if kind == 'file':
                entry['sha256'] = sha256_bytes(read_regular(path)[0])
            out[rel] = entry
    return out


def state_snapshot(params):
    """Keep the whole conversation directory (root-only), to be put back by state-rollback."""
    hex_id, cdir, _ = conversation_dir(params)
    snap = SNAPSHOT_FMT.format(hex=hex_id)
    if os.path.lexists(snap):
        raise Failed(snap + ' exists (state-discard first)')
    os.makedirs(snap, mode=0o700)
    entries = tree_entries(cdir)
    for rel, entry in sorted(entries.items()):
        if entry['kind'] == 'other':
            raise Failed(rel + ' is neither a file nor a directory')
        if entry['kind'] == 'file':
            dst = os.path.join(snap, rel.replace('/', '%2F'))
            write_in_place(dst, read_regular(os.path.join(cdir, rel))[0], 0o600, 0, 0)
    write_in_place(snap + '.json', json.dumps(entries, sort_keys=True).encode('utf-8'), 0o600, 0, 0)
    return {'hex': hex_id, 'entries': len(entries),
            'files': {k: v.get('sha256') for k, v in sorted(entries.items()) if v['kind'] == 'file'}}


def state_rollback(params):
    """Make the conversation directory equal to its snapshot again: remove what was added (by
    an alteration or by a server acting on it), rewrite what changed, recreate what is
    missing, then compare."""
    hex_id, cdir, _ = conversation_dir(params)
    snap = SNAPSHOT_FMT.format(hex=hex_id)
    with open(snap + '.json', encoding='utf-8') as h:
        want = json.load(h)
    now = tree_entries(cdir)
    removed, rewritten = [], []
    for rel in sorted(set(now) - set(want), key=lambda r: r.count('/'), reverse=True):
        path = os.path.join(cdir, rel)
        if now[rel]['kind'] == 'dir':
            for root, dirs, files in os.walk(path, topdown=False):
                for n in files:
                    os.unlink(os.path.join(root, n))
                for n in dirs:
                    full = os.path.join(root, n)
                    os.unlink(full) if os.path.islink(full) else os.rmdir(full)
            os.rmdir(path)
        elif os.path.lexists(path):
            os.unlink(path)
        removed.append(rel)
    for rel, entry in sorted(want.items(), key=lambda kv: kv[0].count('/')):
        path = os.path.join(cdir, rel)
        cur = now.get(rel) if os.path.lexists(path) else None
        if entry['kind'] == 'dir':
            if cur is None:
                os.mkdir(path, entry['mode'])
                rewritten.append(rel)
            elif cur['kind'] != 'dir':
                os.unlink(path)
                os.mkdir(path, entry['mode'])
                rewritten.append(rel)
            os.chown(path, entry['uid'], entry['gid'], follow_symlinks=False)
            os.chmod(path, entry['mode'])
            continue
        if cur is not None and cur['kind'] != 'file':
            raise Failed(rel + ' is now a ' + cur['kind'] + '; not rolled back')
        if cur is None or cur.get('sha256') != entry['sha256'] or \
                (cur['uid'], cur['gid'], cur['mode']) != (entry['uid'], entry['gid'], entry['mode']):
            data = read_regular(os.path.join(snap, rel.replace('/', '%2F')))[0]
            write_in_place(path, data, entry['mode'], entry['uid'], entry['gid'])
            rewritten.append(rel)
    after = tree_entries(cdir)
    return {'hex': hex_id, 'removed': removed, 'rewritten': rewritten, 'equal': after == want}


def state_discard(params):
    hex_id, _, _ = conversation_dir(params) if os.path.lexists(
        CONVERSATIONS + '/' + str(params.get('hex'))) else (params.get('hex'), None, None)
    if not isinstance(hex_id, str) or not HEX32.match(hex_id):
        raise Failed('hex must be a 32-hex conversation id')
    snap = SNAPSHOT_FMT.format(hex=hex_id)
    gone = 0
    if os.path.isdir(snap) and not os.path.islink(snap):
        for n in os.listdir(snap):
            os.unlink(os.path.join(snap, n))
            gone += 1
        os.rmdir(snap)
    if os.path.lexists(snap + '.json'):
        os.unlink(snap + '.json')
    return {'hex': hex_id, 'files_removed': gone, 'present_after': os.path.lexists(snap)}


# ---------------------------------------------------------------- the quiesce step (slice (c))

def quiesce_break(params):
    variant = params.get('variant')
    if variant not in QUIESCE_VARIANTS:
        raise Failed('unknown quiesce variant ' + repr(variant))
    os.makedirs(os.path.dirname(QUIESCE_DROPIN), mode=0o755, exist_ok=True)
    data = QUIESCE_VARIANTS[variant].encode('ascii')
    write_in_place(QUIESCE_DROPIN, data, 0o644, 0, 0)
    daemon_reload()
    return {'variant': variant, 'dropin': QUIESCE_DROPIN, 'sha256': sha256_bytes(data),
            'content': QUIESCE_VARIANTS[variant], 'unit': unit_show(QUIESCE_UNIT)}


def quiesce_restore(params):
    present = os.path.lexists(QUIESCE_DROPIN)
    if present:
        os.unlink(QUIESCE_DROPIN)
    daemon_reload()
    return {'removed': present, 'present_after': os.path.lexists(QUIESCE_DROPIN),
            'unit': unit_show(QUIESCE_UNIT)}


def server_kill(params):
    """SIGKILL every process of the server's unit (the containers live in Moby's cgroups and
    stay up), then wait for systemd's Restart=on-failure start to settle, under a ceiling."""
    t0 = time.monotonic()
    before = unit_show(AS_UNIT)
    n0 = int(before.get('NRestarts') or 0)
    rc, out, err = run(['systemctl', 'kill', '--signal=SIGKILL', AS_UNIT])
    deadline = t0 + float(params.get('ceiling', 420))
    unit = before
    while time.monotonic() < deadline:
        unit = unit_show(AS_UNIT)
        if int(unit.get('NRestarts') or 0) > n0 and unit.get('ActiveState') in ('active', 'failed',
                                                                              'inactive'):
            break
        time.sleep(0.5)
    return {'rc': rc, 'stderr': err.strip()[-600:], 'seconds': round(time.monotonic() - t0, 1),
            'restarts_before': n0, 'unit': unit, 'invocation': invocation_journal(AS_UNIT, 120)}


def monotonic_to_unix(value_us):
    """A systemd CLOCK_MONOTONIC timestamp (microseconds) as Unix time, or None."""
    try:
        value = int(value_us)
    except (TypeError, ValueError):
        return None
    return None if value <= 0 else time.time() - (time.monotonic() - value / 1e6)


def docker_events(since, until):
    """Moby's container events between two Unix times (never socket-activating Moby)."""
    if since is None or until is None or not is_active('docker.service'):
        return None
    fmt = '{' + '{json .}' + '}'
    rc, out, err = run(['docker', 'events', '--since', '%.6f' % since, '--until', '%.6f' % until,
                        '--filter', 'type=container', '--format', fmt], 60)
    if rc != 0:
        return {'error': err.strip()[-300:]}
    events = []
    for line in out.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        events.append({'action': e.get('Action') or e.get('status'),
                       'id': str(e.get('id') or (e.get('Actor') or {}).get('ID') or '')[:12],
                       'time_nano': e.get('timeNano')})
    return events


def quiesce_runs():
    """The quiesce step's summaries of this boot, with their journal times and invocations."""
    rc, out, _ = run(['journalctl', '-b', '-u', QUIESCE_UNIT, '-o', 'json', '--no-pager'], 60)
    runs = []
    for line in out.splitlines() if rc == 0 else []:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get('MESSAGE')
        if isinstance(message, str) and message.startswith(QUIESCE_PREFIX):
            try:
                summary = json.loads(message[len(QUIESCE_PREFIX):])
            except ValueError:
                summary = {'unparsed': True}
            runs.append({'monotonic_us': entry.get('__MONOTONIC_TIMESTAMP'),
                         'invocation': entry.get('_SYSTEMD_INVOCATION_ID'), 'summary': summary})
    return runs


def start_window(params):
    """The last server start's order: the quiesce step's last run (start, exit, summary), the
    server's ExecStart and active state, and Moby's container events in the three windows
    (during the step; between its exit and the server's ExecStart; from ExecStart to active)."""
    q = unit_show(QUIESCE_UNIT)
    s = unit_show(AS_UNIT)
    q_start = monotonic_to_unix(q.get('ExecMainStartTimestampMonotonic'))
    q_exit = monotonic_to_unix(q.get('ExecMainExitTimestampMonotonic'))
    s_start = monotonic_to_unix(s.get('ExecMainStartTimestampMonotonic'))
    s_active = monotonic_to_unix(s.get('ActiveEnterTimestampMonotonic'))
    runs = quiesce_runs()
    return {'quiesce_unit': q, 'server_unit': s, 'runs_this_boot': len(runs),
            'last_run': runs[-1] if runs else None,
            'times': {'quiesce_start': q_start, 'quiesce_exit': q_exit,
                      'server_exec_start': s_start, 'server_active': s_active},
            'events': {'during_quiesce': docker_events(q_start, q_exit),
                       'quiesce_exit_to_server_exec_start': docker_events(q_exit, s_start),
                       'server_exec_start_to_active': docker_events(s_start, s_active)}}


def container_kill(params):
    """SIGKILL the container(s) whose conversation-store bind is this conversation's: no
    shutdown of its inner server runs (the container is --rm, so Moby removes it)."""
    hex_id = params.get('hex')
    if not isinstance(hex_id, str) or not HEX32.match(hex_id):
        raise Failed('hex must be a 32-hex conversation id')
    if not is_active('docker.service'):
        raise Failed('docker.service is not active')
    rc, out, _ = run(['docker', 'ps', '-q', '--no-trunc', '--filter', 'label=' + OWNER_LABEL])
    ids = [i for i in out.split() if HEX64.match(i)] if rc == 0 else []
    mine = []
    if ids:
        rc, out, _ = run(['docker', 'container', 'inspect'] + ids)
        for c in json.loads(out) if rc == 0 else []:
            if any(str(m.get('Source', '')).endswith('/conversations/' + hex_id)
                   for m in c.get('Mounts') or []):
                mine.append(c.get('Id'))
    killed = run(['docker', 'kill', '--signal', 'KILL'] + mine)[0] if mine else None
    left, deadline = mine, time.monotonic() + 60
    while left and time.monotonic() < deadline:
        rc, out, _ = run(['docker', 'ps', '-aq', '--no-trunc'])
        left = [i for i in mine if i in out.split()]
        if left:
            time.sleep(0.5)
    return {'hex': hex_id, 'containers': [i[:12] for i in mine], 'kill_rc': killed,
            'remaining': [i[:12] for i in left]}


def quarantine_list(params):
    out = []
    try:
        names = sorted(os.listdir(QUARANTINE))
    except OSError as exc:
        return {'error': exc.errno}
    for name in names:
        st = os.lstat(os.path.join(QUARANTINE, name))
        out.append({'name': name, 'kind': 'dir' if stat.S_ISDIR(st.st_mode) else
                    'link' if stat.S_ISLNK(st.st_mode) else 'file' if stat.S_ISREG(st.st_mode)
                    else 'other', 'uid': st.st_uid, 'mode': format(stat.S_IMODE(st.st_mode), 'o')})
    st = os.lstat(QUARANTINE)
    return {'entries': out, 'directory': {'uid': st.st_uid, 'gid': st.st_gid,
                                          'mode': format(stat.S_IMODE(st.st_mode), 'o')}}


def quarantine_return(params):
    """Move the newest quarantined entry of a conversation back to the conversations path
    (drill rollback); an entry that took its place meanwhile is moved aside first."""
    hex_id = params.get('hex')
    if not isinstance(hex_id, str) or not HEX32.match(hex_id):
        raise Failed('hex must be a 32-hex conversation id')
    names = sorted(n for n in os.listdir(QUARANTINE) if n.startswith(hex_id + '.') and
                   '.displaced.' not in n)
    if not names:
        raise Failed('no quarantined entry of ' + hex_id)
    target = CONVERSATIONS + '/' + hex_id
    displaced = None
    if os.path.lexists(target):
        displaced = hex_id + '.displaced.' + secrets.token_hex(4)
        os.rename(target, QUARANTINE + '/' + displaced)
    os.rename(QUARANTINE + '/' + names[-1], target)
    return {'hex': hex_id, 'returned': names[-1], 'displaced': displaced}


def sentinel_paths(params):
    hex_id, cdir, _ = conversation_dir(params)
    kind = params.get('kind')
    if kind not in SENTINEL_KINDS:
        raise Failed('kind must be one of ' + ', '.join(SENTINEL_KINDS))
    return hex_id, cdir, kind, SENTINEL_DIR + '/' + hex_id + '-' + kind


def sentinel_plant(params):
    """Replace base_state.json by a symbolic or hard link to a sentinel file outside the
    record (a copy of it saying running, the same owner and mode), and set the sentinel's
    access time an hour before its mtime, so that any later read moves it (relatime)."""
    hex_id, cdir, kind, sentinel = sentinel_paths(params)
    base = cdir + '/base_state.json'
    data, st = read_regular(base)
    doc = json.loads(data.decode('utf-8'))
    doc['execution_status'] = 'running'
    content = json.dumps(doc, separators=(',', ':')).encode('utf-8')
    os.makedirs(SENTINEL_DIR, mode=0o711, exist_ok=True)
    os.chmod(SENTINEL_DIR, 0o711)
    if os.path.lexists(sentinel):
        raise Failed(sentinel + ' exists')
    write_in_place(sentinel, content, stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid)
    os.unlink(base)
    if kind == 'symlink':
        os.symlink(sentinel, base)
    else:
        os.link(sentinel, base)
    s1 = os.lstat(sentinel)
    os.utime(sentinel, ns=(s1.st_mtime_ns - 3600 * 10 ** 9, s1.st_mtime_ns), follow_symlinks=False)
    s2 = os.lstat(sentinel)
    record = {'path': sentinel, 'sha256': sha256_bytes(content), 'ino': s2.st_ino,
              'size': s2.st_size, 'atime_ns': s2.st_atime_ns, 'mtime_ns': s2.st_mtime_ns,
              'ctime_ns': s2.st_ctime_ns, 'nlink': s2.st_nlink}
    write_in_place(sentinel + '.record', json.dumps(record).encode('ascii'), 0o600, 0, 0)
    link = os.lstat(base)
    return dict(record, kind=kind, base_is_link=stat.S_ISLNK(link.st_mode),
                base_nlink=link.st_nlink)


def sentinel_check(params):
    """Was the sentinel read or written since it was planted? (atime, mtime, ctime, size and
    inode unchanged; then its sha256.) The control: the sha256 read itself must move atime."""
    hex_id = params.get('hex')
    kind = params.get('kind')
    if not isinstance(hex_id, str) or not HEX32.match(hex_id) or kind not in SENTINEL_KINDS:
        raise Failed('hex and kind needed')
    sentinel = SENTINEL_DIR + '/' + hex_id + '-' + kind
    with open(sentinel + '.record', encoding='ascii') as h:
        record = json.load(h)
    s = os.lstat(sentinel)
    now = {'ino': s.st_ino, 'size': s.st_size, 'atime_ns': s.st_atime_ns,
           'mtime_ns': s.st_mtime_ns, 'ctime_ns': s.st_ctime_ns}
    unread = now['atime_ns'] == record['atime_ns']
    unwritten = all(now[k] == record[k] for k in ('ino', 'size', 'mtime_ns', 'ctime_ns'))
    data, _ = read_regular(sentinel)
    after = os.lstat(sentinel)
    return {'sentinel': sentinel, 'record': record, 'now': now, 'nlink': s.st_nlink,
            'unread': unread, 'unwritten': unwritten,
            'sha256_equal': sha256_bytes(data) == record['sha256'],
            'control_read_moved_atime': after.st_atime_ns != s.st_atime_ns}


# ---------------------------------------------------------------- root P5 scan

def mounts():
    out = []
    with open('/proc/self/mountinfo', encoding='utf-8', errors='replace') as h:
        for line in h:
            left, _, right = line.partition(' - ')
            parts, rparts = left.split(), right.split()
            if len(parts) < 5 or len(rparts) < 2:
                continue
            out.append({'target': parts[4].replace('\\040', ' '), 'fstype': rparts[0],
                        'source': rparts[1]})
    return out


def scan_data(data, base, needles, cores, hits, found_keys, owner, label_path):
    """One window of a file: secret values by exact bytes, canary cores by sha256, private
    key blocks by body sha256, Owner-class patterns by count. ``base`` is the window's
    offset (positions dedupe the overlap)."""
    for label, value in needles.items():
        start = 0
        while True:
            i = data.find(value, start)
            if i < 0:
                break
            hits.setdefault(label, {}).setdefault(label_path, set()).add(base + i)
            start = i + 1
    for m in CORE.finditer(data):
        digest = sha256_bytes(m.group(0))
        if digest in cores:
            hits.setdefault(cores[digest], {}).setdefault(label_path, set()).add(base + m.start())
    if b'PRIVATE KEY-----' in data:
        for m in KEY_BLOCK.finditer(data):
            body = b''.join(m.group(2).split())
            found_keys.setdefault((label_path, sha256_bytes(body)), (m.group(1).decode(
                'ascii', 'replace').strip() or 'PKCS8', base + m.start()))
    for cls, regexes in owner.items():
        if not any(p in data for p in OWNER_PREFILTER.get(cls, (b'',))):
            continue
        for rx in regexes:
            for m in rx.finditer(data):
                hits.setdefault('owner:' + cls, {}).setdefault(label_path, set()).add(base + m.start())


def scan_file(path, needles, cores, hits, found_keys, owner, label_path=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    total = 0
    try:
        tail, base = b'', 0
        while True:
            chunk = os.read(fd, CHUNK)
            if not chunk:
                break
            data = tail + chunk
            scan_data(data, base - len(tail), needles, cores, hits, found_keys, owner,
                      label_path or path)
            total += len(chunk)
            base += len(chunk)
            tail = data[-OVERLAP:]
    finally:
        os.close(fd)
    return total


def raw_count(device, needles, cores, deadline):
    """Occurrences per label on a raw block device; all-zero chunks are skipped."""
    counts, read, nonzero = {}, 0, 0
    zero = bytes(CHUNK)
    fd = os.open(device, os.O_RDONLY)
    try:
        tail, base = b'', 0
        while time.monotonic() < deadline:
            chunk = os.read(fd, CHUNK)
            if not chunk:
                break
            read += len(chunk)
            if chunk == zero[:len(chunk)]:
                tail, base = b'', base + len(chunk)
                continue
            nonzero += len(chunk)
            data = tail + chunk
            hits = {}
            scan_data(data, base - len(tail), needles, cores, hits, {}, {}, device)
            for label, where in hits.items():
                counts[label] = counts.get(label, set()) | where.get(device, set())
            tail, base = data[-OVERLAP:], base + len(chunk)
        complete = time.monotonic() < deadline
    finally:
        os.close(fd)
    return {'bytes_read': read, 'bytes_nonzero': nonzero, 'complete': complete,
            'counts': {k: len(v) for k, v in sorted(counts.items())}}


def root_scan(params):
    t0 = time.monotonic()
    deadline = t0 + float(params.get('max_seconds', 1500))
    cores = {}
    for label, digest in (params.get('canary_core_sha256') or {}).items():
        if not isinstance(label, str) or not isinstance(digest, str) or not HEX64.match(digest):
            raise Failed('canary_core_sha256 must map labels to sha256 hex')
        cores[digest] = 'canary:' + label
    # the positive control: a fresh canary-shaped value and a private-key block in a
    # root-only file outside every store, found by the same matchers, then removed
    os.makedirs(CONTROL, mode=0o700, exist_ok=True)
    core = secrets.token_hex(16).encode()
    body = secrets.token_urlsafe(48).encode()
    control_path = CONTROL + '/p5-control-' + secrets.token_hex(4)
    write_in_place(control_path, b'aieh-drill-control-canary-' + core + b'\n' +
                   ARMOR.format('BEGIN').encode() + b'\n' + body + b'\n' +
                   ARMOR.format('END').encode() + b'\n', 0o600, 0, 0)
    cores[sha256_bytes(core)] = 'control:canary'
    control_key = sha256_bytes(body)
    os.sync()
    values = known_secrets()
    needles = {'secret:' + k: v.encode() for k, v in values.items()
               if SECRET_VALUE.match(v)}
    needles['control:secret'] = secrets.token_urlsafe(32).encode()
    write_in_place(control_path + '.secret', needles['control:secret'] + b'\n', 0o600, 0, 0)
    owner = {k: [re.compile(rx) for rx in v] for k, v in OWNER_PATTERNS.items()}
    hits, found_keys, errors, scanned = {}, {}, [], {'files': 0, 'bytes': 0}
    walked = []
    for m in mounts():
        if m['fstype'] not in SCAN_FSTYPES or m['target'] in walked:
            continue
        walked.append(m['target'])
        try:
            dev = os.lstat(m['target']).st_dev
        except OSError:
            continue
        for root, dirs, files in os.walk(m['target']):
            if time.monotonic() > deadline:
                break
            keep = []
            for d in dirs:
                p = os.path.join(root, d)
                try:
                    if os.lstat(p).st_dev == dev:
                        keep.append(d)
                except OSError:
                    pass
            dirs[:] = keep
            for n in files:
                p = os.path.join(root, n)
                try:
                    st = os.lstat(p)
                    if not stat.S_ISREG(st.st_mode) or st.st_dev != dev:
                        continue
                    scanned['bytes'] += scan_file(p, needles, cores, hits, found_keys, owner)
                    scanned['files'] += 1
                except OSError as exc:
                    if len(errors) < 50:
                        errors.append({'path': p, 'errno': exc.errno})
    procs = 0
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        for part in ('environ', 'cmdline'):
            try:
                with open('/proc/' + pid + '/' + part, 'rb') as h:
                    data = h.read()
            except OSError:
                continue
            procs += 1
            scan_data(data, 0, needles, cores, hits, found_keys, owner,
                      '/proc/' + pid + '/' + part)
    raw = {}
    if params.get('raw'):
        os.sync()
        for m in mounts():
            if m['fstype'] in ('ext4', 'ext3', 'ext2', 'xfs', 'btrfs', 'vfat') and \
                    m['source'].startswith('/dev/') and m['source'] not in raw:
                raw[m['source']] = dict(raw_count(m['source'], needles, cores, deadline),
                                        mount=m['target'])
    for p in (control_path, control_path + '.secret'):
        os.unlink(p)
    result_hits = {}
    for label, where in sorted(hits.items()):
        result_hits[label] = [{'path': p, 'count': len(offs)} for p, offs in sorted(where.items())]
    return {'mounts_walked': walked, 'files': scanned['files'], 'bytes': scanned['bytes'],
            'proc_files': procs, 'errors': errors, 'complete': time.monotonic() <= deadline,
            'seconds': round(time.monotonic() - t0, 1),
            'secrets': {k: fingerprint(v) for k, v in sorted(values.items())},
            'control': {'path': control_path, 'canary_core_sha256': sha256_bytes(core),
                        'key_body_sha256': control_key, 'removed': not os.path.lexists(control_path)},
            'hits': result_hits,
            'key_blocks': [{'path': p, 'body_sha256': d, 'kind': k, 'offset': off}
                           for (p, d), (k, off) in sorted(found_keys.items())],
            'process_owners': {p: proc_owner(p) for p in sorted({e['path'] for v in result_hits.values()
                                                                   for e in v if e['path'].startswith('/proc/')})},
            'raw': raw}


def proc_owner(path):
    """The unit (systemd cgroup) and comm of a /proc/<pid>/... path."""
    pid = path.split('/')[2]
    try:
        with open('/proc/' + pid + '/cgroup', encoding='utf-8') as h:
            cg = h.read().strip().split('::', 1)[-1]
        with open('/proc/' + pid + '/comm', encoding='utf-8') as h:
            comm = h.read().strip()
        return {'cgroup': cg, 'comm': comm, 'uid': os.stat('/proc/' + pid).st_uid}
    except OSError:
        return None


ACTIONS = {'observe': observe, 'guard-break': guard_break, 'guard-restore': guard_restore,
           'key-break': key_break, 'key-restore': key_restore, 'server-restart': server_restart,
           'state-read': state_read, 'state-alter': state_alter, 'state-snapshot': state_snapshot,
           'state-rollback': state_rollback, 'state-discard': state_discard, 'root-scan': root_scan,
           'quiesce-break': quiesce_break, 'quiesce-restore': quiesce_restore,
           'server-kill': server_kill, 'start-window': start_window,
           'container-kill': container_kill, 'quarantine-list': quarantine_list,
           'quarantine-return': quarantine_return, 'sentinel-plant': sentinel_plant,
           'sentinel-check': sentinel_check}


def redact(text, values):
    count = 0
    for value in sorted(set(values), key=len, reverse=True):
        if value and len(value) >= 16:
            count += text.count(value)
            text = text.replace(value, '<redacted>')
    return text, count


def read_request(agent_uid):
    fd = os.open(REQUEST, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        os.unlink(REQUEST)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != agent_uid or st.st_size > REQUEST_MAX:
            raise Failed('the request is not a regular file of agent within ' + str(REQUEST_MAX))
        data = os.read(fd, REQUEST_MAX + 1)
    finally:
        os.close(fd)
    req = json.loads(data.decode('utf-8'))
    if not isinstance(req, dict) or not REQUEST_ID.match(str(req.get('id'))) or \
            req.get('action') not in ACTIONS or not isinstance(req.get('params', {}), dict):
        raise Failed('the request needs an id, a known action and a params object')
    return req


def serve():
    agent = pwd.getpwnam(AGENT)
    started = time.monotonic()
    try:
        req = read_request(agent.pw_uid)
    except FileNotFoundError:
        return 0
    except (Failed, OSError, ValueError) as exc:
        try:
            os.unlink(REQUEST)            # never leave a request that re-triggers the path unit
        except OSError:
            pass
        print('aieh-drill: refused request: ' + str(exc)[:300], flush=True)
        return 1
    secrets_before = list(known_secrets().values())
    out = {'schema': SCHEMA, 'id': req['id'], 'action': req['action'],
           'params': req.get('params', {}), 'started_monotonic': started}
    try:
        out['detail'] = ACTIONS[req['action']](req.get('params', {}))
        out['ok'] = True
    except Exception as exc:              # every failure is reported with the request
        out['ok'], out['error'] = False, (type(exc).__name__ + ': ' + str(exc))[:1000]
    out['seconds'] = round(time.monotonic() - started, 1)
    text = json.dumps(out, sort_keys=True, default=str)
    text, count = redact(text, secrets_before + list(known_secrets().values()))
    out = json.loads(text)
    out['secret_occurrences_redacted'] = count
    data = json.dumps(out, sort_keys=True).encode('utf-8')
    tmp = RESULTS + '/.' + req['id'] + '.tmp'
    write_in_place(tmp, data, 0o640, 0, agent.pw_gid)
    os.rename(tmp, RESULTS + '/' + req['id'] + '.json')
    print('aieh-drill: ' + req['action'] + ' ' + ('ok' if out.get('ok') else 'failed'), flush=True)
    return 0


PATH_UNIT_TEXT = '''[Unit]
Description=AIEH drill request (TEST ONLY, plan leaf E-01.2.2 slice (b); drill guests only)

[Path]
PathExists=/var/lib/aieh-drill/request/request.json

[Install]
WantedBy=paths.target
'''
SERVICE_TEXT = '''[Unit]
Description=AIEH drill root helper (TEST ONLY, plan leaf E-01.2.2 slice (b); drill guests only)
StartLimitIntervalSec=0

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I /usr/local/sbin/aieh-drill serve
TimeoutStartSec=1800
StandardOutput=journal+console
StandardError=journal+console
'''


def install(source):
    """First boot (cloud-init, root): this file as SELF, the directories and the units."""
    with open(source, 'rb') as h:
        data = h.read()
    agent = pwd.getpwnam(AGENT)
    write_in_place(SELF, data, 0o755, 0, 0)
    for path, mode, gid in ((ROOT, 0o755, 0), (REQUEST_DIR, 0o730, agent.pw_gid),
                            (RESULTS, 0o750, agent.pw_gid), (BACKUP, 0o700, 0)):
        os.makedirs(path, mode=mode, exist_ok=True)
        os.chown(path, 0, gid, follow_symlinks=False)
        os.chmod(path, mode)
    for unit, text in ((PATH_UNIT, PATH_UNIT_TEXT), (SERVICE, SERVICE_TEXT)):
        write_in_place('/etc/systemd/system/' + unit, text.encode('ascii'), 0o644, 0, 0)
    daemon_reload()
    rc, out, err = run(['systemctl', 'enable', '--now', PATH_UNIT])
    print('aieh-drill: installed ' + sha256_bytes(data) + ' path unit rc ' + str(rc), flush=True)
    return 0 if rc == 0 else 1


def main(argv):
    if os.geteuid() != 0:
        print('aieh-drill: must run as root', flush=True)
        return 2
    os.umask(0o022)
    if argv == ['serve']:
        return serve()
    if argv == []:
        return install(os.path.abspath(sys.argv[0]))
    print('aieh-drill: usage: aieh-drill [serve]', flush=True)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
