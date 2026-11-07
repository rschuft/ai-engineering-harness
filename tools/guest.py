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
    netprobe   TEST-ONLY validation cycle for profiles P7 (F-03.3.2; decision 0003,
               "Owner authorization: network validation"): starts a test listener and
               decoys on 127.0.0.1, creates a disposable guest whose seed carries the
               pinned root probe script and whose -netdev carries one test guestfwd to
               the listener, collects the guest's results and the listener log, stops
               the listener, and gives the machine verdict. Ordinary create never
               takes these inputs; a validation instance cannot be started again.
    smoke      the F-03.4 provision/inspect/teardown test on a fresh instance name:
               preflight, create, inspect, graceful stop, start, inspect, forced stop,
               recreate, inspect, destroy, destroy again; inspect records compared
               across start and recreate (stable, per-instance and volatile fields),
               and inventories of the durable sources (the checkout, the state
               directory's image and provider, the other instances/ entries and the
               named --durable roots) compared across every destroy and recreate.
               One machine verdict, PASS or FAIL, with profiles P10.
    provision-fetch  host side of guest provisioning (F-04.1a; decision 0006, Proposed):
               every artifact of the profile's provision lock (provider.provision_lock,
               itself pinned by sha256) is downloaded from its upstream over https and
               checked against the lock; the agent-server image is read and pulled by the
               lock's pinned, verified crane (empty DOCKER_CONFIG, scrubbed environment),
               its manifests are checked against the locked digests and the archive's
               config and layer members against the lock. Staged atomically under
               STATE/provision/<lock sha256>/ with a staged.json manifest; a staged
               directory is re-verified and reused. No guest is involved and nothing
               downloaded is unpacked or run on the host except crane.
    provision  guest side of provisioning (F-04.1b; decision 0006): for an instance made
               with create --provision (whose seed carries the manifest of the verified
               stage and the single-use root step), re-verify the stage, SFTP the .deb
               files, the image archive and the release binary into the agent-owned
               upload directory within provisioning.upload's bounds, check each in the
               guest, create the READY marker, wait on the root step's RESULT.json (an
               inotify event, under a ceiling), fetch it and check it. The root step
               copies, verifies, installs Moby with apt from the local files, docker
               loads the image, checks its ID, keeps only the local immutable tag, runs it
               once, deletes the upload and disables itself. No network at any point.

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
    python -I -B tools/guest.py netprobe  --profile PROFILE --state-dir STATE --name NAME
    python -I -B tools/guest.py smoke     --profile PROFILE --state-dir STATE --name NAME
                                          --canaries DIR --durable DIR [--durable DIR ...]
                                          [--out FILE]
    python -I -B tools/guest.py provision-fetch --profile PROFILE --state-dir STATE
    python -I -B tools/guest.py create    --profile PROFILE --state-dir STATE --name NAME --provision
    python -I -B tools/guest.py provision --profile PROFILE --state-dir STATE --name NAME
    (start, stop, destroy and recreate take the same arguments as inspect; create and
    inspect also take --canaries DIR: create plants the set in its own environment
    before it launches anything, inspect searches the guest for it; create, recreate
    and smoke also take --provision)

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
import copy
import importlib.util
import io
import ipaddress
import json
import os
import platform
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LAUNCH_SCHEMA = 'ai-engineering-harness/profiles/launch-record/v1'
INSPECT_SCHEMA = 'ai-engineering-harness/profiles/inspect-record/v1'
SMOKE_SCHEMA = 'ai-engineering-harness/profiles/smoke-record/v1'
LOG_HEADER_SCHEMA = 'ai-engineering-harness/profiles/log-header/v1'
LOG_HEADER_PREFIX = 'AIEH-LOG-HEADER '
# profiles P11: the label fields and their allowed values
LABEL_VALUES = {'tier': ('strong', 'trusted-workload'), 'nesting': ('none', 'nested')}
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


def label_problems(lab, want=None):
    """profiles P11 schema check of one artifact's labels: tier, provider and nesting
    present with allowed values (and equal to ``want`` when given). [] when clean."""
    if not isinstance(lab, dict):
        return ['no labels']
    problems = [f'{key} missing' for key in ('tier', 'provider', 'nesting') if not lab.get(key)]
    for key, allowed in LABEL_VALUES.items():
        if lab.get(key) and lab[key] not in allowed:
            problems.append(f'{key} {lab[key]!r} not in {list(allowed)}')
    if lab.get('provider') is not None and not isinstance(lab['provider'], str):
        problems.append('provider is not a string')
    if want is not None and {k: lab.get(k) for k in want} != want:
        problems.append(f'differs from the profile labels {want}')
    return problems


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
                        inputs, argv, env, disk_commands, validation=None, provisioning=None):
    """launch.json: every boot input with its digest, the argv and the profile revision.
    A validation instance (netprobe) also records its validation block (Owner constraint 7:
    the full effective configuration); an ordinary record has no such key. An instance
    created with --provision (F-04.1) records its provisioning manifest; others do not."""
    record = {
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
    if validation is not None:
        record['validation'] = validation
    if provisioning is not None:
        record['provisioning'] = provisioning
    return record


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


# WHvGetCapability (WinHvPlatform.dll, Windows Hypervisor Platform API; WinHvPlatformDefs.h):
# the capability codes and the WHV_PROCESSOR_XSAVE_FEATURES bit layout used by preflight.
# It is a read-only query of what the hypervisor offers its partitions; it creates no
# partition and needs no privilege. Observed on the qualification host (F-03.4): code
# 0x1003 returned a mask whose decoded names matched the guest's /proc/cpuinfo flags,
# and 0x1004 (processor clock frequency) a frequency, which fixes the code assignment.
WHV_CAP_HYPERVISOR_PRESENT = 0x0000
WHV_CAP_PROCESSOR_VENDOR = 0x1000
WHV_CAP_PROCESSOR_XSAVE_FEATURES = 0x1003
WHV_VENDORS = {0: 'AMD', 1: 'Intel', 2: 'Hygon', 3: 'ARM'}
WHV_XSAVE_BITS = ('xsave', 'xsaveopt', 'avx', 'avx2', 'fma', 'mpx', 'avx512', 'avx512dq',
                  'avx512cd', 'avx512bw', 'avx512vl', 'xsavec', 'xsaves', 'xcr1',
                  'avx512_bitalg', 'avx512ifma', 'avx512vbmi', 'avx512_vbmi2', 'avx512_vnni',
                  'gfni', 'vaes', 'avx512_vpopcntdq', 'vpclmulqdq', 'avx512_bf16',
                  'avx512_vp2intersect', 'avx512_fp16', 'xfd', 'amx_tile', 'amx_bf16',
                  'amx_int8', 'avx_vnni')
XSAVES_BIT = WHV_XSAVE_BITS.index('xsaves')


def whv_get_capability(code, size=64):
    """(hresult, bytes written) of WHvGetCapability, from System32's WinHvPlatform.dll."""
    import ctypes
    dll = ctypes.WinDLL(str(Path(os.environ.get('SYSTEMROOT', r'C:\Windows')) / 'System32' /
                            'WinHvPlatform.dll'))
    func = dll.WHvGetCapability
    func.restype = ctypes.c_long
    func.argtypes = (ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                     ctypes.POINTER(ctypes.c_uint32))
    buf = (ctypes.c_uint8 * size)()
    written = ctypes.c_uint32(0)
    hr = func(code, buf, size, ctypes.byref(written))
    return hr & 0xffffffff, bytes(buf[:written.value])


def whpx_xsave_features(get=None):
    """Host XSAVE support as the Windows Hypervisor Platform reports it (README open item
    3: on hosts without XSAVES, -cpu max is expected to panic the guest kernel).

    Returns {'xsaves': True/False, ...} or {'xsaves': None, 'error': ...}. ``get`` is
    whv_get_capability, injectable for tests."""
    get = get or whv_get_capability
    try:
        out = {}
        for key, code in (('hypervisor_present', WHV_CAP_HYPERVISOR_PRESENT),
                          ('vendor', WHV_CAP_PROCESSOR_VENDOR),
                          ('xsave_mask', WHV_CAP_PROCESSOR_XSAVE_FEATURES)):
            hr, data = get(code)
            if hr != 0 or not data:
                return {'xsaves': None, 'error': f'WHvGetCapability(0x{code:04x}) returned '
                        f'0x{hr:08x} with {len(data)} bytes'}
            out[key] = int.from_bytes(data, 'little')
    except (OSError, AttributeError) as exc:
        return {'xsaves': None, 'error': f'{type(exc).__name__}: {exc}'}
    mask = out['xsave_mask']
    return {'xsaves': bool(mask >> XSAVES_BIT & 1),
            'hypervisor_present': bool(out['hypervisor_present']),
            'vendor': WHV_VENDORS.get(out['vendor'], out['vendor']),
            'xsave_mask': f'0x{mask:x}',
            'features': [n for i, n in enumerate(WHV_XSAVE_BITS) if mask >> i & 1],
            'method': 'WHvGetCapability(WHvCapabilityCodeProcessorXsaveFeatures), '
                      'bit XsaveSupervisorSupport'}


def xsaves_check(info):
    """(status, detail, owner act) of the preflight host-xsaves check."""
    if info.get('xsaves') is None:
        return ('unknown', 'host XSAVES not determined: ' + str(info.get('error')) +
                '; disclosed, not refused (README open item 3)', None)
    if info['xsaves']:
        return ('ok', f'XSAVES offered by the hypervisor ({info["vendor"]}, xsave features '
                f'{info["xsave_mask"]})', None)
    return ('fail', f'no XSAVES ({info["vendor"]}, xsave features {info["xsave_mask"]}): with '
            '-cpu max the guest kernel is expected to report an XSAVE consistency problem '
            'and panic (README open item 3)',
            'none: this host is not qualified for the profile\'s -cpu max (R-03.x qualifies '
            'a CPU model)')


def preflight(ctx, xsave_info=None):
    checks = []

    def add(check, ok, detail, act, status=None):
        checks.append({'check': check, 'status': status or ('ok' if ok else 'fail'),
                       'detail': detail, 'owner_act': None if ok or status == 'unknown' else act})

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
    if accel == 'whpx':
        info = xsave_info if xsave_info is not None else (
            whpx_xsave_features() if system == 'Windows' else
            {'xsaves': None, 'error': 'not a Windows host'})
        status, detail, act = xsaves_check(info)
        add('host-xsaves', status == 'ok', detail, act, status=status)
        checks[-1]['observed'] = info
    return {'operation': 'preflight', 'labels': labels(ctx.profile),
            'profile': ctx.profile['name'], 'provider': ctx.profile['provider']['name'],
            'result': 'available' if preflight_available(checks) else 'unavailable',
            'checks': checks}


def preflight_available(checks):
    """'unknown' is disclosed in the report and does not refuse (only host-xsaves uses it)."""
    return all(c['status'] in ('ok', 'unknown') for c in checks)


# ---------------------------------------------------------------- launch and readiness


def log_header(labels_, operation, instance):
    """One line written to stderr.log before each launch (profiles P11: a log header
    carries the tier label). QEMU's own output follows it."""
    return LOG_HEADER_PREFIX + json.dumps(
        {'schema': LOG_HEADER_SCHEMA, 'labels': labels_, 'operation': operation,
         'instance': instance, 'at': utc_now()}, sort_keys=True) + '\n'


def parse_log_headers(lines):
    """The header objects among stderr.log's lines (None for an unparsable header)."""
    out = []
    for line in lines:
        if line.startswith(LOG_HEADER_PREFIX):
            try:
                out.append(json.loads(line[len(LOG_HEADER_PREFIX):]))
            except ValueError:
                out.append(None)
    return out


def stderr_findings(instance_dir):
    path = Path(instance_dir) / 'stderr.log'
    text = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else ''
    every = [line for line in text.splitlines() if line.strip()]
    lines = [line for line in every if not line.startswith(LOG_HEADER_PREFIX)]
    return {'lines': lines,
            'headers': parse_log_headers(every),
            'first_line_is_header': bool(every) and every[0].startswith(LOG_HEADER_PREFIX),
            'whpx': [line for line in lines if 'WHPX:' in line],
            'interrupt_vector_0': sum(INTERRUPT_WARNING in line for line in lines)}


def launch(ctx, instance_dir, record, operation):
    """Re-check every input digest, then start QEMU detached and wait for QMP."""
    digests = verify_inputs(record)
    check_forwarding(record)
    if os.name != 'nt':
        raise Refused('REFUSED', 'launch is implemented for Windows only')
    if running_process(instance_dir, record['binary']):
        raise Refused('REFUSED', f'{record["instance"]["name"]} is already running')
    for key in ('ssh', 'qmp'):
        if not port_free(record['ports'][key]):
            raise Refused('REFUSED', f'{key} port {record["ports"][key]} on {LOOPBACK} is in use')
    started = time.time()
    with open(Path(instance_dir) / 'stderr.log', 'ab') as err:
        err.write(log_header(record['labels'], operation,
                             record['instance']['name']).encode('utf-8'))
        err.flush()
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


def create(ctx, name, ready_timeout=READY_TIMEOUT_S, canaries=None, netprobe=None,
           provision=False):
    """The create binding. ``netprobe`` is set only by the netprobe operation (a
    NetprobeSession); the ordinary create takes no validation input. ``provision`` (F-04.1)
    writes the provisioning manifest of the verified host stage into the seed; the
    provision operation then transfers the files and the seeded root step installs them."""
    if netprobe is not None and not isinstance(netprobe, NetprobeSession):
        raise Refused('REFUSED', 'create takes no validation overlay; only the netprobe '
                      'operation creates a validation instance')
    if provision and netprobe is not None:
        raise Refused('REFUSED', 'a validation instance is never provisioned')
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
    manifest = build_provision_manifest(ctx) if provision else None
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
    if netprobe is None:
        gen = load_seed_generator()
        try:
            seed = gen.generate(str(ctx.profile_path.parent), str(idir), name,
                                str(idir / 'ssh' / 'id_ed25519.pub'),
                                provision_manifest=manifest['bytes'] if manifest else None)
        except gen.Refused as exc:
            raise Refused('REFUSED', f'seed: {exc}') from exc
        ssh_port, qmp_port = allocate_ports(2)
    else:
        listener_ports = netprobe.start(idir)       # holds its ports before ours are chosen
        ssh_port, qmp_port = allocate_ports(2)
        script_path = netprobe_script_path(ctx.profile_path)
        params = netprobe_params({'ssh': ssh_port, 'qmp': qmp_port}, listener_ports,
                                 *netprobe_host_addresses(), netprobe_debian_addresses())
        script = render_netprobe_script(script_path.read_bytes(), params)
        seed = netprobe_seed(ctx.profile_path, idir, name, idir / 'ssh' / 'id_ed25519.pub', script)
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
    validation = None
    if netprobe is not None:
        argv, validation = netprobe_validation(
            argv, listener_ports, netprobe.pid, posix(script_path.relative_to(ctx.repo)),
            script, seed['validation'], params)
    provisioning = None
    if manifest is not None:
        if seed.get('provision_manifest_sha256') != manifest['sha256']:
            raise Refused('REFUSED', 'seed: the provisioning manifest digest differs')
        provisioning = manifest['record']
    record = build_launch_record(ctx.profile, ctx.profile_path, values, name,
                                 seed['instance_id'], ports, revision, inputs, argv, env,
                                 disk_commands, validation, provisioning)
    write_json_exclusive(idir / 'launch.json', record)
    img_info = qemu_img_info(record, idir)
    launched = launch(ctx, idir, record, 'create')
    result = {'operation': 'create', 'labels': labels(ctx.profile), 'instance': name,
              'instance_id': seed['instance_id'], 'instance_dir': str(idir), 'ports': ports,
              'launch_record_sha256': sha256_file(idir / 'launch.json'),
              'seed_sha256': seed['sha256'], 'disks': disks, 'qemu_img_info': img_info,
              'launch': launched}
    if provisioning is not None:
        result['provisioning'] = provisioning
    if planted:
        result['canaries'] = {'planted_in_environment': planted,
                              'needles': canary_summary(canaries['needles'])}
    if validation is not None:
        result['validation'] = {k: validation[k] for k in ('mode', 'argv_changes', 'guestfwd',
                                                           'listener', 'script', 'seed')}
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
    if record.get('validation'):
        raise Refused('REFUSED', f'{name} is a {record["validation"].get("mode")} validation '
                      'instance: single boot only; destroy it')
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


def remove_tree(root):
    """shutil.rmtree, clearing the read-only attribute of an entry it cannot delete.

    Git for Windows writes pack files read-only (the exchange's verification
    repositories live in the instance directory), and Windows refuses to delete a
    read-only file. Only entries inside root are touched, and never through a link
    (destroy has already refused any link inside root).
    """
    def retry(func, path, exc):
        exc = exc[1] if isinstance(exc, tuple) else exc
        if not isinstance(exc, PermissionError) or not inside(path, root) or \
                os.path.islink(path) or not os.path.lexists(path):
            raise exc
        os.chmod(path, stat.S_IWRITE)
        func(path)
    if sys.version_info >= (3, 12):
        shutil.rmtree(root, onexc=retry)
    else:
        shutil.rmtree(root, onerror=retry)


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
    remove_tree(idir)
    result['result'] = 'destroyed' if not os.path.lexists(idir) else 'incomplete'
    if result['result'] != 'destroyed':
        raise Refused('DESTROY_FAILED', f'{idir} still exists', result)
    return result


def recreate(ctx, name, ready_timeout=READY_TIMEOUT_S, canaries=None, provision=False):
    """destroy, then create with the same name and profile (with --provision, the new
    instance carries the provisioning manifest again; the provision operation follows)."""
    destroyed = destroy(ctx, name)
    created = create(ctx, name, ready_timeout, canaries, provision=True) if provision \
        else create(ctx, name, ready_timeout, canaries)
    return {'operation': 'recreate', 'labels': labels(ctx.profile), 'instance': name,
            'destroy': destroyed, 'create': created}


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


def source_matches(pattern, source):
    """A declared mount source: literal, or with '*' standing for any run of characters
    other than '/' (for example nsfs[net:[*]], whose namespace inode varies)."""
    if not isinstance(pattern, str) or not isinstance(source, str):
        return pattern == source
    if '*' not in pattern:
        return pattern == source
    return bool(re.fullmatch(re.escape(pattern).replace(r'\*', '[^/]*'), source))


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
            elif not source_matches(entry.get('source'), mount['source']):
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


def declared_directories(storage, provisioned=False):
    """guest_storage.directories that apply to an instance: those marked provisioned_only
    (F-04.1, Moby's data root and the root step's state) only on a provisioned one."""
    return [d for d in (storage or {}).get('directories') or []
            if provisioned or not d.get('provisioned_only')]


def storage_probes(storage, provisioned=False):
    """Probes for the declared directories and forbidden paths (guest_storage)."""
    storage = storage or {}
    dirs = ' '.join(f"'{d['path']}'" for d in declared_directories(storage, provisioned))
    forbidden = ' '.join(f"'{p}'" for p in storage.get('forbidden_paths') or [])
    return [
        ('storage_dirs', f"stat -c '%n|%U|%G|%a|%F|%m' -- {dirs}" if dirs else 'echo none'),
        ('forbidden_paths', f'for p in {forbidden}; do if [ -e "$p" ] || [ -L "$p" ]; then '
                            'echo "present $p"; else echo "absent $p"; fi; done' if forbidden
         else 'echo none'),
    ]


def guest_probes(ports, host_ips, http_ip, storage=None, provisioning=None):
    """(name, bash snippet) pairs: read-only inspection and egress probes. ``provisioning``
    (the profile's provisioning block, for a provisioned instance only) adds the Moby
    probes, all run as agent (provisioning_probes)."""
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
    ] + storage_probes(storage, provisioning is not None) + [
        ('findmnt', 'findmnt -J -o TARGET,SOURCE,FSTYPE,OPTIONS'),
        ('findmnt_shares', f'findmnt -n -t {SHARE_FSTYPES}; echo "count=$(findmnt -n -t '
                           f'{SHARE_FSTYPES} | wc -l)"'),
        ('mnt_c', 'test -e /mnt/c && echo present || echo absent'),
        ('cpu_vmx_svm', "grep -c -E 'vmx|svm' /proc/cpuinfo"),
        ('cpu_model', "grep -m1 '^model name' /proc/cpuinfo; grep -c '^processor' /proc/cpuinfo"),
        ('cpu_flags', "grep -m1 '^flags' /proc/cpuinfo"),
        # README open item 3 (F-03.4): the kernel's XSAVE messages, as far as agent may
        # read the kernel log; the host-side serial log is the decisive source
        ('kernel_log', "if dmesg >/dev/null 2>&1; then echo 'dmesg readable'; "
                       "dmesg | grep -E 'x86/fpu|XSAVE|xstate'; else echo 'dmesg unreadable'; fi; "
                       'echo "dmesg_restrict=$(cat /proc/sys/kernel/dmesg_restrict 2>&1)"'),
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
    if provisioning is not None:
        probes += provisioning_probes(provisioning)
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
    validation_mounts = []
    if mounts and (record.get('validation') or {}).get('mode') == 'netprobe':
        validation_mounts = [m for m in mounts if netprobe_mount(m)]
        mounts = [m for m in mounts if not netprobe_mount(m)]
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
        check('mount table equals the declared allowlist', 'profile guest_storage.mounts' +
              (' (the netprobe namespace mounts excluded)' if validation_mounts else ''),
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
    dirs = declared_directories(storage, bool(record.get('provisioning')))
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
    validation = record.get('validation') or {}
    want_chardevs = sorted(['qmp', 'serial0'] + (
        [(validation.get('guestfwd') or {}).get('chardev')]
        if validation.get('mode') == 'netprobe' else []))
    virtio = parse_virtio(out_text('virtio_devices'))
    channels = sorted(k for k in (virtio or {}) if k in ('console', 'vsock', '9p', 'fs')
                      or k.startswith('id-'))
    vsock = dict(line.split(' ', 1) for line in out_text('vsock').splitlines() if ' ' in line)
    sockets = listed_until_end(out_text('socket_inventory'))
    listening = [line.split()[4] for line in out_text('unix_sockets').splitlines()
                 if len(line.split()) > 4]
    # profiles P6 (amended 2026-11-06): a provisioned instance's own Moby sockets are
    # declared (provisioning.moby.sockets) and checked by moby_p6_checks; nothing else
    own = guest_moby_socket_paths(profile, record)
    mgmt_sockets = sorted({s for s in (sockets or []) + listening if MGMT_SOCKET_NAMES.search(s)
                           and s not in own})
    present = listed_until_end(out_text('mgmt_paths'))
    if present is not None:
        present = [line for line in present if line.split(' ', 1)[-1] not in own]
    env = out_text('mgmt_env').splitlines()
    want_env = [f'{scope} {v}=unset' for scope in ('session', 'login') for v in MGMT_ENV]
    qmp_probes = {k: v for k, v in g.items() if k.startswith('egress_tcp_') and k.endswith('_qmp')}
    agent = out_text('guest_ssh_agent')
    return [
        check('chardevs', want_chardevs, chardevs, 'QMP query-chardev', chardevs == want_chardevs),
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
    ] + (moby_p6_checks(profile, obs) if record.get('provisioning') else [])


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
    validation = record.get('validation') or {}
    netprobe_mode = validation.get('mode') == 'netprobe'
    ip6_nonlo = [line for iface, line in ipv6_address_lines(ip6) if '::1/128' not in line
                 and not (netprobe_mode and (f'inet6 {NETPROBE_V6_ADDR}/' in line or
                                             iface.startswith(NETPROBE_IFACE_PREFIX)))]
    rules = forwarding_rules(record.get('argv') or [])
    declared_rules = [(validation.get('guestfwd') or {}).get('rule')] if netprobe_mode else []
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
        check('guest IPv6 addresses beyond ::1', [], ip6_nonlo,
              'guest: ip -6 addr' + (f' ({NETPROBE_V6_ADDR} and the {NETPROBE_IFACE_PREFIX}* '
                                     'namespace interfaces, added by the netprobe root, excluded)'
                                     if netprobe_mode else ''), not ip6_nonlo),
        check('guest forwarding rules', declared_rules, rules, 'launch record argv (guestfwd=)',
              rules == declared_rules),
    ] + (netprobe_checks(record, obs.get('netprobe')) if netprobe_mode
         else [enforcement_check(profile)]) +
        (moby_p7_checks(obs) if record.get('provisioning') else []),
        formal='F-03.3.2; S-02.1, S-02.2',
        note=('Validation instance: the netprobe checks are the F-03.3.2 test (guest root, '
              'routes, every denied path, both positive controls, decoys).' if netprobe_mode
              else 'Ordinary instance: unprivileged probes; guest-root denial is shown by the '
                   'netprobe validation (F-03.3.2), cited through the enforcement point.')))

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
    ] + (moby_p8_checks(obs) if record.get('provisioning') else []), note='Uniqueness across instances is compared outside a single inspect record.'))

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

    artifacts = obs.get('artifacts')
    props.append(prop('P11', [
        check('labels', labels(profile), record.get('labels'),
              'launch record', record.get('labels') == labels(profile)),
        check('artifact labels', 'every record and log header carries the profile labels',
              artifacts, 'instance directory: launch.json, process.json, records/*.json, '
              'stderr.log headers (label_problems)',
              None if not artifacts else artifacts_clean(artifacts)),
    ]))

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
    if record.get('provisioning'):
        props.append(provisioning_property(profile, record, obs))
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
    probes = guest_probes(record['ports'], ips, http_ip, ctx.profile.get('guest_storage'),
                          provisioning_config(ctx.profile) if record.get('provisioning') else None)
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
    obs['artifacts'] = artifact_labels(idir, labels(ctx.profile))
    if record.get('validation'):
        obs['netprobe'] = latest_record(idir, 'netprobe')
    properties = evaluate(ctx.profile, record, obs)
    serial = idir / 'serial.log'
    compatibility = {'xsave': xsave_findings({
        'serial.log (host side)': serial.read_text(encoding='utf-8', errors='replace')
        if serial.is_file() else None,
        'guest dmesg (as agent)': guest_kernel_log((obs['guest'].get('kernel_log') or {}).get('out'))})}
    compatibility['verdict'] = compatibility['xsave']['verdict']
    out = {'schema': INSPECT_SCHEMA, 'operation': 'inspect', 'labels': labels(ctx.profile),
           'instance': name, 'instance_id': record['instance']['instance_id'],
           'launch_record_sha256': sha256_file(idir / 'launch.json'), 'pid': pid,
           'inspected_at': utc_now(), 'seconds': round(time.time() - t0, 1),
           'verdicts': {p['property']: p['verdict'] for p in properties},
           'compatibility': compatibility,
           'properties': properties, 'observations': obs}
    out['record'] = write_record(idir, 'inspect', out)
    return out


