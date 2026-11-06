"""Guest lifecycle for the QEMU/WHPX strong profile (plan leaf F-03.2.2).

Implements ``lifecycle.bindings`` of ``profiles/strong-windows-qemu-whpx/profile.json``
under the execution-profile contract (``profiles/README.md``, section 3):

    preflight  read-only capability report; each failure names its Owner act
    create     new instance directory, SSH key, image check, overlays, seed, ports,
               launch.json, detached QEMU, then readiness (QMP, serial host keys,
               SSH, cloud-init)
    start      relaunch from launch.json after re-checking every digest in it
    stop       QMP system_powerdown; after stop_timeout_s QMP quit; then terminate
               that process id only
    destroy    stop with force if running, then delete the instance directory only;
               an absent instance succeeds and reports "absent"
    recreate   destroy, then create with the same name and profile
    inspect    QMP queries, qemu-img info, host bindings and guest probes, recorded
               per profiles P1-P12 and labelled per profiles P11
    exec       ssh to agent@127.0.0.1 with the profile's client options (operators
               and provisioning only; never offered to agents)

The exchange operations are F-03.3.1 and are not implemented here.

Usage (from the repository root; the profile and state directory are always named,
never defaulted, contract sections 4 and 11):
    python -I -B tools/guest.py preflight --profile PROFILE --state-dir STATE
    python -I -B tools/guest.py create    --profile PROFILE --state-dir STATE --name NAME
    python -I -B tools/guest.py inspect   --profile PROFILE --state-dir STATE --name NAME
    python -I -B tools/guest.py exec      --profile PROFILE --state-dir STATE --name NAME -- CMD
    (start, stop, destroy and recreate take the same arguments as inspect)

Every operation prints one JSON object on stdout; progress goes to stderr. Records
are written under STATE/instances/NAME/records/. Exit status 0 on success, 1 on a
refusal or failure (``REFUSED <code>: <reason>`` on stderr), and for exec the remote
command's status.

Standard library only; run with ``python -I -B``. Process control uses the Windows
API through ctypes, so the lifecycle runs on Windows only (the profile's host).
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LAUNCH_SCHEMA = 'ai-engineering-harness/profiles/launch-record/v1'
INSPECT_SCHEMA = 'ai-engineering-harness/profiles/inspect-record/v1'
LOOPBACK = '127.0.0.1'
GUEST_USER_HOST = '127.0.0.1'
PLACEHOLDER = re.compile(r'\{([a-z_]+(?::[a-z_]+)?)\}')
NAME_DEFAULT = r'^[a-z][a-z0-9-]{1,40}$'
QMP_WAIT_S = 60          # ceiling for QEMU to open its QMP socket after launch
QUIT_WAIT_S = 30         # ceiling for QEMU to exit after QMP quit
TERMINATE_WAIT_S = 10    # ceiling for the process to vanish after TerminateProcess
POLL_S = 1.0             # interval for conditions that expose no completion signal
READY_TIMEOUT_S = 600    # default overall readiness ceiling
# The environment QEMU and qemu-img are launched with (profiles P5: the provider's
# launch environment is scrubbed to an allowlist). PATH, TEMP and TMP are set here.
ENV_ALLOW = ('SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'NUMBER_OF_PROCESSORS',
             'PROCESSOR_ARCHITECTURE', 'OS')
# Harness additions to identity.ssh_client_options: never prompt, never consult the
# Owner's ssh-agent or a machine-wide known_hosts, bound the connect.
SSH_EXTRA_OPTIONS = ('-o', 'BatchMode=yes', '-o', 'IdentityAgent=none',
                     '-o', 'GlobalKnownHostsFile=none', '-o', 'ConnectTimeout=15')
INTERRUPT_WARNING = 'Ignoring request for interrupt vector 0'
# query-pci: devices allowed on the q35 machine. Intel ids are the q35 chipset
# functions QEMU always creates (MCH host bridge, ICH9 LPC, AHCI, SMBus); virtio ids
# (vendor 0x1af4) are counted against launch.argv's -device list.
Q35_BUILTIN = {(0x8086, 0x29c0): 'q35 host bridge', (0x8086, 0x2918): 'ICH9 LPC',
               (0x8086, 0x2922): 'ICH9 AHCI', (0x8086, 0x2930): 'ICH9 SMBus'}
VIRTIO_IDS = {0x1001: 'virtio-blk-pci', 0x1042: 'virtio-blk-pci',
              0x1000: 'virtio-net-pci', 0x1041: 'virtio-net-pci',
              0x1005: 'virtio-rng-pci', 0x1044: 'virtio-rng-pci'}
SHARE_FSTYPES = '9p,virtiofs,drvfs,fuse,fuse.sshfs,cifs,smb3,nfs,nfs4'


class Refused(Exception):
    """A refusal with a machine-readable code (for example TIER_UNAVAILABLE)."""

    def __init__(self, code, message, detail=None):
        super().__init__(message)
        self.code = code
        self.detail = detail


def log(message):
    print(f'{utc_now()} {message}', file=sys.stderr, flush=True)


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def posix(path):
    return str(path).replace('\\', '/')


# ---------------------------------------------------------------- profile and paths


def load_profile(profile_arg):
    path = Path(profile_arg)
    if path.is_dir():
        path = path / 'profile.json'
    path = path.resolve()
    if path.parent.parent.name != 'profiles':
        raise Refused('REFUSED', f'profile {path}: not at profiles/<name>/profile.json')
    try:
        profile = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise Refused('REFUSED', f'profile {path}: cannot read ({exc})') from exc
    if profile.get('name') != path.parent.name:
        raise Refused('REFUSED', f'profile {path}: name differs from its directory')
    if (profile.get('provider') or {}).get('name') != 'qemu':
        raise Refused('REFUSED', f'profile {profile.get("name")}: guest.py implements the '
                      'qemu provider only')
    return profile, path, path.parents[2]


def labels(profile):
    lab = profile.get('labels') or {}
    return {key: lab.get(key) for key in ('tier', 'provider', 'nesting')}


def check_name(profile, name):
    pattern = (profile.get('identity') or {}).get('instance_name_pattern') or NAME_DEFAULT
    if not isinstance(name, str) or not re.fullmatch(pattern, name):
        raise Refused('REFUSED', f'instance name {name!r} does not match {pattern}')
    return name


def inside(child, parent):
    child = os.path.normcase(os.path.abspath(child))
    parent = os.path.normcase(os.path.abspath(parent))
    return child == parent or child.startswith(parent.rstrip('\\/') + os.sep)


def check_state_dir(state_dir, repo_root=REPO, environ=None):
    """Contract section 11: named, existing, outside the checkout and the Owner's profile."""
    environ = os.environ if environ is None else environ
    if not state_dir:
        raise Refused('TIER_UNAVAILABLE', 'state directory not named (A3)')
    path = Path(state_dir)
    if not path.is_absolute():
        raise Refused('TIER_UNAVAILABLE', f'state directory {state_dir} is not absolute (A3)')
    if ',' in str(path):
        raise Refused('TIER_UNAVAILABLE', f'state directory {state_dir} contains a comma, '
                      'which breaks QEMU option syntax (A3)')
    if not path.is_dir():
        raise Refused('TIER_UNAVAILABLE', f'state directory {state_dir} does not exist (A3)')
    if inside(path, repo_root):
        raise Refused('TIER_UNAVAILABLE', f'state directory {state_dir} is inside the '
                      'checkout (A3)')
    for var in ('USERPROFILE', 'HOME'):
        home = environ.get(var)
        if home and inside(path, home):
            raise Refused('TIER_UNAVAILABLE', f'state directory {state_dir} is inside '
                          f'%{var}% (A3)')
    return path


def expand(template, values):
    """Substitute {key} placeholders; refuse any placeholder that has no value."""
    def sub(match):
        key = match.group(1)
        if key not in values:
            raise Refused('REFUSED', f'no value for placeholder {{{key}}} in {template!r}')
        return str(values[key])
    out = PLACEHOLDER.sub(sub, template)
    if PLACEHOLDER.search(out):
        raise Refused('REFUSED', f'placeholder left in {out!r}')
    return out


def resolve_values(profile, state_dir, name=None, ports=None):
    """The placeholder values of the profile's layout, inputs and launch.argv."""
    layout = (profile.get('state_dir') or {}).get('layout') or {}
    inputs = profile.get('boot_inputs') or {}
    values = {'state_dir': posix(state_dir)}
    values['qemu_prefix'] = expand(layout['qemu_prefix'], values)
    if name is not None:
        values['instance'] = name
        values['instance_dir'] = expand(layout['instance_dir'], values)
        values['input:seed'] = expand(inputs['seed']['local_path'], values)
    values['input:image'] = expand(inputs['image']['local_path'], values)
    values['input:firmware'] = expand(inputs['firmware']['path'], values)
    if ports is not None:
        values['ssh_port'] = str(ports['ssh'])
        values['qmp_port'] = str(ports['qmp'])
    return values


def binaries(profile, values):
    provider = profile.get('provider') or {}
    return {key: {'path': expand(entry['path'], values), 'sha256': entry['sha256']}
            for key, entry in (provider.get('binaries') or {}).items()}


def launch_binary(profile, values):
    ref = (profile.get('launch') or {}).get('binary', '')
    key = ref.split('.', 2)[2] if ref.startswith('provider.binaries.') else None
    entry = binaries(profile, values).get(key)
    if entry is None:
        raise Refused('REFUSED', f'launch.binary {ref!r} names no provider binary')
    return entry


def render_argv(profile, values):
    """The full QEMU command line: the launch binary, then launch.argv substituted."""
    argv = (profile.get('launch') or {}).get('argv')
    if not isinstance(argv, list) or not argv:
        raise Refused('REFUSED', 'launch.argv missing')
    return [launch_binary(profile, values)['path']] + [expand(a, values) for a in argv]


def render_disk_commands(profile, values):
    """qemu-img argv for each per-instance disk, from launch.per_instance_files."""
    out = {}
    bins = binaries(profile, values)
    for name, command in ((profile.get('launch') or {}).get('per_instance_files') or {}).items():
        tokens = command.split()
        if not tokens or tokens[0] != 'qemu-img':
            continue          # seed.iso is generated by tools/nocloud_seed.py
        out[name] = [bins['qemu-img']['path']] + [expand(t, values) for t in tokens[1:]]
    return out


