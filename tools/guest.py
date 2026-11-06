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
    exchange-push  one local branch of a named repository as a git bundle (bounded by
               the profile's exchange.push), copied by SFTP into the guest's exchange
               directory under a new name; digests checked on both sides (F-03.3.1)
    exchange-pull  one file from the guest's exchange directory, copied by SFTP into
               the instance's harness-owned staging directory; a bundle is verified
               in a fresh bare repository there, never in an Owner repository
    canaries   write a synthetic canary set (environment values and a fake home) into
               a new directory outside the checkout, for the profiles P5 test
    check-surfaces  inspect, then the startup inspection verdict for profiles P3 to P6;
               exit 0 only when all four PASS (F-03.3.1)

Usage (from the repository root; the profile and state directory are always named,
never defaulted, contract sections 4 and 11):
    python -I -B tools/guest.py preflight --profile PROFILE --state-dir STATE
    python -I -B tools/guest.py create    --profile PROFILE --state-dir STATE --name NAME
    python -I -B tools/guest.py inspect   --profile PROFILE --state-dir STATE --name NAME
    python -I -B tools/guest.py exec      --profile PROFILE --state-dir STATE --name NAME -- CMD
    python -I -B tools/guest.py exchange-push --profile PROFILE --state-dir STATE --name NAME
                                          --repo REPO --ref BRANCH [--bundle-name FILE]
    python -I -B tools/guest.py exchange-pull --profile PROFILE --state-dir STATE --name NAME
                                          --file FILE
    python -I -B tools/guest.py canaries  --out DIR
    python -I -B tools/guest.py check-surfaces --profile PROFILE --state-dir STATE --name NAME
                                          --canaries DIR
    (start, stop, destroy and recreate take the same arguments as inspect; create and
    inspect also take --canaries DIR: create plants the set in its own environment
    before it launches anything, inspect searches the guest for it)

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
import io
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
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
        result = self.run_raw(command, user, input_text, timeout)
        return subprocess.CompletedProcess(
            result.args, result.returncode,
            result.stdout.decode('utf-8', errors='replace').replace('\r\n', '\n'),
            result.stderr)

    def run_raw(self, command, user='agent', input_text=None, timeout=300):
        """stdout as bytes (for example a tar stream); stderr decoded."""
        # Bytes, not text mode: on Windows a text-mode pipe writes '\r\n' for '\n', and the
        # guest's bash would read '{\r' instead of '{'.
        data = input_text.encode('utf-8') if input_text is not None else None
        result = subprocess.run(self.argv(user, command), input=data, capture_output=True,
                                timeout=timeout, check=False)
        return subprocess.CompletedProcess(
            result.args, result.returncode, result.stdout,
            result.stderr.decode('utf-8', errors='replace').replace('\r\n', '\n'))


class Sftp:
    """sftp.exe in batch mode over the same forward, options and key as Ssh.

    sftp passes -F and every -o to the ssh it spawns; -S names Windows' built-in ssh.exe
    so no other ssh on PATH is used. The effective configuration is checked with
    ``ssh -G`` (Ssh.check_effective) before the first transfer.
    """

    def __init__(self, ssh):
        self.ssh = ssh
        self.exe = openssh('sftp.exe')

    def argv(self, batch_file):
        base = self.ssh.argv('agent', [])[:-1]            # checks the key and ssh -G
        options = base[1:base.index('-p')]                  # profile options, extras, -i KEY
        return [self.exe, '-S', self.ssh.exe] + options + \
            ['-P', str(self.ssh.port), '-b', str(batch_file), f'agent@{GUEST_USER_HOST}']

    def batch(self, commands, work_dir, timeout=600):
        """Run sftp commands; '-b' stops at the first failing command (exit 1)."""
        batch_file = Path(work_dir) / f'sftp-{secrets.token_hex(6)}.batch'
        with open(batch_file, 'x', encoding='utf-8', newline='\n') as handle:
            handle.write('\n'.join(commands) + '\n')
        try:
            result = subprocess.run(self.argv(batch_file), capture_output=True,
                                    stdin=subprocess.DEVNULL, timeout=timeout, check=False)
        finally:
            batch_file.unlink()
        return {'rc': result.returncode, 'commands': commands,
                'stderr': result.stderr.decode('utf-8', errors='replace').strip()}


def sftp_quote(path):
    text = posix(path)
    if '"' in text or '\n' in text:
        raise Refused('REFUSED', f'path {text!r} cannot be quoted for sftp')
    return f'"{text}"'


# ---------------------------------------------------------------- git (host side)


def git_binary():
    path = shutil.which('git')
    if not path:
        raise Refused('REFUSED', 'git not found on PATH (the exchange builds and verifies '
                      'bundles with the host git)')
    return path


def git_env(home):
    """git without system or global configuration, prompts or the caller's environment."""
    env = {key: os.environ[key] for key in ('SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'PATH')
           if key in os.environ}
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_TERMINAL_PROMPT': '0', 'GIT_ATTR_NOSYSTEM': '1', 'HOME': str(home)})
    return env


def run_git(args, home, repo=None, timeout=600):
    argv = [git_binary(), '-c', f'core.hooksPath={os.devnull}', '-c', 'core.fsmonitor=false']
    if repo is not None:
        argv += ['-C', str(repo)]
    result = subprocess.run(argv + list(args), capture_output=True, env=git_env(home),
                            stdin=subprocess.DEVNULL, timeout=timeout, check=False)
    return subprocess.CompletedProcess(
        argv + list(args), result.returncode,
        result.stdout.decode('utf-8', errors='replace').replace('\r\n', '\n'),
        result.stderr.decode('utf-8', errors='replace').replace('\r\n', '\n'))


def git_ok(args, home, repo=None, what=None):
    result = run_git(args, home, repo)
    if result.returncode != 0:
        raise Refused('EXCHANGE', f'{what or "git " + " ".join(args)} failed: '
                      f'{result.stderr.strip() or result.stdout.strip()}')
    return result.stdout.strip()


BUNDLE_SIGNATURES = {b'# v2 git bundle\n': 2, b'# v3 git bundle\n': 3}
BUNDLE_REF = re.compile(r'([0-9a-f]{40}|[0-9a-f]{64}) (refs/\S+|HEAD)')
BUNDLE_HEADER_MAX = 1 << 20


def parse_bundle_header(path):
    """The header of a git bundle file (gitformat-bundle): version, capabilities,
    prerequisites and references. Anything else is refused."""
    with open(path, 'rb') as handle:
        first = handle.readline(64)
        if first not in BUNDLE_SIGNATURES:
            raise Refused('BUNDLE', f'{path}: not a v2 or v3 git bundle')
        out = {'version': BUNDLE_SIGNATURES[first], 'capabilities': [],
               'prerequisites': [], 'refs': []}
        total = len(first)
        while True:
            line = handle.readline(4096)
            total += len(line)
            if not line or not line.endswith(b'\n') or total > BUNDLE_HEADER_MAX:
                raise Refused('BUNDLE', f'{path}: bundle header not terminated')
            if line == b'\n':
                out['pack_offset'] = total
                return out
            try:
                text = line[:-1].decode('ascii')
            except UnicodeDecodeError as exc:
                raise Refused('BUNDLE', f'{path}: non-ASCII header line') from exc
            if text.startswith('@') and out['version'] == 3:
                out['capabilities'].append(text[1:])
            elif text.startswith('-'):
                out['prerequisites'].append(text[1:].split(' ', 1)[0])
            else:
                match = BUNDLE_REF.fullmatch(text)
                if not match:
                    raise Refused('BUNDLE', f'{path}: unparsable header line {text!r}')
                out['refs'].append([match.group(1), match.group(2)])


def pack_trailer(path, header):
    """The bundle's packfile checksum, recomputed: the pack starts with 'PACK' after the
    header and ends with the hash of everything before the trailer (SHA-1, or SHA-256
    when the v3 header says object-format=sha256)."""
    sha256 = 'object-format=sha256' in header.get('capabilities', [])
    size = 32 if sha256 else 20
    digest = hashlib.sha256() if sha256 else hashlib.sha1()
    with open(path, 'rb') as handle:
        handle.seek(header['pack_offset'])
        magic = handle.read(4)
        digest.update(magic)
        tail = b''
        for block in iter(lambda: handle.read(1 << 20), b''):
            data = tail + block
            digest.update(data[:-size])
            tail = data[-size:]
    ok = magic == b'PACK' and len(tail) == size and digest.digest() == tail
    return {'ok': ok, 'algorithm': 'sha256' if sha256 else 'sha1', 'trailer': tail.hex()}


# ---------------------------------------------------------------- exchange


def exchange_config(profile):
    ex = profile.get('exchange')
    if not isinstance(ex, dict) or not ex.get('guest_dir') or not ex.get('host_staging'):
        raise Refused('REFUSED', f'profile {profile.get("name")} declares no exchange')
    return ex


def staging_dir(ctx, name, part):
    """{exchange.host_staging}/<part>: harness-owned, inside the instance directory."""
    idir = ctx.instance_dir(name)
    values = resolve_values(ctx.profile, ctx.state_dir, name)
    path = Path(expand(exchange_config(ctx.profile)['host_staging'], values))
    if not inside(path, idir):
        raise Refused('REFUSED', f'exchange staging {path} is not inside {idir}')
    path = path / part
    path.mkdir(parents=True, exist_ok=True)
    return path


def running_instance(ctx, name):
    idir = ctx.instance_dir(name)
    if not idir.is_dir():
        raise Refused('REFUSED', f'{name}: no such instance')
    record = read_launch_record(idir)
    if not running_process(idir, record['binary']):
        raise Refused('NOT_RUNNING', f'{name} is not running')
    return idir, record


def guest_file_state(ssh, guest_path):
    """'absent', 'symlink', 'other', or ('file', size, sha256) for one guest path."""
    script = (f"p='{guest_path}'\n"
              'if [ -L "$p" ]; then echo symlink; elif [ ! -e "$p" ]; then echo absent; '
              'elif [ -f "$p" ]; then printf "file %s %s\\n" "$(stat -c %s -- "$p")" '
              '"$(sha256sum -- "$p" | cut -c1-64)"; else echo other; fi\n')
    result = ssh.run(['bash', '-s'], input_text=script, timeout=300)
    words = result.stdout.split()
    if result.returncode != 0 or not words:
        raise Refused('EXCHANGE', f'guest stat of {guest_path} failed: {result.stderr.strip()}')
    if words[0] == 'file' and len(words) == 3 and words[1].isdigit() and \
            re.fullmatch(r'[0-9a-f]{64}', words[2]):
        return ('file', int(words[1]), words[2])
    if words[0] in ('absent', 'symlink', 'other') and len(words) == 1:
        return words[0]
    raise Refused('EXCHANGE', f'unexpected guest stat output for {guest_path}: {result.stdout!r}')


def check_exchange_name(name, pattern, what):
    if not isinstance(name, str) or not re.fullmatch(pattern, name) or name.endswith('.partial'):
        raise Refused('REFUSED', f'{what} {name!r} does not match {pattern} (or ends in .partial)')
    return name


def exchange_push(ctx, name, repo, ref, bundle_name=None):
    """exchange push: one local branch as a complete git bundle, bounded and verified."""
    t0 = time.time()
    idir, record = running_instance(ctx, name)
    ex = exchange_config(ctx.profile)
    bounds = ex.get('push') or {}
    outbound = staging_dir(ctx, name, 'outbound')
    home = staging_dir(ctx, name, 'git-home')
    repo = Path(repo).resolve()
    if inside(repo, ctx.state_dir):
        raise Refused('REFUSED', f'{repo} is inside the state directory')
    git_ok(['rev-parse', '--git-dir'], home, repo, f'{repo}: not a git repository;')
    if not isinstance(ref, str) or not ref or ref.startswith('-'):
        raise Refused('REFUSED', f'{ref!r} is not a branch name')
    full = run_git(['rev-parse', '--verify', '--quiet', '--symbolic-full-name', ref], home,
                   repo).stdout.strip()
    if not re.fullmatch(r'refs/heads/[^\s]+', full):
        raise Refused('REFUSED', f'{ref!r} is not a local branch (resolved to {full!r}); '
                      'exchange push sends exactly one refs/heads/ branch')
    commit = git_ok(['rev-parse', '--verify', f'{full}^{{commit}}'], home, repo)
    commits = int(git_ok(['rev-list', '--count', full], home, repo))
    if commits > bounds.get('max_commits', 0):
        raise Refused('BOUNDS', f'{full} has {commits} commits; exchange.push.max_commits is '
                      f'{bounds.get("max_commits")}')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dt%H%M%Sz')
    bname = check_exchange_name(bundle_name or f'{name}-{stamp}-{commit[:12]}.bundle',
                                bounds.get('name_pattern', r'^$'), 'bundle name')
    local = outbound / bname
    if os.path.lexists(local):
        raise Refused('REFUSED', f'{local} exists; a bundle is never overwritten')
    git_ok(['bundle', 'create', '--quiet', str(local), full], home, repo, 'git bundle create')
    try:
        size = local.stat().st_size
        if size > bounds.get('max_bytes', 0):
            raise Refused('BOUNDS', f'bundle is {size} bytes; exchange.push.max_bytes is '
                          f'{bounds.get("max_bytes")}')
        header = parse_bundle_header(local)
        if header['refs'] != [[commit, full]] or header['prerequisites'] or \
                len(header['refs']) != bounds.get('refs', 1):
            raise Refused('BOUNDS', f'bundle header is not exactly {full} at {commit} with no '
                          f'prerequisites: {header}')
        if not pack_trailer(local, header)['ok']:
            raise Refused('BUNDLE', f'{local}: pack checksum mismatch')
        git_ok(['bundle', 'verify', '--quiet', str(local)], home, repo, 'git bundle verify')
    except Refused:
        local.unlink()
        raise
    digest = sha256_file(local)
    ssh = Ssh(ctx.profile, idir, record['ports']['ssh'])
    guest_path = f'{ex["guest_dir"]}/{bname}'
    for path in (guest_path, guest_path + '.partial'):
        state = guest_file_state(ssh, path)
        if state != 'absent':
            raise Refused('REFUSED', f'guest {path} is {state}; never overwritten')
    transfer = Sftp(ssh).batch([f'put {sftp_quote(local)} {guest_path}.partial',
                                f'rename {guest_path}.partial {guest_path}'], outbound)
    if transfer['rc'] != 0:
        raise Refused('EXCHANGE', f'sftp push failed: {transfer["stderr"]}', transfer)
    landed = guest_file_state(ssh, guest_path)
    result = {'operation': 'exchange-push', 'labels': labels(ctx.profile), 'instance': name,
              'source': {'ref': full, 'commit': commit, 'commits': commits},
              'bundle': {'name': bname, 'host_path': str(local), 'bytes': size,
                         'sha256': digest, 'header': header},
              'guest': {'path': guest_path, 'state': list(landed) if isinstance(landed, tuple)
                        else landed},
              'transfer': transfer, 'bounds': bounds}
    ok = isinstance(landed, tuple) and landed[1] == size and landed[2] == digest
    result['result'] = 'pushed' if ok else 'mismatch'
    result['seconds'] = round(time.time() - t0, 1)
    result['record'] = write_record(idir, 'exchange-push', result)
    if not ok:
        raise Refused('EXCHANGE', f'guest copy differs: {landed}', result)
    return result


def verify_pulled_bundle(ctx, name, path):
    """A pulled bundle, verified in a fresh bare repository in the staging directory.

    The repository first fetches every bundle this instance was pushed (the possible
    prerequisites), then ``git bundle verify``, fetches the bundle's references under
    refs/pulled/ and checks each one, then ``git fsck --strict``.
    """
    home = staging_dir(ctx, name, 'git-home')
    header = parse_bundle_header(path)
    vrepo = staging_dir(ctx, name, 'verify') / f'{Path(path).name}.git'
    if os.path.lexists(vrepo):
        raise Refused('REFUSED', f'{vrepo} exists')
    git_ok(['init', '--bare', '--quiet', str(vrepo)], home, None, 'git init --bare')
    pack = pack_trailer(path, header)
    if not pack['ok']:
        raise Refused('BUNDLE', f'{path}: pack checksum mismatch ({pack})')
    # Only a bundle with prerequisites needs the pushed history first; a complete bundle
    # is fetched into an empty repository, so every object is read from its own pack.
    outbound = sorted(staging_dir(ctx, name, 'outbound').glob('*.bundle')) \
        if header['prerequisites'] else []
    for index, bundle in enumerate(outbound):
        git_ok(['fetch', '--quiet', '--no-tags', str(bundle),
                f'+refs/*:refs/outbound/{index}/*'], home, vrepo, f'fetch of pushed {bundle.name}')
    git_ok(['bundle', 'verify', '--quiet', str(path)], home, vrepo, 'git bundle verify')
    git_ok(['fetch', '--quiet', '--no-tags', str(path), '+refs/*:refs/pulled/*'], home, vrepo,
           'fetch of the pulled bundle')
    refs = []
    for sha, ref in header['refs']:
        local_ref = 'refs/pulled/' + ref[len('refs/'):] if ref.startswith('refs/') else None
        got = git_ok(['rev-parse', '--verify', '--end-of-options', local_ref], home, vrepo) \
            if local_ref else None
        refs.append({'ref': ref, 'header': sha, 'fetched': got, 'match': got == sha})
    fsck = run_git(['fsck', '--strict', '--no-progress', '--no-dangling'], home, vrepo)
    return {'header': header, 'pack': pack, 'verify_repo': str(vrepo), 'prerequisite_sources':
            [b.name for b in outbound], 'bundle_verify': 'ok', 'refs': refs,
            'fsck': {'rc': fsck.returncode, 'out': (fsck.stdout + fsck.stderr).strip()},
            'verified': bool(refs) and all(r['match'] for r in refs) and fsck.returncode == 0}


def exchange_pull(ctx, name, filename):
    """exchange pull: one file from the guest's exchange directory into staging, as data."""
    t0 = time.time()
    idir, record = running_instance(ctx, name)
    ex = exchange_config(ctx.profile)
    bounds = ex.get('pull') or {}
    check_exchange_name(filename, bounds.get('name_pattern', r'^$'), 'file name')
    inbound = staging_dir(ctx, name, 'inbound')
    local = inbound / filename
    partial = inbound / (filename + '.partial')
    if os.path.lexists(local) or os.path.lexists(partial):
        raise Refused('REFUSED', f'{local} (or its .partial) exists; never overwritten')
    ssh = Ssh(ctx.profile, idir, record['ports']['ssh'])
    guest_path = f'{ex["guest_dir"]}/{filename}'
    state = guest_file_state(ssh, guest_path)
    if not isinstance(state, tuple):
        raise Refused('REFUSED', f'guest {guest_path} is {state}, not a regular file')
    if state[1] > bounds.get('max_bytes', 0):
        raise Refused('BOUNDS', f'guest {guest_path} is {state[1]} bytes; exchange.pull.max_bytes '
                      f'is {bounds.get("max_bytes")}')
    transfer = Sftp(ssh).batch([f'get {guest_path} {sftp_quote(partial)}'], inbound)
    if transfer['rc'] != 0 or not partial.is_file():
        if partial.exists():
            partial.unlink()
        raise Refused('EXCHANGE', f'sftp pull failed: {transfer["stderr"]}', transfer)
    size = partial.stat().st_size
    if size > bounds.get('max_bytes', 0):
        partial.unlink()
        raise Refused('BOUNDS', f'pulled {size} bytes; exchange.pull.max_bytes is '
                      f'{bounds.get("max_bytes")}')
    os.rename(partial, local)          # Windows: fails if the target appeared meanwhile
    digest = sha256_file(local)
    result = {'operation': 'exchange-pull', 'labels': labels(ctx.profile), 'instance': name,
              'guest': {'path': guest_path, 'bytes': state[1], 'sha256': state[2]},
              'staged': {'path': str(local), 'bytes': size, 'sha256': digest},
              'transfer': transfer, 'bounds': bounds,
              'digest_match': digest == state[2] and size == state[1]}
    if filename.endswith('.bundle'):
        try:
            result['bundle'] = verify_pulled_bundle(ctx, name, local)
        except Refused as exc:
            result['bundle'] = {'verified': False, 'error': f'{exc.code}: {exc}'}
    ok = result['digest_match'] and result.get('bundle', {'verified': True})['verified']
    result['result'] = 'pulled' if ok else 'unverified'
    result['seconds'] = round(time.time() - t0, 1)
    result['record'] = write_record(idir, 'exchange-pull', result)
    if not ok:
        raise Refused('EXCHANGE', f'pulled {filename} did not verify', result)
    return result


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


def create(ctx, name, ready_timeout=READY_TIMEOUT_S, canaries=None):
    t0 = time.time()
    idir = ctx.instance_dir(name)
    if os.path.lexists(idir):
        raise Refused('REFUSED', f'{idir} exists; create never reuses an instance directory')
    planted = apply_canaries(canaries) if canaries else None   # the P5 test: before anything
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
    if planted:
        result['canaries'] = {'planted_in_environment': planted,
                              'needles': canary_summary(canaries['needles'])}
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


# ---------------------------------------------------------------- canaries (profiles P5)

CANARY_SCHEMA = 'ai-engineering-harness/profiles/canaries/v1'
# PEM armour for synthetic key-shaped text, assembled at run time so that no literal
# private-key block appears in the source (the publication gate scans it).
ARMOR = '-' * 5 + '{} OPENSSH PRIVATE KEY' + '-' * 5


def make_canaries(out_dir, repo_root=REPO):
    """A synthetic canary set: environment values and a fake home with credential-shaped
    files. Every value carries a fresh random core; nothing here is a real secret.

    The environment names include credential-looking ones, and LC_AIEH_CANARY, which
    the guest's sshd would accept (AcceptEnv LC_*) if a client ever sent it. The fake
    home is where a careless implementation would look (HOME for git and MSYS tools;
    an ssh_config that sets SetEnv and ForwardAgent; a private key; stored git and AWS
    credentials).
    """
    out = Path(out_dir).resolve()
    if os.path.lexists(out):
        raise Refused('REFUSED', f'{out} exists; a canary set is always new')
    if inside(out, repo_root):
        raise Refused('REFUSED', f'{out} is inside the checkout; canaries are never committed')
    core = lambda: secrets.token_hex(16)                                   # noqa: E731
    alnum = lambda n: ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')  # noqa: E731
                              for _ in range(n))
    env = {
        'AIEH_CANARY_ENV': f'aieh-canary-env-{core()}',
        'AIEH_CANARY_API_TOKEN': f'aieh-canary-token-{core()}',
        'GITHUB_TOKEN': f'ghp_{core()}{alnum(4)}',
        'ANTHROPIC_API_KEY': f'sk-ant-api03-{core()}-aieh-canary',
        'AWS_SECRET_ACCESS_KEY': f'aieh-canary-aws-{core()}',
        'LC_AIEH_CANARY': f'aieh-canary-lc-{core()}',
        'DOCKER_HOST': f'tcp://aieh-canary-docker-{core()}.invalid:2375',
    }
    files = {
        '.ssh/id_ed25519': f'aieh-canary-ssh-key-{core()}',
        '.ssh/config': f'aieh-canary-ssh-config-{core()}',
        '.git-credentials': f'aieh-canary-git-credentials-{core()}',
        '.aws/credentials': f'aieh-canary-aws-file-{core()}',
        '.gitconfig': f'aieh-canary-gitconfig-{core()}',
    }
    akia = f'AKIA{alnum(16)}'
    content = {
        '.ssh/id_ed25519': ARMOR.format('BEGIN') + '\n{v}\n' + ARMOR.format('END') + '\n',
        '.ssh/config': 'Host *\n  # {v}\n  SetEnv LC_AIEH_CANARY_SSHCONFIG={v}\n'
                       '  ForwardAgent yes\n  IdentityFile ~/.ssh/id_ed25519\n',
        '.git-credentials': 'https://aieh:{v}@example.invalid\n',
        '.aws/credentials': '[default]\naws_access_key_id = ' + akia +
                            '\naws_secret_access_key = {v}\n',
        '.gitconfig': '[user]\n\tname = {v}\n[credential]\n\thelper = store\n',
    }
    home = out / 'home'
    home.mkdir(parents=True)
    for rel, value in files.items():
        path = home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content[rel].format(v=value), encoding='ascii', newline='\n')
    needles = {f'env:{k}': v for k, v in env.items()}
    needles.update({f'home:{k}': v for k, v in files.items()})
    needles['home:.aws/credentials:access-key-id'] = akia
    data = {'schema': CANARY_SCHEMA, 'created_at': utc_now(), 'home': str(home),
            'env': env, 'needles': needles}
    write_json_exclusive(out / 'canaries.json', data)
    return {'operation': 'canaries', 'dir': str(out), 'home': str(home),
            'canaries': canary_summary(needles)}