SURFACE_PROPERTIES = ('profiles P3', 'profiles P4', 'profiles P5', 'profiles P6')


def check_surfaces(ctx, name, canary_dir):
    """The startup inspection test (F-03.3.1): inspect with a canary set, then the verdict
    for profiles P3 to P6. PASS only when all four PASS; UNKNOWN counts as not passed."""
    canaries = load_canaries(canary_dir)
    record = inspect(ctx, name, canaries)
    verdicts, failing, result = surface_verdict(record)
    return {'operation': 'check-surfaces', 'labels': labels(ctx.profile), 'instance': name,
            'canaries': canary_summary(canaries['needles']), 'verdicts': verdicts,
            'not_passed': failing, 'inspect_record': record['record'],
            'all_verdicts': record['verdicts'], 'result': result}


def surface_verdict(record):
    """(verdicts, checks not passed, 'PASS'|'FAIL') for profiles P3 to P6 of one inspect
    record; UNKNOWN counts as not passed."""
    verdicts = {p: record['verdicts'].get(p) for p in SURFACE_PROPERTIES}
    failing = [{'property': p['property'], 'check': c['check'], 'verdict': c['verdict']}
               for p in record['properties'] if p['property'] in SURFACE_PROPERTIES
               for c in p['checks'] if c['verdict'] != 'PASS']
    return verdicts, failing, 'PASS' if all(v == 'PASS' for v in verdicts.values()) else 'FAIL'


# ---------------------------------------------------------------- P11 over the artifacts (F-03.4)


def artifact_labels(instance_dir, want):
    """profiles P11 over what guest.py wrote in one instance directory: for launch.json,
    process.json, every records/*.json and every stderr.log header, the labels it
    carries and their problems (label_problems against the profile's labels).

    Not covered, because they are not records: the SSH key and known_hosts, the disks,
    seed.iso, and serial.log (the guest console, written by QEMU from the first byte;
    a header would need a change to launch.argv)."""
    idir = Path(instance_dir)
    out = {}
    records = idir / 'records'
    paths = [idir / 'launch.json', idir / 'process.json'] + \
        (sorted(records.glob('*.json')) if records.is_dir() else [])
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            lab = data.get('labels') if isinstance(data, dict) else None
        except (OSError, ValueError):
            lab = None
        out[posix(path.relative_to(idir))] = {'labels': lab, 'problems': label_problems(lab, want)}
    if (idir / 'stderr.log').is_file():
        err = stderr_findings(idir)
        if not err['first_line_is_header']:
            out['stderr.log'] = {'labels': None, 'problems': ['the log does not start with a header']}
        for i, header in enumerate(err['headers'], 1):
            lab = header.get('labels') if isinstance(header, dict) else None
            out[f'stderr.log#header{i}'] = {'labels': lab, 'problems': label_problems(lab, want)}
    return out


def artifacts_clean(artifacts):
    return bool(artifacts) and all(not a['problems'] for a in artifacts.values())


# ---------------------------------------------------------------- XSAVE detector (README open item 3)

# The guest kernel's XSAVE messages under WHPX with -cpu max. A consistency problem or
# a disabled XSAVE is a FAIL; the misordered-offset warning, observed on the
# qualification host, is a recorded limitation (decision 0003, "Current facts").
XSAVE_PATTERNS = (
    ('misordered-xstate', re.compile(r'x86/fpu: misordered xstate'), 'LIMITATION'),
    ('xsave-consistency-problem', re.compile(r'XSAVE consistency problem'), 'FAIL'),
    ('xsave-disabled', re.compile(r'XSAVE disabled'), 'FAIL'),
)
XSAVE_KERNEL_LINE = re.compile(r'x86/fpu: ')
XSAVE_ENABLED = re.compile(r'x86/fpu: Enabled xstate features .*')


def guest_kernel_log(probe_out):
    """The kernel_log probe's dmesg lines, or None when agent may not read the log."""
    lines = (probe_out or '').replace('\r', '').split('\n')
    if lines[0].strip() != 'dmesg readable':
        return None
    return '\n'.join(line for line in lines[1:] if not line.startswith('dmesg_restrict='))


def xsave_findings(sources):
    """{source: text or None} -> the labelled XSAVE findings and their verdict.

    PASS needs at least one source that holds the kernel's x86/fpu messages; without one
    the verdict is UNKNOWN (a console that never reached the serial log proves nothing)."""
    findings, enabled, read = [], [], {}
    for source, text in sources.items():
        if text is None:
            read[source] = 'unavailable'
            continue
        lines = text.replace('\r', '').split('\n')
        read[source] = 'kernel messages' if any(XSAVE_KERNEL_LINE.search(line) for line in lines) \
            else 'no kernel x86/fpu messages'
        for line in lines:
            for label, regex, severity in XSAVE_PATTERNS:
                if regex.search(line):
                    findings.append({'label': label, 'severity': severity, 'source': source,
                                     'line': line.strip()[:300]})
            match = XSAVE_ENABLED.search(line)
            if match:
                enabled.append({'source': source, 'line': match.group(0).strip()[:300]})
    severities = {f['severity'] for f in findings}
    verdict = 'FAIL' if 'FAIL' in severities else 'LIMITATION' if 'LIMITATION' in severities \
        else 'PASS' if 'kernel messages' in read.values() else 'UNKNOWN'
    return {'verdict': verdict, 'labels': sorted({f['label'] for f in findings}),
            'findings': findings, 'xstate_enabled': enabled, 'sources': read,
            'rule': 'XSAVE consistency problem or XSAVE disabled: FAIL; misordered xstate: '
                    'LIMITATION (recorded, README open item 3)'}


# ---------------------------------------------------------------- inspect comparison (P10)

def _n_addresses(value, profile):
    return sorted(str(x[0]) for x in value) if isinstance(value, list) else value


def _n_refusals(value, profile):
    return sorted({(k.rsplit(':', 1)[0], r) for k, r in value.items()}) \
        if isinstance(value, dict) else value


def _n_blocked(value, profile):
    return {k: probe_blocked(k, {'rc': rc}) for k, rc in value.items()} \
        if isinstance(value, dict) else value


def _n_mount_diff(value, profile):
    return {k: value.get(k) for k in ('unlisted', 'missing')} if isinstance(value, dict) else value


def _n_fstypes(value, profile):
    mounts = (profile.get('guest_storage') or {}).get('mounts') or []
    required = {m['fstype'] for m in mounts if not m.get('optional')}
    optional_only = {m['fstype'] for m in mounts if m.get('optional')} - required
    return [t for t in value if t not in optional_only] if isinstance(value, list) else value


def _n_socket_matches(value, profile):
    return value.get('matched') if isinstance(value, dict) else value


def _n_artifact_labels(value, profile):
    if not isinstance(value, dict):
        return value
    return {'labels': sorted({json.dumps(a.get('labels'), sort_keys=True) for a in value.values()}),
            'problems': sorted({p for a in value.values() for p in a.get('problems') or []})}


NORMALIZERS = {'addresses': _n_addresses, 'refusals': _n_refusals, 'blocked': _n_blocked,
               'mount-diff': _n_mount_diff, 'fstypes': _n_fstypes,
               'socket-matches': _n_socket_matches, 'artifact-labels': _n_artifact_labels}

# Every check of an ordinary inspect record, classified for the comparison across a
# restart (start) and across recreate (contract section 3: recreate "must match the
# previous inspect record, except for identity"):
#   stable        declared and observed equal (after the named normalisation, which
#                 drops what is allocated per launch, such as ports, or what varies with
#                 running services, such as optional mounts)
#   per-instance  the identity of one instance (profiles P8): equal across start,
#                 different across recreate
#   volatile      recorded, not compared (content that grows while a guest runs)
# Every check's verdict must be equal in both records; an unclassified check fails.
STABLE, PER_INSTANCE, VOLATILE = 'stable', 'per-instance', 'volatile'
CHECK_CLASSES = {
    ('profiles P1', 'accelerator'): (STABLE, None),
    ('profiles P1', 'guest kernel'): (STABLE, None),
    ('profiles P1', 'host kernel'): (STABLE, None),
    ('profiles P1', 'vm status'): (STABLE, None),
    ('profiles P2', 'vcpu (QMP)'): (STABLE, None),
    ('profiles P2', 'vcpu (guest)'): (STABLE, None),
    ('profiles P2', 'memory (QMP)'): (STABLE, None),
    # the kernel's MemTotal moves by a page or so between fresh boots (observed in F-03.4:
    # 16382796 then 16382792 kB across recreate); the exact ceiling is 'memory (QMP)',
    # and the 85-100 % band is this check's verdict, which must stay equal
    ('profiles P2', 'memory (guest MemTotal kB)'): (VOLATILE, None),
    ('profiles P2', 'root disk (guest)'): (STABLE, None),
    ('profiles P2', 'scratch disk (guest)'): (STABLE, None),
    ('profiles P2', 'root disk (qemu-img)'): (STABLE, None),
    ('profiles P2', 'scratch disk (qemu-img)'): (STABLE, None),
    ('profiles P3', 'share mounts'): (STABLE, None),
    ('profiles P3', 'mount table file systems'): (STABLE, 'fstypes'),
    ('profiles P3', 'mount table equals the declared allowlist'): (STABLE, 'mount-diff'),
    ('profiles P3', 'forbidden paths'): (STABLE, None),
    ('profiles P3', '/mnt/c'): (STABLE, None),
    ('profiles P3', 'guest virtio devices'): (STABLE, None),
    ('profiles P3', 'host shares declared'): (STABLE, None),
    ('profiles P4', 'block devices (QMP)'): (STABLE, None),
    ('profiles P4', 'block nodes: names, read-only flags and files'): (STABLE, None),
    ('profiles P4', 'guest disks'): (STABLE, None),
    ('profiles P4', 'pci virtio devices'): (STABLE, None),
    ('profiles P4', 'pci devices outside virtio and the q35 chipset'): (STABLE, None),
    ('profiles P4', 'seed read-only in the guest'): (STABLE, None),
    ('profiles P4', 'scratch mounted'): (STABLE, None),
    ('profiles P4', 'exchange and scratch directories'): (STABLE, None),
    ('profiles P5', 'launch environment'): (STABLE, None),
    ('profiles P5', 'collection'): (VOLATILE, None),
    ('profiles P5', 'positive control'): (STABLE, None),
    ('profiles P5', 'Owner-class scan'): (STABLE, None),
    ('profiles P5', 'canaries'): (STABLE, None),
    ('profiles P5', 'per-instance private key'): (STABLE, None),
    ('profiles P6', 'chardevs'): (STABLE, None),
    ('profiles P6', 'virtio-serial ports'): (STABLE, None),
    ('profiles P6', 'virtio channel devices'): (STABLE, None),
    ('profiles P6', 'vsock'): (STABLE, None),
    ('profiles P6', 'host-management paths'): (STABLE, None),
    ('profiles P6', 'socket inventory'): (STABLE, 'socket-matches'),
    ('profiles P6', 'management environment'): (STABLE, None),
    ('profiles P6', '/tmp/.X11-unix'): (STABLE, None),
    ('profiles P6', 'QMP from the guest'): (STABLE, 'blocked'),
    ('profiles P6', 'guest-local ssh-agent'): (STABLE, None),
    ('profiles P6', 'guest agent'): (STABLE, None),
    ('profiles P7', 'netdev'): (STABLE, None),
    ('profiles P7', 'QEMU listening sockets'): (STABLE, 'addresses'),
    ('profiles P7', 'QEMU UDP endpoints on non-loopback addresses'): (STABLE, None),
    ('profiles P7', 'host non-loopback addresses on the forwarded ports'): (STABLE, 'refusals'),
    ('profiles P7', 'positive controls in the guest'): (STABLE, None),
    ('profiles P7', 'guest egress probes'): (STABLE, 'blocked'),
    ('profiles P7', 'guest IPv6 addresses beyond ::1'): (STABLE, None),
    ('profiles P7', 'guest forwarding rules'): (STABLE, None),
    ('profiles P7', 'enforcement point qualified'): (STABLE, None),
    ('profiles P8', 'machine-id'): (PER_INSTANCE, None),
    ('profiles P8', 'hostname'): (STABLE, None),
    ('profiles P8', 'cloud-init instance id'): (PER_INSTANCE, None),
    ('profiles P8', 'agent groups'): (STABLE, None),
    ('profiles P8', 'sudo'): (STABLE, None),
    ('profiles P8', 'root ssh login'): (STABLE, None),
    ('profiles P8', 'sshd drop-in'): (STABLE, None),
    ('profiles P8', 'host keys'): (PER_INSTANCE, None),
    ('profiles P8', 'host principal'): (STABLE, None),
    ('profiles P9', 'launch-record inputs re-hashed'): (STABLE, None),
    ('profiles P9', 'pinned inputs'): (STABLE, None),
    ('profiles P9', 'seed digest recorded'): (PER_INSTANCE, None),
    ('profiles P9', 'profile revision'): (STABLE, None),
    ('profiles P9', 'root overlay backing'): (STABLE, None),
    ('profiles P10', 'disposability'): (STABLE, None),
    ('profiles P11', 'labels'): (STABLE, None),
    ('profiles P11', 'artifact labels'): (STABLE, 'artifact-labels'),
    ('profiles P12', 'declared'): (STABLE, None),
    ('profiles P12', 'QOM vmx/svm'): (STABLE, None),
    ('profiles P12', 'guest cpuinfo vmx|svm count'): (STABLE, None),
    ('profiles P12', '/dev/kvm'): (STABLE, None),
}


def _guest_out(record, key):
    return (((record.get('observations') or {}).get('guest') or {}).get(key) or {}).get('out')


def _input_digest(record, key):
    return (((record.get('observations') or {}).get('input_digests') or {}).get(key) or {}).get('sha256')