def scrubbed_env(values, temp_dir=None, environ=None):
    environ = os.environ if environ is None else environ
    env = {key: environ[key] for key in ENV_ALLOW if key in environ}
    system32 = os.path.join(environ.get('SYSTEMROOT', r'C:\Windows'), 'System32')
    env['PATH'] = os.pathsep.join([str(Path(values['qemu_prefix']) / 'ucrt64' / 'bin'),
                                   system32])
    if temp_dir is not None:
        env['TEMP'] = env['TMP'] = str(temp_dir)
    return env


def openssh(tool):
    """Windows' built-in OpenSSH client tools (never a PATH lookup)."""
    path = Path(os.environ.get('SYSTEMROOT', r'C:\Windows')) / 'System32' / 'OpenSSH' / tool
    if not path.is_file():
        raise Refused('REFUSED', f'{path} not found: the built-in OpenSSH client is required')
    return str(path)


def allocate_ports(count=2, host=LOOPBACK):
    """Distinct free TCP ports on 127.0.0.1, chosen by the OS (held until all are known)."""
    sockets, ports = [], []
    try:
        for _ in range(count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind((host, 0))
            sockets.append(sock)
            ports.append(sock.getsockname()[1])
    finally:
        for sock in sockets:
            sock.close()
    if len(set(ports)) != count:
        raise Refused('REFUSED', f'port allocation returned duplicates {ports}')
    return ports


def port_free(port, host=LOOPBACK):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


class Context:
    def __init__(self, profile_arg, state_dir, repo_root=None):
        self.profile, self.profile_path, root = load_profile(profile_arg)
        self.repo = Path(repo_root) if repo_root else root
        self.state_dir = check_state_dir(state_dir, self.repo)
        self.values = resolve_values(self.profile, self.state_dir)

    def instance_dir(self, name):
        check_name(self.profile, name)
        path = Path(resolve_values(self.profile, self.state_dir, name)['instance_dir'])
        instances = Path(self.state_dir) / 'instances'
        if path.parent.resolve() != instances.resolve() or path.name != name:
            raise Refused('REFUSED', f'instance directory {path} is not '
                          f'{instances}{os.sep}{name}')
        return path


# ---------------------------------------------------------------- records


def write_json_exclusive(path, data):
    with open(path, 'x', encoding='utf-8', newline='\n') as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write('\n')


def write_record(instance_dir, operation, data):
    records = Path(instance_dir) / 'records'
    records.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = records / f'{operation}-{stamp}.json'
    write_json_exclusive(path, data)
    return str(path)


def read_launch_record(instance_dir):
    path = Path(instance_dir) / 'launch.json'
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise Refused('REFUSED', f'{path}: cannot read the launch record ({exc})') from exc
    if record.get('schema') != LAUNCH_SCHEMA:
        raise Refused('REFUSED', f'{path}: schema is not {LAUNCH_SCHEMA}')
    return record


def build_launch_record(profile, profile_path, values, name, instance_id, ports, revision,
                        inputs, argv, env, disk_commands):
    """launch.json: every boot input with its digest, the argv and the profile revision."""
    return {
        'schema': LAUNCH_SCHEMA,
        'labels': labels(profile),
        'profile': {'name': profile['name'],
                    'path': posix(Path(profile_path).relative_to(Path(profile_path).parents[2])),
                    'sha256': sha256_file(profile_path)},
        'profile_revision': revision,
        'instance': {'name': name, 'instance_id': instance_id,
                     'instance_dir': values['instance_dir']},
        'host_principal': host_principal(),
        'created_at': utc_now(),
        'ports': {'ssh': ports['ssh'], 'qmp': ports['qmp'], 'bind': LOOPBACK},
        'inputs': inputs,
        'per_instance_files': disk_commands,
        'binary': argv[0],
        'argv': argv,
        'env': env,
    }


def verify_inputs(record):
    """Re-hash every input in the launch record; a mismatch refuses the launch (P9)."""
    results = {}
    for key, entry in sorted((record.get('inputs') or {}).items()):
        path = entry.get('path')
        try:
            got = sha256_file(path)
        except OSError as exc:
            raise Refused('DIGEST_MISMATCH', f'input {key}: {path} cannot be read ({exc})') from exc
        results[key] = {'path': path, 'sha256': got, 'recorded': entry.get('sha256'),
                        'match': got == entry.get('sha256')}
        if got != entry.get('sha256'):
            raise Refused('DIGEST_MISMATCH', f'input {key}: {path} has sha256 {got}, the '
                          f'launch record has {entry.get("sha256")}', results)
    return results


def host_principal():
    domain = os.environ.get('USERDOMAIN')
    user = os.environ.get('USERNAME') or os.environ.get('USER')
    return f'{domain}\\{user}' if domain and user else user


def profile_revision(repo):
    """git rev-parse HEAD; refuse when profiles/ has uncommitted changes."""
    def git(*args):
        return subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                              text=True, check=False)
    head = git('rev-parse', 'HEAD')
    if head.returncode != 0:
        raise Refused('REFUSED', f'git rev-parse HEAD failed: {head.stderr.strip()}')
    status = git('status', '--porcelain', '--untracked-files=all', '--', 'profiles')
    if status.returncode != 0:
        raise Refused('REFUSED', f'git status failed: {status.stderr.strip()}')
    if status.stdout.strip():
        raise Refused('REFUSED', 'profiles/ has uncommitted changes; create records the '
                      'profile revision and refuses a dirty profile', status.stdout.splitlines())
    return {'kind': 'git-revision', 'head': head.stdout.strip(), 'profiles_clean': True}


# ---------------------------------------------------------------- processes (Windows)


class WinProcess:
    """A handle on one process id: image path, creation time, wait, terminate."""
    SYNCHRONIZE = 0x00100000
    PROCESS_TERMINATE = 0x0001
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes
        self._ct, self._wt = ctypes, wintypes
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                                 wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD))
        k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._k = k
        self.pid = pid
        self._h = k.OpenProcess(self.SYNCHRONIZE | self.PROCESS_TERMINATE |
                                self.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not self._h:
            raise OSError(ctypes.get_last_error(), f'OpenProcess({pid}) failed')

    def image(self):
        size = self._wt.DWORD(32768)
        buf = self._ct.create_unicode_buffer(size.value)
        if not self._k.QueryFullProcessImageNameW(self._h, 0, buf, self._ct.byref(size)):
            raise OSError(self._ct.get_last_error(), 'QueryFullProcessImageNameW failed')
        return buf.value

    def created(self):
        times = [self._wt.FILETIME() for _ in range(4)]
        if not self._k.GetProcessTimes(self._h, *[self._ct.byref(t) for t in times]):
            raise OSError(self._ct.get_last_error(), 'GetProcessTimes failed')
        value = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return value / 1e7 - 11644473600

    def alive(self):
        code = self._wt.DWORD()
        self._k.GetExitCodeProcess(self._h, self._ct.byref(code))
        return code.value == self.STILL_ACTIVE

    def wait(self, seconds):
        """Wait on the process handle itself; True when it has exited."""
        return self._k.WaitForSingleObject(self._h, int(seconds * 1000)) == 0

    def terminate(self):
        if not self._k.TerminateProcess(self._h, 1):
            raise OSError(self._ct.get_last_error(), 'TerminateProcess failed')

    def close(self):
        if self._h:
            self._k.CloseHandle(self._h)
            self._h = None


def same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def running_process(instance_dir, expected_binary):
    """The instance's QEMU process if it still runs, else None.

    The process id comes from process.json (written at launch). It is trusted only when
    the process runs the profile's QEMU binary and was created at the recorded launch.
    """
    path = Path(instance_dir) / 'process.json'
    if not path.is_file():
        return None
    info = json.loads(path.read_text(encoding='utf-8'))
    if os.name != 'nt':
        raise Refused('REFUSED', 'process control is implemented for Windows only')
    try:
        proc = WinProcess(int(info['pid']))
    except OSError:
        return None
    try:
        if not proc.alive() or not same_path(proc.image(), expected_binary):
            proc.close()
            return None
        if not info['launched_at_epoch'] - 5 <= proc.created() <= info['launched_at_epoch'] + 120:
            proc.close()
            return None
    except OSError:
        proc.close()
        return None
    proc.info = info
    return proc


# ---------------------------------------------------------------- QMP


class QmpError(Exception):
    pass


class Qmp:
    """A minimal QMP client on the loopback socket; asynchronous events are kept apart."""

    def __init__(self, port, timeout=30):
        self.sock = socket.create_connection((LOOPBACK, port), timeout)
        self.file = self.sock.makefile('rw', encoding='utf-8', newline='\n')
        self.events = []
        self.greeting = self._read()
        if 'QMP' not in self.greeting:
            raise QmpError(f'no QMP greeting: {self.greeting}')
        self.execute('qmp_capabilities')

    def _read(self):
        while True:
            line = self.file.readline()
            if not line:
                raise QmpError('QMP connection closed')
            message = json.loads(line)
            if 'event' in message:
                self.events.append(message)
                continue
            return message

    def execute(self, command, **arguments):
        request = {'execute': command}
        if arguments:
            request['arguments'] = arguments
        self.file.write(json.dumps(request) + '\n')
        self.file.flush()
        reply = self._read()
        if 'error' in reply:
            raise QmpError(f'{command}: {reply["error"]}')
        return reply.get('return')

    def close(self):
        try:
            self.file.close()
        finally:
            self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------------------------------------------------------------- host keys


def key_fingerprint(b64):
    blob = base64.b64decode(b64, validate=True)
    return 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode('ascii').rstrip('=')


FP_TYPES = {'ED25519': 'ssh-ed25519', 'RSA': 'ssh-rsa', 'ECDSA': 'ecdsa-sha2-nistp256'}
FP_LINE = re.compile(r'(\d+) (SHA256:[A-Za-z0-9+/]+) (.*) \(([A-Z0-9-]+)\)\s*$')
KEY_LINE = re.compile(r'(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)) '
                      r'([A-Za-z0-9+/]+={0,2})(?: (\S+))?\s*$')


def _blocks(lines, begin, end):
    blocks, current = [], None
    for line in lines:
        if begin in line:
            if current is not None:
                raise Refused('HOSTKEY', f'nested {begin} in the serial log')
            current = []
        elif end in line:
            if current is None:
                raise Refused('HOSTKEY', f'{end} without {begin} in the serial log')
            blocks.append(current)
            current = None
        elif current is not None:
            current.append(line)
    return blocks, current is not None


def parse_serial_host_keys(text):
    """cloud-init's host-key blocks on the serial log.

    Returns {'fingerprints': [...], 'keys': [...], 'complete': bool, 'finished': bool}.
    'complete' means the fingerprint block and the key block have both ended, or the
    fingerprint block ended and cloud-init's final stage has finished (no key block
    will follow). More than one block of either kind is refused as ambiguous.
    """
    lines = text.replace('\r', '').split('\n')
    fp_blocks, fp_open = _blocks(lines, '-----BEGIN SSH HOST KEY FINGERPRINTS-----',
                                 '-----END SSH HOST KEY FINGERPRINTS-----')
    key_blocks, key_open = _blocks(lines, '-----BEGIN SSH HOST KEY KEYS-----',
                                   '-----END SSH HOST KEY KEYS-----')
    if len(fp_blocks) > 1 or len(key_blocks) > 1:
        raise Refused('HOSTKEY', 'more than one host-key block in the serial log')
    finished = any(re.search(r'Cloud-init v\. \S+ finished at', line) for line in lines)
    fingerprints = []
    for line in (fp_blocks[0] if fp_blocks else []):
        match = FP_LINE.search(line)
        if match:
            fingerprints.append({'bits': int(match.group(1)), 'fingerprint': match.group(2),
                                 'comment': match.group(3), 'type': match.group(4)})
        elif line.strip() and not line.strip().endswith('#'):
            raise Refused('HOSTKEY', f'unparsed line in the fingerprint block: {line!r}')
    keys = []
    for line in (key_blocks[0] if key_blocks else []):
        match = KEY_LINE.search(line)
        if match:
            keys.append({'type': match.group(1), 'key': match.group(2),
                         'comment': match.group(3)})
        elif line.strip():
            raise Refused('HOSTKEY', f'unparsed line in the key block: {line!r}')
    complete = bool(fp_blocks) and not fp_open and not key_open and \
        (bool(key_blocks) or finished)
    return {'fingerprints': fingerprints, 'keys': keys, 'complete': complete,
            'finished': finished}


def trusted_host_keys(parsed, scanned=None):
    """Host keys whose SHA256 fingerprint the serial fingerprint block vouches for.

    Key material comes from cloud-init's key block, or, when cloud-init printed only
    fingerprints, from ``scanned`` (ssh-keyscan output); either way a key is trusted
    only if its fingerprint and type are in the serial fingerprint block, and every
    fingerprinted key must be found.
    """
    if not parsed['fingerprints']:
        raise Refused('HOSTKEY', 'no host-key fingerprints on the serial log')
    vouched = {(fp['fingerprint'], FP_TYPES.get(fp['type'], fp['type'])) for fp in parsed['fingerprints']}
    source = 'serial key block' if parsed['keys'] else 'ssh-keyscan, checked against the serial fingerprints'
    candidates = parsed['keys'] or (scanned or [])
    trusted, seen = [], set()
    for key in candidates:
        fp = key_fingerprint(key['key'])
        ktype = 'ecdsa-sha2-nistp256' if key['type'].startswith('ecdsa') else key['type']
        if (fp, ktype) in vouched:
            trusted.append(dict(key, fingerprint=fp))
            seen.add((fp, ktype))
        elif parsed['keys']:
            raise Refused('HOSTKEY', f'key {key["type"]} {fp} is not in the serial '
                          'fingerprint block')
    missing = vouched - seen
    if missing:
        raise Refused('HOSTKEY', f'fingerprinted host key(s) without key material: '
                      f'{sorted(m[0] for m in missing)}')
    return trusted, source


def known_hosts_lines(trusted, port):
    host = f'[{GUEST_USER_HOST}]:{port}'
    return [f'{host} {key["type"]} {key["key"]}' for key in trusted]


def parse_keyscan(text):
    out = []
    for line in text.replace('\r', '').split('\n'):
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) >= 3:
            out.append({'type': parts[1], 'key': parts[2], 'comment': None})
    return out