def canary_summary(needles):
    """Labels with the sha256 of each value; the values themselves are never printed."""
    return [{'label': label, 'sha256': hashlib.sha256(value.encode()).hexdigest()}
            for label, value in sorted(needles.items())]


def load_canaries(canary_dir, repo_root=REPO):
    path = Path(canary_dir).resolve() / 'canaries.json'
    if inside(path, repo_root):
        raise Refused('REFUSED', f'{path} is inside the checkout')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise Refused('REFUSED', f'{path}: cannot read the canary set ({exc})') from exc
    if data.get('schema') != CANARY_SCHEMA or not data.get('needles'):
        raise Refused('REFUSED', f'{path}: not a canary set')
    return data


def apply_canaries(data, environ=None):
    """Plant the set in this process: the environment values, and HOME at the fake home.
    Child processes that inherit the environment (git, ssh-keygen) see them; QEMU is
    launched with the scrubbed environment (profiles P5)."""
    environ = os.environ if environ is None else environ
    environ.update(data['env'])
    environ['HOME'] = data['home']
    return sorted(data['env']) + ['HOME']


# ---------------------------------------------------------------- P5 collection and scan

# Owner-class patterns (profiles P5): private-key headers, Git-host and cloud tokens,
# LLM-provider keys. The host account name and profile path are added at run time.
OWNER_PATTERNS = {
    'private-key-header': [rb'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----',
                           rb'PuTTY-User-Key-File-\d'],
    'git-host-token': [rb'gh[pousr]_[A-Za-z0-9]{36}', rb'github_pat_[A-Za-z0-9_]{50,}',
                       rb'glpat-[A-Za-z0-9_-]{20}'],
    'cloud-token': [rb'(?:AKIA|ASIA)[0-9A-Z]{16}', rb'AIza[0-9A-Za-z_-]{35}'],
    'llm-provider-key': [rb'sk-ant-[A-Za-z0-9_-]{20,}', rb'sk-proj-[A-Za-z0-9_-]{20,}',
                         rb'sk-[A-Za-z0-9]{48}'],
}
OWNER_CLASSES = sorted(list(OWNER_PATTERNS) + ['host-account'])
CONTROL_DIR = '/srv/scratch/agent'
COLLECT_MAX_BYTES = 512 << 20
MEMBER_MAX_BYTES = 64 << 20
# What the collection reads, as the agent user (no sudo): the contract's /etc and home
# directories, the scratch disk, cloud-init's run, state and log files, every readable
# process environment, and the login shell's environment.
COLLECT_ROOTS = ('etc', 'home', 'root', 'srv/scratch', 'run/cloud-init', 'var/lib/cloud',
                 'var/log')