# Record-level fields outside the checks, with their class.
INSPECT_FACTS = (
    ('instance id', PER_INSTANCE, lambda r: r.get('instance_id')),
    ('launch record sha256', PER_INSTANCE, lambda r: r.get('launch_record_sha256')),
    ('ssh public key sha256', PER_INSTANCE, lambda r: _input_digest(r, 'ssh_public_key')),
    ('seed sha256', PER_INSTANCE, lambda r: _input_digest(r, 'seed')),
    ('labels', STABLE, lambda r: r.get('labels')),
    ('property verdicts', STABLE, lambda r: r.get('verdicts')),
    ('xsave findings', STABLE,
     lambda r: ((r.get('compatibility') or {}).get('xsave') or {}).get('labels')),
    ('xsave verdict', STABLE, lambda r: (r.get('compatibility') or {}).get('verdict')),
    ('qemu version', STABLE,
     lambda r: ((r.get('observations') or {}).get('qmp') or {}).get('query-version')),
    ('guest cpu flags', STABLE, lambda r: _guest_out(r, 'cpu_flags')),
    ('guest cpu model', STABLE, lambda r: _guest_out(r, 'cpu_model')),
    ('guest kernel command line', STABLE, lambda r: _guest_out(r, 'kernel_cmdline')),
    ('guest addresses', STABLE, lambda r: _guest_out(r, 'ip_addr')),
    ('guest routes', STABLE, lambda r: _guest_out(r, 'ip_route')),
    ('qemu process id', VOLATILE, lambda r: r.get('pid')),
    ('inspected at', VOLATILE, lambda r: r.get('inspected_at')),
    ('inspect seconds', VOLATILE, lambda r: r.get('seconds')),
)


def compare_inspect(profile, before, after, mode):
    """Compare two inspect records of one instance name. mode 'start': the same instance
    after a stop and start (per-instance fields equal); mode 'recreate': a new instance
    under the same name (per-instance fields differ). Returns the per-field table and
    PASS or FAIL."""
    if mode not in ('start', 'recreate'):
        raise ValueError(mode)

    def index(record):
        return {(p['property'], c['check']): c for p in record.get('properties') or []
                for c in p['checks']}

    def per_instance_ok(a, b):
        return a == b if mode == 'start' else (a is not None and b is not None and a != b)

    a_checks, b_checks = index(before), index(after)
    fields = []
    for key in sorted(set(a_checks) | set(b_checks)):
        entry = {'field': f'{key[0]} / {key[1]}', 'kind': 'check'}
        cls = CHECK_CLASSES.get(key)
        ca, cb = a_checks.get(key), b_checks.get(key)
        if cls is None or ca is None or cb is None:
            entry.update({'class': cls[0] if cls else None, 'ok': False,
                          'reason': 'unclassified check' if cls is None else 'missing in one record'})
            fields.append(entry)
            continue
        klass, norm = cls
        f = NORMALIZERS[norm] if norm else (lambda v, p: v)
        va, vb = f(ca['observed'], profile), f(cb['observed'], profile)
        ok = ca['verdict'] == cb['verdict']
        if klass == STABLE:
            ok = ok and va == vb and f(ca['declared'], profile) == f(cb['declared'], profile)
        elif klass == PER_INSTANCE:
            ok = ok and per_instance_ok(va, vb)
        entry.update({'class': klass, 'normalised': norm, 'verdicts': [ca['verdict'], cb['verdict']],
                      'before': va, 'after': vb, 'ok': ok})
        fields.append(entry)
    for name, klass, get in INSPECT_FACTS:
        va, vb = get(before), get(after)
        ok = va == vb if klass == STABLE else per_instance_ok(va, vb) if klass == PER_INSTANCE \
            else True
        fields.append({'field': name, 'kind': 'record', 'class': klass, 'before': va,
                       'after': vb, 'ok': ok})
    counts = {}
    for entry in fields:
        counts[str(entry.get('class'))] = counts.get(str(entry.get('class')), 0) + 1
    bad = [e['field'] for e in fields if not e['ok']]
    return {'mode': mode, 'result': 'FAIL' if bad else 'PASS', 'not_ok': bad,
            'counts': counts, 'fields': fields}


# ---------------------------------------------------------------- inventory of durable sources (P10)

# Files a running QEMU writes in its own instance directory: a running sibling's copies
# are recorded as present, not hashed.
VOLATILE_WHILE_RUNNING = ('root.qcow2', 'scratch.qcow2', 'serial.log', 'stderr.log')


def is_link(entry):
    return entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction())


def tree_inventory(root, volatile=()):
    """Every entry under root, never through a link: type, mode, Windows attributes and
    mtime; each file with its size and sha256. Top-level names in ``volatile`` are
    recorded as present only."""
    root = Path(root)
    st = os.stat(root, follow_symlinks=False)
    out = {'.': {'type': 'dir', 'mode': st.st_mode, 'mtime_ns': st.st_mtime_ns,
                 'attributes': getattr(st, 'st_file_attributes', None)}}
    stack = ['']
    while stack:
        rel_dir = stack.pop()
        with os.scandir(root / rel_dir if rel_dir else root) as entries:
            for entry in entries:
                rel = f'{rel_dir}/{entry.name}' if rel_dir else entry.name
                # os.lstat, not entry.stat: on Windows the directory listing's copy of a
                # child directory's times is updated lazily and can lag the entry itself
                st = os.lstat(entry.path)
                info = {'mode': st.st_mode, 'attributes': getattr(st, 'st_file_attributes', None)}
                if is_link(entry):
                    info['type'] = 'link'
                elif entry.is_dir(follow_symlinks=False):
                    info.update(type='dir', mtime_ns=st.st_mtime_ns)
                    stack.append(rel)
                elif entry.is_file(follow_symlinks=False):
                    if not rel_dir and entry.name in volatile:
                        info = {'type': 'file', 'volatile': 'written by the running QEMU'}
                    else:
                        info.update(type='file', size=st.st_size, mtime_ns=st.st_mtime_ns,
                                    sha256=sha256_file(entry.path))
                else:
                    info['type'] = 'other'
                out[rel] = info
    return dict(sorted(out.items()))


def repo_inventory(repo):
    """The checkout: HEAD, tracked-file status and the index listing's digest (git with no
    global configuration, so the run's environment cannot change what it reports)."""
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args):
        return subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                              check=False, env=env, timeout=300)
    head, status, files = git('rev-parse', 'HEAD'), \
        git('status', '--porcelain=v2', '--untracked-files=no'), git('ls-files', '-s')
    return {'path': posix(repo), 'head': head.stdout.decode().strip(),
            'status_porcelain_v2': status.stdout.decode('utf-8', 'replace').splitlines(),
            'ls_files_s_sha256': hashlib.sha256(files.stdout).hexdigest(),
            'ls_files_count': len(files.stdout.splitlines()),
            'rc': [head.returncode, status.returncode, files.returncode]}


def state_inventory(ctx):
    """The state directory's shared, non-instance content the profile names: the pinned
    image, and the provider prefix (file count, bytes, a digest of every file's path,
    size and mtime, and the sha256 of the pinned binaries and firmware)."""
    image = Path(ctx.values['input:image'])
    st = image.stat()
    prefix = Path(ctx.values['qemu_prefix'])
    lines, count, total, stack = [], 0, 0, [prefix]
    while stack:
        with os.scandir(stack.pop()) as entries:
            for entry in entries:
                if is_link(entry):
                    lines.append(f'{posix(Path(entry.path).relative_to(prefix))}\tlink')
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                else:
                    est = entry.stat(follow_symlinks=False)
                    count, total = count + 1, total + est.st_size
                    lines.append(f'{posix(Path(entry.path).relative_to(prefix))}\t'
                                 f'{est.st_size}\t{est.st_mtime_ns}')
    listing = '\n'.join(sorted(lines)).encode('utf-8')
    return {'image': {'path': posix(image), 'sha256': sha256_file(image), 'size': st.st_size,
                      'mtime_ns': st.st_mtime_ns},
            'provider': {'path': posix(prefix), 'files': count, 'bytes': total,
                         'listing_sha256': hashlib.sha256(listing).hexdigest(),
                         'binaries': {k: sha256_file(v['path'])
                                      for k, v in sorted(binaries(ctx.profile, ctx.values).items())},
                         'firmware': sha256_file(ctx.values['input:firmware'])}}


def sibling_state(path):
    """Whether a sibling directory is an instance, whether its QEMU runs, and its QMP status."""
    try:
        record = read_launch_record(path)
    except Refused:
        return {'instance': False}
    proc = running_process(path, record['binary'])
    if not proc:
        return {'instance': True, 'running': False}
    pid = proc.pid
    proc.close()
    status = qmp_try(record['ports']['qmp'], 'query-status')
    return {'instance': True, 'running': True, 'pid': pid,
            'qmp_status': (status.get('return') or {}).get('status'), 'qmp_error': status.get('error')}


def instances_inventory(ctx, subject):
    """Every entry of the state directory's instances/ except the subject instance."""
    instances = Path(ctx.state_dir) / 'instances'
    out = {}
    if not instances.is_dir():
        return out
    with os.scandir(instances) as entries:
        for entry in sorted(entries, key=lambda e: e.name):
            if entry.name == subject:
                continue
            if is_link(entry):
                out[entry.name] = {'type': 'link'}
            elif entry.is_dir(follow_symlinks=False):
                state = sibling_state(Path(entry.path))
                out[entry.name] = {'type': 'dir', 'state': state, 'tree': tree_inventory(
                    entry.path, VOLATILE_WHILE_RUNNING if state.get('running') else ())}
            else:
                st = entry.stat(follow_symlinks=False)
                out[entry.name] = {'type': 'file', 'size': st.st_size, 'mtime_ns': st.st_mtime_ns,
                                   'sha256': sha256_file(entry.path)}
    return out


def inventory(ctx, subject, durable_roots):
    """The durable sources a destroy or recreate of ``subject`` must leave untouched."""
    return {'taken_at': utc_now(), 'repository': repo_inventory(ctx.repo),
            'state_shared': state_inventory(ctx),
            'instances': instances_inventory(ctx, subject),
            'durable_roots': {posix(r): tree_inventory(r) for r in durable_roots}}


def _short(value):
    text = json.dumps(value, sort_keys=True, default=str)
    return value if len(text) <= 300 else text[:300] + '...'


def diff_inventory(a, b, path=''):
    """Every difference between two inventories (taken_at excluded), as path entries."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b), key=str):
            if not path and key == 'taken_at':
                continue
            sub = f'{path}/{key}' if path else str(key)
            if key not in a:
                out.append({'path': sub, 'change': 'added', 'after': _short(b[key])})
            elif key not in b:
                out.append({'path': sub, 'change': 'removed', 'before': _short(a[key])})
            else:
                out += diff_inventory(a[key], b[key], sub)
        return out
    return [] if a == b else [{'path': path, 'change': 'changed', 'before': _short(a),
                               'after': _short(b)}]


# ---------------------------------------------------------------- smoke (F-03.4)


def inspect_ok(record):
    """An inspect record fit for the smoke test: every property PASS except P10 (proved by
    the smoke test itself, UNKNOWN in inspect), P3 to P6 PASS, and no XSAVE FAIL."""
    verdicts = record['verdicts']
    surfaces = surface_verdict(record)
    bad = {p: v for p, v in verdicts.items()
           if v != ('UNKNOWN' if p == 'profiles P10' else 'PASS')}
    compat = (record.get('compatibility') or {}).get('verdict')
    ok = not bad and surfaces[2] == 'PASS' and compat in ('PASS', 'LIMITATION')
    return ok, {'verdicts': verdicts, 'not_as_expected': bad, 'surfaces': surfaces[2],
                'surfaces_not_passed': surfaces[1], 'compatibility': compat,
                'xsave_labels': ((record.get('compatibility') or {}).get('xsave') or {}).get('labels'),
                'instance_id': record.get('instance_id'), 'pid': record.get('pid'),
                'seconds': record.get('seconds')}


def smoke(ctx, name, canary_dir, durable_roots, out_path=None, ready_timeout=READY_TIMEOUT_S,
          with_provision=False):
    """The F-03.4 provision/inspect/teardown smoke test on a fresh instance name: preflight,
    create, inspect (check-surfaces), graceful stop, start, inspect, forced stop, recreate,
    inspect, destroy, destroy again (absent), with inventories of the durable sources
    before and after each destroy and recreate. One machine verdict: PASS or FAIL.
    ``with_provision`` (F-04.1) creates and recreates with --provision and runs the
    provision operation after each, before the inspect."""
    idir = ctx.instance_dir(name)
    if os.path.lexists(idir):
        raise Refused('REFUSED', f'{idir} exists; the smoke test runs on a fresh instance name')
    if not durable_roots:
        raise Refused('REFUSED', 'name at least one durable root (--durable) to inventory')
    roots = []
    for root in durable_roots:
        path = Path(root).resolve()
        if not path.is_dir():
            raise Refused('REFUSED', f'durable root {root} is not a directory')
        if inside(path, idir) or inside(idir, path):
            raise Refused('REFUSED', f'durable root {root} overlaps the instance directory')
        roots.append(path)
    out_file = None
    if out_path:
        out_file = Path(out_path).resolve()
        if os.path.lexists(out_file) or not out_file.parent.is_dir() or \
                inside(out_file, ctx.repo) or inside(out_file, idir):
            raise Refused('REFUSED', f'--out {out_path}: must be a new file in an existing '
                          'directory, outside the checkout and the instance directory')
    canaries = load_canaries(canary_dir)
    t0, started = time.time(), utc_now()
    steps, failed, inspects, comparisons, inventories = [], [], {}, {}, {}
    caught = (Refused, OSError, ValueError, QmpError, subprocess.SubprocessError)

    def run(step, func, judge, always=False):
        if failed and not always:
            steps.append({'step': step, 'skipped': 'an earlier step failed'})
            return None
        s = time.time()
        entry = {'step': step, 'started_at': utc_now()}
        try:
            result = func()
            ok, summary = judge(result)
        except caught as exc:
            result, ok = None, False
            summary = {'error': getattr(exc, 'code', type(exc).__name__), 'message': str(exc),
                       'detail': getattr(exc, 'detail', None)}
        entry.update(seconds=round(time.time() - s, 1), ok=ok, summary=summary)
        steps.append(entry)
        log(f'smoke: {step}: {"ok" if ok else "FAILED"} ({entry["seconds"]} s)')
        if not ok:
            failed.append(step)
        return result

    def take(label, always=False):
        inv = run(f'inventory {label}', lambda: inventory(ctx, name, roots),
                  lambda r: (True, {'instances': {k: (v.get('state') or {}).get('running')
                                                  for k, v in r['instances'].items()},
                                    'durable_roots': sorted(r['durable_roots'])}), always)
        if inv is not None:
            inventories[label] = inv

    def do_inspect(label):
        record = run(f'inspect {label}', lambda: inspect(ctx, name, canaries), inspect_ok)
        if record is not None:
            inspects[label] = record

    def compare(label, a, b, mode):
        result = run(f'compare {label}', lambda: compare_inspect(ctx.profile, inspects[a],
                                                                inspects[b], mode),
                     lambda r: (r['result'] == 'PASS', {'not_ok': r['not_ok'], 'counts': r['counts']}))
        if result is not None:
            comparisons[label] = result

    def ready(r):
        return r['result'] == 'ready', {'instance_id': r.get('instance_id'),
                                        'ready': r.get('ready'), 'seconds': r.get('seconds'),
                                        'error': r.get('error')}

    def exited(r, how):
        after = [p.get('exited_after') for p in r.get('phases') or [] if 'exited_after' in p]
        return r['result'] == 'stopped' and bool(after) and after[-1] in how, \
            {'result': r['result'], 'phases': r.get('phases')}

    def destroyed(r):
        return r['result'] == 'destroyed' and not os.path.lexists(idir), \
            {'result': r['result'], 'stop': r.get('stop')}

    run('preflight', lambda: preflight(ctx),
        lambda r: (r['result'] == 'available',
                   {'result': r['result'],
                    'not_ok': [c for c in r['checks'] if c['status'] != 'ok'],
                    'host_xsaves': next((c['detail'] for c in r['checks']
                                         if c['check'] == 'host-xsaves'), None)}))
    take('before create')
    def provisioned(r):
        return r['result'] == 'provisioned', {'checks': r.get('checks'),
                                              'timings': r.get('timings')}

    if with_provision:
        run('create', lambda: create(ctx, name, ready_timeout, canaries, provision=True), ready)
        run('provision', lambda: provision(ctx, name), provisioned)
    else:
        run('create', lambda: create(ctx, name, ready_timeout, canaries), ready)
    do_inspect('A (after create)')
    run('stop (graceful)', lambda: stop(ctx, name), lambda r: exited(r, ('system_powerdown',)))
    run('start', lambda: start(ctx, name, ready_timeout), ready)
    do_inspect('B (after start)')
    compare('A-B (start)', 'A (after create)', 'B (after start)', 'start')
    run('stop (forced)', lambda: stop(ctx, name, force=True),
        lambda r: exited(r, ('quit', 'terminate')))
    take('before recreate')
    run('recreate', lambda: recreate(ctx, name, ready_timeout, canaries, with_provision)
        if with_provision else recreate(ctx, name, ready_timeout, canaries),
        lambda r: (r['destroy']['result'] == 'destroyed' and r['create']['result'] == 'ready',
                   {'destroy': {'result': r['destroy']['result'], 'stop': r['destroy'].get('stop')},
                    'create': ready(r['create'])[1]}))
    take('after recreate')
    if with_provision:
        run('provision (after recreate)', lambda: provision(ctx, name), provisioned)
    do_inspect('C (after recreate)')
    compare('A-C (recreate)', 'A (after create)', 'C (after recreate)', 'recreate')
    run('destroy', lambda: destroy(ctx, name), destroyed)
    run('destroy (absent)', lambda: destroy(ctx, name),
        lambda r: (r['result'] == 'absent', {'result': r['result']}))
    if failed and os.path.lexists(idir):
        cleanup = {'step': 'cleanup destroy'}
        try:
            cleanup['result'] = destroy(ctx, name)['result']
        except caught as exc:
            cleanup['result'] = f'{getattr(exc, "code", type(exc).__name__)}: {exc}'
        steps.append(cleanup)
    take('after destroy', always=True)        # also after a failure and its cleanup
    pairs = [('before create', 'before recreate'), ('before recreate', 'after recreate'),
             ('after recreate', 'after destroy'), ('before create', 'after destroy')]
    diffs = {f'{a} -> {b}': diff_inventory(inventories[a], inventories[b])
             for a, b in pairs if a in inventories and b in inventories}
    if any(diffs.values()):
        failed.append('inventory comparison')
    inventory_ok = len(diffs) == len(pairs) and not any(diffs.values())
    durable_changes = {k: [d for d in v if d['path'].startswith('durable_roots/')]
                       for k, v in diffs.items()}
    destroy_steps = {s['step']: (s.get('summary') or {}).get('result') for s in steps
                     if s.get('step') in ('destroy', 'destroy (absent)')}
    recreate_cmp = comparisons.get('A-C (recreate)', {}).get('result')
    p10 = prop('P10', [
        check('destroy removes the instance directory',
              {'destroy': 'destroyed', 'destroy (absent)': 'absent'}, destroy_steps,
              'smoke: destroy, then destroy again', destroy_steps == {'destroy': 'destroyed',
                                                                     'destroy (absent)': 'absent'}),
        check('destroy and recreate change no durable source', 'no difference',
              {k: len(v) for k, v in diffs.items()},
              'smoke: inventories of the repository, the state directory\'s image and provider, '
              'the other instances/ entries and the durable roots', inventory_ok),
        check('Owner data roots untouched', [posix(r) for r in roots],
              {k: len(v) for k, v in durable_changes.items()}, 'smoke: durable-root inventories',
              inventory_ok and not any(durable_changes.values())),
        check('recreate reproduces the observed state',
              'stable fields equal, per-instance fields different', recreate_cmp,
              'smoke: compare_inspect A-C (recreate)', recreate_cmp == 'PASS'),
    ], formal='F-03.4')
    result = {'schema': SMOKE_SCHEMA, 'operation': 'smoke', 'labels': labels(ctx.profile),
              'profile': ctx.profile['name'], 'instance': name, 'started_at': started,
              'ended_at': utc_now(), 'seconds': round(time.time() - t0, 1),
              'host': {'os': platform.platform(),
                       'processor': os.environ.get('PROCESSOR_IDENTIFIER')},
              'result': 'PASS' if not failed and p10['verdict'] == 'PASS' else 'FAIL',
              'failed_steps': failed, 'p10': p10, 'steps': steps,
              'inspects': {k: dict(inspect_ok(v)[1], properties=v['properties'],
                                   compatibility_detail=v.get('compatibility'))
                           for k, v in inspects.items()},
              'comparisons': comparisons, 'inventory_diffs': diffs, 'inventories': inventories}
    if out_file is not None:
        write_json_exclusive(out_file, json.loads(json.dumps(result, default=str)))
        result['out'] = str(out_file)
    return result


# ---------------------------------------------------------------- netprobe (F-03.3.2, test only)
#
# A validation mode, never ordinary operation (decision 0003, "Owner authorization:
# network validation (2026-11-06)"). `netprobe` creates one disposable guest whose seed
# carries a second user-data part, the pinned test-only probe script (run once as root
# at first boot), and whose -netdev carries one test-only guestfwd to a purpose-built
# listener on 127.0.0.1 at an ephemeral port, beside decoys that are not forwarded.
# The profile's launch.argv, the seed templates and the ordinary create are unchanged;
# launch refuses a guestfwd that no validation record declares, and start refuses a
# validation instance (single boot).

NETPROBE_SCRIPT = ('validation', 'netprobe', 'netprobe.py')    # under the profile directory
NETPROBE_SCRIPT_SHA256 = '76e303027848909ee9d395a137cc30b680bd502b65dfa14315961982a3eb5ba1'
NETPROBE_PARAMS_LINE = ("PARAMS_JSON = '{}'  # @@AIEH-NETPROBE-PARAMS@@ "
                        "(tools/guest.py replaces this line)")
NETPROBE_MARKER = 'AIEH-NETPROBE'
NETPROBE_GUESTFWD = {'addr': '10.0.2.100', 'port': 7000}
NETPROBE_SLIRP_NET = ipaddress.ip_network('10.0.2.0/24')
NETPROBE_SLIRP_RESERVED = ('10.0.2.2', '10.0.2.3')
NETPROBE_PUBLIC = {
    'public_ipv4_tcp': [['1.1.1.1', 443], ['1.1.1.1', 80], ['8.8.8.8', 53], ['9.9.9.9', 443]],
    'public_ipv4_icmp': ['1.1.1.1', '8.8.8.8'],
    'public_dns_ipv4': ['1.1.1.1', '8.8.8.8', '9.9.9.9'],
    'public_ipv6_tcp': [['2606:4700:4700::1111', 443], ['2001:4860:4860::8888', 53]],
    'public_ipv6_icmp': ['2606:4700:4700::1111'],
    'public_dns_ipv6': ['2606:4700:4700::1111', '2001:4860:4860::8888'],
}
NETPROBE_V6_ADDR = 'fec0::15'          # the one IPv6 address the probe adds (netprobe.py)
NETPROBE_IFACE_PREFIX = 'aieh-'        # its veth pair (netprobe.py VETH_HOST, VETH_NS)
NETPROBE_NETNS = 'aieh-np'             # its network namespace (netprobe.py NETNS)
NETPROBE_RESULT = '/var/lib/aieh-netprobe/result.json'
NETPROBE_BOUNDARY = '==AIEH-NETPROBE-USER-DATA=='
# Probe results (netprobe.py): a denied path times out, is refused (a reset from SLIRP,
# never a host socket: the host ports probed all have live listeners) or gets no reply;
# a name is not resolved (not found, or no answer within the probe's ceiling). 'unreachable' means the guest's own stack gave up (no route,
# no neighbour), which shows nothing about the enforcement point: it is UNKNOWN.
NETPROBE_DENIED = frozenset({'timeout', 'refused', 'no-reply'})
NETPROBE_RESOLVE_DENIED = frozenset({'not-found', 'timeout'})
NETPROBE_REACHED = frozenset({'connected', 'reply', 'resolved', 'exchanged',
                              'connected-no-exchange'})
NETPROBE_LINE_MAX = 512
NETPROBE_CONN_BYTES_MAX = 1 << 16
NETPROBE_CONN_MAX = 64
NETPROBE_LABEL = re.compile(r'^[a-z]{1,16}$')


def netprobe_mount(mount):
    """The mounts `ip netns add` creates for the probe's namespace (validation only)."""
    return (mount.get('target') == '/run/netns' and mount.get('fstype') == 'tmpfs') or \
        (mount.get('target') == f'/run/netns/{NETPROBE_NETNS}' and mount.get('fstype') == 'nsfs')