# ---------------------------------------------------------------- ssh


class Ssh:
    def __init__(self, profile, instance_dir, port):
        self.instance_dir = Path(instance_dir)
        self.key = self.instance_dir / 'ssh' / 'id_ed25519'
        self.known_hosts = self.instance_dir / 'ssh' / 'known_hosts'
        self.port = port
        values = {'instance_dir': posix(self.instance_dir)}
        options = (profile.get('identity') or {}).get('ssh_client_options') or []
        self.options = [expand(o, values) for o in options] + list(SSH_EXTRA_OPTIONS)
        self.exe = openssh('ssh.exe')
        self._checked = False

    def argv(self, user, command):
        if not self.key.is_file():
            # ssh silently falls back to ~/.ssh identities when -i names a missing file
            raise Refused('REFUSED', f'{self.key} missing; ssh is not run without the '
                          'per-instance key')
        if not self.known_hosts.is_file():
            raise Refused('REFUSED', f'{self.known_hosts} missing')
        base = [self.exe] + self.options + ['-i', str(self.key), '-p', str(self.port)]
        if not self._checked:
            self.check_effective(base)
        return base + [f'{user}@{GUEST_USER_HOST}'] + list(command)

    def check_effective(self, base):
        """ssh -G: the only identity is the per-instance key; no agent; no global file."""
        result = subprocess.run(base + ['-G', f'agent@{GUEST_USER_HOST}'], capture_output=True,
                                text=True, check=False)
        config = {}
        for line in result.stdout.splitlines():
            key, _, value = line.partition(' ')
            config.setdefault(key.lower(), []).append(value)
        identities = config.get('identityfile', [])
        if [os.path.normcase(i) for i in identities] != [os.path.normcase(str(self.key))] or \
                config.get('identityagent') != ['none'] or \
                config.get('globalknownhostsfile') != ['none'] or \
                config.get('stricthostkeychecking') != ['true']:
            raise Refused('REFUSED', f'ssh -G effective configuration is not the per-instance '
                          f'one: identityfile={identities} identityagent={config.get("identityagent")}')
        self._checked = True

    def run(self, command, user='agent', input_text=None, timeout=300):
        # Bytes, not text mode: on Windows a text-mode pipe writes '\r\n' for '\n', and the
        # guest's bash would read '{\r' instead of '{'.
        data = input_text.encode('utf-8') if input_text is not None else None
        result = subprocess.run(self.argv(user, command), input=data, capture_output=True,
                                timeout=timeout, check=False)
        return subprocess.CompletedProcess(
            result.args, result.returncode,
            result.stdout.decode('utf-8', errors='replace').replace('\r\n', '\n'),
            result.stderr.decode('utf-8', errors='replace').replace('\r\n', '\n'))


# ---------------------------------------------------------------- preflight


def preflight(ctx):
    checks = []

    def add(check, ok, detail, act):
        checks.append({'check': check, 'status': 'ok' if ok else 'fail', 'detail': detail,
                       'owner_act': None if ok else act})

    system, machine = platform.system(), platform.machine()
    add('os-arch', system == 'Windows' and machine.lower() in ('amd64', 'x86_64'),
        f'{system} {machine}', 'none: unsupported host (contract section 12)')
    if system == 'Windows':
        build = sys.getwindowsversion().build
        add('os-floor', build >= 22000, f'Windows build {build}',
            'none: Windows 10 is unsupported (contract section 12)')
    add('state-dir', True, f'{ctx.state_dir}: named, exists, outside the checkout and the '
        'Owner profile, no comma', 'A3')
    bins_ok = True
    for key, entry in sorted(binaries(ctx.profile, ctx.values).items()):
        ok, got = False, None
        if Path(entry['path']).is_file():
            got = sha256_file(entry['path'])
            ok = got == entry['sha256']
        bins_ok = bins_ok and ok
        add(f'binary:{key}', ok, f'{entry["path"]} sha256 {got} (pin {entry["sha256"]})',
            'A2: install the pinned QEMU (PREREQUISITES.md, A2)')
    firmware = ctx.profile['boot_inputs']['firmware']
    fw_path = ctx.values['input:firmware']
    fw_got = sha256_file(fw_path) if Path(fw_path).is_file() else None
    add('firmware', fw_got == firmware['sha256'], f'{fw_path} sha256 {fw_got}',
        'A2: install the pinned QEMU (PREREQUISITES.md, A2)')
    accel = (ctx.profile.get('accelerator') or {}).get('name')
    if bins_ok:
        qemu = launch_binary(ctx.profile, ctx.values)['path']
        result = subprocess.run([qemu, '-accel', 'help'], capture_output=True, text=True,
                                env=scrubbed_env(ctx.values), check=False, timeout=60)
        listed = [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]
        add('accelerator-listed', accel in listed, f'-accel help: {listed}',
            'A1: enable HypervisorPlatform and restart (PREREQUISITES.md, A1)')
    else:
        add('accelerator-listed', False, 'not run: the provider binary does not match its pin',
            'A2: install the pinned QEMU (PREREQUISITES.md, A2)')
    image = ctx.profile['boot_inputs']['image']
    img_path = ctx.values['input:image']
    img_got = sha256_file(img_path) if Path(img_path).is_file() else None
    add('image', img_got == image['sha256'], f'{img_path} sha256 {img_got}',
        'A3: place the pinned image in the state directory (PREREQUISITES.md, F-03.2.1b step 3)')
    available = all(c['status'] == 'ok' for c in checks)
    return {'operation': 'preflight', 'labels': labels(ctx.profile),
            'profile': ctx.profile['name'], 'provider': ctx.profile['provider']['name'],
            'result': 'available' if available else 'unavailable', 'checks': checks}


# ---------------------------------------------------------------- launch and readiness


def stderr_findings(instance_dir):
    path = Path(instance_dir) / 'stderr.log'
    text = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else ''
    lines = [line for line in text.splitlines() if line.strip()]
    return {'lines': lines,
            'whpx': [line for line in lines if 'WHPX:' in line],
            'interrupt_vector_0': sum(INTERRUPT_WARNING in line for line in lines)}