COLLECT_SCRIPT = r'''set -u
d=$(mktemp -d /tmp/aieh-p5.XXXXXX) || exit 70
trap 'rm -rf "$d"' EXIT
mkdir "$d/aieh-env"
env > "$d/aieh-env/ssh-session.env"
bash -lc env > "$d/aieh-env/login-shell.env" 2>&1
if cat /proc/1/environ > /dev/null 2>"$d/aieh-env/pid1.err"; then echo readable; else echo unreadable; fi > "$d/aieh-env/pid1.status"
for p in /proc/[0-9]*; do
  n=${p#/proc/}
  if cat "$p/environ" > "$d/aieh-env/proc-$n.environ" 2>/dev/null; then :; else rm -f "$d/aieh-env/proc-$n.environ"; echo "$n" >> "$d/aieh-env/unreadable-pids"; fi
done
tar -czf - --ignore-failed-read -C / @ROOTS@ -C "$d" aieh-env
'''


def collect_script():
    return COLLECT_SCRIPT.replace('@ROOTS@', ' '.join(COLLECT_ROOTS))


def control_samples(token):
    """One synthetic sample per Owner class for the positive control. Returns the file
    text and the stand-in account name the host-account class must also match."""
    rnd = lambda n, chars='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789': \
        ''.join(secrets.choice(chars) for _ in range(n))                   # noqa: E731
    account = f'aiehctl{token}'
    lines = [
        ARMOR.format('BEGIN'), rnd(64), ARMOR.format('END'),
        f'ghp_{rnd(36)}',
        f'AKIA{rnd(16, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")}',
        f'sk-ant-api03-{rnd(40)}',
        f'C:\\Users\\{account}\\AppData',
    ]
    return '\n'.join(lines) + '\n', account