def ipv6_address_lines(text):
    """(interface, line) for every inet6 line of `ip -6 addr`."""
    out, iface = [], ''
    for line in (text or '').splitlines():
        header = re.match(r'^\d+: ([^:@\s]+)', line)
        if header:
            iface = header.group(1)
        elif 'inet6' in line:
            out.append((iface, line))
    return out


def netprobe_script_path(profile_path):
    return Path(profile_path).parent.joinpath(*NETPROBE_SCRIPT)


def netprobe_host_addresses():
    """The host's own IPv4 and IPv6 addresses, without loopback and link-local ones."""
    v4, v6 = set(), set()
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None)
    except OSError:
        infos = []
    for info in infos:
        addr = info[4][0]
        if '%' in addr:
            continue
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            continue
        (v4 if ip.version == 4 else v6).add(str(ip))
    return sorted(v4), sorted(v6)


def netprobe_debian_addresses():
    """deb.debian.org's first IPv4 and IPv6 address as the host resolves them, or None."""
    out = []
    for fam in (socket.AF_INET, socket.AF_INET6):
        try:
            out.append(socket.getaddrinfo('deb.debian.org', 443, fam)[0][4][0])
        except (OSError, IndexError):
            out.append(None)
    return tuple(out)


def validate_netprobe_params(params):
    """Refuse anything but the documented keys, with literal IP addresses and ports."""
    def ip(value, version, what):
        try:
            parsed = ipaddress.ip_address(value)
        except (TypeError, ValueError):
            parsed = None
        if parsed is None or parsed.version != version or str(parsed) != value:
            raise Refused('REFUSED', f'netprobe {what}: {value!r} is not an IPv{version} literal')

    def port(value, what):
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
            raise Refused('REFUSED', f'netprobe {what}: {value!r} is not a port')

    keys = set(NETPROBE_PUBLIC) | {'guestfwd', 'host_ports', 'host_ipv4', 'host_ipv6',
                                   'debian_ipv4', 'debian_ipv6', 'marker'}
    if not isinstance(params, dict) or set(params) != keys:
        raise Refused('REFUSED', f'netprobe parameters: keys must be {sorted(keys)}')
    if params['marker'] != NETPROBE_MARKER:
        raise Refused('REFUSED', 'netprobe parameters: unexpected marker')
    gf = params['guestfwd']
    if not isinstance(gf, dict) or set(gf) != {'addr', 'port'}:
        raise Refused('REFUSED', 'netprobe guestfwd: addr and port required')
    ip(gf['addr'], 4, 'guestfwd address')
    if ipaddress.ip_address(gf['addr']) not in NETPROBE_SLIRP_NET or \
            gf['addr'] in NETPROBE_SLIRP_RESERVED:
        raise Refused('REFUSED', f'netprobe guestfwd address {gf["addr"]} must be an unused '
                      f'address of {NETPROBE_SLIRP_NET}')
    port(gf['port'], 'guestfwd port')
    host_ports = params['host_ports']
    if not isinstance(host_ports, dict) or \
            set(host_ports) != {'ssh', 'qmp', 'decoy_tcp', 'decoy_udp', 'listener'}:
        raise Refused('REFUSED', 'netprobe host ports: ssh, qmp, decoy_tcp, decoy_udp, listener')
    for key, value in host_ports.items():
        port(value, f'host port {key}')
    for version, key in ((4, 'public_ipv4_tcp'), (6, 'public_ipv6_tcp')):
        for pair in params[key]:
            if not isinstance(pair, list) or len(pair) != 2:
                raise Refused('REFUSED', f'netprobe {key}: [address, port] pairs')
            ip(pair[0], version, key)
            port(pair[1], key)
    for version, keys_ in ((4, ('public_ipv4_icmp', 'public_dns_ipv4', 'host_ipv4')),
                           (6, ('public_ipv6_icmp', 'public_dns_ipv6', 'host_ipv6'))):
        for key in keys_:
            if not isinstance(params[key], list):
                raise Refused('REFUSED', f'netprobe {key}: a list')
            for value in params[key]:
                ip(value, version, key)
    if len(params['public_dns_ipv4']) < 2:
        raise Refused('REFUSED', 'netprobe public_dns_ipv4: at least two resolvers')
    for version, key in ((4, 'debian_ipv4'), (6, 'debian_ipv6')):
        if params[key] is not None:
            ip(params[key], version, key)
    return params


def netprobe_params(ports, listener_ports, host_v4, host_v6, debian=(None, None)):
    params = copy.deepcopy(NETPROBE_PUBLIC)
    params.update({
        'guestfwd': dict(NETPROBE_GUESTFWD),
        'host_ports': {'ssh': int(ports['ssh']), 'qmp': int(ports['qmp']),
                       'decoy_tcp': int(listener_ports['decoy_tcp']),
                       'decoy_udp': int(listener_ports['decoy_udp']),
                       'listener': int(listener_ports['listener'])},
        'host_ipv4': list(host_v4), 'host_ipv6': list(host_v6),
        'debian_ipv4': debian[0], 'debian_ipv6': debian[1], 'marker': NETPROBE_MARKER})
    return validate_netprobe_params(params)


def render_netprobe_script(raw, params):
    """The pinned probe script with its one parameter line replaced."""
    got = hashlib.sha256(raw).hexdigest()
    if got != NETPROBE_SCRIPT_SHA256:
        raise Refused('DIGEST_MISMATCH', f'netprobe script sha256 {got} differs from the pin '
                      f'{NETPROBE_SCRIPT_SHA256}')
    if b'\r' in raw:
        raise Refused('REFUSED', 'netprobe script carries CR bytes')
    try:
        text = raw.decode('ascii')
    except UnicodeDecodeError as exc:
        raise Refused('REFUSED', f'netprobe script is not ASCII ({exc})') from exc
    if text.split('\n').count(NETPROBE_PARAMS_LINE) != 1:
        raise Refused('REFUSED', 'netprobe script: the parameter line must occur exactly once')
    validate_netprobe_params(params)
    literal = json.dumps(params, sort_keys=True, separators=(',', ':'))
    return text.replace(NETPROBE_PARAMS_LINE, f'PARAMS_JSON = {literal!r}  '
                        '# rendered by tools/guest.py netprobe', 1).encode('ascii')


def netprobe_user_data(cloud_config, script):
    """cloud-init multipart user-data: the ordinary cloud-config part, unchanged, then the
    test-only script part (cloud-init runs a text/x-shellscript part once, as root)."""
    boundary = NETPROBE_BOUNDARY.encode('ascii')
    for what, body in (('cloud-config', cloud_config), ('script', script)):
        if boundary in body or b'\r' in body:
            raise Refused('REFUSED', f'netprobe user-data: the {what} part holds the boundary '
                          'or a CR')
        try:
            body.decode('ascii')
        except UnicodeDecodeError as exc:
            raise Refused('REFUSED', f'netprobe user-data: the {what} part is not ASCII') from exc

    def part(content_type, filename, body):
        head = (f'--{NETPROBE_BOUNDARY}\n'
                f'Content-Type: {content_type}; charset="us-ascii"\n'
                'MIME-Version: 1.0\n'
                'Content-Transfer-Encoding: 7bit\n'
                f'Content-Disposition: attachment; filename="{filename}"\n\n')
        # the newline before the next delimiter belongs to the delimiter (RFC 2046)
        return head.encode('ascii') + body + b'\n'

    return (f'Content-Type: multipart/mixed; boundary="{NETPROBE_BOUNDARY}"\n'
            'MIME-Version: 1.0\n\n').encode('ascii') + \
        part('text/cloud-config', 'cloud-config.yaml', cloud_config) + \
        part('text/x-shellscript', 'aieh-netprobe.py', script) + \
        f'--{NETPROBE_BOUNDARY}--\n'.encode('ascii')


def netprobe_seed(profile_path, instance_dir, name, public_key, script):
    """seed.iso for a validation instance: the generator's own steps (tools/nocloud_seed.py:
    pinned templates, the same substitutions), with user-data wrapped by netprobe_user_data.
    meta-data and network-config are the ordinary ones."""
    gen = load_seed_generator()
    try:
        profile, root = gen.load_profile(str(Path(profile_path).parent))
        name = gen.check_instance_name(profile, name)
        instance_id = gen.new_instance_id(name)
        templates = gen.read_templates(profile, root)
        values = {'agent_ssh_public_key': gen.read_public_key(str(public_key)),
                  'scratch_device': gen.scratch_device(profile),
                  'provision_manifest': gen.provision_manifest_value(None),
                  'instance_id': instance_id, 'instance_name': name}
        rendered = gen.render(templates, values)
    except gen.Refused as exc:
        raise Refused('REFUSED', f'seed: {exc}') from exc
    ordinary = rendered['user-data']
    rendered['user-data'] = netprobe_user_data(ordinary, script)
    image = gen.build_iso(rendered)
    target = Path(instance_dir) / gen.SEED_NAME
    with open(target, 'xb') as handle:
        handle.write(image)
        handle.flush()
        os.fsync(handle.fileno())
    if sha256_file(target) != hashlib.sha256(image).hexdigest():
        raise Refused('REFUSED', f'{target}: written bytes differ from the generated image')
    return {'seed_iso': str(target), 'sha256': hashlib.sha256(image).hexdigest(),
            'size_bytes': len(image), 'instance_id': instance_id,
            'templates': {n: profile['boot_inputs']['seed']['templates'][n]['sha256']
                          for n in gen.FILES},
            'rendered_sha256': {n: hashlib.sha256(rendered[n]).hexdigest() for n in gen.FILES},
            'validation': {'ordinary_user_data_sha256': hashlib.sha256(ordinary).hexdigest(),
                           'script_part_sha256': hashlib.sha256(script).hexdigest(),
                           'user_data': 'multipart/mixed: text/cloud-config (the ordinary '
                                        'user-data), text/x-shellscript (aieh-netprobe.py)'}}


def netprobe_guestfwd_rule(listener_port):
    return (f'tcp:{NETPROBE_GUESTFWD["addr"]}:{NETPROBE_GUESTFWD["port"]}'
            f'-tcp:{LOOPBACK}:{int(listener_port)}')


def netprobe_chardev_label():
    """QEMU names a guestfwd's chardev guestfwd.tcp.<guest port> (net/slirp.c)."""
    return f'guestfwd.tcp.{NETPROBE_GUESTFWD["port"]}'


def netprobe_argv(argv, rule):
    """The rendered profile argv with one guestfwd appended to its user -netdev."""
    idx = [i + 1 for i in range(len(argv) - 1)
           if argv[i] == '-netdev' and argv[i + 1].startswith('user,')]
    if len(idx) != 1:
        raise Refused('REFUSED', f'netprobe: expected one user -netdev, found {len(idx)}')
    i = idx[0]
    if 'guestfwd=' in argv[i]:
        raise Refused('REFUSED', 'netprobe: the profile -netdev already has a guestfwd')
    if not re.fullmatch(r'tcp:10\.0\.2\.\d{1,3}:\d{1,5}-tcp:127\.0\.0\.1:\d{1,5}', rule):
        raise Refused('REFUSED', f'netprobe: guestfwd {rule!r} is not tcp:<guest>-tcp:127.0.0.1')
    effective = list(argv)
    effective[i] = f'{argv[i]},guestfwd={rule}'
    return effective, [{'index': i, 'profile': argv[i], 'effective': effective[i]}]


def netprobe_validation(profile_argv, listener_ports, listener_pid, script_rel, script,
                        seed_validation, params):
    """The effective argv and the launch record's validation block (Owner constraint 7)."""
    rule = netprobe_guestfwd_rule(listener_ports['listener'])
    argv, changes = netprobe_argv(profile_argv, rule)
    return argv, {
        'mode': 'netprobe', 'test_only': True, 'plan_leaf': 'F-03.3.2',
        'authority': 'decision 0003, "Owner authorization: network validation (2026-11-06)"',
        'single_boot': True,
        'profile_argv_sha256': argv_sha256(profile_argv),
        'argv_changes': changes,
        'guestfwd': {'rule': rule, 'guest_addr': NETPROBE_GUESTFWD['addr'],
                     'guest_port': NETPROBE_GUESTFWD['port'], 'host': LOOPBACK,
                     'host_port': listener_ports['listener'], 'chardev': netprobe_chardev_label()},
        'listener': {'pid': listener_pid, 'bind': LOOPBACK, 'ports': dict(listener_ports)},
        'script': {'path': script_rel, 'sha256': NETPROBE_SCRIPT_SHA256,
                   'rendered_sha256': hashlib.sha256(script).hexdigest()},
        'seed': seed_validation,
        'params': params,
    }


def argv_sha256(argv):
    return hashlib.sha256(json.dumps(argv, separators=(',', ':')).encode('utf-8')).hexdigest()


def forwarding_rules(argv):
    """The guestfwd values of every -netdev argument."""
    rules = []
    for i in range(len(argv) - 1):
        if argv[i] == '-netdev':
            rules += [part[len('guestfwd='):] for part in argv[i + 1].split(',')
                      if part.startswith('guestfwd=')]
    return rules


def check_forwarding(record):
    """Guest forwarding only where a validation record declares it (profiles P7)."""
    rules = forwarding_rules(record.get('argv') or [])
    validation = record.get('validation')
    if validation is None:
        if rules:
            raise Refused('REFUSED', f'the launch record carries guestfwd {rules} without a '
                          'validation mode; no profile endpoint enables guest forwarding')
        return rules
    want = [(validation.get('guestfwd') or {}).get('rule')]
    if validation.get('mode') != 'netprobe' or rules != want:
        raise Refused('REFUSED', f'validation record: guestfwd {rules} is not exactly {want}')
    return rules


def as_list(value):
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, dict) else []


def powershell_json(script):
    shell = Path(os.environ.get('SYSTEMROOT', r'C:\Windows')) / 'System32' / \
        'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, check=False, timeout=120)
    try:
        return json.loads(result.stdout)
    except ValueError:
        return {'error': result.stderr.strip() or result.stdout.strip()}


TCP_SELECT = ("Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,"
              "@{n='State';e={[string]$_.State}},OwningProcess")


def listener_bindings(pid, ports):
    """Get-NetTCPConnection / Get-NetUDPEndpoint for the listener process and its ports."""
    tcp_ports = ','.join(str(int(ports[k])) for k in ('listener', 'decoy_tcp'))
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        f"$t=@(Get-NetTCPConnection -OwningProcess {int(pid)} | {TCP_SELECT});"
        f"$u=@(Get-NetUDPEndpoint -OwningProcess {int(pid)} | "
        "Select-Object LocalAddress,LocalPort,OwningProcess);"
        f"$p=@(Get-NetTCPConnection -LocalPort {tcp_ports} | {TCP_SELECT});"
        f"$q=@(Get-NetUDPEndpoint -LocalPort {int(ports['decoy_udp'])} | "
        "Select-Object LocalAddress,LocalPort,OwningProcess);"
        "ConvertTo-Json -Depth 4 -InputObject "
        "@{tcp_by_pid=$t;udp_by_pid=$u;tcp_by_port=$p;udp_by_port=$q}")
    return powershell_json(script)


def guestfwd_connections(listener_port):
    """The established connections to the listener, with their owning process."""
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        f"$c=@(Get-NetTCPConnection -RemotePort {int(listener_port)} -RemoteAddress 127.0.0.1 | "
        f"{TCP_SELECT});"
        "ConvertTo-Json -Depth 4 -InputObject @{tcp_to_listener=$c}")
    return powershell_json(script)