def launch(ctx, instance_dir, record, operation):
    """Re-check every input digest, then start QEMU detached and wait for QMP."""
    digests = verify_inputs(record)
    if os.name != 'nt':
        raise Refused('REFUSED', 'launch is implemented for Windows only')
    if running_process(instance_dir, record['binary']):
        raise Refused('REFUSED', f'{record["instance"]["name"]} is already running')
    for key in ('ssh', 'qmp'):
        if not port_free(record['ports'][key]):
            raise Refused('REFUSED', f'{key} port {record["ports"][key]} on {LOOPBACK} is in use')
    started = time.time()
    with open(Path(instance_dir) / 'stderr.log', 'ab') as err:
        proc = subprocess.Popen(record['argv'], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=err, cwd=str(instance_dir),
                                env=record['env'], close_fds=True,
                                creationflags=subprocess.DETACHED_PROCESS |
                                subprocess.CREATE_NEW_PROCESS_GROUP)
    info = {'pid': proc.pid, 'launched_at': utc_now(), 'launched_at_epoch': started,
            'binary': record['binary'], 'operation': operation,
            'ports': record['ports'], 'labels': record['labels']}
    path = Path(instance_dir) / 'process.json'
    tmp = path.with_suffix('.json.partial')
    tmp.write_text(json.dumps(info, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, path)
    log(f'{operation}: QEMU pid {proc.pid} launched')
    deadline = started + QMP_WAIT_S
    while True:
        if proc.poll() is not None:
            findings = stderr_findings(instance_dir)
            code = 'TIER_UNAVAILABLE' if findings['whpx'] else 'LAUNCH_FAILED'
            raise Refused(code, f'QEMU exited with {proc.returncode} before QMP answered',
                          findings)
        try:
            qmp = Qmp(record['ports']['qmp'], timeout=10)
            break
        except (OSError, QmpError, ValueError):
            if time.time() > deadline:
                raise Refused('LAUNCH_FAILED', f'QMP did not answer within {QMP_WAIT_S} s')
            time.sleep(0.2)   # no listen notification exists; poll the condition
    with qmp:
        status = qmp.execute('query-status')
        accel = qmp.execute('query-accelerators')
        version = qmp.execute('query-version')
    findings = stderr_findings(instance_dir)
    want = (ctx.profile.get('accelerator') or {}).get('name')
    if accel.get('enabled') != want or findings['whpx']:
        force_stop(instance_dir, record)
        raise Refused('TIER_UNAVAILABLE', f'accelerator {accel} (want {want}); WHPX lines '
                      f'{findings["whpx"]}', findings)
    pidfile = Path(instance_dir) / 'qemu.pid'
    pid_text = pidfile.read_text(encoding='ascii').strip() if pidfile.is_file() else None
    return {'pid': proc.pid, 'qemu_pidfile': pid_text, 'launched_at': info['launched_at'],
            'qmp': {'status': status, 'accelerators': accel, 'version': version},
            'input_digests': digests, 'stderr': findings,
            'seconds_to_qmp': round(time.time() - started, 2)}


def wait_ready(ctx, instance_dir, record, ceiling_s, need_host_keys):
    """Wait on observable signals: serial host keys, the SSH banner, cloud-init status."""
    start = time.time()
    deadline = start + ceiling_s
    port = record['ports']['ssh']
    serial = Path(instance_dir) / 'serial.log'
    marks = {}

    def alive_or_fail(stage):
        if not running_process(instance_dir, record['binary']):
            raise Refused('NOT_READY', f'QEMU is no longer running ({stage})',
                          stderr_findings(instance_dir))
        if time.time() > deadline:
            raise Refused('NOT_READY', f'readiness ceiling of {ceiling_s} s reached at {stage}',
                          {'marks': marks})

    hostkeys = None
    if need_host_keys:
        while True:
            text = serial.read_text(encoding='utf-8', errors='replace') if serial.is_file() else ''
            parsed = parse_serial_host_keys(text)
            if parsed['complete']:
                break
            alive_or_fail('serial host keys')
            time.sleep(POLL_S)    # the serial file exposes no completion signal
        marks['serial_host_keys_s'] = round(time.time() - start, 1)
        scanned = None
        if not parsed['keys']:
            scan = subprocess.run([openssh('ssh-keyscan.exe'), '-p', str(port), '-t', 'ed25519',
                                   GUEST_USER_HOST], capture_output=True, text=True, timeout=60,
                                  check=False)
            scanned = parse_keyscan(scan.stdout)
        trusted, source = trusted_host_keys(parsed, scanned)
        known_hosts = Path(instance_dir) / 'ssh' / 'known_hosts'
        with open(known_hosts, 'x', encoding='ascii', newline='\n') as handle:
            handle.write('\n'.join(known_hosts_lines(trusted, port)) + '\n')
        hostkeys = {'source': source, 'fingerprints': parsed['fingerprints'],
                    'known_hosts': known_hosts_lines(trusted, port)}
        log(f'host keys trusted from {source}: '
            f'{[k["fingerprint"] for k in trusted]}')
    while True:
        try:
            with socket.create_connection((LOOPBACK, port), timeout=5) as sock:
                banner = sock.recv(256)
            if banner.startswith(b'SSH-'):
                break
        except OSError:
            pass
        alive_or_fail('ssh banner')
        time.sleep(POLL_S)        # a forwarded port is listening before the guest answers
    marks['ssh_banner_s'] = round(time.time() - start, 1)
    ssh = Ssh(ctx.profile, instance_dir, port)
    remaining = max(30, deadline - time.time())
    result = ssh.run(['cloud-init', 'status', '--wait', '--long'], timeout=remaining)
    marks['cloud_init_s'] = round(time.time() - start, 1)
    # --wait prints one dot per poll before the status lines
    status = {'rc': result.returncode, 'stdout': re.sub(r'^\.*\n?', '', result.stdout).strip(),
              'stderr': result.stderr.strip()}
    if result.returncode not in (0, 2):
        raise Refused('NOT_READY', f'cloud-init status --wait exited {result.returncode}',
                      {'marks': marks, 'cloud_init': status})
    return {'marks': marks, 'host_keys': hostkeys, 'cloud_init': status,
            'ready_s': round(time.time() - start, 1)}


# ---------------------------------------------------------------- operations


def create(ctx, name, ready_timeout=READY_TIMEOUT_S):
    t0 = time.time()
    idir = ctx.instance_dir(name)
    if os.path.lexists(idir):
        raise Refused('REFUSED', f'{idir} exists; create never reuses an instance directory')
    report = preflight(ctx)
    if report['result'] != 'available':
        raise Refused('TIER_UNAVAILABLE', f'{ctx.profile["name"]}: strong provider unavailable',
                      [c for c in report['checks'] if c['status'] != 'ok'])
    revision = profile_revision(ctx.repo)
    instances = idir.parent
    if not instances.is_dir():
        os.mkdir(instances)
    os.mkdir(idir)            # fails if it appeared meanwhile: never reused
    os.mkdir(idir / 'ssh')
    log(f'create: {idir}')
    keygen = subprocess.run([openssh('ssh-keygen.exe'), '-q', '-t', 'ed25519', '-N', '', '-C',
                             name, '-f', str(idir / 'ssh' / 'id_ed25519')],
                            capture_output=True, text=True, check=False, timeout=60)
    if keygen.returncode != 0:
        raise Refused('REFUSED', f'ssh-keygen failed: {keygen.stderr.strip()}')
    values = resolve_values(ctx.profile, ctx.state_dir, name)
    image = ctx.profile['boot_inputs']['image']
    got = sha256_file(values['input:image'])
    if got != image['sha256']:
        raise Refused('DIGEST_MISMATCH', f'image sha256 {got} differs from the pin '
                      f'{image["sha256"]}')
    env = scrubbed_env(values, temp_dir=Path(values['instance_dir']))
    disk_commands = render_disk_commands(ctx.profile, values)
    disks = {}
    for disk, argv in sorted(disk_commands.items()):
        result = subprocess.run(argv, capture_output=True, text=True, env=env, check=False,
                                timeout=120)
        disks[disk] = {'argv': argv, 'rc': result.returncode, 'stdout': result.stdout.strip(),
                       'stderr': result.stderr.strip()}
        if result.returncode != 0:
            raise Refused('REFUSED', f'qemu-img for {disk} failed: {result.stderr.strip()}')
    seed = load_seed_generator().generate(str(ctx.profile_path.parent), str(idir), name,
                                          str(idir / 'ssh' / 'id_ed25519.pub'))
    ssh_port, qmp_port = allocate_ports(2)
    ports = {'ssh': ssh_port, 'qmp': qmp_port}
    values = resolve_values(ctx.profile, ctx.state_dir, name, ports)
    bins = binaries(ctx.profile, values)
    qemu = launch_binary(ctx.profile, values)
    pub = idir / 'ssh' / 'id_ed25519.pub'
    inputs = {
        'image': {'path': values['input:image'], 'sha256': got,
                  'pin': image['sha256']},
        'firmware': {'path': values['input:firmware'],
                     'sha256': sha256_file(values['input:firmware']),
                     'pin': ctx.profile['boot_inputs']['firmware']['sha256']},
        'seed': {'path': posix(seed['seed_iso']), 'sha256': seed['sha256'],
                 'size_bytes': seed['size_bytes'], 'templates': seed['templates'],
                 'rendered_sha256': seed['rendered_sha256']},
        'provider_binary': {'path': qemu['path'], 'sha256': sha256_file(qemu['path']),
                            'pin': qemu['sha256'],
                            'version': ctx.profile['provider']['version']},
        'qemu_img': {'path': bins['qemu-img']['path'],
                     'sha256': sha256_file(bins['qemu-img']['path']),
                     'pin': bins['qemu-img']['sha256']},
        'ssh_public_key': {'path': posix(pub), 'sha256': sha256_file(pub)},
    }
    for key, entry in inputs.items():
        if 'pin' in entry and entry['pin'] != entry['sha256']:
            raise Refused('DIGEST_MISMATCH', f'{key}: {entry["sha256"]} differs from the pin')
    argv = render_argv(ctx.profile, values)
    record = build_launch_record(ctx.profile, ctx.profile_path, values, name,
                                 seed['instance_id'], ports, revision, inputs, argv, env,
                                 disk_commands)
    write_json_exclusive(idir / 'launch.json', record)
    img_info = qemu_img_info(record, idir)
    launched = launch(ctx, idir, record, 'create')
    result = {'operation': 'create', 'labels': labels(ctx.profile), 'instance': name,
              'instance_id': seed['instance_id'], 'instance_dir': str(idir), 'ports': ports,
              'launch_record_sha256': sha256_file(idir / 'launch.json'),
              'seed_sha256': seed['sha256'], 'disks': disks, 'qemu_img_info': img_info,
              'launch': launched}
    try:
        result['ready'] = wait_ready(ctx, idir, record, ready_timeout, need_host_keys=True)
        result['result'] = 'ready'
    except Refused as exc:
        result['result'] = 'not-ready'
        result['error'] = {'code': exc.code, 'message': str(exc), 'detail': exc.detail}
    result['seconds'] = round(time.time() - t0, 1)
    result['record'] = write_record(idir, 'create', result)
    return result


def start(ctx, name, ready_timeout=READY_TIMEOUT_S):
    idir = ctx.instance_dir(name)
    if not idir.is_dir():
        raise Refused('REFUSED', f'{name}: no such instance')
    t0 = time.time()
    record = read_launch_record(idir)
    launched = launch(ctx, idir, record, 'start')
    result = {'operation': 'start', 'labels': labels(ctx.profile), 'instance': name,
              'launch': launched}
    try:
        result['ready'] = wait_ready(ctx, idir, record, ready_timeout,
                                     need_host_keys=not (idir / 'ssh' / 'known_hosts').is_file())
        result['result'] = 'ready'
    except Refused as exc:
        result['result'] = 'not-ready'
        result['error'] = {'code': exc.code, 'message': str(exc), 'detail': exc.detail}
    result['seconds'] = round(time.time() - t0, 1)
    result['record'] = write_record(idir, 'start', result)
    return result


def qmp_try(port, command, **arguments):
    try:
        with Qmp(port, timeout=10) as qmp:
            return {'command': command, 'return': qmp.execute(command, **arguments)}
    except (OSError, QmpError, ValueError) as exc:
        return {'command': command, 'error': f'{type(exc).__name__}: {exc}'}


def stop_process(proc, qmp_port, stop_timeout_s, force):
    """The stop binding on one verified process. Returns the phases taken."""
    phases, t0 = [], time.time()
    if not force:
        phases.append(qmp_try(qmp_port, 'system_powerdown'))
        if proc.wait(stop_timeout_s):
            phases.append({'exited_after': 'system_powerdown',
                           'seconds': round(time.time() - t0, 1)})
            return phases
        phases.append({'stop_timeout_s_elapsed': stop_timeout_s})
    phases.append(qmp_try(qmp_port, 'quit'))
    if proc.wait(QUIT_WAIT_S):
        phases.append({'exited_after': 'quit', 'seconds': round(time.time() - t0, 1)})
        return phases
    proc.terminate()
    exited = proc.wait(TERMINATE_WAIT_S)
    phases.append({'exited_after': 'terminate' if exited else 'terminate (still running)',
                   'pid': proc.pid, 'seconds': round(time.time() - t0, 1)})
    return phases


def force_stop(instance_dir, record):
    proc = running_process(instance_dir, record['binary'])
    if proc:
        try:
            return stop_process(proc, record['ports']['qmp'], 0, force=True)
        finally:
            proc.close()
    return []


def stop(ctx, name, force=False):
    idir = ctx.instance_dir(name)
    if not idir.is_dir():
        raise Refused('REFUSED', f'{name}: no such instance')
    record = read_launch_record(idir)
    proc = running_process(idir, record['binary'])
    result = {'operation': 'stop', 'labels': labels(ctx.profile), 'instance': name}
    if not proc:
        result['result'] = 'not-running'
    else:
        try:
            timeout = (ctx.profile.get('lifecycle') or {}).get('stop_timeout_s', 120)
            result['pid'] = proc.pid
            result['phases'] = stop_process(proc, record['ports']['qmp'], timeout, force)
            result['result'] = 'stopped' if not proc.alive() else 'still-running'
        finally:
            proc.close()
    result['stderr'] = stderr_findings(idir)
    result['record'] = write_record(idir, 'stop', result)
    if result['result'] == 'still-running':
        raise Refused('STOP_FAILED', f'{name}: process {result["pid"]} still runs', result)
    return result


def reparse_points(root):
    """Every symlink or junction under root (destroy never follows one)."""
    found, stack = [], [str(root)]
    while stack:
        with os.scandir(stack.pop()) as entries:
            for entry in entries:
                if entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction()):
                    found.append(entry.path)
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
    return found