def plant_control_script(path, text):
    return (f"set -e\numask 077\ncat > '{path}' <<'AIEHCONTROL'\n{text}AIEHCONTROL\n"
            f"stat -c '%n %s' '{path}'\n")


def host_account_literals(environ=None, principal=None):
    """The Owner's host account name and profile path, as byte literals to search for."""
    environ = os.environ if environ is None else environ
    names = {n for n in (environ.get('USERNAME'), (principal or '').split('\\')[-1]) if n}
    out = set()
    for n in names:
        out.add(n)
    profile = environ.get('USERPROFILE')
    if profile:
        out.add(profile)
        out.add(profile.replace('\\', '/'))
        drive, rest = profile[:1].lower(), profile[2:].replace('\\', '/')
        out.update({f'/{drive}{rest}', f'/mnt/{drive}{rest}'})
    return sorted(out, key=len, reverse=True)


def private_key_needles(key_path):
    """Byte strings that occur only if the per-instance private key's secret material
    is present: every base64 body line of the OpenSSH key file, and the ed25519 seed as
    raw bytes, hex, and base64 at each of the three alignments."""
    text = Path(key_path).read_text(encoding='ascii')
    body = [line.strip() for line in text.splitlines()
            if line.strip() and not line.startswith('-----')]
    needles = {line.encode() for line in body if len(line) >= 20}
    blob = base64.b64decode(''.join(body))
    if not blob.startswith(b'openssh-key-v1\0'):
        raise Refused('REFUSED', f'{key_path}: not an OpenSSH private key')
    off = len(b'openssh-key-v1\0')

    def take():
        nonlocal off
        size = int.from_bytes(blob[off:off + 4], 'big')
        value = blob[off + 4:off + 4 + size]
        off += 4 + size
        return value

    take(), take(), take()                       # cipher, kdf, kdf options
    off += 4                                     # number of keys
    take()                                       # public key
    private = take()
    off = 0
    blob = private
    off += 8                                     # two check integers
    take(), take()                               # key type, public key
    secret = take()                              # 64 bytes: seed then public key
    seed = secret[:32]
    needles.update({seed, seed.hex().encode()})
    for shift in range(3):
        part = seed[shift:]
        encoded = base64.b64encode(part)[:4 * (len(part) // 3)]
        needles.add(encoded)
    return sorted(needles)


def scan_bytes(data, literals, patterns):
    """Labels of the literals and pattern classes found in one byte string."""
    found = {label for label, needle in literals if needle in data}
    for label, regexes in patterns.items():
        if any(re.search(rx, data) for rx in regexes):
            found.add(label)
    return found


def scan_tar(tar_bytes, literals, patterns):
    """Search every member (name and content) of a gzip tar stream.

    Returns {'members': n, 'bytes': total, 'hits': [{'label', 'member'}], 'truncated': [..]}.
    """
    hits, members, total, truncated = [], 0, 0, []
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode='r:gz') as tar:
        for member in tar:
            members += 1
            data = member.name.encode('utf-8', errors='replace')
            if member.isfile():
                handle = tar.extractfile(member)
                content = handle.read(MEMBER_MAX_BYTES + 1) if handle else b''
                if len(content) > MEMBER_MAX_BYTES:
                    truncated.append(member.name)
                total += len(content)
                data += b'\n' + content
            elif member.issym() or member.islnk():
                data += b'\n' + member.linkname.encode('utf-8', errors='replace')
            for label in sorted(scan_bytes(data, literals, patterns)):
                hits.append({'label': label, 'member': member.name})
    return {'members': members, 'bytes': total, 'hits': hits, 'truncated': truncated}


def tar_member_names(tar_bytes):
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode='r:gz') as tar:
        return [m.name for m in tar]


def tar_member_text(tar_bytes, name):
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode='r:gz') as tar:
        try:
            handle = tar.extractfile(name)
        except KeyError:
            return None
        return handle.read().decode('utf-8', errors='replace') if handle else None


def p5_needles(canaries, key_path, environ=None, principal=None, control_account=None):
    """(literals, patterns): literals are (label, bytes); the canary values are labelled
    by their canary label only."""
    literals = []
    if canaries:
        for label, value in sorted(canaries['needles'].items()):
            literals.append((f'canary:{label}', value.encode()))
            for core in re.findall(r'[0-9a-f]{32}', value):
                literals.append((f'canary:{label}', core.encode()))
    if key_path:
        literals += [('instance-private-key', n) for n in private_key_needles(key_path)]
    patterns = {f'owner:{k}': [re.compile(rx) for rx in v] for k, v in OWNER_PATTERNS.items()}
    # the account name and profile path: case-insensitive, not inside a longer word
    accounts = host_account_literals(environ, principal) + \
        ([control_account] if control_account else [])
    patterns['owner:host-account'] = [
        re.compile(rb'(?i)(?<![A-Za-z0-9])' + re.escape(a.encode('utf-8')) + rb'(?![A-Za-z0-9])')
        for a in accounts]
    return literals, patterns