def binding_problems(bindings, ports):
    """What is wrong with the listener's sockets: anything but 127.0.0.1 on its ports."""
    if not bindings or 'error' in bindings or not ports:
        return [f'no binding observation: {bindings}']
    tcp = as_list(bindings.get('tcp_by_pid'))
    udp = as_list(bindings.get('udp_by_pid'))
    listen = sorted({(c.get('LocalAddress'), c.get('LocalPort')) for c in tcp
                     if c.get('State') == 'Listen'})
    udp_eps = sorted({(u.get('LocalAddress'), u.get('LocalPort')) for u in udp})
    problems = [f'tcp listen {a}:{p}' for a, p in listen if a != LOOPBACK]
    problems += [f'udp {a}:{p}' for a, p in udp_eps if a != LOOPBACK]
    want_tcp = sorted({(LOOPBACK, ports.get('listener')), (LOOPBACK, ports.get('decoy_tcp'))})
    if listen != want_tcp:
        problems.append(f'tcp listening sockets {listen} are not {want_tcp}')
    if udp_eps != [(LOOPBACK, ports.get('decoy_udp'))]:
        problems.append(f'udp endpoints {udp_eps} are not {[(LOOPBACK, ports.get("decoy_udp"))]}')
    return problems


def netprobe_listen(log_path):
    """TEST-ONLY host side of one netprobe cycle, run as its own process by NetprobeSession.

    Three sockets, all bound to 127.0.0.1 at ports the OS chooses:
    - listener (TCP): the only guestfwd target. It speaks one line protocol and exposes
      nothing else: '<marker> HELLO <label>' gets '<marker> NONCE <32 hex>' (a fresh
      random nonce), and '<marker> ECHO <nonce>' gets '<marker> OK <label>' when the
      nonce matches. QEMU's guestfwd chardev keeps one connection open and carries every
      guest connection over it, so the protocol is line-based over one stream.
    - decoy (TCP) and decoy (UDP): never forwarded. The TCP decoy sends a banner and reads
      at most 256 bytes; the UDP decoy only logs. The harness's own self-checks are the
      only expected peers.
    Every connection, line and datagram is logged with its peer and byte count (JSON
    lines). The process prints its ports on stdout, then serves until stdin reaches EOF,
    which is the harness's stop signal.
    """
    lock = threading.Lock()
    state = {'closed': False, 'conns': 0}
    handle = open(log_path, 'x', encoding='utf-8', newline='\n')

    def log(**event):
        event['t'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        with lock:
            if not state['closed']:
                handle.write(json.dumps(event, sort_keys=True) + '\n')
                handle.flush()

    def admit(name, conn, peer):
        with lock:
            state['conns'] += 1
            over = state['conns'] > NETPROBE_CONN_MAX
        log(socket=name, event='accept', peer=list(peer[:2]), refused_over_limit=over)
        if over:
            conn.close()
        return not over

    def serve_listener(conn, peer):
        buf, total, label, pending = b'', 0, None, None
        try:
            while True:
                data = conn.recv(1024)
                if not data:
                    log(socket='listener', event='close', peer=list(peer[:2]), bytes=total)
                    return
                total += len(data)
                log(socket='listener', event='recv', peer=list(peer[:2]), bytes=len(data))
                if total > NETPROBE_CONN_BYTES_MAX:
                    log(socket='listener', event='limit', peer=list(peer[:2]), bytes=total)
                    return
                buf += data
                while b'\n' in buf:
                    raw, buf = buf.split(b'\n', 1)
                    text = raw.decode('ascii', 'replace')[:200]
                    parts = text.split()
                    if len(parts) == 3 and parts[:2] == [NETPROBE_MARKER, 'HELLO'] and \
                            NETPROBE_LABEL.match(parts[2]):
                        label, pending = parts[2], secrets.token_hex(16)
                        conn.sendall(f'{NETPROBE_MARKER} NONCE {pending}\n'.encode('ascii'))
                        log(socket='listener', event='hello', peer=list(peer[:2]), label=label,
                            line=text, nonce=pending)
                    elif len(parts) == 3 and parts[:2] == [NETPROBE_MARKER, 'ECHO']:
                        matched = pending is not None and parts[2] == pending
                        reply = f'{NETPROBE_MARKER} OK {label}' if matched else \
                            f'{NETPROBE_MARKER} BAD'
                        conn.sendall((reply + '\n').encode('ascii'))
                        log(socket='listener', event='exchange', peer=list(peer[:2]),
                            label=label, nonce=pending, echoed=parts[2], matched=matched,
                            line=text, reply=reply)
                        label, pending = None, None
                    else:
                        log(socket='listener', event='ignored', peer=list(peer[:2]), line=text)
                if len(buf) > NETPROBE_LINE_MAX:
                    log(socket='listener', event='overlong', peer=list(peer[:2]), bytes=len(buf))
                    buf = b''
        except OSError as exc:
            log(socket='listener', event='error', peer=list(peer[:2]), error=str(exc))
        finally:
            conn.close()

    def serve_decoy(conn, peer):
        got = b''
        try:
            conn.sendall(b'AIEH-DECOY\n')
            conn.settimeout(2.0)
            got = conn.recv(256)
        except OSError:
            pass
        finally:
            conn.close()
        log(socket='decoy-tcp', event='close', peer=list(peer[:2]), bytes=len(got),
            data=got[:64].decode('ascii', 'replace'))

    def accept_loop(sock, name, serve):
        while True:
            try:
                conn, peer = sock.accept()
            except OSError:
                return
            if admit(name, conn, peer):
                threading.Thread(target=serve, args=(conn, peer), daemon=True).start()

    def udp_loop(sock):
        while True:
            try:
                data, peer = sock.recvfrom(2048)
            except OSError:
                return
            log(socket='decoy-udp', event='datagram', peer=list(peer[:2]), bytes=len(data),
                data=data[:64].decode('ascii', 'replace'))

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    decoy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    decoy_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for sock in (listener, decoy, decoy_udp):
        sock.bind((LOOPBACK, 0))
    listener.listen(4)
    decoy.listen(4)
    ports = {'listener': listener.getsockname()[1], 'decoy_tcp': decoy.getsockname()[1],
             'decoy_udp': decoy_udp.getsockname()[1]}
    log(event='ready', pid=os.getpid(), bind=LOOPBACK, ports=ports)
    for target, args in ((accept_loop, (listener, 'listener', serve_listener)),
                         (accept_loop, (decoy, 'decoy-tcp', serve_decoy)),
                         (udp_loop, (decoy_udp,))):
        threading.Thread(target=target, args=args, daemon=True).start()
    print(json.dumps(dict(ports, pid=os.getpid())), flush=True)
    sys.stdin.buffer.read()              # EOF: the harness's stop signal
    log(event='stop')
    for sock in (listener, decoy, decoy_udp):
        sock.close()
    with lock:
        state['closed'] = True
        handle.close()
    return 0


class NetprobeSession:
    """The listener process of one netprobe cycle, from create to the end of netprobe."""

    def __init__(self):
        self.proc = self.pid = self.ports = self.dir = None
        self.bindings_before = self.bindings_after = None
        self.selfchecks, self.exit, self.killed, self.stopped = [], None, False, False

    def start(self, instance_dir):
        self.dir = Path(instance_dir) / 'netprobe'
        os.mkdir(self.dir)
        self.log_path = self.dir / 'listener.jsonl'
        argv = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), 'netprobe-listen',
                '--log', str(self.log_path)]
        with open(self.dir / 'listener.stderr', 'xb') as err:
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=err, cwd=str(self.dir))
        line = self.proc.stdout.readline()      # the listener's ready line, or EOF if it died
        try:
            ready = json.loads(line)
            self.pid = int(ready['pid'])
            self.ports = {k: int(ready[k]) for k in ('listener', 'decoy_tcp', 'decoy_udp')}
        except (ValueError, KeyError, TypeError) as exc:
            self.stop()
            raise Refused('NETPROBE_LISTENER', f'the test listener did not start: {line!r}') \
                from exc
        log(f'netprobe: listener pid {self.pid} on {LOOPBACK} {self.ports}')
        self.bindings_before = listener_bindings(self.pid, self.ports)
        problems = binding_problems(self.bindings_before, self.ports)
        if problems:
            self.stop()
            raise Refused('NETPROBE_LISTENER', f'the test listener is not on {LOOPBACK} only: '
                          f'{problems}', self.bindings_before)
        self.selfcheck('before')
        return self.ports

    def selfcheck(self, phase):
        """The decoys answer the harness (so their silence towards the guest means something)."""
        entry = {'phase': phase}
        try:
            with socket.create_connection((LOOPBACK, self.ports['decoy_tcp']), timeout=5) as s:
                entry['tcp_local_port'] = s.getsockname()[1]
                entry['tcp_banner'] = s.recv(64).decode('ascii', 'replace').strip()
                s.sendall(f'AIEH-SELFCHECK {phase}\n'.encode('ascii'))
        except OSError as exc:
            entry['tcp_error'] = str(exc)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
                u.bind((LOOPBACK, 0))
                entry['udp_local_port'] = u.getsockname()[1]
                u.sendto(f'AIEH-SELFCHECK {phase}'.encode('ascii'),
                         (LOOPBACK, self.ports['decoy_udp']))
        except OSError as exc:
            entry['udp_error'] = str(exc)
        self.selfchecks.append(entry)
        return entry

    def stop(self):
        if self.proc is None or self.stopped:
            return
        self.stopped = True
        try:
            self.proc.stdin.close()             # EOF: the listener's stop signal
        except OSError:
            pass
        try:
            self.exit = self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.killed = True
            self.exit = self.proc.wait(timeout=10)
        self.proc.stdout.close()
        if self.pid and self.ports:
            self.bindings_after = listener_bindings(self.pid, self.ports)
        log(f'netprobe: listener stopped, exit {self.exit}')

    def report(self):
        events = []
        if self.dir and self.log_path.is_file():
            for line in self.log_path.read_text(encoding='utf-8').splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    events.append({'unparsed': line[:200]})
        stderr = self.dir / 'listener.stderr' if self.dir else None
        return {'pid': self.pid, 'popen_pid': self.proc.pid if self.proc else None,
                'bind': LOOPBACK, 'ports': self.ports, 'bindings_before': self.bindings_before,
                'bindings_after': self.bindings_after, 'selfchecks': self.selfchecks,
                'exit': self.exit, 'killed': self.killed, 'log': events,
                'stderr': stderr.read_text(encoding='utf-8', errors='replace').strip()
                if stderr and stderr.is_file() else None}


def latest_record(instance_dir, operation):
    records = sorted((Path(instance_dir) / 'records').glob(f'{operation}-*.json'))
    if not records:
        return None
    return json.loads(records[-1].read_text(encoding='utf-8'))


def netprobe_probe_ok(probe):
    """True: denied as required; False: reached; None: neither is shown."""
    result = probe.get('result')
    if result in NETPROBE_REACHED:
        return False
    allowed = NETPROBE_RESOLVE_DENIED if probe.get('kind') == 'resolve' else NETPROBE_DENIED
    return True if result in allowed else None


def denied_check(name, probes, classes, method):
    rows = [p for p in probes if p.get('class') in classes and p.get('expect') == 'denied']
    verdicts = [netprobe_probe_ok(p) for p in rows]
    reached = [p.get('id') for p, v in zip(rows, verdicts) if v is False]
    unclear = [f'{p.get("id")}: {p.get("result")}' for p, v in zip(rows, verdicts) if v is None]
    ok = None if not rows else (False if reached else (None if unclear else True))
    return check(name, 'every probe denied: timeout, refused or no reply (a name: not resolved)',
                 {'probes': len(rows), 'reached': reached, 'unclear': unclear,
                  'results': {p.get('id'): p.get('result') for p in rows}}, method, ok)


def snapshot_out(result, phase, key):
    return (((result.get(phase) or {}).get(key)) or {}).get('out') or ''


def tx_packets(result, phase):
    try:
        link = json.loads(snapshot_out(result, phase, 'link_stats'))[0]
        stats = link.get('stats64') or link.get('stats')
        return int(stats['tx']['packets'])
    except (ValueError, IndexError, KeyError, TypeError):
        return None


def positive_check(name, scope_result, events, label, method):
    pos = (scope_result or {}).get('positive') or {}
    nonce = pos.get('nonce')
    matched = [e for e in events if e.get('socket') == 'listener' and e.get('event') == 'exchange'
               and e.get('label') == label and e.get('matched') is True and nonce
               and e.get('nonce') == nonce and e.get('echoed') == nonce]
    ok = None if not scope_result else (pos.get('result') == 'exchanged' and len(matched) == 1)
    return check(name, 'the guest got a fresh nonce, echoed it, and the listener logged the match',
                 {'guest': {'result': pos.get('result'), 'nonce': nonce, 'lines': pos.get('lines')},
                  'listener': [{k: e.get(k) for k in ('t', 'label', 'nonce', 'matched', 'peer')}
                               for e in matched]}, method, ok)


def netprobe_checks(record, np):
    """profiles P7 for a netprobe validation instance (F-03.3.2): the effective argv, the
    guest-root routes, every denied path, the positive control on both sides, the decoys
    and the listener's own sockets. np is the netprobe record (or None)."""
    np = np or {}
    validation = record.get('validation') or {}
    gr = np.get('guest_result') or {}
    lst = np.get('listener') or {}
    events = [e for e in lst.get('log') or [] if isinstance(e, dict)]
    checks = []

    changes = validation.get('argv_changes') or []
    gf = validation.get('guestfwd') or {}
    argv = record.get('argv') or []
    argv_ok = False
    if len(changes) == 1 and gf.get('host_port'):
        i = changes[0].get('index')
        reverted = list(argv)
        if isinstance(i, int) and 0 <= i < len(argv):
            reverted[i] = changes[0].get('profile')
        argv_ok = isinstance(i, int) and 0 <= i < len(argv) and \
            gf.get('rule') == netprobe_guestfwd_rule(gf['host_port']) and \
            argv[i] == f'{changes[0].get("profile")},guestfwd={gf.get("rule")}' and \
            changes[0].get('effective') == argv[i] and \
            argv_sha256(reverted) == validation.get('profile_argv_sha256') and \
            forwarding_rules(argv) == [gf.get('rule')]
    checks.append(check('effective argv: the profile argv plus one test guestfwd',
                        f'guestfwd={NETPROBE_GUESTFWD["addr"]}:{NETPROBE_GUESTFWD["port"]} to '
                        f'{LOOPBACK}:<listener port>, nothing else changed', changes,
                        'launch record argv against validation.argv_changes and the profile '
                        'argv digest', argv_ok))

    if not np:
        checks.append(check('netprobe record', 'records/netprobe-*.json', None,
                            'instance records', None))
        return checks

    checks.append(check('probe ran as guest root', 'uid 0, no error',
                        {'uid': gr.get('uid'), 'error': (gr.get('error') or '')[-400:] or None},
                        'guest: /var/lib/aieh-netprobe/result.json',
                        None if not gr else (gr.get('uid') == 0 and not gr.get('error'))))

    routes4 = snapshot_out(gr, 'after_setup', 'ip_route')
    routes6 = snapshot_out(gr, 'after_setup', 'ip6_route')
    defaults = [line for line in (routes4 + '\n' + routes6).splitlines() if line.startswith('default')]
    checks.append(check('default routes installed by guest root',
                        'default via 10.0.2.2 and default via fec0::2',
                        {'before': [line for line in (snapshot_out(gr, 'before', 'ip_route') + '\n' +
                                                      snapshot_out(gr, 'before', 'ip6_route'))
                                    .splitlines() if line.startswith('default')],
                         'after_setup': defaults},
                        'guest: ip route, ip -6 route', None if not gr else (
                            any(line.startswith('default via 10.0.2.2 ') for line in defaults) and
                            any(line.startswith('default via fec0::2 ') for line in defaults))))

    tx0, tx1 = tx_packets(gr, 'after_setup'), tx_packets(gr, 'after_probes')
    checks.append(check('frames left the guest NIC during the probes', 'tx packets rise',
                        {'after_setup': tx0, 'after_probes': tx1},
                        'guest: ip -s -j link (stats64.tx.packets)',
                        None if tx0 is None or tx1 is None else tx1 > tx0))

    checks.append(positive_check('positive control: guest to the test listener through guestfwd',
                                 gr.get('guest'), events, 'guest',
                                 'guest exchange; host listener log'))
    probes = (gr.get('guest') or {}).get('probes') or []
    for name, classes in (
            ('denied: public IPv4 by IP literal, ICMP and DNS, with a default route',
             {'ipv4-direct', 'dns'}),
            ('denied: host loopback through SLIRP (10.0.2.2) and the allowlist edges',
             {'host-loopback', 'allowlist-edge'}),
            ("denied: the host's LAN addresses", {'host-lan'}),
            ('denied: IPv6, with an address and a default route added by guest root', {'ipv6'})):
        checks.append(denied_check(name, probes, classes, 'guest: netprobe.py as root'))

    selfchecks = lst.get('selfchecks') or []
    sc_tcp = {s.get('tcp_local_port') for s in selfchecks if s.get('tcp_local_port')}
    sc_udp = {s.get('udp_local_port') for s in selfchecks if s.get('udp_local_port')}
    decoy_tcp = [e for e in events if e.get('socket') == 'decoy-tcp' and e.get('event') == 'accept']
    decoy_udp = [e for e in events if e.get('socket') == 'decoy-udp' and e.get('event') == 'datagram']
    foreign = [e for e in decoy_tcp if (e.get('peer') or [None, None])[1] not in sc_tcp] + \
        [e for e in decoy_udp if (e.get('peer') or [None, None])[1] not in sc_udp]
    phases = {s.get('phase') for s in selfchecks if s.get('tcp_local_port') in
              {(e.get('peer') or [None, None])[1] for e in decoy_tcp} and s.get('udp_local_port') in
              {(e.get('peer') or [None, None])[1] for e in decoy_udp}}
    checks.append(check('decoy host-loopback services: no connection from the guest',
                        'only the harness self-checks, before and after the probes, reached them',
                        {'tcp_accepts': len(decoy_tcp), 'udp_datagrams': len(decoy_udp),
                         'selfcheck_phases_logged': sorted(p for p in phases if p),
                         'foreign': foreign},
                        'host: decoy log', False if foreign else (
                            True if {'before', 'after'} <= phases else None)))

    accepts = [e for e in events if e.get('socket') == 'listener' and e.get('event') == 'accept']
    qemu_pid = np.get('qemu_pid')
    conns = as_list((np.get('guestfwd_connections') or {}).get('tcp_to_listener'))
    qemu_ports = {c.get('LocalPort') for c in conns
                  if c.get('OwningProcess') == qemu_pid and c.get('LocalAddress') == LOOPBACK}
    others = [e for e in accepts if (e.get('peer') or [None, None])[1] not in qemu_ports]
    checks.append(check("test listener: connections only from QEMU's guestfwd chardev",
                        'every accepted peer is a 127.0.0.1 port owned by the QEMU process',
                        {'accepts': [e.get('peer') for e in accepts], 'qemu_pid': qemu_pid,
                         'qemu_ports': sorted(p for p in qemu_ports if p), 'others': others},
                        'host: listener log; Get-NetTCPConnection -RemotePort',
                        None if not qemu_pid else (bool(accepts) and not others)))

    problems = binding_problems(lst.get('bindings_before'), lst.get('ports'))
    checks.append(check('test listener and decoys bound to 127.0.0.1 only', [],
                        problems, 'host: Get-NetTCPConnection / Get-NetUDPEndpoint -OwningProcess',
                        None if lst.get('bindings_before') is None else not problems))
    after = lst.get('bindings_after')
    left = time_wait = None
    if after is not None and 'error' not in after:
        # TimeWait entries belong to no process (OwningProcess 0): the kernel's record of a
        # connection already closed, not a socket of the listener
        entries = [e for k in ('tcp_by_pid', 'udp_by_pid', 'tcp_by_port', 'udp_by_port')
                   for e in as_list(after.get(k))]
        time_wait = [e for e in entries if e.get('State') == 'TimeWait' and
                     not e.get('OwningProcess')]
        left = [e for e in entries if e not in time_wait]
    checks.append(check('listener stopped after the cycle', 'exit 0; no socket left',
                        {'exit': lst.get('exit'), 'killed': lst.get('killed'), 'sockets_left': left,
                         'time_wait': len(time_wait) if time_wait is not None else None},
                        'host: process exit; Get-NetTCPConnection / Get-NetUDPEndpoint',
                        None if left is None else (lst.get('exit') == 0 and not left)))

    ns = gr.get('netns') or {}
    if not ns.get('configured'):
        failed = [s for s in ns.get('setup') or [] if s.get('rc') != 0]
        checks.append(check('container namespace', 'configured: veth pair, guest NAT',
                            {'failed_step': failed[-1:] or None},
                            'guest: ip netns, veth, iptables MASQUERADE', None))
    else:
        pos = positive_check('positive control: container namespace through guest NAT and guestfwd',
                             ns, events, 'netns', 'namespace exchange; host listener log')
        checks.append(pos)
        denied = denied_check('denied from the container namespace: IPv4, ICMP, DNS, host '
                              'loopback, LAN, allowlist edges', ns.get('probes') or [],
                              {'ipv4-direct', 'dns', 'host-loopback', 'allowlist-edge', 'host-lan'},
                              'guest: netprobe.py in the namespace')
        if pos['verdict'] != 'PASS' and denied['verdict'] == 'PASS':
            denied['verdict'] = 'UNKNOWN'
            denied['observed']['note'] = ('the namespace positive control did not pass, so no '
                                          'denial is shown to be the enforcement point\'s')
        checks.append(denied)
    return checks