def destroy(ctx, name):
    idir = ctx.instance_dir(name)
    result = {'operation': 'destroy', 'labels': labels(ctx.profile), 'instance': name,
              'instance_dir': str(idir)}
    if not os.path.lexists(idir):
        result['result'] = 'absent'
        return result
    if os.path.islink(idir) or os.path.isjunction(idir) or not idir.is_dir():
        raise Refused('REFUSED', f'{idir} is not a plain directory')
    links = reparse_points(idir)
    if links:
        raise Refused('REFUSED', f'{idir} holds links; destroy follows none: {links}')
    expected = launch_binary(ctx.profile, ctx.values)['path']
    proc = running_process(idir, expected)
    if proc:
        try:
            port = proc.info['ports']['qmp']
            result['stop'] = stop_process(proc, port, 0, force=True)
            if proc.alive():
                raise Refused('STOP_FAILED', f'{name}: process {proc.pid} still runs', result)
        finally:
            proc.close()
    else:
        result['stop'] = 'not-running'
    shutil.rmtree(idir)
    result['result'] = 'destroyed' if not os.path.lexists(idir) else 'incomplete'
    if result['result'] != 'destroyed':
        raise Refused('DESTROY_FAILED', f'{idir} still exists', result)
    return result


def recreate(ctx, name, ready_timeout=READY_TIMEOUT_S):
    return {'operation': 'recreate', 'destroy': destroy(ctx, name),
            'create': create(ctx, name, ready_timeout)}


def exec_command(ctx, name, command):
    idir = ctx.instance_dir(name)
    record = read_launch_record(idir)
    if not running_process(idir, record['binary']):
        raise Refused('NOT_RUNNING', f'{name} is not running')
    if not command:
        raise Refused('REFUSED', 'exec needs a command after --')
    ssh = Ssh(ctx.profile, idir, record['ports']['ssh'])
    argv = ssh.argv('agent', command)
    started = utc_now()
    rc = subprocess.run(argv, check=False).returncode
    write_record(idir, 'exec', {'operation': 'exec', 'labels': labels(ctx.profile),
                                'instance': name, 'command': command, 'rc': rc,
                                'started_at': started, 'ended_at': utc_now()})
    return rc


# ---------------------------------------------------------------- inspect


def qemu_img_info(record, instance_dir):
    out = {}
    for disk in ('root.qcow2', 'scratch.qcow2'):
        argv = [record['inputs']['qemu_img']['path'], 'info', '--output=json', '-U',
                posix(Path(instance_dir) / disk)]
        result = subprocess.run(argv, capture_output=True, text=True, env=record['env'],
                                check=False, timeout=60)
        try:
            out[disk] = json.loads(result.stdout) if result.returncode == 0 else \
                {'error': result.stderr.strip(), 'rc': result.returncode}
        except ValueError:
            out[disk] = {'error': 'unparsable', 'stdout': result.stdout}
    return out


def qmp_inspect(port):
    with Qmp(port, timeout=30) as qmp:
        out = {'greeting': qmp.greeting}
        for command in ('query-version', 'query-status', 'query-accelerators',
                        'query-cpus-fast', 'query-memory-size-summary', 'query-block',
                        'query-pci', 'query-chardev'):
            out[command] = qmp.execute(command)
        out['query-named-block-nodes'] = qmp.execute('query-named-block-nodes', flat=True)
        out['qom-list /objects'] = qmp.execute('qom-list', path='/objects')
        out['cpu-flags'] = [{'cpu-index': cpu['cpu-index'],
                             'vmx': qmp.execute('qom-get', path=cpu['qom-path'], property='vmx'),
                             'svm': qmp.execute('qom-get', path=cpu['qom-path'], property='svm')}
                            for cpu in out['query-cpus-fast']]
    return out


def host_bindings(pid, ports):
    """Get-NetTCPConnection and Get-NetUDPEndpoint for the QEMU process and its ports."""
    shell = Path(os.environ.get('SYSTEMROOT', r'C:\Windows')) / 'System32' / \
        'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    select = ("Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,"
              "@{n='State';e={[string]$_.State}},OwningProcess")
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        f"$t=@(Get-NetTCPConnection -OwningProcess {int(pid)} | {select});"
        f"$u=@(Get-NetUDPEndpoint -OwningProcess {int(pid)} | "
        "Select-Object LocalAddress,LocalPort,OwningProcess);"
        f"$p=@(Get-NetTCPConnection -LocalPort {int(ports['ssh'])},{int(ports['qmp'])} | {select});"
        "ConvertTo-Json -Depth 4 -InputObject @{tcp_by_pid=$t;udp_by_pid=$u;tcp_by_port=$p}")
    result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, check=False, timeout=120)
    try:
        return json.loads(result.stdout)
    except ValueError:
        return {'error': result.stderr.strip() or result.stdout.strip()}


def host_addresses():
    """The host's non-loopback IPv4 addresses (for the refusal checks)."""
    out = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            if not addr.startswith('127.'):
                out.add(addr)
    except OSError:
        pass
    return sorted(out)


def connect_result(host, port, timeout=5):
    family = socket.AF_INET6 if ':' in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return 'connected'
    except ConnectionRefusedError:
        return 'refused'
    except socket.timeout:
        return 'timeout'
    except OSError as exc:
        return f'error: {exc}'
    finally:
        sock.close()