def owner_class(label):
    """'owner:cloud-token' -> 'cloud-token'; anything else -> None."""
    parts = label.split(':')
    return parts[1] if parts[0] == 'owner' else None


def summarize_p5(scan, control_member, host_scans):
    """Split the hits into the positive control, Owner-class hits, canaries and key."""
    out = {'members': scan['members'], 'bytes': scan['bytes'], 'truncated': scan['truncated'],
           'control_classes': sorted({owner_class(h['label']) for h in scan['hits']
                                      if h['member'] == control_member and owner_class(h['label'])}),
           'owner_hits': [], 'canary_hits': [], 'key_hits': []}
    for source, hits in [('guest', scan['hits'])] + [(f'host:{k}', v) for k, v in host_scans.items()]:
        for hit in hits:
            label, where = hit['label'], f'{source}:{hit.get("member", "")}'
            if source == 'guest' and hit['member'] == control_member:
                continue
            if label.startswith('canary:'):
                out['canary_hits'].append({'label': label, 'where': where})
            elif label == 'instance-private-key':
                out['key_hits'].append({'where': where})
            elif label.startswith('owner:'):
                out['owner_hits'].append({'class': owner_class(label), 'where': where})
    return out


def scan_host_file(path, literals, patterns, owner=True):
    data = Path(path).read_bytes()
    use = [(lab, n) for lab, n in literals if owner or not lab.startswith('owner:')]
    pats = patterns if owner else {}
    return [{'label': lab, 'member': Path(path).name} for lab in sorted(scan_bytes(data, use, pats))]


def collect_p5(ssh, idir, record, canaries):
    """The P5 test: plant the positive control, collect, remove it, scan on the host.

    Canary values never travel to the guest: the guest's data comes to the host and is
    searched here. The control file holds synthetic samples of each Owner class only.
    """
    token = secrets.token_hex(6)
    control_path = f'{CONTROL_DIR}/.aieh-p5-control-{token}'
    text, account = control_samples(token)
    planted = ssh.run(['bash', '-s'], input_text=plant_control_script(control_path, text),
                      timeout=120)
    collected = ssh.run_raw(['bash', '-s'], input_text=collect_script(), timeout=900)
    removed = ssh.run(['bash', '-s'], input_text=f"rm -f -- '{control_path}'\n"
                      f"test -e '{control_path}' && echo present || echo absent\n", timeout=120)
    out = {'control': {'path': control_path, 'planted_rc': planted.returncode,
                       'planted': planted.stdout.strip(), 'removed': removed.stdout.strip(),
                       'expected_classes': OWNER_CLASSES},
           'collection': {'rc': collected.returncode, 'bytes': len(collected.stdout),
                          'roots': list(COLLECT_ROOTS),
                          'stderr': [line for line in collected.stderr.splitlines()
                                     if line.strip()]},
           'canaries': canary_summary(canaries['needles']) if canaries else None}
    if len(collected.stdout) > COLLECT_MAX_BYTES:
        out['collection']['error'] = f'more than {COLLECT_MAX_BYTES} bytes'
        return out
    literals, patterns = p5_needles(canaries, Path(idir) / 'ssh' / 'id_ed25519',
                                    principal=record.get('host_principal'),
                                    control_account=account)
    try:
        scan = scan_tar(collected.stdout, literals, patterns)
        names = tar_member_names(collected.stdout)
    except (tarfile.TarError, OSError, EOFError) as exc:
        out['collection']['error'] = f'{type(exc).__name__}: {exc}'
        return out
    out['collection']['env_files'] = sorted(n for n in names if n.startswith('aieh-env/'))
    out['collection']['pid1_environ'] = (tar_member_text(collected.stdout, 'aieh-env/pid1.status')
                                         or '').strip()
    out['collection']['pid1_error'] = (tar_member_text(collected.stdout, 'aieh-env/pid1.err')
                                       or '').strip()
    host = {'seed.iso': record['inputs']['seed']['path'],
            'launch.json': str(Path(idir) / 'launch.json'),
            'serial.log': str(Path(idir) / 'serial.log')}
    host_scans = {}
    for key, path in host.items():
        # launch.json records the host principal by design (profiles P8); it is searched
        # for canaries and the private key only. The seed and the guest's serial
        # console output are searched for everything.
        host_scans[key] = scan_host_file(path, literals, patterns, owner=key != 'launch.json')
    out['host_files'] = sorted(host)
    out['summary'] = summarize_p5(scan, control_path.lstrip('/'), host_scans)
    return out


# ---------------------------------------------------------------- guest storage (P3, P4)


def flatten_mounts(findmnt_text):
    out = []

    def walk(nodes):
        for node in nodes:
            out.append({k: node.get(k) for k in ('target', 'source', 'fstype', 'options')})
            walk(node.get('children') or [])
    try:
        walk(json.loads(findmnt_text or '{}').get('filesystems') or [])
    except (ValueError, AttributeError):
        return None
    return out


def lsblk_disks(lsblk_text):
    """{device path: disk serial} for every disk and its partitions, plus the disk list."""
    paths, disks = {}, []
    try:
        top = json.loads(lsblk_text or '{}').get('blockdevices') or []
    except (ValueError, AttributeError):
        return None, None

    def walk(node, serial):
        if node.get('path'):
            paths[node['path']] = serial
        for child in node.get('children') or []:
            walk(child, serial)
    for dev in top:
        disks.append({'serial': dev.get('serial'), 'type': dev.get('type'), 'ro': dev.get('ro'),
                      'mountpoints': [m for m in dev.get('mountpoints') or [] if m]})
        walk(dev, dev.get('serial'))
    return paths, disks


def target_matches(pattern, target):
    regex = '^' + re.escape(pattern).replace(r'\*', '[^/]+') + '$'
    return bool(re.match(regex, target or ''))


def compare_mounts(storage, mounts, device_serials):
    """The effective mount table against guest_storage.mounts, exactly.

    Every observed mount must match one entry (target, file system type, and the disk
    or source); every entry that is not optional must be observed. Returns
    {'unlisted': [...], 'missing': [...], 'matched': n}.
    """
    devices = storage.get('block_devices') or {}
    entries = storage.get('mounts') or []
    used = [0] * len(entries)
    unlisted = []
    for mount in mounts:
        hit = None
        for i, entry in enumerate(entries):
            if entry.get('fstype') != mount['fstype'] or not target_matches(entry['target'],
                                                                             mount['target']):
                continue
            if 'disk' in entry:
                serial = (devices.get(entry['disk']) or {}).get('serial')
                if device_serials.get(mount['source']) != serial or serial is None:
                    continue
            elif entry.get('source') != mount['source']:
                continue
            if '*' not in entry['target'] and used[i]:
                continue
            hit = i
            break
        if hit is None:
            unlisted.append(mount)
        else:
            used[hit] += 1
    missing = [e for e, n in zip(entries, used) if not n and not e.get('optional')]
    return {'unlisted': unlisted, 'missing': missing, 'matched': sum(used)}


def declared_block_nodes(storage, values):
    """{node-name: {'ro': bool, 'file': path or None}} from guest_storage.block_devices."""
    out = {}
    for dev in (storage.get('block_devices') or {}).values():
        for spec in (dev, dev.get('backing')):
            if not spec:
                continue
            ro = bool(spec.get('read_only'))
            out[spec['node']] = {'ro': ro, 'file': None}
            out[spec['file_node']] = {'ro': ro, 'file': expand(spec['file'], values)}
    return out


def record_values(record):
    """Placeholder values for an instance, from its launch record."""
    return {'instance_dir': record['instance']['instance_dir'],
            'input:image': record['inputs']['image']['path'],
            'input:seed': record['inputs']['seed']['path'],
            'input:firmware': record['inputs']['firmware']['path']}


VIRTIO_LINUX_IDS = {1: 'net', 2: 'block', 3: 'console', 4: 'entropy', 9: '9p',
                    19: 'vsock', 26: 'fs'}