def netprobe_reachability(np):
    """The flat table of every probe: scope, id, class, expected and observed result."""
    gr = (np or {}).get('guest_result') or {}
    rows = []
    for scope, part in (('guest', gr.get('guest')), ('netns', gr.get('netns'))):
        part = part or {}
        pos = part.get('positive')
        if pos:
            rows.append({'scope': scope, 'id': f'guestfwd {pos.get("target")}', 'class': 'allowlisted',
                         'expect': 'permitted', 'result': pos.get('result')})
        for p in part.get('probes') or []:
            ok = netprobe_probe_ok(p) if p.get('expect') == 'denied' else None
            rows.append({'scope': scope, 'id': p.get('id'), 'class': p.get('class'),
                         'expect': p.get('expect'), 'result': p.get('result'),
                         'verdict': {True: 'denied', False: 'REACHED', None: 'unclear'}[ok]
                         if p.get('expect') == 'denied' else 'info'})
    return rows


def netprobe(ctx, name, ready_timeout=READY_TIMEOUT_S):
    """TEST-ONLY validation cycle for profiles P7 (F-03.3.2). The guest stays running for
    inspect, exchange and destroy; the listener is stopped before this returns."""
    t0 = time.time()
    idir = ctx.instance_dir(name)
    session = NetprobeSession()
    out = {'operation': 'netprobe', 'labels': labels(ctx.profile), 'instance': name,
           'mode': 'validation, test only (F-03.3.2; decision 0003, Owner authorization: '
                   'network validation)'}
    try:
        created = create(ctx, name, ready_timeout, netprobe=session)
        out['create'] = {k: created.get(k) for k in (
            'result', 'ports', 'instance_id', 'seed_sha256', 'launch_record_sha256', 'record',
            'error', 'seconds', 'ready', 'launch')}
        if created.get('result') == 'ready':
            record = read_launch_record(idir)
            proc = running_process(idir, record['binary'])
            out['qemu_pid'] = proc.pid if proc else None
            if proc:
                proc.close()
            out['guestfwd_connections'] = guestfwd_connections(session.ports['listener'])
            ssh = Ssh(ctx.profile, idir, record['ports']['ssh'])
            got = ssh.run(['cat', '--', NETPROBE_RESULT], timeout=60)
            try:
                out['guest_result'] = json.loads(got.stdout)
            except ValueError:
                out['guest_result'] = None
                out['guest_result_error'] = f'rc {got.returncode}: {got.stderr.strip()[:500]}'
            session.selfcheck('after')
    finally:
        session.stop()
    out['listener'] = session.report()
    record = read_launch_record(idir)
    out['checks'] = netprobe_checks(record, out)
    out['reachability'] = netprobe_reachability(out)
    out['result'] = prop('P7', out['checks'])['verdict']
    out['seconds'] = round(time.time() - t0, 1)
    out['record'] = write_record(idir, 'netprobe', out)
    return out


def enforcement_check(profile):
    """Ordinary instances: the enforcement point is qualified by the netprobe validation
    (a declared reference; an ordinary guest has no root to repeat that test)."""
    ep = (profile.get('network') or {}).get('enforcement_point')
    status = ep.get('status') if isinstance(ep, dict) else None
    return check('enforcement point qualified', 'qualified by the F-03.3.2 netprobe validation',
                 {'status': status, 'evidence': ep.get('evidence') if isinstance(ep, dict) else None},
                 'profile network.enforcement_point (declared reference)',
                 {'qualified': True, 'failed': False}.get(status))


# ---------------------------------------------------------------- provision fetch (F-04.1a)
#
# Host side of the provisioning channel (decision 0006, Proposed; decision 0005): every
# artifact in the profile's provision lock is downloaded from its original upstream,
# checked against the lock, and staged under {state_dir}/provision/<lock sha256>/. The
# image is fetched by the pinned, verified crane; nothing else downloaded is unpacked or
# run on the host. The guest side (transfer and install) is a later slice.