def tcp_probe(host, port, timeout=5):
    return f"timeout {timeout} bash -c 'exec 3<>\"/dev/tcp/$0/$1\"' {host} {port}"


def guest_probes(ports, host_ips, http_ip):
    """(name, bash snippet) pairs: read-only inspection and egress probes."""
    probes = [
        ('uname', 'uname -srvmo'),
        ('virt', 'systemd-detect-virt'),
        ('nproc', 'nproc'),
        ('meminfo', 'grep -E "^(MemTotal|SwapTotal):" /proc/meminfo'),
        ('lsblk', 'lsblk -J -b -o NAME,SIZE,TYPE,RO,SERIAL,FSTYPE,LABEL,MOUNTPOINTS'),
        ('findmnt', 'findmnt -J -o TARGET,SOURCE,FSTYPE,OPTIONS'),
        ('findmnt_shares', f'findmnt -n -t {SHARE_FSTYPES}; echo "count=$(findmnt -n -t '
                           f'{SHARE_FSTYPES} | wc -l)"'),
        ('mnt_c', 'test -e /mnt/c && echo present || echo absent'),
        ('cpu_vmx_svm', "grep -c -E 'vmx|svm' /proc/cpuinfo"),
        ('cpu_model', "grep -m1 '^model name' /proc/cpuinfo; grep -c '^processor' /proc/cpuinfo"),
        ('dev_kvm', 'test -e /dev/kvm && echo present || echo absent'),
        ('machine_id', 'cat /etc/machine-id'),
        ('hostname', 'hostname'),
        ('id_agent', 'id agent'),
        ('sudo_group', 'getent group sudo'),
        ('sudo_check', 'command -v sudo && sudo -n true'),
        ('sshd_dropin', 'cat /etc/ssh/sshd_config.d/10-aieh.conf'),
        ('host_keys', 'for f in /etc/ssh/ssh_host_*_key.pub; do ssh-keygen -lf "$f"; done'),
        ('kernel_cmdline', 'cat /proc/cmdline'),
        ('cloud_init_status', 'cloud-init status --long'),
        ('cloud_init_result', 'cat /run/cloud-init/result.json'),
        ('cloud_init_query', "cloud-init query -f '{{ v1.instance_id }} {{ v1.local_hostname }} "
                             "{{ v1.platform }} {{ v1.subplatform }}'"),
        ('scratch_mount', 'findmnt -n -o SOURCE,FSTYPE,OPTIONS /srv/scratch'),
        ('exchange_dirs', 'stat -c "%n %U %a" /home/agent/exchange /srv/scratch/agent'),
        ('ip_addr', 'ip -br addr'),
        ('ip6_addr', 'ip -6 addr'),
        ('ip_route', 'ip route'),
        ('resolv_conf', 'cat /etc/resolv.conf'),
        ('virtio_ports', 'ls /dev/virtio-ports'),
        ('unix_sockets', 'ss -xlH'),
        ('host_sockets', 'test -e /var/run/docker.sock && echo docker.sock present || echo '
                         'docker.sock absent; echo "DOCKER_HOST=${DOCKER_HOST-unset}"; test -e '
                         '/tmp/.X11-unix && echo X11 present || echo X11 absent'),
        ('tools', 'for t in bash timeout getent python3 curl wget; do printf "%s=%s\\n" "$t" '
                  '"$(command -v $t || echo absent)"; done'),
        # egress probes (Owner condition 5; evidence toward F-03.3.2): positive controls first
        ('control_tcp_guest_sshd', tcp_probe('127.0.0.1', 22)),
        ('control_dns_localhost', 'timeout 5 getent hosts localhost'),
        ('egress_tcp_1.1.1.1_443', tcp_probe('1.1.1.1', 443)),
        ('egress_tcp_8.8.8.8_53', tcp_probe('8.8.8.8', 53)),
        ('egress_tcp_10.0.2.2_qmp', tcp_probe('10.0.2.2', ports['qmp'])),
        ('egress_tcp_10.0.2.2_ssh', tcp_probe('10.0.2.2', ports['ssh'])),
        ('egress_tcp_10.0.2.3_53', tcp_probe('10.0.2.3', 53)),
    ]
    for ip in host_ips:
        probes.append((f'egress_tcp_host_{ip}_ssh', tcp_probe(ip, ports['ssh'])))
        probes.append((f'egress_tcp_host_{ip}_qmp', tcp_probe(ip, ports['qmp'])))
    probes += [
        ('egress_dns_getent', 'timeout 10 getent ahosts deb.debian.org'),
        ('egress_udp_dns', "timeout 30 python3 - <<'PYEOF'\n" + UDP_DNS_PROBE + 'PYEOF'),
        ('egress_http_name', "timeout 20 python3 - <<'PYEOF'\n" + HTTP_PROBE.replace(
            '@TARGET@', 'deb.debian.org') + 'PYEOF'),
    ]
    if http_ip:
        probes.append(('egress_http_ip', "timeout 20 python3 - <<'PYEOF'\n" +
                       HTTP_PROBE.replace('@TARGET@', http_ip) + 'PYEOF'))
    return probes


UDP_DNS_PROBE = r'''import socket, struct, sys
query = struct.pack('>HHHHHH', 0x5a5a, 0x0100, 1, 0, 0, 0) + b''.join(
    bytes([len(p)]) + p.encode() for p in 'deb.debian.org'.split('.')) + b'\x00' + struct.pack('>HH', 1, 1)
ctl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); ctl.bind(('127.0.0.1', 0)); ctl.settimeout(2)
snd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); snd.sendto(b'ctl', ctl.getsockname())
print('control loopback udp', 'REPLY' if ctl.recvfrom(16)[0] == b'ctl' else 'NO-REPLY')
replies = 0
for server in ('10.0.2.3', '8.8.8.8', '1.1.1.1'):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(4)
    try:
        s.sendto(query, (server, 53)); data, _ = s.recvfrom(512)
        print(server, 'udp/53 REPLY', len(data), 'bytes'); replies += 1
    except Exception as exc:
        print(server, 'udp/53 NO-REPLY', type(exc).__name__, exc)
sys.exit(3 if replies else 10)
'''

HTTP_PROBE = r'''import http.client, sys
c = http.client.HTTPConnection('@TARGET@', 80, timeout=8)
try:
    c.connect()
except Exception as exc:
    print('@TARGET@ tcp/80 connect FAILED', type(exc).__name__, exc); sys.exit(10)
print('@TARGET@ tcp/80 CONNECTED')
try:
    c.request('GET', '/debian/', headers={'Host': 'deb.debian.org'})
    print('@TARGET@ http status', c.getresponse().status)
except Exception as exc:
    print('@TARGET@ http after connect', type(exc).__name__, exc)
sys.exit(3)
'''


def probe_script(probes, marker):
    parts = ['#!/bin/bash']
    for name, snippet in probes:
        parts.append(f"echo '{marker} BEGIN {name}'")
        parts.append('{\n' + snippet + '\n} </dev/null 2>&1')
        parts.append(f'echo "{marker} END {name} rc=$?"')
    return '\n'.join(parts) + '\n'


def parse_probe_output(text, marker):
    out, name, buf = {}, None, []
    for line in text.replace('\r', '').split('\n'):
        if line.startswith(f'{marker} BEGIN '):
            name, buf = line[len(marker) + 7:], []
        elif line.startswith(f'{marker} END ') and name is not None:
            match = re.search(r' rc=(\d+)$', line)
            out[name] = {'rc': int(match.group(1)) if match else None,
                         'out': '\n'.join(buf).rstrip('\n')}
            name = None
        elif name is not None:
            buf.append(line)
    return out


def flatten_pci(buses):
    devices = []
    for bus in buses or []:
        for dev in bus.get('devices', []):
            devices.append(dev)
            bridge = dev.get('pci_bridge')
            if bridge:
                devices.extend(flatten_pci([{'devices': bridge.get('devices', [])}]))
    return devices


def check(name, declared, observed, method, ok):
    verdict = 'UNKNOWN' if ok is None else ('PASS' if ok else 'FAIL')
    return {'check': name, 'declared': declared, 'observed': observed, 'method': method,
            'verdict': verdict}


def prop(pid, checks, formal=None, note=None):
    verdicts = [c['verdict'] for c in checks]
    verdict = 'FAIL' if 'FAIL' in verdicts else ('UNKNOWN' if not checks or 'UNKNOWN' in verdicts
                                                 else 'PASS')
    out = {'property': f'profiles {pid}', 'verdict': verdict, 'checks': checks}
    if formal:
        out['formal_tests'] = formal
    if note:
        out['note'] = note
    return out


def lsblk_by_serial(lsblk_json):
    out = {}
    try:
        for dev in json.loads(lsblk_json).get('blockdevices', []):
            if dev.get('serial'):
                out[dev['serial']] = dev
    except ValueError:
        pass
    return out


def truthy(value):
    return value in (True, 1, '1', 'true')


# Exit statuses that mean "blocked", per probe kind: bash /dev/tcp fails with 1 (refused,
# unreachable) or is cut off by timeout (124); getent reports "not found" with 2; the
# python3 probes exit 10 when nothing answered and 3 when something did. Anything else
# (a connection, a reply, or an unexpected status such as a crash) is not "blocked".
BLOCKED_RC = {'tcp': (1, 124), 'getent': (2, 124), 'python': (10, 124)}


def probe_kind(name):
    if name.startswith('egress_tcp_') or name.startswith('control_tcp_'):
        return 'tcp'
    if name in ('egress_dns_getent', 'control_dns_localhost'):
        return 'getent'
    return 'python'


def probe_blocked(name, result):
    """A guest egress probe is blocked when it neither connected nor got a reply."""
    return result is not None and isinstance(result.get('rc'), int) and \
        result['rc'] in BLOCKED_RC[probe_kind(name)]