# Host-management sockets and display channels that must not exist in the guest
# (profiles P6): container engines, Incus/LXD, libvirt, X11, Wayland, WSLg, PulseAudio.
MGMT_PATHS = ('/var/run/docker.sock', '/run/docker.sock', '/run/podman/podman.sock',
              '/run/containerd/containerd.sock', '/var/lib/incus/unix.socket',
              '/var/snap/lxd/common/lxd/unix.socket', '/var/lib/lxd/unix.socket',
              '/run/libvirt/libvirt-sock', '/var/run/libvirt/libvirt-sock', '/mnt/wslg',
              '/run/user/1000/docker.sock', '/run/user/1000/podman/podman.sock')
MGMT_SOCKET_NAMES = re.compile(r'(^|/)(docker\.sock|podman\.sock|containerd\.sock|'
                               r'unix\.socket|libvirt-sock(-ro)?|X\d+|wayland-\d+|'
                               r'PulseServer|wslg[^/]*)$')
MGMT_ENV = ('DOCKER_HOST', 'CONTAINER_HOST', 'DISPLAY', 'WAYLAND_DISPLAY', 'SSH_AUTH_SOCK',
            'PULSE_SERVER', 'LIBVIRT_DEFAULT_URI', 'INCUS_SOCKET', 'LXD_SOCKET')


def parse_kv_lines(text):
    out = {}
    for line in (text or '').splitlines():
        key, sep, value = line.partition('=')
        if sep:
            out[key.strip()] = value.strip()
    return out


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


VSOCK_PROBE = r'''import errno, fcntl, socket, struct
try:
    with open('/dev/vsock', 'rb') as f:
        buf = bytearray(4)
        fcntl.ioctl(f, 0x7b9, buf)       # IOCTL_VM_SOCKETS_GET_LOCAL_CID
        print('local_cid', struct.unpack('I', buf)[0])
except FileNotFoundError:
    print('local_cid absent')
try:
    s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect((2, 1024))
    print('cid2 CONNECTED')
except OSError as exc:
    print('cid2', errno.errorcode.get(exc.errno, exc.errno))
'''


def storage_probes(storage):
    """Probes for the declared directories and forbidden paths (guest_storage)."""
    storage = storage or {}
    dirs = ' '.join(f"'{d['path']}'" for d in storage.get('directories') or [])
    forbidden = ' '.join(f"'{p}'" for p in storage.get('forbidden_paths') or [])
    return [
        ('storage_dirs', f"stat -c '%n|%U|%G|%a|%F|%m' -- {dirs}" if dirs else 'echo none'),
        ('forbidden_paths', f'for p in {forbidden}; do if [ -e "$p" ] || [ -L "$p" ]; then '
                            'echo "present $p"; else echo "absent $p"; fi; done' if forbidden
         else 'echo none'),
    ]