PROVISION_LOCK_SCHEMA = 'ai-engineering-harness/profiles/provision-lock/v1'
PROVISION_STAGED_SCHEMA = 'ai-engineering-harness/profiles/provision-staged/v1'
PROVISION_UA = 'aieh-provision-fetch/1 (+F-04.1)'
PROVISION_HEX64 = re.compile(r'^[0-9a-f]{64}$')
PROVISION_DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
PROVISION_PART = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+~-]*$')   # one path component
PROVISION_REPOSITORY = re.compile(r'^[a-z0-9.-]+(/[a-z0-9._-]+)+$')
PROVISION_STAGED_FILE = 'staged.json'
FETCH_TIMEOUT_S = 120      # socket ceiling per connect or read (bounds a hang)
CRANE_TIMEOUT_S = 3600     # ceiling for one crane call (bounds a hang; the pull is ~1.3 GB)


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects (snapshot.debian.org and GitHub use them) to https URLs only."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith('https://'):
            raise urllib.error.HTTPError(req.full_url, code, f'redirect refused: {newurl}',
                                         headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def provision_opener():
    return urllib.request.build_opener(_HttpsOnlyRedirect())


def provision_lock(ctx):
    """The profile's provision lock, after its bytes match the profile's sha256 pin."""
    entry = (ctx.profile.get('provider') or {}).get('provision_lock')
    if not isinstance(entry, dict) or not entry.get('path') or \
            not PROVISION_HEX64.match(str(entry.get('sha256', ''))):
        raise Refused('REFUSED', 'profile provider.provision_lock needs a path and a sha256')
    path = (Path(ctx.repo) / entry['path']).resolve()
    if not inside(path, Path(ctx.repo) / 'profiles'):
        raise Refused('REFUSED', f'provision lock {entry["path"]} is not under profiles/')
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise Refused('REFUSED', f'provision lock {entry["path"]}: cannot read ({exc})') from exc
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry['sha256']:
        raise Refused('LOCK_MISMATCH', f'provision lock {entry["path"]} has sha256 {digest}; '
                      f'the profile pins {entry["sha256"]}')
    lock = json.loads(data.decode('utf-8'))
    if lock.get('schema') != PROVISION_LOCK_SCHEMA or lock.get('profile') != ctx.profile.get('name'):
        raise Refused('REFUSED', f'provision lock {entry["path"]}: not a {PROVISION_LOCK_SCHEMA} '
                      f'lock for {ctx.profile.get("name")}')
    return lock, entry['path'], digest


def _provision_rel(*parts):
    for part in parts:
        if not isinstance(part, str) or not PROVISION_PART.match(part) or part in ('.', '..'):
            raise Refused('REFUSED', f'provision lock: unsafe path component {part!r}')
    return '/'.join(parts)


def _provision_pin(what, url, size, sha256):
    if not isinstance(url, str) or not url.startswith('https://'):
        raise Refused('REFUSED', f'provision lock: {what} URL {url!r} is not https')
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise Refused('REFUSED', f'provision lock: {what} size {size!r} is not a byte count')
    if not isinstance(sha256, str) or not PROVISION_HEX64.match(sha256):
        raise Refused('REFUSED', f'provision lock: {what} sha256 is not 64 lowercase hex digits')


def provision_items(lock):
    """Every plain download of the lock: (staged path, url, size, sha256, role)."""
    items = []
    debian = lock.get('debian') or {}
    for suite in debian.get('suites') or []:
        for entry in suite.get('files') or []:
            rel = _provision_rel('index', suite.get('archive'), *str(entry.get('path')).split('/'))
            items.append((rel, entry.get('url'), entry.get('size'), entry.get('sha256'), 'debian-index'))
    for package in debian.get('packages') or []:
        name = package.get('filename')
        if not isinstance(name, str) or not name.endswith('.deb'):
            raise Refused('REFUSED', f'provision lock: package filename {name!r} is not a .deb')
        items.append((_provision_rel('debs', name), package.get('url'), package.get('size'),
                      package.get('sha256'), 'deb'))
    binary = lock.get('release_binary') or {}
    items.append((_provision_rel('agent-server', binary.get('name')), binary.get('url'),
                  binary.get('size'), binary.get('sha256'), 'release-binary'))
    for rel, url, size, sha256, _ in items:
        _provision_pin(rel, url, size, sha256)
    if len({i[0] for i in items}) != len(items):
        raise Refused('REFUSED', 'provision lock: two artifacts share a staged path')
    return items


def provision_image(lock):
    image = lock.get('image') or {}
    for key in ('index_digest', 'manifest_digest', 'config_digest'):
        if not PROVISION_DIGEST.match(str(image.get(key, ''))):
            raise Refused('REFUSED', f'provision lock: image.{key} is not a sha256 digest')
    if not PROVISION_REPOSITORY.match(str(image.get('repository', ''))):
        raise Refused('REFUSED', f'provision lock: image.repository {image.get("repository")!r}')
    if image.get('platform') != 'linux/amd64':
        raise Refused('REFUSED', 'provision lock: image.platform must be linux/amd64')
    layers = image.get('layers')
    if not isinstance(layers, list) or not layers or not all(
            isinstance(l, dict) and PROVISION_DIGEST.match(str(l.get('digest', ''))) and
            isinstance(l.get('size'), int) for l in layers):
        raise Refused('REFUSED', 'provision lock: image.layers must list digests and sizes')
    if image.get('image_id', image['config_digest']) != image['config_digest']:
        raise Refused('REFUSED', 'provision lock: image.image_id differs from config_digest')
    return image


def _check_existing(path, size, sha256):
    got_size = path.stat().st_size
    got = sha256_file(path)
    if got_size != size or got != sha256:
        raise Refused('HASH_MISMATCH', f'{path} is {got_size} bytes with sha256 {got}; the lock '
                      f'says {size} bytes, {sha256} (left in place for inspection)',
                      {'path': str(path), 'observed': got, 'expected': sha256})


def fetch_file(opener, url, dest, size, sha256):
    """Download url to dest through dest.part, refusing more than size bytes or a digest
    other than sha256. A mismatching download is kept as dest.rejected for inspection."""
    part = dest.with_name(dest.name + '.part')
    if os.path.lexists(part):
        part.unlink()                      # this tool's own interrupted download
    digest, count, t0 = hashlib.sha256(), 0, time.time()
    request = urllib.request.Request(url, headers={'User-Agent': PROVISION_UA})
    try:
        with opener.open(request, timeout=FETCH_TIMEOUT_S) as resp:
            final = resp.geturl()
            if not str(final).startswith('https://'):
                raise Refused('FETCH', f'{url}: ended at a non-https URL {final}')
            with open(part, 'xb') as out:
                for block in iter(lambda: resp.read(1 << 20), b''):
                    count += len(block)
                    if count > size:
                        raise Refused('HASH_MISMATCH', f'{url}: more than the locked {size} bytes')
                    digest.update(block)
                    out.write(block)
    except Refused:
        if os.path.lexists(part):
            part.unlink()
        raise
    except (OSError, ValueError) as exc:   # urllib.error.URLError and HTTPError are OSErrors
        if os.path.lexists(part):
            part.unlink()
        raise Refused('FETCH', f'{url}: {exc}') from exc
    got = digest.hexdigest()
    if count != size or got != sha256:
        rejected = dest.with_name(dest.name + '.rejected')
        os.replace(part, rejected)
        raise Refused('HASH_MISMATCH', f'{url}: {count} bytes with sha256 {got}; the lock says '
                      f'{size} bytes, {sha256} (kept as {rejected})',
                      {'url': url, 'observed': got, 'expected': sha256, 'kept': str(rejected)})
    os.rename(part, dest)
    # only the host: a redirect target can be a pre-signed URL (GitHub release assets)
    return {'bytes': count, 'seconds': round(time.time() - t0, 1),
            'final_host': urllib.parse.urlsplit(str(final)).netloc}


def ensure_crane(state_dir, pin, opener):
    """The pinned crane under {state_dir}/tools/crane/<version>/, verified before any use."""
    for key in ('version', 'asset'):
        if not PROVISION_PART.match(str(pin.get(key, ''))):
            raise Refused('REFUSED', f'provision lock: tools.crane.{key} {pin.get(key)!r}')
    member = pin.get('member') or {}
    if member.get('name') != 'crane.exe':
        raise Refused('REFUSED', 'provision lock: tools.crane.member.name must be crane.exe')
    _provision_pin('tools.crane', pin.get('url'), pin.get('size'), pin.get('sha256'))
    if not isinstance(member.get('size'), int) or \
            not PROVISION_HEX64.match(str(member.get('sha256', ''))):
        raise Refused('REFUSED', 'provision lock: tools.crane.member needs a size and a sha256')
    tool_dir = Path(state_dir) / 'tools' / 'crane' / pin['version']
    exe = tool_dir / 'crane.exe'
    if os.path.lexists(exe):
        _check_existing(exe, member['size'], member['sha256'])
        return exe, {'state': 'reused', 'path': str(exe), 'sha256': member['sha256']}
    tool_dir.mkdir(parents=True, exist_ok=True)
    archive = tool_dir / pin['asset']
    fetched = None
    if os.path.lexists(archive):
        _check_existing(archive, pin['size'], pin['sha256'])
    else:
        fetched = fetch_file(opener, pin['url'], archive, pin['size'], pin['sha256'])
    try:
        with tarfile.open(archive, 'r:gz') as tf:
            found = [m for m in tf.getmembers() if m.name == 'crane.exe']
            if len(found) != 1 or not found[0].isfile() or found[0].size != member['size']:
                raise Refused('HASH_MISMATCH', f'{archive}: no single regular crane.exe of '
                              f'{member["size"]} bytes')
            data = tf.extractfile(found[0]).read()
    except (OSError, tarfile.TarError) as exc:
        raise Refused('HASH_MISMATCH', f'{archive}: unreadable ({exc})') from exc
    got = hashlib.sha256(data).hexdigest()
    if got != member['sha256']:
        raise Refused('HASH_MISMATCH', f'{archive}: crane.exe has sha256 {got}; the lock says '
                      f'{member["sha256"]}')
    part = exe.with_name('crane.exe.part')
    if os.path.lexists(part):
        part.unlink()
    with open(part, 'xb') as out:
        out.write(data)
    os.rename(part, exe)
    archive.unlink()
    return exe, {'state': 'installed', 'path': str(exe), 'sha256': got, 'archive_fetch': fetched}


def crane_env(home, temp, environ=None):
    """A scrubbed environment: no proxy or registry settings of the caller, and an empty
    DOCKER_CONFIG and home, so crane reads no stored credentials and pulls anonymously."""
    environ = os.environ if environ is None else environ
    env = {key: environ[key] for key in ('SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE') if key in environ}
    env.update({'DOCKER_CONFIG': str(home), 'USERPROFILE': str(home), 'HOME': str(home),
                'TEMP': str(temp), 'TMP': str(temp)})
    return env


def run_crane(exe, args, env, timeout=CRANE_TIMEOUT_S):
    result = subprocess.run([str(exe)] + list(args), capture_output=True, env=env,
                            stdin=subprocess.DEVNULL, timeout=timeout, check=False)
    return result.returncode, result.stdout, result.stderr.decode('utf-8', errors='replace')


def image_manifests(crane, exe, env, image):
    """The index and platform manifest bytes, each checked against its locked digest, and
    the platform manifest's config and layers against the lock."""
    def get(digest):
        rc, out, err = crane(exe, ['manifest', f'{image["repository"]}@{digest}'], env)
        if rc != 0:
            raise Refused('CRANE', f'crane manifest {digest} exited {rc}: {err.strip()[-500:]}')
        got = 'sha256:' + hashlib.sha256(out).hexdigest()
        if got != digest:
            raise Refused('DIGEST_MISMATCH', f'crane manifest {digest} returned bytes with {got}')
        return out
    index_bytes = get(image['index_digest'])
    index = json.loads(index_bytes)
    os_name, arch = image['platform'].split('/')
    matches = [m.get('digest') for m in index.get('manifests') or []
               if (m.get('platform') or {}).get('os') == os_name and
               (m.get('platform') or {}).get('architecture') == arch and
               not (m.get('platform') or {}).get('variant')]
    if matches != [image['manifest_digest']]:
        raise Refused('DIGEST_MISMATCH', f'index {image["index_digest"]} lists {matches} for '
                      f'{image["platform"]}; the lock says {image["manifest_digest"]}')
    manifest_bytes = get(image['manifest_digest'])
    manifest = json.loads(manifest_bytes)
    config = manifest.get('config') or {}
    if config.get('digest') != image['config_digest'] or \
            ('config_size' in image and config.get('size') != image['config_size']):
        raise Refused('DIGEST_MISMATCH', f'manifest {image["manifest_digest"]} names config '
                      f'{config.get("digest")}; the lock says {image["config_digest"]}')
    got_layers = [(l.get('digest'), l.get('size')) for l in manifest.get('layers') or []]
    if got_layers != [(l['digest'], l['size']) for l in image['layers']]:
        raise Refused('DIGEST_MISMATCH', f'manifest {image["manifest_digest"]} layers differ '
                      'from the lock')
    return index_bytes, manifest_bytes


def _member_sha256(tf, member):
    digest = hashlib.sha256()
    handle = tf.extractfile(member)
    for block in iter(lambda: handle.read(1 << 20), b''):
        digest.update(block)
    return 'sha256:' + digest.hexdigest()


def verify_image_tar(path, image):
    """A docker-archive written by crane pull: manifest.json, the config and the layers,
    all regular files and nothing else; the config member hashes to the locked config
    digest (the image ID) and each layer member, in order, to its locked digest and size."""
    try:
        with tarfile.open(path, 'r:') as tf:
            members = tf.getmembers()
            names = [m.name for m in members]
            by_name = {m.name: m for m in members}
            if len(names) != len(by_name):
                raise Refused('IMAGE_MISMATCH', f'{path}: duplicate member names')
            irregular = [m.name for m in members if not m.isfile()]
            if irregular:
                raise Refused('IMAGE_MISMATCH', f'{path}: non-regular members {irregular[:5]}')
            if 'manifest.json' not in by_name:
                raise Refused('IMAGE_MISMATCH', f'{path}: no manifest.json')
            entries = json.loads(tf.extractfile(by_name['manifest.json']).read())
            if not isinstance(entries, list) or len(entries) != 1 or \
                    not isinstance(entries[0], dict):
                raise Refused('IMAGE_MISMATCH', f'{path}: manifest.json is not one image')
            config_name, layer_names = entries[0].get('Config'), entries[0].get('Layers')
            if not isinstance(config_name, str) or not isinstance(layer_names, list):
                raise Refused('IMAGE_MISMATCH', f'{path}: manifest.json lacks Config or Layers')
            expected = {'manifest.json', config_name, *layer_names}
            if set(names) != expected:
                raise Refused('IMAGE_MISMATCH', f'{path}: members {sorted(set(names) ^ expected)[:5]} '
                              'are unexpected or missing')
            config = _member_sha256(tf, by_name[config_name])
            if config != image['config_digest']:
                raise Refused('IMAGE_MISMATCH', f'{path}: config member has {config}; the lock '
                              f'says {image["config_digest"]} (the image ID)')
            hashed = {name: _member_sha256(tf, by_name[name]) for name in set(layer_names)}
            got = [(hashed[name], by_name[name].size) for name in layer_names]
            if got != [(l['digest'], l['size']) for l in image['layers']]:
                raise Refused('IMAGE_MISMATCH', f'{path}: layer members differ from the lock')
    except (OSError, ValueError, tarfile.TarError) as exc:
        raise Refused('IMAGE_MISMATCH', f'{path}: unreadable ({exc})') from exc
    return {'members': len(names), 'config_digest': config, 'layers': len(layer_names),
            'distinct_layers': len(set(layer_names)), 'repo_tags': entries[0].get('RepoTags'),
            'bytes': Path(path).stat().st_size}


def _plain_dir(path):
    if os.path.islink(path) or os.path.isjunction(path) or \
            (os.path.lexists(path) and not os.path.isdir(path)):
        raise Refused('REFUSED', f'{path} is not a plain directory')


def staged_inventory(root):
    """Every regular file under root, relative and '/'-separated; any other entry refuses."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            if os.path.islink(os.path.join(dirpath, name)) or \
                    os.path.isjunction(os.path.join(dirpath, name)):
                raise Refused('REFUSED', f'{os.path.join(dirpath, name)} is a link')
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or not os.path.isfile(path):
                raise Refused('REFUSED', f'{path} is not a regular file')
            files.append(posix(os.path.relpath(path, root)))
    return sorted(files)


IMAGE_FILES = ('image/index.json', 'image/manifest.json', 'image/agent-server.tar')


def verify_staged(staged_dir, lock_sha, items, image):
    """Re-check a staged directory: its manifest names this lock, it holds exactly the
    lock's artifacts, every file matches, and the image archive matches the lock."""
    t0 = time.time()
    try:
        staged = json.loads((Path(staged_dir) / PROVISION_STAGED_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise Refused('STAGED_MISMATCH', f'{staged_dir}: no readable {PROVISION_STAGED_FILE}') from exc
    if staged.get('schema') != PROVISION_STAGED_SCHEMA or \
            (staged.get('lock') or {}).get('sha256') != lock_sha:
        raise Refused('STAGED_MISMATCH', f'{staged_dir}: the staged manifest is not for lock {lock_sha}')
    files = {f.get('path'): f for f in staged.get('files') or []}
    want = {rel for rel, *_ in items} | set(IMAGE_FILES)
    on_disk = set(staged_inventory(staged_dir)) - {PROVISION_STAGED_FILE}
    if set(files) != want or on_disk != want:
        raise Refused('STAGED_MISMATCH', f'{staged_dir}: holds {sorted(on_disk ^ want)[:5]} '
                      'beyond or short of the lock')
    for rel, _url, size, sha256, _role in items:
        if (files[rel].get('size'), files[rel].get('sha256')) != (size, sha256):
            raise Refused('STAGED_MISMATCH', f'{rel}: the staged manifest differs from the lock')
    for rel, entry in sorted(files.items()):
        try:
            _check_existing(Path(staged_dir) / rel, entry.get('size'), entry.get('sha256'))
        except Refused as exc:
            raise Refused('STAGED_MISMATCH', str(exc), exc.detail) from exc
    for rel, digest in (('image/index.json', image['index_digest']),
                        ('image/manifest.json', image['manifest_digest'])):
        if 'sha256:' + files[rel]['sha256'] != digest:
            raise Refused('STAGED_MISMATCH', f'{rel} is not {digest}')
    tar = verify_image_tar(Path(staged_dir) / 'image' / 'agent-server.tar', image)
    return {'files': len(files), 'bytes': sum(f['size'] for f in files.values()),
            'image': tar, 'seconds': round(time.time() - t0, 1)}


def provision_fetch(ctx, opener=None, crane=None):
    """provision-fetch: download, verify and stage every artifact of the provision lock.

    Idempotent: a staged directory for this lock is re-verified and reused. Atomic: work
    happens in {lock sha256}.partial (resumable; complete files are re-checked, never
    re-downloaded) and is renamed to {lock sha256} only after everything verified."""
    t0 = time.time()
    lock, lock_rel, lock_sha = provision_lock(ctx)
    items = provision_items(lock)
    image = provision_image(lock)
    pin = (lock.get('tools') or {}).get('crane') or {}
    root = Path(ctx.state_dir) / 'provision'
    final, work = root / lock_sha, root / f'{lock_sha}.partial'
    for path in (root, final, work):
        _plain_dir(path)
    result = {'operation': 'provision-fetch', 'labels': labels(ctx.profile),
              'lock': {'path': lock_rel, 'sha256': lock_sha}, 'staged_dir': str(final)}
    if os.path.lexists(final):
        result['verify'] = verify_staged(final, lock_sha, items, image)
        result['result'] = 'reused'
        result['seconds'] = round(time.time() - t0, 1)
        return result
    opener = opener or provision_opener()
    crane = crane or run_crane
    work.mkdir(parents=True, exist_ok=True)
    files, downloads = [], []
    for rel, url, size, sha256, role in items:
        dest = work / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(dest):
            _check_existing(dest, size, sha256)
            downloads.append({'path': rel, 'state': 'reused', 'bytes': size})
        else:
            log(f'provision-fetch: {url}')
            downloads.append(dict(fetch_file(opener, url, dest, size, sha256), path=rel,
                                  state='fetched'))
        files.append({'path': rel, 'role': role, 'size': size, 'sha256': sha256})
    exe, crane_state = ensure_crane(ctx.state_dir, pin, opener)
    home, temp = work / 'crane-home', work / 'crane-tmp'
    for path in (home, temp):
        if os.path.lexists(path):
            remove_tree(path)
        path.mkdir()
    env = crane_env(home, temp)
    (work / 'image').mkdir(exist_ok=True)
    index_bytes, manifest_bytes = image_manifests(crane, exe, env, image)
    for rel, data in (('image/index.json', index_bytes), ('image/manifest.json', manifest_bytes)):
        (work / rel).write_bytes(data)
        files.append({'path': rel, 'role': 'image-' + rel.split('/')[1].split('.')[0],
                      'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    tar = work / 'image' / 'agent-server.tar'
    pull = {'state': 'reused'}
    if not os.path.lexists(tar):
        part = tar.with_name('agent-server.tar.part')
        if os.path.lexists(part):
            part.unlink()
        ref = f'{image["repository"]}@{image["index_digest"]}'
        log(f'provision-fetch: crane pull --platform {image["platform"]} {ref}')
        t1 = time.time()
        rc, _out, err = crane(exe, ['pull', '--platform', image['platform'], ref, str(part)], env)
        pull = {'state': 'pulled', 'rc': rc, 'seconds': round(time.time() - t1, 1)}
        if rc != 0:
            if os.path.lexists(part):
                part.unlink()
            raise Refused('CRANE', f'crane pull exited {rc}: {err.strip()[-500:]}', pull)
        try:
            pull['verify'] = verify_image_tar(part, image)
        except Refused:
            os.replace(part, tar.with_name('agent-server.tar.rejected'))
            raise
        os.rename(part, tar)
    else:
        pull['verify'] = verify_image_tar(tar, image)
    files.append({'path': 'image/agent-server.tar', 'role': 'image-archive',
                  'size': tar.stat().st_size, 'sha256': sha256_file(tar)})
    leftovers = staged_inventory(home)
    if leftovers:
        raise Refused('CRANE_STATE', f'crane wrote into its empty home: {leftovers}')
    remove_tree(home)
    remove_tree(temp)
    staged = {'schema': PROVISION_STAGED_SCHEMA, 'profile': ctx.profile.get('name'),
              'lock': {'path': lock_rel, 'sha256': lock_sha},
              'image': {'ref': f'{image["repository"]}@{image["index_digest"]}',
                        'manifest_digest': image['manifest_digest'],
                        'config_digest': image['config_digest']},
              'crane': {'version': pin['version'], 'sha256': pin['member']['sha256']},
              'files': sorted(files, key=lambda f: f['path'])}
    with open(work / PROVISION_STAGED_FILE, 'w', encoding='utf-8', newline='\n') as handle:
        json.dump(staged, handle, indent=2, sort_keys=True)
        handle.write('\n')
    stray = sorted(set(staged_inventory(work)) - {f['path'] for f in files} -
                   {PROVISION_STAGED_FILE})
    if stray:
        raise Refused('STAGED_MISMATCH', f'{work}: unexpected files {stray[:5]}')
    if os.path.lexists(final):
        raise Refused('REFUSED', f'{final} appeared while staging; not replaced')
    os.rename(work, final)
    result.update({'result': 'staged', 'downloads': downloads, 'crane': crane_state,
                   'image': {'ref': staged['image']['ref'], 'pull': pull},
                   'files': len(files), 'bytes': sum(f['size'] for f in files),
                   'seconds': round(time.time() - t0, 1)})
    records = root / 'records'
    records.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    write_json_exclusive(records / f'provision-fetch-{stamp}.json', result)
    return result


# ---------------------------------------------------------------- provision (F-04.1b)
#
# Guest side of the provisioning channel (decision 0006, Proposed; the Owner's F-04.1
# authorization, Part B). create --provision writes a manifest of the verified host stage
# into the seed; the seed also carries the single-use root step (profiles/seed/
# user-data.tmpl: /usr/local/sbin/aieh-provision, aieh-provision.path and .service, and
# aieh-docker-facts.service). provision copies the files by SFTP into the agent-owned
# upload directory, creates the READY marker, waits on RESULT.json and checks it. The
# root step copies, verifies against the seeded sha256 values, installs with apt and
# docker load, and disables itself. No network, no guestfwd, no launch.argv change.

PROVISION_MANIFEST_SCHEMA = 'ai-engineering-harness/profiles/provision-manifest/v1'
PROVISION_RESULT_SCHEMA = 'ai-engineering-harness/profiles/provision-result/v1'
MOBY_FACTS_SCHEMA = 'ai-engineering-harness/profiles/moby-facts/v1'
PROVISION_ROLES = ('deb', 'image-archive', 'release-binary')
PROVISION_IMAGE_ARCHIVE = 'agent-server.tar'
# processes whose TCP listener would break 'unix socket only' (profiles P6, P7)
MOBY_PROCESSES = ('dockerd', 'containerd', 'docker-proxy', 'containerd-shim')
MOBY_SOCKET_DIRS = ('/run/docker', '/run/containerd')
PROVISION_TRIGGER_UNIT = 'aieh-provision.path'
# the inspect entry of a provisioned instance, beside the contract's P1-P12
PROVISIONING_PROPERTY = 'provisioning (F-04.1)'

# The guest-side wait for RESULT.json, run as agent: the root step writes it last, by a
# rename, so the inotify event on its directory is the completion signal. Between
# events the loop wakes at most every 10 s only to re-check the unit for a failure that
# left no result, under the stated ceiling.
RESULT_WAIT_SCRIPT = r'''import ctypes, os, select, subprocess, sys, time
path, unit, ceiling = sys.argv[1], sys.argv[2], float(sys.argv[3])
libc = ctypes.CDLL(None, use_errno=True)
fd = libc.inotify_init1(os.O_CLOEXEC)
if fd < 0:
    print('inotify_init1 failed', ctypes.get_errno()); sys.exit(3)
if libc.inotify_add_watch(fd, os.path.dirname(path).encode(), 0x80 | 0x100 | 0x8) < 0:
    print('inotify_add_watch failed', ctypes.get_errno()); sys.exit(3)
deadline = time.monotonic() + ceiling
while True:
    if os.path.exists(path):
        print('result present'); sys.exit(0)
    state = subprocess.run(['systemctl', 'show', '-p', 'ActiveState', '--value', unit],
                           capture_output=True, text=True).stdout.strip()
    if state == 'failed' and not os.path.exists(path):
        print('unit failed without a result'); sys.exit(4)
    left = deadline - time.monotonic()
    if left <= 0:
        print('ceiling reached; unit', state); sys.exit(5)
    ready, _, _ = select.select([fd], [], [], min(10.0, left))
    if ready:
        os.read(fd, 65536)
'''

SOCKET_CONNECT_PROBE = r'''import errno, socket, sys
for path in sys.argv[1:]:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect(path)
        print(path, 'CONNECTED')
    except OSError as exc:
        print(path, errno.errorcode.get(exc.errno, exc.errno))
    finally:
        s.close()
'''


def provisioning_config(profile):
    conf = profile.get('provisioning')
    if not isinstance(conf, dict) or not all(isinstance(conf.get(k), dict) for k in
                                             ('upload', 'root_step', 'facts', 'moby', 'image')):
        raise Refused('REFUSED', f'profile {profile.get("name")} declares no provisioning')
    return conf


def guest_moby_socket_paths(profile, record):
    """The provisioned instance's own declared Moby sockets, with their /var/run aliases
    (Debian's /var/run is a link to /run); empty for any other instance."""
    if not record.get('provisioning'):
        return set()
    paths = set()
    for entry in ((profile.get('provisioning') or {}).get('moby') or {}).get('sockets') or []:
        path = entry.get('path', '')
        paths.add(path)
        if path.startswith('/run/'):
            paths.add('/var' + path)
    return paths


def build_provision_manifest(ctx):
    """The seeded manifest of a provisioned instance, from the committed lock and the
    re-verified host stage (provision-fetch): every file to upload with its role, size
    and sha256, the packages, the image (locked config digest, the archive's tags, the
    local immutable tag) and the declared daemon.json. Deterministic for one stage."""
    conf = provisioning_config(ctx.profile)
    lock, lock_rel, lock_sha = provision_lock(ctx)
    items = provision_items(lock)
    image = provision_image(lock)
    staged_dir = Path(ctx.state_dir) / 'provision' / lock_sha
    _plain_dir(staged_dir)
    if not staged_dir.is_dir():
        raise Refused('REFUSED', f'{staged_dir}: no stage for this lock; run provision-fetch')
    verified = verify_staged(staged_dir, lock_sha, items, image)
    staged = json.loads((staged_dir / PROVISION_STAGED_FILE).read_text(encoding='utf-8'))
    by_path = {f['path']: f for f in staged['files']}
    files, sources = [], {}
    for rel, _url, size, sha256, role in items:
        if role not in ('deb', 'release-binary'):
            continue
        name = rel.rsplit('/', 1)[-1]
        files.append({'name': name, 'role': role, 'size': size, 'sha256': sha256})
        sources[name] = staged_dir / rel
    tar = by_path['image/' + PROVISION_IMAGE_ARCHIVE]
    files.insert(len([f for f in files if f['role'] == 'deb']),
                 {'name': PROVISION_IMAGE_ARCHIVE, 'role': 'image-archive',
                  'size': tar['size'], 'sha256': tar['sha256']})
    sources[PROVISION_IMAGE_ARCHIVE] = staged_dir / 'image' / PROVISION_IMAGE_ARCHIVE
    repo_tags = verified['image'].get('repo_tags') or []
    if not isinstance(repo_tags, list) or not repo_tags or \
            not all(isinstance(t, str) and t for t in repo_tags):
        raise Refused('REFUSED', 'the staged image archive names no tag; docker load would '
                      'leave the image untagged')
    moby = conf['moby']
    manifest = {
        'schema': PROVISION_MANIFEST_SCHEMA,
        'profile': ctx.profile['name'],
        'lock': {'path': lock_rel, 'sha256': lock_sha},
        'lock_sha256': lock_sha,
        'files': files,
        'packages': [{'name': p['name'], 'version': p['version'], 'file': p['filename']}
                     for p in (lock.get('debian') or {}).get('packages') or []],
        'image': {'archive': PROVISION_IMAGE_ARCHIVE, 'id': image['config_digest'],
                  'index_digest': image['index_digest'],
                  'manifest_digest': image['manifest_digest'],
                  'archive_repo_tags': repo_tags,
                  'local_tag': conf['image']['local_tag']},
        'docker': {'server_version': moby['server_version'], 'daemon_json': moby['daemon_json']},
    }
    data = (json.dumps(manifest, indent=1, sort_keys=True) + '\n').encode('ascii')
    digest = hashlib.sha256(data).hexdigest()
    return {'bytes': data, 'sha256': digest, 'manifest': manifest, 'sources': sources,
            'record': {'manifest_sha256': digest, 'lock_sha256': lock_sha,
                       'image_id': image['config_digest'],
                       'local_tag': conf['image']['local_tag'],
                       'files': len(files), 'bytes': sum(f['size'] for f in files),
                       'staged_dir': posix(staged_dir), 'stage_verify_seconds':
                       verified['seconds']}}


def provisioning_probes(conf):
    """Agent-side probes of a provisioned instance (inspect). Root-only facts come from
    the facts unit's report, read as agent; nothing here needs or gains privilege."""
    moby, root, facts = conf['moby'], conf['root_step'], conf['facts']
    sockets = ' '.join(f"'{s['path']}'" for s in moby.get('sockets') or [])
    leftovers = ' '.join(f"'{p}'" for p in (conf['upload']['guest_dir'], root['staging']))
    units = ' '.join([PROVISION_TRIGGER_UNIT, root['service'], facts['service']])
    return [
        ('boot_id', 'cat /proc/sys/kernel/random/boot_id'),
        # the facts unit writes at every boot; wait until the boot has finished first
        ('moby_facts', 'timeout 300 systemctl is-system-running --wait >/dev/null 2>&1; '
                       f"cat '{facts['path']}'"),
        ('provision_result', f"cat '{root['result']}'"),
        ('moby_sockets', f"stat -c '%n|%U|%G|%a|%F' -- {sockets}"),
        ('moby_agent_connect', f"timeout 30 python3 - {sockets} <<'PYEOF'\n" +
         SOCKET_CONNECT_PROBE + 'PYEOF'),
        ('docker_as_agent', 'timeout 30 docker info'),
        ('tcp_listeners', 'ss -ltnH'),
        ('agent_docker_group', 'id -nG agent; getent group docker'),
        ('provision_leftovers', f'for p in {leftovers}; do if [ -e "$p" ] || [ -L "$p" ]; '
                                'then echo "present $p"; else echo "absent $p"; fi; done'),
        ('provision_units', f'for u in {units}; do printf "%s %s %s\\n" "$u" '
                            '"$(systemctl is-enabled "$u" 2>&1 | head -n1)" '
                            '"$(systemctl is-active "$u" 2>&1 | head -n1)"; done'),
    ]


def _probe_json(obs, key):
    text = ((obs.get('guest') or {}).get(key) or {}).get('out')
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def _listener_addresses(lines):
    """'LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:*' -> the local address field."""
    out = []
    for line in lines or []:
        parts = line.split()
        if len(parts) >= 4:
            out.append(parts[3])
    return sorted(set(out))


def moby_p6_checks(profile, obs):
    """profiles P6 (amended 2026-11-06) for a provisioned instance: the guest's own Moby
    sockets are the declared ones, root-owned with no access for others, and agent can
    reach none of them."""
    g = obs.get('guest', {})
    out_text = lambda key: (g.get(key) or {}).get('out', '')      # noqa: E731
    moby = (profile.get('provisioning') or {}).get('moby') or {}
    declared = [f"{s['path']}|{s['owner']}|{s['group']}|{s['mode']}|socket"
                for s in moby.get('sockets') or []]
    got = out_text('moby_sockets').splitlines()
    facts = _probe_json(obs, 'moby_facts') or {}
    found = facts.get('sockets') if isinstance(facts.get('sockets'), list) else None
    open_to_others = None if found is None else [
        s for s in found if s.get('state') == 'socket' and (
            s.get('owner') != 'root' or s.get('group') not in ('root', 'docker') or
            int(str(s.get('mode', '7')), 8) & 0o007)]
    connect = dict(line.rsplit(' ', 1) for line in out_text('moby_agent_connect').splitlines()
                   if ' ' in line)
    cli = g.get('docker_as_agent') or {}
    return [
        check('guest Moby sockets', {'declared': declared, 'others': 'root-owned, group root '
                                     'or docker, no access for others'},
              {'stat': got, 'root_view': found, 'open_to_others': open_to_others},
              f"guest: stat -c '%n|%U|%G|%a|%F' (agent); the facts report's sockets under "
              f'{list(MOBY_SOCKET_DIRS)} (root)',
              None if found is None else got == declared and not open_to_others),
        check('agent cannot reach Moby', 'connect EACCES on every declared socket; docker info '
              'refused', {'connect': connect, 'docker_info_rc': cli.get('rc'),
                          'docker_info': (cli.get('out') or '').strip().splitlines()[-1:]},
              'guest, as agent: AF_UNIX connect; docker info',
              bool(connect) and len(connect) == len(declared) and
              all(v == 'EACCES' for v in connect.values()) and cli.get('rc') not in (0, None)
              and 'permission denied' in (cli.get('out') or '').lower()),
    ]


def moby_p7_checks(obs):
    """profiles P7 for a provisioned instance: no TCP listener of Moby (unix socket only),
    and none appeared since the boot-time report."""
    g = obs.get('guest', {})
    facts = _probe_json(obs, 'moby_facts') or {}
    root_lines = facts.get('tcp_listeners') if isinstance(facts.get('tcp_listeners'), list) else None
    moby_owned = None if root_lines is None else [
        line for line in root_lines if any(f'(("{p}' in line or f'"{p}"' in line
                                           for p in MOBY_PROCESSES)]
    agent_view = _listener_addresses((g.get('tcp_listeners') or {}).get('out', '').splitlines())
    root_view = None if root_lines is None else _listener_addresses(root_lines)
    return [check('guest TCP listeners (Moby)',
                  'none owned by dockerd, containerd or docker-proxy; none new since boot',
                  {'agent_view': agent_view, 'boot_root_view': root_view,
                   'moby_owned': moby_owned},
                  'guest: ss -ltnH (agent, now); ss -ltnpH in the facts report (root, at boot)',
                  None if root_lines is None else not moby_owned and agent_view == root_view)]


def moby_p8_checks(obs):
    g = obs.get('guest', {})
    lines = ((g.get('agent_docker_group') or {}).get('out') or '').splitlines()
    groups = lines[0].split() if lines else []
    docker_group = lines[1] if len(lines) > 1 else ''
    members = docker_group.split(':')[3].split(',') if docker_group.count(':') >= 3 else None
    return [check('agent not in group docker', {'agent_groups': 'without docker',
                                                 'docker_members': 'without agent'},
                  {'agent_groups': groups, 'docker_group': docker_group},
                  'guest: id -nG agent; getent group docker',
                  bool(groups) and 'docker' not in groups and members is not None and
                  'agent' not in members)]


def provisioning_property(profile, record, obs):
    """The provisioned instance's Moby state against the profile and the lock (F-04.1):
    an inspect entry beside P1-P12, not a contract property."""
    g = obs.get('guest', {})
    out_text = lambda key: (g.get(key) or {}).get('out', '')      # noqa: E731
    conf = profile.get('provisioning') or {}
    moby, image_conf = conf.get('moby') or {}, conf.get('image') or {}
    prov = record.get('provisioning') or {}
    result = _probe_json(obs, 'provision_result') or {}
    facts = _probe_json(obs, 'moby_facts') or {}
    info = facts.get('info') if isinstance(facts.get('info'), dict) else {}
    version = facts.get('version') if isinstance(facts.get('version'), dict) else {}
    image = facts.get('image') if isinstance(facts.get('image'), dict) else {}
    images = facts.get('images') if isinstance(facts.get('images'), list) else None
    leftovers = out_text('provision_leftovers').splitlines()
    want_left = [f"absent {conf.get('upload', {}).get('guest_dir')}",
                 f"absent {conf.get('root_step', {}).get('staging')}"]
    units = {line.split()[0]: line.split()[1:] for line in out_text('provision_units').splitlines()
             if len(line.split()) >= 3}
    trigger = units.get(PROVISION_TRIGGER_UNIT, [])
    service = units.get((conf.get('root_step') or {}).get('service'), [])
    facts_unit = units.get((conf.get('facts') or {}).get('service'), [])
    security = info.get('SecurityOptions') if isinstance(info.get('SecurityOptions'), list) else []
    modules = facts.get('modules') if isinstance(facts.get('modules'), dict) else {}
    checks = [
        check('root step result', {'result': 'provisioned', 'manifest_sha256':
                                   prov.get('manifest_sha256')},
              {'result': result.get('result'), 'failed_step': result.get('failed_step'),
               'manifest_sha256': (result.get('manifest') or {}).get('sha256'),
               'upload_present': result.get('upload_present'),
               'staging_present': result.get('staging_present')},
              f"guest: {(conf.get('root_step') or {}).get('result')} (root-owned, read as agent)",
              result.get('schema') == PROVISION_RESULT_SCHEMA and
              result.get('result') == 'provisioned' and result.get('failed_step') is None and
              (result.get('manifest') or {}).get('sha256') == prov.get('manifest_sha256') and
              result.get('upload_present') is False and result.get('staging_present') is False),
        check('facts report of this boot', 'written by root at this boot',
              {'schema_ok': facts.get('schema') == MOBY_FACTS_SCHEMA,
               'same_boot': bool(facts) and facts.get('boot_id') == out_text('boot_id').strip()},
              f"guest: {(conf.get('facts') or {}).get('path')} and the kernel boot_id",
              facts.get('schema') == MOBY_FACTS_SCHEMA and
              facts.get('boot_id') == out_text('boot_id').strip()),
        check('Moby server version', moby.get('server_version'),
              (version.get('Server') or {}).get('Version'), 'facts: docker version (root)',
              (version.get('Server') or {}).get('Version') == moby.get('server_version')),
        check('Moby daemon', {'DockerRootDir': moby.get('data_root'),
                              'Driver': moby.get('storage_driver'),
                              'DefaultRuntime': moby.get('default_runtime'),
                              'SecurityOptions': f"including {moby.get('required_security_options')}",
                              'daemon.json': moby.get('daemon_json')},
              {'DockerRootDir': info.get('DockerRootDir'), 'Driver': info.get('Driver'),
               'DefaultRuntime': info.get('DefaultRuntime'), 'SecurityOptions': security,
               'daemon.json': facts.get('daemon_json')},
              'facts: docker info, /etc/docker/daemon.json (root)',
              bool(info) and info.get('DockerRootDir') == moby.get('data_root') and
              info.get('Driver') == moby.get('storage_driver') and
              info.get('DefaultRuntime') == moby.get('default_runtime') and
              set(moby.get('required_security_options') or []) <= set(security) and
              facts.get('daemon_json') == moby.get('daemon_json')),
        check('image', {'Id': prov.get('image_id'), 'RepoTags': [image_conf.get('local_tag')],
                        'store': 'that image only'},
              {'Id': image.get('Id'), 'RepoTags': image.get('RepoTags'),
               'RepoDigests': image.get('RepoDigests'),
               'store': None if images is None else sorted(
                   f"{i.get('ID')} {i.get('Repository')}:{i.get('Tag')}" for i in images)},
              'facts: docker image inspect, docker image ls --all (root)',
              image.get('Id') == prov.get('image_id') and image.get('RepoTags') == [image_conf.get('local_tag')] and
              images is not None and [i.get('ID') for i in images] == [prov.get('image_id')]),
        check('containers', [], facts.get('containers'), 'facts: docker ps --all (root, at boot)',
              facts.get('containers') == []),
        check('kernel modules for Moby', 'overlay loaded', modules,
              'facts: /proc/modules, /proc/filesystems (root)',
              bool(modules) and ('overlay' in (modules.get('loaded') or []) or
                                 modules.get('overlay_filesystem') is True)),
        check('upload and staging removed', want_left, leftovers, 'guest: test -e, test -L',
              leftovers == want_left),
        check('root step disabled', {PROVISION_TRIGGER_UNIT: 'not enabled, inactive',
                                     'service': 'not enabled, inactive',
                                     'facts unit': 'enabled'},
              units, 'guest: systemctl is-enabled, is-active',
              bool(trigger) and trigger[0] in ('not-found', 'disabled') and
              trigger[1] == 'inactive' and bool(service) and
              service[0] in ('static', 'disabled', 'not-found') and service[1] in
              ('inactive', 'failed') and bool(facts_unit) and facts_unit[0] == 'enabled'),
    ]
    out = prop('provisioning', checks, formal='F-04.1 slice (b)', note=(
        'Not a contract property: the provisioned instance\'s Moby and image state against '
        'the profile\'s provisioning block and the provision lock. Root-only facts come '
        'from the boot-time report of aieh-docker-facts.service, read as agent.'))
    out['property'] = PROVISIONING_PROPERTY
    return out


CHECK_CLASSES.update({
    ('profiles P6', 'guest Moby sockets'): (STABLE, None),
    ('profiles P6', 'agent cannot reach Moby'): (STABLE, None),
    ('profiles P7', 'guest TCP listeners (Moby)'): (STABLE, None),
    ('profiles P8', 'agent not in group docker'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'root step result'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'facts report of this boot'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'Moby server version'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'Moby daemon'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'image'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'containers'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'kernel modules for Moby'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'upload and staging removed'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'root step disabled'): (STABLE, None),
})


def _guest_states(ssh, paths):
    script = ''.join(f"p='{p}'; if [ -L \"$p\" ]; then echo \"symlink $p\"; elif [ -e \"$p\" ]; "
                     f'then echo "present $p"; else echo "absent $p"; fi\n' for p in paths)
    result = ssh.run(['bash', '-s'], input_text=script, timeout=120)
    if result.returncode != 0:
        raise Refused('PROVISION', f'guest state check failed: {result.stderr.strip()}')
    return dict(reversed(line.split(' ', 1)) for line in result.stdout.splitlines() if ' ' in line)


def provision(ctx, name):
    """provision (F-04.1b): transfer the stage of a --provision instance and wait for the
    seeded root step. Refuses unless the instance was created with --provision, the stage
    still gives the manifest seeded at create, the trigger is armed, and neither the upload
    nor a result exists yet. Every file is checked in the guest after the transfer."""
    t0 = time.time()
    idir, record = running_instance(ctx, name)
    prov = record.get('provisioning')
    if not prov:
        raise Refused('REFUSED', f'{name} was not created with --provision; its seed holds no '
                      'manifest and its root step is inert')
    conf = provisioning_config(ctx.profile)
    up, root = conf['upload'], conf['root_step']
    manifest = build_provision_manifest(ctx)
    if manifest['sha256'] != prov.get('manifest_sha256'):
        raise Refused('STAGED_MISMATCH', f'the stage now gives manifest {manifest["sha256"]}; '
                      f'{name} was seeded with {prov.get("manifest_sha256")}')
    files = manifest['manifest']['files']
    total = sum(f['size'] for f in files)
    if len(files) > up['max_files'] or total > up['max_bytes'] or \
            any(f['role'] not in up['roles'] for f in files):
        raise Refused('BOUNDS', f'{len(files)} files, {total} bytes exceed provisioning.upload '
                      f'({up["max_files"]} files, {up["max_bytes"]} bytes, roles {up["roles"]})')
    ssh = Ssh(ctx.profile, idir, record['ports']['ssh'])
    guest_dir, result_path = up['guest_dir'], root['result']
    states = _guest_states(ssh, [guest_dir, result_path, root['staging']])
    armed = ssh.run(['systemctl', 'is-active', PROVISION_TRIGGER_UNIT], timeout=60).stdout.strip()
    if any(v != 'absent' for v in states.values()) or armed != 'active':
        raise Refused('REFUSED', f'{name}: not ready to provision (guest paths {states}, '
                      f'trigger {armed!r}); provisioning is single use: recreate --provision',
                      {'paths': states, 'trigger': armed})
    work = idir / 'provision'
    work.mkdir(exist_ok=True)
    out = {'operation': 'provision', 'labels': labels(ctx.profile), 'instance': name,
           'manifest_sha256': manifest['sha256'], 'lock_sha256': prov.get('lock_sha256'),
           'files': [dict(f) for f in files], 'bytes': total}
    commands = [f'mkdir {sftp_quote(guest_dir)}'] + [
        f'put {sftp_quote(manifest["sources"][f["name"]])} {sftp_quote(guest_dir + "/" + f["name"])}'
        for f in files]
    log(f'provision: uploading {len(files)} files, {total} bytes')
    t1 = time.time()
    transfer = Sftp(ssh).batch(commands, work, timeout=up['timeout_s'])
    upload_s = time.time() - t1
    out['upload'] = {'rc': transfer['rc'], 'seconds': round(upload_s, 1),
                     'mib_per_s': round(total / (1 << 20) / upload_s, 1) if upload_s else None,
                     'stderr': transfer['stderr'][-1000:]}
    if transfer['rc'] != 0:
        out['result'] = 'upload-failed'
        out['record'] = write_record(idir, 'provision', out)
        raise Refused('PROVISION', f'sftp upload failed: {transfer["stderr"][-500:]}', out)
    t2 = time.time()
    names = ' '.join(f"'{f['name']}'" for f in files)
    check_script = (f"cd '{guest_dir}' && for f in {names}; do printf '%s %s\\n' \"$f\" "
                    "\"$(stat -c %s -- \"$f\")\"; done && sha256sum -- " + names + '\n')
    landed = ssh.run(['bash', '-s'], input_text=check_script, timeout=up['timeout_s'])
    sizes, digests = {}, {}
    for line in landed.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            sizes[parts[0]] = int(parts[1])
        elif len(parts) == 2 and re.fullmatch(r'[0-9a-f]{64}', parts[0]):
            digests[parts[1]] = parts[0]
    mismatched = [f['name'] for f in files if sizes.get(f['name']) != f['size'] or
                  digests.get(f['name']) != f['sha256']]
    out['guest_check'] = {'rc': landed.returncode, 'seconds': round(time.time() - t2, 1),
                          'mismatched': mismatched}
    if landed.returncode != 0 or mismatched:
        out['result'] = 'transfer-mismatch'
        out['record'] = write_record(idir, 'provision', out)
        raise Refused('HASH_MISMATCH', f'guest copies differ: {mismatched}', out)
    ready = ssh.run(['bash', '-c', f"set -C; : > '{guest_dir}/{up['ready_marker']}'"], timeout=60)
    if ready.returncode != 0:
        raise Refused('PROVISION', f'READY marker not created: {ready.stderr.strip()}')
    t3 = time.time()
    log(f'provision: READY; waiting for {result_path} (ceiling {root["timeout_s"]} s)')
    waited = ssh.run(['python3', '-', result_path, root['service'], str(root['timeout_s'])],
                     input_text=RESULT_WAIT_SCRIPT, timeout=root['timeout_s'] + 120)
    out['root_step_wait'] = {'rc': waited.returncode, 'seconds': round(time.time() - t3, 1),
                             'out': waited.stdout.strip()[-500:],
                             'stderr': waited.stderr.strip()[-500:]}
    fetched, result = None, None
    if waited.returncode == 0:
        fetched = work / f'RESULT-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")}.json'
        get = Sftp(ssh).batch([f'get {sftp_quote(result_path)} {sftp_quote(fetched)}'], work)
        if get['rc'] == 0 and fetched.is_file():
            result = json.loads(fetched.read_text(encoding='utf-8'))
    out['result_file'] = str(fetched) if fetched else None
    out['root_step'] = result
    image = (manifest['manifest'].get('image') or {})
    steps = {s.get('step'): s for s in (result or {}).get('steps') or []}
    tagged = ((steps.get('tag') or {}).get('detail') or {}).get('image') or {}
    verdict = {
        'schema': (result or {}).get('schema') == PROVISION_RESULT_SCHEMA,
        'provisioned': (result or {}).get('result') == 'provisioned',
        'manifest': ((result or {}).get('manifest') or {}).get('sha256') == manifest['sha256'],
        'all_files_verified': [f.get('name') for f in ((steps.get('verify') or {}).get('detail')
                                                     or {}).get('files') or [] if f.get('match')]
        == [f['name'] for f in files],
        'image_id': tagged.get('Id') == image.get('id'),
        'tags': tagged.get('RepoTags') == [image.get('local_tag')],
        'run': ((steps.get('run') or {}).get('detail') or {}).get('rc') == 0,
        'cleanup': (result or {}).get('upload_present') is False and
        (result or {}).get('staging_present') is False,
        'trigger_removed': ((result or {}).get('trigger') or {}).get('path_unit_file') == 'absent',
    }
    out['checks'] = verdict
    out['timings'] = {'upload_s': out['upload']['seconds'],
                      'guest_check_s': out['guest_check']['seconds'],
                      'root_step_s': (result or {}).get('seconds'),
                      'wait_s': out['root_step_wait']['seconds'],
                      'steps_s': {k: v.get('seconds') for k, v in steps.items()},
                      'total_s': round(time.time() - t0, 1)}
    out['result'] = 'provisioned' if all(verdict.values()) else 'failed'
    out['seconds'] = round(time.time() - t0, 1)
    out['record'] = write_record(idir, 'provision', out)
    if out['result'] != 'provisioned':
        raise Refused('PROVISION_FAILED', f'{name}: root step '
                      f'{(result or {}).get("result")!r} at step '
                      f'{(result or {}).get("failed_step")!r}: {(result or {}).get("error")}; '
                      f'checks {verdict}', out)
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
    p = sub.add_parser('canaries')
    p.add_argument('--out', required=True, help='a new directory outside the checkout')
    p = sub.add_parser('netprobe-listen', help=argparse.SUPPRESS)
    p.add_argument('--log', required=True)
    for op in ('preflight', 'create', 'start', 'stop', 'destroy', 'recreate', 'inspect', 'exec',
               'exchange-push', 'exchange-pull', 'check-surfaces', 'netprobe', 'smoke',
               'provision-fetch', 'provision'):
        p = sub.add_parser(op)
        p.add_argument('--profile', required=True, help='profile directory (never defaulted)')
        p.add_argument('--state-dir', required=True, help='the Owner-named state directory')
        if op not in ('preflight', 'provision-fetch'):
            p.add_argument('--name', required=True)
        if op in ('create', 'inspect', 'recreate'):
            p.add_argument('--canaries', help='a canary set written by the canaries operation')
        if op in ('check-surfaces', 'smoke'):
            p.add_argument('--canaries', required=True,
                           help='a canary set written by the canaries operation')
        if op == 'smoke':
            p.add_argument('--durable', action='append', required=True,
                           help='a durable root to inventory before and after each destroy and '
                                'recreate (repeatable; stands for Owner data)')
            p.add_argument('--out', help='also write the smoke record to this new file')
        if op == 'exchange-push':
            p.add_argument('--repo', required=True, help='the repository to read the branch from')
            p.add_argument('--ref', required=True, help='one local branch')
            p.add_argument('--bundle-name', help='file name in the guest exchange directory')
        if op == 'exchange-pull':
            p.add_argument('--file', required=True, help='file name in the guest exchange directory')
        if op in ('create', 'recreate', 'smoke'):
            p.add_argument('--provision', action='store_true',
                           help='F-04.1: seed the provisioning manifest of the verified host '
                                'stage (smoke: and run provision after create and recreate)')
        if op in ('create', 'start', 'recreate', 'netprobe', 'smoke'):
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
        if op == 'netprobe-listen':
            return netprobe_listen(args.log)
        ctx = Context(args.profile, args.state_dir)
        canaries = load_canaries(args.canaries) \
            if op in ('create', 'inspect', 'recreate') and args.canaries else None
        if op == 'exec':
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            return exec_command(ctx, args.name, command)
        if op == 'preflight':
            result = preflight(ctx)
        elif op == 'provision-fetch':
            result = provision_fetch(ctx)
        elif op == 'create':
            result = create(ctx, args.name, args.ready_timeout, canaries, provision=True) \
                if args.provision else create(ctx, args.name, args.ready_timeout, canaries)
        elif op == 'provision':
            result = provision(ctx, args.name)
        elif op == 'start':
            result = start(ctx, args.name, args.ready_timeout)
        elif op == 'stop':
            result = stop(ctx, args.name, args.force)
        elif op == 'destroy':
            result = destroy(ctx, args.name)
        elif op == 'recreate':
            result = recreate(ctx, args.name, args.ready_timeout, canaries, args.provision)
        elif op == 'exchange-push':
            result = exchange_push(ctx, args.name, args.repo, args.ref, args.bundle_name)
        elif op == 'exchange-pull':
            result = exchange_pull(ctx, args.name, args.file)
        elif op == 'check-surfaces':
            result = check_surfaces(ctx, args.name, args.canaries)
        elif op == 'netprobe':
            result = netprobe(ctx, args.name, args.ready_timeout)
        elif op == 'smoke':
            result = smoke(ctx, args.name, args.canaries, args.durable, args.out,
                           args.ready_timeout, args.provision)
        else:
            result = inspect(ctx, args.name, canaries)
    except Refused as exc:
        print(f'REFUSED {exc.code}: {exc}', file=sys.stderr)
        print(json.dumps({'result': 'refused', 'code': exc.code, 'message': str(exc),
                          'detail': exc.detail}, indent=2, sort_keys=True, default=str))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if result.get('operation') in ('check-surfaces', 'netprobe', 'smoke'):
        return 0 if result.get('result') == 'PASS' else 1
    failed = result.get('result') in ('unavailable', 'not-ready') or \
        'FAIL' in (result.get('verdicts') or {}).values() or \
        (result.get('compatibility') or {}).get('verdict') == 'FAIL' or \
        result.get('create', {}).get('result') == 'not-ready'
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