def evaluate(profile, record, obs):
    """The P1-P12 record: declared, observed, method and verdict for each check."""
    g = obs.get('guest', {})
    q = obs.get('qmp', {})
    ceilings = profile.get('ceilings') or {}
    out_text = lambda key: (g.get(key) or {}).get('out', '')      # noqa: E731
    gib = 1024 ** 3
    props = []

    accel = (q.get('query-accelerators') or {}).get('enabled')
    props.append(prop('P1', [
        check('accelerator', profile['accelerator']['name'], accel,
              'QMP query-accelerators', accel == profile['accelerator']['name']),
        check('guest kernel', 'a Linux kernel of its own', out_text('uname'), 'guest: uname -srvmo',
              out_text('uname').startswith('Linux ')),
        check('host kernel', 'differs from the guest', obs.get('host_os'), 'platform.platform()',
              'Linux' not in str(obs.get('host_os'))),
        check('vm status', 'running', (q.get('query-status') or {}).get('status'),
              'QMP query-status', (q.get('query-status') or {}).get('status') == 'running'),
    ], formal='F-03.4'))

    mem_kb = None
    match = re.search(r'MemTotal:\s+(\d+) kB', out_text('meminfo'))
    if match:
        mem_kb = int(match.group(1))
    declared_kb = ceilings.get('memory_mib', 0) * 1024
    blk = lsblk_by_serial(out_text('lsblk'))
    img = obs.get('qemu_img', {})
    cpus = q.get('query-cpus-fast') or []
    props.append(prop('P2', [
        check('vcpu (QMP)', ceilings.get('vcpu'), len(cpus), 'QMP query-cpus-fast',
              len(cpus) == ceilings.get('vcpu')),
        check('vcpu (guest)', ceilings.get('vcpu'), out_text('nproc'), 'guest: nproc',
              out_text('nproc').strip() == str(ceilings.get('vcpu'))),
        check('memory (QMP)', ceilings.get('memory_mib', 0) * 1024 * 1024,
              (q.get('query-memory-size-summary') or {}).get('base-memory'),
              'QMP query-memory-size-summary',
              (q.get('query-memory-size-summary') or {}).get('base-memory') ==
              ceilings.get('memory_mib', 0) * 1024 * 1024),
        check('memory (guest MemTotal kB)', f'85-100 % of {declared_kb}', mem_kb,
              'guest: /proc/meminfo', mem_kb is not None and
              0.85 * declared_kb <= mem_kb <= declared_kb),
        check('root disk (guest)', ceilings.get('root_disk_gib', 0) * gib,
              (blk.get('root') or {}).get('size'), 'guest: lsblk -b (serial root)',
              (blk.get('root') or {}).get('size') == ceilings.get('root_disk_gib', 0) * gib),
        check('scratch disk (guest)', ceilings.get('scratch_disk_gib', 0) * gib,
              (blk.get('scratch') or {}).get('size'), 'guest: lsblk -b (serial scratch)',
              (blk.get('scratch') or {}).get('size') == ceilings.get('scratch_disk_gib', 0) * gib),
        check('root disk (qemu-img)', ceilings.get('root_disk_gib', 0) * gib,
              (img.get('root.qcow2') or {}).get('virtual-size'), 'qemu-img info -U',
              (img.get('root.qcow2') or {}).get('virtual-size') ==
              ceilings.get('root_disk_gib', 0) * gib
              if 'virtual-size' in (img.get('root.qcow2') or {}) else None),
        check('scratch disk (qemu-img)', ceilings.get('scratch_disk_gib', 0) * gib,
              (img.get('scratch.qcow2') or {}).get('virtual-size'), 'qemu-img info -U',
              (img.get('scratch.qcow2') or {}).get('virtual-size') ==
              ceilings.get('scratch_disk_gib', 0) * gib
              if 'virtual-size' in (img.get('scratch.qcow2') or {}) else None),
    ]))

    share_count = re.search(r'count=(\d+)', out_text('findmnt_shares'))
    fstypes = set()
    try:
        def walk(nodes):
            for node in nodes:
                fstypes.add(node.get('fstype'))
                walk(node.get('children', []))
        walk(json.loads(out_text('findmnt') or '{}').get('filesystems', []))
    except ValueError:
        pass
    bad_types = sorted(t for t in fstypes if t and t.split('.')[0] in SHARE_FSTYPES.split(','))
    props.append(prop('P3', [
        check('share mounts', 0, int(share_count.group(1)) if share_count else None,
              f'guest: findmnt -t {SHARE_FSTYPES}',
              share_count is not None and int(share_count.group(1)) == 0),
        check('mount table file systems', 'no share type', sorted(t for t in fstypes if t),
              'guest: findmnt -J', not bad_types if fstypes else None),
        check('/mnt/c', 'absent', out_text('mnt_c'), 'guest: test -e', out_text('mnt_c') == 'absent'),
        check('host shares declared', [], profile.get('host_shares'), 'profile', profile.get('host_shares') == []),
    ], formal='F-03.3.1; S-02.1, S-02.2'))

    nodes = {n.get('node-name'): n for n in q.get('query-named-block-nodes') or []}
    top = sorted((b.get('inserted') or {}).get('node-name') for b in q.get('query-block') or [])
    pci = flatten_pci(q.get('query-pci'))
    virtio, unknown = {}, []
    for dev in pci:
        ident = dev.get('id') or {}
        vendor, device = ident.get('vendor'), ident.get('device')
        if vendor == 0x1af4 and device in VIRTIO_IDS:
            virtio[VIRTIO_IDS[device]] = virtio.get(VIRTIO_IDS[device], 0) + 1
        elif (vendor, device) not in Q35_BUILTIN:
            unknown.append({'vendor': vendor, 'device': device, 'class': (dev.get('class_info') or {}).get('class'),
                            'qdev_id': dev.get('qdev_id')})
    declared_dev = {}
    argv = profile['launch']['argv']
    for i, arg in enumerate(argv[:-1]):
        if arg == '-device':
            model = argv[i + 1].split(',')[0]
            declared_dev[model] = declared_dev.get(model, 0) + 1
    seed_dev = blk.get('cidata') or {}
    props.append(prop('P4', [
        check('block devices', ['root', 'scratch', 'seed'], top, 'QMP query-block',
              top == ['root', 'scratch', 'seed']),
        check('read-only nodes', {'seed': True, 'seed-file': True, 'base': True, 'base-file': True,
                                  'root': False, 'scratch': False},
              {k: (nodes.get(k) or {}).get('ro') for k in
               ('seed', 'seed-file', 'base', 'base-file', 'root', 'scratch')},
              'QMP query-named-block-nodes',
              all((nodes.get(k) or {}).get('ro') is True for k in ('seed', 'seed-file', 'base', 'base-file'))
              and (nodes.get('root') or {}).get('ro') is False),
        check('pci virtio devices', declared_dev, virtio, 'QMP query-pci', virtio == declared_dev),
        check('pci devices outside virtio and the q35 chipset', [], unknown, 'QMP query-pci', not unknown),
        check('seed read-only in the guest', True, seed_dev.get('ro'), 'guest: lsblk (serial cidata)',
              truthy(seed_dev.get('ro')) if seed_dev else None),
        check('scratch mounted', '/srv/scratch ext4', out_text('scratch_mount'), 'guest: findmnt',
              ' ext4 ' in f' {out_text("scratch_mount")} '),
        check('exchange directory', '/home/agent/exchange agent 750', out_text('exchange_dirs'),
              'guest: stat', '/home/agent/exchange agent 750' in out_text('exchange_dirs')),
    ], formal='F-03.3.1; S-02.1, S-02.2'))

    props.append(prop('P5', [check('no Owner secrets', 'none', None,
                                   'not run: needs the canary positive control', None)],
                      formal='F-03.3.1; S-02.1, S-02.2'))

    chardevs = sorted(c.get('label') for c in q.get('query-chardev') or [])
    props.append(prop('P6', [
        check('chardevs', ['qmp', 'serial0'], chardevs, 'QMP query-chardev', chardevs == ['qmp', 'serial0']),
        check('virtio-serial ports', 'absent', out_text('virtio_ports'), 'guest: ls /dev/virtio-ports',
              (g.get('virtio_ports') or {}).get('rc') not in (0, None)),
        check('host sockets', 'docker.sock absent, DOCKER_HOST unset, X11 absent',
              out_text('host_sockets'), 'guest: test -e',
              out_text('host_sockets') == 'docker.sock absent\nDOCKER_HOST=unset\nX11 absent'),
        check('guest agent declared', False, (profile.get('guest_agent') or {}).get('used'),
              'profile', (profile.get('guest_agent') or {}).get('used') is False),
    ], formal='F-03.3.1; S-02.1, S-02.2'))

    host = obs.get('host', {})
    listeners = [c for c in (host.get('bindings') or {}).get('tcp_by_pid') or []
                 if c.get('State') == 'Listen']
    listen_addrs = sorted({(c.get('LocalAddress'), c.get('LocalPort')) for c in listeners})
    want_listen = sorted({(LOOPBACK, record['ports']['ssh']), (LOOPBACK, record['ports']['qmp'])})
    udp = (host.get('bindings') or {}).get('udp_by_pid') or []
    refusals = host.get('non_loopback') or {}
    egress = {k: v for k, v in g.items() if k.startswith('egress_')}
    netdev = [a for a in profile['launch']['argv'] if a.startswith('user,')]
    ip6 = out_text('ip6_addr')
    ip6_nonlo = [line for line in ip6.splitlines() if 'inet6' in line and '::1/128' not in line]
    props.append(prop('P7', [
        check('netdev', 'user, restrict=on, ipv6=off', netdev, 'launch.argv',
              bool(netdev) and 'restrict=on' in netdev[0] and 'ipv6=off' in netdev[0]),
        check('QEMU listening sockets', [list(x) for x in want_listen], [list(x) for x in listen_addrs],
              'Get-NetTCPConnection -OwningProcess', listen_addrs == want_listen),
        check('QEMU UDP endpoints on non-loopback addresses', [],
              [u for u in udp if u.get('LocalAddress') not in (LOOPBACK, '::1')],
              'Get-NetUDPEndpoint -OwningProcess',
              not [u for u in udp if u.get('LocalAddress') not in (LOOPBACK, '::1')]),
        check('host non-loopback addresses on the forwarded ports', 'refused', refusals,
              'host: TCP connect', bool(refusals) and all(v in ('refused', 'timeout') for v in refusals.values())),
        check('positive controls in the guest', 'tcp 127.0.0.1:22 connects; getent localhost resolves',
              {k: (g.get(k) or {}).get('rc') for k in ('control_tcp_guest_sshd', 'control_dns_localhost')},
              'guest: bash /dev/tcp, getent',
              all((g.get(k) or {}).get('rc') == 0 for k in ('control_tcp_guest_sshd', 'control_dns_localhost'))
              and 'control loopback udp REPLY' in out_text('egress_udp_dns')),
        check('guest egress probes', 'all blocked', {k: v['rc'] for k, v in egress.items()},
              'guest: bash /dev/tcp with timeout, getent, python3 socket and http.client',
              bool(egress) and all(probe_blocked(k, v) for k, v in egress.items())),
        check('guest IPv6 addresses beyond ::1', [], ip6_nonlo, 'guest: ip -6 addr', not ip6_nonlo),
        check('allowlisted endpoint positive control', 'none declared yet (F-03.3.2)', None,
              'not run', None),
    ], formal='F-03.3.2; S-02.1, S-02.2',
        note='Evidence toward F-03.3.2; not its formal suite.'))

    kh = obs.get('known_hosts_fingerprints') or []
    guest_fps = re.findall(r'(SHA256:[A-Za-z0-9+/]+)', out_text('host_keys'))
    mid = out_text('machine_id').strip()
    groups = out_text('id_agent')
    query = out_text('cloud_init_query').split()
    root_login = obs.get('root_login') or {}
    props.append(prop('P8', [
        check('machine-id', '32 hex digits, generated at first boot', mid, 'guest: /etc/machine-id',
              bool(re.fullmatch(r'[0-9a-f]{32}', mid))),
        check('hostname', record['instance']['name'], out_text('hostname').strip(), 'guest: hostname',
              out_text('hostname').strip() == record['instance']['name']),
        check('cloud-init instance id', record['instance']['instance_id'],
              query[0] if query else None, 'guest: cloud-init query',
              bool(query) and query[0] == record['instance']['instance_id']),
        check('agent groups', 'no sudo, root, adm or wheel group', groups, 'guest: id agent',
              bool(groups) and not re.search(r'\((sudo|root|adm|wheel)\)', groups.split('groups=')[-1])),
        check('sudo', 'refused', (g.get('sudo_check') or {}).get('out'), 'guest: sudo -n true',
              (g.get('sudo_check') or {}).get('rc') not in (0, None)),
        check('root ssh login', 'refused', root_login.get('stderr'), 'host: ssh root@127.0.0.1',
              root_login.get('rc') == 255 and 'Permission denied' in (root_login.get('stderr') or '')),
        check('sshd drop-in', 'PermitRootLogin no', out_text('sshd_dropin').splitlines()[:1],
              'guest: cat 10-aieh.conf', 'PermitRootLogin no' in out_text('sshd_dropin')),
        check('host keys', sorted(kh), sorted(guest_fps), 'guest: ssh-keygen -lf vs known_hosts',
              bool(kh) and sorted(kh) == sorted(guest_fps)),
        check('host principal', 'the Owner\'s Windows account', record.get('host_principal'),
              'launch record', bool(record.get('host_principal'))),
    ], note='Uniqueness across instances is compared outside a single inspect record.'))

    now = obs.get('input_digests') or {}
    pins = {'image': profile['boot_inputs']['image']['sha256'],
            'firmware': profile['boot_inputs']['firmware']['sha256'],
            'provider_binary': profile['boot_inputs']['provider_binary']['sha256']}
    root_img = img.get('root.qcow2') or {}
    props.append(prop('P9', [
        check('launch-record inputs re-hashed', 'equal to the launch record',
              {k: v.get('match') for k, v in now.items()}, 'sha256 now',
              bool(now) and all(v.get('match') for v in now.values())),
        check('pinned inputs', pins, {k: (now.get(k) or {}).get('sha256') for k in pins},
              'sha256 now vs profile pins', all((now.get(k) or {}).get('sha256') == v for k, v in pins.items())),
        check('seed digest recorded', 'sha256 in launch.json', record['inputs'].get('seed', {}).get('sha256'),
              'launch record', bool(record['inputs'].get('seed', {}).get('sha256'))),
        check('profile revision', 'git HEAD, profiles/ clean', record.get('profile_revision'),
              'launch record', (record.get('profile_revision') or {}).get('profiles_clean') is True),
        check('root overlay backing', record['inputs']['image']['path'],
              root_img.get('backing-filename'), 'qemu-img info -U',
              same_path(str(root_img.get('backing-filename')), record['inputs']['image']['path'])
              if 'backing-filename' in root_img else None),
    ]))

    props.append(prop('P10', [check('disposability', 'destroy removes only the instance', None,
                                    'not run by inspect', None)], formal='F-03.4'))

    props.append(prop('P11', [check('labels', labels(profile), record.get('labels'),
                                    'launch record', record.get('labels') == labels(profile))]))

    flags = q.get('cpu-flags') or []
    vmx = out_text('cpu_vmx_svm').strip()
    props.append(prop('P12', [
        check('declared', False, profile.get('nested_virt_exposed'), 'profile',
              profile.get('nested_virt_exposed') is False),
        check('QOM vmx/svm', 'false on every vCPU', flags, 'QMP qom-get',
              bool(flags) and not any(f['vmx'] or f['svm'] for f in flags)),
        check('guest cpuinfo vmx|svm count', 0, vmx, "guest: grep -c -E 'vmx|svm' /proc/cpuinfo",
              vmx == '0'),
        check('/dev/kvm', 'absent', out_text('dev_kvm'), 'guest: test -e', out_text('dev_kvm') == 'absent'),
    ]))
    return props