def guest_probes(ports, host_ips, http_ip, storage=None):
    """(name, bash snippet) pairs: read-only inspection and egress probes."""
    mgmt_paths = ' '.join(MGMT_PATHS)
    env_names = ' '.join(MGMT_ENV)
    probes = [
        ('uname', 'uname -srvmo'),
        ('virt', 'systemd-detect-virt'),
        ('nproc', 'nproc'),
        ('meminfo', 'grep -E "^(MemTotal|SwapTotal):" /proc/meminfo'),
        ('lsblk', 'lsblk -J -b -o NAME,PATH,SIZE,TYPE,RO,SERIAL,FSTYPE,LABEL,MOUNTPOINTS'),
        # P3, P4, P6 (F-03.3.1): devices, directories and host-management surfaces
        ('virtio_devices', 'for d in /sys/bus/virtio/devices/*; do [ -e "$d/device" ] && '
                           'printf "%s %s\\n" "$(cat "$d/vendor")" "$(cat "$d/device")"; '
                           'done; echo end'),
        ('vsock', "timeout 20 python3 - <<'PYEOF'\n" + VSOCK_PROBE + 'PYEOF'),
        ('socket_inventory', 'find / \\( -path /proc -o -path /sys \\) -prune -o -type s '
                             '-print 2>/dev/null | sort; echo end'),
        ('mgmt_paths', f'for p in {mgmt_paths}; do if [ -e "$p" ] || [ -L "$p" ]; then '
                       'echo "present $p"; fi; done; echo end'),
        ('mgmt_env', f'for v in {env_names}; do if [ -n "${{!v+x}}" ]; then echo "session $v=set"; '
                     'else echo "session $v=unset"; fi; done; '
                     f"bash -lc 'for v in {env_names}; do if [ -n \"${{!v+x}}\" ]; then "
                     "echo \"login $v=set\"; else echo \"login $v=unset\"; fi; done'"),
        ('guest_ssh_agent', 's="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/openssh_agent"; '
                            'if [ -S "$s" ]; then SSH_AUTH_SOCK="$s" timeout 10 ssh-add -l; '
                            'else echo "no guest agent socket"; fi'),
        ('qemu_ga', 'command -v qemu-ga || echo "qemu-ga absent"; '
                    'systemctl is-active qemu-guest-agent'),
    ] + storage_probes(storage) + [
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
        # P6 (amended 2026-11-06): no socket under /tmp/.X11-unix; see x11_unix_clean
        ('x11_unix', 'x=/tmp/.X11-unix; if [ -L "$x" ]; then echo symlink; elif [ ! -e "$x" ]; '
                     'then echo absent; else echo "type=$(stat -c %F "$x")"; '
                     "find \"$x\" -mindepth 1 ! -type d -printf '%y %p\\n'; echo end; fi"),
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


def x11_unix_clean(text):
    """P6 as amended on 2026-11-06 (decision 0003, "Current facts").

    No socket under /tmp/.X11-unix: the path is absent, or it is a directory whose
    entries are all directories (the x11_unix probe lists every other entry, one per
    line, between the type line and "end"). A symlink, a non-directory at the path,
    any listed entry, an error line or unparsable output is not clean.
    """
    lines = [line for line in text.replace('\r', '').split('\n') if line.strip()]
    if lines == ['absent']:
        return True
    return lines == ['type=directory', 'end']


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


def parse_virtio(text):
    """{'block': 3, 'net': 1, ...} from the virtio_devices probe; None if incomplete."""
    lines = [line.strip() for line in (text or '').splitlines() if line.strip()]
    if not lines or lines[-1] != 'end':
        return None
    out = {}
    for line in lines[:-1]:
        parts = line.split()
        if len(parts) != 2:
            return None
        try:
            ident = int(parts[1], 16)
        except ValueError:
            return None
        name = VIRTIO_LINUX_IDS.get(ident, f'id-{ident}')
        out[name] = out.get(name, 0) + 1
    return out


def listed_until_end(text):
    """The lines of a probe that ends with 'end'; None if the listing is incomplete."""
    lines = [line.strip() for line in (text or '').splitlines() if line.strip()]
    return lines[:-1] if lines and lines[-1] == 'end' else None


def storage_checks(profile, record, obs):
    """profiles P3 and P4 against guest_storage (F-03.3.1). Returns (p3, p4) checks."""
    g = obs.get('guest', {})
    q = obs.get('qmp', {})
    out_text = lambda key: (g.get(key) or {}).get('out', '')      # noqa: E731
    storage = profile.get('guest_storage') or {}
    forbidden = storage.get('forbidden_fstypes') or SHARE_FSTYPES.split(',')
    share_count = re.search(r'count=(\d+)', out_text('findmnt_shares'))
    mounts = flatten_mounts(out_text('findmnt'))
    serials, disks = lsblk_disks(out_text('lsblk'))
    fstypes = sorted({m['fstype'] for m in mounts or [] if m.get('fstype')})
    bad_types = [t for t in fstypes if t in forbidden or t.split('.')[0] in forbidden]
    diff = compare_mounts(storage, mounts, serials) \
        if storage.get('mounts') and mounts and serials is not None else None
    virtio = parse_virtio(out_text('virtio_devices'))
    declared_virtio = storage.get('virtio_devices')
    forbidden_paths = storage.get('forbidden_paths') or []
    fp_lines = out_text('forbidden_paths').splitlines()
    p3 = [
        check('share mounts', 0, int(share_count.group(1)) if share_count else None,
              f'guest: findmnt -t {SHARE_FSTYPES}',
              share_count is not None and int(share_count.group(1)) == 0),
        check('mount table file systems', f'none of {forbidden}', fstypes, 'guest: findmnt -J',
              not bad_types if mounts else None),
        check('mount table equals the declared allowlist', 'profile guest_storage.mounts',
              None if diff is None else {'matched': diff['matched'], 'unlisted': diff['unlisted'],
                                         'missing': [e['target'] for e in diff['missing']]},
              'guest: findmnt -J, with lsblk -J for the disk of each block mount',
              None if diff is None else not diff['unlisted'] and not diff['missing']),
        check('forbidden paths', [f'absent {p}' for p in forbidden_paths], fp_lines,
              'guest: test -e, test -L',
              fp_lines == [f'absent {p}' for p in forbidden_paths] if forbidden_paths else None),
        check('/mnt/c', 'absent', out_text('mnt_c'), 'guest: test -e', out_text('mnt_c') == 'absent'),
        check('guest virtio devices', declared_virtio, virtio,
              'guest: /sys/bus/virtio/devices/*/device (no 9p or virtiofs device)',
              virtio == declared_virtio if virtio is not None and declared_virtio else None),
        check('host shares declared', [], profile.get('host_shares'), 'profile',
              profile.get('host_shares') == []),
    ]

    values = record_values(record)
    devices = storage.get('block_devices') or {}
    declared_nodes = declared_block_nodes(storage, values) if devices else None
    observed_nodes = {n.get('node-name'): {'ro': n.get('ro'), 'file': n.get('file')}
                      for n in q.get('query-named-block-nodes') or []}
    nodes_ok = None
    if declared_nodes is not None and observed_nodes:
        nodes_ok = set(observed_nodes) == set(declared_nodes) and all(
            observed_nodes[k]['ro'] is v['ro'] and
            (v['file'] is None or same_path(str(observed_nodes[k]['file']), v['file']))
            for k, v in declared_nodes.items())
    top = sorted(str((b.get('inserted') or {}).get('node-name')) for b in q.get('query-block') or [])
    declared_top = sorted(d['node'] for d in devices.values()) or ['root', 'scratch', 'seed']
    disk_list = [d for d in disks or [] if d.get('type') == 'disk']
    declared_disks = {d['serial']: {'ro': bool(d.get('read_only')),
                                    'mounted': d.get('mounted', True)} for d in devices.values()}
    disks_ok = None
    if disks is not None and declared_disks:
        disks_ok = len(disk_list) == len(disks) and \
            sorted(str(d.get('serial')) for d in disk_list) == sorted(declared_disks) and all(
                truthy(d.get('ro')) == declared_disks[d['serial']]['ro'] and
                (declared_disks[d['serial']]['mounted'] or not d['mountpoints'])
                for d in disk_list if d.get('serial') in declared_disks)
    dirs = storage.get('directories') or []
    want_dirs = [f"{d['path']}|{d['owner']}|{d['group']}|{d['mode']}|directory|{d['mount']}"
                 for d in dirs]
    got_dirs = out_text('storage_dirs').splitlines()
    pci = flatten_pci(q.get('query-pci'))
    virtio_pci, unknown = {}, []
    for dev in pci:
        ident = dev.get('id') or {}
        vendor, device = ident.get('vendor'), ident.get('device')
        if vendor == 0x1af4 and device in VIRTIO_IDS:
            virtio_pci[VIRTIO_IDS[device]] = virtio_pci.get(VIRTIO_IDS[device], 0) + 1
        elif (vendor, device) not in Q35_BUILTIN:
            unknown.append({'vendor': vendor, 'device': device,
                            'class': (dev.get('class_info') or {}).get('class'),
                            'qdev_id': dev.get('qdev_id')})
    declared_dev = {}
    argv = profile['launch']['argv']
    for i, arg in enumerate(argv[:-1]):
        if arg == '-device':
            model = argv[i + 1].split(',')[0]
            declared_dev[model] = declared_dev.get(model, 0) + 1
    seed_dev = lsblk_by_serial(out_text('lsblk')).get('cidata') or {}
    p4 = [
        check('block devices (QMP)', declared_top, top, 'QMP query-block', top == declared_top),
        check('block nodes: names, read-only flags and files', declared_nodes, observed_nodes,
              'QMP query-named-block-nodes flat=true', nodes_ok),
        check('guest disks', declared_disks, disk_list, 'guest: lsblk -J (type disk, by serial)',
              disks_ok),
        check('pci virtio devices', declared_dev, virtio_pci, 'QMP query-pci',
              virtio_pci == declared_dev),
        check('pci devices outside virtio and the q35 chipset', [], unknown, 'QMP query-pci',
              not unknown),
        check('seed read-only in the guest', True, seed_dev.get('ro'), 'guest: lsblk (serial cidata)',
              truthy(seed_dev.get('ro')) if seed_dev else None),
        check('scratch mounted', '/srv/scratch ext4', out_text('scratch_mount'), 'guest: findmnt',
              ' ext4 ' in f' {out_text("scratch_mount")} '),
        check('exchange and scratch directories', want_dirs, got_dirs,
              "guest: stat -c '%n|%U|%G|%a|%F|%m'", got_dirs == want_dirs if dirs else None),
    ]
    return p3, p4


LAUNCH_ENV_ALLOWED = set(ENV_ALLOW) | {'PATH', 'TEMP', 'TMP'}


def p5_checks(record, obs):
    """profiles P5 (F-03.3.1): the Owner-class scan with its positive control, the
    canaries, the per-instance private key and the launch environment."""
    env_keys = sorted((record.get('env') or {}).keys())
    checks = [check('launch environment', f'a subset of {sorted(LAUNCH_ENV_ALLOWED)}', env_keys,
                    'launch record env (QEMU and qemu-img)',
                    set(env_keys) <= LAUNCH_ENV_ALLOWED)]
    p5 = obs.get('p5')
    summary = (p5 or {}).get('summary')
    if not summary:
        reason = (p5 or {}).get('collection', {}).get('error') if p5 else 'not run'
        return checks + [check('guest scan', 'collected and scanned', reason,
                               'guest tar over SSH, scanned on the host', None)]
    coll = p5['collection']
    needed = {'aieh-env/ssh-session.env', 'aieh-env/login-shell.env', 'aieh-env/pid1.status'}
    control = p5['control']
    checks += [
        check('collection', f'complete: {COLLECT_ROOTS} and the process environments',
              {'rc': coll.get('rc'), 'bytes': coll.get('bytes'), 'members': summary['members'],
               'env_files': len(coll.get('env_files') or []), 'truncated': summary['truncated']},
              'guest: tar -czf - as agent over SSH; host: tarfile',
              coll.get('rc') in (0, 1) and summary['members'] > 0 and not summary['truncated']
              and needed <= set(coll.get('env_files') or [])),
        check('positive control', {'classes': OWNER_CLASSES, 'removed': 'absent'},
              {'classes': summary['control_classes'], 'planted_rc': control.get('planted_rc'),
               'removed': control.get('removed')},
              f'guest: a synthetic sample of each class in {CONTROL_DIR}, scanned, then removed',
              control.get('planted_rc') == 0 and summary['control_classes'] == OWNER_CLASSES
              and control.get('removed') == 'absent'),
        check('Owner-class scan', [], summary['owner_hits'],
              'host: regex and literal search of the collection, the seed and serial.log',
              not summary['owner_hits']),
        check('canaries', 'none found', None if p5.get('canaries') is None else
              {'planted': len(p5['canaries']), 'hits': summary['canary_hits']},
              'host: literal search of the collection, seed.iso, launch.json and serial.log',
              None if p5.get('canaries') is None else not summary['canary_hits']),
        check('per-instance private key', 'not in the guest', summary['key_hits'],
              'host: key body lines and the ed25519 seed (raw, hex, base64 at 3 alignments)',
              not summary['key_hits']),
    ]
    return checks


def p6_checks(profile, record, obs):
    """profiles P6 (F-03.3.1): no host-management socket, channel or display."""
    g = obs.get('guest', {})
    q = obs.get('qmp', {})
    out_text = lambda key: (g.get(key) or {}).get('out', '')      # noqa: E731
    chardevs = sorted(c.get('label') for c in q.get('query-chardev') or [])
    virtio = parse_virtio(out_text('virtio_devices'))
    channels = sorted(k for k in (virtio or {}) if k in ('console', 'vsock', '9p', 'fs')
                      or k.startswith('id-'))
    vsock = dict(line.split(' ', 1) for line in out_text('vsock').splitlines() if ' ' in line)
    sockets = listed_until_end(out_text('socket_inventory'))
    listening = [line.split()[4] for line in out_text('unix_sockets').splitlines()
                 if len(line.split()) > 4]
    mgmt_sockets = sorted({s for s in (sockets or []) + listening if MGMT_SOCKET_NAMES.search(s)})
    present = listed_until_end(out_text('mgmt_paths'))
    env = out_text('mgmt_env').splitlines()
    want_env = [f'{scope} {v}=unset' for scope in ('session', 'login') for v in MGMT_ENV]
    qmp_probes = {k: v for k, v in g.items() if k.startswith('egress_tcp_') and k.endswith('_qmp')}
    agent = out_text('guest_ssh_agent')
    return [
        check('chardevs', ['qmp', 'serial0'], chardevs, 'QMP query-chardev',
              chardevs == ['qmp', 'serial0']),
        check('virtio-serial ports', 'absent', out_text('virtio_ports'), 'guest: ls /dev/virtio-ports',
              (g.get('virtio_ports') or {}).get('rc') not in (0, None)),
        check('virtio channel devices', 'no console, vsock, 9p or fs device', virtio,
              'guest: /sys/bus/virtio/devices/*/device', None if virtio is None else not channels),
        check('vsock', 'no guest-to-host transport: local CID 1 (loopback) or -1; CID 2 not '
              'connected', vsock, 'guest: AF_VSOCK ioctl and connect to CID 2',
              vsock.get('local_cid') in ('1', '4294967295', 'absent') and 'cid2' in vsock
              and vsock.get('cid2') != 'CONNECTED'),
        check('host-management paths', [], present, f'guest: test -e {list(MGMT_PATHS)}',
              present == [] if present is not None else None),
        check('socket inventory', 'no container-engine, Incus, libvirt, X11, Wayland, WSLg or '
              'PulseAudio socket', {'sockets': sockets, 'listening': listening,
                                    'matched': mgmt_sockets},
              'guest: find / -type s (excluding /proc, /sys); ss -xlH',
              None if sockets is None else not mgmt_sockets),
        check('management environment', 'unset in the session and the login shell', env,
              f'guest: {list(MGMT_ENV)}', env == want_env),
        check('/tmp/.X11-unix', 'absent, or a directory holding no socket or other '
              'non-directory entry; not a symlink', out_text('x11_unix'),
              "guest: test -L, stat -c %F, find -mindepth 1 ! -type d",
              x11_unix_clean(out_text('x11_unix'))),
        check('QMP from the guest', 'blocked', {k: v.get('rc') for k, v in qmp_probes.items()},
              'guest: bash /dev/tcp to 10.0.2.2 and the host addresses on the QMP port',
              bool(qmp_probes) and all(probe_blocked(k, v) for k, v in qmp_probes.items())),
        check('guest-local ssh-agent', 'no identities (no agent is forwarded)', agent,
              'guest: ssh-add -l on $XDG_RUNTIME_DIR/openssh_agent',
              'The agent has no identities.' in agent or agent == 'no guest agent socket'),
        check('guest agent', 'not declared; qemu-ga absent',
              {'declared': (profile.get('guest_agent') or {}).get('used'),
               'observed': out_text('qemu_ga').splitlines()[:1]},
              'profile; guest: command -v qemu-ga',
              (profile.get('guest_agent') or {}).get('used') is False and
              out_text('qemu_ga').startswith('qemu-ga absent')),
    ]


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

    p3, p4 = storage_checks(profile, record, obs)
    formal = 'F-03.3.1; S-02.1, S-02.2'
    props.append(prop('P3', p3, formal=formal))
    props.append(prop('P4', p4, formal=formal))
    props.append(prop('P5', p5_checks(record, obs), formal=formal, note=(
        'Scanned as the unprivileged agent user: root-only files in the guest (for example '
        '/proc/1/environ, /etc/shadow and the user-data.txt of cloud-init) are not read there; '
        'their source, the seed, is scanned on the host (seed.iso).')))
    props.append(prop('P6', p6_checks(profile, record, obs), formal=formal))

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


def inspect(ctx, name, canaries=None):
    """The P1-P12 record. ``canaries`` is a loaded canary set (load_canaries) or None;
    without it the P5 canary check is UNKNOWN."""
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
    probes = guest_probes(record['ports'], ips, http_ip, ctx.profile.get('guest_storage'))
    result = ssh.run(['bash', '-s'], input_text=probe_script(probes, marker), timeout=600)
    obs['guest'] = parse_probe_output(result.stdout, marker)
    obs['guest_ssh'] = {'rc': result.returncode, 'stderr': result.stderr.strip(),
                        'probes_expected': len(probes), 'probes_parsed': len(obs['guest'])}
    root = ssh.run(['true'], user='root', timeout=60)
    obs['root_login'] = {'rc': root.returncode, 'stderr': root.stderr.strip()}
    obs['p5'] = collect_p5(ssh, idir, record, canaries)
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


SURFACE_PROPERTIES = ('profiles P3', 'profiles P4', 'profiles P5', 'profiles P6')


def check_surfaces(ctx, name, canary_dir):
    """The startup inspection test (F-03.3.1): inspect with a canary set, then the verdict
    for profiles P3 to P6. PASS only when all four PASS; UNKNOWN counts as not passed."""
    canaries = load_canaries(canary_dir)
    record = inspect(ctx, name, canaries)
    verdicts = {p: record['verdicts'].get(p) for p in SURFACE_PROPERTIES}
    failing = [{'property': p['property'], 'check': c['check'], 'verdict': c['verdict']}
               for p in record['properties'] if p['property'] in SURFACE_PROPERTIES
               for c in p['checks'] if c['verdict'] != 'PASS']
    return {'operation': 'check-surfaces', 'labels': labels(ctx.profile), 'instance': name,
            'canaries': canary_summary(canaries['needles']), 'verdicts': verdicts,
            'not_passed': failing, 'inspect_record': record['record'],
            'all_verdicts': record['verdicts'],
            'result': 'PASS' if all(v == 'PASS' for v in verdicts.values()) else 'FAIL'}


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
    p = sub.add_parser('canaries')
    p.add_argument('--out', required=True, help='a new directory outside the checkout')
    for op in ('preflight', 'create', 'start', 'stop', 'destroy', 'recreate', 'inspect', 'exec',
               'exchange-push', 'exchange-pull', 'check-surfaces'):
        p = sub.add_parser(op)
        p.add_argument('--profile', required=True, help='profile directory (never defaulted)')
        p.add_argument('--state-dir', required=True, help='the Owner-named state directory')
        if op != 'preflight':
            p.add_argument('--name', required=True)
        if op in ('create', 'inspect'):
            p.add_argument('--canaries', help='a canary set written by the canaries operation')
        if op == 'check-surfaces':
            p.add_argument('--canaries', required=True,
                           help='a canary set written by the canaries operation')
        if op == 'exchange-push':
            p.add_argument('--repo', required=True, help='the repository to read the branch from')
            p.add_argument('--ref', required=True, help='one local branch')
            p.add_argument('--bundle-name', help='file name in the guest exchange directory')
        if op == 'exchange-pull':
            p.add_argument('--file', required=True, help='file name in the guest exchange directory')
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
        op = args.operation
        if op == 'canaries':
            print(json.dumps(make_canaries(args.out), indent=2, sort_keys=True))
            return 0
        ctx = Context(args.profile, args.state_dir)
        canaries = load_canaries(args.canaries) \
            if op in ('create', 'inspect') and args.canaries else None
        if op == 'exec':
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            return exec_command(ctx, args.name, command)
        if op == 'preflight':
            result = preflight(ctx)
        elif op == 'create':
            result = create(ctx, args.name, args.ready_timeout, canaries)
        elif op == 'start':
            result = start(ctx, args.name, args.ready_timeout)
        elif op == 'stop':
            result = stop(ctx, args.name, args.force)
        elif op == 'destroy':
            result = destroy(ctx, args.name)
        elif op == 'recreate':
            result = recreate(ctx, args.name, args.ready_timeout)
        elif op == 'exchange-push':
            result = exchange_push(ctx, args.name, args.repo, args.ref, args.bundle_name)
        elif op == 'exchange-pull':
            result = exchange_pull(ctx, args.name, args.file)
        elif op == 'check-surfaces':
            result = check_surfaces(ctx, args.name, args.canaries)
        else:
            result = inspect(ctx, args.name, canaries)
    except Refused as exc:
        print(f'REFUSED {exc.code}: {exc}', file=sys.stderr)
        print(json.dumps({'result': 'refused', 'code': exc.code, 'message': str(exc),
                          'detail': exc.detail}, indent=2, sort_keys=True, default=str))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if result.get('operation') == 'check-surfaces':
        return 0 if result.get('result') == 'PASS' else 1
    failed = result.get('result') in ('unavailable', 'not-ready') or \
        'FAIL' in (result.get('verdicts') or {}).values() or \
        result.get('create', {}).get('result') == 'not-ready'
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