def inspect(ctx, name):
    idir = ctx.instance_dir(name)
    record = read_launch_record(idir)
    proc = running_process(idir, record['binary'])
    if not proc:
        raise Refused('NOT_RUNNING', f'{name} is not running')
    pid = proc.pid
    proc.close()
    t0 = time.time()
    obs = {'host_os': platform.platform()}
    try:
        obs['input_digests'] = verify_inputs(record)
    except Refused as exc:
        obs['input_digests'] = exc.detail or {}
    obs['qmp'] = qmp_inspect(record['ports']['qmp'])
    obs['qemu_img'] = qemu_img_info(record, idir)
    ips = host_addresses()
    obs['host'] = {
        'bindings': host_bindings(pid, record['ports']),
        'addresses': ips,
        'non_loopback': {f'{ip}:{record["ports"][k]}': connect_result(ip, record['ports'][k])
                         for ip in ips + ['::1'] for k in ('ssh', 'qmp')},
    }
    http_ip = None
    try:
        http_ip = socket.getaddrinfo('deb.debian.org', 80, socket.AF_INET)[0][4][0]
    except OSError:
        pass
    obs['host']['deb.debian.org'] = http_ip
    ssh = Ssh(ctx.profile, idir, record['ports']['ssh'])
    marker = '@@' + secrets.token_hex(8)
    probes = guest_probes(record['ports'], ips, http_ip)
    result = ssh.run(['bash', '-s'], input_text=probe_script(probes, marker), timeout=600)
    obs['guest'] = parse_probe_output(result.stdout, marker)
    obs['guest_ssh'] = {'rc': result.returncode, 'stderr': result.stderr.strip(),
                        'probes_expected': len(probes), 'probes_parsed': len(obs['guest'])}
    root = ssh.run(['true'], user='root', timeout=60)
    obs['root_login'] = {'rc': root.returncode, 'stderr': root.stderr.strip()}
    kh = (idir / 'ssh' / 'known_hosts').read_text(encoding='ascii').split('\n')
    obs['known_hosts_fingerprints'] = [key_fingerprint(line.split()[2]) for line in kh if line.strip()]
    obs['stderr'] = stderr_findings(idir)
    properties = evaluate(ctx.profile, record, obs)
    out = {'schema': INSPECT_SCHEMA, 'operation': 'inspect', 'labels': labels(ctx.profile),
           'instance': name, 'instance_id': record['instance']['instance_id'],
           'launch_record_sha256': sha256_file(idir / 'launch.json'), 'pid': pid,
           'inspected_at': utc_now(), 'seconds': round(time.time() - t0, 1),
           'verdicts': {p['property']: p['verdict'] for p in properties},
           'properties': properties, 'observations': obs}
    out['record'] = write_record(idir, 'inspect', out)
    return out


# ---------------------------------------------------------------- CLI


def load_seed_generator():
    spec = importlib.util.spec_from_file_location('nocloud_seed', REPO / 'tools' / 'nocloud_seed.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='operation', required=True)
    for op in ('preflight', 'create', 'start', 'stop', 'destroy', 'recreate', 'inspect', 'exec'):
        p = sub.add_parser(op)
        p.add_argument('--profile', required=True, help='profile directory (never defaulted)')
        p.add_argument('--state-dir', required=True, help='the Owner-named state directory')
        if op != 'preflight':
            p.add_argument('--name', required=True)
        if op in ('create', 'start', 'recreate'):
            p.add_argument('--ready-timeout', type=int, default=READY_TIMEOUT_S,
                           help='overall readiness ceiling in seconds')
        if op == 'stop':
            p.add_argument('--force', action='store_true',
                           help='skip system_powerdown: QMP quit, then terminate')
        if op == 'exec':
            p.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        ctx = Context(args.profile, args.state_dir)
        op = args.operation
        if op == 'exec':
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            return exec_command(ctx, args.name, command)
        if op == 'preflight':
            result = preflight(ctx)
        elif op == 'create':
            result = create(ctx, args.name, args.ready_timeout)
        elif op == 'start':
            result = start(ctx, args.name, args.ready_timeout)
        elif op == 'stop':
            result = stop(ctx, args.name, args.force)
        elif op == 'destroy':
            result = destroy(ctx, args.name)
        elif op == 'recreate':
            result = recreate(ctx, args.name, args.ready_timeout)
        else:
            result = inspect(ctx, args.name)
    except Refused as exc:
        print(f'REFUSED {exc.code}: {exc}', file=sys.stderr)
        print(json.dumps({'result': 'refused', 'code': exc.code, 'message': str(exc),
                          'detail': exc.detail}, indent=2, sort_keys=True, default=str))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    failed = result.get('result') in ('unavailable', 'not-ready') or \
        'FAIL' in (result.get('verdicts') or {}).values() or \
        result.get('create', {}).get('result') == 'not-ready'
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
